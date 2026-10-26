// Views' derived quantities. Everything is integer seconds and the same definitions as metrics.ts; none of these is one of
// the 28 contract metrics, and each says so where it is shown.
import { finalResolution, firstHumanReplyAt, firstServiceAt, intervalsOf, ownerAgent, secondsWithin, type History } from "./events";
import { fixed, d4s } from "./fixed";
import { p90Seconds } from "./metrics";
import { secondsBetween } from "./time";
import type { Population, Shift, Ticket, Window } from "./types";

const sum = (xs: readonly number[]): number => xs.reduce((a, b) => a + b, 0);
export interface Tail { n: number; mean: string | null; p90: string | null; p90_over_mean: string | null }
const tail = (xs: number[]): Tail => ({
  n: xs.length, mean: xs.length ? d4s(sum(xs), xs.length) : null,
  p90: xs.length ? d4s(p90Seconds(xs)!) : null,
  p90_over_mean: xs.length && sum(xs) > 0 ? fixed(BigInt(p90Seconds(xs)!) * BigInt(xs.length), sum(xs), 2) : null,
});
export interface Tails { arrivals: number; abandoned: number; first_response: Tail; wait: Tail; resolution: Tail }

/** Mean and P90 (nearest rank) of first response, wait and resolution for the tickets in `ids` over `w`, plus the abandoned
 * arrivals. Same populations as the metrics: arrivals inside the window for response and wait, completions for resolution. */
export function tails(tickets: readonly Ticket[], hist: Map<string, History>, w: Window, ids: ReadonlySet<string> | null = null): Tails {
  const inside = (x: number | null): boolean => x !== null && w[0] <= x && x < w[1];
  const fr: number[] = [], wt: number[] = [], rs: number[] = [];
  let arrivals = 0, abandoned = 0;
  for (const t of tickets) {
    if (ids && !ids.has(t.ticket_id)) continue;
    const h = hist.get(t.ticket_id)!;
    if (inside(t.created_at)) {
      arrivals++;
      if (h.abandoned_at !== null) abandoned++;
      const a = firstHumanReplyAt(h); if (a !== null) fr.push(secondsBetween(t.created_at, a));
      const b = firstServiceAt(h); if (b !== null) wt.push(secondsBetween(t.created_at, b));
    }
    const fin = finalResolution(h);
    if (inside(fin)) rs.push(secondsBetween(t.created_at, fin!));
  }
  return { arrivals, abandoned, first_response: tail(fr), wait: tail(wt), resolution: tail(rs) };
}

/** Tickets per UTC day (YYYY-MM-DD) by arrival. */
export function arrivalsByDay(tickets: readonly Ticket[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const t of tickets) { const d = new Date(t.created_at * 1000).toISOString().slice(0, 10); m.set(d, (m.get(d) ?? 0) + 1); }
  return m;
}

// ---- the queue timeline ---------------------------------------------------------------------------------------------
export type SegKind = "wait" | "service" | "pause";
export interface Seg { kind: SegKind; from: number; to: number | null; queue: string | null }
export interface TimelineRow {
  ticket_id: string; queue_id: string; priority: string; channel: string; arrival: number; segs: Seg[];
  resolved: number[]; reopened: number[]; transfers: { at: number; to: string | null }[]; abandoned: number | null;
  first_service: number | null; first_response: number | null; final_resolution: number | null; handling_seconds: number; owner: string | null;
}
/** A ticket's bar: waiting legs (from arrival, each transfer and each reopen to the next service start), service intervals and
 * pauses; resolutions, reopens, transfers and an abandonment as marks. A null end means still open at the end of the log. */
export function timelineRow(t: Ticket, h: History): TimelineRow {
  const ivs = intervalsOf(h);
  const starts = ivs.map((i) => i.start).sort((a, b) => a - b);
  const entries: { at: number; queue: string | null }[] = [{ at: h.arrival, queue: h.cycles[0]!.queue_id }];
  for (const c of h.cycles) {
    if (c.index > 0) entries.push({ at: c.started_at, queue: c.queue_id });
    for (const x of c.transfers) entries.push({ at: x.at, queue: x.to_queue });
  }
  entries.sort((a, b) => a.at - b.at);
  const segs: Seg[] = [];
  for (const e of entries) {
    const next = starts.find((s) => s >= e.at);
    const stop = next ?? h.abandoned_at ?? null;
    if (stop === null || stop > e.at) segs.push({ kind: "wait", from: e.at, to: stop, queue: e.queue });
  }
  for (const iv of ivs) segs.push({ kind: "service", from: iv.start, to: iv.end, queue: null });
  for (const c of h.cycles) for (const [a, b] of c.pauses) segs.push({ kind: "pause", from: a, to: b, queue: null });
  segs.sort((a, b) => a.from - b.from);
  return {
    ticket_id: t.ticket_id, queue_id: t.queue_id, priority: t.priority, channel: t.channel, arrival: h.arrival, segs,
    resolved: h.cycles.map((c) => c.resolved_at).filter((x): x is number => x !== null),
    reopened: h.cycles.filter((c) => c.index > 0).map((c) => c.started_at),
    transfers: h.cycles.flatMap((c) => c.transfers).map((x) => ({ at: x.at, to: x.to_queue })),
    abandoned: h.abandoned_at, first_service: firstServiceAt(h), first_response: firstHumanReplyAt(h), final_resolution: finalResolution(h),
    handling_seconds: sum(ivs.map((i) => (i.end ?? i.start) - i.start)), owner: ownerAgent(h),
  };
}

