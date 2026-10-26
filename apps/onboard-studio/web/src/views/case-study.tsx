// Case study: the problem, what was built, the analytical choices (cited to the contract), the evidence and the limits.
import { useEffect, useState } from "react";
import { useStudio } from "../state/studio";
import { Link } from "../components/link";
import { ViewHead } from "../components/gate";

const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/onboard-studio";
const CI = "https://github.com/mrrishit909/projects-site/actions/workflows/onboard-studio-ci.yml";

interface Injection { id: string; description: string; test?: string }
type Designed = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; relationships: string[]; injections: Injection[] };

function useDesigned(): Designed {
  const [d, setD] = useState<Designed>({ status: "loading" });
  useEffect(() => {
    let live = true;
    fetch(`${import.meta.env.BASE_URL}data/injection-manifest.json`, { headers: { Accept: "application/json" } })
      .then((r) => { if (!r.ok) throw new Error(`injection-manifest.json: HTTP ${r.status}`); return r.json() as Promise<{ designed_relationships?: string[]; injections?: Injection[] }>; })
      .then((j) => { if (live) setD({ status: "ready", relationships: j.designed_relationships ?? [], injections: j.injections ?? [] }); })
      .catch((e: unknown) => { if (live) setD({ status: "error", error: e instanceof Error ? e.message : String(e) }); });
    return () => { live = false; };
  }, []);
  return d;
}

export function CaseStudy() {
  const designed = useDesigned();
  const { state } = useStudio();
  const rejected = state.status === "ready" ? state.result.rejected.length : null;
  return (
    <article className="prose">
      <ViewHead eyebrow="Case study" title="Onboard Studio: which onboarding workflow, and how to handle exceptions">
        <p className="lede">A business systems analyst has to choose between two onboarding workflows and decide how exceptions are handled. This project puts every case on one business-hours timeline so the choice rests on measured waiting, rework and SLA attainment instead of impressions.</p>
      </ViewHead>

      <section aria-labelledby="problem">
        <h2 id="problem">Problem</h2>
        <p>Onboarding looks slow, but calendar time hides why: weekends, holidays and customer waiting inflate it, and handoffs and rework add real delay. The decision (P02-GOAL-01) is which workflow version to adopt and how exceptions such as rejected documents and customer-info requests should be handled, without double counting time the team cannot act on.</p>
      </section>

      <section aria-labelledby="built">
        <h2 id="built">What was built</h2>
        <ul>
          <li>A case timeline: one case on one business-hours axis, with calendar gaps compressed, assignments as lanes, waiting intervals in amber with their reason and pause-eligibility, document versions and step states. See <Link to="cases">Cases</Link>.</li>
          <li>A workflow canvas: the steps and dependencies of each published version, plus an ordered list. See <Link to="workflow">Workflow</Link>.</li>
          <li>An SLA explorer: business against calendar time, attainment with its numerator and denominator, open cases shown separately, filters in the address and a CSV export. See <Link to="sla">SLA</Link>.</li>
          <li>A work queue of open step instances. See <Link to="queue">Queue</Link>.</li>
          <li>A TypeScript domain that mirrors the Python rules and is checked against a hand-derived golden fixture (calendar 66 h, business 2 h, active 1 h or 2 h).</li>
        </ul>
        <p>Intake, document review, bottlenecks, version comparison and the simulation are in progress and are not part of this milestone.</p>
      </section>

      <section aria-labelledby="choices">
        <h2 id="choices">Analytical choices</h2>
        <ul>
          <li><strong>D-01, time and calendars.</strong> Instants are UTC; the working calendar is a set of half-open intervals with holidays subtracted. Business time is the overlap of the case span with working intervals; paused time is only waiting whose reason the SLA rule lists as pause-eligible; active elapsed is business time minus the paused part that falls inside working hours. Customer waiting is never counted as employee processing.</li>
          <li><strong>D-02, workflow versions.</strong> A published version is immutable and carries a definition hash; a case binds one version and keeps it. A cycle in the dependencies is refused at publication.</li>
          <li><strong>D-03, steps, documents and approvals.</strong> A step is ready only when its mandatory prerequisites are approved; documents are append-only versions; reviewers cannot approve their own work; a completed case is never reopened, a correction opens a linked case.</li>
          <li><strong>D-04, rates and backlog.</strong> Rates are aggregated numerators over denominators. SLA attainment uses completed cases only; open cases are shown beside it, never inside it.</li>
          <li><strong>D-05 and D-06, clarifications.</strong> The SLA test is active minutes at most the rule's business minutes; population durations are means over completed cases; waiting intervals are clipped to the case span and merged before deduction; active hours floor at 0.</li>
          <li><strong>Pause-policy toggle.</strong> A view setting that recomputes the displayed figures with the configured policy or with none. It is labelled as a browser-memory view setting and changes no data.</li>
        </ul>
      </section>

      <section aria-labelledby="evidence">
        <h2 id="evidence">Evidence</h2>
        <ul>
          <li><a href={CI} rel="noreferrer">CI workflow: onboard-studio-ci</a> is the automated check for this app on GitHub-hosted runners; its run history is the evidence for the Python domain, database and API (Mode A) and for this site (Mode B).</li>
          <li><a href={SOURCE} rel="noreferrer">Source tree on GitHub</a> (branch business-data-lab).</li>
          <li>Every page footer prints the dataset version, dataset hash, contract version and the real generation time of the snapshot it shows. Add <code>?dataset=golden</code> to a view to see the golden fixture instead.</li>
          {rejected !== null && <li>Ingest of the published snapshot rejected {rejected} records with reason codes; they are kept raw and never enter a figure.</li>}
        </ul>
      </section>

      <section aria-labelledby="limits">
        <h2 id="limits">Limits</h2>
        <ul>
          <li><strong>Synthetic.</strong> Every organization, person, document and timestamp is generated. There is no real customer, no real document storage and no e-signature.</li>
          <li><strong>Static demo (Mode B).</strong> This site is a TypeScript re-implementation over a published snapshot; case actions are browser-memory simulations and a reload restores the snapshot. The Python domain, PostgreSQL and FastAPI commands (Mode A) are verified separately and are not running here.</li>
          <li><strong>Designed relationships, not discoveries.</strong> The generator builds in the effects below, so seeing them in the charts confirms the pipeline recovers them; it is not evidence about real onboarding.</li>
        </ul>
        {designed.status === "loading" && <p className="muted" role="status">Loading the designed relationships from data/injection-manifest.json.</p>}
        {designed.status === "error" && <p className="notice notice--error" role="alert">The injection manifest could not be loaded: {designed.error}. Nothing is substituted.</p>}
        {designed.status === "ready" && (
          <>
            <ul data-testid="designed-relationships">{designed.relationships.map((r) => <li key={r}>{r}</li>)}</ul>
            <p className="small muted">{designed.injections.length} injected data-quality cases are also recorded in the manifest (ids {designed.injections.map((i) => i.id).join(", ")}) so that ingest rejections can be checked against a known list.</p>
          </>
        )}
      </section>

      <p className="actions"><a className="btn btn--primary" href={PORTFOLIO} rel="noreferrer">Back to the portfolio</a> <Link to="cases" className="btn">Open the case timeline</Link></p>
    </article>
  );
}
