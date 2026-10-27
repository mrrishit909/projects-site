"""Review round R8 (docs/contracts.md D-09), through PostgreSQL and the API: the reviewer's attacks, each shown blocked, and the rules that replaced them.

R8-01 a future-dated event cannot mask a stale source; R8-02 a publication cannot omit a committed batch or a late event, and a watermark never goes back;
R8-06 a fetch names its session, a loop is a repeated cursor inside one session, a new session fetches a cursor again as a refetch; R8-12 overlap is judged
against requests still requested or running; R8-13 the sandbox is explicit; R8-04 Unicode digits and a trailing newline are not money."""
import os

import pytest
from pipeline_observatory.fetch import Fetched, judge_fetch
from pipeline_observatory.errors import DomainError

from support_db import ENGINEER, OPERATOR, at, client, command, conn, count, db_url, ingest, load_world, metrics, rule_ids, run_pipeline_for, PREFIX  # noqa: F401


def rec(key, ev="2026-10-04T08:00:00Z", amount="10.00", **kw):
    return {"payload": {"record_id": key, "quantity": 1, "unit_price": amount, "amount": amount, "event_ts": ev, **kw}}


@pytest.fixture
def lab(client, conn):
    load_world(conn, **{"src-orders": {"freshness_target_seconds": 19800}})
    return client


def gate_failures(out):
    return {x["rule_name"]: (x["eligible_count"], x["failure_count"]) for x in out["gate"]["results"] if x["failure_count"]}


# ------------------------------------------------------------------------------------------------------------ R8-01 a future-dated event
def test_a_future_dated_row_is_quarantined_and_cannot_mask_a_stale_source(lab, conn):
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b1", [rec("K1", ev="2026-10-04T08:00:00Z"), rec("K2", ev="2030-01-01T00:00:00Z")], cursor="c0", next_cursor="c1")
    assert {r["source_key"]: (r["disposition"], r["reason_code"]) for r in conn.execute("SELECT * FROM raw_records").fetchall()} == {"K1": ("accepted", None), "K2": ("quarantined", "EVENT_IN_FUTURE")}
    assert conn.execute("SELECT reason_code FROM quarantine_records").fetchone()["reason_code"] == "EVENT_IN_FUTURE"                # nothing dropped
    at("2026-10-10T00:00:00Z")
    out = run_pipeline_for(lab, "run-1", ["b1"], "2026-10-04T09:00:00Z")
    assert out["gate"]["decision"] == "blocked" and gate_failures(out)["freshness_within_target"] == (1, 1) and "publish" not in out        # the staleness is visible
    f = metrics(lab, cutoff="2026-10-10T00:00:00Z")["data"]["metrics"]["freshness"]["src-orders"]
    assert f["latest_accepted_event_at"] == "2026-10-04T08:00:00Z" and f["freshness_seconds"] == 5 * 86400 + 16 * 3600 and f["freshness_reason"] is None


def test_a_row_dated_after_its_batch_started_is_in_the_future_even_by_one_second(lab, conn):
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b1", [rec("ON-TIME", ev="2026-10-04T10:00:00Z"), rec("LATE-BY-1S", ev="2026-10-04T10:00:01Z"), rec("OFFSET", ev="2026-10-04T12:00:01+02:00")], cursor="c0", next_cursor="c1")
    got = {r["source_key"]: r["reason_code"] for r in conn.execute("SELECT * FROM raw_records").fetchall()}
    assert got == {"ON-TIME": None, "LATE-BY-1S": "EVENT_IN_FUTURE", "OFFSET": "EVENT_IN_FUTURE"}


def test_freshness_is_null_with_a_reason_when_no_accepted_event_exists_never_negative(lab):
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b1", [rec("F1", ev="2031-01-01T00:00:00Z")], cursor="c0", next_cursor="c1")
    f = metrics(lab, cutoff="2026-10-05T00:00:00Z")["data"]["metrics"]["freshness"]["src-orders"]
    assert f["latest_accepted_event_at"] is None and f["freshness_seconds"] is None and f["freshness_reason"] == "NO_ACCEPTED_EVENT" and f["ingestion_age_seconds"] == 50400


