// Half-open backfill ranges [start, end) over daily UTC partitions (D-03, D-P8-11).
import * as E from "./errors";
import { DomainError } from "./errors";
import type { Row } from "./contract";
import { dayPartitions, MICROS, parseTs } from "./time";

/** Half-open ranges overlap iff each starts before the other ends: touching ranges ([a, b) and [b, c)) do not overlap. */
export const rangesOverlap = (aStart: unknown, aEnd: unknown, bStart: unknown, bEnd: unknown): boolean =>
  parseTs(aStart) < parseTs(bEnd) && parseTs(bStart) < parseTs(aEnd);
/** The first earlier accepted request of the same source whose range overlaps the request's. */
export function findOverlap(accepted: Iterable<Row>, request: Row): Row | null {
  for (const o of accepted) if (o["source_id"] === request["source_id"] && rangesOverlap(request["start_at"], request["end_at"], o["start_at"], o["end_at"])) return o;
  return null;
}
/** The partitions of a request: both bounds at UTC midnight, start before end; else DomainError. */
export function checkRange(start: unknown, end: unknown): string[] {
  const s = parseTs(start), e = parseTs(end);
  if (!(s < e)) throw new DomainError(E.INVALID_RANGE, "start_at must be before end_at (the range is half-open)", "input.end_at");
  for (const [name, v] of [["start_at", s], ["end_at", e]] as const) {
    if (((v % MICROS.day) + MICROS.day) % MICROS.day !== 0n) throw new DomainError(E.PARTITION_ALIGNMENT, `${name} must be a UTC midnight (partitions are daily)`, `input.${name}`);
  }
  if (e - s > 3660n * MICROS.day) throw new DomainError(E.INVALID_RANGE, "a backfill covers at most 3660 daily partitions", "input.end_at");
  return dayPartitions(s, e);
}
