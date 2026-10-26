// Display helpers shared by the views. Figures arrive from the domain as exact integers or decimal strings and are never
// re-derived here; Number() is used only to place marks on a chart.
import { fmtScaled, roundHalfUp } from "../domain/money";
import { dayStr, isoZ } from "../domain/time";

export const int = (n: number | null | undefined): string => (n === null || n === undefined ? "n/a" : n.toLocaleString("en-US"));
/** "29090.64" -> "$29,090.64" (a decimal string, grouped without going through a float). */
export function usd(s: string | null): string {
  if (s === null) return "n/a";
  const [whole = "", frac] = s.split(".");
  const neg = whole.startsWith("-");
  const digits = (neg ? whole.slice(1) : whole).replace(/\B(?=(\d{3})+$)/g, ",");
  return `${neg ? "-" : ""}$${digits}${frac ? `.${frac}` : ""}`;
}
/** A 6 dp rate string as a percentage with `dp` places, rounded half-up: "0.932486" -> "93.2%". */
export function pct(rate: string | null, dp = 1): string {
  if (rate === null) return "n/a";
  const v = BigInt(rate.replace(".", "")); // scaled by 10^6
  return `${fmtScaled(roundHalfUp(v * 100n * 10n ** BigInt(dp), 10n ** 6n), dp)}%`;
}
export const stamp = (ms: number): string => isoZ(ms).replace("T", " ").replace("Z", " UTC");
export const dayLabel = (day: number): string => dayStr(day);
export const label = (s: string): string => s.replace(/_/g, " ");
export const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
