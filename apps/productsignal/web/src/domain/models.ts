// Typed records, parsers, the frozen plan and the metric windows (mirror of domain/productsignal/models.py).
import { ID_KEYS, type Entity, DEFAULT_FEATURE } from "./contract";
import { DomainError, ZERO, fracOf, malformed, add, cmp, ONE } from "./num";
import { sha256 } from "./sha256";
import { DAY, isZone, parseDay, parseTs, utcDay } from "./time";

export type Row = Record<string, unknown>;
const NAME = /^[a-z][a-z0-9_]{0,63}$/;
const SHA = /^[0-9a-f]{64}$/;
const PROPORTION = /^(0|1)(\.\d{1,6})?$|^0?\.\d{1,6}$/;

function str(row: Row, name: string, optional = false, maxlen = 256): string | null {
  const v = row[name];
  if ((v === null || v === undefined) && optional) return null;
  if (typeof v !== "string" || v.trim() === "" || v.length > maxlen || v.includes("\u0000")) throw malformed(name, "must be a non-empty string");
  return v;
}
const req = (row: Row, name: string, maxlen = 256): string => str(row, name, false, maxlen)!;
function bool(row: Row, name: string): boolean {
  const v = row[name];
  if (typeof v !== "boolean") throw malformed(name, "must be true or false");
  return v;
}
const ts = (row: Row, name: string): number => parseTs(row[name], name);
const tsOpt = (row: Row, name: string): number | null => (row[name] === null || row[name] === undefined ? null : parseTs(row[name], name));
function tz(row: Row): string {
  const v = req(row, "timezone");
  if (!isZone(v)) throw malformed("timezone", `unknown IANA timezone '${v}'`);
  return v;
}

/** Money in cents: a decimal string with at most two decimals, 0 <= value < 10^12. */
export function moneyCents(value: unknown, name: string): bigint {
  if (typeof value !== "string" && !(typeof value === "number" && Number.isSafeInteger(value))) throw malformed(name, "must be a decimal string");
  const s = String(value).trim();
  const m = /^(\d+)(?:\.(\d+))?$/.exec(s);
  if (!m) throw malformed(name, "is not a decimal number");
  const frac = m[2] ?? "";
  if (/[1-9]/.test(frac.slice(2))) throw malformed(name, "carries more than 2 decimals");
  const cents = BigInt(m[1]! + frac.slice(0, 2).padEnd(2, "0"));
  if (cents >= 10n ** 14n) throw malformed(name, "is out of range");
  return cents;
}

export interface Account { account_id: string; plan: string; segment: string; created_at: number; internal: boolean; timezone: string }
export interface User { user_id: string; account_id: string; created_at: number; timezone: string; bot_flag: boolean }
export interface IdentityLink { identity_link_id: string; anonymous_id: string; user_id: string; linked_at: number; rule_version: string }
export interface Session { session_id: string; user_id: string; started_at: number; ended_at: number | null; device_type: string }
export interface Event { event_id: string; user_id: string | null; anonymous_id: string | null; event_name: string; event_at: number; received_at: number }
export interface EventProperty { property_id: string; event_id: string; property_key: string; property_value: string; value_type: string }
export interface Subscription { subscription_id: string; account_id: string; starts_at: number; ends_at: number | null; status: string; amount_cents: bigint }
export interface ExperimentVersion { experiment_version_id: string; name: string; unit_type: string; primary_metric: string; planned_end: number }
export interface Assignment { assignment_id: string; experiment_version_id: string; unit_id: string; variant: string; assigned_at: number }
export interface Exposure { exposure_id: string; assignment_id: string; exposed_at: number; surface: string; event_id: string | null }
export interface Observation { observation_id: string; assignment_id: string; metric_name: string; value: string; window_end: number }
export interface AnalysisRun { analysis_id: string; experiment_version_id: string; cutoff_at: number; config_hash: string; created_at: number }

export interface Records {
  accounts: Account; users: User; identity_links: IdentityLink; sessions: Session; events: Event; event_properties: EventProperty;
  subscriptions: Subscription; experiment_versions: ExperimentVersion; assignments: Assignment; exposures: Exposure;
  metric_observations: Observation; analysis_runs: AnalysisRun;
}

