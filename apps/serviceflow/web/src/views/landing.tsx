import { Link } from "../components/link";
import { Gate } from "../components/status";
import { Readout } from "../components/ui";
import { last } from "../lib/format";

const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/serviceflow";
const CI = "https://github.com/mrrishit909/projects-site/actions/workflows/serviceflow-ci.yml";

const JOURNEY: [string, string, string][] = [
  ["overview", "Overview", "the 28 contract metrics for the snapshot, with the P90 beside every mean"],
  ["tickets", "Queue timeline", "tickets as bars from arrival through waiting, service, pauses and resolution"],
  ["staffing", "Shift grid", "agents by hour with breaks and occupancy, including the Santiago daylight-saving weekend"],
  ["sla", "SLA review", "compliance by priority, with open overdue tickets counted separately"],
  ["simulation", "Simulation studio", "the golden case reproduced in the browser, then the seeded runs"],
  ["case-study", "Case study", "what is built, what is not, and why each rule is the way it is"],
];

export function Landing() {
  return (
    <article className="landing">
      <p className="eyebrow">Business Data Lab · Project 04</p>
      <h1 className="display">ServiceFlow</h1>
      <p className="lede" data-testid="decision">
        Which staffing or routing change meets support targets under uncertain workload? ServiceFlow replays the event log of
        a synthetic support desk, measures waits, first responses and SLA compliance exactly, shows who was on shift when,
        and runs a seeded queue simulation, so an operations analyst planning next quarter's shifts can see what the numbers
        rest on.
      </p>
      <p className="actions">
        <Link to="overview" className="btn btn--primary" data-testid="start">Start the entry journey</Link>
        <Link to="simulation" className="btn">Jump to the simulation</Link>
      </p>

      <Gate>{(s) => {
        const m = s.result.metrics;
        const open = last(Object.values(m.backlog)) ?? 0;
        return (
          <dl className="readouts" aria-label="Snapshot at a glance" data-testid="glance">
            <Readout id="arrivals" label="Arrivals in the window" value={m.arrival_count} note="tickets created, accepted at ingest" />
            <Readout id="completions" label="Completions" value={m.completion_count} note="final resolutions in the window" />
            <Readout id="backlog" label="Backlog at the window end" value={open} note="arrived, not resolved, not abandoned" />
            <Readout id="overdue" label="Open overdue, shown separately" value={m.open_overdue_at_cutoff} note="never folded into compliance" tone="alert" />
          </dl>
        );
      }}</Gate>

      <section aria-labelledby="journey-h">
        <h2 id="journey-h" className="section-title">The entry journey</h2>
        <ol className="journey" data-testid="journey">
          {JOURNEY.map(([to, label, text]) => <li key={to}><Link to={to}>{label}</Link><span>{text}</span></li>)}
        </ol>
      </section>

      <aside className="disclosure" aria-labelledby="mode-title">
        <h2 id="mode-title" className="disclosure__title">Mode disclosure</h2>
        <p>
          Static demo (Mode B): a TypeScript re-implementation of the domain rules over a published, synthetic snapshot. Every
          figure is computed in your browser from the event log with integer seconds and exact rounding. The simulation runs on
          a copy with the published seed, is an estimate from a seeded model, and nothing is persisted. The Python domain,
          PostgreSQL and FastAPI commands (Mode A) are verified separately on GitHub-hosted runners.
        </p>
      </aside>

      <section aria-labelledby="links-h">
        <h2 id="links-h" className="section-title">Links</h2>
        <ul className="link-list">
          <li><a href={PORTFOLIO} rel="noreferrer" data-testid="backlink">Back to Rishit Raj Mathur's projects (portfolio)</a></li>
          <li><a href={SOURCE} rel="noreferrer">Source on GitHub</a> <span className="muted">(branch business-data-lab)</span></li>
          <li><a href={CI} rel="noreferrer">Evidence: CI workflow</a></li>
        </ul>
      </section>
    </article>
  );
}
