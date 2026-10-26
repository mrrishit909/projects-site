// Mirrors domain/revenue_atlas/money.py (largest_remainder; cents/rate6 live in decimal.ts).
import { type Dec, cents, isNegative } from "./decimal";
import * as D from "./decimal";
import { cmpStr } from "./errors";

/** Floor division on BigInt (rounds toward negative infinity, like Python //). */
function floorDiv(n: bigint, d: bigint): bigint {
  const q = n / d;
  return (n % d !== 0n) && ((n < 0n) !== (d < 0n)) ? q - 1n : q;
}

/**
 * Split `total` over `weights` so the cents sum exactly (D-04). Shares are floored to cents;
 * leftover cents go one at a time to the largest fractional remainders, ties broken by the lowest
 * key. Exact rational arithmetic on BigInt. Returns a Map in ascending key order.
 */
export function largestRemainder(total: Dec, weights: ReadonlyArray<readonly [string, Dec]>): Map<string, Dec> {
  const keys = weights.map(([k]) => k);
  if (new Set(keys).size !== keys.length) throw new Error("duplicate allocation keys");
  if (weights.some(([, w]) => isNegative(w))) throw new Error("negative weight");
  const maxScale = weights.reduce((m, [, w]) => Math.max(m, w.s), 0);
  const ints = weights.map(([k, w]) => [k, w.u * 10n ** BigInt(maxScale - w.s)] as const);
  const wsum = ints.reduce((a, [, w]) => a + w, 0n);
  if (wsum === 0n) throw new Error("sum of weights is zero");
  const totalC = cents(total).u; // integer cents
  const rows = ints.map(([k, w]) => {
    const num = totalC * w;
    const floor = floorDiv(num, wsum);
    return { k, floor, rem: num - floor * wsum };
  });
  let leftover = totalC - rows.reduce((a, r) => a + r.floor, 0n);
  const order = [...rows].sort((a, b) => (a.rem === b.rem ? cmpStr(a.k, b.k) : a.rem > b.rem ? -1 : 1));
  for (const r of order) {
    if (leftover <= 0n) break;
    r.floor += 1n;
    leftover -= 1n;
  }
  const out = new Map<string, Dec>();
  for (const r of [...rows].sort((a, b) => cmpStr(a.k, b.k))) out.set(r.k, { u: r.floor, s: 2 });
  return out;
}

export const sumMap = (m: ReadonlyMap<string, Dec>): Dec => D.sum(m.values());
