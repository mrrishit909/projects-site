"""Commands C01..C10 (docs/api-contract.md, docs/contracts.md D-01..D-05; conventions in README.md).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit together or not at all. Input is validated
(pydantic, then the domain's own rules, ALL rows before the first write) so a refused command writes nothing. The same ``idempotency_key`` with the same
payload, the same actor id and the same role returns the stored response; with a different payload, actor or role it is a 409. Instants are stamped by
the SERVER's clock; an evidence date is a plain date (``measured_on``, ``observed_on``) and may not lie in the future.

Lock order (every command, so two commands cannot deadlock on each other):
    1. the idempotency key (advisory lock)
    2. initiative rows, by id (FOR UPDATE when the command changes the initiative or must serialise on it: C01 approve, C02, C06, C10; else FOR SHARE)
    3. group rows and resource rows, by id (C05; FOR UPDATE for C06's resources)
    4. scenario rows, by id (C07 FOR UPDATE)
A deadlock or serialization failure that still happens is rolled back and retried, three attempts in all, then answered 409 CONCURRENT_UPDATE.

Roles (X-Actor-Role): analyst | sponsor | admin.  C01 create, C02-C06, C08, C09: analyst, sponsor, admin.  C01 approve, C07, C10: sponsor, admin.
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from fractions import Fraction as F
from typing import Any, Callable

import psycopg
from changeworks import Validator, compute
from changeworks.cashflow import expand_costs
from changeworks.context import Ctx
from changeworks.contract import ROLES as ROLE_LIST
from changeworks.errors import DomainError
from changeworks.ingest import Rejection
from changeworks.numbers import canon, dec, ex, m4, money
from changeworks.snapshot import snapshot_hash
from changeworks.people import adoption as adoption_metric
from changeworks.people import forecast as forecast_metric
from changeworks.people import readiness as readiness_metric
from changeworks.people import training as training_metric
from changeworks.roadmap import feasible_starts, initiative_roadmap, resource_views
from changeworks.timeutil import iso_z, matured, period_start_instant
from psycopg.types.json import Jsonb

from data.seed import canonical_json, insert_row, sha256_hex

from . import clock, db
from .errors import ApiError, detail
from .schemas import Envelope

Conn = psycopg.Connection[db.Row]
ROLES = frozenset(ROLE_LIST)
ALL_ROLES = ROLES
SPONSOR_ROLES = frozenset({"sponsor", "admin"})

#: Rejections that are conflicts with stored state (409, error.code = the code); every other rejection is a 422 VALIDATION_FAILED.
CONFLICT_CODES = frozenset({"DUPLICATE_ID", "VERSION_EXISTS", "BASELINE_FROZEN"})
MESSAGES = {
    "MALFORMED_RECORD": "a field is missing, null or of the wrong type", "DUPLICATE_ID": "a record with this id exists", "VERSION_EXISTS": "that version exists and is never overwritten",
    "UNKNOWN_INITIATIVE": "the initiative is not registered", "UNKNOWN_ASSUMPTION": "the assumption version does not exist", "UNKNOWN_GROUP": "the stakeholder group does not exist",
    "UNKNOWN_RESOURCE": "the resource does not exist", "UNKNOWN_BENEFIT": "the benefit item does not exist", "DEPENDENT_REJECTED": "a record it depends on was rejected",
    "STATUS_NOT_ALLOWED": "that status does not exist in this product (nothing here funds anything)", "RATE_PERIOD_MISMATCH": "the discount rate basis differs from the period basis "
    "and no recorded conversion is named", "ONE_TIME_COST_REPEATED": "a one-time cost appears in one period only", "BENEFIT_BEFORE_DEPLOYMENT": "a benefit cannot start before the "
    "initiative's deployment period", "CAPACITY_WITHOUT_CONVERSION": "capacity hours are not cash without a capacity_hourly_rate and a staffing change evidence reference",
    "DEPENDENCY_CYCLE": "the dependency would close a cycle", "RESOURCE_OVERALLOCATED": "the allocation would exceed the resource's capacity", "BASELINE_FROZEN": "the approved "
    "baseline is immutable; record a correction as a new version", "PROBABILITY_OUT_OF_RANGE": "a probability is a value in [0, 1]", "INVALID_SCORE": "a score is an integer 1..5",
    "INVALID_DIMENSION": "not a readiness dimension", "ADOPTED_EXCEEDS_ELIGIBLE": "adopted cannot exceed eligible", "COMPLETED_EXCEEDS_ELIGIBLE": "completed cannot exceed eligible",
    "ELIGIBILITY_RULE_MISMATCH": "the observation uses another eligibility rule than the initiative fixes", "LABEL_NOT_SYNTHETIC": "a stakeholder label must be a synthetic role or team "
    "label, not personal data", "OPERATING_CHANGE_REQUIRED": "describe the operating change", "INVALID_UNIT": "capacity is measured in hours, every other benefit in USD",
    "INVALID_RAMP": "a ramp is a non-decreasing list of fractions in [0, 1]", "RATIONALE_REQUIRED": "a rationale is required", "INVALID_PERIOD": "the period is out of range or inconsistent",
    "EVIDENCE_REQUIRED": "an evidence reference is text that says where the evidence is; blank is not evidence", "COST_KEY_BASIS_CONFLICT": "a cost key is one kind of cost "
    "(one-time or recurring) for an initiative and a basis; record a different kind of cost under a new key and say why", "INVALID_FIELD": "the field is outside its range",
}
MIN_EXPLANATION = 20       # characters of a double-count explanation (R9-22)


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


def _forbidden(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    return _err(403, "FORBIDDEN", code, message, path, context)


def _need_role(actor: Actor, allowed: frozenset[str], what: str) -> None:
    if actor.role not in allowed:
        raise _forbidden("ROLE_FORBIDDEN", f"{what} needs the role {' or '.join(sorted(allowed))}", "header.X-Actor-Role")


def _now() -> datetime:
    return clock.now()


def _domain(err: DomainError, path: str) -> ApiError:
    return _invalid(err.code, err.message, err.path or path, err.details or None)


def _rejections(items: list[tuple[str, Rejection]]) -> ApiError:
    """All rejected rows of a command as ONE refusal (nothing was written). A conflict with stored state wins (409); otherwise 422."""
    details = []
    for path, rej in items:
        d = detail(path, rej.reason_code, MESSAGES.get(rej.reason_code, "the record was rejected"))
        if rej.details:
            d["context"] = rej.details
        details.append(d)
    first = next((r for _, r in items if r.reason_code in CONFLICT_CODES), None)
    if first is not None:
        return ApiError(409, first.reason_code, MESSAGES.get(first.reason_code, "conflict with stored state"), details)
    return ApiError(422, "VALIDATION_FAILED", "the input breaks a business rule: " + ", ".join(sorted({r.reason_code for _, r in items})), details)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _plain_date(s: str, now: datetime, path: str) -> datetime:
    d = date.fromisoformat(s)
    at = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if at > now:
        raise _invalid("DATE_IN_FUTURE", f"{path} may not lie in the future (the server's date is {now.date().isoformat()})", path)
    return at


def _observed_on(s: str | None, now: datetime, path: str, ini: Any, config: dict[str, Any]) -> datetime:
    """R9-11: an observation happened between the first period start of its initiative and the server's date; without a date it happened now. Whatever it
    says, the server stamps when it was recorded."""
    if not s:
        return now
    at = _plain_date(s, now, path)
    first = period_start_instant(config, ini["requested_start_period"])
    if at < first:
        raise _invalid("OBSERVED_BEFORE_START", f"{path} {s} is before the first period start of {ini['initiative_id']} ({first.date().isoformat()})", path,
                       {"first_period_start": first.date().isoformat()})
    return at


def _ev(v: str | None) -> str | None:
    """R9-04: an evidence reference is stored stripped; a blank one is kept blank so that the domain refuses it (EVIDENCE_REQUIRED)."""
    return None if v is None else v.strip()


# --- idempotent execution ---------------------------------------------------------------------------------------

def _payload_hash(name: str, req: Envelope) -> str:
    """sha256 over the command name + dataset_version + input (request_id and key excluded). The dataset_version is part of the payload."""
    body = req.input.model_dump()  # type: ignore[attr-defined]
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
    """Run ``handler`` once per idempotency key. Returns ``(response body, replayed)``. A deadlock is retried (``MAX_ATTEMPTS`` attempts in all, short
    randomised back-off); the last failure is 409 CONCURRENT_UPDATE, never a 500."""
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
    """The request names the dataset it was prepared against; a different current version is 409 STALE_DATASET_VERSION and nothing is written. A database
    with no dataset_versions row has nothing to be stale against."""
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    if row is not None and row["dataset_version"] != req.dataset_version:
        raise ApiError(409, "STALE_DATASET_VERSION",
                       f"the request was prepared against dataset {req.dataset_version!r}; the current dataset is {row['dataset_version']!r}",
                       [{**detail("dataset_version", "STALE_DATASET_VERSION", "re-read the data and retry with the current dataset_version"),
                         "context": {"current": row["dataset_version"], "requested": req.dataset_version}}])


_UNIQUE_CODES = {
    "initiatives_pkey": ("INITIATIVE_EXISTS", "an initiative with this id exists"),
    "scenario_versions_pkey": ("DUPLICATE_ID", "a scenario version with this id exists: an edit is a new scenario_id"),
    "process_baselines_version_uq": ("VERSION_EXISTS", "that baseline version exists and is never overwritten"),
    "baseline_approvals_version_uq": ("ALREADY_APPROVED", "that baseline version is already approved"),
    "assumption_versions_version_uq": ("VERSION_EXISTS", "that assumption version exists and is never overwritten"),
    "forecast_versions_uq": ("VERSION_EXISTS", "that forecast version exists: revise it as a new version"),
    "opportunity_scores_version_uq": ("CONCURRENT_UPDATE", "another request scored this initiative first; retry"),
    "cost_items_one_time_uq": ("ONE_TIME_COST_REPEATED", "a one-time cost appears in one period only"),
    "dependencies_pair_uq": ("DUPLICATE_ID", "that dependency exists"),
}


def _execute_once(name: str, req: Envelope, actor: Actor, handler: Handler, payload_hash: str) -> tuple[dict[str, Any], bool]:
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (req.idempotency_key,))
        prior = conn.execute("SELECT payload_hash, actor_id, actor_role, result FROM command_results WHERE idempotency_key = %s", (req.idempotency_key,)).fetchone()
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
        except psycopg.errors.IntegrityError as exc:  # checks and triggers: append-only, frozen baseline, immutable scenario ...
            msg = exc.diag.message_primary or "integrity rule violated"
            rule = msg.split(":", 1)[0] if msg.split(":", 1)[0].isupper() else "INTEGRITY_RULE"
            raise _conflict("INTEGRITY_RULE", msg, "input", rule_id=rule) from None
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        for a in ([] if out.audit is None else out.audit if isinstance(out.audit, list) else [out.audit]):
            conn.execute(
                "INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, actor_role, occurred_at, before_version, after_version, "
                "reason, request_id, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (f"evt-{uuid.uuid4().hex[:16]}", a.entity_type, a.entity_id, a.action, actor.actor_id, actor.role, _now(), a.before_version,
                 a.after_version, a.reason, req.request_id, Jsonb(a.details)))
        body = {"command_id": command_id, "status": out.status, "result": out.result, "warnings": out.warnings, "version": out.version}
        conn.execute("INSERT INTO command_results (idempotency_key, payload_hash, actor_id, actor_role, command_id, status, result) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s)", (req.idempotency_key, payload_hash, actor.actor_id, actor.role, command_id, out.status, Jsonb(body)))
        return body, False


def _refusal(actor: Actor, req: Envelope, action: str, entity_type: str, entity_id: str, rule_id: str, message: str) -> None:
    """Keep a refused decision in the audit trail (its own transaction: the command's is about to roll back)."""
    with db.autocommit() as c:
        c.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, actor_role, occurred_at, reason, request_id, details) "
                  "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                  (f"evt-{uuid.uuid4().hex[:16]}", entity_type, entity_id, f"{action}-refused", actor.actor_id, actor.role, _now(), message,
                   req.request_id, Jsonb({"rule_id": rule_id})))


