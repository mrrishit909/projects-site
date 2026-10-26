import { ViewHead } from "../components/layout";
import { Link } from "../components/link";
import type { RouteDef } from "../routes";

const NOTES: Record<string, { says: string; instead: [string, string][] }> = {
  queues: {
    says: "A per-queue view of the discipline in force (FIFO within priority in Billing and Technical, plain FIFO in Onboarding) with arrivals, waits and backlog for each queue over time.",
    instead: [["overview?group=queue", "Overview grouped by queue"], ["tickets", "The queue timeline, filtered to one queue"]],
  },
  compare: {
    says: "Two staffing or routing policies run on the same seeds and the same demand paths, with a paired difference, the replication count and a 95 % interval (D-04, backend command C09 compare-policies).",
    instead: [["simulation", "The simulation studio: seeded runs and replications of one policy"]],
  },
  surveys: {
    says: "Survey invitation and response rates, the CSAT among responders and the nonresponse skew (INJ-09), by queue and by outcome of the SLA.",
    instead: [["overview", "CSAT, invitation and response rates in the overview metric sheet"]],
  },
};

/** An honest placeholder: says what the route is for and that it is not built, and points at what exists. */
export function Stub({ route }: { route: RouteDef }) {
  const n = NOTES[route.path];
  return (
    <article data-testid="stub">
      <ViewHead eyebrow={`Route /${route.path}/`} title={route.title}>
        <p className="lede"><strong>Not built yet.</strong> This route is listed in the brief and is deliberately left as a stub: nothing on this page is computed, and no figure is shown.</p>
      </ViewHead>
      {n && (
        <>
          <p>What it is meant to show: {n.says}</p>
          <p>What exists today instead:</p>
          <ul>{n.instead.map(([to, label]) => <li key={to}><Link to={to}>{label}</Link></li>)}</ul>
        </>
      )}
    </article>
  );
}
