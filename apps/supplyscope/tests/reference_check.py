#!/usr/bin/env python3
"""Independent reference calculation for the SupplyScope golden fixtures.

Standard library only. Imports nothing from the application. Every number is
recomputed from inputs.json with plain integer / decimal.Decimal arithmetic and
compared with expected.json (units exact integers, money 2 dp, rates 6 dp).

Usage:
  python3 reference_check.py                # check everything, exit 0 only if all OK
  python3 reference_check.py --write-hashes # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
TWO = Decimal("0.01")
SIX = Decimal("0.000001")
FIXTURES = ["", "variant-rejected/", "variant-empty/"]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENTITIES = ["products", "locations", "sales", "inventory_movements", "purchase_orders", "purchase_order_lines",
            "receipts", "suppliers", "promotions", "forecast_runs", "forecast_points", "policy_scenarios",
            "backorders", "reservations", "replenishment_params"]
ID_KEY = {"products": "product_id", "locations": "location_id", "sales": "sale_id",
          "inventory_movements": "movement_id", "purchase_orders": "purchase_order_id",
          "purchase_order_lines": "po_line_id", "receipts": "receipt_id", "suppliers": "supplier_id",
          "promotions": "promotion_id", "forecast_runs": "forecast_run_id", "forecast_points": "forecast_point_id",
          "policy_scenarios": "scenario_id", "backorders": "backorder_id", "reservations": "reservation_id",
          "replenishment_params": "product_id"}
# D-01 day order: receipts, then demand, then everything else (review)
DAY_CLASS = {"receipt": 0, "sale": 1}

failures = 0


def report(ok, name, expected, got):
    global failures
    if ok:
        print(f"OK {name} {got}")
    else:
        failures += 1
        print(f"MISMATCH {name} expected {expected} got {got}")


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def d2(x):
    return str(x.quantize(TWO, rounding=ROUND_HALF_UP))


def d6(x):
    return None if x is None else str(x.quantize(SIX, rounding=ROUND_HALF_UP))


def ratio(n, d):
    return None if d == 0 else Decimal(n) / Decimal(d)


def ingest(data):
    """D-01 duplicate movement_id (second occurrence rejected, first kept) and
    D-04 RECEIPT_BEFORE_ORDER (receipt earlier than its PO's ordered_at)."""
    accepted = {e: [] for e in ENTITIES}
    rejected = []
    seen = set()
    for row in data["inventory_movements"]:
        if row["movement_id"] in seen:
            rejected.append({"entity": "inventory_movements", "id": row["movement_id"], "status": "rejected",
                             "reason_code": "DUPLICATE_MOVEMENT_ID", "raw_row": row})
        else:
            seen.add(row["movement_id"])
            accepted["inventory_movements"].append(row)
    line_po = {l["po_line_id"]: l["purchase_order_id"] for l in data["purchase_order_lines"]}
    po_at = {p["purchase_order_id"]: ts(p["ordered_at"]) for p in data["purchase_orders"]}
    for row in data["receipts"]:
        if ts(row["received_at"]) < po_at[line_po[row["po_line_id"]]]:
            rejected.append({"entity": "receipts", "id": row["receipt_id"], "status": "rejected",
                             "reason_code": "RECEIPT_BEFORE_ORDER", "raw_row": row})
        else:
            accepted["receipts"].append(row)
    for ent in ENTITIES:
        if ent not in ("inventory_movements", "receipts"):
            accepted[ent] = list(data[ent])
    rejected.sort(key=lambda r: (r["entity"], r["id"]))
    return accepted, rejected


def running_min(movements, cutoff, key):
    """Minimum running stock (including the starting 0) over movements at or before cutoff."""
    run, low = 0, 0
    for m in sorted((m for m in movements if ts(m["event_at"]) <= cutoff), key=key):
        run += m["quantity_delta"]
        low = min(low, run)
    return run, low


def compute(data, acc, state):
    cutoff, start = ts(data["as_of"]), ts(data["window_start"])
    products = {p["product_id"]: p for p in acc["products"]}
    moves = acc["inventory_movements"]

    # ledger as of cutoff; day order = date, class (receipt, sale, other), time, id
    day_key = lambda m: (ts(m["event_at"]).date(), DAY_CLASS.get(m["movement_type"], 2), m["event_at"], m["movement_id"])
    time_key = lambda m: (m["event_at"], m["movement_id"])
    on_hand_raw, low = running_min(moves, cutoff, day_key)
    _, naive_low = running_min(moves, cutoff, time_key)
    negative = on_hand_raw < 0 or low < 0
    on_hand = max(on_hand_raw, 0)

    # on order: confirmed lines, ordered - received (receipts accepted and <= cutoff), never below 0
    lines = list(acc["purchase_order_lines"]) + list(state.get("add_purchase_order_lines", []))
    confirmed = {p["purchase_order_id"] for p in acc["purchase_orders"] if p["status"] == "confirmed"}
    on_order = 0
    for l in lines:
        if l["purchase_order_id"] not in confirmed:
            continue
        got = sum(r["received_quantity"] for r in acc["receipts"]
                  if r["po_line_id"] == l["po_line_id"] and ts(r["received_at"]) <= cutoff)
        on_order += max(l["ordered_quantity"] - got, 0)

    # backorders open at cutoff; reservations as of cutoff
    backorders = sum(b["quantity"] for b in acc["backorders"] if ts(b["opened_at"]) <= cutoff and
                     (b["closed_at"] is None or ts(b["closed_at"]) > cutoff))
    reserved = sum(r["quantity"] for r in acc["reservations"] if ts(r["reserved_at"]) <= cutoff)
    available = on_hand - reserved
    position = on_hand + on_order - backorders          # reserved is NOT subtracted (D-01)

    # replenishment (D-02); no parameter row means not evaluated
    out = {}
    params = acc["replenishment_params"]
    if params:
        p = params[0]
        prod = products[p["product_id"]]
        triggered = position < p["reorder_point"]
        raw = max(p["target_position"] - position, 0) if triggered else 0
        moq = max(raw, prod["minimum_order_quantity"]) if triggered else 0
        qty = math.ceil(moq / prod["pack_size"]) * prod["pack_size"] if triggered else 0
        out.update({"reorder_point": p["reorder_point"], "target_position": p["target_position"],
                    "reorder_triggered": triggered, "raw_order": raw, "order_after_moq": moq, "order_quantity": qty})
    else:
        out.update({"reorder_point": None, "target_position": None, "reorder_triggered": None,
                    "raw_order": None, "order_after_moq": None, "order_quantity": None})

    # fill rate and stockout days over [window_start, cutoff]
    fulfilled = sum(s["quantity"] for s in acc["sales"] if start <= ts(s["sold_at"]) <= cutoff)
    unmet = sum(b["quantity"] for b in acc["backorders"] if start <= ts(b["opened_at"]) <= cutoff)
    requested = fulfilled + unmet
    unmet_days = {ts(b["opened_at"]).date() for b in acc["backorders"] if start <= ts(b["opened_at"]) <= cutoff}
    observed_days = (cutoff.date() - start.date()).days + 1
    empty = len(moves) == 0 and len(acc["sales"]) == 0

    # working capital: on hand valued at unit cost (negative reconstruction valued at zero)
    stock = sum((Decimal(on_hand) * Decimal(pr["unit_cost"]) for pr in products.values()), Decimal(0))  # one product/location here

    out.update({"on_hand": on_hand, "on_order": on_order, "backorders": backorders, "reserved": reserved,
                "available": available, "inventory_position": position, "working_capital": d2(stock),
                "requested_units": requested, "fulfilled_units": fulfilled, "unmet_units": unmet,
                "fill_rate": d6(ratio(fulfilled, requested)), "observed_days": observed_days,
                "stockout_day_count": len(unmet_days),
                "stockout_days": None if empty else d6(ratio(len(unmet_days), observed_days)),
                "running_stock_min": low, "timestamp_order_stock_min": naive_low,
                "negative_stock": negative, "empty_population": empty})
    return out


def check_fixture(prefix):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    label = prefix.rstrip("/") or "golden"
    accepted, rejected = ingest(data)
    for ent in ENTITIES:
        e = exp["ingest"]["counts"][ent]
        got = {"accepted": len(accepted[ent]), "rejected": sum(1 for r in rejected if r["entity"] == ent)}
        report(e == got, f"{label}.ingest.{ent}", e, got)
    report(rejected == exp["ingest"]["rejected_records"], f"{label}.ingest.rejected_records",
           [(r["entity"], r["id"], r["reason_code"]) for r in exp["ingest"]["rejected_records"]],
           [(r["entity"], r["id"], r["reason_code"]) for r in rejected])
    report(set(data["states"]) == set(exp["states"]), f"{label}.state_names", sorted(exp["states"]), sorted(data["states"]))
    for name, spec in exp["states"].items():
        got = compute(data, accepted, data["states"][name])
        for k, want in spec["metrics"].items():
            report(got.get(k) == want and type(got.get(k)) is type(want), f"{label}.{name}.{k}", want, got.get(k))
        report(set(got) == set(spec["metrics"]), f"{label}.{name}.metric_names", sorted(spec["metrics"]), sorted(got))
    if prefix == "variant-rejected/":
        gold = json.loads((GOLDEN / "expected.json").read_text())
        same = gold["states"] == exp["states"]
        report(same, f"{label}.totals_equal_golden", "equal", "equal" if same else "different")


def sha(path):
    return hashlib.sha256((GOLDEN / path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true")
    args = ap.parse_args()
    for prefix in FIXTURES:
        check_fixture(prefix)
    hashes_path = GOLDEN / "HASHES.json"
    if args.write_hashes:
        if failures:
            print(f"NOT WRITING HASHES: {failures} mismatch(es)")
        else:
            hashes_path.write_text(json.dumps({"algorithm": "sha256", "sha256": {p: sha(p) for p in HASHED}}, indent=2) + "\n")
            print(f"OK wrote {hashes_path.name}")
    elif hashes_path.exists():
        stored = json.loads(hashes_path.read_text())["sha256"]
        for p in HASHED:
            report(stored.get(p) == sha(p), f"hash[{p}]", stored.get(p), sha(p))
    print("ALL OK" if not failures else f"{failures} MISMATCH(ES)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
