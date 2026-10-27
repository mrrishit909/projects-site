// Display helpers. Published figures arrive as strings from the domain; these only re-lay them out (no arithmetic on a figure).
export const short = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n)}…` : s);
/** Typographic minus for a signed decimal string. */
export const minus = (s: string): string => s.replace(/^-/, "−");
/** Thousands separators inserted into the integer part of a decimal string (string handling only). */
export function group(s: string | null, empty = "n/a"): string {
  if (s === null) return empty;
  const m = /^(-?)(\d+)(\.\d+)?$/.exec(s);
  if (!m) return s;
  return `${m[1] === "-" ? "−" : ""}${m[2]!.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${m[3] ?? ""}`;
}
export const day = (iso: string): string => iso.slice(0, 10);
export const dayTime = (iso: string): string => `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`;
export const month = (isoDate: string): string => isoDate.slice(0, 7);
export const n0 = (n: number): string => n.toLocaleString("en-US");
/** An integer part-per-ten-thousand (basis points) as a CSS percentage, built with integer arithmetic only. */
export const bp = (basisPoints: number): string => { const b = Math.max(0, Math.min(10000, Math.trunc(basisPoints))); return `${Math.trunc(b / 100)}.${String(b % 100).padStart(2, "0")}%`; };
/** A period as "t (2026-03)". */
export const periodLabel = (t: number, isoDate: string | undefined): string => (isoDate ? `${t} · ${month(isoDate)}` : String(t));
