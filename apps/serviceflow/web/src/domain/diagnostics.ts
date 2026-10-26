// Warnings the domain raises beside a result without changing it (D-09: R4-03, R4-18). Mirrors domain/serviceflow/diagnostics.py.
import { intervalsOf, type History } from "./events";
import { isoZ, parseTs } from "./time";
import type { Population, Window } from "./types";

export const CALENDAR_24X7 = "cal-001";
export interface DomainWarning { code: string; message: string; path: string | null }
export const warning = (code: string, message: string, path: string | null = null): DomainWarning => ({ code, message, path });

/** Calendars are ignored (D-07): the only calendar known is cal-001 (24x7); a policy that names another is computed as 24x7 and says so. */
export function calendarWarnings(pop: Population): DomainWarning[] {
  return [...pop.sla_policies].sort((a, b) => (a.sla_policy_id < b.sla_policy_id ? -1 : a.sla_policy_id > b.sla_policy_id ? 1 : 0))
    .filter((p) => p.calendar_id !== CALENDAR_24X7)
    .map((p) => warning("SLA_CALENDAR_IGNORED",
      `SLA policy ${p.sla_policy_id} names calendar '${p.calendar_id}'; calendars are ignored (D-07), targets are measured on the wall clock as if the calendar were ${CALENDAR_24X7} (24x7)`,
      `sla_policies[${p.sla_policy_id}].calendar_id`));
}

/** A cutoff not before the window end that really counts an arrival, resolution, reopen or abandonment at or after the end (inclusive) is flagged; a cutoff at the end with nothing there is silent. */
export function cutoffWarnings(pop: Population, w: Window, cutoffs: readonly number[]): DomainWarning[] {
  const out: DomainWarning[] = [];
  for (const c of cutoffs) {
    if (c < w[1]) continue;
    const beyond = pop.tickets.filter((t) => w[1] <= t.created_at && t.created_at <= c).length
      + pop.ticket_events.filter((e) => (e.event_type === "resolved" || e.event_type === "reopened" || e.event_type === "abandoned") && w[1] <= e.occurred_at && e.occurred_at <= c).length;
    if (beyond > 0) out.push(warning("CUTOFF_AT_OR_AFTER_WINDOW_END",
      `backlog cutoff ${isoZ(c)} is not before the window end ${isoZ(w[1])} and counts ${beyond} arrival or closing event(s) the half-open window excludes: a cutoff includes events at its own instant (D-09)`, "cutoff"));
  }
  return out;
}

export interface BreakFlag { ticket_id: string; agent_id: string | null; at: string; break_id: string }
/** Service intervals that open inside a recorded break. Breaks are not an ingest entity, so this is a flag, never a rejection. */
export function breakFlags(hist: ReadonlyMap<string, History>, breaks: readonly { break_id?: string; agent_id: string; starts_at: string; ends_at: string }[]): BreakFlag[] {
  const spans = new Map<string, [number, number, string][]>();
  for (const b of breaks) (spans.get(b.agent_id) ?? spans.set(b.agent_id, []).get(b.agent_id)!).push([parseTs(b.starts_at), parseTs(b.ends_at), b.break_id ?? ""]);
  const out: BreakFlag[] = [];
  for (const h of hist.values()) for (const iv of intervalsOf(h)) for (const [a, z, id] of spans.get(iv.agent_id ?? "") ?? []) {
    if (a <= iv.start && iv.start < z) out.push({ ticket_id: iv.ticket_id, agent_id: iv.agent_id, at: isoZ(iv.start), break_id: id });
  }
  return out.sort((x, y) => (x.at < y.at ? -1 : x.at > y.at ? 1 : x.ticket_id < y.ticket_id ? -1 : x.ticket_id > y.ticket_id ? 1 : 0));
}
