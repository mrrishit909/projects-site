import { useEffect, useRef, type ReactNode } from "react";
import { ROUTES } from "../routes";
import { short } from "../lib/format";
import { useDataset, usePrimaryId } from "../state/data";
import { Link } from "./link";

export const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/pipeline-observatory";
const CI = "https://github.com/mrrishit909/projects-site/actions/workflows/pipeline-observatory-ci.yml";

function ManifestStrip() {
  const s = useDataset(usePrimaryId());
  if (s.status !== "ready") return <p className="strip strip--pending" data-testid="manifest-strip">{s.status === "error" ? "Dataset provenance unavailable: the data did not load." : "Dataset provenance appears once the data has loaded."}</p>;
  const m = s.dataset.provenance;
  return (
    <dl className="strip" data-testid="manifest-strip" aria-label="Dataset provenance">
      <div><dt>dataset_version</dt><dd data-k="dataset_version">{m.dataset_version}</dd></div>
      <div><dt>dataset_hash</dt><dd data-k="dataset_hash" title={m.dataset_hash}>{short(m.dataset_hash, 16)}</dd></div>
      <div><dt>generated_at</dt><dd data-k="generated_at">{m.generated_at}</dd></div>
      <div><dt>code_sha</dt><dd data-k="code_sha" title={m.code_sha ?? "not recorded in the manifest until the snapshot is published by CI"}>{m.code_sha ? short(m.code_sha, 12) : "not recorded"}</dd></div>
    </dl>
  );
}

function Mark() {
  // a reticle: a ring, a cross-hair and one body in orbit
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className="brand__mark" focusable="false">
      <circle cx="16" cy="16" r="12" className="m-ring" />
      <circle cx="16" cy="16" r="6" className="m-ring m-ring--in" />
      <path d="M16 1v8M16 23v8M1 16h8M23 16h8" className="m-cross" />
      <circle cx="24.5" cy="8.5" r="2" className="m-body" />
    </svg>
  );
}

export function Layout({ route, title, children }: { route: string | null; title: string; children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  const golden = usePrimaryId() === "golden";
  useEffect(() => {
    document.title = route === "" ? "Pipeline Observatory" : `${title} · Pipeline Observatory`;
    if (first.current) { first.current = false; return; }
    main.current?.focus({ preventScroll: true }); // announce the new view to keyboard and screen-reader users
  }, [route, title]);
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="rail">
        <Link to="" className="brand" aria-label="Pipeline Observatory, home">
          <Mark />
          <span className="brand__name">Pipeline<br />Observatory<small>is this dataset safe, complete and fresh enough to publish?</small></span>
        </Link>
        <nav className="nav" aria-label="Primary">
          <details className="nav__menu" open>
            <summary>Routes</summary>
            <ol>
              {ROUTES.filter((r) => r.path !== "").map((r, i) => (
                <li key={r.path}><Link to={r.path} aria-current={route === r.path ? "page" : undefined}><span className="nav__n" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>{r.label}</Link></li>
              ))}
            </ol>
          </details>
        </nav>
      </aside>
      <div className="stage">
        <header className="topbar">
          <p className="badge" data-testid="synthetic-badge">Synthetic data, demo mode</p>
          <ManifestStrip />
        </header>
        {golden && <p className="golden-flag" data-testid="golden-flag">Showing the golden fixture (<code>?dataset=golden</code>): two sources, 32 raw rows, hand-derived expected results, recomputed here from inputs.json. <a href={`${import.meta.env.BASE_URL}${route ? `${route}/` : ""}`} data-testid="golden-exit">Back to the snapshot</a></p>}
        <p className="honesty" data-testid="honesty">
          <strong>Synthetic data, demo mode.</strong> The quarantine desk, the backfill console and fault injection are simulations in browser memory that reset on reload; nothing is fetched, retried, published or written. Published <code>raw_records</code> are a 2,000-row sample of 40,191 written rows: a figure tagged <em>2,000-row sample</em> describes the sample, <em>Complete world</em> comes from files published in full, <em>Recorded</em> is the generator&apos;s own statement.
        </p>
        <main id="main" ref={main} tabIndex={-1} className="main">{children}</main>
        <footer className="foot">
          <p data-testid="footer-honesty">Synthetic data. No real company, customer, source system or person. Nothing here is live: no batch is fetched, no checkpoint moves, no publication changes. The quarantine desk, backfill console and fault injection are simulations in browser memory that are gone on reload. The delivery guarantee claimed is at-least-once with idempotent apply at the source-key boundary, never exactly-once.</p>
          <p><a href={PORTFOLIO}>Back to Rishit Raj Mathur&apos;s projects</a> · <a href={SOURCE}>Source</a> · <a href={CI}>CI workflow</a></p>
        </footer>
      </div>
    </div>
  );
}
