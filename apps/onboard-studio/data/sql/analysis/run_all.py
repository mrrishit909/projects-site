"""Run every analysis query and reconcile it with the independent sources (P02-ART-04).

Usage:
  DATABASE_URL=<snapshot db> GOLDEN_DATABASE_URL=<golden db> ../../.venv/bin/python data/sql/analysis/run_all.py [--json out.json]

Prepare both databases first with prepare_snapshot.py (and ``--golden``). Order: 00 (views), 01..08 on the snapshot,
09 on the golden database. Exit code 0 only if every query ran and every reconciliation holds:
  (columns: sql_view = this directory's SQL; second_source = reference_metrics.sql where it exists, else the domain or the manifest;
  third_source = the Python domain where a second source exists.)
  A. golden case: business/calendar/paused/active hours from 09 (this SQL) == data/sql/reference_metrics.sql == the Python domain;
  B. snapshot: population means and counts from the view == reference_metrics.sql == the domain, and every completed case's
     calendar/business/paused/active hours (712 cases) equal the domain's for that case, to 4 decimals;
  C. group metrics (version, segment, region), 18 month-end backlog cutoffs, per-step waiting and rework / first-pass equal the domain;
  D. rejected cases, approvals and flagged waits equal data/injection-manifest.json.
"""
from __future__ import annotations

import json
import os
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(HERE)]

from onboard_studio.metrics import compute_metrics, group_metrics  # noqa: E402
from onboard_studio.pipeline import run_pipeline  # noqa: E402
from prepare_snapshot import snapshot_inputs  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
D4, D6 = Decimal("0.0001"), Decimal("0.000001")


def fmt(v) -> str:
    return "" if v is None else format(v, "f") if isinstance(v, Decimal) else str(v)


