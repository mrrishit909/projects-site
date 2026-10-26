// Metrics over an accepted population (D-02, D-03, D-05, D-06). Mirrors domain/serviceflow/metrics.py with integer
// seconds and BigInt rounding: minutes at 4 decimals, ratios at 6, every figure rounded half up from the exact quotient.
import { DEFAULT_ABANDONABLE, GROUP_KEYS, INVALID_WINDOW, METRIC_KEYS, type GroupKey } from "./contract";
import { DomainError } from "./errors";
import { finalResolution, firstHumanReplyAt, firstServiceAt, intervalsOf, isBot, openAt, ownerAgent, replay, reopenCount, secondsWithin, transfersOf, type History, type Interval } from "./events";
import { d4s, d6r } from "./fixed";
import { isoZ, overlapSeconds, secondsBetween } from "./time";
import type { Disclosures, GroupMetrics, Metrics, Population, Shift, Survey, Window } from "./types";

export function checkWindow(w: Window): void {
  if (w[0] >= w[1]) throw new DomainError(INVALID_WINDOW, "the window must start before it ends", "from");
}

export function histories(pop: Population): Map<string, History> {
  const by = new Map<string, typeof pop.ticket_events>();
  for (const e of pop.ticket_events) { const l = by.get(e.ticket_id); if (l) l.push(e); else by.set(e.ticket_id, [e]); }
  return new Map(pop.tickets.map((t) => [t.ticket_id, replay(t, by.get(t.ticket_id) ?? [])] as const));
}

/** (available seconds inside the window, whole-shift seconds). A break is deducted only for a shift the window covers whole. */
export function staffedSeconds(shifts: readonly Shift[], w: Window): { avail: number; whole: number } {
  let avail = 0, whole = 0;
  for (const s of shifts) {
    whole += s.ends_at - s.starts_at - s.break_minutes * 60;
    const ov = overlapSeconds(s.starts_at, s.ends_at, w[0], w[1]);
    if (ov > 0) avail += ov - (w[0] <= s.starts_at && s.ends_at <= w[1] ? s.break_minutes * 60 : 0);
  }
  return { avail, whole };
}

const sum = (xs: Iterable<number>): number => { let s = 0; for (const x of xs) s += x; return s; };
const byKey = <T,>(m: Map<string, T>): [string, T][] => [...m.entries()].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
const meanMin = (xs: number[]): string | null => (xs.length === 0 ? null : d4s(sum(xs), xs.length));
/** Nearest rank (D-02): sort ascending, take index ceil(0.9 n), 1-based. */
export const p90Seconds = (xs: number[]): number | null => {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.max(Math.floor((9 * s.length + 9) / 10), 1) - 1]!;
};

