// Mirrors domain/revenue_atlas/metrics.py: metric aggregation (D-01, D-05). Ratios come from sums.
import { UNALLOCATED_GROUP, UNASSIGNED_REGION } from "./contract";
import * as D from "./decimal";
import { DomainError, INVALID_WINDOW, cmpStr } from "./errors";
import type { Metrics, ReturnEvent, ShipmentLineFact } from "./types";

/** Half-open [from, to) on shipped_at, UTC epoch milliseconds; null is unbounded (D-01). */
export interface Window { from: number | null; to: number | null }
export const NO_WINDOW: Window = { from: null, to: null };

/** Convenience: epoch ms of a UTC calendar date "YYYY-MM-DD" (midnight UTC). */
export const utcMidnight = (date: string): number => Date.parse(`${date}T00:00:00Z`);

export function checkWindow(w: Window): void {
  if (w.from !== null && w.to !== null && w.from >= w.to) {
    throw new DomainError(INVALID_WINDOW, "window start must be before end", { from: w.from, to: w.to });
  }
}
export function inWindow(shippedAt: number, w: Window): boolean {
  return (w.from === null || shippedAt >= w.from) && (w.to === null || shippedAt < w.to);
}

/** Return credits are recognised on credit_date, read as 00:00 UTC of that date (D-01a). */
export const creditInWindow = (creditDate: string, w: Window): boolean => inWindow(utcMidnight(creditDate), w);

const m2 = (x: D.Dec): string => D.fixed(x, 2);
const ratio = (num: D.Dec, den: D.Dec): string | null => (D.isZero(den) ? null : D.fixed(D.divToScale(num, den, 6), 6));

export interface MetricOptions {
  /** Freight that could not be allocated to any line; still counts in shipping cost (D-04). */
  unallocatedFreight?: D.Dec;
  /** Sum of shipment shipping costs; makes allocation_residual a real check (else 0.00). */
  declaredShippingCost?: D.Dec | null;
  /**
   * D-01a: accepted return credits. Shipment lines are selected by shipped_at, credits by credit_date
   * (for lines present in `facts`). Omitted: the facts' own return columns are used, which is exact
   * only for an unwindowed call.
   */
  returns?: readonly ReturnEvent[];
}

export function computeMetrics(facts: readonly ShipmentLineFact[], window: Window = NO_WINDOW, opts: MetricOptions = {}): Metrics {
  checkWindow(window);
  const fs = facts.filter((f) => inWindow(f.shipped_at, window));
  const sum = (pick: (f: ShipmentLineFact) => D.Dec): D.Dec => {
    let acc = D.ZERO;
    for (const f of fs) acc = D.add(acc, pick(f));
    return acc;
  };
  const gross = sum((f) => f.gross_sales);
  const disc = sum((f) => f.allocated_discount);
  let credits = D.ZERO;
  let recov = D.ZERO;
  let returned = 0;
  if (opts.returns === undefined) {
    credits = sum((f) => f.merchandise_credit);
    recov = sum((f) => f.recoverable_return_cost);
    for (const f of fs) returned += f.returned_quantity;
  } else {
    const known = new Set<string>();
    for (const f of facts) known.add(f.shipment_line_id);
    for (const r of opts.returns) {
      if (!known.has(r.shipment_line_id) || !creditInWindow(r.credit_date, window)) continue;
      credits = D.add(credits, r.merchandise_credit);
      recov = D.add(recov, r.recoverable_return_cost);
      returned += r.returned_quantity;
    }
  }
  const cogs = D.sub(sum((f) => f.cogs), recov);
  const shipCost = D.add(sum((f) => f.freight), opts.unallocatedFreight ?? D.ZERO);
  const shipRev = D.ZERO;
  const other = D.ZERO;
  const net = D.sub(D.sub(gross, disc), credits);
  const gp = D.sub(net, cogs);
  const cm = D.sub(D.sub(D.add(gp, shipRev), shipCost), other);
  const eligRev = D.add(net, shipRev);
  let units = 0;
  const orders = new Set<string>();
  for (const f of fs) {
    units += f.shipped_quantity;
    orders.add(f.order_id);
  }
  const declared = opts.declaredShippingCost ?? null;
  const residual = declared === null ? D.ZERO : D.sub(declared, shipCost);
  return {
    gross_sales: m2(gross),
    allocated_discounts: m2(disc),
    merchandise_credits: m2(credits),
    net_merchandise_sales: m2(net),
    cogs: m2(cogs),
    recoverable_return_cost: m2(recov),
    gross_profit: m2(gp),
    shipping_revenue: m2(shipRev),
    shipping_cost: m2(shipCost),
    other_variable_costs: m2(other),
    contribution_margin: m2(cm),
    eligible_net_revenue: m2(eligRev),
    contribution_margin_rate: ratio(cm, eligRev),
    discount_rate: ratio(disc, gross),
    return_rate: ratio(D.fromInt(returned), D.fromInt(units)),
    average_order_value: orders.size === 0 ? null : m2(D.divToScale(net, D.fromInt(orders.size), 2)),
    allocation_residual: m2(residual),
    eligible_orders: orders.size,
    eligible_shipment_lines: fs.length,
    shipped_units: units,
    returned_units: returned,
  };
}

/** Region key; a missing region is the explicit UNASSIGNED row (D-06). */
export const regionKey = (f: ShipmentLineFact): string => f.region_id || UNASSIGNED_REGION;

