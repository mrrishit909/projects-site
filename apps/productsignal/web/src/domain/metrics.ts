// The metrics (D-01..D-05): signup conversion, funnel, activation, retention, feature adoption and the experiment block. Mirror of
// domain/productsignal/metrics.py. Everything is exact (rationals, BigInt fixed point), rounded ROUND_HALF_UP once; a zero
// denominator is null, never 0.
import { INVALID_GROUP, METRIC_KEYS, SEGMENT_FIELDS, WEEK4, GRID_DAYS } from "./contract";
import { canonicalise, identityStats, trackingQuality, type AEvent, type Canon, type IdentityStats, type TrackingQuality } from "./events";
import type { Assignment, FunnelDef, Plan, Population, Windows } from "./models";
import {
  DomainError, S, add, fr, fracOf, fxFrac, fxOf, fxMul, fxQ, fxSqrt, lt, mul, q, q6, ratio, sub, div, ZERO, ONE, sumF, type Frac, le,
} from "./num";
import { chi2SfDf1, newcombe, normalTwoSidedP, sqrtFrac, tCrit, wilson, zCrit } from "./stats";
import { DAY, HOUR, dayIso, isoZ, localDay } from "./time";

export interface Win { from: string; to: string }
export interface SignupOut { window: Win; unit: string; visitors: number; signed_up: number; rate: string | null }
export interface StepOut { step: string; units: number; conversion_from_previous: string | null; conversion_from_first: string | null }
export interface FunnelOut { definition_id: string; version: number; max_gap_hours: number; window: Win; steps: StepOut[]; overall_conversion: string | null }
export interface ActivationOut { window: Win; window_days: number; signups: number; immature_excluded: number; mature_accounts: number; activated: number; rate: string | null }
export interface RetentionOut {
  signup_window: Win; calendar: string; cohort_accounts: number; excluded_internal_accounts: number;
  day7: { mature_accounts: number; immature_excluded: number; retained: number; rate: string | null };
  on_or_after_day7: { mature_accounts: number; retained: number; rate: string | null };
  week4: { mature_accounts: number; immature_excluded: number; retained: number; rate: string | null };
}
export interface AdoptionOut { window: Win; feature: string; eligible_plans: string[]; eligible_accounts: number; adopting_accounts: number; use_events: number; rate: string | null }
export interface SrmOut { observed: Record<string, number>; expected: Record<string, string> | null; statistic: string | null; p_value: string | null; df?: number; verdict: "OK" | "MISMATCH" | "INSUFFICIENT" }
export interface IntervalOut { method: string; confidence: string; z: string; low: string; high: string; low_pp: string; high_pp: string; includes_zero: boolean }
export interface VariantOut { assigned: number; mature_units: number; activated: number; conversion: string | null; wilson_95: { low: string; high: string } | null }
export interface RunOut {
  analysis_id: string | null; cutoff_at: string; planned_end: string; interim: boolean; prior_runs: number | null; plan_frozen: boolean;
  config_hash: string; config_hash_matches_plan: boolean;
}
export interface RevenueVariant { units: number; total: string; mean: string | null; interval: { df: number; t: string; low: string; high: string } | null }
export interface ExperimentOut {
  experiment_version_id: string; unit_type: string; allocation: Record<string, string>; run: RunOut; assigned_units: number; mature_units: number;
  immature_or_unobserved_excluded: number; srm: SrmOut;
  primary: { metric: string; analysis: string; variants: Record<string, VariantOut>; absolute_lift_pp: string | null; relative_lift: string | null; interval: IntervalOut | null; conclusive: boolean };
  exposure: { definition: string; by_variant: Record<string, { exposed: number; units: number; rate: string | null }>; overall: { exposed: number; units: number; rate: string | null } };
  exploratory_exposed_only: { label: string; decision_basis: boolean; by_variant: Record<string, { exposed_units: number; activated: number; conversion: string | null }> };
  guardrail: { metric: string; window_days: number; by_variant: Record<string, { eligible_units: number; units_with_error: number; error_rate: string | null }> };
  revenue_per_assigned_account: { currency: string; window: Win; by_variant: Record<string, RevenueVariant> };
  observations: { rows_accepted: number; rows_matching_events: number };
}
export interface Metrics {
  signup_conversion: SignupOut; funnel: FunnelOut | null; activation: ActivationOut; retention: RetentionOut; feature_adoption: AdoptionOut; experiment: ExperimentOut | null;
}
export interface Warning { code: string; message: string; path: string }
export interface Computation {
  metrics: Metrics; tracking_quality: TrackingQuality; identity: IdentityStats; empty_population: boolean; canon: Canon; warnings: Warning[]; experiment_version_id: string | null;
}

const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
const win = (a: number, b: number): Win => ({ from: isoZ(a), to: isoZ(b) });

