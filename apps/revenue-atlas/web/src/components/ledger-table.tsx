// Sortable, keyboard-operable evidence ledger: one row per shipment line, sticky header, 50 rows a page.
// Sorting is deterministic: ties on the sort key are broken by shipment_line_id ascending.
import { useEffect, useMemo, useState } from "react";
import "../styles/screens.css";
import * as D from "../domain/decimal";
import { cmpStr } from "../domain/errors";
import type { ShipmentLineFact } from "../domain/types";
import type { Population } from "../state/filters";
import { fmtDec, fmtInt } from "./format";

type Lookups = Extract<Population, { status: "ready" }>["lookups"];
export const PAGE_SIZE = 50;

interface Col {
  id: string;
  label: string;
  num?: boolean;
  text: (f: ShipmentLineFact, l: Lookups) => string;
  key: (f: ShipmentLineFact, l: Lookups) => string | number | D.Dec;
  trunc?: boolean;
}
const dec = (x: D.Dec): string => fmtDec(x, 2);
export const COLUMNS: Col[] = [
  { id: "shipped_at", label: "Shipped at (UTC)", text: (f) => new Date(f.shipped_at).toISOString().slice(0, 16).replace("T", " "), key: (f) => f.shipped_at },
  { id: "order", label: "Order", text: (f) => f.order_id, key: (f) => f.order_id },
  { id: "line", label: "Line", text: (f) => f.shipment_line_id, key: (f) => f.shipment_line_id },
  { id: "customer", label: "Customer", text: (f, l) => l.customerName(f.customer_id), key: (f, l) => l.customerName(f.customer_id).toLowerCase(), trunc: true },
  { id: "product", label: "Product", text: (f, l) => l.sku(f.product_id), key: (f, l) => l.sku(f.product_id), trunc: true },
  { id: "region", label: "Region", text: (f) => f.region_id || "UNASSIGNED", key: (f) => f.region_id || "UNASSIGNED" },
  { id: "qty", label: "Qty", num: true, text: (f) => String(f.shipped_quantity), key: (f) => f.shipped_quantity },
  { id: "unit_price", label: "Unit price", num: true, text: (f) => dec(f.unit_price), key: (f) => f.unit_price },
  { id: "gross", label: "Gross", num: true, text: (f) => dec(f.gross_sales), key: (f) => f.gross_sales },
  { id: "discount", label: "Discount", num: true, text: (f) => dec(f.allocated_discount), key: (f) => f.allocated_discount },
  { id: "cost_version", label: "Cost version", text: (f) => f.cost_version_id, key: (f) => f.cost_version_id },
  { id: "unit_cost", label: "Unit cost", num: true, text: (f) => dec(f.unit_cost), key: (f) => f.unit_cost },
  { id: "cogs", label: "COGS", num: true, text: (f) => dec(f.cogs), key: (f) => f.cogs },
  { id: "freight", label: "Freight", num: true, text: (f) => dec(f.freight), key: (f) => f.freight },
  { id: "credit", label: "Credit", num: true, text: (f) => dec(f.merchandise_credit), key: (f) => f.merchandise_credit },
  { id: "fx", label: "FX rate", num: true, text: (f) => D.toString(f.fx_rate), key: (f) => f.fx_rate },
  { id: "currency", label: "Currency", text: (f) => f.currency, key: (f) => f.currency },
];

/** Which ledger columns each bridge step is made of (drill highlight). */
export const STEP_COLUMNS: Record<string, string[]> = {
  gross: ["gross"],
  discounts: ["discount"],
  credits: ["credit"],
  net: ["gross", "discount", "credit"],
  cogs: ["cogs", "unit_cost"],
  gross_profit: ["gross", "discount", "credit", "cogs"],
  shipping_revenue: [],
  shipping_cost: ["freight"],
  contribution: ["gross", "discount", "credit", "cogs", "freight"],
};

export interface LedgerTotals {
  qty: number; gross: D.Dec; discount: D.Dec; credit: D.Dec; cogs: D.Dec; recoverable: D.Dec; freight: D.Dec;
  net: D.Dec; cogsNet: D.Dec; grossProfit: D.Dec; contribution: D.Dec;
}
/** Sums straight from the fact columns, independent of computeMetrics: the ledger-side half of the reconciliation. */
export function ledgerTotals(facts: readonly ShipmentLineFact[], extraFreight: D.Dec = D.ZERO): LedgerTotals {
  let qty = 0;
  let gross = D.ZERO, discount = D.ZERO, credit = D.ZERO, cogs = D.ZERO, recoverable = D.ZERO, freight = extraFreight;
  for (const f of facts) {
    qty += f.shipped_quantity;
    gross = D.add(gross, f.gross_sales);
    discount = D.add(discount, f.allocated_discount);
    credit = D.add(credit, f.merchandise_credit);
    cogs = D.add(cogs, f.cogs);
    recoverable = D.add(recoverable, f.recoverable_return_cost);
    freight = D.add(freight, f.freight);
  }
  const net = D.sub(D.sub(gross, discount), credit);
  const cogsNet = D.sub(cogs, recoverable);
  const grossProfit = D.sub(net, cogsNet);
  return { qty, gross, discount, credit, cogs, recoverable, freight, net, cogsNet, grossProfit, contribution: D.sub(grossProfit, freight) };
}

