"""Business rules through the pure domain (contracts D-01..D-05), one test per rule, named for the requirement."""
from datetime import date, time, timedelta
from fractions import Fraction

import pytest

from serviceflow import compute_metrics, disclosures, group_metrics, run_pipeline, simulate, validate_batch
from serviceflow.events import queue_legs, replay
from serviceflow.metrics import histories, staffed_minutes
from serviceflow.simulation import holdout_report, replicate
from serviceflow.timeutil import d4, d6, local_to_utc, minutes_between, nearest_rank, parse_ts

from support_db import World, at


def run(w: World, window=None, cutoffs=None):
    return run_pipeline(w.data(), window=None if window is None else (parse_ts(at(window[0])), parse_ts(at(window[1]))),
                        cutoffs=None if cutoffs is None else [at(c) for c in cutoffs])


# --- first response ---------------------------------------------------------------------------------------------

def test_bot_ack_is_not_a_first_response():
    w = World()
    w.ticket("t-1", 0)
    w.ev("t-1", "acknowledged_bot", 0.1, actor="bot-7")
    w.serve("t-1", 20, 30)
    m = run(w).metrics
    assert m["first_response_minutes"] == {"t-1": "20.0000"}          # not 0.1 minutes
    assert m["mean_first_response_minutes"] == "20.0000"


def test_a_ticket_with_only_a_bot_ack_has_no_first_response_and_is_disclosed():
    w = World()
    w.ticket("t-1", 0)
    w.ev("t-1", "acknowledged_bot", 0.1, actor="bot-7")
    res = run(w)
    assert res.metrics["first_response_minutes"] == {} and res.metrics["sla_first_response_eligible"] == 0
    d = disclosures(res.population, (parse_ts(at(0)), parse_ts(at(180))))
    assert d["arrivals_without_human_reply"] == 1 and d["bot_events_ignored_for_first_response"] == 1


def test_bot_labelled_human_is_rejected_at_ingest_and_does_not_count():
    w = World()
    w.ticket("t-1", 0)
    w.ev("t-1", "replied_human", 1, actor="bot-9")                      # the injected defect
    w.serve("t-1", 15, 20, reply=True)
    res = run(w)
    rej = [(r["id"], r["reason_code"]) for r in res.rejected]
    assert rej == [("e-0002", "BOT_AS_HUMAN_REPLY")]
    assert res.metrics["first_response_minutes"] == {"t-1": "15.0000"}


# --- queue discipline -------------------------------------------------------------------------------------------

CFG = {"agents": 1, "service_minutes": 10, "arrivals": [0, 0, 1], "priorities": ["P2", "P2", "P1"]}


def test_fifo_within_priority_a_p1_overtakes_a_waiting_p2():
    sim = simulate({**CFG, "discipline": "fifo_within_priority"}, 1, 0, 60)
    starts = {s.demand.ticket_id: s.start for s in sim.served}
    assert (starts["t-001"], starts["t-003"], starts["t-002"]) == (0, 10, 20)   # P1 (t-003) jumps the earlier P2


def test_fifo_within_priority_never_reorders_inside_a_class():
    sim = simulate({"agents": 1, "service_minutes": 10, "arrivals": [0, 1, 2, 3], "priorities": ["P2"] * 4,
                    "discipline": "fifo_within_priority"}, 1, 0, 100)
    assert [s.start for s in sim.served] == [0, 10, 20, 30]


def test_plain_fifo_ignores_priority():
    sim = simulate({**CFG, "discipline": "fifo"}, 1, 0, 60)
    assert [s.start for s in sim.served] == [0, 10, 20]


def test_multi_server_fifo():
    sim = simulate({"agents": 2, "service_minutes": 10, "arrivals": [0, 0, 0, 0], "discipline": "fifo"}, 1, 0, 60)
    assert [s.start for s in sim.served] == [0, 0, 10, 10] and sim.final_completion == 20


# --- transfers and reopens --------------------------------------------------------------------------------------

