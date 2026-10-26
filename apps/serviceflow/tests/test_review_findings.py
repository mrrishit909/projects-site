"""Regression tests for the independent review A-031 (findings R4-01 .. R4-18, decisions in docs/contracts.md D-09).

Each test is named for its finding. The pure-domain tests need no database; the API tests run against DATABASE_URL and
skip without it. The TypeScript twins of the domain tests live in web/scripts/review-check.ts; SQL agreement for R4-01,
R4-15 and the ingest-dependent findings is in tests/test_sql_reference.py.
"""
import hashlib
import json
from pathlib import Path

import pytest

from serviceflow import run_pipeline, validate_batch
from serviceflow.metrics import compute_metrics, disclosures
from serviceflow.simulation import compare_policies, mean_ci95, replication_report
from serviceflow.timeutil import parse_ts
from fractions import Fraction

from support_db import (ADMIN, ANALYST, SUPERVISOR, World, at, client, command, conn, count, db_url, get, load,  # noqa: F401
                        seeded)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "public" / "data"


def reasons(res) -> dict[tuple[str, str], str]:
    return {(r.entity, r.id): r.reason_code for r in res.ingest.rejected}


# --- R4-02: concurrency is resolved to a fixed point -----------------------------------------------------------------

def concurrency_cascade() -> World:
    """t-1 (a-1 0..30) beats t-2 (a-1 10..40). t-A (a-1 50..100, then a-2 resume 150..170) and t-C (a-1 60..70) clash on
    a-1; t-A is later rejected because its a-2 resume overlaps t-B (a-2 120..160), so t-C only clashed with a ticket that
    is not accepted: 'earlier start wins' and 'a rejected ticket occupies nobody' accept it."""
    w = World(window=(0, 180))
    for tid in ("t-1", "t-2", "t-A", "t-C", "t-B"):
        w.ticket(tid, 0)
    w.serve("t-1", 0, 30)
    w.serve("t-2", 10, 40)
    w.ev("t-A", "service_started", 50, agent="a-1")
    w.ev("t-A", "replied_human", 50, agent="a-1")
    w.ev("t-A", "paused", 100, agent="a-1")
    w.ev("t-A", "resumed", 150, agent="a-2")
    w.ev("t-A", "resolved", 170, agent="a-2")
    w.serve("t-C", 60, 70)
    w.serve("t-B", 120, 160, agent="a-2")
    return w


def test_R4_02_a_ticket_rejected_for_a_clash_with_a_later_rejected_ticket_is_accepted():
    res = run_pipeline(concurrency_cascade().data())
    got = {k: v for k, v in reasons(res).items() if k[0] == "tickets"}
    assert got == {("tickets", "t-2"): "CONCURRENCY_EXCEEDED", ("tickets", "t-A"): "CONCURRENCY_EXCEEDED"}
    assert res.metrics["arrival_count"] == 3          # t-1, t-C, t-B (the reviewer's hand count; was 2)


def test_R4_02_the_earlier_start_still_wins_without_a_cascade():
    w = World(window=(0, 180))
    for tid in ("t-1", "t-2"):
        w.ticket(tid, 0)
    w.serve("t-1", 0, 30)
    w.serve("t-2", 10, 40)
    assert {k: v for k, v in reasons(run_pipeline(w.data())).items() if k[0] == "tickets"} == \
        {("tickets", "t-2"): "CONCURRENCY_EXCEEDED"}


def test_R4_02_the_published_snapshot_keeps_its_70_rejections():
    inputs = {"contract_version": 1, "window_start": "2026-07-06T00:00:00Z", "window_end": "2026-09-28T00:00:00Z",
              "backlog_cutoffs": ["2026-09-28T00:00:00Z"], "abandonable_channels": ["chat", "phone"]}
    manifest = json.loads((DATA / "manifest.json").read_text())
    for name in manifest["row_counts"]:
        if name != "shift_breaks":
            inputs[name] = json.loads((DATA / f"{name}.json").read_text())["rows"]
    res = run_pipeline(inputs)
    assert len(res.ingest.rejected) == 70
    expected = {(r["entity"], r["id"]): r["reason_code"] for i in json.loads(
        (ROOT / "data" / "injection-manifest.json").read_text())["injections"] for r in i.get("expected_rejections", [])}
    got = reasons(res)
    assert all(got[k] == v for k, v in expected.items()) and len(expected) == 70
    assert "SERVICE_OUTSIDE_SHIFT" not in got.values() and "RESUME_BEFORE_SERVICE" not in got.values()


