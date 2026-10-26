"""The Python side of the analysis reconciliation (P04-ART-04): what each SQL investigation must return, computed from the
accepted population of the Python domain over ``web/public/data`` with exact rationals, no database and no SQL.

``expected(ctx)`` returns one list of rows (dicts of strings, the columns of the SQL file) per result key. ``run_all.py`` compares
the SQL results with it cell by cell; ``tests/test_artifacts.py`` compares the stored ``artifacts/analysis-results.json`` with it
(so the stored numbers equal the domain without a database). The domain supplies the replay of the event log (``histories``), the
typed records and the rounding helpers; the aggregation below is written separately from both the domain's metrics and the SQL.
Every value is normalised by ``norm`` to the text a reader sees: None -> '', bool -> true / false, Decimal -> plain notation.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for _p in (ROOT / "domain", ROOT, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from prepare_snapshot import SNAPSHOT, snapshot_inputs  # noqa: E402
from serviceflow import run_pipeline  # noqa: E402
from serviceflow.metrics import histories  # noqa: E402
from serviceflow.timeutil import d4, d6, minutes_between, nearest_rank, parse_ts  # noqa: E402

UTC = timezone.utc
P90 = Fraction(9, 10)
WINDOWS = {"full": (parse_ts("2026-07-06T00:00:00Z"), parse_ts("2026-09-28T00:00:00Z")),
           "training": (parse_ts("2026-07-06T00:00:00Z"), parse_ts("2026-08-31T00:00:00Z")),
           "holdout": (parse_ts("2026-08-31T00:00:00Z"), parse_ts("2026-09-28T00:00:00Z"))}
ABANDONABLE = ("chat", "phone")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


def dq(x: Fraction | int | None, places: int) -> str:
    """Exact rational to a decimal string with ``places`` decimals, half up (as SQL round on numeric)."""
    if x is None:
        return ""
    q = Decimal(1).scaleb(-places)
    d = Decimal(Fraction(x).numerator) / Decimal(Fraction(x).denominator) if places >= 0 else Decimal(0)
    return format(d.quantize(q, rounding=ROUND_HALF_UP), "f") if places > 0 else format(d.quantize(Decimal(1), rounding=ROUND_HALF_UP), "f")


def mean(vals: list[Fraction]) -> Fraction | None:
    return sum(vals, Fraction(0)) / len(vals) if vals else None


def p90(vals: list[Fraction]) -> Fraction | None:
    return nearest_rank(vals, P90) if vals else None


@dataclass
class Ctx:
    inputs: dict
    pop: Any
    hist: dict
    tix: dict
    policy: dict            # priority -> (first_response_minutes, resolution_minutes)
    breaks: list            # rows of shift_breaks.json
    manifest: dict
    res: Any


def load() -> Ctx:
    inputs = snapshot_inputs()
    res = run_pipeline(inputs)
    pop = res.population
    return Ctx(inputs, pop, histories(pop), {t.ticket_id: t for t in pop.tickets},
               {p.priority: (p.first_response_minutes, p.resolution_minutes) for p in pop.sla_policies},
               json.loads((SNAPSHOT / "shift_breaks.json").read_text())["rows"],
               json.loads((SNAPSHOT / "manifest.json").read_text()), res)


def inside(x: datetime | None, w: tuple[datetime, datetime]) -> bool:
    return x is not None and w[0] <= x < w[1]


def mins(a: datetime, b: datetime) -> Fraction:
    return minutes_between(a, b)          # exact, clamped at 0 (the SQL's greatest(0, ...))


def raw_mins(a: datetime, b: datetime) -> Fraction:
    d = b - a
    return (Fraction(d.days * 86400 + d.seconds) + Fraction(d.microseconds, 10 ** 6)) / 60


def secs(a: datetime, b: datetime) -> Fraction:
    d = b - a
    return Fraction(d.days * 86400 + d.seconds) + Fraction(d.microseconds, 10 ** 6)


def ts(x: datetime) -> str:
    return x.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- 01 ------------------------------------------------------------------------------------------------------------------
def hour_blocks(tickets_created: list[datetime], shifts: list[tuple[datetime, datetime, int]]) -> list[dict]:
    """Every two-hour block of the UTC week with arrivals, staffed hours and the ratio (shared by 01 and the manifest check)."""
    cut = datetime(2026, 8, 31, tzinfo=UTC)
    arr = defaultdict(int), defaultdict(int), defaultdict(int)
    for d in tickets_created:
        slot = d.weekday() * 24 + d.hour
        arr[0][slot] += 1
        arr[1 if d < cut else 2][slot] += 1
    cap: dict[int, Fraction] = defaultdict(Fraction)
    for a, b, brk in shifts:
        total = secs(a, b)
        keep = (total - 60 * brk) / total
        t = a
        while t < b:
            nxt = min(t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1), b)
            cap[t.weekday() * 24 + t.hour] += secs(t, nxt) / 3600 * keep
            t = nxt
    out = []
    for slot in range(168):
        keys = (slot, (slot + 1) % 168)
        out.append({"slot": slot, "arrivals": sum(arr[0][k] for k in keys), "train": sum(arr[1][k] for k in keys),
                    "hold": sum(arr[2][k] for k in keys), "staffed": sum((cap[k] for k in keys), Fraction(0))})
    return out


def pick_blocks(blocks: list[dict]) -> list[dict]:
    ranked = [dict(b, ratio=Fraction(b["arrivals"]) / b["staffed"]) for b in blocks if b["staffed"] >= 24]
    desc = sorted(ranked, key=lambda b: (-b["ratio"], b["slot"]))
    asc = sorted(ranked, key=lambda b: (b["ratio"], b["slot"]))
    n = len(ranked)

    def row(note: str, b: dict) -> dict:
        d, h = divmod(b["slot"], 24)
        return {"note": note, "block_utc": f"{DAYS[d]} {h:02d}-{(h + 2) % 24:02d}", "arrivals": b["arrivals"],
                "arrivals_training": b["train"], "arrivals_holdout": b["hold"], "staffed_hours": dq(b["staffed"], 2),
                "arrivals_per_staffed_hour": dq(b["ratio"], 4), "blocks_ranked": n}

    ratios = sorted(b["ratio"] for b in ranked)
    mid = (ratios[n // 2 - 1] + ratios[n // 2]) / 2 if n % 2 == 0 else ratios[n // 2]
    rows = [row(f"top {i}", b) for i, b in enumerate(desc[:6], 1)]
    rows.append({"note": "median of the blocks", "block_utc": "(mean of the two middle blocks)", "arrivals": "", "arrivals_training": "",
                 "arrivals_holdout": "", "staffed_hours": "", "arrivals_per_staffed_hour": dq(mid, 4), "blocks_ranked": n})
    rows.append(row("lowest block", asc[0]))
    return rows


def expected_01(c: Ctx) -> list[dict]:
    shifts = [(s.starts_at, s.ends_at, s.break_minutes) for s in c.pop.shifts]
    return pick_blocks(hour_blocks([t.created_at for t in c.pop.tickets], shifts))


# ---- 02 ------------------------------------------------------------------------------------------------------------------
def _groups(items: list[tuple[str, str, Any]]) -> dict[tuple[str, str], list[Any]]:
    g: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for q, p, v in items:
        for key in ((q, p), (q, "ALL"), ("ALL", p), ("ALL", "ALL")):
            g[key].append(v)
    return g


def _order(keys) -> list[tuple[str, str]]:
    return sorted(keys, key=lambda k: (k[0] == "ALL", k[0], k[1] == "ALL", k[1]))


def expected_02a(c: Ctx) -> list[dict]:
    w = WINDOWS["full"]
    items = []
    for t in c.pop.tickets:
        if not inside(t.created_at, w):
            continue
        h = c.hist[t.ticket_id]
        fr = mins(t.created_at, h.first_human_reply_at) if h.first_human_reply_at else None
        wt = mins(t.created_at, h.first_service_at) if h.first_service_at else None
        items.append((t.queue_id, t.priority, (fr, wt)))
    g = _groups(items)
    rows = []
    for key in _order(g):
        frs = [v[0] for v in g[key] if v[0] is not None]
        wts = [v[1] for v in g[key] if v[1] is not None]
        rows.append({"queue_id": key[0], "priority": key[1], "arrivals": len(g[key]), "with_human_reply": len(frs),
                     "mean_first_response_min": d4(mean(frs)), "p90_first_response_min": d4(p90(frs)), "served": len(wts),
                     "mean_wait_min": d4(mean(wts)), "p90_wait_min": d4(p90(wts))})
    return rows


def expected_02b(c: Ctx) -> list[dict]:
    w = WINDOWS["full"]
    items = []
    for t in c.pop.tickets:
        h = c.hist[t.ticket_id]
        if inside(h.final_resolution, w):
            items.append((t.queue_id, t.priority, mins(t.created_at, h.final_resolution)))
    g = _groups(items)
    rows = []
    for key in _order(g):
        v = g[key]
        m, q = mean(v), p90(v)
        rows.append({"queue_id": key[0], "priority": key[1], "completions": len(v), "mean_resolution_min": d4(m),
                     "p90_resolution_min": d4(q), "p90_over_mean": dq(q / m, 3)})
    return rows


# ---- 03 ------------------------------------------------------------------------------------------------------------------
def expected_03a(c: Ctx) -> list[dict]:
    rows = []
    for wname, w in WINDOWS.items():
        per: dict[str, dict[str, int]] = {p: defaultdict(int) for p in ("P1", "P2", "P3")}
        for t in c.pop.tickets:
            h = c.hist[t.ticket_id]
            fr_t, rs_t = c.policy[t.priority]
            d = per[t.priority]
            if inside(t.created_at, w):
                d["arr"] += 1
                if h.first_human_reply_at is not None:
                    d["fre"] += 1
                    d["frw"] += mins(t.created_at, h.first_human_reply_at) <= fr_t
            if inside(h.final_resolution, w):
                d["rse"] += 1
                ok = mins(t.created_at, h.final_resolution) <= rs_t
                d["rsw"] += ok
                d["miss_reopened"] += (not ok) and h.reopen_count > 0
        allp: dict[str, int] = defaultdict(int)
        for d in per.values():
            for k, v in d.items():
                allp[k] += v
        for pr, d in [*sorted(per.items()), ("ALL", allp)]:
            rows.append({"window_name": wname, "priority": pr, "arrivals": d["arr"], "first_response_within": d["frw"],
                         "first_response_eligible": d["fre"], "first_response_compliance": dq(Fraction(d["frw"], d["fre"]), 6) if d["fre"] else "",
                         "arrivals_without_human_reply": d["arr"] - d["fre"],
                         "if_no_reply_counted_as_miss": dq(Fraction(d["frw"], d["arr"]), 6) if d["arr"] else "",
                         "resolution_within": d["rsw"], "resolution_eligible": d["rse"],
                         "resolution_compliance": dq(Fraction(d["rsw"], d["rse"]), 6) if d["rse"] else "",
                         "resolution_misses": d["rse"] - d["rsw"], "misses_that_were_reopened": d["miss_reopened"]})
    return rows


def expected_03d(c: Ctx) -> list[dict]:
    w = WINDOWS["full"]
    acc: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    for t in c.pop.tickets:
        h = c.hist[t.ticket_id]
        fr_t, rs_t = c.policy[t.priority]
        for key in ((t.queue_id, t.priority), (t.queue_id, "ALL")):
            d = acc[key]
            if inside(t.created_at, w) and h.first_human_reply_at is not None:
                d["fre"] += 1
                d["frw"] += mins(t.created_at, h.first_human_reply_at) <= fr_t
            if inside(h.final_resolution, w):
                d["rse"] += 1
                d["rsw"] += mins(t.created_at, h.final_resolution) <= rs_t
    rows = []
    for (q, p) in sorted(acc, key=lambda k: (k[0], k[1] == "ALL", k[1])):
        d = acc[(q, p)]
        rows.append({"queue_id": q, "priority": p, "first_response_within": d["frw"], "first_response_eligible": d["fre"],
                     "first_response_compliance": dq(Fraction(d["frw"], d["fre"]), 6) if d["fre"] else "",
                     "resolution_within": d["rsw"], "resolution_eligible": d["rse"],
                     "resolution_compliance": dq(Fraction(d["rsw"], d["rse"]), 6) if d["rse"] else ""})
    return rows


def monday_cutoffs() -> list[datetime]:
    return [datetime(2026, 7, 6, 10, 30, tzinfo=UTC) + timedelta(days=7 * n) for n in range(12)]


def expected_03b(c: Ctx) -> list[dict]:
    rows = []
    for week, cut in enumerate(monday_cutoffs(), 1):
        backlog = overdue = 0
        for t in c.pop.tickets:
            if t.created_at > cut:
                continue
            h = c.hist[t.ticket_id]
            if h.open_at(cut):
                backlog += 1
                overdue += mins(t.created_at, cut) > c.policy[t.priority][1]
        rows.append({"week": week, "cutoff_utc": ts(cut), "backlog": backlog, "open_overdue": overdue})
    return rows


def expected_03c(c: Ctx) -> list[dict]:
    start = datetime(2026, 7, 6, tzinfo=UTC)
    samples = [start + timedelta(hours=n) for n in range(24 * 7 * 12)]       # 2,016 hourly cutoffs
    cand = []
    for t in c.pop.tickets:
        h = c.hist[t.ticket_id]
        rs_t = c.policy[t.priority][1]
        closes = [e.occurred_at for e in h.events if e.event_type in ("resolved", "abandoned")]
        marks = [e for e in h.events if e.event_type in ("resolved", "reopened", "abandoned")]
        last_kind = marks[-1].event_type if marks else None        # events are ordered by (occurred_at, event_id)
        if not closes or last_kind == "reopened" or raw_mins(t.created_at, max(closes)) > rs_t:
            cand.append((t, h, rs_t))
    seen: dict[str, set] = defaultdict(set)
    per_hour: dict[tuple[str, datetime], int] = defaultdict(int)
    for t, h, rs_t in cand:
        for s in samples:
            if t.created_at <= s and raw_mins(t.created_at, s) > rs_t and h.open_at(s):
                seen[t.priority].add(t.ticket_id)
                per_hour[(t.priority, s)] += 1
                per_hour[("ALL", s)] += 1
                seen["ALL"].add(t.ticket_id)
    rows = []
    for pr in ("P1", "P2", "P3", "ALL"):
        n_c = sum(1 for t, _, _ in cand if pr == "ALL" or t.priority == pr)
        hours = [v for (p, _), v in per_hour.items() if p == pr]
        rows.append({"priority": pr, "could_be_overdue": n_c, "tickets_open_overdue_at_a_sample": len(seen[pr]),
                     "hours_with_any": len(hours), "peak_open_overdue_at_one_hour": max(hours) if hours else 0})
    return rows


# ---- 04 ------------------------------------------------------------------------------------------------------------------
def staffed_in(shifts, w) -> Fraction:
    tot = Fraction(0)
    for s in shifts:
        lo, hi = max(s.starts_at, w[0]), min(s.ends_at, w[1])
        if hi > lo:
            tot += secs(lo, hi) / 60 - (s.break_minutes if s.starts_at >= w[0] and s.ends_at <= w[1] else 0)
    return tot


def expected_04a(c: Ctx) -> list[dict]:
    w = WINDOWS["full"]
    agents = {a.agent_id: a for a in c.pop.agents}
    sh: dict[str, list] = defaultdict(list)
    for s in c.pop.shifts:
        sh[s.agent_id].append(s)
    rb: dict[str, Fraction] = defaultdict(Fraction)
    for b in c.breaks:
        a, z = parse_ts(b["starts_at"]), parse_ts(b["ends_at"])
        if a >= w[0] and z <= w[1]:
            rb[b["agent_id"]] += secs(a, z) / 60
    ivs: dict[str, list] = defaultdict(list)
    for h in c.hist.values():
        for iv in h.intervals:
            ivs[iv.agent_id].append(iv)
    rows, tot = [], defaultdict(Fraction)
    for aid in sorted(agents):
        a = agents[aid]
        overl = [s for s in sh[aid] if min(s.ends_at, w[1]) > max(s.starts_at, w[0])]
        staffed = staffed_in(sh[aid], w)
        decl = sum(s.break_minutes for s in sh[aid] if s.starts_at >= w[0] and s.ends_at <= w[1])
        hand = sum((iv.minutes_within(*w) for iv in ivs[aid]), Fraction(0))
        row = {"agent_id": aid, "timezone": a.timezone, "employment_type": a.employment_type, "shifts": len(overl),
               "staffed_available_min": dq(staffed, 4), "declared_break_min": dq(decl, 4), "recorded_break_min": dq(rb[aid], 4) if aid in rb else "",
               "service_intervals": len(ivs[aid]), "handling_min": dq(hand, 4), "occupancy": dq(hand / staffed, 6) if staffed else ""}
        rows.append(row)
        for k, v in (("shifts", len(overl)), ("staffed", staffed), ("decl", decl), ("rec", rb[aid]), ("iv", len(ivs[aid])), ("hand", hand)):
            tot[k] += v
    rows.append({"agent_id": "ALL", "timezone": "", "employment_type": "", "shifts": int(tot["shifts"]),
                 "staffed_available_min": dq(tot["staffed"], 4), "declared_break_min": dq(tot["decl"], 4),
                 "recorded_break_min": dq(tot["rec"], 4), "service_intervals": int(tot["iv"]), "handling_min": dq(tot["hand"], 4),
                 "occupancy": dq(tot["hand"] / tot["staffed"], 6)})
    return rows


def expected_04b(c: Ctx) -> list[dict]:
    rec_by_shift: dict[str, Fraction] = defaultdict(Fraction)
    for b in c.breaks:
        rec_by_shift[b["shift_id"]] += secs(parse_ts(b["starts_at"]), parse_ts(b["ends_at"])) / 60
    ivs: dict[str, list] = defaultdict(list)
    for h in c.hist.values():
        for iv in h.intervals:
            ivs[iv.agent_id].append(iv)
    far = datetime(9999, 12, 31, tzinfo=UTC)
    groups: dict[tuple, dict] = {}
    for s in c.pop.shifts:
        gross = secs(s.starts_at, s.ends_at) / 60
        rec = rec_by_shift.get(s.shift_id, Fraction(0))
        key = (int(gross), s.break_minutes, int(rec))
        g = groups.setdefault(key, defaultdict(Fraction))
        g["n"] += 1
        g["decl"] += gross - s.break_minutes
        g["rec"] += gross - rec
        g["over"] += rec - s.break_minutes
        for iv in ivs[s.agent_id]:
            e = iv.end or far
            if iv.start < s.ends_at and e > s.starts_at:
                g["hand"] += secs(max(iv.start, s.starts_at), min(e, s.ends_at)) / 60
    # handling inside a recorded break, attributed to the shift the break belongs to
    shift_of = {b["break_id"]: b["shift_id"] for b in c.breaks}
    shift_key = {}
    for s in c.pop.shifts:
        gross = secs(s.starts_at, s.ends_at) / 60
        shift_key[s.shift_id] = (int(gross), s.break_minutes, int(rec_by_shift.get(s.shift_id, Fraction(0))))
    for b in c.breaks:
        a, z = parse_ts(b["starts_at"]), parse_ts(b["ends_at"])
        for iv in ivs[b["agent_id"]]:
            e = iv.end or far
            if iv.start < z and e > a:
                groups[shift_key[shift_of[b["break_id"]]]]["inbrk"] += secs(max(iv.start, a), min(e, z)) / 60
    rows = []
    for key in sorted(groups):
        g = groups[key]
        rows.append({"shift_min": str(key[0]), "declared_break_min": key[1], "recorded_break_min": str(key[2]), "shifts": int(g["n"]),
                     "staffed_min_declared": dq(g["decl"], 4), "staffed_min_recorded": dq(g["rec"], 4),
                     "capacity_overstated_by_declared_min": dq(g["over"], 4), "handling_min": dq(g["hand"], 4),
                     "handling_inside_a_recorded_break_min": dq(g["inbrk"], 4)})
    return rows


def expected_04c(c: Ctx) -> list[dict]:
    from serviceflow.events import queue_at
    tech = {q.skill_id for q in c.pop.queue_skills if q.queue_id == "q-002"}
    held: dict[str, list] = defaultdict(list)
    for s in c.pop.agent_skills:
        if s.skill_id in tech:
            held[s.agent_id].append(s.effective_from)
    by_ticket = c.pop.events_by_ticket()
    lo, hi = WINDOWS["training"]
    acc: dict[str, list[Fraction]] = defaultdict(list)
    for t in c.pop.tickets:
        for iv in c.hist[t.ticket_id].intervals:
            st = iv.start
            if not (lo <= st < hi and st.weekday() == 0 and st.hour in (9, 10)):
                continue
            if not any(e <= st for e in held.get(iv.agent_id, [])):
                continue
            q = queue_at(t, by_ticket[t.ticket_id], st)
            acc[q].append(secs(iv.start, iv.end))
    total = sum((sum(v, Fraction(0)) for v in acc.values()), Fraction(0))
    rows = []
    for q in sorted(acc) + ["ALL"]:
        v = [x for k in acc for x in acc[k]] if q == "ALL" else acc[q]
        s = sum(v, Fraction(0))
        rows.append({"queue_id": q, "intervals": len(v), "handling_min": dq(s / 60, 4), "share_pct": dq(100 * s / total, 1)})
    return rows


def expected_04d(c: Ctx) -> list[dict]:
    w = WINDOWS["full"]
    skill_queues: dict[str, set] = defaultdict(set)
    for q in c.pop.queue_skills:
        skill_queues[q.skill_id].add(q.queue_id)
    sets: dict[str, set] = defaultdict(set)
    for s in c.pop.agent_skills:
        sets[s.agent_id] |= skill_queues[s.skill_id]
    sh: dict[str, list] = defaultdict(list)
    for s in c.pop.shifts:
        sh[s.agent_id].append(s)
    hand: dict[str, Fraction] = defaultdict(Fraction)
    for h in c.hist.values():
        for iv in h.intervals:
            hand[iv.agent_id] += iv.minutes_within(*w)
    groups: dict[str, list] = defaultdict(list)
    for aid, qs in sets.items():
        groups[" + ".join(sorted(qs))].append(aid)
    rows = []
    for key in sorted(groups):
        ids = sorted(groups[key])
        staffed = sum((staffed_in(sh[a], w) for a in ids), Fraction(0))
        hd = sum((hand[a] for a in ids), Fraction(0))
        rows.append({"skill_set": key, "agents": len(ids), "agent_ids": ", ".join(ids), "staffed_available_min": dq(staffed, 4),
                     "handling_min": dq(hd, 4), "occupancy": dq(hd / staffed, 6)})
    return rows


# ---- 05 ------------------------------------------------------------------------------------------------------------------
def expected_05a(c: Ctx) -> list[dict]:
    w = WINDOWS["full"]
    items = []
    for t in c.pop.tickets:
        h = c.hist[t.ticket_id]
        if not inside(h.final_resolution, w):
            continue
        tr, ro = bool(h.transfers), h.reopen_count > 0
        grp = "transferred and reopened" if tr and ro else "transferred only" if tr else "reopened only" if ro else "neither"
        dormant = sum((secs(h.cycles[k].resolved_at, h.cycles[k + 1].started_at) for k in range(len(h.cycles) - 1)
                       if h.cycles[k].resolved_at is not None), Fraction(0))
        hand = sum((secs(iv.start, iv.end) for iv in h.intervals if iv.end is not None), Fraction(0))
        wt = mins(t.created_at, h.first_service_at) if h.first_service_at else None
        items.append((grp, mins(t.created_at, h.final_resolution), wt, hand / 60, dormant / 60))
    n_all = len(items)
    order = ["neither", "transferred only", "reopened only", "transferred and reopened", "ALL"]
    rows = []
    for grp in order:
        sel = [i for i in items if grp == "ALL" or i[0] == grp]
        res = [i[1] for i in sel]
        wts = [i[2] for i in sel if i[2] is not None]
        n = len(sel)
        rows.append({"ticket_group": grp, "completions": n, "share_of_completions_pct": dq(Fraction(100 * n, n_all), 1),
                     "mean_resolution_min": d4(mean(res)), "p90_resolution_min": d4(p90(res)),
                     "mean_wait_to_first_service_min": d4(mean(wts)), "mean_handling_min": d4(sum((i[3] for i in sel), Fraction(0)) / n),
                     "mean_dormant_gap_min": d4(sum((i[4] for i in sel), Fraction(0)) / n)})
    return rows


def expected_05b(c: Ctx) -> list[dict]:
    routes: dict[tuple, list] = defaultdict(list)
    for t in c.pop.tickets:
        h = c.hist[t.ticket_id]
        for tr in h.transfers:
            nxt = next((e.occurred_at for e in h.events if e.event_type in ("service_started", "resumed") and e.occurred_at >= tr.at), None)
            routes[(tr.from_queue, tr.to_queue)].append((raw_mins(t.created_at, tr.at), None if nxt is None else raw_mins(tr.at, nxt)))
    rows = []
    for key in sorted(routes):
        v = routes[key]
        later = [x[1] for x in v if x[1] is not None]
        rows.append({"from_queue": key[0], "to_queue": key[1], "transfers": len(v),
                     "mean_min_arrival_to_transfer": dq(mean([x[0] for x in v]), 4), "with_a_later_service": len(later),
                     "mean_min_transfer_to_next_service": dq(mean(later), 4) if later else ""})
    return rows


# ---- 06 ------------------------------------------------------------------------------------------------------------------
def expected_06a(c: Ctx) -> list[dict]:
    w = WINDOWS["full"]
    pops = []
    for t in c.pop.tickets:
        if not inside(t.created_at, w):
            continue
        h = c.hist[t.ticket_id]
        ab, fs = h.abandoned_at, h.first_service_at
        pops.append((t.channel, ab, (ab is not None and (fs is None or ab < fs)), None if ab is None else raw_mins(t.created_at, ab), bool(h.transfers)))
    rows = []
    for ch in sorted({p[0] for p in pops}) + ["ALL abandonable"]:
        sel = [p for p in pops if (p[0] in ABANDONABLE if ch == "ALL abandonable" else p[0] == ch)]
        can = ch == "ALL abandonable" or ch in ABANDONABLE
        gone = [p for p in sel if p[1] is not None]
        before = sum(1 for p in sel if p[2])
        pat = [p[3] for p in gone]
        rows.append({"channel": ch, "can_abandon": can, "arrivals": len(sel), "abandoned": len(gone),
                     "abandonment_rate": dq(Fraction(len(gone), len(sel)), 6) if can and sel else "",
                     "abandoned_before_first_service": before, "abandoned_after_service_began": len(gone) - before,
                     "of_which_transferred": sum(1 for p in gone if not p[2] and p[4]),
                     "mean_patience_min": dq(mean(pat), 4) if pat else "", "p90_patience_min": dq(p90(pat), 4) if pat else ""})
    return rows


def expected_06b(c: Ctx) -> list[dict]:
    w = WINDOWS["full"]
    bands = [(0, 5, "0-5"), (5, 10, "5-10"), (10, 20, "10-20"), (20, 40, "20-40"), (40, 80, "40-80"), (80, 10 ** 5, "80-more")]
    pop = defaultdict(list)
    for t in c.pop.tickets:
        if not inside(t.created_at, w) or t.channel not in ABANDONABLE:
            continue
        h = c.hist[t.ticket_id]
        ab, fs = h.abandoned_at, h.first_service_at
        if ab is None and fs is None:
            continue
        end = min(x for x in (ab, fs) if x is not None)
        pop[t.channel].append((raw_mins(t.created_at, end), ab is not None and (fs is None or ab < fs)))
    rows = []
    for ch in ("chat", "phone"):
        for lo, hi, label in bands:
            risk = [p for p in pop[ch] if p[0] >= lo]
            gone = sum(1 for p in risk if p[0] < hi and p[1])
            served = sum(1 for p in risk if p[0] < hi and not p[1])
            rows.append({"channel": ch, "wait_band_min": label, "at_risk": len(risk), "abandoned_in_band": gone, "served_in_band": served,
                         "abandonment_hazard": dq(Fraction(gone, len(risk)), 6) if risk else ""})
    return rows


# ---- 07 ------------------------------------------------------------------------------------------------------------------
def _completions(c: Ctx):
    w = WINDOWS["full"]
    by_ticket: dict[str, list] = defaultdict(list)
    for s in c.pop.surveys:
        by_ticket[s.ticket_id].append(s)
    for t in c.pop.tickets:
        h = c.hist[t.ticket_id]
        if inside(h.final_resolution, w):
            yield t, h, by_ticket.get(t.ticket_id, [])


def _flags(s) -> tuple[bool, bool, bool]:
    inv = s.invited_at is not None
    resp = inv and s.score is not None and s.response_at is not None
    pos = inv and s.score is not None and s.score >= 4 and s.response_at is not None
    return inv, resp, pos


def expected_07a(c: Ctx) -> list[dict]:
    acc: dict[str, dict[str, int]] = {g: defaultdict(int) for g in ("good experience", "poor experience", "ALL")}
    for t, h, svs in _completions(c):
        fr_t, rs_t = c.policy[t.priority]
        poor = ((h.first_human_reply_at is not None and mins(t.created_at, h.first_human_reply_at) > fr_t)
                or mins(t.created_at, h.final_resolution) > rs_t or bool(h.transfers) or h.reopen_count > 0)
        g = "poor experience" if poor else "good experience"
        for key in (g, "ALL"):
            acc[key]["n"] += 1
            for s in svs:
                inv, resp, pos = _flags(s)
                acc[key]["inv"] += inv
                acc[key]["resp"] += resp
                acc[key]["pos"] += pos
    rows = []
    for g, d in acc.items():
        rows.append({"experience": g, "completions": d["n"], "invited": d["inv"], "invitation_rate": dq(Fraction(d["inv"], d["n"]), 6),
                     "valid_responses": d["resp"], "response_rate": dq(Fraction(d["resp"], d["inv"]), 6) if d["inv"] else "",
                     "positive": d["pos"], "csat": dq(Fraction(d["pos"], d["resp"]), 6) if d["resp"] else ""})
    return rows


def expected_07b(c: Ctx) -> list[dict]:
    inv = resp = pos = 0
    for t, h, svs in _completions(c):
        for s in svs:
            i, r, p = _flags(s)
            inv += i
            resp += r
            pos += p
    return [{"reading": "CSAT among valid responses (the contract figure)", "positive": pos, "denominator": resp, "value": dq(Fraction(pos, resp), 6)},
            {"reading": "lower bound: every non-responder not positive", "positive": pos, "denominator": inv, "value": dq(Fraction(pos, inv), 6)},
            {"reading": "upper bound: every non-responder positive", "positive": pos + inv - resp, "denominator": inv,
             "value": dq(Fraction(pos + inv - resp, inv), 6)}]


def expected_07c(c: Ctx) -> list[dict]:
    acc: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for t, h, svs in _completions(c):
        for s in svs:
            i, r, p = _flags(s)
            for key in (t.queue_id, "ALL"):
                d = acc[key]
                d["inv"] += i
                d["resp"] += r
                d["pos"] += p
                if r:
                    d[f"s{s.score}"] += 1
    rows = []
    for q in sorted(k for k in acc if k != "ALL") + ["ALL"]:
        d = acc[q]
        rows.append({"queue_id": q, "invited": d["inv"], "valid_responses": d["resp"],
                     "response_rate": dq(Fraction(d["resp"], d["inv"]), 6) if d["inv"] else "",
                     **{f"score_{k}": d[f"s{k}"] for k in range(1, 6)}, "csat": dq(Fraction(d["pos"], d["resp"]), 6) if d["resp"] else ""})
    return rows


# ---- 08 ------------------------------------------------------------------------------------------------------------------
DEFECT_OF = {"BOT_AS_HUMAN_REPLY": "INJ-01", "AGENT_NOT_QUALIFIED": "INJ-03", "CONCURRENCY_EXCEEDED": "INJ-04",
             "TRANSFER_RESETS_ARRIVAL": "INJ-06", "TICKET_REJECTED": "dependants of INJ-03 / INJ-04 / INJ-06"}


def expected_08a(c: Ctx) -> list[dict]:
    g: dict[tuple, list] = defaultdict(list)
    for r in c.res.ingest.rejected:
        g[(r.entity, r.reason_code)].append(r.id)
    rows = []
    keys = sorted(sorted(g, key=lambda k: k[1]), key=lambda k: k[0], reverse=True)       # entity descending, then reason code
    for (ent, reason) in keys:
        ids = sorted(g[(ent, reason)])
        rows.append({"entity": ent, "reason_code": reason, "injected_defect": DEFECT_OF[reason], "rejected_rows": len(ids),
                     "distinct_ids": len(set(ids)), "first_and_last_id": f"{ids[0]} .. {ids[-1]}"})
    return rows


def expected_08b(c: Ctx) -> list[dict]:
    """Only injection_id and found are compared with the SQL (the check texts live in the SQL file)."""
    rej = defaultdict(int)
    for r in c.res.ingest.rejected:
        rej[r.reason_code] += 1
    first_ticket: dict[str, datetime] = {}
    for t in c.pop.tickets:
        first_ticket[t.customer_id] = min(first_ticket.get(t.customer_id, t.created_at), t.created_at)
    inj02 = sum(1 for cu in c.pop.customers if cu.customer_id in first_ticket and cu.created_at == first_ticket[cu.customer_id])
    shifts_with_break = {b["shift_id"] for b in c.breaks}
    inj05 = sum(1 for s in c.pop.shifts if s.break_minutes == 0 and s.shift_id in shifts_with_break)
    zones = {a.agent_id: ZoneInfo(a.timezone) for a in c.pop.agents}
    inj08 = 0
    for s in c.pop.shifts:
        z = zones[s.agent_id]
        wall = s.ends_at.astimezone(z).replace(tzinfo=None) - s.starts_at.astimezone(z).replace(tzinfo=None)
        if wall != s.ends_at - s.starts_at and s.ends_at - s.starts_at == timedelta(minutes=480):
            inj08 += 1
    inj09 = 0
    for t, h, svs in _completions(c):
        fr_t, rs_t = c.policy[t.priority]
        poor = ((h.first_human_reply_at is not None and mins(t.created_at, h.first_human_reply_at) > fr_t)
                or mins(t.created_at, h.final_resolution) > rs_t or bool(h.transfers) or h.reopen_count > 0)
        if poor:
            inj09 += sum(1 for s in svs if s.invited_at is not None and (s.score is None or s.response_at is None))
    found = {"INJ-01": rej["BOT_AS_HUMAN_REPLY"], "INJ-02": inj02, "INJ-03": rej["AGENT_NOT_QUALIFIED"], "INJ-04": rej["CONCURRENCY_EXCEEDED"],
             "INJ-05": inj05, "INJ-06": rej["TRANSFER_RESETS_ARRIVAL"], "INJ-07": sum(1 for r in c.pop.simulation_runs if r.warmup_minutes == 0),
             "INJ-08": inj08, "INJ-09": inj09}
    return [{"injection_id": k, "found": v} for k, v in sorted(found.items())]


def expected_08c(c: Ctx) -> list[dict]:
    rej = defaultdict(int)
    for r in c.res.ingest.rejected:
        rej[r.entity] += 1
    loaded = {"tickets": len(c.pop.tickets), "ticket_events": len(c.pop.ticket_events), "surveys": len(c.pop.surveys)}
    return [{"entity": e, "loaded_rows": loaded[e], "rejected_rows": rej[e], "published_rows": loaded[e] + rej[e]}
            for e in ("tickets", "ticket_events", "surveys")]


#: result key -> (function, compared columns or None for all)
KEYS = {
    "01_arrivals_by_hour_of_week": (expected_01, None),
    "02_wait_and_response_distributions__first_response_and_wait": (expected_02a, None),
    "02_wait_and_response_distributions__resolution_tail": (expected_02b, None),
    "03_sla_compliance_and_open_overdue__compliance_by_priority_and_window": (expected_03a, None),
    "03_sla_compliance_and_open_overdue__compliance_by_queue_and_priority": (expected_03d, None),
    "03_sla_compliance_and_open_overdue__open_overdue_at_monday_cutoffs": (expected_03b, None),
    "03_sla_compliance_and_open_overdue__overdue_exposure_by_priority": (expected_03c, None),
    "04_occupancy_by_agent_and_shift__occupancy_by_agent": (expected_04a, None),
    "04_occupancy_by_agent_and_shift__breaks_declared_vs_recorded": (expected_04b, None),
    "04_occupancy_by_agent_and_shift__monday_bind_handling_by_queue": (expected_04c, None),
    "04_occupancy_by_agent_and_shift__occupancy_by_skill_set": (expected_04d, None),
    "05_transfer_and_reopen_effects__by_transfer_and_reopen": (expected_05a, None),
    "05_transfer_and_reopen_effects__transfer_routes": (expected_05b, None),
    "06_abandonment_by_channel_and_patience__abandonment_by_channel": (expected_06a, None),
    "06_abandonment_by_channel_and_patience__abandonment_hazard_by_wait": (expected_06b, None),
    "07_survey_response_skew__response_by_experience": (expected_07a, None),
    "07_survey_response_skew__csat_and_its_bounds": (expected_07b, None),
    "07_survey_response_skew__score_distribution_by_queue": (expected_07c, None),
    "08_rejections_and_defects_by_reason__rejected_by_reason": (expected_08a, None),
    "08_rejections_and_defects_by_reason__injected_defects_found": (expected_08b, ("injection_id", "found")),
    "08_rejections_and_defects_by_reason__published_vs_loaded": (expected_08c, None),
}


def expected(c: Ctx) -> dict[str, list[dict]]:
    return {k: fn(c) for k, (fn, _) in KEYS.items()}


def compare(key: str, sql_rows: list[dict], py_rows: list[dict]) -> list[str]:
    """Cell differences between a SQL (or stored) result and the Python side, as readable strings (empty when equal)."""
    cols = KEYS[key][1]
    diffs: list[str] = []
    if len(sql_rows) != len(py_rows):
        return [f"{key}: {len(sql_rows)} rows against {len(py_rows)}"]
    for i, (a, b) in enumerate(zip(sql_rows, py_rows)):
        for col in (cols or list(b)):
            if col not in a:
                diffs.append(f"{key}[{i}]: column {col} missing")
            elif norm(a[col]) != norm(b[col]):
                diffs.append(f"{key}[{i}].{col}: {norm(a[col])!r} against {norm(b[col])!r}")
    return diffs
