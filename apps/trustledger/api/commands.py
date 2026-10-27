"""Commands C01..C10 (docs/api-contract.md, docs/contracts.md D-01..D-06; backend conventions in README.md).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit together or not at all.
Input is validated (pydantic, then domain rules) before the first write. The same ``idempotency_key`` with the same payload, the same
actor id and the same role returns the stored response; with a different payload, actor or role it is a 409. Instants that are
decisions (a run, a detection, a merge, a reversal, a registration, a publication) are stamped by the SERVER's clock, never chosen
by the client.

Lock order (every command, so two commands cannot deadlock on each other):
    1. the idempotency key (advisory lock; C02 also takes an advisory lock on its metric id)
    2. dataset rows, by id (FOR SHARE for C03, C04, C05, C09, C10; the rule row of C03/C09 follows the dataset it belongs to)
    3. issue rows / candidate rows, by id (FOR UPDATE), then the customer records of a candidate, sorted by id
A deadlock or serialization failure that still happens is rolled back and retried, three attempts in all, then answered
409 CONCURRENT_UPDATE.

Roles (X-Actor-Role): analyst | steward | admin.  C01, C03-C06, C11, C12: analyst, steward, admin.  C02, C07-C10: steward, admin.
The actor is the registered owner named by X-Actor-Id; the role is the register's (D-10 R7-03).
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any, Callable

import psycopg
from psycopg.types.json import Jsonb
from trustledger.contract import ROLES as ROLE_LIST
from trustledger.errors import (ALREADY_REVERSED, ALREADY_REVIEWED, CLASSIFICATION_REQUIRED, DUPLICATE_PAIR, NON_CANONICAL_ORDER,
                                OWNER_INACTIVE, OWNER_REQUIRED, SAME_RECORD, UNKNOWN_OWNER, UNKNOWN_RECORD,
                                UNKNOWN_WEIGHT_VERSION, WEIGHT_CHANGE_REQUIRES_VERSION, DomainError)
from trustledger.ingest import blank, row_problem
from trustledger.issues import verification_problem
from trustledger.measure import measure_rule
from trustledger.metrics import compare_runs
from trustledger.models import Owner, Population, parse
from trustledger.numbers import h4, p6, rnd
from trustledger.structure import checklist_gaps, owner_covers
from trustledger.timeutil import hours_between, iso_z, parse_ts

from data.seed import canonical_json, insert_rejected, sha256_hex  # noqa: F401

from . import clock, db
from .errors import ApiError, detail
from .schemas import Envelope

Conn = psycopg.Connection[db.Row]
ROLES = frozenset(ROLE_LIST)
ALL_ROLES = ROLES
STEWARD_ROLES = frozenset({"steward", "admin"})
SHARED_UNCERTAINTY = "Shared name and address; possible household"


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str


def resolve_actor(actor_id: str, claimed_role: str) -> Actor:
    """The actor is a registered, active owner (exact id); the role is the register's, and a different ``X-Actor-Role`` is refused (D-10 R7-03)."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM owners WHERE owner_id = %s", (actor_id,)).fetchone()
    if row is None:
        raise ApiError(401, "UNAUTHENTICATED", f"actor {actor_id!r} is not in the owners register",
                       [detail("header.X-Actor-Id", "UNKNOWN_ACTOR", "X-Actor-Id must be the exact id of a registered owner")])
    owner = parse("owners", row)
    if not owner_covers(owner, clock.peek()):
        raise _forbidden("ACTOR_INACTIVE", f"owner {actor_id!r} is inactive and cannot act", "header.X-Actor-Id")
    if owner.role != claimed_role:
        raise _forbidden("ROLE_MISMATCH", f"{actor_id!r} is registered as {owner.role}, not {claimed_role}", "header.X-Actor-Role",
                         {"registered_role": owner.role})
    return Actor(owner.owner_id, owner.role)


@dataclass
class Audit:
    entity_type: str
    entity_id: str
    action: str
    before_version: int | None = None
    after_version: int | None = None
    reason: str | None = None
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


def _domain(err: DomainError, path: str) -> ApiError:
    return _invalid(err.code, err.message, err.path or path, err.details or None)


# --- idempotent execution ---------------------------------------------------------------------------------------

def _normalise(value: Any, key: str = "") -> Any:
    """An instant (a string under a ``*_at`` key) is hashed as the UTC instant it names."""
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
    """sha256 over the command name + dataset_version + input (request_id and key excluded; instants normalised). The dataset_version
    is part of the payload: the same key with another version is a different request."""
    body = _normalise(req.input.model_dump())  # type: ignore[attr-defined]
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
    """Run ``handler`` once per idempotency key. Returns ``(response body, replayed)``. A deadlock is retried (``MAX_ATTEMPTS`` attempts
    in all, short randomised back-off); the last failure is 409 CONCURRENT_UPDATE, never a 500."""
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
    """The request names the dataset it was prepared against; a different current version is 409 STALE_DATASET_VERSION and nothing is
    written. A database with no dataset_versions row has nothing to be stale against."""
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    if row is not None and row["dataset_version"] != req.dataset_version:
        raise ApiError(409, "STALE_DATASET_VERSION",
                       f"the request was prepared against dataset {req.dataset_version!r}; the current dataset is {row['dataset_version']!r}",
                       [{**detail("dataset_version", "STALE_DATASET_VERSION", "re-read the data and retry with the current dataset_version"),
                         "context": {"current": row["dataset_version"], "requested": req.dataset_version}}])


_UNIQUE_CODES = {
    "datasets_pkey": ("DATASET_EXISTS", "a dataset with this id is already registered"),
    "issues_run_uq": ("ISSUE_ALREADY_OPEN", "this rule run already has an issue"),
    "candidates_pair_uq": (DUPLICATE_PAIR, "this pair is already a candidate"),
    "match_candidates_pkey": ("CANDIDATE_EXISTS", "a candidate with this id exists"),
    "merge_decisions_review_uq": (ALREADY_REVIEWED, "this candidate already has a decision"),
    "decisions_reversal_uq": (ALREADY_REVERSED, "this merge is already reversed"),
    "metric_versions_pkey": ("DEFINITION_IMMUTABLE", "a published definition is never rewritten: publish a new version"),
    "metric_versions_uq": ("CONCURRENT_UPDATE", "another request published this metric version first; retry"),
    "dataset_refreshes_pkey": ("REFRESH_EXISTS", "this refresh is already recorded"),
    "dataset_rows_version_uq": ("CONCURRENT_UPDATE", "another request corrected this record first; retry"),
    "dataset_rows_pkey": ("CONCURRENT_UPDATE", "another request wrote this dataset's rows first; retry"),
}


