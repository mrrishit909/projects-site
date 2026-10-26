// Metric aggregation (D-01, D-04, D-05). Rates come from aggregated numerators and denominators.
// computeMetrics returns exactly the keys of expected.json. Paused intervals that contribute no business
// hours are reported separately as flags (P02-TEST-03). Durations are integer ms; strings come from exact
// BigInt ratios (time.ts). Mirrors domain/onboard_studio/metrics.py.
import { effectiveIntervals, merge, overlapMs, type Interval } from "./calendar";
import { DomainError, INVALID_WINDOW } from "./errors";
import { acceptedTypesLatest } from "./workflow";
import { hoursFixed, isoZ, msBetween, parseTs, rate6 } from "./time";
import type { CaseFigures, Flag, Metrics, PausePolicyOverride, Population, SlaRule, Window } from "./types";

export const FLAG_PAUSE_OUTSIDE_WORKING = "PAUSE_OUTSIDE_WORKING_INTERVAL";
/** D-09: a completed case whose SLA calendar has no working interval cannot be evaluated against the SLA. */
export const FLAG_SLA_UNEVALUATED = "SLA_UNEVALUATED_NO_WORKING_TIME";
/** D-09: completed cases excluded from the SLA denominator because their calendar has no working interval. */
export const slaUnevaluatedCases = (flags: readonly Flag[]): number => flags.filter((f) => f.flag === FLAG_SLA_UNEVALUATED).length;
export const GROUP_KEYS = ["organization", "segment", "region", "workflow_version"] as const;
export type GroupKey = (typeof GROUP_KEYS)[number];
export const NO_WINDOW: Window = [null, null];

export function checkWindow([lo, hi]: Window): void {
  if (lo !== null && hi !== null && lo >= hi) {
    throw new DomainError(INVALID_WINDOW, "window start must be before end", undefined, { from: isoZ(lo), to: isoZ(hi) });
  }
}
/** Half-open [from, to) on opened_at. */
export const inWindow = (at: number, [lo, hi]: Window): boolean => (lo === null || at >= lo) && (hi === null || at < hi);

function policyFor(rule: SlaRule, override: PausePolicyOverride): readonly string[] {
  if (override === null) return rule.pause_policy;
  if (Array.isArray(override)) return override as readonly string[];
  return (override as Readonly<Record<string, readonly string[]>>)[rule.sla_rule_id] ?? rule.pause_policy;
}

export function buildCalendars(pop: Population): Map<string, Interval[]> {
  const working = new Map<string, Interval[]>();
  const holidays = new Map<string, Interval[]>();
  for (const ci of pop.calendar_intervals) {
    const into = ci.kind === "holiday" ? holidays : working;
    (into.get(ci.calendar_id) ?? into.set(ci.calendar_id, []).get(ci.calendar_id)!).push([ci.starts_at, ci.ends_at]);
  }
  const out = new Map<string, Interval[]>();
  for (const [cid, w] of working) out.set(cid, effectiveIntervals(w, holidays.get(cid) ?? []));
  return out;
}

const group = <T>(items: readonly T[], key: (x: T) => string): Map<string, T[]> => {
  const out = new Map<string, T[]>();
  for (const x of items) { const k = key(x); (out.get(k) ?? out.set(k, []).get(k)!).push(x); }
  return out;
};
const sum = (xs: readonly number[]): number => xs.reduce((a, b) => a + b, 0);

export interface MetricsRun { metrics: Metrics; flags: Flag[]; perCase: CaseFigures[] }

/** Restrict a population to some cases and everything that hangs off them (index maps, no nested scans). */
export function subsetPopulation(pop: Population, caseIds: ReadonlySet<string>): Population {
  const steps = new Set(pop.step_instances.filter((s) => caseIds.has(s.case_id)).map((s) => s.step_instance_id));
  return {
    ...pop,
    cases: pop.cases.filter((c) => caseIds.has(c.case_id)),
    step_instances: pop.step_instances.filter((s) => caseIds.has(s.case_id)),
    assignments: pop.assignments.filter((a) => steps.has(a.step_instance_id)),
    document_versions: pop.document_versions.filter((d) => caseIds.has(d.case_id)),
    approvals: pop.approvals.filter((a) => steps.has(a.step_instance_id)),
    waiting_intervals: pop.waiting_intervals.filter((w) => caseIds.has(w.case_id)),
    case_events: pop.case_events.filter((e) => caseIds.has(e.case_id)),
  };
}

