"""Commands C01..C06, C08, C09, P (docs/api-contract.md, docs/contracts.md D-01..D-05).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit
together or not at all. Input is validated (pydantic, then domain rules) before the first write. The same
``idempotency_key`` with the same payload returns the stored response; with a different payload it is a 409.

Additions beyond the route table, needed to drive the state machine through the API: ``accept-document``
(a reviewer accepts the latest submitted version of a document type) and ``reopen-case`` (always refused).
C07 reassign-work and C10 migrate-workflow answer 501 NOT_IMPLEMENTED (extension milestone).
"""
from __future__ import annotations

import hashlib
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import psycopg
from onboard_studio import DomainError, workflow
from onboard_studio import calendar as cal
from onboard_studio.errors import CASE_ALREADY_COMPLETE, DECISION_CONFLICT, WORKFLOW_VERSION_NOT_PUBLISHED
from onboard_studio.metrics import FLAG_PAUSE_OUTSIDE_WORKING
from onboard_studio.timeutil import iso_z, parse_ts
from psycopg.types.json import Jsonb

from data.seed import canonical_json, sha256_hex

from . import db
from .errors import ApiError, detail, from_domain
from .schemas import Envelope

Conn = psycopg.Connection[db.Row]
ROLES = frozenset({"ops", "reviewer", "admin"})


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
    version: int
    warnings: list[dict[str, Any]] = field(default_factory=list)
    audit: Audit | None = None


Handler = Callable[[Conn, Any, Actor], Outcome]


def _warning(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path}


def _not_found(path: str, rule_id: str, what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found", [detail(path, rule_id, f"{what} not found")])


def _conflict(code: str, message: str, path: str) -> ApiError:
    return ApiError(409, code, message, [detail(path, code, message)])


def _invalid(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    item = detail(path, code, message)
    if context:
        item["context"] = context
    return ApiError(422, "VALIDATION_FAILED", message, [item])


def _forbidden(code: str, message: str, path: str) -> ApiError:
    return ApiError(403, code, message, [detail(path, code, message)])


def _at(inp: Any, name: str = "occurred_at") -> datetime:
    value = getattr(inp, name, None)
    return parse_ts(value) if value else datetime.now(timezone.utc)


# --- idempotent execution ---------------------------------------------------------

_INSTANT_FIELDS = ("occurred_at", "starts_at", "ends_at")


def _normalise_instants(value: dict[str, Any]) -> dict[str, Any]:
    """Q-06: an instant is hashed as the UTC instant it names, re-serialised with Z, so ``+00:00``, ``Z`` and
    ``+01:00`` spellings of the same instant are the same payload."""
    out = dict(value)
    for name in _INSTANT_FIELDS:
        if isinstance(out.get(name), str):
            out[name] = iso_z(parse_ts(out[name]))
    return out


def _payload_hash(name: str, req: Envelope) -> str:
    """sha256 over the canonical command name + input (request_id and key excluded; instants normalised)."""
    try:
        body = _normalise_instants(req.input.model_dump())  # type: ignore[attr-defined]
        text = canonical_json({"command": name, "input": body})
    except ValueError:  # NaN / Infinity are not JSON
        raise _invalid("JSON_NON_FINITE", "input contains a non-finite number", "input") from None
    if "\\u0000" in text:
        raise _invalid("NUL_CHARACTER", "input contains a NUL character", "input")
    return sha256_hex(text)


_UNIQUE_CODES = {
    "approvals_step_instance_id_version_number_key": (DECISION_CONFLICT, "a decision already exists for this step version"),
    "cases_pkey": ("CASE_EXISTS", "a case with this id already exists"),
    "workflow_versions_template_id_version_number_key": ("VERSION_EXISTS", "this template version number exists"),
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
    raise _conflict("CONCURRENT_UPDATE", f"the command lost a concurrent update {MAX_ATTEMPTS} times; retry it",
                    "input")


def _execute_once(name: str, req: Envelope, actor: Actor, handler: Handler,
                  payload_hash: str) -> tuple[dict[str, Any], bool]:
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (req.idempotency_key,))
        prior = conn.execute("SELECT payload_hash, actor_id, result FROM command_results "
                             "WHERE idempotency_key = %s", (req.idempotency_key,)).fetchone()
        if prior is not None:
            if prior["actor_id"] is not None and prior["actor_id"] != actor.actor_id:  # Q-06: bound to the actor
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED",
                               "this idempotency_key was used by a different actor",
                               [detail("idempotency_key", "IDEMPOTENCY_ACTOR_MISMATCH",
                                       "same key, different X-Actor-Id")])
            if prior["payload_hash"] != payload_hash:
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED",
                               "this idempotency_key was used with a different payload",
                               [detail("idempotency_key", "IDEMPOTENCY_PAYLOAD_MISMATCH",
                                       "same key, different payload_hash")])
            return prior["result"], True
        try:
            out = handler(conn, req, actor)
        except psycopg.errors.UniqueViolation as exc:
            code, message = _UNIQUE_CODES.get(exc.diag.constraint_name or "",
                                              ("ALREADY_EXISTS", "a row with this key already exists"))
            raise _conflict(code, message, "input") from None
        except psycopg.errors.IntegrityError as exc:  # triggers: published definitions, reopening, append-only
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