def _execute_once(name: str, req: Envelope, actor: Actor, handler: Handler, payload_hash: str) -> tuple[dict[str, Any], bool]:
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (req.idempotency_key,))
        prior = conn.execute("SELECT payload_hash, actor_id, actor_role, result FROM command_results WHERE idempotency_key = %s",
                             (req.idempotency_key,)).fetchone()
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
        except psycopg.errors.IntegrityError as exc:  # checks and triggers: append-only, reviewer, verification ...
            msg = exc.diag.message_primary or "integrity rule violated"
            rule = msg.split(":", 1)[0] if msg.split(":", 1)[0].isupper() else "INTEGRITY_RULE"
            raise _conflict("INTEGRITY_RULE", msg, "input", rule_id=rule) from None
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        for a in ([] if out.audit is None else out.audit if isinstance(out.audit, list) else [out.audit]):
            conn.execute(
                "INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, actor_role, before_version, after_version, "
                "reason, request_id, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (f"evt-{uuid.uuid4().hex[:16]}", a.entity_type, a.entity_id, a.action, actor.actor_id, actor.role, a.before_version,
                 a.after_version, a.reason, req.request_id, Jsonb(a.details)))
        body = {"command_id": command_id, "status": out.status, "result": out.result, "warnings": out.warnings, "version": out.version}
        conn.execute("INSERT INTO command_results (idempotency_key, payload_hash, actor_id, actor_role, command_id, status, result) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (req.idempotency_key, payload_hash, actor.actor_id, actor.role, command_id, out.status, Jsonb(body)))
        return body, False


def _refusal(actor: Actor, req: Envelope, action: str, entity_type: str, entity_id: str, rule_id: str, message: str) -> None:
    """Keep a refused decision in the audit trail (its own transaction: the command's is about to roll back)."""
    with db.autocommit() as c:
        c.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, actor_role, reason, request_id, details) "
                  "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                  (f"evt-{uuid.uuid4().hex[:16]}", entity_type, entity_id, f"{action}-refused", actor.actor_id, actor.role, message,
                   req.request_id, Jsonb({"rule_id": rule_id})))


# --- shared lookups and locks -----------------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _lock_dataset(conn: Conn, dataset_id: str, exclusive: bool = False, path: str = "input") -> db.Row:
    """Lock order step 2: the dataset row (FOR SHARE or FOR UPDATE)."""
    row = conn.execute(f"SELECT * FROM datasets WHERE dataset_id = %s FOR {'UPDATE' if exclusive else 'SHARE'}", (dataset_id,)).fetchone()
    if row is None:
        raise _not_found(path, "DATASET_UNKNOWN", "dataset")
    return row


def _owner(conn: Conn, owner_id: str, path: str, at: datetime) -> Owner:
    """An owner who is accountable at ``at``: it exists (UNKNOWN_OWNER) and is active (OWNER_INACTIVE)."""
    row = conn.execute("SELECT * FROM owners WHERE owner_id = %s", (owner_id,)).fetchone()
    if row is None:
        raise _invalid(UNKNOWN_OWNER, f"owner {owner_id!r} is not registered", path)
    o = parse("owners", row)
    if not owner_covers(o, at):
        raise _invalid(OWNER_INACTIVE, f"owner {owner_id!r} is inactive and cannot be accountable", path)
    return o


def _rule_dataset(conn: Conn, rule_id: str, path: str = "input.rule_id") -> db.Row:
    """The rule and its dataset id, read WITHOUT a lock (the dataset is locked next, then the rule: lock order)."""
    row = conn.execute("SELECT * FROM quality_rules WHERE rule_id = %s", (rule_id,)).fetchone()
    if row is None:
        raise _not_found(path, "RULE_UNKNOWN", "rule")
    return row


def _mini_population(conn: Conn, rule_row: db.Row, now: datetime) -> Population:
    """Just what one rule's measurement reads: its dataset, the rule, the dataset's rows and the parent rows of a relationship rule."""
    pop = Population()
    ds = conn.execute("SELECT * FROM datasets WHERE dataset_id = %s", (rule_row["dataset_id"],)).fetchone()
    ds = {**ds, "last_refreshed_at": db.last_refreshes(conn, now).get(ds["dataset_id"])}       # the latest recorded refresh (C12), not after now
    pop.datasets = [parse("datasets", ds)]
    pop.quality_rules = [parse("quality_rules", rule_row)]
    ids = {rule_row["dataset_id"]}
    if rule_row["rule_type"] == "relationship":
        ids.add(rule_row["definition"]["parent_dataset_id"])
    pop.dataset_rows = db.current_rows(conn, now, sorted(ids))                                   # the latest version of each record
    cfg = conn.execute("SELECT whitespace_policy FROM ledger_config WHERE id = 1").fetchone()
    if cfg:
        pop.trim = (cfg["whitespace_policy"] or {}).get("trim_characters", pop.trim)
    return pop


def _weight_in_force(conn: Conn, at: datetime) -> str | None:
    row = conn.execute("SELECT weight_version FROM rule_weight_versions WHERE valid_from <= %s ORDER BY valid_from DESC, weight_version DESC LIMIT 1",
                       (at,)).fetchone()
    return row["weight_version"] if row else None


def _event(conn: Conn, issue_id: str, kind: str, at: datetime, actor: Actor, details: dict[str, Any] | None = None) -> None:
    conn.execute("INSERT INTO issue_events (event_id, issue_id, event_type, occurred_at, actor_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
                 (_new_id("ie"), issue_id, kind, at, actor.actor_id, Jsonb(details or {})))


# --- C01 register-dataset -------------------------------------------------------------------------------------------

