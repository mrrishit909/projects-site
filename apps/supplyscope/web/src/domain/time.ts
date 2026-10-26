// Instants are UTC epoch milliseconds; dates are "YYYY-MM-DD" strings or whole day numbers (days since 1970-01-01).
// A fraction of a second finer than a millisecond is truncated (the published data has whole seconds).
export const DAY_MS = 86_400_000;
export const SECOND_MS = 1000;

export const dayOf = (ms: number): number => Math.floor(ms / DAY_MS);
export const dayStart = (day: number): number => day * DAY_MS;
/** 23:59:59 of the day: the as-of instant that includes the whole day. */
export const dayEnd = (day: number): number => day * DAY_MS + DAY_MS - SECOND_MS;
export const dayStr = (day: number): string => new Date(day * DAY_MS).toISOString().slice(0, 10);

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** Strict calendar date to a day number; throws on anything else. */
export function parseDay(s: unknown): number {
  const m = typeof s === "string" ? DATE.exec(s) : null;
  if (!m) throw new Error("must be an ISO date");
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const ms = Date.UTC(y, mo - 1, d);
  const back = new Date(ms);
  if (back.getUTCFullYear() !== y || back.getUTCMonth() !== mo - 1 || back.getUTCDate() !== d) throw new Error("not a calendar date");
  return ms / DAY_MS;
}
export function tryParseDay(s: string | null | undefined): number | null {
  if (!s) return null;
  try { return parseDay(s); } catch { return null; }
}

const TS = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}(?::?\d{2})?)$/;
/** ISO-8601 string with a zone to UTC ms. Naive values are refused (Python parse_ts). */
export function parseTs(value: unknown): number {
  const m = typeof value === "string" ? TS.exec(value) : null;
  if (!m) throw new Error("timestamp must be an ISO-8601 string with a timezone");
  const day = parseDay(`${m[1]}-${m[2]}-${m[3]}`);
  const [h, mi, s] = [Number(m[4]), Number(m[5]), Number(m[6] ?? 0)];
  if (h > 23 || mi > 59 || s > 59) throw new Error("time out of range");
  const ms = m[7] ? Number(m[7].padEnd(3, "0").slice(0, 3)) : 0;
  let offset = 0;
  if (m[8] !== "Z") {
    const sign = m[8]![0] === "-" ? -1 : 1;
    const digits = m[8]!.slice(1).replace(":", "");
    offset = sign * (Number(digits.slice(0, 2)) * 60 + Number(digits.slice(2) || 0));
  }
  return day * DAY_MS + ((h * 60 + mi - offset) * 60 + s) * 1000 + ms;
}
export function isoZ(ms: number): string {
  const iso = new Date(ms).toISOString(); // YYYY-MM-DDTHH:MM:SS.mmmZ
  return ms % 1000 === 0 ? `${iso.slice(0, 19)}Z` : iso;
}
