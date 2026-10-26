// One business-hours axis for one case. Working intervals of the calendar are drawn at scale (shaded); every
// non-working gap is compressed to a fixed narrow column and marked, so the axis shows only the time that counts.
// Every drawn element also appears as a row of the table built from the same model (timelineRows).
import type { Interval } from "../domain/calendar";
import { isoZ } from "../domain/time";
import type { Assignment, Case, DocumentVersion, StepInstance, WaitingInterval } from "../domain/types";
import { clip, day, label, spanText, stamp } from "../lib/format";
import "../styles/screens.css";

export interface TimelineInput {
  caseRow: Case;
  working: readonly Interval[];
  assignments: readonly { a: Assignment; step: string; role: string }[];
  waits: readonly WaitingInterval[];
  /** Reasons that pause the SLA clock in the current view (configured policy or none). */
  policy: ReadonlySet<string>;
  docs: readonly DocumentVersion[];
  steps: readonly { si: StepInstance; name: string; sequence: number }[];
}

interface Seg { kind: "work" | "gap"; s: number; e: number; x0: number; x1: number }
export interface TimelineRow { key: string; element: string; subject: string; lane: string; starts: number; ends: number | null; detail: string }
export interface TimelineModel { input: TimelineInput; drawEnd: number; segs: Seg[]; rows: TimelineRow[]; gaps: number; open: boolean }

const LABEL = 150, PLOT = 980, PAD_R = 14, W = LABEL + PLOT + PAD_R, ROW = 28;

export function buildTimeline(input: TimelineInput): TimelineModel {
  const c = input.caseRow;
  const instants = [c.opened_at, c.completed_at ?? 0,
    ...input.assignments.flatMap((x) => [x.a.assigned_at, x.a.ended_at ?? 0]),
    ...input.waits.flatMap((w) => [w.starts_at, w.ends_at ?? 0]),
    ...input.docs.flatMap((d) => [d.submitted_at, d.reviewed_at ?? 0]),
    ...input.steps.flatMap((s) => [s.si.ready_at ?? 0, s.si.started_at ?? 0, s.si.approved_at ?? 0])];
  const open = c.completed_at === null;
  let drawEnd = Math.max(...instants);
  if (drawEnd <= c.opened_at) drawEnd = c.opened_at + 60_000;
  const start = c.opened_at;

  const raw: { kind: "work" | "gap"; s: number; e: number }[] = [];
  let cursor = start;
  for (const [ws, we] of input.working) {
    if (we <= start || ws >= drawEnd) continue;
    const s = Math.max(ws, start), e = Math.min(we, drawEnd);
    if (s > cursor) raw.push({ kind: "gap", s: cursor, e: s });
    raw.push({ kind: "work", s, e });
    cursor = e;
  }
  if (cursor < drawEnd) raw.push({ kind: "gap", s: cursor, e: drawEnd });
  const nGaps = raw.filter((r) => r.kind === "gap").length;
  const gapW = Math.min(24, Math.max(5, (PLOT * 0.3) / Math.max(1, nGaps)));
  const workMs = raw.filter((r) => r.kind === "work").reduce((n, r) => n + (r.e - r.s), 0);
  const scale = workMs > 0 ? (PLOT - nGaps * gapW) / workMs : 0;
  let x = LABEL;
  const segs: Seg[] = raw.map((r) => {
    const w = r.kind === "gap" ? gapW : Math.max(1, (r.e - r.s) * scale);
    const seg = { ...r, x0: x, x1: x + w };
    x += w;
    return seg;
  });

  const rows: TimelineRow[] = [];
  rows.push({ key: "span", element: "Case span", subject: c.case_id, lane: "Case span", starts: c.opened_at, ends: c.completed_at, detail: open ? "open: drawn to the last recorded instant" : `completed, status ${c.status}` });
  segs.forEach((g, i) => rows.push(g.kind === "work"
    ? { key: `w${i}`, element: "Working interval", subject: "calendar", lane: "Calendar", starts: g.s, ends: g.e, detail: `${spanText(g.e - g.s)} of working time, drawn to scale` }
    : { key: `g${i}`, element: "Non-working gap (compressed)", subject: "calendar", lane: "Calendar", starts: g.s, ends: g.e, detail: `${spanText(g.e - g.s)} not counted, drawn as a fixed narrow column` }));
  for (const { a, step, role } of input.assignments) {
    rows.push({ key: a.assignment_id, element: "Assignment", subject: a.assignee_id, lane: `Assignee ${a.assignee_id}`, starts: a.assigned_at, ends: a.ended_at, detail: `${label(step)} (role ${role})${a.ended_at === null ? ", still assigned" : ""}` });
  }
  for (const w of input.waits) {
    const eligible = input.policy.has(w.reason_code);
    rows.push({ key: w.waiting_interval_id, element: "Waiting interval", subject: label(w.reason_code), lane: "Waiting", starts: w.starts_at, ends: w.ends_at, detail: `${eligible ? "pause-eligible: deducted from active time" : "not pause-eligible: counted as active time"}${w.pause_requested ? "; pause requested" : ""}${w.ends_at === null ? "; still open" : ""}` });
  }
  for (const d of input.docs) {
    rows.push({ key: `${d.document_version_id}-s`, element: "Document version submitted", subject: `${label(d.document_type)} v${d.version_number}`, lane: "Documents", starts: d.submitted_at, ends: null, detail: `content ${clip(d.content_hash, 20)}` });
    if (d.reviewed_at !== null) rows.push({ key: `${d.document_version_id}-r`, element: "Document review", subject: `${label(d.document_type)} v${d.version_number}`, lane: "Documents", starts: d.reviewed_at, ends: null, detail: d.review_status });
  }
  for (const { si, name } of input.steps) {
    const who = `${label(name)}${si.version_number > 1 ? ` (version ${si.version_number})` : ""}`;
    if (si.ready_at !== null) rows.push({ key: `${si.step_instance_id}-r`, element: "Step state: ready", subject: who, lane: `Step ${label(name)}`, starts: si.ready_at, ends: null, detail: "all mandatory prerequisites approved" });
    if (si.started_at !== null) rows.push({ key: `${si.step_instance_id}-s`, element: "Step state: in progress", subject: who, lane: `Step ${label(name)}`, starts: si.started_at, ends: null, detail: "work started" });
    if (si.approved_at !== null) rows.push({ key: `${si.step_instance_id}-a`, element: "Step state: approved", subject: who, lane: `Step ${label(name)}`, starts: si.approved_at, ends: null, detail: `final state ${si.status}` });
    else rows.push({ key: `${si.step_instance_id}-x`, element: "Step state: not approved", subject: who, lane: `Step ${label(name)}`, starts: si.started_at ?? si.ready_at ?? c.opened_at, ends: null, detail: `current state ${si.status}` });
  }
  rows.sort((a, b) => a.starts - b.starts || a.key.localeCompare(b.key));
  return { input, drawEnd, segs, rows, gaps: nGaps, open };
}