def register_dataset(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """absent -> cataloged. A dataset is registered only with an ACTIVE owner and a classification (D-02, P07-FLOW-01)."""
    i = req.input
    now = _now()
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("dataset:" + i.dataset_id,))
    if blank(i.owner_id):
        raise _invalid(OWNER_REQUIRED, "a dataset is registered only with an accountable owner", "input.owner_id")
    if blank(i.classification):
        raise _invalid(CLASSIFICATION_REQUIRED, "a dataset is registered only with a classification", "input.classification")
    _owner(conn, i.owner_id, "input.owner_id", now)
    last = parse_ts(i.last_refreshed_at) if i.last_refreshed_at else None
    if last is not None and last > now:
        raise _invalid("REFRESH_IN_FUTURE", "last_refreshed_at cannot be after the server's time", "input.last_refreshed_at")
    row = {"dataset_id": i.dataset_id, "dataset_name": i.dataset_name, "source_system": i.source_system, "owner_id": i.owner_id,
           "classification": i.classification, "registered_at": iso_z(now), "monitored": i.monitored, "refresh_timezone": i.refresh_timezone,
           "refresh_local_time": i.refresh_local_time, "refresh_grace_minutes": i.refresh_grace_minutes, "last_refreshed_at": iso_z(last)}
    try:
        parse("datasets", row)
    except DomainError as err:
        raise _domain(err, "input.refresh_timezone") from None
    if conn.execute("SELECT 1 FROM datasets WHERE dataset_id = %s", (i.dataset_id,)).fetchone():
        raise _conflict("DATASET_EXISTS", f"dataset {i.dataset_id!r} is already registered", "input.dataset_id")
    names = [f.field_name for f in i.fields]
    if len(set(names)) != len(names):
        raise _invalid("DUPLICATE_FIELD", "field names must be unique within a dataset", "input.fields")
    seen: set[str] = set()
    for k, r in enumerate(i.rows):
        problem = row_problem(r, seen)
        if problem:
            raise _invalid(problem, "a dataset row is a flat object with a unique row_id and text, integer, boolean or null values", f"input.rows[{k}]")
        seen.add(r["row_id"])
    conn.execute("INSERT INTO datasets (dataset_id, dataset_name, source_system, owner_id, classification, registered_at, monitored, refresh_timezone, "
                 "refresh_local_time, refresh_grace_minutes, last_refreshed_at, registered_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                 (i.dataset_id, i.dataset_name, i.source_system, i.owner_id, i.classification, now, i.monitored, i.refresh_timezone,
                  i.refresh_local_time, i.refresh_grace_minutes, last, actor.actor_id))
    for f in i.fields:
        conn.execute("INSERT INTO fields VALUES (%s,%s,%s,%s,%s)", (f"fld-{i.dataset_id}-{f.field_name}"[:128], i.dataset_id, f.field_name, f.data_type, f.nullable))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO dataset_rows (dataset_id, ordinal, row_id, data) VALUES (%s,%s,%s,%s)",
                        [(i.dataset_id, k, r["row_id"], Jsonb(r)) for k, r in enumerate(i.rows)])
    warnings = []
    if i.monitored and last is None:
        warnings.append(_warning("NEVER_REFRESHED", "a monitored dataset that has never been refreshed counts as late", "input.last_refreshed_at"))
    return Outcome("cataloged", {"dataset_id": i.dataset_id, "owner_id": i.owner_id, "classification": i.classification, "registered_at": iso_z(now),
                                 "monitored": i.monitored, "fields": len(i.fields), "rows": len(i.rows)}, 1, warnings,
                   Audit("dataset", i.dataset_id, "register-dataset", None, 1, None, {"owner_id": i.owner_id, "classification": i.classification}))


# --- C02 publish-definition -----------------------------------------------------------------------------------------

def publish_definition(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """draft -> reviewed -> published, each step a NEW version row with valid_from = now; the older versions stay readable and unchanged (D-02,
    P07-TEST-11, FLOW-02). A step changes the status only: ``reviewed`` needs the metric's latest version to be a draft and a reviewer other
    than its author (409 SELF_REVIEW), ``published`` needs the latest version to be reviewed, and the content must be the content that was
    reviewed (409 CONTENT_CHANGED); changing the content starts a new draft (D-10 R7-12)."""
    i = req.input
    now = _now()
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("metric:" + i.metric_id,))
    if i.status not in ("draft", "reviewed", "published"):
        raise _invalid("INVALID_STATUS", "status must be draft, reviewed or published", "input.status")
    versions = conn.execute("SELECT * FROM metric_versions WHERE metric_id = %s ORDER BY version_number", (i.metric_id,)).fetchall()
    latest = versions[-1] if versions else None
    if i.metric_version_id and conn.execute("SELECT 1 FROM metric_versions WHERE metric_version_id = %s", (i.metric_version_id,)).fetchone():
        msg = f"metric version {i.metric_version_id!r} exists and is never rewritten; publish a new version instead"
        _refusal(actor, req, "publish-definition", "metric", i.metric_id, "DEFINITION_IMMUTABLE", msg)
        raise _conflict("DEFINITION_IMMUTABLE", msg, "input.metric_version_id", {"latest_version": latest["version_number"] if latest else None})
    if i.expected_version is not None and i.expected_version != (latest["version_number"] if latest else 0):
        raise _conflict("STALE_METRIC_VERSION", "the metric has a newer version than the one this request was prepared against", "input.expected_version",
                        {"latest_version": latest["version_number"] if latest else 0})
    if latest is not None and blank(i.reason):
        raise _invalid("REASON_REQUIRED", "a change to an existing metric needs a reason", "input.reason")
    if i.status in ("reviewed", "published"):
        need, code = ("draft", "REVIEW_REQUIRES_DRAFT") if i.status == "reviewed" else ("reviewed", "PUBLICATION_REQUIRES_REVIEW")
        if latest is None or latest["status"] != need:
            raise _conflict("INVALID_TRANSITION", f"a metric version is {i.status} only after its latest version is {need} "
                            f"(draft -> reviewed -> published); the latest is {latest['status'] if latest else 'none'}", "input.status",
                            {"latest_status": latest["status"] if latest else None, "required_status": need}, rule_id=code)
        same = (latest["metric_name"], latest["definition"], latest["grain"], list(latest["source_fields"] or []), latest["owner_id"], latest["refresh"]) == \
               (i.metric_name, i.definition, i.grain, list(i.source_fields), i.owner_id, i.refresh)
        if not same:
            raise _conflict("CONTENT_CHANGED", f"the content differs from the {need} version: only its status changes at this step; start a new draft to change the content",
                            "input.definition", {"latest_metric_version_id": latest["metric_version_id"]})
        if i.status == "reviewed" and latest["published_by"] == actor.actor_id:
            msg = f"{actor.actor_id} drafted this version and cannot review it: a definition needs an independent reviewer"
            _refusal(actor, req, "publish-definition", "metric", i.metric_id, "SELF_REVIEW", msg)
            raise _conflict("SELF_REVIEW", msg, "header.X-Actor-Id", {"metric_version_id": latest["metric_version_id"]})
    owner = conn.execute("SELECT 1 FROM owners WHERE owner_id = %s", (i.owner_id,)).fetchone()
    if owner is None:
        raise _invalid(UNKNOWN_OWNER, f"owner {i.owner_id!r} is not registered", "input.owner_id")
    number = (latest["version_number"] if latest else 0) + 1
    vid = i.metric_version_id or f"mv-{i.metric_id}-{number}"[:128]
    conn.execute("INSERT INTO metric_versions (metric_version_id, metric_id, metric_name, version_number, definition, grain, source_fields, owner_id, "
                 "refresh, valid_from, status, published_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                 (vid, i.metric_id, i.metric_name, number, i.definition, i.grain, Jsonb(list(i.source_fields)), i.owner_id, i.refresh, now,
                  i.status, actor.actor_id))
    change_id = None
    if latest is not None:
        change_id = f"dc-{vid}"[:128]
        conn.execute("INSERT INTO definition_changes VALUES (%s,%s,%s,%s,%s,%s)",
                     (change_id, vid, latest["metric_version_id"], i.reason, actor.actor_id, now))
    warnings = []
    cl = conn.execute("SELECT c.items FROM checklist_versions c JOIN ledger_config g ON g.checklist_version = c.checklist_version WHERE g.id = 1").fetchone()
    if i.status == "published":
        mv = parse("metric_versions", {"metric_version_id": vid, "metric_id": i.metric_id, "metric_name": i.metric_name, "version_number": number,
                                       "definition": i.definition, "grain": i.grain, "source_fields": list(i.source_fields), "owner_id": i.owner_id,
                                       "refresh": i.refresh, "valid_from": now, "status": "published"})
        gaps = checklist_gaps(Population(), mv, list(cl["items"]) if cl else ["definition", "grain", "source_fields", "owner", "refresh"], {i.owner_id})
        if gaps:
            warnings.append(_warning("DEFINITION_INCOMPLETE", f"the contract checklist is incomplete: {', '.join(gaps)}; it counts as incomplete in definition coverage",
                                     "input"))
    return Outcome({"published": "published", "reviewed": "reviewed", "draft": "drafted"}[i.status],
                   {"metric_version_id": vid, "metric_id": i.metric_id, "version_number": number, "valid_from": iso_z(now), "status": i.status,
                    "previous_metric_version_id": latest["metric_version_id"] if latest else None, "change_id": change_id},
                   number, warnings, Audit("metric", i.metric_id, "publish-definition", number - 1 if latest else None, number, i.reason,
                                           {"metric_version_id": vid, "approved_by": actor.actor_id}))