# --- R4-03: an agent starts service only when available ---------------------------------------------------------------

def test_R4_03_ingest_rejects_service_outside_every_shift():
    w = World(window=(0, 700))
    w.ticket("t-late", 485)                    # the shift is minute 0..480
    w.serve("t-late", 490, 520)
    w.ticket("t-ok", 100)
    w.serve("t-ok", 110, 120)
    res = run_pipeline(w.data())
    assert reasons(res)[("tickets", "t-late")] == "SERVICE_OUTSIDE_SHIFT"
    assert all(v == "TICKET_REJECTED" for k, v in reasons(res).items() if k[0] != "tickets")
    assert res.metrics["arrival_count"] == 1 and res.metrics["handling_minutes_total"] == "10.0000"


@pytest.mark.parametrize("start,ok", [(0, True), (479, True), (480, False), (-1, False)])
def test_R4_03_the_shift_is_half_open(start, ok):
    w = World(window=(-10, 700))
    w.ticket("t-1", start - 1 if start > 0 else -5)
    w.serve("t-1", start, start + 5)
    got = reasons(run_pipeline(w.data()))
    assert (("tickets", "t-1") not in got) is ok


def test_R4_03_a_resume_outside_a_shift_rejects_the_ticket():
    w = World(window=(0, 700))
    w.ticket("t-1", 0)
    w.ev("t-1", "service_started", 400, agent="a-1")
    w.ev("t-1", "replied_human", 400, agent="a-1")
    w.ev("t-1", "paused", 470, agent="a-1")
    w.ev("t-1", "resumed", 490, agent="a-1")
    w.ev("t-1", "resolved", 500, agent="a-1")
    assert reasons(run_pipeline(w.data()))[("tickets", "t-1")] == "SERVICE_OUTSIDE_SHIFT"


def test_R4_03_an_agent_with_no_shift_at_all_is_unavailable():
    w = World(window=(0, 180))
    w.d["shifts"] = [s for s in w.d["shifts"] if s["agent_id"] != "a-1"]
    w.ticket("t-1", 0)
    w.serve("t-1", 10, 20)
    assert reasons(run_pipeline(w.data()))[("tickets", "t-1")] == "SERVICE_OUTSIDE_SHIFT"


def api_world() -> World:
    w = World(window=(0, 700))
    w.ticket("t-1", 0)
    w.ev("t-1", "queued", 0, queue="q-1", actor="sup")
    w.ev("t-1", "service_started", 10, agent="a-1", queue="q-1")
    w.ev("t-1", "replied_human", 10, agent="a-1", queue="q-1")
    w.ev("t-1", "paused", 20, agent="a-1", queue="q-1")
    return w


def test_R4_03_resume_work_off_shift_is_422(client, conn):
    load(conn, api_world())
    r = command(client, "resume-work", {"ticket_id": "t-1", "occurred_at": at(500)})
    assert r.status_code == 422 and "AGENT_NOT_IN_SHIFT" in [d["rule_id"] for d in r.json()["error"]["details"]]
    assert conn.execute("SELECT count(*) AS n FROM ticket_events WHERE ticket_id = 't-1' AND event_type = 'resumed'").fetchone()["n"] == 0


def test_R4_03_resume_work_inside_a_recorded_break_is_422_and_after_it_is_allowed(client, conn):
    load(conn, api_world())
    conn.execute("INSERT INTO shift_breaks (break_id, shift_id, agent_id, starts_at, ends_at) VALUES ('br-1', 'sh-a-1', 'a-1', %s, %s)",
                 (at(100), at(130)))
    r = command(client, "resume-work", {"ticket_id": "t-1", "occurred_at": at(110)})
    assert r.status_code == 422 and "AGENT_ON_BREAK" in [d["rule_id"] for d in r.json()["error"]["details"]]
    assert command(client, "resume-work", {"ticket_id": "t-1", "occurred_at": at(130)}).status_code == 200


