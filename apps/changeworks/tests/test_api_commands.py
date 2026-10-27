"""Commands C01..C10: happy paths, hard validation, roles, idempotency, stale dataset versions, audit and atomicity."""
from datetime import datetime, timezone

import pytest

from api import clock
from api.app import PREFIX

from support_db import (ADMIN, ANALYST, SPONSOR, SPONSOR2, client, command, conn, count, current_dataset_version, db_url, get, golden_inputs, load, metrics,  # noqa: F401
                        rule_ids, table_digest)

NOW = datetime(2028, 7, 1, 12, 0, 0, tzinfo=timezone.utc)       # after the fixture's as_of (2028-06-30)
BUSINESS = ["initiatives", "process_baselines", "baseline_approvals", "assumption_versions", "opportunity_scores", "resources", "scenario_versions", "scenario_initiatives",
            "scenario_pins", "cost_items", "expanded_costs", "benefit_items", "dependencies", "stakeholder_groups", "impact_mappings", "resource_allocations",
            "readiness_assessments", "adoption_observations", "training_completions", "benefit_observations", "risk_items", "forecast_versions"]
NOTHING_WRITTEN = BUSINESS + ["audit_events", "command_results"]


@pytest.fixture
def lab(client, conn):
    load(conn, golden_inputs(), dataset_version="ds-golden")
    clock.freeze(NOW)
    return client


def audit(conn, action, entity_id=None):
    return conn.execute("SELECT * FROM audit_events WHERE action = %s AND (%s::text IS NULL OR entity_id = %s)", (action, entity_id, entity_id)).fetchall()


def refused(lab, conn, name, inp, status, rule, headers=None, key=None, audited=False):
    """The command is refused with ``rule`` and NOTHING is written: no business row, no stored result, and no audit row except the one refusal record
    (``audited``) that is kept on purpose in its own transaction."""
    before = table_digest(conn, BUSINESS + ["command_results"])
    n = count(conn, "audit_events")
    r = command(lab, name, inp, headers=headers, key=key)
    assert r.status_code == status and rule in rule_ids(r), r.text
    assert table_digest(conn, BUSINESS + ["command_results"]) == before
    assert count(conn, "audit_events") == n + (1 if audited else 0)
    return r


# ------------------------------------------------------------------------------------------------------------ C01 establish-baseline
BASE = {"initiative_id": "init-003", "baseline_version": "v2", "volume": 950, "minutes_per_case": 18, "error_rate": "0.070000", "evidence_ref": "ev:vendor-register-2026",
        "measured_on": "2028-05-31"}


def test_c01_creates_a_baseline_from_evidence_only_with_the_actor_and_the_servers_time(lab, conn):
    r = command(lab, "establish-baseline", BASE, headers=ANALYST)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "established" and body["result"]["approved"] is False and body["result"]["approved_baseline_version"] is None
    row = conn.execute("SELECT *, cw_iso(measured_at) AS m FROM process_baselines WHERE baseline_version = 'v2' AND initiative_id = 'init-003'").fetchone()
    assert (row["volume"], row["minutes_per_case"], str(row["error_rate"]), row["evidence_ref"], row["m"], row["created_by"], row["created_at"] == NOW) == (
        950, 18, "0.070000", "ev:vendor-register-2026", "2028-05-31T00:00:00Z", "usr-analyst01", True)
    assert len(audit(conn, "establish-baseline", row["baseline_id"])) == 1
    assert conn.execute("SELECT baseline_version FROM initiatives WHERE initiative_id = 'init-003'").fetchone()["baseline_version"] is None      # created, not approved


def test_c01_evidence_and_assumptions_are_separate(lab, conn):
    for field in ("target_minutes_per_case", "expected_savings", "adoption_ramp", "assumed_volume"):
        r = refused(lab, conn, "establish-baseline", {**BASE, field: "8"}, 422, "ASSUMPTION_IN_EVIDENCE")
        assert r.json()["error"]["details"][0]["path"] == f"input.{field}" or field in str(r.json())
    missing = refused(lab, conn, "establish-baseline", {"initiative_id": "init-003", "baseline_version": "v2"}, 422, "FIELD_REQUIRED")
    assert {d["path"] for d in missing.json()["error"]["details"]} == {"input.volume", "input.minutes_per_case", "input.error_rate", "input.evidence_ref", "input.measured_on"}
    refused(lab, conn, "establish-baseline", {**BASE, "evidence_ref": "   "}, 422, "EVIDENCE_REQUIRED")


def test_c01_the_client_never_supplies_an_instant(lab, conn):
    refused(lab, conn, "establish-baseline", {**BASE, "measured_at": "2020-01-01T00:00:00Z"}, 422, "FIELD_UNEXPECTED")
    refused(lab, conn, "establish-baseline", {**BASE, "measured_on": "2020-01-01T00:00:00Z"}, 422, "DATE_INVALID")
    refused(lab, conn, "establish-baseline", {**BASE, "measured_on": "2029-01-01"}, 422, "DATE_IN_FUTURE")
    refused(lab, conn, "establish-baseline", {**BASE, "measured_on": "2028-02-30"}, 422, "DATE_INVALID")


def test_c01_a_correction_of_an_approved_baseline_is_a_new_version_with_a_reason_and_the_old_one_stays(lab, conn):
    v2 = {**BASE, "initiative_id": "init-001", "volume": 13000}
    refused(lab, conn, "establish-baseline", v2, 422, "REASON_REQUIRED")                         # init-001 has an approved baseline (v1)
    before_v1 = table_digest(conn, ["process_baselines"])
    ok = command(lab, "establish-baseline", {**v2, "reason": "volume restated after the audit"}, headers=ANALYST)
    assert ok.status_code == 200 and ok.json()["result"]["approved_baseline_version"] == "v1"
    assert before_v1 != table_digest(conn, ["process_baselines"]) and count(conn, "process_baselines", "baseline_version = 'v1' AND initiative_id = 'init-001'") == 1
    assert conn.execute("SELECT volume FROM process_baselines WHERE baseline_id = 'pb-101'").fetchone()["volume"] == 12000        # v1 untouched


def test_c01_an_approved_version_cannot_be_rewritten_409_and_the_refusal_is_audited(lab, conn):
    r = refused(lab, conn, "establish-baseline", {**BASE, "initiative_id": "init-001", "baseline_version": "v1", "reason": "oops"}, 409, "BASELINE_FROZEN", audited=True)
    assert r.json()["error"]["code"] == "BASELINE_FROZEN"
    assert len(audit(conn, "establish-baseline-refused", "init-001")) == 1
    v = command(lab, "establish-baseline", {**BASE, "initiative_id": "init-002", "baseline_version": "v2", "reason": "again"}, headers=ANALYST)       # v2 exists (not approved): VERSION_EXISTS
    assert v.status_code == 409 and rule_ids(v) == ["VERSION_EXISTS"]


def test_c01_approval_needs_a_sponsor_or_admin_freezes_the_version_and_keeps_the_old_one_readable(lab, conn):
    inp = {"action": "approve", "initiative_id": "init-002", "baseline_version": "v2", "reason": "restated volume accepted"}
    r = command(lab, "establish-baseline", inp, headers=ANALYST)
    assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"]
    assert count(conn, "baseline_approvals") == 2 and len(audit(conn, "establish-baseline-refused", "init-002")) == 1               # refused and audited
    ok = command(lab, "establish-baseline", inp, headers=SPONSOR)
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["version"] == 2
    res = ok.json()["result"]
    assert (res["baseline_version"], res["previous_baseline_version"], res["approved_by"], res["frozen_baseline_ids"]) == ("v2", "v1", "usr-sponsor01", ["pb-202"])
    assert ok.json()["warnings"][0]["code"] == "BASELINE_SUPERSEDED"
    ini = conn.execute("SELECT baseline_version, version FROM initiatives WHERE initiative_id = 'init-002'").fetchone()
    assert ini == {"baseline_version": "v2", "version": 2}
    assert count(conn, "process_baselines", "initiative_id = 'init-002'") == 2                                                         # v1 stays readable
    again = command(lab, "establish-baseline", inp, headers=ADMIN)
    assert again.status_code == 409 and rule_ids(again) == ["ALREADY_APPROVED"]
    back = command(lab, "establish-baseline", {**inp, "baseline_version": "v1"}, headers=ADMIN)
    assert back.status_code == 409 and rule_ids(back) == ["ALREADY_APPROVED"]                                                           # a superseded version is not re-approved
    m = metrics(lab, as_of="2028-06-30T00:00:00Z")
    assert m["data"]["metrics"]["scenarios"]["scn-001"]["initiatives"]["init-002"]["capacity_released"]["hours"] == "660.0000"       # 6600 x (30 - 24) / 60 from the NEW approved set
    assert "BASELINE_VERSION_DIFFERS" in [w["code"] for w in m["warnings"]]                                                           # scn-001 was built on v1: said, not hidden


