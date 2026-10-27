"""The command protocol: identity, roles, envelopes, actor-bound idempotency with dataset_version and role, stale versions, deadlock retries."""
import threading
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import commands as cmds
from api.app import PREFIX, create_app
from api.schemas import FetchSourcePageRequest
from support_db import (ADMIN, ENGINEER, OPERATOR, OPERATOR2, at, client, command, conn, count, db_url, get, ingest, load_world, rule_ids)

FETCH = {"source_id": "src-orders", "cursor": "c0", "batch_id": "b-1", "fetch_session": "s-protocol", "page": {"records": [{"payload": {"record_id": "A-1", "quantity": 1, "unit_price": "1.00", "amount": "1.00", "event_ts": "2026-10-04T08:00:00Z"}}]}}

# command -> (minimal valid body, roles allowed)
ALL3 = {"engineer", "operator", "admin"}
OPS = {"operator", "admin"}
ROLE_MATRIX = {
    "fetch-source-page": (ALL3, FETCH), "validate-contract": (ALL3, {"batch_id": "b-1"}), "commit-batch": (ALL3, {"batch_id": "b-1"}),
    "transform-models": (ALL3, {"batch_ids": ["b-1"]}), "run-quality-gate": (ALL3, {"run_id": "run-1"}),
    "publish-snapshot": (OPS, {"run_id": "run-1", "watermark": "2026-10-04T08:00:00Z"}), "inject-fault": (OPS, {"fault_type": "duplicate_key", "target_id": "run-1"}),
    "request-backfill": (ALL3, {"source_id": "src-orders", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-02T00:00:00Z"}),
    "recover-incident": (OPS, {"incident_id": "inc-001"}), "archive-evidence": (OPS, {"run_id": "run-1"})}
HEADERS = {"engineer": ENGINEER, "operator": OPERATOR, "admin": ADMIN}


@pytest.fixture
def lab(client, conn):
    load_world(conn)
    return client


@pytest.mark.parametrize("name", sorted(ROLE_MATRIX))
def test_role_matrix_and_the_order_of_401_403_422(lab, name):
    roles, body = ROLE_MATRIX[name]
    url = f"{PREFIX}/commands/{name}"
    envelope = {"request_id": "r1", "dataset_version": "ds-api-1", "idempotency_key": f"k-{name}", "input": body}
    anonymous = lab.post(url, json=envelope)
    assert anonymous.status_code == 401 and anonymous.json()["error"]["code"] == "UNAUTHENTICATED" and anonymous.json()["error"]["details"][0]["rule_id"] == "ACTOR_REQUIRED"
    assert lab.post(url, json=envelope, headers={"X-Actor-Id": "  ", "X-Actor-Role": "admin"}).status_code == 401
    assert lab.post(url, json=envelope, headers={"X-Actor-Id": "u1"}).status_code == 403                                  # no role
    assert lab.post(url, json=envelope, headers={"X-Actor-Id": "u1", "X-Actor-Role": "superuser"}).status_code == 403    # a role outside the inventory
    assert lab.post(url, json=envelope, headers={"X-Actor-Id": "u1", "X-Actor-Role": "analyst"}).status_code == 403       # another app's role is not valid here
    for role in sorted(ALL3 - roles):                                                                                      # a role this command does not allow: 403 BEFORE the body is read
        r = lab.post(url, json={"garbage": True}, headers=HEADERS[role])
        assert r.status_code == 403 and r.json()["error"]["details"][0]["rule_id"] == "ROLE_FORBIDDEN", (name, role)
    for role in sorted(roles):                                                                                             # an allowed role reaches validation / the handler
        r = lab.post(url, json={"garbage": True}, headers=HEADERS[role])
        assert r.status_code == 422, (name, role)


def test_unsupported_action_and_method(lab):
    r = lab.post(f"{PREFIX}/commands/delete-everything", json={}, headers=ADMIN)
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNSUPPORTED_ACTION"
    assert lab.get(f"{PREFIX}/commands/commit-batch").status_code == 405
    assert lab.post(f"{PREFIX}/metrics", json={}).status_code == 405


def test_the_response_envelope_and_the_request_id(lab):
    r = command(lab, "fetch-source-page", FETCH, request_id="req-mine")
    body = r.json()
    assert set(body) == {"command_id", "status", "result", "warnings", "version"} and body["command_id"].startswith("cmd-") and body["version"] == 1
    bad = command(lab, "fetch-source-page", {"source_id": "x"}, request_id="req-mine-2")
    assert bad.status_code == 422 and bad.json()["request_id"] == "req-mine-2"
    assert set(bad.json()["error"]) == {"code", "message", "details"} and {d["rule_id"] for d in bad.json()["error"]["details"]} == {"FIELD_REQUIRED"}
    assert lab.post(f"{PREFIX}/commands/commit-batch", content=b"{not json", headers={**ADMIN, "content-type": "application/json"}).json()["error"]["details"][0]["rule_id"] == "BODY_INVALID_JSON"


def test_envelope_fields_are_validated(lab):
    base = {"request_id": "r", "dataset_version": "ds-api-1", "idempotency_key": "k1", "input": FETCH}
    url = f"{PREFIX}/commands/fetch-source-page"
    assert lab.post(url, json={**base, "idempotency_key": "has space"}, headers=ADMIN).json()["error"]["details"][0]["rule_id"] == "IDEMPOTENCY_KEY_INVALID"
    assert lab.post(url, json={**base, "idempotency_key": "x" * 129}, headers=ADMIN).status_code == 422
    assert lab.post(url, json={k: v for k, v in base.items() if k != "dataset_version"}, headers=ADMIN).status_code == 422
    assert lab.post(url, json={**base, "extra": 1}, headers=ADMIN).json()["error"]["details"][0]["rule_id"] == "FIELD_UNEXPECTED"


def test_idempotent_reuse_returns_the_stored_response_and_writes_nothing_twice(lab, conn):
    first = command(lab, "fetch-source-page", FETCH, key="k-same")
    again = command(lab, "fetch-source-page", FETCH, key="k-same", request_id="req-other")                              # request_id is not part of the identity
    assert first.status_code == again.status_code == 200 and again.json() == first.json() and again.headers["Idempotent-Replay"] == "true" and "Idempotent-Replay" not in first.headers
    assert count(conn, "ingestion_batches") == 1 and count(conn, "raw_records") == 1 and count(conn, "audit_events", "action = 'fetch-source-page'") == 1 and count(conn, "command_results") == 1


def test_idempotency_is_bound_to_the_payload_the_actor_and_the_role(lab, conn):
    command(lab, "fetch-source-page", FETCH, key="k1", headers=ENGINEER)
    other_body = command(lab, "fetch-source-page", {**FETCH, "cursor": "c9"}, key="k1", headers=ENGINEER)
    assert other_body.status_code == 409 and other_body.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED" and rule_ids(other_body) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]
    other_actor = command(lab, "fetch-source-page", FETCH, key="k1", headers={"X-Actor-Id": "usr-eng02", "X-Actor-Role": "engineer"})
    assert other_actor.status_code == 409 and rule_ids(other_actor) == ["IDEMPOTENCY_ACTOR_MISMATCH"]
    same_id_other_role = command(lab, "fetch-source-page", FETCH, key="k1", headers={"X-Actor-Id": "usr-eng01", "X-Actor-Role": "operator"})
    assert same_id_other_role.status_code == 409 and rule_ids(same_id_other_role) == ["IDEMPOTENCY_ACTOR_MISMATCH"]       # the role is part of the binding
    other_cmd = command(lab, "validate-contract", {"batch_id": "b-1"}, key="k1", headers=ENGINEER)
    assert other_cmd.status_code == 409                                                                                    # the command name is part of the payload hash
    assert count(conn, "ingestion_batches") == 1 and count(conn, "command_results") == 1


def test_dataset_version_is_part_of_the_binding_and_a_stale_version_is_refused(lab, conn):
    assert command(lab, "fetch-source-page", FETCH, key="kv", dataset_version="ds-api-1").status_code == 200
    other = command(lab, "fetch-source-page", FETCH, key="kv", dataset_version="ds-other")
    assert other.status_code == 409 and rule_ids(other) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]
    stale = command(lab, "fetch-source-page", {**FETCH, "batch_id": "b-2"}, dataset_version="ds-old")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_DATASET_VERSION"
    assert stale.json()["error"]["details"][0]["context"] == {"current": "ds-api-1", "requested": "ds-old"} and count(conn, "ingestion_batches") == 1


def test_a_failed_command_stores_nothing_so_the_same_key_may_be_retried(lab, conn):
    bad = command(lab, "validate-contract", {"batch_id": "b-1"}, key="k-retry")
    assert bad.status_code == 404 and count(conn, "command_results") == 0
    command(lab, "fetch-source-page", FETCH)
    ok = command(lab, "validate-contract", {"batch_id": "b-1"}, key="k-retry")
    assert ok.status_code == 200 and command(lab, "validate-contract", {"batch_id": "b-1"}, key="k-retry").headers["Idempotent-Replay"] == "true"


def _req(key="k-dl"):
    return FetchSourcePageRequest.model_validate({"request_id": "r", "dataset_version": "ds-api-1", "idempotency_key": key, "input": FETCH})


def test_a_deadlock_is_retried_and_the_command_then_succeeds(lab, conn, monkeypatch):
    calls = {"n": 0}
    real = cmds.fetch_source_page

    def flaky(c, req, actor):
        calls["n"] += 1
        if calls["n"] < 3:
            raise psycopg.errors.DeadlockDetected("deadlock detected")
        return real(c, req, actor)
    monkeypatch.setattr(cmds.random, "uniform", lambda a, b: 0)
    body, replayed = cmds.execute("fetch-source-page", _req(), cmds.Actor("u1", "engineer"), flaky)
    assert calls["n"] == 3 and replayed is False and body["status"] == "staged" and count(conn, "ingestion_batches") == 1


def test_three_deadlocks_in_a_row_are_a_409_concurrent_update_never_a_500(lab, conn, monkeypatch):
    calls = {"n": 0}

    def always(c, req, actor):
        calls["n"] += 1
        raise psycopg.errors.DeadlockDetected("deadlock detected")
    monkeypatch.setattr(cmds.random, "uniform", lambda a, b: 0)
    with pytest.raises(Exception) as e:
        cmds.execute("fetch-source-page", _req("k-dl2"), cmds.Actor("u1", "engineer"), always)
    assert calls["n"] == 3 and e.value.status == 409 and e.value.code == "CONCURRENT_UPDATE"
    assert count(conn, "command_results") == 0 and count(conn, "ingestion_batches") == 0


def test_serialization_failures_are_retried_the_same_way(lab, monkeypatch):
    calls = {"n": 0}

    def once(c, req, actor):
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.errors.SerializationFailure("could not serialize")
        return cmds.Outcome("ok", {})
    monkeypatch.setattr(cmds.random, "uniform", lambda a, b: 0)
    body, _ = cmds.execute("fetch-source-page", _req("k-sf"), cmds.Actor("u1", "engineer"), once)
    assert calls["n"] == 2 and body["status"] == "ok"


def test_the_documented_lock_order_names_the_idempotency_key_first():
    doc = cmds.__doc__
    assert doc.index("the idempotency key") < doc.index("source rows, by id") < doc.index("run / backfill / incident rows, by id")


def test_a_failing_audit_write_rolls_the_command_back(lab, conn, monkeypatch):
    real = cmds.Audit

    def bad_audit(*a, **k):
        a_ = real(*a, **k)
        a_.entity_type = None                                                                                              # NOT NULL violation at audit time
        return a_
    monkeypatch.setattr(cmds, "Audit", bad_audit)
    r = command(lab, "fetch-source-page", FETCH)
    assert r.status_code == 500 and count(conn, "ingestion_batches") == 0 and count(conn, "raw_records") == 0 and count(conn, "fetch_log") == 0     # effect and audit commit together or not at all


@pytest.mark.parametrize("name", sorted(ROLE_MATRIX))
@pytest.mark.parametrize("field", ["committed_at", "published_at", "opened_at", "started_at", "closed_at", "verified_at"])
def test_clients_never_supply_the_servers_instants(lab, name, field):
    roles, body = ROLE_MATRIX[name]
    role = sorted(roles)[0]
    r = command(lab, name, {**body, field: "2020-01-01T00:00:00Z"}, headers=HEADERS[role])
    assert r.status_code == 422 and "FIELD_UNEXPECTED" in rule_ids(r)


def test_the_routes_are_the_inventory_of_docs_api_contract_md():
    import re
    from support_db import ROOT
    table = (ROOT / "docs" / "api-contract.md").read_text()
    rows = re.findall(r"^\| (C\d\d|R|M) \| (GET|POST) …/([a-z/{}\-]+)", table, re.MULTILINE)
    assert len(rows) == 12
    paths = create_app().openapi()["paths"]
    for rid, method, path in rows:
        key = f"{PREFIX}/{path}"
        assert key in paths and method.lower() in paths[key], (rid, key)
    assert {r[2] for r in rows if r[0].startswith("C")} == {f"commands/{n}" for n in ROLE_MATRIX}
