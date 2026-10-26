"""Adversarial scenarios named for the P04-TEST requirement each one defends (one injected defect per test, end to end
through the API and the database where the rule is stored)."""
from datetime import date, time, timedelta

import psycopg
import pytest

from api.app import PREFIX
from serviceflow import disclosures, run_pipeline, simulate
from serviceflow.events import replay
from serviceflow.metrics import histories, staffed_minutes
from serviceflow.simulation import holdout_report
from serviceflow.timeutil import local_to_utc, minutes_between, parse_ts

from support_db import (ANALYST, SUPERVISOR, World, at, client, command, conn, count, db_url, events_of, get, load, rule_ids,  # noqa: F401
                        seeded)


def ingest(client, w: World, keys=("tickets", "ticket_events", "surveys")):
    d = w.data()
    return command(client, "ingest-ticket-events", {k: d[k] for k in keys}, headers=ANALYST)


def base(**kw) -> World:
    """Reference data in the database; the test then ingests its own tickets through C01."""
    return World(**kw)


@pytest.fixture
def ref(client, conn):
    """A database holding only reference data (queues, agents, skills, shifts, SLA), no tickets."""
    w = base(window=(0, 480))
    load(conn, w)
    return w


def metrics(client, lo=0, hi=480, **extra):
    return get(client, "/metrics", **{"from": at(lo), "to": at(hi)}, **extra).json()


# --- P04-TEST-01: a bot acknowledgement labelled as a human reply -----------------------------------------------

def test_p04_test_01_bot_ack_labelled_human_is_not_a_first_response(client, ref, conn):
    w = base(window=(0, 480))
    w.ticket("t-1", 0)
    w.ev("t-1", "acknowledged_bot", 0.1, actor="bot-1")
    w.ev("t-1", "replied_human", 0.2, actor="bot-1")                       # the injected defect: a bot typed as human
    w.serve("t-1", 25, 40, agent="a-1")
    r = ingest(client, w)
    assert r.status_code == 200
    rec = {(x["entity"], x["reason_code"]) for x in r.json()["result"]["rejected_records"]}
    assert rec == {("ticket_events", "BOT_AS_HUMAN_REPLY")}
    m = metrics(client)["data"]["metrics"]
    assert m["first_response_minutes"] == {"t-1": "25.0000"}              # the real human, never 0.2 minutes
    with pytest.raises(psycopg.errors.CheckViolation):                    # and the database refuses it on its own
        conn.execute("INSERT INTO ticket_events (event_id, ticket_id, event_type, occurred_at, actor_id) "
                     "VALUES ('e-raw', 't-1', 'replied_human', %s, 'bot-3')", (at(1),))


# --- P04-TEST-02: a reopen recorded as a new customer -----------------------------------------------------------

def test_p04_test_02_a_reopen_is_one_customer_contact(client, ref, conn):
    w = base(window=(0, 480))
    w.ticket("t-1", 0)
    w.serve("t-1", 5, 10)
    ingest(client, w)
    r = command(client, "reopen-ticket", {"ticket_id": "t-1", "occurred_at": at(60)})
    assert r.status_code == 200 and r.json()["result"]["prior_cycle"] == 0
    assert command(client, "assign-queue", {"ticket_id": "t-1", "queue_id": "q-1", "occurred_at": at(61)}).status_code == 200
    assert command(client, "start-service", {"ticket_id": "t-1", "agent_id": "a-1", "occurred_at": at(70)}).status_code == 200
    assert command(client, "resolve-ticket", {"ticket_id": "t-1", "occurred_at": at(80)}).status_code == 200
    d = metrics(client)["data"]
    assert (d["metrics"]["arrival_count"], d["metrics"]["completion_count"]) == (1, 1)    # not 2 customers
    assert d["disclosures"]["reopened_tickets"] == 1 and d["disclosures"]["reopen_events"] == 1
    assert d["metrics"]["resolution_minutes"] == {"t-1": "80.0000"}
    assert count(conn, "tickets") == 1


# --- P04-TEST-03: an agent assigned a skill-incompatible ticket -------------------------------------------------

