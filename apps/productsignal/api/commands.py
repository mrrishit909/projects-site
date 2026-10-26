"""Commands C01..C10 (docs/api-contract.md, docs/contracts.md D-01..D-05; backend conventions in README.md).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit together or not
at all. Input is validated (pydantic, then domain rules) before the first write. The same ``idempotency_key`` with the same
payload, the same actor id and the same role returns the stored response; with a different payload, actor or role it is a 409.

Lock order (every command, so two commands cannot deadlock on each other):
    1. the idempotency key (advisory lock; C01 and C02 also take advisory locks on their natural keys)
    2. experiment version rows, by id (``FOR SHARE`` for C04, C05, C07, C09; ``FOR UPDATE`` for C06, C08, C10)
    3. unit rows (accounts), sorted by id (``FOR UPDATE``)
A deadlock or serialization failure that still happens is rolled back and retried, three attempts in all, then answered
409 CONCURRENT_UPDATE.

Roles (X-Actor-Role): analyst | experimenter | admin.  C01-C03, C07-C09: analyst, experimenter, admin.  C04-C06, C10:
experimenter, admin.  Reads need no actor. C10 records a decision and nothing else: no product state is ever written.
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Any, Callable

import psycopg
from productsignal.contract import DECISIONS, ROLES as ROLE_LIST
from productsignal.errors import (ASSIGNMENT_CONFLICT, DUPLICATE_ID, EXPOSURE_BEFORE_ASSIGNMENT, IDENTITY_CONFLICT,
                                  INELIGIBLE_UNIT, INTERIM_RUN_CANNOT_SHIP, NOT_INTENTION_TO_TREAT, PLAN_NOT_FROZEN,
                                  SEGMENT_NOT_A_DECISION_BASIS, SRM_MISMATCH_BLOCKS_DECISION,
                                  TREATMENT_DEPENDENT_EXCLUSION, UNIT_MISMATCH, UNKNOWN_ASSIGNMENT, UNKNOWN_UNIT,
                                  UNKNOWN_USER, UNKNOWN_VARIANT, DomainError)
from productsignal.events import canonicalise, late_arrivals, late_event_summary
from productsignal.ingest import validate_batch
from productsignal.metrics import (EXCLUSION_FIELDS, Ctx, allowed_after_exclusions, experiment, guardrail_review)
from productsignal.models import AnalysisRun, canonical_json as plan_canonical_json, parse_funnel, parse_plan, plan_hash
from productsignal.timeutil import UTC, iso_z, local_date, parse_ts
from psycopg.types.json import Jsonb

from data.seed import canonical_json, insert_rejected, sha256_hex

from . import clock, db
from .errors import ApiError, detail
from .schemas import Envelope

Conn = psycopg.Connection[db.Row]
ROLES = frozenset(ROLE_LIST)
ALL_ROLES = ROLES
DESIGN_ROLES = frozenset({"experimenter", "admin"})
WORK_ROLES = ROLES


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
    experiment_version_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Outcome:
    status: str
    result: dict[str, Any]
    version: int = 1
    warnings: list[dict[str, Any]] = field(default_factory=list)
    audit: Audit | list[Audit] | None = None


Handler = Callable[[Conn, Any, Actor], Outcome]


def _warning(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path}


def _err(status: int, code: str, rule_id: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    item = detail(path, rule_id, message)
    if context:
        item["context"] = context
    return ApiError(status, code, message, [item])


def _not_found(path: str, rule_id: str, what: str) -> ApiError:
    return _err(404, "NOT_FOUND", rule_id, f"{what} not found", path)


def _conflict(code: str, message: str, path: str, context: dict[str, Any] | None = None, rule_id: str | None = None) -> ApiError:
    return _err(409, code, rule_id or code, message, path, context)


def _invalid(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    return _err(422, "VALIDATION_FAILED", code, message, path, context)


def _forbidden(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    return _err(403, "FORBIDDEN", code, message, path, context)


def _need_role(actor: Actor, allowed: frozenset[str], what: str) -> None:
    if actor.role not in allowed:
        raise _forbidden("ROLE_FORBIDDEN", f"{what} needs the role {' or '.join(sorted(allowed))}", "header.X-Actor-Role")


def _now() -> datetime:
    return clock.now()


def _at(value: str | None) -> datetime:
    return parse_ts(value) if value else _now().replace(microsecond=0)


def _domain(err: DomainError, path: str) -> ApiError:
    return _invalid(err.code, err.message, err.path or path, err.details or None)


# --- idempotent execution ---------------------------------------------------------------------------------------

def _normalise(value: Any, key: str = "") -> Any:
    """An instant (a string under a ``*_at``, ``cutoff``, ``from`` or ``to`` key) is hashed as the UTC instant it names, so
    ``+00:00``, ``Z`` and ``+01:00`` spellings of the same instant are the same payload."""
    if isinstance(value, dict):
        return {k: _normalise(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v, key) for v in value]
    if isinstance(value, str) and (key.endswith("_at") or key in ("cutoff", "from", "to", "planned_end")):
        try:
            return iso_z(parse_ts(value))
        except ValueError:
            return value
    return value


def _payload_hash(name: str, req: Envelope) -> str:
    """sha256 over the canonical command name + dataset_version + input (request_id and key excluded; instants normalised).
    The dataset_version is part of the payload: the same key with another version is a different request."""
    body = _normalise(req.input.model_dump(by_alias=True))  # type: ignore[attr-defined]
    try:
        text = canonical_json({"command": name, "dataset_version": req.dataset_version, "input": body})
    except ValueError:
        raise _invalid("JSON_NON_FINITE", "input contains a non-finite number", "input") from None
    if "\\u0000" in text:
        raise _invalid("NUL_CHARACTER", "input contains a NUL character", "input")
    return sha256_hex(text)


#: A deadlock or serialization failure rolls the whole command back; it is retried this many times in all.
MAX_ATTEMPTS = 3
_RETRYABLE = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)


def execute(name: str, req: Envelope, actor: Actor, handler: Handler, roles: frozenset[str] = ALL_ROLES) -> tuple[dict[str, Any], bool]:
    """Run ``handler`` once per idempotency key. Returns ``(response body, replayed)``. A deadlock is retried
    (``MAX_ATTEMPTS`` attempts in all, short randomised back-off); the last failure is 409 CONCURRENT_UPDATE, never a 500."""
    _need_role(actor, roles, name)
    payload_hash = _payload_hash(name, req)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _execute_once(name, req, actor, handler, payload_hash)
        except _RETRYABLE:
            if attempt < MAX_ATTEMPTS:
                time.sleep(random.uniform(0.005, 0.03) * attempt)
    raise _conflict("CONCURRENT_UPDATE", f"the command lost a concurrent update {MAX_ATTEMPTS} times; retry it", "input")


def _check_dataset_version(conn: Conn, req: Envelope) -> None:
    """The request names the dataset it was prepared against; a different current version is 409 STALE_DATASET_VERSION and
    nothing is written. A database with no dataset_versions row has nothing to be stale against."""
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    if row is not None and row["dataset_version"] != req.dataset_version:
        raise ApiError(409, "STALE_DATASET_VERSION",
                       f"the request was prepared against dataset {req.dataset_version!r}; the current dataset is "
                       f"{row['dataset_version']!r}",
                       [{**detail("dataset_version", "STALE_DATASET_VERSION",
                                  "re-read the data and retry with the current dataset_version"),
                         "context": {"current": row["dataset_version"], "requested": req.dataset_version}}])


_UNIQUE_CODES = {
    "assignments_unit_uq": ("ASSIGNMENT_CONFLICT", "the unit already has an assignment in this experiment version"),
    "exposures_asg_uq": ("ALREADY_EXPOSED", "the assignment already has an exposure"),
    "decisions_uq": ("DECISION_ALREADY_RECORDED", "this analysis run already has a decision"),
    "reviews_uq": ("REVIEW_ALREADY_RECORDED", "this analysis run already has a guardrail review"),
    "links_anon_uq": ("IDENTITY_CONFLICT", "this anonymous_id is already linked"),
    "analysis_plans_pkey": ("PLAN_ALREADY_FROZEN", "this experiment version already has a frozen plan"),
    "funnel_definitions_pkey": ("CONCURRENT_UPDATE", "another request defined this funnel version first; retry"),
}


def _execute_once(name: str, req: Envelope, actor: Actor, handler: Handler, payload_hash: str) -> tuple[dict[str, Any], bool]:
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (req.idempotency_key,))
        prior = conn.execute("SELECT payload_hash, actor_id, actor_role, result FROM command_results "
                             "WHERE idempotency_key = %s", (req.idempotency_key,)).fetchone()
        if prior is not None:
            if prior["actor_id"] != actor.actor_id or prior["actor_role"] != actor.role:   # bound to the actor and the role
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "this idempotency_key was used by a different actor or role",
                               [detail("idempotency_key", "IDEMPOTENCY_ACTOR_MISMATCH", "same key, different X-Actor-Id or X-Actor-Role")])
            if prior["payload_hash"] != payload_hash:
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "this idempotency_key was used with a different payload",
                               [detail("idempotency_key", "IDEMPOTENCY_PAYLOAD_MISMATCH", "same key, different payload_hash")])
            return prior["result"], True
        _check_dataset_version(conn, req)
        try:
            out = handler(conn, req, actor)
        except psycopg.errors.UniqueViolation as exc:
            code, message = _UNIQUE_CODES.get(exc.diag.constraint_name or "", ("ALREADY_EXISTS", "a row with this key already exists"))
            raise _conflict(code, message, "input") from None
        except psycopg.errors.IntegrityError as exc:  # checks and triggers: append-only, exposure order, eligibility ...
            msg = exc.diag.message_primary or "integrity rule violated"
            rule = msg.split(":", 1)[0] if msg.split(":", 1)[0].isupper() else "INTEGRITY_RULE"
            raise _conflict("INTEGRITY_RULE", msg, "input", rule_id=rule) from None
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        for a in ([] if out.audit is None else out.audit if isinstance(out.audit, list) else [out.audit]):
            conn.execute(
                "INSERT INTO audit_events (event_id, entity_type, entity_id, experiment_version_id, action, actor_id, before_version, "
                "after_version, reason, request_id, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (f"evt-{uuid.uuid4().hex[:16]}", a.entity_type, a.entity_id, a.experiment_version_id, a.action, actor.actor_id,
                 a.before_version, a.after_version, a.reason, req.request_id, Jsonb(a.details)))
        body = {"command_id": command_id, "status": out.status, "result": out.result, "warnings": out.warnings, "version": out.version}
        conn.execute("INSERT INTO command_results (idempotency_key, payload_hash, actor_id, actor_role, command_id, status, result) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (req.idempotency_key, payload_hash, actor.actor_id, actor.role, command_id, out.status, Jsonb(body)))
        return body, False


def _refusal(actor: Actor, req: Envelope, action: str, entity_id: str, xv: str | None, rule_id: str, message: str) -> None:
    """Keep a refused decision in the audit trail (its own transaction: the command's is about to roll back)."""
    with db.autocommit() as c:
        c.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, experiment_version_id, action, actor_id, reason, "
                  "request_id, details) VALUES (%s, 'experiment', %s, %s, %s, %s, %s, %s, %s)",
                  (f"evt-{uuid.uuid4().hex[:16]}", entity_id, xv, f"{action}-refused", actor.actor_id, message, req.request_id,
                   Jsonb({"rule_id": rule_id, "actor_role": actor.role})))


