// The twelve metrics of expected.json (D-01..D-08), computed from a Population at asOf. Mirror of domain/trustledger/metrics.py.
// Facts timestamped after asOf do not exist yet: datasets registered later, runs later, issues detected later, versions valid later,
// observed edges, candidates and decisions later are left out. A disabled rule was still active before disabled_at. The optional half-open
// window [from, to) narrows the time-stamped facts a metric counts: issues by detected_at, observed lineage by observed_at, candidates by
// proposed_at and merge decisions by decided_at. Current-state measures (rules over the rows, timeliness, ownership, definitions) are snapshots.
import { METRIC_KEYS } from "./contract";
import { DomainError, INVALID_WINDOW } from "./errors";
import { classify, resolutionBlock, type IssueView } from "./issues";
import { matchingBlock } from "./matching";
import { measureRule, runOf, timelinessOf, type Measure } from "./measure";
import { cmp, populationTotal, ruleActiveAt, weightInForce, type Population, type Row, type RuleRun } from "./models";
import { p6, ratio } from "./num";
import { carriedFailures, dimensionScores, weightedBlock } from "./scoring";
import { definitionsBlocks, lineageBlock, ownershipBlock } from "./structure";
import { isoZ, timelinessState, type Instant } from "./time";
import { precisionBlock, type Truth } from "./verification";

export type Window = readonly [Instant | null, Instant | null];
export interface Computation {
  metrics: Row; rules: Row; definitions: Row; matching: Row; weight_version: string | null; empty_population: boolean;
  warnings: { code: string; path: string; message: string }[]; measures: Measure[]; views: IssueView[]; timeliness_probes: Row;
}

const inWindow = (t: Instant, w: Window | null | undefined): boolean => !w || ((w[0] === null || t >= w[0]) && (w[1] === null || t < w[1]));
export function checkWindow(w: Window | null | undefined): void {
  if (w && w[0] !== null && w[1] !== null && w[0] >= w[1]) throw new DomainError(INVALID_WINDOW, "from must be before to (the window is half-open)", "from");
}

/** The population as it stood at asOf (and inside the window for the time-stamped facts). */
export function at(pop: Population, asOf: Instant, window?: Window | null): Population {
  const ds = pop.datasets.filter((d) => d.registered_at <= asOf);
  const dsIds = new Set(ds.map((d) => d.dataset_id));
  const rules = pop.quality_rules.filter((r) => dsIds.has(r.dataset_id));
  const ruleIds = new Set(rules.map((r) => r.rule_id));
  const runs = pop.rule_runs.filter((r) => r.run_at <= asOf && ruleIds.has(r.rule_id));
  const runIds = new Set(runs.map((r) => r.rule_run_id));
  return {
    ...pop, datasets: ds, fields: pop.fields.filter((f) => dsIds.has(f.dataset_id)), quality_rules: rules, rule_runs: runs,
    issues: pop.issues.filter((i) => i.detected_at <= asOf && inWindow(i.detected_at, window) && runIds.has(i.rule_run_id)),
    lineage_edges: pop.lineage_edges.filter((e) => e.observed_at === null || (e.observed_at <= asOf && inWindow(e.observed_at, window))),
    metric_versions: pop.metric_versions.filter((m) => m.valid_from <= asOf), definition_changes: pop.definition_changes.filter((c) => c.changed_at <= asOf),
    match_candidates: pop.match_candidates.filter((c) => c.proposed_at <= asOf && inWindow(c.proposed_at, window)),
    merge_decisions: pop.merge_decisions.filter((m) => m.decided_at <= asOf && inWindow(m.decided_at, window)),
  };
}

type RunLike = Pick<RuleRun, "rule_version" | "eligible_count" | "failure_count"> & { rule_run_id: string | null };
/** Two runs of one rule are comparable only when their rule version (the eligibility definition) is the same; otherwise no rate is
 * compared and the reason is RULE_VERSION_DIFFERS (D-01, P07-TEST-12). */
export function compareRuns(prev: RunLike, cur: RunLike): Row {
  const same = prev.rule_version === cur.rule_version;
  const rate = (r: RunLike): string | null => p6(ratio(r.failure_count, r.eligible_count));
  return { previous_run_id: prev.rule_run_id, previous_rule_version: prev.rule_version, current_rule_version: cur.rule_version, comparable: same,
    reason: same ? null : "RULE_VERSION_DIFFERS", previous_eligible_count: prev.eligible_count, current_eligible_count: cur.eligible_count,
    failure_rate_previous: same ? rate(prev) : null, failure_rate_current: same ? rate(cur) : null };
}

