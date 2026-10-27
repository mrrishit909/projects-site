"""Commands C01..C10 (docs/api-contract.md, docs/contracts.md D-01..D-05; backend conventions in README.md).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit together or not at all. Input is
validated (pydantic, then domain rules) before the first write. The same ``idempotency_key`` with the same payload, the same actor id and the
same role returns the stored response; with a different payload, actor or role it is a 409. Instants that are decisions (a fetch, a
validation, a commit, a run, a publication, an incident, a backfill) are stamped by the SERVER's clock, never chosen by the client.

Lock order (every command, so two commands cannot deadlock on each other):
    1. the idempotency key (advisory lock)
    2. source rows, by id (FOR NO KEY UPDATE for C01-C03, C07 crash fault and C08; FOR SHARE for C04)
    3. run / backfill / incident rows, by id (FOR NO KEY UPDATE / FOR UPDATE)
A deadlock or serialization failure that still happens is rolled back and retried, three attempts in all, then answered
409 CONCURRENT_UPDATE.

Roles (X-Actor-Role): engineer | operator | admin.  C01-C05, C08: engineer, operator, admin.  C06, C07, C09, C10: operator, admin.
"""
from __future__ import annotations

import os
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

import psycopg
from pipeline_observatory import gate as gate_mod
from pipeline_observatory.backfill import check_range, find_overlap
from pipeline_observatory.classify import (ACCEPTED, DELETED, DUPLICATE, QUARANTINED, classify_rows, money_amount,
                                           next_checkpoint_version)
from pipeline_observatory.contract import ROLES as ROLE_LIST
from pipeline_observatory.errors import DomainError
from pipeline_observatory.fetch import check_cursor_progress, check_retry_allowed, retry_not_before
from pipeline_observatory.hashing import canonical_json, content_hash, payload_hash as hash_payload, sha256_hex
from pipeline_observatory.metrics import compute
from pipeline_observatory.reconcile import reconcile
from pipeline_observatory.redaction import redact_text, redact_value
from pipeline_observatory.timeutil import iso_z, micros_between, parse_ts, seconds_between, utc_date
from psycopg.types.json import Jsonb

from . import clock, db, logs
from .errors import ApiError, detail, from_domain
from .schemas import Envelope

Conn = db.Conn
ROLES = frozenset(ROLE_LIST)
ALL_ROLES = ROLES
OPERATOR_ROLES = frozenset({"operator", "admin"})
MODEL_NAME = "sales_daily"
RETENTION = {"publication_snapshot": "immutable release asset, kept with the release", "quality_results": "versioned compact file, kept with the release",
             "raw_records": "per-batch aggregates plus a sample, kept as a versioned file (size cap)", "audit_events": "versioned compact file",
             "structured_logs": "CI artifact, 30 days, secrets redacted", "evidence_manifest": "versioned compact file with its sha256"}

#: Test seams. ``after_staging(conn, source_id, batch_id)`` runs after the batch's rows are staged and BEFORE the checkpoint is written (the
#: crash-before-checkpoint experiment); ``after_publication(conn, publication_id)`` runs after the publication row and before the pointer moves.
hooks: dict[str, Callable[..., None] | None] = {"after_staging": None, "after_publication": None}


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


def _forbidden(code: str, message: str, path: str) -> ApiError:
    return _err(403, "FORBIDDEN", code, message, path)


def _need_role(actor: Actor, allowed: frozenset[str], what: str) -> None:
    if actor.role not in allowed:
        raise _forbidden("ROLE_FORBIDDEN", f"{what} needs the role {' or '.join(sorted(allowed))}", "header.X-Actor-Role")


def _now() -> datetime:
    return clock.now()


# --- idempotent execution ---------------------------------------------------------------------------------------

def _normalise(value: Any, key: str = "") -> Any:
    """An instant (a string under a ``*_at`` key or ``watermark``) is hashed as the UTC instant it names."""
    if isinstance(value, dict):
        return {k: _normalise(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v, key) for v in value]
    if isinstance(value, str) and (key.endswith("_at") or key == "watermark"):
        try:
            return iso_z(parse_ts(value))
        except ValueError:
            return value
    return value


def _payload_hash(name: str, req: Envelope) -> str:
    """sha256 over the command name + dataset_version + input (request_id and key excluded; instants normalised). The dataset_version is
    part of the payload: the same key with another version is a different request."""
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
    """Run ``handler`` once per idempotency key. Returns ``(response body, replayed)``. A deadlock is retried (``MAX_ATTEMPTS`` attempts in
    all, short randomised back-off); the last failure is 409 CONCURRENT_UPDATE, never a 500."""
    _need_role(actor, roles, name)
    payload_hash = _payload_hash(name, req)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            body, replayed = _execute_once(name, req, actor, handler, payload_hash)
            logs.emit("command", name=name, actor_id=actor.actor_id, role=actor.role, request_id=req.request_id, replayed=replayed, status=body["status"])
            return body, replayed
        except _RETRYABLE:
            if attempt < MAX_ATTEMPTS:
                time.sleep(random.uniform(0.005, 0.03) * attempt)
    raise _conflict("CONCURRENT_UPDATE", f"the command lost a concurrent update {MAX_ATTEMPTS} times; retry it", "input")


def _check_dataset_version(conn: Conn, req: Envelope) -> None:
    """The request names the dataset it was prepared against; a different current version is 409 STALE_DATASET_VERSION and nothing is written.
    A database with no dataset_versions row has nothing to be stale against."""
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    if row is not None and row["dataset_version"] != req.dataset_version:
        raise ApiError(409, "STALE_DATASET_VERSION",
                       f"the request was prepared against dataset {req.dataset_version!r}; the current dataset is {row['dataset_version']!r}",
                       [{**detail("dataset_version", "STALE_DATASET_VERSION", "re-read the data and retry with the current dataset_version"),
                         "context": {"current": row["dataset_version"], "requested": req.dataset_version}}])


_UNIQUE_CODES = {
    "ingestion_batches_pkey": ("DUPLICATE_ID", "a batch with this id exists"),
    "task_runs_attempt_uq": ("DUPLICATE_ID", "this attempt of this task already exists in the run"),
    "checkpoints_version_uq": ("CHECKPOINT_REGRESSION", "this checkpoint version is already committed"),
    "publications_run_id_key": ("ALREADY_PUBLISHED", "this run already has a publication"),
    "evidence_archives_run_id_key": ("ALREADY_ARCHIVED", "this run's evidence is already archived"),
    "pipeline_runs_pkey": ("DUPLICATE_ID", "a run with this id exists"),
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
        except psycopg.errors.IntegrityError as exc:  # checks and triggers: append-only, pointer, checkpoint order, commit pairing ...
            msg = exc.diag.message_primary or "integrity rule violated"
            rule = msg.split(":", 1)[0] if msg.split(":", 1)[0].isupper() else "INTEGRITY_RULE"
            raise _conflict("INTEGRITY_RULE", msg, "input", rule_id=rule) from None
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        for a in ([] if out.audit is None else out.audit if isinstance(out.audit, list) else [out.audit]):
            conn.execute(
                "INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, actor_role, before_version, after_version, "
                "reason, request_id, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (f"evt-{uuid.uuid4().hex[:16]}", a.entity_type, a.entity_id, a.action, actor.actor_id, actor.role, a.before_version,
                 a.after_version, redact_value(a.reason), redact_text(req.request_id), Jsonb(redact_value(a.details))))
        body = {"command_id": command_id, "status": out.status, "result": out.result, "warnings": out.warnings, "version": out.version}
        conn.execute("INSERT INTO command_results (idempotency_key, payload_hash, actor_id, actor_role, command_id, status, result) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (req.idempotency_key, payload_hash, actor.actor_id, actor.role, command_id, out.status, Jsonb(body)))
        return body, False


def _refusal(actor: Actor, req: Envelope, action: str, entity_type: str, entity_id: str, rule_id: str, message: str,
             extra: dict[str, Any] | None = None) -> None:
    """Keep a refused decision in the audit trail (its own transaction: the command's is about to roll back)."""
    with db.autocommit() as c:
        c.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, actor_role, reason, request_id, details) "
                  "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                  (f"evt-{uuid.uuid4().hex[:16]}", entity_type, entity_id, f"{action}-refused", actor.actor_id, actor.role, redact_text(message),
                   redact_text(req.request_id), Jsonb(redact_value({"rule_id": rule_id, **(extra or {})}))))
    logs.emit("refusal", action=action, entity_type=entity_type, entity_id=entity_id, rule_id=rule_id, actor_id=actor.actor_id, request_id=req.request_id)


