// Portfolio-level derivations from the computation: totals by benefit class (never added across classes), confidence labels, benefit windows.
// Totals are exact sums of the domain's rational figures, rounded once at the end; nothing is re-derived from rounded rows.
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { cmp, money, sub, sumFr, type Fr } from "../domain/num";
import type { Exact } from "../domain/cashflow";

export const sumKey = (a: readonly Fr[]): Fr => sumFr(a);
export function exactOf(ds: Dataset, sid: string, iid: string): Exact { return ds.comp.exact.get(`${sid}/${iid}`)!; }

export interface InitiativeFigures {
  iid: string; title: string; programme: string | null; sponsor: string; status: string;
  costs: Fr; cash: Fr; revenue: Fr; avoided: Fr; capacityUsd: Fr; net: Fr;
  avoidedBeside: string | null; capacityHours: string | null;
  /** the exact totals behind the two rounded strings above (R9-07: a total is never a sum of rounded rows) */
  avoidedBesideX: Fr; capacityHoursX: Fr;
  npv: string | null; npvExact: string | null; simple: Row; discounted: Row;
  ramp: boolean;
  /** DEPLOYMENT_BEFORE_FEASIBLE_START, when the plan books benefits before the work can begin (R9-06) */
  deploymentWarning: Row | null;
}
export function programmeOf(ds: Dataset, iid: string): { id: string; name: string } | null {
  const p = ds.manifest.programmes?.find((q) => q.initiative_ids.includes(iid));
  return p ? { id: p.programme_id, name: p.name } : null;
}
export function initiativeFigures(ds: Dataset, sid: string, iid: string): InitiativeFigures {
  const blk = ds.metrics["scenarios"][sid]["initiatives"][iid] as Row;
  const e = exactOf(ds, sid, iid);
  const i = ds.byId.initiatives.get(iid)!;
  return {
    iid, title: i["title"], programme: programmeOf(ds, iid)?.name ?? null, sponsor: i["sponsor_id"], status: i["status"],
    costs: sumFr(e.cost), cash: sumFr(e.byClass.map((c) => c.cash)), revenue: sumFr(e.byClass.map((c) => c.revenue)),
    avoided: sumFr(e.byClass.map((c) => c.avoided_cost_realised)), capacityUsd: sumFr(e.byClass.map((c) => c.capacity_converted)), net: sumFr(e.cf),
    avoidedBeside: blk["excluded_from_cash_flow"]["avoided_cost_beside_total"], capacityHours: blk["excluded_from_cash_flow"]["capacity_hours_not_converted"],
    avoidedBesideX: e.beside, capacityHoursX: e.capHours,
    npv: blk["npv"]["value"], npvExact: blk["npv"]["exact"], simple: blk["payback"]["simple"], discounted: blk["payback"]["discounted"], ramp: blk["ramp"] !== null,
    deploymentWarning: ((ds.metrics["initiatives"][iid]["roadmap"]["warnings"] as Row[])[0]) ?? null,
  };
}

export interface ScenarioTotals {
  id: string; status: string; horizon: number; rateBasis: string; declared: string; effective: string; rateSource: string; baselineVersion: string;
  /** the attributable NPV (shared claims counted once) and the plain sum of the initiative NPVs beside it (R9-02) */
  npv: string | null; npvExact: string | null; npvSum: string | null; doubledPv: string; doubledAmount: string; hoursResidual: string;
  residual: string; planned: string; attributable: string; initiatives: number; explanationFor: string[];
  /** attributable class totals: the sum over the initiatives less the claims that count twice, class by class; hours are never added to them */
  costs: string; cash: string; revenue: string; avoided: string; capacityUsd: string; avoidedBeside: string; capacityHours: string;
  /** the same classes as listed row by row (the plain sums) and the amounts removed from them */
  listed: Record<"cash" | "revenue" | "avoided" | "capacityUsd" | "avoidedBeside", string>;
  removed: Record<"cash" | "revenue" | "avoided" | "capacityUsd" | "avoidedBeside", string>;
  neverSimple: number; neverDiscounted: number;
}
const memo = new WeakMap<Dataset, ScenarioTotals[]>();
const CLS = { cash: "cash", revenue: "revenue", avoided: "avoided_cost_realised", capacityUsd: "capacity_converted", avoidedBeside: "avoided_cost_beside" } as const;
/** One row per scenario, in scenario id order: costs and the benefit classes in separate columns (each class sums only with itself). Class totals are the
 * exact sums over the initiatives less the claims that count twice (`double_count.double_counted_by_class_exact`), rounded once. */
