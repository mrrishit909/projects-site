// Display helpers. Published figures arrive as strings from the domain; these only re-lay them out (no arithmetic on a figure).
export const short = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n)}…` : s);
/** Typographic minus for a signed decimal string. */
export const minus = (s: string): string => s.replace(/^-/, "−");
export const day = (iso: string): string => iso.slice(0, 10);
export const dayTime = (iso: string): string => `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`;
export const n0 = (n: number): string => n.toLocaleString("en-US");
/** A proportion string as a CSS width (display only). */
export const barWidth = (rate: string | null): string => (rate === null ? "0%" : `${Math.max(0, Math.min(100, Number(rate) * 100)).toFixed(2)}%`);
/** A cell value shown so that whitespace and nulls are visible: `null`, `"  "`, `"abc"`. */
export const show = (v: unknown): string => (v === undefined ? "(absent)" : JSON.stringify(v));
/** Label codes of the labelled figures, in words. */
export const LABELS: Record<string, string> = {
  validity_populated_only: "populated-only validity (passing ÷ populated)",
  validity_all_eligible: "all-eligible validity (passing ÷ eligible)",
  duplicate_group_share: "duplicate-group share (keys with more than one row ÷ distinct keys)",
  duplicate_row_share: "duplicate-row share (rows beyond the first ÷ eligible rows)",
};