# --- shared lookups and locks -----------------------------------------------------------------------------------

def _free_id(conn: Conn, table: str, column: str, prefix: str, start: int, width: int = 2) -> str:
    """The first unused ``prefix-NN`` (table and column are constants of this module)."""
    n = start
    while conn.execute(f"SELECT 1 FROM {table} WHERE {column} = %s", (f"{prefix}-{n:0{width}d}",)).fetchone():
        n += 1
    return f"{prefix}-{n:0{width}d}"


def _lock_source(conn: Conn, source_id: str, exclusive: bool = True, path: str = "input.source_id") -> db.Row:
    """Lock order step 2: the source row (FOR NO KEY UPDATE or FOR SHARE: NO KEY, so a command may still write rows that reference the source on its own autocommit connection)."""
    row = conn.execute(f"SELECT * FROM source_contracts WHERE source_id = %s FOR {'NO KEY UPDATE' if exclusive else 'SHARE'}", (source_id,)).fetchone()
    if row is None:
        raise _not_found(path, "UNKNOWN_SOURCE", "source")
    return row


def _lock_run(conn: Conn, run_id: str, path: str = "input.run_id") -> db.Row:
    """Lock order step 3: the run row, FOR NO KEY UPDATE."""
    row = conn.execute("SELECT * FROM pipeline_runs WHERE run_id = %s FOR NO KEY UPDATE", (run_id,)).fetchone()
    if row is None:
        raise _not_found(path, "UNKNOWN_RUN", "run")
    return row


def _suffix(run_id: str) -> str:
    return run_id[4:] if run_id.startswith("run-") else run_id


def _next_attempt(conn: Conn, run_id: str, task_name: str, requested: int | None) -> int:
    """The attempt number of a new task row: the next one, or the one the caller names when it is exactly the next (a repeated attempt is
    DUPLICATE_ID, a skipped one ATTEMPT_GAP)."""
    last = conn.execute("SELECT coalesce(max(attempt), 0) AS n FROM task_runs WHERE run_id = %s AND task_name = %s", (run_id, task_name)).fetchone()["n"]
    if requested is None:
        return last + 1
    if requested <= last:
        raise _conflict("DUPLICATE_ID", f"attempt {requested} of task {task_name!r} already exists in run {run_id!r}", "input.attempt",
                        {"last_attempt": last})
    if requested != last + 1:
        raise _invalid("ATTEMPT_GAP", f"attempt {requested} skips {last + 1}", "input.attempt", {"last_attempt": last})
    return requested


def _add_task(conn: Conn, run_id: str, task_name: str, status: str, attempt: int) -> str:
    n = conn.execute("SELECT count(*) AS n FROM task_runs WHERE run_id = %s", (run_id,)).fetchone()["n"] + 1
    tid = _free_id(conn, "task_runs", "task_run_id", f"tr-{_suffix(run_id)}", n)
    conn.execute("INSERT INTO task_runs (task_run_id, run_id, task_name, status, attempt) VALUES (%s, %s, %s, %s, %s)", (tid, run_id, task_name, status, attempt))
    return tid


def _add_results(conn: Conn, run_id: str, task_run_id: str, results: list[tuple[str, str, int, int]]) -> list[dict[str, Any]]:
    out = []
    for rule, severity, eligible, failures in results:
        seq = conn.execute("SELECT count(*) AS n FROM quality_results q JOIN task_runs t ON t.task_run_id = q.task_run_id WHERE t.run_id = %s", (run_id,)).fetchone()["n"] + 1
        qid = _free_id(conn, "quality_results", "quality_result_id", f"qr-{_suffix(run_id)}", seq, 4)
        conn.execute("INSERT INTO quality_results (quality_result_id, task_run_id, rule_name, severity, eligible_count, failure_count) VALUES (%s,%s,%s,%s,%s,%s)",
                     (qid, task_run_id, rule, severity, eligible, failures))
        out.append({"quality_result_id": qid, "rule_name": rule, "severity": severity, "eligible_count": eligible, "failure_count": failures, "passed": failures == 0})
    return out


def _run_gate(conn: Conn, run_id: str) -> dict[str, Any]:
    rows = conn.execute("SELECT q.* FROM quality_results q JOIN task_runs t ON t.task_run_id = q.task_run_id WHERE t.run_id = %s", (run_id,)).fetchall()
    return gate_mod.decide(rows)


def _open_incident(conn: Conn, run_id: str, reason: str, now: datetime, severity: str = "high") -> str:
    iid = _free_id(conn, "incidents", "incident_id", "inc", 1, 3)
    conn.execute("INSERT INTO incidents (incident_id, run_id, severity, status, opened_at, reason) VALUES (%s, %s, %s, 'open', %s, %s)", (iid, run_id, severity, now, reason))
    return iid


def _scope_facts(conn: Conn, batch_ids: list[str]) -> tuple[list[tuple[str, Decimal]], list[Any], Decimal]:
    """(disposition, amount) of every received row of the batches, the records a delete event of these batches removed, and the delete rows' amount."""
    rows = conn.execute("SELECT raw_record_id, payload_json, disposition FROM raw_records WHERE batch_id = ANY(%s) ORDER BY raw_record_id COLLATE \"C\"", (batch_ids,)).fetchall()
    src = [(r["disposition"] or QUARANTINED, money_amount(r["payload_json"])) for r in rows]
    removed = [SimpleNamespace(amount=money_amount(r["payload_json"])) for r in conn.execute(
        "SELECT r.payload_json FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id "
        "WHERE a.batch_id = ANY(%s) AND a.deleted_in_batch = ANY(%s)", (batch_ids, batch_ids)).fetchall()]
    deletes = sum((amt for k, amt in src if k == DELETED), Decimal("0"))
    return src, removed, deletes


# --- C01 fetch-source-page ------------------------------------------------------------------------------------------