export function computeWithFlags(popIn: Population, pausePolicy: PausePolicyOverride = null, cutoffs: Iterable<string> = [], window: Window = NO_WINDOW): MetricsRun {
  checkWindow(window);
  const cases = popIn.cases.filter((c) => inWindow(c.opened_at, window));
  const pop = cases.length === popIn.cases.length ? popIn : subsetPopulation(popIn, new Set(cases.map((c) => c.case_id)));
  const calendars = buildCalendars(pop);
  const sla = new Map(pop.sla_rules.map((r) => [r.workflow_version_id, r]));
  const flags: Flag[] = [];
  const perCase: CaseFigures[] = [];

  const doneWithRule = cases.filter((c) => c.completed_at !== null && sla.has(c.workflow_version_id));
  const completed = doneWithRule.filter((c) => calendars.has(sla.get(c.workflow_version_id)!.calendar_id));
  for (const c of doneWithRule) { // D-09: unevaluated, excluded from every mean and from the SLA denominator
    if (!calendars.has(sla.get(c.workflow_version_id)!.calendar_id)) flags.push({ case_id: c.case_id, flag: FLAG_SLA_UNEVALUATED });
  }
  const waitsByCase = group(pop.waiting_intervals, (w) => w.case_id);

  const calMs: number[] = [], busMs: number[] = [], pausedMs: number[] = [], povMs: number[] = [], actMs: number[] = [];
  let within = 0;
  for (const c of completed) {
    const rule = sla.get(c.workflow_version_id)!;
    const working = calendars.get(rule.calendar_id)!;
    const opened = c.opened_at, done = c.completed_at!;
    const eligible = new Set(policyFor(rule, pausePolicy));
    const business = overlapMs(opened, done, working);
    const clipped: Interval[] = [];
    const waits = [...(waitsByCase.get(c.case_id) ?? [])].sort((a, b) => a.starts_at - b.starts_at || (a.waiting_interval_id < b.waiting_interval_id ? -1 : a.waiting_interval_id > b.waiting_interval_id ? 1 : 0));
    for (const w of waits) {
      if (!eligible.has(w.reason_code)) continue; // customer waiting that is not pause-eligible is neither deducted nor hidden
      const lo = Math.max(w.starts_at, opened), hi = Math.min(w.ends_at ?? done, done);
      if (hi <= lo) continue;
      if (overlapMs(lo, hi, working) === 0) flags.push({ waiting_interval_id: w.waiting_interval_id, case_id: c.case_id, flag: FLAG_PAUSE_OUTSIDE_WORKING });
      clipped.push([lo, hi]);
    }
    const union = merge(clipped);
    const paused = sum(union.map(([s, e]) => msBetween(s, e)));
    const pov = sum(union.map(([s, e]) => overlapMs(s, e, working)));
    const active = business > pov ? business - pov : 0;
    const cal = msBetween(opened, done);
    calMs.push(cal); busMs.push(business); pausedMs.push(paused); povMs.push(pov); actMs.push(active);
    const okExact = active <= rule.business_minutes * 60_000; // active hours x 60 <= business minutes
    if (okExact) within++;
    perCase.push({
      case_id: c.case_id, calendar_hours: hoursFixed(cal)!, business_hours: hoursFixed(business)!, paused_hours: hoursFixed(paused)!,
      paused_business_overlap_hours: hoursFixed(pov)!, active_hours: hoursFixed(active)!, within_sla: okExact, sla_minutes: rule.business_minutes,
    });
  }

  const backlog: Record<string, number> = {};
  for (const cut of cutoffs) {
    const t = parseTs(cut);
    backlog[isoZ(t)] = cases.reduce((n, c) => n + (c.opened_at <= t && (c.completed_at === null || c.completed_at > t) ? 1 : 0), 0);
  }

  const docsByCase = group(pop.document_versions, (d) => d.case_id);
  const submitted = cases.filter((c) => (docsByCase.get(c.case_id) ?? []).length > 0);
  const reworked = submitted.filter((c) => docsByCase.get(c.case_id)!.some((d) => d.review_status === "rejected"));

  const firsts = new Map<string, (typeof pop.document_versions)[number]>();
  for (const d of pop.document_versions) {
    const k = `${d.case_id}\u0000${d.document_type}`;
    const f = firsts.get(k);
    if (f === undefined || d.version_number < f.version_number) firsts.set(k, d);
  }
  const reviewed = [...firsts.values()].filter((d) => d.review_status === "accepted" || d.review_status === "rejected");
  const firstOk = reviewed.filter((d) => d.review_status === "accepted");

  let reqTotal = 0, reqOk = 0;
  for (const c of cases) {
    const required = pop.requirements[c.workflow_version_id] ?? [];
    const accepted = acceptedTypesLatest(docsByCase.get(c.case_id) ?? []); // D-06: the latest version decides
    reqTotal += required.length;
    reqOk += required.filter((t) => accepted.has(t)).length;
  }

  const perStep = new Map<string, Set<string>>(); // exact replays (same step, assignee and start) count once
  for (const a of pop.assignments) (perStep.get(a.step_instance_id) ?? perStep.set(a.step_instance_id, new Set()).get(a.step_instance_id)!).add(`${a.assignee_id}\u0000${a.assigned_at}`);
  let handoffs = 0;
  for (const v of perStep.values()) handoffs += v.size - 1;

  const caseWv = new Map(cases.map((c) => [c.case_id, c.workflow_version_id]));
  const stepWaits = new Map<string, number[]>(pop.step_definitions.map((s) => [s.step_definition_id, []]));
  for (const si of pop.step_instances) {
    const rule = sla.get(caseWv.get(si.case_id) ?? "");
    if (si.started_at === null || si.ready_at === null || rule === undefined || !calendars.has(rule.calendar_id)) continue;
    (stepWaits.get(si.step_definition_id) ?? stepWaits.set(si.step_definition_id, []).get(si.step_definition_id)!)
      .push(overlapMs(si.ready_at, si.started_at, calendars.get(rule.calendar_id)!));
  }
  const stepWaiting: Record<string, string | null> = {};
  for (const k of [...stepWaits.keys()].sort()) { const v = stepWaits.get(k)!; stepWaiting[k] = hoursFixed(sum(v), v.length); }

  const n = completed.length;
  const metrics: Metrics = {
    calendar_cycle_time_hours: hoursFixed(sum(calMs), n),
    business_cycle_time_hours: hoursFixed(sum(busMs), n),
    paused_time_hours: hoursFixed(sum(pausedMs), n),
    paused_business_overlap_hours: hoursFixed(sum(povMs), n),
    active_elapsed_hours: hoursFixed(sum(actMs), n),
    sla_attainment: rate6(within, n),
    completed_eligible_cases: n,
    within_sla_cases: within,
    open_backlog_at_cutoff: backlog,
    rework_rate: rate6(reworked.length, submitted.length),
    handoff_count: handoffs,
    step_waiting_time_hours: stepWaiting,
    first_pass_approval: rate6(firstOk.length, reviewed.length),
    document_completeness: rate6(reqOk, reqTotal),
    empty_population: cases.length === 0,
  };
  return { metrics, flags, perCase };
}