function compare(a: string | number | D.Dec, b: string | number | D.Dec): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "string" && typeof b === "string") return cmpStr(a, b);
  return D.cmp(a as D.Dec, b as D.Dec);
}

export function LedgerTable({ facts, lookups, highlight, extraFreight }: { facts: ShipmentLineFact[]; lookups: Lookups; highlight: string[]; extraFreight?: D.Dec }) {
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 }>({ col: "shipped_at", dir: 1 });
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [facts]);
  const sorted = useMemo(() => {
    const col = COLUMNS.find((c) => c.id === sort.col) ?? COLUMNS[0]!;
    // Keys are computed once per row, then sorted; the tie-break is shipment_line_id ascending in both directions.
    const keyed = facts.map((f) => [f, col.key(f, lookups)] as const);
    keyed.sort((x, y) => compare(x[1], y[1]) * sort.dir || cmpStr(x[0].shipment_line_id, y[0].shipment_line_id));
    return keyed.map((k) => k[0]);
  }, [facts, lookups, sort]);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const cur = Math.min(page, pages - 1);
  const rows = sorted.slice(cur * PAGE_SIZE, (cur + 1) * PAGE_SIZE);
  const t = useMemo(() => ledgerTotals(facts, extraFreight), [facts, extraFreight]);
  const hl = new Set(highlight);
  const totalCell: Record<string, string> = {
    qty: fmtInt(t.qty), gross: fmtDec(t.gross), discount: fmtDec(t.discount), cogs: fmtDec(t.cogs), freight: fmtDec(t.freight), credit: fmtDec(t.credit),
  };
  const first = sorted.length === 0 ? 0 : cur * PAGE_SIZE + 1;
  return (
    <div>
      <div className="ledger-wrap" tabIndex={0} role="region" aria-label="Transaction ledger, scrollable" data-testid="ledger-scroll">
        <table className="ledger" data-testid="ledger">
          <caption className="sr-only">Shipment lines of the filtered population, USD, synthetic data. Sorted by {sort.col} {sort.dir === 1 ? "ascending" : "descending"}, ties by line id.</caption>
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.id} scope="col" className={`${c.num ? "num" : ""}${hl.has(c.id) ? " hl" : ""}`} data-col={c.id} data-highlight={hl.has(c.id) ? "true" : undefined}
                  aria-sort={sort.col === c.id ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                  <button type="button" onClick={() => setSort((s) => (s.col === c.id ? { col: c.id, dir: s.dir === 1 ? -1 : 1 } : { col: c.id, dir: 1 }))}>
                    {c.label}<span aria-hidden="true">{sort.col === c.id ? (sort.dir === 1 ? " ▲" : " ▼") : ""}</span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.shipment_line_id}>
                {COLUMNS.map((c) => {
                  const v = c.text(f, lookups);
                  const neg = c.num && v.startsWith("-");
                  return (
                    <td key={c.id} className={`${c.num ? "num" : ""}${hl.has(c.id) ? " hl" : ""}${neg ? " neg" : ""}`} data-col={c.id}>
                      {c.trunc ? <span className="trunc" title={v}>{v}</span> : v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr data-testid="ledger-totals-row">
              {COLUMNS.map((c, i) => (
                <td key={c.id} className={`${c.num ? "num" : ""}${hl.has(c.id) ? " hl" : ""}`} data-col={c.id}>
                  {i === 0 ? `Totals, ${fmtInt(facts.length)} lines` : totalCell[c.id] ?? ""}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="pager">
        <span data-testid="page-status" aria-live="polite">Rows {fmtInt(first)}–{fmtInt(Math.min(sorted.length, (cur + 1) * PAGE_SIZE))} of {fmtInt(sorted.length)} · page {cur + 1} of {pages}</span>
        <button type="button" className="btn" onClick={() => setPage(cur - 1)} disabled={cur === 0}>Previous page</button>
        <button type="button" className="btn" onClick={() => setPage(cur + 1)} disabled={cur >= pages - 1}>Next page</button>
      </div>
    </div>
  );
}