# ------------------------------------------------------------------------------------------------------------ R8-02 omit
def test_a_publication_that_omits_a_committed_batch_is_blocked_by_scope_complete(lab, conn):
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b1", [rec("K1")], cursor="c0", next_cursor="c1")
    ingest(lab, "src-orders", "b2", [rec("K2", amount="99.00")], cursor="c1", next_cursor="c2")
    at("2026-10-04T11:00:00Z")
    out = run_pipeline_for(lab, "run-1", ["b1"], "2026-10-04T09:00:00Z")                          # the reviewer's attack: b2 is committed, the candidate leaves it out
    assert out["gate"]["decision"] == "blocked" and gate_failures(out)["scope_complete"] == (2, 1) and "publish" not in out
    assert count(conn, "publications") == 0 and conn.execute("SELECT status FROM pipeline_runs").fetchone()["status"] == "failed" and count(conn, "incidents") == 1
    assert command(lab, "publish-snapshot", {"run_id": "run-1", "watermark": "2026-10-04T09:00:00Z"}).status_code == 409           # the run failed: nothing to publish
    at("2026-10-04T12:00:00Z")
    ok = run_pipeline_for(lab, "run-2", ["b1", "b2"], "2026-10-04T09:00:00Z")                      # the honest candidate includes both
    assert ok["gate"]["decision"] == "allowed" and {x["rule_name"]: (x["eligible_count"], x["failure_count"]) for x in ok["gate"]["results"]}["scope_complete"] == (2, 0)
    assert ok["publish"]["included_batch_ids"] == ["b1", "b2"]


def test_the_scope_a_run_declares_is_judged_not_the_whole_history(lab):
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b1", [rec("K1")], cursor="c0", next_cursor="c1")
    at("2026-10-04T12:00:00Z")
    ingest(lab, "src-orders", "b2", [rec("K2")], cursor="c1", next_cursor="c2")
    at("2026-10-04T13:00:00Z")
    r = command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b2"], "scope_from": "2026-10-04T11:00:00Z"})                  # today's snapshot: only b2 is in [11:00, now)
    assert r.status_code == 200
    g = command(lab, "run-quality-gate", {"run_id": "run-1"}).json()["result"]
    assert g["decision"] == "allowed" and {x["rule_name"]: (x["eligible_count"], x["failure_count"]) for x in g["results"]}["scope_complete"] == (1, 0)
    assert command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b2"], "scope_from": "2026-10-04T09:00:00Z", "attempt": 2}).status_code == 409      # fixed at the start
    assert command(lab, "transform-models", {"run_id": "run-9", "batch_ids": ["b2"], "scope_from": "2026-12-01T00:00:00Z"}).json()["error"]["details"][0]["rule_id"] == "SCOPE_IN_FUTURE"


def test_a_late_event_that_no_publication_includes_is_blocked_by_late_events_included(lab, conn):
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b1", [rec("K1")], cursor="c0", next_cursor="c1")
    at("2026-10-04T11:00:00Z")
    first = run_pipeline_for(lab, "run-1", ["b1"], "2026-10-04T09:00:00Z")
    assert first["gate"]["decision"] == "allowed"
    at("2026-10-04T12:00:00Z")
    ingest(lab, "src-orders", "b3", [rec("K3", ev="2026-10-04T08:30:00Z")], cursor="c1", next_cursor="c2")          # dated before pub-1's watermark (09:00): a late event
    m = metrics(lab, cutoff="2026-10-05T00:00:00Z")["data"]["metrics"]["late_events"]
    assert (m["count"], m["lost"]) == (1, 1)                                                                          # known, and not (yet) in any publication
    at("2026-10-04T13:00:00Z")
    # the reviewer's attack: a run whose declared scope starts AFTER the late batch (scope_from 12:30) leaves it out and passes scope_complete
    assert command(lab, "transform-models", {"run_id": "run-2", "batch_ids": ["b1"], "scope_from": "2026-10-04T12:30:00Z"}).status_code == 200
    g = command(lab, "run-quality-gate", {"run_id": "run-2"}).json()["result"]
    got = {x["rule_name"]: (x["eligible_count"], x["failure_count"]) for x in g["results"]}
    assert got["scope_complete"] == (0, 0) and got["late_events_included"] == (1, 1) and g["decision"] == "blocked"
    at("2026-10-04T14:00:00Z")
    ok = run_pipeline_for(lab, "run-3", ["b1", "b3"], "2026-10-04T09:30:00Z")
    assert ok["gate"]["decision"] == "allowed" and {x["rule_name"]: (x["eligible_count"], x["failure_count"]) for x in ok["gate"]["results"]}["late_events_included"] == (1, 0)
    m = metrics(lab, cutoff="2026-10-05T00:00:00Z")["data"]["metrics"]["late_events"]
    assert (m["count"], m["included_in_next_publication"], m["lost"]) == (1, 1, 0)