# --- shared lookups ----------------------------------------------------------------

def _case(conn: Conn, case_id: str, path: str = "input.case_id") -> db.Row:
    row = conn.execute("SELECT * FROM cases WHERE case_id = %s FOR UPDATE", (case_id,)).fetchone()
    if row is None:
        raise _not_found(path, "CASE_UNKNOWN", "case")
    return row


def _require_open(case: db.Row) -> None:
    if case["status"] == "completed":
        raise _conflict(CASE_ALREADY_COMPLETE, "the case is complete; a completed case cannot change or reopen",
                        "input.case_id")


def _bump(conn: Conn, case_id: str) -> int:
    return conn.execute("UPDATE cases SET version = version + 1 WHERE case_id = %s RETURNING version",
                        (case_id,)).fetchone()["version"]


def _event(conn: Conn, case_id: str, event_type: str, actor_id: str, at: datetime) -> None:
    conn.execute("INSERT INTO case_events (event_id, case_id, event_type, actor_id, occurred_at) "
                 "VALUES (%s, %s, %s, %s, %s)", (f"ev-{uuid.uuid4().hex[:16]}", case_id, event_type, actor_id, at))


def _step(conn: Conn, step_instance_id: str, path: str = "input.step_instance_id") -> db.Row:
    row = conn.execute(
        "SELECT si.*, sd.role_key, sd.workflow_version_id FROM step_instances si "
        "JOIN step_definitions sd ON sd.step_definition_id = si.step_definition_id "
        "WHERE si.step_instance_id = %s FOR UPDATE OF si", (step_instance_id,)).fetchone()
    if row is None:
        raise _not_found(path, "STEP_INSTANCE_UNKNOWN", "step instance")
    return row


def _step_and_case(conn: Conn, step_instance_id: str) -> tuple[db.Row, db.Row]:
    """D-08: lock the case FIRST, then the step instance, like every other command. The step's case id never
    changes, so it is read without a lock to know which case to lock."""
    owner = conn.execute("SELECT case_id FROM step_instances WHERE step_instance_id = %s",
                         (step_instance_id,)).fetchone()
    if owner is None:
        raise _not_found("input.step_instance_id", "STEP_INSTANCE_UNKNOWN", "step instance")
    case = _case(conn, owner["case_id"])
    return _step(conn, step_instance_id), case


def _step_of_case(conn: Conn, step_instance_id: str, case_id: str) -> db.Row:
    step = _step(conn, step_instance_id)
    if step["case_id"] != case_id:
        raise _invalid("STEP_NOT_IN_CASE", "the step instance belongs to another case", "input.step_instance_id")
    return step


def _latest_doc(conn: Conn, case_id: str, document_type: str) -> db.Row | None:
    """Latest version of a document type with its effective status (the latest review, else the inserted one)."""
    return conn.execute(
        "SELECT dv.*, COALESCE((SELECT r.decision FROM document_reviews r "
        "WHERE r.document_version_id = dv.document_version_id ORDER BY r.decided_at DESC, r.review_id DESC LIMIT 1), "
        "dv.review_status) AS effective_status FROM document_versions dv "
        "WHERE dv.case_id = %s AND dv.document_type = %s ORDER BY dv.version_number DESC LIMIT 1",
        (case_id, document_type)).fetchone()


def _set_step(conn: Conn, step_instance_id: str, status: str, **cols: Any) -> None:
    sets = ", ".join(f"{k} = %s" for k in ("status", *cols))  # column names are call-site constants
    conn.execute(f"UPDATE step_instances SET {sets} WHERE step_instance_id = %s",
                 (status, *cols.values(), step_instance_id))


