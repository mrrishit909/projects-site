"""Adversarial tests named by their P02-TEST id (01, 02, 03, 05, 06, 09, 10, 11): each attacks a rule through the
API and, where the rule is also a data rule, through the database or the ingest."""
import psycopg
import pytest

from onboard_studio import run_pipeline

from support_db import (ADMIN, OPS, REVIEWER, client, command, conn, count, db_url, drive_to_completion, golden_inputs,  # noqa: F401
                        open_case, rule_ids, seeded, step_id)


@pytest.fixture
def api(client, seeded):
    return client


def test_p02_test_01_complete_with_missing_document(api, conn):
    """A case with every step approved but no accepted required document cannot complete."""
    open_case(api)
    s1, s2 = step_id("case-100", "sd-001"), step_id("case-100", "sd-002")
    command(api, "submit-document", {"case_id": "case-100", "document_type": "identity_proof", "step_instance_id": s1})
    assert command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1}).status_code == 200
    command(api, "unlock-dependent-step", {"step_instance_id": s2})
    command(api, "submit-document", {"case_id": "case-100", "document_type": "approval_form", "step_instance_id": s2})
    assert command(api, "approve-step", {"step_instance_id": s2, "expected_version": 1}, headers=REVIEWER).status_code == 200
    r = command(api, "complete-case", {"case_id": "case-100"}, headers=REVIEWER)     # identity_proof is only submitted
    assert r.status_code == 422 and rule_ids(r) == ["MISSING_REQUIRED_DOCUMENT"]
    assert r.json()["error"]["details"][0]["path"] == "input.case_id"
    assert conn.execute("SELECT status FROM cases WHERE case_id = 'case-100'").fetchone()["status"] == "open"
    # a submitted document is not an accepted one; accepting it makes completion possible
    assert command(api, "accept-document", {"case_id": "case-100", "document_type": "identity_proof"}, headers=REVIEWER).status_code == 200
    assert command(api, "complete-case", {"case_id": "case-100"}, headers=REVIEWER).status_code == 200


def test_p02_test_01_a_rejected_document_does_not_count_and_missing_steps_are_listed(api):
    open_case(api)
    command(api, "submit-document", {"case_id": "case-100", "document_type": "identity_proof"})
    command(api, "reject-submission", {"case_id": "case-100", "document_type": "identity_proof", "reason": "blur"}, headers=REVIEWER)
    r = command(api, "complete-case", {"case_id": "case-100"}, headers=REVIEWER)
    assert r.status_code == 422 and rule_ids(r) == ["MISSING_REQUIRED_DOCUMENT"]
    assert r.json()["error"]["details"][0]["context"] == {"steps": ["sd-001", "sd-002"], "document_types": ["identity_proof"]}


def test_p02_test_02_conflicting_decisions(api, conn):
    """Two decisions on the same step version: the second is a DECISION_CONFLICT and changes nothing."""
    open_case(api)
    s1 = step_id("case-100", "sd-001")
    command(api, "submit-document", {"case_id": "case-100", "document_type": "identity_proof", "step_instance_id": s1})
    first = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1}, headers={"X-Actor-Id": "ops-2", "X-Actor-Role": "ops"})
    second = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1}, headers={"X-Actor-Id": "ops-3", "X-Actor-Role": "ops"})
    assert first.status_code == 200
    assert second.status_code == 409 and second.json()["error"]["code"] == "DECISION_CONFLICT"
    assert rule_ids(second) == ["DECISION_CONFLICT"]
    assert conn.execute("SELECT count(*) AS n FROM approvals WHERE step_instance_id = %s", (s1,)).fetchone()["n"] == 1
    # the database itself refuses a second row for the same step version
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO approvals VALUES ('apr-x', %s, 'ops-3', 'approved', now(), NULL, 1)", (s1,))


def test_p02_test_02_a_decision_carrying_the_new_version_is_not_a_conflict(api, conn):
    open_case(api)
    s1 = step_id("case-100", "sd-001")
    command(api, "submit-document", {"case_id": "case-100", "document_type": "identity_proof", "step_instance_id": s1})
    # reviewer sends the work back: the step moves to version 2 and goes round again
    assert command(api, "reject-submission", {"case_id": "case-100", "document_type": "identity_proof", "reason": "blur",
                                              "step_instance_id": s1}, headers=REVIEWER).status_code == 200
    assert conn.execute("SELECT version_number, status FROM step_instances WHERE step_instance_id = %s", (s1,)).fetchone() == \
        {"version_number": 2, "status": "changes_requested"}
    assert command(api, "resubmit-document", {"case_id": "case-100", "document_type": "identity_proof",
                                              "step_instance_id": s1}).status_code == 200
    stale = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_VERSION"
    assert command(api, "approve-step", {"step_instance_id": s1, "expected_version": 2}).status_code == 200


