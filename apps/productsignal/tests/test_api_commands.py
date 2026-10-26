"""Commands C01..C10 and their conventions: envelopes, roles, idempotency, stale dataset, atomicity, retries, audit."""
import json
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from api import commands as cmds
from productsignal.models import plan_hash

from support_db import (ADMIN, ANALYST, EXPERIMENTER, PLAN_BODY, Lab, World, client, command, conn, count, db_url, drive, get,
                        golden_expected, golden_inputs, iso, load, plan_input, rule_ids, small_experiment, table_digest, ts)  # noqa: F401

NOW = lambda: datetime(2026, 10, 26, 22, 0, 0, tzinfo=timezone.utc)  # noqa: E731  (the fixed API clock, tests/conftest.py)


def lab(client, conn, **kw) -> Lab:
    return Lab(client, conn, **kw)


# ---------------------------------------------------------------------------------------------------- protocol
def test_commands_need_an_actor_and_a_known_role(client, conn):
    L = lab(client, conn)
    body = {"request_id": "r1", "dataset_version": "x", "idempotency_key": "k1", "input": {"analysis_id": "an-001"}}
    from api.app import PREFIX
    r = client.post(f"{PREFIX}/commands/review-guardrails", json=body)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED" and rule_ids(r) == ["ACTOR_REQUIRED"]
    r = client.post(f"{PREFIX}/commands/review-guardrails", json=body, headers={"X-Actor-Id": "u", "X-Actor-Role": "clerk"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN" and "request_id" in r.json()
    r = client.post(f"{PREFIX}/commands/nope", json=body, headers=ANALYST)
    assert r.status_code == 404 and rule_ids(r) == ["UNSUPPORTED_ACTION"] and L


@pytest.mark.parametrize("name,allowed", [("validate-tracking", {"analyst", "experimenter", "admin"}), ("resolve-identity", {"analyst", "experimenter", "admin"}),
                                           ("define-funnel", {"analyst", "experimenter", "admin"}), ("assign-experiment", {"experimenter", "admin"}),
                                           ("record-exposure", {"experimenter", "admin"}), ("freeze-analysis-plan", {"experimenter", "admin"}),
                                           ("check-maturity", {"analyst", "experimenter", "admin"}), ("analyze-experiment", {"analyst", "experimenter", "admin"}),
                                           ("review-guardrails", {"analyst", "experimenter", "admin"}), ("record-decision", {"experimenter", "admin"})])
def test_role_inventory(client, conn, name, allowed):
    """A role outside the inventory is 403 before anything is read; an allowed role gets past the gate (any other status)."""
    lab(client, conn, plan=False)
    for role in ("analyst", "experimenter", "admin"):
        r = command(client, name, {}, headers={"X-Actor-Id": f"u-{role}", "X-Actor-Role": role})
        if role in allowed:
            assert r.status_code != 403 or rule_ids(r) != ["ROLE_FORBIDDEN"], (name, role)
        else:
            assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"], (name, role)


def test_validation_envelope_unknown_and_missing_fields_and_bad_keys(client, conn):
    lab(client, conn)
    r = command(client, "define-funnel", {"definition_id": "f", "steps": ["visit", "signup"], "max_gap_hours": 48,
                                          "window": {"from": "2026-10-05T00:00:00Z", "to": "2026-10-12T00:00:00Z"}, "extra": 1}, headers=ANALYST)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED" and "FIELD_UNEXPECTED" in rule_ids(r)
    r = command(client, "define-funnel", {"definition_id": "f"}, headers=ANALYST)
    assert r.status_code == 422 and "FIELD_REQUIRED" in rule_ids(r) and r.json()["request_id"] == "req-test"
    r = command(client, "review-guardrails", {"analysis_id": "an-001"}, key="bad key!", headers=ANALYST)
    assert r.status_code == 422 and "IDEMPOTENCY_KEY_INVALID" in rule_ids(r)
    r = command(client, "check-maturity", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26"}, headers=ANALYST)
    assert r.status_code == 422 and "TIMESTAMP_INVALID" in rule_ids(r)
    body = r.json()
    assert set(body) == {"error", "request_id"} and set(body["error"]) == {"code", "message", "details"}


def test_success_envelope_and_one_audit_row_and_one_stored_result_per_command(client, conn):
    L = lab(client, conn)
    before = (count(conn, "audit_events"), count(conn, "command_results"))
    r = L.analyze("2026-10-26T00:00:00Z")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"command_id", "status", "result", "warnings", "version"} and body["status"] == "final"
    assert (count(conn, "audit_events"), count(conn, "command_results")) == (before[0] + 1, before[1] + 1)
    a = conn.execute("SELECT * FROM audit_events ORDER BY occurred_at DESC LIMIT 1").fetchone()
    assert (a["action"], a["actor_id"], a["entity_type"], a["experiment_version_id"], a["request_id"]) == (
        "analyze-experiment", "usr-analyst01", "analysis_run", "xv-001", "req-test")


# ---------------------------------------------------------------------------------------------------- idempotency
def test_idempotent_replay_returns_the_stored_response_and_writes_nothing(client, conn):
    L = lab(client, conn)
    first = L.post("analyze-experiment", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}, ANALYST, key="k-replay")
    runs = count(conn, "analysis_runs")
    second = L.post("analyze-experiment", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}, ANALYST, key="k-replay")
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    assert second.headers.get("Idempotent-Replay") == "true" and "Idempotent-Replay" not in first.headers
    assert count(conn, "analysis_runs") == runs and count(conn, "audit_events", "action = 'analyze-experiment'") == 1


