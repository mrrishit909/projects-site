#!/usr/bin/env python3
"""ServiceFlow synthetic data generator (P04-WORK-03, docs/data-generator.md).

Stdlib only. Deterministic: ``random.Random(seed)`` derives one child stream per purpose (roster, customers,
arrivals, tickets, dispatch, surveys, injections, ...), so the same seed and parameters give byte-identical entity files
and the same ``dataset_hash``. Nothing is imported from ``domain/``: the queue discipline, the shift and break rules and
the metric definitions are restated here from docs/contracts.md (D-01..D-06).

    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --profile golden-shape-check

Writes ``<entity>.json`` (``{"entity", "dataset_version", "rows"}``) and ``manifest.json`` to ``--out`` (plus
``golden/``, the hand-derived fixture in the same shape); ``injection-manifest.json`` and ``injection-events.json`` to
``--data-dir`` (default ``data/``) and a copy of the injection manifest to ``--out``.

The world is a discrete-event simulation (integer seconds from 2026-07-06T00:00:00Z): Poisson arrivals by hour of
week, 18 agents on shifts declared in local wall-clock time (zoneinfo), 30-minute breaks taken at the first idle moment
after the planned time, FIFO within priority (the onboarding queue is plain FIFO), skills with effective dates, pauses,
transfers, reopens, abandonment on chat and phone, surveys. Defects are injected afterwards (INJ-01..09).
"""
from __future__ import annotations

import argparse
import ast
import bisect
import hashlib
import heapq
import itertools
import json
import math
import random
import sys
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
CONTRACT_VERSION = "v1"
UTC = timezone.utc
START = date(2026, 7, 6)                 # a Monday
END = date(2026, 9, 27)                  # inclusive; the snapshot is cut at 23:59:59Z that day
NDAYS = (END - START).days + 1           # 84 days = 12 weeks
WEEKS = NDAYS // 7
TRAIN_WEEKS = 8                          # weeks 1-8 training, weeks 9-12 holdout
HOLDOUT_UPLIFT = 1.20                    # designed and disclosed: the holdout arrives 20 % harder
T0 = datetime(2026, 7, 6, tzinfo=UTC)
CUT = NDAYS * 86400                      # seconds from T0 of 2026-09-28T00:00:00Z (exclusive end of the window)
AS_OF = "2026-09-27T23:59:59Z"
WINDOW_START = "2026-07-06T00:00:00Z"
WINDOW_END = "2026-09-28T00:00:00Z"
TRAIN_END = TRAIN_WEEKS * 7 * 86400      # seconds of 2026-08-31T00:00:00Z

#: Domain entities (docs/contracts.md, domain ENTITIES order) plus the data-load-only ``shift_breaks`` table.
DOMAIN_ENTITIES = ("customers", "queues", "tickets", "ticket_events", "agents", "skills", "agent_skills",
                   "queue_skills", "shifts", "sla_policies", "surveys", "simulation_runs")
EXTRA_ENTITIES = ("shift_breaks",)
ENTITIES = DOMAIN_ENTITIES + EXTRA_ENTITIES
#: Columns of shift_breaks (0001_schema.sql); the other entities use data/seed.py COLUMNS.
SHIFT_BREAK_COLUMNS = ("break_id", "shift_id", "agent_id", "starts_at", "ends_at")

TICKETS_TARGET = 3700                    # expected tickets (the 5 MB cap, see README-generator.md "Size")
SIZE_BUDGET = 5_000_000
STREAMS = ("roster", "customers", "arrivals", "tickets", "dispatch", "surveys", "late", "inject", "simulation")

QUEUES = (("q-001", "Billing", "fifo_within_priority", "s-001"),
          ("q-002", "Technical", "fifo_within_priority", "s-002"),
          ("q-003", "Onboarding", "fifo", "s-003"))
QUEUE_IDS = tuple(q[0] for q in QUEUES)
QUEUE_NAME = {q[0]: q[1] for q in QUEUES}
QUEUE_POLICY = {q[0]: q[2] for q in QUEUES}
QUEUE_SKILL = {q[0]: q[3] for q in QUEUES}
SKILLS = (("s-001", "Billing", "Invoices, refunds and plan changes"),
          ("s-002", "Technical", "Integration faults and outage troubleshooting"),
          ("s-003", "Onboarding", "Account set-up and first-week guidance"))
QUEUE_SHARE = (0.36, 0.40, 0.24)
PRIORITIES = ("P1", "P2", "P3")
PRIORITY_MIX = {"q-001": (0.03, 0.32, 0.65), "q-002": (0.10, 0.40, 0.50), "q-003": (0.04, 0.36, 0.60)}
#: First response / resolution targets in minutes (wall clock, calendar cal-001 is 24x7).
SLA = {"P1": (15, 240), "P2": (60, 1440), "P3": (240, 4320)}
CHANNELS = ("email", "chat", "phone", "web_form")
CHANNEL_SHARE = (0.40, 0.30, 0.15, 0.15)
ABANDONABLE = ("chat", "phone")
PATIENCE_MEAN_SECONDS = {"chat": 35 * 60, "phone": 18 * 60}
P_IMPATIENT = 0.55
P_TRANSFER = 0.085
P_REOPEN = 0.066
P_PAUSE = 0.12
P_INVITE = 0.60
RESPONSE_BASE = 0.42                     # x 1.0 (score >= 4), 0.55 (3), 0.35 (<= 2), x 0.6 after a poor experience
POOR_EXPERIENCE_RESPONSE = 0.60          # about 35 % overall, and skewed towards the satisfied
BREAK_SECONDS = 1800
#: Handling median minutes and sigma by queue and priority (proficiency 3). Technical P1 is a mixture (below).
HANDLING = {("q-001", "P1"): (36, 0.45), ("q-001", "P2"): (30, 0.45), ("q-001", "P3"): (23, 0.45),
            ("q-002", "P2"): (80, 0.55), ("q-002", "P3"): (57, 0.55),
            ("q-003", "P1"): (70, 0.45), ("q-003", "P2"): (57, 0.45), ("q-003", "P3"): (47, 0.45)}
TECH_P1_ROUTINE = (0.72, 28, 0.40)       # share, median minutes, sigma: a routine fix
TECH_P1_ESCALATED = (130, 0.50)          # the rest: escalated to engineering
P_MAJOR = 0.15                           # share of technical P1 that is a major incident (long engineering wait)
MAJOR_HANDLING = (120, 0.40)             # median minutes, sigma of the hands-on time of a major incident
MAJOR_GAP = (2 * 3600 + 600, 5 * 3600)        # seconds the customer-facing work waits for engineering (paused)
HANDOVER_AFTER = 3 * 3600                # a resume nobody on shift owns for this long is handed to a qualified agent
LONG_GAP = 7200                          # a pause longer than this lets the agent leave the shift (resume next shift)
HANDLING_MIN, HANDLING_MAX = 4 * 60, 200 * 60
PROFICIENCY_FACTOR = {1: 1.30, 2: 1.15, 3: 1.00, 4: 0.85, 5: 0.72}
MAX_CHUNK = 90 * 60
FIT_MARGIN = 15 * 60

# hour-of-day weights (UTC) of the arrival intensity, day-of-week multipliers (Mon..Sun), the Monday 09-11 UTC surge
HOUR_WEIGHT = (0.06, 0.05, 0.05, 0.05, 0.06, 0.12, 0.30, 0.55, 0.80, 1.00, 1.10, 1.15, 1.20, 1.30, 1.35, 1.25,
               1.10, 0.90, 0.70, 0.55, 0.40, 0.28, 0.15, 0.09)
DAY_WEIGHT = (1.00, 1.05, 1.05, 1.00, 0.92, 0.14, 0.10)
MONDAY_SURGE = {9: 2.4, 10: 2.4}         # hours (UTC) of Monday multiplied by this

CUSTOMERS_N = 1000
SEGMENTS = (("consumer", 0.55), ("smb", 0.35), ("enterprise", 0.10))
CUSTOMER_ZONES = (("America/New_York", 0.30), ("America/Chicago", 0.12), ("America/Los_Angeles", 0.12),
                  ("Europe/London", 0.10), ("Europe/Berlin", 0.10), ("America/Santiago", 0.06),
                  ("Asia/Kolkata", 0.06), ("Australia/Sydney", 0.05), ("America/Sao_Paulo", 0.05),
                  ("Asia/Singapore", 0.04))

#: id, name, zone, employment, skills (skill, proficiency, effective_from), roster = [(weekdays, "HH:MM", hours)]
EARLY = ((0, 1, 2, 3, 4), "07:00", 8)
MID = ((0, 1, 2, 3, 4), "09:00", 8)
LATE = ((0, 1, 2, 3, 4), "11:00", 8)
SDAY = ((0, 1, 2, 3, 4), "08:00", 8)
SAFT = ((0, 1, 2, 3, 4), "12:00", 8)
AGENT_DEFS = (
    ("agt-001", "Ines Brandt", "Europe/Berlin", "full_time", (("s-001", 4, None), ("s-002", 2, None)), [EARLY]),
    ("agt-002", "Jonas Keller", "Europe/Berlin", "full_time", (("s-002", 5, None), ("s-001", 3, None)), [EARLY]),
    ("agt-003", "Mara Vogel", "Europe/Berlin", "full_time", (("s-003", 3, None),), [EARLY]),
    ("agt-004", "Tilo Neumann", "Europe/Berlin", "full_time", (("s-001", 3, None), ("s-003", 2, None)), [((1, 2, 3, 4, 5), "09:00", 8)]),
    ("agt-005", "Lena Fischer", "Europe/Berlin", "full_time", (("s-002", 4, None), ("s-003", 2, "2026-08-03")), [MID]),
    ("agt-006", "Pavel Novak", "Europe/Berlin", "full_time", (("s-002", 2, None),), [((6, 0, 1, 2, 3), "09:00", 8)]),
    ("agt-007", "Greta Lund", "Europe/Berlin", "part_time", (("s-003", 5, None),), [((0, 1, 2, 3), "09:00", 6)]),
    ("agt-008", "Omar Haddad", "Europe/Berlin", "full_time", (("s-001", 5, None), ("s-002", 3, None)), [LATE]),
    ("agt-009", "Sofia Ricci", "Europe/Berlin", "full_time", (("s-003", 4, None),), [LATE]),
    ("agt-010", "Camila Rojas", "America/Santiago", "full_time", (("s-001", 2, None), ("s-003", 3, None)), [SDAY]),
    ("agt-011", "Tomas Araya", "America/Santiago", "full_time", (("s-002", 3, None), ("s-001", 2, None)), [SDAY]),
    ("agt-012", "Valentina Soto", "America/Santiago", "full_time", (("s-002", 4, None), ("s-003", 2, None)), [SDAY]),
    ("agt-013", "Diego Pinto", "America/Santiago", "part_time", (("s-001", 3, None),), [((1, 2, 3, 4), "12:00", 6)]),
    ("agt-014", "Javiera Munoz", "America/Santiago", "full_time", (("s-002", 5, None),), [SAFT]),
    ("agt-015", "Matias Vega", "America/Santiago", "full_time", (("s-003", 2, None), ("s-001", 3, "2026-08-17")), [SAFT]),
    ("agt-016", "Fernanda Diaz", "America/Santiago", "full_time", (("s-001", 4, None), ("s-003", 3, None)),
     [((5, 6), "10:00", 8), ((0, 1, 2), "12:00", 8)]),
    ("agt-017", "Nicolas Reyes", "America/Santiago", "contractor", (("s-002", 3, None),),
     [((5, 6), "18:00", 8), ((0, 1, 2), "14:00", 8)]),
    ("agt-018", "Paula Campos", "America/Santiago", "full_time", (("s-003", 4, None), ("s-002", 2, None)),
     [((5, 6), "18:00", 8), ((0, 1, 2), "14:00", 8)]),
)
SKILLS_EFFECTIVE_DEFAULT = "2026-01-01T00:00:00Z"
LEAVE_DAYS_PER_AGENT = 2
DST_DAY_INDEXES = (60, 61, 62)           # 2026-09-04 .. 2026-09-06: no leave around the DST weekend
DST_WEEKEND = {"zone": "America/Santiago", "saturday": "2026-09-05", "sunday": "2026-09-06",
               "transition_utc": "2026-09-06T04:00:00Z", "offset_before": "-04:00", "offset_after": "-03:00"}


