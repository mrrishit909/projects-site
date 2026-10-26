"""Commands C01..C06, C08, C09 and two state-machine additions (docs/api-contract.md, docs/contracts.md D-01..D-05).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit
together or not at all. Input is validated (pydantic, then domain rules) before the first write. The same
``idempotency_key`` with the same payload (and the same actor) returns the stored response; with a different payload
or actor it is a 409.

D-08 lock order (every command, so two commands cannot deadlock on each other):
    1. the idempotency key (advisory lock)   2. ticket rows, sorted by ticket_id (``FOR UPDATE``)
    3. agent rows, sorted by agent_id (``FOR UPDATE``: serialises the concurrency count of one agent).
A deadlock or serialization failure that still happens is rolled back and retried, then answered 409 CONCURRENT_UPDATE.

Additions beyond the route table, needed to drive the state machine through the API: ``resume-work`` (the other half
of C05) and ``resolve-ticket``. C07 build-shift-scenario and C10 export-recommendation answer 501 NOT_IMPLEMENTED.
Roles: analyst, supervisor, admin. Ingest, simulation and comparison are open to all three; ticket-state commands
(C02-C06, resolve-ticket) need a supervisor or admin.
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import psycopg
from psycopg.types.json import Jsonb
from serviceflow.errors import INVALID_STATE
from serviceflow.events import Interval, History, interval_conflict, replay
from serviceflow.ingest import validate_batch
from serviceflow.simulation import compare_policies as sim_compare
from serviceflow.simulation import mean_ci95, parse_config, replicate
from serviceflow.timeutil import iso_z, parse_ts

from data.seed import COLUMNS, canonical_json, insert_rejected, insert_simulation, sha256_hex

from . import db
from .errors import ApiError, detail
from .schemas import Envelope

Conn = psycopg.Connection[db.Row]
ROLES = frozenset({"analyst", "supervisor", "admin"})
OPERATOR_ROLES = frozenset({"supervisor", "admin"})
_FAR = datetime(9999, 12, 31, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str


@dataclass
class Audit:
    entity_type: str
    entity_id: str
    action: str
    before_version: int | None = None
    after_version: int | None = None
    reason: str | None = None


@dataclass
class Outcome:
    status: str
    result: dict[str, Any]
    version: int = 1
    warnings: list[dict[str, Any]] = field(default_factory=list)
    audit: Audit | None = None


Handler = Callable[[Conn, Any, Actor], Outcome]


def _warning(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path}


def _not_found(path: str, rule_id: str, what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found", [detail(path, rule_id, f"{what} not found")])


def _conflict(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    item = detail(path, code, message)
    if context:
        item["context"] = context
    return ApiError(409, code, message, [item])


def _invalid(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    item = detail(path, code, message)
    if context:
        item["context"] = context
    return ApiError(422, "VALIDATION_FAILED", message, [item])


def _forbidden(code: str, message: str, path: str) -> ApiError:
    return ApiError(403, code, message, [detail(path, code, message)])


def _require_operator(actor: Actor) -> None:
    if actor.role not in OPERATOR_ROLES:
        raise _forbidden("ROLE_FORBIDDEN", "only a supervisor or admin changes a ticket's state",
                         "header.X-Actor-Role")


def _at(inp: Any, name: str = "occurred_at") -> datetime:
    value = getattr(inp, name, None)
    return parse_ts(value) if value else datetime.now(timezone.utc).replace(microsecond=0)


# --- idempotent execution ---------------------------------------------------------------------------------------

def _normalise(value: Any, key: str = "") -> Any:
    """Q-06: an instant (a string under a ``*_at`` key) is hashed as the UTC instant it names, re-serialised with Z, so
    ``+00:00``, ``Z`` and ``+01:00`` spellings of the same instant are the same payload. Applies at any depth."""
    if isinstance(value, dict):
        return {k: _normalise(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v, key) for v in value]
    if isinstance(value, str) and key.endswith("_at"):
        try:
            return iso_z(parse_ts(value))
        except ValueError:
            return value
    return value


def _payload_hash(name: str, req: Envelope) -> str:
    """sha256 over the canonical command name + dataset_version + input (request_id and key excluded; instants
    normalised). The dataset_version is part of the payload (R4-05): the same key with another version is a different
    request."""
    try:
        text = canonical_json({"command": name, "dataset_version": req.dataset_version,   # R4-05: part of the payload
                               "input": _normalise(req.input.model_dump())})  # type: ignore[attr-defined]
    except ValueError:  # NaN / Infinity are not JSON
        raise _invalid("JSON_NON_FINITE", "input contains a non-finite number", "input") from None
    if "\\u0000" in text:
        raise _invalid("NUL_CHARACTER", "input contains a NUL character", "input")
    return sha256_hex(text)


_UNIQUE_CODES = {
    "ticket_events_event_id_key": ("DUPLICATE_ID", "an event with this id already exists"),
    "tickets_pkey": ("DUPLICATE_ID", "a ticket with this id already exists"),
    "simulation_runs_pkey": ("SIMULATION_EXISTS", "a simulation with this id already exists"),
}

#: D-08: a deadlock or serialization failure rolls the whole command back; it is retried this many times in all.
MAX_ATTEMPTS = 3
_RETRYABLE = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)


def execute(name: str, req: Envelope, actor: Actor, handler: Handler) -> tuple[dict[str, Any], bool]:
    """Run ``handler`` once per idempotency key. Returns ``(response body, replayed)``.

    D-08: every attempt is one whole transaction. A deadlock or serialization failure is rolled back and retried
    (at most ``MAX_ATTEMPTS`` attempts, short randomised back-off); if the last attempt fails too the answer is
    409 CONCURRENT_UPDATE, never a 500."""
    payload_hash = _payload_hash(name, req)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _execute_once(name, req, actor, handler, payload_hash)
        except _RETRYABLE:
            if attempt < MAX_ATTEMPTS:
                time.sleep(random.uniform(0.005, 0.03) * attempt)
    raise _conflict("CONCURRENT_UPDATE", f"the command lost a concurrent update {MAX_ATTEMPTS} times; retry it", "input")


def _check_dataset_version(conn: Conn, req: Envelope) -> None:
    """D-09 / R4-05 (as SupplyScope D-07): the request names the dataset it was prepared against; a different current
    version is 409 STALE_DATASET_VERSION and nothing is written. A database with no dataset_versions row has nothing
    to be stale against (the request is accepted)."""
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC "
                       "LIMIT 1").fetchone()
    if row is not None and row["dataset_version"] != req.dataset_version:
        raise ApiError(409, "STALE_DATASET_VERSION",
                       f"the request was prepared against dataset {req.dataset_version!r}; the current dataset is "
                       f"{row['dataset_version']!r}",
                       [{**detail("dataset_version", "STALE_DATASET_VERSION",
                                  "re-read the data and retry with the current dataset_version"),
                         "context": {"current": row["dataset_version"], "requested": req.dataset_version}}])


def _execute_once(name: str, req: Envelope, actor: Actor, handler: Handler,
                  payload_hash: str) -> tuple[dict[str, Any], bool]:
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (req.idempotency_key,))
        prior = conn.execute("SELECT payload_hash, actor_id, result FROM command_results "
                             "WHERE idempotency_key = %s", (req.idempotency_key,)).fetchone()
        if prior is not None:
            if prior["actor_id"] != actor.actor_id:  # Q-06: bound to the actor
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "this idempotency_key was used by a different actor",
                               [detail("idempotency_key", "IDEMPOTENCY_ACTOR_MISMATCH", "same key, different X-Actor-Id")])
            if prior["payload_hash"] != payload_hash:
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "this idempotency_key was used with a different payload",
                               [detail("idempotency_key", "IDEMPOTENCY_PAYLOAD_MISMATCH",
                                       "same key, different payload_hash")])
            return prior["result"], True
        _check_dataset_version(conn, req)
        try:
            out = handler(conn, req, actor)
        except psycopg.errors.UniqueViolation as exc:
            code, message = _UNIQUE_CODES.get(exc.diag.constraint_name or "",
                                              ("ALREADY_EXISTS", "a row with this key already exists"))
            raise _conflict(code, message, "input") from None
        except psycopg.errors.IntegrityError as exc:  # triggers and checks: immutable log, arrival, bot reply ...
            raise _conflict("INTEGRITY_RULE", exc.diag.message_primary or "integrity rule violated", "input") from None
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        if out.audit is not None:
            a = out.audit
            conn.execute(
                "INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, "
                "before_version, after_version, reason, request_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (f"evt-{uuid.uuid4().hex[:16]}", a.entity_type, a.entity_id, a.action, actor.actor_id,
                 a.before_version, a.after_version, a.reason, req.request_id))
        body = {"command_id": command_id, "status": out.status, "result": out.result,
                "warnings": out.warnings, "version": out.version}
        conn.execute("INSERT INTO command_results (idempotency_key, payload_hash, actor_id, command_id, status, result) "
                     "VALUES (%s, %s, %s, %s, %s, %s)",
                     (req.idempotency_key, payload_hash, actor.actor_id, command_id, out.status, Jsonb(body)))
        return body, False


# --- shared lookups ---------------------------------------------------------------------------------------------

def _lock_tickets(conn: Conn, ids: list[str]) -> dict[str, db.Row]:
    """D-08 step 2: ticket rows ``FOR UPDATE`` in sorted order; returns the rows that exist."""
    rows = conn.execute("SELECT * FROM tickets WHERE ticket_id = ANY(%s) ORDER BY ticket_id FOR UPDATE",
                        (sorted(set(ids)),)).fetchall()
    return {r["ticket_id"]: r for r in rows}


def _lock_agents(conn: Conn, ids: list[str]) -> dict[str, db.Row]:
    """D-08 step 3: agent rows ``FOR UPDATE`` in sorted order (serialises the concurrency count per agent)."""
    rows = conn.execute("SELECT * FROM agents WHERE agent_id = ANY(%s) ORDER BY agent_id FOR UPDATE",
                        (sorted(set(ids)),)).fetchall()
    return {r["agent_id"]: r for r in rows}


def _ticket(conn: Conn, ticket_id: str) -> db.Row:
    row = _lock_tickets(conn, [ticket_id]).get(ticket_id)
    if row is None:
        raise _not_found("input.ticket_id", "TICKET_UNKNOWN", "ticket")
    return row


def _history(conn: Conn, ticket: db.Row) -> History:
    from serviceflow.models import _event, _ticket as parse_ticket  # typed records from trusted rows
    events = [_event(dict(r)) for r in conn.execute(
        "SELECT event_id, ticket_id, event_type, occurred_at, actor_id, queue_id, agent_id FROM ticket_events "
        "WHERE ticket_id = %s ORDER BY event_seq", (ticket["ticket_id"],)).fetchall()]
    return replay(parse_ticket(dict(ticket)), events)


def _state(h: History) -> str:
    return h.state_at(_FAR) or "new"


def _need_state(h: History, allowed: tuple[str, ...], what: str) -> str:
    state = _state(h)
    if state not in allowed:
        raise _conflict(INVALID_STATE, f"{what} needs a ticket that is {' or '.join(allowed)}; this one is {state}",
                        "input.ticket_id", {"state": state, "allowed": list(allowed)})
    return state


def _check_time(h: History, at: datetime) -> None:
    """Commands append to the live log: never before the arrival or the last event (late history goes through C01)."""
    last = max([e.occurred_at for e in h.events] + [h.arrival])
    if at < last:
        raise _invalid("EVENT_BEFORE_LAST", "a command cannot be dated before the ticket's latest event",
                       "input.occurred_at", {"latest": iso_z(last), "occurred_at": iso_z(at)})


def _insert_event(conn: Conn, ticket_id: str, event_type: str, at: datetime, actor_id: str | None,
                  queue_id: str | None, agent_id: str | None) -> str:
    event_id = f"ev-{uuid.uuid4().hex[:16]}"
    conn.execute("INSERT INTO ticket_events (event_id, ticket_id, event_type, occurred_at, actor_id, queue_id, agent_id) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)", (event_id, ticket_id, event_type, at, actor_id, queue_id, agent_id))
    return event_id


def _version(conn: Conn, ticket_id: str) -> int:
    """A ticket's version is its event count: the log is append-only, so it only ever grows."""
    return conn.execute("SELECT count(*) AS n FROM ticket_events WHERE ticket_id = %s", (ticket_id,)).fetchone()["n"]


