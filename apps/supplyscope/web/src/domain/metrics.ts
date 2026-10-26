// Metric aggregation (D-01..D-06). `computeMetrics` returns EXACTLY the keys of expected.json; rates come from aggregated
// numerators and denominators (never an average of rates), money is a 2 dp string, rates 6 dp. Mirrors metrics.py.
import { GROUP_KEYS, type GroupKey } from "./contract";
import { fillRate, inWindow, lastObservedDay, stockoutDayRatio, summarise } from "./demand";
import { DomainError, INVALID_WINDOW, UNKNOWN_REFERENCE } from "./errors";
import { endOfDayOnHand, pairKey, reconstruct, type Stock } from "./ledger";
import { cents, costInForce, d2, d6, fmtCents, onHandValue, ratio } from "./money";
import { parseRow } from "./ingest";
import { replenish, inventoryPosition, type Replenishment } from "./replenishment";
import { dayEnd, dayOf, dayStart, isoZ } from "./time";
import type { Backorder, CostVersion, Metrics, Param, Population, PoLine, Product, PurchaseOrder, Receipt, StateSpec } from "./types";

export type Window = readonly [number | null, number | null];
export interface Scope { products?: ReadonlySet<string>; locations?: ReadonlySet<string> }
const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

export function checkWindow(window: Window): void {
  const [lo, hi] = window;
  if (lo !== null && hi !== null && lo >= hi) throw new DomainError(INVALID_WINDOW, "window start must be before end", null, { from: isoZ(lo), to: isoZ(hi) });
}

// ---- per-population indexes (cached; a population is never mutated) -------------------------------------------------
interface Index {
  productById: Map<string, Product>;
  orderById: Map<string, PurchaseOrder>;
  receiptsByLine: Map<string, Receipt[]>;
  versionsByProduct: Map<string, CostVersion[]>;
  paramLoc: Map<string, string>;
  moveLoc: Map<string, string>;
  firstLocation: string | null;
}
const cache = new WeakMap<Population, Index>();
function indexOf(pop: Population): Index {
  const hit = cache.get(pop);
  if (hit) return hit;
  const ix: Index = {
    productById: new Map(pop.products.map((p) => [p.product_id, p])),
    orderById: new Map(pop.purchase_orders.map((o) => [o.purchase_order_id, o])),
    receiptsByLine: new Map(), versionsByProduct: new Map(), paramLoc: new Map(), moveLoc: new Map(),
    firstLocation: pop.locations.reduce<string | null>((a, l) => (a === null || l.location_id < a ? l.location_id : a), null),
  };
  for (const r of pop.receipts) { const g = ix.receiptsByLine.get(r.po_line_id); if (g) g.push(r); else ix.receiptsByLine.set(r.po_line_id, [r]); }
  for (const v of pop.cost_versions) { const g = ix.versionsByProduct.get(v.product_id); if (g) g.push(v); else ix.versionsByProduct.set(v.product_id, [v]); }
  for (const p of pop.replenishment_params) { const c = ix.paramLoc.get(p.product_id); if (c === undefined || p.location_id < c) ix.paramLoc.set(p.product_id, p.location_id); }
  for (const m of pop.inventory_movements) { const c = ix.moveLoc.get(m.product_id); if (c === undefined || m.location_id < c) ix.moveLoc.set(m.product_id, m.location_id); }
  cache.set(pop, ix);
  return ix;
}

/** A copy with extra purchase order lines (a fixture state's `add_purchase_order_lines`). */
export function withLines(pop: Population, lines: PoLine[]): Population {
  return { ...pop, purchase_order_lines: [...pop.purchase_order_lines, ...lines] };
}
/** The extra purchase order lines of a fixture state; each must reference a known purchase order. */
export function stateLines(pop: Population, state: StateSpec | null | undefined): PoLine[] {
  const orders = new Set(pop.purchase_orders.map((o) => o.purchase_order_id));
  return (state?.add_purchase_order_lines ?? []).map((row) => {
    const line = parseRow<PoLine>("purchase_order_lines", row);
    if (!orders.has(line.purchase_order_id)) throw new DomainError(UNKNOWN_REFERENCE, `state line ${line.po_line_id} references an unknown purchase order`);
    return line;
  });
}

