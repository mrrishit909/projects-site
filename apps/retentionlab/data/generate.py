#!/usr/bin/env python3
"""RetentionLab synthetic data generator (P10-WORK-03, docs/data-generator.md).

Standard library only. The generator simulates the world (accounts, latent state, events) with child ``random.Random`` streams and
integer arithmetic (``Decimal`` for the two transcendental functions), then hands EVERYTHING that is a result to the domain
(``domain/retentionlab``): eligibility, point-in-time features, labels, the split and its purge counts, preprocessing, the four
models, the Platt calibration, every metric and every realised value of a designed relationship. No number in the manifest is typed.
Same seed, same bytes (checked under PYTHONHASHSEED 0/1/2).

    python data/generate.py                              # writes web/public/data and data/injection-events.json
    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --inputs /tmp/full.json      # also the FULL 2,400-account world as one inputs object for data/seed.py (not committed)
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "domain"))

from retentionlab import errors as E  # noqa: E402
from retentionlab.contract import FEATURES, MODELS  # noqa: E402
from retentionlab.fitting import fit_platt, fit_preprocessing, predict_logistic, score_features, train_models  # noqa: E402
from retentionlab.ingest import validate  # noqa: E402
from retentionlab.metrics import average_precision, calibration_bins, psi, set_metrics  # noqa: E402
from retentionlab.numbers import canon, config_hash, p6, pp2, ratio, rnd, sha256_hex  # noqa: E402
from retentionlab.rules import check_calibration_rows, check_capacity, check_feature_request, check_fit_rows, check_threshold  # noqa: E402
from retentionlab.split import retained, split_run  # noqa: E402
from retentionlab.timeutil import days, parse_ts  # noqa: E402
from retentionlab.world import World  # noqa: E402

UTC = timezone.utc
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
VERSION_TAG = "rl"
CONTRACT_VERSION = "v1"
SIZE_CAP_BYTES = 5_000_000

# ---- the calendar (all instants UTC) -----------------------------------------------------------------------------------------
T0 = datetime(2024, 1, 1, tzinfo=UTC)                  # a Monday: week k = [T0 + 7k days, T0 + 7(k+1) days)
AS_OF = datetime(2026, 10, 5, tzinfo=UTC)              # 2026-10-05 is also a Monday: weeks 0 .. 143 are fully before it
K_END = (AS_OF - T0).days // 7
N_ACCOUNTS = 2400
CREATION_MONTHS = [(2024 + (m // 12), m % 12 + 1) for m in range(30)]          # 2024-01 .. 2026-06
CUTOFFS = [datetime(2025 + (m // 12), m % 12 + 1, 1, tzinfo=UTC) for m in range(21)]   # 2025-01-01 .. 2026-09-01
HORIZON, GRACE, OBSERVATION = 90, 14, 90
TRAIN_END, VALIDATION_END, TEST_END = (datetime(2025, 10, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))
RUN_ID = "tr-001"
FEATURE_VERSION, LABEL_VERSION = "fv-1", "lv-1"
MODEL_SEED = 20261026                                   # the random baseline's seed
SCORE_BACKTEST_AT = datetime(2026, 8, 21, 5, 0, tzinfo=UTC)      # the run froze on 2026-08-20; the backtest cutoffs are scored the next morning
SCORE_PRODUCTION_AT = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)     # the cutoff of 2026-09-01 is scored by the monthly production run
RUN_FROZEN_AT = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)

# ---- the world's parameters: chosen BEFORE the first run (see DISCLOSURES for what was changed after looking) -----------------
# segment: weight per mille, mean engagement (milli), usage events per week at engagement 0 (milli), weekly hazard logit at the base
# (milli), monthly-billed share (ppm), monthly price range in USD
SEGMENTS = {"starter": (340, -100, 700, -5400, 900_000, (19, 39)), "smb": (330, 0, 1100, -5400, 750_000, (79, 149)),
            "mid": (220, 100, 1800, -5700, 550_000, (249, 599)), "enterprise": (110, 200, 2600, -6100, 300_000, (1200, 3500))}
REGIONS = {"amer": 340, "emea": 260, "apac": 180, "latam": 120, "anz": 100}
ANNUAL_HAZARD_ADJ = -700            # annual contracts churn less (milli-logit)
HIDDEN_PPM, HIDDEN_ADJ = 140_000, 800            # an unobserved risk factor on 14 % of accounts (+0.8 logit)
ENGAGEMENT_COEF = 2200              # hazard logit milli per 1000 milli of lost engagement
INCIDENT_PPM = 12_000               # weekly chance of an incident (a drop in engagement and a burst of support)
FRUSTRATION_TO_HAZARD = 1000        # logit milli per 1000 of frustration
SUPPORT_HIGH_BASE_PPM, SUPPORT_HIGH_PER_FRUSTRATION = 5_000, 120
SUPPORT_OTHER_PPM = 25_000
DOWNGRADE_Z, DOWNGRADE_PPM = -600, 250_000          # a disengaged monthly payer may downgrade (price x 70 %)
REFUND_PPM = 350_000                # refunds that follow a cancellation (a post-outcome signal: never a feature)
PRICE_CHANGE_AT, PRICE_SEGMENT, PRICE_UPLIFT = datetime(2026, 2, 1, tzinfo=UTC), "starter", 600      # unobserved: starter plan repriced
DRIFT_AT, DRIFT_REGION, DRIFT_KEEP_PPM = datetime(2026, 3, 31, tzinfo=UTC), "apac", 400_000          # instrumentation: 60 % of the logins unrecorded
GROUP_SHARE = (32, 36, 32)          # train / validation / test role of an account, percent, by hash of the account id
# late arrival: ppm of events that arrive >= 1 day late, and the range of the delay in days; all other events arrive within hours
LATE = {"subscription_events": (20_000, (1, 4)), "billing_events": (120_000, (2, 14)), "usage_events": (70_000, (1, 10)),
        "support_events": (100_000, (1, 7))}
CANCEL_LATE_PPM, CANCEL_LATE_DAYS = 90_000, (3, 14)
CANCEL_VERY_LATE_PPM, CANCEL_VERY_LATE_DAYS = 40_000, (15, 60)       # past the 14-day grace: such a cancellation is not churn (D-P10-08)
COHORT_N = 200                      # accounts whose complete records are published (the size cap decides; see DISCLOSURES)
VIOLATORS = {"train_test": (8, 28), "validation_test": (3, 11), "train_validation": (3, 9)}      # (inside the cohort, outside it)
INJ02_EXAMPLES, INJ07_EXAMPLES = 8, 4
MARGINS = {"ap_over_rule": "0.030000", "ap_over_random": "0.050000", "brier_under_rule": "0.002000", "brier_under_random": "0.050000"}
TARGETS = {"calibration_gap_pp": "3.00", "drift_psi": "0.200000", "late_rows_changed_share": "0.030000", "censored_share": "0.150000", "late_features_flipped": 3}
CAP_K = {"sc-001": 5, "sc-002": 10, "sc-003": 20}

SEGMENT_NAMES = tuple(SEGMENTS)
REGION_NAMES = tuple(REGIONS)


# ---- helpers ------------------------------------------------------------------------------------------------------------------
def Z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def stream(seed: int, purpose: str, key: Any = "") -> random.Random:
    """A child stream per purpose and key: independent of every other draw, so a change in one place moves nothing else."""
    return random.Random(int.from_bytes(hashlib.sha256(f"{seed}|{purpose}|{key}".encode()).digest()[:8], "big"))


def chance(r: random.Random, ppm: int) -> bool:
    return r.randrange(1_000_000) < ppm


def wpick(r: random.Random, table: dict[str, int]) -> str:
    x = r.randrange(sum(table.values()))
    for k, w in table.items():
        if x < w:
            return k
        x -= w
    raise AssertionError


_EXP: dict[int, int] = {}


def exp_ppm(x_milli: int) -> int:
    """exp(x / 1000) x 10^6, truncated: ``Decimal.exp`` at 30 digits, identical on every platform."""
    x_milli = max(-15000, min(15000, x_milli))
    v = _EXP.get(x_milli)
    if v is None:
        with localcontext() as ctx:
            ctx.prec = 30
            v = int((Decimal(x_milli) / 1000).exp() * 1_000_000)
        _EXP[x_milli] = v
    return v


def sigmoid_ppm(x_milli: int) -> int:
    return 1_000_000_000_000 // (1_000_000 + exp_ppm(-x_milli))


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def week_start(k: int) -> datetime:
    return T0 + timedelta(days=7 * k)


def calendar_adj(seg: str, k: int) -> int:
    """Known calendar effect on the hazard (milli-logit): the starter plan is repriced from 2026-02-01 (unobserved by any feature)."""
    return PRICE_UPLIFT if seg == PRICE_SEGMENT and week_start(k) >= PRICE_CHANGE_AT else 0


def delay(r: random.Random, late_ppm: int, late_days: tuple[int, int], normal_hours: int = 6) -> timedelta:
    if chance(r, late_ppm):
        return timedelta(days=r.randrange(*late_days), seconds=r.randrange(86400))
    return timedelta(seconds=r.randrange(normal_hours * 3600))


def range_of(pa: datetime) -> str:
    return "train" if pa < TRAIN_END else "validation" if pa < VALIDATION_END else "test" if pa < TEST_END else "outside"


def cutoff_id(aid: int, pa: datetime) -> str:
    return f"co-{aid:04d}-{pa.strftime('%Y%m%d')}"


# ---- the simulation -----------------------------------------------------------------------------------------------------------
def make_accounts(seed: int) -> list[dict[str, Any]]:
    r = stream(seed, "accounts")
    weights = [50 + 2 * m for m in range(30)]
    total, raw = sum(weights), [N_ACCOUNTS * w for w in weights]
    counts = [x // total for x in raw]
    order = sorted(range(30), key=lambda m: (-(raw[m] % total), m))
    for m in order[: N_ACCOUNTS - sum(counts)]:
        counts[m] += 1
    created: list[datetime] = []
    for m, (y, mo) in enumerate(CREATION_MONTHS):
        days_in = (datetime(y + (mo // 12), mo % 12 + 1, 1, tzinfo=UTC) - datetime(y, mo, 1, tzinfo=UTC)).days
        for _ in range(counts[m]):
            created.append(datetime(y, mo, 1 + r.randrange(days_in), r.randrange(24), r.randrange(60), r.randrange(60), tzinfo=UTC))
    created.sort()
    accounts = []
    for i, c in enumerate(created):
        ar = stream(seed, "traits", i + 1)
        seg = wpick(ar, {s: v[0] for s, v in SEGMENTS.items()})
        lo, hi = SEGMENTS[seg][5]
        accounts.append({"account_id": i + 1, "created": c, "segment": seg, "region": wpick(ar, REGIONS),
                         "monthly": chance(ar, SEGMENTS[seg][4]), "price_cents": 100 * ar.randrange(lo, hi + 1),
                         "hidden": chance(ar, HIDDEN_PPM)})
    return accounts


def simulate(seed: int, a: dict[str, Any]) -> None:
    """One account's life, week by week. Adds ``usage``, ``support`` (lists of (event_at, severity)), ``cancel_at``, ``logit`` (week -> hazard
    logit, milli), ``z`` (week -> engagement, milli). The hazard is a function of the latent state; the features see only its footprints."""
    r = stream(seed, "life", a["account_id"])
    seg = a["segment"]
    _w, mu, rate, h0, _m, _p = SEGMENTS[seg]
    created = a["created"]
    kc = (created - T0).days // 7
    mu += (r.randrange(-900, 901) + r.randrange(-900, 901)) // 2       # the account's own long-run engagement level
    a["mu"] = mu
    z = mu + (r.randrange(-300, 301) + r.randrange(-300, 301)) // 2
    f = 0
    usage: list[datetime] = []
    support: list[tuple[datetime, str]] = []
    logit: dict[int, int] = {}
    zs: dict[int, int] = {}
    cancel_at = None
    for k in range(kc, K_END):
        ws = week_start(k)
        if k > kc:
            z += (mu - z) // 10 + (r.randrange(-150, 151) + r.randrange(-150, 151)) // 2
            f = f * 3 // 4
            if chance(r, INCIDENT_PPM):
                z -= r.randrange(800, 1501)
                f += 1000
        tenure = k - kc
        lg = (h0 + (ANNUAL_HAZARD_ADJ if not a["monthly"] else 0) + (300 if tenure < 8 else 100 if tenure < 26 else 0) + (HIDDEN_ADJ if a["hidden"] else 0)
              + (-z * ENGAGEMENT_COEF) // 1000 + f * FRUSTRATION_TO_HAZARD // 1000 + calendar_adj(seg, k))
        logit[k], zs[k] = lg, z
        base = created if k == kc else ws
        end = ws + timedelta(days=7)
        stop = end
        if chance(r, sigmoid_ppm(lg)):
            cancel_at = base + timedelta(seconds=r.randrange(1, max(2, int((end - base).total_seconds()))))
            stop = cancel_at
        p = min(999_999, (rate * exp_ppm(z * 9 // 10) // 1_000_000) * 1000 // 14)
        for _ in range(14):
            if r.randrange(1_000_000) < p:
                t = ws + timedelta(seconds=r.randrange(7 * 86400))
                if t < base or t >= stop:
                    continue
                if a["region"] == DRIFT_REGION and t >= DRIFT_AT and not chance(r, DRIFT_KEEP_PPM):
                    continue
                usage.append(t)
        if chance(r, SUPPORT_HIGH_BASE_PPM + f * SUPPORT_HIGH_PER_FRUSTRATION):
            t = ws + timedelta(seconds=r.randrange(7 * 86400))
            if base <= t < stop:
                support.append((t, "high"))
        if chance(r, SUPPORT_OTHER_PPM):
            t = ws + timedelta(seconds=r.randrange(7 * 86400))
            sev = "low" if r.randrange(10) < 7 else "medium"
            if base <= t < stop:
                support.append((t, sev))
        if cancel_at is not None:
            break
    a.update(usage=sorted(usage), support=sorted(support), cancel_at=cancel_at, logit=logit, z=zs, kc=kc)


def events_of(seed: int, a: dict[str, Any]) -> dict[str, list[tuple]]:
    """Subscription, billing, usage and support events of one account, with their ``available_at`` (declared late-arrival shares).
    An event that has not arrived by ``as_of`` is not part of the world."""
    r = stream(seed, "events", a["account_id"])
    cancel_at, created = a["cancel_at"], a["created"]
    sub: list[tuple] = [(created, created + delay(r, *LATE["subscription_events"]), "start")]
    bill: list[tuple] = []
    step = 30 if a["monthly"] else 365
    annual_amount = a["price_cents"] * 12 * 85 // 100
    downgraded, n = False, 0
    t = created
    while True:
        if cancel_at is not None and t >= cancel_at:
            break
        if t >= AS_OF:
            break
        if n > 0:
            sub.append((t, t + delay(r, *LATE["subscription_events"]), "renew"))
        k = (t - T0).days // 7
        if a["monthly"] and not downgraded and a["z"].get(k, 0) < DOWNGRADE_Z and chance(r, DOWNGRADE_PPM):
            downgraded = True
        cents = (a["price_cents"] * (70 if downgraded else 100) // 100) if a["monthly"] else annual_amount
        bt = t + timedelta(seconds=r.randrange(6 * 3600))
        bill.append((bt, bt + delay(r, *LATE["billing_events"]), money(cents)))
        n += 1
        t = created + timedelta(days=step * n)
    if cancel_at is not None:
        d = delay(r, 0, (0, 1))
        if chance(r, CANCEL_VERY_LATE_PPM):
            d = timedelta(days=r.randrange(*CANCEL_VERY_LATE_DAYS), seconds=r.randrange(86400))
        elif chance(r, CANCEL_LATE_PPM):
            d = timedelta(days=r.randrange(*CANCEL_LATE_DAYS), seconds=r.randrange(86400))
        sub.append((cancel_at, cancel_at + d, "cancel"))
        if a["monthly"] and chance(r, REFUND_PPM):
            rt = cancel_at + timedelta(days=1 + r.randrange(5), seconds=r.randrange(86400))
            bill.append((rt, rt + delay(r, 0, (0, 1)), money(-(a["price_cents"] * (30 + r.randrange(71)) // 100))))
    usage = [(t, t + delay(r, *LATE["usage_events"])) for t in a["usage"]]
    support = [(t, t + delay(r, *LATE["support_events"]), sev) for t, sev in a["support"]]
    keep = lambda rows: [x for x in rows if x[0] < AS_OF and x[1] <= AS_OF]      # noqa: E731
    return {"subscription_events": keep(sub), "billing_events": keep(bill), "usage_events": keep(usage), "support_events": keep(support)}


# ---- the population: roles, violators, injected examples ------------------------------------------------------------------------
REGISTRY_FIELDS = [   # name, source entity, window, post_outcome, latent, id_derived, lineage.  The first four are the only usable features.
    ("usage_events_30d", "usage_events", 30, False, False, False, "events"), ("days_since_last_usage", "usage_events", 90, False, False, False, "events"),
    ("high_severity_support_90d", "support_events", 90, False, False, False, "events"), ("billing_total_90d", "billing_events", 90, False, False, False, "events"),
    ("cancellation_reason", "subscription_events", None, True, False, False, "events"), ("cancellation_survey_score", "support_events", None, True, False, False, "events"),
    ("refund_after_cancel", "billing_events", None, True, False, False, "events"),
    ("latent_churn_propensity", "generator_manifest", None, False, True, False, "generator_manifest"),
    ("generator_seed_bucket", "generator_manifest", None, False, True, False, "generator_manifest"),
    ("account_id", "accounts", None, False, False, True, "identifier"), ("account_id_hash", "accounts", None, False, False, True, "identifier"),
    ("creation_sequence", "accounts", None, False, False, True, "identifier")]


def registry_rows() -> list[dict[str, Any]]:
    return [{"feature_name": n, "feature_version": FEATURE_VERSION, "source_entity": s, "window_days": w, "post_outcome": po, "latent": lt, "id_derived": idd,
             "lineage": ln} for n, s, w, po, lt, idd, ln in REGISTRY_FIELDS]


def cutoff_dates(a: dict[str, Any]) -> list[datetime]:
    """The cutoffs at which an account has a row: it exists, has not cancelled, and the cutoff lies in the range of its role (or after the test)."""
    out = []
    for pa in CUTOFFS:
        if a["created"] >= pa or (a["cancel_at"] is not None and a["cancel_at"] < pa):
            continue
        if range_of(pa) == "outside" or range_of(pa) in a["groups"]:
            out.append(pa)
    return out


def pick_violators(seed: int, accounts: list[dict[str, Any]], cohort: set[int]) -> dict[str, list[int]]:
    """P10-TEST-03: accounts that are given a row in a second split range, against the account-level role assignment."""
    r = stream(seed, "violators")
    taken: set[int] = set()
    out: dict[str, list[int]] = {}
    for kind, primary, extra, when in (("train_test", "train", "test", datetime(2026, 2, 1, tzinfo=UTC)),
                                       ("validation_test", "validation", "test", datetime(2026, 2, 1, tzinfo=UTC)),
                                       ("train_validation", "train", "validation", datetime(2025, 10, 1, tzinfo=UTC))):
        cands = [a for a in accounts if a["primary"] == primary and a["account_id"] not in taken and a["created"] < when - days(OBSERVATION)
                 and (a["cancel_at"] is None or a["cancel_at"] >= when)]
        inside = [a for a in cands if a["account_id"] in cohort]
        outside = [a for a in cands if a["account_id"] not in cohort]
        r.shuffle(inside)
        r.shuffle(outside)
        n_in, n_out = VIOLATORS[kind]
        chosen = inside[:n_in] + outside[:n_out]
        for a in chosen:
            a["groups"].add(extra)
            taken.add(a["account_id"])
        out[kind] = sorted(a["account_id"] for a in chosen)
    return out


def pick_inj02(seed: int, accounts: list[dict[str, Any]], cohort: set[int]) -> list[dict[str, Any]]:
    """P10-TEST-02 (any range): a usage event that happened inside the observation window but reached the store AFTER the cutoff, at a cutoff where
    the account looks silent (no usage in 30 days, no high-severity case): counted, the account would look active; excluded, it is flagged."""
    r = stream(seed, "inj02")
    cands: list[tuple[int, datetime]] = []
    for a in accounts:
        for pa in cutoff_dates(a):
            if a["created"] >= pa - days(OBSERVATION):
                continue
            usage = any(pa - days(30) <= t < pa and av < pa for t, av in a["events"]["usage_events"])
            high = any(sev == "high" and pa - days(90) <= t < pa and av < pa for t, av, sev in a["events"]["support_events"])
            if not usage and not high:
                cands.append((a["account_id"], pa))
    by_id: dict[int, tuple[int, datetime]] = {}
    for aid, pa in cands:
        by_id.setdefault(aid, (aid, pa))
    inside = [c for aid, c in sorted(by_id.items()) if aid in cohort]
    outside = [c for aid, c in sorted(by_id.items()) if aid not in cohort]
    r.shuffle(inside)
    r.shuffle(outside)
    chosen = (inside + outside)[:INJ02_EXAMPLES]
    out = []
    for aid, pa in sorted(chosen):
        a = accounts[aid - 1]
        t = pa - timedelta(days=1 + r.randrange(3), seconds=r.randrange(86400))
        av = pa + timedelta(days=1 + r.randrange(4), seconds=r.randrange(86400))
        a["events"]["usage_events"].append((t, av))
        out.append({"account_id": aid, "prediction_at": pa, "event_at": t, "available_at": av, "in_cohort": aid in cohort})
    return out


def propensity_ppm(a: dict[str, Any], pa: datetime) -> int:
    """The latent churn propensity of an account at a cutoff (parts per million): 1 - prod over 13 weeks of (1 - weekly hazard), the hazard
    held at the account's latest state, plus the known calendar effect. A stylised 90-day probability; it never leaves the manifest."""
    kp = ((pa - timedelta(seconds=1)) - T0).days // 7
    lg = a["logit"].get(kp, a["logit"][max(a["logit"])])
    base = lg - calendar_adj(a["segment"], kp)
    surv = 1_000_000
    for j in range(1, 14):
        surv = surv * (1_000_000 - sigmoid_ppm(base + calendar_adj(a["segment"], kp + j))) // 1_000_000
    return 1_000_000 - surv


