import { useState, type ReactNode } from "react";
import { useStore, type Ready } from "../state/store";
import { Link } from "./link";

/** Renders children once the snapshot is loaded and recomputed; otherwise an honest loading or error state. */
export function WithData({ children }: { children: (d: Ready) => ReactNode }) {
  const { state, reload } = useStore();
  if (state.status === "loading") return <p className="notice" role="status" data-testid="loading">Loading the published snapshot and recomputing every figure in the browser…</p>;
  if (state.status === "error") return <div className="notice notice--bad" role="alert" data-testid="load-error"><p>The data did not load: {state.error}</p><button type="button" onClick={reload}>Try again</button></div>;
  return <>{children(state)}</>;
}

const KIND: Record<string, string> = {
  matched: "ok", approved: "ok", exported: "ok", adjusted: "ok", COUNTED: "ok", new: "plain", assigned: "plain",
  exception: "bad", open: "bad", rejected: "bad", invalid: "bad", QUANTITY_BLOCKED: "bad", PRICE_VARIANCE: "bad", NO_PO_LINE: "bad", CURRENCY_MISMATCH: "bad", ROUNDING_EXCEPTION: "bad",
  SELF_APPROVAL: "bad", ROLE_OR_LIMIT: "bad", NOT_MATCHED: "bad", NOT_REVIEWABLE: "bad", REJECT_AFTER_APPROVAL: "bad",
  BEFORE_IMPORT: "bad", SELF_DECISION: "bad", EXPORT_BEFORE_APPROVAL: "bad", APPROVED_NOT_EXPORTED: "warn", needs_review: "warn", BYTES_FIELDS_CONFLICT: "warn",
  merged: "warn", DUPLICATE_IDENTITY: "warn", DUPLICATE_SOURCE_BYTES: "warn", SUPERSEDED: "warn", received: "plain",
};
/** A stamp-like status label; the colour is never the only signal (the word is always printed). */
export function Chip({ v, children }: { v: string; children?: ReactNode }) {
  return <span className={`chip chip--${KIND[v] ?? "plain"}`} data-chip={v}>{children ?? v}</span>;
}

/** A definition popover: a native disclosure, so it works with keyboard and without a script. */
export function Def({ term, children }: { term: string; children: ReactNode }) {
  return <details className="def"><summary><span>{term}</span><span className="def__q" aria-hidden="true">?</span></summary><div className="def__body">{children}</div></details>;
}

export function Scroll({ children, label }: { children: ReactNode; label?: string }) {
  return <div className="scroll" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}

/** Page through a long list: the table renders `size` rows at a time. */
export function usePager<T>(rows: readonly T[], size = 25): { page: T[]; ui: ReactNode; start: number } {
  const [n, setN] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const cur = Math.min(n, pages - 1);
  const ui = (
    <p className="pager" data-testid="pager">
      <button type="button" disabled={cur === 0} onClick={() => setN(cur - 1)}>Previous</button>
      <span>{rows.length === 0 ? "No rows" : `Rows ${cur * size + 1}-${Math.min(rows.length, cur * size + size)} of ${rows.length.toLocaleString("en-US")}`}</span>
      <button type="button" disabled={cur >= pages - 1} onClick={() => setN(cur + 1)}>Next</button>
    </p>
  );
  return { page: rows.slice(cur * size, cur * size + size), ui, start: cur * size };
}

export const InvoiceLink = ({ id }: { id: string }) => <Link to={`invoices?invoice=${id}`} className="mono">{id}</Link>;

/** A small honest label for what a view does not do. */
export function NotBuilt({ children }: { children: ReactNode }) {
  return <aside className="notbuilt" data-testid="not-built"><strong>Not built here.</strong> {children}</aside>;
}