/** What the metrics share for one cutoff: canonical events, account signups, sessions and (optionally) the set of accounts an
 *  analysis is restricted to (a segment, a variant, a pre-assignment exclusion). */
export class Ctx {
  readonly users: Map<string, Population["users"][number]>;
  readonly accounts: Map<string, Population["accounts"][number]>;
  readonly signupAt = new Map<string, number>();
  readonly actEvents = new Map<string, number[]>();
  readonly errors = new Map<string, number[]>();
  readonly sess = new Map<string, number[]>();
  readonly props: Map<string, Map<string, string>>;
  constructor(readonly pop: Population, readonly cutoff: number, readonly canon: Canon, readonly allowed: ReadonlySet<string> | null = null) {
    this.users = new Map(pop.users.map((u) => [u.user_id, u]));
    this.accounts = new Map(pop.accounts.map((a) => [a.account_id, a]));
    this.props = canon.props;
    const push = (m: Map<string, number[]>, k: string, t: number): void => { const a = m.get(k); if (a) a.push(t); else m.set(k, [t]); };
    for (const a of canon.analysed) {
      if (a.account === null || !this.ok(a.account)) continue;
      if (a.name === "signup") { const cur = this.signupAt.get(a.account); if (cur === undefined || a.at < cur) this.signupAt.set(a.account, a.at); }
      else if (a.name === "activated") push(this.actEvents, a.account, a.at);
      else if (a.name === "product_error") push(this.errors, a.account, a.at);
    }
    for (const s of pop.sessions) {
      const u = this.users.get(s.user_id);
      if (!u || u.bot_flag || this.accounts.get(u.account_id)!.internal || !this.ok(u.account_id)) continue;
      if (s.started_at < cutoff) push(this.sess, u.account_id, s.started_at);
    }
  }
  ok(account: string): boolean { return this.allowed === null || this.allowed.has(account); }
  local(account: string, t: number): number { return localDay(t, this.accounts.get(account)!.timezone); }
  activatedWithin(account: string, days: number): boolean {
    const s = this.signupAt.get(account)!;
    return (this.actEvents.get(account) ?? []).some((t) => s <= t && t < s + days * DAY);
  }
  mature(account: string, days: number): boolean { return this.signupAt.get(account)! + days * DAY <= this.cutoff; }
  /** Day indices (local calendar, day 0 = signup day) of the account's sessions. */
  dayIndices(account: string): number[] {
    const s0 = this.local(account, this.signupAt.get(account)!);
    return (this.sess.get(account) ?? []).map((t) => this.local(account, t) - s0);
  }
  /** Day `day` is complete: local signup date + day + 1 <= local cutoff date (day 7: day 8 has begun; D-02). */
  matured(account: string, day: number): boolean {
    return this.local(account, this.signupAt.get(account)!) + day + 1 <= localDay(this.cutoff, this.accounts.get(account)!.timezone);
  }
}

// ---------------------------------------------------------------------------------------------------- MET-01 .. MET-06
export function signupConversion(ctx: Ctx, w: Windows): SignupOut {
  const inWin = (t: number): boolean => w.signup_from <= t && t < w.signup_to;
  const visitors = new Set<string>();
  for (const a of ctx.canon.analysed) if (a.name === "visit" && a.event.anonymous_id && inWin(a.at)) visitors.add(a.event.anonymous_id);
  const signed = new Set<string>();
  for (const a of ctx.canon.analysed) if (a.name === "signup" && a.event.anonymous_id && visitors.has(a.event.anonymous_id) && inWin(a.at)) signed.add(a.event.anonymous_id);
  return { window: win(w.signup_from, w.signup_to), unit: "distinct anonymous_id", visitors: visitors.size, signed_up: signed.size, rate: q6(ratio(signed.size, visitors.size)) };
}

/** Ordered steps with a maximum gap (inclusive); a unit reaches step k only after step k-1; no re-anchoring (D-02/D-P6-9). */
export function funnel(ctx: Ctx, fd: FunnelDef, window?: [number, number] | null): FunnelOut {
  const [fFrom, fTo] = window ?? [fd.window_from, fd.window_to];
  const gap = fd.max_gap_hours * HOUR;
  const byVk = new Map<string, AEvent[]>();
  for (const a of ctx.canon.analysed) { const l = byVk.get(a.visitor); if (l) l.push(a); else byVk.set(a.visitor, [a]); }
  const reached = fd.steps.map(() => new Set<string>());
  for (const [vk, evs] of byVk) {
    const first = evs.filter((a) => a.name === fd.steps[0] && fFrom <= a.at && a.at < fTo).map((a) => a.at).sort((x, y) => x - y);
    if (first.length === 0) continue;
    let prev = first[0]!;
    reached[0]!.add(vk);
    for (let k = 1; k < fd.steps.length; k++) {
      const nxt = evs.filter((a) => a.name === fd.steps[k] && prev < a.at && a.at <= prev + gap).map((a) => a.at).sort((x, y) => x - y);
      if (nxt.length === 0) break;
      reached[k]!.add(vk);
      prev = nxt[0]!;
    }
  }
  const steps: StepOut[] = fd.steps.map((name, k) => ({
    step: name, units: reached[k]!.size,
    conversion_from_previous: k === 0 ? null : q6(ratio(reached[k]!.size, reached[k - 1]!.size)),
    conversion_from_first: q6(ratio(reached[k]!.size, reached[0]!.size)),
  }));
  return { definition_id: fd.definition_id, version: fd.version, max_gap_hours: fd.max_gap_hours, window: win(fFrom, fTo), steps, overall_conversion: q6(ratio(reached[reached.length - 1]!.size, reached[0]!.size)) };
}

