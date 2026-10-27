"""Run every analysis investigation and reconcile it with the independent sources (P06-ART-04).

Usage (from apps/productsignal):
  ../../.venv/bin/python data/sql/analysis/run_all.py [--json artifacts/analysis-results.json] [--bi-out artifacts/bi] [--keep]

With no environment variables it creates two scratch databases (artifacts06_run_snapshot, artifacts06_run_golden) on the local PostgreSQL named by
ARTIFACTS_ADMIN_URL (default: the repository's local development login, 127.0.0.1:5432), loads the published snapshot ``web/public/data`` and the golden fixture
through ``data/migrate.py`` and ``data/seed.py`` (prepare_snapshot.py), runs everything and drops them again (``--keep`` leaves them). To use databases you
prepared yourself, set ARTIFACTS_DATABASE_URL and ARTIFACTS_GOLDEN_DATABASE_URL (names must start with artifacts06_; the shared productsignal database is never touched).

What runs, in order (exit code 0 only if every query ran and every reconciliation row is equal):
  00_canonical_events.sql (the canonical log and the signups at seven cutoffs, into temporary tables), 01..08 on the snapshot (files hold several blocks marked
  ``-- @@ name``), 09 on the golden database, bi_dimensions.sql and bi_fact_*.sql on the snapshot (written as CSV with --bi-out).
Reconciliation (the rows printed at the end, ``reconciliation`` in the JSON):
  A  golden fixture: data/sql/reference_metrics.sql, the Python domain and tests/fixtures/golden/expected.json agree on every metric key, the tracking quality and the
     identity block; the plain recomputation of 09 equals the hand answer of expected.json (20 of 100 and 30 of 100, +10.00 pp, 0.500000, 5 of 20 on day 7);
  B  snapshot headline figures: the investigations vs data/sql/reference_metrics.sql vs the Python domain, at the as-of and at every logged run cutoff of both versions;
  C  every result set cell by cell against python_side.py (plain Python from the raw JSON rows, no SQL and no domain code);
  D  groups and weeks: plan x segment activation, the weekly cohort grid and the funnel gap sensitivity against the domain's own functions over a widened window;
  E  the injection manifest and the designed relationships against what the SQL finds, and the BI measures recomputed from the CSV facts against the reference and the domain.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import re
import sys
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(HERE)]

import python_side as ps  # noqa: E402
from prepare_snapshot import DEFAULT_ADMIN_URL, create_database, drop_database, prepare, snapshot_inputs, with_db  # noqa: E402
from productsignal import run_pipeline  # noqa: E402
from productsignal.contract import METRIC_KEYS  # noqa: E402
from productsignal.metrics import Ctx, compute as dcompute, funnel as dfunnel, guardrail_review, retention_grid, revenue_difference, week4_difference  # noqa: E402
from productsignal.models import parse_funnel, parse_windows  # noqa: E402
from productsignal.stats import newcombe as domain_newcombe, q as domain_q  # noqa: E402
from productsignal.timeutil import parse_ts  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
CODE_REVISION = "fdf911a"
DATASET_HASH = "12672f9c39402517083bbbbe9164cbefe3435361dff086eb0d9e16e60f9b66f8"
RUN_SNAPSHOT_DB, RUN_GOLDEN_DB = "artifacts06_run_snapshot", "artifacts06_run_golden"
V1, V2 = ps.V1, ps.V2
READS = [(V1, "an-001", "an-001"), (V1, "an-002", "an-002"), (V1, "an-003", "an-003"), (V1, "an-004", "an-004"), (V1, "as-of", None), (V2, "an-005", "an-005"), (V2, "as-of", None)]
RUN_KEY = {(V1, "an-001"): "an-001", (V1, "an-002"): "an-002", (V1, "an-003"): "an-003", (V1, "an-004"): "an-004", (V1, "as-of"): "asof-xv-001",
           (V2, "an-005"): "an-005", (V2, "as-of"): "asof-xv-002"}


def fmt(v) -> str:
    return ps.norm(v)


def canon(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def digest(v) -> str:
    return hashlib.sha256(canon(v).encode()).hexdigest()[:16]


def blocks(path: Path) -> list[tuple[str | None, str]]:
    text = path.read_text()
    parts = re.split(r"(?m)^-- @@ (\w+)\n", text)
    return [(None, text)] if len(parts) == 1 else [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def run_file(conn, path: Path) -> dict[str, list[dict]]:
    out = {}
    for name, sql in blocks(path):
        out[path.stem if name is None else f"{path.stem}__{name}"] = [dict(r) for r in conn.execute(sql).fetchall()]
    return out


def run_script(conn, path: Path) -> None:
    """Execute every block of a file that creates temporary tables (00_canonical_events.sql); nothing is fetched."""
    for _, sql in blocks(path):
        conn.execute(sql)


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


def reference(conn, cutoff: str, xv: str | None, run_id: str | None) -> dict:
    return dict(conn.execute(REFERENCE.read_text(), {"cutoff": parse_ts(cutoff), "xv": xv, "run_id": run_id}).fetchone())


def export_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        cols = list(rows[0])
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r[c]) for c in cols])


# ---- BI measures from the exported facts (no database, no domain) -----------------------------------------------------------------------------------------------
def bi_measures(fact_account: list[dict], fact_run: list[dict], fact_week: list[dict], dim_version: list[dict], dim_run: list[dict]) -> list[dict]:
    """The measures of docs/bi-package.md evaluated over the CSV facts (strings in, exact arithmetic); slice = run_key, run_key|arm or 'asof'."""
    rows: list[dict] = []

    def add(measure: str, slice_: str, value) -> None:
        rows.append({"measure": measure, "slice": slice_, "value": fmt(value)})
    ver = {v["experiment_version_id"]: v for v in dim_version}
    for run in dim_run:
        key, xv = run["run_key"], run["experiment_version_id"]
        z = Decimal(ver[xv]["z"])
        sub = [r for r in fact_run if r["run_key"] == key]
        sc, st = F(ver[xv]["allocation_control"]), F(ver[xv]["allocation_treatment"])
        n_c = sum(1 for r in sub if r["arm"] == "control")
        n_t = sum(1 for r in sub if r["arm"] == "treatment")
        n = n_c + n_t
        stat = (n_c - n * sc) ** 2 / (n * sc) + (n_t - n * st) ** 2 / (n * st) if n else None
        verdict = "INSUFFICIENT" if n == 0 or min(n * sc, n * st) < int(ver[xv]["srm_min_expected_cell"]) else ("MISMATCH" if ps.erfc_p(stat) < Decimal(ver[xv]["srm_p_threshold"]) else "OK")
        withheld = verdict == "MISMATCH"        # the sample ratio comes first: a MISMATCH shows no outcome measure (the facts keep their flags, the measures do not read them)
        cell = {}
        for arm in ("control", "treatment"):
            a = [r for r in sub if r["arm"] == arm]
            mat = [r for r in a if r["mature_7d"] == "1"]
            exp = sum(1 for r in mat if r["exposed"] == "1")
            cell[arm] = (len(a), len(mat), sum(1 for r in mat if r["activated_7d"] == "1"))
            s = f"{key}|{arm}"
            add("assigned_accounts", s, len(a))
            add("mature_accounts", s, len(mat))
            add("exposure_rate", s, ps.ratio6(exp, len(mat)))
            if withheld:
                continue
            act = cell[arm][2]
            el = [r for r in a if r["guardrail_eligible"] == "1"]
            err = sum(1 for r in el if r["errored"] == "1")
            rev = sum((Decimal(r["revenue_usd"]) for r in mat), Decimal(0))
            add("activated_accounts", s, act)
            add("conversion_rate", s, ps.ratio6(act, len(mat)))
            add("guardrail_error_rate", s, ps.ratio6(err, len(el)))
            add("revenue_per_assigned_account", s, ps.rnd(F(rev) / len(mat), 2) if mat else None)
        (_, nc, xc), (_, nt, xt) = cell["control"], cell["treatment"]
        add("assigned_accounts", key, n)
        add("srm_statistic", key, ps.rnd(stat, 6) if n else None)
        add("srm_verdict", key, verdict)
        if nc and nt and not withheld:
            d, lo, hi, pc = ps.newcombe(xt, nt, xc, nc, z)
            add("absolute_lift_pp", key, ps.rnd(d * 100, 2))
            add("relative_lift", key, ps.rnd(d / pc, 6) if pc > 0 else None)
            add("newcombe_low", key, ps.rnd(lo, 6))
            add("newcombe_high", key, ps.rnd(hi, 6))
    elig = [r for r in fact_account if r["is_internal"] == "0" and r["signup_at"] != ""]
    mat7 = [r for r in elig if r["mature_7d"] == "1"]
    add("activation_rate_all_signups", "asof", ps.ratio6(sum(1 for r in mat7 if r["activated_7d"] == "1"), len(mat7)))
    m7 = [r for r in elig if r["mature_day7"] == "1"]
    add("day7_retention", "asof", ps.ratio6(sum(1 for r in m7 if r["retained_day7"] == "1"), len(m7)))
    add("on_or_after_day7_retention", "asof", ps.ratio6(sum(1 for r in m7 if r["retained_on_or_after_day7"] == "1"), len(m7)))
    m35 = [r for r in elig if r["mature_week4"] == "1"]
    add("week4_retention", "asof", ps.ratio6(sum(1 for r in m35 if r["retained_week4"] == "1"), len(m35)))
    tot = {k: sum(int(w[k]) for w in fact_week) for k in ("rows_total", "duplicates_dropped", "canonical", "delayed_over_24h", "unknown_identity", "bot_excluded", "internal_excluded", "analysed")}
    for k, v in tot.items():
        add(k, "asof", v)
    return rows


def main(argv: list[str]) -> int:
    json_out = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    bi_out = Path(argv[argv.index("--bi-out") + 1]) if "--bi-out" in argv else None
    keep = "--keep" in argv
    admin = os.environ.get("ARTIFACTS_ADMIN_URL", DEFAULT_ADMIN_URL)
    snap_url, gold_url = os.environ.get("ARTIFACTS_DATABASE_URL"), os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL")
    created: list[str] = []
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


def _run(snap_url: str, gold_url: str, json_out: Path | None, bi_out: Path | None) -> int:
    rec = Recon()
    R: dict[str, list[dict]] = {}
    prep_s, prep_g = prepare(snap_url, False), prepare(gold_url, True)
    print(f"snapshot prepared: {prep_s['inserted']} (dataset {prep_s['dataset_version']})")
    print(f"golden prepared:   {prep_g['inserted']}")
    ctx = ps.load()
    inputs, manifest = snapshot_inputs()
    bi: dict[str, list[dict]] = {}
    ref: dict[tuple[str, str], dict] = {}
    extra: dict[str, object] = {}
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_canonical_events.sql")
        print("canonical events recomputed from facts (ps_cuts, ps_ev, ps_signup)")
        for f in sorted(HERE.glob("0[1-8]_*.sql")):
            R.update(run_file(c, f))
            print(f"ran {f.name}")
        for f in [HERE / "bi_dimensions.sql"] + sorted(HERE.glob("bi_fact_*.sql")):
            for k, rows in run_file(c, f).items():
                bi[k.split("__")[-1]] = rows
        print("ran the BI dimension and fact queries")
        for xv, label, rid in READS:
            ref[(xv, label)] = reference(c, ps.RUNS[label], xv, rid)
        ref[(V1, "inj-10 early read")] = reference(c, "2026-04-15T00:00:00Z", V1, None)
        print("reference_metrics.sql at every read")
        man = manifest
        inj = {i["id"]: i for i in json.loads((ROOT / "web" / "public" / "data" / "injection-manifest.json").read_text())["injections"]}
        asof = "2026-10-05T00:00:00Z"
        extra["inj05_dups"] = c.execute("SELECT count(*) AS n FROM ps_ev WHERE c = %s AND cls = 'duplicate' AND event_id = ANY(%s)", (asof, inj["INJ-05"]["record_ids"])).fetchone()["n"]
        d7 = inj["INJ-07"]["expected"]
        extra["inj07_attr"] = c.execute("SELECT count(*) AS n FROM ps_ev WHERE c = %s AND cls = 'analysed' AND u IS NOT NULL AND event_id = ANY(%s)", (asof, d7["attributed_by_link"])).fetchone()["n"]
        extra["inj07_remain"] = c.execute("SELECT count(*) AS n FROM ps_ev WHERE c = %s AND cls = 'analysed' AND u IS NULL AND event_id = ANY(%s)", (asof, d7["remain_anonymous"])).fetchone()["n"]
        d12 = inj["INJ-12"]["detail"]
        accts = [x["account_id"] for x in d12["late_returners"] + d12["timezone_edge"]]
        idx = c.execute("""WITH sg AS (SELECT s.acct, a.timezone AS tz, (s.at AT TIME ZONE a.timezone)::date AS d0 FROM ps_signup s JOIN accounts a ON a.account_id = s.acct
                                        WHERE s.c = %s AND s.acct = ANY(%s)),
                                ss AS (SELECT u.account_id AS acct, (x.started_at AT TIME ZONE sg.tz)::date - sg.d0 AS d FROM sessions x JOIN users u ON u.user_id = x.user_id JOIN sg ON sg.acct = u.account_id
                                       WHERE NOT u.bot_flag AND x.started_at < %s::timestamptz)
                           SELECT acct, array_agg(DISTINCT d ORDER BY d) AS idx FROM ss GROUP BY acct""", (asof, accts, asof)).fetchall()
        extra["inj12"] = {r["acct"]: r["idx"] for r in idx}
    with psycopg.connect(gold_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        G = run_file(c, HERE / "09_golden_known_answer.sql")
        g_inputs = json.loads((GOLDEN_DIR / "inputs.json").read_text())
        ref_g = reference(c, g_inputs["cutoff"], None, None)
    R.update(G)

    # ---- A: golden fixture ---------------------------------------------------------------------------------------------------------
    exp = json.loads((GOLDEN_DIR / "expected.json").read_text())
    dom_g = run_pipeline(g_inputs)
    for k in METRIC_KEYS:
        rec.add(f"A golden metric {k}: reference SQL = Python domain = expected.json (digest)", digest(ref_g[k]), digest(exp["metrics"][k]), digest(dom_g.metrics[k]))
    rec.add("A golden tracking_quality: reference SQL = Python domain = expected.json (digest)", digest(ref_g["tracking_quality"]), digest(exp["tracking_quality"]), digest(dom_g.tracking_quality))
    rec.add("A golden identity: reference SQL = Python domain = expected.json (digest)", digest(ref_g["identity"]), digest(exp["identity"]), digest(dom_g.identity))
    rec.add("A golden empty_population (reference SQL vs expected.json vs domain)", ref_g["empty_population"], exp["empty_population"], dom_g.empty_population)
    ev = exp["metrics"]["experiment"]["primary"]
    for r in R["09_golden_known_answer__golden_arms"]:
        v = ev["variants"][r["arm"]]
        rec.add(f"A golden {r['arm']}: assigned | mature | activated | conversion (09 vs expected.json vs domain)", f"{r['assigned']}|{r['mature']}|{r['activated']}|{fmt(r['conversion'])}",
                f"{v['assigned']}|{v['mature_units']}|{v['activated']}|{v['conversion']}",
                "|".join(str(x) for x in (dom_g.metrics["experiment"]["primary"]["variants"][r["arm"]][k] for k in ("assigned", "mature_units", "activated", "conversion"))))
    lf = R["09_golden_known_answer__golden_lift"][0]
    rec.add("A golden absolute lift (pp) | relative lift (09 vs expected.json vs domain)", f"{fmt(lf['absolute_lift_pp'])}|{fmt(lf['relative_lift'])}", f"{ev['absolute_lift_pp']}|{ev['relative_lift']}",
            f"{dom_g.metrics['experiment']['primary']['absolute_lift_pp']}|{dom_g.metrics['experiment']['primary']['relative_lift']}")
    rt, gr = exp["metrics"]["retention"], R["09_golden_known_answer__golden_retention"][0]
    rec.add("A golden retention cohort | day 7 retained | rate | on or after day 7 | week 4 (09 vs expected.json vs domain)",
            f"{gr['cohort_accounts']}|{gr['day7_retained']}|{fmt(gr['day7_rate'])}|{gr['on_or_after_day7_retained']}|{gr['week4_retained']}",
            f"{rt['cohort_accounts']}|{rt['day7']['retained']}|{rt['day7']['rate']}|{rt['on_or_after_day7']['retained']}|{rt['week4']['retained']}",
            f"{dom_g.metrics['retention']['cohort_accounts']}|{dom_g.metrics['retention']['day7']['retained']}|{dom_g.metrics['retention']['day7']['rate']}|"
            f"{dom_g.metrics['retention']['on_or_after_day7']['retained']}|{dom_g.metrics['retention']['week4']['retained']}")

    # ---- B: snapshot headline figures --------------------------------------------------------------------------------------------
    dom: dict[tuple[str, str], object] = {}
    for xv, label, rid in READS:
        inp = {**inputs, "analysis_plan": manifest["analysis_plans"][xv]}
        dom[(xv, label)] = run_pipeline(inp, cutoff=ps.RUNS[label], experiment_version_id=xv, run_id=rid)
    print("Python domain at every read")
    for xv, label, rid in READS:
        r, d = ref[(xv, label)], dom[(xv, label)]
        rec.add(f"B reference SQL equals the Python domain on the six metric keys at {xv} {label} (digest)", digest({k: r[k] for k in METRIC_KEYS}), digest(d.metrics))
        rec.add(f"B reference SQL equals the Python domain on tracking_quality and identity at {xv} {label} (digest)", digest([r["tracking_quality"], r["identity"]]),
                digest([d.tracking_quality, d.identity]))
    r0, d0 = ref[(V1, "as-of")], dom[(V1, "as-of")]
    w = R["01_activation_by_plan_and_segment__window_check"][0]
    for k_sql, k in (("signups", "signups"), ("immature", "immature_excluded"), ("mature", "mature_accounts"), ("activated", "activated"), ("activation_rate", "rate")):
        rec.add(f"B activation.{k} (01 window_check vs reference SQL vs domain)", w[k_sql], r0["activation"][k], d0.metrics["activation"][k])
    w = R["02_weekly_cohort_grid__window_check"][0]
    rr, dr = r0["retention"], d0.metrics["retention"]
    for k_sql, path in (("cohort_accounts", ("cohort_accounts",)), ("excluded_internal_accounts", ("excluded_internal_accounts",)), ("day7_mature", ("day7", "mature_accounts")),
                        ("day7_retained", ("day7", "retained")), ("day7_rate", ("day7", "rate")), ("on_or_after_day7_retained", ("on_or_after_day7", "retained")),
                        ("on_or_after_day7_rate", ("on_or_after_day7", "rate")), ("week4_mature", ("week4", "mature_accounts")), ("week4_retained", ("week4", "retained")),
                        ("week4_rate", ("week4", "rate"))):
        g = lambda m: m[path[0]] if len(path) == 1 else m[path[0]][path[1]]      # noqa: E731
        rec.add(f"B retention.{'.'.join(path)} (02 window_check vs reference SQL vs domain)", w[k_sql], g(rr), g(dr))
    steps_ref = {s["step"]: s for s in r0["funnel"]["steps"]}
    steps_dom = {s["step"]: s for s in d0.metrics["funnel"]["steps"]}
    for r in R["03_funnel_steps_and_exclusions__funnel_steps"]:
        rec.add(f"B funnel step {r['step']}: units | from previous | from first (03 vs reference SQL vs domain)", f"{r['units']}|{fmt(r['conversion_from_previous'])}|{fmt(r['conversion_from_first'])}",
                f"{steps_ref[r['step']]['units']}|{fmt(steps_ref[r['step']]['conversion_from_previous'])}|{steps_ref[r['step']]['conversion_from_first']}",
                f"{steps_dom[r['step']]['units']}|{fmt(steps_dom[r['step']]['conversion_from_previous'])}|{steps_dom[r['step']]['conversion_from_first']}")
    sc = R["03_funnel_steps_and_exclusions__signup_conversion"][0]
    rec.add("B signup_conversion visitors | signed up | rate (03 vs reference SQL vs domain)", f"{sc['visitors']}|{sc['signed_up']}|{fmt(sc['signup_conversion'])}",
            f"{r0['signup_conversion']['visitors']}|{r0['signup_conversion']['signed_up']}|{r0['signup_conversion']['rate']}",
            f"{d0.metrics['signup_conversion']['visitors']}|{d0.metrics['signup_conversion']['signed_up']}|{d0.metrics['signup_conversion']['rate']}")
    tq = [r for r in R["04_tracking_quality_by_week__by_week"] if r["week_start"] == "ALL"][0]
    for k_sql, k in (("rows_total", "rows_total"), ("duplicates_dropped", "duplicates_dropped"), ("canonical", "canonical"), ("delayed_over_24h", "delayed_over_24h"),
                     ("unknown_identity", "unknown_identity"), ("bot_excluded", "bot_events_excluded"), ("internal_excluded", "internal_events_excluded"), ("analysed", "analysed")):
        rec.add(f"B tracking_quality.{k} (04 by_week ALL vs reference SQL vs domain)", tq[k_sql], r0["tracking_quality"][k], d0.tracking_quality[k])
    idn = R["04_tracking_quality_by_week__identity_links"][0]
    for k in ("anonymous_events", "attributed_by_link", "remain_anonymous"):
        rec.add(f"B identity.{k} (04 identity_links vs reference SQL vs domain)", idn[k], r0["identity"][k], d0.identity[k])
    ex_tot = [r for r in R["03_funnel_steps_and_exclusions__exclusions_by_event"] if r["event_name"] == "ALL"][0]
    rec.add("B event exclusions: rows | duplicates | unknown | bot | internal | analysed (03 ALL vs reference SQL vs domain)",
            f"{ex_tot['rows_received']}|{ex_tot['duplicates_dropped']}|{ex_tot['unknown_identity']}|{ex_tot['bot_excluded']}|{ex_tot['internal_excluded']}|{ex_tot['analysed']}",
            "|".join(str(r0["tracking_quality"][k]) for k in ("rows_total", "duplicates_dropped", "unknown_identity", "bot_events_excluded", "internal_events_excluded", "analysed")),
            "|".join(str(d0.tracking_quality[k]) for k in ("rows_total", "duplicates_dropped", "unknown_identity", "bot_events_excluded", "internal_events_excluded", "analysed")))

    def exrow(ex: dict) -> str:
        p, s = ex["primary"], ex["srm"]
        v = p["variants"]
        return "|".join(fmt(x) for x in (ex["run"]["interim"], ex["run"]["prior_runs"], v["control"]["assigned"], v["treatment"]["assigned"], v["control"]["mature_units"], v["treatment"]["mature_units"],
                                         v["control"]["activated"], v["treatment"]["activated"], v["control"]["conversion"], v["treatment"]["conversion"], p["absolute_lift_pp"], p["relative_lift"],
                                         p["interval"]["low"], p["interval"]["high"], p["interval"]["includes_zero"], s["statistic"], s["p_value"], s["verdict"], ex["run"]["plan_frozen"], p["conclusive"]))

    def sqlrow(r: dict) -> str:
        return "|".join(fmt(r[k]) for k in ("interim", "prior_runs", "assigned_control", "assigned_treatment", "mature_control", "mature_treatment", "activated_control", "activated_treatment",
                                            "conversion_control", "conversion_treatment", "absolute_lift_pp", "relative_lift", "newcombe_low", "newcombe_high", "interval_includes_zero",
                                            "srm_statistic", "srm_p_value", "srm_verdict", "plan_frozen", "conclusive"))
    for r in R["05_experiment_v1_at_each_run_cutoff__lift_by_cutoff"]:
        rec.add(f"B experiment v1 at {r['run']}: interim | prior | assigned | mature | activated | conversion | lift | interval | SRM | plan frozen | conclusive (05 vs reference SQL vs domain)",
                sqlrow(r), exrow(ref[(V1, r["run"])]["experiment"]), exrow(dom[(V1, r["run"])].metrics["experiment"]))
    for r in R["05_experiment_v1_at_each_run_cutoff__arms_by_cutoff"]:
        a = ref[(V1, r["run"])]["experiment"]["primary"]["variants"][r["arm"]]
        b = dom[(V1, r["run"])].metrics["experiment"]["primary"]["variants"][r["arm"]]
        ex = lambda m: f"{m['assigned']}|{m['mature_units']}|{m['activated']}|{m['conversion']}|{m['wilson_95']['low']}|{m['wilson_95']['high']}"      # noqa: E731
        rec.add(f"B experiment v1 {r['run']} {r['arm']}: assigned | mature | activated | conversion | Wilson (05 vs reference SQL vs domain)",
                f"{r['assigned']}|{r['mature']}|{r['activated']}|{fmt(r['conversion'])}|{fmt(r['wilson_low'])}|{fmt(r['wilson_high'])}", ex(a), ex(b))
        e1, e2 = ref[(V1, r["run"])]["experiment"]["exposure"]["by_variant"][r["arm"]], dom[(V1, r["run"])].metrics["experiment"]["exposure"]["by_variant"][r["arm"]]
        rec.add(f"B experiment v1 {r['run']} {r['arm']}: exposed | exposure rate (05 vs reference SQL vs domain)", f"{r['exposed']}|{fmt(r['exposure_rate'])}", f"{e1['exposed']}|{e1['rate']}", f"{e2['exposed']}|{e2['rate']}")
    for r in R["06_experiment_v2_sample_ratio__srm_by_read"]:
        xv, label = r["experiment_version"], r["run"]
        s1, s2 = ref[(xv, label)]["experiment"]["srm"], dom[(xv, label)].metrics["experiment"]["srm"]
        f = lambda s: f"{s['observed']['control']}|{s['observed']['treatment']}|{s['expected']['control']}|{s['expected']['treatment']}|{s['statistic']}|{s['p_value']}|{s['df']}|{s['verdict']}"      # noqa: E731
        rec.add(f"B sample ratio {xv} {label}: observed | expected | statistic | p | df | verdict (06 vs reference SQL vs domain)",
                f"{r['observed_control']}|{r['observed_treatment']}|{fmt(r['expected_control'])}|{fmt(r['expected_treatment'])}|{fmt(r['statistic'])}|{fmt(r['p_value'])}|{r['df']}|{r['verdict']}", f(s1), f(s2))
    v2 = {r["arm"]: r for r in R["06_experiment_v2_sample_ratio__v2_population"]}
    v2d = dom[(V2, "as-of")].metrics["experiment"]
    rec.add("B v2 at the as-of: assigned | mature (06 v2_population vs reference SQL vs domain)", f"{v2['control']['assigned'] + v2['treatment']['assigned']}|{v2['control']['mature'] + v2['treatment']['mature']}",
            f"{ref[(V2, 'as-of')]['experiment']['assigned_units']}|{ref[(V2, 'as-of')]['experiment']['mature_units']}", f"{v2d['assigned_units']}|{v2d['mature_units']}")
    rec.add("B v2 at the as-of: treatment mature accounts (D-10: 87; 06 vs domain primary variants)", v2["treatment"]["mature"], v2d["primary"]["variants"]["treatment"]["mature_units"], 87)
    v2_ids = {a["assignment_id"] for a in inputs["assignments"] if a["experiment_version_id"] == V2}
    rec.add("B v2 at the as-of: exposures recorded on v2 assignments (06 v2_population vs the published exposures.json rows)", v2["control"]["exposed"] + v2["treatment"]["exposed"],
            sum(1 for x in inputs["exposures"] if x["assignment_id"] in v2_ids))
    for r in R["07_guardrail_and_revenue_per_arm__guardrail_by_cutoff"]:
        g1 = ref[(V1, r["run"])]["experiment"]["guardrail"]["by_variant"]
        d_ = dom[(V1, r["run"])]
        gr_ = guardrail_review(d_.metrics["experiment"], d_.population.plans[V1])
        rec.add(f"B guardrail v1 {r['run']}: eligible | errors | rates (07 vs reference SQL vs domain)", f"{r['eligible_control']}|{r['eligible_treatment']}|{r['errors_control']}|{r['errors_treatment']}|{fmt(r['error_rate_control'])}|{fmt(r['error_rate_treatment'])}",
                f"{g1['control']['eligible_units']}|{g1['treatment']['eligible_units']}|{g1['control']['units_with_error']}|{g1['treatment']['units_with_error']}|{g1['control']['error_rate']}|{g1['treatment']['error_rate']}",
                f"{gr_['by_variant']['control']['eligible_units']}|{gr_['by_variant']['treatment']['eligible_units']}|{gr_['by_variant']['control']['units_with_error']}|"
                f"{gr_['by_variant']['treatment']['units_with_error']}|{gr_['by_variant']['control']['error_rate']}|{gr_['by_variant']['treatment']['error_rate']}")
        rec.add(f"B guardrail v1 {r['run']}: difference pp | Newcombe | verdict (07 vs the domain's C09 review)", f"{fmt(r['difference_pp'])}|{fmt(r['newcombe_low'])}|{fmt(r['newcombe_high'])}|{r['verdict']}",
                f"{gr_['difference_pp']}|{gr_['interval']['low']}|{gr_['interval']['high']}|{gr_['verdict']}")
    for r in R["07_guardrail_and_revenue_per_arm__revenue_by_arm"]:
        a = ref[(V1, r["run"])]["experiment"]["revenue_per_assigned_account"]["by_variant"][r["arm"]]
        b = dom[(V1, r["run"])].metrics["experiment"]["revenue_per_assigned_account"]["by_variant"][r["arm"]]
        f = lambda m: f"{m['units']}|{m['total']}|{m['mean']}|{m['interval']['df']}|{m['interval']['t']}|{m['interval']['low']}|{m['interval']['high']}"      # noqa: E731
        rec.add(f"B revenue per account v1 {r['run']} {r['arm']}: units | total | mean | df | t | interval (07 vs reference SQL vs domain)",
                f"{r['units']}|{fmt(r['total_usd'])}|{fmt(r['mean_usd'])}|{r['df']}|{fmt(r['t_quantile'])}|{fmt(r['interval_low'])}|{fmt(r['interval_high'])}", f(a), f(b))
    for r in R["07_guardrail_and_revenue_per_arm__revenue_difference"]:
        d_ = dom[(V1, r["run"])]
        cx = Ctx(d_.population, parse_ts(ps.RUNS[r["run"]]), d_.computation.canon)
        rd = revenue_difference(cx, d_.population.plans[V1])
        rec.add(f"B revenue difference v1 {r['run']}: difference | Welch df | t | interval (07 vs the domain's revenue_difference)",
                f"{fmt(r['difference_usd'])}|{r['welch_df']}|{fmt(r['t_quantile'])}|{fmt(r['interval_low'])}|{fmt(r['interval_high'])}",
                f"{rd['difference']}|{rd['interval']['df']}|{rd['interval']['t']}|{rd['interval']['low']}|{rd['interval']['high']}")
    w4 = R["07_guardrail_and_revenue_per_arm__week4_by_arm"][0]
    cx = Ctx(d0.population, parse_ts(ps.ASOF), d0.computation.canon)
    wd = week4_difference(cx, d0.population.plans[V1])
    rec.add("B week-4 retention v1: mature | retained | rates | difference | Newcombe (07 vs the domain's week4_difference)",
            f"{w4['mature_control']}|{w4['mature_treatment']}|{w4['retained_control']}|{w4['retained_treatment']}|{fmt(w4['rate_control'])}|{fmt(w4['rate_treatment'])}|{fmt(w4['difference_pp'])}|{fmt(w4['newcombe_low'])}|{fmt(w4['newcombe_high'])}",
            f"{wd['by_variant']['control']['mature_units']}|{wd['by_variant']['treatment']['mature_units']}|{wd['by_variant']['control']['retained']}|{wd['by_variant']['treatment']['retained']}|"
            f"{wd['by_variant']['control']['rate']}|{wd['by_variant']['treatment']['rate']}|{wd['difference_pp']}|{wd['interval']['low']}|{wd['interval']['high']}")

    # ---- C: every result set cell by cell against python_side.py ------------------------------------------------------------------------------
    py = ps.compute(ctx)
    for key in ps.KEYS:
        a, b = [{k: fmt(v) for k, v in r.items()} for r in R[key]], ps.normalised(py[key])
        cols = len(a[0]) if a else 0
        diff = sum(1 for ra, rb in zip(a, b) for k in set(ra) | set(rb) if ra.get(k) != rb.get(k)) + abs(len(a) - len(b)) * cols
        rec.add(f"C {key}: {len(a)} rows, {sum(len(r) for r in a)} cells, cells differing from the Python side", diff, 0)

    # ---- D: groups and weeks against the domain's own functions ---------------------------------------------------------------------------------
    wide = copy.deepcopy(inputs["metric_windows"])
    wide["activation"] = {"from": "2026-01-01T00:00:00Z", "to": "2026-10-06T00:00:00Z", "window_days": 7}
    wide["retention"] = {"signup_from": "2026-01-01", "signup_to": "2026-10-06"}
    wres = run_pipeline({**inputs, "metric_windows": wide}, cutoff=ps.ASOF, experiment_version_id=V1)
    ww = parse_windows(wide)
    asof_dt = parse_ts(ps.ASOF)
    accts = wres.population.accounts
    for r in R["01_activation_by_plan_and_segment__plan_segment"]:
        allowed = {a.account_id for a in accts if not a.internal and (r["plan"] in ("ALL", a.plan)) and (r["segment"] in ("ALL", a.segment))}
        m = dcompute(wres.population, asof_dt, ww, None, V1, None, allowed=allowed).metrics["activation"]
        rec.add(f"D plan {r['plan']} x segment {r['segment']}: accounts | signed up | immature | mature | activated | rate (01 vs domain activation over the widened window)",
                f"{r['accounts']}|{r['signed_up']}|{r['immature']}|{r['mature']}|{r['activated']}|{fmt(r['activation_rate'])}",
                f"{len(allowed)}|{m['signups']}|{m['immature_excluded']}|{m['mature_accounts']}|{m['activated']}|{m['rate']}")
    cx = Ctx(wres.population, asof_dt, wres.computation.canon)
    grid = retention_grid(cx, ww)
    byw: dict[str, dict[str, list[int]]] = {}
    for row in grid["rows"]:
        d = date.fromisoformat(row["cohort"])
        wk = (d - timedelta(days=d.weekday())).isoformat()
        cells = byw.setdefault(wk, {"accounts": [0], **{n: [0, 0] for n in ("day1", "day7", "day14", "day28", "on_or_after_day7", "week4")}})
        cells["accounts"][0] += row["accounts"]
        for n in ("day1", "day7", "day14", "day28", "on_or_after_day7", "week4"):
            cells[n][0] += row["cells"][n]["mature_accounts"]
            cells[n][1] += row["cells"][n]["retained"]
    for r in R["02_weekly_cohort_grid__cohort_grid"]:
        if r["week_start"] == "ALL":
            continue
        g = byw[r["week_start"]]
        rec.add(f"D cohort week {r['week_start']}: accounts | day 1, 7, 14, 28, on or after day 7 and week 4, each mature/retained (02 vs domain retention_grid)",
                f"{r['accounts']}|" + "|".join(f"{r[n + '_mature']}/{r[n + '_retained']}" for n in ("day1", "day7", "day14", "day28", "on_or_after_day7", "week4")),
                f"{g['accounts'][0]}|" + "|".join(f"{g[n][0]}/{g[n][1]}" for n in ("day1", "day7", "day14", "day28", "on_or_after_day7", "week4")))
    fd = inputs["metric_windows"]["funnel"]
    dctx = Ctx(d0.population, asof_dt, d0.computation.canon)
    for r in R["03_funnel_steps_and_exclusions__funnel_gap_sensitivity"]:
        f = dfunnel(dctx, parse_funnel({**fd, "max_gap_hours": r["max_gap_hours"]}))
        u = [s["units"] for s in f["steps"]]
        rec.add(f"D funnel at a maximum gap of {r['max_gap_hours']} h: visit | signup | step 1 | activated | overall (03 vs the domain's funnel)",
                f"{r['visit']}|{r['signup']}|{r['onboarding_step_1']}|{r['activated']}|{fmt(r['overall_conversion'])}", f"{u[0]}|{u[1]}|{u[2]}|{u[3]}|{f['overall_conversion']}")

    # ---- E: the injection manifest, the designed relationships and the BI facts ---------------------------------------------------------------
    drs = {d["id"]: d["realised"] for d in manifest["designed_relationships"]}
    lift = {r["run"]: r for r in R["05_experiment_v1_at_each_run_cutoff__lift_by_cutoff"]}
    arms = {(r["run"], r["arm"]): r for r in R["05_experiment_v1_at_each_run_cutoff__arms_by_cutoff"]}
    for key in ("at_planned_end", "at_as_of"):
        run = "an-004" if key == "at_planned_end" else "as-of"
        d1 = drs["DR-01"][key]
        rec.add(f"E DR-01 {key}: control and treatment activated | assigned | lift pp | relative lift | Newcombe (SQL vs manifest)",
                f"{arms[(run, 'control')]['activated']}/{arms[(run, 'control')]['mature']}|{arms[(run, 'treatment')]['activated']}/{arms[(run, 'treatment')]['mature']}|{fmt(lift[run]['absolute_lift_pp'])}|"
                f"{fmt(lift[run]['relative_lift'])}|{fmt(lift[run]['newcombe_low'])}|{fmt(lift[run]['newcombe_high'])}|{fmt(lift[run]['interval_includes_zero'])}",
                f"{d1['arms']['control']['activated']}/{d1['arms']['control']['mature']}|{d1['arms']['treatment']['activated']}/{d1['arms']['treatment']['mature']}|{d1['absolute_lift_pp']}|"
                f"{d1['relative_lift']}|{d1['newcombe_95_low']}|{d1['newcombe_95_high']}|{fmt(d1['interval_includes_zero'])}")
    gap = drs["DR-01"]["instrumentation_gap_disclosure"]
    ga = {r["arm"]: r for r in R["05_experiment_v1_at_each_run_cutoff__gap_accounts"]}
    gl = {r["reading"]: r for r in R["05_experiment_v1_at_each_run_cutoff__gap_lift"]}
    for arm in ("control", "treatment"):
        b = gap["by_arm"][arm]
        rec.add(f"E INJ-10 / R6-08 gap accounts in {arm}: gap accounts | mature excluding gap | published activated | activated excluding gap (SQL vs manifest)",
                f"{ga[arm]['gap_accounts']}|{ga[arm]['mature_excluding_gap']}|{ga[arm]['activated']}|{ga[arm]['activated_excluding_gap']}",
                f"{b['gap_accounts']}|{b['mature_excluding_gap']}|{b['published_activated']}|{b['drawn_activated_excluding_gap']}")
    rec.add("E INJ-10 gap accounts, both arms (SQL vs manifest v1_gap_accounts)", sum(int(ga[a]["gap_accounts"]) for a in ga), gap["v1_gap_accounts"])
    drawn = (F(gap["by_arm"]["treatment"]["drawn_activated"], gap["by_arm"]["treatment"]["mature"]) - F(gap["by_arm"]["control"]["drawn_activated"], gap["by_arm"]["control"]["mature"])) * 100
    rec.add("E R6-08 published lift | lift excluding the gap accounts (SQL) vs the manifest; drawn lift recomputed from the manifest's drawn counts (constructed) vs its drawn_lift_pp",
            f"{fmt(gl['published (all mature accounts)']['absolute_lift_pp'])}|{fmt(gl['excluding the gap accounts from both arms']['absolute_lift_pp'])}|{ps.rnd(drawn, 2)}",
            f"{gap['published_lift_pp']}|{gap['lift_excluding_gap_accounts_pp']}|{gap['drawn_lift_pp']}")
    dd, dlo, dhi, _ = ps.newcombe(gap["by_arm"]["treatment"]["drawn_activated"], gap["by_arm"]["treatment"]["mature"], gap["by_arm"]["control"]["drawn_activated"],
                                  gap["by_arm"]["control"]["mature"], Decimal(manifest["analysis_plans"][V1]["z"]))
    rec.add("E R6-08 the drawn (constructed) Newcombe interval in percentage points, 86 of 200 against 63 of 200 (recomputed here) vs the interval the public case study states (+2.02 to +20.69)",
            f"{ps.rnd(dlo * 100, 2)}|{ps.rnd(dhi * 100, 2)}", "2.02|20.69")
    ex_gap = gl["excluding the gap accounts from both arms"]
    zf = F(manifest["analysis_plans"][V1]["z"])
    _, glo, ghi = domain_newcombe(int(ex_gap["activated_treatment"]), int(ex_gap["mature_treatment"]), int(ex_gap["activated_control"]), int(ex_gap["mature_control"]), zf)
    sl, sh = ps.newcombe(int(ex_gap["activated_treatment"]), int(ex_gap["mature_treatment"]), int(ex_gap["activated_control"]), int(ex_gap["mature_control"]), Decimal(manifest["analysis_plans"][V1]["z"]))[1:3]
    rec.add("E R6-08 Newcombe interval of the lift excluding the gap accounts, in percentage points (SQL counts through python_side vs the domain's statistics code vs the literal +0.35 to +19.32 quoted in the documents)",
            f"{ps.rnd(sl * 100, 2)}|{ps.rnd(sh * 100, 2)}", f"{domain_q(glo * 100, 2)}|{domain_q(ghi * 100, 2)}", "0.35|19.32")
    rec.add("E R6-08 drawn treatment activations = published activations + the drawn activations the gap suppressed (82 + 4; manifest arithmetic)", gap["by_arm"]["treatment"]["published_activated"] + gap["by_arm"]["treatment"]["gap_drawn_activations"],
            gap["by_arm"]["treatment"]["drawn_activated"])
    early = ref[(V1, "inj-10 early read")]["experiment"]
    d10 = inj["INJ-10"]
    rec.add("E INJ-10 early read at 2026-04-15: mature control | mature treatment | control conversion | relative lift is null (reference SQL vs manifest)",
            f"{early['primary']['variants']['control']['mature_units']}|{early['primary']['variants']['treatment']['mature_units']}|{early['primary']['variants']['control']['conversion']}|{fmt(early['primary']['relative_lift'])}",
            f"{d10['detail']['mature_control']}|{d10['detail']['mature_treatment']}|{d10['expected']['control_conversion']}|{fmt(d10['expected']['relative_lift'])}")
    rec.add("E INJ-04 immature signups in the activation window (01 vs manifest) and v2 assigned immature at the as-of (06 vs manifest)",
            f"{R['01_activation_by_plan_and_segment__window_check'][0]['immature']}|{sum(int(r['immature_or_unobserved']) for r in R['06_experiment_v2_sample_ratio__v2_population'])}",
            f"{inj['INJ-04']['expected']['activation_immature_excluded']}|{inj['INJ-04']['expected']['v2_immature_or_unobserved_excluded']}")
    rec.add("E INJ-05 re-sent `activated` events dropped as duplicates (SQL rows among the manifest's ids | manifest ids) and duplicates dropped at the as-of (04 | manifest)",
            f"{extra['inj05_dups']}|{tq['duplicates_dropped']}", f"{len(inj['INJ-05']['record_ids'])}|{inj['INJ-05']['expected']['duplicates_dropped_at_as_of']}")
    eids = set(inj["INJ-06"]["record_ids"])
    asof_ev = [e for e in ctx.log["as-of"] if e.cls == "analysed"]
    steps, gap_h, lo, hi = ps._fd(ctx)
    with_, without = ps._funnel_units(asof_ev, steps, gap_h, lo, hi), ps._funnel_units([e for e in asof_ev if e.event_id not in eids], steps, gap_h, lo, hi)
    rec.add("E INJ-06 the 8 designed late events add this many units to the as-of funnel: step 1 | activated (python without them vs manifest)", f"{with_[2] - without[2]}|{with_[3] - without[3]}",
            f"{inj['INJ-06']['expected']['funnel_step_1_units_added']}|{inj['INJ-06']['expected']['funnel_activated_units_added']}")
    lb = {r["reading"]: r for r in R["03_funnel_steps_and_exclusions__late_batch_effect"]}["late batch (hindsight - known)"]
    read = ctx.cuts["inj-06 earlier read"]
    known = ps._funnel_units([e for e in ctx.log["inj-06 earlier read"] if e.cls == "analysed"], steps, gap_h, lo, hi)
    hind_wo = ps._funnel_units([e for e in asof_ev if e.at <= read and e.event_id not in eids], steps, gap_h, lo, hi)
    rec.add("E INJ-06 the late batch of 03 (hindsight - known): visit | signup | step 1 | activated = the ordinary late events (python, the 8 removed) + the 8 designed ones",
            f"{lb['visit']}|{lb['signup']}|{lb['onboarding_step_1']}|{lb['activated']}",
            "|".join(str(h - k + extra_) for h, k, extra_ in zip(hind_wo, known, (0, 0, 8, 4))))
    rec.add("E INJ-07 events the link attributes (SQL rows with a user among the manifest's) | events that stay anonymous (SQL rows without a user among the manifest's)", f"{extra['inj07_attr']}|{extra['inj07_remain']}",
            f"{len(inj['INJ-07']['expected']['attributed_by_link'])}|{len(inj['INJ-07']['expected']['remain_anonymous'])}")
    s_v2 = [r for r in R["06_experiment_v2_sample_ratio__srm_by_read"] if r["experiment_version"] == V2 and r["run"] == "an-005"][0]
    i8 = inj["INJ-08"]["detail"]
    rec.add("E INJ-08 / DR-06 v2 sample ratio: observed | expected | statistic | p | verdict (06 vs manifest)",
            f"{s_v2['observed_control']}|{s_v2['observed_treatment']}|{fmt(s_v2['expected_control'])}|{fmt(s_v2['expected_treatment'])}|{fmt(s_v2['statistic'])}|{fmt(s_v2['p_value'])}|{s_v2['verdict']}",
            f"{i8['observed']['control']}|{i8['observed']['treatment']}|{i8['expected']['control']}|{i8['expected']['treatment']}|{i8['statistic']}|{i8['p_value']}|{i8['verdict']}")
    s_v1 = [r for r in R["06_experiment_v2_sample_ratio__srm_by_read"] if r["experiment_version"] == V1 and r["run"] == "an-004"][0]
    d6 = drs["DR-06"]["v1"]
    rec.add("E DR-06 v1 sample ratio: observed | statistic | p | verdict (06 vs manifest)", f"{s_v1['observed_control']}|{s_v1['observed_treatment']}|{fmt(s_v1['statistic'])}|{fmt(s_v1['p_value'])}|{s_v1['verdict']}",
            f"{d6['observed']['control']}|{d6['observed']['treatment']}|{d6['statistic']}|{d6['p_value']}|{d6['verdict']}")
    got = extra["inj12"]
    want = {x["account_id"]: x["local_day_indices"] for x in inj["INJ-12"]["detail"]["late_returners"] + inj["INJ-12"]["detail"]["timezone_edge"]}
    rec.add(f"E INJ-12 local day indices of the {len(want)} accounts the manifest names (SQL, the account's calendar) | accounts equal", f"{sum(1 for a in want if got.get(a) == want[a])}|{len(got)}", f"{len(want)}|{len(want)}")
    rec.add("E INJ-12 exact day 7 and on-or-after day 7 are separate figures: the difference over the window of the manifest is at least its stated minimum (02 grid ALL vs manifest)",
            int([r for r in R["02_weekly_cohort_grid__cohort_grid"] if r["week_start"] == "ALL"][0]["on_or_after_day7_retained"]) - int([r for r in R["02_weekly_cohort_grid__cohort_grid"] if r["week_start"] == "ALL"][0]["day7_retained"]) >= inj["INJ-12"]["expected"]["on_or_after_minus_exact_day7_at_least"], True)
    d2 = drs["DR-02"]
    rec.add("E DR-02 week-4 retention v1: retained | mature | difference pp | Newcombe (07 vs manifest)", f"{w4['retained_control']}/{w4['mature_control']}|{w4['retained_treatment']}/{w4['mature_treatment']}|{fmt(w4['difference_pp'])}|{fmt(w4['newcombe_low'])}|{fmt(w4['newcombe_high'])}",
            f"{d2['week4']['control']['retained']}/{d2['week4']['control']['mature']}|{d2['week4']['treatment']['retained']}/{d2['week4']['treatment']['mature']}|{d2['difference_pp']}|{d2['newcombe_95_low']}|{d2['newcombe_95_high']}")
    d3 = drs["DR-03"]["plan"]
    for r in R["01_activation_by_plan_and_segment__time_to_activation_by_plan"]:
        m = d3[r["plan"]]
        rec.add(f"E DR-03 plan {r['plan']} (accounts never assigned to the treatment): accounts | activated | rate | median hours (01 vs manifest)",
                f"{r['accounts']}|{r['activated']}|{fmt(r['activation_rate'])}|{fmt(r['median_hours_to_activate'])}", f"{m['accounts']}|{m['activated']}|{m['rate']}|{m['median_hours_to_activate']}")
    gd = {r["run"]: r for r in R["07_guardrail_and_revenue_per_arm__guardrail_by_cutoff"]}["as-of"]
    d4 = drs["DR-04"]["realised"] if "realised" in drs["DR-04"] else drs["DR-04"]
    rec.add("E DR-04 guardrail v1: errors | eligible | rates | difference pp | Newcombe (07 vs manifest)",
            f"{gd['errors_control']}/{gd['eligible_control']}|{gd['errors_treatment']}/{gd['eligible_treatment']}|{fmt(gd['error_rate_control'])}|{fmt(gd['error_rate_treatment'])}|{fmt(gd['difference_pp'])}|{fmt(gd['newcombe_low'])}|{fmt(gd['newcombe_high'])}",
            f"{d4['by_variant']['control']['units_with_error']}/{d4['by_variant']['control']['eligible_units']}|{d4['by_variant']['treatment']['units_with_error']}/{d4['by_variant']['treatment']['eligible_units']}|"
            f"{d4['by_variant']['control']['error_rate']}|{d4['by_variant']['treatment']['error_rate']}|{d4['difference_pp']}|{d4['newcombe_95_low']}|{d4['newcombe_95_high']}")
    rv = {(r["run"], r["arm"]): r for r in R["07_guardrail_and_revenue_per_arm__revenue_by_arm"]}
    rd5 = {r["run"]: r for r in R["07_guardrail_and_revenue_per_arm__revenue_difference"]}["as-of"]
    d5 = drs["DR-05"]
    rec.add("E DR-05 revenue per assigned account v1: totals | means | difference of means (07 vs manifest)",
            f"{fmt(rv[('as-of', 'control')]['total_usd'])}|{fmt(rv[('as-of', 'treatment')]['total_usd'])}|{fmt(rv[('as-of', 'control')]['mean_usd'])}|{fmt(rv[('as-of', 'treatment')]['mean_usd'])}|{fmt(rd5['difference_usd'])}",
            f"{d5['by_variant']['control']['total']}|{d5['by_variant']['treatment']['total']}|{d5['by_variant']['control']['mean']}|{d5['by_variant']['treatment']['mean']}|{d5['difference_of_means']}")
    d7 = drs["DR-07"]["by_variant"]
    rec.add("E DR-07 exposure v1: exposed | rate per arm (05 vs manifest)", f"{arms[('as-of', 'control')]['exposed']}|{fmt(arms[('as-of', 'control')]['exposure_rate'])}|{arms[('as-of', 'treatment')]['exposed']}|{fmt(arms[('as-of', 'treatment')]['exposure_rate'])}",
            f"{d7['control']['exposed']}|{d7['control']['rate']}|{d7['treatment']['exposed']}|{d7['treatment']['rate']}")
    st = manifest["stats"]
    rec.add("E manifest stats: duplicates re-sent | delayed over 24 h | ghost (unknown identity) events | linked share | v1 assigned | v2 assigned (04, 06 vs manifest)",
            f"{tq['duplicates_dropped']}|{tq['delayed_over_24h']}|{tq['unknown_identity']}|{fmt(idn['linked_share'])}|{lift['as-of']['assigned_control'] + lift['as-of']['assigned_treatment']}|{s_v2['observed_control'] + s_v2['observed_treatment']}",
            f"{st['duplicates_resent']}|{st['delayed_over_24h']}|{st['ghost_events']}|{st['linked_share']}|{st['v1_assigned']}|{st['v2_assigned']}")
    a1 = arms[("an-001", "control")], arms[("an-001", "treatment")]
    rec.add("E D-08 the first interim run (2026-05-18): assigned control | treatment | SRM statistic | revenue totals | means (05, 07 vs the D-08 text of docs/contracts.md)",
            f"{a1[0]['assigned']}|{a1[1]['assigned']}|{fmt(lift['an-001']['srm_statistic'])}|{fmt(rv[('an-001', 'control')]['total_usd'])}|{fmt(rv[('an-001', 'treatment')]['total_usd'])}|{fmt(rv[('an-001', 'control')]['mean_usd'])}|{fmt(rv[('an-001', 'treatment')]['mean_usd'])}",
            "77|78|0.006452|5322.00|5481.00|81.88|85.64")

    csvs = {k: [{c: fmt(v) for c, v in r.items()} for r in rows] for k, rows in bi.items()}
    meas = bi_measures(csvs["fact_account"], csvs["fact_run_assignment"], csvs["fact_tracking_week"], csvs["dim_experiment_version"], csvs["dim_run"])
    mv = {(m["measure"], m["slice"]): m["value"] for m in meas}
    for xv, label, rid in READS:
        key = RUN_KEY[(xv, label)]
        ex = dom[(xv, label)].metrics["experiment"]
        rx = ref[(xv, label)]["experiment"]
        held = ex["srm"]["verdict"] == "MISMATCH"
        rec.add(f"E BI {key}: sample-ratio statistic | verdict (CSV facts vs reference SQL vs domain)", f"{mv[('srm_statistic', key)]}|{mv[('srm_verdict', key)]}",
                f"{rx['srm']['statistic']}|{rx['srm']['verdict']}", f"{ex['srm']['statistic']}|{ex['srm']['verdict']}")
        if held:
            outcome = [m for m in ("activated_accounts", "conversion_rate", "guardrail_error_rate", "revenue_per_assigned_account") if (m, f"{key}|control") in mv or (m, f"{key}|treatment") in mv]
            lifts = [m for m in ("absolute_lift_pp", "relative_lift", "newcombe_low", "newcombe_high") if (m, key) in mv]
            rec.add(f"E BI {key}: the sample ratio is a MISMATCH, so no outcome measure and no lift is emitted (number of outcome measures present)", len(outcome) + len(lifts), 0)
        for arm in ("control", "treatment"):
            v, rv_ = ex["primary"]["variants"][arm], rx["primary"]["variants"][arm]
            rec.add(f"E BI {key} {arm}: assigned | mature (CSV facts vs reference SQL vs domain)",
                    f"{mv[('assigned_accounts', f'{key}|{arm}')]}|{mv[('mature_accounts', f'{key}|{arm}')]}", f"{rv_['assigned']}|{rv_['mature_units']}", f"{v['assigned']}|{v['mature_units']}")
            rec.add(f"E BI {key} {arm}: exposure rate (CSV facts vs reference SQL vs domain)", mv[("exposure_rate", f"{key}|{arm}")],
                    rx["exposure"]["by_variant"][arm]["rate"], ex["exposure"]["by_variant"][arm]["rate"])
            if held:
                continue
            rec.add(f"E BI {key} {arm}: activated | conversion (CSV facts vs reference SQL vs domain)",
                    f"{mv[('activated_accounts', f'{key}|{arm}')]}|{mv[('conversion_rate', f'{key}|{arm}')]}", f"{rv_['activated']}|{fmt(rv_['conversion'])}", f"{v['activated']}|{fmt(v['conversion'])}")
            rec.add(f"E BI {key} {arm}: guardrail error rate | revenue per assigned account (CSV facts vs reference SQL vs domain)",
                    f"{mv[('guardrail_error_rate', f'{key}|{arm}')]}|{mv[('revenue_per_assigned_account', f'{key}|{arm}')]}",
                    f"{fmt(rx['guardrail']['by_variant'][arm]['error_rate'])}|{fmt(rx['revenue_per_assigned_account']['by_variant'][arm]['mean'])}",
                    f"{fmt(ex['guardrail']['by_variant'][arm]['error_rate'])}|{fmt(ex['revenue_per_assigned_account']['by_variant'][arm]['mean'])}")
        if held:
            continue
        p = ex["primary"]
        rec.add(f"E BI {key}: absolute lift pp | relative lift | Newcombe low | high (CSV facts vs reference SQL vs domain)",
                f"{mv[('absolute_lift_pp', key)]}|{mv[('relative_lift', key)]}|{mv[('newcombe_low', key)]}|{mv[('newcombe_high', key)]}",
                f"{rx['primary']['absolute_lift_pp']}|{fmt(rx['primary']['relative_lift'])}|{rx['primary']['interval']['low']}|{rx['primary']['interval']['high']}",
                f"{p['absolute_lift_pp']}|{fmt(p['relative_lift'])}|{p['interval']['low']}|{p['interval']['high']}")
    rec.add("E BI account fact: activation rate over all mature signups | day 7 | on or after day 7 | week 4 (CSV vs 01 and 02 ALL rows vs the domain over the widened windows)",
            f"{mv[('activation_rate_all_signups', 'asof')]}|{mv[('day7_retention', 'asof')]}|{mv[('on_or_after_day7_retention', 'asof')]}|{mv[('week4_retention', 'asof')]}",
            f"{[r for r in R['01_activation_by_plan_and_segment__plan_segment'] if r['plan'] == 'ALL' and r['segment'] == 'ALL'][0]['activation_rate']}|"
            + "|".join(fmt(ratio) for ratio in (ps.ratio6(int([r for r in R['02_weekly_cohort_grid__cohort_grid'] if r['week_start'] == 'ALL'][0][k]), int([r for r in R['02_weekly_cohort_grid__cohort_grid'] if r['week_start'] == 'ALL'][0][m]))
                                               for k, m in (("day7_retained", "day7_mature"), ("on_or_after_day7_retained", "on_or_after_day7_mature"), ("week4_retained", "week4_mature")))),
            f"{wres.metrics['activation']['rate']}|{ps.ratio6(sum(g['day7'][1] for g in byw.values()), sum(g['day7'][0] for g in byw.values()))}|"
            f"{ps.ratio6(sum(g['on_or_after_day7'][1] for g in byw.values()), sum(g['on_or_after_day7'][0] for g in byw.values()))}|{ps.ratio6(sum(g['week4'][1] for g in byw.values()), sum(g['week4'][0] for g in byw.values()))}")
    for k, dk in (("rows_total", "rows_total"), ("duplicates_dropped", "duplicates_dropped"), ("canonical", "canonical"), ("delayed_over_24h", "delayed_over_24h"), ("unknown_identity", "unknown_identity"),
                  ("bot_excluded", "bot_events_excluded"), ("internal_excluded", "internal_events_excluded"), ("analysed", "analysed")):
        rec.add(f"E BI tracking fact total {k} (CSV facts vs reference SQL vs domain)", mv[(k, "asof")], r0["tracking_quality"][dk], d0.tracking_quality[dk])
    rec.add("E BI dim_run keys: the five logged runs and the as-of read of each version (CSV vs dataset)", "|".join(r["run_key"] for r in csvs["dim_run"]),
            "an-001|an-002|an-003|an-004|asof-xv-001|an-005|asof-xv-002")
    rec.add("E BI row counts: dim_account | fact_account | fact_run_assignment | fact_tracking_week", f"{len(csvs['dim_account'])}|{len(csvs['fact_account'])}|{len(csvs['fact_run_assignment'])}|{len(csvs['fact_tracking_week'])}",
            f"{manifest['row_counts']['accounts']}|{manifest['row_counts']['accounts']}|{155 + 253 + 353 + 400 + 400 + 154 + 154}|26")

    # ---- results -----------------------------------------------------------------------------------------------------------------------------------------
    equal = sum(1 for r in rec.rows if r["equal"])
    meta = {"dataset_hash": DATASET_HASH, "dataset_version": manifest["dataset_version"], "code_revision": CODE_REVISION, "contract_version": 1, "seed": manifest["generator"]["seed"],
            "as_of": ps.ASOF, "analysis_cutoffs": "|".join(f"{k}={v}" for k, v in ps.CUT_LABELS.items()), "accounts": len(ctx.rows["accounts"]), "events": len(ctx.rows["events"]),
            "reconciliation_rows": len(rec.rows), "reconciliation_equal": equal, "result_sets": len(ps.KEYS) + len(G), "result_rows": sum(len(R[k]) for k in R)}
    for r in rec.rows:
        print(("OK   " if r["equal"] else "DIFF ") + r["check"] + (" | " + " | ".join(str(r[k]) for k in ("analysis_sql", "second_source", "third_source", "fourth_source") if r[k] != "") if not r["equal"] else ""))
    print(f"RESULT: {'OK' if rec.ok else 'FAILED'} ({len(rec.rows)} reconciliation rows, {equal} equal; {meta['result_sets']} result sets, {meta['result_rows']} rows)")
    if bi_out:
        for k, rows in csvs.items():
            export_csv(bi_out / f"{k}.csv", rows)
        export_csv(bi_out / "measures_recomputed.csv", meas)
        print(f"wrote {len(csvs) + 1} CSV files to {bi_out}")
    if json_out:
        out = {"meta": [meta], **{k: ps.normalised(v) for k, v in R.items()}, "bi_measures": meas, "reconciliation": rec.rows}
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
        print(f"wrote {json_out}")
    return 0 if rec.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