def default_parameters(seed: int) -> dict[str, Any]:
    return {
        "seed": seed, "window": [START.isoformat(), END.isoformat()], "days": NDAYS, "weeks": WEEKS, "as_of": AS_OF,
        "training_weeks": [1, TRAIN_WEEKS], "holdout_weeks": [TRAIN_WEEKS + 1, WEEKS],
        "holdout_intensity_uplift": HOLDOUT_UPLIFT, "tickets_target": TICKETS_TARGET,
        "arrival_realisation": "first attempt (0, 1, ...) with holdout/training rate within 1.5 points of +20 %",
        "queues": {q[0]: {"name": q[1], "priority_policy": q[2], "skill": q[3], "share": QUEUE_SHARE[i]}
                   for i, q in enumerate(QUEUES)},
        "priority_mix": {q: list(m) for q, m in PRIORITY_MIX.items()}, "sla_minutes": {p: list(v) for p, v in SLA.items()},
        "channels": dict(zip(CHANNELS, CHANNEL_SHARE)), "abandonable_channels": list(ABANDONABLE),
        "patience_mean_minutes": {c: s // 60 for c, s in PATIENCE_MEAN_SECONDS.items()}, "p_impatient": P_IMPATIENT,
        "p_transfer": P_TRANSFER, "p_reopen": P_REOPEN, "p_pause": P_PAUSE, "p_survey_invited": P_INVITE,
        "survey_response_base": RESPONSE_BASE, "survey_poor_experience_factor": POOR_EXPERIENCE_RESPONSE, "break_minutes": BREAK_SECONDS // 60,
        "agents": len(AGENT_DEFS), "agent_zones": ["Europe/Berlin", "America/Santiago"],
        "dst_weekend": DST_WEEKEND, "leave_days_per_agent": LEAVE_DAYS_PER_AGENT,
        "hour_weight_utc": list(HOUR_WEIGHT), "day_weight_mon_to_sun": list(DAY_WEIGHT),
        "monday_surge_hours_utc": {str(h): m for h, m in MONDAY_SURGE.items()},
        "handling_median_minutes": {f"{q}/{p}": list(v) for (q, p), v in sorted(HANDLING.items())},
        "technical_p1": {"routine": list(TECH_P1_ROUTINE), "escalated_median_sigma": list(TECH_P1_ESCALATED),
                         "major_incident_share": P_MAJOR, "major_handling_median_sigma": list(MAJOR_HANDLING),
                         "major_wait_seconds": list(MAJOR_GAP)},
        "proficiency_factor": {str(k): v for k, v in PROFICIENCY_FACTOR.items()},
        "customers": CUSTOMERS_N, "size_budget_bytes": SIZE_BUDGET,
        "volume_cap": ("one event row per state change and no separate 'queued' row at creation (created carries the "
                       "queue); a human reply is recorded once per ticket; about 4,800 tickets so the 12 files stay "
                       "under 5 MB (a row costs about 150 bytes with every field present)"),
    }


# ---------------------------------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------------------------------

def iso(t: int) -> str:
    return (T0 + timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%SZ")


def secs(dt: datetime) -> int:
    return int((dt.astimezone(UTC) - T0).total_seconds())


def parse_z(stamp: str) -> int:
    return secs(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC))


def poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def pick(rng: random.Random, items: tuple, weights: tuple) -> Any:
    x, acc = rng.random() * sum(weights), 0.0
    for it, w in zip(items, weights):
        acc += w
        if x < acc:
            return it
    return items[-1]


def nearest_rank(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[max(math.ceil(p * len(s)), 1) - 1]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def local_instant(day: date, hhmm: str, plus_hours: int, zone: str) -> tuple[int, int]:
    """(start, end) seconds of a shift declared in LOCAL wall-clock time: start HH:MM on ``day``, ending ``plus_hours``
    of wall-clock later (naive local arithmetic, then each end converted by zoneinfo). Across a daylight-saving jump the
    real elapsed time differs from the declared hours (the declared 18:00-02:00 night shift is 7 h on 2026-09-05)."""
    h, m = int(hhmm[:2]), int(hhmm[3:])
    zi = ZoneInfo(zone)
    start_local = datetime.combine(day, dtime(h, m))
    end_local = start_local + timedelta(hours=plus_hours)
    return secs(start_local.replace(tzinfo=zi)), secs(end_local.replace(tzinfo=zi))


def lognorm_minutes(rng: random.Random, median: float, sigma: float) -> float:
    return rng.lognormvariate(math.log(median), sigma)


def draw_handling(rng: random.Random, queue: str, prio: str) -> int:
    """Base handling seconds (proficiency 3) of one cycle."""
    if queue == "q-002" and prio == "P1":
        share, med, sig = TECH_P1_ROUTINE
        minutes = lognorm_minutes(rng, med, sig) if rng.random() < share else lognorm_minutes(rng, *TECH_P1_ESCALATED)
    else:
        minutes = lognorm_minutes(rng, *HANDLING[(queue, prio)])
    return int(min(max(minutes * 60, HANDLING_MIN), HANDLING_MAX))


# ---------------------------------------------------------------------------------------------------------------------
# the generator
# ---------------------------------------------------------------------------------------------------------------------

class Generator:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        master = random.Random(seed)
        self.rs = {name: random.Random(master.getrandbits(64)) for name in STREAMS}
        self.counter = itertools.count()

    # ---- roster ------------------------------------------------------------------------------------------------------
    def setup_roster(self) -> None:
        r = self.rs["roster"]
        self.agents: list[dict] = []
        for i, (aid, name, zone, emp, skills, patterns) in enumerate(AGENT_DEFS):
            sk = {s: (p, parse_z(eff + "T00:00:00Z") if eff else -10 ** 9) for s, p, eff in skills}
            self.agents.append({"id": aid, "ix": i, "name": name, "zone": zone, "emp": emp, "skills": sk,
                                "skill_rows": skills, "patterns": patterns, "shifts": [], "ptr": 0, "busy": 0,
                                "resumes": []})
        self.shifts: list[dict] = []
        for a in self.agents:
            works = [d for d in range(NDAYS) if any((START + timedelta(days=d)).weekday() in days
                                                    for days, _, _ in a["patterns"])]
            cand = [d for d in works if (START + timedelta(days=d)).weekday() in (1, 2, 3, 4)
                    and d not in DST_DAY_INDEXES]
            leave = set(r.sample(cand, LEAVE_DAYS_PER_AGENT))
            a["leave"] = sorted(leave)
            for d in range(NDAYS):
                day = START + timedelta(days=d)
                if d in leave:
                    continue
                for days, hhmm, hours in a["patterns"]:
                    if day.weekday() not in days:
                        continue
                    s, e = local_instant(day, hhmm, hours, a["zone"])
                    planned = s + int(round((e - s) * r.uniform(0.42, 0.55) / 900.0)) * 900
                    sh = {"agent": a["ix"], "start": s, "end": e, "date": day, "hhmm": hhmm, "hours": hours,
                          "bp": planned, "taken": False, "bstart": None, "recorded_end": e, "recorded_break": 30}
                    a["shifts"].append(sh)
                    self.shifts.append(sh)
            a["shifts"].sort(key=lambda x: x["start"])
        self.shifts.sort(key=lambda x: (x["start"], x["agent"]))
        for n, sh in enumerate(self.shifts, 1):
            sh["id"] = f"sh-{n:04d}"

    # ---- customers ---------------------------------------------------------------------------------------------------
    def setup_customers(self) -> None:
        r = self.rs["customers"]
        self.customers: list[dict] = []
        weights = []
        for i in range(CUSTOMERS_N):
            seg = pick(r, tuple(s for s, _ in SEGMENTS), tuple(w for _, w in SEGMENTS))
            zone = pick(r, tuple(z for z, _ in CUSTOMER_ZONES), tuple(w for _, w in CUSTOMER_ZONES))
            created = parse_z("2025-06-01T00:00:00Z") + r.randrange(0, 400 * 86400 // 60) * 60
            created = min(created, -86400)
            self.customers.append({"customer_id": f"c-{i + 1:04d}", "segment": seg, "timezone": zone,
                                   "created_at": iso(created), "synthetic": True})
            weights.append(min(r.paretovariate(1.5), 12.0))
        self.cust_cum = list(itertools.accumulate(weights))

    # ---- arrivals ----------------------------------------------------------------------------------------------------
    def hour_weight(self, dow: int, hour: int) -> float:
        w = HOUR_WEIGHT[hour] * DAY_WEIGHT[dow]
        return w * (MONDAY_SURGE.get(hour, 1.0) if dow == 0 else 1.0)

    def weekly_weight(self) -> float:
        return sum(self.hour_weight(d, h) for d in range(7) for h in range(24))

    def arrival_times(self) -> list[int]:
        """Poisson counts per hour from the hour-of-week intensity, holdout weeks x HOLDOUT_UPLIFT. The realisation is
        the first of a fixed series of attempts (attempt 0, 1, ...) whose holdout/training rate ratio is within 1.5
        points of +20 %: Poisson noise alone moves it by about 4 points at this volume, and the uplift is designed."""
        base = self.rs["arrivals"].getrandbits(64)
        scale = TICKETS_TARGET / (self.weekly_weight() * (TRAIN_WEEKS + (WEEKS - TRAIN_WEEKS) * HOLDOUT_UPLIFT))
        self.intensity_scale = scale
        for attempt in range(200):
            r = random.Random(base + attempt)
            out: list[int] = []
            for d in range(NDAYS):
                dow, week = d % 7, d // 7
                up = HOLDOUT_UPLIFT if week >= TRAIN_WEEKS else 1.0
                for h in range(24):
                    n = poisson(r, scale * self.hour_weight(dow, h) * up)
                    b = d * 86400 + h * 3600
                    out.extend(b + o for o in sorted(r.randrange(3600) for _ in range(n)))
            tr = sum(1 for t in out if t < TRAIN_END) / TRAIN_WEEKS
            ho = sum(1 for t in out if t >= TRAIN_END) / (WEEKS - TRAIN_WEEKS)
            if abs((ho - tr) / tr - (HOLDOUT_UPLIFT - 1)) <= 0.015:
                self.arrival_attempt = attempt
                return out
        raise RuntimeError("no arrival realisation within tolerance")

    # ---- tickets (all random draws made up front, in arrival order) --------------------------------------------------
    def make_tickets(self, arrivals: list[int]) -> None:
        r = self.rs["tickets"]
        self.tks: list[dict] = []
        for ix, t in enumerate(arrivals):
            q = pick(r, QUEUE_IDS, QUEUE_SHARE)
            prio = pick(r, PRIORITIES, PRIORITY_MIX[q])
            chan = pick(r, CHANNELS, CHANNEL_SHARE)
            cust = bisect.bisect_left(self.cust_cum, r.random() * self.cust_cum[-1])
            tk = {"major": False, "ix": ix, "created": t, "q0": q, "queue": q, "prio": prio, "channel": chan, "cust": cust,
                  "H0": draw_handling(r, q, prio), "fr": [r.random() + 0.4 for _ in range(4)],
                  "gaps": [r.randrange(600, 3000) for _ in range(3)], "pause": r.random() < P_PAUSE,
                  "reply": r.randrange(60, 240), "ack": r.randrange(3, 10), "events": [], "replied": False,
                  "state": "new", "cycle": 0, "patience": None, "xfer": None, "reopen": None, "survey": None}
            if q == "q-002" and prio == "P1" and r.random() < P_MAJOR:
                tk["major"], tk["pause"] = True, True
                tk["H0"] = int(min(max(lognorm_minutes(r, *MAJOR_HANDLING) * 60, 40 * 60), HANDLING_MAX))
                tk["gaps"][0] = r.randrange(*MAJOR_GAP)
            if chan in ABANDONABLE and r.random() < P_IMPATIENT:
                tk["patience"] = max(120, int(r.expovariate(1.0 / PATIENCE_MEAN_SECONDS[chan])))
            if r.random() < P_TRANSFER and not tk["major"]:
                others = [x for x in QUEUE_IDS if x != q]
                nq = pick(r, tuple(others), (0.6, 0.4) if q != "q-002" else (0.5, 0.5))
                tk["xfer"] = {"after": r.randrange(300, 720), "queue": nq, "H": int(draw_handling(r, nq, prio) * 0.8)}
            fq = tk["xfer"]["queue"] if tk["xfer"] else q
            if r.random() < P_REOPEN:
                tk["reopen"] = {"delay": r.randrange(2 * 3600, 30 * 3600), "H": int(draw_handling(r, fq, prio) * 0.6)}
            tk["survey"] = {"invite": r.random(), "resp": r.random(), "z": r.gauss(0, 0.9),
                            "inv_delay": r.randrange(60, 3600), "resp_delay": 120 + int(r.expovariate(1 / (9 * 3600)))}
            self.tks.append(tk)

    # ---- the simulation ----------------------------------------------------------------------------------------------
    @staticmethod
    def plan(H: int, fr: list[float], gaps: list[int], pause: bool) -> tuple[list[int], list[int]]:
        n = max(1, math.ceil(H / MAX_CHUNK))
        if pause and H >= 900:
            n = max(n, 2)
        n = min(n, 4)
        total = sum(fr[:n])
        return [max(180, int(H * w / total)) for w in fr[:n]], gaps[: n - 1]

    def factor(self, a: dict, queue: str, t: int) -> float:
        prof, eff = a["skills"][QUEUE_SKILL[queue]]
        return PROFICIENCY_FACTOR[prof]

    def qualified(self, a: dict, queue: str, t: int) -> bool:
        s = a["skills"].get(QUEUE_SKILL[queue])
        return s is not None and s[1] <= t

    def emit(self, tk: dict, t: int, etype: str, actor: str | None, queue: str | None, agent: str | None) -> None:
        tk["events"].append((t, etype, actor, queue, agent))

    def simulate(self, arrivals: list[int]) -> None:
        dr = self.rs["dispatch"]
        heap: list[tuple] = []
        seq = self.counter
        waiting: dict[str, list[tuple]] = {q: [] for q in QUEUE_IDS}
        pending: list[tuple] = []          # paused work whose customer or engineering wait is over: (ready, ticket, chunks, gaps, queue, owner)
        items: dict[int, dict] = {}
        self.stats_sim = {"breaks_missed": 0, "dispatched": 0}

        def push(t: int, kind: str, payload: Any = None) -> None:
            heapq.heappush(heap, (t, next(seq), kind, payload))

        for tk in self.tks:
            push(tk["created"], "arrive", tk["ix"])
        for a in self.agents:
            for sh in a["shifts"]:
                push(sh["start"], "wake", None)
                push(sh["bp"], "wake", None)

        def enqueue(tk: dict, kind: str, key_t: int, H: int, xfer: dict | None) -> None:
            q = tk["queue"]
            it = {"id": next(seq), "tix": tk["ix"], "kind": kind, "queue": q, "H": H, "xfer": xfer, "gone": False}
            items[it["id"]] = it
            rank = PRIORITIES.index(tk["prio"]) if QUEUE_POLICY[q] == "fifo_within_priority" else 1
            bisect.insort(waiting[q], (rank, key_t, it["id"]))
            tk["item"] = it["id"]

        def item_plan(it: dict, a: dict, s: int) -> tuple[list[int], list[int], bool]:
            tk = self.tks[it["tix"]]
            if it["xfer"] is not None:
                return [it["xfer"]["after"]], [], True
            H = max(240, int(it["H"] * self.factor(a, it["queue"], s)))
            chunks, gaps = self.plan(H, tk["fr"], tk["gaps"], tk["pause"])
            return chunks, gaps, False

        def in_shift_need(chunks: list[int], gaps: list[int]) -> int:
            """Seconds the agent needs inside the shift: the first chunk, plus later chunks and short pauses; a long
            pause (waiting for engineering) lets the work resume on a later shift."""
            need = chunks[0]
            for i, g in enumerate(gaps):
                if g > LONG_GAP:
                    break
                need += g + chunks[i + 1]
            return need

        def current_shift(a: dict, t: int) -> dict | None:
            shifts = a["shifts"]
            while a["ptr"] < len(shifts) and shifts[a["ptr"]]["end"] <= t:
                a["ptr"] += 1
            if a["ptr"] < len(shifts) and shifts[a["ptr"]]["start"] <= t:
                return shifts[a["ptr"]]
            return None

        def run_chunks(a: dict, tk: dict, s: int, chunks: list[int], gaps: list[int], xfer: dict | None,
                       resumed: bool) -> None:
            aid = a["id"]
            self.emit(tk, s, "resumed" if resumed else "service_started", aid, None, aid)
            if not tk["replied"] and not resumed:
                rd = min(tk["reply"], max(30, chunks[0] // 2))
                self.emit(tk, s + rd, "replied_human", aid, None, aid)
                tk["replied"] = True
            end = s + chunks[0]
            a["busy"] = end
            push(end, "wake", None)
            tk["state"] = "in_service"
            if xfer is not None:
                self.emit(tk, end, "transferred", aid, xfer["queue"], None)
                tk["queue"] = xfer["queue"]
                tk["state"] = "queued"
                push(end, "xfer", tk["ix"])
            elif len(chunks) > 1:
                self.emit(tk, end, "paused", aid, None, aid)
                tk["state"] = "waiting_customer"
                push(end + gaps[0], "resume", (tk["ix"], a["ix"], chunks[1:], gaps[1:], tk["queue"]))
            else:
                self.emit(tk, end, "resolved", aid, None, aid)
                tk["state"] = "resolved"
                tk["resolved_at"] = end
                if tk["reopen"] is not None and tk["cycle"] == 0:
                    push(end + tk["reopen"]["delay"], "reopen", tk["ix"])

        def dispatch(t: int) -> None:
            order = sorted(self.agents, key=lambda x: (x["busy"], x["ix"]))
            for a in order:
                if a["busy"] > t:
                    continue
                sh = current_shift(a, t)
                if sh is not None:
                    ready = sorted(x for x in pending if x[0] <= t and t + 5 + x[2][0] <= sh["end"]
                                   and (x[5] == a["ix"] or (t - x[0] >= HANDOVER_AFTER and self.qualified(a, x[4], t)
                                                            and current_shift(self.agents[x[5]], t) is None)))
                    if ready:
                        x = ready[0]
                        pending.remove(x)
                        tk = self.tks[x[1]]
                        run_chunks(a, tk, t + 5 + dr.randrange(26), x[2], x[3], None, True)
                        continue
                if sh is None:
                    continue
                if not sh["taken"] and t >= sh["bp"]:
                    if t + BREAK_SECONDS <= sh["end"]:
                        sh["taken"], sh["bstart"] = True, t
                        a["busy"] = t + BREAK_SECONDS
                        push(a["busy"], "wake", None)
                    else:
                        sh["taken"] = True
                        self.stats_sim["breaks_missed"] += 1
                    continue
                lag = 10 + dr.randrange(51)
                s = t + lag
                best = None
                for q in QUEUE_IDS:
                    if not self.qualified(a, q, t):
                        continue
                    lst = waiting[q]
                    scanned = 0
                    for k, ent in enumerate(lst):
                        it = items[ent[2]]
                        if it["gone"]:
                            continue
                        scanned += 1
                        if scanned > 60:
                            break
                        chunks, gaps, xf = item_plan(it, a, s)
                        need = in_shift_need(chunks, gaps) + FIT_MARGIN + (0 if sh["taken"] else BREAK_SECONDS)
                        if s + need <= sh["end"]:
                            if best is None or ent < best[0]:
                                best = (ent, q, k)
                            break
                if best is None:
                    continue
                ent, q, k = best
                waiting[q].pop(k)
                it = items[ent[2]]
                chunks, gaps, xf = item_plan(it, a, s)
                tk = self.tks[it["tix"]]
                tk["item"] = None
                self.stats_sim["dispatched"] += 1
                run_chunks(a, tk, s, chunks, gaps, it["xfer"], False)

        while heap:
            t, _, kind, payload = heapq.heappop(heap)
            if t >= CUT:
                break
            if kind == "arrive":
                tk = self.tks[payload]
                self.emit(tk, t, "created", None, tk["q0"], None)
                self.emit(tk, t + tk["ack"], "acknowledged_bot", "bot-001", None, None)
                tk["state"] = "queued"
                enqueue(tk, "new", t, tk["H0"], tk["xfer"])
                if tk["patience"] is not None:
                    push(t + tk["patience"], "abandon", tk["ix"])
            elif kind == "abandon":
                tk = self.tks[payload]
                if tk["state"] == "queued" and tk["cycle"] == 0 and tk.get("item") is not None:
                    items[tk["item"]]["gone"] = True
                    for q in QUEUE_IDS:
                        waiting[q] = [e for e in waiting[q] if e[2] != tk["item"]]
                    tk["item"] = None
                    tk["state"] = "abandoned"
                    self.emit(tk, t, "abandoned", None, None, None)
            elif kind == "xfer":
                tk = self.tks[payload]
                enqueue(tk, "xfer", t, tk["xfer"]["H"], None)
            elif kind == "resume":
                tix, aix, chunks, gaps, queue = payload
                pending.append((t, tix, chunks, gaps, queue, aix))
            elif kind == "reopen":
                tk = self.tks[payload]
                tk["cycle"] = 1
                tk["state"] = "queued"
                tk["xfer"] = None
                self.emit(tk, t, "reopened", None, None, None)
                self.emit(tk, t + 1, "queued", None, tk["queue"], None)
                enqueue(tk, "reopen", t + 1, tk["reopen"]["H"], None)
            dispatch(t)
        for tk in self.tks:
            tk["events"] = [e for e in tk["events"] if e[0] < CUT]
        # breaks that were taken, per shift, are the published shift_breaks; leftovers are counted
        self.stats_sim["breaks_taken"] = sum(1 for s in self.shifts if s["bstart"] is not None)
        self.stats_sim["shifts"] = len(self.shifts)

    # ---- intervals and agent availability (used by the injections and the statistics) --------------------------------
    @staticmethod
    def intervals_of(tk: dict) -> list[tuple[int, int, str, str]]:
        """(start, end, agent_id, queue_id) of each service interval; the queue is the one the ticket was in at the start."""
        out, open_iv, cur = [], None, tk["q0"]
        for t, etype, actor, queue, agent in sorted(tk["events"], key=lambda e: e[0]):
            if etype in ("service_started", "resumed") and open_iv is None:
                open_iv = (t, agent, cur)
            elif etype in ("paused", "transferred", "resolved", "abandoned") and open_iv is not None:
                out.append((open_iv[0], t, open_iv[1], open_iv[2]))
                open_iv = None
            if etype in ("transferred", "queued") and queue is not None:
                cur = queue
        if open_iv is not None:
            out.append((open_iv[0], CUT, open_iv[1], open_iv[2]))
        return out

    def agent_intervals(self) -> dict[str, list[tuple[int, int, int]]]:
        by: dict[str, list[tuple[int, int, int]]] = {a["id"]: [] for a in self.agents}
        for tk in self.tks:
            for s, e, aid, _q in self.intervals_of(tk):
                by[aid].append((s, e, tk["ix"]))
        for v in by.values():
            v.sort()
        return by

    def agent_free(self, a: dict, s: int, e: int, by: dict, margin: int = 120, ignore: int | None = None) -> bool:
        """Agent ``a`` is in a shift over [s - margin, e + margin], not on a break and not serving anyone."""
        inside = any(sh["start"] <= s - margin and e + margin <= sh["end"] for sh in a["shifts"])
        if not inside:
            return False
        for sh in a["shifts"]:
            if sh["bstart"] is not None and sh["bstart"] < e + margin and s - margin < sh["bstart"] + BREAK_SECONDS:
                return False
        return not any(iv[0] < e + margin and s - margin < iv[1] and iv[2] != ignore for iv in by[a["id"]])

    # ---- ticket views ------------------------------------------------------------------------------------------------
    @staticmethod
    def sorted_events(tk: dict) -> list[tuple]:
        return sorted(tk["events"], key=lambda e: e[0])

    def is_single(self, tk: dict) -> bool:
        types = sorted(e[1] for e in tk["events"])
        return types == sorted(["created", "acknowledged_bot", "service_started", "replied_human", "resolved"])

    def final_resolved(self, tk: dict) -> int | None:
        last_res = last_reopen = None
        for t, etype, *_ in self.sorted_events(tk):
            if etype == "resolved":
                last_res = t
            elif etype == "reopened":
                last_reopen = t
        if last_res is None or (last_reopen is not None and last_reopen > last_res):
            return None
        return last_res

    def first_human(self, tk: dict) -> int | None:
        times = [e[0] for e in tk["events"] if e[1] == "replied_human" and not (e[2] or "").startswith("bot-")]
        return min(times) if times else None

    def reassign(self, tk: dict, new_id: str) -> None:
        old = next(e[4] for e in tk["events"] if e[1] == "service_started")
        tk["events"] = [(t, ty, new_id if ac == old else ac, q, new_id if ag == old else ag)
                        for t, ty, ac, q, ag in tk["events"]]

    # ---- injected defects (INJ-01..09) -------------------------------------------------------------------------------
    def inject(self) -> None:
        r = self.rs["inject"]
        tks = self.tks
        self.inj: dict[str, Any] = {}
        used: set[int] = set()
        week = lambda tk: tk["created"] // (7 * 86400)  # noqa: E731
        singles = [tk for tk in tks if self.is_single(tk) and 1 <= week(tk) <= 9]
        by = self.agent_intervals()

        # INJ-03: one billing, one technical and one onboarding ticket served by an agent without the queue's skill
        order = list(singles)
        r.shuffle(order)
        picked03 = []
        for q in QUEUE_IDS:
            for tk in order:
                if tk["ix"] in used or tk["q0"] != q:
                    continue
                s, e, aid, _ = self.intervals_of(tk)[0]
                cands = [a for a in self.agents if a["id"] != aid and not self.qualified(a, q, s)]
                r.shuffle(cands)
                hit = next((a for a in cands if self.agent_free(a, s, e, by)), None)
                if hit is not None:
                    self.reassign(tk, hit["id"])
                    used.add(tk["ix"])
                    picked03.append((tk["ix"], hit["id"]))
                    break
        by = self.agent_intervals()
        self.inj["INJ-03"] = {"picked": picked03}

        # INJ-04: a second ticket assigned to an agent who is already serving another one
        ivs = sorted(((self.intervals_of(tk)[0], tk) for tk in singles if tk["ix"] not in used),
                     key=lambda x: x[0][0])
        pairs = []
        for i, ((s1, e1, a1, q1), x) in enumerate(ivs):
            if e1 - s1 < 25 * 60:
                continue
            agent1 = next(a for a in self.agents if a["id"] == a1)
            for (s2, e2, a2, q2), y in ivs[i + 1:]:
                if s2 > e1 - 300:
                    break
                if s2 >= s1 + 300 and a2 != a1 and e2 - s2 >= 300 and self.qualified(agent1, q2, s2):
                    pairs.append((x["ix"], y["ix"], a1))
        r.shuffle(pairs)
        picked04, seen = [], set()
        for xi, yi, a1 in pairs:
            if xi in seen or yi in seen or len(picked04) >= 3:
                continue
            seen |= {xi, yi}
            picked04.append((xi, yi, a1))
        for xi, yi, a1 in picked04:
            self.reassign(tks[yi], a1)
            used |= {xi, yi}
        self.inj["INJ-04"] = {"picked": picked04}

        # INJ-06: a transferred ticket whose arrival was reset to the transfer instant
        xf = [tk for tk in tks if tk["ix"] not in used and self.final_resolved(tk) is not None and 1 <= week(tk) <= 10
              and any(e[1] == "transferred" for e in tk["events"])]
        picked06 = r.sample(xf, 3)
        for tk in picked06:
            tk["row_created"] = min(e[0] for e in tk["events"] if e[1] == "transferred")
            used.add(tk["ix"])
        self.inj["INJ-06"] = {"picked": [tk["ix"] for tk in picked06]}

        # INJ-01: a bot message typed as a human reply, on tickets whose real first reply came much later
        slow = [tk for tk in tks if tk["ix"] not in used and week(tk) <= 5 and self.first_human(tk) is not None
                and self.first_human(tk) - tk["created"] >= 90 * 60]
        picked01 = r.sample(slow, 4)
        for tk in picked01:
            at = tk["created"] + tk["ack"] + 40
            tk["events"].append((at, "replied_human", "bot-001", None, None))
            tk["bot_human_at"] = at
            used.add(tk["ix"])
        self.inj["INJ-01"] = {"picked": [tk["ix"] for tk in picked01]}

        # INJ-05 and INJ-08: shift rows
        picked05 = []
        for aid in ("agt-002", "agt-008", "agt-014"):
            a = next(x for x in self.agents if x["id"] == aid)
            cands = [sh for sh in a["shifts"] if sh["hours"] == 8 and sh["bstart"] is not None
                     and 2 <= (sh["start"] // (7 * 86400)) <= 5]
            sh = r.choice(cands)
            sh["recorded_break"] = 0
            picked05.append(sh)
        self.inj["INJ-05"] = {"shifts": picked05}
        a18 = next(x for x in self.agents if x["id"] == "agt-018")
        sh18 = next(sh for sh in a18["shifts"] if sh["date"] == date(2026, 9, 5) and sh["hhmm"] == "18:00")
        sh18["recorded_end"] = sh18["start"] + sh18["hours"] * 3600      # naive wall-clock arithmetic: 480, not 420
        self.inj["INJ-08"] = {"shift": sh18}

        # INJ-02: a reopen recorded as a brand new ticket from a brand new customer record
        by = self.agent_intervals()
        orig = [tk for tk in singles if tk["ix"] not in used and tk["channel"] in ("email", "web_form")
                and self.final_resolved(tk) is not None and tk["xfer"] is None and tk["reopen"] is None
                and 2 <= week(tk) <= 9]
        picked02 = []
        for tk in r.sample(orig, 12):
            if len(picked02) >= 4:
                break
            res = self.final_resolved(tk)
            c = res + r.randrange(2 * 3600, 36 * 3600)
            q = tk["q0"]
            ok = None
            for _ in range(60):
                s0 = c + 20 + r.randrange(70)
                Hs = draw_handling(r, q, tk["prio"])
                agents = [a for a in self.agents if self.qualified(a, q, s0)]
                r.shuffle(agents)
                for a in agents:
                    dur = max(240, int(Hs * PROFICIENCY_FACTOR[a["skills"][QUEUE_SKILL[q]][0]]))
                    if self.agent_free(a, s0, s0 + dur, by):
                        ok = (a, s0, dur)
                        break
                if ok:
                    break
                c += 600
            if ok is None:
                continue
            a, s0, dur = ok
            old = self.customers[tk["cust"]]
            cust = {"customer_id": f"c-{len(self.customers) + 1:04d}", "segment": old["segment"],
                    "timezone": old["timezone"], "created_at": iso(c), "synthetic": True}
            self.customers.append(cust)
            ix = len(self.tks)
            rep = s0 + min(r.randrange(60, 240), max(30, dur // 2))
            sv = {"invite": r.random(), "resp": r.random(), "z": r.gauss(0, 0.9),
                  "inv_delay": r.randrange(60, 3600), "resp_delay": 120 + int(r.expovariate(1 / (9 * 3600)))}
            dup = {"major": False, "ix": ix, "created": c, "q0": q, "queue": q, "prio": tk["prio"],
                   "channel": tk["channel"], "cust": len(self.customers) - 1, "xfer": None, "reopen": None,
                   "state": "resolved", "cycle": 0, "survey": sv, "dup_of": tk["ix"], "ack": 6, "reply": 0,
                   "events": [(c, "created", None, q, None), (c + 6, "acknowledged_bot", "bot-001", None, None),
                              (s0, "service_started", a["id"], None, a["id"]), (rep, "replied_human", a["id"], None, a["id"]),
                              (s0 + dur, "resolved", a["id"], None, a["id"])]}
            self.tks.append(dup)
            by = self.agent_intervals()
            used |= {tk["ix"], ix}
            picked02.append((tk["ix"], ix))
        self.inj["INJ-02"] = {"picked": picked02}

    # ---- surveys -----------------------------------------------------------------------------------------------------
    def make_surveys(self, order: list[dict]) -> tuple[list[dict], dict[str, dict]]:
        rows, latent = [], {}
        for tk in order:
            res = self.final_resolved(tk)
            if res is None or tk["survey"]["invite"] >= P_INVITE:
                continue
            sv = tk["survey"]
            inv = res + sv["inv_delay"]
            if inv >= CUT:
                continue
            fr = self.first_human(tk)
            sla_fr, sla_res = SLA[tk["prio"]]
            mu = 4.3
            if fr is not None and (fr - tk["created"]) / 60 > sla_fr:
                mu -= 0.9
            if (res - tk["created"]) / 60 > sla_res:
                mu -= 0.8
            if any(e[1] == "reopened" for e in tk["events"]):
                mu -= 0.5
            if any(e[1] == "transferred" for e in tk["events"]):
                mu -= 0.4
            score = int(min(5, max(1, round(mu + sv["z"]))))
            poor = mu < 4.3                       # a target missed, a reopen or a transfer
            p = RESPONSE_BASE * (1.0 if score >= 4 else 0.55 if score == 3 else 0.35) * (POOR_EXPERIENCE_RESPONSE if poor else 1.0)
            resp_at = inv + sv["resp_delay"]
            answered = sv["resp"] < p and resp_at < CUT
            sid = f"sv-{len(rows) + 1:04d}"
            rows.append({"survey_id": sid, "ticket_id": tk["id"], "response_at": iso(resp_at) if answered else None,
                         "score": score if answered else None, "invited_at": iso(inv)})
            latent[sid] = {"score": score, "answered": answered, "poor": poor}
        return rows, latent

    # ---- assemble the entity files -----------------------------------------------------------------------------------
    def assemble(self) -> dict[str, Any]:
        tks = self.tks
        order = sorted(tks, key=lambda tk: (tk["created"], tk["ix"]))
        for n, tk in enumerate(order, 1):
            tk["id"] = f"t-{n:04d}"
        ents: dict[str, list[dict]] = {}
        ents["customers"] = sorted(self.customers, key=lambda c: c["customer_id"])
        ents["queues"] = [{"queue_id": q, "queue_name": n, "priority_policy": pol, "calendar_id": "cal-001",
                           "active": True} for q, n, pol, _ in QUEUES]
        ents["tickets"] = [{"ticket_id": tk["id"], "customer_id": self.customers[tk["cust"]]["customer_id"],
                            "queue_id": tk["queue"], "priority": tk["prio"],
                            "created_at": iso(tk.get("row_created", tk["created"])), "channel": tk["channel"]}
                           for tk in order]
        # event ids follow the order in which the log RECEIVED each event (a few replies and pauses arrive late)
        lr = self.rs["late"]
        pend = []
        for tk in order:
            for seq, (t, ety, ac, q, ag) in enumerate(self.sorted_events(tk)):
                rec = t
                if ety in ("replied_human", "paused", "resumed") and lr.random() < 0.01:
                    rec = t + lr.randrange(1800, 6 * 3600)
                pend.append((rec, tk["id"], seq, tk["ix"], t, ety, ac, q, ag))
        pend.sort()
        events, self.event_of = [], {}
        for n, (rec, tid, seq, ix, t, ety, ac, q, ag) in enumerate(pend, 1):
            eid = f"e-{n:05d}"
            events.append({"event_id": eid, "ticket_id": tid, "event_type": ety, "occurred_at": iso(t), "actor_id": ac,
                           "queue_id": q, "agent_id": ag})
            self.event_of[(ix, t, ety, ac)] = eid
        ents["ticket_events"] = events
        ents["agents"] = [{"agent_id": a["id"], "agent_name": a["name"], "timezone": a["zone"],
                           "employment_type": a["emp"], "active": True, "max_concurrent": 1} for a in self.agents]
        ents["skills"] = [{"skill_id": s, "skill_name": n, "description": d, "active": True,
                           "created_at": SKILLS_EFFECTIVE_DEFAULT} for s, n, d in SKILLS]
        ents["agent_skills"] = []
        for a in self.agents:
            for sid, prof, eff in a["skill_rows"]:
                ents["agent_skills"].append({"agent_skill_id": f"as-{len(ents['agent_skills']) + 1:03d}",
                                             "agent_id": a["id"], "skill_id": sid, "proficiency": prof,
                                             "effective_from": f"{eff}T00:00:00Z" if eff else SKILLS_EFFECTIVE_DEFAULT})
        ents["queue_skills"] = [{"queue_id": q, "skill_id": sk} for q, _, _, sk in QUEUES]
        ents["shifts"] = [{"shift_id": sh["id"], "agent_id": self.agents[sh["agent"]]["id"], "starts_at": iso(sh["start"]),
                           "ends_at": iso(sh["recorded_end"]), "break_minutes": sh["recorded_break"]}
                          for sh in self.shifts]
        ents["shift_breaks"] = []
        for sh in self.shifts:
            if sh["bstart"] is not None:
                ents["shift_breaks"].append({"break_id": f"br-{len(ents['shift_breaks']) + 1:04d}", "shift_id": sh["id"],
                                             "agent_id": self.agents[sh["agent"]]["id"], "starts_at": iso(sh["bstart"]),
                                             "ends_at": iso(sh["bstart"] + BREAK_SECONDS)})
        ents["sla_policies"] = [{"sla_policy_id": f"sla-{p}", "priority": p, "first_response_minutes": v[0],
                                 "resolution_minutes": v[1], "calendar_id": "cal-001"} for p, v in SLA.items()]
        ents["surveys"], self.latent = self.make_surveys(order)
        self.order = order
        ents["simulation_runs"] = self.simulation_runs(order)
        self.ents = ents
        stats, designed = self.analysis(order)
        injections = self.injection_manifest()
        events_doc = self.injection_events()
        return {"entities": ents, "stats": stats, "designed": designed, "injections": injections,
                "events": events_doc, "parameters": default_parameters(self.seed)}

    # ---- simulation runs (a pure-queue picture of the technical queue at the Monday 09-11 UTC bind) ------------------
    def simulation_runs(self, order: list[dict]) -> list[dict]:
        train = [tk for tk in order if tk["created"] < TRAIN_END and tk["q0"] == "q-002"]
        hours = TRAIN_WEEKS * 2
        mon = [tk for tk in train if (tk["created"] // 86400) % 7 == 0 and 9 <= (tk["created"] // 3600) % 24 <= 10]
        rate = round(len(mon) / hours, 2)
        counts = []
        for w in range(TRAIN_WEEKS):
            at = w * 7 * 86400 + 10 * 3600
            counts.append(sum(1 for a in self.agents if self.qualified(a, "q-002", at)
                              and any(sh["start"] <= at < sh["end"] for sh in a["shifts"])))
        agents = max(1, round(sum(counts) / len(counts)))
        handling = [sum(e - s for s, e, _, _ in self.intervals_of(tk)) / 60 for tk in train
                    if self.final_resolved(tk) is not None]
        service = round(sum(handling) / len(handling), 1)
        mix = {p: round(sum(1 for tk in train if tk["prio"] == p) / len(train), 2) for p in PRIORITIES}
        base = {"agents": agents, "service_minutes": service, "arrival_rate_per_hour": rate, "priority_mix": mix,
                "service": "exponential", "discipline": "fifo_within_priority"}
        self.sim_params = {"agents": agents, "rate": rate, "service_minutes": service, "mix": mix,
                           "technical_agents_on_shift_by_training_monday": counts}
        runs = [("sim-001", "baseline-v1", base), ("sim-002", "plus-one-agent-v1", {**base, "agents": agents + 1}),
                ("sim-003", "holdout-intensity-v1", {**base, "arrival_rate_per_hour": round(rate * HOLDOUT_UPLIFT, 2)})]
        return [{"simulation_id": sid, "seed": self.seed, "warmup_minutes": 120, "policy_version": pv,
                 "horizon_minutes": 720, "config": cfg} for sid, pv, cfg in runs]

    # ---- statistics and designed relationships (own implementation, no domain import) --------------------------------
    def analysis(self, order: list[dict]) -> tuple[dict[str, Any], list[str]]:
        n = len(order)
        completed = [tk for tk in order if self.final_resolved(tk) is not None]
        res_min = lambda tk: (self.final_resolved(tk) - tk["created"]) / 60  # noqa: E731
        fr_min = lambda tk: (self.first_human(tk) - tk["created"]) / 60 if self.first_human(tk) is not None else None  # noqa: E731
        tech1 = [tk for tk in completed if tk["queue"] == "q-002" and tk["prio"] == "P1" and "dup_of" not in tk]
        tr = [res_min(tk) for tk in tech1]
        tf = [fr_min(tk) for tk in tech1 if fr_min(tk) is not None]
        p90 = nearest_rank(tr, 0.9)
        # arrival-to-capacity by hour of week (capacity = shift overlap minus the break pro rata, true shifts)
        arr: dict[tuple[int, int], int] = {}
        for tk in order:
            k = ((tk["created"] // 86400) % 7, (tk["created"] // 3600) % 24)
            arr[k] = arr.get(k, 0) + 1
        cap: dict[tuple[int, int], float] = {}
        for sh in self.shifts:
            length = sh["end"] - sh["start"]
            f = (length - BREAK_SECONDS) / length
            t = sh["start"]
            while t < sh["end"]:
                h0 = t // 3600 * 3600
                nxt = min(h0 + 3600, sh["end"])
                k = ((h0 // 86400) % 7, (h0 // 3600) % 24)
                cap[k] = cap.get(k, 0.0) + (nxt - t) / 3600 * f
                t = nxt
        blocks = {}
        for d in range(7):
            for h in range(24):
                ks = [(d, h), ((d + (h + 1) // 24) % 7, (h + 1) % 24)]
                c = sum(cap.get(k, 0.0) for k in ks)
                if c >= 24:
                    blocks[(d, h)] = sum(arr.get(k, 0) for k in ks) / c
        best = sorted(blocks.items(), key=lambda x: -x[1])
        mon_block = blocks.get((0, 9))
        # proficiency and speed
        per: dict[tuple[int, str], list[float]] = {}
        cell: dict[tuple[str, str], list[float]] = {}
        for tk in order:
            for s, e, aid, q in self.intervals_of(tk):
                a = next(x for x in self.agents if x["id"] == aid)
                if e == CUT or QUEUE_SKILL[q] not in a["skills"]:   # open interval, or an INJ-03 mis-assignment
                    continue
                per.setdefault((a["skills"][QUEUE_SKILL[q]][0], q + tk["prio"]), []).append((e - s) / 60)
                cell.setdefault((q, tk["prio"]), []).append((e - s) / 60)
        hi = [m for (p, _), v in per.items() if p >= 4 for m in v]
        lo = [m for (p, _), v in per.items() if p < 4 for m in v]
        cellmean = {k: sum(v) / len(v) for k, v in cell.items()}
        norm = lambda sel: [m / cellmean[(c[:5], c[5:])] for (p, c), v in per.items() if sel(p) for m in v]  # noqa: E731
        train = [tk for tk in order if tk["created"] < TRAIN_END]
        hold = [tk for tk in order if tk["created"] >= TRAIN_END]
        tr_rate = len(train) / (TRAIN_WEEKS * 7 * 24)
        ho_rate = len(hold) / ((WEEKS - TRAIN_WEEKS) * 7 * 24)
        invited = len(self.ents["surveys"]) if hasattr(self, "ents") else 0
        survey = self.ents["surveys"]
        answered = [s for s in survey if s["score"] is not None]
        sla_ok = lambda tk: res_min(tk) <= SLA[tk["prio"]][1]  # noqa: E731
        breach = [sv for sv in survey if self.latent[sv["survey_id"]]["poor"]]
        ok_ = [sv for sv in survey if not self.latent[sv["survey_id"]]["poor"]]
        rate = lambda rows: (sum(1 for s in rows if s["score"] is not None) / len(rows)) if rows else None  # noqa: E731
        handling_total = sum(e - s for tk in order for s, e, _, _ in self.intervals_of(tk) if e != CUT) / 3600
        staffed = sum(sh["end"] - sh["start"] - BREAK_SECONDS for sh in self.shifts) / 3600
        by_q = {q: sum(1 for tk in order if tk["q0"] == q) for q in QUEUE_IDS}
        by_p = {p: sum(1 for tk in order if tk["prio"] == p) for p in PRIORITIES}
        n_events = sum(len(tk["events"]) for tk in order)
        stats = {
            "tickets": n, "events": n_events, "events_per_ticket": round(n_events / n, 3),
            "tickets_by_queue": by_q, "tickets_by_priority": by_p,
            "tickets_by_channel": {c: sum(1 for tk in order if tk["channel"] == c) for c in CHANNELS},
            "tickets_per_week": [sum(1 for tk in order if tk["created"] // (7 * 86400) == w) for w in range(WEEKS)],
            "training_arrivals": len(train), "holdout_arrivals": len(hold),
            "training_rate_per_hour": round(tr_rate, 4), "holdout_rate_per_hour": round(ho_rate, 4),
            "holdout_relative_change": round((ho_rate - tr_rate) / tr_rate, 4),
            "transferred_share": round(sum(1 for tk in order if any(e[1] == "transferred" for e in tk["events"])) / n, 4),
            "reopened_share": round(sum(1 for tk in order if any(e[1] == "reopened" for e in tk["events"])) / n, 4),
            "abandoned_share": round(sum(1 for tk in order if any(e[1] == "abandoned" for e in tk["events"])) / n, 4),
            "completed_share": round(len(completed) / n, 4),
            "surveys_invited": len(survey), "survey_invitation_rate": round(len(survey) / max(1, len(completed)), 4),
            "survey_response_rate": round(len(answered) / max(1, len(survey)), 4),
            "csat_among_responders": round(sum(1 for s in answered if s["score"] >= 4) / max(1, len(answered)), 4),
            "csat_latent_all_invited": round(sum(1 for s in survey if self.latent[s["survey_id"]]["score"] >= 4)
                                             / max(1, len(survey)), 4),
            "invited_after_poor_experience": len(breach),
            "response_rate_after_poor_experience": None if rate(breach) is None else round(rate(breach), 4),
            "response_rate_after_good_experience": None if rate(ok_) is None else round(rate(ok_), 4),
            "bot_acknowledgements": sum(1 for tk in order if any(e[1] == "acknowledged_bot" for e in tk["events"])),
            "shifts": len(self.shifts), "breaks_recorded": len(self.ents["shift_breaks"]) if hasattr(self, "ents") else 0,
            "staffed_hours_net_of_breaks": round(staffed, 1), "handling_hours": round(handling_total, 1),
            "occupancy": round(handling_total / staffed, 4),
            "sla_resolution_within_all": round(sum(1 for tk in completed if sla_ok(tk)) / max(1, len(completed)), 4),
            "simulation": self.stats_sim, "simulation_run_parameters": self.sim_params,
            "leave_days": {a["id"]: [(START + timedelta(days=d)).isoformat() for d in a["leave"]] for a in self.agents},
        }
        designed = [
            (f"technical queue P1 resolution has a long tail: n {len(tr)}, mean {mean(tr):.1f} min, P90 {p90:.1f} min "
             f"(nearest rank), P90 / mean {p90 / mean(tr):.2f}; first response mean {mean(tf):.1f} min "
             f"(15 % of technical P1 are major incidents that wait hours for engineering; resolution is measured from "
             f"the original arrival; synthetic)."),
            (f"Monday 09-11 UTC is the capacity bind: arrivals per staffed hour {mon_block:.2f} against "
             f"{best[1][1]:.2f} for the next 2-hour block ({_hour_name(best[1][0])}) and "
             f"{statistics_median([v for v in blocks.values()]):.2f} for the median block (staffed = shift minus the "
             f"break pro rata; blocks with fewer than 24 staffed hours excluded; surge multiplier "
             f"{MONDAY_SURGE[9]} on those two hours; synthetic)."),
            (f"proficiency >= 4 resolves faster: mean handling {mean(hi):.1f} min (n {len(hi)}) against "
             f"{mean(lo):.1f} min (n {len(lo)}) for proficiency <= 3; relative to the queue and priority mean "
             f"{mean(norm(lambda p: p >= 4)):.3f} against {mean(norm(lambda p: p < 4)):.3f} (handling factors "
             f"{PROFICIENCY_FACTOR}; synthetic)."),
            (f"the holdout (weeks 9-12) arrives {stats['holdout_relative_change'] * 100:+.1f} % harder than the training "
             f"window (weeks 1-8): {stats['holdout_rate_per_hour']:.3f} against {stats['training_rate_per_hour']:.3f} "
             f"tickets per hour; designed uplift {int(round((HOLDOUT_UPLIFT - 1) * 100))} % and disclosed (synthetic)."),
        ]
        stats["designed"] = {
            "technical_p1": {"n": len(tr), "mean_resolution_minutes": round(mean(tr), 2),
                             "p90_resolution_minutes": round(p90, 2), "p90_over_mean": round(p90 / mean(tr), 3),
                             "mean_first_response_minutes": round(mean(tf), 2),
                             "p90_first_response_minutes": round(nearest_rank(tf, 0.9), 2)},
            "monday_block": {"hour_utc": "Mon 09-11", "ratio": round(mon_block, 4),
                             "next_best": {"block": _hour_name(best[1][0]), "ratio": round(best[1][1], 4)},
                             "top": _hour_name(best[0][0]),
                             "median_block_ratio": round(statistics_median(list(blocks.values())), 4)},
            "proficiency": {"mean_handling_ge4_minutes": round(mean(hi), 2), "mean_handling_le3_minutes": round(mean(lo), 2),
                            "normalised_ge4": round(mean(norm(lambda p: p >= 4)), 4),
                            "normalised_le3": round(mean(norm(lambda p: p < 4)), 4)},
        }
        return stats, designed

    # ---- build -------------------------------------------------------------------------------------------------------
    def build(self) -> dict[str, Any]:
        self.setup_roster()
        self.setup_customers()
        arrivals = self.arrival_times()
        self.make_tickets(arrivals)
        self.simulate(arrivals)
        self.inject()
        return self.assemble()

    # ---- injection manifest ------------------------------------------------------------------------------------------
    def _rejections(self, tix: int, reason: str) -> list[dict]:
        """Direct and dependent rejections of one whole ticket (D-05): the ticket, its events, its survey."""
        tid = self.tks[tix]["id"]
        out = [{"entity": "tickets", "id": tid, "reason_code": reason}]
        out += [{"entity": "ticket_events", "id": e["event_id"], "reason_code": "TICKET_REJECTED"}
                for e in self.ents["ticket_events"] if e["ticket_id"] == tid]
        out += [{"entity": "surveys", "id": sv["survey_id"], "reason_code": "TICKET_REJECTED"}
                for sv in self.ents["surveys"] if sv["ticket_id"] == tid]
        return sorted(out, key=lambda r: (r["entity"], r["id"]))

    def injection_manifest(self) -> dict[str, Any]:
        tid = lambda ix: self.tks[ix]["id"]  # noqa: E731
        aid = lambda ix: self.agents[ix]["id"]  # noqa: E731
        out: list[dict] = []
        ids01 = []
        for ix in self.inj["INJ-01"]["picked"]:
            tk = self.tks[ix]
            ids01.append(self.event_of[(ix, tk["bot_human_at"], "replied_human", "bot-001")])
        out.append({
            "id": "INJ-01", "test": "P04-TEST-01", "entity": "ticket_events", "location": "entity_files+events",
            "record_ids": ids01, "tickets": [tid(ix) for ix in self.inj["INJ-01"]["picked"]],
            "description": ("4 bot messages typed as a human reply (event_type replied_human, actor bot-001, 40 s after "
                            "the creation acknowledgement) on tickets whose real first human reply came 90 minutes or "
                            "more later; kept in the entity file so the domain must refuse them."),
            "expected_handling": ("ingest rejects each event alone with BOT_AS_HUMAN_REPLY (the ticket stays); "
                                  "first response is measured from the real human reply, never from the bot."),
            "expected_rejections": [{"entity": "ticket_events", "id": e, "reason_code": "BOT_AS_HUMAN_REPLY"} for e in ids01]})
        pairs = self.inj["INJ-02"]["picked"]
        out.append({
            "id": "INJ-02", "test": "P04-TEST-02", "entity": "tickets", "location": "entity_files+events",
            "record_ids": [x for o, d in pairs for x in (tid(o), tid(d), self.customers[self.tks[d]["cust"]]["customer_id"])],
            "detail": [{"original_ticket": tid(o), "duplicate_ticket": tid(d),
                        "duplicate_customer": self.customers[self.tks[d]["cust"]]["customer_id"],
                        "original_customer": self.customers[self.tks[o]["cust"]]["customer_id"],
                        "duplicate_created_at": iso(self.tks[d]["created"])} for o, d in pairs],
            "description": ("4 customer follow-ups on resolved tickets were recorded as a NEW ticket from a NEW customer "
                            "record (created at the same instant as the ticket, same segment, timezone, queue, priority "
                            "and channel as the original's customer) instead of a reopened event on the original."),
            "expected_handling": ("the domain cannot see the link (no field carries it): both tickets count as arrivals "
                                  "and completions and the original's reopen is missing from disclosures.reopened_tickets; "
                                  "the manifest is the analyst check. The correct recording is EV-02 (C06 reopen-ticket: "
                                  "one customer contact, reopen_count 1, prior cycle linked).")})
        out.append({
            "id": "INJ-03", "test": "P04-TEST-03", "entity": "tickets", "location": "entity_files+events",
            "record_ids": [tid(ix) for ix, _ in self.inj["INJ-03"]["picked"]],
            "detail": [{"ticket": tid(ix), "queue_id": self.tks[ix]["q0"], "agent_id": a} for ix, a in self.inj["INJ-03"]["picked"]],
            "description": ("3 tickets (one per queue) were served by an agent who does not hold the queue's skill at the "
                            "start instant (a billing ticket by an onboarding-only agent, and so on)."),
            "expected_handling": ("ingest rejects each whole ticket with AGENT_NOT_QUALIFIED; its events and survey carry "
                                  "TICKET_REJECTED (D-05); EV-03 shows C03 start-service refusing the same assignment."),
            "expected_rejections": [r for ix, _ in self.inj["INJ-03"]["picked"] for r in self._rejections(ix, "AGENT_NOT_QUALIFIED")]})
        out.append({
            "id": "INJ-04", "test": "P04-TEST-04", "entity": "tickets", "location": "entity_files+events",
            "record_ids": [tid(yi) for _, yi, _ in self.inj["INJ-04"]["picked"]],
            "detail": [{"first_ticket": tid(xi), "rejected_ticket": tid(yi), "agent_id": a, "max_concurrent": 1}
                       for xi, yi, a in self.inj["INJ-04"]["picked"]],
            "description": ("3 tickets were assigned to an agent who was already serving another ticket (max_concurrent "
                            "1): the second service starts while the first is still open."),
            "expected_handling": ("ingest keeps the earlier start and rejects the later ticket with CONCURRENCY_EXCEEDED "
                                  "(events and survey TICKET_REJECTED); the rejected ticket occupies nobody."),
            "expected_rejections": [r for _, yi, _ in self.inj["INJ-04"]["picked"] for r in self._rejections(yi, "CONCURRENCY_EXCEEDED")]})
        shifts05 = self.inj["INJ-05"]["shifts"]
        out.append({
            "id": "INJ-05", "test": "P04-TEST-05", "entity": "shifts", "location": "entity_files+events",
            "record_ids": [sh["id"] for sh in shifts05],
            "detail": [{"shift_id": sh["id"], "agent_id": aid(sh["agent"]), "recorded_break_minutes": 0,
                        "break_recorded_in_shift_breaks": next(b["break_id"] for b in self.ents["shift_breaks"]
                                                               if b["shift_id"] == sh["id"])} for sh in shifts05],
            "description": ("3 full 8-hour shifts carry break_minutes 0 although a 30-minute break was taken "
                            "(shift_breaks has it): the break is counted as available time."),
            "expected_handling": ("the shift rows are accepted as given (the domain deducts the declared break only); "
                                  "staffed time is overstated by 30 minutes per shift and occupancy understated; a "
                                  "shift with a recorded break and break_minutes 0 is the reconciliation check; "
                                  "EV-05 shows C03 start-service refusing an instant inside the recorded break "
                                  "(AGENT_ON_BREAK).")})
        out.append({
            "id": "INJ-06", "test": "P04-TEST-08", "entity": "tickets", "location": "entity_files+events",
            "record_ids": [tid(ix) for ix in self.inj["INJ-06"]["picked"]],
            "description": ("3 transferred tickets whose ticket row has created_at set to the transfer instant (the "
                            "arrival was reset) while the first event still carries the original arrival."),
            "expected_handling": ("ingest rejects each whole ticket with TRANSFER_RESETS_ARRIVAL (events and survey "
                                  "TICKET_REJECTED); a correct transfer keeps created_at and restarts only the per-queue wait."),
            "expected_rejections": [r for ix in self.inj["INJ-06"]["picked"] for r in self._rejections(ix, "TRANSFER_RESETS_ARRIVAL")]})
        out.append({
            "id": "INJ-07", "test": "P04-TEST-09", "entity": "simulation_runs", "location": "events",
            "record_ids": ["sim-ev07-cold"],
            "description": ("A simulation run that includes its warm-up: the baseline run sim-001 declares 120 warm-up "
                            "minutes, the replayed run declares 0 with the same seed and config, so the empty-system "
                            "start is counted in the statistics."),
            "expected_handling": ("C08 accepts the run (0 warm-up is legal) but statistics.warmup_excluded is 0 and the "
                                  "mean wait is lower than the warmed run's (cold-start bias); results are labelled "
                                  "simulated estimates and must show the declared warm-up.")})
        sh18 = self.inj["INJ-08"]["shift"]
        ok_ids = [sh["id"] for a in self.agents if a["id"] == "agt-017" for sh in a["shifts"] if sh["date"] == date(2026, 9, 5)
                  and sh["hhmm"] == "18:00"]
        out.append({
            "id": "INJ-08", "test": "P04-TEST-07", "entity": "shifts", "location": "entity_files",
            "record_ids": [sh18["id"]],
            "detail": {"weekend": DST_WEEKEND, "agent_id": "agt-018", "shift_id": sh18["id"],
                       "declared_local": "Sat 2026-09-05 18:00 to Sun 2026-09-06 02:00 America/Santiago",
                       "recorded_utc": [iso(sh18["start"]), iso(sh18["recorded_end"])],
                       "correct_utc": [iso(sh18["start"]), iso(sh18["end"])],
                       "recorded_minutes": (sh18["recorded_end"] - sh18["start"]) // 60,
                       "correct_minutes": (sh18["end"] - sh18["start"]) // 60,
                       "correct_crossing_shifts": ok_ids},
            "description": ("America/Santiago moves from UTC-04:00 to UTC-03:00 at 2026-09-06T04:00:00Z. The night crew "
                            "(agt-017 and agt-018) works Sat 18:00 to Sun 02:00 local; the real shift is 420 minutes "
                            "(22:00Z to 05:00Z). agt-018's row was built with naive wall-clock arithmetic (+8 h): it ends "
                            "at 06:00Z, 480 minutes. agt-017's row on the same night is correct."),
            "expected_handling": ("the domain stores shifts as UTC instants (D-02) and cannot know the roster: staffed time "
                                  "is overstated by 60 minutes; detection recomputes the end from the agent's zone "
                                  "(timeutil.local_to_utc) and compares; the agent's Santiago shifts move one hour "
                                  "earlier in UTC from 2026-09-06 on (week 10 weekdays and week 9 Sunday).")})
        breach_noresp = [sv["survey_id"] for sv in self.ents["surveys"] if self.latent[sv["survey_id"]]["poor"]
                         and sv["score"] is None]
        out.append({
            "id": "INJ-09", "test": "P04-TEST-11", "entity": "surveys", "location": "entity_files",
            "record_ids": breach_noresp[:30], "record_count": len(breach_noresp),
            "description": ("Survey nonresponse is not random: customers who missed a first-response or resolution target, "
                            "were transferred or were reopened respond far less often (x0.6, and x0.55 / x0.35 for "
                            "scores 3 and below), so CSAT among responders is higher than among all invited. record_ids "
                            "lists the first 30 unanswered invitations after a poor experience; record_count is all of them."),
            "expected_handling": ("the domain computes CSAT over valid responses and discloses invited, valid, nonresponse "
                                  "and the note 'nonresponse is not random'; the realised numbers are in "
                                  "manifest.stats (csat_among_responders against csat_latent_all_invited).")})
        return {"list": out}

    # ---- replay-only events ------------------------------------------------------------------------------------------
    def injection_events(self) -> list[dict]:
        version = f"sf-{self.seed}-{DATE_TAG}"
        sup = {"X-Actor-Id": "sup-1", "X-Actor-Role": "supervisor"}
        ana = {"X-Actor-Id": "ana-1", "X-Actor-Role": "analyst"}

        def env(n: str, inp: dict) -> dict:
            return {"request_id": f"ev-{n}", "dataset_version": version, "idempotency_key": f"ev-{n}", "input": inp}

        ents, ev = self.ents, []
        evrows = {e["event_id"]: e for e in ents["ticket_events"]}
        tk_rows = {t["ticket_id"]: t for t in ents["tickets"]}

        def rows_of(tid: str) -> dict:
            return {"tickets": [tk_rows[tid]], "ticket_events": [e for e in ents["ticket_events"] if e["ticket_id"] == tid],
                    "surveys": [s for s in ents["surveys"] if s["ticket_id"] == tid]}

        # EV-01: re-ingest the bot message typed as human
        ix = self.inj["INJ-01"]["picked"][0]
        tk = self.tks[ix]
        eid = self.event_of[(ix, tk["bot_human_at"], "replied_human", "bot-001")]
        ev.append({"event_id": "EV-01", "injection": "INJ-01", "command": "ingest-ticket-events", "requires": [],
                   "steps": [{"command": "ingest-ticket-events", "headers": ana,
                              "input": env("01", {"ticket_events": [evrows[eid]]})}],
                   "expected_status": 200, "expected_reason": "BOT_AS_HUMAN_REPLY",
                   "expected": {"rejected_records": [{"entity": "ticket_events", "id": eid, "reason_code": "BOT_AS_HUMAN_REPLY"}]},
                   "expected_handling": "the event alone is rejected (automation never makes a first response); nothing is stored"})
        # EV-02: the correct recording of a reopen
        o, d = self.inj["INJ-02"]["picked"][0]
        ev.append({"event_id": "EV-02", "injection": "INJ-02", "command": "reopen-ticket", "requires": [],
                   "steps": [{"command": "reopen-ticket", "headers": sup,
                              "input": env("02", {"ticket_id": self.tks[o]["id"], "occurred_at": iso(self.tks[d]["created"])})}],
                   "expected_status": 200, "expected_reason": None,
                   "expected": {"state": "reopened", "reopen_count": 1, "customer_contacts": 1, "prior_cycle": 0, "cycle": 1},
                   "expected_handling": "one customer contact: the follow-up reopens the original ticket and links the prior cycle"})

        def start_chain(n: str, tid: str, q: str, agent: str, s: int, tag: str) -> list[dict]:
            return [
                {"command": "ingest-ticket-events", "headers": ana, "input": env(f"{n}a", {
                    "tickets": [{"ticket_id": tid, "customer_id": "c-0001", "queue_id": q, "priority": "P2",
                                 "created_at": iso(s - 900), "channel": "email"}],
                    "ticket_events": [{"event_id": f"e-{tag}-1", "ticket_id": tid, "event_type": "created",
                                       "occurred_at": iso(s - 900), "actor_id": None, "queue_id": q, "agent_id": None}]})},
                {"command": "assign-queue", "headers": sup, "input": env(f"{n}b", {"ticket_id": tid, "queue_id": q,
                                                                                       "occurred_at": iso(s - 600)})},
                {"command": "start-service", "headers": sup, "input": env(f"{n}c", {"ticket_id": tid, "agent_id": agent,
                                                                                         "occurred_at": iso(s)})}]

        # EV-03: start-service by an agent without the queue's skill (agt-003 holds onboarding only)
        a3 = next(a for a in self.agents if a["id"] == "agt-003")
        sh3 = next(sh for sh in a3["shifts"] if sh["date"] >= date(2026, 7, 27))
        s3 = sh3["start"] + 3600
        ev.append({"event_id": "EV-03", "injection": "INJ-03", "command": "start-service", "requires": [],
                   "steps": start_chain("03", "t-ev03", "q-001", "agt-003", s3, "ev03"),
                   "expected_status": 422, "expected_reason": "AGENT_NOT_QUALIFIED",
                   "expected_handling": "refused: agt-003 lacks the billing skill; the ticket stays queued"})
        # EV-04: re-ingest a rejected concurrent ticket
        yi = self.inj["INJ-04"]["picked"][0][1]
        r4 = rows_of(self.tks[yi]["id"])
        ev.append({"event_id": "EV-04", "injection": "INJ-04", "command": "ingest-ticket-events", "requires": [],
                   "steps": [{"command": "ingest-ticket-events", "headers": ana, "input": env("04", r4)}],
                   "expected_status": 200, "expected_reason": "CONCURRENCY_EXCEEDED",
                   "expected": {"rejected_records": self._rejections(yi, "CONCURRENCY_EXCEEDED")},
                   "expected_handling": "the later of the two overlapping services is rejected with its events and survey"})
        # EV-05: start-service inside a recorded break (needs shift_breaks.json loaded)
        sh5 = self.inj["INJ-05"]["shifts"][0]
        br = next(b for b in ents["shift_breaks"] if b["shift_id"] == sh5["id"])
        s5 = parse_z(br["starts_at"]) + 300
        agent5 = self.agents[sh5["agent"]]["id"]
        ev.append({"event_id": "EV-05", "injection": "INJ-05", "command": "start-service", "requires": ["shift_breaks"],
                   "shift_breaks_rows": [br],
                   "steps": start_chain("05", "t-ev05", "q-001", agent5, s5, "ev05"),
                   "expected_status": 422, "expected_reason": "AGENT_ON_BREAK",
                   "expected_handling": "refused: a break is not capacity; the shift row's break_minutes 0 does not hide the recorded break"})
        # EV-06: re-ingest a transferred ticket whose arrival was reset
        xi = self.inj["INJ-06"]["picked"][0]
        r6 = rows_of(self.tks[xi]["id"])
        ev.append({"event_id": "EV-06", "injection": "INJ-06", "command": "ingest-ticket-events", "requires": [],
                   "steps": [{"command": "ingest-ticket-events", "headers": ana, "input": env("06", r6)}],
                   "expected_status": 200, "expected_reason": "TRANSFER_RESETS_ARRIVAL",
                   "expected": {"rejected_records": self._rejections(xi, "TRANSFER_RESETS_ARRIVAL")},
                   "expected_handling": "the whole ticket is rejected: a transfer never moves the arrival"})
        # EV-07: a run with the warm-up included
        base = self.ents["simulation_runs"][0]
        ev.append({"event_id": "EV-07", "injection": "INJ-07", "command": "run-simulation", "requires": [],
                   "steps": [{"command": "run-simulation", "headers": sup, "input": env("07", {
                       "simulation_id": "sim-ev07-cold", "seed": base["seed"], "warmup_minutes": 0,
                       "horizon_minutes": base["horizon_minutes"], "policy_version": "baseline-v1-cold-start",
                       "config": base["config"], "replications": 1})}],
                   "expected_status": 200, "expected_reason": None,
                   "expected": {"statistics.warmup_excluded": 0, "mean_wait_lower_than": base["simulation_id"]},
                   "expected_handling": "accepted but flagged: warmup_excluded is 0 and the mean wait is biased low against the warmed run"})
        return ev


def _hour_name(key: tuple[int, int]) -> str:
    d, h = key
    return f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[d]} {h:02d}-{(h + 2) % 24:02d}"


def statistics_median(v: list[float]) -> float:
    s = sorted(v)
    return s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2


# ---------------------------------------------------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------------------------------------------------

def canonical_rows(rows: list[dict]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def dataset_hash(entities: dict[str, list[dict]]) -> str:
    h = hashlib.sha256()
    for name in sorted(entities):
        h.update(canonical_rows(entities[name]).encode())
    return h.hexdigest()


def entity_text(name: str, version: str, rows: list[dict]) -> str:
    body = ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return f'{{"entity":{json.dumps(name)},"dataset_version":{json.dumps(version)},"rows":[\n{body}\n]}}\n'


def build(seed: int) -> dict[str, Any]:
    return Generator(seed).build()


def write_golden(out: Path) -> None:
    """The hand-derived fixture in the published shape, for ``?dataset=golden`` (same layout as SupplyScope)."""
    fx = APP_ROOT / "tests" / "fixtures" / "golden"
    inputs = json.loads((fx / "inputs.json").read_text())
    hashes = json.loads((fx / "HASHES.json").read_text())
    gdir = out / "golden"
    gdir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in ENTITIES:
        rows = inputs.get(name, [])
        counts[name] = len(rows)
        (gdir / f"{name}.json").write_text(entity_text(name, "golden-v1", rows))
    (gdir / "expected.json").write_text((fx / "expected.json").read_text())
    manifest = {
        "contract_version": CONTRACT_VERSION, "dataset_hash": hashes["sha256"]["inputs.json"],
        "dataset_version": "golden-v1", "generated_at": "2026-10-26T00:00:00Z",
        "generator": {"name": "tests/fixtures/golden (hand-derived, no generator)", "seed": 0, "parameters": {}},
        "designed_relationships": [], "fixture_id": "serviceflow-golden-v1",
        "window_start": inputs["window_start"], "window_end": inputs["window_end"],
        "backlog_cutoffs": inputs["backlog_cutoffs"], "abandonable_channels": inputs["abandonable_channels"],
        "expected": "expected.json", "row_counts": counts,
    }
    (gdir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def write_all(seed: int, out: Path, data_dir: Path) -> dict[str, Any]:
    built = build(seed)
    ents = built["entities"]
    version = f"sf-{seed}-{DATE_TAG}"
    dhash = dataset_hash(ents)
    out.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ENTITIES:
        (out / f"{name}.json").write_text(entity_text(name, version, ents[name]))
    inj_manifest = {"dataset_version": version, "dataset_hash": dhash, "seed": seed, "contract_version": CONTRACT_VERSION,
                    "injections": built["injections"]["list"], "designed_relationships": built["designed"],
                    "events_file": "data/injection-events.json"}
    inj_text = json.dumps(inj_manifest, indent=2, sort_keys=True) + "\n"
    (data_dir / "injection-manifest.json").write_text(inj_text)
    (out / "injection-manifest.json").write_text(inj_text)
    (data_dir / "injection-events.json").write_text(json.dumps(
        {"dataset_version": version, "events": built["events"]}, indent=2, sort_keys=True) + "\n")
    manifest = {
        "dataset_version": version, "dataset_hash": dhash,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contract_version": CONTRACT_VERSION,
        "generator": {"name": "generate.py", "seed": seed, "parameters": built["parameters"]},
        "row_counts": {name: len(ents[name]) for name in ENTITIES},
        "designed_relationships": built["designed"],
        "injection_manifest": "injection-manifest.json",
        "stats": built["stats"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_golden(out)
    return manifest


def seed_columns() -> dict[str, tuple[str, ...]]:
    """data/seed.py COLUMNS without importing psycopg (the file is parsed, not executed)."""
    tree = ast.parse((APP_ROOT / "data" / "seed.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "COLUMNS":
            return ast.literal_eval(node.value)
    raise RuntimeError("COLUMNS not found in data/seed.py")


def shape_check(seed: int) -> int:
    golden = json.loads((APP_ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
    columns = seed_columns()
    columns["shift_breaks"] = SHIFT_BREAK_COLUMNS
    ents = build(seed)["entities"]
    bad = 0
    for name in ENTITIES:
        want = set(columns.get(name, ()))
        if name in golden and golden[name]:
            if set(golden[name][0]) != want and name in columns:
                print(f"NOTE {name}: fixture fields {sorted(golden[name][0])} differ from COLUMNS {sorted(want)}")
            want = set(golden[name][0])
        if name == "simulation_runs":
            want = set(golden[name][0])
        for row in ents[name]:
            if set(row) != want:
                print(f"SHAPE MISMATCH {name}: {sorted(set(row) ^ want)}")
                bad += 1
                break
        else:
            print(f"ok {name}: {sorted(want)}")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=APP_ROOT / "web" / "public" / "data")
    ap.add_argument("--data-dir", type=Path, default=APP_ROOT / "data",
                    help="where injection-manifest.json and injection-events.json go")
    ap.add_argument("--profile", choices=("default", "golden-shape-check"), default="default")
    args = ap.parse_args(argv)
    if args.profile == "golden-shape-check":
        return shape_check(args.seed)
    t0 = time.perf_counter()
    m = write_all(args.seed, args.out, args.data_dir)
    total = sum(p.stat().st_size for p in args.out.glob("*.json"))
    print(json.dumps({"dataset_version": m["dataset_version"], "dataset_hash": m["dataset_hash"],
                      "row_counts": m["row_counts"], "bytes": total,
                      "elapsed_seconds": round(time.perf_counter() - t0, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
