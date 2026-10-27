"""Adversarial cases P07-TEST-01..12 end to end (API over PostgreSQL), plus concurrency, stale-dataset, key-reuse and hostile-input cases.
Domain-level versions of the same rules are in test_rules.py; here the refusal, its status and its envelope are the point."""
import threading
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from api import clock
from api import commands as cmds
from support_db import (ADMIN, ANALYST, STEWARD, STEWARD2, client, command, conn, count, current_dataset_version, db_url, get, golden_inputs, publish_through_review,  # noqa: F401
                        load, metrics, rule_ids, table_digest)

AS_OF = datetime(2026, 10, 5, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def lab(client, conn):
    load(conn, golden_inputs())
    clock.freeze(AS_OF)
    return client


def snapshot(lab):
    return metrics(lab, as_of="2026-10-05T00:00:00Z")["data"]["metrics"]


def test_01_a_score_above_95_never_hides_a_critical_key_failure(lab):
    m = snapshot(lab)
    ws = m["weighted_score"]["datasets"]["ds-customers"]
    assert float(ws["value"]) > 0.95                                                       # (test arithmetic only: the API never returns a float)
    assert ws["critical_override"] is True and ws["critical_failures"] == 2 and ws["critical_open_issues"] == 1
    assert m["critical_failures"] == {"failures": 2, "open_issues": 1, "datasets_overridden": 1, "carried": []}
    for wv in ("w1", "w2"):                                                                # whatever the weights, the override stays
        again = metrics(lab, as_of="2026-10-05T00:00:00Z", weight_version=wv)["data"]["metrics"]["weighted_score"]["datasets"]["ds-customers"]
        assert again["critical_override"] is True and float(again["value"]) > 0.95
    r = command(lab, "run-rule", {"rule_id": "r-cust-key-unique"})
    assert r.json()["warnings"][0]["code"] == "CRITICAL_FAILURE"
    warns = get(lab, "/metrics", as_of="2026-10-05T00:00:00Z").json()["warnings"]
    assert "CRITICAL_OVERRIDE" in {w["code"] for w in warns}


def test_02_disabling_a_rule_retains_its_runs_and_issues_and_it_is_not_repair(lab, conn):
    before = table_digest(conn, ["rule_runs", "issues"])
    assert command(lab, "disable-rule", {"rule_id": "r-cust-key-unique", "reason": "noise"}).status_code == 200
    assert table_digest(conn, ["rule_runs", "issues"]) == before                            # not a row of history changed
    m = snapshot(lab)
    # D-10 R7-02: disabling is not repair. The failure of the rule's latest run (rr-003, 2 rows) is carried with the override, beside the open issue
    assert m["critical_failures"] == {"failures": 2, "open_issues": 1, "datasets_overridden": 1,
                                      "carried": [{"dataset_id": "ds-customers", "rule_id": "r-cust-key-unique", "rule_run_id": "rr-003", "failure_count": 2}]}
    assert m["weighted_score"]["datasets"]["ds-customers"]["critical_override"] is True and m["weighted_score"]["datasets"]["ds-customers"]["critical_failures"] == 2
    assert {i["issue_id"]: i["class"] for i in get(lab, "/data/issues").json()["data"]}["iss-006"] == "open"
    assert [r["rule_run_id"] for r in get(lab, "/data/rule_runs", rule_id="r-ord-amount-range").json()["data"]] == ["rr-004", "rr-005"]    # an older disabled rule
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("DELETE FROM rule_runs WHERE rule_run_id = 'rr-004'")
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("UPDATE quality_rules SET status = 'active', disabled_at = NULL, disabled_reason = NULL WHERE rule_id = 'r-ord-amount-range'")


def test_03_a_pair_sharing_name_and_address_is_never_merged_automatically(lab, conn):
    conn.execute("INSERT INTO customer_records VALUES ('rec-011', 'web', 'W-9', 'maria lopez', 'addr-0101')")
    decisions = count(conn, "merge_decisions")
    r = command(lab, "suggest-match", {"left_record_id": "rec-001", "right_record_id": "rec-011", "score": "0.990000", "features": {"name_similarity": "1.000000",
                "address_match": "1.000000"}, "explanation": "identical name and address"}, headers=ANALYST)
    assert r.status_code == 200 and r.json()["result"]["merged"] is False and r.json()["result"]["uncertainty"]
    assert count(conn, "merge_decisions") == decisions                                      # a score of 0.99 decides nothing
    m = get(lab, "/data/identity_map").json()["data"]["identity_map"]
    assert m["rec-011"] == "rec-011"
    cid = r.json()["result"]["candidate_id"]
    assert command(lab, "approve-merge", {"candidate_id": cid}, headers=ANALYST).status_code == 403    # only a human steward decides, never the proposer
    assert command(lab, "approve-merge", {"candidate_id": cid}, headers={"X-Actor-Id": "own-01", "X-Actor-Role": "steward"}).status_code == 403
    assert command(lab, "approve-merge", {"candidate_id": cid}, headers=STEWARD).status_code == 200


def test_04_null_foreign_keys_are_counted_separately_never_dropped(lab):
    r = snapshot(lab)["relationship_integrity"]["r-ord-cust-fk"]
    assert (r["total_fk_count"], r["null_fk_count"], r["eligible_count"], r["matched_count"], r["value"]) == (40, 3, 37, 35, "0.945946")     # 2 nulls and 1 empty string are missing: counted apart
    run = command(lab, "run-rule", {"rule_id": "r-ord-cust-fk"}).json()["result"]
    assert (run["eligible_count"], run["null_fk_count"], run["failure_count"]) == (37, 3, 2)            # the run says it too, and 35/40 or 37/40 would be wrong
    assert r["value"] not in ("0.875000", "0.925000")


def test_05_a_weight_change_without_a_new_version_is_refused(lab, conn):
    weights = {"completeness": "0.5", "validity": "0.2", "uniqueness": "0.1", "relationship": "0.1", "timeliness": "0.1"}
    r = command(lab, "run-rule", {"rule_id": "r-cust-fresh", "weight_version": "w2", "weights": weights})
    assert r.status_code == 422 and rule_ids(r) == ["WEIGHT_CHANGE_REQUIRES_VERSION"] and count(conn, "rule_runs") == 13
    with pytest.raises(psycopg.errors.IntegrityError):                                       # nor can the database be edited in place
        conn.execute("UPDATE rule_weight_versions SET weights = %s::jsonb WHERE weight_version = 'w2'", ('{"completeness": "0.5"}',))
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("DELETE FROM rule_weight_versions WHERE weight_version = 'w1'")
    with pytest.raises(psycopg.errors.CheckViolation):                                       # and a new version must be a complete set that sums to 1
        conn.execute("INSERT INTO rule_weight_versions VALUES ('w3', now(), %s::jsonb)", ('{"completeness": "0.5", "validity": "0.2", "uniqueness": "0.1", "relationship": "0.1", "timeliness": "0.2"}',))
    conn.execute("INSERT INTO rule_weight_versions VALUES ('w3', '2026-10-01T00:00:00Z', %s::jsonb)",
                 ('{"completeness": "0.5", "validity": "0.2", "uniqueness": "0.1", "relationship": "0.1", "timeliness": "0.1"}',))
    ok = command(lab, "run-rule", {"rule_id": "r-cust-fresh", "weight_version": "w3", "weights": weights})
    assert ok.status_code == 200 and ok.json()["result"]["weight_version"] == "w3"           # the named new version is what makes it legitimate
    assert metrics(lab, as_of="2026-10-05T00:00:00Z")["data"]["weight_version"] == "w3"       # in force from its valid_from


def test_06_a_merge_is_reversible_and_the_history_is_kept(lab, conn):
    first = command(lab, "approve-merge", {"candidate_id": "cand-005"}, headers=STEWARD).json()["result"]["merge_id"]
    assert get(lab, "/data/identity_map").json()["data"]["identity_map"]["rec-010"] == "rec-009"
    rev = command(lab, "reverse-merge", {"merge_id": first, "reason": "different households"}, headers=STEWARD2)
    assert rev.status_code == 200
    data = get(lab, "/data/identity_map").json()["data"]
    assert data["identity_map"]["rec-009"] == "rec-009" and data["identity_map"]["rec-010"] == "rec-010"          # both identities restored
    hist = {h["merge_id"]: h for h in data["mapping_history"]}
    assert hist[first]["state"] == "reversed" and hist[first]["reversed_by"] == rev.json()["result"]["merge_id"]    # the mapping stays on record
    assert count(conn, "merge_decisions") == 7
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("DELETE FROM merge_decisions WHERE merge_id = %s", (first,))


def test_07_an_inactive_owner_leaves_the_dataset_uncovered(lab):
    o = snapshot(lab)["ownership_coverage"]
    assert (o["covered"], o["datasets"], o["value"], o["uncovered"]) == (4, 5, "0.800000", ["ds-shipments"])
    assert command(lab, "register-dataset", {"dataset_id": "d-x", "dataset_name": "x", "source_system": "s", "owner_id": "own-05", "classification": "internal"}).status_code == 422
    assert command(lab, "register-dataset", {"dataset_id": "d-x", "dataset_name": "x", "source_system": "s", "owner_id": "own-03", "classification": "internal"}).status_code == 200
    # the owner who was active becomes inactive later: the dataset turns uncovered from that instant
    assert metrics(lab, as_of="2026-09-14T00:00:00Z")["data"]["metrics"]["ownership_coverage"]["uncovered"] == []
    assert metrics(lab, as_of="2026-09-15T00:00:00Z")["data"]["metrics"]["ownership_coverage"]["uncovered"] == ["ds-shipments"]


def test_08_an_inferred_edge_is_never_styled_observed(lab, conn):
    lc = snapshot(lab)["lineage_coverage"]
    assert lc["inferred_edges"] == [{"source_dataset_id": "ds-products", "target_dataset_id": "ds-shipments"}]
    assert lc["declared_not_observed"] == lc["inferred_edges"] and lc["value"] == "0.833333"
    rows = {e["edge_id"]: e for e in get(lab, "/data/lineage_edges").json()["data"]}
    assert rows["ei-1"]["evidence_type"] == "inferred" and rows["ei-1"]["observed_at"] is None
    assert {e["evidence_type"] for e in rows.values()} == {"declared", "observed", "inferred"}
    assert all((e["evidence_type"] == "observed") == (e["observed_at"] is not None) for e in rows.values())
    assert get(lab, "/data/lineage_edges", evidence_type="observed").json()["meta"]["total_count"] == 7        # 7 observed rows, 6 distinct pairs
    with pytest.raises(psycopg.errors.CheckViolation):                                       # the database refuses an observed edge with no observation
        conn.execute("INSERT INTO lineage_edges VALUES ('x', 'ds-products', 'ds-orders', 'observed', NULL)")
    with pytest.raises(psycopg.errors.CheckViolation):                                       # and an inferred edge that claims an observation time
        conn.execute("INSERT INTO lineage_edges VALUES ('y', 'ds-products', 'ds-orders', 'inferred', now())")


def test_09_an_issue_closed_without_a_rerun_stays_claimed(lab, conn):
    issues = {i["issue_id"]: i for i in get(lab, "/data/issues").json()["data"]}
    assert issues["iss-004"]["class"] == "claimed" and issues["iss-004"]["resolved_at"] is None
    r = snapshot(lab)["resolution_time"]
    assert (r["resolved_count"], r["claimed_count"], r["open_count"]) == (3, 1, 2) and r["issues"]["iss-004"]["claimed_hours"] == "81.0000"
    assert "iss-004" not in {k for k, v in r["issues"].items() if v["class"] == "resolved"} and r["mean_hours"] == "38.4444"
    with pytest.raises(psycopg.errors.IntegrityError):                                       # the database will not accept a "resolution" that is not a successful rerun
        conn.execute("UPDATE issues SET verification_run_id = 'rr-005' WHERE issue_id = 'iss-004'")
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("UPDATE issues SET verification_run_id = 'rr-007' WHERE issue_id = 'iss-004'")   # a rerun of another issue and rule
    # disabling the rule (iss-004's rule is already disabled) is not repair: verification is refused as not verified
    claimed = command(lab, "verify-remediation", {"issue_id": "iss-004"})
    assert claimed.status_code == 200 and claimed.json()["result"]["reasons"] == ["RULE_NOT_MEASURABLE"] and claimed.json()["status"] == "claimed"
    assert claimed.json()["result"]["rule_disabled"] is True and claimed.json()["result"]["rerun_run_id"] is None      # a pattern-less rule has nothing to rerun
    assert snapshot(lab)["resolution_time"]["issues"]["iss-004"]["class"] == "claimed"


def test_10_the_duplicate_pair_is_refused_both_ways(lab, conn):
    body = {"score": "0.5", "features": {"f": "1"}, "explanation": "again"}
    n = count(conn, "match_candidates")
    for a, b in (("rec-001", "rec-002"), ("rec-002", "rec-001"), ("rec-009", "rec-010"), ("rec-010", "rec-009")):
        r = command(lab, "suggest-match", {"left_record_id": a, "right_record_id": b, **body})
        assert r.status_code == 409 and rule_ids(r) == ["DUPLICATE_PAIR"], (a, b)
    assert count(conn, "match_candidates") == n
    with pytest.raises(psycopg.errors.IntegrityError):                                       # nor can the database hold the reverse twin or a second copy
        conn.execute("INSERT INTO match_candidates VALUES ('x1', 'rec-002', 'rec-001', 0.5, '{\"f\": 1}', 'x', NULL, 'p', now())")
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("INSERT INTO match_candidates VALUES ('x2', 'rec-001', 'rec-002', 0.5, '{\"f\": 1}', 'x', NULL, 'p', now())")


def test_11_a_published_definition_is_never_rewritten_in_place(lab, conn):
    before = table_digest(conn, ["metric_versions", "definition_changes"])
    r = command(lab, "publish-definition", {"metric_id": "m-revenue", "metric_name": "Net revenue", "definition": "rewritten", "grain": "order", "source_fields": ["x"],
                                            "owner_id": "own-04", "refresh": "daily", "reason": "edit", "metric_version_id": "mv-rev-1", "status": "draft"})
    assert r.status_code == 409 and rule_ids(r) == ["DEFINITION_IMMUTABLE"]
    assert table_digest(conn, ["metric_versions", "definition_changes"]) == before
    for sql in ("UPDATE metric_versions SET definition = 'x' WHERE metric_version_id = 'mv-rev-2'", "DELETE FROM metric_versions WHERE metric_version_id = 'mv-rev-1'",
                "UPDATE definition_changes SET reason = 'x'"):
        with pytest.raises(psycopg.errors.IntegrityError):
            conn.execute(sql)
    ok = publish_through_review(lab, {"metric_id": "m-revenue", "metric_name": "Net revenue", "definition": "net of refunds and chargebacks", "grain": "order",
                                      "source_fields": ["orders.amount"], "owner_id": "own-04", "refresh": "daily"}, reason="chargebacks are netted")
    assert ok.status_code == 200 and ok.json()["result"]["version_number"] == 5          # v3 draft, v4 reviewed, v5 published (the golden m-revenue has 2 versions)
    d = metrics(lab, as_of="2026-10-06T00:00:00Z")["data"]["definitions"]
    assert d["version_counts"]["m-revenue"] == 5 and d["effective_at_as_of"]["m-revenue"] == "mv-m-revenue-5" and d["effective_at_probe"]["m-revenue"] == "mv-rev-1"
    assert d["versions_without_change_record"] == [] and d["changes_with_mismatched_valid_from"] == []


def test_12_a_denominator_change_is_flagged_as_not_comparable(lab):
    r = command(lab, "run-rule", {"rule_id": "r-cust-valid-email"})                          # v2 now; the last scheduled run was v1 with 92 eligible
    c = r.json()["result"]["comparison"]
    assert (c["comparable"], c["reason"], c["previous_rule_version"], c["current_rule_version"]) == (False, "RULE_VERSION_DIFFERS", 1, 2)
    assert (c["previous_eligible_count"], c["current_eligible_count"]) == (92, 100) and c["failure_rate_previous"] is None
    runs = {x["rule_id"]: x for x in get(lab, "/data/comparable_runs").json()["data"]}
    assert runs["r-cust-valid-email"]["current_rule_version"] == 2
    # the same rule at the same version stays comparable even though its null foreign keys shrank the denominator (documented: null FKs are excluded in both)
    fk = command(lab, "run-rule", {"rule_id": "r-ord-cust-fk"}).json()["result"]["comparison"]
    assert fk["comparable"] is True and (fk["previous_eligible_count"], fk["current_eligible_count"]) == (36, 37)
    assert metrics(lab, as_of="2026-10-05T00:00:00Z")["data"]["rules"]["comparisons"]["r-cust-valid-email"]["comparable"] is False


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


def test_two_approvals_of_one_candidate_leave_one_decision(lab, conn):
    out = _race(lambda i: command(_client(), "approve-merge", {"candidate_id": "cand-005"}, key=f"appr-{i}", headers=(STEWARD, STEWARD2)[i]))
    assert sorted(r.status_code for r in out) == [200, 409], [r.text for r in out]
    assert count(conn, "merge_decisions", "candidate_id = 'cand-005'") == 1 and count(conn, "audit_events", "action = 'approve-merge'") == 1
    assert [r.json()["error"]["details"][0]["rule_id"] for r in out if r.status_code == 409] == ["ALREADY_REVIEWED"]


def test_two_approve_and_reject_decisions_of_one_candidate_leave_one(lab, conn):
    out = _race(lambda i: command(_client(), "approve-merge", {"candidate_id": "cand-005", "decision": ("approve", "reject")[i]}, key=f"ar-{i}"))
    assert sorted(r.status_code for r in out) == [200, 409] and count(conn, "merge_decisions", "candidate_id = 'cand-005'") == 1


def test_two_runs_of_one_rule_at_once_are_both_stored_with_distinct_ids(lab, conn):
    n = count(conn, "rule_runs", "rule_id = 'r-cust-complete-email'")
    out = _race(lambda i: command(_client(), "run-rule", {"rule_id": "r-cust-complete-email"}, key=f"run-{i}"), 4)
    assert [r.status_code for r in out] == [200] * 4, [r.text for r in out]
    ids = {r.json()["result"]["rule_run_id"] for r in out}
    assert len(ids) == 4 and count(conn, "rule_runs", "rule_id = 'r-cust-complete-email'") == n + 4
    assert {(r.json()["result"]["eligible_count"], r.json()["result"]["failure_count"]) for r in out} == {(100, 5)}


def test_two_threads_opening_one_issue_and_disabling_one_rule_leave_one(lab, conn):
    run = command(lab, "run-rule", {"rule_id": "r-cust-complete-email"}).json()["result"]["rule_run_id"]
    out = _race(lambda i: command(_client(), "open-issue", {"rule_run_id": run}, key=f"oi-{i}"))
    assert sorted(r.status_code for r in out) == [200, 409] and count(conn, "issues", f"rule_run_id = '{run}'") == 1
    out = _race(lambda i: command(_client(), "disable-rule", {"rule_id": "r-cust-fresh", "reason": f"r{i}"}, key=f"dr-{i}"))
    assert sorted(r.status_code for r in out) == [200, 409] and count(conn, "audit_events", "action = 'disable-rule'") == 1


def test_a_disable_and_a_run_of_the_same_rule_serialise_without_a_deadlock(lab, conn):
    out = _race(lambda i: command(_client(), *(("run-rule", {"rule_id": "r-cust-fresh"}), ("disable-rule", {"rule_id": "r-cust-fresh", "reason": "x"}))[i], key=f"mix-{i}"))
    assert all(r.status_code in (200, 409) for r in out), [r.text for r in out]
    assert count(conn, "quality_rules", "rule_id = 'r-cust-fresh' AND status = 'disabled'") == 1


def test_two_verifications_and_two_suggestions_race_to_one_result(lab, conn):
    clock.freeze(AS_OF)
    run = command(lab, "run-rule", {"rule_id": "r-ship-fresh"}).json()["result"]["rule_run_id"]
    iid = command(lab, "open-issue", {"rule_run_id": run, "owner_id": "own-02"}).json()["result"]["issue_id"]
    command(lab, "triage-issue", {"issue_id": iid, "action": "claim"})
    clock.freeze(AS_OF + timedelta(hours=12))
    assert command(lab, "record-refresh", {"dataset_id": "ds-shipments", "refreshed_at": "2026-10-05T04:30:00Z"}, headers=ANALYST).status_code == 200
    out = _race(lambda i: command(_client(), "verify-remediation", {"issue_id": iid}, key=f"v-{i}", headers=(STEWARD, STEWARD2)[i]))
    assert sorted(r.status_code for r in out) == [200, 409], [r.text for r in out]
    assert count(conn, "rule_runs", f"kind = 'rerun' AND rerun_for_issue = '{iid}'") == 1
    conn.execute("INSERT INTO customer_records VALUES ('rec-011', 'web', 'W9', 'zed', 'addr-9')")
    body = {"left_record_id": "rec-003", "right_record_id": "rec-011", "score": "0.5", "features": {"f": "1"}, "explanation": "x"}
    out = _race(lambda i: command(_client(), "suggest-match", body, key=f"sm-{i}", headers=ANALYST))
    assert sorted(r.status_code for r in out) == [200, 409] and count(conn, "match_candidates") == 6


def test_the_same_idempotency_key_raced_executes_once(lab, conn):
    out = _race(lambda i: command(_client(), "run-rule", {"rule_id": "r-cust-fresh"}, key="same-key", headers=ANALYST), 3)
    assert {r.status_code for r in out} == {200} and count(conn, "rule_runs", "run_by = 'own-01'") == 1
    assert count(conn, "command_results", "idempotency_key = 'same-key'") == 1 and len({r.json()["command_id"] for r in out}) == 1


def test_a_deadlock_is_retried_three_times_then_409_concurrent_update(lab, conn, monkeypatch):
    from api.errors import ApiError
    from api.schemas import RunRuleRequest
    calls = {"n": 0}

    def deadlock(c, req, actor):
        calls["n"] += 1
        raise psycopg.errors.DeadlockDetected("deadlock detected")

    monkeypatch.setattr(cmds.time, "sleep", lambda s: None)
    req = RunRuleRequest(request_id="r", dataset_version=current_dataset_version(), idempotency_key="k-dl", input={"rule_id": "r-cust-fresh"})
    with pytest.raises(ApiError) as exc:
        cmds.execute("run-rule", req, cmds.Actor("u", "analyst"), deadlock)
    assert exc.value.status == 409 and exc.value.code == "CONCURRENT_UPDATE" and calls["n"] == cmds.MAX_ATTEMPTS == 3
    calls["n"] = 0

    def flaky(c, req, actor):
        calls["n"] += 1
        if calls["n"] < 3:
            raise psycopg.errors.DeadlockDetected("deadlock detected")
        return cmds.Outcome("ok", {"attempt": calls["n"]})

    body, replayed = cmds.execute("run-rule", req, cmds.Actor("u", "analyst"), flaky)
    assert body["result"] == {"attempt": 3} and replayed is False and count(conn, "command_results", "idempotency_key = 'k-dl'") == 1


def test_a_failure_after_the_write_rolls_the_command_and_its_audit_back(lab, conn, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    real = cmds._event

    def boom(*a, **kw):
        real(*a, **kw)
        raise RuntimeError("after the write")

    run = command(lab, "run-rule", {"rule_id": "r-cust-complete-email"}).json()["result"]["rule_run_id"]
    monkeypatch.setattr(cmds, "_event", boom)
    with TestClient(create_app(), raise_server_exceptions=False) as c2:
        before = (count(conn, "issues"), count(conn, "issue_events"), count(conn, "audit_events"), count(conn, "command_results"))
        r = command(c2, "open-issue", {"rule_run_id": run})
        assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR" and "after the write" not in r.text
        assert (count(conn, "issues"), count(conn, "issue_events"), count(conn, "audit_events"), count(conn, "command_results")) == before


# ---------------------------------------------------------------------------------------------------- hostile input
@pytest.mark.parametrize("value", ["'; DROP TABLE rule_runs; --", "r-cust-fresh' OR '1'='1", "\u0000", "é" * 200, "../../etc/passwd", "r-cust-fresh\n"])
def test_hostile_ids_are_data_not_code(lab, conn, value):
    r = command(lab, "run-rule", {"rule_id": value})
    assert r.status_code in (404, 422) and "Traceback" not in r.text and count(conn, "rule_runs") == 13
    assert get(lab, "/data/rule_runs", rule_id=value).status_code in (200, 422)
    assert get(lab, "/metrics", dataset_id=value).status_code in (404, 422)


def test_non_finite_numbers_and_oversize_bodies_are_refused(lab):
    from api.app import PREFIX
    h = {**ADMIN, "content-type": "application/json"}
    body = '{"request_id":"r","dataset_version":"x","idempotency_key":"k1","input":{"rule_id":"r-cust-fresh","weights":{"completeness":NaN}}}'
    assert lab.post(f"{PREFIX}/commands/run-rule", content=body, headers=h).status_code == 422
    assert command(lab, "run-rule", {"rule_id": "r" * 5000}).status_code == 422
    assert command(lab, "suggest-match", {"left_record_id": "rec-003", "right_record_id": "rec-004", "score": 0.5, "features": {"f": "1"}, "explanation": "x"}).status_code == 422


def test_a_float_or_string_score_in_the_wrong_form_is_refused_not_rounded(lab):
    base = {"left_record_id": "rec-003", "right_record_id": "rec-005", "features": {"f": "1"}, "explanation": "x"}
    for score in ("0.1234567", "1e-1", ".5", "1.000001", "0,5", " 0.5"):
        r = command(lab, "suggest-match", {**base, "score": score})
        assert r.status_code == 422 and "SCORE_INVALID" in rule_ids(r), score
    assert command(lab, "suggest-match", {**base, "score": "0.1234567"}).status_code == 422
    assert command(lab, "suggest-match", {**base, "score": "0.123456"}).json()["result"]["score"] == "0.123456"
