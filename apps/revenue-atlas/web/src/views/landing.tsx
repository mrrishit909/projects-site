import { Link } from "../components/link";

const PORTFOLIO = "https://mrrishit909.github.io/projects-site/revenue-atlas/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/revenue-atlas";
const EVIDENCE = "https://github.com/mrrishit909/projects-site/actions";

export function Landing() {
  return (
    <article className="landing">
      <p className="eyebrow">Business Data Lab · Project 01</p>
      <h1 className="display">Revenue Atlas</h1>
      <p className="lede">
        Which customer, product, region or discount policy explains declining contribution margin? Revenue Atlas
        reconciles every shipment line from gross sales to contribution, so a revenue analyst preparing the
        monthly margin review can trace each dollar of discount, cost, credit and freight to exactly one line.
      </p>
      <p><Link to="overview" className="btn btn--primary">Start the demo</Link></p>

      <aside className="disclosure" aria-labelledby="mode-title">
        <h2 id="mode-title" className="disclosure__title">Mode disclosure</h2>
        <p>
          Static demo. Synthetic data. Actions are browser-memory simulations; reload restores the published
          snapshot. Backend behaviour is verified separately in CI.
        </p>
      </aside>

      <section aria-labelledby="links-title">
        <h2 id="links-title" className="section-title">Links</h2>
        <ul className="link-list">
          <li><a href={PORTFOLIO} rel="noreferrer">Portfolio entry</a> <span className="muted">(placeholder until published)</span></li>
          <li><a href={SOURCE} rel="noreferrer">Source on GitHub</a> <span className="muted">(branch business-data-lab)</span></li>
          <li><a href={EVIDENCE} rel="noreferrer">Evidence: CI runs</a> <span className="muted">(placeholder for the run link)</span></li>
        </ul>
      </section>
    </article>
  );
}
