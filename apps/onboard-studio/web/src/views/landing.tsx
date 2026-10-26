import { Link } from "../components/link";

const PORTFOLIO = "https://mrrishit909.github.io/projects-site/onboard-studio/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/onboard-studio";
const EVIDENCE = "https://github.com/mrrishit909/projects-site/actions/workflows/onboard-studio-ci.yml";

export function Landing() {
  return (
    <article className="landing">
      <p className="eyebrow">Business Data Lab · Project 02</p>
      <h1 className="display">Onboard Studio</h1>
      <p className="lede">
        Which onboarding workflow should be adopted, and how should exceptions be handled? Onboard Studio lays every case out on
        one business-hours timeline, so a business systems analyst can compare two workflow versions on cycle time, waiting,
        rework and SLA attainment, and see which waits belong to the customer and which to the team.
      </p>
      <p className="actions"><Link to="cases" className="btn btn--primary">Start the demo</Link></p>

      <aside className="disclosure" aria-labelledby="mode-title">
        <h2 id="mode-title" className="disclosure__title">Mode disclosure</h2>
        <p>
          Static demo (Mode B): a TypeScript re-implementation of the domain rules over a published, synthetic snapshot.
          Every case action is a browser-memory simulation; reloading restores the snapshot. The Python domain, PostgreSQL
          and FastAPI commands (Mode A) are verified separately on GitHub-hosted runners.
        </p>
      </aside>

      <section aria-labelledby="links-title">
        <h2 id="links-title" className="section-title">Links</h2>
        <ul className="link-list">
          <li><a href={PORTFOLIO} rel="noreferrer">Portfolio entry</a></li>
          <li><a href={SOURCE} rel="noreferrer">Source on GitHub</a> <span className="muted">(branch business-data-lab)</span></li>
          <li><a href={EVIDENCE} rel="noreferrer">Evidence: CI workflow</a></li>
        </ul>
      </section>
    </article>
  );
}