export function activation(ctx: Ctx, w: Windows): ActivationOut {
  const pop = [...ctx.signupAt].filter(([, s]) => w.activation_from <= s && s < w.activation_to).map(([a]) => a).sort(cmpStr);
  const mature = pop.filter((a) => ctx.mature(a, w.activation_days));
  const n = mature.filter((a) => ctx.activatedWithin(a, w.activation_days)).length;
  return { window: win(w.activation_from, w.activation_to), window_days: w.activation_days, signups: pop.length, immature_excluded: pop.length - mature.length, mature_accounts: mature.length, activated: n, rate: q6(ratio(n, mature.length)) };
}

/** Accounts whose signup date in the account's own calendar lies in [from, to). */
export function retentionCohort(ctx: Ctx, w: Windows): string[] {
  return [...ctx.signupAt.keys()].filter((a) => { const d = ctx.local(a, ctx.signupAt.get(a)!); return w.retention_from <= d && d < w.retention_to; }).sort(cmpStr);
}

export function retention(ctx: Ctx, w: Windows): RetentionOut {
  const cohort = retentionCohort(ctx, w);
  const m7 = cohort.filter((a) => ctx.matured(a, 7));
  const m35 = cohort.filter((a) => ctx.matured(a, WEEK4[1]));
  const d7 = m7.filter((a) => ctx.dayIndices(a).includes(7));
  const d7plus = m7.filter((a) => ctx.dayIndices(a).some((d) => d >= 7));
  const w4 = m35.filter((a) => ctx.dayIndices(a).some((d) => WEEK4[0] <= d && d <= WEEK4[1]));
  const internal = new Set<string>();
  for (const [a, t] of ctx.canon.internalSignups) if (ctx.ok(a)) { const d = ctx.local(a, t); if (w.retention_from <= d && d < w.retention_to) internal.add(a); }
  return {
    signup_window: { from: dayIso(w.retention_from), to: dayIso(w.retention_to) }, calendar: "account timezone", cohort_accounts: cohort.length, excluded_internal_accounts: internal.size,
    day7: { mature_accounts: m7.length, immature_excluded: cohort.length - m7.length, retained: d7.length, rate: q6(ratio(d7.length, m7.length)) },
    on_or_after_day7: { mature_accounts: m7.length, retained: d7plus.length, rate: q6(ratio(d7plus.length, m7.length)) },
    week4: { mature_accounts: m35.length, immature_excluded: cohort.length - m35.length, retained: w4.length, rate: q6(ratio(w4.length, m35.length)) },
  };
}

export interface GridCell { mature_accounts: number; retained: number; rate: string | null }
export interface GridRow { key: number; accounts: number; cells: Record<string, GridCell> }
export interface GridColumn { name: string; from_day: number; to_day: number | null }
/** Columns of the retention grid: exact calendar days, then the two ranges (never mixed, TEST-12). */
export const GRID_COLUMNS: { name: string; lo: number; hi: number | null; need: number }[] = [
  ...GRID_DAYS.map((d) => ({ name: `day${d}`, lo: d, hi: d as number | null, need: d })),
  { name: "on_or_after_day7", lo: 7, hi: null, need: 7 },
  { name: "week4", lo: WEEK4[0], hi: WEEK4[1], need: WEEK4[1] },
];
/** One row per key of the accounts (the local signup date for the contract's grid, the local signup week for the cohort page); a
 *  cell counts the accounts whose day has completed (mature) and those with a session on exactly that day (or in the range). */
