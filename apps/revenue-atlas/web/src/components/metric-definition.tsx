// "i" disclosure listing formula, grain, window and exclusions for a contract metric (docs/contracts.md D-05, D-01).
import "../styles/screens.css";

interface Def { name: string; formula: string; zero: string }
const DEFS: Record<string, Def> = {
  gross_sales: { name: "Gross sales", formula: "Σ shipped_quantity × unit_price, converted to USD at the shipment-date rate (D-02)", zero: "0.00" },
  allocated_discounts: { name: "Allocated discounts", formula: "Order-line discounts allocated to shipment lines by shipped ÷ ordered quantity, cents by largest remainder (D-04)", zero: "0.00" },
  merchandise_credits: { name: "Merchandise credits", formula: "Σ credit_amount of accepted returns, at the credit-date rate; recognised on credit date (D-01)", zero: "0.00" },
  net_merchandise_sales: { name: "Net merchandise sales", formula: "gross − allocated discounts − merchandise credits", zero: "0.00" },
  cogs: { name: "COGS", formula: "Σ shipped_quantity × historical unit cost − recoverable return cost; cost is the version valid at shipped_at (D-03)", zero: "0.00" },
  gross_profit: { name: "Gross profit", formula: "net merchandise sales − COGS", zero: "0.00" },
  shipping_revenue: { name: "Shipping revenue", formula: "None is recorded in this dataset; the contract keeps the term", zero: "0.00" },
  shipping_cost: { name: "Shipping cost", formula: "Shipment shipping_cost allocated over its lines by gross-sales weight, cents by largest remainder (D-04)", zero: "0.00" },
  contribution_margin: { name: "Contribution margin", formula: "gross profit + shipping revenue − shipping cost − other variable costs", zero: "0.00 (may be negative)" },
  contribution_margin_rate: { name: "Contribution margin rate", formula: "contribution ÷ (net merchandise sales + shipping revenue), from aggregated sums, never averaged over rows", zero: "n/a when the denominator is 0" },
};

export function MetricDefinition({ metric }: { metric: keyof typeof DEFS | string }) {
  const d = DEFS[metric];
  if (!d) return null;
  return (
    <details className="def">
      <summary aria-label={`Definition: ${d.name}`} title={`Definition: ${d.name}`}>i</summary>
      <div className="def__body">
        <p className="def__title">{d.name}</p>
        <dl>
          <dt>Formula</dt><dd>{d.formula}</dd>
          <dt>Grain</dt><dd>Shipment line (D-01)</dd>
          <dt>Window</dt><dd>Shipment date, UTC, half-open [from, to); credits on credit date</dd>
          <dt>Exclusions</dt><dd>Cancelled orders and quarantined lines (FX rate missing, cost version missing or ambiguous)</dd>
          <dt>Empty</dt><dd>{d.zero}</dd>
        </dl>
      </div>
    </details>
  );
}