def table(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def q4(x) -> str:
    return None if x is None else format(Decimal(x).quantize(D4, ROUND_HALF_UP), "f")


def q6(x) -> str:
    return None if x is None else format(Decimal(x).quantize(D6, ROUND_HALF_UP), "f")


class Recon:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.ok = True

    def add(self, check: str, a, b, c=None) -> None:
        vals = [a, b] + ([c] if c is not None else [])
        eq = all(str(v) == str(a) for v in vals)
        self.ok &= eq
        self.rows.append({"check": check, "sql_view": a, "second_source": b,
                          "third_source": "" if c is None else c, "equal": eq})


def main(argv: list[str]) -> int:
    url, gurl = os.environ["DATABASE_URL"], os.environ.get("GOLDEN_DATABASE_URL")
    results: dict[str, list[dict]] = {}
    rec = Recon()
    with psycopg.connect(url, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as conn:
        conn.execute((HERE / "00_case_facts.sql").read_text())
        for f in sorted(HERE.glob("0[1-8]_*.sql")):
            results[f.stem] = conn.execute(f.read_text()).fetchall()
            print(f"### {f.name}\n\n{table(results[f.stem])}\n")
        ref = dict(conn.execute(REFERENCE.read_text()).fetchone())
        view = dict(conn.execute("""
            SELECT count(completed_at)::int AS completed_eligible_cases,
                   round(avg(calendar_s) / 3600, 4)::text AS calendar_cycle_time_hours,
                   round(avg(business_s) / 3600, 4)::text AS business_cycle_time_hours,
                   round(avg(paused_s) / 3600, 4)::text AS paused_time_hours,
                   round(avg(paused_business_s) / 3600, 4)::text AS paused_business_overlap_hours,
                   round(avg(active_s) / 3600, 4)::text AS active_elapsed_hours,
                   count(*) FILTER (WHERE within_sla)::int AS within_sla_cases
              FROM os_case_facts""").fetchone())
        cases_sql = {r["case_id"]: r for r in conn.execute(
            "SELECT case_id, calendar_s, business_s, paused_s, active_s FROM os_case_facts WHERE completed_at IS NOT NULL")}

        # ---- Python domain over the same snapshot files (no database) --------------------------------------
        inputs = snapshot_inputs()
        cutoffs = [r["cutoff"].replace("T00:00Z", "T00:00:00Z") for r in results["07_backlog_month_ends"]]
        res = run_pipeline(inputs, cutoffs=cutoffs)
        py = res.metrics
        for k in view:
            rec.add(f"B snapshot population: {k}", view[k], ref[k], py[k])
        # per-case: every completed case, all four durations, domain vs SQL
        bad = 0
        for cid, r in cases_sql.items():
            m = compute_metrics(res.population.subset({cid}))
            if (m["calendar_cycle_time_hours"], m["business_cycle_time_hours"], m["paused_time_hours"],
                    m["active_elapsed_hours"]) != tuple(q4(r[k] / 3600) for k in ("calendar_s", "business_s", "paused_s", "active_s")):
                bad += 1
        rec.add("B per-case calendar/business/paused/active hours, cases differing (domain, 712 cases)", bad, 0)
        rec.add("B completed cases compared per case", len(cases_sql), 712)

        # ---- groups -------------------------------------------------------------------------------------
        for by, col in (("workflow_version", "workflow_version_id"), ("segment", "segment"), ("region", "region")):
            g = group_metrics(res.population, by)
            if by == "workflow_version":
                g_ver = g
            sql = conn.execute(f"""
                SELECT {col} AS g, count(completed_at)::int AS n, round(avg(active_s) / 3600, 4)::text AS active,
                       round(count(*) FILTER (WHERE within_sla)::numeric / NULLIF(count(within_sla), 0), 6)::text AS sla,
                       sum(handoffs)::int AS handoffs, round(avg(paused_s) / 3600, 4)::text AS paused
                  FROM os_case_facts GROUP BY 1 ORDER BY 1""").fetchall()
            for r in sql:
                m = g[r["g"]]
                rec.add(f"C {by}={r['g']}: n / active / SLA / handoffs / paused",
                        f"{r['n']} / {r['active']} / {r['sla']} / {r['handoffs']} / {r['paused']}",
                        f"{m['completed_eligible_cases']} / {m['active_elapsed_hours']} / {m['sla_attainment']} / "
                        f"{m['handoff_count']} / {m['paused_time_hours']}")
        for r in results["02_version_comparison_comparable_window"]:
            if r["window"].startswith("all"):
                m = g_ver[r["version"]]
                rec.add(f"C 02 {r['version']} (all window): rework / first-pass vs domain",
                        f"{r['rework_rate']} / {r['first_pass_rate']}", f"{m['rework_rate']} / {m['first_pass_approval']}")
        # backlog
        sql_bl = {r["cutoff"].replace("T00:00Z", "T00:00:00Z"): r["open_at_end"] for r in results["07_backlog_month_ends"]}
        rec.add("C backlog at 18 month-end cutoffs (sum of open_at_end)", sum(sql_bl.values()),
                sum(py["open_backlog_at_cutoff"].values()))
        rec.add("C backlog per cutoff, cutoffs differing", sum(1 for k, v in sql_bl.items() if py["open_backlog_at_cutoff"][k] != v), 0)
        # step waiting per step_definition
        steps = conn.execute("""
            SELECT si.step_definition_id AS sd, round(avg(os_business_seconds(si.ready_at, si.started_at, f.calendar_id)) / 3600, 4)::text AS w
              FROM step_instances si JOIN os_case_facts f USING (case_id)
             WHERE si.started_at IS NOT NULL AND si.ready_at IS NOT NULL GROUP BY 1 ORDER BY 1""").fetchall()
        rec.add("C step waiting per step_definition (10), differing",
                sum(1 for r in steps if py["step_waiting_time_hours"][r["sd"]] != r["w"]), 0)
        # rework / first pass
        r05 = {(r["lens"], r["segment"], r["document_type"]): r for r in results["05_rework_first_pass_by_segment"]}
        tot = r05[("segment", "ALL", "ALL")]
        rec.add("C rework rate / first-pass approval (all cases)", f"{tot['rework_rate']} / {tot['first_pass_rate']}",
                f"{py['rework_rate']} / {py['first_pass_approval']}")

        # ---- rejections and flags vs the injection manifest ----------------------------------------------
        inj = {i["id"]: i for i in json.loads((ROOT / "data" / "injection-manifest.json").read_text())["injections"]}
        r08 = {r["reason"]: r for r in results["08_flags_and_rejections_by_reason"]}
        rec.add("D INJ-01 MISSING_REQUIRED_DOCUMENT cases", r08["MISSING_REQUIRED_DOCUMENT"]["ids"], ", ".join(sorted(inj["INJ-01"]["record_ids"])))
        rec.add("D INJ-02 DECISION_CONFLICT approvals", r08["DECISION_CONFLICT"]["ids"], ", ".join(sorted(inj["INJ-02"]["record_ids"])))
        rec.add("D INJ-03 PAUSE_OUTSIDE_WORKING_INTERVAL waits", r08["PAUSE_OUTSIDE_WORKING_INTERVAL"]["ids"], ", ".join(sorted(inj["INJ-03"]["record_ids"])))
        rec.add("D INJ-09 PAUSE_REASON_NOT_CONFIGURED cases", r08["PAUSE_REASON_NOT_CONFIGURED"]["ids"], ", ".join(sorted(inj["INJ-09"]["case_ids"])))
        rec.add("D INJ-10 SELF_APPROVAL cases", r08["SELF_APPROVAL"]["ids"], ", ".join(sorted(inj["INJ-10"]["case_ids"])))
        rec.add("D domain flags equal SQL flags", len(res.flags), r08["PAUSE_OUTSIDE_WORKING_INTERVAL"]["total_rows"])
        rec.add("D rejected rows kept (domain vs table)", conn.execute("SELECT count(*)::int AS n FROM rejected_records").fetchone()["n"],
                len(res.ingest.rejected))

    # ---- A. golden case, three sources, printed --------------------------------------------------------
    golden_rows: list[dict] = []
    if gurl:
        with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as gc:
            gc.execute((HERE / "00_case_facts.sql").read_text())
            mine = gc.execute((HERE / "09_golden_case_business_hours.sql").read_text()).fetchall()
            gref = dict(gc.execute(REFERENCE.read_text()).fetchone())
        results["09_golden_case_business_hours"] = mine
        print(f"### 09_golden_case_business_hours.sql (golden database)\n\n{table(mine)}\n")
        gin = json.loads((ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
        gdom = {s: run_pipeline(gin, state=s).metrics for s in ("pause_eligible", "pause_not_eligible")}
        m = mine[0]
        exp = json.loads((ROOT / "tests" / "fixtures" / "golden" / "expected.json").read_text())["states"]
        for label, mine_v, ref_v, dom_v, exp_v in (
            ("calendar hours", m["calendar_h"], gref["calendar_cycle_time_hours"], gdom["pause_eligible"]["calendar_cycle_time_hours"],
             exp["pause_eligible"]["metrics"]["calendar_cycle_time_hours"]),
            ("BUSINESS hours", m["business_h"], gref["business_cycle_time_hours"], gdom["pause_eligible"]["business_cycle_time_hours"],
             exp["pause_eligible"]["metrics"]["business_cycle_time_hours"]),
            ("paused hours", m["paused_h"], gref["paused_time_hours"], gdom["pause_eligible"]["paused_time_hours"],
             exp["pause_eligible"]["metrics"]["paused_time_hours"]),
            ("paused business overlap", m["paused_business_overlap_h"], gref["paused_business_overlap_hours"],
             gdom["pause_eligible"]["paused_business_overlap_hours"], exp["pause_eligible"]["metrics"]["paused_business_overlap_hours"]),
            ("active, pause eligible", m["active_h_pause_eligible"], gref["active_elapsed_hours"],
             gdom["pause_eligible"]["active_elapsed_hours"], exp["pause_eligible"]["metrics"]["active_elapsed_hours"]),
            ("active, not eligible", m["active_h_pause_not_eligible"], None, gdom["pause_not_eligible"]["active_elapsed_hours"],
             exp["pause_not_eligible"]["metrics"]["active_elapsed_hours"]),
        ):
            golden_rows.append({"quantity": label, "analysis_sql_09": q4(mine_v),
                                "reference_metrics_sql": "n/a (policy fixed in the rule)" if ref_v is None else ref_v,
                                "python_domain": dom_v, "expected_json": exp_v})
            vals = [q4(mine_v), dom_v, exp_v] + ([ref_v] if ref_v is not None else [])
            ok = len(set(vals)) == 1
            rec.ok &= ok
            rec.rows.append({"check": f"A golden {label}", "sql_view": q4(mine_v), "second_source": ref_v or "",
                             "third_source": dom_v, "equal": ok})
        print("### golden case-001: per-case hours from three sources (and the hand-derived expected.json)\n\n" + table(golden_rows) + "\n")
    else:
        rec.ok = False
        print("GOLDEN_DATABASE_URL not set: golden reconciliation skipped", file=sys.stderr)

    print("### reconciliation\n\n" + table(rec.rows) + "\n")
    results["reconciliation"] = rec.rows
    results["golden_three_sources"] = golden_rows
    results["reference_metrics_snapshot"] = [ref]
    results["python_domain_snapshot"] = [{k: v for k, v in py.items() if k not in ("open_backlog_at_cutoff", "step_waiting_time_hours")}]
    results["python_domain_step_waiting"] = [py["step_waiting_time_hours"]]
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(
            results, indent=1, default=lambda o: format(o, "f") if isinstance(o, Decimal) else str(o)) + "\n")
    print("RESULT:", "OK" if rec.ok else "MISMATCH")
    return 0 if rec.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
