import { useMemo } from "react";
import { ViewHead } from "../components/layout";
import { Link } from "../components/link";
import { Gate } from "../components/status";
import { Definition, Panel, Readout, RealisationNote, RULES, V } from "../components/ui";
import { METRIC_KEYS, type GroupKey, type MetricKey } from "../domain/contract";
import { tails } from "../domain/extras";
import { disclosures, groupMetrics, computeMetrics } from "../domain/metrics";
import { isoZ } from "../domain/time";
import type { Metrics, Window } from "../domain/types";
import { last, ratioToPct } from "../lib/format";
import { useParam } from "../router";
import type { Ready } from "../state/store";

const WINDOW_LABEL: Record<string, string> = { full: "Full window", training: "Training, weeks 1-8", holdout: "Holdout, weeks 9-12" };
const GROUP_BY = ["none", "queue", "priority", "agent"] as const;
const MAPS = new Set<MetricKey>(["backlog", "first_response_minutes", "wait_minutes", "resolution_minutes"]);
const LABEL: Record<MetricKey, string> = {
  arrival_count: "Arrivals", completion_count: "Completions", arrival_rate_per_hour: "Arrival rate per hour", completion_rate_per_hour: "Completion rate per hour",
  backlog: "Backlog at the cutoff", first_response_minutes: "First response, per ticket (min)", mean_first_response_minutes: "Mean first response (min)",
  p90_first_response_minutes: "P90 first response (min)", wait_minutes: "Wait to first service, per ticket (min)", mean_wait_minutes: "Mean wait to first service (min)",
  resolution_minutes: "Resolution, per ticket (min)", mean_resolution_minutes: "Mean resolution (min)", handling_minutes_total: "Handling, total (min)",
  sla_first_response_compliance: "SLA first-response compliance", sla_first_response_within: "First response within target",
  sla_first_response_eligible: "First response eligible", sla_resolution_compliance: "SLA resolution compliance", sla_resolution_within: "Resolution within target",
  sla_resolution_eligible: "Resolution eligible", open_overdue_at_cutoff: "Open overdue at the cutoff", staffed_available_minutes: "Staffed available (min)",
  staffed_shift_minutes_whole: "Staffed, whole shifts (min)", agent_occupancy: "Agent occupancy", abandonment_rate: "Abandonment rate", csat: "CSAT (positive share)",
  survey_invitation_rate: "Survey invitation rate", survey_response_rate: "Survey response rate", empty_population: "Empty population",
};

function cell(m: Metrics, k: MetricKey): string | number | boolean | null {
  const v = m[k];
  if (k === "backlog") { const e = Object.values(m.backlog); return e.length ? String(e[e.length - 1]) : null; }
  if (MAPS.has(k)) return `${Object.keys(v as object).length} tickets`;
  return typeof v === "boolean" ? String(v) : (v as string | number | null);
}

export function Overview() {
  return (
    <article>
      <ViewHead eyebrow="Entry route" title="Service overview">
        <p className="lede">The 28 metrics of the contract for the snapshot, recomputed in your browser. A mean is never shown without its P90; backlog, open overdue and abandoned work are kept apart.</p>
      </ViewHead>
      <Gate>{(s) => <Body s={s} />}</Gate>
    </article>
  );
}

