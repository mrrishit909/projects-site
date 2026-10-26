// Three-way match (match.py): cumulative consumption in (invoice_date, imported_at, invoice_id) order, rounding tolerances,
// exceptions. A line matches when quantity variance <= 0 and |price variance| <= the price tolerance. Only a MATCHED invoice
// consumes received quantity. Matching never confers approval (D-03).
import { invoiceAmounts, lineMoney } from "./amounts";
import { RULE_VERSION } from "./contract";
import { absB, fmt, maxB, money10, rescale, s2, s4q, sumB } from "./num";
import type { Invoice, PoLine, Population } from "./types";

export interface LineResult {
  invoice_line_id: string; invoice_id: string; po_line_id: string; status: "matched" | "exception"; reason_code: string | null;
  available: bigint | null; quantity_variance: bigint | null; price_variance: bigint | null; invoice_price: bigint; explanation: string;
  // beside the contract, for the invoice view: what the line was matched against
  quantity: bigint; ordered: bigint | null; net_received: bigint | null; previously_invoiced: bigint | null; po_price: bigint | null;
}
export interface InvoiceResult {
  invoice_id: string; subtotal: bigint; tax: bigint; total: bigint; rounding_difference: bigint; reasons: string[]; matched: boolean;
  line_rounding: [string, bigint][];
}
export interface MatchRun {
  cutoff: number; po_lines: Map<string, PoLine>; net: Map<string, bigint>; consumed: Map<string, bigint>; lines: LineResult[]; invoices: Map<string, InvoiceResult>;
}
const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
export const bookOrder = (a: Invoice, b: Invoice): number => cmp(a.invoice_date, b.invoice_date) || a.imported_at - b.imported_at || cmp(a.invoice_id, b.invoice_id);

/** The canonical row of expected.json["documents"]["match_results"]. */
export function asRow(r: LineResult): Record<string, unknown> {
  return {
    invoice_line_id: r.invoice_line_id, invoice_id: r.invoice_id, rule_version: RULE_VERSION, status: r.status, reason_code: r.reason_code,
    available_quantity: r.available === null ? null : s4q(r.available),
    quantity_variance: r.quantity_variance === null ? null : s4q(r.quantity_variance),
    price_variance: r.price_variance === null ? null : fmt(rescale(r.price_variance, 6, 4), 4),
  };
}

