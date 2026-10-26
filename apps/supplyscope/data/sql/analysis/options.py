"""Decision options of the executive memo, computed with the Python domain (P03-ART-07, P03-FLOW-08).

Not SQL: the forecast-derived reorder parameters and the common-random-number simulation are domain functions. Two tables:
  service_target_options  the draft buying plan at the snapshot cutoff under (a) the replenishment_params of record (the
                          generator used z = 1.28, about a 0.90 service target), (b) parameters derived by the domain from the
                          forecast at service 0.90 and (c) at 0.95 (the path C05 takes when a SKU has no parameter row);
  unmet_policy_options    lost sale against backlog for the two triggered class A SKUs on common random numbers, with the stored
                          scenario sc-95-lost / sc-95-backlog (seed 20261026, warm-up 28 days, 100 replications), 180 days.
Simulated directions only: the simulation is a compact (s, S) loop and its statistical quality is not assessed. The derived
parameters use the domain's forecast, whose promotion factor has the open defect S-03.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from supplyscope import ledger
from supplyscope import metrics as dm
from supplyscope.demand import compare_policies
from supplyscope.forecast import dataset_end, forecast_demand
from supplyscope.money import cost_in_force
from supplyscope.replenishment import (derived_parameters, effective_lead_days, lead_time_demand, replenish, safety_stock,
                                       z_value)

SKUS = ("prod-002", "prod-005")


def _pairs(pop, as_of):
    stocks = ledger.reconstruct(pop.inventory_movements, as_of)
    open_by = dm.on_order_by_product(pop, as_of)
    sup = {s.supplier_id: s for s in pop.suppliers}
    versions: dict[str, list] = {}
    for v in pop.cost_versions:
        versions.setdefault(v.product_id, []).append(v)
    end = dataset_end(pop.sales, pop.inventory_movements, pop.receipts)
    for p in sorted(pop.replenishment_params, key=lambda x: (x.product_id, x.location_id)):
        prod = pop.product(p.product_id)
        st = stocks.get((p.product_id, p.location_id))
        oo = open_by.get(p.product_id, 0) if dm.allocation_location(pop, p.product_id) == p.location_id else 0
        bo = sum(b.quantity for b in pop.backorders if (b.product_id, b.location_id) == (p.product_id, p.location_id)
                 and b.opened_at <= as_of and (b.closed_at is None or b.closed_at > as_of))
        s = sup[p.supplier_id]
        cost = cost_in_force(prod.unit_cost, versions.get(p.product_id, []), as_of.date())
        yield p, prod, s, (st.on_hand if st else 0), oo, bo, cost, end


def service_target_options(pop, as_of) -> tuple[list[dict], list[dict]]:
    summary: dict[str, dict] = {k: {"triggered_pairs": 0, "class_a_triggered": 0, "order_units": 0, "order_value": Decimal(0)}
                                for k in ("params of record (generator z 1.28, about 0.90)", "derived from the forecast at 0.90",
                                          "derived from the forecast at 0.95")}
    names = list(summary)
    detail: list[dict] = []
    for p, prod, s, oh, oo, bo, cost, end in _pairs(pop, as_of):
        lead = effective_lead_days(as_of.date(), s.quoted_lead_days, pop.calendar_closures, s.calendar_id)
        fc = forecast_demand(pop.sales, pop.promotions, p.product_id, p.location_id, as_of, max(lead, 7), end)
        series = fc.points[fc.selected_model]
        cases = {names[0]: (p.reorder_point, p.target_position)}
        for name, tgt in ((names[1], "0.90"), (names[2], "0.95")):
            cases[name] = derived_parameters(lead_time_demand(series, lead), safety_stock(z_value(tgt), fc.sigma_variance, lead), sum(series[:7]))
        for name, (rop, target) in cases.items():
            r = replenish(oh, oo, bo, rop, target, prod.minimum_order_quantity, prod.pack_size)
            sm = summary[name]
            if r.triggered:
                sm["triggered_pairs"] += 1
                sm["class_a_triggered"] += 1 if prod.abc_class == "A" else 0
            sm["order_units"] += r.order_quantity
            sm["order_value"] += r.order_quantity * cost
            if p.product_id in SKUS:
                detail.append({"sku": p.product_id, "option": name, "position": r.position, "reorder_point": rop, "target_position": target,
                               "triggered": r.triggered, "order_quantity": r.order_quantity, "order_value": format(r.order_quantity * cost, "f")})
    rows = [{"option": k, **{a: (format(b, "f") if isinstance(b, Decimal) else b) for a, b in v.items()}} for k, v in summary.items()]
    return rows, detail


def unmet_policy_options(pop, as_of) -> list[dict]:
    sc = {s.scenario_id: s for s in pop.policy_scenarios}
    lost, back = sc["sc-95-lost"], sc["sc-95-backlog"]
    latent: dict[tuple, int] = {}
    for x in pop.latent_demand:
        latent[(x.product_id, x.location_id)] = latent.get((x.product_id, x.location_id), 0) + x.latent_quantity
    days_observed = (date(2026, 9, 30) - date(2025, 4, 1)).days + 1
    rows = []
    for p, prod, s, oh, oo, bo, cost, end in _pairs(pop, as_of):
        if p.product_id not in SKUS:
            continue
        mean = latent[(p.product_id, p.location_id)] / days_observed
        out = compare_policies([lost, back], 180, mean, s.quoted_lead_days, s.quoted_lead_days + 7, p.reorder_point,
                               p.target_position, prod.minimum_order_quantity, prod.pack_size, oh)
        for sid, reps in out["results"].items():
            req, ful = sum(r["requested"] for r in reps), sum(r["fulfilled"] for r in reps)
            so, sc_days = sum(r["stockout_days"] for r in reps), sum(r["scored_days"] for r in reps)
            rows.append({"sku": p.product_id, "scenario": sid, "policy": sc[sid].unmet_policy, "seed": out["seed"],
                         "replications": out["replications"], "mean_latent_demand_per_day": format(round(Decimal(mean), 2), "f"),
                         "lead_days": f"{s.quoted_lead_days}-{s.quoted_lead_days + 7}", "fill_rate": format(round(Decimal(ful) / Decimal(req), 4), "f"),
                         "stockout_day_share": format(round(Decimal(so) / Decimal(sc_days), 4), "f")})
    return rows
