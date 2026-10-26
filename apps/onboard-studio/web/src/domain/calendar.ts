// Working calendars as sets of half-open intervals [start, end) in epoch ms (D-01). A holiday is an
// interval subtracted from the working set; a holiday on a weekend subtracts nothing (P02-TEST-08).
export type Interval = readonly [number, number];

const byStart = (a: Interval, b: Interval): number => a[0] - b[0] || a[1] - b[1];

/** Union as sorted, disjoint, non-empty half-open intervals (touching ones join). */
export function merge(intervals: readonly Interval[]): Interval[] {
  const out: [number, number][] = [];
  for (const [s, e] of intervals.filter((i) => i[1] > i[0]).sort(byStart)) {
    const last = out[out.length - 1];
    if (last && s <= last[1]) { if (e > last[1]) last[1] = e; }
    else out.push([s, e]);
  }
  return out;
}

/** Working set minus holidays, as disjoint intervals. */
export function subtract(working: readonly Interval[], holidays: readonly Interval[]): Interval[] {
  let result = merge(working);
  for (const [hs, he] of merge(holidays)) {
    const next: Interval[] = [];
    for (const [s, e] of result) {
      if (he <= s || hs >= e) { next.push([s, e]); continue; }
      if (s < hs) next.push([s, hs]);
      if (he < e) next.push([he, e]);
    }
    result = next;
  }
  return result;
}

export const effectiveIntervals = (working: readonly Interval[], holidays: readonly Interval[] = []): Interval[] =>
  subtract(working, holidays);

/** Milliseconds of [start, end) inside the intervals (sorted, disjoint); 0 when end <= start. Binary search start. */
export function overlapMs(start: number, end: number, intervals: readonly Interval[]): number {
  if (end <= start) return 0;
  let lo = 0, hi = intervals.length;
  while (lo < hi) { // first interval whose end is after start
    const mid = (lo + hi) >> 1;
    if (intervals[mid]![1] <= start) lo = mid + 1; else hi = mid;
  }
  let total = 0;
  for (let i = lo; i < intervals.length; i++) {
    const [s, e] = intervals[i]!;
    if (s >= end) break;
    const a = Math.max(start, s), b = Math.min(end, e);
    if (b > a) total += b - a;
  }
  return total;
}

export const inWorkingTime = (at: number, intervals: readonly Interval[]): boolean =>
  intervals.some(([s, e]) => s <= at && at < e);
