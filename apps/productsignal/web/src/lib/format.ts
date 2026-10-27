// Display helpers. Published figures arrive as strings from the domain; these only re-lay them out (no arithmetic on a figure).
export const short = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n)}…` : s);
/** Typographic minus for a signed decimal string. */
export const minus = (s: string): string => s.replace(/^-/, "−");
/** "0.315000" -> "31.50 %" by moving the decimal point in the string. */
export function pct(rate: string | null): string {
  if (rate === null) return "n/a";
  const m = /^(-?)(\d+)\.(\d+)$/.exec(rate);
  if (!m) return rate;
  const frac = m[3]!.padEnd(4, "0");
  const whole = `${m[2]}${frac.slice(0, 2)}`.replace(/^0+(?=\d)/, "");
  return `${m[1] ? "\u2212" : ""}${whole}.${frac.slice(2, 4)} %`;
}
/** "9.50" -> "+9.50 pp"; "-4.50" -> "−4.50 pp"; null -> "n/a". */
export const pp = (v: string | null): string => (v === null ? "n/a" : v.startsWith("-") ? `−${v.slice(1)} pp` : `+${v} pp`);
/** A proportion string as a CSS width (display only). */
export const barWidth = (rate: string | null): string => (rate === null ? "0%" : `${Math.max(0, Math.min(100, Number(rate) * 100)).toFixed(2)}%`);
export const day = (iso: string): string => iso.slice(0, 10);
export const n0 = (n: number): string => n.toLocaleString("en-US");
