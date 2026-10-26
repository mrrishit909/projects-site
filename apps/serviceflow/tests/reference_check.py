#!/usr/bin/env python3
"""Independent reference calculation for the ServiceFlow golden fixtures (P04-GOLD-01..10).

Standard library only; imports nothing from the application. Recomputes every number from
inputs.json by replaying the event log per ticket and by a plain FIFO simulation loop, then
compares with expected.json. Durations: decimal strings, 4 dp, minutes. Rates: 6 dp.

Usage:
  python3 reference_check.py                # check everything, exit 0 only if all OK
  python3 reference_check.py --write-hashes # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
FOUR, SIX = Decimal("0.0001"), Decimal("0.000001")
FIXTURES = ["", "variant-rejected/", "variant-empty/"]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENTITIES = ["customers", "queues", "tickets", "ticket_events", "agents", "skills", "agent_skills",
            "queue_skills", "shifts", "sla_policies", "surveys", "simulation_runs"]
failures = 0


def report(ok, name, expected, got):
    global failures
    if ok:
        print(f"OK {name} {got}")
    else:
        failures += 1
        print(f"MISMATCH {name} expected {expected} got {got}")


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def minutes(a, b):
    """b - a in minutes as an exact Decimal."""
    return Decimal(int((b - a).total_seconds())) / Decimal(60)


def d4(x):
    return None if x is None else str(x.quantize(FOUR, rounding=ROUND_HALF_UP))


def d6(x):
    return None if x is None else str(x.quantize(SIX, rounding=ROUND_HALF_UP))


def ratio(n, d):
    return None if d == 0 else Decimal(n) / Decimal(d)


def mean(xs):
    return None if not xs else sum(xs, Decimal(0)) / len(xs)


def nearest_rank(xs, p):
    """D-02: sort ascending, take index ceil(p * n) (1-based)."""
    if not xs:
        return None
    s = sorted(xs)
    return s[math.ceil(Decimal(p) * len(s)) - 1]


def by_time(events):
    return sorted(events, key=lambda e: (e["occurred_at"], e["event_id"]))


def service_intervals(events):
    """Replay one ticket's log: each service_started opens an interval closed by the next
    resolved / paused / transferred / abandoned event (D-02 handling = sum of active intervals)."""
    out, open_at = [], None
    for e in by_time(events):
        if e["event_type"] == "service_started" and open_at is None:
            open_at = ts(e["occurred_at"])
        elif e["event_type"] in ("resolved", "paused", "transferred", "abandoned") and open_at is not None:
            out.append((open_at, ts(e["occurred_at"])))
            open_at = None
    return out, open_at


def ingest(data):
    """D-01 qualification and concurrency; a rejected ticket takes its events and surveys with it."""
    tickets = {t["ticket_id"]: t for t in data["tickets"]}
    agents = {a["agent_id"]: a for a in data["agents"]}
    need = {}
    for q in data["queue_skills"]:
        need.setdefault(q["queue_id"], set()).add(q["skill_id"])
    ev_by_t = {}
    for e in data["ticket_events"]:
        ev_by_t.setdefault(e["ticket_id"], []).append(e)
    reason = {}
    starts = sorted((e for e in data["ticket_events"] if e["event_type"] == "service_started"),
                    key=lambda e: (e["occurred_at"], e["event_id"]))
    accepted_iv = []   # (agent, start, end or None, ticket)
    for e in starts:
        t = e["ticket_id"]
        at = ts(e["occurred_at"])
        ag = agents[e["agent_id"]]
        held = {s["skill_id"] for s in data["agent_skills"]
                if s["agent_id"] == ag["agent_id"] and ts(s["effective_from"]) <= at}
        if not need.get(tickets[t]["queue_id"], set()) <= held:
            reason[t] = "AGENT_NOT_QUALIFIED"
            continue
        iv, still = service_intervals(ev_by_t[t])
        end = None
        for a, b in iv:
            if a == at:
                end = b
        busy = sum(1 for (g, s, en, tk) in accepted_iv
                   if g == ag["agent_id"] and s <= at and (en is None or at < en))
        if busy >= ag["max_concurrent"]:
            reason[t] = "CONCURRENCY_EXCEEDED"
            continue
        accepted_iv.append((ag["agent_id"], at, end, t))
    acc = {k: list(data.get(k, [])) for k in ENTITIES}
    rejected = []
    for ent, idk, tk in (("tickets", "ticket_id", "ticket_id"), ("ticket_events", "event_id", "ticket_id"),
                         ("surveys", "survey_id", "ticket_id")):
        keep = []
        for r in data[ent]:
            if r[tk] in reason:
                code = reason[r[tk]] if ent == "tickets" else "TICKET_REJECTED"
                rejected.append({"entity": ent, "id": r[idk], "status": "rejected", "reason_code": code, "raw_row": r})
            else:
                keep.append(r)
        acc[ent] = keep
    rejected.sort(key=lambda r: (r["entity"], r["id"]))
    return acc, rejected


def staffed(shifts, w0, w1):
    """D-03: shift overlap with the window minus break minutes. No break interval is recorded, so
    the break is deducted only when the window covers the whole shift (assumption A-2)."""
    total, whole = Decimal(0), Decimal(0)
    for s in shifts:
        a, b = ts(s["starts_at"]), ts(s["ends_at"])
        whole += minutes(a, b) - s["break_minutes"]
        lo, hi = max(a, w0), min(b, w1)
        if hi > lo:
            ov = minutes(lo, hi)
            total += ov - (s["break_minutes"] if (lo, hi) == (a, b) else 0)
    return total, whole


def compute(data, acc):
    w0, w1 = ts(data["window_start"]), ts(data["window_end"])
    hours = minutes(w0, w1) / 60
    tickets = {t["ticket_id"]: t for t in acc["tickets"]}
    log = {t: [] for t in tickets}
    for e in acc["ticket_events"]:
        log[e["ticket_id"]].append(e)
    policy = {p["priority"]: p for p in acc["sla_policies"]}

    created, resolved, first_resp, wait, resol, handling = {}, {}, {}, {}, {}, Decimal(0)
    for t, row in tickets.items():
        events = by_time(log[t])
        created[t] = ts(row["created_at"])
        cycle_start = created[t]
        res = None
        for e in events:                       # last cycle wins; reopen restarts the cycle record
            if e["event_type"] == "reopened":
                res = None
            if e["event_type"] == "resolved":
                res = ts(e["occurred_at"])
        resolved[t] = res
        humans = [ts(e["occurred_at"]) for e in events
                  if e["event_type"] == "replied_human" and not str(e["actor_id"]).startswith("bot-")]
        started = [ts(e["occurred_at"]) for e in events if e["event_type"] == "service_started"]
        if humans:
            first_resp[t] = minutes(cycle_start, min(humans))
        if started:
            wait[t] = minutes(cycle_start, min(started))
        if res is not None:
            resol[t] = minutes(cycle_start, res)
        iv, _ = service_intervals(events)
        handling += sum((minutes(a, b) for a, b in iv), Decimal(0))

    in_win = lambda x: x is not None and w0 <= x < w1
    arrivals = [t for t in tickets if in_win(created[t])]
    completions = [t for t in tickets if in_win(resolved[t])]
    backlog = {c: sum(1 for t in tickets if created[t] <= ts(c) and (resolved[t] is None or resolved[t] > ts(c)))
               for c in data["backlog_cutoffs"]}

    fr_vals = [first_resp[t] for t in arrivals if t in first_resp]
    res_vals = [resol[t] for t in completions]
    fr_ok = sum(1 for t in arrivals if t in first_resp and first_resp[t] <= policy[tickets[t]["priority"]]["first_response_minutes"])
    rs_ok = sum(1 for t in completions if resol[t] <= policy[tickets[t]["priority"]]["resolution_minutes"])
    overdue = 0
    for t in tickets:
        if created[t] <= w1 and (resolved[t] is None or resolved[t] > w1):
            if minutes(created[t], w1) > policy[tickets[t]["priority"]]["resolution_minutes"]:
                overdue += 1

    staff, whole = staffed(acc["shifts"], w0, w1)
    occ = None if staff == 0 else handling / staff          # D-03: null when staffed time is 0
    ab_ch = set(data["abandonable_channels"])
    ab_t = [t for t in arrivals if tickets[t]["channel"] in ab_ch]
    ab_n = sum(1 for t in ab_t if any(e["event_type"] == "abandoned" for e in log[t]))

    surveys = acc["surveys"]
    invited = [s for s in surveys if s["invited_at"]]
    responded = [s for s in invited if s["score"] is not None and s["response_at"] is not None]
    pos = sum(1 for s in responded if s["score"] >= 4)

    empty = len(tickets) == 0
    return {
        "arrival_count": len(arrivals), "completion_count": len(completions),
        "arrival_rate_per_hour": d6(Decimal(len(arrivals)) / hours),
        "completion_rate_per_hour": d6(Decimal(len(completions)) / hours),
        "backlog": backlog,
        "first_response_minutes": {t: d4(first_resp[t]) for t in sorted(arrivals) if t in first_resp},
        "mean_first_response_minutes": d4(mean(fr_vals)),
        "p90_first_response_minutes": d4(nearest_rank(fr_vals, "0.9")),
        "wait_minutes": {t: d4(wait[t]) for t in sorted(arrivals) if t in wait},
        "mean_wait_minutes": d4(mean([wait[t] for t in arrivals if t in wait])),
        "resolution_minutes": {t: d4(resol[t]) for t in sorted(completions)},
        "mean_resolution_minutes": d4(mean(res_vals)),
        "handling_minutes_total": d4(handling),
        "sla_first_response_compliance": d6(ratio(fr_ok, len(fr_vals))),
        "sla_first_response_within": fr_ok, "sla_first_response_eligible": len(fr_vals),
        "sla_resolution_compliance": d6(ratio(rs_ok, len(res_vals))),
        "sla_resolution_within": rs_ok, "sla_resolution_eligible": len(res_vals),
        "open_overdue_at_cutoff": overdue,
        "staffed_available_minutes": d4(staff), "staffed_shift_minutes_whole": d4(whole),
        "agent_occupancy": d6(occ),
        "abandonment_rate": d6(ratio(ab_n, len(ab_t))),
        "csat": d6(ratio(pos, len(responded))),
        "survey_invitation_rate": d6(ratio(len(invited), len(completions))),
        "survey_response_rate": d6(ratio(len(responded), len(invited))),
        "empty_population": empty,
    }


def simulate(run):
    """FIFO discrete-event loop: each ticket (in arrival order) takes the earliest-free agent."""
    cfg = run["config"]
    assert cfg["discipline"] == "fifo"
    free = [Decimal(0)] * cfg["agents"]
    svc = Decimal(cfg["service_minutes"])
    rows, waits, last = [], [], Decimal(0)
    for i, arr in enumerate(cfg["arrivals"]):
        arr = Decimal(arr)
        j = free.index(min(free))
        start = max(free[j], arr)
        end = start + svc
        free[j] = end
        rows.append((i, start, end))
        waits.append(start - arr)
        last = max(last, end)
    events = []
    for kind, pick in (("service_started", 1), ("resolved", 2)):
        for r in rows:
            events.append((kind, r[0], r[pick]))
    return {"simulation_id": run["simulation_id"], "waits_minutes": [d4(w) for w in waits],
            "mean_wait_minutes": d4(mean(waits)), "final_completion_minute": d4(last),
            "events": [{"simulation_event_id": f"se-{k+1:03d}", "simulation_id": run["simulation_id"],
                        "ticket_id": f"t-{i+1:03d}", "event_type": kind, "event_at": d4(at)}
                       for k, (kind, i, at) in enumerate(events)]}


def check_fixture(prefix):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    label = prefix.rstrip("/") or "golden"
    for k in ENTITIES:
        data.setdefault(k, [])
    acc, rejected = ingest(data)
    for ent in ENTITIES:
        e = exp["ingest"]["counts"][ent]
        got = {"accepted": len(acc[ent]), "rejected": sum(1 for r in rejected if r["entity"] == ent)}
        report(e == got, f"{label}.ingest.{ent}", e, got)
    report(rejected == exp["ingest"]["rejected_records"], f"{label}.ingest.rejected_records",
           [(r["entity"], r["id"], r["reason_code"]) for r in exp["ingest"]["rejected_records"]],
           [(r["entity"], r["id"], r["reason_code"]) for r in rejected])
    got = compute(data, acc)
    for k, want in exp["metrics"].items():
        report(got.get(k) == want and type(got.get(k)) is type(want), f"{label}.{k}", want, got.get(k))
    report(set(got) == set(exp["metrics"]), f"{label}.metric_names", sorted(exp["metrics"]), sorted(got))
    runs = data.get("simulation_runs", [])
    sim = simulate(runs[0]) if runs else None
    report(sim == exp["simulation"], f"{label}.simulation", exp["simulation"], sim)
    if prefix == "variant-rejected/":
        gold = json.loads((GOLDEN / "expected.json").read_text())
        same = gold["metrics"] == exp["metrics"] and gold["simulation"] == exp["simulation"]
        report(same, f"{label}.totals_equal_golden", "equal", "equal" if same else "different")


def sha(path):
    return hashlib.sha256((GOLDEN / path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true")
    args = ap.parse_args()
    for prefix in FIXTURES:
        check_fixture(prefix)
    hp = GOLDEN / "HASHES.json"
    if args.write_hashes:
        if failures:
            print(f"NOT WRITING HASHES: {failures} mismatch(es)")
        else:
            hp.write_text(json.dumps({"algorithm": "sha256", "sha256": {p: sha(p) for p in HASHED}}, indent=2) + "\n")
            print(f"OK wrote {hp.name}")
    elif hp.exists():
        stored = json.loads(hp.read_text())["sha256"]
        for p in HASHED:
            report(stored.get(p) == sha(p), f"hash[{p}]", stored.get(p), sha(p))
    print("ALL OK" if not failures else f"{failures} MISMATCH(ES)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