def test_a_watermark_never_goes_back(lab, conn):
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b1", [rec("K1")], cursor="c0", next_cursor="c1")
    at("2026-10-04T11:00:00Z")
    run_pipeline_for(lab, "run-1", ["b1"], "2026-10-04T09:00:00Z")
    at("2026-10-04T12:00:00Z")
    ingest(lab, "src-orders", "b2", [rec("K2")], cursor="c1", next_cursor="c2")
    at("2026-10-04T13:00:00Z")
    out = run_pipeline_for(lab, "run-2", ["b1", "b2"], "2026-10-04T05:00:00Z", publish=False)                      # the reviewer's run-3: a watermark BEFORE the previous publication's
    assert out["gate"]["decision"] == "allowed"
    r = command(lab, "publish-snapshot", {"run_id": "run-2", "watermark": "2026-10-04T05:00:00Z"})
    assert r.status_code == 422 and rule_ids(r) == ["WATERMARK_REGRESSION"] and r.json()["error"]["details"][0]["context"]["previous_watermark"] == "2026-10-04T09:00:00Z"
    assert count(conn, "publications") == 1 and conn.execute("SELECT publication_id FROM publication_pointer").fetchone()["publication_id"] == "pub-1"
    assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'publish-snapshot-refused'").fetchone()["n"] == 1
    assert command(lab, "publish-snapshot", {"run_id": "run-2", "watermark": "2026-10-04T09:00:00Z"}).status_code == 200        # equal is fine: it does not go back


# ------------------------------------------------------------------------------------------------------------ R8-06 fetch sessions
def test_a_fetch_must_name_its_session(lab):
    body = {"request_id": "r", "dataset_version": "ds-api-1", "idempotency_key": "k-nosess", "input": {"source_id": "src-orders", "cursor": "c0", "page": {"records": []}}}
    r = lab.post(f"{PREFIX}/commands/fetch-source-page", json=body, headers=OPERATOR)
    assert r.status_code == 422 and rule_ids(r) == ["FETCH_SESSION_REQUIRED"]
    body["idempotency_key"] = "k-emptysess"
    body["input"]["fetch_session"] = ""
    assert lab.post(f"{PREFIX}/commands/fetch-source-page", json=body, headers=OPERATOR).status_code == 422


def fetch(lab, src, bid, cursor, nxt, session, **page):
    return command(lab, "fetch-source-page", {"source_id": src, "cursor": cursor, "batch_id": bid, "fetch_session": session, "page": {"records": [], "next_cursor": nxt, **page}})


def statuses(conn):
    return [(r["cursor_value"], r["session_id"], r["status"]) for r in conn.execute("SELECT * FROM fetch_log ORDER BY fetch_id").fetchall()]


