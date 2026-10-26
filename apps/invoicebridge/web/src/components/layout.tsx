import { useEffect, useRef, type ReactNode } from "react";
import { ROUTES } from "../routes";
import { useStore } from "../state/store";
import { short } from "../lib/format";
import { Link } from "./link";

export const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/invoicebridge";

function ManifestStrip() {
  const { state } = useStore();
  const m = state.status === "ready" ? state.snapshot.manifest : null;
  if (!m) return <p className="strip strip--pending" data-testid="manifest-strip">{state.status === "error" ? "Dataset provenance unavailable: the snapshot did not load." : "Dataset provenance appears once the snapshot has loaded."}</p>;
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
  const { state } = useStore();
  const golden = state.status === "ready" && state.snapshot.golden;
  useEffect(() => {
    document.title = route === "" ? "InvoiceBridge" : `${title} · InvoiceBridge`;
    if (first.current) { first.current = false; return; }
    main.current?.focus({ preventScroll: true }); // announce the new view to keyboard and screen-reader users
  }, [route, title]);
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <div className="desk">
        <header className="mast">
          <div className="mast__row">
            <Link to="" className="brand" aria-label="InvoiceBridge, home"><span className="brand__mark" aria-hidden="true">IB</span><span className="brand__name">InvoiceBridge<small>reconciliation desk</small></span></Link>
            <p className="badge" data-testid="synthetic-badge">Synthetic data, demo mode</p>
          </div>
          <ManifestStrip />
          {golden && <p className="mast__golden" data-testid="golden-flag">Showing the golden fixture (?dataset=golden): one vendor, one purchase order line, three invoices (a pair and a re-sent copy).</p>}
        </header>
        <nav className="tabs" aria-label="Primary">
          <ul>
            {ROUTES.filter((r) => r.path !== "").map((r) => (
              <li key={r.path}><Link to={r.path} aria-current={route === r.path ? "page" : undefined}>{r.label}</Link></li>
            ))}
          </ul>
        </nav>
        <p className="honesty" data-testid="honesty">
          <strong>Synthetic data, demo mode.</strong> Nothing is approved, exported or paid from this site, and there is no live activity: every figure is recomputed in your browser from a published snapshot.
        </p>
        <main id="main" ref={main} tabIndex={-1} className="main"><div className="wrap">{children}</div></main>
        <footer className="foot">
          <div className="wrap">
            <p data-testid="footer-honesty">Synthetic data. No real supplier, invoice, person or company. Nothing here is live, nothing is approved, exported or paid from the site, and no bank or payment connection exists; any action on the intake desk is a simulation in browser memory.</p>
            <p><a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a> · <a href={SOURCE}>Source</a> · <a href="https://github.com/mrrishit909/projects-site/actions/workflows/invoicebridge-ci.yml">CI workflow</a></p>
          </div>
        </footer>
      </div>
    </>
  );
}

/** The opening of a view: an eyebrow, the h1 and an optional lede. */
export function ViewHead({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <header className="view-head">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {children}
    </header>
  );
}
