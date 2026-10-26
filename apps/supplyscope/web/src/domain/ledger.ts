// Ledger reconstruction (D-01). Stock is the sum of posted deltas up to the cutoff instant per (product, location).
// Within a date the order is receipts, then sales, then everything else (review): the sort key is
// (date, movement type rank, event_at, movement_id). The same order is used by the simulation.
import { NEGATIVE_STOCK } from "./errors";
import { dayOf } from "./time";
import type { Movement } from "./types";

export const pairKey = (product: string, location: string): string => `${product}\u0000${location}`;
export const splitPair = (key: string): [string, string] => key.split("\u0000") as [string, string];

const RANK: Record<string, number> = { receipt: 0, sale: 1 };
const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

export function dayKeyCompare(a: Movement, b: Movement): number {
  return dayOf(a.event_at) - dayOf(b.event_at) || (RANK[a.movement_type] ?? 2) - (RANK[b.movement_type] ?? 2) ||
    a.event_at - b.event_at || cmp(a.movement_id, b.movement_id);
}
const timeKeyCompare = (a: Movement, b: Movement): number => a.event_at - b.event_at || cmp(a.movement_id, b.movement_id);

export interface Stock {
  product_id: string; location_id: string;
  /** The reconstructed sum, possibly negative. */
  on_hand_raw: number;
  /** Never negative: a negative reconstruction is valued and offered at zero. */
  on_hand: number;
  /** Lowest running stock in day order, including the opening 0. */
  running_min: number;
  /** The same by timestamp only, to show what day order prevents. */
  timestamp_order_min: number;
  negative: boolean;
  movement_count: number;
  flags: string[];
}

function run(ordered: readonly Movement[]): [number, number] {
  let r = 0, low = 0;
  for (const m of ordered) { r += m.quantity_delta; if (r < low) low = r; }
  return [r, low];
}

/** Stock per (product, location) from the movements posted at or before `asOf` (a later movement is excluded). */
export function reconstruct(movements: Iterable<Movement>, asOf: number): Map<string, Stock> {
  const groups = new Map<string, Movement[]>();
  for (const m of movements) {
    if (m.event_at > asOf) continue;
    const k = pairKey(m.product_id, m.location_id);
    const g = groups.get(k);
    if (g) g.push(m); else groups.set(k, [m]);
  }
  const out = new Map<string, Stock>();
  for (const [k, items] of [...groups].sort((a, b) => cmp(a[0], b[0]))) {
    const [raw, low] = run([...items].sort(dayKeyCompare));
    const [, naiveLow] = run([...items].sort(timeKeyCompare));
    const [p, l] = splitPair(k);
    const negative = raw < 0 || low < 0;
    out.set(k, { product_id: p, location_id: l, on_hand_raw: raw, on_hand: Math.max(raw, 0), running_min: low, timestamp_order_min: naiveLow, negative, movement_count: items.length, flags: negative ? [NEGATIVE_STOCK] : [] });
  }
  return out;
}

/** Raw end-of-day stock per pair for each day first..last (order within a day does not change the day's close). */
export function endOfDayOnHand(movements: Iterable<Movement>, first: number, last: number): Map<string, number[]> {
  const byPair = new Map<string, Movement[]>();
  for (const m of movements) {
    const k = pairKey(m.product_id, m.location_id);
    const g = byPair.get(k);
    if (g) g.push(m); else byPair.set(k, [m]);
  }
  const out = new Map<string, number[]>();
  for (const [k, items] of [...byPair].sort((a, b) => cmp(a[0], b[0]))) {
    const deltas = new Map<number, number>();
    let opening = 0;
    for (const m of items) {
      const d = dayOf(m.event_at);
      if (d < first) opening += m.quantity_delta;
      else if (d <= last) deltas.set(d, (deltas.get(d) ?? 0) + m.quantity_delta);
    }
    let r = opening;
    const series: number[] = [];
    for (let d = first; d <= last; d++) { r += deltas.get(d) ?? 0; series.push(r); }
    out.set(k, series);
  }
  return out;
}