export function retentionGrid(ctx: Ctx, accounts: readonly string[], keyOf: (account: string, localSignupDay: number) => number): GridRow[] {
  const by = new Map<number, string[]>();
  for (const a of accounts) {
    const k = keyOf(a, ctx.local(a, ctx.signupAt.get(a)!));
    const l = by.get(k);
    if (l) l.push(a); else by.set(k, [a]);
  }
  return [...by.keys()].sort((x, y) => x - y).map((key) => {
    const cells: Record<string, GridCell> = {};
    for (const c of GRID_COLUMNS) {
      const mat = by.get(key)!.filter((a) => ctx.matured(a, c.need));
      const hit = mat.filter((a) => ctx.dayIndices(a).some((d) => c.lo <= d && d <= (c.hi ?? 1e9)));
      cells[c.name] = { mature_accounts: mat.length, retained: hit.length, rate: q6(ratio(hit.length, mat.length)) };
    }
    return { key, accounts: by.get(key)!.length, cells };
  });
}
/** The contract's grid (one row per local signup date of the cohort window), in the published JSON shape. */
export function retentionGridWindow(ctx: Ctx, w: Windows): Record<string, unknown> {
  const rows = retentionGrid(ctx, retentionCohort(ctx, w), (_a, d) => d).map((r) => ({ cohort: dayIso(r.key), accounts: r.accounts, cells: r.cells }));
  return { cohort_unit: "account-local signup date", calendar: "account timezone", columns: GRID_COLUMNS.map((c) => ({ name: c.name, from_day: c.lo, to_day: c.hi })), rows };
}

export function featureAdoption(ctx: Ctx, w: Windows): AdoptionOut {
  const active = [...ctx.sess].filter(([, ss]) => ss.some((t) => w.adoption_from <= t && t < w.adoption_to)).map(([a]) => a);
  const eligible = active.filter((a) => w.eligible_plans.includes(ctx.accounts.get(a)!.plan)).sort(cmpStr);
  const el = new Set(eligible);
  const uses = ctx.canon.analysed.filter((a) => a.name === "feature_used" && a.account !== null && el.has(a.account) && w.adoption_from <= a.at && a.at < w.adoption_to
    && ctx.props.get(a.event.event_id)?.get("feature") === w.feature);
  const adopters = new Set(uses.map((a) => a.account));
  return { window: win(w.adoption_from, w.adoption_to), feature: w.feature, eligible_plans: [...w.eligible_plans], eligible_accounts: eligible.length, adopting_accounts: adopters.size, use_events: uses.length, rate: q6(ratio(adopters.size, eligible.length)) };
}

// ---------------------------------------------------------------------------------------------------- the experiment
/** The first accepted assignment per unit of the version; D-08: only assignments with assigned_at <= cutoff exist for the run. */
export function acceptedAssignments(pop: Population, xv: string, allowed: ReadonlySet<string> | null, cutoff: number | null = null): Map<string, Assignment> {
  const out = new Map<string, Assignment>();
  const list = pop.assignments.filter((a) => a.experiment_version_id === xv).sort((a, b) => a.assigned_at - b.assigned_at || cmpStr(a.assignment_id, b.assignment_id));
  for (const a of list) {
    if (cutoff !== null && a.assigned_at > cutoff) continue;
    if ((allowed === null || allowed.has(a.unit_id)) && !out.has(a.unit_id)) out.set(a.unit_id, a);
  }
  return out;
}

/** MET-10: chi-square against the prespecified allocation; verdict order INSUFFICIENT, MISMATCH, OK. */
export function srmBlock(plan: Plan, observed: Record<string, number>): SrmOut {
  const variants = plan.variants;
  const n = variants.reduce((t, v) => t + observed[v]!, 0);
  if (n === 0) return { observed, expected: null, statistic: null, p_value: null, verdict: "INSUFFICIENT" };
  const cells: Record<string, Frac> = {};
  for (const v of variants) cells[v] = mul(fr(n), fracOf(plan.allocation[v]!));
  const stat = sumF(variants.map((v) => { const d = sub(fr(observed[v]!), cells[v]!); return div(mul(d, d), cells[v]!); }));
  const pv = chi2SfDf1(stat);
  let verdict: SrmOut["verdict"];
  if (variants.some((v) => lt(cells[v]!, fr(plan.srm_min_expected_cell)))) verdict = "INSUFFICIENT";
  else if (pv < fxOf(fracOf(plan.srm_p_threshold))) verdict = "MISMATCH";
  else verdict = "OK";
  return { observed, expected: Object.fromEntries(variants.map((v) => [v, q(cells[v]!, 2)])), statistic: q6(stat), p_value: fxQ(pv, 6), df: variants.length - 1, verdict };
}