export const PARSERS: { [E in Entity]: (r: Row) => Records[E] } = {
  accounts: (r) => ({ account_id: req(r, "account_id"), plan: req(r, "plan"), segment: req(r, "segment"), created_at: ts(r, "created_at"), internal: bool(r, "internal"), timezone: tz(r) }),
  users: (r) => ({ user_id: req(r, "user_id"), account_id: req(r, "account_id"), created_at: ts(r, "created_at"), timezone: tz(r), bot_flag: bool(r, "bot_flag") }),
  identity_links: (r) => ({ identity_link_id: req(r, "identity_link_id"), anonymous_id: req(r, "anonymous_id"), user_id: req(r, "user_id"), linked_at: ts(r, "linked_at"), rule_version: req(r, "rule_version") }),
  sessions: (r) => ({ session_id: req(r, "session_id"), user_id: req(r, "user_id"), started_at: ts(r, "started_at"), ended_at: tsOpt(r, "ended_at"), device_type: req(r, "device_type") }),
  events: (r) => {
    const name = req(r, "event_name");
    if (!NAME.test(name)) throw malformed("event_name", "must be lower-case letters, digits and underscores");
    return { event_id: req(r, "event_id"), user_id: str(r, "user_id", true), anonymous_id: str(r, "anonymous_id", true), event_name: name, event_at: ts(r, "event_at"), received_at: ts(r, "received_at") };
  },
  event_properties: (r) => {
    const vt = req(r, "value_type");
    if (vt !== "string") throw malformed("value_type", "must be string");
    return { property_id: req(r, "property_id"), event_id: req(r, "event_id"), property_key: req(r, "property_key"), property_value: req(r, "property_value", 1024), value_type: vt };
  },
  subscriptions: (r) => ({ subscription_id: req(r, "subscription_id"), account_id: req(r, "account_id"), starts_at: ts(r, "starts_at"), ends_at: tsOpt(r, "ends_at"), status: req(r, "status"), amount_cents: moneyCents(r["amount_usd"], "amount_usd") }),
  experiment_versions: (r) => ({ experiment_version_id: req(r, "experiment_version_id"), name: req(r, "name"), unit_type: req(r, "unit_type"), primary_metric: req(r, "primary_metric"), planned_end: ts(r, "planned_end") }),
  assignments: (r) => ({ assignment_id: req(r, "assignment_id"), experiment_version_id: req(r, "experiment_version_id"), unit_id: req(r, "unit_id"), variant: req(r, "variant"), assigned_at: ts(r, "assigned_at") }),
  exposures: (r) => ({ exposure_id: req(r, "exposure_id"), assignment_id: req(r, "assignment_id"), exposed_at: ts(r, "exposed_at"), surface: req(r, "surface"), event_id: str(r, "event_id", true) }),
  metric_observations: (r) => {
    const v = req(r, "value");
    if (v !== "0" && v !== "1") throw malformed("value", "must be '0' or '1'");
    return { observation_id: req(r, "observation_id"), assignment_id: req(r, "assignment_id"), metric_name: req(r, "metric_name"), value: v, window_end: ts(r, "window_end") };
  },
  analysis_runs: (r) => {
    const h = req(r, "config_hash");
    if (!SHA.test(h)) throw malformed("config_hash", "must be 64 lower-case hex digits");
    return { analysis_id: req(r, "analysis_id"), experiment_version_id: req(r, "experiment_version_id"), cutoff_at: ts(r, "cutoff_at"), config_hash: h, created_at: ts(r, "created_at") };
  },
};
export const idOf = (ent: Entity, row: Row): string => String(row[ID_KEYS[ent]]);

// ------------------------------------------------------------------------------------------------ the frozen plan
/** Compact, key-sorted JSON: the form the plan hash is taken over (D-P6-22). */
export function canonicalJson(v: unknown): string {
  const sorted = (x: unknown): unknown => Array.isArray(x) ? x.map(sorted)
    : x && typeof x === "object" ? Object.fromEntries(Object.entries(x as Row).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([k, y]) => [k, sorted(y)])) : x;
  return JSON.stringify(sorted(v));
}
export const planHash = (body: Row): string => sha256(canonicalJson(Object.fromEntries(Object.entries(body).filter(([k]) => k !== "config_hash"))));

