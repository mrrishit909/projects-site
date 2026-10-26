// Fixed-point helpers. Units are integers, money is a decimal string with 2 places held as BigInt cents, rates come
// from exact integer ratios (Rat) and are rounded half-up to 6 places. No floating point touches a figure.
import type { CostVersion } from "./types";
import { dayOf } from "./time";

export interface Rat { readonly num: bigint; readonly den: bigint } // den > 0
/** A terminating decimal: n / 10^s. Scale is never normalised, so addition and multiplication stay exact and cheap. */
export interface Dec { readonly n: bigint; readonly s: number }

const P10: bigint[] = [1n];
export function pow10(k: number): bigint {
  while (P10.length <= k) P10.push(P10[P10.length - 1]! * 10n);
  return P10[k]!;
}

// ---- rounding and formatting ------------------------------------------------------------------------------------
/** round(num / den) half away from zero (Decimal ROUND_HALF_UP); den > 0. */
export function roundHalfUp(num: bigint, den: bigint): bigint {
  const neg = num < 0n;
  const a = neg ? -num : num;
  const q = (2n * a + den) / (2n * den);
  return neg ? -q : q;
}
/** An integer scaled by 10^dp as text: 1250n, 2 -> "12.50". */
export function fmtScaled(v: bigint, dp: number): string {
  const neg = v < 0n;
  const digits = (neg ? -v : v).toString().padStart(dp + 1, "0");
  const body = dp === 0 ? digits : `${digits.slice(0, -dp)}.${digits.slice(-dp)}`;
  return neg ? `-${body}` : body;
}
export const ratio = (num: number | bigint, den: number | bigint): Rat | null => {
  const d = BigInt(den);
  return d === 0n ? null : d < 0n ? { num: -BigInt(num), den: -d } : { num: BigInt(num), den: d };
};
export function ratStr(r: Rat | null, dp: number): string | null {
  return r === null ? null : fmtScaled(roundHalfUp(r.num * pow10(dp), r.den), dp);
}
export const d2 = (r: Rat | null): string | null => ratStr(r, 2);
export const d6 = (r: Rat | null): string | null => ratStr(r, 6);
export const ratCmp = (a: Rat, b: Rat): number => { const l = a.num * b.den, r = b.num * a.den; return l < r ? -1 : l > r ? 1 : 0; };

// ---- money ------------------------------------------------------------------------------------------------------
const MONEY = /^\+?(\d+)(?:\.(\d+))?$/;
/** A non-negative amount with at most 2 decimals (more only as zeros), from a string or integer; never a float. */
export function parseMoney(v: unknown): string {
  if (typeof v === "number") {
    if (!Number.isInteger(v)) throw new Error("money must be a decimal string");
    if (v < 0) throw new Error("money must not be negative");
    return fmtScaled(BigInt(v) * 100n, 2);
  }
  const m = typeof v === "string" ? MONEY.exec(v.trim()) : null;
  if (!m) throw new Error("money must be a decimal string");
  const frac = m[2] ?? "";
  if (/[1-9]/.test(frac.slice(2))) throw new Error("money must have at most 2 decimals");
  return fmtScaled(BigInt(m[1]!) * 100n + BigInt(frac.slice(0, 2).padEnd(2, "0")), 2);
}
export const cents = (s: string): bigint => BigInt(s.replace(".", ""));
export const fmtCents = (c: bigint): string => fmtScaled(c, 2);
/** Negative stock is never valued: it counts as zero. */
export const onHandValue = (onHand: number, unitCost: string): bigint => BigInt(Math.max(onHand, 0)) * cents(unitCost);

/** The unit cost on day `onDay`: the latest cost version effective on or before it, else the product's base cost. */
export function costInForce(base: string, versions: readonly CostVersion[], onDay: number): string {
  let best: CostVersion | null = null;
  for (const v of versions) {
    if (dayOf(v.effective_from) <= onDay && (best === null || v.effective_from > best.effective_from ||
        (v.effective_from === best.effective_from && v.cost_version_id > best.cost_version_id))) best = v;
  }
  return best ? best.unit_cost : base;
}

// ---- decimals ---------------------------------------------------------------------------------------------------
export const decInt = (n: number): Dec => ({ n: BigInt(n), s: 0 });
export function parseDec(text: string): Dec {
  const m = MONEY.exec(text.trim());
  if (!m) throw new Error("not a decimal");
  const frac = m[2] ?? "";
  return { n: BigInt(m[1]! + frac), s: frac.length };
}
const up = (d: Dec, s: number): bigint => (d.s === s ? d.n : d.n * pow10(s - d.s));
export const decAdd = (a: Dec, b: Dec): Dec => { const s = Math.max(a.s, b.s); return { n: up(a, s) + up(b, s), s }; };
export const decSub = (a: Dec, b: Dec): Dec => { const s = Math.max(a.s, b.s); return { n: up(a, s) - up(b, s), s }; };
export const decMul = (a: Dec, b: Dec): Dec => ({ n: a.n * b.n, s: a.s + b.s });
export const decAbs = (a: Dec): Dec => (a.n < 0n ? { n: -a.n, s: a.s } : a);
export const decToRat = (d: Dec): Rat => ({ num: d.n, den: pow10(d.s) });
export const decDivInt = (d: Dec, k: number): Rat => ({ num: d.n, den: pow10(d.s) * BigInt(k) });
export function decCeil(d: Dec): bigint {
  const p = pow10(d.s);
  const q = d.n / p; // truncates toward zero
  return d.n > 0n && d.n % p !== 0n ? q + 1n : q;
}
/** Text with `dp` places, rounded half-up. */
export const decStr = (d: Dec, dp: number): string => fmtScaled(roundHalfUp(d.n * pow10(dp), pow10(d.s)), dp);
