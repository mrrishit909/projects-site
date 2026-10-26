import { useMemo, useRef } from "react";
import { ViewHead } from "../components/layout";
import { Gate } from "../components/status";
import { Definition, Panel, RULES, V } from "../components/ui";
import { arrivalsByDay, timelineRow, type Seg, type TimelineRow } from "../domain/extras";
import { d4s } from "../domain/fixed";
import { dayOf, dayStart, hhmm, last, stamp } from "../lib/format";
import { useParam } from "../router";
import type { Ready } from "../state/store";

const VW = 1000, GUTTER = 118, RIGHT = 14, TOP = 40, PITCH = 18;
const SPANS = ["24", "48", "96"];
const mm = (sec: number | null): string | null => (sec === null ? null : d4s(sec));

export function Tickets() {
  return (
    <article>
      <ViewHead eyebrow="Entry route" title="Queue timeline">
        <p className="lede">Each ticket that arrived on the chosen day is a bar from its arrival: hatched while it waits for service, solid while an agent handles it, dashed while it is paused, closed by a diamond at resolution. The table underneath lists the same rows.</p>
      </ViewHead>
      <Gate>{(s) => <Body s={s} />}</Gate>
    </article>
  );
}

function Body({ s }: { s: Ready }) {
  const pop = s.result.population, hist = s.result.histories;
  const days = useMemo(() => arrivalsByDay(pop.tickets), [pop]);
  const sorted = useMemo(() => [...days.keys()].sort(), [days]);
  const busiest = useMemo(() => [...days.entries()].reduce((a, b) => (b[1] > a[1] || (b[1] === a[1] && b[0] < a[0]) ? b : a))[0], [days]);
  const [day, setDay] = useParam("day", busiest);
  const [queue, setQueue] = useParam("queue", "all");
  const [prio, setPrio] = useParam("priority", "all");
  const [span, setSpan] = useParam("span", "48");
  const [sel, setSel] = useParam("ticket", "");
  const dayKey = days.has(day) || /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : busiest;
  const t0 = dayStart(dayKey), hours = SPANS.includes(span) ? Number(span) : 48, t1 = t0 + hours * 3600;
  const policy = new Map(pop.sla_policies.map((p) => [p.priority, p.resolution_minutes] as const));
  const qname = new Map(pop.queues.map((q) => [q.queue_id, q.queue_name] as const));

  const rows = useMemo(() => pop.tickets
    .filter((t) => t.created_at >= t0 && t.created_at < t0 + 86400 && (queue === "all" || t.queue_id === queue) && (prio === "all" || t.priority === prio))
    .sort((a, b) => a.created_at - b.created_at || (a.ticket_id < b.ticket_id ? -1 : 1))
    .map((t) => timelineRow(t, hist.get(t.ticket_id)!)), [pop, hist, t0, queue, prio]);
  const selected = rows.find((r) => r.ticket_id === sel) ?? null;
  const step = (d: number): void => setDay(dayOf(t0 + d * 86400));
  const first = sorted[0]!, lastDay = last(sorted)!;

  return (
    <>
      <form className="toolbar" aria-label="Timeline settings" onSubmit={(e) => e.preventDefault()}>
        <div className="field field--day">
          <label htmlFor="day">Arrival day (UTC)</label>
          <div className="daybox">
            <button type="button" className="btn btn--small" onClick={() => step(-1)} disabled={dayKey <= first} aria-label="Previous day">‹</button>
            <input id="day" type="date" value={dayKey} min={first} max={lastDay} onChange={(e) => e.target.value && setDay(e.target.value)} />
            <button type="button" className="btn btn--small" onClick={() => step(1)} disabled={dayKey >= lastDay} aria-label="Next day">›</button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="queue">Queue</label>
          <select id="queue" value={queue} onChange={(e) => setQueue(e.target.value)}>
            <option value="all">All queues</option>
            {pop.queues.map((q) => <option key={q.queue_id} value={q.queue_id}>{q.queue_name} ({q.queue_id})</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="priority">Priority</label>
          <select id="priority" value={prio} onChange={(e) => setPrio(e.target.value)}>
            <option value="all">All priorities</option>
            {["P1", "P2", "P3"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="span">Axis span</label>
          <select id="span" value={String(hours)} onChange={(e) => setSpan(e.target.value)}>
            {SPANS.map((h) => <option key={h} value={h}>{h} hours from midnight</option>)}
          </select>
        </div>
      </form>
      <p className="summary" data-testid="timeline-summary">{rows.length} ticket{rows.length === 1 ? "" : "s"} arrived on {dayKey} (UTC){queue !== "all" ? `, queue ${qname.get(queue) ?? queue}` : ""}{prio !== "all" ? `, priority ${prio}` : ""}. Bars run to the axis end at most; a ▸ marks one that continues.</p>

      {rows.length === 0 ? (
        <div className="status" role="status"><p className="status__title">No ticket arrived on this day with these filters</p><p className="status__body">The snapshot covers {first} to {lastDay}.</p></div>
      ) : (
        <Timeline rows={rows} t0={t0} t1={t1} hours={hours} selected={sel} onSelect={setSel} policy={policy} qname={qname} />
      )}

      <ul className="legend" aria-label="Legend" data-testid="timeline-legend">
        <li><svg width="30" height="12" aria-hidden="true"><rect x="1" y="2" width="28" height="8" className="tl-wait" /></svg> waiting for service</li>
        <li><svg width="30" height="12" aria-hidden="true"><rect x="1" y="1" width="28" height="10" className="tl-service" /></svg> in service</li>
        <li><svg width="30" height="12" aria-hidden="true"><rect x="1" y="3" width="28" height="6" className="tl-pause" /></svg> paused (waiting for the customer)</li>
        <li><svg width="14" height="12" aria-hidden="true"><path d="M7 1 L12 6 L7 11 L2 6 Z" className="tl-done" /></svg> resolved</li>
        <li><svg width="14" height="12" aria-hidden="true"><circle cx="7" cy="6" r="3.5" className="tl-reopen" /></svg> reopened</li>
        <li><svg width="14" height="12" aria-hidden="true"><path d="M7 0 V12" className="tl-xfer" /></svg> transferred</li>
        <li><svg width="14" height="12" aria-hidden="true"><path d="M2 2 L12 10 M12 2 L2 10" className="tl-abandon" /></svg> abandoned</li>
        <li><svg width="14" height="12" aria-hidden="true"><path d="M3 1 V11 M3 6 H9" className="tl-sla" /></svg> resolution target</li>
      </ul>

      {selected && <Detail row={selected} s={s} onClose={() => setSel("")} />}

      <Panel title="The same rows as a table" id="timeline-table-panel">
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Ticket table, scrolls sideways on narrow screens">
          <table data-testid="timeline-table" className="grid-table">
            <caption className="sr-only">Tickets arrived on {dayKey}; durations in minutes</caption>
            <thead><tr>
              <th scope="col">Ticket</th><th scope="col">Queue</th><th scope="col">Priority</th><th scope="col">Channel</th><th scope="col">Arrived (UTC)</th>
              <th scope="col" className="num">Wait (min)</th><th scope="col" className="num">First response (min)</th><th scope="col" className="num">Handling (min)</th><th scope="col" className="num">Resolution (min)</th><th scope="col">Outcome</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ticket_id} aria-selected={sel === r.ticket_id} className={sel === r.ticket_id ? "is-sel" : ""}>
                  <th scope="row"><button type="button" className="linklike" onClick={() => setSel(r.ticket_id)}>{r.ticket_id}</button></th>
                  <td>{qname.get(r.queue_id) ?? r.queue_id}</td><td>{r.priority}</td><td>{r.channel}</td><td>{hhmm(r.arrival)}Z</td>
                  <td className="num"><V v={mm(r.first_service === null ? null : Math.max(0, r.first_service - r.arrival))} /></td>
                  <td className="num"><V v={mm(r.first_response === null ? null : Math.max(0, r.first_response - r.arrival))} /></td>
                  <td className="num">{d4s(r.handling_seconds)}</td>
                  <td className="num"><V v={mm(r.final_resolution === null ? null : Math.max(0, r.final_resolution - r.arrival))} /></td>
                  <td>{outcome(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Definition items={[RULES.firstResponse, RULES.resolution, { name: "Waiting legs", rule: "D-01", text: "A transfer keeps the original arrival, but the wait for service restarts in the new queue, so a transferred ticket shows a second hatched leg; a reopen starts a new cycle of the same ticket. Handling is the sum of active service intervals; time waiting for the customer is not handling." }]} />
    </>
  );
}

function outcome(r: TimelineRow): string {
  if (r.abandoned !== null) return "abandoned";
  if (r.final_resolution !== null) return r.reopened.length ? `resolved after ${r.reopened.length} reopen${r.reopened.length > 1 ? "s" : ""}` : "resolved";
  return "open at the end of the log";
}

function Timeline({ rows, t0, t1, hours, selected, onSelect, policy, qname }: {
  rows: TimelineRow[]; t0: number; t1: number; hours: number; selected: string; onSelect: (id: string) => void;
  policy: Map<string, number>; qname: Map<string, string>;
}) {
  const plotW = VW - GUTTER - RIGHT;
  const x = (sec: number): number => GUTTER + (Math.min(Math.max(sec, t0), t1) - t0) / (t1 - t0) * plotW;
  const height = TOP + rows.length * PITCH + 12;
  const refs = useRef<(SVGGElement | null)[]>([]);
  const focusRow = (i: number): void => refs.current[Math.max(0, Math.min(rows.length - 1, i))]?.focus();
  const ticks: number[] = [];
  for (let h = 0; h <= hours; h += hours > 48 ? 12 : 6) ticks.push(t0 + h * 3600);
  const cur = rows.findIndex((r) => r.ticket_id === selected);
  const rover = cur >= 0 ? cur : 0;

  return (
    <div className="chart" data-testid="timeline">
      <div className="chart__scroll" tabIndex={0} role="region" aria-label="Queue timeline chart, scrolls sideways on narrow screens; rows are reachable with the arrow keys">
        <svg className="chart__svg tl" viewBox={`0 0 ${VW} ${height}`} role="group" aria-label={`Timeline of ${rows.length} tickets`} style={{ minWidth: 760 }}>
          <defs>
            <pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="5" height="5" className="tl-hatch-bg" /><line x1="0" y1="0" x2="0" y2="5" className="tl-hatch-line" /></pattern>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={TOP - 8} y2={height - 6} className={`tl-grid${(t - t0) % 86400 === 0 ? " tl-grid--day" : ""}`} />
              <text x={x(t) + 3} y={TOP - 14} className="tl-tick">{(t - t0) % 86400 === 0 ? `${dayOf(t).slice(5)} 00:00` : `${hhmm(t)}`}</text>
            </g>
          ))}
          {rows.map((r, i) => {
            const y = TOP + i * PITCH;
            const sla = r.arrival + (policy.get(r.priority) ?? 0) * 60;
            const label = `${r.ticket_id} ${r.priority}`;
            const aria = `${r.ticket_id}, ${qname.get(r.queue_id) ?? r.queue_id}, ${r.priority}, arrived ${hhmm(r.arrival)} UTC, ${outcome(r)}`;
            return (
              <g key={r.ticket_id} ref={(el) => { refs.current[i] = el; }} className={`tl-row${selected === r.ticket_id ? " is-sel" : ""}`} tabIndex={i === rover ? 0 : -1} role="button" aria-pressed={selected === r.ticket_id} aria-label={aria}
                data-ticket={r.ticket_id}
                onClick={() => onSelect(r.ticket_id)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") { e.preventDefault(); focusRow(i + 1); }
                  else if (e.key === "ArrowUp") { e.preventDefault(); focusRow(i - 1); }
                  else if (e.key === "Home") { e.preventDefault(); focusRow(0); }
                  else if (e.key === "End") { e.preventDefault(); focusRow(rows.length - 1); }
                  else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(r.ticket_id); }
                }}>
                <rect x="0" y={y} width={VW} height={PITCH} className="tl-hit" />
                <text x="4" y={y + 12} className="tl-label">{label}</text>
                <text x={GUTTER - 6} y={y + 12} className="tl-label tl-label--q" textAnchor="end">{(qname.get(r.queue_id) ?? r.queue_id).slice(0, 4)}</text>
                {segRects(r.segs, "wait", x, y, t1)}
                {segRects(r.segs, "pause", x, y, t1)}
                {segRects(r.segs, "service", x, y, t1)}
                {sla > t0 && sla <= t1 && <path d={`M${x(sla)} ${y + 2} V${y + 16}`} className="tl-sla" />}
                {r.transfers.filter((m) => m.at >= t0 && m.at <= t1).map((m) => <path key={m.at} d={`M${x(m.at)} ${y + 1} V${y + 17}`} className="tl-xfer" />)}
                {r.reopened.filter((m) => m >= t0 && m <= t1).map((m) => <circle key={m} cx={x(m)} cy={y + 9} r="3.4" className="tl-reopen" />)}
                {r.resolved.filter((m) => m >= t0 && m <= t1).map((m) => <path key={m} d={`M${x(m)} ${y + 3} l5 6 l-5 6 l-5 -6 Z`} className="tl-done" />)}
                {r.abandoned !== null && r.abandoned >= t0 && r.abandoned <= t1 && <path d={`M${x(r.abandoned) - 4} ${y + 5} l8 8 M${x(r.abandoned) + 4} ${y + 5} l-8 8`} className="tl-abandon" />}
                {endsBeyond(r, t1) && <text x={VW - RIGHT - 2} y={y + 13} className="tl-more" textAnchor="end">▸</text>}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

const dayLabel = (sec: number): string => stamp(sec);
const endsBeyond = (r: TimelineRow, t1: number): boolean => r.segs.some((g) => g.to === null || g.to > t1) && (r.final_resolution === null || r.final_resolution > t1) && (r.abandoned === null || r.abandoned > t1);

function segRects(segs: Seg[], kind: Seg["kind"], x: (s: number) => number, y: number, t1: number) {
  return segs.filter((g) => g.kind === kind).map((g, i) => {
    const a = x(g.from), b = x(g.to ?? t1);
    const w = Math.max(b - a, 1.2);
    const [dy, h] = kind === "service" ? [3, 12] : kind === "wait" ? [5, 8] : [6, 6];
    return <rect key={`${kind}${i}`} x={a} y={y + dy} width={w} height={h} className={`tl-${kind}`} />;
  });
}

function Detail({ row, s, onClose }: { row: TimelineRow; s: Ready; onClose: () => void }) {
  const h = s.result.histories.get(row.ticket_id)!;
  return (
    <section className="panel" aria-labelledby="detail-h" data-testid="ticket-detail">
      <h2 id="detail-h" className="panel__title">{row.ticket_id}: event log</h2>
      <p className="panel__note">Ordered by (occurred_at, event_id), so a late-arriving record lands where it happened. Owner agent: {row.owner ?? "none (never served)"}. <button type="button" className="linklike" onClick={onClose}>Close</button></p>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Event log">
        <table className="grid-table">
          <caption className="sr-only">Events of {row.ticket_id}</caption>
          <thead><tr><th scope="col">When (UTC)</th><th scope="col">Event</th><th scope="col">Actor</th><th scope="col">Agent</th><th scope="col">Queue</th><th scope="col">Event id</th></tr></thead>
          <tbody>{h.events.map((e) => (
            <tr key={e.event_id}><td>{dayLabel(e.occurred_at)}</td><td>{e.event_type}</td><td>{e.actor_id ?? "–"}</td><td>{e.agent_id ?? "–"}</td><td>{e.queue_id ?? "–"}</td><td><code>{e.event_id}</code></td></tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}
