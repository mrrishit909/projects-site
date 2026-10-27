// Instants: UTC, one accepted form (`YYYY-MM-DDTHH:MM:SS[.f]` with `Z` or an offset). An instant is an exact integer count of microseconds
// since 1970-01-01T00:00:00Z (a BigInt): no Date object and no floating point in any comparison or difference.
const TS_FORM = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/;
const US = 1_000_000n, DAY_US = 86_400n * US;

/** Days since 1970-01-01 of a proleptic Gregorian civil date (Howard Hinnant's algorithm, integers only). */
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
  const y = yoe + era * 400;
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp + (mp < 10 ? 3 : -9);
  return [y + (m <= 2 ? 1 : 0), m, d];
}
const isLeap = (y: number): boolean => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const dim = (y: number, m: number): number => [31, isLeap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]!;

const memo = new Map<string, bigint>();
/** Parse an instant to UTC microseconds. Naive values and other forms are refused with a RangeError (Python: ValueError). */
export function parseTs(value: unknown): bigint {
  if (typeof value === "bigint") return value;
  if (typeof value !== "string") throw new RangeError("timestamp must be an ISO-8601 string");
  const hit = memo.get(value);
  if (hit !== undefined) return hit;
  const m = TS_FORM.exec(value);
  if (!m) throw new RangeError("timestamp must be YYYY-MM-DDTHH:MM:SS with a zone");
  const [y, mo, d, h, mi, s] = [1, 2, 3, 4, 5, 6].map((i) => Number(m[i]!)) as [number, number, number, number, number, number];
  if (y < 1) throw new RangeError("year is out of range");
  if (mo < 1 || mo > 12) throw new RangeError("month must be in 1..12");
  if (d < 1 || d > dim(y, mo)) throw new RangeError("day is out of range for month");
  if (h > 23) throw new RangeError("hour must be in 0..23");
  if (mi > 59) throw new RangeError("minute must be in 0..59");
  if (s > 59) throw new RangeError("second must be in 0..59");
  const frac = m[7] === undefined ? 0n : BigInt((m[7] + "000000").slice(0, 6));      // digits beyond microseconds are truncated
  let off = 0n;
  if (m[8] !== "Z") {
    const oh = Number(m[8]!.slice(1, 3)), om = Number(m[8]!.slice(4, 6));
    if (oh > 23 || om > 59) throw new RangeError("offset is out of range");
    off = BigInt((oh * 60 + om) * 60) * US * (m[8]![0] === "-" ? -1n : 1n);
  }
  const t = BigInt(daysFromCivil(y, mo, d)) * DAY_US + BigInt((h * 60 + mi) * 60 + s) * US + frac - off;
  memo.set(value, t);
  return t;
}
const pad = (n: number | bigint, w: number): string => String(n).padStart(w, "0");
/** The instant as `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` (fraction only when non-zero), or null. */
export function isoZ(v: bigint | string | null | undefined): string | null {
  if (v === null || v === undefined) return null;
  const t = typeof v === "bigint" ? v : parseTs(v);
  const days = t >= 0n ? t / DAY_US : -((-t + DAY_US - 1n) / DAY_US);
  const rem = t - days * DAY_US;
  const [y, m, d] = civilFromDays(Number(days));
  const secs = rem / US, us = rem % US;
  const hh = secs / 3600n, mm = (secs % 3600n) / 60n, ss = secs % 60n;
  return `${pad(y, 4)}-${pad(m, 2)}-${pad(d, 2)}T${pad(hh, 2)}:${pad(mm, 2)}:${pad(ss, 2)}${us ? `.${pad(us, 6)}` : ""}Z`;
}
const floorDiv = (a: bigint, b: bigint): bigint => { const q = a / b; return (a % b !== 0n && (a < 0n) !== (b < 0n)) ? q - 1n : q; };
/** Whole seconds from a to b (floor, integer arithmetic on microseconds), as in timedelta.days * 86400 + timedelta.seconds. */
export const secondsBetween = (a: bigint | string, b: bigint | string): number => Number(floorDiv(parseTs(b) - parseTs(a), US));
export const microsBetween = (a: bigint | string, b: bigint | string): bigint => parseTs(b) - parseTs(a);
/** The UTC date (the partition of a timestamp, D-P8-02). */
export const utcDate = (v: bigint | string): string => isoZ(floorDiv(parseTs(v), DAY_US) * DAY_US)!.slice(0, 10);
/** The daily UTC partitions of the half-open range [start, end): each is the date of a start + k days that is before the end. */
export function dayPartitions(start: bigint | string, end: bigint | string): string[] {
  let cur = parseTs(start);
  const stop = parseTs(end), out: string[] = [];
  while (cur < stop) { out.push(isoZ(cur)!.slice(0, 10)); cur += DAY_US; }
  return out;
}
export const MICROS = { second: US, day: DAY_US };
