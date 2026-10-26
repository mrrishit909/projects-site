// Replay of one ticket's ordered event log into cycles (D-01, D-02). Mirrors domain/serviceflow/events.py.
import { BOT_PREFIX, CLOSERS, OPENERS } from "./contract";
import type { Ticket, TicketEvent } from "./types";

export const isBot = (actor: string | null): boolean => actor !== null && actor.startsWith(BOT_PREFIX);
export const isHumanReply = (e: TicketEvent): boolean => e.event_type === "replied_human" && !isBot(e.actor_id);
const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
/** Ordered by (occurred_at, event_id) so a late arrival lands where it happened. */
export const ordered = (events: Iterable<TicketEvent>): TicketEvent[] =>
  [...events].sort((a, b) => a.occurred_at - b.occurred_at || cmpStr(a.event_id, b.event_id));

export interface Interval { ticket_id: string; agent_id: string | null; start: number; end: number | null; cycle: number }
export interface Transfer { at: number; from_queue: string | null; to_queue: string | null }
export interface Cycle {
  index: number; started_at: number; prior: number | null; resolved_at: number | null; first_response_at: number | null;
  first_service_at: number | null; queue_id: string | null; intervals: Interval[]; pauses: [number, number | null][]; transfers: Transfer[];
}
export interface History {
  ticket_id: string; arrival: number; events: TicketEvent[]; cycles: Cycle[]; abandoned_at: number | null; queue_id: string | null;
}

export const intervalsOf = (h: History): Interval[] => h.cycles.flatMap((c) => c.intervals);
export const reopenCount = (h: History): number => h.cycles.length - 1;
export const transfersOf = (h: History): Transfer[] => h.cycles.flatMap((c) => c.transfers);
export const finalResolution = (h: History): number | null => h.cycles[h.cycles.length - 1]!.resolved_at;
const minOf = (xs: (number | null)[]): number | null => { const v = xs.filter((x): x is number => x !== null); return v.length ? Math.min(...v) : null; };
export const firstHumanReplyAt = (h: History): number | null => minOf(h.cycles.map((c) => c.first_response_at));
export const firstServiceAt = (h: History): number | null => minOf(h.cycles.map((c) => c.first_service_at));
/** The agent of the last service interval (the one who carried the ticket to its end). */
export function ownerAgent(h: History): string | null {
  const ivs = intervalsOf(h).filter((iv) => iv.agent_id !== null);
  return ivs.length ? ivs[ivs.length - 1]!.agent_id : null;
}
/** Seconds of an interval inside [lo, hi); an open interval runs to hi. */
export function secondsWithin(iv: Interval, lo: number, hi: number): number {
  const a = Math.max(iv.start, lo), b = Math.min(iv.end ?? hi, hi);
  return b > a ? b - a : 0;
}
/** Arrived, not resolved (a ticket in service is unresolved) and not abandoned at `instant` (D-05). */
export function openAt(h: History, instant: number): boolean {
  if (h.arrival > instant) return false;
  let gone = false;
  for (const e of h.events) {
    if (e.occurred_at > instant) break;
    if (e.event_type === "resolved" || e.event_type === "abandoned") gone = true;
    else if (e.event_type === "reopened") gone = false;
  }
  return !gone;
}

