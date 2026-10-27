import { useEffect, useRef, type ReactNode } from "react";
import { ROUTES } from "../routes";
import { short } from "../lib/format";
import { useDataset, usePrimaryId } from "../state/data";
import { Link } from "./link";

export const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/trustledger";

function ManifestStrip() {
  const s = useDataset(usePrimaryId());
  if (s.status !== "ready") return <p className="strip strip--pending" data-testid="manifest-strip">{s.status === "error" ? "Dataset provenance unavailable: the data did not load." : "Dataset provenance appears once the data has loaded."}</p>;
  const m = s.dataset.manifest;
  return (
    <dl className="strip" data-testid="manifest-strip" aria-label="Dataset provenance">
      <div><dt>dataset_version</dt><dd data-k="dataset_version">{m.dataset_version}</dd></div>
      <div><dt>dataset_hash</dt><dd data-k="dataset_hash" title={m.dataset_hash}>{short(m.dataset_hash, 16)}</dd></div>
      <div><dt>generated_at</dt><dd data-k="generated_at">{m.generated_at}</dd></div>
      <div><dt>code_sha</dt><dd data-k="code_sha" title={m.code_sha ?? "not recorded in the manifest"}>{m.code_sha ? short(m.code_sha, 12) : "not recorded"}</dd></div>
    </dl>
  );
}

function Mark() {
  // a library index card: a ruled card with the punch hole at its foot
  return (
    <svg viewBox="0 0 28 36" aria-hidden="true" className="brand__mark" focusable="false">
      <rect x="2" y="1.5" width="24" height="33" rx="2" className="m-card" />
      <path d="M6 9h16M6 14h16M6 19h10" className="m-rule" />
      <path d="M6 24.5l3 3 6-6.5" className="m-tick" />
      <circle cx="14" cy="31" r="1.5" className="m-hole" />
    </svg>
  );
}

export function Layout({ route, title, children }: { route: string | null; title: string; children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  const golden = usePrimaryId() === "golden";
  useEffect(() => {
    document.title = route === "" ? "TrustLedger" : `${title} · TrustLedger`;
    if (first.current) { first.current = false; return; }
    main.current?.focus({ preventScroll: true }); // announce the new view to keyboard and screen-reader users
  }, [route, title]);
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="house">
        <div className="house__row wrap">
          <Link to="" className="brand" aria-label="TrustLedger, home">
            <Mark />
            <span className="brand__name">TrustLedger<small>an evidence library for data trust</small></span>
          </Link>
          <p className="badge" data-testid="synthetic-badge">Synthetic data, demo mode</p>
        </div>
        <nav className="drawer wrap" aria-label="Primary">
          <ol>
            {ROUTES.filter((r) => r.path !== "").map((r, i) => (
              <li key={r.path}><Link to={r.path} aria-current={route === r.path ? "page" : undefined}><span className="drawer__n" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>{r.label}</Link></li>
            ))}
          </ol>
        </nav>
        <div className="wrap"><ManifestStrip /></div>
      </header>
      {golden && <p className="golden-flag wrap" data-testid="golden-flag">Showing the golden fixture (?dataset=golden): five datasets, 140 rows, hand-derived expected results. <a href={`${import.meta.env.BASE_URL}${route ? `${route}/` : ""}`} data-testid="golden-exit">Back to the snapshot</a></p>}
      <p className="honesty wrap" data-testid="honesty">
        <strong>Synthetic data, demo mode.</strong> Nothing is merged, closed or disabled from this site: the issue workbench and the duplicate review simulate in browser memory, and there is no live activity. Every figure is recomputed in your browser from a published snapshot.
      </p>
      <main id="main" ref={main} tabIndex={-1} className="main"><div className="wrap">{children}</div></main>
      <footer className="foot">
        <div className="wrap">
          <p data-testid="footer-honesty">Synthetic data. No real company, customer, person or system. Nothing here is live: no dataset is registered, no issue is closed, no pair is merged and no rule is disabled from the site, and any action on the issue workbench or the duplicate review is a simulation in browser memory that is gone on reload.</p>
          <p><a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a> · <a href={SOURCE}>Source</a> · <a href="https://github.com/mrrishit909/projects-site/actions/workflows/trustledger-ci.yml">CI workflow</a></p>
        </div>
      </footer>
    </>
  );
}