def test_p04_test_03_an_incompatible_skill_assignment_is_refused_everywhere(client, ref, conn):
    conn.execute("INSERT INTO skills VALUES ('s-2', 'Rare', NULL, true, now())")
    conn.execute("INSERT INTO queues VALUES ('q-3', 'Rare queue', 'fifo', 'cal-1', true)")
    conn.execute("INSERT INTO queue_skills VALUES ('q-3', 's-2')")
    conn.execute("INSERT INTO agent_skills VALUES ('as-r', 'a-2', 's-2', 5, '2026-01-01T00:00Z')")   # only a-2 holds it
    w = base(window=(0, 480))
    w.ticket("t-1", 0, queue="q-3")
    w.ev("t-1", "queued", 1, queue="q-3")
    w.ev("t-1", "service_started", 10, agent="a-1", queue="q-3")           # a-1 lacks s-2: injected defect
    r = ingest(client, w)
    assert {(x["entity"], x["id"]): x["reason_code"] for x in r.json()["result"]["rejected_records"]}[("tickets", "t-1")] == "AGENT_NOT_QUALIFIED"
    w2 = base(window=(0, 480))
    w2.ticket("t-2", 0, queue="q-3")
    w2.ev("t-2", "queued", 1, queue="q-3")
    assert ingest(client, w2).json()["status"] == "loaded"
    r = command(client, "start-service", {"ticket_id": "t-2", "agent_id": "a-1", "occurred_at": at(20)})
    assert r.status_code == 422 and rule_ids(r) == ["AGENT_NOT_QUALIFIED"]
    assert r.json()["error"]["details"][0]["context"]["missing_skills"] == ["s-2"]
    assert command(client, "start-service", {"ticket_id": "t-2", "agent_id": "a-2", "occurred_at": at(20)}).status_code == 200


# --- P04-TEST-04: two simultaneous services for one agent -------------------------------------------------------

def test_p04_test_04_two_simultaneous_services_for_one_agent(client, ref, conn):
    w = base(window=(0, 480))
    for t in ("t-1", "t-2"):
        w.ticket(t, 0)
        w.ev(t, "queued", 1, queue="q-1")
    w.ev("t-1", "service_started", 10, agent="a-1", queue="q-1")
    w.ev("t-1", "resolved", 30, agent="a-1", queue="q-1")
    w.ev("t-2", "service_started", 20, agent="a-1", queue="q-1")           # overlaps t-1 for a-1 (cap 1): defect
    w.ev("t-2", "resolved", 25, agent="a-1", queue="q-1")
    r = ingest(client, w)
    assert {(x["entity"], x["id"]): x["reason_code"] for x in r.json()["result"]["rejected_records"]}[("tickets", "t-2")] == "CONCURRENCY_EXCEEDED"
    # the rule has no trigger (see 0002_constraints.sql): the application is the guard, serialised per agent
    assert conn.execute("SELECT count(*) AS n FROM tickets WHERE ticket_id = 't-2'").fetchone()["n"] == 0
    conn.execute("UPDATE agents SET max_concurrent = 2 WHERE agent_id = 'a-1'")
    w2 = World(window=(0, 480), prefix="f")
    w2.ticket("t-2", 0)
    w2.ev("t-2", "queued", 1, queue="q-1")
    w2.ev("t-2", "service_started", 20, agent="a-1", queue="q-1")
    w2.ev("t-2", "resolved", 25, agent="a-1", queue="q-1")
    assert ingest(client, w2).json()["status"] == "loaded"                  # within the declared max_concurrent of 2
    w3 = World(window=(0, 480), prefix="g")
    w3.ticket("t-3", 0)
    w3.ev("t-3", "queued", 1, queue="q-1")
    w3.ev("t-3", "service_started", 22, agent="a-1", queue="q-1")           # a third at once, beyond the declared 2
    got = {(x["entity"], x["id"]): x["reason_code"] for x in ingest(client, w3).json()["result"]["rejected_records"]}
    assert got[("tickets", "t-3")] == "CONCURRENCY_EXCEEDED"


# --- P04-TEST-05: a shift with a break counted as available -----------------------------------------------------

def test_p04_test_05_a_break_is_not_capacity(client, ref, conn):
    d = metrics(client, 0, 480)["data"]["metrics"]
    assert d["staffed_shift_minutes_whole"] == "900.0000"                    # two agents x (480 - 30)
    assert d["staffed_available_minutes"] == "900.0000"                      # window covers both whole shifts: break deducted
    assert metrics(client, 0, 60)["data"]["metrics"]["staffed_available_minutes"] == "120.0000"   # D-05: no pro-rata deduction
    # a recorded break blocks service: it is not capacity
    conn.execute("INSERT INTO shift_breaks VALUES ('b-1', 'sh-a-1', 'a-1', %s, %s)", (at(100), at(130)))
    w = base(window=(0, 480))
    w.ticket("t-1", 0)
    w.ev("t-1", "queued", 1, queue="q-1")
    ingest(client, w)
    r = command(client, "start-service", {"ticket_id": "t-1", "agent_id": "a-1", "occurred_at": at(110)})
    assert r.status_code == 422 and rule_ids(r) == ["AGENT_ON_BREAK"]


