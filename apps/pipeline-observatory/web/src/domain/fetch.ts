// Cursor pagination with a rate-limit hint (D-01, P08-FLOW-01, P08-TEST-03, P08-TEST-10). A source is fetched page by page from a cursor; a page
// carries the next cursor and, when the source rate-limits, a `retry_after_seconds` hint. A retry honours the hint and never happens sooner; a
// cursor that repeats itself stops the fetch with CURSOR_LOOP. `fetchAll` is the pure driver: the transport, the clock and the sleep are
// injected so a test (or the case study's experiment) controls time.
import * as E from "./errors";
import { DomainError } from "./errors";
import type { Row } from "./contract";
import { microsBetween, parseTs } from "./time";

export interface Page { status: number; records: Row[]; next_cursor: string | null; retry_after_seconds: number | null }
export interface FetchResult { records: Row[]; cursors: string[]; calls: [string, bigint][]; waits: number[] }

/** A retry sooner than `retry_after_seconds` after the rate-limited response is refused (RETRY_TOO_SOON). */
export function checkRetryAllowed(rateLimitedAt: bigint | string, retryAfterSeconds: number, now: bigint | string): void {
  const notBefore = parseTs(rateLimitedAt) + BigInt(retryAfterSeconds) * 1_000_000n;
  if (parseTs(now) < notBefore) {
    const us = microsBetween(now, notBefore);
    const whole = Number((us + 999_999n) / 1_000_000n);                  // whole seconds, rounded up, integer arithmetic
    throw new DomainError(E.RETRY_TOO_SOON, `the source asked for ${retryAfterSeconds} s; retry in ${whole} s`, "input.cursor", { retry_after_seconds: retryAfterSeconds, remaining_seconds: whole });
  }
}
/** `next_cursor` must be new: equal to the cursor just fetched, or to one already seen in this fetch session, is a loop. */
export function checkCursorProgress(cursor: string, nextCursor: string | null, seen: Set<string>): void {
  if (nextCursor !== null && (nextCursor === cursor || seen.has(nextCursor))) {
    throw new DomainError(E.CURSOR_LOOP, `cursor ${JSON.stringify(nextCursor)} repeats; the fetch is stopped`, "input.page.next_cursor", { cursor, next_cursor: nextCursor });
  }
}
/** Fetch from `start` until a page has no next cursor. On a 429 wait exactly `retry_after_seconds` (via `sleep`) and ask again; more than
 * `maxRetries` consecutive rate limits is RETRY_EXHAUSTED; a repeated cursor is CURSOR_LOOP. */
export function fetchAll(fetchPage: (cursor: string) => Page, start: string, now: () => bigint, sleep: (seconds: number) => void, maxPages = 1000, maxRetries = 5): FetchResult {
  const res: FetchResult = { records: [], cursors: [], calls: [], waits: [] };
  const seen = new Set<string>([start]);
  let cursor = start, retries = 0;
  for (let i = 0; i < maxPages * (maxRetries + 1); i++) {
    res.calls.push([cursor, now()]);
    const page = fetchPage(cursor);
    if (page.status === 429) {
      retries++;
      if (retries > maxRetries) throw new DomainError(E.RETRY_EXHAUSTED, `${maxRetries} retries were rate-limited`, "input.cursor", { cursor });
      const wait = page.retry_after_seconds ?? 1;
      res.waits.push(wait);
      sleep(wait);
      continue;
    }
    retries = 0;
    res.records.push(...page.records);
    res.cursors.push(cursor);
    checkCursorProgress(cursor, page.next_cursor, seen);
    if (page.next_cursor === null) return res;
    seen.add(page.next_cursor);
    cursor = page.next_cursor;
    if (res.cursors.length >= maxPages) throw new DomainError(E.CURSOR_LOOP, "too many pages without an end", "input.cursor", { pages: res.cursors.length });
  }
  throw new DomainError(E.RETRY_EXHAUSTED, "fetch did not finish", "input.cursor");
}
