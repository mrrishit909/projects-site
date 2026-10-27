#!/usr/bin/env python3
"""ChangeWorks synthetic data generator (P09-WORK-03, docs/data-generator.md, demo profile of section 12).

Standard library plus the domain (``domain/changeworks``, itself standard library only). A master ``random.Random(seed)`` hands one child stream to
each purpose; every probability is parts per million, every draw is ``randrange``; money is integer cents, proportions integer micro-units, instants
``datetime`` arithmetic on UTC; no float is written or used to decide anything. Same seed, same bytes (PYTHONHASHSEED 0/1/2).

Every figure in the manifest and the injection manifest is computed by the domain (``run_pipeline`` and ``Validator``) over the finished world, never
typed. The synthetic counterfactual (the true share of an observed improvement that the rollout caused) lives only in the manifest.

    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --inputs /tmp/inputs.json      # one inputs object for data/seed.py (not committed)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT / "domain") not in sys.path:
    sys.path.insert(0, str(APP_ROOT / "domain"))
from changeworks import run_pipeline  # noqa: E402
from changeworks.contract import ENTITIES as DOMAIN_ENTITIES  # noqa: E402
from changeworks.ingest import Validator, validate_batch  # noqa: E402

UTC = timezone.utc
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
VERSION_TAG = "cw"
CONTRACT_VERSION = "v1"
AS_OF = datetime(2026, 10, 5, tzinfo=UTC)
AS_OF_TEXT = "2026-10-05T00:00:00Z"
PERIODS = 36
CONFIG = {"contract_version": 1, "as_of": AS_OF_TEXT, "period_basis": "monthly", "period_start": "2026-01-01"}
MATURED = 9                                            # periods 0..8 end on or before 2026-10-05 (period 8 = September 2026)
ENTITIES = tuple(sorted(DOMAIN_ENTITIES))
PURPOSES = ("programmes", "baselines", "assumptions", "benefits", "costs", "scenarios", "roadmap", "people", "adoption", "observations", "risks",
            "forecasts", "injections")
SIZE_CAP = 5_000_000

# ---- targets (the brief; the counts below are exact) ----------------------------------------------------------------------------------------
TARGET = {"assumption_versions": 160, "cost_items": 900, "benefit_items": 700, "dependencies": 40, "resources": 8, "stakeholder_groups": 60,
          "readiness_assessments": 300, "adoption_observations": 500, "training_completions": 200, "benefit_observations": 400, "risk_items": 120,
          "scenario_versions": 30, "process_baselines": 30, "initiatives": 24}
BENEFIT_LIFE = 12                                      # rows per benefit stream (a twelve-period recognition window), shortened where the horizon ends first
SHARE_ABOVE_TREND = 85                                 # DR-06: per cent of the observed improvement that the recorded baseline trend explains
FORECAST_MISS_TOLERANCE_PCT = 10                       # a forecast is "missed" when the observed value is more than 10 % below it
D4_PERF = (68, 66)                                     # DR-04: observed / planned, per cent, before the first and before the second revision
D4_REVISION = (80, 70)                                 # the revised forecasts are 80 % and 70 % of the plan for the periods they still cover


# ---- small exact helpers --------------------------------------------------------------------------------------------------------------------
def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def pdate(p: int) -> date:
    m = p
    return date(2026 + m // 12, m % 12 + 1, 1)


def at(d: date, h: int = 9, mi: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, mi, tzinfo=UTC)


def cents(n: int) -> str:
    assert n >= 0, n
    return f"{n // 100}.{n % 100:02d}"


def micro(n: int) -> str:
    assert 0 <= n <= 1_000_000, n
    return f"{n // 1_000_000}.{n % 1_000_000:06d}"


def chance(r: random.Random, ppm: int) -> bool:
    return r.randrange(1_000_000) < ppm


def ri(r: random.Random, a: int, b: int) -> int:
    return a + r.randrange(b - a + 1)


def pick(r: random.Random, seq: Any) -> Any:
    return seq[r.randrange(len(seq))]


def rdiv(a: int, b: int) -> int:
    """a / b rounded half up for non-negative integers."""
    return (2 * a + b) // (2 * b)


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def rhu(x: Fraction, places: int) -> str:
    neg = x < 0
    n = abs(x) * 10 ** places
    q = (2 * n.numerator + n.denominator) // (2 * n.denominator)
    s = f"{q // 10 ** places}.{q % 10 ** places:0{places}d}" if places else str(q)
    return "-" + s if neg and q else s


def twelfth_root_rate_micro(annual_micro: int) -> int:
    """(1 + r)^(1/12) - 1 rounded to 6 places, by exact rational comparison (no float): the nearest micro-unit x with (1 + x)^12 = 1 + r."""
    target = Fraction(1_000_000 + annual_micro, 1_000_000)
    lo, hi = 0, annual_micro
    while lo < hi:                                      # the largest x with (1 + x)^12 <= target
        mid = (lo + hi + 1) // 2
        if Fraction(1_000_000 + mid, 1_000_000) ** 12 <= target:
            lo = mid
        else:
            hi = mid - 1
    half = Fraction(2_000_000 + 2 * lo + 1, 2_000_000)
    return lo + 1 if half ** 12 <= target else lo


# ---- the register ---------------------------------------------------------------------------------------------------------------------------
PROGRAMMES = [  # id, name, sponsor, baseline version the programme's initiatives have approved (None: no baseline yet)
    ("prog-fin", "Finance Operations Renewal", "sp-cfo", "v2"),
    ("prog-cust", "Customer Service Transformation", "sp-coo", "v2"),
    ("prog-supply", "Supply Chain Digitisation", "sp-cscm", "v1"),
    ("prog-work", "Workplace and Technology Modernisation", "sp-cio", None)]

# n, title, programme index, status, requested start, duration, deployment, eligibility rule, one-time cost k$, recurring k$ per period,
# benefit-to-cost ratio in permille (money benefits that enter the cash flow / total cost, over the recognition window), ramp length
# streams: (name, class, mode, share of the cash-flow benefit, lag).  mode: "" plain | "realised" avoided cost removed from a budget line (evidence) |
# "beside" avoided cost not realised | "noevid" says realised but cites nothing | "shared" the capacity both D2 initiatives claim
INI = [
    (1, "Invoice-to-pay automation", 0, "adopted", 0, 4, 1, "elig-v1", 900, 18, 1500, 5,
     [("late-fee-avoidance", "avoided_cost", "realised", 40, 0), ("early-payment-discounts", "cash", "", 60, 1), ("ap-team-time", "capacity", "shared", 0, 0)]),
    (2, "Automated bank reconciliation", 0, "adopted", 0, 5, 2, "elig-v1", 650, 12, 1450, 5,
     [("bank-fee-reduction", "cash", "", 100, 0), ("audit-fee-avoidance", "avoided_cost", "beside", 0, 1), ("ap-team-time", "capacity", "shared", 0, 1)]),
    (3, "Expense report straight-through processing", 0, "in_delivery", 1, 6, 3, "elig-v1", 500, 10, 1350, 6,
     [("card-rebates-and-recoveries", "cash", "", 100, 0), ("travel-policy-savings", "avoided_cost", "noevid", 0, 1), ("review-time", "capacity", "", 0, 1)]),
    (4, "Month-end close orchestration", 0, "in_delivery", 2, 7, 4, "elig-v1", 1100, 22, 1250, 6,
     [("temp-staffing-line", "avoided_cost", "realised", 55, 0), ("close-interest-income", "cash", "", 45, 1), ("close-effort", "capacity", "", 0, 1)]),
    (5, "Credit-control workflow", 0, "assessed", 8, 6, 10, "elig-v1", 700, 14, 1300, 5,
     [("overdue-balance-release", "cash", "", 100, 0), ("collector-time", "capacity", "", 0, 1)]),
    (6, "Supplier onboarding portal", 0, "candidate", 12, 6, 15, "elig-v1", 450, 9, 1200, 5,
     [("onboarding-cost-avoided", "avoided_cost", "beside", 0, 0), ("onboarding-effort", "capacity", "", 0, 1)]),
    (7, "Claims intake digitisation", 1, "closed", 0, 3, 1, "elig-v1", 1500, 30, 1400, 6,
     [("faster-settlement-retention", "revenue", "", 70, 0), ("leakage-avoidance", "avoided_cost", "beside", 0, 1), ("intake-time", "capacity", "", 0, 1)]),
    (8, "Knowledge-assisted contact handling", 1, "adopted", 0, 4, 2, "elig-v2", 800, 16, 1300, 5,
     [("overtime-reduction", "cash", "", 60, 0), ("repeat-contact-revenue", "revenue", "", 40, 1), ("handling-time", "capacity", "", 0, 1)]),
    (9, "Complaint triage routing", 1, "in_delivery", 1, 6, 3, "elig-v1", 600, 12, 0, 5,
     [("triage-time", "capacity", "", 0, 0)]),
    (10, "Customer onboarding verification", 1, "in_delivery", 3, 6, 9, "elig-v1", 1200, 24, 1350, 6,
     [("conversion-uplift", "revenue", "", 100, 0), ("manual-review-avoidance", "avoided_cost", "beside", 0, 1), ("verification-time", "capacity", "", 0, 1)]),
    (11, "Self-service address changes", 1, "assessed", 9, 5, 12, "elig-v1", 350, 7, 1250, 4,
     [("contact-volume-saving", "cash", "", 100, 0), ("agent-time", "capacity", "", 0, 1)]),
    (12, "Returns and refunds workflow", 1, "candidate", 14, 6, 17, "elig-v1", 750, 15, 1200, 5,
     [("recovered-refund-revenue", "revenue", "", 100, 0), ("refund-leakage", "avoided_cost", "beside", 0, 1), ("refund-handling-time", "capacity", "", 0, 1)]),
    (13, "Demand-planning consolidation", 2, "adopted", 0, 4, 1, "elig-v2", 1300, 26, 1500, 6,
     [("carrying-cost-reduction", "cash", "", 65, 0), ("expedite-freight-line", "avoided_cost", "realised", 35, 1), ("planner-time", "capacity", "", 0, 1)]),
    (14, "Warehouse slotting optimisation", 2, "in_delivery", 3, 6, 5, "elig-v1", 950, 19, 1300, 5,
     [("outsourced-picking-fees", "cash", "", 100, 0), ("overtime-avoidance", "avoided_cost", "beside", 0, 1), ("picker-time", "capacity", "", 0, 1)]),
    (15, "Carrier booking automation", 2, "in_delivery", 2, 6, 4, "elig-v1", 900, 28, 620, 5,
     [("carrier-fee-savings", "cash", "", 100, 0), ("rework-avoidance", "avoided_cost", "beside", 0, 1), ("booking-time", "capacity", "", 0, 1)]),
    (16, "Purchase-order approval redesign", 2, "in_delivery", 4, 7, 6, "elig-v1", 600, 12, 1300, 5,
     [("maverick-spend-reduction", "cash", "", 55, 0), ("duplicate-order-line", "avoided_cost", "realised", 45, 1), ("approver-time", "capacity", "", 0, 1)]),
    (17, "Supplier quality scorecards", 2, "assessed", 10, 6, 13, "elig-v1", 400, 8, 1250, 5,
     [("warranty-claims-line", "avoided_cost", "realised", 100, 0), ("quality-review-time", "capacity", "", 0, 1)]),
    (18, "Inventory count automation", 2, "candidate", 15, 6, 18, "elig-v1", 500, 10, 1200, 5,
     [("write-off-reduction", "cash", "", 100, 0)]),
    (19, "HR case management", 3, "assessed", 9, 7, 14, "elig-v1", 850, 17, 1250, 5,
     [("case-handling-time", "capacity", "", 0, 0), ("external-counsel-avoidance", "avoided_cost", "beside", 0, 1)]),
    (20, "Employee onboarding workflow", 3, "assessed", 12, 8, 16, "elig-v1", 700, 14, 1200, 5,
     [("onboarding-effort", "capacity", "", 0, 0), ("equipment-lead-time-saving", "cash", "", 100, 1)]),
    (21, "Meeting-room and desk booking", 3, "candidate", 16, 6, 19, "elig-v1", 300, 6, 1150, 4,
     [("space-cost-avoided", "avoided_cost", "beside", 0, 0), ("booking-admin-time", "capacity", "", 0, 1)]),
    (22, "IT service desk deflection", 3, "candidate", 18, 6, 24, "elig-v1", 550, 11, 1200, 5,
     [("deflected-ticket-time", "capacity", "", 0, 0), ("vendor-support-fees", "cash", "", 100, 1)]),
    (23, "Data platform consolidation", 3, "in_delivery", 6, 12, 12, "elig-v1", 2400, 45, 1250, 6,
     [("licence-consolidation", "avoided_cost", "realised", 60, 0), ("hosting-savings", "cash", "", 40, 1)]),
    (24, "Identity and access automation", 3, "in_delivery", 7, 8, 11, "elig-v1", 1000, 20, 1250, 5,
     [("access-review-effort-line", "cash", "", 100, 0), ("audit-finding-avoidance", "avoided_cost", "noevid", 0, 1), ("provisioning-time", "capacity", "", 0, 1)]),
]
SPONSOR_OVERRIDE = {9: "sp-cx", 23: "sp-cdo", 13: "sp-cscm", 24: "sp-ciso"}
SHARED_CAP_KEY = "src-fin-ap-shared-team"               # D2: the one released capacity two initiatives claim
D1, D2A, D2B, D3, D4, D6 = 9, 1, 2, 15, 3, 8            # the initiatives of the designed relationships
FORECAST_SET = {3: 3, 13: 2, 4: 2, 1: 1, 2: 1, 8: 1, 14: 1, 16: 1}      # initiative -> forecast versions (12 in all)
TRAINING_INI = (1, 2, 3, 4, 5, 7, 8, 9, 10, 13, 14, 15, 16, 23, 24)
ADOPTION_INI = (1, 2, 3, 4, 7, 8, 9, 13, 14, 15, 16)
D5_RESOURCE = "res-03"
D5_PERIODS = (14, 15, 16)

SYSTEMS = {1: "ap-ledger", 2: "treasury", 3: "expense", 4: "gl-close", 5: "ar-ledger", 6: "vendor-master", 7: "claims", 8: "contact-centre", 9: "complaints",
           10: "crm", 11: "crm", 12: "returns", 13: "planning", 14: "wms", 15: "tms", 16: "procurement", 17: "supplier-master", 18: "stock",
           19: "hr-cases", 20: "hris", 21: "facilities", 22: "service-desk", 23: "platform", 24: "iam"}
BASELINE_DRIFT = {1: "invoice volume restated after the ledger migration", 2: "bank statement lines recounted with the new feeds",
                  3: "expense claims recounted with card feeds included", 4: "close tasks recounted per entity", 5: "dunning cases recounted",
                  6: "onboarding requests recounted", 7: "claims volume restated after the portal launch", 8: "contacts recounted with chat included",
                  9: "complaints recounted with social channels", 10: "applications recounted", 11: "change requests recounted", 12: "returns recounted"}

RESOURCES = [  # id, name, capacity, unit
    ("res-01", "Process analyst pool", "6.00", "FTE"), ("res-02", "Change manager pool", "3.00", "FTE"),
    (D5_RESOURCE, "Data migration specialist", "2.00", "FTE"), ("res-04", "Integration engineer pool", "4.00", "FTE"),
    ("res-05", "Training developer pool", "2.50", "FTE"), ("res-06", "Finance subject-matter expert", "2.00", "FTE"),
    ("res-07", "Operations subject-matter expert", "3.00", "FTE"), ("res-08", "Test lead", "2.00", "FTE")]
RES_FOR = {"res-01": range(1, 25), "res-02": range(1, 25), "res-04": (1, 2, 3, 4, 7, 8, 10, 13, 14, 15, 16, 19, 20, 22, 23, 24),
           "res-05": (1, 2, 3, 4, 7, 8, 9, 10, 13, 14, 15, 16), "res-06": (1, 2, 3, 4, 5, 6, 17, 18, 23),
           "res-07": (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18), "res-08": (1, 3, 4, 8, 10, 14, 16, 23, 24, 19, 20)}

ROLES = [("Accounts payable clerks", 1), ("Treasury analysts", 2), ("Expense approvers", 3), ("Finance controllers", 4), ("Credit controllers", 5),
         ("Procurement buyers", 6), ("Claims handlers", 7), ("Contact-centre agents", 8), ("Complaint specialists", 9), ("Onboarding officers", 10),
         ("Customer service leads", 11), ("Refund processors", 12), ("Demand planners", 13), ("Warehouse pickers", 14), ("Transport coordinators", 15),
         ("Purchasing approvers", 16), ("Supplier quality engineers", 17), ("Stock controllers", 18), ("HR business partners", 19), ("Hiring managers", 20),
         ("Facilities coordinators", 21), ("Service desk analysts", 22), ("Platform engineers", 23), ("Security administrators", 24)]
MODIFIERS = ["North region", "South region", "Shared services"]
CHANGES = {
    1: "Invoices are matched by the system; clerks resolve exceptions only", 2: "Statement lines are reconciled automatically; analysts review breaks",
    3: "Claims under the policy limit are approved without review", 4: "Close tasks are scheduled and tracked in one workflow",
    5: "Dunning steps run from the workflow; controllers handle disputes", 6: "Suppliers register themselves; buyers approve exceptions",
    7: "Claims are captured digitally at intake; handlers work the exception queue", 8: "Agents answer from one knowledge surface instead of three",
    9: "Complaints are routed by category and urgency, not by who is free", 10: "Identity checks run before the officer sees the application",
    11: "Customers change their own address; agents see an audit trail", 12: "Refund decisions follow one rule set; leads review overrides",
    13: "Planners work from one demand signal and one forecast", 14: "Pickers follow slotting rules reviewed monthly", 15: "Carrier bookings are placed and confirmed automatically",
    16: "Approvals follow value bands and a single path", 17: "Supplier scorecards replace ad hoc quality reviews", 18: "Counts are scheduled and reconciled by the system",
    19: "Cases are opened, assigned and closed in one record", 20: "Joiners receive a checklist-driven onboarding", 21: "Desks and rooms are booked in one place",
    22: "Common requests are answered before they reach the desk", 23: "Teams share one data platform and one access model", 24: "Access requests and reviews run automatically"}
MITIGATIONS = ["Parallel run for one cycle", "Phased rollout by site", "Dedicated hypercare team for six weeks", "Vendor penalty clause on delivery dates",
               "Weekly steering review of the benefit register", "Fallback to the manual procedure for 30 days", "Named super-user in every team",
               "Data reconciliation before every cut-over", "Training completion gate before go-live", "Contract price cap for two years"]
RISK_TITLES = ["Integration delay", "Low adoption", "Data quality below plan", "Vendor delivery slip", "Key specialist unavailable", "Scope growth"]
OTHER_ASSUMPTIONS = [("volume_growth", "per period", "Annual volume growth carried into the plan"), ("price_escalation", "per year", "Vendor price escalation"),
                     ("attrition_rate", "per year", "Staff attrition used to size natural capacity release"), ("benefit_confidence", "proportion", "Confidence in the benefit estimate"),
                     ("contingency_rate", "proportion", "Contingency held against the one-time costs")]
AUTHORS = ["an-01", "an-02", "an-03", "an-04", "an-05", "an-06"]
EVIDENCE_SYSTEM = {"cash": "ledger", "revenue": "billing", "avoided_cost": "budget", "capacity": "timesheet"}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# the world
# ---------------------------------------------------------------------------------------------------------------------------------------------
class World:
    def __init__(self, seed: int):
        self.seed = seed
        master = random.Random(seed)
        self.rs = {p: random.Random(master.getrandbits(64)) for p in PURPOSES}
        self.pad_notes: dict[str, Any] = {}
        self.truth: dict[str, Any] = {}

    # ---- initiatives, baselines ------------------------------------------------------------------------------------------------------------
    def build_initiatives(self) -> None:
        self.t = {}                                   # n -> the table row as a dict
        self.initiatives: list[dict] = []
        for (n, title, pi, status, start, dur, dep, elig, ot, rec, ratio, rampn, streams) in INI:
            self.t[n] = dict(n=n, title=title, pi=pi, status=status, start=start, dur=dur, dep=dep, elig=elig, ot=ot, rec=rec, ratio=ratio, rampn=rampn, streams=streams)
            self.initiatives.append({"initiative_id": f"init-{n:03d}", "title": title, "sponsor_id": SPONSOR_OVERRIDE.get(n, PROGRAMMES[pi][2]), "status": status,
                                     "baseline_version": PROGRAMMES[pi][3], "requested_start_period": start, "duration_periods": dur, "deployment_period": dep,
                                     "eligibility_rule_version": elig})

    def iid(self, n: int) -> str:
        return f"init-{n:03d}"

    def build_baselines(self) -> None:
        r = self.rs["baselines"]
        self.baselines: list[dict] = []
        self.base = {}                                # n -> (volume, minutes_per_case) of the approved version
        for n in sorted(self.t):
            pi = self.t[n]["pi"]
            if PROGRAMMES[pi][3] is None:
                continue
            vol, mpc, err = ri(r, 1800, 9500), ri(r, 9, 38), ri(r, 25_000, 110_000)
            if n == D2B:                                  # the second claimant of the shared pool is sized like the first, so the overlap matters
                vol, mpc = max(vol, 8000), max(mpc, 24)
            system = SYSTEMS[n]
            self.baselines.append({"baseline_id": f"pb-{n:03d}-v1", "initiative_id": self.iid(n), "baseline_version": "v1", "volume": vol, "minutes_per_case": mpc,
                                   "error_rate": micro(err), "evidence_ref": f"ev:{system}-timesheet-2025", "measured_at": ts(at(date(2025, ri(r, 10, 12), ri(r, 1, 28)), 0)),
                                   "reason": None})
            self.base[n] = (vol, mpc)
            if PROGRAMMES[pi][3] == "v2":
                vol2, mpc2 = vol * ri(r, 86, 118) // 100, max(6, mpc + ri(r, -3, 3))
                err2 = max(10_000, err + ri(r, -12_000, 12_000))
                self.baselines.append({"baseline_id": f"pb-{n:03d}-v2", "initiative_id": self.iid(n), "baseline_version": "v2", "volume": vol2, "minutes_per_case": mpc2,
                                       "error_rate": micro(err2), "evidence_ref": f"ev:{system}-recount-2026", "measured_at": ts(at(date(2026, ri(r, 2, 3), ri(r, 1, 28)), 0)),
                                       "reason": "Correction: " + BASELINE_DRIFT[n]})
                self.base[n] = (vol2, mpc2)

    # ---- assumptions -----------------------------------------------------------------------------------------------------------------------
    def build_assumptions(self) -> None:
        r = self.rs["assumptions"]
        self.assumptions: list[dict] = []
        self.ramp_vals: dict[int, list[int]] = {}       # n -> latest ramp (micro-units)
        self.target10: dict[int, int] = {}              # n -> latest target in tenths of a minute
        self.conv_rate: dict[int, int] = {}             # n -> latest hourly rate in cents (only with staffing evidence)
        self.has_conv = (1, 2, 3, 4, 7, 13)
        self.asm_ids: dict[tuple[int, str], list[tuple[str, datetime]]] = {}

        def add(n: int | None, name: str, v: int, value: str | None, values: list[str] | None, unit: str, why: str, created: datetime,
                evidence: str | None = None, staff: str | None = None, author: str | None = None) -> str:
            tag = "conv" if n is None else f"{n:03d}"
            aid = f"a-{tag}-{name[:6].replace('_', '')}-{v}"
            self.assumptions.append({"assumption_id": aid, "initiative_id": None if n is None else self.iid(n), "name": name, "version_number": v, "value": value,
                                     "values": values, "unit": unit, "rationale": why, "author_id": author or pick(r, AUTHORS), "evidence_ref": evidence,
                                     "staffing_change_evidence_ref": staff, "created_at": ts(created)})
            if n is not None:
                self.asm_ids.setdefault((n, name), []).append((aid, created))
            return aid

        def tri(k: int) -> list[int]:                      # triangular ramp: (j+1)(j+2) / (k(k+1)), non-decreasing, ends at 1
            return [rdiv((j + 1) * (j + 2) * 1_000_000, k * (k + 1)) for j in range(k)]

        for n in sorted(self.t):
            t = self.t[n]
            c1 = at(date(2026, 1, ri(r, 5, 20)), ri(r, 8, 16))
            v1 = tri(t["rampn"])
            add(n, "adoption_ramp", 1, None, [micro(x) for x in v1], "fraction of the planned benefit", f"Planned adoption over {t['rampn']} periods from the first benefit period", c1)
            self.ramp_vals[n] = v1
            if n in ADOPTION_INI:
                v2 = tri(t["rampn"] + 2)
                add(n, "adoption_ramp", 2, None, [micro(x) for x in v2], "fraction of the planned benefit",
                    f"Slower ramp after the first months of adoption data ({t['rampn'] + 2} periods)", at(date(2026, ri(r, 6, 7), ri(r, 2, 26)), 11))
                self.ramp_vals[n] = v2
            if n in self.base:
                vol, mpc = self.base[n]
                f1 = ri(r, 38, 66)
                t1 = max(10, mpc * 10 * f1 // 100)
                add(n, "target_minutes_per_case", 1, f"{t1 // 10}.{t1 % 10}", None, "minutes", f"Target from the pilot team's observed handling time at {f1} % of baseline", c1 + timedelta(days=1))
                self.target10[n] = t1
                if n in ADOPTION_INI:
                    t2 = min(mpc * 10 - 5, t1 + mpc * 10 * ri(r, 4, 9) // 100)
                    add(n, "target_minutes_per_case", 2, f"{t2 // 10}.{t2 % 10}", None, "minutes", "Target revised upward after the first months of operation", at(date(2026, ri(r, 5, 7), ri(r, 2, 26)), 12))
                    self.target10[n] = t2
            if n in self.has_conv:
                rate = ri(r, 2800, 4600)
                add(n, "capacity_hourly_rate", 1, cents(rate), None, "USD per hour", "Loaded hourly cost proposed by finance; no staffing change agreed yet", c1 + timedelta(days=2))
                add(n, "capacity_hourly_rate", 2, cents(rate), None, "USD per hour", "Same rate; HR confirmed the staffing change that releases the budget line",
                    at(date(2026, 5, ri(r, 4, 28)), 10), staff=f"ev:hr-headcount-plan-{SYSTEMS[n]}-2026")
                self.conv_rate[n] = rate
        for k, annual in enumerate((60_000, 80_000, 100_000, 120_000), start=1):
            m = twelfth_root_rate_micro(annual)
            add(None, "monthly_rate_conversion", k, micro(m), None, "per period", f"Monthly equivalent of an annual rate of {micro(annual)}: (1 + {micro(annual)})^(1/12) - 1, rounded to six places",
                at(date(2026, 1, 8 + k), 9), author="an-02")
        self.conv_ids = {annual: f"a-conv-monthl-{k}" for k, annual in enumerate((60_000, 80_000, 100_000, 120_000), start=1)}
        self._add_other = add
        self._r_asm = r

    def pad_assumptions(self) -> None:
        """Other named assumptions (growth, escalation, attrition, confidence, contingency) up to the brief's count; the draws come after everything else."""
        need = TARGET["assumption_versions"] - len(self.assumptions)
        assert need >= 0, f"already {len(self.assumptions)} assumption versions"
        r = self._r_asm
        counts: dict[tuple[int, str], int] = {}
        order = [(n, nm) for n in sorted(self.t) for nm in range(len(OTHER_ASSUMPTIONS))]
        k = 0
        while need > 0:
            n, ix = order[k % len(order)]
            name, unit, why = OTHER_ASSUMPTIONS[ix]
            v = counts.get((n, name), 0) + 1
            if v > 3:
                k += 1
                continue
            counts[(n, name)] = v
            val = {"volume_growth": ri(r, 0, 60_000), "price_escalation": ri(r, 10_000, 70_000), "attrition_rate": ri(r, 40_000, 190_000),
                   "benefit_confidence": ri(r, 450_000, 950_000), "contingency_rate": ri(r, 50_000, 200_000)}[name]
            self._add_other(n, name, v, micro(val), None, unit, why + (" (revised)" if v > 1 else ""), at(date(2026, ri(r, 1, 9), ri(r, 1, 27)), ri(r, 8, 17)))
            need -= 1
            k += 1
        # the "other" names made version numbers per (initiative, name) 1..n in creation-draw order; keep them consistent with their dates
        for key in {(a["initiative_id"], a["name"]) for a in self.assumptions}:
            rows = sorted((a for a in self.assumptions if (a["initiative_id"], a["name"]) == key), key=lambda a: a["version_number"])
            for prev, nxt in zip(rows, rows[1:]):
                if nxt["created_at"] < prev["created_at"]:
                    prev["created_at"], nxt["created_at"] = nxt["created_at"], prev["created_at"]

    # ---- benefit streams and rows ----------------------------------------------------------------------------------------------------------
    def build_streams(self) -> None:
        """Windows first: every stream recognises BENEFIT_LIFE periods from its start (clipped by the 36-period calendar), then lengthened or shortened one
        period at a time, in a fixed order, to reach exactly the brief's 700 rows. The amounts follow once the costs are known."""
        self.streams: list[dict] = []
        for n in sorted(self.t):
            t = self.t[n]
            for k, (name, cls, mode, share, lag) in enumerate(t["streams"]):
                s = t["dep"] + lag
                self.streams.append({"n": n, "k": k, "name": name, "cls": cls, "mode": mode, "share": share, "lag": lag, "start": s, "end": min(PERIODS, s + BENEFIT_LIFE)})
        total = sum(s["end"] - s["start"] for s in self.streams)
        self.pad_notes["benefit_rows_before_adjustment"] = total
        by_late = sorted(self.streams, key=lambda s: (-s["start"], s["n"], s["k"]))
        by_early = sorted(self.streams, key=lambda s: (s["start"], s["n"], s["k"]))
        i = 0
        while total > TARGET["benefit_items"]:
            s = by_late[i % len(by_late)]
            i += 1
            if s["end"] - s["start"] > 6:
                s["end"] -= 1
                total -= 1
        i = 0
        guard = 0
        while total < TARGET["benefit_items"]:
            s = by_early[i % len(by_early)]
            i += 1
            guard += 1
            assert guard < 100_000, "cannot reach the benefit item count"
            if s["end"] < PERIODS and s["end"] - s["start"] < 18:
                s["end"] += 1
                total += 1
        self.case_end = {n: max(s["end"] for s in self.streams if s["n"] == n) for n in self.t}
        self.stream_of = {(s["n"], s["k"]): s for s in self.streams}

    # ---- costs -----------------------------------------------------------------------------------------------------------------------------
    def build_costs(self) -> None:
        r = self.rs["costs"]
        rows: list[dict] = []
        self.planned_by_ini: dict[int, dict[int, int]] = {n: {} for n in self.t}      # n -> period -> planned cents (one-time + expanded recurring)
        self.total_cost: dict[int, int] = {}
        cats = [("implementation", 35), ("integration", 15), ("data-migration", 10), ("training-development", 8), ("change-management", 10),
                ("licence-setup", 7), ("project-office", 10), ("contingency", 5)]
        for n in sorted(self.t):
            t = self.t[n]
            bv = PROGRAMMES[t["pi"]][3]
            ot_total, rec_month = t["ot"] * 100_000, t["rec"] * 100_000
            first, last = t["start"], max(t["start"], t["dep"])
            case_end = self.case_end[n]
            tot = 0

            def planned(key: str, ctype: str, amount: int, p: int | None = None, s: int | None = None, e: int | None = None) -> None:
                nonlocal tot
                rows.append({"cost_id": "", "initiative_id": self.iid(n), "cost_key": key, "cost_type": ctype, "cost_basis": "planned", "amount": cents(amount),
                             "period_index": p, "start_period": s, "end_period": e, "baseline_version": bv, "_n": n})
                for q in ([p] if ctype == "one_time" else range(s, e)):
                    self.planned_by_ini[n][q] = self.planned_by_ini[n].get(q, 0) + amount
                    tot += amount
            planned(f"ck-{n:03d}-discovery", "one_time", rdiv(ot_total * 2 // 100, 5000) * 5000, p=0)        # logged and assessed in January 2026: see D-07 (payback)
            for cname, w in cats:
                amt = ot_total * w // 100
                nl = ri(r, 2, 3) if cname in ("implementation", "integration", "change-management") else ri(r, 1, 3)
                weights = [ri(r, 5, 15) for _ in range(nl)]
                parts = [rdiv(rdiv(amt * x, sum(weights)), 5000) * 5000 for x in weights]
                parts[-1] = max(5000, amt - sum(parts[:-1]))
                for j in range(nl):
                    planned(f"ck-{n:03d}-{cname}-{j + 1}", "one_time", parts[j], p=ri(r, first, last))
            dep = t["dep"]
            seg = dep + 6
            for cname, w in (("support", 45), ("subscription", 35), ("run-team", 20)):
                base = rec_month * w // 100
                if seg < case_end:
                    planned(f"ck-{n:03d}-{cname}-s1", "recurring", rdiv(base, 5000) * 5000, s=dep, e=seg)
                    planned(f"ck-{n:03d}-{cname}-s2", "recurring", rdiv(base * ri(r, 100, 108) // 100, 5000) * 5000, s=seg, e=case_end)
                else:
                    planned(f"ck-{n:03d}-{cname}-s1", "recurring", rdiv(base, 5000) * 5000, s=dep, e=case_end)
            self.total_cost[n] = tot
        # actual cost: the periods that have matured, in three lines, against the plan with a per-initiative cost performance
        for n in sorted(self.t):
            t = self.t[n]
            if t["start"] >= MATURED:
                continue
            cf = ri(r, 900, 1250)
            for p in range(t["start"], MATURED):
                pl = self.planned_by_ini[n].get(p, 0)
                if pl == 0:
                    continue
                for cname, w in (("labour", 45), ("vendor", 40), ("other", 15)):
                    amt = pl * w * cf * ri(r, 940, 1070) // (100 * 1000 * 1000)
                    rows.append({"cost_id": "", "initiative_id": self.iid(n), "cost_key": f"ck-{n:03d}-act-{cname}-{p:02d}", "cost_type": "one_time", "cost_basis": "actual",
                                 "amount": cents(max(amt, 100)), "period_index": p, "start_period": None, "end_period": None, "baseline_version": None, "_n": n})
        self.cost_rows_base = len(rows)
        need = TARGET["cost_items"] - len(rows)
        assert need >= 0, f"{len(rows)} cost items before padding exceed the brief's {TARGET['cost_items']}"
        self.pad_notes["cost_items_before_padding"] = len(rows)
        # padding: contingency tranches on the initiatives, round robin, until the count is exact; they raise the one-time plan by their amounts
        k = 0
        order = sorted(self.t)
        while need > 0:
            n = order[k % len(order)]
            t = self.t[n]
            idx = k // len(order) + 1
            amt = rdiv(t["ot"] * 100_000 * ri(r, 1, 3) // 100, 5000) * 5000
            p = ri(r, t["start"], max(t["start"], t["dep"]))
            rows.append({"cost_id": "", "initiative_id": self.iid(n), "cost_key": f"ck-{n:03d}-contingency-tranche-{idx}", "cost_type": "one_time", "cost_basis": "planned",
                         "amount": cents(amt), "period_index": p, "start_period": None, "end_period": None, "baseline_version": PROGRAMMES[t["pi"]][3], "_n": n})
            self.planned_by_ini[n][p] = self.planned_by_ini[n].get(p, 0) + amt
            self.total_cost[n] += amt
            need -= 1
            k += 1
        self.pad_notes["cost_items_padded"] = TARGET["cost_items"] - self.pad_notes["cost_items_before_padding"]
        rows.sort(key=lambda c: (c["initiative_id"], c["cost_basis"], c["cost_type"], c["cost_key"]))
        for i, c in enumerate(rows, start=1):
            c["cost_id"] = f"c-{i:04d}"
            del c["_n"]
        self.costs = rows

    # ---- benefit amounts, rows, trends -----------------------------------------------------------------------------------------------------
    def build_benefits(self) -> None:
        r = self.rs["benefits"]
        rows: list[dict] = []
        self.stream_rows: dict[tuple[int, int], list[dict]] = {}
        for n in sorted(self.t):
            t = self.t[n]
            ramp = self.ramp_vals[n]
            ramp_early = [rdiv((j + 1) * (j + 2) * 1_000_000, t["rampn"] * (t["rampn"] + 1)) for j in range(t["rampn"])]
            s_ramp = sum(ramp_early[min(j, len(ramp_early) - 1)] for j in range(BENEFIT_LIFE))      # micro-units of a full period
            b_ref = rdiv(t["ratio"] * self.total_cost[n] * 1_000_000, 1000 * s_ramp) if t["ratio"] else 0
            norm = sum(s["share"] for s in self.streams if s["n"] == n and s["share"] > 0) or 1
            for s in self.streams:
                if s["n"] != n:
                    continue
                if s["cls"] == "capacity":
                    if n in self.base:
                        vol, mpc = self.base[n]
                        hours100 = vol * (mpc * 10 - self.target10[n]) // 6
                        amt = rdiv(hours100 * ri(r, 90, 100), 100)
                    else:
                        amt = ri(r, 150, 900) * 100
                elif s["share"] > 0:
                    amt = rdiv(rdiv(b_ref * s["share"], norm), 5000) * 5000
                else:
                    amt = rdiv(rdiv(b_ref * 30, 100), 5000) * 5000
                amt = max(amt, 5000)
                s["steady"] = amt
                s["trend_pct"] = ri(r, 5, 25)
                s["perf_pct"] = ri(r, 72, 104)
                s["key"] = SHARED_CAP_KEY if s["mode"] == "shared" else f"src-{n:03d}-{s['name']}"
                s["rows"] = []
        # rows (ids assigned in stream order)
        for s in sorted(self.streams, key=lambda s: (s["n"], s["k"])):
            for p in range(s["start"], s["end"]):
                cls, mode = s["cls"], s["mode"]
                row = {"benefit_id": "", "initiative_id": self.iid(s["n"]), "benefit_type": cls, "amount": cents(s["steady"]), "period_index": p, "starts_period": s["start"],
                       "unit": "hours" if cls == "capacity" else "USD",
                       "cash_realisation": True if mode in ("realised", "noevid") else (False if mode == "beside" else None),
                       "evidence_ref": f"ev:budget-line-{s['n']:03d}-{s['k'] + 1}" if mode == "realised" else None,
                       "benefit_source_key": s["key"], "baseline_trend_per_period": cents(rdiv(s["steady"] * s["trend_pct"], 100)), "_s": (s["n"], s["k"])}
                rows.append(row)
                s["rows"].append(row)
        for i, b in enumerate(rows, start=1):
            b["benefit_id"] = f"b-{i:04d}"
        self.benefits = rows

    # ---- benefit observations --------------------------------------------------------------------------------------------------------------
    def ramp_at(self, n: int, start: int, p: int) -> int:
        rv = self.ramp_vals[n]
        return rv[min(max(p - start, 0), len(rv) - 1)]

    def build_observations(self) -> None:
        """Observed values of the matured periods (0..8), up to five readings each (flash, preliminary, reconciled, audited, restated), the last one is the value of the row.
        Observed = planned (ramped) x the stream's performance; the baseline trend recorded on a row is a share of its observed value (5 to 25 %, DR-06: 85 %)."""
        r = self.rs["observations"]
        cand: list[dict] = []                                   # one entry per matured row: stream, row, candidate readings
        for s in sorted(self.streams, key=lambda s: (s["n"], s["k"])):
            err = ri(r, -8, 8)
            for row in s["rows"]:
                p = row["period_index"]
                ramped = rdiv(s["steady"] * self.ramp_at(s["n"], s["start"], p), 1_000_000)
                if p >= MATURED:
                    row["baseline_trend_per_period"] = cents(rdiv(ramped * s["trend_pct"] * (100 + err), 10_000))     # a plan-side trend, not yet observed
                    continue
                perf = s["perf_pct"]
                if (s["n"], s["k"]) == (D4, 0):
                    perf = D4_PERF[0] if p <= 4 else D4_PERF[1] + (2 if p == 8 else 0)
                if (s["n"], s["k"]) == (D6, 0):
                    perf = ri(r, 93, 98)
                final = rdiv(ramped * perf * ri(r, 96, 104), 10_000)
                end = pdate(p + 1)
                days = [ri(r, 1, 2), ri(r, 3, 9), ri(r, 28, 45), ri(r, 60, 80), ri(r, 95, 120)]
                if (s["n"], s["k"]) == (D4, 0) and p == 7:
                    days[1] = 4
                hours = [ri(r, 8, 16) for _ in days]
                times = [at(end + timedelta(days=d), h) for d, h in zip(days, hours)]
                keep = [chance(r, 250_000), True, chance(r, 850_000), chance(r, 450_000), chance(r, 250_000)]
                cand.append({"s": s, "row": row, "p": p, "final": final, "times": times, "keep": keep, "err": err})
        total = lambda: sum(sum(1 for k, t in zip(c["keep"], c["times"]) if k and t < AS_OF) for c in cand)
        for c in cand:                                         # a reading needs to exist at as_of; the first reading is always kept when its date allows
            c["keep"] = [k and t < AS_OF for k, t in zip(c["keep"], c["times"])]
            if not any(c["keep"]):
                c["keep"][1] = c["times"][1] < AS_OF
        self.pad_notes["observation_readings_before_trimming"] = total()
        n_now = total()
        idx = [i for i in range(len(cand))]
        r.shuffle(idx)
        for slot in (4, 3, 0, 2):                              # trim the restated, audited, flash and reconciled readings, in that order
            for i in idx:
                if n_now <= TARGET["benefit_observations"]:
                    break
                c = cand[i]
                if c["keep"][slot] and sum(c["keep"]) > 1:
                    c["keep"][slot] = False
                    n_now -= 1
        for slot in (1, 2, 3, 0, 4):                           # or add the readings that fit before as_of
            for i in idx:
                if n_now >= TARGET["benefit_observations"]:
                    break
                c = cand[i]
                if not c["keep"][slot] and c["times"][slot] < AS_OF:
                    c["keep"][slot] = True
                    n_now += 1
        assert n_now == TARGET["benefit_observations"], f"{n_now} benefit observations"
        obs: list[dict] = []
        for c in cand:
            s, row, p = c["s"], c["row"], c["p"]
            slots = [i for i, k in enumerate(c["keep"]) if k]
            for j, i in enumerate(slots):
                last = j == len(slots) - 1
                val = c["final"] if last else rdiv(c["final"] * (ri(r, 88, 106) if i <= 1 else ri(r, 97, 103)), 100)
                kind = ("flash", "prelim", "reconciled", "audited", "restated")[i]
                obs.append({"benefit_observation_id": "", "benefit_id": row["benefit_id"], "measured_value": cents(val),
                            "evidence_ref": f"ev:{EVIDENCE_SYSTEM[s['cls']]}-{SYSTEMS[s['n']]}-{pdate(p):%Y-%m}-{kind}", "observed_at": ts(c["times"][i])})
            tp = SHARE_ABOVE_TREND if (s["n"], s["k"]) == (D6, 0) else None
            if tp is not None:
                trend = rdiv(c["final"] * tp * (100 + ri(r, -4, 4)), 10_000)
                true_t = rdiv(c["final"] * tp, 100)
            else:
                trend = rdiv(c["final"] * s["trend_pct"] * (100 + c["err"]), 10_000)
                true_t = rdiv(c["final"] * s["trend_pct"], 100)
            row["baseline_trend_per_period"] = cents(trend)
            if slots:                                               # the counterfactual covers the rows the domain can compare (those with a reading)
                acc = self.truth.setdefault("trend", {}).setdefault(f"init-{s['n']:03d}/{s['cls']}", [0, 0])
                acc[0] += c["final"]
                acc[1] += true_t
        obs.sort(key=lambda o: (o["benefit_id"], o["observed_at"]))
        for i, o in enumerate(obs, start=1):
            o["benefit_observation_id"] = f"bo-{i:04d}"
        self.bobs = obs
        for b in self.benefits:
            b.pop("_s", None)

    # ---- scenarios -------------------------------------------------------------------------------------------------------------------------
    def build_scenarios(self) -> None:
        r = self.rs["scenarios"]
        by_prog = {pi: [n for n in sorted(self.t) if self.t[n]["pi"] == pi] for pi in range(4)}
        spec: list[dict] = []
        dates = {0: [(2, 10), (6, 15), (7, 2), (4, 22), (7, 20), (8, 4)], 1: [(2, 12), (6, 9), (7, 6), (5, 20), (7, 27), (8, 11)],
                 2: [(2, 16), (6, 11), (7, 8), (5, 27), (8, 3), (8, 18)], 3: [(2, 19), (6, 24), (7, 13), (6, 3), (8, 10), (9, 1)]}
        for pi in range(4):
            m = by_prog[pi]
            d = dates[pi]
            sub = [n for n in m if self.t[n]["status"] == "in_delivery"] if pi < 3 else [23, 24]
            if pi == 0:
                sub = [3, 4, 5, 6]
            lab = PROGRAMMES[pi][1]
            spec += [
                {"name": f"{lab}: base case", "ids": m, "H": 36, "rate": 80_000, "basis": "annual", "date": d[0], "status": "draft", "mode": "latest"},
                {"name": f"{lab}: higher discount rate", "ids": m, "H": 36, "rate": 120_000, "basis": "annual", "date": d[1], "status": "draft", "mode": "latest"},
                {"name": f"{lab}: 24-period horizon", "ids": m, "H": 24, "rate": 80_000, "basis": "annual", "date": d[2], "status": "draft", "mode": "latest"},
                {"name": f"{lab}: initiatives in delivery", "ids": sub, "H": 36, "rate": 100_000, "basis": "annual", "date": d[3], "status": "draft", "mode": "latest"},
                {"name": f"{lab}: first ramp and target", "ids": m, "H": 36, "rate": 100_000, "basis": "annual", "date": d[4], "status": "draft", "mode": "earliest"},
                {"name": f"{lab}: monthly rate declared", "ids": m, "H": 36, "rate": 7_000, "basis": "monthly", "date": d[5], "status": "draft", "mode": "latest"}]
        allids = sorted(self.t)
        spec += [
            {"name": "Portfolio: all initiatives", "ids": allids, "H": 36, "rate": 80_000, "basis": "annual", "date": (9, 2), "status": "draft", "mode": "latest"},
            {"name": "Portfolio without the duplicate capacity claim", "ids": [n for n in allids if n != D2B], "H": 36, "rate": 80_000, "basis": "annual", "date": (9, 3), "status": "draft", "mode": "latest"},
            {"name": "Adopted and closed initiatives", "ids": [1, 2, 7, 8, 13], "H": 24, "rate": 100_000, "basis": "annual", "date": (8, 25), "status": "draft", "mode": "latest"},
            {"name": "Platform first", "ids": [23, 24, 19, 20, 5, 11, 17], "H": 36, "rate": 100_000, "basis": "annual", "date": (8, 28), "status": "draft", "mode": "latest"},
            {"name": "Candidate pipeline", "ids": [n for n in allids if self.t[n]["status"] in ("candidate", "assessed")], "H": 36, "rate": 120_000, "basis": "annual", "date": (9, 7), "status": "draft", "mode": "latest"},
            {"name": "Budget-capped selection", "ids": [3, 4, 8, 9, 10, 13, 14, 16, 23, 24], "H": 36, "rate": 100_000, "basis": "annual", "date": (9, 9), "status": "draft", "mode": "latest"}]
        assert len(spec) == TARGET["scenario_versions"]
        self.scenarios: list[dict] = []
        for i, sp in enumerate(spec, start=1):
            mo, dy = sp["date"]
            created = at(date(2026, mo, dy), ri(r, 8, 17))
            pins: list[str] = []
            for n in sp["ids"]:
                for name in ("adoption_ramp", "target_minutes_per_case", "capacity_hourly_rate"):
                    versions = [(aid, c) for aid, c in self.asm_ids.get((n, name), []) if c <= created]
                    if not versions:
                        continue
                    versions.sort(key=lambda x: x[1])
                    pins.append(versions[0][0] if sp["mode"] == "earliest" else versions[-1][0])
            first = sp["ids"][0]
            label = "v1" if PROGRAMMES[self.t[first]["pi"]][3] in (None, "v1") and len(sp["ids"]) < 20 and all(PROGRAMMES[self.t[n]["pi"]][3] in (None, "v1") for n in sp["ids"]) else "v2"
            if sp["basis"] == "annual":
                conv, rate_text = self.conv_ids[sp["rate"]], micro(sp["rate"])
            else:
                conv, rate_text = None, micro(sp["rate"])
            self.scenarios.append({"scenario_id": f"scn-{i:03d}", "baseline_version": label, "discount_rate": rate_text, "rate_basis": sp["basis"],
                                   "rate_conversion_assumption_id": conv, "horizon_periods": sp["H"], "status": sp["status"],
                                   "initiative_ids": [self.iid(n) for n in sorted(sp["ids"])], "pinned_assumption_ids": sorted(set(pins)), "created_at": ts(created)})
            self.scenarios[-1]["_name"] = sp["name"]

    # ---- dependencies, resources, allocations ----------------------------------------------------------------------------------------------
    def build_roadmap(self) -> None:
        r = self.rs["roadmap"]
        order = sorted(self.t, key=lambda n: (self.t[n]["start"], n))
        pos = {n: i for i, n in enumerate(order)}
        edges: dict[tuple[int, int], tuple[str, int]] = {}

        def choose(i: int, p: int, force: str | None = None, lag: int | None = None) -> tuple[str, int]:
            ti, tp = self.t[i], self.t[p]
            if ti["start"] < MATURED:                                   # already started: the nominal plan must satisfy the edge
                gap = ti["start"] - (tp["start"] + tp["dur"])
                if gap >= 0 and force != "start_to_start":
                    return "finish_to_start", min(3, ri(r, 0, gap))
                return "start_to_start", min(3, ri(r, 0, max(0, ti["start"] - tp["start"])))
            kind = force or pick(r, ["finish_to_start", "finish_to_start", "start_to_start"])
            return kind, ri(r, 0, 3) if lag is None else lag

        fixed = [(19, 23, "finish_to_start", 1), (20, 23, "finish_to_start", 0), (5, 23, "start_to_start", 2), (11, 23, "start_to_start", 1), (17, 23, "start_to_start", 3), (24, 23, "start_to_start", 1)]
        for i, p, kind, lag in fixed:
            edges[(i, p)] = (kind, lag)
        for i in order[1:]:                                            # every initiative but the first has a prerequisite that starts no later
            if any(k[0] == i for k in edges):
                continue
            pool = [p for p in order[:pos[i]]]
            same = [p for p in pool if self.t[p]["pi"] == self.t[i]["pi"]]
            p = pick(r, same if same and chance(r, 750_000) else pool)
            edges[(i, p)] = choose(i, p)
        guard = 0
        while len(edges) < TARGET["dependencies"]:
            guard += 1
            assert guard < 10_000
            i = pick(r, order[1:])
            pool = [p for p in order[:pos[i]] if (i, p) not in edges and (p, i) not in edges]
            if not pool:
                continue
            same = [p for p in pool if self.t[p]["pi"] == self.t[i]["pi"]]
            p = pick(r, same if same and chance(r, 700_000) else pool)
            edges[(i, p)] = choose(i, p)
        self.dependencies = [{"dependency_id": f"d-{k:03d}", "initiative_id": self.iid(i), "prerequisite_id": self.iid(p), "dependency_type": kind, "lag_periods": lag}
                             for k, ((i, p), (kind, lag)) in enumerate(sorted(edges.items(), key=lambda e: (e[0][0], e[0][1])), start=1)]
        self.resources = [{"resource_id": a, "name": b, "capacity_per_period": c, "unit": d} for a, b, c, d in RESOURCES]
        cap = {a: int(c.replace(".", "")) for a, _, c, _ in RESOURCES}
        used: dict[tuple[str, int], int] = {}
        allocs: list[tuple[str, int, int, int]] = []                  # resource, initiative n, period, hundredths

        def put(res: str, n: int, p: int, amt: int) -> None:
            room = cap[res] - used.get((res, p), 0)
            amt = min(amt, room) // 25 * 25
            if amt > 0:
                used[(res, p)] = used.get((res, p), 0) + amt
                allocs.append((res, n, p, amt))

        d5 = {23: {**{p: 50 for p in range(6, 12)}, **{12: 75, 13: 75, 14: 75, 15: 75, 16: 100, 17: 50}},
              19: {**{p: 25 for p in range(9, 12)}, 12: 75, 13: 75, 14: 75, 15: 50},
              17: {**{p: 25 for p in range(10, 13)}, 13: 50, 14: 50, 15: 75},
              20: {12: 25, 13: 25, 14: 25, 15: 25, 16: 100, 17: 50, 18: 50},
              24: {p: 50 for p in range(7, 13)}}
        # res-03 at exactly 2.00 in periods 14..16 (a sum equal to capacity is allowed) so that the replay requests there are the ones that cross
        d5[20][14] = 0
        d5[20][15] = 0
        d5[19][14] = 75
        for n, per in d5.items():
            for p, a in sorted(per.items()):
                put(D5_RESOURCE, n, p, a)
        for res, who in RES_FOR.items():
            for n in who:
                t = self.t[n]
                level = pick(r, [25, 50, 50, 75, 100])
                for p in range(t["start"], min(PERIODS, t["start"] + min(t["dur"], 6))):
                    put(res, n, p, level)
        allocs.sort(key=lambda a: (a[0], a[1], a[2]))
        self.allocations = [{"allocation_id": f"al-{k:04d}", "resource_id": res, "initiative_id": self.iid(n), "period_index": p, "amount": cents(a)}
                            for k, (res, n, p, a) in enumerate(allocs, start=1)]
        self.res_used = used
        self.res_cap = cap

    # ---- stakeholders, impact, readiness ---------------------------------------------------------------------------------------------------
    def build_people(self) -> None:
        r = self.rs["people"]
        self.groups: list[dict] = []
        self.group_ini: dict[str, list[int]] = {}
        k = 0
        for mod in range(3):
            for role, n in ROLES:
                if k >= TARGET["stakeholder_groups"]:
                    break
                if mod == 2 and n % 4 != 0 and n % 4 != 1:
                    continue
                if mod == 1 and n % 3 == 0:
                    continue
                k += 1
                gid = f"grp-{k:03d}"
                self.groups.append({"group_id": gid, "group_name": f"{role} - {MODIFIERS[mod]}", "owner_id": SPONSOR_OVERRIDE.get(n, PROGRAMMES[self.t[n]['pi']][2]),
                                    "affected_count": ri(r, 12, 420), "impact_level": pick(r, ["low", "medium", "medium", "high", "high"])})
                self.group_ini[gid] = [n]
        fill = 0
        while len(self.groups) < TARGET["stakeholder_groups"]:         # top up with the shared-services variants of the remaining roles
            role, n = ROLES[fill % len(ROLES)]
            fill += 1
            if any(g["group_name"] == f"{role} - {MODIFIERS[2]}" for g in self.groups):
                continue
            gid = f"grp-{len(self.groups) + 1:03d}"
            self.groups.append({"group_id": gid, "group_name": f"{role} - {MODIFIERS[2]}", "owner_id": SPONSOR_OVERRIDE.get(n, PROGRAMMES[self.t[n]['pi']][2]),
                                "affected_count": ri(r, 12, 420), "impact_level": pick(r, ["low", "medium", "medium", "high", "high"])})
            self.group_ini[gid] = [n]
        assert len(self.groups) == TARGET["stakeholder_groups"], len(self.groups)
        self.mappings: list[dict] = []
        for g in self.groups:
            n0 = self.group_ini[g["group_id"]][0]
            ids = [n0]
            for extra in (n0 + 1, n0 - 1, 23):
                if 1 <= extra <= 24 and extra != n0 and chance(r, 260_000) and len(ids) < 3:
                    ids.append(extra)
            self.group_ini[g["group_id"]] = ids
            for n in ids:
                self.mappings.append({"mapping_id": f"im-{len(self.mappings) + 1:03d}", "initiative_id": self.iid(n), "group_id": g["group_id"],
                                      "operating_change": CHANGES[n] if n == n0 else f"Indirect effect: {CHANGES[n][0].lower() + CHANGES[n][1:]}",
                                      "impact_level": g["impact_level"] if n == n0 else pick(r, ["low", "low", "medium"])})
        # readiness: complete sets for 54 groups (270), three dimensions for 6 groups (18), twelve reassessments = 300
        dims = ("awareness", "desire", "knowledge", "ability", "reinforcement")
        wts = {"awareness": "1.00", "desire": "1.50", "knowledge": "1.00", "ability": "1.50", "reinforcement": "0.75"}
        rows: list[tuple[str, str, int, str, datetime]] = []
        for gi, g in enumerate(self.groups):
            n0 = self.group_ini[g["group_id"]][0]
            live = self.t[n0]["dep"] < MATURED
            use = dims if gi < 54 else dims[:3]
            base = 3 + (1 if live else 0)
            when = at(date(2026, ri(r, 2, 6), ri(r, 1, 27)), ri(r, 9, 16))
            for d in use:
                sc = max(1, min(5, base + ri(r, -1, 1) + (1 if d == "awareness" else 0) - (1 if d == "reinforcement" and not live else 0)))
                rows.append((g["group_id"], d, sc, wts[d], when + timedelta(days=ri(r, 0, 6))))
        for gi in range(12):                                           # a later reassessment of the dimension that moves most after go-live
            g = self.groups[gi]
            d = "reinforcement" if gi % 2 == 0 else "ability"
            old = next(x for x in rows if x[0] == g["group_id"] and x[1] == d)
            rows.append((g["group_id"], d, max(1, min(5, old[2] + ri(r, 0, 2))), wts[d], at(date(2026, ri(r, 8, 9), ri(r, 1, 28)), ri(r, 9, 16))))
        assert len(rows) == TARGET["readiness_assessments"], len(rows)
        rows.sort(key=lambda x: (x[0], x[4], x[1]))
        self.readiness = [{"assessment_id": f"ra-{k:04d}", "group_id": g, "dimension": d, "score": s, "weight": w, "assessed_at": ts(t)} for k, (g, d, s, w, t) in enumerate(rows, start=1)]

    # ---- adoption and training -------------------------------------------------------------------------------------------------------------
    def build_adoption(self) -> None:
        r = self.rs["adoption"]
        sstep = lambda u: (u * u * (3 * 1_000_000 - 2 * u)) // (1_000_000 * 1_000_000)           # smoothstep of u in micro-units, in micro-units
        self.adopt_params: dict[int, dict] = {}
        ad: list[tuple[int, datetime, int, int]] = []
        tr: list[tuple[int, datetime, int, int]] = []
        for n in TRAINING_INI:
            t = self.t[n]
            pop = ri(r, 120, 900)
            t0 = at(pdate(t["start"]) + timedelta(days=ri(r, 8, 20)), 15)
            tdays = ri(r, 56, 84)
            plateau = ri(r, 94, 100)
            amax = ri(r, 70, 92)
            rdays = ri(r, 270, 340)
            if n == D4:
                plateau, amax = 98, 41                                  # training done, adoption stalled: the substitution trap (INJ-05)
            self.adopt_params[n] = {"population": pop, "training_start": ts(t0), "training_days": tdays, "plateau_pct": plateau, "adoption_max_pct": amax, "ramp_days": rdays}
            elig_t = pop
            k = 0
            sat = None
            while True:
                when = t0 + timedelta(days=7 * k)
                if when >= AS_OF:
                    break
                u = min(1_000_000, 7 * k * 1_000_000 // tdays)
                if sat is not None and k > sat + 4:
                    break
                if u >= 1_000_000 and sat is None:
                    sat = k
                done = min(elig_t, elig_t * plateau * sstep(u) // 100 // 1_000_000)
                tr.append((n, when, elig_t, done))
                k += 1
            if n in ADOPTION_INI:
                g = at(pdate(t["dep"]) + timedelta(days=ri(r, 1, 3)), 12)
                elig_a = max(1, pop * ri(r, 97, 103) // 100)
                step = 0
                when = g
                while when < AS_OF - timedelta(hours=2):
                    days = (when - g).total_seconds() / 86400
                    u = min(1_000_000, int(days * 1_000_000) // rdays)
                    noise = ri(r, 970, 1030)
                    adopted = min(elig_a, elig_a * amax * sstep(u) * noise // (100 * 1_000_000 * 1000))
                    ad.append((n, when, elig_a, adopted))
                    when = when + timedelta(days=3 + (step % 2), hours=ri(r, -2, 2))
                    step += 1
        self.pad_notes["adoption_candidates"] = len(ad)
        self.pad_notes["training_candidates"] = len(tr)
        # exact counts: missed telemetry extracts are drawn out of the candidates; short training series gain weekly refresher readings
        need = TARGET["adoption_observations"]
        assert len(ad) >= need, f"{len(ad)} adoption candidates"
        drop = sorted(r.sample(range(len(ad)), len(ad) - need))
        ad = [x for i, x in enumerate(ad) if i not in set(drop)]
        by_n: dict[int, list] = {}
        for x in tr:
            by_n.setdefault(x[0], []).append(x)
        need_t = TARGET["training_completions"]
        if len(tr) > need_t:
            drop_t = set(r.sample(range(len(tr)), len(tr) - need_t))
            tr = [x for i, x in enumerate(tr) if i not in drop_t]
        else:
            k = 0
            order = sorted(by_n)
            while len(tr) < need_t:
                n = order[k % len(order)]
                last = max((x for x in tr if x[0] == n), key=lambda x: x[1])
                when = last[1] + timedelta(days=7)
                k += 1
                assert k < 100_000, "cannot reach the training count"
                if when >= AS_OF:
                    continue
                elig = last[2] + ri(r, 0, 2)
                tr.append((n, when, elig, min(elig, last[3] + ri(r, 0, 2))))
        ad.sort(key=lambda x: (x[0], x[1]))
        tr.sort(key=lambda x: (x[0], x[1]))
        self.adoption = [{"observation_id": f"ad-{k:04d}", "initiative_id": self.iid(n), "eligible_count": e, "adopted_count": a, "observed_at": ts(w),
                          "eligibility_rule_version": self.t[n]["elig"]} for k, (n, w, e, a) in enumerate(ad, start=1)]
        self.training = [{"training_id": f"tc-{k:04d}", "initiative_id": self.iid(n), "eligible_trainees": e, "completed": c, "recorded_at": ts(w),
                          "eligibility_rule_version": self.t[n]["elig"]} for k, (n, w, e, c) in enumerate(tr, start=1)]

    # ---- risks, forecasts ------------------------------------------------------------------------------------------------------------------
    def build_risks(self) -> None:
        r = self.rs["risks"]
        self.risks = []
        for n in sorted(self.t):
            titles = r.sample(RISK_TITLES, 5)
            for j, title in enumerate(titles, start=1):
                impact = rdiv(self.t[n]["ot"] * 100_000 * ri(r, 4, 55), 100 * 5000) * 5000
                self.risks.append({"risk_id": f"r-{n:03d}-{j}", "initiative_id": self.iid(n), "probability": micro(ri(r, 40_000, 600_000)), "impact": cents(impact),
                                   "mitigation": f"{title}: {pick(r, MITIGATIONS)}"})
        assert len(self.risks) == TARGET["risk_items"]

    def build_forecasts(self) -> None:
        r = self.rs["forecasts"]
        self.forecasts: list[dict] = []
        self.forecast_meta: dict[int, list[dict]] = {}
        for n, nver in sorted(FORECAST_SET.items()):
            cash = next(s for s in sorted((s for s in self.streams if s["n"] == n and s["cls"] == "cash"), key=lambda s: s["k"]))
            periods = list(range(cash["start"], cash["end"]))
            plan = {p: rdiv(cash["steady"] * self.ramp_at(n, cash["start"], p), 1_000_000) for p in periods}
            created = [at(date(2026, 3, 12), 10) if n == D4 else at(date(2026, 1, ri(r, 22, 31)), 10)]
            amounts = [dict(plan)]
            reasons = ["Approved forecast"]
            if nver >= 2:
                if n == D4:
                    c2 = at(date(2026, 6, 12), 10)
                    new = {p: (v if p < 5 else rdiv(plan[p] * D4_REVISION[0], 100)) for p, v in plan.items()}
                    reasons.append("Revised after April and May fell short of the approved forecast")
                else:
                    c2 = at(date(2026, ri(r, 6, 8), ri(r, 3, 25)), 10)
                    new = {p: (v if pdate(p) < c2.date() else rdiv(plan[p] * (100 + (8 if n == 13 else -8)), 100)) for p, v in plan.items()}
                    reasons.append("Revised for a change of scope in the second wave" if n == 13 else "Revised after the first months of operation")
                created.append(c2)
                amounts.append(new)
            if nver >= 3:
                c3 = at(date(2026, 9, 9), 10)
                created.append(c3)
                amounts.append({p: (v if p < 8 else rdiv(plan[p] * D4_REVISION[1], 100)) for p, v in amounts[1].items()})
                reasons.append("Revised again after June, July and August fell short of the revised forecast")
            self.forecast_meta[n] = [{"version": v, "created_at": ts(created[v - 1])} for v in range(1, nver + 1)]
            for v in range(1, nver + 1):
                for p in periods:
                    self.forecasts.append({"forecast_id": f"f-{n:03d}-{v}-{p:02d}", "initiative_id": self.iid(n), "version_number": v, "period_index": p,
                                           "amount": cents(amounts[v - 1][p]), "reason": reasons[v - 1], "created_at": ts(created[v - 1])})
        assert len({(f["initiative_id"], f["version_number"]) for f in self.forecasts}) == 12

    # ---- assemble --------------------------------------------------------------------------------------------------------------------------
    def build_all(self) -> None:
        self.build_initiatives()
        self.build_baselines()
        self.build_assumptions()
        self.build_streams()
        self.build_costs()
        self.build_benefits()
        self.build_observations()
        self.pad_assumptions()
        self.build_scenarios()
        self.build_roadmap()
        self.build_people()
        self.build_adoption()
        self.build_risks()
        self.build_forecasts()

    def entities(self) -> dict[str, list[dict]]:
        for sc in self.scenarios:
            sc.pop("_name", None)
        ents = {"initiatives": self.initiatives, "process_baselines": self.baselines, "assumption_versions": self.assumptions, "resources": self.resources,
                "scenario_versions": self.scenarios, "cost_items": self.costs, "benefit_items": self.benefits, "dependencies": self.dependencies,
                "stakeholder_groups": self.groups, "impact_mappings": self.mappings, "resource_allocations": self.allocations,
                "readiness_assessments": self.readiness, "adoption_observations": self.adoption, "training_completions": self.training,
                "benefit_observations": self.bobs, "risk_items": self.risks, "forecast_versions": self.forecasts}
        return {k: ents[k] for k in sorted(ents)}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# output: entity files, the domain's reading of the world, the injection manifest
# ---------------------------------------------------------------------------------------------------------------------------------------------
def entity_text(name: str, version: str, rows: list[dict]) -> str:
    body = ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return f'{{"entity":{json.dumps(name)},"dataset_version":{json.dumps(version)},"rows":[\n{body}\n]}}\n'


def dataset_hash(ents: dict[str, list[dict]]) -> str:
    h = hashlib.sha256()
    for name in sorted(ents):
        h.update(canonical(ents[name]).encode())
    return h.hexdigest()


def to_inputs(ents: dict[str, list[dict]]) -> dict[str, Any]:
    inp: dict[str, Any] = dict(CONFIG)
    inp.update(copy.deepcopy(ents))
    return inp


def lookup(obj: Any, path: str) -> Any:
    """``a.b[2].c`` on nested dicts and lists (the paths of the injection checks)."""
    cur = obj
    for part in path.replace("[", ".[").split("."):
        if part.startswith("["):
            cur = cur[int(part[1:-1])]
        else:
            cur = cur[part]
    return cur


def month_index(iso: str) -> int:
    return int(iso[:4]) * 12 + int(iso[5:7]) - 1


class Reading:
    """The domain's reading of a finished world: ingest counts, the metrics tree and the warnings, plus helpers to ask it questions."""

    def __init__(self, ents: dict[str, list[dict]]):
        self.inputs = to_inputs(ents)
        self.result = run_pipeline(self.inputs)
        self.metrics = self.result.metrics
        self.doc = {"metrics": self.metrics, "ingest": {"counts": self.result.counts, "rejected_records": self.result.ingest.rejected_records()}}

    def get(self, path: str) -> Any:
        return lookup(self.doc, path)

    def validator(self) -> Validator:
        return Validator(validate_batch(self.inputs).population)


class Injections:
    def __init__(self, w: World, ents: dict[str, list[dict]], version: str):
        self.w, self.ents, self.version = w, ents, version
        self.read = Reading(ents)
        self.events: list[dict] = []
        self.injections: list[dict] = []
        self.designed: list[dict] = []

    # -- step builders ----------------------------------------------------------------------------------------------------------------------
    def ingest(self, v: Validator, entity: str, row: dict, expect: str | None) -> dict:
        """One row through the domain's validator: ``expect`` is the reason code the contract requires (None: it must be accepted)."""
        rej = v.add(entity, copy.deepcopy(row))
        got = rej.reason_code if rej else None
        assert got == expect, f"{entity} {row.get(next(iter(row)))}: expected {expect}, the domain says {got}"
        step: dict[str, Any] = {"kind": "ingest", "entity": entity, "row": row, "expected": "accepted" if rej is None else "rejected"}
        if rej is not None:
            step["reason_code"] = rej.reason_code
            step["details"] = rej.details
        return step

    def command(self, name: str, inp: dict, key: str, status: int, reason: str | None = None, role: str = "analyst", **extra: Any) -> dict:
        actor = {"analyst": {"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "analyst"}, "sponsor": {"X-Actor-Id": "usr-sponsor01", "X-Actor-Role": "sponsor"}}[role]
        s: dict[str, Any] = {"kind": "command", "command": name, "headers": actor,
                             "input": {"request_id": f"req-{key}", "dataset_version": self.version, "idempotency_key": key, "input": inp}, "expected_status": status}
        if reason:
            s["expected_reason"] = reason
        s.update(extra)
        return s

    def metrics_read(self, expect: list[dict], scenario_id: str | None = None) -> dict:
        params = {"as_of": AS_OF_TEXT}
        if scenario_id:
            params["scenario_id"] = scenario_id
        return {"kind": "read", "path": "/metrics", "params": params, "expect": expect, "expected_status": 200}

    def checks(self, paths: list[str]) -> list[dict]:
        return [{"path": p, "equals": self.read.get(p)} for p in paths]

    def event(self, ev: str, inj: str, requires: list[str], steps: list[dict]) -> None:
        self.events.append({"event_id": ev, "injection": inj, "requires": requires, "steps": steps})

    def inj(self, n: int, name: str, location: str, defect: str, handling: str, records: list[dict], checks: list[dict], rejections: list[dict], events: list[str]) -> None:
        self.injections.append({"id": f"INJ-{n:02d}", "test": f"P09-TEST-{n:02d}", "name": name, "location": location, "defect": defect, "expected_handling": handling,
                                "records": records, "checks": checks, "expected_rejections": rejections, "events": events})

    # -- scenario helpers ------------------------------------------------------------------------------------------------------------------
    def scenarios_with(self, n: int) -> list[str]:
        iid = self.w.iid(n)
        return [s["scenario_id"] for s in self.ents["scenario_versions"] if iid in s["initiative_ids"]]

    def sc_path(self, sid: str, n: int, rest: str) -> str:
        return f"metrics.scenarios.{sid}.initiatives.{self.w.iid(n)}.{rest}"

    # -- the twelve ------------------------------------------------------------------------------------------------------------------------
    def build(self) -> None:
        w, E = self.w, self.ents
        iid = w.iid
        scn_d1 = "scn-025"                                                # the all-initiatives portfolio of September: latest pins, every initiative
        scn_pair = next(s["scenario_id"] for s in E["scenario_versions"] if s["status"] == "draft" and iid(D2A) in s["initiative_ids"] and iid(D2B) in s["initiative_ids"]
                        and self.read.get(f"metrics.scenarios.{s['scenario_id']}.double_count.residual") != "0.00")
        scn_pair_all = "scn-025"
        clean_draft = next(s["scenario_id"] for s in E["scenario_versions"] if self.read.get(f"metrics.scenarios.{s['scenario_id']}.double_count.explanation_required") is False)
        scn_d6 = "scn-025"
        scn_d4 = scn_pair_all

        # INJ-01 / EV-01: time savings booked as cash with no staffing change
        v = self.read.validator()
        row1 = {"benefit_id": "b-inj-01", "initiative_id": iid(D1), "benefit_type": "capacity", "amount": "100.00", "period_index": 12, "starts_period": 12, "unit": "hours",
                "cash_realisation": True, "evidence_ref": None, "benefit_source_key": f"src-{D1:03d}-triage-time", "baseline_trend_per_period": "5.00"}
        asm1 = {"assumption_id": "a-inj-01-rate", "initiative_id": iid(D1), "name": "capacity_hourly_rate", "version_number": 1, "value": "31.50", "values": None, "unit": "USD per hour",
                "rationale": "Loaded cost of a triage handler", "author_id": "an-02", "evidence_ref": None, "staffing_change_evidence_ref": "ev:hr-headcount-plan-complaints-2026",
                "created_at": "2026-10-04T09:00:00Z"}
        steps = [self.ingest(v, "benefit_items", row1, "CAPACITY_WITHOUT_CONVERSION"), self.ingest(v, "assumption_versions", asm1, None),
                 self.ingest(v, "benefit_items", {**row1, "benefit_id": "b-inj-01b"}, None)]
        steps.append(self.command("build-cash-flows", {"scenario_id": "scn-inj-01", "baseline_version": "v2", "discount_rate": "0.080000", "rate_basis": "annual",
                                                       "rate_conversion_assumption_id": w.conv_ids[80_000], "horizon_periods": 24, "initiative_ids": [iid(D1)], "pinned_assumption_ids": [],
                                                       "benefits": [{"initiative_id": iid(D1), "benefit_type": "capacity", "amount": "100.00", "period_index": 12, "starts_period": 12,
                                                                     "unit": "hours", "cash_realisation": True}]}, "inj-01-a", 422, "CAPACITY_WITHOUT_CONVERSION"))
        self.event("EV-01", "INJ-01", [iid(D1)], steps)
        self.inj(1, "time savings booked as cash without a staffing change", "both",
                 f"{iid(D1)} ({INI[D1 - 1][1]}) has released capacity as its only benefit; a row claims 100 of those hours as realised cash, with no capacity_hourly_rate and no staffing change evidence.",
                 "The claim is refused CAPACITY_WITHOUT_CONVERSION; the hours stay out of the cash flow (listed as not converted, NPV from costs alone); a derived cash item exists only after a "
                 "conversion assumption with a staffing change evidence reference, and then as a separate item citing it, in a scenario built after that assumption existed (a scenario "
                 "keeps the assumptions it was built on).",
                 [{"entity": "initiatives", "id": iid(D1)}, {"entity": "benefit_items", "id": "b-inj-01"}],
                 self.checks([self.sc_path(scn_d1, D1, "excluded_from_cash_flow.capacity_hours_not_converted"), self.sc_path(scn_d1, D1, "converted_capacity"),
                              self.sc_path(scn_d1, D1, "npv.value"), self.sc_path(scn_d1, D1, "cash_flow[20].cash_benefits")]),
                 [{"entity": "benefit_items", "id": "b-inj-01", "reason_code": "CAPACITY_WITHOUT_CONVERSION", "details": steps[0]["details"]}], ["EV-01"])

        # INJ-02 / EV-02: two initiatives claim the same released capacity
        res_pair = self.read.get(f"metrics.scenarios.{scn_pair_all}.double_count")
        steps = [self.command("select-scenario", {"scenario_id": scn_pair_all, "compared_scenario_ids": [clean_draft]}, "inj-02-a", 422, "DOUBLE_COUNT_UNEXPLAINED", role="sponsor"),
                 self.command("select-scenario", {"scenario_id": scn_pair_all, "compared_scenario_ids": [clean_draft],
                                                  "residual_explanation": "Both initiatives release time of the same accounts-payable team; the larger claim is counted once and the overlap is listed."},
                              "inj-02-b", 200, None, role="sponsor"),
                 self.command("select-scenario", {"scenario_id": clean_draft}, "inj-02-c", 200, None, role="sponsor")]
        proposable = [s["scenario_id"] for s in E["scenario_versions"] if self.read.get(f"metrics.scenarios.{s['scenario_id']}.double_count.explanation_required") is False]
        chk = self.checks([f"metrics.scenarios.{scn_pair_all}.double_count.{k}" for k in ("planned_benefits", "attributable_benefits", "residual", "explanation_required")]
                          + [f"metrics.scenarios.{scn_pair_all}.double_count.overlaps[0].benefit_source_key", f"metrics.scenarios.{scn_pair_all}.double_count.overlaps[0].overlap"]
                          + [f"metrics.scenarios.{scn_pair_all}.double_count.{k}" for k in ("double_counted_amount", "double_counted_pv", "hours_residual", "explanation_required_for")]
                          + [f"metrics.scenarios.{scn_pair_all}.npv_total.{k}" for k in ("value", "sum_of_initiatives")]
                          + [f"metrics.scenarios.{p}.double_count.{k}" for p in proposable[:6] for k in ("residual", "hours_residual")])
        self.event("EV-02", "INJ-02", [scn_pair_all, clean_draft], steps)
        self.inj(2, "two initiatives claim the same released capacity", "both",
                 f"{iid(D2A)} and {iid(D2B)} both claim the time of the same accounts-payable team (benefit_source_key {SHARED_CAP_KEY}); with the capacity converted (rate pinned from May) "
                 f"the portfolio adds both claims.",
                 "The claims sharing a key in a period count once, at the larger claim; the rest is the double-count residual with the overlaps listed; select-scenario is refused "
                 "DOUBLE_COUNT_UNEXPLAINED until the residual is explained (in money or in hours, with an explanation of at least 20 characters); the portfolio NPV is the attributable one, the "
                 "sum of the initiative NPVs less the present value of the claim that counts twice; a scenario without an overlap in money or in hours (for example scn-026, the portfolio without init-002) "
                 "has both residuals at 0.00 and can be proposed without an explanation.",
                 [{"entity": "benefit_items", "id": b["benefit_id"]} for b in E["benefit_items"] if b["benefit_source_key"] == SHARED_CAP_KEY][:2], chk, [], ["EV-02"])

        # INJ-03 / EV-03: an annual rate on monthly periods
        v = self.read.validator()
        sc_row = {"scenario_id": "scn-inj-03", "baseline_version": "v2", "discount_rate": "0.080000", "rate_basis": "annual", "rate_conversion_assumption_id": None, "horizon_periods": 36,
                  "status": "draft", "initiative_ids": [iid(1)], "pinned_assumption_ids": [], "created_at": "2026-10-04T09:00:00Z"}
        steps = [self.ingest(v, "scenario_versions", sc_row, "RATE_PERIOD_MISMATCH"),
                 self.ingest(v, "scenario_versions", {**sc_row, "scenario_id": "scn-inj-03b", "rate_conversion_assumption_id": w.conv_ids[80_000]}, None),
                 self.command("build-cash-flows", {"scenario_id": "scn-inj-03", "baseline_version": "v2", "discount_rate": "0.080000", "rate_basis": "annual", "horizon_periods": 36,
                                                   "initiative_ids": [iid(1)]}, "inj-03-a", 422, "RATE_PERIOD_MISMATCH"),
                 self.command("build-cash-flows", {"scenario_id": "scn-inj-03b", "baseline_version": "v2", "discount_rate": "0.080000", "rate_basis": "annual",
                                                   "rate_conversion_assumption_id": w.conv_ids[80_000], "horizon_periods": 36, "initiative_ids": [iid(1)]}, "inj-03-b", 200)]
        conv_val = next(a["value"] for a in E["assumption_versions"] if a["assumption_id"] == w.conv_ids[80_000])
        self.event("EV-03", "INJ-03", [iid(1)], steps)
        self.inj(3, "an annual rate applied to monthly periods", "both",
                 "A scenario declares an annual discount rate of 0.08 on monthly periods and cites no conversion.",
                 "Refused RATE_PERIOD_MISMATCH, never applied raw; an annual rate is accepted only with its recorded conversion (1 + r)^(1/12) - 1, a declared six-place assumption "
                 f"version ({conv_val} for 0.08), and the scenario then reports the converted rate and its source.",
                 [{"entity": "assumption_versions", "id": w.conv_ids[80_000]}, {"entity": "scenario_versions", "id": "scn-001"}],
                 self.checks([f"metrics.scenarios.scn-001.{k}" for k in ("rate_basis", "declared_rate", "effective_period_rate", "effective_period_rate_exact", "rate_source")]),
                 [{"entity": "scenario_versions", "id": "scn-inj-03", "reason_code": "RATE_PERIOD_MISMATCH", "details": steps[0]["details"]}], ["EV-03"])

        # INJ-04 / EV-04: a benefit before deployment
        n4 = 5
        dep4 = w.t[n4]["dep"]
        v = self.read.validator()
        b4 = {"benefit_id": "b-inj-04", "initiative_id": iid(n4), "benefit_type": "cash", "amount": "9000.00", "period_index": dep4 - 3, "starts_period": dep4 - 3, "unit": "USD",
              "cash_realisation": None, "evidence_ref": None, "benefit_source_key": f"src-{n4:03d}-early", "baseline_trend_per_period": "100.00"}
        steps = [self.ingest(v, "benefit_items", b4, "BENEFIT_BEFORE_DEPLOYMENT"),
                 self.ingest(v, "benefit_items", {**b4, "benefit_id": "b-inj-04b", "period_index": dep4, "starts_period": dep4}, None),
                 self.command("build-cash-flows", {"scenario_id": "scn-inj-04", "baseline_version": "v2", "discount_rate": "0.080000", "rate_basis": "annual",
                                                   "rate_conversion_assumption_id": w.conv_ids[80_000], "horizon_periods": 36, "initiative_ids": [iid(n4)],
                                                   "benefits": [{k: val for k, val in b4.items() if k not in ("benefit_id",)}]}, "inj-04-a", 422, "BENEFIT_BEFORE_DEPLOYMENT")]
        self.event("EV-04", "INJ-04", [iid(n4)], steps)
        self.inj(4, "a benefit before deployment", "both",
                 f"A cash benefit for {iid(n4)} starts in period {dep4 - 3}, three periods before its deployment period {dep4}.",
                 "Refused BENEFIT_BEFORE_DEPLOYMENT; every benefit stream of the world starts at or after deployment (lag 0 to 2) and the adoption ramp, indexed from each row's own "
                 "starts_period, is applied beside the unramped plan.",
                 [{"entity": "benefit_items", "id": "b-inj-04"}],
                 self.checks([self.sc_path("scn-001", 1, k) for k in ("ramp.values", "planned_money_benefits.ramped", "planned_money_benefits.unramped")]),
                 [{"entity": "benefit_items", "id": "b-inj-04", "reason_code": "BENEFIT_BEFORE_DEPLOYMENT", "details": steps[0]["details"]}], ["EV-04"])

        # INJ-05 / EV-05: training completion substituted for adoption
        n5 = D4
        v = self.read.validator()
        tr_last = [t for t in E["training_completions"] if t["initiative_id"] == iid(n5)][-1]
        bad = {"observation_id": "ad-inj-05", "initiative_id": iid(n5), "eligible_count": tr_last["eligible_trainees"], "adopted_count": tr_last["completed"],
               "observed_at": "2026-10-04T09:00:00Z", "eligibility_rule_version": "elig-training"}
        over = {**bad, "observation_id": "ad-inj-05b", "eligible_count": max(1, tr_last["completed"] // 2), "eligibility_rule_version": w.t[n5]["elig"]}
        steps = [self.ingest(v, "adoption_observations", bad, "ELIGIBILITY_RULE_MISMATCH"), self.ingest(v, "adoption_observations", over, "ADOPTED_EXCEEDS_ELIGIBLE"),
                 self.command("record-adoption", {"initiative_id": iid(n5), "eligible_count": tr_last["eligible_trainees"], "adopted_count": tr_last["completed"],
                                                  "eligibility_rule_version": "elig-training"}, "inj-05-a", 422, "ELIGIBILITY_RULE_MISMATCH"),
                 self.metrics_read(self.checks([f"metrics.initiatives.{iid(n5)}.adoption.adoption_rate", f"metrics.initiatives.{iid(n5)}.training.training_completion",
                                                f"metrics.initiatives.{iid(n5)}.training.differs_from_adoption"]))]
        self.event("EV-05", "INJ-05", [iid(n5)], steps)
        self.inj(5, "training completion substituted for adoption", "both",
                 f"{iid(n5)}: nearly everyone completed training (see the figures) while adoption stalled; rows that restate training completion as adoption are offered.",
                 "Adoption and training stay two series: the adoption rate comes only from adoption observations on the initiative's eligibility rule, training completion beside it, "
                 "substituted_for_adoption false and differs_from_adoption true; the substitution rows are refused (ELIGIBILITY_RULE_MISMATCH, ADOPTED_EXCEEDS_ELIGIBLE).",
                 [{"entity": "training_completions", "id": tr_last["training_id"]}],
                 self.checks([f"metrics.initiatives.{iid(n5)}.{k}" for k in ("adoption.adoption_rate", "adoption.eligible_count", "adoption.adopted_count", "training.training_completion",
                                                                          "training.substituted_for_adoption", "training.differs_from_adoption")]),
                 [{"entity": "adoption_observations", "id": "ad-inj-05", "reason_code": "ELIGIBILITY_RULE_MISMATCH", "details": steps[0]["details"]},
                  {"entity": "adoption_observations", "id": "ad-inj-05b", "reason_code": "ADOPTED_EXCEEDS_ELIGIBLE", "details": steps[1]["details"]}], ["EV-05"])

        # INJ-06 / EV-06: a forecast overwrite
        n6 = D4
        f3 = [f for f in E["forecast_versions"] if f["initiative_id"] == iid(n6) and f["version_number"] == 1][2]
        v = self.read.validator()
        over = {**f3, "forecast_id": "f-inj-06", "amount": "1.00", "reason": "Overwrite attempt", "created_at": "2026-10-04T09:00:00Z"}
        v4 = {**f3, "forecast_id": "f-inj-06b", "version_number": 4, "reason": "Revision four", "created_at": "2026-10-04T09:00:00Z"}
        v3_rows = [f for f in E["forecast_versions"] if f["initiative_id"] == iid(n6) and f["version_number"] == 3]
        steps = [self.ingest(v, "forecast_versions", over, "VERSION_EXISTS"), self.ingest(v, "forecast_versions", v4, None),
                 self.command("revise-forecast", {"initiative_id": iid(n6), "reason": "Overwrite attempt", "periods": [{"period_index": f3["period_index"], "amount": "1.00"}],
                                                  "expected_version": 1}, "inj-06-a", 409, "STALE_FORECAST_VERSION", role="sponsor"),
                 self.command("revise-forecast", {"initiative_id": iid(n6), "reason": "Partial revision", "periods": [{"period_index": f3["period_index"], "amount": f3["amount"]}],
                                                  "expected_version": 3}, "inj-06-c", 422, "REVISION_PERIODS_INCOMPLETE", role="sponsor"),
                 self.command("revise-forecast", {"initiative_id": iid(n6), "reason": "Fourth revision", "periods": [{"period_index": f["period_index"], "amount": f["amount"]} for f in v3_rows],
                                                  "expected_version": 3}, "inj-06-b", 200, None, role="sponsor")]
        self.event("EV-06", "INJ-06", [iid(n6)], steps)
        self.inj(6, "a forecast overwrite", "both",
                 f"After the target was missed, a row rewrites version 1 of the {iid(n6)} forecast instead of adding a revision.",
                 "Refused VERSION_EXISTS (the database also refuses UPDATE and DELETE); a revision is the next version and restates every period of the original "
                 "(a partial one is REVISION_PERIODS_INCOMPLETE), the original approved version 1 stays unchanged and the comparison lists the original, every revision and the "
                 "observed values with their dates.",
                 [{"entity": "forecast_versions", "id": f3["forecast_id"]}],
                 self.checks([f"metrics.initiatives.{iid(n6)}.forecast.{k}" for k in ("original_version", "original_preserved", "latest_version", "latest_minus_original", "versions[0].total",
                                                                                   "versions[1].total", "versions[2].total", "versions[0].created_at", "versions[2].created_at")]),
                 [{"entity": "forecast_versions", "id": "f-inj-06", "reason_code": "VERSION_EXISTS", "details": steps[0]["details"]}], ["EV-06"])

        # INJ-07 / EV-07: a dependency cycle
        deps = E["dependencies"]
        chain = next((a, b) for a in deps for b in deps if b["prerequisite_id"] == a["initiative_id"] and a["prerequisite_id"] != b["initiative_id"])
        a_, b_ = chain                                   # b needs a's initiative, a's initiative needs a's prerequisite: closing: a's prerequisite needs b's initiative
        close = {"dependency_id": "d-inj-07", "initiative_id": a_["prerequisite_id"], "prerequisite_id": b_["initiative_id"], "dependency_type": "finish_to_start", "lag_periods": 0}
        v = self.read.validator()
        ok = {"dependency_id": "d-inj-07b", "initiative_id": b_["initiative_id"], "prerequisite_id": a_["prerequisite_id"], "dependency_type": "start_to_start", "lag_periods": 0}
        steps = [self.ingest(v, "dependencies", close, "DEPENDENCY_CYCLE"),
                 self.command("plan-roadmap", {"dependencies": [{k: val for k, val in close.items() if k != "dependency_id"}]}, "inj-07-a", 422, "DEPENDENCY_CYCLE"),
                 self.metrics_read(self.checks([f"metrics.initiatives.{b_['initiative_id']}.roadmap.dependency_feasible_start", f"metrics.initiatives.{b_['initiative_id']}.roadmap.binding_dependency_id"]))]
        self.event("EV-07", "INJ-07", [a_["dependency_id"], b_["dependency_id"]], steps)
        _ = ok
        self.inj(7, "a dependency cycle", "both",
                 f"{close['initiative_id']} is asked to depend on {close['prerequisite_id']} which already depends (through {a_['initiative_id']}) on it.",
                 "Refused DEPENDENCY_CYCLE with the cycle listed from the rejected edge's initiative; the 40 dependencies of the world form no cycle and every initiative has a "
                 "feasible start, the dependency delay reported beside the requested start.",
                 [{"entity": "dependencies", "id": a_["dependency_id"]}, {"entity": "dependencies", "id": b_["dependency_id"]}],
                 self.checks([f"metrics.initiatives.{b_['initiative_id']}.roadmap.{k}" for k in ("requested_start", "dependency_feasible_start", "dependency_delay", "binding_dependency_id")]),
                 [{"entity": "dependencies", "id": "d-inj-07", "reason_code": "DEPENDENCY_CYCLE", "details": steps[0]["details"]}], ["EV-07"])

        # INJ-08 / EV-08: a case that never pays back, presented with a payback
        n8 = D3
        sids = self.scenarios_with(n8)
        chk8 = []
        for sid in sids:
            chk8 += self.checks([self.sc_path(sid, n8, "payback.simple.period"), self.sc_path(sid, n8, "payback.discounted.period"), self.sc_path(sid, n8, "npv.value")])
        v = self.read.validator()
        long_sc = {"scenario_id": "scn-inj-08", "baseline_version": "v1", "discount_rate": "0.080000", "rate_basis": "annual", "rate_conversion_assumption_id": w.conv_ids[80_000],
                   "horizon_periods": 120, "status": "draft", "initiative_ids": [iid(n8)], "pinned_assumption_ids": [], "created_at": "2026-10-04T09:00:00Z"}
        steps = [self.ingest(v, "scenario_versions", long_sc, None),
                 self.command("build-cash-flows", {"scenario_id": "scn-inj-08", "baseline_version": "v1", "discount_rate": "0.080000", "rate_basis": "annual",
                                                   "rate_conversion_assumption_id": w.conv_ids[80_000], "horizon_periods": 120, "initiative_ids": [iid(n8)]}, "inj-08-a", 200, None)]
        self.event("EV-08", "INJ-08", [iid(n8)], steps)
        self.inj(8, "a case that never pays back presented with a payback", "dataset",
                 f"{iid(n8)} ({INI[n8 - 1][1]}) recovers about {INI[n8 - 1][10] // 10} % of its cost over its benefit window; a presentation shows a payback period anyway.",
                 "Simple and discounted payback are null (not 0, not rejected) in every scenario that holds it, with a negative NPV; a longer horizon does not create a payback because "
                 "the benefits end with the window; the page says it does not pay back within the horizon.",
                 [{"entity": "initiatives", "id": iid(n8)}], chk8, [], ["EV-08"])

        # INJ-09 / EV-09: a shared specialist overallocated
        v = self.read.validator()
        rows9 = [{"allocation_id": f"al-inj-09-{k}", "resource_id": D5_RESOURCE, "initiative_id": iid(12), "period_index": p, "amount": "0.50"} for k, p in enumerate(D5_PERIODS, start=1)]
        steps = [self.ingest(v, "resource_allocations", r_, "RESOURCE_OVERALLOCATED") for r_ in rows9]
        steps.append(self.ingest(v, "resource_allocations", {**rows9[0], "allocation_id": "al-inj-09-moved", "period_index": 18}, None))
        steps.append(self.command("plan-roadmap", {"allocations": [{k: val for k, val in rows9[0].items() if k != "allocation_id"}]}, "inj-09-a", 422, "RESOURCE_OVERALLOCATED"))
        self.event("EV-09", "INJ-09", [D5_RESOURCE, iid(12)], steps)
        self.inj(9, "a shared specialist overallocated", "both",
                 f"{D5_RESOURCE} (2.00 FTE) is already allocated to capacity in periods {D5_PERIODS[0]}, {D5_PERIODS[1]} and {D5_PERIODS[2]}; {iid(12)} asks for 0.50 more in each.",
                 "Each request is refused RESOURCE_OVERALLOCATED with its period (a sum equal to capacity is allowed); the refused rows are kept in the replay events; the stored "
                 "allocations show 2.00 allocated and 0.00 headroom in those periods and no overallocated period.",
                 [{"entity": "resources", "id": D5_RESOURCE}],
                 self.checks([f"metrics.resources.{D5_RESOURCE}.overallocated_periods"] + [f"metrics.resources.{D5_RESOURCE}.by_period[{k}]" for k in range(len(self.read.get(f"metrics.resources.{D5_RESOURCE}.by_period"))) if self.read.get(f"metrics.resources.{D5_RESOURCE}.by_period[{k}].period_index") in D5_PERIODS]),
                 [{"entity": "resource_allocations", "id": r_["allocation_id"], "reason_code": "RESOURCE_OVERALLOCATED", "details": s_["details"]} for r_, s_ in zip(rows9, steps[:3])], ["EV-09"])

        # INJ-10 / EV-10: an improvement attributed entirely to the rollout
        n10 = D6
        bid10 = next(b["benefit_id"] for b in E["benefit_items"] if b["initiative_id"] == iid(n10) and b["benefit_type"] == "cash" and b["period_index"] == 8)
        steps = [self.command("track-benefits", {"benefit_id": bid10, "measured_value": "50000.00", "unit": "USD", "evidence_ref": "ev:ledger-contact-centre-2026-09", "observed_on": "2026-10-04",
                                                 "attribution": "caused_by_rollout"}, "inj-10-a", 422, "ATTRIBUTION_NOT_ESTABLISHED"),
                 self.command("track-benefits", {"benefit_id": bid10, "measured_value": "50000.00", "unit": "USD", "evidence_ref": "ev:ledger-contact-centre-2026-09", "observed_on": "2026-10-04",
                                                 "attribution": "observed_not_attributed"}, "inj-10-b", 200, None)]
        self.event("EV-10", "INJ-10", [bid10], steps)
        self.inj(10, "an improvement attributed entirely to the rollout", "both",
                 f"The cash benefit of {iid(n10)} ({INI[n10 - 1][1]}) is close to plan, and a client claims all of it for the rollout; most of it is the trend that was already under way.",
                 "An observed improvement is compared with the baseline trend recorded before deployment and reported as 'observed, not attributed'; the share above the trend sits beside "
                 "the raw change, never in place of it; a claim of full attribution is refused ATTRIBUTION_NOT_ESTABLISHED.",
                 [{"entity": "initiatives", "id": iid(n10)}],
                 self.checks([self.sc_path(scn_d6, n10, f"benefit_realization.cash.{k}") for k in ("planned_comparable", "observed_comparable", "realization", "baseline_trend",
                                                                                              "observed_above_trend", "attribution")]), [], ["EV-10"])

        # INJ-11 / EV-11: a one-time cost that recurs
        first = next(c for c in E["cost_items"] if c["initiative_id"] == iid(1) and c["cost_type"] == "one_time" and c["cost_basis"] == "planned" and c["cost_key"].endswith("licence-setup-1"))
        v = self.read.validator()
        rep = {**first, "cost_id": "c-inj-11", "period_index": first["period_index"] + 4}
        rec = {**first, "cost_id": "c-inj-11b", "cost_key": first["cost_key"].replace("licence-setup-1", "licence-renewal"), "cost_type": "recurring", "period_index": None,
               "start_period": first["period_index"] + 1, "end_period": first["period_index"] + 5}
        steps = [self.ingest(v, "cost_items", rep, "ONE_TIME_COST_REPEATED"), self.ingest(v, "cost_items", rec, None),
                 self.command("build-cash-flows", {"scenario_id": "scn-inj-11", "baseline_version": "v2", "discount_rate": "0.080000", "rate_basis": "annual",
                                                   "rate_conversion_assumption_id": w.conv_ids[80_000], "horizon_periods": 36, "initiative_ids": [iid(1)],
                                                   "costs": [{k: val for k, val in rep.items() if k not in ("cost_id", "_n")}]}, "inj-11-a", 422, "ONE_TIME_COST_REPEATED")]
        self.event("EV-11", "INJ-11", [first["cost_id"]], steps)
        self.inj(11, "a one-time cost that recurs", "both",
                 f"The one-time cost {first['cost_key']} ({first['amount']}, period {first['period_index']}) is entered again {4} periods later.",
                 "The repeat is refused ONE_TIME_COST_REPEATED and the first row is kept; a cost that really recurs is a recurring row over an explicit half-open range, expanded one "
                 "row per period by the command that builds the cash flows; no cost key of the world repeats as a one-time cost.",
                 [{"entity": "cost_items", "id": first["cost_id"]}],
                 self.checks(["ingest.counts.cost_items.accepted", "ingest.counts.cost_items.rejected"]),
                 [{"entity": "cost_items", "id": "c-inj-11", "reason_code": "ONE_TIME_COST_REPEATED", "details": steps[0]["details"]}], ["EV-11"])

        # INJ-12 / EV-12: cost avoidance added to realised cash savings
        n_b, n_n, n_r = 2, 3, 1
        chk12 = self.checks([self.sc_path(scn_pair_all, n_b, "excluded_from_cash_flow.avoided_cost_beside_total"), self.sc_path(scn_pair_all, n_b, "excluded_from_cash_flow.avoided_cost_beside[0].reason"),
                             self.sc_path(scn_pair_all, n_n, "excluded_from_cash_flow.avoided_cost_beside_total"), self.sc_path(scn_pair_all, n_n, "excluded_from_cash_flow.avoided_cost_beside[0].reason"),
                             self.sc_path(scn_pair_all, n_r, "excluded_from_cash_flow.avoided_cost_beside_total"), self.sc_path(scn_pair_all, n_r, "npv.value")])
        self.event("EV-12", "INJ-12", [iid(n_b), iid(n_n), iid(n_r)], [self.metrics_read(chk12, scn_pair_all)])
        self.inj(12, "cost avoidance added to realised cash savings", "dataset",
                 f"{iid(n_b)} avoids cost that no budget line removed; {iid(n_n)} says its avoided cost is realised but cites no evidence; {iid(n_r)} removed a budget line and cites it.",
                 "Avoided cost enters the cash flow only when cash_realisation is true and an evidence_ref names the budget line removed (NPV of the evidenced item inside); the rest is "
                 "reported beside the cash flow (NOT_CASH_REALISED, NO_EVIDENCE_REF) with its total, never added and never refused.",
                 [{"entity": "benefit_items", "id": b["benefit_id"]} for b in E["benefit_items"] if b["initiative_id"] in (iid(n_b), iid(n_n)) and b["benefit_type"] == "avoided_cost"][:2],
                 chk12, [], ["EV-12"])
        self.pair_scenario, self.d1_scenario, self.d6_scenario = scn_pair, scn_d1, scn_d6

    # -- designed relationships, realised values computed by the domain ------------------------------------------------------------------------
    def designed_relationships(self) -> list[dict]:
        w, E, R = self.w, self.ents, self.read
        iid = w.iid
        out: list[dict] = []
        M = R.metrics

        # DR-01 capacity is the only benefit
        n = D1
        sid = self.d1_scenario
        blk = M["scenarios"][sid]["initiatives"][iid(n)]
        classes = sorted({b["benefit_type"] for b in E["benefit_items"] if b["initiative_id"] == iid(n)})
        hours = sum(Fraction(b["amount"]) for b in E["benefit_items"] if b["initiative_id"] == iid(n))
        out.append({"id": "DR-01", "name": "an initiative whose only benefit is released capacity",
                    "statement": f"{iid(n)} plans only capacity hours; with no conversion there is no cash case.",
                    "realised": {"initiative_id": iid(n), "scenario_id": sid, "benefit_classes": classes, "planned_hours": rhu(hours, 2),
                                 "capacity_hours_not_converted": blk["excluded_from_cash_flow"]["capacity_hours_not_converted"], "converted_capacity_items": len(blk["converted_capacity"]),
                                 "cash_benefits_total": rhu(sum(Fraction(r_["cash_benefits"]) for r_ in blk["cash_flow"]), 2), "npv": blk["npv"]["value"],
                                 "simple_payback": blk["payback"]["simple"]["period"], "capacity_released_hours_per_period": blk["capacity_released"]["hours"]}})

        # DR-02 two initiatives claim the same released capacity
        sid = "scn-025"
        dc = M["scenarios"][sid]["double_count"]
        resid = [s["scenario_id"] for s in E["scenario_versions"] if M["scenarios"][s["scenario_id"]]["double_count"]["residual"] != "0.00"]
        hres = [s["scenario_id"] for s in E["scenario_versions"] if M["scenarios"][s["scenario_id"]]["double_count"]["hours_residual"] != "0.00"]
        out.append({"id": "DR-02", "name": "two initiatives claim the same released capacity",
                    "statement": f"{iid(D2A)} and {iid(D2B)} both claim the accounts-payable team's time (benefit_source_key {SHARED_CAP_KEY}).",
                    "realised": {"scenario_id": sid, "initiatives": [iid(D2A), iid(D2B)], "benefit_source_key": SHARED_CAP_KEY, "planned_benefits": dc["planned_benefits"],
                                 "attributable_benefits": dc["attributable_benefits"], "residual": dc["residual"], "overlap_periods": len(dc["overlaps"]),
                                 "first_overlap_period": dc["overlaps"][0]["period_index"], "last_overlap_period": dc["overlaps"][-1]["period_index"],
                                 "scenarios_with_a_residual": resid,
                                 "scenarios_with_no_residual": [s["scenario_id"] for s in E["scenario_versions"] if s["scenario_id"] not in resid],
                                 "double_counted_pv": dc["double_counted_pv"], "npv_total_attributable": M["scenarios"][sid]["npv_total"]["value"],
                                 "npv_sum_of_initiatives": M["scenarios"][sid]["npv_total"]["sum_of_initiatives"], "hours_residual": dc["hours_residual"],
                                 "scenarios_with_an_hours_residual": hres}})

        # DR-03 never pays back: every ratio names its scenario (the ramp the scenario pins changes the benefits that enter the cash flow)
        n = D3
        sids = self.scenarios_with(n)
        rows = [M["scenarios"][s]["initiatives"][iid(n)] for s in sids]
        npvs = sorted(Fraction(b["npv"]["exact"]) for b in rows)
        per_scn = {}
        for sid_, b in zip(sids, rows):
            cost_s = sum((Fraction(x["costs"]) for x in b["cash_flow"]), Fraction(0))                     # planned costs inside the scenario's horizon
            ben_s = sum((Fraction(x["cash_benefits"]) for x in b["cash_flow"]), Fraction(0))
            per_scn[sid_] = {"planned_cost": rhu(cost_s, 2), "benefits_entering_the_cash_flow": rhu(ben_s, 2), "benefit_to_cost": rhu(ben_s / cost_s, 6), "npv": b["npv"]["value"],
                             "ramp_assumption_id": b["ramp"]["assumption_id"] if b["ramp"] else None}
        by_ratio: dict[str, list[str]] = {}
        for sid_, v_ in per_scn.items():
            by_ratio.setdefault(v_["benefit_to_cost"], []).append(sid_)
        out.append({"id": "DR-03", "name": "an initiative that never pays back",
                    "statement": f"{iid(n)} recovers well under its cost over its benefit window; the ratio depends on the adoption ramp the scenario pins, so each value names its scenarios.",
                    "realised": {"initiative_id": iid(n), "scenarios": sids, "scenarios_with_simple_payback_null": sum(1 for b in rows if b["payback"]["simple"]["period"] is None),
                                 "scenarios_with_discounted_payback_null": sum(1 for b in rows if b["payback"]["discounted"]["period"] is None),
                                 "npv_lowest": rhu(npvs[0], 2), "npv_highest": rhu(npvs[-1], 2), "by_scenario": per_scn, "scenarios_by_benefit_to_cost": by_ratio}})

        # DR-04 forecast revised twice after a missed target, the original kept
        n = D4
        fc = M["initiatives"][iid(n)]["forecast"]
        readings: dict[int, list[tuple[str, Fraction]]] = {}
        for o in fc["observed"]:
            if o["period_matured"]:
                readings.setdefault(o["period_index"], []).append((o["observed_at"], Fraction(o["measured_value"])))
        obs = {p: sorted(rs)[-1][1] for p, rs in readings.items()}
        vers = {v["version_number"]: {r_["period_index"]: Fraction(r_["amount"]) for r_ in v["by_period"]} for v in fc["versions"]}
        misses = []
        for v in fc["versions"][1:]:
            k = v["version_number"]
            prev = vers[k - 1]
            before = vers[k - 2] if k >= 3 else None
            revised = [p for p in prev if before is None or prev[p] != before[p]]           # the periods the previous version itself revised
            seen = {}
            for p in revised:
                got = [val for at_, val in sorted(readings.get(p, [])) if at_ <= v["created_at"]]
                if got:
                    seen[p] = got[-1]
            short = {p: (o, prev[p]) for p, o in seen.items() if o * 100 < prev[p] * (100 - FORECAST_MISS_TOLERANCE_PCT)}
            misses.append({"revision": k, "created_at": v["created_at"], "revises_version": k - 1, "periods_checked": sorted(seen), "periods_below_the_previous_forecast": sorted(short),
                           "observed_over_forecast": {str(p): rhu(o / prev[p], 6) for p, (o, _) in sorted(short.items())},
                           "all_checked_periods_observed_over_forecast": {str(p): rhu(o / prev[p], 6) for p, o in sorted(seen.items())}})
        out.append({"id": "DR-04", "name": "a forecast revised twice after a missed target, the original kept",
                    "statement": f"{iid(n)}'s approved forecast (version 1) is revised in June and again in September after the observed cash benefit fell short.",
                    "realised": {"initiative_id": iid(n), "versions": [{"version_number": v["version_number"], "created_at": v["created_at"], "total": v["total"], "reason": v["reason"]} for v in fc["versions"]],
                                 "original_preserved": fc["original_preserved"], "latest_minus_original": fc["latest_minus_original"], "miss_tolerance_percent": FORECAST_MISS_TOLERANCE_PCT,
                                 "misses": misses, "latest_observed": {str(p): rhu(o, 2) for p, o in sorted(obs.items())}}})

        # DR-05 a shared specialist at capacity: designed for three periods, the periods the domain finds are the realised ones
        res = M["resources"][D5_RESOURCE]
        byp = {b["period_index"]: b for b in res["by_period"]}
        full = sorted(p for p, b in byp.items() if b["headroom"] == "0.00")
        refused = [x for x in self.events if x["event_id"] == "EV-09"][0]["steps"][:3]
        out.append({"id": "DR-05", "name": "a shared specialist at capacity",
                    "statement": f"{D5_RESOURCE} is designed to be allocated to capacity in periods {list(D5_PERIODS)}; the periods at capacity in the rows are in realised.periods (the draws "
                                 "also fill it earlier); further requests there are refused at ingest and kept in the replay events.",
                    "realised": {"resource_id": D5_RESOURCE, "capacity_per_period": res["capacity_per_period"], "designed_periods": list(D5_PERIODS), "periods": full,
                                 "allocated": {str(p): byp[p]["allocated"] for p in full}, "headroom": {str(p): byp[p]["headroom"] for p in full},
                                 "stored_overallocated_periods": res["overallocated_periods"], "requests_refused": len(refused),
                                 "refused_periods": [s["details"]["periods"][0] for s in refused], "requested": [s["details"]["requested"] for s in refused],
                                 "initiatives_allocated_in_those_periods": sorted({a["initiative_id"] for a in E["resource_allocations"] if a["resource_id"] == D5_RESOURCE and a["period_index"] in full})}})

        # DR-06 an observed improvement that is mostly the baseline trend
        n = D6
        sid = self.d6_scenario
        rb = M["scenarios"][sid]["initiatives"][iid(n)]["benefit_realization"]["cash"]
        share = Fraction(rb["baseline_trend"]) / Fraction(rb["observed_comparable"])
        out.append({"id": "DR-06", "name": "an observed improvement that is mostly the baseline trend",
                    "statement": f"{iid(n)}'s cash benefit is close to plan, and most of it is the trend recorded before deployment.",
                    "realised": {"initiative_id": iid(n), "scenario_id": sid, "comparable_rows": len(rb["comparable_items"]), "planned_comparable": rb["planned_comparable"],
                                 "observed_comparable": rb["observed_comparable"], "realization": rb["realization"], "baseline_trend": rb["baseline_trend"],
                                 "observed_above_trend": rb["observed_above_trend"], "trend_share_of_observed": rhu(share, 6), "attribution": rb["attribution"],
                                 "parameter_trend_share_percent": SHARE_ABOVE_TREND}})

        # DR-07 adoption lags training completion
        lags = []
        for n in ADOPTION_INI:
            tr = [t for t in E["training_completions"] if t["initiative_id"] == iid(n)]
            t90 = next((t["recorded_at"] for t in tr if t["completed"] * 100 >= t["eligible_trainees"] * 90), None)
            series = M["initiatives"][iid(n)]["adoption"]["series"]
            a50 = next((x["observed_at"] for x in series if x["adoption_rate"] is not None and Fraction(x["adoption_rate"]) >= Fraction(1, 2)), None)
            lag = month_index(a50) - month_index(t90) if t90 and a50 else None
            so_far = month_index(AS_OF_TEXT) - month_index(t90) if t90 else None
            lags.append({"initiative_id": iid(n), "training_90_percent_on": t90, "adoption_50_percent_on": a50, "lag_periods": lag, "periods_since_training_90_percent": so_far,
                         "training_completion_now": M["initiatives"][iid(n)]["training"]["training_completion"], "adoption_rate_now": M["initiatives"][iid(n)]["adoption"]["adoption_rate"]})
        reached = sorted(x["lag_periods"] for x in lags if x["lag_periods"] is not None)
        out.append({"id": "DR-07", "name": "adoption that lags training completion by several periods",
                    "statement": "In every initiative with both series, 90 % of the eligible trainees complete training long before half of the eligible staff have adopted.",
                    "realised": {"initiatives": lags, "lag_periods_sorted": reached, "initiatives_whose_adoption_never_reached_50_percent": [x["initiative_id"] for x in lags if x["lag_periods"] is None],
                                 "training_completion_summary": R.metrics["summary"]["training_completion"], "adoption_rate_summary": R.metrics["summary"]["adoption_rate"]}})
        return out


# ---------------------------------------------------------------------------------------------------------------------------------------------
# build and write
# ---------------------------------------------------------------------------------------------------------------------------------------------
DISCLOSURES = [
    "Every designed relationship is built into the draws as a parameter chosen before the first run: the capacity-only initiative (init-009), the shared capacity pool (init-001 and "
    "init-002, key src-fin-ap-shared-team), the benefit-to-cost ratio of 0.62 for init-015, the forecast misses of init-003 (observed at 68 and 66 per cent of plan, revised forecasts at 80 and "
    "70 per cent, a miss being more than 10 per cent below the forecast), the specialist res-03 filled to capacity in periods 14 to 16 (the rows also fill it earlier; the periods at "
    "capacity are computed by the domain and listed in DR-05), the baseline trend of init-008 set to 85 per "
    "cent of its observed cash benefit, and an adoption curve that starts at go-live while training ends about a month earlier. Their realised values are in designed_relationships.",
    "Outcome-informed changes after the first runs, all kept: (1) the first run showed a simple payback of 0 for any initiative whose first cash flow is after period 0 (the domain's "
    "rule D-P9-07 counts a cumulative of 0 at t = 0 as paid back), so every initiative now carries a small planned discovery cost in period 0 (2 per cent of its one-time cost) and "
    "its payback is measured from a negative position; (2) the benefit shares of an initiative are normalised to 100 per cent after a first run gave init-007 a ratio below 1 for a "
    "reason that was a bug, not a design; (3) init-002 is sized at no less than 8,000 cases a month and 24 minutes so that its overlap with init-001 is a material residual; (4) "
    "benefit observations were first drawn with three readings per matured row, which gave 332 readings, so two further readings (a flash reading one to two days after the period "
    "and a restated reading 95 to 120 days after it) were added, and readings were then trimmed or added in a fixed shuffled order to reach exactly 400; (5) the baseline trend "
    "recorded on an observed row is drawn as a share of that row's observed value (5 to 25 per cent, and 85 per cent for init-008), so the trend was fixed after the observation it is "
    "compared with: a design choice made after the outcome was known, in this synthetic world only.",
    "Sizes are exact by construction, not by tuning outcomes: benefit rows are 12 per stream (shortened or lengthened one row at a time in a fixed order to reach 700), cost items are "
    "completed with contingency tranches (see pad_notes), adoption observations are the 3.5-day telemetry candidates thinned by drawn outages to 500, and training completions are "
    "weekly readings thinned or extended with refresher readings to 200.",
    "The business case recognises benefits for 12 periods per stream and recurring costs run only over that window (D-07): the dataset has 700 benefit rows, which cannot cover 36 "
    "periods for all 24 initiatives, so payback and NPV describe the twelve-period benefit window (some streams are shorter), not a three-year case.",
    "The synthetic counterfactual (the true share of each observed improvement that the rollout caused, and the true trend) is in synthetic_truth of this manifest only and is never "
    "loaded by the seeder, the API or the web.",
    "Baseline trends on observed rows are drawn as a share of the row's observed value (5 to 25 per cent, with a per-stream estimation error of -8 to +8 per cent), which is "
    "outcome-informed by design: a trend recorded before deployment cannot depend on a later observation in the real world.",
    "The adoption ramp of each initiative (the days from go-live to full effect) was first drawn from 190 to 330 days; the first run gave a lag of 2 periods for the earliest "
    "initiative, which is not 'several', so the range was moved to 270 to 340 days before the final run. The forecast of init-003: the second observed ratio was first 70 per "
    "cent of plan, which left June only 0.1 point inside the 10 per cent tolerance of the revised forecast, so it became 66 per cent, and the second revision moved from 10 to 12 June "
    "so that every May reading exists when it is made. No other parameter was changed after seeing the designed relationships.",
]


def parameters(w: World, extra: list[str] | None = None) -> dict[str, str]:
    return {"seed": str(w.seed), "profile": "demo (section 12): about 500 primary business objects, enough linked events for every required path",
            "period_basis": "monthly", "periods": "36 (2026-01 .. 2028-12)", "as_of": AS_OF_TEXT, "matured_periods_at_as_of": "9 (2026-01 .. 2026-09)",
            "initiatives": "24 in 4 programmes", "process_baselines": "30 (18 initiatives v1, 12 corrected to v2)", "discount_rates": "annual 0.06/0.08/0.10/0.12 with monthly_rate_conversion "
            "assumption versions; 0.007000 declared monthly", "benefit_life": f"{BENEFIT_LIFE} periods per stream", "benefit_lag": "0 to 2 periods after deployment",
            "forecast_miss_tolerance_percent": str(FORECAST_MISS_TOLERANCE_PCT), "trend_share_dr06_percent": str(SHARE_ABOVE_TREND),
            "d4_observed_over_plan_percent": f"{D4_PERF[0]} then {D4_PERF[1]}", "d4_revised_forecast_percent_of_plan": f"{D4_REVISION[0]} then {D4_REVISION[1]}",
            "size_cap_bytes": str(SIZE_CAP), "disclosures": " | ".join(DISCLOSURES + (extra or []))}


def build(seed: int) -> tuple[World, dict[str, list[dict]], Injections]:
    w = World(seed)
    w.build_all()
    ents = w.entities()
    version = f"{VERSION_TAG}-{seed}-{DATE_TAG}"
    inj = Injections(w, ents, version)
    inj.build()
    inj.designed = inj.designed_relationships()
    return w, ents, inj


def write_all(seed: int, out: Path) -> dict[str, Any]:
    w, ents, inj = build(seed)
    version = f"{VERSION_TAG}-{seed}-{DATE_TAG}"
    dhash = dataset_hash(ents)
    out.mkdir(parents=True, exist_ok=True)
    nbytes = 0
    for name in ENTITIES:
        text = entity_text(name, version, ents[name])
        nbytes += len(text.encode())
        (out / f"{name}.json").write_text(text)
    R = inj.read
    counts = R.result.counts
    objects = sum(len(ents[e]) for e in ("initiatives", "process_baselines", "assumption_versions", "resources", "scenario_versions", "cost_items", "benefit_items", "dependencies",
                                          "stakeholder_groups", "impact_mappings", "resource_allocations", "risk_items")) + len({(f["initiative_id"], f["version_number"]) for f in ents["forecast_versions"]})
    events = sum(len(ents[e]) for e in ("readiness_assessments", "adoption_observations", "training_completions", "benefit_observations")) + len(ents["forecast_versions"])
    warn: dict[str, int] = {}
    for x in R.result.warnings:
        warn[x["code"]] = warn.get(x["code"], 0) + 1
    scen_table = {sid: {"status": s["status"], "baseline_version": s["baseline_version"], "horizon_periods": s["horizon_periods"], "rate_source": s["rate_source"],
                        "effective_period_rate": s["effective_period_rate"], "npv_total": s["npv_total"]["value"], "double_count_residual": s["double_count"]["residual"]}
                  for sid, s in R.metrics["scenarios"].items()}
    initiatives = {}
    for iid_, b in R.metrics["scenarios"]["scn-025"]["initiatives"].items():
        initiatives[iid_] = {"npv": b["npv"]["value"], "simple_payback": b["payback"]["simple"]["period"], "discounted_payback": b["payback"]["discounted"]["period"],
                             "capacity_released_hours": b["capacity_released"]["hours"], "cost_variance": b["cost_variance"]["variance"],
                             "adoption_rate": R.metrics["initiatives"][iid_]["adoption"]["adoption_rate"], "training_completion": R.metrics["initiatives"][iid_]["training"]["training_completion"]}
    early = [{"initiative_id": i_, "deployment_period": x["roadmap"]["deployment_period"], "dependency_feasible_start": x["roadmap"]["dependency_feasible_start"],
              "periods_early": x["roadmap"]["warnings"][0]["periods_early"]} for i_, x in R.metrics["initiatives"].items() if x["roadmap"]["warnings"]]
    each = "; ".join("{} deploys at {} but cannot start before {}".format(e_["initiative_id"], e_["deployment_period"], e_["dependency_feasible_start"]) for e_ in early)
    early_note = (f"{len(early)} initiatives book benefits from a deployment period earlier than their dependency-feasible start ({each}): "
                  "the draws set deployment periods and dependencies independently. The domain reports DEPLOYMENT_BEFORE_FEASIBLE_START on each and does not re-time the cash flow (D-P9-08).")
    truth = {k: {"observed_comparable_cents": v[0], "true_trend_cents": v[1], "true_attributable_share": rhu(Fraction(v[0] - v[1], v[0]), 6)} for k, v in sorted(w.truth.get("trend", {}).items())}
    manifest = {
        "dataset_version": version, "dataset_hash": dhash, "generated_at": AS_OF_TEXT, "contract_version": CONTRACT_VERSION, "as_of": AS_OF_TEXT,
        "config": {"contract_version": 1, "period_basis": "monthly", "period_start": "2026-01-01", "periods": PERIODS, "as_of": AS_OF_TEXT},
        "generator": {"name": "generate.py", "seed": seed, "parameters": parameters(w, [early_note])},
        "programmes": [{"programme_id": pid, "name": name, "sponsor_id": sp, "approved_baseline_version": bv,
                        "initiative_ids": [w.iid(n) for n in sorted(w.t) if w.t[n]["pi"] == pi]} for pi, (pid, name, sp, bv) in enumerate(PROGRAMMES)],
        "row_counts": {name: len(ents[name]) for name in ENTITIES}, "designed_relationships": inj.designed, "injection_manifest": "injection-manifest.json",
        "stats": {"entity_file_bytes": nbytes, "forecast_version_sets": len({(f["initiative_id"], f["version_number"]) for f in ents["forecast_versions"]}), "primary_objects": objects, "linked_events": events, "ingest": {e: counts[e] for e in sorted(counts)},
                  "warnings": dict(sorted(warn.items())), "summary": R.metrics["summary"], "scenarios": scen_table, "initiatives_in_scn-025": initiatives,
                  "deployment_before_feasible_start": early, "pad_notes": w.pad_notes, "adoption_parameters": {w.iid(n): p for n, p in sorted(w.adopt_params.items())}},
        "synthetic_truth": {"note": "Synthetic counterfactual for the verification layer only: the true share of each observed improvement that the rollout caused. It is never loaded by "
                                    "the seeder, the API or the web.", "by_initiative_and_type": truth}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    inj_doc = {"dataset_version": version, "dataset_hash": dhash, "seed": seed, "contract_version": CONTRACT_VERSION, "injections": inj.injections,
               "designed_relationships": inj.designed, "events": inj.events}
    (out / "injection-manifest.json").write_text(json.dumps(inj_doc, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=APP_ROOT / "web" / "public" / "data")
    ap.add_argument("--inputs", type=Path, help="also write one inputs object for data/seed.py to this path (not committed)")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    m = write_all(args.seed, args.out)
    if args.inputs:
        _, ents, _ = build(args.seed)
        args.inputs.write_text(json.dumps(to_inputs(ents), sort_keys=True))
    total = sum(p.stat().st_size for p in args.out.rglob("*.json"))
    print(json.dumps({"dataset_version": m["dataset_version"], "dataset_hash": m["dataset_hash"], "row_counts": m["row_counts"], "bytes": total,
                      "elapsed_seconds": round(time.perf_counter() - t0, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