def _require_reviewer(actor: Actor) -> None:
    if actor.role not in ("reviewer", "admin"):
        raise _forbidden("ROLE_FORBIDDEN", "only a reviewer or admin may review documents", "header.X-Actor-Role")


def _domain(fn: Callable[[], Any], path: str) -> Any:
    try:
        return fn()
    except DomainError as err:
        raise from_domain(err, path) from None


# --- C01 create-case ---------------------------------------------------------------

def create_case(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    at = _at(inp)
    if conn.execute("SELECT 1 FROM organizations WHERE organization_id = %s", (inp.organization_id,)).fetchone() is None:
        raise _not_found("input.organization_id", "ORGANIZATION_UNKNOWN", "organization")
    wv = conn.execute("SELECT * FROM workflow_versions WHERE workflow_version_id = %s",
                      (inp.workflow_version_id,)).fetchone()
    if wv is None:
        raise _not_found("input.workflow_version_id", "WORKFLOW_VERSION_UNKNOWN", "workflow version")
    if wv["published_at"] is None or wv["published_at"] > at:
        raise _invalid(WORKFLOW_VERSION_NOT_PUBLISHED, "a case binds a published workflow version",
                       "input.workflow_version_id")
    if inp.corrects_case_id is not None:
        target = conn.execute("SELECT status FROM cases WHERE case_id = %s", (inp.corrects_case_id,)).fetchone()
        if target is None:
            raise _not_found("input.corrects_case_id", "CASE_UNKNOWN", "case to correct")
        if target["status"] != "completed":
            raise _invalid("CORRECTION_TARGET_NOT_COMPLETED", "only a completed case is corrected by a new case",
                           "input.corrects_case_id")
    steps = conn.execute("SELECT * FROM step_definitions WHERE workflow_version_id = %s ORDER BY sequence",
                         (inp.workflow_version_id,)).fetchall()
    known = {s["step_definition_id"] for s in steps}
    for sd in inp.assignments:
        if sd not in known:
            raise _invalid("STEP_DEFINITION_UNKNOWN", f"{sd!r} is not a step of this workflow version",
                           f"input.assignments.{sd}")
    deps = conn.execute("SELECT * FROM dependencies WHERE step_definition_id = ANY(%s)", (list(known),)).fetchall()
    conn.execute("INSERT INTO cases (case_id, organization_id, workflow_version_id, status, opened_at, linked_case_id) "
                 "VALUES (%s, %s, %s, 'open', %s, %s)",
                 (inp.case_id, inp.organization_id, inp.workflow_version_id, at, inp.corrects_case_id))
    created = []
    for s in steps:
        ready = not workflow.mandatory_prerequisites(s["step_definition_id"], deps)
        sid = f"{inp.case_id}:{s['step_definition_id']}"
        conn.execute("INSERT INTO step_instances (step_instance_id, case_id, step_definition_id, status, "
                     "version_number, ready_at) VALUES (%s, %s, %s, %s, 1, %s)",
                     (sid, inp.case_id, s["step_definition_id"], "ready" if ready else "blocked", at if ready else None))
        created.append({"step_instance_id": sid, "step_definition_id": s["step_definition_id"],
                        "status": "ready" if ready else "blocked"})
        if s["step_definition_id"] in inp.assignments:
            conn.execute("INSERT INTO assignments (assignment_id, step_instance_id, assignee_id, assigned_at) "
                         "VALUES (%s, %s, %s, %s)", (f"asg-{uuid.uuid4().hex[:12]}", sid,
                                                     inp.assignments[s["step_definition_id"]], at))
    _event(conn, inp.case_id, "case_opened", actor.actor_id, at)
    return Outcome("created", {"case_id": inp.case_id, "workflow_version_id": inp.workflow_version_id,
                               "opened_at": iso_z(at), "steps": created}, 1,
                   audit=Audit("case", inp.case_id, "create-case", None, 1))


# --- C02 submit-document / C04 resubmit-document ------------------------------------

def _placeholder_hash(case_id: str, document_type: str, number: int) -> str:
    return "sha256:" + hashlib.sha256(f"placeholder:{case_id}:{document_type}:{number}".encode()).hexdigest()


def _insert_document(conn: Conn, inp: Any, actor: Actor, at: datetime, number: int) -> str:
    doc_id = f"{inp.case_id}:{inp.document_type}:v{number}"
    conn.execute("INSERT INTO document_versions (document_version_id, case_id, document_type, version_number, "
                 "content_hash, review_status, submitted_at) VALUES (%s, %s, %s, %s, %s, 'submitted', %s)",
                 (doc_id, inp.case_id, inp.document_type, number,
                  inp.content_hash or _placeholder_hash(inp.case_id, inp.document_type, number), at))
    _event(conn, inp.case_id, "document_submitted", actor.actor_id, at)
    return doc_id


def submit_document(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    at = _at(inp)
    case = _case(conn, inp.case_id)
    _require_open(case)
    if _latest_doc(conn, inp.case_id, inp.document_type) is not None:
        raise _invalid("DOCUMENT_ALREADY_SUBMITTED",
                       "a version of this document type exists; use resubmit-document after a rejection",
                       "input.document_type")
    step_status = None
    if inp.step_instance_id:
        step = _step_of_case(conn, inp.step_instance_id, inp.case_id)
        _domain(lambda: workflow.require_transition(step["status"], "in_review"), "input.step_instance_id")
        _set_step(conn, step["step_instance_id"], "in_review", started_at=step["started_at"] or at)
        step_status = "in_review"
    doc_id = _insert_document(conn, inp, actor, at, 1)
    version = _bump(conn, inp.case_id)
    return Outcome("submitted", {"document_version_id": doc_id, "version_number": 1, "step_status": step_status},
                   version, audit=Audit("document", doc_id, "submit-document", version - 1, version))


def resubmit_document(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    at = _at(inp)
    case = _case(conn, inp.case_id)
    _require_open(case)
    prior = _latest_doc(conn, inp.case_id, inp.document_type)
    if prior is None:
        raise _not_found("input.document_type", "DOCUMENT_UNKNOWN", "document")
    if prior["effective_status"] != "rejected":
        raise _invalid("NOT_IN_CHANGES_REQUESTED", "only a rejected submission can be resubmitted",
                       "input.document_type")
    step_status = None
    if inp.step_instance_id:
        step = _step_of_case(conn, inp.step_instance_id, inp.case_id)
        _domain(lambda: workflow.require_transition(step["status"], "ready"), "input.step_instance_id")
        _set_step(conn, step["step_instance_id"], "in_review", ready_at=at)  # changes_requested -> ready -> in_review
        step_status = "in_review"
    number = prior["version_number"] + 1
    doc_id = _insert_document(conn, inp, actor, at, number)
    version = _bump(conn, inp.case_id)
    return Outcome("submitted", {"document_version_id": doc_id, "version_number": number,
                                 "prior_document_version_id": prior["document_version_id"],
                                 "step_status": step_status},
                   version, audit=Audit("document", doc_id, "resubmit-document", version - 1, version))


# --- C03 reject-submission / accept-document ----------------------------------------

def reject_submission(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    _require_reviewer(actor)
    at = _at(inp)
    case = _case(conn, inp.case_id)
    _require_open(case)
    doc = _latest_doc(conn, inp.case_id, inp.document_type)
    if doc is None:
        raise _not_found("input.document_type", "DOCUMENT_UNKNOWN", "document")
    if doc["effective_status"] != "submitted":
        raise _invalid("DOCUMENT_NOT_SUBMITTED", "only a submitted version can be rejected", "input.document_type")
    step_version = None
    if inp.step_instance_id:
        step = _step_of_case(conn, inp.step_instance_id, inp.case_id)
        _domain(lambda: workflow.require_transition(step["status"], "changes_requested"), "input.step_instance_id")
        step_version = step["version_number"] + 1  # a new step version: the next decision carries it
        _set_step(conn, step["step_instance_id"], "changes_requested", version_number=step_version)
    conn.execute("INSERT INTO document_reviews (review_id, document_version_id, decision, reason, reviewer_id, "
                 "decided_at) VALUES (%s, %s, 'rejected', %s, %s, %s)",
                 (f"rev-{uuid.uuid4().hex[:16]}", doc["document_version_id"], inp.reason, actor.actor_id, at))
    _event(conn, inp.case_id, "document_rejected", actor.actor_id, at)
    version = _bump(conn, inp.case_id)
    return Outcome("changes_requested", {"document_version_id": doc["document_version_id"],
                                         "step_version_number": step_version}, version,
                   audit=Audit("document", doc["document_version_id"], "reject-submission", version - 1, version,
                               inp.reason))


def accept_document(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    _require_reviewer(actor)
    at = _at(inp)
    case = _case(conn, inp.case_id)
    _require_open(case)
    doc = _latest_doc(conn, inp.case_id, inp.document_type)
    if doc is None:
        raise _not_found("input.document_type", "DOCUMENT_UNKNOWN", "document")
    if doc["effective_status"] != "submitted":
        raise _invalid("DOCUMENT_NOT_SUBMITTED", "only a submitted version can be accepted", "input.document_type")
    conn.execute("INSERT INTO document_reviews (review_id, document_version_id, decision, reviewer_id, decided_at) "
                 "VALUES (%s, %s, 'accepted', %s, %s)",
                 (f"rev-{uuid.uuid4().hex[:16]}", doc["document_version_id"], actor.actor_id, at))
    _event(conn, inp.case_id, "document_accepted", actor.actor_id, at)
    version = _bump(conn, inp.case_id)
    return Outcome("accepted", {"document_version_id": doc["document_version_id"]}, version,
                   audit=Audit("document", doc["document_version_id"], "accept-document", version - 1, version))


# --- C05 unlock-dependent-step -------------------------------------------------------

def unlock_step(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    at = _at(inp)
    step, case = _step_and_case(conn, inp.step_instance_id)
    _require_open(case)
    if inp.expected_version is not None and inp.expected_version != step["version_number"]:
        raise _conflict("STALE_VERSION", f"the step is at version {step['version_number']}", "input.expected_version")
    if step["status"] != "blocked":
        raise _invalid("STEP_NOT_BLOCKED", "only a blocked step can be unlocked", "input.step_instance_id")
    statuses = {r["step_definition_id"]: r["status"] for r in conn.execute(
        "SELECT step_definition_id, status FROM step_instances WHERE case_id = %s", (step["case_id"],)).fetchall()}
    deps = conn.execute("SELECT * FROM dependencies WHERE step_definition_id = %s",
                        (step["step_definition_id"],)).fetchall()
    _domain(lambda: workflow.require_unlockable(step["step_definition_id"], deps, statuses), "input.step_instance_id")
    _set_step(conn, step["step_instance_id"], "ready", ready_at=at)
    version = _bump(conn, step["case_id"])
    return Outcome("ready", {"step_instance_id": step["step_instance_id"], "ready_at": iso_z(at)}, version,
                   audit=Audit("step_instance", step["step_instance_id"], "unlock-dependent-step",
                               version - 1, version))


# --- C06 approve-step ----------------------------------------------------------------

def approve_step(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    at = _at(inp)
    step, case = _step_and_case(conn, inp.step_instance_id)
    _require_open(case)
    assignees = [r["assignee_id"] for r in conn.execute(
        "SELECT assignee_id FROM assignments WHERE step_instance_id = %s", (step["step_instance_id"],)).fetchall()]
    _domain(lambda: workflow.check_approval(actor.actor_id, actor.role, step["role_key"], assignees),
            "input.step_instance_id")

    def decided(version: int) -> bool:
        return conn.execute("SELECT 1 FROM approvals WHERE step_instance_id = %s AND version_number = %s",
                            (step["step_instance_id"], version)).fetchone() is not None

    if inp.expected_version != step["version_number"]:
        if decided(inp.expected_version):
            raise _conflict(DECISION_CONFLICT, "a decision was already made on that step version",
                            "input.expected_version")
        raise _conflict("STALE_VERSION", f"the step is at version {step['version_number']}",
                        "input.expected_version")
    if decided(step["version_number"]):
        raise _conflict(DECISION_CONFLICT, "a decision was already made on this step version",
                        "input.step_instance_id")
    if step["status"] != "in_review":
        raise _invalid("STEP_NOT_IN_REVIEW", "only a step in review can be approved", "input.step_instance_id")
    approval_id = f"apr-{uuid.uuid4().hex[:16]}"
    conn.execute("INSERT INTO approvals (approval_id, step_instance_id, reviewer_id, decision, decided_at, reason, "
                 "version_number) VALUES (%s, %s, %s, 'approved', %s, %s, %s)",
                 (approval_id, step["step_instance_id"], actor.actor_id, at, inp.reason, step["version_number"]))
    _set_step(conn, step["step_instance_id"], "approved", approved_at=at)
    _event(conn, step["case_id"], "step_approved", actor.actor_id, at)
    version = _bump(conn, step["case_id"])
    return Outcome("approved", {"approval_id": approval_id, "step_instance_id": step["step_instance_id"],
                                "version_number": step["version_number"]}, version,
                   audit=Audit("step_instance", step["step_instance_id"], "approve-step", version - 1, version,
                               inp.reason))


# --- C08 pause-sla -------------------------------------------------------------------

def _calendar(conn: Conn, calendar_id: str) -> list[cal.Interval]:
    rows = conn.execute("SELECT starts_at, ends_at, kind FROM calendar_intervals WHERE calendar_id = %s",
                        (calendar_id,)).fetchall()
    return cal.effective_intervals([(r["starts_at"], r["ends_at"]) for r in rows if r["kind"] == "working"],
                                   [(r["starts_at"], r["ends_at"]) for r in rows if r["kind"] == "holiday"])


def _require_inside_case_span(case: db.Row, start: datetime, end: datetime | None) -> None:
    """D-07 / Q-01: a pause lies inside the case span [opened_at, completed_at). An open case has no upper bound
    (completion later closes or refuses what is open); a completed case never gets here (409 CASE_ALREADY_COMPLETE)."""
    done = case["completed_at"]
    if start < case["opened_at"] or (done is not None and (start >= done or (end is not None and end > done))):
        raise _invalid("PAUSE_OUTSIDE_CASE_SPAN", "a pause must lie inside the case span (after it opened, "
                       "before it completed)", "input.starts_at",
                       {"opened_at": iso_z(case["opened_at"]), "completed_at": iso_z(done)})


def pause_sla(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    at = _at(inp)
    case = _case(conn, inp.case_id)
    _require_open(case)
    rule = conn.execute("SELECT * FROM sla_rules WHERE workflow_version_id = %s", (case["workflow_version_id"],)).fetchone()
    if rule is None:
        raise _invalid("SLA_RULE_MISSING", "the case's workflow version has no SLA rule", "input.case_id")
    _domain(lambda: workflow.check_pause_reason(inp.reason_code, rule["pause_policy"]), "input.reason_code")
    start = parse_ts(inp.starts_at) if inp.starts_at else at
    end = parse_ts(inp.ends_at) if inp.ends_at else None
    if end is not None and end <= start:
        raise _invalid("INVALID_INTERVAL", "ends_at must be after starts_at", "input.ends_at")
    _require_inside_case_span(case, start, end)
    if conn.execute("SELECT 1 FROM waiting_intervals WHERE case_id = %s AND ends_at IS NULL",
                    (inp.case_id,)).fetchone():
        raise _conflict("ALREADY_PAUSED", "the case already has an open waiting interval", "input.case_id")
    wid = f"wi-{uuid.uuid4().hex[:16]}"
    conn.execute("INSERT INTO waiting_intervals (waiting_interval_id, case_id, reason_code, starts_at, ends_at) "
                 "VALUES (%s, %s, %s, %s, %s)", (wid, inp.case_id, inp.reason_code, start, end))
    _event(conn, inp.case_id, "waiting_started", actor.actor_id, start)
    warnings: list[dict[str, Any]] = []
    if end is not None:
        _event(conn, inp.case_id, "waiting_ended", actor.actor_id, end)
        if cal.overlap_seconds(start, end, _calendar(conn, rule["calendar_id"])) == 0:
            warnings.append(_warning(FLAG_PAUSE_OUTSIDE_WORKING,
                                     "the pause lies outside every working interval and contributes 0 business hours",
                                     f"waiting_intervals[{wid}]"))
    version = _bump(conn, inp.case_id)
    return Outcome("waiting_external", {"waiting_interval_id": wid, "reason_code": inp.reason_code,
                                        "starts_at": iso_z(start), "ends_at": iso_z(end)}, version, warnings,
                   Audit("case", inp.case_id, "pause-sla", version - 1, version, inp.reason_code))


# --- C09 complete-case ---------------------------------------------------------------

def complete_case(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    at = _at(inp)
    case = _case(conn, inp.case_id)
    _require_open(case)
    if inp.expected_version is not None and inp.expected_version != case["version"]:
        raise _conflict("STALE_VERSION", f"the case is at version {case['version']}", "input.expected_version")
    if at < case["opened_at"]:
        raise _invalid("INVALID_TIMESTAMP", "completed_at cannot precede opened_at", "input.occurred_at")
    latest = _latest_recorded(conn, inp.case_id)
    if latest is not None and at < latest:  # D-07: never complete before work already recorded on the case
        raise _invalid("COMPLETION_BEFORE_RECORDED_WORK",
                       "a case cannot complete before the latest recorded event, approval, document review, "
                       "assignment end or waiting interval on it", "input.occurred_at",
                       {"latest_recorded_at": iso_z(latest), "occurred_at": iso_z(at)})
    required = {r["step_definition_id"]: r["status"] or "missing" for r in conn.execute(
        "SELECT sd.step_definition_id, si.status FROM step_definitions sd "
        "LEFT JOIN step_instances si ON si.step_definition_id = sd.step_definition_id AND si.case_id = %s "
        "WHERE sd.workflow_version_id = %s AND sd.required", (inp.case_id, case["workflow_version_id"])).fetchall()}
    types = [r["document_type"] for r in conn.execute(
        "SELECT document_type FROM workflow_requirements WHERE workflow_version_id = %s",
        (case["workflow_version_id"],)).fetchall()]
    accepted = [t for t in types if _latest_accepted(conn, inp.case_id, t)]
    _domain(lambda: workflow.require_completable(required, types, accepted), "input.case_id")
    # D-07: open waiting is closed at the completion instant. None can start after it (the ordering check above).
    conn.execute("UPDATE waiting_intervals SET ends_at = %s WHERE case_id = %s AND ends_at IS NULL",
                 (at, inp.case_id))
    conn.execute("UPDATE cases SET status = 'completed', completed_at = %s, version = version + 1 "
                 "WHERE case_id = %s", (at, inp.case_id))
    _event(conn, inp.case_id, "case_completed", actor.actor_id, at)
    version = case["version"] + 1
    return Outcome("completed", {"case_id": inp.case_id, "completed_at": iso_z(at)}, version,
                   audit=Audit("case", inp.case_id, "complete-case", case["version"], version))


def _latest_accepted(conn: Conn, case_id: str, document_type: str) -> bool:
    """D-06 / Q-04: True when the LATEST version of the type has the effective status accepted (the latest review
    of that version, else the status it was inserted with). v1 accepted + v2 rejected or submitted is False."""
    doc = _latest_doc(conn, case_id, document_type)
    return doc is not None and doc["effective_status"] == "accepted"


def _latest_recorded(conn: Conn, case_id: str) -> datetime | None:
    """The latest instant of work recorded on the case: events, approvals, document reviews, assignment ends and
    waiting intervals (starts and ends). ``GREATEST`` ignores the NULL of an empty table."""
    return conn.execute(
        "SELECT GREATEST("
        " (SELECT max(occurred_at) FROM case_events WHERE case_id = %(c)s),"
        " (SELECT max(a.decided_at) FROM approvals a JOIN step_instances si ON si.step_instance_id = a.step_instance_id"
        "   WHERE si.case_id = %(c)s),"
        " (SELECT max(r.decided_at) FROM document_reviews r JOIN document_versions d"
        "   ON d.document_version_id = r.document_version_id WHERE d.case_id = %(c)s),"
        " (SELECT max(g.ended_at) FROM assignments g JOIN step_instances si ON si.step_instance_id = g.step_instance_id"
        "   WHERE si.case_id = %(c)s),"
        " (SELECT max(GREATEST(w.starts_at, w.ends_at)) FROM waiting_intervals w WHERE w.case_id = %(c)s)"
        ") AS latest", {"c": case_id}).fetchone()["latest"]


# --- P publish-workflow-version ------------------------------------------------------

def publish_workflow_version(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    if actor.role != "admin":
        raise _forbidden("ROLE_FORBIDDEN", "only an admin publishes a workflow version", "header.X-Actor-Role")
    at = _at(inp)
    wv = conn.execute("SELECT * FROM workflow_versions WHERE workflow_version_id = %s FOR UPDATE",
                      (inp.workflow_version_id,)).fetchone()
    if wv is not None and wv["published_at"] is not None:
        raise _conflict("ALREADY_PUBLISHED", "a published workflow version is immutable", "input.workflow_version_id")
    if wv is None:
        if not inp.steps:
            raise _invalid("DEFINITION_REQUIRED", "a new version needs its steps", "input.steps")
        ids = [s.step_definition_id for s in inp.steps]
        if len(set(ids)) != len(ids) or len({s.sequence for s in inp.steps}) != len(ids):
            raise _invalid("DUPLICATE_STEP", "step ids and sequences must be unique", "input.steps")
        steps = [s.model_dump() | {"workflow_version_id": inp.workflow_version_id} for s in inp.steps]
        deps = [d.model_dump() for d in inp.dependencies]
    else:
        steps = conn.execute("SELECT * FROM step_definitions WHERE workflow_version_id = %s", (wv["workflow_version_id"],)).fetchall()
        deps = conn.execute("SELECT * FROM dependencies WHERE step_definition_id = ANY(%s)",
                            ([s["step_definition_id"] for s in steps],)).fetchall()
    if inp.sla_rule is not None and conn.execute(
            "SELECT 1 FROM calendars WHERE calendar_id = %s", (inp.sla_rule.calendar_id,)).fetchone() is None:
        raise _invalid("CALENDAR_UNKNOWN", f"calendar {inp.sla_rule.calendar_id!r} does not exist",
                       "input.sla_rule.calendar_id")
    order = _domain(lambda: workflow.check_publishable(
        [s["step_definition_id"] for s in steps], [(d["step_definition_id"], d["prerequisite_id"]) for d in deps]),
        "input.dependencies")
    dhash = workflow.definition_hash(steps, deps)
    if wv is None:
        template = inp.template_id or f"tpl-{inp.workflow_version_id}"
        number = inp.version_number or (conn.execute(
            "SELECT COALESCE(max(version_number), 0) + 1 AS n FROM workflow_versions WHERE template_id = %s",
            (template,)).fetchone()["n"])
        conn.execute("INSERT INTO workflow_versions (workflow_version_id, template_id, version_number) "
                     "VALUES (%s, %s, %s)", (inp.workflow_version_id, template, number))
        for s in steps:
            conn.execute("INSERT INTO step_definitions (step_definition_id, workflow_version_id, step_name, required, "
                         "role_key, sequence) VALUES (%s, %s, %s, %s, %s, %s)",
                         (s["step_definition_id"], s["workflow_version_id"], s["step_name"], s["required"],
                          s["role_key"], s["sequence"]))
        for d in deps:
            conn.execute("INSERT INTO dependencies (dependency_id, step_definition_id, prerequisite_id, "
                         "dependency_type, created_at) VALUES (%s, %s, %s, %s, %s)",
                         (d["dependency_id"], d["step_definition_id"], d["prerequisite_id"], d["dependency_type"], at))
        for t in inp.required_document_types:
            conn.execute("INSERT INTO workflow_requirements (workflow_version_id, document_type) VALUES (%s, %s) "
                         "ON CONFLICT DO NOTHING", (inp.workflow_version_id, t))
        if inp.sla_rule is not None:
            conn.execute("INSERT INTO sla_rules (sla_rule_id, workflow_version_id, business_minutes, pause_policy, "
                         "calendar_id) VALUES (%s, %s, %s, %s, %s)",
                         (inp.sla_rule.sla_rule_id, inp.workflow_version_id, inp.sla_rule.business_minutes,
                          inp.sla_rule.pause_policy, inp.sla_rule.calendar_id))
    conn.execute("UPDATE workflow_versions SET published_at = %s, definition_hash = %s WHERE workflow_version_id = %s",
                 (at, dhash, inp.workflow_version_id))
    return Outcome("published", {"workflow_version_id": inp.workflow_version_id, "definition_hash": dhash,
                                 "published_at": iso_z(at), "step_order": order}, 1,
                   audit=Audit("workflow_version", inp.workflow_version_id, "publish-workflow-version", None, 1))


# --- extension commands and refused actions --------------------------------------------

def not_implemented(name: str, code: str) -> ApiError:
    return ApiError(501, "NOT_IMPLEMENTED", f"{name} ({code}) is an extension-milestone command and is not implemented",
                    [detail("command", "NOT_IMPLEMENTED", f"{name} is not implemented in this milestone")])


def reopen_case(case_id: str) -> None:
    """P02-TEST-11: a completed case cannot be reopened; a correction opens a linked new case."""
    with db.transaction() as conn:
        case = conn.execute("SELECT status FROM cases WHERE case_id = %s", (case_id,)).fetchone()
    if case is None:
        raise _not_found("input.case_id", "CASE_UNKNOWN", "case")
    if case["status"] == "completed":
        raise _conflict("CASE_REOPEN_FORBIDDEN",
                        "a completed case cannot be reopened; open a linked correction case with create-case "
                        "(corrects_case_id)", "input.case_id")
    raise _invalid("CASE_NOT_COMPLETED", "the case is not complete, so there is nothing to reopen", "input.case_id")


__all__ = ["Actor", "ROLES", "execute", "create_case", "submit_document", "resubmit_document", "reject_submission",
           "accept_document", "unlock_step", "approve_step", "pause_sla", "complete_case",
           "publish_workflow_version", "not_implemented", "reopen_case"]