# --- P04-TEST-06: open overdue tickets dropped from SLA compliance ----------------------------------------------

def test_p04_test_06_open_overdue_tickets_are_counted_not_dropped(client, ref):
    w = base(window=(0, 480))
    w.ticket("t-open", 0)                                                   # still open after 480 min, target 60
    w.ticket("t-ok", 0)
    w.serve("t-ok", 5, 30)
    w.ticket("t-late", 0)
    w.serve("t-late", 20, 200, agent="a-2")
    ingest(client, w)
    m = metrics(client)["data"]
    mm = m["metrics"]
    assert mm["open_overdue_at_cutoff"] == 1                                 # shown separately
    assert (mm["sla_resolution_eligible"], mm["sla_resolution_within"]) == (2, 1)
    assert mm["sla_resolution_compliance"] == "0.500000"
    assert m["disclosures"]["open_overdue_at_window_end"] == 1 and mm["backlog"][at(480)] == 1


# --- P04-TEST-07: a daylight-saving shift -----------------------------------------------------------------------

def test_p04_test_07_dst_shift_is_measured_in_utc_minutes(client, ref, conn):
    zone = "America/New_York"
    s = local_to_utc(date(2026, 11, 1) - timedelta(days=1), time(22), zone)       # Sat 22:00 local
    e = local_to_utc(date(2026, 11, 1), time(6), zone)                              # Sun 06:00 local, after the fall-back
    assert minutes_between(s, e) == 540
    z = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    conn.execute("INSERT INTO shifts VALUES ('sh-dst', 'a-1', %s, %s, 30)", (z(s), z(e)))
    m = get(client, "/metrics", **{"from": z(s), "to": z(e)}).json()["data"]["metrics"]
    # shift sh-dst: 540 - 30; the two day shifts of the reference data fall outside this window
    assert m["staffed_available_minutes"] == "510.0000"
    wrong = 8 * 60 - 30                                                             # what a wall-clock calculation would say
    assert m["staffed_available_minutes"] != f"{wrong}.0000"
    with pytest.raises(psycopg.errors.CheckViolation):                              # a shift cannot end before it starts
        conn.execute("INSERT INTO shifts VALUES ('sh-bad', 'a-1', %s, %s, 0)", (z(e), z(s)))


# --- P04-TEST-08: a transfer that resets the arrival ------------------------------------------------------------

def test_p04_test_08_a_transfer_never_resets_the_arrival(client, ref, conn):
    w = base(window=(0, 480))
    w.ticket("t-1", 0)
    w.ev("t-1", "queued", 1, queue="q-1")
    w.ev("t-1", "transferred", 30, actor="sup", queue="q-2")
    w.d["tickets"][0]["created_at"] = at(30)                               # defect: arrival overwritten by the transfer
    r = ingest(client, w)
    got = {(x["entity"], x["id"]): x["reason_code"] for x in r.json()["result"]["rejected_records"]}
    assert got[("tickets", "t-1")] == "TRANSFER_RESETS_ARRIVAL" and got[("ticket_events", "e-0002")] == "TICKET_REJECTED"
    w2 = base(window=(0, 480))
    w2.ticket("t-2", 0)
    w2.ev("t-2", "queued", 1, queue="q-1")
    ingest(client, w2)
    for i, q in enumerate(("q-2", "q-1", "q-2")):
        assert command(client, "transfer-ticket", {"ticket_id": "t-2", "to_queue_id": q, "occurred_at": at(10 + i)}).status_code == 200
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="ARRIVAL_IMMUTABLE"):
        conn.execute("UPDATE tickets SET created_at = %s WHERE ticket_id = 't-2'", (at(40),))
    assert command(client, "start-service", {"ticket_id": "t-2", "agent_id": "a-1", "occurred_at": at(50), "reply": True}).status_code == 200
    m = metrics(client)["data"]["metrics"]
    assert m["wait_minutes"] == {"t-2": "50.0000"} and m["first_response_minutes"] == {"t-2": "50.0000"}   # from the original arrival


# --- P04-TEST-09: a simulation run that included its warm-up ----------------------------------------------------