def test_transfer_preserves_the_original_arrival():
    w = World()
    w.ticket("t-1", 0, queue="q-1")
    w.ev("t-1", "queued", 1, queue="q-1")
    w.ev("t-1", "transferred", 30, actor="sup-1", queue="q-2")
    w.serve("t-1", 45, 60, queue="q-2")
    res = run(w)
    m = res.metrics
    assert res.rejected == []
    assert m["wait_minutes"] == {"t-1": "45.0000"} and m["first_response_minutes"] == {"t-1": "45.0000"}
    assert m["resolution_minutes"] == {"t-1": "60.0000"}               # measured from the ORIGINAL arrival
    h = histories(res.population)["t-1"]
    legs = queue_legs(h)
    assert [(l["queue_id"], l["wait_minutes"]) for l in legs] == [("q-1", None), ("q-2", Fraction(15))]
    assert len(h.transfers) == 1 and h.transfers[0].from_queue == "q-1" and h.transfers[0].to_queue == "q-2"


def test_transfer_back_and_forth_never_moves_the_arrival():
    w = World()
    w.ticket("t-1", 0, queue="q-1")
    w.ev("t-1", "transferred", 10, actor="s", queue="q-2")
    w.ev("t-1", "transferred", 20, actor="s", queue="q-1")
    w.serve("t-1", 25, 30)
    h = histories(run(w).population)["t-1"]
    assert h.arrival == parse_ts(at(0)) and h.queue_id == "q-1" and len(h.transfers) == 2


def test_transfer_that_resets_the_arrival_is_rejected_with_its_dependents():
    w = World()
    w.ticket("t-1", 0)
    w.ev("t-1", "transferred", 30, actor="s", queue="q-2")
    w.d["tickets"][0]["created_at"] = at(40)                             # created_at later than the first event
    res = run(w)
    assert {(r["entity"], r["id"]): r["reason_code"] for r in res.rejected}[("tickets", "t-1")] == "TRANSFER_RESETS_ARRIVAL"
    assert {r["reason_code"] for r in res.rejected if r["entity"] == "ticket_events"} == {"TICKET_REJECTED"}
    assert res.metrics["arrival_count"] == 0


def test_reopen_is_one_customer():
    w = World()
    w.ticket("t-1", 0)
    w.serve("t-1", 5, 10)
    w.ev("t-1", "reopened", 60, actor="sup-1")
    w.serve("t-1", 70, 80)
    res = run(w, window=(0, 180), cutoffs=[30, 65, 90])
    m = res.metrics
    assert (m["arrival_count"], m["completion_count"]) == (1, 1)         # one contact, one completion
    assert m["backlog"] == {at(30): 0, at(65): 1, at(90): 0}              # open again between the reopen and the re-resolve
    assert m["resolution_minutes"] == {"t-1": "80.0000"}                  # the last cycle's resolution from the arrival
    h = histories(res.population)["t-1"]
    assert h.reopen_count == 1 and [c.prior for c in h.cycles] == [None, 0]
    d = disclosures(res.population, (parse_ts(at(0)), parse_ts(at(180))))
    assert d["reopened_tickets"] == 1 and d["reopen_events"] == 1
    assert m["handling_minutes_total"] == "15.0000"                       # 5 + 10 minutes of service in two cycles


def test_a_reopened_ticket_not_yet_resolved_is_open_and_not_a_completion():
    w = World()
    w.ticket("t-1", 0)
    w.serve("t-1", 5, 10)
    w.ev("t-1", "reopened", 60, actor="sup-1")
    m = run(w).metrics
    assert m["completion_count"] == 0 and m["backlog"][at(180)] == 1


# --- concurrency, breaks, shifts -------------------------------------------------------------------------------

