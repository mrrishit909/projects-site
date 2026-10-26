"""Commands through the HTTP API: valid, malformed, unknown resource, state conflict, idempotency, 401 and 403
(docs/api-contract.md)."""
import concurrent.futures as cf
import threading

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import commands
from api.app import PREFIX, create_app

from support_db import (ADMIN, ANALYST, SUPERVISOR, World, at, client, command, conn, count, db_url, events_of,  # noqa: F401
                        golden_expected, golden_inputs, load, rule_ids, seeded)


def api_world() -> World:
    """t-new (just created), t-q and t-q2 (queued in q-1), t-in (a-2 has served it since minute 10), t-res (resolved)."""
    w = World(window=(0, 480))
    w.ticket("t-new", 0)
    for t in ("t-q", "t-q2"):
        w.ticket(t, 0)
        w.ev(t, "queued", 1, queue="q-1")
    w.ticket("t-in", 0)
    w.ev("t-in", "queued", 1, queue="q-1")
    w.ev("t-in", "service_started", 10, agent="a-2", queue="q-1")
    w.ticket("t-res", 0)
    w.ev("t-res", "queued", 1, queue="q-1")
    w.serve("t-res", 5, 30, agent="a-1")
    return w


@pytest.fixture
def api(client, conn):
    load(conn, api_world())
    return client


def start(api, ticket="t-q", agent="a-1", minute=60, **extra):
    return command(api, "start-service", {"ticket_id": ticket, "agent_id": agent, "occurred_at": at(minute), **extra})


# --- C01 ingest-ticket-events -----------------------------------------------------------------------------------

def ingest(api, headers=None, **rows):
    """C01 as an analyst by default; a batch that touches an EXISTING ticket needs ``headers=SUPERVISOR`` (R4-04)."""
    return command(api, "ingest-ticket-events", rows, headers=ANALYST if headers is None else headers)


def new_ticket(tid, minute=100):
    return ({"ticket_id": tid, "customer_id": "c-1", "queue_id": "q-1", "priority": "P2", "created_at": at(minute),
             "channel": "email"},
            {"event_id": f"e-{tid}-1", "ticket_id": tid, "event_type": "created", "occurred_at": at(minute),
             "actor_id": None, "queue_id": "q-1", "agent_id": None})


def test_ingest_valid_batch(api, conn):
    t, e = new_ticket("t-100")
    r = ingest(api, tickets=[t], ticket_events=[e])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "loaded" and body["command_id"].startswith("cmd-")
    assert body["result"]["inserted"]["tickets"] == 1 and body["result"]["rejected_records"] == []
    assert body["result"]["counts"]["ticket_events"] == {"accepted": 1, "rejected": 0}
    assert count(conn, "tickets") == 6 and count(conn, "raw_batches") == 1
    assert conn.execute("SELECT action, actor_id FROM audit_events").fetchone() == {"action": "ingest-ticket-events", "actor_id": "ana-1"}


def test_ingest_partial_keeps_good_rows_and_records_the_rejected(api, conn):
    t, e = new_ticket("t-100")
    bad = dict(e, event_id="e-bad", event_type="teleported")
    r = ingest(api, tickets=[t], ticket_events=[e, bad])
    body = r.json()
    assert r.status_code == 200 and body["status"] == "partial"
    assert body["result"]["rejected_records"] == [{"entity": "ticket_events", "id": "e-bad", "reason_code": "MALFORMED_RECORD"}]
    assert body["warnings"][0]["code"] == "MALFORMED_RECORD"
    assert count(conn, "ticket_events") == 6 * 0 + 1 + conn.execute("SELECT count(*) AS n FROM ticket_events WHERE ticket_id <> 't-100'").fetchone()["n"]
    assert conn.execute("SELECT reason_code, raw_row->>'event_id' AS id FROM rejected_records").fetchone() == \
        {"reason_code": "MALFORMED_RECORD", "id": "e-bad"}


def test_ingest_preserves_late_arrivals_with_their_own_time(api, conn):
    t, e = new_ticket("t-100", 100)
    late = {"event_id": "e-late", "ticket_id": "t-100", "event_type": "queued", "occurred_at": at(101),
            "actor_id": None, "queue_id": "q-1", "agent_id": None}
    r1 = ingest(api, tickets=[t], ticket_events=[e])
    r2 = ingest(api, headers=SUPERVISOR, ticket_events=[dict(late, event_id="e-later", occurred_at=at(130)), late])    # out of order
    assert r1.status_code == r2.status_code == 200
    rows = conn.execute("SELECT event_id, to_char(occurred_at, 'HH24:MI') AS t FROM ticket_events WHERE ticket_id = 't-100' "
                        "ORDER BY event_seq").fetchall()
    assert [(r["event_id"], r["t"]) for r in rows] == [("e-t-100-1", "10:40"), ("e-later", "11:10"), ("e-late", "10:41")]