def test_c01_approval_refusals(lab, conn):
    base = {"action": "approve", "initiative_id": "init-003", "baseline_version": "v9"}
    refused(lab, conn, "establish-baseline", base, 404, "UNKNOWN_BASELINE")
    refused(lab, conn, "establish-baseline", {**base, "initiative_id": "init-404", "baseline_version": "v1"}, 404, "UNKNOWN_INITIATIVE")
    refused(lab, conn, "establish-baseline", {**base, "baseline_version": "v1", "expected_version": 7}, 409, "STALE_VERSION")
    ok = command(lab, "establish-baseline", {**base, "baseline_version": "v1", "expected_version": 1}, headers=SPONSOR)
    assert ok.status_code == 200 and ok.json()["result"]["previous_baseline_version"] is None and ok.json()["warnings"] == []


# ------------------------------------------------------------------------------------------------------------ C02 assess-opportunity
CRIT = [{"criterion": "value", "score": 4, "weight": "2.00"}, {"criterion": "effort", "score": 2, "weight": "1.00"}]


def test_c02_scores_a_candidate_with_explicit_weights_and_rationale_and_versions_the_score(lab, conn):
    r = command(lab, "assess-opportunity", {"initiative_id": "init-003", "criteria": CRIT, "rationale": "value dominates effort"}, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (res["version_number"], res["weighted_score"], res["weighted_exact"], res["status"]) == (1, "3.3333", "10/3", "assessed")
    assert r.json()["version"] == 2 and conn.execute("SELECT status, version FROM initiatives WHERE initiative_id = 'init-003'").fetchone() == {"status": "assessed", "version": 2}
    second = command(lab, "assess-opportunity", {"initiative_id": "init-003", "criteria": [{"criterion": "value", "score": 5, "weight": "1"}], "rationale": "re-scored"})
    assert second.json()["result"]["version_number"] == 2 and second.json()["result"]["weighted_score"] == "5.0000" and second.json()["version"] == 2     # no status change
    assert count(conn, "opportunity_scores", "initiative_id = 'init-003'") == 2
    assert len(audit(conn, "assess-opportunity", "init-003")) == 2


def test_c02_creates_a_candidate_when_asked(lab, conn):
    r = command(lab, "assess-opportunity", {"initiative_id": "init-009", "new_initiative": {"title": "Smart routing", "sponsor_id": "sp-ops"}, "criteria": CRIT, "rationale": "r"})
    assert r.status_code == 200 and r.json()["version"] == 1
    assert conn.execute("SELECT status, deployment_period, created_by FROM initiatives WHERE initiative_id = 'init-009'").fetchone() == {"status": "assessed", "deployment_period": 1,
                                                                                                                                     "created_by": "usr-sponsor01"}
    again = command(lab, "assess-opportunity", {"initiative_id": "init-009", "new_initiative": {"title": "x", "sponsor_id": "s"}, "criteria": CRIT, "rationale": "r"})
    assert again.status_code == 409 and rule_ids(again) == ["INITIATIVE_EXISTS"]


@pytest.mark.parametrize("patch,status,rule", [
    ({"rationale": "  "}, 422, "RATIONALE_REQUIRED"), ({"rationale": None}, 422, "FIELD_INVALID"),
    ({"criteria": [{"criterion": "value", "score": 4}]}, 422, "FIELD_REQUIRED"), ({"criteria": [{"criterion": "value", "score": 4, "weight": "0"}]}, 422, "INVALID_WEIGHT"),
    ({"criteria": [{"criterion": "value", "score": 6, "weight": "1"}]}, 422, "FIELD_INVALID"), ({"criteria": [{"criterion": "value", "score": 4, "weight": 1}]}, 422, "FIELD_INVALID"),
    ({"criteria": [{"criterion": "v", "score": 4, "weight": "1"}, {"criterion": "v", "score": 3, "weight": "1"}]}, 422, "DUPLICATE_CRITERION"), ({"criteria": []}, 422, "FIELD_INVALID"),
    ({"initiative_id": "nope"}, 404, "UNKNOWN_INITIATIVE"), ({"expected_version": 9}, 409, "STALE_VERSION")])
def test_c02_hard_validation_weights_and_rationale_explicit(lab, conn, patch, status, rule):
    refused(lab, conn, "assess-opportunity", {"initiative_id": "init-003", "criteria": CRIT, "rationale": "because", **patch}, status, rule)


# ------------------------------------------------------------------------------------------------------------ C03 build-cash-flows
SCN = {"scenario_id": "scn-new", "baseline_version": "v1", "discount_rate": "0.10", "rate_basis": "annual", "horizon_periods": 3, "initiative_ids": ["init-001"]}


def test_c03_builds_a_new_scenario_and_expands_recurring_costs_explicitly(lab, conn):
    inp = {**SCN, "costs": [{"initiative_id": "init-001", "cost_key": "support", "cost_type": "recurring", "amount": "50.00", "start_period": 1, "end_period": 3}],
           "benefits": [{"initiative_id": "init-001", "benefit_type": "cash", "amount": "100.00", "period_index": 1, "starts_period": 1}]}
    r = command(lab, "build-cash-flows", inp, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["rows_added"] == {"assumption_versions": 0, "cost_items": 1, "benefit_items": 1, "expanded_costs": 3}
    assert [(e["cost_id"], e["period_index"], e["amount"]) for e in res["expanded_costs"] if e["cost_id"] != "c-101"] == [(res["expanded_costs"][1]["cost_id"], 1, "50.00"), (res["expanded_costs"][2]["cost_id"], 2, "50.00")]
    blk = res["scenario"]["initiatives"]["init-001"]
    assert [x["costs"] for x in blk["cash_flow"]] == ["1000.00", "50.00", "50.00"] and blk["npv"]["label"] == "estimate" and res["label"] == "estimate"
    rows = conn.execute("SELECT period_index, amount::text AS a, cost_id FROM expanded_costs WHERE scenario_id = 'scn-new' ORDER BY period_index, cost_id").fetchall()
    assert [(x["period_index"], x["a"]) for x in rows] == [(0, "1000.000000"), (1, "50.000000"), (2, "50.000000")]
    assert conn.execute("SELECT status, created_by FROM scenario_versions WHERE scenario_id = 'scn-new'").fetchone() == {"status": "draft", "created_by": "usr-analyst01"}
    assert "ESTIMATE" in [w["code"] for w in r.json()["warnings"]]
    # the stored rows reproduce the same model through the read path
    m = metrics(lab, scenario_id="scn-new", as_of="2028-06-30T00:00:00Z")["data"]["metrics"]["scenarios"]["scn-new"]["initiatives"]["init-001"]
    assert m["npv"] == blk["npv"] and m["cash_flow"] == blk["cash_flow"]


def test_c03_records_assumptions_as_versions_with_the_actor_as_author_and_pins_them(lab, conn):
    inp = {**SCN, "scenario_id": "scn-ramp", "pinned_assumption_ids": ["a-101-t1"], "assumptions": [
        {"initiative_id": "init-001", "name": "adoption_ramp", "values": ["0.250000", "1.000000"], "rationale": "phased rollout"},
        {"initiative_id": "init-001", "name": "target_minutes_per_case", "value": "7", "rationale": "second pilot"}],
        "benefits": [{"initiative_id": "init-001", "benefit_type": "cash", "amount": "200.00", "period_index": 1, "starts_period": 1}]}
    r = command(lab, "build-cash-flows", inp, headers=ANALYST)
    assert r.status_code == 200, r.text
    rows = conn.execute("SELECT name, version_number, author_id, value, value_list, cw_iso(created_at) AS c FROM assumption_versions WHERE initiative_id = 'init-001' ORDER BY name, version_number").fetchall()
    assert [(x["name"], x["version_number"], x["author_id"]) for x in rows] == [("adoption_ramp", 1, "usr-analyst01"), ("target_minutes_per_case", 1, "analyst-1"),
                                                                              ("target_minutes_per_case", 2, "usr-analyst01")]      # 7 is version 2 of the target; the author is the actor
    assert r.json()["result"]["scenario"]["initiatives"]["init-001"]["cash_flow"][1]["cash_benefits"] == "200.00"      # (the new 200 + the fixture's 600) x ramp idx 0 = 0.25: the unpinned latest ramp
    again = command(lab, "build-cash-flows", {**inp, "scenario_id": "scn-ramp-2", "assumptions": [{"initiative_id": "init-001", "name": "adoption_ramp", "version_number": 1,
                                                                                                    "values": ["1.000000"], "rationale": "overwrite"}]})
    assert again.status_code == 409 and rule_ids(again) == ["VERSION_EXISTS"]                            # an assumption version is never overwritten


@pytest.mark.parametrize("patch,status,rules", [
    ({"rate_basis": "monthly"}, 422, ["RATE_PERIOD_MISMATCH"]),
    ({"benefits": [{"initiative_id": "init-002", "benefit_type": "cash", "amount": "10.00", "period_index": 1, "starts_period": 0}]}, 422, ["BENEFIT_BEFORE_DEPLOYMENT"]),
    ({"costs": [{"initiative_id": "init-001", "cost_key": "ck-101-licence", "cost_type": "one_time", "amount": "10.00", "period_index": 2}]}, 422, ["ONE_TIME_COST_REPEATED"]),
    ({"benefits": [{"initiative_id": "init-001", "benefit_type": "capacity", "amount": "10.00", "period_index": 1, "starts_period": 1, "cash_realisation": True}]}, 422,
     ["CAPACITY_WITHOUT_CONVERSION"]),
    ({"horizon_periods": 0}, 422, ["INVALID_HORIZON"]), ({"scenario_id": "scn-001"}, 409, ["DUPLICATE_ID"]), ({"status": "funded"}, 422, ["FIELD_UNEXPECTED"]),
    ({"discount_rate": 0.1}, 422, ["FIELD_INVALID"]), ({"discount_rate": "1e-1"}, 422, ["DECIMAL_INVALID"]), ({"initiative_ids": ["init-404"]}, 404, ["UNKNOWN_INITIATIVE"]),
    ({"costs": [{"initiative_id": "init-001", "cost_key": "k", "cost_type": "recurring", "amount": "1.00", "start_period": 3, "end_period": 3}]}, 422, ["INVALID_PERIOD"])])
def test_c03_hard_validation_writes_nothing(lab, conn, patch, status, rules):
    r = refused(lab, conn, "build-cash-flows", {**SCN, **patch}, status, rules[0])
    assert set(rules) <= set(rule_ids(r))


def test_c03_reports_every_rejected_row_together(lab, conn):
    inp = {**SCN, "rate_basis": "monthly", "costs": [{"initiative_id": "init-001", "cost_key": "ck-101-licence", "cost_type": "one_time", "amount": "10.00", "period_index": 2}],
           "benefits": [{"initiative_id": "init-001", "benefit_type": "cash", "amount": "5.00", "period_index": 0, "starts_period": 0}]}
    r = refused(lab, conn, "build-cash-flows", inp, 422, "RATE_PERIOD_MISMATCH")
    assert sorted(rule_ids(r)) == ["BENEFIT_BEFORE_DEPLOYMENT", "ONE_TIME_COST_REPEATED", "RATE_PERIOD_MISMATCH"]
    assert {d["path"] for d in r.json()["error"]["details"]} == {"input", "input.costs[0]", "input.benefits[0]"}


def test_c03_capacity_is_cash_only_with_a_recorded_conversion_in_the_same_request(lab, conn):
    inp = {**SCN, "scenario_id": "scn-cap", "pinned_assumption_ids": [], "assumptions": [{"initiative_id": "init-001", "name": "capacity_hourly_rate", "value": "30.00", "unit": "USD/hour",
                                                                                         "rationale": "loaded rate", "staffing_change_evidence_ref": "hr:headcount-plan-2028"}],
           "benefits": [{"initiative_id": "init-001", "benefit_type": "capacity", "amount": "10.00", "period_index": 1, "starts_period": 1, "cash_realisation": True}]}
    r = command(lab, "build-cash-flows", inp)
    assert r.status_code == 200, r.text
    blk = r.json()["result"]["scenario"]["initiatives"]["init-001"]
    new = [x for x in blk["converted_capacity"] if x["hours"] == "10.00"][0]                     # the fixture's own 400 hours at period 1 are converted at the new rate too
    assert new["amount"] == "300.00" and new["hourly_rate"] == "30.00" and blk["cash_flow"][1]["benefits_by_class"]["capacity_converted"] == "12300.00"
    assert new["staffing_change_evidence_ref"] == "hr:headcount-plan-2028" and new["conversion_assumption_id"].startswith("as-")
    # scn-001 pins nothing for that rate, so its unpinned latest conversion now applies to init-001 as well: the model says so through the read path
    assert metrics(lab, as_of="2028-06-30T00:00:00Z")["data"]["metrics"]["scenarios"]["scn-cap"]["initiatives"]["init-001"]["converted_capacity"]


def test_c03_monthly_scenario_with_a_recorded_conversion(client, conn):
    d = golden_inputs("variant-rejected")
    load(conn, d, dataset_version="ds-rej")
    clock.freeze(NOW)
    inp = {"scenario_id": "rs-new", "baseline_version": "v1", "discount_rate": "0.100000", "rate_basis": "annual", "horizon_periods": 4, "initiative_ids": ["rj-i2"]}
    r = command(client, "build-cash-flows", inp)
    assert r.status_code == 422 and rule_ids(r) == ["RATE_PERIOD_MISMATCH"]
    ok = command(client, "build-cash-flows", {**inp, "rate_conversion_assumption_id": "ra-conv"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["result"]["scenario"]["effective_period_rate"] == "0.007974" and ok.json()["result"]["scenario"]["rate_source"] == "conversion:ra-conv"


# ------------------------------------------------------------------------------------------------------------ C04 map-impacts
def test_c04_maps_operating_changes_to_synthetic_groups(lab, conn):
    inp = {"initiative_id": "init-002", "groups": [{"group_id": "grp-9", "group_name": "Onboarding coaches", "owner_id": "sp-ops", "affected_count": 12, "impact_level": "medium"}],
           "mappings": [{"group_id": "grp-9", "operating_change": "A new checklist replaces the welcome call", "impact_level": "medium"},
                        {"group_id": "grp-003", "operating_change": "Buyers receive onboarding status", "impact_level": "low"}]}
    r = command(lab, "map-impacts", inp, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["groups_created"] == ["grp-9"] and res["total_mappings"] == 2 and res["total_affected_count"] == 37 and res["by_impact_level"] == {"medium": 1, "low": 1}
    assert [g["group_id"] for g in res["groups_affected"]] == ["grp-003", "grp-9"] and res["labels"] == "synthetic"
    assert count(conn, "impact_mappings", "initiative_id = 'init-002'") == 2 and len(audit(conn, "map-impacts", "init-002")) == 1


@pytest.mark.parametrize("patch,status,rule", [
    ({"mappings": [{"group_id": "grp-001", "operating_change": "  ", "impact_level": "low"}]}, 422, "OPERATING_CHANGE_REQUIRED"),
    ({"mappings": [{"group_id": "grp-404", "operating_change": "x", "impact_level": "low"}]}, 422, "UNKNOWN_GROUP"),
    ({"mappings": [{"group_id": "grp-001", "operating_change": "x", "impact_level": "enormous"}]}, 422, "INVALID_IMPACT_LEVEL"),
    ({"groups": [{"group_id": "grp-9", "group_name": "maria.lopez@example.com", "owner_id": "o", "affected_count": 1, "impact_level": "low"}],
      "mappings": [{"group_id": "grp-9", "operating_change": "x", "impact_level": "low"}]}, 422, "LABEL_NOT_SYNTHETIC"),
    ({"groups": [{"group_id": "grp-9", "group_name": "Call 5551234567", "owner_id": "o", "affected_count": 1, "impact_level": "low"}],
      "mappings": [{"group_id": "grp-9", "operating_change": "x", "impact_level": "low"}]}, 422, "LABEL_NOT_SYNTHETIC"),
    ({"groups": [{"group_id": "grp-001", "group_name": "Duplicate", "owner_id": "o", "affected_count": 1, "impact_level": "low"}]}, 409, "DUPLICATE_ID"),
    ({"initiative_id": "init-404"}, 404, "UNKNOWN_INITIATIVE"), ({"mappings": []}, 422, "FIELD_INVALID")])
def test_c04_hard_validation(lab, conn, patch, status, rule):
    base = {"initiative_id": "init-002", "mappings": [{"group_id": "grp-001", "operating_change": "x", "impact_level": "low"}]}
    refused(lab, conn, "map-impacts", {**base, **patch}, status, rule)


# ------------------------------------------------------------------------------------------------------------ C05 assess-readiness
def test_c05_records_dimension_assessments_stamped_by_the_server_and_returns_the_readiness(lab, conn):
    r = command(lab, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "awareness", "score": 4}, {"dimension": "desire", "score": 2, "weight": "3.00"}]}, headers=ANALYST)
    assert r.status_code == 200, r.text
    snap = r.json()["result"]["readiness"]
    assert snap["readiness_score"] == "2.5000" and snap["readiness_exact"] == "5/2" and snap["label"] == "assessment, not a probability" and snap["dimensions_assessed"] == 2
    rows = conn.execute("SELECT dimension, score, weight::text AS w, cw_iso(assessed_at) AS at, assessed_by FROM readiness_assessments WHERE group_id = 'grp-003' ORDER BY dimension").fetchall()
    assert [(x["dimension"], x["score"], x["w"], x["assessed_by"]) for x in rows] == [("awareness", 4, "1.000000", "usr-analyst01"), ("desire", 2, "3.000000", "usr-analyst01")]
    assert rows[0]["at"].startswith("2028-07-01T12:00:00")
    assert r.json()["warnings"][0]["code"] == "ASSESSMENT_NOT_PROBABILITY"
    later = command(lab, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "awareness", "score": 1}]}).json()["result"]["readiness"]
    assert later["readiness_score"] == "1.7500" and count(conn, "readiness_assessments", "group_id = 'grp-003'") == 3        # the later score supersedes, the earlier stays