def test_concurrency_is_bounded_by_the_declared_max():
    for cap, rejected in ((1, 1), (2, 0)):
        w = World(agents=("a-1",), max_concurrent=cap)
        for i, t in enumerate(("t-1", "t-2")):
            w.ticket(t, 0)
            w.serve(t, 5 + i, 20, reply=False)                           # 5-20 and 6-20 overlap
        res = run(w)
        assert len([r for r in res.rejected if r["entity"] == "tickets"]) == rejected
        if rejected:
            assert res.rejected[-1]["reason_code"] == "CONCURRENCY_EXCEEDED" and res.rejected[-1]["id"] == "t-2"


def test_a_third_concurrent_service_exceeds_a_cap_of_two():
    w = World(agents=("a-1",), max_concurrent=2)
    for i, t in enumerate(("t-1", "t-2", "t-3")):
        w.ticket(t, 0)
        w.serve(t, 5 + i, 30, reply=False)
    res = run(w)
    assert [(r["id"], r["reason_code"]) for r in res.rejected if r["entity"] == "tickets"] == [("t-3", "CONCURRENCY_EXCEEDED")]


def test_back_to_back_services_do_not_overlap():
    w = World(agents=("a-1",))
    w.ticket("t-1", 0)
    w.serve("t-1", 5, 10, reply=False)
    w.ticket("t-2", 0)
    w.serve("t-2", 10, 15, reply=False)          # starts at the very instant the first ends
    assert run(w).rejected == []


def test_break_is_not_capacity():
    w = World(agents=("a-1",))
    pop = run(w).population
    whole = (parse_ts(at(0)), parse_ts(at(480)))
    assert staffed_minutes(pop.shifts, whole) == (Fraction(450), Fraction(450))        # 480 - 30
    # a window that does not cover the whole shift deducts nothing (D-05: pro-rata is a later decision)
    assert staffed_minutes(pop.shifts, (parse_ts(at(0)), parse_ts(at(60))))[0] == 60
    m = compute_metrics(pop, whole)
    assert m["staffed_available_minutes"] == "450.0000" and m["staffed_shift_minutes_whole"] == "450.0000"


def test_dst_crossing_shift_is_measured_in_utc_minutes():
    zone = "America/New_York"
    # fall back, 2026-11-01: 22:00 Saturday to 06:00 Sunday is NINE elapsed hours (the 01:00 hour happens twice)
    s, e = local_to_utc(date(2026, 10, 31), time(22), zone), local_to_utc(date(2026, 11, 1), time(6), zone)
    assert minutes_between(s, e) == 540
    # spring forward, 2026-03-08: the same wall-clock shift is SEVEN elapsed hours (02:00 does not exist)
    s2, e2 = local_to_utc(date(2026, 3, 7), time(22), zone), local_to_utc(date(2026, 3, 8), time(6), zone)
    assert minutes_between(s2, e2) == 420
    w = World(agents=("a-1",))
    w.d["shifts"] = [{"shift_id": "sh-dst", "agent_id": "a-1", "starts_at": s.isoformat().replace("+00:00", "Z"),
                      "ends_at": e.isoformat().replace("+00:00", "Z"), "break_minutes": 30}]
    pop = run_pipeline(w.data()).population
    avail, whole = staffed_minutes(pop.shifts, (s, e))
    assert avail == whole == 510                                                   # 540 - 30, never 480 - 30 or 600 - 30


def test_shift_with_a_break_longer_than_the_shift_is_malformed():
    w = World(agents=("a-1",))
    w.d["shifts"][0]["break_minutes"] = 481
    assert [(r["id"], r["reason_code"]) for r in run(w).rejected] == [("sh-a-1", "MALFORMED_RECORD")]


# --- percentiles, SLA, open overdue ----------------------------------------------------------------------------

def test_p90_nearest_rank_n3_is_the_third_value():
    assert nearest_rank([Fraction(20), Fraction(0), Fraction(10)], Fraction(9, 10)) == 20


def test_p90_nearest_rank_n10_is_the_ninth_value_not_the_tenth():
    assert nearest_rank([Fraction(i) for i in range(10, 0, -1)], Fraction(9, 10)) == 9


