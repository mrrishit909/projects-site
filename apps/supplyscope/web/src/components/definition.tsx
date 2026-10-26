import type { ReactNode } from "react";

/** Metric definitions, collapsed by default, each citing the contract rule it implements. */
export const METRICS: readonly { name: string; rule: string; text: string }[] = [
  { name: "On hand", rule: "D-01", text: "The sum of posted movement quantities up to the as-of instant, per SKU and location; a negative reconstruction is flagged NEGATIVE_STOCK and valued at zero. Day order is receipts, then sales, then review." },
  { name: "Inventory position", rule: "D-01", text: "On hand + confirmed on order (open purchase order lines: ordered minus received) - backorders. Reserved units are not subtracted." },
  { name: "Reorder, raw, MOQ, pack", rule: "D-02, D-06", text: "When position < reorder point: raw = target - position, then max(raw, MOQ), then rounded up to whole packs. Otherwise 0 at every step. A draft, never a purchase order." },
  { name: "Fill rate", rule: "D-04, D-06", text: "Units fulfilled immediately / requested units, where requested = fulfilled + unmet demand opened in the window. Aggregated numerators and denominators, never an average of rates." },
  { name: "Stockout days", rule: "D-04, D-06", text: "Days on which unmet demand opened / observed days. A date with a backorder or a lost sale counts once." },
  { name: "Working capital", rule: "D-05", text: "The sum of on hand x unit cost, at the cost in force on the valuation date." },
  { name: "MAE and WAPE", rule: "D-03", text: "MAE = mean |actual - forecast|. WAPE = sum |error| / sum actual, null when the actuals sum to 0 (an intermittent SKU's zero-demand folds)." },
  { name: "Beats baseline", rule: "D-03", text: "The model counts only when its MAE is lower than seasonal-naive's on the same rolling-origin folds; not judged when the baseline cannot be scored." },
];

export function Definition({ title = "Definitions", only, children }: { title?: string; only?: readonly string[]; children?: ReactNode }) {
  const rows = only ? METRICS.filter((m) => only.includes(m.name)) : METRICS;
  return (
    <details className="definition">
      <summary>{title}</summary>
      {children ?? (
        <dl className="definition__list">
          {rows.map((m) => <div key={m.name}><dt>{m.name} <span className="chip">{m.rule}</span></dt><dd>{m.text}</dd></div>)}
        </dl>
      )}
    </details>
  );
}