@pytest.mark.parametrize("patch,status,rule", [
    ({"assessments": [{"dimension": "awareness", "score": 6}]}, 422, "INVALID_SCORE"), ({"assessments": [{"dimension": "awareness", "score": 0}]}, 422, "INVALID_SCORE"),
    ({"assessments": [{"dimension": "enthusiasm", "score": 3}]}, 422, "INVALID_DIMENSION"), ({"assessments": [{"dimension": "desire", "score": 3, "weight": "0.00"}]}, 422, "INVALID_WEIGHT"),
    ({"assessments": [{"dimension": "desire", "score": 3}, {"dimension": "desire", "score": 4}]}, 422, "DUPLICATE_DIMENSION"), ({"group_id": "grp-404"}, 404, "UNKNOWN_GROUP"),
    ({"assessments": [{"dimension": "desire", "score": 3, "assessed_at": "2020-01-01T00:00:00Z"}]}, 422, "FIELD_UNEXPECTED"),
    ({"assessments": [{"dimension": "desire", "score": 3.5}]}, 422, "FIELD_INVALID")])
def test_c05_hard_validation(lab, conn, patch, status, rule):
    refused(lab, conn, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}], **patch}, status, rule)


# ------------------------------------------------------------------------------------------------------------ C06 plan-roadmap
def test_c06_plans_a_feasible_schedule_and_shows_dependency_and_resource_views(lab, conn):
    inp = {"schedule": [{"initiative_id": "init-001", "requested_start_period": 1, "duration_periods": 1, "expected_version": 1}],
           "allocations": [{"resource_id": "res-001", "initiative_id": "init-001", "period_index": 1, "amount": "0.50"}]}
    r = command(lab, "plan-roadmap", inp, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["changed_initiatives"] == ["init-001"] and r.json()["version"] == 2
    assert (res["schedule"]["init-001"]["dependency_feasible_start"], res["schedule"]["init-002"]["dependency_feasible_start"], res["schedule"]["init-002"]["dependency_delay"]) == (1, 3, 3)
    assert res["schedule"]["init-003"]["dependency_feasible_start"] == 4 and res["schedule"]["init-003"]["binding_dependency_id"] == "d-2"
    assert res["resources"]["res-001"]["by_period"][1] == {"period_index": 1, "allocated": "0.50", "headroom": "1.50"}
    assert conn.execute("SELECT requested_start_period, version FROM initiatives WHERE initiative_id = 'init-001'").fetchone() == {"requested_start_period": 1, "version": 2}
    assert len(audit(conn, "plan-roadmap")) == 2          # one for the changed initiative, one for the plan
    assert get(lab, "/metrics", as_of="2028-06-30T00:00:00Z").json()["data"]["metrics"]["initiatives"]["init-002"]["roadmap"]["dependency_delay"] == 3


def test_c06_a_cycle_is_refused_with_the_cycle_listed(lab, conn):
    r = refused(lab, conn, "plan-roadmap", {"dependencies": [{"initiative_id": "init-001", "prerequisite_id": "init-003", "dependency_type": "finish_to_start"}]}, 422, "DEPENDENCY_CYCLE")
    assert r.json()["error"]["details"][0]["context"]["cycle"] == ["init-001", "init-003", "init-001"]       # init-003 also needs init-001 directly (d-3): the shortest way back is reported
    ok = command(lab, "plan-roadmap", {"dependencies": [{"initiative_id": "init-003", "prerequisite_id": "init-001", "dependency_type": "finish_to_start", "lag_periods": 5}]})
    assert ok.status_code == 200 and ok.json()["result"]["schedule"]["init-003"]["dependency_feasible_start"] == 6 and ok.json()["result"]["schedule"]["init-003"]["binding_dependency_id"] != "d-2"


def test_c06_shared_capacity_is_checked_and_the_whole_command_rolls_back(lab, conn):
    inp = {"schedule": [{"initiative_id": "init-003", "requested_start_period": 2, "duration_periods": 1}],
           "allocations": [{"resource_id": "res-001", "initiative_id": "init-003", "period_index": 3, "amount": "0.01"}]}      # period 3 is exactly at capacity (2.00)
    r = refused(lab, conn, "plan-roadmap", inp, 422, "RESOURCE_OVERALLOCATED")
    assert r.json()["error"]["details"][0]["context"] == {"resource_id": "res-001", "periods": [3], "allocated_before": "2.00", "requested": "0.01", "capacity": "2.00"}
    assert conn.execute("SELECT requested_start_period, version FROM initiatives WHERE initiative_id = 'init-003'").fetchone() == {"requested_start_period": 0, "version": 1}   # not shifted
    ok = command(lab, "plan-roadmap", {"allocations": [{"resource_id": "res-001", "initiative_id": "init-003", "period_index": 1, "amount": "2.00"}]})      # exactly at capacity: allowed
    assert ok.status_code == 200 and ok.json()["result"]["resources"]["res-001"]["by_period"][1]["headroom"] == "0.00"


def test_c06_new_resources_and_unknown_things(lab, conn):
    ok = command(lab, "plan-roadmap", {"resources": [{"resource_id": "res-9", "name": "Change coaches", "capacity_per_period": "3.00", "unit": "FTE"}],
                                       "allocations": [{"resource_id": "res-9", "initiative_id": "init-001", "period_index": 0, "amount": "3.00"}]})
    assert ok.status_code == 200 and count(conn, "resource_allocations", "resource_id = 'res-9'") == 1
    refused(lab, conn, "plan-roadmap", {"allocations": [{"resource_id": "res-404", "initiative_id": "init-001", "period_index": 0, "amount": "1.00"}]}, 422, "UNKNOWN_RESOURCE")
    refused(lab, conn, "plan-roadmap", {"schedule": [{"initiative_id": "init-404", "requested_start_period": 0, "duration_periods": 1}]}, 404, "UNKNOWN_INITIATIVE")
    refused(lab, conn, "plan-roadmap", {"schedule": [{"initiative_id": "init-001", "requested_start_period": 0, "duration_periods": 1, "expected_version": 5}]}, 409, "STALE_VERSION")
    refused(lab, conn, "plan-roadmap", {}, 422, "NOTHING_TO_PLAN")
    refused(lab, conn, "plan-roadmap", {"dependencies": [{"initiative_id": "init-001", "prerequisite_id": "init-001", "dependency_type": "finish_to_start"}]}, 422, "DEPENDENCY_CYCLE")


# ------------------------------------------------------------------------------------------------------------ C07 select-scenario
def test_c07_proposes_only_never_funds_and_needs_the_residual_explained(lab, conn):
    funded = refused(lab, conn, "select-scenario", {"scenario_id": "scn-001", "status": "funded"}, 422, "STATUS_NOT_ALLOWED")
    assert "is not a status of this product" in funded.text
    r = command(lab, "select-scenario", {"scenario_id": "scn-001"})
    assert r.status_code == 422 and rule_ids(r) == ["DOUBLE_COUNT_UNEXPLAINED"]
    ctx = r.json()["error"]["details"][0]["context"]
    assert ctx["residual"] == "75.00" and ctx["overlaps"][0]["benefit_source_key"] == "cost-line:CC-4410"
    assert len(audit(conn, "select-scenario-refused", "scn-001")) == 1 and conn.execute("SELECT status FROM scenario_versions").fetchone()["status"] == "draft"
    ok = command(lab, "select-scenario", {"scenario_id": "scn-001", "residual_explanation": "CC-4410 is claimed by two initiatives; counted once at the larger claim"})
    assert ok.status_code == 200, ok.text
    res = ok.json()["result"]
    assert (ok.json()["status"], res["status"], res["funded"], res["proposed_by"], res["double_count"]["residual"]) == ("proposed", "proposed", False, "usr-sponsor01", "75.00")
    assert {w["code"] for w in ok.json()["warnings"]} == {"PROPOSAL_NOT_FUNDING", "RESIDUAL_EXPLAINED"}
    row = conn.execute("SELECT status, proposed_by, residual_explanation, comparison, cw_iso(proposed_at) AS p FROM scenario_versions").fetchone()
    assert (row["status"], row["proposed_by"]) == ("proposed", "usr-sponsor01") and row["p"].startswith("2028-07-01T12:00:00")
    assert row["comparison"]["scenarios"]["scn-001"]["npv_total"]["value"] == "-754.55" and row["comparison"]["label"] == "estimates"      # R9-02: the attributable total
    assert row["comparison"]["scenarios"]["scn-001"]["npv_total"]["sum_of_initiatives"] == "-692.56" and len(row["comparison"]["snapshot_hash"]) == 64
    assert len(audit(conn, "select-scenario", "scn-001")) == 1
    assert get(lab, "/data/scenario_versions").json()["data"][0]["status"] == "proposed"


def test_c07_an_explanation_needs_twenty_characters_and_the_hours_residual_needs_one_too(lab, conn):
    """R9-22 and R9-03: 'x' explains nothing; a scenario whose only residual is in hours is refused without an explanation as well."""
    r = refused(lab, conn, "select-scenario", {"scenario_id": "scn-001", "residual_explanation": "too short to say"}, 422, "EXPLANATION_TOO_SHORT")
    assert r.json()["error"]["details"][0]["context"] == {"minimum": 20, "length": 16}
    refused(lab, conn, "select-scenario", {"scenario_id": "scn-001", "residual_explanation": "          x          "}, 422, "EXPLANATION_TOO_SHORT")        # stripped first
    hours = command(lab, "build-cash-flows", {**SCN, "scenario_id": "scn-hours", "initiative_ids": ["init-001", "init-002"], "benefits": [
        {"initiative_id": "init-001", "benefit_type": "capacity", "amount": "40.00", "period_index": 2, "starts_period": 1, "benefit_source_key": "team:ap"},
        {"initiative_id": "init-002", "benefit_type": "capacity", "amount": "60.00", "period_index": 2, "starts_period": 1, "benefit_source_key": "team:ap"}]}, headers=ANALYST)
    assert hours.status_code == 200, hours.text
    dc = hours.json()["result"]["scenario"]["double_count"]
    assert (dc["residual"], dc["hours_residual"], dc["explanation_required"], dc["explanation_required_for"]) == ("0.00", "40.00", True, ["hours"])
    r = refused(lab, conn, "select-scenario", {"scenario_id": "scn-hours"}, 422, "DOUBLE_COUNT_UNEXPLAINED", audited=True)
    assert r.json()["error"]["details"][0]["context"]["hours_residual"] == "40.00" and r.json()["error"]["details"][0]["context"]["hours_overlaps"][0]["benefit_source_key"] == "team:ap"
    ok = command(lab, "select-scenario", {"scenario_id": "scn-hours", "residual_explanation": "The AP team's hours are claimed by both initiatives; counted once"})
    assert ok.status_code == 200 and ok.json()["result"]["double_count"]["hours_residual"] == "40.00"


def test_c07_a_proposal_is_final_and_a_scenario_without_overlap_needs_no_explanation(lab, conn):
    clean = command(lab, "build-cash-flows", {**SCN, "scenario_id": "scn-clean"}, headers=ANALYST)
    assert clean.json()["result"]["scenario"]["double_count"]["residual"] == "0.00"
    ok = command(lab, "select-scenario", {"scenario_id": "scn-clean", "compared_scenario_ids": ["scn-001"]})
    assert ok.status_code == 200 and ok.json()["result"]["comparison"]["compared_scenario_ids"] == ["scn-001", "scn-clean"]
    assert set(ok.json()["result"]["comparison"]["scenarios"]) == {"scn-001", "scn-clean"} and ok.json()["warnings"][0]["code"] == "PROPOSAL_NOT_FUNDING"
    again = command(lab, "select-scenario", {"scenario_id": "scn-clean"})
    assert again.status_code == 409 and rule_ids(again) == ["ALREADY_PROPOSED"]
    refused(lab, conn, "select-scenario", {"scenario_id": "nope"}, 404, "UNKNOWN_SCENARIO")
    refused(lab, conn, "select-scenario", {"scenario_id": "scn-001", "compared_scenario_ids": ["nope"], "residual_explanation": "x"}, 404, "UNKNOWN_SCENARIO")
    with pytest.raises(Exception, match="SCENARIO_IMMUTABLE"):
        conn.execute("UPDATE scenario_versions SET status = 'draft', proposed_at = NULL WHERE scenario_id = 'scn-clean'")


def test_c07_needs_a_sponsor_or_admin_and_refuses_before_reading_the_body(lab):
    r = command(lab, "select-scenario", {"scenario_id": "scn-001", "residual_explanation": "x"}, headers=ANALYST)
    assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"]
    assert lab.post(f"{PREFIX}/commands/select-scenario", json={"junk": 1}, headers=ANALYST).status_code == 403
    assert command(lab, "select-scenario", {"scenario_id": "scn-001", "residual_explanation": "CC-4410 is claimed twice and counted once"}, headers=ADMIN).status_code == 200


# ------------------------------------------------------------------------------------------------------------ C08 record-adoption
def test_c08_records_an_observation_with_its_denominator_and_keeps_training_apart(lab, conn):
    inp = {"initiative_id": "init-001", "eligible_count": 40, "adopted_count": 36, "eligibility_rule_version": "elig-v1", "observed_on": "2028-06-15",
           "training": {"eligible_trainees": 40, "completed": 40}}
    r = command(lab, "record-adoption", inp, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (res["adoption_rate"], res["eligible_count"], res["adopted_count"], res["observed_at"]) == ("0.900000", 40, 36, "2028-06-15T00:00:00Z")
    assert res["training"]["training_completion"] == "1.000000" and res["training"]["substituted_for_adoption"] is False and res["training_is_not_adoption"] is True
    assert [s["adoption_rate"] for s in res["series"]] == ["0.250000", "0.750000", "0.900000"]            # ad-1, ad-2, the new one; ad-3 is after as_of
    assert conn.execute("SELECT recorded_by, eligible_count FROM adoption_observations WHERE observation_id = %s", (res["observation_id"],)).fetchone() == {"recorded_by": "usr-analyst01", "eligible_count": 40}


def test_c08_hard_validation_denominator_rule_version_and_instants(lab, conn):
    base = {"initiative_id": "init-001", "eligible_count": 40, "adopted_count": 30, "eligibility_rule_version": "elig-v1"}
    refused(lab, conn, "record-adoption", {**base, "adopted_count": 41}, 422, "ADOPTED_EXCEEDS_ELIGIBLE")
    refused(lab, conn, "record-adoption", {**base, "eligibility_rule_version": "elig-v2"}, 422, "ELIGIBILITY_RULE_MISMATCH")
    refused(lab, conn, "record-adoption", {**base, "training": {"eligible_trainees": 40, "completed": 41}}, 422, "COMPLETED_EXCEEDS_ELIGIBLE")
    refused(lab, conn, "record-adoption", {**base, "observed_at": "2028-06-01T00:00:00Z"}, 422, "FIELD_UNEXPECTED")
    refused(lab, conn, "record-adoption", {**base, "observed_on": "2029-01-01"}, 422, "DATE_IN_FUTURE")
    refused(lab, conn, "record-adoption", {**base, "adopted_count": -1}, 422, "FIELD_INVALID")
    refused(lab, conn, "record-adoption", {**base, "initiative_id": "init-404"}, 404, "UNKNOWN_INITIATIVE")
    zero = command(lab, "record-adoption", {**base, "eligible_count": 0, "adopted_count": 0, "initiative_id": "init-003"})
    assert zero.status_code == 200 and zero.json()["result"]["adoption_rate"] is None and zero.json()["warnings"][0]["code"] == "ZERO_ELIGIBLE"


# ------------------------------------------------------------------------------------------------------------ C09 track-benefits
TRACK = {"benefit_id": "b-101", "measured_value": "520.00", "unit": "USD", "evidence_ref": "ev:ap-ledger-2028-05", "observed_on": "2028-05-31"}


def test_c09_compares_within_the_benefit_type_and_never_attributes(lab, conn):
    r = command(lab, "track-benefits", TRACK, headers=ANALYST)
    assert r.status_code == 200, r.text
    cmp_ = r.json()["result"]["comparisons"]["scn-001"]
    assert (cmp_["unit"], cmp_["planned_comparable"], cmp_["observed_comparable"], cmp_["realization"], cmp_["baseline_trend"], cmp_["observed_above_trend"], cmp_["attribution"]) == (
        "USD", "600.00", "520.00", "0.866667", "50.00", "470.00", "observed, not attributed")         # the raw 520 stays beside the above-trend 470
    assert r.json()["result"]["attribution"] == "observed, not attributed" and r.json()["warnings"][0]["code"] == "OBSERVED_NOT_ATTRIBUTED"
    assert "capacity" not in str(r.json()["result"]["comparisons"]["scn-001"]["comparable_items"]) and r.json()["result"]["forecast"]["observed"][0]["benefit_id"] == "b-101"
    assert conn.execute("SELECT measured_value::text AS v, recorded_by, cw_iso(observed_at) AS o FROM benefit_observations WHERE benefit_observation_id = %s",
                        (r.json()["result"]["benefit_observation_id"],)).fetchone() == {"v": "520.000000", "recorded_by": "usr-analyst01", "o": "2028-05-31T00:00:00Z"}


def test_c09_hours_are_a_different_type_and_an_unmatured_period_is_kept_but_not_compared(lab, conn):
    r = refused(lab, conn, "track-benefits", {**TRACK, "benefit_id": "b-103", "unit": "USD"}, 422, "BENEFIT_TYPE_MISMATCH")
    assert r.json()["error"]["details"][0]["context"] == {"benefit_type": "capacity", "unit": "hours"}
    ok = command(lab, "track-benefits", {**TRACK, "benefit_id": "b-103", "unit": "hours", "measured_value": "390.00"})
    assert ok.status_code == 200 and ok.json()["result"]["comparisons"]["scn-001"]["unit"] == "hours" and ok.json()["result"]["comparisons"]["scn-001"]["realization"] == "0.975000"
    late = command(lab, "track-benefits", {**TRACK, "benefit_id": "b-102", "observed_on": "2028-06-30"})         # period 2 ends 2029-01-01
    assert late.status_code == 200 and "PERIOD_NOT_MATURED" in [w["code"] for w in late.json()["warnings"]]
    assert late.json()["result"]["comparisons"]["scn-001"]["comparable_items"] == ["b-101"]
    assert "NO_BASELINE_TREND" in [w["code"] for w in ok.json()["warnings"]]


@pytest.mark.parametrize("patch,status,rule", [
    ({"attribution": "rollout_caused"}, 422, "ATTRIBUTION_NOT_ESTABLISHED"), ({"attribution": "full"}, 422, "ATTRIBUTION_NOT_ESTABLISHED"), ({"evidence_ref": " "}, 422, "EVIDENCE_REQUIRED"),
    ({"benefit_id": "b-404"}, 404, "UNKNOWN_BENEFIT"), ({"measured_value": "-5.00"}, 422, "INVALID_AMOUNT"), ({"measured_value": 520}, 422, "FIELD_INVALID"),
    ({"observed_at": "2028-05-31T00:00:00Z"}, 422, "FIELD_UNEXPECTED"), ({"observed_on": "2030-01-01"}, 422, "DATE_IN_FUTURE")])
def test_c09_hard_validation(lab, conn, patch, status, rule):
    refused(lab, conn, "track-benefits", {**TRACK, **patch}, status, rule)


# ------------------------------------------------------------------------------------------------------------ C10 revise-forecast
REVISE = {"initiative_id": "init-001", "reason": "Observed shortfall again", "expected_version": 2,
          "periods": [{"period_index": 1, "amount": "450.00"}, {"period_index": 2, "amount": "500.00"}]}


def test_c10_creates_version_n_plus_1_and_never_touches_the_original(lab, conn):
    before = conn.execute("SELECT * FROM forecast_versions WHERE version_number = 1 ORDER BY forecast_id").fetchall()
    r = command(lab, "revise-forecast", REVISE)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (res["version_number"], res["original_version"], res["original_preserved"], res["total"], res["latest_minus_original"]) == (3, 1, True, "950.00", "-250.00")
    assert r.json()["version"] == 3 and [v["version_number"] for v in res["forecast"]["versions"]] == [1, 2, 3]
    assert res["forecast"]["versions"][0]["total"] == "1200.00" and res["forecast"]["versions"][1]["total"] == "980.00"
    assert conn.execute("SELECT * FROM forecast_versions WHERE version_number = 1 ORDER BY forecast_id").fetchall() == before
    row = conn.execute("SELECT created_by, cw_iso(created_at) AS c FROM forecast_versions WHERE version_number = 3 LIMIT 1").fetchone()
    assert row["created_by"] == "usr-sponsor01" and row["c"].startswith("2028-07-01T12:00:00")
    assert len(audit(conn, "revise-forecast", "init-001:v3")) == 1 and audit(conn, "revise-forecast", "init-001:v3")[0]["before_version"] == 2


def test_c10_the_first_forecast_is_the_original_and_an_overwrite_is_impossible(lab, conn):
    first = command(lab, "revise-forecast", {"initiative_id": "init-002", "reason": "Approved forecast", "expected_version": 0, "periods": [{"period_index": 1, "amount": "200.00"}]}, headers=ADMIN)
    assert first.status_code == 200 and first.json()["result"]["version_number"] == 1 and first.json()["warnings"][0]["code"] == "FIRST_FORECAST"
    refused(lab, conn, "revise-forecast", {**REVISE, "version_number": 1}, 422, "FIELD_UNEXPECTED")                    # there is no way to name a version to replace
    with pytest.raises(Exception, match="FORECAST_OVERWRITE"):
        conn.execute("UPDATE forecast_versions SET amount = 1 WHERE initiative_id = 'init-001' AND version_number = 1")
    with pytest.raises(Exception, match="FORECAST_OVERWRITE"):
        conn.execute("DELETE FROM forecast_versions WHERE initiative_id = 'init-001' AND version_number = 1")


@pytest.mark.parametrize("patch,status,rule", [
    ({"expected_version": 1}, 409, "STALE_FORECAST_VERSION"), ({"reason": "  "}, 422, "REASON_REQUIRED"), ({"periods": []}, 422, "FIELD_INVALID"),
    ({"periods": [{"period_index": 1, "amount": "1.00"}, {"period_index": 1, "amount": "2.00"}]}, 422, "DUPLICATE_PERIOD"), ({"periods": [{"period_index": 1, "amount": "-1.00"}]}, 422, "INVALID_AMOUNT"),
    ({"periods": [{"period_index": -1, "amount": "1.00"}]}, 422, "FIELD_INVALID"), ({"initiative_id": "init-404"}, 404, "UNKNOWN_INITIATIVE"),
    ({"created_at": "2028-01-01T00:00:00Z"}, 422, "FIELD_UNEXPECTED")])
def test_c10_hard_validation(lab, conn, patch, status, rule):
    refused(lab, conn, "revise-forecast", {**REVISE, **patch}, status, rule)


def test_c10_needs_a_sponsor_or_admin(lab):
    assert command(lab, "revise-forecast", REVISE, headers=ANALYST).status_code == 403


# ------------------------------------------------------------------------------------------------------------ envelope, roles, idempotency
def test_identity_roles_and_envelope_errors(lab):
    body = {"request_id": "r1", "dataset_version": "ds-golden", "idempotency_key": "k1", "input": {"initiative_id": "init-003", "criteria": CRIT, "rationale": "x"}}
    assert lab.post(f"{PREFIX}/commands/assess-opportunity", json=body).status_code == 401
    assert lab.post(f"{PREFIX}/commands/assess-opportunity", json=body, headers={"X-Actor-Id": "u", "X-Actor-Role": "root"}).status_code == 403
    assert lab.post(f"{PREFIX}/commands/assess-opportunity", json=body, headers={"X-Actor-Id": "u", "X-Actor-Role": "steward"}).status_code == 403          # another app's role
    assert lab.post(f"{PREFIX}/commands/assess-opportunity", json=body, headers={"X-Actor-Id": " ", "X-Actor-Role": "admin"}).status_code == 401
    unsupported = lab.post(f"{PREFIX}/commands/nothing", json=body, headers=ADMIN)                                                                  # an unsupported action
    assert unsupported.status_code == 404 and rule_ids(unsupported) == ["UNSUPPORTED_ACTION"] and unsupported.json()["error"]["code"] == "UNSUPPORTED_ACTION"
    assert lab.get(f"{PREFIX}/commands/assess-opportunity").status_code == 405
    assert lab.post(f"{PREFIX}/commands/assess-opportunity", json=body, headers=ANALYST).status_code == 200
    bad = lab.post(f"{PREFIX}/commands/assess-opportunity", json={"request_id": "r9", "idempotency_key": "k 1", "input": {"initiative_id": "i", "extra": 1}}, headers=ADMIN)
    assert bad.status_code == 422 and bad.json()["request_id"] == "r9"
    assert {"FIELD_REQUIRED", "IDEMPOTENCY_KEY_INVALID", "FIELD_UNEXPECTED"} <= set(rule_ids(bad))
    assert lab.post(f"{PREFIX}/commands/assess-opportunity", content=b"{not json", headers={**ADMIN, "content-type": "application/json"}).status_code == 422
    ok = lab.get(f"{PREFIX}/data/initiatives")
    assert ok.status_code == 200 and set(ok.json()) == {"data", "meta", "warnings"}                                                       # reads need no actor


def test_a_success_has_the_envelope_command_id_status_result_warnings_version(lab):
    r = command(lab, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]})
    assert set(r.json()) == {"command_id", "status", "result", "warnings", "version"} and r.json()["command_id"].startswith("cmd-")