const xOf = (m: TimelineModel, t: number): number => {
  const segs = m.segs;
  for (const g of segs) if (t >= g.s && t <= g.e) return g.e === g.s ? g.x0 : g.x0 + ((t - g.s) / (g.e - g.s)) * (g.x1 - g.x0);
  return t < (segs[0]?.s ?? 0) ? LABEL : LABEL + PLOT;
};

export function Timeline({ model }: { model: TimelineModel }) {
  const { input } = model;
  const c = input.caseRow;
  const X = (t: number): number => xOf(model, t);
  const assignees = [...new Set(input.assignments.map((x) => x.a.assignee_id))].sort();
  // waiting lanes: stack overlapping intervals
  const waitLaneEnds: number[] = [];
  const waitPlaced = [...input.waits].sort((a, b) => a.starts_at - b.starts_at).map((w) => {
    const x0 = X(w.starts_at), x1 = X(w.ends_at ?? model.drawEnd);
    let lane = waitLaneEnds.findIndex((e) => e <= x0);
    if (lane < 0) { lane = waitLaneEnds.length; waitLaneEnds.push(0); }
    waitLaneEnds[lane] = x1 + 2;
    return { w, x0, x1, lane };
  });
  const nWait = Math.max(1, waitLaneEnds.length);
  const steps = [...input.steps].sort((a, b) => a.sequence - b.sequence || a.si.version_number - b.si.version_number);
  const AX = 30; // axis header
  const yCalendar = AX, ySpan = yCalendar + ROW, yAssign = ySpan + ROW;
  const yWait = yAssign + Math.max(1, assignees.length) * ROW, yDoc = yWait + nWait * ROW, ySteps = yDoc + ROW * 1.6;
  const H = ySteps + Math.max(1, steps.length) * ROW + 6;
  const lanes: { y: number; h: number; text: string }[] = [
    { y: yCalendar, h: ROW, text: "Calendar" }, { y: ySpan, h: ROW, text: "Case span" },
    ...(assignees.length ? assignees.map((a, i) => ({ y: yAssign + i * ROW, h: ROW, text: a })) : [{ y: yAssign, h: ROW, text: "Assignments (none)" }]),
    ...waitPlaced.length ? [{ y: yWait, h: nWait * ROW, text: "Waiting" }] : [{ y: yWait, h: ROW, text: "Waiting (none)" }],
    { y: yDoc, h: ROW * 1.6, text: "Documents" },
    ...(steps.length ? steps.map((s, i) => ({ y: ySteps + i * ROW, h: ROW, text: label(s.name) })) : [{ y: ySteps, h: ROW, text: "Steps (none)" }]),
  ];
  let lastLabel = -100;
  const ticks = model.segs.filter((g) => g.kind === "work").flatMap((g) => {
    if (g.x0 - lastLabel < 46) return [];
    lastLabel = g.x0;
    return [{ x: g.x0, text: day(g.s) }];
  });
  const rightEnd = c.completed_at ?? model.drawEnd;
  return (
    <div className="tl" role="region" aria-label="Case timeline chart (scrollable)" tabIndex={0}>
      <svg className="tl__svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="tl-title tl-desc" width="100%" style={{ minWidth: 900 }}>
        <title id="tl-title">{`Timeline of ${c.case_id} on one business-hours axis`}</title>
        <desc id="tl-desc">{`Case ${c.case_id}, opened ${isoZ(c.opened_at)}, ${c.completed_at === null ? "still open" : `completed ${isoZ(c.completed_at)}`}. Shaded columns are working intervals drawn to scale; narrow hatched columns are compressed non-working gaps (${model.gaps}). Lanes show assignments, waiting intervals, document versions and step states. A table with every element follows the chart.`}</desc>
        <defs>
          <pattern id="tl-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" className="tl__hatch-line" /></pattern>
          <pattern id="tl-pause" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="5" height="5" className="tl__pause-bg" /><line x1="0" y1="0" x2="0" y2="5" className="tl__pause-line" /></pattern>
        </defs>
        {lanes.map((l, i) => (
          <g key={`${l.text}-${l.y}`}>
            {i % 2 === 0 && <rect className="tl__stripe" x={0} y={l.y} width={W} height={l.h} />}
            <text className="tl__lane" x={LABEL - 8} y={l.y + ROW / 2 + 4} textAnchor="end"><title>{l.text}</title>{clip(l.text, 20)}</text>
          </g>
        ))}
        {model.segs.map((g, i) => g.kind === "work"
          ? <rect key={i} className="tl__work" x={g.x0} y={AX} width={g.x1 - g.x0} height={H - AX} />
          : <g key={i}>
              <rect className="tl__gap" x={g.x0} y={AX} width={g.x1 - g.x0} height={H - AX} fill="url(#tl-hatch)"><title>{`Non-working gap, ${spanText(g.e - g.s)} not counted`}</title></rect>
              <text className="tl__gapmark" x={(g.x0 + g.x1) / 2} y={AX - 6} textAnchor="middle" aria-hidden="true">≈</text>
            </g>)}
        {ticks.map((t) => <text key={t.x} className="tl__tick" x={t.x + 2} y={AX - 8}>{t.text}</text>)}

        <rect className="tl__span" x={X(c.opened_at)} y={ySpan + 7} width={Math.max(3, X(rightEnd) - X(c.opened_at))} height={ROW - 14} rx={4}>
          <title>{`Case span ${stamp(c.opened_at)} to ${c.completed_at === null ? "open" : stamp(c.completed_at)}`}</title>
        </rect>
        {c.completed_at === null && <text className="tl__note" x={X(rightEnd) - 4} y={ySpan + ROW / 2 + 4} textAnchor="end">open</text>}

        {input.assignments.map(({ a, step }) => {
          const x0 = X(a.assigned_at), x1 = X(a.ended_at ?? model.drawEnd), y = yAssign + assignees.indexOf(a.assignee_id) * ROW + 6;
          const w = Math.max(3, x1 - x0);
          return (
            <g key={a.assignment_id}>
              <rect className="tl__assign" x={x0} y={y} width={w} height={ROW - 12} rx={3}><title>{`${a.assignee_id}: ${label(step)}, ${stamp(a.assigned_at)} to ${stamp(a.ended_at)}`}</title></rect>
              {w > label(step).length * 6.4 + 8 && <text className="tl__bartext" x={x0 + 5} y={y + 11}>{label(step)}</text>}
            </g>
          );
        })}

        {waitPlaced.map(({ w, x0, x1, lane }) => {
          const eligible = input.policy.has(w.reason_code);
          const bw = Math.max(3, x1 - x0), y = yWait + lane * ROW + 5;
          const text = `${label(w.reason_code)}${eligible ? " (pause)" : ""}`;
          return (
            <g key={w.waiting_interval_id}>
              <rect className={eligible ? "tl__wait tl__wait--pause" : "tl__wait"} x={x0} y={y} width={bw} height={ROW - 10} rx={3} fill={eligible ? "url(#tl-pause)" : undefined}>
                <title>{`Waiting: ${label(w.reason_code)}, ${stamp(w.starts_at)} to ${stamp(w.ends_at)}; ${eligible ? "pause-eligible" : "not pause-eligible"}`}</title>
              </rect>
              {bw > text.length * 6.4 + 10 && <text className="tl__waittext" x={x0 + 5} y={y + 12}>{text}</text>}
            </g>
          );
        })}

        {input.docs.map((d, i) => {
          const xs = X(d.submitted_at), y = yDoc + 10 + (i % 2) * 18;
          const xr = d.reviewed_at === null ? null : X(d.reviewed_at);
          return (
            <g key={d.document_version_id}>
              <path className="tl__doc" d={`M${xs} ${y - 6} l6 6 l-6 6 l-6 -6 z`}><title>{`${label(d.document_type)} v${d.version_number} submitted ${stamp(d.submitted_at)}`}</title></path>
              <text className="tl__doctext" x={xs + 9} y={y + 4}>{`${clip(label(d.document_type), 10)} v${d.version_number}`}</text>
              {xr !== null && <rect className={d.review_status === "accepted" ? "tl__review tl__review--ok" : "tl__review tl__review--no"} x={xr - 4} y={y - 4} width={8} height={8}><title>{`${label(d.document_type)} v${d.version_number} ${d.review_status} ${stamp(d.reviewed_at)}`}</title></rect>}
            </g>
          );
        })}

        {steps.map(({ si, name }, i) => {
          const y = ySteps + i * ROW + ROW / 2;
          const from = si.ready_at ?? si.started_at ?? c.opened_at;
          const to = si.approved_at ?? model.drawEnd;
          return (
            <g key={si.step_instance_id}>
              <line className={si.approved_at === null ? "tl__stepline tl__stepline--open" : "tl__stepline"} x1={X(from)} x2={X(to)} y1={y} y2={y} />
              {si.ready_at !== null && <circle className="tl__ready" cx={X(si.ready_at)} cy={y} r={5}><title>{`${label(name)} ready ${stamp(si.ready_at)}`}</title></circle>}
              {si.started_at !== null && <circle className="tl__started" cx={X(si.started_at)} cy={y} r={5}><title>{`${label(name)} started ${stamp(si.started_at)}`}</title></circle>}
              {si.approved_at !== null && <rect className="tl__approved" x={X(si.approved_at) - 5} y={y - 5} width={10} height={10}><title>{`${label(name)} approved ${stamp(si.approved_at)}`}</title></rect>}
            </g>
          );
        })}
      </svg>
      <ul className="tl__legend small" aria-label="Legend">
        <li><span className="key key--work" aria-hidden="true" /> Working interval (to scale)</li>
        <li><span className="key key--gap" aria-hidden="true" /> Non-working gap (compressed, ≈)</li>
        <li><span className="key key--assign" aria-hidden="true" /> Assignment</li>
        <li><span className="key key--pause" aria-hidden="true" /> Waiting, pause-eligible (hatched)</li>
        <li><span className="key key--wait" aria-hidden="true" /> Waiting, not pause-eligible</li>
        <li><span className="key key--doc" aria-hidden="true" /> Document submitted (diamond), review (square)</li>
        <li><span className="key key--step" aria-hidden="true" /> Step: ready (open circle), started (dot), approved (square)</li>
      </ul>
    </div>
  );
}