# --- C03 run-rule ---------------------------------------------------------------------------------------------------

def run_rule(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """active rule -> measured result: eligible and failing counts under the rule version and the named weight version (D-01)."""
    i = req.input
    now = _now()
    rule0 = _rule_dataset(conn, i.rule_id)
    _lock_dataset(conn, rule0["dataset_id"], False, "input.rule_id")
    rule = conn.execute("SELECT * FROM quality_rules WHERE rule_id = %s FOR SHARE", (i.rule_id,)).fetchone()
    if rule["status"] != "active":
        raise _conflict("RULE_DISABLED", f"rule {i.rule_id!r} is disabled; its history is kept but it is no longer measured", "input.rule_id",
                        {"disabled_at": iso_z(rule["disabled_at"]), "disabled_reason": rule["disabled_reason"]})
    wv = i.weight_version or _weight_in_force(conn, now)
    wrow = conn.execute("SELECT * FROM rule_weight_versions WHERE weight_version = %s", (wv,)).fetchone() if wv else None
    if wrow is None:
        raise _invalid(UNKNOWN_WEIGHT_VERSION, f"unknown weight version {wv!r}" if wv else "no rule weight version is defined", "input.weight_version")
    if i.weights is not None:
        try:
            given = {k: Fraction(v) for k, v in i.weights.items()}
        except ValueError:
            raise _invalid("WEIGHTS_INVALID", "weights must be decimal strings", "input.weights") from None
        if given != {k: Fraction(v) for k, v in wrow["weights"].items()}:
            msg = f"the weights differ from weight version {wv!r}: a change of weights is a new, versioned weight set"
            _refusal(actor, req, "run-rule", "rule", i.rule_id, WEIGHT_CHANGE_REQUIRES_VERSION, msg)
            raise _invalid(WEIGHT_CHANGE_REQUIRES_VERSION, msg, "input.weights", {"weight_version": wv})
    pop = _mini_population(conn, rule, now)
    m = measure_rule(pop.quality_rules[0], pop, now)
    run_id = _new_id("rr")
    prev = conn.execute("SELECT * FROM rule_runs WHERE rule_id = %s AND kind = 'scheduled' AND run_at < %s ORDER BY run_at DESC, rule_run_id DESC LIMIT 1",
                        (i.rule_id, now)).fetchone()
    details = {**m.run_extra, "failing_row_ids": m.failing, "value": p6(m.value)}
    conn.execute("INSERT INTO rule_runs (rule_run_id, rule_id, rule_version, weight_version, kind, run_at, eligible_count, failure_count, details, run_by) "
                 "VALUES (%s,%s,%s,%s,'scheduled',%s,%s,%s,%s,%s)",
                 (run_id, i.rule_id, rule["version_number"], wv, now, m.eligible, m.failures, Jsonb(details), actor.actor_id))
    comparison = None
    if prev is not None:
        from types import SimpleNamespace  # noqa: PLC0415
        comparison = compare_runs(SimpleNamespace(**{k: prev[k] for k in ("rule_run_id", "rule_version", "eligible_count", "failure_count")}),
                                  SimpleNamespace(rule_run_id=run_id, rule_version=rule["version_number"], eligible_count=m.eligible,
                                                  failure_count=m.failures))
    warnings = []
    if rule["severity"] == "critical" and m.failures > 0:
        warnings.append(_warning("CRITICAL_FAILURE", f"{m.failures} failure(s) of a critical rule: shown beside any score, never hidden by it", "result.failure_count"))
    if comparison and not comparison["comparable"]:
        warnings.append(_warning("RULE_VERSION_DIFFERS", "the previous run used another rule version: the two runs are not comparable", "result.comparison"))
    result = {"rule_run_id": run_id, "rule_id": i.rule_id, "dataset_id": rule["dataset_id"], "rule_type": rule["rule_type"], "severity": rule["severity"],
              "rule_version": rule["version_number"], "weight_version": wv, "kind": "scheduled", "run_at": iso_z(now),
              "eligible_count": m.eligible, "failure_count": m.failures, "value": p6(m.value), **m.run_extra, "comparison": comparison}
    return Outcome("measured", result, 1, warnings, Audit("rule_run", run_id, "run-rule", None, 1, None,
                                                         {"rule_id": i.rule_id, "eligible_count": m.eligible, "failure_count": m.failures, "weight_version": wv}))


# --- C04 open-issue / C05 triage-issue -----------------------------------------------------------------------------

def open_issue(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """failure -> owned issue, linked to the run and carrying the rule's severity; detected_at is the failing run's run_at."""
    i = req.input
    now = _now()
    run0 = conn.execute("SELECT r.*, q.dataset_id, q.severity FROM rule_runs r JOIN quality_rules q ON q.rule_id = r.rule_id WHERE r.rule_run_id = %s",
                        (i.rule_run_id,)).fetchone()
    if run0 is None:
        raise _not_found("input.rule_run_id", "RUN_UNKNOWN", "rule run")
    ds = _lock_dataset(conn, run0["dataset_id"], False, "input.rule_run_id")
    if run0["kind"] != "scheduled":
        raise _invalid("RUN_NOT_SCHEDULED", "an issue is opened on a measuring run, not on a rerun", "input.rule_run_id")
    if run0["failure_count"] == 0:
        raise _invalid("NO_FAILURE", "the run has no failure to open an issue for", "input.rule_run_id")
    owner_id = i.owner_id or ds["owner_id"]
    _owner(conn, owner_id, "input.owner_id" if i.owner_id else "input.rule_run_id", now)
    issue_id = _new_id("iss")
    ids = (run0["details"] or {}).get("failing_row_ids")
    conn.execute("INSERT INTO issues (issue_id, rule_run_id, severity, owner_id, status, detected_at, record_ids) VALUES (%s,%s,%s,%s,'open',%s,%s)",
                 (issue_id, i.rule_run_id, run0["severity"], owner_id, run0["run_at"], Jsonb(ids) if ids is not None else None))
    _event(conn, issue_id, "detected", run0["run_at"], actor, {"rule_run_id": i.rule_run_id})
    warnings = [_warning("CRITICAL_ISSUE", "a critical issue keeps the dataset's critical_override on until it is verified", "result.severity")] \
        if run0["severity"] == "critical" else []
    return Outcome("opened", {"issue_id": issue_id, "rule_run_id": i.rule_run_id, "rule_id": run0["rule_id"], "dataset_id": run0["dataset_id"],
                              "severity": run0["severity"], "owner_id": owner_id, "status": "open", "detected_at": iso_z(run0["run_at"]),
                              "failing_records": len(ids) if ids is not None else None}, 1, warnings,
                   Audit("issue", issue_id, "open-issue", None, 1, None, {"rule_run_id": i.rule_run_id, "severity": run0["severity"], "owner_id": owner_id}))


def _lock_issue(conn: Conn, issue_id: str) -> tuple[db.Row, db.Row]:
    """Lock order: the issue's dataset (FOR SHARE), then the issue row (FOR UPDATE). Returns (issue, base run joined with its rule)."""
    pre = conn.execute("SELECT q.dataset_id FROM issues i JOIN rule_runs r ON r.rule_run_id = i.rule_run_id JOIN quality_rules q ON q.rule_id = r.rule_id "
                       "WHERE i.issue_id = %s", (issue_id,)).fetchone()
    if pre is None:
        raise _not_found("input.issue_id", "ISSUE_UNKNOWN", "issue")
    _lock_dataset(conn, pre["dataset_id"], False, "input.issue_id")
    issue = conn.execute("SELECT * FROM issues WHERE issue_id = %s FOR UPDATE", (issue_id,)).fetchone()
    base = conn.execute("SELECT r.*, q.dataset_id, q.severity, q.status AS rule_status, q.version_number AS rule_current_version "
                        "FROM rule_runs r JOIN quality_rules q ON q.rule_id = r.rule_id WHERE r.rule_run_id = %s", (issue["rule_run_id"],)).fetchone()
    return issue, base


def triage_issue(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """open -> investigating (owner and due date). Also: ``claim`` (the owner says it is fixed: closed without a rerun = CLAIMED, never
    resolved) and ``reopen`` (closed or claimed -> open, a reopen cycle; the first detected_at is kept)."""
    i = req.input
    now = _now()
    issue, base = _lock_issue(conn, i.issue_id)
    if i.action not in ("investigate", "claim", "reopen"):
        raise _invalid("INVALID_ACTION", "action must be investigate, claim or reopen", "input.action")
    before = issue["version"]
    if i.action == "investigate":
        if i.owner_id is None:
            raise _invalid(OWNER_REQUIRED, "triage sets an owner", "input.owner_id")
        if i.due_at is None:
            raise _invalid("DUE_DATE_REQUIRED", "triage sets a due date", "input.due_at")
        due = parse_ts(i.due_at)
        if due <= issue["detected_at"]:
            raise _invalid("DUE_BEFORE_DETECTION", "the due date must be after the issue was detected", "input.due_at")
        if issue["status"] == "closed":
            raise _conflict("INVALID_STATE", "a closed issue is reopened before it is triaged", "input.issue_id", {"status": issue["status"]})
        _owner(conn, i.owner_id, "input.owner_id", now)
        conn.execute("UPDATE issues SET status = 'investigating', owner_id = %s, due_at = %s, version = version + 1 WHERE issue_id = %s",
                     (i.owner_id, due, i.issue_id))
        _event(conn, i.issue_id, "triaged", now, actor, {"owner_id": i.owner_id, "due_at": iso_z(due), "note": i.note})
        result = {"issue_id": i.issue_id, "status": "investigating", "owner_id": i.owner_id, "due_at": iso_z(due)}
        status = "triaged"
        warnings: list[dict[str, Any]] = []
    elif i.action == "claim":
        if issue["status"] == "closed":
            raise _conflict("INVALID_STATE", "the issue is already closed", "input.issue_id", {"status": issue["status"]})
        conn.execute("UPDATE issues SET status = 'closed', closed_at = %s, version = version + 1 WHERE issue_id = %s", (now, i.issue_id))
        _event(conn, i.issue_id, "claimed", now, actor, {"note": i.note})
        result = {"issue_id": i.issue_id, "status": "closed", "class": "claimed", "closed_at": iso_z(now)}
        status = "claimed"
        warnings = [_warning("CLAIMED_NOT_RESOLVED", "closed without a rerun: the issue is claimed, listed apart, and not resolved until C10 verify-remediation "
                                                     "confirms it with a successful rerun of the same rule version", "result.class")]
    else:
        if issue["status"] != "closed":
            raise _conflict("INVALID_STATE", "only a closed (claimed or resolved) issue can be reopened", "input.issue_id", {"status": issue["status"]})
        conn.execute("UPDATE issues SET status = 'open', reopened_at = array_append(reopened_at, %s), version = version + 1 WHERE issue_id = %s",
                     (now, i.issue_id))
        _event(conn, i.issue_id, "reopened", now, actor, {"note": i.note})
        result = {"issue_id": i.issue_id, "status": "open", "reopen_cycles": len(issue["reopened_at"]) + 1, "detected_at": iso_z(issue["detected_at"])}
        status = "reopened"
        warnings = []
    return Outcome(status, result, before + 1, warnings, Audit("issue", i.issue_id, f"triage-issue:{i.action}", before, before + 1, i.note,
                                                              {"action": i.action, "actor_role": actor.role}))


# --- C10 verify-remediation -----------------------------------------------------------------------------------------

def verify_remediation(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """claimed -> resolved only by a successful rerun of the SAME rule version over the issue's records; otherwise the issue stays
    claimed. Disabling the rule is not repair (a disabled rule's issue is still unresolved), yet a passing rerun resolves it, which is also what
    clears the critical failure a disabled rule carries (D-03, P07-TEST-09, D-10 R7-02)."""
    i = req.input
    now = _now()
    issue, base = _lock_issue(conn, i.issue_id)
    if issue["status"] != "closed":
        raise _conflict("INVALID_STATE", "only a claimed (closed) issue can be verified; close it first (C05 action=claim)", "input.issue_id",
                        {"status": issue["status"]})
    ver0 = conn.execute("SELECT * FROM rule_runs WHERE rule_run_id = %s", (issue["verification_run_id"],)).fetchone() if issue["verification_run_id"] else None
    if ver0 is not None and (not issue["reopened_at"] or ver0["run_at"] >= issue["reopened_at"][-1]):
        raise _conflict("ALREADY_RESOLVED", "the issue is already resolved by a successful rerun", "input.issue_id", {"verification_run_id": ver0["rule_run_id"]})
    before = issue["version"]
    reasons: list[str] = []
    rule = conn.execute("SELECT * FROM quality_rules WHERE rule_id = %s FOR SHARE", (base["rule_id"],)).fetchone()
    run_id = None
    failures = eligible = None
    disabled = rule["status"] != "active"                 # disabling is not repair, and it does not forbid proof: only a passing rerun resolves (D-10 R7-02)
    if rule["version_number"] != base["rule_version"]:
        reasons.append("RULE_VERSION_DIFFERS")            # a rerun of another rule version verifies nothing
    elif rule["rule_type"] == "validity" and not (rule["definition"] or {}).get("pattern"):
        reasons.append("RULE_NOT_MEASURABLE")             # a disabled validity rule may have no pattern: there is nothing to rerun
    else:
        pop = _mini_population(conn, rule, now)
        m = measure_rule(pop.quality_rules[0], pop, now)
        records = issue["record_ids"]
        if records is None:
            eligible, failures, failing = m.eligible, m.failures, m.failing
        else:
            failing = sorted(set(records) & set(m.failing))
            eligible, failures = len(records), len(failing)
        run_id = _new_id("rr")
        wv = _weight_in_force(conn, now) or base["weight_version"]
        conn.execute("INSERT INTO rule_runs (rule_run_id, rule_id, rule_version, weight_version, kind, run_at, eligible_count, failure_count, "
                     "rerun_for_issue, details, run_by) VALUES (%s,%s,%s,%s,'rerun',%s,%s,%s,%s,%s,%s)",
                     (run_id, rule["rule_id"], rule["version_number"], wv, now, eligible, failures, i.issue_id,
                      Jsonb({"failing_row_ids": failing, "records_checked": records}), actor.actor_id))
        if eligible == 0:
            reasons.append("NO_RECORDS_TO_CHECK")
        elif failures > 0:
            reasons.append("RERUN_STILL_FAILING")
    extra = [_warning("RULE_DISABLED", "the rule is disabled: disabling is not repair, a critical failure of its latest run keeps counting until a rerun passes", "result.class")] if disabled else []
    if reasons:
        _event(conn, i.issue_id, "verification_failed", now, actor, {"reasons": reasons, "rerun_run_id": run_id})
        conn.execute("UPDATE issues SET version = version + 1 WHERE issue_id = %s", (i.issue_id,))
        return Outcome("claimed", {"issue_id": i.issue_id, "class": "claimed", "verified": False, "reasons": reasons, "rerun_run_id": run_id,
                                   "eligible_count": eligible, "failure_count": failures, "rule_disabled": disabled}, before + 1,
                       [_warning(reasons[0], "the issue stays claimed: it is not resolved without a successful rerun of the same rule version", "result.class"), *extra],
                       Audit("issue", i.issue_id, "verify-remediation:not-verified", before, before + 1, ",".join(reasons), {"rerun_run_id": run_id}))
    problem = verification_problem(parse("issues", {**issue, "reopened_at": list(issue["reopened_at"])}), parse("rule_runs", base),
                                   parse("rule_runs", conn.execute("SELECT * FROM rule_runs WHERE rule_run_id = %s", (run_id,)).fetchone()))
    assert problem is None, problem
    conn.execute("UPDATE issues SET verification_run_id = %s, version = version + 1 WHERE issue_id = %s", (run_id, i.issue_id))
    _event(conn, i.issue_id, "verified", now, actor, {"rerun_run_id": run_id})
    return Outcome("resolved", {"issue_id": i.issue_id, "class": "resolved", "verified": True, "rerun_run_id": run_id, "resolved_at": iso_z(now),
                                "resolution_hours": h4(hours_between(issue["detected_at"], now)), "eligible_count": eligible, "failure_count": failures,
                                "rule_disabled": disabled},
                   before + 1, extra, Audit("issue", i.issue_id, "verify-remediation", before, before + 1, None, {"rerun_run_id": run_id}))


# --- C11 correct-dataset-rows / C12 record-refresh ---------------------------------------------------------------------

def correct_dataset_rows(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """records -> new record VERSIONS. Append-only: a correction writes a new row (row_version + 1, supersedes_row_id, the reason, the actor and the
    server's instant); the measurement reads the latest version of each record, a dataset's earlier versions and every earlier run stay as they were.
    A correction does not resolve an issue: C10 reruns the rule over the issue's records (D-10 R7-07)."""
    i = req.input
    now = _now()
    _lock_dataset(conn, i.dataset_id, False, "input.dataset_id")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("rows:" + i.dataset_id,))
    if blank(i.reason):
        raise _invalid("REASON_REQUIRED", "a correction needs a reason", "input.reason")
    ids = [c.row_id for c in i.corrections]
    if len(set(ids)) != len(ids):
        raise _invalid("DUPLICATE_ROW", "a record is corrected once per request", "input.corrections")
    latest = {r["row_id"]: r for r in conn.execute(
        "SELECT DISTINCT ON (row_id) row_id, row_version, data FROM dataset_rows WHERE dataset_id = %s AND row_id = ANY(%s) "
        "ORDER BY row_id, row_version DESC", (i.dataset_id, ids)).fetchall()}
    top = conn.execute("SELECT coalesce(max(ordinal), -1) AS n FROM dataset_rows WHERE dataset_id = %s", (i.dataset_id,)).fetchone()["n"]
    done = []
    for k, c in enumerate(i.corrections):
        cur = latest.get(c.row_id)
        if cur is None:
            raise _invalid("UNKNOWN_ROW", f"record {c.row_id!r} is not a row of dataset {i.dataset_id!r}", f"input.corrections[{k}].row_id")
        if "row_id" in c.changes:
            raise _invalid("ROW_ID_IMMUTABLE", "the id of a record does not change; a correction changes its cells", f"input.corrections[{k}].changes.row_id")
        new = {**cur["data"], **c.changes}
        if new == cur["data"]:
            raise _invalid("NO_CHANGE", f"the correction of {c.row_id!r} changes nothing", f"input.corrections[{k}].changes")
        if row_problem(new, set()):
            raise _invalid(row_problem(new, set()) or "MALFORMED_RECORD", "a cell is text, an integer, a boolean or null", f"input.corrections[{k}].changes")
        version = cur["row_version"] + 1
        top += 1
        conn.execute("INSERT INTO dataset_rows (dataset_id, ordinal, row_id, data, row_version, supersedes_row_id, reason, corrected_by, recorded_at) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (i.dataset_id, top, c.row_id, Jsonb(new), version, f"{c.row_id}@{cur['row_version']}", i.reason, actor.actor_id, now))
        done.append({"row_id": c.row_id, "row_version": version, "supersedes_row_id": f"{c.row_id}@{cur['row_version']}"})
    unresolved = conn.execute(
        "SELECT count(*) AS n FROM issues i JOIN rule_runs r ON r.rule_run_id = i.rule_run_id JOIN quality_rules q ON q.rule_id = r.rule_id "
        "WHERE q.dataset_id = %s AND (i.status <> 'closed' OR i.verification_run_id IS NULL)", (i.dataset_id,)).fetchone()["n"]
    warnings = [_warning("CORRECTION_IS_NOT_VERIFICATION", f"{unresolved} issue(s) of this dataset are not resolved: a correction resolves nothing; "
                         "verify-remediation (C10) reruns the rule over the issue's records", "result.corrected")] if unresolved else []
    return Outcome("corrected", {"dataset_id": i.dataset_id, "corrected": done, "recorded_at": iso_z(now), "corrected_by": actor.actor_id},
                   1, warnings, Audit("dataset", i.dataset_id, "correct-dataset-rows", None, None, i.reason,
                                      {"rows": [d["row_id"] for d in done], "corrected_by": actor.actor_id}))


def record_refresh(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """A refresh of a dataset that happened at ``refreshed_at``: appended to the dataset's refresh history (never edited); timeliness reads the
    latest refresh not after its as-of. The instant cannot be in the future or before the dataset was registered (D-10 R7-07)."""
    i = req.input
    now = _now()
    ds = _lock_dataset(conn, i.dataset_id, False, "input.dataset_id")
    at = parse_ts(i.refreshed_at)
    if at > now:
        raise _invalid("REFRESH_IN_FUTURE", "a refresh cannot be after the server's time", "input.refreshed_at")
    if at < ds["registered_at"]:
        raise _invalid("REFRESH_BEFORE_REGISTRATION", "a refresh cannot be before the dataset was registered", "input.refreshed_at")
    conn.execute("INSERT INTO dataset_refreshes (dataset_id, refreshed_at, recorded_at, recorded_by) VALUES (%s,%s,%s,%s)", (i.dataset_id, at, now, actor.actor_id))
    latest = db.last_refreshes(conn, now).get(i.dataset_id)
    warnings = [] if ds["monitored"] else [_warning("NOT_MONITORED", "the dataset is not monitored: the refresh is recorded but no timeliness is measured", "input.dataset_id")]
    return Outcome("recorded", {"dataset_id": i.dataset_id, "refreshed_at": iso_z(at), "recorded_at": iso_z(now), "last_refreshed_at": iso_z(latest)}, 1, warnings,
                   Audit("dataset", i.dataset_id, "record-refresh", None, None, None, {"refreshed_at": iso_z(at), "recorded_by": actor.actor_id}))


# --- C06 suggest-match / C07 approve-merge / C08 reverse-merge ----------------------------------------------------

def suggest_match(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """records -> candidate, stored once in canonical order (left < right). Never an automatic merge: a pair that shares a name and an
    address carries explicit uncertainty and waits for a human decision (D-04)."""
    i = req.input
    lo, hi = i.left_record_id, i.right_record_id
    if lo == hi:
        raise _invalid(SAME_RECORD, "a candidate pairs two distinct source records", "input.right_record_id")
    recs = {r["record_id"]: r for r in conn.execute("SELECT * FROM customer_records WHERE record_id = ANY(%s) ORDER BY record_id FOR SHARE", ([lo, hi],)).fetchall()}
    for path, rid in (("input.left_record_id", lo), ("input.right_record_id", hi)):
        if rid not in recs:
            raise _invalid(UNKNOWN_RECORD, f"record {rid!r} is not a known source record", path)
    twin = conn.execute("SELECT candidate_id FROM match_candidates WHERE (left_record_id = %s AND right_record_id = %s) OR (left_record_id = %s AND right_record_id = %s)",
                        (lo, hi, hi, lo)).fetchone()
    if twin:
        raise _conflict(DUPLICATE_PAIR, "this pair is already a candidate (a pair is stored once, in canonical order)", "input.right_record_id",
                        {"candidate_id": twin["candidate_id"]})
    if lo > hi:
        raise _invalid(NON_CANONICAL_ORDER, "a pair is stored once with left_record_id before right_record_id", "input.left_record_id",
                       {"canonical": {"left_record_id": hi, "right_record_id": lo}})
    shared = recs[lo]["normalized_name"] == recs[hi]["normalized_name"] and recs[lo]["address_key"] == recs[hi]["address_key"]
    uncertainty = i.uncertainty if not blank(i.uncertainty) else (SHARED_UNCERTAINTY if shared else None)
    warnings = []
    if shared:
        warnings.append(_warning("SHARED_NAME_AND_ADDRESS", "the records share a name and an address: possibly one household, never merged automatically; "
                                                            "a human decides (C07)", "result.uncertainty"))
    now = _now()
    cid = i.candidate_id or _new_id("cand")
    conn.execute("INSERT INTO match_candidates VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                 (cid, lo, hi, i.score, Jsonb(i.features), i.explanation, uncertainty, actor.actor_id, now))
    return Outcome("proposed", {"candidate_id": cid, "left_record_id": lo, "right_record_id": hi, "score": rnd(Fraction(i.score), 6), "features": i.features,
                                "explanation": i.explanation, "uncertainty": uncertainty, "proposed_by": actor.actor_id, "proposed_at": iso_z(now),
                                "merged": False}, 1, warnings, Audit("candidate", cid, "suggest-match", None, 1, None, {"left": lo, "right": hi}))


def _lock_candidate(conn: Conn, candidate_id: str, path: str) -> tuple[db.Row, dict[str, db.Row]]:
    """Lock order step 3: the candidate row (FOR UPDATE), then its two customer records sorted by id (FOR UPDATE)."""
    cand = conn.execute("SELECT * FROM match_candidates WHERE candidate_id = %s FOR UPDATE", (candidate_id,)).fetchone()
    if cand is None:
        raise _not_found(path, "CANDIDATE_UNKNOWN", "match candidate")
    recs = {r["record_id"]: r for r in conn.execute("SELECT * FROM customer_records WHERE record_id = ANY(%s) ORDER BY record_id FOR UPDATE",
                                                    ([cand["left_record_id"], cand["right_record_id"]],)).fetchall()}
    return cand, recs


def _same_person_check(actor: Actor, req: Any, cand: db.Row, action: str) -> None:
    """A proposer cannot decide (or reverse) their own candidate: 409 SELF_REVIEW, kept in the audit trail (D-10 R7-03). The domain and the
    database keep REVIEWER_IS_PROPOSER for the same rule on stored data."""
    if cand["proposed_by"] == actor.actor_id:
        msg = f"{actor.actor_id} proposed candidate {cand['candidate_id']} and cannot decide it: a merge needs an independent reviewer"
        _refusal(actor, req, action, "candidate", cand["candidate_id"], "SELF_REVIEW", msg)
        raise _conflict("SELF_REVIEW", msg, "header.X-Actor-Id", {"candidate_id": cand["candidate_id"]})


def approve_merge(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """candidate -> linked (or rejected): a human decision by a reviewer other than the proposer; the RIGHT record maps to the LEFT."""
    i = req.input
    if i.decision not in ("approve", "reject"):
        raise _invalid("INVALID_DECISION", "decision must be approve or reject", "input.decision")
    cand, _ = _lock_candidate(conn, i.candidate_id, "input.candidate_id")
    _same_person_check(actor, req, cand, "approve-merge")
    prior = conn.execute("SELECT merge_id, decision FROM merge_decisions WHERE candidate_id = %s AND decision IN ('approve', 'reject')", (i.candidate_id,)).fetchone()
    if prior:
        raise _conflict(ALREADY_REVIEWED, "this candidate already has a decision", "input.candidate_id", {"merge_id": prior["merge_id"], "decision": prior["decision"]})
    lo, hi = cand["left_record_id"], cand["right_record_id"]
    if i.decision == "approve":
        clash = conn.execute(
            "SELECT m.merge_id FROM merge_decisions m JOIN match_candidates c ON c.candidate_id = m.candidate_id "
            "WHERE m.decision = 'approve' AND NOT EXISTS (SELECT 1 FROM merge_decisions r WHERE r.reverses_merge_id = m.merge_id) "
            "AND (c.right_record_id = ANY(%s) OR c.left_record_id = %s) LIMIT 1", ([lo, hi], hi)).fetchone()
        if clash:
            raise _conflict("RECORD_ALREADY_MERGED", "one of the records is already merged away (or is the target of a merge into this record): reverse that merge first",
                            "input.candidate_id", {"merge_id": clash["merge_id"]})
    now = _now()
    mid = _new_id("md")
    conn.execute("INSERT INTO merge_decisions VALUES (%s,%s,%s,%s,%s,NULL,%s)", (mid, i.candidate_id, actor.actor_id, i.decision, now, i.reason))
    linked = i.decision == "approve"
    result = {"merge_id": mid, "candidate_id": i.candidate_id, "decision": i.decision, "state": "linked" if linked else "rejected",
              "reviewer_id": actor.actor_id, "proposed_by": cand["proposed_by"], "decided_at": iso_z(now),
              "maps": {"from_record_id": hi, "to_record_id": lo} if linked else None}
    return Outcome("linked" if linked else "rejected", result, 1, [], Audit("merge", mid, f"{i.decision}-merge", None, 1, i.reason,
                                                                             {"candidate_id": i.candidate_id, "reviewer_id": actor.actor_id,
                                                                              "proposed_by": cand["proposed_by"], "left": lo, "right": hi}))


def reverse_merge(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """merged -> reversed: restores both source identities and keeps the mapping history (a reversal is a new decision, not an edit)."""
    i = req.input
    tgt = conn.execute("SELECT * FROM merge_decisions WHERE merge_id = %s", (i.merge_id,)).fetchone()
    if tgt is None:
        raise _not_found("input.merge_id", "MERGE_UNKNOWN", "merge decision")
    cand, _ = _lock_candidate(conn, tgt["candidate_id"], "input.merge_id")
    if tgt["decision"] != "approve":
        raise _invalid("NOT_AN_APPROVAL", "only an approved merge can be reversed", "input.merge_id", {"decision": tgt["decision"]})
    if blank(i.reason):
        raise _invalid("REASON_REQUIRED", "a reversal needs a reason", "input.reason")
    _same_person_check(actor, req, cand, "reverse-merge")
    if conn.execute("SELECT 1 FROM merge_decisions WHERE reverses_merge_id = %s", (i.merge_id,)).fetchone():
        raise _conflict(ALREADY_REVERSED, "this merge is already reversed", "input.merge_id")
    now = _now()
    rid = _new_id("md")
    conn.execute("INSERT INTO merge_decisions VALUES (%s,%s,%s,'reverse',%s,%s,%s)", (rid, cand["candidate_id"], actor.actor_id, now, i.merge_id, i.reason))
    lo, hi = cand["left_record_id"], cand["right_record_id"]
    return Outcome("reversed", {"merge_id": rid, "reverses_merge_id": i.merge_id, "candidate_id": cand["candidate_id"], "state": "reversed",
                                "reviewer_id": actor.actor_id, "decided_at": iso_z(now), "restored": {lo: lo, hi: hi}}, 1, [],
                   Audit("merge", rid, "reverse-merge", None, 1, i.reason, {"reverses_merge_id": i.merge_id, "candidate_id": cand["candidate_id"]}))


# --- C09 disable-rule -----------------------------------------------------------------------------------------------

def disable_rule(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """active -> disabled with a reason and a date; its runs and issues stay readable and open issues stay open (D-01, P07-TEST-02)."""
    i = req.input
    if blank(i.reason):
        raise _invalid("REASON_REQUIRED", "disabling a rule needs a reason", "input.reason")
    rule0 = _rule_dataset(conn, i.rule_id)
    _lock_dataset(conn, rule0["dataset_id"], False, "input.rule_id")
    rule = conn.execute("SELECT * FROM quality_rules WHERE rule_id = %s FOR UPDATE", (i.rule_id,)).fetchone()
    if rule["status"] == "disabled":
        raise _conflict("RULE_ALREADY_DISABLED", "the rule is already disabled", "input.rule_id", {"disabled_at": iso_z(rule["disabled_at"])})
    now = _now()
    conn.execute("UPDATE quality_rules SET status = 'disabled', disabled_at = %s, disabled_reason = %s WHERE rule_id = %s", (now, i.reason, i.rule_id))
    runs = conn.execute("SELECT count(*) AS n FROM rule_runs WHERE rule_id = %s", (i.rule_id,)).fetchone()["n"]
    open_n = conn.execute("SELECT count(*) AS n FROM issues i JOIN rule_runs r ON r.rule_run_id = i.rule_run_id WHERE r.rule_id = %s "
                          "AND (i.status <> 'closed' OR i.verification_run_id IS NULL)", (i.rule_id,)).fetchone()["n"]
    warnings = [_warning("DISABLING_IS_NOT_REPAIR", f"{open_n} issue(s) of this rule are not resolved and stay open or claimed", "result.unresolved_issues")] if open_n else []
    last = conn.execute("SELECT rule_run_id, failure_count FROM rule_runs WHERE rule_id = %s AND run_at <= %s ORDER BY run_at DESC, rule_run_id COLLATE \"C\" DESC LIMIT 1",
                        (i.rule_id, now)).fetchone()
    carried = last["failure_count"] if rule["severity"] == "critical" and last is not None else 0
    if carried:
        warnings.append(_warning("CRITICAL_FAILURE_CARRIED", f"the latest run of this critical rule has {carried} failure(s): they keep counting, with the override, "
                                 "until a verified rerun passes (disabling never clears a live failure)", "result.carried_critical_failures"))
    return Outcome("disabled", {"rule_id": i.rule_id, "status": "disabled", "disabled_at": iso_z(now), "disabled_reason": i.reason, "runs_retained": runs,
                                "unresolved_issues": open_n, "carried_critical_failures": carried}, 1, warnings,
                   Audit("rule", i.rule_id, "disable-rule", rule["version_number"], rule["version_number"], i.reason, {"runs_retained": runs, "unresolved_issues": open_n}))
