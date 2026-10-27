// Exact rationals over BigInt (D-04): money, rates, discount factors, hours and scores are fractions inside and are rounded only at the declared
// presentation step, ROUND_HALF_UP (half away from zero), by integer arithmetic. There is no floating point in any figure this module touches.
export interface Fr { readonly n: bigint; readonly d: bigint }

const gcd = (a: bigint, b: bigint): bigint => { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b) { [a, b] = [b, a % b]; } return a; };
export function fr(n: bigint | number, d: bigint | number = 1n): Fr {
  let nn = BigInt(n), dd = BigInt(d);
  if (dd === 0n) throw new RangeError("zero denominator");
  if (dd < 0n) { nn = -nn; dd = -dd; }
  if (dd === 1n) return { n: nn, d: 1n };
  const g = gcd(nn, dd) || 1n;
  return { n: nn / g, d: dd / g };
}
export const ZERO: Fr = { n: 0n, d: 1n };
export const ONE: Fr = { n: 1n, d: 1n };
export const add = (a: Fr, b: Fr): Fr => (a.d === b.d ? fr(a.n + b.n, a.d) : fr(a.n * b.d + b.n * a.d, a.d * b.d));
export const sub = (a: Fr, b: Fr): Fr => (a.d === b.d ? fr(a.n - b.n, a.d) : fr(a.n * b.d - b.n * a.d, a.d * b.d));
export const mul = (a: Fr, b: Fr): Fr => fr(a.n * b.n, a.d * b.d);
export const div = (a: Fr, b: Fr): Fr => fr(a.n * b.d, a.d * b.n);
export const neg = (a: Fr): Fr => ({ n: -a.n, d: a.d });
export const absFr = (a: Fr): Fr => (a.n < 0n ? neg(a) : a);
/** Sign of a - b as -1, 0, 1 (exact). */
export const cmpFr = (a: Fr, b: Fr): number => { const l = a.n * b.d, r = b.n * a.d; return l < r ? -1 : l > r ? 1 : 0; };
export const eqFr = (a: Fr, b: Fr): boolean => a.n === b.n && a.d === b.d;
export const lt = (a: Fr, b: Fr): boolean => cmpFr(a, b) < 0;
export const gt = (a: Fr, b: Fr): boolean => cmpFr(a, b) > 0;
export const le = (a: Fr, b: Fr): boolean => cmpFr(a, b) <= 0;
export const ge = (a: Fr, b: Fr): boolean => cmpFr(a, b) >= 0;
export const isZero = (a: Fr): boolean => a.n === 0n;
export const sumFr = (xs: readonly Fr[]): Fr => xs.reduce(add, ZERO);
export const maxFr = (xs: readonly Fr[]): Fr => xs.reduce((m, x) => (gt(x, m) ? x : m));
/** x to a non-negative integer power. A reduced fraction stays reduced under a power, so no gcd is needed. */
export function powFr(x: Fr, k: number): Fr {
  if (!Number.isInteger(k) || k < 0) throw new RangeError("exponent must be a non-negative integer");
  return { n: x.n ** BigInt(k), d: x.d ** BigInt(k) };
}
/** 1 / (1 + r)^p for a rate r > -1: the discount factor of period p as a rational. */
export function discountFactor(r: Fr, p: number): Fr {
  const base = add(ONE, r);
  const pw = powFr(base, p);
  return pw.n < 0n ? fr(-pw.d, -pw.n) : { n: pw.d, d: pw.n };
}

/** The decimal strings the contract admits: up to 14 integer and 6 decimal digits, optional minus (D-04). */
export const DECIMAL_RE = /^-?\d{1,14}(\.\d{1,6})?$/;
export const isDecimal = (s: unknown): s is string => typeof s === "string" && DECIMAL_RE.test(s);

