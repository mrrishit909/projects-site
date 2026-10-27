// The full `metrics` tree in the exact key nesting of expected.json:
// summary, scenarios.<id>.{..., initiatives.<id>.{...}, double_count, npv_total}, initiatives.<id>.{roadmap, adoption, training, risk, forecast},
// groups.<id> and resources.<id>. Metrics that depend on the scenario sit under it; the others do not.
import { Model, doubleCount, hoursComponents, initiativeCashFlow, type Claim, type Exact, type HourClaim, type Tweaks } from "./cashflow";
import { Ctx, type Window } from "./context";
import type { Row } from "./contract";
import type { Population } from "./ingest";
import * as measures from "./measures";
import { add, cmp, dec, ex, fr, m4, maxFr, mn, p6, parseEx, sub, sumFr, ZERO, type Fr } from "./num";
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
  /** the exact figures behind each scenario's double-count block: the present value that counts twice and the amount removed per class */
  doubleCounted: Map<string, { pv: Fr; byClass: Record<string, Fr> }>;
}

/** `window` narrows the time-stamped facts and the periods of the observed measures (half-open); the dated model (cash flow, NPV, paybacks,
 * capacity, risk, roadmap, double count) is not windowed and a warning says so. `tweaks` is for the sensitivity lab only. */
