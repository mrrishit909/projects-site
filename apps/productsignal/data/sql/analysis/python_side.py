"""The Python side of the reconciliation of docs/sql-analysis.md (P06-ART-04): every result set of the eight investigations, recomputed from the
published snapshot ``web/public/data`` WITHOUT PostgreSQL, so that run_all.py (and tests/test_artifacts.py, which runs it again without a database) can
compare it cell by cell with what the SQL returns.

Independence: the SQL derives the canonical event log, the signups and every statistic from facts in PostgreSQL (00_canonical_events.sql, a copy of the
common table expressions of data/sql/reference_metrics.sql, numeric arithmetic, a Maclaurin series for erfc); this file derives them from the raw JSON rows in
plain Python (its own event canonicalisation, ``zoneinfo`` for the local calendars, Fraction and Decimal for the arithmetic, its own Wilson, Newcombe, chi-square,
Student t and Welch code) and imports NOTHING from the ProductSignal domain. Only the Student t quantile table ``data/sql/t_quantiles.csv`` (generated from the
domain's quantile once; the SQL reads it too) is shared. The 706-check reference script and the domain are compared with these figures separately, in run_all.py.

Every block function returns a list of dicts whose keys are the SQL column names, in the SQL ``ORDER BY`` order; ``norm`` renders a value the way run_all.py renders
a database value (None -> '', datetimes in UTC with a Z, Decimals with their scale). No float is used in a published figure.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT / "web" / "public" / "data"
T_TABLE = ROOT / "data" / "sql" / "t_quantiles.csv"
UTC = timezone.utc
ENTITIES = ["accounts", "users", "identity_links", "sessions", "events", "event_properties", "subscriptions", "experiment_versions", "assignments",
            "exposures", "metric_observations", "analysis_runs"]
V1, V2 = "xv-001", "xv-002"
RUNS = {"an-001": "2026-05-18T00:00:00Z", "an-002": "2026-06-15T00:00:00Z", "an-003": "2026-07-13T00:00:00Z", "an-004": "2026-08-02T00:00:00Z",
        "an-005": "2026-10-04T00:00:00Z", "as-of": "2026-10-05T00:00:00Z"}
CUT_LABELS = {"an-001": RUNS["an-001"], "an-002": RUNS["an-002"], "an-003": RUNS["an-003"], "an-004": RUNS["an-004"], "inj-06 earlier read": "2026-10-02T12:00:00Z",
              "an-005": RUNS["an-005"], "as-of": RUNS["as-of"]}
ASOF = RUNS["as-of"]
V1_READS = ("an-001", "an-002", "an-003", "an-004", "as-of")
GAP_ENDS = "2026-04-08T00:00:00Z"
BLOCKS: dict[str, Callable[["Ctx"], list[dict[str, Any]]]] = {}
KEYS: list[str] = []


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def z(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return z(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


def rnd(x: F | Decimal | int, places: int) -> Decimal:
    """Half-up (away from zero) rounding to ``places`` decimals, exact for Fractions, as a Decimal that carries its scale (PostgreSQL's round)."""
    if isinstance(x, Decimal):
        with localcontext() as ctx:
            ctx.prec = 200
            return x.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    f = F(x)
    sign = -1 if f < 0 else 1
    n = abs(f.numerator) * 10 ** places
    q = (2 * n + f.denominator) // (2 * f.denominator)
    return Decimal(sign * q).scaleb(-places)


def ratio6(a: int, b: int) -> Decimal | None:
    return None if b == 0 else rnd(F(a, b), 6)


def block(key: str):
    def deco(fn):
        BLOCKS[key] = fn
        KEYS.append(key)
        return fn
    return deco


# ---- exact statistics (own code; Decimal at 80 digits, the rounding points of the SQL: sqrt arguments rounded to 40 places) ----------------------------------
def D(x: F | int | str) -> Decimal:
    if isinstance(x, F):
        with localcontext() as ctx:
            ctx.prec = 100
            return Decimal(x.numerator) / Decimal(x.denominator)
    return Decimal(x)


def r40(x: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 200
        return x.quantize(Decimal(1).scaleb(-40), rounding=ROUND_HALF_UP)


def sqrt40(x: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 100
        return r40(x).sqrt()


def wilson(x: int, n: int, zc: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """(p, low, high) of the Wilson score interval."""
    with localcontext() as ctx:
        ctx.prec = 100
        p = D(F(x, n))
        nn = Decimal(n)
        root = sqrt40(p * (1 - p) / nn + zc ** 2 / (4 * nn * nn))
        lo = (p + zc ** 2 / (2 * nn) - zc * root) / (1 + zc ** 2 / nn)
        hi = (p + zc ** 2 / (2 * nn) + zc * root) / (1 + zc ** 2 / nn)
        return p, lo, hi


def newcombe(xt: int, nt: int, xc: int, nc: int, zc: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """(d, low, high, control proportion) of the Newcombe hybrid score interval for treatment minus control."""
    with localcontext() as ctx:
        ctx.prec = 100
        pt, lt, ht = wilson(xt, nt, zc)
        pc, lc, hc = wilson(xc, nc, zc)
        d = pt - pc
        return d, d - sqrt40((pt - lt) ** 2 + (hc - pc) ** 2), d + sqrt40((ht - pt) ** 2 + (pc - lc) ** 2), pc


def erfc_p(stat: F) -> Decimal:
    """Two-sided chi-square (df 1) tail probability erfc(sqrt(stat / 2)) by the Maclaurin series of erf at 120 digits."""
    if stat <= 0:
        return Decimal(1)
    if stat > 100:
        return Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 140
        x = (D(stat) / 2).sqrt()
        term, s, n = x, Decimal(0), 0
        while abs(term) > Decimal("1e-70"):
            s += term / (2 * n + 1)
            n += 1
            term = -term * x * x / n
        pi = Decimal("3.14159265358979323846264338327950288419716939937510582097494459230781640628620899862803482534211706798")
        return 1 - 2 * s / pi.sqrt()


def load_t() -> dict[int, Decimal]:
    return {int(r[0]): Decimal(r[1]) for r in list(csv.reader(T_TABLE.read_text().splitlines()))[1:]}


# ---- the data ----------------------------------------------------------------------------------------------------------------------------------------------
class Ev:
    __slots__ = ("event_id", "user_id", "anon", "name", "at", "recv", "props", "rn", "u", "acct", "cls", "vk")


class Ctx:
    """The snapshot rows, the canonical log per cutoff and the lookups the blocks share."""

    def __init__(self) -> None:
        self.manifest = json.loads((DATA / "manifest.json").read_text())
        self.rows = {e: json.loads((DATA / f"{e}.json").read_text())["rows"] for e in ENTITIES}
        self.cuts = {label: ts(s) for label, s in CUT_LABELS.items()}
        self.accounts = {a["account_id"]: a for a in self.rows["accounts"]}
        self.users = {u["user_id"]: u for u in self.rows["users"]}
        self.tz = {k: ZoneInfo(a["timezone"]) for k, a in self.accounts.items()}
        self.plans = self.manifest["analysis_plans"]
        self.windows = self.manifest["metric_windows"]
        links = sorted(self.rows["identity_links"], key=lambda l: (l["linked_at"], l["identity_link_id"]))
        self.first_link: dict[str, dict] = {}
        self.anon_of_user: dict[str, str] = {}
        for l in links:
            self.first_link.setdefault(l["anonymous_id"], l)
            self.anon_of_user.setdefault(l["user_id"], l["anonymous_id"])
        props: dict[str, dict[str, str]] = defaultdict(dict)
        for p in self.rows["event_properties"]:
            props[p["event_id"]][p["property_key"]] = p["property_value"]
        self.raw = [(e, ts(e["event_at"]), ts(e["received_at"]), props.get(e["event_id"], {})) for e in self.rows["events"]]
        self.log: dict[str, list[Ev]] = {}
        self.signup: dict[str, dict[str, datetime]] = {}
        for label, c in self.cuts.items():
            self.log[label] = self.canonical(c)
            sg: dict[str, datetime] = {}
            for e in self.log[label]:
                if e.cls == "analysed" and e.name == "signup" and e.acct is not None and (e.acct not in sg or e.at < sg[e.acct]):
                    sg[e.acct] = e.at
            self.signup[label] = sg
        self.asg = defaultdict(list)
        for a in sorted(self.rows["assignments"], key=lambda a: (a["assigned_at"], a["assignment_id"])):
            self.asg[a["experiment_version_id"]].append(a)
        self.exposure = {x["assignment_id"]: ts(x["exposed_at"]) for x in self.rows["exposures"]}
        self.sessions: list[tuple[str, datetime]] = []                       # (account, started_at) of non-bot users of non-internal accounts
        for s in self.rows["sessions"]:
            u = self.users[s["user_id"]]
            if not u["bot_flag"] and not self.accounts[u["account_id"]]["internal"]:
                self.sessions.append((u["account_id"], ts(s["started_at"])))
        self.runs = [r for r in self.rows["analysis_runs"]]
        self.t = load_t()

    def canonical(self, c: datetime) -> list[Ev]:
        groups: dict[tuple, list] = defaultdict(list)
        for e, at, recv, pr in self.raw:
            if recv <= c:
                actor = e["user_id"] if e["user_id"] is not None else e["anonymous_id"]
                groups[(actor, e["event_name"], at, tuple(sorted(pr.items())))].append((recv, e["event_id"], e, at, pr))
        out: list[Ev] = []
        for lst in groups.values():
            lst.sort(key=lambda t: (t[0], t[1]))
            for rn, (recv, eid, e, at, pr) in enumerate(lst, start=1):
                v = Ev()
                v.event_id, v.user_id, v.anon, v.name, v.at, v.recv, v.props, v.rn = eid, e["user_id"], e["anonymous_id"], e["event_name"], at, recv, pr, rn
                fl = self.first_link.get(e["anonymous_id"]) if e["anonymous_id"] is not None else None
                if e["user_id"] is not None:
                    v.u = e["user_id"]
                elif fl is not None and ts(fl["linked_at"]) <= at:
                    v.u = fl["user_id"]
                else:
                    v.u = None
                usr = self.users.get(v.u) if v.u is not None else None
                v.acct = usr["account_id"] if usr else None
                if rn > 1:
                    v.cls = "duplicate"
                elif (e["user_id"] is None and e["anonymous_id"] is None) or (v.u is not None and usr is None):
                    v.cls = "unknown"
                elif v.u is not None and usr["bot_flag"]:
                    v.cls = "bot"
                elif v.u is not None and self.accounts[usr["account_id"]]["internal"]:
                    v.cls = "internal"
                else:
                    v.cls = "analysed"
                v.vk = e["anonymous_id"] or self.anon_of_user.get(e["user_id"]) or "user:" + str(e["user_id"])
                out.append(v)
        return out

    # lookups --------------------------------------------------------------------------------------------------------------------------------------------
    def analysed(self, label: str, name: str) -> list[Ev]:
        return [e for e in self.log[label] if e.cls == "analysed" and e.name == name]

    def local(self, acct: str, t: datetime) -> date:
        return t.astimezone(self.tz[acct]).date()

    def activated(self, label: str, acct: str, lo: datetime, hi: datetime) -> bool:
        return any(e.acct == acct and lo <= e.at < hi for e in self._act(label))

    def _act(self, label: str) -> list[Ev]:
        cache = self.__dict__.setdefault("_actcache", {})
        if label not in cache:
            cache[label] = self.analysed(label, "activated")
        return cache[label]

    def _act_by_acct(self, label: str) -> dict[str, list[datetime]]:
        cache = self.__dict__.setdefault("_actacct", {})
        if label not in cache:
            d: dict[str, list[datetime]] = defaultdict(list)
            for e in self._act(label):
                if e.acct is not None:
                    d[e.acct].append(e.at)
            cache[label] = d
        return cache[label]

    def act_in(self, label: str, acct: str, lo: datetime, hi: datetime) -> bool:
        return any(lo <= t < hi for t in self._act_by_acct(label).get(acct, ()))


def load() -> Ctx:
    return Ctx()


H168 = timedelta(hours=168)


def sess_days(ctx: Ctx) -> dict[str, list[tuple[date, datetime]]]:
    d: dict[str, list[tuple[date, datetime]]] = defaultdict(list)
    for acct, t in ctx.sessions:
        d[acct].append((ctx.local(acct, t), t))
    return d


# =========================================================================================== 01 activation by plan and segment
def _asof_accounts(ctx: Ctx) -> list[dict]:
    sg = ctx.signup["as-of"]
    asof = ctx.cuts["as-of"]
    out = []
    for a in ctx.rows["accounts"]:
        if a["internal"]:
            continue
        s = sg.get(a["account_id"])
        mature = s is not None and s + H168 <= asof
        act = s is not None and ctx.act_in("as-of", a["account_id"], s, s + H168)
        out.append({"id": a["account_id"], "plan": a["plan"], "segment": a["segment"], "signup": s, "mature": mature, "activated": act})
    return out


def _grp(rows: list[dict]) -> dict[str, Any]:
    mature = [r for r in rows if r["mature"]]
    act = sum(1 for r in mature if r["activated"])
    return {"accounts": len(rows), "signed_up": sum(1 for r in rows if r["signup"] is not None),
            "immature": sum(1 for r in rows if r["signup"] is not None and not r["mature"]), "mature": len(mature), "activated": act,
            "activation_rate": ratio6(act, len(mature))}


@block("01_activation_by_plan_and_segment__plan_segment")
def b01_plan_segment(ctx: Ctx):
    rows = _asof_accounts(ctx)
    out = []

    def add(plan: str, seg: str, sub: list[dict]) -> None:
        out.append({"plan": plan, "segment": seg, **_grp(sub)})
    plans = sorted({r["plan"] for r in rows})
    segs = sorted({r["segment"] for r in rows})
    for p in plans:
        for s in segs:
            sub = [r for r in rows if r["plan"] == p and r["segment"] == s]
            if sub:
                add(p, s, sub)
        add(p, "ALL", [r for r in rows if r["plan"] == p])
    for s in segs:
        add("ALL", s, [r for r in rows if r["segment"] == s])
    add("ALL", "ALL", rows)
    return out


@block("01_activation_by_plan_and_segment__by_signup_month")
def b01_month(ctx: Ctx):
    rows = [r for r in _asof_accounts(ctx) if r["signup"] is not None]
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["signup"].strftime("%Y-%m")].append(r)
    out = []
    for m in sorted(by):
        g = _grp(by[m])
        out.append({"signup_month": m, "signups": g["signed_up"], "immature": g["immature"], "mature": g["mature"], "activated": g["activated"],
                    "activation_rate": g["activation_rate"]})
    return out


@block("01_activation_by_plan_and_segment__window_check")
def b01_window(ctx: Ctx):
    w = ctx.windows["activation"]
    lo, hi, days = ts(w["from"]), ts(w["to"]), w["window_days"]
    asof = ctx.cuts["as-of"]
    pop = [r for r in _asof_accounts(ctx) if r["signup"] is not None and lo <= r["signup"] < hi]
    mature = [r for r in pop if r["signup"] + timedelta(hours=24 * days) <= asof]
    act = sum(1 for r in mature if ctx.act_in("as-of", r["id"], r["signup"], r["signup"] + timedelta(hours=24 * days)))
    return [{"signups": len(pop), "immature": len(pop) - len(mature), "mature": len(mature), "activated": act, "activation_rate": ratio6(act, len(mature))}]


@block("01_activation_by_plan_and_segment__time_to_activation_by_plan")
def b01_time(ctx: Ctx):
    treated = {a["unit_id"] for v in ctx.asg.values() for a in v if a["variant"] == "treatment"}
    asof = ctx.cuts["as-of"]
    by: dict[str, list[tuple[bool, int | None]]] = defaultdict(list)
    for r in _asof_accounts(ctx):
        if r["signup"] is None or not r["mature"] or r["id"] in treated:
            continue
        firsts = [t for t in ctx._act_by_acct("as-of").get(r["id"], ()) if r["signup"] <= t < r["signup"] + H168]
        by[r["plan"]].append((bool(firsts), int((min(firsts) - r["signup"]).total_seconds()) if firsts else None))
    out = []
    for p in sorted(by):
        waits = sorted(w for ok, w in by[p] if ok)
        out.append({"plan": p, "accounts": len(by[p]), "activated": len(waits), "activation_rate": ratio6(len(waits), len(by[p])),
                    "median_hours_to_activate": rnd(F(waits[len(waits) // 2], 3600), 2) if waits else None})
    return out


# =========================================================================================== 02 weekly cohort grid
def _cohort_flags(ctx: Ctx, acct: str, d0: date, dc: date, days: list[tuple[date, datetime]]) -> dict[str, bool]:
    idx = [(d - d0).days for d, _ in days]
    return {"m1": d0 + timedelta(days=2) <= dc, "m7": d0 + timedelta(days=8) <= dc, "m14": d0 + timedelta(days=15) <= dc, "m28": d0 + timedelta(days=29) <= dc,
            "m35": d0 + timedelta(days=35) <= dc, "r1": 1 in idx, "r7": 7 in idx, "r14": 14 in idx, "r28": 28 in idx, "r7plus": any(i >= 7 for i in idx),
            "r4w": any(28 <= i <= 34 for i in idx)}


def _cohort(ctx: Ctx):
    sd = sess_days(ctx)
    asof = ctx.cuts["as-of"]
    out = []
    for acct, s in sorted(ctx.signup["as-of"].items()):
        if ctx.accounts[acct]["internal"]:
            continue
        d0, dc = ctx.local(acct, s), ctx.local(acct, asof)
        out.append((acct, s, d0, dc, _cohort_flags(ctx, acct, d0, dc, sd.get(acct, []))))
    return out


@block("02_weekly_cohort_grid__cohort_grid")
def b02_grid(ctx: Ctx):
    rows = _cohort(ctx)
    by: dict[date, list] = defaultdict(list)
    for r in rows:
        by[r[2] - timedelta(days=r[2].weekday())].append(r)

    def agg(label: str, sub: list) -> dict:
        n = len(sub)
        f = lambda m, r_=None: sum(1 for x in sub if x[4][m] and (r_ is None or x[4][r_]))      # noqa: E731
        m7, m35 = f("m7"), f("m35")
        return {"week_start": label, "accounts": n, "day1_mature": f("m1"), "day1_retained": f("m1", "r1"), "day7_mature": m7, "day7_retained": f("m7", "r7"),
                "day14_mature": f("m14"), "day14_retained": f("m14", "r14"), "day28_mature": f("m28"), "day28_retained": f("m28", "r28"),
                "on_or_after_day7_mature": m7, "on_or_after_day7_retained": f("m7", "r7plus"), "week4_mature": m35, "week4_retained": f("m35", "r4w"),
                "day7_status": "blank" if m7 == 0 else "partial" if m7 < n else "complete", "week4_status": "blank" if m35 == 0 else "partial" if m35 < n else "complete"}
    out = [agg(w.isoformat(), by[w]) for w in sorted(by)]
    out.append(agg("ALL", rows))
    return out


@block("02_weekly_cohort_grid__window_check")
def b02_window(ctx: Ctx):
    w = ctx.windows["retention"]
    lo, hi = date.fromisoformat(w["signup_from"]), date.fromisoformat(w["signup_to"])
    rows = [r for r in _cohort(ctx) if lo <= r[2] < hi]
    m7 = [r for r in rows if r[4]["m7"]]
    m35 = [r for r in rows if r[4]["m35"]]
    internal = {e.acct for e in ctx.log["as-of"] if e.cls == "internal" and e.name == "signup" and e.acct is not None and lo <= ctx.local(e.acct, e.at) < hi}
    r7 = sum(1 for r in m7 if r[4]["r7"])
    r7p = sum(1 for r in m7 if r[4]["r7plus"])
    r4 = sum(1 for r in m35 if r[4]["r4w"])
    return [{"cohort_accounts": len(rows), "day7_mature": len(m7), "day7_retained": r7, "day7_rate": ratio6(r7, len(m7)), "on_or_after_day7_retained": r7p,
             "on_or_after_day7_rate": ratio6(r7p, len(m7)), "week4_mature": len(m35), "week4_retained": r4, "week4_rate": ratio6(r4, len(m35)),
             "excluded_internal_accounts": len(internal)}]


@block("02_weekly_cohort_grid__timezone_effect")
def b02_tz(ctx: Ctx):
    asof = ctx.cuts["as-of"]
    by: dict[str, list[dict]] = defaultdict(list)
    sess_by: dict[str, list[datetime]] = defaultdict(list)
    for acct, t in ctx.sessions:
        if t < asof:
            sess_by[acct].append(t)
    for acct, s in ctx.signup["as-of"].items():
        a = ctx.accounts[acct]
        if a["internal"]:
            continue
        d0, dc = ctx.local(acct, s), ctx.local(acct, asof)
        local7 = any((ctx.local(acct, t) - d0).days == 7 for t in sess_by.get(acct, ()))
        utc7 = any((t.date() - s.date()).days == 7 for t in sess_by.get(acct, ()))
        by[a["timezone"]].append({"m7": d0 + timedelta(days=8) <= dc, "local7": local7, "utc7": utc7})

    def agg(label: str, sub: list[dict]) -> dict:
        m = [x for x in sub if x["m7"]]
        return {"timezone": label, "mature_accounts": len(m), "exact_day7_local": sum(1 for x in m if x["local7"]), "exact_day7_utc": sum(1 for x in m if x["utc7"]),
                "local_only": sum(1 for x in m if x["local7"] and not x["utc7"]), "utc_only": sum(1 for x in m if x["utc7"] and not x["local7"])}
    out = [agg(tz, by[tz]) for tz in sorted(by)]
    out.append(agg("ALL", [x for v in by.values() for x in v]))
    return out


# =========================================================================================== 03 funnel
def _funnel_units(events: list[Ev], steps: list[str], gap_h: int, w_from: datetime, w_to: datetime) -> list[int]:
    by: dict[str, list[Ev]] = defaultdict(list)
    for e in events:
        by[e.vk].append(e)
    counts = [0] * len(steps)
    gap = timedelta(hours=gap_h)
    for evs in by.values():
        first = [e.at for e in evs if e.name == steps[0] and w_from <= e.at < w_to]
        if not first:
            continue
        prev = min(first)
        counts[0] += 1
        for k in range(1, len(steps)):
            nxt = [e.at for e in evs if e.name == steps[k] and prev < e.at <= prev + gap]
            if not nxt:
                break
            counts[k] += 1
            prev = min(nxt)
    return counts


def _fd(ctx: Ctx):
    f = ctx.windows["funnel"]
    return f["steps"], f["max_gap_hours"], ts(f["from"]), ts(f["to"])


@block("03_funnel_steps_and_exclusions__funnel_steps")
def b03_steps(ctx: Ctx):
    steps, gap, lo, hi = _fd(ctx)
    u = _funnel_units([e for e in ctx.log["as-of"] if e.cls == "analysed"], steps, gap, lo, hi)
    out = []
    for i, (name, n) in enumerate(zip(steps, u), start=1):
        out.append({"step_number": i, "step": name, "units": n, "conversion_from_previous": None if i == 1 or u[i - 2] == 0 else ratio6(n, u[i - 2]),
                    "conversion_from_first": ratio6(n, u[0]), "lost_at_this_step": None if i == 1 else u[i - 2] - n})
    return out


@block("03_funnel_steps_and_exclusions__funnel_gap_sensitivity")
def b03_gap(ctx: Ctx):
    steps, _, lo, hi = _fd(ctx)
    ev = [e for e in ctx.log["as-of"] if e.cls == "analysed"]
    out = []
    for g in (24, 48, 72):
        u = _funnel_units(ev, steps, g, lo, hi)
        out.append({"max_gap_hours": g, "visit": u[0], "signup": u[1], "onboarding_step_1": u[2], "activated": u[3], "overall_conversion": ratio6(u[3], u[0])})
    return out


@block("03_funnel_steps_and_exclusions__signup_conversion")
def b03_conv(ctx: Ctx):
    w = ctx.windows["signup_conversion"]
    lo, hi = ts(w["from"]), ts(w["to"])
    ev = [e for e in ctx.log["as-of"] if e.cls == "analysed"]
    vis = {e.anon for e in ev if e.name == "visit" and e.anon is not None and lo <= e.at < hi}
    sgn = {e.anon for e in ev if e.name == "signup" and e.anon in vis and lo <= e.at < hi}
    return [{"visitors": len(vis), "signed_up": len(sgn), "signup_conversion": ratio6(len(sgn), len(vis))}]


@block("03_funnel_steps_and_exclusions__exclusions_by_event")
def b03_excl(ctx: Ctx):
    log = ctx.log["as-of"]
    names = sorted({e.name for e in log})

    def row(label: str, sub: list[Ev]) -> dict:
        c = lambda k: sum(1 for e in sub if e.cls == k)      # noqa: E731
        return {"event_name": label, "rows_received": len(sub), "duplicates_dropped": c("duplicate"), "unknown_identity": c("unknown"), "bot_excluded": c("bot"),
                "internal_excluded": c("internal"), "analysed": c("analysed")}
    return [row(n, [e for e in log if e.name == n]) for n in names] + [row("ALL", log)]


@block("03_funnel_steps_and_exclusions__late_batch_effect")
def b03_late(ctx: Ctx):
    steps, gap, lo, hi = _fd(ctx)
    read = ctx.cuts["inj-06 earlier read"]
    known = _funnel_units([e for e in ctx.log["inj-06 earlier read"] if e.cls == "analysed"], steps, gap, lo, hi)
    hind = _funnel_units([e for e in ctx.log["as-of"] if e.cls == "analysed" and e.at <= read], steps, gap, lo, hi)
    cols = ("visit", "signup", "onboarding_step_1", "activated")
    rows = [{"reading": "known_at_the_read", **dict(zip(cols, known))}, {"reading": "in_hindsight", **dict(zip(cols, hind))},
            {"reading": "late batch (hindsight - known)", **{c: h - k for c, h, k in zip(cols, hind, known)}}]
    return sorted(rows, key=lambda r: r["reading"], reverse=True)


# =========================================================================================== 04 tracking quality
def _monday(t: datetime) -> date:
    d = t.astimezone(UTC).date()
    return d - timedelta(days=d.weekday())


@block("04_tracking_quality_by_week__by_week")
def b04_week(ctx: Ctx):
    log = ctx.log["as-of"]
    by: dict[date, list[Ev]] = defaultdict(list)
    for e in log:
        by[_monday(e.at)].append(e)

    def row(label: str, sub: list[Ev]) -> dict:
        canon = [e for e in sub if e.rn == 1]
        delayed = sum(1 for e in canon if e.recv - e.at > timedelta(hours=24))
        c = lambda k: sum(1 for e in sub if e.cls == k)      # noqa: E731
        return {"week_start": label, "rows_total": len(sub), "duplicates_dropped": c("duplicate"), "canonical": len(canon), "delayed_over_24h": delayed,
                "unknown_identity": c("unknown"), "bot_excluded": c("bot"), "internal_excluded": c("internal"), "analysed": c("analysed"),
                "anonymous_events": sum(1 for e in sub if e.cls == "analysed" and e.user_id is None),
                "attributed_by_link": sum(1 for e in sub if e.cls == "analysed" and e.user_id is None and e.u is not None),
                "delayed_share": ratio6(delayed, len(canon))}
    return [row(w.isoformat(), by[w]) for w in sorted(by)] + [row("ALL", log)]


@block("04_tracking_quality_by_week__delay_distribution")
def b04_delay(ctx: Ctx):
    late = [e for e in ctx.log["as-of"] if e.rn == 1 and e.recv - e.at > timedelta(hours=24)]

    def row(label: str, sub: list[Ev]) -> dict:
        hrs = [F(int((e.recv - e.at).total_seconds()), 3600) for e in sub]
        return {"event_name": label, "delayed_rows": len(sub), "hours_24_to_48": sum(1 for h in hrs if h <= 48), "days_2_to_7": sum(1 for h in hrs if 48 < h <= 168),
                "over_7_days": sum(1 for h in hrs if h > 168), "longest_delay_hours": rnd(max(hrs), 2)}
    return [row(n, [e for e in late if e.name == n]) for n in sorted({e.name for e in late})] + [row("ALL", late)]


@block("04_tracking_quality_by_week__identity_links")
def b04_ident(ctx: Ctx):
    real = {u["user_id"] for u in ctx.rows["users"] if not u["bot_flag"]}
    linked = {l["user_id"] for l in ctx.rows["identity_links"]} & real
    anon = [e for e in ctx.log["as-of"] if e.cls == "analysed" and e.user_id is None]
    return [{"links": len(ctx.rows["identity_links"]), "real_users": len(real), "real_users_linked": len(linked), "linked_share": ratio6(len(linked), len(real)),
             "anonymous_events": len(anon), "attributed_by_link": sum(1 for e in anon if e.u is not None), "remain_anonymous": sum(1 for e in anon if e.u is None)}]


# =========================================================================================== 05 experiment v1 at each run cutoff
def plan_facts(ctx: Ctx, xv: str) -> dict[str, Any]:
    p = ctx.plans[xv]
    body = {k: v for k, v in p.items() if k != "config_hash"}
    return {"z": Decimal(p["z"]), "planned_end": ts(p["planned_end"]), "frozen_at": ts(p["frozen_at"]), "share_c": p["allocation"]["control"], "share_t": p["allocation"]["treatment"],
            "p_threshold": Decimal(p["srm"]["p_threshold"]), "min_cell": Decimal(p["srm"]["min_expected_cell"]), "hash": p["config_hash"],
            "hash_ok": hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == p["config_hash"],
            "g_days": p["guardrail"]["window_days"], "rev_from": ts(p["revenue_window"]["from"]), "rev_to": ts(p["revenue_window"]["to"]), "conf": p["confidence"]}


def arm_rows(ctx: Ctx, xv: str, label: str, *, act_label: str | None = None, only_before: datetime | None = None) -> list[dict]:
    """One dict per assignment of ``xv`` with assigned_at <= the cutoff of ``label``: variant, mature, activated, exposed, signup (the log of ``label``)."""
    c = ctx.cuts[label]
    sg = ctx.signup[label]
    out = []
    for a in ctx.asg[xv]:
        at = ts(a["assigned_at"])
        if at > c:
            continue
        s = sg.get(a["unit_id"])
        mature = s is not None and s + H168 <= c
        act = s is not None and ctx.act_in(label, a["unit_id"], max(s, at), s + H168)
        ex = ctx.exposure.get(a["assignment_id"])
        out.append({"assignment": a, "unit": a["unit_id"], "variant": a["variant"], "assigned_at": at, "signup": s, "mature": mature, "activated": act,
                    "exposed": ex is not None and ex <= c})
    return out


def counts(rows: list[dict]) -> dict[str, int]:
    r = {}
    for v, k in (("control", "c"), ("treatment", "t")):
        sub = [x for x in rows if x["variant"] == v]
        r[f"asg_{k}"] = len(sub)
        r[f"n_{k}"] = sum(1 for x in sub if x["mature"])
        r[f"x_{k}"] = sum(1 for x in sub if x["mature"] and x["activated"])
        r[f"e_{k}"] = sum(1 for x in sub if x["mature"] and x["exposed"])
    return r


def srm(asg_c: int, asg_t: int, share_c: str, share_t: str, p_threshold: Decimal, min_cell: Decimal) -> tuple[F, Decimal, str]:
    n = asg_c + asg_t
    sc, st = F(share_c), F(share_t)
    stat = (asg_c - n * sc) ** 2 / (n * sc) + (asg_t - n * st) ** 2 / (n * st)
    p = erfc_p(stat)
    if min_cell > D(n * min(sc, st)):
        v = "INSUFFICIENT"
    elif p < p_threshold:
        v = "MISMATCH"
    else:
        v = "OK"
    return stat, p, v


@block("05_experiment_v1_at_each_run_cutoff__arms_by_cutoff")
def b05_arms(ctx: Ctx):
    zc = plan_facts(ctx, V1)["z"]
    out = []
    for label in V1_READS:
        rows = arm_rows(ctx, V1, label)
        k = counts(rows)
        for v, s in (("control", "c"), ("treatment", "t")):
            n, x = k[f"n_{s}"], k[f"x_{s}"]
            lo = hi = None
            if n:
                _, wl, wh = wilson(x, n, zc)
                lo, hi = rnd(wl, 6), rnd(wh, 6)
            out.append({"run": label, "cutoff_at": RUNS[label], "arm": v, "assigned": k[f"asg_{s}"], "immature_or_unobserved": k[f"asg_{s}"] - n, "mature": n, "activated": x,
                        "conversion": ratio6(x, n), "wilson_low": lo, "wilson_high": hi, "exposed": k[f"e_{s}"], "exposure_rate": ratio6(k[f"e_{s}"], n)})
    return out


@block("05_experiment_v1_at_each_run_cutoff__lift_by_cutoff")
def b05_lift(ctx: Ctx):
    pf = plan_facts(ctx, V1)
    runs = [r for r in ctx.runs if r["experiment_version_id"] == V1]
    first_created = min(ts(r["created_at"]) for r in runs)
    out = []
    for label in V1_READS:
        c = ctx.cuts[label]
        k = counts(arm_rows(ctx, V1, label))
        d, lo, hi, pc = newcombe(k["x_t"], k["n_t"], k["x_c"], k["n_c"], pf["z"])
        stat, p, verdict = srm(k["asg_c"], k["asg_t"], pf["share_c"], pf["share_t"], pf["p_threshold"], pf["min_cell"])
        run = next((r for r in runs if ts(r["cutoff_at"]) == c), None)
        prior = None if run is None else sum(1 for r in runs if ts(r["created_at"]) < ts(run["created_at"]))
        frozen = pf["frozen_at"] <= first_created
        interim = c < pf["planned_end"]
        zero = lo <= 0 <= hi
        with localcontext() as ctx_:
            ctx_.prec = 100
            rel = rnd(d / pc, 6) if pc > 0 else None
        out.append({"run": label, "cutoff_at": RUNS[label], "interim": interim, "prior_runs": prior, "assigned_control": k["asg_c"], "assigned_treatment": k["asg_t"],
                    "mature_control": k["n_c"], "mature_treatment": k["n_t"], "activated_control": k["x_c"], "activated_treatment": k["x_t"],
                    "conversion_control": ratio6(k["x_c"], k["n_c"]), "conversion_treatment": ratio6(k["x_t"], k["n_t"]), "absolute_lift_pp": rnd(d * 100, 2),
                    "relative_lift": rel, "newcombe_low": rnd(lo, 6), "newcombe_high": rnd(hi, 6), "interval_includes_zero": zero, "srm_statistic": rnd(F(stat), 6),
                    "srm_p_value": rnd(p, 6), "srm_verdict": verdict, "plan_hash_valid": pf["hash_ok"], "plan_frozen": frozen,
                    "conclusive": (not zero) and (not interim) and pf["hash_ok"] and frozen and verdict == "OK"})
    return out


def _mature_asof(ctx: Ctx) -> list[dict]:
    return [r for r in arm_rows(ctx, V1, "as-of") if r["mature"]]


@block("05_experiment_v1_at_each_run_cutoff__gap_accounts")
def b05_gap(ctx: Ctx):
    gap = ts(GAP_ENDS)
    out = []
    for v in ("control", "treatment"):
        sub = [r for r in _mature_asof(ctx) if r["variant"] == v]
        inside = [r for r in sub if r["signup"] < gap]
        outside = [r for r in sub if r["signup"] >= gap]
        out.append({"arm": v, "mature": len(sub), "activated": sum(1 for r in sub if r["activated"]), "published_conversion": ratio6(sum(1 for r in sub if r["activated"]), len(sub)),
                    "gap_accounts": len(inside), "gap_published_activations": sum(1 for r in inside if r["activated"]), "mature_excluding_gap": len(outside),
                    "activated_excluding_gap": sum(1 for r in outside if r["activated"]),
                    "conversion_excluding_gap": ratio6(sum(1 for r in outside if r["activated"]), len(outside))})
    return out


@block("05_experiment_v1_at_each_run_cutoff__gap_lift")
def b05_gaplift(ctx: Ctx):
    gap = ts(GAP_ENDS)
    rows = _mature_asof(ctx)
    out = []
    for reading, sub in (("published (all mature accounts)", rows), ("excluding the gap accounts from both arms", [r for r in rows if r["signup"] >= gap])):
        c = [r for r in sub if r["variant"] == "control"]
        t = [r for r in sub if r["variant"] == "treatment"]
        xc, xt = sum(1 for r in c if r["activated"]), sum(1 for r in t if r["activated"])
        out.append({"reading": reading, "mature_control": len(c), "activated_control": xc, "mature_treatment": len(t), "activated_treatment": xt,
                    "conversion_control": ratio6(xc, len(c)), "conversion_treatment": ratio6(xt, len(t)), "absolute_lift_pp": rnd((F(xt, len(t)) - F(xc, len(c))) * 100, 2)})
    return out


# =========================================================================================== 06 v2 sample ratio
@block("06_experiment_v2_sample_ratio__srm_by_read")
def b06_srm(ctx: Ctx):
    reads = [(V1, l) for l in ("an-001", "an-002", "an-003", "an-004", "as-of")] + [(V2, l) for l in ("an-005", "as-of")]
    out = []
    for xv, label in reads:
        pf = plan_facts(ctx, xv)
        c = ctx.cuts[label]
        asg = [a for a in ctx.asg[xv] if ts(a["assigned_at"]) <= c]
        nc = sum(1 for a in asg if a["variant"] == "control")
        nt = sum(1 for a in asg if a["variant"] == "treatment")
        n = nc + nt
        stat, p, verdict = srm(nc, nt, pf["share_c"], pf["share_t"], pf["p_threshold"], pf["min_cell"])
        out.append({"experiment_version": xv, "run": label, "cutoff_at": RUNS[label], "planned_control": pf["share_c"], "planned_treatment": pf["share_t"],
                    "observed_control": nc, "observed_treatment": nt, "expected_control": rnd(n * F(pf["share_c"]), 2), "expected_treatment": rnd(n * F(pf["share_t"]), 2),
                    "treatment_share": ratio6(nt, n), "statistic": rnd(stat, 6), "p_value": rnd(p, 6), "df": 1, "verdict": verdict})
    return sorted(out, key=lambda r: (r["experiment_version"], r["cutoff_at"]))


@block("06_experiment_v2_sample_ratio__v2_assignment_by_week")
def b06_weeks(ctx: Ctx):
    by: dict[date, list[dict]] = defaultdict(list)
    for a in ctx.asg[V2]:
        by[_monday(ts(a["assigned_at"]))].append(a)
    return [{"week_start": w.isoformat(), "control": sum(1 for a in by[w] if a["variant"] == "control"), "treatment": sum(1 for a in by[w] if a["variant"] == "treatment"),
             "assigned": len(by[w]), "treatment_share": ratio6(sum(1 for a in by[w] if a["variant"] == "treatment"), len(by[w]))} for w in sorted(by)]


@block("06_experiment_v2_sample_ratio__v2_population")
def b06_pop(ctx: Ctx):
    rows = arm_rows(ctx, V2, "as-of")
    out = []
    for v in ("control", "treatment"):
        sub = [r for r in rows if r["variant"] == v]
        out.append({"arm": v, "assigned": len(sub), "mature": sum(1 for r in sub if r["mature"]), "immature_or_unobserved": sum(1 for r in sub if not r["mature"]),
                    "exposed": sum(1 for r in sub if r["assignment"]["assignment_id"] in ctx.exposure and ctx.exposure[r["assignment"]["assignment_id"]] <= ctx.cuts["as-of"])})
    return out


# =========================================================================================== 07 guardrail, revenue, week 4
def _errors(ctx: Ctx, label: str) -> dict[str, list[datetime]]:
    d: dict[str, list[datetime]] = defaultdict(list)
    for e in ctx.log[label]:
        if e.cls == "analysed" and e.name == "product_error" and e.acct is not None:
            d[e.acct].append(e.at)
    return d


@block("07_guardrail_and_revenue_per_arm__guardrail_by_cutoff")
def b07_guard(ctx: Ctx):
    pf = plan_facts(ctx, V1)
    out = []
    for label in V1_READS:
        c = ctx.cuts[label]
        err = _errors(ctx, label)
        cells = {}
        for v in ("control", "treatment"):
            elig = [r for r in arm_rows(ctx, V1, label) if r["variant"] == v and r["mature"] and r["assigned_at"] + timedelta(hours=24 * pf["g_days"]) <= c]
            hit = sum(1 for r in elig if any(r["assigned_at"] <= t < r["assigned_at"] + timedelta(hours=24 * pf["g_days"]) for t in err.get(r["unit"], ())))
            cells[v] = (hit, len(elig))
        (xc, nc), (xt, nt) = cells["control"], cells["treatment"]
        d, lo, hi, _ = newcombe(xt, nt, xc, nc, pf["z"])
        out.append({"run": label, "cutoff_at": RUNS[label], "eligible_control": nc, "eligible_treatment": nt, "errors_control": xc, "errors_treatment": xt,
                    "error_rate_control": ratio6(xc, nc), "error_rate_treatment": ratio6(xt, nt), "difference_pp": rnd(d * 100, 2), "newcombe_low": rnd(lo, 6),
                    "newcombe_high": rnd(hi, 6), "interval_includes_zero": lo <= 0 <= hi, "verdict": "HARMFUL" if lo > 0 else "OK"})
    return out


def _revenue(ctx: Ctx, label: str) -> dict[str, list[F]]:
    pf = plan_facts(ctx, V1)
    c = ctx.cuts[label]
    rev: dict[str, F] = defaultdict(lambda: F(0))
    for s in ctx.rows["subscriptions"]:
        st = ts(s["starts_at"])
        if s["status"] in ("active", "ended") and pf["rev_from"] <= st < pf["rev_to"] and st <= c:
            rev[s["account_id"]] += F(s["amount_usd"])
    out = {"control": [], "treatment": []}
    for r in arm_rows(ctx, V1, label):
        if r["mature"]:
            out[r["variant"]].append(rev[r["unit"]])
    return out


def _stats(vals: list[F]) -> tuple[int, F, F]:
    n = len(vals)
    total = sum(vals, F(0))
    mean = total / n
    m40 = F(r40(D(mean)))
    var = sum(((x - m40) ** 2 for x in vals), F(0)) / (n - 1)
    return n, m40, var


@block("07_guardrail_and_revenue_per_arm__revenue_by_arm")
def b07_rev(ctx: Ctx):
    out = []
    for label in V1_READS:
        rev = _revenue(ctx, label)
        for v in ("control", "treatment"):
            vals = rev[v]
            n, m40, var = _stats(vals)
            t = ctx.t.get(n - 1)
            total = sum(vals, F(0))
            half = None if t is None else t * sqrt40(D(var / n))
            out.append({"run": label, "cutoff_at": RUNS[label], "arm": v, "units": n, "total_usd": rnd(total, 2), "mean_usd": rnd(m40, 2), "df": n - 1,
                        "t_quantile": None if t is None else rnd(t, 6), "interval_low": None if half is None else rnd(D(m40) - half, 2),
                        "interval_high": None if half is None else rnd(D(m40) + half, 2)})
    return out


@block("07_guardrail_and_revenue_per_arm__revenue_difference")
def b07_revdiff(ctx: Ctx):
    out = []
    for label in V1_READS:
        rev = _revenue(ctx, label)
        nc, mc, vc = _stats(rev["control"])
        nt, mt, vt = _stats(rev["treatment"])
        diff = mt - mc
        a, b = vt / nt, vc / nc
        df = int((a + b) ** 2 / (a * a / (nt - 1) + b * b / (nc - 1)))
        t = ctx.t[df]
        half = t * sqrt40(D(a + b))
        lo, hi = D(diff) - half, D(diff) + half
        out.append({"run": label, "cutoff_at": RUNS[label], "difference_usd": rnd(diff, 2), "welch_df": df, "t_quantile": rnd(t, 6), "interval_low": rnd(lo, 2),
                    "interval_high": rnd(hi, 2), "interval_includes_zero": lo <= 0 <= hi})
    return out


@block("07_guardrail_and_revenue_per_arm__week4_by_arm")
def b07_w4(ctx: Ctx):
    pf = plan_facts(ctx, V1)
    sd = sess_days(ctx)
    asof = ctx.cuts["as-of"]
    cells = {}
    for v in ("control", "treatment"):
        n = x = 0
        for r in arm_rows(ctx, V1, "as-of"):
            if r["variant"] != v or r["signup"] is None:
                continue
            d0, dc = ctx.local(r["unit"], r["signup"]), ctx.local(r["unit"], asof)
            if d0 + timedelta(days=35) <= dc:
                n += 1
                x += 1 if any(28 <= (d - d0).days <= 34 and t < asof for d, t in sd.get(r["unit"], ())) else 0
        cells[v] = (x, n)
    (xc, nc), (xt, nt) = cells["control"], cells["treatment"]
    d, lo, hi, _ = newcombe(xt, nt, xc, nc, pf["z"])
    return [{"mature_control": nc, "mature_treatment": nt, "retained_control": xc, "retained_treatment": xt, "rate_control": ratio6(xc, nc), "rate_treatment": ratio6(xt, nt),
             "difference_pp": rnd(d * 100, 2), "newcombe_low": rnd(lo, 6), "newcombe_high": rnd(hi, 6), "interval_includes_zero": lo <= 0 <= hi}]


# =========================================================================================== 08 identity and late events
@block("08_identity_attribution_and_late_events__attribution_by_event")
def b08_attr(ctx: Ctx):
    anon = [e for e in ctx.log["as-of"] if e.cls == "analysed" and e.user_id is None]

    def row(label: str, sub: list[Ev]) -> dict:
        def linked_at(e: Ev):
            fl = ctx.first_link.get(e.anon)
            return None if fl is None else ts(fl["linked_at"])
        return {"event_name": label, "anonymous_events": len(sub), "attributed_by_link": sum(1 for e in sub if linked_at(e) is not None and e.at >= linked_at(e)),
                "before_the_link_stays_anonymous": sum(1 for e in sub if linked_at(e) is not None and e.at < linked_at(e)),
                "no_link_stays_anonymous": sum(1 for e in sub if linked_at(e) is None), "remain_anonymous": sum(1 for e in sub if e.u is None)}
    return [row(n, [e for e in anon if e.name == n]) for n in sorted({e.name for e in anon})] + [row("ALL", anon)]


@block("08_identity_attribution_and_late_events__links_by_timing")
def b08_timing(ctx: Ctx):
    anon = [e for e in ctx.log["as-of"] if e.cls == "analysed" and e.user_id is None]
    by: dict[str, list[Ev]] = defaultdict(list)
    for e in anon:
        by[e.anon].append(e)
    pats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for aid, fl in ctx.first_link.items():
        la = ts(fl["linked_at"])
        before = sum(1 for e in by.get(aid, ()) if e.at < la)
        after = sum(1 for e in by.get(aid, ()) if e.at >= la)
        pat = ("both: earlier events stay anonymous, later ones are attributed" if before and after else "only before the link: all stay anonymous" if before
               else "only at or after the link: all attributed" if after else "no anonymous event")
        p = pats[pat]
        p[0] += 1
        p[1] += before
        p[2] += after
    return [{"pattern": k, "anonymous_ids": v[0], "events_before_link": v[1], "events_after_link": v[2]} for k, v in sorted(pats.items())]


@block("08_identity_attribution_and_late_events__late_events_by_cutoff")
def b08_late(ctx: Ctx):
    canon = [e for e in ctx.log["as-of"] if e.rn == 1]
    out = []
    for label, c in sorted(ctx.cuts.items(), key=lambda kv: kv[1]):
        late = [e for e in canon if e.at <= c < e.recv]
        out.append({"read": label, "cutoff_at": z(c), "late_events": len(late), "signup": sum(1 for e in late if e.name == "signup"),
                    "activated": sum(1 for e in late if e.name == "activated"), "product_error": sum(1 for e in late if e.name == "product_error"),
                    "other": sum(1 for e in late if e.name in ("visit", "onboarding_step_1", "onboarding_step_2", "onboarding_step_3", "feature_used"))})
    return out


@block("08_identity_attribution_and_late_events__late_activations_by_run")
def b08_lateact(ctx: Ctx):
    out = []
    for label in ("an-001", "an-002", "an-003", "an-004"):
        c = ctx.cuts[label]
        hind = [e for e in ctx.log["as-of"] if e.cls == "analysed" and e.at <= c]
        h_sg: dict[str, datetime] = {}
        h_act: dict[str, list[datetime]] = defaultdict(list)
        for e in hind:
            if e.acct is None:
                continue
            if e.name == "signup" and (e.acct not in h_sg or e.at < h_sg[e.acct]):
                h_sg[e.acct] = e.at
            elif e.name == "activated":
                h_act[e.acct].append(e.at)
        for v in ("control", "treatment"):
            k_m = k_a = h_m = h_a = 0
            for a in ctx.asg[V1]:
                at = ts(a["assigned_at"])
                if a["variant"] != v or at > c:
                    continue
                s = ctx.signup[label].get(a["unit_id"])
                if s is not None and s + H168 <= c:
                    k_m += 1
                    k_a += 1 if ctx.act_in(label, a["unit_id"], max(s, at), s + H168) else 0
                s2 = h_sg.get(a["unit_id"])
                if s2 is not None and s2 + H168 <= c:
                    h_m += 1
                    h_a += 1 if any(max(s2, at) <= t < s2 + H168 for t in h_act.get(a["unit_id"], ())) else 0
            out.append({"run": label, "arm": v, "mature_known": k_m, "activated_known": k_a, "mature_hindsight": h_m, "activated_hindsight": h_a,
                        "activations_changed_by_late_events": h_a - k_a})
    return out


def compute(ctx: Ctx) -> dict[str, list[dict[str, Any]]]:
    return {k: BLOCKS[k](ctx) for k in KEYS}


def normalised(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{k: norm(v) for k, v in r.items()} for r in rows]


if __name__ == "__main__":
    ctx = load()
    res = compute(ctx)
    for k, rows in res.items():
        print(k, len(rows))
