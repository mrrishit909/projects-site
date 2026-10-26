"""One test per contract rule, on inline fixtures (docs/contracts.md D-01..D-05). No database needed."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from onboard_studio import DomainError, calendar as cal, run_pipeline, workflow
from onboard_studio.errors import (CASE_ALREADY_COMPLETE, DECISION_CONFLICT, DEPENDENCY_CYCLE,
                                   MISSING_REQUIRED_DOCUMENT, PAUSE_REASON_NOT_CONFIGURED, SELF_APPROVAL,
                                   STEP_NOT_READY, WORKFLOW_VERSION_NOT_PUBLISHED)
from onboard_studio.ingest import validate_batch
from onboard_studio.metrics import compute_with_flags, group_metrics
from onboard_studio.timeutil import d4, d6, hours, seconds_between

from support_db import golden_inputs


def T(day: int, hhmm: str) -> datetime:
    """March 2026 instant (Mon 2026-03-02 .. Fri 03-06, Sat 03-07, Sun 03-08, Mon 03-09)."""
    h, m = hhmm.split(":")
    return datetime(2026, 3, day, int(h), int(m), tzinfo=timezone.utc)


def iso(day: int, hhmm: str) -> str:
    return T(day, hhmm).strftime("%Y-%m-%dT%H:%M:%SZ")


def reasons(inputs) -> dict[tuple[str, str], str]:
    return {(r.entity, r.id): r.reason_code for r in validate_batch(inputs).rejected}


def with_holiday(inputs, start, end, cid="hol-1"):
    inputs["calendar_intervals"].append({"calendar_interval_id": cid, "calendar_id": "cal-001",
                                         "starts_at": start, "ends_at": end, "timezone": "UTC", "kind": "holiday"})
    return inputs


# --- D-01 calendars ------------------------------------------------------------------

def test_holiday_on_a_weekend_subtracts_nothing():  # P02-TEST-08
    base = run_pipeline(golden_inputs(), "pause_not_eligible").metrics
    data = with_holiday(golden_inputs(), iso(7, "00:00"), iso(8, "23:59"))  # Saturday and Sunday
    m = run_pipeline(data, "pause_not_eligible").metrics
    assert m["business_cycle_time_hours"] == base["business_cycle_time_hours"] == "2.0000"
    assert m["calendar_cycle_time_hours"] == "66.0000"


def test_holiday_on_a_working_day_is_subtracted():
    data = with_holiday(golden_inputs(), iso(9, "09:00"), iso(9, "17:00"))  # Monday
    m = run_pipeline(data, "pause_not_eligible").metrics
    assert m["business_cycle_time_hours"] == "1.0000"  # only Friday 16:00-17:00 is left
    assert m["active_elapsed_hours"] == "1.0000"


def test_holiday_splits_a_working_interval():
    working = [(T(6, "09:00"), T(6, "17:00"))]
    left = cal.subtract(working, [(T(6, "12:00"), T(6, "13:00"))])
    assert left == [(T(6, "09:00"), T(6, "12:00")), (T(6, "13:00"), T(6, "17:00"))]
    assert cal.overlap_seconds(T(6, "08:00"), T(6, "18:00"), left) == 7 * 3600


@pytest.mark.parametrize("start,end,expected_seconds", [
    ((6, "09:00"), (6, "17:00"), 8 * 3600),     # exactly the interval
    ((6, "08:59"), (6, "09:00"), 0),            # ends exactly where the interval starts: [s, e) is half-open
    ((6, "17:00"), (6, "17:01"), 0),            # starts exactly where it ends
    ((6, "08:59"), (6, "09:01"), 60),           # one minute across the start boundary
    ((6, "16:59"), (6, "17:01"), 60),           # one minute across the end boundary
    ((6, "09:00"), (6, "09:00"), 0),            # empty range
    ((6, "12:00"), (6, "11:00"), 0),            # reversed range is never negative
])
def test_business_overlap_at_exact_interval_boundaries(start, end, expected_seconds):
    working = [(T(6, "09:00"), T(6, "17:00"))]
    assert cal.overlap_seconds(T(*start), T(*end), working) == expected_seconds


def test_adjacent_intervals_do_not_double_count_the_shared_instant():
    working = cal.merge([(T(6, "09:00"), T(6, "12:00")), (T(6, "12:00"), T(6, "17:00"))])
    assert working == [(T(6, "09:00"), T(6, "17:00"))]
    assert cal.in_working_time(T(6, "09:00"), working) and not cal.in_working_time(T(6, "17:00"), working)


def test_durations_are_never_negative_and_round_half_up():
    assert seconds_between(T(6, "12:00"), T(6, "11:00")) == 0
    assert hours(Decimal(-5)) == 0
    assert d4(Decimal("0.00005")) == "0.0001" and d4(Decimal("0.00004")) == "0.0000"
    assert d6(Decimal("0.0000005")) == "0.000001" and d4(None) is None


def test_paused_interval_outside_working_time_contributes_zero_and_is_flagged():  # P02-TEST-03
    data = golden_inputs()
    data["waiting_intervals"][0].update(starts_at=iso(7, "10:00"), ends_at=iso(8, "10:00"))  # Sat 10:00 -> Sun 10:00
    res = run_pipeline(data, "pause_eligible")
    assert res.metrics["paused_business_overlap_hours"] == "0.0000"
    assert res.metrics["paused_time_hours"] == "24.0000"          # the calendar time is still recorded
    assert res.metrics["active_elapsed_hours"] == "2.0000"        # nothing is deducted from business time
    assert res.flags == [{"waiting_interval_id": "wi-001", "case_id": "case-001",
                          "flag": "PAUSE_OUTSIDE_WORKING_INTERVAL"}]


def test_pause_that_touches_working_time_is_not_flagged():
    assert run_pipeline(golden_inputs(), "pause_eligible").flags == []


def test_customer_waiting_that_is_not_pause_eligible_is_not_deducted():  # P02-DOMAIN-03
    m = run_pipeline(golden_inputs(), "pause_not_eligible").metrics
    assert (m["paused_time_hours"], m["active_elapsed_hours"]) == ("0.0000", "2.0000")


def test_waiting_interval_is_clipped_to_the_case_span():
    data = golden_inputs()
    data["waiting_intervals"][0].update(starts_at=iso(5, "09:00"), ends_at=iso(10, "09:00"))
    m = run_pipeline(data, "pause_eligible").metrics
    assert m["paused_time_hours"] == "66.0000"                 # not the 120 h of the raw interval
    assert m["paused_business_overlap_hours"] == "2.0000" and m["active_elapsed_hours"] == "0.0000"


def test_active_elapsed_is_never_negative():
    data = golden_inputs()
    data["waiting_intervals"][0].update(starts_at=iso(6, "00:00"), ends_at=iso(9, "23:00"))
    assert run_pipeline(data, "pause_eligible").metrics["active_elapsed_hours"] == "0.0000"


def test_sla_uses_active_minutes_at_the_boundary():
    data = golden_inputs()
    data["sla_rules"][0]["business_minutes"] = 60   # active 1 h == 60 min: within
    assert run_pipeline(data, "pause_eligible").metrics["within_sla_cases"] == 1
    data["sla_rules"][0]["business_minutes"] = 59
    m = run_pipeline(data, "pause_eligible").metrics
    assert (m["within_sla_cases"], m["sla_attainment"]) == (0, "0.000000")


# --- D-02 workflow versions ------------------------------------------------------------

def test_cycle_detection_with_kahns_algorithm():  # P02-TEST-05
    assert workflow.check_publishable(["a", "b", "c"], [("b", "a"), ("c", "b")]) == ["a", "b", "c"]
    with pytest.raises(DomainError) as e:
        workflow.check_publishable(["a", "b", "c"], [("b", "a"), ("c", "b"), ("a", "c")])
    assert e.value.code == DEPENDENCY_CYCLE and e.value.details["steps"] == ["a", "b", "c"]


def test_self_dependency_is_a_cycle_and_unknown_step_is_an_orphan():
    with pytest.raises(DomainError) as e:
        workflow.check_publishable(["a"], [("a", "a")])
    assert e.value.code == DEPENDENCY_CYCLE
    with pytest.raises(DomainError) as e2:
        workflow.check_publishable(["a"], [("a", "zzz")])
    assert e2.value.code == "ORPHAN_REFERENCE"


def test_cyclic_version_is_rejected_at_ingest_with_its_steps_and_cases():
    data = golden_inputs()
    data["dependencies"].append({"dependency_id": "dep-002", "step_definition_id": "sd-001",
                                 "prerequisite_id": "sd-002", "dependency_type": "mandatory",
                                 "created_at": "2026-03-01T00:00:00Z"})
    r = reasons(data)
    assert r[("workflow_versions", "wfv-001")] == DEPENDENCY_CYCLE
    assert r[("cases", "case-001")] == DEPENDENCY_CYCLE
    assert r[("step_definitions", "sd-001")] == DEPENDENCY_CYCLE
    assert r[("step_instances", "si-001")] == DEPENDENCY_CYCLE


def test_definition_hash_changes_with_the_dependencies():
    data = golden_inputs()
    a = workflow.definition_hash(data["step_definitions"], data["dependencies"])
    assert a == data["workflow_versions"][0]["definition_hash"]
    assert workflow.definition_hash(data["step_definitions"], []) != a


def test_case_bound_to_an_unpublished_version_is_rejected():  # P02-TEST-04
    data = golden_inputs()
    data["workflow_versions"][0]["published_at"] = None
    assert reasons(data)[("cases", "case-001")] == WORKFLOW_VERSION_NOT_PUBLISHED
    data = golden_inputs()
    data["workflow_versions"][0]["published_at"] = "2026-03-07T00:00:00Z"   # published after the case opened
    assert reasons(data)[("cases", "case-001")] == WORKFLOW_VERSION_NOT_PUBLISHED


# --- D-03 steps, documents, approvals --------------------------------------------------

def test_step_readiness_needs_every_mandatory_prerequisite_approved():
    deps = [{"step_definition_id": "b", "prerequisite_id": "a", "dependency_type": "mandatory"},
            {"step_definition_id": "b", "prerequisite_id": "o", "dependency_type": "optional"}]
    assert not workflow.step_is_ready("b", deps, {"a": "in_review"})
    assert not workflow.step_is_ready("b", deps, {})                       # no instance is not approved
    assert workflow.step_is_ready("b", deps, {"a": "approved"})             # the optional one does not count
    assert workflow.step_is_ready("a", deps, {})
    with pytest.raises(DomainError) as e:
        workflow.require_unlockable("b", deps, {"a": "ready"})
    assert e.value.code == STEP_NOT_READY and e.value.details["unapproved"] == ["a"]


def test_step_started_before_its_prerequisite_was_approved_is_step_not_ready():
    data = golden_inputs()
    data["step_instances"][1]["started_at"] = "2026-03-09T09:30:00Z"  # before si-001 was approved (09:40)
    data["step_instances"][1]["ready_at"] = "2026-03-09T09:30:00Z"
    assert reasons(data)[("cases", "case-001")] == STEP_NOT_READY


def test_state_machine_transitions():
    workflow.require_transition("blocked", "ready")
    workflow.require_transition("changes_requested", "ready")
    for a, b in [("blocked", "approved"), ("approved", "ready"), ("in_review", "ready")]:
        with pytest.raises(DomainError):
            workflow.require_transition(a, b)


def test_self_approval_rejects_the_case_and_its_children():  # P02-TEST-10
    data = golden_inputs()
    data["approvals"][1]["reviewer_id"] = "ops-002"            # the assignee of si-002 approves it
    r = reasons(data)
    assert r[("approvals", "apr-002")] == SELF_APPROVAL
    assert r[("cases", "case-001")] == SELF_APPROVAL
    assert set(r.values()) == {SELF_APPROVAL} and len(r) == 19   # the case and all 18 rows that hang off it
    assert run_pipeline(data, "pause_eligible").metrics["empty_population"] is True


def test_any_assignee_ever_counts_for_self_approval():
    data = golden_inputs()
    data["assignments"][0]["ended_at"] = "2026-03-06T17:00:00Z"
    data["assignments"].append({"assignment_id": "asg-003", "step_instance_id": "si-001", "assignee_id": "rev-001",
                                "assigned_at": "2026-03-06T17:00:00Z", "ended_at": "2026-03-09T09:40:00Z"})
    assert reasons(data)[("cases", "case-001")] == SELF_APPROVAL


def test_approval_check_roles_and_assignees():
    workflow.check_approval("rev-1", "reviewer", "reviewer", ["ops-1"])
    workflow.check_approval("adm-1", "admin", "reviewer", [])
    with pytest.raises(DomainError) as e:
        workflow.check_approval("ops-1", "reviewer", "reviewer", ["ops-1"])
    assert e.value.code == SELF_APPROVAL
    with pytest.raises(DomainError) as e2:
        workflow.check_approval("ops-2", "ops", "reviewer", ["ops-1"])
    assert e2.value.code == "ROLE_MISMATCH"


def test_second_decision_on_the_same_step_version_is_a_decision_conflict():  # P02-TEST-02
    data = golden_inputs()
    data["approvals"].append({"approval_id": "apr-003", "step_instance_id": "si-002", "reviewer_id": "rev-003",
                              "decision": "changes_requested", "decided_at": "2026-03-09T10:05:00Z", "reason": "late"})
    r = reasons(data)
    assert r == {("approvals", "apr-003"): DECISION_CONFLICT}            # only the later decision is rejected
    # carrying the new version number is not a conflict
    data["approvals"][-1]["version_number"] = 2
    assert reasons(data) == {}


def test_completed_case_missing_a_required_document_is_rejected():  # P02-TEST-01
    data = golden_inputs()
    data["document_versions"][0]["review_status"] = "submitted"
    assert reasons(data)[("cases", "case-001")] == MISSING_REQUIRED_DOCUMENT
    data = golden_inputs()
    data["step_instances"][1]["status"] = "in_review"
    assert reasons(data)[("cases", "case-001")] == MISSING_REQUIRED_DOCUMENT


def test_completion_check_lists_what_is_missing():
    with pytest.raises(DomainError) as e:
        workflow.require_completable({"sd-1": "approved", "sd-2": "in_review"}, ["id", "tax"], ["id"])
    assert e.value.code == MISSING_REQUIRED_DOCUMENT
    assert e.value.details == {"steps": ["sd-2"], "document_types": ["tax"]}
    workflow.require_completable({"sd-1": "approved"}, ["id"], ["id", "extra"])


def test_reopening_a_completed_case_is_rejected():  # P02-TEST-11
    data = golden_inputs()
    data["case_events"].append({"event_id": "ev-011", "case_id": "case-001", "event_type": "case_reopened",
                                "actor_id": "ops-001", "occurred_at": "2026-03-09T11:00:00Z"})
    assert reasons(data)[("cases", "case-001")] == CASE_ALREADY_COMPLETE


def test_second_completion_event_or_activity_after_completion_is_rejected():
    data = golden_inputs()
    data["case_events"].append({"event_id": "ev-011", "case_id": "case-001", "event_type": "case_completed",
                                "actor_id": "ops-001", "occurred_at": "2026-03-09T10:00:00Z"})
    assert reasons(data)[("cases", "case-001")] == CASE_ALREADY_COMPLETE
    data = golden_inputs()
    data["case_events"].append({"event_id": "ev-011", "case_id": "case-001", "event_type": "step_started",
                                "actor_id": "ops-001", "occurred_at": "2026-03-09T12:00:00Z"})
    assert reasons(data)[("cases", "case-001")] == CASE_ALREADY_COMPLETE


def test_pause_reason_must_be_configured():
    workflow.check_pause_reason("customer_info_requested", ["customer_info_requested"])
    with pytest.raises(DomainError) as e:
        workflow.check_pause_reason("lunch", ["customer_info_requested"])
    assert e.value.code == PAUSE_REASON_NOT_CONFIGURED
    data = golden_inputs()
    data["waiting_intervals"][0].update(reason_code="lunch", pause_requested=True)
    assert reasons(data)[("cases", "case-001")] == PAUSE_REASON_NOT_CONFIGURED
    data["waiting_intervals"][0].pop("pause_requested")      # a plain waiting interval is only recorded
    assert reasons(data) == {}


def test_malformed_orphan_and_duplicate_rows():
    data = golden_inputs()
    data["cases"].append({"case_id": "case-bad"})                                  # missing fields
    data["case_events"].append({"event_id": "ev-x", "case_id": "ghost", "event_type": "x", "actor_id": "a",
                                "occurred_at": "2026-03-09T10:00:00Z"})
    data["organizations"].append(dict(data["organizations"][0]))                   # same id twice
    res = validate_batch(data)
    got = {(r.entity, r.id): r.reason_code for r in res.rejected}
    assert got[("cases", "case-bad")] == "MALFORMED_RECORD"
    assert got[("case_events", "ev-x")] == "ORPHAN_REFERENCE"
    assert got[("organizations", "org-001")] == "DUPLICATE_ID"
    assert res.counts["organizations"] == {"accepted": 1, "rejected": 1}


def test_wrong_contract_is_refused():
    with pytest.raises(DomainError) as e:
        validate_batch({"contract": "v9"})
    assert e.value.code == "CONTRACT_MISMATCH"


# --- D-03 handoffs, D-04 rates and groups -----------------------------------------------

def _second_case(data, case_id="case-003", org="org-002", opened=(10, "09:00"), done=(10, "12:00")):
    data["organizations"].append({"organization_id": org, "organization_name": "Other", "segment": "ent",
                                  "region": "apac", "created_at": "2026-02-01T00:00:00Z"})
    data["cases"].append({"case_id": case_id, "organization_id": org, "workflow_version_id": "wfv-001",
                          "status": "completed", "opened_at": iso(*opened), "completed_at": iso(*done)})
    for sd, n in (("sd-001", 1), ("sd-002", 2)):
        data["step_instances"].append({
            "step_instance_id": f"{case_id}-{sd}", "case_id": case_id, "step_definition_id": sd, "status": "approved",
            "version_number": 1, "ready_at": iso(10, f"0{9 + n - 1}:00"), "started_at": iso(10, f"0{9 + n - 1}:30"),
            "approved_at": iso(10, f"0{9 + n - 1}:45")})
        data["assignments"].append({"assignment_id": f"asg-{case_id}-{sd}", "step_instance_id": f"{case_id}-{sd}",
                                    "assignee_id": "ops-009", "assigned_at": iso(10, "09:00"), "ended_at": None})
        data["approvals"].append({"approval_id": f"apr-{case_id}-{sd}", "step_instance_id": f"{case_id}-{sd}",
                                  "reviewer_id": "rev-009", "decision": "approved",
                                  "decided_at": iso(10, f"0{9 + n - 1}:45"), "reason": None})
    data["document_versions"].append({
        "document_version_id": f"doc-{case_id}", "case_id": case_id, "document_type": "identity_proof",
        "version_number": 1, "content_hash": "sha256:" + "0" * 63 + "9", "review_status": "accepted",
        "submitted_at": iso(10, "09:05"), "reviewed_at": iso(10, "09:10")})
    return data


def test_group_metrics_by_each_dimension():
    data = _second_case(golden_inputs())
    res = run_pipeline(data, "pause_eligible")
    assert res.counts["cases"] == {"accepted": 2, "rejected": 0}
    pop = res.population
    for by, keys in (("organization", ["org-001", "org-002"]), ("segment", ["ent", "smb"]),
                     ("region", ["apac", "emea"]), ("workflow_version", ["wfv-001"])):
        groups = group_metrics(pop, by, None, data["cutoffs"])
        assert list(groups) == keys
    by_org = group_metrics(pop, "organization", None, data["cutoffs"])
    assert by_org["org-001"]["business_cycle_time_hours"] == "2.0000"
    assert by_org["org-002"]["business_cycle_time_hours"] == "3.0000"
    assert res.metrics["business_cycle_time_hours"] == "2.5000"       # population mean over completed cases
    assert res.metrics["completed_eligible_cases"] == 2


def test_group_by_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        group_metrics(run_pipeline(golden_inputs()).population, "colour")


def test_window_is_half_open_on_opened_at():
    data = _second_case(golden_inputs())
    pop = run_pipeline(data, "pause_eligible").population
    lo, hi = T(10, "09:00"), T(10, "09:00")
    assert compute_with_flags(pop, None, [], (lo, T(11, "00:00")))[0]["completed_eligible_cases"] == 1
    assert compute_with_flags(pop, None, [], (T(6, "00:00"), T(10, "09:00")))[0]["completed_eligible_cases"] == 1
    with pytest.raises(DomainError):
        compute_with_flags(pop, None, [], (lo, hi))


def test_handoffs_count_assignments_minus_one_and_ignore_exact_replays():  # P02-FLOW-07
    data = golden_inputs()
    data["assignments"][0]["ended_at"] = "2026-03-06T18:00:00Z"
    data["assignments"].append({"assignment_id": "asg-003", "step_instance_id": "si-001", "assignee_id": "ops-003",
                                "assigned_at": "2026-03-06T18:00:00Z", "ended_at": "2026-03-09T09:40:00Z"})
    assert run_pipeline(data, "pause_eligible").metrics["handoff_count"] == 1
    data["assignments"].append({**data["assignments"][-1], "assignment_id": "asg-004"})   # exact replay
    assert run_pipeline(data, "pause_eligible").metrics["handoff_count"] == 1


def test_rework_and_first_pass_with_a_rejected_first_submission():
    data = golden_inputs()
    data["document_versions"][0].update(review_status="rejected")
    data["document_versions"].append({
        "document_version_id": "doc-002", "case_id": "case-001", "document_type": "identity_proof",
        "version_number": 2, "content_hash": "sha256:" + "0" * 63 + "2", "review_status": "accepted",
        "submitted_at": "2026-03-09T09:00:00Z", "reviewed_at": "2026-03-09T09:35:00Z"})
    m = run_pipeline(data, "pause_eligible").metrics
    assert m["rework_rate"] == "1.000000" and m["first_pass_approval"] == "0.000000"
    assert m["document_completeness"] == "1.000000"


def test_open_backlog_counts_open_cases_at_the_cutoff():
    data = golden_inputs()
    data["cases"].append({"case_id": "case-open", "organization_id": "org-001", "workflow_version_id": "wfv-001",
                          "status": "open", "opened_at": "2026-03-06T12:00:00Z", "completed_at": None})
    m = run_pipeline(data, "pause_eligible", cutoffs=["2026-03-06T11:59:59Z", "2026-03-07T12:00:00Z",
                                                      "2026-03-09T10:00:00Z"]).metrics
    assert m["open_backlog_at_cutoff"] == {"2026-03-06T11:59:59Z": 0, "2026-03-07T12:00:00Z": 2,
                                           "2026-03-09T10:00:00Z": 1}   # completed_at == cutoff is closed
    assert m["completed_eligible_cases"] == 1                          # open cases stay beside, not inside


def test_open_case_without_documents_has_null_rework_and_zero_completeness():
    data = golden_inputs()
    data["cases"] = [{"case_id": "case-open", "organization_id": "org-001", "workflow_version_id": "wfv-001",
                      "status": "open", "opened_at": "2026-03-06T12:00:00Z", "completed_at": None}]
    for k in ("step_instances", "assignments", "document_versions", "approvals", "waiting_intervals", "case_events"):
        data[k] = []
    m = run_pipeline(data, "pause_eligible").metrics
    assert m["sla_attainment"] is None and m["rework_rate"] is None and m["first_pass_approval"] is None
    assert m["document_completeness"] == "0.000000" and m["empty_population"] is False
