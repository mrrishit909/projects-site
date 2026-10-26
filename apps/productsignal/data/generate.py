#!/usr/bin/env python3
"""ProductSignal synthetic data generator (P06-WORK-03, docs/data-generator.md).

Stdlib only. Deterministic: ``random.Random(seed)`` derives one child stream per purpose (accounts, users, visitors, assign,
outcomes, sessions, events, tracking, subscriptions, exposure, injections), every probability is an integer number of parts
per million and every draw is ``randrange``, instants are ``date`` / ``datetime`` arithmetic on fixed UTC offsets, and nothing
iterates a set of strings, so the same seed gives byte-identical entity files and the same ``dataset_hash`` (checked under
PYTHONHASHSEED 0, 1 and 2). No float is ever written. Nothing is imported from ``domain/``: the rules (activation window,
local-calendar retention, intention to treat, Newcombe, the sample-ratio chi-square) are restated here from docs/contracts.md
(D-01..D-06); ``tests/test_generator.py`` runs the domain over the output and compares.

    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --profile golden-shape-check

Writes ``<entity>.json`` (``{"entity", "dataset_version", "rows"}``) and ``manifest.json`` to ``--out`` (plus ``golden/``, the
hand-derived fixture in the same shape); ``injection-manifest.json`` and ``injection-events.json`` to ``--data-dir`` (default
``data/``) and a copy of the injection manifest to ``--out``.

The world: 600 accounts signing up over 26 weeks (2026-04-06 .. 2026-10-04 UTC, as_of 2026-10-05T00:00:00Z), about 1,800 users,
anonymous visitors and identity links, sessions and events, subscriptions, and one onboarding experiment in two versions
(v1 50/50, v2 a re-plan at 60/40 whose randomiser was configured the wrong way round). Twelve defects are injected (INJ-01..12).
Every outcome is drawn once: nothing is re-drawn or selected on a result; the realised effects are reported in the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
CONTRACT_VERSION = "v1"

START = datetime(2026, 4, 6, tzinfo=UTC)            # Monday of week 1
LAST_DAY = date(2026, 10, 4)                        # Sunday of week 26
AS_OF = datetime(2026, 10, 5, tzinfo=UTC)           # the dataset's as_of and cutoff: no row is received after it
WEEKS = 26
Z_TEXT = "1.959964"
Z = Fraction(Z_TEXT)

# ---- the world's constants (docs/data-generator.md); every probability is parts per million or per hundred ---------------
#: Accounts created per local week (sum 600). Weeks 1-16 are v1's enrolment, 18-25 v2's.
WEEK_QUOTA = (27, 25, 26, 28, 24, 26, 27, 25, 26, 24, 25, 27, 24, 26, 25, 23,
              20, 18, 19, 21, 17, 19, 20, 18, 22, 18)
N_ACCOUNTS = sum(WEEK_QUOTA)
N_INTERNAL = 12                                     # 2 % of 600
N_BOTS = 18                                         # 1 % of about 1,800 users
LINK_SHARE = 70                                     # per hundred users whose signup is linked from an anonymous visit
N_BOUNCE_VISITORS = 3000                            # anonymous visitors who never sign up (the cap, not the world, limits this)
N_GHOST_EVENTS = 30                                 # events of an unknown identity
DELAYED_PERMILLE = 20                               # 2 % received more than 24 h after they happened
DUPLICATE_PERMILLE = 10                             # 1 % re-sent under a new event id
N_INJ05 = 14                                        # activation events re-sent (part of the 1 %)
N_LATE_FUNNEL = 8                                   # INJ-06
N_BACKWARD = 15                                     # INJ-07
N_LATE_RETURNERS, N_TZ_EDGE = 10, 5                 # INJ-12

PLAN_W = (("free", 450), ("team", 400), ("business", 150))
SEG_W = {"free": (("smb", 75), ("mid", 20), ("enterprise", 5)),
         "team": (("smb", 55), ("mid", 35), ("enterprise", 10)),
         "business": (("smb", 10), ("mid", 35), ("enterprise", 55))}
TZ_W = (("America/New_York", 45), ("America/Los_Angeles", 25), ("Europe/London", 30))
#: Fixed UTC offsets in hours. No transition of these three zones falls in 2026-04-06 .. 2026-10-05 (US DST 03-08 / 11-01, UK
#: 03-29 / 10-25); tests/test_generator.py checks them against zoneinfo.
OFFSET_H = {"America/New_York": -4, "America/Los_Angeles": -7, "Europe/London": 1}
DOW_W = ((0, 6), (1, 6), (2, 6), (3, 6), (4, 5), (5, 2), (6, 1))
HOUR_W = ((8, 1), (9, 3), (10, 5), (11, 6), (12, 6), (13, 4), (14, 5), (15, 6), (16, 5), (17, 4), (18, 2), (19, 1))
EXTRA_USERS = {"free": ((0, 50), (1, 30), (2, 20)),
               "team": ((0, 15), (1, 22), (2, 22), (3, 17), (4, 12), (5, 7), (6, 5)),
               "business": ((1, 4), (2, 8), (3, 14), (4, 18), (5, 16), (6, 14), (7, 11), (8, 8), (9, 7))}
JOIN_DELAY = ((3600, 21600, 30), (21600, 172800, 35), (172800, 864000, 25), (864000, 2592000, 10))   # seconds after the creator
FIRST_VISIT = ((60, 3600, 40), (3600, 86400, 30), (86400, 432000, 20), (432000, 1209600, 10))        # seconds before signup
STEP_GAP = ((30, 1800, 55), (1800, 21600, 30), (21600, 86400, 10), (86400, 259200, 5))

# activation: the probability of activating within 7 days (ppm) by plan and segment; treatment adds EFFECT
P_ACT_PLAN = {"free": 240000, "team": 320000, "business": 480000}
P_ACT_SEG = {"smb": 0, "mid": 30000, "enterprise": 60000}
EFFECT = 80000                                      # the true activation effect: +8 percentage points
P_CAP = 950000
P_LATE_ACT = 60000                                  # accounts that did not activate in 7 days but do later (6 %)
DELAY_FAST = ((60, 3600, 30), (3600, 21600, 30), (21600, 86400, 20), (86400, 259200, 15), (259200, 604799, 5))   # business plan
DELAY_SLOW = ((60, 3600, 10), (3600, 21600, 20), (21600, 86400, 25), (86400, 259200, 27), (259200, 604799, 18))
# engagement classes (per mille): the share of hot and warm accounts by plan; organic activators are more engaged
HOT_PM = {"free": 60, "team": 180, "business": 350}
WARM_PM = {"free": 220, "team": 360, "business": 380}
ORG_HOT_PM, ORG_WARM_PM = 120, 100
SCHEDULE = {"hot": ((14, 520000), (35, 300000), (70, 130000)), "warm": ((14, 230000), (35, 120000), (70, 45000)),
            "cold": ((5, 110000), (10, 40000))}
CAP_SESSIONS = {"hot": 30, "warm": 16, "cold": 4}
FEATS_PAID = (("export", 45), ("import", 25), ("share", 20), ("report", 10))
FEATS_FREE = (("import", 50), ("share", 50))
N_FEAT = {"hot": (8, 19), "warm": (1, 7), "cold": (0, 2)}
P_ERR_SESSION = 80000                               # a product_error in 8 % of sessions, whatever the arm
ERR_CODES = (("E-TIMEOUT", 40), ("E-UPLOAD", 25), ("E-PERMISSION", 20), ("E-SYNC", 15))
SUBSCRIBE_PM = {"free": 0, "team": 600, "business": 760}

# ---- the experiment ------------------------------------------------------------------------------------------------------
XV1, XV2 = "xv-001", "xv-002"
V1_START, V1_END = datetime(2026, 4, 6, tzinfo=UTC), datetime(2026, 7, 26, tzinfo=UTC)     # signup instants assigned (half-open)
V2_START, V2_END = datetime(2026, 8, 5, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
V1_PLANNED_END = datetime(2026, 8, 2, tzinfo=UTC)
V2_PLANNED_END = datetime(2026, 10, 4, tzinfo=UTC)
V1_FROZEN = datetime(2026, 4, 5, 12, tzinfo=UTC)
V2_FROZEN = datetime(2026, 8, 2, 12, tzinfo=UTC)
V1_RUN_CUTOFFS = (datetime(2026, 5, 18, tzinfo=UTC), datetime(2026, 6, 15, tzinfo=UTC), datetime(2026, 7, 13, tzinfo=UTC),
                  V1_PLANNED_END)                   # three interim runs and one at planned_end
V2_RUN_CUTOFFS = (V2_PLANNED_END,)
GAP_END = datetime(2026, 4, 8, tzinfo=UTC)          # INJ-10: `activated` was not instrumented for signups before this instant
EARLY_CUTOFF = datetime(2026, 4, 15, tzinfo=UTC)    # INJ-10: the run at which every mature account is in the gap
LATE_CUT = datetime(2026, 10, 2, 12, tzinfo=UTC)    # INJ-06: the earlier cutoff the late events missed
P_EXPOSED_BASE, P_EXPOSED_SPAN = 780000, 140000     # exposure probability 0.78 .. 0.92 (mean 0.85), higher for engaged accounts
WINDOWS = {
    "signup_conversion": {"from": "2026-09-28T00:00:00Z", "to": "2026-10-05T00:00:00Z"},
    "funnel": {"definition_id": "fun-001", "version": 1, "steps": ["visit", "signup", "onboarding_step_1", "activated"],
               "max_gap_hours": 48, "from": "2026-09-28T00:00:00Z", "to": "2026-10-05T00:00:00Z"},
    "activation": {"from": "2026-09-07T00:00:00Z", "to": "2026-10-05T00:00:00Z", "window_days": 7},
    "retention": {"signup_from": "2026-08-24", "signup_to": "2026-08-31"},
    "feature_adoption": {"from": "2026-09-28T00:00:00Z", "to": "2026-10-05T00:00:00Z", "feature": "export",
                         "eligible_plans": ["team", "business"]},
}

ENTITIES = ("accounts", "event_properties", "events", "experiment_versions", "analysis_runs", "assignments", "exposures",
            "identity_links", "metric_observations", "sessions", "subscriptions", "users")
ENTITIES = tuple(sorted(ENTITIES))
#: Choices made after looking at an earlier draft of the same world (D-07 style disclosure; also in README-generator.md).
DISCLOSURES = [
    "v1 is randomised in permuted blocks of four. The first draft used an independent fair coin per account and gave 223 control / 177 treatment (sample ratio p = 0.021: still OK, but unlucky); blocks make 'v1 passes the sample-ratio check' a property of the design rather than of one coin flip. This was chosen after seeing that draw.",
    "product_error is generated per session (8 % of sessions, whatever the arm). The first draft drew a number of errors per account and gave 21.1 % of control and 34.5 % of treatment accounts with an error in the 7-day guardrail window (a difference whose Newcombe interval excluded 0, from noise alone), and an error rate that was unrealistically high. The per-session model was written after seeing that draw; the realised guardrail difference is reported as drawn.",
    "v2's enrolment starts 2026-08-05 (first draft 2026-08-04: 157 accounts) so that v2 has about 150 assigned accounts; the number of bounce visitors was raised from 1,600 to 3,000 so that signup conversion is not implausibly high. Both are count choices.",
    "INJ-06 candidates are signups from 2026-09-28T06:00Z to 2026-10-02T04:00Z (widened from 10-01T12:00Z so that other seeds also have eight): the picked accounts, and so the later random draws, changed; the activation outcomes did not.",
    "Every other draw (activation, retention, revenue, exposure) is made once from the seed; the realised relationships, including the ones that did not come out as 'interesting' as designed, are in designed_relationships.",
]

PURPOSES = ("accounts", "injections", "users", "visitors", "assign", "outcomes", "sessions", "events", "tracking", "subscriptions",
            "exposure", "bots")


# ---------------------------------------------------------------------------------------------------------------------
# small exact helpers
# ---------------------------------------------------------------------------------------------------------------------

def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def pick(r: random.Random, table: tuple) -> Any:
    total = sum(w for _, w in table)
    x = r.randrange(total)
    for v, w in table:
        if x < w:
            return v
        x -= w
    raise AssertionError("unreachable")


def pick_range(r: random.Random, table: tuple) -> int:
    lo, hi, _ = table[0]
    total = sum(w for _, _, w in table)
    x = r.randrange(total)
    for lo, hi, w in table:
        if x < w:
            return lo + r.randrange(hi - lo)
        x -= w
    raise AssertionError("unreachable")


def chance(r: random.Random, ppm: int) -> bool:
    return r.randrange(1_000_000) < ppm


def local_date(t: datetime, tz: str) -> date:
    return (t + timedelta(hours=OFFSET_H[tz])).date()


def from_local(d: date, hour: int, minute: int, second: int, tz: str) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=UTC) - timedelta(hours=OFFSET_H[tz])


def rhu6(x: Fraction) -> str:
    """ROUND_HALF_UP to six places (x >= 0 or negative: sign kept, never '-0.000000')."""
    neg = x < 0
    n = abs(x) * 10 ** 6
    q = (2 * n.numerator + n.denominator) // (2 * n.denominator)
    s = f"{q // 10 ** 6}.{q % 10 ** 6:06d}"
    return "-" + s if neg and q else s


def rhu(x: Fraction, places: int) -> str:
    neg = x < 0
    n = abs(x) * 10 ** places
    q = (2 * n.numerator + n.denominator) // (2 * n.denominator)
    s = f"{q // 10 ** places}.{q % 10 ** places:0{places}d}"
    return "-" + s if neg and q else s


def cents(c: int) -> str:
    return f"{c // 100}.{c % 100:02d}"


def sqrt_frac(x: Fraction) -> Fraction:
    return Fraction(math.isqrt(x.numerator * 10 ** 40 // x.denominator), 10 ** 20)


def wilson(x: int, n: int, z: Fraction = Z) -> tuple[Fraction, Fraction]:
    p = Fraction(x, n)
    z2 = z * z
    centre = p + z2 / (2 * n)
    half = z * sqrt_frac(p * (1 - p) / n + z2 / (4 * n * n))
    den = 1 + z2 / n
    return (centre - half) / den, (centre + half) / den


def newcombe(x1: int, n1: int, x2: int, n2: int, z: Fraction = Z) -> tuple[Fraction, Fraction, Fraction]:
    """Newcombe hybrid score interval of p1 - p2 (group 1 = treatment)."""
    p1, p2 = Fraction(x1, n1), Fraction(x2, n2)
    l1, u1 = wilson(x1, n1, z)
    l2, u2 = wilson(x2, n2, z)
    d = p1 - p2
    return d, d - sqrt_frac((p1 - l1) ** 2 + (u2 - p2) ** 2), d + sqrt_frac((u1 - p1) ** 2 + (p2 - l2) ** 2)


def chi2_p_df1(stat: Fraction) -> Decimal:
    """P(chi-square_1 > stat) = erfc(sqrt(stat / 2)) by the Maclaurin series of erf, 60 digits."""
    with localcontext() as ctx:
        ctx.prec = 80
        if stat == 0:
            return Decimal(1)
        x = (Decimal(stat.numerator) / Decimal(stat.denominator) / 2).sqrt()
        pi = Decimal("3.14159265358979323846264338327950288419716939937510582097494459230781640628620899")
        term, total, n = x, x, 0
        while abs(term) > Decimal("1e-70"):
            n += 1
            term = -term * x * x / n
            total += term / (2 * n + 1)
        return 1 - 2 * total / pi.sqrt()


def dec6(x: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 80
        return str(x.quantize(Decimal("0.000001")))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class GenError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------------------------------
# the world
# ---------------------------------------------------------------------------------------------------------------------

class World:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        master = random.Random(seed)
        self.rs = {p: random.Random(master.getrandbits(64)) for p in PURPOSES}
        self.accounts: list[NS] = []
        self.users: list[NS] = []
        self.visitors: list[NS] = []
        self.events: list[dict[str, Any]] = []
        self.keys: set[tuple] = set()
        self.seq = 0
        self.stats: dict[str, Any] = {}

    # ---- accounts ------------------------------------------------------------------------------------------------------
    def make_accounts(self) -> None:
        r, ri = self.rs["accounts"], self.rs["injections"]
        raw: list[tuple[datetime, str]] = []
        for wk, quota in enumerate(WEEK_QUOTA):
            for _ in range(quota):
                tz = pick(r, TZ_W)
                while True:
                    day = START.date() + timedelta(days=wk * 7 + pick(r, DOW_W))
                    local = datetime(day.year, day.month, day.day, pick(r, HOUR_W), r.randrange(60), r.randrange(60), tzinfo=UTC)
                    utc = local - timedelta(hours=OFFSET_H[tz])
                    if START <= utc < AS_OF:
                        break
                raw.append((utc, tz))
        raw.sort()
        internal = set(ri.sample(range(len(raw)), N_INTERNAL))
        for i, (utc, tz) in enumerate(raw):
            plan = pick(r, PLAN_W)
            a = NS(seq=i, id=f"acc-{i + 1:04d}", plan=plan, segment=pick(r, SEG_W[plan]), signup=utc, tz=tz, internal=i in internal,
                   users=[], xv=None, variant=None, assigned_at=None, sessions=[], inj06=False, inj07=False, inj12=None,
                   gap=False, cls="cold", subs=[], exposure=None)
            a.gap = utc < GAP_END
            if not a.internal:
                if V1_START <= utc < V1_END:
                    a.xv = XV1
                elif V2_START <= utc < V2_END:
                    a.xv = XV2
            self.accounts.append(a)

    def pick_injection_targets(self) -> None:
        ri = self.rs["injections"]
        free = [a for a in self.accounts if not a.internal]
        cand6 = [a for a in free if datetime(2026, 9, 28, 6, tzinfo=UTC) <= a.signup <= datetime(2026, 10, 2, 4, tzinfo=UTC)]
        if len(cand6) < N_LATE_FUNNEL:
            raise GenError("not enough accounts for INJ-06")
        for a in ri.sample(cand6, N_LATE_FUNNEL):
            a.inj06 = True
        cand7 = [a for a in free if datetime(2026, 5, 4, tzinfo=UTC) <= a.signup <= datetime(2026, 9, 14, tzinfo=UTC) and not a.inj06]
        for a in ri.sample(cand7, N_BACKWARD):
            a.inj07 = True

    # ---- users ---------------------------------------------------------------------------------------------------------
    def make_users(self) -> None:
        r, rb = self.rs["users"], self.rs["bots"]
        for a in self.accounts:
            creator = NS(acct=a, signup=a.signup, bot=False, creator=True, linked=a.inj06 or a.inj07 or r.randrange(100) < LINK_SHARE,
                         vis=None, link_at=None, seq=len(self.users))
            self.users.append(creator)
            a.users.append(creator)
            for _ in range(pick(r, EXTRA_USERS[a.plan])):
                t = a.signup + timedelta(seconds=pick_range(r, JOIN_DELAY))
                if t >= AS_OF - timedelta(hours=1):
                    continue
                u = NS(acct=a, signup=t, bot=False, creator=False, linked=r.randrange(100) < LINK_SHARE, vis=None, link_at=None,
                       seq=len(self.users))
                self.users.append(u)
                a.users.append(u)
        pool = [a for a in self.accounts if not a.internal and a.plan != "free"]
        for i, a in enumerate(rb.sample(pool, N_BOTS)):
            t = a.signup + timedelta(seconds=3600 + rb.randrange(3 * 86400))
            b = NS(acct=a, signup=t, bot=True, creator=False, linked=i % 4 == 0, vis=None, link_at=None, seq=len(self.users))
            self.users.append(b)
            a.users.append(b)
        order = sorted(self.users, key=lambda u: (u.signup, u.acct.seq, u.seq))
        for i, u in enumerate(order):
            u.id = f"u-{i + 1:05d}"
        self.users = order
        for a in self.accounts:
            a.users.sort(key=lambda u: (u.signup, u.seq))
            a.real = [u for u in a.users if not u.bot]

    # ---- the experiment: assignments and outcomes -------------------------------------------------------------------
    def assign(self) -> None:
        r = self.rs["assign"]
        v2 = [a for a in self.accounts if a.xv == XV2]
        # v1: permuted blocks of four (two control, two treatment), the usual way to keep arms balanced as accounts arrive.
        v1 = [a for a in self.accounts if a.xv == XV1]
        for i in range(0, len(v1), 4):
            block = ["control", "control", "treatment", "treatment"]
            r.shuffle(block)
            for a, v in zip(v1[i:i + 4], block):
                a.variant = v
        # v2: the randomiser was configured with the arms swapped (3 treatment : 2 control in every block of five) while the plan
        # says control 0.60 / treatment 0.40: a designed sample ratio mismatch, deterministic by construction.
        for i in range(0, len(v2), 5):
            block = ["treatment", "treatment", "treatment", "control", "control"]
            r.shuffle(block)
            for a, v in zip(v2[i:i + 5], block):
                a.variant = v
        for a in self.accounts:
            if a.xv:
                a.assigned_at = a.signup + timedelta(seconds=60 + r.randrange(540))

    def outcomes(self) -> None:
        r = self.rs["outcomes"]
        for a in self.accounts:
            a.ua = r.randrange(1_000_000)
            a.p0 = P_ACT_PLAN[a.plan] + P_ACT_SEG[a.segment]
            p = min(P_CAP, a.p0 + (EFFECT if a.variant == "treatment" else 0))
            a.act7 = a.ua < p
            a.organic = a.ua < a.p0           # would have activated without the treatment: the treatment's extra ones are not engaged
            a.act_delay = None
            if a.act7:
                a.act_delay = pick_range(r, DELAY_FAST if a.plan == "business" else DELAY_SLOW)
            elif chance(r, P_LATE_ACT):
                a.act_delay = 7 * 86400 + 3600 + r.randrange(21 * 86400)
            hot = HOT_PM[a.plan] + (ORG_HOT_PM if a.organic else 0)
            warm = WARM_PM[a.plan] + (ORG_WARM_PM if a.organic else 0)
            x = r.randrange(1000)
            a.cls = "hot" if x < hot else "warm" if x < hot + warm else "cold"
            a.exposed = chance(r, P_EXPOSED_BASE + (1_000_000 - a.ua) * P_EXPOSED_SPAN // 1_000_000)

    # ---- sessions ------------------------------------------------------------------------------------------------------
    def make_sessions(self) -> None:
        r = self.rs["sessions"]
        for a in self.accounts:
            creator = a.real[0]
            a.sessions.append(NS(start=a.signup, user=creator, dur=60 * (3 + r.randrange(30)), device="web"))
            d0 = local_date(a.signup, a.tz)
            sched, cap = SCHEDULE[a.cls], CAP_SESSIONS[a.cls]
            n = 0
            for d in range(1, sched[-1][0] + 1):
                p = next(pp for lim, pp in sched if d <= lim)
                if (d0 + timedelta(days=d)).weekday() >= 5:
                    p = p * 3 // 10
                if not chance(r, p):
                    continue
                t = from_local(d0 + timedelta(days=d), pick(r, HOUR_W), r.randrange(60), r.randrange(60), a.tz)
                if t >= AS_OF:
                    break
                self.add_session(a, t, r)
                n += 1
                if n >= cap:
                    break
        self.engineer_retention()
        for a in self.accounts:
            a.sessions.sort(key=lambda s: (s.start, s.user.seq))

    def add_session(self, a: NS, t: datetime, r: random.Random) -> None:
        elig = [u for u in a.real if u.signup <= t]
        a.sessions.append(NS(start=t, user=elig[r.randrange(len(elig))], dur=60 * (2 + r.randrange(38)),
                             device="web" if r.randrange(100) < 70 else "mobile"))

    def engineer_retention(self) -> None:
        """INJ-12: accounts of a five-week signup cohort that return on day 8-11 but not on day 7 (the rolling definition counts
        them, the exact day does not) and accounts whose day-7 session is on day 7 only on their own calendar (UTC says day 8)."""
        ri, r = self.rs["injections"], self.rs["sessions"]
        lo, hi = date(2026, 7, 27), date(2026, 8, 31)
        cohort = [a for a in self.accounts if not a.internal and lo <= local_date(a.signup, a.tz) < hi]
        late = ri.sample([a for a in cohort], N_LATE_RETURNERS)
        chosen = {a.id for a in late}
        rest = [a for a in cohort if a.id not in chosen and a.tz != "Europe/London"]
        edge = ri.sample(rest, N_TZ_EDGE)
        for kind, group in (("late_returner", late), ("timezone_edge", edge)):
            for a in group:
                d0 = local_date(a.signup, a.tz)
                a.sessions = [s for s in a.sessions if (local_date(s.start, a.tz) - d0).days != 7]
                a.inj12 = kind
                if kind == "late_returner":
                    if not any(8 <= (local_date(s.start, a.tz) - d0).days <= 11 for s in a.sessions):
                        t = from_local(d0 + timedelta(days=8 + r.randrange(4)), 9 + r.randrange(9), r.randrange(60), r.randrange(60), a.tz)
                        self.add_session(a, t, r)
                else:
                    t = from_local(d0 + timedelta(days=7), 21 + r.randrange(2), 5 + r.randrange(50), r.randrange(60), a.tz)
                    self.add_session(a, t, r)

    # ---- events --------------------------------------------------------------------------------------------------------
    def ev(self, name: str, u: NS | None = None, v: NS | None = None, at: datetime | None = None, props: dict[str, str] | None = None,
           raw_user: str | None = None, recv: datetime | None = None, tag: str | None = None) -> dict[str, Any] | None:
        if at is None or at >= AS_OF:
            return None
        props = props or {}
        actor = ("u", u.seq) if u is not None else ("v", v.seq) if v is not None else ("g", raw_user)
        while True:                                  # a distinct (actor, name, instant, properties): only a re-send may repeat one
            key = (actor, name, at, tuple(sorted(props.items())))
            if key not in self.keys:
                break
            at += timedelta(seconds=1)
            if at >= AS_OF:
                return None
        self.keys.add(key)
        self.seq += 1
        e = {"u": u, "v": v, "raw_user": raw_user, "name": name, "at": at, "props": props, "recv": recv, "tag": tag, "seq": self.seq,
             "dup_of": None}
        self.events.append(e)
        return e

    def make_visitor(self) -> NS:
        v = NS(seq=len(self.visitors), first=None, user=None)
        self.visitors.append(v)
        return v

    def make_events(self) -> None:
        r, rv, rb = self.rs["events"], self.rs["visitors"], self.rs["bots"]
        # -- signup, link, visits, onboarding for every real user -------------------------------------------------------
        for u in self.users:
            if u.bot:
                continue
            a = u.acct
            if u.linked:
                u.vis = self.make_visitor()
                u.vis.user = u
                S = u.signup
                if u.creator:
                    if a.inj06:
                        n, offs = 1, [600 + rv.randrange(17400)]
                    else:
                        n = 2 + rv.randrange(2) if a.inj07 else pick(rv, ((1, 60), (2, 30), (3, 10)))
                        first = pick_range(rv, FIRST_VISIT)
                        offs = [first] + sorted((rv.randrange(60, first) for _ in range(n - 1)), reverse=True) if first > 60 else [first]
                else:
                    offs = [60 + rv.randrange(3540)]
                for off in offs:
                    t = max(S - timedelta(seconds=off), START + timedelta(seconds=rv.randrange(1800)))
                    e = self.ev("visit", v=u.vis, at=t, tag="inj07_pre" if a.inj07 and u.creator else None)
                    if e:
                        u.vis.first = t if u.vis.first is None else min(u.vis.first, t)
                u.link_at = S if (a.inj07 and u.creator) or rv.randrange(100) < 85 else S + timedelta(seconds=60 + rv.randrange(1740))
                if (a.inj07 and u.creator) or rv.randrange(100) < 10:        # a logged-out visit after the link: attributed by the link
                    self.ev("visit", v=u.vis, at=u.link_at + timedelta(seconds=3600 + rv.randrange(3 * 86400)),
                            tag="inj07_post" if a.inj07 and u.creator else None)
            self.ev("signup", u=u, v=u.vis, at=u.signup)
            # onboarding steps
            p1 = 850 + (100 if (u.creator and a.act7) else 0) if u.creator else 650
            t = u.signup
            for k, (pp) in enumerate((p1, 700 if u.creator else 450, 550 if u.creator else 300), start=1):
                if a.inj06 and u.creator:
                    break                                   # INJ-06 sets this account's steps below
                if r.randrange(1000) >= pp:
                    break
                t = t + timedelta(seconds=pick_range(r, STEP_GAP))
                self.ev(f"onboarding_step_{k}", u=u, at=t)
        # -- activation (account level, by the creator) -------------------------------------------------------------
        for a in self.accounts:
            if a.act_delay is None or a.gap or a.inj06:
                continue
            e = self.ev("activated", u=a.real[0], at=a.signup + timedelta(seconds=a.act_delay))
        self.make_inj06()
        # -- anonymous visitors who never sign up -----------------------------------------------------------------------
        weights = []
        for wk, q in enumerate(WEEK_QUOTA):
            weights.append((wk, q))
        for _ in range(N_BOUNCE_VISITORS):
            wk = pick(rv, tuple(weights))
            day = START + timedelta(days=wk * 7 + pick(rv, DOW_W))
            t = day + timedelta(seconds=12 * 3600 + rv.randrange(11 * 3600))
            v = self.make_visitor()
            self.ev("visit", v=v, at=t)
            v.first = t
            if rv.randrange(100) < 25:
                self.ev("visit", v=v, at=t + timedelta(seconds=3600 + rv.randrange(6 * 86400)))
        # -- features and errors at the account's own sessions ------------------------------------------------------------
        for a in self.accounts:
            lo, hi = N_FEAT[a.cls]
            n = lo + r.randrange(hi - lo)
            if a.plan == "free":
                n //= 2
            for _ in range(n):
                s = a.sessions[r.randrange(len(a.sessions))]
                self.ev("feature_used", u=s.user, at=s.start + timedelta(seconds=r.randrange(s.dur)),
                        props={"feature": pick(r, FEATS_FREE if a.plan == "free" else FEATS_PAID)})
            for s in a.sessions:
                if chance(r, P_ERR_SESSION):
                    self.ev("product_error", u=s.user, at=s.start + timedelta(seconds=r.randrange(s.dur)),
                            props={"error_code": pick(r, ERR_CODES)})
        self.make_bots(rb)
        self.make_ghosts(r)

    def make_inj06(self) -> None:
        """INJ-06: eight visitors whose `onboarding_step_1` event is received after LATE_CUT (days late). Four of them also have an
        `activated` event received on time: until the late event arrives their chain stops at the signup (strict order)."""
        r = self.rs["injections"]
        accs = [a for a in self.accounts if a.inj06]
        for k, a in enumerate(accs):
            u = a.real[0]
            t1 = a.signup + timedelta(seconds=1200 + r.randrange(4200))
            recv = LATE_CUT + timedelta(seconds=6 * 3600 + r.randrange(52 * 3600))
            e1 = self.ev("onboarding_step_1", u=u, at=t1, recv=recv, tag="inj06_late")
            if e1 is None:
                raise GenError("INJ-06 step event beyond as_of")
            if k < N_LATE_FUNNEL // 2:
                room = int((LATE_CUT - t1).total_seconds()) - 3600           # the activation happens before the earlier cutoff
                e2 = self.ev("activated", u=u, at=t1 + timedelta(seconds=1800 + r.randrange(min(17 * 3600, room - 1800))), tag="inj06_act")
                if e2 is None or e2["at"] >= LATE_CUT:
                    raise GenError("INJ-06 activation not before LATE_CUT")

    def make_bots(self, rb: random.Random) -> None:
        bots = [u for u in self.users if u.bot]
        for b in bots:
            if b.linked:
                b.vis = self.make_visitor()
                b.vis.user = b
                b.link_at = b.signup
                for _ in range(2):
                    self.ev("visit", v=b.vis, at=b.signup - timedelta(seconds=60 + rb.randrange(7200)))
                self.ev("visit", v=b.vis, at=b.signup + timedelta(seconds=600 + rb.randrange(86400)))
            self.ev("signup", u=b, v=b.vis, at=b.signup)
            for k in (1, 2, 3):
                self.ev(f"onboarding_step_{k}", u=b, at=b.signup + timedelta(seconds=60 * k + rb.randrange(3000)))
            if rb.randrange(100) < 40:
                self.ev("activated", u=b, at=b.signup + timedelta(seconds=7200 + rb.randrange(86400)))
            for _ in range(5 + rb.randrange(14)):
                t = b.signup + timedelta(seconds=300 + rb.randrange(10 * 86400))
                if rb.randrange(2):
                    self.ev("feature_used", u=b, at=t, props={"feature": pick(rb, FEATS_PAID)})
                else:
                    self.ev("product_error", u=b, at=t, props={"error_code": pick(rb, ERR_CODES)})
            for _ in range(2 + rb.randrange(3)):
                self.ev("visit", u=b, at=b.signup + timedelta(seconds=rb.randrange(10 * 86400)))
            for _ in range(3):
                t = b.signup + timedelta(seconds=rb.randrange(8 * 86400))
                if t < AS_OF:
                    b.acct.sessions_bot = getattr(b.acct, "sessions_bot", []) + [NS(start=t, user=b, dur=60 * (2 + rb.randrange(20)), device="web")]

    def make_ghosts(self, r: random.Random) -> None:
        """Events whose user_id is no user and has no link (a deleted user, a mis-set SDK id), and a few with no identity at all."""
        for i in range(N_GHOST_EVENTS):
            t = START + timedelta(seconds=r.randrange(int((AS_OF - START).total_seconds()) - 86400))
            name = ("visit", "feature_used", "product_error")[r.randrange(3)]
            props = {} if name == "visit" else {"feature": "export"} if name == "feature_used" else {"error_code": "E-SYNC"}
            self.ev(name, raw_user=f"u-ghost-{i + 1:02d}" if i < N_GHOST_EVENTS - 4 else None, at=t, props=props, tag="ghost")

    # ---- received_at, duplicates, ids -------------------------------------------------------------------------------
    def tracking(self) -> None:
        r, ri = self.rs["tracking"], self.rs["injections"]
        for e in sorted(self.events, key=lambda e: e["seq"]):
            if e["recv"] is not None:
                continue
            x = r.randrange(1000)
            if x < DELAYED_PERMILLE:
                lag = (25 * 3600) + r.randrange(192 * 3600)
            elif x < 70:
                lag = 300 + r.randrange(6900)
            elif x < 200:
                lag = 20 + r.randrange(280)
            else:
                lag = 1 + r.randrange(25)
            e["recv"] = e["at"] + timedelta(seconds=lag)
            if e["recv"] > AS_OF:
                e["recv"] = e["at"] + timedelta(seconds=1 + r.randrange(25))
        base = [e for e in self.events]
        n_dups = (len(base) * DUPLICATE_PERMILLE + 500) // 1000
        acts = [e for e in base if e["name"] == "activated" and e["u"] is not None and not e["u"].bot and e["u"].acct.xv
                and e["recv"] <= AS_OF - timedelta(hours=1) and e["tag"] is None]
        inj05 = ri.sample(acts, N_INJ05)
        chosen = {e["seq"] for e in inj05}
        others = [e for e in base if e["seq"] not in chosen and e["recv"] <= AS_OF - timedelta(hours=1)]
        general = ri.sample(others, n_dups - N_INJ05)
        for e, tag in [(e, "inj05") for e in inj05] + [(e, "dup") for e in general]:
            lag = 2 + r.randrange(88) if r.randrange(10) else 3600 + r.randrange(7200)
            self.events.append({**e, "recv": e["recv"] + timedelta(seconds=lag), "tag": tag, "dup_of": e, "seq": 0})
        for i, e in enumerate(sorted(self.events, key=lambda e: (e["recv"], e["at"], e["seq"], 0 if e["dup_of"] is None else 1))):
            e["id"] = f"ev-{i + 1:06d}"
        self.events.sort(key=lambda e: e["id"])
        for e in self.events:
            if e["dup_of"] is not None:
                e["seq"] = e["dup_of"]["seq"]
        self.stats["duplicates_resent"] = n_dups

    # ---- subscriptions --------------------------------------------------------------------------------------------------
    def subscriptions(self) -> list[dict[str, Any]]:
        r = self.rs["subscriptions"]
        rows = []
        for a in self.accounts:
            if not chance(r, SUBSCRIBE_PM[a.plan] * 1000):
                continue
            start = a.signup + timedelta(seconds=pick_range(r, ((0, 86400, 30), (86400, 7 * 86400, 40), (7 * 86400, 30 * 86400, 20),
                                                                  (30 * 86400, 90 * 86400, 10))))
            if start >= AS_OF - timedelta(hours=1):
                continue
            seat = (1200, 3 + r.randrange(12)) if a.plan == "team" else (3900, 6 + r.randrange(35))
            amount = seat[0] * seat[1]
            age = AS_OF - start
            ends, status = None, "active"
            if age < timedelta(days=14) and r.randrange(100) < 55:
                status = "trial"
            else:
                x = r.randrange(100)
                if x >= 70 and x < 92:
                    e = start + timedelta(seconds=14 * 86400 + r.randrange(106 * 86400))
                    if e < AS_OF:
                        status, ends = "ended", e
                elif x >= 92:
                    status, ends = "refunded", start + timedelta(seconds=86400 + r.randrange(9 * 86400))
                    if ends >= AS_OF:
                        status, ends = "active", None
            rows.append({"account": a, "starts_at": start, "ends_at": ends, "status": status, "amount_c": amount})
            if status == "active" and r.randrange(100) < 6 and AS_OF - start > timedelta(days=45):
                # an upgrade: the first subscription ends the day the second starts
                s2 = start + timedelta(seconds=30 * 86400 + r.randrange(15 * 86400))
                rows[-1]["status"], rows[-1]["ends_at"] = "ended", s2
                rows.append({"account": a, "starts_at": s2, "ends_at": None, "status": "active", "amount_c": amount + 1200 * (1 + r.randrange(4))})
        rows.sort(key=lambda s: (s["starts_at"], s["account"].seq))
        for i, s in enumerate(rows):
            s["id"] = f"sub-{i + 1:03d}"
            s["account"].subs.append(s)
        return rows

    # ---- the rule, restated: facts from the final event list --------------------------------------------------------
    def index(self) -> None:
        self.sig: dict[str, list] = {}
        self.act: dict[str, list] = {}
        self.err: dict[str, list] = {}
        for e in self.events:
            u = e["u"]
            if e["dup_of"] is not None or u is None or u.bot or u.acct.internal:
                continue
            if e["name"] == "signup":
                self.sig.setdefault(u.acct.id, []).append((e["at"], e["recv"]))
            elif e["name"] == "activated":
                self.act.setdefault(u.acct.id, []).append((e["at"], e["recv"]))
            elif e["name"] == "product_error":
                self.err.setdefault(u.acct.id, []).append((e["at"], e["recv"]))

    def signup_at(self, a: NS, cutoff: datetime) -> datetime | None:
        t = [at for at, rc in self.sig.get(a.id, []) if rc <= cutoff]
        return min(t) if t else None

    def activated_7d(self, a: NS, cutoff: datetime) -> bool | None:
        s = self.signup_at(a, cutoff)
        if s is None or s + timedelta(days=7) > cutoff:
            return None
        return any(s <= at < s + timedelta(days=7) and rc <= cutoff for at, rc in self.act.get(a.id, []))

    def analysis(self, xv: str, cutoff: datetime) -> dict[str, Any]:
        out: dict[str, Any] = {}
        revenue_from, revenue_to = self.plan_revenue_window(xv)
        for var in ("control", "treatment"):
            accs = [a for a in self.accounts if a.xv == xv and a.variant == var]
            mature, act, expo, errs, rev = [], 0, 0, 0, []
            for a in accs:
                v = self.activated_7d(a, cutoff)
                if v is None:
                    continue
                mature.append(a)
                act += v
                expo += 1 if a.exposure is not None else 0
                errs += 1 if any(a.assigned_at <= at < a.assigned_at + timedelta(days=7) and rc <= cutoff for at, rc in self.err.get(a.id, [])) else 0
                rev.append(sum(s["amount_c"] for s in a.subs if s["status"] in ("active", "ended") and revenue_from <= s["starts_at"] < revenue_to))
            out[var] = {"assigned": len(accs), "mature": len(mature), "activated": act, "exposed": expo, "errors": errs, "revenue_c": rev,
                        "accounts": mature}
        return out

    def plan_revenue_window(self, xv: str) -> tuple[datetime, datetime]:
        return (START, V1_PLANNED_END) if xv == XV1 else (datetime(2026, 8, 3, tzinfo=UTC), V2_PLANNED_END)

    # ---- tables ---------------------------------------------------------------------------------------------------------
    def build(self) -> dict[str, Any]:
        self.make_accounts()
        self.pick_injection_targets()
        self.make_users()
        self.assign()
        self.outcomes()
        self.make_sessions()
        self.make_events()
        self.tracking()
        subs = self.subscriptions()
        # anonymous ids: in the order of the visitor's first event
        first_at: dict[int, datetime] = {}
        for e in self.events:
            if e["v"] is not None and e["dup_of"] is None:
                k = e["v"].seq
                first_at[k] = e["at"] if k not in first_at else min(first_at[k], e["at"])
        for i, v in enumerate(sorted(self.visitors, key=lambda v: (first_at.get(v.seq, AS_OF), v.seq))):
            v.id = f"a-{i + 1:05d}"
        T: dict[str, list[dict[str, Any]]] = {}
        T["accounts"] = [{"account_id": a.id, "plan": a.plan, "segment": a.segment, "created_at": ts(a.signup), "internal": a.internal,
                          "timezone": a.tz} for a in self.accounts]
        T["users"] = [{"user_id": u.id, "account_id": u.acct.id, "created_at": ts(u.signup), "timezone": u.acct.tz, "bot_flag": u.bot}
                      for u in self.users]
        links = [(u.link_at, u) for u in self.users if u.linked and u.vis is not None]
        links.sort(key=lambda t: (t[0], t[1].id))
        T["identity_links"] = [{"identity_link_id": f"il-{i + 1:05d}", "anonymous_id": u.vis.id, "user_id": u.id, "linked_at": ts(t),
                                "rule_version": "v1"} for i, (t, u) in enumerate(links)]
        sess = []
        for a in self.accounts:
            sess.extend(a.sessions)
            sess.extend(getattr(a, "sessions_bot", []))
        sess.sort(key=lambda s: (s.start, s.user.id))
        T["sessions"] = [{"session_id": f"s-{i + 1:05d}", "user_id": s.user.id, "started_at": ts(s.start),
                          "ended_at": ts(s.start + timedelta(seconds=s.dur)), "device_type": s.device} for i, s in enumerate(sess)]
        ev_rows, pr_rows = [], []
        for e in self.events:
            uid = e["u"].id if e["u"] is not None else e["raw_user"]
            ev_rows.append({"event_id": e["id"], "user_id": uid, "anonymous_id": e["v"].id if e["v"] is not None else None,
                            "event_name": e["name"], "event_at": ts(e["at"]), "received_at": ts(e["recv"])})
            for k in sorted(e["props"]):
                pr_rows.append({"property_id": f"pr-{len(pr_rows) + 1:06d}", "event_id": e["id"], "property_key": k,
                                "property_value": e["props"][k], "value_type": "string"})
        T["events"], T["event_properties"] = ev_rows, pr_rows
        T["subscriptions"] = [{"subscription_id": s["id"], "account_id": s["account"].id, "starts_at": ts(s["starts_at"]),
                               "ends_at": ts(s["ends_at"]) if s["ends_at"] else None, "status": s["status"],
                               "amount_usd": cents(s["amount_c"])} for s in subs]
        T["experiment_versions"] = [
            {"experiment_version_id": XV1, "name": "Onboarding checklist", "unit_type": "account", "primary_metric": "activation_7d",
             "planned_end": ts(V1_PLANNED_END)},
            {"experiment_version_id": XV2, "name": "Onboarding checklist (re-plan)", "unit_type": "account",
             "primary_metric": "activation_7d", "planned_end": ts(V2_PLANNED_END)}]
        asg = sorted((a for a in self.accounts if a.xv), key=lambda a: (a.assigned_at, a.id))
        T["assignments"] = []
        for i, a in enumerate(asg):
            a.assignment_id = f"as-{i + 1:04d}"
            T["assignments"].append({"assignment_id": a.assignment_id, "experiment_version_id": a.xv, "unit_id": a.id,
                                     "variant": a.variant, "assigned_at": ts(a.assigned_at)})
        re = self.rs["exposure"]
        exps = []
        for a in asg:
            if a.exposed:
                a.exposure = a.assigned_at + timedelta(seconds=10 + re.randrange(1190))
                exps.append(a)
        T["exposures"] = [{"exposure_id": f"ex-{i + 1:04d}", "assignment_id": a.assignment_id, "exposed_at": ts(a.exposure),
                           "surface": "onboarding_checklist", "event_id": None} for i, a in enumerate(exps)]
        self.index()
        obs = []
        for a in asg:
            v = self.activated_7d(a, AS_OF)
            if v is None:
                continue
            obs.append({"observation_id": f"ob-{len(obs) + 1:04d}", "assignment_id": a.assignment_id, "metric_name": "activation_7d",
                        "value": "1" if v else "0", "window_end": ts(self.signup_at(a, AS_OF) + timedelta(days=7))})
        T["metric_observations"] = obs
        self.plans = {XV1: self.make_plan(XV1), XV2: self.make_plan(XV2)}
        runs = []
        for xv, cuts in ((XV1, V1_RUN_CUTOFFS), (XV2, V2_RUN_CUTOFFS)):
            for c in cuts:
                runs.append({"analysis_id": f"an-{len(runs) + 1:03d}", "experiment_version_id": xv, "cutoff_at": ts(c),
                             "config_hash": self.plans[xv]["config_hash"], "created_at": ts(c + timedelta(minutes=5))})
        T["analysis_runs"] = runs
        self.T = T
        self.subs = subs
        injections = self.build_injections()
        events = self.build_replay_events()
        designed = self.designed_relationships()
        return {"entities": T, "injections": injections, "events": events, "designed": designed, "parameters": self.parameters(),
                "stats": self.stats, "plans": self.plans}

    def make_plan(self, xv: str) -> dict[str, Any]:
        v1 = xv == XV1
        body = {"experiment_version_id": xv, "primary_metric": "activation_7d", "unit_type": "account",
                "allocation": {"control": "0.500000", "treatment": "0.500000"} if v1 else {"control": "0.600000", "treatment": "0.400000"},
                "planned_end": ts(V1_PLANNED_END if v1 else V2_PLANNED_END), "activation_window_days": 7,
                "guardrail": {"metric": "product_error_rate", "window_days": 7},
                "revenue_window": {"from": ts(START if v1 else datetime(2026, 8, 3, tzinfo=UTC)),
                                   "to": ts(V1_PLANNED_END if v1 else V2_PLANNED_END)},
                "confidence": "0.95", "z": Z_TEXT, "srm": {"p_threshold": "0.001", "min_expected_cell": 5},
                "frozen_at": ts(V1_FROZEN if v1 else V2_FROZEN)}
        return {**body, "config_hash": sha(canonical(body))}

    # ---- injections -------------------------------------------------------------------------------------------------------
    def build_injections(self) -> dict[str, Any]:
        T = self.T
        lst: list[dict[str, Any]] = []
        a1 = {r["analysis_id"]: r for r in T["analysis_runs"]}
        # INJ-01 user-level analysis (replay)
        lst.append({"id": "INJ-01", "test": "P06-TEST-01", "entity": "analysis_requests", "location": "events", "record_ids": [XV1],
                    "description": "An analysis of the account-randomised experiment at the user level (users of one account are not independent).",
                    "detail": {"analysis_unit": "user", "experiment_version_id": XV1}, "handling_kind": "replay_only",
                    "expected_handling": "C08 analyze-experiment refuses an analysis_unit other than account: 422 UNIT_MISMATCH; the request is not a run.",
                    "expected_merges": [], "expected_rejections": [], "replay": ["EV-01"]})
        lst.append({"id": "INJ-02", "test": "P06-TEST-02", "entity": "analysis_requests", "location": "events", "record_ids": [XV1],
                    "description": "An analysis that excludes accounts by a fact that depends on the treatment (exposure).",
                    "detail": {"exclusions": [{"field": "exposed", "values": ["false"]}]}, "handling_kind": "replay_only",
                    "expected_handling": "C08 refuses an exclusion on anything decided after assignment: 422 TREATMENT_DEPENDENT_EXCLUSION; only plan, segment, timezone and internal are allowed.",
                    "expected_merges": [], "expected_rejections": [], "replay": ["EV-02"]})
        lst.append({"id": "INJ-03", "test": "P06-TEST-03", "entity": "analysis_runs", "location": "entity_files+events", "record_ids": ["an-002"],
                    "description": "The second interim run of v1 (cutoff 2026-06-15, before planned_end) presented as the final result and used to ship.",
                    "detail": {"analysis_id": "an-002", "cutoff_at": a1["an-002"]["cutoff_at"], "planned_end": ts(V1_PLANNED_END),
                               "prior_runs": 1, "runs_of_v1": 4},
                    "handling_kind": "replay_only",
                    "expected_handling": "the run is interim (cutoff < planned_end), the count of prior runs is shown, and C10 record-decision ship on it is refused: 409 INTERIM_RUN_CANNOT_SHIP.",
                    "expected_merges": [], "expected_rejections": [], "replay": ["EV-03"]})
        # INJ-04 immature cohort
        win_from, win_to = datetime(2026, 9, 7, tzinfo=UTC), AS_OF
        pop = [a for a in self.accounts if win_from <= a.signup < win_to and not a.internal]
        imm_all = [a for a in pop if a.signup + timedelta(days=7) > AS_OF]
        imm_v2 = [a for a in self.accounts if a.xv == XV2 and a.signup + timedelta(days=7) > AS_OF]
        lst.append({"id": "INJ-04", "test": "P06-TEST-04", "entity": "accounts", "location": "entity_files",
                    "record_ids": [a.id for a in imm_all],
                    "description": "Accounts that signed up less than seven days before the as-of: their activation window is not complete.",
                    "detail": {"activation_window": WINDOWS["activation"], "signups_in_window": len(pop), "immature": len(imm_all),
                               "v2_assigned_immature": len(imm_v2), "v2_assigned_immature_ids": [a.id for a in imm_v2]},
                    "handling_kind": "excluded_and_counted",
                    "expected_handling": "nobody is rejected: the activation metric and the experiment exclude a signup whose signup_at + 7 d is after the cutoff and count it (activation.immature_excluded, experiment.immature_or_unobserved_excluded).",
                    "expected_merges": [], "expected_rejections": [],
                    "expected": {"activation_immature_excluded": len(imm_all), "v2_immature_or_unobserved_excluded": len(imm_v2)}})
        # INJ-05 duplicate activations
        dups = [e for e in self.events if e["tag"] == "inj05"]
        lst.append({"id": "INJ-05", "test": "P06-TEST-05", "entity": "events", "location": "entity_files",
                    "record_ids": [e["id"] for e in dups],
                    "description": f"{len(dups)} `activated` events re-sent under a new event id (same user, name and instant).",
                    "detail": [{"event_id": e["id"], "duplicate_of": e["dup_of"]["id"], "user_id": e["u"].id,
                                "event_at": ts(e["at"]), "received_at": ts(e["recv"])} for e in dups],
                    "handling_kind": "merged",
                    "expected_handling": "ingest accepts every row (the log is immutable); the canonical events of a run drop the re-send (duplicates_dropped) and no account-level figure changes: an account is activated once.",
                    "expected_merges": [], "expected_rejections": [],
                    "expected": {"duplicates_dropped_at_as_of": sum(1 for e in self.events if e["dup_of"] is not None)}})
        # INJ-06 late event
        late = [e for e in self.events if e["tag"] == "inj06_late"]
        late_act = [e for e in self.events if e["tag"] == "inj06_act"]
        lst.append({"id": "INJ-06", "test": "P06-TEST-06", "entity": "events", "location": "entity_files",
                    "record_ids": [e["id"] for e in late],
                    "description": f"{len(late)} `onboarding_step_1` events that happened before {ts(LATE_CUT)} but were received days later; {len(late_act)} of the visitors also have an `activated` event received on time.",
                    "detail": {"funnel_window": WINDOWS["funnel"], "earlier_cutoff": ts(LATE_CUT),
                               "late_events": [{"event_id": e["id"], "user_id": e["u"].id, "account_id": e["u"].acct.id,
                                                "event_at": ts(e["at"]), "received_at": ts(e["recv"])} for e in late],
                               "activated_event_ids": [e["id"] for e in late_act]},
                    "handling_kind": "late_event",
                    "expected_handling": "a run at an earlier cutoff does not see them (the funnel stops at signup for these visitors); a later run does and differs as a disclosed revision; the earlier published result is never rewritten.",
                    "expected_merges": [], "expected_rejections": [],
                    "expected": {"funnel_step_1_units_added": len(late), "funnel_activated_units_added": len(late_act)}})
        # INJ-07 identity backward
        pre = [e for e in self.events if e["tag"] == "inj07_pre"]
        post = [e for e in self.events if e["tag"] == "inj07_post"]
        lst.append({"id": "INJ-07", "test": "P06-TEST-07", "entity": "identity_links", "location": "entity_files",
                    "record_ids": sorted({e["v"].id for e in pre}),
                    "description": f"{N_BACKWARD} visitors with two or three anonymous visits before their identity link and one anonymous visit after it.",
                    "detail": {"before_link_event_ids": [e["id"] for e in pre], "after_link_event_ids": [e["id"] for e in post],
                               "links": [{"anonymous_id": e["v"].id, "user_id": e["v"].user.id, "linked_at": ts(e["v"].user.link_at)} for e in post]},
                    "handling_kind": "accepted_time_aware",
                    "expected_handling": "the link attributes only events with event_at >= linked_at: the earlier visits stay anonymous (never re-attributed backward), the later ones are attributed to the user.",
                    "expected_merges": [], "expected_rejections": [],
                    "expected": {"remain_anonymous": [e["id"] for e in pre], "attributed_by_link": [e["id"] for e in post]}})
        lst.append({"id": "INJ-08", "test": "P06-TEST-08", "entity": "assignments", "location": "entity_files+events", "record_ids": [XV2],
                    "description": "v2 was planned 60/40 (control/treatment) but its randomiser sent 3 of every 5 accounts to treatment: the assignments do not match the allocation and a ship decision is attempted anyway.",
                    "detail": self.srm(XV2), "handling_kind": "replay_only",
                    "expected_handling": "the sample ratio verdict is MISMATCH and is shown before any lift; C10 ship and C10 stop on the run are refused (409 SRM_MISMATCH_BLOCKS_DECISION), inconclusive is recorded.",
                    "expected_merges": [], "expected_rejections": [], "replay": ["EV-08"]})
        lst.append({"id": "INJ-09", "test": "P06-TEST-09", "entity": "analysis_requests", "location": "events", "record_ids": ["an-004"],
                    "description": "A segment result (the best-looking of three) cited as the basis of a decision.",
                    "detail": {"analysis_id": "an-004", "segments_tested": 3, "by": "segment"}, "handling_kind": "replay_only",
                    "expected_handling": "the segment analysis is labelled exploratory with the number of segments tested and the Bonferroni threshold; C10 with a segment basis is refused: 422 SEGMENT_NOT_A_DECISION_BASIS.",
                    "expected_merges": [], "expected_rejections": [], "replay": ["EV-09"]})
        gap = [a for a in self.accounts if a.gap and not a.internal]
        n_c = sum(1 for a in gap if a.xv and a.variant == "control" and a.signup + timedelta(days=7) <= EARLY_CUTOFF)
        n_t = sum(1 for a in gap if a.xv and a.variant == "treatment" and a.signup + timedelta(days=7) <= EARLY_CUTOFF)
        lst.append({"id": "INJ-10", "test": "P06-TEST-10", "entity": "events", "location": "entity_files+events", "record_ids": [a.id for a in gap],
                    "description": "`activated` was not instrumented for signups before 2026-04-08 (both arms alike): an early read of v1 finds zero control conversions.",
                    "detail": {"gap_ends": ts(GAP_END), "early_cutoff": ts(EARLY_CUTOFF), "mature_control": n_c, "mature_treatment": n_t},
                    "handling_kind": "replay_only",
                    "expected_handling": "at the early cutoff the control conversion is 0/n: the relative lift is null (never infinity or 0), the absolute lift is reported, nothing is divided by zero.",
                    "expected_merges": [], "expected_rejections": [], "replay": ["EV-10"],
                    "expected": {"control_conversion": "0.000000", "relative_lift": None, "absolute_lift_pp": "0.00"}})
        unexp = self.unexposed_assignment()
        lst.append({"id": "INJ-11", "test": "P06-TEST-11", "entity": "exposures", "location": "events", "record_ids": [unexp.assignment_id],
                    "description": "An exposure recorded one hour before the assignment it belongs to.",
                    "detail": {"assignment_id": unexp.assignment_id, "assigned_at": ts(unexp.assigned_at),
                               "exposed_at": ts(unexp.assigned_at - timedelta(hours=1))}, "handling_kind": "replay_only",
                    "expected_handling": "C05 record-exposure refuses it: 422 EXPOSURE_BEFORE_ASSIGNMENT; the raw row is kept in rejected_records and no exposure is written.",
                    "expected_merges": [], "expected_rejections": [], "replay": ["EV-11"]})
        late_r = sorted((a for a in self.accounts if a.inj12 == "late_returner"), key=lambda a: a.id)
        edge = sorted((a for a in self.accounts if a.inj12 == "timezone_edge"), key=lambda a: a.id)

        def idx(a: NS) -> list[int]:
            d0 = local_date(a.signup, a.tz)
            return sorted({(local_date(s.start, a.tz) - d0).days for s in a.sessions})
        lst.append({"id": "INJ-12", "test": "P06-TEST-12", "entity": "sessions", "location": "entity_files",
                    "record_ids": [a.id for a in late_r + edge],
                    "description": f"{len(late_r)} accounts that return on day 8-11 but not on day 7 (counted by a rolling `on or after day 7` definition, not by the exact day) and {len(edge)} whose day-7 session is on day 7 only in their own calendar (the UTC date says day 8).",
                    "detail": {"retention_window": {"signup_from": "2026-07-27", "signup_to": "2026-08-31"},
                               "late_returners": [{"account_id": a.id, "timezone": a.tz, "local_day_indices": idx(a)} for a in late_r],
                               "timezone_edge": [{"account_id": a.id, "timezone": a.tz, "local_day_indices": idx(a)} for a in edge]},
                    "handling_kind": "accepted_separate_figures",
                    "expected_handling": "exact day 7 and `on or after day 7` are two figures that are never mixed: for the stated cohort the second exceeds the first by at least the late returners; day indices are on the account's local calendar.",
                    "expected_merges": [], "expected_rejections": [],
                    "expected": {"on_or_after_minus_exact_day7_at_least": len(late_r)}})
        return {"list": lst}

    def unexposed_assignment(self) -> NS:
        c = [a for a in self.accounts if a.xv == XV1 and a.exposure is None and a.signup > datetime(2026, 6, 1, tzinfo=UTC)]
        if not c:
            raise GenError("no unexposed v1 account")
        return c[0]

    def srm(self, xv: str) -> dict[str, Any]:
        plan = self.plans[xv]
        obs = {v: sum(1 for a in self.accounts if a.xv == xv and a.variant == v) for v in ("control", "treatment")}
        n = sum(obs.values())
        alloc = {v: Fraction(plan["allocation"][v]) for v in obs}
        exp = {v: n * alloc[v] for v in obs}
        stat = sum(((obs[v] - exp[v]) ** 2 / exp[v] for v in obs), Fraction(0))
        p = chi2_p_df1(stat)
        verdict = "INSUFFICIENT" if any(e < 5 for e in exp.values()) else "MISMATCH" if p < Decimal("0.001") else "OK"
        return {"experiment_version_id": xv, "observed": obs, "expected": {v: rhu(exp[v], 2) for v in obs}, "statistic": rhu6(stat),
                "p_value": dec6(p), "verdict": verdict}

    # ---- replay-only commands ---------------------------------------------------------------------------------------------
    def build_replay_events(self) -> list[dict[str, Any]]:
        ver = f"ps-{self.seed}-{DATE_TAG}"
        H = {"analyst": {"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "analyst"},
             "experimenter": {"X-Actor-Id": "usr-exp01", "X-Actor-Role": "experimenter"}}

        def step(cmd: str, who: str, key: str, inp: dict[str, Any], status: int, reason: str | None = None, bind: list | None = None,
                 expect: dict | None = None) -> dict[str, Any]:
            s = {"command": cmd, "headers": H[who], "input": {"request_id": f"req-{key}", "dataset_version": ver, "idempotency_key": key,
                                                              "input": inp},
                 "expected_status": status}
            if reason:
                s["expected_reason"] = reason
            if bind:
                s["bind"] = bind
            if expect:
                s["expect"] = expect
            return s

        def ev(eid: str, inj: str, requires: list, steps: list, expected: dict) -> dict[str, Any]:
            return {"event_id": eid, "injection": inj, "requires": requires, "steps": steps, "expected_status": steps[-1]["expected_status"],
                    "expected_reason": steps[-1].get("expected_reason"), "expected": expected}

        rationale = "The lift looks good on the data so far; shipping."
        un = self.unexposed_assignment()
        out = [
            ev("EV-01", "INJ-01", [], [step("analyze-experiment", "analyst", "ev-01-a", {"experiment_version_id": XV1,
                                            "cutoff": ts(V1_PLANNED_END), "analysis_unit": "user"}, 422, "UNIT_MISMATCH")],
               {"runs_written": 0}),
            ev("EV-02", "INJ-02", [], [step("analyze-experiment", "analyst", "ev-02-a", {"experiment_version_id": XV1,
                                            "cutoff": ts(V1_PLANNED_END), "exclusions": [{"field": "exposed", "values": ["false"]}]},
                                            422, "TREATMENT_DEPENDENT_EXCLUSION")], {"runs_written": 0}),
            ev("EV-03", "INJ-03", ["an-002"],
               [step("review-guardrails", "analyst", "ev-03-a", {"analysis_id": "an-002"}, 200),
                step("record-decision", "experimenter", "ev-03-b", {"experiment_version_id": XV1, "analysis_id": "an-002",
                     "review_id": "$review", "decision": "ship", "rationale": rationale}, 409, "INTERIM_RUN_CANNOT_SHIP",
                     bind=[{"into": "review_id", "from_step": 0, "path": "result.review_id"}])],
               {"decisions_written": 0, "refusal_audited": "record-decision-refused"}),
            ev("EV-08", "INJ-08", ["an-005"],
               [step("review-guardrails", "analyst", "ev-08-a", {"analysis_id": "an-005"}, 200),
                step("record-decision", "experimenter", "ev-08-b", {"experiment_version_id": XV2, "analysis_id": "an-005",
                     "review_id": "$review", "decision": "ship", "rationale": rationale}, 409, "SRM_MISMATCH_BLOCKS_DECISION",
                     bind=[{"into": "review_id", "from_step": 0, "path": "result.review_id"}]),
                step("record-decision", "experimenter", "ev-08-c", {"experiment_version_id": XV2, "analysis_id": "an-005",
                     "review_id": "$review", "decision": "stop", "rationale": "Stop: the treatment looks harmful."}, 409,
                     "SRM_MISMATCH_BLOCKS_DECISION", bind=[{"into": "review_id", "from_step": 0, "path": "result.review_id"}]),
                step("record-decision", "experimenter", "ev-08-d", {"experiment_version_id": XV2, "analysis_id": "an-005",
                     "review_id": "$review", "decision": "inconclusive", "rationale": "Sample ratio mismatch: the randomisation cannot be trusted."},
                     200, None, bind=[{"into": "review_id", "from_step": 0, "path": "result.review_id"}])],
               {"decisions_written": 1, "decision": "inconclusive", "refusals_audited": 2}),
            ev("EV-09", "INJ-09", ["an-004"],
               [step("review-guardrails", "analyst", "ev-09-a", {"analysis_id": "an-004"}, 200),
                step("record-decision", "experimenter", "ev-09-b", {"experiment_version_id": XV1, "analysis_id": "an-004",
                     "review_id": "$review", "decision": "ship", "rationale": "The enterprise segment shows the biggest lift.",
                     "basis": "segment"}, 422, "SEGMENT_NOT_A_DECISION_BASIS",
                     bind=[{"into": "review_id", "from_step": 0, "path": "result.review_id"}])],
               {"decisions_written": 0, "segment_analysis": {"by": "segment", "cutoff": ts(V1_PLANNED_END), "segments_tested": 3,
                                                              "label": "exploratory", "decision_basis": False}}),
            ev("EV-10", "INJ-10", [], [step("analyze-experiment", "analyst", "ev-10-a", {"experiment_version_id": XV1,
                                            "cutoff": ts(EARLY_CUTOFF)}, 200)],
               {"relative_lift": None, "absolute_lift_pp": "0.00", "control_conversion": "0.000000", "interim": True,
                "mature_control": self.inj_n("control"), "mature_treatment": self.inj_n("treatment")}),
            ev("EV-11", "INJ-11", [], [step("record-exposure", "experimenter", "ev-11-a", {"assignment_id": un.assignment_id,
                                             "exposure_id": "ex-ev11", "exposed_at": ts(un.assigned_at - timedelta(hours=1)),
                                             "surface": "onboarding_checklist"}, 422, "EXPOSURE_BEFORE_ASSIGNMENT")],
               {"exposures_written": 0, "rejected_records_kept": 1}),
        ]
        return out

    def summary_stats(self) -> dict[str, Any]:
        names: dict[str, int] = {}
        for e in self.events:
            names[e["name"]] = names.get(e["name"], 0) + 1
        canon = [e for e in self.events if e["dup_of"] is None]
        delayed = sum(1 for e in canon if e["recv"] - e["at"] > timedelta(hours=24))
        signups = [u for u in self.users if not u.bot]
        linked = [u for u in signups if u.linked]
        return {"events_by_name": dict(sorted(names.items())), "events_total": len(self.events), "duplicates_resent": len(self.events) - len(canon),
                "delayed_over_24h": delayed, "delayed_share": rhu6(Fraction(delayed, len(canon))),
                "duplicate_share": rhu6(Fraction(len(self.events) - len(canon), len(canon))),
                "real_users": len(signups), "bot_users": len(self.users) - len(signups), "bot_share": rhu6(Fraction(len(self.users) - len(signups), len(self.users))),
                "linked_signups": len(linked), "linked_share": rhu6(Fraction(len(linked), len(signups))),
                "anonymous_visitors": len(self.visitors), "internal_accounts": sum(1 for a in self.accounts if a.internal),
                "v1_assigned": sum(1 for a in self.accounts if a.xv == XV1), "v2_assigned": sum(1 for a in self.accounts if a.xv == XV2),
                "subscribing_accounts": len({s["account"].id for s in self.subs}),
                "subscribing_share": rhu6(Fraction(len({s["account"].id for s in self.subs}), len(self.accounts))),
                "ghost_events": sum(1 for e in self.events if e["tag"] == "ghost")}

    def inj_n(self, var: str) -> int:
        return sum(1 for a in self.accounts if a.gap and a.xv and a.variant == var and a.signup + timedelta(days=7) <= EARLY_CUTOFF)

    # ---- designed relationships ---------------------------------------------------------------------------------------------
    def designed_relationships(self) -> list[dict[str, Any]]:
        out = []
        v1_end, v1_asof = self.analysis(XV1, V1_PLANNED_END), self.analysis(XV1, AS_OF)

        def arm_block(res: dict) -> dict:
            return {v: {"assigned": res[v]["assigned"], "mature": res[v]["mature"], "activated": res[v]["activated"],
                        "conversion": rhu6(Fraction(res[v]["activated"], res[v]["mature"]))} for v in res}

        def lift(res: dict) -> dict:
            c, t = res["control"], res["treatment"]
            d, lo, hi = newcombe(t["activated"], t["mature"], c["activated"], c["mature"])
            ctl = Fraction(c["activated"], c["mature"])
            return {"absolute_lift_pp": rhu(d * 100, 2), "relative_lift": rhu6(d / ctl) if ctl else None,
                    "newcombe_95_low": rhu6(lo), "newcombe_95_high": rhu6(hi), "interval_includes_zero": lo <= 0 <= hi}
        out.append({"id": "DR-01", "name": "the treatment lifts activation",
                    "statement": f"v1's true activation effect is +{EFFECT // 10000} percentage points (every account's 7-day activation probability is raised by 0.08, exposed or not). The realised lift is what one draw gave: it is reported, not selected.",
                    "realised": {"true_effect_pp": "8.00", "at_planned_end": {"cutoff": ts(V1_PLANNED_END), "arms": arm_block(v1_end), **lift(v1_end)},
                                 "at_as_of": {"cutoff": ts(AS_OF), "arms": arm_block(v1_asof), **lift(v1_asof)}}})
        # retention by arm (week 4: any session on local days 28..34; mature when day 35 has begun)
        def week4(xv: str) -> dict:
            res = {}
            for var in ("control", "treatment"):
                mat = hit = 0
                for a in self.accounts:
                    if a.xv != xv or a.variant != var:
                        continue
                    d0 = local_date(a.signup, a.tz)
                    if d0 + timedelta(days=35) > local_date(AS_OF, a.tz):
                        continue
                    mat += 1
                    hit += 1 if any(28 <= (local_date(s.start, a.tz) - d0).days <= 34 for s in a.sessions) else 0
                res[var] = (hit, mat)
            return res
        w4 = week4(XV1)
        d, lo, hi = newcombe(w4["treatment"][0], w4["treatment"][1], w4["control"][0], w4["control"][1])
        out.append({"id": "DR-02", "name": "the treatment does not lift week-4 retention",
                    "statement": "Sessions depend on the account's plan and on whether it would have activated anyway (organic activation), never on the arm: the accounts the treatment activates in addition are not more engaged.",
                    "realised": {"experiment_version_id": XV1, "week4": {v: {"retained": w4[v][0], "mature": w4[v][1],
                                                                          "rate": rhu6(Fraction(*w4[v]))} for v in w4},
                                 "difference_pp": rhu(d * 100, 2), "newcombe_95_low": rhu6(lo), "newcombe_95_high": rhu6(hi),
                                 "interval_includes_zero": lo <= 0 <= hi}})
        # segments: activation among matured signups of the activation window of the whole book
        def rate(accs: list[NS]) -> tuple[int, int]:
            n = k = 0
            for a in accs:
                v = self.activated_7d(a, AS_OF)
                if v is None or a.internal:
                    continue
                n += 1
                k += v
            return k, n
        allbook = {}
        for att in ("plan", "segment"):
            allbook[att] = {}
            for g in sorted({getattr(a, att) for a in self.accounts}):
                accs = [a for a in self.accounts if getattr(a, att) == g and a.variant != "treatment"]       # control-like: no treatment effect
                k, n = rate(accs)
                med = sorted(a.act_delay for a in accs if a.act7 and self.activated_7d(a, AS_OF) is not None and not a.internal)
                allbook[att][g] = {"accounts": n, "activated": k, "rate": rhu6(Fraction(k, n)),
                                   "median_hours_to_activate": rhu(Fraction(med[len(med) // 2], 3600), 2) if med else None}
        out.append({"id": "DR-03", "name": "the business segment activates faster",
                    "statement": "Accounts on the business plan activate more often and sooner (a higher 7-day rate and a shorter median time to activation); the enterprise segment, correlated with the plan, has the highest rate by segment (its median time is not the shortest: noise). Read over accounts not assigned to the treatment (control and unassigned) so the experiment's effect does not mix in.",
                    "realised": allbook})
        g = {v: (v1_asof[v]["errors"], v1_asof[v]["mature"]) for v in ("control", "treatment")}
        d, lo, hi = newcombe(g["treatment"][0], g["treatment"][1], g["control"][0], g["control"][1])
        out.append({"id": "DR-04", "name": "guardrail error rate is equal across variants",
                    "statement": "product_error depends on plan and engagement, not on the arm.",
                    "realised": {"experiment_version_id": XV1, "window_days": 7, "by_variant": {v: {"units_with_error": g[v][0], "eligible_units": g[v][1],
                                 "error_rate": rhu6(Fraction(*g[v]))} for v in g}, "difference_pp": rhu(d * 100, 2),
                                 "newcombe_95_low": rhu6(lo), "newcombe_95_high": rhu6(hi), "interval_includes_zero": lo <= 0 <= hi}})
        revs = {}
        for var in ("control", "treatment"):
            vals = v1_asof[var]["revenue_c"]
            n = len(vals)
            mean = Fraction(sum(vals), n * 100)
            var_ = sum(((Fraction(x, 100) - mean) ** 2 for x in vals), Fraction(0)) / (n - 1)
            revs[var] = (n, mean, var_)
        diff = revs["treatment"][1] - revs["control"][1]
        half = Z * sqrt_frac(revs["treatment"][2] / revs["treatment"][0] + revs["control"][2] / revs["control"][0])
        out.append({"id": "DR-05", "name": "revenue per assigned account is noisy and inconclusive",
                    "statement": "Subscriptions depend on plan and signup date only; the difference between arms is noise and its interval is wide.",
                    "realised": {"experiment_version_id": XV1, "currency": "USD",
                                 "by_variant": {v: {"accounts": revs[v][0], "mean": rhu(revs[v][1], 2), "total": cents(sum(v1_asof[v]["revenue_c"]))} for v in revs},
                                 "difference_of_means": rhu(diff, 2), "approx_95_low": rhu(diff - half, 2), "approx_95_high": rhu(diff + half, 2),
                                 "interval_includes_zero": diff - half <= 0 <= diff + half,
                                 "note": "normal-approximation interval of the difference (the contract pins only per-variant t-intervals)"}})
        out.append({"id": "DR-06", "name": "v2 has a sample ratio mismatch, v1 does not",
                    "statement": "v1 assigns in permuted blocks of four (two control, two treatment), so its counts match the 50/50 plan by construction; v2's randomiser was configured the wrong way round and sends 3 of every 5 accounts to treatment while the plan says 0.40: a mismatch by construction.",
                    "realised": {"v1": self.srm(XV1), "v2": self.srm(XV2)}})
        exp = {v: (sum(1 for a in self.accounts if a.xv == XV1 and a.variant == v and a.exposure is not None),
                   sum(1 for a in self.accounts if a.xv == XV1 and a.variant == v)) for v in ("control", "treatment")}
        out.append({"id": "DR-07", "name": "exposure rate is about 85 %",
                    "statement": "Exposure is recorded for 78 % to 92 % of assigned accounts (higher for accounts that would activate); ITT counts the unexposed too.",
                    "realised": {"experiment_version_id": XV1, "by_variant": {v: {"exposed": exp[v][0], "assigned": exp[v][1],
                                 "rate": rhu6(Fraction(*exp[v]))} for v in exp},
                                 "overall": rhu6(Fraction(sum(e[0] for e in exp.values()), sum(e[1] for e in exp.values())))}})
        return out

    def parameters(self) -> dict[str, Any]:
        return {"accounts": N_ACCOUNTS, "internal_accounts": N_INTERNAL, "bot_users": N_BOTS, "link_share": "0.700000",
                "plans": ["free", "team", "business"], "segments": ["smb", "mid", "enterprise"], "timezones": [t for t, _ in TZ_W],
                "window_start": ts(START), "window_end": ts(AS_OF - timedelta(seconds=1)), "weeks": WEEKS,
                "delayed_share": "0.020000", "duplicate_share": "0.010000", "bounce_visitors": N_BOUNCE_VISITORS,
                "ghost_events": N_GHOST_EVENTS, "true_activation_effect_pp": "8.00", "exposure_mean": "0.850000",
                "v1": {"allocation": "0.500000/0.500000", "enrolled_signups": f"{ts(V1_START)} .. {ts(V1_END)}", "planned_end": ts(V1_PLANNED_END),
                       "frozen_at": ts(V1_FROZEN), "runs": [ts(c) for c in V1_RUN_CUTOFFS]},
                "v2": {"allocation": "0.600000/0.400000", "enrolled_signups": f"{ts(V2_START)} .. {ts(V2_END)}", "planned_end": ts(V2_PLANNED_END),
                       "frozen_at": ts(V2_FROZEN), "runs": [ts(c) for c in V2_RUN_CUTOFFS], "randomiser": "3 treatment : 2 control per block of 5"},
                "outcome_selection": "no outcome is re-drawn, kept or dropped because of its value; the design choices below were made after looking at earlier drafts and are disclosed",
                "disclosures": DISCLOSURES,
                "size_cap_bytes": 5000000, "size_cap_binding": False,
                "offsets_hours": OFFSET_H}


# ---------------------------------------------------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------------------------------------------------

def dataset_hash(entities: dict[str, list[dict]]) -> str:
    h = hashlib.sha256()
    for name in sorted(entities):
        h.update(canonical(entities[name]).encode())
    return h.hexdigest()


def entity_text(name: str, version: str, rows: list[dict]) -> str:
    body = ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return f'{{"entity":{json.dumps(name)},"dataset_version":{json.dumps(version)},"rows":[\n{body}\n]}}\n'


def build(seed: int) -> dict[str, Any]:
    w = World(seed)
    out = w.build()
    out["world"] = w
    return out


def write_golden(out: Path) -> None:
    """The hand-derived fixture in the published shape, for ``?dataset=golden`` (same layout as InvoiceBridge's)."""
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
        "contract_version": CONTRACT_VERSION, "dataset_hash": hashes["sha256"]["inputs.json"], "dataset_version": "golden-v1",
        "generated_at": "2026-10-26T00:00:00Z",
        "generator": {"name": "tests/fixtures/golden (hand-derived, no generator)", "seed": 0, "parameters": {}},
        "designed_relationships": [], "fixture_id": "productsignal-golden-v1", "as_of": inputs["as_of"], "cutoff": inputs["cutoff"],
        "analysis_plan": inputs["analysis_plan"], "metric_windows": inputs["metric_windows"], "expected": "expected.json",
        "row_counts": counts}
    (gdir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def write_all(seed: int, out: Path, data_dir: Path) -> dict[str, Any]:
    built = build(seed)
    ents = built["entities"]
    version = f"ps-{seed}-{DATE_TAG}"
    dhash = dataset_hash(ents)
    out.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    nbytes = 0
    for name in ENTITIES:
        text = entity_text(name, version, ents[name])
        nbytes += len(text.encode())
        (out / f"{name}.json").write_text(text)
    inj_manifest = {"dataset_version": version, "dataset_hash": dhash, "seed": seed, "contract_version": CONTRACT_VERSION,
                    "injections": built["injections"]["list"], "designed_relationships": built["designed"],
                    "events_file": "data/injection-events.json"}
    inj_text = json.dumps(inj_manifest, indent=2, sort_keys=True) + "\n"
    (data_dir / "injection-manifest.json").write_text(inj_text)
    (out / "injection-manifest.json").write_text(inj_text)
    (data_dir / "injection-events.json").write_text(json.dumps({"dataset_version": version, "events": built["events"]}, indent=2,
                                                                  sort_keys=True) + "\n")
    w: World = built["world"]
    stats = dict(built["stats"])
    stats["entity_file_bytes"] = nbytes
    stats.update(w.summary_stats())
    manifest = {
        "dataset_version": version, "dataset_hash": dhash, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contract_version": CONTRACT_VERSION, "window_start": ts(START), "window_end": ts(AS_OF - timedelta(seconds=1)), "as_of": ts(AS_OF),
        "cutoff": ts(AS_OF), "metric_windows": WINDOWS, "analysis_plan": built["plans"][XV1], "analysis_plans": built["plans"],
        "generator": {"name": "generate.py", "seed": seed, "parameters": built["parameters"]},
        "row_counts": {name: len(ents[name]) for name in ENTITIES}, "designed_relationships": built["designed"],
        "injection_manifest": "injection-manifest.json", "stats": stats}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_golden(out)
    return manifest


def shape_check(seed: int) -> int:
    golden = json.loads((APP_ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
    ents = build(seed)["entities"]
    bad = 0
    for name in ENTITIES:
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
    ap.add_argument("--data-dir", type=Path, default=APP_ROOT / "data", help="where injection-manifest.json and injection-events.json go")
    ap.add_argument("--profile", choices=("default", "golden-shape-check"), default="default")
    args = ap.parse_args(argv)
    if args.profile == "golden-shape-check":
        return shape_check(args.seed)
    t0 = time.perf_counter()
    m = write_all(args.seed, args.out, args.data_dir)
    total = sum(p.stat().st_size for p in args.out.rglob("*.json"))
    print(json.dumps({"dataset_version": m["dataset_version"], "dataset_hash": m["dataset_hash"], "row_counts": m["row_counts"],
                      "bytes": total, "elapsed_seconds": round(time.perf_counter() - t0, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
