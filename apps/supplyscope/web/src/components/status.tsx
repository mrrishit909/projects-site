import type { ReactNode } from "react";
import { useAtlas, type Ready } from "../state/atlas";

export function Loading({ what = "the published snapshot" }: { what?: string }) {
  return (
    <div className="status status--loading" role="status" aria-live="polite">
      <p className="status__title">Loading {what}</p>
      <p className="status__body">Reading the synthetic dataset, rebuilding stock from the ledger and recomputing every figure in your browser.</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="status status--error" role="alert">
      <p className="status__title">The data could not be loaded</p>
      <p className="status__body">{message}</p>
      <p className="status__body">No figures are shown, and none are substituted, while the snapshot is unavailable.</p>
      {onRetry && <button type="button" className="btn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Empty({ title = "Nothing to show", children }: { title?: string; children?: ReactNode }) {
  return (
    <div className="status status--empty" role="status">
      <p className="status__title">{title}</p>
      {children && <div className="status__body">{children}</div>}
    </div>
  );
}

/** Renders `children` only when the snapshot is loaded and the pipeline has run; otherwise the matching status. */
export function Gate({ children }: { children: (s: Ready) => ReactNode }) {
  const { state, reload } = useAtlas();
  if (state.status === "loading") return <Loading />;
  if (state.status === "error") return <ErrorState message={state.error} onRetry={reload} />;
  return <>{children(state)}</>;
}