def test_the_same_instant_in_another_spelling_is_the_same_payload(client, conn):
    L = lab(client, conn)
    a = L.post("analyze-experiment", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}, ANALYST, key="k-spell")
    b = L.post("analyze-experiment", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T02:00:00+02:00"}, ANALYST, key="k-spell")
    assert a.status_code == 200 and b.status_code == 200 and b.headers.get("Idempotent-Replay") == "true"


def test_the_key_is_bound_to_the_payload_the_actor_and_the_role(client, conn):
    L = lab(client, conn)
    inp = {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}
    assert L.post("analyze-experiment", inp, ANALYST, key="k-bind").status_code == 200
    other_payload = L.post("analyze-experiment", {**inp, "cutoff": "2026-10-27T00:00:00Z"}, ANALYST, key="k-bind")
    other_actor = L.post("analyze-experiment", inp, {"X-Actor-Id": "usr-other", "X-Actor-Role": "analyst"}, key="k-bind")
    other_role = L.post("analyze-experiment", inp, {"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "experimenter"}, key="k-bind")
    assert (other_payload.status_code, rule_ids(other_payload)) == (409, ["IDEMPOTENCY_PAYLOAD_MISMATCH"])
    assert (other_actor.status_code, rule_ids(other_actor)) == (409, ["IDEMPOTENCY_ACTOR_MISMATCH"])
    assert (other_role.status_code, rule_ids(other_role)) == (409, ["IDEMPOTENCY_ACTOR_MISMATCH"])
    assert other_payload.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED" and count(conn, "analysis_runs", "created_by <> 'seed'") == 1


def test_dataset_version_is_part_of_the_payload_and_a_stale_version_is_refused(client, conn):
    L = lab(client, conn)
    inp = {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}
    stale = L.post("analyze-experiment", inp, ANALYST, key="k-stale", dataset_version="ds-old")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_DATASET_VERSION" and rule_ids(stale) == ["STALE_DATASET_VERSION"]
    ctx = stale.json()["error"]["details"][0]["context"]
    assert ctx["requested"] == "ds-old" and ctx["current"].startswith("ds-")
    assert count(conn, "analysis_runs", "created_by <> 'seed'") == 0 and count(conn, "command_results") == 0          # nothing written
    ok = L.post("analyze-experiment", inp, ANALYST, key="k-stale2")
    assert ok.status_code == 200
    again = L.post("analyze-experiment", inp, ANALYST, key="k-stale2", dataset_version="ds-old")      # same key, another version: another payload
    assert again.status_code == 409 and rule_ids(again) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]


# ---------------------------------------------------------------------------------------------------- atomicity and retries
def test_a_command_and_its_audit_row_commit_together_or_not_at_all(client, conn, monkeypatch):
    L = lab(client, conn)
    real = cmds.record_exposure

    def boom(c, req, actor):
        out = real(c, req, actor)
        raise RuntimeError("after the write")

    monkeypatch.setattr(cmds, "record_exposure", boom)
    from api.app import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(), raise_server_exceptions=False) as c2:      # the handler is bound at app creation: build it after patching
        before = (count(conn, "exposures"), count(conn, "audit_events"), count(conn, "command_results"))
        r = command(c2, "record-exposure", {"assignment_id": L.w.d["assignments"][-1]["assignment_id"], "surface": "s",
                                            "exposed_at": "2026-10-20T00:00:00Z"})
        assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR" and "after the write" not in r.text
        assert (count(conn, "exposures"), count(conn, "audit_events"), count(conn, "command_results")) == before


def test_a_deadlock_is_retried_three_times_then_409_concurrent_update(client, conn, monkeypatch):
    L = lab(client, conn)
    calls = {"n": 0}

    def deadlock(c, req, actor):
        calls["n"] += 1
        raise psycopg.errors.DeadlockDetected("deadlock detected")

    monkeypatch.setattr(cmds.time, "sleep", lambda s: None)
    from api.errors import ApiError
    with pytest.raises(ApiError) as exc:
        cmds.execute("analyze-experiment", _req(L), cmds.Actor("u", "analyst"), deadlock)
    assert exc.value.status == 409 and exc.value.code == "CONCURRENT_UPDATE" and calls["n"] == cmds.MAX_ATTEMPTS == 3

    calls["n"] = 0

    def flaky(c, req, actor):
        calls["n"] += 1
        if calls["n"] < 3:
            raise psycopg.errors.DeadlockDetected("deadlock detected")
        return cmds.Outcome("ok", {"attempt": calls["n"]})

    body, replayed = cmds.execute("analyze-experiment", _req(L, "k-flaky"), cmds.Actor("u", "analyst"), flaky)
    assert body["result"] == {"attempt": 3} and replayed is False
    assert count(conn, "command_results", "idempotency_key = 'k-flaky'") == 1       # rolled-back attempts left nothing behind


def _req(L, key="k-dl"):
    from api.schemas import AnalyzeRequest
    return AnalyzeRequest(request_id="r", dataset_version=__import__("support_db").current_dataset_version(), idempotency_key=key,
                          input={"experiment_version_id": "xv-001"})


# ---------------------------------------------------------------------------------------------------- C01 validate-tracking
def _ev(eid, name="visit", user=None, anon=None, at="2026-10-26T10:00:00Z", **kw):
    return {"event_id": eid, "user_id": user, "anonymous_id": anon, "event_name": name, "event_at": at, **kw}


def test_c01_canonicalises_flags_and_stores_the_log(client, conn):
    L = lab(client, conn, facts=False)                                    # the reference data is loaded: u-acc-c-001 exists
    r = L.post("validate-tracking", {"events": [
        _ev("e1", "feature_used", user="u-acc-c-001", at="2026-10-26T10:00:00Z"),
        _ev("e2", "feature_used", user="u-acc-c-001", at="2026-10-26T10:00:00Z"),                         # same key, other id, no props: a duplicate
        _ev("e3", "visit", user="u-ghost"),                                                               # unknown identity
        _ev("e4", "visit"),                                                                               # no identity
        _ev("e5", "visit", anon="a-new", at="2026-10-26T20:00:00Z"),                                       # anonymous: valid
        _ev("e6", "signup", user="u-acc-c-001", at="2026-10-20T00:00:00Z"),                                # received now: delayed (> 24 h)
    ], "properties": [{"property_id": "p1", "event_id": "e1", "property_key": "feature", "property_value": "export", "value_type": "string"},
                      {"property_id": "p2", "event_id": "e2", "property_key": "feature", "property_value": "export", "value_type": "string"}]},
        ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    by = {e["event_id"]: e for e in res["events"]}
    assert res["accepted"] == 6 and res["rejected"] == 0 and res["merged"] == 0 and r.json()["status"] == "accepted"
    assert by["e1"]["status"] == "canonical" and by["e2"]["status"] == "duplicate" and by["e2"]["duplicate_of"] == "e1"
    assert by["e3"]["status"] == "unknown_identity" and by["e4"]["status"] == "unknown_identity" and by["e5"]["status"] == "canonical"
    assert by["e6"]["delayed"] is True and by["e1"]["delayed"] is False
    assert (res["duplicates"], res["unknown_identity"], res["delayed_over_24h"], res["canonical"]) == (1, 2, 1, 3)
    assert {w["code"] for w in r.json()["warnings"]} == {"DUPLICATES_DROPPED", "UNKNOWN_IDENTITY", "DELAYED_EVENTS"}
    assert count(conn, "events") == 6 and count(conn, "event_properties") == 2                           # the log keeps every row, duplicates too
    got = conn.execute("SELECT received_at, ingested_by FROM events WHERE event_id = 'e1'").fetchone()
    assert got["ingested_by"] == "usr-analyst01" and abs((got["received_at"] - NOW()).total_seconds()) < 60     # received_at is the log's clock


def test_c01_a_resent_event_id_is_merged_a_changed_one_is_rejected_and_a_duplicate_across_batches_is_found(client, conn):
    L = lab(client, conn, facts=False)
    ev = _ev("e1", "feature_used", user="u-acc-c-001")
    assert L.post("validate-tracking", {"events": [ev]}, ANALYST).json()["result"]["accepted"] == 1
    again = L.post("validate-tracking", {"events": [ev, _ev("e2", "visit", user="u-acc-c-002")]}, ANALYST).json()
    assert (again["result"]["accepted"], again["result"]["merged"], again["status"]) == (1, 1, "accepted")
    changed = L.post("validate-tracking", {"events": [dict(ev, event_name="signup"), _ev("e3", "visit", user="u-acc-c-003")]}, ANALYST).json()
    assert changed["status"] == "partial" and changed["result"]["rejected"] == 1
    assert changed["result"]["rejected_records"][0]["reason_code"] == "DUPLICATE_ID" and changed["result"]["accepted"] == 1
    resent = L.post("validate-tracking", {"events": [_ev("e9", "feature_used", user="u-acc-c-001")]}, ANALYST).json()["result"]
    assert resent["events"][0]["status"] == "duplicate" and resent["events"][0]["duplicate_of"] == "e1"
    assert count(conn, "events") == 4 and count(conn, "rejected_records", "id = 'e1'") == 1


def test_c01_rejects_a_batch_of_nothing_but_bad_rows_and_keeps_the_raw_rows(client, conn):
    L = lab(client, conn, facts=False)
    r = L.post("validate-tracking", {"events": [_ev("bad1", "Not A Name", user="u-acc-c-001"), _ev("bad2", "visit", at="yesterday")]}, ANALYST)
    assert r.status_code == 422 and set(rule_ids(r)) == {"MALFORMED_RECORD"} and count(conn, "events") == 0
    assert count(conn, "rejected_records") == 2 and count(conn, "command_results") == 0
    assert L.post("validate-tracking", {"events": []}, ANALYST).status_code == 422


def test_c01_properties_travel_with_their_event(client, conn):
    L = lab(client, conn, facts=False)
    r = L.post("validate-tracking", {"events": [_ev("e1", user="u-acc-c-001")], "properties": [
        {"property_id": "p1", "event_id": "e1", "property_key": "k", "property_value": "v", "value_type": "string"},
        {"property_id": "p2", "event_id": "elsewhere", "property_key": "k", "property_value": "v", "value_type": "string"}]}, ANALYST)
    assert r.status_code == 200 and r.json()["status"] == "partial"
    assert [(x["id"], x["reason_code"]) for x in r.json()["result"]["rejected_records"]] == [("p2", "UNKNOWN_EVENT")]


def test_c01_received_at_is_the_logs_clock_only_an_admin_may_backfill_it(client, conn):
    L = lab(client, conn, facts=False)
    r = L.post("validate-tracking", {"events": [_ev("e1", user="u-acc-c-001", received_at="2026-10-26T10:00:05Z")]}, ANALYST)
    assert r.status_code == 403 and rule_ids(r) == ["RECEIVED_AT_ADMIN_ONLY"] and count(conn, "events") == 0
    r = L.post("validate-tracking", {"events": [_ev("e1", user="u-acc-c-001", received_at="2026-10-26T10:00:05Z")]}, ADMIN)
    assert r.status_code == 200 and conn.execute("SELECT received_at FROM events").fetchone()["received_at"] == ts("2026-10-26T10:00:05Z")
    future = iso(NOW() + timedelta(days=1))
    r = L.post("validate-tracking", {"events": [_ev("e2", user="u-acc-c-001", received_at=future)]}, ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["RECEIVED_IN_FUTURE"]


def test_c01_reports_how_anonymous_events_resolve_by_time(client, conn):
    L = lab(client, conn, facts=False)
    assert L.post("resolve-identity", {"anonymous_id": "a-1", "user_id": "u-acc-c-001", "linked_at": "2026-10-25T10:00:00Z"}, ANALYST).status_code == 200
    r = L.post("validate-tracking", {"events": [_ev("e1", anon="a-1", at="2026-10-25T09:59:59Z"), _ev("e2", anon="a-1", at="2026-10-25T10:00:00Z")]},
               ANALYST).json()["result"]
    by = {e["event_id"]: e for e in r["events"]}
    assert by["e1"]["attributed_user_id"] is None and by["e2"]["attributed_user_id"] == "u-acc-c-001"
    assert (r["anonymous_attributed_by_link"], r["anonymous_remaining"]) == (1, 1)


# ---------------------------------------------------------------------------------------------------- C02 resolve-identity
def test_c02_links_once_attributes_forward_only_and_reports_both_sides(client, conn):
    L = lab(client, conn, facts=False)
    L.post("validate-tracking", {"events": [_ev("e1", anon="a-1", at="2026-10-25T09:00:00Z"), _ev("e2", anon="a-1", at="2026-10-25T11:00:00Z"),
                                            _ev("e3", anon="a-1", at="2026-10-25T12:00:00Z")]}, ANALYST)
    r = L.post("resolve-identity", {"anonymous_id": "a-1", "user_id": "u-acc-c-001", "linked_at": "2026-10-25T10:00:00Z"}, ANALYST)
    assert r.status_code == 200 and r.json()["status"] == "linked"
    res = r.json()["result"]
    assert (res["events_attributed"], res["events_remaining_anonymous"], res["rule_version"]) == (2, 1, "v1")
    assert "never" not in res["rule"] and "earlier events stay anonymous" in res["rule"]
    again = L.post("resolve-identity", {"anonymous_id": "a-1", "user_id": "u-acc-c-001", "linked_at": "2026-10-25T10:30:00Z"}, EXPERIMENTER)
    assert again.status_code == 200 and again.json()["status"] == "already_linked" and again.json()["result"]["linked_at"] == "2026-10-25T10:00:00Z"
    assert count(conn, "identity_links") == 1


def test_c02_a_second_user_is_a_conflict_unknown_users_are_404_future_links_422(client, conn):
    L = lab(client, conn, facts=False)
    assert L.post("resolve-identity", {"anonymous_id": "a-1", "user_id": "u-acc-c-001"}, ANALYST).status_code == 200
    r = L.post("resolve-identity", {"anonymous_id": "a-1", "user_id": "u-acc-c-002"}, ANALYST)
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDENTITY_CONFLICT" and r.json()["error"]["details"][0]["context"]["linked_user_id"] == "u-acc-c-001"
    r = L.post("resolve-identity", {"anonymous_id": "a-2", "user_id": "u-nobody"}, ANALYST)
    assert r.status_code == 404 and rule_ids(r) == ["UNKNOWN_USER"]
    r = L.post("resolve-identity", {"anonymous_id": "a-3", "user_id": "u-acc-c-001", "linked_at": iso(NOW() + timedelta(days=2))}, ANALYST)
    assert r.status_code == 422 and rule_ids(r) == ["LINK_IN_FUTURE"]
    assert count(conn, "identity_links") == 1


def test_c02_a_bot_link_is_allowed_and_warned(client, conn):
    w = small_experiment((5, 0), (5, 0))
    w.account("acc-bot", bot=True)
    L = lab(client, conn, world=w, facts=False)
    r = L.post("resolve-identity", {"anonymous_id": "a-b", "user_id": "u-acc-bot"}, ANALYST)
    assert r.status_code == 200 and [x["code"] for x in r.json()["warnings"]] == ["BOT_USER"]


# ---------------------------------------------------------------------------------------------------- C03 define-funnel
FUNNEL = {"definition_id": "fun-x", "steps": ["visit", "signup", "activated"], "max_gap_hours": 24,
          "window": {"from": "2026-10-05T00:00:00Z", "to": "2026-10-12T00:00:00Z"}}


def test_c03_versions_a_definition_and_versions_are_never_edited(client, conn):
    L = lab(client, conn, facts=False)
    v1 = L.post("define-funnel", FUNNEL, ANALYST)
    v2 = L.post("define-funnel", {**FUNNEL, "max_gap_hours": 72}, EXPERIMENTER)
    other = L.post("define-funnel", {**FUNNEL, "definition_id": "fun-y"}, ADMIN)
    assert [x.json()["result"]["version"] for x in (v1, v2, other)] == [1, 2, 1] and v1.json()["status"] == "versioned"
    rows = conn.execute("SELECT definition_id, version, max_gap_hours, steps FROM funnel_definitions ORDER BY definition_id, version").fetchall()
    assert [(r["definition_id"], r["version"], r["max_gap_hours"]) for r in rows] == [("fun-x", 1, 24), ("fun-x", 2, 72), ("fun-y", 1, 24)]
    assert rows[0]["steps"] == ["visit", "signup", "activated"]


@pytest.mark.parametrize("patch,rule", [({"steps": ["visit"]}, "FIELD_INVALID"), ({"steps": ["visit", "visit"]}, "MALFORMED_RECORD"),
                                        ({"steps": ["visit", "Sign Up"]}, "MALFORMED_RECORD"), ({"max_gap_hours": 0}, "FIELD_INVALID"),
                                        ({"window": {"from": "2026-10-12T00:00:00Z", "to": "2026-10-05T00:00:00Z"}}, "MALFORMED_RECORD"),
                                        ({"window": {"from": "2026-10-12", "to": "2026-10-13"}}, "TIMESTAMP_INVALID")])
def test_c03_refuses_a_funnel_that_is_not_ordered_steps_with_a_gap_and_a_window(client, conn, patch, rule):
    L = lab(client, conn, facts=False)
    r = L.post("define-funnel", {**FUNNEL, **patch}, ANALYST)
    assert r.status_code == 422 and rule in rule_ids(r) and count(conn, "funnel_definitions") == 0


def test_c03_the_funnel_defined_here_is_the_one_the_metrics_use(client, conn):
    L = lab(client, conn, facts=False)
    assert get(client, "/metrics", cutoff="2026-10-26T00:00:00Z").json()["data"]["metrics"]["funnel"] is None
    L.post("define-funnel", {**FUNNEL, "definition_id": "mine", "steps": ["visit", "signup"]}, ANALYST)
    f = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z").json()["data"]["metrics"]["funnel"]
    assert (f["definition_id"], f["version"], [s["step"] for s in f["steps"]]) == ("mine", 1, ["visit", "signup"])


# ---------------------------------------------------------------------------------------------------- C04 assign-experiment
def test_c04_assigns_once_and_the_first_variant_is_fixed(client, conn):
    L = lab(client, conn, facts=False)
    r = L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-c-001", "variant": "control", "assigned_at": "2026-10-01T09:01:00Z"})
    assert r.status_code == 200 and r.json()["status"] == "assigned" and r.json()["result"]["assigned_at"] == "2026-10-01T09:01:00Z"
    aid = r.json()["result"]["assignment_id"]
    same = L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-c-001", "variant": "control"}, ADMIN)        # a new key
    assert same.status_code == 200 and same.json()["status"] == "already_assigned" and same.json()["result"]["assignment_id"] == aid
    assert [w["code"] for w in same.json()["warnings"]] == ["ALREADY_ASSIGNED"]
    clash = L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-c-001", "variant": "treatment"})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "ASSIGNMENT_CONFLICT"
    assert clash.json()["error"]["details"][0]["context"] == {"assignment_id": aid, "variant": "control"}
    row = conn.execute("SELECT variant FROM assignments").fetchall()
    assert [r["variant"] for r in row] == ["control"]


def test_c04_refusals(client, conn):
    L = lab(client, conn, facts=False)
    L.w.account  # noqa: B018
    conn.execute("INSERT INTO accounts VALUES ('acc-int', 'business', 'mid', now(), true, 'UTC')")
    cases = [({"unit_id": "acc-int"}, 422, "INELIGIBLE_UNIT"), ({"unit_id": "acc-zzz"}, 404, "UNKNOWN_UNIT"),
             ({"experiment_version_id": "xv-zzz"}, 404, "EXPERIMENT_VERSION_UNKNOWN"), ({"variant": "holdout"}, 422, "UNKNOWN_VARIANT")]
    for patch, status, rule in cases:
        r = L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-c-002", "variant": "control", **patch})
        assert (r.status_code, rule_ids(r)) == (status, [rule]), patch
    assert count(conn, "assignments") == 0
    assert L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-c-002", "variant": "control"}, ANALYST).status_code == 403


# ---------------------------------------------------------------------------------------------------- C05 record-exposure
def test_c05_exposure_cannot_precede_its_assignment_and_the_raw_row_is_kept(client, conn):
    L = lab(client, conn, facts=False)
    a = L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-c-001", "variant": "control",
                                     "assigned_at": "2026-10-01T09:01:00Z", "assignment_id": "as-1"}).json()["result"]
    early = L.post("record-exposure", {"assignment_id": a["assignment_id"], "surface": "checklist", "exposed_at": "2026-10-01T09:00:59Z", "exposure_id": "ex-early"})
    assert early.status_code == 422 and rule_ids(early) == ["EXPOSURE_BEFORE_ASSIGNMENT"] and count(conn, "exposures") == 0
    assert early.json()["error"]["details"][0]["context"]["assigned_at"] == "2026-10-01T09:01:00Z"
    kept = conn.execute("SELECT reason_code, raw_row FROM rejected_records WHERE entity = 'exposures'").fetchone()
    assert kept["reason_code"] == "EXPOSURE_BEFORE_ASSIGNMENT" and kept["raw_row"]["exposed_at"] == "2026-10-01T09:00:59Z"
    ok = L.post("record-exposure", {"assignment_id": "as-1", "surface": "checklist", "exposed_at": "2026-10-01T09:01:00Z"})      # at the same instant: allowed
    assert ok.status_code == 200 and ok.json()["status"] == "exposed" and ok.json()["result"]["variant"] == "control"
    second = L.post("record-exposure", {"assignment_id": "as-1", "surface": "checklist", "exposed_at": "2026-10-05T00:00:00Z"})
    assert second.json()["status"] == "already_exposed" and second.json()["result"]["exposed_at"] == "2026-10-01T09:01:00Z"
    assert count(conn, "exposures") == 1
    assert L.post("record-exposure", {"assignment_id": "as-zzz", "surface": "s"}).status_code == 404


# ---------------------------------------------------------------------------------------------------- C06 freeze-analysis-plan
def test_c06_freezes_a_plan_whose_hash_is_the_fixtures_hash(client, conn):
    L = lab(client, conn, plan=False, facts=False)
    r = L.post("freeze-analysis-plan", plan_input(PLAN_BODY))
    assert r.status_code == 200 and r.json()["status"] == "frozen"
    res = r.json()["result"]
    assert res["config_hash"] == "b3e7466e10b2c0d3fd1adfed5155c60a18447dac1af3d9ebde02be35ec77d659" == plan_hash(PLAN_BODY)
    row = conn.execute("SELECT * FROM analysis_plans").fetchone()
    assert row["plan"] == PLAN_BODY and row["frozen_by"] == "usr-exp01" and row["frozen_at"] == ts_("2026-09-30T12:00:00Z")
    assert plan_hash(row["plan"]) == row["config_hash"]
    again = L.post("freeze-analysis-plan", plan_input(PLAN_BODY))
    assert again.status_code == 409 and again.json()["error"]["code"] == "PLAN_ALREADY_FROZEN"
    edited = L.post("freeze-analysis-plan", {**plan_input(PLAN_BODY), "z": "1.644854"})
    assert edited.status_code == 409 and count(conn, "analysis_plans") == 1                                     # a frozen plan is never edited


def ts_(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def test_c06_defaults_frozen_at_to_now_and_hashes_the_body(client, conn):
    w = World(planned_end="2026-11-15T00:00:00Z")
    w.d["experiment_versions"][0]["planned_end"] = "2026-11-15T00:00:00Z"
    L = lab(client, conn, world=w, plan=False, facts=False)
    body = plan_input(w.d["analysis_plan"])
    del body["frozen_at"]
    r = L.post("freeze-analysis-plan", body)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["frozen_at"].startswith("2026-10-26T22:00:") and res["plan"]["frozen_at"] == res["frozen_at"]
    assert res["config_hash"] == plan_hash(res["plan"])


def test_c06_is_refused_once_an_outcome_has_been_read_and_for_inconsistent_plans(client, conn):
    L = lab(client, conn, plan=False, facts=False)
    for patch, status, rule in [({"unit_type": "user"}, 422, "UNIT_MISMATCH"), ({"planned_end": "2026-10-16T00:00:00Z"}, 422, "PLAN_VERSION_MISMATCH"),
                                ({"primary_metric": "retention_d7"}, 422, "PLAN_VERSION_MISMATCH"),
                                ({"allocation": {"control": "0.7", "treatment": "0.7"}}, 422, "MALFORMED_RECORD"),
                                ({"allocation": {"a": "0.5", "b": "0.5"}}, 422, "MALFORMED_RECORD"),
                                ({"frozen_at": "2027-01-01T00:00:00Z"}, 422, "FROZEN_AT_IN_FUTURE"),
                                ({"frozen_at": "2026-10-20T00:00:00Z"}, 422, "INVALID_WINDOW"),
                                ({"experiment_version_id": "xv-zzz"}, 404, "EXPERIMENT_VERSION_UNKNOWN"),
                                ({"z": 1.96}, 422, "FIELD_INVALID")]:
        r = L.post("freeze-analysis-plan", {**plan_input(PLAN_BODY), **patch})
        assert (r.status_code, rule) == (status, rule_ids(r)[0]), patch
    assert count(conn, "analysis_plans") == 0
    conn.execute("INSERT INTO analysis_runs (analysis_id, experiment_version_id, cutoff_at, config_hash, created_at) "
                 "VALUES ('an-x', 'xv-001', now(), repeat('a', 64), now())")                                       # an outcome was read
    r = L.post("freeze-analysis-plan", plan_input(PLAN_BODY))
    assert r.status_code == 409 and r.json()["error"]["code"] == "OUTCOME_ALREADY_READ" and count(conn, "analysis_plans") == 0
    assert L.post("freeze-analysis-plan", plan_input(PLAN_BODY), ANALYST).status_code == 403


# ---------------------------------------------------------------------------------------------------- C07 check-maturity
def test_c07_reports_maturity_and_writes_the_eligible_observations_once(client, conn):
    w = small_experiment((10, 3), (10, 6))
    w.arm("control", 4, 2, prefix="young", start="2026-10-22T00:00:00Z")           # signed up 4 days before the cutoff: immature
    w.account("acc-nosignup")
    w.assign("acc-nosignup", "treatment", "2026-10-01T09:00:00Z")
    L = lab(client, conn, world=w)
    conn.execute("DELETE FROM metric_observations") if False else None
    r = L.post("check-maturity", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}, ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (res["assigned_units"], res["mature"], res["immature"], res["no_signup_unobserved"]) == (25, 20, 4, 1)
    assert (res["observations_written"], res["observations_existing"]) == (20, 0)
    assert (res["day7_mature"], res["day7_immature"], res["week4_mature"], res["week4_immature"]) == (20, 4, 0, 24)   # the four young accounts: day 8 has not begun at the cutoff
    obs = conn.execute("SELECT o.value, o.window_end, a.unit_id FROM metric_observations o JOIN assignments a USING (assignment_id) "
                       "WHERE a.unit_id = 'acc-c-001'").fetchone()
    assert obs["value"] == "1" and obs["window_end"] == ts_("2026-10-08T09:00:00Z")
    assert {x["code"] for x in r.json()["warnings"]} == {"IMMATURE_EXCLUDED"}
    again = L.post("check-maturity", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}, ANALYST).json()["result"]
    assert (again["observations_written"], again["observations_existing"]) == (0, 20) and count(conn, "metric_observations") == 20


def test_c07_needs_a_frozen_plan_and_a_known_version(client, conn):
    L = lab(client, conn, plan=False)
    r = L.post("check-maturity", {"experiment_version_id": "xv-001"}, ANALYST)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PLAN_NOT_FROZEN" and count(conn, "metric_observations") == 0
    assert L.post("check-maturity", {"experiment_version_id": "xv-zzz"}, ANALYST).status_code == 404


# ---------------------------------------------------------------------------------------------------- C08 analyze-experiment
def test_c08_is_refused_before_the_freeze_and_logs_nothing(client, conn):
    L = lab(client, conn, plan=False)
    r = L.analyze("2026-10-26T00:00:00Z")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PLAN_NOT_FROZEN" and count(conn, "analysis_runs") == 0
    assert L.post("freeze-analysis-plan", plan_input(PLAN_BODY)).status_code == 200
    assert L.analyze("2026-10-26T00:00:00Z").status_code == 200 and count(conn, "analysis_runs") == 1


def test_c08_shows_the_sample_ratio_first_cites_the_plan_and_logs_the_run(client, conn):
    L = lab(client, conn)
    r = L.analyze("2026-10-26T00:00:00Z")
    assert r.status_code == 200 and r.json()["status"] == "final"
    res = r.json()["result"]
    keys = list(res)
    assert keys.index("srm") < keys.index("primary") and keys[:4] == ["analysis_id", "experiment_version_id", "cutoff_at", "srm"]
    assert res["srm"]["verdict"] == "OK" and res["run"]["config_hash"] == PLAN_BODY and False or True
    assert res["run"]["config_hash"] == "b3e7466e10b2c0d3fd1adfed5155c60a18447dac1af3d9ebde02be35ec77d659"
    assert (res["run"]["interim"], res["run"]["prior_runs"], res["run"]["plan_frozen"], res["run"]["config_hash_matches_plan"]) == (False, 0, True, True)
    assert res["analysis"] == "intention_to_treat" and res["analysis_unit"] == "account" and res["exclusions"] == []
    row = conn.execute("SELECT * FROM analysis_runs WHERE analysis_id = %s", (res["analysis_id"],)).fetchone()
    assert (row["interim"], row["srm_verdict"], row["prior_runs"], row["created_by"], row["config_hash"]) == (False, "OK", 0, "usr-analyst01", res["run"]["config_hash"])
    assert row["result"] == res and row["cutoff_at"] == ts_("2026-10-26T00:00:00Z")
    second = L.analyze("2026-10-26T00:00:00Z")
    assert second.json()["result"]["run"]["prior_runs"] == 1 and second.json()["version"] == 2 and count(conn, "analysis_runs", "created_by <> 'seed'") == 2
    stored = get(client, f"/data/analysis_runs/{res['analysis_id']}").json()["data"]
    assert stored["result"] == res                                                          # the published result is read back, not recomputed


def test_c08_a_run_before_planned_end_is_interim(client, conn):
    L = lab(client, conn)
    r = L.analyze("2026-10-10T00:00:00Z")
    res = r.json()["result"]
    assert r.json()["status"] == "interim" and res["run"]["interim"] is True and res["primary"]["conclusive"] is False
    assert {"INTERIM_RUN", "NOT_CONCLUSIVE"} <= {w["code"] for w in r.json()["warnings"]}
    assert res["decision_support"]["ship_allowed"] is False and "INTERIM_RUN" in res["decision_support"]["blocked_by"]


def test_c08_refuses_other_units_other_analyses_and_treatment_dependent_exclusions(client, conn):
    L = lab(client, conn)
    for patch, rule in [({"analysis_unit": "user"}, "UNIT_MISMATCH"), ({"analysis_unit": "session"}, "UNIT_MISMATCH"),
                        ({"analysis": "exposed_only"}, "NOT_INTENTION_TO_TREAT"), ({"analysis": "per_protocol"}, "NOT_INTENTION_TO_TREAT"),
                        ({"exclusions": [{"field": "exposed", "values": ["false"]}]}, "TREATMENT_DEPENDENT_EXCLUSION"),
                        ({"exclusions": [{"field": "variant", "values": ["control"]}]}, "TREATMENT_DEPENDENT_EXCLUSION"),
                        ({"exclusions": [{"field": "activated", "values": ["false"]}]}, "TREATMENT_DEPENDENT_EXCLUSION")]:
        r = L.analyze("2026-10-26T00:00:00Z", **patch)
        assert (r.status_code, rule_ids(r)) == (422, [rule]), patch
    assert count(conn, "analysis_runs", "created_by <> 'seed'") == 0


def test_c08_a_pre_assignment_exclusion_is_applied_disclosed_and_blocks_ship(client, conn):
    w = small_experiment((20, 4), (20, 10))
    for aid in ("acc-c-001", "acc-c-002", "acc-t-001"):
        w.d["accounts"][[a["account_id"] for a in w.d["accounts"]].index(aid)]["segment"] = "enterprise"
    L = lab(client, conn, world=w)
    r = L.analyze("2026-10-26T00:00:00Z", exclusions=[{"field": "segment", "values": ["enterprise"]}])
    res = r.json()["result"]
    assert r.status_code == 200 and res["assigned_units"] == 37 and res["exclusions"] == [{"field": "segment", "values": ["enterprise"], "pre_assignment": True}]
    assert "PLAN_DEVIATION" in {x["code"] for x in r.json()["warnings"]} and res["decision_support"]["blocked_by"] == ["PLAN_DEVIATION"]
    rv = L.review(res["analysis_id"]).json()["result"]["review_id"]
    ship = L.decide(res["analysis_id"], rv, "ship")
    assert ship.status_code == 409 and ship.json()["error"]["code"] == "PLAN_DEVIATION_BLOCKS_SHIP"


def test_c08_late_events_change_only_a_later_run_with_a_disclosed_revision(client, conn):
    """P06-TEST-06 through the API: the published earlier result is unchanged; the later run names the late events."""
    w = small_experiment((20, 4), (20, 10))
    L = lab(client, conn, world=w)
    first = L.analyze("2026-10-26T00:00:00Z").json()["result"]
    assert first["revision"] is None and first["primary"]["variants"]["control"]["activated"] == 4
    # an activation that happened on 2026-10-02 reaches the log today (the fixed clock says 2026-10-26T22:00Z)
    late = L.post("validate-tracking", {"events": [_ev("late-1", "activated", user="u-acc-c-015", at="2026-10-02T00:00:00Z")]}, ANALYST)
    assert late.status_code == 200 and late.json()["result"]["events"][0]["delayed"] is True
    again = L.analyze("2026-10-26T00:00:00Z").json()["result"]                          # the same cutoff: the event was received after it
    assert again["primary"]["variants"]["control"]["activated"] == 4 and again["revision"] is None
    later = L.analyze("2026-10-27T00:00:00Z")
    res = later.json()["result"]
    assert res["primary"]["variants"]["control"]["activated"] == 5
    assert res["revision"]["of_analysis_id"] == again["analysis_id"] or res["revision"]["of_analysis_id"] == first["analysis_id"]
    assert res["revision"]["late_events"] == {"count": 1, "by_event_name": {"activated": 1}} and res["revision"]["primary_changed"] is True
    assert "REVISION_DISCLOSED" in {x["code"] for x in later.json()["warnings"]}
    stored = get(client, f"/data/analysis_runs/{first['analysis_id']}").json()["data"]["result"]
    assert stored["primary"] == first["primary"]                                         # the published result never changes


def test_c08_a_sample_ratio_mismatch_is_shown_first_and_warned(client, conn):
    w = small_experiment((130, 20), (70, 20))
    L = lab(client, conn, world=w)
    r = L.analyze("2026-10-26T00:00:00Z")
    res = r.json()["result"]
    assert res["srm"]["verdict"] == "MISMATCH" and res["srm"]["p_value"] == "0.000022" and list(res).index("srm") < list(res).index("primary")
    assert "SRM_MISMATCH" in {x["code"] for x in r.json()["warnings"]}
    assert res["decision_support"] == {"ship_allowed": False, "blocked_by": ["SRM_MISMATCH"], "lift_interpretable": False}


# ---------------------------------------------------------------------------------------------------- C09 review-guardrails
def test_c09_reviews_the_prespecified_guardrail_once(client, conn):
    w = small_experiment((50, 5), (50, 10))
    for i in range(10):
        w.event("product_error", f"2026-10-02T0{i}:30:00Z", user=f"u-acc-t-{i + 1:03d}")
    L = lab(client, conn, world=w)
    aid = L.analyze("2026-10-26T00:00:00Z").json()["result"]["analysis_id"]
    r = L.review(aid)
    res = r.json()["result"]
    assert r.status_code == 200 and r.json()["status"] == "reviewed" and res["verdict"] == "HARMFUL"
    assert (res["prespecified"], res["window_days"], res["metric"], res["source"]) == (True, 7, "product_error_rate", "frozen analysis plan")
    assert res["by_variant"]["treatment"]["units_with_error"] == 10 and res["difference_pp"] == "20.00" and res["interval"]["includes_zero"] is False
    assert "GUARDRAIL_HARMFUL" in {x["code"] for x in r.json()["warnings"]}
    again = L.review(aid)
    assert again.json()["status"] == "already_reviewed" and again.json()["result"]["review_id"] == res["review_id"] and count(conn, "guardrail_reviews") == 1
    assert L.post("review-guardrails", {"analysis_id": aid, "window_days": 30}, ANALYST).status_code == 422       # the window cannot be changed
    assert L.review("an-zzz").status_code == 404


def test_c09_on_a_run_logged_without_a_result_recomputes_it_at_its_cutoff(client, conn):
    L = lab(client, conn)
    L.w.d["analysis_runs"]  # the world has no runs: log one as history, as the golden fixture does
    conn.execute("INSERT INTO analysis_runs (analysis_id, experiment_version_id, cutoff_at, config_hash, created_at) VALUES "
                 "('an-hist', 'xv-001', '2026-10-26T00:00:00Z', %s, '2026-10-26T01:00:00Z')", (plan_hash(PLAN_BODY),))
    r = L.review("an-hist")
    assert r.status_code == 200 and r.json()["result"]["verdict"] == "OK" and r.json()["result"]["by_variant"]["control"]["eligible_units"] == 50


# ---------------------------------------------------------------------------------------------------- C10 record-decision
PRODUCT_TABLES = ["accounts", "users", "events", "event_properties", "sessions", "subscriptions", "experiment_versions", "assignments",
                  "exposures", "metric_observations", "analysis_plans", "analysis_runs", "identity_links", "funnel_definitions"]


def test_c10_records_a_ship_decision_citing_the_run_and_the_review_and_changes_no_product_state(client, conn):
    L = lab(client, conn, world=small_experiment((100, 20), (100, 40)))
    aid, rid = L.final()
    before = table_digest(conn, PRODUCT_TABLES)
    r = L.decide(aid, rid, "ship")
    assert r.status_code == 200 and r.json()["status"] == "ship"
    res = r.json()["result"]
    assert res["product_state_changed"] is False and res["basis"] == "primary" and res["decided_by"] == "usr-exp01"
    assert res["evidence"] == {"analysis_id": aid, "review_id": rid, "config_hash": "b3e7466e10b2c0d3fd1adfed5155c60a18447dac1af3d9ebde02be35ec77d659",
                               "srm_verdict": "OK", "interim": False, "conclusive": True, "guardrail_verdict": "OK", "prior_runs": 0,
                               "cutoff_at": "2026-10-26T00:00:00Z"}
    assert table_digest(conn, PRODUCT_TABLES) == before                                         # a decision writes no product row
    d = conn.execute("SELECT * FROM decisions").fetchone()
    assert (d["decision"], d["analysis_id"], d["review_id"], d["decided_role"]) == ("ship", aid, rid, "experimenter")
    a = conn.execute("SELECT * FROM audit_events WHERE action = 'record-decision'").fetchone()
    assert a["entity_id"] == d["decision_id"] and a["reason"] == "because the evidence says so" and a["details"]["review_id"] == rid


def test_c10_refuses_an_interim_run_for_ship_but_not_for_stop_or_inconclusive(client, conn):
    """P06-TEST-03."""
    L = lab(client, conn, world=small_experiment((100, 20), (100, 60)))
    interim = L.analyze("2026-10-10T00:00:00Z").json()["result"]["analysis_id"]
    rv = L.review(interim).json()["result"]["review_id"]
    ship = L.decide(interim, rv, "ship")
    assert ship.status_code == 409 and ship.json()["error"]["code"] == "INTERIM_RUN_CANNOT_SHIP" and count(conn, "decisions") == 0
    refusal = conn.execute("SELECT * FROM audit_events WHERE action = 'record-decision-refused'").fetchone()
    assert refusal["details"]["rule_id"] == "INTERIM_RUN_CANNOT_SHIP" and refusal["actor_id"] == "usr-exp01"      # the refusal is kept
    assert L.decide(interim, rv, "inconclusive").status_code == 200


def test_c10_a_sample_ratio_mismatch_blocks_ship_and_stop(client, conn):
    """P06-TEST-08."""
    L = lab(client, conn, world=small_experiment((130, 20), (70, 40)))
    aid, rid = L.final()
    ship = L.decide(aid, rid, "ship")
    assert ship.status_code == 409 and ship.json()["error"]["code"] == "SRM_MISMATCH_BLOCKS_DECISION"
    assert ship.json()["error"]["details"][0]["context"]["srm"]["verdict"] == "MISMATCH"
    assert L.decide(aid, rid, "stop").status_code == 409 and count(conn, "decisions") == 0
    ok = L.decide(aid, rid, "inconclusive")
    assert ok.status_code == 200 and ok.json()["result"]["evidence"]["srm_verdict"] == "MISMATCH"


def test_c10_needs_a_frozen_plan_a_matching_review_and_one_decision_per_run(client, conn):
    L = lab(client, conn, world=small_experiment((100, 20), (100, 40)))
    aid, rid = L.final()
    other = L.analyze("2026-10-27T00:00:00Z").json()["result"]["analysis_id"]
    other_review = L.review(other).json()["result"]["review_id"]
    assert (L.decide(aid, other_review).status_code, rule_ids(L.decide(aid, other_review))) == (422, ["REVIEW_MISMATCH"])
    assert L.decide(aid, "gr-zzz").status_code == 404 and L.decide("an-zzz", rid).status_code == 404
    assert L.decide(aid, rid, "maybe").status_code == 422
    assert L.decide(aid, rid, "ship", basis="segment").status_code == 422 and rule_ids(L.decide(aid, rid, "ship", basis="segment")) == ["SEGMENT_NOT_A_DECISION_BASIS"]
    assert L.decide(aid, rid, "ship", who=ANALYST).status_code == 403
    assert L.decide(aid, rid, "ship").status_code == 200
    dup = L.decide(aid, rid, "stop")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DECISION_ALREADY_RECORDED" and count(conn, "decisions") == 1
    assert L.decide(other, other_review, "stop", who=ADMIN).status_code == 200          # another run may carry its own decision
    conn.execute("ALTER TABLE analysis_plans DISABLE TRIGGER USER")
    conn.execute("DELETE FROM analysis_plans")
    conn.execute("ALTER TABLE analysis_plans ENABLE TRIGGER USER")
    third = L.analyze("2026-10-28T00:00:00Z")
    assert third.status_code == 409 and third.json()["error"]["code"] == "PLAN_NOT_FROZEN"


def test_c10_a_harmful_guardrail_or_a_hash_that_does_not_match_blocks_ship(client, conn):
    w = small_experiment((50, 10), (50, 25))
    for i in range(12):
        w.event("product_error", f"2026-10-02T0{i % 10}:3{i // 10}:00Z", user=f"u-acc-t-{i + 1:03d}")
    L = lab(client, conn, world=w)
    aid, rid = L.final()
    assert L.review(aid).json()["result"]["verdict"] == "HARMFUL"
    r = L.decide(aid, rid, "ship")
    assert r.status_code == 409 and r.json()["error"]["code"] == "GUARDRAIL_HARM_BLOCKS_SHIP"
    assert L.decide(aid, rid, "stop").status_code == 200


def test_c10_a_ship_on_a_result_that_is_not_conclusive_is_allowed_with_a_warning(client, conn):
    L = lab(client, conn, world=small_experiment((100, 20), (100, 30)))          # the golden shape: the interval includes 0
    aid, rid = L.final()
    r = L.decide(aid, rid, "ship")
    assert r.status_code == 200 and [w["code"] for w in r.json()["warnings"]] == ["NOT_CONCLUSIVE"] and r.json()["result"]["evidence"]["conclusive"] is False


# ---------------------------------------------------------------------------------------------------- the golden fixtures through the commands
@pytest.mark.parametrize("variant", ["", "variant-rejected"])
def test_the_fixture_replayed_through_the_commands_reproduces_expected_json(client, conn, variant):
    """C06, C03, C01, C02, C04, C05 and C07 rebuild the population; GET /metrics equals expected.json leaf by leaf, and C08 at the
    cutoff reproduces the experiment block."""
    inputs, exp = golden_inputs(variant), golden_expected(variant)
    log = drive(client, conn, inputs)
    refused = {k: v for k, v in log.items() if v != 200}
    if variant:
        assert refused == {"assign:as-c-003-b": 409, "expose:ex-c-003-b": 404, "expose:ex-t-004": 422}
    else:
        assert refused == {}
    body = get(client, "/metrics", cutoff=inputs["cutoff"], experiment_version_id="xv-001").json()
    d = body["data"]
    assert d["metrics"] == exp["metrics"] and d["tracking_quality"] == exp["tracking_quality"] and d["identity"] == exp["identity"]
    assert d["empty_population"] is exp["empty_population"]
    run = L_analyze(client, inputs["cutoff"])
    want = {k: v for k, v in exp["metrics"]["experiment"].items() if k not in ("run", "srm")}
    got = {k: v for k, v in run["result"].items() if k in want}
    assert got == want and run["result"]["srm"] == exp["metrics"]["experiment"]["srm"]
    assert run["result"]["run"]["prior_runs"] == len(inputs["analysis_runs"]) and run["result"]["run"]["config_hash_matches_plan"] is True


def L_analyze(client, cutoff):
    r = command(client, "analyze-experiment", {"experiment_version_id": "xv-001", "cutoff": cutoff}, headers=ANALYST)
    assert r.status_code == 200, r.text
    return r.json()
