// Instants: UTC, `Z`, one accepted form (seconds, optional fraction, a zone). Naive values are refused. An instant is a BigInt count of
// microseconds since 1970-01-01T00:00:00Z, so ordering, differences and the half-open rules are exact integer arithmetic.
export type Ts = bigint;
const FORM = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/;
const US = 1_000_000n;
const DAY_US = 86_400n * US;

export function daysFromCivil(y: number, m: number, d: number): number {
  y -= m <= 2 ? 1 : 0;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}
function civilFromDays(z: number): [number, number, number] {
  z += 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp + (mp < 10 ? 3 : -9);
  return [yoe + era * 400 + (m <= 2 ? 1 : 0), m, d];
}
const dim = (y: number, m: number): number => (m === 2 ? ((y % 4 === 0 && y % 100 !== 0) || y % 400 === 0 ? 29 : 28) : [4, 6, 9, 11].includes(m) ? 30 : 31);

const memo = new Map<string, Ts>();
/** Parse one instant. Results are memoised by string: the same published instants are read many times by the point-in-time rebuild. */
export function parseTs(value: unknown): Ts {
  if (typeof value !== "string") throw new TypeError("timestamp must be an ISO-8601 string");
  const hit = memo.get(value);
  if (hit !== undefined) return hit;
  const t = parseTsUncached(value);
  if (memo.size > 400_000) memo.clear();
  memo.set(value, t);
  return t;
}
function parseTsUncached(value: string): Ts {
  const m = FORM.exec(value);
  if (!m) throw new RangeError("timestamp must be YYYY-MM-DDTHH:MM:SS with a zone");
  const [y, mo, d, h, mi, s] = [1, 2, 3, 4, 5, 6].map((i) => Number(m[i]));
  if (y! < 1 || mo! < 1 || mo! > 12 || d! < 1 || d! > dim(y!, mo!) || h! > 23 || mi! > 59 || s! > 59) throw new RangeError("not a calendar instant");
  const micro = BigInt((m[7] ?? "").slice(0, 6).padEnd(6, "0") || "0");
  let off = 0n;
  const z = m[8]!;
  if (z !== "Z") {
    const oh = Number(z.slice(1, 3)), om = Number(z.slice(4, 6));
    if (oh > 23 || om > 59) throw new RangeError("bad zone offset");
    off = BigInt((oh * 3600 + om * 60) * (z[0] === "-" ? -1 : 1)) * US;
  }
  return BigInt(daysFromCivil(y!, mo!, d!)) * DAY_US + BigInt(h! * 3600 + mi! * 60 + s!) * US + micro - off;
}
const floorDiv = (a: bigint, b: bigint): bigint => { const q = a / b; return (a % b !== 0n) && ((a < 0n) !== (b < 0n)) ? q - 1n : q; };
export function isoZ(t: Ts | null): string | null {
  if (t === null) return null;
  const days = floorDiv(t, DAY_US);
  const rem = t - days * DAY_US;
  const [y, mo, d] = civilFromDays(Number(days));
  const secs = Number(rem / US), micro = Number(rem % US);
  const p = (n: number, w = 2): string => String(n).padStart(w, "0");
  return `${p(y, 4)}-${p(mo)}-${p(d)}T${p(Math.floor(secs / 3600))}:${p(Math.floor((secs % 3600) / 60))}:${p(secs % 60)}${micro ? `.${p(micro, 6)}` : ""}Z`;
}
export const daysUs = (n: number): bigint => BigInt(n) * DAY_US;
/** Whole hours, floored. */
export const hoursBetween = (later: Ts, earlier: Ts): number => Number(floorDiv(later - earlier, 3600n * US));
/** Whole days, floored (the `days_since` of a feature). */
export const wholeDays = (later: Ts, earlier: Ts): number => Number(floorDiv(later - earlier, DAY_US));
