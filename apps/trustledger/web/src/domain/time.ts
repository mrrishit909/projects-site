// Instants (UTC microseconds as BigInt, one accepted form) and the dataset's local refresh schedule (Intl, IANA names).
// Mirror of domain/trustledger/timeutil.py: a time that occurs twice (clocks going back) is the LATER instant, a time that does not
// exist (clocks going forward) uses the offset before the change; both are what PostgreSQL's `timestamp AT TIME ZONE` does.
import { ValueError } from "./errors";
import { fr, type Fr } from "./num";

export type Instant = bigint; // microseconds since 1970-01-01T00:00:00Z
const US = 1_000_000n;
const TS_FORM = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/;
const HHMM = /^([01]\d|2[0-3]):([0-5]\d)$/;

/** Days since 1970-01-01 of a proleptic Gregorian date. */
export function daysFromCivil(y: number, m: number, d: number): number {
  const yy = m <= 2 ? y - 1 : y;
  const era = Math.floor(yy / 400);
  const yoe = yy - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}
export function civilFromDays(z0: number): [number, number, number] {
  const z = z0 + 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp < 10 ? mp + 3 : mp - 9;
  return [yoe + era * 400 + (m <= 2 ? 1 : 0), m, d];
}
const leap = (y: number): boolean => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const dim = (y: number, m: number): number => [31, leap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]!;

/** `YYYY-MM-DDTHH:MM:SS[.f]` with `Z` or an offset, to UTC microseconds. Naive values are refused. */
export function parseTs(value: unknown): Instant {
  if (typeof value !== "string") throw new ValueError("timestamp must be an ISO-8601 string");
  const m = TS_FORM.exec(value);
  if (!m) throw new ValueError("timestamp must be YYYY-MM-DDTHH:MM:SS with a zone");
  const [y, mo, d, h, mi, s] = [1, 2, 3, 4, 5, 6].map((i) => Number(m[i]!)) as [number, number, number, number, number, number];
  if (y < 1 || mo < 1 || mo > 12 || d < 1 || d > dim(y, mo) || h > 23 || mi > 59 || s > 59) throw new ValueError("not a valid instant");
  const frac = BigInt((m[7] ?? "").slice(0, 6).padEnd(6, "0"));
  let off = 0;
  if (m[8] !== "Z") {
    const oh = Number(m[8]!.slice(1, 3)), om = Number(m[8]!.slice(4, 6));
    if (oh > 23 || om > 59) throw new ValueError("not a valid offset");
    off = (m[8]![0] === "-" ? -1 : 1) * (oh * 60 + om);
  }
  const secs = daysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s - off * 60;
  return BigInt(secs) * US + frac;
}
const p2 = (n: number): string => String(n).padStart(2, "0");
export function isoZ(t: Instant | null): string | null {
  if (t === null) return null;
  const secs = t / US, micro = t % US;
  const days = Math.floor(Number(secs) / 86400), rem = Number(secs) - days * 86400;
  const [y, mo, d] = civilFromDays(days);
  return `${String(y).padStart(4, "0")}-${p2(mo)}-${p2(d)}T${p2(Math.floor(rem / 3600))}:${p2(Math.floor((rem % 3600) / 60))}:${p2(rem % 60)}${micro ? `.${micro.toString().padStart(6, "0")}` : ""}Z`;
}
/** Exact hours from a to b (integer microseconds). */
export const hoursBetween = (a: Instant, b: Instant): Fr => fr(b - a, 3_600_000_000n);
export const minutes = (n: number): bigint => BigInt(n) * 60n * US;

// ---- zones -------------------------------------------------------------------------------------------------------------------
const fmts = new Map<string, Intl.DateTimeFormat>();
/** An IANA zone known to this browser's tz database; ValueError otherwise. */
export function zone(name: string): string {
  if (typeof name !== "string" || !name || name.startsWith("/") || name.includes("..")) throw new ValueError("timezone must be an IANA name");
  if (!fmts.has(name)) {
    try {
      fmts.set(name, new Intl.DateTimeFormat("en-US", { timeZone: name, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" }));
    } catch { throw new ValueError(`unknown IANA timezone '${name}'`); }
  }
  return name;
}
/** The wall clock of the zone at `ms` (UTC milliseconds), as a pseudo-UTC millisecond count at second precision. */
function wall(tz: string, ms: number): number {
  zone(tz);
  const parts = fmts.get(tz)!.formatToParts(Math.floor(ms / 1000) * 1000);
  const g = (t: string): number => Number(parts.find((p) => p.type === t)!.value);
  return Date.UTC(g("year"), g("month") - 1, g("day"), g("hour"), g("minute"), g("second"));
}
const offsetMs = (tz: string, ms: number): number => wall(tz, ms) - Math.floor(ms / 1000) * 1000;
/** The local calendar date (day number) of an instant in the zone. */
export const localDayNumber = (t: Instant, tz: string): number => Math.floor(wall(tz, Number(t / 1000n)) / 86_400_000);

export function parseHhmm(value: string): [number, number] {
  const m = typeof value === "string" ? HHMM.exec(value) : null;
  if (!m) throw new ValueError("local time must be HH:MM");
  return [Number(m[1]), Number(m[2])];
}
/** The UTC instant of day number `day` at hh:mm in the zone (later one when the time occurs twice; offset before the change when it does not exist). */
export function localToUtc(day: number, hh: number, mm: number, tz: string): Instant {
  const w = (day * 86400 + hh * 3600 + mm * 60) * 1000;
  const o1 = offsetMs(tz, w - 86_400_000), o2 = offsetMs(tz, w + 86_400_000);
  const cands = o1 === o2 ? [w - o1] : [w - o1, w - o2];
  const ok = cands.filter((c) => wall(tz, c) === w);
  return BigInt(ok.length ? Math.max(...ok) : w - o1) * 1000n;
}
/** The latest daily occurrence (local time in tz) whose grace window has closed by `asOf` (s + grace <= asOf) and its deadline. Half-open [s, s + grace). */
export function scheduledOccurrence(tz: string, localTime: string, graceMinutes: number, asOf: Instant): [Instant, Instant] {
  const [hh, mm] = parseHhmm(localTime);
  const grace = minutes(graceMinutes);
  const d0 = localDayNumber(asOf, tz);
  for (let back = -1; back < 5; back++) {
    const s = localToUtc(d0 - back, hh, mm, tz);
    if (s + grace <= asOf) return [s, s + grace];
  }
  throw new ValueError("no occurrence found");
}
