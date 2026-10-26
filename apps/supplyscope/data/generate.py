#!/usr/bin/env python3
"""SupplyScope synthetic data generator (P03-WORK-03, docs/data-generator.md).

Stdlib only. Deterministic: ``random.Random(seed)`` derives one child stream per purpose (demand per SKU, the
supply simulation, reservations, injections), so the same seed and parameters give byte-identical entity files and the
same ``dataset_hash``. Nothing is imported from ``domain/``: the calendar rule and the replenishment rule are restated
here from docs/contracts.md (D-01, D-02, D-04, D-05).

    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --profile golden-shape-check

Writes ``<entity>.json`` (``{"entity", "dataset_version", "rows"}``) and ``manifest.json`` to ``--out``;
``injection-manifest.json`` and ``injection-events.json`` to ``--data-dir`` (default ``data/``) and a copy of the
injection manifest to ``--out``.
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
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
CONTRACT_VERSION = "v1"
START = date(2025, 4, 1)
END = date(2026, 9, 30)          # inclusive; the snapshot is cut at 23:59:59Z that day
NDAYS = (END - START).days + 1   # 548
AS_OF = "2026-09-30T23:59:59Z"
OPENING = "2025-03-31T23:00:00Z"  # opening balances: before the first day, so they never follow a sale in day order

ENTITIES = ("products", "locations", "suppliers", "sales", "inventory_movements", "purchase_orders",
            "purchase_order_lines", "receipts", "promotions", "forecast_runs", "forecast_points", "policy_scenarios",
            "backorders", "reservations", "replenishment_params", "cost_versions", "calendar_closures",
            "latent_demand", "lost_sales")

# id, name, calendar, quoted lead days, probability that a purchase order is late (receipt after the promised date)
SUPPLIERS = (("sup-01", "Northwind Components", "cal-01", 5, 0.08),
             ("sup-02", "Harbor Industrial Supply", "cal-02", 12, 0.10),
             ("sup-03", "Summit Wholesale", "cal-03", 9, 0.30),
             ("sup-04", "Pacific Trade Partners", "cal-04", 21, 0.10))
CLOSURE = ("clo-001", "cal-02", date(2026, 1, 5), date(2026, 1, 18))   # sup-02: two weeks closed
LOCATIONS = (("loc-01", "Main DC", "America/New_York"), ("loc-02", "Overflow DC", "America/Chicago"),
             ("loc-03", "East Cross-dock", "America/New_York"))
BACKLOG_LOCATION = "loc-03"      # the unmet-demand policy of record: backlog here, lost sale elsewhere
CAPACITY_LOCATION = "loc-02"
CAPACITY_FACTOR = {"loc-01": 2.0, "loc-02": 0.62, "loc-03": 2.0}  # storage_capacity / sum of target positions
DOW = (1.10, 1.05, 1.00, 1.00, 1.15, 0.90, 0.80)  # Monday .. Sunday
PROMO_DAYS = 10
COST_STEP = (date(2026, 2, 1), 0.06, "sup-04")    # one step: +6 % on every sup-04 product
RECENT_OPEN_DAYS = 25            # a short-shipped line stays open only if ordered this recently
Z_REORDER = 1.28
SERVICE_TARGETS = ("0.95", "0.98")
UNMET_POLICIES = ("lost_sale", "backlog")
FORECAST_CUTOFFS = (date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 16))
FORECAST_HORIZON = 14
N_A, N_B, N_C, N_INTERMITTENT, N_PROMOTED = 8, 16, 36, 12, 15


def default_parameters(seed: int) -> dict[str, Any]:
    return {
        "seed": seed, "window": [START.isoformat(), END.isoformat()], "days": NDAYS, "as_of": AS_OF,
        "locations": len(LOCATIONS), "skus": N_A + N_B + N_C, "abc_split": {"A": N_A, "B": N_B, "C": N_C},
        "intermittent_skus": N_INTERMITTENT, "promoted_skus": N_PROMOTED,
        "suppliers": {s[0]: {"quoted_lead_days": s[3], "late_probability": s[4]} for s in SUPPLIERS},
        "closure": {"calendar_id": CLOSURE[1], "from": CLOSURE[2].isoformat(), "to": CLOSURE[3].isoformat()},
        "backlog_location": BACKLOG_LOCATION, "capacity_location": CAPACITY_LOCATION,
        "capacity_factor": CAPACITY_FACTOR, "dow_profile": list(DOW), "promotion_days": PROMO_DAYS,
        "cost_step": {"effective_from": COST_STEP[0].isoformat(), "uplift": COST_STEP[1], "supplier_id": COST_STEP[2]},
        "service_targets": list(SERVICE_TARGETS), "unmet_policies": list(UNMET_POLICIES),
        "forecast_cutoffs": [d.isoformat() for d in FORECAST_CUTOFFS], "forecast_horizon_days": FORECAST_HORIZON,
        "reorder_z": Z_REORDER, "size_budget_bytes": 5_000_000,
        "volume_cap": ("one sale row and one sale movement per SKU x location x day with sales; each SKU is stocked at "
                       "one home location (60 pairs); only the 8 class-A pairs sell on almost every day, class B/C "
                       "pairs sell on about 5-60 % of days (rates chosen to stay under the 5 MB budget); latent demand "
                       "is published for class A, promoted and intermittent pairs, positive days only"),
    }


# ---------------------------------------------------------------------------------------------------------------------
# small helpers (no domain imports: restated rules)
# ---------------------------------------------------------------------------------------------------------------------

def day_of(i: int) -> date:
    return START + timedelta(days=i)


def ts(d: date, hh: int = 0, mm: int = 0, ss: int = 0) -> str:
    return f"{d.isoformat()}T{hh:02d}:{mm:02d}:{ss:02d}Z"


def money(x: float) -> str:
    return f"{x:.2f}"


def pack_round_up(q: int, pack: int) -> int:
    return -(-q // pack) * pack


def closed_days(calendar_id: str) -> set[date]:
    out: set[date] = set()
    if calendar_id == CLOSURE[1]:
        d = CLOSURE[2]
        while d <= CLOSURE[3]:
            out.add(d)
            d += timedelta(days=1)
    return out


def arrival_date(start: date, lead_days: int, calendar_id: str) -> date:
    """The date ``lead_days`` open supplier-calendar days after ``start`` (closure days do not count, P03-TEST-05)."""
    closed = closed_days(calendar_id)
    d, counted = start, 0
    while counted < lead_days:
        d += timedelta(days=1)
        if d not in closed:
            counted += 1
    return d


def poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    if mean > 30:
        return max(0, round(rng.gauss(mean, math.sqrt(mean))))
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


class Sku:
    """One SKU and its single home location (the 60 SKU x location pairs)."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.product_id = f"prod-{n:03d}"
        self.sku = f"SKU-{n:03d}"
        self.abc = "A" if n <= N_A else "B" if n <= N_A + N_B else "C"
        self.intermittent = False
        self.promoted = False
        self.location_id = ""
        self.supplier_id = ""
        self.mean = 0.0          # mean daily latent demand before weekly / seasonal / promotion factors
        self.p_event = 0.0       # intermittent only: probability of a demand event on a day
        self.pack = 1
        self.moq = 0
        self.cost = 0.0
        self.rop = 0
        self.target = 0
        self.promos: list[dict] = []
        self.latent: list[int] = []
        # simulation state
        self.stock = 0
        self.on_order = 0
        self.open_bo: list[dict] = []
        self.observed: list[int] = [0] * NDAYS
        self.stockout_days: list[int] = []

    @property
    def key(self) -> tuple[str, str]:
        return (self.product_id, self.location_id)