// ---- the shift grid -------------------------------------------------------------------------------------------------
export interface GridCell { onShiftSeconds: number; handlingSeconds: number; breakSeconds: number }
export interface GridRow { agent_id: string; shifts: Shift[]; cells: GridCell[]; breaks: [number, number][] }
/** Agents x 24 UTC hours of `dayStart` (epoch seconds of 00:00Z): seconds on shift (minus the recorded break), seconds in a
 * recorded break, and handling seconds. Occupancy of a cell = handling / on-shift (display only; D-05 defines the metric). */
export function shiftGrid(pop: Population, hist: Map<string, History>, breaks: readonly { agent_id: string; starts_at: number; ends_at: number }[], dayStart: number): GridRow[] {
  const day: Window = [dayStart, dayStart + 86400];
  const ivs = [...hist.values()].flatMap(intervalsOf);
  const rows: GridRow[] = [];
  for (const a of pop.agents) {
    const shifts = pop.shifts.filter((s) => s.agent_id === a.agent_id && s.ends_at > day[0] && s.starts_at < day[1]);
    const brs = breaks.filter((b) => b.agent_id === a.agent_id && b.ends_at > day[0] && b.starts_at < day[1]).map((b): [number, number] => [b.starts_at, b.ends_at]);
    const mine = ivs.filter((i) => i.agent_id === a.agent_id);
    const cells: GridCell[] = [];
    for (let h = 0; h < 24; h++) {
      const lo = dayStart + h * 3600, hi = lo + 3600;
      const shiftSec = sum(shifts.map((s) => Math.max(0, Math.min(s.ends_at, hi) - Math.max(s.starts_at, lo))));
      const brk = sum(brs.map(([x, y]) => Math.max(0, Math.min(y, hi) - Math.max(x, lo))));
      cells.push({ onShiftSeconds: Math.max(0, shiftSec - brk), breakSeconds: brk, handlingSeconds: sum(mine.map((i) => secondsWithin(i, lo, hi))) });
    }
    rows.push({ agent_id: a.agent_id, shifts, cells, breaks: brs });
  }
  return rows;
}

/** UTC offset in minutes of an IANA zone at an instant (display of the DST weekend; computed by the runtime's tz data). */
export function zoneOffsetMinutes(zone: string, sec: number): number {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" }).formatToParts(new Date(sec * 1000));
  const g = (t: string): number => parseInt(parts.find((p) => p.type === t)!.value, 10);
  return Math.round((Date.UTC(g("year"), g("month") - 1, g("day"), g("hour"), g("minute"), g("second")) / 1000 - sec) / 60);
}
export function localClock(zone: string, sec: number): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone: zone, hourCycle: "h23", weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(sec * 1000));
}
export const fmtOffset = (min: number): string => `UTC${min < 0 ? "-" : "+"}${String(Math.floor(Math.abs(min) / 60)).padStart(2, "0")}:${String(Math.abs(min) % 60).padStart(2, "0")}`;

/** Arrival intensity, tickets per hour at 4 decimals, and the change from the training to the holdout window as a ratio at
 * 6 decimals (D-04: the change is reported, never hidden). */
export function holdoutReport(trainCount: number, trainSeconds: number, holdCount: number, holdSeconds: number): { train_rate: string; holdout_rate: string; relative_change: string | null } {
  const tr = BigInt(trainCount) * 3600n * BigInt(holdSeconds), ho = BigInt(holdCount) * 3600n * BigInt(trainSeconds);
  return {
    train_rate: fixed(BigInt(trainCount) * 3600n, trainSeconds, 4), holdout_rate: fixed(BigInt(holdCount) * 3600n, holdSeconds, 4),
    relative_change: trainCount === 0 ? null : fixed(ho - tr, tr, 6),
  };
}