/**
 * Metrics per group, ascending key order; empty/missing keys become UNASSIGNED (as in Python).
 * D-08 (R-03): freight no shipment line could carry (`unallocatedFreight`, already restricted to the window by
 * the caller) is emitted as an explicit UNALLOCATED group whose shipping cost is that freight and whose
 * contribution is minus it, for every grouping key, so the groups add up to the overall metrics. Nothing is
 * emitted when it is zero.
 */
export function groupMetrics(
  facts: readonly ShipmentLineFact[], keyFn: (f: ShipmentLineFact) => string | null | undefined, window: Window = NO_WINDOW,
  returns?: readonly ReturnEvent[], unallocatedFreight: D.Dec = D.ZERO,
): Map<string, Metrics> {
  checkWindow(window);
  const groups = new Map<string, ShipmentLineFact[]>();
  for (const f of facts) {
    const k = keyFn(f) || UNASSIGNED_REGION;
    const g = groups.get(k);
    if (g) g.push(f);
    else groups.set(k, [f]);
  }
  const computed = new Map<string, Metrics>();
  for (const [k, g] of groups) computed.set(k, computeMetrics(g, window, returns === undefined ? {} : { returns }));
  if (!D.isZero(unallocatedFreight)) computed.set(UNALLOCATED_GROUP, computeMetrics([], window, { unallocatedFreight }));
  const out = new Map<string, Metrics>();
  for (const k of [...computed.keys()].sort(cmpStr)) out.set(k, computed.get(k)!);
  return out;
}

const monthKey = (ms: number): string => new Date(ms).toISOString().slice(0, 7);

/**
 * Month by month metrics under D-01a/D-09 (mirrors metrics.py monthly_metrics): month M selects the shipment
 * lines shipped in M and the credits dated in M (whatever month their line shipped), intersected with `window`.
 * Months with only credits appear (gross 0.00). A shipment's unallocated freight belongs to its shipped month.
 */
export function monthlyMetrics(
  facts: readonly ShipmentLineFact[], returns: readonly ReturnEvent[], window: Window = NO_WINDOW,
  unallocatedByShipment: ReadonlyMap<string, D.Dec> = new Map(),
): Map<string, Metrics> {
  checkWindow(window);
  const shipAt = new Map<string, number>();
  const known = new Set<string>();
  const months = new Set<string>();
  for (const f of facts) {
    shipAt.set(f.shipment_id, f.shipped_at);
    known.add(f.shipment_line_id);
    if (inWindow(f.shipped_at, window)) months.add(monthKey(f.shipped_at));
  }
  for (const r of returns) if (known.has(r.shipment_line_id) && creditInWindow(r.credit_date, window)) months.add(r.credit_date.slice(0, 7));
  const out = new Map<string, Metrics>();
  for (const m of [...months].sort(cmpStr)) {
    const y = Number(m.slice(0, 4));
    const mo = Number(m.slice(5));
    let lo = Date.UTC(y, mo - 1, 1);
    let hi = Date.UTC(y, mo, 1);
    if (window.from !== null) lo = Math.max(lo, window.from);
    if (window.to !== null) hi = Math.min(hi, window.to);
    let unalloc = D.ZERO;
    for (const [sid, v] of unallocatedByShipment) {
      const at = shipAt.get(sid);
      if (at !== undefined && at >= lo && at < hi) unalloc = D.add(unalloc, v);
    }
    out.set(m, computeMetrics(facts, { from: lo, to: hi }, { returns, unallocatedFreight: unalloc }));
  }
  return out;
}

/** A credit dated inside the window for a line shipped outside it (D-09). */
export interface OutsideCredit { event: ReturnEvent; fact: ShipmentLineFact }

/**
 * D-09: the evidence-ledger view of a window. `lines` are the facts shipped in the window with their credit
 * columns restricted to credits dated in the window; `outside` are the credits dated in the window for lines
 * shipped outside it. lines + outside sum to computeMetrics(facts, window, { returns }) exactly.
 */
export function windowLedger(
  facts: readonly ShipmentLineFact[], returns: readonly ReturnEvent[], window: Window,
): { lines: ShipmentLineFact[]; outside: OutsideCredit[] } {
  const byLine = new Map<string, ShipmentLineFact>();
  for (const f of facts) byLine.set(f.shipment_line_id, f);
  const credit = new Map<string, { c: D.Dec; r: D.Dec; q: number }>();
  const outside: OutsideCredit[] = [];
  for (const e of returns) {
    const f = byLine.get(e.shipment_line_id);
    if (!f || !creditInWindow(e.credit_date, window)) continue;
    if (!inWindow(f.shipped_at, window)) { outside.push({ event: e, fact: f }); continue; }
    const cur = credit.get(e.shipment_line_id) ?? { c: D.ZERO, r: D.ZERO, q: 0 };
    credit.set(e.shipment_line_id, { c: D.add(cur.c, e.merchandise_credit), r: D.add(cur.r, e.recoverable_return_cost), q: cur.q + e.returned_quantity });
  }
  const lines = facts.filter((f) => inWindow(f.shipped_at, window)).map((f) => {
    const c = credit.get(f.shipment_line_id);
    return { ...f, merchandise_credit: c?.c ?? D.ZERO, recoverable_return_cost: c?.r ?? D.ZERO, returned_quantity: c?.q ?? 0 };
  });
  outside.sort((a, b) => cmpStr(a.event.credit_date, b.event.credit_date) || cmpStr(a.event.return_id, b.event.return_id));
  return { lines, outside };
}