def test_ingest_duplicate_event_id_is_rejected_not_overwritten(api, conn):
    dup = {"event_id": "e-0001", "ticket_id": "t-new", "event_type": "queued", "occurred_at": at(5), "queue_id": "q-1"}
    r = ingest(api, headers=SUPERVISOR, ticket_events=[dup])
    assert r.json()["result"]["rejected_records"] == [{"entity": "ticket_events", "id": "e-0001", "reason_code": "DUPLICATE_ID"}]
    assert conn.execute("SELECT event_type FROM ticket_events WHERE event_id = 'e-0001'").fetchone()["event_type"] == "created"


def test_ingest_bot_as_human_reply_is_rejected(api):
    ev = {"event_id": "e-bot", "ticket_id": "t-new", "event_type": "replied_human", "occurred_at": at(3),
          "actor_id": "bot-1", "queue_id": "q-1", "agent_id": None}
    assert ingest(api, headers=SUPERVISOR, ticket_events=[ev]).json()["result"]["rejected_records"][0]["reason_code"] == "BOT_AS_HUMAN_REPLY"


def test_ingest_agent_not_qualified_rejects_the_whole_ticket(api, conn):
    conn.execute("INSERT INTO agents VALUES ('a-9', 'Nine', 'UTC', 'full_time', true, 1)")
    t, e = new_ticket("t-100")
    svc = {"event_id": "e-svc", "ticket_id": "t-100", "event_type": "service_started", "occurred_at": at(110),
           "actor_id": "a-9", "queue_id": "q-1", "agent_id": "a-9"}
    r = ingest(api, tickets=[t], ticket_events=[e, svc])
    got = {(x["entity"], x["id"]): x["reason_code"] for x in r.json()["result"]["rejected_records"]}
    assert got == {("tickets", "t-100"): "AGENT_NOT_QUALIFIED", ("ticket_events", "e-t-100-1"): "TICKET_REJECTED",
                   ("ticket_events", "e-svc"): "TICKET_REJECTED"}
    assert conn.execute("SELECT count(*) AS n FROM tickets WHERE ticket_id = 't-100'").fetchone()["n"] == 0


def test_ingest_concurrency_is_checked_against_what_is_already_stored(api, conn):
    t, e = new_ticket("t-100", 100)
    svc = {"event_id": "e-svc", "ticket_id": "t-100", "event_type": "service_started", "occurred_at": at(120),
           "actor_id": "a-2", "queue_id": "q-1", "agent_id": "a-2"}        # a-2 has served t-in since minute 10
    r = ingest(api, tickets=[t], ticket_events=[e, svc])
    assert {(x["entity"], x["id"]): x["reason_code"] for x in r.json()["result"]["rejected_records"]}[("tickets", "t-100")] == "CONCURRENCY_EXCEEDED"
    ok = ingest(api, tickets=[dict(t, ticket_id="t-101")], ticket_events=[dict(e, event_id="e-101", ticket_id="t-101"),
                dict(svc, event_id="e-svc2", ticket_id="t-101", agent_id="a-1", actor_id="a-1")])
    assert ok.json()["status"] == "loaded"


def test_ingest_against_a_trusted_ticket_rejects_only_the_new_events(api, conn):
    """A new service_started for a stored ticket by an unqualified agent: the stored rows stay, the new ones go."""
    conn.execute("INSERT INTO agents VALUES ('a-9', 'Nine', 'UTC', 'full_time', true, 1)")
    svc = {"event_id": "e-svc", "ticket_id": "t-q", "event_type": "service_started", "occurred_at": at(70),
           "actor_id": "a-9", "queue_id": "q-1", "agent_id": "a-9"}
    rep = {"event_id": "e-rep", "ticket_id": "t-q", "event_type": "replied_human", "occurred_at": at(70),
           "actor_id": "a-9", "queue_id": "q-1", "agent_id": "a-9"}
    got = {(x["id"]): x["reason_code"] for x in ingest(api, headers=SUPERVISOR, ticket_events=[svc, rep]).json()["result"]["rejected_records"]}
    assert got == {"e-svc": "AGENT_NOT_QUALIFIED", "e-rep": "TICKET_REJECTED"}
    assert conn.execute("SELECT count(*) AS n FROM tickets WHERE ticket_id = 't-q'").fetchone()["n"] == 1


def test_ingest_transfer_moves_the_current_queue_but_not_the_arrival(api, conn):
    ev = {"event_id": "e-x", "ticket_id": "t-q", "event_type": "transferred", "occurred_at": at(20), "actor_id": "s", "queue_id": "q-2"}
    assert ingest(api, headers=SUPERVISOR, ticket_events=[ev]).json()["status"] == "loaded"
    row = conn.execute("SELECT queue_id, to_char(created_at, 'HH24:MI') AS c FROM tickets WHERE ticket_id = 't-q'").fetchone()
    assert row == {"queue_id": "q-2", "c": "09:00"}