# --- shared lookups and locks -----------------------------------------------------------------------------------

def _lock_version(conn: Conn, xv: str, exclusive: bool, path: str = "input.experiment_version_id") -> db.Row:
    """Lock order step 2: the experiment version row (``FOR SHARE`` or ``FOR UPDATE``)."""
    row = conn.execute(f"SELECT * FROM experiment_versions WHERE experiment_version_id = %s FOR {'UPDATE' if exclusive else 'SHARE'}",
                       (xv,)).fetchone()
    if row is None:
        raise _not_found(path, "EXPERIMENT_VERSION_UNKNOWN", "experiment version")
    return row


def _lock_accounts(conn: Conn, ids: list[str]) -> dict[str, db.Row]:
    """Lock order step 3: unit rows (accounts) ``FOR UPDATE`` in sorted order; returns the rows that exist."""
    rows = conn.execute("SELECT * FROM accounts WHERE account_id = ANY(%s) ORDER BY account_id FOR UPDATE", (sorted(set(ids)),)).fetchall()
    return {r["account_id"]: r for r in rows}


def _plan_row(conn: Conn, xv: str) -> db.Row | None:
    return conn.execute("SELECT * FROM analysis_plans WHERE experiment_version_id = %s", (xv,)).fetchone()


def _plan(conn: Conn, xv: str):
    row = _plan_row(conn, xv)
    if row is None:
        raise _conflict(PLAN_NOT_FROZEN, "this experiment version has no frozen analysis plan (C06 freeze-analysis-plan first)",
                        "input.experiment_version_id", {"experiment_version_id": xv})
    return parse_plan(row["plan"], row["config_hash"])


def _persist_rejection(req: Any, batch: str, rejected: list[Any]) -> None:
    """A rejected record keeps its raw row in ``rejected_records`` even though the command is refused (own transaction)."""
    if rejected:
        with db.autocommit() as c:
            insert_rejected(c, batch, rejected)


def _batch_id(req: Any) -> str:
    return f"batch-{sha256_hex(req.idempotency_key)[:16]}"


# --- C01 validate-tracking --------------------------------------------------------------------------------------

