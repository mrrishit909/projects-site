"""Commands C01..C10: happy paths, hard validation, roles, server-stamped instants, audit, atomicity and the crash experiments."""
import json
import os
from datetime import datetime, timezone

import psycopg
import pytest

from api import commands as cmds
from pipeline_observatory.hashing import canonical_json, payload_hash
from support_db import (ADMIN, ENGINEER, OPERATOR, at, client, command, conn, count, db_url, fixture_json, get, golden_inputs, ingest, load, load_world,  # noqa: F401
                        metrics, payloads, rule_ids, run_pipeline_for, table_digest, world)


def rec(key, qty=1, amount="10.00", ev="2026-10-04T08:00:00Z", **extra):
    return {"payload": {"record_id": key, "quantity": qty, "unit_price": amount, "amount": amount, "event_ts": ev, **extra}}


def batch_of(n, prefix="K", **kw):
    return [rec(f"{prefix}-{i}", **kw) for i in range(1, n + 1)]


@pytest.fixture
def lab(client, conn):
    load_world(conn, **{"src-orders": {"freshness_target_seconds": None}})
    return client


def audit(conn, action, entity_id=None):
    return conn.execute("SELECT * FROM audit_events WHERE action = %s AND (%s::text IS NULL OR entity_id = %s)", (action, entity_id, entity_id)).fetchall()


def accepted(conn, source="src-orders"):
    return count(conn, "accepted_records", f"source_id = '{source}'")


def version(conn, source="src-orders"):
    return conn.execute("SELECT coalesce(max(version_number), 0) AS v FROM checkpoints WHERE source_id = %s", (source,)).fetchone()["v"]


# ------------------------------------------------------------------------------------------------------------ C01
def test_c01_stages_a_page_with_server_stamped_time_and_server_computed_hashes(lab, conn):
    at("2026-10-04T10:00:00Z")
    r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "cur-000", "batch_id": "b-1", "page": {"records": [rec("A-1"), rec("A-2")], "next_cursor": "cur-002"}},
                headers=ENGINEER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "staged" and body["result"]["received"] == 2 and body["result"]["started_at"] == "2026-10-04T10:00:00Z" and body["result"]["next_cursor"] == "cur-002"
    b = conn.execute("SELECT * FROM ingestion_batches WHERE batch_id = 'b-1'").fetchone()
    assert (b["status"], b["source_cursor"], b["next_cursor"], b["started_at"]) == ("staged", "cur-000", "cur-002", datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc))
    raws = conn.execute("SELECT * FROM raw_records WHERE batch_id = 'b-1' ORDER BY raw_record_id").fetchall()
    assert [x["raw_record_id"] for x in raws] == ["rr-b-1-0001", "rr-b-1-0002"] and raws[0]["payload_hash"] == payload_hash(raws[0]["payload_json"]) and raws[0]["source_key"] == "A-1"
    assert all(x["disposition"] is None for x in raws) and accepted(conn) == 0 and version(conn) == 0       # staged is not counted: nothing is accepted before the commit
    e, = audit(conn, "fetch-source-page", "b-1")
    assert e["actor_id"] == "usr-eng01" and e["actor_role"] == "engineer" and e["request_id"] == "req-test"


@pytest.mark.parametrize("extra", [{"started_at": "2020-01-01T00:00:00Z"}, {"committed_at": "2020-01-01T00:00:00Z"}, {"status": "committed"}])
def test_c01_clients_never_supply_server_instants_or_status(lab, extra):
    r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "page": {"records": []}, **extra})
    assert r.status_code == 422 and rule_ids(r) == ["FIELD_UNEXPECTED"]


def test_c01_hard_validation(lab, conn):
    base = {"source_id": "src-orders", "cursor": "c0", "page": {"records": [rec("A-1")]}}
    r = command(lab, "fetch-source-page", {**base, "source_id": "src-nope"})
    assert r.status_code == 404 and rule_ids(r) == ["UNKNOWN_SOURCE"]
    r = command(lab, "fetch-source-page", {**base, "page": {"records": [rec("A-1", price=1.5)]}})
    assert r.status_code == 422 and "FLOAT_NOT_ALLOWED" in rule_ids(r)                                          # money is a string, never a JSON float
    r = command(lab, "fetch-source-page", {**base, "page": {"records": [{**rec("A-1"), "payload_hash": "0" * 64}]}})
    assert r.status_code == 422 and rule_ids(r) == ["PAYLOAD_HASH_MISMATCH"]
    good = payload_hash(rec("A-1")["payload"])
    assert command(lab, "fetch-source-page", {**base, "page": {"records": [{**rec("A-1"), "payload_hash": good}]}}).status_code == 200
    assert command(lab, "fetch-source-page", {**base, "page": {"records": [], "status": 500}}).status_code == 422
    assert command(lab, "fetch-source-page", {**base, "cursor": ""}).status_code == 422
    assert command(lab, "fetch-source-page", {**base, "batch_id": "b-dup"}).status_code == 200
    r = command(lab, "fetch-source-page", {**base, "batch_id": "b-dup"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_ID"
    assert count(conn, "ingestion_batches") == 2


def test_c01_p08_test_03_a_retry_sooner_than_retry_after_is_refused_and_one_after_it_is_accepted(lab, conn):
    limited = {"source_id": "src-orders", "cursor": "c1", "page": {"status": 429, "retry_after_seconds": 30}}
    at("2026-10-04T08:00:00Z")
    r = command(lab, "fetch-source-page", limited)
    assert r.status_code == 200 and r.json()["status"] == "rate_limited" and r.json()["result"]["retry_not_before"] == "2026-10-04T08:00:30Z" and count(conn, "ingestion_batches") == 0
    ok = {"source_id": "src-orders", "cursor": "c1", "page": {"records": [rec("A-1")], "next_cursor": "c2"}}
    at("2026-10-04T08:00:29Z")
    r = command(lab, "fetch-source-page", ok)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RETRY_TOO_SOON" and r.headers["Retry-After"] == "1"
    assert r.json()["error"]["details"][0]["context"] == {"retry_after_seconds": 30, "remaining_seconds": 1} and count(conn, "ingestion_batches") == 0
    assert audit(conn, "fetch-source-page-refused")[0]["details"]["rule_id"] == "RETRY_TOO_SOON"
    at("2026-10-04T08:00:30Z")
    assert command(lab, "fetch-source-page", ok).status_code == 200 and count(conn, "ingestion_batches") == 1
    at("2026-10-04T08:00:31Z")                                                                                   # the constraint ended with the successful fetch
    assert command(lab, "fetch-source-page", {**ok, "cursor": "c1", "batch_id": "b-again"}).status_code == 200


def test_c01_a_429_page_without_a_retry_after_is_refused(lab):
    r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c1", "page": {"status": 429}})
    assert r.status_code == 422 and rule_ids(r) == ["RETRY_AFTER_REQUIRED"]


def test_c01_p08_test_10_a_repeating_cursor_stops_the_session_with_cursor_loop(lab, conn):
    fx = fixture_json("pagination/cursor_loop.json")
    seq = [(c, p["next_cursor"], p["records"]) for c, (p,) in fx["responses"].items()]
    results = []
    for n, (cursor, nxt, records) in enumerate(seq):
        r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": cursor, "fetch_session": "s1",
                                                "page": {"records": [{"payload": x} for x in records], "next_cursor": nxt}})
        results.append(r)
    assert [r.status_code for r in results] == [200, 200, 409]                                                  # c0 -> c1, c1 -> c2, c2 -> c1: the third repeats
    assert results[2].json()["error"]["code"] == "CURSOR_LOOP" and results[2].json()["error"]["details"][0]["context"] == {"cursor": "c2", "next_cursor": "c1"}
    assert count(conn, "ingestion_batches") == 2 and count(conn, "fetch_log", "status = 'cursor_loop'") == 1       # the loop is recorded though the command rolled back
    again = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c9", "fetch_session": "s1", "page": {"records": [], "next_cursor": "c10"}})
    assert again.status_code == 409 and again.json()["error"]["code"] == "CURSOR_LOOP"                           # the session is stopped
    assert command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c9", "fetch_session": "s2", "page": {"records": [], "next_cursor": "c10"}}).status_code == 200
    assert audit(conn, "fetch-source-page-refused")[0]["details"]["rule_id"] == "CURSOR_LOOP"