export function experiment(ctx: Ctx, plan: Plan, runId: string | null = null): ExperimentOut {
  const { pop, cutoff } = ctx;
  const xv = plan.experiment_version_id;
  const variants = plan.variants;
  const z = fracOf(plan.z);
  const accepted = acceptedAssignments(pop, xv, ctx.allowed, cutoff);
  const assigned: Record<string, Assignment[]> = {};
  for (const v of variants) assigned[v] = [...accepted.values()].filter((a) => a.variant === v);
  const nAssigned: Record<string, number> = Object.fromEntries(variants.map((v) => [v, assigned[v]!.length]));
  const win_ = plan.activation_window_days;
  const mat: Record<string, Assignment[]> = {};
  for (const v of variants) mat[v] = assigned[v]!.filter((a) => ctx.signupAt.has(a.unit_id) && ctx.mature(a.unit_id, win_));
  const nTotal = variants.reduce((t, v) => t + nAssigned[v]!, 0);
  const srm = srmBlock(plan, nAssigned);

  const act: Record<string, number> = {}, nM: Record<string, number> = {}, conv: Record<string, Frac | null> = {};
  for (const v of variants) { act[v] = mat[v]!.filter((a) => ctx.activatedWithin(a.unit_id, win_)).length; nM[v] = mat[v]!.length; conv[v] = ratio(act[v]!, nM[v]!); }
  const perVariant: Record<string, VariantOut> = {};
  for (const v of variants) {
    let w: VariantOut["wilson_95"] = null;
    if (nM[v]) { const [, lo, hi] = wilson(act[v]!, nM[v]!, z); w = { low: q(lo, 6), high: q(hi, 6) }; }
    perVariant[v] = { assigned: nAssigned[v]!, mature_units: nM[v]!, activated: act[v]!, conversion: q6(conv[v]!), wilson_95: w };
  }
  const c = "control", t = "treatment";
  const both = (nM[c] ?? 0) > 0 && (nM[t] ?? 0) > 0;
  const absLift = both ? sub(conv[t]!, conv[c]!) : null;
  const rel = !both || conv[c]!.n === 0n ? null : div(sub(conv[t]!, conv[c]!), conv[c]!);

  const runs = pop.analysis_runs.filter((r) => r.experiment_version_id === xv);
  const cand = runId ? runs.filter((r) => r.analysis_id === runId) : runs.filter((r) => r.cutoff_at === cutoff);
  const runRow = cand.length ? cand.reduce((m, r) => (r.created_at < m.created_at || (r.created_at === m.created_at && r.analysis_id < m.analysis_id) ? r : m)) : null;
  const hashOk = plan.hash_valid;
  const interim = cutoff < plan.planned_end;
  let interval: IntervalOut | null = null, conclusive = false;
  if (both) {
    const [, lo, hi] = newcombe(act[t]!, nM[t]!, act[c]!, nM[c]!, z);
    const includes0 = le(lo, ZERO) && le(ZERO, hi);
    interval = { method: "newcombe_hybrid_score", confidence: plan.confidence, z: plan.z, low: q(lo, 6), high: q(hi, 6), low_pp: q(mul(lo, fr(100)), 2), high_pp: q(mul(hi, fr(100)), 2), includes_zero: includes0 };
    conclusive = !includes0 && !interim && hashOk;
  }
  const prior = runRow === null ? null : runs.filter((r) => r.created_at < runRow.created_at).length;
  const runBlock: RunOut = {
    analysis_id: runRow ? runRow.analysis_id : null, cutoff_at: isoZ(cutoff), planned_end: isoZ(plan.planned_end), interim, prior_runs: prior,
    plan_frozen: runs.length > 0 && plan.frozen_at <= Math.min(...runs.map((r) => r.created_at)), config_hash: plan.config_hash,
    config_hash_matches_plan: hashOk && runRow !== null && runRow.config_hash === plan.config_hash,
  };

  const exposedIds = new Set(pop.exposures.filter((x) => x.exposed_at <= cutoff).map((x) => x.assignment_id)); // D-08
  const exposed: Record<string, number> = {};
  for (const v of variants) exposed[v] = mat[v]!.filter((a) => exposedIds.has(a.assignment_id)).length;
  const nMAll = variants.reduce((tt, v) => tt + nM[v]!, 0);
  const exposedAll = variants.reduce((tt, v) => tt + exposed[v]!, 0);
  const exposure = {
    definition: "exposed mature assigned accounts / mature assigned accounts",
    by_variant: Object.fromEntries(variants.map((v) => [v, { exposed: exposed[v]!, units: nM[v]!, rate: q6(ratio(exposed[v]!, nM[v]!)) }])),
    overall: { exposed: exposedAll, units: nMAll, rate: q6(ratio(exposedAll, nMAll)) },
  };
  const exploratory: ExperimentOut["exploratory_exposed_only"] = { label: "exploratory", decision_basis: false, by_variant: {} };
  for (const v of variants) {
    const ex = mat[v]!.filter((a) => exposedIds.has(a.assignment_id));
    const k = ex.filter((a) => ctx.activatedWithin(a.unit_id, win_)).length;
    exploratory.by_variant[v] = { exposed_units: ex.length, activated: k, conversion: q6(ratio(k, ex.length)) };
  }

  const gdays = plan.guardrail_window_days * DAY;
  const guard: ExperimentOut["guardrail"]["by_variant"] = {};
  for (const v of variants) {
    const hit = mat[v]!.filter((a) => (ctx.errors.get(a.unit_id) ?? []).some((e) => a.assigned_at <= e && e < a.assigned_at + gdays)).length;
    guard[v] = { eligible_units: nM[v]!, units_with_error: hit, error_rate: q6(ratio(hit, nM[v]!)) };
  }

  const revBy = new Map<string, bigint>();
  for (const s of pop.subscriptions) {
    if ((s.status === "active" || s.status === "ended") && plan.revenue_from <= s.starts_at && s.starts_at < plan.revenue_to && s.starts_at <= cutoff) { // D-08
      revBy.set(s.account_id, (revBy.get(s.account_id) ?? 0n) + s.amount_cents);
    }
  }
  const revenue: Record<string, RevenueVariant> = {};
  for (const v of variants) {
    const vals = mat[v]!.map((a) => revBy.get(a.unit_id) ?? 0n);
    const n = vals.length;
    if (n === 0) { revenue[v] = { units: 0, total: "0.00", mean: null, interval: null }; continue; }
    const tot = vals.reduce((x, y) => x + y, 0n);
    const meanF = fr(tot, 100n * BigInt(n)); // dollars
    if (n < 2) { revenue[v] = { units: n, total: q(fr(tot, 100n), 2), mean: q(meanF, 2), interval: null }; continue; }
    const sumSq = vals.reduce((x, y) => x + y * y, 0n);
    const varF = fr(BigInt(n) * sumSq - tot * tot, BigInt(n) * BigInt(n - 1) * 10_000n); // sample variance, dollars squared
    const tc = tCrit(n - 1, plan.confidence);
    const half = fxMul(tc, fxSqrt(fxOf(div(varF, fr(n)))));
    const meanFx = fxOf(meanF);
    revenue[v] = { units: n, total: q(fr(tot, 100n), 2), mean: q(meanF, 2), interval: { df: n - 1, t: fxQ(tc, 6), low: fxQ(meanFx - half, 2), high: fxQ(meanFx + half, 2) } };
  }

  const obsIds = new Map([...accepted.values()].map((a) => [a.assignment_id, a]));
  const obsOk = pop.metric_observations.filter((o) => obsIds.has(o.assignment_id) && o.window_end <= cutoff); // D-08
  let obsMatch = 0;
  for (const o of obsOk) {
    const u = obsIds.get(o.assignment_id)!.unit_id;
    if (ctx.signupAt.has(u)) {
      const want = ctx.activatedWithin(u, win_) ? "1" : "0";
      if (o.value === want && o.window_end === ctx.signupAt.get(u)! + win_ * DAY) obsMatch++;
    }
  }
  return {
    experiment_version_id: xv, unit_type: plan.unit_type, allocation: { ...plan.allocation }, run: runBlock, assigned_units: nTotal, mature_units: nMAll,
    immature_or_unobserved_excluded: nTotal - nMAll, srm,
    primary: { metric: plan.primary_metric, analysis: "intention_to_treat", variants: perVariant, absolute_lift_pp: absLift === null ? null : q(mul(absLift, fr(100)), 2), relative_lift: q6(rel), interval, conclusive },
    exposure, exploratory_exposed_only: exploratory, guardrail: { metric: plan.guardrail_metric, window_days: plan.guardrail_window_days, by_variant: guard },
    revenue_per_assigned_account: { currency: "USD", window: win(plan.revenue_from, plan.revenue_to), by_variant: revenue }, observations: { rows_accepted: obsOk.length, rows_matching_events: obsMatch },
  };
}

