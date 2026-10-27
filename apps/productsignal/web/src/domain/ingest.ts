// Ingest: validate a batch of raw rows (D-03/D-05 rejection codes, dependent rejection, merge of idempotent repeats). Mirror of
// domain/productsignal/ingest.py: every row is accepted, rejected (reason code, raw row kept) or, for an idempotent repeat, merged.
import {
  ASSIGNMENT_CONFLICT, DEPENDENT_REJECTED, DUPLICATE_ID, ENTITIES, EXPOSURE_BEFORE_ASSIGNMENT, IDENTITY_CONFLICT, ID_KEYS, INELIGIBLE_UNIT,
  INVALID_INTERVAL, UNKNOWN_ACCOUNT, UNKNOWN_ASSIGNMENT, UNKNOWN_EVENT, UNKNOWN_EXPERIMENT_VERSION, UNKNOWN_UNIT, UNKNOWN_USER,
  UNKNOWN_VARIANT, UNSUPPORTED_UNIT_TYPE, type Entity,
} from "./contract";
import { DomainError, MALFORMED_RECORD } from "./num";
import { PARSERS, canonicalJson, type Plan, type Records, type Row, type Typed } from "./models";

export interface Rejection { entity: Entity; id: string; reason_code: string; raw_row: Row; message: string }
export interface IngestResult {
  accepted: Typed;
  rejected: Rejection[];
  merged: Record<Entity, number>;
  counts: Record<Entity, { accepted: number; rejected: number; merged: number }>;
}
const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
const empty = <T,>(f: () => T): Record<Entity, T> => Object.fromEntries(ENTITIES.map((e) => [e, f()])) as Record<Entity, T>;