/** The supplier a product is bought from: its own record, a parameter row, its latest purchase order, else none. */
export function supplierOf(pop: Population, productId: string): string {
  const ix = indexOf(pop);
  const prod = ix.productById.get(productId);
  if (prod?.supplier_id) return prod.supplier_id;
  for (const p of [...pop.replenishment_params].sort((a, b) => cmp(a.location_id, b.location_id))) if (p.product_id === productId && p.supplier_id) return p.supplier_id;
  let best: [number, string, string] | null = null;
  for (const l of pop.purchase_order_lines) {
    const o = ix.orderById.get(l.purchase_order_id);
    if (l.product_id !== productId || !o) continue;
    if (best === null || o.ordered_at > best[0] || (o.ordered_at === best[0] && l.po_line_id > best[1])) best = [o.ordered_at, l.po_line_id, o.supplier_id];
  }
  return best ? best[2] : "unassigned";
}

/** Purchase order lines carry no location: a product's open quantity counts at its first parameter location, else the
 * first location with movements, else the first location. */
export function allocationLocation(pop: Population, productId: string): string | null {
  const ix = indexOf(pop);
  return ix.paramLoc.get(productId) ?? ix.moveLoc.get(productId) ?? ix.firstLocation;
}

const lineOpen = (ix: Index, line: PoLine, asOf: number): number => {
  let got = 0;
  for (const r of ix.receiptsByLine.get(line.po_line_id) ?? []) if (r.received_at <= asOf) got += r.received_quantity;
  return Math.max(line.ordered_quantity - got, 0);
};
/** Open quantity (ordered - received at or before asOf) of lines on confirmed orders placed by asOf. */
export function onOrderByProduct(pop: Population, asOf: number): Map<string, number> {
  const ix = indexOf(pop);
  const out = new Map<string, number>();
  for (const l of pop.purchase_order_lines) {
    const o = ix.orderById.get(l.purchase_order_id);
    if (o && o.status === "confirmed" && o.ordered_at <= asOf) out.set(l.product_id, (out.get(l.product_id) ?? 0) + lineOpen(ix, l, asOf));
  }
  return out;
}
export function defaultStart(pop: Population, asOf: number): number {
  let first: number | null = null;
  for (const s of pop.sales) if (first === null || s.sold_at < first) first = s.sold_at;
  for (const m of pop.inventory_movements) if (first === null || m.event_at < first) first = m.event_at;
  return dayStart(dayOf(first ?? asOf));
}

const openBackorder = (b: Backorder, asOf: number): boolean => b.opened_at <= asOf && (b.closed_at === null || b.closed_at > asOf);

// ---- replenishment rows ---------------------------------------------------------------------------------------------
export interface PairRow extends Replenishment {
  product_id: string; sku: string; location_id: string; supplier_id: string; abc_class: string | null; unit_cost: string;
  on_hand: number; on_order: number; backorders: number; reserved: number; available: number; moq: number; pack_size: number;
  /** A recommendation row only: nothing becomes a supplier commitment (D-02). */
  status: "draft";
}
interface Core { stocks: Map<string, Stock>; openByProduct: Map<string, number>; alloc: Map<string, string | null>; openBo: Map<string, number>; rows: PairRow[] }