# --- shared lookups and locks -----------------------------------------------------------------------------------

def _lock_initiatives(conn: Conn, ids: set[str] | list[str], exclusive: bool = False, path: str = "input.initiative_id", must_exist: bool = True) -> dict[str, db.Row]:
    """Lock order step 2: initiative rows by id (FOR UPDATE or FOR SHARE). An unknown id is 404 UNKNOWN_INITIATIVE."""
    wanted = sorted(set(ids))
    rows = conn.execute(f"SELECT * FROM initiatives WHERE initiative_id = ANY(%s) ORDER BY initiative_id COLLATE \"C\" FOR {'UPDATE' if exclusive else 'SHARE'}",
                        (wanted,)).fetchall()
    found = {r["initiative_id"]: r for r in rows}
    if must_exist:
        for i in wanted:
            if i not in found:
                raise _err(404, "NOT_FOUND", "UNKNOWN_INITIATIVE", f"initiative {i!r} is not registered", path)
    return found


def _check_all(v: Validator, items: list[tuple[str, str, dict[str, Any]]]) -> list[tuple[str, Rejection]]:
    """Run ``(path, entity, row)`` through the validator IN ORDER, recording accepted rows so later rows see them; returns every rejection."""
    rejected: list[tuple[str, Rejection]] = []
    for path, entity, row in items:
        rej = v.add(entity, row)
        if rej is not None:
            rejected.append((path, rej))
    return rejected


