"""The golden scenario played through the real API over PostgreSQL, with the clock set to the fixture's instants: the backend result is compared
with the reference (expected.json), not with itself (P08-GOLD-06). Also: the seeded fixtures read back through GET /metrics equal expected.json
leaf for leaf, for all three fixtures."""
import pytest

from api import commands as cmds
from support_db import (ADMIN, CUTOFF, ENGINEER, OPERATOR, VARIANTS, at, client, command, conn, count, db_url, diff, flat, get, golden_expected,  # noqa: F401
                        golden_inputs, ingest, load, load_world, metrics, payloads, run_pipeline_for, world)


@pytest.mark.parametrize("variant", VARIANTS)
def test_seeded_fixture_read_back_through_the_api_equals_expected_json_leaf_for_leaf(client, conn, variant):
    inputs = golden_inputs(variant)
    load(conn, inputs)
    body = metrics(client, cutoff=inputs["cutoff"])
    want = golden_expected(variant)
    assert diff(body["data"]["metrics"], want["metrics"]) == []
    assert diff(body["data"]["ingest"], want["ingest"]) == []
    assert body["data"]["empty_population"] is want["empty_population"]
    assert body["data"]["cutoff"] == want["cutoff"]


def test_the_whole_golden_story_through_the_commands(client, conn):
    inputs = golden_inputs()
    load_world(conn)
    want = golden_expected()["metrics"]
    orders = payloads(inputs, "b-001")

    # ---- 10:00 b-001 arrives and commits at 10:05 with the measured processing (12 s, cold)
    at("2026-10-04T10:00:00Z")
    r = command(client, "fetch-source-page", {"source_id": "src-orders", "cursor": "cur-000", "batch_id": "b-001", "page": {"records": orders, "next_cursor": "cur-010"}})
    assert r.status_code == 200 and r.json()["result"]["received"] == 10
    at("2026-10-04T10:01:00Z")
    v = command(client, "validate-contract", {"batch_id": "b-001"}).json()["result"]
    assert (v["received"], v["accepted_unique"], v["duplicate"], v["quarantined"]) == (10, 8, 1, 1) and v["quarantine_by_reason"] == {"NEGATIVE_QUANTITY": 1}
    at("2026-10-04T10:05:00Z")
    c = command(client, "commit-batch", {"batch_id": "b-001", "processing": {"measured_seconds": "12", "hardware": want["processing_rate"]["hardware"], "cache_state": "cold"}})
    assert c.status_code == 200, c.text
    cp = c.json()["result"]["checkpoint"]
    assert (cp["version_number"], cp["committed_cursor"], cp["committed_at"]) == (1, "cur-010", "2026-10-04T10:05:00Z") and c.json()["result"]["source_accepted_total"] == 8

    # ---- run-001: transform, gate (allowed), publish at 10:30 with watermark 10:00
    at("2026-10-04T10:10:00Z")
    assert command(client, "transform-models", {"run_id": "run-001", "batch_ids": ["b-001"]}).status_code == 200
    at("2026-10-04T10:20:00Z")
    g = command(client, "run-quality-gate", {"run_id": "run-001"}).json()["result"]
    assert g["decision"] == "allowed" and g["reconciliation"]["residual"] == "0.00" and g["incident_id"] is None
    assert {x["rule_name"]: x["passed"] for x in g["results"]} == {"keys_unique": True, "relationships_intact": True, "reconciliation_residual_zero": True, "completeness_vs_expectation": False}
    at("2026-10-04T10:30:00Z")
    assert command(client, "publish-snapshot", {"run_id": "run-001", "watermark": "2026-10-04T10:00:00Z"}).status_code == 200

    # ---- 11:00 the refund REF-2001 (event 09:10, before the 10:00 watermark) arrives after pub-001: a late event
    refunds = payloads(inputs, "b-101")
    at("2026-10-04T11:00:00Z")
    ingest(client, "src-refunds", "b-101", refunds, next_cursor="cur-001", commit=False)
    at("2026-10-04T11:05:00Z")
    assert command(client, "commit-batch", {"batch_id": "b-101"}).status_code == 200

    # ---- 12:00 the replay of the same ten rows (b-002): 0 new, 9 duplicates, 1 quarantined again
    at("2026-10-04T12:00:00Z")
    command(client, "fetch-source-page", {"source_id": "src-orders", "cursor": "cur-000", "batch_id": "b-002", "page": {"records": orders, "next_cursor": "cur-010"}})
    command(client, "validate-contract", {"batch_id": "b-002"})
    at("2026-10-04T12:05:00Z")
    c2 = command(client, "commit-batch", {"batch_id": "b-002"}).json()["result"]
    assert (c2["accepted_unique"], c2["duplicate"], c2["quarantined"], c2["source_accepted_total"], c2["checkpoint"]["version_number"]) == (0, 9, 1, 8, 2)

    # ---- run-002: an injected duplicate key blocks the gate, opens an incident and the pointer stays on pub-001
    at("2026-10-04T12:10:00Z")
    assert command(client, "transform-models", {"run_id": "run-002", "batch_ids": ["b-001", "b-002"]}).status_code == 200
    at("2026-10-04T12:15:00Z")
    f = command(client, "inject-fault", {"fault_type": "duplicate_key", "target_id": "run-002", "note": "P08-TEST-07"})
    assert f.status_code == 200 and f.json()["result"]["sandbox"] is True
    at("2026-10-04T12:20:00Z")
    g2 = command(client, "run-quality-gate", {"run_id": "run-002"}).json()
    assert g2["result"]["decision"] == "blocked" and g2["result"]["incident_id"] == "inc-001" and g2["warnings"][0]["code"] == "GATE_BLOCKED"
    refused = command(client, "publish-snapshot", {"run_id": "run-002", "watermark": "2026-10-04T10:00:00Z"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "RUN_NOT_SUCCESSFUL"
    assert conn.execute("SELECT publication_id FROM publication_pointer").fetchone()["publication_id"] == "pub-001"

    # ---- 18:00 b-003: the crash after the data write, before the checkpoint
    at("2026-10-04T18:00:00Z")
    command(client, "fetch-source-page", {"source_id": "src-orders", "cursor": "cur-000", "batch_id": "b-003", "page": {"records": orders, "next_cursor": "cur-010"}})
    command(client, "validate-contract", {"batch_id": "b-003"})
    def crash(c, source_id, batch_id):
        raise RuntimeError("process died after the data write")
    cmds.hooks["after_staging"] = crash
    try:
        dead = command(client, "commit-batch", {"batch_id": "b-003"})
    finally:
        cmds.hooks["after_staging"] = None
    assert dead.status_code == 500
    assert (count(conn, "accepted_records", "source_id = 'src-orders'"), conn.execute("SELECT max(version_number) AS v FROM checkpoints WHERE source_id = 'src-orders'").fetchone()["v"]) == (8, 2)

    # ---- run-003 recovers: gate allowed, publish at 20:15 (watermark 11:00), the incident closes with a verified recovery
    at("2026-10-04T20:00:00Z")
    assert command(client, "transform-models", {"run_id": "run-003", "batch_ids": ["b-001", "b-002", "b-101"]}).status_code == 200
    at("2026-10-04T20:10:00Z")
    assert command(client, "run-quality-gate", {"run_id": "run-003"}).json()["result"]["decision"] == "allowed"
    at("2026-10-04T20:15:00Z")
    p = command(client, "publish-snapshot", {"run_id": "run-003", "watermark": "2026-10-04T11:00:00Z"}).json()["result"]
    assert p["publication_id"] == "pub-003" and p["lag_seconds"] == 38700 and p["previous_publication_id"] == "pub-001"
    pubs = {x["publication_id"]: x["content_hash"] for x in golden_inputs()["publications"]}
    assert p["content_hash"] == pubs["pub-003"]                                    # the API computes the fixture's content_hash rule
    at("2026-10-04T20:16:00Z")
    rec = command(client, "recover-incident", {"incident_id": "inc-001"})
    assert rec.status_code == 200 and rec.json()["result"]["recovery_seconds"] == 28500 and rec.json()["result"]["closed_at"] == "2026-10-04T20:15:00Z"

    # ---- backfills: bf-001 accepted, the overlap refused (bf-002), the touching range accepted (bf-003)
    at("2026-10-04T21:00:00Z")
    assert command(client, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-04T00:00:00Z"}, headers=ENGINEER).json()["result"]["backfill_id"] == "bf-001"
    over = command(client, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-03T00:00:00Z", "end_at": "2026-09-06T00:00:00Z"}, headers=ENGINEER)
    assert over.status_code == 409 and over.json()["error"]["code"] == "BACKFILL_OVERLAP"
    touch = command(client, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-04T00:00:00Z", "end_at": "2026-09-05T00:00:00Z"}, headers=ENGINEER)
    assert touch.status_code == 200 and touch.json()["result"]["backfill_id"] == "bf-003"

    # ---- the backend result against the reference
    got = metrics(client, cutoff=CUTOFF)["data"]
    m = got["metrics"]
    orders_src = m["ingestion"]["sources"]["src-orders"]
    assert diff(orders_src["batches"]["b-001"], want["ingestion"]["sources"]["src-orders"]["batches"]["b-001"]) == []
    assert diff(orders_src["batches"]["b-002"], want["ingestion"]["sources"]["src-orders"]["batches"]["b-002"]) == []
    assert (orders_src["batches"]["b-003"]["status"], orders_src["batches"]["b-003"]["counted"], orders_src["batches"]["b-003"]["written_rows"]) == ("staged", False, 10)
    for k in ("received", "accepted_unique", "duplicate", "quarantined", "quarantined_distinct_keys", "rejection_rate", "duplicate_rate", "quarantine_by_reason", "checkpoint"):
        assert orders_src[k] == want["ingestion"]["sources"]["src-orders"][k], k
    assert m["ingestion"]["sources"]["src-refunds"] == want["ingestion"]["sources"]["src-refunds"]
    assert m["freshness"] == want["freshness"] and m["completeness"] == want["completeness"] and m["processing_rate"] == want["processing_rate"]
    assert m["publications"] == want["publications"]
    assert m["reconciliation"] == want["reconciliation"] and m["late_events"] == want["late_events"]
    assert m["incidents"] == want["incidents"]
    assert m["runs"]["durations"] == want["runs"]["durations"]
    assert {rid: (r["status"], r["duration_seconds"]) for rid, r in m["runs"]["runs"].items()} == {rid: (r["status"], r["duration_seconds"]) for rid, r in want["runs"]["runs"].items()}
    assert {rid: g["decision"] for rid, g in m["quality_gate"].items()} == {rid: g["decision"] for rid, g in want["quality_gate"].items()}
    assert m["backfills"]["refused"] == ["bf-002"] and sorted(m["backfills"]["requests"]) == ["bf-001", "bf-003"]
    assert m["backfills"]["requests"]["bf-001"]["requested_partitions"] == 3 and m["backfills"]["requests"]["bf-003"]["requested_partitions"] == 1
    assert m["backfills"]["overall"]["coverage"] == "0.000000"                      # nothing verified yet: 0 of 4, a zero numerator is 0, not null