def test_p90_nearest_rank_through_the_metrics():
    w = World(agents=("a-1", "a-2"))
    for i in range(1, 11):
        w.ticket(f"t-{i:02d}", 0)
        w.serve(f"t-{i:02d}", i, i + 1, agent="a-1" if i % 2 else "a-2")
    m = run(w).metrics
    assert m["p90_first_response_minutes"] == "9.0000" and m["mean_first_response_minutes"] == "5.5000"


def test_p90_is_shown_beside_the_mean_and_the_per_priority_tail():
    w = World()
    for i in range(1, 11):
        w.ticket(f"t-{i:02d}", 0, priority="P1" if i == 10 else "P3")
        w.serve(f"t-{i:02d}", i * 2 if i < 10 else 90, i * 2 + 1 if i < 10 else 91)
    res = run(w)
    groups = group_metrics(res.population, "priority", (parse_ts(at(0)), parse_ts(at(180))), [])
    assert res.metrics["p90_first_response_minutes"] == "18.0000"       # 9th of 10 sorted values
    assert res.metrics["mean_first_response_minutes"] == "18.0000"
    assert groups["P1"]["p90_first_response_minutes"] == "90.0000"       # the tail the mean and the overall P90 hide


def test_open_overdue_tickets_are_counted_and_shown_separately():
    w = World()
    w.ticket("t-1", 0)                      # never resolved, P2 target 60 minutes
    w.ticket("t-2", 150)                    # open, but only 30 minutes old at the window end
    w.ticket("t-3", 0)
    w.serve("t-3", 5, 20)
    m = run(w).metrics
    assert m["open_overdue_at_cutoff"] == 1
    assert (m["sla_resolution_eligible"], m["sla_resolution_within"], m["completion_count"]) == (1, 1, 1)
    assert m["backlog"][at(180)] == 2


def test_sla_boundaries_are_inclusive():
    w = World()
    w.ticket("t-1", 0)
    w.serve("t-1", 15, 60)                  # exactly the P2 targets: 15 min first response, 60 min resolution
    m = run(w).metrics
    assert (m["sla_first_response_within"], m["sla_resolution_within"]) == (1, 1)


def test_handling_excludes_waiting_customer_and_idle_time():
    w = World()
    w.ticket("t-1", 0)
    w.ev("t-1", "service_started", 10, agent="a-1")
    w.ev("t-1", "replied_human", 10, agent="a-1")
    w.ev("t-1", "paused", 20, agent="a-1")
    w.ev("t-1", "resumed", 50, agent="a-1")
    w.ev("t-1", "resolved", 60, agent="a-1")
    res = run(w)
    assert res.metrics["handling_minutes_total"] == "20.0000"             # 10-20 and 50-60
    assert histories(res.population)["t-1"].cycles[0].pauses == [(parse_ts(at(20)), parse_ts(at(50)))]


def test_occupancy_is_handling_over_staffed_time_and_null_without_staff():
    w = World(agents=("a-1",))
    w.ticket("t-1", 0)
    w.serve("t-1", 0, 60)
    m = run(w, window=(0, 480)).metrics
    assert m["agent_occupancy"] == d6(Fraction(60, 450))
    w.d["shifts"] = []
    assert run(w).metrics["agent_occupancy"] is None


def test_abandonment_only_counts_channels_that_can_abandon():
    w = World()
    w.ticket("t-1", 0, channel="chat")
    w.ev("t-1", "abandoned", 5, actor=None)
    w.ticket("t-2", 0, channel="chat")
    w.serve("t-2", 1, 2)
    w.ticket("t-3", 0, channel="email")
    assert run(w).metrics["abandonment_rate"] == "0.500000"
    only_email = World()
    only_email.ticket("t-1", 0, channel="email")
    assert run(only_email).metrics["abandonment_rate"] is None


