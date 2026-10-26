"""Canonical events (D-01, D-05): received by the cutoff, de-duplicated, identity resolved in time, exclusions counted.

Processing order (D-P6-6): (1) keep events with ``received_at`` <= cutoff, (2) de-duplicate, (3) drop unknown identity,
(4) drop events of bot users (also those attributed to a bot by a link), (5) drop events of internal accounts. The log is
never edited: a late event changes a later run, never a published one, because a run at cutoff C reads only what was
received by C.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .models import Event, Population

DELAYED = timedelta(hours=24)


@dataclass(frozen=True)
class AEvent:
    """An analysed event: identity resolved, account and visitor key attached."""
    event: Event
    user: str | None            # the user the event is attributed to (own user_id, or by a link at or after linked_at)
    account: str | None
    visitor: str                # funnel unit (D-P6-9)
    name: str
    at: datetime
    props: tuple[tuple[str, str], ...] = ()


@dataclass
class Canon:
    rows_total: int
    received_after_cutoff: int
    duplicates: int
    canon: list[Event]
    delayed: int
    unknown: int
    bots: int
    internals: int
    analysed: list[AEvent]
    anon_events: int
    attributed: int
    internal_signup_accounts: list[tuple[str, datetime]] = field(default_factory=list)   # (account, signup instant), for retention
    props: dict[str, dict[str, str]] = field(default_factory=dict)

    def tracking_quality(self) -> dict[str, int]:
        return {"rows_total": self.rows_total, "received_after_cutoff": self.received_after_cutoff,
                "duplicates_dropped": self.duplicates, "canonical": len(self.canon), "delayed_over_24h": self.delayed,
                "unknown_identity": self.unknown, "bot_events_excluded": self.bots,
                "internal_events_excluded": self.internals, "analysed": len(self.analysed)}

    def identity(self) -> dict[str, int]:
        return {"anonymous_events": self.anon_events, "attributed_by_link": self.attributed,
                "remain_anonymous": self.anon_events - self.attributed}


def properties_by_event(pop: Population) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for p in pop.event_properties:
        out[p.event_id][p.property_key] = p.property_value
    return out


def canonicalise(pop: Population, cutoff: datetime) -> Canon:
    users = {u.user_id: u for u in pop.users}
    accounts = {a.account_id: a for a in pop.accounts}
    props = properties_by_event(pop)
    links_by_anon: dict[str, list] = defaultdict(list)
    anon_of_user: dict[str, str] = {}
    for l in sorted(pop.identity_links, key=lambda l: (l.linked_at, l.identity_link_id)):
        links_by_anon[l.anonymous_id].append(l)
        anon_of_user.setdefault(l.user_id, l.anonymous_id)

    # (1) received by the cutoff, (2) de-duplicated: earliest (received_at, event_id) survives (D-P6-7)
    recv = sorted((e for e in pop.events if e.received_at <= cutoff), key=lambda e: (e.received_at, e.event_id))
    seen_ids: set[str] = set()
    seen_keys: set[tuple] = set()
    canon: list[Event] = []
    dups = 0
    for e in recv:
        actor = e.user_id or e.anonymous_id
        key = (actor, e.event_name, e.event_at, tuple(sorted(props.get(e.event_id, {}).items())))
        if e.event_id in seen_ids or key in seen_keys:
            dups += 1
            continue
        seen_ids.add(e.event_id)
        seen_keys.add(key)
        canon.append(e)

    def effective_user(e: Event) -> str | None:
        """Time-aware identity (D-01): a link attributes only events at or after ``linked_at``; never backwards."""
        if e.user_id:
            return e.user_id
        for l in links_by_anon.get(e.anonymous_id or "", []):
            if l.linked_at <= e.event_at:
                return l.user_id
        return None

    analysed: list[AEvent] = []
    unknown = bots = internals = 0
    internal_signups: list[tuple[str, datetime]] = []
    for e in canon:
        u = effective_user(e)
        if (e.user_id is None and e.anonymous_id is None) or (u is not None and u not in users):
            unknown += 1
            continue
        if u is not None and users[u].bot_flag:
            bots += 1
            continue
        if u is not None and accounts[users[u].account_id].internal:
            internals += 1
            if e.event_name == "signup":
                internal_signups.append((users[u].account_id, e.event_at))
            continue
        acct = users[u].account_id if u else None
        vk = e.anonymous_id or (anon_of_user.get(e.user_id) if e.user_id else None) or "user:" + str(e.user_id)
        analysed.append(AEvent(e, u, acct, vk, e.event_name, e.event_at))
    delayed = sum(1 for e in canon if e.received_at - e.event_at > DELAYED)
    anon = [a for a in analysed if a.event.user_id is None]
    attributed = sum(1 for a in anon if a.user is not None)
    return Canon(len(pop.events), len(pop.events) - len(recv), dups, canon, delayed, unknown, bots, internals, analysed,
                 len(anon), attributed, internal_signups, props)


def late_arrivals(pop: Population, prior_cutoff: datetime, cutoff: datetime) -> list[Event]:
    """Events that happened by ``prior_cutoff`` but were received after it and by ``cutoff``: what a later run sees that the
    earlier run could not (TEST-06: a revision, disclosed as such)."""
    return [e for e in pop.events if e.event_at <= prior_cutoff < e.received_at <= cutoff]


def late_event_summary(events: list[Event]) -> dict[str, Any]:
    names: dict[str, int] = defaultdict(int)
    for e in events:
        names[e.event_name] += 1
    return {"count": len(events), "by_event_name": dict(sorted(names.items()))}