def validate_tracking(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """raw -> canonical events: schema, identity (unknown identity flagged), delayed, duplicates (re-sent events are logged and
    dropped from every figure, counted here). The log is immutable: a re-sent event_id with the same content is merged, with
    different content it is rejected."""
    inp = req.input
    now = _now()
    events: list[dict[str, Any]] = []
    for r in inp.events:
        r = dict(r)
        if r.get("received_at") is not None:
            if actor.role != "admin":
                raise _forbidden("RECEIVED_AT_ADMIN_ONLY", "received_at is the log's own clock; only an admin may backfill it",
                                 "input.events.received_at")
            try:
                if parse_ts(r["received_at"]) > now:
                    raise _invalid("RECEIVED_IN_FUTURE", "an event cannot have been received in the future", "input.events.received_at")
            except ValueError:
                pass                                          # malformed: the domain rejects the row with MALFORMED_RECORD
        else:
            r["received_at"] = iso_z(now)
        events.append(r)
    batch = validate_batch({"events": events, "event_properties": [dict(p) for p in inp.properties]})
    rejected = list(batch.rejected)
    accepted = batch.accepted["events"]
    props: dict[str, dict[str, str]] = {}
    for p in batch.accepted["event_properties"]:
        props.setdefault(p.event_id, {})[p.property_key] = p.property_value

    existing = {r["event_id"]: r for r in conn.execute(
        "SELECT e.*, coalesce((SELECT jsonb_object_agg(property_key, property_value) FROM event_properties p WHERE p.event_id = e.event_id), "
        "'{}'::jsonb) AS props FROM events e WHERE event_id = ANY(%s)", ([e.event_id for e in accepted],)).fetchall()}
    fresh, merged = [], []
    from productsignal.models import Event  # noqa: PLC0415
    for e in accepted:
        old = existing.get(e.event_id)
        if old is None:
            fresh.append(e)
        elif (old["user_id"], old["anonymous_id"], old["event_name"], old["event_at"], old["props"]) == \
                (e.user_id, e.anonymous_id, e.event_name, e.event_at, props.get(e.event_id, {})):
            merged.append(e)
        else:
            from productsignal.ingest import Rejection  # noqa: PLC0415
            raw = next(r for r in events if r.get("event_id") == e.event_id)
            rejected.append(Rejection("events", e.event_id, DUPLICATE_ID, raw, "this event_id is logged with different content"))
            fresh = [f for f in fresh if f.event_id != e.event_id]
    # duplicates by key: against the log and within the batch; the earliest (received_at, event_id) survives
    keys = {(e.user_id or e.anonymous_id, e.event_name, e.event_at) for e in fresh}
    log_by_key: dict[tuple, list[tuple]] = {}
    if keys:
        for r in conn.execute(
                "SELECT e.event_id, e.received_at, coalesce(e.user_id, e.anonymous_id) AS actor, e.event_name, e.event_at, "
                "coalesce((SELECT jsonb_object_agg(property_key, property_value) FROM event_properties p WHERE p.event_id = e.event_id), "
                "'{}'::jsonb) AS props FROM events e WHERE (coalesce(e.user_id, e.anonymous_id), e.event_name, e.event_at) IN "
                "(SELECT * FROM unnest(%s::text[], %s::text[], %s::timestamptz[]))",
                ([k[0] for k in keys], [k[1] for k in keys], [k[2] for k in keys])).fetchall():
            log_by_key.setdefault((r["actor"], r["event_name"], r["event_at"], tuple(sorted(r["props"].items()))), []).append(
                (r["received_at"], r["event_id"]))
    for e in fresh:
        log_by_key.setdefault((e.user_id or e.anonymous_id, e.event_name, e.event_at, tuple(sorted(props.get(e.event_id, {}).items()))), []).append(
            (e.received_at, e.event_id))
    users = {r["user_id"] for r in conn.execute("SELECT user_id FROM users WHERE user_id = ANY(%s)",
                                                  ([e.user_id for e in fresh if e.user_id],)).fetchall()}
    first_links = {r["anonymous_id"]: r for r in conn.execute(
        "SELECT anonymous_id, user_id, linked_at FROM identity_links WHERE anonymous_id = ANY(%s)",
        ([e.anonymous_id for e in fresh if e.anonymous_id and not e.user_id],)).fetchall()}
    flags = []
    counts = {"duplicate": 0, "unknown_identity": 0, "delayed": 0, "attributed_by_link": 0, "remain_anonymous": 0}
    for e in sorted(fresh, key=lambda e: (e.received_at, e.event_id)):
        k = (e.user_id or e.anonymous_id, e.event_name, e.event_at, tuple(sorted(props.get(e.event_id, {}).items())))
        survivor = min(log_by_key[k])[1]
        dup = survivor != e.event_id
        unknown = (e.user_id is None and e.anonymous_id is None) or (e.user_id is not None and e.user_id not in users)
        link = first_links.get(e.anonymous_id) if e.user_id is None and e.anonymous_id else None
        attributed = link["user_id"] if link is not None and link["linked_at"] <= e.event_at else None
        delayed = e.received_at - e.event_at > timedelta(hours=24)
        status = "duplicate" if dup else "unknown_identity" if unknown else "canonical"
        counts["duplicate"] += dup
        counts["unknown_identity"] += unknown and not dup
        counts["delayed"] += delayed
        if e.user_id is None and e.anonymous_id and not unknown:
            counts["attributed_by_link" if attributed else "remain_anonymous"] += 1
        flags.append({"event_id": e.event_id, "status": status, "duplicate_of": survivor if dup else None, "delayed": delayed,
                      "attributed_user_id": attributed, "event_at": iso_z(e.event_at), "received_at": iso_z(e.received_at)})
    for e in fresh:
        conn.execute("INSERT INTO events (event_id, user_id, anonymous_id, event_name, event_at, received_at, ingested_by) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (e.event_id, e.user_id, e.anonymous_id, e.event_name, e.event_at, e.received_at, actor.actor_id))
    fresh_ids = {e.event_id for e in fresh}
    for p in batch.accepted["event_properties"]:
        if p.event_id in fresh_ids:
            conn.execute("INSERT INTO event_properties VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         (p.property_id, p.event_id, p.property_key, p.property_value, p.value_type))
    bid = _batch_id(req)
    if rejected and not fresh and not merged:
        _persist_rejection(req, bid, rejected)
        raise ApiError(422, "VALIDATION_FAILED", "every event in the batch was rejected",
                       [detail(f"input.{r.entity}[{r.id}]", r.reason_code, r.message or r.reason_code) for r in rejected[:50]])
    if rejected:
        _persist_rejection(req, bid, rejected)
    result = {"batch_id": bid, "accepted": len(fresh), "merged": len(merged), "rejected": len(rejected),
              "canonical": len(fresh) - counts["duplicate"] - counts["unknown_identity"],
              "duplicates": counts["duplicate"], "unknown_identity": counts["unknown_identity"], "delayed_over_24h": counts["delayed"],
              "anonymous_attributed_by_link": counts["attributed_by_link"], "anonymous_remaining": counts["remain_anonymous"],
              "events": flags, "rejected_records": [r.as_dict() for r in rejected]}
    warns = [_warning(r.reason_code, f"{r.entity} {r.id} was rejected: {r.message or r.reason_code}", f"input.{r.entity}") for r in rejected[:20]]
    if counts["duplicate"]:
        warns.append(_warning("DUPLICATES_DROPPED", f"{counts['duplicate']} re-sent event(s) are logged and dropped from every figure", "input.events"))
    if counts["unknown_identity"]:
        warns.append(_warning("UNKNOWN_IDENTITY", f"{counts['unknown_identity']} event(s) have an unknown identity and are excluded", "input.events"))
    if counts["delayed"]:
        warns.append(_warning("DELAYED_EVENTS", f"{counts['delayed']} event(s) were received more than 24 h after they happened", "input.events"))
    return Outcome("partial" if rejected else "accepted", result, 1, warns,
                   Audit("tracking_batch", bid, "validate-tracking", details={k: result[k] for k in
                         ("accepted", "merged", "rejected", "canonical", "duplicates", "unknown_identity")}))


# --- C02 resolve-identity ---------------------------------------------------------------------------------------

def resolve_identity(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """anonymous -> linked. The link attributes the anonymous events of ``anonymous_id`` at or after ``linked_at`` only; the
    earlier ones stay anonymous (never applied backward). The earliest link of an anonymous_id fixes its user."""
    inp = req.input
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"identity:{inp.anonymous_id}",))
    user = conn.execute("SELECT * FROM users WHERE user_id = %s FOR SHARE", (inp.user_id,)).fetchone()
    if user is None:
        raise _not_found("input.user_id", UNKNOWN_USER, "user")
    at = _at(inp.linked_at)
    if at > _now() + timedelta(seconds=1):
        raise _invalid("LINK_IN_FUTURE", "an identity link cannot be dated in the future", "input.linked_at")
    link = conn.execute("SELECT * FROM identity_links WHERE anonymous_id = %s", (inp.anonymous_id,)).fetchone()
    if link is not None and link["user_id"] != inp.user_id:
        raise _conflict(IDENTITY_CONFLICT, "this anonymous_id is already linked to another user (the earliest link wins)",
                        "input.anonymous_id", {"linked_user_id": link["user_id"], "linked_at": iso_z(link["linked_at"])})
    status = "linked"
    if link is None:
        lid = inp.identity_link_id or f"il-{uuid.uuid4().hex[:12]}"
        link = conn.execute("INSERT INTO identity_links (identity_link_id, anonymous_id, user_id, linked_at, rule_version, created_by) "
                            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *", (lid, inp.anonymous_id, inp.user_id, at, inp.rule_version, actor.actor_id)).fetchone()
    else:
        status = "already_linked"
    n = conn.execute("SELECT count(*) FILTER (WHERE event_at >= %s) AS after, count(*) FILTER (WHERE event_at < %s) AS before "
                     "FROM events WHERE anonymous_id = %s AND user_id IS NULL", (link["linked_at"], link["linked_at"], inp.anonymous_id)).fetchone()
    result = {"identity_link_id": link["identity_link_id"], "anonymous_id": inp.anonymous_id, "user_id": inp.user_id,
              "linked_at": iso_z(link["linked_at"]), "rule_version": link["rule_version"], "status": status,
              "events_attributed": n["after"], "events_remaining_anonymous": n["before"],
              "rule": "a link attributes anonymous events at or after linked_at; earlier events stay anonymous"}
    warns = [_warning("BOT_USER", "the user is a bot: its events are excluded from every figure", "input.user_id")] if user["bot_flag"] else []
    return Outcome(status, result, 1, warns,
                   Audit("identity_link", link["identity_link_id"], "resolve-identity", details={"anonymous_id": inp.anonymous_id, "user_id": inp.user_id,
                                                                                                 "status": status}))


# --- C03 define-funnel ------------------------------------------------------------------------------------------

def define_funnel(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """draft -> versioned funnel: ordered steps, a maximum gap (hours, inclusive) and a window on the first step. A new definition
    under an existing definition_id is the next version; versions are never edited."""
    inp = req.input
    raw = {"definition_id": inp.definition_id, "steps": inp.steps, "max_gap_hours": inp.max_gap_hours,
           "from": inp.window.from_, "to": inp.window.to}
    try:
        fd = parse_funnel(raw)
    except DomainError as err:
        raise _domain(err, "input") from None
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"funnel:{inp.definition_id}",))
    ver = conn.execute("SELECT coalesce(max(version), 0) + 1 AS v FROM funnel_definitions WHERE definition_id = %s", (inp.definition_id,)).fetchone()["v"]
    conn.execute("INSERT INTO funnel_definitions (definition_id, version, steps, max_gap_hours, window_from, window_to, created_by) "
                 "VALUES (%s,%s,%s,%s,%s,%s,%s)", (fd.definition_id, ver, list(fd.steps), fd.max_gap_hours, fd.window_from, fd.window_to, actor.actor_id))
    result = {"definition_id": fd.definition_id, "version": ver, "steps": list(fd.steps), "max_gap_hours": fd.max_gap_hours,
              "window": {"from": iso_z(fd.window_from), "to": iso_z(fd.window_to)}, "status": "versioned",
              "rule": "a unit reaches step k only after step k-1, within the gap; the window applies to the first step"}
    return Outcome("versioned", result, ver, audit=Audit("funnel", f"{fd.definition_id}@{ver}", "define-funnel", ver - 1, ver,
                                                          details={"steps": list(fd.steps)}))


# --- C04 assign-experiment --------------------------------------------------------------------------------------

def assign_experiment(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """eligible unit -> fixed variant, idempotent per (experiment_version_id, unit_id): the first assignment fixes the variant;
    the same variant again returns it, another variant is 409 ASSIGNMENT_CONFLICT."""
    inp = req.input
    _lock_version(conn, inp.experiment_version_id, exclusive=False)                    # lock order: the version row ...
    unit = _lock_accounts(conn, [inp.unit_id]).get(inp.unit_id)                         # ... then the unit row
    if unit is None:
        raise _not_found("input.unit_id", UNKNOWN_UNIT, "unit (account)")
    if unit["internal"]:
        raise _invalid(INELIGIBLE_UNIT, "internal accounts are not randomised (eligibility is decided before assignment)", "input.unit_id")
    plan_row = _plan_row(conn, inp.experiment_version_id)
    variants = list(plan_row["plan"]["allocation"]) if plan_row else ["control", "treatment"]
    if inp.variant not in variants:
        raise _invalid(UNKNOWN_VARIANT, f"the variant must be one of {', '.join(variants)}", "input.variant", {"variants": variants})
    prior = conn.execute("SELECT * FROM assignments WHERE experiment_version_id = %s AND unit_id = %s",
                         (inp.experiment_version_id, inp.unit_id)).fetchone()
    if prior is not None:
        if prior["variant"] != inp.variant:
            raise _conflict(ASSIGNMENT_CONFLICT, "the first assignment of a unit fixes its variant", "input.variant",
                            {"assignment_id": prior["assignment_id"], "variant": prior["variant"]})
        result = {"assignment_id": prior["assignment_id"], "experiment_version_id": inp.experiment_version_id, "unit_id": inp.unit_id,
                  "variant": prior["variant"], "assigned_at": iso_z(prior["assigned_at"]), "status": "already_assigned"}
        return Outcome("already_assigned", result, 1,
                       [_warning("ALREADY_ASSIGNED", "the unit already has this variant; nothing changed", "input.unit_id")],
                       Audit("assignment", prior["assignment_id"], "assign-experiment", experiment_version_id=inp.experiment_version_id,
                             details={"status": "already_assigned"}))
    at = _at(inp.assigned_at)
    aid = inp.assignment_id or f"as-{uuid.uuid4().hex[:12]}"
    if conn.execute("SELECT 1 FROM assignments WHERE assignment_id = %s", (aid,)).fetchone():
        raise _conflict(DUPLICATE_ID, "an assignment with this id exists for another unit", "input.assignment_id")
    conn.execute("INSERT INTO assignments (assignment_id, experiment_version_id, unit_id, variant, assigned_at, created_by) "
                 "VALUES (%s,%s,%s,%s,%s,%s)", (aid, inp.experiment_version_id, inp.unit_id, inp.variant, at, actor.actor_id))
    result = {"assignment_id": aid, "experiment_version_id": inp.experiment_version_id, "unit_id": inp.unit_id, "variant": inp.variant,
              "assigned_at": iso_z(at), "status": "assigned"}
    return Outcome("assigned", result, 1, audit=Audit("assignment", aid, "assign-experiment", None, 1,
                                                      experiment_version_id=inp.experiment_version_id,
                                                      details={"unit_id": inp.unit_id, "variant": inp.variant}))


# --- C05 record-exposure ----------------------------------------------------------------------------------------

def record_exposure(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """assigned -> exposed: exposed_at >= assigned_at (else EXPOSURE_BEFORE_ASSIGNMENT, the raw row is kept as rejected). A unit
    is exposed once: the first exposure fixes exposed_at."""
    inp = req.input
    a = conn.execute("SELECT * FROM assignments WHERE assignment_id = %s", (inp.assignment_id,)).fetchone()   # immutable row
    if a is None:
        raise _not_found("input.assignment_id", UNKNOWN_ASSIGNMENT, "assignment")
    _lock_version(conn, a["experiment_version_id"], exclusive=False)
    _lock_accounts(conn, [a["unit_id"]])
    at = _at(inp.exposed_at)
    if at < a["assigned_at"]:
        from productsignal.ingest import Rejection  # noqa: PLC0415
        raw = {"exposure_id": inp.exposure_id or "", "assignment_id": inp.assignment_id, "exposed_at": iso_z(at), "surface": inp.surface,
               "event_id": inp.event_id}
        _persist_rejection(req, _batch_id(req), [Rejection("exposures", inp.exposure_id or f"exp-{inp.assignment_id}",
                                                           EXPOSURE_BEFORE_ASSIGNMENT, raw)])
        raise _invalid(EXPOSURE_BEFORE_ASSIGNMENT, "an exposure cannot precede its assignment", "input.exposed_at",
                       {"assigned_at": iso_z(a["assigned_at"])})
    prior = conn.execute("SELECT * FROM exposures WHERE assignment_id = %s", (inp.assignment_id,)).fetchone()
    if prior is not None:
        result = {"exposure_id": prior["exposure_id"], "assignment_id": inp.assignment_id, "exposed_at": iso_z(prior["exposed_at"]),
                  "surface": prior["surface"], "status": "already_exposed"}
        return Outcome("already_exposed", result, 1, [_warning("ALREADY_EXPOSED", "the first exposure fixes exposed_at; nothing changed",
                                                              "input.assignment_id")],
                       Audit("exposure", prior["exposure_id"], "record-exposure", experiment_version_id=a["experiment_version_id"],
                             details={"status": "already_exposed"}))
    eid = inp.exposure_id or f"ex-{uuid.uuid4().hex[:12]}"
    conn.execute("INSERT INTO exposures (exposure_id, assignment_id, exposed_at, surface, event_id, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
                 (eid, inp.assignment_id, at, inp.surface, inp.event_id, actor.actor_id))
    result = {"exposure_id": eid, "assignment_id": inp.assignment_id, "experiment_version_id": a["experiment_version_id"],
              "unit_id": a["unit_id"], "variant": a["variant"], "exposed_at": iso_z(at), "surface": inp.surface, "status": "exposed"}
    return Outcome("exposed", result, 1, audit=Audit("exposure", eid, "record-exposure", None, 1,
                                                    experiment_version_id=a["experiment_version_id"], details={"assignment_id": inp.assignment_id}))


# --- C06 freeze-analysis-plan -----------------------------------------------------------------------------------

def freeze_analysis_plan(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """draft -> registered plan, before any outcome is read: refused once the version has an analysis run or a plan. The plan
    (primary outcome, guardrail, horizon, allocation, SRM rule) is hashed: ``config_hash`` is the sha256 of its compact
    key-sorted JSON, and every analysis run cites it."""
    inp = req.input
    ver = _lock_version(conn, inp.experiment_version_id, exclusive=True)
    now = _now()
    frozen_at = parse_ts(inp.frozen_at) if inp.frozen_at else now.replace(microsecond=0)
    if frozen_at > now + timedelta(seconds=1):
        raise _invalid("FROZEN_AT_IN_FUTURE", "a plan cannot be frozen in the future", "input.frozen_at")
    body = {"experiment_version_id": inp.experiment_version_id, "primary_metric": inp.primary_metric, "unit_type": inp.unit_type,
            "allocation": dict(inp.allocation), "planned_end": iso_z(parse_ts(inp.planned_end)),
            "activation_window_days": inp.activation_window_days,
            "guardrail": {"metric": inp.guardrail.metric, "window_days": inp.guardrail.window_days},
            "revenue_window": {"from": iso_z(parse_ts(inp.revenue_window.from_)), "to": iso_z(parse_ts(inp.revenue_window.to))},
            "confidence": inp.confidence, "z": inp.z,
            "srm": {"p_threshold": inp.srm.p_threshold, "min_expected_cell": inp.srm.min_expected_cell},
            "frozen_at": iso_z(frozen_at)}
    if inp.unit_type != ver["unit_type"]:
        raise _invalid("UNIT_MISMATCH", "the plan's unit_type must be the experiment version's (account)", "input.unit_type")
    try:
        plan = parse_plan(body, plan_hash(body))
    except DomainError as err:
        raise _domain(err, "input") from None
    if plan.planned_end != ver["planned_end"] or plan.primary_metric != ver["primary_metric"]:
        raise _invalid("PLAN_VERSION_MISMATCH", "planned_end and primary_metric must be those of the experiment version",
                       "input.planned_end", {"planned_end": iso_z(ver["planned_end"]), "primary_metric": ver["primary_metric"]})
    if plan.planned_end <= frozen_at:
        raise _invalid("INVALID_WINDOW", "planned_end must be after the freeze", "input.planned_end")
    if _plan_row(conn, inp.experiment_version_id) is not None:
        raise _conflict("PLAN_ALREADY_FROZEN", "this experiment version already has a frozen plan; a frozen plan is never edited "
                        "(a re-plan is a new experiment version)", "input.experiment_version_id")
    runs = conn.execute("SELECT count(*) AS n FROM analysis_runs WHERE experiment_version_id = %s", (inp.experiment_version_id,)).fetchone()["n"]
    if runs:
        raise _conflict("OUTCOME_ALREADY_READ", "an analysis run already read outcomes of this version: the plan can no longer be frozen "
                        "before them", "input.experiment_version_id", {"runs": runs})
    conn.execute("INSERT INTO analysis_plans (experiment_version_id, plan, config_hash, frozen_at, frozen_by) VALUES (%s,%s,%s,%s,%s)",
                 (plan.experiment_version_id, Jsonb(body), plan.config_hash, frozen_at, actor.actor_id))
    result = {"experiment_version_id": plan.experiment_version_id, "config_hash": plan.config_hash, "frozen_at": iso_z(frozen_at),
              "frozen_by": actor.actor_id, "plan": body, "status": "frozen"}
    return Outcome("frozen", result, 1, audit=Audit("analysis_plan", plan.experiment_version_id, "freeze-analysis-plan", None, 1,
                                                    experiment_version_id=plan.experiment_version_id,
                                                    details={"config_hash": plan.config_hash}))


# --- C07 check-maturity -----------------------------------------------------------------------------------------

def check_maturity(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """cohort -> eligible observation: which assigned units have a complete activation window (signup + window <= cutoff) and
    which a complete day-7 (day 8 begun) and week-4 (day 35 begun) calendar in their own timezone. Mature units get an
    ``activation`` observation row (value and window_end derived from the events received by the cutoff; never the source of
    the result)."""
    inp = req.input
    ver = _lock_version(conn, inp.experiment_version_id, exclusive=False)
    plan = _plan(conn, inp.experiment_version_id)
    cutoff = _at(inp.cutoff)
    units = sorted({r["unit_id"] for r in conn.execute(           # D-08: assigned by the cutoff only
        "SELECT unit_id FROM assignments WHERE experiment_version_id = %s AND assigned_at <= %s", (inp.experiment_version_id, cutoff)).fetchall()})
    _lock_accounts(conn, units)                                                       # lock order: unit rows by id
    pop = db.load_population(conn)
    canon = canonicalise(pop, cutoff)
    ctx = Ctx(pop, cutoff, canon, set(units))
    win = plan.activation_window_days
    asg = {a.unit_id: a for a in pop.assignments if a.experiment_version_id == inp.experiment_version_id and a.assigned_at <= cutoff}
    have = {r["assignment_id"] for r in conn.execute(
        "SELECT assignment_id FROM metric_observations WHERE metric_name = 'activation_7d' AND assignment_id IN "
        "(SELECT assignment_id FROM assignments WHERE experiment_version_id = %s)", (inp.experiment_version_id,)).fetchall()}
    stats = {"assigned_units": len(units), "no_signup_unobserved": 0, "immature": 0, "mature": 0, "observations_written": 0,
             "observations_existing": 0, "day7_mature": 0, "day7_immature": 0, "week4_mature": 0, "week4_immature": 0}
    for u in units:
        if u not in ctx.signup_at:
            stats["no_signup_unobserved"] += 1
            continue
        if not ctx.mature(u, win):
            stats["immature"] += 1
        else:
            stats["mature"] += 1
            a = asg[u]
            if a.assignment_id in have:
                stats["observations_existing"] += 1
            else:
                conn.execute("INSERT INTO metric_observations (observation_id, assignment_id, metric_name, value, window_end) "
                             "VALUES (%s,%s,'activation_7d',%s,%s) ON CONFLICT DO NOTHING",
                             (f"ob-{uuid.uuid4().hex[:12]}", a.assignment_id, "1" if ctx.activated_within(u, win) else "0",
                              ctx.signup_at[u] + timedelta(days=win)))
                stats["observations_written"] += 1
        d0 = ctx.local(u, ctx.signup_at[u])
        dc = local_date(cutoff, ctx.accounts[u].timezone)
        stats["day7_mature" if d0 + timedelta(days=8) <= dc else "day7_immature"] += 1
        stats["week4_mature" if d0 + timedelta(days=35) <= dc else "week4_immature"] += 1
    result = {"experiment_version_id": inp.experiment_version_id, "cutoff_at": iso_z(cutoff), "activation_window_days": win,
              "rules": {"activation": "signup_at + window <= cutoff", "day7": "day 8 has begun in the account timezone",
                        "week4": "day 35 has begun in the account timezone"}, **stats}
    warns = []
    if stats["immature"] or stats["no_signup_unobserved"]:
        warns.append(_warning("IMMATURE_EXCLUDED", f"{stats['immature']} immature and {stats['no_signup_unobserved']} unobserved unit(s) are "
                              "excluded from the primary result and counted", "result.immature"))
    return Outcome("checked", result, 1, warns,
                   Audit("experiment", inp.experiment_version_id, "check-maturity", experiment_version_id=inp.experiment_version_id,
                         details={k: stats[k] for k in ("mature", "immature", "observations_written")}))


# --- C08 analyze-experiment -------------------------------------------------------------------------------------

def _decision_support(block: dict[str, Any], exclusions: list[dict[str, Any]], plan: Any) -> dict[str, Any]:
    blocked = []
    if block["srm"]["verdict"] == "MISMATCH":
        blocked.append("SRM_MISMATCH")
    if block["run"]["interim"]:
        blocked.append("INTERIM_RUN")
    if exclusions:
        blocked.append("PLAN_DEVIATION")
    if not plan.hash_valid or not block["run"]["config_hash_matches_plan"]:
        blocked.append("PLAN_HASH_INVALID")
    return {"ship_allowed": not blocked, "blocked_by": blocked, "lift_interpretable": block["srm"]["verdict"] != "MISMATCH"}


def _primary_signature(block: dict[str, Any]) -> Any:
    p = block["primary"]
    return {"variants": p["variants"], "absolute_lift_pp": p["absolute_lift_pp"], "relative_lift": p["relative_lift"],
            "interval": p["interval"], "mature_units": block["mature_units"], "assigned_units": block["assigned_units"]}


def analyze_experiment(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """frozen plan -> results: intention-to-treat on the account, the sample ratio first, Wilson and Newcombe intervals, the run
    logged with the plan hash and the count of prior runs. Refused before the freeze; interim before planned_end; a request
    for another unit, another analysis or a treatment-dependent exclusion is refused with its reason."""
    inp = req.input
    if inp.analysis_unit != "account":
        raise _invalid(UNIT_MISMATCH, "the experiment is randomised by account: an analysis at another unit (users, sessions) is "
                       "refused because the units are not independent", "input.analysis_unit", {"unit_type": "account"})
    if inp.analysis != "intention_to_treat":
        raise _invalid(NOT_INTENTION_TO_TREAT, "the primary analysis is intention-to-treat: an exposed-only or per-protocol "
                       "analysis is exploratory and is never a decision basis", "input.analysis")
    exclusions = []
    for i, e in enumerate(inp.exclusions):
        if e.field not in EXCLUSION_FIELDS:
            raise _invalid(TREATMENT_DEPENDENT_EXCLUSION, f"an exclusion may only use a fact decided before assignment "
                           f"({', '.join(EXCLUSION_FIELDS)}); {e.field!r} can depend on the treatment", f"input.exclusions[{i}].field",
                           {"allowed": list(EXCLUSION_FIELDS)})
        exclusions.append({"field": e.field, "values": list(e.values), "pre_assignment": True})
    _lock_version(conn, inp.experiment_version_id, exclusive=True)
    plan = _plan(conn, inp.experiment_version_id)                                     # refused before the freeze
    now = _now()
    cutoff = parse_ts(inp.cutoff) if inp.cutoff else now.replace(microsecond=0)
    analysis_id = f"an-{uuid.uuid4().hex[:12]}"
    pop = db.load_population(conn)
    pop.analysis_runs.append(AnalysisRun(analysis_id, plan.experiment_version_id, cutoff, plan.config_hash, now))
    canon = canonicalise(pop, cutoff)
    allowed = allowed_after_exclusions(pop, exclusions) if exclusions else None
    block = experiment(Ctx(pop, cutoff, canon, allowed), plan, analysis_id)
    support = _decision_support(block, exclusions, plan)
    prior = conn.execute("SELECT analysis_id, cutoff_at, result FROM analysis_runs WHERE experiment_version_id = %s AND cutoff_at < %s "
                         "AND result IS NOT NULL ORDER BY cutoff_at DESC, created_at DESC LIMIT 1",
                         (plan.experiment_version_id, cutoff)).fetchone()
    revision = None
    if prior is not None:
        late = late_arrivals(pop, prior["cutoff_at"], cutoff)
        if late:
            revision = {"of_analysis_id": prior["analysis_id"], "prior_cutoff_at": iso_z(prior["cutoff_at"]),
                        "late_events": late_event_summary(late),
                        "primary_changed": _primary_signature(prior["result"]) != _primary_signature(block),
                        "note": "events that happened by the earlier cutoff but were received after it: this run differs from the "
                                "earlier one as a disclosed revision; the earlier published result is unchanged"}
    result = {"analysis_id": analysis_id, "experiment_version_id": plan.experiment_version_id, "cutoff_at": iso_z(cutoff),
              "srm": block["srm"], "run": block["run"],
              **{k: v for k, v in block.items() if k not in ("srm", "run", "experiment_version_id")},
              "analysis": "intention_to_treat", "analysis_unit": "account", "exclusions": exclusions,
              "tracking_quality": canon.tracking_quality(), "identity": canon.identity(), "revision": revision,
              "decision_support": support}
    conn.execute("INSERT INTO analysis_runs (analysis_id, experiment_version_id, cutoff_at, config_hash, created_at, created_by, interim, "
                 "srm_verdict, conclusive, prior_runs, result) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                 (analysis_id, plan.experiment_version_id, cutoff, plan.config_hash, now, actor.actor_id, block["run"]["interim"],
                  block["srm"]["verdict"], block["primary"]["conclusive"], block["run"]["prior_runs"], Jsonb(result)))
    warns = []
    if block["srm"]["verdict"] == "MISMATCH":
        warns.append(_warning("SRM_MISMATCH", "the assignment counts do not match the allocation: no lift can be trusted and a ship "
                              "decision is blocked", "result.srm"))
    if block["run"]["interim"]:
        warns.append(_warning("INTERIM_RUN", f"the cutoff is before planned_end ({block['run']['planned_end']}): this is an interim run "
                              f"(prior runs: {block['run']['prior_runs']}) and cannot support ship", "result.run.interim"))
    if exclusions:
        warns.append(_warning("PLAN_DEVIATION", "exclusions are not part of the frozen plan: a ship decision is blocked", "input.exclusions"))
    if revision:
        warns.append(_warning("REVISION_DISCLOSED", f"{revision['late_events']['count']} late event(s) changed this run against "
                              f"{revision['of_analysis_id']}", "result.revision"))
    if not block["primary"]["conclusive"]:
        warns.append(_warning("NOT_CONCLUSIVE", "the result is not conclusive (interval includes 0, interim run or no comparison)",
                              "result.primary.conclusive"))
    n_prior = block["run"]["prior_runs"] or 0
    return Outcome("interim" if block["run"]["interim"] else "final", result, n_prior + 1, warns,
                   Audit("analysis_run", analysis_id, "analyze-experiment", n_prior, n_prior + 1,
                         experiment_version_id=plan.experiment_version_id,
                         details={"cutoff_at": iso_z(cutoff), "interim": block["run"]["interim"], "srm": block["srm"]["verdict"],
                                  "config_hash": plan.config_hash, "conclusive": block["primary"]["conclusive"]}))


# --- C09 review-guardrails --------------------------------------------------------------------------------------

def _run_evidence(conn: Conn, run: db.Row, plan: Any) -> dict[str, Any]:
    """The stored result of a run, or (for a run logged without one, such as a seeded run) the same figures recomputed at its
    cutoff; the run is deterministic in (cutoff, received events)."""
    if run["result"] is not None:
        return run["result"]
    pop = db.load_population(conn)
    cutoff = run["cutoff_at"]
    block = experiment(Ctx(pop, cutoff, canonicalise(pop, cutoff), None), plan, run["analysis_id"])
    return {**block, "exclusions": [], "decision_support": _decision_support(block, [], plan), "recomputed": True}


def review_guardrails(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """result -> decision evidence: the run's guardrail over the plan's prespecified window (the request cannot change it)."""
    inp = req.input
    run = conn.execute("SELECT * FROM analysis_runs WHERE analysis_id = %s", (inp.analysis_id,)).fetchone()
    if run is None:
        raise _not_found("input.analysis_id", "ANALYSIS_UNKNOWN", "analysis run")
    xv = run["experiment_version_id"]
    _lock_version(conn, xv, exclusive=False)
    plan = _plan(conn, xv)
    prior = conn.execute("SELECT * FROM guardrail_reviews WHERE analysis_id = %s", (inp.analysis_id,)).fetchone()
    if prior is not None:
        return Outcome("already_reviewed", {"review_id": prior["review_id"], "analysis_id": inp.analysis_id, "verdict": prior["verdict"],
                                            **prior["result"], "status": "already_reviewed"}, 1,
                       [_warning("ALREADY_REVIEWED", "the guardrail of this run was already reviewed; the stored review is returned", "input.analysis_id")])
    review = guardrail_review(_run_evidence(conn, run, plan), plan)
    rid = f"gr-{uuid.uuid4().hex[:12]}"
    conn.execute("INSERT INTO guardrail_reviews (review_id, analysis_id, experiment_version_id, verdict, result, reviewed_by) "
                 "VALUES (%s,%s,%s,%s,%s,%s)", (rid, inp.analysis_id, xv, review["verdict"], Jsonb(review), actor.actor_id))
    result = {"review_id": rid, "analysis_id": inp.analysis_id, "experiment_version_id": xv, "verdict": review["verdict"], **review,
              "status": "reviewed"}
    warns = [_warning("GUARDRAIL_HARMFUL", "treatment raises the error rate: a ship decision is blocked", "result.verdict")] \
        if review["verdict"] == "HARMFUL" else []
    return Outcome("reviewed", result, 1, warns, Audit("guardrail_review", rid, "review-guardrails", experiment_version_id=xv,
                                                       details={"analysis_id": inp.analysis_id, "verdict": review["verdict"]}))


# --- C10 record-decision ----------------------------------------------------------------------------------------

def record_decision(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """evidence -> ship | stop | inconclusive. Cites one analysis run and its guardrail review. Needs a frozen plan. ``ship``
    needs a non-interim run, a sample ratio that is not MISMATCH, no plan deviation and no guardrail harm; ``stop`` needs a
    sample ratio that is not MISMATCH; ``inconclusive`` is always an honest outcome. A decision never changes product state."""
    inp = req.input
    xv = inp.experiment_version_id
    if inp.decision not in DECISIONS:
        raise _invalid("DECISION_INVALID", f"decision must be one of {', '.join(DECISIONS)}", "input.decision")
    if inp.basis != "primary":
        raise _invalid(SEGMENT_NOT_A_DECISION_BASIS, "a decision rests on the primary intention-to-treat result; a segment result is "
                       "exploratory and cannot be cited", "input.basis")
    _lock_version(conn, xv, exclusive=True)
    plan = _plan(conn, xv)                                                             # needs a frozen plan
    run = conn.execute("SELECT * FROM analysis_runs WHERE analysis_id = %s", (inp.analysis_id,)).fetchone()
    if run is None or run["experiment_version_id"] != xv:
        raise _not_found("input.analysis_id", "ANALYSIS_UNKNOWN", "analysis run of this experiment version")
    review = conn.execute("SELECT * FROM guardrail_reviews WHERE review_id = %s", (inp.review_id,)).fetchone()
    if review is None:
        raise _not_found("input.review_id", "REVIEW_UNKNOWN", "guardrail review")
    if review["analysis_id"] != inp.analysis_id:
        raise _invalid("REVIEW_MISMATCH", "the guardrail review belongs to another analysis run", "input.review_id")
    if conn.execute("SELECT 1 FROM decisions WHERE analysis_id = %s", (inp.analysis_id,)).fetchone():
        raise _conflict("DECISION_ALREADY_RECORDED", "this analysis run already has a decision", "input.analysis_id")
    ev = _run_evidence(conn, run, plan)
    srm, interim = ev["srm"]["verdict"], ev["run"]["interim"]
    if inp.decision in ("ship", "stop") and srm == "MISMATCH":
        _refusal(actor, req, "record-decision", xv, xv, SRM_MISMATCH_BLOCKS_DECISION, "sample ratio mismatch")
        raise _conflict(SRM_MISMATCH_BLOCKS_DECISION, "the sample ratio mismatches the allocation: randomisation cannot be trusted, so "
                        f"no {inp.decision} decision can rest on this run (record inconclusive)", "input.analysis_id", {"srm": ev["srm"]})
    if inp.decision == "ship":
        if interim:
            _refusal(actor, req, "record-decision", xv, xv, INTERIM_RUN_CANNOT_SHIP, "interim run presented as final")
            raise _conflict(INTERIM_RUN_CANNOT_SHIP, "the run is interim (its cutoff is before planned_end): an interim run cannot "
                            "support ship", "input.analysis_id", {"cutoff_at": ev["run"]["cutoff_at"], "planned_end": ev["run"]["planned_end"]})
        if ev.get("exclusions"):
            raise _conflict("PLAN_DEVIATION_BLOCKS_SHIP", "the run applied exclusions that are not in the frozen plan", "input.analysis_id")
        if not ev["run"]["config_hash_matches_plan"] or not plan.hash_valid:
            raise _conflict("PLAN_HASH_INVALID_BLOCKS_SHIP", "the run does not cite the frozen plan's hash", "input.analysis_id")
        if review["verdict"] == "HARMFUL":
            raise _conflict("GUARDRAIL_HARM_BLOCKS_SHIP", "the guardrail review found more errors under treatment", "input.review_id")
    at = _at(inp.decided_at)
    did = f"dc-{uuid.uuid4().hex[:12]}"
    evidence = {"analysis_id": inp.analysis_id, "review_id": inp.review_id, "config_hash": plan.config_hash, "srm_verdict": srm,
                "interim": interim, "conclusive": ev["primary"]["conclusive"], "guardrail_verdict": review["verdict"],
                "prior_runs": ev["run"]["prior_runs"], "cutoff_at": ev["run"]["cutoff_at"]}
    conn.execute("INSERT INTO decisions (decision_id, experiment_version_id, analysis_id, review_id, decision, basis, rationale, decided_by, "
                 "decided_role, decided_at, evidence) VALUES (%s,%s,%s,%s,%s,'primary',%s,%s,%s,%s,%s)",
                 (did, xv, inp.analysis_id, inp.review_id, inp.decision, inp.rationale.strip(), actor.actor_id, actor.role, at, Jsonb(evidence)))
    result = {"decision_id": did, "experiment_version_id": xv, "decision": inp.decision, "basis": "primary", "rationale": inp.rationale.strip(),
              "decided_by": actor.actor_id, "decided_at": iso_z(at), "evidence": evidence, "product_state_changed": False,
              "note": "recording a decision releases, stops or changes nothing in the product"}
    warns = []
    if inp.decision == "ship" and not ev["primary"]["conclusive"]:
        warns.append(_warning("NOT_CONCLUSIVE", "the cited result is not conclusive: ship rests on more than the primary interval",
                              "result.evidence.conclusive"))
    return Outcome(inp.decision, result, 1, warns, Audit("decision", did, "record-decision", None, 1, reason=inp.rationale.strip(),
                                                         experiment_version_id=xv, details=evidence))


__all__ = ["Actor", "ROLES", "DESIGN_ROLES", "ALL_ROLES", "execute", "validate_tracking", "resolve_identity", "define_funnel",
           "assign_experiment", "record_exposure", "freeze_analysis_plan", "check_maturity", "analyze_experiment", "review_guardrails",
           "record_decision"]
