// Exact arithmetic. Durations are integer seconds, ratios are (numerator, denominator) integer pairs and every
// published figure is rounded half up from the exact quotient with BigInt: no floating point reaches a figure.

const TEN = 10n;
const pow10 = (p: number): bigint => TEN ** BigInt(p);

/** num/den as a decimal string with `places` decimals, ROUND_HALF_UP (ties away from zero) like Python's Decimal. */
export function fixed(num: bigint | number, den: bigint | number, places: number): string {
  let n = BigInt(num), d = BigInt(den);
  if (d === 0n) throw new Error("division by zero");
  if (d < 0n) { n = -n; d = -d; }
  const neg = n < 0n;
  if (neg) n = -n;
  const scaled = n * pow10(places);
  let q = scaled / d;
  if (2n * (scaled % d) >= d) q += 1n;
  const s = q.toString().padStart(places + 1, "0");
  const body = places === 0 ? s : `${s.slice(0, s.length - places)}.${s.slice(s.length - places)}`;
  return neg ? `-${body}` : body;
}

/** Minutes at 4 decimals from a number of seconds (an integer or an exact fraction secNum/secDen). */
export const d4s = (secNum: bigint | number, secDen: bigint | number = 1): string => fixed(secNum, BigInt(secDen) * 60n, 4);
/** A ratio at 6 decimals; null when the denominator is 0 (the domain's `ratio`). */
export const d6r = (num: bigint | number, den: bigint | number): string | null => (BigInt(den) === 0n ? null : fixed(num, den, 6));

/** Exact rational with a positive denominator in lowest terms (used by the simulator, whose times are decimals). */
export interface Frac { readonly n: bigint; readonly d: bigint }
const gcd = (a: bigint, b: bigint): bigint => { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b) { [a, b] = [b, a % b]; } return a; };
export function frac(n: bigint | number, d: bigint | number = 1n): Frac {
  let nn = BigInt(n), dd = BigInt(d);
  if (dd === 0n) throw new Error("zero denominator");
  if (dd < 0n) { nn = -nn; dd = -dd; }
  const g = gcd(nn, dd) || 1n;
  return { n: nn / g, d: dd / g };
}
export const ZERO: Frac = { n: 0n, d: 1n };
export const fAdd = (a: Frac, b: Frac): Frac => frac(a.n * b.d + b.n * a.d, a.d * b.d);
export const fSub = (a: Frac, b: Frac): Frac => frac(a.n * b.d - b.n * a.d, a.d * b.d);
export const fMul = (a: Frac, b: Frac): Frac => frac(a.n * b.n, a.d * b.d);
export const fDiv = (a: Frac, b: Frac): Frac => frac(a.n * b.d, a.d * b.n);
export const fCmp = (a: Frac, b: Frac): number => { const l = a.n * b.d, r = b.n * a.d; return l < r ? -1 : l > r ? 1 : 0; };
export const fMax = (a: Frac, b: Frac): Frac => (fCmp(a, b) >= 0 ? a : b);
export const fMin = (a: Frac, b: Frac): Frac => (fCmp(a, b) <= 0 ? a : b);
export const fSum = (xs: readonly Frac[]): Frac => xs.reduce(fAdd, ZERO);
export const fMean = (xs: readonly Frac[]): Frac | null => (xs.length === 0 ? null : fDiv(fSum(xs), frac(xs.length)));
/** Ceiling of a non-negative fraction. */
export const fCeil = (a: Frac): bigint => (a.n + a.d - 1n) / a.d;
/** Fraction as a Number: only for feeding the seeded generator (as Python's float()); never for a figure. */
export const fToNumber = (a: Frac): number => {
  const lim = 9007199254740991n;
  if (a.n <= lim && a.n >= -lim && a.d <= lim) return Number(a.n) / Number(a.d);
  return Number((a.n * 10n ** 30n) / a.d) / 1e30;
};
export const fixedF = (a: Frac | null, places: number): string | null => (a === null ? null : fixed(a.n, a.d, places));
export const d4f = (a: Frac | null): string | null => fixedF(a, 4);
export const d6f = (a: Frac | null): string | null => fixedF(a, 6);

/** A JSON number or decimal string ("69.1", "1e-3", 12) as an exact fraction; null when not finite/decimal. */
export function parseDecimal(v: unknown): Frac | null {
  if (typeof v === "number") { if (!Number.isFinite(v)) return null; v = String(v); }
  if (typeof v !== "string") return null;
  const m = /^\s*([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?\s*$/.exec(v) ?? /^\s*([+-]?)()\.(\d+)(?:[eE]([+-]?\d+))?\s*$/.exec(v);
  if (!m) return null;
  const frs = m[3] ?? "";
  let n = BigInt(`${m[2] || "0"}${frs}`);
  let e = (m[4] ? parseInt(m[4], 10) : 0) - frs.length;
  if (m[1] === "-") n = -n;
  return e >= 0 ? frac(n * pow10(e)) : frac(n, pow10(-e));
}
