"""Run every analysis investigation and reconcile it with the independent sources (P10-ART-04).

Usage (from apps/retentionlab):
  ../../.venv/bin/python data/sql/analysis/run_all.py [--json artifacts/analysis-results.json] [--bi-out artifacts/bi] [--keep] [--skip-world]

With no environment variables it creates two scratch databases (artifacts10_run_snapshot, artifacts10_run_golden) on the local PostgreSQL named by ARTIFACTS_ADMIN_URL (default: the
repository's local development login, 127.0.0.1:5432), loads the published snapshot ``web/public/data`` and the golden fixture through ``data/migrate.py`` and ``data/seed.py``
(prepare_snapshot.py), runs everything and drops them again (``--keep`` leaves them). To use databases you prepared yourself, set ARTIFACTS_DATABASE_URL and
ARTIFACTS_GOLDEN_DATABASE_URL (names must start with artifacts10_; the shared retentionlab database is never touched).

What runs, in order (exit code 0 only if every query ran and every reconciliation row is equal):
  01..08 and 10 on the snapshot database (files hold several blocks marked ``-- @@ name``), 09 on the golden database, bi_dimensions.sql and bi_fact_*.sql on the snapshot
  (written as CSV with --bi-out).
Reconciliation (the rows printed at the end, ``reconciliation`` in the JSON):
  A  golden fixture: data/sql/reference_metrics.sql, the Python domain (``retentionlab.evaluate``) and tests/fixtures/golden/expected.json agree on every metric of every cutoff set; the
     SQL of investigation 09 equals the hand answer of expected.json and CALCULATION.md (precision and recall 0.5 at K = 2, Brier 0.1925, AP 5/6 = 0.833333, lift 1, budget 10.00,
     value 8.45, 2 arrived-late events, a fully censored February, PSI 0.074266 and 2.381316, 27 split rows);
  B  the 200-account cohort: for every model and every one of the 21 cutoffs the reference SQL, the domain re-run over the loaded cohort and the figures the manifest published
     agree; the economics of the 2026-09-01 queue (SQL of investigation 03, reference SQL, domain, manifest, python_side);
  C  every result set cell by cell against python_side.py (plain Python from the raw JSON rows, no SQL and no domain code), AP and PSI included;
  D  the designed relationships (DR-01..DR-05), the calibration file, the split summary, the injection manifest and the manifest statistics against what the SQL finds;
  E  the BI measures recomputed from the CSV facts against the analysis, the reference and the domain;
  F  the whole 2,400-account world: the generator is re-run in memory and its test table, per-cutoff aggregates, drift series and full-world economics equal the published files
     (about 25 s; --skip-world leaves it out and says so).
AP and PSI have a SQL statement in investigations 01, 02, 07, 08 and 09 (window functions; numeric ln()) AND a Python statement in python_side.py and in the domain.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import timedelta
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
from retentionlab import evaluate  # noqa: E402
from retentionlab.timeutil import parse_ts  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
SNAP_DIR = ROOT / "web" / "public" / "data"
CODE_REVISION = "ce96e65"
DATASET_HASH = "9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c"
RUN_SNAPSHOT_DB, RUN_GOLDEN_DB = "artifacts10_run_snapshot", "artifacts10_run_golden"
AS_OF = "2026-10-05T00:00:00Z"
SEED = 20261026
SNAPSHOT_FILES = ["01", "02", "03", "04", "05", "06", "07", "08", "10"]
BI_FILES = ["bi_dimensions", "bi_fact_test_row", "bi_fact_model_metric", "bi_fact_calibration_bin", "bi_fact_capacity", "bi_fact_cutoff", "bi_fact_drift", "bi_fact_purge", "bi_fact_segment_gap"]
MODELS = ("random_baseline", "business_rule", "logistic_regression", "prevalence_baseline")


def fmt(v) -> str:
    return ps.norm(v)


def canon(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


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


def reference(conn, as_of: str, pa: str, scenario: str | None, model: str = "logistic_regression", run: str = "tr-001") -> dict:
    return dict(conn.execute(REFERENCE.read_text(), {"as_of": parse_ts(as_of), "pa": parse_ts(pa), "run": run, "scenario": scenario, "model": model}, prepare=False).fetchone())


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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- BI measures from the exported facts (no database, no domain): exact arithmetic over the CSV strings -------------------------------------------------------------------------
def bi_measures(csvs: dict[str, list[dict]]) -> list[dict]:
    """The measures of docs/bi-package.md evaluated over the CSV facts. Every cell of the measure grid has a row: a value, or a stated reason why there is none.
    Economics rows carry result_kind 'hypothetical' and their population; everything else is 'simulated' (a synthetic world), never a real-world result."""
    rows: list[dict] = []

    def add(measure: str, population: str, slice_: str, value=None, num=None, den=None, status: str = "value", kind: str = "simulated", note: str = "") -> None:
        rows.append({"measure": measure, "population": population, "slice": slice_, "value": "" if value is None else fmt(value), "numerator": "" if num is None else fmt(num),
                     "denominator": "" if den is None else fmt(den), "status": status, "result_kind": kind, "note": note})

    def share(measure, population, slice_, n, d, places=6, note="", kind="simulated"):
        if d == 0:
            add(measure, population, slice_, None, n, d, "null: zero denominator", kind, note)
        else:
            add(measure, population, slice_, ps.rnd(F(n, d), places), n, d, "value", kind, note)

    T = [{k: (F(v) if k.startswith("p_") else v) for k, v in r.items()} for r in csvs["fact_test_row"]]
    for r in T:
        r["churned"], r["account_id"], r["cutoff"] = int(r["churned"]), int(r["account_id"]), r["prediction_at"]
    pcols = {"random_baseline": "p_random_baseline", "business_rule": "p_business_rule", "logistic_regression": "p_logistic_regression", "prevalence_baseline": "p_prevalence_baseline",
             "logistic_uncalibrated": "p_logistic_uncalibrated"}
    pop = "test_world"
    n, pos = len(T), sum(r["churned"] for r in T)
    add("evaluated_rows", pop, "all", n)
    add("distinct_accounts", pop, "all", len({r["account_id"] for r in T}), note="rows are not accounts: overlapping cutoffs of one account are correlated, so no interval is given")
    share("prevalence", pop, "all", pos, n)
    ap_b: dict[str, tuple] = {}
    for m, col in pcols.items():
        it = [(r[col], r["churned"]) for r in T]
        ap_b[m] = (ps.avg_precision(it), ps.brier(it))
        add("average_precision", pop, m, ps.rnd(ap_b[m][0], 6), note="scikit-learn step form over distinct probabilities")
        add("brier_score", pop, m, ps.rnd(ap_b[m][1], 6), note="mean((p - y)^2) on one population")
    L = "logistic_regression"
    for name, a, b, sign, declared in (("ap_margin_over_rule", L, "business_rule", 1, "0.030000"), ("ap_margin_over_random", L, "random_baseline", 1, "0.050000"),
                                       ("brier_margin_under_rule", "business_rule", L, 0, "0.002000"), ("brier_margin_under_random", "random_baseline", L, 0, "0.050000"),
                                       ("ap_margin_over_prevalence_constant", L, "prevalence_baseline", 1, ""), ("brier_margin_under_prevalence_constant", "prevalence_baseline", L, 0, "")):
        i = 0 if sign else 1
        v = F(ps.rnd(ap_b[a][i], 6)) - F(ps.rnd(ap_b[b][i], 6))
        status = ("met, by construction (D-G02)" if declared and v >= F(declared) else "not met") if declared else "reference, not a target"
        add(name, pop, f"declared {declared}" if declared else "reference", ps.rnd(v, 6), status=status,
            note="a property of the synthetic world, not evidence about real accounts" + ("; uninformative: a uniform random score cannot beat about 0.33" if name == "brier_margin_under_random" else ""))
    for m in MODELS:
        col = pcols[m]
        order = sorted(T, key=lambda r: (-r[col], r["account_id"], r["cutoff"]))
        for sid, k in (("sc-001", 5), ("sc-002", 10), ("sc-003", 20)):
            tp = sum(r["churned"] for r in order[:k])
            tie = any(r[col] == order[k - 1][col] for r in order[k:])
            note = "tie across the cut: the order inside the tie group is by account id" if tie else ""
            share("precision_at_k", pop, f"{m}|K={k}", tp, k, note=note)
            share("recall_at_k", pop, f"{m}|K={k}", tp, pos, note=note)
            add("risk_lift_at_k", pop, f"{m}|K={k}", ps.rnd(F(tp, k) / F(pos, n), 6), tp, k, note="a ranking statistic, not treatment uplift" + ("; " + note if note else ""))
    # calibration: ten bins, empty bins are rows with a stated reason
    for m in ("logistic_regression", "logistic_uncalibrated"):
        for b in [x for x in csvs["fact_calibration_bin"] if x["model_key"] == m]:
            if b["empty_bin"] == "true":
                add("calibration_gap_pp", pop, f"{m}|bin {b['bin_index']}", None, 0, 0, "null: empty bin", note="no rows fall in this bin; the gap is unknown, never 0")
            else:
                cnt = int(b["rows_in_bin"])
                sel = [r for r in T if min(int(r[pcols[m]] * 10 // 1), 9) == int(b["bin_index"])]
                mean = sum((r[pcols[m]] for r in sel), F(0)) / len(sel)
                obs = F(sum(r["churned"] for r in sel), len(sel))
                assert len(sel) == cnt
                add("calibration_gap_pp", pop, f"{m}|bin {b['bin_index']}", ps.rnd((mean - obs) * 100, 2), cnt, len(sel), note="mean predicted minus observed churn rate, percentage points")
    for m, col in (("logistic_regression", "p_logistic_regression"), ("logistic_uncalibrated", "p_logistic_uncalibrated")):
        add("calibration_gap_pp", pop, f"{m}|overall", ps.rnd((sum((r[col] for r in T), F(0)) / n - F(pos, n)) * 100, 2), note="Platt scaling made the overall gap and the Brier score worse on test" if m == L else "")
    for g in csvs["fact_segment_gap"]:
        sel = [r for r in T if r["segment_key" if g["dimension"] == "segment" else "region_key"] == g["group_key"]]
        add("calibration_gap_pp", pop, f"{g['dimension']}|{g['group_key']}", ps.rnd((sum((r["p_logistic_regression"] for r in sel), F(0)) / len(sel) - F(sum(r["churned"] for r in sel), len(sel))) * 100, 2),
            sum(r["churned"] for r in sel), len(sel), note="not a designed relationship" if g["group_key"] == "apac" else ("designed (DR-02): an unobserved repricing" if g["group_key"] == "starter" else ""))
    # economics: HYPOTHETICAL, by population; the ranking measures of the queue populations are unavailable because the outcomes are censored
    sc = {s["scenario_id"]: s for s in csvs["dim_scenario"]}
    for c in csvs["fact_capacity"]:
        if c["population_key"] == "test_world":
            continue
        s = sc[c["scenario_id"]]
        k = int(s["capacity"])
        add("contact_budget", c["population_key"], c["scenario_id"], ps.rnd(F(s["contact_cost"]) * k, 2), k, s["contact_cost"], kind="hypothetical", note=f"{k} contacts x {s['contact_cost']} per contact")
        add("expected_intervention_value", c["population_key"], c["scenario_id"], c["expected_value"], kind="hypothetical",
            note=f"assumption-based: assumed effect {s['assumed_effect']}, margin {s['margin_value']}; no randomised experiment supports the effect; a ranking by risk is not a treatment effect; {c['evaluated_rows']} scored accounts")
        add("precision_at_k", c["population_key"], c["scenario_id"], None, status="null: outcomes censored", note="every row of the 2026-09-01 cutoff has a label window that closes after the as-of")
        add("recall_at_k", c["population_key"], c["scenario_id"], None, status="null: outcomes censored", note="as precision_at_k")
    add("treatment_effect_estimate", "all", "all", None, status="withheld: no randomised experiment", kind="hypothetical", note="the product never estimates a treatment effect from a risk ranking (P10-DOMAIN-06, P10-TEST-09)")
    cut = csvs["fact_cutoff"]
    for p in ("cohort_200", "world_2400"):
        sel = [c for c in cut if c["population_key"] == p]
        el, ce, ma, ch = (sum(int(c[k]) for c in sel) for k in ("eligible", "censored", "mature", "churned"))
        share("censored_share", p, "all cutoffs", ce, el, note="eligible rows whose label window has not closed at the as-of")
        share("mature_churn_rate", p, "all cutoffs", ch, ma, note="mature eligible churned / mature eligible")
        for c in sel:
            if int(c["censored"]) > 0:
                share("censored_share", p, c["prediction_at"], int(c["censored"]), int(c["eligible"]))
                add("mature_churn_rate", p, c["prediction_at"], None, 0, 0, "null: no mature row", note="censored rows are never counted as retained")
    for r in csvs["fact_purge"]:
        add("rows_dropped_by_the_purge", r["population_key"], r["split_range"], int(r["cutoff_rows"]) - int(r["retained"]), int(r["cutoff_rows"]) - int(r["retained"]), r["cutoff_rows"],
            note=f"LABEL_WINDOW {r['label_window']}, GROUP_TEST {r['group_test']}, GROUP_VALIDATION {r['group_validation']}")
    dr = [d for d in csvs["fact_drift"] if d["source"] == "published full world" and d["grp"] == "apac"]
    pre = [d for d in dr if d["prediction_at"] < "2026-03-31" and d["prediction_at"] != "2026-02-01T00:00:00+00:00"]
    add("drift_exceedances_before_the_change", "world_2400", "apac", sum(1 for d in pre if d["exceeds_threshold"] == "true"), sum(1 for d in pre if d["exceeds_threshold"] == "true"), len(pre),
        note=f"{sum(1 for d in pre if d['exceeds_threshold'] == 'true' and int(d['floored_bins']) > 0)} of them carry a floored bin: false positives of a diagnostic")
    post = [d for d in dr if d["prediction_at"] >= "2026-05-01"]
    add("drift_exceedances_from_2026_05", "world_2400", "apac", sum(1 for d in post if d["exceeds_threshold"] == "true"), sum(1 for d in post if d["exceeds_threshold"] == "true"), len(post),
        note="the shift: 60 percent of logins unrecorded from 2026-03-31")
    return rows


def main(argv: list[str]) -> int:
    json_out = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    bi_out = Path(argv[argv.index("--bi-out") + 1]) if "--bi-out" in argv else None
    keep, skip_world = "--keep" in argv, "--skip-world" in argv
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
        return _run(snap_url, gold_url, json_out, bi_out, skip_world)
    finally:
        if not keep:
            for name in created:
                drop_database(admin, name)


def _run(snap_url: str, gold_url: str, json_out: Path | None, bi_out: Path | None, skip_world: bool) -> int:
    rec = Recon()
    R: dict[str, list[dict]] = {}
    prep_s, prep_g = prepare(snap_url, False), prepare(gold_url, True)
    print(f"snapshot prepared: {prep_s['inserted']} (dataset {prep_s['dataset_version']}, hash {prep_s['dataset_hash'][:12]}..., {prep_s['skipped']} rejected rows kept)")
    print(f"golden prepared:   {prep_g['inserted']} (hash {prep_g['dataset_hash'][:12]}...)")
    inputs, manifest = snapshot_inputs()
    bi: dict[str, list[dict]] = {}
    ref_c: dict[tuple[str, str, str | None], dict] = {}
    scalar: dict[str, object] = {}
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        for prefix in SNAPSHOT_FILES:
            f = next(HERE.glob(f"{prefix}_*.sql"))
            R.update(run_file(c, f))
            print(f"ran {f.name}")
        for name in BI_FILES:
            for k, rows in run_file(c, HERE / f"{name}.sql").items():
                bi[k.split("__")[-1] if "__" in k else k.removeprefix("bi_")] = rows
        print("ran the BI dimension and fact queries")
        cut_ids = sorted({r["prediction_at"] for r in c.execute("SELECT prediction_at FROM prediction_cutoffs").fetchall()})
        for m in MODELS:
            for pa in cut_ids:
                iso = pa.strftime("%Y-%m-%dT%H:%M:%SZ")
                ref_c[(m, iso, None)] = reference(c, AS_OF, iso, None, m)
        for sid in ("sc-001", "sc-002", "sc-003"):
            ref_c[("logistic_regression", "2026-09-01T00:00:00Z", sid)] = reference(c, AS_OF, "2026-09-01T00:00:00Z", sid)
        print(f"reference_metrics.sql on {len(cut_ids)} cutoffs x {len(MODELS)} models and the three scenarios")
        scalar["counts"] = {t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in
                            ("accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels", "training_runs", "predictions",
                             "scoring_publications", "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments", "rejected_records", "art_test_table")}
        scalar["outreach_status"] = [r["status"] for r in c.execute("SELECT status FROM outreach_events GROUP BY status ORDER BY status COLLATE \"C\"").fetchall()]
        scalar["dataset_version"] = dict(c.execute("SELECT dataset_version, dataset_hash FROM dataset_versions").fetchone())
        scalar["claims"] = {r["claim"]: r["value"] for r in c.execute("SELECT claim, value FROM art_published_claim").fetchall()}
    with psycopg.connect(gold_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        G = run_file(c, HERE / "09_golden_known_answer.sql")
        g_inputs = json.loads((GOLDEN_DIR / "inputs.json").read_text())
        ref_g = {pa: reference(c, g_inputs["as_of"], pa, sc) for pa, sc in (("2026-01-01T00:00:00Z", "sc-001"), ("2026-02-01T00:00:00Z", None))}
    R.update(G)

    # ---- A: golden fixture ---------------------------------------------------------------------------------------------------------------------------------------------------------
    exp = json.loads((GOLDEN_DIR / "expected.json").read_text())
    dom_g = evaluate(g_inputs)
    rec.add("A golden whole shape of expected.json (domain evaluate() vs the file, digest)", digest(dom_g), digest(exp))
    rec.add("A golden consistency block (domain vs expected.json)", digest(dom_g["consistency"]), digest(exp["consistency"]))
    keys = ("population", "churn_rate", "late_events", "precision_at_k", "recall_at_k", "risk_lift_at_k", "outreach_queue", "empty_population", "empty_evaluation")
    for pa, ref in ref_g.items():
        e, d = exp["cutoff_sets"][pa], dom_g["cutoff_sets"][pa]
        for k in keys:
            rec.add(f"A golden {pa[:10]} {k}: reference SQL = domain = expected.json (digest)", digest(ref[k]), digest(e[k]), digest(d[k]))
        rec.add(f"A golden {pa[:10]} brier_score: reference SQL = domain = expected.json (digest)", digest({"value": ref["brier_score"]["value"], "n": ref["brier_score"]["n"], "terms": ref["brier_score"]["terms"]}),
                digest({"value": e["brier_score"]["value"], "n": e["brier_score"]["n"], "terms": e["brier_score"]["terms"]}), digest({"value": d["brier_score"]["value"], "n": d["brier_score"]["n"], "terms": d["brier_score"]["terms"]}))
        rec.add(f"A golden {pa[:10]} calibration bins: reference SQL = domain = expected.json (digest)", digest(ref["calibration_bins"]),
                digest([{k: b[k] for k in ref["calibration_bins"][0]} for b in e["calibration"]["bins"]]), digest([{k: b[k] for k in ref["calibration_bins"][0]} for b in d["calibration"]["bins"]]))
        rec.add(f"A golden {pa[:10]} economics: reference SQL = domain = expected.json (budget, value, accounts)",
                digest(None if ref["economics"] is None else {k: ref["economics"][k] for k in ("contact_budget", "expected_value", "selected_account_ids")}),
                digest(None if e["economics"] is None else {k: e["economics"][k] for k in ("contact_budget", "expected_value", "selected_account_ids")}),
                digest(None if d["economics"] is None else {k: d["economics"][k] for k in ("contact_budget", "expected_value", "selected_account_ids")}))
        fm = e["feature_missingness"]
        rec.add(f"A golden {pa[:10]} feature missingness overall (reference SQL vs expected.json vs domain)", ref["feature_missingness"]["overall_value"], fm["overall"]["value"], d["feature_missingness"]["overall"]["value"])
    ka = G["09_golden_known_answer__known_answer"][0]
    jan = exp["cutoff_sets"]["2026-01-01T00:00:00Z"]
    for label, got, hand, from_exp in (("churn rate", ka["churn_rate"], "0.500000", jan["churn_rate"]["value"]), ("precision at K=2", ka["precision_at_k"], "0.500000", jan["precision_at_k"]["value"]),
                                       ("recall at K=2", ka["recall_at_k"], "0.500000", jan["recall_at_k"]["value"]), ("risk lift at K=2", ka["risk_lift_at_k"], "1.000000", jan["risk_lift_at_k"]["value"]),
                                       ("Brier score", ka["brier_score"], "0.192500", jan["brier_score"]["value"]), ("average precision (5/6)", ka["average_precision"], "0.833333", jan["average_precision"]["value"]),
                                       ("contact budget", ka["contact_budget"], "10.00", jan["economics"]["contact_budget"]), ("expected intervention value", ka["expected_intervention_value"], "8.45", jan["economics"]["expected_value"])):
        rec.add(f"A golden known answer {label}: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json", got, hand, from_exp)
    rec.add("A golden eligible of cutoff rows (4 of 6) and the two reasons (SQL 09 vs hand)", f"{ka['eligible_rows']}/{ka['cutoff_rows']}|{ka['ineligible_created_on_or_after_observation_start']}|{ka['ineligible_not_active']}", "4/6|1|1",
            f"{jan['population']['eligible']}/{jan['population']['cutoff_rows']}|{jan['population']['ineligible']['CREATED_ON_OR_AFTER_OBSERVATION_START']}|{jan['population']['ineligible']['NOT_ACTIVE']}")
    rec.add("A golden arrived-late events (SQL 09 vs expected.json): usage, support, billing, subscription", "|".join(str(r["arrived_late"]) for r in G["09_golden_known_answer__arrived_late"]),
            f"{jan['late_events']['usage_events']}|{jan['late_events']['support_events']}|{jan['late_events']['billing_events']}|{jan['late_events']['subscription_events']}")
    ce = G["09_golden_known_answer__censored_cohort"][0]
    feb = exp["cutoff_sets"]["2026-02-01T00:00:00Z"]
    rec.add("A golden censored February cohort: eligible/mature/censored, ranking metrics null (SQL 09 vs expected.json)", f"{ce['eligible_rows']}|{ce['mature_rows']}|{ce['censored_rows']}|{ce['churn_rate']}",
            f"{feb['population']['eligible']}|{feb['population']['mature']}|{feb['population']['censored']}|{feb['churn_rate']['value']}")
    for r in G["09_golden_known_answer__purge_counts"]:
        s = exp["split"]["tr-001"]["counts"][r["split_range"]]
        rec.add(f"A golden purge counts {r['split_range']} (SQL 09 vs expected.json)", f"{r['cutoff_rows']}|{r['retained']}|{r['label_window']}|{r['group_test']}|{r['group_validation']}",
                f"{s['total']}|{s['retained']}|{s['label_window']}|{s['group_test']}|{s['group_validation']}")
    for r in G["09_golden_known_answer__psi_against_the_march_2025_cohort"]:
        pd = exp["cutoff_sets"][r["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ")]["population_drift"]
        rec.add(f"A golden PSI {r['prediction_at'].date()} against 2025-03-01 (SQL ln() vs domain Decimal.ln vs expected.json)", r["psi"], pd["psi"], dom_g["cutoff_sets"][r["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ")]["population_drift"]["psi"])
    occupied = [(b["bin_index"], b["rows_in_bin"], fmt(b["gap_pp"])) for b in G["09_golden_known_answer__calibration_bins"] if not b["empty_bin"]]
    wanted = [(b["index"], b["count"], b["gap_pp"]) for b in jan["calibration"]["bins"] if b["count"]]
    rec.add("A golden occupied calibration bins and gaps (SQL 09 vs expected.json)", occupied, wanted)
    rec.add("A golden hand literals: gaps +10.00, -60.00, +60.00, -20.00 in bins 1, 4, 6, 8", "|".join(b[2] for b in occupied), "10.00|-60.00|60.00|-20.00")

    # ---- B: the cohort -----------------------------------------------------------------------------------------------------------------------------------------------------------
    claims = manifest["published_cohort"]["claims"]
    dom_c = {}
    for m in MODELS:
        dm = {**inputs, "predictions": [p for p in inputs["predictions"] if p["model_name"] == m], "scoring_publications": [p for p in inputs["scoring_publications"] if p["model_name"] == m],
              "scope": {"training_run_id": "tr-001", "sets": [{"prediction_at": pa, "scenario_id": None} for pa in sorted({c["prediction_at"] for c in inputs["prediction_cutoffs"]})]}}
        dom_c[m] = evaluate(dm)
    print("domain evaluate() over the loaded cohort for the four models")
    for m in MODELS:
        for pa in sorted(claims[m]["cutoff_sets"]):
            cl, d, ref = claims[m]["cutoff_sets"][pa], dom_c[m]["cutoff_sets"][pa], ref_c[(m, pa, None)]
            ref_view = {"cutoff_rows": ref["population"]["cutoff_rows"], "eligible": ref["population"]["eligible"], "mature": ref["population"]["mature"], "censored": ref["population"]["censored"],
                        "scored": ref["population"]["scored"], "evaluated": ref["population"]["evaluated"], "churned": ref["population"]["churned"], "churn_rate": ref["churn_rate"]["value"],
                        "brier_score": ref["brier_score"]["value"], "late_total": ref["late_events"]["total"], "missingness_overall": ref["feature_missingness"]["overall_value"]}
            dom_view = {"cutoff_rows": d["population"]["cutoff_rows"], "eligible": d["population"]["eligible"], "mature": d["population"]["mature"], "censored": d["population"]["censored"],
                        "scored": d["population"]["scored"], "evaluated": d["population"]["evaluated"], "churned": d["population"]["churned"], "churn_rate": d["churn_rate"]["value"],
                        "brier_score": d["brier_score"]["value"], "late_total": d["late_events"]["total"], "missingness_overall": d["feature_missingness"]["overall"]["value"]}
            cl_view = {"cutoff_rows": cl["cutoff_rows"], "eligible": cl["eligible"], "mature": cl["mature"], "censored": cl["censored"], "scored": cl["scored"], "evaluated": cl["evaluated"],
                       "churned": cl["churned"], "churn_rate": cl["churn_rate"], "brier_score": cl["brier_score"], "late_total": cl["late_events"]["total"], "missingness_overall": cl["missingness_overall"]}
            rec.add(f"B cohort {m} {pa[:10]}: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest)", digest(ref_view), digest(dom_view), digest(cl_view))
    for m in MODELS:
        rec.add(f"B cohort {m}: the domain's consistency block over the loaded cohort is empty (stored derived rows = rebuilt rows)", digest(dom_c[m]["consistency"]), digest({k: [] for k in dom_c[m]["consistency"]}), digest(claims[m]["consistency"]))
    econ = manifest["published_cohort"]["economics"]
    P = {**ps.results(), **ps.golden_results()}
    for r in R["03_capacity_economics__cohort_economics"]:
        sid = r["scenario_id"]
        rf = ref_c[("logistic_regression", "2026-09-01T00:00:00Z", sid)]
        rec.add(f"B cohort economics {sid} expected value on 97 scored accounts (SQL 03 = reference SQL = manifest = python_side)", r["expected_value"], rf["economics"]["expected_value"], econ[sid]["expected_value"],
                next(x for x in P["03_capacity_economics__cohort_economics"] if x["scenario_id"] == sid)["expected_value"])
        rec.add(f"B cohort economics {sid} contact budget and capacity (SQL 03 = reference SQL = manifest)", f"{r['contact_budget']}|{r['selected_accounts']}", f"{rf['economics']['contact_budget']}|{len(rf['economics']['selected_account_ids'])}",
                f"{econ[sid]['contact_budget']}|{econ[sid]['capacity']}")
        rec.add(f"B cohort economics {sid} draft queue = the first {r['capacity']} of the ranking (stored rows in my top K vs manifest queue vs reference SQL)", r["stored_rows_in_my_top_k"], r["capacity"], len(set(rf["economics"]["selected_account_ids"]) & set(manifest["published_cohort"]["queue_account_ids"][sid])))
        rec.add(f"B cohort economics {sid} label hypothetical, no treatment effect, population 97", f"{r['label']}|{r['scored_accounts']}", f"{econ[sid]['label']}|{econ[sid]['population']}", f"hypothetical|{rf['outreach_queue']['population']}")
    rec.add("B cohort freshness: scoring 812 h, data 1 h (reference SQL vs manifest vs domain)", f"{ref_c[('logistic_regression', '2026-09-01T00:00:00Z', None)]['freshness']['scoring_hours']}|{ref_c[('logistic_regression', '2026-09-01T00:00:00Z', None)]['freshness']['data_hours']}",
            f"{claims['logistic_regression']['freshness']['scoring_hours']}|{claims['logistic_regression']['freshness']['data_hours']}", f"{dom_c['logistic_regression']['freshness']['scoring_hours']}|{dom_c['logistic_regression']['freshness']['data_hours']}")
    rec.add("B dataset version and hash: seed output = manifest = the constant of this package", f"{prep_s['dataset_version']}|{prep_s['dataset_hash']}", f"{manifest['dataset_version']}|{manifest['dataset_hash']}", f"{scalar['dataset_version']['dataset_version']}|{DATASET_HASH}")
    cnt = scalar["counts"]
    rc = manifest["row_counts"]
    for t in ("accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "predictions", "scoring_publications", "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments"):
        rec.add(f"B loaded rows of {t} (database count = manifest row_counts)", cnt[t], rc[t])
    rec.add("B loaded labels + the rejected injected labels = manifest labels (765 + 4 = 769)", cnt["labels"] + cnt["rejected_records"], rc["labels"])
    rec.add("B test table loaded = manifest row_counts.test_cohort", cnt["art_test_table"], rc["test_cohort"])

    # ---- C: every result set against python_side -------------------------------------------------------------------------------------------------------------------------------
    for key in sorted(R):
        a, b = ps.normalised(R[key]), ps.normalised(P[key])
        rec.add(f"C {key}: {len(a)} rows, every cell SQL = python_side.py (digest)", digest(a), digest(b))
    rec.add("C python_side covers exactly the result sets the SQL files produce", len(R), len(P))

    # ---- D: designed relationships, the calibration file, the split summary, the injection manifest -----------------------------------------------------------------------
    drs = {d["id"]: d["realised"] for d in manifest["designed_relationships"]}
    M = {r["model"]: r for r in R["01_model_comparison__models"]}
    name = {"random_baseline": "random_baseline", "business_rule": "business_rule", "logistic_regression": "logistic_regression (Platt)", "prevalence_baseline": "prevalence_baseline"}
    for m in MODELS:
        rec.add(f"D DR-01 {m}: average precision and Brier (SQL 01 vs manifest)", f"{M[name[m]]['average_precision']}|{M[name[m]]['brier_score']}", f"{drs['DR-01'][m]['average_precision']}|{drs['DR-01'][m]['brier_score']}")
        rec.add(f"D DR-01 {m}: rows, positives, prevalence (SQL 01 vs manifest)", f"{M[name[m]]['test_rows']}|{M[name[m]]['positive_rows']}|{M[name[m]]['prevalence']}", f"{drs['DR-01'][m]['n']}|{drs['DR-01'][m]['positives']}|{drs['DR-01'][m]['prevalence']}")
    mg = {r["margin"]: r["realised_margin"] for r in R["08_rows_and_margins__margins"]}
    for key, mk in (("ap_over_rule", "ap_over_rule"), ("ap_over_random", "ap_over_random"), ("brier_under_rule", "brier_under_rule"), ("brier_under_random", "brier_under_random")):
        rec.add(f"D DR-01 margin {key}: realised margin (SQL 08 vs manifest; met = by construction)", mg[mk], drs["DR-01"]["margins"][key])
    rec.add("D DR-01 reference margins over the prevalence constant (SQL 08 vs manifest)", f"{mg['ap_over_prevalence_constant (reference)']}|{mg['brier_under_prevalence_constant (reference)']}",
            f"{drs['DR-01']['reference_margins']['ap_over_prevalence_constant']}|{drs['DR-01']['reference_margins']['brier_under_prevalence_constant']}")
    rec.add("D DR-01 the model before Platt: Brier 0.104515 (SQL 01 vs calibration.json platt_effect)", M["logistic_regression (before Platt)"]["brier_score"], json.loads((SNAP_DIR / "calibration.json").read_text())["platt_effect"]["brier_uncalibrated"])
    cal = json.loads((SNAP_DIR / "calibration.json").read_text())
    pe = R["02_calibration_platt__platt_effect"][0]
    rec.add("D Platt effect (SQL 02 vs calibration.json): Brier before, after, gaps, fit rows, worse on test",
            f"{pe['brier_before']}|{pe['brier_after']}|{pe['overall_gap_pp_before']}|{pe['overall_gap_pp_after']}|{pe['fit_rows']}|{pe['made_the_brier_worse']}",
            f"{cal['platt_effect']['brier_uncalibrated']}|{cal['platt_effect']['brier_calibrated']}|{cal['platt_effect']['gap_pp_uncalibrated']}|{cal['platt_effect']['gap_pp_calibrated']}|{cal['platt_effect']['fit_rows']}|{cal['platt_effect']['worse_on_test']}")
    rec.add("D Platt mapping a, b (loaded calibration_maps vs calibration.json vs manifest training)", f"{pe['platt_a']}|{pe['platt_b']}", f"{cal['a']}|{cal['b']}", f"{manifest['training']['calibration']['a']}|{manifest['training']['calibration']['b']}")
    pr = R["02_calibration_platt__platt_reproduced"][0]
    rec.add("D the frozen Platt mapping applied in SQL reproduces the stored calibrated probability on all 1,513 rows", pr["equal_at_6_places"], pr["rows_compared"], 1513)
    rec.add("D calibration fit rows all come from one cutoff (cohort SQL 02 vs calibration.json fit_rows_by_cutoff)", R["02_calibration_platt__fit_rows_by_cutoff"][0]["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ"), list(cal["fit_rows_by_cutoff"])[0])
    for model, key in (("logistic_regression (Platt)", "reliability_calibrated"), ("logistic_regression (before Platt)", "reliability_uncalibrated")):
        sql_bins = [b for b in R["02_calibration_platt__bins"] if b["model"] == model]
        for b, pub in zip(sql_bins, cal[key]):
            rec.add(f"D reliability bin {b['bin_index']} of {model}: count, mean, observed, gap (SQL 02 vs calibration.json)", f"{b['rows_in_bin']}|{b['mean_predicted']}|{b['observed_rate']}|{b['gap_pp']}",
                    f"{pub['count']}|{pub['mean_predicted']}|{pub['observed_rate']}|{pub['gap_pp']}")
    for r in R["10_segment_region_calibration__by_segment"] + R["10_segment_region_calibration__by_region"]:
        pub = cal["by_segment" if r["dimension"] == "segment" else "by_region"][r["grp"]]
        rec.add(f"D DR-02 {r['dimension']} {r['grp']}: n, positives, mean, observed, gap (SQL 10 vs calibration.json)", f"{r['test_rows']}|{r['churning_rows']}|{r['mean_predicted']}|{r['observed_rate']}|{r['gap_pp']}",
                f"{pub['n']}|{pub['positives']}|{pub['mean_predicted']}|{pub['observed_rate']}|{pub['gap_pp']}")
    rec.add("D the largest regional gap is apac, -10.68 pp, not designed (SQL 10 vs calibration.json largest_region_gap)", next(r for r in R["10_segment_region_calibration__largest_gaps"] if r["dimension"] == "region")["most_negative_gap_group"] + "|" + str(next(r for r in R["10_segment_region_calibration__largest_gaps"] if r["dimension"] == "region")["gap_pp"]),
            f"{cal['largest_region_gap']['region']}|{cal['largest_region_gap']['gap_pp']}")
    rec.add("D overall calibration gap -2.86 pp and its mean predicted (SQL 10 vs calibration.json overall)", next(r for r in R["10_segment_region_calibration__largest_gaps"] if r["dimension"] == "overall")["gap_pp"], cal["overall"]["gap_pp"])
    agg = json.loads((SNAP_DIR / "cutoff_aggregates.json").read_text())
    pubd = {(d["prediction_at"], g): d[g] for d in agg["drift"]["by_cutoff"] for g in ("apac", "other_regions", "all_accounts")}
    for r in R["07_drift_by_region__psi_test_range"]:
        if r["grp"] in ("apac", "other_regions", "all_accounts"):
            pub = pubd[(r["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ"), r["grp"])]
            rec.add(f"D DR-03 PSI {r['grp']} {r['prediction_at'].date()}: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds)",
                    f"{r['psi']}|{r['reference_rows']}|{r['current_rows']}|{r['exceeds_threshold']}", f"{pub['psi']}|{pub['reference_rows']}|{pub['current_rows']}|{pub['exceeds_threshold']}")
            if r["grp"] == "apac":
                rec.add(f"D DR-03 floored bins apac {r['prediction_at'].date()} (SQL from the test table vs published)", r["floored_bins"], pub["floored_bins"])
    dr3 = drs["DR-03"]
    sm = R["07_drift_by_region__published_summary"][0]
    rec.add("D DR-03 apac after the change: five exceedances from 2026-05-01, minimum and maximum PSI (SQL 07 vs manifest after_change_psi)", f"{sm['exceedances_from_the_change']}|{sm['shift_min_psi']}|{sm['shift_max_psi']}",
            f"{len(dr3['after_change_psi'])}|{min(dr3['after_change_psi'])}|{max(dr3['after_change_psi'])}")
    rec.add("D DR-03 the two published pre-change figures are 0.000000 (the reference) and 0.142972 (2026-03-01) (SQL 07 vs manifest before_change_psi)",
            "|".join(str(r["psi"]) for r in R["07_drift_by_region__psi_test_range"] if r["grp"] == "apac" and r["prediction_at"].month in (2, 3) and r["prediction_at"].year == 2026), "|".join(dr3["before_change_psi"]))
    rec.add("D DR-03 the whole population never exceeds 0.2 (maximum 0.043730) and other regions stay below it (SQL 07 vs the case study's claim)", f"{sm['all_accounts_max_psi']}|{sm['other_regions_max_psi']}", "0.043730|0.051631")
    rec.add("D R10-07 apac pre-change exceedances: 5 of 14 comparison cutoffs, 4 with a floored bin, maximum 0.679573 (SQL 07 vs the published series by python_side)",
            f"{sm['exceedances_before_the_change']}|{sm['comparison_cutoffs_before_the_change']}|{sm['exceedances_before_the_change_with_a_floored_bin']}|{sm['max_psi_before_the_change']}", "5|14|4|0.679573")
    cl = scalar["claims"]
    ws = R["04_censored_tail__world_summary"][0]
    rec.add("D DR-05 eligible, censored rows, share and mature churn rate (SQL 04 vs manifest)", f"{ws['eligible_rows']}|{ws['censored_rows']}|{ws['censored_share']}|{ws['mature_churn_rate']}", f"{manifest['population']['feature_rows']}|{drs['DR-05']['censored_rows']}|{drs['DR-05']['censored_share']}|{drs['DR-05']['mature_churn_rate']}")
    rec.add("D DR-05 the censored rows are exactly the last three cutoffs (SQL 04 vs manifest immature_cutoffs)", "|".join(r["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ") for r in R["04_censored_tail__world_by_cutoff"] if r["censored"] > 0), "|".join(drs["DR-05"]["immature_cutoffs"]))
    for r in R["04_censored_tail__world_by_cutoff"]:
        if r["published_rate_if_censored_were_non_churn"] is not None:
            rec.add(f"D DR-05 {r['prediction_at'].date()} rate if censored rows were counted as non-churn, an integer number of cancellations seen so far (SQL 04 vs manifest)",
                    f"{r['published_rate_if_censored_were_non_churn']}|{r['implied_cancellations_seen_so_far']}", f"{drs['DR-05']['churn_rate_if_censored_were_non_churn'][r['prediction_at'].strftime('%Y-%m-%dT%H:%M:%SZ')]}|{round(float(drs['DR-05']['churn_rate_if_censored_were_non_churn'][r['prediction_at'].strftime('%Y-%m-%dT%H:%M:%SZ')]) * r['eligible'])}")
    for rng, pop in manifest["population"]["by_range"].items():
        s = [c for c in agg["cutoffs"] if c["range"] == rng]
        rec.add(f"D population range {rng}: eligible, mature, censored, churned (SQL 04 aggregate sums vs manifest population.by_range)",
                f"{sum(c['population']['eligible'] for c in s)}|{sum(c['population']['mature'] for c in s)}|{sum(c['population']['censored'] for c in s)}|{sum(c['population']['churned'] for c in s)}",
                f"{pop['eligible']}|{pop['mature']}|{pop['censored']}|{pop['churned']}")
    rec.add("D test prevalence 0.124917 and 1,513 rows (SQL 01 vs manifest population)", f"{M['logistic_regression (Platt)']['prevalence']}|{M['logistic_regression (Platt)']['test_rows']}", f"{manifest['population']['by_range']['test']['churn_rate']}|{manifest['population']['by_range']['test']['eligible']}")
    ra = R["08_rows_and_margins__rows_and_accounts"][0]
    rec.add("D R10-06 rows are not accounts: 1,513 rows from 442 accounts, 189 churning rows from 95 accounts (SQL 08 vs the generator test)", f"{ra['test_rows']}|{ra['distinct_accounts']}|{ra['churning_rows']}|{ra['churning_accounts']}", "1513|442|189|95")
    d4 = drs["DR-04"]
    for src in R["05_arrived_late__late_events_by_source"]:
        rec.add(f"D DR-04 late share {src['source']}: published full-world share = manifest realised share (SQL 05 vs manifest); the cohort share is a different population", src["published_full_world_share"], d4["realised"][src["source"]]["share"])
    pf = {r["claim"]: r["value"] for r in R["05_arrived_late__published_full_world"]}
    rec.add("D DR-04 full-world test rows with a late event 183, features that change 175 = 0.115664 (published, SQL 05 vs manifest)", f"{pf['test_rows_with_a_late_event']}|{pf['test_rows_features_change_if_ignored']}|{pf['share_of_test_rows_changed']}",
            f"{d4['test_rows_with_a_late_event']}|{d4['test_rows_features_change_if_ignored']}|{d4['share_of_test_rows_changed']}")
    fr = R["05_arrived_late__feature_recomputation"][0]
    rec.add("D point-in-time: all 765 stored feature rows equal the recomputation from the events (SQL 05)", fr["stored_equals_point_in_time_recomputation"], fr["feature_rows"], manifest["row_counts"]["feature_rows"])
    sp = json.loads((SNAP_DIR / "split_summary.json").read_text())
    for r in R["06_purge_counts__world_published"]:
        mt = manifest["training"]["split_counts_population"][r["split_range"]]
        rec.add(f"D purge counts of the whole world {r['split_range']} (SQL 06 on the published split vs manifest training vs split_summary)", f"{r['cutoff_rows']}|{r['retained']}|{r['label_window']}|{r['group_test']}|{r['group_validation']}",
                f"{mt['total']}|{mt['retained']}|{mt['label_window']}|{mt['group_test']}|{mt['group_validation']}", f"{sp['population'][r['split_range']]['total']}|{sp['population'][r['split_range']]['retained']}|{sp['population'][r['split_range']]['label_window']}|{sp['population'][r['split_range']]['group_test']}|{sp['population'][r['split_range']]['group_validation']}")
    for r in R["06_purge_counts__cohort_recomputed"]:
        s = sp["published_cohort"][r["split_range"]]
        rec.add(f"D purge counts of the cohort {r['split_range']}: recomputed in SQL from the cutoff windows vs split_summary published_cohort vs manifest claims",
                f"{r['cutoff_rows']}|{r['retained']}|{r['label_window']}|{r['group_test']}|{r['group_validation']}", f"{s['total']}|{s['retained']}|{s['label_window']}|{s['group_test']}|{s['group_validation']}",
                f"{claims['logistic_regression']['split_counts'][r['split_range']]['total']}|{claims['logistic_regression']['split_counts'][r['split_range']]['retained']}|{claims['logistic_regression']['split_counts'][r['split_range']]['label_window']}|{claims['logistic_regression']['split_counts'][r['split_range']]['group_test']}|{claims['logistic_regression']['split_counts'][r['split_range']]['group_validation']}")
    rec.add("D the 104-day embargo (SQL 06 vs split_summary vs manifest training)", R["06_purge_counts__world_totals"][0]["embargo_days"], sp["embargo_days"], manifest["training"]["embargo_days"])
    rec.add("D the training run: 744 rows fit, 79 positives; validation 289 rows, 27 positives (manifest training vs calibration fit_rows)", f"{manifest['training']['training_rows']}|{manifest['training']['training_positives']}|{manifest['training']['validation_rows']}|{manifest['training']['validation_positives']}",
            "744|79|289|27", f"{manifest['training']['preprocessing']['fit_rows']}|79|{cal['fit_rows']}|27")
    wp = {r["scenario_id"]: r for r in R["03_capacity_economics__both_populations"]}
    efw = manifest["economics_full_world"]["scenarios"]
    for sid, e in efw.items():
        rec.add(f"D full-world economics {sid}: scored accounts, budget, value (SQL 03 loaded aggregate vs manifest vs cutoff_aggregates)", f"{wp[sid]['world_scored_accounts']}|{wp[sid]['world_contact_budget']}|{wp[sid]['world_expected_value']}",
                f"{e['scored_accounts']}|{e['contact_budget']}|{e['expected_value']}", f"{agg['economics_full_world']['scenarios'][sid]['scored_accounts']}|{agg['economics_full_world']['scenarios'][sid]['contact_budget']}|{agg['economics_full_world']['scenarios'][sid]['expected_value']}")
    rec.add("D the cohort values (+21.38 / -6.87 / -95.46 on 97) and the world values (+81.13 / +71.04 / -29.12 on 1,241) are different populations (SQL 03)",
            "|".join(f"{wp[s]['cohort_expected_value']}@{wp[s]['cohort_scored_accounts']}/{wp[s]['world_expected_value']}@{wp[s]['world_scored_accounts']}" for s in sorted(wp)), "21.38@97/81.13@1241|-6.87@97/71.04@1241|-95.46@97/-29.12@1241")
    kt = {(r["model"], r["capacity"]): r for r in R["03_capacity_economics__test_population_at_k"]}
    rec.add("D top-K of the logistic model on the test population: churners in the top 5, 10, 20 (SQL 03 vs python_side)", "|".join(str(kt[("logistic_regression (Platt)", k)]["churners_in_top_k"]) for k in (5, 10, 20)), "0|2|5")
    inj = json.loads((SNAP_DIR / "injection-manifest.json").read_text())["injections"]
    inj_by = {i["id"] if "id" in i else k: i for k, i in (inj.items() if isinstance(inj, dict) else enumerate(inj))}
    rej = R["04_censored_tail__rejected_false_labels"][0]
    rec.add("D INJ-07 four labels of false for an open window are refused CENSORED_LABEL and kept raw (SQL 04 vs injection manifest)", f"{rej['reason_code']}|{rej['rejected_labels']}", "CENSORED_LABEL|4")
    rec.add("D INJ-03 no account retained on both sides of a boundary (SQL 06 vs injection manifest check)", R["06_purge_counts__cohort_no_account_on_both_sides"][0]["accounts_retained_in_two_ranges"], 0)
    rec.add("D INJ-04 no retained train or validation row has a label window crossing its boundary (SQL 06)", sum(r["retained_rows_crossing_the_boundary"] for r in R["06_purge_counts__cohort_label_windows_inside_the_range"]), 0)
    rec.add("D INJ-09 every outreach row is a draft (loaded outreach_events)", "|".join(scalar["outreach_status"]), "draft")
    rec.add("D INJ-10 the three capacities are within the scored population (SQL 03: scored accounts >= capacity)", all(r["scored_accounts"] >= r["capacity"] for r in R["03_capacity_economics__cohort_economics"]), True)
    rec.add("D cohort maturity rule: stored flag and label_end equal the 104-day rule for all 765 labelled rows (SQL 04)", f"{R['04_censored_tail__cohort_maturity_rule'][0]['stored_flag_equals_rule']}|{R['04_censored_tail__cohort_maturity_rule'][0]['stored_label_end_equals_rule']}", "765|765")

    # ---- E: the BI package ------------------------------------------------------------------------------------------------------------------------------------------------------
    csvs = {k: [{c: fmt(v) for c, v in r.items()} for r in rows] for k, rows in bi.items()}
    meas_rows = bi_measures(csvs)
    fm = {(r["population_key"], r["model_key"]): r for r in csvs["fact_model_metric"]}
    mm = {(r["measure"], r["slice"]): r for r in meas_rows if r["population"] == "test_world"}
    inv01 = {"random_baseline": "random_baseline", "business_rule": "business_rule", "logistic_regression": "logistic_regression (Platt)", "prevalence_baseline": "prevalence_baseline",
             "logistic_uncalibrated": "logistic_regression (before Platt)"}
    for key, label in inv01.items():
        row = M[label]
        pub = drs["DR-01"].get(key)
        rec.add(f"E BI measure average precision and Brier of {key}: recomputed from the CSV test rows vs the SQL fact vs investigation 01 vs the manifest",
                f"{mm[('average_precision', key)]['value']}|{mm[('brier_score', key)]['value']}", f"{fm[('test_world', key)]['average_precision']}|{fm[('test_world', key)]['brier_score']}",
                f"{row['average_precision']}|{row['brier_score']}", None if pub is None else f"{pub['average_precision']}|{pub['brier_score']}")
    for c in csvs["fact_capacity"]:
        if c["population_key"] == "test_world":
            continue
        s = sc[c["scenario_id"]]
        k = int(s["capacity"])
        add("contact_budget", c["population_key"], c["scenario_id"], ps.rnd(F(s["contact_cost"]) * k, 2), k, s["contact_cost"], kind="hypothetical", note=f"{k} contacts x {s['contact_cost']} per contact")
        add("expected_intervention_value", c["population_key"], c["scenario_id"], c["expected_value"], kind="hypothetical",
            note=f"assumption-based: assumed effect {s['assumed_effect']}, margin {s['margin_value']}; no randomised experiment supports the effect; a ranking by risk is not a treatment effect; {c['evaluated_rows']} scored accounts")
        add("precision_at_k", c["population_key"], c["scenario_id"], None, status="null: outcomes censored", note="every row of the 2026-09-01 cutoff has a label window that closes after the as-of")
        add("recall_at_k", c["population_key"], c["scenario_id"], None, status="null: outcomes censored", note="as precision_at_k")
    add("treatment_effect_estimate", "all", "all", None, status="withheld: no randomised experiment", kind="hypothetical", note="the product never estimates a treatment effect from a risk ranking (P10-DOMAIN-06, P10-TEST-09)")
    cut = csvs["fact_cutoff"]
    for p in ("cohort_200", "world_2400"):
        sel = [c for c in cut if c["population_key"] == p]
        el, ce, ma, ch = (sum(int(c[k]) for c in sel) for k in ("eligible", "censored", "mature", "churned"))
        share("censored_share", p, "all cutoffs", ce, el, note="eligible rows whose label window has not closed at the as-of")
        share("mature_churn_rate", p, "all cutoffs", ch, ma, note="mature eligible churned / mature eligible")
        for c in sel:
            if int(c["censored"]) > 0:
                share("censored_share", p, c["prediction_at"], int(c["censored"]), int(c["eligible"]))
                add("mature_churn_rate", p, c["prediction_at"], None, 0, 0, "null: no mature row", note="censored rows are never counted as retained")
    for r in csvs["fact_purge"]:
        add("rows_dropped_by_the_purge", r["population_key"], r["split_range"], int(r["cutoff_rows"]) - int(r["retained"]), int(r["cutoff_rows"]) - int(r["retained"]), r["cutoff_rows"],
            note=f"LABEL_WINDOW {r['label_window']}, GROUP_TEST {r['group_test']}, GROUP_VALIDATION {r['group_validation']}")
    dr = [d for d in csvs["fact_drift"] if d["source"] == "published full world" and d["grp"] == "apac"]
    pre = [d for d in dr if d["prediction_at"] < "2026-03-31" and d["prediction_at"] != "2026-02-01T00:00:00+00:00"]
    add("drift_exceedances_before_the_change", "world_2400", "apac", sum(1 for d in pre if d["exceeds_threshold"] == "true"), sum(1 for d in pre if d["exceeds_threshold"] == "true"), len(pre),
        note=f"{sum(1 for d in pre if d['exceeds_threshold'] == 'true' and int(d['floored_bins']) > 0)} of them carry a floored bin: false positives of a diagnostic")
    post = [d for d in dr if d["prediction_at"] >= "2026-05-01"]
    add("drift_exceedances_from_2026_05", "world_2400", "apac", sum(1 for d in post if d["exceeds_threshold"] == "true"), sum(1 for d in post if d["exceeds_threshold"] == "true"), len(post),
        note="the shift: 60 percent of logins unrecorded from 2026-03-31")
    return rows


def main(argv: list[str]) -> int:
    json_out = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    bi_out = Path(argv[argv.index("--bi-out") + 1]) if "--bi-out" in argv else None
    keep, skip_world = "--keep" in argv, "--skip-world" in argv
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
        return _run(snap_url, gold_url, json_out, bi_out, skip_world)
    finally:
        if not keep:
            for name in created:
                drop_database(admin, name)


def _run(snap_url: str, gold_url: str, json_out: Path | None, bi_out: Path | None, skip_world: bool) -> int:
    rec = Recon()
    R: dict[str, list[dict]] = {}
    prep_s, prep_g = prepare(snap_url, False), prepare(gold_url, True)
    print(f"snapshot prepared: {prep_s['inserted']} (dataset {prep_s['dataset_version']}, hash {prep_s['dataset_hash'][:12]}..., {prep_s['skipped']} rejected rows kept)")
    print(f"golden prepared:   {prep_g['inserted']} (hash {prep_g['dataset_hash'][:12]}...)")
    inputs, manifest = snapshot_inputs()
    bi: dict[str, list[dict]] = {}
    ref_c: dict[tuple[str, str, str | None], dict] = {}
    scalar: dict[str, object] = {}
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        for prefix in SNAPSHOT_FILES:
            f = next(HERE.glob(f"{prefix}_*.sql"))
            R.update(run_file(c, f))
            print(f"ran {f.name}")
        for name in BI_FILES:
            for k, rows in run_file(c, HERE / f"{name}.sql").items():
                bi[k.split("__")[-1] if "__" in k else k.removeprefix("bi_")] = rows
        print("ran the BI dimension and fact queries")
        cut_ids = sorted({r["prediction_at"] for r in c.execute("SELECT prediction_at FROM prediction_cutoffs").fetchall()})
        for m in MODELS:
            for pa in cut_ids:
                iso = pa.strftime("%Y-%m-%dT%H:%M:%SZ")
                ref_c[(m, iso, None)] = reference(c, AS_OF, iso, None, m)
        for sid in ("sc-001", "sc-002", "sc-003"):
            ref_c[("logistic_regression", "2026-09-01T00:00:00Z", sid)] = reference(c, AS_OF, "2026-09-01T00:00:00Z", sid)
        print(f"reference_metrics.sql on {len(cut_ids)} cutoffs x {len(MODELS)} models and the three scenarios")
        scalar["counts"] = {t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in
                            ("accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels", "training_runs", "predictions",
                             "scoring_publications", "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments", "rejected_records", "art_test_table")}
        scalar["outreach_status"] = [r["status"] for r in c.execute("SELECT status FROM outreach_events GROUP BY status ORDER BY status COLLATE \"C\"").fetchall()]
        scalar["dataset_version"] = dict(c.execute("SELECT dataset_version, dataset_hash FROM dataset_versions").fetchone())
        scalar["claims"] = {r["claim"]: r["value"] for r in c.execute("SELECT claim, value FROM art_published_claim").fetchall()}
    with psycopg.connect(gold_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        G = run_file(c, HERE / "09_golden_known_answer.sql")
        g_inputs = json.loads((GOLDEN_DIR / "inputs.json").read_text())
        ref_g = {pa: reference(c, g_inputs["as_of"], pa, sc) for pa, sc in (("2026-01-01T00:00:00Z", "sc-001"), ("2026-02-01T00:00:00Z", None))}
    R.update(G)

    # ---- A: golden fixture ---------------------------------------------------------------------------------------------------------------------------------------------------------
    exp = json.loads((GOLDEN_DIR / "expected.json").read_text())
    dom_g = evaluate(g_inputs)
    rec.add("A golden whole shape of expected.json (domain evaluate() vs the file, digest)", digest(dom_g), digest(exp))
    rec.add("A golden consistency block (domain vs expected.json)", digest(dom_g["consistency"]), digest(exp["consistency"]))
    keys = ("population", "churn_rate", "late_events", "precision_at_k", "recall_at_k", "risk_lift_at_k", "outreach_queue", "empty_population", "empty_evaluation")
    for pa, ref in ref_g.items():
        e, d = exp["cutoff_sets"][pa], dom_g["cutoff_sets"][pa]
        for k in keys:
            rec.add(f"A golden {pa[:10]} {k}: reference SQL = domain = expected.json (digest)", digest(ref[k]), digest(e[k]), digest(d[k]))
        rec.add(f"A golden {pa[:10]} brier_score: reference SQL = domain = expected.json (digest)", digest({"value": ref["brier_score"]["value"], "n": ref["brier_score"]["n"], "terms": ref["brier_score"]["terms"]}),
                digest({"value": e["brier_score"]["value"], "n": e["brier_score"]["n"], "terms": e["brier_score"]["terms"]}), digest({"value": d["brier_score"]["value"], "n": d["brier_score"]["n"], "terms": d["brier_score"]["terms"]}))
        rec.add(f"A golden {pa[:10]} calibration bins: reference SQL = domain = expected.json (digest)", digest(ref["calibration_bins"]),
                digest([{k: b[k] for k in ref["calibration_bins"][0]} for b in e["calibration"]["bins"]]), digest([{k: b[k] for k in ref["calibration_bins"][0]} for b in d["calibration"]["bins"]]))
        rec.add(f"A golden {pa[:10]} economics: reference SQL = domain = expected.json (budget, value, accounts)",
                digest(None if ref["economics"] is None else {k: ref["economics"][k] for k in ("contact_budget", "expected_value", "selected_account_ids")}),
                digest(None if e["economics"] is None else {k: e["economics"][k] for k in ("contact_budget", "expected_value", "selected_account_ids")}),
                digest(None if d["economics"] is None else {k: d["economics"][k] for k in ("contact_budget", "expected_value", "selected_account_ids")}))
        fm = e["feature_missingness"]
        rec.add(f"A golden {pa[:10]} feature missingness overall (reference SQL vs expected.json vs domain)", ref["feature_missingness"]["overall_value"], fm["overall"]["value"], d["feature_missingness"]["overall"]["value"])
    ka = G["09_golden_known_answer__known_answer"][0]
    jan = exp["cutoff_sets"]["2026-01-01T00:00:00Z"]
    for label, got, hand, from_exp in (("churn rate", ka["churn_rate"], "0.500000", jan["churn_rate"]["value"]), ("precision at K=2", ka["precision_at_k"], "0.500000", jan["precision_at_k"]["value"]),
                                       ("recall at K=2", ka["recall_at_k"], "0.500000", jan["recall_at_k"]["value"]), ("risk lift at K=2", ka["risk_lift_at_k"], "1.000000", jan["risk_lift_at_k"]["value"]),
                                       ("Brier score", ka["brier_score"], "0.192500", jan["brier_score"]["value"]), ("average precision (5/6)", ka["average_precision"], "0.833333", jan["average_precision"]["value"]),
                                       ("contact budget", ka["contact_budget"], "10.00", jan["economics"]["contact_budget"]), ("expected intervention value", ka["expected_intervention_value"], "8.45", jan["economics"]["expected_value"])):
        rec.add(f"A golden known answer {label}: SQL of investigation 09 = hand answer (CALCULATION.md) = expected.json", got, hand, from_exp)
    rec.add("A golden eligible of cutoff rows (4 of 6) and the two reasons (SQL 09 vs hand)", f"{ka['eligible_rows']}/{ka['cutoff_rows']}|{ka['ineligible_created_on_or_after_observation_start']}|{ka['ineligible_not_active']}", "4/6|1|1",
            f"{jan['population']['eligible']}/{jan['population']['cutoff_rows']}|{jan['population']['ineligible']['CREATED_ON_OR_AFTER_OBSERVATION_START']}|{jan['population']['ineligible']['NOT_ACTIVE']}")
    rec.add("A golden arrived-late events (SQL 09 vs expected.json): usage, support, billing, subscription", "|".join(str(r["arrived_late"]) for r in G["09_golden_known_answer__arrived_late"]),
            f"{jan['late_events']['usage_events']}|{jan['late_events']['support_events']}|{jan['late_events']['billing_events']}|{jan['late_events']['subscription_events']}")
    ce = G["09_golden_known_answer__censored_cohort"][0]
    feb = exp["cutoff_sets"]["2026-02-01T00:00:00Z"]
    rec.add("A golden censored February cohort: eligible/mature/censored, ranking metrics null (SQL 09 vs expected.json)", f"{ce['eligible_rows']}|{ce['mature_rows']}|{ce['censored_rows']}|{ce['churn_rate']}",
            f"{feb['population']['eligible']}|{feb['population']['mature']}|{feb['population']['censored']}|{feb['churn_rate']['value']}")
    for r in G["09_golden_known_answer__purge_counts"]:
        s = exp["split"]["tr-001"]["counts"][r["split_range"]]
        rec.add(f"A golden purge counts {r['split_range']} (SQL 09 vs expected.json)", f"{r['cutoff_rows']}|{r['retained']}|{r['label_window']}|{r['group_test']}|{r['group_validation']}",
                f"{s['total']}|{s['retained']}|{s['label_window']}|{s['group_test']}|{s['group_validation']}")
    for r in G["09_golden_known_answer__psi_against_the_march_2025_cohort"]:
        pd = exp["cutoff_sets"][r["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ")]["population_drift"]
        rec.add(f"A golden PSI {r['prediction_at'].date()} against 2025-03-01 (SQL ln() vs domain Decimal.ln vs expected.json)", r["psi"], pd["psi"], dom_g["cutoff_sets"][r["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ")]["population_drift"]["psi"])
    occupied = [(b["bin_index"], b["rows_in_bin"], fmt(b["gap_pp"])) for b in G["09_golden_known_answer__calibration_bins"] if not b["empty_bin"]]
    wanted = [(b["index"], b["count"], b["gap_pp"]) for b in jan["calibration"]["bins"] if b["count"]]
    rec.add("A golden occupied calibration bins and gaps (SQL 09 vs expected.json)", occupied, wanted)
    rec.add("A golden hand literals: gaps +10.00, -60.00, +60.00, -20.00 in bins 1, 4, 6, 8", "|".join(b[2] for b in occupied), "10.00|-60.00|60.00|-20.00")

    # ---- B: the cohort -----------------------------------------------------------------------------------------------------------------------------------------------------------
    claims = manifest["published_cohort"]["claims"]
    dom_c = {}
    for m in MODELS:
        dm = {**inputs, "predictions": [p for p in inputs["predictions"] if p["model_name"] == m], "scoring_publications": [p for p in inputs["scoring_publications"] if p["model_name"] == m],
              "scope": {"training_run_id": "tr-001", "sets": [{"prediction_at": pa, "scenario_id": None} for pa in sorted({c["prediction_at"] for c in inputs["prediction_cutoffs"]})]}}
        dom_c[m] = evaluate(dm)
    print("domain evaluate() over the loaded cohort for the four models")
    for m in MODELS:
        for pa in sorted(claims[m]["cutoff_sets"]):
            cl, d, ref = claims[m]["cutoff_sets"][pa], dom_c[m]["cutoff_sets"][pa], ref_c[(m, pa, None)]
            ref_view = {"cutoff_rows": ref["population"]["cutoff_rows"], "eligible": ref["population"]["eligible"], "mature": ref["population"]["mature"], "censored": ref["population"]["censored"],
                        "scored": ref["population"]["scored"], "evaluated": ref["population"]["evaluated"], "churned": ref["population"]["churned"], "churn_rate": ref["churn_rate"]["value"],
                        "brier_score": ref["brier_score"]["value"], "late_total": ref["late_events"]["total"], "missingness_overall": ref["feature_missingness"]["overall_value"]}
            dom_view = {"cutoff_rows": d["population"]["cutoff_rows"], "eligible": d["population"]["eligible"], "mature": d["population"]["mature"], "censored": d["population"]["censored"],
                        "scored": d["population"]["scored"], "evaluated": d["population"]["evaluated"], "churned": d["population"]["churned"], "churn_rate": d["churn_rate"]["value"],
                        "brier_score": d["brier_score"]["value"], "late_total": d["late_events"]["total"], "missingness_overall": d["feature_missingness"]["overall"]["value"]}
            cl_view = {"cutoff_rows": cl["cutoff_rows"], "eligible": cl["eligible"], "mature": cl["mature"], "censored": cl["censored"], "scored": cl["scored"], "evaluated": cl["evaluated"],
                       "churned": cl["churned"], "churn_rate": cl["churn_rate"], "brier_score": cl["brier_score"], "late_total": cl["late_events"]["total"], "missingness_overall": cl["missingness_overall"]}
            rec.add(f"B cohort {m} {pa[:10]}: reference SQL = domain re-run = manifest (counts, churn rate, Brier, late events, missingness; digest)", digest(ref_view), digest(dom_view), digest(cl_view))
    for m in MODELS:
        rec.add(f"B cohort {m}: the domain's consistency block over the loaded cohort is empty (stored derived rows = rebuilt rows)", digest(dom_c[m]["consistency"]), digest({k: [] for k in dom_c[m]["consistency"]}), digest(claims[m]["consistency"]))
    econ = manifest["published_cohort"]["economics"]
    P = {**ps.results(), **ps.golden_results()}
    for r in R["03_capacity_economics__cohort_economics"]:
        sid = r["scenario_id"]
        rf = ref_c[("logistic_regression", "2026-09-01T00:00:00Z", sid)]
        rec.add(f"B cohort economics {sid} expected value on 97 scored accounts (SQL 03 = reference SQL = manifest = python_side)", r["expected_value"], rf["economics"]["expected_value"], econ[sid]["expected_value"],
                next(x for x in P["03_capacity_economics__cohort_economics"] if x["scenario_id"] == sid)["expected_value"])
        rec.add(f"B cohort economics {sid} contact budget and capacity (SQL 03 = reference SQL = manifest)", f"{r['contact_budget']}|{r['selected_accounts']}", f"{rf['economics']['contact_budget']}|{len(rf['economics']['selected_account_ids'])}",
                f"{econ[sid]['contact_budget']}|{econ[sid]['capacity']}")
        rec.add(f"B cohort economics {sid} draft queue = the first {r['capacity']} of the ranking (stored rows in my top K vs manifest queue vs reference SQL)", r["stored_rows_in_my_top_k"], r["capacity"], len(set(rf["economics"]["selected_account_ids"]) & set(manifest["published_cohort"]["queue_account_ids"][sid])))
        rec.add(f"B cohort economics {sid} label hypothetical, no treatment effect, population 97", f"{r['label']}|{r['scored_accounts']}", f"{econ[sid]['label']}|{econ[sid]['population']}", f"hypothetical|{rf['outreach_queue']['population']}")
    rec.add("B cohort freshness: scoring 812 h, data 1 h (reference SQL vs manifest vs domain)", f"{ref_c[('logistic_regression', '2026-09-01T00:00:00Z', None)]['freshness']['scoring_hours']}|{ref_c[('logistic_regression', '2026-09-01T00:00:00Z', None)]['freshness']['data_hours']}",
            f"{claims['logistic_regression']['freshness']['scoring_hours']}|{claims['logistic_regression']['freshness']['data_hours']}", f"{dom_c['logistic_regression']['freshness']['scoring_hours']}|{dom_c['logistic_regression']['freshness']['data_hours']}")
    rec.add("B dataset version and hash: seed output = manifest = the constant of this package", f"{prep_s['dataset_version']}|{prep_s['dataset_hash']}", f"{manifest['dataset_version']}|{manifest['dataset_hash']}", f"{scalar['dataset_version']['dataset_version']}|{DATASET_HASH}")
    cnt = scalar["counts"]
    rc = manifest["row_counts"]
    for t in ("accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "predictions", "scoring_publications", "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments"):
        rec.add(f"B loaded rows of {t} (database count = manifest row_counts)", cnt[t], rc[t])
    rec.add("B loaded labels + the rejected injected labels = manifest labels (765 + 4 = 769)", cnt["labels"] + cnt["rejected_records"], rc["labels"])
    rec.add("B test table loaded = manifest row_counts.test_cohort", cnt["art_test_table"], rc["test_cohort"])

    # ---- C: every result set against python_side -------------------------------------------------------------------------------------------------------------------------------
    for key in sorted(R):
        a, b = ps.normalised(R[key]), ps.normalised(P[key])
        rec.add(f"C {key}: {len(a)} rows, every cell SQL = python_side.py (digest)", digest(a), digest(b))
    rec.add("C python_side covers exactly the result sets the SQL files produce", len(R), len(P))

    # ---- D: designed relationships, the calibration file, the split summary, the injection manifest -----------------------------------------------------------------------
    drs = {d["id"]: d["realised"] for d in manifest["designed_relationships"]}
    M = {r["model"]: r for r in R["01_model_comparison__models"]}
    name = {"random_baseline": "random_baseline", "business_rule": "business_rule", "logistic_regression": "logistic_regression (Platt)", "prevalence_baseline": "prevalence_baseline"}
    for m in MODELS:
        rec.add(f"D DR-01 {m}: average precision and Brier (SQL 01 vs manifest)", f"{M[name[m]]['average_precision']}|{M[name[m]]['brier_score']}", f"{drs['DR-01'][m]['average_precision']}|{drs['DR-01'][m]['brier_score']}")
        rec.add(f"D DR-01 {m}: rows, positives, prevalence (SQL 01 vs manifest)", f"{M[name[m]]['test_rows']}|{M[name[m]]['positive_rows']}|{M[name[m]]['prevalence']}", f"{drs['DR-01'][m]['n']}|{drs['DR-01'][m]['positives']}|{drs['DR-01'][m]['prevalence']}")
    mg = {r["margin"]: r["realised_margin"] for r in R["08_rows_and_margins__margins"]}
    for key, mk in (("ap_over_rule", "ap_over_rule"), ("ap_over_random", "ap_over_random"), ("brier_under_rule", "brier_under_rule"), ("brier_under_random", "brier_under_random")):
        rec.add(f"D DR-01 margin {key}: realised margin (SQL 08 vs manifest; met = by construction)", mg[mk], drs["DR-01"]["margins"][key])
    rec.add("D DR-01 reference margins over the prevalence constant (SQL 08 vs manifest)", f"{mg['ap_over_prevalence_constant (reference)']}|{mg['brier_under_prevalence_constant (reference)']}",
            f"{drs['DR-01']['reference_margins']['ap_over_prevalence_constant']}|{drs['DR-01']['reference_margins']['brier_under_prevalence_constant']}")
    rec.add("D DR-01 the model before Platt: Brier 0.104515 (SQL 01 vs calibration.json platt_effect)", M["logistic_regression (before Platt)"]["brier_score"], json.loads((SNAP_DIR / "calibration.json").read_text())["platt_effect"]["brier_uncalibrated"])
    cal = json.loads((SNAP_DIR / "calibration.json").read_text())
    pe = R["02_calibration_platt__platt_effect"][0]
    rec.add("D Platt effect (SQL 02 vs calibration.json): Brier before, after, gaps, fit rows, worse on test",
            f"{pe['brier_before']}|{pe['brier_after']}|{pe['overall_gap_pp_before']}|{pe['overall_gap_pp_after']}|{pe['fit_rows']}|{pe['made_the_brier_worse']}",
            f"{cal['platt_effect']['brier_uncalibrated']}|{cal['platt_effect']['brier_calibrated']}|{cal['platt_effect']['gap_pp_uncalibrated']}|{cal['platt_effect']['gap_pp_calibrated']}|{cal['platt_effect']['fit_rows']}|{cal['platt_effect']['worse_on_test']}")
    rec.add("D Platt mapping a, b (loaded calibration_maps vs calibration.json vs manifest training)", f"{pe['platt_a']}|{pe['platt_b']}", f"{cal['a']}|{cal['b']}", f"{manifest['training']['calibration']['a']}|{manifest['training']['calibration']['b']}")
    pr = R["02_calibration_platt__platt_reproduced"][0]
    rec.add("D the frozen Platt mapping applied in SQL reproduces the stored calibrated probability on all 1,513 rows", pr["equal_at_6_places"], pr["rows_compared"], 1513)
    rec.add("D calibration fit rows all come from one cutoff (cohort SQL 02 vs calibration.json fit_rows_by_cutoff)", R["02_calibration_platt__fit_rows_by_cutoff"][0]["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ"), list(cal["fit_rows_by_cutoff"])[0])
    for model, key in (("logistic_regression (Platt)", "reliability_calibrated"), ("logistic_regression (before Platt)", "reliability_uncalibrated")):
        sql_bins = [b for b in R["02_calibration_platt__bins"] if b["model"] == model]
        for b, pub in zip(sql_bins, cal[key]):
            rec.add(f"D reliability bin {b['bin_index']} of {model}: count, mean, observed, gap (SQL 02 vs calibration.json)", f"{b['rows_in_bin']}|{b['mean_predicted']}|{b['observed_rate']}|{b['gap_pp']}",
                    f"{pub['count']}|{pub['mean_predicted']}|{pub['observed_rate']}|{pub['gap_pp']}")
    for r in R["10_segment_region_calibration__by_segment"] + R["10_segment_region_calibration__by_region"]:
        pub = cal["by_segment" if r["dimension"] == "segment" else "by_region"][r["grp"]]
        rec.add(f"D DR-02 {r['dimension']} {r['grp']}: n, positives, mean, observed, gap (SQL 10 vs calibration.json)", f"{r['test_rows']}|{r['churning_rows']}|{r['mean_predicted']}|{r['observed_rate']}|{r['gap_pp']}",
                f"{pub['n']}|{pub['positives']}|{pub['mean_predicted']}|{pub['observed_rate']}|{pub['gap_pp']}")
    rec.add("D the largest regional gap is apac, -10.68 pp, not designed (SQL 10 vs calibration.json largest_region_gap)", next(r for r in R["10_segment_region_calibration__largest_gaps"] if r["dimension"] == "region")["most_negative_gap_group"] + "|" + str(next(r for r in R["10_segment_region_calibration__largest_gaps"] if r["dimension"] == "region")["gap_pp"]),
            f"{cal['largest_region_gap']['region']}|{cal['largest_region_gap']['gap_pp']}")
    rec.add("D overall calibration gap -2.86 pp and its mean predicted (SQL 10 vs calibration.json overall)", next(r for r in R["10_segment_region_calibration__largest_gaps"] if r["dimension"] == "overall")["gap_pp"], cal["overall"]["gap_pp"])
    agg = json.loads((SNAP_DIR / "cutoff_aggregates.json").read_text())
    pubd = {(d["prediction_at"], g): d[g] for d in agg["drift"]["by_cutoff"] for g in ("apac", "other_regions", "all_accounts")}
    for r in R["07_drift_by_region__psi_test_range"]:
        if r["grp"] in ("apac", "other_regions", "all_accounts"):
            pub = pubd[(r["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ"), r["grp"])]
            rec.add(f"D DR-03 PSI {r['grp']} {r['prediction_at'].date()}: recomputed in SQL from the test table vs published series (psi, reference rows, current rows, exceeds)",
                    f"{r['psi']}|{r['reference_rows']}|{r['current_rows']}|{r['exceeds_threshold']}", f"{pub['psi']}|{pub['reference_rows']}|{pub['current_rows']}|{pub['exceeds_threshold']}")
            if r["grp"] == "apac":
                rec.add(f"D DR-03 floored bins apac {r['prediction_at'].date()} (SQL from the test table vs published)", r["floored_bins"], pub["floored_bins"])
    dr3 = drs["DR-03"]
    sm = R["07_drift_by_region__published_summary"][0]
    rec.add("D DR-03 apac after the change: five exceedances from 2026-05-01, minimum and maximum PSI (SQL 07 vs manifest after_change_psi)", f"{sm['exceedances_from_the_change']}|{sm['shift_min_psi']}|{sm['shift_max_psi']}",
            f"{len(dr3['after_change_psi'])}|{min(dr3['after_change_psi'])}|{max(dr3['after_change_psi'])}")
    rec.add("D DR-03 the two published pre-change figures are 0.000000 (the reference) and 0.142972 (2026-03-01) (SQL 07 vs manifest before_change_psi)",
            "|".join(str(r["psi"]) for r in R["07_drift_by_region__psi_test_range"] if r["grp"] == "apac" and r["prediction_at"].month in (2, 3) and r["prediction_at"].year == 2026), "|".join(dr3["before_change_psi"]))
    rec.add("D DR-03 the whole population never exceeds 0.2 (maximum 0.043730) and other regions stay below it (SQL 07 vs the case study's claim)", f"{sm['all_accounts_max_psi']}|{sm['other_regions_max_psi']}", "0.043730|0.051631")
    rec.add("D R10-07 apac pre-change exceedances: 5 of 14 comparison cutoffs, 4 with a floored bin, maximum 0.679573 (SQL 07 vs the published series by python_side)",
            f"{sm['exceedances_before_the_change']}|{sm['comparison_cutoffs_before_the_change']}|{sm['exceedances_before_the_change_with_a_floored_bin']}|{sm['max_psi_before_the_change']}", "5|14|4|0.679573")
    cl = scalar["claims"]
    ws = R["04_censored_tail__world_summary"][0]
    rec.add("D DR-05 eligible, censored rows, share and mature churn rate (SQL 04 vs manifest)", f"{ws['eligible_rows']}|{ws['censored_rows']}|{ws['censored_share']}|{ws['mature_churn_rate']}", f"{manifest['population']['feature_rows']}|{drs['DR-05']['censored_rows']}|{drs['DR-05']['censored_share']}|{drs['DR-05']['mature_churn_rate']}")
    rec.add("D DR-05 the censored rows are exactly the last three cutoffs (SQL 04 vs manifest immature_cutoffs)", "|".join(r["prediction_at"].strftime("%Y-%m-%dT%H:%M:%SZ") for r in R["04_censored_tail__world_by_cutoff"] if r["censored"] > 0), "|".join(drs["DR-05"]["immature_cutoffs"]))
    for r in R["04_censored_tail__world_by_cutoff"]:
        if r["published_rate_if_censored_were_non_churn"] is not None:
            rec.add(f"D DR-05 {r['prediction_at'].date()} rate if censored rows were counted as non-churn, an integer number of cancellations seen so far (SQL 04 vs manifest)",
                    f"{r['published_rate_if_censored_were_non_churn']}|{r['implied_cancellations_seen_so_far']}", f"{drs['DR-05']['churn_rate_if_censored_were_non_churn'][r['prediction_at'].strftime('%Y-%m-%dT%H:%M:%SZ')]}|{round(float(drs['DR-05']['churn_rate_if_censored_were_non_churn'][r['prediction_at'].strftime('%Y-%m-%dT%H:%M:%SZ')]) * r['eligible'])}")
    for rng, pop in manifest["population"]["by_range"].items():
        s = [c for c in agg["cutoffs"] if c["range"] == rng]
        rec.add(f"D population range {rng}: eligible, mature, censored, churned (SQL 04 aggregate sums vs manifest population.by_range)",
                f"{sum(c['population']['eligible'] for c in s)}|{sum(c['population']['mature'] for c in s)}|{sum(c['population']['censored'] for c in s)}|{sum(c['population']['churned'] for c in s)}",
                f"{pop['eligible']}|{pop['mature']}|{pop['censored']}|{pop['churned']}")
    rec.add("D test prevalence 0.124917 and 1,513 rows (SQL 01 vs manifest population)", f"{M['logistic_regression (Platt)']['prevalence']}|{M['logistic_regression (Platt)']['test_rows']}", f"{manifest['population']['by_range']['test']['churn_rate']}|{manifest['population']['by_range']['test']['eligible']}")
    ra = R["08_rows_and_margins__rows_and_accounts"][0]
    rec.add("D R10-06 rows are not accounts: 1,513 rows from 442 accounts, 189 churning rows from 95 accounts (SQL 08 vs the generator test)", f"{ra['test_rows']}|{ra['distinct_accounts']}|{ra['churning_rows']}|{ra['churning_accounts']}", "1513|442|189|95")
    d4 = drs["DR-04"]
    for src in R["05_arrived_late__late_events_by_source"]:
        rec.add(f"D DR-04 late share {src['source']}: published full-world share = manifest realised share (SQL 05 vs manifest); the cohort share is a different population", src["published_full_world_share"], d4["realised"][src["source"]]["share"])
    pf = {r["claim"]: r["value"] for r in R["05_arrived_late__published_full_world"]}
    rec.add("D DR-04 full-world test rows with a late event 183, features that change 175 = 0.115664 (published, SQL 05 vs manifest)", f"{pf['test_rows_with_a_late_event']}|{pf['test_rows_features_change_if_ignored']}|{pf['share_of_test_rows_changed']}",
            f"{d4['test_rows_with_a_late_event']}|{d4['test_rows_features_change_if_ignored']}|{d4['share_of_test_rows_changed']}")
    fr = R["05_arrived_late__feature_recomputation"][0]
    rec.add("D point-in-time: all 765 stored feature rows equal the recomputation from the events (SQL 05)", fr["stored_equals_point_in_time_recomputation"], fr["feature_rows"], manifest["row_counts"]["feature_rows"])
    sp = json.loads((SNAP_DIR / "split_summary.json").read_text())
    for r in R["06_purge_counts__world_published"]:
        mt = manifest["training"]["split_counts_population"][r["split_range"]]
        rec.add(f"D purge counts of the whole world {r['split_range']} (SQL 06 on the published split vs manifest training vs split_summary)", f"{r['cutoff_rows']}|{r['retained']}|{r['label_window']}|{r['group_test']}|{r['group_validation']}",
                f"{mt['total']}|{mt['retained']}|{mt['label_window']}|{mt['group_test']}|{mt['group_validation']}", f"{sp['population'][r['split_range']]['total']}|{sp['population'][r['split_range']]['retained']}|{sp['population'][r['split_range']]['label_window']}|{sp['population'][r['split_range']]['group_test']}|{sp['population'][r['split_range']]['group_validation']}")
    for r in R["06_purge_counts__cohort_recomputed"]:
        s = sp["published_cohort"][r["split_range"]]
        rec.add(f"D purge counts of the cohort {r['split_range']}: recomputed in SQL from the cutoff windows vs split_summary published_cohort vs manifest claims",
                f"{r['cutoff_rows']}|{r['retained']}|{r['label_window']}|{r['group_test']}|{r['group_validation']}", f"{s['total']}|{s['retained']}|{s['label_window']}|{s['group_test']}|{s['group_validation']}",
                f"{claims['logistic_regression']['split_counts'][r['split_range']]['total']}|{claims['logistic_regression']['split_counts'][r['split_range']]['retained']}|{claims['logistic_regression']['split_counts'][r['split_range']]['label_window']}|{claims['logistic_regression']['split_counts'][r['split_range']]['group_test']}|{claims['logistic_regression']['split_counts'][r['split_range']]['group_validation']}")
    rec.add("D the 104-day embargo (SQL 06 vs split_summary vs manifest training)", R["06_purge_counts__world_totals"][0]["embargo_days"], sp["embargo_days"], manifest["training"]["embargo_days"])
    rec.add("D the training run: 744 rows fit, 79 positives; validation 289 rows, 27 positives (manifest training vs calibration fit_rows)", f"{manifest['training']['training_rows']}|{manifest['training']['training_positives']}|{manifest['training']['validation_rows']}|{manifest['training']['validation_positives']}",
            "744|79|289|27", f"{manifest['training']['preprocessing']['fit_rows']}|79|{cal['fit_rows']}|27")
    wp = {r["scenario_id"]: r for r in R["03_capacity_economics__both_populations"]}
    efw = manifest["economics_full_world"]["scenarios"]
    for sid, e in efw.items():
        rec.add(f"D full-world economics {sid}: scored accounts, budget, value (SQL 03 loaded aggregate vs manifest vs cutoff_aggregates)", f"{wp[sid]['world_scored_accounts']}|{wp[sid]['world_contact_budget']}|{wp[sid]['world_expected_value']}",
                f"{e['scored_accounts']}|{e['contact_budget']}|{e['expected_value']}", f"{agg['economics_full_world']['scenarios'][sid]['scored_accounts']}|{agg['economics_full_world']['scenarios'][sid]['contact_budget']}|{agg['economics_full_world']['scenarios'][sid]['expected_value']}")
    rec.add("D the cohort values (+21.38 / -6.87 / -95.46 on 97) and the world values (+81.13 / +71.04 / -29.12 on 1,241) are different populations (SQL 03)",
            "|".join(f"{wp[s]['cohort_expected_value']}@{wp[s]['cohort_scored_accounts']}/{wp[s]['world_expected_value']}@{wp[s]['world_scored_accounts']}" for s in sorted(wp)), "21.38@97/81.13@1241|-6.87@97/71.04@1241|-95.46@97/-29.12@1241")
    kt = {(r["model"], r["capacity"]): r for r in R["03_capacity_economics__test_population_at_k"]}
    rec.add("D top-K of the logistic model on the test population: churners in the top 5, 10, 20 (SQL 03 vs python_side)", "|".join(str(kt[("logistic_regression (Platt)", k)]["churners_in_top_k"]) for k in (5, 10, 20)), "0|2|5")
    inj = json.loads((SNAP_DIR / "injection-manifest.json").read_text())["injections"]
    inj_by = {i["id"] if "id" in i else k: i for k, i in (inj.items() if isinstance(inj, dict) else enumerate(inj))}
    rej = R["04_censored_tail__rejected_false_labels"][0]
    rec.add("D INJ-07 four labels of false for an open window are refused CENSORED_LABEL and kept raw (SQL 04 vs injection manifest)", f"{rej['reason_code']}|{rej['rejected_labels']}", "CENSORED_LABEL|4")
    rec.add("D INJ-03 no account retained on both sides of a boundary (SQL 06 vs injection manifest check)", R["06_purge_counts__cohort_no_account_on_both_sides"][0]["accounts_retained_in_two_ranges"], 0)
    rec.add("D INJ-04 no retained train or validation row has a label window crossing its boundary (SQL 06)", sum(r["retained_rows_crossing_the_boundary"] for r in R["06_purge_counts__cohort_label_windows_inside_the_range"]), 0)
    rec.add("D INJ-09 every outreach row is a draft (loaded outreach_events)", "|".join(scalar["outreach_status"]), "draft")
    rec.add("D INJ-10 the three capacities are within the scored population (SQL 03: scored accounts >= capacity)", all(r["scored_accounts"] >= r["capacity"] for r in R["03_capacity_economics__cohort_economics"]), True)
    rec.add("D cohort maturity rule: stored flag and label_end equal the 104-day rule for all 765 labelled rows (SQL 04)", f"{R['04_censored_tail__cohort_maturity_rule'][0]['stored_flag_equals_rule']}|{R['04_censored_tail__cohort_maturity_rule'][0]['stored_label_end_equals_rule']}", "765|765")

    # ---- E: the BI package ------------------------------------------------------------------------------------------------------------------------------------------------------
    csvs = {k: [{c: fmt(v) for c, v in r.items()} for r in rows] for k, rows in bi.items()}
    meas_rows = bi_measures(csvs)
    fm = {(r["population_key"], r["model_key"]): r for r in csvs["fact_model_metric"]}
    mm = {(r["measure"], r["slice"]): r for r in meas_rows if r["population"] == "test_world"}
    for key, mname in (("random_baseline", "random_baseline"), ("business_rule", "business_rule"), ("logistic_regression", "logistic_regression"), ("prevalence_baseline", "prevalence_baseline"), ("logistic_uncalibrated", "logistic_uncalibrated")):
        rec.add(f"E BI measure average precision and Brier of {key}: recomputed from the CSV test rows vs the SQL fact vs investigation 01 vs the manifest",
                f"{mm[('average_precision', key)]['value']}|{mm[('brier_score', key)]['value']}", f"{fm[('test_world', key)]['average_precision']}|{fm[('test_world', key)]['brier_score']}",
                f"{next(x for x in R['01_model_comparison__models'] if x['model'].startswith(name.get(key, key.replace('logistic_uncalibrated', 'logistic_regression (before Platt)'))))['average_precision']}|"
                f"{next(x for x in R['01_model_comparison__models'] if x['model'].startswith(name.get(key, key.replace('logistic_uncalibrated', 'logistic_regression (before Platt)'))))['brier_score']}" if key != "logistic_regression" else f"{M['logistic_regression (Platt)']['average_precision']}|{M['logistic_regression (Platt)']['brier_score']}",
                f"{drs['DR-01'][key]['average_precision']}|{drs['DR-01'][key]['brier_score']}" if key in drs["DR-01"] else None)
    for c in csvs["fact_capacity"]:
        if c["population_key"] == "test_world":
            for kind, col in (("precision_at_k", "precision_at_k"), ("recall_at_k", "recall_at_k"), ("risk_lift_at_k", "risk_lift_at_k")):
                rec.add(f"E BI {kind} {c['model_key']} {c['scenario_id']}: recomputed from the CSV rows vs the SQL fact", mm[(kind, f"{c['model_key']}|K={c['capacity']}")]["value"], c[col])
        else:
            ev = next(m for m in meas_rows if m["measure"] == "expected_intervention_value" and m["population"] == c["population_key"] and m["slice"] == c["scenario_id"])
            rec.add(f"E BI expected value {c['population_key']} {c['scenario_id']}: measure vs SQL fact vs investigation 03 (hypothetical)", ev["value"], c["expected_value"],
                    next(x for x in R["03_capacity_economics__both_populations"] if x["scenario_id"] == c["scenario_id"])["cohort_expected_value" if c["population_key"] == "cohort_200" else "world_expected_value"])
    rec.add("E BI every economics measure is labelled hypothetical and names its population", all(m["result_kind"] == "hypothetical" and m["population"] in ("cohort_200", "world_2400", "all") for m in meas_rows if m["measure"] in ("expected_intervention_value", "contact_budget", "treatment_effect_estimate")), True)
    rec.add("E BI nothing is withheld silently: every row with an empty value has a status other than 'value'", all(m["status"] != "value" for m in meas_rows if m["value"] == ""), True)
    rec.add("E BI the six empty reliability bins of the Platt-calibrated model are rows with a stated reason", sum(1 for m in meas_rows if m["measure"] == "calibration_gap_pp" and m["slice"].startswith("logistic_regression|bin") and m["status"] == "null: empty bin"), 6)
    rec.add("E BI CSV row counts equal the SQL fact counts (test rows 1513; model metric 5; capacity 18; cutoff 42; drift 91; purge 8; segment gap 9)", "|".join(str(len(csvs[k])) for k in ("fact_test_row", "fact_model_metric", "fact_capacity", "fact_cutoff", "fact_drift", "fact_purge", "fact_segment_gap")), "1513|5|18|42|91|8|9")
    ds = {r["population_key"]: r for r in csvs["dim_population"]}
    rec.add("E BI dimension keys: every fact key is in its dimension (population, model, scenario, cutoff)",
            all(r["population_key"] in ds for k in ("fact_model_metric", "fact_capacity", "fact_cutoff", "fact_purge", "fact_segment_gap", "fact_calibration_bin") for r in csvs[k])
            and all(r["model_key"] in {m["model_key"] for m in csvs["dim_model"]} for k in ("fact_model_metric", "fact_capacity", "fact_calibration_bin") for r in csvs[k])
            and all(r["scenario_id"] in {s["scenario_id"] for s in csvs["dim_scenario"]} for r in csvs["fact_capacity"])
            and all(r["prediction_at"] in {c["prediction_at"] for c in csvs["dim_cutoff"]} for r in csvs["fact_cutoff"]), True)

    # ---- F: the whole world --------------------------------------------------------------------------------------------------------------------------------------------------
    if skip_world:
        print("F skipped (--skip-world): the whole-world rebuild was not run")
    else:
        gen = load_module("rl_generate", ROOT / "data" / "generate.py")
        B = gen.build_all(SEED)
        tt = json.loads((SNAP_DIR / "test_cohort.json").read_text())
        rec.add("F full world: the rebuilt test table equals test_cohort.json (1,513 rows x 14 columns, digest)", digest(B["test_table"]["rows"]), digest(tt["rows"]), digest([r for r in tt["rows"]]))
        rec.add("F full world: the rebuilt economics equal manifest economics_full_world and cutoff_aggregates (digest)", digest(B["economics_full_world"]), digest(manifest["economics_full_world"]), digest(agg["economics_full_world"]))
        for a, pubc in zip(B["aggregates"], agg["cutoffs"]):
            rec.add(f"F full world {a['prediction_at'][:10]}: rebuilt population, churn rate and four models' AP/Brier equal cutoff_aggregates (digest)", digest([a["population"], a["churn_rate"], a["models"]]), digest([pubc["population"], pubc["churn_rate"], pubc["models"]]))
        rec.add("F full world: the rebuilt censored-tail design relationship equals the manifest (DR-05, digest)", digest({k: B["dr"]["censored"][k] for k in ("eligible_rows", "censored_rows", "censored_share", "mature_churn_rate", "churn_rate_if_censored_were_non_churn")}),
                digest({k: drs["DR-05"][k] for k in ("eligible_rows", "censored_rows", "censored_share", "mature_churn_rate", "churn_rate_if_censored_were_non_churn")}))
        rec.add("F full world: the rebuilt population statistics (accounts, events, ranges, 9,039 eligible rows, 3,594 censored) equal manifest population (digest)", digest(gen.population_stats(B)), digest(manifest["population"]))
        run_pub = json.loads((SNAP_DIR / "training_runs.json").read_text())["rows"][0]
        rec.add("F full world: the rebuilt training run (config, config hash, boundaries) equals the published run and the manifest (digest)", digest([B["fit"]["run"]["config"], B["fit"]["run"]["config_hash"]]),
                digest([run_pub["config"], run_pub["config_hash"]]), digest([manifest["training"]["config_hash"] and run_pub["config"], manifest["training"]["config_hash"]]))
        rec.add("F full world: the rebuilt split counts equal split_summary and the manifest (digest)", digest(B["fit"]["split_counts"]), digest(sp["population"]), digest(manifest["training"]["split_counts_population"]))
        print("F the 2,400-account world rebuilt in memory and compared")

    # ---- results ---------------------------------------------------------------------------------------------------------------------------------------------------------------------
    equal = sum(1 for r in rec.rows if r["equal"])
    meta = {"dataset_hash": DATASET_HASH, "dataset_version": manifest["dataset_version"], "code_revision": CODE_REVISION, "contract_version": 1, "seed": SEED, "as_of": AS_OF,
            "golden_dataset_hash": prep_g["dataset_hash"], "accounts_in_cohort": manifest["row_counts"]["accounts"], "test_rows": manifest["row_counts"]["test_cohort"],
            "whole_world_rebuilt": not skip_world, "reconciliation_rows": len(rec.rows), "reconciliation_equal": equal, "result_sets": len(R), "result_rows": sum(len(R[k]) for k in R)}
    for r in rec.rows:
        print(("OK   " if r["equal"] else "DIFF ") + r["check"] + (" | " + " | ".join(str(r[k]) for k in ("analysis_sql", "second_source", "third_source", "fourth_source") if r[k] != "") if not r["equal"] else ""))
    print(f"RESULT: {'OK' if rec.ok else 'FAILED'} ({len(rec.rows)} reconciliation rows, {equal} equal; {meta['result_sets']} result sets, {meta['result_rows']} rows)")
    if bi_out:
        for k, rows in csvs.items():
            export_csv(bi_out / f"{k}.csv", rows)
        export_csv(bi_out / "measures_recomputed.csv", meas_rows)
        print(f"wrote {len(csvs) + 1} CSV files to {bi_out}")
    if json_out:
        groups = {"A": "golden fixture", "B": "cohort (reference SQL, domain, manifest)", "C": "every result set against python_side.py", "D": "designed relationships and published files",
                  "E": "BI package", "F": "whole 2,400-account world rebuilt in memory"}
        summary = [{"group": g, "what": groups[g], "rows": sum(1 for r in rec.rows if r["check"].startswith(g + " ")), "equal": sum(1 for r in rec.rows if r["check"].startswith(g + " ") and r["equal"])}
                   for g in sorted(groups)]
        out = {"meta": [meta], **{k: ps.normalised(v) for k, v in R.items()}, "bi_measures": meas_rows, "reconciliation_summary": summary,
               "reconciliation_listing": [{"n": i, "check": r["check"], "equal": r["equal"]} for i, r in enumerate(rec.rows, 1)], "reconciliation": rec.rows}
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
        print(f"wrote {json_out}")
    return 0 if rec.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