def test_a_to_b_to_a_is_a_loop_inside_one_session_and_a_refetch_across_sessions(lab, conn):
    assert [fetch(lab, "src-refunds", "r1", "A", "B", "s1").status_code, fetch(lab, "src-refunds", "r2", "B", "A", "s2").status_code,
            fetch(lab, "src-refunds", "r3", "A", "B", "s3").status_code] == [200, 200, 200]                       # three sessions: allowed, and the second A is a refetch
    assert statuses(conn) == [("A", "s1", "ok"), ("B", "s2", "ok"), ("A", "s3", "refetch")]
    assert fetch(lab, "src-refunds", "r4", "A", "B", "s4").status_code == 200
    stop = fetch(lab, "src-refunds", "r5", "B", "A", "s4")                                                         # the same loop inside one session
    assert stop.status_code == 409 and stop.json()["error"]["code"] == "CURSOR_LOOP" and stop.json()["error"]["details"][0]["context"] == {"cursor": "B", "next_cursor": "A"}
    assert fetch(lab, "src-refunds", "r6", "Z", "Y", "s4").status_code == 409                                      # the session is stopped
    assert count(conn, "ingestion_batches") == 4 and count(conn, "fetch_log", "status = 'cursor_loop'") == 1       # the looping page staged nothing; the loop is evidence


def test_a_new_session_may_re_poll_the_last_committed_cursor_of_a_stale_source(lab, conn):
    ingest(lab, "src-orders", "b1", [rec("K1")], cursor="off-1", next_cursor="off-2")
    assert fetch(lab, "src-orders", "s1", "off-2", "off-2", "poll-1").status_code == 200                           # nothing new: next == cursor, the last committed cursor
    assert fetch(lab, "src-orders", "s2", "off-2", "off-2", "poll-2").status_code == 200
    assert [s for _, _, s in statuses(conn)] == ["ok", "refetch", "refetch"]
    assert fetch(lab, "src-orders", "s3", "off-2", "off-2", "poll-2").status_code == 409                           # but not twice inside a session
    assert fetch(lab, "src-orders", "s4", "off-9", "off-9", "poll-3").status_code == 409                           # and a page that points at itself at any other cursor is a loop


def test_the_replay_of_a_window_in_a_new_session_is_a_refetch(lab, conn):
    for n in range(3):
        assert fetch(lab, "src-orders", f"w{n}", "cur-000", "cur-010", f"replay-{n}").status_code == 200
    assert [s for _, _, s in statuses(conn)] == ["ok", "refetch", "refetch"]


def test_judge_fetch_is_the_one_pure_rule():
    h = [Fetched("s", "A", "B"), Fetched("s", "B", "C")]
    assert judge_fetch([], None, "s", "A", "B") == "ok"
    assert judge_fetch(h, "C", "t", "A", "B") == "refetch" and judge_fetch(h, "C", "t", "C", "C") == "refetch" and judge_fetch(h, "C", "t", "C", "D") == "ok"
    for cursor, nxt in (("C", "A"), ("C", "B"), ("C", "C"), ("A", "D")):
        with pytest.raises(DomainError) as e:
            judge_fetch(h, "C", "s", cursor, nxt)
        assert e.value.code == "CURSOR_LOOP", (cursor, nxt)
    assert judge_fetch([Fetched("s", "A", "B", "rate_limited")], None, "s", "A", "B") == "ok"                    # a 429 is not a page


# ------------------------------------------------------------------------------------------------------------ R8-12 overlap against active requests
def day(n):
    return f"2026-09-{n:02d}T00:00:00Z"


def bf(lab, a, b, src="src-orders"):
    return command(lab, "request-backfill", {"source_id": src, "start_at": day(a), "end_at": day(b)})


def test_a_requested_or_running_backfill_blocks_an_overlap_and_a_settled_one_does_not(lab, conn):
    assert bf(lab, 1, 3).json()["result"]["backfill_id"] == "bf-001" and conn.execute("SELECT status FROM backfill_requests").fetchone()["status"] == "requested"
    r = bf(lab, 2, 4)
    assert r.status_code == 409 and r.json()["error"]["code"] == "BACKFILL_OVERLAP" and r.json()["error"]["details"][0]["context"]["conflicts_with"] == "bf-001"
    conn.execute("UPDATE backfill_requests SET status = 'running'")
    assert bf(lab, 2, 4).status_code == 409
    for settled in ("partial", "complete"):
        conn.execute("UPDATE backfill_requests SET status = %s", (settled,))
        assert bf(lab, 2, 3).status_code == 200, settled                                                           # the reviewer's probe: a completed request no longer blocks
        conn.execute("UPDATE backfill_requests SET status = 'complete' WHERE backfill_id <> 'bf-001'")
    assert bf(lab, 3, 4).status_code == 200 and bf(lab, 1, 2, src="src-refunds").status_code == 200


