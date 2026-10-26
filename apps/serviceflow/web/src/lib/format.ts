import { fixed } from "../domain/fixed";

/** Share as a percentage with one decimal from an exact ratio of integers. */
export const pct = (num: number, den: number): string => (den === 0 ? "no value" : `${fixed(BigInt(num) * 100n, den, 1)} %`);
/** A 6-decimal ratio string as a percentage with two decimals (string arithmetic on the exact digits, rounded half up). */
export const ratioToPct = (r: string | null): string | null => {
  if (r === null) return null;
  const neg = r.startsWith("-");
  const n = BigInt(r.replace("-", "").replace(".", ""));
  return `${fixed(neg ? -n : n, 10000n, 2)} %`;
};
export const dayOf = (sec: number): string => new Date(sec * 1000).toISOString().slice(0, 10);
export const hhmm = (sec: number): string => new Date(sec * 1000).toISOString().slice(11, 16);
export const stamp = (sec: number): string => `${dayOf(sec)} ${hhmm(sec)}Z`;
export const dayStart = (day: string): number => Date.parse(`${day}T00:00:00Z`) / 1000;
export const short = (s: string, n = 12): string => (s.length > n ? `${s.slice(0, n)}…` : s);
/** Whole minutes of a number of seconds, 1 decimal (display of table cells where 4 decimals add nothing). */
export const mins1 = (sec: number): string => fixed(sec, 60, 1);

export const last = <T,>(xs: readonly T[]): T | undefined => xs[xs.length - 1];
