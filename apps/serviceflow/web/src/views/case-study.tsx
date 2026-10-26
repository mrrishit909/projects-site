import { useMemo } from "react";
import { ViewHead } from "../components/layout";
import { Link } from "../components/link";
import { Gate } from "../components/status";
import { Panel, V } from "../components/ui";
import { tails } from "../domain/extras";
import { d4s } from "../domain/fixed";
import { groupValues, staffedSeconds } from "../domain/metrics";
import { useInjections } from "../lib/injections";
import type { Ready } from "../state/store";

const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/serviceflow";
const CI = "https://github.com/mrrishit909/projects-site/actions/workflows/serviceflow-ci.yml";

export function CaseStudy() {
  return (
    <article className="prose">
      <ViewHead eyebrow="Case study" title="ServiceFlow: which staffing or routing change meets support targets?">
        <p className="lede">An operations analyst plans next quarter's shifts and queue routing. This project replays the event log of a synthetic support desk, measures what happened exactly, shows who was on shift when, and estimates what a change might do with a seeded simulation, labelled as an estimate throughout.</p>
      </ViewHead>

      <section aria-labelledby="problem">
        <h2 id="problem">The decision, and what it is not</h2>
        <p>The decision (P04-GOAL-01) is which staffing or routing change meets support targets under uncertain workload. The non-goals are as binding: this is not a live ticketing system, it uses no real customer data, and it makes no claim of realised staffing benefits. Everything on this site is synthetic and computed in the browser from a published snapshot.</p>
      </section>

      <section aria-labelledby="built">
        <h2 id="built">What is built</h2>
        <ul data-testid="built-list">
          <li><Link to="overview">Overview</Link>: the 28 contract metrics over the full window or the training and holdout windows, grouped by queue, priority or agent, with every mean beside its P90 and backlog, open overdue and abandoned work kept apart.</li>
          <li><Link to="tickets">Queue timeline</Link>: one bar per ticket from arrival through waiting, service, pauses and resolution, by queue and priority, keyboard-navigable, with the same rows as a table.</li>
          <li><Link to="staffing">Shift grid</Link>: agents by hour of a chosen UTC day with recorded breaks and occupancy; the Santiago daylight-saving weekend (2026-09-05 and 06) is one click away.</li>
          <li><Link to="sla">SLA review</Link>: compliance by priority for first response and resolution with open overdue tickets counted separately.</li>
          <li><Link to="simulation">Simulation studio</Link>: the golden case reproduced to the digit, the three published runs re-simulated from their seed and compared with the Python simulator's events, and seeded replications with a 95 % interval.</li>
          <li><Link to="evidence">Evidence</Link>: the golden checks run live, and the list of what CI runs.</li>
        </ul>
      </section>

      <section aria-labelledby="not-built">
        <h2 id="not-built">What is not built</h2>
        <ul data-testid="not-built-list">
          <li><strong>Queues, Compare and Surveys</strong> are honest stubs: the routes exist, say what they are for and show no figure. Compare needs two policies on the same seeds (backend C09 compare-policies exists; the browser studio runs one policy at a time). CSAT, invitation and response rates are in the overview, but there is no survey view.</li>
          <li><strong>Backend commands C07 build-shift-scenario and C10 export-recommendation</strong> are not implemented: the API returns 501 NOT_IMPLEMENTED for both (D-06). Nothing on this static site calls an API; Mode B has no backend and persists nothing.</li>
          <li>No forecast of next quarter's demand is made, and no recommendation is exported. The simulation compares nothing against a real desk.</li>
          <li>A declared-interval rule for staffed time over <code>shift_breaks</code> is a later decision (see the limits below).</li>
        </ul>
      </section>

      <section aria-labelledby="choices">
        <h2 id="choices">Analytical choices, cited to the contract</h2>
        <ul>
          <li><strong>D-01, the log is the truth.</strong> History is an ordered, immutable event log; a late arrival keeps its occurred_at and sorts where it happened. Within a queue the discipline is first in first out within priority unless the queue says plain FIFO (Onboarding). A transfer keeps the original arrival but restarts the wait in the new queue. A reopen is a new cycle of the same ticket, one customer contact.</li>
          <li><strong>D-02, clocks.</strong> First response is the first human reply minus arrival; bot acknowledgements never count. Resolution is measured from the original arrival. Handling is the sum of active service intervals, excluding waiting for the customer. P90 is nearest rank, index ceil(0.9 n), shown beside every mean. SLA compliance is within policy over eligible, with open overdue counted separately.</li>
          <li><strong>D-03, capacity.</strong> Staffed time is shift length minus break; breaks are never capacity. Occupancy is handling over staffed time and is "no value" when staffed time is 0, never 0. CSAT is positive (4 or 5) over valid responses with invitation and response rates beside it.</li>
          <li><strong>D-04, simulation.</strong> The golden case must reproduce before random arrivals are used. Demand comes from seed-derived streams drawn before dispatching so policies share a demand path; warm-up observations are excluded; results carry the replication count and a 95 % interval; improvement is always an estimate.</li>
          <li><strong>D-05 and D-06, clarifications.</strong> Backlog counts arrived tickets not yet resolved, including those in service; the break is deducted only when the window covers the whole shift; a ticket rejected at ingest rejects its events and survey (TICKET_REJECTED); tickets still waiting at the horizon are censored.</li>
          <li><strong>D-07, the synthetic world.</strong> Zones Europe/Berlin and America/Santiago; the DST weekend is 2026-09-05/06 in Santiago, switch at 2026-09-06T04:00Z; SLA targets P1 15/240, P2 60/1440, P3 240/4320 minutes; holdout arrivals are Poisson times 1.2.</li>
        </ul>
        <p>Arithmetic: durations are integer seconds and every published figure is rounded half up from an exact integer quotient (BigInt), minutes at four decimals and ratios at six. No floating point reaches a figure.</p>
      </section>

      <Gate>{(s) => <Live s={s} />}</Gate>

      <section aria-labelledby="limits">
        <h2 id="limits">Limits and disclosures</h2>
        <ul>
          <li>The published snapshot holds fewer tickets than the specification's "about 6,000": with every event field present, 6,000 tickets would exceed the 5 MB cap the same specification sets, so the cap wins (D-07).</li>
          <li>Synthetic data cannot show that a staffing change helps a real desk; it shows that the rules and the simulation behave as stated.</li>
          <li>The Python and TypeScript domains were compared on the golden fixture, its variants and the published snapshot; the golden check fails on any difference.</li>
          <li>The simulation's replication interval takes its square root in exact integers, where Python uses a float; the published runs themselves are compared event for event.</li>
          <li>Source: <a href={SOURCE}>apps/serviceflow on GitHub</a>; evidence: <a href={CI}>the CI workflow</a>.</li>
        </ul>
      </section>
    </article>
  );
}

