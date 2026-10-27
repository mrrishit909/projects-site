"""data/sql/reference_metrics.sql recomputes the metrics of a cutoff set from the facts, independently of the Python domain and of any
stored derived row, and equals expected.json on the fixtures and the domain on a synthetic world.

AVERAGE PRECISION and the POPULATION STABILITY INDEX are not recomputed in SQL (tied-threshold grouping and a 60-digit logarithm):
they stay Python-only, proven against expected.json and by hand in test_golden_domain.py and test_rules.py."""
from pathlib import Path

import pytest

from support_db import (FEB, JAN, SCIENTIST, VARIANTS, client, command, conn, db_url, flat, get, golden_expected, golden_inputs, load, metrics)  # noqa: F401
from worlds import READ_AS_OF, SETS, build_world, pipeline

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
SCENARIOS = {"": {JAN: "sc-001", FEB: None, "2025-03-01T00:00:00Z": None}, "variant-rejected": {JAN: "sc-1"}, "variant-empty": {JAN: None}}


def reference(conn, as_of, pa, run="tr-001", scenario=None, model="logistic_regression"):
    return conn.execute(SQL, {"as_of": as_of, "pa": pa, "run": run, "scenario": scenario, "model": model}).fetchone()


def expected_view(e):
    """The part of expected.json's cutoff set that the SQL reproduces, in the SQL's shape."""
    fm = e["feature_missingness"]
    out = {"population": e["population"], "churn_rate": e["churn_rate"], "late_events": e["late_events"],
           "precision_at_k": e["precision_at_k"], "recall_at_k": e["recall_at_k"], "risk_lift_at_k": e["risk_lift_at_k"],
           "brier_score": {"value": e["brier_score"]["value"], "n": e["brier_score"]["n"], "terms": e["brier_score"]["terms"]},
           "calibration_bins": [{k: b[k] for k in ("index", "lower", "upper", "closed_upper", "count", "mean_predicted", "observed_rate", "gap_pp")}
                                for b in e["calibration"]["bins"]],
           "economics": None if e["economics"] is None else {"contact_budget": e["economics"]["contact_budget"], "expected_value": e["economics"]["expected_value"],
                                                            "selected_account_ids": e["economics"]["selected_account_ids"],
                                                            "terms": [t["value_exact"] for t in e["economics"]["terms"]]},
           "outreach_queue": e["outreach_queue"],
           "feature_missingness": {"period": fm["period"], "overall_missing": fm["overall"]["missing"], "overall_total": fm["overall"]["total"],
                                   "overall_value": fm["overall"]["value"], "days_since_last_usage_missing": fm["by_feature"]["days_since_last_usage"]["missing"],
                                   "billing_total_90d_missing": fm["by_feature"]["billing_total_90d"]["missing"]},
           "empty_population": e["empty_population"], "empty_evaluation": e["empty_evaluation"]}
    return out


@pytest.mark.parametrize("variant", VARIANTS)
def test_sql_equals_expected_for_every_fixture_set_key_by_key(conn, variant):
    inputs, want = golden_inputs(variant), golden_expected(variant)
    load(conn, inputs)
    for pa, e in want["cutoff_sets"].items():
        row = reference(conn, inputs["as_of"], pa, scenario=SCENARIOS[variant].get(pa))
        got = {k: row[k] for k in expected_view(e)}
        assert flat(got) == flat(expected_view(e)), (variant, pa)
        f = row["freshness"]
        assert (f["scoring_hours"], f["data_hours"], f["latest_completed_publication_id"]) == (
            want["freshness"]["scoring_hours"], want["freshness"]["data_hours"], want["freshness"]["latest_completed_publication_id"])


def test_sql_spec_sentence_values(conn):
    inputs = golden_inputs()
    load(conn, inputs)
    r = reference(conn, inputs["as_of"], JAN, scenario="sc-001")
    assert r["precision_at_k"]["value"] == "0.500000" and r["recall_at_k"]["value"] == "0.500000" and r["brier_score"]["value"] == "0.192500"
    assert r["risk_lift_at_k"]["value"] == "1.000000" and r["economics"]["expected_value"] == "8.45" and r["economics"]["contact_budget"] == "10.00"
    assert r["churn_rate"]["value"] == "0.500000" and r["freshness"]["scoring_hours"] == 2878 and r["freshness"]["data_hours"] == 264