function core(pop: Population, asOf: number, scope: Scope): Core {
  const ix = indexOf(pop);
  const inp = (p: string, l: string): boolean => (!scope.products || scope.products.has(p)) && (!scope.locations || scope.locations.has(l));
  const stocks = reconstruct(pop.inventory_movements.filter((m) => inp(m.product_id, m.location_id)), asOf);
  const alloc = new Map(pop.products.map((p) => [p.product_id, allocationLocation(pop, p.product_id)] as const));
  const openByProduct = onOrderByProduct(pop, asOf);
  const openBo = new Map<string, number>();
  for (const b of pop.backorders) if (inp(b.product_id, b.location_id) && openBackorder(b, asOf)) { const k = pairKey(b.product_id, b.location_id); openBo.set(k, (openBo.get(k) ?? 0) + b.quantity); }
  const reservedBy = new Map<string, number>();
  for (const r of pop.reservations) if (inp(r.product_id, r.location_id) && r.reserved_at <= asOf && (r.released_at === null || r.released_at > asOf)) { const k = pairKey(r.product_id, r.location_id); reservedBy.set(k, (reservedBy.get(k) ?? 0) + r.quantity); }
  const rows: PairRow[] = [];
  for (const p of pop.replenishment_params) {
    if (!inp(p.product_id, p.location_id)) continue;
    const prod = ix.productById.get(p.product_id)!;
    const k = pairKey(p.product_id, p.location_id);
    const onHand = stocks.get(k)?.on_hand ?? 0;
    const onOrder = alloc.get(p.product_id) === p.location_id ? openByProduct.get(p.product_id) ?? 0 : 0;
    const bo = openBo.get(k) ?? 0;
    const reserved = reservedBy.get(k) ?? 0;
    rows.push({
      ...replenish(onHand, onOrder, bo, p.reorder_point, p.target_position, prod.minimum_order_quantity, prod.pack_size),
      product_id: p.product_id, sku: prod.sku, location_id: p.location_id, supplier_id: p.supplier_id ?? supplierOf(pop, p.product_id),
      abc_class: prod.abc_class, unit_cost: prod.unit_cost, on_hand: onHand, on_order: onOrder, backorders: bo, reserved, available: onHand - reserved,
      moq: prod.minimum_order_quantity, pack_size: prod.pack_size, status: "draft",
    });
  }
  return { stocks, openByProduct, alloc, openBo, rows };
}

/** One draft row per replenishment parameter row (SKU x location) at `asOf`, in parameter order. */
export function reorderRows(pop: Population, asOf: number, state: StateSpec | null = null): PairRow[] {
  const extra = stateLines(pop, state);
  return core(extra.length ? withLines(pop, extra) : pop, asOf, {}).rows;
}

/** The metric set at `asOf` over the window [start, end) (an absent end means up to and including asOf). `scope` narrows
 * products / locations (used by `groupMetrics`). `state` may add purchase order lines. */
export function computeMetrics(pop0: Population, asOf: number, window: Window = [null, null], state: StateSpec | null = null, scope: Scope = {}): Metrics {
  checkWindow(window);
  const extra = stateLines(pop0, state);
  const pop = extra.length ? withLines(pop0, extra) : pop0;
  const ix = indexOf(pop);
  const start = window[0] ?? defaultStart(pop, asOf);
  const end = window[1];
  const inp = (p: string, l: string): boolean => (!scope.products || scope.products.has(p)) && (!scope.locations || scope.locations.has(l));
  const c = core(pop, asOf, scope);

  let onHand = 0, runningMin = 0, naiveMin = 0, negative = false, capital = 0n;
  for (const s of c.stocks.values()) {
    onHand += s.on_hand;
    runningMin = Math.min(runningMin, s.running_min);
    naiveMin = Math.min(naiveMin, s.timestamp_order_min);
    negative = negative || s.negative;
    capital += onHandValue(s.on_hand, costInForce(ix.productById.get(s.product_id)!.unit_cost, ix.versionsByProduct.get(s.product_id) ?? [], dayOf(asOf)));
  }
  let onOrder = 0;
  for (const [p, q] of c.openByProduct) if (inp(p, c.alloc.get(p) ?? "")) onOrder += q;
  let backorders = 0;
  for (const q of c.openBo.values()) backorders += q;
  let reserved = 0;
  for (const r of pop.reservations) if (inp(r.product_id, r.location_id) && r.reserved_at <= asOf && (r.released_at === null || r.released_at > asOf)) reserved += r.quantity;
  let position = inventoryPosition(onHand, onOrder, backorders); // reserved is NOT subtracted

  const rows = c.rows;
  let rep: Pick<Metrics, "reorder_point" | "target_position" | "reorder_triggered" | "raw_order" | "order_after_moq" | "order_quantity">;
  if (rows.length) {
    const sum = (f: (r: PairRow) => number): number => rows.reduce((a, r) => a + f(r), 0);
    rep = { reorder_point: sum((r) => r.reorder_point), target_position: sum((r) => r.target_position), reorder_triggered: rows.some((r) => r.triggered), raw_order: sum((r) => r.raw_order), order_after_moq: sum((r) => r.order_after_moq), order_quantity: sum((r) => r.order_quantity) };
    if (rows.length === 1) position = rows[0]!.position; // one parameter row: the position is that row's own
  } else {
    rep = { reorder_point: null, target_position: null, reorder_triggered: null, raw_order: null, order_after_moq: null, order_quantity: null };
  }

  const ds = summarise(pop.sales.filter((s) => inp(s.product_id, s.location_id)), pop.backorders.filter((b) => inp(b.product_id, b.location_id)), pop.lost_sales.filter((l) => inp(l.product_id, l.location_id)), start, end, asOf);
  const empty = !pop.inventory_movements.some((m) => inp(m.product_id, m.location_id)) && !pop.sales.some((s) => inp(s.product_id, s.location_id));
  return {
    fill_rate: d6(fillRate(ds)), requested_units: ds.requested, fulfilled_units: ds.fulfilled, unmet_units: ds.unmet, observed_days: ds.observedDays,
    stockout_day_count: ds.stockoutDates.size, stockout_days: empty ? null : d6(stockoutDayRatio(ds)), running_stock_min: runningMin,
    timestamp_order_stock_min: naiveMin, negative_stock: negative, working_capital: fmtCents(capital), empty_population: empty,
    on_hand: onHand, on_order: onOrder, backorders, reserved, available: onHand - reserved, inventory_position: position, ...rep,
  } as Metrics;
}