/** An exact decimal string ("0.250000", "-3.5") as a rational; refuses anything that is not a decimal (a number is not accepted: no floats). */
export function dec(s: unknown): Fr {
  if (typeof s !== "string") throw new TypeError(`a decimal must be a string, got ${typeof s}`);
  const m = /^(-)?(\d+)(?:\.(\d+))?$/.exec(s.trim());
  if (!m) throw new RangeError(`not a decimal string: ${s}`);
  const f = m[3] ?? "";
  const n = BigInt(m[2]! + f);
  return fr(m[1] ? -n : n, 10n ** BigInt(f.length));
}
/** A rational given as the exact text "n/d" or "n". */
export function parseEx(s: string): Fr {
  const m = /^(-?\d+)(?:\/(\d+))?$/.exec(s);
  if (!m) throw new RangeError(`not an exact rational: ${s}`);
  return fr(BigInt(m[1]!), BigInt(m[2] ?? "1"));
}

/** ROUND_HALF_UP of an exact rational to `dp` places, as a string; never "-0.00". */
export function rnd(x: Fr, dp: number): string {
  const negative = x.n < 0n;
  const absn = negative ? -x.n : x.n;
  const scale = 10n ** BigInt(dp);
  const sn = absn * scale;
  const n = (sn * 2n + x.d) / (2n * x.d);
  const whole = n / scale, frac = n % scale;
  const s = dp ? `${whole}.${frac.toString().padStart(dp, "0")}` : String(whole);
  return (negative && n !== 0n ? "-" : "") + s;
}
export const money = (x: Fr): string => rnd(x, 2);
export const p6 = (x: Fr | null): string | null => (x === null ? null : rnd(x, 6));
export const m4 = (x: Fr | null): string | null => (x === null ? null : rnd(x, 4));
export const mn = (x: Fr | null): string | null => (x === null ? null : money(x));
/** The exact rational as "n/d" ("n" for an integer). */
export const ex = (x: Fr | null): string | null => (x === null ? null : x.d === 1n ? x.n.toString() : `${x.n}/${x.d}`);

/** Canonical text of a stored amount: at least 2 places, no trailing zeros beyond them ("1000.000000" -> "1000.00"). */
export function canon(v: string): string {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(v);
  if (!m) throw new RangeError(`not a decimal string: ${v}`);
  const whole = m[2]!.replace(/^0+(?=\d)/, "");
  if (m[3] === undefined) return `${m[1]}${whole}.00`;
  const frac = m[3].replace(/0+$/, "").padEnd(2, "0");
  return `${m[1]}${whole}.${frac}`;
}

/** Code-point order, as Python sorts strings (JavaScript compares UTF-16 units). */
export function cmp(a: string, b: string): number {
  if (a === b) return 0;
  const x = Array.from(a), y = Array.from(b);
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) {
    const p = x[i]!.codePointAt(0)!, q = y[i]!.codePointAt(0)!;
    if (p !== q) return p < q ? -1 : 1;
  }
  return x.length === y.length ? 0 : x.length < y.length ? -1 : 1;
}
export const cmpNum = (a: number | bigint, b: number | bigint): number => (a < b ? -1 : a > b ? 1 : 0);

/**
 * The monthly rate that stands for an annual one: (1 + r)^(1/12) - 1, recorded as a 6-place decimal (D-P9-06; the twelfth root is irrational).
 * Exact integer search, no floating point: the largest k/10^6 whose 12th power of (1 + k/10^6) does not exceed 1 + r, rounded half up.
 */
export function monthlyFromAnnual(annual: Fr): Fr {
  if (annual.n < 0n) throw new RangeError("a negative annual rate has no declared conversion here");
  const target = add(ONE, annual);
  const S = 1_000_000n;
  const le12 = (k2: bigint, scale2: bigint): boolean => { // (scale2 + k2)^12 / scale2^12 <= target ?
    const base = scale2 + k2;
    return base ** 12n * target.d <= target.n * scale2 ** 12n;
  };
  let lo = 0n, hi = S * 2n; // monthly rate below 200 % for any annual rate below 4,095 times
  while (le12(hi, S)) hi *= 2n;
  while (lo < hi) { const mid = (lo + hi + 1n) / 2n; if (le12(mid, S)) lo = mid; else hi = mid - 1n; }
  // half-step: is the true root at or above k + 1/2 ?  Compare (2S + 2k + 1)^12 with target * (2S)^12.
  const exactUp = (2n * S + 2n * lo + 1n) ** 12n * target.d <= target.n * (2n * S) ** 12n;
  return fr(exactUp ? lo + 1n : lo, S);
}