def test_sql_is_a_snapshot_as_of_an_instant(conn):
    """Before a4's late cancel and the Jan publication were known, the same facts say something else (nothing later is visible)."""
    inputs = golden_inputs()
    load(conn, inputs)
    early = reference(conn, "2026-04-12T00:00:00Z", JAN, scenario="sc-001")             # a3's cancel (available 04-10) is known, a4's (04-20) is not
    assert early["population"]["mature"] == 0 and early["churn_rate"]["value"] is None and early["precision_at_k"] is None       # label_end 04-15 > as_of: censored
    assert early["freshness"]["data_hours"] == 2 * 24 and early["freshness"]["scoring_hours"] == (101 * 24 - 2)                   # 04-12 minus 04-10, minus 01-01T02
    late = reference(conn, "2026-05-01T00:00:00Z", JAN, scenario="sc-001")
    assert late["population"]["mature"] == 4


def test_sql_counts_what_a_wrong_definition_would_get_wrong(conn):
    """The a4 case: its cancel arrives after label_end, so SQL (like the domain) says not churned; a3's arrives inside the grace: churned."""
    inputs = golden_inputs()
    load(conn, inputs)
    r = reference(conn, inputs["as_of"], JAN)
    assert r["population"]["churned"] == 2 and r["late_events"] == {"subscription_events": 0, "billing_events": 0, "usage_events": 1, "support_events": 1, "total": 2}
    assert r["economics"] is None and r["outreach_queue"] is None                         # no scenario: no queue, no economics


def test_sql_equals_the_domain_over_the_api_on_a_fitted_world(client, conn):
    load(conn, build_world())
    out = pipeline(client, command)
    assert all(r.status_code == 200 for r in out.values()), [(k, r.text[:200]) for k, r in out.items() if r.status_code != 200]
    for pa, scenario in ((SETS["test"][0], None), (SETS["new"][0], None), (SETS["test"][0], "sc-w"), (SETS["new"][0], "sc-w")):
        if scenario:
            r = command(client, "simulate-economics", {"training_run_id": "tr-w", "prediction_at": pa, "scenario": {"scenario_id": scenario, "capacity": 5,
                        "contact_cost": "7.50", "assumed_effect": "0.250000", "margin_value": "321.99"}})
            assert r.status_code == 200, r.text
        api = metrics(client, training_run_id="tr-w", prediction_at=pa, scenario_id=scenario, as_of=READ_AS_OF)["data"]["cutoff_sets"][pa]
        row = reference(conn, READ_AS_OF, pa, run="tr-w", scenario=scenario)
        want = {k: v for k, v in expected_view(api).items()}
        assert flat({k: row[k] for k in want}) == flat(want), (pa, scenario)
    first = reference(conn, READ_AS_OF, SETS["test"][0], run="tr-w")
    assert first["population"]["evaluated"] == first["population"]["mature"] == 28 and first["population"]["censored"] == 0
    newest = reference(conn, READ_AS_OF, SETS["new"][0], run="tr-w")
    assert newest["population"]["mature"] == 0 and newest["population"]["censored"] == 15 and newest["churn_rate"]["value"] is None


def test_sql_selects_the_model_whose_predictions_it_is_asked_about(client, conn):
    load(conn, build_world())
    pipeline(client, command)
    assert command(client, "score-accounts", {"training_run_id": "tr-w", "prediction_at": SETS["test"][0], "model": "random_baseline"}).status_code == 200
    pa = SETS["test"][0]
    rnd = reference(conn, READ_AS_OF, pa, run="tr-w", model="random_baseline")
    lr = reference(conn, READ_AS_OF, pa, run="tr-w", model="logistic_regression")
    assert rnd["brier_score"]["terms"] != lr["brier_score"]["terms"] and rnd["population"]["evaluated"] == lr["population"]["evaluated"] == 28
    api = metrics(client, training_run_id="tr-w", prediction_at=pa, model="random_baseline", as_of=READ_AS_OF)["data"]["cutoff_sets"][pa]
    assert api["brier_score"]["terms"] == rnd["brier_score"]["terms"]
