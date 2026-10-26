"""Commands through the HTTP API: valid, malformed, unknown resource, stale version, idempotency, unsupported
action, 401 and 403 (docs/api-contract.md)."""
import pytest

from api.app import PREFIX

from support_db import (ADMIN, OPS, REVIEWER, client, command, conn, count, db_url, drive_to_completion, open_case,  # noqa: F401
                        rule_ids, seeded, step_id)

HOST = {"X-Actor-Id": "x", "X-Actor-Role": "ops"}


@pytest.fixture
def api(client, seeded):
    return client


# --- C01 create-case ----------------------------------------------------------------

def test_create_case_valid(api, conn):
    r = open_case(api)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "created" and body["version"] == 1 and body["command_id"].startswith("cmd-")
    assert [(s["step_definition_id"], s["status"]) for s in body["result"]["steps"]] == \
        [("sd-001", "ready"), ("sd-002", "blocked")]
    assert count(conn, "cases") == 2 and count(conn, "step_instances") == 4
    assert conn.execute("SELECT count(*) AS n FROM assignments WHERE ended_at IS NULL").fetchone()["n"] == 2          # the two new assignments; the seeded ones are closed
    assert conn.execute("SELECT action, actor_id FROM audit_events").fetchone() == \
        {"action": "create-case", "actor_id": "ops-2"}


def test_create_case_binds_only_a_published_version(api, conn):  # P02-TEST-04
    conn.execute("INSERT INTO workflow_versions (workflow_version_id, template_id, version_number) VALUES ('wfv-draft', 'tpl-001', 2)")
    r = command(api, "create-case", {"case_id": "c-d", "organization_id": "org-001", "workflow_version_id": "wfv-draft"})
    assert r.status_code == 422 and rule_ids(r) == ["WORKFLOW_VERSION_NOT_PUBLISHED"]
    assert r.json()["error"]["details"][0]["path"] == "input.workflow_version_id"
    assert count(conn, "cases") == 1 and count(conn, "audit_events") == 0     # nothing written


def test_create_case_unknown_resources(api):
    r = command(api, "create-case", {"case_id": "c", "organization_id": "nope", "workflow_version_id": "wfv-001"})
    assert r.status_code == 404 and rule_ids(r) == ["ORGANIZATION_UNKNOWN"]
    r = command(api, "create-case", {"case_id": "c", "organization_id": "org-001", "workflow_version_id": "nope"})
    assert r.status_code == 404 and rule_ids(r) == ["WORKFLOW_VERSION_UNKNOWN"]
    r = command(api, "create-case", {"case_id": "c", "organization_id": "org-001", "workflow_version_id": "wfv-001",
                                     "assignments": {"sd-zzz": "ops-1"}})
    assert r.status_code == 422 and rule_ids(r) == ["STEP_DEFINITION_UNKNOWN"]


def test_create_case_duplicate_id_is_a_conflict(api):
    assert open_case(api).status_code == 200
    r = open_case(api)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CASE_EXISTS"


def test_correction_case_links_to_a_completed_case(api, conn):
    r = command(api, "create-case", {"case_id": "case-fix", "organization_id": "org-001",
                                     "workflow_version_id": "wfv-001", "corrects_case_id": "case-001"})
    assert r.status_code == 200
    assert conn.execute("SELECT linked_case_id FROM cases WHERE case_id = 'case-fix'").fetchone()["linked_case_id"] == "case-001"
    open_case(api)
    r = command(api, "create-case", {"case_id": "case-fix2", "organization_id": "org-001",
                                     "workflow_version_id": "wfv-001", "corrects_case_id": "case-100"})
    assert r.status_code == 422 and rule_ids(r) == ["CORRECTION_TARGET_NOT_COMPLETED"]