// ---------------------------------------------------------------------------------------------------- the whole set
export function selectFunnel(pop: Population, definitionId: string | null = null, version: number | null = null): FunnelDef | null {
  const cand = pop.funnels.filter((f) => (definitionId === null || f.definition_id === definitionId) && (version === null || f.version === version));
  if (cand.length === 0) return null;
  return cand.reduce((m, f) => (f.version > m.version ? f : m));
}
export function selectPlan(pop: Population, xv: string | null): Plan | null {
  if (xv !== null) return pop.plans.get(xv) ?? null;
  const all = [...pop.plans.values()];
  return all.length ? all.reduce((m, p) => (p.frozen_at > m.frozen_at || (p.frozen_at === m.frozen_at && p.experiment_version_id > m.experiment_version_id) ? p : m)) : null;
}

export function compute(pop: Population, cutoff: number, windows: Windows, funnelDef: FunnelDef | null = null, experimentVersionId: string | null = null,
  runId: string | null = null, allowed: ReadonlySet<string> | null = null, funnelWindow: [number, number] | null = null, canon: Canon | null = null): Computation {
  const cn = canon ?? canonicalise(pop, cutoff);
  const ctx = new Ctx(pop, cutoff, cn, allowed);
  const plan = selectPlan(pop, experimentVersionId);
  const warnings: Warning[] = [];
  const metrics: Metrics = {
    signup_conversion: signupConversion(ctx, windows), funnel: funnelDef ? funnel(ctx, funnelDef, funnelWindow) : null, activation: activation(ctx, windows),
    retention: retention(ctx, windows), feature_adoption: featureAdoption(ctx, windows), experiment: plan ? experiment(ctx, plan, runId) : null,
  };
  if (!funnelDef) warnings.push({ code: "NO_FUNNEL_DEFINITION", message: "no funnel is defined (C03 define-funnel)", path: "metrics.funnel" });
  if (!plan) warnings.push({ code: "NO_ANALYSIS_PLAN", message: "no frozen analysis plan: the experiment is not analysed", path: "metrics.experiment" });
  else {
    if (!plan.hash_valid) warnings.push({ code: "PLAN_HASH_MISMATCH", message: "config_hash is not the hash of the stored plan", path: "metrics.experiment.run.config_hash" });
    const ex = metrics.experiment!;
    if (ex.srm.verdict === "MISMATCH") warnings.push({ code: "SRM_MISMATCH", message: "the assignment counts do not match the allocation: no lift can be trusted and a ship decision is blocked", path: "metrics.experiment.srm" });
    if (ex.run.interim) warnings.push({ code: "INTERIM_RUN", message: "the cutoff is before planned_end: this is an interim run and cannot support a ship decision", path: "metrics.experiment.run.interim" });
  }
  const tq = trackingQuality(cn);
  if (tq.received_after_cutoff) warnings.push({ code: "EVENTS_RECEIVED_AFTER_CUTOFF", message: `${tq.received_after_cutoff} event(s) were received after the cutoff and are not in this run (a later cutoff will include them, as a disclosed revision)`, path: "tracking_quality.received_after_cutoff" });
  for (const [key, code, what] of [["unknown_identity", "UNKNOWN_IDENTITY_EXCLUDED", "with an unknown identity"], ["bot_events_excluded", "BOT_EVENTS_EXCLUDED", "of bot users"], ["internal_events_excluded", "INTERNAL_EVENTS_EXCLUDED", "of internal accounts"]] as const) {
    if (tq[key]) warnings.push({ code, message: `${tq[key]} event(s) ${what} are excluded from every figure`, path: `tracking_quality.${key}` });
  }
  const empty = cn.canon.length === 0 && (metrics.experiment === null || metrics.experiment.assigned_units === 0);
  void METRIC_KEYS;
  return { metrics, tracking_quality: tq, identity: identityStats(cn), empty_population: empty, canon: cn, warnings, experiment_version_id: plan ? plan.experiment_version_id : null };
}