@pytest.mark.parametrize("body,rule,path", [
    ({"tickets": "nope"}, "FIELD_INVALID", "input.tickets"),
    ({"surprise": []}, "FIELD_UNEXPECTED", "input.surprise"),
    ({"tickets": [1, 2]}, "FIELD_INVALID", "input.tickets.0"),
])
def test_ingest_malformed_envelope_is_422(api, body, rule, path):
    r = ingest(api, **body)
    assert r.status_code == 422 and rule in rule_ids(r) and r.json()["error"]["details"][0]["path"] == path


# --- C02 assign-queue -------------------------------------------------------------------------------------------

def test_assign_queue_valid(api, conn):
    r = command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "q-2", "occurred_at": at(10)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued" and body["result"]["state"] == "queued" and body["result"]["eligible_agents"] == ["a-1", "a-2"]
    assert events_of(conn, "t-new") == [("created", "09:00"), ("queued", "09:10")]
    assert conn.execute("SELECT queue_id FROM tickets WHERE ticket_id = 't-new'").fetchone()["queue_id"] == "q-2"
    assert conn.execute("SELECT action, actor_id FROM audit_events").fetchone() == {"action": "assign-queue", "actor_id": "sup-1"}


def test_assign_queue_skill_mismatch_is_422(api, conn):
    conn.execute("INSERT INTO skills VALUES ('s-2', 'Rare', NULL, true, now())")
    conn.execute("INSERT INTO queues VALUES ('q-3', 'Rare queue', 'fifo', 'cal-1', true)")
    conn.execute("INSERT INTO queue_skills VALUES ('q-3', 's-2')")
    r = command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "q-3", "occurred_at": at(10)})
    assert r.status_code == 422 and rule_ids(r) == ["QUEUE_SKILL_MISMATCH"]
    assert r.json()["error"]["details"][0]["context"] == {"required_skills": ["s-2"]}
    assert events_of(conn, "t-new") == [("created", "09:00")]                          # nothing written
    conn.execute("INSERT INTO agent_skills VALUES ('as-rare', 'a-1', 's-2', 3, '2026-07-07T00:00Z')")   # effective LATER
    assert command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "q-3", "occurred_at": at(10)}).status_code == 422
    conn.execute("UPDATE agent_skills SET effective_from = '2026-01-01T00:00Z' WHERE agent_skill_id = 'as-rare'")
    assert command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "q-3", "occurred_at": at(10)}).status_code == 200


def test_assign_queue_errors(api, conn):
    assert command(api, "assign-queue", {"ticket_id": "nope", "queue_id": "q-1"}).status_code == 404
    r = command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "nope"})
    assert r.status_code == 404 and rule_ids(r) == ["QUEUE_UNKNOWN"]
    conn.execute("UPDATE queues SET active = false WHERE queue_id = 'q-2'")
    r = command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "q-2", "occurred_at": at(10)})
    assert r.status_code == 422 and rule_ids(r) == ["QUEUE_INACTIVE"]
    r = command(api, "assign-queue", {"ticket_id": "t-q", "queue_id": "q-1", "occurred_at": at(10)})   # already queued
    assert r.status_code == 409 and rule_ids(r) == ["INVALID_STATE"]
    assert r.json()["error"]["details"][0]["context"]["state"] == "queued"
    r = command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "q-1", "occurred_at": at(-5)})
    assert r.status_code == 422 and rule_ids(r) == ["EVENT_BEFORE_LAST"]


# --- C03 start-service ------------------------------------------------------------------------------------------

def test_start_service_valid(api, conn):
    r = start(api, reply=True)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "started" and r.json()["result"]["state"] == "in_service" and len(r.json()["result"]["event_ids"]) == 2
    assert events_of(conn, "t-q") == [("created", "09:00"), ("queued", "09:01"), ("service_started", "10:00"), ("replied_human", "10:00")]
    assert conn.execute("SELECT agent_id, actor_id, queue_id FROM ticket_events WHERE event_type = 'service_started' AND ticket_id = 't-q'").fetchone() \
        == {"agent_id": "a-1", "actor_id": "a-1", "queue_id": "q-1"}


def test_start_service_agent_must_be_in_shift(api):
    r = start(api, minute=500)                                                         # 17:20, the shift ended at 17:00
    assert r.status_code == 422 and rule_ids(r) == ["AGENT_NOT_IN_SHIFT"]
    r = start(api, minute=480)                                                         # the end instant itself is out
    assert rule_ids(r) == ["AGENT_NOT_IN_SHIFT"]


def test_start_service_agent_on_break_is_refused_break_is_not_capacity(api, conn):
    conn.execute("INSERT INTO shift_breaks VALUES ('b-1', 'sh-a-1', 'a-1', %s, %s)", (at(55), at(85)))
    r = start(api, minute=60)
    assert r.status_code == 422 and rule_ids(r) == ["AGENT_ON_BREAK"]
    assert start(api, minute=85).status_code == 200                                    # the break is [start, end)