export function matchRun(pop: Population, candidates: readonly Invoice[], cutoff: number): MatchRun {
  const tolPrice = pop.tolerances.price_per_unit, tolLine = pop.tolerances.rounding_per_line, tolInv = pop.tolerances.rounding_per_invoice;
  const poCur = new Map(pop.purchase_orders.map((p) => [p.po_id, p.currency]));
  const ordered = new Set(pop.purchase_orders.filter((p) => p.ordered_at <= cutoff).map((p) => p.po_id));
  const pol = new Map(pop.po_lines.filter((l) => ordered.has(l.po_id)).map((l) => [l.po_line_id, l]));
  const net = new Map<string, bigint>([...pol.keys()].map((k) => [k, 0n]));
  for (const r of pop.receipts) if (!r.reversed && r.received_at <= cutoff && net.has(r.po_line_id)) net.set(r.po_line_id, net.get(r.po_line_id)! + r.received_quantity);
  const consumed = new Map<string, bigint>([...pol.keys()].map((k) => [k, 0n]));
  const results: LineResult[] = [];
  const invs = new Map<string, InvoiceResult>();
  for (const inv of [...candidates].sort(bookOrder)) {
    const [sub, tax, total] = invoiceAmounts(inv);
    const reasons = new Set<string>();
    const local = new Map<string, bigint>();
    const rows: LineResult[] = [];
    const lineRound: [string, bigint][] = [];
    for (const l of [...inv.lines].sort((a, b) => cmp(a.invoice_line_id, b.invoice_line_id))) {
      const p = pol.get(l.po_line_id);
      const row: LineResult = {
        invoice_line_id: l.invoice_line_id, invoice_id: inv.invoice_id, po_line_id: l.po_line_id, status: "matched", reason_code: null, available: null,
        quantity_variance: null, price_variance: null, invoice_price: l.unit_price, explanation: "", quantity: l.quantity, ordered: null, net_received: null, previously_invoiced: null, po_price: null,
      };
      if (!p) {
        row.status = "exception"; row.reason_code = "NO_PO_LINE";
        row.explanation = `no purchase-order line ${l.po_line_id} exists at the cutoff`;
      } else if (poCur.get(p.po_id) !== inv.currency) {
        row.status = "exception"; row.reason_code = "CURRENCY_MISMATCH";
        row.explanation = `invoice currency ${inv.currency} differs from the PO currency ${poCur.get(p.po_id)} and no dated conversion rate exists`;
      } else {
        const prev = consumed.get(p.po_line_id)! + (local.get(p.po_line_id) ?? 0n);
        const avail = net.get(p.po_line_id)! - prev;
        const qv = l.quantity - avail, pv = l.unit_price - p.unit_price;
        Object.assign(row, { available: avail, quantity_variance: qv, price_variance: pv, ordered: p.quantity, net_received: net.get(p.po_line_id)!, previously_invoiced: prev, po_price: p.unit_price });
        if (qv > 0n) {
          row.status = "exception"; row.reason_code = "QUANTITY_BLOCKED";
          row.explanation = `invoiced ${s4q(l.quantity)} exceeds the ${s4q(avail)} available to invoice`;
        } else if (absB(pv) > tolPrice) {
          row.status = "exception"; row.reason_code = "PRICE_VARIANCE";
          row.explanation = `invoice price ${fmt(l.unit_price, 6)} differs from the PO price ${fmt(p.unit_price, 6)} by ${fmt(rescale(pv, 6, 4), 4)} (tolerance ${pop.tolerances.raw.price_per_unit})`;
        } else row.explanation = `${s4q(l.quantity)} of ${s4q(avail)} available, price within tolerance`;
        local.set(p.po_line_id, (local.get(p.po_line_id) ?? 0n) + l.quantity);
      }
      if (row.reason_code) reasons.add(row.reason_code);
      if (l.line_amount !== null) {
        const ldiff = absB(l.line_amount - lineMoney(l));
        if (ldiff > 0n) lineRound.push([l.invoice_line_id, ldiff]);
        if (ldiff * 10_000n > tolLine) reasons.add("ROUNDING_EXCEPTION");
      }
      rows.push(row);
    }
    const diff = absB(inv.declared_total - total);
    if (diff * 10_000n > tolInv) reasons.add("ROUNDING_EXCEPTION");
    const ok = reasons.size === 0;
    if (ok) for (const [k, v] of local) consumed.set(k, consumed.get(k)! + v);
    results.push(...rows);
    invs.set(inv.invoice_id, { invoice_id: inv.invoice_id, subtotal: sub, tax, total, rounding_difference: diff, reasons: [...reasons].sort(cmp), matched: ok, line_rounding: lineRound });
  }
  return { cutoff, po_lines: pol, net, consumed, lines: results, invoices: invs };
}

/** D-P5-14 open quantities at the run's cutoff over all PO lines. */
export function quantities(run: MatchRun): Record<string, string> {
  const keys = [...run.po_lines.keys()];
  const pos = (k: string): bigint => maxB(run.net.get(k)! - run.consumed.get(k)!, 0n);
  const rniVal = sumB(keys.map((k) => pos(k) * run.po_lines.get(k)!.unit_price));
  const blocked = run.lines.filter((r) => r.reason_code === "QUANTITY_BLOCKED");
  return {
    ordered_quantity: s4q(sumB(keys.map((k) => run.po_lines.get(k)!.quantity))),
    net_received_quantity: s4q(sumB(keys.map((k) => run.net.get(k)!))),
    accepted_invoiced_quantity: s4q(sumB(keys.map((k) => run.consumed.get(k)!))),
    open_to_receive_quantity: s4q(sumB(keys.map((k) => maxB(run.po_lines.get(k)!.quantity - run.net.get(k)!, 0n)))),
    open_to_invoice_quantity: s4q(sumB(keys.map((k) => maxB(run.po_lines.get(k)!.quantity - run.consumed.get(k)!, 0n)))),
    received_not_invoiced_quantity: s4q(sumB(keys.map(pos))),
    received_not_invoiced_value: s2(money10(rniVal)),
    invoiced_not_received_quantity: s4q(sumB(blocked.map((r) => r.quantity_variance!))),
    invoiced_not_received_value: s2(money10(sumB(blocked.map((r) => r.quantity_variance! * r.invoice_price)))),
  };
}
