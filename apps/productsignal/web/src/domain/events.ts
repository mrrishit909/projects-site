// Canonical events (D-01, D-05): received by the cutoff, de-duplicated, identity resolved in time, exclusions counted. Mirror of
// domain/productsignal/events.py. Order (D-P6-6): (1) received_at <= cutoff, (2) de-duplicate, (3) unknown identity, (4) bots,
// (5) internal accounts. The log is never edited: a late event changes a later run, never a published one.
import type { Event, IdentityLink, Population } from "./models";
import { DAY } from "./time";

export interface AEvent { event: Event; user: string | null; account: string | null; visitor: string; name: string; at: number }
export interface TrackingQuality {
  rows_total: number; received_after_cutoff: number; duplicates_dropped: number; canonical: number; delayed_over_24h: number;
  unknown_identity: number; bot_events_excluded: number; internal_events_excluded: number; analysed: number;
}
export interface IdentityStats { anonymous_events: number; attributed_by_link: number; remain_anonymous: number }
export interface Canon {
  rowsTotal: number; receivedAfterCutoff: number; duplicates: number; canon: Event[]; delayed: number; unknown: number; bots: number; internals: number;
  analysed: AEvent[]; anonEvents: number; attributed: number; internalSignups: [string, number][]; props: Map<string, Map<string, string>>;
}
export const trackingQuality = (c: Canon): TrackingQuality => ({
  rows_total: c.rowsTotal, received_after_cutoff: c.receivedAfterCutoff, duplicates_dropped: c.duplicates, canonical: c.canon.length,
  delayed_over_24h: c.delayed, unknown_identity: c.unknown, bot_events_excluded: c.bots, internal_events_excluded: c.internals, analysed: c.analysed.length,
});
export const identityStats = (c: Canon): IdentityStats => ({ anonymous_events: c.anonEvents, attributed_by_link: c.attributed, remain_anonymous: c.anonEvents - c.attributed });

const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

export function propertiesByEvent(pop: Population): Map<string, Map<string, string>> {
  const out = new Map<string, Map<string, string>>();
  for (const p of pop.event_properties) {
    let m = out.get(p.event_id);
    if (!m) { m = new Map(); out.set(p.event_id, m); }
    m.set(p.property_key, p.property_value);
  }
  return out;
}

export function canonicalise(pop: Population, cutoff: number): Canon {
  const users = new Map(pop.users.map((u) => [u.user_id, u]));
  const accounts = new Map(pop.accounts.map((a) => [a.account_id, a]));
  const props = propertiesByEvent(pop);
  const linksByAnon = new Map<string, IdentityLink[]>();
  const anonOfUser = new Map<string, string>();
  for (const l of [...pop.identity_links].sort((a, b) => a.linked_at - b.linked_at || cmpStr(a.identity_link_id, b.identity_link_id))) {
    const arr = linksByAnon.get(l.anonymous_id) ?? [];
    arr.push(l);
    linksByAnon.set(l.anonymous_id, arr);
    if (!anonOfUser.has(l.user_id)) anonOfUser.set(l.user_id, l.anonymous_id);
  }
  // (1) received by the cutoff, (2) de-duplicated: the earliest (received_at, event_id) survives (D-P6-7)
  const recv = pop.events.filter((e) => e.received_at <= cutoff).sort((a, b) => a.received_at - b.received_at || cmpStr(a.event_id, b.event_id));
  const seenIds = new Set<string>();
  const seenKeys = new Set<string>();
  const canon: Event[] = [];
  let dups = 0;
  for (const e of recv) {
    const p = props.get(e.event_id);
    const sorted = p ? [...p.entries()].sort((a, b) => cmpStr(a[0], b[0]) || cmpStr(a[1], b[1])) : [];
    const key = JSON.stringify([e.user_id || e.anonymous_id, e.event_name, e.event_at, sorted]);
    if (seenIds.has(e.event_id) || seenKeys.has(key)) { dups++; continue; }
    seenIds.add(e.event_id);
    seenKeys.add(key);
    canon.push(e);
  }
  /** Time-aware identity (D-01): a link attributes only events at or after `linked_at`; never backwards. */
  const effectiveUser = (e: Event): string | null => {
    if (e.user_id) return e.user_id;
    for (const l of linksByAnon.get(e.anonymous_id ?? "") ?? []) if (l.linked_at <= e.event_at) return l.user_id;
    return null;
  };
  const analysed: AEvent[] = [];
  let unknown = 0, bots = 0, internals = 0;
  const internalSignups: [string, number][] = [];
  for (const e of canon) {
    const u = effectiveUser(e);
    if ((e.user_id === null && e.anonymous_id === null) || (u !== null && !users.has(u))) { unknown++; continue; }
    const usr = u !== null ? users.get(u)! : null;
    if (usr && usr.bot_flag) { bots++; continue; }
    if (usr && accounts.get(usr.account_id)!.internal) {
      internals++;
      if (e.event_name === "signup") internalSignups.push([usr.account_id, e.event_at]);
      continue;
    }
    const acct = usr ? usr.account_id : null;
    const vk = e.anonymous_id || (e.user_id ? anonOfUser.get(e.user_id) : undefined) || `user:${e.user_id}`;
    analysed.push({ event: e, user: u, account: acct, visitor: vk, name: e.event_name, at: e.event_at });
  }
  const delayed = canon.filter((e) => e.received_at - e.event_at > DAY).length;
  const anon = analysed.filter((a) => a.event.user_id === null);
  const attributed = anon.filter((a) => a.user !== null).length;
  return {
    rowsTotal: pop.events.length, receivedAfterCutoff: pop.events.length - recv.length, duplicates: dups, canon, delayed, unknown, bots, internals,
    analysed, anonEvents: anon.length, attributed, internalSignups, props,
  };
}