function compute(pop: Population, hist: Map<string, History>, ids: ReadonlySet<string>, intervals: readonly Interval[],
  shifts: readonly Shift[] | null, w: Window, cutoffs: readonly number[], abandonable: readonly string[]): Metrics {
  checkWindow(w);
  const [w0, w1] = w;
  const tickets = pop.tickets.filter((t) => ids.has(t.ticket_id));
  const policy = new Map(pop.sla_policies.map((p) => [p.priority, p] as const));
  const byId = new Map(tickets.map((t) => [t.ticket_id, t] as const));
  const inside = (x: number | null): boolean => x !== null && w0 <= x && x < w1;
  const H = (id: string): History => hist.get(id)!;

  const arrivals = tickets.filter((t) => inside(t.created_at)).sort((a, b) => (a.ticket_id < b.ticket_id ? -1 : 1));
  const completions = tickets.filter((t) => inside(finalResolution(H(t.ticket_id)))).sort((a, b) => (a.ticket_id < b.ticket_id ? -1 : 1));
  const firstResp = new Map<string, number>(), wait = new Map<string, number>(), resolution = new Map<string, number>();
  for (const t of arrivals) {
    const fr = firstHumanReplyAt(H(t.ticket_id)); if (fr !== null) firstResp.set(t.ticket_id, secondsBetween(t.created_at, fr));
    const fs = firstServiceAt(H(t.ticket_id)); if (fs !== null) wait.set(t.ticket_id, secondsBetween(t.created_at, fs));
  }
  for (const t of completions) resolution.set(t.ticket_id, secondsBetween(t.created_at, finalResolution(H(t.ticket_id))!));

  let frOk = 0, frElig = 0, rsOk = 0, rsElig = 0;
  for (const [id, s] of firstResp) { const p = policy.get(byId.get(id)!.priority); if (p) { frElig++; if (s <= p.first_response_minutes * 60) frOk++; } }
  for (const [id, s] of resolution) { const p = policy.get(byId.get(id)!.priority); if (p) { rsElig++; if (s <= p.resolution_minutes * 60) rsOk++; } }
  let overdue = 0;
  for (const t of tickets) {
    const p = policy.get(t.priority);
    if (t.created_at <= w1 && p && openAt(H(t.ticket_id), w1) && secondsBetween(t.created_at, w1) > p.resolution_minutes * 60) overdue++;
  }
  const handling = sum(intervals.map((iv) => secondsWithin(iv, w0, w1)));
  let staff: number | null = null, whole: number | null = null;
  if (shifts !== null) ({ avail: staff, whole } = staffedSeconds(shifts, w));

  const abSet = new Set(abandonable);
  const abArr = arrivals.filter((t) => abSet.has(t.channel));
  const abN = abArr.filter((t) => H(t.ticket_id).abandoned_at !== null).length;
  const done = new Set(completions.map((t) => t.ticket_id));
  const surveys: Survey[] = pop.surveys.filter((s) => done.has(s.ticket_id));
  const invited = surveys.filter((s) => s.invited_at !== null);
  const responded = invited.filter((s) => s.score !== null && s.response_at !== null);
  const positive = responded.filter((s) => s.score! >= 4).length;

  const mapMin = (m: Map<string, number>): Record<string, string> => Object.fromEntries(byKey(m).map(([k, v]) => [k, d4s(v)]));
  const out: Metrics = {
    arrival_count: arrivals.length, completion_count: completions.length,
    arrival_rate_per_hour: d6r(BigInt(arrivals.length) * 3600n, w1 - w0)!, completion_rate_per_hour: d6r(BigInt(completions.length) * 3600n, w1 - w0)!,
    backlog: Object.fromEntries(cutoffs.map((c) => [isoZ(c), tickets.filter((t) => openAt(H(t.ticket_id), c)).length])),
    first_response_minutes: mapMin(firstResp), mean_first_response_minutes: meanMin([...firstResp.values()]),
    p90_first_response_minutes: (() => { const p = p90Seconds([...firstResp.values()]); return p === null ? null : d4s(p); })(),
    wait_minutes: mapMin(wait), mean_wait_minutes: meanMin([...wait.values()]),
    resolution_minutes: mapMin(resolution), mean_resolution_minutes: meanMin([...resolution.values()]),
    handling_minutes_total: d4s(handling),
    sla_first_response_compliance: d6r(frOk, frElig), sla_first_response_within: frOk, sla_first_response_eligible: frElig,
    sla_resolution_compliance: d6r(rsOk, rsElig), sla_resolution_within: rsOk, sla_resolution_eligible: rsElig,
    open_overdue_at_cutoff: overdue,
    staffed_available_minutes: staff === null ? null : d4s(staff), staffed_shift_minutes_whole: whole === null ? null : d4s(whole),
    agent_occupancy: staff === null ? null : d6r(handling, staff),
    abandonment_rate: d6r(abN, abArr.length), csat: d6r(positive, responded.length),
    survey_invitation_rate: d6r(invited.length, completions.length), survey_response_rate: d6r(responded.length, invited.length),
    empty_population: tickets.length === 0,
  };
  if (Object.keys(out).join() !== METRIC_KEYS.join()) throw new Error("metric keys out of contract order");
  return out;
}

/** All metrics of `pop` for the half-open window; `cutoffs` are the backlog instants (default: the window end). */
export function computeMetrics(pop: Population, w: Window, cutoffs?: readonly number[], abandonable: readonly string[] = DEFAULT_ABANDONABLE, hist: Map<string, History> = histories(pop)): Metrics {
  const intervals = [...hist.values()].flatMap(intervalsOf);
  return compute(pop, hist, new Set(pop.tickets.map((t) => t.ticket_id)), intervals, pop.shifts, w, cutoffs ?? [w[1]], abandonable);
}

