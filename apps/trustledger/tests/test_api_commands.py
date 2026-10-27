"""Commands C01..C10: happy paths, hard validation, roles, idempotency, stale dataset versions, audit and atomicity."""
from datetime import datetime, timedelta, timezone

import pytest

from api import clock
from support_db import (ADMIN, ANALYST, INACTIVE, STEWARD, STEWARD2, client, command, conn, count, db_url, get, golden_inputs, load,  # noqa: F401
                        publish_through_review, rule_ids, table_digest)

AS_OF = datetime(2026, 10, 5, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def lab(client, conn):
    load(conn, golden_inputs())
    clock.freeze(AS_OF)
    return client


def audit(conn, action, entity_id=None):
    return conn.execute("SELECT * FROM audit_events WHERE action = %s AND (%s::text IS NULL OR entity_id = %s)", (action, entity_id, entity_id)).fetchall()


# ------------------------------------------------------------------------------------------------------------ C01
def test_c01_registers_a_dataset_with_owner_classification_and_server_time(lab, conn):
    r = command(lab, "register-dataset", {"dataset_id": "ds-new", "dataset_name": "New feed", "source_system": "erp", "owner_id": "own-02",
                                          "classification": "internal", "monitored": True, "refresh_timezone": "Asia/Kolkata",
                                          "refresh_local_time": "05:30", "refresh_grace_minutes": 45,
                                          "fields": [{"field_name": "k"}], "rows": [{"row_id": "a", "k": "1"}, {"row_id": "b", "k": None}]}, headers=ANALYST)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cataloged" and body["result"]["registered_at"].startswith("2026-10-05T00:00:00") and body["result"]["rows"] == 2
    assert any(w["code"] == "NEVER_REFRESHED" for w in body["warnings"])
    row = conn.execute("SELECT * FROM datasets WHERE dataset_id = 'ds-new'").fetchone()
    assert (row["owner_id"], row["classification"], row["registered_by"], row["refresh_timezone"]) == ("own-02", "internal", "own-01", "Asia/Kolkata")
    assert count(conn, "dataset_rows", "dataset_id = 'ds-new'") == 2 and count(conn, "fields", "dataset_id = 'ds-new'") == 1
    assert len(audit(conn, "register-dataset", "ds-new")) == 1


def test_c01_the_server_stamps_the_registration_time(lab):
    r = command(lab, "register-dataset", {"dataset_id": "ds-x", "dataset_name": "x", "source_system": "s", "owner_id": "own-02", "classification": "internal",
                                          "registered_at": "2020-01-01T00:00:00Z"})
    assert r.status_code == 422 and rule_ids(r) == ["FIELD_UNEXPECTED"]


@pytest.mark.parametrize("patch,code", [
    ({"owner_id": None}, "OWNER_REQUIRED"), ({"owner_id": "   "}, "OWNER_REQUIRED"), ({"classification": None}, "CLASSIFICATION_REQUIRED"),
    ({"classification": " \t"}, "CLASSIFICATION_REQUIRED"), ({"owner_id": "own-05"}, "OWNER_INACTIVE"), ({"owner_id": "own-99"}, "UNKNOWN_OWNER"),
    ({"monitored": True}, "SCHEDULE_REQUIRED"),
    ({"monitored": True, "refresh_timezone": "Mars/Base", "refresh_local_time": "06:00", "refresh_grace_minutes": 5}, "MALFORMED_RECORD"),
    ({"monitored": True, "refresh_timezone": "UTC", "refresh_local_time": "25:00", "refresh_grace_minutes": 5}, "MALFORMED_RECORD"),
    ({"last_refreshed_at": "2030-01-01T00:00:00Z"}, "REFRESH_IN_FUTURE"),
    ({"rows": [{"row_id": "a"}, {"row_id": "a"}]}, "DUPLICATE_ID"), ({"rows": [{"k": 1}]}, "MALFORMED_RECORD"), ({"rows": [{"row_id": "a", "k": {"x": 1}}]}, "MALFORMED_RECORD"),
    ({"fields": [{"field_name": "k"}, {"field_name": "k"}]}, "DUPLICATE_FIELD")])
def test_c01_hard_validation(lab, conn, patch, code):
    base = {"dataset_id": "ds-bad", "dataset_name": "Bad", "source_system": "erp", "owner_id": "own-02", "classification": "internal"}
    before = table_digest(conn, ["datasets", "dataset_rows", "fields", "audit_events", "command_results"])
    r = command(lab, "register-dataset", {**base, **patch})
    assert r.status_code == 422 and code in rule_ids(r), r.text
    assert table_digest(conn, ["datasets", "dataset_rows", "fields", "audit_events", "command_results"]) == before      # nothing written


def test_c01_duplicate_dataset_is_409(lab):
    r = command(lab, "register-dataset", {"dataset_id": "ds-orders", "dataset_name": "x", "source_system": "s", "owner_id": "own-02", "classification": "internal"})
    assert r.status_code == 409 and rule_ids(r) == ["DATASET_EXISTS"]


# ------------------------------------------------------------------------------------------------------------ C02
def test_c02_publishes_versions_and_never_rewrites(lab, conn):
    pub = {"metric_id": "m-new", "metric_name": "New metric", "definition": "d", "grain": "order", "source_fields": ["orders.amount"], "owner_id": "own-04", "refresh": "daily"}
    v1 = publish_through_review(lab, pub)                       # draft (v1), reviewed (v2), published (v3): each step a new row
    assert v1.status_code == 200, v1.text
    rows = conn.execute("SELECT * FROM metric_versions WHERE metric_id = 'm-new' ORDER BY version_number").fetchall()
    assert [(r["version_number"], r["status"], r["published_by"]) for r in rows] == [(1, "draft", "own-02"), (2, "reviewed", "own-03"), (3, "published", "own-02")]
    assert v1.json()["result"]["version_number"] == 3 and v1.json()["result"]["change_id"] is not None and v1.json()["warnings"] == []
    first = rows[0]
    no_reason = command(lab, "publish-definition", {**pub, "definition": "d2", "status": "draft"})
    assert no_reason.status_code == 422 and rule_ids(no_reason) == ["REASON_REQUIRED"]
    v4 = command(lab, "publish-definition", {**pub, "definition": "d2", "status": "draft", "reason": "clearer wording", "expected_version": 3})
    assert v4.status_code == 200 and v4.json()["result"]["version_number"] == 4 and v4.json()["result"]["previous_metric_version_id"] == rows[2]["metric_version_id"]
    rows2 = conn.execute("SELECT * FROM metric_versions WHERE metric_id = 'm-new' ORDER BY version_number").fetchall()
    assert [r["definition"] for r in rows2] == ["d", "d", "d", "d2"] and rows2[0] == first            # the first version row is untouched
    ch = conn.execute("SELECT * FROM definition_changes WHERE metric_version_id = %s", (rows2[3]["metric_version_id"],)).fetchone()
    assert (ch["reason"], ch["approved_by"], ch["changed_at"]) == ("clearer wording", "own-02", rows2[3]["valid_from"])
    stale = command(lab, "publish-definition", {**pub, "reason": "again", "expected_version": 1, "status": "draft"})
    assert stale.status_code == 409 and rule_ids(stale) == ["STALE_METRIC_VERSION"]


def test_c02_the_reviewed_state_sits_between_draft_and_published(lab, conn):
    """D-10 R7-12 (FLOW-02): draft -> reviewed -> published. No step is skipped, the content is the content that was reviewed, and the reviewer is
    not the author. Reviewed and draft versions are not counted in definition coverage."""
    pub = {"metric_id": "m-flow", "metric_name": "Flow", "definition": "d", "grain": "g", "source_fields": ["a.b"], "owner_id": "own-04", "refresh": "daily"}
    skip = command(lab, "publish-definition", {**pub, "status": "published"})
    assert skip.status_code == 409 and rule_ids(skip) == ["PUBLICATION_REQUIRES_REVIEW"] and skip.json()["error"]["code"] == "INVALID_TRANSITION"
    assert command(lab, "publish-definition", {**pub, "status": "reviewed"}).json()["error"]["details"][0]["rule_id"] == "REVIEW_REQUIRES_DRAFT"
    assert command(lab, "publish-definition", {**pub, "status": "draft"}).json()["status"] == "drafted"
    self_review = command(lab, "publish-definition", {**pub, "status": "reviewed", "reason": "mine"}, headers=STEWARD)       # own-02 drafted it
    assert self_review.status_code == 409 and rule_ids(self_review) == ["SELF_REVIEW"] and len(audit(conn, "publish-definition-refused", "m-flow")) == 1
    published_first = command(lab, "publish-definition", {**pub, "status": "published", "reason": "x"}, headers=STEWARD2)     # still a draft: not reviewed
    assert published_first.status_code == 409 and rule_ids(published_first) == ["PUBLICATION_REQUIRES_REVIEW"]
    changed = command(lab, "publish-definition", {**pub, "definition": "other", "status": "reviewed", "reason": "r"}, headers=STEWARD2)
    assert changed.status_code == 409 and rule_ids(changed) == ["CONTENT_CHANGED"]
    rev = command(lab, "publish-definition", {**pub, "status": "reviewed", "reason": "checked by a second person"}, headers=STEWARD2)
    assert rev.status_code == 200 and rev.json()["status"] == "reviewed" and rev.json()["result"]["status"] == "reviewed"
    cov = get(lab, "/metrics", as_of="2026-10-06T00:00:00Z").json()["data"]["metrics"]["definition_coverage"]
    assert cov["published_metrics"] == 4                                                                # a reviewed version is not published yet
    changed2 = command(lab, "publish-definition", {**pub, "grain": "other", "status": "published", "reason": "r"})
    assert changed2.status_code == 409 and rule_ids(changed2) == ["CONTENT_CHANGED"]
    done = command(lab, "publish-definition", {**pub, "status": "published", "reason": "approved"})
    assert done.status_code == 200 and done.json()["status"] == "published"
    assert get(lab, "/metrics", as_of="2026-10-06T00:00:00Z").json()["data"]["metrics"]["definition_coverage"]["published_metrics"] == 5


def test_c02_in_place_rewrite_is_refused_and_audited(lab, conn):
    before = table_digest(conn, ["metric_versions", "definition_changes"])
    r = command(lab, "publish-definition", {"metric_id": "m-revenue", "metric_name": "Net revenue", "definition": "rewritten", "grain": "order",
                                            "source_fields": ["x"], "owner_id": "own-04", "refresh": "daily", "reason": "oops", "metric_version_id": "mv-rev-2"})
    assert r.status_code == 409 and rule_ids(r) == ["DEFINITION_IMMUTABLE"]
    assert table_digest(conn, ["metric_versions", "definition_changes"]) == before
    assert len(audit(conn, "publish-definition-refused", "m-revenue")) == 1                       # the refusal is kept in the trail
    assert conn.execute("SELECT definition FROM metric_versions WHERE metric_version_id = 'mv-rev-2'").fetchone()["definition"] == "Order amount net of refunds"


def test_c02_incomplete_checklist_warns_and_drafts_stay_out_of_coverage(lab, conn):
    r = publish_through_review(lab, {"metric_id": "m-thin", "metric_name": "Thin", "definition": "d", "grain": "", "source_fields": [], "owner_id": "own-04", "refresh": " "})
    assert r.status_code == 200 and r.json()["warnings"][0]["code"] == "DEFINITION_INCOMPLETE"
    assert "grain, source_fields, refresh" in r.json()["warnings"][0]["message"]
    command(lab, "publish-definition", {"metric_id": "m-draft", "metric_name": "D", "definition": "d", "grain": "g", "source_fields": ["a"], "owner_id": "own-04",
                                        "refresh": "daily", "status": "draft"})
    cov = get(lab, "/metrics", as_of="2026-10-06T00:00:00Z").json()["data"]["metrics"]["definition_coverage"]
    assert cov["published_metrics"] == 5 and cov["incomplete"]["m-thin"] == ["grain", "source_fields", "refresh"] and "m-draft" not in cov["incomplete"]
    assert command(lab, "publish-definition", {"metric_id": "m-z", "metric_name": "Z", "definition": "d", "grain": "g", "source_fields": [], "owner_id": "own-99",
                                               "refresh": "daily", "status": "draft"}).json()["error"]["details"][0]["rule_id"] == "UNKNOWN_OWNER"


def test_c02_needs_a_steward_or_admin(lab):
    pub = {"metric_id": "m-a", "metric_name": "A", "definition": "d", "grain": "g", "source_fields": ["a"], "owner_id": "own-04", "refresh": "daily", "status": "draft"}
    r = command(lab, "publish-definition", pub, headers=ANALYST)
    assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"]
    assert command(lab, "publish-definition", pub, headers=ADMIN).status_code == 200


# ------------------------------------------------------------------------------------------------------------ C03
def test_c03_replays_the_eight_active_rules_and_equals_the_golden_runs(lab, conn):
    want = __import__("support_db").golden_expected()["rules"]["runs"]
    for rid, exp in want.items():
        r = command(lab, "run-rule", {"rule_id": rid}, headers=ANALYST)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert (res["eligible_count"], res["failure_count"], res["rule_version"], res["weight_version"], res["severity"]) == (
            exp["eligible_count"], exp["failure_count"], exp["rule_version"], "w2", exp["severity"]), rid
        assert res["run_at"].startswith("2026-10-05T00:00:00") and res["kind"] == "scheduled"
        assert res.get("populated_count") == exp.get("populated_count") and res.get("null_fk_count") == exp.get("null_fk_count")
        stored = conn.execute("SELECT * FROM rule_runs WHERE rule_run_id = %s", (res["rule_run_id"],)).fetchone()
        assert (stored["eligible_count"], stored["failure_count"], stored["weight_version"], stored["run_by"]) == (exp["eligible_count"], exp["failure_count"], "w2", "own-01")
    assert count(conn, "rule_runs") == 13 + 8


def test_c03_comparison_and_critical_warning(lab):
    ok = command(lab, "run-rule", {"rule_id": "r-cust-complete-email"}).json()
    assert ok["result"]["comparison"]["comparable"] is True and ok["result"]["comparison"]["failure_rate_previous"] == "0.080000"   # rr-001: 8/100
    assert ok["result"]["comparison"]["failure_rate_current"] == "0.050000"
    bad = command(lab, "run-rule", {"rule_id": "r-cust-valid-email"}).json()
    assert bad["result"]["comparison"]["comparable"] is False and bad["result"]["comparison"]["reason"] == "RULE_VERSION_DIFFERS"
    assert bad["result"]["comparison"]["failure_rate_current"] is None and any(w["code"] == "RULE_VERSION_DIFFERS" for w in bad["warnings"])
    crit = command(lab, "run-rule", {"rule_id": "r-cust-key-unique"}).json()
    assert crit["result"]["failure_count"] == 2 and crit["warnings"][0]["code"] == "CRITICAL_FAILURE"


def test_c03_refusals(lab, conn):
    assert command(lab, "run-rule", {"rule_id": "r-ord-amount-range"}).json()["error"]["details"][0]["rule_id"] == "RULE_DISABLED"
    assert command(lab, "run-rule", {"rule_id": "nope"}).status_code == 404
    unk = command(lab, "run-rule", {"rule_id": "r-cust-fresh", "weight_version": "w9"})
    assert unk.status_code == 422 and rule_ids(unk) == ["UNKNOWN_WEIGHT_VERSION"]
    changed = command(lab, "run-rule", {"rule_id": "r-cust-fresh", "weights": {"completeness": "0.5", "validity": "0.5", "uniqueness": "0", "relationship": "0", "timeliness": "0"}})
    assert changed.status_code == 422 and rule_ids(changed) == ["WEIGHT_CHANGE_REQUIRES_VERSION"]
    assert len(audit(conn, "run-rule-refused")) == 1
    same = {"completeness": "0.25", "validity": "0.250000", "uniqueness": "0.25", "relationship": "0.15", "timeliness": "0.1"}
    assert command(lab, "run-rule", {"rule_id": "r-cust-fresh", "weights": same}).status_code == 200            # the same weights are not a change
    w1 = command(lab, "run-rule", {"rule_id": "r-cust-fresh", "weight_version": "w1"}).json()["result"]
    assert w1["weight_version"] == "w1"


# ------------------------------------------------------------------------------------------------------------ C04 / C05
def failing_run(lab, rule="r-cust-complete-email"):
    return command(lab, "run-rule", {"rule_id": rule}).json()["result"]["rule_run_id"]


def test_c04_opens_an_owned_issue_linked_to_run_and_severity(lab, conn):
    run = failing_run(lab)
    r = command(lab, "open-issue", {"rule_run_id": run}, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (res["owner_id"], res["severity"], res["status"], res["detected_at"], res["failing_records"]) == ("own-01", "high", "open", "2026-10-05T00:00:00Z", 5)
    row = conn.execute("SELECT * FROM issues WHERE issue_id = %s", (res["issue_id"],)).fetchone()
    assert row["rule_run_id"] == run and row["severity"] == "high" and row["record_ids"] == ["cust-011", "cust-029", "cust-047", "cust-063", "cust-088"]
    assert count(conn, "issue_events", f"issue_id = '{res['issue_id']}' AND event_type = 'detected'") == 1 and len(audit(conn, "open-issue", res["issue_id"])) == 1
    again = command(lab, "open-issue", {"rule_run_id": run})
    assert again.status_code == 409 and rule_ids(again) == ["ISSUE_ALREADY_OPEN"]


def test_c04_refusals(lab):
    clean = command(lab, "run-rule", {"rule_id": "r-cust-fresh"}).json()["result"]["rule_run_id"]           # on time at as_of: no failure
    assert command(lab, "open-issue", {"rule_run_id": clean}).json()["error"]["details"][0]["rule_id"] == "NO_FAILURE"
    assert command(lab, "open-issue", {"rule_run_id": "rr-007"}).json()["error"]["details"][0]["rule_id"] == "RUN_NOT_SCHEDULED"
    assert command(lab, "open-issue", {"rule_run_id": "nope"}).status_code == 404
    late = command(lab, "run-rule", {"rule_id": "r-ship-fresh"}).json()["result"]["rule_run_id"]              # ds-shipments: owner own-05 is inactive
    inactive = command(lab, "open-issue", {"rule_run_id": late})
    assert inactive.status_code == 422 and rule_ids(inactive) == ["OWNER_INACTIVE"]
    ok = command(lab, "open-issue", {"rule_run_id": late, "owner_id": "own-02"})
    assert ok.status_code == 200 and ok.json()["result"]["owner_id"] == "own-02"
    assert command(lab, "open-issue", {"rule_run_id": failing_run(lab), "owner_id": "own-99"}).json()["error"]["details"][0]["rule_id"] == "UNKNOWN_OWNER"


def test_c05_triage_claim_and_reopen(lab, conn):
    iid = command(lab, "open-issue", {"rule_run_id": failing_run(lab)}).json()["result"]["issue_id"]
    due = "2026-10-12T00:00:00Z"
    assert command(lab, "triage-issue", {"issue_id": iid, "owner_id": "own-02"}).json()["error"]["details"][0]["rule_id"] == "DUE_DATE_REQUIRED"
    assert command(lab, "triage-issue", {"issue_id": iid, "due_at": due}).json()["error"]["details"][0]["rule_id"] == "OWNER_REQUIRED"
    assert command(lab, "triage-issue", {"issue_id": iid, "owner_id": "own-02", "due_at": "2026-10-04T00:00:00Z"}).json()["error"]["details"][0]["rule_id"] == "DUE_BEFORE_DETECTION"
    assert command(lab, "triage-issue", {"issue_id": iid, "owner_id": "own-05", "due_at": due}).json()["error"]["details"][0]["rule_id"] == "OWNER_INACTIVE"
    t = command(lab, "triage-issue", {"issue_id": iid, "owner_id": "own-02", "due_at": due}, headers=ANALYST)
    assert t.status_code == 200 and t.json()["status"] == "triaged" and t.json()["result"]["status"] == "investigating" and t.json()["version"] == 2
    row = conn.execute("SELECT * FROM issues WHERE issue_id = %s", (iid,)).fetchone()
    assert (row["status"], row["owner_id"], row["due_at"].isoformat()) == ("investigating", "own-02", "2026-10-12T00:00:00+00:00")
    claim = command(lab, "triage-issue", {"issue_id": iid, "action": "claim"}, headers=ANALYST)
    assert claim.status_code == 200 and claim.json()["result"]["class"] == "claimed" and claim.json()["warnings"][0]["code"] == "CLAIMED_NOT_RESOLVED"
    assert command(lab, "triage-issue", {"issue_id": iid, "action": "claim"}).status_code == 409
    assert command(lab, "triage-issue", {"issue_id": iid, "owner_id": "own-02", "due_at": due}).status_code == 409          # closed: reopen first
    re = command(lab, "triage-issue", {"issue_id": iid, "action": "reopen"})
    assert re.status_code == 200 and re.json()["result"]["reopen_cycles"] == 1 and re.json()["result"]["detected_at"] == "2026-10-05T00:00:00Z"
    assert command(lab, "triage-issue", {"issue_id": iid, "action": "reopen"}).status_code == 409
    assert command(lab, "triage-issue", {"issue_id": iid, "action": "dance"}).json()["error"]["details"][0]["rule_id"] == "INVALID_ACTION"
    assert [e["event_type"] for e in conn.execute("SELECT event_type FROM issue_events WHERE issue_id = %s ORDER BY occurred_at, event_id", (iid,)).fetchall()] == [
        "detected", "triaged", "claimed", "reopened"]


# ------------------------------------------------------------------------------------------------------------ C10
def refresh_shipments(lab, at: str):
    """The shipments feed refreshed at ``at``: recorded through C12 record-refresh, as an operator would (no SQL outside the application)."""
    r = command(lab, "record-refresh", {"dataset_id": "ds-shipments", "refreshed_at": at}, headers=ANALYST)
    assert r.status_code == 200, r.text


def late_shipments_issue(lab):
    run = command(lab, "run-rule", {"rule_id": "r-ship-fresh"}).json()["result"]
    assert run["failure_count"] == 1
    iid = command(lab, "open-issue", {"rule_run_id": run["rule_run_id"], "owner_id": "own-02"}).json()["result"]["issue_id"]
    assert command(lab, "triage-issue", {"issue_id": iid, "action": "claim"}).status_code == 200
    return iid


def test_c10_resolves_only_after_a_successful_rerun_of_the_same_rule_version(lab, conn):
    iid = late_shipments_issue(lab)
    still = command(lab, "verify-remediation", {"issue_id": iid})                      # nothing was fixed: the rerun still fails
    assert still.status_code == 200 and still.json()["status"] == "claimed" and still.json()["result"]["verified"] is False
    assert still.json()["result"]["reasons"] == ["RERUN_STILL_FAILING"] and still.json()["result"]["class"] == "claimed"
    assert conn.execute("SELECT verification_run_id FROM issues WHERE issue_id = %s", (iid,)).fetchone()["verification_run_id"] is None
    assert count(conn, "rule_runs", "kind = 'rerun' AND failure_count = 1") == 1       # the failed rerun is evidence and is kept
    clock.freeze(AS_OF + timedelta(hours=12))                                         # a later day: refresh inside [04:00Z, 05:00Z)
    refresh_shipments(lab, "2026-10-05T04:30:00Z")
    ok = command(lab, "verify-remediation", {"issue_id": iid})
    res = ok.json()["result"]
    assert ok.status_code == 200 and ok.json()["status"] == "resolved" and res["verified"] is True and res["class"] == "resolved"
    run = conn.execute("SELECT * FROM rule_runs WHERE rule_run_id = %s", (res["rerun_run_id"],)).fetchone()
    assert (run["kind"], run["rerun_for_issue"], run["failure_count"], run["rule_version"]) == ("rerun", iid, 0, 1) and res["resolved_at"].startswith("2026-10-05T12:00:00")
    assert conn.execute("SELECT verification_run_id FROM issues WHERE issue_id = %s", (iid,)).fetchone()["verification_run_id"] == run["rule_run_id"]
    cls = {r["issue_id"]: r for r in get(lab, "/data/issues").json()["data"]}[iid]
    assert cls["class"] == "resolved" and cls["resolved_at"] == res["resolved_at"]
    assert command(lab, "verify-remediation", {"issue_id": iid}).json()["error"]["details"][0]["rule_id"] == "ALREADY_RESOLVED"


def test_c10_needs_a_claimed_issue_a_steward_and_a_live_rule_of_the_same_version(lab, conn):
    run = failing_run(lab)
    iid = command(lab, "open-issue", {"rule_run_id": run}).json()["result"]["issue_id"]
    not_closed = command(lab, "verify-remediation", {"issue_id": iid})
    assert not_closed.status_code == 409 and rule_ids(not_closed) == ["INVALID_STATE"]
    command(lab, "triage-issue", {"issue_id": iid, "action": "claim"})
    assert command(lab, "verify-remediation", {"issue_id": iid}, headers=ANALYST).status_code == 403
    assert command(lab, "verify-remediation", {"issue_id": "nope"}).status_code == 404
    # records are checked: the five missing e-mails are still missing, so the rerun fails on the issue's own records
    r = command(lab, "verify-remediation", {"issue_id": iid}).json()["result"]
    assert (r["eligible_count"], r["failure_count"], r["verified"]) == (5, 5, False)
    # disabling the rule is not repair: the issue stays claimed, and only a passing rerun resolves it (D-10 R7-02)
    assert command(lab, "disable-rule", {"rule_id": "r-cust-complete-email", "reason": "no longer needed"}).status_code == 200
    d = command(lab, "verify-remediation", {"issue_id": iid})
    assert d.json()["result"]["reasons"] == ["RERUN_STILL_FAILING"] and d.json()["result"]["rule_disabled"] is True and d.json()["status"] == "claimed"
    assert d.json()["result"]["rerun_run_id"] is not None and {w["code"] for w in d.json()["warnings"]} == {"RERUN_STILL_FAILING", "RULE_DISABLED"}
    cls = {r["issue_id"]: r for r in get(lab, "/data/issues").json()["data"]}[iid]["class"]
    assert cls == "claimed"


def test_c10_a_rerun_of_another_rule_version_verifies_nothing(lab, conn):
    iid = late_shipments_issue(lab)
    conn.execute("ALTER TABLE quality_rules DISABLE TRIGGER USER")
    conn.execute("UPDATE quality_rules SET version_number = 2 WHERE rule_id = 'r-ship-fresh'")
    conn.execute("ALTER TABLE quality_rules ENABLE TRIGGER USER")
    clock.freeze(AS_OF + timedelta(hours=12))
    refresh_shipments(lab, "2026-10-05T04:30:00Z")                                    # the data is fine now ...
    r = command(lab, "verify-remediation", {"issue_id": iid})
    assert r.json()["result"]["reasons"] == ["RULE_VERSION_DIFFERS"] and r.json()["status"] == "claimed"      # ... but v2 is not the rule that failed


def test_c10_reopen_then_reclaim_needs_a_new_verification(lab, conn):
    iid = late_shipments_issue(lab)
    clock.freeze(AS_OF + timedelta(hours=12))
    refresh_shipments(lab, "2026-10-05T04:30:00Z")
    assert command(lab, "verify-remediation", {"issue_id": iid}).json()["status"] == "resolved"
    clock.freeze(AS_OF + timedelta(hours=13))
    assert command(lab, "triage-issue", {"issue_id": iid, "action": "reopen"}).status_code == 200
    assert {r["issue_id"]: r for r in get(lab, "/data/issues").json()["data"]}[iid]["class"] == "open"
    clock.freeze(AS_OF + timedelta(hours=14))
    command(lab, "triage-issue", {"issue_id": iid, "action": "claim"})
    assert {r["issue_id"]: r for r in get(lab, "/data/issues").json()["data"]}[iid]["class"] == "claimed"      # the old rerun predates the reopen
    clock.freeze(AS_OF + timedelta(hours=15))
    ok = command(lab, "verify-remediation", {"issue_id": iid})
    assert ok.json()["status"] == "resolved"
    row = {r["issue_id"]: r for r in get(lab, "/data/issues").json()["data"]}[iid]
    assert row["class"] == "resolved" and row["reopen_cycles"] == 1 and row["detected_at"] == "2026-10-05T00:00:00Z"


# ------------------------------------------------------------------------------------------------------------ C06 / C07 / C08
def add_record(conn, rid, name, addr, system="web"):
    conn.execute("INSERT INTO customer_records VALUES (%s,%s,%s,%s,%s)", (rid, system, rid.upper(), name, addr))


SUGGEST = {"score": "0.910000", "features": {"name_similarity": "0.900000"}, "explanation": "similar names"}


def test_c06_suggests_a_canonical_candidate_never_a_merge(lab, conn):
    add_record(conn, "rec-011", "maria lopez", "addr-0101")
    r = command(lab, "suggest-match", {"left_record_id": "rec-001", "right_record_id": "rec-011", **SUGGEST}, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["uncertainty"] == "Shared name and address; possible household" and res["merged"] is False and res["proposed_by"] == "own-01"
    assert r.json()["warnings"][0]["code"] == "SHARED_NAME_AND_ADDRESS"
    assert count(conn, "merge_decisions") == 5 and conn.execute("SELECT left_record_id < right_record_id AS ok FROM match_candidates WHERE candidate_id = %s", (res["candidate_id"],)).fetchone()["ok"]
    diff = command(lab, "suggest-match", {"left_record_id": "rec-003", "right_record_id": "rec-005", **SUGGEST, "uncertainty": "check"}).json()["result"]
    assert diff["uncertainty"] == "check"


def test_c06_refusals_reverse_pair_both_ways_unknown_and_same(lab, conn):
    add_record(conn, "rec-011", "x", "y")
    same_orientation = command(lab, "suggest-match", {"left_record_id": "rec-001", "right_record_id": "rec-002", **SUGGEST})
    assert same_orientation.status_code == 409 and rule_ids(same_orientation) == ["DUPLICATE_PAIR"]
    reverse = command(lab, "suggest-match", {"left_record_id": "rec-002", "right_record_id": "rec-001", **SUGGEST})
    assert reverse.status_code == 409 and rule_ids(reverse) == ["DUPLICATE_PAIR"]
    assert reverse.json()["error"]["details"][0]["context"] == {"candidate_id": "cand-001"}
    wrong = command(lab, "suggest-match", {"left_record_id": "rec-011", "right_record_id": "rec-003", **SUGGEST})
    assert wrong.status_code == 422 and rule_ids(wrong) == ["NON_CANONICAL_ORDER"]
    assert wrong.json()["error"]["details"][0]["context"]["canonical"] == {"left_record_id": "rec-003", "right_record_id": "rec-011"}
    assert command(lab, "suggest-match", {"left_record_id": "rec-003", "right_record_id": "rec-003", **SUGGEST}).json()["error"]["details"][0]["rule_id"] == "SAME_RECORD"
    assert command(lab, "suggest-match", {"left_record_id": "rec-003", "right_record_id": "rec-99", **SUGGEST}).json()["error"]["details"][0]["rule_id"] == "UNKNOWN_RECORD"
    for bad in ({"score": "1.5"}, {"score": "-0.1"}, {"score": 0.5}, {"features": {}}, {"explanation": ""}):
        assert command(lab, "suggest-match", {"left_record_id": "rec-003", "right_record_id": "rec-011", **SUGGEST, **bad}).status_code == 422
    assert count(conn, "match_candidates") == 5


def test_c07_approves_a_merge_with_an_independent_reviewer(lab, conn):
    r = command(lab, "approve-merge", {"candidate_id": "cand-005"}, headers=STEWARD)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (r.json()["status"], res["state"], res["reviewer_id"], res["proposed_by"], res["maps"]) == (
        "linked", "linked", "own-02", "own-01", {"from_record_id": "rec-010", "to_record_id": "rec-009"})
    assert res["decided_at"].startswith("2026-10-05T00:00:00") and len(audit(conn, "approve-merge", res["merge_id"])) == 1
    assert get(lab, "/data/identity_map").json()["data"]["identity_map"]["rec-010"] == "rec-009"
    again = command(lab, "approve-merge", {"candidate_id": "cand-005"}, headers=ADMIN)
    assert again.status_code == 409 and rule_ids(again) == ["ALREADY_REVIEWED"]
    prior = command(lab, "approve-merge", {"candidate_id": "cand-004", "decision": "reject"}, headers=ADMIN)       # md-4 already rejected it
    assert prior.status_code == 409 and prior.json()["error"]["details"][0]["context"] == {"merge_id": "md-4", "decision": "reject"}
    add_record(conn, "rec-011", "other person", "addr-9")
    cid = command(lab, "suggest-match", {"left_record_id": "rec-003", "right_record_id": "rec-011", **SUGGEST}, headers=ANALYST).json()["result"]["candidate_id"]
    rej = command(lab, "approve-merge", {"candidate_id": cid, "decision": "reject", "reason": "different people"}, headers=ADMIN)
    assert rej.status_code == 200 and rej.json()["status"] == "rejected" and rej.json()["result"]["maps"] is None
    assert get(lab, "/data/identity_map").json()["data"]["identity_map"]["rec-011"] == "rec-011"


def test_c07_a_proposer_cannot_decide_their_own_candidate_and_the_refusal_is_kept(lab, conn):
    """D-10 R7-03, through the API with separate registered identities: own-02 (a steward) proposes, own-02 cannot approve (409 SELF_REVIEW, audited),
    own-03 (another steward) can."""
    add_record(conn, "rec-011", "other person", "addr-9")
    cid = command(lab, "suggest-match", {"left_record_id": "rec-003", "right_record_id": "rec-011", **SUGGEST}, headers=STEWARD).json()["result"]["candidate_id"]
    r = command(lab, "approve-merge", {"candidate_id": cid}, headers=STEWARD)
    assert r.status_code == 409 and rule_ids(r) == ["SELF_REVIEW"] and r.json()["error"]["code"] == "SELF_REVIEW"
    assert count(conn, "merge_decisions") == 5
    refusal = audit(conn, "approve-merge-refused", cid)
    assert len(refusal) == 1 and refusal[0]["actor_id"] == "own-02" and refusal[0]["details"]["rule_id"] == "SELF_REVIEW"
    ok = command(lab, "approve-merge", {"candidate_id": cid}, headers=STEWARD2)
    assert ok.status_code == 200 and ok.json()["result"]["reviewer_id"] == "own-03" and ok.json()["result"]["proposed_by"] == "own-02"
    # the golden proposer own-01 is an analyst: an analyst cannot decide at all, and cannot claim to be a steward
    assert command(lab, "approve-merge", {"candidate_id": "cand-005"}, headers=ANALYST).status_code == 403
    claim = command(lab, "approve-merge", {"candidate_id": "cand-005"}, headers={"X-Actor-Id": "own-01", "X-Actor-Role": "steward"})
    assert claim.status_code == 403 and rule_ids(claim) == ["ROLE_MISMATCH"] and count(conn, "merge_decisions") == 6
    assert command(lab, "approve-merge", {"candidate_id": "nope"}).status_code == 404
    assert command(lab, "approve-merge", {"candidate_id": "cand-005", "decision": "maybe"}).json()["error"]["details"][0]["rule_id"] == "INVALID_DECISION"


def test_c07_a_merged_away_record_cannot_be_merged_again(lab, conn):
    add_record(conn, "rec-011", "maria lopez", "addr-0101")
    cid = command(lab, "suggest-match", {"left_record_id": "rec-002", "right_record_id": "rec-011", **SUGGEST}, headers=ANALYST).json()["result"]["candidate_id"]
    clash = command(lab, "approve-merge", {"candidate_id": cid})        # rec-002 was merged into rec-001 by md-1: it is not a target
    assert clash.status_code == 409 and rule_ids(clash) == ["RECORD_ALREADY_MERGED"]
    sibling = command(lab, "suggest-match", {"left_record_id": "rec-001", "right_record_id": "rec-011", **SUGGEST}, headers=ANALYST).json()["result"]["candidate_id"]
    assert command(lab, "approve-merge", {"candidate_id": sibling}).status_code == 200          # a second record into rec-001 is fine


def test_c08_reverses_a_merge_restoring_both_identities_and_keeping_history(lab, conn):
    r = command(lab, "reverse-merge", {"merge_id": "md-1", "reason": "different customers after all"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["restored"] == {"rec-001": "rec-001", "rec-002": "rec-002"} and r.json()["status"] == "reversed"
    m = get(lab, "/data/identity_map").json()["data"]
    assert m["identity_map"]["rec-002"] == "rec-002" and m["merges_reversed"] == 2 and m["active_merges"] == 1
    hist = {h["merge_id"]: h for h in m["mapping_history"]}
    assert hist["md-1"]["state"] == "reversed" and hist["md-1"]["reversed_by"] == r.json()["result"]["merge_id"] and hist["md-1"]["from_record_id"] == "rec-002"
    assert conn.execute("SELECT decision FROM merge_decisions WHERE merge_id = 'md-1'").fetchone()["decision"] == "approve"      # the approval is kept
    # the approval stays in precision (a reversal does not remove it)
    assert get(lab, "/metrics", as_of="2026-10-06T00:00:00Z").json()["data"]["metrics"]["match_precision"]["approved_decisions"] == 3
    assert len(audit(conn, "reverse-merge")) == 1


def test_c08_refusals(lab, conn):
    assert command(lab, "reverse-merge", {"merge_id": "md-3", "reason": "again"}).json()["error"]["details"][0]["rule_id"] == "ALREADY_REVERSED"
    assert command(lab, "reverse-merge", {"merge_id": "md-4", "reason": "undo"}).json()["error"]["details"][0]["rule_id"] == "NOT_AN_APPROVAL"
    assert command(lab, "reverse-merge", {"merge_id": "md-5", "reason": "undo"}).json()["error"]["details"][0]["rule_id"] == "NOT_AN_APPROVAL"
    assert command(lab, "reverse-merge", {"merge_id": "md-1", "reason": "  "}).json()["error"]["details"][0]["rule_id"] == "REASON_REQUIRED"
    assert command(lab, "reverse-merge", {"merge_id": "nope", "reason": "x"}).status_code == 404
    assert command(lab, "reverse-merge", {"merge_id": "md-1", "reason": "x"}, headers=ANALYST).status_code == 403
    add_record(conn, "rec-011", "other person", "addr-9")           # a steward who proposed a pair cannot reverse its merge either
    cid = command(lab, "suggest-match", {"left_record_id": "rec-003", "right_record_id": "rec-011", **SUGGEST}, headers=STEWARD).json()["result"]["candidate_id"]
    mid = command(lab, "approve-merge", {"candidate_id": cid}, headers=STEWARD2).json()["result"]["merge_id"]
    own = command(lab, "reverse-merge", {"merge_id": mid, "reason": "x"}, headers=STEWARD)
    assert own.status_code == 409 and rule_ids(own) == ["SELF_REVIEW"]
    assert count(conn, "merge_decisions") == 6


# ------------------------------------------------------------------------------------------------------------ C09
def test_c09_disables_a_rule_keeping_history_and_open_issues(lab, conn):
    runs_before = count(conn, "rule_runs", "rule_id = 'r-cust-complete-email'")
    r = command(lab, "disable-rule", {"rule_id": "r-cust-complete-email", "reason": "replaced by the contract check"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (res["status"], res["runs_retained"], res["unresolved_issues"]) == ("disabled", runs_before, 1) and r.json()["warnings"][0]["code"] == "DISABLING_IS_NOT_REPAIR"
    row = conn.execute("SELECT * FROM quality_rules WHERE rule_id = 'r-cust-complete-email'").fetchone()
    assert (row["status"], row["disabled_reason"]) == ("disabled", "replaced by the contract check") and row["disabled_at"] == AS_OF
    assert count(conn, "rule_runs", "rule_id = 'r-cust-complete-email'") == runs_before                  # history retained
    assert {i["issue_id"]: i["class"] for i in get(lab, "/data/issues").json()["data"]}["iss-005"] == "open"      # the open issue stays open
    m = get(lab, "/metrics", as_of="2026-10-06T00:00:00Z").json()["data"]
    assert "r-cust-complete-email" in m["rules"]["disabled"] and m["rules"]["disabled"]["r-cust-complete-email"]["runs_retained"] == runs_before
    assert "r-cust-complete-email" not in m["metrics"]["completeness"] and m["rules"]["active_count"] == 7
    assert len(audit(conn, "disable-rule", "r-cust-complete-email")) == 1
    assert command(lab, "disable-rule", {"rule_id": "r-cust-complete-email", "reason": "again"}).json()["error"]["details"][0]["rule_id"] == "RULE_ALREADY_DISABLED"
    assert command(lab, "run-rule", {"rule_id": "r-cust-complete-email"}).status_code == 409


def test_c09_needs_a_reason_and_a_steward(lab):
    assert command(lab, "disable-rule", {"rule_id": "r-cust-fresh", "reason": " "}).json()["error"]["details"][0]["rule_id"] == "REASON_REQUIRED"
    assert command(lab, "disable-rule", {"rule_id": "r-cust-fresh", "reason": "x"}, headers=ANALYST).status_code == 403
    assert command(lab, "disable-rule", {"rule_id": "nope", "reason": "x"}).status_code == 404


# ------------------------------------------------------------------------------------------------------------ envelope, roles, idempotency
def test_identity_roles_and_envelope_errors(lab):
    body = {"request_id": "r1", "dataset_version": "x", "idempotency_key": "k1", "input": {"rule_id": "r-cust-fresh"}}
    from api.app import PREFIX
    assert lab.post(f"{PREFIX}/commands/run-rule", json=body).status_code == 401
    assert lab.post(f"{PREFIX}/commands/run-rule", json=body, headers={"X-Actor-Id": "own-01", "X-Actor-Role": "root"}).status_code == 403
    assert lab.post(f"{PREFIX}/commands/run-rule", json=body, headers={"X-Actor-Id": " ", "X-Actor-Role": "admin"}).status_code == 401
    # D-10 R7-03: the actor is a registered owner, exactly; the role is the register's; an inactive owner cannot act
    unknown = lab.post(f"{PREFIX}/commands/run-rule", json=body, headers={"X-Actor-Id": "usr-nobody", "X-Actor-Role": "admin"})
    assert unknown.status_code == 401 and rule_ids(unknown) == ["UNKNOWN_ACTOR"]
    for odd in ("OWN-02", "own-2", "own-02x", "own_02"):                                           # no case folding, no near match
        assert lab.post(f"{PREFIX}/commands/run-rule", json=body, headers={"X-Actor-Id": odd, "X-Actor-Role": "steward"}).status_code == 401, odd
    mismatch = lab.post(f"{PREFIX}/commands/run-rule", json=body, headers={"X-Actor-Id": "own-01", "X-Actor-Role": "admin"})
    assert mismatch.status_code == 403 and rule_ids(mismatch) == ["ROLE_MISMATCH"] and mismatch.json()["error"]["details"][0]["context"] == {"registered_role": "analyst"}
    inactive = lab.post(f"{PREFIX}/commands/run-rule", json=body, headers=INACTIVE)
    assert inactive.status_code == 403 and rule_ids(inactive) == ["ACTOR_INACTIVE"]
    assert lab.post(f"{PREFIX}/commands/nothing", json=body, headers=ADMIN).status_code == 404
    forbidden = lab.post(f"{PREFIX}/commands/disable-rule", json={"junk": 1}, headers=ANALYST)       # the role is checked before the body is read
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "FORBIDDEN"
    bad = lab.post(f"{PREFIX}/commands/run-rule", json={"request_id": "r9", "idempotency_key": "k 1", "input": {"rule_id": "r", "extra": 1}}, headers=ADMIN)
    assert bad.status_code == 422 and bad.json()["request_id"] == "r9"
    assert {"FIELD_REQUIRED", "IDEMPOTENCY_KEY_INVALID", "FIELD_UNEXPECTED"} <= set(rule_ids(bad))
    assert lab.post(f"{PREFIX}/commands/run-rule", content=b"{not json", headers={**ADMIN, "content-type": "application/json"}).status_code == 422
    ok = lab.post(f"{PREFIX}/commands/run-rule", json={**body, "dataset_version": __import__("support_db").current_dataset_version()}, headers=ANALYST)
    assert ok.status_code == 200 and set(ok.json()) == {"command_id", "status", "result", "warnings", "version"}


def test_idempotency_replay_reuse_and_actor_binding(lab, conn):
    first = command(lab, "run-rule", {"rule_id": "r-cust-fresh"}, key="idem-1", headers=ANALYST)
    n = count(conn, "rule_runs")
    replay = command(lab, "run-rule", {"rule_id": "r-cust-fresh"}, key="idem-1", headers=ANALYST)
    assert replay.status_code == 200 and replay.json() == first.json() and replay.headers["Idempotent-Replay"] == "true"
    assert count(conn, "rule_runs") == n and "Idempotent-Replay" not in first.headers
    other_payload = command(lab, "run-rule", {"rule_id": "r-cust-fresh", "weight_version": "w1"}, key="idem-1", headers=ANALYST)
    assert other_payload.status_code == 409 and rule_ids(other_payload) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]
    other_actor = command(lab, "run-rule", {"rule_id": "r-cust-fresh"}, key="idem-1", headers=STEWARD2)
    assert other_actor.status_code == 409 and rule_ids(other_actor) == ["IDEMPOTENCY_ACTOR_MISMATCH"]
    other_role = command(lab, "run-rule", {"rule_id": "r-cust-fresh"}, key="idem-1", headers={"X-Actor-Id": "own-01", "X-Actor-Role": "admin"})
    assert other_role.status_code == 403 and rule_ids(other_role) == ["ROLE_MISMATCH"]          # the role is the register's: it cannot be a second binding
    other_version = command(lab, "run-rule", {"rule_id": "r-cust-fresh"}, key="idem-1", headers=ANALYST, dataset_version="ds-other")
    assert other_version.status_code == 409                                              # a different dataset_version is a different request
    assert count(conn, "rule_runs") == n


def test_stale_dataset_version_is_409_and_nothing_is_written(lab, conn):
    before = table_digest(conn, ["rule_runs", "audit_events", "command_results"])
    r = command(lab, "run-rule", {"rule_id": "r-cust-fresh"}, dataset_version="ds-old")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_DATASET_VERSION" and rule_ids(r) == ["STALE_DATASET_VERSION"]
    ctx = r.json()["error"]["details"][0]["context"]
    assert ctx["requested"] == "ds-old" and ctx["current"].startswith("ds-")
    assert table_digest(conn, ["rule_runs", "audit_events", "command_results"]) == before
    assert command(lab, "run-rule", {"rule_id": "r-cust-fresh"}, dataset_version=ctx["current"]).status_code == 200


def test_every_command_writes_exactly_one_audit_row_and_a_failure_writes_none(lab, conn):
    n0 = count(conn, "audit_events")
    assert command(lab, "run-rule", {"rule_id": "r-cust-fresh"}).status_code == 200
    assert count(conn, "audit_events") == n0 + 1 and count(conn, "command_results") == 1
    assert command(lab, "run-rule", {"rule_id": "r-ord-amount-range"}).status_code == 409
    assert count(conn, "audit_events") == n0 + 1 and count(conn, "command_results") == 1                   # the refusal stored nothing
    a = conn.execute("SELECT * FROM audit_events ORDER BY occurred_at DESC LIMIT 1").fetchone()
    assert (a["entity_type"], a["action"], a["actor_id"], a["actor_role"], a["request_id"]) == ("rule_run", "run-rule", "own-02", "steward", "req-test")
