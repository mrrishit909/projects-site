// Exact arithmetic for the mirror of domain/productsignal (stats.py, D-04, D-05): BigInt only, no floating point in any published
// figure. Ratios are rationals (Frac). The special functions (erf series, atan, Student t) run in BigInt fixed point at 70
// decimals; Python's 80-digit Decimal differs from this by far less than the 1e-6 a figure is rounded to.
export class DomainError extends Error {
  readonly code: string;
  readonly detail: string;
  constructor(code: string, detail: string, readonly path: string | null = null) {
    super(`${code}: ${detail}`);
    this.code = code;
    this.detail = detail;
  }
}
export const MALFORMED_RECORD = "MALFORMED_RECORD";
export const malformed = (name: string, why: string): DomainError => new DomainError(MALFORMED_RECORD, `${name} ${why}`, name);

export const pow10 = (n: number): bigint => 10n ** BigInt(n);
export const absB = (v: bigint): bigint => (v < 0n ? -v : v);
export const gcd = (a: bigint, b: bigint): bigint => { a = absB(a); b = absB(b); while (b) [a, b] = [b, a % b]; return a; };

/** n / d rounded half away from zero (Python ROUND_HALF_UP), d > 0. */
export function roundDiv(n: bigint, d: bigint): bigint {
  const neg = n < 0n;
  const a = neg ? -n : n;
  let q = a / d;
  if (2n * (a % d) >= d) q += 1n;
  return neg ? -q : q;
}

/** Scaled integer as a decimal string with exactly `dp` decimals ("-0.00" is never produced by q()). */
export function fmt(v: bigint, dp: number): string {
  const neg = v < 0n;
  const s = (neg ? -v : v).toString().padStart(dp + 1, "0");
  const out = dp === 0 ? s : `${s.slice(0, s.length - dp)}.${s.slice(s.length - dp)}`;
  return neg ? `-${out}` : out;
}

// ------------------------------------------------------------------------------------------------ rationals
export interface Frac { readonly n: bigint; readonly d: bigint }
export function fr(n: bigint | number, d: bigint | number = 1n): Frac {
  let a = BigInt(n), b = BigInt(d);
  if (b === 0n) throw new DomainError("DIVISION_BY_ZERO", "zero denominator");
  if (b < 0n) { a = -a; b = -b; }
  const g = gcd(a, b) || 1n;
  return { n: a / g, d: b / g };
}
export const ZERO: Frac = { n: 0n, d: 1n };
export const ONE: Frac = { n: 1n, d: 1n };
export const add = (a: Frac, b: Frac): Frac => fr(a.n * b.d + b.n * a.d, a.d * b.d);
export const sub = (a: Frac, b: Frac): Frac => fr(a.n * b.d - b.n * a.d, a.d * b.d);
export const mul = (a: Frac, b: Frac): Frac => fr(a.n * b.n, a.d * b.d);
export const div = (a: Frac, b: Frac): Frac => fr(a.n * b.d, a.d * b.n);
export const cmp = (a: Frac, b: Frac): number => { const l = a.n * b.d, r = b.n * a.d; return l < r ? -1 : l > r ? 1 : 0; };
export const lt = (a: Frac, b: Frac): boolean => cmp(a, b) < 0;
export const le = (a: Frac, b: Frac): boolean => cmp(a, b) <= 0;
export const gt = (a: Frac, b: Frac): boolean => cmp(a, b) > 0;
export const eqF = (a: Frac, b: Frac): boolean => cmp(a, b) === 0;
export const absF = (a: Frac): Frac => ({ n: absB(a.n), d: a.d });
export const mulI = (a: Frac, k: bigint | number): Frac => mul(a, fr(k));
export const sumF = (xs: Iterable<Frac>): Frac => { let t = ZERO; for (const x of xs) t = add(t, x); return t; };
/** n / d as a ratio, null when d = 0 (a zero denominator is "unknown", never 0: D-04). */
export const ratio = (n: number, d: number): Frac | null => (d === 0 ? null : fr(n, d));

/** A decimal string such as "1.959964" as an exact rational. */
export function fracOf(s: string): Frac {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(s);
  if (!m) throw malformed("decimal", `"${s}" is not a decimal string`);
  const frac = m[3] ?? "";
  const v = BigInt(`${m[2]}${frac}`);
  return fr(m[1] === "-" ? -v : v, pow10(frac.length));
}
/** ROUND_HALF_UP to `places`, once, on the unrounded value (D-P6-1); never "-0.00". */
export function q(x: Frac, places: number): string {
  return fmt(roundDiv(x.n * pow10(places), x.d), places);
}
export const q6 = (x: Frac | null): string | null => (x === null ? null : q(x, 6));

// ------------------------------------------------------------------------------------------------ fixed point
export const P = 70;
export const S = pow10(P);
export type Fx = bigint;
export const fxOf = (x: Frac): Fx => (x.n * S) / x.d;
export const fxInt = (n: number | bigint): Fx => BigInt(n) * S;
export const fxMul = (a: Fx, b: Fx): Fx => (a * b) / S;
export const fxDiv = (a: Fx, b: Fx): Fx => (a * S) / b;
export const fxQ = (x: Fx, places: number): string => fmt(roundDiv(x * pow10(places), S), places);
/** Exact rational of a fixed-point value (to hand a critical value to the exact interval code). */
export const fxFrac = (x: Fx): Frac => fr(x, S);

/** floor(sqrt(n)) by integer Newton iteration. */
export function isqrt(n: bigint): bigint {
  if (n < 2n) return n;
  let x = 1n << BigInt((n.toString(2).length + 1) >> 1);
  for (;;) {
    const y = (x + n / x) >> 1n;
    if (y >= x) return x;
    x = y;
  }
}
export const fxSqrt = (a: Fx): Fx => isqrt(a * S);