def test_idempotency_replay_reuse_and_actor_binding(lab, conn):
    inp = {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]}
    first = command(lab, "assess-readiness", inp, key="idem-1", headers=ANALYST)
    n = count(conn, "readiness_assessments")
    replay = command(lab, "assess-readiness", inp, key="idem-1", headers=ANALYST)
    assert replay.status_code == 200 and replay.json() == first.json() and replay.headers["Idempotent-Replay"] == "true"
    assert count(conn, "readiness_assessments") == n and "Idempotent-Replay" not in first.headers and len(audit(conn, "assess-readiness")) == 1
    other_payload = command(lab, "assess-readiness", {**inp, "assessments": [{"dimension": "desire", "score": 4}]}, key="idem-1", headers=ANALYST)
    assert other_payload.status_code == 409 and rule_ids(other_payload) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]
    other_actor = command(lab, "assess-readiness", inp, key="idem-1", headers={"X-Actor-Id": "usr-other", "X-Actor-Role": "analyst"})
    assert other_actor.status_code == 409 and rule_ids(other_actor) == ["IDEMPOTENCY_ACTOR_MISMATCH"]
    other_role = command(lab, "assess-readiness", inp, key="idem-1", headers={"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "admin"})
    assert other_role.status_code == 409 and rule_ids(other_role) == ["IDEMPOTENCY_ACTOR_MISMATCH"]
    other_version = command(lab, "assess-readiness", inp, key="idem-1", headers=ANALYST, dataset_version="ds-other")
    assert other_version.status_code == 409                                              # a different dataset_version is a different request
    assert count(conn, "readiness_assessments") == n


def test_a_refused_command_does_not_burn_its_idempotency_key(lab, conn):
    bad = command(lab, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 9}]}, key="burn-1")
    assert bad.status_code == 422 and count(conn, "command_results", "idempotency_key = 'burn-1'") == 0
    ok = command(lab, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]}, key="burn-1")
    assert ok.status_code == 200 and count(conn, "command_results", "idempotency_key = 'burn-1'") == 1