def test_R4_03_breaks_are_flagged_not_rejected(conn, client):
    """Breaks are not an ingest entity (D-05 keeps the break rule for the staffed-time metric): a service that opens
    inside a recorded break is a warning on the metrics read."""
    w = World(window=(0, 480))
    w.ticket("t-1", 0)
    w.serve("t-1", 110, 120)
    load(conn, w)
    conn.execute("INSERT INTO shift_breaks (break_id, shift_id, agent_id, starts_at, ends_at) VALUES ('br-1', 'sh-a-1', 'a-1', %s, %s)",
                 (at(100), at(130)))
    body = get(client, "/metrics", **{"from": at(0), "to": at(480)}).json()
    assert [x["code"] for x in body["warnings"] if x["code"].startswith("SERVICE")] == ["SERVICE_DURING_BREAK"]
    assert body["data"]["metrics"]["arrival_count"] == 1


# --- R4-04: C01 is not a back door round the operator-only commands -----------------------------------------------------

def ticket_state_world() -> World:
    w = World(window=(0, 700))
    w.ticket("t-1", 0)
    w.ev("t-1", "queued", 0, queue="q-1", actor="sup")
    return w


def resolve_batch(tid="t-1"):
    return {"ticket_events": [{"event_id": "x-1", "ticket_id": tid, "event_type": "resolved", "occurred_at": at(12),
                               "actor_id": "ana-1", "queue_id": None, "agent_id": "a-1"}]}


def test_R4_04_an_analyst_cannot_change_an_existing_tickets_state_through_ingest(client, conn):
    load(conn, ticket_state_world())
    before = count(conn, "ticket_events")
    r = command(client, "ingest-ticket-events", resolve_batch(), headers=ANALYST)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_FORBIDDEN"
    assert count(conn, "ticket_events") == before and count(conn, "command_results") == 0


@pytest.mark.parametrize("headers", [SUPERVISOR, ADMIN])
def test_R4_04_a_supervisor_or_admin_may(client, conn, headers):
    load(conn, ticket_state_world())
    r = command(client, "ingest-ticket-events", resolve_batch(), headers=headers)
    assert r.status_code == 200 and r.json()["result"]["inserted"]["ticket_events"] == 1


def test_R4_04_an_analyst_still_ingests_new_tickets(client, conn):
    load(conn, World(window=(0, 700)))
    t = {"ticket_id": "t-new", "customer_id": "c-1", "queue_id": "q-1", "priority": "P2", "created_at": at(5), "channel": "email"}
    e = {"event_id": "e-new", "ticket_id": "t-new", "event_type": "created", "occurred_at": at(5), "actor_id": None,
         "queue_id": "q-1", "agent_id": None}
    r = command(client, "ingest-ticket-events", {"tickets": [t], "ticket_events": [e]}, headers=ANALYST)
    assert r.status_code == 200 and r.json()["status"] == "loaded"


# --- R4-05: dataset_version is checked and hashed -----------------------------------------------------------------------

def test_R4_05_a_stale_dataset_version_is_409_and_writes_nothing(client, seeded):
    r = command(client, "run-simulation", {"simulation_id": "s-x", "seed": 1, "horizon_minutes": 60, "policy_version": "p",
                                           "config": {"service_minutes": 10, "arrivals": [0]}}, dataset_version="ds-stale")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_DATASET_VERSION"
    ctx = r.json()["error"]["details"][0]["context"]
    assert ctx["requested"] == "ds-stale" and ctx["current"].startswith("ds-")
    assert count(seeded, "command_results") == 0 and count(seeded, "simulation_runs") == 1      # only the golden run


def test_R4_05_the_current_version_is_accepted_and_is_part_of_the_idempotency_payload(client, seeded):
    cur = seeded.execute("SELECT dataset_version FROM dataset_versions").fetchone()["dataset_version"]
    inp = {"simulation_id": "s-x", "seed": 1, "horizon_minutes": 60, "policy_version": "p",
           "config": {"service_minutes": 10, "arrivals": [0]}}
    assert command(client, "run-simulation", inp, key="k-1", dataset_version=cur).status_code == 200
    again = command(client, "run-simulation", inp, key="k-1", dataset_version=cur)
    assert again.status_code == 200 and again.headers.get("Idempotent-Replay") == "true"
    other = command(client, "run-simulation", inp, key="k-1", dataset_version="ds-another")      # same key and body
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_R4_05_no_dataset_row_means_nothing_to_be_stale_against(client, conn):
    load(conn, World(window=(0, 60)))
    conn.execute("DELETE FROM dataset_versions")
    r = command(client, "compare-policies", {"seed": 1, "horizon_minutes": 60, "replications": 2,
                                             "baseline": {"service_minutes": 10, "arrivals": [0]},
                                             "proposal": {"service_minutes": 10, "arrivals": [0]}}, dataset_version="anything")
    assert r.status_code == 200


