// Layout scaling from exact rationals using integer arithmetic only: how many basis points of `max` is `x` (clamped to 0..10000).
import { cmpFr, type Fr } from "../domain/num";

export function basisPoints(x: Fr, max: Fr): number {
  if (max.n <= 0n || cmpFr(x, { n: 0n, d: 1n }) <= 0) return 0;
  const v = (x.n * max.d * 10000n) / (x.d * max.n);
  return v > 10000n ? 10000 : Number(v);
}
/** A signed position on [-max, +max] mapped to 0..10000 basis points (0 = -max, 5000 = zero). */
export function signedBasisPoints(x: Fr, max: Fr): number {
  if (max.n <= 0n) return 5000;
  const v = (x.n * max.d * 5000n) / (x.d * max.n);
  const c = v > 5000n ? 5000n : v < -5000n ? -5000n : v;
  return 5000 + Number(c);
}