export function negativeStockFlags(pop: Population, asOf: number): { flag: string; product_id: string; location_id: string; on_hand_raw: number }[] {
  return [...reconstruct(pop.inventory_movements, asOf).values()].flatMap((s) => s.flags.map((flag) => ({ flag, product_id: s.product_id, location_id: s.location_id, on_hand_raw: s.on_hand_raw })));
}

/** group value -> the scope (products, locations) of the group. */
export function groupValues(pop: Population, key: GroupKey): Map<string, Scope> {
  if (!(GROUP_KEYS as readonly string[]).includes(key)) throw new Error(`group_by must be one of ${GROUP_KEYS.join(", ")}`);
  const out = new Map<string, Scope>();
  if (key === "product") for (const p of [...pop.products].sort((a, b) => cmp(a.product_id, b.product_id))) out.set(p.product_id, { products: new Set([p.product_id]) });
  else if (key === "location") for (const l of [...pop.locations].sort((a, b) => cmp(a.location_id, b.location_id))) out.set(l.location_id, { locations: new Set([l.location_id]) });
  else {
    const groups = new Map<string, Set<string>>();
    for (const p of pop.products) {
      const g = key === "supplier" ? supplierOf(pop, p.product_id) : p.abc_class || "unclassified";
      const s = groups.get(g) ?? new Set<string>();
      s.add(p.product_id);
      groups.set(g, s);
    }
    for (const g of [...groups.keys()].sort(cmp)) out.set(g, { products: groups.get(g)! });
  }
  return out;
}
export function groupMetrics(pop: Population, key: GroupKey, asOf: number, window: Window = [null, null], state: StateSpec | null = null): Map<string, Metrics> {
  return new Map([...groupValues(pop, key)].map(([g, scope]) => [g, computeMetrics(pop, asOf, window, state, scope)] as const));
}

/** Average daily inventory value and turnover (annualised COGS / average inventory value, D-05). Each day is valued at the
 * cost in force on that day (P03-TEST-12). */