@pytest.mark.parametrize("body,rule,path", [
    ({"organization_id": "org-001", "workflow_version_id": "wfv-001"}, "FIELD_REQUIRED", "input.case_id"),
    ({"case_id": "c", "organization_id": "org-001", "workflow_version_id": "wfv-001", "surprise": 1},
     "FIELD_UNEXPECTED", "input.surprise"),
    ({"case_id": 7, "organization_id": "org-001", "workflow_version_id": "wfv-001"}, "FIELD_INVALID", "input.case_id"),
    ({"case_id": "c", "organization_id": "org-001", "workflow_version_id": "wfv-001", "occurred_at": "yesterday"},
     "TIMESTAMP_INVALID", "input.occurred_at"),
    ({"case_id": "c", "organization_id": "org-001", "workflow_version_id": "wfv-001",
      "occurred_at": "2026-03-10T09:00:00"}, "TIMESTAMP_INVALID", "input.occurred_at"),
])
def test_malformed_input_is_422_with_path_and_rule(api, body, rule, path):
    r = command(api, "create-case", body)
    assert r.status_code == 422
    d = r.json()["error"]["details"][0]
    assert d["rule_id"] == rule and d["path"] == path
    assert r.json()["request_id"] == "req-test"


def test_malformed_envelope_and_body(api):
    r = api.post(f"{PREFIX}/commands/create-case", content=b"{not json", headers={**OPS, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["rule_id"] == "BODY_INVALID_JSON"
    r = api.post(f"{PREFIX}/commands/create-case", json={"request_id": "r", "dataset_version": "d",
                                                          "idempotency_key": "bad key!", "input": {}}, headers=OPS)
    assert r.status_code == 422
    assert "IDEMPOTENCY_KEY_INVALID" in rule_ids(r)


# --- identity and roles ---------------------------------------------------------------

def test_missing_identity_is_401_and_unknown_role_is_403(api, conn):
    body = {"case_id": "c", "organization_id": "org-001", "workflow_version_id": "wfv-001"}
    r = command(api, "create-case", body, headers={})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    r = command(api, "create-case", body, headers={"X-Actor-Id": "  ", "X-Actor-Role": "ops"})
    assert r.status_code == 401
    r = command(api, "create-case", body, headers={"X-Actor-Id": "u", "X-Actor-Role": "guest"})
    assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"]
    r = command(api, "create-case", body, headers={"X-Actor-Id": "u"})
    assert r.status_code == 403
    assert count(conn, "cases") == 1


def test_role_gates_per_command(api):
    open_case(api)
    r = command(api, "reject-submission", {"case_id": "case-100", "document_type": "x", "reason": "r"}, headers=OPS)
    assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"]
    r = command(api, "publish-workflow-version", {"workflow_version_id": "w"}, headers=REVIEWER)
    assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"]


# --- idempotency ------------------------------------------------------------------------

def test_same_key_same_payload_replays_the_stored_response(api, conn):
    body = {"case_id": "case-100", "organization_id": "org-001", "workflow_version_id": "wfv-001"}
    first = command(api, "create-case", body, key="k-1")
    again = command(api, "create-case", body, key="k-1", request_id="req-other")
    assert first.status_code == again.status_code == 200
    assert again.headers["Idempotent-Replay"] == "true" and "Idempotent-Replay" not in first.headers
    assert again.json() == first.json()
    assert count(conn, "cases") == 2 and count(conn, "audit_events") == 1


def test_same_key_different_payload_is_409(api, conn):
    command(api, "create-case", {"case_id": "case-100", "organization_id": "org-001",
                                 "workflow_version_id": "wfv-001"}, key="k-2")
    r = command(api, "create-case", {"case_id": "case-101", "organization_id": "org-001",
                                     "workflow_version_id": "wfv-001"}, key="k-2")
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert rule_ids(r) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"] and count(conn, "cases") == 2


def test_failed_command_stores_no_result_so_the_key_can_be_retried(api, conn):
    bad = {"case_id": "c", "organization_id": "nope", "workflow_version_id": "wfv-001"}
    assert command(api, "create-case", bad, key="k-3").status_code == 404
    assert count(conn, "command_results") == 0
    good = {"case_id": "c", "organization_id": "org-001", "workflow_version_id": "wfv-001"}
    assert command(api, "create-case", good, key="k-3").status_code == 200


# --- unsupported and not implemented --------------------------------------------------------

def test_unsupported_action_is_404(api):
    r = command(api, "frobnicate-case", {})
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNSUPPORTED_ACTION"
    assert command(api, "frobnicate-case", {}, headers={}).status_code == 401      # identity is checked first


@pytest.mark.parametrize("name", ["reassign-work", "migrate-workflow"])
def test_extension_commands_are_501_not_implemented(api, name):
    r = command(api, name, {"anything": 1})
    assert r.status_code == 501 and r.json()["error"]["code"] == "NOT_IMPLEMENTED"
    assert command(api, name, {}, headers={}).status_code == 401


def test_get_on_a_command_path_is_405(api):
    r = api.get(f"{PREFIX}/commands/create-case")
    assert r.status_code == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


# --- C02 .. C04 documents -----------------------------------------------------------------

def test_submit_document_creates_a_version_row_with_a_placeholder_hash(api, conn):
    open_case(api)
    r = command(api, "submit-document", {"case_id": "case-100", "document_type": "identity_proof",
                                         "step_instance_id": step_id("case-100", "sd-001")})
    assert r.status_code == 200 and r.json()["result"]["version_number"] == 1
    assert r.json()["result"]["step_status"] == "in_review"
    row = conn.execute("SELECT * FROM document_versions WHERE case_id = 'case-100'").fetchone()
    assert row["content_hash"].startswith("sha256:") and len(row["content_hash"]) == 71
    assert conn.execute("SELECT status FROM step_instances WHERE step_instance_id = 'case-100:sd-001'").fetchone()["status"] == "in_review"


def test_submit_document_rejects_a_real_looking_hash_and_a_second_first_submission(api):
    open_case(api)
    r = command(api, "submit-document", {"case_id": "case-100", "document_type": "d", "content_hash": "abc"})
    assert r.status_code == 422 and rule_ids(r) == ["CONTENT_HASH_INVALID"]
    assert command(api, "submit-document", {"case_id": "case-100", "document_type": "d"}).status_code == 200
    r = command(api, "submit-document", {"case_id": "case-100", "document_type": "d"})
    assert r.status_code == 422 and rule_ids(r) == ["DOCUMENT_ALREADY_SUBMITTED"]


def test_submit_document_unknown_resources_and_wrong_step_state(api):
    assert command(api, "submit-document", {"case_id": "nope", "document_type": "d"}).status_code == 404
    open_case(api)
    r = command(api, "submit-document", {"case_id": "case-100", "document_type": "d",
                                         "step_instance_id": "case-100:sd-002"})   # blocked -> in_review is illegal
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_TRANSITION"]
    r = command(api, "submit-document", {"case_id": "case-100", "document_type": "d", "step_instance_id": "zzz"})
    assert r.status_code == 404 and rule_ids(r) == ["STEP_INSTANCE_UNKNOWN"]
    r = command(api, "submit-document", {"case_id": "case-001", "document_type": "d"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CASE_ALREADY_COMPLETE"


def test_reject_submission_needs_a_reason(api):
    open_case(api)
    command(api, "submit-document", {"case_id": "case-100", "document_type": "d"})
    for reason in ("", "   "):
        r = command(api, "reject-submission", {"case_id": "case-100", "document_type": "d", "reason": reason}, headers=REVIEWER)
        assert r.status_code == 422 and r.json()["error"]["details"][0]["path"] == "input.reason"
    r = command(api, "reject-submission", {"case_id": "case-100", "document_type": "d"}, headers=REVIEWER)
    assert r.status_code == 422 and rule_ids(r) == ["FIELD_REQUIRED"]
    r = command(api, "reject-submission", {"case_id": "case-100", "document_type": "d", "reason": "blurry"}, headers=REVIEWER)
    assert r.status_code == 200 and r.json()["status"] == "changes_requested"
    r = command(api, "reject-submission", {"case_id": "case-100", "document_type": "d", "reason": "again"}, headers=REVIEWER)
    assert r.status_code == 422 and rule_ids(r) == ["DOCUMENT_NOT_SUBMITTED"]


def test_resubmit_requires_a_rejection_and_keeps_the_prior_version(api, conn):
    open_case(api)
    command(api, "submit-document", {"case_id": "case-100", "document_type": "d"})
    r = command(api, "resubmit-document", {"case_id": "case-100", "document_type": "d"})
    assert r.status_code == 422 and rule_ids(r) == ["NOT_IN_CHANGES_REQUESTED"]
    assert command(api, "resubmit-document", {"case_id": "case-100", "document_type": "zzz"}).status_code == 404
    command(api, "reject-submission", {"case_id": "case-100", "document_type": "d", "reason": "blurry"}, headers=REVIEWER)
    r = command(api, "resubmit-document", {"case_id": "case-100", "document_type": "d"})
    assert r.status_code == 200 and r.json()["result"]["version_number"] == 2
    assert [x["version_number"] for x in conn.execute(
        "SELECT version_number FROM document_versions WHERE case_id = 'case-100' ORDER BY 1").fetchall()] == [1, 2]


# --- C05 unlock ------------------------------------------------------------------------------

def test_unlock_dependent_step_needs_the_prerequisite_approved(api):
    open_case(api)
    s2 = step_id("case-100", "sd-002")
    r = command(api, "unlock-dependent-step", {"step_instance_id": s2})
    assert r.status_code == 422 and rule_ids(r) == ["STEP_NOT_READY"]
    assert command(api, "unlock-dependent-step", {"step_instance_id": "zzz"}).status_code == 404
    r = command(api, "unlock-dependent-step", {"step_instance_id": step_id("case-100", "sd-001")})
    assert r.status_code == 422 and rule_ids(r) == ["STEP_NOT_BLOCKED"]
    r = command(api, "unlock-dependent-step", {"step_instance_id": s2, "expected_version": 5})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_VERSION"


# --- C06 approve ----------------------------------------------------------------------------------

def _in_review(api, case_id="case-100"):
    open_case(api, case_id)
    command(api, "submit-document", {"case_id": case_id, "document_type": "identity_proof",
                                     "step_instance_id": step_id(case_id, "sd-001")})
    return step_id(case_id, "sd-001")


def test_approve_step_valid_and_audited(api, conn):
    s1 = _in_review(api)
    r = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1})   # ops-2 has the ops role
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert conn.execute("SELECT status, approved_at IS NOT NULL AS ok FROM step_instances WHERE step_instance_id = %s", (s1,)).fetchone() == {"status": "approved", "ok": True}
    assert conn.execute("SELECT action FROM audit_events ORDER BY occurred_at DESC LIMIT 1").fetchone()["action"] == "approve-step"


def test_approve_step_stale_version_and_unknown_step(api):
    s1 = _in_review(api)
    r = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 7})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_VERSION"
    assert command(api, "approve-step", {"step_instance_id": "zzz", "expected_version": 1}).status_code == 404
    r = command(api, "approve-step", {"step_instance_id": s1})
    assert r.status_code == 422 and rule_ids(r) == ["FIELD_REQUIRED"]
    r = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 0})
    assert r.status_code == 422