export function computeMetrics(pop: Population, pausePolicy: PausePolicyOverride = null, cutoffs: Iterable<string> = [], window: Window = NO_WINDOW): Metrics {
  return computeWithFlags(pop, pausePolicy, cutoffs, window).metrics;
}

/** Metrics per group of cases, keyed by the group value in sorted order. */
export function groupMetrics(pop: Population, by: GroupKey, pausePolicy: PausePolicyOverride = null, cutoffs: Iterable<string> = [], window: Window = NO_WINDOW): Record<string, Metrics> {
  checkWindow(window);
  const orgs = new Map(pop.organizations.map((o) => [o.organization_id, o]));
  const key: (c: Population["cases"][number]) => string =
    by === "organization" ? (c) => c.organization_id
    : by === "segment" ? (c) => orgs.get(c.organization_id)?.segment ?? "UNKNOWN"
    : by === "region" ? (c) => orgs.get(c.organization_id)?.region ?? "UNKNOWN"
    : (c) => c.workflow_version_id;
  const members = new Map<string, Set<string>>();
  for (const c of pop.cases) {
    if (!inWindow(c.opened_at, window)) continue;
    const k = key(c);
    (members.get(k) ?? members.set(k, new Set()).get(k)!).add(c.case_id);
  }
  const cuts = [...cutoffs];
  const out: Record<string, Metrics> = {};
  for (const g of [...members.keys()].sort()) out[g] = computeMetrics(subsetPopulation(pop, members.get(g)!), pausePolicy, cuts);
  return out;
}
