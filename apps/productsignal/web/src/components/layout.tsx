import { useEffect, useRef, type ReactNode } from "react";
import { ROUTES } from "../routes";
import { short } from "../lib/format";
import { useDataset, usePrimaryId } from "../state/data";
import { Link } from "./link";

export const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/productsignal";

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

export function Layout({ route, title, children }: { route: string | null; title: string; children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  const golden = usePrimaryId() === "golden";
  useEffect(() => {
    document.title = route === "" ? "ProductSignal" : `${title} · ProductSignal`;
    if (first.current) { first.current = false; return; }
    main.current?.focus({ preventScroll: true }); // announce the new view to keyboard and screen-reader users
  }, [route, title]);
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <div className="lab">
        <aside className="rail">
          <Link to="" className="brand" aria-label="ProductSignal, home">
            <span className="brand__mark" aria-hidden="true"><svg viewBox="0 0 32 32"><circle cx="9" cy="23" r="3.2" className="m-a" /><circle cx="23" cy="9" r="3.2" className="m-b" /><path d="M9 23 C 9 12, 23 20, 23 9" fill="none" strokeWidth="2" className="m-line" /></svg></span>
            <span className="brand__name">ProductSignal<small>product journey laboratory</small></span>
          </Link>
          <nav className="stations" aria-label="Primary">
            <ol>
              {ROUTES.filter((r) => r.path !== "").map((r, i) => (
                <li key={r.path}><Link to={r.path} aria-current={route === r.path ? "page" : undefined}><span className="stations__n mono" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span><span>{r.label}</span></Link></li>
              ))}
            </ol>
          </nav>
        </aside>
        <div className="stage">
          <header className="mast">
            <p className="badge" data-testid="synthetic-badge">Synthetic data, demo mode</p>
            <ManifestStrip />
            {golden && <p className="mast__golden" data-testid="golden-flag">Showing the golden fixture (?dataset=golden): 235 accounts, 200 assigned to one experiment, hand-derived expected results.</p>}
          </header>
          <p className="honesty" data-testid="honesty">
            <strong>Synthetic data, demo mode.</strong> Nothing ships from this site: the registry and the decision screen simulate in browser memory, and there is no live activity. Every figure is recomputed in your browser from a published snapshot.
          </p>
          <main id="main" ref={main} tabIndex={-1} className="main"><div className="wrap">{children}</div></main>
          <footer className="foot">
            <div className="wrap">
              <p data-testid="footer-honesty">Synthetic data. No real product, customer, person or company. Nothing here is live; no release, feature flag or experiment is changed from the site, and any action on the registry or decision screen is a simulation in browser memory that is gone on reload.</p>
              <p><a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a> · <a href={SOURCE}>Source</a> · <a href="https://github.com/mrrishit909/projects-site/actions/workflows/productsignal-ci.yml">CI workflow</a></p>
            </div>
          </footer>
        </div>
      </div>
    </>
  );
}