def _queue_eligibility(conn: Conn, queue_id: str, at: datetime, path: str) -> list[str]:
    """P04-FLOW-03: the queue must exist, be active and have at least one active agent holding every skill it
    requires (effective at ``at``). Returns those agents; else 422 QUEUE_SKILL_MISMATCH."""
    q = conn.execute("SELECT * FROM queues WHERE queue_id = %s", (queue_id,)).fetchone()
    if q is None:
        raise _not_found(path, "QUEUE_UNKNOWN", "queue")
    if not q["active"]:
        raise _invalid("QUEUE_INACTIVE", "the queue is not active", path)
    required = [r["skill_id"] for r in conn.execute(
        "SELECT skill_id FROM queue_skills WHERE queue_id = %s ORDER BY skill_id", (queue_id,)).fetchall()]
    agents = [r["agent_id"] for r in conn.execute(
        "SELECT a.agent_id FROM agents a WHERE a.active AND NOT EXISTS ("
        " SELECT 1 FROM unnest(%s::text[]) AS need(skill_id) WHERE NOT EXISTS ("
        "  SELECT 1 FROM agent_skills s WHERE s.agent_id = a.agent_id AND s.skill_id = need.skill_id "
        "  AND s.effective_from <= %s)) ORDER BY a.agent_id", (required, at)).fetchall()]
    if not agents:
        raise _invalid("QUEUE_SKILL_MISMATCH", "no active agent holds every skill this queue requires", path,
                       {"required_skills": required})
    return agents