def test_approve_step_role_must_match_the_step(api):
    s1 = _in_review(api)
    r = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1}, headers=REVIEWER)   # needs ops
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_MISMATCH"
    r = command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1}, headers=ADMIN)
    assert r.status_code == 200


def test_approve_step_must_be_in_review(api):
    open_case(api)
    r = command(api, "approve-step", {"step_instance_id": step_id("case-100", "sd-001"), "expected_version": 1})
    assert r.status_code == 422 and rule_ids(r) == ["STEP_NOT_IN_REVIEW"]


# --- C08 pause -----------------------------------------------------------------------------------------

def test_pause_sla_with_a_configured_reason(api, conn):
    open_case(api)
    r = command(api, "pause-sla", {"case_id": "case-100", "reason_code": "customer_info_requested",
                                   "starts_at": "2026-03-10T10:00:00Z", "ends_at": "2026-03-10T12:00:00Z"})
    assert r.status_code == 200 and r.json()["status"] == "waiting_external" and r.json()["warnings"] == []
    assert conn.execute("SELECT reason_code FROM waiting_intervals WHERE case_id = 'case-100'").fetchone()["reason_code"] == "customer_info_requested"


def test_pause_sla_unconfigured_reason_is_422(api, conn):
    open_case(api)
    r = command(api, "pause-sla", {"case_id": "case-100", "reason_code": "lunch"})
    assert r.status_code == 422 and rule_ids(r) == ["PAUSE_REASON_NOT_CONFIGURED"]
    assert count(conn, "waiting_intervals") == 1


