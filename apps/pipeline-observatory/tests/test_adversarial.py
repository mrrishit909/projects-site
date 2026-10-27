"""Adversarial cases end to end (API over PostgreSQL): replay storms, out-of-order checkpoints, duplicate task attempts, overlapping backfills,
publishing a blocked run, actor and role mismatches, idempotency reuse with a different body, concurrency, and hostile input.
Domain-level versions of the same rules are in test_domain_rules.py; here the refusal, its status and its envelope are the point."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api.app import PREFIX, create_app

SHARED_APP = create_app()                                  # built once: the threads share the app, each has its own client and connection
from support_db import (ADMIN, ENGINEER, OPERATOR, OPERATOR2, at, client, command, conn, count, db_url, golden_inputs, ingest, load_world, metrics, payloads,
                        rule_ids, run_pipeline_for, table_digest)


def rec(key, qty=1, amount="10.00", ev="2026-10-04T08:00:00Z", **extra):
    return {"payload": {"record_id": key, "quantity": qty, "unit_price": amount, "amount": amount, "event_ts": ev, **extra}}


def many(n, prefix="K"):
    return [rec(f"{prefix}-{i}") for i in range(1, n + 1)]


@pytest.fixture
def lab(client, conn):
    load_world(conn)
    return client


def accepted(conn):
    return count(conn, "accepted_records", "source_id = 'src-orders'")


def test_01_replay_storm_the_accepted_count_never_moves(lab, conn):
    """P08-TEST-01: forty replays of one batch (new batch ids, new idempotency keys) leave eight accepted records and forty-one checkpoints."""
    inputs = golden_inputs()
    ingest(lab, "src-orders", "b-000", payloads(inputs, "b-001"))
    for n in range(1, 41):
        out = ingest(lab, "src-orders", f"b-{n:03d}", payloads(inputs, "b-001"))["commit"]
        assert out["accepted_unique"] == 0 and out["source_accepted_total"] == 8
    assert accepted(conn) == 8 and count(conn, "checkpoints", "source_id = 'src-orders'") == 41
    assert metrics(lab)["data"]["metrics"]["ingestion"]["sources"]["src-orders"]["accepted_unique"] == 8


def test_02_the_same_commit_repeated_with_the_same_key_is_one_commit_with_a_different_key_a_conflict(lab, conn):
    ingest(lab, "src-orders", "b-1", many(3), commit=False)
    first = command(lab, "commit-batch", {"batch_id": "b-1"}, key="commit-1")
    again = command(lab, "commit-batch", {"batch_id": "b-1"}, key="commit-1")
    assert again.json() == first.json() and again.headers["Idempotent-Replay"] == "true"
    other_key = command(lab, "commit-batch", {"batch_id": "b-1"}, key="commit-2")
    assert other_key.status_code == 409 and other_key.json()["error"]["code"] == "BATCH_ALREADY_COMMITTED"
    assert accepted(conn) == 3 and count(conn, "checkpoints") == 1


def test_03_concurrent_replays_of_the_same_rows_accept_each_key_exactly_once(lab, conn):
    """Six batches with the same eight keys commit at the same time: the source lock serialises them, exactly one batch accepts the keys."""
    for n in range(6):
        ingest(lab, "src-orders", f"b-{n}", many(8), commit=False)
    results, errors = [], []

    def commit(n):
        with TestClient(SHARED_APP, raise_server_exceptions=False) as c:
            r = command(c, "commit-batch", {"batch_id": f"b-{n}"}, headers=ENGINEER)
            (results if r.status_code == 200 else errors).append(r)
    threads = [threading.Thread(target=commit, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and len(results) == 6
    accepted_per_batch = sorted(r.json()["result"]["accepted_unique"] for r in results)
    assert accepted_per_batch == [0, 0, 0, 0, 0, 8]                                                                  # not 16, not 48: idempotent under concurrency
    assert accepted(conn) == 8 and sorted(r.json()["result"]["checkpoint"]["version_number"] for r in results) == [1, 2, 3, 4, 5, 6]


def test_04_out_of_order_checkpoint_versions_never_reach_the_database(lab, conn):
    ingest(lab, "src-orders", "b-1", many(2, "A"))
    ingest(lab, "src-orders", "b-2", many(2, "B"))
    for n, v in enumerate((0, 1, 2, 5, 99), 3):
        ingest(lab, "src-orders", f"b-{n}", many(2, f"C{n}"), commit=False)
        r = command(lab, "commit-batch", {"batch_id": f"b-{n}", "checkpoint_version": v})
        assert r.status_code == 409 and rule_ids(r)[0] in ("CHECKPOINT_REGRESSION", "CHECKPOINT_GAP")
    assert accepted(conn) == 4 and count(conn, "checkpoints") == 2
    with pytest.raises(Exception, match="CHECKPOINT_REGRESSION"):                                                    # and the database refuses it too, bypassing the application
        conn.execute("INSERT INTO ingestion_batches (batch_id, source_id, source_cursor, started_at, status) VALUES ('b-x', 'src-orders', 'c', now(), 'staged')")
        conn.execute("INSERT INTO checkpoints VALUES ('cp-x', 'src-orders', 'b-x', 'c', now(), 1)")


def test_05_duplicate_task_attempts_are_refused_and_never_counted_twice(lab, conn):
    ingest(lab, "src-orders", "b-1", many(2))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})                                       # attempt 1
    body = {"run_id": "run-1", "batch_ids": ["b-1"]}
    for attempt, status in ((1, 409), (1, 409), (3, 422), (2, 200), (2, 409)):
        r = command(lab, "transform-models", {**body, "attempt": attempt})
        assert r.status_code == status, (attempt, r.text)
        if status == 409:
            assert r.json()["error"]["code"] == "DUPLICATE_ID"
    attempts = [r["attempt"] for r in conn.execute("SELECT attempt FROM task_runs WHERE run_id = 'run-1' AND task_name = 'transform'").fetchall()]
    assert sorted(attempts) == [1, 2] and len(attempts) == len(set(attempts))
    run = metrics(lab)["data"]["metrics"]["runs"]["runs"]["run-1"]
    assert run["tasks"]["transform"]["attempts"] == 2 and run["attempts"] == 3                                        # ingest + two transform attempts, none counted twice
    with pytest.raises(Exception, match="task_runs_attempt_uq"):                                                      # the database refuses a repeated attempt as well
        conn.execute("INSERT INTO task_runs VALUES ('tr-x', 'run-1', 'transform', 'success', 2)")


def test_06_overlapping_backfills_cannot_run_together_even_at_the_same_instant(lab, conn):
    """P08-TEST-02: four threads request overlapping ranges of one source at once; exactly one is accepted."""
    outcomes = []

    def ask(i):
        with TestClient(SHARED_APP, raise_server_exceptions=False) as c:
            start = f"2026-09-0{1 + i}T00:00:00Z"
            r = command(c, "request-backfill", {"source_id": "src-orders", "start_at": start, "end_at": "2026-09-10T00:00:00Z"}, headers=ENGINEER)
            outcomes.append((r.status_code, r.json().get("error", {}).get("code")))
    threads = [threading.Thread(target=ask, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outcomes) == [(200, None), (409, "BACKFILL_OVERLAP"), (409, "BACKFILL_OVERLAP"), (409, "BACKFILL_OVERLAP")]
    assert count(conn, "backfill_requests") == 1 and count(conn, "rejected_records", "reason_code = 'BACKFILL_OVERLAP'") == 3
    ids = sorted(r["backfill_id"] for r in conn.execute("SELECT backfill_id FROM backfill_requests UNION SELECT id FROM rejected_records").fetchall())
    assert ids == ["bf-001", "bf-002", "bf-003", "bf-004"]                                                            # no id is reused, none is lost
    # a contained range, a containing range and an exact repeat are all refused; an adjacent one is accepted
    kept = conn.execute("SELECT start_at, end_at FROM backfill_requests").fetchone()
    s, e = kept["start_at"].strftime("%Y-%m-%dT%H:%M:%SZ"), kept["end_at"].strftime("%Y-%m-%dT%H:%M:%SZ")
    for lo, hi in ((s, e), ("2026-08-01T00:00:00Z", "2026-12-01T00:00:00Z"), ("2026-09-09T00:00:00Z", "2026-09-09T00:00:00Z")):
        assert command(lab, "request-backfill", {"source_id": "src-orders", "start_at": lo, "end_at": hi}).status_code in (409, 422)
    assert command(lab, "request-backfill", {"source_id": "src-orders", "start_at": e, "end_at": "2026-09-11T00:00:00Z"}).status_code == 200


def test_07_publishing_a_blocked_run_never_moves_the_pointer_in_any_way(lab, conn):
    """P08-TEST-07: every route to publish a blocked or failed run is closed, and the current publication stays exactly as it was."""
    ingest(lab, "src-orders", "b-1", many(3))
    run_pipeline_for(lab, "run-ok", ["b-1"], "2026-10-04T07:00:00Z")
    snapshot = table_digest(conn, ["publications", "publication_pointer"])
    command(lab, "transform-models", {"run_id": "run-x", "batch_ids": ["b-1"]})
    command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-x"}, headers=OPERATOR)
    assert command(lab, "run-quality-gate", {"run_id": "run-x"}).json()["status"] == "blocked"
    for headers in (OPERATOR, ADMIN):
        r = command(lab, "publish-snapshot", {"run_id": "run-x", "watermark": "2026-10-04T07:00:00Z"}, headers=headers)
        assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_NOT_SUCCESSFUL"
    assert command(lab, "publish-snapshot", {"run_id": "run-x", "watermark": "2026-10-04T07:00:00Z"}, headers=ENGINEER).status_code == 403
    with pytest.raises(Exception, match="PUBLICATION_REQUIRES_SUCCESS"):                                              # even straight SQL cannot publish it
        conn.execute("INSERT INTO publications VALUES ('pub-x', 'run-x', 'sales_daily', now(), now(), '{src-orders}', '{b-1}', repeat('a', 64))")
    with pytest.raises(Exception, match="POINTER_REQUIRES_SUCCESS|PUBLICATION_REQUIRES_SUCCESS"):
        conn.execute("UPDATE publication_pointer SET publication_id = 'pub-x'")
    assert table_digest(conn, ["publications", "publication_pointer"]) == snapshot
    assert metrics(lab)["data"]["metrics"]["publications"]["current_publication_id"] == "pub-ok"


def test_08_a_publication_is_immutable_and_a_second_one_never_overwrites_the_first(lab, conn):
    ingest(lab, "src-orders", "b-1", many(3))
    run_pipeline_for(lab, "run-1", ["b-1"], "2026-10-04T07:00:00Z")
    before = conn.execute("SELECT * FROM publications").fetchone()
    for sql in ("UPDATE publications SET content_hash = repeat('b', 64)", "DELETE FROM publications"):
        with pytest.raises(Exception, match="APPEND_ONLY"):
            conn.execute(sql)
    assert conn.execute("SELECT * FROM publications").fetchone() == before


def test_09_actor_and_role_mismatches(lab, conn):
    assert command(lab, "publish-snapshot", {"run_id": "r", "watermark": "2026-10-04T07:00:00Z"}, headers={"X-Actor-Id": "u", "X-Actor-Role": "engineer"}).status_code == 403
    assert command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "r"}, headers={"X-Actor-Id": "u", "X-Actor-Role": "ENGINEER"}).status_code == 403    # roles are case-sensitive
    assert command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "r"}, headers={"X-Actor-Id": "u", "X-Actor-Role": "admin "}).status_code == 403
    assert command(lab, "commit-batch", {"batch_id": "b"}, headers={"X-Actor-Role": "admin"}).status_code == 401
    assert command(lab, "commit-batch", {"batch_id": "b"}, headers={"X-Actor-Id": "x" * 129, "X-Actor-Role": "admin"}).status_code == 401
    assert count(conn, "audit_events") == 0 and count(conn, "command_results") == 0                                      # nothing a forbidden actor sent left a trace in the data
    # the same key and the same body under another actor or role is a conflict, never a replay of someone else's result
    ingest(lab, "src-orders", "b-1", many(1), commit=False)
    mine = command(lab, "commit-batch", {"batch_id": "b-1"}, key="shared-key", headers=OPERATOR)
    assert mine.status_code == 200
    for headers in (OPERATOR2, ADMIN, {"X-Actor-Id": "usr-op01", "X-Actor-Role": "admin"}):
        r = command(lab, "commit-batch", {"batch_id": "b-1"}, key="shared-key", headers=headers)
        assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED" and "result" not in r.text


def test_10_idempotency_reuse_with_a_different_body_is_refused_for_every_command(lab, conn):
    page = {"source_id": "src-orders", "cursor": "c0", "batch_id": "b-1", "page": {"records": many(2)}}
    assert command(lab, "fetch-source-page", page, key="k-body").status_code == 200
    for changed in ({**page, "page": {"records": many(3)}}, {**page, "cursor": "c1"}, {**page, "fetch_session": "s"}, {**page, "source_id": "src-refunds"},
                    {**page, "page": {"records": many(2), "next_cursor": "c1"}}):
        r = command(lab, "fetch-source-page", changed, key="k-body")
        assert r.status_code == 409 and rule_ids(r) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"], changed
    assert count(conn, "ingestion_batches") == 1 and count(conn, "raw_records") == 2
    # an instant under a *_at key is compared as an instant: the same moment written another way is the same request
    bf = {"source_id": "src-orders", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-02T00:00:00Z"}
    a = command(lab, "request-backfill", bf, key="k-time")
    b = command(lab, "request-backfill", {**bf, "start_at": "2026-09-01T02:00:00+02:00"}, key="k-time")
    assert a.status_code == 200 and b.status_code == 200 and b.headers["Idempotent-Replay"] == "true" and count(conn, "backfill_requests") == 1


def test_11_concurrent_calls_with_one_idempotency_key_run_the_command_once(lab, conn):
    ingest(lab, "src-orders", "b-1", many(2), commit=False)
    outs = []

    def go():
        with TestClient(SHARED_APP, raise_server_exceptions=False) as c:
            r = command(c, "commit-batch", {"batch_id": "b-1"}, key="one-key", headers=OPERATOR)
            outs.append((r.status_code, r.headers.get("Idempotent-Replay"), r.json()["command_id"]))
    threads = [threading.Thread(target=go) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [s for s, _, _ in outs] == [200] * 5 and sorted(str(h) for _, h, _ in outs) == ["None", "true", "true", "true", "true"] and len({c for _, _, c in outs}) == 1
    assert count(conn, "checkpoints") == 1 and accepted(conn) == 2


def test_12_concurrent_publications_of_one_run_publish_once(lab, conn):
    ingest(lab, "src-orders", "b-1", many(3))
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    command(lab, "run-quality-gate", {"run_id": "run-1"})
    outs = []

    def go(n):
        with TestClient(SHARED_APP, raise_server_exceptions=False) as c:
            r = command(c, "publish-snapshot", {"run_id": "run-1", "watermark": "2026-10-04T07:00:00Z"}, headers=OPERATOR)
            outs.append((r.status_code, r.json().get("error", {}).get("code")))
    threads = [threading.Thread(target=go, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outs) == [(200, None), (409, "ALREADY_PUBLISHED"), (409, "ALREADY_PUBLISHED"), (409, "ALREADY_PUBLISHED")]
    assert count(conn, "publications") == 1 and count(conn, "task_runs", "task_name = 'publish'") == 1


def test_13_concurrent_distinct_commits_on_different_sources_do_not_block_each_other(lab, conn):
    ingest(lab, "src-orders", "b-o", many(3), commit=False)
    ingest(lab, "src-refunds", "b-r", many(3, "R"), commit=False)
    codes = []

    def go(b):
        with TestClient(SHARED_APP, raise_server_exceptions=False) as c:
            codes.append(command(c, "commit-batch", {"batch_id": b}).status_code)
    threads = [threading.Thread(target=go, args=(b,)) for b in ("b-o", "b-r")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes == [200, 200] and count(conn, "checkpoints") == 2


@pytest.mark.parametrize("value", ["'; DROP TABLE raw_records; --", "<script>alert(1)</script>", "../../etc/passwd", "a" * 128, "é中\U0001f600", "x\x00y"])
def test_14_hostile_strings_are_data_never_code(lab, conn, value):
    r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "batch_id": "b-h", "page": {"records": [rec(value[:60] if "\x00" not in value else "k")]}})
    if "\x00" in value:
        assert r.status_code in (200, 422)
    assert r.status_code in (200, 422) and count(conn, "raw_records") in (0, 1)
    assert conn.execute("SELECT to_regclass('raw_records') AS t").fetchone()["t"] is not None


def test_15_a_nul_character_in_a_payload_is_refused_not_a_500(lab, conn):
    r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "page": {"records": [rec("A", note="x\u0000y")]}})
    assert r.status_code == 422 and rule_ids(r) == ["NUL_CHARACTER"] and count(conn, "ingestion_batches") == 0


def test_16_oversized_and_malformed_pages_are_refused(lab, conn):
    assert command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "page": {"records": [rec(f"R{i}") for i in range(2001)]}}).status_code == 422
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": 1}}}}}}}}}}
    r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "page": {"records": [{"payload": {"record_id": "D", **deep}}]}})
    assert r.status_code == 422 and "PAYLOAD_TOO_DEEP" in rule_ids(r)
    assert command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "page": {"records": [{"payload": "not an object"}]}}).status_code == 422
    raw = b'{"request_id":"r","dataset_version":"ds-api-1","idempotency_key":"k-inf","input":{"source_id":"src-orders","cursor":"c0","page":{"records":[{"payload":{"record_id":"A","quantity":1e400}}]}}}'
    r = lab.post(f"{PREFIX}/commands/fetch-source-page", content=raw, headers={**ADMIN, "content-type": "application/json"})
    assert r.status_code == 422 and "FLOAT_NOT_ALLOWED" in rule_ids(r)                                                  # an infinite float is a float: refused, not stored
    assert count(conn, "ingestion_batches") == 0


def test_17_a_dataset_that_changed_underneath_makes_every_command_stale(lab, conn):
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version, created_at) VALUES ('ds-api-2', 'h', '1', now() + interval '1 hour')")
    for name, body in (("fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "page": {}}), ("commit-batch", {"batch_id": "b"}), ("request-backfill",
                       {"source_id": "src-orders", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-02T00:00:00Z"})):
        r = command(lab, name, body, dataset_version="ds-api-1")
        assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_DATASET_VERSION", name
    assert count(conn, "audit_events") == 0 and count(conn, "backfill_requests") == 0


def test_18_the_error_envelope_never_leaks_internals(lab, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://lab:wrong-pw-123@127.0.0.1:5432/pipeline_observatory")
    r = command(lab, "fetch-source-page", {"source_id": "src-orders", "cursor": "c0", "page": {}}, headers=ADMIN, dataset_version="ds-api-1")
    assert r.status_code == 500 and r.json()["error"] == {"code": "INTERNAL_ERROR", "message": "internal error", "details": []}
    for secret in ("wrong-pw-123", "postgresql://", "Traceback", "psycopg", "password"):
        assert secret not in r.text