def test_p02_test_03_pause_outside_working_interval(api, conn):
    """A pause on a weekend contributes 0 business hours and is flagged, on the command and in the metrics."""
    open_case(api, at="2026-03-06T16:30:00Z")
    r = command(api, "pause-sla", {"case_id": "case-100", "reason_code": "customer_info_requested",
                                   "starts_at": "2026-03-07T10:00:00Z", "ends_at": "2026-03-08T10:00:00Z"})
    assert r.status_code == 200
    assert [w["code"] for w in r.json()["warnings"]] == ["PAUSE_OUTSIDE_WORKING_INTERVAL"]
    # complete the case Monday 10:00 through the domain-visible rows, then read the metrics
    conn.execute("UPDATE cases SET status = 'completed', completed_at = '2026-03-09T10:00:00Z' WHERE case_id = 'case-100'")
    m = api.get("/api/v1/onboard-studio/metrics", params={"from": "2026-03-06T16:15:00Z", "to": "2026-03-06T17:00:00Z"})
    body = m.json()
    metrics = body["data"]["metrics"]
    assert metrics["paused_business_overlap_hours"] == "0.0000"
    assert metrics["paused_time_hours"] == "24.0000" and metrics["business_cycle_time_hours"] == "1.5000"
    assert metrics["calendar_cycle_time_hours"] == "65.5000" and metrics["active_elapsed_hours"] == "1.5000"
    assert [w["code"] for w in body["warnings"]] == ["PAUSE_OUTSIDE_WORKING_INTERVAL"]


def test_p02_test_03_a_pause_inside_working_hours_is_not_flagged(api):
    open_case(api)
    r = command(api, "pause-sla", {"case_id": "case-100", "reason_code": "customer_info_requested",
                                   "starts_at": "2026-03-10T10:00:00Z", "ends_at": "2026-03-10T11:00:00Z"})
    assert r.json()["warnings"] == []