def test_p04_test_09_warmup_is_excluded_from_every_statistic(client, db_url):
    cfg = {"simulation_id": "sim-w", "seed": 3, "warmup_minutes": 60, "horizon_minutes": 480, "policy_version": "p",
           "config": {"agents": 1, "service_minutes": 5, "service": "exponential", "arrival_rate_per_hour": 10}}
    warm = command(client, "run-simulation", cfg).json()["result"]
    cold = command(client, "run-simulation", {**cfg, "simulation_id": "sim-c", "warmup_minutes": 0}).json()["result"]
    assert warm["statistics"]["warmup_excluded"] > 0 and cold["statistics"]["warmup_excluded"] == 0
    assert len(warm["waits_minutes"]) == len(cold["waits_minutes"]) - warm["statistics"]["warmup_excluded"]
    assert warm["events"][0]["event_at"] == cold["events"][0]["event_at"]            # same path ...
    assert warm["mean_wait_minutes"] != cold["mean_wait_minutes"]                      # ... different statistic
    ids = set(warm["statistics"]["warmup_ticket_ids"])
    first_counted = next(t for t in (f"t-{i:03d}" for i in range(1, 99)) if t not in ids)
    assert all(t < first_counted for t in ids)


# --- P04-TEST-10: averages shown beside the P90 and the per-priority tail ---------------------------------------

def test_p04_test_10_p90_and_the_priority_tail_sit_beside_the_mean(client, ref):
    w = base(window=(0, 480))
    for i in range(1, 11):
        w.ticket(f"t-{i:02d}", 0, priority="P1" if i == 10 else "P3")
        w.serve(f"t-{i:02d}", i if i < 10 else 150, i + 1 if i < 10 else 151, agent="a-1" if i % 2 else "a-2")
    ingest(client, w)
    m = metrics(client)["data"]["metrics"]
    assert m["mean_first_response_minutes"] == "19.5000" and m["p90_first_response_minutes"] == "9.0000"   # the tail hides here
    groups = metrics(client, group_by="priority")["data"]["groups"]
    assert groups["P1"]["p90_first_response_minutes"] == "150.0000" and groups["P3"]["p90_first_response_minutes"] == "9.0000"
    assert groups["P1"]["sla_first_response_compliance"] == "0.000000"              # P1 target 5 minutes: the whole tail breaches


# --- P04-TEST-11: survey nonresponse skew (a disclosure, not a correction) --------------------------------------

def test_p04_test_11_csat_nonresponse_is_disclosed(client, ref):
    w = base(window=(0, 480))
    for i in range(1, 9):
        w.ticket(f"t-{i}", 0)
        w.serve(f"t-{i}", i * 10, i * 10 + 5, agent="a-1")
        w.d["surveys"].append({"survey_id": f"sv-{i}", "ticket_id": f"t-{i}", "invited_at": at(i * 10 + 6),
                               "response_at": at(i * 10 + 20) if i == 1 else None, "score": 5 if i == 1 else None})
    r = ingest(client, w)
    assert r.json()["status"] == "loaded"
    d = metrics(client)["data"]
    assert d["metrics"]["csat"] == "1.000000" and d["metrics"]["survey_response_rate"] == "0.125000"
    assert d["metrics"]["survey_invitation_rate"] == "1.000000"
    assert d["disclosures"]["csat"]["nonresponse"] == 7 and "nonresponse" in d["disclosures"]["csat"]["note"]
    assert d["disclosures"]["csat"]["valid_responses"] == 1                          # 100 % of one response, shown with its base


# --- P04-TEST-12: holdout intensity change ----------------------------------------------------------------------

def test_p04_test_12_holdout_intensity_change_is_reported(client, db_url):
    start = parse_ts("2026-07-06T00:00:00Z")
    arrivals = []
    for week in range(12):
        n = 12 if week >= 8 else 10                                                  # +20 % designed in the holdout
        for day in range(7):
            arrivals += [start + timedelta(weeks=week, days=day, hours=h) for h in range(n)]
    train = (start, start + timedelta(weeks=8))
    hold = (train[1], start + timedelta(weeks=12))
    rep = holdout_report(arrivals, train, hold)
    assert rep["intensity_changed"] is True and rep["relative_change"] == "0.200000" and rep["estimated_on"] == "training window only"
    assert "differs from the training estimate" in rep["note"]
    # a simulation built on the training rate is labelled an estimate wherever it appears
    cfg = {"simulation_id": "sim-h", "seed": 1, "horizon_minutes": 240, "policy_version": "p",
           "config": {"agents": 2, "service_minutes": 5, "arrival_rate_per_hour": float(rep["train_rate_per_hour"]) * 24}}
    r = command(client, "run-simulation", cfg).json()["result"]
    assert r["label"] == "simulated estimate, not an observed result" and r["statistics"]["label"] == r["label"]
