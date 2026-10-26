// Supplier reliability and open lines (D-04). Computed only from receipts dated at or before the cutoff; a partial
// receipt never completes its line.
import { d6, ratio } from "./money";
import { arrivalDay } from "./replenishment";
import { dayOf } from "./time";
import type { Closure, PoLine, PurchaseOrder, Receipt, Supplier } from "./types";

export function receivedQuantity(lineId: string, receipts: readonly Receipt[], cutoff: number | null = null): number {
  let q = 0;
  for (const r of receipts) if (r.po_line_id === lineId && (cutoff === null || r.received_at <= cutoff)) q += r.received_quantity;
  return q;
}
/** ordered - received (receipts at or before the cutoff), never below 0. > 0 means the line is open. */
export const openQuantity = (line: PoLine, receipts: readonly Receipt[], cutoff: number | null = null): number =>
  Math.max(line.ordered_quantity - receivedQuantity(line.po_line_id, receipts, cutoff), 0);
export const lineStatus = (line: PoLine, receipts: readonly Receipt[], cutoff: number | null = null): "open" | "complete" =>
  receivedQuantity(line.po_line_id, receipts, cutoff) < line.ordered_quantity ? "open" : "complete"; // partial stays open

/** The deadline promised at order time: the quoted lead days counted on the supplier calendar (a day number). */
export const promisedDay = (order: PurchaseOrder, supplier: Supplier, closures: readonly Closure[]): number =>
  arrivalDay(dayOf(order.ordered_at), supplier.quoted_lead_days, closures, supplier.calendar_id);

export interface OnTime {
  eligible_receipts: number; on_time_receipts: number; late_receipts: string[]; on_time_rate: string | null;
  partially_received_open_lines: string[]; open_lines: string[];
}
const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** Receipts within the promised deadline / eligible receipts, from receipts dated <= cutoff (no future leakage). */
export function onTimeRate(orders: readonly PurchaseOrder[], lines: readonly PoLine[], receipts: readonly Receipt[],
  suppliers: readonly Supplier[], closures: readonly Closure[], cutoff: number, supplierId: string | null = null): OnTime {
  const sup = new Map(suppliers.map((s) => [s.supplier_id, s]));
  const ord = new Map(orders.map((o) => [o.purchase_order_id, o]));
  const line = new Map(lines.map((l) => [l.po_line_id, l]));
  let eligible = 0, onTime = 0;
  const late: string[] = [];
  for (const r of [...receipts].sort((a, b) => a.received_at - b.received_at || cmp(a.receipt_id, b.receipt_id))) {
    const l = line.get(r.po_line_id);
    if (r.received_at > cutoff || !l) continue;
    const o = ord.get(l.purchase_order_id);
    const s = o ? sup.get(o.supplier_id) : undefined;
    if (!o || !s || (supplierId !== null && s.supplier_id !== supplierId)) continue;
    eligible += 1;
    if (dayOf(r.received_at) <= promisedDay(o, s, closures)) onTime += 1; else late.push(r.receipt_id);
  }
  const open = lines.filter((l) => {
    const o = ord.get(l.purchase_order_id);
    return o !== undefined && (supplierId === null || o.supplier_id === supplierId) && o.ordered_at <= cutoff && lineStatus(l, receipts, cutoff) === "open";
  }).map((l) => l.po_line_id).sort(cmp);
  return {
    eligible_receipts: eligible, on_time_receipts: onTime, late_receipts: late, on_time_rate: d6(ratio(onTime, eligible)),
    partially_received_open_lines: open.filter((l) => receivedQuantity(l, receipts, cutoff) > 0), open_lines: open,
  };
}
