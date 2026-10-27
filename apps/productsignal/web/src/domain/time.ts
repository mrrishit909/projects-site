// Instants as whole UTC seconds (number), calendar dates as day numbers (days since 1970-01-01). Mirror of timeutil.py. The account's
// local calendar (D-02) is the IANA zone's, from the platform's Intl database; the Python outputs verify it (scripts/golden-check.ts).
import { malformed } from "./num";

const TS_FORM = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/;
const DATE_FORM = /^\d{4}-\d{2}-\d{2}$/;
export const DAY = 86_400;
export const HOUR = 3_600;

export function parseTs(value: unknown, name = "timestamp"): number {
  if (typeof value !== "string") throw malformed(name, "timestamp must be an ISO-8601 string");
  const m = TS_FORM.exec(value);
  if (!m) throw malformed(name, "timestamp must be YYYY-MM-DDTHH:MM:SS with a zone");
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number) as [number, number, number, number, number, number];
  const t = Date.UTC(y, mo - 1, d, h, mi, s);
  const chk = new Date(t);
  if (chk.getUTCFullYear() !== y || chk.getUTCMonth() !== mo - 1 || chk.getUTCDate() !== d || h > 23 || mi > 59 || s > 59) throw malformed(name, "is not a valid instant");
  if (m[7] !== undefined && /[1-9]/.test(m[7])) throw malformed(name, "sub-second precision is not supported by the TypeScript mirror");
  let off = 0;
  const z = m[8]!;
  if (z !== "Z") off = (z[0] === "-" ? -1 : 1) * (Number(z.slice(1, 3)) * 3600 + Number(z.slice(4, 6)) * 60);
  return Math.floor(t / 1000) - off;
}
export const isoZ = (sec: number): string => `${new Date(sec * 1000).toISOString().slice(0, 19)}Z`;

/** Day number of a YYYY-MM-DD date. */
export function parseDay(value: unknown, name = "date"): number {
  if (typeof value !== "string" || !DATE_FORM.test(value)) throw malformed(name, "date must be YYYY-MM-DD");
  const t = Date.parse(`${value}T00:00:00Z`);
  if (Number.isNaN(t) || new Date(t).toISOString().slice(0, 10) !== value) throw malformed(name, "is not a calendar date");
  return Math.round(t / 86_400_000);
}
export const dayIso = (n: number): string => new Date(n * 86_400_000).toISOString().slice(0, 10);
/** The UTC calendar date of an instant, as a day number. */
export const utcDay = (sec: number): number => Math.floor(sec / DAY);
export const weekdayOf = (day: number): number => (((day + 3) % 7) + 7) % 7; // 0 = Monday (1970-01-01 was a Thursday)

const ZONES = new Map<string, Intl.DateTimeFormat | null>();
function formatter(tz: string): Intl.DateTimeFormat | null {
  let f = ZONES.get(tz);
  if (f === undefined) {
    try { f = new Intl.DateTimeFormat("en-US", { timeZone: tz, year: "numeric", month: "numeric", day: "numeric" }); } catch { f = null; }
    ZONES.set(tz, f);
  }
  return f;
}
/** True for an IANA name the platform knows (Python: zoneinfo; names with a leading "/" or ".." are refused). */
export const isZone = (tz: unknown): tz is string => typeof tz === "string" && tz !== "" && !tz.startsWith("/") && !tz.includes("..") && formatter(tz) !== null;

const LOCAL = new Map<string, Map<number, number>>();
/** The calendar date of the instant in the IANA zone `tz`, as a day number (D-02: day indices are local calendar days). */
export function localDay(sec: number, tz: string): number {
  let cache = LOCAL.get(tz);
  if (!cache) { cache = new Map(); LOCAL.set(tz, cache); }
  const hit = cache.get(sec);
  if (hit !== undefined) return hit;
  const f = formatter(tz);
  if (!f) throw malformed("timezone", `unknown IANA timezone ${tz}`);
  let y = 0, m = 0, d = 0;
  for (const p of f.formatToParts(new Date(sec * 1000))) {
    if (p.type === "year") y = Number(p.value);
    else if (p.type === "month") m = Number(p.value);
    else if (p.type === "day") d = Number(p.value);
  }
  const r = Math.round(Date.UTC(y, m - 1, d) / 86_400_000);
  cache.set(sec, r);
  return r;
}