def test_start_service_agent_must_be_qualified(api, conn):
    conn.execute("INSERT INTO agents VALUES ('a-9', 'Nine', 'UTC', 'full_time', true, 1)")
    conn.execute("INSERT INTO shifts VALUES ('sh-9', 'a-9', %s, %s, 30)", (at(0), at(480)))
    r = start(api, agent="a-9")
    assert r.status_code == 422 and rule_ids(r) == ["AGENT_NOT_QUALIFIED"]
    assert r.json()["error"]["details"][0]["context"] == {"queue_id": "q-1", "missing_skills": ["s-1"]}


def test_start_service_respects_max_concurrent(api, conn):
    r = start(api, agent="a-2")                                                        # a-2 already serves t-in
    assert r.status_code == 422 and rule_ids(r) == ["CONCURRENCY_EXCEEDED"]
    assert r.json()["error"]["details"][0]["context"] == {"max_concurrent": 1, "in_service_at_that_instant": 1}
    conn.execute("UPDATE agents SET max_concurrent = 2 WHERE agent_id = 'a-2'")
    assert start(api, agent="a-2").status_code == 200
    r = start(api, ticket="t-q2", agent="a-2", minute=61)                              # a third at once
    assert r.status_code == 422 and rule_ids(r) == ["CONCURRENCY_EXCEEDED"]


def test_start_service_errors(api, conn):
    assert start(api, ticket="nope").status_code == 404
    r = start(api, agent="nope")
    assert r.status_code == 404 and rule_ids(r) == ["AGENT_UNKNOWN"]
    r = start(api, ticket="t-new")
    assert r.status_code == 409 and rule_ids(r) == ["INVALID_STATE"]
    r = start(api, ticket="t-in", agent="a-1")
    assert r.status_code == 409
    conn.execute("UPDATE agents SET active = false WHERE agent_id = 'a-1'")
    r = start(api, minute=60)
    assert r.status_code == 422 and rule_ids(r) == ["AGENT_INACTIVE"]


# --- C04 transfer-ticket ----------------------------------------------------------------------------------------

def test_transfer_preserves_the_original_arrival(api, conn):
    before = conn.execute("SELECT created_at FROM tickets WHERE ticket_id = 't-q'").fetchone()["created_at"]
    r = command(api, "transfer-ticket", {"ticket_id": "t-q", "to_queue_id": "q-2", "occurred_at": at(30)})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["arrival_preserved"] is True and res["created_at"] == at(0) and res["from_queue_id"] == "q-1"
    assert conn.execute("SELECT created_at, queue_id FROM tickets WHERE ticket_id = 't-q'").fetchone() == {"created_at": before, "queue_id": "q-2"}


def test_transfer_back_and_forth_never_changes_created_at(api, conn):
    for i, q in enumerate(("q-2", "q-1", "q-2", "q-1")):
        assert command(api, "transfer-ticket", {"ticket_id": "t-q", "to_queue_id": q, "occurred_at": at(10 + i)}).status_code == 200
    assert conn.execute("SELECT to_char(created_at, 'HH24:MI') AS c FROM tickets WHERE ticket_id = 't-q'").fetchone()["c"] == "09:00"
    assert [e for e, _ in events_of(conn, "t-q")].count("transferred") == 4
    # and the metrics still measure from the original arrival
    m = api.get(f"{PREFIX}/metrics", params={"from": at(0), "to": at(480)}).json()["data"]["metrics"]
    assert m["arrival_count"] == 5


def test_transfer_of_an_in_service_ticket_closes_the_interval(api, conn):
    assert command(api, "transfer-ticket", {"ticket_id": "t-in", "to_queue_id": "q-2", "occurred_at": at(40)}).status_code == 200
    # a-2 is free again: starting another ticket for them now succeeds
    assert start(api, agent="a-2", minute=60).status_code == 200


def test_transfer_errors(api, conn):
    r = command(api, "transfer-ticket", {"ticket_id": "t-q", "to_queue_id": "q-1", "occurred_at": at(30)})
    assert r.status_code == 422 and rule_ids(r) == ["SAME_QUEUE"]
    r = command(api, "transfer-ticket", {"ticket_id": "t-res", "to_queue_id": "q-2", "occurred_at": at(60)})
    assert r.status_code == 409 and rule_ids(r) == ["INVALID_STATE"]
    r = command(api, "transfer-ticket", {"ticket_id": "t-new", "to_queue_id": "q-2", "occurred_at": at(60)})
    assert r.status_code == 409
    assert command(api, "transfer-ticket", {"ticket_id": "t-q", "to_queue_id": "nope", "occurred_at": at(30)}).status_code == 404
    conn.execute("INSERT INTO skills VALUES ('s-2', 'Rare', NULL, true, now())")
    conn.execute("INSERT INTO queues VALUES ('q-3', 'Rare queue', 'fifo', 'cal-1', true)")
    conn.execute("INSERT INTO queue_skills VALUES ('q-3', 's-2')")
    r = command(api, "transfer-ticket", {"ticket_id": "t-q", "to_queue_id": "q-3", "occurred_at": at(30)})
    assert r.status_code == 422 and rule_ids(r) == ["QUEUE_SKILL_MISMATCH"]


