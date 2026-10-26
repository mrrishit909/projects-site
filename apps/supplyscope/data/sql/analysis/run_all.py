"""Run every analysis query and reconcile it with the independent sources (P03-ART-04).

Usage:
  DATABASE_URL=<snapshot db> GOLDEN_DATABASE_URL=<golden db> ../../.venv/bin/python data/sql/analysis/run_all.py [--json out.json]

Prepare both databases first with prepare_snapshot.py (and ``--golden``). Order: 00 (views), 01..08 on the snapshot, 09 on the
golden database in both fixture states. Exit code 0 only if every query ran and every reconciliation holds:
  A. golden fixture, three sources printed side by side (this directory's 09, data/sql/reference_metrics.sql, the Python domain)
     plus the hand-derived expected.json, for state golden and state position_80;
  B. snapshot totals: 01 / 02 / 03 / 06 vs reference_metrics.sql vs the domain (on hand, on order, backorders, position, the
     replenishment arithmetic, fill rate, working capital, average inventory value);
  C. cell by cell: 54 month-end stock and position cells vs an independent Python replay, 60 draft-order rows vs the domain's
     ``replenish`` per pair, 18 x 3 fill-rate cells vs ``compute_metrics``, supplier on-time rate at 18 cutoffs vs the domain's
     ``on_time_rate``, forecast WAPE for 14 SKUs x 3 models vs Python over the JSON files, censored vs latent vs the domain's
     ``censored_vs_latent`` and the generator's designed counts;
  D. rejected and detected defects vs data/injection-manifest.json.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(HERE)]

from options import service_target_options, unmet_policy_options  # noqa: E402
from prepare_snapshot import SNAPSHOT, snapshot_inputs  # noqa: E402
from supplyscope import run_pipeline  # noqa: E402
from supplyscope.demand import censored_vs_latent  # noqa: E402
from supplyscope.ledger import reconstruct  # noqa: E402
from supplyscope.metrics import compute_metrics, supplementary  # noqa: E402
from supplyscope.models import parse_ts  # noqa: E402
from supplyscope.suppliers import on_time_rate, open_quantity  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
AS_OF = "2026-09-30T23:59:59Z"
START = "2025-04-01T00:00:00Z"
G_AS_OF, G_START = "2026-03-31T23:59:59Z", "2026-03-01T00:00:00Z"
D6 = Decimal("0.000001")


def fmt(v) -> str:
    return "" if v is None else format(v, "f") if isinstance(v, Decimal) else str(v)


def table(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def q6(x) -> str | None:
    if x is None:
        return None
    d = Decimal(x.numerator) / Decimal(x.denominator) if isinstance(x, Fraction) else Decimal(x)
    return format(d.quantize(D6, ROUND_HALF_UP), "f")


class Recon:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.ok = True

    def add(self, check: str, a, b, c=None, d=None) -> None:
        vals = [a, b] + [v for v in (c, d) if v is not None]
        eq = all(fmt(v) == fmt(a) for v in vals)
        self.ok &= eq
        self.rows.append({"check": check, "analysis_sql": fmt(a), "second_source": fmt(b),
                          "third_source": "" if c is None else fmt(c), "fourth_source": "" if d is None else fmt(d), "equal": eq})


def month_cutoffs() -> list[tuple[str, datetime]]:
    out = []
    y, m = 2025, 4
    for _ in range(18):
        ny, nm = (y + (m == 12), 1 if m == 12 else m + 1)
        out.append((f"{y}-{m:02d}", datetime(ny, nm, 1, tzinfo=timezone.utc) - timedelta(seconds=1)))
        y, m = ny, nm
    return out


def main(argv: list[str]) -> int:
    url, gurl = os.environ["DATABASE_URL"], os.environ.get("GOLDEN_DATABASE_URL")
    results: dict[str, list[dict]] = {}
    rec = Recon()
    cutoffs = month_cutoffs()
    with psycopg.connect(url, row_factory=dict_row, options="-c timezone=UTC", autocommit=True) as conn:
        conn.execute((HERE / "00_ledger_views.sql").read_text())
        for f in sorted(HERE.glob("0[1-8]_*.sql")):
            results[f.stem] = conn.execute(f.read_text()).fetchall()
            print(f"### {f.name}\n\n{table(results[f.stem])}\n")
        ref = dict(conn.execute(REFERENCE.read_text(), {"as_of": AS_OF, "window_start": START, "window_end": None}).fetchone())
        so_days_ref = conn.execute("""SELECT count(DISTINCT d)::int AS n FROM (
                SELECT (opened_at AT TIME ZONE 'UTC')::date AS d FROM backorders
                UNION ALL SELECT (occurred_at AT TIME ZONE 'UTC')::date FROM lost_sales) u""").fetchone()["n"]
        bi_day = conn.execute((HERE / "bi_fact_movement_day.sql").read_text()).fetchall()
        bi_draft = conn.execute((HERE / "bi_fact_draft_order.sql").read_text()).fetchall()
        n_draft_rows = conn.execute("SELECT count(*)::int AS n FROM draft_orders").fetchone()["n"]
        n_rej = conn.execute("SELECT count(*)::int AS n FROM rejected_records").fetchone()["n"]

    # ---- Python domain over the same snapshot files (no database) --------------------------------------------
    inputs = snapshot_inputs()
    res = run_pipeline(inputs)
    pop, dom = res.population, res.metrics
    as_of = parse_ts(AS_OF)
    window = (parse_ts(START), None)

    # ---- B. snapshot totals ----------------------------------------------------------------------------------
    r01 = [r for r in results["01_stock_position_month_end_by_location"] if r["month"] == "2026-09"]
    t02 = next(r for r in results["02_draft_orders_arithmetic"] if r["product_id"].startswith("TOTAL"))
    a03 = next(r for r in results["03_fill_rate_stockout_by_location_abc"] if r["location_id"] == "ALL")
    last06 = next(r for r in results["06_working_capital_by_location"] if r["month"] == "2026-09")
    all06 = next(r for r in results["06_working_capital_by_location"] if r["month"] == "ALL")
    mine = {"on_hand": sum(r["on_hand"] for r in r01), "on_order": sum(r["on_order_confirmed_only"] for r in r01),
            "backorders": sum(r["backorders"] for r in r01), "inventory_position": t02["position"],
            "reorder_point": t02["reorder_point"], "target_position": t02["target_position"],
            "raw_order": t02["raw_order"], "order_after_moq": t02["after_moq"], "order_quantity": t02["order_qty"],
            "fulfilled_units": a03["fulfilled_units"], "unmet_units": a03["unmet_units"], "requested_units": a03["requested_units"],
            "fill_rate": fmt(a03["fill_rate"]), "working_capital": fmt(last06["end_total"])}
    # ---- decision options of the memo (domain computed, not SQL) --------------------------------------------
    opt_rows, opt_detail = service_target_options(pop, as_of)
    results["10_options_service_target"], results["10_options_service_target_sku_detail"] = opt_rows, opt_detail
    results["10_options_unmet_policy"] = unmet_policy_options(pop, as_of)
    for k in ("10_options_service_target", "10_options_service_target_sku_detail", "10_options_unmet_policy"):
        print(f"### {k} (Python domain, options.py)\n\n{table(results[k])}\n")
    rec.add("B options: params-of-record row equals the 02 TOTAL (triggered pairs / order units)",
            f"{opt_rows[0]['triggered_pairs']} / {opt_rows[0]['order_units']}", f"{len(results['02_draft_orders_arithmetic']) - 1} / {t02['order_qty']}")

    for k, v in mine.items():
        rec.add(f"B snapshot {k}: query 01/02/03/06 vs reference_metrics.sql vs domain", v, ref[k], dom[k])
    rec.add("B on hand 02 TOTAL vs 01 month-end 2026-09", t02["on_hand"], mine["on_hand"], ref["on_hand"])
    rec.add("B on order (contract, confirmed only) 02 TOTAL vs 01 column on_order_confirmed_only", t02["on_order"], mine["on_order"], ref["on_order"])
    rec.add("B observed days 548 (03 pair-days / 60 pairs) vs reference vs domain", 548, ref["observed_days"], dom["observed_days"])
    rec.add("B stockout days (distinct dates with unmet demand, all pairs): SQL vs reference vs domain", so_days_ref, ref["stockout_day_count"],
            dom["stockout_day_count"])
    sup = supplementary(pop, as_of, window)
    rec.add("B average daily inventory value 06 row ALL vs domain supplementary()", fmt(all06["avg_daily_total"]),
            sup["average_inventory_value"])
    rec.add("B on-order difference as-of rule vs confirmed only at the final month-end (S-04: closed orders with a partial line)",
            sum(r["on_order"] - r["on_order_confirmed_only"] for r in r01), 72)
    rec.add("B bi_fact_movement_day rows (60 pairs x 548 days)", len(bi_day), 60 * 548)
    last_day = [r for r in bi_day if r["date_key"] == 20260930]
    rec.add("B bi_fact_movement_day stock value on 2026-09-30 vs working capital", fmt(sum(r["stock_value"] for r in last_day)), ref["working_capital"])
    rec.add("B bi_fact_movement_day fulfilled units vs reference", sum(r["fulfilled_units"] for r in bi_day), ref["fulfilled_units"])
    rec.add("B bi_fact_movement_day unmet units vs reference", sum(r["unmet_units"] for r in bi_day), ref["unmet_units"])
    # the expected values of docs/bi-package.md, recomputed here from the two fact exports (not by Power BI)
    cogs = sum(Decimal(r["cogs_value"]) for r in bi_day)
    value_sum = sum(Decimal(r["stock_value"]) for r in bi_day)
    sku_day_cells = sum(1 for r in bi_day if r["stockout_flag"])
    cal_days = len({r["date_key"] for r in bi_day})
    so_dates = len({r["date_key"] for r in bi_day if r["stockout_flag"]})
    turnover = q6(Fraction(cogs) * 365 / Fraction(value_sum))
    results["bi_expected_measures"] = [
        {"measure": "Fulfilled Units", "expected": sum(r["fulfilled_units"] for r in bi_day), "source": "fact_movement_day, sum"},
        {"measure": "Unmet Units", "expected": sum(r["unmet_units"] for r in bi_day), "source": "fact_movement_day, sum"},
        {"measure": "Requested Units", "expected": sum(r["fulfilled_units"] + r["unmet_units"] for r in bi_day), "source": "fulfilled + unmet"},
        {"measure": "Fill Rate", "expected": q6(Fraction(sum(r["fulfilled_units"] for r in bi_day), sum(r["fulfilled_units"] + r["unmet_units"] for r in bi_day))),
         "source": "query 03 ALL"},
        {"measure": "Stockout SKU Day Share", "expected": q6(Fraction(sku_day_cells, len(bi_day))), "source": f"{sku_day_cells} / {len(bi_day)}, query 03 ALL"},
        {"measure": "Stockout Calendar Day Share", "expected": q6(Fraction(so_dates, cal_days)), "source": f"{so_dates} / {cal_days}, reference_metrics.sql stockout_days"},
        {"measure": "On Hand Units (2026-09-30)", "expected": sum(r["closing_on_hand"] for r in last_day), "source": "query 01, 2026-09"},
        {"measure": "Working Capital (2026-09-30)", "expected": fmt(sum(Decimal(r["stock_value"]) for r in last_day)), "source": "query 06, 2026-09 end_total"},
        {"measure": "Average Inventory Value", "expected": format((value_sum / cal_days).quantize(Decimal("0.01"), ROUND_HALF_UP), "f"), "source": "query 06 row ALL"},
        {"measure": "Inventory Turnover", "expected": turnover, "source": "domain supplementary()"},
        {"measure": "Inventory Position (2026-09-30)", "expected": sum(r["inventory_position"] for r in bi_draft), "source": "query 02 TOTAL"},
        {"measure": "Draft Order Units", "expected": sum(r["order_quantity"] for r in bi_draft), "source": "query 02 TOTAL"},
        {"measure": "Draft Order Value", "expected": fmt(sum(Decimal(r["order_value"]) for r in bi_draft if r["order_value"] is not None)), "source": "query 02 TOTAL"},
        {"measure": "Triggered Pairs", "expected": sum(1 for r in bi_draft if r["triggered"]), "source": "query 02"},
    ]
    rec.add("B bi Inventory Turnover (facts) vs domain supplementary()", turnover, sup["inventory_turnover"])
    rec.add("B bi Stockout Calendar Day Share (facts) vs reference_metrics.sql stockout_days", results["bi_expected_measures"][5]["expected"], ref["stockout_days"])
    rec.add("B bi Inventory Position (facts) vs reference_metrics.sql", results["bi_expected_measures"][10]["expected"], ref["inventory_position"])
    rec.add("B bi Draft Order Units (facts) vs reference_metrics.sql order_quantity", results["bi_expected_measures"][11]["expected"], ref["order_quantity"])
    rec.add("B draft_orders rows persisted in the seeded snapshot (derived table, written by the API)", n_draft_rows, 0)
    rec.add("B bi_fact_draft_order rows (60 pairs at the cutoff)", len(bi_draft), 60)

    # ---- C1. 54 month-end cells vs an independent Python replay ----------------------------------------------
    home: dict[str, str] = {}
    for p in sorted(pop.replenishment_params, key=lambda x: (x.product_id, x.location_id)):
        home.setdefault(p.product_id, p.location_id)
    orders = {o.purchase_order_id: o for o in pop.purchase_orders}
    bad = 0
    for r in results["01_stock_position_month_end_by_location"]:
        cut = next(c for m, c in cutoffs if m == r["month"])
        oh = sum(s.on_hand for (pid, loc), s in reconstruct(pop.inventory_movements, cut).items() if loc == r["location_id"])
        oo = sum(open_quantity(l, pop.receipts, cut) for l in pop.purchase_order_lines
                 if orders[l.purchase_order_id].status != "cancelled" and orders[l.purchase_order_id].ordered_at <= cut
                 and home[l.product_id] == r["location_id"])
        bo = sum(b.quantity for b in pop.backorders if b.location_id == r["location_id"] and b.opened_at <= cut
                 and (b.closed_at is None or b.closed_at > cut))
        if (oh, oo, bo) != (r["on_hand"], r["on_order"], r["backorders"]):
            bad += 1
    rec.add("C 01 month-end cells (18 months x 3 locations) differing from the Python replay of on hand / on order / backorders", bad, 0)

    # ---- C2. draft-order arithmetic per pair vs the domain's replenish ---------------------------------------
    bad = 0
    for r in bi_draft:
        m = compute_metrics(pop, as_of, window, None, products={r["product_id"]}, locations={r["location_id"]})
        if (m["on_hand"], m["on_order"], m["inventory_position"], m["raw_order"], m["order_after_moq"], m["order_quantity"]) != (
                r["on_hand"], r["on_order"], r["inventory_position"], r["raw_order"], r["order_after_moq"], r["order_quantity"]):
            bad += 1
    rec.add("C 60 draft-order rows (bi_fact_draft_order) differing from the domain per pair", bad, 0)
    rec.add("C triggered pairs: 02 rows vs bi_fact_draft_order triggered vs domain",
            len(results["02_draft_orders_arithmetic"]) - 1, sum(1 for r in bi_draft if r["triggered"]),
            sum(1 for r in bi_draft if r["order_quantity"] > 0))

    # ---- C3. fill rate and stockout cells vs compute_metrics --------------------------------------------------
    abc = {p.product_id: p.abc_class for p in pop.products}
    bad = 0
    for r in results["03_fill_rate_stockout_by_location_abc"]:
        locs = None if r["location_id"] == "ALL" else {r["location_id"]}
        prods = {p for p in abc if r["abc_class"] == "ALL" or abc[p] == r["abc_class"]}
        m = compute_metrics(pop, as_of, window, None, products=prods, locations=locs)
        if (m["fulfilled_units"], m["unmet_units"], m["fill_rate"]) != (r["fulfilled_units"], r["unmet_units"], fmt(r["fill_rate"])):
            bad += 1
    rec.add("C 03 rows (location x ABC, location subtotals, ALL) differing from compute_metrics", bad, 0)

    # ---- C4. supplier on-time rate at every month-end vs the domain ------------------------------------------
    bad = n = 0
    for r in results["04_supplier_on_time_by_month"]:
        if r["month"] == "ALL":
            continue
        cut = next(c for m, c in cutoffs if m == r["month"])
        d = on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, pop.calendar_closures, cut, r["supplier_id"])
        n += 1
        if (d["eligible_receipts"], d["on_time_rate"]) != (r["cum_eligible"], fmt(r["cum_on_time_rate"]) or None):
            bad += 1
    rec.add("C 04 cumulative as-of rate cells (4 suppliers x 18 cutoffs) differing from on_time_rate(cutoff)", bad, 0)
    rec.add("C 04 cells compared", n, 72)
    for r in (x for x in results["04_supplier_on_time_by_month"] if x["month"] == "ALL"):
        d = on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, pop.calendar_closures, as_of, r["supplier_id"])
        rec.add(f"C 04 {r['supplier_id']} whole history: eligible / on-time rate", f"{r['eligible_receipts']} / {fmt(r['on_time_rate'])}",
                f"{d['eligible_receipts']} / {d['on_time_rate']}")
    mon = json.loads((SNAPSHOT / "manifest.json").read_text())
    s3 = next(x for x in results["04_supplier_on_time_by_month"] if x["supplier_id"] == "sup-03" and x["month"] == "ALL")
    rec.add("C 04 sup-03 late share vs the manifest's designed 31.9 % of 254",
            f"{round(100 * (1 - s3['on_time_receipts'] / s3['eligible_receipts']), 1)} % of {s3['eligible_receipts']}", "31.9 % of 254")

    # ---- C5. censored vs latent --------------------------------------------------------------------------------
    designed = json.loads(re.search(r"(\{[^{}]*\"prod-001\"[^{}]*\})", mon["designed_relationships"][0].replace('\\"', '"')).group(1))
    bad = 0
    for r in results["05_censored_vs_latent_class_a"]:
        c = censored_vs_latent(pop.sales, pop.backorders, pop.lost_sales, pop.latent_demand, r["product_id"], r["location_id"],
                               date(2025, 4, 1), date(2026, 9, 30), as_of)
        cdays = set(c["censored_days"])
        obs = sum(v for k, v in c["observed"].items() if k in cdays)
        lat = sum(v for k, v in c["latent"].items() if k in cdays)
        if (len(cdays), obs, lat) != (r["stockout_days"], r["observed_on_stockout_days"], r["latent_on_stockout_days"]):
            bad += 1
        if r["censored_units"] != r["unmet_recorded"] or r["days_observed_ne_latent"] != 0:
            bad += 1
        if r["product_id"] in designed and designed[r["product_id"]] != r["stockout_days"]:
            bad += 1
    rec.add("C 05 SKUs (8 class A) differing from censored_vs_latent, censored = unmet, or the manifest's stockout days", bad, 0)

    # ---- C6. forecast WAPE in plain Python over the JSON files ------------------------------------------------
    fr = json.loads((SNAPSHOT / "forecast_runs.json").read_text())["rows"]
    fp = json.loads((SNAPSHOT / "forecast_points.json").read_text())["rows"]
    sales = json.loads((SNAPSHOT / "sales.json").read_text())["rows"]
    by_day: dict[tuple, int] = defaultdict(int)
    for s in sales:
        by_day[(s["product_id"], s["location_id"], s["sold_at"][:10])] += s["quantity"]
    run = {r["forecast_run_id"]: r for r in fr}
    err: dict[tuple, Decimal] = defaultdict(Decimal)
    act: dict[tuple, int] = defaultdict(int)
    for p in fp:
        r = run[p["forecast_run_id"]]
        a = by_day.get((r["product_id"], r["location_id"], p["target_date"]), 0)
        err[(r["product_id"], p["model"])] += abs(Decimal(a) - Decimal(p["forecast_value"]))
        if p["model"] == "naive":
            act[r["product_id"]] += a
    bad = 0
    for r in results["07_forecast_wape_by_sku"]:
        for model, col in (("naive", "wape_naive"), ("seasonal_naive", "wape_seasonal_naive"), ("ewma", "wape_ewma")):
            want = q6(err[(r["product_id"], model)] / act[r["product_id"]]) if act[r["product_id"]] else None
            if want != (fmt(r[col]) or None):
                bad += 1
    rec.add("C 07 WAPE cells (14 SKUs x 3 models) differing from Python over forecast_points.json and sales.json", bad, 0)
    rec.add("C 07 leaky forecast points (target date on or before the cutoff)", sum(r["leaky_points"] for r in results["07_forecast_wape_by_sku"]), 0)

    # ---- D. rejections and detected defects vs the injection manifest ----------------------------------------
    inj = {i["id"]: i for i in json.loads((ROOT / "data" / "injection-manifest.json").read_text())["injections"]}
    r08 = {r["reason"]: r for r in results["08_rejections_and_defects_by_reason"]}
    rec.add("D INJ-01 DUPLICATE_MOVEMENT_ID ids", r08["DUPLICATE_MOVEMENT_ID"]["ids"], ", ".join(sorted(inj["INJ-01"]["record_ids"])))
    rec.add("D INJ-02 RECEIPT_BEFORE_ORDER ids", r08["RECEIPT_BEFORE_ORDER"]["ids"], ", ".join(sorted(inj["INJ-02"]["record_ids"])))
    rec.add("D INJ-03 closed orders partly received (po lines)", r08["CLOSED_ORDER_PARTLY_RECEIVED"]["ids"], ", ".join(sorted(inj["INJ-03"]["record_ids"])))
    rec.add("D INJ-04 receipts spanning the closure", r08["LEAD_TIME_SPANS_CLOSURE"]["records"], 8)
    rec.add("D INJ-07 open reservations at the cutoff", r08["OPEN_RESERVATION_AT_CUTOFF"]["ids"], ", ".join(sorted(inj["INJ-07"]["record_ids"])))
    rec.add("D rejected rows kept (table) vs domain ingest", n_rej, len(res.ingest.rejected), 4)

    # ---- A. golden fixture, three sources + expected.json ------------------------------------------------------
    golden_rows: list[dict] = []
    if gurl:
        gin = json.loads((ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
        exp = json.loads((ROOT / "tests" / "fixtures" / "golden" / "expected.json").read_text())["states"]
        sql09 = (HERE / "09_golden_position_and_order.sql").read_text()
        keymap = (("on_hand", "on_hand"), ("on_order", "on_order"), ("backorders", "backorders"), ("position", "inventory_position"),
                  ("reorder_point", "reorder_point"), ("target_position", "target_position"), ("triggered", "reorder_triggered"),
                  ("raw_order", "raw_order"), ("order_after_moq", "order_after_moq"), ("order_quantity", "order_quantity"),
                  ("running_min_day_order", "running_stock_min"), ("running_min_timestamp_order", "timestamp_order_stock_min"),
                  ("working_capital", "working_capital"), ("fulfilled_units", "fulfilled_units"), ("unmet_units", "unmet_units"),
                  ("fill_rate", "fill_rate"), ("stockout_days_count", "stockout_day_count"), ("stockout_days", "stockout_days"))
        params = {"as_of": G_AS_OF, "window_start": G_START, "window_end": None}
        per_state: dict[str, tuple[dict, dict]] = {}
        with psycopg.connect(gurl, row_factory=dict_row, options="-c timezone=UTC") as gc:
            per_state["golden"] = (gc.execute(sql09).fetchone(), dict(gc.execute(REFERENCE.read_text(), params).fetchone()))
            extra = gc.execute("SELECT payload FROM fixture_states WHERE state_name = 'position_80'").fetchone()["payload"]
            for line in extra["add_purchase_order_lines"]:       # the fixture's second line, inside a transaction that is rolled back
                gc.execute("INSERT INTO purchase_order_lines (po_line_id, purchase_order_id, product_id, ordered_quantity, unit_cost) "
                           "VALUES (%(po_line_id)s, %(purchase_order_id)s, %(product_id)s, %(ordered_quantity)s, %(unit_cost)s)", line)
            per_state["position_80"] = (gc.execute(sql09).fetchone(), dict(gc.execute(REFERENCE.read_text(), params).fetchone()))
            gc.rollback()
        results["09_golden_position_and_order"] = [dict(per_state["golden"][0]), {"state": "position_80", **dict(per_state["position_80"][0])}]
        print(f"### 09_golden_position_and_order.sql (golden database, state golden then position_80)\n\n{table(results['09_golden_position_and_order'])}\n")
        for state in ("golden", "position_80"):
            mine_row, ref_row = per_state[state]
            gdom = run_pipeline(gin, state=state).metrics
            for k9, kd in keymap:
                v = mine_row[k9]
                rec.add(f"A golden state {state}: {kd}", v, ref_row[kd], gdom[kd], exp[state]["metrics"][kd])
                golden_rows.append({"state": state, "quantity": kd, "analysis_sql_09": fmt(v), "reference_metrics_sql": fmt(ref_row[kd]),
                                    "python_domain": fmt(gdom[kd]), "expected_json": fmt(exp[state]["metrics"][kd])})
        print("### golden fixture: position / order from three sources (and the hand-derived expected.json)\n\n" + table(golden_rows) + "\n")
    else:
        rec.ok = False
        print("GOLDEN_DATABASE_URL not set: golden reconciliation skipped", file=sys.stderr)

    print("### reconciliation\n\n" + table(rec.rows) + "\n")
    results["reconciliation"] = rec.rows
    results["golden_three_sources"] = golden_rows
    results["reference_metrics_snapshot"] = [ref]
    results["python_domain_snapshot"] = [dom]
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(
            results, indent=1, default=lambda o: format(o, "f") if isinstance(o, Decimal) else str(o)) + "\n")
    print("RESULT:", "OK" if rec.ok else "MISMATCH")
    return 0 if rec.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