export function compute(pop: Population, asOf: Instant, window?: Window | null, scenarioIds?: readonly string[] | null, tweaks?: Tweaks): Computation {
  const ctx = new Ctx(pop, asOf, window, scenarioIds);
  const warnings: Row[] = [];
  const exact = new Map<string, Exact>(), rates = new Map<string, Fr>(), doubleCounted = new Map<string, { pv: Fr; byClass: Record<string, Fr> }>();
  if (ctx.window !== null) {
    warnings.push({ code: "MODEL_NOT_WINDOWED", path: "metrics.scenarios",
      message: "the window narrows observations and matured periods; cash flow, NPV, paybacks, capacity, risk, roadmap and double count are not windowed" });
  }
  const scenarios: Row = {};
  const hourClaimsOf = new Map<string, HourClaim[]>();
  for (const sc of ctx.scenarios) {
    const [r, src] = ctx.rate(sc);
    rates.set(sc["scenario_id"], r);
    const outI: Row = {};
    const claims: Claim[] = [], hourClaims: HourClaim[] = [];
    for (const iid of sc["initiative_ids"] as string[]) {
      const model = new Model(ctx, sc, iid, tweaks);
      const res = initiativeCashFlow(ctx, sc, iid, r, model);
      claims.push(...res.claims);
      hourClaims.push(...res.hourClaims);
      exact.set(`${sc["scenario_id"]}/${iid}`, res.exact);
      const [real, immature, late] = measures.benefitRealization(ctx, sc, iid, model);
      Object.assign(res.block, { capacity_released: measures.capacityReleased(ctx, sc, iid), cost_variance: measures.costVariance(ctx, sc, iid), benefit_realization: real,
        immature_observation_ids: immature, late_recorded_observation_ids: late });
      outI[iid] = res.block;
      for (const [typ, rb] of Object.entries(real) as [string, Row][]) {
        if (!rb["trend_coverage"]["complete"] && rb["baseline_trend"] !== null) { // some rows carry a trend, some do not
          warnings.push({ code: "PARTIAL_TREND_COVERAGE", path: `metrics.scenarios.${sc["scenario_id"]}.initiatives.${iid}.benefit_realization.${typ}`, rows: rb["trend_coverage"]["rows_without_trend"],
            message: `${rb["trend_coverage"]["rows_without_trend"].length} compared ${typ} row(s) carry no baseline trend: observed_above_trend is not published` });
        }
      }
      const ib = ctx.ini.get(iid)!["baseline_version"];
      if (ib !== null && sc["baseline_version"] !== ib) {
        warnings.push({ code: "BASELINE_VERSION_DIFFERS", path: `metrics.scenarios.${sc["scenario_id"]}.initiatives.${iid}`,
          message: `the scenario was built on baseline ${sc["baseline_version"]}; the approved baseline now is ${ib}` });
      }
    }
    const npvs = Object.values(outI).filter((x) => x["npv"]["exact"] !== null).map((x) => parseEx(x["npv"]["exact"]));
    const dcb = doubleCount(claims, hourClaims, r);
    hourClaimsOf.set(sc["scenario_id"], hourClaims);
    doubleCounted.set(sc["scenario_id"], { pv: dcb.pvExact, byClass: dcb.byClassExact });
    const total = npvs.length ? sumFr(npvs) : null;
    const attributable = total !== null ? sub(total, dcb.pvExact) : null; // R9-02: shared claims count once
    scenarios[sc["scenario_id"]] = {
      status: sc["status"], baseline_version: sc["baseline_version"], horizon_periods: sc["horizon_periods"], rate_basis: sc["rate_basis"],
      declared_rate: p6(dec(sc["discount_rate"])), effective_period_rate: p6(r), effective_period_rate_exact: ex(r), rate_source: src,
      initiatives: outI, double_count: dcb.block,
      npv_total: { value: mn(attributable), exact: ex(attributable), basis: "attributable", sum_of_initiatives: mn(total), sum_of_initiatives_exact: ex(total) },
    };
  }
  // scenario-independent initiative metrics
  const feas = roadmap.feasibleStarts(ctx.ini, ctx.acc.dependencies);
  const inits: Row = {};
  for (const iid of [...ctx.ini.keys()].sort(cmp)) {
    const adopt = people.adoption(ctx, iid);
    inits[iid] = { roadmap: roadmap.initiativeRoadmap(ctx, feas, iid), adoption: adopt, training: people.training(ctx, iid, adopt["adoption_rate"]), risk: people.risk(ctx, iid), forecast: people.forecast(ctx, iid) };
    for (const w of inits[iid].roadmap.warnings as Row[]) {
      warnings.push({ code: w["code"], path: `metrics.initiatives.${iid}.roadmap`,
        message: `deployment_period ${w["deployment_period"]} is earlier than the dependency-feasible start ${w["dependency_feasible_start"]}: benefits are booked ${w["periods_early"]} period(s) before the work can begin; the cash flow is not re-timed` });
    }
  }
  // summary: pools only what can be pooled (D-P9-21); sums are exact and rounded once (R9-07); money and hours count shared claims once (R9-02, R9-03)
  const first: Row | null = Object.values(scenarios)[0] ?? null;
  const firstId: string | null = Object.keys(scenarios)[0] ?? null;
  const vals = Object.values(inits) as Row[];
  const withAdoption = vals.filter((x) => x["adoption"]["eligible_count"]);
  const adopted = withAdoption.reduce((n, x) => n + (x["adoption"]["adopted_count"] as number), 0);
  const elig = withAdoption.reduce((n, x) => n + (x["adoption"]["eligible_count"] as number), 0);
  const withTraining = vals.filter((x) => x["training"]["eligible_trainees"]);
  const tcomp = withTraining.reduce((n, x) => n + (x["training"]["completed"] as number), 0);
  const telig = withTraining.reduce((n, x) => n + (x["training"]["eligible_trainees"] as number), 0);
  const risks = vals.filter((x) => x["risk"]["risk_exposure_exact"] !== null).map((x) => parseEx(x["risk"]["risk_exposure_exact"]));
  const caps = new Map<string, Fr>();
  if (first) for (const [iid, x] of Object.entries(first["initiatives"] as Row)) if (x["capacity_released"]["hours"] !== null) caps.set(iid, parseEx(x["capacity_released"]["hours_exact"]));
  let capTotal = ZERO, capTwice = ZERO;
  for (const v of caps.values()) capTotal = add(capTotal, v);
  if (firstId !== null) {
    for (const comp of hoursComponents(hourClaimsOf.get(firstId)!)) {
      const members = [...comp].sort(cmp).filter((i) => caps.has(i)).map((i) => caps.get(i)!);
      if (members.length > 1) capTwice = add(capTwice, sub(sumFr(members), maxFr(members)));
    }
  }
  const dcf: Row | null = first ? first["double_count"] : null;
  const live = !!first && Object.keys(first["initiatives"]).length > 0;
  const summary: Row = {
    summary_scenario_id: firstId, initiatives: ctx.ini.size, scenarios: Object.keys(scenarios).length,
    npv_total: first ? first["npv_total"]["value"] : null, npv_sum_of_initiatives: first ? first["npv_total"]["sum_of_initiatives"] : null,
    double_counted_amount: dcf && live ? dcf["double_counted_amount"] : null, double_counted_pv: dcf && live ? dcf["double_counted_pv"] : null,
    double_count_residual: dcf && live ? dcf["residual"] : null, hours_residual: dcf && live ? dcf["hours_residual"] : null,
    adoption_rate: elig ? p6(fr(adopted, elig)) : null, training_completion: telig ? p6(fr(tcomp, telig)) : null,
    risk_exposure_total: risks.length ? mn(sumFr(risks)) : null,
    capacity_released_hours_total: caps.size ? m4(sub(capTotal, capTwice)) : null, capacity_released_hours_double_counted: caps.size ? m4(capTwice) : null,
  };
  return { metrics: { summary, scenarios, initiatives: inits, groups: people.readiness(ctx), resources: roadmap.resourceViews(ctx) }, warnings, exact, rates, doubleCounted };
}