def build_population(seed: int) -> dict[str, Any]:
    accounts = make_accounts(seed)
    for a in accounts:
        simulate(seed, a)
        a["events"] = events_of(seed, a)
        u = stream(seed, "group", a["account_id"]).randrange(100)
        a["primary"] = "train" if u < GROUP_SHARE[0] else "validation" if u < GROUP_SHARE[0] + GROUP_SHARE[1] else "test"
        a["groups"] = {a["primary"]}
    cohort = sorted(stream(seed, "cohort").sample(range(1, N_ACCOUNTS + 1), COHORT_N))
    cset = set(cohort)
    violators = pick_violators(seed, accounts, cset)
    inj02 = pick_inj02(seed, accounts, cset)
    return {"accounts": accounts, "cohort": cohort, "violators": violators, "inj02": inj02}


def entity_rows(seed: int, pop: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The full world as entity rows (dicts in the shape of the golden inputs), ids assigned in event order."""
    accounts = pop["accounts"]
    ents: dict[str, list[dict[str, Any]]] = {
        "accounts": [{"account_id": a["account_id"], "created_at": Z(a["created"]), "segment": a["segment"], "region": a["region"], "synthetic": True} for a in accounts]}
    names = stream(seed, "usage-names")
    table = {"login": 55, "report": 20, "export": 10, "invite": 8, "api_call": 7}
    spec = (("subscription_events", "subscription_event_id", "se", "event_type"), ("billing_events", "billing_event_id", "bil", "amount"),
            ("usage_events", "usage_event_id", "ue", "event_name"), ("support_events", "support_event_id", "sup", "severity"))
    for entity, idcol, prefix, extra in spec:
        flat = []
        for a in accounts:
            for ev in a["events"][entity]:
                flat.append((ev[0], a["account_id"], ev[1], ev[2] if len(ev) > 2 else ""))
        flat.sort()
        rows = []
        for n, (t, aid, av, x) in enumerate(flat, 1):
            rows.append({idcol: f"{prefix}-{n:06d}", "account_id": aid, extra: wpick(names, table) if entity == "usage_events" else x, "event_at": Z(t), "available_at": Z(av)})
        ents[entity] = rows
    cut = []
    for a in accounts:
        for pa in cutoff_dates(a):
            cut.append({"cutoff_id": cutoff_id(a["account_id"], pa), "account_id": a["account_id"], "prediction_at": Z(pa), "horizon_end": Z(pa + days(HORIZON)),
                        "observation_start": Z(pa - days(OBSERVATION))})
    cut.sort(key=lambda c: (c["prediction_at"], c["account_id"]))
    ents["prediction_cutoffs"] = cut
    ents["feature_registry"] = registry_rows()
    return ents


def base_inputs(ents: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"contract_version": 1, "as_of": Z(AS_OF), "label_version": {"label_version_id": LABEL_VERSION, "horizon_days": HORIZON, "grace_days": GRACE},
            "feature_version_spec": {"feature_version": FEATURE_VERSION, "observation_days": OBSERVATION}, **ents}


# ---- the domain's turn: features, labels, split, fitting, scoring --------------------------------------------------------------
def with_predictions(world: World, extra: dict[str, list[dict[str, Any]]], model: str | None) -> World:
    """A view of the analysed world with the given extra entities; predictions and publications filtered to ONE model (the domain keys a
    prediction by (run, cutoff), so a metric is always computed per model, as the API does)."""
    import copy
    w = copy.copy(world)
    acc = dict(world.acc)
    for k, v in extra.items():
        acc[k] = [x for x in v if model is None or x.get("model_name", model) == model] if k in ("predictions", "scoring_publications") else v
    w.acc = acc
    w.runs = {r["training_run_id"]: r for r in acc.get("training_runs", [])}
    w.scenarios = {s["scenario_id"]: s for s in acc.get("intervention_scenarios", [])}
    w.preds = {(p["training_run_id"], p["cutoff_id"]): p for p in acc.get("predictions", [])}
    return w


def feature_and_label_rows(rows: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fr, lb = [], []
    for cid in sorted(rows):
        a = rows[cid]
        if not a["eligible"]:
            continue
        fr.append({"feature_row_id": f"fr-{cid}", "cutoff_id": cid, "feature_version": FEATURE_VERSION, "features_json": a["features"],
                   "max_available_at": a["max_available_at"]})
        lb.append({"label_id": f"lb-{cid}", "cutoff_id": cid, "churned": a["churned"], "label_end": a["label_end"], "mature": a["mature"]})
    return fr, lb


def fit_run(world: World, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """C03..C06 as the API runs them, through the domain's own code: split with purge, preprocessing on retained training rows, three
    models, Platt on retained validation rows. Returns the run (with its config and hash) and the split."""
    run = {"training_run_id": RUN_ID, "train_end": Z(TRAIN_END), "validation_end": Z(VALIDATION_END), "test_end": Z(TEST_END)}
    split_rows, counts = split_run(world, run)
    train_ids = sorted(c for c in retained(split_rows, "train") if rows[c]["eligible"] and rows[c]["mature"])
    val_ids = sorted(c for c in retained(split_rows, "validation") if rows[c]["eligible"] and rows[c]["mature"])
    pre = fit_preprocessing([rows[c]["features"] for c in train_ids])
    pre["fit_rows_sha256"] = sha256_hex(canon(train_ids))
    models = train_models(pre, [(rows[c]["features"], bool(rows[c]["churned"])) for c in train_ids], MODEL_SEED)
    config: dict[str, Any] = {"feature_version": FEATURE_VERSION, "label_version": LABEL_VERSION, "seed": DEFAULT_SEED, "split": "chronological",
                              "preprocessing": pre, "models": models}
    cal = fit_platt([score_features(config, "logistic_regression", c, rows[c]["features"], calibrated=False) for c in val_ids],
                    [bool(rows[c]["churned"]) for c in val_ids])
    cal["fit_rows"] = len(val_ids)
    cal["fit_rows_sha256"] = sha256_hex(canon(val_ids))
    config["calibration"] = cal
    run.update(config=config, config_hash=config_hash(config))
    return {"run": run, "split_rows": split_rows, "split_counts": counts, "train_ids": train_ids, "validation_ids": val_ids}


def score_all(rows: dict[str, dict[str, Any]], run: dict[str, Any]) -> list[dict[str, Any]]:
    """Every eligible cutoff scored by the four models from the frozen run (the logistic one is Platt-scaled)."""
    out = []
    for cid in sorted(rows):
        a = rows[cid]
        if not a["eligible"]:
            continue
        pa = parse_ts(a["prediction_at"])
        at = SCORE_PRODUCTION_AT if pa == CUTOFFS[-1] else SCORE_BACKTEST_AT
        for model in MODELS:
            p = score_features(run["config"], model, cid, a["features"])
            out.append({"prediction_id": f"pr-{cid}" if model == "logistic_regression" else f"pr-{model}-{cid}", "training_run_id": RUN_ID, "cutoff_id": cid,
                        "model_name": model, "probability": p, "scored_at": Z(at), "config_hash": run["config_hash"], "feature_version": FEATURE_VERSION,
                        "label_version": LABEL_VERSION})
    return out


def publication_rows(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for pa in CUTOFFS:
        if not any(a["eligible"] and a["prediction_at"] == Z(pa) for a in rows.values()):
            continue
        at = SCORE_PRODUCTION_AT if pa == CUTOFFS[-1] else SCORE_BACKTEST_AT
        for model in MODELS:
            out.append({"publication_id": f"sp-{RUN_ID}-{model}-{pa.strftime('%Y%m%d')}-1", "training_run_id": RUN_ID, "model_name": model, "prediction_at": Z(pa),
                        "published_at": Z(at + timedelta(hours=1)), "status": "completed"})
    return out


def union_items(world_m: World, rows: dict[str, dict[str, Any]], ranges: tuple[str, ...] = ("test",), extra: Any = None) -> list[dict[str, Any]]:
    """The evaluation population of one model over the cutoffs of the given ranges: mature, eligible, retained-by-range rows with a prediction."""
    items = []
    for cid, a in rows.items():
        if not (a["eligible"] and a["mature"]) or range_of(parse_ts(a["prediction_at"])) not in ranges:
            continue
        pr = world_m.preds.get((RUN_ID, cid))
        if pr is None or (extra is not None and not extra(a)):
            continue
        items.append({"p": Fraction(pr["probability"]), "pstr": pr["probability"], "y": bool(a["churned"]), "account_id": a["account_id"], "cutoff_id": cid})
    return items


def ap_brier(items: list[dict[str, Any]]) -> dict[str, Any]:
    from retentionlab.metrics import rank_key
    items = sorted(items, key=rank_key)
    pos = sum(1 for it in items if it["y"])
    ap, _ = average_precision(items, pos)
    sq = sum(((it["p"] - (1 if it["y"] else 0)) ** 2 for it in items), Fraction(0))
    return {"n": len(items), "positives": pos, "prevalence": p6(ratio(pos, len(items))), "average_precision": p6(ap), "brier_score": p6(sq / len(items) if items else None)}


# ---- designed relationships: every realised value comes from the domain's own functions ------------------------------------------
def margin(a: str | None, b: str | None) -> str | None:
    return None if a is None or b is None else rnd(Fraction(a) - Fraction(b), 6)


def dr_models(world: World, rows: dict[str, dict[str, Any]], ext: dict[str, Any], pop: dict[str, Any]) -> dict[str, Any]:
    """DR-01: the logistic model against the rule and the random baseline on the TEST range (the four cutoffs as one evaluation population)."""
    res: dict[str, Any] = {}
    for m in MODELS:
        res[m] = ap_brier(union_items(with_predictions(world, ext, m), rows))
    accounts = pop["accounts"]
    oracle = [{**it, "p": Fraction(propensity_ppm(accounts[it["account_id"] - 1], parse_ts(rows[it["cutoff_id"]]["prediction_at"])), 1_000_000)}
              for it in union_items(with_predictions(world, ext, "logistic_regression"), rows)]
    res["latent_propensity_reference"] = ap_brier(oracle)
    lr, rule, rnd_ = res["logistic_regression"], res["business_rule"], res["random_baseline"]
    stated = MARGINS
    res["margins"] = {"ap_over_rule": margin(lr["average_precision"], rule["average_precision"]), "ap_over_random": margin(lr["average_precision"], rnd_["average_precision"]),
                      "brier_under_rule": margin(rule["brier_score"], lr["brier_score"]), "brier_under_random": margin(rnd_["brier_score"], lr["brier_score"])}
    res["stated_margins"] = stated
    res["met"] = {k: Fraction(res["margins"][k]) >= Fraction(stated[k]) for k in stated}
    # D-09 (R10-14): the prevalence constant is the honest Brier reference. The stated margins stay as declared against the rule and the random
    # baseline; the margin over the constant is reported beside them, and the random baseline's Brier margin is named uninformative.
    prev = res["prevalence_baseline"]
    res["reference_margins"] = {"brier_under_prevalence_constant": margin(prev["brier_score"], lr["brier_score"]),
                                "ap_over_prevalence_constant": margin(lr["average_precision"], prev["average_precision"])}
    res["uninformative_margin"] = {"key": "brier_under_random", "random_brier": rnd_["brier_score"], "prevalence_constant_brier": prev["brier_score"],
                                   "why": "a uniform random score has a Brier near one third on a population that is 12 % positive, so any model that is not absurd clears a margin over it; "
                                          "the honest reference is the prevalence constant"}
    return res


def gap_block(items: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(items)
    mean = sum((it["p"] for it in items), Fraction(0)) / n if n else None
    obs = Fraction(sum(1 for it in items if it["y"]), n) if n else None
    return {"n": n, "positives": sum(1 for it in items if it["y"]), "mean_predicted": p6(mean), "observed_rate": p6(obs),
            "gap_pp": None if n == 0 else pp2(mean - obs)}


def dr_calibration(world: World, rows: dict[str, dict[str, Any]], ext: dict[str, Any], pop: dict[str, Any], fit: dict[str, Any]) -> dict[str, Any]:
    """DR-02: calibration on the test range, overall and by segment and region (gap = mean predicted - observed, percentage points)."""
    accounts = pop["accounts"]
    wl = with_predictions(world, ext, "logistic_regression")
    items = union_items(wl, rows)
    cfg = fit["run"]["config"]
    uncal = [{**it, "p": Fraction(predict_logistic(cfg["preprocessing"], next(m for m in cfg["models"] if m["name"] == "logistic_regression")["coefficients"],
                                                   rows[it["cutoff_id"]]["features"]))} for it in items]
    by_seg = {s: gap_block([it for it in items if accounts[it["account_id"] - 1]["segment"] == s]) for s in SEGMENT_NAMES}
    by_reg = {s: gap_block([it for it in items if accounts[it["account_id"] - 1]["region"] == s]) for s in REGION_NAMES}
    others = [abs(Fraction(v["gap_pp"])) for k, v in by_seg.items() if k != PRICE_SEGMENT]
    worst_region = max(by_reg, key=lambda k: abs(Fraction(by_reg[k]["gap_pp"])))
    b_cal, b_unc = ap_brier(items), ap_brier(uncal)
    platt = {"brier_uncalibrated": b_unc["brier_score"], "brier_calibrated": b_cal["brier_score"], "gap_pp_uncalibrated": gap_block(uncal)["gap_pp"], "gap_pp_calibrated": gap_block(items)["gap_pp"],
             "worse_on_test": Fraction(b_cal["brier_score"]) > Fraction(b_unc["brier_score"]) and abs(Fraction(gap_block(items)["gap_pp"])) > abs(Fraction(gap_block(uncal)["gap_pp"])),
             "fit_rows": cfg["calibration"]["fit_rows"],
             "why": "the mapping has two parameters and was fitted on the retained validation rows, all of which come from the first validation cutoff (the label-window purge removes the later ones); "
                    "a small fit set from one month does not transfer to the next four"}
    return {"platt_effect": platt, "overall": gap_block(items), "by_segment": by_seg, "by_region": by_reg, "reliability_calibrated": calibration_bins(items),
            "reliability_uncalibrated": calibration_bins(uncal), "uncalibrated_overall": gap_block(uncal),
            "segment_with_gap": PRICE_SEGMENT, "target_gap_pp": TARGETS["calibration_gap_pp"],
            "met": Fraction(by_seg[PRICE_SEGMENT]["gap_pp"]) <= -Fraction(TARGETS["calibration_gap_pp"]),
            "largest_other_segment_abs_gap_pp": rnd(max(others), 2),
            "largest_region_gap": {"region": worst_region, "gap_pp": by_reg[worst_region]["gap_pp"], "designed": False,
                                   "note": "the largest regional calibration gap is a one-draw realisation of this seed's world, not a designed relationship: the instrumentation change "
                                           "was designed to move the apac usage distribution (DR-03), and no effect on its calibration was designed"}}


def drift_counts(rs: list[dict[str, Any]], drift: dict[str, Any]) -> list[int]:
    from retentionlab.metrics import in_bin
    return [sum(1 for r in rs if in_bin(r["features"][drift["feature"]], b)) for b in drift["bins"]]


def dr_drift(world: World, rows: dict[str, dict[str, Any]], ext: dict[str, Any], pop: dict[str, Any]) -> dict[str, Any]:
    """DR-03: usage_events_30d against the 2026-02-01 cohort, per cutoff: all accounts (the domain's own drift block) and the drifting region
    against the others (PSI of the declared bins, floor 0.0001, diagnostic threshold 0.2)."""
    from retentionlab.contract import DEFAULT_DRIFT
    accounts = pop["accounts"]
    ref_at = Z(VALIDATION_END)
    drift = {**DEFAULT_DRIFT, "reference_prediction_at": ref_at}
    wl = with_predictions(world, ext, "logistic_regression")
    by_at: dict[str, list[dict[str, Any]]] = {}
    for r in rows.values():
        if r["eligible"]:
            by_at.setdefault(r["prediction_at"], []).append(r)
    out_rows = []
    for pa in CUTOFFS:
        key = Z(pa)
        cur = by_at.get(key, [])
        ref = by_at[ref_at]
        entry: dict[str, Any] = {"prediction_at": key, "range": range_of(pa), "eligible": len(cur)}
        whole = set_metrics(wl, RUN_ID, key, None, drift)["population_drift"]
        entry["all_accounts"] = None if whole is None else {"psi": whole["psi"], "exceeds_threshold": whole["exceeds_threshold"], "reference_rows": whole["reference_rows"], "current_rows": whole["current_rows"]}
        for label, test in ((DRIFT_REGION, lambda a: a["region"] == DRIFT_REGION), ("other_regions", lambda a: a["region"] != DRIFT_REGION)):
            rr = [r for r in ref if test(accounts[r["account_id"] - 1])]
            cc = [r for r in cur if test(accounts[r["account_id"] - 1])]
            res = psi(drift_counts(rr, drift), drift_counts(cc, drift), [b["label"] for b in drift["bins"]], drift["floor"])
            entry[label] = None if res is None else {"psi": rnd(Fraction(res[0]), 6), "exceeds_threshold": res[0] > Decimal(drift["threshold"]), "reference_rows": len(rr),
                                                     "current_rows": len(cc), "mean_usage_events_30d": rnd(Fraction(sum(r["features"]["usage_events_30d"] for r in cc), len(cc)), 2) if cc else None,
                                                     "floored_bins": sum(1 for b in res[1] if b["floored"])}
        out_rows.append(entry)
    after = [e for e in out_rows if parse_ts(e["prediction_at"]) >= datetime(2026, 5, 1, tzinfo=UTC)]
    before = [e for e in out_rows if datetime(2026, 2, 1, tzinfo=UTC) <= parse_ts(e["prediction_at"]) <= datetime(2026, 3, 1, tzinfo=UTC)]
    met = all(e[DRIFT_REGION] and e[DRIFT_REGION]["exceeds_threshold"] for e in after) and \
        all(e["other_regions"] and not e["other_regions"]["exceeds_threshold"] for e in out_rows if e["range"] != "train" and parse_ts(e["prediction_at"]) >= VALIDATION_END)
    return {"feature": drift["feature"], "reference_prediction_at": ref_at, "region": DRIFT_REGION, "change_at": Z(DRIFT_AT), "bins": drift["bins"], "floor": drift["floor"],
            "threshold": drift["threshold"], "by_cutoff": out_rows, "target_psi": TARGETS["drift_psi"], "met": met,
            "before_change_psi": [e[DRIFT_REGION]["psi"] for e in before if e[DRIFT_REGION]], "after_change_psi": [e[DRIFT_REGION]["psi"] for e in after if e[DRIFT_REGION]]}


def dr_late(seed: int, world: World, rows: dict[str, dict[str, Any]], ents: dict[str, list[dict[str, Any]]], data: dict[str, Any]) -> dict[str, Any]:
    """DR-04: what ignoring ``available_at`` would change. The same domain rebuilds the test-range rows from a copy of the events in which every
    event is treated as available when it happened; rows whose features (or label) differ are the ones the late arrivals protect."""
    cf_ents = {k: ents[k] for k in ents}
    for e in ("subscription_events", "billing_events", "usage_events", "support_events"):
        cf_ents[e] = [{**ev, "available_at": ev["event_at"]} for ev in ents[e]]
    cf_data = {**data, **{e: cf_ents[e] for e in ("subscription_events", "billing_events", "usage_events", "support_events")}}
    ing = validate(cf_data)
    cw = World(cf_data, ing.accepted)
    flips = {f: 0 for f in FEATURES}
    rows_changed = rule_flips = label_flips = test_rows = rows_with_late = 0
    for cid, a in rows.items():
        if not (a["eligible"] and range_of(parse_ts(a["prediction_at"])) == "test"):
            continue
        test_rows += 1
        b = cw.analyse(cid)
        late = sum(a["arrived_late"].values())
        rows_with_late += 1 if late else 0
        diff = [f for f in FEATURES if a["features"][f] != b["features"][f]]
        for f in diff:
            flips[f] += 1
        rows_changed += 1 if diff else 0
        flag = lambda r: r["features"]["usage_events_30d"] == 0 or r["features"]["high_severity_support_90d"] >= 1      # noqa: E731
        rule_flips += 1 if flag(a) != flag(b) else 0
        label_flips += 1 if (a["mature"] and a["churned"] != b["churned"]) else 0
    declared = {e: {"late_ppm": LATE[e][0], "late_days": list(LATE[e][1])} for e in LATE}
    realised = {}
    for e in LATE:
        n = len(ents[e])
        late_n = sum(1 for ev in ents[e] if parse_ts(ev["available_at"]) - parse_ts(ev["event_at"]) >= timedelta(days=1))
        realised[e] = {"events": n, "late_one_day_or_more": late_n, "share": p6(ratio(late_n, n))}
    cancels = [ev for ev in ents["subscription_events"] if ev["subscription_event_id"] and parse_ts(ev["available_at"]) - parse_ts(ev["event_at"]) >= timedelta(days=GRACE + 1)]
    return {"test_rows": test_rows, "test_rows_with_a_late_event": rows_with_late, "test_rows_features_change_if_ignored": rows_changed,
            "share_of_test_rows_changed": p6(ratio(rows_changed, test_rows)), "target_share": TARGETS["late_rows_changed_share"],
            "features_flipped": flips, "rule_flag_flips": rule_flips, "mature_test_labels_flipped": label_flips,
            "declared": declared, "realised": realised, "subscription_events_arriving_after_the_grace": len(cancels),
            "met": Fraction(rows_changed, test_rows) >= Fraction(TARGETS["late_rows_changed_share"]) and sum(1 for v in flips.values() if v > 0) >= TARGETS["late_features_flipped"]}


def dr_censored(rows: dict[str, dict[str, Any]], ents: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """DR-05: the censored tail: eligible rows whose label window is not closed at as_of, by cutoff, and what labelling them non-churn would
    claim: only the cancellations seen so far count, so the rate collapses towards zero the nearer the cutoff is to as_of."""
    cancels: dict[int, list[Any]] = {}
    for ev in ents["subscription_events"]:
        if ev["event_type"] == "cancel":
            cancels.setdefault(ev["account_id"], []).append(parse_ts(ev["event_at"]))
    by: dict[str, dict[str, int]] = {}
    for a in rows.values():
        if not a["eligible"]:
            continue
        d = by.setdefault(a["prediction_at"], {"eligible": 0, "censored": 0, "mature": 0, "churned": 0, "cancelled_so_far": 0})
        d["eligible"] += 1
        d["censored" if not a["mature"] else "mature"] += 1
        d["churned"] += 1 if a["churned"] else 0
        if not a["mature"]:
            pa = parse_ts(a["prediction_at"])
            d["cancelled_so_far"] += 1 if any(pa <= t < pa + days(HORIZON) for t in cancels.get(a["account_id"], [])) else 0
    tot = {k: sum(d[k] for d in by.values()) for k in ("eligible", "censored", "mature", "churned")}
    last3 = [Z(c) for c in CUTOFFS[-3:]]
    return {"eligible_rows": tot["eligible"], "censored_rows": tot["censored"], "censored_share": p6(ratio(tot["censored"], tot["eligible"])),
            "target_share": TARGETS["censored_share"], "immature_cutoffs": last3, "mature_churn_rate": p6(ratio(tot["churned"], tot["mature"])),
            "by_cutoff": {k: {**v, "censored_share": p6(ratio(v["censored"], v["eligible"]))} for k, v in sorted(by.items())},
            "churn_rate_if_censored_were_non_churn": {k: p6(ratio(by[k]["cancelled_so_far"], by[k]["eligible"])) for k in last3},
            "met": Fraction(tot["censored"], tot["eligible"]) >= Fraction(TARGETS["censored_share"])}


# ---- the published cohort: complete records of a sample of accounts, so that the domain can rebuild every number from them --------
SCENARIOS = [{"scenario_id": "sc-001", "capacity": CAP_K["sc-001"], "contact_cost": "8.00", "assumed_effect": "0.300000", "margin_value": "200.00"},
             {"scenario_id": "sc-002", "capacity": CAP_K["sc-002"], "contact_cost": "8.00", "assumed_effect": "0.200000", "margin_value": "200.00"},
             {"scenario_id": "sc-003", "capacity": CAP_K["sc-003"], "contact_cost": "8.00", "assumed_effect": "0.100000", "margin_value": "200.00"}]   # narrow and optimistic / central / wide and pessimistic
PUBLISH_FROM = TRAIN_END                      # predictions and publications of the cohort start with the validation range
EVENT_ENTITIES = ("subscription_events", "billing_events", "usage_events", "support_events")


def assemble_cohort(seed: int, pop: dict[str, Any], ents: dict[str, list[dict[str, Any]]], rows: dict[str, dict[str, Any]], fit: dict[str, Any],
                    preds: list[dict[str, Any]], world: World) -> dict[str, Any]:
    cs = set(pop["cohort"])
    ce: dict[str, list[dict[str, Any]]] = {"accounts": [x for x in ents["accounts"] if x["account_id"] in cs]}
    for e in EVENT_ENTITIES + ("prediction_cutoffs",):
        ce[e] = [x for x in ents[e] if x["account_id"] in cs]
    ce["feature_registry"] = ents["feature_registry"]
    cids = {c["cutoff_id"] for c in ce["prediction_cutoffs"]}
    ce["feature_rows"], good = feature_and_label_rows({c: rows[c] for c in cids})
    r = stream(seed, "inj07")
    immature = sorted(c for c in cids if rows[c]["eligible"] and not rows[c]["mature"])
    r.shuffle(immature)
    bad = sorted(immature[:INJ07_EXAMPLES])
    ce["labels"] = good + [{"label_id": f"lb-inj-{c}", "cutoff_id": c, "churned": False, "label_end": rows[c]["label_end"], "mature": False} for c in bad]
    ce["training_runs"] = [fit["run"]]
    ce["split_assignments"] = [{"assignment_id": f"sa-{RUN_ID}-{x['cutoff_id']}", "training_run_id": RUN_ID, "cutoff_id": x["cutoff_id"], "split": x["split"],
                                "status": x["status"], "drop_reason": x["drop_reason"]} for x in fit["split_rows"] if x["cutoff_id"] in cids]
    ce["predictions"] = [p for p in preds if p["cutoff_id"] in cids and parse_ts(rows[p["cutoff_id"]]["prediction_at"]) >= PUBLISH_FROM]
    pubs = []
    for pa in CUTOFFS:
        if pa < PUBLISH_FROM or not any(rows[c]["eligible"] and rows[c]["prediction_at"] == Z(pa) for c in cids):
            continue
        at = SCORE_PRODUCTION_AT if pa == CUTOFFS[-1] else SCORE_BACKTEST_AT
        for model in MODELS:
            pubs.append({"publication_id": f"sp-{RUN_ID}-{model}-{pa.strftime('%Y%m%d')}-1", "training_run_id": RUN_ID, "model_name": model, "prediction_at": Z(pa),
                         "published_at": Z(at + timedelta(hours=1)), "status": "completed"})
    ce["scoring_publications"] = pubs
    ce["intervention_scenarios"] = [dict(s) for s in SCENARIOS]
    ce["outreach_events"] = []
    data_c = base_inputs(ce)
    ing = validate(data_c)
    wc = World(data_c, ing.accepted)
    for c in sorted(cids):                                                  # the cohort's own rebuild equals the population's rows (events are per account)
        a, b = wc.analyse(c), rows[c]
        if {k: a[k] for k in ("eligible", "features", "max_available_at", "churned", "mature", "arrived_late")} != {k: b[k] for k in ("eligible", "features", "max_available_at", "churned", "mature", "arrived_late")}:
            raise AssertionError(f"cohort rebuild differs from the population at {c}")
    queue_at = Z(CUTOFFS[-1])
    wl = with_predictions(wc, {"intervention_scenarios": ce["intervention_scenarios"], "predictions": ce["predictions"], "training_runs": ce["training_runs"]}, "logistic_regression")
    economics: dict[str, Any] = {}
    for s in ce["intervention_scenarios"]:
        sm = set_metrics(wl, RUN_ID, queue_at, s["scenario_id"], None)
        q = sm["outreach_queue"]
        economics[s["scenario_id"]] = {"capacity": s["capacity"], "population": q["population"], "contact_budget": sm["economics"]["contact_budget"],
                                       "expected_value": sm["economics"]["expected_value"], "label": sm["economics"]["label"], "treatment_effect_estimate": sm["economics"]["treatment_effect_estimate"],
                                       "assumption_based": sm["economics"]["assumption_based"], "status": q["status"], "account_ids": q["account_ids"]}
        for rank, aid in enumerate(q["account_ids"], 1):
            ce["outreach_events"].append({"outreach_event_id": f"oe-{s['scenario_id']}-{rank:04d}", "account_id": aid, "scenario_id": s["scenario_id"],
                                          "action": "propose_contact", "status": "draft", "training_run_id": RUN_ID, "prediction_at": queue_at, "queue_rank": rank})
    data_c = base_inputs(ce)
    return {"ents": ce, "data": data_c, "bad_label_cutoffs": bad, "economics": economics, "queue_at": queue_at, "world": wc}


def compact_set(m: dict[str, Any]) -> dict[str, Any]:
    pop = m["population"]
    return {"cutoff_rows": pop["cutoff_rows"], "eligible": pop["eligible"], "ineligible": pop["ineligible"], "mature": pop["mature"], "censored": pop["censored"],
            "scored": pop["scored"], "evaluated": pop["evaluated"], "churned": pop["churned"], "churn_rate": m["churn_rate"]["value"],
            "average_precision": m["average_precision"]["value"], "prevalence": m["average_precision"]["prevalence"], "positives": m["average_precision"]["positives"],
            "brier_score": m["brier_score"]["value"], "late_events": m["late_events"], "missingness_overall": m["feature_missingness"]["overall"]["value"]}


def cohort_claims(data_c: dict[str, Any]) -> dict[str, Any]:
    """What the domain says about the published cohort, per model, through its own ``evaluate`` (the tests repeat this from the files)."""
    from retentionlab.pipeline import evaluate
    out: dict[str, Any] = {}
    for m in MODELS:
        dm = {**data_c, "predictions": [p for p in data_c["predictions"] if p["model_name"] == m],
              "scoring_publications": [p for p in data_c["scoring_publications"] if p["model_name"] == m],
              "scope": {"training_run_id": RUN_ID, "sets": [{"prediction_at": Z(pa), "scenario_id": None} for pa in CUTOFFS]}}
        ev = evaluate(dm)
        out[m] = {"ingest": ev["ingest"]["counts"], "rejected_records": ev["ingest"]["rejected_records"], "consistency": ev["consistency"],
                  "split_counts": ev["split"][RUN_ID]["counts"], "freshness": ev["freshness"],
                  "publications": {p["prediction_at"]: [p["eligible"], p["scored"], p["status"]] for p in ev["scoring_publications"]},
                  "cutoff_sets": {k: compact_set(v) for k, v in ev["cutoff_sets"].items()}}
    return out


def test_cohort_table(rows: dict[str, dict[str, Any]], preds: list[dict[str, Any]], pop: dict[str, Any], fit: dict[str, Any]) -> dict[str, Any]:
    """The whole test range (all 2,400-account population rows that are eligible, mature and scored) as one compact table, for the browser."""
    cfg = fit["run"]["config"]
    lr = next(m for m in cfg["models"] if m["name"] == "logistic_regression")
    by = {m: {p["cutoff_id"]: p["probability"] for p in preds if p["model_name"] == m} for m in MODELS}
    test_cutoffs = [Z(pa) for pa in CUTOFFS if range_of(pa) == "test"]
    cols = ["account_id", "cutoff_index", "segment", "region", *FEATURES, "churned", "p_random_baseline", "p_business_rule", "p_logistic_uncalibrated", "p_logistic_calibrated", "p_prevalence_baseline"]
    table = []
    for cid in sorted(rows, key=lambda c: (rows[c]["prediction_at"], rows[c]["account_id"])):
        a = rows[cid]
        if not (a["eligible"] and a["mature"] and a["prediction_at"] in test_cutoffs):
            continue
        acc = pop["accounts"][a["account_id"] - 1]
        f = a["features"]
        table.append([a["account_id"], test_cutoffs.index(a["prediction_at"]), acc["segment"], acc["region"], *[f[n] for n in FEATURES], 1 if a["churned"] else 0,
                      by["random_baseline"][cid], by["business_rule"][cid], predict_logistic(cfg["preprocessing"], lr["coefficients"], f), by["logistic_regression"][cid], by["prevalence_baseline"][cid]])
    return {"cutoffs": test_cutoffs, "columns": cols, "rows": table}


def economics_full_world(world: World, ext: dict[str, Any]) -> dict[str, Any]:
    """D-09 (R10-04): the three scenarios' economics over the WHOLE 2,400-account world at the production cutoff, by the domain's own function. The
    published cohort's figures (97 scored accounts) are a different population; both are shown wherever economics appear. Hypothetical."""
    at = Z(CUTOFFS[-1])
    wl = with_predictions(world, {**ext, "intervention_scenarios": [dict(x) for x in SCENARIOS]}, "logistic_regression")
    out: dict[str, Any] = {}
    for sc in SCENARIOS:
        m = set_metrics(wl, RUN_ID, at, sc["scenario_id"], None)
        e = m["economics"]
        out[sc["scenario_id"]] = {"capacity": sc["capacity"], "scored_accounts": m["outreach_queue"]["population"], "contact_budget": e["contact_budget"],
                                  "expected_value": e["expected_value"], "label": e["label"], "assumption_based": e["assumption_based"],
                                  "assumptions": e["assumptions"], "treatment_effect_estimate": e["treatment_effect_estimate"]}
    return {"prediction_at": at, "population": "all 2,400 accounts as built by the domain: the eligible accounts of the cutoff that carry a prediction",
            "scenarios": out}


def aggregates(world: World, rows: dict[str, dict[str, Any]], ext: dict[str, Any]) -> list[dict[str, Any]]:
    wm = {m: with_predictions(world, ext, m) for m in MODELS}
    out = []
    for pa in CUTOFFS:
        key = Z(pa)
        entry: dict[str, Any] = {"prediction_at": key, "range": range_of(pa), "models": {}}
        for m in MODELS:
            sm = set_metrics(wm[m], RUN_ID, key, None, None)
            if m == "logistic_regression":
                entry.update(population=sm["population"], churn_rate=sm["churn_rate"]["value"], late_events=sm["late_events"],
                             missingness={"overall": sm["feature_missingness"]["overall"]["value"], **{f: v["value"] for f, v in sm["feature_missingness"]["by_feature"].items()}})
            ranking = sm["ranking"]
            entry["models"][m] = {"n": sm["average_precision"]["n"], "positives": sm["average_precision"]["positives"], "prevalence": sm["average_precision"]["prevalence"],
                                  "average_precision": sm["average_precision"]["value"], "brier_score": sm["brier_score"]["value"],
                                  "mean_probability": p6(sum((Fraction(x["probability"]) for x in ranking), Fraction(0)) / len(ranking)) if ranking else None}
        out.append(entry)
    return out


# ---- injected defects: what is in the data, how the domain handles it ---------------------------------------------------------------
def refusal(registry: dict[str, dict[str, Any]], fields: list[str]) -> dict[str, Any] | None:
    try:
        check_feature_request(registry, fields)
        return None
    except E.DomainError as err:
        return {"code": err.code, "offending": err.details["offending"]}


def trapped(fn: Any, *a: Any) -> dict[str, Any] | None:
    try:
        fn(*a)
        return None
    except E.DomainError as err:
        return {"code": err.code, "offending": err.details["offending"]}


def latent_keys(ents: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Every field name that starts with ``latent_`` in any published entity row, nested ones included (there must be none)."""
    found: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).startswith("latent_"):
                    found.add(str(k))
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for rows in ents.values():
        walk(rows)
    return sorted(found)


def both_sides(split_rows: list[dict[str, Any]]) -> int:
    """Accounts that keep retained rows in more than one of train / validation / test (after both purges there must be none)."""
    seen: dict[int, set[str]] = {}
    for r in split_rows:
        if r["status"] == "retained" and r["split"] in ("train", "validation", "test"):
            seen.setdefault(r["account_id"], set()).add(r["split"])
    return sum(1 for v in seen.values() if len(v) > 1)


def cohort_facts(data_c: dict[str, Any], world_c: World, pop_summary: dict[str, Any]) -> dict[str, Any]:
    """The facts each injection leaves in the PUBLISHED cohort, computed by the domain from the published rows only (the tests repeat this from the
    files). ``pop_summary`` carries the few population-level numbers the cohort cannot show (violator ids)."""
    reg = {r["feature_name"]: r for r in data_c["feature_registry"]}
    run = data_c["training_runs"][0]
    split_rows, counts = split_run(world_c, run)
    ret = {k: retained(split_rows, k) for k in ("train", "validation", "test")}
    sp = {r["cutoff_id"]: r for r in split_rows}
    all_rows = {c["cutoff_id"]: world_c.analyse(c["cutoff_id"]) for c in data_c["prediction_cutoffs"]}
    f4 = list(FEATURES)
    out: dict[str, Any] = {}
    cancel_at = {s["account_id"]: parse_ts(s["event_at"]) for s in data_c["subscription_events"] if s["event_type"] == "cancel"}
    refunds = [b for b in data_c["billing_events"] if Decimal(b["amount"]) < 0]
    out["INJ-01"] = {"refusal": refusal(reg, f4 + ["cancellation_reason"]), "registry_post_outcome": sorted(n for n, r in reg.items() if r["post_outcome"]),
                     "feature_keys_published": sorted({k for fr in data_c["feature_rows"] for k in fr["features_json"]}), "refund_events": len(refunds),
                     "refunds_all_after_the_cancellation": all(b["account_id"] in cancel_at and parse_ts(b["event_at"]) > cancel_at[b["account_id"]] for b in refunds)}
    ex = []
    for ev in pop_summary["inj02"]:
        if not ev["in_cohort"]:
            continue
        cid = cutoff_id(ev["account_id"], parse_ts(ev["prediction_at"]))
        a = all_rows[cid]
        uid = next(u["usage_event_id"] for u in data_c["usage_events"] if u["account_id"] == ev["account_id"] and u["event_at"] == ev["event_at"])
        ex.append({"account_id": ev["account_id"], "cutoff_id": cid, "usage_event_id": uid, "event_at": ev["event_at"], "available_at": ev["available_at"],
                   "usage_events_30d": a["features"]["usage_events_30d"], "arrived_late_usage_events": a["arrived_late"]["usage_events"],
                   "rule_flagged": a["features"]["usage_events_30d"] == 0 and a["features"]["high_severity_support_90d"] == 0,
                   "usage_events_30d_if_ignored": a["features"]["usage_events_30d"] + 1})
    out["INJ-02"] = {"examples": ex, "examples_excluded_correctly": bool(ex) and all(e["arrived_late_usage_events"] >= 1 and e["usage_events_30d"] == 0 and e["rule_flagged"] for e in ex), "rows_checked": sum(1 for a in all_rows.values() if a["eligible"]),
                     "all_max_available_before_cutoff": all(a["max_available_at"] is None or parse_ts(a["max_available_at"]) < parse_ts(a["prediction_at"]) for a in all_rows.values() if a["eligible"]),
                     "arrived_late_total_eligible_rows": sum(sum(a["arrived_late"].values()) for a in all_rows.values() if a["eligible"])}
    viol = pop_summary["violators"]
    gt = sorted(c for c, r in sp.items() if r["drop_reason"] == "GROUP_TEST")
    gv = sorted(c for c, r in sp.items() if r["drop_reason"] == "GROUP_VALIDATION")
    out["INJ-03"] = {"violators_population": {k: len(v) for k, v in viol.items()}, "violators_in_cohort": {k: [a for a in v if a in pop_summary["cohort_set"]] for k, v in viol.items()},
                     "dropped_group_test": len(gt), "dropped_group_validation": len(gv),
                     "accounts_retained_on_both_sides_of_a_boundary": both_sides(split_rows),
                     "example_row": gt[0] if gt else None,
                     "refusal": trapped(check_fit_rows, [gt[0]], ret["train"]) if gt else None, "split_counts": counts}
    lw = sorted(c for c, r in sp.items() if r["drop_reason"] == "LABEL_WINDOW")
    bound = {"train": parse_ts(run["train_end"]), "validation": parse_ts(run["validation_end"])}
    out["INJ-04"] = {"label_window_dropped": {k: counts[k]["label_window"] for k in ("train", "validation")}, "example_row": lw[0] if lw else None,
                     "retained_label_ends_within_range": all(parse_ts(all_rows[c]["label_end"]) <= bound[k] for k in bound for c in ret[k]),
                     "refusal": trapped(check_fit_rows, [lw[0]], ret["train"]) if lw else None, "embargo_days": HORIZON + GRACE}
    tr = sorted(ret["train"])[:1]
    va = sorted(ret["validation"])[:1]
    te = sorted(ret["test"])[:1]
    out["INJ-05"] = {"mixed_fit_rows": tr + va + te, "refusal": trapped(check_fit_rows, tr + va + te, ret["train"]),
                     "retained_train_rows": len(ret["train"]), "retained_validation_rows": len(ret["validation"]), "retained_test_rows": len(ret["test"])}
    out["INJ-06"] = {"refusal": trapped(check_threshold, "capacity", "test"), "validation_accepted": trapped(check_threshold, "capacity", "validation"),
                     "scenario_capacities": {s["scenario_id"]: s["capacity"] for s in data_c["intervention_scenarios"]}}
    ing = validate(data_c)
    out["INJ-07"] = {"rejected_labels": [r for r in ing.rejected if r["entity"] == "labels"], "other_rejections": [r for r in ing.rejected if r["entity"] != "labels"],
                     "censored_labels_are_null": all(lb["churned"] is None for lb in data_c["labels"] if not lb["mature"] and not lb["label_id"].startswith("lb-inj-")),
                     "censored_labels": sum(1 for lb in data_c["labels"] if not lb["mature"] and not lb["label_id"].startswith("lb-inj-"))}
    out["INJ-08"] = {"refusal": refusal(reg, f4 + ["latent_churn_propensity"]), "refusal_unregistered_latent_name": refusal(reg, ["usage_events_30d", "latent_made_up"]),
                     "latent_keys_in_published_entities": latent_keys({k: v for k, v in data_c.items() if isinstance(v, list)})}
    out["INJ-09"] = {"outreach_statuses": sorted({o["status"] for o in data_c["outreach_events"]}), "outreach_events": len(data_c["outreach_events"]),
                     "scenario_fields": sorted({k for s in data_c["intervention_scenarios"] for k in s}),
                     "outreach_fields": sorted({k for o in data_c["outreach_events"] for k in o})}
    pool = sum(1 for a in all_rows.values() if a["eligible"] and a["prediction_at"] == Z(CUTOFFS[-1]))
    out["INJ-10"] = {"queue_population": pool, "capacities_within_population": all(s["capacity"] <= pool for s in data_c["intervention_scenarios"]),
                     "oversize_capacity": pool + 1, "refusal": trapped(check_capacity, "sc-oversize", pool + 1, pool)}
    val_labelled = sorted(c for c in ret["validation"] if all_rows[c]["eligible"] and all_rows[c]["mature"])
    out["INJ-11"] = {"fit_rows_example": val_labelled[:3], "evaluation_rows_example": val_labelled[:1] + te,
                     "refusal": trapped(check_calibration_rows, val_labelled[:3], val_labelled[:1] + te, ret["validation"]) if val_labelled else None,
                     "calibration_fit_rows_in_cohort": len(val_labelled), "overlap_with_test_rows": len(set(val_labelled) & ret["test"])}
    out["INJ-12"] = {"refusal": refusal(reg, ["usage_events_30d", "generator_seed_bucket", "creation_sequence"]), "refusal_id_only": refusal(reg, ["creation_sequence"]),
                     "refusal_hash": refusal(reg, ["account_id_hash"])}
    return out


def population_facts(B: dict[str, Any]) -> dict[str, Any]:
    """Injection facts that need the whole population (the published cohort cannot show them)."""
    rows, fit = B["rows"], B["fit"]
    cfg = fit["run"]["config"]
    test_ids = {c for c, a in rows.items() if a["eligible"] and range_of(parse_ts(a["prediction_at"])) == "test"}
    train_ids, val_ids = fit["train_ids"], fit["validation_ids"]
    in_range = lambda ids, rg: all(range_of(parse_ts(rows[c]["prediction_at"])) == rg for c in ids)     # noqa: E731
    accounts = B["pop"]["accounts"]
    id_items = [{**it, "p": Fraction(it["account_id"], N_ACCOUNTS)} for it in union_items(with_predictions(B["world"], B["ext"], "logistic_regression"), rows)]
    return {"INJ-03": {"split_counts": fit["split_counts"], "violators": {k: len(v) for k, v in B["pop"]["violators"].items()},
                       "accounts_retained_on_both_sides_of_a_boundary": both_sides(fit["split_rows"])},
            "INJ-05": {"fit_rows": cfg["preprocessing"]["fit_rows"], "retained_mature_train_rows": len(train_ids), "fit_rows_sha256_is_the_retained_train_rows": cfg["preprocessing"]["fit_rows_sha256"] == sha256_hex(canon(train_ids)),
                       "all_fit_rows_in_the_train_range": in_range(train_ids, "train")},
            "INJ-11": {"calibration_fit_rows": cfg["calibration"]["fit_rows"], "equals_retained_mature_validation_rows": cfg["calibration"]["fit_rows"] == len(val_ids),
                       "fit_rows_sha256_is_the_retained_validation_rows": cfg["calibration"]["fit_rows_sha256"] == sha256_hex(canon(val_ids)),
                       "all_fit_rows_in_the_validation_range": in_range(val_ids, "validation"), "overlap_with_test_rows": len(set(val_ids) & test_ids), "evaluation_rows_are_test_rows": len(test_ids)},
            "INJ-12": {"id_only_ranking_newest_first": ap_brier(id_items)["average_precision"], "prevalence": ap_brier(id_items)["prevalence"],
                       "note": "a ranking by account id alone (creation order) scores this AP on the test range: an identifier carries what the calendar carries"},
            "accounts": len(accounts)}


INJECTIONS = [
    ("INJ-01", "P10-TEST-01", "cancellation reason offered as a feature", "request",
     "A feature request names cancellation_reason, a field that only exists after the cancellation (the registry flags it post_outcome, as it does cancellation_survey_score and refund_after_cancel). "
     "The leak is real in the events: every refund in the billing events follows its cancellation.",
     "The builder refuses the request with POST_OUTCOME_FIELD naming the field; nothing is stored; the four registered features rebuild unchanged."),
    ("INJ-02", "P10-TEST-02", "event arriving after the cutoff", "data",
     "Usage events that happened inside the observation window but were stored after the cutoff, at cutoffs where the account is otherwise silent (no usage in 30 days, no high-severity case).",
     "The event is excluded from the row and counted as arrived_late; the row's max_available_at stays before the cutoff; an account that looks active only because of the late event is still flagged by the rule."),
    ("INJ-03", "P10-TEST-03", "account repeated across splits", "data",
     "Accounts that were given a role in one split range by hash are also scored in another range (train and test, validation and test, train and validation), so the same account is on both sides of a boundary.",
     "The group purge drops the earlier rows of such an account from train and validation (GROUP_TEST, GROUP_VALIDATION); the drop counts are published with the split; preprocessing fitted on one of them is refused LEAKAGE."),
    ("INJ-04", "P10-TEST-04", "label window crossing a boundary", "data",
     "Rows in the last 104 days before train_end and validation_end have label windows (horizon plus grace) that end after the boundary.",
     "The label-window purge drops them from the earlier side (LABEL_WINDOW); the counts are published; preprocessing fitted on one of them is refused LEAKAGE; no retained row's label_end passes its range end."),
    ("INJ-05", "P10-TEST-05", "preprocessing fitted on all rows", "request",
     "A preprocessing fit that lists a training row together with a validation row and a test row (median, mean and deviation over everything).",
     "Refused LEAKAGE with every non-training row listed; the run's fit rows are exactly its retained, mature training rows (fit_rows_sha256)."),
    ("INJ-06", "P10-TEST-06", "threshold chosen on test", "request",
     "A capacity (the threshold of a queue) declared as selected on the test set.",
     "Refused THRESHOLD_ON_TEST; the three published scenarios declare capacities fixed before any outcome and selected on validation."),
    ("INJ-07", "P10-TEST-07", "immature rows labelled non-churn", "data",
     "Labels of false (not null) for eligible rows whose 104-day label window is still open at as_of.",
     "Import rejects each with CENSORED_LABEL; the rows keep their censored label (null) and are excluded from every outcome metric; the immature count is shown."),
    ("INJ-08", "P10-TEST-08", "latent truth column exposed as a feature", "request",
     "A feature request names latent_churn_propensity (or any latent_ name), the generator's synthetic truth.",
     "Refused LATENT_TRUTH; no published entity row carries a latent_ field; the propensities live only in the manifest."),
    ("INJ-09", "P10-TEST-09", "risk read as responsiveness", "request",
     "An outreach request whose basis is responsiveness or uplift, i.e. a high churn risk presented as willingness to respond to an offer.",
     "Refused RISK_NOT_RESPONSIVENESS; the accepted basis is risk_ranking; every queue is a draft, nothing is sent, and the economics carry no treatment-effect estimate."),
    ("INJ-10", "P10-TEST-10", "capacity above the population", "request",
     "A scenario whose capacity K is larger than the scored eligible population of the cutoff.",
     "Refused CAPACITY_EXCEEDS_POPULATION (CAPACITY_K_GT_N); the three published capacities are within the population."),
    ("INJ-11", "P10-TEST-11", "calibration evaluated on its own training rows", "request",
     "A calibration request whose evaluation rows include rows the Platt mapping was fitted on.",
     "Refused CALIBRATION_ON_FIT_ROWS; the mapping is fitted on the retained validation rows only and its reliability curve is read on test rows, with no overlap."),
    ("INJ-12", "P10-TEST-12", "identifier-derived feature", "request",
     "A feature request names creation_sequence (or an account id hash), and generator_seed_bucket, a generator internal.",
     "Refused ID_FEATURE / LATENT_TRUTH with every offending field listed; an identifier is creation order, which the calendar already carries."),
]


CHECKS = {   # (scope, path into the facts, expected value)
    "INJ-01": [("cohort", "INJ-01.refusal.code", "POST_OUTCOME_FIELD"), ("cohort", "INJ-01.refunds_all_after_the_cancellation", True),
               ("cohort", "INJ-01.feature_keys_published", sorted(FEATURES))],
    "INJ-02": [("cohort", "INJ-02.examples_excluded_correctly", True), ("cohort", "INJ-02.all_max_available_before_cutoff", True)],
    "INJ-03": [("cohort", "INJ-03.refusal.code", "LEAKAGE"), ("cohort", "INJ-03.accounts_retained_on_both_sides_of_a_boundary", 0),
               ("population", "INJ-03.accounts_retained_on_both_sides_of_a_boundary", 0)],
    "INJ-04": [("cohort", "INJ-04.refusal.code", "LEAKAGE"), ("cohort", "INJ-04.retained_label_ends_within_range", True)],
    "INJ-05": [("cohort", "INJ-05.refusal.code", "LEAKAGE"), ("cohort", "INJ-05.refusal.offending#len", 2),
               ("population", "INJ-05.fit_rows_sha256_is_the_retained_train_rows", True), ("population", "INJ-05.all_fit_rows_in_the_train_range", True)],
    "INJ-06": [("cohort", "INJ-06.refusal.code", "THRESHOLD_ON_TEST"), ("cohort", "INJ-06.validation_accepted", None)],
    "INJ-07": [("cohort", "INJ-07.rejected_labels#len", INJ07_EXAMPLES), ("cohort", "INJ-07.censored_labels_are_null", True), ("cohort", "INJ-07.other_rejections#len", 0)],
    "INJ-08": [("cohort", "INJ-08.refusal.code", "LATENT_TRUTH"), ("cohort", "INJ-08.refusal_unregistered_latent_name.code", "LATENT_TRUTH"),
               ("cohort", "INJ-08.latent_keys_in_published_entities", [])],
    "INJ-09": [("cohort", "INJ-09.outreach_statuses", ["draft"])],
    "INJ-10": [("cohort", "INJ-10.refusal.code", "CAPACITY_EXCEEDS_POPULATION"), ("cohort", "INJ-10.capacities_within_population", True)],
    "INJ-11": [("cohort", "INJ-11.refusal.code", "CALIBRATION_ON_FIT_ROWS"), ("population", "INJ-11.overlap_with_test_rows", 0),
               ("population", "INJ-11.fit_rows_sha256_is_the_retained_validation_rows", True), ("population", "INJ-11.all_fit_rows_in_the_validation_range", True)],
    "INJ-12": [("cohort", "INJ-12.refusal.code", "LATENT_TRUTH"), ("cohort", "INJ-12.refusal_id_only.code", "ID_FEATURE"), ("cohort", "INJ-12.refusal_hash.code", "ID_FEATURE")]}


def resolve(facts: dict[str, Any], path: str) -> Any:
    """A dotted path into the facts; a trailing ``#len`` is the length of the list."""
    want_len = path.endswith("#len")
    cur: Any = facts
    for part in path.removesuffix("#len").split("."):
        cur = None if cur is None else cur[part]
    return len(cur) if want_len else cur


def injection_records(inj: str, data_c: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    f = facts[inj]
    rec = lambda e, ids: [{"entity": e, "id": i} for i in ids]       # noqa: E731
    if inj == "INJ-01":
        return rec("feature_registry", ["cancellation_reason", "cancellation_survey_score", "refund_after_cancel"])
    if inj == "INJ-02":
        return [x for e in f["examples"] for x in (rec("usage_events", [e["usage_event_id"]]) + rec("prediction_cutoffs", [e["cutoff_id"]]))]
    if inj == "INJ-03":
        sp = [s for s in data_c["split_assignments"] if s["drop_reason"] in ("GROUP_TEST", "GROUP_VALIDATION")]
        return rec("accounts", sorted(a for v in f["violators_in_cohort"].values() for a in v)) + rec("split_assignments", [s["assignment_id"] for s in sp[:8]])
    if inj == "INJ-04":
        return rec("split_assignments", [s["assignment_id"] for s in data_c["split_assignments"] if s["drop_reason"] == "LABEL_WINDOW"][:8])
    if inj in ("INJ-05", "INJ-11"):
        return rec("training_runs", [RUN_ID])
    if inj in ("INJ-06", "INJ-09", "INJ-10"):
        return rec("intervention_scenarios", [s["scenario_id"] for s in data_c["intervention_scenarios"]])
    if inj == "INJ-07":
        return rec("labels", [lb["label_id"] for lb in data_c["labels"] if lb["label_id"].startswith("lb-inj-")])
    if inj == "INJ-08":
        return rec("feature_registry", ["latent_churn_propensity"])
    return rec("feature_registry", ["creation_sequence", "account_id_hash", "generator_seed_bucket"])


def replay_events(version: str, data_c: dict[str, Any], facts: dict[str, Any], wc: World) -> dict[str, Any]:
    """The replay of each injection through the API on a database seeded with the published cohort (server clock 2026-10-05T12:00:00Z): the
    request that carries the defect, and the one that recovers. ``expected_*`` are what the API must answer; the tests replay them."""
    H = {"X-Actor-Id": "usr-scientist01", "X-Actor-Role": "scientist"}
    f4 = list(FEATURES)
    t_test = Z(datetime(2026, 3, 1, tzinfo=UTC))
    t_last = Z(CUTOFFS[-1])
    t_imm = Z(CUTOFFS[-3])
    rows_c = {c["cutoff_id"]: wc.analyse(c["cutoff_id"]) for c in data_c["prediction_cutoffs"]}
    elig_at = lambda pa: sum(1 for a in rows_c.values() if a["eligible"] and a["prediction_at"] == pa)      # noqa: E731
    cens_at = lambda pa: sum(1 for a in rows_c.values() if a["eligible"] and not a["mature"] and a["prediction_at"] == pa)      # noqa: E731
    run = data_c["training_runs"][0]
    split_rows, _ = split_run(wc, run)
    ret = {k: retained(split_rows, k) for k in ("train", "validation", "test")}
    n = {"v": 0}

    def cmd(ev: str, name: str, input_: dict[str, Any], status: int = 200, **expect: Any) -> dict[str, Any]:
        n["v"] += 1
        step: dict[str, Any] = {"kind": "command", "command": name, "headers": H,
                                "input": {"request_id": f"req-{ev.lower()}-{n['v']}", "dataset_version": version, "idempotency_key": f"{ev.lower()}-{n['v']}", "input": input_},
                                "expected_status": status}
        step.update(expect)
        return step

    def read(path: str, params: dict[str, Any], expect: list[dict[str, Any]]) -> dict[str, Any]:
        return {"kind": "read", "path": path, "params": params, "expected_status": 200, "expect": expect}

    def split_step(ev: str, run_id: str) -> dict[str, Any]:
        return cmd(ev, "split-evaluation", {"training_run_id": run_id, "train_end": run["train_end"], "validation_end": run["validation_end"], "test_end": run["test_end"]},
                   expected_result={"created": True})

    def leak(offending: list[tuple[str, str]]) -> dict[str, Any]:
        return {"expected_rules": ["LEAKAGE"], "expected_offending": [{"item": i, "code": c} for i, c in offending]}

    fit_default = sum(1 for c in ret["train"] if rows_c[c]["eligible"])
    events: list[dict[str, Any]] = []
    # EV-01
    events.append({"event_id": "EV-01", "injection": "INJ-01", "requires": ["seed:published-cohort"], "steps": [
        cmd("EV-01", "build-point-in-time-features", {"prediction_at": t_test, "fields": f4 + ["cancellation_reason"]}, 422,
            expected_rules=["POST_OUTCOME_FIELD"], expected_offending=[{"item": "cancellation_reason", "code": "POST_OUTCOME_FIELD"}]),
        cmd("EV-01", "build-point-in-time-features", {"prediction_at": t_test, "fields": f4}, 200,
            expected_result={"built": 0, "unchanged": elig_at(t_test), "eligible": elig_at(t_test)})]})
    # EV-02
    ex = facts["INJ-02"]["examples"]
    steps02: list[dict[str, Any]] = []
    if ex:
        e0 = ex[0]
        steps02.append(cmd("EV-02", "build-point-in-time-features", {"prediction_at": parse_pa(e0["cutoff_id"]), "account_ids": [e0["account_id"]]}, 200,
                           expected_result={"built": 0, "unchanged": 1, "arrived_late.usage_events": e0["arrived_late_usage_events"], "availability_proof.all_before_cutoff": True},
                           expected_warning_codes=["LATE_EVENTS_EXCLUDED"]))
        steps02.append(read("/data/feature_rows", {"cutoff_id": e0["cutoff_id"]}, [{"path": "data[0].features_json.usage_events_30d", "equals": e0["usage_events_30d"]}]))
    events.append({"event_id": "EV-02", "injection": "INJ-02", "requires": ["seed:published-cohort"], "steps": steps02})
    # EV-03..05 (a fresh run each)
    gt = facts["INJ-03"]["example_row"]
    lw = facts["INJ-04"]["example_row"]
    mixed = facts["INJ-05"]["mixed_fit_rows"]
    for ev, run_id, rows_, off in (("EV-03", "tr-replay-03", [gt], [(gt, "NOT_TRAINING_ROW")]), ("EV-04", "tr-replay-04", [lw], [(lw, "NOT_TRAINING_ROW")]),
                                   ("EV-05", "tr-replay-05", mixed, [(c, "NOT_TRAINING_ROW") for c in mixed if c not in ret["train"]])):
        events.append({"event_id": ev, "injection": "INJ-" + ev[3:], "requires": ["seed:published-cohort"], "steps": [
            split_step(ev, run_id),
            cmd(ev, "fit-preprocessing", {"training_run_id": run_id, "fit_rows": rows_}, 422, **leak(off)),
            cmd(ev, "fit-preprocessing", {"training_run_id": run_id}, 200, expected_result={"fit_rows": fit_default, "fitted_on": "retained training rows only"})]})
    # EV-06
    sc6 = {"scenario_id": "sc-replay-06", "capacity": 5, "contact_cost": "8.00", "assumed_effect": "0.200000", "margin_value": "150.00"}
    pool = facts["INJ-10"]["queue_population"]
    events.append({"event_id": "EV-06", "injection": "INJ-06", "requires": ["seed:published-cohort"], "steps": [
        cmd("EV-06", "simulate-economics", {"training_run_id": RUN_ID, "prediction_at": t_last, "scenario": {**sc6, "selected_on": "test"}}, 422,
            expected_rules=["THRESHOLD_ON_TEST"], expected_offending=[{"item": "capacity", "code": "SELECTED_ON_TEST"}]),
        cmd("EV-06", "simulate-economics", {"training_run_id": RUN_ID, "prediction_at": t_last, "scenario": {**sc6, "selected_on": "validation"}}, 200,
            expected_result={"label": "hypothetical", "treatment_effect_estimate": None, "population": pool}, expected_warning_codes=["HYPOTHETICAL"])]})
    # EV-07
    c7 = cens_at(t_imm)
    events.append({"event_id": "EV-07", "injection": "INJ-07", "requires": ["seed:published-cohort"], "steps": [
        cmd("EV-07", "define-label", {"prediction_at": t_imm}, 200, expected_result={"censored": c7, "mature": 0, "churn_rate": None, "created": 0, "unchanged": c7},
            expected_warning_codes=["CENSORED_ROWS"]),
        read("/metrics", {"training_run_id": RUN_ID, "prediction_at": t_imm, "model": "logistic_regression"},
             [{"path": f"data.cutoff_sets.{t_imm}.population.censored", "equals": c7}, {"path": f"data.cutoff_sets.{t_imm}.churn_rate.value", "equals": None},
              {"path": f"data.cutoff_sets.{t_imm}.population.evaluated", "equals": 0}])]})
    # EV-08
    events.append({"event_id": "EV-08", "injection": "INJ-08", "requires": ["seed:published-cohort"], "steps": [
        cmd("EV-08", "build-point-in-time-features", {"prediction_at": t_test, "fields": ["latent_churn_propensity"]}, 422,
            expected_rules=["LATENT_TRUTH"], expected_offending=[{"item": "latent_churn_propensity", "code": "LATENT_TRUTH"}]),
        cmd("EV-08", "build-point-in-time-features", {"prediction_at": t_test, "fields": ["usage_events_30d", "latent_made_up"]}, 422,
            expected_rules=["LATENT_TRUTH"], expected_offending=[{"item": "latent_made_up", "code": "LATENT_TRUTH"}]),
        cmd("EV-08", "build-point-in-time-features", {"prediction_at": t_test, "fields": f4}, 200, expected_result={"built": 0, "unchanged": elig_at(t_test)})]})
    # EV-09 / EV-10
    sc9 = {"scenario_id": "sc-replay-09", "capacity": 5, "contact_cost": "8.00", "assumed_effect": "0.200000", "margin_value": "150.00"}
    events.append({"event_id": "EV-09", "injection": "INJ-09", "requires": ["seed:published-cohort"], "steps": [
        cmd("EV-09", "prioritize-outreach", {"training_run_id": RUN_ID, "prediction_at": t_last, "basis": "responsiveness", "scenario": sc9}, 422,
            expected_rules=["RISK_NOT_RESPONSIVENESS"], expected_offending=[{"item": "responsiveness", "code": "BASIS_NOT_RISK_RANKING"}]),
        cmd("EV-09", "prioritize-outreach", {"training_run_id": RUN_ID, "prediction_at": t_last, "basis": "uplift", "scenario": sc9}, 422, expected_rules=["RISK_NOT_RESPONSIVENESS"]),
        cmd("EV-09", "prioritize-outreach", {"training_run_id": RUN_ID, "prediction_at": t_last, "basis": "risk_ranking", "scenario": sc9}, 200,
            expected_result={"queue_status": "draft", "sent": 0, "treatment_effect_estimate": None, "capacity": 5, "population": pool}, expected_warning_codes=["RISK_IS_NOT_RESPONSIVENESS", "DRAFT_ONLY"])]})
    big = {"scenario_id": "sc-replay-10", "capacity": pool + 1, "contact_cost": "8.00", "assumed_effect": "0.200000", "margin_value": "150.00"}
    events.append({"event_id": "EV-10", "injection": "INJ-10", "requires": ["seed:published-cohort"], "steps": [
        cmd("EV-10", "prioritize-outreach", {"training_run_id": RUN_ID, "prediction_at": t_last, "scenario": big}, 422,
            expected_rules=["CAPACITY_EXCEEDS_POPULATION"], expected_offending=[{"item": "sc-replay-10", "code": f"CAPACITY_{pool + 1}_GT_{pool}"}]),
        cmd("EV-10", "prioritize-outreach", {"training_run_id": RUN_ID, "prediction_at": t_last, "scenario": {**big, "scenario_id": "sc-replay-10b", "capacity": pool}}, 200,
            expected_result={"capacity": pool, "population": pool, "queue_status": "draft"})]})
    # EV-11
    f11 = facts["INJ-11"]
    val_labelled = f11["fit_rows_example"]
    events.append({"event_id": "EV-11", "injection": "INJ-11", "requires": ["seed:published-cohort"], "steps": [
        split_step("EV-11", "tr-replay-11"),
        cmd("EV-11", "fit-preprocessing", {"training_run_id": "tr-replay-11"}, 200, expected_result={"fit_rows": fit_default}),
        cmd("EV-11", "train-baseline", {"training_run_id": "tr-replay-11"}, 200),
        cmd("EV-11", "calibrate-model", {"training_run_id": "tr-replay-11", "fit_rows": f11["fit_rows_example"], "evaluation_rows": f11["evaluation_rows_example"]}, 422,
            expected_rules=["CALIBRATION_ON_FIT_ROWS"], expected_offending=[{"item": val_labelled[0], "code": "IN_FIT_ROWS"}]),
        cmd("EV-11", "calibrate-model", {"training_run_id": "tr-replay-11"}, 200,
            expected_result={"method": "platt", "fit_rows": f11["calibration_fit_rows_in_cohort"], "evaluation_rows": len(ret["test"]), "evaluation_rows_overlap_fit_rows": 0, "test_rows_read": 0})]})
    # EV-12
    events.append({"event_id": "EV-12", "injection": "INJ-12", "requires": ["seed:published-cohort"], "steps": [
        cmd("EV-12", "build-point-in-time-features", {"prediction_at": t_test, "fields": ["usage_events_30d", "generator_seed_bucket", "creation_sequence"]}, 422,
            expected_rules=["LATENT_TRUTH"], expected_offending=[{"item": "generator_seed_bucket", "code": "LATENT_TRUTH"}, {"item": "creation_sequence", "code": "ID_FEATURE"}]),
        cmd("EV-12", "build-point-in-time-features", {"prediction_at": t_test, "fields": ["creation_sequence"]}, 422,
            expected_rules=["ID_FEATURE"], expected_offending=[{"item": "creation_sequence", "code": "ID_FEATURE"}]),
        cmd("EV-12", "build-point-in-time-features", {"prediction_at": t_test, "fields": f4}, 200, expected_result={"built": 0, "unchanged": elig_at(t_test)})]})
    return {"dataset_version": version, "server_clock": Z(AS_OF + timedelta(hours=12)), "events": events}


def parse_pa(cid: str) -> str:
    """The prediction_at of a cutoff id ``co-<account>-<yyyymmdd>``."""
    d = cid.rsplit("-", 1)[1]
    return f"{d[:4]}-{d[4:6]}-{d[6:]}T00:00:00Z"


# ---- disclosures --------------------------------------------------------------------------------------------------------------------
def disclosures(B: dict[str, Any]) -> list[tuple[str, str] | tuple[str, str, list[str]]]:
    trows = B["test_table"]["rows"]
    tn, ta = len(trows), len({r[0] for r in trows})
    sh = GROUP_SHARE
    lt = {e: LATE[e][0] // 10_000 for e in LATE}
    return [
        ("D-G01", "Parameters declared before the first run: the seed, the sizes (2,400 accounts, 21 cutoffs, the three split boundaries), the stated margins and targets "
                  "(MARGINS, TARGETS), the drift and repricing designs, the late-arrival shares, the scenario capacities 5 / 10 / 20 and the cohort size rule. The values below "
                  "were changed AFTER looking at outcomes during development; the published world is the first run of the final code and nothing was re-drawn, kept or dropped "
                  "after it."),
        ("D-G02", "Outcome-informed changes, in order.", [
            "After the first simulation the starter 90-day churn was 20-27 % per cutoff: the weekly hazard intercepts were lowered (starter -4800 to -5100, smb -5000 to -5100, mid -5300 to "
            "-5400, enterprise -5700 to -5800 milli-logit) and the starter repricing uplift from 700 to 600.",
            "The first model fit gave logistic AP 0.199 against the rule's 0.116 and a Brier margin of 0.0010, below the stated 0.002, and a high-severity coefficient near zero: a "
            "per-account long-run engagement offset (+-500, then +-900 milli) was added and the engagement coefficient raised 1100 to 1500 to 2200, with the intercepts lowered once more "
            "(starter and smb to -5400, mid -5700, enterprise -6100) to keep the churn level. These changes strengthen the signal the four features can see; they were made until the "
            "stated margins were met and are why the margins are met.",
            "The first drift run showed PSI 0.138 at 2026-04-01 for the drifting region (the change straddled the window): the change moved from 2026-03-15 to 2026-03-31, 40 % of logins "
            "kept instead of 50 %, and the statement narrowed from 'every cutoff after 2026-03' to 'every cutoff from 2026-05-01'.",
            "The share of cancellations that arrive after the 14-day grace went from 2 % to 4 % (range 15 to 60 days) so that the label effect is visible.",
            "The late-arrival target changed from 'all four features flip' to 'at least three of four' after the high-severity count flipped on no test row.",
            "The INJ-02 examples (usage events that arrive after the cutoff) were allowed in any range: they were all outside the cohort when restricted to the test range.",
            "The scenario assumptions were changed once after the first run showed negative expected value for all three (contact cost 8 / 12 / 20, effect 0.20 / 0.15 / 0.10, margin 150 / "
            "220 / 320 became cost 8, effect 0.30 / 0.20 / 0.10, margin 200), so that the lab shows a range of outcomes; the values remain assumptions.",
            "The cohort grew from 140 to 200 accounts once the first output measured 3.1 MB."]),
        ("D-G03", "Account-level roles, a design choice made to keep the contract's group purge workable and therefore listed with the outcome-informed choices.", [
            f"Each account is assigned to train ({sh[0]} %), validation ({sh[1]} %) or test ({sh[2]} %) by a hash of its id, independent of everything else, and has cutoff rows only in the "
            "cutoffs of its role plus every cutoff from 2026-06-01 (outside the test range, where every active account is scored). The group purge of D-02 would otherwise remove every "
            "earlier row of every surviving account.",
            f"The consequence is part of the design: the test population is the test-role accounts' rows, {tn:,} rows from {ta} accounts, not every account at every test cutoff, and the same "
            "account contributes several rows across overlapping cutoffs.",
            "The injected violators (INJ-03) are accounts given a second role."]),
        ("D-G04", "What is published. The 2,400-account world is built and evaluated by the domain in full; the files carry (a) the COMPLETE records of a uniform sample of "
                  "accounts (the published cohort, entity files, cohort size in the manifest), so that the domain rebuilds every row from events, (b) per-cutoff aggregates of the whole "
                  "population, (c) the whole test range as one compact table (features, outcome, the five probabilities: random, rule, logistic before and after Platt scaling, prevalence constant) for the browser, and (d) the population-level calibration, split "
                  "and drift summaries. Predictions and scoring publications of the cohort start at the 2025-10-01 cutoff (the validation range); the world also scored the earlier rows. "
                  "Events of the other accounts are not published. The size cap (5 MB) set the cohort size; it is a sample, not the population."),
        ("D-G05", "Latent truth. The per-account, per-cutoff churn propensity is a stylised 90-day probability (one minus the product over 13 weeks of one minus the weekly hazard, the "
                  "hazard held at the account's latest state, plus the known repricing effect). It is kept only in the manifest (synthetic_truth), for every eligible cutoff of the "
                  "population; no feature, no prediction and no entity row reads it. The reference average precision of the propensity is an approximate ceiling, not a bound."),
        ("D-G06", f"Late arrival is simulated per event with declared shares (events that arrive a day or more late: usage {lt['usage_events']} %, billing {lt['billing_events']} %, "
                  f"support {lt['support_events']} %, subscription {lt['subscription_events']} %; cancellations a further {CANCEL_LATE_PPM // 10_000} % of {CANCEL_LATE_DAYS[0]} to "
                  f"{CANCEL_LATE_DAYS[1] - 1} days and {CANCEL_VERY_LATE_PPM // 10_000} % of {CANCEL_VERY_LATE_DAYS[0]} to {CANCEL_VERY_LATE_DAYS[1] - 1} days); an event that has not "
                  "arrived by as_of is not in the world. Cancellations arriving after the 14-day grace are not churn (D-P10-08), so such accounts are labelled non-churn."),
        ("D-G07", "Only the four registered features exist: the domain builds four. The registry also carries the refused fields (post-outcome, latent, identifier-derived); the "
                  "'about twenty features' of the brief are not met. Every usable feature is registered and every registered one is either built or refused."),
        ("D-G08", "Scoring instants are generator choices: the run froze on 2026-08-20, the backtest cutoffs were scored on 2026-08-21 and the cutoff of 2026-09-01 by the production run "
                  "on 2026-09-01; the domain reports the scoring freshness and the data freshness at as_of separately (published_cohort.claims.*.freshness). The capacities 5 / 10 / 20 "
                  "and the economics are assumptions fixed before any outcome (scenario values: see D-G02 (7)) and labelled hypothetical; no treatment effect is estimated."),
        ("D-G09", "Simplifications: one cancellation per account (no win-back), renewals at the billing interval (30 days or 365), refunds only after a cancellation, the usage event names "
                  "carry no information, amounts are synthetic USD, accounts are not deleted. The logistic model is trained on the survivors of the account-level split (train rows are "
                  "those of train-role accounts in 2025-01 .. 2025-06), which is what the contract's group purge produces. The demo profile of the brief's section 12 was not available "
                  "to the generator; the full population can be written as one inputs object with --inputs."),
    ]


def disclosure_entry(d: tuple[Any, ...]) -> dict[str, Any]:
    """A disclosure as the manifest carries it: ``text`` is the whole statement; ``items`` (when the disclosure is an ordered list) are its numbered
    parts, so that a page can list every one of them (D-09, R10-11)."""
    if len(d) == 2:
        return {"id": d[0], "text": d[1]}
    return {"id": d[0], "text": d[1] + " " + " ".join(f"({n}) {t}" for n, t in enumerate(d[2], 1)), "items": list(d[2])}


NOTE_TRUTH = ("Synthetic truth for the verification layer only: the latent churn propensities (parts per million) of the published cohort's and the test table's eligible "
              "cutoffs, the account roles and the injected accounts. It is never read by a feature, a model, the seeder or the API (P10-DOMAIN-03).")


# ---- build, write ---------------------------------------------------------------------------------------------------------------------
def build_all(seed: int = DEFAULT_SEED) -> dict[str, Any]:
    B: dict[str, Any] = {"seed": seed}
    pop = build_population(seed)
    ents = entity_rows(seed, pop)
    data = base_inputs(ents)
    ing = validate(data)
    if ing.rejected:
        raise AssertionError(f"the generated population has rejected rows: {ing.rejected[:3]}")
    world = World(data, ing.accepted)
    rows = {c["cutoff_id"]: world.analyse(c["cutoff_id"]) for c in ing.accepted["prediction_cutoffs"]}
    fit = fit_run(world, rows)
    preds = score_all(rows, fit["run"])
    pubs = publication_rows(rows)
    ext = {"training_runs": [fit["run"]], "predictions": preds, "scoring_publications": pubs}
    B.update(pop=pop, ents=ents, data=data, ing=ing, world=world, rows=rows, fit=fit, preds=preds, pubs=pubs, ext=ext)
    dr = {"models": dr_models(world, rows, ext, pop), "calibration": dr_calibration(world, rows, ext, pop, fit), "drift": dr_drift(world, rows, ext, pop),
          "late": dr_late(seed, world, rows, ents, data), "censored": dr_censored(rows, ents)}
    B["dr"] = dr
    B["cohort"] = coh = assemble_cohort(seed, pop, ents, rows, fit, preds, world)
    B["claims"] = cohort_claims(coh["data"])
    B["pop_summary"] = {"cohort_set": set(pop["cohort"]), "violators": pop["violators"],
                        "inj02": [{"account_id": e["account_id"], "prediction_at": Z(e["prediction_at"]), "event_at": Z(e["event_at"]), "available_at": Z(e["available_at"]),
                                   "in_cohort": e["in_cohort"]} for e in pop["inj02"]]}
    B["facts"] = cohort_facts(coh["data"], coh["world"], B["pop_summary"])
    B["pfacts"] = population_facts(B)
    for inj, checks in CHECKS.items():
        for scope, path, want in checks:
            got = resolve(B["facts"] if scope == "cohort" else B["pfacts"], path)
            if got != want:
                raise AssertionError(f"injection check {path} ({scope}): expected {want!r}, got {got!r}")
    B["test_table"] = test_cohort_table(rows, preds, pop, fit)
    B["aggregates"] = aggregates(world, rows, ext)
    B["economics_full_world"] = economics_full_world(world, ext)
    return B


def entity_text(name: str, version: str, rows: list[dict]) -> str:
    body = ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return f'{{"entity":{json.dumps(name)},"dataset_version":{json.dumps(version)},"rows":[\n{body}\n]}}\n'


def table_text(name: str, version: str, t: dict[str, Any]) -> str:
    body = ",\n".join(json.dumps(r, separators=(",", ":")) for r in t["rows"])
    head = {k: v for k, v in t.items() if k != "rows"}
    return (f'{{"entity":{json.dumps(name)},"dataset_version":{json.dumps(version)},"head":{json.dumps(head, sort_keys=True, separators=(",", ":"))},"rows":[\n{body}\n]}}\n')


def pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


SORT = {"accounts": lambda r: r["account_id"], "subscription_events": lambda r: r["subscription_event_id"], "billing_events": lambda r: r["billing_event_id"],
        "usage_events": lambda r: r["usage_event_id"], "support_events": lambda r: r["support_event_id"], "prediction_cutoffs": lambda r: r["cutoff_id"],
        "feature_rows": lambda r: r["cutoff_id"], "labels": lambda r: (r["cutoff_id"], r["label_id"]), "training_runs": lambda r: r["training_run_id"],
        "predictions": lambda r: (r["cutoff_id"], r["model_name"]), "intervention_scenarios": lambda r: r["scenario_id"], "outreach_events": lambda r: r["outreach_event_id"],
        "feature_registry": lambda r: 0, "split_assignments": lambda r: r["cutoff_id"], "scoring_publications": lambda r: (r["prediction_at"], r["model_name"])}
ENTITIES = ("accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels", "training_runs",
            "predictions", "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments", "scoring_publications")


def training_summary(B: dict[str, Any]) -> dict[str, Any]:
    fit, rows = B["fit"], B["rows"]
    cfg = fit["run"]["config"]
    pos = lambda ids: sum(1 for c in ids if rows[c]["churned"])      # noqa: E731
    return {"training_run_id": RUN_ID, "train_end": fit["run"]["train_end"], "validation_end": fit["run"]["validation_end"], "test_end": fit["run"]["test_end"],
            "embargo_days": HORIZON + GRACE, "split_counts_population": fit["split_counts"], "training_rows": len(fit["train_ids"]), "training_positives": pos(fit["train_ids"]),
            "validation_rows": len(fit["validation_ids"]), "validation_positives": pos(fit["validation_ids"]), "preprocessing": cfg["preprocessing"], "models": cfg["models"],
            "calibration": cfg["calibration"], "config_hash": fit["run"]["config_hash"]}


def write_all(seed: int, out: Path, data_dir: Path, inputs_path: Path | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    B = build_all(seed)
    version = f"{VERSION_TAG}-{seed}-{DATE_TAG}"
    coh, rows, fit, pop = B["cohort"], B["rows"], B["fit"], B["pop"]
    ents_c = {k: sorted(coh["ents"][k], key=SORT[k]) for k in ENTITIES}
    wc: World = coh["world"]
    split_c = split_run(wc, fit["run"])[1]
    full_sp = {r["cutoff_id"]: r for r in fit["split_rows"]}
    for sa in ents_c["split_assignments"]:
        d = full_sp[sa["cutoff_id"]]
        if (sa["split"], sa["status"], sa["drop_reason"]) != (d["split"], d["status"], d["drop_reason"]):
            raise AssertionError("cohort split differs from the population split at " + sa["cutoff_id"])
    # analytic files -----------------------------------------------------------------------------------------------
    latent = {cid: propensity_ppm(pop["accounts"][a["account_id"] - 1], parse_ts(a["prediction_at"])) for cid, a in sorted(rows.items()) if a["eligible"]}
    split_summary = {"dataset_version": version, "training_run_id": RUN_ID, "boundaries": {"train_end": Z(TRAIN_END), "validation_end": Z(VALIDATION_END), "test_end": Z(TEST_END)},
                     "embargo_days": HORIZON + GRACE, "population": fit["split_counts"], "published_cohort": split_c,
                     "reasons": {"LABEL_WINDOW": "label window [prediction_at, label_end) crosses the boundary of its range (label_end > boundary); dropped from the earlier side",
                                 "GROUP_TEST": "the account has a row in the test range; its earlier train and validation rows are dropped",
                                 "GROUP_VALIDATION": "the account has a row in the validation range; its earlier train rows are dropped"},
                     "injected_violators": {k: len(v) for k, v in pop["violators"].items()}}
    cal = B["dr"]["calibration"]
    calibration = {"dataset_version": version, "training_run_id": RUN_ID, "method": "platt", "a": fit["run"]["config"]["calibration"]["a"], "b": fit["run"]["config"]["calibration"]["b"],
                   "fit_rows": fit["run"]["config"]["calibration"]["fit_rows"], "fit_range": "validation (retained, mature rows only)", "evaluation_range": "test",
                   "platt_effect": cal["platt_effect"], "fit_rows_by_cutoff": dict(sorted(Counter(rows[c]["prediction_at"] for c in fit["validation_ids"]).items())),
                   "evaluation_rows": cal["overall"]["n"], "overall": cal["overall"], "uncalibrated_overall": cal["uncalibrated_overall"], "by_segment": cal["by_segment"],
                   "by_region": cal["by_region"], "largest_region_gap": cal["largest_region_gap"],
                   "reliability_calibrated": cal["reliability_calibrated"], "reliability_uncalibrated": cal["reliability_uncalibrated"]}
    agg = {"dataset_version": version, "training_run_id": RUN_ID, "population": "all 2,400 accounts as built by the domain; a cutoff before 2026-06-01 holds the accounts of the matching role only",
           "cutoffs": B["aggregates"], "drift": B["dr"]["drift"], "economics_full_world": B["economics_full_world"]}
    files: dict[str, str] = {}
    for name in ENTITIES:
        files[f"{name}.json"] = entity_text(name, version, ents_c[name])
    files["test_cohort.json"] = table_text("test_cohort", version, B["test_table"])
    files["cutoff_aggregates.json"] = pretty(agg)
    files["calibration.json"] = pretty(calibration)
    files["split_summary.json"] = pretty(split_summary)
    hobj = {n: ents_c[n] for n in ENTITIES}
    hobj.update(test_cohort=B["test_table"], cutoff_aggregates=agg, calibration=calibration, split_summary=split_summary)
    dhash = hashlib.sha256()
    for k in sorted(hobj):
        dhash.update(canon(hobj[k]).encode())
    dataset_hash = dhash.hexdigest()
    # injections -----------------------------------------------------------------------------------------------------
    facts = {**B["facts"]}
    events = replay_events(version, coh["data"], facts, wc)
    ev_by_inj: dict[str, list[str]] = {}
    for e in events["events"]:
        ev_by_inj.setdefault(e["injection"], []).append(e["event_id"])
    injections = []
    for inj, test, name, location, defect, handling in INJECTIONS:
        injections.append({"id": inj, "test": test, "name": name, "location": location, "defect": defect, "expected_handling": handling,
                           "records": injection_records(inj, coh["data"], facts),
                           "expected_rejections": B["facts"]["INJ-07"]["rejected_labels"] if inj == "INJ-07" else [],
                           "checks": [{"scope": s, "path": p, "equals": w} for s, p, w in CHECKS[inj]], "facts": {"cohort": facts[inj], **({"population": B["pfacts"][inj]} if inj in B["pfacts"] else {})},
                           "events": ev_by_inj.get(inj, [])})
    designed = designed_relationships(B)
    inj_doc = {"dataset_version": version, "dataset_hash": dataset_hash, "seed": seed, "contract_version": CONTRACT_VERSION, "injections": injections,
               "designed_relationships": designed, "events_file": "injection-events.json"}
    files["injection-manifest.json"] = pretty(inj_doc)
    files["injection-events.json"] = pretty(events)
    # manifest -------------------------------------------------------------------------------------------------------
    manifest = {
        "dataset_version": version, "dataset_hash": dataset_hash, "generated_at": Z(AS_OF), "contract_version": CONTRACT_VERSION, "as_of": Z(AS_OF),
        "config": {"label_version": {"label_version_id": LABEL_VERSION, "horizon_days": HORIZON, "grace_days": GRACE}, "feature_version_spec": {"feature_version": FEATURE_VERSION, "observation_days": OBSERVATION},
                   "cutoffs": [Z(c) for c in CUTOFFS], "immature_cutoffs": [Z(c) for c in CUTOFFS if c + days(HORIZON + GRACE) > AS_OF], "training_run_id": RUN_ID,
                   "scoring": {"backtest_scored_at": Z(SCORE_BACKTEST_AT), "production_scored_at": Z(SCORE_PRODUCTION_AT), "run_frozen_at": Z(RUN_FROZEN_AT)}},
        "generator": {"name": "generate.py", "seed": seed, "parameters": generator_parameters(B)},
        "disclosures": [disclosure_entry(d) for d in disclosures(B)],
        "row_counts": {**{n: len(ents_c[n]) for n in ENTITIES}, "test_cohort": len(B["test_table"]["rows"]), "cutoff_aggregates": len(B["aggregates"])},
        "designed_relationships": designed, "injection_manifest": "injection-manifest.json",
        "published_cohort": {"accounts": len(ents_c["accounts"]), "sampling": f"uniform sample of {COHORT_N} of {N_ACCOUNTS} accounts by seeded draw; every record of each sampled account is published",
                             "account_ids": pop["cohort"], "claims": B["claims"], "economics": {k: {x: y for x, y in v.items() if x != "account_ids"} for k, v in coh["economics"].items()},
                             "economics_population": f"{coh['economics']['sc-001']['population']} scored accounts of the published cohort (not the population; see economics_full_world)",
                             "queue_prediction_at": coh["queue_at"], "queue_account_ids": {k: v["account_ids"] for k, v in coh["economics"].items()}},
        "population": population_stats(B), "training": training_summary(B), "economics_full_world": B["economics_full_world"],
        "stats": {"data_file_bytes_without_manifest": sum(len(t.encode()) for t in files.values()), "size_cap_bytes": SIZE_CAP_BYTES, "size_cap_binding": True},
        "synthetic_truth": {"note": NOTE_TRUTH, "latent_churn_propensity_ppm": latent,
                            "latent_reference_test": B["dr"]["models"]["latent_propensity_reference"],
                            "roles": {"train": sum(1 for a in pop["accounts"] if a["primary"] == "train"), "validation": sum(1 for a in pop["accounts"] if a["primary"] == "validation"),
                                      "test": sum(1 for a in pop["accounts"] if a["primary"] == "test")},
                            "violators": pop["violators"], "hidden_risk_accounts": sum(1 for a in pop["accounts"] if a["hidden"]),
                            "unobserved_designs": {"starter_repricing": {"segment": PRICE_SEGMENT, "from": Z(PRICE_CHANGE_AT), "hazard_uplift_milli_logit": PRICE_UPLIFT},
                                                   "instrumentation": {"region": DRIFT_REGION, "from": Z(DRIFT_AT), "logins_kept_ppm": DRIFT_KEEP_PPM}}}}
    manifest_text = pretty(manifest)
    out.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out / name).write_text(text)
    (out / "manifest.json").write_text(manifest_text)
    (data_dir / "injection-events.json").write_text(files["injection-events.json"])
    all_bytes = sum(p.stat().st_size for p in out.glob("*.json"))
    if all_bytes >= SIZE_CAP_BYTES:
        raise AssertionError(f"published data is {all_bytes} bytes, the cap is {SIZE_CAP_BYTES}")
    if inputs_path is not None:
        full = {**B["data"], "feature_rows": feature_and_label_rows(rows)[0], "labels": feature_and_label_rows(rows)[1], "training_runs": [fit["run"]],
                "split_assignments": [{"assignment_id": f"sa-{RUN_ID}-{r['cutoff_id']}", "training_run_id": RUN_ID, "cutoff_id": r["cutoff_id"], "split": r["split"], "status": r["status"],
                                      "drop_reason": r["drop_reason"]} for r in fit["split_rows"]],
                "predictions": B["preds"], "scoring_publications": B["pubs"], "intervention_scenarios": SCENARIOS, "outreach_events": []}
        inputs_path.write_text(json.dumps(full, sort_keys=True))
    manifest["_bytes"] = all_bytes
    manifest["_elapsed_seconds"] = round(time.perf_counter() - t0, 1)
    return manifest


def designed_relationships(B: dict[str, Any]) -> list[dict[str, Any]]:
    dr = B["dr"]
    m, c, d, la, ce = dr["models"], dr["calibration"], dr["drift"], dr["late"], dr["censored"]
    return [
        {"id": "DR-01", "name": "the logistic model beats the rule and the random baseline",
         "statement": ("On the test range (the cutoffs 2026-02-01 .. 2026-05-01, mature eligible rows with a prediction, as one evaluation population) the logistic regression's average "
                       f"precision exceeds the rule's by at least {MARGINS['ap_over_rule']} and the random baseline's by at least {MARGINS['ap_over_random']}, and its Brier score is lower "
                       f"than the rule's by at least {MARGINS['brier_under_rule']} and the random baseline's by at least {MARGINS['brier_under_random']}."),
         "realised": {k: m[k] for k in ("logistic_regression", "business_rule", "random_baseline", "prevalence_baseline", "margins", "stated_margins", "met", "reference_margins",
                                       "uninformative_margin")}, "met": all(m["met"].values())},
        {"id": "DR-02", "name": "a segment with a calibration gap",
         "statement": (f"The {PRICE_SEGMENT} segment's mean predicted churn on the test range is at least {TARGETS['calibration_gap_pp']} percentage points below its observed churn "
                       f"(an unobserved repricing from {Z(PRICE_CHANGE_AT)} that no feature sees); the gap is mean predicted minus observed."),
         "realised": {"segment": c["segment_with_gap"], "by_segment": c["by_segment"], "overall": c["overall"], "uncalibrated_overall": c["uncalibrated_overall"],
                      "largest_other_segment_abs_gap_pp": c["largest_other_segment_abs_gap_pp"], "by_region": c["by_region"], "largest_region_gap": c["largest_region_gap"],
                      "platt_effect": c["platt_effect"]}, "met": c["met"]},
        {"id": "DR-03", "name": "a cohort with population drift after 2026-03",
         "statement": (f"From the 2026-05-01 cutoff the usage_events_30d distribution of the {DRIFT_REGION} region has a PSI above {TARGETS['drift_psi']} against its "
                       f"{d['reference_prediction_at']} cohort ({100 - DRIFT_KEEP_PPM // 10_000} % of logins are not recorded from {Z(DRIFT_AT)}), while the other regions stay below it. "
                       "The PSI is a diagnostic (threshold 0.2), not proof."),
         "realised": {"region": d["region"], "change_at": d["change_at"], "reference_prediction_at": d["reference_prediction_at"], "before_change_psi": d["before_change_psi"],
                      "after_change_psi": d["after_change_psi"], "series": "cutoff_aggregates.json drift.by_cutoff"}, "met": d["met"]},
        {"id": "DR-04", "name": "late arrivals that would flip features if ignored",
         "statement": (f"Ignoring available_at would change at least one feature on at least {TARGETS['late_rows_changed_share']} of the test rows and change at least "
                       f"{TARGETS['late_features_flipped']} of the four features on at least one row each; cancellations that arrive after the label grace are not churn."),
         "realised": {k: la[k] for k in ("test_rows", "test_rows_with_a_late_event", "test_rows_features_change_if_ignored", "share_of_test_rows_changed", "features_flipped",
                                        "rule_flag_flips", "mature_test_labels_flipped", "declared", "realised", "subscription_events_arriving_after_the_grace")}, "met": la["met"]},
        {"id": "DR-05", "name": "a sizeable censored tail",
         "statement": f"At least {TARGETS['censored_share']} of the eligible rows are censored at as_of (the last three cutoffs have label windows that close after 2026-10-05).",
         "realised": {k: ce[k] for k in ("eligible_rows", "censored_rows", "censored_share", "mature_churn_rate", "immature_cutoffs", "churn_rate_if_censored_were_non_churn")}, "met": ce["met"]}]


def generator_parameters(B: dict[str, Any]) -> dict[str, str]:
    return {"accounts": str(N_ACCOUNTS), "creation_months": "2024-01 .. 2026-06 (weights 50 + 2m)", "segments": canon({k: v[0] for k, v in SEGMENTS.items()}),
            "regions": canon(REGIONS), "cutoffs": "21 monthly, 2025-01-01 .. 2026-09-01", "horizon_days": str(HORIZON), "grace_days": str(GRACE), "observation_days": str(OBSERVATION),
            "as_of": Z(AS_OF), "split": f"train < {Z(TRAIN_END)} <= validation < {Z(VALIDATION_END)} <= test < {Z(TEST_END)}", "role_share_percent": canon(list(GROUP_SHARE)),
            "week_grid_start": Z(T0), "hazard": "weekly logistic hazard of the latent state; intercepts " + canon({k: v[3] for k, v in SEGMENTS.items()}) + " milli-logit",
            "engagement_coefficient_milli": str(ENGAGEMENT_COEF), "annual_hazard_adjustment_milli": str(ANNUAL_HAZARD_ADJ), "hidden_risk": f"{HIDDEN_PPM} ppm of accounts, +{HIDDEN_ADJ} milli-logit",
            "incident_ppm_per_week": str(INCIDENT_PPM), "usage_rate_milli_per_week": canon({k: v[2] for k, v in SEGMENTS.items()}), "monthly_billed_ppm": canon({k: v[4] for k, v in SEGMENTS.items()}),
            "late_arrival": canon({e: {"ppm": v[0], "days": list(v[1])} for e, v in LATE.items()}),
            "cancel_late": f"{CANCEL_LATE_PPM} ppm {CANCEL_LATE_DAYS} days; {CANCEL_VERY_LATE_PPM} ppm {CANCEL_VERY_LATE_DAYS} days", "starter_repricing": f"+{PRICE_UPLIFT} milli-logit from {Z(PRICE_CHANGE_AT)}",
            "instrumentation_change": f"{DRIFT_REGION} from {Z(DRIFT_AT)}, {DRIFT_KEEP_PPM} ppm of usage events recorded", "cohort_accounts": str(COHORT_N), "violators_in_out_of_cohort": canon(VIOLATORS),
            "inj02_examples": str(INJ02_EXAMPLES), "inj07_examples": str(INJ07_EXAMPLES), "margins": canon(MARGINS), "targets": canon(TARGETS), "scenarios": canon(CAP_K),
            "model_seed": str(MODEL_SEED), "size_cap_bytes": str(SIZE_CAP_BYTES)}


def population_stats(B: dict[str, Any]) -> dict[str, Any]:
    pop, rows, ents = B["pop"], B["rows"], B["ents"]
    accts = pop["accounts"]
    by_range: dict[str, dict[str, int]] = {}
    for a in rows.values():
        d = by_range.setdefault(range_of(parse_ts(a["prediction_at"])), {"cutoff_rows": 0, "eligible": 0, "ineligible": 0, "mature": 0, "censored": 0, "churned": 0})
        d["cutoff_rows"] += 1
        if a["eligible"]:
            d["eligible"] += 1
            d["mature" if a["mature"] else "censored"] += 1
            d["churned"] += 1 if a["churned"] else 0
        else:
            d["ineligible"] += 1
    for d in by_range.values():
        d["churn_rate"] = p6(ratio(d["churned"], d["mature"]))
    return {"accounts": len(accts), "accounts_with_a_cancellation": sum(1 for s in ents["subscription_events"] if s["event_type"] == "cancel"),
            "by_segment": {s: sum(1 for a in accts if a["segment"] == s) for s in SEGMENT_NAMES}, "by_region": {r: sum(1 for a in accts if a["region"] == r) for r in REGION_NAMES},
            "monthly_billed_accounts": sum(1 for a in accts if a["monthly"]), "events": {e: len(ents[e]) for e in EVENT_ENTITIES}, "cutoff_rows": len(ents["prediction_cutoffs"]),
            "by_range": dict(sorted(by_range.items())), "feature_rows": sum(1 for a in rows.values() if a["eligible"]), "predictions": len(B["preds"]), "scoring_publications": len(B["pubs"]),
            "immature_rows_excluded_from_every_metric": sum(1 for a in rows.values() if a["eligible"] and not a["mature"])}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=APP_ROOT / "web" / "public" / "data")
    ap.add_argument("--data-dir", type=Path, default=APP_ROOT / "data")
    ap.add_argument("--inputs", type=Path, help="also write the FULL population as one inputs object for data/seed.py to this path (not committed)")
    args = ap.parse_args(argv)
    m = write_all(args.seed, args.out, args.data_dir, args.inputs)
    print(json.dumps({"dataset_version": m["dataset_version"], "dataset_hash": m["dataset_hash"], "row_counts": m["row_counts"], "bytes": m["_bytes"],
                      "elapsed_seconds": m["_elapsed_seconds"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
