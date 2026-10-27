"""P09-TEST-01..12, each as DETECT (the violation is refused or shown, never accepted into a misleading number) and RECOVER (a valid correction or safe
replay restores consistency), through the real application path: the dataset of tests/fixtures/adversarial/test-NN-{detect,recover}.json is loaded by the
seeder (the domain's ingest) and read back through GET /metrics and GET /data, and the same rule is driven through the command that enforces it. Then the
race, atomicity and hostile-input tests."""
import threading
from urllib.parse import quote
from datetime import datetime, timezone
from fractions import Fraction as F

import psycopg
import pytest

from api import clock
from api import commands as cmds
from api.app import PREFIX

from support_db import (ADMIN, ANALYST, SPONSOR, SPONSOR2, client, command, conn, count, current_dataset_version, db_url, fixture, get, load, metrics, rule_ids, table_digest)

AS_OF = "2028-06-30T00:00:00Z"
NOW = datetime(2028, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
BUSINESS = ["initiatives", "process_baselines", "baseline_approvals", "assumption_versions", "resources", "scenario_versions", "scenario_initiatives", "cost_items", "expanded_costs",
            "benefit_items", "dependencies", "stakeholder_groups", "resource_allocations", "readiness_assessments", "adoption_observations", "training_completions",
            "benefit_observations", "forecast_versions", "command_results"]


def start(client, conn, name):
    """Load one adversarial fixture the way production data gets in, and freeze the clock after its as_of."""
    d = fixture(f"adversarial/test-{name}.json")
    load(conn, d, dataset_version="ds-adv")
    clock.freeze(NOW)
    return d


def read(client, **kw):
    return metrics(client, as_of=kw.pop("as_of", AS_OF), **kw)["data"]


def rejected(client):
    rows = get(client, "/data/rejected_records", limit=200).json()["data"]
    return {(r["entity"], r["id"]): r for r in rows}


def init(data, scn="scn-1", i="i-1"):
    return data["metrics"]["scenarios"][scn]["initiatives"][i]


def refused(client, conn, name, inp, status, rule, headers=None):
    before = table_digest(conn, BUSINESS)
    r = command(client, name, inp, headers=headers)
    assert r.status_code == status and rule in rule_ids(r), r.text
    assert table_digest(conn, BUSINESS) == before                         # nothing was written
    assert "Traceback" not in r.text and "postgresql://" not in r.text    # a specific explanation, no internals
    return r


def cash_flow(i):
    return [(r["costs"], r["cash_benefits"], r["net_cash_flow"]) for r in i["cash_flow"]]


# ------------------------------------------------------------------------------------------------------------ 01 time savings counted as cash
def test_01_detect_hours_claimed_as_cash_without_a_staffing_change_are_refused_and_hours_stay_out_of_the_cash_flow(client, conn):
    d = start(client, conn, "01-detect")
    rej = rejected(client)
    assert set(rej) == {("benefit_items", "b-bad")} and rej[("benefit_items", "b-bad")]["reason_code"] == "CAPACITY_WITHOUT_CONVERSION"
    assert rej[("benefit_items", "b-bad")]["details"] == {"hours": "50.00"} and rej[("benefit_items", "b-bad")]["raw_row"]["cash_realisation"] is True
    i = init(read(client))
    assert cash_flow(i)[1] == ("0.00", "700.00", "700.00")                                      # 700 cash; the 100 hours are NOT 100 dollars
    assert i["excluded_from_cash_flow"]["capacity_hours_not_converted"] == "100.00" and i["excluded_from_cash_flow"]["capacity_not_converted"][0]["reason"] == "NO_CONVERSION_ASSUMPTION"
    assert i["npv"]["exact"] == "-4000/11" and i["npv"]["value"] == "-363.64" and i["converted_capacity"] == []
    assert count(conn, "benefit_items") == 2                                                    # the valid records around the rejection are unaffected
    inp = {"scenario_id": "scn-api", "baseline_version": "v1", "discount_rate": "0.10", "rate_basis": "annual", "horizon_periods": 3, "initiative_ids": ["i-1"],
           "benefits": [{"initiative_id": "i-1", "benefit_type": "capacity", "amount": "50.00", "period_index": 2, "starts_period": 1, "cash_realisation": True}]}
    r = refused(client, conn, "build-cash-flows", inp, 422, "CAPACITY_WITHOUT_CONVERSION")
    assert "capacity_hourly_rate" in r.text and "staffing change evidence" in r.text
    again = refused(client, conn, "build-cash-flows", inp, 422, "CAPACITY_WITHOUT_CONVERSION")  # retrying the refusal adds no side effect
    assert again.json()["error"] == r.json()["error"]


def test_01_recover_a_recorded_conversion_makes_the_hours_separate_derived_cash_items(client, conn):
    start(client, conn, "01-recover")
    assert rejected(client) == {}
    i = init(read(client))
    conv = i["converted_capacity"]
    assert [(c["hours"], c["hourly_rate"], c["amount"], c["conversion_assumption_id"], c["staffing_change_evidence_ref"]) for c in conv] == [
        ("50.00", "25.00", "1250.00", "a-rate", "hr:headcount-plan-2026"), ("100.00", "25.00", "2500.00", "a-rate", "hr:headcount-plan-2026")]      # by benefit id
    assert i["cash_flow"][1]["benefits_by_class"] == {"cash": "700.00", "revenue": "0.00", "avoided_cost_realised": "0.00", "capacity_converted": "2500.00"}   # a separate class
    assert F(i["npv"]["exact"]) == F(356000, 121) and i["npv"]["value"] == "2942.15" and i["excluded_from_cash_flow"]["capacity_hours_not_converted"] is None


def test_01_recover_through_the_command_in_one_request(client, conn):
    start(client, conn, "01-detect")
    inp = {"scenario_id": "scn-api", "baseline_version": "v1", "discount_rate": "0.10", "rate_basis": "annual", "horizon_periods": 3, "initiative_ids": ["i-1"],
           "assumptions": [{"assumption_id": "a-api-rate", "initiative_id": "i-1", "name": "capacity_hourly_rate", "value": "25.00", "unit": "USD/hour", "rationale": "loaded cost",
                            "staffing_change_evidence_ref": "hr:headcount-plan-2026"}],
           "benefits": [{"initiative_id": "i-1", "benefit_type": "capacity", "amount": "50.00", "period_index": 2, "starts_period": 1, "cash_realisation": True}]}
    r = command(client, "build-cash-flows", inp, headers=ANALYST)
    assert r.status_code == 200, r.text
    blk = r.json()["result"]["scenario"]["initiatives"]["i-1"]
    assert {c["hours"]: c["amount"] for c in blk["converted_capacity"]} == {"100.00": "2500.00", "50.00": "1250.00"} and all(c["conversion_assumption_id"] == "a-api-rate" for c in blk["converted_capacity"])


# ------------------------------------------------------------------------------------------------------------ 02 two initiatives claim the same capacity
def test_02_detect_the_overlap_is_counted_once_listed_and_blocks_the_proposal_until_explained(client, conn):
    start(client, conn, "02-detect")
    dc = read(client)["metrics"]["scenarios"]["scn-1"]["double_count"]
    assert (dc["planned_benefits"], dc["attributable_benefits"], dc["residual"], dc["explanation_required"]) == ("800.00", "500.00", "300.00", True)
    assert dc["overlaps"] == [{"benefit_source_key": "cost-line:CC-1", "period_index": 1, "claims": [{"initiative_id": "i-1", "benefit_id": "b-1", "amount": "500.00"},
                                                                                                  {"initiative_id": "i-2", "benefit_id": "b-2", "amount": "300.00"}],
                              "counted_once": "500.00", "overlap": "300.00"}]
    r = command(client, "select-scenario", {"scenario_id": "scn-1"})
    assert r.status_code == 422 and rule_ids(r) == ["DOUBLE_COUNT_UNEXPLAINED"] and r.json()["error"]["details"][0]["context"]["residual"] == "300.00"
    assert conn.execute("SELECT status FROM scenario_versions WHERE scenario_id = 'scn-1'").fetchone()["status"] == "draft"
    assert command(client, "select-scenario", {"scenario_id": "scn-1", "residual_explanation": "   "}).status_code == 422          # a blank explanation is no explanation


def test_02_recover_a_scenario_without_the_overlap_or_a_written_explanation(client, conn):
    start(client, conn, "02-recover")
    sc = read(client)["metrics"]["scenarios"]
    assert sc["scn-2"]["double_count"]["residual"] == "0.00" and sc["scn-2"]["double_count"]["overlaps"] == [] and sc["scn-1"]["double_count"]["residual"] == "300.00"
    ok = command(client, "select-scenario", {"scenario_id": "scn-2", "compared_scenario_ids": ["scn-1"]})
    assert ok.status_code == 200 and ok.json()["result"]["status"] == "proposed" and ok.json()["result"]["comparison"]["scenarios"]["scn-1"]["residual"] == "300.00"
    explained = command(client, "select-scenario", {"scenario_id": "scn-1", "residual_explanation": "CC-1 is claimed by i-1 and i-2; counted once at the larger claim"})
    assert explained.status_code == 200 and conn.execute("SELECT residual_explanation FROM scenario_versions WHERE scenario_id = 'scn-1'").fetchone()["residual_explanation"].startswith("CC-1")


# ------------------------------------------------------------------------------------------------------------ 03 annual rate applied monthly
def test_03_detect_an_annual_rate_on_monthly_periods_is_never_applied_raw(client, conn):
    start(client, conn, "03-detect")
    rej = rejected(client)
    assert rej[("scenario_versions", "rs-annual")]["reason_code"] == "RATE_PERIOD_MISMATCH" and rej[("scenario_versions", "rs-annual")]["details"] == {"rate_basis": "annual", "period_basis": "monthly"}
    data = read(client)
    assert list(data["metrics"]["scenarios"]) == ["rs-monthly"] and data["period_basis"] == "monthly"
    inp = {"scenario_id": "rs-api", "baseline_version": "v1", "discount_rate": "0.10", "rate_basis": "annual", "horizon_periods": 3, "initiative_ids": ["i-1"]}
    refused(client, conn, "build-cash-flows", inp, 422, "RATE_PERIOD_MISMATCH")
    ok = command(client, "build-cash-flows", {**inp, "assumptions": [{"assumption_id": "a-api-conv", "name": "monthly_rate_conversion", "value": "0.007974", "unit": "rate per month",
                                                                      "rationale": "(1.10)^(1/12) - 1 = 0.0079741..., recorded to 6 places"}],
                                              "rate_conversion_assumption_id": "a-api-conv"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["result"]["scenario"]["effective_period_rate"] == "0.007974"


def test_03_recover_the_conversion_is_a_recorded_assumption_and_the_npv_is_exact_over_it(client, conn):
    start(client, conn, "03-recover")
    assert rejected(client) == {}
    sc = read(client)["metrics"]["scenarios"]["rs-annual"]
    assert (sc["rate_source"], sc["effective_period_rate"], sc["declared_rate"], sc["rate_basis"]) == ("conversion:a-conv", "0.007974", "0.100000", "annual")
    r = F(7974, 1_000_000)
    assert F(sc["initiatives"]["i-1"]["npv"]["exact"]) == -1000 + 600 / (1 + r) + 600 / (1 + r) ** 2
    assert sc["initiatives"]["i-1"]["npv"]["exact"] != "5000/121"                           # the raw 10% (41.32) was not applied to months
    assert get(client, "/data/assumption_versions", name="monthly_rate_conversion").json()["data"][0]["initiative_id"] is None


# ------------------------------------------------------------------------------------------------------------ 04 benefits before deployment
def test_04_detect_a_benefit_before_deployment_is_refused_with_both_periods(client, conn):
    start(client, conn, "04-detect")
    rej = rejected(client)
    assert rej[("benefit_items", "b-early")]["reason_code"] == "BENEFIT_BEFORE_DEPLOYMENT" and rej[("benefit_items", "b-early")]["details"] == {"starts_period": 1, "deployment_period": 2}
    i = init(read(client))
    assert [x["cash_benefits"] for x in i["cash_flow"]] == ["0.00", "0.00", "500.00", "0.00"]
    r = refused(client, conn, "build-cash-flows", {"scenario_id": "scn-api", "baseline_version": "v1", "discount_rate": "0.10", "rate_basis": "annual", "horizon_periods": 4,
                                                   "initiative_ids": ["i-1"], "benefits": [{"initiative_id": "i-1", "benefit_type": "cash", "amount": "5.00", "period_index": 1,
                                                                                            "starts_period": 1}]}, 422, "BENEFIT_BEFORE_DEPLOYMENT")
    assert r.json()["error"]["details"][0]["context"] == {"starts_period": 1, "deployment_period": 2}


def test_04_recover_benefits_start_at_deployment_with_a_ramp_and_the_unramped_plan_stays_visible(client, conn):
    start(client, conn, "04-recover")
    assert rejected(client) == {}
    i = init(read(client))
    assert [x["cash_benefits"] for x in i["cash_flow"]] == ["0.00", "0.00", "250.00", "500.00"]       # ramp [0.5, 1.0] indexed from each row's own starts_period (2)
    assert i["unramped_net_cash_flow"] == ["-400.00", "0.00", "500.00", "500.00"] and i["planned_money_benefits"] == {"ramped": "750.00", "unramped": "1000.00"}
    assert i["ramp"] == {"assumption_id": "a-ramp", "values": ["0.500000", "1.000000"]}


# ------------------------------------------------------------------------------------------------------------ 05 training mistaken for adoption
def test_05_detect_training_is_not_adoption_and_a_training_count_cannot_be_recorded_as_adoption(client, conn):
    start(client, conn, "05-detect")
    rej = rejected(client)
    assert rej[("adoption_observations", "ad-bad")]["reason_code"] == "ADOPTED_EXCEEDS_ELIGIBLE" and rej[("adoption_observations", "ad-rule")]["reason_code"] == "ELIGIBILITY_RULE_MISMATCH"
    m = read(client)["metrics"]
    ad, tr = m["initiatives"]["i-1"]["adoption"], m["initiatives"]["i-1"]["training"]
    assert ad["adoption_rate"] is None and ad["series"] == [] and tr["training_completion"] == "0.950000" and tr["substituted_for_adoption"] is False and tr["differs_from_adoption"] is None
    assert m["summary"]["adoption_rate"] is None and m["summary"]["training_completion"] == "0.950000"       # the pooled figures are separate too
    refused(client, conn, "record-adoption", {"initiative_id": "i-1", "eligible_count": 30, "adopted_count": 38, "eligibility_rule_version": "elig-v1"}, 422, "ADOPTED_EXCEEDS_ELIGIBLE")
    refused(client, conn, "record-adoption", {"initiative_id": "i-1", "eligible_count": 40, "adopted_count": 38, "eligibility_rule_version": "elig-v2"}, 422, "ELIGIBILITY_RULE_MISMATCH")


def test_05_recover_adoption_is_observed_on_its_own_denominator(client, conn):
    start(client, conn, "05-recover")
    m = read(client)["metrics"]["initiatives"]["i-1"]
    assert (m["adoption"]["adoption_rate"], m["training"]["training_completion"], m["training"]["differs_from_adoption"]) == ("0.750000", "0.950000", True)
    start_ = command(client, "record-adoption", {"initiative_id": "i-1", "eligible_count": 40, "adopted_count": 32, "eligibility_rule_version": "elig-v1", "observed_on": "2028-06-01"})
    assert start_.status_code == 200 and start_.json()["result"]["adoption_rate"] == "0.800000" and start_.json()["result"]["training"]["training_completion"] == "0.950000"


def test_05_recover_from_the_detect_state_through_the_command(client, conn):
    start(client, conn, "05-detect")
    ok = command(client, "record-adoption", {"initiative_id": "i-1", "eligible_count": 40, "adopted_count": 30, "eligibility_rule_version": "elig-v1", "observed_on": "2028-06-15"})
    assert ok.status_code == 200
    m = read(client)["metrics"]["initiatives"]["i-1"]
    assert m["adoption"]["adoption_rate"] == "0.750000" and m["training"]["training_completion"] == "0.950000"


# ------------------------------------------------------------------------------------------------------------ 06 forecast overwrite
def test_06_detect_the_original_forecast_cannot_be_overwritten_by_data_command_or_sql(client, conn):
    start(client, conn, "06-detect")
    assert [k for k in rejected(client)] == [("forecast_versions", "f-i-1-1-1-480.00")] and rejected(client)[("forecast_versions", "f-i-1-1-1-480.00")]["reason_code"] == "VERSION_EXISTS"
    f = read(client)["metrics"]["initiatives"]["i-1"]["forecast"]
    assert [v["total"] for v in f["versions"]] == ["1200.00"] and f["versions"][0]["by_period"][0]["amount"] == "600.00" and f["observed"][0]["measured_value"] == "480.00"
    before = table_digest(conn, ["forecast_versions"])
    for sql, args in [("UPDATE forecast_versions SET amount = 480 WHERE version_number = 1", ()), ("DELETE FROM forecast_versions WHERE version_number = 1", ()),
                      ("INSERT INTO forecast_versions (forecast_id, initiative_id, version_number, period_index, amount, reason, created_at) VALUES ('x', 'i-1', 1, 1, 480, 'r', now())", ())]:
        with pytest.raises(psycopg.errors.IntegrityError):
            conn.execute(sql, args)
    assert table_digest(conn, ["forecast_versions"]) == before
    refused(client, conn, "revise-forecast", {"initiative_id": "i-1", "reason": "x", "version_number": 1, "periods": [{"period_index": 1, "amount": "480.00"}]}, 422, "FIELD_UNEXPECTED")


def test_06_recover_the_revision_is_version_2_and_the_missed_target_stays_visible(client, conn):
    start(client, conn, "06-recover")
    f = read(client)["metrics"]["initiatives"]["i-1"]["forecast"]
    assert [(v["version_number"], v["total"], v["created_at"]) for v in f["versions"]] == [(1, "1200.00", "2026-01-20T00:00:00Z"), (2, "980.00", "2028-02-15T00:00:00Z")]
    assert f["latest_minus_original"] == "-220.00" and f["original_preserved"] is True and f["observed"][0]["measured_value"] == "480.00" and f["observed"][0]["period_matured"] is True


def test_06_recover_through_the_command_from_the_detect_state(client, conn):
    start(client, conn, "06-detect")
    r = command(client, "revise-forecast", {"initiative_id": "i-1", "reason": "Observed shortfall in the first full period", "expected_version": 1,
                                            "periods": [{"period_index": 1, "amount": "480.00"}, {"period_index": 2, "amount": "500.00"}]})
    assert r.status_code == 200 and r.json()["result"]["version_number"] == 2 and r.json()["result"]["latest_minus_original"] == "-220.00"
    assert [v["total"] for v in read(client, as_of="2028-07-02T00:00:00Z")["metrics"]["initiatives"]["i-1"]["forecast"]["versions"]] == ["1200.00", "980.00"]
    assert [v["total"] for v in read(client)["metrics"]["initiatives"]["i-1"]["forecast"]["versions"]] == ["1200.00"]            # as of 2028-06-30 the revision does not exist yet


# ------------------------------------------------------------------------------------------------------------ 07 dependency cycle
def test_07_detect_the_closing_edge_is_refused_with_the_cycle_listed_and_the_rest_stays(client, conn):
    start(client, conn, "07-detect")
    rej = rejected(client)
    assert rej[("dependencies", "d-3")]["reason_code"] == "DEPENDENCY_CYCLE" and rej[("dependencies", "d-3")]["details"] == {"cycle": ["i-1", "i-3", "i-2", "i-1"]}
    rm = read(client)["metrics"]["initiatives"]
    assert [rm[i]["roadmap"]["dependency_feasible_start"] for i in ("i-1", "i-2", "i-3")] == [0, 1, 2] and count(conn, "dependencies") == 2
    r = refused(client, conn, "plan-roadmap", {"dependencies": [{"initiative_id": "i-1", "prerequisite_id": "i-3", "dependency_type": "finish_to_start"}]}, 422, "DEPENDENCY_CYCLE")
    assert r.json()["error"]["details"][0]["context"]["cycle"] == ["i-1", "i-3", "i-2", "i-1"]


def test_07_recover_an_acyclic_edge_gives_feasible_starts_and_delays(client, conn):
    start(client, conn, "07-recover")
    assert rejected(client) == {}
    rm = read(client)["metrics"]["initiatives"]
    assert [(rm[i]["roadmap"]["dependency_feasible_start"], rm[i]["roadmap"]["dependency_delay"]) for i in ("i-1", "i-2", "i-3", "i-4")] == [(0, 0), (1, 1), (2, 2), (3, 3)]


def test_07_recover_from_the_detect_state_through_the_command(client, conn):
    start(client, conn, "07-detect")
    ok = command(client, "plan-roadmap", {"dependencies": [{"initiative_id": "i-3", "prerequisite_id": "i-1", "dependency_type": "start_to_start", "lag_periods": 1}]})
    assert ok.status_code == 200 and ok.json()["result"]["schedule"]["i-3"]["dependency_feasible_start"] == 2 and count(conn, "dependencies") == 3


# ------------------------------------------------------------------------------------------------------------ 08 never pays back
def test_08_detect_a_flow_that_never_pays_back_has_null_paybacks_not_zero_and_not_a_rejection(client, conn):
    start(client, conn, "08-detect")
    assert rejected(client) == {}
    i = init(read(client))
    assert i["payback"] == {"simple": {"period": None, "interpolated": None}, "discounted": {"period": None, "interpolated": None}}
    assert [x["cumulative"] for x in i["cash_flow"]] == ["-1000.00", "-900.00", "-800.00"] and F(i["npv"]["exact"]) < 0 and i["npv"]["label"] == "estimate"


def test_08_recover_a_longer_horizon_is_a_new_scenario_and_the_old_one_still_says_null(client, conn):
    start(client, conn, "08-recover")
    sc = read(client)["metrics"]["scenarios"]
    assert sc["scn-1"]["initiatives"]["i-1"]["payback"]["simple"]["period"] is None                                    # the first scenario was not edited
    two = sc["scn-2"]["initiatives"]["i-1"]
    assert two["payback"]["simple"] == {"period": 10, "interpolated": "10.0000"} and two["payback"]["discounted"] == {"period": None, "interpolated": None}      # exactly 0 counts
    assert F(two["npv"]["exact"]) < 0                                                                                 # it pays back undiscounted, not in present value


# ------------------------------------------------------------------------------------------------------------ 09 shared specialist overallocated
def test_09_detect_the_crossing_allocation_is_refused_with_its_periods_and_exactly_at_capacity_is_allowed(client, conn):
    start(client, conn, "09-detect")
    rej = rejected(client)
    assert list(rej) == [("resource_allocations", "al-2")] and rej[("resource_allocations", "al-2")]["details"] == {
        "resource_id": "res-1", "periods": [0], "allocated_before": "1.50", "requested": "1.00", "capacity": "2.00"}
    res = read(client)["metrics"]["resources"]["res-1"]
    assert res["by_period"] == [{"period_index": 0, "allocated": "2.00", "headroom": "0.00"}] and res["overallocated_periods"] == []
    assert get(client, "/data/resource_allocations").json()["meta"]["total_count"] == 2
    r = refused(client, conn, "plan-roadmap", {"allocations": [{"resource_id": "res-1", "initiative_id": "i-2", "period_index": 0, "amount": "0.01"}]}, 422, "RESOURCE_OVERALLOCATED")
    assert r.json()["error"]["details"][0]["context"]["periods"] == [0]


def test_09_recover_the_allocation_moves_to_a_period_with_headroom(client, conn):
    start(client, conn, "09-recover")
    assert rejected(client) == {}
    res = read(client)["metrics"]["resources"]["res-1"]
    assert res["by_period"] == [{"period_index": 0, "allocated": "2.00", "headroom": "0.00"}, {"period_index": 1, "allocated": "1.00", "headroom": "1.00"}]


def test_09_recover_from_the_detect_state_through_the_command(client, conn):
    start(client, conn, "09-detect")
    ok = command(client, "plan-roadmap", {"allocations": [{"resource_id": "res-1", "initiative_id": "i-2", "period_index": 1, "amount": "1.00"}]})
    assert ok.status_code == 200 and ok.json()["result"]["resources"]["res-1"]["by_period"][1] == {"period_index": 1, "allocated": "1.00", "headroom": "1.00"}


# ------------------------------------------------------------------------------------------------------------ 10 observed improvement attributed to the rollout
def test_10_detect_full_attribution_is_refused_and_the_trend_sits_beside_the_raw_change(client, conn):
    start(client, conn, "10-detect")
    c = init(read(client))["benefit_realization"]["cash"]
    assert (c["observed_comparable"], c["baseline_trend"], c["observed_above_trend"], c["realization"], c["attribution"]) == ("480.00", "50.00", "430.00", "0.800000", "observed, not attributed")
    r = refused(client, conn, "track-benefits", {"benefit_id": "b-1", "measured_value": "480.00", "unit": "USD", "evidence_ref": "ev:x", "attribution": "rollout_caused"},
                422, "ATTRIBUTION_NOT_ESTABLISHED")
    assert "baseline trend" in r.text


def test_10_recover_observed_not_attributed_and_the_trend_only_where_it_was_recorded(client, conn):
    start(client, conn, "10-recover")
    c = init(read(client))["benefit_realization"]["cash"]
    assert (c["planned_comparable"], c["observed_comparable"], c["realization"], c["baseline_trend"], c["attribution"]) == ("700.00", "570.00", "0.814286", "50.00", "observed, not attributed")


def test_10_recover_from_the_detect_state_through_the_command(client, conn):
    start(client, conn, "10-detect")
    r = command(client, "track-benefits", {"benefit_id": "b-1", "measured_value": "500.00", "unit": "USD", "evidence_ref": "ev:ap-ledger", "observed_on": "2028-05-31"})
    assert r.status_code == 200
    c = r.json()["result"]["comparisons"]["scn-1"]
    assert (c["observed_comparable"], c["observed_above_trend"], c["attribution"]) == ("500.00", "450.00", "observed, not attributed")        # the latest observation wins
    assert count(conn, "benefit_observations") == 2 and "OBSERVED_NOT_ATTRIBUTED" in [w["code"] for w in r.json()["warnings"]]


# ------------------------------------------------------------------------------------------------------------ 11 one-time cost recurs
def test_11_detect_a_repeated_one_time_cost_is_refused_and_the_first_is_kept(client, conn):
    start(client, conn, "11-detect")
    rej = rejected(client)[("cost_items", "c-2")]
    assert rej["reason_code"] == "ONE_TIME_COST_REPEATED" and rej["details"] == {"first_cost_id": "c-1", "first_period": 0, "repeat_period": 2}
    i = init(read(client))
    assert [x["costs"] for x in i["cash_flow"]] == ["1000.00", "0.00", "0.00"] and [x["cost_id"] for x in i["expanded_planned_costs"]] == ["c-1"]
    r = refused(client, conn, "build-cash-flows", {"scenario_id": "scn-api", "baseline_version": "v1", "discount_rate": "0.10", "rate_basis": "annual", "horizon_periods": 3,
                                                   "initiative_ids": ["i-1"], "costs": [{"initiative_id": "i-1", "cost_key": "ck-lic", "cost_type": "one_time", "amount": "1000.00",
                                                                                         "period_index": 2}]}, 422, "ONE_TIME_COST_REPEATED")
    assert r.json()["error"]["details"][0]["context"]["first_period"] == 0
    with pytest.raises(psycopg.errors.UniqueViolation):                                                              # the database refuses it as well
        conn.execute("INSERT INTO cost_items (cost_id, initiative_id, cost_key, cost_type, cost_basis, amount, period_index) VALUES ('c-9', 'i-1', 'ck-lic', 'one_time', 'planned', 1, 2)")


def test_11_recover_the_second_cost_is_a_recurring_fee_expanded_explicitly(client, conn):
    start(client, conn, "11-recover")
    assert rejected(client) == {}
    i = init(read(client))
    assert [x["costs"] for x in i["cash_flow"]] == ["1000.00", "100.00", "100.00"] and [(x["cost_id"], x["period_index"]) for x in i["expanded_planned_costs"]] == [("c-1", 0), ("c-2", 1), ("c-2", 2)]


# ------------------------------------------------------------------------------------------------------------ 12 cost avoidance as realised cash
def test_12_detect_avoided_cost_without_a_removed_budget_line_stays_beside_the_cash_flow(client, conn):
    start(client, conn, "12-detect")
    assert rejected(client) == {}                                                                                      # accepted as a plan, never refused
    i = init(read(client))
    assert [(x["benefit_id"], x["reason"]) for x in i["excluded_from_cash_flow"]["avoided_cost_beside"]] == [("b-av1", "NOT_CASH_REALISED"), ("b-av2", "NO_EVIDENCE_REF")]
    assert i["excluded_from_cash_flow"]["avoided_cost_beside_total"] == "1000.00" and [x["cash_benefits"] for x in i["cash_flow"]] == ["0.00", "600.00", "0.00"]
    assert i["npv"]["exact"] == "500/11" and i["npv"]["value"] == "45.45"


def test_12_recover_evidence_of_a_removed_budget_line_moves_it_into_the_cash_flow(client, conn):
    start(client, conn, "12-recover")
    i = init(read(client))
    assert i["cash_flow"][1]["benefits_by_class"]["avoided_cost_realised"] == "800.00" and i["cash_flow"][1]["cash_benefits"] == "1400.00"
    assert [x["benefit_id"] for x in i["excluded_from_cash_flow"]["avoided_cost_beside"]] == ["b-av2"] and i["excluded_from_cash_flow"]["avoided_cost_beside_total"] == "200.00"
    assert i["npv"]["exact"] == "8500/11" and i["npv"]["value"] == "772.73"


# ---------------------------------------------------------------------------------------------------- concurrency
def _race(fn, n=2):
    """Run ``fn(i)`` in ``n`` threads released together; return the results in thread order."""
    barrier, out = threading.Barrier(n), [None] * n

    def run(i):
        barrier.wait()
        out[i] = fn(i)
    ts_ = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts_]
    [t.join() for t in ts_]
    return out


def _client():
    from fastapi.testclient import TestClient
    from api.app import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def lab(client, conn):
    from support_db import golden_inputs
    load(conn, golden_inputs(), dataset_version="ds-golden")
    clock.freeze(NOW)
    return client


def test_two_approvals_of_one_baseline_version_leave_one_approval(lab, conn):
    inp = {"action": "approve", "initiative_id": "init-002", "baseline_version": "v2", "reason": "restated"}
    out = _race(lambda i: command(_client(), "establish-baseline", inp, key=f"ap-{i}", headers=(SPONSOR, SPONSOR2)[i]))
    assert sorted(r.status_code for r in out) == [200, 409], [r.text for r in out]
    assert count(conn, "baseline_approvals", "initiative_id = 'init-002'") == 2 and count(conn, "audit_events", "action = 'establish-baseline'") == 1
    assert [r.json()["error"]["details"][0]["rule_id"] for r in out if r.status_code == 409] == ["ALREADY_APPROVED"]


def test_two_proposals_of_one_scenario_leave_one(lab, conn):
    inp = {"scenario_id": "scn-001", "residual_explanation": "counted once"}
    out = _race(lambda i: command(_client(), "select-scenario", inp, key=f"sel-{i}", headers=(SPONSOR, SPONSOR2)[i]))
    assert sorted(r.status_code for r in out) == [200, 409] and count(conn, "audit_events", "action = 'select-scenario'") == 1
    assert [r.json()["error"]["details"][0]["rule_id"] for r in out if r.status_code == 409] == ["ALREADY_PROPOSED"]


def test_two_revisions_of_one_forecast_serialise_and_never_overwrite(lab, conn):
    body = lambda n: {"initiative_id": "init-001", "reason": f"revision {n}", "periods": [{"period_index": 1, "amount": f"{400 + n}.00"}]}
    out = _race(lambda i: command(_client(), "revise-forecast", body(i), key=f"rev-{i}", headers=(SPONSOR, SPONSOR2)[i]), 2)
    assert [r.status_code for r in out] == [200, 200] and sorted(r.json()["result"]["version_number"] for r in out) == [3, 4]          # serialised: n+1 each time
    assert count(conn, "forecast_versions", "version_number IN (1, 2)") == 4
    same = lambda i: command(_client(), "revise-forecast", {**body(i), "expected_version": 4}, key=f"revx-{i}", headers=(SPONSOR, SPONSOR2)[i])
    out = _race(same)
    assert sorted(r.status_code for r in out) == [200, 409] and [r.json()["error"]["details"][0]["rule_id"] for r in out if r.status_code == 409] == ["STALE_FORECAST_VERSION"]
    assert count(conn, "forecast_versions", "version_number = 5") == 1


def test_two_builds_of_one_scenario_id_leave_one(lab, conn):
    inp = {"scenario_id": "scn-race", "baseline_version": "v1", "discount_rate": "0.10", "rate_basis": "annual", "horizon_periods": 3, "initiative_ids": ["init-001"]}
    out = _race(lambda i: command(_client(), "build-cash-flows", inp, key=f"bld-{i}", headers=ANALYST))
    assert sorted(r.status_code for r in out) == [200, 409], [r.text for r in out]
    assert count(conn, "scenario_versions", "scenario_id = 'scn-race'") == 1 and count(conn, "expanded_costs", "scenario_id = 'scn-race'") == 1


def test_two_allocations_that_together_cross_a_capacity_leave_one(lab, conn):
    body = lambda init: {"allocations": [{"resource_id": "res-001", "initiative_id": init, "period_index": 5, "amount": "1.50"}]}
    out = _race(lambda i: command(_client(), "plan-roadmap", body(("init-001", "init-002")[i]), key=f"alloc-{i}", headers=ANALYST))
    assert sorted(r.status_code for r in out) == [200, 422] and [rule_ids(r) for r in out if r.status_code == 422] == [["RESOURCE_OVERALLOCATED"]]
    assert count(conn, "resource_allocations", "period_index = 5") == 1


def test_two_opposite_dependencies_leave_one_and_never_a_cycle(lab, conn):
    for n in ("init-009", "init-010"):
        assert command(lab, "assess-opportunity", {"initiative_id": n, "new_initiative": {"title": n, "sponsor_id": "sp-x"}, "criteria": [{"criterion": "c", "score": 3, "weight": "1"}],
                                                   "rationale": "r"}).status_code == 200
    edge = lambda a, b: {"dependencies": [{"initiative_id": a, "prerequisite_id": b, "dependency_type": "finish_to_start"}]}
    pairs = (("init-009", "init-010"), ("init-010", "init-009"))
    out = _race(lambda i: command(_client(), "plan-roadmap", edge(*pairs[i]), key=f"cyc-{i}", headers=ANALYST))
    assert sorted(r.status_code for r in out) == [200, 422], [r.text for r in out]
    assert [rule_ids(r) for r in out if r.status_code == 422] == [["DEPENDENCY_CYCLE"]]
    assert count(conn, "dependencies", "initiative_id IN ('init-009', 'init-010')") == 1


def test_the_same_idempotency_key_raced_executes_once(lab, conn):
    inp = {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]}
    out = _race(lambda i: command(_client(), "assess-readiness", inp, key="same-key", headers=ANALYST), 3)
    assert {r.status_code for r in out} == {200} and count(conn, "readiness_assessments", "group_id = 'grp-003'") == 1
    assert count(conn, "command_results", "idempotency_key = 'same-key'") == 1 and len({r.json()["command_id"] for r in out}) == 1


def test_a_deadlock_is_retried_three_times_then_409_concurrent_update(lab, conn, monkeypatch):
    from api.errors import ApiError
    from api.schemas import AssessReadinessRequest
    calls = {"n": 0}

    def deadlock(c, req, actor):
        calls["n"] += 1
        raise psycopg.errors.DeadlockDetected("deadlock detected")

    monkeypatch.setattr(cmds.time, "sleep", lambda s: None)
    req = AssessReadinessRequest(request_id="r", dataset_version=current_dataset_version(), idempotency_key="k-dl", input={"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]})
    with pytest.raises(ApiError) as exc:
        cmds.execute("assess-readiness", req, cmds.Actor("u", "analyst"), deadlock)
    assert exc.value.status == 409 and exc.value.code == "CONCURRENT_UPDATE" and calls["n"] == cmds.MAX_ATTEMPTS == 3
    calls["n"] = 0

    def flaky(c, req, actor):
        calls["n"] += 1
        if calls["n"] < 3:
            raise psycopg.errors.DeadlockDetected("deadlock detected")
        return cmds.Outcome("ok", {"attempt": calls["n"]})

    body, replayed = cmds.execute("assess-readiness", req, cmds.Actor("u", "analyst"), flaky)
    assert body["result"] == {"attempt": 3} and replayed is False and count(conn, "command_results", "idempotency_key = 'k-dl'") == 1


def test_a_deadlock_through_the_http_route_is_409_not_500(lab, conn, monkeypatch):
    def deadlock(c, req, actor):
        raise psycopg.errors.SerializationFailure("could not serialize")
    monkeypatch.setattr(cmds.time, "sleep", lambda s: None)
    monkeypatch.setattr(cmds, "assess_readiness", deadlock)
    from fastapi.testclient import TestClient
    from api.app import create_app
    with TestClient(create_app(), raise_server_exceptions=False) as c2:
        r = command(c2, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONCURRENT_UPDATE" and "serialize" not in r.text


def test_a_failure_after_the_write_rolls_the_command_and_its_audit_back(lab, conn, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    real = cmds.insert_row
    seen = {"n": 0}

    def boom(*a, **kw):
        real(*a, **kw)
        seen["n"] += 1
        if seen["n"] == 2:
            raise RuntimeError("after the second write")

    monkeypatch.setattr(cmds, "insert_row", boom)
    inp = {"scenario_id": "scn-boom", "baseline_version": "v1", "discount_rate": "0.10", "rate_basis": "annual", "horizon_periods": 3, "initiative_ids": ["init-001"],
           "costs": [{"initiative_id": "init-001", "cost_key": "x", "cost_type": "one_time", "amount": "1.00", "period_index": 1}]}
    with TestClient(create_app(), raise_server_exceptions=False) as c2:
        before = table_digest(conn, BUSINESS + ["audit_events"])
        r = command(c2, "build-cash-flows", inp)
        assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR" and "after the second write" not in r.text
        assert seen["n"] == 2 and table_digest(conn, BUSINESS + ["audit_events"]) == before          # the scenario row written first was rolled back with the rest
    monkeypatch.setattr(cmds, "insert_row", real)
    assert command(lab, "build-cash-flows", inp).status_code == 200                                  # and the same request, retried, succeeds once


def test_an_interrupted_command_leaves_no_idempotency_record_so_the_retry_runs(lab, conn, monkeypatch):
    real = cmds.record_adoption

    def die(conn_, req, actor):
        real(conn_, req, actor)
        raise RuntimeError("connection lost")

    monkeypatch.setattr(cmds, "record_adoption", die)
    from fastapi.testclient import TestClient
    from api.app import create_app
    inp = {"initiative_id": "init-001", "eligible_count": 40, "adopted_count": 30, "eligibility_rule_version": "elig-v1", "observed_on": "2028-06-20"}
    with TestClient(create_app(), raise_server_exceptions=False) as c2:
        assert command(c2, "record-adoption", inp, key="resume-1").status_code == 500
    assert count(conn, "adoption_observations") == 5 and count(conn, "command_results") == 0           # explicit non-commit
    monkeypatch.setattr(cmds, "record_adoption", real)
    ok = command(lab, "record-adoption", inp, key="resume-1")
    assert ok.status_code == 200 and count(conn, "adoption_observations") == 6 and command(lab, "record-adoption", inp, key="resume-1").headers["Idempotent-Replay"] == "true"


# ---------------------------------------------------------------------------------------------------- hostile input
@pytest.mark.parametrize("value", ["'; DROP TABLE initiatives; --", "init-001' OR '1'='1", "\u0000", "é" * 200, "../../etc/passwd", "init-001\n", " init-001"])
def test_hostile_ids_are_data_not_code(lab, conn, value):
    n = count(conn, "initiatives")
    r = command(lab, "record-adoption", {"initiative_id": value, "eligible_count": 1, "adopted_count": 1, "eligibility_rule_version": "elig-v1"})
    assert r.status_code in (404, 422) and "Traceback" not in r.text and count(conn, "initiatives") == n
    assert get(lab, "/data/cost_items", initiative_id=value).status_code in (200, 422)
    assert get(lab, "/metrics", scenario_id=value).status_code in (404, 422)
    assert get(lab, "/data/" + quote(value, safe="")).status_code in (404, 422)
    assert command(lab, "map-impacts", {"initiative_id": "init-001", "mappings": [{"group_id": "grp-001", "operating_change": value, "impact_level": "low"}]}).status_code in (200, 422)
    assert count(conn, "initiatives") == n


def test_non_finite_numbers_floats_and_oversize_bodies_are_refused(lab):
    h = {**ADMIN, "content-type": "application/json"}
    body = '{"request_id":"r","dataset_version":"x","idempotency_key":"k1","input":{"benefit_id":"b-101","measured_value":NaN,"unit":"USD","evidence_ref":"e"}}'
    assert lab.post(f"{PREFIX}/commands/track-benefits", content=body, headers=h).status_code == 422
    assert command(lab, "track-benefits", {"benefit_id": "b" * 5000, "measured_value": "1.00", "unit": "USD", "evidence_ref": "e"}).status_code == 422
    assert command(lab, "track-benefits", {"benefit_id": "b-101", "measured_value": 12.5, "unit": "USD", "evidence_ref": "e"}).status_code == 422          # a JSON number is never money
    assert command(lab, "track-benefits", {"benefit_id": "b-101", "measured_value": "12.5000001", "unit": "USD", "evidence_ref": "e"}).status_code == 422     # 7 places: not rounded silently
    assert command(lab, "track-benefits", {"benefit_id": "b-101", "measured_value": "1" * 20, "unit": "USD", "evidence_ref": "e"}).status_code == 422
    assert command(lab, "track-benefits", {"benefit_id": "b-101", "measured_value": "1e3", "unit": "USD", "evidence_ref": "e"}).status_code == 422
    huge = command(lab, "build-cash-flows", {"scenario_id": "s", "baseline_version": "v1", "discount_rate": "0.1", "rate_basis": "annual", "horizon_periods": 10**12, "initiative_ids": ["init-001"]})
    assert huge.status_code == 422


def test_the_largest_storable_value_is_accepted_and_one_digit_more_is_a_422_not_a_500(lab, conn):
    edge = "99999999999999.999999"                                                                      # 14 + 6 digits: exactly NUMERIC(20,6)
    ok = command(lab, "plan-roadmap", {"resources": [{"resource_id": "res-big", "name": "n", "capacity_per_period": edge, "unit": "FTE"}]})
    assert ok.status_code == 200 and get(lab, "/data/resources", unit="FTE").json()["data"][-1]["capacity_per_period"] == edge
    for too_big in ("999999999999999.00", "1.0000001", "-1" + "0" * 20):
        r = command(lab, "plan-roadmap", {"resources": [{"resource_id": "res-x", "name": "n", "capacity_per_period": too_big, "unit": "FTE"}]})
        assert r.status_code == 422 and "DECIMAL_INVALID" in rule_ids(r), too_big
    assert count(conn, "resources", "resource_id = 'res-x'") == 0


def test_a_client_can_never_supply_a_server_stamped_instant_in_any_command(lab, conn):
    stamped = {"created_at": "2020-01-01T00:00:00Z"}
    cases = {
        "establish-baseline": {"initiative_id": "init-003", "baseline_version": "v2", "volume": 1, "minutes_per_case": 1, "error_rate": "0.1", "evidence_ref": "e", "measured_on": "2028-01-01"},
        "assess-opportunity": {"initiative_id": "init-003", "criteria": [{"criterion": "c", "score": 1, "weight": "1"}], "rationale": "r"},
        "build-cash-flows": {"scenario_id": "s", "baseline_version": "v1", "discount_rate": "0.1", "rate_basis": "annual", "horizon_periods": 2, "initiative_ids": ["init-001"]},
        "map-impacts": {"initiative_id": "init-001", "mappings": [{"group_id": "grp-001", "operating_change": "c", "impact_level": "low"}]},
        "assess-readiness": {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]},
        "plan-roadmap": {"schedule": [{"initiative_id": "init-001", "requested_start_period": 0, "duration_periods": 1}]},
        "select-scenario": {"scenario_id": "scn-001", "residual_explanation": "x"},
        "record-adoption": {"initiative_id": "init-001", "eligible_count": 1, "adopted_count": 1, "eligibility_rule_version": "elig-v1"},
        "track-benefits": {"benefit_id": "b-101", "measured_value": "1.00", "unit": "USD", "evidence_ref": "e"},
        "revise-forecast": {"initiative_id": "init-001", "reason": "r", "periods": [{"period_index": 1, "amount": "1.00"}]}}
    assert len(cases) == 10
    for name, inp in cases.items():
        for field in ("created_at", "proposed_at", "observed_at", "assessed_at", "approved_at", "recorded_at"):
            r = command(lab, name, {**inp, field: "2020-01-01T00:00:00Z"})
            assert r.status_code == 422 and "FIELD_UNEXPECTED" in rule_ids(r), (name, field, r.text)
    assert count(conn, "command_results") == 0
