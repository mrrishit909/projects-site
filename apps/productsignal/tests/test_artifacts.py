"""Artifact package checks (P06-ART-01..10): the SQL analysis results, the analyst workbook, the BI exports, the documents and the checksums.

openpyxl cannot calculate formulas, so this file (1) proves from the workbook's cell contents that every result cell of the formula sheets is a live
formula, (2) reads the values LibreOffice cached in the delivered file and compares them with the Python domain RECOMPUTED HERE (not with the pasted
reference column), (3) recalculates copies with LibreOffice headless for each of the five logged runs (formulas only, so no cache) and compares each with
the domain for that run, (4) checks that the stored analysis results equal the plain-Python recomputation over web/public/data (no database), through
data/sql/analysis/python_side.py, which shares no code with the SQL or the domain, (5) recomputes the BI measures from the CSV exports, (6) checks that each
document quotes the stored results and the public case study, and (7) checks CHECKSUMS.txt and the release-package table.
With ARTIFACTS_DATABASE_URL (a scratch database named artifacts06_* prepared by data/sql/analysis/prepare_snapshot.py) it also re-runs the SQL files and
compares their rows with the stored results; without it that test is skipped. Excel and Power BI are never run.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "data" / "sql" / "analysis"
DOCS = ROOT / "docs"
ART = ROOT / "artifacts"
for _p in (ROOT / "domain", ROOT, SQL_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

openpyxl = pytest.importorskip("openpyxl")

XLSX = ART / "productsignal-analyst-workbook.xlsx"
RES = json.loads((ART / "analysis-results.json").read_text()) if (ART / "analysis-results.json").exists() else {}
CODE_REVISION = "fdf911a"
DATASET_HASH = "12672f9c39402517083bbbbe9164cbefe3435361dff086eb0d9e16e60f9b66f8"
RUNS = ("an-001", "an-002", "an-003", "an-004", "an-005")
_CASE_STUDY = next((p for p in (ROOT.parents[1] / "productsignal" / "project.json", ROOT.parents[3] / "productsignal" / "project.json") if p.exists()), None)
PROJECT = json.loads(_CASE_STUDY.read_text()) if _CASE_STUDY else None          # the public case study lives on unified-portfolio, in the main checkout

pytestmark = pytest.mark.skipif(not XLSX.exists() or not RES, reason="artifacts not built (data/sql/analysis/run_all.py, artifacts/build_workbook.py)")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ps():
    import python_side
    return python_side


@pytest.fixture(scope="module")
def ctx(ps):
    return ps.load()


@pytest.fixture(scope="module")
def wb():
    return openpyxl.load_workbook(XLSX)


@pytest.fixture(scope="module")
def wbv():
    return openpyxl.load_workbook(XLSX, data_only=True)


@pytest.fixture(scope="module")
def bw():
    return _load("ps_build_workbook", ART / "build_workbook.py")


@pytest.fixture(scope="module")
def ra():
    return _load("ps_run_all", SQL_DIR / "run_all.py")


@pytest.fixture(scope="module")
def domain_ref(bw, ctx):
    return bw.domain_reference(ctx)


def row_of(key: str, **where) -> dict:
    return next(r for r in RES[key] if all(str(r[k]) == str(v) for k, v in where.items()))


def read(name: str) -> str:
    return (DOCS / name).read_text()


def n(x) -> str:
    """A stored number as the documents print it: thousands separators on the integer part."""
    s = str(x)
    whole, _, frac = s.partition(".")
    return f"{int(whole):,}" + (f".{frac}" if frac else "")


def sha_of(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def all_test_names() -> str:
    return " ".join(p.read_text() for p in (ROOT / "tests").glob("test_*.py"))


# ---- stored analysis results ---------------------------------------------------------------------------------------------------------------

def test_analysis_results_reconcile_and_cover_every_investigation(ps):
    assert RES["reconciliation"] and all(r["equal"] is True for r in RES["reconciliation"])
    assert len(RES["reconciliation"]) >= 250
    meta = RES["meta"][0]
    assert meta["dataset_hash"] == DATASET_HASH and meta["code_revision"] == CODE_REVISION
    assert meta["reconciliation_rows"] == len(RES["reconciliation"]) == meta["reconciliation_equal"]
    for key in ps.KEYS:
        assert RES[key], key
    numbered = sorted(p.name for p in SQL_DIR.glob("0[1-8]_*.sql"))
    assert len(numbered) == 8                                          # eight numbered investigations
    assert {k.split("__")[0] for k in ps.KEYS} == {p[:-4] for p in numbered}
    for k in ("09_golden_known_answer__golden_arms", "09_golden_known_answer__golden_lift", "09_golden_known_answer__golden_retention"):
        assert RES[k]
    assert {c.split(" ")[0] for c in (r["check"] for r in RES["reconciliation"])} == {"A", "B", "C", "D", "E"}
    assert meta["result_sets"] == len(ps.KEYS) + 3


def test_golden_fixture_reference_sql_domain_and_expected_json_agree_on_every_key():
    from productsignal import run_pipeline
    from productsignal.contract import METRIC_KEYS
    expected = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())
    inputs = json.loads((ROOT / "tests/fixtures/golden/inputs.json").read_text())
    res = run_pipeline(inputs)
    assert res.metrics == expected["metrics"]
    rows = {r["check"].split(" ")[3].rstrip(":"): r for r in RES["reconciliation"] if r["check"].startswith("A golden metric ")}
    assert set(rows) == set(METRIC_KEYS) == set(expected["metrics"]) and len(rows) == 6
    for k in METRIC_KEYS:
        r = rows[k]
        assert r["analysis_sql"] == r["second_source"] == r["third_source"] == sha_of(expected["metrics"][k]), k       # the reference SQL, expected.json and the domain
    for label, key in (("tracking_quality", "tracking_quality"), ("identity", "identity")):
        r = next(x for x in RES["reconciliation"] if x["check"].startswith(f"A golden {label}"))
        assert r["analysis_sql"] == r["second_source"] == r["third_source"] == sha_of(expected[key])
    arms = {r["arm"]: r for r in RES["09_golden_known_answer__golden_arms"]}
    assert (arms["control"]["activated"], arms["control"]["mature"], arms["treatment"]["activated"], arms["treatment"]["mature"]) == ("20", "100", "30", "100")
    lift = RES["09_golden_known_answer__golden_lift"][0]
    assert (lift["absolute_lift_pp"], lift["relative_lift"]) == ("10.00", "0.500000")
    ret = RES["09_golden_known_answer__golden_retention"][0]
    assert (ret["cohort_accounts"], ret["day7_retained"], ret["day7_rate"]) == ("20", "5", "0.250000")


def test_stored_results_equal_the_python_side_recomputation_over_the_snapshot_files(ps, ctx):
    py = ps.compute(ctx)
    for key in ps.KEYS:
        assert RES[key] == ps.normalised(py[key]), key


def test_stored_reference_figures_equal_the_domain(ps):
    """Recompute the domain here and compare it with the stored SQL results at the as-of and at every logged run cutoff."""
    from productsignal import run_pipeline
    m = json.loads((ROOT / "web/public/data/manifest.json").read_text())
    rows = {e: json.loads((ROOT / f"web/public/data/{e}.json").read_text())["rows"] for e in m["row_counts"]}
    inputs = {"contract_version": 1, "as_of": m["as_of"], "cutoff": m["cutoff"], "metric_windows": m["metric_windows"], **rows}
    lift = {r["run"]: r for r in RES["05_experiment_v1_at_each_run_cutoff__lift_by_cutoff"]}
    arms = {(r["run"], r["arm"]): r for r in RES["05_experiment_v1_at_each_run_cutoff__arms_by_cutoff"]}
    guard = {r["run"]: r for r in RES["07_guardrail_and_revenue_per_arm__guardrail_by_cutoff"]}
    rev = {(r["run"], r["arm"]): r for r in RES["07_guardrail_and_revenue_per_arm__revenue_by_arm"]}
    for run, rid in (("an-001", "an-001"), ("an-002", "an-002"), ("an-003", "an-003"), ("an-004", "an-004"), ("as-of", None)):
        d = run_pipeline({**inputs, "analysis_plan": m["analysis_plans"]["xv-001"]}, cutoff=ps.RUNS[run], experiment_version_id="xv-001", run_id=rid)
        ex = d.metrics["experiment"]
        p = ex["primary"]
        r = lift[run]
        assert (r["absolute_lift_pp"], r["relative_lift"], r["newcombe_low"], r["newcombe_high"]) == (p["absolute_lift_pp"], p["relative_lift"], p["interval"]["low"], p["interval"]["high"]), run
        assert r["conclusive"] == ("true" if p["conclusive"] else "false") and r["srm_verdict"] == ex["srm"]["verdict"]
        assert (r["srm_statistic"], r["srm_p_value"]) == (ex["srm"]["statistic"], ex["srm"]["p_value"]) and r["prior_runs"] == ("" if ex["run"]["prior_runs"] is None else str(ex["run"]["prior_runs"]))
        for arm in ("control", "treatment"):
            v, a = p["variants"][arm], arms[(run, arm)]
            assert (a["assigned"], a["mature"], a["activated"], a["conversion"], a["wilson_low"], a["wilson_high"]) == (
                str(v["assigned"]), str(v["mature_units"]), str(v["activated"]), v["conversion"], v["wilson_95"]["low"], v["wilson_95"]["high"]), (run, arm)
            e = ex["exposure"]["by_variant"][arm]
            assert (a["exposed"], a["exposure_rate"]) == (str(e["exposed"]), e["rate"]), (run, arm)
            g = ex["guardrail"]["by_variant"][arm]
            assert (guard[run][f"eligible_{arm}"], guard[run][f"errors_{arm}"], guard[run][f"error_rate_{arm}"]) == (str(g["eligible_units"]), str(g["units_with_error"]), g["error_rate"]), (run, arm)
            q, x = rev[(run, arm)], ex["revenue_per_assigned_account"]["by_variant"][arm]
            assert (q["units"], q["total_usd"], q["mean_usd"], q["interval_low"], q["interval_high"]) == (str(x["units"]), x["total"], x["mean"], x["interval"]["low"], x["interval"]["high"]), (run, arm)
    d2 = run_pipeline({**inputs, "analysis_plan": m["analysis_plans"]["xv-002"]}, cutoff=ps.RUNS["an-005"], experiment_version_id="xv-002", run_id="an-005")
    s2 = next(r for r in RES["06_experiment_v2_sample_ratio__srm_by_read"] if r["experiment_version"] == "xv-002" and r["run"] == "an-005")
    assert (s2["statistic"], s2["verdict"]) == (d2.metrics["experiment"]["srm"]["statistic"], d2.metrics["experiment"]["srm"]["verdict"]) == ("25.004329", "MISMATCH")
    d2a = run_pipeline({**inputs, "analysis_plan": m["analysis_plans"]["xv-002"]}, cutoff=ps.RUNS["as-of"], experiment_version_id="xv-002")
    pop = {r["arm"]: r for r in RES["06_experiment_v2_sample_ratio__v2_population"]}
    assert (int(pop["control"]["mature"]) + int(pop["treatment"]["mature"]), int(pop["treatment"]["mature"])) == (d2a.metrics["experiment"]["mature_units"], d2a.metrics["experiment"]["primary"]["variants"]["treatment"]["mature_units"]) == (144, 87)
    assert lift["an-004"]["newcombe_low"] == "0.000812" and lift["an-004"]["conclusive"] == "true"                  # conclusive by a hair


def test_headline_numbers_of_the_documents_are_the_stored_ones():
    memo, case, sqla, wbd = read("executive-memo.md"), read("business-case.md"), read("sql-analysis.md"), read("workbook.md")
    lift = {r["run"]: r for r in RES["05_experiment_v1_at_each_run_cutoff__lift_by_cutoff"]}
    arms = {(r["run"], r["arm"]): r for r in RES["05_experiment_v1_at_each_run_cutoff__arms_by_cutoff"]}
    for run in ("an-001", "an-002", "an-003", "an-004"):
        r = lift[run]
        for doc in (memo, sqla, wbd):
            for v in (r["conversion_control"], r["conversion_treatment"], r["newcombe_low"].lstrip("-"), r["newcombe_high"], r["absolute_lift_pp"]):
                assert v in doc, (run, v)
        assert f"{arms[(run, 'control')]['activated']} / {arms[(run, 'treatment')]['activated']}" in memo and f"{arms[(run, 'control')]['activated']} / {arms[(run, 'treatment')]['activated']}" in wbd
    assert lift["an-004"]["relative_lift"] == "0.301587" and all("0.301587" in d for d in (memo, case, sqla, wbd))
    assert lift["an-001"]["assigned_control"] == "77" and lift["an-001"]["assigned_treatment"] == "78" and "155 accounts" in sqla and "155 accounts" in case
    g = row_of("07_guardrail_and_revenue_per_arm__guardrail_by_cutoff", run="an-004")
    assert (g["errors_control"], g["errors_treatment"], g["difference_pp"], g["newcombe_low"], g["newcombe_high"], g["verdict"]) == ("31", "30", "-0.50", "-0.076005", "0.066018", "OK")
    rev = {r["arm"]: r for r in RES["07_guardrail_and_revenue_per_arm__revenue_by_arm"] if r["run"] == "an-004"}
    rd = row_of("07_guardrail_and_revenue_per_arm__revenue_difference", run="an-004")
    assert (rev["control"]["mean_usd"], rev["treatment"]["mean_usd"], rd["difference_usd"], rd["interval_low"], rd["interval_high"], rd["welch_df"]) == ("97.83", "130.95", "33.12", "-25.59", "91.83", "391")
    assert (rev["control"]["total_usd"], rev["treatment"]["total_usd"]) == ("19566.00", "26190.00")
    for doc in (memo, sqla, wbd):
        for v in ("97.83", "130.95", "33.12", "25.59", "91.83", "0.076005", "0.066018"):
            assert v in doc, v
    assert "19,566.00" in sqla and "26,190.00" in sqla
    w4 = RES["07_guardrail_and_revenue_per_arm__week4_by_arm"][0]
    assert (w4["retained_control"], w4["mature_control"], w4["retained_treatment"], w4["difference_pp"], w4["newcombe_low"], w4["newcombe_high"]) == ("71", "200", "62", "-4.50", "-0.136053", "0.047102")
    for doc in (memo, sqla):
        assert "0.136053" in doc and "0.047102" in doc
    v2 = row_of("06_experiment_v2_sample_ratio__srm_by_read", experiment_version="xv-002", run="an-005")
    assert (v2["observed_control"], v2["observed_treatment"], v2["expected_control"], v2["expected_treatment"], v2["statistic"], v2["p_value"]) == ("62", "92", "92.40", "61.60", "25.004329", "0.000001")
    for doc in (memo, case, sqla, wbd):
        assert "25.004329" in doc and "MISMATCH" in doc
    gap = {r["reading"]: r for r in RES["05_experiment_v1_at_each_run_cutoff__gap_lift"]}
    assert gap["published (all mature accounts)"]["absolute_lift_pp"] == "9.50" and gap["excluding the gap accounts from both arms"]["absolute_lift_pp"] == "9.96"
    for doc in (memo, case, sqla, wbd):
        assert "+9.50" in doc and "+11.50" in doc and "+9.96" in doc, doc[:60]
    ps_all = [r for r in RES["01_activation_by_plan_and_segment__plan_segment"] if r["plan"] == "ALL" and r["segment"] == "ALL"][0]
    assert (ps_all["accounts"], ps_all["mature"], ps_all["immature"], ps_all["activated"], ps_all["activation_rate"]) == ("588", "571", "17", "214", "0.374781")
    assert "0.374781" in sqla and "0.374781" in case
    tq = [r for r in RES["04_tracking_quality_by_week__by_week"] if r["week_start"] == "ALL"][0]
    for k in ("rows_total", "duplicates_dropped", "unknown_identity", "bot_excluded", "internal_excluded", "analysed", "delayed_over_24h"):
        assert n(tq[k]) in sqla, k
    assert tq["delayed_share"] == "0.019070" and "0.019070" in sqla and "0.019070" in case and "0.697121" in sqla and "0.697121" in case
    fs = {r["step"]: r["units"] for r in RES["03_funnel_steps_and_exclusions__funnel_steps"]}
    assert fs == {"visit": "154", "signup": "51", "onboarding_step_1": "41", "activated": "4"}
    ts = {r["plan"]: r for r in RES["01_activation_by_plan_and_segment__time_to_activation_by_plan"]}
    assert (ts["business"]["activation_rate"], ts["business"]["median_hours_to_activate"]) == ("0.527778", "9.62") and "9.62 hours" in sqla and "0.527778" in case
    grid = {r["week_start"]: r for r in RES["02_weekly_cohort_grid__cohort_grid"]}
    assert (grid["2026-04-13"]["accounts"], grid["2026-04-13"]["day7_retained"], grid["2026-04-13"]["on_or_after_day7_retained"]) == ("25", "7", "16")
    assert "7 of 25" in sqla and "16 of 25" in sqla


def test_designed_relationships_and_defects_are_present_in_the_results():
    sig = RES["reconciliation"]
    by = {r["check"]: r for r in sig}
    inj = [r for r in sig if "INJ-" in r["check"]]
    assert {re.search(r"INJ-\d+", r["check"]).group(0) for r in inj} >= {"INJ-04", "INJ-05", "INJ-06", "INJ-07", "INJ-08", "INJ-10", "INJ-12"}
    assert all(r["equal"] for r in inj)
    for dr in ("DR-01", "DR-02", "DR-03", "DR-04", "DR-05", "DR-06", "DR-07"):
        assert any(f"E {dr}" in r["check"] for r in sig), dr
    # the designed relationships: business activates sooner, the treatment does not lift week 4, the guardrail is equal, v1 passes the sample ratio and v2 does not
    ts = {r["plan"]: r for r in RES["01_activation_by_plan_and_segment__time_to_activation_by_plan"]}
    assert Decimal(ts["business"]["median_hours_to_activate"]) < Decimal(ts["free"]["median_hours_to_activate"]) and Decimal(ts["business"]["activation_rate"]) > Decimal(ts["free"]["activation_rate"])
    assert RES["07_guardrail_and_revenue_per_arm__week4_by_arm"][0]["interval_includes_zero"] == "true"
    assert row_of("07_guardrail_and_revenue_per_arm__guardrail_by_cutoff", run="an-004")["interval_includes_zero"] == "true"
    assert row_of("07_guardrail_and_revenue_per_arm__revenue_difference", run="an-004")["interval_includes_zero"] == "true"
    srm = {(r["experiment_version"], r["run"]): r["verdict"] for r in RES["06_experiment_v2_sample_ratio__srm_by_read"]}
    assert srm[("xv-001", "an-004")] == "OK" and srm[("xv-002", "an-005")] == "MISMATCH" and all(v == "OK" for (xv, _), v in srm.items() if xv == "xv-001")
    # interim runs never conclusive; the final one is, by a hair; the gap accounts are the manifest's 11
    lift = {r["run"]: r for r in RES["05_experiment_v1_at_each_run_cutoff__lift_by_cutoff"]}
    assert [lift[r]["conclusive"] for r in ("an-001", "an-002", "an-003", "an-004")] == ["false", "false", "false", "true"] and all(lift[r]["interim"] == "true" for r in ("an-001", "an-002", "an-003"))
    ga = RES["05_experiment_v1_at_each_run_cutoff__gap_accounts"]
    assert sum(int(r["gap_accounts"]) for r in ga) == 11 and all(r["gap_published_activations"] == "0" for r in ga)
    # a late event never moved v1's activation at any run (no revision to disclose)
    assert {r["activations_changed_by_late_events"] for r in RES["08_identity_attribution_and_late_events__late_activations_by_run"]} == {"0"}
    # the late batch of INJ-06 and the identity link that never applies backward
    lb = {r["reading"]: r for r in RES["03_funnel_steps_and_exclusions__late_batch_effect"]}
    assert (lb["late batch (hindsight - known)"]["onboarding_step_1"], lb["late batch (hindsight - known)"]["activated"]) == ("9", "4")
    attr = [r for r in RES["08_identity_attribution_and_late_events__attribution_by_event"] if r["event_name"] == "ALL"][0]
    assert (attr["attributed_by_link"], attr["before_the_link_stays_anonymous"], attr["remain_anonymous"]) == ("124", "1507", "5264")
    assert by  # the reconciliation is indexed by its check text


@pytest.mark.skipif(not os.environ.get("ARTIFACTS_DATABASE_URL"),
                    reason="ARTIFACTS_DATABASE_URL (a scratch database named artifacts06_* prepared by data/sql/analysis/prepare_snapshot.py) is not set")
def test_sql_files_rerun_against_the_prepared_database_give_the_stored_rows(ps, ra):
    import psycopg
    from psycopg.rows import dict_row
    url = os.environ["ARTIFACTS_DATABASE_URL"]
    assert url.rsplit("/", 1)[-1].startswith("artifacts06_")
    with psycopg.connect(url, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
        ra.run_script(c, SQL_DIR / "00_canonical_events.sql")
        for f in sorted(SQL_DIR.glob("0[1-8]_*.sql")):
            for key, rows in ra.run_file(c, f).items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key
    if os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL"):
        gurl = os.environ["ARTIFACTS_GOLDEN_DATABASE_URL"]
        assert gurl.rsplit("/", 1)[-1].startswith("artifacts06_")
        with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as c:
            for key, rows in ra.run_file(c, SQL_DIR / "09_golden_known_answer.sql").items():
                assert [{k: ps.norm(v) for k, v in r.items()} for r in rows] == RES[key], key


def test_a_database_rerun_without_the_scratch_url_is_skipped_with_a_reason():
    marks = [m for m in test_sql_files_rerun_against_the_prepared_database_give_the_stored_rows.pytestmark if m.name == "skipif"]
    assert marks and "ARTIFACTS_DATABASE_URL" in marks[0].kwargs["reason"] and "artifacts06_" in marks[0].kwargs["reason"]


def test_scratch_guard_refuses_a_non_scratch_database():
    prep = _load("ps_prepare", SQL_DIR / "prepare_snapshot.py")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/productsignal")
    with pytest.raises(SystemExit):
        prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts05_snapshot")
    prep.assert_scratch("postgresql://u:p@127.0.0.1:5432/artifacts06_snapshot")
    with pytest.raises(SystemExit):
        prep.create_database("postgresql://u:p@127.0.0.1:5432/postgres", "productsignal")


def test_every_sql_file_has_its_header_and_the_numbered_files_read_only():
    files = sorted(SQL_DIR.glob("0*.sql"))
    assert [f.name[:2] for f in files] == ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09"]
    for f in files:
        text = f.read_text()
        assert text.startswith(f"-- {f.name[:-4]}.sql:") or text.startswith(f"-- {f.name}:"), f.name
        assert "P06-" in text and ("D-0" in text or "D-1" in text or "D-05" in text), f.name
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b", body, re.I) or f.name == "00_canonical_events.sql", f.name       # read-only (00 only creates temporary tables)
        if f.name != "00_canonical_events.sql":
            assert "CREATE" not in body, f.name
        assert not re.search(r"make_interval\(days", body), f.name                         # hour-based intervals only (R6-03)
    book = (SQL_DIR / "00_canonical_events.sql").read_text()
    assert len(re.findall(r"CREATE TEMP TABLE", book)) == 3 and "CREATE TABLE" not in book.replace("CREATE TEMP TABLE", "")
    for f in sorted(SQL_DIR.glob("bi_*.sql")):
        assert "BI package" in f.read_text(), f.name
    assert not re.search(r"(?i)\b(insert|update|delete|drop|alter)\b", "\n".join(l for l in "\n".join(f.read_text() for f in SQL_DIR.glob("bi_*.sql")).splitlines() if not l.strip().startswith("--")))


def test_the_canonical_events_repeat_the_reference_sql_text():
    """00_canonical_events.sql repeats the canonical-event common table expressions of data/sql/reference_metrics.sql (the cutoff is a column instead of a parameter)."""
    ref = (ROOT / "data/sql/reference_metrics.sql").read_text()
    book = (SQL_DIR / "00_canonical_events.sql").read_text()
    for frag in ("SELECT DISTINCT ON (anonymous_id) anonymous_id, user_id, linked_at FROM identity_links",
                 "ORDER BY anonymous_id, linked_at, identity_link_id",
                 "SELECT DISTINCT ON (user_id) user_id, anonymous_id FROM identity_links ORDER BY user_id, linked_at, identity_link_id",
                 "coalesce((SELECT jsonb_object_agg(ep.property_key, ep.property_value) FROM event_properties ep",
                 "WHEN fl.linked_at <=", "THEN fl.user_id END AS u",
                 "(r.user_id IS NULL AND r.anonymous_id IS NULL) OR (r.u IS NOT NULL AND u2.user_id IS NULL) THEN 'unknown'",
                 "WHEN r.u IS NOT NULL AND u2.bot_flag THEN 'bot'", "WHEN r.u IS NOT NULL AND a2.internal THEN 'internal'",
                 "coalesce(c.anonymous_id, (SELECT anonymous_id FROM anon_of_user WHERE user_id = c.user_id), 'user:' || c.user_id) AS vk"):
        assert frag in ref and frag in book, frag
    assert "%(cutoff)s" not in book and "PARTITION BY c, actor, event_name, event_at, props ORDER BY received_at, event_id" in book
    assert "ORDER BY received_at, event_id" in ref


# ---- the workbook --------------------------------------------------------------------------------------------------------------------------

def _metrics_values(path: Path, bw) -> dict[tuple[str, str], object]:
    ws = openpyxl.load_workbook(path, data_only=True)["Metrics"]
    return {(ws.cell(row=6 + i, column=1).value, s): ws.cell(row=6 + i, column=4 + k).value for i in range(len(bw.METRICS)) for k, s in enumerate(bw.SCOPES)}


def _assert_metrics_equal(got: dict, domain_ref: dict, run: str, bw) -> None:
    tol = {m[0]: bw.TOL[m[3]] for m in bw.METRICS}
    for scope in bw.SCOPES:
        for mid, want in domain_ref[(run, scope)].items():
            g = got[(mid, scope)]
            if isinstance(want, bool):
                assert g is want, (run, mid, scope, g, want)
            elif isinstance(want, str):
                assert g == want, (run, mid, scope, g, want)
            elif want is None:
                assert g in (None, ""), (run, mid, scope, g)
            else:
                assert isinstance(g, (int, float)) and not isinstance(g, bool), (run, mid, scope, g)
                assert abs(float(g) - want) <= tol[mid] + 1e-9, (run, mid, scope, g, want)
    for (mid, scope), g in got.items():
        if mid not in domain_ref[(run, scope)]:
            assert g in (None, ""), (run, mid, scope, g)        # nothing is shown that the domain does not publish


def test_workbook_sheets_present_and_assumptions_listed(wb):
    assert wb.sheetnames == ["Read me", "Cutoff", "Metrics", "Domain reference", "Golden case", "Plan x segment", "Assumptions", "Assignments", "Subscriptions", "Accounts", "Runs", "Plans",
                             "SQL results (pasted)"]
    text = " ".join(str(c.value) for row in wb["Assumptions"].iter_rows() for c in row if c.value)
    for d in ("D-01", "D-02", "D-03", "D-05", "D-07", "D-08", "D-10", "W-01", "W-02", "W-03", "W-04", "W-05"):
        assert d in text
    assert "SYNTHETIC" in wb["Read me"]["A2"].value and "PASTED VALUES" in wb["SQL results (pasted)"]["A1"].value and "PASTED VALUES" in wb["Domain reference"]["A1"].value
    assert wb["Cutoff"]["B3"].value == "an-004"
    assert any("an-001,an-002,an-003,an-004,an-005" in str(dv.formula1) for dv in wb["Cutoff"].data_validations.dataValidation)
    readme = " ".join(str(c.value) for row in wb["Read me"].iter_rows() for c in row if c.value)
    assert DATASET_HASH in readme and CODE_REVISION in readme and "Excel was NOT run" in readme and "withheld" in readme and "conclusive by a hair" in readme and "+0.000812" in readme
    assert "published +9.50, drawn +11.50, +9.96 excluding" in readme and "four generator choices" in readme.lower().replace("four generator choices were", "four generator choices")


def test_data_sheets_equal_the_snapshot_and_the_independent_side(wb, ctx, ps):
    counts = {"Assignments": 554, "Subscriptions": 207, "Accounts": 600, "Runs": None}
    assert wb["Assignments"].max_row - 1 == counts["Assignments"] and wb["Subscriptions"].max_row - 1 == 207 and wb["Accounts"].max_row - 1 == 600
    asg = {a["assignment_id"]: a for v in ctx.asg.values() for a in v}
    exp = ctx.exposure
    acts = {e.acct: e for e in ctx.log["as-of"] if e.cls == "analysed" and e.name == "activated" and e.acct}
    epoch = lambda s: int(ps.ts(s).timestamp()) if isinstance(s, str) else int(s.timestamp())      # noqa: E731
    for row in wb["Assignments"].iter_rows(min_row=2, max_col=11, values_only=True):
        a = asg[row[0]]
        assert (row[1], row[2], row[3], row[4]) == (a["experiment_version_id"], a["unit_id"], a["variant"], epoch(a["assigned_at"])), row[0]
        s = ctx.signup["as-of"].get(a["unit_id"])
        assert row[5] == (1e15 if s is None else epoch(s)), row[0]
        assert row[9] == (1e15 if row[0] not in exp else epoch(exp[row[0]])), row[0]
        assert row[7] == (1e15 if a["unit_id"] not in acts else epoch(acts[a["unit_id"]].at)), row[0]
    typed = {r[0]: r for r in wb["Subscriptions"].iter_rows(min_row=2, max_col=4, values_only=True)}
    for s in ctx.rows["subscriptions"]:
        assert typed[s["account_id"]][3] is not None
    assert abs(sum(r[3] for r in wb["Subscriptions"].iter_rows(min_row=2, max_col=4, values_only=True)) - sum(float(s["amount_usd"]) for s in ctx.rows["subscriptions"])) < 1e-6
    assert [r[0] for r in wb["Runs"].iter_rows(min_row=5, max_row=9, max_col=1, values_only=True)] == list(RUNS)
    assert [r[0] for r in wb["Plans"].iter_rows(min_row=5, max_row=6, max_col=1, values_only=True)] == ["xv-001", "xv-002"]


def test_result_cells_of_the_formula_sheets_are_live_formulas_without_hardcoded_figures(wb, bw):
    assert [m[0] for m in bw.METRICS][:3] == ["assigned_accounts", "mature_accounts", "immature_or_unobserved"] and len(bw.METRICS) == 39
    m = wb["Metrics"]
    for i, (mid, _label, _unit, _kind, scopes, _outcome, _def) in enumerate(bw.METRICS):
        r = 6 + i
        for k, scope in enumerate(bw.SCOPES):
            applicable = ("c" in scopes and scope == "control") or ("t" in scopes and scope == "treatment") or ("+" in scopes and scope == "combined")
            v = m.cell(row=r, column=4 + k).value
            assert (isinstance(v, str) and v.startswith("=")) if applicable else v is None, (mid, scope, v)           # no typed figure on Metrics
        assert str(m.cell(row=r, column=9).value).startswith("=AND("), r
    a = wb["Assignments"]
    for col in range(12, 20):
        for row in (2, 300, 555):
            assert str(a.cell(row=row, column=col).value).startswith("="), (col, row)
    for row in (2, 208):
        assert str(wb["Subscriptions"].cell(row=row, column=5).value).startswith("=")
    for row in (2, 601):
        assert str(wb["Accounts"].cell(row=row, column=8).value).startswith("=") and str(wb["Accounts"].cell(row=row, column=9).value).startswith("=")
    g = wb["Golden case"]
    for r in range(16, 29):
        assert str(g.cell(row=r, column=2).value).startswith("="), r
    assert (g["B4"].value, g["B5"].value, g["B6"].value, g["B7"].value) == (100, 20, 100, 30)                   # the typed inputs of the known answer
    c = wb["Cutoff"]
    assert str(c["B10"].value).startswith("=INDEX(") and str(c["B11"].value).startswith("=MATCH(")
    total = sum(1 for ws in wb.worksheets for row in ws.iter_rows() for cell in row if isinstance(cell.value, str) and cell.value.startswith("="))
    assert total > 5_000
    withheld = str(m["D14"].value)
    assert "withheld" in withheld and "$B$4" in withheld                                                          # the sample ratio comes first


def test_cached_values_equal_the_domain_recomputed_here(wbv, bw, domain_ref):
    got = _metrics_values(XLSX, bw)
    _assert_metrics_equal(got, domain_ref, "an-004", bw)
    ws = wbv["Metrics"]
    assert ws["B3"].value == "an-004" and ws["E3"].value is True and ws["B4"].value is False
    assert all(ws.cell(row=r, column=9).value is True for r in range(6, 6 + len(bw.METRICS)))
    assert wbv["Golden case"]["B30"].value is True and all(wbv["Golden case"].cell(row=r, column=4).value is True for r in range(16, 29))
    # the pasted column is the domain's too (a boolean pasted as a constant is stored by LibreOffice as =TRUE() / =FALSE())
    dr = wbv["Domain reference"]
    labels = [c.value for c in dr[4]][1:]
    for r in range(5, 5 + len(bw.METRICS)):
        mid = dr.cell(row=r, column=1).value
        for c, label in enumerate(labels, start=2):
            run, scope = label.split("|")
            v = dr.cell(row=r, column=c).value
            want = domain_ref[(run, scope)].get(mid)
            if isinstance(want, (bool, str)) or want is None:
                assert v == want, (mid, label, v, want)
            else:
                assert abs(v - want) < 1e-9, (mid, label)
    # plan x segment, live over Accounts, equals the stored SQL result of investigation 01
    pxs = wbv["Plan x segment"]
    sql = {(r["plan"], r["segment"]): r for r in RES["01_activation_by_plan_and_segment__plan_segment"]}
    for r in range(5, 5 + 16):
        p, s = pxs.cell(row=r, column=1).value, pxs.cell(row=r, column=2).value
        want = sql[(p, s)]
        assert [pxs.cell(row=r, column=c).value for c in (3, 4, 5, 6)] == [int(want["accounts"]), int(want["signed_up"]), int(want["mature"]), int(want["activated"])], (p, s)
        rate = pxs.cell(row=r, column=7).value
        assert (rate in (None, "") and want["activation_rate"] == "") or abs(rate - float(want["activation_rate"])) < 5e-7, (p, s)


def test_full_calc_on_load_is_set_in_workbook_xml():
    import zipfile
    assert 'fullCalcOnLoad="1"' in zipfile.ZipFile(XLSX).read("xl/workbook.xml").decode()


needs_lo = pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice (soffice) is not installed")


def _lo_recalc(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(exist_ok=True)
    subprocess.run(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{out_dir}/profile",
                    "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out_dir / "out"), str(src)],
                   check=True, capture_output=True, timeout=1800)
    return out_dir / "out" / src.name


@needs_lo
def test_libreoffice_headless_recalculation_of_a_copy_as_delivered(tmp_path, bw, domain_ref):
    src = tmp_path / "copy.xlsx"
    shutil.copy(XLSX, src)
    res = _lo_recalc(src, tmp_path / "a")
    _assert_metrics_equal(_metrics_values(res, bw), domain_ref, "an-004", bw)
    assert openpyxl.load_workbook(res, data_only=True)["Metrics"]["E3"].value is True


@needs_lo
@pytest.mark.parametrize("run", ["an-001", "an-002", "an-003", "an-005"])
def test_the_cutoff_switch_is_live_and_equals_the_domain_for_that_run(tmp_path, bw, domain_ref, run):
    flip = openpyxl.load_workbook(XLSX)                         # formulas only: openpyxl drops the cached values on save
    flip["Cutoff"]["B3"] = run
    src = tmp_path / f"{run}.xlsx"
    flip.save(src)
    assert _metrics_values(src, bw)[("assigned_accounts", "control")] is None   # no cached values until recalculated
    res = _lo_recalc(src, tmp_path / run)
    got = _metrics_values(res, bw)
    _assert_metrics_equal(got, domain_ref, run, bw)
    v = openpyxl.load_workbook(res, data_only=True)
    assert v["Metrics"]["E3"].value is True and v["Metrics"]["B3"].value == run
    assert got[("assigned_accounts", "combined")] == {"an-001": 155, "an-002": 253, "an-003": 353, "an-005": 154}[run]
    if run == "an-005":
        assert v["Metrics"]["B4"].value is True and got[("srm_verdict", "combined")] == "MISMATCH" and got[("absolute_lift_pp", "combined")] == "withheld"
        assert abs(got[("srm_statistic", "combined")] - 25.004329) < 5e-7
    else:
        assert v["Metrics"]["B4"].value is False and got[("conclusive", "combined")] is False and got[("interim", "combined")] is True


def test_pasted_sql_results_sheet_matches_the_stored_results(wb):
    ws = wb["SQL results (pasted)"]
    cells = {c.value for row in ws.iter_rows() for c in row if c.value is not None}
    meta = RES["meta"][0]
    assert (ws["B3"].value, ws["C3"].value) == (meta["reconciliation_rows"], meta["reconciliation_equal"])
    assert any(isinstance(c, str) and DATASET_HASH in c and CODE_REVISION in c for c in cells)
    lift = row_of("05_experiment_v1_at_each_run_cutoff__lift_by_cutoff", run="an-004")
    assert float(lift["absolute_lift_pp"]) in cells and float(lift["newcombe_low"]) in cells and float(lift["relative_lift"]) in cells
    assert "an-005" in cells and "MISMATCH" in cells
    assert not any(isinstance(c, str) and c.startswith("=") for c in cells)               # pasted values, not formulas


# ---- the BI package ------------------------------------------------------------------------------------------------------------------------

def _csv(name: str) -> list[dict]:
    with (ART / "bi" / f"{name}.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def test_bi_exports_have_the_documented_grain_and_equal_the_snapshot(ctx, ps):
    sizes = {"fact_run_assignment": 155 + 253 + 353 + 400 + 400 + 154 + 154, "fact_account": 600, "fact_tracking_week": 26, "dim_account": 600, "dim_date": 183, "dim_experiment_version": 2,
             "dim_run": 7, "dim_event_name": 8}
    for name, rows in sizes.items():
        assert len(_csv(name)) == rows, name
    runs = {}
    for r in _csv("fact_run_assignment"):
        runs.setdefault(r["run_key"], []).append(r)
    assert {k: len(v) for k, v in runs.items()} == {"an-001": 155, "an-002": 253, "an-003": 353, "an-004": 400, "an-005": 154, "asof-xv-001": 400, "asof-xv-002": 154}
    asg = {a["assignment_id"]: a for v in ctx.asg.values() for a in v}
    for r in _csv("fact_run_assignment"):
        a = asg[r["assignment_id"]]
        assert (r["account_id"], r["experiment_version_id"], r["arm"]) == (a["unit_id"], a["experiment_version_id"], a["variant"]), r["assignment_id"]
    for key, label in (("an-001", "an-001"), ("an-004", "an-004")):                               # the D-08 rule: every row of a read was assigned by its cutoff
        assert all(ps.ts(r["assigned_at"]) <= ctx.cuts[label] for r in runs[key])
    acc = {r["account_id"]: r for r in _csv("fact_account")}
    sg = ctx.signup["as-of"]
    for a in ctx.rows["accounts"]:
        r = acc[a["account_id"]]
        assert (r["is_internal"] == "1") == a["internal"] and (r["signup_at"] == "") == (a["account_id"] not in sg), a["account_id"]
        if a["account_id"] in sg:
            assert r["signup_at"] == ps.z(sg[a["account_id"]])
    assert [r["date_key"] for r in _csv("dim_date")][0] == "20260406" and [r["date_key"] for r in _csv("dim_date")][-1] == "20261005"
    assert [r["run_key"] for r in _csv("dim_run")] == ["an-001", "an-002", "an-003", "an-004", "asof-xv-001", "an-005", "asof-xv-002"]
    for name in sizes:
        text = (ART / "bi" / f"{name}.csv").read_text()
        assert "postgresql://" not in text and "lab:lab" not in text


def test_bi_measures_recomputed_from_the_csv_files_equal_the_stored_expected_values_and_the_domain(ctx, ra):
    meas = ra.bi_measures(_csv("fact_account"), _csv("fact_run_assignment"), _csv("fact_tracking_week"), _csv("dim_experiment_version"), _csv("dim_run"))
    assert meas == RES["bi_measures"]
    assert [{"measure": r["measure"], "slice": r["slice"], "value": r["value"]} for r in _csv("measures_recomputed")] == meas
    mv = {(m["measure"], m["slice"]): m["value"] for m in meas}
    assert mv[("absolute_lift_pp", "an-004")] == "9.50" and mv[("newcombe_low", "an-004")] == "0.000812" and mv[("relative_lift", "an-004")] == "0.301587"
    assert (mv[("assigned_accounts", "an-001")], mv[("assigned_accounts", "an-004")], mv[("srm_statistic", "an-005")], mv[("srm_verdict", "an-005")]) == ("155", "400", "25.004329", "MISMATCH")
    # the sample ratio comes first: no outcome of a MISMATCH read is emitted
    for key in ("an-005", "asof-xv-002"):
        assert not [m for m in meas if m["slice"].startswith(key) and m["measure"] in ("activated_accounts", "conversion_rate", "guardrail_error_rate", "revenue_per_assigned_account",
                                                                                         "absolute_lift_pp", "relative_lift", "newcombe_low", "newcombe_high")]
    assert sum(1 for r in RES["reconciliation"] if r["check"].startswith("E BI") and r["equal"]) >= 40


def test_bi_package_defines_every_measure_and_makes_no_pbix_claim():
    doc = read("bi-package.md")
    assert "No `.pbix` was produced" in doc and "pseudocode" in doc and "not executed" in doc and "Power BI Desktop is not available here and was not run" in doc
    for m in ("Selected Run", "Assigned Accounts", "Mature Accounts", "Activated Accounts", "Exposed Accounts", "SRM Statistic", "SRM P Value", "SRM Verdict", "Outcomes Shown", "Conversion Rate",
              "Exposure Rate", "Guardrail Error Rate", "Absolute Lift PP", "Relative Lift", "Newcombe Low", "Newcombe High", "Interval Includes Zero", "Conclusive", "Revenue Per Assigned Account",
              "Activation Rate All Signups", "Day 7 Retention", "On Or After Day 7 Retention", "Week 4 Retention", "Rows Total", "Duplicates Dropped", "Delayed Over 24h", "Delayed Share",
              "Unknown Identity", "Bot Events Excluded", "Internal Events Excluded", "Analysed Events"):
        assert f"{m} " in doc, m
    assert doc.count("DIVIDE") >= 8 and "SELECTEDVALUE" in doc and "BLANK" in doc and "withheld" in doc.lower().replace("withholding", "withheld")
    for name in ("fact_run_assignment", "fact_account", "fact_tracking_week", "dim_account", "dim_date", "dim_experiment_version", "dim_run", "dim_event_name", "measures_recomputed"):
        assert f"`{name}`" in doc and f"artifacts/bi/{name}.csv" in doc, name
    assert DATASET_HASH in doc and CODE_REVISION in doc and "conclusive by a hair" in doc and "+9.96" in doc and "+11.50" in doc
    assert not list(ROOT.rglob("*.pbix"))
    sizes = {"fact_run_assignment": 1869, "fact_account": 600, "fact_tracking_week": 26, "dim_account": 600, "dim_date": 183, "dim_experiment_version": 2, "dim_run": 7, "dim_event_name": 8,
             "measures_recomputed": len(RES["bi_measures"])}
    for name, rows in sizes.items():
        assert re.search(rf"\| `{name}` \|[^\n]*\| {rows:,} \|", doc), name


# ---- data dictionary, ERD, SQL analysis document -------------------------------------------------------------------------------------------------------------

def _tables_and_columns() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    text = (ROOT / "data/migrations/0001_schema.sql").read_text()
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", text, re.S):
        cols = []
        for line in m.group(2).splitlines():
            mm = re.match(r"\s*([a-z_0-9]+)\s+(TEXT\[\]|TEXT|INT|BOOLEAN|TIMESTAMPTZ|JSONB|NUMERIC\(\d+,\d+\))", line)
            if mm:
                cols.append(mm.group(1))
        out[m.group(1)] = cols
    return out


def test_data_dictionary_and_erd_cover_every_table_and_column_of_the_migrations():
    tables = _tables_and_columns()
    assert len(tables) == 23
    dd, erd = read("data-dictionary.md"), read("erd.md")
    assert "```mermaid" in erd and "erDiagram" in erd
    section2 = dd.split("## 2. Columns", 1)[1].split("\n## 3.", 1)[0]
    heads = {}
    for block in section2.split("\n### ")[1:]:
        title, body = block.split("\n", 1)
        for t in [x.strip() for x in title.split(",")]:
            heads[t] = body
    for t, cols in tables.items():
        assert f"`{t}`" in dd, t
        assert re.search(rf"^\s+{t} \{{", erd, re.M), t
        assert t in heads, t
        for c in cols:
            assert f"`{c}`" in heads[t], (t, c)
            assert re.search(rf"^\s+[\w()\[\]]+ {c}\b", erd, re.M), (t, c)
    for key in ("grain", "Deletion policy", "Append-only events and versioned plans", "append-only", "rejected_records", "Source-to-target", "Foreign keys", "analysis_plans", "config_hash",
                "assignments_unit_uq", "exposures_not_early", "cutoff", "synthetic", "account"):
        assert key.lower() in dd.lower(), key
    counts = {"accounts": "600", "users": "1,824", "identity_links": "1,264", "sessions": "3,420", "events": "12,552", "event_properties": "2,561", "subscriptions": "207", "experiment_versions": "2",
              "analysis_plans": "2", "assignments": "554", "exposures": "484", "metric_observations": "544", "analysis_runs": "5", "funnel_definitions": "1", "decisions": "0", "rejected_records": "0"}
    for k, v in counts.items():
        assert re.search(rf"\| `{k}` \|[^\n]*\| {v} \|", dd), k
    assert DATASET_HASH in dd and CODE_REVISION in dd and DATASET_HASH in erd and "INJ-10" in dd


def test_sql_analysis_doc_quotes_the_stored_results_and_every_table_is_rendered_from_them(ps):
    render = _load("ps_render", ART / "render_sql_analysis.py")
    for name in ("sql-analysis.md", "bi-package.md"):
        text = read(name)
        assert render.render(text, RES) == text, f"{name} drifted from artifacts/analysis-results.json: run artifacts/render_sql_analysis.py"
        assert "(to be rendered)" not in text
    doc = read("sql-analysis.md")
    for key in ps.KEYS:
        assert f"<!-- BEGIN:{key} -->" in doc, key
    for key in ("09_golden_known_answer__golden_arms", "09_golden_known_answer__golden_lift", "09_golden_known_answer__golden_retention"):
        assert f"<!-- BEGIN:{key} -->" in doc, key
    assert "<!-- BEGIN:reconciliation -->" in doc and DATASET_HASH in doc and CODE_REVISION in doc
    for sentence in ("conclusive by a hair", "+0.000812", "published +9.50", "drawn +11.50", "+9.96 excluding the 11 gap accounts", "constructed", "observed", "hypothetical", "four choices",
                     "Excel and Power BI were not run", "Segments are exploratory", "D-08", "Five of the twelve injected defects live only in replay events"):
        assert sentence in doc, sentence
    for v in ("214 of 571 mature accounts activated (0.374781)", "76 signups, 17 immature, 59 mature, 21 activated (0.355932)", "107 of 571 mature accounts (0.187391)", "154 visitors, 51 signed up (0.331169)",
              "12,552 rows received, 124 are re-sent duplicates", "237 delayed over 24 hours (0.019070)", "155 accounts assigned by then (77 control, 78 treatment)", "5 control and 6 treatment accounts",
              "chi-square 25.004329", "MISMATCH", "-0.50 points, interval -0.076005 to +0.066018", "USD 33.12 has a Welch interval of -25.59 to +91.83 (df 391)",
              "-4.50 points, Newcombe interval -0.136053 to +0.047102", "124 are attributed by a link", "a difference of 0 in every row", "20 of 100 control and 30 of 100 treatment"):
        assert v in doc, v
    assert f"{RES['meta'][0]['reconciliation_rows']}" in read("requirements.md") and "equal" in doc


def test_the_documents_name_the_real_entities_metrics_and_commands_and_keep_result_kinds_apart():
    case = read("business-case.md")
    for token in ("Should an onboarding change ship, stop, or receive more investigation", "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "validate-tracking", "resolve-identity",
                  "define-funnel", "assign-experiment", "record-exposure", "freeze-analysis-plan", "check-maturity", "analyze-experiment", "review-guardrails", "record-decision",
                  "events", "assignments", "analysis_plans", "analysis_runs", "guardrail_reviews", "decisions", "identity_links", "audit_events", "P06-MET-", "P06-FLOW-", "P06-TEST-", "P06-DOMAIN-",
                  "OBSERVED", "observed", "constructed", "hypothetical", "Decision criteria", "Current-state", "Future", "Simulated stakeholders", DATASET_HASH, CODE_REVISION,
                  "conclusive by a hair", "+0.000812", "published +9.50", "drawn +11.50", "+9.96", "25.004329", "intention to treat", "The sample ratio comes first", "D-08", "D-10",
                  "writes no product state", "Mode A and Mode B"):
        assert token in case, token
    assert "four generator choices" in case.lower()
    assert "Excel" in case and "Power BI" in case


def test_requirements_trace_every_requirement_family():
    req = read("requirements.md")
    for fam in ("P06-GOAL", "P06-DOMAIN-01", "P06-DOMAIN-06", "P06-GOLD-01", "P06-DATA-01..12", "P06-MET-01", "P06-MET-12", "P06-FLOW-01", "P06-FLOW-10", "P06-UI-01", "P06-UI-10",
                "P06-TEST-01", "P06-TEST-12", "P06-ART", "P06-REL"):
        assert fam in req, fam
    assert "Functional requirements" in req and "Non-functional requirements" in req and "User stories" in req and "Traceability" in req
    for run in ("40426536267", "40435203915", "40426869172", "40435315836"):
        assert run in req, run
    tests_text = all_test_names()
    named = set(re.findall(r"`(test_[a-zA-Z0-9_]+)`", req))
    assert len(named) > 60
    for doc in ("requirements.md", "technical-case-study.md", "uat-evidence.md", "executive-memo.md", "release-package.md"):
        for t in set(re.findall(r"`(test_[a-zA-Z0-9_]+)`", read(doc))):
            assert f"def {t}(" in tests_text, f"{doc} cites a test that does not exist: {t}"
    spec = (ROOT / "web/e2e/journey.spec.ts").read_text()
    for title in re.findall(r'`"([^"`]+)"`|\(`web/e2e/journey.spec.ts`\)', req):
        if title:
            assert title in spec, title
    for title in ("every route is reachable by direct entry and reload on the nested base path, with the honesty labels", "result under ?dataset=golden: the golden case, sample ratio before the lift",
                  "decision: evidence, the inconclusive option, blocked options, the simulation is labelled and in memory"):
        assert f'"{title}"' in req and title in spec
    assert DATASET_HASH in req and CODE_REVISION in req and "deferred" in req and "not_checked" in req and "pending" in req
    assert "INJ-10" in req and "conclusive by a hair" in req and "Welch" in req


def test_executive_memo_quotes_the_evidence_options_and_the_caveats():
    memo = read("executive-memo.md")
    for token in ("OBSERVED", "SIMULATED", "HYPOTHETICAL", "## Decision", "| Option |", "## Evidence", "## Uncertainty", "## Limitations", "## Recommendation", "conclusive by a hair", "+0.000812 to +0.186863",
                  "+9.50", "+11.50", "+9.96", "+0.35 to +19.32", "25.004329", "MISMATCH", "inconclusive", "ship", "stop", "223 / 177", "Four choices were made after looking at earlier drafts",
                  "Excel and Power BI were not run", "does not support any statement about a realised benefit", "-0.004952", "-0.136053 to +0.047102", "-25.59 to +91.83", "0.697121", DATASET_HASH, CODE_REVISION,
                  "staged", "positive, size uncertain"):
        assert token in memo, token
    assert not re.search(r"\b(saves?|saved|savings of|roi)\b", memo, re.I)


def test_uat_evidence_keeps_the_original_and_adds_routes_screenshots_scenarios_and_run_links():
    uat = read("uat-evidence.md")
    if shutil.which("git"):
        orig = subprocess.run(["git", "-C", str(ROOT), "show", f"{CODE_REVISION}:apps/productsignal/docs/uat-evidence.md"], capture_output=True, text=True)
        if orig.returncode == 0:
            assert uat.startswith(orig.stdout), f"uat-evidence.md is append-only: the text of revision {CODE_REVISION} must be unchanged"
    assert "R6-01" in uat and "Entry-journey evidence (P06-ART-08" in uat
    for url in ("https://github.com/mrrishit909/projects-site/actions/runs/40426536267", "https://github.com/mrrishit909/projects-site/actions/runs/40426869172"):
        assert url in uat
    for token in ("d7111f1", "fdf911a", "e360bf1", "pending", "40435203915", "40435315836", "own CI and live-check runs", "npm run e2e", "did **not** run `npm run e2e`", "not fetched"):
        assert token in uat, token
    for route in ("`/`", "`/overview/`", "`/funnel/`", "`/cohorts/`", "`/tracking/`", "`/experiments/`", "`/result/`", "`/population/`", "`/segments/`", "`/decision/`", "`/evidence/`", "`/case-study/`"):
        assert route in uat, route
    for shot in ("home", "overview", "funnel", "cohorts", "tracking", "experiments", "result", "result-golden", "population", "segments", "decision", "evidence", "case-study"):
        assert f"`{shot}`" in uat, shot
    assert "-zoom200.png" in uat and "65 files" in uat
    for s in range(1, 11):
        assert f"| S{s} |" in uat, s
    for token in ("Expected answer", "Actual observation", "Disposition", "Defect disposition", "+0.000812", "25.004329", "+9.96", "+11.50", "155 accounts", "conclusive by a hair"):
        assert token in uat, token
    shots_dir = ROOT / "web" / "evidence"
    if (shots_dir / "index.json").exists():
        idx = json.loads((shots_dir / "index.json").read_text())
        assert idx["count"] == 65 and all(s["scrollWidth"] <= s["innerWidth"] for s in idx["shots"])
        assert {s["file"].rsplit("-", 1)[0] for s in idx["shots"]} >= {"home", "overview", "result-golden", "case-study"}


def test_technical_case_study_and_release_package_cite_the_ledger_evidence():
    tcs, rel = read("technical-case-study.md"), read("release-package.md")
    for token in ("Architecture", "Trade-offs", "Recovery behaviour", "Reproducible setup", "Measured evidence", "Open gaps", "```mermaid", "D-08 cutoff rule", "Fact-time server stamping", "40426536267",
                  "40435203915", "40426869172", "40435315836", "d7111f1", "fdf911a", "e360bf1", "6e381bf", DATASET_HASH, "296 reconciliation rows", "conclusive by a hair", "Excel and Power BI Desktop were not run",
                  "no hosted run of `tests/test_artifacts.py` is recorded yet"):
        assert token in tcs, token
    assert "four outcome-informed generator choices" in tcs.lower()
    for token in ("e360bf1", "6e381bf", "fdf911a", "40426536267", "40435203915", "40426869172", "40435315836", "pending", "Rollback procedure", "git revert", "Artifacts and checksums", DATASET_HASH,
                  "ef39beb5a4a6f7c0799ad304322339489252904022840cd963249344b48d33d3", "release-manifest", "committed and pushed nothing", "Main-portfolio metadata", "Excel", "Power BI",
                  "conclusive by a hair", "+9.96", "47c19d1", "b99a4e9", "5f07cac", "not fetch"):
        assert token in rel, token
    assert "lab:lab" not in rel
    if shutil.which("git"):
        for c in ("e360bf1", "6e381bf", "d7111f1", "fdf911a", "b99a4e9", "5f07cac"):
            probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", c], capture_output=True, text=True)
            if probe.returncode != 0:
                pytest.skip(f"commit {c} is not in this checkout")
        for c, subj in (("e360bf1", "republish after the reviewer fixes"), ("6e381bf", "publish the site under labs/productsignal"), ("b99a4e9", "disclose the injected instrumentation gap")):
            assert subj in subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%s", c], capture_output=True, text=True).stdout


def test_resume_bullets_are_four_to_six_and_claim_no_business_impact_and_match_the_public_case_study():
    text = read("resume-bullets.md")
    bullets = [l for l in text.splitlines() if l.startswith("* ")]
    assert 4 <= len(bullets) <= 6
    body = " ".join(bullets)
    assert not re.search(r"\b(saved|savings|reduced (?:cost|time)|increased revenue|users|customers? adopted|adoption of|roi)\b", body, re.I)
    for token in ("D-01..D-10", "706-check", "357 Python tests", "R6-01..R6-14", "296 reconciliation rows", "LibreOffice", "no `.pbix`", "+0.000812", "+11.50", "+9.96", "2,519", "36 review checks", "77 Playwright"):
        assert token in body, token
    assert "synthetic" in text.lower() and "no bullet claims business impact" in text
    if PROJECT:
        tech = " ".join(PROJECT["tech"])
        assert "357 Python tests" in tech and "2,519 TypeScript golden" in tech and "36 review checks" in tech and "77 browser tests" in tech


def test_public_case_study_figures_agree_with_the_stored_results():
    if PROJECT is None:
        pytest.skip("the public case study /productsignal/project.json is not in this checkout (it lives on unified-portfolio)")
    text = re.sub(r"<[^>]+>", " ", PROJECT["results"] + PROJECT["built"] + PROJECT["tagline"]).replace("−", "-")
    lift = row_of("05_experiment_v1_at_each_run_cutoff__lift_by_cutoff", run="an-004")
    arms = {r["arm"]: r for r in RES["05_experiment_v1_at_each_run_cutoff__arms_by_cutoff"] if r["run"] == "an-004"}
    assert f"{arms['control']['activated']} of {arms['control']['mature']} control and {arms['treatment']['activated']} of {arms['treatment']['mature']} treatment" in text
    assert "+9.50 points (relative 0.301587)" in text and "+0.08 to +18.69 points" in text and lift["relative_lift"] == "0.301587"
    assert "conclusive by a hair" in text and "+11.50 points" in text and "+2.02 to +20.69" in text and "+9.96" in text
    assert "71 of 200 against 62 of 200 (-4.50 points)" in text and "31 against 30 of 200" in text and "97.83 against 130.95" in text
    assert "155 accounts had been assigned (77 and 78)" in text and "25.004329" in text and "below 0.000001" in text
    tq = [r for r in RES["04_tracking_quality_by_week__by_week"] if r["week_start"] == "ALL"][0]
    assert f"{tq['duplicates_dropped']} duplicate events dropped" in text and f"{tq['delayed_over_24h']} delayed" in text and f"{tq['unknown_identity']} with an unknown identity" in text and "69.7%" in text
    assert "20 of 100 control accounts and 30 of 100 treatment accounts" in PROJECT["tagline"]
    assert PROJECT["repo"].endswith("apps/productsignal") and PROJECT["date"] == "2026-10"


def test_no_credentials_or_secrets_in_the_artifact_documents_and_files():
    docs = ["business-case.md", "requirements.md", "data-dictionary.md", "erd.md", "sql-analysis.md", "workbook.md", "bi-package.md", "executive-memo.md", "technical-case-study.md",
            "release-package.md", "resume-bullets.md", "uat-evidence.md"]
    for d in docs:
        text = read(d)
        if d == "uat-evidence.md":
            text = text.split("# Entry-journey evidence", 1)[1]          # the original review evidence is append-only
        assert "lab:lab" not in text, d
        assert not re.search(r"postgres(ql)?://[^<\s]*:[^<\s@]+@", text), d
        assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*\S{12,}", text), d
    for p in list(ART.glob("*.json")) + list((ART / "bi").glob("*.csv")) + [ART / "CHECKSUMS.txt"] + list(SQL_DIR.glob("*.sql")):
        assert "postgresql://" not in p.read_text(), p.name
        assert "lab:lab" not in p.read_text(), p.name
    wbtext = " ".join(str(c.value) for ws in openpyxl.load_workbook(XLSX).worksheets[:7] for row in ws.iter_rows() for c in row if c.value)
    assert "postgresql://" not in wbtext and "password" not in wbtext.lower()


def test_workbook_doc_states_what_was_and_was_not_run():
    doc = read("workbook.md")
    assert "LibreOffice" in doc and "Excel itself was NOT run" in doc and "productsignal-analyst-workbook.xlsx" in doc and "openpyxl 3.1.5" in doc
    for sheet in ("Read me", "Cutoff", "Metrics", "Domain reference", "Golden case", "Plan x segment", "Assumptions", "Assignments", "Subscriptions", "Accounts", "Runs", "Plans", "SQL results (pasted)"):
        assert f"`{sheet}`" in doc, sheet
    assert "Cutoff!B3" in doc and "an-001" in doc and "an-005" in doc and "fullCalcOnLoad" in doc and "How to read it without installing" in doc and "withheld" in doc
    for v in ("+9.50", "0.301587", "+0.000812", "0.186863", "97.83", "130.95", "33.12", "-25.59", "+91.83", "391", "-0.076005", "+0.066018", "25.004329", "+9.96", "+11.50", "conclusive by a hair"):
        assert v in doc, v
    assert (ROOT / "requirements-artifacts.txt").read_text().strip() == "openpyxl==3.1.5"


def test_provenance_the_analysed_code_and_data_equal_revision_fdf911a():
    """The numbers describe revision fdf911a: the domain, API, migrations, loaders, reference SQL, published data and fixtures are unchanged since
    (docs/contracts.md and the other documents are deliberately not part of the check: wording fixes there move no number)."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", CODE_REVISION], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"revision {CODE_REVISION} is not in this checkout")
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", CODE_REVISION, "--", "domain", "api", "data/migrations", "data/seed.py", "data/migrate.py", "data/generate.py",
                        "data/sql/reference_metrics.sql", "web/public", "tests/fixtures"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "", r.stdout
    manifest = json.loads((ROOT / "web/public/data/manifest.json").read_text())
    assert manifest["dataset_hash"] == DATASET_HASH and manifest["dataset_version"] == "ps-20261026-20261026"


