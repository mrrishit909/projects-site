"""Replay of one ticket's ordered event log into cycles (D-01, D-02).

The log is the truth: events are ordered by ``(occurred_at, event_id)`` so a late arrival lands where it happened.
The replay is tolerant (it records facts, it does not police transitions; ingest and the commands do that), which
matters because real histories carry a ``queued`` stamp a second after the service it describes (golden t-001).

* A **cycle** runs from an arrival to the next reopen. Cycle 0 starts at the ticket's ``created_at``; a ``reopened``
  event starts a new cycle that links the prior one (``prior``). A reopened ticket is still ONE customer contact.
* A **service interval** opens at ``service_started`` / ``resumed`` and closes at ``paused``, ``transferred``,
  ``resolved`` or ``abandoned`` (idle and waiting_customer time are never handling, D-02).
* A **transfer** moves the ticket to another queue; the arrival instant never changes (P04-FLOW-04, P04-TEST-08):
  only the per-queue wait leg restarts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Iterable

from .contract import BOT_PREFIX, CLOSERS, OPENERS
from .models import Ticket, TicketEvent
from .timeutil import minutes_between


def is_bot(actor_id: str | None) -> bool:
    return actor_id is not None and actor_id.startswith(BOT_PREFIX)


def is_human_reply(e: TicketEvent) -> bool:
    """A reply counts as a first response only when typed replied_human and not authored by automation."""
    return e.event_type == "replied_human" and not is_bot(e.actor_id)


def ordered(events: Iterable[TicketEvent]) -> list[TicketEvent]:
    return sorted(events, key=lambda e: (e.occurred_at, e.event_id))


@dataclass(frozen=True)
class Interval:
    ticket_id: str
    agent_id: str | None
    start: datetime
    end: datetime | None      # None: still in service at the end of the log
    cycle: int

    def minutes_within(self, lo: datetime, hi: datetime) -> Fraction:
        """Minutes of this interval inside [lo, hi); an open interval runs to ``hi``."""
        a, b = max(self.start, lo), min(self.end if self.end is not None else hi, hi)
        return minutes_between(a, b) if b > a else Fraction(0)


@dataclass(frozen=True)
class Transfer:
    at: datetime
    from_queue: str | None
    to_queue: str | None


@dataclass
class Cycle:
    index: int
    started_at: datetime
    prior: int | None = None
    resolved_at: datetime | None = None
    first_response_at: datetime | None = None
    first_service_at: datetime | None = None
    queue_id: str | None = None
    intervals: list[Interval] = field(default_factory=list)
    pauses: list[tuple[datetime, datetime | None]] = field(default_factory=list)
    transfers: list[Transfer] = field(default_factory=list)


@dataclass
class History:
    ticket_id: str
    arrival: datetime
    events: list[TicketEvent]
    cycles: list[Cycle]
    abandoned_at: datetime | None
    queue_id: str | None

    @property
    def intervals(self) -> list[Interval]:
        return [iv for c in self.cycles for iv in c.intervals]

    @property
    def reopen_count(self) -> int:
        return len(self.cycles) - 1

    @property
    def transfers(self) -> list[Transfer]:
        return [t for c in self.cycles for t in c.transfers]

    @property
    def final_resolution(self) -> datetime | None:
        """The resolution of the last cycle; None while the ticket is open (reopened and not yet resolved)."""
        return self.cycles[-1].resolved_at

    @property
    def first_human_reply_at(self) -> datetime | None:
        times = [c.first_response_at for c in self.cycles if c.first_response_at is not None]
        return min(times) if times else None

    @property
    def first_service_at(self) -> datetime | None:
        times = [c.first_service_at for c in self.cycles if c.first_service_at is not None]
        return min(times) if times else None

    @property
    def owner_agent(self) -> str | None:
        """The agent of the last service interval (the one who carried the ticket to its end)."""
        ivs = [iv for iv in self.intervals if iv.agent_id is not None]
        return ivs[-1].agent_id if ivs else None

    def open_at(self, instant: datetime) -> bool:
        """Arrived, not resolved (a ticket in service is unresolved) and not abandoned at ``instant`` (D-05)."""
        if self.arrival > instant:
            return False
        gone = False
        for e in self.events:
            if e.occurred_at > instant:
                break
            if e.event_type in ("resolved", "abandoned"):
                gone = True
            elif e.event_type == "reopened":
                gone = False
        return not gone

    def state_at(self, instant: datetime) -> str | None:
        """new | queued | in_service | waiting_customer | resolved | reopened | abandoned (None before arrival).

        ``queued`` stamps only matter while no stronger event has happened."""
        state: str | None = None
        for e in self.events:
            if e.occurred_at > instant:
                break
            t = e.event_type
            if t == "created":
                state = state or "new"
            elif t == "queued":
                state = "queued" if state in (None, "new") else state
            elif t in OPENERS:
                state = "in_service"
            elif t == "paused":
                state = "waiting_customer"
            elif t == "transferred":
                state = "queued"
            elif t == "resolved":
                state = "resolved"
            elif t == "reopened":
                state = "reopened"
            elif t == "abandoned":
                state = "abandoned"
        if state is None and self.arrival <= instant:
            state = "new"
        return state


def replay(ticket: Ticket, events: Iterable[TicketEvent]) -> History:
    """Replay ``events`` of ``ticket`` (any order) into its cycles."""
    evs = ordered(events)
    created = next((e.queue_id for e in evs if e.event_type == "created" and e.queue_id), None)
    queue = created or ticket.queue_id          # the queue the ticket started in (the row holds the CURRENT one)
    cycles = [Cycle(0, ticket.created_at, None, queue_id=queue)]
    open_iv: tuple[datetime, str | None] | None = None
    last_agent: str | None = None
    abandoned_at: datetime | None = None
    for e in evs:
        cyc, t = cycles[-1], e.event_type
        if t == "reopened":
            cycles.append(Cycle(len(cycles), e.occurred_at, cyc.index, queue_id=queue))
            continue
        if t in OPENERS and open_iv is None:
            last_agent = e.agent_id or last_agent
            open_iv = (e.occurred_at, last_agent)
            if t == "service_started" and cyc.first_service_at is None:
                cyc.first_service_at = e.occurred_at
        if t == "resumed" and cyc.pauses and cyc.pauses[-1][1] is None:
            cyc.pauses[-1] = (cyc.pauses[-1][0], e.occurred_at)
        if t in CLOSERS:
            if open_iv is not None:
                cyc.intervals.append(Interval(ticket.ticket_id, open_iv[1], open_iv[0], e.occurred_at, cyc.index))
                open_iv = None
            if t == "resolved":
                cyc.resolved_at = e.occurred_at
            elif t == "paused":
                cyc.pauses.append((e.occurred_at, None))
            elif t == "transferred":
                cyc.transfers.append(Transfer(e.occurred_at, queue, e.queue_id))
            elif t == "abandoned" and abandoned_at is None:
                abandoned_at = e.occurred_at
        if t in ("queued", "transferred") and e.queue_id is not None:
            queue = e.queue_id
        if is_human_reply(e) and (cyc.first_response_at is None or e.occurred_at < cyc.first_response_at):
            cyc.first_response_at = e.occurred_at
    if open_iv is not None:
        cycles[-1].intervals.append(Interval(ticket.ticket_id, open_iv[1], open_iv[0], None, cycles[-1].index))
    return History(ticket.ticket_id, ticket.created_at, evs, cycles, abandoned_at, queue)


def queue_legs(h: History) -> list[dict]:
    """Per-queue wait legs: the arrival never moves but the wait for service restarts in each queue (P04-TEST-08)."""
    out = []
    start, queue = h.arrival, h.cycles[0].queue_id
    starts = sorted(iv.start for iv in h.intervals)
    marks = [(t.at, t.to_queue) for t in h.transfers]
    for at, to in marks + [(None, None)]:  # type: ignore[list-item]
        end = at
        served = next((s for s in starts if s >= start and (end is None or s < end)), None)
        out.append({"queue_id": queue, "entered_at": start,
                    "wait_minutes": minutes_between(start, served) if served is not None else None})
        if at is not None:
            start, queue = at, to
    return out


def queue_at(ticket: Ticket, events: Iterable[TicketEvent], instant: datetime) -> str | None:
    """The queue a ticket is in at ``instant``: where it was created, then the latest queued / transferred stamp."""
    evs = ordered(events)
    queue = next((e.queue_id for e in evs if e.event_type == "created" and e.queue_id), None) or ticket.queue_id
    for e in evs:
        if e.occurred_at > instant:
            break
        if e.event_type in ("queued", "transferred") and e.queue_id is not None:
            queue = e.queue_id
    return queue


def interval_conflict(existing: list[Interval], new: Interval, cap: int, horizon_end: datetime | None = None) -> bool:
    """True when adding ``new`` to ``existing`` (one agent's accepted intervals) puts more than ``cap`` of them in
    service at some instant (P04-TEST-04). An interval that closes at the instant another opens does not overlap."""
    far = datetime.max.replace(tzinfo=new.start.tzinfo)
    new_end = new.end if new.end is not None else far
    points = [new.start] + [a.start for a in existing if new.start < a.start < new_end]
    for p in points:
        n = 1 + sum(1 for a in existing if a.start <= p < (a.end if a.end is not None else far))
        if n > cap:
            return True
    return False
