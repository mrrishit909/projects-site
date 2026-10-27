// Derived figures shared by the views and the checks: everything is computed from the dataset with the domain's own functions, so a figure on a
// page and the same figure in scripts/golden-check.ts come from the same code. Strings in, strings out; the only numbers are counts and positions.
import type { Population, TestRow } from "../data/dataset";
import { rankTest } from "../data/dataset";
import { calibrationBins, economics, evaluateRanked, inBin, psi, topK, type Economics, type Item } from "../domain/metrics";
import type { Row } from "../domain/models";
import { div, fr, p6, parseFraction, pp2, ratio, scaledOfFr, scaledToString, sub, sumFr } from "../domain/num";

export const DEFAULT_DRIFT_BINS: Row[] = [{ label: "0", lower: 0, upper: 1 }, { label: "1-2", lower: 1, upper: 3 }, { label: "3+", lower: 3, upper: null }];
export const DRIFT_FLOOR = "0.000100", DRIFT_THRESHOLD = "0.200000";
export const REFUSAL_K = "CAPACITY_EXCEEDS_POPULATION";

export interface KResult { k: number; hits: number; precision: string; recall: string | null; lift: string | null; tie_split: boolean }
/** Precision, recall and risk lift at K, or the refusal when K is outside 1..n. */
export function kAt(items: Item[], k: number): KResult | typeof REFUSAL_K {
  const n = items.length;
  if (!(Number.isInteger(k) && k >= 1 && k <= n)) return REFUSAL_K;
  const positives = items.filter((i) => i.y).length;
  const t = topK(items, k, positives);
  return { k, hits: t.hits, precision: t.precision_at_k["value"], recall: t.recall_at_k["value"], lift: t.risk_lift_at_k["value"], tie_split: t.risk_lift_at_k["tie_split_at_k"] };
}
export interface EcoAt { k: number; contact_budget: string; expected_value: string; economics: Economics }
/** Contact budget and hypothetical expected value for the top K of a ranked population under a scenario's assumptions. */
export function ecoAt(items: Item[], k: number, scenario: { contact_cost: string; assumed_effect: string; margin_value: string; scenario_id?: string }): EcoAt | typeof REFUSAL_K {
  if (!(Number.isInteger(k) && k >= 1 && k <= items.length)) return REFUSAL_K;
  const e = economics({ scenario_id: "simulation", ...scenario }, items.slice(0, k));
  return { k, contact_budget: e.contact_budget, expected_value: e.expected_value, economics: e };
}
export interface Block {
  n: number; positives: number; average_precision: string | null; prevalence: string | null; brier_score: string | null; bins: ReturnType<typeof calibrationBins>;
  k: Record<string, KResult | typeof REFUSAL_K>; economics: Record<string, { k: number; contact_budget: string; expected_value: string }>;
}
/** One population under one model: the figures the models, calibration and capacity pages show. `ks` and `scenarios` are optional extras. */
export function blockOf(items: Item[], ks: readonly number[] = [], scenarios: Row[] = []): Block {
  const e = evaluateRanked(items, null, false);
  const eco: Block["economics"] = {};
  for (const s of scenarios) {
    const r = ecoAt(items, Math.min(s["capacity"], items.length), s as never);
    if (r !== REFUSAL_K) eco[s["scenario_id"]] = { k: r.k, contact_budget: r.contact_budget, expected_value: r.expected_value };
  }
  return { n: e.n, positives: e.positives, average_precision: e.average_precision.value, prevalence: e.average_precision.prevalence, brier_score: e.brier_score.value, bins: e.calibration.bins,
    k: Object.fromEntries(ks.map((k) => [String(k), kAt(items, k)])), economics: eco };
}
export const seriesOf = (pop: Population, key: string): Item[] => pop.models.find((m) => m.key === key)?.items ?? [];