def test_p02_test_05_dependency_cycle(api, conn):
    """Publishing a version whose dependencies form a cycle is refused and writes nothing."""
    steps = [{"step_definition_id": f"cy-{i}", "step_name": f"s{i}", "required": True, "role_key": "ops", "sequence": i}
             for i in (1, 2, 3)]
    deps = [{"dependency_id": f"cd-{i}", "step_definition_id": f"cy-{i}", "prerequisite_id": f"cy-{i % 3 + 1}"}
            for i in (1, 2, 3)]                                     # 1 -> 2 -> 3 -> 1
    before = (count(conn, "workflow_versions"), count(conn, "step_definitions"))
    r = command(api, "publish-workflow-version", {"workflow_version_id": "wfv-cycle", "steps": steps, "dependencies": deps}, headers=ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["DEPENDENCY_CYCLE"]
    assert (count(conn, "workflow_versions"), count(conn, "step_definitions")) == before
    assert count(conn, "audit_events") == 0 and count(conn, "command_results") == 0
    # an acyclic diamond publishes
    steps4 = steps + [{"step_definition_id": "cy-4", "step_name": "s4", "required": False, "role_key": "ops", "sequence": 4}]
    diamond = [{"dependency_id": "dd-1", "step_definition_id": "cy-2", "prerequisite_id": "cy-1"},
               {"dependency_id": "dd-2", "step_definition_id": "cy-3", "prerequisite_id": "cy-1"},
               {"dependency_id": "dd-3", "step_definition_id": "cy-4", "prerequisite_id": "cy-2"},
               {"dependency_id": "dd-4", "step_definition_id": "cy-4", "prerequisite_id": "cy-3"}]
    r = command(api, "publish-workflow-version", {"workflow_version_id": "wfv-ok", "steps": steps4, "dependencies": diamond}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["result"]["step_order"] == ["cy-1", "cy-2", "cy-3", "cy-4"]


def test_p02_test_05_a_cyclic_draft_already_in_the_database_cannot_be_published(api, conn):
    conn.execute("INSERT INTO workflow_versions (workflow_version_id, template_id, version_number) VALUES ('wfv-c', 'tpl-c', 1)")
    conn.execute("INSERT INTO step_definitions VALUES ('c1', 'wfv-c', 'a', true, 'ops', 1), ('c2', 'wfv-c', 'b', true, 'ops', 2)")
    conn.execute("INSERT INTO dependencies VALUES ('cd1', 'c1', 'c2', 'mandatory', NULL), ('cd2', 'c2', 'c1', 'mandatory', NULL)")
    r = command(api, "publish-workflow-version", {"workflow_version_id": "wfv-c"}, headers=ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["DEPENDENCY_CYCLE"]
    assert conn.execute("SELECT published_at FROM workflow_versions WHERE workflow_version_id = 'wfv-c'").fetchone()["published_at"] is None


def test_p02_test_06_resubmission_preserves_the_prior_version(api, conn):
    """Resubmitting never edits the earlier row; the database forbids editing it."""
    open_case(api)
    command(api, "submit-document", {"case_id": "case-100", "document_type": "identity_proof"})
    before = conn.execute("SELECT * FROM document_versions WHERE document_version_id = 'case-100:identity_proof:v1'").fetchone()
    command(api, "reject-submission", {"case_id": "case-100", "document_type": "identity_proof", "reason": "blur"}, headers=REVIEWER)
    r = command(api, "resubmit-document", {"case_id": "case-100", "document_type": "identity_proof", "content_hash": "sha256:" + "ab" * 32})
    assert r.status_code == 200
    rows = conn.execute("SELECT * FROM document_versions WHERE case_id = 'case-100' ORDER BY version_number").fetchall()
    assert [x["version_number"] for x in rows] == [1, 2]
    assert rows[0] == before                                           # byte-for-byte the same row
    assert rows[1]["content_hash"] == "sha256:" + "ab" * 32 and rows[0]["content_hash"] != rows[1]["content_hash"]
    review = conn.execute("SELECT decision, reason FROM document_reviews WHERE document_version_id = %s", (rows[0]["document_version_id"],)).fetchone()
    assert review == {"decision": "rejected", "reason": "blur"}        # the rejection is history, not an overwrite
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        conn.execute("UPDATE document_versions SET content_hash = 'sha256:tampered' WHERE version_number = 1")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        conn.execute("DELETE FROM document_versions WHERE version_number = 1")
    # the metrics see a rework case whose first pass failed
    m = api.get("/api/v1/onboard-studio/metrics", params={"from": "2026-03-10", "to": "2026-03-11"}).json()["data"]["metrics"]
    assert m["rework_rate"] == "1.000000" and m["first_pass_approval"] == "0.000000"


def test_p02_test_09_customer_waiting_is_not_active_time():
    """Customer waiting is never counted as employee processing (P02-DOMAIN-03)."""
    eligible = run_pipeline(golden_inputs(), "pause_eligible").metrics
    assert eligible["business_cycle_time_hours"] == "2.0000"
    assert eligible["paused_business_overlap_hours"] == "1.0000"
    assert eligible["active_elapsed_hours"] == "1.0000"               # the waiting hour is removed from active time
    # and a case that sat entirely in customer waiting has no active time at all
    data = golden_inputs()
    data["waiting_intervals"][0].update(starts_at="2026-03-06T16:00:00Z", ends_at="2026-03-09T10:00:00Z")
    all_waiting = run_pipeline(data, "pause_eligible").metrics
    assert all_waiting["active_elapsed_hours"] == "0.0000" and all_waiting["sla_attainment"] == "1.000000"
    assert all_waiting["calendar_cycle_time_hours"] == "66.0000"      # cycle time itself still includes the wait


def test_p02_test_10_self_approval(api, conn):
    """A reviewer who is or was an assignee of the step cannot approve it."""
    open_case(api, assignments={"sd-001": "ops-1", "sd-002": "rev-1"})
    s1, s2 = step_id("case-100", "sd-001"), step_id("case-100", "sd-002")
    command(api, "submit-document", {"case_id": "case-100", "document_type": "identity_proof", "step_instance_id": s1})
    r = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1},
                headers={"X-Actor-Id": "ops-1", "X-Actor-Role": "ops"})            # the assignee approves their own work
    assert r.status_code == 403 and r.json()["error"]["code"] == "SELF_APPROVAL" and rule_ids(r) == ["SELF_APPROVAL"]
    assert command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1}).status_code == 200
    command(api, "unlock-dependent-step", {"step_instance_id": s2})
    command(api, "submit-document", {"case_id": "case-100", "document_type": "approval_form", "step_instance_id": s2})
    r = command(api, "approve-step", {"step_instance_id": s2, "expected_version": 1}, headers=REVIEWER)   # rev-1 is the assignee
    assert r.status_code == 403 and rule_ids(r) == ["SELF_APPROVAL"]
    assert command(api, "approve-step", {"step_instance_id": s2, "expected_version": 1},
                   headers={"X-Actor-Id": "rev-2", "X-Actor-Role": "reviewer"}).status_code == 200
    assert conn.execute("SELECT count(*) AS n FROM approvals WHERE reviewer_id IN ('ops-1', 'rev-1')").fetchone()["n"] == 0


