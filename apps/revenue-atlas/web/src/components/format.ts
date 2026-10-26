// Display formatting on exact decimal strings (no floats on money). Negative values keep a leading minus.
import * as D from "../domain/decimal";

/** "1234567.5" -> "1,234,567.50"; "-12" -> "-12.00". Input is a decimal string from the pipeline. */
export function fmtMoney(s: string | null | undefined, scale = 2): string {
  if (s === null || s === undefined) return "n/a";
  const t = D.fixed(D.parse(s), scale);
  const neg = t.startsWith("-");
  const [int = "0", frac] = (neg ? t.slice(1) : t).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const body = frac === undefined ? grouped : `${grouped}.${frac}`;
  return neg && /[1-9]/.test(body) ? `-${body}` : body;
}
export const fmtDec = (x: D.Dec, scale = 2): string => fmtMoney(D.toString(x), scale);

/** A proportion string ("0.311111") as a percentage with two decimals ("31.11%"); null is "n/a". */
export function fmtRate(s: string | null | undefined): string {
  if (s === null || s === undefined) return "n/a";
  return `${D.fixed(D.mul(D.parse(s), D.fromInt(100)), 2)}%`;
}

/** Plot-only conversion (positions, never shown as a figure). */
export const toNumber = (s: string): number => Number(s);

export const fmtInt = (n: number): string => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** "2026-03" -> "Mar 2026". */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  return `${MONTHS[Number(m) - 1] ?? m} ${y}`;
}
/** Every month key from `from` to `to` inclusive ("YYYY-MM"). */
export function monthRange(from: string, to: string): string[] {
  const out: string[] = [];
  let [y, m] = from.split("-").map(Number) as [number, number];
  const [ty, tm] = to.split("-").map(Number) as [number, number];
  while (y < ty || (y === ty && m <= tm)) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
  return out;
}