# ---- checksums -----------------------------------------------------------------------------------------------------------------------------

def test_checksums_file_matches_files_and_the_release_package_table():
    path = ART / "CHECKSUMS.txt"
    if not path.exists():
        pytest.skip("CHECKSUMS.txt not written (artifacts/checksums.py)")
    listed = {}
    for line in path.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
        listed[rel] = digest
    chk = _load("ps_checksums", ART / "checksums.py")
    assert sorted(listed) == chk.files()                                  # every artifact and doc, nothing stale
    for must in ("artifacts/productsignal-analyst-workbook.xlsx", "artifacts/analysis-results.json", "artifacts/build_workbook.py", "artifacts/render_sql_analysis.py", "artifacts/checksums.py",
                 "requirements-artifacts.txt", "tests/test_artifacts.py", "docs/data-dictionary.md", "docs/erd.md", "docs/sql-analysis.md", "docs/workbook.md", "docs/bi-package.md",
                 "docs/executive-memo.md", "docs/technical-case-study.md", "docs/resume-bullets.md", "docs/business-case.md", "docs/requirements.md", "docs/uat-evidence.md",
                 "docs/contracts.md", "docs/api-contract.md", "docs/web-brief.md", "docs/data-generator.md", "data/sql/analysis/run_all.py", "data/sql/analysis/prepare_snapshot.py",
                 "data/sql/analysis/python_side.py", "artifacts/bi/fact_run_assignment.csv", "artifacts/bi/dim_date.csv", "artifacts/bi/measures_recomputed.csv"):
        assert must in listed, must
    for f in sorted(SQL_DIR.glob("0*.sql")) + sorted(SQL_DIR.glob("bi_*.sql")):
        assert f"data/sql/analysis/{f.name}" in listed
    assert "docs/release-package.md" not in listed and "artifacts/CHECKSUMS.txt" not in listed
    rel_doc = read("release-package.md")
    for rel, digest in listed.items():
        assert f"| `{rel}` | `{digest}` |" in rel_doc, rel               # release-package.md carries the same table (it cannot list itself)