def fetch_source_page(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """cursor -> raw page. The page the source answered with is staged as a batch (status ``staged``, rows unclassified). A 429 page records the
    retry-after hint and a retry sooner than that is refused (RETRY_TOO_SOON); a ``next_cursor`` that repeats inside a fetch session is
    CURSOR_LOOP and stops the session (P08-FLOW-01, P08-TEST-03, P08-TEST-10)."""
    i = req.input
    now = _now()
    _lock_source(conn, i.source_id)
    if i.fetch_session and conn.execute("SELECT 1 FROM fetch_log WHERE source_id = %s AND session_id = %s AND status = 'cursor_loop' LIMIT 1",
                                        (i.source_id, i.fetch_session)).fetchone():
        raise _conflict("CURSOR_LOOP", "this fetch session was stopped by a repeating cursor; start a new session", "input.fetch_session", rule_id="CURSOR_LOOP")
    last = conn.execute("SELECT status, retry_after_seconds, fetched_at FROM fetch_log WHERE source_id = %s AND cursor_value = %s "
                        "ORDER BY fetched_at DESC, fetch_id DESC LIMIT 1", (i.source_id, i.cursor)).fetchone()
    if last and last["status"] == "rate_limited":
        try:
            check_retry_allowed(last["fetched_at"], last["retry_after_seconds"], now)
        except DomainError as err:
            _refusal(actor, req, "fetch-source-page", "source", i.source_id, err.code, err.message, {"cursor": i.cursor, **err.details})
            raise from_domain(err, "input.cursor") from None
    page = i.page
    if page.status == 429:
        if page.retry_after_seconds is None:
            raise _invalid("RETRY_AFTER_REQUIRED", "a 429 page must carry retry_after_seconds", "input.page.retry_after_seconds")
        conn.execute("INSERT INTO fetch_log (source_id, cursor_value, session_id, status, retry_after_seconds, fetched_at) VALUES (%s,%s,%s,'rate_limited',%s,%s)",
                     (i.source_id, i.cursor, i.fetch_session, page.retry_after_seconds, now))
        not_before = retry_not_before(now, page.retry_after_seconds)
        return Outcome("rate_limited", {"source_id": i.source_id, "cursor": i.cursor, "retry_after_seconds": page.retry_after_seconds,
                                        "retry_not_before": iso_z(not_before), "batch_id": None},
                       warnings=[_warning("RATE_LIMITED", f"retry no sooner than {iso_z(not_before)}", "input.page")],
                       audit=Audit("source", i.source_id, "fetch-source-page", details={"cursor": i.cursor, "status": "rate_limited", "retry_after_seconds": page.retry_after_seconds}))
    seen: set[str] = set()
    if i.fetch_session:
        for r in conn.execute("SELECT cursor_value, next_cursor FROM fetch_log WHERE source_id = %s AND session_id = %s AND status = 'ok'", (i.source_id, i.fetch_session)).fetchall():
            seen.add(r["cursor_value"])
            if r["next_cursor"]:
                seen.add(r["next_cursor"])
    try:
        check_cursor_progress(i.cursor, page.next_cursor, seen)
    except DomainError as err:
        with db.autocommit() as c:         # the loop is evidence: it survives the rollback of this command
            c.execute("INSERT INTO fetch_log (source_id, cursor_value, session_id, status, next_cursor, fetched_at) VALUES (%s,%s,%s,'cursor_loop',%s,%s)",
                      (i.source_id, i.cursor, i.fetch_session, page.next_cursor, now))
        _refusal(actor, req, "fetch-source-page", "source", i.source_id, err.code, err.message, {"cursor": i.cursor, "next_cursor": page.next_cursor})
        raise from_domain(err, "input.page.next_cursor") from None
    batch_id = i.batch_id or f"b-{uuid.uuid4().hex[:12]}"
    if conn.execute("SELECT 1 FROM ingestion_batches WHERE batch_id = %s", (batch_id,)).fetchone():
        raise _conflict("DUPLICATE_ID", f"batch {batch_id!r} already exists", "input.batch_id", rule_id="DUPLICATE_ID")
    conn.execute("INSERT INTO ingestion_batches (batch_id, source_id, source_cursor, started_at, status, next_cursor, schema_version, fetch_session) VALUES (%s,%s,%s,%s,'staged',%s,%s,%s)",
                 (batch_id, i.source_id, i.cursor, now, page.next_cursor, page.schema_version, i.fetch_session))
    ids = []
    for n, rec in enumerate(page.records, 1):
        key = rec.source_key if rec.source_key is not None else (rec.payload.get("record_id") if isinstance(rec.payload.get("record_id"), str) else None)
        h = hash_payload(rec.payload)
        if rec.payload_hash is not None and rec.payload_hash != h:
            raise _invalid("PAYLOAD_HASH_MISMATCH", f"record {n} carries a payload_hash that is not the sha256 of its canonical payload", f"input.page.records[{n - 1}].payload_hash")
        rid = f"rr-{batch_id}-{n:04d}"
        conn.execute("INSERT INTO raw_records (raw_record_id, batch_id, source_key, payload_hash, payload_json) VALUES (%s,%s,%s,%s,%s)", (rid, batch_id, key, h, Jsonb(rec.payload)))
        ids.append(rid)
    conn.execute("INSERT INTO fetch_log (source_id, cursor_value, session_id, status, next_cursor, fetched_at, batch_id) VALUES (%s,%s,%s,'ok',%s,%s,%s)",
                 (i.source_id, i.cursor, i.fetch_session, page.next_cursor, now, batch_id))
    return Outcome("staged", {"batch_id": batch_id, "source_id": i.source_id, "cursor": i.cursor, "next_cursor": page.next_cursor, "received": len(ids),
                              "schema_version": page.schema_version, "started_at": iso_z(now), "raw_record_ids": ids},
                   audit=Audit("batch", batch_id, "fetch-source-page", details={"source_id": i.source_id, "cursor": i.cursor, "received": len(ids)}))


# --- C02 validate-contract ------------------------------------------------------------------------------------------

def _accepted_keys(conn: Conn, source_id: str) -> tuple[set[str], set[str]]:
    rows = conn.execute("SELECT source_key, deleted_in_batch IS NOT NULL AS deleted FROM accepted_records WHERE source_id = %s", (source_id,)).fetchall()
    return {r["source_key"] for r in rows}, {r["source_key"] for r in rows if r["deleted"]}


def _classify_batch(conn: Conn, batch: db.Row, schema_ok: bool) -> list[Any]:
    rows = conn.execute("SELECT raw_record_id, source_key, payload_json FROM raw_records WHERE batch_id = %s ORDER BY raw_record_id COLLATE \"C\"", (batch["batch_id"],)).fetchall()
    keys, deleted = _accepted_keys(conn, batch["source_id"])
    return classify_rows(rows, keys, deleted, schema_ok)


def _staged_batch(conn: Conn, batch_id: str) -> tuple[db.Row, db.Row]:
    """Lock order: the batch's source first, then the batch. Returns (source, batch)."""
    pre = conn.execute("SELECT source_id FROM ingestion_batches WHERE batch_id = %s", (batch_id,)).fetchone()
    if pre is None:
        raise _not_found("input.batch_id", "UNKNOWN_BATCH", "batch")
    src = _lock_source(conn, pre["source_id"])
    b = conn.execute("SELECT * FROM ingestion_batches WHERE batch_id = %s FOR NO KEY UPDATE", (batch_id,)).fetchone()
    return src, b


def validate_contract(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """raw -> accepted / duplicate / quarantined, per row, nothing dropped. A batch declaring another schema_version than the source's expected
    one is quarantined WHOLE with SCHEMA_CHANGED (the checkpoint does not move); the expected version changes only by the explicit
    ``bump_schema_version`` of an operator or admin (P08-TEST-04)."""
    i = req.input
    now = _now()
    src, b = _staged_batch(conn, i.batch_id)
    if b["status"] != "staged":
        raise _conflict("BATCH_NOT_STAGED", f"batch {b['batch_id']!r} is {b['status']}; only a staged batch is validated", "input.batch_id", {"status": b["status"]})
    expected = src["schema_version"]
    audits: list[Audit] = []
    if i.bump_schema_version is not None:
        _need_role(actor, OPERATOR_ROLES, "bump_schema_version")
        if b["schema_version"] != i.bump_schema_version:
            raise _invalid("SCHEMA_VERSION_MISMATCH", "the bump must name the schema_version the batch declares", "input.bump_schema_version",
                           {"batch_schema_version": b["schema_version"]})
        conn.execute("UPDATE source_contracts SET schema_version = %s WHERE source_id = %s", (i.bump_schema_version, src["source_id"]))
        audits.append(Audit("source", src["source_id"], "bump-schema-version", reason="explicit bump", details={"from": expected, "to": i.bump_schema_version}))
        expected = i.bump_schema_version
    schema_ok = b["schema_version"] in (None, expected)
    disp = _classify_batch(conn, b, schema_ok)
    reasons: dict[str, int] = {}
    for d in disp:
        conn.execute("UPDATE raw_records SET disposition = %s, reason_code = %s WHERE raw_record_id = %s", (d.kind, d.reason, d.raw_record_id))
        if d.reason:
            reasons[d.reason] = reasons.get(d.reason, 0) + 1
    kinds = [d.kind for d in disp]
    counts = {"received": len(disp), "accepted_unique": kinds.count(ACCEPTED), "duplicate": kinds.count(DUPLICATE), "quarantined": kinds.count(QUARANTINED),
              "deleted": kinds.count(DELETED)}
    warnings: list[dict[str, Any]] = []
    status = "validated"
    if not schema_ok:
        status = "quarantined"
        conn.execute("UPDATE ingestion_batches SET status = 'quarantined', validated_at = %s WHERE batch_id = %s", (now, b["batch_id"]))
        raws = {r["raw_record_id"]: r for r in conn.execute("SELECT raw_record_id, source_key, payload_hash FROM raw_records WHERE batch_id = %s", (b["batch_id"],)).fetchall()}
        for n, d in enumerate(disp, 1):
            conn.execute("INSERT INTO quarantine_records (quarantine_id, batch_id, source_key, reason_code, payload_hash) VALUES (%s,%s,%s,%s,%s)",
                         (f"q-{b['batch_id']}-{n:02d}", b["batch_id"], raws[d.raw_record_id]["source_key"], d.reason, raws[d.raw_record_id]["payload_hash"]))
        warnings.append(_warning("SCHEMA_CHANGED", f"batch declares schema_version {b['schema_version']!r}, the source expects {expected!r}; the whole batch is quarantined "
                                 "and the checkpoint does not move. Bump the expected version explicitly (operator or admin) and fetch the window again.", "input.batch_id"))
    else:
        conn.execute("UPDATE ingestion_batches SET validated_at = %s WHERE batch_id = %s", (now, b["batch_id"]))
    audits.append(Audit("batch", b["batch_id"], "validate-contract", details={**counts, "status": status, "reasons": reasons}))
    return Outcome(status, {"batch_id": b["batch_id"], "source_id": b["source_id"], "status": status, **counts, "quarantine_by_reason": dict(sorted(reasons.items())),
                            "expected_schema_version": expected, "batch_schema_version": b["schema_version"], "validated_at": iso_z(now)},
                   warnings=warnings, audit=audits)


# --- C03 commit-batch -----------------------------------------------------------------------------------------------

def commit_batch(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """staged -> durable batch + checkpoint, ONE transaction: the accepted records, the quarantine rows, the batch status and the checkpoint
    row (version = previous + 1) commit together or not at all. Apply is idempotent on source_key (``accepted_records`` is unique on
    (source_id, source_key)): a replay yields duplicates, never a second accepted record. The delivery guarantee is at-least-once with
    idempotent apply, proven at the source-key boundary, never exactly-once (P08-FLOW-03, P08-TEST-01)."""
    i = req.input
    now = _now()
    src, b = _staged_batch(conn, i.batch_id)
    if b["status"] != "staged":
        code = {"committed": "BATCH_ALREADY_COMMITTED", "quarantined": "BATCH_QUARANTINED", "aborted": "BATCH_ABORTED"}.get(b["status"], "BATCH_NOT_STAGED")
        raise _conflict(code, f"batch {b['batch_id']!r} is {b['status']}", "input.batch_id", {"status": b["status"]})
    if b["validated_at"] is None:
        raise _conflict("BATCH_NOT_VALIDATED", "validate the batch (C02) before committing it", "input.batch_id")
    if b["schema_version"] not in (None, src["schema_version"]):
        raise _conflict("SCHEMA_CHANGED", "the batch declares a schema_version the source does not expect; validate it again after the explicit bump", "input.batch_id")
    prev = conn.execute("SELECT coalesce(max(version_number), 0) AS v FROM checkpoints WHERE source_id = %s", (b["source_id"],)).fetchone()["v"]
    try:
        version = next_checkpoint_version(prev, i.checkpoint_version if i.checkpoint_version is not None else prev + 1)
    except DomainError as err:
        _refusal(actor, req, "commit-batch", "batch", b["batch_id"], err.code, err.message, err.details)
        raise from_domain(err, "input.checkpoint_version") from None
    disp = _classify_batch(conn, b, True)                      # authoritative: against what is accepted NOW, under the source lock
    raws = {r["raw_record_id"]: r for r in conn.execute("SELECT raw_record_id, source_key, payload_hash, payload_json FROM raw_records WHERE batch_id = %s", (b["batch_id"],)).fetchall()}
    n_acc = n_q = 0
    for d in disp:
        conn.execute("UPDATE raw_records SET disposition = %s, reason_code = %s WHERE raw_record_id = %s", (d.kind, d.reason, d.raw_record_id))
        r = raws[d.raw_record_id]
        if d.kind == ACCEPTED:
            got = conn.execute("INSERT INTO accepted_records (source_id, source_key, raw_record_id, batch_id, accepted_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                               (b["source_id"], r["source_key"], d.raw_record_id, b["batch_id"], now)).rowcount
            if got != 1:
                raise _conflict("IDEMPOTENCY_BOUNDARY", f"source key {r['source_key']!r} was accepted concurrently", "input.batch_id")
            n_acc += 1
        elif d.kind == DELETED:
            conn.execute("UPDATE accepted_records SET deleted_in_batch = %s WHERE source_id = %s AND source_key = %s", (b["batch_id"], b["source_id"], r["source_key"]))
        elif d.kind == QUARANTINED:
            n_q += 1
            conn.execute("INSERT INTO quarantine_records (quarantine_id, batch_id, source_key, reason_code, payload_hash) VALUES (%s,%s,%s,%s,%s)",
                         (f"q-{b['batch_id']}-{n_q:02d}", b["batch_id"], r["source_key"], d.reason, r["payload_hash"]))
    # ---- the data is written; the checkpoint is not. A crash here must leave NOTHING behind (the transaction rolls back).
    if hooks["after_staging"] is not None:
        hooks["after_staging"](conn, b["source_id"], b["batch_id"])
    armed = conn.execute("SELECT fault_id FROM fault_injections WHERE fault_type = 'crash_before_checkpoint' AND target_id = %s AND armed ORDER BY injected_at, fault_id LIMIT 1",
                         (b["source_id"],)).fetchone()
    if armed:
        with db.autocommit() as c:
            c.execute("UPDATE fault_injections SET armed = false, consumed_at = %s WHERE fault_id = %s", (now, armed["fault_id"]))
        _refusal(actor, req, "commit-batch", "batch", b["batch_id"], "INJECTED_CRASH", "an injected fault killed the commit before the checkpoint", {"fault_id": armed["fault_id"]})
        raise ApiError(500, "INJECTED_CRASH", "an injected fault killed the commit before the checkpoint; nothing was committed",
                       [detail("input.batch_id", "INJECTED_CRASH", "crash after the data write, before the checkpoint")])
    cursor = b["next_cursor"] or b["source_cursor"]
    cp_id = f"cp-{b['batch_id']}"
    conn.execute("INSERT INTO checkpoints (checkpoint_id, source_id, batch_id, committed_cursor, committed_at, version_number) VALUES (%s,%s,%s,%s,%s,%s)",
                 (cp_id, b["source_id"], b["batch_id"], cursor, now, version))
    conn.execute("UPDATE ingestion_batches SET status = 'committed' WHERE batch_id = %s", (b["batch_id"],))
    if i.processing is not None:
        conn.execute("INSERT INTO processing_measurements (source_id, batch_id, measured_seconds, hardware, cache_state, recorded_at) VALUES (%s,%s,%s,%s,%s,%s)",
                     (b["source_id"], b["batch_id"], i.processing.measured_seconds, i.processing.hardware, i.processing.cache_state, now))
    kinds = [d.kind for d in disp]
    total = conn.execute("SELECT count(*) AS n FROM accepted_records WHERE source_id = %s", (b["source_id"],)).fetchone()["n"]
    counts = {"received": len(disp), "accepted_unique": kinds.count(ACCEPTED), "duplicate": kinds.count(DUPLICATE), "quarantined": kinds.count(QUARANTINED),
              "deleted": kinds.count(DELETED)}
    return Outcome("committed", {"batch_id": b["batch_id"], "source_id": b["source_id"], **counts, "source_accepted_total": total,
                                 "checkpoint": {"checkpoint_id": cp_id, "version_number": version, "committed_cursor": cursor, "committed_at": iso_z(now)},
                                 "delivery_guarantee": "at-least-once with idempotent apply on source_key"},
                   version=version, audit=Audit("batch", b["batch_id"], "commit-batch", prev, version, details={**counts, "checkpoint_id": cp_id}))


# --- C04 transform-models -------------------------------------------------------------------------------------------

def transform_models(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """staging -> analytical tables. Builds ``model_outputs`` (the published shape, one row per accepted record of the batches that no included
    delete event removed) for a run (created here when ``run_id`` is new or absent), then runs the key and relationship tests as critical
    results ``model_keys_unique`` and ``model_relationships_intact`` on the transform task (P08-FLOW-04)."""
    i = req.input
    now = _now()
    batch_ids = sorted(set(i.batch_ids))
    found = {r["batch_id"]: r for r in conn.execute("SELECT batch_id, source_id, status FROM ingestion_batches WHERE batch_id = ANY(%s)", (batch_ids,)).fetchall()}
    for n, bid in enumerate(i.batch_ids):
        if bid not in found:
            raise _not_found(f"input.batch_ids[{n}]", "UNKNOWN_BATCH", "batch")
    bad = sorted(b for b, r in found.items() if r["status"] != "committed")
    if bad:
        raise _conflict("BATCH_NOT_COMMITTED", f"only committed batches are transformed; not committed: {', '.join(bad)}", "input.batch_ids", {"batches": bad})
    for sid in sorted({r["source_id"] for r in found.values()}):
        _lock_source(conn, sid, exclusive=False)
    run_id = i.run_id or f"run-{uuid.uuid4().hex[:12]}"
    created = False
    if conn.execute("SELECT 1 FROM pipeline_runs WHERE run_id = %s", (run_id,)).fetchone() is None:
        if i.backfill_id and not conn.execute("SELECT 1 FROM backfill_requests WHERE backfill_id = %s", (i.backfill_id,)).fetchone():
            raise _not_found("input.backfill_id", "UNKNOWN_BACKFILL", "backfill")
        conn.execute("INSERT INTO pipeline_runs (run_id, started_at, status, code_sha, backfill_id) VALUES (%s,%s,'running',%s,%s) ON CONFLICT DO NOTHING",
                     (run_id, now, os.environ.get("CODE_SHA", "dev"), i.backfill_id))
        created = True
    run = _lock_run(conn, run_id)
    if run["status"] != "running":
        raise _conflict("RUN_NOT_OPEN", f"run {run_id!r} is {run['status']}; start a new run", "input.run_id", {"status": run["status"]})
    if i.backfill_id is not None and run["backfill_id"] != i.backfill_id:
        raise _conflict("BACKFILL_MISMATCH", "the run belongs to another backfill", "input.backfill_id")
    if created:
        _add_task(conn, run_id, "ingest", "success", 1)
    attempt = _next_attempt(conn, run_id, "transform", i.attempt)
    conn.execute("DELETE FROM model_outputs WHERE run_id = %s", (run_id,))
    rows = conn.execute(
        "SELECT a.source_id, a.source_key, a.batch_id, r.payload_hash, r.payload_json FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id "
        "WHERE a.batch_id = ANY(%s) AND (a.deleted_in_batch IS NULL OR NOT (a.deleted_in_batch = ANY(%s))) ORDER BY a.source_id COLLATE \"C\", a.source_key COLLATE \"C\"",
        (batch_ids, batch_ids)).fetchall()
    for r in rows:
        conn.execute("INSERT INTO model_outputs (run_id, model_name, source_id, record_key, batch_id, day, amount, payload_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                     (run_id, MODEL_NAME, r["source_id"], r["source_key"], r["batch_id"], utc_date(r["payload_json"]["event_ts"]), money_amount(r["payload_json"]), r["payload_hash"]))
    conn.execute("UPDATE pipeline_runs SET included_batch_ids = %s WHERE run_id = %s", (batch_ids, run_id))
    keys = _key_test(conn, run_id)
    rel = _relationship_test(conn, run_id)
    ok = keys[1] == 0 and rel[1] == 0
    tid = _add_task(conn, run_id, "transform", "success" if ok else "failed", attempt)
    results = _add_results(conn, run_id, tid, [("model_keys_unique", "critical", *keys), ("model_relationships_intact", "critical", *rel)])
    warnings = [] if ok else [_warning("TRANSFORM_TESTS_FAILED", "a key or relationship test failed; the gate will block this run", "result.tests")]
    return Outcome("transformed" if ok else "tests_failed", {"run_id": run_id, "task_run_id": tid, "attempt": attempt, "run_created": created, "included_batch_ids": batch_ids,
                                                             "outputs": len(rows), "tests": results},
                   warnings=warnings, audit=Audit("run", run_id, "transform-models", details={"batches": batch_ids, "outputs": len(rows), "attempt": attempt, "tests_passed": ok}))


def _key_test(conn: Conn, run_id: str) -> tuple[int, int]:
    r = conn.execute("SELECT count(*) AS n, count(*) - count(DISTINCT (source_id, record_key)) AS dup FROM model_outputs WHERE run_id = %s", (run_id,)).fetchone()
    return r["n"], r["dup"]


def _relationship_test(conn: Conn, run_id: str) -> tuple[int, int]:
    r = conn.execute("SELECT count(*) AS n, count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM accepted_records a WHERE a.source_id = o.source_id AND a.source_key = o.record_key "
                     "AND a.batch_id = o.batch_id)) AS orphan FROM model_outputs o WHERE o.run_id = %s", (run_id,)).fetchone()
    return r["n"], r["orphan"]


# --- C05 run-quality-gate -------------------------------------------------------------------------------------------

def run_quality_gate(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """candidate -> pass / block, FAIL CLOSED. Critical checks: keys unique, relationships intact, reconciliation residual 0.00, freshness within
    target (for sources that declare one). Completeness against the declared expectation is a warning. Any critical failure blocks, fails the
    run and opens an incident; no critical result at all also blocks (P08-FLOW-05, P08-TEST-06/07)."""
    i = req.input
    now = _now()
    run = _lock_run(conn, i.run_id)
    if run["status"] != "running":
        raise _conflict("RUN_NOT_OPEN", f"run {run['run_id']!r} is {run['status']}", "input.run_id", {"status": run["status"]})
    batch_ids = list(run["included_batch_ids"])
    if not batch_ids:
        raise _conflict("TRANSFORM_REQUIRED", "transform the run (C04) before gating it", "input.run_id")
    attempt = _next_attempt(conn, run["run_id"], "quality_gate", i.attempt)
    sources = sorted({r["source_id"] for r in conn.execute("SELECT source_id FROM ingestion_batches WHERE batch_id = ANY(%s)", (batch_ids,)).fetchall()})
    keys, rel = _key_test(conn, run["run_id"]), _relationship_test(conn, run["run_id"])
    src_rows, removed, del_amt = _scope_facts(conn, batch_ids)
    published = conn.execute("SELECT coalesce(sum(amount), 0) AS total FROM model_outputs WHERE run_id = %s", (run["run_id"],)).fetchone()["total"]
    rec = reconcile(src_rows, [], del_amt, removed, published)                       # the published total is the stored table's, not a recomputation
    checks: list[tuple[str, str, int, int]] = [("keys_unique", "critical", keys[0], keys[1]), ("relationships_intact", "critical", rel[0], rel[1]),
                                               ("reconciliation_residual_zero", "critical", 1, 0 if rec["residual"] == "0.00" else 1)]
    targets = conn.execute("SELECT source_id, freshness_target_seconds AS t FROM source_contracts WHERE source_id = ANY(%s) AND freshness_target_seconds IS NOT NULL ORDER BY source_id", (sources,)).fetchall()
    if targets:
        stale = 0
        for t in targets:
            latest = conn.execute("SELECT max((r.payload_json ->> 'event_ts')::timestamptz) AS m FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id WHERE a.source_id = %s", (t["source_id"],)).fetchone()["m"]
            if latest is None or micros_between(latest, now) > t["t"] * 1_000_000:
                stale += 1
        checks.append(("freshness_within_target", "critical", len(targets), stale))
    exp = conn.execute("SELECT x.source_id, x.partition, x.expected_records, (SELECT count(*) FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id "
                       "WHERE a.source_id = x.source_id AND to_char((r.payload_json ->> 'event_ts')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD') = x.partition) AS n "
                       "FROM source_expectations x WHERE x.source_id = ANY(%s)", (sources,)).fetchall()
    if exp:
        checks.append(("completeness_vs_expectation", "warning", sum(e["expected_records"] for e in exp), sum(max(e["expected_records"] - e["n"], 0) for e in exp)))
    tid = _add_task(conn, run["run_id"], "quality_gate", "running", attempt)
    results = _add_results(conn, run["run_id"], tid, checks)
    gate = _run_gate(conn, run["run_id"])
    allowed = gate["decision"] == gate_mod.ALLOWED
    conn.execute("UPDATE task_runs SET status = %s WHERE task_run_id = %s", ("success" if allowed else "failed", tid))
    incident_id = None
    if allowed:
        conn.execute("UPDATE pipeline_runs SET status = 'success' WHERE run_id = %s", (run["run_id"],))
    else:
        conn.execute("UPDATE pipeline_runs SET status = 'failed', finished_at = %s WHERE run_id = %s", (now, run["run_id"]))
        incident_id = _open_incident(conn, run["run_id"], "GATE_BLOCKED", now)
    return Outcome("allowed" if allowed else "blocked",
                   {"run_id": run["run_id"], "task_run_id": tid, "attempt": attempt, "decision": gate["decision"], "critical_failures": gate["critical_failures"],
                    "noncritical_failures": gate["noncritical_failures"], "results": results, "reconciliation": rec, "incident_id": incident_id},
                   warnings=[] if allowed else [_warning("GATE_BLOCKED", "a critical check failed: publication is blocked and an incident is open", "result.results")],
                   audit=Audit("run", run["run_id"], "run-quality-gate", details={"decision": gate["decision"], "critical_failures": gate["critical_failures"], "incident_id": incident_id}))


# --- C06 publish-snapshot -------------------------------------------------------------------------------------------

def publish_snapshot(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """passed candidate -> current. REFUSES a run whose status is not success or whose gate is blocked, and then NEVER moves the pointer. The
    publication row and the pointer move in this one transaction (atomic); the watermark is disclosed with the publication; published_at is
    the server's (P08-FLOW-06, P08-TEST-07, P08-TEST-09)."""
    i = req.input
    now = _now()
    run = _lock_run(conn, i.run_id)
    if run["status"] != "success":
        _refusal(actor, req, "publish-snapshot", "run", run["run_id"], "RUN_NOT_SUCCESSFUL", f"run is {run['status']}", {"status": run["status"]})
        raise _conflict("RUN_NOT_SUCCESSFUL", f"run {run['run_id']!r} is {run['status']}; only a successful, gated run is published", "input.run_id", {"status": run["status"]})
    gate = _run_gate(conn, run["run_id"])
    if gate["decision"] != gate_mod.ALLOWED:
        _refusal(actor, req, "publish-snapshot", "run", run["run_id"], "GATE_BLOCKED", "the quality gate is not allowed", {"critical_failures": gate["critical_failures"]})
        raise _conflict("GATE_BLOCKED", f"the quality gate of run {run['run_id']!r} is {gate['decision']}", "input.run_id", {"critical_failures": gate["critical_failures"]})
    if conn.execute("SELECT 1 FROM publications WHERE run_id = %s", (run["run_id"],)).fetchone():
        raise _conflict("ALREADY_PUBLISHED", f"run {run['run_id']!r} already has a publication", "input.run_id")
    batch_ids = list(run["included_batch_ids"])
    if not batch_ids:
        raise _conflict("TRANSFORM_REQUIRED", "the run has no transformed scope", "input.run_id")
    watermark = parse_ts(i.watermark)
    if watermark > now:
        raise _invalid("WATERMARK_IN_FUTURE", "the watermark cannot be after the server's time", "input.watermark")
    attempt = _next_attempt(conn, run["run_id"], "publish", i.attempt)
    hashes = [r["payload_hash"] for r in conn.execute("SELECT payload_hash FROM model_outputs WHERE run_id = %s", (run["run_id"],)).fetchall()]
    sources = [r["source_id"] for r in conn.execute("SELECT source_id FROM source_contracts ORDER BY source_id COLLATE \"C\"").fetchall()]   # the dataset's sources
    pid = f"pub-{_suffix(run['run_id'])}"
    chash = content_hash(hashes)
    conn.execute("INSERT INTO publications (publication_id, run_id, dataset_name, published_at, watermark, source_ids, included_batch_ids, content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                 (pid, run["run_id"], i.dataset_name, now, watermark, sources, batch_ids, chash))
    if hooks["after_publication"] is not None:
        hooks["after_publication"](conn, pid)
    before = conn.execute("SELECT publication_id FROM publication_pointer WHERE id = 1 FOR UPDATE").fetchone()
    conn.execute("INSERT INTO publication_pointer (id, publication_id, updated_at) VALUES (1, %s, %s) ON CONFLICT (id) DO UPDATE SET publication_id = EXCLUDED.publication_id, updated_at = EXCLUDED.updated_at",
                 (pid, now))
    _add_task(conn, run["run_id"], "publish", "success", attempt)
    conn.execute("UPDATE pipeline_runs SET finished_at = %s WHERE run_id = %s", (now, run["run_id"]))
    latest = conn.execute("SELECT max((r.payload_json ->> 'event_ts')::timestamptz) AS m FROM model_outputs o JOIN accepted_records a ON a.source_id = o.source_id AND a.source_key = o.record_key "
                          "JOIN raw_records r ON r.raw_record_id = a.raw_record_id WHERE o.run_id = %s", (run["run_id"],)).fetchone()["m"]
    backfill = _verify_backfill(conn, run, batch_ids) if run["backfill_id"] else None
    return Outcome("published", {"publication_id": pid, "run_id": run["run_id"], "published_at": iso_z(now), "watermark": iso_z(watermark), "content_hash": chash,
                                 "published_records": len(hashes), "latest_included_event_at": iso_z(latest),
                                 "lag_seconds": seconds_between(latest, now) if latest else None, "included_batch_ids": batch_ids,
                                 "previous_publication_id": before["publication_id"] if before else None, "current_publication_id": pid, "backfill": backfill},
                   audit=Audit("publication", pid, "publish-snapshot", details={"run_id": run["run_id"], "content_hash": chash, "watermark": iso_z(watermark),
                                                                                "previous_publication_id": before["publication_id"] if before else None}))


def _verify_backfill(conn: Conn, run: db.Row, batch_ids: list[str]) -> dict[str, Any]:
    """A published backfill run verifies the partitions whose accepted records in the run's scope reach the declared expectation (> 0)."""
    bf = conn.execute("SELECT * FROM backfill_requests WHERE backfill_id = %s FOR UPDATE", (run["backfill_id"],)).fetchone()
    parts = []
    for p in bf["partitions"]:
        exp = conn.execute("SELECT expected_records FROM source_expectations WHERE source_id = %s AND partition = %s", (bf["source_id"], p["partition"])).fetchone()
        n = conn.execute("SELECT count(*) AS n FROM accepted_records a JOIN raw_records r ON r.raw_record_id = a.raw_record_id WHERE a.source_id = %s AND a.batch_id = ANY(%s) "
                         "AND to_char((r.payload_json ->> 'event_ts')::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD') = %s", (bf["source_id"], batch_ids, p["partition"])).fetchone()["n"]
        verified = bool(p["verified"]) or (exp is not None and exp["expected_records"] > 0 and n >= exp["expected_records"])
        parts.append({"partition": p["partition"], "verified": verified})
    status = "complete" if all(p["verified"] for p in parts) else "partial"
    conn.execute("UPDATE backfill_requests SET partitions = %s, status = %s WHERE backfill_id = %s", (Jsonb(parts), status, bf["backfill_id"]))
    return {"backfill_id": bf["backfill_id"], "status": status, "verified_partitions": sum(1 for p in parts if p["verified"]), "requested_partitions": len(parts)}


# --- C07 inject-fault -----------------------------------------------------------------------------------------------

def sandbox() -> bool:
    """Fault injection is allowed only in the synthetic sandbox: PIPELINE_ENVIRONMENT must be ``sandbox`` (the default for this synthetic product)."""
    return os.environ.get("PIPELINE_ENVIRONMENT", "sandbox") == "sandbox"


def inject_fault(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """healthy -> controlled failure, SANDBOX ONLY and always recorded (``fault_injections`` and the audit trail; P08-FLOW-07).
    duplicate_key: a copy of an output row enters the run's table (the gate must block); task_failure: the run fails and an incident opens;
    crash_before_checkpoint: the next commit on the source dies after its data write, before its checkpoint."""
    i = req.input
    now = _now()
    if not sandbox():
        _refusal(actor, req, "inject-fault", "fault", i.target_id, "NOT_SANDBOX", "fault injection is only allowed in the synthetic sandbox", {"fault_type": i.fault_type})
        raise _forbidden("NOT_SANDBOX", "fault injection is only allowed in the synthetic sandbox", "input.fault_type")
    fid = f"ft-{uuid.uuid4().hex[:12]}"
    note = redact_text(i.note) if i.note is not None else None            # a note is free text: it never carries a secret into a table or a log
    detail_out: dict[str, Any] = {}
    armed = False
    if i.fault_type == "crash_before_checkpoint":
        _lock_source(conn, i.target_id, path="input.target_id")
        armed = True
    else:
        run = _lock_run(conn, i.target_id, "input.target_id")
        if run["status"] != "running":
            raise _conflict("RUN_NOT_OPEN", f"run {run['run_id']!r} is {run['status']}; a fault is injected into a healthy, running run", "input.target_id", {"status": run["status"]})
        if i.fault_type == "duplicate_key":
            row = conn.execute("SELECT * FROM model_outputs WHERE run_id = %s ORDER BY output_id LIMIT 1", (run["run_id"],)).fetchone()
            if row is None:
                raise _conflict("NO_OUTPUTS", "transform the run (C04) before injecting a duplicate key", "input.target_id")
            conn.execute("INSERT INTO model_outputs (run_id, model_name, source_id, record_key, batch_id, day, amount, payload_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                         (row["run_id"], row["model_name"], row["source_id"], row["record_key"], row["batch_id"], row["day"], row["amount"], row["payload_hash"]))
            detail_out = {"duplicated_key": row["record_key"], "source_id": row["source_id"]}
        else:
            attempt = _next_attempt(conn, run["run_id"], "transform", None)
            _add_task(conn, run["run_id"], "transform", "failed", attempt)
            conn.execute("UPDATE pipeline_runs SET status = 'failed', finished_at = %s WHERE run_id = %s", (now, run["run_id"]))
            detail_out = {"incident_id": _open_incident(conn, run["run_id"], "INJECTED_FAULT", now), "failed_task": "transform", "attempt": attempt}
    conn.execute("INSERT INTO fault_injections (fault_id, fault_type, target_id, injected_by, injected_at, armed, note) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                 (fid, i.fault_type, i.target_id, actor.actor_id, now, armed, note))
    return Outcome("injected", {"fault_id": fid, "fault_type": i.fault_type, "target_id": i.target_id, "sandbox": True, "armed": armed, "injected_at": iso_z(now), **detail_out},
                   warnings=[_warning("SANDBOX_FAULT", "a controlled fault was injected into the synthetic sandbox and recorded", "result.fault_id")],
                   audit=Audit("fault", fid, "inject-fault", reason=note, details={"fault_type": i.fault_type, "target_id": i.target_id, "sandbox": True, **detail_out}))


# --- C08 request-backfill -------------------------------------------------------------------------------------------

def _next_backfill_id(conn: Conn) -> str:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('backfill-id', 0))")
    used = [r["id"] for r in conn.execute("SELECT backfill_id AS id FROM backfill_requests UNION SELECT id FROM rejected_records WHERE entity = 'backfill_requests'").fetchall()]
    nums = [int(x[3:]) for x in used if x.startswith("bf-") and x[3:].isdigit()]
    return f"bf-{max(nums, default=0) + 1:03d}"


def request_backfill(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """range -> scheduled partitions. The range is half-open [start_at, end_at) over daily UTC partitions; an earlier accepted request of the same
    source whose range overlaps it refuses this one with BACKFILL_OVERLAP (a range that only TOUCHES, end = start, is accepted). The refusal is
    kept in rejected_records and the audit trail. Concurrent requests for one source serialise on the source row (P08-FLOW-08, P08-TEST-02)."""
    i = req.input
    _lock_source(conn, i.source_id)
    try:
        parts = check_range(i.start_at, i.end_at)
    except DomainError as err:
        raise from_domain(err, "input.start_at") from None
    start, end = parse_ts(i.start_at), parse_ts(i.end_at)
    existing = conn.execute("SELECT backfill_id, source_id, start_at, end_at FROM backfill_requests WHERE source_id = %s ORDER BY backfill_id COLLATE \"C\"", (i.source_id,)).fetchall()
    bid = _next_backfill_id(conn)
    other = find_overlap(existing, {"source_id": i.source_id, "start_at": start, "end_at": end})
    if other is not None:
        raw = {"backfill_id": bid, "source_id": i.source_id, "start_at": iso_z(start), "end_at": iso_z(end), "status": "requested",
               "partitions": [{"partition": p, "verified": False} for p in parts]}
        with db.autocommit() as c:
            c.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row, ordinal) VALUES ('api', 'backfill_requests', %s, 'BACKFILL_OVERLAP', %s, 0) ON CONFLICT DO NOTHING", (bid, Jsonb(raw)))
        _refusal(actor, req, "request-backfill", "backfill", bid, "BACKFILL_OVERLAP", f"overlaps {other['backfill_id']}", {"conflicts_with": other["backfill_id"], "source_id": i.source_id})
        raise _conflict("BACKFILL_OVERLAP", f"[{iso_z(start)}, {iso_z(end)}) overlaps {other['backfill_id']} [{iso_z(other['start_at'])}, {iso_z(other['end_at'])}) of the same source",
                        "input.start_at", {"conflicts_with": other["backfill_id"], "refused_id": bid}, rule_id="BACKFILL_OVERLAP")
    conn.execute("INSERT INTO backfill_requests (backfill_id, source_id, start_at, end_at, status, partitions, requested_by) VALUES (%s,%s,%s,%s,'scheduled',%s,%s)",
                 (bid, i.source_id, start, end, Jsonb([{"partition": p, "verified": False} for p in parts]), actor.actor_id))
    return Outcome("scheduled", {"backfill_id": bid, "source_id": i.source_id, "start_at": iso_z(start), "end_at": iso_z(end), "partitions": parts, "requested_partitions": len(parts),
                                 "range": "half-open [start_at, end_at)"},
                   audit=Audit("backfill", bid, "request-backfill", details={"source_id": i.source_id, "partitions": len(parts)}))


# --- C09 recover-incident -------------------------------------------------------------------------------------------

def recover_incident(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """failed run -> verified recovered. The incident closes only after a VERIFIED recovery: the first later run that succeeded, passed its gate,
    published, and whose publication reconciles to residual 0.00. closed_at is the verified instant (that publication's published_at), the
    recovery time is verified - detection (P08-FLOW-09, P08-MET-10)."""
    i = req.input
    now = _now()
    inc = conn.execute("SELECT * FROM incidents WHERE incident_id = %s FOR UPDATE", (i.incident_id,)).fetchone()
    if inc is None:
        raise _not_found("input.incident_id", "UNKNOWN_INCIDENT", "incident")
    if inc["status"] != "open":
        raise _conflict("INCIDENT_NOT_OPEN", f"incident {inc['incident_id']!r} is already {inc['status']}", "input.incident_id")
    golden = compute(db.load_rows(conn), db.load_rejected(conn), db.load_params(conn, iso_z(now)))
    got = golden["metrics"]["incidents"]["incidents"][inc["incident_id"]]
    if not got["verified"]:
        later = [r for r in golden["metrics"]["runs"]["runs"].items()]
        unreconciled = sorted(pid for pid, rc in golden["metrics"]["reconciliation"].items() if rc["residual"] != "0.00"
                              and parse_ts(golden["metrics"]["publications"]["publications"][pid]["published_at"]) >= inc["opened_at"])
        rule = "RESIDUAL_NOT_ZERO" if unreconciled else "RECOVERY_NOT_VERIFIED"
        raise _invalid(rule, "no later run succeeded, passed its gate, published and reconciled to 0.00" if not unreconciled
                       else f"the reconciliation residual of {', '.join(unreconciled)} is not 0.00", "input.incident_id",
                       {"unreconciled_publications": unreconciled, "runs_seen": len(later)})
    if i.recovery_run_id is not None and i.recovery_run_id != got["recovery_run_id"]:
        raise _invalid("RECOVERY_RUN_MISMATCH", f"the verified recovery is run {got['recovery_run_id']!r}", "input.recovery_run_id", {"verified_run_id": got["recovery_run_id"]})
    verified_at = parse_ts(got["verified_at"])
    conn.execute("UPDATE incidents SET status = 'closed', closed_at = %s, recovery_run_id = %s WHERE incident_id = %s", (verified_at, got["recovery_run_id"], inc["incident_id"]))
    return Outcome("recovered", {"incident_id": inc["incident_id"], "status": "closed", "detected_at": iso_z(inc["opened_at"]), "recovery_run_id": got["recovery_run_id"],
                                 "verified_at": got["verified_at"], "closed_at": got["verified_at"], "recovery_seconds": got["recovery_seconds"],
                                 "recovery_minutes": got["recovery_minutes"]},
                   audit=Audit("incident", inc["incident_id"], "recover-incident", details={"recovery_run_id": got["recovery_run_id"], "recovery_seconds": got["recovery_seconds"]}))


# --- C10 archive-evidence (extension) -------------------------------------------------------------------------------

def archive_evidence(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """completed run -> release evidence: a manifest of the run, its tasks, quality results, gate decision, publication and incidents, each with
    a sha256, the manifest's own sha256 and the retention mapping (P08-FLOW-10). A run is completed when it has finished."""
    i = req.input
    now = _now()
    run = _lock_run(conn, i.run_id)
    if run["finished_at"] is None:
        raise _conflict("RUN_NOT_COMPLETED", f"run {run['run_id']!r} has not finished ({run['status']})", "input.run_id", {"status": run["status"]})
    if conn.execute("SELECT 1 FROM evidence_archives WHERE run_id = %s", (run["run_id"],)).fetchone():
        raise _conflict("ALREADY_ARCHIVED", f"the evidence of run {run['run_id']!r} is already archived", "input.run_id")
    pub = conn.execute("SELECT * FROM publications WHERE run_id = %s", (run["run_id"],)).fetchone()
    parts = {
        "run": db.jsonable_row(run),
        "task_runs": [db.jsonable_row(r) for r in conn.execute("SELECT * FROM task_runs WHERE run_id = %s ORDER BY task_run_id COLLATE \"C\"", (run["run_id"],)).fetchall()],
        "quality_results": [db.jsonable_row(r) for r in conn.execute("SELECT q.* FROM quality_results q JOIN task_runs t ON t.task_run_id = q.task_run_id WHERE t.run_id = %s ORDER BY q.quality_result_id COLLATE \"C\"", (run["run_id"],)).fetchall()],
        "gate": _run_gate(conn, run["run_id"]),
        "publication": db.jsonable_row(pub) if pub else None,
        "incidents": [db.jsonable_row(r) for r in conn.execute("SELECT * FROM incidents WHERE run_id = %s OR recovery_run_id = %s ORDER BY incident_id COLLATE \"C\"", (run["run_id"], run["run_id"])).fetchall()],
    }
    parts = redact_value(parts)
    manifest = {"run_id": run["run_id"], "contract_version": 1, "archived_at": iso_z(now), "items": {k: {"sha256": sha256_hex(canonical_json(v)), "content": v} for k, v in parts.items()},
                "retention": RETENTION}
    mhash = sha256_hex(canonical_json(manifest))
    aid = f"ev-{_suffix(run['run_id'])}"
    conn.execute("INSERT INTO evidence_archives (archive_id, run_id, created_at, created_by, manifest, manifest_hash, retention) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                 (aid, run["run_id"], now, actor.actor_id, Jsonb(manifest), mhash, Jsonb(RETENTION)))
    return Outcome("archived", {"archive_id": aid, "run_id": run["run_id"], "manifest_hash": mhash, "item_hashes": {k: v["sha256"] for k, v in manifest["items"].items()},
                                "retention": RETENTION, "created_at": iso_z(now)},
                   audit=Audit("archive", aid, "archive-evidence", details={"run_id": run["run_id"], "manifest_hash": mhash}))
