"""Run every analysis investigation and reconcile it with the independent sources (P04-ART-04).

Usage (from apps/serviceflow):
  ../../.venv/bin/python data/sql/analysis/run_all.py [--json artifacts/analysis-results.json] [--bi-out artifacts/bi] [--keep]

With no environment variables it creates two scratch databases (artifacts04_run_snapshot, artifacts04_run_golden) on the local
PostgreSQL named by ARTIFACTS_ADMIN_URL (default: the repository's local development login, 127.0.0.1:5432), loads the published
snapshot ``web/public/data`` and the golden fixture through ``data/migrate.py`` and ``data/seed.py`` (prepare_snapshot.py), runs
everything and drops them again (``--keep`` leaves them). To use databases you prepared yourself, set ARTIFACTS_DATABASE_URL and
ARTIFACTS_GOLDEN_DATABASE_URL (names must start with artifacts04_; the shared serviceflow database is never touched).

What runs, in order (exit code 0 only if every query ran and every reconciliation row is equal):
  00_event_views.sql, then 01..08 on the snapshot (some files hold several blocks marked ``-- @@ name``), 09 on the golden database,
  bi_fact_*.sql and bi_dimensions.sql on the snapshot (written as CSV with --bi-out).
Reconciliation (the rows printed at the end, ``reconciliation`` in the JSON):
  A  golden fixture: data/sql/reference_metrics.sql, the Python domain and tests/fixtures/golden/expected.json agree on all 28 metric
     keys, the per-ticket figures of 09 equal the hand calculation, the seeded simulation events equal expected.json;
  B  snapshot headline figures: the investigations vs data/sql/reference_metrics.sql vs the Python domain, whole window and the
     training and holdout windows, and reference_metrics.sql vs the domain on all 28 keys in each window;
  C  every result set cell by cell against python_side.py (exact rationals over the domain's replay, no SQL);
  D  groups: queue, priority, agent and channel figures vs the domain's group_metrics; Monday cutoffs vs the reference and the domain;
  E  rejections and injected defects vs data/injection-manifest.json and manifest.json; the BI measures recomputed from the CSV facts.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(HERE)]

import python_side as ps  # noqa: E402
from prepare_snapshot import (DEFAULT_ADMIN_URL, SNAPSHOT, assert_scratch, create_database, drop_database, prepare, with_db)  # noqa: E402
from serviceflow import compute_metrics, disclosures, group_metrics  # noqa: E402
from serviceflow.contract import METRIC_KEYS  # noqa: E402
from serviceflow.simulation import mean_ci95  # noqa: E402
from serviceflow.timeutil import d4, d6, nearest_rank, parse_ts  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
CODE_REVISION = "43de7f8"
DATASET_HASH = "944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4"
ABANDON = ["chat", "phone"]
RUN_SNAPSHOT_DB, RUN_GOLDEN_DB = "artifacts04_run_snapshot", "artifacts04_run_golden"


def fmt(v) -> str:
    return ps.norm(v)


def table(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(fmt(r[c]).replace("|", "/") for c in cols) + " |" for r in rows]
    return "\n".join(out)


def blocks(path: Path) -> list[tuple[str | None, str]]:
    text = path.read_text()
    parts = re.split(r"(?m)^-- @@ (\w+)\n", text)
    return [(None, text)] if len(parts) == 1 else [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def run_file(conn, path: Path) -> dict[str, list[dict]]:
    out = {}
    for name, sql in blocks(path):
        out[path.stem if name is None else f"{path.stem}__{name}"] = [dict(r) for r in conn.execute(sql).fetchall()]
    return out


class Recon:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.ok = True

    def add(self, check: str, a, b, c=None, d=None) -> None:
        vals = [a, b] + [v for v in (c, d) if v is not None]
        eq = all(fmt(v) == fmt(a) for v in vals)
        self.ok &= eq
        self.rows.append({"check": check, "analysis_sql": fmt(a), "second_source": fmt(b), "third_source": "" if c is None else fmt(c),
                          "fourth_source": "" if d is None else fmt(d), "equal": eq})


def iso(x: datetime) -> str:
    return x.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reference(conn, w0: datetime, w1: datetime, cutoffs: list[datetime] | None = None) -> dict:
    row = conn.execute(REFERENCE.read_text(), {"w0": iso(w0), "w1": iso(w1), "cutoffs": [iso(c) for c in (cutoffs or [w1])],
                                               "abandonable": ABANDON}).fetchone()
    return dict(row)


def export_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        cols = list(rows[0])
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r[c]) for c in cols])


# ---- BI measures from the exported facts (no database, no domain) ---------------------------------------------------------
def bi_measures(ticket: list[dict], interval: list[dict], shift: list[dict], survey: list[dict], reps: list[dict],
                window: tuple[datetime, datetime] | None = None) -> list[dict]:
    """The measures of docs/bi-package.md evaluated over the CSV facts for day-aligned dates [p0, p1) (default: the whole twelve weeks)."""
    p0, p1 = window or (parse_ts("2026-07-06T00:00:00Z"), parse_ts("2026-09-28T00:00:00Z"))
    k0, k1 = int(p0.strftime("%Y%m%d")), int(p1.strftime("%Y%m%d"))
    hours = Fraction(int((p1 - p0).total_seconds()), 3600)
    arr = [r for r in ticket if k0 <= int(r["created_date_key"]) < k1]                         # created date role
    comp = [r for r in ticket if fmt(r["resolved_date_key"]) != "" and k0 <= int(r["resolved_date_key"]) < k1]   # resolved date role
    fr = [Fraction(int(r["first_response_seconds"]), 60) for r in arr if fmt(r["first_response_seconds"]) != ""]
    wt = [Fraction(int(r["wait_seconds"]), 60) for r in arr if fmt(r["wait_seconds"]) != ""]
    rs = [Fraction(int(r["resolution_seconds"]), 60) for r in comp]
    m_fr = sum(int(r["met_first_response"]) for r in arr if fmt(r["met_first_response"]) != "")
    m_rs = sum(int(r["met_resolution"]) for r in comp)
    handling = Fraction(0)
    for r in interval:                                                                         # clipped at the dates, as the DAX measure does
        a, b = parse_ts(r["started_at"]), parse_ts(r["ended_at"])
        lo, hi = max(a, p0), min(b, p1)
        if hi > lo:
            handling += Fraction(int((hi - lo).total_seconds()), 60)
    staffed = Fraction(0)
    whole = sum(int(r["staffed_available_minutes"]) for r in shift)
    for r in shift:                                                                            # D-05 with clipping, as the DAX measure does
        a, b = parse_ts(r["starts_at"]), parse_ts(r["ends_at"])
        lo, hi = max(a, p0), min(b, p1)
        if hi > lo:
            staffed += Fraction(int((hi - lo).total_seconds()), 60) - (int(r["declared_break_minutes"]) if a >= p0 and b <= p1 else 0)
    abandonable = [r for r in arr if int(r["can_abandon"]) == 1]
    abandoned = sum(int(r["is_abandoned"]) for r in abandonable)
    sv = [r for r in survey if fmt(r["resolved_date_key"]) != "" and k0 <= int(r["resolved_date_key"]) < k1]
    inv, resp, pos = (sum(int(r[c]) for r in sv) for c in ("is_invited", "is_valid_response", "is_positive"))
    reopened = sum(1 for r in comp if int(r["reopen_count"]) > 0)
    transferred = sum(1 for r in arr if int(r["transfer_count"]) > 0)
    open_end = sum(1 for r in ticket if int(r["is_completed"]) == 0 and int(r["is_abandoned"]) == 0 and k0 <= int(r["created_date_key"]) < k1)
    out = [
        ("Arrivals", len(arr), "COUNTROWS(fact_ticket) on the created date"),
        ("Completions", len(comp), "tickets with a final resolution (resolved date)"),
        ("Arrival Rate per Hour", ps.dq(len(arr) / hours, 6), "Arrivals / (days x 24)"),
        ("Completion Rate per Hour", ps.dq(len(comp) / hours, 6), "Completions / (days x 24)"),
        ("Mean First Response (min)", d4(sum(fr, Fraction(0)) / len(fr)), "tickets with a human reply"),
        ("P90 First Response (min)", d4(nearest_rank(fr, Fraction(9, 10))), "nearest rank, index ceil(0.9 n)"),
        ("Mean Wait to First Service (min)", d4(sum(wt, Fraction(0)) / len(wt)), "tickets that were served"),
        ("Mean Resolution (min)", d4(sum(rs, Fraction(0)) / len(rs)), "completed tickets, from the original arrival"),
        ("P90 Resolution (min)", d4(nearest_rank(rs, Fraction(9, 10))), "nearest rank"),
        ("SLA First Response Compliance", d6(Fraction(m_fr, len(fr))), f"{m_fr} / {len(fr)}"),
        ("SLA Resolution Compliance", d6(Fraction(m_rs, len(comp))), f"{m_rs} / {len(comp)}"),
        ("Open at End of Data", open_end, "not completed and not abandoned (open overdue = 0 of them)"),
        ("Handling Minutes", d4(handling), "service intervals clipped to the selected dates"),
        ("Staffed Available Minutes", ps.dq(staffed, 4), "overlap of each shift with the selected dates, minus the declared break only for a shift inside them (D-05)"),
        ("Staffed Shift Minutes (whole shifts)", ps.dq(Fraction(whole), 4), "every shift net of its declared break, clipped by nothing"),
        ("Agent Occupancy", d6(handling / staffed), "Handling Minutes / Staffed Available Minutes"),
        ("Abandonment Rate", d6(Fraction(abandoned, len(abandonable))), f"{abandoned} / {len(abandonable)} (chat and phone)"),
        ("Survey Invitation Rate", d6(Fraction(inv, len(comp))), f"{inv} invited / {len(comp)} completed"),
        ("Survey Response Rate", d6(Fraction(resp, inv)), f"{resp} valid / {inv} invited"),
        ("CSAT", d6(Fraction(pos, resp)), f"{pos} positive / {resp} valid"),
        ("Reopen Rate of Completions", d6(Fraction(reopened, len(comp))), f"{reopened} / {len(comp)} (an addition beyond the 28 published keys)"),
        ("Transfer Share of Arrivals", d6(Fraction(transferred, len(arr))), f"{transferred} / {len(arr)} (an addition beyond the 28 published keys)"),
    ]
    by_run: dict[str, list[Fraction]] = defaultdict(list)
    for r in sorted(reps, key=lambda r: (r["simulation_id"], int(r["replication"]))):
        by_run[r["simulation_id"]].append(Fraction(r["mean_wait_minutes"]))
    for sid in sorted(by_run):
        ci = mean_ci95(by_run[sid])
        out.append((f"Simulated Mean Wait {sid} (min, mean of {ci['n']} replications)", ci["mean"], "SIMULATED estimate"))
        out.append((f"Simulated 95 % Half-width {sid} (min)", ci["ci95_half_width"], "SIMULATED estimate, Student-t"))
    diff = [b - a for a, b in zip(by_run["sim-001"], by_run["sim-002"])]
    pc = mean_ci95(diff)
    out.append(("Simulated Paired Difference sim-002 minus sim-001 (min)", pc["mean"], "SIMULATED estimate, same seeds"))
    out.append(("Simulated Paired 95 % Half-width (min)", pc["ci95_half_width"], "SIMULATED estimate, Student-t"))
    return [{"measure": m, "expected": v, "source": s} for m, v, s in out]


def main(argv: list[str]) -> int:
    url, gurl = os.environ.get("ARTIFACTS_DATABASE_URL"), os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL")
    provisioned = False
    admin = os.environ.get("ARTIFACTS_ADMIN_URL", DEFAULT_ADMIN_URL)
    if not url or not gurl:
        provisioned = True
        url, gurl = with_db(admin, RUN_SNAPSHOT_DB), with_db(admin, RUN_GOLDEN_DB)
        create_database(admin, RUN_SNAPSHOT_DB)
        create_database(admin, RUN_GOLDEN_DB)
        prep = prepare(url, False)
        prepare(gurl, True)
        print(f"prepared scratch databases: dataset_version {prep['dataset_version']}, {prep['skipped']} rejected rows kept, "
              f"{prep['shift_breaks_loaded']} breaks loaded", file=sys.stderr)
    assert_scratch(url)
    assert_scratch(gurl)
    try:
        return run(argv, url, gurl)
    finally:
        if provisioned and "--keep" not in argv:
            drop_database(admin, RUN_SNAPSHOT_DB)
            drop_database(admin, RUN_GOLDEN_DB)


def run(argv: list[str], url: str, gurl: str) -> int:
    rec = Recon()
    results: dict[str, list[dict]] = {}
    sql_files = sorted(f for f in HERE.glob("0[1-8]_*.sql"))
    ctx = ps.load()
    pop, dom_hist = ctx.pop, ctx.hist
    full, train, hold = ps.WINDOWS["full"], ps.WINDOWS["training"], ps.WINDOWS["holdout"]
    cutoff = parse_ts(ctx.inputs["backlog_cutoffs"][0])

    with psycopg.connect(url, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as conn:
        conn.execute((HERE / "00_event_views.sql").read_text())
        for f in sql_files:
            for key, rows in run_file(conn, f).items():
                results[key] = rows
                print(f"### {key}\n\n{table(rows)}\n")
        ref = {n: reference(conn, *w) for n, w in ps.WINDOWS.items()}
        mon_ref = []
        for c in ps.monday_cutoffs():
            mon_ref.append(reference(conn, full[0], c, [c]))
        bi = {name: [dict(r) for r in conn.execute((HERE / f"bi_fact_{name}.sql").read_text()).fetchall()]
              for name in ("ticket", "service_interval", "shift", "survey")}
        dims = run_file(conn, HERE / "bi_dimensions.sql")
        rejected_db = {(r["entity"], r["id"], r["reason_code"]) for r in conn.execute("SELECT entity, id, reason_code FROM rejected_records").fetchall()}
        db_version = conn.execute("SELECT dataset_version, dataset_hash FROM dataset_versions ORDER BY created_at DESC LIMIT 1").fetchone()
        sim_rows = conn.execute("SELECT count(*) AS n FROM simulation_events").fetchone()["n"]

    # ---- domain, per window ------------------------------------------------------------------------------------------
    dom = {n: compute_metrics(pop, w, [w[1]], ABANDON) for n, w in ps.WINDOWS.items()}

    # ---- B. reference_metrics.sql against the domain on all 28 keys, per window ---------------------------------------
    for n in ("full", "training", "holdout"):
        bad = [k for k in METRIC_KEYS if fmt(ref[n][k]) != fmt(dom[n][k])]
        rec.add(f"B reference_metrics.sql vs Python domain, {n} window: metric keys differing (of {len(METRIC_KEYS)})", len(bad), 0)
    rec.add("B snapshot arrivals + rejected tickets = published tickets (manifest row_counts)", len(pop.tickets) + sum(1 for r in ctx.res.ingest.rejected if r.entity == "tickets"),
            ctx.manifest["row_counts"]["tickets"])

    def row(key: str, **where) -> dict:
        return next(r for r in results[key] if all(r[k] == v for k, v in where.items()))

    a02 = row("02_wait_and_response_distributions__first_response_and_wait", queue_id="ALL", priority="ALL")
    b02 = row("02_wait_and_response_distributions__resolution_tail", queue_id="ALL", priority="ALL")
    head = [
        ("arrival_count", a02["arrivals"], "arrival_count"),
        ("mean_first_response_minutes", a02["mean_first_response_min"], "mean_first_response_minutes"),
        ("p90_first_response_minutes", a02["p90_first_response_min"], "p90_first_response_minutes"),
        ("mean_wait_minutes", a02["mean_wait_min"], "mean_wait_minutes"),
        ("completion_count", b02["completions"], "completion_count"),
        ("mean_resolution_minutes", b02["mean_resolution_min"], "mean_resolution_minutes"),
    ]
    for label, v, key in head:
        rec.add(f"B whole window {label}: query 02 ALL vs reference_metrics.sql vs domain", v, ref["full"][key], dom["full"][key])
    rec.add("B whole window first-response tickets with a human reply (02) vs sla_first_response_eligible", a02["with_human_reply"], ref["full"]["sla_first_response_eligible"],
            dom["full"]["sla_first_response_eligible"])
    for wname in ("full", "training", "holdout"):
        r3 = row("03_sla_compliance_and_open_overdue__compliance_by_priority_and_window", window_name=wname, priority="ALL")
        rec.add(f"B {wname} window SLA first response within / eligible / compliance: query 03 vs reference vs domain",
                f"{r3['first_response_within']} / {r3['first_response_eligible']} / {fmt(r3['first_response_compliance'])}",
                f"{ref[wname]['sla_first_response_within']} / {ref[wname]['sla_first_response_eligible']} / {ref[wname]['sla_first_response_compliance']}",
                f"{dom[wname]['sla_first_response_within']} / {dom[wname]['sla_first_response_eligible']} / {dom[wname]['sla_first_response_compliance']}")
        rec.add(f"B {wname} window SLA resolution within / eligible / compliance: query 03 vs reference vs domain",
                f"{r3['resolution_within']} / {r3['resolution_eligible']} / {fmt(r3['resolution_compliance'])}",
                f"{ref[wname]['sla_resolution_within']} / {ref[wname]['sla_resolution_eligible']} / {ref[wname]['sla_resolution_compliance']}",
                f"{dom[wname]['sla_resolution_within']} / {dom[wname]['sla_resolution_eligible']} / {dom[wname]['sla_resolution_compliance']}")
        rec.add(f"B {wname} window arrivals: query 03 vs reference vs domain", r3["arrivals"], ref[wname]["arrival_count"], dom[wname]["arrival_count"])
    r4 = row("04_occupancy_by_agent_and_shift__occupancy_by_agent", agent_id="ALL")
    for label, v, key in (("staffed_available_minutes", r4["staffed_available_min"], "staffed_available_minutes"),
                          ("handling_minutes_total", r4["handling_min"], "handling_minutes_total"),
                          ("agent_occupancy", r4["occupancy"], "agent_occupancy")):
        rec.add(f"B whole window {label}: query 04 ALL vs reference_metrics.sql vs domain", v, ref["full"][key], dom["full"][key])
    r6 = row("06_abandonment_by_channel_and_patience__abandonment_by_channel", channel="ALL abandonable")
    rec.add("B whole window abandonment_rate: query 06 vs reference_metrics.sql vs domain", r6["abandonment_rate"], ref["full"]["abandonment_rate"], dom["full"]["abandonment_rate"])
    r7 = row("07_survey_response_skew__response_by_experience", experience="ALL")
    for label, v, key in (("csat", r7["csat"], "csat"), ("survey_invitation_rate", r7["invitation_rate"], "survey_invitation_rate"),
                          ("survey_response_rate", r7["response_rate"], "survey_response_rate")):
        rec.add(f"B whole window {label}: query 07 vs reference_metrics.sql vs domain", v, ref["full"][key], dom["full"][key])
    disc = disclosures(pop, full)
    rec.add("B surveys invited / valid / positive among completions: query 07 vs disclosures()", f"{r7['invited']} / {r7['valid_responses']}",
            f"{disc['csat']['invited']} / {disc['csat']['valid_responses']}")
    rec.add("B open overdue at the window end (the reference's one open-overdue figure) vs domain vs the last Monday cutoff query", ref["full"]["open_overdue_at_cutoff"],
            dom["full"]["open_overdue_at_cutoff"], results["03_sla_compliance_and_open_overdue__open_overdue_at_monday_cutoffs"][-1]["open_overdue"])

    # ---- C. every result set against the Python side -----------------------------------------------------------------
    exp = ps.expected(ctx)
    for key in ps.KEYS:
        diffs = ps.compare(key, results[key], exp[key])
        rec.add(f"C {key}: {len(results[key])} rows, cells differing from the Python side", len(diffs), 0)
        for d in diffs[:5]:
            print("DIFF", d, file=sys.stderr)

    # ---- D. groups and cutoffs ---------------------------------------------------------------------------------------
    for gb, col in (("queue", "queue_id"), ("priority", "priority")):
        gm = group_metrics(pop, gb, full, [cutoff], ABANDON)
        for k, m in gm.items():
            f = {col: k, "priority" if gb == "queue" else "queue_id": "ALL"}
            a = row("02_wait_and_response_distributions__first_response_and_wait", **f)
            b = row("02_wait_and_response_distributions__resolution_tail", **f)
            rec.add(f"D {gb} {k}: mean first response / P90 / mean wait / mean resolution (queue = final queue): queries 02 vs group_metrics",
                    f"{a['mean_first_response_min']} / {a['p90_first_response_min']} / {a['mean_wait_min']} / {b['mean_resolution_min']}",
                    f"{m['mean_first_response_minutes']} / {m['p90_first_response_minutes']} / {m['mean_wait_minutes']} / {m['mean_resolution_minutes']}")
        if gb == "priority":
            for k, m in gm.items():
                for wname in ("full",):
                    r3 = row("03_sla_compliance_and_open_overdue__compliance_by_priority_and_window", window_name=wname, priority=k)
                    rec.add(f"D priority {k}: SLA first response and resolution within / eligible: query 03 vs group_metrics",
                            f"{r3['first_response_within']}/{r3['first_response_eligible']} {r3['resolution_within']}/{r3['resolution_eligible']}",
                            f"{m['sla_first_response_within']}/{m['sla_first_response_eligible']} {m['sla_resolution_within']}/{m['sla_resolution_eligible']}")
    for wn in ("training", "holdout"):
        for k, m in group_metrics(pop, "priority", ps.WINDOWS[wn], [ps.WINDOWS[wn][1]], ABANDON).items():
            r3 = row("03_sla_compliance_and_open_overdue__compliance_by_priority_and_window", window_name=wn, priority=k)
            rec.add(f"D {wn} priority {k}: SLA within / eligible (first response, resolution): query 03 vs group_metrics",
                    f"{r3['first_response_within']}/{r3['first_response_eligible']} {r3['resolution_within']}/{r3['resolution_eligible']}",
                    f"{m['sla_first_response_within']}/{m['sla_first_response_eligible']} {m['sla_resolution_within']}/{m['sla_resolution_eligible']}")
    for week, (c, mref) in enumerate(zip(ps.monday_cutoffs(), mon_ref), 1):
        m = compute_metrics(pop, (full[0], c), [c], ABANDON)
        r = results["03_sla_compliance_and_open_overdue__open_overdue_at_monday_cutoffs"][week - 1]
        rec.add(f"D Monday cutoff {iso(c)}: backlog / open overdue: query 03 vs reference_metrics.sql vs domain", f"{r['backlog']} / {r['open_overdue']}",
                f"{mref['backlog'][iso(c)]} / {mref['open_overdue_at_cutoff']}", f"{m['backlog'][iso(c)]} / {m['open_overdue_at_cutoff']}")
    for k, m in group_metrics(pop, "agent", full, [cutoff], ABANDON).items():
        r = row("04_occupancy_by_agent_and_shift__occupancy_by_agent", agent_id=k)
        rec.add(f"D agent {k}: staffed minutes / handling minutes / occupancy: query 04 vs group_metrics",
                f"{r['staffed_available_min']} / {r['handling_min']} / {fmt(r['occupancy'])}",
                f"{m['staffed_available_minutes']} / {m['handling_minutes_total']} / {m['agent_occupancy']}")
    for k, m in group_metrics(pop, "channel", full, [cutoff], ABANDON).items():
        r = row("06_abandonment_by_channel_and_patience__abandonment_by_channel", channel=k)
        rec.add(f"D channel {k}: abandonment rate: query 06 vs group_metrics", r["abandonment_rate"], m["abandonment_rate"])
    for k, m in group_metrics(pop, "queue", full, [cutoff], ABANDON).items():
        r = row("07_survey_response_skew__score_distribution_by_queue", queue_id=k)
        rec.add(f"D queue {k}: CSAT / response rate (completions by final queue): query 07 vs group_metrics",
                f"{r['csat']} / {r['response_rate']}", f"{m['csat']} / {m['survey_response_rate']}")
    n_tr = sum(1 for e in pop.ticket_events if e.event_type == "transferred")
    rec.add("D transfers: query 05 routes total vs 'transferred' events vs tickets with a transfer (domain disclosures, arrivals)",
            sum(r["transfers"] for r in results["05_transfer_and_reopen_effects__transfer_routes"]), n_tr, disc["transferred_tickets"])
    rec.add("D reopened completions: query 05 groups with a reopen vs disclosures reopened_among_completions",
            sum(r["completions"] for r in results["05_transfer_and_reopen_effects__by_transfer_and_reopen"] if "reopened" in r["ticket_group"]),
            disc["reopened_among_completions"])
    rec.add("D service intervals: query 04 ALL vs bi_fact_service_interval rows vs the domain replay",
            r4["service_intervals"], len(bi["service_interval"]), sum(len(h.intervals) for h in dom_hist.values()))

    mb = results["04_occupancy_by_agent_and_shift__monday_bind_handling_by_queue"]
    mb_all = next(r for r in mb if r["queue_id"] == "ALL")
    mb_other = sum(Decimal(fmt(r["handling_min"])) for r in mb if r["queue_id"] not in ("ALL", "q-002"))
    rec.add("D Monday 09-11 bind, training weeks: share of the technical-skilled agents' started handling that went to other queues (1 dp): query 04 vs "
            "docs/uat-evidence.md (reviewer harness: 988 of 3,423 minutes, 28.9 %)", str((100 * mb_other / Decimal(fmt(mb_all["handling_min"]))).quantize(Decimal("0.1"))), "28.9")

    # ---- E. rejections, injected defects, published counts ------------------------------------------------------------
    inj = {i["id"]: i for i in json.loads((ROOT / "data" / "injection-manifest.json").read_text())["injections"]}
    want_rej = {(r["entity"], r["id"], r["reason_code"]) for i in inj.values() for r in i.get("expected_rejections", [])}
    rec.add("E rejected_records rows vs the manifest's expected_rejections (rows in the symmetric difference)", len(rejected_db ^ want_rej), 0, len(rejected_db) - len(want_rej))
    rec.add("E rejected rows kept: table vs domain ingest", len(rejected_db), len(ctx.res.ingest.rejected), 70)
    for r in results["08_rejections_and_defects_by_reason__published_vs_loaded"]:
        rec.add(f"E published {r['entity']} rows (loaded + rejected) vs manifest row_counts", r["published_rows"], ctx.manifest["row_counts"][r["entity"]])
    found = {r["injection_id"]: r["found"] for r in results["08_rejections_and_defects_by_reason__injected_defects_found"]}
    manifest_count = {"INJ-01": len(inj["INJ-01"]["record_ids"]), "INJ-02": len(inj["INJ-02"]["detail"]), "INJ-03": len(inj["INJ-03"]["record_ids"]),
                      "INJ-04": len(inj["INJ-04"]["record_ids"]), "INJ-05": len(inj["INJ-05"]["record_ids"]), "INJ-06": len(inj["INJ-06"]["record_ids"]),
                      "INJ-07": 0, "INJ-08": len(inj["INJ-08"]["record_ids"])}
    for k, v in manifest_count.items():
        note = " (replay-only: the cold-start run is not in simulation_runs)" if k == "INJ-07" else ""
        rec.add(f"E {k} found by its SQL check vs the manifest's own count{note}", found[k], v)
    known_differences = []
    known_differences.append({"item": "INJ-09 unanswered invitations after a poor experience", "this_package": found["INJ-09"], "manifest": inj["INJ-09"]["record_count"],
                              "why": "the manifest counts over all 2,153 published surveys (6 belong to rejected tickets) and its own definition of a poor experience; "
                                     "this package counts completed accepted tickets and the definition printed in 07"})
    st = ctx.manifest["stats"]
    pub_tickets = [parse_ts(t["created_at"]) for t in json.loads((SNAPSHOT / "tickets.json").read_text())["rows"]]
    pub_blocks = {b["note"]: b for b in ps.pick_blocks(ps.hour_blocks(pub_tickets, [(s.starts_at, s.ends_at, s.break_minutes) for s in pop.shifts]))}
    mb = st["designed"]["monday_block"]
    rec.add("E Monday 09-11 block ratio: query 01 (accepted tickets) vs the same block over all published tickets vs manifest stats.designed", row("01_arrivals_by_hour_of_week", note="top 1")["arrivals_per_staffed_hour"],
            pub_blocks["top 1"]["arrivals_per_staffed_hour"], f"{mb['ratio']:.4f}")
    sql_next = row("01_arrivals_by_hour_of_week", note="top 2")
    known_differences.append({"item": "01 next-best block", "this_package": f"{sql_next['block_utc']} {sql_next['arrivals_per_staffed_hour']} (accepted tickets)",
                              "manifest": f"{mb['next_best']['block']} {mb['next_best']['ratio']:.4f}; over all published tickets here: {pub_blocks['top 2']['block_utc']} {pub_blocks['top 2']['arrivals_per_staffed_hour']}",
                              "why": "the manifest counts the 3,826 published tickets; 9 are rejected at ingest, so the accepted arrivals of the block are fewer"})
    rec.add("E median block ratio: query 01 (accepted tickets) vs the same over all published tickets vs manifest stats.designed.median_block_ratio",
            row("01_arrivals_by_hour_of_week", note="median of the blocks")["arrivals_per_staffed_hour"], pub_blocks["median of the blocks"]["arrivals_per_staffed_hour"],
            f"{mb['median_block_ratio']:.4f}")
    pe = results["07_survey_response_skew__response_by_experience"]
    good = next(r for r in pe if r["experience"] == "good experience")
    poor = next(r for r in pe if r["experience"] == "poor experience")
    rec.add("E response rate after a good experience: query 07 (4 dp) vs manifest stats.response_rate_after_good_experience", f"{good['response_rate']:.4f}", f"{st['response_rate_after_good_experience']:.4f}")
    known_differences.append({"item": "07 response rate after a poor experience", "this_package": fmt(poor["response_rate"]),
                              "manifest": f"{st['response_rate_after_poor_experience']} (invited {st['invited_after_poor_experience']})",
                              "why": "other population (all published tickets and surveys) and the generator's own definition of a poor experience"})
    rec.add("E CSAT among responders: query 07 vs manifest stats.csat_among_responders (3 dp)", f"{Decimal(fmt(r7['csat'])):.3f}", f"{st['csat_among_responders']:.3f}")

    # ---- A. golden fixture -------------------------------------------------------------------------------------------
    golden_rows: list[dict] = []
    gin = json.loads((GOLDEN_DIR / "inputs.json").read_text())
    gexp = json.loads((GOLDEN_DIR / "expected.json").read_text())
    from serviceflow import run_pipeline
    gres = run_pipeline(gin)
    with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as gc:
        gc.execute((HERE / "00_event_views.sql").read_text())
        g09 = run_file(gc, HERE / "09_golden_known_answer.sql")
        gref = dict(gc.execute(REFERENCE.read_text(), {"w0": gin["window_start"], "w1": gin["window_end"], "cutoffs": gin["backlog_cutoffs"],
                                                         "abandonable": gin["abandonable_channels"]}).fetchone())
        gsim = [dict(r) for r in gc.execute("SELECT simulation_event_id, ticket_id, event_type, event_at FROM simulation_events WHERE simulation_id = 'sim-001' "
                                            "ORDER BY simulation_event_id").fetchall()]
    results.update(g09)
    for k, v in g09.items():
        print(f"### {k} (golden database)\n\n{table(v)}\n")
    for k in METRIC_KEYS:
        rec.add(f"A golden {k}: reference_metrics.sql vs Python domain vs expected.json", gref[k], gres.metrics[k], gexp["metrics"][k])
        golden_rows.append({"quantity": k, "reference_metrics_sql": json.dumps(gref[k], sort_keys=True) if isinstance(gref[k], (dict, list)) else fmt(gref[k]),
                            "python_domain": json.dumps(gres.metrics[k], sort_keys=True) if isinstance(gres.metrics[k], (dict, list)) else fmt(gres.metrics[k]),
                            "expected_json": json.dumps(gexp["metrics"][k], sort_keys=True) if isinstance(gexp["metrics"][k], (dict, list)) else fmt(gexp["metrics"][k])})
    hand = {"t-001": ("0.0000", "0.0000", "10.0000", "10.0000"), "t-002": ("10.0000", "10.0000", "20.0000", "10.0000"),
            "t-003": ("20.0000", "20.0000", "30.0000", "10.0000")}          # CALCULATION.md, typed by hand
    for r in g09["09_golden_known_answer__golden_per_ticket"]:
        tid = r["ticket_id"]
        mine = (fmt(r["first_response_min"]), fmt(r["wait_min"]), fmt(r["resolution_min"]), fmt(r["handling_min"]))
        e = gexp["metrics"]
        rec.add(f"A golden {tid}: first response / wait / resolution / handling (09 vs expected.json vs CALCULATION.md)", " / ".join(mine),
                " / ".join((e["first_response_minutes"][tid], e["wait_minutes"][tid], e["resolution_minutes"][tid], hand[tid][3])), " / ".join(hand[tid]))
    t1 = g09["09_golden_known_answer__golden_totals"]
    rec.add("A golden mean wait / handling total / last completion: event log (09) vs expected.json", f"{t1[0]['mean_wait_min']} / {t1[0]['handling_min_total']} / {t1[0]['last_completion_min']}",
            f"{gexp['metrics']['mean_wait_minutes']} / {gexp['metrics']['handling_minutes_total']} / {gexp['simulation']['final_completion_minute']}")
    rec.add("A golden simulation sim-001 mean wait / last completion: simulation_events (09) vs expected.json", f"{t1[1]['mean_wait_min']} / {t1[1]['last_completion_min']}",
            f"{gexp['simulation']['mean_wait_minutes']} / {gexp['simulation']['final_completion_minute']}")
    want_ev = [(e["simulation_event_id"], e["ticket_id"], e["event_type"], e["event_at"]) for e in gexp["simulation"]["events"]]
    got_ev = [(e["simulation_event_id"], e["ticket_id"], e["event_type"], fmt(e["event_at"])) for e in gsim]
    rec.add("A golden simulation events (6): seeded rows vs expected.json (rows differing)", sum(1 for a, b in zip(got_ev, want_ev) if a != b) + abs(len(got_ev) - len(want_ev)), 0)

    # ---- BI facts: CSV, measures, reconciliation ------------------------------------------------------------------------
    sim_ref = json.loads((ROOT / "web" / "public" / "reference" / "simulation-runs.json").read_text())
    reps = []
    for sid, run_ in sorted(sim_ref["replications"]["runs"].items()):
        for r, (seed, w) in enumerate(zip(run_["seeds"], run_["per_replication_mean_wait_minutes"])):
            reps.append({"simulation_id": sid, "replication": r, "seed": seed, "mean_wait_minutes": w})
    sim_cfg = [{"simulation_id": r["simulation_id"], "policy_version": r["policy_version"], "agents": r["config"]["agents"],
                "arrival_rate_per_hour": r["config"]["arrival_rate_per_hour"], "service_minutes": r["config"]["service_minutes"],
                "discipline": r["config"]["discipline"], "warmup_minutes": r["warmup_minutes"], "horizon_minutes": r["horizon_minutes"], "seed": r["seed"],
                "label": "simulated"} for r in json.loads((SNAPSHOT / "simulation_runs.json").read_text())["rows"]]
    measures = bi_measures(bi["ticket"], bi["service_interval"], bi["shift"], bi["survey"], reps)
    results["bi_expected_measures"] = measures
    mm = {m["measure"]: m["expected"] for m in measures}
    for measure, key in (("Arrivals", "arrival_count"), ("Completions", "completion_count"), ("Arrival Rate per Hour", "arrival_rate_per_hour"),
                         ("Completion Rate per Hour", "completion_rate_per_hour"), ("Mean First Response (min)", "mean_first_response_minutes"),
                         ("P90 First Response (min)", "p90_first_response_minutes"), ("Mean Wait to First Service (min)", "mean_wait_minutes"),
                         ("Mean Resolution (min)", "mean_resolution_minutes"), ("SLA First Response Compliance", "sla_first_response_compliance"),
                         ("SLA Resolution Compliance", "sla_resolution_compliance"), ("Handling Minutes", "handling_minutes_total"),
                         ("Staffed Available Minutes", "staffed_available_minutes"), ("Agent Occupancy", "agent_occupancy"),
                         ("Abandonment Rate", "abandonment_rate"), ("Survey Invitation Rate", "survey_invitation_rate"),
                         ("Survey Response Rate", "survey_response_rate"), ("CSAT", "csat")):
        rec.add(f"E BI measure {measure}: recomputed from the CSV facts vs reference_metrics.sql vs domain", mm[measure], ref["full"][key], dom["full"][key])
    rec.add("E BI measure Staffed Shift Minutes (whole shifts): recomputed from the CSV facts vs reference_metrics.sql staffed_shift_minutes_whole vs domain", mm["Staffed Shift Minutes (whole shifts)"],
            ref["full"]["staffed_shift_minutes_whole"], dom["full"]["staffed_shift_minutes_whole"])
    rec.add("E BI measure Open at End of Data vs reference open_overdue_at_cutoff (nothing open, so nothing open and overdue)", mm["Open at End of Data"], ref["full"]["open_overdue_at_cutoff"], dom["full"]["open_overdue_at_cutoff"])
    rec.add("E BI measure Reopen Rate of Completions vs domain disclosures (reopened_among_completions / completion_count)", mm["Reopen Rate of Completions"],
            d6(Fraction(disc["reopened_among_completions"], dom["full"]["completion_count"])))
    rec.add("E BI measure Transfer Share of Arrivals vs domain disclosures (transferred_tickets / arrival_count)", mm["Transfer Share of Arrivals"],
            d6(Fraction(disc["transferred_tickets"], dom["full"]["arrival_count"])))
    rec.add("E BI measure P90 Resolution vs query 02 ALL", mm["P90 Resolution (min)"], b02["p90_resolution_min"])
    runs = sim_ref["replications"]["runs"]
    pair = sim_ref["replications"]["paired"]["baseline_vs_plus_one_agent"]
    for sid in ("sim-001", "sim-002", "sim-003"):
        k1 = f"Simulated Mean Wait {sid} (min, mean of 50 replications)"
        rec.add(f"E BI simulated {sid} mean wait / 95 % half-width over 50 replications vs web/public/reference/simulation-runs.json",
                f"{mm[k1]} / {mm[f'Simulated 95 % Half-width {sid} (min)']}", f"{runs[sid]['mean_wait_minutes']['mean']} / {runs[sid]['mean_wait_minutes']['ci95_half_width']}")
    rec.add("E BI simulated paired difference sim-002 minus sim-001 / half-width vs simulation-runs.json",
            f"{mm['Simulated Paired Difference sim-002 minus sim-001 (min)']} / {mm['Simulated Paired 95 % Half-width (min)']}",
            f"{pair['difference_mean_wait_minutes']['mean']} / {pair['difference_mean_wait_minutes']['ci95_half_width']}")

    for wn in ("training", "holdout"):
        bm = {m["measure"]: m["expected"] for m in bi_measures(bi["ticket"], bi["service_interval"], bi["shift"], bi["survey"], reps, ps.WINDOWS[wn])}
        pairs = (("Arrivals", "arrival_count"), ("Completions", "completion_count"), ("Mean First Response (min)", "mean_first_response_minutes"),
                 ("P90 First Response (min)", "p90_first_response_minutes"), ("Mean Wait to First Service (min)", "mean_wait_minutes"),
                 ("Mean Resolution (min)", "mean_resolution_minutes"), ("SLA First Response Compliance", "sla_first_response_compliance"),
                 ("SLA Resolution Compliance", "sla_resolution_compliance"), ("Handling Minutes", "handling_minutes_total"),
                 ("Staffed Available Minutes", "staffed_available_minutes"), ("Agent Occupancy", "agent_occupancy"),
                 ("Abandonment Rate", "abandonment_rate"), ("Survey Invitation Rate", "survey_invitation_rate"),
                 ("Survey Response Rate", "survey_response_rate"), ("CSAT", "csat"))
        rec.add(f"E BI measures over the {wn} dates ({len(pairs)} measures: arrivals, completions, means, P90, SLA, handling, staffed, occupancy, abandonment, survey): "
                "recomputed from the CSV facts vs reference_metrics.sql vs domain",
                " / ".join(fmt(bm[m]) for m, _ in pairs), " / ".join(fmt(ref[wn][k]) for _, k in pairs), " / ".join(fmt(dom[wn][k]) for _, k in pairs))
    if "--bi-out" in argv:
        out = Path(argv[argv.index("--bi-out") + 1])
        for name, rows in (("fact_ticket", bi["ticket"]), ("fact_service_interval", bi["service_interval"]), ("fact_shift", bi["shift"]),
                           ("fact_survey", bi["survey"]), ("fact_simulation_replication", reps), ("dim_simulation_run", sim_cfg)):
            export_csv(out / f"{name}.csv", rows)
        for key, rows in dims.items():
            export_csv(out / f"{key.split('__')[1]}.csv", rows)
        print(f"wrote the BI CSV exports to {out}", file=sys.stderr)

    print("### reconciliation\n\n" + table(rec.rows) + "\n")
    results["meta"] = [{"dataset_hash": DATASET_HASH, "dataset_version": ctx.manifest["dataset_version"], "code_revision": CODE_REVISION,
                        "seeded_database_version": db_version["dataset_version"], "seeded_database_hash": db_version["dataset_hash"],
                        "seed": 20261026, "analysis_window_utc": "[2026-07-06T00:00:00Z, 2026-09-28T00:00:00Z)", "reconciliation_rows": len(rec.rows)}]
    results["known_differences"] = known_differences
    results["reconciliation"] = rec.rows
    results["golden_reference_metrics"] = golden_rows
    results["reference_metrics_snapshot"] = [{"window": n, **{k: v for k, v in ref[n].items() if not isinstance(v, dict)},
                                              "backlog": json.dumps(ref[n]["backlog"], sort_keys=True)} for n in ("full", "training", "holdout")]
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(
            results, indent=1, default=lambda o: format(o, "f") if isinstance(o, Decimal) else str(o)) + "\n")
    print(f"RESULT: {'OK' if rec.ok else 'MISMATCH'} ({len(rec.rows)} reconciliation rows, {sum(1 for r in rec.rows if r['equal'])} equal)")
    return 0 if rec.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
