// The full `metrics` tree in the exact key nesting of expected.json:
// summary, scenarios.<id>.{..., initiatives.<id>.{...}, double_count, npv_total}, initiatives.<id>.{roadmap, adoption, training, risk, forecast},
// groups.<id> and resources.<id>. Metrics that depend on the scenario sit under it; the others do not.
import { Model, doubleCount, initiativeCashFlow, type Exact, type Tweaks } from "./cashflow";
import { Ctx, type Window } from "./context";
import type { Row } from "./contract";
import type { Population } from "./ingest";
import * as measures from "./measures";
import { cmp, dec, ex, fr, m4, mn, p6, parseEx, sumFr, type Fr } from "./num";
import * as people from "./people";
import * as roadmap from "./roadmap";
import type { Instant } from "./time";

export interface Computation {
  metrics: Row;
  warnings: Row[];
  /** exact internals by "scenario_id/initiative_id" (not part of the published shape) */
  exact: Map<string, Exact>;
  /** the effective per-period rate of each scenario, exactly */
  rates: Map<string, Fr>;
}

/** `window` narrows the time-stamped facts and the periods of the observed measures (half-open); the dated model (cash flow, NPV, paybacks,
 * capacity, risk, roadmap, double count) is not windowed and a warning says so. `tweaks` is for the sensitivity lab only. */
export function compute(pop: Population, asOf: Instant, window?: Window | null, scenarioIds?: readonly string[] | null, tweaks?: Tweaks): Computation {
  const ctx = new Ctx(pop, asOf, window, scenarioIds);
  const warnings: Row[] = [];
  const exact = new Map<string, Exact>(), rates = new Map<string, Fr>();
  if (ctx.window !== null) {
    warnings.push({ code: "MODEL_NOT_WINDOWED", path: "metrics.scenarios",
      message: "the window narrows observations and matured periods; cash flow, NPV, paybacks, capacity, risk, roadmap and double count are not windowed" });
  }
  const scenarios: Row = {};
  for (const sc of ctx.scenarios) {
    const [r, src] = ctx.rate(sc);
    rates.set(sc["scenario_id"], r);
    const outI: Row = {};
    const claims = [] as ReturnType<typeof initiativeCashFlow>["claims"];
    for (const iid of sc["initiative_ids"] as string[]) {
      const model = new Model(ctx, sc, iid, tweaks);
      const res = initiativeCashFlow(ctx, sc, iid, r, model);
      claims.push(...res.claims);
      exact.set(`${sc["scenario_id"]}/${iid}`, res.exact);
      const [real, immature] = measures.benefitRealization(ctx, sc, iid, model);
      Object.assign(res.block, { capacity_released: measures.capacityReleased(ctx, sc, iid), cost_variance: measures.costVariance(ctx, sc, iid), benefit_realization: real, immature_observation_ids: immature });
      outI[iid] = res.block;
      const ib = ctx.ini.get(iid)!["baseline_version"];
      if (ib !== null && sc["baseline_version"] !== ib) {
        warnings.push({ code: "BASELINE_VERSION_DIFFERS", path: `metrics.scenarios.${sc["scenario_id"]}.initiatives.${iid}`,
          message: `the scenario was built on baseline ${sc["baseline_version"]}; the approved baseline now is ${ib}` });
      }
    }
    const npvs = Object.values(outI).filter((x) => x["npv"]["exact"] !== null).map((x) => parseEx(x["npv"]["exact"]));
    const total = npvs.length ? sumFr(npvs) : null;
    scenarios[sc["scenario_id"]] = {
      status: sc["status"], baseline_version: sc["baseline_version"], horizon_periods: sc["horizon_periods"], rate_basis: sc["rate_basis"],
      declared_rate: p6(dec(sc["discount_rate"])), effective_period_rate: p6(r), effective_period_rate_exact: ex(r), rate_source: src,
      initiatives: outI, double_count: doubleCount(claims), npv_total: { value: mn(total), exact: ex(total) },
    };
  }
  // scenario-independent initiative metrics
  const feas = roadmap.feasibleStarts(ctx.ini, ctx.acc.dependencies);
  const inits: Row = {};
  for (const iid of [...ctx.ini.keys()].sort(cmp)) {
    const adopt = people.adoption(ctx, iid);
    inits[iid] = { roadmap: roadmap.initiativeRoadmap(ctx, feas, iid), adoption: adopt, training: people.training(ctx, iid, adopt["adoption_rate"]), risk: people.risk(ctx, iid), forecast: people.forecast(ctx, iid) };
  }
  // summary: pools only what can be pooled (D-P9-21)
  const first: Row | null = Object.values(scenarios)[0] ?? null;
  const vals = Object.values(inits) as Row[];
  const withAdoption = vals.filter((x) => x["adoption"]["eligible_count"]);
  const adopted = withAdoption.reduce((n, x) => n + (x["adoption"]["adopted_count"] as number), 0);
  const elig = withAdoption.reduce((n, x) => n + (x["adoption"]["eligible_count"] as number), 0);
  const withTraining = vals.filter((x) => x["training"]["eligible_trainees"]);
  const tcomp = withTraining.reduce((n, x) => n + (x["training"]["completed"] as number), 0);
  const telig = withTraining.reduce((n, x) => n + (x["training"]["eligible_trainees"] as number), 0);
  const risks = vals.filter((x) => x["risk"]["risk_exposure"] !== null).map((x) => dec(x["risk"]["risk_exposure"]));
  const caps = first ? (Object.values(first["initiatives"]) as Row[]).filter((x) => x["capacity_released"]["hours"] !== null).map((x) => dec(x["capacity_released"]["hours"])) : [];
  const summary: Row = {
    summary_scenario_id: Object.keys(scenarios)[0] ?? null, initiatives: ctx.ini.size, scenarios: Object.keys(scenarios).length,
    npv_total: first ? first["npv_total"]["value"] : null,
    double_count_residual: first && Object.keys(first["initiatives"]).length ? first["double_count"]["residual"] : null,
    adoption_rate: elig ? p6(fr(adopted, elig)) : null, training_completion: telig ? p6(fr(tcomp, telig)) : null,
    risk_exposure_total: risks.length ? mn(sumFr(risks)) : null, capacity_released_hours_total: caps.length ? m4(sumFr(caps)) : null,
  };
  return { metrics: { summary, scenarios, initiatives: inits, groups: people.readiness(ctx), resources: roadmap.resourceViews(ctx) }, warnings, exact, rates };
}