export interface Gap { gap_pp: string | null; mean_predicted: string | null; n: number; observed_rate: string | null; positives: number }
/** Mean predicted risk minus observed churn, in percentage points, on a group of test rows under the calibrated probabilities. */
export function gapOf(rows: TestRow[], column: "logistic_calibrated" | "logistic_uncalibrated" = "logistic_calibrated"): Gap {
  const n = rows.length, positives = rows.filter((r) => r.y === 1).length;
  const mean = n ? div(sumFr(rows.map((r) => parseFraction(r.p[column], false))), fr(n)) : null;
  const obs = ratio(positives, n);
  return { gap_pp: mean && obs ? pp2(sub(mean, obs)) : null, mean_predicted: p6(mean), n, observed_rate: p6(obs), positives };
}
/** The same gap for a ranked evaluation population (a series of items). */
export function gapOfItems(items: Item[]): Gap {
  const n = items.length, positives = items.filter((i) => i.y).length;
  const mean = n ? div(sumFr(items.map((i) => i.p)), fr(n)) : null;
  const obs = ratio(positives, n);
  return { gap_pp: mean && obs ? pp2(sub(mean, obs)) : null, mean_predicted: p6(mean), n, observed_rate: p6(obs), positives };
}
export const groupGaps = (rows: TestRow[], key: "segment" | "region", column: "logistic_calibrated" | "logistic_uncalibrated" = "logistic_calibrated"): Record<string, Gap> =>
  Object.fromEntries([...new Set(rows.map((r) => r[key]))].sort().map((g) => [g, gapOf(rows.filter((r) => r[key] === g), column)]));

export interface PsiResult { psi: string | null; exceeds: boolean | null; reference_rows: number; current_rows: number; bins: { label: string; reference_count: number; current_count: number; reference_proportion: string; current_proportion: string; floored: boolean; term: string }[] }
/** Population stability index of usage_events_30d on the declared bins (D-P10-10): the natural log is the BigInt fixed-point one of num.ts. */
export function psiFor(ref: TestRow[], cur: TestRow[]): PsiResult {
  const count = (rows: TestRow[]): number[] => DEFAULT_DRIFT_BINS.map((b) => rows.filter((r) => inBin(r.usage_events_30d, b)).length);
  const rc = count(ref), cc = count(cur);
  const res = psi(rc, cc, DEFAULT_DRIFT_BINS.map((b) => b["label"]), DRIFT_FLOOR);
  return { psi: res ? scaledToString(res.total, 6) : null, exceeds: res ? res.total > scaledOfFr(parseFraction(DRIFT_THRESHOLD, false)) : null, reference_rows: rc.reduce((a, b) => a + b, 0), current_rows: cc.reduce((a, b) => a + b, 0), bins: res ? res.bins : [] };
}
export interface RegionDrift { all_accounts: PsiResult; apac: PsiResult; other_regions: PsiResult }
/** The PSI of each test cutoff against the first, for everyone, for apac and for the other regions: the whole population hides the apac cohort. */
export function driftByRegion(rows: TestRow[], cutoffs: number): RegionDrift[] {
  const ref = rows.filter((r) => r.cut === 0);
  return Array.from({ length: cutoffs }, (_, i) => {
    const cur = rows.filter((r) => r.cut === i);
    return {
      all_accounts: psiFor(ref, cur), apac: psiFor(ref.filter((r) => r.region === "apac"), cur.filter((r) => r.region === "apac")),
      other_regions: psiFor(ref.filter((r) => r.region !== "apac"), cur.filter((r) => r.region !== "apac")),
    };
  });
}
/** Churn by a grouping of the test rows (observed rate and count). */
export function churnBy(rows: TestRow[], key: "segment" | "region"): { group: string; n: number; churned: number; rate: string | null }[] {
  return [...new Set(rows.map((r) => r[key]))].sort().map((g) => { const sub = rows.filter((r) => r[key] === g); const c = sub.filter((r) => r.y === 1).length; return { group: g, n: sub.length, churned: c, rate: p6(ratio(c, sub.length)) }; });
}
export const rankOf = (rows: TestRow[], model: Parameters<typeof rankTest>[1]): Item[] => rankTest(rows, model);
