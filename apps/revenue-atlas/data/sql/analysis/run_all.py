"""Run every analysis query and reconcile the bridge total with reference_totals.sql (P01-ART-04).

Usage:  DATABASE_URL=... ../../.venv/bin/python data/sql/analysis/run_all.py [--json out.json] [--md]

Order: 00_line_facts.sql (views), then 01..08. Exit code 0 only if (a) every query ran, (b) the bridge TOTAL row
equals reference_totals.sql with no window on every money field, (c) the regional TOTAL equals the bridge TOTAL
and (d) the allocation residual check has 0 failures. Prints each result as a Markdown table.
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parent / "reference_totals.sql"
MAP = {"gross_sales": "gross_sales", "allocated_discounts": "discounts", "merchandise_credits": "credits",
       "net_merchandise_sales": "net_sales", "cogs": "cogs", "gross_profit": "gross_profit",
       "shipping_cost": "freight", "contribution_margin": "contribution"}


def fmt(v) -> str:
    return "" if v is None else format(v, "f") if isinstance(v, Decimal) else str(v)


def table(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    url = os.environ["DATABASE_URL"]
    results: dict[str, list[dict]] = {}
    with psycopg.connect(url, row_factory=dict_row, options="-c timezone=UTC") as conn:
        conn.execute((HERE / "00_line_facts.sql").read_text())
        for f in sorted(HERE.glob("0[1-9]_*.sql")):
            results[f.stem] = conn.execute(f.read_text()).fetchall()
            print(f"### {f.name}\n\n{table(results[f.stem])}\n")
        ref = dict(conn.execute(REFERENCE.read_text(), {"lo": None, "hi": None}).fetchone())
    bridge = next(r for r in results["01_margin_bridge_by_month"] if r["period"] == "TOTAL")
    region = next(r for r in results["02_contribution_by_region"] if r["region_id"] == "TOTAL")
    print("### reconciliation: bridge TOTAL (01) vs data/sql/reference_totals.sql (no window) and the Python domain\n")
    rec, ok = [], True
    for rk, bk in MAP.items():
        match = Decimal(ref[rk]) == bridge[bk]
        ok &= match
        rec.append({"field": rk, "bridge_total": bridge[bk], "reference_totals_sql": ref[rk], "equal": match})
    reg_ok = region["contribution"] == bridge["contribution"] and region["net_sales"] == bridge["net_sales"]
    ok &= reg_ok
    rec.append({"field": "regions TOTAL contribution vs bridge", "bridge_total": bridge["contribution"],
                "reference_totals_sql": region["contribution"], "equal": reg_ok})
    chk = results["08_allocation_residual_check"][0]
    ok &= chk["failures"] == 0 and Decimal(ref["allocation_residual"]) == 0
    # Third, independent computation: the Python domain pipeline over the same snapshot files (no database).
    sys.path[:0] = [str(HERE.parents[2] / "domain")]
    from revenue_atlas import run_pipeline
    snap: dict = {"contract": "v1", "reporting_currency": "USD"}
    for f in (HERE.parents[2] / "web" / "public" / "data").glob("*.json"):
        if f.stem not in ("manifest", "injection-manifest", "quotas"):
            snap[f.stem] = json.loads(f.read_text())["rows"]
    py = run_pipeline(snap, include_returns=True).metrics
    py_ok = all(Decimal(py[rk]) == bridge[bk] for rk, bk in MAP.items())
    ok &= py_ok
    rec.append({"field": "python domain run_pipeline (all 8 money fields)", "bridge_total": bridge["contribution"],
                "reference_totals_sql": py["contribution_margin"], "equal": py_ok})
    print(table(rec), "\n")
    print("reference allocation_residual:", ref["allocation_residual"], "\n")
    # Derived arithmetic for the executive memo (inputs are the printed outputs of 01, 03, 04; no other data).
    pre = next(r for r in results["01_margin_bridge_by_month"] if r["period"].startswith("SUBTOTAL 2024"))
    post = next(r for r in results["01_margin_bridge_by_month"] if r["period"].startswith("SUBTOTAL 2026"))
    rate_pre, rate_post = pre["contribution"] / pre["net_sales"], post["contribution"] / post["net_sales"]
    lost = (rate_pre - rate_post) * post["net_sales"]
    fx = next(r for r in results["04_fixtures_cost_vs_price_by_month"] if r["month"].startswith("SUM 2026"))
    west = next(r for r in results["03_discount_rate_by_region_before_after_2026_03"] if r["region"] == "reg-west")
    memo = {"cm_rate_pre": rate_pre.quantize(Decimal("0.0001")), "cm_rate_post": rate_post.quantize(Decimal("0.0001")),
            "rate_drop_pp": ((rate_pre - rate_post) * 100).quantize(Decimal("0.01")),
            "contribution_lost_to_rate_drop_usd": lost.quantize(Decimal("0.01")),
            "fixtures_extra_cost_usd": fx["extra_cost_usd"], "west_extra_discount_usd": west["extra_discount_usd"],
            "fixtures_share_of_lost": (100 * fx["extra_cost_usd"] / lost).quantize(Decimal("0.1")),
            "west_share_of_lost": (100 * west["extra_discount_usd"] / lost).quantize(Decimal("0.1"))}
    print("### memo arithmetic (derived from 01, 03, 04)\n\n" + table([memo]) + "\n")
    results["memo_arithmetic"] = [memo]
    results["python_domain_metrics"] = [py]
    results["reconciliation"] = rec
    results["reference_totals"] = [ref]
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(
            json.dumps(results, indent=1, default=lambda o: format(o, "f") if isinstance(o, Decimal) else str(o)))
    print("RESULT:", "OK" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