def test_stale_dataset_version_is_409_and_nothing_is_written(lab, conn):
    before = table_digest(conn, NOTHING_WRITTEN)
    r = command(lab, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]}, dataset_version="ds-old")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_DATASET_VERSION" and rule_ids(r) == ["STALE_DATASET_VERSION"]
    assert r.json()["error"]["details"][0]["context"] == {"current": "ds-golden", "requested": "ds-old"}
    assert table_digest(conn, NOTHING_WRITTEN) == before
    assert command(lab, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]}, dataset_version="ds-golden").status_code == 200


def test_every_successful_command_writes_audit_rows_with_the_actor_and_request_id_and_a_failure_none(lab, conn):
    n0 = count(conn, "audit_events")
    assert command(lab, "assess-readiness", {"group_id": "grp-003", "assessments": [{"dimension": "desire", "score": 3}]}, headers=ANALYST, request_id="req-77").status_code == 200
    assert count(conn, "audit_events") == n0 + 1 and count(conn, "command_results") == 1
    assert command(lab, "assess-readiness", {"group_id": "grp-404", "assessments": [{"dimension": "desire", "score": 3}]}).status_code == 404
    assert count(conn, "audit_events") == n0 + 1 and count(conn, "command_results") == 1                  # the refusal stored nothing
    a = conn.execute("SELECT * FROM audit_events ORDER BY occurred_at DESC LIMIT 1").fetchone()
    assert (a["entity_type"], a["action"], a["actor_id"], a["actor_role"], a["request_id"]) == ("stakeholder_group", "assess-readiness", "usr-analyst01", "analyst", "req-77")
    assert a["occurred_at"] >= NOW


