import { m4, ratio } from "../domain/num";
// Display helpers. Published figures arrive as exact strings or integers from the domain; these only re-lay them out (no arithmetic on a figure, no float).
export const short = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n)}…` : s);
export const minus = (s: string): string => s.replace(/^-/, "−");
export const day = (iso: string): string => iso.slice(0, 10);
export const hhmm = (iso: string): string => iso.slice(11, 16);
export const dayTime = (iso: string): string => `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`;
export const dayTimeS = (iso: string): string => `${iso.slice(0, 10)} ${iso.slice(11, 19)}Z`;
export const n0 = (n: number): string => n.toLocaleString("en-US");
/** Whole seconds as minutes with 4 places (the domain's m4 of seconds / 60, exact rational arithmetic): freshness, ingestion age and lag are stored and
 * published in seconds (D-09, R8-15) and shown in minutes beside them. */
export const minutes = (sec: number | null): string => (sec === null ? "n/a" : (m4(ratio(sec, 60)) ?? "n/a"));
/** Whole seconds as `3 d 1 h 2 min 3 s`-style text with integer arithmetic only (the largest two non-zero units). */
export function dur(sec: number | null): string {
  if (sec === null) return "n/a";
  const neg = sec < 0, s0 = Math.abs(sec);
  const d = Math.floor(s0 / 86400), h = Math.floor((s0 % 86400) / 3600), m = Math.floor((s0 % 3600) / 60), s = s0 % 60;
  const parts: string[] = [];
  if (d) parts.push(`${d} d`);
  if (h) parts.push(`${h} h`);
  if (m && parts.length < 2) parts.push(`${m} min`);
  if (!parts.length || (s && parts.length < 2 && !d && !h && !m)) parts.push(`${s} s`);
  return (neg ? "−" : "") + parts.slice(0, 2).join(" ");
}
const bp = (basisPoints: number): string => `${Math.floor(basisPoints / 100)}.${String(basisPoints % 100).padStart(2, "0")}%`;
/** A 6-place proportion string ("0.993200") as a CSS width, by integer arithmetic on its digits (display only). */
export function barWidth(rate: string | null): string {
  const m = rate === null ? null : /^(-?)(\d+)\.(\d{6})$/.exec(rate);
  if (!m || m[1]) return "0%";
  const ppm = Number(m[2]) * 1_000_000 + Number(m[3]);
  return bp(Math.min(10_000, Math.floor((ppm + 50) / 100)));
}
/** n out of total as a CSS width, by integer arithmetic (display only). */
export const pct = (n: number, total: number): string => (total <= 0 || n <= 0 ? "0%" : bp(Math.min(10_000, Math.floor((n * 20_000 + total) / (2 * total)))));