# --- R4-01 / R4-15 are SQL findings (tests/test_sql_reference.py); the domain side of R4-01 ------------------------------

def test_R4_01_no_shift_in_the_window_is_zero_staffed_time_and_null_occupancy():
    w = World(window=(0, 180))
    w.d["shifts"] = []
    w.ticket("t-1", 0)
    res = run_pipeline(w.data())
    assert res.metrics["staffed_available_minutes"] == "0.0000" and res.metrics["agent_occupancy"] is None


# --- R4-15 / R4-16 ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("first,second,completed", [("reopened", "resolved", 1), ("resolved", "reopened", 0)])
def test_R4_15_same_instant_reopen_and_resolve_are_ordered_by_event_id(first, second, completed):
    w = World(window=(0, 180))
    w.ticket("t-1", 0)
    w.serve("t-1", 5, 20)
    w.ev("t-1", first, 30, actor="x", agent="a-1" if first == "resolved" else None)
    w.ev("t-1", second, 30, actor="x", agent="a-1" if second == "resolved" else None)
    assert run_pipeline(w.data()).metrics["completion_count"] == completed


def test_R4_16_a_log_that_opens_with_resumed_is_rejected():
    w = World(window=(0, 180))
    w.ticket("t-1", 0)
    w.ev("t-1", "resumed", 5, agent="a-1")
    w.ev("t-1", "service_started", 10, agent="a-1")
    w.ev("t-1", "replied_human", 10, agent="a-1")
    w.ev("t-1", "resolved", 20, agent="a-1")
    res = run_pipeline(w.data())
    got = reasons(res)
    assert got[("tickets", "t-1")] == "RESUME_BEFORE_SERVICE"
    assert all(v == "TICKET_REJECTED" for k, v in got.items() if k[0] == "ticket_events")
    assert res.metrics["arrival_count"] == 0


def test_R4_16_a_resume_after_a_service_start_is_unaffected():
    w = World(window=(0, 180))
    w.ticket("t-1", 0)
    w.ev("t-1", "service_started", 10, agent="a-1")
    w.ev("t-1", "replied_human", 10, agent="a-1")
    w.ev("t-1", "paused", 20, agent="a-1")
    w.ev("t-1", "resumed", 40, agent="a-1")
    w.ev("t-1", "resolved", 50, agent="a-1")
    res = run_pipeline(w.data())
    assert res.ingest.rejected == [] and res.metrics["wait_minutes"] == {"t-1": "10.0000"}


# --- R4-17: one parsing rule in both domains ----------------------------------------------------------------------------

def batch_with(**changes):
    w = World(window=(0, 180))
    w.ticket("t-1", 0)
    w.serve("t-1", 5, 20)
    d = w.data()
    d.update(changes)
    return d


def test_R4_17_an_integral_float_is_an_integer_and_a_fractional_one_is_not():
    for v, ok in ((30.0, True), (30, True), (30.5, False), (float("nan"), False), (True, False), ("30", False)):
        shifts = [{"shift_id": "sh-x", "agent_id": "a-1", "starts_at": at(0), "ends_at": at(480), "break_minutes": v}]
        rej = validate_batch(batch_with(shifts=shifts)).rejected
        assert (rej == []) is ok, v


def test_R4_17_an_instant_needs_seconds():
    d = batch_with()
    d["ticket_events"][-1]["occurred_at"] = "2026-07-06T09:20Z"
    got = {(r.entity, r.reason_code) for r in validate_batch(d).rejected}
    assert ("ticket_events", "MALFORMED_RECORD") in got
    for bad in ("2026-07-06T09:20", "2026-07-06", "20260706T092000Z", "2026-07-06T09:20:00"):
        with pytest.raises(ValueError):
            parse_ts(bad)
    assert parse_ts("2026-07-06T09:20:00Z") == parse_ts("2026-07-06T11:20:00+02:00") == parse_ts("2026-07-06 09:20:00+00:00")


