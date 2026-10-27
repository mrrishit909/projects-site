import { useEffect, useRef, useState, type ReactNode } from "react";
import { ROUTES } from "../routes";
import { short } from "../lib/format";
import { useDataset, usePrimaryId } from "../state/data";
import { Link } from "./link";

export const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/changeworks";

function ManifestStrip() {
  const s = useDataset(usePrimaryId());
  if (s.status !== "ready") return <p className="strip strip--pending" data-testid="manifest-strip">{s.status === "error" ? "Dataset provenance unavailable: the data did not load." : "Dataset provenance appears once the data has loaded."}</p>;
  const m = s.dataset.manifest;
  return (
    <dl className="strip" data-testid="manifest-strip" aria-label="Dataset provenance">
      <div><dt>dataset_version</dt><dd data-k="dataset_version">{m.dataset_version}</dd></div>
      <div><dt>dataset_hash</dt><dd data-k="dataset_hash" title={m.dataset_hash}>{short(m.dataset_hash, 16)}</dd></div>
      <div><dt>generated_at</dt><dd data-k="generated_at">{m.generated_at}</dd></div>
      <div><dt>as_of</dt><dd data-k="as_of">{m.as_of}</dd></div>
    </dl>
  );
}

function Mark() {
  // three stepped bars joined by a dependency arrow: a roadmap, in brass on the green spine
  return (
    <svg viewBox="0 0 34 34" aria-hidden="true" className="brand__mark" focusable="false">
      <rect x="1" y="1" width="32" height="32" rx="2" fill="none" stroke="#b08d57" strokeWidth="1.4" />
      <rect x="5" y="6" width="12" height="5" fill="#b08d57" /><rect x="12" y="14" width="12" height="5" fill="#efe6cf" /><rect x="19" y="22" width="10" height="5" fill="#b08d57" />
      <path d="M11 11v3.5h1M18 19v3.5h1" fill="none" stroke="#efe6cf" strokeWidth="1.1" />
    </svg>
  );
}

export function Layout({ route, title, children }: { route: string | null; title: string; children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  const golden = usePrimaryId() === "golden";
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 980px)");
    const sync = (): void => setOpen(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  useEffect(() => {
    document.title = route === "" ? "ChangeWorks" : `${title} · ChangeWorks`;
    if (first.current) { first.current = false; return; }
    main.current?.focus({ preventScroll: true }); // announce the new view to keyboard and screen-reader users
    if (!window.matchMedia("(min-width: 980px)").matches) setOpen(false);
  }, [route, title]);
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <div className="shell">
        <aside className="spine">
          <Link to="" className="brand" aria-label="ChangeWorks, home">
            <Mark />
            <span className="brand__name">ChangeWorks<small>an investment atelier for transformation</small></span>
          </Link>
          <details className="menu" open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
            <summary>Chapters</summary>
            <nav aria-label="Primary">
              <ol className="chapters">
                {ROUTES.filter((r) => r.path !== "").map((r, i) => (
                  <li key={r.path}><Link to={r.path} aria-current={route === r.path ? "page" : undefined}><span className="n" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span><span>{r.label}</span></Link></li>
                ))}
              </ol>
            </nav>
          </details>
          <p className="badge" data-testid="synthetic-badge">Synthetic data, demo mode</p>
        </aside>
        <div className="sheet">
          <ManifestStrip />
          {golden && <p className="golden-flag wrap" data-testid="golden-flag">Showing the golden fixture (?dataset=golden): three initiatives, one annual scenario, hand-derived expected results. <a href={`${import.meta.env.BASE_URL}${route ? `${route}/` : ""}`} data-testid="golden-exit">Back to the snapshot</a></p>}
          <div className="honesty wrap" data-testid="honesty">
            <strong>Synthetic data, demo mode.</strong> No real company, person or money. Nothing here is funded.
            <ul>
              <li>The sensitivity lab, roadmap edits and scenario selection are <strong>simulations in browser memory</strong>: they reset on reload and change no published figure.</li>
              <li>The snapshot is a <strong>first-year case</strong>: benefits are recognised for 12 periods per stream, so NPV and payback describe the first year after go-live.</li>
              <li>Every scenario is a draft estimate; selecting one only makes a <strong>proposal</strong>, and an observed change is <strong>not attributed</strong> to the rollout.</li>
            </ul>
          </div>
          <main id="main" ref={main} tabIndex={-1} className="main"><div className="wrap">{children}</div></main>
          <footer className="foot">
            <div className="wrap">
              <p data-testid="footer-honesty">Synthetic data. No real company, customer, person or system. Nothing here is live and nothing is funded: the sensitivity lab, the roadmap edits and the scenario selection are simulations in browser memory that are gone on reload, and every figure is recomputed in your browser from a published snapshot.</p>
              <p><a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a> · <a href={SOURCE}>Source</a> · <a href="https://github.com/mrrishit909/projects-site/actions/workflows/changeworks-ci.yml">CI workflow</a></p>
            </div>
          </footer>
        </div>
      </div>
    </>
  );
}
