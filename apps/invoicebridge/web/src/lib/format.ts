export const short = (s: string, n = 12): string => (s.length > n ? `${s.slice(0, n)}…` : s);
/** "2026-10-01T02:00:00Z" as "2026-10-01 02:00Z". */
export const stamp = (iso: string): string => `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`;
export const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
/** Share of two integers as a percentage with one decimal, from integer arithmetic (no float). */
export function pct(num: number, den: number): string {
  if (den === 0) return "no value";
  const t = Math.floor((num * 1000 * 2 + den) / (den * 2)); // half up, tenths of a percent
  return `${Math.floor(t / 10)}.${t % 10} %`;
}
export const plural = (n: number, one: string, many = `${one}s`): string => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