def _insert(conn: Conn, items: list[tuple[str, str, dict[str, Any]]], actor: Actor, at: datetime | None = None) -> None:
    """Write the rows; ``at`` is the server instant they were recorded (it stamps plan rows and observations, R9-01 and R9-11)."""
    for _, entity, row in items:
        insert_row(conn, entity, row, by=actor.actor_id, at=at)


def _ctx(pop: Any, at: datetime, scenario_ids: list[str] | None = None) -> Ctx:
    return Ctx(pop, at, None, scenario_ids)


# --- C01 establish-baseline -------------------------------------------------------------------------------------

def establish_baseline(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """create: a measured baseline row (evidence only, version >= 1, a reason once an approved baseline exists). approve (sponsor, admin): that set becomes
    THE approved baseline of the initiative and every row of the version is frozen; the earlier approved version stays readable."""
    inp = req.input
    now = _now()
    if inp.action == "approve":
        if actor.role not in SPONSOR_ROLES:
            _refusal(actor, req, "establish-baseline", "initiative", inp.initiative_id, "ROLE_FORBIDDEN", "baseline approval needs a sponsor or admin")
            raise _forbidden("ROLE_FORBIDDEN", "approving a baseline needs the role admin or sponsor", "header.X-Actor-Role")
    ini = _lock_initiatives(conn, [inp.initiative_id], exclusive=True)[inp.initiative_id]
    if inp.expected_version is not None and inp.expected_version != ini["version"]:
        raise _conflict("STALE_VERSION", f"the initiative is at version {ini['version']}, not {inp.expected_version}", "input.expected_version",
                        {"current": ini["version"], "requested": inp.expected_version})
    pop = db.load_population(conn)
    if inp.action == "approve":
        base = next((b for b in pop.acc["process_baselines"] if b["initiative_id"] == inp.initiative_id and b["baseline_version"] == inp.baseline_version), None)
        if base is None:
            raise _err(404, "NOT_FOUND", "UNKNOWN_BASELINE", f"baseline {inp.baseline_version!r} of {inp.initiative_id!r} does not exist", "input.baseline_version")
        if ini["baseline_version"] == inp.baseline_version:
            raise _conflict("ALREADY_APPROVED", "this baseline version is already the approved one", "input.baseline_version")
        if any(a["initiative_id"] == inp.initiative_id and a["baseline_version"] == inp.baseline_version for a in pop.approvals):
            raise _conflict("ALREADY_APPROVED", "this baseline version was approved before and is superseded", "input.baseline_version")
        before = ini["version"]
        approval_id = _new_id("appr")
        conn.execute("INSERT INTO baseline_approvals (approval_id, initiative_id, baseline_version, approved_by, approved_at, reason) VALUES (%s,%s,%s,%s,%s,%s)",
                     (approval_id, inp.initiative_id, inp.baseline_version, actor.actor_id, now, inp.reason))
        conn.execute("UPDATE initiatives SET baseline_version = %s, version = version + 1 WHERE initiative_id = %s", (inp.baseline_version, inp.initiative_id))
        frozen = [b["baseline_id"] for b in pop.acc["process_baselines"] if b["initiative_id"] == inp.initiative_id and b["baseline_version"] == inp.baseline_version]
        warns = []
        if ini["baseline_version"] is not None:
            warns.append(_warning("BASELINE_SUPERSEDED", f"baseline {ini['baseline_version']} stays readable but is no longer the approved baseline", "input.baseline_version"))
        return Outcome("approved", {"initiative_id": inp.initiative_id, "baseline_version": inp.baseline_version, "approval_id": approval_id, "approved_by": actor.actor_id,
                                    "approved_at": iso_z(now), "frozen_baseline_ids": frozen, "previous_baseline_version": ini["baseline_version"]},
                       before + 1, warns, Audit("initiative", inp.initiative_id, "establish-baseline", before, before + 1, inp.reason,
                                                {"action": "approve", "baseline_version": inp.baseline_version}))
    # create
    missing = [f for f in ("volume", "minutes_per_case", "error_rate", "evidence_ref", "measured_on") if getattr(inp, f) is None]
    if missing:
        raise ApiError(422, "VALIDATION_FAILED", "a baseline is measured evidence: " + ", ".join(missing) + " required",
                       [detail(f"input.{f}", "FIELD_REQUIRED", "required to create a baseline") for f in missing])
    if ini["baseline_version"] is not None and not (inp.reason or "").strip():
        raise _invalid("REASON_REQUIRED", "a correction of an approved baseline is a new version with a reason", "input.reason")
    row = {"baseline_id": inp.baseline_id or _new_id("pb"), "initiative_id": inp.initiative_id, "baseline_version": inp.baseline_version, "volume": inp.volume,
           "minutes_per_case": inp.minutes_per_case, "error_rate": inp.error_rate, "evidence_ref": _ev(inp.evidence_ref),
           "measured_at": iso_z(_plain_date(inp.measured_on, now, "input.measured_on")), "reason": inp.reason}
    items = [("input", "process_baselines", row)]
    rej = _check_all(Validator(pop), items)
    if rej:
        if rej[0][1].reason_code == "BASELINE_FROZEN":
            _refusal(actor, req, "establish-baseline", "initiative", inp.initiative_id, "BASELINE_FROZEN", "an approved baseline version cannot be rewritten")
        raise _rejections(rej)
    insert_row(conn, "process_baselines", row, by=actor.actor_id, at=now)
    return Outcome("established", {"baseline_id": row["baseline_id"], "initiative_id": inp.initiative_id, "baseline_version": inp.baseline_version, "approved": False,
                                   "evidence": {k: row[k] for k in ("volume", "minutes_per_case", "error_rate", "evidence_ref", "measured_at")},
                                   "approved_baseline_version": ini["baseline_version"], "next_action": "approve (sponsor or admin) to freeze this version"},
                   ini["version"], [], Audit("process_baseline", row["baseline_id"], "establish-baseline", None, None, inp.reason,
                                             {"action": "create", "initiative_id": inp.initiative_id, "baseline_version": inp.baseline_version}))


# --- C02 assess-opportunity -------------------------------------------------------------------------------------

def assess_opportunity(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """A scored option: explicit criteria, scores 1..5 and weights, plus a rationale. The weighted score is Sum(w x s) / Sum(w), exact, shown to 4 places;
    it ranks options, it forecasts nothing. A candidate becomes ``assessed``; an initiative can be created here as a candidate."""
    inp = req.input
    now = _now()
    if not inp.rationale.strip():
        raise _invalid("RATIONALE_REQUIRED", "a rationale is required", "input.rationale")
    seen: set[str] = set()
    for i, c in enumerate(inp.criteria):
        if c.criterion in seen:
            raise _invalid("DUPLICATE_CRITERION", f"criterion {c.criterion!r} appears twice", f"input.criteria[{i}].criterion")
        seen.add(c.criterion)
        if dec(c.weight) <= 0:
            raise _invalid("INVALID_WEIGHT", "a weight is a positive decimal", f"input.criteria[{i}].weight")
    existing = _lock_initiatives(conn, [inp.initiative_id], exclusive=True, must_exist=False).get(inp.initiative_id)
    if existing is None:
        if inp.new_initiative is None:
            raise _err(404, "NOT_FOUND", "UNKNOWN_INITIATIVE", f"initiative {inp.initiative_id!r} is not registered (send new_initiative to create a candidate)", "input.initiative_id")
        n = inp.new_initiative
        v = Validator(db.load_population(conn))
        row = {"initiative_id": inp.initiative_id, "title": n.title, "sponsor_id": n.sponsor_id, "status": "assessed", "baseline_version": None,
               "requested_start_period": n.requested_start_period, "duration_periods": n.duration_periods, "deployment_period": n.deployment_period,
               "eligibility_rule_version": n.eligibility_rule_version}
        rej = _check_all(v, [("input.new_initiative", "initiatives", row)])
        if rej:
            raise _rejections(rej)
        conn.execute("INSERT INTO initiatives (initiative_id, title, sponsor_id, status, baseline_version, requested_start_period, duration_periods, deployment_period, "
                     "eligibility_rule_version, version, created_at, created_by) VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,%s,1,%s,%s)",
                     (row["initiative_id"], row["title"], row["sponsor_id"], "assessed", row["requested_start_period"], row["duration_periods"],
                      row["deployment_period"], row["eligibility_rule_version"], now, actor.actor_id))
        before, after = None, 1
    else:
        if inp.new_initiative is not None:
            raise _conflict("INITIATIVE_EXISTS", "the initiative exists: send criteria only", "input.new_initiative")
        if inp.expected_version is not None and inp.expected_version != existing["version"]:
            raise _conflict("STALE_VERSION", f"the initiative is at version {existing['version']}, not {inp.expected_version}", "input.expected_version",
                            {"current": existing["version"], "requested": inp.expected_version})
        before = existing["version"]
        after = before
        if existing["status"] == "candidate":
            conn.execute("UPDATE initiatives SET status = 'assessed', version = version + 1 WHERE initiative_id = %s", (inp.initiative_id,))
            after = before + 1
    sw = sum((dec(c.weight) for c in inp.criteria), F(0))
    score = sum((dec(c.weight) * c.score for c in inp.criteria), F(0)) / sw
    n_prev = conn.execute("SELECT coalesce(max(version_number), 0) AS n FROM opportunity_scores WHERE initiative_id = %s", (inp.initiative_id,)).fetchone()["n"]
    score_id = _new_id("os")
    criteria = [{"criterion": c.criterion, "score": c.score, "weight": canon(c.weight)} for c in inp.criteria]
    conn.execute("INSERT INTO opportunity_scores (score_id, initiative_id, version_number, criteria, weighted_score, weighted_exact, rationale, author_id, created_at) "
                 "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (score_id, inp.initiative_id, n_prev + 1, Jsonb(criteria), m4(score), ex(score), inp.rationale, actor.actor_id, now))
    return Outcome("scored", {"score_id": score_id, "initiative_id": inp.initiative_id, "version_number": n_prev + 1, "weighted_score": m4(score), "weighted_exact": ex(score),
                              "criteria": criteria, "rationale": inp.rationale, "label": "a ranking aid on declared weights, not a forecast",
                              "status": "assessed" if existing is None or existing["status"] == "candidate" else existing["status"]},
                   after, [], Audit("initiative", inp.initiative_id, "assess-opportunity", before, after, inp.rationale, {"score_id": score_id, "weighted_score": m4(score)}))


# --- C03 build-cash-flows ---------------------------------------------------------------------------------------

def build_cash_flows(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """Assumptions -> a dated model: new assumption versions, a NEW scenario version (an edit is a new scenario_id), cost and benefit rows. Recurring costs
    are expanded here into one row per period of the half-open range (``expanded_costs``). Every row is checked before the first write; the model (net cash
    flow, NPV as an exact rational, both paybacks) is computed from the stored rows at the server's now and is labelled an estimate."""
    inp = req.input
    now = _now()
    ids = set(inp.initiative_ids) | {c.initiative_id for c in inp.costs} | {b.initiative_id for b in inp.benefits} | {a.initiative_id for a in inp.assumptions if a.initiative_id}
    _lock_initiatives(conn, ids, path="input")
    pop = db.load_population(conn)
    v = Validator(pop)
    items: list[tuple[str, str, dict[str, Any]]] = []
    next_version: dict[tuple[str | None, str], int] = {}
    for i, a in enumerate(inp.assumptions):
        key = (a.initiative_id, a.name)
        last = next_version.get(key) or max((x["version_number"] for x in pop.acc["assumption_versions"] if (x["initiative_id"], x["name"]) == key), default=0)
        nv = a.version_number or last + 1
        next_version[key] = max(last, nv)
        items.append((f"input.assumptions[{i}]", "assumption_versions", {
            "assumption_id": a.assumption_id or _new_id("as"), "initiative_id": a.initiative_id, "name": a.name, "version_number": nv,
            "value": a.value, "values": a.values, "unit": a.unit, "rationale": a.rationale, "author_id": actor.actor_id, "evidence_ref": _ev(a.evidence_ref),
            "staffing_change_evidence_ref": _ev(a.staffing_change_evidence_ref), "created_at": iso_z(now)}))
    sc = {"scenario_id": inp.scenario_id, "baseline_version": inp.baseline_version, "discount_rate": inp.discount_rate, "rate_basis": inp.rate_basis,
          "rate_conversion_assumption_id": inp.rate_conversion_assumption_id, "horizon_periods": inp.horizon_periods, "status": "draft",
          "initiative_ids": list(dict.fromkeys(inp.initiative_ids)), "pinned_assumption_ids": list(dict.fromkeys(inp.pinned_assumption_ids)), "created_at": iso_z(now)}
    items.append(("input", "scenario_versions", sc))
    for i, c in enumerate(inp.costs):
        items.append((f"input.costs[{i}]", "cost_items", {
            "cost_id": c.cost_id or _new_id("c"), "initiative_id": c.initiative_id, "cost_key": c.cost_key, "cost_type": c.cost_type, "cost_basis": c.cost_basis,
            "amount": c.amount, "period_index": c.period_index, "start_period": c.start_period, "end_period": c.end_period, "baseline_version": c.baseline_version,
            "recorded_at": iso_z(now)}))
    for i, b in enumerate(inp.benefits):
        items.append((f"input.benefits[{i}]", "benefit_items", {
            "benefit_id": b.benefit_id or _new_id("b"), "initiative_id": b.initiative_id, "benefit_type": b.benefit_type, "amount": b.amount, "period_index": b.period_index,
            "starts_period": b.starts_period, "unit": b.unit or ("hours" if b.benefit_type == "capacity" else "USD"), "cash_realisation": b.cash_realisation,
            "evidence_ref": _ev(b.evidence_ref), "benefit_source_key": b.benefit_source_key, "baseline_trend_per_period": b.baseline_trend_per_period,
            "recorded_at": iso_z(now)}))
    rej = _check_all(v, items)
    if rej:
        raise _rejections(rej)
    _insert(conn, items, actor, now)
    expanded = []
    for iid in sc["initiative_ids"]:
        for c in sorted((c for c in v.acc["cost_items"] if c["initiative_id"] == iid and c["cost_basis"] == "planned"), key=lambda c: c["cost_id"]):
            for _, p, amount in expand_costs(c, inp.horizon_periods):
                conn.execute("INSERT INTO expanded_costs (scenario_id, cost_id, initiative_id, period_index, amount) VALUES (%s,%s,%s,%s,%s)",
                             (inp.scenario_id, c["cost_id"], iid, p, money(amount)))
                expanded.append({"cost_id": c["cost_id"], "initiative_id": iid, "period_index": p, "amount": money(amount)})
    metrics, warns = compute(v.pop, _now(), None, [inp.scenario_id])
    model = metrics["scenarios"][inp.scenario_id]
    warnings = [_warning("ESTIMATE", "NPV, paybacks and cash flows are estimates from declared assumptions, not observed results", "result.scenario")]
    for iid, blk in model["initiatives"].items():
        if blk["excluded_from_cash_flow"]["capacity_hours_not_converted"]:
            warnings.append(_warning("CAPACITY_NOT_IN_CASH_FLOW", f"{blk['excluded_from_cash_flow']['capacity_hours_not_converted']} capacity hours of {iid} stay out of the "
                                     "cash flow: there is no capacity_hourly_rate with a staffing change evidence reference", f"result.scenario.initiatives.{iid}"))
        if blk["excluded_from_cash_flow"]["avoided_cost_beside"]:
            warnings.append(_warning("AVOIDED_COST_BESIDE", f"avoided cost of {iid} is reported beside the cash flow (no removed budget line)", f"result.scenario.initiatives.{iid}"))
    return Outcome("built", {"scenario_id": inp.scenario_id, "status": "draft", "rows_added": {"assumption_versions": len(inp.assumptions), "cost_items": len(inp.costs),
                                                                                                  "benefit_items": len(inp.benefits), "expanded_costs": len(expanded)},
                             "expanded_costs": expanded, "scenario": model, "label": "estimate"},
                   1, warnings, Audit("scenario", inp.scenario_id, "build-cash-flows", None, 1, None, {"initiatives": sc["initiative_ids"], "horizon_periods": inp.horizon_periods}))


# --- C04 map-impacts --------------------------------------------------------------------------------------------

def map_impacts(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    _lock_initiatives(conn, [inp.initiative_id])
    pop = db.load_population(conn)
    v = Validator(pop)
    items: list[tuple[str, str, dict[str, Any]]] = []
    for i, g in enumerate(inp.groups):
        items.append((f"input.groups[{i}]", "stakeholder_groups", {"group_id": g.group_id, "group_name": g.group_name, "owner_id": g.owner_id,
                                                                  "affected_count": g.affected_count, "impact_level": g.impact_level}))
    for i, m in enumerate(inp.mappings):
        items.append((f"input.mappings[{i}]", "impact_mappings", {"mapping_id": m.mapping_id or _new_id("im"), "initiative_id": inp.initiative_id, "group_id": m.group_id,
                                                                  "operating_change": m.operating_change, "impact_level": m.impact_level}))
    rej = _check_all(v, items)
    if rej:
        raise _rejections(rej)
    _insert(conn, items, actor)
    maps = [m for m in v.acc["impact_mappings"] if m["initiative_id"] == inp.initiative_id]
    groups = {g["group_id"]: g for g in v.acc["stakeholder_groups"]}
    affected = sorted({m["group_id"] for m in maps})
    by_level: dict[str, int] = {}
    for m in maps:
        by_level[m["impact_level"]] = by_level.get(m["impact_level"], 0) + 1
    return Outcome("mapped", {"initiative_id": inp.initiative_id, "mappings_added": [i[2]["mapping_id"] for i in items if i[1] == "impact_mappings"],
                              "groups_created": [g.group_id for g in inp.groups], "groups_affected": [
                                  {"group_id": g, "group_name": groups[g]["group_name"], "affected_count": groups[g]["affected_count"], "impact_level": groups[g]["impact_level"]}
                                  for g in affected],
                              "total_mappings": len(maps), "total_affected_count": sum(groups[g]["affected_count"] for g in affected), "by_impact_level": by_level,
                              "labels": "synthetic"},
                   1, [], Audit("initiative", inp.initiative_id, "map-impacts", None, None, None, {"mappings": len(inp.mappings), "groups_created": len(inp.groups)}))


# --- C05 assess-readiness ---------------------------------------------------------------------------------------

def assess_readiness(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    now = _now()
    grp = conn.execute("SELECT * FROM stakeholder_groups WHERE group_id = %s FOR SHARE", (inp.group_id,)).fetchone()
    if grp is None:
        raise _err(404, "NOT_FOUND", "UNKNOWN_GROUP", f"stakeholder group {inp.group_id!r} does not exist", "input.group_id")
    dims = [a.dimension for a in inp.assessments]
    for i, d in enumerate(dims):
        if dims.index(d) != i:
            raise _invalid("DUPLICATE_DIMENSION", f"dimension {d!r} appears twice in one request", f"input.assessments[{i}].dimension")
    pop = db.load_population(conn)
    v = Validator(pop)
    items = [(f"input.assessments[{i}]", "readiness_assessments", {"assessment_id": _new_id("ra"), "group_id": inp.group_id, "dimension": a.dimension, "score": a.score,
                                                                    "weight": a.weight, "assessed_at": iso_z(now)}) for i, a in enumerate(inp.assessments)]
    rej = _check_all(v, items)
    if rej:
        raise _rejections(rej)
    _insert(conn, items, actor)
    snap = readiness_metric(_ctx(v.pop, _now()))[inp.group_id]
    return Outcome("assessed", {"group_id": inp.group_id, "assessment_ids": [i[2]["assessment_id"] for i in items], "readiness": snap, "labels": "synthetic"},
                   1, [_warning("ASSESSMENT_NOT_PROBABILITY", "a readiness score is an assessment, not a probability of success", "result.readiness")],
                   Audit("stakeholder_group", inp.group_id, "assess-readiness", None, None, None, {"dimensions": dims, "readiness_score": snap["readiness_score"]}))


# --- C06 plan-roadmap -------------------------------------------------------------------------------------------

def plan_roadmap(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """Options -> a feasible schedule: schedule edits (optimistic ``expected_version``), dependencies (a cycle is refused with the cycle listed) and shared
    capacity (an allocation that would cross a resource's capacity is refused with its periods; exactly at capacity is allowed). Allocations are checked in
    the order sent. Nothing is written unless every row passes."""
    inp = req.input
    ids = {s.initiative_id for s in inp.schedule} | {d.initiative_id for d in inp.dependencies} | {d.prerequisite_id for d in inp.dependencies} | \
        {a.initiative_id for a in inp.allocations}
    locked = _lock_initiatives(conn, ids, exclusive=True, path="input")
    res_ids = sorted({a.resource_id for a in inp.allocations})
    if res_ids:
        conn.execute("SELECT resource_id FROM resources WHERE resource_id = ANY(%s) ORDER BY resource_id COLLATE \"C\" FOR UPDATE", (res_ids,)).fetchall()
    pop = db.load_population(conn)
    v = Validator(pop)
    by_id = {i["initiative_id"]: i for i in pop.acc["initiatives"]}
    changed: dict[str, tuple[int, int, int]] = {}
    for k, s in enumerate(inp.schedule):
        cur = locked[s.initiative_id]
        if s.expected_version is not None and s.expected_version != cur["version"]:
            raise _conflict("STALE_VERSION", f"initiative {s.initiative_id} is at version {cur['version']}, not {s.expected_version}", f"input.schedule[{k}].expected_version",
                            {"current": cur["version"], "requested": s.expected_version})
        if (s.requested_start_period, s.duration_periods) != (cur["requested_start_period"], cur["duration_periods"]):
            changed[s.initiative_id] = (s.requested_start_period, s.duration_periods, cur["version"])
            by_id[s.initiative_id]["requested_start_period"] = s.requested_start_period
            by_id[s.initiative_id]["duration_periods"] = s.duration_periods
    items: list[tuple[str, str, dict[str, Any]]] = []
    for i, r in enumerate(inp.resources):
        items.append((f"input.resources[{i}]", "resources", {"resource_id": r.resource_id, "name": r.name, "capacity_per_period": r.capacity_per_period, "unit": r.unit}))
    for i, d in enumerate(inp.dependencies):
        items.append((f"input.dependencies[{i}]", "dependencies", {"dependency_id": d.dependency_id or _new_id("d"), "initiative_id": d.initiative_id,
                                                                  "prerequisite_id": d.prerequisite_id, "dependency_type": d.dependency_type, "lag_periods": d.lag_periods}))
    for i, a in enumerate(inp.allocations):
        items.append((f"input.allocations[{i}]", "resource_allocations", {"allocation_id": a.allocation_id or _new_id("al"), "resource_id": a.resource_id,
                                                                         "initiative_id": a.initiative_id, "period_index": a.period_index, "amount": a.amount}))
    rej = _check_all(v, items)
    if rej:
        raise _rejections(rej)
    _insert(conn, items, actor)
    audits: list[Audit] = []
    for iid, (start, dur, ver) in sorted(changed.items()):
        conn.execute("UPDATE initiatives SET requested_start_period = %s, duration_periods = %s, version = version + 1 WHERE initiative_id = %s", (start, dur, iid))
        audits.append(Audit("initiative", iid, "plan-roadmap", ver, ver + 1, None, {"requested_start_period": start, "duration_periods": dur}))
    try:
        feas = feasible_starts({i["initiative_id"]: i for i in v.acc["initiatives"]}, v.acc["dependencies"])
    except DomainError as err:
        raise _domain(err, "input.dependencies") from None
    plan_ctx = Ctx(v.pop, _now())
    schedule = {iid: initiative_roadmap(plan_ctx, feas, iid) for iid in sorted(feas)}
    audits.append(Audit("roadmap", "roadmap", "plan-roadmap", None, None, None, {"dependencies": len(inp.dependencies), "allocations": len(inp.allocations),
                                                                                 "schedule_changes": sorted(changed)}))
    version = max([ver + 1 for _, _, ver in changed.values()], default=1)
    return Outcome("planned", {"schedule": schedule, "resources": resource_views(Ctx(v.pop, _now())), "changed_initiatives": sorted(changed),
                               "dependencies_added": [i[2]["dependency_id"] for i in items if i[1] == "dependencies"],
                               "allocations_added": [i[2]["allocation_id"] for i in items if i[1] == "resource_allocations"],
                               "note": "the roadmap is reported beside the cash flows and does not re-time them"}, version, [], audits)


# --- C07 select-scenario ----------------------------------------------------------------------------------------

def select_scenario(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """Compared options -> a PROPOSED portfolio. It is never "funded" (STATUS_NOT_ALLOWED). It is refused while the double-count residual is not 0.00 and
    has no explanation (DOUBLE_COUNT_UNEXPLAINED, with the overlaps listed); the comparison it was chosen from is stored with the proposal."""
    inp = req.input
    now = _now()
    if inp.status != "proposed":
        raise _invalid("STATUS_NOT_ALLOWED", f"a selected scenario is a proposal; {inp.status!r} is not a status of this product", "input.status")
    sc = conn.execute("SELECT * FROM scenario_versions WHERE scenario_id = %s", (inp.scenario_id,)).fetchone()
    if sc is None:
        raise _not_found("input.scenario_id", "UNKNOWN_SCENARIO", "scenario")
    compared = sorted({inp.scenario_id, *inp.compared_scenario_ids})
    inits = conn.execute("SELECT DISTINCT initiative_id FROM scenario_initiatives WHERE scenario_id = ANY(%s)", (compared,)).fetchall()
    _lock_initiatives(conn, [r["initiative_id"] for r in inits], path="input")
    rows = conn.execute("SELECT scenario_id, status FROM scenario_versions WHERE scenario_id = ANY(%s) ORDER BY scenario_id COLLATE \"C\" FOR UPDATE", (compared,)).fetchall()
    known = {r["scenario_id"]: r["status"] for r in rows}
    for i, other in enumerate(inp.compared_scenario_ids):
        if other not in known:
            raise _not_found(f"input.compared_scenario_ids[{i}]", "UNKNOWN_SCENARIO", "scenario")
    if known[inp.scenario_id] == "proposed":
        raise _conflict("ALREADY_PROPOSED", "this scenario is already a proposal", "input.scenario_id")
    pop = db.load_population(conn)
    metrics, _ = compute(pop, now, None, compared)
    chosen = metrics["scenarios"][inp.scenario_id]
    dc = chosen["double_count"]
    explanation = (inp.residual_explanation or "").strip()
    if dc["explanation_required"] and not explanation:
        _refusal(actor, req, "select-scenario", "scenario", inp.scenario_id, "DOUBLE_COUNT_UNEXPLAINED", f"residual {dc['residual']} has no explanation")
        raise _invalid("DOUBLE_COUNT_UNEXPLAINED", f"the double-count residual is {dc['residual']} USD and {dc['hours_residual']} hours (explain: "
                       f"{' and '.join(dc['explanation_required_for'])}) and must be explained on the portfolio before a scenario can be proposed",
                       "input.residual_explanation", {"residual": dc["residual"], "hours_residual": dc["hours_residual"], "overlaps": dc["overlaps"],
                                                      "hours_overlaps": dc["hours_overlaps"]})
    if explanation and len(explanation) < MIN_EXPLANATION:
        raise _invalid("EXPLANATION_TOO_SHORT", f"an explanation says what the shared claim is and why it is counted once: at least {MIN_EXPLANATION} characters "
                       f"(got {len(explanation)})", "input.residual_explanation", {"minimum": MIN_EXPLANATION, "length": len(explanation)})
    resolved = snapshot_hash(Ctx(pop, now, None, compared), next(sv for sv in pop.acc["scenario_versions"] if sv["scenario_id"] == inp.scenario_id))
    comparison = {"compared_scenario_ids": compared, "as_of": iso_z(now), "snapshot_hash": resolved, "scenarios": {
        sid: {"npv_total": s["npv_total"], "residual": s["double_count"]["residual"], "hours_residual": s["double_count"]["hours_residual"], "status": s["status"],
              "initiatives": {iid: {"npv": b["npv"]["value"], "simple_payback": b["payback"]["simple"]["period"],
                                    "discounted_payback": b["payback"]["discounted"]["period"]} for iid, b in s["initiatives"].items()}}
        for sid, s in metrics["scenarios"].items()}, "label": "estimates"}
    conn.execute("UPDATE scenario_versions SET status = 'proposed', proposed_at = %s, proposed_by = %s, comparison = %s, residual_explanation = %s, snapshot_hash = %s "
                 "WHERE scenario_id = %s", (now, actor.actor_id, Jsonb(comparison), explanation or None, resolved, inp.scenario_id))
    warns = [_warning("PROPOSAL_NOT_FUNDING", "a proposal; nothing here funds anything", "result.status")]
    if dc["explanation_required"]:
        warns.append(_warning("RESIDUAL_EXPLAINED", f"residual {dc['residual']} USD and {dc['hours_residual']} hours accepted with the stated explanation", "input.residual_explanation"))
    return Outcome("proposed", {"scenario_id": inp.scenario_id, "status": "proposed", "funded": False, "proposed_by": actor.actor_id, "proposed_at": iso_z(now),
                                "double_count": dc, "residual_explanation": explanation or None, "snapshot_hash": resolved, "comparison": comparison},
                   1, warns, Audit("scenario", inp.scenario_id, "select-scenario", None, None, explanation or None, {"compared": compared, "residual": dc["residual"]}))


# --- C08 record-adoption ----------------------------------------------------------------------------------------

def record_adoption(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """An adoption observation with its denominator preserved (eligible and adopted, under the initiative's eligibility rule version). Training completion
    may travel with it but is a separate series and is never substituted for adoption."""
    inp = req.input
    now = _now()
    ini = _lock_initiatives(conn, [inp.initiative_id])[inp.initiative_id]
    pop = db.load_population(conn)
    at = _observed_on(inp.observed_on, now, "input.observed_on", ini, pop.config)
    v = Validator(pop)
    items: list[tuple[str, str, dict[str, Any]]] = [("input", "adoption_observations", {
        "observation_id": _new_id("ad"), "initiative_id": inp.initiative_id, "eligible_count": inp.eligible_count, "adopted_count": inp.adopted_count,
        "observed_at": iso_z(at), "eligibility_rule_version": inp.eligibility_rule_version, "recorded_at": iso_z(now)})]
    if inp.training is not None:
        items.append(("input.training", "training_completions", {"training_id": _new_id("tc"), "initiative_id": inp.initiative_id,
                                                                 "eligible_trainees": inp.training.eligible_trainees, "completed": inp.training.completed,
                                                                 "recorded_at": iso_z(at), "eligibility_rule_version": inp.eligibility_rule_version, "entered_at": iso_z(now)}))
    rej = _check_all(v, items)
    if rej:
        raise _rejections(rej)
    _insert(conn, items, actor, now)
    ctx = _ctx(v.pop, _now())
    ad = adoption_metric(ctx, inp.initiative_id)
    tr = training_metric(ctx, inp.initiative_id, ad["adoption_rate"])
    warns = []
    if inp.eligible_count == 0:
        warns.append(_warning("ZERO_ELIGIBLE", "no eligible population: the adoption rate is null, not 0", "result.adoption_rate"))
    return Outcome("recorded", {"observation_id": items[0][2]["observation_id"], "initiative_id": inp.initiative_id, "eligible_count": inp.eligible_count,
                                "adopted_count": inp.adopted_count, "adoption_rate": ad["adoption_rate"], "observed_at": iso_z(at),
                                "eligibility_rule_version": inp.eligibility_rule_version, "series": ad["series"], "excluded_after_as_of": ad["excluded_after_as_of"],
                                "training": tr, "training_is_not_adoption": True},
                   1, warns, Audit("initiative", inp.initiative_id, "record-adoption", None, None, None,
                                   {"observation_id": items[0][2]["observation_id"], "eligible": inp.eligible_count, "adopted": inp.adopted_count}))


# --- C09 track-benefits -----------------------------------------------------------------------------------------

def track_benefits(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """An observed value for one planned benefit, compared WITHIN its benefit type on matured periods. The comparison always says "observed, not
    attributed"; a claim of full attribution is refused (ATTRIBUTION_NOT_ESTABLISHED), and the baseline trend sits beside the raw change."""
    inp = req.input
    now = _now()
    if inp.attribution != "observed_not_attributed":
        raise _invalid("ATTRIBUTION_NOT_ESTABLISHED", "an observed improvement is not attributed to the rollout without a comparison with the baseline trend; "
                       "use attribution \"observed_not_attributed\"", "input.attribution")
    if not inp.evidence_ref.strip():
        raise _invalid("EVIDENCE_REQUIRED", "an observation cites its evidence", "input.evidence_ref")
    b = conn.execute("SELECT benefit_id, initiative_id, benefit_type, unit, period_index, cw_dec(baseline_trend_per_period) AS trend FROM benefit_items WHERE benefit_id = %s",
                     (inp.benefit_id,)).fetchone()
    if b is None:
        raise _err(404, "NOT_FOUND", "UNKNOWN_BENEFIT", f"benefit {inp.benefit_id!r} does not exist", "input.benefit_id")
    ini = _lock_initiatives(conn, [b["initiative_id"]])[b["initiative_id"]]
    if inp.unit != b["unit"]:
        raise _invalid("BENEFIT_TYPE_MISMATCH", f"{inp.benefit_id} is a {b['benefit_type']} benefit measured in {b['unit']}; an observation in {inp.unit} is a different type "
                       "and is never added or compared", "input.unit", {"benefit_type": b["benefit_type"], "unit": b["unit"]})
    pop = db.load_population(conn)
    at = _observed_on(inp.observed_on, now, "input.observed_on", ini, pop.config)
    v = Validator(pop)
    row = {"benefit_observation_id": _new_id("bo"), "benefit_id": inp.benefit_id, "measured_value": inp.measured_value, "evidence_ref": _ev(inp.evidence_ref),
           "observed_at": iso_z(at), "recorded_at": iso_z(now)}
    rej = _check_all(v, [("input", "benefit_observations", row)])
    if rej:
        raise _rejections(rej)
    insert_row(conn, "benefit_observations", row, by=actor.actor_id, at=now)
    when = _now()
    metrics, _ = compute(v.pop, when, None, None)
    iid = b["initiative_id"]
    comparisons = {sid: s["initiatives"][iid]["benefit_realization"].get(b["benefit_type"]) for sid, s in metrics["scenarios"].items() if iid in s["initiatives"]}
    warns = [_warning("OBSERVED_NOT_ATTRIBUTED", "observed, not attributed: the change is compared with the baseline trend and is not credited to the rollout", "result.comparisons")]
    if b["trend"] is None:
        warns.append(_warning("NO_BASELINE_TREND", "no baseline trend was recorded before deployment for this benefit", "result.comparisons"))
    if not matured(pop.config, b["period_index"], when):
        warns.append(_warning("PERIOD_NOT_MATURED", "the benefit's period has not ended: the observation is kept but excluded from the realization", "result.comparisons"))
    return Outcome("tracked", {"benefit_observation_id": row["benefit_observation_id"], "benefit_id": inp.benefit_id, "initiative_id": iid, "benefit_type": b["benefit_type"],
                               "unit": b["unit"], "measured_value": canon(inp.measured_value), "observed_at": iso_z(at), "attribution": "observed, not attributed",
                               "comparisons": comparisons, "forecast": metrics["initiatives"][iid]["forecast"]},
                   1, warns, Audit("benefit", inp.benefit_id, "track-benefits", None, None, None, {"observation_id": row["benefit_observation_id"], "unit": b["unit"]}))


# --- C10 revise-forecast ----------------------------------------------------------------------------------------

def revise_forecast(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """Forecast version n+1 for an initiative; versions are rows and the database refuses an UPDATE or DELETE, so the original approval is never overwritten.
    The first forecast of an initiative is version 1 (the original). ``expected_version`` is the version the caller last read."""
    inp = req.input
    now = _now()
    if not inp.reason.strip():
        raise _invalid("REASON_REQUIRED", "a revision states why the forecast changed", "input.reason")
    pers = [p.period_index for p in inp.periods]
    for i, p in enumerate(pers):
        if pers.index(p) != i:
            raise _invalid("DUPLICATE_PERIOD", f"period {p} appears twice", f"input.periods[{i}].period_index")
    ini = _lock_initiatives(conn, [inp.initiative_id], exclusive=True)[inp.initiative_id]
    n = conn.execute("SELECT coalesce(max(version_number), 0) AS n FROM forecast_versions WHERE initiative_id = %s", (inp.initiative_id,)).fetchone()["n"]
    if inp.expected_version != n:                       # R9-22: the version the caller last read is always named (0: no forecast yet)
        raise _conflict("STALE_FORECAST_VERSION", f"the latest forecast is version {n}, not {inp.expected_version}", "input.expected_version", {"current": n, "requested": inp.expected_version})
    pop = db.load_population(conn)
    v = Validator(pop)
    items = [(f"input.periods[{i}]", "forecast_versions", {"forecast_id": _new_id("f"), "initiative_id": inp.initiative_id, "version_number": n + 1,
                                                            "period_index": p.period_index, "amount": p.amount, "reason": inp.reason, "created_at": iso_z(now)})
             for i, p in enumerate(inp.periods)]
    rej = _check_all(v, items)
    if rej:
        raise _rejections(rej)
    if n:                                               # R9-10: a revision restates every period of the original, so its total is comparable with it
        original = {r["period_index"] for r in conn.execute("SELECT period_index FROM forecast_versions WHERE initiative_id = %s AND version_number = 1", (inp.initiative_id,)).fetchall()}
        missing = sorted(original - set(pers))
        if missing:
            raise _invalid("REVISION_PERIODS_INCOMPLETE", f"a revision covers every period of the original forecast; periods {missing} are missing",
                           "input.periods", {"missing_periods": missing, "original_periods": sorted(original)})
    _insert(conn, items, actor)
    fc = forecast_metric(_ctx(v.pop, _now()), inp.initiative_id)
    assert fc is not None
    return Outcome("revised", {"initiative_id": inp.initiative_id, "version_number": n + 1, "original_version": fc["original_version"], "original_preserved": True,
                               "total": fc["versions"][-1]["total"], "latest_minus_original": fc["latest_minus_original"], "forecast": fc},
                   n + 1, [] if n else [_warning("FIRST_FORECAST", "no forecast existed: this is version 1, the original", "result.version_number")],
                   Audit("forecast", f"{inp.initiative_id}:v{n + 1}", "revise-forecast", n or None, n + 1, inp.reason, {"initiative_id": inp.initiative_id, "periods": len(items)}))
