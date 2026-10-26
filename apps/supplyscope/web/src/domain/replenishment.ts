// Replenishment (D-02, D-06). position = on hand + on order - backorders (reserved is NOT subtracted);
// quantity = pack_round_up(max(target - position, MOQ)) when position < reorder point, else 0. Integer arithmetic only.
import { Z_TABLE } from "./contract";
import { DomainError, UNSUPPORTED_SERVICE_TARGET } from "./errors";
import { decAdd, decCeil, decInt, fmtScaled, parseDec, pow10, type Dec, type Rat } from "./money";
import { parseDay } from "./time";
import type { Closure } from "./types";

export const inventoryPosition = (onHand: number, onOrder: number, backorders: number): number => onHand + onOrder - backorders;
export const isTriggered = (position: number, reorderPoint: number): boolean => position < reorderPoint;
export const rawOrder = (target: number, position: number): number => Math.max(target - position, 0);
export const applyMoq = (raw: number, moq: number): number => Math.max(raw, moq);
/** Round up to a whole number of packs. */
export function packRoundUp(quantity: number, packSize: number): number {
  if (packSize < 1) throw new Error("pack_size must be at least 1");
  return Math.ceil(quantity / packSize) * packSize;
}

export interface Replenishment {
  position: number; reorder_point: number; target_position: number; triggered: boolean;
  raw_order: number; order_after_moq: number; order_quantity: number;
}
/** The golden arithmetic. Not triggered: raw, MOQ and pack quantities are all 0 (D-06). */
export function replenish(onHand: number, onOrder: number, backorders: number, reorderPoint: number, target: number, moq: number, packSize: number): Replenishment {
  const position = inventoryPosition(onHand, onOrder, backorders);
  if (!isTriggered(position, reorderPoint)) return { position, reorder_point: reorderPoint, target_position: target, triggered: false, raw_order: 0, order_after_moq: 0, order_quantity: 0 };
  const raw = rawOrder(target, position);
  const after = applyMoq(raw, moq);
  return { position, reorder_point: reorderPoint, target_position: target, triggered: true, raw_order: raw, order_after_moq: after, order_quantity: packRoundUp(after, packSize) };
}

// ---- supplier calendar and lead time ------------------------------------------------------------------------------
function closedDays(closures: readonly Closure[], calendarId: string): Set<number> {
  const days = new Set<number>();
  for (const c of closures) if (c.calendar_id === calendarId) for (let d = parseDay(c.closed_from); d <= parseDay(c.closed_to); d++) days.add(d);
  return days;
}
/** The day `leadDays` open supplier-calendar days after `start` (closure days do not count, P03-TEST-05). */
export function arrivalDay(start: number, leadDays: number, closures: readonly Closure[], calendarId: string): number {
  const closed = closedDays(closures, calendarId);
  let d = start, counted = 0;
  while (counted < leadDays) { d += 1; if (!closed.has(d)) counted += 1; }
  return d;
}
/** Calendar days from `start` until the quoted lead days have elapsed on the supplier calendar. */
export const effectiveLeadDays = (start: number, leadDays: number, closures: readonly Closure[], calendarId: string): number =>
  arrivalDay(start, leadDays, closures, calendarId) - start;

// ---- safety stock -------------------------------------------------------------------------------------------------
/** z for a supported service target (6 dp, as an integer scaled by 10^6). */
export function zValue(serviceTarget: string): bigint {
  const d = parseDec(serviceTarget);
  const hundredths = d.n * 100n;
  const key = hundredths % pow10(d.s) === 0n ? fmtScaled(hundredths / pow10(d.s), 2) : "";
  if (!(key in Z_TABLE)) {
    throw new DomainError(UNSUPPORTED_SERVICE_TARGET, `service target ${serviceTarget} is not one of ${Object.keys(Z_TABLE).sort().join(", ")}`, null, { supported: Object.keys(Z_TABLE).sort() });
  }
  return parseDec(Z_TABLE[key]!).n;
}
/** ceil(z * sqrt(daily residual variance * lead days)), exact: the least integer k with k^2 >= z^2 * variance * lead. */
export function safetyStock(z6: bigint, dailyVariance: Rat | null, leadDays: number): number {
  if (dailyVariance === null || leadDays <= 0 || dailyVariance.num === 0n) return 0;
  const lhsDen = dailyVariance.den * 10n ** 12n; // k^2 * den * 10^12 >= z6^2 * num * lead
  const rhs = z6 * z6 * dailyVariance.num * BigInt(leadDays);
  let k = BigInt(Math.floor(Math.sqrt(Number(rhs / lhsDen))));
  while (k * k * lhsDen < rhs) k += 1n;
  while (k > 0n && (k - 1n) * (k - 1n) * lhsDen >= rhs) k -= 1n;
  return Number(k);
}
/** Expected demand over the lead window (the first `leadDays` forecast days, closure days included). */
export const leadTimeDemand = (daily: readonly Dec[], leadDays: number): Dec => daily.slice(0, leadDays).reduce(decAdd, decInt(0));
/** (reorder point, target position) when no parameter row exists: ROP = ceil(LTD + SS), target = ROP + ceil(review demand). */
export function derivedParameters(ltd: Dec, safety: number, reviewDemand: Dec): [number, number] {
  const rop = Number(decCeil(decAdd(ltd, decInt(safety))));
  return [rop, rop + Number(decCeil(reviewDemand))];
}
