import { useEffect, useRef, type ReactNode } from "react";
import { ROUTES } from "../routes";
import { useAtlas } from "../state/atlas";
import { Link } from "./link";

/** Routes whose views are built in a later milestone. */
const IN_PROGRESS = new Set(["locations", "suppliers", "simulator", "capital", "draft"]);
const short = (s: string, n = 12): string => (s.length > n ? `${s.slice(0, n)}…` : s);

function Footer() {
  const { state } = useAtlas();
  const m = state.status === "ready" ? state.snapshot.manifest : null;
  return (
    <footer className="site-footer">
      <div className="wrap">
        <p className="synthetic-tag">Synthetic data. No real company, product, supplier or purchase order.{state.status === "ready" && state.snapshot.golden ? " Showing the golden fixture (?dataset=golden)." : ""}</p>
        {m ? (
          <dl className="provenance">
            <div><dt>dataset_version</dt><dd>{m.dataset_version}</dd></div>
            <div><dt>dataset_hash</dt><dd title={m.dataset_hash}>{short(m.dataset_hash, 16)}</dd></div>
            <div><dt>generated_at</dt><dd>{m.generated_at}</dd></div>
            <div><dt>contract_version</dt><dd>{m.contract_version}</dd></div>
            <div><dt>code_sha</dt><dd title={m.code_sha}>{m.code_sha ? short(m.code_sha, 12) : "not recorded"}</dd></div>
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
    document.title = route === "" ? "SupplyScope" : `${title} · SupplyScope`;
    if (first.current) { first.current = false; return; }
    main.current?.focus({ preventScroll: true }); // announce the new view to keyboard and screen-reader users
  }, [route, title]);
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="wrap site-header__row">
          <Link to="" className="brand" aria-label="SupplyScope, home"><span className="brand__mark" aria-hidden="true"><i /><i /><i /><i /></span> SupplyScope</Link>
          <nav aria-label="Primary">
            <ul className="nav">
              {ROUTES.filter((r) => r.path !== "").map((r) => (
                <li key={r.path}><Link to={r.path} aria-current={route === r.path ? "page" : undefined}>{r.label}{IN_PROGRESS.has(r.path) && <span className="nav__tag"> in progress</span>}</Link></li>
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
