// Published number formats (docs/contracts.md D-04): proportions and scores are 6-place decimal strings, percentage points 2 places,
// money 2 places, ROUND_HALF_UP, null means unknown, censored or a zero denominator, never 0.
// Every ratio is an exact rational over BigInt; there is no floating point in any figure this module produces or compares.
export interface Fr { readonly n: bigint; readonly d: bigint }

const gcd = (a: bigint, b: bigint): bigint => { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b) { [a, b] = [b, a % b]; } return a; };
export function fr(n: bigint | number, d: bigint | number = 1n): Fr {
  let nn = BigInt(n), dd = BigInt(d);
  if (dd === 0n) throw new RangeError("zero denominator");
  if (dd < 0n) { nn = -nn; dd = -dd; }
  const g = gcd(nn, dd) || 1n;
  return { n: nn / g, d: dd / g };
}
/** Knuth's addition: the gcd is taken between the denominators first, so a sum with a huge denominator stays cheap. */
export function add(a: Fr, b: Fr): Fr {
  if (a.d === b.d) return fr(a.n + b.n, a.d);
  const g = gcd(a.d, b.d);
  const ad = a.d / g, bd = b.d / g;
  const n = a.n * bd + b.n * ad;
  const g2 = gcd(n, g) || 1n;
  return { n: n / g2, d: ad * (b.d / g2) };
}
export const neg = (a: Fr): Fr => ({ n: -a.n, d: a.d });
export const sub = (a: Fr, b: Fr): Fr => add(a, neg(b));
export function mul(a: Fr, b: Fr): Fr {
  const g1 = gcd(a.n, b.d) || 1n, g2 = gcd(b.n, a.d) || 1n;
  return { n: (a.n / g1) * (b.n / g2), d: (a.d / g2) * (b.d / g1) };
}
export function div(a: Fr, b: Fr): Fr {
  if (b.n === 0n) throw new RangeError("zero denominator");
  return mul(a, b.n < 0n ? { n: -b.d, d: -b.n } : { n: b.d, d: b.n });
}
export const cmpFr = (a: Fr, b: Fr): number => { const l = a.n * b.d, r = b.n * a.d; return l < r ? -1 : l > r ? 1 : 0; };
export const eqFr = (a: Fr, b: Fr): boolean => a.n === b.n && a.d === b.d;
export const sumFr = (xs: readonly Fr[]): Fr => xs.reduce(add, fr(0));
export const isZero = (a: Fr): boolean => a.n === 0n;
export const ZERO: Fr = { n: 0n, d: 1n };
export const ONE: Fr = { n: 1n, d: 1n };

const RATIONAL = /^([+-]?)(?=\d|\.\d)(\d+(?:_\d+)*)?(?:\s*\/\s*(\d+(?:_\d+)*)|(?:\.(\d+(?:_\d+)*)?)?(?:[eE]([+-]?\d+(?:_\d+)*))?)$/;
/** The exact value of a decimal or rational string as Python's `Fraction(str)` reads it ("0.25", "1e-3", "3/4", " 2 "). Throws on anything else. */
export function parseFraction(s: string, allowSlash = true): Fr {
  const m = RATIONAL.exec(s.trim());
  if (!m) throw new RangeError(`not a number: ${s}`);
  const [, sign, whole, denom, frac, exp] = m;
  const clean = (x: string | undefined): string => (x ?? "").replace(/_/g, "");
  if (denom !== undefined) {
    if (!allowSlash) throw new RangeError(`not a decimal: ${s}`);
    const d = BigInt(clean(denom));
    if (d === 0n) throw new RangeError("zero denominator");
    return fr(BigInt((sign === "-" ? "-" : "") + (clean(whole) || "0")), d);
  }
  const f = clean(frac);
  let n = BigInt(`${clean(whole) || "0"}${f}`), d = 10n ** BigInt(f.length);
  if (exp !== undefined) { const e = BigInt(clean(exp)); if (e >= 0n) n *= 10n ** e; else d *= 10n ** -e; }
  return fr(sign === "-" ? -n : n, d);
}
/** An exact decimal string ("0.250000") as a rational (no fractions of the form 3/4). */
export const fracOfDec = (s: string): Fr => parseFraction(s, false);
/** The exact rational value of a JSON number (an IEEE double is a dyadic rational); used only for numbers that arrive as inputs. */
export function fracOfNumber(x: number): Fr {
  if (!Number.isFinite(x)) throw new RangeError("not finite");
  if (Number.isInteger(x)) return fr(BigInt(x));
  const dv = new DataView(new ArrayBuffer(8));
  dv.setFloat64(0, x);
  const hi = dv.getUint32(0), lo = dv.getUint32(4);
  const sign = hi >>> 31 ? -1n : 1n;
  const e = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let exp: number;
  if (e === 0) exp = -1074; else { mant |= 1n << 52n; exp = e - 1075; }
  return exp >= 0 ? fr(sign * (mant << BigInt(exp))) : fr(sign * mant, 1n << BigInt(-exp));
}
/** `Fraction(value)` for a JSON value: string, number or boolean. */
export function toFraction(v: unknown): Fr {
  if (typeof v === "string") return parseFraction(v);
  if (typeof v === "number") return fracOfNumber(v);
  if (typeof v === "boolean") return fr(v ? 1 : 0);
  throw new TypeError("not a number");
}

