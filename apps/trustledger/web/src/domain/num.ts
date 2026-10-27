// Published number formats (D-05): proportions are 6-place decimal strings, hours 4 places, ROUND_HALF_UP, null = unknown.
// Every ratio is an exact rational over BigInt; there is no floating point in any published figure.
export interface Fr { readonly n: bigint; readonly d: bigint }

const gcd = (a: bigint, b: bigint): bigint => { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b) { [a, b] = [b, a % b]; } return a; };
export function fr(n: bigint | number, d: bigint | number = 1n): Fr {
  let nn = BigInt(n), dd = BigInt(d);
  if (dd === 0n) throw new RangeError("zero denominator");
  if (dd < 0n) { nn = -nn; dd = -dd; }
  const g = gcd(nn, dd) || 1n;
  return { n: nn / g, d: dd / g };
}
export const add = (a: Fr, b: Fr): Fr => fr(a.n * b.d + b.n * a.d, a.d * b.d);
export const sub = (a: Fr, b: Fr): Fr => fr(a.n * b.d - b.n * a.d, a.d * b.d);
export const mul = (a: Fr, b: Fr): Fr => fr(a.n * b.n, a.d * b.d);
export const div = (a: Fr, b: Fr): Fr => fr(a.n * b.d, a.d * b.n);
export const eqFr = (a: Fr, b: Fr): boolean => a.n === b.n && a.d === b.d;
export const sumFr = (xs: readonly Fr[]): Fr => xs.reduce(add, fr(0));
export const isZero = (a: Fr): boolean => a.n === 0n;

/** An exact decimal string ("0.250000") as a rational. */
export function fracOfDec(s: string): Fr {
  const m = /^\s*(\d+)(?:\.(\d+))?\s*$/.exec(s);
  if (!m) throw new RangeError(`not a decimal string: ${s}`);
  const f = m[2] ?? "";
  return fr(BigInt(m[1]! + f), 10n ** BigInt(f.length));
}

/** ROUND_HALF_UP of an exact rational to `dp` places, as a string. */
export function rnd(x: Fr, dp: number): string {
  const neg = x.n < 0n;
  const absn = neg ? -x.n : x.n;
  const scale = 10n ** BigInt(dp);
  const sn = absn * scale;
  const n = (sn * 2n + x.d) / (2n * x.d);
  const whole = n / scale, frac = n % scale;
  const s = dp ? `${whole}.${frac.toString().padStart(dp, "0")}` : String(whole);
  return (neg && n !== 0n ? "-" : "") + s;
}
export const p6 = (x: Fr | null): string | null => (x === null ? null : rnd(x, 6));
export const h4 = (x: Fr | null): string | null => (x === null ? null : rnd(x, 4));
/** num/den, or null when the denominator is zero (unknown, never 0). */
export const ratio = (num: number, den: number): Fr | null => (den === 0 ? null : fr(num, den));
