#!/usr/bin/env python3
"""Independent reference calculation for the Revenue Atlas golden fixtures.

Standard library only. Imports nothing from the application. Every number is
recomputed from inputs.json with decimal.Decimal, step by step, and compared
with expected.json (money: exact at 2 dp, rates: exact at 6 dp).

Usage:
  python3 reference_check.py                # check everything, exit 0 only if all OK
  python3 reference_check.py --write-hashes # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
CENT = Decimal("0.01")
SIX = Decimal("0.000001")
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENTITIES = ["customers", "products", "orders", "order_lines", "discounts", "shipments",
            "shipment_lines", "returns", "cost_versions", "exchange_rates"]
MONEY = ["gross_sales", "allocated_discounts", "merchandise_credits", "net_merchandise_sales",
         "cogs", "recoverable_return_cost", "gross_profit", "shipping_revenue", "shipping_cost",
         "other_variable_costs", "contribution_margin", "eligible_net_revenue", "allocation_residual"]
RATES = ["contribution_margin_rate", "discount_rate", "return_rate"]
NULLABLE_MONEY = ["average_order_value"]
COUNTS = ["eligible_orders", "eligible_shipment_lines", "shipped_units", "returned_units"]

failures = 0


def report(ok, name, expected, got):
    global failures
    if ok:
        print(f"OK {name} {got}")
    else:
        failures += 1
        print(f"MISMATCH {name} expected {expected} got {got}")


def money(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def rate(x):
    return x.quantize(SIX, rounding=ROUND_HALF_UP)


def fmt(x):
    return None if x is None else str(x)


def split_by_largest_remainder(total, weights):
    """Split `total` (cents precision) over {id: weight} proportionally.
    Round each share down to a cent, then hand out the leftover cents one at a
    time to the largest fractional remainder; ties go to the lowest id."""
    weight_sum = sum(weights.values())
    floors, remainders = {}, {}
    for key, w in weights.items():
        exact = total * w / weight_sum
        floors[key] = exact.quantize(CENT, rounding=ROUND_FLOOR)
        remainders[key] = exact - floors[key]
    leftover_cents = int((total - sum(floors.values())) / CENT)
    order = sorted(weights, key=lambda k: (-remainders[k], k))
    for key in order[:leftover_cents]:
        floors[key] += CENT
    return floors


def ingest(data):
    """Return (accepted rows per entity, rejected records).
    Rule: an order whose currency is not three capital letters is rejected
    (CURRENCY_NOT_ISO4217); its lines, shipments, shipment lines, discounts and
    returns are rejected with it."""
    bad_orders = {o["order_id"] for o in data["orders"] if not re.fullmatch(r"[A-Z]{3}", o["currency"])}
    bad_lines = {l["line_id"] for l in data["order_lines"] if l["order_id"] in bad_orders}
    bad_ships = {s["shipment_id"] for s in data["shipments"] if s["order_id"] in bad_orders}
    bad_sls = {s["shipment_line_id"] for s in data["shipment_lines"]
               if s["shipment_id"] in bad_ships or s["line_id"] in bad_lines}
    bad = {"orders": bad_orders, "order_lines": bad_lines, "shipments": bad_ships, "shipment_lines": bad_sls,
           "discounts": {d["discount_id"] for d in data["discounts"] if d["line_id"] in bad_lines},
           "returns": {r["return_id"] for r in data["returns"] if r["shipment_line_id"] in bad_sls}}
    idkey = {"orders": "order_id", "order_lines": "line_id", "shipments": "shipment_id",
             "shipment_lines": "shipment_line_id", "discounts": "discount_id", "returns": "return_id"}
    accepted, rejected = {}, []
    for ent in ENTITIES:
        accepted[ent] = []
        for row in data[ent]:
            if ent in bad and row[idkey[ent]] in bad[ent]:
                rejected.append({"entity": ent, "id": row[idkey[ent]], "status": "rejected",
                                 "reason_code": "CURRENCY_NOT_ISO4217", "raw_row": row})
            else:
                accepted[ent].append(row)
    rejected.sort(key=lambda r: (r["entity"], r["id"]))
    return accepted, rejected


def compute(acc, with_returns, label):
    """Compute all metrics for one state. `label` is only used in check names."""
    lines = {l["line_id"]: l for l in acc["order_lines"]}
    versions = {c["cost_version_id"]: c for c in acc["cost_versions"]}
    sls = sorted(acc["shipment_lines"], key=lambda s: s["shipment_line_id"])

    # Step 1: gross sales per shipment line = shipped_quantity * unit_price
    gross = {s["shipment_line_id"]: s["shipped_quantity"] * Decimal(lines[s["line_id"]]["unit_price"]) for s in sls}
    gross_sales = sum(gross.values(), Decimal("0"))

    # Step 2: discount allocated to shipment lines = discount * shipped / ordered, cents, remainder rule
    disc_alloc = {}
    for d in acc["discounts"]:
        mine = [s for s in sls if s["line_id"] == d["line_id"]]
        if not mine:
            continue
        ordered = lines[d["line_id"]]["quantity"]
        shipped_total = sum(s["shipped_quantity"] for s in mine)
        target = money(Decimal(d["discount_amount"]) * shipped_total / ordered)
        shares = split_by_largest_remainder(target, {s["shipment_line_id"]: Decimal(s["shipped_quantity"]) for s in mine})
        disc_alloc.update(shares)
    allocated_discounts = sum(disc_alloc.values(), Decimal("0"))

    # Step 3: returns (only in the after_return state)
    credits = Decimal("0")
    recoverable = Decimal("0")
    returned_units = 0
    if with_returns:
        by_id = {s["shipment_line_id"]: s for s in sls}
        for r in acc["returns"]:
            s = by_id[r["shipment_line_id"]]
            line = lines[s["line_id"]]
            per_unit_net = Decimal(line["unit_price"]) - disc_alloc[s["shipment_line_id"]] / s["shipped_quantity"]
            should_be = money(r["returned_quantity"] * per_unit_net)
            report(should_be == Decimal(r["credit_amount"]), f"{label}.return_credit_matches_formula[{r['return_id']}]",
                   fmt(should_be), r["credit_amount"])
            credits += Decimal(r["credit_amount"])
            recoverable += r["returned_quantity"] * Decimal(versions[s["cost_version_id"]]["unit_cost"])
            returned_units += r["returned_quantity"]

    # Step 4: net, COGS, gross profit
    net = gross_sales - allocated_discounts - credits
    shipped_cost = sum((s["shipped_quantity"] * Decimal(versions[s["cost_version_id"]]["unit_cost"]) for s in sls), Decimal("0"))
    cogs = shipped_cost - recoverable
    gross_profit = net - cogs

    # Step 5: freight allocation per shipment by gross-sales weight
    freight = {}
    shipping_cost = Decimal("0")
    residual = Decimal("0")
    for sh in sorted(acc["shipments"], key=lambda x: x["shipment_id"]):
        mine = [s for s in sls if s["shipment_id"] == sh["shipment_id"]]
        total = Decimal(sh["shipping_cost"])
        shipping_cost += total
        shares = split_by_largest_remainder(total, {s["shipment_line_id"]: gross[s["shipment_line_id"]] for s in mine})
        freight.update(shares)
        residual += total - sum(shares.values())

    # Step 6: contribution (no shipping revenue / other variable costs in the contract)
    shipping_revenue = Decimal("0")
    other_costs = Decimal("0")
    contribution = gross_profit + shipping_revenue - shipping_cost - other_costs
    eligible_net = net + shipping_revenue

    # Step 7: ratios, null when the denominator is zero
    orders = {lines[s["line_id"]]["order_id"] for s in sls}
    shipped_units = sum(s["shipped_quantity"] for s in sls)
    cm_rate = rate(contribution / eligible_net) if eligible_net != 0 else None
    disc_rate = rate(allocated_discounts / gross_sales) if gross_sales != 0 else None
    ret_rate = rate(Decimal(returned_units) / shipped_units) if shipped_units != 0 else None
    aov = money(net / len(orders)) if len(orders) != 0 else None

    metrics = {"gross_sales": money(gross_sales), "allocated_discounts": money(allocated_discounts),
               "merchandise_credits": money(credits), "net_merchandise_sales": money(net), "cogs": money(cogs),
               "recoverable_return_cost": money(recoverable), "gross_profit": money(gross_profit),
               "shipping_revenue": money(shipping_revenue), "shipping_cost": money(shipping_cost),
               "other_variable_costs": money(other_costs), "contribution_margin": money(contribution),
               "eligible_net_revenue": money(eligible_net), "contribution_margin_rate": cm_rate,
               "discount_rate": disc_rate, "return_rate": ret_rate, "average_order_value": aov,
               "allocation_residual": money(residual), "eligible_orders": len(orders),
               "eligible_shipment_lines": len(sls), "shipped_units": shipped_units, "returned_units": returned_units}
    return metrics, {k: str(v) for k, v in disc_alloc.items()}, {k: str(v) for k, v in freight.items()}


def compare_state(prefix, got, exp):
    for name in MONEY + NULLABLE_MONEY + RATES:
        e = exp["metrics"][name]
        g = got[0][name]
        # exact equality at the fixed decimal places (2 for money, 6 for rates)
        ok = (e is None and g is None) or (e is not None and g is not None and Decimal(e) == g)
        report(ok, f"{prefix}.{name}", e, fmt(g))
    for name in COUNTS:
        report(exp["metrics"][name] == got[0][name], f"{prefix}.{name}", exp["metrics"][name], got[0][name])
    report(exp["discount_by_shipment_line"] == got[1], f"{prefix}.discount_by_shipment_line", exp["discount_by_shipment_line"], got[1])
    report(exp["freight_by_shipment_line"] == got[2], f"{prefix}.freight_by_shipment_line", exp["freight_by_shipment_line"], got[2])
    # extra invariant straight from the spec: freight shares add up to the shipping cost
    freight_sum = sum((Decimal(v) for v in got[2].values()), Decimal("0"))
    report(freight_sum == got[0]["shipping_cost"], f"{prefix}.freight_sum_equals_shipping_cost", fmt(got[0]["shipping_cost"]), fmt(freight_sum))


def check_fixture(name, folder):
    data = json.loads((folder / "inputs.json").read_text())
    exp = json.loads((folder / "expected.json").read_text())
    accepted, rejected = ingest(data)
    for ent in ENTITIES:
        got_counts = {"accepted": len(accepted[ent]), "rejected": len([r for r in rejected if r["entity"] == ent]), "quarantined": 0}
        report(exp["ingest"]["counts"][ent] == got_counts, f"{name}.ingest.{ent}", exp["ingest"]["counts"][ent], got_counts)
    report(exp["ingest"]["rejected_records"] == rejected, f"{name}.ingest.rejected_records",
           [r["id"] for r in exp["ingest"]["rejected_records"]], [r["id"] for r in rejected])
    empty = len(accepted["shipment_lines"]) == 0
    if "empty_population" in exp or empty:
        report(exp.get("empty_population", False) == empty, f"{name}.empty_population", exp.get("empty_population", False), empty)
    for state, with_returns in (("baseline", False), ("after_return", True)):
        compare_state(f"{name}.{state}", compute(accepted, with_returns, f"{name}.{state}"), exp["states"][state])


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_hashes():
    hf = GOLDEN / "HASHES.json"
    if not hf.exists():
        print("SKIP hashes (HASHES.json not written yet; run with --write-hashes)")
        return
    stored = json.loads(hf.read_text())["sha256"]
    for rel in HASHED:
        got = sha256(GOLDEN / rel)
        report(stored.get(rel) == got, f"hash.{rel}", stored.get(rel), got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true", help="write HASHES.json after a clean check")
    args = ap.parse_args()
    check_fixture("golden", GOLDEN)
    check_fixture("rejected", GOLDEN / "variant-rejected")
    check_fixture("empty", GOLDEN / "variant-empty")
    if args.write_hashes:
        if failures:
            print("NOT writing HASHES.json: checks failed")
            return 1
        out = {"algorithm": "sha256", "sha256": {rel: sha256(GOLDEN / rel) for rel in HASHED}}
        (GOLDEN / "HASHES.json").write_text(json.dumps(out, indent=2) + "\n")
        print("WROTE HASHES.json")
    else:
        check_hashes()
    print(f"{'ALL OK' if not failures else 'FAILED'} ({failures} mismatches)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