/** ROUND_HALF_UP of an exact rational to `dp` places, as a string (sign kept, no negative zero). */
export function rnd(x: Fr, dp: number): string {
  const neg = x.n < 0n;
  const absn = neg ? -x.n : x.n;
  const scale = 10n ** BigInt(dp);
  const n = (absn * scale * 2n + x.d) / (2n * x.d);
  const whole = n / scale, frac = n % scale;
  const s = dp ? `${whole}.${frac.toString().padStart(dp, "0")}` : String(whole);
  return (neg && n !== 0n ? "-" : "") + s;
}
export const p6 = (x: Fr | null): string | null => (x === null ? null : rnd(x, 6));
/** A difference of proportions in percentage points with 2 places. */
export const pp2 = (diff: Fr | null): string | null => (diff === null ? null : rnd(mul(diff, fr(100)), 2));
/** `Decimal.quantize(10^-dp, ROUND_HALF_UP)` of an exact value: like Python's Decimal a negative amount that rounds to zero keeps its sign ("-0.00"). */
export function quant(x: Fr, dp: number): string {
  const s = rnd({ n: x.n < 0n ? -x.n : x.n, d: x.d }, dp);
  return (x.n < 0n ? "-" : "") + s;
}
/** USD with 2 places, ROUND_HALF_UP. */
export const money = (x: Fr): string => quant(x, 2);
/** num/den, or null when the denominator is zero (unknown, never 0). */
export const ratio = (num: number, den: number): Fr | null => (den === 0 ? null : fr(num, den));

// ------------------------------------------------------------------------------------------------ the natural logarithm
// Deterministic and exact enough for any 6- or 10-place figure: fixed-point BigInt arithmetic at 10^90, atanh series, no Math.log.
export const SCALE_DIGITS = 90;
const SCALE = 10n ** BigInt(SCALE_DIGITS);
function atanhSeries(zNum: bigint, zDen: bigint): bigint {
  // 2 * atanh(z) = 2 * sum z^(2i+1) / (2i+1), z = zNum / zDen, in fixed point
  const z = (zNum * SCALE) / zDen;
  const z2 = (z * z) / SCALE;
  let term = z, sum = 0n;
  for (let i = 0n; term !== 0n; i++) { sum += term / (2n * i + 1n); term = (term * z2) / SCALE; }
  return 2n * sum;
}
const LN2 = atanhSeries(1n, 3n);
/** ln(x) for a positive rational, scaled by 10^90 (truncated). ln(1) is exactly 0. */
export function lnScaled(x: Fr): bigint {
  if (x.n <= 0n) throw new RangeError("ln of a non-positive number");
  // x = m * 2^k with m in [3/4, 3/2): ln x = k ln 2 + 2 atanh((m-1)/(m+1))
  let n = x.n, d = x.d, k = 0n;
  while (n * 4n < d * 3n) { n *= 2n; k -= 1n; }
  while (n * 2n >= d * 3n) { d *= 2n; k += 1n; }
  return k * LN2 + atanhSeries(n - d, n + d);
}
/** A scaled (10^60) value as a decimal string with `dp` places, ROUND_HALF_UP (away from zero). */
export function scaledToString(v: bigint, dp: number): string {
  return quant({ n: v, d: SCALE }, dp);
}
/** (a - e) x ln(a / e), scaled by 10^90: one term of the population stability index. */
export function psiTermScaled(a: Fr, e: Fr): bigint {
  const diff = sub(a, e);
  if (isZero(diff)) return 0n;
  return (diff.n * lnScaled(div(a, e))) / diff.d;
}
/** A scaled value quantized to `dp` places (ROUND_HALF_UP) and printed as Python prints a `Decimal`: plain notation while the adjusted exponent is at
 * least -6, scientific ("0E-10", "1.2E-9") below that. The population stability index publishes each bin's term this way. */
export function scaledToDecimalStr(v: bigint, dp: number): string {
  const neg = v < 0n;
  const c = (((neg ? -v : v) * 10n ** BigInt(dp) * 2n + SCALE) / (2n * SCALE));
  const sign = neg && c !== 0n ? "-" : "";
  const digits = c.toString();
  const adjusted = -dp + digits.length - 1;
  if (c === 0n) return dp === 0 ? "0" : adjusted >= -6 ? `0.${"0".repeat(dp)}` : `0E-${dp}`;
  if (adjusted >= -6) {
    if (digits.length > dp) return `${sign}${digits.slice(0, digits.length - dp)}.${digits.slice(digits.length - dp)}`;
    return `${sign}0.${"0".repeat(dp - digits.length)}${digits}`;
  }
  return `${sign}${digits[0]}${digits.length > 1 ? `.${digits.slice(1)}` : ""}E${adjusted < 0 ? "-" : "+"}${Math.abs(adjusted)}`;
}
export const SCALED_ONE = SCALE;
export const scaledOfFr = (x: Fr): bigint => (x.n * SCALE) / x.d;