function Live({ s }: { s: Ready }) {
  const pop = s.result.population, hist = s.result.histories;
  const inj = useInjections();
  const tech = useMemo(() => {
    const ids = groupValues(pop, "queue", hist).get("q-002"), p1 = groupValues(pop, "priority", hist).get("P1");
    if (!ids || !p1) return null;
    return tails(pop.tickets, hist, s.windows.full, new Set([...ids].filter((x) => p1.has(x))));
  }, [pop, hist, s.windows]);
  const staffed = useMemo(() => {
    const { full, training, holdout } = s.windows;
    if (!training || !holdout) return null;
    const a = staffedSeconds(pop.shifts, full).avail, b = staffedSeconds(pop.shifts, training).avail, c = staffedSeconds(pop.shifts, holdout).avail;
    return { full: a, parts: b + c };
  }, [pop, s.windows]);
  const rej = s.result.ingest.rejected;
  const byReason = rej.reduce((m, r) => m.set(r.reason_code, (m.get(r.reason_code) ?? 0) + 1), new Map<string, number>());
  const m = s.snapshot.manifest;

  return (
    <>
      <section aria-labelledby="data">
        <h2 id="data">The data, as computed here</h2>
        <p data-testid="data-line">{m.dataset_version}: {s.result.ingest.counts.tickets.accepted + s.result.ingest.counts.tickets.rejected} tickets and {s.result.ingest.counts.ticket_events.accepted + s.result.ingest.counts.ticket_events.rejected} events in the files; {s.result.ingest.counts.tickets.accepted} tickets and {s.result.ingest.counts.ticket_events.accepted} events accepted at ingest, {rej.length} records rejected ({[...byReason].map(([c, n]) => `${c} ${n}`).join(", ") || "none"}).</p>
        {m.designed_relationships && m.designed_relationships.length > 0 && (
          <>
            <h3 className="h3">Relationships the generator was built to contain</h3>
            <p className="small">The generator's own statements, quoted; the figure below the list is recomputed here by the TypeScript domain from the accepted tickets, so small differences from the quoted numbers are the rejected tickets.</p>
            <ul data-testid="designed">{m.designed_relationships.map((r) => <li key={r}>{r}</li>)}</ul>
          </>
        )}
        {tech && (
          <p data-testid="tech-p1">Recomputed: technical queue, P1, full window: resolution of {tech.resolution.n} completed tickets has mean <V v={tech.resolution.mean} unit=" min" /> and P90 <V v={tech.resolution.p90} unit=" min" /> (P90 over mean <V v={tech.resolution.p90_over_mean} />). The mean alone would hide the tail.</p>
        )}
      </section>

      <Panel title="Injected defects and how each is met" id="injections">
        {inj.status === "loading" ? <p>Loading the injection manifest.</p> : inj.status === "error" ? <p className="notice notice--error">The injection manifest could not be read: {inj.error}</p> : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Injected defects, scrolls sideways on narrow screens">
            <table className="grid-table" data-testid="injection-table">
              <caption className="sr-only">Injected defects</caption>
              <thead><tr><th scope="col">Id</th><th scope="col">In</th><th scope="col">What was planted</th><th scope="col">Handling</th></tr></thead>
              <tbody>{inj.injections.map((i) => <tr key={i.id}><th scope="row">{i.id}</th><td>{i.entity}</td><td>{i.description}</td><td>{i.expected_handling ?? ""}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </Panel>

      {staffed && (
        <section aria-labelledby="known">
          <h2 id="known">A known behaviour, not fixed</h2>
          <p data-testid="known-staffed">Because D-05 deducts no break from a shift that a window cuts, the staffed minutes of two adjacent windows add up to more than those of the whole: here the training and holdout windows sum to {d4s(staffed.parts)} minutes against {d4s(staffed.full)} for the full window. A declared-interval rule over the recorded breaks is a later decision. One injected defect, INJ-02 (a reopen recorded as a new customer), is not detectable by the domain and stays an analyst check in the manifest.</p>
        </section>
      )}
    </>
  );
}
