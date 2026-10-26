#!/usr/bin/env python3
"""Revenue Atlas synthetic data generator (P01-WORK-03, docs/data-generator.md).

Stdlib only. Deterministic: one ``random.Random(seed)`` stream and integer-cent money, so the
same seed and parameters give byte-identical entity files and the same ``dataset_hash``.

    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --profile golden-shape-check

Writes ``<entity>.json`` (``{"entity", "dataset_version", "rows"}``) and ``manifest.json`` to
``--out``; ``injection-manifest.json`` and ``injection-events.json`` to ``--data-dir`` (default
``data/``) and a copy of the injection manifest to ``--out``.
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
WINDOW_START = date(2024, 10, 1)
WINDOW_END = date(2026, 9, 30)          # inclusive
ORDER_DATE_LAST = date(2026, 9, 22)     # leaves room for two shipments inside the window

ENTITIES = ("customers", "products", "orders", "order_lines", "discounts", "shipments",
            "shipment_lines", "returns", "cost_versions", "exchange_rates", "quotas")
REGIONS = ("reg-north", "reg-south", "reg-east", "reg-west")
SEGMENTS = {"smb": 26, "mid_market": 14, "enterprise": 8}
SEGMENT_WEIGHT = {"smb": 1.0, "mid_market": 2.2, "enterprise": 5.0}
SEGMENT_QTY = {"smb": (1, 8), "mid_market": (4, 24), "enterprise": (10, 60)}
FOREIGN = {"EUR": 6, "CAD": 4}           # customers per currency (10 of 48, about 20 %)
PRICE_FACTOR = {"USD": 1.0, "EUR": 0.92, "CAD": 1.36}  # fixed list-price conversion, never changes
REASONS = (("volume", 0.35, (0.06, 0.12)), ("promo", 0.30, (0.05, 0.10)),
           ("goodwill", 0.15, (0.02, 0.06)), ("price_match", 0.20, (0.04, 0.08)))
WEST_START = date(2026, 3, 1)
WEST_PROB = 0.55                         # vs 0.35 elsewhere
WEST_PCT = (0.08, 0.13)                  # promo, vs a blended mean of about 0.072 elsewhere
FIX_STEP_DATE = date(2026, 1, 1)
COST_BOUNDS = (date(2024, 10, 1), date(2025, 4, 1), date(2025, 10, 1), date(2026, 4, 1))

# category -> (sku prefix, price range USD, popularity, cost/price ratio, units of measure, names)
CATEGORIES: dict[str, tuple[str, tuple[int, int], float, float, tuple[str, ...], tuple[str, ...]]] = {
    "cat-fixtures": ("FIX", (45, 320), 1.2, 0.58, ("each",),
                     ("LED High Bay Light 150W", "Linear Strip Fixture 4ft", "Surface Mount Panel 600mm",
                      "Emergency Exit Sign Unit", "Pendant Task Lamp Industrial", "Floodlight Wall Pack 80W")),
    "cat-apparel": ("APP", (12, 90), 1.0, 0.55, ("each", "pair"),
                    ("Hi-Vis Work Jacket", "Insulated Bib Overall", "Cut Resistant Glove Pair",
                     "Flame Resistant Coverall", "Rain Shell Parka", "Steel Toe Work Boot")),
    "cat-tools": ("TLS", (25, 260), 1.0, 0.60, ("each", "kit"),
                  ("Cordless Drill Driver Kit", "Torque Wrench 3/8in", "Laser Distance Measure",
                   "Precision Screwdriver Set 32pc", "Oscillating Multi-Tool", "Pipe Cutter Heavy Duty")),
    "cat-packaging": ("PKG", (3, 40), 1.4, 0.52, ("case", "roll", "pack"),
                      ("Corrugated Box 12x12x12 Bundle", "Stretch Film Roll 18in", "Packing Tape 48mm Case",
                       "Bubble Wrap 12in Roll", "Void Fill Paper Pack", "Poly Mailer 10x13 Pack")),
    "cat-safety": ("SAF", (8, 120), 0.9, 0.57, ("each", "box"),
                   ("Safety Glasses Anti-Fog", "Half Mask Respirator", "Ear Muff Noise Reducing",
                    "First Aid Kit 50 Person", "Fire Extinguisher ABC 5lb", "Hard Hat Vented")),
    "cat-office": ("OFC", (4, 60), 1.1, 0.62, ("each", "pack"),
                   ("Ergonomic Task Chair", "Sit Stand Desk Converter", "Label Printer Thermal",
                    "Document Shredder 12 Sheet", "Whiteboard 4x6 Magnetic", "Monitor Arm Dual")),
}
LONG_SKU_SUFFIX = {"cat-apparel": "-ARC-RATED-FLAME-RESISTANT-COVERALL-WITH-REFLECTIVE-TAPE-AND-DETACHABLE-HOOD-SIZE-XL",
                   "cat-safety": "-FULL-FACE-POWERED-AIR-PURIFYING-RESPIRATOR-KIT-WITH-SPARE-FILTERS-AND-CARRY-CASE"}

NAME_A = ("Marlowe", "Alder", "Cinder", "Dunmore", "Elmstead", "Fenwick", "Garnet", "Halbrook", "Ironvale",
          "Juniper", "Kestrel", "Lindenhurst", "Moorfield", "Norvale", "Oakhollow", "Pinegate", "Quarry",
          "Ridgemont", "Stonebrook", "Thornley", "Umberfield", "Valewood", "Whitcombe", "Yarrow")
NAME_B = ("Ridge", "Harbor", "Summit", "Meadow", "Canyon", "Lakeside", "Prairie", "Foundry")
NAME_C = ("Supply Co", "Industrial LLC", "Distribution Inc", "Fabrication Ltd", "Facilities Group",
          "Trading Company", "Logistics Corp", "Works Partners")
LONG_NAMES = (
    "Consolidated Regional Wholesale Distribution and Industrial Supply Partnership of the Great Lakes",
    "International Association of Municipal Facilities Maintenance and Public Works Procurement Cooperatives",
    "Northern Territories Mining, Forestry and Heavy Equipment Contractors Purchasing Consortium Limited",
    "Metropolitan Hospital and Educational Campus Facilities Services Shared Procurement Authority",
)


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}{c // 100}.{c % 100:02d}"


def rate_s(micro: int) -> str:
    return f"{micro // 1_000_000}.{micro % 1_000_000:06d}"


def half_up_div(num: int, den: int) -> int:
    return (2 * num + den) // (2 * den)


def largest_remainder(total: int, weights: list[tuple[str, int]]) -> dict[str, int]:
    wsum = sum(w for _, w in weights)
    floors = {k: total * w // wsum for k, w in weights}
    rems = {k: total * w % wsum for k, w in weights}
    left = total - sum(floors.values())
    for k in sorted(floors, key=lambda k: (-rems[k], k))[:left]:
        floors[k] += 1
    return floors


def ts(d: date, hour: int, minute: int) -> str:
    return f"{d.isoformat()}T{hour:02d}:{minute:02d}:00Z"


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def default_parameters(seed: int) -> dict[str, Any]:
    return {
        "seed": seed, "window_start": WINDOW_START.isoformat(), "window_end": WINDOW_END.isoformat(),
        "months": 24, "regions": list(REGIONS), "customers": 48, "segments": SEGMENTS,
        "products": 36, "categories": list(CATEGORIES), "orders": 2400, "reps": 8,
        "foreign_currency_customers": FOREIGN, "reporting_currency": "USD",
        "line_count_weights": {"1": 0.25, "2": 0.30, "3": 0.22, "4": 0.14, "5": 0.09},
        "discount_line_probability": 0.35, "discount_reason_codes": [r[0] for r in REASONS],
        "return_line_probability": 0.052, "enterprise_apparel_return_multiplier": 3.0,
        "return_credit_delay_days": [5, 45], "split_order_probability": 0.18,
        "short_ship_line_probability": 0.03,
        "fixtures_cost_step": {"from": FIX_STEP_DATE.isoformat(), "factor": [1.17, 1.19]},
        "cost_version_boundaries": [d.isoformat() for d in COST_BOUNDS],
        "west_discount_change": {"from": WEST_START.isoformat(), "probability": WEST_PROB,
                                 "pct_range": list(WEST_PCT), "reason_code": "promo"},
        "injections": {"malformed_currency_orders": 3, "overlapping_cost_versions": 2,
                       "missing_cost_version_products": 1, "missing_fx_dates": 2,
                       "duplicate_shipment_line_rows": 1, "returns_exceeding_remaining": 4,
                       "negative_credits": 1, "territory_change_customers": 2,
                       "unassigned_customers": 3, "cancelled_orders": 5, "zero_gross_orders": 2},
    }


def build(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    P = default_parameters(seed)

    # ---- products ---------------------------------------------------------------------------
    products: list[dict] = []
    prod_meta: dict[str, dict] = {}
    n = 0
    for cat, (pref, (lo, hi), pop, ratio, uoms, names) in CATEGORIES.items():
        for j, name in enumerate(names):
            n += 1
            pid = f"prod-{n:04d}"
            slug = "".join(ch if ch.isalnum() else "-" for ch in name.upper()).strip("-")
            while "--" in slug:
                slug = slug.replace("--", "-")
            if j == len(names) - 1 and cat in LONG_SKU_SUFFIX:
                slug = slug.split("-")[0] + LONG_SKU_SUFFIX[cat]
            sku = f"{pref}-{n:04d}-{slug}"
            price = int(round(rng.uniform(lo, hi) * 100))
            products.append({"product_id": pid, "sku": sku, "category_id": cat,
                             "unit_of_measure": rng.choice(uoms), "active": True})
            prod_meta[pid] = {"cat": cat, "price": price, "pop": pop,
                              "ratio": ratio + rng.uniform(-0.04, 0.04)}
    prod_ids = [p["product_id"] for p in products]

    # ---- customers --------------------------------------------------------------------------
    seg_list = [s for s, k in SEGMENTS.items() for _ in range(k)]
    rng.shuffle(seg_list)
    names = [f"{a} {b} {c}" for a in NAME_A for b in NAME_B for c in NAME_C]
    rng.shuffle(names)
    cust_ids = [f"cust-{i + 1:04d}" for i in range(P["customers"])]
    region_cycle = [REGIONS[i % 4] for i in range(len(cust_ids))]
    rng.shuffle(region_cycle)
    cust: dict[str, dict] = {}
    for i, cid in enumerate(cust_ids):
        cust[cid] = {"name": names[i], "segment": seg_list[i], "region": region_cycle[i],
                     "currency": "USD", "territory": []}
    for cid, nm in zip(rng.sample(cust_ids, len(LONG_NAMES)), LONG_NAMES):
        cust[cid]["name"] = nm
    pool = rng.sample(cust_ids, sum(FOREIGN.values()))
    k = 0
    for ccy, cnt in FOREIGN.items():
        for cid in pool[k:k + cnt]:
            cust[cid]["currency"] = ccy
        k += cnt
    # territory changes: mid-market customers outside reg-west, moving between non-west regions
    tc_pool = [c for c in cust_ids if cust[c]["segment"] == "mid_market" and cust[c]["region"] != "reg-west"]
    territory_ids = rng.sample(tc_pool, 2)
    for cid, eff in zip(territory_ids, (date(2025, 9, 1), date(2026, 2, 1))):
        new = rng.choice([r for r in REGIONS if r not in (cust[cid]["region"], "reg-west")])
        cust[cid]["territory"] = [(eff, new)]
    un_pool = [c for c in cust_ids if cust[c]["segment"] == "smb" and cust[c]["region"] != "reg-west"
               and c not in territory_ids]
    unassigned_ids = rng.sample(un_pool, 3)
    rep_of_region = {r: [f"rep-{2 * i + 1:02d}", f"rep-{2 * i + 2:02d}"] for i, r in enumerate(REGIONS)}

    def policy_region(cid: str, d: date) -> str:
        reg = cust[cid]["region"]
        for eff, new in sorted(cust[cid]["territory"]):
            if d >= eff:
                reg = new
        return reg

    # ---- orders and lines -------------------------------------------------------------------
    weights_m = [1 + 0.012 * i + 0.12 * math.sin(2 * math.pi * (i + 1) / 12) for i in range(24)]
    cust_w = [SEGMENT_WEIGHT[cust[c]["segment"]] for c in cust_ids]
    pw = [prod_meta[p]["pop"] for p in prod_ids]
    skeleton = []
    for _ in range(P["orders"]):
        m = rng.choices(range(24), weights_m)[0]
        first = add_months(WINDOW_START, m)
        last = min(add_months(first, 1) - timedelta(days=1), ORDER_DATE_LAST)
        d = first + timedelta(days=rng.randint(0, (last - first).days))
        skeleton.append((d, rng.choices(cust_ids, cust_w)[0]))
    skeleton.sort()
    order_ids = [f"ord-{i + 1:06d}" for i in range(len(skeleton))]
    usd_idx = [i for i, (_, c) in enumerate(skeleton) if cust[c]["currency"] == "USD" and i > 80]
    special = rng.sample(usd_idx, 3 + 5 + 2)
    malformed_idx = dict(zip(special[:3], ("US$", "usd", "EU")))
    cancelled_idx = set(special[3:8])
    zero_idx = set(special[8:10])

    orders: list[dict] = []
    order_lines: list[dict] = []
    discounts: list[dict] = []
    lines_of: dict[str, list[dict]] = {}
    disc_of: dict[str, int] = {}
    line_n = disc_n = 0
    line_w = [1, 2, 3, 4, 5]
    line_p = [0.25, 0.30, 0.22, 0.14, 0.09]
    for i, (d, cid) in enumerate(skeleton):
        c = cust[cid]
        ccy = c["currency"]
        oid = order_ids[i]
        orders.append({"order_id": oid, "customer_id": cid, "order_date": d.isoformat(),
                       "currency": malformed_idx.get(i, ccy),
                       "status": "cancelled" if i in cancelled_idx else "shipped"})
        nl = rng.choices(line_w, line_p)[0]
        chosen: list[str] = []
        while len(chosen) < nl:
            p = rng.choices(prod_ids, pw)[0]
            if p not in chosen:
                chosen.append(p)
        lines_of[oid] = []
        reg = policy_region(cid, d)
        for pid in chosen:
            line_n += 1
            meta = prod_meta[pid]
            lo, hi = SEGMENT_QTY[c["segment"]]
            qty = rng.randint(lo, hi) * (3 if meta["cat"] == "cat-packaging" else 1)
            price = int(round(meta["price"] * PRICE_FACTOR[ccy])) if i not in zero_idx else 0
            lid = f"line-{line_n:06d}"
            row = {"line_id": lid, "order_id": oid, "product_id": pid, "quantity": qty,
                   "unit_price": money(price)}
            order_lines.append(row)
            lines_of[oid].append(row)
            west_after = reg == "reg-west" and d >= WEST_START
            prob = WEST_PROB if west_after else 0.35
            if i not in zero_idx and rng.random() < prob:
                if west_after:
                    reason, pct = "promo", rng.uniform(*WEST_PCT)
                else:
                    reason, _, rng_pct = rng.choices(REASONS, [r[1] for r in REASONS])[0]
                    pct = rng.uniform(*rng_pct)
                amt = max(1, int(round(qty * price * pct)))
                disc_n += 1
                discounts.append({"discount_id": f"disc-{disc_n:06d}", "line_id": lid,
                                  "discount_amount": money(amt), "reason_code": reason,
                                  "approved_by": rng.choice(rep_of_region[reg])})
                disc_of[lid] = amt

    # ---- shipments --------------------------------------------------------------------------
    shipments: list[dict] = []
    shipment_lines: list[dict] = []
    ship_n = sl_n = 0
    order_by_id = {o["order_id"]: o for o in orders}
    zero_ids = {order_ids[i] for i in zero_idx}
    sl_meta: dict[str, dict] = {}
    for o in orders:
        if o["status"] == "cancelled":
            continue
        oid = o["order_id"]
        d0 = date.fromisoformat(o["order_date"])
        lines = lines_of[oid]
        plan: list[list[tuple[dict, int]]] = [[]]
        totals = {}
        for ln in lines:
            q = ln["quantity"]
            short = rng.randint(1, min(2, q - 1)) if q >= 2 and rng.random() < 0.03 else 0
            totals[ln["line_id"]] = q - short
        if oid not in zero_ids and rng.random() < 0.18:
            groups: list[list[tuple[dict, int]]] = [[], []]
            for ln in lines:
                t = totals[ln["line_id"]]
                if t >= 2 and rng.random() < 0.45:
                    a = rng.randint(1, t - 1)
                    groups[0].append((ln, a))
                    groups[1].append((ln, t - a))
                else:
                    groups[rng.randint(0, 1)].append((ln, t))
            if groups[0] and groups[1]:
                plan = groups
        if len(plan) == 1:
            plan = [[(ln, totals[ln["line_id"]]) for ln in lines]]
        d1 = d0 + timedelta(days=rng.randint(1, 4))
        times = [(d1, rng.randint(8, 17), rng.choice((0, 15, 30, 45)))]
        if len(plan) == 2:
            times.append((d1 + timedelta(days=rng.randint(1, 4)), rng.randint(8, 17), rng.choice((0, 15, 30, 45))))
        for grp, (sd, hh, mm) in zip(plan, times):
            ship_n += 1
            sid = f"shp-{ship_n:06d}"
            units = sum(q for _, q in grp)
            if oid in zero_ids:
                cost = rng.choice((1850, 2475))
            else:
                base = (600 + 55 * units ** 0.75) * rng.uniform(0.85, 1.3)
                cost = int(round(base * PRICE_FACTOR[cust[o["customer_id"]]["currency"]]))
            shipments.append({"shipment_id": sid, "order_id": oid, "shipped_at": ts(sd, hh, mm),
                              "shipping_cost": money(cost), "currency": o["currency"]})
            for ln, q in grp:
                sl_n += 1
                slid = f"sl-{sl_n:06d}"
                shipment_lines.append({"shipment_line_id": slid, "shipment_id": sid,
                                       "line_id": ln["line_id"], "shipped_quantity": q,
                                       "cost_version_id": None})
                sl_meta[slid] = {"date": sd, "shipment_id": sid, "line": ln, "order": o}

    # discount allocated to each shipment line (D-04), needed for the credit amount
    sls_of_line: dict[str, list[dict]] = {}
    for sl in shipment_lines:
        sls_of_line.setdefault(sl["line_id"], []).append(sl)
    alloc_disc: dict[str, int] = {}
    for lid, sls in sls_of_line.items():
        disc = disc_of.get(lid, 0)
        ordered = next(m["line"]["quantity"] for m in [sl_meta[sls[0]["shipment_line_id"]]])
        shipped = sum(s["shipped_quantity"] for s in sls)
        total = half_up_div(disc * shipped, ordered) if disc else 0
        weights = [(s["shipment_line_id"], s["shipped_quantity"]) for s in sls]
        alloc_disc.update(largest_remainder(total, weights) if total else {k2: 0 for k2, _ in weights})

    # ---- returns ----------------------------------------------------------------------------
    pending = []
    returned_orders: set[str] = set()
    for sl in shipment_lines:
        m = sl_meta[sl["shipment_line_id"]]
        cat = prod_meta[m["line"]["product_id"]]["cat"]
        seg = cust[m["order"]["customer_id"]]["segment"]
        p = 0.052 * (3.0 if (seg == "enterprise" and cat == "cat-apparel") else 1.0)
        if rng.random() >= p:
            continue
        sq = sl["shipped_quantity"]
        rq = sq if (sq == 1 or rng.random() < 0.45) else rng.randint(1, sq)
        cd = m["date"] + timedelta(days=rng.randint(5, 45))
        if cd > WINDOW_END or sq == 0:
            continue
        price = int(round(float(m["line"]["unit_price"]) * 100))
        credit = half_up_div(rq * (price * sq - alloc_disc[sl["shipment_line_id"]]), sq)
        pending.append((cd.isoformat(), sl["shipment_line_id"], rq, credit))
        returned_orders.add(m["order"]["order_id"])
    pending.sort()
    returns = [{"return_id": f"ret-{i + 1:05d}", "shipment_line_id": s, "returned_quantity": rq,
                "credit_amount": money(cr), "credit_date": cd}
               for i, (cd, s, rq, cr) in enumerate(pending)]
    for o in orders:
        if o["order_id"] in returned_orders:
            o["status"] = "partially_returned"

    # ---- customers rows (type-2 versions) ---------------------------------------------------
    first_ship: dict[str, date] = {}
    for sl in shipment_lines:
        m = sl_meta[sl["shipment_line_id"]]
        cid = m["order"]["customer_id"]
        if cid not in first_ship or m["date"] < first_ship[cid]:
            first_ship[cid] = m["date"]
    customers: list[dict] = []
    for cid in cust_ids:
        c = cust[cid]
        eff0 = date(2024, 1, 1)
        if cid in unassigned_ids:
            eff0 = first_ship[cid] + timedelta(days=20)
        customers.append({"customer_id": cid, "customer_name": c["name"], "region_id": c["region"],
                          "segment": c["segment"], "effective_from": eff0.isoformat()})
        for eff, new in sorted(c["territory"]):
            customers.append({"customer_id": cid, "customer_name": c["name"], "region_id": new,
                              "segment": c["segment"], "effective_from": eff.isoformat()})

    # ---- injection targets chosen from the data (no rng, so they are stable) -----------------
    bad_orders = {order_ids[i] for i in malformed_idx}
    good_sl = [sl for sl in shipment_lines if sl_meta[sl["shipment_line_id"]]["order"]["order_id"] not in bad_orders
               and sl_meta[sl["shipment_line_id"]]["order"]["order_id"] not in zero_ids]

    def lines_in(month_start: date, month_end: date) -> dict[str, int]:
        cnt: dict[str, int] = {}
        for sl in good_sl:
            m = sl_meta[sl["shipment_line_id"]]
            if month_start <= m["date"] < month_end:
                pid = m["line"]["product_id"]
                cnt[pid] = cnt.get(pid, 0) + 1
        return cnt

    non_fix = lambda pid: prod_meta[pid]["cat"] != "cat-fixtures"  # noqa: E731
    oct25 = {p: c for p, c in lines_in(date(2025, 10, 1), date(2025, 11, 1)).items() if non_fix(p)}
    overlap_products = sorted(oct25, key=lambda p: (-oct25[p], p))[:2]
    feb26 = {p: c for p, c in lines_in(date(2026, 2, 1), date(2026, 3, 1)).items()
             if non_fix(p) and p not in overlap_products}
    gap_product = sorted(feb26, key=lambda p: (-feb26[p], p))[0]

    # ---- cost versions ----------------------------------------------------------------------
    cost_versions: list[dict] = []
    cv_n = 0
    cv_ids: dict[tuple[str, int], str] = {}
    for pid in prod_ids:
        meta = prod_meta[pid]
        cost = meta["price"] * meta["ratio"]
        starts = list(COST_BOUNDS)
        steps = [1.0] + [rng.uniform(1.015, 1.03) for _ in range(3)]
        if meta["cat"] == "cat-fixtures":
            starts = [COST_BOUNDS[0], COST_BOUNDS[1], COST_BOUNDS[2], FIX_STEP_DATE, COST_BOUNDS[3]]
            steps = [1.0, steps[1], steps[2], rng.uniform(1.17, 1.19), steps[3]]
        if pid == gap_product:
            starts = [COST_BOUNDS[0], COST_BOUNDS[1], COST_BOUNDS[2], date(2026, 3, 1)]
        for vi, (s, step) in enumerate(zip(starts, steps)):
            cost *= step
            nxt = starts[vi + 1] if vi + 1 < len(starts) else None
            if pid == gap_product and vi == 2:
                nxt = date(2026, 2, 1)
            if pid in overlap_products and nxt == date(2025, 10, 1):
                nxt = date(2025, 11, 1)
            cv_n += 1
            cv_ids[(pid, vi)] = f"cv-{cv_n:04d}"
            cost_versions.append({"cost_version_id": f"cv-{cv_n:04d}", "product_id": pid,
                                  "unit_cost": money(int(round(cost))), "valid_from": s.isoformat(),
                                  "valid_to": nxt.isoformat() if nxt else None})

    # ---- exchange rates (daily) -------------------------------------------------------------
    days = (WINDOW_END - WINDOW_START).days + 1
    fx_rows: list[dict] = []
    fx_n = 0
    for ccy, start, mean, sigma in (("EUR", 1.085, 1.08, 0.0035), ("CAD", 0.735, 0.73, 0.002)):
        r = start
        for k2 in range(days):
            r += 0.02 * (mean - r) + rng.gauss(0, sigma) * r
            fx_n += 1
            fx_rows.append({"rate_id": f"fx-{fx_n:06d}", "currency": ccy, "reporting_currency": "USD",
                            "rate_date": (WINDOW_START + timedelta(days=k2)).isoformat(),
                            "rate": rate_s(int(round(r * 1_000_000)))})
    missing_fx = []
    for ccy, lo, hi in (("EUR", date(2025, 4, 1), date(2025, 10, 1)), ("CAD", date(2025, 11, 1), date(2026, 4, 1))):
        cnt: dict[str, int] = {}
        for shp in shipments:
            dd = shp["shipped_at"][:10]
            if shp["currency"] == ccy and lo <= date.fromisoformat(dd) < hi:
                cnt[dd] = cnt.get(dd, 0) + 1
        dd = sorted(cnt, key=lambda x: (-cnt[x], x))[0]
        missing_fx.append((ccy, dd))
    fx_removed = [r for r in fx_rows if (r["currency"], r["rate_date"]) in set(missing_fx)]
    exchange_rates = [r for r in fx_rows if r not in fx_removed]

    # ---- quotas -----------------------------------------------------------------------------
    quotas: list[dict] = []
    gross_q: dict[str, int] = {}
    for sl in shipment_lines:
        m = sl_meta[sl["shipment_line_id"]]
        q = f"{m['date'].year}-Q{(m['date'].month - 1) // 3 + 1}"
        gross_q[q] = gross_q.get(q, 0) + sl["shipped_quantity"] * prod_meta[m["line"]["product_id"]]["price"]
    qn = 0
    for qi in range(8):
        qs = add_months(WINDOW_START, 3 * qi)
        label = f"{qs.year}-Q{(qs.month - 1) // 3 + 1}"
        for rep in range(1, 9):
            qn += 1
            amt = int(round(gross_q.get(label, 0) / 8 / 100 * rng.uniform(0.85, 1.2) / 500) * 500)
            quotas.append({"quota_id": f"quota-{qn:03d}", "rep_id": f"rep-{rep:02d}", "period": label,
                           "period_start": qs.isoformat(), "period_end": add_months(qs, 3).isoformat(),
                           "quota_amount": money(amt * 100), "currency": "USD"})

    entities = {"customers": customers, "products": products, "orders": orders,
                "order_lines": order_lines, "discounts": discounts, "shipments": shipments,
                "shipment_lines": shipment_lines, "returns": returns, "cost_versions": cost_versions,
                "exchange_rates": exchange_rates, "quotas": quotas}

    # ---- events (kept out of the entity files) ----------------------------------------------
    ret_sls = {r["shipment_line_id"] for r in returns}
    cand = [sl for sl in good_sl if 2 <= sl["shipped_quantity"] <= 8 and sl["shipment_line_id"] not in ret_sls
            and sl_meta[sl["shipment_line_id"]]["order"]["currency"] == "USD"
            and sl_meta[sl["shipment_line_id"]]["order"]["status"] != "cancelled"
            and sl_meta[sl["shipment_line_id"]]["date"] <= date(2026, 8, 1)]
    step = len(cand) // 6
    picks = [cand[(j + 1) * step] for j in range(5)]
    events: list[dict] = []

    def ret_event(inj: str, sl: dict, qty: int, credit_cents: int, delta_days: int, code: str, note: str) -> dict:
        cd = sl_meta[sl["shipment_line_id"]]["date"] + timedelta(days=delta_days)
        return {"injection": inj, "command": "post-a-partial-return",
                "input": {"shipment_line_id": sl["shipment_line_id"], "returned_quantity": qty,
                          "credit_amount": money(credit_cents), "credit_date": cd.isoformat(),
                          "expected_version": 1, "reason": note},
                "expected_error_code": code}

    exceed = []
    for j, sl in enumerate(picks[:4]):
        price = int(round(float(sl_meta[sl["shipment_line_id"]]["line"]["unit_price"]) * 100))
        qty = sl["shipped_quantity"] + 1 + j % 2
        exceed.append(ret_event("INJ-06", sl, qty, price * qty, 10 + j, "RETURN_EXCEEDS_REMAINING",
                                f"injected: return of {qty} against {sl['shipped_quantity']} shipped"))
    neg_sl = picks[4]
    neg_price = int(round(float(sl_meta[neg_sl["shipment_line_id"]]["line"]["unit_price"]) * 100))
    negative = ret_event("INJ-07", neg_sl, 1, -neg_price, 12, "CREDIT_SIGN_REVERSED", "injected: negative credit")
    multi = [sl for sl in good_sl if sum(1 for x in shipment_lines if x["shipment_id"] == sl["shipment_id"]) > 1
             and sl["shipment_line_id"] not in ret_sls
             and sl_meta[sl["shipment_line_id"]]["order"]["currency"] == "USD"]
    dup_row = dict(multi[len(multi) // 2])
    dup_event = {"injection": "INJ-05", "command": "ingest-sales",
                 "input": {"batch": {"contract": CONTRACT_VERSION, "shipment_lines": [dup_row]}},
                 "expected_handling": "the row repeats an existing shipment_line_id; it must not create a second "
                                      "shipment line or a second allocation"}
    alloc_event = {"injection": "INJ-05", "command": "allocate-freight",
                   "input": {"shipment_id": dup_row["shipment_id"]}, "repeat": 2,
                   "expected_error_code": "FREIGHT_ALREADY_ALLOCATED",
                   "expected_handling": "second call returns 409 and rolls back; the shipment line is allocated once"}
    events = [dup_event, alloc_event] + exceed + [negative]

    # ---- injection manifest -----------------------------------------------------------------
    sl_by_prod_month = lambda pid, a, b: sorted(  # noqa: E731
        sl["shipment_line_id"] for sl in good_sl
        if sl_meta[sl["shipment_line_id"]]["line"]["product_id"] == pid and a <= sl_meta[sl["shipment_line_id"]]["date"] < b)
    ext = [cv_ids[(p, 1)] for p in overlap_products]
    nxt = [cv_ids[(p, 2)] for p in overlap_products]
    amb = sum((sl_by_prod_month(p, date(2025, 10, 1), date(2025, 11, 1)) for p in overlap_products), [])
    gap_lines = sl_by_prod_month(gap_product, date(2026, 2, 1), date(2026, 3, 1))
    fx_aff = []
    for ccy, dd in missing_fx:
        fx_aff += [s["shipment_id"] for s in shipments if s["currency"] == ccy and s["shipped_at"][:10] == dd]
    mal_ids = [order_ids[i] for i in malformed_idx]
    inj = [
        {"id": "INJ-01", "test": "P01-FLOW-01", "entity": "orders", "record_ids": mal_ids,
         "description": "3 orders with a malformed currency: " + ", ".join(
             f"{order_ids[i]}={v!r}" for i, v in malformed_idx.items()) + "; their lines, discounts, shipments, "
             "shipment lines and returns are in the files too.",
         "expected_handling": "C01/validate_batch rejects exactly these orders and every dependent row with "
                              "CURRENCY_NOT_ISO4217; raw rows are kept; none enters the population."},
        {"id": "INJ-02", "test": "P01-TEST-03", "entity": "cost_versions", "record_ids": ext,
         "overlapping_with": nxt, "products": overlap_products,
         "description": "2 cost versions whose valid_to runs one month (to 2025-11-01) into the next version of the "
                        "same product, so 2025-10 has two matching versions.",
         "expected_handling": f"{len(amb)} shipment lines in 2025-10 are quarantined with COST_VERSION_AMBIGUOUS.",
         "affected_shipment_line_ids": amb},
        {"id": "INJ-03", "test": "P01-TEST-03", "entity": "cost_versions",
         "record_ids": [cv_ids[(gap_product, 2)], cv_ids[(gap_product, 3)]], "product_id": gap_product,
         "description": f"{gap_product} has no cost version in 2026-02 (one version ends 2026-02-01, the next starts "
                        "2026-03-01).",
         "expected_handling": f"{len(gap_lines)} shipment lines in 2026-02 are quarantined with COST_VERSION_MISSING.",
         "affected_shipment_line_ids": gap_lines},
        {"id": "INJ-04", "test": "P01-TEST-04", "entity": "exchange_rates",
         "record_ids": [r["rate_id"] for r in fx_removed],
         "missing": [{"currency": c, "rate_date": d} for c, d in missing_fx],
         "description": "2 daily FX rows are absent (rate_ids are skipped in the sequence).",
         "expected_handling": f"shipment lines of {len(fx_aff)} shipments on those dates are quarantined with "
                              "FX_RATE_MISSING; never defaulted to 1.0.",
         "affected_shipment_ids": fx_aff},
        {"id": "INJ-05", "test": "P01-TEST-01", "entity": "shipment_lines", "record_ids": [dup_row["shipment_line_id"]],
         "description": "1 duplicate shipment line row (same shipment_line_id). Kept in data/injection-events.json, not "
                        "in the entity file, because seeding would collide on the primary key.",
         "expected_handling": "replayed through C01 it adds no row; freight allocation is keyed by shipment_line_id so a "
                              "repeated C04 returns 409 FREIGHT_ALREADY_ALLOCATED."},
        {"id": "INJ-06", "test": "P01-TEST-06", "entity": "returns",
         "record_ids": [e["input"]["shipment_line_id"] for e in exceed],
         "description": "4 returns exceeding the remaining quantity. Kept in data/injection-events.json as C03 inputs.",
         "expected_handling": "C03 rejects each with RETURN_EXCEEDS_REMAINING; nothing is written."},
        {"id": "INJ-07", "test": "P01-TEST-10", "entity": "returns", "record_ids": [neg_sl["shipment_line_id"]],
         "description": "1 return with a negative credit. Kept in data/injection-events.json as a C03 input (not in the "
                        "entity file: the database CHECK credit_amount >= 0 would fail the seed).",
         "expected_handling": "C03 rejects with CREDIT_SIGN_REVERSED."},
        {"id": "INJ-08", "test": "P01-TEST-07", "entity": "customers", "record_ids": territory_ids,
         "description": "2 customers change region mid-series: " + "; ".join(
             f"{c} {cust[c]['region']} -> {cust[c]['territory'][0][1]} on {cust[c]['territory'][0][0]}"
             for c in territory_ids) + ".",
         "expected_handling": "each shipment line takes the customer version effective at shipped_at (type-2)."},
        {"id": "INJ-09", "test": "P01-TEST-11", "entity": "customers", "record_ids": unassigned_ids,
         "description": "3 customers whose only version starts 20 days after their first shipment.",
         "expected_handling": "earlier lines resolve to region UNASSIGNED, shown as its own row."},
        {"id": "INJ-10", "test": "P01-TEST-09", "entity": "orders", "record_ids": [order_ids[i] for i in sorted(cancelled_idx)],
         "description": "5 orders cancelled before shipment (status cancelled, lines kept, no shipments).",
         "expected_handling": "no shipment lines; never in the reporting population."},
        {"id": "INJ-11", "test": "P01-TEST-05", "entity": "orders", "record_ids": [order_ids[i] for i in sorted(zero_idx)],
         "description": "2 orders with every unit_price 0.00 (zero gross) and nonzero shipping_cost (18.50 or 24.75).",
         "expected_handling": "freight allocates by shipped quantity, so residual stays 0.00 and contribution carries the cost."},
    ]
    designed = [
        "cat-fixtures unit costs rise about 18 % from 2026-01 (cost_versions valid_from 2026-01-01) while unit prices "
        "stay unchanged, so fixtures contribution margin rate falls from 2026-01.",
        "reg-west discount rate roughly doubles from 2026-03 (probability .35 -> .55, depth x1.45, reason_code promo), "
        "visible as allocated discounts / gross sales by region and month.",
        "enterprise customers in cat-apparel return about 3x the rate of other segment/category combinations "
        "(return probability 0.156 vs 0.052 per shipment line).",
    ]
    return {"entities": entities, "events": events, "injections": inj, "designed": designed,
            "parameters": P}


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


def write_all(seed: int, out: Path, data_dir: Path) -> dict[str, Any]:
    built = build(seed)
    ents = built["entities"]
    version = f"ra-{seed}-{DATE_TAG}"
    dhash = dataset_hash(ents)
    out.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ENTITIES:
        (out / f"{name}.json").write_text(entity_text(name, version, ents[name]))
    inj_manifest = {"dataset_version": version, "dataset_hash": dhash, "seed": seed,
                    "contract_version": CONTRACT_VERSION, "injections": built["injections"],
                    "designed_relationships": built["designed"],
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
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def shape_check(seed: int) -> int:
    golden = json.loads((APP_ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
    ents = build(seed)["entities"]
    bad = 0
    for name, g_rows in golden.items():
        if not isinstance(g_rows, list) or name not in ents:
            continue
        want = set(g_rows[0])
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