// ---------------------------------------------------------------------------------------------------- groups and segments
export function groupValues(pop: Population, by: string, xv: string | null, cutoff: number | null = null): Map<string, Set<string>> {
  if (by === "none" || !["variant", "plan", "segment", "timezone"].includes(by)) throw new DomainError(INVALID_GROUP, "group_by must be one of none, variant, plan, segment, timezone", "group_by");
  const out = new Map<string, Set<string>>();
  const add_ = (k: string, v: string): void => { const s = out.get(k); if (s) s.add(v); else out.set(k, new Set([v])); };
  if (by === "variant") {
    if (xv === null) throw new DomainError(INVALID_GROUP, "group_by=variant needs an experiment_version_id", "group_by");
    for (const a of acceptedAssignments(pop, xv, null, cutoff).values()) add_(a.variant, a.unit_id);
  } else for (const a of pop.accounts) add_(by === "plan" ? a.plan : by === "segment" ? a.segment : a.timezone, a.account_id);
  return new Map([...out].sort((a, b) => cmpStr(a[0], b[0])));
}

export interface SegmentItem {
  value: string; label: string; decision_basis: boolean;
  variants: Record<string, { mature_units: number; activated: number; conversion: string | null }>;
  absolute_lift_pp: string | null; p_value: string | null;
  adjusted_interval: { confidence: string; z: string; low: string; high: string; includes_zero: boolean } | null; below_bonferroni_threshold: boolean;
}
export interface SegmentOut {
  label: string; decision_basis: boolean; by: string; segments_tested: number; alpha: string; bonferroni_threshold: string; correction: string; note: string; segments: SegmentItem[];
}
const hasBothArms = (pop: Population, plan: Plan, accounts: ReadonlySet<string>, cutoff: number): boolean => {
  const vs = new Set([...acceptedAssignments(pop, plan.experiment_version_id, accounts, cutoff).values()].map((a) => a.variant));
  return vs.has("control") && vs.has("treatment");
};

/** Exploratory segment results (D-03, P06-UI-08): every segment carries the label, the number of segments tested and the
 *  Bonferroni-adjusted threshold alpha / k. No decision may cite a segment. */