def test_values_with_more_than_two_decimals_survive_the_database_round_trip(lab, conn):
    """cw_dec keeps 3+ places (a regression: rpad truncated them)."""
    r = command(lab, "build-cash-flows", {**SCN, "scenario_id": "scn-dec", "costs": [{"initiative_id": "init-001", "cost_key": "fx", "cost_type": "one_time", "amount": "10.125", "period_index": 1}]})
    assert r.status_code == 200
    rows = get(lab, "/data/cost_items", initiative_id="init-001").json()["data"]
    assert "10.125" in [x["amount"] for x in rows] and "1000.00" in [x["amount"] for x in rows]
    cf = metrics(lab, scenario_id="scn-dec", as_of="2028-06-30T00:00:00Z")["data"]["metrics"]["scenarios"]["scn-dec"]["initiatives"]["init-001"]["cash_flow"]
    assert cf[1]["costs"] == "10.13"                                                                      # ROUND_HALF_UP at the declared step only


# ------------------------------------------------------------------------------------------------------------ review 9: the plan a scenario was built on (R9-01)
def test_a_proposed_scenario_keeps_its_figures_after_a_later_build_on_the_same_initiatives(lab, conn):
    """The reviewer's reproduction: propose scn-001, then build a second scenario that adds a cost, a capacity conversion and a slower ramp for init-001. The proposal's figures
    are the ones it was proposed on: its stored comparison, its snapshot hash and a fresh computation agree."""
    asof = "2028-07-02T00:00:00Z"
    before = metrics(lab, scenario_id="scn-001", as_of=asof)["data"]["metrics"]["scenarios"]["scn-001"]
    assert before["npv_total"]["value"] == "-754.55"
    ok = command(lab, "select-scenario", {"scenario_id": "scn-001", "residual_explanation": "CC-4410 is claimed by two initiatives; counted once at the larger claim"})
    assert ok.status_code == 200, ok.text
    stored = ok.json()["result"]["comparison"]["scenarios"]["scn-001"]
    sealed = ok.json()["result"]["snapshot_hash"]
    assert conn.execute("SELECT snapshot_hash FROM scenario_versions WHERE scenario_id = 'scn-001'").fetchone()["snapshot_hash"] == sealed
    later = command(lab, "build-cash-flows", {**SCN, "scenario_id": "scn-later", "assumptions": [
        {"initiative_id": "init-001", "name": "capacity_hourly_rate", "value": "30.00", "rationale": "converted after the proposal", "staffing_change_evidence_ref": "hr:plan-2028"},
        {"initiative_id": "init-001", "name": "adoption_ramp", "values": ["0.100000", "0.200000"], "rationale": "a slower ramp"}],
        "costs": [{"initiative_id": "init-001", "cost_key": "ck-new", "cost_type": "one_time", "amount": "5000.00", "period_index": 1}]}, headers=ANALYST)
    assert later.status_code == 200, later.text
    new = later.json()["result"]["scenario"]["initiatives"]["init-001"]
    assert new["npv"]["value"] != before["initiatives"]["init-001"]["npv"]["value"] and new["converted_capacity"] and new["ramp"]            # the new scenario does see them
    m = metrics(lab, scenario_id="scn-001", as_of=asof)
    after = m["data"]["metrics"]["scenarios"]["scn-001"]
    assert after["npv_total"] == stored["npv_total"] == before["npv_total"] and after["initiatives"]["init-001"]["npv"] == before["initiatives"]["init-001"]["npv"]
    assert after["initiatives"]["init-001"]["converted_capacity"] == [] and after["initiatives"]["init-001"]["ramp"] is None
    assert after["double_count"]["residual"] == stored["residual"] and after["initiatives"]["init-001"]["cash_flow"] == before["initiatives"]["init-001"]["cash_flow"]
    proof = m["data"]["proposals"]["scn-001"]
    assert proof["snapshot_verified"] is True and proof["snapshot_hash_stored"] == proof["snapshot_hash_now"] == sealed and proof["figures_equal_the_stored_comparison"] is True


