// Display helpers shared by the views. Durations arrive from the domain as exact 4-decimal strings and are
// never re-derived here; Number() is used only to place marks on a chart or to sort.
import { isoZ } from "../domain/time";

export const stamp = (ms: number | null): string => (ms === null ? "open" : isoZ(ms).replace("T", " ").replace("Z", " UTC"));
export const day = (ms: number): string => isoZ(ms).slice(5, 10);
export const hoursOrNa = (h: string | null | undefined): string => (h === null || h === undefined ? "n/a" : h);
export const hoursNum = (h: string): number => Number(h);
export const percent = (num: number, den: number): string => (den === 0 ? "n/a" : `${((num / den) * 100).toFixed(1)}%`);
export const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
export const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
export const label = (s: string): string => s.replace(/_/g, " ");

/** Hours shown as a short human duration for gap labels (display only). */
export const spanText = (ms: number): string => {
  const h = ms / 3_600_000;
  return h >= 48 ? `${(h / 24).toFixed(1)} days` : `${h.toFixed(1)} h`;
};
