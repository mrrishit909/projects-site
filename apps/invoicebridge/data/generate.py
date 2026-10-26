#!/usr/bin/env python3
"""InvoiceBridge synthetic data generator (P05-WORK-03, docs/data-generator.md).

Stdlib only. Deterministic: ``random.Random(seed)`` derives one child stream per purpose (vendors, catalog, purchase
orders, shipment plans, receipts, invoices, duplicates, injections, decisions, exceptions, exports, credits, events), all
quantities, prices, rates and money are integers until they are written as decimal strings (no float is ever written),
dates are plain ``date`` / ``datetime`` arithmetic, and nothing iterates a set of strings, so the same seed gives
byte-identical entity files and the same ``dataset_hash`` (checked under PYTHONHASHSEED 0, 1 and 2). Nothing is imported
from ``domain/``: the three-way match, the duplicate identity, the amounts and the approval policy are restated here from
docs/contracts.md (D-01..D-06); ``tests/test_generator.py`` runs the domain over the output and compares.

    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --profile golden-shape-check

Writes ``<entity>.json`` (``{"entity", "dataset_version", "rows"}``) and ``manifest.json`` to ``--out`` (plus ``golden/``,
the hand-derived fixture in the same shape); ``injection-manifest.json`` and ``injection-events.json`` to ``--data-dir``
(default ``data/``) and a copy of the injection manifest to ``--out``.

The world: 40 vendors in three currencies, 1,200 purchase orders with 3,000 lines ordered 2025-10-01 .. 2026-08-31, each
PO delivered in one to four shipments (a receipt per line and shipment, 2 % of them reversed), one invoice per shipment,
re-sent PDFs, the invoices matched by a nightly run at 02:00Z (cumulative three-way match), reviewed by reviewers under two
approval-policy versions, exported in weekly batches and credited on 4 % of them. Defects are injected into it (INJ-01..12).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
CONTRACT_VERSION = "v1"

WIN_START = datetime(2025, 10, 1, tzinfo=UTC)
WIN_END = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)       # the last instant any fact may carry
FIRST_NIGHT = datetime(2025, 10, 2, 2, 0, 0, tzinfo=UTC)      # the nightly match run, 02:00Z
N_NIGHTS = 365
AS_OF = FIRST_NIGHT + timedelta(days=N_NIGHTS - 1)            # 2026-10-01T02:00:00Z: the final run, the dataset's as_of
LAST_PO_DAY = 335                                              # POs are ordered 2025-10-01 + 0..335 = up to 2026-08-31
V2_FROM = datetime(2026, 4, 1, tzinfo=UTC)                     # the approval limit changes
PRICE_VENDOR = 7                                               # its price list changes from 2026-03-01
PRICE_CHANGE = date(2026, 3, 1)
PO_CATALOGUE_UPDATED = datetime(2026, 4, 15, tzinfo=UTC)       # POs ordered from here carry the new prices
GROUP_02X = tuple(range(20, 30))                               # vendors ven-020 .. ven-029 invoice before they deliver

# ---- volumes (docs/data-generator.md) -----------------------------------------------------------------------------
N_VENDORS, N_POS, N_PO_LINES, N_INVOICES = 40, 1200, 3000, 2800
N_DUPLICATES = 95                  # re-sent PDFs of an invoice already imported (merged, DUPLICATE_IDENTITY)
CREDIT_SHARE_PERMILLE = 40         # credit notes on 4 % of the invoices
REVERSAL_PERMILLE = 20.2           # reversed receipts, per mille of the first-entry receipts (about 2 % of all rows)
P_SHORT_02X = 0.40                 # a ven-02x line whose last shipment is not (fully) received by the end
P_DUP_MONTH_END = 0.74             # a re-sent PDF lands in the last three days of a month
LIMIT_V1, LIMIT_V2 = 500000, 800000  # cents: reviewer approval limit under pol-v1 and pol-v2
TOLERANCES = {"price_per_unit": "0.00", "rounding_per_line": "0.01", "rounding_per_invoice": "0.02"}
TOL_INV_CENTS = 2

DOMAIN_ENTITIES = ("vendors", "purchase_orders", "po_lines", "receipts", "invoices", "invoice_lines", "credit_notes",
                   "approval_policies", "approvals", "export_requests")
EXTRA_ENTITIES = ("exceptions", "exception_assignments", "export_batches")
ENTITIES = tuple(sorted(DOMAIN_ENTITIES + EXTRA_ENTITIES))
#: Columns of the entities the golden fixture leaves empty (tables of 0001_schema.sql; data/seed.py has no COLUMNS table).
EXTRA_COLUMNS = {
    "exceptions": ("exception_id", "invoice_id", "exception_type", "status", "owner_id", "created_at", "resolved_at"),
    "exception_assignments": ("assignment_id", "exception_id", "owner_id", "assigned_by", "assigned_at", "note"),
    "export_batches": ("batch_id", "idempotency_key", "requested_by", "exported_at", "row_count", "total"),
    "credit_notes": ("credit_id", "invoice_id", "credit_amount", "credited_at"),
}
EXTRA_ROW_FIELDS = {"approvals": ("reason",)}      # the fixture rows carry no reason: a rejection needs one (D-04)

PURPOSES = ("vendors", "catalog", "pos", "plans", "receipts", "invoices", "pricing", "duplicates", "injections",
            "decisions", "exceptions", "exports", "credits", "events")

ADJ = ("Northwind Harbor Summit Granite Cobalt Meridian Alder Keystone Lakeshore Ironwood Redwood Bluebird Falcon "
       "Orchard Pinnacle Silverline Beacon Crestview Evergreen Tidewater Brightwater Copperfield Highland Juniper "
       "Oakridge Prairie Quarry Riverbend Stonegate Westfield Zenith Atlas Birch Cedar Delta Ember Fjord Glacier "
       "Horizon Ivory").split()
NOUNS = ("Supply Industrial Packaging Fasteners Electronics Logistics Components Chemicals Textiles Tooling Plastics "
         "Metals Paper Foods Lubricants Cables Safety Hardware Labels Pumps").split()
SUFFIX = {"USD": ("Co", "Inc", "LLC"), "EUR": ("GmbH", "SARL", "BV", "SpA"), "GBP": ("Ltd", "PLC")}
WORDS = ("WIDGET BRACKET GASKET BOLT CABLE FILTER SENSOR VALVE HINGE PANEL RELAY SEAL TUBE CLAMP FUSE BEARING "
         "LABEL PALLET DRUM GLOVE MOTOR SPRING WASHER NOZZLE").split()
CLERKS = tuple(f"usr-clerk{i:02d}" for i in range(1, 7))
REVIEWERS = tuple(f"usr-rev{i:02d}" for i in range(1, 6))
ANALYSTS = tuple(f"usr-ap{i:02d}" for i in range(1, 7))
SUPERVISOR = "usr-sup01"
ADMIN = "usr-adm01"
TAX_RATES = {"USD": (0, 60000, 72500, 82500, 100000), "EUR": (190000, 200000, 210000, 70000), "GBP": (200000,)}
REJECT_REASONS = {
    "PRICE_VARIANCE": "Unit price differs from the purchase order; vendor to credit and re-bill at the PO price.",
    "QUANTITY_BLOCKED": "Billed ahead of receipt; vendor to re-send once the delivery is booked.",
    "ROUNDING_EXCEPTION": "Declared total does not agree with the line extension; vendor to re-issue.",
    "CURRENCY_MISMATCH": "Invoiced in a currency other than the purchase order and no dated rate exists.",
}


# ---------------------------------------------------------------------------------------------------------------------
# small exact helpers: quantity units 1e-4, price units 1e-6, money cents, rates 1e-6; integers all the way
# ---------------------------------------------------------------------------------------------------------------------

def rhu(n: int, d: int) -> int:
    """Round half up (n >= 0)."""
    return (2 * n + d) // (2 * d)


def fq(u: int) -> str:
    return f"{u // 10000}.{u % 10000:04d}"


def fp(u: int) -> str:
    return f"{u // 1000000}.{u % 1000000:06d}"


def fm(c: int) -> str:
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}{c // 100}.{c % 100:02d}"


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def at_day(d: date, sec: int) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(seconds=sec)


def next_biz(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def last_dom(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def norm_number(s: str) -> str:
    return "".join(c for c in s.upper() if "A" <= c <= "Z" or "0" <= c <= "9")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def night_time(n: int) -> datetime:
    return FIRST_NIGHT + timedelta(days=n)


def night_idx(dt: datetime) -> int:
    """The first nightly run at or after ``dt``."""
    delta = dt - FIRST_NIGHT
    if delta <= timedelta(0):
        return 0
    n = delta.days + (1 if (delta.seconds or delta.microseconds) else 0)
    return min(n, N_NIGHTS - 1)


def amounts(lines: list[Any], rate_u: int, freight_c: int, disc_c: int) -> tuple[int, int, int]:
    """(subtotal, tax, total) in cents: tax once on the unrounded subtotal, ROUND_HALF_UP (D-02, D-05)."""
    raw = sum(l.units * l.price_u for l in lines)                 # 1e-10
    sub = rhu(raw, 10 ** 8)
    tax = rhu(raw * rate_u, 10 ** 14)
    return sub, tax, sub + tax + freight_c - disc_c


def biz_dt(r: random.Random, d: date, lo: int = 7, hi: int = 17) -> datetime:
    return at_day(next_biz(d), r.randint(lo * 3600, hi * 3600 - 1))


def norm_biz(dt: datetime) -> datetime:
    """A working-hours instant at or after ``dt`` (minutes and seconds kept)."""
    d = dt.date()
    if d.weekday() >= 5:
        d = next_biz(d)
        return at_day(d, 8 * 3600 + dt.minute * 60 + dt.second)
    if dt.hour < 7:
        return at_day(d, 7 * 3600 + dt.minute * 60 + dt.second)
    if dt.hour >= 18:
        return at_day(next_biz(d + timedelta(days=1)), 8 * 3600 + dt.minute * 60 + dt.second)
    return dt


class GenError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------------------------------
# the world
# ---------------------------------------------------------------------------------------------------------------------

class World:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        master = random.Random(seed)
        self.r = {p: random.Random(master.getrandbits(64)) for p in PURPOSES}
        self.inj: dict[str, Any] = {}
        self.stats: dict[str, Any] = {}

    # ---- vendors and catalogue --------------------------------------------------------------------------------------
    def build_vendors(self) -> None:
        r, rc = self.r["vendors"], self.r["catalog"]
        pool = [i for i in range(2, 40) if i != PRICE_VENDOR]
        eur = set(r.sample(pool, 10))
        gbp = set(r.sample([i for i in pool if i not in eur], 5))
        rounders = set(r.sample([i for i in pool if i not in GROUP_02X], 6))   # vendors that round tax per line
        self.vendors = []
        for i in range(1, N_VENDORS + 1):
            cur = "EUR" if i in eur else "GBP" if i in gbp else "USD"
            if i == 1:
                noun, suffix = "Supply", "Co"
            else:
                noun, suffix = r.choice(NOUNS), r.choice(SUFFIX[cur])
            v = NS(idx=i, id=f"ven-{i:03d}", name=f"{ADJ[i - 1]} {noun} {suffix}", currency=cur,
                   tax_ref=f"{'US-TAX' if cur == 'USD' else 'EU-VAT' if cur == 'EUR' else 'GB-VAT'}-{i:04d}",
                   rate_u=100000 if i == 1 else 82500 if i == PRICE_VENDOR else r.choice(TAX_RATES[cur]),
                   prefix=ADJ[i - 1][:3].upper(), lead=r.choice((4, 6, 8, 10, 14)), g02x=i in GROUP_02X,
                   price_vendor=i == PRICE_VENDOR, rounder=i in rounders, active=i != N_VENDORS, counter=0, products=[])
            v.counter = r.randint(1000, 9000)
            for j in range(10):
                dp = rc.choices((2, 3, 4, 5, 6), (70, 12, 12, 3, 3))[0]
                price = math.exp(rc.gauss(math.log(25), 1.35))
                price = min(max(price, 0.35), 900.0)
                if v.price_vendor:
                    dp, price = 2, max(price, 1.5)
                p_u = max(1, round(price * 10 ** dp)) * 10 ** (6 - dp)
                frac = rc.random() < 0.18
                v.products.append(NS(code=f"{WORDS[(i * 3 + j) % len(WORDS)]}-{chr(65 + j)}", price_u=p_u,
                                     step=2500 if frac else 10000))
            self.vendors.append(v)
        if len({v.prefix for v in self.vendors}) != N_VENDORS:
            raise GenError("vendor prefixes are not unique")
        self.vendor_by_id = {v.id: v for v in self.vendors}

    # ---- purchase orders --------------------------------------------------------------------------------------------
    def build_pos(self) -> None:
        r = self.r["pos"]
        weights = [r.lognormvariate(0, 0.45) for _ in self.vendors]
        for v, w in zip(self.vendors, weights):
            weights[v.idx - 1] = 0.0 if not v.active else w * (3.2 if v.price_vendor else 1.15 if v.g02x else 1.0)
        counts = r.choices((1, 2, 3, 4, 5), (25, 30, 25, 12, 8), k=N_POS)
        while sum(counts) != N_PO_LINES:
            i = r.randrange(N_POS)
            if sum(counts) < N_PO_LINES and counts[i] < 5:
                counts[i] += 1
            elif sum(counts) > N_PO_LINES and counts[i] > 1:
                counts[i] -= 1
        pos = []
        for n in range(N_POS):
            v = r.choices(self.vendors, weights)[0]
            d = next_biz(date(2025, 10, 1) + timedelta(days=r.randint(0, LAST_PO_DAY)))
            po = NS(seq=n, vendor=v, ordered_at=at_day(d, r.randint(8 * 3600, 16 * 3600)), currency=v.currency,
                    lines=[], lead=max(2, round(v.lead * r.uniform(0.6, 1.6))), ships=[], id="")
            for p in r.sample(v.products, counts[n]):
                value = math.exp(r.gauss(math.log(520), 1.0))
                q = max(1, round(value / (p.price_u / 1e6) * (10000 / p.step))) if p.step == 2500 else \
                    max(1, round(value / (p.price_u / 1e6)))
                units = min(q * p.step, 3000 * 10000)
                po.lines.append(NS(po=po, product=p.code, price_u=p.price_u, step=p.step, units=units, id=""))
            pos.append(po)
        pos.sort(key=lambda p: (p.ordered_at, p.seq))
        self.pos = pos
        k = 0
        for i, po in enumerate(pos, 1):
            po.id = f"po-{i:04d}"
            for l in po.lines:
                k += 1
                l.id = f"pol-{k:04d}"
        self.po_by_id = {p.id: p for p in pos}
        self.line_by_id = {l.id: l for p in pos for l in p.lines}

    # ---- shipments: how each PO is delivered (and invoiced) ---------------------------------------------------------
    def plan(self, po: NS) -> None:
        r = self.r["plans"]
        v = po.vendor
        s = []
        for l in po.lines:
            steps = l.units // l.step
            s.append(max(1, min(r.choices((1, 2, 3), (45, 35, 20))[0], steps)))
        k = max(s)
        imax = s.index(k)
        ships = [NS(lines={}, short={}, gap=r.randint(3, 21), lag=0, back=0, t_r=r.randint(7 * 3600, 16 * 3600),
                    t_i=r.randint(6 * 3600, 18 * 3600), eom=None, off={}) for _ in range(k)]
        for li, l in enumerate(po.lines):
            sl = s[li]
            slots = list(range(k)) if li == imax else sorted(r.sample(range(k), sl))
            total = l.units // l.step
            cuts = sorted(r.sample(range(1, total), sl - 1)) if sl > 1 else []
            parts = [b - a for a, b in zip([0] + cuts, cuts + [total])]
            for slot, part in zip(slots, parts):
                ships[slot].lines[li] = part * l.step
            if v.g02x and r.random() < P_SHORT_02X:
                ships[slots[-1]].short[li] = ("omit",) if r.random() < 0.55 else ("pct", r.randint(35, 75))
        for sh in ships:
            self.fresh_timing(sh, v)
        po.ships = ships

    def fresh_timing(self, sh: NS, v: NS) -> None:
        r = self.r["plans"]
        if v.g02x:
            sh.lag = r.randint(3, 25)                                  # the invoice precedes the delivery by this many days
            sh.back = r.choice((0, 0, 1, 2))
        else:
            u = r.random()
            sh.lag = r.randint(1, 3) if u < 0.40 else r.randint(4, 8) if u < 0.80 else r.randint(9, 14)
            sh.back = r.choice((0, 1, 1, 2, 3))
            sh.eom = r.randint(0, 2) if r.random() < 0.10 else None
        sh.t_r = r.randint(7 * 3600, 16 * 3600)
        sh.t_i = r.randint(6 * 3600, 18 * 3600)
        sh.gap = r.randint(2, 9) if sh.gap is None else sh.gap

    def schedule(self, po: NS) -> list[NS]:
        out = []
        prev_inv = prev_date = None
        day = None
        for j, sh in enumerate(po.ships):
            day = po.ordered_at.date() + timedelta(days=po.lead) if j == 0 else day + timedelta(days=sh.gap)
            rd = next_biz(day)
            rcpt = at_day(rd, sh.t_r)
            if po.vendor.g02x:
                d = next_biz(max((rcpt - timedelta(days=sh.lag)).date(), po.ordered_at.date() + timedelta(days=1)))
            else:
                d = next_biz(rd + timedelta(days=sh.lag))
                if sh.eom is not None:
                    tgt = last_dom(d) - timedelta(days=sh.eom)
                    if tgt > d:
                        d = next_biz(tgt)
            inv_dt = at_day(d, sh.t_i)
            if prev_inv is not None:
                inv_dt = max(inv_dt, prev_inv + timedelta(minutes=20))
            inv_date = max(inv_dt.date() - timedelta(days=sh.back), po.ordered_at.date(), prev_date or date(2000, 1, 1))
            prev_inv, prev_date = inv_dt, inv_date
            out.append(NS(rcpt=rcpt, inv_dt=inv_dt, inv_date=inv_date))
        return out

    def invoice_count(self, po: NS) -> int:
        return sum(1 for s in self.schedule(po) if s.inv_dt <= WIN_END)

    def calibrate(self, target: int) -> None:
        r = self.r["plans"]
        for po in self.pos:
            self.plan(po)
        counts = [self.invoice_count(po) for po in self.pos]
        total = sum(counts)
        self.stats["plan_invoices_before_calibration"] = total
        guard = 0
        while total != target:
            guard += 1
            if guard > 50000:
                raise GenError("calibration did not converge")
            i = r.randrange(len(self.pos))
            po = self.pos[i]
            if total > target:
                if len(po.ships) < 2 or self.schedule(po)[-1].inv_dt > WIN_END:
                    continue
                last, prev = po.ships[-1], po.ships[-2]
                for li, u in last.lines.items():
                    prev.lines[li] = prev.lines.get(li, 0) + u
                    prev.short.pop(li, None)
                    if li in last.short:
                        prev.short[li] = last.short[li]
                po.ships.pop()
            else:
                cand = [j for j, sh in enumerate(po.ships) if self.schedule(po)[j].inv_dt <= WIN_END
                        and (len(sh.lines) >= 2 or any(u // po.lines[li].step >= 2 for li, u in sh.lines.items()))]
                if not cand or len(po.ships) >= 5:
                    continue
                j = r.choice(cand)
                sh = po.ships[j]
                new = NS(lines={}, short={}, gap=r.randint(2, 9), lag=0, back=0, t_r=0, t_i=0, eom=None, off={})
                self.fresh_timing(new, po.vendor)
                if len(sh.lines) >= 2:
                    li = sorted(sh.lines)[r.randrange(len(sh.lines))]
                    new.lines[li] = sh.lines.pop(li)
                else:
                    li = next(iter(sh.lines))
                    steps = sh.lines[li] // po.lines[li].step
                    moved = r.randint(1, steps - 1)
                    new.lines[li] = moved * po.lines[li].step
                    sh.lines[li] -= new.lines[li]
                if li in sh.short:
                    new.short[li] = sh.short.pop(li)
                po.ships.insert(j + 1, new)
                # a later shipment now exists for this line: a short mark belongs to its last shipment only (moved above)
            new_count = self.invoice_count(po)
            total += new_count - counts[i]
            counts[i] = new_count
        self.stats["plan_calibration_steps"] = guard

    # ---- receipts ----------------------------------------------------------------------------------------------------
    def build_receipts(self) -> None:
        r = self.r["receipts"]
        rows = []
        for po in self.pos:
            sched = self.schedule(po)
            for j, sh in enumerate(po.ships):
                for li in sorted(sh.lines):
                    units = sh.lines[li]
                    step = po.lines[li].step
                    mode = sh.short.get(li)
                    if mode is not None:
                        if mode[0] == "omit":
                            continue
                        units = (units * mode[1] // 100) // step * step
                        if units <= 0 or units >= sh.lines[li]:
                            continue
                    dt = sched[j].rcpt + timedelta(minutes=7 * li + r.randint(0, 6))
                    if dt <= WIN_END:
                        rows.append(NS(line=po.lines[li], dt=dt, units=units, reversed=False, seq=len(rows), reentry=False,
                                       ship=(po.id, j, li), injected=False))
        n_rev = round(len(rows) * REVERSAL_PERMILLE / 1000)
        base = list(rows)
        for rc in r.sample(base, n_rev):
            rc.reversed = True
            if r.random() < 0.70:
                dt = norm_biz(rc.dt + timedelta(days=1, hours=r.randint(0, 3)))
                if dt <= WIN_END:
                    rows.append(NS(line=rc.line, dt=dt, units=rc.units, reversed=False, seq=len(rows), reentry=True,
                                   ship=rc.ship, injected=False))
        self.receipts = rows
        self.stats["reversed_receipts"] = n_rev
        self.stats["reentered_receipts"] = sum(1 for x in rows if x.reentry)

    # ---- invoices ------------------------------------------------------------------------------------------------
    def make_invoice(self, vendor: NS, po: NS, lines: list[NS], inv_dt: datetime, inv_date: date, kind: str) -> NS:
        r = self.r["invoices"]
        creator = r.choice(CLERKS) if r.random() > 0.04 else r.choice(REVIEWERS)
        freight = r.choice((1250, 1800, 2500, 4500, 6500, 8500)) if r.random() < 0.22 else 0
        inv = NS(seq=self.seq, vendor=vendor, po=po, lines=lines, imported_at=inv_dt, date=inv_date, currency=vendor.currency,
                 rate_u=vendor.rate_u, freight_c=freight, disc_c=0, created_by=creator, kind=kind, number="", sha="",
                 filename="", id="", declared_c=0, ship=None, dup_of=None, tags=[])
        self.seq += 1
        sub, tax, total = amounts(lines, vendor.rate_u, freight, 0)
        if r.random() < 0.10:
            inv.disc_c = rhu(sub * r.choice((1, 2)), 100)
            sub, tax, total = amounts(lines, vendor.rate_u, freight, inv.disc_c)
        inv.sub_c, inv.tax_c, inv.total_c = sub, tax, total
        inv.declared_c = total
        if vendor.rounder and len(lines) >= 2:                       # vendor that rounds tax per line: a tolerated gap
            line_tax = sum(rhu(l.units * l.price_u * vendor.rate_u, 10 ** 14) for l in lines)
            diff = max(-TOL_INV_CENTS, min(TOL_INV_CENTS, line_tax - tax))
            inv.declared_c = total + diff
        return inv

    def build_invoices(self) -> None:
        r = self.r["pricing"]
        self.seq = 0
        invs = []
        for po in self.pos:
            sched = self.schedule(po)
            v = po.vendor
            for j, sh in enumerate(po.ships):
                if sched[j].inv_dt > WIN_END:
                    continue
                lines = []
                for li in sorted(sh.lines):
                    pl = po.lines[li]
                    price = pl.price_u
                    if v.price_vendor and sched[j].inv_date >= PRICE_CHANGE and po.ordered_at < PO_CATALOGUE_UPDATED:
                        price = max(rhu(price * 1075, 1000 * 10 ** 4) * 10 ** 4, price + 10 ** 4)
                    lines.append(NS(po_line=pl, units=sh.lines[li], price_u=price, id=""))
                inv = self.make_invoice(v, po, lines, sched[j].inv_dt, sched[j].inv_date, "base")
                inv.ship = (po.id, j)
                invs.append(inv)
        self.invoices = invs
        self.number_invoices(invs)
        self.stats["base_invoices"] = len(invs)

    def number_invoices(self, invs: list[NS]) -> None:
        r = self.r["invoices"]
        for inv in sorted(invs, key=lambda i: (i.imported_at, i.seq)):
            self.new_number(inv)

    def new_number(self, inv: NS, suffix: str = "") -> None:
        r = self.r["invoices"]
        v = inv.vendor
        v.counter += r.randint(1, 6)
        inv.number = f"{v.prefix}-{v.counter}{suffix}"
        inv.filename = f"{inv.number}.pdf"
        inv.sha = sha(f"{self.seed}|src|{v.id}|{inv.number}|{inv.date}|{inv.total_c}|{inv.seq}")

    # ---- the book: duplicates, the nightly match run ------------------------------------------------------------------
    @staticmethod
    def identity(inv: NS) -> str:
        return f"{inv.vendor.id}|{norm_number(inv.number)}|{inv.date.isoformat()}|{fm(inv.total_c)}"

    def merges(self, invs: list[NS]) -> dict[int, tuple[int, str]]:
        """seq -> (canonical seq, reason): same bytes first, then identity; the earliest import is canonical."""
        by_sha: dict[str, int] = {}
        by_key: dict[str, int] = {}
        out: dict[int, tuple[int, str]] = {}
        for inv in sorted(invs, key=lambda i: (i.imported_at, i.id)):
            key = self.identity(inv)
            canon, reason = by_sha.get(inv.sha), "DUPLICATE_SOURCE_BYTES"
            if canon is None:
                canon, reason = by_key.get(key), "DUPLICATE_IDENTITY"
            if canon is None:
                canon = inv.seq
            else:
                out[inv.seq] = (canon, reason)
            by_key.setdefault(key, canon)
            by_sha.setdefault(inv.sha, canon)
        return out

    def assign_ids(self, invs: list[NS]) -> None:
        for i, inv in enumerate(sorted(invs, key=lambda i: (i.imported_at, i.seq)), 1):
            inv.id = f"inv-{i:04d}"
        k = 0
        for inv in sorted(invs, key=lambda i: i.id):
            for l in inv.lines:
                k += 1
                l.id = f"il-{k:05d}"

    @staticmethod
    def book_key(inv: NS) -> tuple:
        return (inv.date, inv.imported_at, inv.id)

    def eval_po(self, po: NS, invs: list[NS], t: datetime, rcpts: list[NS]) -> dict[int, tuple[bool, tuple[str, ...]]]:
        net: dict[str, int] = {}
        for rc in rcpts:
            if rc.dt > t:
                break
            net[rc.line.id] = net.get(rc.line.id, 0) + rc.units
        consumed: dict[str, int] = {}
        out = {}
        for inv in invs:
            if inv.imported_at > t:
                continue
            reasons = set()
            local: dict[str, int] = {}
            for l in inv.lines:
                pl = l.po_line
                if inv.currency != po.currency:
                    reasons.add("CURRENCY_MISMATCH")
                    continue
                avail = net.get(pl.id, 0) - consumed.get(pl.id, 0) - local.get(pl.id, 0)
                if l.units > avail:
                    reasons.add("QUANTITY_BLOCKED")
                elif l.price_u != pl.price_u:
                    reasons.add("PRICE_VARIANCE")
                local[pl.id] = local.get(pl.id, 0) + l.units
            if abs(inv.declared_c - inv.total_c) > TOL_INV_CENTS:
                reasons.add("ROUNDING_EXCEPTION")
            if not reasons:
                for k, u in local.items():
                    consumed[k] = consumed.get(k, 0) + u
            out[inv.seq] = (not reasons, tuple(sorted(reasons)))
        self._last_eval = (net, consumed)
        return out

    def history(self, invs: list[NS]) -> NS:
        """Run the nightly match from scratch for every PO at each night something changed. Returns the merge map and, per
        invoice, the list of (night, matched, reasons) at each change."""
        merged = self.merges(invs)
        by_po: dict[str, list[NS]] = {}
        for inv in invs:
            if inv.seq not in merged:
                by_po.setdefault(inv.po.id, []).append(inv)
        rc_by_po: dict[str, list[NS]] = {}
        for rc in sorted(self.receipts, key=lambda x: (x.dt, x.seq)):
            if not rc.reversed:
                rc_by_po.setdefault(rc.line.po.id, []).append(rc)
        hist: dict[int, list[tuple[int, bool, tuple[str, ...]]]] = {}
        spare: dict[str, int] = {}
        for po in self.pos:
            ivs = sorted(by_po.get(po.id, []), key=self.book_key)
            rcs = rc_by_po.get(po.id, [])
            nights = sorted({night_idx(i.imported_at) for i in ivs} | {night_idx(x.dt) for x in rcs})
            if not ivs:
                for l in po.lines:
                    spare[l.id] = sum(x.units for x in rcs if x.line is l)
                continue
            for n in nights:
                res = self.eval_po(po, ivs, night_time(n), rcs)
                for seq, (ok, reasons) in res.items():
                    h = hist.setdefault(seq, [])
                    if not h or (h[-1][1], h[-1][2]) != (ok, reasons):
                        h.append((n, ok, reasons))
            net, consumed = self._last_eval
            for l in po.lines:
                spare[l.id] = net.get(l.id, 0) - consumed.get(l.id, 0)
        return NS(merged=merged, hist=hist, spare=spare)

    @staticmethod
    def final_state(h: NS, inv: NS) -> tuple[bool, tuple[str, ...]] | None:
        rec = h.hist.get(inv.seq)
        return None if not rec else (rec[-1][1], rec[-1][2])

    @staticmethod
    def matched_from(h: NS, inv: NS) -> int | None:
        """The night from which the invoice has been matched without interruption to the final run (None: not matched)."""
        rec = h.hist.get(inv.seq)
        if not rec or not rec[-1][1]:
            return None
        return rec[-1][0]

    # ---- re-sent PDFs, injected defects -------------------------------------------------------------------------------
    def inject(self) -> None:
        r = self.r["duplicates"]
        ri = self.r["injections"]
        base = self.invoices
        self.assign_ids(base)
        h0 = self.history(base)
        self.stats["h0_flagged"] = sum(1 for i in base if i.seq not in h0.merged and h0.hist[i.seq][-1][1] is False)

        taken: set[int] = set()
        by_seq = {i.seq: i for i in base}

        def stable(i: NS) -> bool:
            return i.seq not in h0.merged and self.matched_from(h0, i) is not None

        normal = [i for i in base if not i.vendor.g02x and not i.vendor.price_vendor and i.vendor.currency == "USD"
                  and stable(i) and date(2025, 11, 1) <= i.imported_at.date() <= date(2026, 8, 31)]
        normal_any = [i for i in base if not i.vendor.g02x and not i.vendor.price_vendor
                      and stable(i) and date(2025, 11, 1) <= i.imported_at.date() <= date(2026, 8, 31)]

        def pick(pool: list[NS], k: int, pred=lambda i: True) -> list[NS]:
            cand = [i for i in pool if i.seq not in taken and pred(i)]
            chosen = ri.sample(cand, k)
            for c in chosen:
                taken.add(c.seq)
            return chosen

        receipts_by_line: dict[str, list[NS]] = {}
        for rc in self.receipts:
            receipts_by_line.setdefault(rc.line.id, []).append(rc)
        ships_of_line: dict[str, int] = {}
        for po in self.pos:
            for sh in po.ships:
                for li in sh.lines:
                    ships_of_line[po.lines[li].id] = ships_of_line.get(po.lines[li].id, 0) + 1

        def clean_receipts(i: NS) -> bool:
            return all(not rc.reversed and not rc.reentry for l in i.lines for rc in receipts_by_line.get(l.po_line.id, []))

        # INJ-04 cumulative consumption: a second invoice on a line the first invoice consumed in full
        firsts = pick(normal, 3, lambda i: len(i.lines) == 1 and ships_of_line.get(i.lines[0].po_line.id) == 1
                      and i.lines[0].units // i.lines[0].po_line.step >= 2 and clean_receipts(i))
        extras4 = []
        for a in firsts:
            l = a.lines[0]
            steps = l.units // l.po_line.step
            b_units = max(1, round(steps * ri.uniform(0.4, 0.7))) * l.po_line.step
            dt = norm_biz(a.imported_at + timedelta(days=ri.randint(3, 12), hours=ri.randint(0, 6)))
            d = max(dt.date() - timedelta(days=ri.choice((0, 1, 2))), a.date)
            inv = self.make_invoice(a.vendor, a.po, [NS(po_line=l.po_line, units=b_units, price_u=l.po_line.price_u, id="")],
                                    dt, d, "cumulative")
            inv.ship = None
            self.new_number(inv)
            extras4.append((a, inv))
        # INJ-03 partial receipt short of the invoiced quantity (the last shipment of its lines, nothing after)
        shorts = pick(normal_any, 5, lambda i: all(ships_of_line.get(l.po_line.id) == 1 or self.is_last_ship(i, l)
                                                    for l in i.lines) and i.imported_at.date() <= date(2026, 8, 20)
                      and clean_receipts(i) and i.po.vendor.currency in ("USD", "EUR")
                      and any(l.units // l.po_line.step >= 3 for l in i.lines))
        short_detail = []
        for i in shorts:
            wide = [x for x in i.lines if x.units // x.po_line.step >= 3]
            l = wide[ri.randrange(len(wide))]
            rc = next(x for x in receipts_by_line[l.po_line.id] if x.ship[0] == i.ship[0] and x.ship[1] == i.ship[1])
            step = l.po_line.step
            steps = rc.units // step
            new_units = max(1, min(steps - 1, int(steps * ri.uniform(0.60, 0.85)))) * step
            rc.injected = True
            short_detail.append({"invoice": i, "line": l, "received": new_units, "invoiced": l.units})
            rc.units = new_units
        # INJ-01 the same bytes under two filenames
        bytes_src = pick(normal_any, 3)
        copies = []
        for a in bytes_src:
            dt = norm_biz(a.imported_at + timedelta(days=ri.randint(1, 6), hours=ri.randint(0, 5)))
            inv = self.clone(a, dt, kind="same_bytes")
            inv.number = a.number if ri.random() < 0.5 else a.number.lower()
            inv.sha = a.sha
            inv.filename = ri.choice((f"scan_{a.number}.pdf", f"{a.number} (1).pdf", f"{a.number}_copy.pdf"))
            copies.append((a, inv))
        # INJ-05 rounding gap beyond the 0.02 tolerance
        gaps = pick(normal_any, 4)
        for i, d in zip(gaps, (3, -5, 10, 37)):
            i.declared_c = i.total_c + d
        # INJ-09 a foreign-currency invoice against a USD purchase order (no dated rate)
        fx = pick(normal, 3)
        fx_detail = []
        for i, cur in zip(fx, ("EUR", "GBP", "EUR")):
            fx_detail.append((i, i.currency, cur))
            i.currency = cur
        # INJ-02 one invoice number used by two vendors
        reuse = []
        a_list = pick(normal_any, 4)
        for k, a in enumerate(a_list):
            b = pick(normal_any, 1, lambda i, a=a: i.vendor.id != a.vendor.id and abs((i.imported_at - a.imported_at).days) <= 90)[0]
            b.number = a.number if k % 2 == 0 else a.number.lower()
            b.filename = f"{b.number}.pdf"
            b.sha = sha(f"{self.seed}|src|{b.vendor.id}|{b.number}|{b.date}|{b.total_c}|{b.seq}")
            reuse.append((a, b))
        # a few random price differences on ordinary vendors (baseline noise, not a listed defect)
        noise = pick(normal_any, 4)
        for i in noise:
            l = i.lines[0]
            l.price_u += 10 ** 4 * ri.choice((1, 2, 5))
            sub, tax, total = amounts(i.lines, i.rate_u, i.freight_c, i.disc_c)
            i.sub_c, i.tax_c, i.total_c, i.declared_c = sub, tax, total, total
            i.tags.append("price_noise")
        # organic duplicates: re-sent PDFs (different bytes, same obligation), clustered in the last three days of a month
        def month_end_window(d: date) -> tuple[datetime, datetime] | None:
            end = last_dom(d)
            start = end - timedelta(days=2)
            if d >= start:
                nd = end + timedelta(days=1)
                end = last_dom(nd)
                start = end - timedelta(days=2)
            if at_day(end, 80000) > WIN_END:
                return None
            return at_day(start, 5 * 3600), at_day(end, 20 * 3600)

        pool = [i for i in base if i.seq not in taken and i.imported_at.date() <= date(2026, 9, 26)]
        dups = []
        for orig in r.sample(pool, len(pool)):
            if len(dups) == N_DUPLICATES:
                break
            if r.random() < P_DUP_MONTH_END:
                w = month_end_window(orig.imported_at.date())
                if w is None:
                    continue
                dt = w[0] + timedelta(seconds=r.randint(0, int((w[1] - w[0]).total_seconds())))
            else:
                dt = orig.imported_at + timedelta(days=r.randint(2, 25), seconds=r.randint(0, 40000))
                if not (WIN_START <= dt <= WIN_END):
                    continue
                dt = norm_biz(dt)
            if dt <= orig.imported_at + timedelta(hours=20) or dt > WIN_END:
                continue
            taken.add(orig.seq)
            inv = self.clone(orig, dt, kind="resent")
            variants = (orig.number.lower(), orig.number.replace("-", " "), orig.number.replace("-", ""), orig.number)
            inv.number = r.choice(variants)
            inv.sha = sha(f"{self.seed}|resent|{orig.sha}|{inv.seq}")
            inv.filename = r.choice((f"{orig.number}_resent.pdf", f"{orig.number} (1).pdf", f"scan_{orig.number}.pdf"))
            dups.append((orig, inv))
        if len(dups) != N_DUPLICATES:
            raise GenError(f"only {len(dups)} duplicates could be placed")
        for i in [d["invoice"] for d in short_detail] + [b for _, b in extras4] + gaps + [x[0] for x in fx_detail]:
            i.tags.append("injected")                                       # these stay open exceptions (never rejected)
        allinv = base + [x[1] for x in extras4] + [x[1] for x in copies] + [x[1] for x in dups]
        self.invoices = allinv
        self.assign_ids(allinv)
        self.inj = NS(extras4=extras4, shorts=short_detail, copies=copies, gaps=gaps, fx=fx_detail, reuse=reuse,
                      noise=noise, dups=dups)

    def is_last_ship(self, inv: NS, l: NS) -> bool:
        po = inv.po
        j = inv.ship[1]
        li = po.lines.index(l.po_line)
        return all(li not in sh.lines for sh in po.ships[j + 1:])

    def clone(self, orig: NS, dt: datetime, kind: str) -> NS:
        r = self.r["duplicates"]
        lines = [NS(po_line=l.po_line, units=l.units, price_u=l.price_u, id="") for l in orig.lines]
        inv = NS(seq=self.seq, vendor=orig.vendor, po=orig.po, lines=lines, imported_at=dt, date=orig.date,
                 currency=orig.currency, rate_u=orig.rate_u, freight_c=orig.freight_c, disc_c=orig.disc_c,
                 created_by=orig.created_by if r.random() < 0.7 else r.choice(CLERKS), kind=kind, number=orig.number, sha="",
                 filename="", id="", declared_c=orig.declared_c, ship=None, dup_of=orig, tags=[],
                 sub_c=orig.sub_c, tax_c=orig.tax_c, total_c=orig.total_c)
        self.seq += 1
        return inv

    # ---- decisions: approvals, rejections ---------------------------------------------------------------------------
    def decide(self) -> None:
        r = self.r["decisions"]
        invs = self.invoices
        self.h = self.history(invs)
        h = self.h
        approvals: list[NS] = []
        rejected: dict[int, NS] = {}
        pending_over_limit = 0
        for inv in sorted(invs, key=lambda i: i.id):
            if inv.seq in h.merged:
                continue
            st = self.final_state(h, inv)
            n0 = self.matched_from(h, inv)
            inv.approved_at = None
            inv.rejected_at = None
            if n0 is not None:
                u = r.random()
                hours = r.uniform(3, 30) if u < 0.75 else r.uniform(30, 80) if u < 0.95 else r.uniform(80, 250)
                when = norm_biz(night_time(n0) + timedelta(hours=hours))
                skip = r.random() < 0.03                                  # never reviewed
                if skip or when > WIN_END:
                    continue
                limit = LIMIT_V1 if when < V2_FROM else LIMIT_V2
                if inv.total_c > limit:
                    pending_over_limit += 1
                    inv.over_limit = True
                    continue
                approver = r.choice([x for x in REVIEWERS if x != inv.created_by])
                inv.approved_at = when
                approvals.append(NS(inv=inv, actor=approver, role="reviewer", decision="approve", at=when, reason=None))
            elif st is not None and st[1] and "injected" not in inv.tags and all(not x[1] for x in h.hist[inv.seq]):
                kinds = st[1]
                p = max({"PRICE_VARIANCE": 0.35, "ROUNDING_EXCEPTION": 0.5, "CURRENCY_MISMATCH": 0.7,
                         "QUANTITY_BLOCKED": 0.12}[k] for k in kinds)
                if r.random() < p:
                    when = norm_biz(night_time(h.hist[inv.seq][0][0]) + timedelta(days=r.randint(1, 14), hours=r.randint(0, 8)))
                    if when <= WIN_END:
                        reason = REJECT_REASONS[kinds[0]]
                        actor = r.choice([x for x in REVIEWERS if x != inv.created_by])
                        inv.rejected_at = when
                        rejected[inv.seq] = inv
                        approvals.append(NS(inv=inv, actor=actor, role="reviewer", decision="reject", at=when, reason=reason))
        approvals.sort(key=lambda a: (a.at, a.inv.id))
        for i, a in enumerate(approvals, 1):
            a.id = f"ap-{i:04d}"
        self.approvals = approvals
        self.stats["approvals_over_limit_pending"] = pending_over_limit

    # ---- exceptions with assignment history ---------------------------------------------------------------------------
    def build_exceptions(self) -> None:
        r = self.r["exceptions"]
        recs = []
        for inv in sorted(self.invoices, key=lambda i: i.id):
            if inv.seq in self.h.merged:
                continue
            open_at: dict[str, datetime] = {}
            for n, ok, reasons in self.h.hist[inv.seq]:
                t = night_time(n)
                for typ in reasons:
                    if typ not in open_at:
                        open_at[typ] = t
                for typ in sorted(open_at):
                    if typ not in reasons:
                        recs.append(NS(inv=inv, typ=typ, created=open_at.pop(typ), resolved=t))
            for typ in sorted(open_at):
                recs.append(NS(inv=inv, typ=typ, created=open_at[typ],
                               resolved=inv.rejected_at if inv.rejected_at else None))
        recs.sort(key=lambda e: (e.created, e.inv.id, e.typ))
        asg = []
        for i, e in enumerate(recs, 1):
            e.id = f"exc-{i:03d}"
            e.assignments = []
            end = e.resolved or (AS_OF + timedelta(days=1))
            t = None
            if r.random() < 0.90:
                t = norm_biz(e.created + timedelta(hours=r.uniform(3, 30)))
                if t < end and t <= WIN_END:
                    owner = r.choice(ANALYSTS)
                    e.assignments.append(NS(owner=owner, by=SUPERVISOR if r.random() < 0.6 else owner, at=t,
                                            note="triage" if r.random() < 0.5 else None))
                    k = 1 if r.random() < 0.80 else 2 if r.random() < 0.8 else 3
                    for _ in range(k - 1):
                        t2 = norm_biz(e.assignments[-1].at + timedelta(hours=r.uniform(4, 90)))
                        if t2 < end and t2 <= WIN_END:
                            new_owner = r.choice([a for a in ANALYSTS if a != e.assignments[-1].owner])
                            e.assignments.append(NS(owner=new_owner, by=SUPERVISOR, at=t2, note="reassigned"))
            for a in e.assignments:
                asg.append(a)
                a.exc = e
        asg.sort(key=lambda a: (a.at, a.exc.id))
        for i, a in enumerate(asg, 1):
            a.id = i
        self.exceptions, self.assignments = recs, asg

    # ---- exports and credit notes -------------------------------------------------------------------------------------
    def build_exports(self) -> None:
        r = self.r["exports"]
        approved = sorted((a for a in self.approvals if a.decision == "approve"), key=lambda a: (a.at, a.inv.id))
        exported: set[int] = set()
        batches, requests = [], []
        t = datetime(2025, 10, 10, 16, tzinfo=UTC)
        n = 0
        while t <= WIN_END:
            ids = []
            for a in approved:
                if a.inv.seq not in exported and a.at <= t - timedelta(hours=3) and r.random() > 0.06:
                    ids.append(a.inv)
            if ids:
                n += 1
                for i in ids:
                    exported.add(i.seq)
                    i.exported_at = t
                    i.batch = f"bat-{n:03d}"
                by = r.choice(REVIEWERS + (ADMIN,))
                b = NS(id=f"bat-{n:03d}", key=f"exp-key-{n:03d}", by=by, at=t, invs=sorted(ids, key=lambda i: i.id))
                batches.append(b)
                requests.append(NS(batch=b, at=t, repeat=False))
            t += timedelta(days=7)
        close = datetime(2026, 9, 30, 22, tzinfo=UTC)                    # period close: every approved invoice still unexported
        ids = [a.inv for a in approved if a.inv.seq not in exported]
        if ids:
            n += 1
            for i in ids:
                exported.add(i.seq)
                i.exported_at = close
                i.batch = f"bat-{n:03d}"
            b = NS(id=f"bat-{n:03d}", key=f"exp-key-{n:03d}", by=ADMIN, at=close, invs=sorted(ids, key=lambda i: i.id))
            batches.append(b)
            requests.append(NS(batch=b, at=close, repeat=False))
        for b in r.sample(batches[:-1], 7):
            requests.append(NS(batch=b, at=b.at + timedelta(seconds=r.randint(20, 90)), repeat=True))
        requests.sort(key=lambda q: (q.at, q.batch.id))
        self.batches, self.requests = batches, requests
        self.stats["exported_invoices"] = len(exported)

    def build_credits(self) -> None:
        r = self.r["credits"]
        n_target = round(N_INVOICES * CREDIT_SHARE_PERMILLE / 1000)
        cand = sorted((a.inv for a in self.approvals if a.decision == "approve" and a.at <= WIN_END - timedelta(days=8)),
                      key=lambda i: i.id)
        chosen = r.sample(cand, n_target)
        notes = []
        for inv in chosen:
            u = r.random()
            amt = inv.total_c if u < 0.12 else rhu(inv.total_c * r.choice((25, 50, 50, 75)), 100) if u < 0.5 else \
                max(1, rhu(inv.total_c * r.randint(3, 60), 100))
            amt = min(amt, inv.total_c)
            at = norm_biz(inv.approved_at + timedelta(days=r.randint(2, 45), hours=r.randint(0, 6)))
            at = min(at, norm_biz(WIN_END - timedelta(days=1)))
            if at <= inv.approved_at:
                at = norm_biz(inv.approved_at + timedelta(days=2))
            notes.append(NS(inv=inv, amount=amt, at=at))
        for inv in r.sample(chosen, 6):                                   # a second credit note on a few invoices
            first = next(n for n in notes if n.inv is inv)
            left = inv.total_c - first.amount
            if left >= 200:
                notes.append(NS(inv=inv, amount=max(1, rhu(left * r.randint(10, 60), 100)),
                                at=max(min(norm_biz(first.at + timedelta(days=r.randint(3, 20))), norm_biz(WIN_END - timedelta(days=1))),
                                       first.at + timedelta(hours=1))))
        notes.sort(key=lambda n: (n.at, n.inv.id))
        for i, n in enumerate(notes, 1):
            n.id = f"cn-{i:03d}"
        self.credits = notes

    # ---- policies, rows -----------------------------------------------------------------------------------------------
    def rows(self) -> dict[str, list[dict[str, Any]]]:
        E: dict[str, list[dict[str, Any]]] = {}
        E["vendors"] = [{"vendor_id": v.id, "vendor_name": v.name, "tax_reference": v.tax_ref, "currency": v.currency,
                         "active": v.active} for v in self.vendors]
        E["purchase_orders"] = [{"po_id": p.id, "vendor_id": p.vendor.id, "ordered_at": ts(p.ordered_at),
                                 "status": p.status, "currency": p.currency} for p in self.pos]
        E["po_lines"] = [{"po_line_id": l.id, "po_id": p.id, "product_code": l.product, "quantity": fq(l.units),
                          "unit_price": fp(l.price_u)} for p in self.pos for l in p.lines]
        rc_sorted = sorted(self.receipts, key=lambda x: (x.dt, x.seq))
        for i, rc in enumerate(rc_sorted, 1):
            rc.id = f"rc-{i:04d}"
        E["receipts"] = [{"receipt_id": rc.id, "po_line_id": rc.line.id, "received_quantity": fq(rc.units),
                          "received_at": ts(rc.dt), "reversed": rc.reversed} for rc in rc_sorted]
        E["invoices"] = [{"invoice_id": i.id, "vendor_id": i.vendor.id, "invoice_number": i.number,
                          "invoice_date": i.date.isoformat(), "currency": i.currency, "tax_rate": fp(i.rate_u),
                          "freight": fm(i.freight_c), "invoice_discount": fm(i.disc_c), "declared_total": fm(i.declared_c),
                          "created_by": i.created_by, "source_sha256": i.sha, "source_filename": i.filename,
                          "idempotency_key": i.key, "imported_at": ts(i.imported_at)}
                         for i in sorted(self.invoices, key=lambda i: i.id)]
        E["invoice_lines"] = [{"invoice_line_id": l.id, "invoice_id": i.id, "po_line_id": l.po_line.id,
                               "quantity": fq(l.units), "unit_price": fp(l.price_u)}
                              for i in sorted(self.invoices, key=lambda i: i.id) for l in i.lines]
        E["credit_notes"] = [{"credit_id": n.id, "invoice_id": n.inv.id, "credit_amount": fm(n.amount),
                              "credited_at": ts(n.at)} for n in self.credits]
        E["approval_policies"] = [
            {"policy_id": "pol-v1", "version_number": 1, "amount_limit": fm(LIMIT_V1), "reviewer_role": "reviewer",
             "effective_from": ts(WIN_START)},
            {"policy_id": "pol-v2", "version_number": 2, "amount_limit": fm(LIMIT_V2), "reviewer_role": "reviewer",
             "effective_from": ts(V2_FROM)}]
        E["approvals"] = [{"approval_id": a.id, "invoice_id": a.inv.id, "actor_id": a.actor, "actor_role": a.role,
                           "decision": a.decision, "decided_at": ts(a.at), "reason": a.reason} for a in self.approvals]
        E["export_requests"] = [{"batch_id": q.batch.id, "idempotency_key": q.batch.key,
                                 "invoice_ids": [i.id for i in q.batch.invs], "exported_at": ts(q.at)} for q in self.requests]
        E["exceptions"] = []
        for e in self.exceptions:
            owner = e.assignments[-1].owner if e.assignments else None
            status = "resolved" if e.resolved else "assigned" if owner else "open"
            E["exceptions"].append({"exception_id": e.id, "invoice_id": e.inv.id, "exception_type": e.typ, "status": status,
                                    "owner_id": owner, "created_at": ts(e.created),
                                    "resolved_at": ts(e.resolved) if e.resolved else None})
        E["exception_assignments"] = [{"assignment_id": a.id, "exception_id": a.exc.id, "owner_id": a.owner,
                                       "assigned_by": a.by, "assigned_at": ts(a.at), "note": a.note} for a in self.assignments]
        E["export_batches"] = [{"batch_id": b.id, "idempotency_key": b.key, "requested_by": b.by, "exported_at": ts(b.at),
                                "row_count": len(b.invs), "total": fm(sum(i.total_c for i in b.invs))} for b in self.batches]
        return E

    # ---- orchestration ------------------------------------------------------------------------------------------------
    def build(self) -> dict[str, Any]:
        self.build_vendors()
        self.build_pos()
        extras = 6 + N_DUPLICATES                               # 3 same-bytes copies + 3 cumulative + re-sent PDFs
        self.calibrate(N_INVOICES - extras)
        self.build_receipts()
        self.build_invoices()
        self.inject()
        for i, inv in enumerate(sorted(self.invoices, key=lambda i: i.id), 1):
            inv.key = f"idem-{i:04d}"
        if len(self.invoices) != N_INVOICES:
            raise GenError(f"{len(self.invoices)} invoices, wanted {N_INVOICES}")
        self.decide()
        self.build_exceptions()
        self.build_exports()
        self.build_credits()
        self.finish_po_status()
        entities = self.rows()
        from_gen = NS(entities=entities)
        self.events_and_manifest(entities)
        return {"entities": entities, "injections": {"list": self.inj_list}, "events": self.events, "designed": self.designed,
                "stats": self.stats, "parameters": self.parameters()}

    def finish_po_status(self) -> None:
        inv_units: dict[str, int] = {}
        for inv in self.invoices:
            if inv.seq in self.h.merged:
                continue
            for l in inv.lines:
                inv_units[l.po_line.id] = inv_units.get(l.po_line.id, 0) + l.units
        rc_units: dict[str, int] = {}
        for rc in self.receipts:
            if not rc.reversed:
                rc_units[rc.line.id] = rc_units.get(rc.line.id, 0) + rc.units
        for po in self.pos:
            closed = all(rc_units.get(l.id, 0) >= l.units and inv_units.get(l.id, 0) >= l.units for l in po.lines)
            po.status = "closed" if closed else "open"

    def parameters(self) -> dict[str, Any]:
        return {"window": ["2025-10-01", "2026-09-30"], "vendors": N_VENDORS, "currencies": ["USD", "EUR", "GBP"],
                "purchase_orders": N_POS, "po_lines": N_PO_LINES, "invoices": N_INVOICES, "resent_pdf_duplicates": N_DUPLICATES,
                "credit_share": CREDIT_SHARE_PERMILLE / 1000, "reversal_share_of_first_entry_receipts": REVERSAL_PERMILLE / 1000,
                "group_02x": ["ven-020", "ven-029"], "p_short_02x_line": P_SHORT_02X, "p_duplicate_month_end": P_DUP_MONTH_END,
                "price_list_vendor": f"ven-{PRICE_VENDOR:03d}", "price_change_from": PRICE_CHANGE.isoformat(),
                "price_uplift": 0.075, "catalogue_updated": ts(PO_CATALOGUE_UPDATED),
                "policy_limits": {"pol-v1": fm(LIMIT_V1), "pol-v2": fm(LIMIT_V2), "v2_from": ts(V2_FROM)},
                "tolerances": TOLERANCES, "as_of": ts(AS_OF), "nightly_match": "02:00:00Z",
                "snapshot_cutoffs": SNAPSHOT_CUTOFFS, "export_batches": "Fridays 16:00Z"}

    # ---- injection manifest, events, designed relationships (filled in by the second half of this file) -------------
    def events_and_manifest(self, entities: dict[str, list[dict[str, Any]]]) -> None:
        build_manifest(self, entities)


SNAPSHOT_CUTOFFS = ["2026-03-31T23:59:59Z", "2026-06-30T23:59:59Z", ts(AS_OF)]


# ---------------------------------------------------------------------------------------------------------------------
# injection manifest, replay events and the designed relationships
# ---------------------------------------------------------------------------------------------------------------------

def build_manifest(w: World, E: dict[str, list[dict[str, Any]]]) -> None:
    h = w.h
    inj = w.inj
    ver = f"ib-{w.seed}-{DATE_TAG}"

    def flagged(inv: NS, typ: str) -> bool:
        st = w.final_state(h, inv)
        return st is not None and typ in st[1]

    lst: list[dict[str, Any]] = []

    # INJ-01 same bytes, two filenames
    for a, b in inj.copies:
        if h.merged.get(b.seq) != (a.seq, "DUPLICATE_SOURCE_BYTES") or w.matched_from(h, a) is None:
            raise GenError("INJ-01 copy not merged by source bytes")
    lst.append({
        "id": "INJ-01", "test": "P05-TEST-01", "entity": "invoices", "location": "entity_files+events",
        "record_ids": [b.id for a, b in inj.copies],
        "description": "The same PDF bytes imported twice under two filenames (and two invoice ids): one obligation, not two.",
        "detail": [{"invoice_id": b.id, "same_bytes_as": a.id, "source_sha256": b.sha,
                    "filenames": [a.filename, b.filename]} for a, b in inj.copies],
        "handling_kind": "merged",
        "expected_handling": "ingest merges the later import into the earlier one, reason DUPLICATE_SOURCE_BYTES (bytes are checked before the identity); lineage and hash kept, no received quantity consumed.",
        "expected_merges": [{"entity": "invoices", "id": b.id, "reason_code": "DUPLICATE_SOURCE_BYTES", "merged_into": a.id}
                            for a, b in inj.copies],
        "expected_rejections": []})

    # INJ-02 reused invoice number across vendors
    for a, b in inj.reuse:
        if a.seq in h.merged or b.seq in h.merged or norm_number(a.number) != norm_number(b.number) or a.vendor is b.vendor:
            raise GenError("INJ-02 pair is not a cross-vendor reuse")
    lst.append({
        "id": "INJ-02", "test": "P05-TEST-02", "entity": "invoices", "location": "entity_files",
        "record_ids": [x.id for a, b in inj.reuse for x in (a, b)],
        "description": "Four pairs of invoices from different vendors carry the same invoice number (two pairs differ only in case).",
        "detail": [{"invoice_number": a.number, "invoices": [a.id, b.id], "vendors": [a.vendor.id, b.vendor.id]} for a, b in inj.reuse],
        "handling_kind": "accepted_distinct",
        "expected_handling": "not duplicates: identity includes the vendor (D-01), so both invoices of each pair are accepted and none is merged.",
        "expected_merges": [], "expected_rejections": []})

    # INJ-03 partial receipts short of invoiced quantity
    exc3 = []
    for d in inj.shorts:
        if not flagged(d["invoice"], "QUANTITY_BLOCKED"):
            raise GenError("INJ-03 invoice is not quantity-blocked")
        exc3.append({"invoice_id": d["invoice"].id, "reason_code": "QUANTITY_BLOCKED"})
    lst.append({
        "id": "INJ-03", "test": "P05-TEST-03", "entity": "receipts", "location": "entity_files",
        "record_ids": [d["invoice"].id for d in inj.shorts],
        "description": "Five invoices bill a quantity the delivery receipt does not cover: the receipt was booked at 60-85 % of the invoiced quantity and nothing followed.",
        "detail": [{"invoice_id": d["invoice"].id, "invoice_line_id": d["line"].id, "po_line_id": d["line"].po_line.id,
                    "invoiced_quantity": fq(d["invoiced"]), "received_quantity": fq(d["received"])} for d in inj.shorts],
        "handling_kind": "exception",
        "expected_handling": "match raises QUANTITY_BLOCKED on the line (invoiced above the available received quantity); the invoice consumes nothing and stays an open exception.",
        "expected_exceptions": exc3, "expected_rejections": []})

    # INJ-04 cumulative consumption
    exc4 = []
    for a, b in inj.extras4:
        if not (flagged(b, "QUANTITY_BLOCKED") and w.matched_from(h, a) is not None):
            raise GenError("INJ-04 second invoice is not blocked")
        exc4.append({"invoice_id": b.id, "reason_code": "QUANTITY_BLOCKED"})
    lst.append({
        "id": "INJ-04", "test": "P05-TEST-04", "entity": "invoices", "location": "entity_files",
        "record_ids": [b.id for a, b in inj.extras4],
        "description": "Three vendors bill a second invoice against a line whose full received quantity the first invoice already consumed; each invoice is within the received quantity on its own.",
        "detail": [{"invoice_id": b.id, "first_invoice": a.id, "po_line_id": b.lines[0].po_line.id,
                    "first_quantity": fq(a.lines[0].units), "second_quantity": fq(b.lines[0].units)} for a, b in inj.extras4],
        "handling_kind": "exception",
        "expected_handling": "match is cumulative (D-03): the available quantity is net received minus quantity on earlier matched invoices, so the second invoice is QUANTITY_BLOCKED.",
        "expected_exceptions": exc4, "expected_rejections": []})

    # INJ-05 rounding gap over tolerance
    exc5 = []
    for i in inj.gaps:
        if not flagged(i, "ROUNDING_EXCEPTION"):
            raise GenError("INJ-05 invoice is not a rounding exception")
        exc5.append({"invoice_id": i.id, "reason_code": "ROUNDING_EXCEPTION"})
    lst.append({
        "id": "INJ-05", "test": "P05-TEST-05", "entity": "invoices", "location": "entity_files",
        "record_ids": [i.id for i in inj.gaps],
        "description": "Four invoices declare a total that differs from the computed total by 0.03, 0.05, 0.10 and 0.37, beyond the 0.02 per-invoice tolerance.",
        "detail": [{"invoice_id": i.id, "declared_total": fm(i.declared_c), "computed_total": fm(i.total_c),
                    "difference": fm(abs(i.declared_c - i.total_c))} for i in inj.gaps],
        "handling_kind": "exception",
        "expected_handling": "raises ROUNDING_EXCEPTION (gap beyond tolerance); differences up to 0.02 elsewhere in the data are tolerated and disclosed.",
        "expected_exceptions": exc5, "expected_rejections": []})

    # INJ-06/07/08/10/11/12 replay events (filled below)
    # INJ-09 foreign currency without a rate
    exc9 = []
    for i, was, now in inj.fx:
        if not flagged(i, "CURRENCY_MISMATCH"):
            raise GenError("INJ-09 invoice is not a currency mismatch")
        exc9.append({"invoice_id": i.id, "reason_code": "CURRENCY_MISMATCH"})
    inj9 = {
        "id": "INJ-09", "test": "P05-TEST-09", "entity": "invoices", "location": "entity_files",
        "record_ids": [i.id for i, _, _ in inj.fx],
        "description": "Three invoices are denominated in a currency other than their purchase order's and no dated conversion rate exists.",
        "detail": [{"invoice_id": i.id, "po_id": i.po.id, "po_currency": was, "invoice_currency": now} for i, was, now in inj.fx],
        "handling_kind": "exception",
        "expected_handling": "never compared without a dated conversion: CURRENCY_MISMATCH on every line (D-02); the invoice consumes nothing.",
        "expected_exceptions": exc9, "expected_rejections": []}

    events, ev_inj = build_events(w, ver)
    w.events = events
    reps = [q for q in w.requests if q.repeat]
    by_inj = {
        "INJ-06": {"description": "A reviewer who imported an invoice tries to approve it himself.",
                   "expected_handling": "refused 403 SELF_APPROVAL (the approver must differ from created_by); the refusal is audited and the invoice stays matched.",
                   "test": "P05-TEST-06", "entity": "approvals"},
        "INJ-07": {"description": "Two reviewers approve the same matched invoice at the same moment.",
                   "expected_handling": "exactly one approval succeeds (200); the other is refused 409 INVALID_STATE (the invoice is no longer matched); one approval row exists.",
                   "test": "P05-TEST-07", "entity": "approvals"},
        "INJ-08": {"description": "The same credit note id is applied twice (a client retry with a fresh idempotency key).",
                   "expected_handling": "the second application is refused 409 CREDIT_ALREADY_APPLIED; the approved payable is reduced once; no cash movement.",
                   "test": "P05-TEST-08", "entity": "credit_notes"},
        "INJ-10": {"description": "A corrected extraction is re-imported under the id of the original invoice with different bytes.",
                   "expected_handling": "refused 409 DUPLICATE_ID: the source of an import is immutable, corrections are versioned rows (C06, an extension, answers 501), the original row never changes.",
                   "test": "P05-TEST-10", "entity": "invoices"},
        "INJ-12": {"description": "A request carries a paid flag (paid: true) on an export.",
                   "expected_handling": "refused 422 FIELD_UNEXPECTED: nothing in the contract marks an invoice paid and there is no paid status; the invoice stays approved.",
                   "test": "P05-TEST-12", "entity": "export_batches"},
    }
    for iid, meta in sorted(by_inj.items()):
        lst.append({"id": iid, "test": meta["test"], "entity": meta["entity"], "location": "events", "record_ids": [],
                    "description": meta["description"], "handling_kind": "replay_only", "expected_handling": meta["expected_handling"],
                    "events": [e["event_id"] for e in events if e["injection"] == iid], "expected_rejections": []})
    lst.append(inj9)
    lst.append({
        "id": "INJ-11", "test": "P05-TEST-11", "entity": "export_requests", "location": "entity_files+events",
        "record_ids": sorted({q.batch.id for q in reps}),
        "description": f"{len(reps)} export batches were requested a second time seconds after the first request (a retry after a timeout): same batch id, same idempotency key, later exported_at.",
        "detail": [{"batch_id": q.batch.id, "idempotency_key": q.batch.key, "first_exported_at": ts(q.batch.at),
                    "repeat_exported_at": ts(q.at)} for q in reps],
        "handling_kind": "warned",
        "expected_handling": "the repeat returns the prior batch (API: status returned_prior with warning BATCH_RETURNED_PRIOR, or a stored replay for the same key); export.repeat_requests_returned_prior counts it, no second row, reconciliation stays 0.00.",
        "events": [e["event_id"] for e in events if e["injection"] == "INJ-11"], "expected_rejections": []})
    lst.sort(key=lambda x: x["id"])
    for rec in lst:
        rec.setdefault("expected_merges", [])
        rec.setdefault("expected_exceptions", [])
        rec.setdefault("expected_rejections", [])
        rec.setdefault("record_count", len(rec["record_ids"]))
    w.inj_list = lst
    w.designed = designed_relationships(w)


def pick_spare_lines(w: World, k: int) -> list[NS]:
    r = w.r["events"]
    cand = []
    for po in w.pos:
        v = po.vendor
        if v.currency != "USD" or v.g02x or v.price_vendor or not v.active:
            continue
        for l in po.lines:
            if w.h.spare.get(l.id, 0) >= 3 * 10000 and l.step == 10000 and l.price_u % 10 ** 4 == 0:
                cand.append(l)
    cand.sort(key=lambda l: l.id)
    if len(cand) < k:
        raise GenError("not enough spare received lines for the replay events")
    return r.sample(cand, k)


def build_events(w: World, ver: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    lines = pick_spare_lines(w, 8)
    CLERK = {"X-Actor-Id": "usr-clerk01", "X-Actor-Role": "clerk"}
    REV1 = {"X-Actor-Id": "usr-rev01", "X-Actor-Role": "reviewer"}
    REV2 = {"X-Actor-Id": "usr-rev02", "X-Actor-Role": "reviewer"}

    def invoice_input(n: int, l: NS, units: int = 10000, number: str | None = None, suffix: str = "a",
                      declared: int | None = None, fname: str | None = None, digest: str | None = None) -> dict[str, Any]:
        v = l.po.vendor
        sub, tax, total = amounts([NS(units=units, price_u=l.price_u)], v.rate_u, 0, 0)
        return {"invoice_id": f"inv-ev{n:02d}{suffix}", "vendor_id": v.id, "invoice_number": number or f"EV-{n:02d}{suffix.upper()}",
                "invoice_date": "2026-09-30", "currency": v.currency, "tax_rate": fp(v.rate_u), "freight": "0.00",
                "invoice_discount": "0.00", "declared_total": fm(declared if declared is not None else total),
                "source_sha256": digest or sha(f"{w.seed}|event|{n}|{suffix}"),
                "source_filename": fname or f"EV-{n:02d}{suffix.upper()}.pdf", "imported_at": f"2026-09-30T23:{50 + n:02d}:00Z",
                "lines": [{"invoice_line_id": f"il-ev{n:02d}{suffix}", "po_line_id": l.id, "quantity": fq(units), "unit_price": fp(l.price_u)}]}, total

    counter = {"n": 0}

    def step(ev: int, command: str, headers: dict[str, str], inp: dict[str, Any], tag: str) -> dict[str, Any]:
        counter["n"] += 1
        return {"command": command, "headers": headers,
                "input": {"dataset_version": ver, "idempotency_key": f"ev-{ev:02d}{tag}", "input": inp,
                          "request_id": f"ev-{ev:02d}{tag}"}}

    def flow(ev: int, l: NS, who_import: dict[str, str], extra_digest: str | None = None) -> tuple[list[dict[str, Any]], str, int]:
        inp, total = invoice_input(ev, l, digest=extra_digest)
        iid = inp["invoice_id"]
        return [step(ev, "import-invoice", who_import, inp, "a"), step(ev, "validate-invoice", CLERK, {"invoice_id": iid}, "b"),
                step(ev, "match-three-way", CLERK, {"invoice_id": iid}, "c")], iid, total

    events: list[dict[str, Any]] = []
    # EV-01 the same bytes under another filename (INJ-01)
    inp_a, _ = invoice_input(1, lines[0], suffix="a", fname="EV-01.pdf")
    inp_b, _ = invoice_input(1, lines[0], suffix="b", fname="scan_EV-01 (1).pdf", digest=inp_a["source_sha256"])
    inp_b["invoice_number"] = inp_a["invoice_number"]
    events.append({"event_id": "EV-01", "injection": "INJ-01", "command": "import-invoice", "requires": [],
                   "steps": [step(1, "import-invoice", CLERK, inp_a, "a"), step(1, "import-invoice", CLERK, inp_b, "b")],
                   "expected_status": 200, "expected_reason": "DUPLICATE_SOURCE_BYTES",
                   "expected": {"status": "merged", "import_status": "merged", "reason_code": "DUPLICATE_SOURCE_BYTES",
                                "duplicate_of": inp_a["invoice_id"]},
                   "expected_handling": "accepted as a merged import: same bytes under a second filename is one obligation (warning DUPLICATE_SOURCE_BYTES), nothing consumed"})
    # EV-02 self-approval (INJ-06)
    st, iid, _ = flow(2, lines[1], REV2)
    events.append({"event_id": "EV-02", "injection": "INJ-06", "command": "approve-invoice", "requires": [],
                   "steps": st + [step(2, "approve-invoice", REV2, {"invoice_id": iid}, "d")],
                   "expected_status": 403, "expected_reason": "SELF_APPROVAL",
                   "expected": {"invoice_status_after": "matched", "approvals_rows": 0},
                   "expected_handling": "refused: the approver imported the invoice (usr-rev02 created it); the invoice stays matched"})
    # EV-03 racing approvals (INJ-07): the last two steps are sent at the same moment
    st, iid, _ = flow(3, lines[2], CLERK)
    events.append({"event_id": "EV-03", "injection": "INJ-07", "command": "approve-invoice", "requires": [], "concurrent_last": 2,
                   "steps": st + [step(3, "approve-invoice", REV1, {"invoice_id": iid}, "d"),
                                  step(3, "approve-invoice", REV2, {"invoice_id": iid}, "e")],
                   "expected_status": 409, "expected_reason": "INVALID_STATE",
                   "expected": {"concurrent_statuses": [200, 409], "approvals_rows": 1, "invoice_status_after": "approved"},
                   "expected_handling": "exactly one of the two simultaneous approvals succeeds; the loser is refused 409 INVALID_STATE; one approval row"})
    # EV-04 credit applied twice (INJ-08)
    st, iid, total = flow(4, lines[3], CLERK)
    credit = max(100, total // 10)
    cr = {"credit_id": "cn-ev04", "invoice_id": iid, "credit_amount": fm(credit), "reason": "pricing correction"}
    events.append({"event_id": "EV-04", "injection": "INJ-08", "command": "apply-credit-note", "requires": [],
                   "steps": st + [step(4, "approve-invoice", REV1, {"invoice_id": iid}, "d"),
                                  step(4, "apply-credit-note", REV1, cr, "e"), step(4, "apply-credit-note", REV1, cr, "f")],
                   "expected_status": 409, "expected_reason": "CREDIT_ALREADY_APPLIED",
                   "expected": {"credit_rows": 1, "credit_total": fm(credit), "cash_movement": False},
                   "expected_handling": "second application refused: a credit note applies once per credit_id; one credit row; no cash movement"})
    # EV-05 correction overwriting the original (INJ-10)
    inp5, _ = invoice_input(5, lines[4], suffix="a")
    fixed, _ = invoice_input(5, lines[4], suffix="a", units=20000, fname="EV-05A_corrected.pdf",
                             digest=sha(f"{w.seed}|event|5|corrected"))
    events.append({"event_id": "EV-05", "injection": "INJ-10", "command": "import-invoice", "requires": [],
                   "steps": [step(5, "import-invoice", CLERK, inp5, "a"), step(5, "import-invoice", CLERK, fixed, "b")],
                   "expected_status": 409, "expected_reason": "DUPLICATE_ID",
                   "expected": {"lines_after": 1, "source_sha256_after": inp5["source_sha256"]},
                   "expected_handling": "refused: an invoice id with different bytes is never overwritten; the original extraction is unchanged (a correction is a versioned row, C06 answers 501)"})
    # EV-06 repeated export after a timeout (INJ-11)
    st, iid, total = flow(6, lines[5], CLERK)
    exp1 = {"batch_id": "bat-ev06", "invoice_ids": [iid], "exported_at": "2026-10-02T16:00:00Z"}
    exp2 = {**exp1, "exported_at": "2026-10-02T16:00:40Z"}
    s_exp1 = step(6, "export-payable", REV1, exp1, "e")
    s_exp2 = step(6, "export-payable", REV1, exp2, "e")
    events.append({"event_id": "EV-06", "injection": "INJ-11", "command": "export-payable", "requires": [],
                   "steps": st + [step(6, "approve-invoice", REV1, {"invoice_id": iid}, "d"), s_exp1, s_exp2],
                   "expected_status": 200, "expected_reason": "returned_prior",
                   "expected": {"idempotent_replay": True, "export_rows": 1, "export_requests": 2,
                                "outcomes": ["created", "returned_prior"], "amount": fm(total)},
                   "expected_handling": "the retry (same key, later exported_at) returns the stored batch (Idempotent-Replay), is counted as returned_prior and adds no row"})
    # EV-07 a paid flag (INJ-12)
    st, iid, _ = flow(7, lines[6], CLERK)
    paid = {"batch_id": "bat-ev07", "invoice_ids": [iid], "exported_at": "2026-10-02T16:00:00Z", "paid": True}
    events.append({"event_id": "EV-07", "injection": "INJ-12", "command": "export-payable", "requires": [],
                   "steps": st + [step(7, "approve-invoice", REV1, {"invoice_id": iid}, "d"),
                                  step(7, "export-payable", REV1, paid, "e")],
                   "expected_status": 422, "expected_reason": "FIELD_UNEXPECTED",
                   "expected": {"invoice_status_after": "approved", "export_rows": 0},
                   "expected_handling": "refused: the contract has no paid flag and no paid status; nothing is exported and the invoice stays approved"})
    return events, {}


def designed_relationships(w: World) -> list[dict[str, Any]]:
    h = w.h
    every = [i for i in w.invoices if i.seq not in h.merged]
    book = [i for i in every if i.rejected_at is None]                  # the domain's book: validated, not merged, not rejected

    def rate(group: list[NS]) -> tuple[int, int]:
        qb = sum(1 for i in group if "QUANTITY_BLOCKED" in w.final_state(h, i)[1])
        return qb, len(group)

    g02 = [i for i in book if i.vendor.g02x]
    oth = [i for i in book if not i.vendor.g02x]
    a, b = rate(g02)
    c, d = rate(oth)
    per_vendor = {}
    for v in w.vendors:
        grp = [i for i in book if i.vendor is v]
        if grp:
            q, n = rate(grp)
            per_vendor[v.id] = f"{q}/{n}"
    pv = [i for i in book if i.vendor.price_vendor]
    pv_flag = [i for i in pv if "PRICE_VARIANCE" in w.final_state(h, i)[1]]
    pv_first = min((night_time(h.hist[i.seq][0][0]) for i in every if i.vendor.price_vendor
                    and "PRICE_VARIANCE" in w.final_state(h, i)[1]), default=None)
    pv_all = sum(1 for i in book if "PRICE_VARIANCE" in w.final_state(h, i)[1])
    dups = [(o, i) for o, i in w.inj.dups]
    end3 = sum(1 for o, i in dups if i.imported_at.day >= last_dom(i.imported_at.date()).day - 2)
    all_end3 = sum(1 for i in w.invoices if i.imported_at.day >= last_dom(i.imported_at.date()).day - 2)
    w.stats["designed"] = {"ven02x_qb": [a, b], "others_qb": [c, d]}
    return [
        {"id": "DR-01", "name": "ven-02x invoices before receipts",
         "statement": "Vendors ven-020..ven-029 invoice 3-25 days before they deliver and a third of their lines are never fully received in the window: their invoices carry by far the highest QUANTITY_BLOCKED rate.",
         "realised": {"ven_02x_invoices": b, "ven_02x_quantity_blocked": a, "ven_02x_rate": f"{a / b:.4f}",
                      "other_invoices": d, "other_quantity_blocked": c, "other_rate": f"{c / d:.4f}",
                      "ven_02x_share_of_blocked": f"{a / (a + c):.4f}"}},
        {"id": "DR-02", "name": "price-list change from 2026-03",
         "statement": f"ven-{PRICE_VENDOR:03d} bills a new price list (+7.5 %) from 2026-03-01 on purchase orders still carrying the old prices (the catalogue is updated on 2026-04-15): PRICE_VARIANCE exceptions begin in 2026-03.",
         "realised": {"vendor": f"ven-{PRICE_VENDOR:03d}", "vendor_invoices": len(pv), "price_variance_invoices": len(pv_flag),
                      "first_flagged_at": ts(pv_first) if pv_first else None, "all_price_variance_invoices": pv_all,
                      "vendor_share_of_price_variance": f"{len(pv_flag) / pv_all:.4f}"}},
        {"id": "DR-03", "name": "re-sent PDFs cluster at month ends",
         "statement": "A re-sent PDF (different bytes, same vendor, number, date and total) is imported in the last three days of the month far more often than invoices in general.",
         "realised": {"resent_duplicates": len(dups), "in_last_three_days_of_month": end3, "share": f"{end3 / len(dups):.4f}",
                      "all_invoices_in_last_three_days_share": f"{all_end3 / len(w.invoices):.4f}"}},
        {"id": "DR-04", "name": "approval limit change on 2026-04-01",
         "statement": f"Reviewers may approve up to {fm(LIMIT_V1)} under pol-v1 and up to {fm(LIMIT_V2)} from 2026-04-01 (pol-v2); invoices above the limit in force are matched but never approved (no escalation role is carried by the fixture shape).",
         "realised": {"approvals_between_limits_after_change": sum(1 for a in w.approvals if a.decision == "approve" and LIMIT_V1 < a.inv.total_c <= LIMIT_V2),
                      "matched_unapproved_over_limit": w.stats["approvals_over_limit_pending"]}},
    ]


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
    return World(seed).build()


def write_golden(out: Path) -> None:
    """The hand-derived fixture in the published shape, for ``?dataset=golden`` (same layout as ServiceFlow's)."""
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
        "designed_relationships": [], "fixture_id": "invoicebridge-golden-v1",
        "as_of": inputs["as_of"], "snapshot_cutoffs": inputs["snapshot_cutoffs"], "tolerances": inputs["tolerances"],
        "expected": "expected.json", "row_counts": counts,
    }
    (gdir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def write_all(seed: int, out: Path, data_dir: Path) -> dict[str, Any]:
    built = build(seed)
    ents = built["entities"]
    version = f"ib-{seed}-{DATE_TAG}"
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
        "window_start": ts(WIN_START), "window_end": ts(WIN_END), "as_of": ts(AS_OF), "snapshot_cutoffs": SNAPSHOT_CUTOFFS,
        "tolerances": TOLERANCES,
        "generator": {"name": "generate.py", "seed": seed, "parameters": built["parameters"]},
        "row_counts": {name: len(ents[name]) for name in ENTITIES},
        "designed_relationships": built["designed"],
        "injection_manifest": "injection-manifest.json",
        "stats": built["stats"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_golden(out)
    return manifest


def shape_check(seed: int) -> int:
    golden = json.loads((APP_ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
    ents = build(seed)["entities"]
    bad = 0
    for name in ENTITIES:
        want = set(EXTRA_COLUMNS.get(name, ()))
        if name in golden and golden[name]:
            want = set(golden[name][0]) | set(EXTRA_ROW_FIELDS.get(name, ()))
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
    total = sum(p.stat().st_size for p in args.out.rglob("*.json"))
    print(json.dumps({"dataset_version": m["dataset_version"], "dataset_hash": m["dataset_hash"],
                      "row_counts": m["row_counts"], "bytes": total,
                      "elapsed_seconds": round(time.perf_counter() - t0, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
