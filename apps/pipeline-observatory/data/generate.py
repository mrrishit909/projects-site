#!/usr/bin/env python3
"""Pipeline Observatory synthetic data generator (P08-WORK-03, docs/data-generator.md).

Standard library only. A master seed hands one named child stream to each purpose (sha256 of ``seed/name``, so adding a purpose never
shifts another); every probability is parts per million and every draw is ``randrange``; instants are integer epoch seconds; money is integer
cents rendered as 2-place decimal strings; no float is used or written. Same seed, same bytes.

The WORLD is built in memory: 6 sources, about 1,300 batches with about 40,000 raw records, hourly runs with tasks, attempts and quality results,
publications, incidents and backfills. The domain (``domain/pipeline_observatory``, imported lazily) then computes every number the manifest
states from those rows; the generator keeps its own tally of what it constructed and ``tests/test_generator.py`` compares the two.
What is PUBLISHED under ``web/public/data`` stays under the 5 MB cap: all entities except ``raw_records``, which is a sample of whole batches
(at most 2,000 rows), plus ``batch_summaries`` that carry the per-batch counts of every raw record.

    python data/generate.py                                  # -> web/public/data
    python data/generate.py --out /tmp/out --seed 20261026
    python data/generate.py --full-inputs /tmp/full.json     # the complete world (40,000 raw rows) as one inputs object (not committed)
"""
from __future__ import annotations

import argparse
import bisect
import functools
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
VERSION_TAG = "po"
CONTRACT_VERSION = 1
SIZE_CAP = 5_000_000
SAMPLE_CAP = 2_000

E0 = int(datetime(2026, 8, 10, tzinfo=UTC).timestamp())           # first instant of the window
AS_OF_S = int(datetime(2026, 10, 5, tzinfo=UTC).timestamp())      # as_of and cutoff
N_DAYS = 56                                                       # 2026-08-10 .. 2026-10-04
N_TICKS = N_DAYS * 24
H, D = 3600, 86400
AS_OF = "2026-10-05T00:00:00Z"

PURPOSES = ("emission", "batches", "rows", "fetch", "runs", "failures", "backfills", "models", "injections", "sample", "timing")

# --- scenario parameters, fixed BEFORE the first run (see DISCLOSURES) ---------------------------------------------------------------
STALE_SOURCE, STALE_FROM = "src-refunds", int(datetime(2026, 10, 2, tzinfo=UTC).timestamp())
STALE_REPLAY_ROWS = 14
SCHEMA_SOURCE, SCHEMA_FROM, SCHEMA_VERSION = "src-payments", int(datetime(2026, 9, 15, tzinfo=UTC).timestamp()), "2"
SCHEMA_BUMP_DELAY_S = 2_240                                       # the operator bumps the expected version 37 minutes after the refused page
RATE_LIMITED_SOURCE, RATE_LIMIT_PPM, RETRY_AFTER_CHOICES = "src-shipments", 125_000, (30, 60, 90, 120)
LOOP_SOURCE, LOOP_SLOT = "src-web-events", datetime(2026, 9, 2, 18, tzinfo=UTC)
LATE_SOURCE, LATE_SLOT, LATE_N = "src-orders", datetime(2026, 9, 18, 16, tzinfo=UTC), 9
KEYLESS_SLOT = ("src-orders", datetime(2026, 8, 27, 8, tzinfo=UTC))
DELETE_SLOT = ("src-orders", datetime(2026, 9, 22, 8, tzinfo=UTC), datetime(2026, 9, 22, 12, tzinfo=UTC))
LEAK_SLOT = ("src-payments", datetime(2026, 9, 9, 10, tzinfo=UTC))   # the crashed ingest whose staged rows leak into the next transform
RESIDUAL_TICK = datetime(2026, 9, 9, 11, tzinfo=UTC)
LEAK_ROWS = 3
N_ABORTED_RANDOM, N_INCIDENTS = 7, 25
FAIL_TYPES = (["transform"] * 9 + ["ingest"] * 3 + ["gate_infra"] * 3 + ["relationships"] * 4)   # + 5 freshness + 1 residual = 25
N_FRESH = 5
PPM = {"neg": 6_000, "missing": 2_500, "invalid": 2_500, "fix": 350_000, "cancel": 4_000, "cancel_dirty": 100_000, "double_delete": 60_000,
       "flaky_run": 70_000}
DRAW_FLAKY_TASKS = ("ingest", "transform", "publish")
RUN_OFFSET_S = 900                                                # a run starts 15 minutes after the hour
SEASON = [30, 25, 20, 20, 25, 40, 60, 90, 110, 125, 135, 140, 145, 140, 135, 130, 130, 125, 120, 115, 100, 80, 60, 40]
WEEKEND_PCT = 85

# id, name, prefix, period h, offset h, minute, events per hour x100, quantity max, unit prices (cents), freshness target (s), frequency text
SOURCES = (
    ("src-orders", "Synthetic orders feed", "ORD", 4, 0, 3, 1260, 8, (450, 799, 1250, 1999, 2450, 4000, 9999), 19_800, "every 4 hours"),
    ("src-payments", "Synthetic payments feed", "PAY", 4, 2, 4, 790, 6, (799, 1250, 1999, 2450, 4000, 8900), 21_600, "every 4 hours"),
    ("src-refunds", "Synthetic refunds feed", "REF", 6, 1, 5, 315, 3, (450, 799, 1250, 1999, 2450), 604_800, "every 6 hours"),
    ("src-shipments", "Synthetic shipments feed", "SHP", 6, 3, 6, 315, 4, (350, 495, 695, 1095), 259_200, "every 6 hours"),
    ("src-inventory", "Synthetic inventory feed", "INV", 24, 5, 7, 131, 20, (120, 250, 480, 975), 259_200, "daily"),
    ("src-web-events", "Synthetic web events feed", "EVT", 12, 6, 8, 131, 12, (10, 25, 50), 216_000, "every 12 hours"),
)
SRC = {s[0]: dict(zip(("id", "name", "prefix", "period", "offset", "minute", "rate", "qmax", "prices", "target", "freq"), s)) for s in SOURCES}
SRC_ORDER = [s[0] for s in SOURCES]
CHANNELS = ("web", "app", "pos", "partner")

MODELS = (   # name, layer, grain, depends_on, definition
    ("stg_orders", "staging", "one row per source_key", [], "select record_id, quantity, unit_price, amount, event_ts from raw_accepted where source_id = 'src-orders'"),
    ("stg_payments", "staging", "one row per source_key", [], "select record_id, quantity, unit_price, amount, event_ts, channel from raw_accepted where source_id = 'src-payments'"),
    ("stg_refunds", "staging", "one row per source_key", [], "select record_id, quantity, unit_price, amount, event_ts from raw_accepted where source_id = 'src-refunds'"),
    ("stg_shipments", "staging", "one row per source_key", [], "select record_id, quantity, unit_price, amount, event_ts from raw_accepted where source_id = 'src-shipments'"),
    ("stg_inventory", "staging", "one row per source_key", [], "select record_id, quantity, unit_price, amount, event_ts from raw_accepted where source_id = 'src-inventory'"),
    ("stg_web_events", "staging", "one row per source_key", [], "select record_id, quantity, unit_price, amount, event_ts from raw_accepted where source_id = 'src-web-events'"),
    ("int_orders_paid", "intermediate", "one row per order and payment", ["stg_orders", "stg_payments", "stg_web_events"],
     "select o.record_id, o.amount, p.amount as paid, w.quantity as sessions from stg_orders o left join stg_payments p on p.event_ts >= o.event_ts left join stg_web_events w on w.event_ts <= o.event_ts"),
    ("int_refunds_netted", "intermediate", "one row per refund", ["stg_refunds", "stg_orders"],
     "select r.record_id, r.amount, o.amount as order_amount from stg_refunds r left join stg_orders o on o.event_ts <= r.event_ts"),
    ("int_fulfilment_lag", "intermediate", "one row per shipment", ["stg_shipments", "stg_orders"],
     "select s.record_id, s.event_ts, o.event_ts as ordered_at from stg_shipments s left join stg_orders o on o.event_ts <= s.event_ts"),
    ("sales_daily", "marts", "one row per record_id and UTC day", ["int_orders_paid", "int_refunds_netted"],
     "select date(event_ts) as day, record_id, amount from int_orders_paid union all select date(event_ts), record_id, amount from int_refunds_netted"),
    ("fulfilment_daily", "marts", "one row per UTC day", ["int_fulfilment_lag"],
     "select date(event_ts) as day, count(*) as shipments, sum(amount) as fees from int_fulfilment_lag group by 1"),
    ("stock_position", "marts", "one row per UTC day", ["stg_inventory"],
     "select date(event_ts) as day, sum(quantity) as units, sum(amount) as value from stg_inventory group by 1"),
)
MODEL_V2 = {"stg_payments": 2}

DISCLOSURES = [
    "Parameters fixed BEFORE the first run, and not changed afterwards to improve an outcome: the six cadences and offsets; src-refunds stops delivering new events at "
    "2026-10-02T00:00:00Z and declares a 7-day freshness target; src-shipments is rate limited on 12.5 % of its fetches (retry-after 30, 60, 90 or 120 s); nine src-orders "
    "events dated 2026-09-17 18:00..23:50 are held back to the batch of 2026-09-18 16:00; src-payments declares schema version 2 from 2026-09-15; 25 runs fail (9 transform, "
    "3 ingest, 3 gate task, 4 relationships, 5 freshness, 1 residual on 2026-09-09 11:00); 15 backfill requests, two of them (bf-006, bf-012) overlapping an earlier one.",
    "OUTCOME-INFORMED choices, all made while building the generator and before the reported run: (a) the first complete world had 38,249 raw rows and 1,263 batches, so the "
    "hourly event rates were raised by about 5 % and the src-shipments cadence went from 8 to 6 hours to come near 40,000 and 1,300; (b) the first freshness targets (orders 4.5 h, "
    "payments 5 h, shipments 24 h, inventory 48 h, web events 30 h) made the gate fail on runs the plan had not designated (thin night windows; whole-day backfilled partitions), so "
    "they were loosened to orders 5.5 h, payments 6 h, shipments 72 h, inventory 72 h, web events 60 h, backfills were limited to one day per partition (refunds up to two), never on "
    "adjacent days of one source, and src-payments was removed from the backfill sources; (c) the backfill request dates were re-spaced after two requests fell after the as-of, the "
    "minimum spacing of the flagged slots went from 3 to 2 days when placement failed, and the margin before the next slot in the freshness scenario went from 2 h to 15 min.",
    "The reported world is the first run of the final code; no draw was repeated or filtered by its value. Every designed relationship came out as designed once the code ran; "
    "none was tuned on the realised value. The realised values are in designed_relationships and are computed by the domain from the rows.",
    "src-refunds declares a freshness target (7 days) looser than its silence on purpose: the gate cannot see the staleness, which is the defect P08-TEST-06 shows. The unexplained "
    "residual of 2026-09-09 is constructed (the candidate table holds the amount of three records of a crashed batch beyond the accepted records); the pipeline records no cause.",
    "The watermark of a publication is the earliest, over all sources, of the end of the window of the latest batch committed before the gate. Late events are therefore rare for "
    "live batches (the designed nine and the corrections of rejected rows) and common for backfills, whose records are weeks old when they arrive; all of them are included in the next publication.",
    "raw_records is a SAMPLE: whole batches (the injected defects and designed relationships first, then a seeded shuffle) until the next batch would pass 2,000 rows. "
    "Every other count comes from batch_summaries, which the domain computed over all raw records. The 5 MB size cap did not bind: the sample is capped at 2,000 rows by the brief.",
    "Quality results sit on the quality_gate task run (five checks per gate); the two tests the transform runs (keys, relationships) are the gate's keys_unique and relationships_intact. "
    "Hardware, cache state and the measured seconds of the processing rate are synthetic values for one batch, not a benchmark.",
    "Review round R8 (docs/contracts.md D-09) changed the world, and the generator was adapted to the rules, not the rules to the world: the gate records two more critical "
    "checks per run (scope_complete: every batch committed from pipeline_runs.scope_from to the run's start is in the candidate; late_events_included: no late event that has "
    "arrived and is in no earlier publication is left out), asked of the domain run by run; the scope of a run now ends at its start (it used to end at the end of the UTC day on "
    "the hour-0 tick); the realised values were recomputed by the domain. A publication's watermark never goes back (C06 refuses it).",
    "Backfill overlap is judged only against requests still requested or running: the two refusals (bf-006 over bf-004, bf-012 over bf-010) were re-timed to two minutes after the "
    "victim's last batch committed, before the run that settled it published, and every request carries requested_at (and settled_at when it settled). A page fetched again in a new "
    "fetch session is a refetch in fetch_log (stale-source polls, replays of a window, backfills re-reading the last committed cursor); the one loop is now a second page of the same "
    "session pointing back at the first cursor. These choices were made after the first run of the previous round's code and are not tuned on any realised value.",
]


# --- helpers --------------------------------------------------------------------------------------------------------------------------
def iso(t: int) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_of(t: int) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")


def at(*a: int) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp())


def canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def cents(c: int) -> str:
    return ("-" if c < 0 else "") + f"{abs(c) // 100}.{abs(c) % 100:02d}"