# --- C05 pause-work / resume-work -------------------------------------------------------------------------------

def test_pause_and_resume(api, conn):
    r = command(api, "pause-work", {"ticket_id": "t-in", "occurred_at": at(40)})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["state"] == "waiting_customer" and res["handling_clock"] == "stopped" and res["sla_policy"]["resolution_minutes"] == 60
    assert start(api, agent="a-2", minute=45).status_code == 200                      # the paused ticket no longer holds a-2
    r = command(api, "resume-work", {"ticket_id": "t-in", "occurred_at": at(50)})              # a-2 is busy again
    assert r.status_code == 422 and rule_ids(r) == ["CONCURRENCY_EXCEEDED"]
    r = command(api, "resolve-ticket", {"ticket_id": "t-q", "occurred_at": at(56)})
    assert r.status_code == 200 and r.json()["result"]["state"] == "resolved"
    r = command(api, "resume-work", {"ticket_id": "t-in", "occurred_at": at(57)})
    assert r.status_code == 200 and r.json()["result"]["state"] == "in_service"
    assert events_of(conn, "t-in")[-2:] == [("paused", "09:40"), ("resumed", "09:57")]


def test_pause_needs_an_sla_policy_that_differentiates(api, conn):
    conn.execute("DELETE FROM sla_policies WHERE priority = 'P2'")
    r = command(api, "pause-work", {"ticket_id": "t-in", "occurred_at": at(40)})
    assert r.status_code == 422 and rule_ids(r) == ["SLA_POLICY_MISSING"]


def test_pause_resume_state_errors(api):
    for name, tid in (("pause-work", "t-q"), ("pause-work", "t-res"), ("resume-work", "t-in"), ("resolve-ticket", "t-q")):
        r = command(api, name, {"ticket_id": tid, "occurred_at": at(60)})
        assert r.status_code == 409 and rule_ids(r) == ["INVALID_STATE"], (name, tid)
    assert command(api, "pause-work", {"ticket_id": "nope"}).status_code == 404


# --- C06 reopen-ticket ------------------------------------------------------------------------------------------

def test_reopen_links_the_prior_cycle_and_counts_once(api, conn):
    r = command(api, "reopen-ticket", {"ticket_id": "t-res", "occurred_at": at(100)})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert (res["prior_cycle"], res["cycle"], res["reopen_count"], res["customer_contacts"]) == (0, 1, 1, 1)
    assert res["prior_resolved_at"] == at(30) and res["state"] == "reopened"
    d = api.get(f"{PREFIX}/metrics", params={"from": at(0), "to": at(480)}).json()["data"]
    assert d["metrics"]["arrival_count"] == 5 and d["disclosures"]["reopened_tickets"] == 1      # still one customer contact
    assert d["metrics"]["completion_count"] == 0                                                  # open again, not a completion
    # reopened -> queued -> in service -> resolved: the second cycle is linked, not a new ticket
    assert command(api, "assign-queue", {"ticket_id": "t-res", "queue_id": "q-1", "occurred_at": at(101)}).status_code == 200
    assert start(api, ticket="t-res", minute=110).status_code == 200
    assert command(api, "resolve-ticket", {"ticket_id": "t-res", "occurred_at": at(130)}).json()["result"]["cycle"] == 1
    assert conn.execute("SELECT count(*) AS n FROM tickets WHERE ticket_id = 't-res'").fetchone()["n"] == 1


def test_reopen_only_a_resolved_ticket(api):
    for tid in ("t-new", "t-q", "t-in"):
        r = command(api, "reopen-ticket", {"ticket_id": tid, "occurred_at": at(100)})
        assert r.status_code == 409 and rule_ids(r) == ["INVALID_STATE"]
    assert command(api, "reopen-ticket", {"ticket_id": "t-res", "occurred_at": at(100)}).status_code == 200
    assert command(api, "reopen-ticket", {"ticket_id": "t-res", "occurred_at": at(101)}).status_code == 409   # already reopened
    assert command(api, "reopen-ticket", {"ticket_id": "nope"}).status_code == 404


# --- C07 / C10 are not implemented ------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["build-shift-scenario", "export-recommendation"])
def test_extension_commands_are_501(api, name):
    r = command(api, name, {"anything": 1})
    assert r.status_code == 501 and r.json()["error"]["code"] == "NOT_IMPLEMENTED" and rule_ids(r) == ["NOT_IMPLEMENTED"]


def test_unknown_command_is_404(api):
    r = command(api, "teleport-ticket", {})
    assert r.status_code == 404 and rule_ids(r) == ["UNSUPPORTED_ACTION"]


# --- C08 run-simulation -----------------------------------------------------------------------------------------

def golden_run(sim_id="sim-001"):
    run = golden_inputs()["simulation_runs"][0]
    return {**{k: run[k] for k in ("seed", "warmup_minutes", "policy_version", "horizon_minutes", "config")}, "simulation_id": sim_id}


