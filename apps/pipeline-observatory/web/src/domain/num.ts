// Published number formats (contract D-04): proportions are 6-place decimal strings, minutes 4 places, money 2 places, ROUND_HALF_UP,
// null = unknown or a zero denominator. Every ratio is an exact rational over BigInt: there is no floating point in any figure.
export interface Fr { readonly n: bigint; readonly d: bigint }

const gcd = (a: bigint, b: bigint): bigint => { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b) { [a, b] = [b, a % b]; } return a; };
export function fr(n: bigint | number, d: bigint | number = 1n): Fr {
  let nn = BigInt(n), dd = BigInt(d);
  if (dd === 0n) throw new RangeError("zero denominator");
  if (dd < 0n) { nn = -nn; dd = -dd; }
  const g = gcd(nn, dd) || 1n;
  return { n: nn / g, d: dd / g };
}
export const ZERO: Fr = { n: 0n, d: 1n };
/** Sum; equal denominators (the common case: money in hundredths) skip the gcd. Reduce lazily: every comparison cross-multiplies. */
export const add = (a: Fr, b: Fr): Fr => (a.d === b.d ? { n: a.n + b.n, d: a.d } : fr(a.n * b.d + b.n * a.d, a.d * b.d));
export const sub = (a: Fr, b: Fr): Fr => (a.d === b.d ? { n: a.n - b.n, d: a.d } : fr(a.n * b.d - b.n * a.d, a.d * b.d));
export const neg = (a: Fr): Fr => ({ n: -a.n, d: a.d });
export const cmpFr = (a: Fr, b: Fr): number => { const l = a.n * b.d, r = b.n * a.d; return l < r ? -1 : l > r ? 1 : 0; };
export const eqFr = (a: Fr, b: Fr): boolean => cmpFr(a, b) === 0;
export const isZero = (a: Fr): boolean => a.n === 0n;
export const sumFr = (xs: Iterable<Fr>): Fr => { let s = ZERO; for (const x of xs) s = add(s, x); return s; };

/** An exact decimal string ("-12.50", "7", " 3.1\n") as a rational. Surrounding whitespace is ignored (as Decimal does). */
export function decFr(s: string): Fr {
  const m = /^\s*(-?)(\d+)(?:\.(\d+))?\s*$/.exec(s);
  if (!m) throw new RangeError(`not a decimal string: ${JSON.stringify(s)}`);
  const f = m[3] ?? "";
  const v = BigInt(m[2]! + f);
  return { n: m[1] ? -v : v, d: 10n ** BigInt(f.length) };
}

/** ROUND_HALF_UP of an exact rational to `dp` places, as a string; a rounding to zero never prints a minus sign. */
export function rnd(x: Fr, dp: number): string {
  const isNeg = x.n < 0n;
  const absn = isNeg ? -x.n : x.n;
  const scale = 10n ** BigInt(dp);
  const sn = absn * scale;
  const n = (sn * 2n + x.d) / (2n * x.d);
  const whole = n / scale, frac = n % scale;
  const s = dp ? `${whole}.${frac.toString().padStart(dp, "0")}` : String(whole);
  return (isNeg && n !== 0n ? "-" : "") + s;
}
export const p6 = (x: Fr | null): string | null => (x === null ? null : rnd(x, 6));
export const m4 = (x: Fr | null): string | null => (x === null ? null : rnd(x, 4));
export const money = (x: Fr): string => rnd(x, 2);
/** num/den, or null when the denominator is zero (unknown, never 0). */
export function ratio(num: number | bigint | Fr, den: number | bigint | Fr): Fr | null {
  const a = typeof num === "object" ? num : fr(num), b = typeof den === "object" ? den : fr(den);
  return b.n === 0n ? null : fr(a.n * b.d, a.d * b.n);
}
/** Round-half-up of a rational to an integer (display of an exact count only). */
export const toInt = (x: Fr): bigint => (x.n * 2n + x.d) / (2n * x.d);
