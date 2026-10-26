// Mirrors domain/revenue_atlas/pipeline.py: ingest -> facts -> allocation -> returns -> metrics.
// All lookups use index maps (customers, orders, lines, shipments, rates, costs); no nested scans.
import { allocateDiscounts, allocateFreight } from "./allocation";
import { ELIGIBLE_ORDER_STATUSES, UNASSIGNED_REGION } from "./contract";
import { indexCosts, resolveCostVersion } from "./costing";
import * as D from "./decimal";
import { DomainError, SHIPMENT_LINE_UNKNOWN, cmpStr } from "./errors";
import { indexRates, rateFor } from "./fx";
import { type IngestResult, utcDate, validateBatch } from "./ingest";
import { NO_WINDOW, type Window, computeMetrics, inWindow } from "./metrics";
import { recoverableCost, validateReturn } from "./returns";
import type {
  Customer, Metrics, PipelineInputs, RejectedRecord, Return, ReturnEvent, Shipment, ShipmentLine, ShipmentLineFact,
} from "./types";

export interface PipelineResult {
  ingest: IngestResult;
  facts: ShipmentLineFact[];
  freightByLine: Map<string, D.Dec>;
  discountByLine: Map<string, D.Dec>;
  quarantined: RejectedRecord[];
  metrics: Metrics;
  /** Freight left on the explicit unallocated row (all shipments); counts in contribution. */
  unallocatedFreight: D.Dec;
  /** Same, only for shipments inside the window (what `metrics` used). */
  unallocatedFreightInWindow: D.Dec;
  /** Shipment lines excluded by order status (cancelled etc.), not quarantined. */
  excluded: string[];
  /** Accepted return credits, for credit_date windows (D-01a). */
  returns: ReturnEvent[];
}

/** Customer version with the greatest effective_from <= UTC shipped date, else UNASSIGNED (D-06). */
export function regionFor(versions: readonly Customer[] | undefined, shippedAt: number): string {
  if (!versions) return UNASSIGNED_REGION;
  const day = utcDate(shippedAt);
  let best: Customer | null = null;
  for (const c of versions) if (c.effective_from <= day && (best === null || c.effective_from > best.effective_from)) best = c;
  return best ? best.region_id : UNASSIGNED_REGION;
}

function groupBy<T>(items: readonly T[], key: (t: T) => string): Map<string, T[]> {
  const m = new Map<string, T[]>();
  for (const it of items) {
    const k = key(it);
    const g = m.get(k);
    if (g) g.push(it);
    else m.set(k, [it]);
  }
  return m;
}

