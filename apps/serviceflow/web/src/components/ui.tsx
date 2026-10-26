import type { ArrivalRealisation } from "../domain/types";
import type { ReactNode } from "react";

/** A value that may be null: null is shown as "no value" (never as 0 or blank). */
export function V({ v, unit }: { v: string | number | null; unit?: string | undefined }) {
  return v === null ? <span className="null" title="no value: the denominator is empty">no value</span> : <>{v}{unit ? <span className="unit">{unit}</span> : null}</>;
}

/** A control-room readout: label, a large monospaced figure and an optional note. */
export function Readout({ id, label, value, unit, note, tone }: { id: string; label: string; value: string | number | null; unit?: string; note?: ReactNode; tone?: "alert" }) {
  return (
    <div className={`readout${tone ? ` readout--${tone}` : ""}`} data-figure={id}>
      <dt>{label}</dt>
      <dd className="readout__v"><V v={value} unit={unit} /></dd>
      {note ? <dd className="readout__n">{note}</dd> : null}
    </div>
  );
}

export function Panel({ title, id, children, tone }: { title: string; id?: string; children: ReactNode; tone?: "night" }) {
  return (
    <section className={`panel${tone === "night" ? " panel--night" : ""}`} aria-labelledby={id ? `${id}-h` : undefined} data-testid={id}>
      <h2 id={id ? `${id}-h` : undefined} className="panel__title">{title}</h2>
      {children}
    </section>
  );
}

export function Definition({ title = "Definitions", items }: { title?: string; items: readonly { name: string; rule: string; text: string }[] }) {
  return (
    <details className="definition">
      <summary>{title}</summary>
      <dl className="definition__list">
        {items.map((m) => <div key={m.name}><dt>{m.name} <span className="chip">{m.rule}</span></dt><dd>{m.text}</dd></div>)}
      </dl>
    </details>
  );
}

/** The rules the metrics follow, quoted from docs/contracts.md. */
export const RULES = {
  p90: { name: "P90 beside the mean", rule: "D-02", text: "The 90th percentile uses the nearest-rank method: sort ascending and take the value at index ceil(0.9 n). Every average is shown beside its P90 because a mean hides the tail (P04-TEST-10)." },
  firstResponse: { name: "First response", rule: "D-02, D-05", text: "The first human reply minus the arrival. Bot acknowledgements (actor ids starting bot-) never count. A ticket with no human reply is outside this population and is disclosed." },
  resolution: { name: "Resolution", rule: "D-02, D-06, D-09", text: "The final resolution minus the ORIGINAL arrival; a transfer never moves the arrival, and a reopened ticket reports its last cycle with the reopen count disclosed. A reopened ticket is therefore charged its dormant gap, the time between its first resolution and its reopen, against the resolution target." },
  wait: { name: "Wait to first service", rule: "D-02, D-09", text: "The first service_started minus the original arrival, for tickets that arrived in the window and were served. It is not the wait for a human reply (that is first response), tickets never served (abandoned, or still waiting) are outside it, and a transfer restarts the wait only in the per-queue legs, not in this figure." },
  sla: { name: "SLA compliance", rule: "D-02", text: "Eligible tickets within policy divided by eligible tickets. Open overdue tickets (still open and older than the resolution target at the window end) are counted and shown separately, never dropped and never mixed into the compliance ratio." },
  backlog: { name: "Backlog", rule: "D-05", text: "Tickets that have arrived and are not resolved or abandoned at the cutoff; a ticket in service is still unresolved." },
  occupancy: { name: "Occupancy and staffed time", rule: "D-03, D-05", text: "Occupancy is active handling divided by staffed available time, null when staffed time is 0. Staffed time is shift length minus break, with the break deducted only when the window covers the whole shift." },
  csat: { name: "CSAT and abandonment", rule: "D-03", text: "CSAT is the share of valid responses scoring 4 or 5 of 5, with the invitation and response rates beside it. Abandonment counts only channels that can abandon (chat and phone)." },
  window: { name: "Window", rule: "D-05, D-09", text: "Half-open [from, to). An arrival counts on its created_at, a completion on its final resolution. The full window is the snapshot's declared 84 days; training is weeks 1-8 and the holdout weeks 9-12. A backlog cutoff is an instant, not a window edge: events AT the cutoff count, so a cutoff equal to the window end counts events the half-open window itself excludes." },
} as const;


/** R4-13: the +20 % holdout is a chosen realisation, not a measurement. Renders nothing for a dataset without the record. */
export function RealisationNote({ r }: { r: ArrivalRealisation | undefined }) {
  if (!r || r.attempt_index === null) return null;
  return (
    <span><strong>Chosen realisation; noise sd ≈ {r.noise_sd_points.toFixed(0)} pts.</strong> The holdout's +{r.designed_uplift_percent.toFixed(0)} % is attempt {r.attempt_index} of a fixed series, kept because it landed within {r.tolerance_points} points of +{r.designed_uplift_percent.toFixed(0)} % (+{(r.chosen_uplift_percent ?? 0).toFixed(1)} %); attempts 0 to {r.attempt_index - 1} gave {r.discarded_uplift_percent.map((x) => `+${x.toFixed(1)} %`).join(", ")}. Poisson noise alone moves the ratio by about {r.noise_sd_points.toFixed(0)} points, so the size of the change is designed, not found.</span>
  );
}