def test_p02_test_10_a_past_assignee_is_still_an_assignee(api, conn):
    open_case(api, assignments={"sd-001": "ops-1"})
    s1 = step_id("case-100", "sd-001")
    conn.execute("UPDATE assignments SET ended_at = now() WHERE step_instance_id = %s", (s1,))   # reassigned away
    conn.execute("INSERT INTO assignments VALUES ('asg-new', %s, 'ops-9', now(), NULL)", (s1,))
    command(api, "submit-document", {"case_id": "case-100", "document_type": "identity_proof", "step_instance_id": s1})
    r = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1},
                headers={"X-Actor-Id": "ops-1", "X-Actor-Role": "ops"})
    assert r.status_code == 403 and rule_ids(r) == ["SELF_APPROVAL"]


def test_p02_test_11_reopen_after_completion(api, conn):
    """A completed case cannot be completed again, changed, paused or reopened; a correction is a linked new case."""
    drive_to_completion(api)
    assert conn.execute("SELECT version FROM cases WHERE case_id = 'case-100'").fetchone()["version"] >= 7
    again = command(api, "complete-case", {"case_id": "case-100"}, headers=REVIEWER)
    assert again.status_code == 409 and again.json()["error"]["code"] == "CASE_ALREADY_COMPLETE"
    r = command(api, "reopen-case", {"case_id": "case-100"}, headers=ADMIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CASE_REOPEN_FORBIDDEN"
    for name, body in (("pause-sla", {"case_id": "case-100", "reason_code": "customer_info_requested"}),
                       ("submit-document", {"case_id": "case-100", "document_type": "extra"}),
                       ("resubmit-document", {"case_id": "case-100", "document_type": "identity_proof"})):
        r = command(api, name, body, headers=ADMIN)
        assert r.status_code == 409 and r.json()["error"]["code"] == "CASE_ALREADY_COMPLETE", name
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):                      # the database agrees
        conn.execute("UPDATE cases SET status = 'open', completed_at = NULL WHERE case_id = 'case-100'")
    assert conn.execute("SELECT status FROM cases WHERE case_id = 'case-100'").fetchone()["status"] == "completed"
    r = command(api, "create-case", {"case_id": "case-100-fix", "organization_id": "org-001", "workflow_version_id": "wfv-001",
                                     "corrects_case_id": "case-100"})
    assert r.status_code == 200
    assert conn.execute("SELECT linked_case_id FROM cases WHERE case_id = 'case-100-fix'").fetchone()["linked_case_id"] == "case-100"


def test_p02_test_11_reopen_of_unknown_or_open_cases(api):
    assert command(api, "reopen-case", {"case_id": "zzz"}).status_code == 404
    open_case(api)
    r = command(api, "reopen-case", {"case_id": "case-100"})
    assert r.status_code == 422 and rule_ids(r) == ["CASE_NOT_COMPLETED"]
    assert command(api, "reopen-case", {"case_id": "case-100"}, headers={}).status_code == 401


def test_atomicity_a_failed_command_leaves_no_trace(api, conn):
    open_case(api)
    snapshot = {t: count(conn, t) for t in ("cases", "step_instances", "document_versions", "case_events", "audit_events", "command_results")}
    r = command(api, "approve-step", {"step_instance_id": step_id("case-100", "sd-001"), "expected_version": 1})   # not in review
    assert r.status_code == 422
    assert snapshot == {t: count(conn, t) for t in snapshot}
