// Exact arithmetic for the mirror of domain/invoicebridge/money.py: BigInt only, no floating point in any figure.
// Scales: money = cents (1e-2), quantity = ten-thousandths (1e-4), unit price and rate = millionths (1e-6).
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
export const MAX_ABS = 10n ** 12n; // contract.MAX_ABS

/** n / d rounded half away from zero (Python ROUND_HALF_UP), d > 0. */
export function roundDiv(n: bigint, d: bigint): bigint {
  const neg = n < 0n;
  const a = neg ? -n : n;
  let q = a / d;
  if (2n * (a % d) >= d) q += 1n;
  return neg ? -q : q;
}
/** Re-scale a fixed-point integer from `from` to `to` decimals, half up. */
export const rescale = (v: bigint, from: number, to: number): bigint => (to >= from ? v * pow10(to - from) : roundDiv(v, pow10(from - to)));

/** Scaled integer as a decimal string with exactly `dp` decimals. */
export function fmt(v: bigint, dp: number): string {
  const neg = v < 0n;
  const s = (neg ? -v : v).toString().padStart(dp + 1, "0");
  const out = dp === 0 ? s : `${s.slice(0, s.length - dp)}.${s.slice(s.length - dp)}`;
  return neg ? `-${out}` : out;
}
/** num/den rounded half up to `places` decimals as a string (money.frac_str). */
export function fracStr(num: bigint, den: bigint, places: number): string {
  const scale = pow10(places);
  const a = (num < 0n ? -num : num) * scale;
  let q = a / den;
  if (2n * (a % den) >= den) q += 1n;
  const neg = num < 0n && q !== 0n;
  return `${neg ? "-" : ""}${fmt(q, places)}`;
}

// ASCII digits only (R5-17): no underscores, exponents or non-ASCII digits, the same spelling as money.DECIMAL_TEXT in Python.
const DEC = /^([+-]?)([0-9]*)(?:\.([0-9]*))?$/;
/** A JSON string (or integer) as a fixed-point BigInt at `dp` decimals. Over-long non-zero fractions, floats and
 *  out-of-range values are refused, not rounded (money.dec). */
export function parseDec(value: unknown, name: string, dp: number): bigint {
  let s: string;
  if (typeof value === "string") s = value.trim();
  else if (typeof value === "number" && Number.isSafeInteger(value)) s = String(value);
  else throw malformed(name, "must be a decimal string");
  const m = DEC.exec(s);
  if (!m || ((m[2] ?? "") === "" && (m[3] ?? "") === "")) throw malformed(name, "is not a decimal number");
  let frac = m[3] ?? "";
  if (frac.length > dp) {
    if (/[1-9]/.test(frac.slice(dp))) throw malformed(name, `carries more than ${dp} decimals`);
    frac = frac.slice(0, dp);
  }
  let v = BigInt(`${m[2] || "0"}${frac.padEnd(dp, "0")}`);
  if (m[1] === "-") v = -v;
  if ((v < 0n ? -v : v) >= MAX_ABS * pow10(dp)) throw malformed(name, "is out of range");
  return v;
}

export const s2 = (cents: bigint): string => fmt(cents, 2);
export const s4q = (q4: bigint): string => fmt(q4, 4);
/** Value at scale 10 (quantity 1e-4 x price 1e-6) as money, half up. */
export const money10 = (v: bigint): bigint => roundDiv(v, 100_000_000n);
export const absB = (v: bigint): bigint => (v < 0n ? -v : v);
export const maxB = (a: bigint, b: bigint): bigint => (a > b ? a : b);
export const sumB = (xs: Iterable<bigint>): bigint => { let t = 0n; for (const x of xs) t += x; return t; };
