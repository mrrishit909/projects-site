// Instants as whole UTC seconds (number). One accepted form, seconds required (timeutil.py).
import { malformed } from "./num";

const TS_FORM = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/;
const DATE_FORM = /^\d{4}-\d{2}-\d{2}$/;
/** "No cutoff": every recorded fact counts (9999-12-31T23:59:59Z). */
export const FAR_FUTURE = 253402300799;

export function parseDate(value: unknown, name: string): string {
  if (typeof value !== "string" || !DATE_FORM.test(value)) throw malformed(name, "date must be YYYY-MM-DD");
  const d = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== value) throw malformed(name, "is not a calendar date");
  return value;
}

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
export const dayOf = (sec: number): string => new Date(sec * 1000).toISOString().slice(0, 10);
export const monthOf = (sec: number): string => new Date(sec * 1000).toISOString().slice(0, 7);
