import { Link } from "../components/link";

const PORTFOLIO = "https://mrrishit909.github.io/projects-site/supplyscope/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/supplyscope";
const EVIDENCE = "https://github.com/mrrishit909/projects-site/actions/workflows/supplyscope-ci.yml";

export function Landing() {
  return (
    <article className="landing">
      <p className="eyebrow">Business Data Lab · Project 03</p>
      <h1 className="display">SupplyScope</h1>
      <p className="lede" data-testid="decision">
        What should be ordered, when, and under which service and working-capital assumptions? SupplyScope rebuilds stock from a
        movement ledger, lines it up against reorder points and targets, and drafts the order quantities an operations analyst
        would review in a weekly buying plan: every draft shows its arithmetic, and none is ever a purchase order.
      </p>
      <p className="actions"><Link to="reorder" className="btn btn--primary">Start the demo</Link> <Link to="overview" className="btn">Planning overview</Link></p>

      <aside className="disclosure" aria-labelledby="mode-title">
        <h2 id="mode-title" className="disclosure__title">Mode disclosure</h2>
        <p>
          Static demo (Mode B): a TypeScript re-implementation of the domain rules over a published, synthetic snapshot. The
          simulator runs in your browser on a copy with the published seed and nothing is persisted; reloading restores the
          snapshot. The Python domain, PostgreSQL and FastAPI commands (Mode A) are verified separately on GitHub-hosted runners.
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