def test_the_sets_of_a_scenario_are_sealed_by_the_database(lab, conn):
    """R9-01: once a scenario exists, no initiative and no pinned assumption can be added to it, whatever road the row takes."""
    for table, col, value in (("scenario_pins", "assumption_id", "a-201-t2"), ("scenario_initiatives", "initiative_id", "init-003")):
        with pytest.raises(Exception, match="SCENARIO_IMMUTABLE"):
            conn.execute(f"INSERT INTO {table} (scenario_id, {col}) VALUES ('scn-001', %s)", (value,))        # constants
    with pytest.raises(Exception, match="SCENARIO_IMMUTABLE"):
        conn.execute("UPDATE scenario_versions SET pins_expected = 9 WHERE scenario_id = 'scn-001'")
    assert count(conn, "scenario_pins", "scenario_id = 'scn-001'") == 3 and count(conn, "scenario_initiatives", "scenario_id = 'scn-001'") == 3
    ok = command(lab, "build-cash-flows", {**SCN, "scenario_id": "scn-sealed", "pinned_assumption_ids": ["a-201-t1"], "initiative_ids": ["init-001", "init-002"]}, headers=ANALYST)
    assert ok.status_code == 200 and count(conn, "scenario_pins", "scenario_id = 'scn-sealed'") == 1 and count(conn, "scenario_initiatives", "scenario_id = 'scn-sealed'") == 2