def test_the_partition_a_backfill_left_unverified_can_be_backfilled_again(lab, conn):
    """The recovery path: bf-001 asks for 2026-09-01 and 09-02; the source delivers only half of 09-02, so the request settles `partial` with 09-02 unverified;
    a new request for 09-02 is accepted, runs, and verifies it. While a request is requested or running nothing may overlap it."""
    conn.execute("INSERT INTO source_expectations (source_id, partition, expected_records) VALUES ('src-refunds', '2026-09-01', 2), ('src-refunds', '2026-09-02', 2)")
    at("2026-10-04T09:00:00Z")
    assert bf(lab, 1, 3, src="src-refunds").status_code == 200
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-refunds", "b1", [rec("A1", ev="2026-09-01T08:00:00Z"), rec("A2", ev="2026-09-01T09:00:00Z"), rec("B1", ev="2026-09-02T08:00:00Z")], cursor="bf-1", next_cursor="bf-1x")
    at("2026-10-04T11:00:00Z")
    assert command(lab, "transform-models", {"run_id": "run-bf1", "batch_ids": ["b1"], "backfill_id": "bf-001"}).status_code == 200
    assert conn.execute("SELECT status FROM backfill_requests").fetchone()["status"] == "running" and bf(lab, 2, 3, src="src-refunds").status_code == 409
    g = command(lab, "run-quality-gate", {"run_id": "run-bf1"}).json()["result"]
    assert g["decision"] == "allowed"
    at("2026-10-04T11:30:00Z")
    p = command(lab, "publish-snapshot", {"run_id": "run-bf1", "watermark": "2026-10-04T10:00:00Z"}).json()["result"]
    assert p["backfill"] == {"backfill_id": "bf-001", "status": "partial", "verified_partitions": 1, "requested_partitions": 2}
    row = conn.execute("SELECT * FROM backfill_requests WHERE backfill_id = 'bf-001'").fetchone()
    assert row["status"] == "partial" and row["settled_at"].isoformat().startswith("2026-10-04T11:30:00") and [x["verified"] for x in row["partitions"]] == [True, False]
    # recovery: the unverified partition is requested again, runs and verifies
    at("2026-10-04T12:00:00Z")
    again = bf(lab, 2, 3, src="src-refunds")
    assert again.status_code == 200 and again.json()["result"]["backfill_id"] == "bf-003"          # bf-002 was the refused attempt: a refusal consumes its id and again.json()["status"] == "requested"
    ingest(lab, "src-refunds", "b2", [rec("B2", ev="2026-09-02T08:30:00Z")], cursor="bf-2", next_cursor="bf-2x")      # the missing record arrives
    at("2026-10-04T13:00:00Z")
    assert command(lab, "transform-models", {"run_id": "run-bf2", "batch_ids": ["b1", "b2"], "backfill_id": "bf-003", "scope_from": "2026-10-04T10:00:00Z"}).status_code == 200
    assert command(lab, "run-quality-gate", {"run_id": "run-bf2"}).json()["result"]["decision"] == "allowed"
    at("2026-10-04T13:30:00Z")
    done = command(lab, "publish-snapshot", {"run_id": "run-bf2", "watermark": "2026-10-04T10:30:00Z"}).json()["result"]
    assert done["backfill"] == {"backfill_id": "bf-003", "status": "complete", "verified_partitions": 1, "requested_partitions": 1}
    m = metrics(lab, cutoff="2026-10-05T00:00:00Z")["data"]["metrics"]["backfills"]
    assert m["overall"] == {"requested_partitions": 3, "verified_partitions": 2, "coverage": "0.666667"}