def test_c01_a_cursor_equal_to_its_next_cursor_is_a_loop_even_without_a_session(lab):
    r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "page": {"records": [], "next_cursor": "c0"}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CURSOR_LOOP"


def test_c01_replaying_a_window_with_a_new_session_is_not_a_loop(lab):
    """A replay legitimately re-reads cur-000 and gets the same next cursor again (golden b-001, b-002): only a repeat INSIDE one fetch session loops."""
    for n in range(3):
        assert command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "cur-000", "fetch_session": f"replay-{n}", "page": {"records": [rec("A-1")], "next_cursor": "cur-010"}}).status_code == 200


# ------------------------------------------------------------------------------------------------------------ C02
def test_c02_classifies_every_row_and_persists_the_verdict_without_counting_anything(lab, conn):
    inputs = golden_inputs()
    ingest(lab, "src-orders", "b-001", payloads(inputs, "b-001"), commit=False)
    v = command(lab, "validate-contract", {"batch_id": "b-001"}).json()["result"]
    assert (v["received"], v["accepted_unique"], v["duplicate"], v["quarantined"], v["status"]) == (10, 8, 1, 1, "validated") and v["quarantine_by_reason"] == {"NEGATIVE_QUANTITY": 1}
    got = {r["raw_record_id"]: (r["disposition"], r["reason_code"]) for r in conn.execute("SELECT * FROM raw_records").fetchall()}
    assert got["rr-b-001-0006"] == ("duplicate", None) and got["rr-b-001-0008"] == ("quarantined", "NEGATIVE_QUANTITY") and got["rr-b-001-0001"] == ("accepted", None)
    assert accepted(conn) == 0 and version(conn) == 0 and count(conn, "quarantine_records") == 0               # a verdict is not a commit: counted only at C03
    assert conn.execute("SELECT validated_at FROM ingestion_batches").fetchone()["validated_at"] is not None


def test_c02_p08_test_05_a_malformed_row_is_quarantined_with_its_reason_never_dropped(lab, conn):
    rows = [rec("OK-1"), {"payload": {"quantity": 1}}, {"payload": {"record_id": "NO-AMOUNT", "quantity": 1, "unit_price": "1.00", "event_ts": "2026-10-04T08:00:00Z"}}, rec("NEG", qty=-2)]
    out = ingest(lab, "src-orders", "b-1", rows)
    assert (out["commit"]["received"], out["commit"]["accepted_unique"], out["commit"]["quarantined"]) == (4, 1, 3)
    q = {r["quarantine_id"]: (r["source_key"], r["reason_code"]) for r in conn.execute("SELECT * FROM quarantine_records").fetchall()}
    assert q == {"q-b-1-01": (None, "MISSING_FIELD"), "q-b-1-02": ("NO-AMOUNT", "MISSING_FIELD"), "q-b-1-03": ("NEG", "NEGATIVE_QUANTITY")}
    assert count(conn, "raw_records", "batch_id = 'b-1'") == 4                                                    # every raw row is still there
    m = metrics(lab)["data"]["metrics"]["ingestion"]["sources"]["src-orders"]["batches"]["b-1"]
    assert m["received"] == m["accepted_unique"] + m["duplicate"] + m["quarantined"] and m["quarantine_rows_match"] is True