/** All metrics at asOf under weightVersion (default: the version in force at asOf). */
export function compute(pop: Population, asOf: Instant, weightVersion?: string | null, window?: Window | null, truth?: Truth | null, empty?: boolean): Computation {
  checkWindow(window);
  const isEmpty = empty ?? populationTotal(pop) === 0;
  const wv = weightVersion || weightInForce(pop, asOf) || pop.weight_version;
  const p = at(pop, asOf, window);
  const warnings: Computation["warnings"] = [];

  const live = [...p.quality_rules].sort((a, b) => cmp(a.rule_id, b.rule_id)).filter((r) => ruleActiveAt(r, asOf));
  const noPattern = (r: (typeof live)[number]): boolean => r.rule_type === "validity" && !r.definition["pattern"];
  for (const r of live) if (noPattern(r)) warnings.push({ code: "RULE_NOT_MEASURABLE", path: `rules.runs.${r.rule_id}`, message: `validity rule ${r.rule_id} has no pattern` });
  const measures = live.filter((r) => !noPattern(r)).map((r) => measureRule(r, p, asOf));
  const runs: Row = Object.fromEntries(measures.map((m) => [m.rule.rule_id, runOf(m, wv, asOf)]));
  const byType = (t: string): Row => Object.fromEntries(measures.filter((m) => m.rule.rule_type === t).map((m) => [m.rule.rule_id, m.block]));

  const lastScheduled = new Map<string, RuleRun>();
  for (const r of p.rule_runs) {
    if (r.kind !== "scheduled" || r.run_at >= asOf) continue;
    const cur = lastScheduled.get(r.rule_id);
    if (!cur || r.run_at > cur.run_at || (r.run_at === cur.run_at && cmp(r.rule_run_id, cur.rule_run_id) > 0)) lastScheduled.set(r.rule_id, r);
  }
  const comparisons: Row = {};
  for (const m of measures) {
    const prev = lastScheduled.get(m.rule.rule_id);
    if (prev) comparisons[m.rule.rule_id] = compareRuns(prev, { rule_run_id: null, rule_version: m.rule.version_number, eligible_count: m.eligible, failure_count: m.failures });
  }
  const runCount = new Map<string, number>(), runRule = new Map<string, string>();
  for (const r of p.rule_runs) { runCount.set(r.rule_id, (runCount.get(r.rule_id) ?? 0) + 1); runRule.set(r.rule_run_id, r.rule_id); }
  const issueCount = new Map<string, number>();
  for (const i of p.issues) { const rid = runRule.get(i.rule_run_id)!; issueCount.set(rid, (issueCount.get(rid) ?? 0) + 1); }
  const disabled: Row = {};
  for (const r of p.quality_rules) {
    if (!ruleActiveAt(r, asOf)) disabled[r.rule_id] = { disabled_at: isoZ(r.disabled_at), disabled_reason: r.disabled_reason, runs_retained: runCount.get(r.rule_id) ?? 0, issues_retained: issueCount.get(r.rule_id) ?? 0 };
  }

  const tl: Row = {};
  for (const d of [...p.datasets].sort((a, b) => cmp(a.dataset_id, b.dataset_id))) { const t = timelinessOf(d, asOf); if (t) tl[d.dataset_id] = t; }
  const states = Object.values(tl).map((v) => v["state"]);
  const on = states.filter((s) => s === "on_time").length, pending = states.filter((s) => s === "pending").length;
  const evaluated = states.length - pending; // a pending occurrence is neither on time nor late (D-10 R7-01)
  const timeliness = { monitored_datasets: states.length, evaluated_datasets: evaluated, pending_count: pending, on_time_count: on, value: p6(ratio(on, evaluated)), datasets: tl };

  const views = classify(p, asOf);
  const carried = carriedFailures(p, asOf);
  const { weighted, critical } = weightedBlock(p, dimensionScores(measures), measures, views, wv, carried);
  const { coverage, definitions } = definitionsBlocks(p, asOf);
  const { block: matching, approved, reviewed } = matchingBlock(p);
  const metrics: Row = {
    completeness: byType("completeness"), validity: byType("validity"), uniqueness: byType("uniqueness"), relationship_integrity: byType("relationship"), timeliness,
    weighted_score: weighted, critical_failures: critical, resolution_time: resolutionBlock(views), ownership_coverage: ownershipBlock(p, asOf),
    definition_coverage: coverage, match_precision: precisionBlock(truth, approved, reviewed), lineage_coverage: lineageBlock(p),
  };
  if (JSON.stringify(Object.keys(metrics)) !== JSON.stringify(METRIC_KEYS)) throw new Error("metric keys out of contract order");
  if (metrics["match_precision"]["precision"] === null && approved.length) warnings.push({ code: "MATCH_TRUTH_UNAVAILABLE", path: "metrics.match_precision", message: "no synthetic truth names every decided record: precision is unknown (null), not 0" });
  if (Object.values(weighted["datasets"] as Row).some((v) => v["critical_override"])) warnings.push({ code: "CRITICAL_OVERRIDE", path: "metrics.weighted_score", message: "a score hides an open critical failure or issue: read critical_failures beside it" });
  if (!pop.weight_versions.length) warnings.push({ code: "NO_WEIGHT_VERSION", path: "weight_version", message: "no rule weight version is defined: scores are null" });
  const probes: Row = {};
  for (const c of pop.probe_timeliness) { // stated cases: the rule alone, no dataset, no population
    const { state, start, deadline } = timelinessState(c.timezone, c.local_time, c.grace_minutes, c.last_refreshed_at, c.as_of);
    probes[c.probe_id] = { as_of: isoZ(c.as_of), last_refreshed_at: isoZ(c.last_refreshed_at), evaluated_occurrence_utc: isoZ(start), deadline_utc: isoZ(deadline), state };
  }
  return { metrics, rules: { active_count: Object.keys(runs).length, runs, comparisons, disabled }, definitions, matching, weight_version: wv ?? null, empty_population: isEmpty, warnings, measures, views, timeliness_probes: probes };
}