def stream(seed: int, name: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{seed}/{name}".encode()).hexdigest()[:16], 16))


def ppm(r: random.Random, p: int) -> bool:
    return r.randrange(1_000_000) < p


class Ev:
    """One event a source emits (vendor side). ``ts`` is epoch seconds."""
    __slots__ = ("src", "n", "ts", "key", "qty", "price", "chan", "dirty", "fix_after", "cancel_ts", "hold", "date", "double", "designed")

    def __init__(self, src: str, n: int, ts: int, key: str, qty: int, price: int, chan: str):
        self.src, self.n, self.ts, self.key, self.qty, self.price, self.chan = src, n, ts, key, qty, price, chan
        self.dirty: str | None = None
        self.fix_after = 0
        self.cancel_ts: int | None = None
        self.hold: str | None = None          # 'late' | 'bf' | 'never'
        self.date = day_of(ts)
        self.double = False
        self.designed: str | None = None

    @property
    def amount(self) -> int:
        return self.qty * self.price


def payload_of(e: Ev, schema: str | None, variant: str | None = None) -> dict[str, Any]:
    """The payload a source sends for an event. ``variant``: None (clean) | neg | missing | invalid | keyless."""
    q, up, am, ts = e.qty, cents(e.price), cents(e.amount), iso(e.ts)
    p: dict[str, Any] = {"record_id": e.key, "quantity": q, "unit_price": up, "amount": am, "event_ts": ts}
    if variant == "neg":
        p["quantity"], p["amount"] = -q, cents(-e.amount)
    elif variant == "missing":
        del p[("unit_price", "amount", "quantity")[e.n % 3]]
    elif variant == "invalid":
        kind = e.n % 3
        if kind == 0:
            p["amount"] = am.replace(".", ",")
        elif kind == 1:
            p["event_ts"] = ts.replace("T", " ").replace("Z", "")
        else:
            p["quantity"] = str(q)
    elif variant == "keyless":
        del p["record_id"]
    if schema == SCHEMA_VERSION and e.src == SCHEMA_SOURCE:
        p["channel"] = e.chan
    return p


class Batch:
    """A fetched page: kind live | aborted | replay | schema_q | schema_refetch | backfill."""

    def __init__(self, src: str, kind: str, start: int, rows: list[dict], status: str, cursor_from: str, cursor_to: str):
        self.src, self.kind, self.start, self.rows, self.status = src, kind, start, rows, status
        self.cursor_from, self.cursor_to = cursor_from, cursor_to
        self.commit: int | None = None
        self.schema: str | None = None
        self.window_end: int | None = None
        self.slot: int | None = None
        self.bf: str | None = None
        self.session = ""
        self.batch_id = ""
        self.tags: list[str] = []
        self.cp_cursor = cursor_to


class World:
    def __init__(self, seed: int):
        self.seed = seed
        self.rs = {p: stream(seed, p) for p in PURPOSES}
        self.events: dict[str, list[Ev]] = {}
        self.slots: dict[str, list[dict]] = {}
        self.batches: list[Batch] = []
        self.fetch_log: list[dict] = []
        self.refused_attempts: list[dict] = []
        self.designed: dict[str, Any] = {}
        self.tick_times = [E0 + i * H for i in range(1, N_TICKS)]            # tick 0 (08-10 00:00) has no data yet: 1,343 runs
        self.gate_at: dict[int, int] = {}
        self.run_draw: dict[int, dict] = {}

    # ---------------------------------------------------------------------------------------------------------------- timing draws
    def draw_run_timing(self) -> None:
        r = self.rs["timing"]
        for t in self.tick_times:
            self.run_draw[t] = {"gate": r.randrange(480, 601), "dur": r.randrange(660, 961), "flaky": ppm(r, PPM["flaky_run"]),
                                "flaky_task": DRAW_FLAKY_TASKS[r.randrange(3)], "extra": r.randrange(200, 400), "fail_dur": r.randrange(420, 600)}
            self.gate_at[t] = t + RUN_OFFSET_S + self.run_draw[t]["gate"]
        self.gates_sorted = [self.gate_at[t] for t in self.tick_times]

    # ---------------------------------------------------------------------------------------------------------------- slots
    def plan_slots(self) -> None:
        for sid in SRC_ORDER:
            s = SRC[sid]
            slots = []
            for d in range(N_DAYS):
                for h in range(24):
                    if h % s["period"] == s["offset"] % s["period"]:
                        nominal = E0 + d * D + h * H + s["minute"] * 60
                        if nominal >= E0 + H:
                            slots.append({"nominal": nominal, "delay_to": None})
            self.slots[sid] = slots

    def slot_at(self, sid: str, dt: datetime) -> int:
        base = int(dt.timestamp())
        for i, sl in enumerate(self.slots[sid]):
            if sl["nominal"] // H * H == base:
                return i
        raise KeyError((sid, dt))

    # ---------------------------------------------------------------------------------------------------------------- emission
    def emit(self) -> None:
        r = self.rs["emission"]
        sw = sum(SEASON)
        for sid in SRC_ORDER:
            s = SRC[sid]
            last_end = self.slots[sid][-1]["nominal"] - 90
            evs: list[tuple[int, int]] = []
            for d in range(N_DAYS):
                weekend = datetime.fromtimestamp(E0 + d * D, UTC).weekday() >= 5
                for h in range(24):
                    mean100 = s["rate"] * SEASON[h] * 24 // sw
                    if weekend:
                        mean100 = mean100 * WEEKEND_PCT // 100
                    n = mean100 // 100 + (1 if r.randrange(100) < mean100 % 100 else 0)
                    if n >= 4:
                        n += r.randrange(-1, 2)
                    base = E0 + d * D + h * H
                    for _ in range(n):
                        t = base + r.randrange(1, H)
                        evs.append((t, r.randrange(1 << 30)))
            evs.sort()
            out = []
            for i, (t, salt) in enumerate(x for x in evs if x[0] <= last_end):
                qty = 1 + salt % s["qmax"]
                price = s["prices"][(salt >> 8) % len(s["prices"])]
                out.append(Ev(sid, i + 1, t, f"{s['prefix']}-{i + 1:06d}", qty, price, CHANNELS[(salt >> 16) % 4]))
            self.events[sid] = out

    def window(self, sid: str, lo: int, hi: int) -> list[Ev]:
        evs = self.events[sid]
        ts = self._ts[sid]
        return evs[bisect.bisect_right(ts, lo):bisect.bisect_right(ts, hi)]

    # ---------------------------------------------------------------------------------------------------------------- flags on events
    def flag_events(self) -> None:
        r = self.rs["rows"]
        self._ts = {sid: [e.ts for e in self.events[sid]] for sid in SRC_ORDER}
        for sid in SRC_ORDER:
            for e in self.events[sid]:
                if sid == STALE_SOURCE and e.ts >= STALE_FROM:
                    e.hold = "never"
                    continue
                x = r.randrange(1_000_000)
                if x < PPM["neg"]:
                    e.dirty = "neg"
                elif x < PPM["neg"] + PPM["missing"]:
                    e.dirty = "missing"
                elif x < PPM["neg"] + PPM["missing"] + PPM["invalid"]:
                    e.dirty = "invalid"
                if e.dirty and ppm(r, PPM["fix"]):
                    e.fix_after = 1 + r.randrange(3)
                if sid in ("src-orders", "src-payments", "src-shipments") and (not e.dirty and ppm(r, PPM["cancel"]) or e.dirty and ppm(r, PPM["cancel_dirty"])):
                    e.cancel_ts = e.ts + r.randrange(1800, 30 * H)
                    e.double = ppm(r, PPM["double_delete"])
        # the designed late events: held back from their own batches, delivered in one later batch of the same source
        k = self.slot_at(LATE_SOURCE, LATE_SLOT)
        lo, hi = at(2026, 9, 17, 18), at(2026, 9, 17, 23, 50)
        cand = [e for e in self.events[LATE_SOURCE] if lo <= e.ts <= hi and not e.dirty and e.cancel_ts is None]
        chosen = sorted(r.sample(range(len(cand)), LATE_N))
        for i in chosen:
            cand[i].hold, cand[i].designed = "late", "INJ-09"
        self.late_slot_index = k
        # the designed delete: one src-orders event delivered at 08:00 and cancelled in the 12:00 batch of the same day
        sid, a, b = DELETE_SLOT
        ka, kb = self.slot_at(sid, a), self.slot_at(sid, b)
        wa = [e for e in self.window(sid, self.slots[sid][ka - 1]["nominal"] - 90, self.slots[sid][ka]["nominal"] - 90)
              if not e.dirty and e.cancel_ts is None and e.hold is None]
        e = wa[len(wa) // 2]
        e.cancel_ts = self.slots[sid][kb]["nominal"] - 90 - 1800
        e.double, e.designed = False, "INJ-08"
        self.delete_event = e

    # ---------------------------------------------------------------------------------------------------------------- backfill plan
    def plan_backfills(self) -> None:
        r = self.rs["backfills"]
        weights = ["src-inventory"] * 5 + ["src-web-events"] * 4 + ["src-shipments"] * 2 + ["src-refunds"] * 2
        r.shuffle(weights)
        positions = [i for i in range(1, 16) if i not in (6, 12)]               # bf-006 and bf-012 are the refused overlaps
        req_start = at(2026, 8, 19, 9)
        times = {i: req_start + (i - 1) * (2 * D + 18 * H) + r.randrange(0, 4 * H) for i in range(1, 16)}
        used: dict[str, set[str]] = {}
        reqs: dict[int, dict] = {}
        partial = set(r.sample(positions, 4))
        for pos, src in zip(positions, weights):
            nd = [1, 2, 1][r.randrange(3)] if src == "src-refunds" else 1
            for _ in range(200):
                first = at(2026, 8, 12) + r.randrange(0, max(1, (times[pos] - 3 * D - at(2026, 8, 12)) // D)) * D
                days = [day_of(first + j * D) for j in range(nd)]
                bad = {day_of(at(2026, 9, 9) + j * D) for j in (-1, 0, 1)} | {day_of(at(2026, 9, 15) + j * D) for j in (-1, 0, 1)}
                near = {day_of(first - D)} | {day_of(first + (nd) * D)} | set(days)             # no two backfilled partitions of one source are adjacent
                if first + nd * D < times[pos] - 2 * D and not (near & used.get(src, set())) and not (src == "src-payments" and set(days) & bad) \
                        and not (src == STALE_SOURCE and first + nd * D >= STALE_FROM):
                    break
            else:
                raise RuntimeError("no backfill days")
            used.setdefault(src, set()).update(days)
            reqs[pos] = {"pos": pos, "id": f"bf-{pos:03d}", "src": src, "first": first, "days": days, "request": times[pos], "partial": pos in partial, "refused": False}
        for pos, victim in ((6, 4), (12, 10)):
            v = reqs[victim]
            first, nd = v["first"], 2                                              # same first day: the ranges overlap whatever the victim's length
            reqs[pos] = {"pos": pos, "id": f"bf-{pos:03d}", "src": v["src"], "first": first, "days": [day_of(first + j * D) for j in range(nd)], "request": times[pos],
                         "partial": False, "refused": True, "overlaps": v["id"]}
        self.bf = reqs
        for q in reqs.values():
            if not q["refused"]:
                for e in self.events[q["src"]]:
                    if e.date in q["days"] and e.hold is None:
                        e.hold, e.dirty, e.cancel_ts, e.fix_after = "bf", None, None, 0
                        e.designed = q["id"]
                if q["partial"]:                                                  # the last partition keeps two rows that fail the contract for good
                    last = [e for e in self.events[q["src"]] if e.date == q["days"][-1]]
                    for e in (last[len(last) // 3], last[2 * len(last) // 3]):
                        e.dirty, e.fix_after = "neg", 0
                        q.setdefault("forced_bad", []).append(e.key)

    # ---------------------------------------------------------------------------------------------------------------- slot flags
    def plan_flags(self) -> None:
        r = self.rs["failures"]
        avoid = {day_of(at(2026, 9, 9) + j * D) for j in (-1, 0, 1)} | {day_of(at(2026, 9, 15) + j * D) for j in (-1, 0, 1)} \
            | {day_of(at(2026, 9, 17) + j * D) for j in range(3)} | {day_of(at(2026, 9, 22) + j * D) for j in (-1, 0, 1)} | {day_of(at(2026, 8, 27) + j * D) for j in (-1, 0, 1)}

        def pick(srcs: tuple[str, ...], hours: tuple[int, ...], n: int, gap: int, taken: list[int], lo: int, hi: int) -> list[tuple[str, int]]:
            out: list[tuple[str, int]] = []
            for _ in range(5000):
                if len(out) == n:
                    return out
                sid = srcs[r.randrange(len(srcs))]
                k = r.randrange(len(self.slots[sid]))
                nom = self.slots[sid][k]["nominal"]
                if not (lo <= nom <= hi) or day_of(nom) in avoid or (nom % D) // H not in hours:
                    continue
                if any(abs(nom - t) < gap * D for t in taken):
                    continue
                taken.append(nom)
                out.append((sid, k))
            raise RuntimeError("could not place the slot flags")

        taken: list[int] = []
        lo, hi = at(2026, 8, 14), at(2026, 9, 28)
        fresh = pick(("src-orders",), (8, 12, 16), 3, 2, taken, lo, hi) + pick(("src-payments",), (10, 14), 2, 2, taken, lo, hi)
        self.fresh_slots = {x: None for x in fresh}
        ab = pick(("src-orders", "src-payments", "src-refunds", "src-shipments"), tuple(range(1, 23)), N_ABORTED_RANDOM, 2, taken, lo, hi)
        ab.sort(key=lambda x: self.slots[x[0]][x[1]]["nominal"])
        self.aborted_slots = set(ab)
        self.inj01_slot = ab[3]
        self.leak_slot = (LEAK_SLOT[0], self.slot_at(*LEAK_SLOT))
        self.aborted_slots.add(self.leak_slot)
        self.schema_slot = next(i for i, sl in enumerate(self.slots[SCHEMA_SOURCE]) if sl["nominal"] >= SCHEMA_FROM)
        self.loop_slot = self.slot_at(LOOP_SOURCE, LOOP_SLOT)
        self.keyless_slot = (KEYLESS_SLOT[0], self.slot_at(*KEYLESS_SLOT))
        self.unknown_op_slots = {(sid, r.randrange(len(self.slots[sid]))) for sid in ("src-orders", "src-payments", "src-shipments") for _ in range(1)}

    # ---------------------------------------------------------------------------------------------------------------- classification mirror
    REASON = {"neg": "NEGATIVE_QUANTITY", "missing": "MISSING_FIELD", "invalid": "INVALID_FIELD", "keyless": "MISSING_FIELD", "badop": "UNKNOWN_OP"}

    def mk_row(self, label: str, key: str | None, payload: dict, ev: Ev | None) -> dict:
        return {"label": label, "key": key, "payload": payload, "hash": sha(canon(payload)), "ev": ev, "disp": None, "reason": None}

    def mirror(self, rows: list[dict], st: dict) -> None:
        for r in rows:
            lab, key = r["label"], r["key"]
            if lab == "del":
                if key in st["acc"] and key not in st["del"]:
                    r["disp"] = "deleted"
                    st["del"].add(key)
                elif key in st["del"]:
                    r["disp"] = "duplicate"
                else:
                    r["disp"], r["reason"] = "quarantined", "DELETE_TARGET_UNKNOWN"
            elif lab == "badop":
                r["disp"], r["reason"] = "quarantined", "UNKNOWN_OP"
            elif key is not None and key in st["acc"]:
                r["disp"] = "duplicate"
            elif lab in self.REASON:
                r["disp"], r["reason"] = "quarantined", self.REASON[lab]
            else:
                r["disp"] = "accepted"
                st["acc"].add(key)

    # ---------------------------------------------------------------------------------------------------------------- live batches
    def build_live(self) -> None:
        rb, rf = self.rs["batches"], self.rs["fetch"]
        self.states = {sid: {"acc": set(), "del": set()} for sid in SRC_ORDER}
        self.rl_slots: list[tuple[str, int]] = []
        self.fresh_gate: dict[tuple[str, int], int] = {}
        never_ts = sorted(e.ts for e in self.events[STALE_SOURCE] if e.hold == "never")
        for sid in SRC_ORDER:
            s, slots, st = SRC[sid], self.slots[sid], self.states[sid]
            prev_end, prev_cursor, L = E0, "off-000000", None
            prev_acc: list[Ev] = []
            recent: list[Ev] = []
            pend_fix: dict[int, list[Ev]] = {}
            pend_del: list[Ev] = []
            pend_dd: list[Ev] = []
            schema: str | None = None
            for k, sl in enumerate(slots):
                nominal = sl["nominal"]
                if (sid, k) in self.fresh_slots:
                    gi = bisect.bisect_right(self.gates_sorted, L + s["target"])
                    g_star = self.gates_sorted[gi]
                    assert g_star - nominal >= 600 and (k + 1 >= len(slots) or g_star + 150 + 900 < slots[k + 1]["nominal"]), (sid, k, g_star - nominal)
                    self.fresh_gate[(sid, k)] = g_star
                    nominal = g_star + 150
                end = nominal - 90
                jitter = rb.randrange(0, 150)
                start = nominal + jitter
                # --- fetch attempts of this slot
                tags: list[str] = ["fresh_delay"] if (sid, k) in self.fresh_slots else []
                if sid == RATE_LIMITED_SOURCE and ppm(rf, RATE_LIMIT_PPM):
                    n429 = 1 + (1 if ppm(rf, 300_000) else 0)
                    t = start
                    for j in range(n429):
                        ra = RETRY_AFTER_CHOICES[rf.randrange(len(RETRY_AFTER_CHOICES))]
                        self.fetch_log.append({"src": sid, "cursor": prev_cursor, "session": f"{sid}:{k}", "status": "rate_limited", "next": None, "ra": ra, "t": t, "slot": (sid, k)})
                        if not self.refused_attempts:
                            self.refused_attempts.append({"source_id": sid, "cursor": prev_cursor, "rate_limited_at": iso(t), "retry_after_seconds": ra,
                                                          "attempted_at": iso(t + ra // 3), "retry_not_before": iso(t + ra), "refused": "RETRY_TOO_SOON",
                                                          "remaining_seconds": ra - ra // 3, "slot": (sid, k)})
                        t = t + ra + rf.randrange(0, 26)
                    start = t
                    tags.append("rate_limited")
                    self.rl_slots.append((sid, k))
                loop_here = False
                if sid == LOOP_SOURCE and k == self.loop_slot:
                    start += 600 + rb.randrange(0, 120)              # the page is fetched late; the page AFTER it points back (recorded below, in the same session)
                    tags.append("cursor_loop")
                    loop_here = True
                # --- rows
                win = self.window(sid, prev_end, end)
                deliver = [e for e in win if e.hold is None]
                rows: list[dict] = []
                replay = sid == STALE_SOURCE and nominal >= STALE_FROM and not deliver
                declared = schema
                if sid == SCHEMA_SOURCE and k >= self.schema_slot:
                    declared = SCHEMA_VERSION
                if replay:
                    for e in recent[-STALE_REPLAY_ROWS:]:
                        rows.append(self.mk_row("dup", e.key, payload_of(e, declared), e))
                    tags.append("stale_replay")
                else:
                    if prev_acc:
                        for e in prev_acc[len(prev_acc) - rb.randrange(0, 4):] if len(prev_acc) >= 3 else []:
                            rows.append(self.mk_row("dup", e.key, payload_of(e, declared), e))
                    for e in deliver:
                        if e.dirty:
                            rows.append(self.mk_row(e.dirty, e.key, payload_of(e, declared, e.dirty), e))
                            if e.fix_after:
                                pend_fix.setdefault(min(k + e.fix_after, len(slots) - 1), []).append(e)
                        else:
                            rows.append(self.mk_row("ok", e.key, payload_of(e, declared), e))
                        if e.cancel_ts is not None:
                            pend_del.append(e)
                    if sid == LATE_SOURCE and k == self.late_slot_index:
                        for e in self.events[sid]:
                            if e.hold == "late":
                                rows.append(self.mk_row("ok", e.key, payload_of(e, declared), e))
                                tags.append("late_events")
                    for e in pend_fix.pop(k, []):
                        rows.append(self.mk_row("ok", e.key, payload_of(e, declared), e))
                    dels = [e for e in pend_dd] + [e for e in pend_del if e.cancel_ts <= end]
                    pend_dd = []
                    for e in dels:
                        rows.append(self.mk_row("del", e.key, {"record_id": e.key, "op": "delete", "amount": "0.00", "event_ts": iso(e.cancel_ts)}, e))
                        if e in pend_del:
                            pend_del.remove(e)
                            if e.double:
                                pend_dd.append(e)
                    if (sid, k) == self.keyless_slot:
                        e0 = deliver[len(deliver) // 2]
                        rows.append(self.mk_row("keyless", None, payload_of(e0, declared, "keyless") | {"event_ts": iso(e0.ts + 1)}, None))
                        tags.append("keyless")
                    if (sid, k) in self.unknown_op_slots and prev_acc:
                        e0 = prev_acc[-1]
                        rows.append(self.mk_row("badop", e0.key, {"record_id": e0.key, "op": "merge", "amount": "0.00", "event_ts": iso(end)}, None))
                        tags.append("unknown_op")
                off = bisect.bisect_right(self._ts[sid], end) - (bisect.bisect_right(never_ts, end) if sid == STALE_SOURCE else 0)
                cursor_to = prev_cursor if replay else f"off-{off:06d}"
                proc = 120 + rb.randrange(0, 280) + len(rows) * 2
                aborted = (sid, k) in self.aborted_slots
                if aborted:
                    start2 = start + 1200 + rb.randrange(0, 300)
                    kinds = [("aborted", start, False), ("replay", start2, True)]
                elif sid == SCHEMA_SOURCE and k == self.schema_slot:
                    start2 = start + SCHEMA_BUMP_DELAY_S
                    kinds = [("schema_q", start, False), ("schema_refetch", start2, True)]
                else:
                    kinds = [("live", start, True)]
                for kind, t_start, commits in kinds:
                    status = "committed" if commits else ("aborted" if kind == "aborted" else "quarantined")
                    b = Batch(sid, kind, t_start, rows if commits else [dict(x) for x in rows], status, prev_cursor, cursor_to)
                    b.slot, b.window_end, b.tags, b.session = k, end, list(tags), f"{sid}:{k}" + (":b" if kind in ("schema_refetch", "replay") else "")
                    if declared is not None or kind.startswith("schema"):
                        b.schema = declared
                    if commits:
                        b.commit = t_start + proc
                    self.batches.append(b)
                    if loop_here and kind == "live":
                        # D-09 (R8-06): a loop is a repeated cursor INSIDE one fetch session: the page after this one (cursor_to) answers with the cursor this
                        # session started from; the session is stopped (nothing is staged for the looping page) and the next slot fetches from cursor_to
                        self.fetch_log.append({"src": sid, "cursor": cursor_to, "session": b.session, "status": "cursor_loop", "next": prev_cursor, "ra": None, "t": t_start + 45, "slot": (sid, k)})
                    if kind == "schema_q":
                        b.schema = SCHEMA_VERSION
                    if kind == "aborted" and (sid, k) == self.inj01_slot:
                        b.tags.append("inj01")
                    if kind == "aborted" and (sid, k) == self.leak_slot:
                        b.tags.append("leak")
                self.mirror(rows, st)        # the committed copy (the same row objects are shared with `rows`)
                acc_now = [x["ev"] for x in rows if x["disp"] == "accepted" and x["ev"] is not None]
                if acc_now:
                    top = max(x.ts for x in acc_now)
                    L = top if L is None else max(L, top)
                    recent.extend(acc_now)
                    recent = recent[-60:]
                if not replay:
                    prev_acc = [x["ev"] for x in rows if x["disp"] == "accepted" and x["ev"] is not None] or prev_acc
                prev_end, prev_cursor = end, cursor_to

    # ---------------------------------------------------------------------------------------------------------------- backfill batches
    def build_backfill_batches(self) -> None:
        rb = self.rs["batches"]
        for pos in sorted(self.bf):
            q = self.bf[pos]
            if q["refused"]:
                continue
            st = self.states[q["src"]]
            q["batches"] = []
            live = sorted((x for x in self.batches if x.src == q["src"] and x.kind != "backfill" and x.status == "committed"), key=lambda x: x.commit)
            live_commits = [x.commit for x in live]
            for j, day in enumerate(q["days"]):
                evs = [e for e in self.events[q["src"]] if e.designed == q["id"] and e.date == day]
                rows = [self.mk_row(e.dirty if e.dirty else "ok", e.key, payload_of(e, SCHEMA_VERSION if q["src"] == SCHEMA_SOURCE else None, e.dirty), e) for e in evs]
                start = q["request"] + 3600 + j * 1800 + rb.randrange(0, 240)
                i_live = bisect.bisect_left(live_commits, start)
                cur = live[i_live - 1].cursor_to if i_live else "off-000000"      # D-09: a backfill re-polls the last committed cursor (a refetch), it has no cursor of its own
                b = Batch(q["src"], "backfill", start, rows, "committed", cur, cur)
                b.commit = start + 150 + rb.randrange(0, 200) + 2 * len(rows)
                b.bf, b.session, b.tags = q["id"], f"{q['src']}:{q['id']}:{day}", ["backfill"]
                if q["src"] == SCHEMA_SOURCE:
                    b.schema = SCHEMA_VERSION
                self.mirror(rows, st)
                self.batches.append(b)
                q["batches"].append(b)
            q["commit_last"] = max(b.commit for b in q["batches"])
            q["verified"] = {}

    def finalize_batches(self) -> None:
        """Ids in start order, checkpoint versions in commit order, the live cursor under each backfill checkpoint."""
        order = {s: i for i, s in enumerate(SRC_ORDER)}
        self.batches.sort(key=lambda b: (b.start, order[b.src], b.kind))
        for i, b in enumerate(self.batches, 1):
            b.batch_id = f"b-{i:04d}"
        self.committed = sorted((b for b in self.batches if b.status == "committed"), key=lambda b: (b.commit, b.batch_id))
        ver: dict[str, int] = {}
        live_cursor: dict[str, list[tuple[int, str]]] = {s: [] for s in SRC_ORDER}
        for b in self.committed:
            ver[b.src] = ver.get(b.src, 0) + 1
            b.version = ver[b.src]
            if b.kind != "backfill":
                live_cursor[b.src].append((b.commit, b.cursor_to))
                b.cp_cursor = b.cursor_to
            else:
                prior = [c for c in live_cursor[b.src] if c[0] < b.commit]
                b.cp_cursor = prior[-1][1] if prior else "off-000000"
        self.by_id = {b.batch_id: b for b in self.batches}

    # ---------------------------------------------------------------------------------------------------------------- expectations, ledger
    def build_expectations(self) -> None:
        self.expected: dict[tuple[str, str], int] = {}
        for sid in SRC_ORDER:
            for e in self.events[sid]:
                self.expected[(sid, e.date)] = self.expected.get((sid, e.date), 0) + 1

    def build_ledger(self) -> None:
        """What the committed batches made known and when: accepted records, deletes, per-source freshness and horizons."""
        self.deleted_in: dict[tuple[str, str], str] = {}
        self.accepted_by_batch: dict[str, list[dict]] = {}
        led: list[tuple[int, str, str]] = []
        per_src_ev: dict[str, list[tuple[int, int]]] = {s: [] for s in SRC_ORDER}
        per_src_hz: dict[str, list[tuple[int, int]]] = {s: [] for s in SRC_ORDER}
        for b in self.committed:
            acc = []
            for r in b.rows:
                if r["disp"] == "accepted":
                    acc.append(r)
                    led.append((b.commit, b.src, r["ev"].date))
                elif r["disp"] == "deleted":
                    self.deleted_in[(b.src, r["key"])] = b.batch_id
            self.accepted_by_batch[b.batch_id] = acc
        for sid in SRC_ORDER:
            top = None
            for b in self.committed:
                if b.src != sid:
                    continue
                mx = max((r["ev"].ts for r in self.accepted_by_batch[b.batch_id]), default=None)
                if mx is not None:
                    top = mx if top is None else max(top, mx)
                    per_src_ev[sid].append((b.commit, top))
            hz = None
            for b in self.committed:
                if b.src == sid and b.kind != "backfill":
                    hz = b.window_end if hz is None else max(hz, b.window_end)
                    per_src_hz[sid].append((b.commit, hz))
        self.led = sorted(led)
        self.src_ev = {s: ([c for c, _ in v], [t for _, t in v]) for s, v in per_src_ev.items()}
        self.src_hz = {s: ([c for c, _ in v], [t for _, t in v]) for s, v in per_src_hz.items()}

    def latest_event(self, sid: str, at_s: int) -> int | None:
        cs, ts = self.src_ev[sid]
        i = bisect.bisect_left(cs, at_s)                 # commits strictly before at_s
        return ts[i - 1] if i else None

    def horizon(self, sid: str, at_s: int) -> int:
        cs, ts = self.src_hz[sid]
        i = bisect.bisect_left(cs, at_s)
        return ts[i - 1] if i else E0

    # ---------------------------------------------------------------------------------------------------------------- failure plan
    def plan_failures(self) -> None:
        r = self.rs["failures"]
        tick_of_gate = {g: t for t, g in self.gate_at.items()}
        plan: dict[int, str] = {}
        for (sid, k), g in self.fresh_gate.items():
            plan[tick_of_gate[g]] = "freshness"
        plan[int(RESIDUAL_TICK.timestamp())] = "residual"
        reserved = list(plan)
        avoid_days = {day_of(at(2026, 9, 9) + j * D) for j in (-1, 0, 1)} | {day_of(at(2026, 9, 15) + j * D) for j in (-1, 0, 1)} | \
            {day_of(at(2026, 9, 17) + j * D) for j in range(3)} | {day_of(at(2026, 9, 22) + j * D) for j in (0,)} | {day_of(at(2026, 8, 27))}
        lo, hi = at(2026, 8, 12), at(2026, 9, 30, 23)
        types = list(FAIL_TYPES)
        r.shuffle(types)
        chosen: list[int] = []
        for _ in range(100_000):
            if len(chosen) == len(types):
                break
            t = self.tick_times[r.randrange(len(self.tick_times))]
            if not (lo <= t <= hi) or not (6 <= (t % D) // H <= 21) or day_of(t) in avoid_days:
                continue
            if any(abs(t - x) < 4 * H for x in reserved + chosen):
                continue
            chosen.append(t)
        assert len(chosen) == len(types), "failure ticks"
        chosen.sort()
        for t, ty in zip(sorted(chosen), types):
            plan[t] = ty
        self.plan = plan
        rel = sorted(t for t, ty in plan.items() if ty == "relationships")
        self.inj07_tick = rel[1]
        assert len(plan) == N_INCIDENTS

    # ---------------------------------------------------------------------------------------------------------------- the runs
    def simulate_runs(self) -> None:
        self.runs, self.tasks, self.quals, self.pubs, self.totals = [], [], [], [], []
        self.incident_rows: list[dict] = []
        committed_commits = [b.commit for b in self.committed]
        pending_bf = sorted((q for q in self.bf.values() if not q["refused"]), key=lambda q: q["commit_last"])
        bf_run: dict[int, str] = {}
        leak_batch = next(b for b in self.batches if "leak" in b.tags)
        leak_amount = sum(r["ev"].amount for r in [x for x in leak_batch.rows if x["label"] == "ok"][:LEAK_ROWS])
        self.leak_amount_c, self.leak_batch_id = leak_amount, leak_batch.batch_id
        ledger_i, acc_part = 0, {}
        natural_fresh: dict[int, int] = {}
        deploys = [(at(2026, 8, 10), "c0a81f2"), (at(2026, 8, 21), "5be90d4"), (at(2026, 9, 2), "9d3f7a1"), (at(2026, 9, 16), "e41b6c8"), (at(2026, 9, 28), "27af05e")]
        pub_no = 0
        failed_idx: list[int] = []
        # D-09 (R8-02): the two checks the gate gained are asked of the DOMAIN (gate.scope_complete, reconcile.late_events), run by run, as the API's C05 asks them
        gm, rm = self.dom.mod["gate"], self.dom.mod["reconcile"]
        from decimal import Decimal
        committed_pairs = [(b.batch_id, iso(b.commit)) for b in self.committed]
        arr_i, pending, last_wm = 0, [], None
        for i, T in enumerate(self.tick_times, 1):
            S, g, dr = T + RUN_OFFSET_S, self.gate_at[T], self.run_draw[T]
            D0 = ((T - H) // D) * D
            lo_i, hi_i = bisect.bisect_left(committed_commits, D0), bisect.bisect_left(committed_commits, S)       # the scope: committed in [the UTC day of the tick minus one hour, the run's start)
            scope = self.committed[lo_i:hi_i]
            ids = sorted(b.batch_id for b in scope)
            idset = set(ids)
            run_id, plan = f"run-{i:04d}", self.plan.get(T)
            bf = None
            while pending_bf and pending_bf[0]["commit_last"] < S:
                bf = pending_bf.pop(0)["id"]
            if bf:
                bf_run[T] = bf
            code = [c for t0, c in deploys if t0 <= T][-1]
            srcs = sorted({b.src for b in scope})
            # published records
            pub_hashes, total = [], 0
            for b in scope:
                for r in self.accepted_by_batch[b.batch_id]:
                    d = self.deleted_in.get((b.src, r["key"]))
                    if d is not None and d in idset:
                        continue
                    pub_hashes.append(r["hash"])
                    total += r["ev"].amount
            n_pub = len(pub_hashes)
            candidate_total = total + (leak_amount if plan == "residual" else 0)
            # scope_complete: every batch committed in [D0, S) is in the candidate (the domain judges it from the commit instants, not from how the scope was cut)
            n_scope, missing = gm.scope_complete(committed_pairs, ids, iso(D0), iso(S))
            # late_events_included: every late event that has arrived before S and is in no earlier publication is in the candidate
            while arr_i < len(self.committed) and self.committed[arr_i].commit < S:
                nb = self.committed[arr_i]
                arr_i += 1
                accs = [rm.Accepted(nb.src, nb.batch_id, r["key"], iso(r["ev"].ts), iso(nb.commit), "", r["hash"], Decimal(0)) for r in self.accepted_by_batch[nb.batch_id]]
                if accs and self.pubs:
                    pending += rm.late_events(accs, self.pubs[-12:])
            n_pending, n_left = len(pending), sum(1 for e in pending if e["batch_id"] not in idset)
            # gate numbers as of the gate instant
            while ledger_i < len(self.led) and self.led[ledger_i][0] < g:
                _, ls, ld = self.led[ledger_i]
                acc_part[(ls, ld)] = acc_part.get((ls, ld), 0) + 1
                ledger_i += 1
            stale = 0
            for sid in srcs:
                le = self.latest_event(sid, g)
                if le is None or g - le > SRC[sid]["target"]:
                    stale += 1
            if stale and plan != "freshness":
                natural_fresh[T] = stale
            elig = short = 0
            today = day_of(D0)
            for sid in srcs:
                for d in range(N_DAYS):
                    ds = day_of(E0 + d * D)
                    if ds >= today:
                        break
                    ex = self.expected[(sid, ds)]
                    elig += ex
                    short += max(ex - acc_part.get((sid, ds), 0), 0)
            status, finish, tasks, quals, pub = "success", S + dr["dur"], [], None, None
            atts = lambda name, st: [(name, s_, a) for a, s_ in enumerate(st, 1)]   # noqa: E731
            flaky = dr["flaky"] and plan is None
            tl: list[tuple[str, str, int]] = []
            if plan == "ingest":
                tl = atts("ingest", ["failed"] * 3)
                status, finish = "failed", S + dr["fail_dur"]
            elif plan == "transform":
                tl = atts("ingest", ["success"]) + atts("transform", ["failed"] * 3)
                status, finish = "failed", S + dr["fail_dur"] + 2 * dr["extra"]
            else:
                for name in ("ingest", "transform"):
                    tl += atts(name, ["failed", "success"] if flaky and dr["flaky_task"] == name else ["success"])
                if plan == "gate_infra":
                    tl += atts("quality_gate", ["failed"] * 3)
                    status, finish = "failed", g + 2 * dr["extra"]
                else:
                    gate_ok = plan is None
                    tl += atts("quality_gate", ["success"] if gate_ok else ["failed"])
                    if gate_ok:
                        tl += atts("publish", ["failed", "success"] if flaky and dr["flaky_task"] == "publish" else ["success"])
                        finish = max(S + dr["dur"] + (dr["extra"] if flaky else 0), g + 90)
                    else:
                        status, finish = "failed", g + 45
                        quals = True
            if plan not in ("ingest", "transform", "gate_infra"):
                quals = True
            row = {"run_id": run_id, "started_at": iso(S), "finished_at": iso(finish), "status": status, "code_sha": code, "backfill_id": bf, "scope_from": iso(D0)}
            self.runs.append(row)
            tids = {}
            for n, (name, st, att) in enumerate(tl, 1):
                tid = f"tr-{i:04d}-{n}"
                self.tasks.append({"task_run_id": tid, "run_id": run_id, "task_name": name, "status": st, "attempt": att})
                tids[(name, att)] = tid
            if quals:
                gate_tid = next(t["task_run_id"] for t in reversed(self.tasks) if t["run_id"] == run_id and t["task_name"] == "quality_gate")
                checks = [("keys_unique", "critical", n_pub, 0), ("relationships_intact", "critical", n_pub, 1 if plan == "relationships" else 0),
                          ("reconciliation_residual_zero", "critical", 1, 1 if plan == "residual" else 0),
                          ("freshness_within_target", "critical", len(srcs), stale), ("completeness_vs_expectation", "warning", elig, short),
                          (gm.SCOPE_COMPLETE, "critical", n_scope, len(missing)), (gm.LATE_EVENTS_INCLUDED, "critical", n_pending, n_left)]
                assert not missing and n_left == 0, f"{run_id}: the world does not satisfy the gate it records: missing {missing[:3]}, late events left out {n_left}"
                for n, (rule, sev, el, fl) in enumerate(checks, 1):
                    self.quals.append({"quality_result_id": f"qr-{i:04d}-{n:02d}", "task_run_id": gate_tid, "rule_name": rule, "severity": sev, "eligible_count": el, "failure_count": fl})
            if plan not in ("ingest", "transform"):
                trow = {"run_id": run_id, "output_rows": n_pub, "total_amount": cents(candidate_total)}
                if status == "success":
                    pub_no += 1
                    horizon = min(self.horizon(sid, g) for sid in SRC_ORDER)
                    assert last_wm is None or horizon >= last_wm, f"{run_id}: the watermark goes back"          # C06 refuses it (WATERMARK_REGRESSION)
                    last_wm = horizon
                    pub = {"publication_id": f"pub-{i:04d}", "run_id": run_id, "dataset_name": "sales_daily", "published_at": iso(finish), "watermark": iso(horizon),
                           "source_ids": list(SRC_ORDER), "included_batch_ids": ids, "content_hash": sha("\n".join(sorted(pub_hashes)))}
                    self.pubs.append(pub)
                    pending = [e for e in pending if e["batch_id"] not in set(ids)]          # included in a publication published after its arrival
                else:
                    trow["included_batch_ids"] = ids
                self.totals.append(trow)
            if status == "failed":
                failed_idx.append(len(self.runs) - 1)
                self.incident_rows.append({"run": len(self.runs) - 1, "plan": plan, "opened": finish})
        self.natural_fresh = natural_fresh
        assert not natural_fresh, f"unplanned freshness failures at {[iso(t) for t in natural_fresh]}"
        self.bf_run = bf_run
        # incidents: verified recovery is the first later run that succeeded and published (its residual is 0.00 by construction)
        sev = {"residual": "critical", "relationships": "high", "transform": "high", "freshness": "medium", "ingest": "medium", "gate_infra": "medium"}
        pub_of = {p["run_id"]: p for p in self.pubs}
        self.incidents = []
        for n, inc in enumerate(sorted(self.incident_rows, key=lambda x: (x["opened"], x["run"])), 1):
            rec = next(r for r in self.runs[inc["run"] + 1:] if r["status"] == "success" and r["run_id"] in pub_of)
            self.incidents.append({"incident_id": f"inc-{n:03d}", "run_id": self.runs[inc["run"]]["run_id"], "severity": sev[inc["plan"]], "status": "closed",
                                   "opened_at": iso(inc["opened"]), "closed_at": pub_of[rec["run_id"]]["published_at"], "recovery_run_id": rec["run_id"], "_plan": inc["plan"]})

    # ---------------------------------------------------------------------------------------------------------------- backfill rows
    def backfill_rows(self) -> list[dict]:
        """The requests. D-09 (R8-12): overlap is judged against requests still ``requested`` or ``running``, so a refused request is one made while its
        victim was still being worked on: the refused rows carry ``requested_at`` two minutes after the victim's last batch committed, before the run that
        settled the victim published; an accepted request carries ``requested_at`` and ``settled_at`` (the publication of the first successful run that
        started with or after the run the backfill rode on)."""
        out = []
        run_start = {r["run_id"]: r["started_at"] for r in self.runs}
        succeeded = sorted(((p["published_at"], run_start[p["run_id"]]) for p in self.pubs), key=lambda x: x[1])
        run_of = {bf_id: f"run-{self.tick_times.index(t) + 1:04d}" for t, bf_id in self.bf_run.items()}
        for pos in sorted(self.bf):
            q = self.bf[pos]
            first = q["first"]
            start, end = iso(first), iso(first + len(q["days"]) * D)
            if q["refused"]:
                victim = self.bf[int(q["overlaps"][3:])]
                q["requested_final"] = victim["commit_last"] + 120
                out.append({"backfill_id": q["id"], "source_id": q["src"], "start_at": start, "end_at": end, "status": "requested", "requested_at": iso(q["requested_final"]),
                            "settled_at": None, "partitions": [{"partition": d, "verified": False} for d in q["days"]]})
                continue
            parts = []
            for day, b in zip(q["days"], q["batches"]):
                n = sum(1 for r in b.rows if r["disp"] == "accepted")
                parts.append({"partition": day, "verified": n >= self.expected[(q["src"], day)]})
            q["verified"] = {p["partition"]: p["verified"] for p in parts}
            attach = run_start[run_of[q["id"]]]
            settled = next(pub for pub, st in succeeded if st >= attach)
            q["settled_final"] = settled
            out.append({"backfill_id": q["id"], "source_id": q["src"], "start_at": start, "end_at": end,
                        "status": "complete" if all(p["verified"] for p in parts) else "partial", "requested_at": iso(q["request"]), "settled_at": settled, "partitions": parts})
        return out

    # ---------------------------------------------------------------------------------------------------------------- entities
    def build_all(self) -> None:
        self.dom = Domain()          # the checks the gate records (scope_complete, late_events_included) and the fetch verdicts are the domain's, not typed here
        self.draw_run_timing()
        self.plan_slots()
        self.emit()
        self.flag_events()
        self.plan_backfills()
        self.plan_flags()
        self.build_live()
        self.build_backfill_batches()
        self.finalize_batches()
        self.build_expectations()
        self.build_ledger()
        self.plan_failures()
        self.simulate_runs()
        self.build_models()
        self.ents = self.entities()

    def build_models(self) -> None:
        self.models = []
        for name, layer, grain, deps, definition in MODELS:
            v = MODEL_V2.get(name, 1)
            self.models.append({"model_id": "m-" + name.replace("_", "-"), "model_name": name, "grain": grain, "version_number": v,
                                "definition": definition, "definition_hash": sha(definition), "layer": layer, "depends_on": deps})

    def raw_id(self, b: Batch, n: int) -> str:
        return f"rr-{b.batch_id}-{n:04d}"

    def entities(self) -> dict[str, list[dict]]:
        sc = []
        owner = {"src-orders": 1, "src-payments": 1, "src-refunds": 1, "src-shipments": 2, "src-inventory": 2, "src-web-events": 3}
        for sid in SRC_ORDER:
            s = SRC[sid]
            sc.append({"source_id": sid, "source_name": s["name"], "schema_version": SCHEMA_VERSION if sid == SCHEMA_SOURCE else "1",
                       "expected_frequency": s["freq"], "owner_id": f"own-{owner[sid]:02d}", "freshness_target_seconds": s["target"]})
        batches, raws, quars, cps = [], [], [], []
        for b in self.batches:
            row = {"batch_id": b.batch_id, "source_id": b.src, "source_cursor": b.cursor_from, "started_at": iso(b.start), "status": b.status}
            if b.schema:
                row["schema_version"] = b.schema
            batches.append(row)
            nq = 0
            for n, r in enumerate(b.rows, 1):
                raws.append({"raw_record_id": self.raw_id(b, n), "batch_id": b.batch_id, "source_key": r["key"], "payload_hash": r["hash"], "payload_json": r["payload"]})
                if b.status == "quarantined":
                    nq += 1
                    quars.append({"quarantine_id": f"q-{b.batch_id}-{nq:02d}", "batch_id": b.batch_id, "source_key": r["key"], "reason_code": "SCHEMA_CHANGED", "payload_hash": r["hash"]})
                elif b.status == "committed" and r["disp"] == "quarantined":
                    nq += 1
                    quars.append({"quarantine_id": f"q-{b.batch_id}-{nq:02d}", "batch_id": b.batch_id, "source_key": r["key"], "reason_code": r["reason"], "payload_hash": r["hash"]})
            if b.status == "committed":
                cps.append({"checkpoint_id": f"cp-{b.batch_id}", "source_id": b.src, "batch_id": b.batch_id, "committed_cursor": b.cp_cursor,
                            "committed_at": iso(b.commit), "version_number": b.version})
        expect = [{"source_id": sid, "partition": ds, "expected_records": n} for (sid, ds), n in sorted(self.expected.items())]
        return {"source_contracts": sc, "source_expectations": expect, "ingestion_batches": batches, "raw_records": raws, "quarantine_records": quars,
                "checkpoints": cps, "model_definitions": self.models, "pipeline_runs": self.runs, "task_runs": self.tasks, "quality_results": self.quals,
                "publications": self.pubs, "incidents": [{k: v for k, v in i.items() if not k.startswith("_")} for i in self.incidents],
                "backfill_requests": self.backfill_rows(), "model_output_totals": self.totals}

    def fetch_rows(self) -> list[dict]:
        """The fetch log. Every page's status (``ok`` / ``refetch``) and the one loop are the DOMAIN's verdict (``fetch.judge_fetch``) over what the log
        recorded before it: a cursor fetched again in a new session, or the re-poll of the last committed cursor by a source with nothing new, is a
        ``refetch``; a repeated cursor inside one session is the loop. Cached: it is asked for several times."""
        if getattr(self, "_fetch_rows", None) is not None:
            return self._fetch_rows
        fm = self.dom.mod["fetch"]
        rows = []
        for f in self.fetch_log:
            rows.append({"source_id": f["src"], "cursor_value": f["cursor"], "session_id": f["session"], "status": f["status"], "next_cursor": f["next"],
                         "retry_after_seconds": f["ra"], "fetched_at": iso(f["t"]), "batch_id": None, "_t": f["t"]})
        for b in self.batches:
            rows.append({"source_id": b.src, "cursor_value": b.cursor_from, "session_id": b.session, "status": "ok", "next_cursor": b.cursor_to,
                         "retry_after_seconds": None, "fetched_at": iso(b.start), "batch_id": b.batch_id, "_t": b.start})
        rows.sort(key=lambda x: (x["fetched_at"], x["source_id"], x["status"], x["batch_id"] or ""))
        cps: dict[str, tuple[list[int], list[str]]] = {}
        for b in self.committed:
            cs, cu = cps.setdefault(b.src, ([], []))
            cs.append(b.commit)
            cu.append(b.cp_cursor)
        history: dict[str, list] = {}
        for n, r in enumerate(rows, 1):
            r["fetch_id"] = n
            t = r.pop("_t")
            if r["status"] == "rate_limited":
                continue
            cs, cu = cps.get(r["source_id"], ([], []))
            i = bisect.bisect_left(cs, t)
            last = cu[i - 1] if i else None
            hist = history.setdefault(r["source_id"], [])
            if r["status"] == "cursor_loop":
                try:
                    fm.judge_fetch(hist, last, r["session_id"], r["cursor_value"], r["next_cursor"])
                except Exception as err:               # DomainError(CURSOR_LOOP): the world and the domain agree it is a loop
                    assert getattr(err, "code", None) == "CURSOR_LOOP", err
                else:
                    raise AssertionError(f"fetch {n} is recorded as a loop but the domain accepts it")
                continue
            r["status"] = fm.judge_fetch(hist, last, r["session_id"], r["cursor_value"], r["next_cursor"])
            hist.append(fm.Fetched(r["session_id"], r["cursor_value"], r["next_cursor"], r["status"]))
        self._fetch_rows = rows
        return rows


# ==================================================================================================================== the domain
CONFIG = {"contract_version": CONTRACT_VERSION, "as_of": AS_OF, "cutoff": AS_OF, "business_total_field": "amount", "freshness_timestamp_field": "event_ts",
          "partition_rule": "UTC date of the freshness timestamp field"}
DOMAIN12 = ("source_contracts", "ingestion_batches", "raw_records", "quarantine_records", "checkpoints", "model_definitions", "pipeline_runs",
            "task_runs", "quality_results", "publications", "incidents", "backfill_requests")
PUBLISHED = tuple(sorted(DOMAIN12 + ("source_expectations", "model_output_totals", "batch_summaries", "fetch_log")))


class Domain:
    """The domain package, imported lazily. ``parse_ts`` is memoised in the modules that call it in a loop (a pure function: the same
    arguments always give the same instant), because ``late_events`` parses every publication instant once per accepted record."""

    def __init__(self) -> None:
        dom = str(APP_ROOT / "domain")
        if dom not in sys.path:
            sys.path.insert(0, dom)
        import pipeline_observatory as po
        from pipeline_observatory import backfill, classify, fetch, gate, hashing, ingest, metrics, reconcile, redaction, scope, timeutil, workflow_guard
        cached = getattr(timeutil, "_po_memo", None)
        if cached is None:
            cached = functools.lru_cache(maxsize=None)(timeutil.parse_ts)
            timeutil._po_memo = cached
            for m in (reconcile, metrics, classify, ingest, scope, backfill, fetch, gate):
                if hasattr(m, "parse_ts"):
                    m.parse_ts = cached
        self.po, self.mod = po, dict(backfill=backfill, classify=classify, fetch=fetch, gate=gate, hashing=hashing, ingest=ingest, metrics=metrics, reconcile=reconcile,
                                     redaction=redaction, scope=scope, timeutil=timeutil, workflow_guard=workflow_guard)
        self.parse_ts = timeutil.parse_ts

    def run(self, data: dict, totals: dict[str, str]) -> tuple[Any, dict, Any]:
        from decimal import Decimal
        m = self.mod["metrics"]
        imp = self.mod["ingest"].validate_import(data)
        params = m.params_of(data)
        params["published_totals"] = {k: Decimal(v) for k, v in totals.items()}
        golden = m.compute(imp.accepted, imp.rejected, params)
        return imp, golden, m.derive(imp.accepted)

    def reconciliations(self, facts: Any, scopes: list[dict], totals: dict[str, str]) -> list[dict]:
        """The reconciliation of every run that reached a candidate table: source total, candidate total, exclusions and the residual, by the domain's
        own ``reconcile`` (the same function the publications use)."""
        from decimal import Decimal
        m, rc = self.mod["metrics"], self.mod["reconcile"]
        out = []
        for sc in scopes:
            inc, pubd, src_rows, removed, del_rows = m.publication_scope({"included_batch_ids": sc["included_batch_ids"]}, facts)
            r = rc.reconcile(src_rows, pubd, del_rows, removed, Decimal(sc["total_amount"]))
            out.append({"run_id": sc["run_id"], **r})
        return out


def entity_text(name: str, version: str, rows: list[dict]) -> str:
    body = ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return f'{{"entity":{json.dumps(name)},"dataset_version":{json.dumps(version)},"rows":[\n{body}\n]}}\n'


def dataset_hash(ents: dict[str, list[dict]]) -> str:
    h = hashlib.sha256()
    for name in sorted(PUBLISHED):
        h.update(canon(ents[name]).encode())
    return h.hexdigest()


class Built:
    """The world, the domain's verdict on all of it, and what is published."""

    def __init__(self, seed: int):
        self.seed = seed
        self.version = f"{VERSION_TAG}-{seed}-{DATE_TAG}"
        self.w = World(seed)
        self.w.build_all()
        self.dom = self.w.dom
        self.assemble()

    # ------------------------------------------------------------------------------------------------------------------------------
    def processing_measurement(self) -> dict:
        w = self.w
        best = max((b for b in w.committed if b.src == "src-orders" and b.kind == "live"), key=lambda b: (len(w.accepted_by_batch[b.batch_id]), b.batch_id))
        secs = w.rs["timing"].randrange(2_000, 6_000)
        self.pm_batch = best
        return {"source_id": best.src, "batch_id": best.batch_id, "measured_seconds": f"{secs // 1000}.{secs % 1000:03d}",
                "hardware": "Synthetic world value, not a benchmark: 2 vCPU, 8 GB RAM, GitHub-hosted runner class", "cache_state": "cold"}

    def inputs(self, raw: list[dict]) -> dict:
        data = {**CONFIG, "source_expectations": self.w.ents["source_expectations"], "processing_measurement": self.pm}
        for k in DOMAIN12:
            data[k] = raw if k == "raw_records" else self.w.ents[k]
        return data

    def evidence_batches(self) -> list[str]:
        """Batch ids chosen first for the sample: the injected defects and the designed relationships."""
        w = self.w
        ids: list[str] = []

        def by_slot(src: str, slot: int, *kinds: str) -> list[str]:
            return [b.batch_id for b in w.batches if b.src == src and b.slot == slot and (not kinds or b.kind in kinds)]
        ids += by_slot(*w.inj01_slot)
        ids += by_slot(*w.leak_slot)
        ids += by_slot(SCHEMA_SOURCE, w.schema_slot)
        ids += by_slot(*w.keyless_slot)
        ids += by_slot(LATE_SOURCE, w.late_slot_index) + by_slot(LATE_SOURCE, w.late_slot_index - 1)
        sid, a, b_ = DELETE_SLOT
        ids += by_slot(sid, w.slot_at(sid, a)) + by_slot(sid, w.slot_at(sid, b_))
        ids += by_slot(LOOP_SOURCE, w.loop_slot)
        rl = [x for x in w.batches if "rate_limited" in x.tags]
        ids += [x.batch_id for x in rl[:2]]
        stale = [x for x in w.batches if x.src == STALE_SOURCE and x.start >= STALE_FROM - 12 * H]
        ids += [x.batch_id for x in stale[:3]] + [stale[-1].batch_id]
        ids += [x.batch_id for x in w.batches if "unknown_op" in x.tags]
        ids += [x.batch_id for x in w.batches if "fresh_delay" in x.tags]
        part = [q for q in w.bf.values() if not q["refused"] and q["partial"]][:2] + [q for q in w.bf.values() if not q["refused"] and not q["partial"]][:1]
        ids += [x.batch_id for q in part for x in q["batches"]]
        return list(dict.fromkeys(ids))

    def choose_sample(self, cap: int) -> list[str]:
        w = self.w
        size = {b.batch_id: len(b.rows) for b in w.batches}
        chosen: list[str] = []
        total = 0
        for bid in self.evidence_batches():
            if total + size[bid] <= cap:
                chosen.append(bid)
                total += size[bid]
        rest = [b.batch_id for b in w.batches if b.batch_id not in set(chosen) and b.kind == "live"]
        w.rs["sample"].shuffle(rest)
        for bid in rest:
            if total + size[bid] <= cap:
                chosen.append(bid)
                total += size[bid]
        return sorted(chosen)

    def summaries(self, sample: set[str]) -> list[dict]:
        from collections import Counter
        w, facts = self.w, self.facts
        out = []
        for b in w.batches:
            row: dict[str, Any] = {"batch_id": b.batch_id, "source_id": b.src, "kind": b.kind, "status": b.status, "written_rows": len(b.rows), "sampled": b.batch_id in sample}
            if b.status == "committed":
                kinds = Counter(facts.disposition[f"rr-{b.batch_id}-{n:04d}"].kind for n in range(1, len(b.rows) + 1))
                row.update({"received": len(b.rows), "accepted_unique": kinds["accepted"], "duplicate": kinds["duplicate"], "quarantined": kinds["quarantined"], "deleted": kinds["deleted"],
                            "quarantine_by_reason": dict(sorted(Counter(facts.derived_reasons[b.batch_id]).items()))})
            else:
                row.update({"received": 0, "accepted_unique": 0, "duplicate": 0, "quarantined": 0, "deleted": 0,
                            "quarantine_by_reason": {"SCHEMA_CHANGED": len(b.rows)} if b.status == "quarantined" else {}})
            out.append(row)
        return out

    def assemble(self) -> None:
        w = self.w
        self.pm = self.processing_measurement()
        pub_of_run = {p["run_id"]: p["publication_id"] for p in w.pubs}
        self.totals = {pub_of_run[t["run_id"]]: t["total_amount"] for t in w.totals if t["run_id"] in pub_of_run}
        self.full_data = self.inputs(w.ents["raw_records"])
        self.imp, self.golden, self.facts = self.dom.run(self.full_data, self.totals)
        self.recon = self.dom.reconciliations(self.facts, [{"run_id": t["run_id"], "total_amount": t["total_amount"],
                                                            "included_batch_ids": t.get("included_batch_ids") or next(p["included_batch_ids"] for p in w.pubs if p["run_id"] == t["run_id"])}
                                                           for t in w.totals], self.totals)
        # --- what is published: the sample is the largest whole-batch selection that fits the cap
        cap = SAMPLE_CAP
        while True:
            sample_ids = self.choose_sample(cap)
            ents = self.published_entities(set(sample_ids))
            size = sum(len(entity_text(n, self.version, ents[n]).encode()) for n in PUBLISHED)
            if size <= SIZE_CAP - 120_000 or cap <= 100:
                break
            cap -= 100
        self.sample_ids, self.sample_cap, self.ents, self.entity_bytes = sample_ids, cap, ents, size
        self.pub_data = self.inputs(ents["raw_records"])
        self.imp_pub, self.golden_pub, self.facts_pub = self.dom.run(self.pub_data, self.totals)

    def published_entities(self, sample: set[str]) -> dict[str, list[dict]]:
        w = self.w
        ents = {k: w.ents[k] for k in PUBLISHED if k in w.ents}
        ents["raw_records"] = [r for r in w.ents["raw_records"] if r["batch_id"] in sample]
        ents["batch_summaries"] = self.summaries(sample)
        ents["fetch_log"] = w.fetch_rows()
        return ents


# ==================================================================================================================== numbers for the manifest
def rnd6(n: int, d: int) -> str | None:
    """n/d to 6 places, half up, integer arithmetic (the domain's ``rnd`` restated)."""
    if d == 0:
        return None
    q = (n * 10 ** 6 * 2 + d) // (2 * d)
    return f"{q // 10 ** 6}.{q % 10 ** 6:06d}"


class Numbers:
    """Everything the manifest states, taken from the domain's verdict (``golden``) and the rows; nothing is typed in."""

    def __init__(self, b: Built):
        self.b, self.w, self.g = b, b.w, b.golden
        self.m = b.golden["metrics"]

    def fetch_analysis(self) -> dict:
        fm = self.b.dom.mod["fetch"]
        tm = self.b.dom.parse_ts
        rows = self.w.fetch_rows()
        sess: dict[tuple, list[dict]] = {}
        for r in rows:
            sess.setdefault((r["source_id"], r["session_id"]), []).append(r)
        limited = retries = honoured = 0
        slacks: list[int] = []
        sessions = set()
        for (sid, ses), seq in sess.items():
            seq.sort(key=lambda r: (r["fetched_at"], r["fetch_id"]))
            for i, r in enumerate(seq):
                if r["status"] == "rate_limited":
                    limited += 1
                    sessions.add((sid, ses))
                    nxt = seq[i + 1]
                    retries += 1
                    try:
                        fm.check_retry_allowed(tm(r["fetched_at"]), r["retry_after_seconds"], tm(nxt["fetched_at"]))
                        honoured += 1
                    except Exception:
                        pass
                    slacks.append(int((tm(nxt["fetched_at"]) - tm(r["fetched_at"])).total_seconds()) - r["retry_after_seconds"])
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        return {"source_id": RATE_LIMITED_SOURCE, "fetch_log_statuses": dict(sorted(by_status.items())), "rate_limited_responses": limited, "retries": retries, "retries_honouring_retry_after": honoured,
                "retries_too_soon": retries - honoured, "min_slack_seconds": min(slacks), "max_slack_seconds": max(slacks), "sessions_rate_limited": len(sessions),
                "sources_rate_limited": sorted({s for s, _ in sessions}),
                "cursor_loops": sum(1 for r in rows if r["status"] == "cursor_loop"), "fetch_rows": len(rows)}

    def late_split(self) -> dict:
        kind = {x.batch_id: x.kind for x in self.w.batches}
        designed = {e.key for e in self.w.events[LATE_SOURCE] if e.hold == "late"}
        ev = self.m["late_events"]["events"]
        out = {"designed": 0, "corrections": 0, "backfill": 0}
        for e in ev:
            if e["source_key"] in designed:
                out["designed"] += 1
            elif kind[e["batch_id"]] == "backfill":
                out["backfill"] += 1
            else:
                out["corrections"] += 1
        return out

    def residual_days(self) -> list[dict]:
        run_day = {r["run_id"]: r["started_at"][:10] for r in self.w.runs}
        return [{"run_id": r["run_id"], "day": run_day[r["run_id"]], "residual": r["residual"], "source_total": r["source_total"], "published_total": r["published_total"],
                 "exclusions_total": r["exclusions_total"]} for r in self.b.recon if r["residual"] != "0.00"]

    def completeness_by_source(self) -> dict:
        out = {}
        for sid, parts in self.m["completeness"].items():
            exp = sum(p["expected_records"] for p in parts.values())
            acc = sum(p["accepted_records"] for p in parts.values())
            out[sid] = {"partitions": len(parts), "expected_records": exp, "accepted_records": acc, "value": rnd6(acc, exp)}
        return out

    def stats(self) -> dict:
        m, w = self.m, self.w
        ing = m["ingestion"]
        quar_rows = {}
        for q in self.b.ents["quarantine_records"]:
            quar_rows[q["reason_code"]] = quar_rows.get(q["reason_code"], 0) + 1
        by_reason: dict[str, int] = {}
        for s in ing["sources"].values():
            for k, v in s["quarantine_by_reason"].items():
                by_reason[k] = by_reason.get(k, 0) + v
        gates = m["quality_gate"]
        n_allowed = sum(1 for g_ in gates.values() if g_["decision"] == "allowed")
        reached = sum(1 for g_ in gates.values() if g_["results"])             # a run reached the gate when the gate recorded at least one result for it
        funnel = {"runs": len(gates), "reached_gate": reached, "allowed": n_allowed, "blocked_at_gate": sum(1 for g_ in gates.values() if g_["results"] and g_["decision"] == "blocked"),
                  "failed_before_gate": len(gates) - reached}
        assert funnel["reached_gate"] == funnel["allowed"] + funnel["blocked_at_gate"] and all(r["status"] == "failed" for r in w.runs if not gates[r["run_id"]]["results"])
        bf_req = m["backfills"]["requests"]
        refused_ids = m["backfills"]["refused"]
        refused_parts = sum(len(x["partitions"]) for x in w.ents["backfill_requests"] if x["backfill_id"] in refused_ids)
        bo = m["backfills"]["overall"]
        bf_statement = (f"{bo['verified_partitions']} of {bo['requested_partitions']} partitions of the {len(bf_req)} accepted requests ({bo['coverage']}); "
                        f"{len(refused_ids)} requests for {refused_parts} partitions refused for overlap")
        runs = m["runs"]
        inc = m["incidents"]
        kinds: dict[str, int] = {}
        for x in w.batches:
            kinds[x.kind] = kinds.get(x.kind, 0) + 1
        by_type: dict[str, int] = {}
        for i in w.incidents:
            by_type[i["_plan"]] = by_type.get(i["_plan"], 0) + 1
        return {
            "batches_by_kind": dict(sorted(kinds.items())),
            "ingestion": {"overall": ing["overall"], "sources": {sid: {k: v for k, v in s.items() if k not in ("batches", "checkpoint")} | {"checkpoint_version": s["checkpoint"]["committed_version"]}
                                                          for sid, s in ing["sources"].items()}},
            "quarantine_by_reason_committed_batches": dict(sorted(by_reason.items())),
            "quarantine_scope": {"counted_in": "committed batches (the headline quarantined count and rejection rate)",
                                 "rows_listed_separately": sum(1 for q in self.b.ents["quarantine_records"] if q["reason_code"] == "SCHEMA_CHANGED"),
                                 "listed_separately_because": "the rows of the one batch quarantined whole (SCHEMA_CHANGED) belong to no committed batch; their quarantine rows are listed, never counted in the rate"},
            "quarantine_rows_by_reason": dict(sorted(quar_rows.items())),
            "freshness_at_as_of": m["freshness"],
            "completeness_by_source": self.completeness_by_source(),
            "runs": {"overall": runs["overall"], "successful": {k: runs["durations"]["successful"][k] for k in ("count", "mean_minutes")},
                     "failed": {k: runs["durations"]["failed"][k] for k in ("count", "mean_minutes")}, "backfill_runs": sum(1 for r in w.runs if r["backfill_id"])},
            "quality_gate": funnel,
            "publications": {"count": len(m["publications"]["publications"]), "current_publication_id": m["publications"]["current_publication_id"],
                             "first_published_at": w.pubs[0]["published_at"], "last_published_at": w.pubs[-1]["published_at"],
                             "content_hash_ok": sum(1 for p in m["publications"]["publications"].values() if p["content_hash_ok"])},
            "late_events": {"count": m["late_events"]["count"], "included_in_next_publication": m["late_events"]["included_in_next_publication"],
                            "lost": m["late_events"]["lost"], "by_cause": self.late_split()},
            "reconciliation": {"publications": len(m["reconciliation"]), "residual_not_zero": sum(1 for r in m["reconciliation"].values() if r["residual"] != "0.00"),
                               "candidates": len(self.b.recon), "candidates_residual_not_zero": len(self.residual_days())},
            "incidents": {"total": inc["total"], "open": inc["open"], "closed": inc["closed"], "verified": inc["verified"], "mean_recovery_minutes": inc["mean_recovery_minutes"],
                          "by_type": dict(sorted(by_type.items())), "all_closures_consistent": all(i["closure_consistent"] for i in inc["incidents"].values())},
            "backfills": {"overall": m["backfills"]["overall"], "accepted_requests": len(bf_req), "refused_requests": len(refused_ids), "refused_partitions": refused_parts,
                          "statement": bf_statement, "refused": m["backfills"]["refused"], "requests": {k: {"source_id": v["source_id"], "requested_partitions": v["requested_partitions"],
                                                                                                                     "verified_partitions": v["verified_partitions"], "coverage": v["coverage"]}
                                                                           for k, v in m["backfills"]["requests"].items()}},
            "processing_rate": m["processing_rate"],
            "models": {layer: sum(1 for x in w.models if x["layer"] == layer) for layer in ("staging", "intermediate", "marts")},
            "retry": self.fetch_analysis(),
        }

    def stats_funnel(self) -> dict:
        gates = self.m["quality_gate"]
        reached = sum(1 for g_ in gates.values() if g_["results"])
        n_allowed = sum(1 for g_ in gates.values() if g_["decision"] == "allowed")
        return {"runs": len(gates), "reached_gate": reached, "allowed": n_allowed, "blocked_at_gate": reached - n_allowed, "failed_before_gate": len(gates) - reached}

    def designed(self) -> list[dict]:
        b, w, m = self.b, self.w, self.m
        dr = []
        # DR-01
        fr = m["freshness"][STALE_SOURCE]
        stale_runs = [r for r in w.runs if r["started_at"] >= iso(STALE_FROM)]
        allowed = sum(1 for r in stale_runs if m["quality_gate"][r["run_id"]]["decision"] == "allowed")
        stale_batches = [x for x in w.batches if x.src == STALE_SOURCE and x.start >= STALE_FROM]
        comp = m["completeness"][STALE_SOURCE]
        dr.append({"id": "DR-01", "name": "a source stale for three days while its jobs stay green",
                   "statement": "src-refunds stops delivering new events at 2026-10-02T00:00:00Z; its batches keep committing (the same page again) and every run stays green.",
                   "parameters": {"source_id": STALE_SOURCE, "stops_at": iso(STALE_FROM), "freshness_target_seconds": SRC[STALE_SOURCE]["target"], "declared_frequency": SRC[STALE_SOURCE]["freq"],
                                  "replayed_rows_per_batch": STALE_REPLAY_ROWS},
                   "realised": {"freshness_seconds": fr["freshness_seconds"], "ingestion_age_seconds": fr["ingestion_age_seconds"], "latest_accepted_event_at": fr["latest_accepted_event_at"],
                                "last_successful_ingestion_at": fr["last_successful_ingestion_at"], "committed_batches_in_window": len(stale_batches),
                                "duplicates_in_window": sum(sum(1 for r in x.rows if r["disp"] == "duplicate") for x in stale_batches),
                                "batches_with_no_accepted_record": sum(1 for x in stale_batches if not any(r["disp"] == "accepted" for r in x.rows)),
                                "accepted_in_window": sum(sum(1 for r in x.rows if r["disp"] == "accepted") for x in stale_batches),
                                "runs_in_window": len(stale_runs), "runs_allowed_by_the_gate": allowed, "runs_succeeded": sum(1 for r in stale_runs if r["status"] == "success"),
                                "completeness": {d: comp[d]["value"] for d in sorted(comp) if d >= "2026-10-02"}}})
        # DR-02
        run = next(r for r in w.runs if r["started_at"] == iso(w.inj07_tick + RUN_OFFSET_S))
        hist = m["publications"]["pointer_history"]
        i = next(j for j, h in enumerate(hist) if h["run_id"] == run["run_id"])
        gate = m["quality_gate"][run["run_id"]]
        inc = next(x for x in w.incidents if x["run_id"] == run["run_id"])
        dr.append({"id": "DR-02", "name": "a failed run that never replaces the publication",
                   "statement": "A run whose critical relationships check fails is blocked, opens an incident and publishes nothing; the pointer stays where it was.",
                   "parameters": {"rule": "the second relationships failure in time order is the designated run (P08-TEST-07)", "failure": "relationships_intact critical check, one orphan output row"},
                   "realised": {"run_id": run["run_id"], "run_status": run["status"], "gate_decision": gate["decision"], "critical_failures": gate["critical_failures"],
                                "publication_exists": any(p["run_id"] == run["run_id"] for p in w.pubs), "pointer_before": hist[i - 1]["pointer_after"],
                                "pointer_after": hist[i]["pointer_after"], "pointer_unchanged": hist[i]["pointer_after"] == hist[i - 1]["pointer_after"], "pointer_history_index": i,
                                "incident_id": inc["incident_id"], "recovery_run_id": inc["recovery_run_id"],
                                "recovery_minutes": m["incidents"]["incidents"][inc["incident_id"]]["recovery_minutes"],
                                "gate_funnel": self.stats_funnel()}})
        # DR-03
        fa = self.fetch_analysis()
        dr.append({"id": "DR-03", "name": "a rate-limited source whose retries honour retry-after",
                   "statement": "src-shipments answers some fetches with 429 and a retry-after; every retry waits at least that long.",
                   "parameters": {"source_id": RATE_LIMITED_SOURCE, "rate_limit_ppm": RATE_LIMIT_PPM, "retry_after_choices_seconds": list(RETRY_AFTER_CHOICES),
                                  "second_429_ppm": 300_000, "retry_slack_seconds": "0..25"},
                   "realised": fa})
        # DR-04
        split = self.late_split()
        designed_keys = sorted(e.key for e in w.events[LATE_SOURCE] if e.hold == "late")
        ev = {e["source_key"]: e for e in m["late_events"]["events"]}
        dr.append({"id": "DR-04", "name": "late events behind the watermark, included in the next publication",
                   "statement": "Nine src-orders events dated before the watermark of the preceding publication arrive in one later batch; each is accepted and enters the next publication.",
                   "parameters": {"source_id": LATE_SOURCE, "events": LATE_N, "event_window": "2026-09-17T18:00:00Z..2026-09-17T23:50:00Z", "delivered_in_the_batch_of": iso(int(LATE_SLOT.timestamp())),
                                  "watermark_rule": "the earliest, over all sources, of the end of the window of the latest committed batch"},
                   "realised": {"designed_events": split["designed"], "late_events_in_all": m["late_events"]["count"], "by_cause": split, "included_in_next_publication": m["late_events"]["included_in_next_publication"],
                                "lost": m["late_events"]["lost"], "designed": [{"source_key": k, "event_at": ev[k]["event_at"], "arrival_at": ev[k]["arrival_at"], "behind_publication_id": ev[k]["behind_publication_id"],
                                                                                "watermark": ev[k]["watermark"], "included_in_publication_id": ev[k]["included_in_publication_id"]} for k in designed_keys if k in ev]}})
        # DR-05
        nz = self.residual_days()
        inc5 = next(x for x in w.incidents if x["_plan"] == "residual")
        dr.append({"id": "DR-05", "name": "residual zero except one day with an unexplained residual",
                   "statement": "Every publication reconciles to 0.00; on one day the transform of one run read the staged rows of a crashed batch, the candidate reconciliation was off by their amount, the gate blocked and an incident opened.",
                   "parameters": {"day": RESIDUAL_TICK.strftime("%Y-%m-%d"), "tick": iso(int(RESIDUAL_TICK.timestamp())),
                                  "amount": f"the candidate table holds the amount of the first {LEAK_ROWS} new records of the crashed payments batch {w.leak_batch_id} beyond the accepted records of its scope",
                                  "cause_recorded": "none: no quarantine, duplicate or delete accounts for it"},
                   "realised": {"publications_with_nonzero_residual": sum(1 for r in m["reconciliation"].values() if r["residual"] != "0.00"), "publications": len(m["reconciliation"]),
                                "candidates_with_nonzero_residual": nz, "days_with_nonzero_residual": sorted({x["day"] for x in nz}),
                                "incident_id": inc5["incident_id"], "incident_run_id": inc5["run_id"], "recovery_run_id": inc5["recovery_run_id"],
                                "recovery_minutes": m["incidents"]["incidents"][inc5["incident_id"]]["recovery_minutes"],
                                "leaked_rows": LEAK_ROWS, "leak_batch_id": w.leak_batch_id}})
        return dr


# ==================================================================================================================== the twelve injected defects
WORKFLOW_BAD = """name: refresh-generated-evidence
on:
  push:
    branches: [main]
permissions:
  contents: write
jobs:
  refresh:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - run: python data/generate.py
      - run: |
          git config user.name synthetic-bot
          git add -A
          git commit -m "refresh generated evidence"
          git push origin main
"""
WORKFLOW_GOOD = WORKFLOW_BAD.replace('git commit -m "refresh generated evidence"', 'git commit -m "refresh generated evidence [skip ci]"')
LOG_LINE = ('{"event":"fetch","level":"INFO","msg":"retrying src-shipments","api_key":"SYNTHETIC-NOT-A-KEY-0001",'
            '"headers":{"Authorization":"Bearer SYNTHETICTOKEN0000"},"url":"https://api.example.test/shipments?token=SYNTHETIC-TOKEN-0002"}')
LOG_SECRETS = ("SYNTHETIC-NOT-A-KEY-0001", "SYNTHETICTOKEN0000", "SYNTHETIC-TOKEN-0002")
H_ENG = {"X-Actor-Id": "usr-eng01", "X-Actor-Role": "engineer"}
H_OP = {"X-Actor-Id": "usr-op01", "X-Actor-Role": "operator"}


class Injections:
    def __init__(self, b: Built, nums: Numbers):
        self.b, self.w, self.n, self.m = b, b.w, nums, b.golden["metrics"]
        self.ver = b.version

    # --- replay step builders -----------------------------------------------------------------------------------------------------------
    def cmd(self, ev: str, n: str, name: str, t: str, hdr: dict, inp: dict, status: int, reason: str | None = None, body: dict | None = None,
            warnings: list[str] | None = None, headers: dict | None = None) -> dict:
        s: dict[str, Any] = {"kind": "command", "command": name, "at": t, "headers": hdr,
                             "input": {"request_id": f"req-{ev}-{n}", "dataset_version": self.ver, "idempotency_key": f"{ev}-{n}", "input": inp}, "expected_status": status}
        if reason:
            s["expected_reason"] = reason
        if body:
            s["expected_body"] = body
        if warnings:
            s["expected_warning_codes"] = warnings
        if headers:
            s["expected_headers"] = headers
        return s

    @staticmethod
    def read(t: str, path: str, params: dict, expect: list[dict]) -> dict:
        return {"kind": "read", "at": t, "path": path, "params": params, "expect": expect, "expected_status": 200}

    @staticmethod
    def rec(key: str | None, qty: int = 1, price: str = "10.00", ts: str = "2026-10-04T23:40:00Z", **extra: Any) -> dict:
        p = {"quantity": qty, "unit_price": price, "amount": cents(int(price.replace(".", "")) * qty), "event_ts": ts, **extra}
        if key is not None:
            p["record_id"] = key
        return {"payload": p}

    def ingest(self, ev: str, n: str, src: str, bid: str, cursor: str, nxt: str, recs: list[dict], t: str, validate: bool = True, commit: bool = True,
               hdr: dict | None = None, **page: Any) -> list[dict]:
        hdr = hdr or H_ENG
        steps = [self.cmd(ev, n + "-fetch", "fetch-source-page", t, hdr, {"source_id": src, "cursor": cursor, "batch_id": bid, "fetch_session": f"{ev}-{n}",
                                                                          "page": {"records": recs, "next_cursor": nxt, **page}}, 200, body={"status": "staged"})]
        if validate:
            steps.append(self.cmd(ev, n + "-validate", "validate-contract", t, hdr, {"batch_id": bid}, 200))
        if commit:
            steps.append(self.cmd(ev, n + "-commit", "commit-batch", t, hdr, {"batch_id": bid}, 200, body={"status": "committed"}))
        return steps

    def pipeline(self, ev: str, n: str, run: str, batches: list[str], t: str, wm: str, scope_from: str, publish: bool = True) -> list[dict]:
        """One run. ``scope_from`` declares the run's scope: the batches committed from there to the run's start (D-09: the gate fails a run that leaves one out)."""
        steps = [self.cmd(ev, n + "-transform", "transform-models", t, H_OP, {"run_id": run, "batch_ids": batches, "scope_from": scope_from}, 200),
                 self.cmd(ev, n + "-gate", "run-quality-gate", t, H_OP, {"run_id": run}, 200, body={"status": "allowed"})]
        if publish:
            steps.append(self.cmd(ev, n + "-publish", "publish-snapshot", t, H_OP, {"run_id": run, "watermark": wm}, 200, body={"status": "published"}))
        return steps

    # --- the events ------------------------------------------------------------------------------------------------------------------
    def events(self) -> list[dict]:
        w, m = self.w, self.m
        T = lambda hhmmss: f"2026-10-05T{hhmmss}Z"          # noqa: E731
        order_version = max(c.version for c in w.committed if c.src == "src-orders")
        last_pub = m["publications"]["current_publication_id"]
        evs: list[dict] = []
        # EV-01 crash after the write, before the checkpoint
        r3 = [self.rec(f"INJ-CR-{i}", ts=f"2026-10-04T23:{40 + i}:00Z") for i in range(1, 4)]
        s = self.ingest("ev-01", "a", "src-orders", "b-ev01-a", "off-ev01", "off-ev01-n", r3, T("00:30:00"), commit=False)
        s += [self.cmd("ev-01", "fault", "inject-fault", T("00:31:00"), H_OP, {"fault_type": "crash_before_checkpoint", "target_id": "src-orders", "note": "P08-TEST-01"}, 200, body={"result": {"armed": True}}),
              self.cmd("ev-01", "crash", "commit-batch", T("00:32:00"), H_ENG, {"batch_id": "b-ev01-a"}, 500, reason="INJECTED_CRASH"),
              self.read(T("00:32:30"), "/data/accepted_records", {"batch_id": "b-ev01-a"}, [{"path": "meta.total_count", "equals": 0}]),
              self.cmd("ev-01", "retry", "commit-batch", T("00:33:00"), H_ENG, {"batch_id": "b-ev01-a"}, 200,
                       body={"result": {"accepted_unique": 3, "duplicate": 0, "checkpoint": {"version_number": order_version + 1}}}),
              self.read(T("00:33:30"), "/data/accepted_records", {"batch_id": "b-ev01-a"}, [{"path": "meta.total_count", "equals": 3}])]
        s += self.ingest("ev-01", "b", "src-orders", "b-ev01-b", "off-ev01", "off-ev01-n", r3, T("00:34:00"), commit=False)
        s += [self.cmd("ev-01", "b-commit", "commit-batch", T("00:35:00"), H_ENG, {"batch_id": "b-ev01-b"}, 200,
                       body={"result": {"accepted_unique": 0, "duplicate": 3, "checkpoint": {"version_number": order_version + 2}}})]
        evs.append({"event_id": "EV-01", "injection": "INJ-01", "requires": [], "steps": s})
        # EV-02 overlapping backfills
        s = [self.cmd("ev-02", "a", "request-backfill", T("01:00:00"), H_ENG, {"source_id": "src-inventory", "start_at": "2026-10-07T00:00:00Z", "end_at": "2026-10-09T00:00:00Z"}, 200,
                      body={"result": {"backfill_id": "bf-016", "requested_partitions": 2}}),
             self.cmd("ev-02", "b", "request-backfill", T("01:01:00"), H_ENG, {"source_id": "src-inventory", "start_at": "2026-10-08T00:00:00Z", "end_at": "2026-10-10T00:00:00Z"}, 409,
                      reason="BACKFILL_OVERLAP"),
             self.cmd("ev-02", "c", "request-backfill", T("01:02:00"), H_ENG, {"source_id": "src-inventory", "start_at": "2026-10-09T00:00:00Z", "end_at": "2026-10-11T00:00:00Z"}, 200,
                      body={"result": {"backfill_id": "bf-018"}}),
             self.read(T("01:03:00"), "/data/rejected_records", {"entity": "backfill_requests", "reason_code": "BACKFILL_OVERLAP"}, [{"path": "meta.total_count", "equals": 3}])]
        evs.append({"event_id": "EV-02", "injection": "INJ-02", "requires": ["bf-006", "bf-012"], "steps": s})
        # EV-03 a retry that ignores retry-after
        rec1 = [self.rec("INJ-RA-1", ts="2026-10-04T23:30:00Z")]
        s = [self.cmd("ev-03", "a", "fetch-source-page", T("01:30:00"), H_ENG, {"source_id": "src-shipments", "cursor": "off-ev03", "fetch_session": "ev03-s", "page": {"status": 429, "retry_after_seconds": 90}}, 200,
                      body={"status": "rate_limited", "result": {"retry_not_before": T("01:31:30")}}),
             self.cmd("ev-03", "b", "fetch-source-page", T("01:30:12"), H_ENG, {"source_id": "src-shipments", "cursor": "off-ev03", "batch_id": "b-ev03", "fetch_session": "ev03-s", "page": {"records": rec1, "next_cursor": "off-ev03-n"}}, 429,
                      reason="RETRY_TOO_SOON", headers={"Retry-After": "78"}),
             self.cmd("ev-03", "c", "fetch-source-page", T("01:31:30"), H_ENG, {"source_id": "src-shipments", "cursor": "off-ev03", "batch_id": "b-ev03", "fetch_session": "ev03-s", "page": {"records": rec1, "next_cursor": "off-ev03-n"}}, 200,
                      body={"status": "staged"}),
             self.read(T("01:32:00"), "/data/fetch_log", {"source_id": "src-shipments", "status": "rate_limited"}, [{"path": "meta.total_count", "equals": 1}])]
        evs.append({"event_id": "EV-03", "injection": "INJ-03", "requires": [], "steps": s})
        # EV-04 an unexpected required field
        r2 = [self.rec(f"INJ-SC-{i}", ts=f"2026-10-04T23:{50 + i}:00Z", channel="web", currency="EUR") for i in (1, 2)]
        s = [self.cmd("ev-04", "a-fetch", "fetch-source-page", T("02:00:00"), H_ENG, {"source_id": "src-payments", "cursor": "off-ev04", "batch_id": "b-ev04-a", "fetch_session": "ev04-a", "page": {"records": r2, "next_cursor": "off-ev04-n", "schema_version": "3"}}, 200),
             self.cmd("ev-04", "a-validate", "validate-contract", T("02:00:10"), H_ENG, {"batch_id": "b-ev04-a"}, 200, body={"status": "quarantined", "result": {"quarantine_by_reason": {"SCHEMA_CHANGED": 2}}},
                      warnings=["SCHEMA_CHANGED"]),
             self.cmd("ev-04", "a-commit", "commit-batch", T("02:00:20"), H_ENG, {"batch_id": "b-ev04-a"}, 409, reason="BATCH_QUARANTINED"),
             self.cmd("ev-04", "b-fetch", "fetch-source-page", T("02:30:00"), H_ENG, {"source_id": "src-payments", "cursor": "off-ev04", "batch_id": "b-ev04-b", "fetch_session": "ev04-b", "page": {"records": r2, "next_cursor": "off-ev04-n", "schema_version": "3"}}, 200),
             self.cmd("ev-04", "b-bump-engineer", "validate-contract", T("02:30:10"), H_ENG, {"batch_id": "b-ev04-b", "bump_schema_version": "3"}, 403, reason="ROLE_FORBIDDEN"),
             self.cmd("ev-04", "b-bump", "validate-contract", T("02:30:20"), H_OP, {"batch_id": "b-ev04-b", "bump_schema_version": "3"}, 200, body={"status": "validated", "result": {"accepted_unique": 2}}),
             self.cmd("ev-04", "b-commit", "commit-batch", T("02:30:30"), H_OP, {"batch_id": "b-ev04-b"}, 200, body={"result": {"accepted_unique": 2}})]
        evs.append({"event_id": "EV-04", "injection": "INJ-04", "requires": [], "steps": s})
        # EV-05 a malformed row that would vanish
        recs = [self.rec("INJ-MF-1", ts="2026-10-04T23:40:00Z"), self.rec(None, ts="2026-10-04T23:41:00Z"), self.rec("INJ-MF-3", ts="2026-10-04T23:42:00Z")]
        recs[2]["payload"]["amount"] = "12,50"
        s = self.ingest("ev-05", "a", "src-orders", "b-ev05", "off-ev05", "off-ev05-n", recs, T("02:40:00"), commit=False)
        s[1]["expected_body"] = {"result": {"received": 3, "accepted_unique": 1, "quarantined": 2, "quarantine_by_reason": {"INVALID_FIELD": 1, "MISSING_FIELD": 1}}}
        s += [self.cmd("ev-05", "commit", "commit-batch", T("02:40:30"), H_ENG, {"batch_id": "b-ev05"}, 200, body={"result": {"received": 3, "accepted_unique": 1, "quarantined": 2}}),
              self.read(T("02:41:00"), "/data/quarantine_records", {"batch_id": "b-ev05"}, [{"path": "meta.total_count", "equals": 2}]),
              self.read(T("02:41:10"), "/data/raw_records", {"batch_id": "b-ev05"}, [{"path": "meta.total_count", "equals": 3}])]
        evs.append({"event_id": "EV-05", "injection": "INJ-05", "requires": [], "steps": s})
        # EV-06 a green job on a stale source
        fr = self.m["freshness"][STALE_SOURCE]
        comp = self.m["completeness"][STALE_SOURCE]
        s = [self.read(T("03:00:00"), "/metrics", {"cutoff": AS_OF, "source_id": STALE_SOURCE},
                       [{"path": f"data.metrics.freshness.{STALE_SOURCE}.freshness_seconds", "equals": fr["freshness_seconds"]},
                        {"path": f"data.metrics.freshness.{STALE_SOURCE}.ingestion_age_seconds", "equals": fr["ingestion_age_seconds"]},
                        {"path": "data.metrics.completeness.src-refunds.2026-10-03.value", "equals": comp["2026-10-03"]["value"]}])]
        evs.append({"event_id": "EV-06", "injection": "INJ-06", "requires": [STALE_SOURCE], "steps": s})
        # EV-07 a failed run never replaces the publication
        r3 = [self.rec(f"INJ-FR-{i}", ts=f"2026-10-04T23:{40 + i}:00Z", price=f"{i}0.00") for i in range(1, 4)]
        s = self.ingest("ev-07", "a", "src-orders", "b-ev07", "off-ev07", "off-ev07-n", r3, T("03:30:00"))
        s += [self.cmd("ev-07", "transform", "transform-models", T("03:31:00"), H_OP, {"run_id": "run-ev07", "batch_ids": ["b-ev07"], "scope_from": T("03:30:00")}, 200),
              self.cmd("ev-07", "fault", "inject-fault", T("03:32:00"), H_OP, {"fault_type": "duplicate_key", "target_id": "run-ev07", "note": "P08-TEST-07"}, 200),
              self.cmd("ev-07", "gate", "run-quality-gate", T("03:33:00"), H_OP, {"run_id": "run-ev07"}, 200, body={"status": "blocked", "result": {"decision": "blocked", "critical_failures": 2}}, warnings=["GATE_BLOCKED"]),
              self.cmd("ev-07", "publish", "publish-snapshot", T("03:34:00"), H_OP, {"run_id": "run-ev07", "watermark": T("03:00:00")}, 409, reason="RUN_NOT_SUCCESSFUL"),
              self.read(T("03:35:00"), "/data/publication_pointer", {}, [{"path": "data.0.publication_id", "equals": last_pub}]),
              self.read(T("03:35:10"), "/data/publications", {"run_id": "run-ev07"}, [{"path": "meta.total_count", "equals": 0}]),
              self.read(T("03:35:20"), "/data/incidents", {"run_id": "run-ev07"}, [{"path": "meta.total_count", "equals": 1}, {"path": "data.0.status", "equals": "open"}])]
        evs.append({"event_id": "EV-07", "injection": "INJ-07", "requires": [last_pub], "steps": s})
        # EV-08 a delete that must propagate
        a = [self.rec("INJ-DEL-1", price="10.00", ts="2026-10-04T23:40:00Z"), self.rec("INJ-DEL-2", price="20.00", ts="2026-10-04T23:41:00Z")]
        dl = [{"payload": {"record_id": "INJ-DEL-1", "op": "delete", "amount": "0.00", "event_ts": "2026-10-04T23:50:00Z"}},
              {"payload": {"record_id": "INJ-DEL-404", "op": "delete", "amount": "0.00", "event_ts": "2026-10-04T23:51:00Z"}}]
        s = self.ingest("ev-08", "a", "src-orders", "b-ev08-a", "off-ev08", "off-ev08-n", a, T("04:00:00"))
        s += self.ingest("ev-08", "b", "src-orders", "b-ev08-b", "off-ev08-n", "off-ev08-m", dl, T("04:10:00"), commit=False)
        s[-1]["expected_body"] = {"result": {"deleted": 1, "quarantined": 1, "quarantine_by_reason": {"DELETE_TARGET_UNKNOWN": 1}}}
        s += [self.cmd("ev-08", "b-commit", "commit-batch", T("04:10:30"), H_ENG, {"batch_id": "b-ev08-b"}, 200, body={"result": {"deleted": 1, "quarantined": 1}}),
              self.cmd("ev-08", "transform", "transform-models", T("04:11:00"), H_OP, {"run_id": "run-ev08", "batch_ids": ["b-ev08-a", "b-ev08-b"], "scope_from": T("04:00:00")}, 200, body={"result": {"outputs": 1}}),
              self.cmd("ev-08", "gate", "run-quality-gate", T("04:12:00"), H_OP, {"run_id": "run-ev08"}, 200,
                       body={"status": "allowed", "result": {"reconciliation": {"exclusions": {"deletes": "10.00", "quarantined": "0.00", "duplicates": "0.00"}, "residual": "0.00"}}}),
              self.cmd("ev-08", "publish", "publish-snapshot", T("04:13:00"), H_OP, {"run_id": "run-ev08", "watermark": T("04:00:00")}, 200, body={"result": {"published_records": 1}})]
        evs.append({"event_id": "EV-08", "injection": "INJ-08", "requires": [], "steps": s})
        # EV-09 a late event behind the watermark
        s = self.ingest("ev-09", "a", "src-orders", "b-ev09-a", "off-ev09", "off-ev09-a", [self.rec("INJ-LATE-0", ts="2026-10-05T00:00:00Z"), self.rec("INJ-LATE-00", ts="2026-10-05T00:01:00Z")], T("04:30:00"))
        s += self.pipeline("ev-09", "x", "run-ev09x", ["b-ev09-a"], T("04:31:00"), T("04:20:00"), T("04:30:00"))
        s += self.ingest("ev-09", "b", "src-orders", "b-ev09-b", "off-ev09-a", "off-ev09-b", [self.rec("INJ-LATE-1", ts="2026-10-05T00:10:00Z")], T("04:40:00"))
        s += self.pipeline("ev-09", "y", "run-ev09y", ["b-ev09-a", "b-ev09-b"], T("04:50:00"), T("04:45:00"), T("04:30:00"))
        s += [self.read(T("05:00:00"), "/metrics", {"cutoff": T("05:00:00"), "source_id": "src-orders"},
                        [{"path": "data.metrics.late_events.events", "find": {"source_key": "INJ-LATE-1"},
                          "equals": {"behind_publication_id": "pub-ev09x", "included_in_publication_id": "pub-ev09y", "batch_id": "b-ev09-b"}}])]
        evs.append({"event_id": "EV-09", "injection": "INJ-09", "requires": [], "steps": s})
        # EV-10 a pagination token that repeats
        seq = [("c0", "c1"), ("c1", "c2"), ("c2", "c1")]
        s = []
        for n, (c, nx) in enumerate(seq):
            s.append(self.cmd("ev-10", f"p{n}", "fetch-source-page", T("05:30:00"), H_ENG, {"source_id": "src-web-events", "cursor": c, "fetch_session": "ev10-s1",
                                                                                          "page": {"records": [self.rec(f"INJ-CL-{n}", ts="2026-10-04T23:30:00Z")], "next_cursor": nx}},
                              409 if n == 2 else 200, reason="CURSOR_LOOP" if n == 2 else None))
        s += [self.cmd("ev-10", "stopped", "fetch-source-page", T("05:31:00"), H_ENG, {"source_id": "src-web-events", "cursor": "c9", "fetch_session": "ev10-s1", "page": {"records": [], "next_cursor": "c10"}}, 409, reason="CURSOR_LOOP"),
              self.cmd("ev-10", "new-session", "fetch-source-page", T("05:32:00"), H_ENG, {"source_id": "src-web-events", "cursor": "c9", "fetch_session": "ev10-s2", "page": {"records": [], "next_cursor": "c10"}}, 200),
              self.read(T("05:33:00"), "/data/fetch_log", {"source_id": "src-web-events", "status": "cursor_loop"}, [{"path": "meta.total_count", "equals": 1}])]
        evs.append({"event_id": "EV-10", "injection": "INJ-10", "requires": [], "steps": s})
        # EV-11 a secret in a structured log line
        note = "retry with api_key=SYNTHETIC-NOT-A-KEY-0001 and Authorization: Bearer SYNTHETICTOKEN0000"
        s = [self.cmd("ev-11", "fault", "inject-fault", T("06:00:00"), H_OP, {"fault_type": "crash_before_checkpoint", "target_id": "src-web-events", "note": note}, 200),
             self.read(T("06:00:30"), "/data/fault_injections", {"target_id": "src-web-events"},
                       [{"path": "data.0.note", "contains": "[REDACTED]"}, {"path": "data.0.note", "not_contains": LOG_SECRETS[0]}, {"path": "data.0.note", "not_contains": LOG_SECRETS[1]}]),
             {"kind": "check", "fn": "redaction.safe_line", "args": {"line": LOG_LINE}, "expect_contains": ["[REDACTED]"], "expect_not_contains": list(LOG_SECRETS)}]
        evs.append({"event_id": "EV-11", "injection": "INJ-11", "requires": [], "steps": s})
        # EV-12 a workflow that triggers itself
        s = [{"kind": "check", "fn": "workflow_guard.analyze", "args": {"text": WORKFLOW_BAD, "file_name": "refresh-generated-evidence.yml"}, "expect_codes": ["SELF_PUSH"]},
             {"kind": "check", "fn": "workflow_guard.analyze", "args": {"text": WORKFLOW_GOOD, "file_name": "refresh-generated-evidence.yml"}, "expect_codes": []}]
        evs.append({"event_id": "EV-12", "injection": "INJ-12", "requires": [], "steps": s})
        return evs

    # --- the manifest entries ------------------------------------------------------------------------------------------------------------
    def bf_settled(self, bf_id: str) -> str | None:
        return next((r["settled_at"] for r in self.b.ents["backfill_requests"] if r["backfill_id"] == bf_id), None)

    def entries(self) -> list[dict]:
        b, w, m = self.b, self.w, self.m
        ents = b.ents
        ing = m["ingestion"]["sources"]

        def bpath(sid: str, bid: str, leaf: str) -> str:
            return f"metrics.ingestion.sources.{sid}.batches.{bid}.{leaf}"
        out: list[dict] = []

        def add(n: int, name: str, test: str, defect: str, handling: str, location: str, records: list[dict], checks: list[dict], events: list[str], evidence: dict | None = None,
                rejections: list[dict] | None = None) -> None:
            out.append({"id": f"INJ-{n:02d}", "test": f"P08-TEST-{n:02d}", "name": name, "defect": defect, "expected_handling": handling, "location": location,
                        "records": records, "checks": checks, "events": events, "expected_rejections": rejections or [], "evidence": evidence or {}})
        # 01
        A = next(x for x in w.batches if x.kind == "aborted" and "inj01" in x.tags)
        R = next(x for x in w.batches if x.kind == "replay" and x.src == A.src and x.slot == A.slot)
        accR = sum(1 for r in R.rows if r["disp"] == "accepted")
        add(1, "crash after the data write, before the checkpoint", "P08-TEST-01",
            f"The ingest of {A.batch_id} wrote its {len(A.rows)} rows and died before the checkpoint; the batch was re-fetched from the same cursor as {R.batch_id}.",
            "The aborted batch counts for nothing (no checkpoint, counted false); the replay accepts each key exactly once; the checkpoint versions stay consecutive.", "both",
            [{"entity": "ingestion_batches", "id": A.batch_id}, {"entity": "ingestion_batches", "id": R.batch_id}, {"entity": "checkpoints", "id": f"cp-{R.batch_id}"}],
            [{"path": bpath(A.src, A.batch_id, "counted"), "equals": False}, {"path": bpath(A.src, A.batch_id, "status"), "equals": "aborted"},
             {"path": bpath(A.src, A.batch_id, "written_rows"), "equals": len(A.rows)}, {"path": bpath(A.src, A.batch_id, "accepted_unique"), "equals": 0},
             {"path": bpath(R.src, R.batch_id, "accepted_unique"), "equals": accR}, {"path": bpath(R.src, R.batch_id, "received"), "equals": len(R.rows)},
             {"path": f"metrics.ingestion.sources.{A.src}.checkpoint.uncommitted_batches", "contains": A.batch_id}], ["EV-01"],
            {"aborted_batch": A.batch_id, "replay_batch": R.batch_id, "rows_written": len(A.rows), "accepted_by_the_replay": accR, "rows_accepted_in_the_aborted_batch": 0})
        # 02
        add(2, "overlapping backfills", "P08-TEST-02",
            "Two backfill requests (bf-006 and bf-012) overlap an earlier request of the same source that is still requested or running (bf-004 and bf-010, whose last batch had just committed).",
            "Each is refused with BACKFILL_OVERLAP and keeps its id; the earlier request stands; touching half-open ranges are accepted; a request that has settled (partial or complete) no longer blocks.", "both",
            [{"entity": "backfill_requests", "id": i} for i in ("bf-004", "bf-006", "bf-010", "bf-012")],
            [{"path": "metrics.backfills.refused", "equals": ["bf-006", "bf-012"]}, {"path": "ingest.counts.backfill_requests.accepted", "equals": 13},
             {"path": "ingest.counts.backfill_requests.rejected", "equals": 2}], ["EV-02"],
            {"refused": {q["id"]: {"overlaps": q["overlaps"], "source_id": q["src"], "requested_at": iso(q["requested_final"]), "victim_settled_at": self.bf_settled(q["overlaps"])}
                         for q in w.bf.values() if q["refused"]}},
            rejections=[{"entity": "backfill_requests", "id": q["id"], "reason_code": "BACKFILL_OVERLAP"} for q in sorted(w.bf.values(), key=lambda q: q["id"]) if q["refused"]])
        # 03
        fa = self.n.fetch_analysis()
        ra = w.refused_attempts[0]
        add(3, "retries that ignore retry-after", "P08-TEST-03",
            f"A client retries {RATE_LIMITED_SOURCE} {ra['remaining_seconds']} s too early after a 429 with retry-after {ra['retry_after_seconds']} s.",
            "The early retry is refused with RETRY_TOO_SOON (429, Retry-After header, nothing staged); the fetches recorded in fetch_log all wait at least retry-after.", "both",
            [{"entity": "fetch_log", "id": r["fetch_id"]} for r in b.ents["fetch_log"] if r["source_id"] == ra["source_id"] and r["session_id"] == f"{ra['slot'][0]}:{ra['slot'][1]}"],
            [], ["EV-03"], {"refused_attempt": {k: v for k, v in ra.items() if k != "slot"}, "recorded_retries": fa})
        # 04
        Q = next(x for x in w.batches if x.kind == "schema_q")
        F = next(x for x in w.batches if x.kind == "schema_refetch")
        accF = sum(1 for r in F.rows if r["disp"] == "accepted")
        add(4, "an unexpected required field", "P08-TEST-04",
            f"From 2026-09-15 {SCHEMA_SOURCE} declares schema_version {SCHEMA_VERSION} and adds the required field channel; the first page ({Q.batch_id}) arrives before the expected version is bumped.",
            "The batch is quarantined whole with SCHEMA_CHANGED and the checkpoint does not move; an operator bumps the expected version explicitly and the window is fetched again.", "both",
            [{"entity": "ingestion_batches", "id": Q.batch_id}, {"entity": "ingestion_batches", "id": F.batch_id}, {"entity": "source_contracts", "id": SCHEMA_SOURCE}],
            [{"path": bpath(Q.src, Q.batch_id, "status"), "equals": "quarantined"}, {"path": bpath(Q.src, Q.batch_id, "counted"), "equals": False},
             {"path": bpath(Q.src, Q.batch_id, "written_rows"), "equals": len(Q.rows)}, {"path": bpath(F.src, F.batch_id, "accepted_unique"), "equals": accF}],
            ["EV-04"], {"quarantined_batch": Q.batch_id, "rows_quarantined_whole": len(Q.rows), "refetch_batch": F.batch_id, "accepted_after_the_bump": accF,
                        "bumped_at": iso(F.start), "from_version": "1", "to_version": SCHEMA_VERSION})
        # 05
        K = next(x for x in w.batches if "keyless" in x.tags and x.status == "committed")
        kn = next(n for n, r in enumerate(K.rows, 1) if r["label"] == "keyless")
        kq = next(q for q in ents["quarantine_records"] if q["batch_id"] == K.batch_id and q["source_key"] is None)
        add(5, "a malformed row that would vanish", "P08-TEST-05",
            f"{K.batch_id} carries a row with no record_id and no key.",
            "The row is quarantined MISSING_FIELD with a null source_key and has a quarantine row; received equals accepted + duplicate + quarantined + deleted for the batch.", "both",
            [{"entity": "raw_records", "id": self.b.w.raw_id(K, kn)}, {"entity": "quarantine_records", "id": kq["quarantine_id"]}],
            [{"path": bpath(K.src, K.batch_id, "quarantine_rows_match"), "equals": True}, {"path": bpath(K.src, K.batch_id, "quarantined"), "min": 1},
             {"path": f"metrics.ingestion.sources.{K.src}.quarantine_by_reason.MISSING_FIELD", "min": 1}], ["EV-05"], {"batch": K.batch_id, "raw_record_id": self.b.w.raw_id(K, kn)})
        # 06
        st = [x for x in w.batches if x.src == STALE_SOURCE and x.start >= STALE_FROM]
        add(6, "a green job on a stale source", "P08-TEST-06",
            f"{STALE_SOURCE} stops delivering new events at 2026-10-02T00:00:00Z but its fetches keep succeeding.",
            "Freshness (now minus the latest accepted event) reads three days while the ingestion age stays hours; completeness of the silent partitions is 0; every run is green.", "both",
            [{"entity": "source_contracts", "id": STALE_SOURCE}, {"entity": "ingestion_batches", "id": st[0].batch_id}, {"entity": "ingestion_batches", "id": st[-1].batch_id}],
            [{"path": f"metrics.freshness.{STALE_SOURCE}.freshness_seconds", "min": 3 * D}, {"path": f"metrics.freshness.{STALE_SOURCE}.ingestion_age_seconds", "max": 6 * H},
             {"path": f"metrics.completeness.{STALE_SOURCE}.2026-10-02.value", "equals": "0.000000"}, {"path": f"metrics.completeness.{STALE_SOURCE}.2026-10-04.value", "equals": "0.000000"}],
            ["EV-06"], {"committed_batches_in_window": len(st)})
        # 07
        dr2 = next(d for d in self.n.designed() if d["id"] == "DR-02")["realised"]
        run7 = dr2["run_id"]
        i7 = dr2["pointer_history_index"]
        qr7 = [q["quality_result_id"] for q in ents["quality_results"] if q["task_run_id"].startswith("tr-" + run7[4:] + "-") and q["failure_count"] > 0]
        add(7, "a failed run that would replace a publication", "P08-TEST-07",
            f"{run7} fails its critical relationships check; a pipeline that publishes it anyway would replace the current publication with a snapshot that failed the gate.",
            "The gate blocks, the run fails, an incident opens, no publication row exists and the pointer stays on the previous publication.", "both",
            [{"entity": "pipeline_runs", "id": run7}] + [{"entity": "quality_results", "id": x} for x in qr7] + [{"entity": "incidents", "id": dr2["incident_id"]}],
            [{"path": f"metrics.quality_gate.{run7}.decision", "equals": "blocked"}, {"path": f"metrics.quality_gate.{run7}.critical_failures", "equals": 1},
             {"path": f"metrics.publications.pointer_history.{i7}.gate_decision", "equals": "blocked"},
             {"path": f"metrics.publications.pointer_history.{i7}.pointer_after", "equals": dr2["pointer_before"]},
             {"path": f"metrics.publications.publications.pub-{run7[4:]}", "absent": True}], ["EV-07"], dr2)
        # 08
        de = w.delete_event
        dbatch = next(x for x in w.batches if x.status == "committed" and any(r["label"] == "del" and r["key"] == de.key for r in x.rows))
        tbatch = next(x for x in w.batches if x.status == "committed" and any(r["ev"] is de and r["label"] == "ok" for r in x.rows))
        drow = next(n for n, r in enumerate(dbatch.rows, 1) if r["label"] == "del" and r["key"] == de.key)
        after = next(p for p in w.pubs if tbatch.batch_id in p["included_batch_ids"] and dbatch.batch_id in p["included_batch_ids"] and p["published_at"] > iso(dbatch.commit))
        before = [p for p in w.pubs if tbatch.batch_id in p["included_batch_ids"] and dbatch.batch_id not in p["included_batch_ids"] and p["published_at"] < after["published_at"]][-1]
        add(8, "a delete that is not propagated", "P08-TEST-08",
            f"{de.key} is accepted in {tbatch.batch_id} and cancelled by a delete event in {dbatch.batch_id} the same day; a pipeline that ignores op = delete would keep it in every later snapshot.",
            "The delete row is classified deleted; the record leaves the snapshot from the first publication that includes the delete and appears as a deletes exclusion in the reconciliation; a delete of an unknown key is quarantined DELETE_TARGET_UNKNOWN.", "both",
            [{"entity": "raw_records", "id": self.b.w.raw_id(dbatch, drow)}, {"entity": "ingestion_batches", "id": tbatch.batch_id}, {"entity": "ingestion_batches", "id": dbatch.batch_id},
             {"entity": "publications", "id": before["publication_id"]}, {"entity": "publications", "id": after["publication_id"]}],
            [{"path": f"metrics.reconciliation.{after['publication_id']}.exclusions.deletes", "equals": m["reconciliation"][after["publication_id"]]["exclusions"]["deletes"]},
             {"path": f"metrics.reconciliation.{before['publication_id']}.exclusions.deletes", "equals": "0.00"},
             {"path": f"metrics.reconciliation.{after['publication_id']}.residual", "equals": "0.00"},
             {"path": f"metrics.publications.publications.{after['publication_id']}.published_records", "equals": m["publications"]["publications"][after["publication_id"]]["published_records"]},
             {"path": f"metrics.publications.publications.{before['publication_id']}.published_records", "equals": m["publications"]["publications"][before["publication_id"]]["published_records"]}],
            ["EV-08"], {"record": de.key, "accepted_in": tbatch.batch_id, "deleted_in": dbatch.batch_id, "last_publication_with_the_record": before["publication_id"],
                        "first_publication_without_it": after["publication_id"]})
        # 09
        dr4 = next(d for d in self.n.designed() if d["id"] == "DR-04")["realised"]
        lb = next(x for x in w.batches if "late_events" in x.tags and x.status == "committed")
        add(9, "a late event behind the watermark", "P08-TEST-09",
            f"{LATE_N} src-orders events dated 2026-09-17 18:00..23:50 arrive in {lb.batch_id} (2026-09-18), after the preceding publication whose watermark is later than they are.",
            "Each is accepted, counted as a late event with the publication it is behind, and included in the next publication; none is lost.", "both",
            [{"entity": "ingestion_batches", "id": lb.batch_id}] + [{"entity": "publications", "id": d["behind_publication_id"]} for d in dr4["designed"][:1]]
            + [{"entity": "publications", "id": d["included_in_publication_id"]} for d in dr4["designed"][:1]],
            [{"path": "metrics.late_events.lost", "equals": 0}] + [{"path": "metrics.late_events.events", "find": {"source_key": d["source_key"]},
                                                                  "equals": {"behind_publication_id": d["behind_publication_id"], "included_in_publication_id": d["included_in_publication_id"], "batch_id": lb.batch_id}}
                                                                 for d in dr4["designed"]], ["EV-09"],
            {"batch": lb.batch_id, "designed_events": [d["source_key"] for d in dr4["designed"]]})
        # 10
        cl = next(r for r in ents["fetch_log"] if r["status"] == "cursor_loop")
        add(10, "a pagination token that repeats", "P08-TEST-10",
            f"In one fetch session {LOOP_SOURCE} answers the page after {cl['next_cursor']} (cursor {cl['cursor_value']}) with next_cursor {cl['next_cursor']}, the cursor the session started from.",
            "The fetch stops with CURSOR_LOOP (409) and is recorded; the session is dead; a new session may fetch a cursor again (recorded as a refetch); no batch is created by the looping page.", "both",
            [{"entity": "fetch_log", "id": cl["fetch_id"]}], [], ["EV-10"], {"fetch_log_row": cl["fetch_id"], "session_id": cl["session_id"], "fetched_at": cl["fetched_at"]})
        # 11
        from_domain = self.b.dom.mod["redaction"].safe_line(LOG_LINE)
        add(11, "a secret in a structured log line", "P08-TEST-11",
            "A structured log line (and a fault note) carries an API key, a bearer token and a token in a URL.",
            "Every secret span is replaced by [REDACTED] before the line is emitted or stored; a line that still matches is withheld whole.", "replay", [], [], ["EV-11"],
            {"log_line": LOG_LINE, "secrets": list(LOG_SECRETS), "redacted_by_the_domain": from_domain})
        # 12
        add(12, "a workflow that triggers itself", "P08-TEST-12",
            "A workflow that runs on push to main commits and pushes to main without a skip marker.",
            "The static guard reports SELF_PUSH for the workflow; with the [skip ci] marker in the commit message it reports nothing.", "replay", [], [], ["EV-12"],
            {"workflow_file": "refresh-generated-evidence.yml", "workflow_text": WORKFLOW_BAD, "fixed_text": WORKFLOW_GOOD,
             "findings": [{"code": f.code, "line": f.line} for f in self.b.dom.mod["workflow_guard"].analyze(WORKFLOW_BAD, "refresh-generated-evidence.yml")]})
        return out


# ==================================================================================================================== the manifest and the files
def parameters(b: Built) -> dict[str, str]:
    w = b.w
    p = {"window": "2026-08-10 .. 2026-10-04 (56 days, hourly runs)", "as_of": AS_OF, "sources": str(len(SRC_ORDER)),
         "cadences": "; ".join(f"{s[0]} {s[10]} at minute {s[5]}" for s in SOURCES), "events_per_hour_x100": "; ".join(f"{s[0]} {s[6]}" for s in SOURCES),
         "freshness_targets_seconds": "; ".join(f"{s[0]} {s[9]}" for s in SOURCES), "schema_bump": f"{SCHEMA_SOURCE} to version {SCHEMA_VERSION} on 2026-09-15",
         "stale_source": f"{STALE_SOURCE} from {iso(STALE_FROM)}", "rate_limit": f"{RATE_LIMITED_SOURCE} {RATE_LIMIT_PPM} ppm of fetches, retry-after {list(RETRY_AFTER_CHOICES)}",
         "late_events": f"{LATE_N} events of {LATE_SOURCE} held to the batch of {iso(int(LATE_SLOT.timestamp()))}", "residual_day": RESIDUAL_TICK.strftime("%Y-%m-%d"),
         "ppm": canon(PPM), "failure_plan": canon({t: FAIL_TYPES.count(t) for t in sorted(set(FAIL_TYPES))} | {"freshness": N_FRESH, "residual": 1}),
         "aborted_ingests": f"{N_ABORTED_RANDOM} random + 1 designed", "unknown_op_rows": "3: one slot each of src-orders, src-payments, src-shipments", "backfills": "15 requests: 13 accepted, 2 refused (bf-006, bf-012), each made while the request it overlaps (bf-004, bf-010) was still requested or running",
         "publication_scope": "every batch committed from the start of the UTC day of (the run's hour tick minus one hour) until the run started (pipeline_runs.scope_from declares the start): the day's snapshot, rebuilt hourly; backfill batches enter on the day they commit",
         "watermark": "the earliest, over all sources, of the end of the window of the latest batch committed before the gate",
         "sample_cap_rows": str(SAMPLE_CAP), "sample_rows_published": str(len(b.ents["raw_records"])), "size_cap_bytes": str(SIZE_CAP),
         "size_cap_binding": "false" if b.sample_cap == SAMPLE_CAP else "true", "run_start_offset_seconds": str(RUN_OFFSET_S)}
    return p


def build_manifest(b: Built, nums: Numbers, designed: list[dict], stats: dict) -> dict:
    w = b.w
    full_counts = {k: v["accepted"] for k, v in b.golden["ingest"]["counts"].items()}
    pub_counts = {k: v["accepted"] for k, v in b.golden_pub["ingest"]["counts"].items()}
    rejected_full = {k: v["rejected"] for k, v in b.golden["ingest"]["counts"].items() if v["rejected"]}
    m_pub = b.golden_pub["metrics"]
    return {
        "dataset_version": b.version, "dataset_hash": dataset_hash(b.ents), "generated_at": AS_OF, "contract_version": CONTRACT_VERSION, "window_start": "2026-08-10T00:00:00Z",
        "window_end": "2026-10-04T23:59:59Z", "as_of": AS_OF,
        "config": {**CONFIG, "processing_measurement": b.pm, "freshness_targets_seconds": {s[0]: s[9] for s in SOURCES}},
        "generator": {"name": "generate.py", "seed": b.seed, "parameters": parameters(b), "disclosures": DISCLOSURES},
        "row_counts": {k: len(b.ents[k]) for k in PUBLISHED},
        "full_world": {"note": "Counts of the complete world the domain was run over (regenerate it with generate.py --full-inputs); raw_records are published as a sample only.",
                       "row_counts": {k: len(w.ents[k]) for k in w.ents if k != "model_output_totals"} | {"model_output_totals": len(w.totals), "fetch_log": len(w.fetch_rows()), "batch_summaries": len(b.ents["batch_summaries"])},
                       "domain_ingest_counts": full_counts, "domain_rejected": rejected_full,
                       "raw_records_received_by_committed_batches": stats["ingestion"]["overall"]["received"],
                       "raw_records_written_in_all_batches": sum(len(x.rows) for x in w.batches)},
        "sample": {"raw_records_published": len(b.ents["raw_records"]), "cap_rows": SAMPLE_CAP, "cap_used": b.sample_cap, "batches_sampled": len(b.sample_ids), "batches_in_all": len(w.batches),
                   "rule": "whole batches: the injected defects and designed relationships first, then a seeded shuffle of the live batches until the next batch would pass the cap",
                   "entity_bytes": b.entity_bytes, "size_cap_bytes": SIZE_CAP, "size_cap_binding": b.sample_cap != SAMPLE_CAP,
                   "published_world": {"domain_ingest_counts": pub_counts, "ingestion_overall": m_pub["ingestion"]["overall"], "current_publication_id": m_pub["publications"]["current_publication_id"],
                                       "publications_content_hash_ok": sum(1 for p in m_pub["publications"]["publications"].values() if p["content_hash_ok"]),
                                       "publications": len(m_pub["publications"]["publications"]),
                                       "note": "the domain over the sampled files: the per-batch rows of unsampled batches are absent there, so use batch_summaries for those"}},
        "designed_relationships": designed, "injection_manifest": "injection-manifest.json", "stats": stats,
    }


def write_all(seed: int, out: Path, built: Built | None = None) -> tuple[dict, Built]:
    b = built or Built(seed)
    nums = Numbers(b)
    designed = nums.designed()
    stats = nums.stats()
    manifest = build_manifest(b, nums, designed, stats)
    inj = Injections(b, nums)
    inj_doc = {"dataset_version": b.version, "dataset_hash": manifest["dataset_hash"], "seed": seed, "contract_version": CONTRACT_VERSION,
               "checks_run_against": "the complete world (generate.py --full-inputs, then the domain's run_pipeline with the published totals); paths are into the shape of expected.json",
               "check_operators": {"equals": "exact value", "min": "at least (integer)", "max": "at most (integer)", "contains": "list or string contains", "not_contains": "string does not contain",
                                   "absent": "the path does not exist", "find": "pick the list element whose fields equal `find`, then compare `equals` as a subset"},
               "replay": {"clock": "each step carries `at`: freeze the API clock there", "database": "seed data/seed.py with the published entity files, dataset_version = dataset_version",
                          "step_kinds": ["command", "read", "check"]},
               "injections": inj.entries(), "designed_relationships": designed, "events": inj.events()}
    out.mkdir(parents=True, exist_ok=True)
    nbytes = 0
    for name in PUBLISHED:
        text = entity_text(name, b.version, b.ents[name])
        nbytes += len(text.encode())
        (out / f"{name}.json").write_text(text)
    t1 = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    t2 = json.dumps(inj_doc, indent=2, sort_keys=True) + "\n"
    (out / "manifest.json").write_text(t1)
    (out / "injection-manifest.json").write_text(t2)
    manifest["_bytes"] = nbytes + len(t1.encode()) + len(t2.encode())
    return manifest, b


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=APP_ROOT / "web" / "public" / "data")
    ap.add_argument("--full-inputs", type=Path, help="also write the complete world as one inputs object for data/seed.py (not committed)")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    m, b = write_all(args.seed, args.out)
    if args.full_inputs:
        args.full_inputs.write_text(json.dumps(b.full_data, sort_keys=True))
    total = sum(p.stat().st_size for p in args.out.glob("*.json"))
    print(json.dumps({"dataset_version": m["dataset_version"], "dataset_hash": m["dataset_hash"], "row_counts": m["row_counts"], "bytes": total,
                      "elapsed_seconds": round(time.perf_counter() - t0, 1)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