export function segmentAnalysis(pop: Population, cutoff: number, plan: Plan, by: string, canon: Canon | null = null): SegmentOut {
  if (!(SEGMENT_FIELDS as readonly string[]).includes(by)) throw new DomainError(INVALID_GROUP, `a segment analysis is by ${SEGMENT_FIELDS.join(", ")}`, "group_by");
  const cn = canon ?? canonicalise(pop, cutoff);
  const alpha = sub(ONE, fracOf(plan.confidence));
  const groups = groupValues(pop, by, null);
  const tested = [...groups.keys()].filter((k) => hasBothArms(pop, plan, groups.get(k)!, cutoff));
  const thr = div(alpha, fr(Math.max(tested.length, 1)));
  const zadj = tested.length > 0 ? zCrit(q(sub(ONE, thr), 6)) : null;
  const win_ = plan.activation_window_days;
  const segs: SegmentItem[] = [];
  for (const [val, set] of groups) {
    const ctx = new Ctx(pop, cutoff, cn, set);
    const acc = acceptedAssignments(pop, plan.experiment_version_id, set, cutoff);
    const cells: Record<string, [number, number]> = {};
    for (const v of plan.variants) {
      const m = [...acc.values()].filter((a) => a.variant === v && ctx.signupAt.has(a.unit_id) && ctx.mature(a.unit_id, win_));
      cells[v] = [m.filter((a) => ctx.activatedWithin(a.unit_id, win_)).length, m.length];
    }
    const [xc, nc] = cells["control"]!, [xt, nt] = cells["treatment"]!;
    const item: SegmentItem = {
      value: val, label: "exploratory", decision_basis: false,
      variants: Object.fromEntries(plan.variants.map((v) => [v, { mature_units: cells[v]![1], activated: cells[v]![0], conversion: q6(ratio(cells[v]![0], cells[v]![1])) }])),
      absolute_lift_pp: null, p_value: null, adjusted_interval: null, below_bonferroni_threshold: false,
    };
    if (nc && nt) {
      const d = sub(fr(xt, nt), fr(xc, nc));
      item.absolute_lift_pp = q(mul(d, fr(100)), 2);
      const pooled = fr(xt + xc, nt + nc);
      const se2 = mul(mul(pooled, sub(ONE, pooled)), add(fr(1, nt), fr(1, nc)));
      if (se2.n > 0n) {
        const zstat = div(d, sqrtFrac(se2));
        const pv = normalTwoSidedP(zstat);
        item.p_value = fxQ(pv, 6);
        item.below_bonferroni_threshold = pv * thr.d < thr.n * S;
      }
      const [, lo, hi] = newcombe(xt, nt, xc, nc, fxFrac(zadj!));
      item.adjusted_interval = { confidence: q(sub(ONE, thr), 6), z: fxQ(zadj!, 6), low: q(lo, 6), high: q(hi, 6), includes_zero: le(lo, ZERO) && le(ZERO, hi) };
    }
    segs.push(item);
  }
  return {
    label: "exploratory", decision_basis: false, by, segments_tested: tested.length, alpha: q(alpha, 6), bonferroni_threshold: q(thr, 6), correction: "bonferroni",
    note: "segment results are exploratory: a segment that looks different is a hypothesis for the next experiment, never a decision basis", segments: segs,
  };
}

// ---------------------------------------------------------------------------------------------------- guardrail review
export interface GuardrailReview {
  metric: string; window_days: number; prespecified: boolean; source: string; by_variant: ExperimentOut["guardrail"]["by_variant"]; difference_pp: string | null;
  interval: { method: string; confidence: string; z: string; low: string; high: string; includes_zero: boolean } | null; verdict: "OK" | "HARMFUL" | "INSUFFICIENT";
}
/** C09: HARMFUL when the whole Newcombe interval of the error-rate difference lies above 0 (more errors under treatment),
 *  INSUFFICIENT when a variant has no eligible unit, else OK. */
export function guardrailReview(block: ExperimentOut, plan: Plan): GuardrailReview {
  const g = block.guardrail;
  const c = g.by_variant["control"]!, t = g.by_variant["treatment"]!;
  const out: GuardrailReview = { metric: g.metric, window_days: g.window_days, prespecified: true, source: "frozen analysis plan", by_variant: g.by_variant, difference_pp: null, interval: null, verdict: "INSUFFICIENT" };
  if (c.eligible_units === 0 || t.eligible_units === 0) return out;
  const [d, lo, hi] = newcombe(t.units_with_error, t.eligible_units, c.units_with_error, c.eligible_units, fracOf(plan.z));
  out.difference_pp = q(mul(d, fr(100)), 2);
  out.interval = { method: "newcombe_hybrid_score", confidence: plan.confidence, z: plan.z, low: q(lo, 6), high: q(hi, 6), includes_zero: le(lo, ZERO) && le(ZERO, hi) };
  out.verdict = lt(ZERO, lo) ? "HARMFUL" : "OK";
  return out;
}

