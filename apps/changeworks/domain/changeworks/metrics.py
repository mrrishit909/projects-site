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
    hour_claims_of: dict[str, list[tuple[Any, ...]]] = {}
    for sc in ctx.scenarios:
        r, src = ctx.rate(sc)
        out_i: dict[str, Any] = {}
        claims: list[tuple[Any, ...]] = []
        hour_claims: list[tuple[Any, ...]] = []
        for iid in sc["initiative_ids"]:
            model = cashflow.Model(ctx, sc, iid)
            block, cl, hcl, npv, _ = cashflow.initiative_cash_flow(ctx, sc, iid, r, model)
            claims += cl
            hour_claims += hcl
            real, immature, late = measures.benefit_realization(ctx, sc, iid, model)
            block.update({"capacity_released": measures.capacity_released(ctx, sc, iid), "cost_variance": measures.cost_variance(ctx, sc, iid),
                          "benefit_realization": real, "immature_observation_ids": immature, "late_recorded_observation_ids": late})
            out_i[iid] = block
            for typ, rb in real.items():
                if not rb["trend_coverage"]["complete"] and rb["baseline_trend"] is not None:       # some rows carry a trend, some do not
                    warnings.append({"code": "PARTIAL_TREND_COVERAGE", "path": f"metrics.scenarios.{sc['scenario_id']}.initiatives.{iid}.benefit_realization.{typ}",
                                     "rows": rb["trend_coverage"]["rows_without_trend"],
                                     "message": f"{len(rb['trend_coverage']['rows_without_trend'])} compared {typ} row(s) carry no baseline trend: observed_above_trend is not published"})
            if ctx.ini[iid]["baseline_version"] is not None and sc["baseline_version"] != ctx.ini[iid]["baseline_version"]:
                warnings.append({"code": "BASELINE_VERSION_DIFFERS", "path": f"metrics.scenarios.{sc['scenario_id']}.initiatives.{iid}",
                                 "message": f"the scenario was built on baseline {sc['baseline_version']}; the approved baseline now is {ctx.ini[iid]['baseline_version']}"})
        npvs = [F(x["npv"]["exact"]) for x in out_i.values() if x["npv"]["exact"] is not None]
        dcb = cashflow.double_count(claims, hour_claims, r)
        hour_claims_of[sc["scenario_id"]] = hour_claims
        total = sum(npvs, F(0))
        attributable = total - F(dcb["double_counted_pv_exact"]) if npvs else None       # R9-02: shared claims count once
        scenarios[sc["scenario_id"]] = {
            "status": sc["status"], "baseline_version": sc["baseline_version"], "horizon_periods": sc["horizon_periods"], "rate_basis": sc["rate_basis"],
            "declared_rate": p6(dec(sc["discount_rate"])), "effective_period_rate": p6(r), "effective_period_rate_exact": ex(r), "rate_source": src,
            "initiatives": out_i, "double_count": dcb,
            "npv_total": {"value": mn(attributable), "exact": ex(attributable), "basis": "attributable", "sum_of_initiatives": mn(total) if npvs else None,
                          "sum_of_initiatives_exact": ex(total) if npvs else None}}
    # scenario-independent initiative metrics
    feas = roadmap.feasible_starts(ctx.ini, ctx.acc["dependencies"])
    inits: dict[str, Any] = {}
    for iid in sorted(ctx.ini):
        adopt = people.adoption(ctx, iid)
        inits[iid] = {"roadmap": roadmap.initiative_roadmap(ctx, feas, iid), "adoption": adopt, "training": people.training(ctx, iid, adopt["adoption_rate"]),
                      "risk": people.risk(ctx, iid), "forecast": people.forecast(ctx, iid)}
        for w in inits[iid]["roadmap"]["warnings"]:
            warnings.append({"code": w["code"], "path": f"metrics.initiatives.{iid}.roadmap",
                             "message": f"deployment_period {w['deployment_period']} is earlier than the dependency-feasible start {w['dependency_feasible_start']}: benefits are booked "
                                        f"{w['periods_early']} period(s) before the work can begin; the cash flow is not re-timed"})
    # summary: pools only what can be pooled (D-P9-21); sums are exact and rounded once (R9-07); money and hours count shared claims once (R9-02, R9-03)
    first = next(iter(scenarios.values()), None)
    first_id = next(iter(scenarios), None)
    adopted = sum(x["adoption"]["adopted_count"] for x in inits.values() if x["adoption"]["eligible_count"])
    elig = sum(x["adoption"]["eligible_count"] for x in inits.values() if x["adoption"]["eligible_count"])
    tcomp = sum(x["training"]["completed"] for x in inits.values() if x["training"]["eligible_trainees"])
    telig = sum(x["training"]["eligible_trainees"] for x in inits.values() if x["training"]["eligible_trainees"])
    risks = [F(x["risk"]["risk_exposure_exact"]) for x in inits.values() if x["risk"]["risk_exposure_exact"] is not None]
    caps = {iid: F(x["capacity_released"]["hours_exact"]) for iid, x in (first["initiatives"].items() if first else []) if x["capacity_released"]["hours"] is not None}
    cap_total = sum(caps.values(), F(0))
    cap_counted_twice = F(0)
    if first_id is not None:
        for comp in cashflow.hours_components(hour_claims_of[first_id]):
            members = [caps[i] for i in sorted(comp) if i in caps]
            if len(members) > 1:
                cap_counted_twice += sum(members, F(0)) - max(members)
    dcf = first["double_count"] if first else None
    summary = {"summary_scenario_id": first_id, "initiatives": len(ctx.ini), "scenarios": len(scenarios),
               "npv_total": first["npv_total"]["value"] if first else None,
               "npv_sum_of_initiatives": first["npv_total"]["sum_of_initiatives"] if first else None,
               "double_counted_amount": dcf["double_counted_amount"] if dcf and first["initiatives"] else None,
               "double_counted_pv": dcf["double_counted_pv"] if dcf and first["initiatives"] else None,
               "double_count_residual": dcf["residual"] if dcf and first["initiatives"] else None,
               "hours_residual": dcf["hours_residual"] if dcf and first["initiatives"] else None,
               "adoption_rate": p6(F(adopted, elig)) if elig else None, "training_completion": p6(F(tcomp, telig)) if telig else None,
               "risk_exposure_total": mn(sum(risks, F(0))) if risks else None,
               "capacity_released_hours_total": m4(cap_total - cap_counted_twice) if caps else None,
               "capacity_released_hours_double_counted": m4(cap_counted_twice) if caps else None}
    return ({"summary": summary, "scenarios": scenarios, "initiatives": inits, "groups": people.readiness(ctx), "resources": roadmap.resource_views(ctx)},
            warnings)