export interface Plan {
  experiment_version_id: string; primary_metric: string; unit_type: string; allocation: Record<string, string>; planned_end: number;
  activation_window_days: number; guardrail_metric: string; guardrail_window_days: number; revenue_from: number; revenue_to: number;
  confidence: string; z: string; srm_p_threshold: string; srm_min_expected_cell: number; frozen_at: number; config_hash: string;
  body: Row; hash_valid: boolean; variants: string[];
}
const posInt = (v: unknown, name: string): number => {
  if (typeof v !== "number" || !Number.isInteger(v) || v < 1 || v > 3650) throw malformed(name, "must be a positive integer");
  return v;
};
const isObj = (v: unknown): v is Row => !!v && typeof v === "object" && !Array.isArray(v);

export function parsePlan(raw: unknown): Plan {
  if (!isObj(raw)) throw malformed("analysis_plan", "must be an object");
  const body = Object.fromEntries(Object.entries(raw).filter(([k]) => k !== "config_hash"));
  const h = raw["config_hash"];
  if (typeof h !== "string" || !SHA.test(h)) throw malformed("config_hash", "must be 64 lower-case hex digits");
  const alloc = raw["allocation"];
  if (!isObj(alloc) || Object.keys(alloc).length < 2) throw malformed("allocation", "must name at least two variants");
  if (!("control" in alloc) || !("treatment" in alloc)) throw malformed("allocation", "must name control and treatment (lift is treatment minus control)");
  let total = ZERO;
  for (const [k, v] of Object.entries(alloc)) {
    if (typeof v !== "string" || !PROPORTION.test(v)) throw malformed(`allocation.${k}`, "must be a decimal string with at most 6 places in [0, 1]");
    const f = fracOf(v);
    if (f.n === 0n) throw malformed("allocation", "shares must be positive and sum to 1");
    total = add(total, f);
  }
  if (cmp(total, ONE) !== 0) throw malformed("allocation", "shares must be positive and sum to 1");
  const guard = raw["guardrail"], rw = raw["revenue_window"], srm = raw["srm"];
  if (!isObj(guard) || !isObj(rw) || !isObj(srm)) throw malformed("analysis_plan", "needs guardrail, revenue_window and srm objects");
  const conf = req(raw, "confidence"), z = req(raw, "z");
  for (const [name, v] of [["confidence", conf], ["z", z], ["srm.p_threshold", srm["p_threshold"]]] as const) {
    if (typeof v !== "string" || !/^\d+(\.\d+)?$/.test(v)) throw malformed(name, "must be a decimal string");
  }
  const cf = fracOf(conf);
  if (!(cf.n > 0n && cmp(cf, ONE) < 0) || fracOf(z).n <= 0n) throw malformed("confidence", "must be in (0, 1) with a positive z");
  const cell = srm["min_expected_cell"];
  if (typeof cell !== "number" || !Number.isInteger(cell) || cell < 0) throw malformed("srm.min_expected_cell", "must be a nonnegative integer");
  const rf = ts(rw, "from"), rt = ts(rw, "to");
  if (rf >= rt) throw malformed("revenue_window", "from must be before to");
  const unit = req(raw, "unit_type");
  if (unit !== "account") throw malformed("unit_type", "must be account (the unit of randomisation and analysis)");
  const allocation = alloc as Record<string, string>;
  return {
    experiment_version_id: req(raw, "experiment_version_id"), primary_metric: req(raw, "primary_metric"), unit_type: unit, allocation,
    planned_end: ts(raw, "planned_end"), activation_window_days: posInt(raw["activation_window_days"], "activation_window_days"),
    guardrail_metric: req(guard, "metric"), guardrail_window_days: posInt(guard["window_days"], "guardrail.window_days"), revenue_from: rf, revenue_to: rt,
    confidence: conf, z, srm_p_threshold: srm["p_threshold"] as string, srm_min_expected_cell: cell, frozen_at: ts(raw, "frozen_at"), config_hash: h,
    body, hash_valid: planHash(body) === h, variants: Object.keys(allocation),
  };
}

