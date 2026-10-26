// Mirrors domain/revenue_atlas/allocation.py: discount and freight allocation (D-04).
import * as D from "./decimal";
import { cmpStr } from "./errors";
import { largestRemainder } from "./money";
import type { Discount, OrderLine, Shipment, ShipmentLine } from "./types";

export interface FreightAllocation {
  allocations: Map<string, D.Dec>;
  residual: D.Dec;
  unallocated: boolean;
}

const ZERO2: D.Dec = { u: 0n, s: 2 };

/**
 * Discount * shipped / ordered per shipment line, exact cents (D-04). Each order line's discounts
 * are summed, then split over its shipment lines by shipped quantity with largest remainder
 * (tie-break: lowest shipment_line_id). Lines are indexed, never scanned per order line.
 */
export function allocateDiscounts(
  orderLines: readonly OrderLine[], discounts: readonly Discount[], shipmentLines: readonly ShipmentLine[],
): Map<string, D.Dec> {
  const slsByLine = new Map<string, ShipmentLine[]>();
  for (const s of shipmentLines) {
    const l = slsByLine.get(s.line_id);
    if (l) l.push(s);
    else slsByLine.set(s.line_id, [s]);
  }
  const discByLine = new Map<string, D.Dec>();
  for (const d of discounts) discByLine.set(d.line_id, D.add(discByLine.get(d.line_id) ?? D.ZERO, d.discount_amount));

  const out = new Map<string, D.Dec>();
  for (const ol of [...orderLines].sort((a, b) => cmpStr(a.line_id, b.line_id))) {
    const group = slsByLine.get(ol.line_id);
    if (!group) continue;
    const sls = [...group].sort((a, b) => cmpStr(a.shipment_line_id, b.shipment_line_id));
    const disc = discByLine.get(ol.line_id) ?? D.ZERO;
    const shipped = sls.reduce((a, s) => a + s.shipped_quantity, 0);
    if (shipped === 0 || D.isZero(disc)) {
      for (const s of sls) out.set(s.shipment_line_id, ZERO2);
      continue;
    }
    const total = D.divToScale(D.mul(disc, D.fromInt(shipped)), D.fromInt(ol.quantity), 2);
    for (const [k, v] of largestRemainder(total, sls.map((s) => [s.shipment_line_id, D.fromInt(s.shipped_quantity)] as const))) out.set(k, v);
  }
  return out;
}

/** Allocate shipping_cost by gross-sales weight, else shipped quantity, else leave it unallocated (D-04). */
export function allocateFreight(
  shipment: Shipment, shipmentLines: readonly ShipmentLine[], grossByLine: ReadonlyMap<string, D.Dec>,
): FreightAllocation {
  const cost = D.cents(shipment.shipping_cost);
  const lines = [...shipmentLines].sort((a, b) => cmpStr(a.shipment_line_id, b.shipment_line_id));
  let weights = lines.map((s) => [s.shipment_line_id, grossByLine.get(s.shipment_line_id) ?? D.ZERO] as const);
  if (D.isZero(D.sum(weights.map(([, w]) => w)))) weights = lines.map((s) => [s.shipment_line_id, D.fromInt(s.shipped_quantity)] as const);
  if (D.isZero(D.sum(weights.map(([, w]) => w)))) return { allocations: new Map(), residual: cost, unallocated: true };
  const alloc = largestRemainder(cost, weights);
  return { allocations: alloc, residual: D.sub(cost, D.sum(alloc.values())), unallocated: false };
}
