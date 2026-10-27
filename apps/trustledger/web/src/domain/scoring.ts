// The weighted quality score and the critical override (D-01, D-06).
// score = sum(dimension score x weight) / sum(weights of the measured dimensions), under the NAMED weight version. A dimension with no
// measured score (no active rule, or a zero denominator) is dropped from both sums; a dataset that measures nothing has a null score.
// Several active rules of one dimension on one dataset contribute the plain mean of their scores. Critical failures (failure counts of
// active critical rules on the current run) and open critical issues are counted separately and NEVER hidden by the score:
// `critical_override` is true if either is above 0, however high the score. A critical rule that is disabled while its latest run fails keeps counting
// that failure (and the override) until a verified rerun passes: disabling is not repair (D-10 R7-02).
import { DIMENSIONS } from "./contract";
import { DomainError, UNKNOWN_WEIGHT_VERSION } from "./errors";
import type { IssueView } from "./issues";
import type { Measure } from "./measure";
import { cmp, type Population, type Row } from "./models";
import type { Instant } from "./time";
import { div, fr, mul, p6, sumFr, type Fr } from "./num";

export type DimScores = Record<string, Record<string, Fr>>;
/** dataset -> dimension -> mean score of its measured rules. */
export function dimensionScores(measures: Measure[]): DimScores {
  const acc: Record<string, Record<string, Fr[]>> = {};
  for (const m of measures) if (m.value !== null) ((acc[m.rule.dataset_id] ??= {})[m.rule.rule_type] ??= []).push(m.value);
  const out: DimScores = {};
  for (const [ds, dims] of Object.entries(acc)) { out[ds] = {}; for (const [dim, v] of Object.entries(dims)) out[ds]![dim] = div(sumFr(v), fr(v.length)); }
  return out;
}

/** Failures of disabled critical rules that are still live: the rule's latest run (by run_at, a rerun included) at asOf has failures. A later passing rerun is the latest run, which clears it. */
export function carriedFailures(pop: Population, asOf: Instant): Row[] {
  const latest = new Map<string, Population["rule_runs"][number]>();
  for (const r of pop.rule_runs) {
    const cur = latest.get(r.rule_id);
    if (!cur || r.run_at > cur.run_at || (r.run_at === cur.run_at && cmp(r.rule_run_id, cur.rule_run_id) > 0)) latest.set(r.rule_id, r);
  }
  const out: Row[] = [];
  for (const rule of [...pop.quality_rules].sort((a, b) => cmp(a.rule_id, b.rule_id))) {
    const run = latest.get(rule.rule_id);
    const active = rule.status === "active" || (rule.disabled_at !== null && rule.disabled_at > asOf);
    if (rule.severity === "critical" && !active && run && run.failure_count > 0) out.push({ dataset_id: rule.dataset_id, rule_id: rule.rule_id, rule_run_id: run.rule_run_id, failure_count: run.failure_count });
  }
  return out;
}

export function weightsOf(pop: Population, version: string | null): Record<string, Fr> {
  for (const w of pop.weight_versions) if (w.weight_version === version) return w.weights;
  throw new DomainError(UNKNOWN_WEIGHT_VERSION, `unknown weight version ${JSON.stringify(version)}`, "weight_version");
}

export function score(scores: Record<string, Fr>, weights: Record<string, Fr>): { measured: string[]; wsum: Fr; value: Fr | null } {
  const measured = DIMENSIONS.filter((d) => d in scores);
  const wsum = sumFr(measured.map((d) => weights[d]!));
  if (!measured.length || wsum.n === 0n) return { measured, wsum, value: null };
  return { measured, wsum, value: div(sumFr(measured.map((d) => mul(weights[d]!, scores[d]!))), wsum) };
}

export function weightedBlock(pop: Population, dimScores: DimScores, measures: Measure[], views: IssueView[], version: string | null, carried: Row[] = []): { weighted: Row; critical: Row } {
  const hasW = pop.weight_versions.length > 0;
  const w = hasW ? weightsOf(pop, version) : {};
  const dsOut: Row = {};
  const wvs = [...pop.weight_versions].sort((a, b) => cmp(a.weight_version, b.weight_version));
  const byVersion: Row = Object.fromEntries(wvs.map((x) => [x.weight_version, {}]));
  let cfTotal = 0, ciTotal = 0, over = 0;
  for (const ds of pop.datasets.map((d) => d.dataset_id).sort(cmp)) {
    const sc = dimScores[ds] ?? {};
    const r = hasW ? score(sc, w) : { measured: DIMENSIONS.filter((d) => d in sc), wsum: fr(0), value: null as Fr | null };
    const cf = measures.filter((m) => m.rule.dataset_id === ds && m.rule.severity === "critical").reduce((a, m) => a + m.failures, 0)
      + carried.filter((c) => c["dataset_id"] === ds).reduce((a, c) => a + (c["failure_count"] as number), 0);
    const ci = views.filter((v) => v.rule.severity === "critical" && v.cls !== "resolved" && v.rule.dataset_id === ds).length;
    const ov = cf > 0 || ci > 0;
    dsOut[ds] = { weight_version: version, dimension_scores: Object.fromEntries(r.measured.map((d) => [d, p6(sc[d]!)])), measured_dimensions: r.measured, weight_sum: p6(r.wsum),
      value: p6(r.value), critical_failures: cf, critical_open_issues: ci, critical_override: ov };
    cfTotal += cf; ciTotal += ci; over += ov ? 1 : 0;
    for (const x of pop.weight_versions) byVersion[x.weight_version][ds] = p6(score(sc, x.weights).value);
  }
  return { weighted: { datasets: dsOut, by_weight_version: byVersion }, critical: { failures: cfTotal, open_issues: ciTotal, datasets_overridden: over, carried } };
}
