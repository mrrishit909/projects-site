import { useEffect, useRef, useState, type ReactNode } from "react";
import { ROUTES } from "../routes";
import { short } from "../lib/format";
import { useDataset, usePrimaryId } from "../state/data";
import { Link } from "./link";

export const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/retentionlab";

function ManifestStrip() {
  const s = useDataset(usePrimaryId());
  if (s.status !== "ready") return <p className="strip strip--pending" data-testid="manifest-strip">{s.status === "error" ? "Dataset provenance unavailable: the data did not load." : "Dataset provenance appears once the data has loaded."}</p>;
  const m = s.dataset.strip;
  return (
    <dl className="strip" data-testid="manifest-strip" aria-label="Dataset provenance">
      <div><dt>dataset_version</dt><dd data-k="dataset_version">{m.dataset_version}</dd></div>
      <div><dt>dataset_hash</dt><dd data-k="dataset_hash" title={m.dataset_hash}>{short(m.dataset_hash, 16)}</dd></div>
      <div><dt>generated_at</dt><dd data-k="generated_at">{m.generated_at}</dd></div>
      <div><dt>as_of</dt><dd data-k="as_of">{m.as_of}</dd></div>
      <div><dt>contract</dt><dd data-k="contract_version">v{m.contract_version.replace(/^v/, "")}</dd></div>
    </dl>
  );
}

function Mark() {
  // a reliability curve against its diagonal: the lab's one instrument
  return (
    <svg viewBox="0 0 36 36" aria-hidden="true" className="brand__mark" focusable="false">
      <rect x="1" y="1" width="34" height="34" rx="7" fill="#3d2046" stroke="#4a2e52" />
      <path d="M6 30L30 6" stroke="#7fc8b8" strokeWidth="1.6" strokeDasharray="3 2.5" fill="none" />
      <path d="M6 28C12 27 15 24 19 20S26 14 30 9" stroke="#ef7a6a" strokeWidth="2.4" fill="none" strokeLinecap="round" />
      <circle cx="12" cy="26.4" r="2" fill="#ef7a6a" /><circle cx="19" cy="20" r="2.8" fill="#ef7a6a" /><circle cx="28" cy="10.6" r="1.6" fill="#ef7a6a" />
    </svg>
  );
}

export function Layout({ route, title, children }: { route: string | null; title: string; children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  const [open, setOpen] = useState(false);
  const golden = usePrimaryId() === "golden";
  useEffect(() => {
    document.title = route === "" ? "RetentionLab" : `${title} · RetentionLab`;
    setOpen(false);
    if (first.current) { first.current = false; return; }
    main.current?.focus({ preventScroll: true }); // announce the new view to keyboard and screen-reader users
  }, [route, title]);
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <div className="frame">
        <header className="frame__rail house">
          <div className="house__row">
            <Link to="" className="brand" aria-label="RetentionLab, home">
              <Mark />
              <span className="brand__name">RetentionLab<small>a customer intelligence lab</small></span>
            </Link>
            <p className="badge" data-testid="synthetic-badge">Synthetic data, demo mode</p>
          </div>
          <button type="button" className="menu-toggle" aria-expanded={open} aria-controls="primary-nav" onClick={() => setOpen(!open)} data-testid="menu-toggle">{open ? "Hide the routes" : "Show the routes"}</button>
          <nav id="primary-nav" className={`rail${open ? " is-open" : ""}`} aria-label="Primary">
            <ol>
              {ROUTES.filter((r) => r.path !== "").map((r, i) => (
                <li key={r.path}><Link to={r.path} aria-current={route === r.path ? "page" : undefined}><span className="rail__n" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>{r.label}</Link></li>
              ))}
            </ol>
          </nav>
        </header>
        <div className="frame__content">
          <div className="wrap"><ManifestStrip /></div>
          {golden && <p className="golden-flag wrap" data-testid="golden-flag">Showing the golden fixture (?dataset=golden): fourteen accounts, hand-derived expected results, recomputed in your browser. <a href={`${import.meta.env.BASE_URL}${route ? `${route}/` : ""}`} data-testid="golden-exit">Back to the snapshot</a></p>}
          <div className="honesty" data-testid="honesty">
            <div className="wrap">
              <strong>Synthetic data, demo mode.</strong> No real customer, company or system; every figure is recomputed in your browser from a published snapshot.
              <ul>
                <li>The capacity planner, the economics and the outreach queue are simulations in browser memory that reset on reload. Nothing is sent to anyone.</li>
                <li>A high churn risk is not treatment responsiveness: the ranking says who is likely to leave, not who an offer would keep.</li>
                <li>The model's margin over the baselines was reached by construction: the generator's signal was strengthened until the margins were met (disclosure D-G02).</li>
              </ul>
            </div>
          </div>
          <main id="main" ref={main} tabIndex={-1} className="main"><div className="wrap">{children}</div></main>
          <footer className="foot">
            <div className="wrap">
              <p data-testid="footer-honesty">Synthetic data. No real company, customer, person or system. Nothing here is live: no offer, e-mail or call is sent, and the capacity planner, the economics and the outreach queue are simulations in browser memory that are gone on reload. Expected values are hypothetical and rest on stated assumptions; no retention improvement is claimed.</p>
              <p><a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a> · <a href={SOURCE}>Source</a></p>
            </div>
          </footer>
        </div>
      </div>
    </>
  );
}