export function validateBatch(raw: Record<string, unknown>, plans: ReadonlyMap<string, Plan>): IngestResult {
  const rej: Rejection[] = [];
  const acc = empty<unknown[]>(() => []) as unknown as Typed;
  const ids = empty<Map<string, unknown>>(() => new Map());
  const rejectedIds = empty<Set<string>>(() => new Set());
  const merged = empty(() => 0);
  const seen = empty<Map<string, string>>(() => new Map());

  const rid = (row: unknown, key: string): string => {
    const v = row && typeof row === "object" ? (row as Row)[key] : undefined;
    return typeof v === "string" ? v : "";
  };
  const reject = (ent: Entity, row: unknown, code: string, message = ""): void => {
    const id = rid(row, ID_KEYS[ent]);
    if (id) rejectedIds[ent].add(id);
    rej.push({ entity: ent, id, reason_code: code, raw_row: row && typeof row === "object" && !Array.isArray(row) ? (row as Row) : { value: String(row) }, message });
  };
  const section = (ent: Entity): unknown[] => { const v = raw[ent]; return Array.isArray(v) ? v : []; };
  function parsed<E extends Entity>(ent: E, row: unknown): Records[E] | null {
    if (!row || typeof row !== "object" || Array.isArray(row)) { reject(ent, row, MALFORMED_RECORD, "row must be an object"); return null; }
    let obj: Records[E];
    try { obj = PARSERS[ent](row as Row); } catch (e) {
      if (e instanceof DomainError) { reject(ent, row, e.code, e.detail); return null; }
      throw e;
    }
    const id = (row as Row)[ID_KEYS[ent]] as string;
    const sig = canonicalJson(row);
    const prior = seen[ent].get(id);
    if (prior !== undefined) {
      if (prior === sig) merged[ent] += 1; else reject(ent, row, DUPLICATE_ID, `${ID_KEYS[ent]} already loaded with different content`);
      return null;
    }
    seen[ent].set(id, sig);
    return obj;
  }
  function take<E extends Entity>(ent: E, row: unknown, obj: Records[E]): void {
    ids[ent].set((row as Row)[ID_KEYS[ent]] as string, obj);
    (acc[ent] as Records[E][]).push(obj);
  }

  for (const r of section("accounts")) { const o = parsed("accounts", r); if (o) take("accounts", r, o); }
  for (const r of section("users")) {
    const o = parsed("users", r);
    if (!o) continue;
    if (!ids.accounts.has(o.account_id)) reject("users", r, UNKNOWN_ACCOUNT); else take("users", r, o);
  }
  const okLinks: [Records["identity_links"], unknown][] = [];
  for (const r of section("identity_links")) {
    const o = parsed("identity_links", r);
    if (!o) continue;
    if (!ids.users.has(o.user_id)) reject("identity_links", r, UNKNOWN_USER); else okLinks.push([o, r]);
  }
  const linked = new Set<string>();
  const firstUser = new Map<string, string>(); // the earliest link of an anonymous_id fixes its user (D-01)
  okLinks.sort((a, b) => a[0].linked_at - b[0].linked_at || cmpStr(a[0].identity_link_id, b[0].identity_link_id));
  for (const [o, r] of okLinks) {
    if (!firstUser.has(o.anonymous_id)) firstUser.set(o.anonymous_id, o.user_id);
    if (firstUser.get(o.anonymous_id) !== o.user_id) reject("identity_links", r, IDENTITY_CONFLICT, "this anonymous_id is already linked to another user");
    else if (linked.has(o.anonymous_id)) merged.identity_links += 1;
    else { linked.add(o.anonymous_id); take("identity_links", r, o); }
  }
  for (const r of section("sessions")) {
    const o = parsed("sessions", r);
    if (!o) continue;
    if (!ids.users.has(o.user_id)) reject("sessions", r, UNKNOWN_USER);
    else if (o.ended_at !== null && o.ended_at < o.started_at) reject("sessions", r, INVALID_INTERVAL, "ended_at is before started_at");
    else take("sessions", r, o);
  }
  for (const r of section("events")) { const o = parsed("events", r); if (o) take("events", r, o); }
  const seenProp = new Set<string>();
  for (const r of section("event_properties")) {
    const o = parsed("event_properties", r);
    if (!o) continue;
    const k = `${o.event_id}\u0000${o.property_key}`;
    if (rejectedIds.events.has(o.event_id) && !ids.events.has(o.event_id)) reject("event_properties", r, DEPENDENT_REJECTED);
    else if (!ids.events.has(o.event_id)) reject("event_properties", r, UNKNOWN_EVENT);
    else if (seenProp.has(k)) reject("event_properties", r, DUPLICATE_ID, "this event already carries the property");
    else { seenProp.add(k); take("event_properties", r, o); }
  }
  for (const r of section("subscriptions")) {
    const o = parsed("subscriptions", r);
    if (!o) continue;
    if (!ids.accounts.has(o.account_id)) reject("subscriptions", r, UNKNOWN_ACCOUNT);
    else if (o.ends_at !== null && o.ends_at < o.starts_at) reject("subscriptions", r, INVALID_INTERVAL, "ends_at is before starts_at");
    else take("subscriptions", r, o);
  }
  for (const r of section("experiment_versions")) {
    const o = parsed("experiment_versions", r);
    if (!o) continue;
    if (o.unit_type !== "account") reject("experiment_versions", r, UNSUPPORTED_UNIT_TYPE, "the unit of randomisation is the account");
    else take("experiment_versions", r, o);
  }

  // assignments: processed in (assigned_at, assignment_id) order; the first per (version, unit) wins (D-03)
  const cand: [Records["assignments"], unknown][] = [];
  for (const r of section("assignments")) {
    const o = parsed("assignments", r);
    if (!o) continue;
    const plan = plans.get(o.experiment_version_id);
    const unit = ids.accounts.get(o.unit_id) as Records["accounts"] | undefined;
    if (!ids.experiment_versions.has(o.experiment_version_id)) reject("assignments", r, UNKNOWN_EXPERIMENT_VERSION);
    else if (!unit) reject("assignments", r, UNKNOWN_UNIT, "the unit of randomisation is an account that exists");
    else if (unit.internal) reject("assignments", r, INELIGIBLE_UNIT, "internal accounts are not randomised (decided before assignment)");
    else if (plan && !(o.variant in plan.allocation)) reject("assignments", r, UNKNOWN_VARIANT, `the plan names ${plan.variants.join(", ")}`);
    else cand.push([o, r]);
  }
  const firstByUnit = new Map<string, Records["assignments"]>();
  const mergedInto = new Map<string, string>();
  cand.sort((a, b) => a[0].assigned_at - b[0].assigned_at || cmpStr(a[0].assignment_id, b[0].assignment_id));
  for (const [o, r] of cand) {
    const key = `${o.experiment_version_id}\u0000${o.unit_id}`;
    const first = firstByUnit.get(key);
    if (!first) { firstByUnit.set(key, o); take("assignments", r, o); }
    else if (first.variant === o.variant) { merged.assignments += 1; mergedInto.set(o.assignment_id, first.assignment_id); }
    else reject("assignments", r, ASSIGNMENT_CONFLICT, "the first assignment of a unit fixes its variant");
  }
  const acceptedAsg = ids.assignments as Map<string, Records["assignments"]>;
  const rejectedAsg = new Set([...rejectedIds.assignments].filter((i) => !acceptedAsg.has(i) && !mergedInto.has(i)));

  function resolve(ent: Entity, aidIn: string, r: unknown): Records["assignments"] | null {
    const aid = mergedInto.get(aidIn) ?? aidIn;
    const a = acceptedAsg.get(aid);
    if (a) return a;
    reject(ent, r, rejectedAsg.has(aid) ? DEPENDENT_REJECTED : UNKNOWN_ASSIGNMENT);
    return null;
  }

  const exposedSet = new Set<string>();
  const expo: [Records["exposures"], unknown][] = [];
  for (const r of section("exposures")) { const o = parsed("exposures", r); if (o) expo.push([o, r]); }
  expo.sort((a, b) => a[0].exposed_at - b[0].exposed_at || cmpStr(a[0].exposure_id, b[0].exposure_id));
  for (const [o0, r] of expo) {
    const a = resolve("exposures", o0.assignment_id, r);
    if (!a) continue;
    if (o0.exposed_at < a.assigned_at) reject("exposures", r, EXPOSURE_BEFORE_ASSIGNMENT, "an exposure cannot precede its assignment");
    else if (exposedSet.has(a.assignment_id)) merged.exposures += 1; // a unit is exposed once; later exposures add nothing
    else { exposedSet.add(a.assignment_id); take("exposures", r, { ...o0, assignment_id: a.assignment_id }); }
  }
  const observed = new Map<string, Records["metric_observations"]>();
  for (const r of section("metric_observations")) {
    const o0 = parsed("metric_observations", r);
    if (!o0) continue;
    const a = resolve("metric_observations", o0.assignment_id, r);
    if (!a) continue;
    const o = { ...o0, assignment_id: a.assignment_id };
    const key = `${o.assignment_id}\u0000${o.metric_name}`;
    const prior = observed.get(key);
    if (!prior) { observed.set(key, o); take("metric_observations", r, o); }
    else if (prior.value === o.value && prior.window_end === o.window_end) merged.metric_observations += 1;
    else reject("metric_observations", r, DUPLICATE_ID, "the unit already has a different observation of this metric");
  }
  for (const r of section("analysis_runs")) {
    const o = parsed("analysis_runs", r);
    if (!o) continue;
    if (!ids.experiment_versions.has(o.experiment_version_id)) reject("analysis_runs", r, UNKNOWN_EXPERIMENT_VERSION); else take("analysis_runs", r, o);
  }

  rej.sort((a, b) => cmpStr(a.entity, b.entity) || cmpStr(a.id, b.id));
  const counts = empty(() => ({ accepted: 0, rejected: 0, merged: 0 }));
  for (const e of ENTITIES) counts[e] = { accepted: (acc[e] as unknown[]).length, rejected: rej.filter((r) => r.entity === e).length, merged: merged[e] };
  return { accepted: acc, rejected: rej, merged, counts };
}