def test_R4_17_the_seed_range_is_json_safe_in_both_domains():
    cfg = {"service_minutes": 10, "arrivals": [0]}
    for seed, ok in ((2 ** 53 - 1, True), (-(2 ** 53 - 1), True), (2 ** 53, False), (2 ** 62, False), (-(2 ** 62), False)):
        run = [{"simulation_id": "s-1", "seed": seed, "warmup_minutes": 0, "policy_version": "p", "horizon_minutes": 60, "config": cfg}]
        assert (validate_batch(batch_with(simulation_runs=run)).rejected == []) is ok, seed


# --- R4-18 and the cutoff edge -------------------------------------------------------------------------------------------

def test_R4_18_a_calendar_other_than_the_24x7_one_is_warned_about():
    res = run_pipeline(World(window=(0, 180)).data())             # the builder's policies name cal-1
    assert {w["code"] for w in res.warnings} == {"SLA_CALENDAR_IGNORED"} and len(res.warnings) == 3   # cutoff = end, nothing there
    d = World(window=(0, 180)).data()
    for p in d["sla_policies"]:
        p["calendar_id"] = "cal-001"
    assert run_pipeline(d).warnings == []


def test_R4_18_the_window_is_half_open_but_a_cutoff_counts_events_at_its_own_instant():
    """Documented edge (D-09): at a cutoff equal to the window end the arrival AT that instant is in the backlog and the
    resolution AT that instant is not, although the half-open window excludes both."""
    w = World(window=(0, 60), cutoffs=[60])
    w.ticket("t-1", 0)
    w.serve("t-1", 10, 60)                       # resolved exactly at the window end
    w.ticket("t-3", 60)                          # arrives exactly at the window end
    res = run_pipeline(w.data())
    assert res.metrics["arrival_count"] == 1 and res.metrics["completion_count"] == 0
    assert res.metrics["backlog"] == {at(60): 1}
    assert [x["code"] for x in res.warnings if x["code"].startswith("CUTOFF")] == ["CUTOFF_AT_OR_AFTER_WINDOW_END"]
    inside = World(window=(0, 60), cutoffs=[59])
    inside.ticket("t-1", 0)
    assert not [x for x in run_pipeline(inside.data()).warnings if x["code"].startswith("CUTOFF")]


def test_R4_18_the_metrics_read_carries_the_warnings(client, conn):
    load(conn, World(window=(0, 180)))
    plain = get(client, "/metrics", **{"from": at(0), "to": at(180)}).json()
    assert {x["code"] for x in plain["warnings"]} == {"SLA_CALENDAR_IGNORED"}            # default cutoff: no edge noise
    w2 = World(window=(0, 60))
    w2.ticket("t-3", 60)                                                                  # arrives AT the window end
    conn.execute("DELETE FROM ticket_events"); conn.execute("DELETE FROM tickets")
    load(conn, w2)
    edged = get(client, "/metrics", **{"from": at(0), "to": at(60), "cutoff": at(60)}).json()
    assert "CUTOFF_AT_OR_AFTER_WINDOW_END" in {x["code"] for x in edged["warnings"]}


# --- R4-09 / R4-10 ----------------------------------------------------------------------------------------------------

def test_R4_09_a_reopen_is_counted_over_completions_as_well_as_arrivals():
    w = World(window=(100, 300))
    w.ticket("t-1", 0)                                   # arrived before the window
    w.serve("t-1", 5, 20)
    w.ev("t-1", "reopened", 110, actor="c")
    w.serve("t-1", 120, 130)
    res = run_pipeline(w.data())
    d = disclosures(res.population, (parse_ts(at(100)), parse_ts(at(300))))
    assert res.metrics["arrival_count"] == 0 and res.metrics["completion_count"] == 1
    assert d["reopened_tickets"] == 1 and d["reopen_events"] == 1 and d["reopened_among_completions"] == 1
    assert "arrivals and completions" in d["reopened_basis"]