def test_late_arrival_is_preserved_with_its_own_time():
    w = World()
    w.ticket("t-1", 0)
    w.ev("t-1", "resolved", 30, agent="a-1")                             # arrives in the batch BEFORE the start
    w.ev("t-1", "service_started", 10, agent="a-1")
    w.ev("t-1", "replied_human", 10, agent="a-1")
    m = run(w).metrics
    assert m["resolution_minutes"] == {"t-1": "30.0000"} and m["handling_minutes_total"] == "20.0000"


def test_exact_rounding_is_half_up_on_rationals():
    assert d4(Fraction(1, 3)) == "0.3333" and d4(Fraction(5, 3)) == "1.6667"
    assert d4(Fraction(1, 20000)) == "0.0001"                             # an exact tie rounds up
    assert d6(Fraction(2, 3)) == "0.666667"


# --- CSAT ------------------------------------------------------------------------------------------------------

def test_csat_nonresponse_is_disclosed_beside_the_score():
    w = World()
    for i in range(1, 6):
        w.ticket(f"t-{i}", 0)
        w.serve(f"t-{i}", i * 6, i * 6 + 5)
        w.d["surveys"].append({"survey_id": f"sv-{i}", "ticket_id": f"t-{i}", "invited_at": at(6),
                               "response_at": at(10) if i == 1 else None, "score": 5 if i == 1 else None})
    res = run(w)
    assert res.metrics["csat"] == "1.000000" and res.metrics["survey_response_rate"] == "0.200000"
    d = disclosures(res.population, (parse_ts(at(0)), parse_ts(at(180))))["csat"]
    assert (d["invited"], d["valid_responses"], d["nonresponse"]) == (5, 1, 4)


# --- simulation ------------------------------------------------------------------------------------------------

RANDOM = {"agents": 2, "service_minutes": 6, "service": "exponential", "arrival_rate_per_hour": 20,
          "priority_mix": {"P1": 1, "P2": 2, "P3": 2}, "discipline": "fifo_within_priority"}


def test_warm_up_is_excluded_from_every_statistic():
    cfg = {"agents": 1, "service_minutes": 10, "arrivals": [0, 0, 0, 30], "discipline": "fifo"}
    full = simulate(cfg, 1, 0, 100)
    warm = simulate(cfg, 1, 15, 100)
    assert full.golden()["waits_minutes"] == ["0.0000", "10.0000", "20.0000", "0.0000"]
    assert warm.golden()["waits_minutes"] == ["0.0000"]                    # only the ticket arriving after minute 15
    assert warm.warmup_ticket_ids == ["t-001", "t-002", "t-003"] and warm.statistics()["warmup_excluded"] == 3
    assert warm.golden()["final_completion_minute"] == "40.0000"
    assert [e["event_at"] for e in warm.events] == [e["event_at"] for e in full.events]    # same path, other statistics


def test_same_seed_same_path_and_a_different_seed_differs():
    a, b = simulate(RANDOM, 42, 10, 240), simulate(RANDOM, 42, 10, 240)
    assert a.events == b.events and a.golden() == b.golden() and len(a.events) > 10
    assert simulate(RANDOM, 43, 10, 240).events != a.events


def test_common_random_numbers_policies_see_the_same_demand():
    one = simulate({**RANDOM, "agents": 1}, 7, 0, 240)
    two = simulate({**RANDOM, "agents": 3, "discipline": "fifo"}, 7, 0, 240)
    assert [(s.demand.arrival, s.demand.priority, s.demand.service) for s in one.served] == \
           [(s.demand.arrival, s.demand.priority, s.demand.service) for s in two.served]
    assert two.mean_wait < one.mean_wait


def test_replications_use_consecutive_seeds():
    runs = replicate(RANDOM, 5, 3, 0, 120)
    assert [r.seed for r in runs] == [5, 6, 7] and runs[0].events == simulate(RANDOM, 5, 0, 120).events


