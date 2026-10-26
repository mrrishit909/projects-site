import { useEffect, useRef, type ReactNode } from "react";
import { useAtlas } from "../state/atlas";
import { ROUTES } from "../routes";
import { Link } from "./link";

const short = (s: string, n = 12): string => (s.length > n ? `${s.slice(0, n)}…` : s);

function Footer() {
  const { state } = useAtlas();
  const m = state.status === "ready" ? state.snapshot.manifest : null;
  const val = (v: string | undefined, n?: number) => (v ? (n ? short(v, n) : v) : "not recorded");
  return (
    <footer className="site-footer">
      <div className="wrap">
        <p className="synthetic-tag">Synthetic data. No real customer, price or company.</p>
        {m ? (
          <dl className="provenance">
            <div><dt>dataset_version</dt><dd>{m.dataset_version}</dd></div>
            <div><dt>dataset_hash</dt><dd title={m.dataset_hash}>{short(m.dataset_hash, 16)}</dd></div>
            <div><dt>generated_at</dt><dd>{m.generated_at}</dd></div>
            <div><dt>contract_version</dt><dd>{m.contract_version}</dd></div>
            <div><dt>code_sha</dt><dd title={m.code_sha}>{val(m.code_sha, 12)}</dd></div>
          </dl>
        ) : (
          <p className="provenance-pending">
            {state.status === "error" ? "Dataset provenance unavailable: the snapshot did not load." : "Dataset provenance appears once the snapshot has loaded."}
          </p>
        )}
      </div>
    </footer>
  );
}

export function Layout({ route, title, children }: { route: string | null; title: string; children: ReactNode }) {
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  useEffect(() => {
    document.title = route === "" ? "Revenue Atlas" : `${title} · Revenue Atlas`;
    if (first.current) { first.current = false; return; }
    main.current?.focus({ preventScroll: true }); // announce the new view to keyboard and screen-reader users
  }, [route, title]);
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="wrap site-header__row">
          <Link to="" className="brand" aria-label="Revenue Atlas, home"><span className="brand__mark" aria-hidden="true">RA</span> Revenue Atlas</Link>
          <nav aria-label="Primary">
            <ul className="nav">
              {ROUTES.filter((r) => r.path !== "").map((r) => (
                <li key={r.path}><Link to={r.path} aria-current={route === r.path ? "page" : undefined}>{r.label}</Link></li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <main id="main" ref={main} tabIndex={-1} className="main"><div className="wrap">{children}</div></main>
      <Footer />
    </>
  );
}
