// Instants, hours and decimal rounding (D-01). Instants are UTC epoch milliseconds (integers).
// Durations are integer milliseconds; hours and rates are formatted from exact BigInt ratios, so no
// floating-point arithmetic is ever applied to a duration. Hours: 4 decimals, rates: 6, ROUND_HALF_UP.

export const MS_PER_HOUR = 3_600_000;

const TS = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;

/** ISO-8601 string with a zone (Z or an offset) to UTC epoch ms. Naive values are refused. */
export function parseTs(value: unknown): number {
  if (typeof value !== "string") throw new Error("timestamp must be an ISO-8601 string");
  const m = TS.exec(value);
  if (!m) throw new Error("timestamp needs a timezone and ISO-8601 form");
  const frac = m[7] ? Number(m[7].slice(1, 4).padEnd(3, "0")) : 0; // sub-millisecond digits are dropped
  const zone = m[8]!;
  let offset = 0;
  if (zone !== "Z") {
    const sign = zone.startsWith("-") ? -1 : 1;
    const digits = zone.slice(1).replace(":", "");
    offset = sign * (Number(digits.slice(0, 2)) * 60 + Number(digits.slice(2, 4))) * 60_000;
  }
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6] ?? "0"), frac);
  if (!Number.isFinite(ms)) throw new Error("invalid timestamp");
  const probe = new Date(ms);
  if (probe.getUTCMonth() !== Number(m[2]) - 1 || probe.getUTCDate() !== Number(m[3])) throw new Error("invalid calendar date");
  return ms - offset;
}

export function parseTsOpt(value: unknown): number | null {
  return value === null || value === undefined ? null : parseTs(value);
}

/** UTC ISO-8601 with a Z suffix (milliseconds only when present). */
export function isoZ(ms: number): string {
  const s = new Date(ms).toISOString();
  return ms % 1000 === 0 ? s.replace(".000Z", "Z") : s;
}

/** Non-negative duration in ms between two instants. */
export const msBetween = (start: number, end: number): number => (end > start ? end - start : 0);

function pow10(n: number): bigint { return 10n ** BigInt(n); }

/** num/den rounded half-up to `places` decimals, as a plain decimal string. den > 0, num >= 0. */
export function ratioFixed(num: bigint, den: bigint, places: number): string {
  const scaled = (2n * num * pow10(places) + den) / (2n * den); // floor((num*10^p)/den + 1/2)
  const s = scaled.toString().padStart(places + 1, "0");
  return places === 0 ? s : `${s.slice(0, s.length - places)}.${s.slice(s.length - places)}`;
}

/** Hours (4 dp) of a total of milliseconds divided by `count` (a mean when count > 1). Null when count is 0. */
export function hoursFixed(totalMs: number, count = 1): string | null {
  if (count === 0) return null;
  return ratioFixed(BigInt(Math.max(totalMs, 0)), BigInt(MS_PER_HOUR) * BigInt(count), 4);
}

/** Rate (6 dp) of numerator over denominator. Null when the denominator is 0. */
export function rate6(num: number, den: number): string | null {
  return den === 0 ? null : ratioFixed(BigInt(num), BigInt(den), 6);
}

/** Display helper: hours string as given, or an en dash when null. */
export const showHours = (h: string | null): string => (h === null ? "n/a" : `${h} h`);