def test_horizon_censors_waiting_tickets():
    sim = simulate({"agents": 1, "service_minutes": 10, "arrivals": [0, 0, 0], "discipline": "fifo"}, 1, 0, 15)
    assert sim.censored_ticket_ids == ["t-003"] and sim.golden()["waits_minutes"] == ["0.0000", "10.0000"]


@pytest.mark.parametrize("cfg", [{"service_minutes": 10}, {"service_minutes": 0, "arrivals": [0]},
                                 {"service_minutes": 5, "arrivals": [0], "arrival_rate_per_hour": 3},
                                 {"service_minutes": 5, "arrivals": [0], "agents": 0},
                                 {"service_minutes": 5, "arrivals": [-1]}, {"service_minutes": 5, "arrivals": [0], "x": 1},
                                 {"service_minutes": 5, "arrivals": [0], "discipline": "lifo"}])
def test_invalid_configs_are_refused(cfg):
    with pytest.raises(ValueError):
        simulate(cfg, 1, 0, 60)


def test_holdout_intensity_change_is_reported_not_hidden():
    start = parse_ts("2026-07-06T00:00:00Z")      # a Monday
    arrivals = []
    for week in range(12):                         # 10 tickets a day in weeks 1-8, 12 a day (+20 %) in weeks 9-12
        for day in range(7):
            n = 12 if week >= 8 else 10
            arrivals += [start + timedelta(weeks=week, days=day, hours=h) for h in range(n)]
    train = (start, start + timedelta(weeks=8))
    hold = (train[1], start + timedelta(weeks=12))
    rep = holdout_report(arrivals, train, hold)
    assert rep["estimated_on"] == "training window only"
    assert (rep["train_rate_per_hour"], rep["holdout_rate_per_hour"]) == ("0.416667", "0.500000")
    assert rep["intensity_changed"] is True and rep["relative_change"] == "0.200000"
    flat = [a for a in arrivals if a < train[1]]                        # no holdout surge: nothing to report
    flat += [a + timedelta(weeks=8) for a in flat[: 70 * 4]]
    same = holdout_report(flat, train, hold)
    assert same["intensity_changed"] is False and same["relative_change"] == "0.000000"


def test_replay_cycles_link_the_prior_cycle():
    w = World()
    w.ticket("t-1", 0)
    w.serve("t-1", 1, 5)
    w.ev("t-1", "reopened", 10, actor="s")
    w.serve("t-1", 12, 15)
    w.ev("t-1", "reopened", 20, actor="s")
    pop = run(w).population
    h = replay(pop.tickets[0], pop.ticket_events)
    assert [(c.index, c.prior) for c in h.cycles] == [(0, None), (1, 0), (2, 1)] and h.final_resolution is None


def test_ingest_unknown_reference_duplicate_and_malformed():
    w = World()
    w.ticket("t-1", 0)
    w.d["ticket_events"].append(dict(w.d["ticket_events"][0]))                            # DUPLICATE_ID
    w.d["ticket_events"].append({"event_id": "e-x", "ticket_id": "t-404", "event_type": "created",
                                 "occurred_at": at(0), "actor_id": None, "queue_id": "q-1", "agent_id": None})
    w.d["ticket_events"].append({"event_id": "e-y", "ticket_id": "t-1", "event_type": "teleported",
                                 "occurred_at": at(0)})
    w.d["tickets"].append({"ticket_id": "t-2", "customer_id": "c-nobody", "queue_id": "q-1", "priority": "P2",
                           "created_at": at(0), "channel": "email"})
    res = validate_batch(w.data())
    got = sorted((r.entity, r.id, r.reason_code) for r in res.rejected)
    assert got == [("ticket_events", "e-0001", "DUPLICATE_ID"), ("ticket_events", "e-x", "UNKNOWN_REFERENCE"),
                   ("ticket_events", "e-y", "MALFORMED_RECORD"), ("tickets", "t-2", "UNKNOWN_REFERENCE")]
    assert res.counts["ticket_events"] == {"accepted": 1, "rejected": 3}