def test_pause_sla_open_interval_blocks_a_second_pause_and_validates_the_interval(api):
    open_case(api)
    base = {"case_id": "case-100", "reason_code": "customer_info_requested"}
    assert command(api, "pause-sla", {**base, "starts_at": "2026-03-10T10:00:00Z"}).status_code == 200
    r = command(api, "pause-sla", {**base, "starts_at": "2026-03-10T11:00:00Z"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_PAUSED"
    r = command(api, "pause-sla", {**base, "starts_at": "2026-03-10T12:00:00Z", "ends_at": "2026-03-10T11:00:00Z"})
    assert r.status_code == 422
    assert command(api, "pause-sla", {**base, "case_id": "zzz"}).status_code == 404


# --- C09 complete ------------------------------------------------------------------------------------------

def test_complete_case_full_flow_and_metrics(api, conn):
    drive_to_completion(api)
    row = conn.execute("SELECT status, completed_at, version FROM cases WHERE case_id = 'case-100'").fetchone()
    assert row["status"] == "completed" and row["completed_at"].isoformat().startswith("2026-03-10T09:45:00")
    r = api.get(f"{PREFIX}/metrics", params={"from": "2026-03-10", "to": "2026-03-11", "cutoff": "2026-03-10T09:30:00Z"})
    m = r.json()["data"]["metrics"]
    assert m["completed_eligible_cases"] == 1 and m["calendar_cycle_time_hours"] == "0.7500"
    assert m["business_cycle_time_hours"] == "0.7500" and m["active_elapsed_hours"] == "0.7500"
    assert m["open_backlog_at_cutoff"] == {"2026-03-10T09:30:00Z": 1}
    assert m["document_completeness"] == "1.000000" and m["rework_rate"] == "0.000000"


def test_complete_case_stale_version_and_unknown(api):
    open_case(api)
    r = command(api, "complete-case", {"case_id": "case-100", "expected_version": 9})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_VERSION"
    assert command(api, "complete-case", {"case_id": "zzz"}).status_code == 404
    r = command(api, "complete-case", {"case_id": "case-100", "occurred_at": "2026-03-01T00:00:00Z"})
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_TIMESTAMP"]


# --- P publish -----------------------------------------------------------------------------------------------

STEPS = [{"step_definition_id": "n-1", "step_name": "a", "required": True, "role_key": "ops", "sequence": 1},
         {"step_definition_id": "n-2", "step_name": "b", "required": True, "role_key": "reviewer", "sequence": 2}]


def test_publish_workflow_version_then_it_is_immutable(api, conn):
    dep = {"dependency_id": "nd-1", "step_definition_id": "n-2", "prerequisite_id": "n-1"}
    r = command(api, "publish-workflow-version", {"workflow_version_id": "wfv-new", "template_id": "tpl-001", "steps": STEPS,
                                                  "dependencies": [dep], "required_document_types": ["identity_proof"],
                                                  "sla_rule": {"sla_rule_id": "sla-new", "business_minutes": 240,
                                                               "pause_policy": ["customer_info_requested"],
                                                               "calendar_id": "cal-001"}}, headers=ADMIN)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["step_order"] == ["n-1", "n-2"] and len(res["definition_hash"]) == 64
    assert conn.execute("SELECT version_number FROM workflow_versions WHERE workflow_version_id = 'wfv-new'").fetchone()["version_number"] == 2
    r = command(api, "publish-workflow-version", {"workflow_version_id": "wfv-new"}, headers=ADMIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_PUBLISHED"
    assert open_case_on(api, "wfv-new").status_code == 200


def open_case_on(api, wfv):
    return command(api, "create-case", {"case_id": "case-n", "organization_id": "org-001", "workflow_version_id": wfv})


def test_publish_validation(api):
    r = command(api, "publish-workflow-version", {"workflow_version_id": "w"}, headers=ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["DEFINITION_REQUIRED"]
    r = command(api, "publish-workflow-version", {"workflow_version_id": "w", "steps": STEPS + STEPS}, headers=ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["DUPLICATE_STEP"]
    bad = {"dependency_id": "d", "step_definition_id": "n-2", "prerequisite_id": "n-9"}
    r = command(api, "publish-workflow-version", {"workflow_version_id": "w", "steps": STEPS, "dependencies": [bad]}, headers=ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["ORPHAN_REFERENCE"]


def test_publish_an_existing_draft(api, conn):
    conn.execute("INSERT INTO workflow_versions (workflow_version_id, template_id, version_number) VALUES ('wfv-d', 'tpl-9', 1)")
    conn.execute("INSERT INTO step_definitions VALUES ('dd-1', 'wfv-d', 'a', true, 'ops', 1)")
    r = command(api, "publish-workflow-version", {"workflow_version_id": "wfv-d"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["result"]["step_order"] == ["dd-1"]
    assert conn.execute("SELECT published_at IS NOT NULL AS p FROM workflow_versions WHERE workflow_version_id = 'wfv-d'").fetchone()["p"]
