"""The golden fixture through the pure domain: every figure equals expected.json key by key (P06-GOLD-01..)."""
import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from productsignal import run_pipeline
from productsignal.contract import ENTITIES, METRIC_KEYS

from support_db import flat, golden_expected, golden_inputs


@pytest.fixture(scope="module")
def result():
    return run_pipeline(golden_inputs())


@pytest.mark.parametrize("key", METRIC_KEYS)
def test_metric_equals_expected(result, key):
    assert result.metrics[key] == golden_expected()["metrics"][key]


def test_metric_names_are_exactly_the_expected_keys(result):
    exp = golden_expected()["metrics"]
    assert list(result.metrics) == list(exp) == list(METRIC_KEYS)


def test_whole_golden_shape_equals_expected_json(result):
    assert result.golden() == golden_expected()


def test_every_leaf_of_expected_json_is_reproduced_and_nothing_else_is_emitted(result):
    fe, fg = flat(golden_expected()), flat(result.golden())
    assert set(fe) == set(fg)
    assert [k for k in fe if fe[k] != fg[k]] == []
    assert len(fe) == 205                       # the number of leaves of the golden expected.json


@pytest.mark.parametrize("entity", ENTITIES)
def test_ingest_counts_per_entity(result, entity):
    assert result.counts[entity] == golden_expected()["ingest"]["counts"][entity]


def test_tracking_quality_and_identity(result):
    exp = golden_expected()
    assert result.tracking_quality == exp["tracking_quality"] == {
        "rows_total": 529, "received_after_cutoff": 1, "duplicates_dropped": 1, "canonical": 527, "delayed_over_24h": 1,
        "unknown_identity": 1, "bot_events_excluded": 4, "internal_events_excluded": 3, "analysed": 519}
    assert result.identity == exp["identity"] == {"anonymous_events": 19, "attributed_by_link": 1, "remain_anonymous": 18}


def test_spec_sentence_figures(result):
    """P06-GOLD-01: 20/100 vs 30/100 -> absolute 10 pp, relative 50 %, interval includes 0, not conclusive; day-7 retention 5/20."""
    e = result.metrics["experiment"]
    v = e["primary"]["variants"]
    assert (v["control"]["activated"], v["control"]["mature_units"], v["control"]["conversion"]) == (20, 100, "0.200000")
    assert (v["treatment"]["activated"], v["treatment"]["mature_units"], v["treatment"]["conversion"]) == (30, 100, "0.300000")
    assert (e["primary"]["absolute_lift_pp"], e["primary"]["relative_lift"]) == ("10.00", "0.500000")
    assert e["primary"]["interval"]["includes_zero"] is True and e["primary"]["conclusive"] is False
    assert e["primary"]["interval"]["low"] == "-0.020249" and e["primary"]["interval"]["high"] == "0.216734"
    assert (v["control"]["wilson_95"], v["treatment"]["wilson_95"]) == (
        {"low": "0.133367", "high": "0.288829"}, {"low": "0.218949", "high": "0.395849"})
    r = result.metrics["retention"]["day7"]
    assert (r["retained"], r["mature_accounts"], r["rate"]) == (5, 20, "0.250000")
    assert result.metrics["retention"]["on_or_after_day7"]["rate"] == "0.600000"        # a different figure, never mixed in
    assert e["srm"]["verdict"] == "OK" and e["srm"]["statistic"] == "0.000000" and e["srm"]["p_value"] == "1.000000"


def test_itt_keeps_unexposed_units_and_exposed_only_is_labelled_exploratory(result):
    e = result.metrics["experiment"]
    assert e["exposure"]["overall"] == {"exposed": 180, "units": 200, "rate": "0.900000"}
    x = e["exploratory_exposed_only"]
    assert x["label"] == "exploratory" and x["decision_basis"] is False
    assert x["by_variant"]["control"]["conversion"] == x["by_variant"]["treatment"]["conversion"] == "0.222222"   # lift would vanish
    assert e["primary"]["absolute_lift_pp"] == "10.00"


def test_the_run_cites_the_plan_and_counts_prior_runs(result):
    run = result.metrics["experiment"]["run"]
    assert run["analysis_id"] == "an-002" and run["prior_runs"] == 1 and run["interim"] is False
    assert run["plan_frozen"] is True and run["config_hash_matches_plan"] is True
    early = run_pipeline(golden_inputs(), cutoff="2026-10-10T00:00:00Z").metrics["experiment"]
    assert early["run"]["analysis_id"] == "an-001" and early["run"]["interim"] is True and early["run"]["prior_runs"] == 0
    assert early["primary"]["conclusive"] is False


def test_domain_source_has_no_float():
    """No float anywhere in the domain package: no float() call, no float literal, no total_seconds() (a float)."""
    root = Path(__file__).resolve().parents[1] / "domain" / "productsignal"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), f"{path.name}:{node.lineno} float literal"
            assert not (isinstance(node, ast.Name) and node.id == "float"), f"{path.name}:{node.lineno} float"
            assert not (isinstance(node, ast.Attribute) and node.attr in ("total_seconds", "sqrt", "erfc", "erf")), f"{path.name}:{node.lineno} float math"
            assert not (isinstance(node, ast.ImportFrom) and node.module == "math"), f"{path.name}: imports math"


def test_subprocess_reference_check_is_independent_of_the_domain():
    """reference_check.py imports nothing from the application; it still agrees (also run as a script by the CI gate)."""
    p = Path(__file__).resolve().parent / "reference_check.py"
    out = subprocess.run([sys.executable, "-I", str(p)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and "ALL OK (706 checks)" in out.stdout
    assert sum(1 for l in out.stdout.splitlines() if l.startswith("OK hash.")) == 7


def test_expected_json_has_no_float_numbers():
    text = (Path(__file__).resolve().parent / "fixtures" / "golden" / "expected.json").read_text()
    json.loads(text, parse_float=lambda s: pytest.fail(f"float {s} in expected.json"))


def test_domain_equals_the_reference_computation_on_the_three_fixtures():
    """The reference's own compute() (stdlib, independent) and the domain agree on every leaf, not only on expected.json."""
    spec = importlib.util.spec_from_file_location("reference_check", Path(__file__).resolve().parent / "reference_check.py")
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    for sub in ("", "variant-rejected", "variant-empty"):
        data = golden_inputs(sub)
        assert flat(run_pipeline(data).golden()) == flat(ref.compute(data)), sub