def test_c02_unknown_unstaged_and_committed_batches(lab):
    assert command(lab, "validate-contract", {"batch_id": "b-nope"}).status_code == 404
    ingest(lab, "src-orders", "b-1", batch_of(2))
    r = command(lab, "validate-contract", {"batch_id": "b-1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "BATCH_NOT_STAGED"


def test_c02_p08_test_04_a_schema_change_quarantines_the_whole_batch_until_an_explicit_bump(lab, conn):
    fx = fixture_json("schema/schema_changed.json")
    page = {"records": fx["records"], "next_cursor": fx["next_cursor"], "schema_version": fx["declared_schema_version"]}
    command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": fx["cursor"], "batch_id": "b-v2", "page": page})
    r = command(lab, "validate-contract", {"batch_id": "b-v2"})
    assert r.status_code == 200 and r.json()["status"] == "quarantined" and r.json()["result"]["quarantine_by_reason"] == {"SCHEMA_CHANGED": 3}
    assert r.json()["warnings"][0]["code"] == "SCHEMA_CHANGED"
    assert conn.execute("SELECT status FROM ingestion_batches WHERE batch_id = 'b-v2'").fetchone()["status"] == "quarantined"
    assert count(conn, "quarantine_records", "reason_code = 'SCHEMA_CHANGED'") == 3 and accepted(conn) == 0         # nothing silently accepted, nothing dropped
    refused = command(lab, "commit-batch", {"batch_id": "b-v2"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "BATCH_QUARANTINED" and version(conn) == 0
    # the bump is explicit: an engineer may not, an operator must name the version the batch declares
    command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": fx["cursor"], "batch_id": "b-v2b", "page": page})
    assert command(lab, "validate-contract", {"batch_id": "b-v2b", "bump_schema_version": "2"}, headers=ENGINEER).status_code == 403
    wrong = command(lab, "validate-contract", {"batch_id": "b-v2b", "bump_schema_version": "3"}, headers=OPERATOR)
    assert wrong.status_code == 422 and rule_ids(wrong) == ["SCHEMA_VERSION_MISMATCH"]
    assert conn.execute("SELECT schema_version FROM source_contracts WHERE source_id = 'src-orders'").fetchone()["schema_version"] == "1"
    ok = command(lab, "validate-contract", {"batch_id": "b-v2b", "bump_schema_version": "2"}, headers=OPERATOR)
    assert ok.status_code == 200 and ok.json()["status"] == "validated" and ok.json()["result"]["accepted_unique"] == fx["expected"]["accepted_after_bump"]
    assert conn.execute("SELECT schema_version FROM source_contracts WHERE source_id = 'src-orders'").fetchone()["schema_version"] == "2"
    assert audit(conn, "bump-schema-version")[0]["details"] == {"from": "1", "to": "2"}
    assert command(lab, "commit-batch", {"batch_id": "b-v2b"}).status_code == 200 and accepted(conn) == 3


# ------------------------------------------------------------------------------------------------------------ C03
def test_c03_commits_the_batch_and_its_checkpoint_in_one_transaction(lab, conn):
    at("2026-10-04T10:05:00Z")
    out = ingest(lab, "src-orders", "b-001", payloads(golden_inputs(), "b-001"))
    c = out["commit"]
    assert (c["received"], c["accepted_unique"], c["duplicate"], c["quarantined"], c["source_accepted_total"]) == (10, 8, 1, 1, 8)
    assert c["checkpoint"] == {"checkpoint_id": "cp-b-001", "version_number": 1, "committed_cursor": "cur-010", "committed_at": "2026-10-04T10:05:00Z"}
    assert c["delivery_guarantee"].startswith("at-least-once with idempotent apply")                                # never an exactly-once claim
    assert accepted(conn) == 8 and version(conn) == 1 and count(conn, "quarantine_records") == 1
    assert conn.execute("SELECT status FROM ingestion_batches").fetchone()["status"] == "committed"
    e, = audit(conn, "commit-batch", "b-001")
    assert (e["before_version"], e["after_version"]) == (0, 1)


def test_c03_needs_a_validated_staged_batch(lab):
    command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "batch_id": "b-1", "page": {"records": batch_of(2)}})
    r = command(lab, "commit-batch", {"batch_id": "b-1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "BATCH_NOT_VALIDATED"
    assert command(lab, "commit-batch", {"batch_id": "b-nope"}).status_code == 404
    command(lab, "validate-contract", {"batch_id": "b-1"})
    assert command(lab, "commit-batch", {"batch_id": "b-1"}).status_code == 200
    again = command(lab, "commit-batch", {"batch_id": "b-1"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "BATCH_ALREADY_COMMITTED"


def test_c03_replay_is_idempotent_on_source_key_the_replay_adds_no_accepted_record(lab, conn):
    inputs = golden_inputs()
    ingest(lab, "src-orders", "b-001", payloads(inputs, "b-001"))
    again = ingest(lab, "src-orders", "b-002", payloads(inputs, "b-002"))["commit"]
    assert (again["accepted_unique"], again["duplicate"], again["quarantined"], again["source_accepted_total"], again["checkpoint"]["version_number"]) == (0, 9, 1, 8, 2)
    for n in range(3, 8):
        assert ingest(lab, "src-orders", f"b-00{n}", payloads(inputs, "b-001"))["commit"]["accepted_unique"] == 0
    assert accepted(conn) == 8 and version(conn) == 7 and count(conn, "quarantine_records") == 7                    # the invalid row is quarantined once per occurrence


def test_c03_validation_is_re_done_under_the_lock_two_staged_copies_of_one_key_are_accepted_once(lab, conn):
    command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "batch_id": "b-1", "page": {"records": [rec("SAME")]}})
    command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "batch_id": "b-2", "page": {"records": [rec("SAME")]}})
    for b in ("b-1", "b-2"):
        assert command(lab, "validate-contract", {"batch_id": b}).json()["result"]["accepted_unique"] == 1          # both look new when validated
    assert command(lab, "commit-batch", {"batch_id": "b-1"}).json()["result"]["accepted_unique"] == 1
    second = command(lab, "commit-batch", {"batch_id": "b-2"}).json()["result"]
    assert (second["accepted_unique"], second["duplicate"]) == (0, 1) and accepted(conn) == 1                       # the commit classifies against what is accepted NOW


def test_c03_out_of_order_checkpoints_are_refused_and_nothing_is_written(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(2, "A"))
    ingest(lab, "src-orders", "b-2", batch_of(2, "B"))
    for n, bad in enumerate((1, 2, 4, 9), 3):
        ingest(lab, "src-orders", f"b-{n}", batch_of(2, f"C{n}"), commit=False)
        before = table_digest(conn, ["accepted_records", "checkpoints", "quarantine_records", "ingestion_batches"])
        r = command(lab, "commit-batch", {"batch_id": f"b-{n}", "checkpoint_version": bad})
        code = "CHECKPOINT_REGRESSION" if bad <= 2 else "CHECKPOINT_GAP"
        assert r.status_code == 409 and r.json()["error"]["code"] == code and rule_ids(r) == [code]
        assert table_digest(conn, ["accepted_records", "checkpoints", "quarantine_records", "ingestion_batches"]) == before
        assert audit(conn, "commit-batch-refused", f"b-{n}")[0]["details"]["rule_id"] == code
    assert command(lab, "commit-batch", {"batch_id": "b-3", "checkpoint_version": 3}).status_code == 200          # previous + 1 is accepted


def test_c03_crash_after_the_data_write_before_the_checkpoint_leaves_nothing_behind(lab, conn):
    """P08-TEST-01/02: kill the transaction after the rows are staged and BEFORE the checkpoint is written. The accepted count and the checkpoint
    version are unchanged, the batch is still staged, and the replay is idempotent: the data is applied exactly once, never twice."""
    inputs = golden_inputs()
    ingest(lab, "src-orders", "b-001", payloads(inputs, "b-001"))
    ingest(lab, "src-orders", "b-002", payloads(inputs, "b-002"))
    assert (accepted(conn), version(conn)) == (8, 2)
    ingest(lab, "src-orders", "b-003", payloads(inputs, "b-001") + [rec("ORD-9999")], commit=False)
    seen = {}
    verdicts = conn.execute("SELECT raw_record_id, disposition, reason_code FROM raw_records WHERE batch_id = 'b-003' ORDER BY raw_record_id").fetchall()    # C02's verdicts

    def crash(c, source_id, batch_id):                                                   # runs inside the commit transaction, after the staging writes
        seen["staged_in_tx"] = c.execute("SELECT count(*) AS n FROM accepted_records").fetchone()["n"]
        raise RuntimeError("process died after the data write")
    cmds.hooks["after_staging"] = crash
    try:
        r = command(lab, "commit-batch", {"batch_id": "b-003"})
    finally:
        cmds.hooks["after_staging"] = None
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR" and "Traceback" not in r.text
    assert seen["staged_in_tx"] == 9                                                     # inside the dying transaction the new record WAS written ...
    assert (accepted(conn), version(conn)) == (8, 2)                                     # ... and after the crash it is not: no ninth accepted record
    assert count(conn, "accepted_records", "source_key = 'ORD-9999'") == 0 and count(conn, "quarantine_records", "batch_id = 'b-003'") == 0
    assert conn.execute("SELECT status FROM ingestion_batches WHERE batch_id = 'b-003'").fetchone()["status"] == "staged"
    assert conn.execute("SELECT raw_record_id, disposition, reason_code FROM raw_records WHERE batch_id = 'b-003' ORDER BY raw_record_id").fetchall() == verdicts   # still C02's verdicts
    # the replay from the last committed cursor: ORD-9999 is a legitimate NEW record and enters exactly once; the replay of the replay adds nothing
    first = ingest(lab, "src-orders", "b-004", payloads(inputs, "b-001") + [rec("ORD-9999")])["commit"]
    assert (first["accepted_unique"], first["source_accepted_total"], first["checkpoint"]["version_number"]) == (1, 9, 3)
    second = ingest(lab, "src-orders", "b-005", payloads(inputs, "b-001") + [rec("ORD-9999")])["commit"]
    assert (second["accepted_unique"], second["source_accepted_total"]) == (0, 9)
    # and the exact golden case: the crashed batch re-delivers keys that are all accepted already, so the count never leaves 8
    ingest(lab, "src-orders", "b-006", payloads(inputs, "b-001"), commit=False)
    cmds.hooks["after_staging"] = crash
    try:
        assert command(lab, "commit-batch", {"batch_id": "b-006"}).status_code == 500
    finally:
        cmds.hooks["after_staging"] = None
    assert accepted(conn) == 9 and version(conn) == 4


def test_c03_a_real_backend_kill_mid_commit_is_atomic(lab, conn):
    """The experiment with a real crash: the server process of the transaction is terminated (pg_terminate_backend) after the staging writes."""
    ingest(lab, "src-orders", "b-001", batch_of(8, "ORD"))
    ingest(lab, "src-orders", "b-002", batch_of(8, "ORD") + [rec("ORD-NEW")], commit=False)

    def kill(c, source_id, batch_id):
        c.execute("SELECT pg_terminate_backend(pg_backend_pid())")
    cmds.hooks["after_staging"] = kill
    try:
        r = command(lab, "commit-batch", {"batch_id": "b-002"})
    finally:
        cmds.hooks["after_staging"] = None
    assert r.status_code == 500 and (accepted(conn), version(conn)) == (8, 1)
    assert conn.execute("SELECT status FROM ingestion_batches WHERE batch_id = 'b-002'").fetchone()["status"] == "staged"
    assert count(conn, "accepted_records", "source_key = 'ORD-NEW'") == 0
    retry = command(lab, "commit-batch", {"batch_id": "b-002"})                          # the same batch commits cleanly afterwards
    assert retry.status_code == 200 and retry.json()["result"]["accepted_unique"] == 1 and accepted(conn) == 9


def test_c03_an_injected_crash_fault_fires_once_and_is_recorded(lab, conn):
    ingest(lab, "src-orders", "b-001", batch_of(3), commit=False)
    f = command(lab, "inject-fault", {"fault_type": "crash_before_checkpoint", "target_id": "src-orders", "note": "P08-TEST-01"}, headers=OPERATOR)
    assert f.status_code == 200 and f.json()["result"]["armed"] is True
    r = command(lab, "commit-batch", {"batch_id": "b-001"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "INJECTED_CRASH"
    assert (accepted(conn), version(conn)) == (0, 0)
    fault = conn.execute("SELECT * FROM fault_injections").fetchone()
    assert fault["armed"] is False and fault["consumed_at"] is not None and fault["injected_by"] == "usr-op01"
    assert audit(conn, "commit-batch-refused", "b-001")[0]["details"]["rule_id"] == "INJECTED_CRASH"
    assert command(lab, "commit-batch", {"batch_id": "b-001"}).status_code == 200 and accepted(conn) == 3         # the fault was one-shot


def test_c03_processing_measurement_is_recorded_with_its_conditions(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(4), commit=False)
    bad = command(lab, "commit-batch", {"batch_id": "b-1", "processing": {"measured_seconds": "0", "hardware": "x", "cache_state": "cold"}})
    assert bad.status_code == 422 and rule_ids(bad) == ["MEASURED_SECONDS_INVALID"]
    assert command(lab, "commit-batch", {"batch_id": "b-1", "processing": {"measured_seconds": "2", "hardware": "2 vCPU", "cache_state": "warm"}}).status_code == 200
    rate = metrics(lab)["data"]["metrics"]["processing_rate"]
    assert rate == {"accepted_records": 4, "measured_seconds": "2", "records_per_second": "2.000000", "hardware": "2 vCPU", "cache_state": "warm"}


# ------------------------------------------------------------------------------------------------------------ C04
def test_c04_builds_the_published_table_and_runs_the_key_and_relationship_tests(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(3, "A"))
    ingest(lab, "src-orders", "b-2", batch_of(3, "A") + [rec("B-1")])
    r = command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-2", "b-1"]})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (res["run_created"], res["outputs"], res["attempt"], res["included_batch_ids"]) == (True, 4, 1, ["b-1", "b-2"])
    assert {t["rule_name"]: (t["severity"], t["eligible_count"], t["failure_count"]) for t in res["tests"]} == {"model_keys_unique": ("critical", 4, 0), "model_relationships_intact": ("critical", 4, 0)}
    assert count(conn, "model_outputs", "run_id = 'run-1'") == 4 and count(conn, "task_runs", "run_id = 'run-1'") == 2
    assert {x["task_name"] for x in conn.execute("SELECT task_name FROM task_runs").fetchall()} == {"ingest", "transform"}
    assert conn.execute("SELECT status, included_batch_ids FROM pipeline_runs").fetchone() == {"status": "running", "included_batch_ids": ["b-1", "b-2"]}


def test_c04_names_the_run_itself_when_none_is_given_and_validates_its_batches(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(2))
    command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c9", "batch_id": "b-staged", "page": {"records": batch_of(1, "S")}})
    r = command(lab, "transform-models", {"batch_ids": ["b-1"]})
    assert r.status_code == 200 and r.json()["result"]["run_id"].startswith("run-")
    unknown = command(lab, "transform-models", {"batch_ids": ["b-1", "b-nope"]})
    assert unknown.status_code == 404 and rule_ids(unknown) == ["UNKNOWN_BATCH"] and unknown.json()["error"]["details"][0]["path"] == "input.batch_ids[1]"
    staged = command(lab, "transform-models", {"batch_ids": ["b-1", "b-staged"]})
    assert staged.status_code == 409 and staged.json()["error"]["code"] == "BATCH_NOT_COMMITTED"
    assert command(lab, "transform-models", {"batch_ids": []}).status_code == 422
    assert command(lab, "transform-models", {"batch_ids": ["b-1"], "backfill_id": "bf-nope"}).status_code == 404


def test_c04_attempts_are_distinct_and_a_retry_rebuilds_the_outputs_without_doubling_them(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(3))
    assert command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]}).status_code == 200
    again = command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    assert again.json()["result"]["attempt"] == 2 and count(conn, "model_outputs") == 3                              # a retry replaces, never doubles
    dup = command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"], "attempt": 2})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_ID"
    gap = command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"], "attempt": 7})
    assert gap.status_code == 422 and rule_ids(gap) == ["ATTEMPT_GAP"]
    assert command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"], "attempt": 3}).status_code == 200
    assert [r["attempt"] for r in conn.execute("SELECT attempt FROM task_runs WHERE task_name = 'transform' ORDER BY attempt").fetchall()] == [1, 2, 3]


def test_c04_a_delete_event_removes_the_record_from_the_published_table(lab, conn):
    d = fixture_json("deletes/deletes.json")
    d.pop("expected")
    ingest(lab, "src-orders", "b-1", [{"payload": r["payload_json"]} for r in d["raw_records"] if r["batch_id"] == "b-1"])
    ingest(lab, "src-orders", "b-2", [{"payload": r["payload_json"]} for r in d["raw_records"] if r["batch_id"] == "b-2"], cursor="cur-003", next_cursor="cur-006")
    assert conn.execute("SELECT deleted_in_batch FROM accepted_records WHERE source_key = 'D-2'").fetchone()["deleted_in_batch"] == "b-2"
    assert sorted(r["disposition"] for r in conn.execute("SELECT * FROM raw_records WHERE batch_id = 'b-2'").fetchall()) == ["deleted", "duplicate", "quarantined"]
    out = run_pipeline_for(lab, "run-1", ["b-1", "b-2"], "2026-10-04T09:10:00Z")
    assert out["transform"]["outputs"] == 2 and out["gate"]["decision"] == "allowed" and out["gate"]["reconciliation"]["exclusions"]["deletes"] == "20.00"
    assert out["gate"]["reconciliation"]["residual"] == "0.00" and out["publish"]["published_records"] == 2
    assert {r["record_key"] for r in conn.execute("SELECT record_key FROM model_outputs").fetchall()} == {"D-1", "D-3"}
    body = metrics(lab)["data"]
    assert body["deleted_records"] == [{"source_id": "src-orders", "source_key": "D-2", "accepted_in_batch": "b-1", "deleted_in_batch": "b-2", "excluded_amount": "20.00", "reason": "DELETE_EVENT"}]
    assert body["metrics"]["reconciliation"]["pub-1"]["exclusions"]["deletes"] == "20.00" and body["metrics"]["publications"]["publications"]["pub-1"]["content_hash_ok"] is True


# ------------------------------------------------------------------------------------------------------------ C05
def test_c05_allowed_gate_and_its_checks(lab, conn):
    inputs = golden_inputs()
    ingest(lab, "src-orders", "b-001", payloads(inputs, "b-001"))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-001"]})
    r = command(lab, "run-quality-gate", {"run_id": "run-1"})
    assert r.status_code == 200 and r.json()["status"] == "allowed"
    res = r.json()["result"]
    checks = {x["rule_name"]: (x["severity"], x["eligible_count"], x["failure_count"]) for x in res["results"]}
    assert checks == {"keys_unique": ("critical", 8, 0), "relationships_intact": ("critical", 8, 0), "reconciliation_residual_zero": ("critical", 1, 0),
                      "scope_complete": ("critical", 1, 0), "late_events_included": ("critical", 0, 0), "completeness_vs_expectation": ("warning", 9, 1)}
    assert res["decision"] == "allowed" and res["critical_failures"] == 0 and res["noncritical_failures"] == 1 and res["incident_id"] is None
    assert (res["reconciliation"]["source_total"], res["reconciliation"]["published_total"], res["reconciliation"]["residual"]) == ("289.94", "289.97", "0.00")
    assert conn.execute("SELECT status FROM pipeline_runs").fetchone()["status"] == "success" and count(conn, "incidents") == 0
    assert {t["task_name"] for t in conn.execute("SELECT task_name FROM task_runs").fetchall()} == {"ingest", "transform", "quality_gate"}


def test_c05_fails_closed_a_critical_failure_blocks_fails_the_run_and_opens_an_incident(lab, conn):
    at("2026-10-04T12:00:00Z")
    ingest(lab, "src-orders", "b-1", batch_of(3))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    assert command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-1"}, headers=OPERATOR).status_code == 200
    at("2026-10-04T12:20:00Z")
    r = command(lab, "run-quality-gate", {"run_id": "run-1"})
    body = r.json()
    assert body["status"] == "blocked" and body["result"]["decision"] == "blocked" and body["result"]["incident_id"] == "inc-001"
    failing = {x["rule_name"] for x in body["result"]["results"] if x["severity"] == "critical" and not x["passed"]}
    assert failing == {"keys_unique", "reconciliation_residual_zero"}                          # the duplicate fails the key test AND leaves a residual of -10.00
    assert body["result"]["reconciliation"]["residual"] == "-10.00"
    run = conn.execute("SELECT status, finished_at FROM pipeline_runs").fetchone()
    assert run["status"] == "failed" and run["finished_at"] == datetime(2026, 10, 4, 12, 20, tzinfo=timezone.utc)
    inc = conn.execute("SELECT * FROM incidents").fetchone()
    assert (inc["status"], inc["run_id"], inc["reason"], inc["opened_at"]) == ("open", "run-1", "GATE_BLOCKED", datetime(2026, 10, 4, 12, 20, tzinfo=timezone.utc))
    assert count(conn, "publications") == 0 and count(conn, "publication_pointer") == 0


def test_c05_requires_a_transform_and_an_open_run(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(2))
    assert command(lab, "run-quality-gate", {"run_id": "run-nope"}).status_code == 404
    conn.execute("INSERT INTO pipeline_runs (run_id, started_at, status, code_sha) VALUES ('run-empty', now(), 'running', 'x')")
    r = command(lab, "run-quality-gate", {"run_id": "run-empty"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TRANSFORM_REQUIRED"
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    assert command(lab, "run-quality-gate", {"run_id": "run-1"}).status_code == 200
    again = command(lab, "run-quality-gate", {"run_id": "run-1"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "RUN_NOT_OPEN"


def test_c05_p08_test_06_a_green_run_on_a_stale_source_shows_the_stale_freshness(lab, conn):
    """The job succeeds and the gate passes (no freshness target declared), yet the metric says the source is stale: freshness is not ingestion age."""
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b-1", batch_of(2, ev="2026-10-01T08:00:00Z"))
    out = run_pipeline_for(lab, "run-1", ["b-1"], "2026-10-04T09:00:00Z")
    assert out["gate"]["decision"] == "allowed" and conn.execute("SELECT status FROM pipeline_runs").fetchone()["status"] == "success"
    f = metrics(lab, cutoff="2026-10-04T12:00:00Z")["data"]["metrics"]["freshness"]["src-orders"]
    assert f["freshness_seconds"] == 3 * 86400 + 4 * 3600 and f["ingestion_age_seconds"] == 7200 and f["freshness_seconds"] != f["ingestion_age_seconds"]


def test_c05_a_declared_freshness_target_makes_a_stale_source_a_critical_failure(client, conn):
    load_world(conn, **{"src-orders": {"freshness_target_seconds": 86400}})
    at("2026-10-04T10:00:00Z")
    ingest(client, "src-orders", "b-1", batch_of(2, ev="2026-10-01T08:00:00Z"))
    out = run_pipeline_for(client, "run-1", ["b-1"], "2026-10-04T09:00:00Z")
    assert out["gate"]["decision"] == "blocked"
    assert {x["rule_name"]: x["failure_count"] for x in out["gate"]["results"]}["freshness_within_target"] == 1 and "publish" not in out


# ------------------------------------------------------------------------------------------------------------ C06
def test_c06_publishes_a_passed_candidate_and_moves_the_pointer_atomically(lab, conn):
    inputs = golden_inputs()
    at("2026-10-04T10:05:00Z")
    ingest(lab, "src-orders", "b-001", payloads(inputs, "b-001"))
    at("2026-10-04T10:10:00Z")
    command(lab, "transform-models", {"run_id": "run-001", "batch_ids": ["b-001"]})
    command(lab, "run-quality-gate", {"run_id": "run-001"})
    at("2026-10-04T10:30:00Z")
    r = command(lab, "publish-snapshot", {"run_id": "run-001", "watermark": "2026-10-04T10:00:00Z"})
    assert r.status_code == 200, r.text
    p = r.json()["result"]
    assert (p["publication_id"], p["published_at"], p["watermark"], p["published_records"], p["lag_seconds"], p["previous_publication_id"]) == (
        "pub-001", "2026-10-04T10:30:00Z", "2026-10-04T10:00:00Z", 8, 3600, None)
    assert p["content_hash"] == golden_inputs()["publications"][0]["content_hash"]                               # the fixture's content_hash rule
    assert conn.execute("SELECT publication_id FROM publication_pointer").fetchone()["publication_id"] == "pub-001"
    pub = conn.execute("SELECT * FROM publications").fetchone()
    assert pub["source_ids"] == ["src-orders", "src-refunds"] and pub["included_batch_ids"] == ["b-001"]
    run = conn.execute("SELECT status, finished_at FROM pipeline_runs").fetchone()
    assert run["status"] == "success" and run["finished_at"] == datetime(2026, 10, 4, 10, 30, tzinfo=timezone.utc)
    again = command(lab, "publish-snapshot", {"run_id": "run-001", "watermark": "2026-10-04T10:00:00Z"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_PUBLISHED"


def test_c06_refuses_a_failed_a_blocked_and_an_ungated_run_and_never_moves_the_pointer(lab, conn):
    """P08-TEST-07: a failed run never replaces the valid publication."""
    ingest(lab, "src-orders", "b-1", batch_of(3))
    run_pipeline_for(lab, "run-ok", ["b-1"], "2026-10-04T07:00:00Z")
    pointer = conn.execute("SELECT * FROM publication_pointer").fetchone()
    assert pointer["publication_id"] == "pub-ok"
    ingest(lab, "src-orders", "b-2", batch_of(3, "B"))
    command(lab, "transform-models", {"run_id": "run-bad", "batch_ids": ["b-1", "b-2"]})
    command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-bad"}, headers=OPERATOR)
    assert command(lab, "run-quality-gate", {"run_id": "run-bad"}).json()["status"] == "blocked"
    before = table_digest(conn, ["publications", "publication_pointer", "pipeline_runs", "task_runs"])
    r = command(lab, "publish-snapshot", {"run_id": "run-bad", "watermark": "2026-10-04T07:00:00Z"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_NOT_SUCCESSFUL" and r.json()["error"]["details"][0]["context"] == {"status": "failed"}
    # even if the status is forced to success by hand, the gate still blocks it, in the application and then in the database
    conn.execute("UPDATE pipeline_runs SET status = 'success' WHERE run_id = 'run-bad'")
    r = command(lab, "publish-snapshot", {"run_id": "run-bad", "watermark": "2026-10-04T07:00:00Z"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "GATE_BLOCKED"
    with pytest.raises(psycopg.errors.IntegrityError, match="PUBLICATION_REQUIRES_GATE"):
        conn.execute("INSERT INTO publications VALUES ('pub-x', 'run-bad', 'sales_daily', now(), now(), '{src-orders}', '{b-1}', repeat('a', 64))")
    conn.execute("UPDATE pipeline_runs SET status = 'failed' WHERE run_id = 'run-bad'")
    assert table_digest(conn, ["publications", "publication_pointer", "task_runs"]) == {k: v for k, v in before.items() if k != "pipeline_runs"}
    assert conn.execute("SELECT * FROM publication_pointer").fetchone() == pointer
    # a run that never reached the gate, and one that does not exist
    command(lab, "transform-models", {"run_id": "run-new", "batch_ids": ["b-1"]})
    assert command(lab, "publish-snapshot", {"run_id": "run-new", "watermark": "2026-10-04T07:00:00Z"}).json()["error"]["code"] == "RUN_NOT_SUCCESSFUL"
    assert command(lab, "publish-snapshot", {"run_id": "run-nope", "watermark": "2026-10-04T07:00:00Z"}).status_code == 404
    assert [a["details"]["rule_id"] for a in audit(conn, "publish-snapshot-refused")][:2] == ["RUN_NOT_SUCCESSFUL", "GATE_BLOCKED"]


def test_c06_the_watermark_is_disclosed_never_in_the_future_and_published_at_is_the_servers(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(2))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    command(lab, "run-quality-gate", {"run_id": "run-1"})
    at("2026-10-04T10:00:00Z")
    assert rule_ids(command(lab, "publish-snapshot", {"run_id": "run-1", "watermark": "2026-10-04T10:00:01Z"})) == ["WATERMARK_IN_FUTURE"]
    assert rule_ids(command(lab, "publish-snapshot", {"run_id": "run-1", "watermark": "2026-10-04T10:00:00Z", "published_at": "2020-01-01T00:00:00Z"})) == ["FIELD_UNEXPECTED"]
    assert rule_ids(command(lab, "publish-snapshot", {"run_id": "run-1", "watermark": "yesterday"})) == ["TIMESTAMP_INVALID"]
    assert command(lab, "publish-snapshot", {"run_id": "run-1"}).status_code == 422                       # the watermark is required
    assert count(conn, "publications") == 0


def test_c06_publication_and_pointer_are_one_transaction(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(2))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    command(lab, "run-quality-gate", {"run_id": "run-1"})
    seen = {}

    def die(c, publication_id):
        seen["row_in_tx"] = c.execute("SELECT count(*) AS n FROM publications").fetchone()["n"]
        raise RuntimeError("died between the publication row and the pointer")
    cmds.hooks["after_publication"] = die
    try:
        r = command(lab, "publish-snapshot", {"run_id": "run-1", "watermark": "2026-10-04T07:00:00Z"})
    finally:
        cmds.hooks["after_publication"] = None
    assert r.status_code == 500 and seen["row_in_tx"] == 1
    assert count(conn, "publications") == 0 and count(conn, "publication_pointer") == 0                  # neither the row nor the pointer survived
    assert command(lab, "publish-snapshot", {"run_id": "run-1", "watermark": "2026-10-04T07:00:00Z"}).status_code == 200


def test_c06_a_later_publication_replaces_the_pointer_and_reports_the_previous_one(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(2))
    run_pipeline_for(lab, "run-1", ["b-1"], "2026-10-04T07:00:00Z")
    ingest(lab, "src-orders", "b-2", batch_of(2, "B"))
    out = run_pipeline_for(lab, "run-2", ["b-1", "b-2"], "2026-10-04T08:00:00Z")
    assert out["publish"]["previous_publication_id"] == "pub-1" and out["publish"]["current_publication_id"] == "pub-2"
    assert conn.execute("SELECT publication_id FROM publication_pointer").fetchone()["publication_id"] == "pub-2" and count(conn, "publications") == 2       # pub-1 stays, immutable


def test_c06_publishing_a_backfill_run_verifies_the_partitions_it_covers(client, conn):
    w = world()
    w["source_expectations"] = [{"source_id": "src-orders", "partition": "2026-09-01", "expected_records": 2}, {"source_id": "src-orders", "partition": "2026-09-02", "expected_records": 2},
                                {"source_id": "src-refunds", "partition": "2026-10-04", "expected_records": 1}]
    load(conn, w, dataset_version="ds-api-1")
    bf = command(client, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-03T00:00:00Z"}, headers=ENGINEER).json()["result"]["backfill_id"]
    ingest(client, "src-orders", "b-1", [rec("S-1", ev="2026-09-01T08:00:00Z"), rec("S-2", ev="2026-09-01T09:00:00Z"), rec("S-3", ev="2026-09-02T08:00:00Z")])
    r = command(client, "transform-models", {"run_id": "run-bf", "batch_ids": ["b-1"], "backfill_id": bf})
    assert r.status_code == 200
    command(client, "run-quality-gate", {"run_id": "run-bf"})
    p = command(client, "publish-snapshot", {"run_id": "run-bf", "watermark": "2026-09-02T09:00:00Z"})
    assert p.json()["result"]["backfill"] == {"backfill_id": bf, "status": "partial", "verified_partitions": 1, "requested_partitions": 2}      # 2 of 2 on 09-01, 1 of 2 on 09-02
    m = metrics(client)["data"]["metrics"]["backfills"]
    assert m["requests"][bf]["coverage"] == "0.500000" and m["requests"][bf]["verified_partitions"] == 1


# ------------------------------------------------------------------------------------------------------------ C07
def test_c07_inject_fault_is_sandbox_only_and_always_recorded(lab, conn, monkeypatch):
    ingest(lab, "src-orders", "b-1", batch_of(2))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    monkeypatch.setenv("PIPELINE_ENVIRONMENT", "production")
    r = command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-1"}, headers=ADMIN)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN" and rule_ids(r) == ["NOT_SANDBOX"]
    assert count(conn, "fault_injections") == 0 and count(conn, "model_outputs", "run_id = 'run-1'") == 2
    assert audit(conn, "inject-fault-refused")[0]["details"]["rule_id"] == "NOT_SANDBOX"
    monkeypatch.setenv("PIPELINE_ENVIRONMENT", "sandbox")
    ok = command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-1", "note": "TEST-07"}, headers=ADMIN)
    assert ok.status_code == 200 and ok.json()["warnings"][0]["code"] == "SANDBOX_FAULT"
    assert count(conn, "model_outputs", "run_id = 'run-1'") == 3
    f = conn.execute("SELECT * FROM fault_injections").fetchone()
    assert (f["fault_type"], f["target_id"], f["injected_by"], f["note"]) == ("duplicate_key", "run-1", "usr-adm01", "TEST-07")
    a, = audit(conn, "inject-fault", f["fault_id"])
    assert a["actor_id"] == "usr-adm01" and a["actor_role"] == "admin" and a["details"]["sandbox"] is True and a["details"]["fault_type"] == "duplicate_key"


def test_c07_task_failure_fails_the_run_and_opens_an_incident(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(2))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    r = command(lab, "inject-fault", {"fault_type": "task_failure", "target_id": "run-1"}, headers=OPERATOR)
    assert r.status_code == 200 and r.json()["result"]["incident_id"] == "inc-001" and r.json()["result"]["failed_task"] == "transform"
    assert conn.execute("SELECT status FROM pipeline_runs").fetchone()["status"] == "failed"
    assert conn.execute("SELECT status, attempt FROM task_runs WHERE task_name = 'transform' ORDER BY attempt").fetchall() == [{"status": "success", "attempt": 1}, {"status": "failed", "attempt": 2}]
    again = command(lab, "inject-fault", {"fault_type": "task_failure", "target_id": "run-1"}, headers=OPERATOR)
    assert again.status_code == 409 and again.json()["error"]["code"] == "RUN_NOT_OPEN"                      # only a healthy, running run can be faulted


@pytest.mark.parametrize("body,status,rule", [({"fault_type": "meltdown", "target_id": "run-1"}, 422, "FAULT_TYPE_INVALID"), ({"fault_type": "duplicate_key", "target_id": "run-nope"}, 404, "UNKNOWN_RUN"),
                                              ({"fault_type": "crash_before_checkpoint", "target_id": "src-nope"}, 404, "UNKNOWN_SOURCE"),
                                              ({"fault_type": "duplicate_key", "target_id": "run-1"}, 409, "NO_OUTPUTS")])
def test_c07_hard_validation(lab, conn, body, status, rule):
    conn.execute("INSERT INTO pipeline_runs (run_id, started_at, status, code_sha) VALUES ('run-1', now(), 'running', 'x')")
    r = command(lab, "inject-fault", body, headers=OPERATOR)
    assert r.status_code == status and rule in rule_ids(r) + [r.json()["error"]["code"]]
    assert count(conn, "fault_injections") == 0


# ------------------------------------------------------------------------------------------------------------ C08
def test_c08_half_open_range_overlap_refused_touching_accepted(lab, conn):
    r = command(lab, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-04T00:00:00Z"}, headers=ENGINEER)
    assert r.status_code == 200 and r.json()["result"]["backfill_id"] == "bf-001" and r.json()["result"]["partitions"] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    over = command(lab, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-03T00:00:00Z", "end_at": "2026-09-06T00:00:00Z"}, headers=ENGINEER)
    assert over.status_code == 409 and over.json()["error"]["code"] == "BACKFILL_OVERLAP" and rule_ids(over) == ["BACKFILL_OVERLAP"]
    assert over.json()["error"]["details"][0]["context"] == {"conflicts_with": "bf-001", "refused_id": "bf-002"}
    touch = command(lab, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-04T00:00:00Z", "end_at": "2026-09-05T00:00:00Z"}, headers=ENGINEER)
    assert touch.status_code == 200 and touch.json()["result"]["backfill_id"] == "bf-003"                          # 09-04 is excluded from bf-001: half-open
    other = command(lab, "request-backfill", {"source_id": "src-refunds", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-04T00:00:00Z"})
    assert other.status_code == 200                                                                                # another source never conflicts
    assert [r["backfill_id"] for r in conn.execute("SELECT backfill_id FROM backfill_requests ORDER BY backfill_id").fetchall()] == ["bf-001", "bf-003", "bf-004"]
    rj = conn.execute("SELECT * FROM rejected_records").fetchone()
    assert (rj["entity"], rj["id"], rj["reason_code"]) == ("backfill_requests", "bf-002", "BACKFILL_OVERLAP") and rj["raw_row"]["start_at"] == "2026-09-03T00:00:00Z"
    assert audit(conn, "request-backfill-refused", "bf-002")[0]["details"]["conflicts_with"] == "bf-001"
    assert metrics(lab)["data"]["metrics"]["backfills"]["refused"] == ["bf-002"]


@pytest.mark.parametrize("s,e,rule", [("2026-09-04T00:00:00Z", "2026-09-01T00:00:00Z", "INVALID_RANGE"), ("2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", "INVALID_RANGE"),
                                      ("2026-09-01T06:00:00Z", "2026-09-04T00:00:00Z", "PARTITION_ALIGNMENT"), ("2026-09-01T00:00:00Z", "2026-09-04T12:00:00Z", "PARTITION_ALIGNMENT")])
def test_c08_hard_validation(lab, conn, s, e, rule):
    r = command(lab, "request-backfill", {"source_id": "src-orders", "start_at": s, "end_at": e})
    assert r.status_code == 422 and rule_ids(r) == [rule] and count(conn, "backfill_requests") == 0
    assert command(lab, "request-backfill", {"source_id": "src-nope", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-02T00:00:00Z"}).status_code == 404
    assert command(lab, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-01", "end_at": "2026-09-02T00:00:00Z"}).status_code == 422


# ------------------------------------------------------------------------------------------------------------ C09
def _incident_scenario(lab, conn):
    """run-bad fails its gate (incident inc-001); run-good succeeds, publishes."""
    at("2026-10-04T09:00:00Z")
    ingest(lab, "src-orders", "b-1", batch_of(3))
    at("2026-10-04T12:10:00Z")
    command(lab, "transform-models", {"run_id": "run-bad", "batch_ids": ["b-1"]})
    command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-bad"}, headers=OPERATOR)
    at("2026-10-04T12:20:00Z")
    assert command(lab, "run-quality-gate", {"run_id": "run-bad"}).json()["result"]["incident_id"] == "inc-001"


def test_c09_recovery_is_verified_before_the_incident_closes(lab, conn):
    _incident_scenario(lab, conn)
    at("2026-10-04T12:30:00Z")
    early = command(lab, "recover-incident", {"incident_id": "inc-001"}, headers=OPERATOR)
    assert early.status_code == 422 and rule_ids(early) == ["RECOVERY_NOT_VERIFIED"]
    assert conn.execute("SELECT status FROM incidents").fetchone()["status"] == "open"
    at("2026-10-04T20:00:00Z")
    command(lab, "transform-models", {"run_id": "run-good", "batch_ids": ["b-1"]})
    command(lab, "run-quality-gate", {"run_id": "run-good"})
    at("2026-10-04T20:15:00Z")
    assert command(lab, "publish-snapshot", {"run_id": "run-good", "watermark": "2026-10-04T09:00:00Z"}).status_code == 200
    at("2026-10-04T20:20:00Z")
    wrong = command(lab, "recover-incident", {"incident_id": "inc-001", "recovery_run_id": "run-bad"}, headers=OPERATOR)
    assert wrong.status_code == 422 and rule_ids(wrong) == ["RECOVERY_RUN_MISMATCH"]
    ok = command(lab, "recover-incident", {"incident_id": "inc-001", "recovery_run_id": "run-good"}, headers=OPERATOR)
    assert ok.status_code == 200 and ok.json()["status"] == "recovered"
    res = ok.json()["result"]
    assert (res["recovery_run_id"], res["verified_at"], res["closed_at"], res["recovery_seconds"], res["recovery_minutes"]) == ("run-good", "2026-10-04T20:15:00Z", "2026-10-04T20:15:00Z", 28500, "475.0000")
    inc = conn.execute("SELECT * FROM incidents").fetchone()
    assert inc["status"] == "closed" and inc["closed_at"] == datetime(2026, 10, 4, 20, 15, tzinfo=timezone.utc) and inc["recovery_run_id"] == "run-good"       # the verified instant, not the 20:20 restart
    m = metrics(lab, cutoff="2026-10-05T00:00:00Z")["data"]["metrics"]["incidents"]
    assert m["closed"] == 1 and m["incidents"]["inc-001"]["closure_consistent"] is True and m["mean_recovery_minutes"] == "475.0000"
    again = command(lab, "recover-incident", {"incident_id": "inc-001"}, headers=OPERATOR)
    assert again.status_code == 409 and again.json()["error"]["code"] == "INCIDENT_NOT_OPEN"


def test_c09_requires_the_reconciliation_residual_to_be_zero_before_closing(lab, conn):
    _incident_scenario(lab, conn)
    at("2026-10-04T20:00:00Z")
    command(lab, "transform-models", {"run_id": "run-good", "batch_ids": ["b-1"]})
    command(lab, "run-quality-gate", {"run_id": "run-good"})
    at("2026-10-04T20:15:00Z")
    command(lab, "publish-snapshot", {"run_id": "run-good", "watermark": "2026-10-04T09:00:00Z"})
    conn.execute("UPDATE model_outputs SET amount = amount + 1.00 WHERE run_id = 'run-good' AND record_key = 'K-1'")       # the stored published table drifts by 1.00
    at("2026-10-04T20:20:00Z")
    r = command(lab, "recover-incident", {"incident_id": "inc-001"}, headers=OPERATOR)
    assert r.status_code == 422 and rule_ids(r) == ["RESIDUAL_NOT_ZERO"] and "pub-good" in r.json()["error"]["message"]
    assert conn.execute("SELECT status FROM incidents").fetchone()["status"] == "open"
    assert metrics(lab)["data"]["metrics"]["reconciliation"]["pub-good"]["residual"] == "-1.00"                              # the reader sees the same residual
    conn.execute("UPDATE model_outputs SET amount = amount - 1.00 WHERE run_id = 'run-good' AND record_key = 'K-1'")
    assert command(lab, "recover-incident", {"incident_id": "inc-001"}, headers=OPERATOR).status_code == 200


def test_c09_unknown_incident_and_roles(lab):
    assert command(lab, "recover-incident", {"incident_id": "inc-nope"}, headers=OPERATOR).status_code == 404
    assert command(lab, "recover-incident", {"incident_id": "inc-001"}, headers=ENGINEER).status_code == 403


# ------------------------------------------------------------------------------------------------------------ C10
def test_c10_archives_a_completed_run_with_hashes_and_the_retention_mapping(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(3))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    early = command(lab, "archive-evidence", {"run_id": "run-1"}, headers=OPERATOR)
    assert early.status_code == 409 and early.json()["error"]["code"] == "RUN_NOT_COMPLETED"
    command(lab, "run-quality-gate", {"run_id": "run-1"})
    command(lab, "publish-snapshot", {"run_id": "run-1", "watermark": "2026-10-04T07:00:00Z"})
    r = command(lab, "archive-evidence", {"run_id": "run-1"}, headers=OPERATOR)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    row = conn.execute("SELECT * FROM evidence_archives").fetchone()
    assert row["manifest_hash"] == res["manifest_hash"] and canonical_json_hash(row["manifest"]) == res["manifest_hash"]
    for name, h in res["item_hashes"].items():
        assert canonical_json_hash(row["manifest"]["items"][name]["content"]) == h
    assert set(res["item_hashes"]) == {"run", "task_runs", "quality_results", "gate", "publication", "incidents"}
    assert {"publication_snapshot", "quality_results", "raw_records", "audit_events", "structured_logs", "evidence_manifest"} <= set(res["retention"])
    assert row["manifest"]["items"]["publication"]["content"]["content_hash"] == conn.execute("SELECT content_hash FROM publications").fetchone()["content_hash"]
    dup = command(lab, "archive-evidence", {"run_id": "run-1"}, headers=OPERATOR)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "ALREADY_ARCHIVED"
    assert command(lab, "archive-evidence", {"run_id": "run-nope"}, headers=OPERATOR).status_code == 404


def test_c10_a_failed_run_is_archivable_with_its_incident(lab, conn):
    ingest(lab, "src-orders", "b-1", batch_of(2))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-1"}, headers=OPERATOR)
    command(lab, "run-quality-gate", {"run_id": "run-1"})
    row = command(lab, "archive-evidence", {"run_id": "run-1"}, headers=ADMIN).json()["result"]
    m = conn.execute("SELECT manifest FROM evidence_archives").fetchone()["manifest"]
    assert m["items"]["gate"]["content"]["decision"] == "blocked" and m["items"]["publication"]["content"] is None and m["items"]["incidents"]["content"][0]["incident_id"] == "inc-001"
    assert row["archive_id"] == "ev-1"


def canonical_json_hash(obj):
    import hashlib
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()
