import type { ReactNode } from "react";
import "../styles/screens.css";

/** Metric definitions, collapsed by default, each citing the contract rule it implements. */
export const METRICS: readonly { name: string; rule: string; text: string }[] = [
  { name: "Calendar hours", rule: "D-01", text: "completed_at minus opened_at, in hours, 4 decimals. Completed cases only." },
  { name: "Business hours", rule: "D-01", text: "The overlap of [opened_at, completed_at) with the calendar's working intervals; holidays are subtracted from the working set." },
  { name: "Paused (calendar)", rule: "D-01", text: "The merged length of waiting intervals whose reason is pause-eligible under the case's SLA rule, clipped to the case span. Customer waiting is never counted as employee processing." },
  { name: "Paused business overlap", rule: "D-01", text: "The part of the paused time that falls inside working intervals. A pause outside every working interval contributes 0 and is flagged." },
  { name: "Active elapsed", rule: "D-01", text: "Business hours minus paused business overlap, never below 0." },
  { name: "SLA attainment", rule: "D-04, D-05", text: "Completed eligible cases whose active elapsed minutes are at most the rule's business minutes, divided by completed eligible cases. Open cases are shown beside it, never inside it. Null when no case has completed." },
  { name: "Pause policy toggle", rule: "view setting", text: "Configured uses each SLA rule's pause_policy; None treats no reason as pause-eligible. It recomputes the displayed figures in your browser and changes no data." },
];

export function Definition({ title = "Metric definitions", children }: { title?: string; children?: ReactNode }) {
  return (
    <details className="definition">
      <summary>{title}</summary>
      {children ?? (
        <dl className="definition__list">
          {METRICS.map((m) => (
            <div key={m.name}><dt>{m.name} <span className="chip">{m.rule}</span></dt><dd>{m.text}</dd></div>
          ))}
        </dl>
      )}
    </details>
  );
}