def _agent_intervals(conn: Conn, agent_id: str, exclude_ticket: str | None = None) -> list[Interval]:
    """Every service interval of one agent, replayed from the event log of the tickets they touched."""
    from serviceflow.models import _event, _ticket as parse_ticket
    out: list[Interval] = []
    ids = [r["ticket_id"] for r in conn.execute(
        "SELECT DISTINCT ticket_id FROM ticket_events WHERE agent_id = %s AND event_type IN ('service_started', 'resumed')",
        (agent_id,)).fetchall()]
    for tid in ids:
        if tid == exclude_ticket:
            continue
        t = conn.execute("SELECT * FROM tickets WHERE ticket_id = %s", (tid,)).fetchone()
        evs = [_event(dict(r)) for r in conn.execute(
            "SELECT event_id, ticket_id, event_type, occurred_at, actor_id, queue_id, agent_id FROM ticket_events "
            "WHERE ticket_id = %s", (tid,)).fetchall()]
        out += [iv for iv in replay(parse_ticket(dict(t)), evs).intervals if iv.agent_id == agent_id]
    return out


def _check_available(conn: Conn, agent_id: str, at: datetime) -> None:
    """D-01 / R4-03: an agent opens service (start or resume) only inside a shift and outside a recorded break."""
    if conn.execute("SELECT 1 FROM shifts WHERE agent_id = %s AND starts_at <= %s AND %s < ends_at",
                    (agent_id, at, at)).fetchone() is None:
        raise _invalid("AGENT_NOT_IN_SHIFT", "the agent has no shift at that instant", "input.agent_id")
    if conn.execute("SELECT 1 FROM shift_breaks WHERE agent_id = %s AND starts_at <= %s AND %s < ends_at",
                    (agent_id, at, at)).fetchone() is not None:
        raise _invalid("AGENT_ON_BREAK", "the agent is on a break at that instant (a break is not capacity)",
                       "input.agent_id")


