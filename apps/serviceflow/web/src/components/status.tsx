import type { ReactNode } from "react";
import { useStore, type Ready } from "../state/store";

export function Loading() {
  return (
    <div className="status" role="status" aria-live="polite" data-testid="loading">
      <p className="status__title">Loading the published snapshot</p>
      <p className="status__body">Reading the synthetic dataset, replaying every ticket's event log and recomputing every figure in your browser.</p>
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
/** Renders `children` only when the snapshot is loaded and the pipeline has run; otherwise the matching status. */
export function Gate({ children }: { children: (s: Ready) => ReactNode }) {
  const { state, reload } = useStore();
  if (state.status === "loading") return <Loading />;
  if (state.status === "error") return <ErrorState message={state.error} onRetry={reload} />;
  return <>{children(state)}</>;
}