def test_R4_10_group_by_queue_uses_the_final_queue_and_says_so(client, conn):
    w = World(window=(0, 180))
    w.ticket("t-1", 0, queue="q-1")
    w.d["tickets"][0]["queue_id"] = "q-2"            # the ticket row holds the CURRENT queue (what C01 stores after a transfer)
    w.ev("t-1", "transferred", 5, actor="s", queue="q-2")
    w.serve("t-1", 10, 20, queue="q-2")
    load(conn, w)
    d = get(client, "/metrics", **{"from": at(0), "to": at(180)}, group_by="queue").json()["data"]
    assert list(d["groups"]) == ["q-2"] and d["groups"]["q-2"]["arrival_count"] == 1 and "FINAL queue" in d["group_basis"]


# --- R4-11: replications and the paired difference ---------------------------------------------------------------------

def test_R4_11_the_reference_file_equals_the_python_simulator():
    ref = json.loads((ROOT / "web" / "public" / "reference" / "simulation-runs.json").read_text())
    rows = {r["simulation_id"]: r for r in json.loads((DATA / "simulation_runs.json").read_text())["rows"]}
    rep = ref["replications"]
    assert rep["count"] == 50
    for sid, r in rows.items():
        assert replication_report(r["config"], r["seed"], 50, r["warmup_minutes"], r["horizon_minutes"]) == rep["runs"][sid]
        assert rep["runs"][sid]["mean_wait_minutes"]["n"] == 50 and rep["runs"][sid]["mean_wait_minutes"]["ci95_half_width"]
    b, p, h = rows["sim-001"], rows["sim-002"], rows["sim-003"]
    pair = compare_policies(b["config"], p["config"], b["seed"], 50, b["warmup_minutes"], b["horizon_minutes"])
    assert {**rep["paired"]["baseline_vs_plus_one_agent"]} == {"baseline": "sim-001", "proposal": "sim-002", **pair}
    assert pair["same_demand_paths"] is True and pair["proposal_better"] is True
    assert rep["paired"]["baseline_vs_holdout_intensity"]["same_demand_paths"] is False       # sim-003: by design


def test_R4_11_the_95_percent_interval_uses_the_student_t_value_at_49_degrees_of_freedom():  # t = 2.010
    vals = [Fraction(i) for i in range(50)]
    sd = (sum((v - Fraction(49, 2)) ** 2 for v in vals) / 49) ** 0.5
    want = 2.010 * sd / 50 ** 0.5
    assert abs(float(mean_ci95(vals)["ci95_half_width"]) - want) < 5e-4          # was 1.96, 2.5 % too narrow


# --- R4-12 / R4-13: documentation and the recorded realisation ---------------------------------------------------------

def test_R4_12_the_staffed_minutes_sentence_names_the_right_totals():
    text = (ROOT / "docs" / "contracts.md").read_text()
    assert "(447,450 vs 447,990)" not in text
    for needle in ("447,450", "447,990", "297,870", "149,640", "447,510"):
        assert needle in text


def test_R4_13_the_manifest_records_the_realisation_and_the_hash_still_covers_the_entity_files_only():
    m = json.loads((DATA / "manifest.json").read_text())
    r = m["generator"]["parameters"]["arrival_realisation"]
    assert r["attempt_index"] == 7 and r["discarded_uplift_percent"] == [12.86, 14.58, 22.82, 16.92, 12.69, 22.02, 30.46]
    assert r["chosen_uplift_percent"] == 20.1 and r["noise_sd_points"] == 4.3 and "chosen realisation" in r["note"]
    h = hashlib.sha256()
    for name in sorted(m["row_counts"]):
        rows = json.loads((DATA / f"{name}.json").read_text())["rows"]
        h.update(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
    assert h.hexdigest() == m["dataset_hash"] == "944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4"


def test_R4_10_R4_13_the_documents_say_what_the_site_says():
    contracts = (ROOT / "docs" / "contracts.md").read_text()
    assert "## D-09" in contracts and "wait to first service" in contracts and "chosen realisation" in contracts
    api = (ROOT / "docs" / "api-contract.md").read_text()
    assert "ROLE_FORBIDDEN" in api and "STALE_DATASET_VERSION" in api