export function replay(ticket: Ticket, events: Iterable<TicketEvent>): History {
  const evs = ordered(events);
  const created = evs.find((e) => e.event_type === "created" && e.queue_id)?.queue_id ?? null;
  let queue: string | null = created || ticket.queue_id;
  const cycles: Cycle[] = [{ index: 0, started_at: ticket.created_at, prior: null, resolved_at: null, first_response_at: null, first_service_at: null, queue_id: queue, intervals: [], pauses: [], transfers: [] }];
  let openIv: [number, string | null] | null = null;
  let lastAgent: string | null = null;
  let abandonedAt: number | null = null;
  for (const e of evs) {
    const cyc = cycles[cycles.length - 1]!, t = e.event_type;
    if (t === "reopened") {
      cycles.push({ index: cycles.length, started_at: e.occurred_at, prior: cyc.index, resolved_at: null, first_response_at: null, first_service_at: null, queue_id: queue, intervals: [], pauses: [], transfers: [] });
      continue;
    }
    if (OPENERS.has(t) && openIv === null) {
      lastAgent = e.agent_id ?? lastAgent;
      openIv = [e.occurred_at, lastAgent];
      if (t === "service_started" && cyc.first_service_at === null) cyc.first_service_at = e.occurred_at;
    }
    if (t === "resumed" && cyc.pauses.length && cyc.pauses[cyc.pauses.length - 1]![1] === null) cyc.pauses[cyc.pauses.length - 1] = [cyc.pauses[cyc.pauses.length - 1]![0], e.occurred_at];
    if (CLOSERS.has(t)) {
      if (openIv !== null) { cyc.intervals.push({ ticket_id: ticket.ticket_id, agent_id: openIv[1], start: openIv[0], end: e.occurred_at, cycle: cyc.index }); openIv = null; }
      if (t === "resolved") cyc.resolved_at = e.occurred_at;
      else if (t === "paused") cyc.pauses.push([e.occurred_at, null]);
      else if (t === "transferred") cyc.transfers.push({ at: e.occurred_at, from_queue: queue, to_queue: e.queue_id });
      else if (t === "abandoned" && abandonedAt === null) abandonedAt = e.occurred_at;
    }
    if ((t === "queued" || t === "transferred") && e.queue_id !== null) queue = e.queue_id;
    if (isHumanReply(e) && (cyc.first_response_at === null || e.occurred_at < cyc.first_response_at)) cyc.first_response_at = e.occurred_at;
  }
  if (openIv !== null) { const c = cycles[cycles.length - 1]!; c.intervals.push({ ticket_id: ticket.ticket_id, agent_id: openIv[1], start: openIv[0], end: null, cycle: c.index }); }
  return { ticket_id: ticket.ticket_id, arrival: ticket.created_at, events: evs, cycles, abandoned_at: abandonedAt, queue_id: queue };
}

/** The queue a ticket is in at `instant`: where it was created, then the latest queued / transferred stamp. */
export function queueAt(ticket: Ticket, events: Iterable<TicketEvent>, instant: number): string | null {
  const evs = ordered(events);
  let queue: string | null = evs.find((e) => e.event_type === "created" && e.queue_id)?.queue_id || ticket.queue_id;
  for (const e of evs) {
    if (e.occurred_at > instant) break;
    if ((e.event_type === "queued" || e.event_type === "transferred") && e.queue_id !== null) queue = e.queue_id;
  }
  return queue;
}

/** True when adding `iv` to one agent's accepted intervals puts more than `cap` in service at once (P04-TEST-04). */
export function intervalConflict(existing: readonly Interval[], iv: Interval, cap: number): boolean {
  const newEnd = iv.end ?? Infinity;
  const points = [iv.start, ...existing.filter((a) => iv.start < a.start && a.start < newEnd).map((a) => a.start)];
  for (const p of points) {
    const n = 1 + existing.filter((a) => a.start <= p && p < (a.end ?? Infinity)).length;
    if (n > cap) return true;
  }
  return false;
}

/** One queue leg of a ticket's wait: the arrival never moves but the wait restarts in each queue (P04-TEST-08). */
export interface QueueLeg { queue_id: string | null; entered_at: number; wait_seconds: number | null }
export function queueLegs(h: History): QueueLeg[] {
  const out: QueueLeg[] = [];
  let start = h.arrival, queue = h.cycles[0]!.queue_id;
  const starts = intervalsOf(h).map((iv) => iv.start).sort((a, b) => a - b);
  const marks: [number | null, string | null][] = [...transfersOf(h).map((t): [number, string | null] => [t.at, t.to_queue]), [null, null]];
  for (const [at, to] of marks) {
    const s = start;
    const served = starts.find((x) => x >= s && (at === null || x < at));
    out.push({ queue_id: queue, entered_at: start, wait_seconds: served === undefined ? null : Math.max(0, served - start) });
    if (at !== null) { start = at; queue = to; }
  }
  return out;
}
