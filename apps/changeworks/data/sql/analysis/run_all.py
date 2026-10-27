"""Run every analysis investigation and reconcile it with the independent sources (P09-ART-04).

Usage (from apps/changeworks):
  ../../.venv/bin/python data/sql/analysis/run_all.py [--json artifacts/analysis-results.json] [--bi-out artifacts/bi] [--keep]

With no environment variables it creates two scratch databases (artifacts09_run_snapshot, artifacts09_run_golden) on the local PostgreSQL named by ARTIFACTS_ADMIN_URL (default: the
repository's local development login, 127.0.0.1:5432), loads the published snapshot ``web/public/data`` and the golden fixture through ``data/migrate.py`` and ``data/seed.py``
(prepare_snapshot.py), runs everything and drops them again (``--keep`` leaves them). To use databases you prepared yourself, set ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL
(names must start with artifacts09_; the shared changeworks database is never touched).

What runs, in order (exit code 0 only if every query ran and every reconciliation row is equal):
  00_portfolio_model.sql (the scenario model in temporary tables cw_*), 01..09 and 11 on the snapshot (files hold several blocks marked ``-- @@ name``), 10 on the golden database, leaves.sql on both
  (the model's figures as expected.json leaf paths), data/sql/reference_metrics.sql on both, bi_dimensions.sql and bi_fact_*.sql on the snapshot (written as CSV with --bi-out).
Reconciliation (the rows printed at the end, ``reconciliation`` in the JSON):
  A  golden fixture: the analysis leaves = the reference SQL = the Python domain = tests/fixtures/golden/expected.json, family by family; investigation 10 equals expected.json and the hand
     answers of CALCULATION.md (NPV 5000/121 = 41.32, simple payback 2 / 1.6667, discounted payback 2 / 1.9167, attributable NPV -8300/11 = -754.55);
  B  snapshot: the analysis leaves = the reference SQL = the Python domain for every scenario and figure family, and the headline result sets row by row against the domain;
  C  every result set cell by cell against python_side.py (plain Python from the raw JSON rows, no SQL and no domain code);
  D  the designed relationships (DR-01..DR-07), the injection manifest checks (INJ-01..INJ-12) and the manifest statistics against what the SQL finds;
  E  the BI measures recomputed from the CSV facts against the analysis, the reference and the domain.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from fractions import Fraction as F
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(HERE)]

import python_side as ps  # noqa: E402
from prepare_snapshot import DEFAULT_ADMIN_URL, create_database, drop_database, prepare, snapshot_inputs, with_db  # noqa: E402
from changeworks import run_pipeline  # noqa: E402
from changeworks.timeutil import parse_ts  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
SNAP_DIR = ROOT / "web" / "public" / "data"
CODE_REVISION = "29948f9"
CODE_SHA = "29948f92f0c3839f070e4b6499b99f3810d1361b"
DATASET_HASH = "6bf7ebaad6bf75084c82c41de1031d6d585af730c8a22979ed7c77df2a38e3a9"
DATASET_VERSION = "cw-20261026-20261026"
RUN_SNAPSHOT_DB, RUN_GOLDEN_DB = "artifacts09_run_snapshot", "artifacts09_run_golden"
AS_OF = "2026-10-05T00:00:00Z"
SNAPSHOT_FILES = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "11"]
GOLDEN_FILE = "10"
BI_FILES = ["bi_dimensions", "bi_fact_scenario", "bi_fact_scenario_initiative", "bi_fact_cash_flow", "bi_fact_double_count", "bi_fact_realisation", "bi_fact_adoption", "bi_fact_forecast",
            "bi_fact_resource", "bi_fact_risk"]
FAMILIES = {
    "cash flow (costs, benefits entering, net, cumulative, discounted, cumulative discounted)": r"\.cash_flow\[",
    "NPV": r"\.npv\.value$",
    "simple and discounted payback (period, interpolation, reason)": r"\.payback\.",
    "beside the cash flow (capacity hours not converted, avoided cost)": r"\.excluded_from_cash_flow\.",
    "capacity released": r"\.capacity_released\.",
    "cost variance": r"\.cost_variance\.",
    "benefit realisation within a type": r"\.benefit_realization\.",
    "double count (money and hours)": r"\.double_count\.",
    "portfolio NPV (attributable and plain sum)": r"\.npv_total\.",
}
INIT_FAMILIES = {"adoption": r"^metrics\.initiatives\.[^.]+\.adoption\.", "training completion": r"^metrics\.initiatives\.[^.]+\.training\.",
                 "roadmap (feasible start, delay, binding dependency)": r"^metrics\.initiatives\.[^.]+\.roadmap\.", "summary pools": r"^metrics\.summary\."}


def fmt(v) -> str:
    return ps.norm(v)


def canon(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def digest(v) -> str:
    return hashlib.sha256(canon(v).encode()).hexdigest()[:16]


def text(v):
    return None if v is None else str(v).lower() if isinstance(v, bool) else str(v)


def blocks(path: Path) -> list[tuple[str | None, str]]:
    t = path.read_text()
    parts = re.split(r"(?m)^-- @@ (\w+)\n", t)
    return [(None, t)] if len(parts) == 1 else [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def run_file(conn, path: Path) -> dict[str, list[dict]]:
    out = {}
    for name, sql in blocks(path):
        out[path.stem if name is None else f"{path.stem}__{name}"] = [dict(r) for r in conn.execute(sql).fetchall()]
    return out


def run_script(conn, path: Path) -> None:
    """Execute every block of a file that creates temporary tables (00_portfolio_model.sql); nothing is fetched."""
    for _, sql in blocks(path):
        conn.execute(sql)


def leaves(conn) -> dict[str, str | None]:
    return {r["path"]: r["val"] for r in conn.execute((HERE / "leaves.sql").read_text()).fetchall()}


def reference(conn, as_of: str) -> dict[str, str | None]:
    conn.execute("SET jit = off")
    rows = conn.execute(REFERENCE.read_text(), {"as_of": parse_ts(as_of)}).fetchall()
    return {r["path"]: r["val"] for r in rows}


def flat(x, path: str = "") -> dict:
    """Every leaf of a JSON value by path (the nesting tests/support_db.py uses)."""
    if isinstance(x, dict):
        if not x:
            return {path + "{}": "empty"}
        out: dict = {}
        for k, v in x.items():
            out.update(flat(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(x, list):
        if not x:
            return {path + "[]": "empty"}
        out = {}
        for i, v in enumerate(x):
            out.update(flat(v, f"{path}[{i}]"))
        return out
    return {path: x}


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


def export_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        cols = list(rows[0])
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r[c]) for c in cols])


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


# ---- BI measures from the exported facts (no database, no domain): exact arithmetic over the CSV strings ---------------------------------------------------------------
def dx(s: str) -> F:
    return F(0) if s in ("", None) else ps.dec(s)


def bi_measures(csvs: dict[str, list[dict]]) -> list[dict]:
    """The measures of docs/bi-package.md evaluated over the CSV facts. Every row has a status and a scope; nothing is dropped: a zero denominator, an initiative with no record or a
    series that never recovers is stated, never shown as 0."""
    rows: list[dict] = []

    def add(measure: str, slice_: str, value, scope: str, num=None, den=None, status: str = "value", note: str = "") -> None:
        rows.append({"measure": measure, "slice": slice_, "value": "" if value is None else fmt(value), "numerator": "" if num is None else fmt(num),
                     "denominator": "" if den is None else fmt(den), "status": status, "scope": scope, "note": note})

    scen = {s["scenario_id"]: s for s in csvs["dim_scenario"]}
    fsi = csvs["fact_scenario_initiative"]
    cf = csvs["fact_cash_flow"]
    dc = csvs["fact_double_count"]
    for sid in sorted(scen):
        s = scen[sid]
        q = 1 + dx(s["period_rate"])
        scope = f"scenario {sid}: {s['initiatives']} initiatives, {s['horizon_periods']} monthly periods, period rate {s['period_rate']} ({s['rate_source']}); plan estimate in USD"
        rows_i = [r for r in fsi if r["scenario_id"] == sid]
        flows = [r for r in cf if r["scenario_id"] == sid]
        sums = {k: sum((dx(r[k]) for r in flows), F(0)) for k in ("costs", "cash", "revenue", "avoided_cost_realised", "capacity_converted")}
        beside = sum((dx(r["avoided_cost_beside"]) for r in rows_i), F(0))
        hours_nc = sum((dx(r["capacity_hours_not_converted"]) for r in rows_i), F(0))
        planned = sums["cash"] + sums["revenue"] + sums["avoided_cost_realised"] + sums["capacity_converted"] + beside
        claims = [r for r in dc if r["scenario_id"] == sid]
        removed = sum((dx(r["amount"]) for r in claims if r["rule"] == "money" and r["retained"] == "0"), F(0))
        hours_removed = sum((dx(r["amount"]) for r in claims if r["rule"] == "hours" and r["retained"] == "0"), F(0))
        pv = sum((dx(r["amount"]) / q ** int(r["period_index"]) for r in claims if r["rule"] == "money" and r["retained"] == "0" and r["enters_cash_flow"] == "1"), F(0))
        with_flows = {r["initiative_id"] for r in rows_i if r["has_flows"] == "1"}
        npv_sum = sum((dx(r["net_cash_flow"]) / q ** int(r["period_index"]) for r in flows if r["initiative_id"] in with_flows), F(0))
        add("Planned Costs", sid, ps.rnd(sums["costs"], 2), scope, note="planned cost rows inside the horizon, recurring rows expanded over [start, end)")
        for k, label in (("cash", "Cash Benefits"), ("revenue", "Revenue Benefits"), ("avoided_cost_realised", "Avoided Cost Realised"), ("capacity_converted", "Capacity Converted")):
            add(label, sid, ps.rnd(sums[k], 2), scope, note="enters the net cash flow; ramped")
        add("Avoided Cost Beside", sid, ps.rnd(beside, 2), scope, note="reported beside the cash flow, never in it")
        add("Capacity Hours Not Converted", sid, ps.rnd(hours_nc, 2), scope.replace("in USD", "in hours"), note="hours, never added to dollars")
        add("Planned Benefits", sid, ps.rnd(planned, 2), scope, note="the plain sum of the money claims (four classes entering plus the avoided cost beside); hours excluded")
        add("Double Counted Amount", sid, ps.rnd(removed, 2), scope, note="claims sharing a source key in one period, beyond the largest")
        add("Attributable Benefits", sid, ps.rnd(planned - removed, 2), scope)
        add("Hours Residual", sid, ps.rnd(hours_removed, 2), scope.replace("in USD", "in hours"))
        add("NPV Sum Of Initiatives", sid, ps.rnd(npv_sum, 2) if with_flows else None, scope, status="value" if with_flows else "null: no flows",
            note="from the exact net_cash_flow and the exact period_rate, not from the rounded discounted column")
        add("Double Counted PV", sid, ps.rnd(pv, 2), scope)
        add("Attributable NPV", sid, ps.rnd(npv_sum - pv, 2) if with_flows else None, scope, status="value" if with_flows else "null: no flows", note="the headline: the plain sum less the present value counted twice")
    s25 = [r for r in fsi if r["scenario_id"] == "scn-025"]
    sc25 = "scenario scn-025: 24 initiatives, 36 monthly periods, period rate 0.006434 (8 % annual converted); plan estimate"
    add("Initiatives Never Paying Back", "scn-025", sum(1 for r in s25 if r["simple_payback_period"] == ""), sc25, den=len(s25), note="simple payback null (NOT_RECOVERED); never 0")
    for r in s25:
        if r["simple_payback_period"] == "":
            add("Simple Payback", r["initiative_id"] + "|scn-025", None, sc25, status="null: " + r["simple_payback_reason"], note="the last crossing from below zero")
        else:
            add("Simple Payback", r["initiative_id"] + "|scn-025", r["simple_payback_interpolated"], sc25, note=f"period {r['simple_payback_period']}, interpolated")
    obs_scope = "scn-025, matured periods 0..8 at the as-of 2026-10-05; observed, not attributed"
    for r in csvs["fact_realisation"]:
        if r["scenario_id"] != "scn-025" or r["benefit_type"] != "cash":
            continue
        if r["compared_rows"] == "0":
            add("Benefit Realisation", r["initiative_id"] + "|cash", None, obs_scope, status="null: no comparable matured row with an observation")
            continue
        p, o = dx(r["planned_comparable"]), dx(r["observed_comparable"])
        add("Benefit Realisation", r["initiative_id"] + "|cash", ps.rnd(o / p, 6) if p else None, obs_scope, ps.rnd(o, 2), ps.rnd(p, 2), status="value" if p else "null: zero planned")
        if r["baseline_trend"] != "" and o != 0:
            add("Baseline Trend Share", r["initiative_id"] + "|cash", ps.rnd(dx(r["baseline_trend"]) / o, 6), obs_scope, ps.rnd(dx(r["baseline_trend"]), 2), ps.rnd(o, 2),
                note="the recorded pre-deployment trend over the raw observed change; shown beside it, never in place of it")
    ad = csvs["fact_adoption"]
    a = [r for r in ad if r["adoption_status"] == "value"]
    t = [r for r in ad if r["training_status"] == "value"]
    pop = "the latest record of each initiative at or before the as-of 2026-10-05; observed"
    an, aden = sum(int(r["adopted"]) for r in a), sum(int(r["adoption_eligible"]) for r in a)
    tn, tden = sum(int(r["training_completed"]) for r in t), sum(int(r["training_eligible"]) for r in t)
    add("Adoption Rate", "pooled", ps.rnd(F(an, aden), 6), pop + f" ({len(a)} initiatives with an adoption series)", an, aden)
    add("Training Completion", "pooled", ps.rnd(F(tn, tden), 6), pop + f" ({len(t)} initiatives with a training record)", tn, tden, note="a separate series, never a substitute for adoption")
    both = [r for r in ad if r["adoption_status"] == "value" and r["training_status"] == "value"]
    bn, bden = sum(int(r["training_completed"]) for r in both), sum(int(r["training_eligible"]) for r in both)
    add("Training Completion", "common population", ps.rnd(F(bn, bden), 6), pop + f" ({len(both)} initiatives with both series)", bn, bden)
    for r in ad:
        if r["adoption_status"] != "value":
            add("Adoption Rate", r["initiative_id"], None, pop, status="null: " + r["adoption_status"])
    fc = csvs["fact_forecast"]
    tot: dict[int, F] = {}
    for r in fc:
        if r["initiative_id"] == "init-003":
            tot[int(r["version_number"])] = tot.get(int(r["version_number"]), F(0)) + dx(r["amount"])
    for v in sorted(tot):
        add("Forecast Total", f"init-003|v{v}", ps.rnd(tot[v], 2), "init-003 forecast versions as stored; version 1 is the original", note="cash benefit forecast")
    add("Forecast Revision Change", "init-003|latest minus original", ps.rnd(tot[max(tot)] - tot[1], 2), "init-003 forecast versions as stored")
    res = [r for r in csvs["fact_resource"] if r["resource_id"] == "res-03" and r["at_capacity"] == "1"]
    add("Resource Periods At Capacity", "res-03", len(res), "allocations as stored (2.00 FTE capacity)", note="periods " + ",".join(r["period_index"] for r in res))
    add("Resource Periods Over Capacity", "all resources", sum(1 for r in csvs["fact_resource"] if r["over_capacity"] == "1"), "allocations as stored", note="refused at ingest; none is stored")
    risk = sum((dx(r["expected_loss"]) for r in csvs["fact_risk"]), F(0))
    add("Risk Exposure", "portfolio", ps.rnd(risk, 2), "120 risk items; probability x impact; a scenario estimate, not a forecast")
    return rows


def main(argv: list[str]) -> int:
    json_out = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    bi_out = Path(argv[argv.index("--bi-out") + 1]) if "--bi-out" in argv else None
    keep = "--keep" in argv
    admin = os.environ.get("ARTIFACTS_ADMIN_URL", DEFAULT_ADMIN_URL)
    snap_url, gold_url = os.environ.get("ARTIFACTS_DATABASE_URL"), os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL")
    created = []
    try:
        if not snap_url:
            create_database(admin, RUN_SNAPSHOT_DB)
            created.append(RUN_SNAPSHOT_DB)
            snap_url = with_db(admin, RUN_SNAPSHOT_DB)
        if not gold_url:
            create_database(admin, RUN_GOLDEN_DB)
            created.append(RUN_GOLDEN_DB)
            gold_url = with_db(admin, RUN_GOLDEN_DB)
        return _run(snap_url, gold_url, json_out, bi_out)
    finally:
        if not keep:
            for name in created:
                drop_database(admin, name)


def _family_rows(rec: Recon, label: str, mine: dict, ref: dict, dom: dict, exp: dict | None, scope: str, per_scenario: list[str] | None) -> None:
    for fam, pat in FAMILIES.items():
        keys = [p for p in mine if re.search(pat, p)]
        groups = {None: keys} if per_scenario is None else {s: [p for p in keys if p.startswith(f"metrics.scenarios.{s}.")] for s in per_scenario}
        for s, ks in groups.items():
            ks = sorted(ks)
            a = digest([(p, mine[p]) for p in ks])
            b = digest([(p, ref.get(p, "MISSING")) for p in ks])
            c = digest([(p, text(dom.get(p, "MISSING"))) for p in ks])
            d = digest([(p, text(exp.get(p, "MISSING"))) for p in ks]) if exp is not None else None
            where = scope if s is None else f"{s}"
            rec.add(f"{label} {fam} in {where}: {len(ks)} leaves (analysis leaves vs reference SQL vs Python domain{' vs expected.json' if exp is not None else ''}, digest)", a, b, c, d)
    for fam, pat in INIT_FAMILIES.items():
        ks = sorted(p for p in mine if re.search(pat, p))
        rec.add(f"{label} {fam}: {len(ks)} leaves (analysis leaves vs reference SQL vs Python domain{' vs expected.json' if exp is not None else ''}, digest)",
                digest([(p, mine[p]) for p in ks]), digest([(p, ref.get(p, "MISSING")) for p in ks]), digest([(p, text(dom.get(p, "MISSING"))) for p in ks]),
                digest([(p, text(exp.get(p, "MISSING"))) for p in ks]) if exp is not None else None)


def _run(snap_url: str, gold_url: str, json_out: Path | None, bi_out: Path | None) -> int:
    rec = Recon()
    R: dict[str, list[dict]] = {}
    prep_s, prep_g = prepare(snap_url, False), prepare(gold_url, True)
    print(f"snapshot prepared: {sum(prep_s['inserted'].values())} rows (dataset {prep_s['dataset_version']}, hash {prep_s['dataset_hash'][:12]}...)")
    print(f"golden prepared:   {sum(prep_g['inserted'].values())} rows (hash {prep_g['dataset_hash'][:12]}...)")
    inputs, manifest = snapshot_inputs()
    bi: dict[str, list[dict]] = {}
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_portfolio_model.sql")
        print("the scenario model built (cw_p, cw_scn, cw_pick, cw_model, cw_cost, cw_ben, cw_flow, cw_qpow, cw_dnum, cw_init, cw_exact, cw_claim, cw_hours, cw_dc, cw_scn_npv, cw_cap, cw_var, cw_obs, cw_real, cw_roadmap, cw_adopt, cw_train)")
        for prefix in SNAPSHOT_FILES:
            f = next(HERE.glob(f"{prefix}_*.sql"))
            R.update(run_file(c, f))
            print(f"ran {f.name}")
        for name in BI_FILES:
            for k, rows in run_file(c, HERE / f"{name}.sql").items():
                bi[k.split("__")[-1] if "__" in k else k.removeprefix("bi_")] = rows
        print("ran the BI dimension and fact queries")
        mine = leaves(c)
        ref = reference(c, AS_OF)
        print(f"leaves.sql: {len(mine)} leaves; reference_metrics.sql: {len(ref)} rows")
        counts = {t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in manifest["row_counts"]}
    with psycopg.connect(gold_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_portfolio_model.sql")
        G = run_file(c, next(HERE.glob(f"{GOLDEN_FILE}_*.sql")))
        g_inputs = json.loads((GOLDEN_DIR / "inputs.json").read_text())
        mine_g = leaves(c)
        ref_g = reference(c, g_inputs["as_of"])
    R.update(G)

    # ---- A: golden fixture ---------------------------------------------------------------------------------------------------------
    exp = json.loads((GOLDEN_DIR / "expected.json").read_text())
    dom_g = run_pipeline(g_inputs)
    fexp = flat(exp)
    fdom_g = flat({"metrics": dom_g.metrics, "empty_population": False})
    rec.add("A golden whole shape of expected.json: the Python domain's result.golden() vs the file (digest of all leaves)", digest(flat(dom_g.golden())), digest(fexp))
    rec.add("A golden leaves of the analysis model that are not in the reference SQL output (count)", sum(1 for p in mine_g if p not in ref_g), 0)
    rec.add("A golden leaves of the analysis model that are not leaves of expected.json (count)", sum(1 for p in mine_g if p not in fexp), 0)
    _family_rows(rec, "A golden", mine_g, ref_g, fdom_g, fexp, "scn-001", None)
    a1 = G["10_golden_known_answer__init001_answer"][0]
    e1 = exp["metrics"]["scenarios"]["scn-001"]["initiatives"]["init-001"]
    rec.add("A golden init-001 NPV | exact | simple period | simple interpolated | discounted period | discounted interpolated | hours excluded (10 vs expected.json vs the spec's hand answer)",
            f"{fmt(a1['npv'])}|{a1['npv_exact']}|{a1['simple_payback_period']}|{fmt(a1['simple_payback_interpolated'])}|{a1['discounted_payback_period']}|{fmt(a1['discounted_payback_interpolated'])}|{fmt(a1['capacity_hours_excluded'])}",
            f"{e1['npv']['value']}|{e1['npv']['exact']}|{e1['payback']['simple']['period']}|{e1['payback']['simple']['interpolated']}|{e1['payback']['discounted']['period']}|"
            f"{e1['payback']['discounted']['interpolated']}|{e1['excluded_from_cash_flow']['capacity_hours_not_converted']}",
            "41.32|5000/121|2|1.6667|2|1.9167|800.00")
    for r in G["10_golden_known_answer__cash_flow_init001"]:
        e = e1["cash_flow"][r["period_index"]]
        rec.add(f"A golden init-001 cash flow period {r['period_index']}: costs | benefits | net | cumulative | discount factor | discounted | cumulative discounted (10 vs expected.json)",
                "|".join(fmt(r[k]) for k in ("costs", "cash_benefits", "net_cash_flow", "cumulative", "discount_factor", "discounted_cash_flow", "cumulative_discounted")),
                "|".join(str(e[k]) for k in ("costs", "cash_benefits", "net_cash_flow", "cumulative", "discount_factor", "discounted_cash_flow", "cumulative_discounted")))
    hand = {"init-001": "41.32|5000/121", "init-002": "-57.85|-7000/121", "init-003": "-676.03|-81800/121"}
    for r in G["10_golden_known_answer__initiatives"]:
        e = exp["metrics"]["scenarios"]["scn-001"]["initiatives"][r["initiative_id"]]
        rec.add(f"A golden {r['initiative_id']} NPV | exact | both paybacks and reasons (10 vs expected.json; NPV vs CALCULATION.md parts a-c)",
                f"{fmt(r['npv'])}|{r['npv_exact']}|{fmt(r['simple_payback_period'])}|{fmt(r['simple_payback_interpolated'])}|{fmt(r['simple_reason'])}|{fmt(r['discounted_payback_period'])}|"
                f"{fmt(r['discounted_payback_interpolated'])}|{fmt(r['discounted_reason'])}",
                f"{e['npv']['value']}|{e['npv']['exact']}|{fmt(e['payback']['simple']['period'])}|{fmt(e['payback']['simple']['interpolated'])}|{fmt(e['payback']['simple']['reason'])}|"
                f"{fmt(e['payback']['discounted']['period'])}|{fmt(e['payback']['discounted']['interpolated'])}|{fmt(e['payback']['discounted']['reason'])}")
        rec.add(f"A golden {r['initiative_id']} NPV and exact rational (10 vs the hand answer)", f"{fmt(r['npv'])}|{r['npv_exact']}", hand[r["initiative_id"]])
    gp = G["10_golden_known_answer__portfolio"][0]
    en, ed = exp["metrics"]["scenarios"]["scn-001"]["npv_total"], exp["metrics"]["scenarios"]["scn-001"]["double_count"]
    rec.add("A golden portfolio: plain sum | double-counted PV | attributable NPV | exact | planned | residual | attributable benefits | hours | hours residual (10 vs expected.json vs the hand answer)",
            "|".join(fmt(gp[k]) for k in ("sum_of_initiatives", "double_counted_pv", "attributable_npv", "attributable_exact", "planned_benefits", "residual", "attributable_benefits", "planned_hours", "hours_residual")),
            f"{en['sum_of_initiatives']}|{ed['double_counted_pv']}|{en['value']}|{en['exact']}|{ed['planned_benefits']}|{ed['residual']}|{ed['attributable_benefits']}|{ed['planned_hours']}|{ed['hours_residual']}",
            "-692.56|61.98|-754.55|-8300/11|2195.00|75.00|2120.00|800.00|0.00")

    # ---- B: snapshot ------------------------------------------------------------------------------------------------------------------
    dom = run_pipeline(inputs)
    M = dom.metrics
    fdom = flat({"metrics": M, "empty_population": False})
    rec.add("B loaded row counts equal the manifest row_counts (every entity)", digest(sorted(counts.items())), digest(sorted(manifest["row_counts"].items())))
    rec.add("B leaves of the analysis model that are not in the reference SQL output (count)", sum(1 for p in mine if p not in ref), 0)
    rec.add("B leaves of the analysis model that are not leaves of the domain's metrics tree (count)", sum(1 for p in mine if p not in fdom), 0)
    _family_rows(rec, "B snapshot", mine, ref, fdom, None, "", sorted(M["scenarios"]))
    ex25 = {r["initiative_id"]: r["npv_exact"] for r in R["02_initiative_npv__scn025_exact"]}
    for r in R["02_initiative_npv__scn025"]:
        d = M["scenarios"]["scn-025"]["initiatives"][r["initiative_id"]]
        rec.add(f"B scn-025 {r['initiative_id']}: NPV and its exact rational (02 vs Python domain)", f"{fmt(r['npv'])}|{ex25[r['initiative_id']]}", f"{d['npv']['value']}|{d['npv']['exact']}")
        p6 = "metrics.scenarios.scn-025.initiatives." + r["initiative_id"] + ".npv.value_6dp"
        rec.add(f"B scn-025 {r['initiative_id']}: NPV (02 vs reference SQL) and the exact rational within the reference's documented 0.000001 USD of its 6-place NPV",
                f"{fmt(r['npv'])}|True", f"{ref['metrics.scenarios.scn-025.initiatives.' + r['initiative_id'] + '.npv.value']}|{abs(F(ex25[r['initiative_id']]) - F(ref[p6])) <= F(1, 1000000)}")
    for r in R["04_payback__scn025"]:
        d = M["scenarios"]["scn-025"]["initiatives"][r["initiative_id"]]["payback"]
        rec.add(f"B scn-025 {r['initiative_id']}: simple and discounted payback, interpolation and reason (04 vs Python domain)",
                "|".join(fmt(r[k]) for k in ("simple_payback_period", "simple_interpolated", "simple_reason", "discounted_payback_period", "discounted_interpolated", "discounted_reason")),
                "|".join(fmt(x) for x in (d["simple"]["period"], d["simple"]["interpolated"], d["simple"]["reason"], d["discounted"]["period"], d["discounted"]["interpolated"], d["discounted"]["reason"])))
    for r in R["01_portfolio_ledger__by_scenario"]:
        d = M["scenarios"][r["scenario_id"]]["double_count"]
        planned_dom = sum((F(x["planned_money_benefits"]["ramped"]) for x in M["scenarios"][r["scenario_id"]]["initiatives"].values()), F(0))
        rec.add(f"B {r['scenario_id']} ledger: planned benefits | attributable | residual | planned hours | hours residual (01 vs Python domain double_count)",
                "|".join(fmt(r[k]) for k in ("planned_benefits", "attributable_benefits", "double_counted_amount", "capacity_hours_planned", "hours_residual")),
                f"{d['planned_benefits']}|{d['attributable_benefits']}|{d['residual']}|{d['planned_hours']}|{d['hours_residual']}")
        rec.add(f"B {r['scenario_id']} ledger: planned benefits within the rounding of the domain's per-initiative 2-place figures (|01 - sum of rounded rows| <= 0.005 x initiatives)",
                abs(F(fmt(r["planned_benefits"])) - planned_dom) <= F(5, 1000) * len(M["scenarios"][r["scenario_id"]]["initiatives"]), True)
    for r in R["02_initiative_npv__by_scenario"]:
        n = M["scenarios"][r["scenario_id"]]["npv_total"]
        rec.add(f"B {r['scenario_id']} portfolio NPV: attributable | plain sum | double-counted PV (02 vs Python domain vs reference SQL)",
                f"{fmt(r['attributable_npv'])}|{fmt(r['sum_of_initiatives'])}|{fmt(r['double_counted_pv'])}",
                f"{n['value']}|{n['sum_of_initiatives']}|{M['scenarios'][r['scenario_id']]['double_count']['double_counted_pv']}",
                f"{ref['metrics.scenarios.' + r['scenario_id'] + '.npv_total.value']}|{ref['metrics.scenarios.' + r['scenario_id'] + '.npv_total.sum_of_initiatives']}|"
                f"{ref['metrics.scenarios.' + r['scenario_id'] + '.double_count.double_counted_pv']}")
    exs = {r["scenario_id"]: r["attributable_exact"] for r in R["02_initiative_npv__by_scenario_exact"]}
    rec.add("B the exact attributable NPV of all 30 scenarios (02 vs Python domain npv_total.exact, digest)", digest(sorted(exs.items())),
            digest(sorted((s, x["npv_total"]["exact"]) for s, x in M["scenarios"].items() if x["npv_total"]["exact"] is not None)))
    for r in R["07_adoption_training__by_initiative"]:
        a, t = M["initiatives"][r["initiative_id"]]["adoption"], M["initiatives"][r["initiative_id"]]["training"]
        rec.add(f"B {r['initiative_id']} adoption eligible | adopted | rate | training eligible | completed | rate (07 vs Python domain)",
                "|".join(fmt(r[k]) for k in ("adoption_eligible", "adopted", "adoption_rate", "training_eligible", "training_completed", "training_completion")),
                "|".join(fmt(x) for x in (a["eligible_count"], a["adopted_count"], a["adoption_rate"], t["eligible_trainees"], t["completed"], t["training_completion"])))
    for r in R["09_roadmap_capacity__dependency_delay"]:
        d = M["initiatives"][r["initiative_id"]]["roadmap"]
        rec.add(f"B {r['initiative_id']} roadmap: feasible start | delay | binding dependency | finish | deployment before feasible start (09 vs Python domain)",
                f"{r['dependency_feasible_start']}|{r['dependency_delay']}|{fmt(r['binding_dependency_id'])}|{r['finish']}|{fmt(r['deployment_before_feasible_start'])}",
                f"{d['dependency_feasible_start']}|{d['dependency_delay']}|{fmt(d['binding_dependency_id'])}|{d['finish']}|{fmt(bool(d['warnings']))}")
    for r in R["11_proposal_screen__initiative_screen"]:
        dm = M["initiatives"][r["initiative_id"]]
        rec.add(f"B {r['initiative_id']} screen inputs: risk exposure | cost variance | cash realisation (11 vs Python domain)",
                f"{fmt(r['risk_exposure'])}|{fmt(r['cost_variance'])}|{fmt(r['cash_realisation'])}",
                f"{fmt(dm['risk']['risk_exposure'])}|{fmt(M['scenarios']['scn-025']['initiatives'][r['initiative_id']]['cost_variance']['variance'])}|"
                f"{fmt((M['scenarios']['scn-025']['initiatives'][r['initiative_id']]['benefit_realization'].get('cash') or {}).get('realization'))}")
    for r in R["08_forecast_revisions__original_preserved"]:
        fz = M["initiatives"][r["initiative_id"]]["forecast"]
        rec.add(f"B {r['initiative_id']} forecast: versions | original preserved | covers the original periods | latest minus original (08 vs Python domain)",
                f"{r['versions']}|true|{fmt(r['every_version_covers_the_original_periods'])}|{fmt(r['latest_minus_original'])}",
                f"{len(fz['versions'])}|{fmt(fz['original_preserved'])}|{fmt(fz['revisions_cover_original_periods'])}|{fz['latest_minus_original']}")
    res03 = M["resources"]["res-03"]
    rec.add("B res-03 periods at capacity and their allocation (09 vs Python domain)", ",".join(f"{r['period_index']}:{fmt(r['allocated'])}" for r in R["09_roadmap_capacity__resource_at_capacity"]),
            ",".join(f"{b['period_index']}:{b['allocated']}" for b in res03["by_period"] if b["headroom"] == "0.00"))
    rec.add("B resources: periods over capacity in every resource (09 vs Python domain)", sum(int(r["periods_over_capacity"]) for r in R["09_roadmap_capacity__resources"]),
            sum(len(x["overallocated_periods"]) for x in M["resources"].values()))
    rec.add("B DEPLOYMENT_BEFORE_FEASIBLE_START warnings (09 vs Python domain warnings)", ",".join(r["initiative_id"] for r in R["09_roadmap_capacity__deployment_before_feasible_start"]),
            ",".join(sorted(w["path"].split(".")[2] for w in dom.warnings if w["code"] == "DEPLOYMENT_BEFORE_FEASIBLE_START")))

    # ---- C: every result set cell by cell against python_side.py -------------------------------------------------------------------
    P = ps.results()
    P.update(ps.golden_results())
    for key, prows in P.items():
        a, b = ps.normalised(R[key]), ps.normalised(prows)
        if a != b:
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print(f"DIFF {key} row {i}: SQL {x} / python {y}")
                    break
            else:
                print(f"DIFF {key}: {len(a)} SQL rows / {len(b)} python rows")
        rec.add(f"C {key}: {len(a)} row(s), every cell (SQL result set vs plain Python from the raw JSON)", digest(a), digest(b))
    missing = sorted(k for k in R if k not in P)
    assert not missing, f"result sets with no python-side counterpart: {missing}"

    # ---- D: designed relationships, the injection manifest and the manifest statistics -------------------------------------------------
    inj_doc = json.loads((SNAP_DIR / "injection-manifest.json").read_text())
    dr = {d["id"]: d["realised"] for d in inj_doc["designed_relationships"]}
    rec.add("D injection manifest and manifest carry the dataset hash and version of this package", f"{inj_doc['dataset_hash']}|{inj_doc['dataset_version']}",
            f"{manifest['dataset_hash']}|{manifest['dataset_version']}", f"{DATASET_HASH}|{DATASET_VERSION}")
    s25 = {r["initiative_id"]: r for r in R["01_portfolio_ledger__scn025_by_initiative"]}
    n25 = {r["initiative_id"]: r for r in R["02_initiative_npv__scn025"]}
    p25 = {r["initiative_id"]: r for r in R["04_payback__scn025"]}
    d1 = dr["DR-01"]
    rec.add("D DR-01 init-009 capacity only: hours not converted | cash benefits | NPV | simple payback (01, 02, 04 vs the manifest)",
            f"{fmt(s25['init-009']['capacity_hours_not_converted'])}|{fmt(n25['init-009']['cash_benefits_entering'])}|{fmt(n25['init-009']['npv'])}|{fmt(p25['init-009']['simple_payback_period'])}",
            f"{d1['capacity_hours_not_converted']}|{d1['cash_benefits_total']}|{d1['npv']}|{fmt(d1['simple_payback'])}")
    d2 = dr["DR-02"]
    pv = R["03_double_count__present_value_scn025"][0]
    key = R["03_double_count__by_source_key"][0]
    oc = R["03_double_count__outcome"][0]
    rec.add("D DR-02 shared capacity in scn-025: planned | attributable | residual | PV | hours residual | plain NPV sum | attributable NPV (03 vs the manifest)",
            "|".join(fmt(pv[k]) for k in ("planned_benefits", "attributable_benefits", "double_counted_amount", "double_counted_pv", "hours_residual", "npv_sum_of_initiatives", "npv_attributable")),
            f"{d2['planned_benefits']}|{d2['attributable_benefits']}|{d2['residual']}|{d2['double_counted_pv']}|{d2['hours_residual']}|{d2['npv_sum_of_initiatives']}|{d2['npv_total_attributable']}")
    rec.add("D DR-02 the key, its initiatives and periods: key | initiatives | first | last | overlapping periods (03 vs the manifest)",
            f"{key['benefit_source_key']}|{key['initiatives']}|{key['first_period']}|{key['last_period']}|{key['overlapping_periods']}",
            f"{d2['benefit_source_key']}|{','.join(d2['initiatives'])}|{d2['first_overlap_period']}|{d2['last_overlap_period']}|{d2['overlap_periods']}")
    rec.add("D DR-02 scenarios with a money residual | with an hours residual (03 vs the manifest)", f"{oc['money_residual_scenarios']}|{oc['hours_residual_scenarios']}",
            f"{','.join(d2['scenarios_with_a_residual'])}|{','.join(d2['scenarios_with_an_hours_residual'])}")
    d3 = dr["DR-03"]
    for r in R["04_payback__init015_by_scenario"]:
        x = d3["by_scenario"][r["scenario_id"]]
        rec.add(f"D DR-03 init-015 in {r['scenario_id']}: ramp | cost | benefits entering | benefit-to-cost | NPV | both paybacks null (04 vs the manifest)",
                f"{r['ramp_assumption_id']}|{fmt(r['planned_cost'])}|{fmt(r['benefits_entering_the_cash_flow'])}|{fmt(r['benefit_to_cost'])}|{fmt(r['npv'])}|{r['simple_payback_period'] is None and r['discounted_payback_period'] is None}",
                f"{x['ramp_assumption_id']}|{x['planned_cost']}|{x['benefits_entering_the_cash_flow']}|{x['benefit_to_cost']}|{x['npv']}|True")
    d4 = dr["DR-04"]
    v3 = R["08_forecast_revisions__init003_versions"]
    rec.add("D DR-04 init-003 forecast totals v1 | v2 | v3 | latest minus original (08 vs the manifest)", "|".join(fmt(r["total"]) for r in v3) + "|" + fmt(v3[-1]["change_vs_original"]),
            "|".join(v["total"] for v in d4["versions"]) + "|" + d4["latest_minus_original"])
    trig = [r for r in R["08_forecast_revisions__revision_triggers"] if r["initiative_id"] == "init-003"]
    rec.add("D DR-04 the misses behind each revision: periods checked | periods more than 10 % below | lowest and highest observed over forecast (08 vs the manifest)",
            ";".join(f"{r['periods_checked']}|{r['periods_more_than_10_percent_below']}|{fmt(r['lowest_observed_over_forecast'])}|{fmt(r['highest_observed_over_forecast'])}" for r in trig),
            ";".join(f"{','.join(map(str, m['periods_checked']))}|{','.join(map(str, m['periods_below_the_previous_forecast']))}|{min(m['observed_over_forecast'].values())}|"
                     f"{max(m['observed_over_forecast'].values())}" for m in d4["misses"]))
    rec.add("D DR-04 the latest observed cash value of each matured period (08 vs the manifest)",
            ",".join(f"{r['period_index']}:{fmt(r['latest_observed'])}" for r in R["08_forecast_revisions__init003_by_period"] if r["latest_observed"] is not None),
            ",".join(f"{k}:{v}" for k, v in d4["latest_observed"].items()))
    d5 = dr["DR-05"]
    rq = R["09_roadmap_capacity__refused_requests"]
    rec.add("D DR-05 res-03 at capacity: periods | allocated | headroom | refused requests | refused periods (09 vs the manifest)",
            f"{','.join(str(r['period_index']) for r in R['09_roadmap_capacity__resource_at_capacity'])}|{','.join(fmt(r['allocated']) for r in R['09_roadmap_capacity__resource_at_capacity'])}|"
            f"{','.join(fmt(r['headroom']) for r in R['09_roadmap_capacity__resource_at_capacity'])}|{sum(1 for r in rq if r['refused_overallocated'])}|{','.join(str(r['period_index']) for r in rq)}",
            f"{','.join(map(str, d5['periods']))}|{','.join(d5['allocated'].values())}|{','.join(d5['headroom'].values())}|{d5['requests_refused']}|{','.join(map(str, d5['refused_periods']))}")
    d6 = dr["DR-06"]
    tb = R["06_variance_realisation__trend_beside_raw"][0]
    r8 = next(r for r in R["06_variance_realisation__realisation_scn025"] if r["initiative_id"] == "init-008" and r["benefit_type"] == "cash")
    rec.add("D DR-06 init-008 cash: planned | observed | realisation | trend | above trend | trend share | rows | attribution (06 vs the manifest)",
            f"{fmt(r8['planned_comparable'])}|{fmt(tb['observed_comparable'])}|{fmt(tb['realisation'])}|{fmt(tb['baseline_trend'])}|{fmt(tb['observed_above_trend'])}|{fmt(tb['trend_share_of_observed'])}|{r8['compared_rows']}|{r8['attribution']}",
            f"{d6['planned_comparable']}|{d6['observed_comparable']}|{d6['realization']}|{d6['baseline_trend']}|{d6['observed_above_trend']}|{d6['trend_share_of_observed']}|{d6['comparable_rows']}|{d6['attribution']}")
    d7 = dr["DR-07"]
    po, ls = R["07_adoption_training__pooled"][0], R["07_adoption_training__lag_summary"][0]
    rec.add("D DR-07 pooled adoption | pooled training | lags | never reached half adoption (07 vs the manifest)",
            f"{fmt(po['adoption_rate_pooled'])}|{fmt(po['training_completion_pooled'])}|{ls['lag_periods_sorted']}|{ls['never_reached_half_adoption']}",
            f"{d7['adoption_rate_summary']}|{d7['training_completion_summary']}|{','.join(map(str, d7['lag_periods_sorted']))}|{','.join(d7['initiatives_whose_adoption_never_reached_50_percent'])}")
    lag = {r["initiative_id"]: r for r in R["07_adoption_training__lag_to_half_adoption"]}
    rec.add("D DR-07 per initiative: training 90 % on | adoption 50 % on | lag | periods since | training now | adoption now (07 vs the manifest, digest)",
            digest([[x["initiative_id"], lag[x["initiative_id"]]["training_90_percent_on"], lag[x["initiative_id"]]["adoption_50_percent_on"], fmt(lag[x["initiative_id"]]["lag_periods"]),
                     fmt(lag[x["initiative_id"]]["periods_since_training_90_percent"]), fmt(lag[x["initiative_id"]]["training_completion_now"]), fmt(lag[x["initiative_id"]]["adoption_rate_now"])] for x in d7["initiatives"]]),
            digest([[x["initiative_id"], x["training_90_percent_on"], x["adoption_50_percent_on"], fmt(x["lag_periods"]), fmt(x["periods_since_training_90_percent"]), x["training_completion_now"],
                     x["adoption_rate_now"]] for x in d7["initiatives"]]))
    st = manifest["stats"]
    bys = {r["scenario_id"]: r for r in R["02_initiative_npv__by_scenario"]}
    dcs = {r["scenario_id"]: r for r in R["03_double_count__by_scenario"]}
    led = {r["scenario_id"]: r for r in R["01_portfolio_ledger__by_scenario"]}
    for sid, x in sorted(st["scenarios"].items()):
        rec.add(f"D manifest stats.scenarios {sid}: attributable NPV | residual | period rate | horizon (02, 03, 01 vs the manifest)",
                f"{fmt(bys[sid]['attributable_npv'])}|{fmt(dcs[sid]['residual'])}|{fmt(led[sid]['period_rate'])}|{led[sid]['horizon_periods']}",
                f"{x['npv_total']}|{x['double_count_residual']}|{x['effective_period_rate']}|{x['horizon_periods']}")
    var25 = {r["initiative_id"]: r for r in R["06_variance_realisation__cost_variance_scn025"]}
    adt = {r["initiative_id"]: r for r in R["07_adoption_training__by_initiative"]}
    for iid, x in sorted(st["initiatives_in_scn-025"].items()):
        rec.add(f"D manifest stats initiatives_in_scn-025 {iid}: NPV | simple | discounted payback | cost variance | adoption | training (02, 04, 06, 07 vs the manifest)",
                f"{fmt(n25[iid]['npv'])}|{fmt(p25[iid]['simple_payback_period'])}|{fmt(p25[iid]['discounted_payback_period'])}|{fmt(var25[iid]['variance'])}|{fmt(adt[iid]['adoption_rate'])}|{fmt(adt[iid]['training_completion'])}",
                f"{x['npv']}|{fmt(x['simple_payback'])}|{fmt(x['discounted_payback'])}|{fmt(x['cost_variance'])}|{fmt(x['adoption_rate'])}|{fmt(x['training_completion'])}")
    rec.add("D manifest stats.deployment_before_feasible_start: initiative | deployment | feasible start | periods early (09 vs the manifest)",
            ";".join(f"{r['initiative_id']}|{r['deployment_period']}|{r['dependency_feasible_start']}|{r['periods_early']}" for r in R["09_roadmap_capacity__deployment_before_feasible_start"]),
            ";".join(f"{x['initiative_id']}|{x['deployment_period']}|{x['dependency_feasible_start']}|{x['periods_early']}" for x in st["deployment_before_feasible_start"]))
    rec.add("D manifest stats.summary: npv_total | hours residual | adoption | training (leaves of the summary scenario scn-001 vs the manifest)",
            f"{mine['metrics.summary.npv_total']}|{mine['metrics.summary.hours_residual']}|{mine['metrics.summary.adoption_rate']}|{mine['metrics.summary.training_completion']}",
            f"{st['summary']['npv_total']}|{st['summary']['hours_residual']}|{st['summary']['adoption_rate']}|{st['summary']['training_completion']}")
    rec.add("D manifest stats.forecast_version_sets (08 vs the manifest)", len(R["08_forecast_revisions__versions"]), st["forecast_version_sets"])
    covered = uncovered = 0
    for inj in inj_doc["injections"]:
        ok_rows = []
        for chk in inj["checks"]:
            p = chk["path"]
            if p in mine:
                covered += 1
                ok_rows.append((p, mine[p], text(chk["equals"]) if not isinstance(chk["equals"], (list, dict)) else canon(chk["equals"])))
            else:
                uncovered += 1
        if ok_rows:
            rec.add(f"D {inj['id']} ({inj['name']}): the {len(ok_rows)} dataset checks the analysis leaves cover (analysis vs the injection manifest, digest)",
                    digest([(p, a) for p, a, _ in ok_rows]), digest([(p, b) for p, _, b in ok_rows]))
    print(f"injection checks: {covered} covered by the analysis leaves, {uncovered} are list / identity paths read by the domain tests only")
    rc = R["09_roadmap_capacity__refused_cycle"][0]
    ev7 = next(e for e in inj_doc["events"] if e["event_id"] == "EV-07")["steps"][0]
    rec.add("D INJ-07 the refused edge closes the cycle the replay event lists (09 vs the injection manifest)", rc["cycle_it_would_close"].replace(" -> ", ","),
            ",".join(ev7["details"]["cycle"]))
    rec.add("D INJ-07 the stored graph has no cycle (09 cycle_check)", R["09_roadmap_capacity__cycle_check"][0]["cycles_found"], 0)
    ev11 = next(e for e in inj_doc["events"] if e["event_id"] == "EV-11")["steps"][0]
    k11 = R["05_cost_expansion__inj11_key"][0]
    rec.add("D INJ-11 the one-time cost key is stored once, in its first period (05 vs the injection manifest)", f"{k11['cost_id']}|{k11['period_index']}|{k11['rows_with_this_key']}|{k11['rows_in_period_5']}",
            f"{ev11['details']['first_cost_id']}|{ev11['details']['first_period']}|1|0")
    rec.add("D INJ-11 no one-time cost key repeats and no key is of two kinds (05)", f"{R['05_cost_expansion__one_time_rule'][0]['cost_keys_in_more_than_one_period']}|{R['05_cost_expansion__one_time_rule'][0]['cost_keys_of_two_kinds']}", "0|0")

    # ---- E: the BI package ----------------------------------------------------------------------------------------------------------
    csvs = {k: [{c: fmt(v) for c, v in r.items()} for r in rows] for k, rows in bi.items()}
    meas = bi_measures(csvs)
    mv = {(m["measure"], m["slice"]): m for m in meas}
    rec.add("E BI row counts: dim_initiative | dim_scenario | dim_period | dim_resource | fact_scenario | fact_scenario_initiative | fact_forecast | fact_risk | fact_adoption",
            "|".join(str(len(csvs[k])) for k in ("dim_initiative", "dim_scenario", "dim_period", "dim_resource", "fact_scenario", "fact_scenario_initiative", "fact_forecast", "fact_risk", "fact_adoption")),
            f"{manifest['row_counts']['initiatives']}|{manifest['row_counts']['scenario_versions']}|36|{manifest['row_counts']['resources']}|30|210|{manifest['row_counts']['forecast_versions']}|"
            f"{manifest['row_counts']['risk_items']}|{manifest['row_counts']['initiatives']}")
    rec.add("E BI fact_cash_flow rows equal the sum of the scenario horizons over their initiatives", len(csvs["fact_cash_flow"]),
            sum(int(s["horizon_periods"]) * int(s["initiatives"]) for s in csvs["dim_scenario"]))
    for sid in sorted(M["scenarios"]):
        n, d = M["scenarios"][sid]["npv_total"], M["scenarios"][sid]["double_count"]
        rec.add(f"E BI {sid}: attributable NPV | plain sum | PV | planned benefits | residual | hours residual (CSV facts vs 02/01 vs Python domain)",
                "|".join(mv[(m, sid)]["value"] for m in ("Attributable NPV", "NPV Sum Of Initiatives", "Double Counted PV", "Planned Benefits", "Double Counted Amount", "Hours Residual")),
                f"{fmt(bys[sid]['attributable_npv'])}|{fmt(bys[sid]['sum_of_initiatives'])}|{fmt(bys[sid]['double_counted_pv'])}|{fmt(led[sid]['planned_benefits'])}|{fmt(led[sid]['double_counted_amount'])}|{fmt(led[sid]['hours_residual'])}",
                f"{fmt(n['value'])}|{fmt(n['sum_of_initiatives'])}|{d['double_counted_pv']}|{d['planned_benefits']}|{d['residual']}|{d['hours_residual']}")
        rec.add(f"E BI {sid}: costs and the four classes and beside and hours not converted (CSV facts vs 01)",
                "|".join(mv[(m, sid)]["value"] for m in ("Planned Costs", "Cash Benefits", "Revenue Benefits", "Avoided Cost Realised", "Capacity Converted", "Avoided Cost Beside", "Capacity Hours Not Converted")),
                "|".join(fmt(led[sid][k]) for k in ("planned_costs", "cash", "revenue", "avoided_cost_realised", "capacity_converted", "avoided_cost_beside", "capacity_hours_not_converted")))
    rec.add("E BI pooled adoption | pooled training | common-population training (CSV facts vs 07 vs Python domain summary)",
            f"{mv[('Adoption Rate', 'pooled')]['value']}|{mv[('Training Completion', 'pooled')]['value']}|{mv[('Training Completion', 'common population')]['value']}",
            f"{fmt(po['adoption_rate_pooled'])}|{fmt(po['training_completion_pooled'])}|{fmt(R['07_adoption_training__common_population'][0]['training_completion_pooled'])}",
            f"{M['summary']['adoption_rate']}|{M['summary']['training_completion']}|{fmt(R['07_adoption_training__common_population'][0]['training_completion_pooled'])}")
    rec.add("E BI init-003 forecast totals and latest minus original (CSV facts vs 08)", "|".join(mv[("Forecast Total", f"init-003|v{v}")]["value"] for v in (1, 2, 3)) + "|" + mv[("Forecast Revision Change", "init-003|latest minus original")]["value"],
            "|".join(fmt(r["total"]) for r in v3) + "|" + fmt(v3[-1]["change_vs_original"]))
    rec.add("E BI res-03 periods at capacity | periods over capacity (CSV facts vs 09)", f"{mv[('Resource Periods At Capacity', 'res-03')]['value']}|{mv[('Resource Periods Over Capacity', 'all resources')]['value']}",
            f"{len(R['09_roadmap_capacity__resource_at_capacity'])}|{sum(int(r['periods_over_capacity']) for r in R['09_roadmap_capacity__resources'])}")
    rec.add("E BI risk exposure (CSV facts vs Python domain summary vs reference SQL)", mv[("Risk Exposure", "portfolio")]["value"], M["summary"]["risk_exposure_total"], ref["metrics.summary.risk_exposure_total"])
    rec.add("E BI scn-025 initiatives never paying back (CSV facts vs 04)", mv[("Initiatives Never Paying Back", "scn-025")]["value"], sum(1 for r in R["04_payback__scn025"] if r["simple_payback_period"] is None))
    real25 = {r["initiative_id"]: r for r in R["06_variance_realisation__realisation_scn025"] if r["benefit_type"] == "cash"}
    rec.add("E BI scn-025 cash realisation of every initiative with a matured cash row (CSV facts vs 06, digest)",
            digest(sorted((m["slice"].split("|")[0], m["value"]) for m in meas if m["measure"] == "Benefit Realisation")),
            digest(sorted((i, fmt(r["realisation"])) for i, r in real25.items())))
    rec.add("E BI nothing withheld silently: rows with an empty value | of them with a non-value status | rows with an empty scope",
            f"{sum(1 for m in meas if m['value'] == '')}|{sum(1 for m in meas if m['value'] == '' and m['status'] != 'value')}|{sum(1 for m in meas if not m['scope'])}",
            f"{sum(1 for m in meas if m['value'] == '')}|{sum(1 for m in meas if m['value'] == '')}|0")

    # ---- results -----------------------------------------------------------------------------------------------------------------------------------------
    equal = sum(1 for r in rec.rows if r["equal"])
    meta = {"dataset_hash": DATASET_HASH, "dataset_version": manifest["dataset_version"], "code_revision": CODE_REVISION, "code_sha": CODE_SHA, "contract_version": 1,
            "seed": inj_doc["seed"], "as_of": AS_OF, "golden_dataset_hash": prep_g["dataset_hash"], "initiatives": manifest["row_counts"]["initiatives"],
            "scenarios": manifest["row_counts"]["scenario_versions"], "analysis_leaves_snapshot": len(mine), "analysis_leaves_golden": len(mine_g),
            "reconciliation_rows": len(rec.rows), "reconciliation_equal": equal, "result_sets": len(R), "result_rows": sum(len(R[k]) for k in R)}
    for r in rec.rows:
        print(("OK   " if r["equal"] else "DIFF ") + r["check"] + (" | " + " | ".join(str(r[k]) for k in ("analysis_sql", "second_source", "third_source", "fourth_source") if r[k] != "") if not r["equal"] else ""))
    print(f"RESULT: {'OK' if rec.ok else 'FAILED'} ({len(rec.rows)} reconciliation rows, {equal} equal; {meta['result_sets']} result sets, {meta['result_rows']} rows; "
          f"{len(mine)} + {len(mine_g)} leaves equal to the reference SQL and the domain)")
    if bi_out:
        for k, rows in csvs.items():
            export_csv(bi_out / f"{k}.csv", rows)
        export_csv(bi_out / "measures_recomputed.csv", meas)
        print(f"wrote {len(csvs) + 1} CSV files to {bi_out}")
    if json_out:
        out = {"meta": [meta], **{k: ps.normalised(v) for k, v in R.items()}, "bi_measures": meas,
               "bi_measures_scn025": [m for m in meas if m["slice"] == "scn-025" or m["slice"].endswith("|scn-025")],
               "bi_measures_portfolio": [m for m in meas if not m["slice"].startswith("scn-") and not m["slice"].endswith("|scn-025")], "reconciliation": rec.rows}
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
        print(f"wrote {json_out}")
    return 0 if rec.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
