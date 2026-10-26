import type { ReactNode } from "react";
import { useStudio, type StudioState } from "../state/studio";
import { ErrorState, Loading } from "./status";

export type Ready = Extract<StudioState, { status: "ready" }>;

/** Renders its children only once the snapshot has loaded and the metrics are computed; otherwise an explicit loading or error state. */
export function Gate({ children }: { children: (s: Ready) => ReactNode }) {
  const { state, reload } = useStudio();
  if (state.status === "loading") return <Loading />;
  if (state.status === "error") return <ErrorState message={state.error} onRetry={reload} />;
  return <>{children(state)}</>;
}

export function ViewHead({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <header className="view-head">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {children}
      <p><span className="synthetic-note">Synthetic data. No real customer, document or person.</span></p>
    </header>
  );
}