function Body({ s }: { s: Ready }) {
  const [win, setWin] = useParam("window", "full");
  const [group, setGroup] = useParam("group", "none");
  const avail = (["full", "training", "holdout"] as const).filter((k) => s.windows[k] !== null);
  const wkey = avail.includes(win as never) ? (win as "full" | "training" | "holdout") : "full";
  const w = s.windows[wkey] as Window;
  const gkey = (GROUP_BY as readonly string[]).includes(group) ? (group as (typeof GROUP_BY)[number]) : "none";
  const { pop, hist } = { pop: s.result.population, hist: s.result.histories };
  const cut = useMemo(() => [w[1]], [w]);
  const overall = useMemo(() => computeMetrics(pop, w, cut, s.result.abandonable, hist), [pop, w, cut, s.result.abandonable, hist]);
  const grouped = useMemo(() => (gkey === "none" ? null : groupMetrics(pop, gkey as GroupKey, w, cut, s.result.abandonable, hist)), [gkey, pop, w, cut, s.result.abandonable, hist]);
  const disc = useMemo(() => disclosures(pop, w, hist), [pop, w, hist]);
  const tl = useMemo(() => tails(pop.tickets, hist, w), [pop, hist, w]);
  const columns: [string, Metrics][] = grouped ? Object.entries(grouped) : [["all tickets", overall]];
  const backlog = last(Object.values(overall.backlog)) ?? 0;
  const abandonCount = tl.abandoned;
  const rej = s.result.ingest.rejected;
  const reasons = [...rej.reduce((m, r) => m.set(r.reason_code, (m.get(r.reason_code) ?? 0) + 1), new Map<string, number>())];

  return (
    <>
      <form className="toolbar" aria-label="Overview settings" onSubmit={(e) => e.preventDefault()}>
        <fieldset className="seg">
          <legend>Window</legend>
          {avail.map((k) => (
            <label key={k} className={wkey === k ? "is-on" : ""}><input type="radio" name="window" value={k} checked={wkey === k} onChange={() => setWin(k)} />{WINDOW_LABEL[k]}</label>
          ))}
        </fieldset>
        <div className="field">
          <label htmlFor="group-by">Group by</label>
          <select id="group-by" value={gkey} onChange={(e) => setGroup(e.target.value)}>
            {GROUP_BY.map((g) => <option key={g} value={g}>{g === "none" ? "No grouping" : g}</option>)}
          </select>
        </div>
      </form>
      <p className="summary" data-testid="window-line">
        Window [{isoZ(w[0])}, {isoZ(w[1])}) · {WINDOW_LABEL[wkey]}{avail.length === 1 ? " (the training and holdout windows are defined for the published snapshot only)" : ""}
      </p>

      <Panel title="Waiting and the tail" id="tails" tone="night">
        <p className="panel__note">Mean beside P90 (nearest rank, D-02) for the whole window. P90 of wait and resolution are additions to the 28 contract keys, from the same populations. Wait means wait to first service (first service_started minus the original arrival); tickets never served are outside it.</p>
        <dl className="readouts readouts--pairs">
          <Readout id="first_response_mean" label="First response, mean" value={overall.mean_first_response_minutes} unit=" min" note={`n ${tl.first_response.n}`} />
          <Readout id="first_response_p90" label="First response, P90" value={overall.p90_first_response_minutes} unit=" min" note={`P90 / mean ${tl.first_response.p90_over_mean ?? "no value"}`} />
          <Readout id="wait_mean" label="Wait to first service, mean" value={overall.mean_wait_minutes} unit=" min" note={`n ${tl.wait.n}`} />
          <Readout id="wait_p90" label="Wait to first service, P90" value={tl.wait.p90} unit=" min" note={`P90 / mean ${tl.wait.p90_over_mean ?? "no value"}`} />
          <Readout id="resolution_mean" label="Resolution, mean" value={overall.mean_resolution_minutes} unit=" min" note={`n ${tl.resolution.n}`} />
          <Readout id="resolution_p90" label="Resolution, P90" value={tl.resolution.p90} unit=" min" note={`P90 / mean ${tl.resolution.p90_over_mean ?? "no value"}`} />
        </dl>
      </Panel>

      <Panel title="Open work, kept apart" id="open-work">
        <dl className="readouts readouts--light">
          <Readout id="backlog_end" label="Backlog at the window end" value={backlog} note="arrived, not resolved, not abandoned" />
          <Readout id="overdue_end" label="Open overdue" value={overall.open_overdue_at_cutoff} note="open and older than the resolution target; not in the compliance ratio" tone="alert" />
          <Readout id="abandoned" label="Abandoned arrivals" value={abandonCount} note={<>abandonment rate <V v={overall.abandonment_rate} /> over chat and phone arrivals</>} />
        </dl>
      </Panel>

      <section aria-labelledby="sheet-h" className="panel" data-testid="metric-sheet">
        <h2 id="sheet-h" className="panel__title">The 28 metrics{grouped ? `, by ${gkey}` : ""}</h2>
        <p className="panel__note">Durations are minutes at 4 decimals and ratios 6 decimals, rounded half up from exact integers. Per-ticket maps are counted here; the tickets themselves are on the <Link to="tickets">queue timeline</Link>. Staffing figures exist only for the agent grouping (a queue or priority has no staffed time of its own).</p>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Metric sheet, scrolls sideways on narrow screens">
          <table className="sheet">
            <caption className="sr-only">Metrics in contract order</caption>
            <thead><tr><th scope="col">Metric key</th>{columns.map(([k]) => <th key={k} scope="col" className="num">{k}</th>)}</tr></thead>
            <tbody>
              {METRIC_KEYS.map((k) => (
                <tr key={k} data-metric={k}>
                  <th scope="row"><code>{k}</code><span className="sub">{LABEL[k]}</span></th>
                  {columns.map(([g, m]) => <td key={g} className="num"><V v={cell(m, k) as string | number | null} /></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">SLA first-response compliance {ratioToPct(overall.sla_first_response_compliance) ?? "no value"} and resolution compliance {ratioToPct(overall.sla_resolution_compliance) ?? "no value"} for all tickets; the SLA page breaks them down by priority. <span data-testid="resolution-basis">Resolution compliance is measured from the original arrival: a reopened ticket is charged its dormant gap, the time between its resolution and its reopen.</span>{gkey === "queue" ? <span data-testid="queue-basis"> Grouped by queue means the ticket's final queue: a transferred ticket counts only where it ended, with its whole wait from the original arrival.</span> : null}</p>
      </section>

      <Panel title="What a reader must see beside the numbers" id="disclosures">
        <dl className="facts">
          <div><dt>Reopened tickets (one customer contact each; arrivals and completions in the window)</dt><dd data-fact="reopened">{disc.reopened_tickets} tickets, {disc.reopen_events} reopens, {disc.reopened_among_completions} of them completed in the window</dd></div>
          <div><dt>Transferred tickets (arrival never moves)</dt><dd data-fact="transferred">{disc.transferred_tickets}</dd></div>
          <div><dt>Arrivals without a human reply (outside the first-response population)</dt><dd data-fact="no-reply">{disc.arrivals_without_human_reply}</dd></div>
          <div><dt>Bot events ignored for first response</dt><dd data-fact="bots">{disc.bot_events_ignored_for_first_response}</dd></div>
          <div><dt>CSAT base</dt><dd data-fact="csat">{disc.csat.valid_responses} valid responses of {disc.csat.invited} invited, {disc.csat.nonresponse} unanswered</dd></div>
        </dl>
        <p className="small">{disc.csat.note}.</p>
        <p className="small" data-testid="realisation-note"><RealisationNote r={s.snapshot.manifest.generator?.parameters?.arrival_realisation} /></p>
        <p className="small">{disc.p90_method}. {disc.staffed_break_rule}.</p>
        <h3 className="h3">Quarantined at ingest</h3>
        {rej.length === 0 ? <p>No record was rejected.</p> : (
          <p data-testid="rejected">{rej.length} records were rejected, not dropped silently: {reasons.map(([c, n]) => `${c} ${n}`).join(", ")}. They are kept with their raw rows by the domain; dependents of a rejected ticket carry TICKET_REJECTED (D-05).</p>
        )}
      </Panel>
      <Definition items={[RULES.window, RULES.p90, RULES.firstResponse, RULES.wait, RULES.resolution, RULES.backlog, RULES.occupancy, RULES.csat]} />
    </>
  );
}