export function scenarioTotals(ds: Dataset): ScenarioTotals[] {
  const hit = memo.get(ds);
  if (hit) return hit;
  const rows = (Object.entries(ds.metrics["scenarios"]) as [string, Row][]).map(([sid, s]) => {
    const figs = Object.keys(s["initiatives"]).map((iid) => initiativeFigures(ds, sid, iid));
    const dcx = ds.comp.doubleCounted.get(sid)!;
    const listedX: Record<keyof typeof CLS, Fr> = {
      cash: sumFr(figs.map((f) => f.cash)), revenue: sumFr(figs.map((f) => f.revenue)), avoided: sumFr(figs.map((f) => f.avoided)),
      capacityUsd: sumFr(figs.map((f) => f.capacityUsd)), avoidedBeside: sumFr(figs.map((f) => f.avoidedBesideX)),
    };
    const out = (k: keyof typeof CLS): Fr => sub(listedX[k], dcx.byClass[CLS[k]]!);
    const listed = Object.fromEntries((Object.keys(CLS) as (keyof typeof CLS)[]).map((k) => [k, money(listedX[k])])) as ScenarioTotals["listed"];
    const removed = Object.fromEntries((Object.keys(CLS) as (keyof typeof CLS)[]).map((k) => [k, money(dcx.byClass[CLS[k]]!)])) as ScenarioTotals["removed"];
    return {
      id: sid, status: s["status"], horizon: s["horizon_periods"], rateBasis: s["rate_basis"], declared: s["declared_rate"], effective: s["effective_period_rate"], rateSource: s["rate_source"],
      baselineVersion: s["baseline_version"], npv: s["npv_total"]["value"], npvExact: s["npv_total"]["exact"], npvSum: s["npv_total"]["sum_of_initiatives"],
      doubledPv: s["double_count"]["double_counted_pv"], doubledAmount: s["double_count"]["double_counted_amount"], hoursResidual: s["double_count"]["hours_residual"],
      residual: s["double_count"]["residual"], planned: s["double_count"]["planned_benefits"], attributable: s["double_count"]["attributable_benefits"], initiatives: figs.length,
      explanationFor: s["double_count"]["explanation_required_for"],
      costs: money(sumFr(figs.map((f) => f.costs))), cash: money(out("cash")), revenue: money(out("revenue")), avoided: money(out("avoided")), capacityUsd: money(out("capacityUsd")),
      avoidedBeside: money(out("avoidedBeside")), capacityHours: money(sumFr(figs.map((f) => f.capacityHoursX))),
      listed, removed,
      neverSimple: figs.filter((f) => f.simple["period"] === null).length, neverDiscounted: figs.filter((f) => f.discounted["period"] === null).length,
    } satisfies ScenarioTotals;
  });
  memo.set(ds, rows);
  return rows;
}

/** The scenario the pages open on: the one the designed relationships were realised in (DR-02), otherwise the first. */
export function defaultScenario(ds: Dataset): string {
  const ids = Object.keys(ds.metrics["scenarios"]);
  const dr = ds.manifest.designed_relationships?.find((d) => d.id === "DR-02")?.realised["scenario_id"];
  return typeof dr === "string" && ids.includes(dr) ? dr : (ids[0] ?? "");
}
export function scenariosWith(ds: Dataset, iid: string): string[] {
  return Object.entries(ds.metrics["scenarios"]).filter(([, s]) => iid in (s as Row)["initiatives"]).map(([k]) => k).sort(cmp);
}

export type ConfidenceLabel = "strong" | "partial" | "thin";
export interface Confidence { label: ConfidenceLabel; points: { key: string; ok: boolean; why: string }[]; score: number }
/** An assessment of how much of the case has been measured, not a probability: four yes/no points printed beside the label. */
export function confidence(ds: Dataset, sid: string, iid: string): Confidence {
  const blk = ds.metrics["scenarios"][sid]["initiatives"][iid] as Row;
  const init = ds.metrics["initiatives"][iid] as Row;
  const points = [
    { key: "baseline", ok: blk["capacity_released"]["baseline_version"] !== null, why: blk["capacity_released"]["baseline_version"] !== null ? `baseline ${blk["capacity_released"]["baseline_version"]} approved` : "no approved baseline" },
    { key: "benefits", ok: Object.values(blk["benefit_realization"] as Row).some((r) => (r as Row)["comparable_items"].length > 0), why: "matured benefit rows with an observation" },
    { key: "adoption", ok: init["adoption"]["adoption_rate"] !== null, why: "an adoption rate with its denominator" },
    { key: "costs", ok: blk["cost_variance"]["variance"] !== null, why: "actual cost against the approved baseline cost" },
  ];
  const score = points.filter((p) => p.ok).length;
  return { label: score >= 3 ? "strong" : score === 2 ? "partial" : "thin", points, score };
}

/** Periods in which an initiative's benefit rows fall (all rows, not only those inside a scenario horizon). */
export function benefitWindow(ds: Dataset, iid: string): { from: number; to: number; rows: number } | null {
  const ps = ds.result.population.acc.benefit_items.filter((b) => b["initiative_id"] === iid).map((b) => b["period_index"] as number);
  return ps.length ? { from: Math.min(...ps), to: Math.max(...ps) + 1, rows: ps.length } : null;
}

/** Partial baseline-trend coverage (R9-13): the domain reports `trend_coverage.complete` false, and `observed_above_trend` is null with PARTIAL_TREND_COVERAGE. */
export function partialTrend(ds: Dataset, iid: string, type: string, sid: string): boolean {
  const r = ds.metrics["scenarios"][sid]["initiatives"][iid]["benefit_realization"][type] as Row | undefined;
  const cov = r?.["trend_coverage"] as Row | undefined;
  return !!cov && cov["complete"] === false && r?.["baseline_trend"] !== null;
}
