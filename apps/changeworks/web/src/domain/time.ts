// Calendar (D-04): integer periods from 0 with a `period_basis` and a `period_start` date; ranges half-open; instants UTC with Z.
// An instant is a BigInt count of microseconds since 1970-01-01T00:00:00Z, so comparisons are exact and fractional seconds keep their order.
import { DomainError, type Row } from "./contract";

export type Instant = bigint;
const TS = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$/;
const US = 1_000_000n;

/** Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant's algorithm), integer arithmetic only. */
export function daysFromCivil(y: number, m: number, d: number): number {
  y -= m <= 2 ? 1 : 0;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}
export function civilFromDays(z: number): [number, number, number] {
  z += 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const y = yoe + era * 400;
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp + (mp < 10 ? 3 : -9);
  return [y + (m <= 2 ? 1 : 0), m, d];
}
const leap = (y: number): boolean => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
export const daysInMonth = (y: number, m: number): number => [31, leap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]!;
const validDate = (y: number, m: number, d: number): boolean => y >= 1 && y <= 9999 && m >= 1 && m <= 12 && d >= 1 && d <= daysInMonth(y, m);

export function isTs(s: unknown): boolean {
  if (typeof s !== "string") return false;
  const m = TS.exec(s);
  if (!m) return false;
  const [y, mo, d, h, mi, se] = [1, 2, 3, 4, 5, 6].map((i) => Number(m[i]));
  return validDate(y!, mo!, d!) && h! < 24 && mi! < 60 && se! < 60;
}
export function parseTs(s: unknown): Instant {
  if (!isTs(s)) throw new RangeError(`not a UTC instant with Z: ${String(s)}`);
  const m = TS.exec(s as string)!;
  const [y, mo, d, h, mi, se] = [1, 2, 3, 4, 5, 6].map((i) => Number(m[i]));
  const frac = BigInt((m[7] ?? "").padEnd(6, "0") || "0");
  const secs = BigInt(daysFromCivil(y!, mo!, d!)) * 86400n + BigInt(h! * 3600 + mi! * 60 + se!);
  return secs * US + frac;
}
const two = (n: number): string => String(n).padStart(2, "0");
/** The instant as `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`, trailing zeros of the fraction dropped. */
export function isoZ(t: Instant | null): string | null {
  if (t === null) return null;
  const secs = t >= 0n ? t / US : -((-t + US - 1n) / US);
  const micro = Number(t - secs * US);
  const days = Math.floor(Number(secs) / 86400);
  const rem = Number(secs) - days * 86400;
  const [y, m, d] = civilFromDays(days);
  const base = `${String(y).padStart(4, "0")}-${two(m)}-${two(d)}T${two(Math.floor(rem / 3600))}:${two(Math.floor((rem % 3600) / 60))}:${two(rem % 60)}`;
  return base + (micro ? `.${String(micro).padStart(6, "0").replace(/0+$/, "")}` : "") + "Z";
}
/** The instant to whole seconds (strftime "%Y-%m-%dT%H:%M:%SZ"). */
export function isoSeconds(t: Instant): string { const s = isoZ(t - (t % US + US) % US)!; return s; }

export interface Config { period_basis: string; period_start: string; as_of: string | null }
export interface Ymd { y: number; m: number; d: number }

/** R9-14: a period start is a real calendar date whose day is at most 28, so the same day exists in every month and every year (PERIOD_START_INVALID). */
export function checkPeriodStart(s: unknown): void {
  const m = typeof s === "string" ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(s) : null;
  if (!m || !validDate(Number(m[1]), Number(m[2]), Number(m[3]))) throw new DomainError("PERIOD_START_INVALID", `period_start must be a calendar date YYYY-MM-DD, got ${JSON.stringify(s)}`, {});
  if (Number(m[3]) > 28) throw new DomainError("PERIOD_START_INVALID", `period_start day must be at most 28 so that every month has it, got ${String(s)}`, { day: Number(m[3]) });
}

/** `period_start` of period `t` (the start of the half-open period [t, t+1)); throws when the calendar date does not exist. */
export function periodDate(config: Row, t: number): Ymd {
  const m0 = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(config["period_start"]));
  if (!m0) throw new RangeError("period_start is not a date");
  const [sy, sm, sd] = [Number(m0[1]), Number(m0[2]), Number(m0[3])] as [number, number, number];
  let y: number, mo: number;
  if (config["period_basis"] === "annual") { y = sy + t; mo = sm; }
  else { const mm = sm - 1 + t; y = sy + Math.floor(mm / 12); mo = (mm % 12) + 1; }
  if (!validDate(y, mo, sd)) throw new RangeError("period date out of range");
  return { y, m: mo, d: sd };
}
export const isoDate = (d: Ymd): string => `${String(d.y).padStart(4, "0")}-${two(d.m)}-${two(d.d)}`;
const instantOf = (d: Ymd): Instant => BigInt(daysFromCivil(d.y, d.m, d.d)) * 86400n * US;
export const periodStartInstant = (config: Row, t: number): Instant => instantOf(periodDate(config, t));
export const periodEndInstant = (config: Row, t: number): Instant => instantOf(periodDate(config, t + 1));
/** A period is matured when its end (the start of period t+1) is <= as_of (D-P9-22). */
export function matured(config: Row, t: number, asOf: Instant): boolean {
  try { return periodEndInstant(config, t) <= asOf; } catch { return false; }
}
/** How many leading periods are matured, looking at no more than `cap` periods. */
export function maturedCount(config: Row, asOf: Instant, cap: number): number {
  let n = 0;
  while (n < cap && matured(config, n, asOf)) n++;
  return n;
}