export function groupValues(pop: Population, groupBy: GroupKey, hist: Map<string, History>): Map<string, Set<string>> {
  if (!GROUP_KEYS.includes(groupBy)) throw new DomainError("INVALID_GROUP_BY", `group_by must be one of ${GROUP_KEYS.join(", ")}`, "group_by");
  const out = new Map<string, Set<string>>();
  for (const t of pop.tickets) {
    const k = groupBy === "queue" ? t.queue_id : groupBy === "priority" ? t.priority : groupBy === "channel" ? t.channel : ownerAgent(hist.get(t.ticket_id)!);
    if (k !== null) (out.get(k) ?? out.set(k, new Set()).get(k)!).add(t.ticket_id);
  }
  return out;
}

/** Metrics per queue, priority, agent or channel (keys sorted). Staffing figures exist only for `agent` (null otherwise). */
export function groupMetrics(pop: Population, groupBy: GroupKey, w: Window, cutoffs?: readonly number[], abandonable: readonly string[] = DEFAULT_ABANDONABLE, hist: Map<string, History> = histories(pop)): GroupMetrics {
  const cuts = cutoffs ?? [w[1]];
  const out: GroupMetrics = {};
  const allIv = groupBy === "agent" ? [...hist.values()].flatMap(intervalsOf) : [];
  for (const [key, ids] of byKey(groupValues(pop, groupBy, hist))) {
    if (groupBy === "agent") out[key] = compute(pop, hist, ids, allIv.filter((iv) => iv.agent_id === key), pop.shifts.filter((s) => s.agent_id === key), w, cuts, abandonable);
    else out[key] = compute(pop, hist, ids, [...ids].flatMap((id) => intervalsOf(hist.get(id)!)), null, w, cuts, abandonable);
  }
  return out;
}

/** What a reader must see beside the numbers (P04-TEST-02/06/10/11). */
export function disclosures(pop: Population, w: Window, hist: Map<string, History> = histories(pop)): Disclosures {
  const [w0, w1] = w;
  const inside = (x: number | null): boolean => x !== null && w0 <= x && x < w1;
  const arr = pop.tickets.filter((t) => inside(t.created_at));
  const done = new Set(pop.tickets.filter((t) => inside(finalResolution(hist.get(t.ticket_id)!))).map((t) => t.ticket_id));
  const surveys = pop.surveys.filter((s) => done.has(s.ticket_id));
  const invited = surveys.filter((s) => s.invited_at !== null);
  const responded = invited.filter((s) => s.score !== null && s.response_at !== null);
  const all = new Set(pop.tickets.map((t) => t.ticket_id));
  return {
    reopened_tickets: arr.filter((t) => reopenCount(hist.get(t.ticket_id)!) > 0).length,
    reopen_events: sum(arr.map((t) => reopenCount(hist.get(t.ticket_id)!))),
    transferred_tickets: arr.filter((t) => transfersOf(hist.get(t.ticket_id)!).length > 0).length,
    arrivals_without_human_reply: arr.filter((t) => firstHumanReplyAt(hist.get(t.ticket_id)!) === null).length,
    bot_events_ignored_for_first_response: pop.ticket_events.filter((e) => e.event_type === "acknowledged_bot" || (e.event_type === "replied_human" && isBot(e.actor_id))).length,
    open_overdue_at_window_end: compute(pop, hist, all, [], null, w, [], DEFAULT_ABANDONABLE).open_overdue_at_cutoff,
    p90_method: "nearest rank: sort ascending, take index ceil(0.9 n); n is the first-response population",
    csat: { completed_tickets: done.size, invited: invited.length, valid_responses: responded.length, nonresponse: invited.length - responded.length,
      note: "CSAT is over valid responses only; nonresponse is not random, read it beside the response rate" },
    staffed_break_rule: "a shift's break is deducted only when the window covers the whole shift (D-05)",
  };
}
