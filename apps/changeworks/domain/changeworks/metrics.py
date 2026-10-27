"""The full ``metrics`` tree in the exact key nesting of ``expected.json``:
``summary``, ``scenarios.<id>.{..., initiatives.<id>.{...}, double_count, npv_total}``, ``initiatives.<id>.{roadmap, adoption, training, risk, forecast}``,
``groups.<id>`` and ``resources.<id>``. Metrics that depend on the scenario sit under it; the others do not."""
from __future__ import annotations

from datetime import datetime
from fractions import Fraction as F
from typing import Any

from . import cashflow, measures, people, roadmap
from .context import Ctx, Window
from .ingest import Population
from .numbers import dec, ex, m4, mn, p6


def compute(pop: Population, as_of: datetime, window: Window | None = None, scenario_ids: list[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Returns ``(metrics, warnings)``. ``window`` narrows the time-stamped facts and the periods of the observed measures (half-open); the dated
    model (cash flow, NPV, paybacks, capacity, risk, roadmap, double count) is not windowed and a warning says so."""
    ctx = Ctx(pop, as_of, window, scenario_ids)
    warnings: list[dict[str, Any]] = []
    if ctx.window is not None:
        warnings.append({"code": "MODEL_NOT_WINDOWED", "path": "metrics.scenarios",
                         "message": "the window narrows observations and matured periods; cash flow, NPV, paybacks, capacity, risk, roadmap and double count are not windowed"})
    scenarios: dict[str, Any] = {}
    for sc in ctx.scenarios:
        r, src = ctx.rate(sc)
        out_i: dict[str, Any] = {}
        claims: list[tuple[Any, ...]] = []
        for iid in sc["initiative_ids"]:
            model = cashflow.Model(ctx, sc, iid)
            block, cl, npv, _ = cashflow.initiative_cash_flow(ctx, sc, iid, r, model)
            claims += cl
            real, immature = measures.benefit_realization(ctx, sc, iid, model)
            block.update({"capacity_released": measures.capacity_released(ctx, sc, iid), "cost_variance": measures.cost_variance(ctx, sc, iid),
                          "benefit_realization": real, "immature_observation_ids": immature})
            out_i[iid] = block
            if ctx.ini[iid]["baseline_version"] is not None and sc["baseline_version"] != ctx.ini[iid]["baseline_version"]:
                warnings.append({"code": "BASELINE_VERSION_DIFFERS", "path": f"metrics.scenarios.{sc['scenario_id']}.initiatives.{iid}",
                                 "message": f"the scenario was built on baseline {sc['baseline_version']}; the approved baseline now is {ctx.ini[iid]['baseline_version']}"})
        npvs = [F(x["npv"]["exact"]) for x in out_i.values() if x["npv"]["exact"] is not None]
        scenarios[sc["scenario_id"]] = {
            "status": sc["status"], "baseline_version": sc["baseline_version"], "horizon_periods": sc["horizon_periods"], "rate_basis": sc["rate_basis"],
            "declared_rate": p6(dec(sc["discount_rate"])), "effective_period_rate": p6(r), "effective_period_rate_exact": ex(r), "rate_source": src,
            "initiatives": out_i, "double_count": cashflow.double_count(claims),
            "npv_total": {"value": mn(sum(npvs, F(0))) if npvs else None, "exact": ex(sum(npvs, F(0))) if npvs else None}}
    # scenario-independent initiative metrics
    feas = roadmap.feasible_starts(ctx.ini, ctx.acc["dependencies"])
    inits: dict[str, Any] = {}
    for iid in sorted(ctx.ini):
        adopt = people.adoption(ctx, iid)
        inits[iid] = {"roadmap": roadmap.initiative_roadmap(ctx, feas, iid), "adoption": adopt, "training": people.training(ctx, iid, adopt["adoption_rate"]),
                      "risk": people.risk(ctx, iid), "forecast": people.forecast(ctx, iid)}
    # summary: pools only what can be pooled (D-P9-21)
    first = next(iter(scenarios.values()), None)
    adopted = sum(x["adoption"]["adopted_count"] for x in inits.values() if x["adoption"]["eligible_count"])
    elig = sum(x["adoption"]["eligible_count"] for x in inits.values() if x["adoption"]["eligible_count"])
    tcomp = sum(x["training"]["completed"] for x in inits.values() if x["training"]["eligible_trainees"])
    telig = sum(x["training"]["eligible_trainees"] for x in inits.values() if x["training"]["eligible_trainees"])
    risks = [F(x["risk"]["risk_exposure"]) for x in inits.values() if x["risk"]["risk_exposure"] is not None]
    caps = [F(x["capacity_released"]["hours"]) for x in (first["initiatives"].values() if first else []) if x["capacity_released"]["hours"] is not None]
    summary = {"summary_scenario_id": next(iter(scenarios), None), "initiatives": len(ctx.ini), "scenarios": len(scenarios),
               "npv_total": first["npv_total"]["value"] if first else None,
               "double_count_residual": first["double_count"]["residual"] if first and first["initiatives"] else None,
               "adoption_rate": p6(F(adopted, elig)) if elig else None, "training_completion": p6(F(tcomp, telig)) if telig else None,
               "risk_exposure_total": mn(sum(risks, F(0))) if risks else None,
               "capacity_released_hours_total": m4(sum(caps, F(0))) if caps else None}
    return ({"summary": summary, "scenarios": scenarios, "initiatives": inits, "groups": people.readiness(ctx), "resources": roadmap.resource_views(ctx)},
            warnings)