# ---------------------------------------------------------------------------------------------------------------------
# the generator
# ---------------------------------------------------------------------------------------------------------------------

class Generator:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        master = random.Random(seed)
        self.rng_setup = random.Random(master.getrandbits(64))
        self.rng_demand = [random.Random(master.getrandbits(64)) for _ in range(N_A + N_B + N_C)]
        self.rng_sim = random.Random(master.getrandbits(64))
        self.rng_extra = random.Random(master.getrandbits(64))
        self.skus: list[Sku] = []
        self.sup = {s[0]: s for s in SUPPLIERS}

    # ---- catalogue ------------------------------------------------------------------------------------------------
    def setup_skus(self) -> None:
        r = self.rng_setup
        self.skus = [Sku(n) for n in range(1, N_A + N_B + N_C + 1)]
        smooth_c = [s for s in self.skus if s.abc == "C"]
        for s in r.sample(smooth_c, N_INTERMITTENT):
            s.intermittent = True
        b_skus = [s for s in self.skus if s.abc == "B"]
        for s in [s for s in self.skus if s.abc == "A"] + r.sample(b_skus, N_PROMOTED - N_A):
            s.promoted = True
        a_cycle = ("loc-01", "loc-02", "loc-03")
        for s in self.skus:
            s.supplier_id = SUPPLIERS[(s.n - 1) % 4][0]
            if s.abc == "A":
                s.location_id = a_cycle[(s.n - 1) % 3]
            else:
                u = r.random()
                s.location_id = "loc-01" if u < 0.45 else "loc-02" if u < 0.78 else "loc-03"
            if s.abc == "A":
                s.mean, s.pack, s.moq, s.cost = r.uniform(5.0, 9.0), 12, 24, r.uniform(18, 60)
            elif s.abc == "B":
                s.mean, s.pack, s.moq, s.cost = r.uniform(0.25, 0.55), 6, 12, r.uniform(8, 25)
            elif s.intermittent:
                s.p_event, s.pack, s.moq, s.cost = r.uniform(0.05, 0.10), 6, 6, r.uniform(2, 14)
                s.mean = s.p_event * 2.2
            else:
                s.mean, s.pack, s.moq, s.cost = r.uniform(0.08, 0.20), 4, 8, r.uniform(2, 14)
            s.cost = round(s.cost, 2)
            quoted = self.sup[s.supplier_id][3]
            lt = quoted + 1
            sigma = math.sqrt(lt * (s.mean * 2.0 if s.intermittent else s.mean * (1 + s.mean / 6)))
            s.rop = max(math.ceil(s.mean * lt + Z_REORDER * sigma), s.pack)
            cover = s.moq if s.intermittent else math.ceil(s.mean * 14)
            s.target = pack_round_up(s.rop + max(cover, s.pack), s.pack)
        # promotions: three ten-day windows per promoted SKU, announced 14 days ahead, none in the last ten days
        for s in self.skus:
            if not s.promoted:
                continue
            starts = sorted(r.sample(range(30, NDAYS - PROMO_DAYS - 12, 7), 3))
            while any(b - a < 30 for a, b in zip(starts, starts[1:])):
                starts = sorted(r.sample(range(30, NDAYS - PROMO_DAYS - 12, 7), 3))
            for d0 in starts:
                planned = round(r.uniform(0.6, 1.0) if s.abc == "A" else r.uniform(0.3, 0.6), 2)
                realised = round(planned * r.uniform(0.7, 1.3), 4)
                s.promos.append({"start": d0, "end": d0 + PROMO_DAYS - 1, "planned": planned, "realised": realised})

    def make_latent(self) -> None:
        """Latent daily demand: negative binomial (gamma-mixed Poisson) with weekly and annual seasonality and promotion
        factors; intermittent SKUs draw an event with probability p_event and a lumpy size."""
        for s in self.skus:
            rng = self.rng_demand[s.n - 1]
            uplift = [0.0] * NDAYS
            for p in s.promos:
                for i in range(p["start"], p["end"] + 1):
                    uplift[i] = p["realised"]
            out = []
            for i in range(NDAYS):
                d = day_of(i)
                f = DOW[d.weekday()] * (1 + 0.10 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 80) / 365))
                f *= 1 + uplift[i]
                if s.intermittent:
                    out.append((1 + poisson(rng, 1.2)) if rng.random() < min(1.0, s.p_event * f) else 0)
                else:
                    lam = s.mean * f * rng.gammavariate(8, 1 / 8)
                    out.append(poisson(rng, lam))
            s.latent = out

    # ---- supply simulation ----------------------------------------------------------------------------------------
    def simulate(self) -> dict[str, Any]:
        r = self.rng_sim
        skus = self.skus
        loc_target: dict[str, int] = {}
        for s in skus:
            loc_target[s.location_id] = loc_target.get(s.location_id, 0) + s.target
        capacity = {l[0]: math.ceil(CAPACITY_FACTOR[l[0]] * loc_target.get(l[0], 0)) for l in LOCATIONS}
        init_sum: dict[str, float] = {}
        for s in skus:
            init_sum[s.location_id] = init_sum.get(s.location_id, 0) + 0.9 * s.target
        scale = {l: min(1.0, 0.8 * capacity[l] / v) for l, v in init_sum.items()}
        movements: list[dict] = []      # without ids yet
        sales: list[dict] = []
        receipts: list[dict] = []
        lost: list[dict] = []
        backorders: list[dict] = []
        pos: list[dict] = []
        lines: list[dict] = []
        for s in skus:
            q = max(s.pack, int(0.9 * s.target * scale[s.location_id]) // s.pack * s.pack)
            s.stock = q
            movements.append({"product_id": s.product_id, "location_id": s.location_id, "quantity_delta": q,
                              "event_at": OPENING, "movement_type": "adjustment", "_rank": -1})
        arrivals: dict[int, list[dict]] = {}
        loc_stock = {l[0]: 0 for l in LOCATIONS}
        loc_order = {l[0]: 0 for l in LOCATIONS}
        for s in skus:
            loc_stock[s.location_id] += s.stock
        loc_util = {l[0]: [] for l in LOCATIONS}
        loc_commit = {l[0]: [] for l in LOCATIONS}
        blocked = {l[0]: 0 for l in LOCATIONS}
        closed_partial_left = 2
        shortship_left = 4
        counters = {"po": 0, "line": 0, "bo": 0, "ls": 0}
        closed_first_day = (date(2026, 3, 1) - START).days

        for i in range(NDAYS):
            d = day_of(i)
            # 1. receipts
            for ev in arrivals.pop(i, []):
                s, ln = ev["sku"], ev["line"]
                s.stock += ev["qty"]
                s.on_order -= ev["qty"]
                loc_stock[s.location_id] += ev["qty"]
                loc_order[s.location_id] -= ev["qty"]
                ln["received"] += ev["qty"]
                at = ts(d, 8)
                receipts.append({"po_line_id": ln["po_line_id"], "location_id": s.location_id,
                                 "received_quantity": ev["qty"], "received_at": at, "_part": ev["part"]})
                movements.append({"product_id": s.product_id, "location_id": s.location_id, "quantity_delta": ev["qty"],
                                  "event_at": at, "movement_type": "receipt", "_rank": 0})
            po_today: dict[str, dict] = {}
            for s in skus:
                # 2. backlog fills (first from the stock that just arrived)
                if s.open_bo:
                    for bo in list(s.open_bo):
                        if s.stock >= bo["quantity"]:
                            s.stock -= bo["quantity"]
                            loc_stock[s.location_id] -= bo["quantity"]
                            bo["closed_at"] = ts(d, 11, 59, 59)
                            s.open_bo.remove(bo)
                            movements.append({"product_id": s.product_id, "location_id": s.location_id,
                                              "quantity_delta": -bo["quantity"], "event_at": ts(d, 11, 59, 59),
                                              "movement_type": "sale", "_rank": 1, "_fill": bo["backorder_id"]})
                # 3. demand
                dem = s.latent[i]
                sold = min(s.stock, dem)
                if sold:
                    s.stock -= sold
                    loc_stock[s.location_id] -= sold
                    s.observed[i] = sold
                    sales.append({"product_id": s.product_id, "location_id": s.location_id, "sold_at": ts(d, 12),
                                  "quantity": sold})
                    movements.append({"product_id": s.product_id, "location_id": s.location_id, "quantity_delta": -sold,
                                      "event_at": ts(d, 12), "movement_type": "sale", "_rank": 1})
                unmet = dem - sold
                if unmet:
                    s.stockout_days.append(i)
                    if s.location_id == BACKLOG_LOCATION:
                        counters["bo"] += 1
                        bo = {"backorder_id": f"bo-{counters['bo']:05d}", "product_id": s.product_id,
                              "location_id": s.location_id, "quantity": unmet, "opened_at": ts(d, 12),
                              "closed_at": None, "scenario_id": None}
                        backorders.append(bo)
                        s.open_bo.append(bo)
                    else:
                        counters["ls"] += 1
                        lost.append({"lost_sale_id": f"ls-{counters['ls']:05d}", "product_id": s.product_id,
                                     "location_id": s.location_id, "quantity": unmet, "occurred_at": ts(d, 12),
                                     "scenario_id": None})
                # 4. review
                position = s.stock + s.on_order - sum(b["quantity"] for b in s.open_bo)
                if position >= s.rop:
                    continue
                qty = pack_round_up(max(s.target - position, s.moq), s.pack)
                loc = s.location_id
                room = capacity[loc] - loc_stock[loc] - loc_order[loc]
                if qty > room:
                    qty = max(room, 0) // s.pack * s.pack
                    if qty < s.moq:
                        blocked[loc] += 1
                        continue
                sup = self.sup[s.supplier_id]
                po = po_today.get(sup[0])
                if po is None:
                    counters["po"] += 1
                    late = r.random() < sup[4]
                    delay = r.randint(1, 7) if late else 0
                    arr = arrival_date(d, sup[3] + delay, sup[2])
                    po = {"purchase_order_id": f"po-{counters['po']:04d}", "supplier_id": sup[0],
                          "ordered_at": ts(d, 17), "ordered_date": d, "status": "confirmed", "currency": "USD",
                          "cancelled": r.random() < 0.015, "arrival": arr, "late": late, "delay": delay, "lines": []}
                    po_today[sup[0]] = po
                    pos.append(po)
                counters["line"] += 1
                cost = s.cost
                if COST_STEP[2] == s.supplier_id and d >= COST_STEP[0]:
                    cost = round(s.cost * (1 + COST_STEP[1]), 2)
                ln = {"po_line_id": f"pol-{counters['line']:05d}", "purchase_order_id": po["purchase_order_id"],
                      "product_id": s.product_id, "ordered_quantity": qty, "unit_cost": money(cost), "received": 0,
                      "sku": s, "mode": "full", "po": po}
                po["lines"].append(ln)
                lines.append(ln)
                loc_order[loc] += qty
                if po["cancelled"]:
                    loc_order[loc] -= qty        # a cancelled order is never pending
                    continue
                parts = [(qty, po["arrival"], "1")]
                if (closed_partial_left and sup[0] == "sup-03" and i >= closed_first_day and qty >= 96):
                    closed_partial_left -= 1
                    first = max(s.pack, int(qty * 0.65) // s.pack * s.pack)
                    parts = [(first, po["arrival"], "1")]
                    ln["mode"] = "closed_partial"
                    loc_order[loc] -= qty - first     # the remainder is abandoned: never counted as on order
                    s.on_order += first
                    po["force_closed"] = True
                elif i >= NDAYS - RECENT_OPEN_DAYS and shortship_left and qty >= 2 * s.pack and r.random() < 0.15:
                    shortship_left -= 1
                    first = max(s.pack, int(qty * 0.6) // s.pack * s.pack)
                    parts = [(first, po["arrival"], "1")]   # the remainder stays open (on order)
                    ln["mode"] = "short_shipped_open"
                    s.on_order += qty
                elif qty >= 2 * s.pack and r.random() < 0.08:
                    first = max(s.pack, int(qty * r.uniform(0.5, 0.8)) // s.pack * s.pack)
                    second = arrival_date(po["arrival"], r.randint(1, 5), sup[2])
                    parts = [(first, po["arrival"], "1"), (qty - first, second, "2")]
                    ln["mode"] = "split"
                    s.on_order += qty
                else:
                    s.on_order += qty
                for q_, adate, part in parts:
                    ai = (adate - START).days
                    if ai < NDAYS:
                        arrivals.setdefault(ai, []).append({"sku": s, "line": ln, "qty": q_, "part": part})
            for l in loc_util:
                loc_util[l].append(loc_stock[l])
                loc_commit[l].append(loc_stock[l] + loc_order[l])
        return {"movements": movements, "sales": sales, "receipts": receipts, "lost_sales": lost,
                "backorders": backorders, "pos": pos, "lines": lines, "capacity": capacity, "loc_util": loc_util, "loc_commit": loc_commit,
                "blocked": blocked}

    # ---- assembling the entities ----------------------------------------------------------------------------------
    def build(self) -> dict[str, Any]:
        self.setup_skus()
        self.make_latent()
        sim = self.simulate()
        r = self.rng_extra
        ents: dict[str, list[dict]] = {}
        skus = self.skus
        by_pid = {s.product_id: s for s in skus}

        ents["suppliers"] = [{"supplier_id": s[0], "supplier_name": s[1], "calendar_id": s[2], "quoted_lead_days": s[3],
                              "active": True} for s in SUPPLIERS]
        ents["locations"] = [{"location_id": l[0], "location_name": l[1], "timezone": l[2],
                              "storage_capacity": sim["capacity"][l[0]], "active": True} for l in LOCATIONS]
        ents["calendar_closures"] = [{"closure_id": CLOSURE[0], "calendar_id": CLOSURE[1],
                                      "closed_from": CLOSURE[2].isoformat(), "closed_to": CLOSURE[3].isoformat()}]
        ents["products"] = [{"product_id": s.product_id, "sku": s.sku, "unit_cost": money(s.cost), "pack_size": s.pack,
                             "minimum_order_quantity": s.moq, "abc_class": s.abc}
                            for s in skus]   # supplier lives on replenishment_params (ingest loads products first)
        ents["replenishment_params"] = [{"product_id": s.product_id, "location_id": s.location_id,
                                         "reorder_point": s.rop, "target_position": s.target,
                                         "supplier_id": s.supplier_id} for s in skus]
        ents["cost_versions"] = [
            {"cost_version_id": f"cv-{k:03d}", "product_id": s.product_id,
             "unit_cost": money(round(s.cost * (1 + COST_STEP[1]), 2)), "effective_from": ts(COST_STEP[0])}
            for k, s in enumerate([s for s in skus if s.supplier_id == COST_STEP[2]], 1)]
        ents["policy_scenarios"] = [
            {"scenario_id": f"sc-{t[2:]}-{'lost' if u == 'lost_sale' else 'backlog'}",
             "scenario_name": f"service {t} / {u.replace('_', ' ')}", "service_target": t, "unmet_policy": u,
             "seed": self.seed, "warmup_days": 28, "replications": 100}
            for t in SERVICE_TARGETS for u in UNMET_POLICIES]
        ents["promotions"] = []
        for s in skus:
            for p in s.promos:
                d0, d1 = day_of(p["start"]), day_of(p["end"])
                ents["promotions"].append({
                    "promotion_id": f"promo-{len(ents['promotions']) + 1:03d}", "product_id": s.product_id,
                    "location_id": s.location_id, "starts_at": ts(d0), "ends_at": ts(d1, 23, 59, 59),
                    "planned_uplift": f"{p['planned']:.2f}", "announced_at": ts(d0 - timedelta(days=14), 9),
                    "realised_uplift": f"{p['realised']:.4f}"})

        # purchase orders, lines, receipts ------------------------------------------------------------------------
        po_rows, line_rows = [], []
        for po in sim["pos"]:
            complete = all(ln["received"] >= ln["ordered_quantity"] for ln in po["lines"])
            status = "cancelled" if po["cancelled"] else "closed" if (po.get("force_closed") or complete) else "confirmed"
            po["final_status"] = status
            po_rows.append({"purchase_order_id": po["purchase_order_id"], "supplier_id": po["supplier_id"],
                            "ordered_at": po["ordered_at"], "status": status, "currency": "USD"})
            for ln in po["lines"]:
                line_rows.append({"po_line_id": ln["po_line_id"], "purchase_order_id": ln["purchase_order_id"],
                                  "product_id": ln["product_id"], "ordered_quantity": ln["ordered_quantity"],
                                  "unit_cost": ln["unit_cost"]})
        sim["receipts"].sort(key=lambda x: (x["received_at"], x["po_line_id"], x["_part"]))
        receipt_rows = []
        for k, x in enumerate(sim["receipts"], 1):
            receipt_rows.append({"receipt_id": f"rcpt-{k:05d}", "po_line_id": x["po_line_id"],
                                 "location_id": x["location_id"], "received_quantity": x["received_quantity"],
                                 "received_at": x["received_at"]})

        # injected: a receipt dated before its order (typed month), on a fresh sup-01 order near the cut --------------
        pick = next(s for s in skus if s.supplier_id == "sup-01" and s.abc == "B")
        n_po, n_line = len(po_rows) + 1, len(line_rows) + 1
        bad_po = {"purchase_order_id": f"po-{n_po:04d}", "supplier_id": "sup-01", "ordered_at": "2026-09-22T09:00:00Z",
                  "status": "confirmed", "currency": "USD"}
        bad_line = {"po_line_id": f"pol-{n_line:05d}", "purchase_order_id": bad_po["purchase_order_id"],
                    "product_id": pick.product_id, "ordered_quantity": pick.pack * 4, "unit_cost": money(pick.cost)}
        bad_receipt = {"receipt_id": f"rcpt-{len(receipt_rows) + 1:05d}", "po_line_id": bad_line["po_line_id"],
                       "location_id": pick.location_id, "received_quantity": bad_line["ordered_quantity"],
                       "received_at": "2026-09-12T08:00:00Z"}
        po_rows.append(bad_po)
        line_rows.append(bad_line)
        receipt_rows.append(bad_receipt)
        ents["purchase_orders"], ents["purchase_order_lines"], ents["receipts"] = po_rows, line_rows, receipt_rows

        # movements and sales with ids -----------------------------------------------------------------------------
        mv = sorted(sim["movements"], key=lambda m: (m["event_at"], m["_rank"], m["product_id"], m["location_id"]))
        move_rows = []
        for k, m in enumerate(mv, 1):
            move_rows.append({"movement_id": f"mv-{k:06d}", "product_id": m["product_id"], "location_id": m["location_id"],
                              "quantity_delta": m["quantity_delta"], "event_at": m["event_at"],
                              "movement_type": m["movement_type"]})
        sale_rows = []
        for k, x in enumerate(sorted(sim["sales"], key=lambda x: (x["sold_at"], x["product_id"])), 1):
            sale_rows.append({"sale_id": f"sale-{k:06d}", "product_id": x["product_id"], "location_id": x["location_id"],
                              "sold_at": x["sold_at"], "quantity": x["quantity"]})
        # injected: exact replays of three movement ids (two sales, one receipt), appended at the end of the file
        sale_idx = [k for k, m in enumerate(move_rows) if m["movement_type"] == "sale"]
        rcpt_idx = [k for k, m in enumerate(move_rows) if m["movement_type"] == "receipt"]
        dup_src = [move_rows[sale_idx[len(sale_idx) // 5]], move_rows[sale_idx[len(sale_idx) * 3 // 5]],
                   move_rows[rcpt_idx[len(rcpt_idx) // 2]]]
        dup_rows = [dict(m) for m in dup_src]
        move_rows.extend(dup_rows)
        ents["inventory_movements"], ents["sales"] = move_rows, sale_rows
        ents["lost_sales"] = sim["lost_sales"]
        ents["backorders"] = [{k: v for k, v in b.items()} for b in sim["backorders"]]

        # latent demand (positive days) for class A, promoted and intermittent pairs ---------------------------------
        tracked = [s for s in skus if s.abc == "A" or s.promoted or s.intermittent]
        ents["latent_demand"] = [{"product_id": s.product_id, "location_id": s.location_id,
                                  "demand_date": day_of(i).isoformat(), "latent_quantity": q}
                                 for s in tracked for i, q in enumerate(s.latent) if q > 0]

        # reservations: a few released ones, and open ones against the closing stock -------------------------------
        ents["reservations"] = self.reservations(r, skus, ents)

        # forecasts ---------------------------------------------------------------------------------------------------
        self.forecasts(ents, skus)

        injections = self.injection_manifest(ents, sim, dup_rows, bad_po, bad_line, bad_receipt, by_pid)
        designed = self.designed(ents, sim, by_pid)
        events = self.injection_events(ents, sim, dup_rows, bad_line, bad_receipt, by_pid)
        for name in ENTITIES:
            assert name in ents, name
        return {"entities": ents, "injections": injections, "designed": designed, "events": events,
                "parameters": default_parameters(self.seed), "stats": self.stats(ents, sim)}

    def reservations(self, r: random.Random, skus: list[Sku], ents: dict) -> list[dict]:
        rows: list[dict] = []
        pairs = [s for s in skus if s.abc in "AB" and s.stock >= 20]
        for s in r.sample(pairs, 6):                          # open: reserved against stock at the cut
            q = max(1, int(s.stock * 0.25))
            rows.append({"reservation_id": f"res-{len(rows) + 1:03d}", "product_id": s.product_id,
                         "location_id": s.location_id, "quantity": q, "reserved_at": ts(date(2026, 9, 24 + len(rows) % 5), 10),
                         "released_at": None})
        for s in r.sample([s for s in skus if s.abc in "AB"], 10):   # released holds in the past
            d0 = START + timedelta(days=r.randint(40, NDAYS - 40))
            rows.append({"reservation_id": f"res-{len(rows) + 1:03d}", "product_id": s.product_id,
                         "location_id": s.location_id, "quantity": r.randint(3, 13),
                         "reserved_at": ts(d0, 10), "released_at": ts(d0 + timedelta(days=r.randint(3, 9)), 15)})
        return rows

    def forecasts(self, ents: dict, skus: list[Sku]) -> None:
        chosen = [s for s in skus if s.abc == "A"] + [s for s in skus if s.intermittent][:4] + \
                 [s for s in skus if s.abc == "B" and s.promoted][:2]
        runs, points = [], []
        for s in chosen:
            obs = s.observed
            for c in FORECAST_CUTOFFS:
                ci = (c - START).days
                hist = obs[:ci + 1]
                preds = self.models(hist, FORECAST_HORIZON)
                mae = {m: 0.0 for m in preds}
                for back in (7, 14, 21, 28):                          # rolling origins, seven-day horizon
                    o = ci - back
                    pr = self.models(obs[:o + 1], 7)
                    for m in pr:
                        mae[m] += sum(abs(obs[o + 1 + h] - pr[m][h]) for h in range(7)) / 7
                best = "seasonal_naive"
                for m in ("naive", "ewma"):
                    if mae[m] < mae["seasonal_naive"] and mae[m] < mae[best]:
                        best = m
                rid = f"fr-{len(runs) + 1:04d}"
                runs.append({"forecast_run_id": rid, "product_id": s.product_id, "location_id": s.location_id,
                             "cutoff": ts(c, 23, 59, 59), "horizon_days": FORECAST_HORIZON, "selected_model": best})
                for m in ("naive", "seasonal_naive", "ewma"):
                    for h in range(FORECAST_HORIZON):
                        points.append({"forecast_point_id": f"fp-{len(points) + 1:06d}", "forecast_run_id": rid,
                                       "model": m, "target_date": day_of(ci + 1 + h).isoformat(),
                                       "forecast_value": f"{preds[m][h]:.2f}"})
        ents["forecast_runs"], ents["forecast_points"] = runs, points

    @staticmethod
    def models(hist: list[int], h: int) -> dict[str, list[float]]:
        level = float(hist[0])
        for x in hist[1:]:
            level = 0.3 * x + 0.7 * level
        snaive = []
        for k in range(h):
            back = 7 * (-(-(k + 1) // 7))        # most recent same weekday inside the history
            snaive.append(float(hist[len(hist) - back + k]))
        return {"naive": [float(hist[-1])] * h, "seasonal_naive": snaive, "ewma": [level] * h}

    # ---- statistics used by the manifests -------------------------------------------------------------------------
    def stats(self, ents: dict, sim: dict) -> dict[str, Any]:
        return {"capacity_blocked_orders": sim["blocked"]}

    def supplier_lateness(self, ents: dict) -> dict[str, dict[str, int]]:
        orders = {o["purchase_order_id"]: o for o in ents["purchase_orders"]}
        lines = {l["po_line_id"]: l for l in ents["purchase_order_lines"]}
        out = {s[0]: {"eligible": 0, "late": 0} for s in SUPPLIERS}
        for rc in ents["receipts"]:
            o = orders[lines[rc["po_line_id"]]["purchase_order_id"]]
            if rc["received_at"] < o["ordered_at"]:
                continue
            sup = self.sup[o["supplier_id"]]
            od = date.fromisoformat(o["ordered_at"][:10])
            promised = arrival_date(od, sup[3], sup[2])
            out[sup[0]]["eligible"] += 1
            out[sup[0]]["late"] += 1 if date.fromisoformat(rc["received_at"][:10]) > promised else 0
        return out

    def designed(self, ents: dict, sim: dict, by_pid: dict) -> list[str]:
        late = self.supplier_lateness(ents)
        share = {k: v["late"] / v["eligible"] for k, v in late.items()}
        a_promoted = [s for s in self.skus if s.abc == "A" and s.promoted and s.location_id != BACKLOG_LOCATION]
        a_days = {s.product_id: len(s.stockout_days) for s in a_promoted}
        util = {l: max(sim["loc_util"][l]) / sim["capacity"][l] for l in sim["capacity"]}
        full = {l: sum(1 for v in sim["loc_commit"][l] if v >= 0.9 * sim["capacity"][l]) for l in sim["capacity"]}
        return [
            "class A SKUs with promotions show censoring during stockouts: observed sales fall below the published latent "
            "demand on stockout days (a lost_sale row records the gap); stockout days of the class A promoted pairs at "
            f"lost-sale locations: {json.dumps(a_days, sort_keys=True)} (synthetic).",
            f"supplier sup-03 is late on about 30 % of receipts ({share['sup-03']:.1%} of {late['sup-03']['eligible']}), "
            "against " + ", ".join(f"{k} {share[k]:.1%}" for k in sorted(share) if k != "sup-03") +
            " (late = received after the promised date counted on the supplier calendar; synthetic).",
            f"location loc-02 is capacity-bound: storage_capacity is {CAPACITY_FACTOR['loc-02']:.0%} of the summed "
            f"target positions, so orders are cut to the room left ({sim['blocked']['loc-02']} reviews blocked; "
            f"on hand + on order was at least 90 % of capacity on {full['loc-02']} of {NDAYS} days vs {full['loc-01']} "
            f"at loc-01 and {full['loc-03']} at loc-03; peak on-hand {util['loc-02']:.0%} of capacity vs "
            f"{util['loc-01']:.0%} and {util['loc-03']:.0%}; synthetic).",
        ]

    # ---- injection manifest -----------------------------------------------------------------------------------------
    def injection_manifest(self, ents: dict, sim: dict, dup_rows: list[dict], bad_po: dict, bad_line: dict,
                           bad_receipt: dict, by_pid: dict) -> dict[str, Any]:
        lines = {l["po_line_id"]: l for l in ents["purchase_order_lines"]}
        orders = {o["purchase_order_id"]: o for o in ents["purchase_orders"]}
        closed_partial = []
        for l in sim["lines"]:
            if l["mode"] == "closed_partial":
                got = l["received"]
                closed_partial.append({"po_line_id": l["po_line_id"], "purchase_order_id": l["purchase_order_id"],
                                       "ordered": l["ordered_quantity"], "received": got})
        c_from, c_to = CLOSURE[2], CLOSURE[3]
        span = []
        rc_by_line: dict[str, list[dict]] = {}
        for rc in ents["receipts"]:
            rc_by_line.setdefault(rc["po_line_id"], []).append(rc)
        for o in ents["purchase_orders"]:
            if o["supplier_id"] != "sup-02" or o["status"] == "cancelled":
                continue
            od = date.fromisoformat(o["ordered_at"][:10])
            for l in ents["purchase_order_lines"]:
                if l["purchase_order_id"] != o["purchase_order_id"]:
                    continue
                for rc in rc_by_line.get(l["po_line_id"], []):
                    rd = date.fromisoformat(rc["received_at"][:10])
                    if od < c_from and rd > c_to:
                        span.append({"purchase_order_id": o["purchase_order_id"], "po_line_id": l["po_line_id"],
                                     "ordered": od.isoformat(), "received": rd.isoformat(),
                                     "calendar_days": (rd - od).days,
                                     "promised": arrival_date(od, 12, "cal-02").isoformat()})
        assert span, "no sup-02 lead time spans the closure"
        inter = [s for s in self.skus if s.intermittent]
        zero_share = {s.product_id: round(1 - sum(1 for q in s.observed if q) / NDAYS, 3) for s in inter}
        reserved_open = [x for x in ents["reservations"] if x["released_at"] is None]
        inj = [
            {"id": "INJ-01", "test": "P03-TEST-04", "entity": "inventory_movements", "location": "entity_files",
             "record_ids": [m["movement_id"] for m in dup_rows],
             "description": "3 exact replays of already posted movement ids (2 sales, 1 receipt) appended at the end of "
                            "inventory_movements.",
             "expected_handling": "ingest rejects each replay with DUPLICATE_MOVEMENT_ID and keeps the first occurrence; "
                                  "on hand is unchanged."},
            {"id": "INJ-02", "test": "P03-TEST-11", "entity": "receipts", "location": "entity_files",
             "record_ids": [bad_receipt["receipt_id"]],
             "description": f"receipt {bad_receipt['receipt_id']} is dated {bad_receipt['received_at']}, ten days before "
                            f"its order {bad_po['purchase_order_id']} ({bad_po['ordered_at']}); no movement was posted.",
             "expected_handling": "ingest rejects it with RECEIPT_BEFORE_ORDER; the line stays open and on order."},
            {"id": "INJ-03", "test": "P03-TEST-07", "entity": "purchase_orders", "location": "entity_files+events",
             "record_ids": [c["po_line_id"] for c in closed_partial], "detail": closed_partial,
             "description": "2 sup-03 purchase orders are status closed although a line was only partly received "
                            "(about 65 % of the ordered quantity, the remainder never arrived).",
             "expected_handling": "the line stays open (ordered - received > 0) and is listed in "
                                  "partially_received_open_lines; the status flag does not complete it."},
            {"id": "INJ-04", "test": "P03-TEST-05", "entity": "calendar_closures", "location": "entity_files",
             "record_ids": [CLOSURE[0]] + sorted({s["purchase_order_id"] for s in span}),
             "description": f"sup-02 (calendar cal-02) is closed {c_from} .. {c_to}; {len(span)} receipts of orders "
                            "placed before the closure arrive after it, so their calendar lead time spans the closure.",
             "detail": span[:6],
             "expected_handling": "the promised date counts only open days, so a receipt on the extended date is on "
                                  "time; counting calendar days would call it late."},
            {"id": "INJ-05", "test": "P03-TEST-06", "entity": "sales", "location": "entity_files",
             "record_ids": [s.product_id for s in inter], "detail": {"zero_demand_day_share": zero_share},
             "description": "12 intermittent SKUs sell on only about 5-10 % of days, so most rolling-origin folds have "
                            "zero actual demand.",
             "expected_handling": "WAPE is null on a fold whose actuals sum to 0; the zero-demand folds are disclosed."},
            {"id": "INJ-06", "test": "P03-TEST-12", "entity": "cost_versions", "location": "entity_files",
             "record_ids": [c["cost_version_id"] for c in ents["cost_versions"]],
             "description": f"one unit-cost step: +{COST_STEP[1]:.0%} on every sup-04 product effective "
                            f"{COST_STEP[0].isoformat()}, inside any valuation period that spans it (for example "
                            "2026-01-01 .. 2026-03-31).",
             "expected_handling": "each day is valued at the cost in force that day; PO line costs carry the cost at order."},
            {"id": "INJ-07", "test": "P03-TEST-10", "entity": "reservations", "location": "entity_files+events",
             "record_ids": [x["reservation_id"] for x in reserved_open],
             "description": "6 open reservations of 25 % of closing stock; a naive position would subtract them twice "
                            "(once in available, once in the position).",
             "expected_handling": "position = on hand + on order - backorders; reserved only reduces available."},
            {"id": "INJ-08", "test": "P03-TEST-04", "entity": "inventory_movements", "location": "events",
             "record_ids": ["EV-01"], "description": "a movement id re-posted with a different quantity.",
             "expected_handling": "DUPLICATE_MOVEMENT_CONFLICT: every occurrence is rejected."},
            {"id": "INJ-09", "test": "P03-TEST-05", "entity": "receipts", "location": "events",
             "record_ids": ["EV-02", "EV-06"],
             "description": "an arrival before the order date and an arrival before the quoted lead time (replay).",
             "expected_handling": "RECEIPT_BEFORE_ORDER (422) and RECEIPT_BEFORE_LEAD_TIME (422)."},
            {"id": "INJ-10", "test": "P03-TEST-09", "entity": "policy_scenarios", "location": "events",
             "record_ids": ["EV-05"], "description": "two policies with different seeds are compared (attempt).",
             "expected_handling": "POLICY_SEED_MISMATCH: common random numbers need one seed."},
            {"id": "INJ-11", "test": "P03-TEST-03", "entity": "replenishment_params", "location": "events",
             "record_ids": ["EV-07"],
             "description": "pack rounding applied before the minimum order quantity gives an order below MOQ.",
             "expected_handling": "MOQ first, then pack rounding: max(raw, MOQ) rounded up to a whole pack."},
        ]
        return {"list": inj}

    # ---- replay-only events ---------------------------------------------------------------------------------------
    def injection_events(self, ents: dict, sim: dict, dup_rows: list[dict], bad_line: dict, bad_receipt: dict,
                         by_pid: dict) -> list[dict]:
        version = f"ss-{self.seed}-{DATE_TAG}"
        hdr = {"X-Actor-Id": "plan-1", "X-Actor-Role": "planner"}
        env = lambda n: {"request_id": f"ev-{n}", "dataset_version": version, "idempotency_key": f"ev-{n}"}  # noqa: E731
        orders = {o["purchase_order_id"]: o for o in ents["purchase_orders"]}
        lines = {l["po_line_id"]: l for l in ents["purchase_order_lines"]}
        base = dup_rows[0]
        ev: list[dict] = []
        ev.append({"event_id": "EV-01", "injection": "INJ-08", "command": "load-movements", "headers": hdr,
                   "input": {**env("01"), "input": {"movements": [dict(base), {**base, "quantity_delta": base["quantity_delta"] - 1}]}},
                   "expected_reason": "DUPLICATE_MOVEMENT_CONFLICT",
                   "expected_handling": "both rows are rejected (same id, different payloads); nothing is posted"})
        confirmed = next(l for l in ents["purchase_order_lines"]
                         if orders[l["purchase_order_id"]]["status"] == "confirmed" and l["po_line_id"] != bad_line["po_line_id"])
        co = orders[confirmed["purchase_order_id"]]
        cp = by_pid[confirmed["product_id"]]
        od = date.fromisoformat(co["ordered_at"][:10])
        ev.append({"event_id": "EV-02", "injection": "INJ-09", "command": "simulate-arrival", "headers": hdr,
                   "input": {**env("02"), "input": {"po_line_id": confirmed["po_line_id"], "location_id": cp.location_id,
                                                    "at": ts(od - timedelta(days=3), 8), "quantity": cp.pack}},
                   "expected_status": 422, "expected_reason": "RECEIPT_BEFORE_ORDER",
                   "expected_handling": "refused: a receipt cannot be dated before its order"})
        cl = next(l for l in sim["lines"] if l["mode"] == "closed_partial")
        ev.append({"event_id": "EV-03", "injection": "INJ-03", "command": "sql",
                   "statement": f"UPDATE purchase_orders SET status = 'closed' WHERE purchase_order_id = '{cl['purchase_order_id']}'",
                   "input": {"po_line_id": cl["po_line_id"], "ordered": cl["ordered_quantity"], "received": cl["received"]},
                   "expected_reason": "PARTIAL_RECEIPT_NOT_COMPLETE",
                   "expected_handling": "the status flag is a label only: line_status stays 'open' because "
                                        "ordered - received > 0, and the line is listed in partially_received_open_lines"})
        open_res = next(x for x in ents["reservations"] if x["released_at"] is None)
        rs = by_pid[open_res["product_id"]]
        on_hand = rs.stock
        got: dict[str, int] = {}
        for rc in ents["receipts"]:
            if rc["receipt_id"] != bad_receipt["receipt_id"]:
                got[rc["po_line_id"]] = got.get(rc["po_line_id"], 0) + rc["received_quantity"]
        on_order = sum(max(l["ordered_quantity"] - got.get(l["po_line_id"], 0), 0) for l in ents["purchase_order_lines"]
                       if l["product_id"] == rs.product_id and orders[l["purchase_order_id"]]["status"] == "confirmed")
        bo = sum(b["quantity"] for b in rs.open_bo)
        reserved = sum(x["quantity"] for x in ents["reservations"] if x["released_at"] is None
                       and x["product_id"] == rs.product_id and x["location_id"] == rs.location_id)
        ev.append({"event_id": "EV-04", "injection": "INJ-07", "command": "reserved-double-subtraction-attempt",
                   "input": {"product_id": rs.product_id, "location_id": rs.location_id, "as_of": AS_OF},
                   "expected": {"on_hand": on_hand, "on_order": on_order, "backorders": bo, "reserved": reserved,
                                "available": on_hand - reserved, "inventory_position": on_hand + on_order - bo},
                   "forbidden": {"inventory_position": on_hand + on_order - bo - reserved},
                   "expected_handling": "position does not subtract reserved; only available does (P03-TEST-10)"})
        a, b = ents["policy_scenarios"][0], ents["policy_scenarios"][1]
        ev.append({"event_id": "EV-05", "injection": "INJ-10", "command": "compare-policies", "headers": hdr,
                   "setup": {"policy_scenarios": [{**a, "scenario_id": "sc-x-seed-a", "seed": self.seed},
                                                   {**b, "scenario_id": "sc-x-seed-b", "seed": self.seed + 1}]},
                   "input": {**env("05"), "input": {"scenario_ids": ["sc-x-seed-a", "sc-x-seed-b"],
                                                    "product_id": rs.product_id, "location_id": rs.location_id}},
                   "expected_status": 422, "expected_reason": "POLICY_SEED_MISMATCH",
                   "expected_handling": "refused: scenarios compared on common random numbers must declare one seed"})
        s1 = next(l for l in ents["purchase_order_lines"] if orders[l["purchase_order_id"]]["supplier_id"] == "sup-01"
                  and orders[l["purchase_order_id"]]["status"] == "confirmed" and l["po_line_id"] != bad_line["po_line_id"])
        o1 = orders[s1["purchase_order_id"]]
        p1 = by_pid[s1["product_id"]]
        d1 = date.fromisoformat(o1["ordered_at"][:10])
        ev.append({"event_id": "EV-06", "injection": "INJ-09", "command": "simulate-arrival", "headers": hdr,
                   "input": {**env("06"), "input": {"po_line_id": s1["po_line_id"], "location_id": p1.location_id,
                                                    "at": ts(d1 + timedelta(days=1), 8), "quantity": p1.pack}},
                   "expected_status": 422, "expected_reason": "RECEIPT_BEFORE_LEAD_TIME",
                   "expected_handling": "refused: sup-01 quotes 5 days; the earliest receipt is the 5th open day"})
        ev.append({"event_id": "EV-07", "injection": "INJ-11", "command": "calculate-replenishment-check",
                   "input": {"position": 105, "reorder_point": 110, "target_position": 115, "moq": 50, "pack_size": 24},
                   "wrong": {"order_quantity": 24, "how": "pack rounding of the raw 10 without applying the MOQ"},
                   "expected": {"raw_order": 10, "order_after_moq": 50, "order_quantity": 72},
                   "expected_handling": "MOQ before pack rounding: max(10, 50) = 50, rounded up to 72; never 24 (below MOQ)"})
        return ev


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


def write_all(seed: int, out: Path, data_dir: Path) -> dict[str, Any]:
    built = build(seed)
    ents = built["entities"]
    version = f"ss-{seed}-{DATE_TAG}"
    dhash = dataset_hash(ents)
    out.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ENTITIES:
        (out / f"{name}.json").write_text(entity_text(name, version, ents[name]))
    inj_manifest = {"dataset_version": version, "dataset_hash": dhash, "seed": seed,
                    "contract_version": CONTRACT_VERSION, "injections": built["injections"]["list"],
                    "designed_relationships": built["designed"], "events_file": "data/injection-events.json"}
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
    return manifest


def shape_check(seed: int) -> int:
    golden = json.loads((APP_ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
    ents = build(seed)["entities"]
    bad = 0
    for name, g_rows in golden.items():
        if not isinstance(g_rows, list) or name not in ents or not g_rows or not isinstance(g_rows[0], dict):
            continue
        want = set(g_rows[0])
        for row in ents[name]:
            if not want <= set(row):
                print(f"SHAPE MISMATCH {name}: {sorted(set(row) ^ want)}")
                bad += 1
                break
        else:
            print(f"ok {name}: {sorted(want)} (+ {sorted(set(ents[name][0]) - want)})")
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
