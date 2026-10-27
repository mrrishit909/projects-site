"""Cursor pagination with a rate-limit hint (D-01, P08-FLOW-01, P08-TEST-03, P08-TEST-10).

A source is fetched page by page from a cursor. A page carries the next cursor and, when the source rate-limits, a ``retry_after_seconds``
hint. A retry honours the hint and never happens sooner; a cursor that repeats itself (a ``next_cursor`` seen before, or equal to the cursor
just fetched) stops the fetch with ``CURSOR_LOOP``. ``fetch_all`` is the pure driver (the transport, the clock and the sleep are injected so
a test controls time); the API's C01 applies the same two checks one page at a time (``check_retry_allowed`` and ``judge_fetch``).

D-09 (R8-06): a LOOP is a repeated cursor inside ONE fetch session (a next cursor already seen in the session, a cursor fetched twice in it, or a
page pointing at itself). A NEW session may fetch a cursor again: the fetch is recorded as ``refetch`` (a scheduled re-fetch of a stale source, a
replay of a window after a crash, a backfill that re-reads the last committed cursor). ``judge_fetch`` is the one pure rule C01, the generator and
the tests share.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from . import errors as E
from .errors import DomainError
from .timeutil import micros_between


@dataclass(frozen=True)
class Page:
    status: int = 200                         # 200 or 429
    records: tuple[dict[str, Any], ...] = ()
    next_cursor: str | None = None
    retry_after_seconds: int | None = None


@dataclass
class FetchResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    cursors: list[str] = field(default_factory=list)          # every cursor fetched successfully, in order
    calls: list[tuple[str, datetime]] = field(default_factory=list)   # every request, with the instant it was made
    waits: list[int] = field(default_factory=list)            # the retry-after waits honoured


def retry_not_before(rate_limited_at: datetime, retry_after_seconds: int) -> datetime:
    return rate_limited_at + timedelta(seconds=retry_after_seconds)


def check_retry_allowed(rate_limited_at: datetime, retry_after_seconds: int, now: datetime) -> None:
    """A retry sooner than ``retry_after_seconds`` after the rate-limited response is refused (RETRY_TOO_SOON)."""
    not_before = retry_not_before(rate_limited_at, retry_after_seconds)
    if now < not_before:
        whole = -(-micros_between(now, not_before) // 1_000_000)          # whole seconds, rounded up, integer arithmetic
        raise DomainError(E.RETRY_TOO_SOON, f"the source asked for {retry_after_seconds} s; retry in {whole} s", "input.cursor",
                          {"retry_after_seconds": retry_after_seconds, "remaining_seconds": whole})


def check_cursor_progress(cursor: str, next_cursor: str | None, seen: set[str]) -> None:
    """``next_cursor`` must be new: equal to the cursor just fetched, or to one already seen in this fetch session, is a loop."""
    if next_cursor is not None and (next_cursor == cursor or next_cursor in seen):
        raise DomainError(E.CURSOR_LOOP, f"cursor {next_cursor!r} repeats; the fetch is stopped", "input.page.next_cursor",
                          {"cursor": cursor, "next_cursor": next_cursor})


@dataclass(frozen=True)
class Fetched:
    """One earlier page of a source as the fetch log records it (rate-limited and loop rows are not pages)."""
    session: str | None
    cursor: str
    next_cursor: str | None
    status: str = "ok"


def judge_fetch(history: Iterable[Fetched], last_committed_cursor: str | None, session: str, cursor: str, next_cursor: str | None) -> str:
    """Judge a page that answered 200: ``ok`` (a cursor never fetched before), ``refetch`` (a cursor fetched before in another session, or the
    re-poll of the last committed cursor by a new session whose page points at itself because the source has nothing new), or CURSOR_LOOP.

    Inside one session: ``next_cursor`` already seen there (as a cursor or as a next cursor), a page pointing at itself, or a cursor fetched
    twice, is a loop, EXCEPT the first page of a session that re-polls the source's last committed cursor and points at itself (nothing new)."""
    pages = [h for h in history if h.status in ("ok", "refetch")]
    mine = [h for h in pages if h.session == session]
    fetched_here = {h.cursor for h in mine}
    seen = fetched_here | {h.next_cursor for h in mine if h.next_cursor is not None}
    stale_repoll = not mine and next_cursor is not None and next_cursor == cursor and cursor == last_committed_cursor
    if not stale_repoll and (cursor in fetched_here or (next_cursor is not None and (next_cursor == cursor or next_cursor in seen))):
        raise DomainError(E.CURSOR_LOOP, f"cursor {(next_cursor if next_cursor is not None else cursor)!r} repeats inside session {session!r}; the fetch is stopped",
                          "input.page.next_cursor", {"cursor": cursor, "next_cursor": next_cursor})
    return "refetch" if stale_repoll or any(h.cursor == cursor for h in pages) else "ok"


def fetch_all(fetch_page: Callable[[str], Page], start: str, now: Callable[[], datetime], sleep: Callable[[int], None],
              max_pages: int = 1000, max_retries: int = 5) -> FetchResult:
    """Fetch from ``start`` until a page has no next cursor. On a 429 wait exactly ``retry_after_seconds`` (via ``sleep``) and ask again;
    more than ``max_retries`` consecutive rate limits is RETRY_EXHAUSTED; a repeated cursor is CURSOR_LOOP."""
    res = FetchResult()
    seen: set[str] = {start}
    cursor, retries = start, 0
    for _ in range(max_pages * (max_retries + 1)):
        res.calls.append((cursor, now()))
        page = fetch_page(cursor)
        if page.status == 429:
            retries += 1
            if retries > max_retries:
                raise DomainError(E.RETRY_EXHAUSTED, f"{max_retries} retries were rate-limited", "input.cursor", {"cursor": cursor})
            wait = page.retry_after_seconds if page.retry_after_seconds is not None else 1
            res.waits.append(wait)
            sleep(wait)
            continue
        retries = 0
        res.records.extend(page.records)
        res.cursors.append(cursor)
        check_cursor_progress(cursor, page.next_cursor, seen)
        if page.next_cursor is None:
            return res
        seen.add(page.next_cursor)
        cursor = page.next_cursor
        if len(res.cursors) >= max_pages:
            raise DomainError(E.CURSOR_LOOP, "too many pages without an end", "input.cursor", {"pages": len(res.cursors)})
    raise DomainError(E.RETRY_EXHAUSTED, "fetch did not finish", "input.cursor")