export function runPipeline(inputs: PipelineInputs, includeReturns: boolean, window: Window = NO_WINDOW): PipelineResult {
  const ing = validateBatch(inputs);
  const acc = ing.accepted;
  const orders = new Map(acc.orders.map((o) => [o.order_id, o]));
  const lines = new Map(acc.order_lines.map((x) => [x.line_id, x]));
  const shipments = new Map(acc.shipments.map((s) => [s.shipment_id, s]));
  const rates = indexRates(acc.exchange_rates);
  const costs = indexCosts(acc.cost_versions);
  const customersById = groupBy(acc.customers, (c) => c.customer_id);
  const quarantined: RejectedRecord[] = [];
  const excluded: string[] = [];

  const quarantine = (entity: "shipment_lines" | "returns", id: string, err: DomainError): void => {
    quarantined.push({ entity, id, reason_code: err.code, raw_row: (ing.raw[entity].get(id) ?? {}) as Record<string, unknown> });
    ing.counts[entity].quarantined += 1;
  };

  // Facts without allocation (D-01, D-02, D-03).
  const base = new Map<string, ShipmentLineFact>();
  const keptSls: ShipmentLine[] = [];
  const nativeGross = new Map<string, D.Dec>();
  const shipRate = new Map<string, D.Dec>();
  for (const sl of acc.shipment_lines) {
    const ln = lines.get(sl.line_id)!;
    const shp = shipments.get(sl.shipment_id)!;
    const order = orders.get(ln.order_id)!;
    if (!ELIGIBLE_ORDER_STATUSES.has(order.status)) {
      excluded.push(sl.shipment_line_id);
      continue;
    }
    const day = utcDate(shp.shipped_at);
    let rate: D.Dec;
    let srate: D.Dec;
    let cv;
    try {
      rate = rateFor(order.currency, day, rates);
      srate = rateFor(shp.currency, day, rates);
      cv = resolveCostVersion(ln.product_id, shp.shipped_at, costs);
    } catch (err) {
      if (err instanceof DomainError) {
        quarantine("shipment_lines", sl.shipment_line_id, err);
        continue;
      }
      throw err;
    }
    const gross = D.mul(D.fromInt(sl.shipped_quantity), ln.unit_price);
    nativeGross.set(sl.shipment_line_id, gross);
    shipRate.set(sl.shipment_id, srate);
    base.set(sl.shipment_line_id, {
      shipment_line_id: sl.shipment_line_id, shipment_id: shp.shipment_id, order_id: order.order_id,
      line_id: ln.line_id, customer_id: order.customer_id, product_id: ln.product_id,
      region_id: regionFor(customersById.get(order.customer_id), shp.shipped_at),
      shipped_at: shp.shipped_at, shipped_date: day, currency: order.currency, fx_rate: rate,
      shipped_quantity: sl.shipped_quantity, unit_price: D.mul(ln.unit_price, rate),
      gross_sales: D.mul(gross, rate), allocated_discount: D.ZERO, cost_version_id: cv.cost_version_id,
      unit_cost: cv.unit_cost, cogs: D.mul(D.fromInt(sl.shipped_quantity), cv.unit_cost), freight: D.ZERO,
      returned_quantity: 0, merchandise_credit: D.ZERO, recoverable_return_cost: D.ZERO,
    });
    keptSls.push(sl);
  }

  // Discounts (D-04): allocated natively, then converted.
  const discNative = allocateDiscounts(acc.order_lines, acc.discounts, keptSls);
  const discountByLine = new Map<string, D.Dec>();
  for (const k of [...discNative.keys()].sort(cmpStr)) discountByLine.set(k, D.mul(discNative.get(k)!, base.get(k)!.fx_rate));

  // Freight (D-04): per shipment over its included lines.
  const freightByLine = new Map<string, D.Dec>();
  const unallocByShp = new Map<string, D.Dec>();
  let declared = D.ZERO;
  const slsByShipment = groupBy(keptSls, (s) => s.shipment_id);
  for (const shpId of [...slsByShipment.keys()].sort(cmpStr)) {
    const shp: Shipment = shipments.get(shpId)!;
    const fa = allocateFreight(shp, slsByShipment.get(shpId)!, nativeGross);
    const r = shipRate.get(shpId)!;
    for (const [k, v] of fa.allocations) freightByLine.set(k, D.mul(v, r));
    if (fa.unallocated) unallocByShp.set(shpId, D.mul(fa.residual, r));
    if (inWindow(shp.shipped_at, window)) declared = D.add(declared, D.mul(shp.shipping_cost, r));
  }
  const facts = new Map<string, ShipmentLineFact>();
  for (const [k, f] of base) {
    facts.set(k, { ...f, allocated_discount: discountByLine.get(k) ?? D.ZERO, freight: freightByLine.get(k) ?? D.ZERO });
  }

  // Returns (D-06 C03), recognised at the credit-date rate (D-02).
  const events: ReturnEvent[] = [];
  if (includeReturns) {
    const prior = new Map<string, Return[]>();
    const slById = new Map<string, ShipmentLine>(acc.shipment_lines.map((s) => [s.shipment_line_id, s]));
    const ordered = [...acc.returns].sort((a, b) => cmpStr(a.credit_date, b.credit_date) || cmpStr(a.return_id, b.return_id));
    for (const ret of ordered) {
      const fact = facts.get(ret.shipment_line_id);
      let credit: D.Dec;
      try {
        if (!fact) throw new DomainError(SHIPMENT_LINE_UNKNOWN, "shipment line not in the population", { shipment_line_id: ret.shipment_line_id });
        validateReturn(slById.get(ret.shipment_line_id)!, prior.get(ret.shipment_line_id) ?? [], ret.returned_quantity, ret.credit_amount);
        credit = D.mul(ret.credit_amount, rateFor(fact.currency, ret.credit_date, rates));
      } catch (err) {
        if (err instanceof DomainError) {
          quarantine("returns", ret.return_id, err);
          continue;
        }
        throw err;
      }
      const list = prior.get(ret.shipment_line_id);
      if (list) list.push(ret);
      else prior.set(ret.shipment_line_id, [ret]);
      const rec = recoverableCost(fact!, ret.returned_quantity);
      events.push({
        return_id: ret.return_id, shipment_line_id: ret.shipment_line_id, credit_date: ret.credit_date,
        returned_quantity: ret.returned_quantity, merchandise_credit: credit, recoverable_return_cost: rec,
      });
      facts.set(fact!.shipment_line_id, {
        ...fact!,
        returned_quantity: fact!.returned_quantity + ret.returned_quantity,
        merchandise_credit: D.add(fact!.merchandise_credit, credit),
        recoverable_return_cost: D.add(fact!.recoverable_return_cost, rec),
      });
    }
  }

  const factList = [...facts.keys()].sort(cmpStr).map((k) => facts.get(k)!);
  const inWinShipments = new Set(factList.filter((f) => inWindow(f.shipped_at, window)).map((f) => f.shipment_id));
  let unallocW = D.ZERO;
  for (const [k, v] of unallocByShp) if (inWinShipments.has(k)) unallocW = D.add(unallocW, v);
  const metrics = computeMetrics(factList, window, { unallocatedFreight: unallocW, declaredShippingCost: declared, returns: events });
  quarantined.sort((a, b) => cmpStr(a.entity, b.entity) || cmpStr(a.id, b.id));
  return {
    ingest: ing, facts: factList, freightByLine, discountByLine, quarantined, metrics,
    unallocatedFreight: D.sum(unallocByShp.values()), unallocatedFreightInWindow: unallocW,
    excluded: excluded.sort(cmpStr), returns: events,
  };
}