def _check_concurrency(conn: Conn, agent: db.Row, ticket_id: str, at: datetime) -> None:
    """P04-TEST-04: opening a service interval at ``at`` must keep the agent within ``max_concurrent``."""
    existing = _agent_intervals(conn, agent["agent_id"], exclude_ticket=ticket_id)
    new = Interval(ticket_id, agent["agent_id"], at, None, 0)
    if interval_conflict(existing, new, agent["max_concurrent"]):
        busy = sum(1 for iv in existing if iv.start <= at and (iv.end is None or at < iv.end))
        raise _invalid("CONCURRENCY_EXCEEDED", "the agent is already serving as many tickets as they may", "input.agent_id",
                       {"max_concurrent": agent["max_concurrent"], "in_service_at_that_instant": busy})


# --- C01 ingest-ticket-events -----------------------------------------------------------------------------------

def ingest_ticket_events(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    raw = {k: v for k, v in inp.model_dump().items()}
    payload_hash = _payload_hash("ingest-ticket-events", req)
    batch_id = f"batch-{payload_hash[:16]}"

    def ids(rows: list[dict], key: str) -> list[str]:
        return [r[key] for r in rows if isinstance(r, dict) and isinstance(r.get(key), str)]

    touched = ids(raw["tickets"], "ticket_id") + ids(raw["ticket_events"], "ticket_id") + ids(raw["surveys"], "ticket_id")
    agents = ids(raw["ticket_events"], "agent_id")
    _lock_tickets(conn, touched)             # D-08: tickets first ...
    _lock_agents(conn, agents)               # ... then agents
    base = db.load_population(conn)
    existing = {t.ticket_id for t in base.tickets}
    if actor.role not in OPERATOR_ROLES and set(ids(raw["ticket_events"], "ticket_id")) & existing:
        # R4-04 / D-09: C01 must not be a back door round C02-C06: an analyst may ingest new tickets only.
        raise _forbidden("ROLE_FORBIDDEN", "only a supervisor or admin adds events to an existing ticket; an analyst "
                         "ingests new tickets", "header.X-Actor-Role")
    ing = validate_batch(raw, base)
    inserted: dict[str, int] = {}
    for ent in ("customers", "queues", "agents", "skills", "agent_skills", "queue_skills", "shifts", "sla_policies",
                "tickets", "ticket_events", "surveys"):
        cols = COLUMNS[ent]
        sql = f"INSERT INTO {ent} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"  # constants
        for row in ing.accepted_rows[ent]:
            conn.execute(sql, [row.get(c) for c in cols])
        inserted[ent] = len(ing.accepted_rows[ent])
    # A transferred history moves the ticket's CURRENT queue; the arrival (created_at) never moves.
    from serviceflow.events import queue_at
    tickets_now = {t.ticket_id: t for t in [*base.tickets, *ing.accepted["tickets"]]}
    all_events = [*base.ticket_events, *ing.accepted["ticket_events"]]
    for tid in sorted({e.ticket_id for e in ing.accepted["ticket_events"]}):
        now_q = queue_at(tickets_now[tid], [e for e in all_events if e.ticket_id == tid], _FAR)
        if now_q and now_q != tickets_now[tid].queue_id:
            conn.execute("UPDATE tickets SET queue_id = %s WHERE ticket_id = %s", (now_q, tid))
    total_rows = sum(len(v) for v in raw.values())
    status = "accepted" if not ing.rejected else ("partial" if sum(inserted.values()) else "rejected")
    conn.execute("INSERT INTO raw_batches (batch_id, idempotency_key, payload_hash, payload, status) "
                 "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                 (batch_id, req.idempotency_key, payload_hash, Jsonb(raw), status))
    insert_rejected(conn, batch_id, ing.rejected)
    result = {"batch_id": batch_id, "received": total_rows, "inserted": inserted, "counts": ing.counts,
              "rejected_records": [{"entity": r.entity, "id": r.id, "reason_code": r.reason_code} for r in ing.rejected]}
    return Outcome("loaded" if not ing.rejected else status, result, 1,
                   [_warning(r.reason_code, f"{r.entity} {r.id or '(no id)'} rejected", f"input.{r.entity}[{r.id}]")
                    for r in ing.rejected],
                   Audit("raw_batch", batch_id, "ingest-ticket-events"))


# --- C02 assign-queue -------------------------------------------------------------------------------------------

def assign_queue(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _require_operator(actor)
    inp = req.input
    at = _at(inp)
    ticket = _ticket(conn, inp.ticket_id)
    h = _history(conn, ticket)
    _need_state(h, ("new", "reopened"), "assign-queue")
    _check_time(h, at)
    eligible = _queue_eligibility(conn, inp.queue_id, at, "input.queue_id")
    before = _version(conn, inp.ticket_id)
    event_id = _insert_event(conn, inp.ticket_id, "queued", at, actor.actor_id, inp.queue_id, None)
    conn.execute("UPDATE tickets SET queue_id = %s WHERE ticket_id = %s", (inp.queue_id, inp.ticket_id))
    return Outcome("queued", {"ticket_id": inp.ticket_id, "queue_id": inp.queue_id, "state": "queued",
                              "event_id": event_id, "occurred_at": iso_z(at), "eligible_agents": eligible},
                   before + 1, audit=Audit("ticket", inp.ticket_id, "assign-queue", before, before + 1))


# --- C03 start-service ------------------------------------------------------------------------------------------

def start_service(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _require_operator(actor)
    inp = req.input
    at = _at(inp)
    ticket = _ticket(conn, inp.ticket_id)                       # D-08: ticket, then agent
    agent = _lock_agents(conn, [inp.agent_id]).get(inp.agent_id)
    if agent is None:
        raise _not_found("input.agent_id", "AGENT_UNKNOWN", "agent")
    h = _history(conn, ticket)
    _need_state(h, ("queued",), "start-service")
    _check_time(h, at)
    if not agent["active"]:
        raise _invalid("AGENT_INACTIVE", "the agent is not active", "input.agent_id")
    _check_available(conn, inp.agent_id, at)
    queue = h.queue_id or ticket["queue_id"]
    missing = [r["skill_id"] for r in conn.execute(
        "SELECT q.skill_id FROM queue_skills q WHERE q.queue_id = %s AND NOT EXISTS ("
        " SELECT 1 FROM agent_skills s WHERE s.agent_id = %s AND s.skill_id = q.skill_id AND s.effective_from <= %s) "
        "ORDER BY q.skill_id", (queue, inp.agent_id, at)).fetchall()]
    if missing:
        raise _invalid("AGENT_NOT_QUALIFIED", "the agent lacks a skill the queue requires", "input.agent_id",
                       {"queue_id": queue, "missing_skills": missing})
    _check_concurrency(conn, agent, inp.ticket_id, at)
    before = _version(conn, inp.ticket_id)
    ids = [_insert_event(conn, inp.ticket_id, "service_started", at, inp.agent_id, queue, inp.agent_id)]
    if inp.reply:
        ids.append(_insert_event(conn, inp.ticket_id, "replied_human", at, inp.agent_id, queue, inp.agent_id))
    return Outcome("started", {"ticket_id": inp.ticket_id, "agent_id": inp.agent_id, "queue_id": queue,
                               "state": "in_service", "event_ids": ids, "occurred_at": iso_z(at)},
                   before + len(ids), audit=Audit("ticket", inp.ticket_id, "start-service", before, before + len(ids)))


# --- C04 transfer-ticket ----------------------------------------------------------------------------------------

def transfer_ticket(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _require_operator(actor)
    inp = req.input
    at = _at(inp)
    ticket = _ticket(conn, inp.ticket_id)
    h = _history(conn, ticket)
    _need_state(h, ("queued", "in_service", "waiting_customer"), "transfer-ticket")
    _check_time(h, at)
    if (h.queue_id or ticket["queue_id"]) == inp.to_queue_id:
        raise _invalid("SAME_QUEUE", "the ticket is already in that queue", "input.to_queue_id")
    _queue_eligibility(conn, inp.to_queue_id, at, "input.to_queue_id")
    before = _version(conn, inp.ticket_id)
    from_q = h.queue_id or ticket["queue_id"]
    event_id = _insert_event(conn, inp.ticket_id, "transferred", at, actor.actor_id, inp.to_queue_id, None)
    conn.execute("UPDATE tickets SET queue_id = %s WHERE ticket_id = %s", (inp.to_queue_id, inp.ticket_id))
    after = conn.execute("SELECT created_at FROM tickets WHERE ticket_id = %s", (inp.ticket_id,)).fetchone()
    assert after["created_at"] == ticket["created_at"]    # the arrival is untouched (also guarded by a trigger)
    return Outcome("transferred", {"ticket_id": inp.ticket_id, "from_queue_id": from_q, "to_queue_id": inp.to_queue_id,
                                   "state": "queued", "event_id": event_id, "occurred_at": iso_z(at),
                                   "created_at": iso_z(after["created_at"]), "arrival_preserved": True,
                                   "transfers": len(h.transfers) + 1,
                                   "note": "waiting restarts in the new queue; the first-response and resolution "
                                           "clocks keep running from the original arrival"},
                   before + 1, audit=Audit("ticket", inp.ticket_id, "transfer-ticket", before, before + 1))


# --- C05 pause-work (+ resume-work) -----------------------------------------------------------------------------

def pause_work(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _require_operator(actor)
    inp = req.input
    at = _at(inp)
    ticket = _ticket(conn, inp.ticket_id)
    h = _history(conn, ticket)
    _need_state(h, ("in_service",), "pause-work")
    _check_time(h, at)
    policy = conn.execute("SELECT * FROM sla_policies WHERE priority = %s ORDER BY sla_policy_id LIMIT 1",
                          (ticket["priority"],)).fetchone()
    if policy is None:
        raise _invalid("SLA_POLICY_MISSING", f"no SLA policy for priority {ticket['priority']}: a pause must be "
                       "differentiated by the policy", "input.ticket_id", {"priority": ticket["priority"]})
    agent = h.owner_agent
    before = _version(conn, inp.ticket_id)
    event_id = _insert_event(conn, inp.ticket_id, "paused", at, agent, h.queue_id, agent)
    return Outcome("paused", {"ticket_id": inp.ticket_id, "state": "waiting_customer", "event_id": event_id,
                              "occurred_at": iso_z(at), "handling_clock": "stopped",
                              "sla_clocks": "running: first-response and resolution clocks do not pause (D-02)",
                              "sla_policy": {"sla_policy_id": policy["sla_policy_id"], "priority": policy["priority"],
                                             "first_response_minutes": policy["first_response_minutes"],
                                             "resolution_minutes": policy["resolution_minutes"]}},
                   before + 1, audit=Audit("ticket", inp.ticket_id, "pause-work", before, before + 1))


def resume_work(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _require_operator(actor)
    inp = req.input
    at = _at(inp)
    ticket = _ticket(conn, inp.ticket_id)
    h = _history(conn, ticket)
    _need_state(h, ("waiting_customer",), "resume-work")
    _check_time(h, at)
    agent_id = h.owner_agent
    agent = _lock_agents(conn, [agent_id]).get(agent_id or "")
    if agent is None:
        raise _invalid("AGENT_UNKNOWN", "the paused ticket has no agent to resume with", "input.ticket_id")
    _check_available(conn, agent["agent_id"], at)          # R4-03: the same availability rule as start-service
    _check_concurrency(conn, agent, inp.ticket_id, at)
    before = _version(conn, inp.ticket_id)
    event_id = _insert_event(conn, inp.ticket_id, "resumed", at, agent_id, h.queue_id, agent_id)
    return Outcome("resumed", {"ticket_id": inp.ticket_id, "agent_id": agent_id, "state": "in_service",
                               "event_id": event_id, "occurred_at": iso_z(at)},
                   before + 1, audit=Audit("ticket", inp.ticket_id, "resume-work", before, before + 1))


def resolve_ticket(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _require_operator(actor)
    inp = req.input
    at = _at(inp)
    ticket = _ticket(conn, inp.ticket_id)
    h = _history(conn, ticket)
    _need_state(h, ("in_service",), "resolve-ticket")
    _check_time(h, at)
    agent = h.owner_agent
    before = _version(conn, inp.ticket_id)
    event_id = _insert_event(conn, inp.ticket_id, "resolved", at, agent, h.queue_id, agent)
    return Outcome("resolved", {"ticket_id": inp.ticket_id, "state": "resolved", "event_id": event_id,
                                "occurred_at": iso_z(at), "cycle": len(h.cycles) - 1},
                   before + 1, audit=Audit("ticket", inp.ticket_id, "resolve-ticket", before, before + 1))


# --- C06 reopen-ticket ------------------------------------------------------------------------------------------

def reopen_ticket(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _require_operator(actor)
    inp = req.input
    at = _at(inp)
    ticket = _ticket(conn, inp.ticket_id)
    h = _history(conn, ticket)
    _need_state(h, ("resolved",), "reopen-ticket")
    _check_time(h, at)
    prior = h.cycles[-1]
    before = _version(conn, inp.ticket_id)
    event_id = _insert_event(conn, inp.ticket_id, "reopened", at, actor.actor_id, h.queue_id, None)
    return Outcome("reopened", {"ticket_id": inp.ticket_id, "state": "reopened", "event_id": event_id,
                                "occurred_at": iso_z(at), "prior_cycle": prior.index, "cycle": prior.index + 1,
                                "prior_resolved_at": iso_z(prior.resolved_at), "reopen_count": h.reopen_count + 1,
                                "customer_contacts": 1,
                                "note": "a reopen links the prior cycle; the ticket stays one customer contact"},
                   before + 1, audit=Audit("ticket", inp.ticket_id, "reopen-ticket", before, before + 1))


# --- C08 run-simulation / C09 compare-policies ------------------------------------------------------------------

def _valid_config(cfg: dict[str, Any], path: str) -> None:
    try:
        parse_config(cfg)
    except ValueError as exc:
        raise _invalid("INVALID_CONFIG", str(exc), path) from None


def run_simulation(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    _valid_config(inp.config, "input.config")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"simulation:{inp.simulation_id}",))
    if conn.execute("SELECT 1 FROM simulation_runs WHERE simulation_id = %s", (inp.simulation_id,)).fetchone():
        raise _conflict("SIMULATION_EXISTS", "a simulation with this id already exists", "input.simulation_id")
    try:
        runs = replicate(inp.config, inp.seed, inp.replications, inp.warmup_minutes, inp.horizon_minutes,
                         inp.simulation_id)
    except ValueError as exc:
        raise _invalid("INVALID_CONFIG", str(exc), "input") from None
    insert_simulation(conn, {"simulation_id": inp.simulation_id, "seed": inp.seed,
                             "warmup_minutes": inp.warmup_minutes, "policy_version": inp.policy_version,
                             "horizon_minutes": inp.horizon_minutes, "config": inp.config}, inp.replications)
    first = runs[0]
    means = [r.mean_wait for r in runs if r.mean_wait is not None]
    result = {**first.golden(), "statistics": first.statistics(),
              "replications": {"count": inp.replications, "seeds": [r.seed for r in runs],
                               "mean_wait_minutes": mean_ci95(means),
                               "stored_events": "replication 1 (the declared seed)"},
              "label": "simulated estimate, not an observed result"}
    return Outcome("simulated", result, 1, audit=Audit("simulation", inp.simulation_id, "run-simulation"))


def compare_policies(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    _valid_config(inp.baseline, "input.baseline")
    _valid_config(inp.proposal, "input.proposal")
    try:
        result = sim_compare(inp.baseline, inp.proposal, inp.seed, inp.replications, inp.warmup_minutes,
                             inp.horizon_minutes)
    except ValueError as exc:
        raise _invalid("INVALID_CONFIG", str(exc), "input") from None
    return Outcome("compared", result, 1, audit=Audit("comparison", f"seed-{inp.seed}", "compare-policies"))


# --- extension commands -----------------------------------------------------------------------------------------

def not_implemented(name: str, code: str) -> ApiError:
    return ApiError(501, "NOT_IMPLEMENTED", f"{name} ({code}) is an extension-milestone command and is not implemented",
                    [detail("command", "NOT_IMPLEMENTED", f"{name} is not implemented in this milestone")])


__all__ = ["Actor", "ROLES", "OPERATOR_ROLES", "execute", "ingest_ticket_events", "assign_queue", "start_service",
           "transfer_ticket", "pause_work", "resume_work", "resolve_ticket", "reopen_ticket", "run_simulation",
           "compare_policies", "not_implemented"]