export function supplementary(pop: Population, asOf: number, window: Window = [null, null]) {
  const ix = indexOf(pop);
  const start = window[0] ?? defaultStart(pop, asOf);
  const first = dayOf(start), last = lastObservedDay(window[1], asOf);
  if (last < first) return { average_inventory_value: null, annualised_cogs: null, inventory_turnover: null };
  const eod = endOfDayOnHand(pop.inventory_movements.filter((m) => m.event_at <= asOf), first, last);
  const days = last - first + 1;
  let total = 0n;
  for (const [k, series] of eod) {
    const p = k.split("\u0000")[0]!;
    const prod = ix.productById.get(p)!;
    series.forEach((qty, i) => { total += onHandValue(qty, costInForce(prod.unit_cost, ix.versionsByProduct.get(p) ?? [], first + i)); });
  }
  let cogs = 0n;
  for (const s of pop.sales) if (inWindow(s.sold_at, start, window[1], asOf)) {
    const prod = ix.productById.get(s.product_id)!;
    cogs += BigInt(s.quantity) * cents(costInForce(prod.unit_cost, ix.versionsByProduct.get(s.product_id) ?? [], dayOf(s.sold_at)));
  }
  return {
    average_inventory_value: d2(ratio(total, 100 * days)), annualised_cogs: d2(ratio(cogs * 365n, 100 * days)),
    inventory_turnover: d6(ratio(cogs * 365n, total)),
  };
}

// ---- daily series for one SKU x location (the trajectory) ------------------------------------------------------------
export interface PairSeries {
  days: number[]; on_hand: number[]; on_order: number[]; backorders: number[]; position: number[];
  receipts: { day: number; quantity: number; receipt_id: string }[]; stockout_days: number[];
}
/** End-of-day on hand, on order, backorders and position for each day first..last, by the rules `computeMetrics` uses. */
export function pairSeries(pop0: Population, productId: string, locationId: string, first: number, last: number, state: StateSpec | null = null): PairSeries {
  const extra = stateLines(pop0, state);
  const pop = extra.length ? withLines(pop0, extra) : pop0;
  const ix = indexOf(pop);
  const n = Math.max(last - first + 1, 0);
  const days = Array.from({ length: n }, (_, i) => first + i);
  const eod = endOfDayOnHand(pop.inventory_movements.filter((m) => m.product_id === productId && m.location_id === locationId), first, last).get(pairKey(productId, locationId));
  const onHand = days.map((_, i) => Math.max(eod?.[i] ?? 0, 0));
  const counted = allocationLocation(pop, productId) === locationId;
  const lines = counted ? pop.purchase_order_lines.filter((l) => l.product_id === productId && ix.orderById.get(l.purchase_order_id)?.status === "confirmed") : [];
  const onOrder = days.map((d) => {
    const at = dayEnd(d);
    let q = 0;
    for (const l of lines) if (ix.orderById.get(l.purchase_order_id)!.ordered_at <= at) q += lineOpen(ix, l, at);
    return q;
  });
  const bos = pop.backorders.filter((b) => b.product_id === productId && b.location_id === locationId);
  const backorders = days.map((d) => bos.reduce((a, b) => a + (openBackorder(b, dayEnd(d)) ? b.quantity : 0), 0));
  const lineProduct = new Map(pop.purchase_order_lines.map((l) => [l.po_line_id, l.product_id] as const));
  const receipts = pop.receipts.filter((r) => r.location_id === locationId && lineProduct.get(r.po_line_id) === productId && dayOf(r.received_at) >= first && dayOf(r.received_at) <= last)
    .map((r) => ({ day: dayOf(r.received_at), quantity: r.received_quantity, receipt_id: r.receipt_id })).sort((a, b) => a.day - b.day || cmp(a.receipt_id, b.receipt_id));
  const so = new Set<number>();
  for (const b of bos) so.add(dayOf(b.opened_at));
  for (const l of pop.lost_sales) if (l.product_id === productId && l.location_id === locationId) so.add(dayOf(l.occurred_at));
  return { days, on_hand: onHand, on_order: onOrder, backorders, position: days.map((_, i) => onHand[i]! + onOrder[i]! - backorders[i]!), receipts, stockout_days: days.filter((d) => so.has(d)) };
}

export const paramOf = (pop: Population, productId: string, locationId: string): Param | undefined =>
  pop.replenishment_params.find((p) => p.product_id === productId && p.location_id === locationId);