# ------------------------------------------------------------------------------------------------------------ R8-13 the sandbox is explicit
@pytest.mark.parametrize("value", [None, "", "production", "Sandbox", "sandbox ", "sandbox,production"])
def test_the_sandbox_is_only_the_exact_word(lab, conn, monkeypatch, value):
    run = {"fault_type": "task_failure", "target_id": "run-1"}
    if value is None:
        monkeypatch.delenv("PIPELINE_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("PIPELINE_ENVIRONMENT", value)
    r = command(lab, "inject-fault", run)
    assert r.status_code == 403 and rule_ids(r) == ["NOT_SANDBOX"] and count(conn, "fault_injections") == 0
    assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'inject-fault-refused'").fetchone()["n"] == 1


def test_the_sandbox_allows_a_fault_only_when_it_says_sandbox(lab, conn, monkeypatch):
    monkeypatch.setenv("PIPELINE_ENVIRONMENT", "sandbox")
    ingest(lab, "src-orders", "b1", [rec("K1")], cursor="c0", next_cursor="c1")
    assert command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b1"]}).status_code == 200
    assert command(lab, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-1"}).status_code == 200


# ------------------------------------------------------------------------------------------------------------ R8-04 the reviewer's money
def test_unicode_digits_and_a_trailing_newline_are_not_money_through_the_api(lab, conn):
    at("2026-10-04T10:00:00Z")
    ingest(lab, "src-orders", "b1", [rec("K1", amount="١٠.٠٠"), rec("K2", amount="5.00\n"), rec("K3"), rec("K4", **{"quantity": 3}) | {"payload": {"record_id": "K4", "quantity": 2**53 + 1,
           "unit_price": "1.00", "amount": "1.00", "event_ts": "2026-10-04T08:00:00Z"}}], cursor="c0", next_cursor="c1")
    got = {r["source_key"]: (r["disposition"], r["reason_code"]) for r in conn.execute("SELECT * FROM raw_records").fetchall()}
    assert got == {"K1": ("quarantined", "INVALID_FIELD"), "K2": ("quarantined", "INVALID_FIELD"), "K3": ("accepted", None), "K4": ("quarantined", "INVALID_FIELD")}
    at("2026-10-04T11:00:00Z")
    out = run_pipeline_for(lab, "run-1", ["b1"], "2026-10-04T09:00:00Z")
    assert out["gate"]["reconciliation"]["source_total"] == "11.00" and out["gate"]["reconciliation"]["residual"] == "0.00"              # K3 10.00 + K4 1.00; the Unicode "10.00" never became money
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
    ref = conn.execute(sql, {"cutoff": "2026-10-05T00:00:00Z"}).fetchone()
    assert ref["ingestion"]["overall"]["quarantined"] == 3 and ref["reconciliation"]["pub-1"]["source_total"] == "11.00"
    assert metrics(lab, cutoff="2026-10-05T00:00:00Z")["data"]["metrics"]["ingestion"]["overall"] == ref["ingestion"]["overall"]


# ------------------------------------------------------------------------------------------------------------ R8-15 units and money columns
def test_migration_0003_money_columns_and_the_refetch_status(conn):
    t = {r["column_name"]: (r["numeric_precision"], r["numeric_scale"]) for r in conn.execute(
        "SELECT column_name, numeric_precision, numeric_scale FROM information_schema.columns WHERE table_name = 'model_outputs' AND column_name = 'amount'").fetchall()}
    assert t["amount"] == (20, 6)
    cols = {r["column_name"] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name IN ('pipeline_runs', 'backfill_requests')").fetchall()}
    assert {"scope_from", "requested_at", "settled_at"} <= cols
    conn.execute("INSERT INTO source_contracts (source_id, source_name, schema_version, expected_frequency, owner_id) VALUES ('s', 's', '1', 'h', 'o')")
    conn.execute("INSERT INTO fetch_log (source_id, cursor_value, session_id, status, fetched_at) VALUES ('s', 'c', 'x', 'refetch', now())")
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO fetch_log (source_id, cursor_value, session_id, status, fetched_at) VALUES ('s', 'c', 'x', 'again', now())")