def test_plan_rows_and_observations_carry_the_servers_instant(lab, conn):
    """R9-01 and R9-11: every row the API writes to a plan or an observation says when the server recorded it, whatever date the caller gives."""
    r = command(lab, "build-cash-flows", {**SCN, "scenario_id": "scn-stamps", "costs": [{"initiative_id": "init-001", "cost_key": "ck-s", "cost_type": "one_time", "amount": "1.00", "period_index": 1}],
                                          "benefits": [{"initiative_id": "init-001", "benefit_type": "cash", "amount": "2.00", "period_index": 2, "starts_period": 1}]}, headers=ANALYST)
    assert r.status_code == 200, r.text
    served = lambda t: NOW <= t < NOW.replace(minute=1)           # the frozen clock steps by a millisecond per reading
    assert served(conn.execute("SELECT recorded_at FROM cost_items WHERE cost_key = 'ck-s'").fetchone()["recorded_at"])
    assert served(conn.execute("SELECT recorded_at FROM benefit_items WHERE amount = 2 AND initiative_id = 'init-001' AND period_index = 2 AND starts_period = 1 AND recorded_at IS NOT NULL").fetchone()["recorded_at"])
    a = command(lab, "record-adoption", {"initiative_id": "init-001", "eligible_count": 40, "adopted_count": 31, "eligibility_rule_version": "elig-v1", "observed_on": "2028-03-31",
                                         "training": {"eligible_trainees": 40, "completed": 39}}, headers=ANALYST)
    assert a.status_code == 200, a.text
    row = conn.execute("SELECT cw_iso(observed_at) AS o, recorded_at FROM adoption_observations WHERE adopted_count = 31").fetchone()
    assert row["o"] == "2028-03-31T00:00:00Z" and served(row["recorded_at"])                  # it happened on the 31st of March, the server recorded it on 1 July
    assert served(conn.execute("SELECT entered_at FROM training_completions WHERE completed = 39").fetchone()["entered_at"])
    b = command(lab, "track-benefits", {"benefit_id": "b-101", "measured_value": "470.00", "unit": "USD", "evidence_ref": "  ev:ledger-2028  ", "observed_on": "2028-02-01"}, headers=ANALYST)
    assert b.status_code == 200, b.text
    row = conn.execute("SELECT recorded_at, evidence_ref FROM benefit_observations WHERE measured_value = 470").fetchone()
    assert served(row["recorded_at"]) and row["evidence_ref"] == "ev:ledger-2028"             # stripped


def test_a_back_dated_observation_cannot_change_an_earlier_as_of_and_is_listed_as_late_recorded(lab, conn):
    """R9-11: an observation entered on 1 July for 31 March is not part of what was published for 30 June; the same-day tie goes to the later record."""
    asof = "2028-06-30T00:00:00Z"
    base = metrics(lab, as_of=asof)["data"]["metrics"]["initiatives"]["init-001"]["adoption"]
    assert base["adoption_rate"] == "0.750000" and base["latest_observation_id"] == "ad-2"
    r = command(lab, "record-adoption", {"initiative_id": "init-001", "eligible_count": 40, "adopted_count": 0, "eligibility_rule_version": "elig-v1", "observed_on": "2028-03-31"}, headers=ANALYST)
    assert r.status_code == 200, r.text
    new_id = r.json()["result"]["observation_id"]
    again = metrics(lab, as_of=asof)["data"]["metrics"]["initiatives"]["init-001"]["adoption"]
    assert again["adoption_rate"] == "0.750000" and again["late_recorded"] == [new_id] and [x["observation_id"] for x in again["series"]] == [x["observation_id"] for x in base["series"]]
    later = metrics(lab, as_of="2028-07-02T00:00:00Z")["data"]["metrics"]["initiatives"]["init-001"]["adoption"]
    assert later["latest_observation_id"] == new_id and later["adoption_rate"] == "0.000000"            # same day as ad-2, recorded later: it wins the tie from 2 July on
    assert later["late_recorded"] == []


@pytest.mark.parametrize("patch,rule", [({"observed_on": "1999-01-01"}, "OBSERVED_BEFORE_START"), ({"observed_on": "2030-01-01"}, "DATE_IN_FUTURE")])
def test_c08_and_c09_observed_on_lies_between_the_first_period_start_and_the_servers_date(lab, conn, patch, rule):
    refused(lab, conn, "record-adoption", {"initiative_id": "init-001", "eligible_count": 40, "adopted_count": 1, "eligibility_rule_version": "elig-v1", **patch}, 422, rule)
    refused(lab, conn, "track-benefits", {**TRACK, **patch}, 422, rule)
    ok = command(lab, "record-adoption", {"initiative_id": "init-001", "eligible_count": 40, "adopted_count": 1, "eligibility_rule_version": "elig-v1", "observed_on": "2026-01-01"}, headers=ANALYST)
    assert ok.status_code == 200                                                    # exactly the first period start of init-001 (requested start 0 = 2026-01-01) is allowed


# ------------------------------------------------------------------------------------------------------------ review 9: evidence, cost keys, validation
@pytest.mark.parametrize("field,where", [("evidence_ref", "benefit"), ("staffing_change_evidence_ref", "assumption"), ("evidence_ref", "assumption")])
def test_blank_evidence_is_refused_in_the_command_and_never_opens_the_cash_flow(lab, conn, field, where):
    """R9-04: '   ' is not evidence: avoided cost does not enter the cash flow on it and capacity is not converted on it; the command refuses it EVIDENCE_REQUIRED."""
    if where == "benefit":
        body = {**SCN, "scenario_id": "scn-blank", "benefits": [{"initiative_id": "init-001", "benefit_type": "avoided_cost", "amount": "999.00", "period_index": 1, "starts_period": 1,
                                                             "cash_realisation": True, "evidence_ref": "   "}]}
    else:
        body = {**SCN, "scenario_id": "scn-blank", "initiative_ids": ["init-003"], "assumptions": [{"initiative_id": "init-003", "name": "capacity_hourly_rate", "value": "40.00",
                                                                                                    "rationale": "r", field: "  \t "}]}
    refused(lab, conn, "build-cash-flows", body, 422, "EVIDENCE_REQUIRED")


def test_a_cost_key_cannot_be_retyped_from_one_time_to_recurring_and_a_new_key_can(lab, conn):
    """R9-05: the reviewer's attack (ck-101-licence is the golden licence); the recovery is a different key."""
    retyped = {**SCN, "scenario_id": "scn-retyped", "costs": [{"initiative_id": "init-001", "cost_key": "ck-101-licence", "cost_type": "recurring", "amount": "1000.00", "start_period": 1, "end_period": 3}]}
    r = refused(lab, conn, "build-cash-flows", retyped, 422, "COST_KEY_BASIS_CONFLICT")
    assert r.json()["error"]["details"][0]["context"]["first_cost_id"] in ("c-101", "c-102")
    ok = command(lab, "build-cash-flows", {**retyped, "costs": [{**retyped["costs"][0], "cost_key": "ck-101-support"}]}, headers=ANALYST)
    assert ok.status_code == 200 and ok.json()["result"]["rows_added"]["cost_items"] == 1
    actual = command(lab, "build-cash-flows", {**SCN, "scenario_id": "scn-actual", "costs": [{"initiative_id": "init-001", "cost_key": "ck-101-licence", "cost_type": "recurring",
                                                                                          "cost_basis": "actual", "amount": "1.00", "start_period": 1, "end_period": 2}]}, headers=ANALYST)
    assert actual.status_code == 422 and rule_ids(actual) == ["COST_KEY_BASIS_CONFLICT"]            # the golden also has an ACTUAL one-time cost under this key (c-102)


def test_c01_an_error_rate_outside_0_1_is_invalid_field_and_c10_needs_expected_version(lab, conn):
    refused(lab, conn, "establish-baseline", {**BASE, "error_rate": "1.5"}, 422, "INVALID_FIELD")
    refused(lab, conn, "revise-forecast", {k: v for k, v in REVISE.items() if k != "expected_version"}, 422, "FIELD_REQUIRED")      # R9-22: the version last read is always named


def test_c10_a_revision_covers_the_periods_of_the_original(lab, conn):
    """R9-10: the reviewer's partial revision (period 2 only) is refused; a full one is accepted, and the stored original stays preserved."""
    partial = {"initiative_id": "init-001", "reason": "partial: only period 2", "expected_version": 2, "periods": [{"period_index": 2, "amount": "550.00"}]}
    r = refused(lab, conn, "revise-forecast", partial, 422, "REVISION_PERIODS_INCOMPLETE")
    assert r.json()["error"]["details"][0]["context"] == {"missing_periods": [1], "original_periods": [1, 2]}
    ok = command(lab, "revise-forecast", {**partial, "periods": [{"period_index": 1, "amount": "450.00"}, {"period_index": 2, "amount": "550.00"}]})
    assert ok.status_code == 200 and ok.json()["result"]["latest_minus_original"] == "-200.00" and ok.json()["result"]["forecast"]["revisions_cover_original_periods"] is True
    assert ok.json()["result"]["original_preserved"] is True
