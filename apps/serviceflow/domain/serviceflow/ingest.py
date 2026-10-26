"""Batch validation with dependent rejection (D-01, D-02, D-05). Pure: the same input gives an equal result.

Row rules: a record that cannot be parsed is MALFORMED_RECORD, a repeated id is DUPLICATE_ID (the first row stays),
a reference to a row that is not there is UNKNOWN_REFERENCE. Event rule: an event typed ``replied_human`` whose actor
is a bot is BOT_AS_HUMAN_REPLY (that event alone is rejected; automation never makes a first response).

Ticket rules (the whole ticket is rejected): TRANSFER_RESETS_ARRIVAL (a transferred ticket whose ``created_at`` is
later than its first event: the transfer reset the arrival), AGENT_NOT_QUALIFIED (a service_started by an agent who
lacks a skill the queue requires, effective at that instant) and CONCURRENCY_EXCEEDED (a service interval that puts
more than the agent's ``max_concurrent`` in service at once; the earlier start wins). D-05: a ticket rejected for a
rule carries that reason; its events and surveys carry TICKET_REJECTED.

``base`` is the population already stored (the API's C01): its rows are trusted and never rejected, but they
count for references and for concurrency. A trusted ticket that a NEW event would break keeps its stored rows: the
offending new event carries the reason and the batch's other new events of that ticket carry TICKET_REJECTED.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .contract import CONTRACT_VERSION, ENTITIES, OPENERS
from .errors import (AGENT_NOT_QUALIFIED, BOT_AS_HUMAN_REPLY, CONCURRENCY_EXCEEDED, CONTRACT_MISMATCH, DUPLICATE_ID,
                     MALFORMED_RECORD, TICKET_REJECTED, TRANSFER_RESETS_ARRIVAL, UNKNOWN_REFERENCE, DomainError)
from .events import interval_conflict, is_bot, ordered, queue_at, replay
from .models import Population, RejectedRecord, Ticket, TicketEvent, parsers, row_id


@dataclass
class IngestResult:
    accepted: dict[str, list[Any]] = field(default_factory=dict)
    accepted_rows: dict[str, list[dict]] = field(default_factory=dict)
    rejected: list[RejectedRecord] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def population(self) -> Population:
        pop = Population()
        for ent in ENTITIES:
            setattr(pop, ent, list(self.accepted.get(ent, [])))
        return pop

    def rejected_dicts(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.rejected]


def _group(items: list[Any], key: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for x in items:
        out.setdefault(key(x), []).append(x)
    return out


def validate_batch(raw: dict[str, Any], base: Population | None = None) -> IngestResult:
    """Validate and parse a raw batch; raw rows of rejected records are kept as they arrived."""
    if raw.get("contract_version", CONTRACT_VERSION) != CONTRACT_VERSION:
        raise DomainError(CONTRACT_MISMATCH, f"expected contract_version {CONTRACT_VERSION}",
                          details={"got": raw.get("contract_version")})
    base = base or Population()
    ps = parsers()
    bad: dict[tuple[str, int], str] = {}                 # (entity, position) -> reason
    parsed: dict[str, list[tuple[int, Any, Any]]] = {}   # entity -> [(position, raw row, typed)]
    base_ids = {ent: {row_id(ent, o) for o in getattr(base, ent)} for ent in ENTITIES}

    for ent in ENTITIES:
        parsed[ent] = []
        seen: set[str] = set()
        rows = raw.get(ent) or []
        if not isinstance(rows, list):
            rows = []
        for pos, row in enumerate(rows):
            try:
                if not isinstance(row, dict):
                    raise ValueError("record must be an object")
                obj = ps[ent](row)
            except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
                bad[(ent, pos)] = MALFORMED_RECORD
                parsed[ent].append((pos, row, None))
                continue
            rid = row_id(ent, obj)
            if rid in seen or rid in base_ids[ent]:
                bad[(ent, pos)] = DUPLICATE_ID
                parsed[ent].append((pos, row, None))
                continue
            seen.add(rid)
            parsed[ent].append((pos, row, obj))

    def ok(ent: str) -> list[tuple[int, Any, Any]]:
        return [p for p in parsed[ent] if (ent, p[0]) not in bad and p[2] is not None]

    def reject(ent: str, pos: int, reason: str) -> None:
        bad.setdefault((ent, pos), reason)

    # --- references among reference data ---------------------------------------------------------------------
    known: dict[str, set[str]] = {ent: set(base_ids[ent]) for ent in ENTITIES}
    for ent in ("customers", "queues", "agents", "skills"):
        known[ent] |= {row_id(ent, o) for _, _, o in ok(ent)}
    for ent, checks in (("queue_skills", (("queue_id", "queues"), ("skill_id", "skills"))),
                        ("agent_skills", (("agent_id", "agents"), ("skill_id", "skills"))),
                        ("shifts", (("agent_id", "agents"),)),
                        ("tickets", (("customer_id", "customers"), ("queue_id", "queues")))):
        for pos, _, o in ok(ent):
            if any(getattr(o, f) not in known[parent] for f, parent in checks):
                reject(ent, pos, UNKNOWN_REFERENCE)
    for ent in ("queue_skills", "agent_skills", "shifts", "tickets"):
        known[ent] |= {row_id(ent, o) for _, _, o in ok(ent)}

    # Tickets that are already rejected (any reason): their dependents carry TICKET_REJECTED.
    bad_ticket: dict[str, str] = {}
    for pos, row, o in parsed["tickets"]:
        reason = bad.get(("tickets", pos))
        if reason in (MALFORMED_RECORD, UNKNOWN_REFERENCE):
            tid = o.ticket_id if o is not None else (row.get("ticket_id") if isinstance(row, dict) else None)
            if isinstance(tid, str) and tid not in base_ids["tickets"]:
                bad_ticket.setdefault(tid, reason)
    new_ticket_ids = {o.ticket_id for _, _, o in ok("tickets")}
    ticket_ids = new_ticket_ids | base_ids["tickets"]

    # --- events and surveys: references and the bot rule ------------------------------------------------------
    for pos, _, e in ok("ticket_events"):
        if e.ticket_id in bad_ticket:
            reject("ticket_events", pos, TICKET_REJECTED)
        elif e.ticket_id not in ticket_ids or (e.queue_id is not None and e.queue_id not in known["queues"]) or (
                e.agent_id is not None and e.agent_id not in known["agents"]):
            reject("ticket_events", pos, UNKNOWN_REFERENCE)
        elif e.event_type == "replied_human" and is_bot(e.actor_id):
            reject("ticket_events", pos, BOT_AS_HUMAN_REPLY)
    for pos, _, s in ok("surveys"):
        if s.ticket_id in bad_ticket:
            reject("surveys", pos, TICKET_REJECTED)
        elif s.ticket_id not in ticket_ids:
            reject("surveys", pos, UNKNOWN_REFERENCE)

    # --- ticket rules -----------------------------------------------------------------------------------------
    tickets: dict[str, Ticket] = {t.ticket_id: t for t in base.tickets}
    tickets.update({o.ticket_id: o for _, _, o in ok("tickets")})
    new_ev = _group([(pos, e) for pos, _, e in ok("ticket_events")], lambda p: p[1].ticket_id)
    base_ev = _group(base.ticket_events, lambda e: e.ticket_id)
    skills_of_queue: dict[str, set[str]] = {}
    for q in [*base.queue_skills, *(o for _, _, o in ok("queue_skills"))]:
        skills_of_queue.setdefault(q.queue_id, set()).add(q.skill_id)
    agent_skills = _group([*base.agent_skills, *(o for _, _, o in ok("agent_skills"))], lambda s: s.agent_id)
    agents = {a.agent_id: a for a in [*base.agents, *(o for _, _, o in ok("agents"))]}

    reason_of: dict[str, str] = {}      # ticket -> reason code
    offender: dict[str, int | None] = {}  # ticket -> position of the new event that triggered it (None: unknown)

    def flag(tid: str, reason: str, pos: int | None) -> None:
        if tid not in reason_of:
            reason_of[tid] = reason
            offender[tid] = pos

    def events_of(tid: str) -> list[TicketEvent]:
        return [*base_ev.get(tid, []), *(e for _, e in new_ev.get(tid, []))]

    for tid in sorted(new_ev):
        t, evs = tickets[tid], events_of(tid)
        if any(e.event_type == "transferred" for e in evs) and t.created_at > min(e.occurred_at for e in evs):
            xfer = [p for p, e in new_ev[tid] if e.event_type == "transferred"]
            flag(tid, TRANSFER_RESETS_ARRIVAL, xfer[0] if xfer else None)
        for pos, e in new_ev[tid]:
            if e.event_type != "service_started":
                continue
            q = queue_at(t, evs, e.occurred_at)
            held = {s.skill_id for s in agent_skills.get(e.agent_id or "", []) if s.effective_from <= e.occurred_at}
            if not skills_of_queue.get(q or "", set()) <= held:
                flag(tid, AGENT_NOT_QUALIFIED, pos)

    # Concurrency, sequentially by start so the earlier start wins. Trusted intervals are in from the start.
    accepted_iv: dict[str, list[Any]] = {}
    for tid, evs in base_ev.items():
        for iv in replay(tickets[tid], evs).intervals if tid in tickets else []:
            accepted_iv.setdefault(iv.agent_id or "", []).append(iv)
    candidates = sorted(((e.occurred_at, e.event_id, pos, e) for tid, lst in new_ev.items()
                         for pos, e in lst if e.event_type in OPENERS and tid not in reason_of),
                        key=lambda c: (c[0], c[1]))
    history = {tid: replay(tickets[tid], events_of(tid)) for tid in new_ev}
    placed: dict[str, list[tuple[str, Any]]] = {}
    for at, _, pos, e in candidates:
        tid = e.ticket_id
        if tid in reason_of:
            continue
        iv = next((i for i in history[tid].intervals if i.start == at and i.agent_id == e.agent_id), None)
        if iv is None:
            continue
        ag = agents.get(iv.agent_id or "")
        cap = ag.max_concurrent if ag is not None else 1
        mine = accepted_iv.get(iv.agent_id or "", [])
        if interval_conflict(mine, iv, cap):
            flag(tid, CONCURRENCY_EXCEEDED, pos)
            for agent_key, ivs in list(accepted_iv.items()):   # a rejected ticket occupies nobody
                accepted_iv[agent_key] = [i for i in ivs if i.ticket_id != tid]
            continue
        accepted_iv.setdefault(iv.agent_id or "", []).append(iv)

    for tid, reason in reason_of.items():
        if tid in new_ticket_ids:
            for pos, row, o in parsed["tickets"]:
                if o is not None and o.ticket_id == tid and ("tickets", pos) not in bad:
                    bad[("tickets", pos)] = reason
            for pos, e in new_ev.get(tid, []):
                bad.setdefault(("ticket_events", pos), TICKET_REJECTED)
        else:  # a trusted ticket: only this batch's new events are rejected
            for pos, e in new_ev.get(tid, []):
                bad.setdefault(("ticket_events", pos), reason if pos == offender[tid] else TICKET_REJECTED)
        for pos, _, s in ok("surveys"):
            if s.ticket_id == tid:
                bad.setdefault(("surveys", pos), TICKET_REJECTED)

    # --- result -----------------------------------------------------------------------------------------------
    result = IngestResult()
    for ent in ENTITIES:
        result.accepted[ent], result.accepted_rows[ent] = [], []
        for pos, row, obj in parsed[ent]:
            if (ent, pos) not in bad and obj is not None:
                result.accepted[ent].append(obj)
                result.accepted_rows[ent].append(row)
    recs: list[RejectedRecord] = []
    for ent in ENTITIES:
        for pos, row, obj in parsed[ent]:
            if (ent, pos) in bad:
                recs.append(RejectedRecord(ent, row_id(ent, obj if obj is not None else row), bad[(ent, pos)],
                                           copy.deepcopy(row)))
    result.rejected = sorted(recs, key=lambda r: (r.entity, r.id))
    for ent in ENTITIES:
        result.counts[ent] = {"accepted": len(result.accepted[ent]),
                              "rejected": sum(1 for r in result.rejected if r.entity == ent)}
    return result