def test_golden_simulation_through_the_api(client, db_url, conn):
    r = command(client, "run-simulation", golden_run(), headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    exp = golden_expected()["simulation"]
    for k in exp:
        assert res[k] == exp[k], k
    rows = conn.execute("SELECT simulation_event_id, simulation_id, ticket_id, event_type, event_at::text AS event_at "
                        "FROM simulation_events ORDER BY simulation_event_id").fetchall()
    assert [dict(r) for r in rows] == exp["events"]
    assert conn.execute("SELECT seed, warmup_minutes::text AS w FROM simulation_runs").fetchone() == {"seed": 1, "w": "0.0000"}
    assert res["label"].startswith("simulated estimate")


def test_same_seed_gives_identical_events_under_another_id(client, db_url):
    cfg = {"simulation_id": "sim-a", "seed": 99, "warmup_minutes": 10, "horizon_minutes": 240, "policy_version": "p1",
           "config": {"agents": 2, "service_minutes": 6, "service": "exponential", "arrival_rate_per_hour": 20,
                      "priority_mix": {"P1": 1, "P2": 2}, "discipline": "fifo_within_priority"}}
    a = command(client, "run-simulation", cfg).json()["result"]
    b = command(client, "run-simulation", {**cfg, "simulation_id": "sim-b"}).json()["result"]
    strip = lambda ev: [(e["simulation_event_id"], e["ticket_id"], e["event_type"], e["event_at"]) for e in ev]  # noqa: E731
    assert strip(a["events"]) == strip(b["events"]) and len(a["events"]) > 10
    assert a["waits_minutes"] == b["waits_minutes"] and a["mean_wait_minutes"] == b["mean_wait_minutes"]
    c = command(client, "run-simulation", {**cfg, "simulation_id": "sim-c", "seed": 100}).json()["result"]
    assert strip(c["events"]) != strip(a["events"])


def test_simulation_warmup_is_excluded_and_flagged(client, db_url, conn):
    cfg = {"simulation_id": "sim-w", "seed": 1, "warmup_minutes": 15, "horizon_minutes": 100, "policy_version": "p",
           "config": {"agents": 1, "service_minutes": 10, "arrivals": [0, 0, 0, 30], "discipline": "fifo"}}
    r = command(client, "run-simulation", cfg).json()["result"]
    assert r["waits_minutes"] == ["0.0000"] and r["statistics"]["warmup_excluded"] == 3
    flags = conn.execute("SELECT ticket_id, bool_or(warmup) AS w FROM simulation_events GROUP BY ticket_id ORDER BY ticket_id").fetchall()
    assert [(f["ticket_id"], f["w"]) for f in flags] == [("t-001", True), ("t-002", True), ("t-003", True), ("t-004", False)]


def test_simulation_replications_report_count_and_interval(client, db_url):
    cfg = {"simulation_id": "sim-r", "seed": 5, "horizon_minutes": 240, "policy_version": "p", "replications": 8,
           "config": {"agents": 1, "service_minutes": 5, "service": "exponential", "arrival_rate_per_hour": 9}}
    r = command(client, "run-simulation", cfg).json()["result"]
    rep = r["replications"]
    assert rep["count"] == 8 and rep["seeds"] == list(range(5, 13)) and rep["mean_wait_minutes"]["n"] == 8
    assert rep["mean_wait_minutes"]["ci95_half_width"] is not None


def test_simulation_errors(client, db_url):
    ok = golden_run()
    assert command(client, "run-simulation", ok).status_code == 200
    r = command(client, "run-simulation", ok)
    assert r.status_code == 409 and r.json()["error"]["code"] == "SIMULATION_EXISTS"
    bad = {**golden_run("sim-x"), "config": {"agents": 0, "service_minutes": 10, "arrivals": [0]}}
    r = command(client, "run-simulation", bad)
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_CONFIG"] and r.json()["error"]["details"][0]["path"] == "input.config"
    for patch, path in (({"horizon_minutes": 0}, "input.horizon_minutes"), ({"seed": "one"}, "input.seed"),
                        ({"warmup_minutes": -1}, "input.warmup_minutes"), ({"replications": 0}, "input.replications")):
        r = command(client, "run-simulation", {**golden_run("sim-y"), **patch})
        assert r.status_code == 422 and r.json()["error"]["details"][0]["path"] == path


# --- C09 compare-policies ---------------------------------------------------------------------------------------

def test_compare_policies_same_seed_same_demand(client, db_url):
    base = {"agents": 1, "service_minutes": 5, "service": "exponential", "arrival_rate_per_hour": 8}
    body = {"seed": 4, "replications": 6, "horizon_minutes": 240, "baseline": base, "proposal": {**base, "agents": 2}}
    r = command(client, "compare-policies", body, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["replications"] == 6 and res["same_demand_paths"] is True and res["proposal_better"] is True
    assert res["difference_mean_wait_minutes"]["n"] == 6 and res["label"].startswith("simulated estimate")
    again = command(client, "compare-policies", body).json()["result"]
    assert again == res                                                              # deterministic
    r = command(client, "compare-policies", {**body, "proposal": {"agents": 2}})
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_CONFIG"]


# --- identity and roles -----------------------------------------------------------------------------------------

def test_missing_actor_is_401_and_bad_role_is_403(api):
    body = {"request_id": "r", "dataset_version": "d", "idempotency_key": "k1", "input": {"ticket_id": "t-q", "queue_id": "q-1"}}
    r = api.post(f"{PREFIX}/commands/assign-queue", json=body)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED" and rule_ids(r) == ["ACTOR_REQUIRED"]
    r = api.post(f"{PREFIX}/commands/assign-queue", json=body, headers={"X-Actor-Id": " "})
    assert r.status_code == 401
    r = api.post(f"{PREFIX}/commands/assign-queue", json=body, headers={"X-Actor-Id": "x", "X-Actor-Role": "ops"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    r = api.post(f"{PREFIX}/commands/assign-queue", json=body, headers={"X-Actor-Id": "x"})
    assert r.status_code == 403
    r = api.post(f"{PREFIX}/commands/build-shift-scenario", json=body)
    assert r.status_code == 401


def test_an_analyst_cannot_change_ticket_state_but_may_ingest_and_simulate(api, conn):
    for name, inp in (("assign-queue", {"ticket_id": "t-new", "queue_id": "q-1"}), ("start-service", {"ticket_id": "t-q", "agent_id": "a-1"}),
                      ("transfer-ticket", {"ticket_id": "t-q", "to_queue_id": "q-2"}), ("pause-work", {"ticket_id": "t-in"}),
                      ("resume-work", {"ticket_id": "t-in"}), ("reopen-ticket", {"ticket_id": "t-res"}),
                      ("resolve-ticket", {"ticket_id": "t-in"})):
        r = command(api, name, inp, headers=ANALYST)
        assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"], name
    assert count(conn, "command_results") == 0 and count(conn, "audit_events") == 0
    assert command(api, "run-simulation", golden_run("sim-q"), headers=ANALYST).status_code == 200
    assert command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "q-1", "occurred_at": at(10)}, headers=ADMIN).status_code == 200


# --- idempotency ------------------------------------------------------------------------------------------------

def test_replay_returns_the_stored_response_and_writes_nothing(api, conn):
    inp = {"ticket_id": "t-q", "agent_id": "a-1", "occurred_at": at(60)}
    first = command(api, "start-service", inp, key="k-replay")
    again = command(api, "start-service", inp, key="k-replay")
    assert first.status_code == again.status_code == 200 and again.headers["Idempotent-Replay"] == "true"
    assert first.json() == again.json() and "Idempotent-Replay" not in first.headers
    assert [e for e, _ in events_of(conn, "t-q")].count("service_started") == 1 and count(conn, "audit_events") == 1


def test_same_key_different_payload_is_409(api):
    command(api, "start-service", {"ticket_id": "t-q", "agent_id": "a-1", "occurred_at": at(60)}, key="k-pay")
    r = command(api, "start-service", {"ticket_id": "t-q", "agent_id": "a-1", "occurred_at": at(61)}, key="k-pay")
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED" and rule_ids(r) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]


def test_same_key_from_another_actor_is_409(api):
    inp = {"ticket_id": "t-q", "agent_id": "a-1", "occurred_at": at(60)}
    command(api, "start-service", inp, key="k-act")
    r = command(api, "start-service", inp, key="k-act", headers=ADMIN)
    assert r.status_code == 409 and rule_ids(r) == ["IDEMPOTENCY_ACTOR_MISMATCH"]


def test_idempotency_instants_are_normalised(api):
    a = command(api, "start-service", {"ticket_id": "t-q", "agent_id": "a-1", "occurred_at": "2026-07-06T10:00:00Z"}, key="k-z")
    b = command(api, "start-service", {"ticket_id": "t-q", "agent_id": "a-1", "occurred_at": "2026-07-06T10:00:00+00:00"}, key="k-z")
    c = command(api, "start-service", {"ticket_id": "t-q", "agent_id": "a-1", "occurred_at": "2026-07-06T11:00:00+01:00"}, key="k-z")
    assert a.status_code == b.status_code == c.status_code == 200 and b.headers["Idempotent-Replay"] == c.headers["Idempotent-Replay"] == "true"


def test_invalid_idempotency_key_and_envelope(api):
    r = command(api, "assign-queue", {"ticket_id": "t-new", "queue_id": "q-1"}, key="bad key!")
    assert r.status_code == 422 and "IDEMPOTENCY_KEY_INVALID" in rule_ids(r)
    r = api.post(f"{PREFIX}/commands/assign-queue", json={"input": {}}, headers=SUPERVISOR)
    assert r.status_code == 422 and set(rule_ids(r)) == {"FIELD_REQUIRED"}
    r = api.post(f"{PREFIX}/commands/assign-queue", content="{not json", headers={**SUPERVISOR, "content-type": "application/json"})
    assert r.status_code == 422 and rule_ids(r) == ["BODY_INVALID_JSON"]


@pytest.mark.parametrize("body,rule,path", [
    ({"queue_id": "q-1"}, "FIELD_REQUIRED", "input.ticket_id"),
    ({"ticket_id": "t-new", "queue_id": "q-1", "surprise": 1}, "FIELD_UNEXPECTED", "input.surprise"),
    ({"ticket_id": 7, "queue_id": "q-1"}, "FIELD_INVALID", "input.ticket_id"),
    ({"ticket_id": "t-new", "queue_id": "q-1", "occurred_at": "yesterday"}, "TIMESTAMP_INVALID", "input.occurred_at"),
    ({"ticket_id": "t-new", "queue_id": "q-1", "occurred_at": "2026-07-06T09:00:00"}, "TIMESTAMP_INVALID", "input.occurred_at"),
])
def test_malformed_input_is_422_with_path_and_rule(api, body, rule, path):
    r = command(api, "assign-queue", body)
    assert r.status_code == 422
    d = r.json()["error"]["details"][0]
    assert (d["rule_id"], d["path"]) == (rule, path)


def test_request_id_is_echoed_on_errors(api):
    r = command(api, "assign-queue", {"ticket_id": "nope", "queue_id": "q-1"}, request_id="req-mine")
    assert r.json()["request_id"] == "req-mine"


# --- atomicity, lock order, concurrency -------------------------------------------------------------------------

def test_a_failed_command_leaves_no_trace(api, conn):
    snap = {t: count(conn, t) for t in ("tickets", "ticket_events", "audit_events", "command_results")}
    assert command(api, "start-service", {"ticket_id": "t-q", "agent_id": "a-2", "occurred_at": at(60)}).status_code == 422
    assert snap == {t: count(conn, t) for t in snap}


def test_d08_every_command_locks_the_ticket_before_the_agent(api, monkeypatch):
    order: list[str] = []
    real_t, real_a = commands._lock_tickets, commands._lock_agents
    monkeypatch.setattr(commands, "_lock_tickets", lambda *a, **k: (order.append("ticket"), real_t(*a, **k))[1])
    monkeypatch.setattr(commands, "_lock_agents", lambda *a, **k: (order.append("agent"), real_a(*a, **k))[1])
    start(api, ticket="t-q", agent="a-1", minute=60)
    command(api, "pause-work", {"ticket_id": "t-in", "occurred_at": at(40)})
    command(api, "resume-work", {"ticket_id": "t-in", "occurred_at": at(50)})
    ingest(api, tickets=[new_ticket("t-100")[0]], ticket_events=[new_ticket("t-100")[1]])
    assert order == ["ticket", "agent", "ticket", "ticket", "agent", "ticket", "agent"]


def test_a_deadlock_is_retried_then_409_never_500(api, monkeypatch):
    calls = {"n": 0}
    real = commands._execute_once

    def always(*a, **k):
        calls["n"] += 1
        raise psycopg.errors.DeadlockDetected("deadlock detected")
    monkeypatch.setattr(commands, "_execute_once", always)
    monkeypatch.setattr(commands.time, "sleep", lambda s: None)
    r = command(api, "pause-work", {"ticket_id": "t-in", "occurred_at": at(40)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONCURRENT_UPDATE" and calls["n"] == 3

    calls["n"] = 0

    def once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.errors.SerializationFailure("could not serialize access")
        return real(*a, **k)
    monkeypatch.setattr(commands, "_execute_once", once)
    r = command(api, "pause-work", {"ticket_id": "t-in", "occurred_at": at(40)})
    assert r.status_code == 200 and calls["n"] == 2


def test_two_simultaneous_starts_for_one_agent_exactly_one_wins(api, db_url):
    """Concurrency is serialised by the agent row lock: with max_concurrent 1 only one of two racing starts succeeds."""
    wins = []
    for round_ in range(6):
        a, b = f"t-r{round_}a", f"t-r{round_}b"
        for t in (a, b):
            tk, ev = new_ticket(t, 100)
            q = {"event_id": f"q-{t}", "ticket_id": t, "event_type": "queued", "occurred_at": at(101), "actor_id": None,
                 "queue_id": "q-1", "agent_id": None}
            assert ingest(api, tickets=[tk], ticket_events=[ev, q]).json()["status"] == "loaded"
        bar = threading.Barrier(2)

        def go(t):
            bar.wait()
            with TestClient(create_app(), raise_server_exceptions=False) as c:
                return command(c, "start-service", {"ticket_id": t, "agent_id": "a-1", "occurred_at": at(200 + round_ * 10)})
        with cf.ThreadPoolExecutor(2) as ex:
            codes = sorted(f.result().status_code for f in [ex.submit(go, a), ex.submit(go, b)])
        wins.append(codes)
        # clear the winner before the next round: resolve whichever ticket got service
        for t in (a, b):
            command(api, "resolve-ticket", {"ticket_id": t, "occurred_at": at(205 + round_ * 10)})
    assert all(c == [200, 422] for c in wins), wins
