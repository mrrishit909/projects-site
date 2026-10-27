#!/usr/bin/env python3
"""TrustLedger synthetic data generator (P07-WORK-03, docs/data-generator.md).

Stdlib only; nothing is imported from ``domain/`` (the measures, the score and the schedule are restated from docs/contracts.md
D-01..D-07 and compared with the domain by ``tests/test_generator.py``). A master ``random.Random(seed)`` hands one child stream to
each purpose; every probability is parts per million and every draw is ``randrange``; instants are ``datetime`` arithmetic on
fixed UTC offsets; no float is written or used to decide anything. Same seed, same bytes (PYTHONHASHSEED 0/1/2).

    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --profile golden-shape-check
    python data/generate.py --inputs /tmp/inputs.json      # one inputs object for data/seed.py (not committed)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
CONTRACT_VERSION = "v1"
T0 = datetime(2026, 7, 13, tzinfo=UTC)
N_DAYS = 84                                           # 2026-07-13 .. 2026-10-04
AS_OF = datetime(2026, 10, 5, tzinfo=UTC)
WEIGHT_CHANGE = datetime(2026, 9, 1, tzinfo=UTC)
EARLY_CUT = datetime(2026, 8, 25, tzinfo=UTC)         # before this no issue is left open (they are resolved or claimed)
TRIM = " \t\r\n"
VERSION_TAG = "tl"

PURPOSES = ("owners", "datasets", "rules", "rows", "runs", "issues", "lineage", "metrics", "customers", "matching", "injections")

ENTITIES = tuple(sorted(("owners", "datasets", "fields", "quality_rules", "rule_runs", "issues", "lineage_edges", "metric_versions",
                         "definition_changes", "customer_records", "match_candidates", "merge_decisions", "dataset_rows",
                         "weight_versions")))
DOMAIN12 = ("owners", "datasets", "fields", "quality_rules", "rule_runs", "issues", "lineage_edges", "metric_versions",
            "definition_changes", "customer_records", "match_candidates", "merge_decisions")

WEIGHTS = [
    {"weight_version": "w1", "valid_from": "2026-01-01T00:00:00Z",
     "weights": {"completeness": "0.400000", "validity": "0.300000", "uniqueness": "0.200000", "relationship": "0.050000", "timeliness": "0.050000"}},
    {"weight_version": "w2", "valid_from": "2026-09-01T00:00:00Z",
     "weights": {"completeness": "0.250000", "validity": "0.250000", "uniqueness": "0.250000", "relationship": "0.150000", "timeliness": "0.100000"}}]
DIMS = ("completeness", "validity", "uniqueness", "relationship", "timeliness")
CONFIG = {"contract_version": 1, "as_of": "2026-10-05T00:00:00Z", "whitespace_policy": {"name": "trim_empty_is_missing", "trim_characters": TRIM},
          "weight_version": "w2", "checklist_version": "cl-1",
          "checklist_versions": [{"checklist_version": "cl-1", "items": ["definition", "grain", "source_fields", "owner", "refresh"]}],
          "probes": {"definition_at": "2026-08-01T00:00:00Z"}}

# fixed UTC offsets in minutes: no transition of these zones falls in 2026-07-13 .. 2026-10-05 (US 11-01, EU 10-25); tests check zoneinfo
OFFSET_MIN = {"UTC": 0, "America/New_York": -240, "America/Chicago": -300, "Europe/London": 60, "Europe/Berlin": 120,
              "Asia/Kolkata": 330, "Asia/Singapore": 480}
ZONES = tuple(OFFSET_MIN)

# ---- the register -----------------------------------------------------------------------------------------------------------
OWNERS = [  # id, name, team, role, deactivated_at
    ("own-01", "Ansel Whitcombe", "Data Governance", "admin", None), ("own-02", "Briar Delacroix", "Data Governance", "steward", None),
    ("own-03", "Corvin Ashdown", "Data Governance", "analyst", None), ("own-04", "Delphine Marrow", "Data Platform", "steward", None),
    ("own-05", "Eamon Fairweather", "Data Platform", "analyst", None), ("own-06", "Fenna Lindqvist", "Data Platform", "admin", None),
    ("own-07", "Garrick Tolland", "Customer Data", "steward", None), ("own-08", "Hesper Valdane", "Customer Data", "analyst", None),
    ("own-09", "Ione Kestrel", "Customer Data", "steward", "2026-08-18T09:00:00Z"),
    ("own-10", "Jorin Blackwater", "Finance Systems", "steward", None), ("own-11", "Kestra Maddox", "Finance Systems", "analyst", None),
    ("own-12", "Linden Thorpe", "Finance Systems", "admin", "2026-09-04T09:00:00Z"),
    ("own-13", "Marisol Venn", "Supply Chain", "steward", None), ("own-14", "Nikolai Pryce", "Supply Chain", "analyst", None),
    ("own-15", "Odessa Quillfeather", "Supply Chain", "analyst", "2026-09-22T09:00:00Z"),
    ("own-16", "Perrin Haldane", "Support Operations", "steward", None), ("own-17", "Quentin Brightwell", "Support Operations", "analyst", None),
    ("own-18", "Rowena Stray", "Support Operations", "admin", None)]
FAST_TEAM = "Data Platform"

# id, name, system, classification, key field, core fields, has rows, monitored, registered day index (None = before the window)
DS = [
    ("ds-customers", "Customers", "crm", "restricted", "customer_key", ["email", "full_name", "phone", "postal_code"], 1, 1, None),
    ("ds-contacts", "Contacts", "crm", "confidential", "contact_key", ["customer_key", "email", "full_name"], 1, 1, None),
    ("ds-accounts", "Accounts", "crm", "confidential", "account_key", ["customer_key", "account_name", "tier"], 1, 0, None),
    ("ds-leads", "Leads", "crm", "confidential", "lead_key", ["email", "full_name", "lead_source"], 1, 0, None),
    ("ds-opportunities", "Opportunities", "crm", "internal", "opportunity_key", ["account_key", "amount", "stage"], 1, 0, None),
    ("ds-campaigns", "Campaigns", "crm", "internal", "campaign_key", ["campaign_name", "channel", "budget_amount"], 0, 1, None),
    ("ds-crm-activities", "CRM activities", "crm", "internal", "activity_key", ["contact_key", "activity_type", "occurred_at"], 0, 0, None),
    ("ds-segments", "Segments", "crm", "internal", "segment_key", ["segment_name", "rule_text"], 0, 0, None),
    ("ds-invoices", "Invoices", "billing", "confidential", "invoice_key", ["customer_key", "currency", "due_date", "amount"], 1, 1, None),
    ("ds-payments", "Payments", "billing", "restricted", "payment_key", ["invoice_key", "amount", "paid_at"], 1, 1, None),
    ("ds-subscriptions", "Subscriptions", "billing", "confidential", "subscription_key", ["customer_key", "plan_code", "started_on"], 1, 1, None),
    ("ds-refunds", "Refunds", "billing", "confidential", "refund_key", ["payment_key", "reason_code", "amount"], 1, 0, None),
    ("ds-credit-notes", "Credit notes", "billing", "internal", "credit_note_key", ["invoice_key", "amount"], 0, 0, None),
    ("ds-price-books", "Price books", "billing", "internal", "price_book_key", ["currency", "effective_from"], 0, 1, None),
    ("ds-billing-accounts", "Billing accounts", "billing", "restricted", "billing_account_key", ["customer_key", "payment_terms"], 0, 0, None),
    ("ds-orders", "Orders", "erp", "confidential", "order_key", ["customer_key", "order_date", "currency", "order_total"], 1, 1, None),
    ("ds-order-lines", "Order lines", "erp", "internal", "order_line_key", ["order_key", "product_code", "quantity"], 1, 0, None),
    ("ds-products", "Products", "erp", "internal", "product_code", ["product_name", "category", "unit_cost"], 1, 0, None),
    ("ds-suppliers", "Suppliers", "erp", "confidential", "supplier_key", ["supplier_name", "contact_email"], 1, 0, None),
    ("ds-purchase-orders", "Purchase orders", "erp", "confidential", "purchase_order_key", ["supplier_key", "amount", "ordered_on"], 1, 1, None),
    ("ds-ledger-entries", "Ledger entries", "erp", "restricted", "entry_key", ["currency", "amount", "cost_centre_code", "posted_on"], 1, 0, None),
    ("ds-cost-centres", "Cost centres", "erp", "internal", "cost_centre_code", ["cost_centre_name", "owner_ref"], 1, 0, None),
    ("ds-employees", "Employees", "erp", "restricted", "employee_key", ["work_email", "full_name", "department_code"], 1, 0, None),
    ("ds-tickets", "Tickets", "support", "confidential", "ticket_key", ["customer_key", "priority", "opened_at"], 1, 1, None),
    ("ds-ticket-events", "Ticket events", "support", "internal", "event_key", ["ticket_key", "event_type", "occurred_at"], 1, 0, 8),
    ("ds-kb-articles", "Knowledge articles", "support", "public", "article_key", ["title", "topic"], 1, 0, 63),
    ("ds-csat-surveys", "CSAT surveys", "support", "confidential", "survey_key", ["ticket_key", "score", "responded_at"], 1, 0, None),
    ("ds-support-agents", "Support agents", "support", "restricted", "agent_key", ["full_name", "team_code"], 0, 0, None),
    ("ds-sla-policies", "SLA policies", "support", "internal", "policy_key", ["policy_name", "target_minutes"], 0, 1, None),
    ("ds-shipments", "Shipments", "logistics", "internal", "shipment_key", ["order_key", "carrier_code", "tracking_ref", "shipped_on"], 1, 1, None),
    ("ds-warehouses", "Warehouses", "logistics", "internal", "warehouse_code", ["warehouse_name", "postal_code", "region_code"], 1, 0, None),
    ("ds-inventory", "Inventory", "logistics", "internal", "inventory_key", ["product_code", "warehouse_code", "on_hand"], 1, 1, None),
    ("ds-carriers", "Carriers", "logistics", "internal", "carrier_code", ["carrier_name", "service_level"], 1, 0, None),
    ("ds-returns", "Returns", "logistics", "internal", "return_key", ["order_key", "reason_code", "returned_on"], 1, 0, None),
    ("ds-delivery-events", "Delivery events", "logistics", "internal", "event_ref", ["shipment_key", "event_type", "occurred_at"], 1, 0, 28),
    ("ds-web-sessions", "Web sessions", "web", "internal", "session_key", ["user_key", "started_at", "device"], 1, 0, None),
    ("ds-page-events", "Page events", "web", "internal", "page_event_key", ["session_key", "page_path"], 0, 0, None),
    ("ds-web-users", "Web users", "web", "restricted", "user_key", ["email", "signup_date"], 1, 1, None),
    ("ds-consent-records", "Consent records", "web", "restricted", "consent_key", ["user_key", "consent_flag", "recorded_at"], 1, 1, 42),
    ("ds-experiments", "Experiments", "web", "internal", "experiment_key", ["experiment_name", "hypothesis"], 0, 0, None)]
GENERIC = ["status", "created_date", "updated_at", "region_code", "source_ref", "category", "amount", "currency", "owner_ref", "channel",
           "country_code", "segment", "priority", "version_tag", "batch_id", "external_ref", "effective_from", "effective_to", "quantity",
           "notes_flag", "language_code", "cost_band"]
FIELD_TOTAL = 420

# type, dataset, field, severity, extra.  60 rules: completeness 14, validity 12, uniqueness 11, relationship 13, timeliness 10.
PATTERNS = {"email": r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", "ccy": r"^[A-Z]{3}$", "tracking": r"^[A-Z]{2}[0-9]{9}$", "zip": r"^[0-9]{5}$",
            "ticket": r"^TK-[0-9]{6}$", "evref": r"^EV-[0-9]{8}$", "carrier": r"^[A-Z]{3,5}$"}
INVALID = {"email": ["no-at-sign.example.com", "two@@example.com", "name@nodot", "sp ace@example.com", "name@example.c"],
           "ccy": ["usd", "US", "EURO", "U$D"], "tracking": ["12AB34567", "ZZ12345", "zz123456789"], "zip": ["1234", "ABCDE", "123456"],
           "ticket": ["tk-000123", "TK123", "TK-12A456"], "evref": ["EV-123", "ev-00000001"], "carrier": ["d", "dhl!", "UPS-1"]}
R = [
    ("C", "ds-customers", "email", "high"), ("V", "ds-customers", "email", "medium", "email"), ("U", "ds-customers", "customer_key", "critical"),
    ("T", "ds-customers", None, "medium"),
    ("C", "ds-contacts", "email", None), ("R", "ds-contacts", "customer_key", None, ("ds-customers", "customer_key")),
    ("U", "ds-accounts", "account_key", None), ("R", "ds-accounts", "customer_key", None, ("ds-customers", "customer_key")),
    ("V", "ds-leads", "email", None, "email"),
    ("R", "ds-opportunities", "account_key", None, ("ds-accounts", "account_key")),
    ("R", "ds-orders", "customer_key", "high", ("ds-customers", "customer_key")), ("C", "ds-orders", "order_date", None),
    ("V", "ds-orders", "currency", None, "ccy"), ("T", "ds-orders", None, None), ("U", "ds-orders", "order_key", "critical"),
    ("R", "ds-order-lines", "order_key", "critical", ("ds-orders", "order_key")), ("R", "ds-order-lines", "product_code", None, ("ds-products", "product_code")),
    ("U", "ds-products", "product_code", None), ("C", "ds-products", "category", None),
    ("R", "ds-invoices", "customer_key", None, ("ds-customers", "customer_key")), ("V", "ds-invoices", "currency", None, "ccy"), ("T", "ds-invoices", None, None),
    ("R", "ds-payments", "invoice_key", None, ("ds-invoices", "invoice_key")), ("U", "ds-payments", "payment_key", "critical"), ("T", "ds-payments", None, None),
    ("R", "ds-subscriptions", "customer_key", None, ("ds-customers", "customer_key")), ("C", "ds-subscriptions", "plan_code", None),
    ("R", "ds-refunds", "payment_key", None, ("ds-payments", "payment_key")),
    ("C", "ds-suppliers", "contact_email", None), ("V", "ds-suppliers", "contact_email", None, "email"), ("U", "ds-suppliers", "supplier_key", None),
    ("R", "ds-purchase-orders", "supplier_key", None, ("ds-suppliers", "supplier_key")), ("T", "ds-purchase-orders", None, None),
    ("V", "ds-ledger-entries", "currency", None, "ccy"), ("U", "ds-ledger-entries", "entry_key", "critical"), ("C", "ds-ledger-entries", "amount", None),
    ("U", "ds-cost-centres", "cost_centre_code", None), ("C", "ds-cost-centres", "owner_ref", None),
    ("V", "ds-employees", "work_email", None, "email"),
    ("R", "ds-tickets", "customer_key", None, ("ds-customers", "customer_key")), ("C", "ds-tickets", "priority", None), ("T", "ds-tickets", None, None),
    ("R", "ds-shipments", "order_key", None, ("ds-orders", "order_key")), ("V", "ds-shipments", "tracking_ref", None, "tracking"), ("T", "ds-shipments", None, None),
    ("C", "ds-inventory", "warehouse_code", None), ("T", "ds-inventory", None, None),
    ("V", "ds-warehouses", "postal_code", None, "zip"),
    ("U", "ds-web-sessions", "session_key", None),
    ("C", "ds-web-users", "email", None), ("U", "ds-web-users", "user_key", None), ("T", "ds-web-users", None, None),
    ("C", "ds-consent-records", "consent_flag", None), ("T", "ds-consent-records", None, None),
    ("C", "ds-returns", "reason_code", None), ("C", "ds-csat-surveys", "score", None),
    ("V", "ds-ticket-events", "ticket_key", None, "ticket"), ("V", "ds-delivery-events", "event_ref", None, "evref"),
    ("V", "ds-carriers", "carrier_code", None, "carrier"), ("U", "ds-kb-articles", "article_key", None)]
CODE = {"C": "completeness", "V": "validity", "U": "uniqueness", "R": "relationship", "T": "timeliness"}
SHORT = {"C": "complete", "V": "valid", "U": "unique", "R": "fk", "T": "fresh"}
KEYPREFIX = {"ds-customers": "CK", "ds-contacts": "CT", "ds-accounts": "AC", "ds-leads": "LD", "ds-opportunities": "OP", "ds-orders": "OR",
             "ds-order-lines": "OL", "ds-products": "PRD", "ds-invoices": "INV", "ds-payments": "PAY", "ds-subscriptions": "SUB", "ds-refunds": "RF",
             "ds-suppliers": "SUP", "ds-purchase-orders": "PO", "ds-ledger-entries": "LE", "ds-cost-centres": "CC", "ds-employees": "EMP",
             "ds-ticket-events": "TEV", "ds-kb-articles": "KB", "ds-csat-surveys": "SV", "ds-shipments": "SH", "ds-warehouses": "WH",
             "ds-inventory": "IV", "ds-returns": "RT", "ds-web-sessions": "WS", "ds-web-users": "WU", "ds-consent-records": "CN"}
ROWPREFIX = {d[0]: d[0][3:9].replace("-", "") for d in DS}
DISABLE_REASONS = ["Superseded by the upstream contract check", "Source feed decommissioned; the check no longer applies",
                   "Replaced by a rule on the curated layer", "Owner team retired the dataset's legacy export", "Threshold review: check moved to the vendor"]
FIRST = ["alba", "bruno", "carys", "dario", "elena", "farid", "greta", "hugo", "irena", "jonas", "katya", "lucas", "mira", "nils", "orla", "pavel",
         "quinn", "rosa", "sven", "talia", "umar", "vera", "wen", "xavi", "yara", "zane", "amara", "boris", "chiara", "dmitri", "esme", "felix",
         "gaia", "hana", "ivan", "jade", "kofi", "lena", "marco", "nadia", "otto", "petra", "rafael", "sana", "tomas", "ulla", "viktor", "wanda"]
LAST = ["abbott", "bergstrom", "calloway", "dunmore", "eastwick", "farrow", "galloway", "hartigan", "ironside", "jessop", "kerrigan", "lombardi",
        "montrose", "newcastle", "oakhurst", "pemberton", "quarles", "ravenscroft", "sandoval", "thackeray", "underhill", "valmont", "whitlock",
        "yardley", "zielinski", "ashgrove", "barlow", "cranmer", "devereux", "ellwood", "fenwick", "garnier", "hollis", "ibarra", "jovanovic",
        "kowalski", "lindgren", "marchetti", "norcross", "okafor", "prasad", "rinaldi", "szabo", "tanaka", "ulrich", "vasquez", "wexford", "xenakis",
        "yamada", "zorrilla", "alder", "brandt", "crowe", "delgado", "ekström", "foss", "grimaldi", "halloran", "iverson", "joyner"]
LAST = [x.replace("ö", "o") for x in LAST]
STREETS = ["Cedar Test Lane", "Example Row", "Placeholder Court", "Sample Mews", "Fictional Avenue", "Synthetic Close"]


# ---------------------------------------------------------------------------------------------------------------------
# small exact helpers
# ---------------------------------------------------------------------------------------------------------------------
def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def day_at(i: int, h: int = 0, m: int = 0, s: int = 0) -> datetime:
    return T0 + timedelta(days=i, hours=h, minutes=m, seconds=s)


def chance(r: random.Random, ppm: int) -> bool:
    return r.randrange(1_000_000) < ppm


def pick(r: random.Random, table: tuple | list) -> Any:
    total = sum(w for _, w in table)
    x = r.randrange(total)
    for v, w in table:
        if x < w:
            return v
        x -= w
    raise AssertionError("unreachable")


def rhu(x: Fraction, places: int) -> str:
    neg = x < 0
    n = abs(x) * 10 ** places
    q = (2 * n.numerator + n.denominator) // (2 * n.denominator)
    s = f"{q // 10 ** places}.{q % 10 ** places:0{places}d}" if places else str(q)
    return "-" + s if neg and q else s


def p6(x: Fraction | None) -> str | None:
    return None if x is None else rhu(x, 6)


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def is_missing(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip(TRIM) == "")


def cell_text(v: Any) -> str | None:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> Fraction:
    return Fraction(max(len(a), len(b)) - lev(a, b), max(len(a), len(b)))


def weight_version_at(t: datetime) -> str:
    return "w2" if t >= WEIGHT_CHANGE else "w1"


def evaluated_occurrence(zone: str, hhmm: str, grace: int) -> tuple[datetime, datetime]:
    """The latest daily local occurrence whose grace window has closed by AS_OF, and its deadline (D-06)."""
    off = timedelta(minutes=OFFSET_MIN[zone])
    h, m = int(hhmm[:2]), int(hhmm[3:])
    d0 = (AS_OF + off).date()
    for back in range(-1, 5):
        d = d0 - timedelta(days=back)
        s = datetime(d.year, d.month, d.day, h, m, tzinfo=UTC) - off
        if s + timedelta(minutes=grace) <= AS_OF:
            return s, s + timedelta(minutes=grace)
    raise AssertionError("no occurrence")


# ---------------------------------------------------------------------------------------------------------------------
# the world
# ---------------------------------------------------------------------------------------------------------------------
class Rule:
    def __init__(self, idx: int, code: str, ds: str, field: str | None, severity: str, extra: Any):
        self.idx, self.code, self.ds, self.field, self.severity, self.extra = idx, code, ds, field, severity, extra
        self.rtype = CODE[code]
        self.rule_id = f"r-{ds[3:]}-{SHORT[code]}" + (f"-{field}" if field else "")
        self.version = 1
        self.changes: list[int] = []                 # day indices at which the version number goes up
        self.filter: dict | None = None              # the filter declared by the CURRENT version
        self.disabled_day: int | None = None
        self.disabled_at: datetime | None = None
        self.disabled_reason: str | None = None
        self.start = 0
        self.minute = 0
        self.designated = ""
        self.inj12 = False

    def definition(self, v2: bool = True) -> dict:
        if self.code == "T":
            return {"target": "dataset_schedule"}
        d: dict[str, Any] = {"field": self.field}
        if self.code == "V":
            d.update(pattern=PATTERNS[self.extra], eligibility="all_rows")
        elif self.code == "U":
            d.update(not_null=True, unique=True, keep="first_in_row_order")
        elif self.code == "R":
            d.update(parent_dataset_id=self.extra[0], parent_field=self.extra[1])
        if self.filter and v2:
            d["filter"] = dict(self.filter)
        return d

    def version_at(self, day: int) -> int:
        return 1 + sum(1 for c in self.changes if day >= c)


class World:
    def __init__(self, seed: int):
        self.seed = seed
        master = random.Random(seed)
        self.rs = {p: random.Random(master.getrandbits(64)) for p in PURPOSES}
        self.disclosures: list[str] = []

    # ---- owners, datasets, fields -----------------------------------------------------------------------------------
    def build_register(self) -> None:
        r = self.rs["datasets"]
        self.owners = [{"owner_id": o, "owner_name": n, "team": t, "role": role, "active": d is None, "deactivated_at": d}
                       for o, n, t, role, d in OWNERS]
        self.team = {o["owner_id"]: o["team"] for o in self.owners}
        self.deact = {o["owner_id"]: o["deactivated_at"] for o in self.owners}
        active = [o["owner_id"] for o in self.owners if o["active"]]
        fast = [o for o in active if self.team[o] == FAST_TEAM]
        general = [o for o in active if self.team[o] != FAST_TEAM]
        pool = [d[0] for d in DS if d[8] is None and d[6] and d[0] != "ds-customers"]
        r.shuffle(pool)
        inactive_owner = {}
        for k, dsid in enumerate(pool[:5]):
            inactive_owner[dsid] = ("own-09", "own-09", "own-12", "own-12", "own-15")[k]
        fast_owner = {dsid: fast[k % len(fast)] for k, dsid in enumerate(pool[5:14])}
        self.uncovered_ds = sorted(inactive_owner)
        self.fast_ds = sorted(fast_owner)
        self.ds_list = []
        self.ds_idx = {}
        for d in DS:
            dsid, name, system, klass, key, core, rows, mon, reg = d
            if dsid == "ds-customers":
                owner = "own-07"
            elif dsid in inactive_owner:
                owner = inactive_owner[dsid]
            elif dsid in fast_owner:
                owner = fast_owner[dsid]
            else:
                owner = general[r.randrange(len(general))]
            if reg is None:
                registered = datetime(2026, 3, 2, 9, tzinfo=UTC) + timedelta(days=r.randrange(120))
            else:
                registered = day_at(reg, 9)
            ds = {"dataset_id": dsid, "dataset_name": name, "source_system": system, "owner_id": owner, "classification": klass,
                  "registered_at": ts(registered), "monitored": bool(mon), "refresh_timezone": None, "refresh_local_time": None,
                  "refresh_grace_minutes": None, "last_refreshed_at": None}
            self.ds_idx[dsid] = len(self.ds_list)
            self.ds_list.append(ds)
        self.reg_at = {d["dataset_id"]: datetime.strptime(d["registered_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) for d in self.ds_list}
        # schedules and refreshes
        self.p_late = {}
        self.timeliness_final = {}
        for d in self.ds_list:
            if d["monitored"]:
                while True:
                    zone = ZONES[r.randrange(len(ZONES))]
                    hhmm = f"{1 + r.randrange(20):02d}:{(0, 15, 30, 45)[r.randrange(4)]:02d}"
                    grace = (30, 60, 90, 120)[r.randrange(4)]
                    if d["dataset_id"] == "ds-customers":
                        zone, hhmm, grace = "America/New_York", "06:00", 60
                    s, dl = evaluated_occurrence(zone, hhmm, grace)
                    if dl <= AS_OF - timedelta(minutes=10):
                        break
                d.update(refresh_timezone=zone, refresh_local_time=hhmm, refresh_grace_minutes=grace)
                self.p_late[d["dataset_id"]] = (0 if d["dataset_id"] == "ds-customers" else (50000, 150000, 300000, 450000)[r.randrange(4)])
                late = chance(r, self.p_late[d["dataset_id"]])
                if not late:
                    last = s + timedelta(seconds=r.randrange(grace * 60))
                else:
                    after = dl + timedelta(seconds=60 + r.randrange(14400))
                    last = after if after < AS_OF else s - timedelta(seconds=3600 + r.randrange(82800))
                d["last_refreshed_at"] = ts(last)
                self.timeliness_final[d["dataset_id"]] = not late
            elif r.randrange(100) < 85:
                d["last_refreshed_at"] = ts(AS_OF - timedelta(seconds=3600 + r.randrange(172800)))
        # fields
        self.fields = []
        self.field_id = {}
        self.columns = {}
        extra = FIELD_TOTAL - 10 * len(DS)
        for k, d in enumerate(DS):
            dsid, key, core = d[0], d[4], d[5]
            names = [key] + [c for c in core if c != key]
            for g in GENERIC:
                if len(names) >= 10 + (1 if k < extra else 0):
                    break
                if g not in names:
                    names.append(g)
            self.columns[dsid] = names
            for nm in names:
                fid = f"fld-{len(self.fields) + 1:04d}"
                self.field_id[(dsid, nm)] = fid
                self.fields.append({"field_id": fid, "dataset_id": dsid, "field_name": nm, "data_type": self.dtype(nm), "nullable": nm != key})
        assert len(self.fields) == FIELD_TOTAL, len(self.fields)

    @staticmethod
    def dtype(nm: str) -> str:
        if nm.endswith(("_date", "_on")) or nm in ("effective_from", "effective_to"):
            return "date"
        if nm.endswith("_at"):
            return "timestamp"
        if nm in ("amount", "order_total", "budget_amount", "unit_cost"):
            return "decimal"
        if nm in ("quantity", "score", "on_hand", "target_minutes"):
            return "integer"
        if nm.endswith("_flag"):
            return "boolean"
        return "text"

    # ---- rules ------------------------------------------------------------------------------------------------------------
    def build_rules(self) -> None:
        r = self.rs["rules"]
        self.rules: list[Rule] = []
        for i, spec in enumerate(R):
            code, dsid, fld, sev = spec[:4]
            extra = spec[4] if len(spec) > 4 else None
            sev = sev or pick(r, (("low", 25), ("medium", 40), ("high", 35)))
            self.rules.append(Rule(i, code, dsid, fld, sev, extra))
        assert len(self.rules) == 60
        by = {x.rule_id: x for x in self.rules}
        assert len(by) == 60
        self.rule_by_id = by
        for x in self.rules:
            reg = next(d[8] for d in DS if d[0] == x.ds)
            x.start = (reg + r.randrange(4)) if reg is not None else (0 if r.randrange(100) < 60 else 3 + r.randrange(43))
            x.minute = 23 * 60 + 50 if x.code == "T" else 120 + (x.idx * 13) % 240
        cust = self.rules[2]
        cust.designated = "critical-key"
        pool = [x for x in self.rules if x.code != "T" and x.ds != "ds-customers" and x.severity != "critical"]
        r.shuffle(pool)
        v2 = pool[:14]
        for k, x in enumerate(v2):
            x.filter = {"field": "status", "equals": "active"}
            if k == 0:
                x.inj12 = True
                x.changes = [N_DAYS]                  # the second version starts after the last run (2026-10-05T00:00:00Z)
            else:
                while True:
                    c = 20 + r.randrange(52)
                    if not (36 <= c <= 64) and c >= x.start + 3:   # no rule changes within a fortnight of the 2026-09-01 weight change (day 50)
                        break
                x.changes = [c]
        v3 = v2[1]
        while True:
            c = 20 + r.randrange(60)
            if not (36 <= c <= 64) and c > v3.changes[0] + 2:
                break
        v3.changes.append(c)
        v3.version = 3
        for x in v2:
            x.version = 1 + len(x.changes)
        rest = [x for x in self.rules if x not in v2 and x.ds != "ds-customers" and x.severity != "critical"
                and next(d[8] for d in DS if d[0] == x.ds) is None and x.start < 20]
        r.shuffle(rest)
        for x in rest[:5]:
            x.disabled_day = 38 + r.randrange(43)
            x.disabled_at = day_at(x.disabled_day, 1 + r.randrange(20), r.randrange(60), 0)
            x.disabled_reason = DISABLE_REASONS[r.randrange(len(DISABLE_REASONS))]
        self.v2_rules, self.disabled_rules = v2, rest[:5]
        self.inj12_rule = v2[0]
        self.v3_rule = v3

    # ---- dataset rows -----------------------------------------------------------------------------------------------------
    def build_rows(self) -> None:
        r = self.rs["rows"]
        rowds = [d[0] for d in DS if d[6]]
        parents = {x.ds: set() for x in self.rules}
        for x in self.rules:
            if x.code == "R":
                parents[x.ds].add(x.extra[0])
        order: list[str] = []
        left = list(rowds)
        while left:
            for dsid in list(left):
                if all(p in order or p == dsid for p in parents.get(dsid, ())):
                    order.append(dsid)
                    left.remove(dsid)
        tier = {dsid: pick(r, (("good", 35), ("fair", 45), ("poor", 20))) for dsid in rowds}
        self.tier = tier
        rng = {"miss": {"good": (5000, 25000), "fair": (25000, 70000), "poor": (70000, 160000)},
               "invalid": {"good": (5000, 20000), "fair": (20000, 60000), "poor": (60000, 140000)},
               "dup": {"good": (0, 10000), "fair": (10000, 30000), "poor": (30000, 70000)},
               "unmatched": {"good": (5000, 30000), "fair": (30000, 90000), "poor": (90000, 180000)}}

        def draw(kind: str, dsid: str) -> int:
            lo, hi = rng[kind][tier[dsid]]
            return lo + r.randrange(hi - lo)

        self.rates: dict[tuple[str, str], dict[str, int]] = {}
        for x in self.rules:
            if x.code == "T" or x.ds not in tier:
                continue
            rt = self.rates.setdefault((x.ds, x.field), {"miss": 0, "invalid": 0, "dup": 0, "unmatched": 0, "null": 0})
            crit = x.severity == "critical"
            if x.code == "C":
                rt["miss"] = draw("miss", x.ds)
            elif x.code == "V":
                rt["invalid"] = draw("invalid", x.ds)
            elif x.code == "U":
                rt["dup"] = 0 if crit else draw("dup", x.ds)
            elif x.code == "R":
                rt["unmatched"] = 0 if crit else draw("unmatched", x.ds)
                rt["null"] = 60000 + r.randrange(40000) if x.ds == "ds-orders" else r.randrange(20000)
        self.rows: dict[str, list[dict]] = {}
        self.keys: dict[str, list[str]] = {}
        nrows = {dsid: 45 + r.randrange(86) for dsid in rowds}
        nrows["ds-customers"] = 120
        for dsid in order:
            self.rows[dsid] = self.make_rows(dsid, nrows[dsid], r)
        # the designed dataset: ds-customers is near perfect with one open critical key failure (exact counts, not rates)
        rows = self.rows["ds-customers"]
        for row in rows:
            row["email"] = f"{row['row_id'][-4:]}.{LAST[int(row['row_id'][-4:]) % len(LAST)]}@example.com"
            row["status"] = "active"
        rows[36]["email"] = None
        rows[82]["email"] = "no-at-sign.example.com"
        for k in range(120):
            rows[k]["customer_key"] = f"CK-{k + 1:04d}"
        rows[60]["customer_key"] = rows[11]["customer_key"]
        rows[96]["customer_key"] = rows[44]["customer_key"]
        self.keys["ds-customers"] = [x["customer_key"] for x in rows]
        # parents of the customers' children must be rebuilt now that the keys are fixed: rows were built after customers in `order`
        # (customers has no parents, so it is first) with the keys of the first pass; re-point them
        self.repoint_children("ds-customers", r)

    def repoint_children(self, parent: str, r: random.Random) -> None:
        for x in self.rules:
            if x.code == "R" and x.extra[0] == parent:
                valid = set(self.keys[parent])
                prefix = KEYPREFIX[parent]
                for row in self.rows[x.ds]:
                    v = row.get(x.field)
                    if v is not None and not is_missing(v) and isinstance(v, str) and v.startswith(prefix + "-") and not v.startswith(prefix + "-9"):
                        if v not in valid:
                            row[x.field] = self.keys[parent][r.randrange(len(self.keys[parent]))]

    def key_value(self, dsid: str, i: int) -> str:
        if dsid == "ds-tickets":
            return f"TK-{100000 + i:06d}"
        if dsid == "ds-delivery-events":
            return f"EV-{i:08d}"
        if dsid == "ds-carriers":
            return "".join(chr(65 + (i // 26 ** p) % 26) for p in (2, 1, 0))
        return f"{KEYPREFIX.get(dsid, 'K')}-{i:04d}"

    def missing_value(self, r: random.Random) -> Any:
        return pick(r, ((None, 55), ("", 20), ("   ", 15), ("\t", 10)))

    def make_rows(self, dsid: str, n: int, r: random.Random) -> list[dict]:
        spec = next(d for d in DS if d[0] == dsid)
        key = spec[4]
        rules = [x for x in self.rules if x.ds == dsid and x.code != "T"]
        cols = [key] + [x.field for x in rules if x.field != key]
        cols += ["status"] + [c for c in spec[5] if c not in cols][: max(0, 7 - len(set(cols + ["status"])))]
        cols = list(dict.fromkeys(cols))
        fk = {x.field: x for x in rules if x.code == "R"}
        vkind = {x.field: x.extra for x in rules if x.code == "V"}
        out = []
        keys: list[str] = []
        for i in range(1, n + 1):
            row: dict[str, Any] = {"row_id": f"{ROWPREFIX[dsid]}-{i:04d}"}
            for c in cols:
                rt = self.rates.get((dsid, c), {"miss": 0, "invalid": 0, "dup": 0, "unmatched": 0, "null": 0})
                if c == key:
                    k = self.key_value(dsid, i)
                    if keys and rt["dup"] and chance(r, rt["dup"]):
                        k = keys[r.randrange(len(keys))]
                    keys.append(k)
                    v: Any = k
                    if c in vkind and chance(r, rt["invalid"]):
                        v = INVALID[vkind[c]][r.randrange(len(INVALID[vkind[c]]))]
                elif c in fk:
                    parent, pfield = fk[c].extra
                    if chance(r, rt["null"]):
                        v = None if r.randrange(100) < 80 else ""
                    elif chance(r, rt["unmatched"]):
                        v = f"{KEYPREFIX.get(parent, 'K')}-9{r.randrange(1000):03d}"
                        if parent == "ds-tickets":
                            v = f"TK-9{r.randrange(100000):05d}"
                    else:
                        pk = self.keys[parent]
                        v = pk[r.randrange(len(pk))]
                elif c == "status":
                    v = pick(r, (("active", 85), ("inactive", 10), ("pending", 5)))
                else:
                    v = self.value(dsid, c, i, r, vkind.get(c))
                    if chance(r, rt["miss"]):
                        v = self.missing_value(r)
                    elif c in vkind and chance(r, rt["invalid"]):
                        v = INVALID[vkind[c]][r.randrange(len(INVALID[vkind[c]]))]
                row[c] = v
            out.append(row)
        self.keys[dsid] = keys
        return out

    def value(self, dsid: str, c: str, i: int, r: random.Random, kind: str | None) -> Any:
        if kind == "email" or c in ("email", "contact_email", "work_email"):
            return f"{FIRST[r.randrange(len(FIRST))]}.{LAST[r.randrange(len(LAST))]}{i}@example.{('com', 'org', 'net')[r.randrange(3)]}"
        if kind == "ccy" or c == "currency":
            return ("USD", "EUR", "GBP", "CAD")[r.randrange(4)]
        if kind == "tracking":
            return f"{chr(65 + r.randrange(26))}{chr(65 + r.randrange(26))}{r.randrange(10 ** 9):09d}"
        if kind == "zip" or c == "postal_code":
            return f"{r.randrange(10000, 99999)}"
        if kind == "ticket":
            return f"TK-{100001 + r.randrange(300):06d}"
        if kind == "evref":
            return f"EV-{i:08d}"
        if kind == "carrier":
            return "".join(chr(65 + r.randrange(26)) for _ in range(3))
        if c.endswith(("_date", "_on")) or c in ("effective_from", "effective_to"):
            return f"2026-{1 + r.randrange(9):02d}-{1 + r.randrange(28):02d}"
        if c.endswith("_at"):
            return f"2026-{1 + r.randrange(9):02d}-{1 + r.randrange(28):02d}T{r.randrange(24):02d}:{r.randrange(60):02d}:00Z"
        if c in ("amount", "order_total", "budget_amount", "unit_cost"):
            return 100 + r.randrange(99900)
        if c in ("quantity", "on_hand"):
            return 1 + r.randrange(200)
        if c == "score":
            return 1 + r.randrange(5)
        if c.endswith("_flag"):
            return r.randrange(2) == 1
        if c == "full_name":
            return f"{FIRST[r.randrange(len(FIRST))].title()} {LAST[r.randrange(len(LAST))].title()}"
        if c == "phone":
            return f"+1555{r.randrange(10 ** 7):07d}"
        return ("A", "B", "C", "D")[r.randrange(4)]

    # ---- the row-level measure (restated from D-01/D-06) ----------------------------------------------------------------
    def measure(self, x: Rule, filt: bool = True) -> dict[str, Any] | None:
        if x.code == "T":
            if x.ds not in self.timeliness_final:
                return None
            ok = self.timeliness_final[x.ds]
            return {"E": 1, "F": 0 if ok else 1, "score": Fraction(1 if ok else 0)}
        rows = self.rows[x.ds]
        f = x.filter if filt else None
        if f:
            rows = [w for w in rows if cell_text(w.get(f["field"])) == f["equals"]]
        el = len(rows)
        vals = [w.get(x.field) for w in rows]
        if x.code == "C":
            miss = sum(1 for v in vals if is_missing(v))
            return {"E": el, "F": miss, "score": Fraction(el - miss, el) if el else None}
        if x.code == "V":
            pat = re.compile(PATTERNS[x.extra])
            pop = [v for v in vals if not is_missing(v)]
            ok = sum(1 for v in pop if isinstance(v, str) and pat.search(v))
            return {"E": el, "F": el - ok, "score": Fraction(ok, len(pop)) if pop else None, "populated": len(pop)}
        if x.code == "U":
            seen: set[str] = set()
            nulls = dup = 0
            for v in vals:
                if is_missing(v):
                    nulls += 1
                    continue
                k = cell_text(v)
                if k in seen:
                    dup += 1
                seen.add(k)
            return {"E": el, "F": nulls + dup, "score": 1 - Fraction(dup, el) if el else None, "dup": dup, "nulls": nulls}
        parent = {cell_text(w.get(x.extra[1])) for w in self.rows.get(x.extra[0], []) if not is_missing(w.get(x.extra[1]))}
        present = [v for v in vals if not is_missing(v)]
        matched = sum(1 for v in present if cell_text(v) in parent)
        return {"E": len(present), "F": len(present) - matched, "score": Fraction(matched, len(present)) if present else None,
                "nulls": el - len(present), "total": el}

    def measure_all(self) -> None:
        self.cur = {}
        self.old = {}
        for x in self.rules:
            if x.inj12:
                self.cur[x.rule_id] = self.measure(x, True)           # version 2 (filtered): what the domain measures now
                self.old[x.rule_id] = self.measure(x, False)          # version 1: what the last stored run was
            else:
                self.cur[x.rule_id] = self.measure(x, True)
                self.old[x.rule_id] = self.measure(x, False) if x.filter else self.cur[x.rule_id]

    def active_rules(self) -> list[Rule]:
        return [x for x in self.rules if x.disabled_day is None]

    def dataset_scores(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        wts = {w["weight_version"]: {k: Fraction(v) for k, v in w["weights"].items()} for w in WEIGHTS}
        for d in self.ds_list:
            acc: dict[str, list[Fraction]] = {}
            cf = 0
            for x in self.active_rules():
                if x.ds != d["dataset_id"]:
                    continue
                m = self.cur[x.rule_id]
                if m is None:
                    continue
                if x.severity == "critical":
                    cf += m["F"]
                if m["score"] is not None:
                    acc.setdefault(x.rtype, []).append(m["score"])
            dims = {k: sum(v, Fraction(0)) / len(v) for k, v in acc.items()}
            sc = {}
            for wv, w in wts.items():
                meas = [k for k in DIMS if k in dims]
                den = sum((w[k] for k in meas), Fraction(0))
                sc[wv] = sum((w[k] * dims[k] for k in meas), Fraction(0)) / den if meas and den else None
            out[d["dataset_id"]] = {"dims": dims, "scores": sc, "critical_failures": cf}
        return out

    # ---- rule runs --------------------------------------------------------------------------------------------------------
    def build_runs(self) -> None:
        r = self.rs["runs"]
        self.runs: list[dict] = []
        self.drift = {}
        for x in self.rules:
            end = N_DAYS - 1 if x.disabled_day is None else x.disabled_day - 1
            drift = r.randrange(-30, 31)
            for t in range(x.start, end + 1):
                ver = x.version_at(t)
                m = self.old[x.rule_id] if (x.inj12 or not x.filter or ver < 2) else self.cur[x.rule_id]
                if m is None:
                    continue
                at = day_at(t, 0, x.minute)
                if x.code == "T":
                    final = t == N_DAYS - 1 and x.disabled_day is None
                    late = (m["F"] == 1) if final else chance(r, self.p_late.get(x.ds, 100000))
                    E, F = 1, (1 if late else 0)
                else:
                    E_T, F_T = m["E"], m["F"]
                    if E_T == 0:
                        continue
                    if t == N_DAYS - 1 and x.disabled_day is None:
                        E, F = E_T, F_T
                    else:
                        E = max(1, (E_T * (80 + 20 * t // 83) + 50) // 100)
                        if x.designated == "critical-key":
                            F = 2 if t >= 71 else (1 if t == 15 else (2 if t == 31 else 0))
                        elif x.severity == "critical":
                            F = 0 if t >= 69 else (min(E, 1 + r.randrange(2)) if chance(r, 40000) else 0)
                        elif F_T == 0:
                            F = min(E, 1 + r.randrange(3)) if (t < 60 and chance(r, 30000)) else 0
                        else:
                            factor = 100 - drift * (83 - t) // 83
                            mult = 2 + r.randrange(3) if chance(r, 30000) else 1
                            n = 70 + r.randrange(61)
                            num, den = E * F_T * factor * n * mult, E_T * 10000
                            F = min(E, (2 * num + den) // (2 * den))
                self.runs.append({"rule": x, "day": t, "at": at, "kind": "scheduled", "ver": ver, "E": E, "F": F, "issue": None})
        self.scheduled = len(self.runs)

    # ---- issues -----------------------------------------------------------------------------------------------------------
    def dist(self, r: random.Random, scale: int) -> int:
        geo = 0
        while geo < 6 and chance(r, 550000):
            geo += 1
        return (scale // 2 + r.randrange(scale)) * (1 + geo)

    def can_verify(self, base: dict, at: datetime) -> bool:
        x = base["rule"]
        if x.disabled_at is not None and at >= x.disabled_at:
            return False
        return x.version_at((at - T0).days) == base["ver"] if at < AS_OF else False

    def build_issues(self) -> None:
        r = self.rs["issues"]
        ds_owner = {d["dataset_id"]: d["owner_id"] for d in self.ds_list}
        sev_w = {"critical": 30, "high": 14, "medium": 10, "low": 6}
        cand = [u for u in self.runs if u["kind"] == "scheduled" and u["F"] > 0]
        cand.sort(key=lambda u: (u["day"], u["rule"].idx))
        pool = [u for u in cand if not (u["rule"].designated and u["day"] >= 71)]
        W = sum(sev_w[u["rule"].severity] for u in pool)
        forced = [u for u in cand if u["rule"].designated and u["day"] in (31, 71)]
        chosen = []
        for u in pool:
            p = min(1_000_000, 600 * 1_000_000 * sev_w[u["rule"].severity] // W)
            if (u in forced) or chance(r, p):
                chosen.append(u)
        for u in forced:
            if u not in chosen:
                chosen.append(u)
        chosen.sort(key=lambda u: (u["day"], u["rule"].idx))
        self.issues: list[dict] = []
        for base in chosen:
            x = base["rule"]
            det = base["at"]
            owner = ds_owner[x.ds]
            team = self.team[owner]
            fast = team == FAST_TEAM
            crit_other = x.severity == "critical" and not x.designated
            u = r.randrange(100)
            if x.designated and base["day"] == 71:
                cls = "open"
            elif x.designated:
                cls = "resolved"
            elif crit_other:
                cls = "resolved"
            elif det < EARLY_CUT:
                cls = "resolved" if u < 72 else "claimed"
            else:
                cls = "resolved" if u < 55 else ("claimed" if u < 67 else "open")
                d_ = self.deact.get(owner)
                if d_ and det >= datetime.strptime(d_, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) and r.randrange(100) < 90:
                    cls = "open"
            iss = {"base": base, "owner": owner, "det": det, "status": "open", "due": None, "closed": None, "ver": None, "reopened": [],
                   "cls": None, "fast": fast, "failed_rerun": None, "second": None}
            limit = AS_OF - timedelta(hours=1)
            s1 = 300 if crit_other else (900 if fast else 2400)
            gap = (30 + r.randrange(270)) if fast else (60 + r.randrange(840))
            if cls == "resolved":
                closed = det + timedelta(minutes=self.dist(r, s1))
                rerun = closed + timedelta(minutes=gap)
                if rerun > limit:
                    cls = "open"
                elif not self.can_verify(base, rerun):
                    cls = "claimed"
                else:
                    iss["closed"], iss["status"] = closed, "closed"
                    run = {"rule": x, "day": (rerun - T0).days, "at": rerun, "kind": "rerun", "ver": base["ver"], "E": base["F"], "F": 0, "issue": iss}
                    self.runs.append(run)
                    iss["ver"], iss["cls"] = run, "resolved"
                    if (not x.designated and not crit_other and det >= EARLY_CUT and chance(r, 70000)):
                        reopen = rerun + timedelta(minutes=1440 + r.randrange(13 * 1440))
                        if reopen <= AS_OF - timedelta(hours=6):
                            iss["reopened"], iss["status"], iss["cls"] = [reopen], "open", "open"
                            if r.randrange(100) < 40:
                                c2 = reopen + timedelta(minutes=self.dist(r, s1))
                                rr2 = c2 + timedelta(minutes=gap)
                                if rr2 <= limit and self.can_verify(base, rr2):
                                    run2 = {"rule": x, "day": (rr2 - T0).days, "at": rr2, "kind": "rerun", "ver": base["ver"], "E": base["F"], "F": 0, "issue": iss}
                                    self.runs.append(run2)
                                    iss.update(closed=c2, status="closed", ver=run2, cls="resolved")
            if cls == "claimed":
                closed = det + timedelta(minutes=self.dist(r, 1500))
                if closed > limit:
                    cls = "open"
                else:
                    iss.update(closed=closed, status="closed", cls="claimed")
                    if r.randrange(100) < 35:
                        at = closed + timedelta(minutes=60 + r.randrange(2880))
                        if at <= limit and self.can_verify(base, at):
                            run = {"rule": x, "day": (at - T0).days, "at": at, "kind": "rerun", "ver": base["ver"], "E": base["F"],
                                   "F": 1 + r.randrange(base["F"]), "issue": iss}
                            self.runs.append(run)
                            iss["failed_rerun"] = run
            if cls == "open":
                iss["cls"] = "open"
                if x.designated and base["day"] == 71:
                    iss.update(status="investigating", due=datetime(2026, 9, 29, tzinfo=UTC))
                elif r.randrange(100) < 55:
                    iss.update(status="investigating", due=datetime.combine((det + timedelta(days=3 + r.randrange(12))).date(), datetime.min.time(), UTC))
                elif r.randrange(100) < 20:
                    iss["due"] = datetime.combine((det + timedelta(days=5 + r.randrange(10))).date(), datetime.min.time(), UTC)
            if iss["cls"] is None:
                iss["cls"] = cls
            if iss["status"] == "open" and iss["reopened"]:
                iss["cls"] = "open"
            base["issue"] = iss
            self.issues.append(iss)
        # ids
        self.runs.sort(key=lambda u: (u["at"], u["rule"].idx, u["kind"]))
        for k, u in enumerate(self.runs, 1):
            u["id"] = f"rr-{k:05d}"
        self.issues.sort(key=lambda i: (i["det"], i["base"]["rule"].idx))
        for k, i in enumerate(self.issues, 1):
            i["id"] = f"iss-{k:04d}"
        for u in self.runs:
            if u["kind"] == "rerun":
                u["rerun_for"] = u["issue"]["id"]

    # ---- lineage ----------------------------------------------------------------------------------------------------------
    def build_lineage(self) -> None:
        r = self.rs["lineage"]
        ids = [d["dataset_id"] for d in self.ds_list]
        idx = {d: i for i, d in enumerate(ids)}
        declared: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for x in self.rules:
            if x.code == "R" and (x.extra[0], x.ds) not in seen:
                seen.add((x.extra[0], x.ds))
                declared.append((x.extra[0], x.ds))
        while len(declared) < 80:
            a, b = ids[r.randrange(40)], ids[r.randrange(40)]
            if idx[a] < idx[b] and (a, b) not in seen:
                seen.add((a, b))
                declared.append((a, b))
        order = list(range(80))
        r.shuffle(order)
        obs_decl = [declared[i] for i in order[:58]]
        not_obs = [declared[i] for i in order[58:]]
        undeclared: list[tuple[str, str]] = []
        used = set(seen)
        while len(undeclared) < 12:
            a, b = ids[r.randrange(40)], ids[r.randrange(40)]
            if a != b and (a, b) not in used:
                used.add((a, b))
                undeclared.append((a, b))
        inferred = [not_obs[k] for k in range(4)]
        while len(inferred) < 10:
            a, b = ids[r.randrange(40)], ids[r.randrange(40)]
            if a != b and (a, b) not in used:
                used.add((a, b))
                inferred.append((a, b))
        self.declared, self.obs_decl, self.undeclared, self.inferred, self.not_obs = declared, obs_decl, undeclared, inferred, not_obs
        edges = []
        for k, (a, b) in enumerate(declared, 1):
            edges.append({"edge_id": f"ed-{k:03d}", "source_dataset_id": a, "target_dataset_id": b, "evidence_type": "declared", "observed_at": None})
        obs = obs_decl + undeclared
        obs_order = list(range(len(obs)))
        r.shuffle(obs_order)
        for k, j in enumerate(obs_order, 1):
            a, b = obs[j]
            first = max(0, (max(self.reg_at[a], self.reg_at[b]) - T0).days + 1)
            at = day_at(first + r.randrange(N_DAYS - 1 - first), r.randrange(24), r.randrange(60), 0)
            edges.append({"edge_id": f"eo-{k:03d}", "source_dataset_id": a, "target_dataset_id": b, "evidence_type": "observed", "observed_at": ts(at)})
        for k, (a, b) in enumerate(inferred, 1):
            edges.append({"edge_id": f"ei-{k:03d}", "source_dataset_id": a, "target_dataset_id": b, "evidence_type": "inferred", "observed_at": None})
        self.edges = edges

    # ---- metric definitions -----------------------------------------------------------------------------------------------
    def build_metrics(self) -> None:
        r = self.rs["metrics"]
        names = ["Net revenue", "Gross margin", "Customer churn rate", "Average order value", "Customer lifetime value", "Net promoter score",
                 "Active customers", "New customers", "Repeat purchase rate", "Refund rate", "Days sales outstanding", "Invoice accuracy rate",
                 "On-time delivery rate", "Order fill rate", "Inventory turnover", "Stock-out rate", "Ticket first-response time",
                 "Ticket resolution time", "CSAT score", "Support backlog", "Subscription MRR", "Subscription churn", "Trial conversion rate",
                 "Lead conversion rate", "Pipeline coverage", "Opportunity win rate", "Supplier lead time", "Purchase price variance",
                 "Consent coverage", "Session conversion rate"]
        owner_ids = [o["owner_id"] for o in self.owners]
        reviewers = [o["owner_id"] for o in self.owners if o["active"] and o["role"] in ("steward", "admin")]
        self.reviewers = reviewers
        rowds = [d for d in DS if d[6]]
        order = list(range(30))
        r.shuffle(order)
        two = set(order[:15])
        broken = order[15:22] if False else order[10:17]            # effective versions with a gap in the checklist (7)
        gaps = ("grain", "refresh", "source_fields", "owner_id", "definition", "grain", "refresh")
        self.metric_versions, self.definition_changes = [], []
        self.incomplete_metrics = {}
        gap_of = {m: gaps[k] for k, m in enumerate(broken)}
        reasons = ["Refunds are netted from the figure", "Window aligned to the fiscal calendar", "Excludes internal test accounts",
                   "Grain changed from order to customer-month", "Source moved to the curated layer"]
        for m, name in enumerate(names):
            slug = "m-" + name.lower().replace(" ", "-")
            srcs = []
            for _ in range(1 + r.randrange(3)):
                d = rowds[r.randrange(len(rowds))]
                srcs.append(f"{d[0][3:]}.{self.columns[d[0]][r.randrange(min(5, len(self.columns[d[0]])))]}")
            srcs = list(dict.fromkeys(srcs))
            owner = owner_ids[r.randrange(18)]
            grain = ("order", "customer", "customer-month", "ticket", "shipment", "day")[r.randrange(6)]
            refresh = ("daily", "weekly", "monthly")[r.randrange(3)]
            v1_from = datetime(2026, 2, 1, 9, tzinfo=UTC) + timedelta(days=r.randrange(140))
            base = {"metric_id": slug, "metric_name": name, "definition": f"{name} as defined in the governance glossary, computed from {', '.join(srcs)}",
                    "grain": grain, "source_fields": srcs, "owner_id": owner, "refresh": refresh}
            versions = [dict(base, version_number=1, valid_from=v1_from, status="superseded" if m in two else "published")]
            if m in two:
                v2 = dict(base, version_number=2, valid_from=day_at(r.randrange(80), 9), status="published")
                v2["definition"] = base["definition"] + f"; revised: {reasons[r.randrange(len(reasons))].lower()}"
                versions.append(v2)
            eff = versions[-1]
            if m in gap_of:
                g = gap_of[m]
                eff[g] = {"grain": "", "refresh": None, "source_fields": [], "owner_id": None, "definition": "   "}[g]
                self.incomplete_metrics[slug] = g
            for v in versions:
                v["metric_version_id"] = f"mv-{slug[2:]}-{v['version_number']}"
                self.metric_versions.append({"metric_version_id": v["metric_version_id"], "metric_id": slug, "metric_name": name,
                                             "version_number": v["version_number"], "definition": v["definition"], "grain": v["grain"],
                                             "source_fields": v["source_fields"], "owner_id": v["owner_id"], "refresh": v["refresh"],
                                             "valid_from": ts(v["valid_from"]), "status": v["status"]})
            if m in two:
                self.definition_changes.append({"change_id": f"dc-{slug[2:]}-2", "metric_version_id": versions[1]["metric_version_id"],
                                                "previous_metric_version_id": versions[0]["metric_version_id"],
                                                "reason": reasons[r.randrange(len(reasons))], "approved_by": reviewers[r.randrange(len(reviewers))],
                                                "changed_at": ts(versions[1]["valid_from"])})
        self.metric_versions.sort(key=lambda v: (v["metric_id"], v["version_number"]))
        self.definition_changes.sort(key=lambda c: c["change_id"])

    # ---- customers and matching ---------------------------------------------------------------------------------------
    def build_customers(self) -> None:
        r = self.rs["customers"]
        self.persons = 0
        addr_n = [0]

        def new_addr() -> str:
            addr_n[0] += 1
            return f"addr-{addr_n[0]:05d}"

        def person() -> int:
            self.persons += 1
            return self.persons

        def full_name() -> str:
            return f"{FIRST[r.randrange(len(FIRST))]} {LAST[r.randrange(len(LAST))]}"

        def variant(nm: str) -> str:
            f, l = nm.split(" ")
            k = r.randrange(100)
            if k < 70:
                return nm
            if k < 85:
                return f"{f[0]} {l}"
            i = r.randrange(len(l))
            return f"{f} {l[:i] + l[i + 1:]}"

        sysw = (("crm", 40), ("billing", 35), ("support", 25))
        systems = ("crm", "billing", "support")
        recs: list[dict] = []
        plans: list[dict] = []

        def rec(p: int, system: str, name: str, addr: str) -> dict:
            d = {"person": p, "system": system, "name": name, "addr": addr}
            recs.append(d)
            return d

        def two_systems() -> tuple[str, str]:
            a = pick(r, sysw)
            b = a
            while b == a:
                b = pick(r, sysw)
            return a, b

        for _ in range(330):
            p, nm, ad = person(), full_name(), new_addr()
            s1, s2 = two_systems()
            a = rec(p, s1, nm, ad)
            b = rec(p, s2, variant(nm), ad if r.randrange(100) < 80 else new_addr())
            plans.append({"a": a, "b": b, "kind": "true"})
        for _ in range(12):
            p, nm, ad = person(), full_name(), new_addr()
            ss = list(systems)
            r.shuffle(ss)
            a = rec(p, ss[0], nm, ad)
            b = rec(p, ss[1], variant(nm), ad)
            rec(p, ss[2], variant(nm), ad if r.randrange(100) < 80 else new_addr())
            plans.append({"a": a, "b": b, "kind": "true"})
        for k in range(31):                                # households: two people, one name, one address
            nm, ad = full_name(), new_addr()
            s1, s2 = two_systems()
            a = rec(person(), s1, nm, ad)
            b = rec(person(), s2, nm, ad)
            if k < 25:
                plans.append({"a": a, "b": b, "kind": "household"})
            else:
                self.unlinked_households = getattr(self, "unlinked_households", []) + [(a, b)]
        for _ in range(33):                                # near names, different people
            nm = full_name()
            f, l = nm.split(" ")
            i = r.randrange(len(l))
            s1, s2 = two_systems()
            a = rec(person(), s1, nm, new_addr())
            b = rec(person(), s2, f"{f} {l[:i] + l[i + 1:]}" if len(l) > 3 else f"{f} {l}x", new_addr())
            plans.append({"a": a, "b": b, "kind": "near"})
        while len(recs) < 2000:
            rec(person(), pick(r, sysw), full_name(), new_addr())
        assert len(recs) == 2000, len(recs)
        order = list(range(len(recs)))
        r.shuffle(order)
        perm = list(range(1, self.persons + 1))
        r.shuffle(perm)
        counters = {s: 0 for s in systems}
        pref = {"crm": ("C-", 10000), "billing": ("B-", 20000), "support": ("S-", 30000)}
        self.customer_records = []
        self.truth = {}
        for k, i in enumerate(order, 1):
            d = recs[i]
            d["id"] = f"rec-{k:04d}"
            counters[d["system"]] += 1
            p, base = pref[d["system"]]
            self.customer_records.append({"record_id": d["id"], "source_system": d["system"], "source_customer_id": f"{p}{base + counters[d['system']]}",
                                          "normalized_name": d["name"], "address_key": d["addr"]})
            self.truth[d["id"]] = f"E-{perm[d['person'] - 1]:04d}"
        self.customer_records.sort(key=lambda c: c["record_id"])
        self.plans = plans
        self.recs_by_id = {d["id"]: d for d in recs}

    def build_matching(self) -> None:
        r = self.rs["matching"]
        proposers = [o["owner_id"] for o in self.owners if o["active"]]
        cands = []
        for pl in self.plans:
            a, b = pl["a"], pl["b"]
            left, right = (a, b) if a["id"] < b["id"] else (b, a)
            sim = similarity(left["name"], right["name"])
            same_addr = left["addr"] == right["addr"]
            shared = left["name"] == right["name"] and same_addr
            if pl["kind"] == "household":
                score = Fraction(88 + r.randrange(10), 100)
            else:
                score = (60 * sim + 40 * (1 if same_addr else 0)) / 100
            if shared:
                expl = "Same name and address in two systems"
            elif same_addr:
                expl = f"Near-identical name (similarity {rhu(sim, 2)}), same address"
            elif sim == 1:
                expl = "Same name, different address (moved or a second address)"
            else:
                expl = f"Similar name (similarity {rhu(sim, 2)}), different address; weak evidence"
            day = r.randrange(70)
            cands.append({"left_record_id": left["id"], "right_record_id": right["id"], "score": p6(score),
                          "features": {"name_similarity": p6(sim), "address_match": "1.000000" if same_addr else "0.000000"},
                          "explanation": expl, "uncertainty": "Shared name and address; possible household" if shared else None,
                          "proposed_by": proposers[r.randrange(len(proposers))],
                          "proposed_at": day_at(day, 8 + r.randrange(10), r.randrange(60), r.randrange(60)), "kind": pl["kind"],
                          "same": self.truth[left["id"]] == self.truth[right["id"]], "day": day})
        cands.sort(key=lambda c: (c["proposed_at"], c["left_record_id"]))
        for k, c in enumerate(cands, 1):
            c["candidate_id"] = f"cand-{k:04d}"
        keyed = sorted(range(len(cands)), key=lambda i: (r.randrange(1_000_000) + cands[i]["day"] * 6000, i))
        reviewed = sorted(keyed[:220])
        decisions = []
        p_app = {"true": 94, "household": 25, "near": 12}
        for i in reviewed:
            c = cands[i]
            pool = [x for x in self.reviewers if x != c["proposed_by"]]
            rev = pool[r.randrange(len(pool))]
            at = c["proposed_at"] + timedelta(hours=1, minutes=r.randrange(72 * 60))
            dec = "approve" if r.randrange(100) < p_app[c["kind"]] else "reject"
            reason = None
            if dec == "reject" and r.randrange(100) < 50:
                reason = ("Names similar, addresses differ", "Different people", "Insufficient evidence")[r.randrange(3)]
            decisions.append({"cand": c, "reviewer_id": rev, "decision": dec, "decided_at": at, "reverses": None, "reason": reason})
        approvals = [d for d in decisions if d["decision"] == "approve"]
        weights = [8 if not d["cand"]["same"] else 1 for d in approvals]
        rev_reasons = ["Different people in one household", "Address match was a coincidence", "Customer asked to keep the accounts separate"]
        picked = []
        for _ in range(15):
            tot = sum(weights)
            x = r.randrange(tot)
            for j, w in enumerate(weights):
                if x < w:
                    break
                x -= w
            picked.append(approvals[j])
            weights[j] = 0
        for a in picked:
            c = a["cand"]
            pool = [x for x in self.reviewers if x != c["proposed_by"]]
            room = int((AS_OF - timedelta(hours=1) - a["decided_at"]).total_seconds() // 60) - 1440
            at = a["decided_at"] + timedelta(minutes=1440 + r.randrange(min(20 * 1440, room)))
            decisions.append({"cand": c, "reviewer_id": pool[r.randrange(len(pool))], "decision": "reverse", "decided_at": at, "reverses": a,
                              "reason": rev_reasons[r.randrange(3)]})
        decisions.sort(key=lambda d: (d["decided_at"], d["cand"]["candidate_id"]))
        for k, d in enumerate(decisions, 1):
            d["merge_id"] = f"md-{k:04d}"
        self.cands, self.decisions = cands, decisions

    # ---- entity rows ------------------------------------------------------------------------------------------------------
    def entities(self) -> dict[str, list[dict]]:
        quality_rules = []
        for x in self.rules:
            quality_rules.append({
                "rule_id": x.rule_id, "dataset_id": x.ds, "field_id": self.field_id.get((x.ds, x.field)) if x.field else None,
                "rule_type": x.rtype, "severity": x.severity, "version_number": x.version,
                "status": "disabled" if x.disabled_day is not None else "active",
                "disabled_at": ts(x.disabled_at) if x.disabled_at else None, "disabled_reason": x.disabled_reason, "definition": x.definition()})
        rule_runs = []
        for u in self.runs:
            rule_runs.append({"rule_run_id": u["id"], "rule_id": u["rule"].rule_id, "rule_version": u["ver"], "weight_version": weight_version_at(u["at"]),
                              "kind": u["kind"], "run_at": ts(u["at"]), "eligible_count": u["E"], "failure_count": u["F"],
                              "rerun_for_issue": u.get("rerun_for")})
        issues = []
        for i in self.issues:
            issues.append({"issue_id": i["id"], "rule_run_id": i["base"]["id"], "owner_id": i["owner"], "status": i["status"], "detected_at": ts(i["det"]),
                           "due_at": ts(i["due"]) if i["due"] else None, "closed_at": ts(i["closed"]) if i["closed"] else None,
                           "verification_run_id": i["ver"]["id"] if i["ver"] else None, "reopened_at": [ts(t) for t in i["reopened"]]})
        cands = [{"candidate_id": c["candidate_id"], "left_record_id": c["left_record_id"], "right_record_id": c["right_record_id"], "score": c["score"],
                  "features": c["features"], "explanation": c["explanation"], "uncertainty": c["uncertainty"], "proposed_by": c["proposed_by"],
                  "proposed_at": ts(c["proposed_at"])} for c in self.cands]
        decs = [{"merge_id": d["merge_id"], "candidate_id": d["cand"]["candidate_id"], "reviewer_id": d["reviewer_id"], "decision": d["decision"],
                 "decided_at": ts(d["decided_at"]), "reverses_merge_id": d["reverses"]["merge_id"] if d["reverses"] else None, "reason": d["reason"]}
                for d in self.decisions]
        flat_rows = []
        for dsid in sorted(self.rows):
            for row in self.rows[dsid]:
                flat_rows.append({"dataset_id": dsid, **row})
        return {"owners": self.owners, "datasets": self.ds_list, "fields": self.fields, "quality_rules": quality_rules, "rule_runs": rule_runs,
                "issues": issues, "lineage_edges": self.edges, "metric_versions": self.metric_versions, "definition_changes": self.definition_changes,
                "customer_records": self.customer_records, "match_candidates": cands, "merge_decisions": decs, "dataset_rows": flat_rows,
                "weight_versions": WEIGHTS}

    def build_all(self) -> None:
        self.build_register()
        self.build_rules()
        self.build_rows()
        self.measure_all()
        self.build_runs()
        self.build_issues()
        self.build_lineage()
        self.build_metrics()
        self.build_customers()
        self.build_matching()


    # ---- statistics and designed relationships ---------------------------------------------------------------------------
    def hours(self, a: datetime, b: datetime) -> Fraction:
        return Fraction(int((b - a).total_seconds()), 3600)

    def stats(self) -> dict[str, Any]:
        sc = self.dataset_scores()
        self.scores = sc
        cls: dict[str, int] = {}
        for i in self.issues:
            cls[i["cls"]] = cls.get(i["cls"], 0) + 1
        resolved = [i for i in self.issues if i["cls"] == "resolved"]
        by_team: dict[str, list[Fraction]] = {"fast": [], "other": []}
        for i in resolved:
            by_team["fast" if i["fast"] else "other"].append(self.hours(i["det"], i["ver"]["at"]))
        mean = lambda xs: sum(xs, Fraction(0)) / len(xs) if xs else None  # noqa: E731
        unresolved = sorted((i for i in self.issues if i["cls"] != "resolved"), key=lambda i: (i["det"], i["id"]))
        k = 0
        while k < len(unresolved) and unresolved[k]["cls"] == "claimed":
            k += 1
        approvals = [d for d in self.decisions if d["decision"] == "approve"]
        ok = sum(1 for d in approvals if d["cand"]["same"])
        rev = [d for d in self.decisions if d["decision"] == "reverse"]
        reviewed = {d["cand"]["candidate_id"] for d in self.decisions if d["decision"] != "reverse"}
        rev_same = sum(1 for c in self.cands if c["candidate_id"] in reviewed and c["same"])
        self.match_stats = {"candidates": len(self.cands), "reviewed": len(reviewed), "approved": len(approvals), "approved_correct": ok,
                            "precision": p6(Fraction(ok, len(approvals))), "reviewed_correct_share": p6(Fraction(rev_same, len(reviewed))),
                            "rejected": len(reviewed) - len(approvals), "reversals": len(rev),
                            "reversed_wrong_approvals": sum(1 for d in rev if not d["reverses"]["cand"]["same"]),
                            "households_candidates": sum(1 for c in self.cands if c["kind"] == "household"),
                            "households_wrongly_approved": sum(1 for d in approvals if d["cand"]["kind"] == "household"),
                            "near_name_candidates": sum(1 for c in self.cands if c["kind"] == "near"),
                            "shared_name_address_candidates": sum(1 for c in self.cands if c["uncertainty"]),
                            "entities": len(set(self.truth.values()))}
        scored = {d: v for d, v in sc.items() if v["scores"]["w2"] is not None}
        moved = {d: v["scores"]["w2"] - v["scores"]["w1"] for d, v in scored.items()}
        self.weight_stats = {
            "datasets_scored": len(scored), "datasets_moved_at_least_0.005": sum(1 for x in moved.values() if abs(x) >= Fraction(5, 1000)),
            "datasets_with_different_score": sum(1 for x in moved.values() if x != 0),
            "mean_score_w1": p6(sum((v["scores"]["w1"] for v in scored.values()), Fraction(0)) / len(scored)),
            "mean_score_w2": p6(sum((v["scores"]["w2"] for v in scored.values()), Fraction(0)) / len(scored)),
            "largest_move": p6(max(moved.values(), key=abs)),
            "rule_version_changes_days": sorted(c for x in self.rules for c in x.changes if c < N_DAYS),
            "rule_version_changes_within_14_days_of_the_weight_change": sum(1 for x in self.rules for c in x.changes if 36 <= c <= 64)}
        self.team_stats = {"fast_team": FAST_TEAM, "fast_resolved": len(by_team["fast"]), "other_resolved": len(by_team["other"]),
                           "fast_mean_hours": rhu(mean(by_team["fast"]), 4), "other_mean_hours": rhu(mean(by_team["other"]), 4),
                           "ratio": p6(mean(by_team["fast"]) / mean(by_team["other"])), "fast_datasets": self.fast_ds}
        self.oldest = {"unresolved": len(unresolved), "leading_claimed_run": k, "all_of_the_oldest_25_claimed": all(i["cls"] == "claimed" for i in unresolved[:25]),
                       "first_not_claimed": unresolved[k]["id"] if k < len(unresolved) else None,
                       "first_not_claimed_detected_at": ts(unresolved[k]["det"]) if k < len(unresolved) else None,
                       "oldest_detected_at": ts(unresolved[0]["det"]), "oldest_issue": unresolved[0]["id"],
                       "claimed_before_2026-08-25": sum(1 for i in unresolved if i["det"] < EARLY_CUT and i["cls"] == "claimed")}
        self.issue_stats = {"issues": len(self.issues), "by_class": dict(sorted(cls.items())), "reopened": sum(1 for i in self.issues if i["reopened"]),
                            "claimed_with_failed_rerun": sum(1 for i in self.issues if i["failed_rerun"]),
                            "scheduled_runs": self.scheduled, "reruns": sum(1 for u in self.runs if u["kind"] == "rerun")}
        return sc

    # ---- injections ---------------------------------------------------------------------------------------------------------
    def build_injections(self) -> tuple[list[dict], list[dict], list[dict]]:
        r = self.rs["injections"]
        sc = self.stats()
        VER = f"{VERSION_TAG}-{self.seed}-{DATE_TAG}"
        cust = self.rules[2]
        crit_issue = next(i for i in self.issues if i["base"]["rule"] is cust and i["cls"] == "open")
        crit_run = crit_issue["base"]
        s_c = sc["ds-customers"]["scores"]
        orders_fk = self.rule_by_id["r-orders-fk-customer_key"]
        mo = self.cur[orders_fk.rule_id]
        inj12 = self.inj12_rule
        inj12_cur, inj12_old = self.cur[inj12.rule_id], self.old[inj12.rule_id]
        # replay actors
        H = {"analyst": {"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "analyst"}, "steward": {"X-Actor-Id": "usr-steward01", "X-Actor-Role": "steward"},
             "steward2": {"X-Actor-Id": "usr-steward02", "X-Actor-Role": "steward"}}

        def actor(i: str, role: str = "steward") -> dict:
            return {"X-Actor-Id": i, "X-Actor-Role": role}

        def step(ev: str, n: str, command: str, hdr: dict, inp: dict, status: int, reason: str | None = None, result: dict | None = None,
                 warnings: list[str] | None = None, bind: list | None = None) -> dict:
            s: dict[str, Any] = {"kind": "command", "command": command, "headers": hdr,
                                 "input": {"request_id": f"req-{ev}-{n}".lower(), "dataset_version": VER, "idempotency_key": f"{ev}-{n}".lower(), "input": inp},
                                 "expected_status": status}
            if reason:
                s["expected_reason"] = reason
            if result:
                s["expected_result"] = result
            if warnings:
                s["expected_warning_codes"] = warnings
            if bind:
                s["bind"] = bind
            return s

        def read(path: str, params: dict, expect: list) -> dict:
            return {"kind": "read", "path": path, "params": params, "expect": expect, "expected_status": 200}

        events = []
        # EV-01
        events.append({"event_id": "EV-01", "injection": "INJ-01", "requires": [crit_issue["id"]], "steps": [
            step("ev-01", "a", "run-rule", H["analyst"], {"rule_id": cust.rule_id}, 200, result={"status": "measured", "result": {"eligible_count": 120, "failure_count": 2, "severity": "critical"}},
                 warnings=["CRITICAL_FAILURE"]),
            read("/metrics", {"as_of": "2026-10-05T00:00:00Z"}, [
                {"path": "metrics.weighted_score.datasets.ds-customers.critical_override", "equals": True},
                {"path": "metrics.weighted_score.datasets.ds-customers.value", "equals": p6(s_c["w2"])}])]})
        # EV-02: disable a further active rule and read its retained history
        act = [x for x in self.active_rules() if not x.designated and not x.inj12 and x.severity != "critical"]
        def n_issues(x: Rule) -> int:
            return sum(1 for i in self.issues if i["base"]["rule"] is x)
        pick2 = max(act, key=lambda x: (n_issues(x), -x.idx))
        runs_n = sum(1 for u in self.runs if u["rule"] is pick2)
        unres = sum(1 for i in self.issues if i["base"]["rule"] is pick2 and (i["status"] != "closed" or i["ver"] is None))
        self.inj02_rule = pick2
        events.append({"event_id": "EV-02", "injection": "INJ-02", "requires": [pick2.rule_id], "steps": [
            step("ev-02", "a", "disable-rule", H["steward"], {"rule_id": pick2.rule_id, "reason": "Replay: the rule is retired; its history must stay readable"}, 200,
                 result={"status": "disabled", "result": {"status": "disabled", "runs_retained": runs_n, "unresolved_issues": unres}}),
            step("ev-02", "b", "run-rule", H["analyst"], {"rule_id": pick2.rule_id}, 409, "RULE_DISABLED"),
            read("/metrics", {"as_of": "2026-10-27T00:00:00Z"}, [
                {"path": f"rules.disabled.{pick2.rule_id}.runs_retained", "equals": runs_n},
                {"path": f"rules.disabled.{pick2.rule_id}.issues_retained", "equals": n_issues(pick2)}])]})
        # EV-03
        ua, ub = self.unlinked_households[0]
        lo, hi = sorted((ua["id"], ub["id"]))
        events.append({"event_id": "EV-03", "injection": "INJ-03", "requires": [lo, hi], "steps": [
            step("ev-03", "a", "suggest-match", H["analyst"], {"left_record_id": lo, "right_record_id": hi, "score": "0.930000",
                 "features": {"name_similarity": "1.000000", "address_match": "1.000000"}, "explanation": "Same name and address in two systems"}, 200,
                 result={"status": "proposed", "result": {"merged": False, "uncertainty": "Shared name and address; possible household"}},
                 warnings=["SHARED_NAME_AND_ADDRESS"])]})
        # EV-04
        events.append({"event_id": "EV-04", "injection": "INJ-04", "requires": [orders_fk.rule_id], "steps": [
            step("ev-04", "a", "run-rule", H["analyst"], {"rule_id": orders_fk.rule_id}, 200,
                 result={"status": "measured", "result": {"eligible_count": mo["E"], "failure_count": mo["F"], "null_fk_count": mo["nulls"]}})]})
        # EV-05
        w2 = WEIGHTS[1]["weights"]
        changed = dict(w2, completeness="0.300000", uniqueness="0.200000")
        events.append({"event_id": "EV-05", "injection": "INJ-05", "requires": ["w2"], "steps": [
            step("ev-05", "a", "run-rule", H["analyst"], {"rule_id": self.rules[0].rule_id, "weight_version": "w2", "weights": changed}, 422, "WEIGHT_CHANGE_REQUIRES_VERSION"),
            step("ev-05", "b", "run-rule", H["analyst"], {"rule_id": self.rules[0].rule_id, "weight_version": "w2", "weights": dict(w2)}, 200,
                 result={"status": "measured", "result": {"weight_version": "w2"}})]})
        # EV-06: a merge by the proposer, then an independent one, a reversal without a reason, the reversal, a second reversal
        unrev = sorted(c["candidate_id"] for c in self.cands if c["candidate_id"] not in {d["cand"]["candidate_id"] for d in self.decisions} and c["kind"] == "true")
        c6 = next(c for c in self.cands if c["candidate_id"] == unrev[0])
        other = next(o for o in self.reviewers if o != c6["proposed_by"])
        bind = [{"into": "merge_id", "from_step": 1, "path": "result.merge_id"}]
        events.append({"event_id": "EV-06", "injection": "INJ-06", "requires": [c6["candidate_id"]], "steps": [
            step("ev-06", "a", "approve-merge", actor(c6["proposed_by"]), {"candidate_id": c6["candidate_id"], "decision": "approve"}, 403, "REVIEWER_IS_PROPOSER"),
            step("ev-06", "b", "approve-merge", actor(other), {"candidate_id": c6["candidate_id"], "decision": "approve"}, 200,
                 result={"status": "linked", "result": {"state": "linked", "maps": {"from_record_id": c6["right_record_id"], "to_record_id": c6["left_record_id"]}}}),
            step("ev-06", "c", "reverse-merge", actor(other), {"merge_id": "$merge_id", "reason": "  "}, 422, "REASON_REQUIRED", bind=bind),
            step("ev-06", "d", "reverse-merge", actor(other), {"merge_id": "$merge_id", "reason": "Different people in one household"}, 200,
                 result={"status": "reversed", "result": {"restored": {c6["left_record_id"]: c6["left_record_id"], c6["right_record_id"]: c6["right_record_id"]}}}, bind=bind),
            step("ev-06", "e", "reverse-merge", actor(other), {"merge_id": "$merge_id", "reason": "Again"}, 409, "ALREADY_REVERSED", bind=bind)]})
        # EV-07
        uncovered = sorted(d["dataset_id"] for d in self.ds_list if self.deact.get(d["owner_id"]))
        events.append({"event_id": "EV-07", "injection": "INJ-07", "requires": ["own-12"], "steps": [
            step("ev-07", "a", "register-dataset", H["analyst"], {"dataset_id": "ds-replay-orphaned", "dataset_name": "Replay dataset", "source_system": "crm",
                 "owner_id": "own-12", "classification": "internal"}, 422, "OWNER_INACTIVE"),
            step("ev-07", "b", "register-dataset", H["analyst"], {"dataset_id": "ds-replay-owned", "dataset_name": "Replay dataset", "source_system": "crm",
                 "owner_id": "own-02", "classification": "internal"}, 200, result={"status": "cataloged"}),
            read("/metrics", {"as_of": "2026-10-05T00:00:00Z"}, [{"path": "metrics.ownership_coverage.uncovered", "equals": uncovered},
                                                                   {"path": "metrics.ownership_coverage.covered", "equals": 40 - len(uncovered)}])]})
        # EV-08: an inferred edge presented as observed
        inf = self.inferred[0]
        events.append({"event_id": "EV-08", "injection": "INJ-08", "requires": [f"{inf[0]}->{inf[1]}"], "steps": [
            {"kind": "database", "table": "lineage_edges", "row": {"edge_id": "ex-observed-without-time", "source_dataset_id": inf[0], "target_dataset_id": inf[1],
                                                                    "evidence_type": "observed", "observed_at": None}, "expected_error": "edges_evidence_ck"},
            {"kind": "database", "table": "lineage_edges", "row": {"edge_id": "ex-inferred-extra", "source_dataset_id": "ds-leads", "target_dataset_id": "ds-segments",
                                                                    "evidence_type": "inferred", "observed_at": None}, "expected": "inserted"},
            read("/metrics", {"as_of": "2026-10-05T00:00:00Z"}, [{"path": "metrics.lineage_coverage.value", "equals": "0.725000"},
                                                                   {"path": "metrics.lineage_coverage.observed_distinct", "equals": 70},
                                                                   {"path": "metrics.lineage_coverage.inferred_edges", "length": 11}])]})
        # EV-09: claimed is not resolved
        events.append({"event_id": "EV-09", "injection": "INJ-09", "requires": [crit_issue["id"]], "steps": [
            step("ev-09", "a", "triage-issue", H["analyst"], {"issue_id": crit_issue["id"], "action": "claim", "note": "Replay: closed without a rerun"}, 200,
                 result={"status": "claimed", "result": {"class": "claimed"}}, warnings=["CLAIMED_NOT_RESOLVED"]),
            step("ev-09", "b", "verify-remediation", H["steward"], {"issue_id": crit_issue["id"]}, 200,
                 result={"status": "claimed", "result": {"verified": False, "reasons": ["RERUN_STILL_FAILING"]}})]})
        # EV-10
        used = {c["left_record_id"] for c in self.cands} | {c["right_record_id"] for c in self.cands}
        free = [c for c in self.customer_records if c["record_id"] not in used]
        x = free[0]
        y = next(c for c in free[1:] if c["normalized_name"] != x["normalized_name"] and c["address_key"] != x["address_key"])
        c10 = self.cands[0]
        feats = {"name_similarity": "0.500000", "address_match": "0.000000"}
        events.append({"event_id": "EV-10", "injection": "INJ-10", "requires": [c10["candidate_id"]], "steps": [
            step("ev-10", "a", "suggest-match", H["analyst"], {"left_record_id": c10["right_record_id"], "right_record_id": c10["left_record_id"], "score": "0.900000",
                 "features": feats, "explanation": "The same pair, the other way round"}, 409, "DUPLICATE_PAIR"),
            step("ev-10", "b", "suggest-match", H["analyst"], {"left_record_id": y["record_id"], "right_record_id": x["record_id"], "score": "0.300000",
                 "features": feats, "explanation": "A new pair in reverse order"}, 422, "NON_CANONICAL_ORDER"),
            step("ev-10", "c", "suggest-match", H["analyst"], {"left_record_id": x["record_id"], "right_record_id": y["record_id"], "score": "0.300000",
                 "features": feats, "explanation": "A new pair in canonical order"}, 200, result={"status": "proposed", "result": {"merged": False}})]})
        # EV-11
        v2ids = {m["metric_id"] for m in self.metric_versions if m["version_number"] == 2}
        single = next(m for m in self.metric_versions if m["metric_id"] not in v2ids and m["grain"] and m["source_fields"] and m["owner_id"] and m["refresh"])
        base11 = {"metric_id": single["metric_id"], "metric_name": single["metric_name"], "definition": "Rewritten in place", "grain": single["grain"],
                  "source_fields": single["source_fields"], "owner_id": single["owner_id"], "refresh": single["refresh"]}
        events.append({"event_id": "EV-11", "injection": "INJ-11", "requires": [single["metric_version_id"]], "steps": [
            step("ev-11", "a", "publish-definition", H["steward"], dict(base11, metric_version_id=single["metric_version_id"], reason="Rewrite"), 409, "DEFINITION_IMMUTABLE"),
            step("ev-11", "b", "publish-definition", H["steward"], dict(base11, definition="Revised definition as a new version", reason="Replay: revised in a new version"), 200,
                 result={"status": "published", "result": {"version_number": 2, "previous_metric_version_id": single["metric_version_id"]}})]})
        # EV-12
        events.append({"event_id": "EV-12", "injection": "INJ-12", "requires": [inj12.rule_id], "steps": [
            step("ev-12", "a", "run-rule", H["analyst"], {"rule_id": inj12.rule_id}, 200,
                 result={"status": "measured", "result": {"eligible_count": inj12_cur["E"], "comparison": {"comparable": False, "reason": "RULE_VERSION_DIFFERS",
                         "previous_eligible_count": inj12_old["E"]}}}, warnings=["RULE_VERSION_DIFFERS"])]})
        self.replay_context = {"crit_issue": crit_issue["id"], "pick2": pick2.rule_id}

        # ---- the manifest of the injections ----
        disabled = [{"rule_id": x.rule_id, "disabled_at": ts(x.disabled_at), "runs_retained": sum(1 for u in self.runs if u["rule"] is x),
                     "issues_retained": n_issues(x)} for x in sorted(self.disabled_rules, key=lambda x: x.idx)]
        households = [c for c in self.cands if c["kind"] == "household"]
        rev0 = next(d for d in self.decisions if d["decision"] == "reverse")
        rc = rev0["cand"]
        claimed = [i for i in self.issues if i["cls"] == "claimed"]
        m2 = next(m for m in self.metric_versions if m["version_number"] == 2)
        ship_mv = [x for x in self.rules if x.changes and x.changes[0] < N_DAYS]
        inj = [
            {"id": "INJ-01", "test": "P07-TEST-01", "name": "critical failure under a high weighted score", "location": "both",
             "defect": "ds-customers scores near 1 on every dimension while its critical key rule fails and a critical issue is open.",
             "records": [{"entity": "datasets", "id": "ds-customers"}, {"entity": "quality_rules", "id": cust.rule_id}, {"entity": "issues", "id": crit_issue["id"]}],
             "expected_handling": "critical_override is true beside the score; the score is shown, never used to hide the failure; critical_failures 2 and one open critical issue.",
             "expected_rejections": [], "events": ["EV-01"],
             "checks": [{"path": "metrics.weighted_score.datasets.ds-customers.critical_override", "equals": True},
                        {"path": "metrics.weighted_score.datasets.ds-customers.critical_failures", "equals": 2},
                        {"path": "metrics.weighted_score.datasets.ds-customers.critical_open_issues", "equals": 1},
                        {"path": "metrics.weighted_score.datasets.ds-customers.value", "equals": p6(s_c["w2"])},
                        {"path": "metrics.weighted_score.by_weight_version.w1.ds-customers", "equals": p6(s_c["w1"])}]},
            {"id": "INJ-02", "test": "P07-TEST-02", "name": "a disabled rule's history vanishes", "location": "both",
             "defect": "Five rules are disabled with a reason and a date; their runs and issues must stay readable and the issues stay unresolved.",
             "records": [{"entity": "quality_rules", "id": d["rule_id"]} for d in disabled], "disabled_rules": disabled,
             "expected_handling": "rules.disabled lists each rule with runs_retained and issues_retained; no current run; disabling is not repair.",
             "expected_rejections": [], "events": ["EV-02"],
             "checks": [c for d in disabled for c in ({"path": f"rules.disabled.{d['rule_id']}.runs_retained", "equals": d["runs_retained"]},
                                                       {"path": f"rules.disabled.{d['rule_id']}.issues_retained", "equals": d["issues_retained"]})]},
            {"id": "INJ-03", "test": "P07-TEST-03", "name": "a shared name-and-address pair", "location": "both",
             "defect": "25 candidates are two different people who share a name and an address (a household); six more such pairs are not yet candidates.",
             "records": [{"entity": "match_candidates", "id": c["candidate_id"]} for c in households],
             "expected_handling": "Each is stored once with the uncertainty 'Shared name and address; possible household' and waits for a human decision; none is merged automatically.",
             "expected_rejections": [], "events": ["EV-03"],
             "checks": [{"path": "matching.candidates", "equals": 400}]},
            {"id": "INJ-04", "test": "P07-TEST-04", "name": "null foreign keys silently excluded", "location": "both",
             "defect": f"ds-orders has {mo['nulls']} null customer_key values among {mo['total']} (eligible by the rule {mo['E']}).",
             "records": [{"entity": "quality_rules", "id": orders_fk.rule_id}],
             "expected_handling": "Excluded from the denominator and counted separately as null_fk_count; never matched, never failed.",
             "expected_rejections": [], "events": ["EV-04"],
             "checks": [{"path": f"metrics.relationship_integrity.{orders_fk.rule_id}.null_fk_count", "equals": mo["nulls"]},
                        {"path": f"metrics.relationship_integrity.{orders_fk.rule_id}.eligible_count", "equals": mo["E"]},
                        {"path": f"metrics.relationship_integrity.{orders_fk.rule_id}.unmatched_count", "equals": mo["F"]}]},
            {"id": "INJ-05", "test": "P07-TEST-05", "name": "a weight change without a version", "location": "both",
             "defect": "The weights change on 2026-09-01 as a new version w2; a request to run a rule with other weights under the name w2 is the defect.",
             "records": [{"entity": "weight_versions", "id": "w1"}, {"entity": "weight_versions", "id": "w2"}],
             "expected_handling": "Scores differ between w1 and w2 on identical rows and are labelled with the version; C03 refuses changed weights (422 WEIGHT_CHANGE_REQUIRES_VERSION).",
             "expected_rejections": [], "events": ["EV-05"],
             "checks": [{"path": "metrics.weighted_score.by_weight_version.w1.ds-orders", "equals": p6(sc["ds-orders"]["scores"]["w1"])},
                        {"path": "metrics.weighted_score.by_weight_version.w2.ds-orders", "equals": p6(sc["ds-orders"]["scores"]["w2"])}]},
            {"id": "INJ-06", "test": "P07-TEST-06", "name": "an irreversible merge", "location": "both",
             "defect": "15 approved merges are reversed; a merge by its own proposer must be refused and every merge must stay reversible.",
             "records": [{"entity": "merge_decisions", "id": rev0["merge_id"]}, {"entity": "merge_decisions", "id": rev0["reverses"]["merge_id"]}],
             "expected_handling": "A reversal restores both identities and keeps the mapping history; reviewer = proposer is refused (403 REVIEWER_IS_PROPOSER).",
             "expected_rejections": [], "events": ["EV-06"],
             "checks": [{"path": "matching.merges_reversed", "equals": 15}, {"path": f"matching.identity_map.{rc['right_record_id']}", "equals": rc["right_record_id"]},
                        {"path": f"matching.identity_map.{rc['left_record_id']}", "equals": rc["left_record_id"]}]},
            {"id": "INJ-07", "test": "P07-TEST-07", "name": "an inactive owner counted as covered", "location": "both",
             "defect": "Three owners are inactive and still own five datasets.", "records": [{"entity": "datasets", "id": d} for d in uncovered],
             "expected_handling": "Ownership coverage counts only datasets whose owner is active: 35/40; the five are listed as uncovered; registering a dataset with an inactive owner is refused.",
             "expected_rejections": [], "events": ["EV-07"],
             "checks": [{"path": "metrics.ownership_coverage.uncovered", "equals": uncovered}, {"path": "metrics.ownership_coverage.value", "equals": p6(Fraction(40 - len(uncovered), 40))}]},
            {"id": "INJ-08", "test": "P07-TEST-08", "name": "inferred lineage shown as observed", "location": "both",
             "defect": "Ten inferred edges (four on declared edges that were never observed) and an observed edge without an observation time.",
             "records": [{"entity": "lineage_edges", "id": e["edge_id"]} for e in self.edges if e["evidence_type"] == "inferred"],
             "expected_handling": "Inferred edges are listed apart and never enter the observed numerator: coverage 58/80; the database refuses an observed edge without observed_at.",
             "expected_rejections": [], "events": ["EV-08"],
             "checks": [{"path": "metrics.lineage_coverage.value", "equals": "0.725000"}, {"path": "metrics.lineage_coverage.observed_distinct", "equals": 70},
                        {"path": "metrics.lineage_coverage.observed_matching_declared", "equals": 58}, {"path": "metrics.lineage_coverage.undeclared_observed", "length": 12},
                        {"path": "metrics.lineage_coverage.inferred_edges", "length": 10}]},
            {"id": "INJ-09", "test": "P07-TEST-09", "name": "an issue closed without a rerun", "location": "both",
             "defect": f"{len(claimed)} issues are closed without a verifying rerun (the oldest unresolved issues are all among them).",
             "records": [{"entity": "issues", "id": i["id"]} for i in claimed[:10]],
             "expected_handling": "Listed as claimed, never counted as resolved; C10 verify-remediation leaves it claimed unless a rerun of the same rule version passes.",
             "expected_rejections": [], "events": ["EV-09"],
             "checks": [{"path": "metrics.resolution_time.claimed_count", "equals": len(claimed)}, {"path": f"metrics.resolution_time.issues.{claimed[0]['id']}.class", "equals": "claimed"}]},
            {"id": "INJ-10", "test": "P07-TEST-10", "name": "a duplicate pair stored both ways", "location": "replay",
             "defect": "A pair submitted in both orientations, and a first-seen pair with the larger id on the left.",
             "records": [], "expected_handling": "A pair is stored once with left < right; the reverse is 409 DUPLICATE_PAIR and a first-seen reverse-order pair is 422 NON_CANONICAL_ORDER. The clean file holds 400 distinct canonical pairs.",
             "expected_rejections": [], "events": ["EV-10"], "checks": [{"path": "matching.candidates", "equals": 400}]},
            {"id": "INJ-11", "test": "P07-TEST-11", "name": "a published definition rewritten in place", "location": "both",
             "defect": "15 metrics have a second version created by a change record; rewriting a published version in place is the defect.",
             "records": [{"entity": "metric_versions", "id": m2["metric_version_id"]}, {"entity": "definition_changes", "id": self.definition_changes[0]["change_id"]}],
             "expected_handling": "A change is a new metric_versions row with valid_from and a definition_changes row; an existing metric_version_id is refused (409 DEFINITION_IMMUTABLE).",
             "expected_rejections": [], "events": ["EV-11"],
             "checks": [{"path": "definitions.change_records", "equals": 15}, {"path": "definitions.versions_without_change_record", "length": 0},
                        {"path": "definitions.changes_with_mismatched_valid_from", "length": 0}, {"path": f"definitions.version_counts.{m2['metric_id']}", "equals": 2}]},
            {"id": "INJ-12", "test": "P07-TEST-12", "name": "a denominator change between compared runs", "location": "both",
             "defect": f"{inj12.rule_id} gained an eligibility filter in version 2 after its last stored run (version 1); {len(self.v2_rules) - 1} other rules changed version earlier.",
             "records": [{"entity": "quality_rules", "id": inj12.rule_id}],
             "expected_handling": "The two runs are not comparable (RULE_VERSION_DIFFERS) and no rates are compared; the other changed rules compare version 2 with version 2.",
             "expected_rejections": [], "events": ["EV-12"],
             "checks": [{"path": f"rules.comparisons.{inj12.rule_id}.comparable", "equals": False}, {"path": f"rules.comparisons.{inj12.rule_id}.reason", "equals": "RULE_VERSION_DIFFERS"},
                        {"path": f"rules.comparisons.{inj12.rule_id}.previous_eligible_count", "equals": inj12_old["E"]},
                        {"path": f"rules.comparisons.{inj12.rule_id}.current_eligible_count", "equals": inj12_cur["E"]}]}]
        # ---- designed relationships ----
        ow = self.ownership()
        dr = [
            {"id": "DR-01", "name": "a near-perfect score and an open critical key failure", "statement": "ds-customers scores above 0.95 under both weight versions while its critical key rule fails.",
             "realised": {"dataset_id": "ds-customers", "rule_id": cust.rule_id, "weighted_score_w2": p6(s_c["w2"]), "weighted_score_w1": p6(s_c["w1"]),
                          "critical_failures": 2, "critical_open_issues": 1, "issue_id": crit_issue["id"], "critical_override": True,
                          "datasets_overridden": sum(1 for v in sc.values() if v["critical_failures"] > 0) }},
            {"id": "DR-02", "name": "inactive owners leave five datasets uncovered", "statement": "Three inactive owners own five datasets.",
             "realised": {"uncovered": uncovered, "inactive_owners": sorted(o for o, d in self.deact.items() if d), "covered": 40 - len(uncovered), "value": p6(Fraction(40 - len(uncovered), 40))}},
            {"id": "DR-03", "name": "the weight change moves scores without any rule change", "statement": "Identical rows and rules score differently under w1 and w2.",
             "realised": dict(self.weight_stats, weight_change="2026-09-01T00:00:00Z",
                              runs_under_w1=sum(1 for u in self.runs if weight_version_at(u["at"]) == "w1"), runs_under_w2=sum(1 for u in self.runs if weight_version_at(u["at"]) == "w2"))},
            {"id": "DR-04", "name": "one team resolves twice as fast", "statement": "Issues owned by the Data Platform team resolve in less than half the mean time of the others.", "realised": self.team_stats},
            {"id": "DR-05", "name": "the oldest unresolved issues are all claimed-not-verified", "statement": "The oldest unresolved issues were closed without a verifying rerun.", "realised": self.oldest},
            {"id": "DR-06", "name": "matching: precision from the synthetic truth", "statement": "Precision is approved decisions confirmed by the truth over approved decisions (the truth is in the manifest only).",
             "realised": self.match_stats}]
        return inj, events, dr

    def ownership(self) -> dict:
        return {}


# ---------------------------------------------------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------------------------------------------------
DISCLOSURES = [
    "No realised outcome was re-drawn, kept or dropped because of its value. The designed relationships are built into the draws as parameters chosen "
    "BEFORE the first run (the fast team's delay scale is 900 minutes against 2,400; issues detected before 2026-08-25 are never left open; critical rules "
    "other than ds-customers' stop failing on 2026-09-20), and they came out as designed on the first run; nothing was tuned afterwards.",
    "The sizes (rule runs and issues, see row_counts) are what the stated parameters gave; start offsets and the issue probability were set to reach "
    "'about 4,500' and 'about 600' before looking at any other outcome. Two code changes altered the draws before the final run (a stray draw was removed "
    "from the rules stream, and the window kept free of rule-version changes around the weight change was widened from 7 to 14 days after the "
    "realised changes were seen to fall 8 to 14 days from it); the reported world is the first run of the final code and nothing was re-drawn after it.",
    "Match precision, the households wrongly approved and the reversals are drawn from reviewer probabilities (true pair approved 94 %, household 25 %, near name 12 %; "
    "reversals weighted 8:1 towards wrong approvals); the realised values are reported, not steered.",
    "The size cap of 5 MB did not bind: every count of the specification is met.",
]


def entity_text(name: str, version: str, rows: list[dict]) -> str:
    body = ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return f'{{"entity":{json.dumps(name)},"dataset_version":{json.dumps(version)},"rows":[\n{body}\n]}}\n'


def dataset_hash(ents: dict[str, list[dict]]) -> str:
    h = hashlib.sha256()
    for name in sorted(ents):
        h.update(canonical(ents[name]).encode())
    return h.hexdigest()


def build(seed: int) -> World:
    w = World(seed)
    w.build_all()
    w.ents = w.entities()
    w.injections, w.events, w.designed = w.build_injections()
    return w


def to_inputs(ents: dict[str, list[dict]]) -> dict[str, Any]:
    inp = json.loads(json.dumps(CONFIG))
    for k in DOMAIN12:
        inp[k] = ents[k]
    rows: dict[str, list[dict]] = {}
    for r in ents["dataset_rows"]:
        r = dict(r)
        rows.setdefault(r.pop("dataset_id"), []).append(r)
    inp["dataset_rows"] = rows
    inp["weight_versions"] = ents["weight_versions"]
    return inp


def write_golden(out: Path) -> None:
    fx = APP_ROOT / "tests" / "fixtures" / "golden"
    inputs = json.loads((fx / "inputs.json").read_text())
    hashes = json.loads((fx / "HASHES.json").read_text())
    gdir = out / "golden"
    gdir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in DOMAIN12:
        rows = inputs.get(name, [])
        counts[name] = len(rows)
        (gdir / f"{name}.json").write_text(entity_text(name, "golden-v1", rows))
    flat = [{"dataset_id": d, **row} for d in sorted(inputs["dataset_rows"]) for row in inputs["dataset_rows"][d]]
    counts["dataset_rows"] = len(flat)
    (gdir / "dataset_rows.json").write_text(entity_text("dataset_rows", "golden-v1", flat))
    counts["weight_versions"] = len(inputs["weight_versions"])
    (gdir / "weight_versions.json").write_text(entity_text("weight_versions", "golden-v1", inputs["weight_versions"]))
    (gdir / "expected.json").write_text((fx / "expected.json").read_text())
    config = {k: inputs[k] for k in ("contract_version", "as_of", "whitespace_policy", "weight_version", "checklist_version", "checklist_versions", "probes")}
    manifest = {"contract_version": CONTRACT_VERSION, "dataset_hash": hashes["sha256"]["inputs.json"], "dataset_version": "golden-v1",
                "generated_at": "2026-10-26T00:00:00Z", "generator": {"name": "tests/fixtures/golden (hand-derived, no generator)", "seed": 0, "parameters": {}},
                "designed_relationships": [], "fixture_id": "trustledger-golden-v1", "as_of": inputs["as_of"], "config": config, "expected": "expected.json",
                "row_counts": counts, "synthetic_truth": inputs["synthetic_truth"]}
    (gdir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def parameters(w: World) -> dict[str, Any]:
    return {"datasets": "40", "source_systems": "6", "fields": "420", "owners": "18", "inactive_owners": "3", "metrics": "30", "metric_versions": "45",
            "definition_changes": "15", "quality_rules": "60", "weight_versions": "2", "weight_change": "2026-09-01T00:00:00Z",
            "window": "2026-07-13 .. 2026-10-04 (84 daily runs)", "as_of": "2026-10-05T00:00:00Z", "customer_records": "2000", "customer_systems": "3",
            "match_candidates": "400", "reviewed_decisions": "220", "reversals": "15", "declared_edges": "80", "observed_edges": "70",
            "undeclared_observed": "12", "inferred_edges": "10", "fast_team": FAST_TEAM, "fast_delay_scale_minutes": "900", "other_delay_scale_minutes": "2400",
            "issue_class_split_early": "resolved 72 / claimed 28 per hundred before 2026-08-25", "issue_class_split_late": "resolved 55 / claimed 12 / open 33 per hundred",
            "issue_probability": "600 expected issues over the failing scheduled runs, weighted by severity 30/14/10/6",
            "reviewer_approve_true_pair": "0.940000", "reviewer_approve_household": "0.250000", "reviewer_approve_near_name": "0.120000",
            "offsets_minutes": canonical(OFFSET_MIN), "size_cap_bytes": "5000000", "size_cap_binding": "false", "disclosures": " | ".join(DISCLOSURES)}


def write_all(seed: int, out: Path, data_dir: Path) -> dict[str, Any]:
    w = build(seed)
    ents = w.ents
    version = f"{VERSION_TAG}-{seed}-{DATE_TAG}"
    dhash = dataset_hash(ents)
    out.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    nbytes = 0
    for name in ENTITIES:
        text = entity_text(name, version, ents[name])
        nbytes += len(text.encode())
        (out / f"{name}.json").write_text(text)
    inj_doc = {"dataset_version": version, "dataset_hash": dhash, "seed": seed, "contract_version": CONTRACT_VERSION, "injections": w.injections,
               "designed_relationships": w.designed, "events_file": "data/injection-events.json"}
    inj_text = json.dumps(inj_doc, indent=2, sort_keys=True) + "\n"
    (data_dir / "injection-manifest.json").write_text(inj_text)
    (out / "injection-manifest.json").write_text(inj_text)
    (data_dir / "injection-events.json").write_text(json.dumps({"dataset_version": version, "events": w.events}, indent=2, sort_keys=True) + "\n")
    stats = {"entity_file_bytes": nbytes, "issues": w.issue_stats, "weights": w.weight_stats, "matching": w.match_stats,
             "rule_runs": {"scheduled": w.scheduled, "reruns": w.issue_stats["reruns"], "total": len(w.runs)},
             "rules": {"by_type": {t: sum(1 for x in w.rules if x.rtype == t) for t in DIMS}, "disabled": len(w.disabled_rules),
                       "version_2_or_more": len(w.v2_rules), "version_3": 1},
             "datasets": {"monitored": sum(1 for d in w.ds_list if d["monitored"]), "with_rows": len(w.rows), "rows": sum(len(v) for v in w.rows.values()),
                          "by_tier": {t: sum(1 for v in w.tier.values() if v == t) for t in ("good", "fair", "poor")}},
             "lineage": {"declared": 80, "observed": 70, "undeclared_observed": 12, "inferred": 10, "inferred_on_declared_unobserved": 4},
             "customer_systems": {s: sum(1 for c in w.customer_records if c["source_system"] == s) for s in ("crm", "billing", "support")},
             "definitions_incomplete": w.incomplete_metrics,
             "timeliness_on_time": sum(1 for v in w.timeliness_final.values() if v), "timeliness_monitored": len(w.timeliness_final)}
    manifest = {
        "dataset_version": version, "dataset_hash": dhash, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contract_version": CONTRACT_VERSION, "window_start": "2026-07-13T00:00:00Z", "window_end": "2026-10-04T23:59:59Z", "as_of": CONFIG["as_of"],
        "config": {k: CONFIG[k] for k in ("contract_version", "as_of", "whitespace_policy", "weight_version", "checklist_version", "checklist_versions", "probes")},
        "generator": {"name": "generate.py", "seed": seed, "parameters": parameters(w)},
        "row_counts": {name: len(ents[name]) for name in ENTITIES}, "designed_relationships": w.designed,
        "injection_manifest": "injection-manifest.json", "stats": stats,
        "synthetic_truth": {"note": "Synthetic match truth for the verification layer only: it is never loaded by the matcher, the seeder or the API.",
                            "entities": w.match_stats["entities"], "precision": {k: w.match_stats[k] for k in ("approved", "approved_correct", "precision", "reviewed", "reviewed_correct_share")},
                            "true_entity": dict(sorted(w.truth.items()))}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_golden(out)
    return manifest


def shape_check(seed: int) -> int:
    golden = json.loads((APP_ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
    ents = build(seed).ents
    bad = 0
    for name in DOMAIN12:
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
    ap.add_argument("--data-dir", type=Path, default=APP_ROOT / "data")
    ap.add_argument("--profile", choices=("default", "golden-shape-check"), default="default")
    ap.add_argument("--inputs", type=Path, help="also write one inputs object for data/seed.py to this path (not committed)")
    args = ap.parse_args(argv)
    if args.profile == "golden-shape-check":
        return shape_check(args.seed)
    t0 = time.perf_counter()
    m = write_all(args.seed, args.out, args.data_dir)
    if args.inputs:
        w = build(args.seed)
        args.inputs.write_text(json.dumps(to_inputs(w.ents), sort_keys=True))
    total = sum(p.stat().st_size for p in args.out.rglob("*.json"))
    print(json.dumps({"dataset_version": m["dataset_version"], "dataset_hash": m["dataset_hash"], "row_counts": m["row_counts"], "bytes": total,
                      "elapsed_seconds": round(time.perf_counter() - t0, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