// ------------------------------------------------------------------------------------------------ windows and funnel
export interface FunnelDef { definition_id: string; version: number; steps: string[]; max_gap_hours: number; window_from: number; window_to: number }
export function parseFunnel(r: Row): FunnelDef {
  const steps = r["steps"];
  if (!Array.isArray(steps) || steps.length < 2 || steps.length > 20 || !steps.every((s) => typeof s === "string" && NAME.test(s))) throw malformed("steps", "must be 2 to 20 event names");
  if (new Set(steps).size !== steps.length) throw malformed("steps", "must be distinct");
  const gap = r["max_gap_hours"];
  if (typeof gap !== "number" || !Number.isInteger(gap) || gap < 1 || gap > 24 * 365) throw malformed("max_gap_hours", "must be a positive integer number of hours");
  const ver = r["version"] ?? 1;
  if (typeof ver !== "number" || !Number.isInteger(ver) || ver < 1) throw malformed("version", "must be a positive integer");
  const f = ts(r, "from" in r ? "from" : "window_from"), t = ts(r, "to" in r ? "to" : "window_to");
  if (f >= t) throw malformed("window", "from must be before to");
  return { definition_id: req(r, "definition_id"), version: ver, steps: steps as string[], max_gap_hours: gap, window_from: f, window_to: t };
}

export interface Windows {
  signup_from: number; signup_to: number; activation_from: number; activation_to: number; activation_days: number;
  retention_from: number; retention_to: number;
  adoption_from: number; adoption_to: number; feature: string; eligible_plans: string[];
}
export function parseWindows(mw: unknown): Windows {
  if (!isObj(mw) || !isObj(mw["signup_conversion"]) || !isObj(mw["activation"]) || !isObj(mw["retention"]) || !isObj(mw["feature_adoption"])) {
    throw malformed("metric_windows", "needs signup_conversion, activation, retention and feature_adoption");
  }
  const sc = mw["signup_conversion"], ac = mw["activation"], rt = mw["retention"], fa = mw["feature_adoption"];
  const plans = fa["eligible_plans"];
  if (!Array.isArray(plans) || !plans.every((p) => typeof p === "string")) throw malformed("eligible_plans", "must be a list of plan names");
  const w: Windows = {
    signup_from: ts(sc, "from"), signup_to: ts(sc, "to"), activation_from: ts(ac, "from"), activation_to: ts(ac, "to"), activation_days: posInt(ac["window_days"], "window_days"),
    retention_from: parseDay(rt["signup_from"], "retention.signup_from"),
    retention_to: parseDay(rt["signup_to"], "retention.signup_to"), adoption_from: ts(fa, "from"), adoption_to: ts(fa, "to"), feature: req(fa, "feature"), eligible_plans: plans as string[],
  };
  if (w.signup_from >= w.signup_to || w.activation_from >= w.activation_to || w.adoption_from >= w.adoption_to || w.retention_from >= w.retention_to) {
    throw new DomainError("INVALID_WINDOW", "every window must have from before to", "metric_windows");
  }
  return w;
}
/** Windows for a cutoff with none stored (README assumption 3): 7 days before for signup conversion, funnel and feature adoption,
 *  28 days for activation, the retention cohort the seven local dates ending 35 days before the cutoff's UTC date. */
export function defaultWindows(cutoff: number): Windows {
  const day = utcDay(cutoff);
  return {
    signup_from: cutoff - 7 * DAY, signup_to: cutoff, activation_from: cutoff - 28 * DAY, activation_to: cutoff, activation_days: 7,
    retention_from: day - 42, retention_to: day - 35,
    adoption_from: cutoff - 7 * DAY, adoption_to: cutoff, feature: DEFAULT_FEATURE.feature, eligible_plans: [...DEFAULT_FEATURE.eligible_plans],
  };
}

// ------------------------------------------------------------------------------------------------ population
export type Typed = { [E in Entity]: Records[E][] };
export interface Population extends Typed {
  plans: Map<string, Plan>;
  funnels: FunnelDef[];
}
