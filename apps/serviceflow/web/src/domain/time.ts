// Instants are integer UTC epoch seconds (the published data has second precision). An ISO string with a sub-second
// part that is not zero is refused: the Python domain keeps microseconds, the snapshot never carries any.
const RE = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/;

export function parseTs(value: unknown): number {
  if (typeof value !== "string") throw new Error("timestamp must be an ISO-8601 string");
  const m = RE.exec(value);
  if (!m) throw new Error("timestamp needs a timezone and ISO-8601 form");
  if (m[7] && /[1-9]/.test(m[7])) throw new Error("sub-second precision is not supported");
  const [y, mo, d, h, mi, s] = [1, 2, 3, 4, 5, 6].map((i) => parseInt(m[i]!, 10)) as [number, number, number, number, number, number];
  const ms = Date.UTC(y, mo - 1, d, h, mi, s);
  const chk = new Date(ms);
  if (chk.getUTCFullYear() !== y || chk.getUTCMonth() !== mo - 1 || chk.getUTCDate() !== d || h > 23 || mi > 59 || s > 59) throw new Error("not a calendar instant");
  let off = 0;
  if (m[8] !== "Z") { const sign = m[8]![0] === "-" ? -1 : 1; off = sign * (parseInt(m[8]!.slice(1, 3), 10) * 3600 + parseInt(m[8]!.slice(4, 6), 10) * 60); }
  return ms / 1000 - off;
}
export const parseTsOpt = (v: unknown): number | null => (v === null || v === undefined ? null : parseTs(v));

const p2 = (n: number): string => String(n).padStart(2, "0");
/** UTC ISO-8601 with a Z suffix. */
export function isoZ(sec: number): string {
  const d = new Date(sec * 1000);
  return `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}T${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}:${p2(d.getUTCSeconds())}Z`;
}
export const isoOrNull = (sec: number | null): string | null => (sec === null ? null : isoZ(sec));

/** Overlap in seconds of [a0, a1) and [b0, b1). */
export const overlapSeconds = (a0: number, a1: number, b0: number, b1: number): number => Math.max(0, Math.min(a1, b1) - Math.max(a0, b0));
/** Seconds from start to end, never negative (a late-arriving reply clamps to 0, D-02). */
export const secondsBetween = (start: number, end: number): number => Math.max(0, end - start);

/** True for an IANA zone name this runtime knows. */
export function validZone(name: string): boolean {
  try { new Intl.DateTimeFormat("en-GB", { timeZone: name }); return true; } catch { return false; }
}
