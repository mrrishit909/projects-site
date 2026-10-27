"""Commands C01..C10 (docs/api-contract.md, docs/contracts.md D-01..D-05; backend conventions and assumptions in README.md).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit together or not at all.
Input is validated (pydantic, then domain rules) before the first write. The same ``idempotency_key`` with the same payload, the same
actor id, the same role and the same dataset_version returns the stored response; with a different payload, actor or role it is a 409.
Instants that are decisions (a run's ``created_at``, ``scored_at``, ``published_at``, a scenario's ``created_at``) are stamped by the
SERVER's clock, never chosen by the client. The ``as_of`` of every command is the server's clock.

Lock order (every command, so two commands cannot deadlock on each other):
    1. the idempotency key (advisory lock)
    2. training-run rows, by id (FOR SHARE for C01/C02/C08/C09/C10 reads of a run, FOR UPDATE where the run's config or split changes;
       an advisory lock on the run id guards the creation of a run in C03)
    3. scenario rows, by id (an advisory lock on the scenario id guards creation, then the row FOR SHARE)
A deadlock or serialization failure that still happens is rolled back and retried, three attempts in all, then answered
409 CONCURRENT_UPDATE.

Roles (X-Actor-Role): scientist | analyst | admin.  C01-C07 and C10: scientist, admin.  C08, C09: scientist, analyst, admin.
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any, Callable

import psycopg
from psycopg.types.json import Jsonb
from retentionlab import errors as E
from retentionlab.contract import DEFAULT_DRIFT, FEATURES, MODELS, ROLES as ROLE_LIST
from retentionlab.errors import DomainError
from retentionlab.fitting import fit_platt, fit_preprocessing, model_config, score_features, train_models
from retentionlab.metrics import average_precision, economics, freshness, publications, rank_key, set_metrics
from retentionlab.numbers import canon, config_hash, p6, ratio, sha256_hex
from retentionlab.rules import check_calibration_rows, check_capacity, check_feature_request, check_fit_rows, check_threshold
from retentionlab.split import retained, split_run
from retentionlab.timeutil import iso_z, parse_ts
from retentionlab.world import World

from data.artefacts import write_artefacts

from . import clock, db
from .errors import ApiError, detail
from .schemas import Envelope

Conn = psycopg.Connection[db.Row]
ROLES = frozenset(ROLE_LIST)
ALL_ROLES = ROLES
SCIENTIST_ROLES = frozenset({"scientist", "admin"})
#: Domain refusals that are kept in the audit trail even though the command's own transaction is rolled back.
REFUSAL_RULES = frozenset({E.POST_OUTCOME_FIELD, E.LATENT_TRUTH, E.ID_FEATURE, E.UNKNOWN_FEATURE, E.LEAKAGE, E.CALIBRATION_ON_FIT_ROWS,
                           E.THRESHOLD_ON_TEST, E.CAPACITY_EXCEEDS_POPULATION, E.RISK_NOT_RESPONSIVENESS, E.ASSUMED_EFFECT_OUT_OF_RANGE,
                           E.SCENARIO_IMMUTABLE, E.RUN_FROZEN})


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
    from .errors import from_domain
    return from_domain(err, path)


# --- idempotent execution ---------------------------------------------------------------------------------------

def _normalise(value: Any, key: str = "") -> Any:
    """An instant (a string under a ``*_at`` / ``*_end`` key) is hashed as the UTC instant it names."""
    if isinstance(value, dict):
        return {k: _normalise(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v, key) for v in value]
    if isinstance(value, str) and key.endswith(("_at", "_end")):
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
        text = canon({"command": name, "dataset_version": req.dataset_version, "input": body})
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
    in all, short randomised back-off); the last failure is 409 CONCURRENT_UPDATE, never a 500. A domain refusal is audited."""
    _need_role(actor, roles, name)
    payload_hash = _payload_hash(name, req)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _execute_once(name, req, actor, handler, payload_hash)
        except _RETRYABLE:
            if attempt < MAX_ATTEMPTS:
                time.sleep(random.uniform(0.005, 0.03) * attempt)
        except ApiError as exc:
            rules = [d.get("rule_id") for d in exc.details]
            if exc.status in (409, 422) and any(r in REFUSAL_RULES for r in rules):
                _refusal(actor, req, name, rules[0], exc.message, exc.details)
            raise
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
    "training_runs_pkey": ("TRAINING_RUN_EXISTS", "a training run with this id exists"),
    "intervention_scenarios_pkey": ("SCENARIO_EXISTS", "a scenario with this id exists"),
    "outreach_scenario_account_uq": (E.QUEUE_EXISTS, "this scenario already has an outreach queue"),
    "predictions_run_cutoff_model_uq": ("ALREADY_SCORED", "this account is already scored by this model under this run"),
    "feature_rows_cutoff_version_uq": ("FEATURES_EXIST", "this cutoff already has feature rows"),
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
        except psycopg.errors.IntegrityError as exc:  # checks and triggers: append-only, citations, availability ...
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


def _refusal(actor: Actor, req: Envelope, command: str, rule_id: str, message: str, details: list[dict[str, Any]]) -> None:
    """Keep a refused decision in the audit trail (its own transaction: the command's is rolled back)."""
    with db.autocommit() as c:
        c.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, actor_role, reason, request_id, details) "
                  "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                  (f"evt-{uuid.uuid4().hex[:16]}", "command", command, f"{command}-refused", actor.actor_id, actor.role, message,
                   req.request_id, Jsonb({"rule_id": rule_id, "context": [d.get("context") for d in details]})))


# --- shared lookups and locks -----------------------------------------------------------------------------------

def _lock_run(conn: Conn, run_id: str, exclusive: bool = False, path: str = "input.training_run_id") -> db.Row:
    """Lock order step 2: the training-run row (FOR SHARE or FOR UPDATE)."""
    row = conn.execute(f"SELECT * FROM training_runs WHERE training_run_id = %s FOR {'UPDATE' if exclusive else 'SHARE'}", (run_id,)).fetchone()
    if row is None:
        raise _not_found(path, E.UNKNOWN_TRAINING_RUN, "training run")
    return row


def _world(conn: Conn, model: str = "logistic_regression") -> tuple[dict[str, Any], World]:
    data = db.load_data(conn, _now(), model)
    return data, World(data, data)


def _frozen(conn: Conn, run_id: str) -> bool:
    return conn.execute("SELECT EXISTS (SELECT 1 FROM predictions WHERE training_run_id = %s) AS f", (run_id,)).fetchone()["f"]


def _require_unfrozen(conn: Conn, run_id: str) -> None:
    if _frozen(conn, run_id):
        raise _domain(DomainError(E.RUN_FROZEN, f"training run {run_id!r} has been scored: its configuration never changes (start a new run)",
                                  "input.training_run_id"), "input.training_run_id")


def _save_config(conn: Conn, run_id: str, config: dict[str, Any]) -> str:
    h = config_hash(config)
    conn.execute("UPDATE training_runs SET config = %s, config_hash = %s WHERE training_run_id = %s", (Jsonb(config), h, run_id))
    write_artefacts(conn, run_id, config)
    return h


def _model_name(model: str, path: str = "input.model") -> str:
    if model not in MODELS:
        raise _invalid(E.UNKNOWN_MODEL, f"model must be one of {', '.join(MODELS)}", path)
    return model


def _stored_rows(data: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    return {f["cutoff_id"]: f["features_json"] for f in data["feature_rows"]}, {l["cutoff_id"]: l for l in data["labels"]}


def _labelled(cutoff_ids: set[str], features: dict[str, Any], labels: dict[str, Any]) -> list[tuple[str, dict[str, Any], bool]]:
    """(cutoff_id, features, churned) for the rows with a stored feature row AND a mature stored label, in cutoff_id order."""
    return [(c, features[c], bool(labels[c]["churned"])) for c in sorted(cutoff_ids)
            if c in features and c in labels and labels[c]["mature"] and labels[c]["churned"] is not None]


def _cutoffs_at(world: World, prediction_at: str, account_ids: list[int] | None) -> list[dict[str, Any]]:
    pa = parse_ts(prediction_at)
    want = set(account_ids) if account_ids else None
    rows = [c for c in world.acc["prediction_cutoffs"] if parse_ts(c["prediction_at"]) == pa and (want is None or c["account_id"] in want)]
    if not rows:
        raise _not_found("input.prediction_at", E.UNKNOWN_CUTOFF, "cutoff set")
    return rows


def _validation_comparison(config: dict[str, Any], rows: list[tuple[str, dict[str, Any], bool]]) -> dict[str, Any]:
    """AP and Brier of each model on the (retained, mature) VALIDATION rows, uncalibrated: the choice of model is made here, never on test."""
    out: dict[str, Any] = {}
    for model in MODELS:
        items = [{"p": Fraction(score_features(config, model, c, f, calibrated=False)), "y": y, "account_id": k} for k, (c, f, y) in enumerate(rows)]
        positives = sum(1 for it in items if it["y"])
        ap, _ = average_precision(items, positives)
        squares = [(it["p"] - (1 if it["y"] else 0)) ** 2 for it in items]
        out[model] = {"average_precision": p6(ap), "brier_score": p6(sum(squares, Fraction(0)) / len(items) if items else None),
                      "n": len(items), "positives": positives}
    return out


def _better(a: str | None, b: str | None, lower_is_better: bool) -> bool:
    if a is None or b is None:
        return False
    return Fraction(a) < Fraction(b) if lower_is_better else Fraction(a) > Fraction(b)


# --- C01 build-point-in-time-features ----------------------------------------------------------------------------------

def build_features(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """cutoff -> features (P10-FLOW-01). Only registry features; an event counts only when BOTH its event_at and its available_at are
    before the cutoff; an event that happened earlier but arrived after the cutoff is excluded and counted as arrived_late."""
    i = req.input
    data, world = _world(conn)
    fields = list(i.fields) if i.fields else list(FEATURES)
    try:
        check_feature_request(world.registry, fields)
    except DomainError as err:
        raise _domain(err, "input.fields") from None
    cutoffs = _cutoffs_at(world, i.prediction_at, i.account_ids)
    stored = {f["cutoff_id"]: f for f in data["feature_rows"]}
    built = unchanged = 0
    mismatched: list[str] = []
    ineligible: dict[str, int] = {}
    late = {"subscription_events": 0, "billing_events": 0, "usage_events": 0, "support_events": 0}
    proof = {"checked": 0, "all_before_cutoff": True}
    for c in cutoffs:
        a = world.analyse(c["cutoff_id"])
        if not a["eligible"]:
            ineligible[a["ineligible_code"]] = ineligible.get(a["ineligible_code"], 0) + 1
            continue
        for k, v in a["arrived_late"].items():
            late[k] += v
        proof["checked"] += 1
        if a["max_available_at"] is not None and not parse_ts(a["max_available_at"]) < parse_ts(a["prediction_at"]):
            proof["all_before_cutoff"] = False
        old = stored.get(c["cutoff_id"])
        if old is None:
            conn.execute("INSERT INTO feature_rows (feature_row_id, cutoff_id, feature_version, features_json, max_available_at) VALUES (%s,%s,%s,%s,%s)",
                         (f"fr-{c['cutoff_id']}", c["cutoff_id"], world.feature_version, Jsonb(a["features"]),
                          parse_ts(a["max_available_at"]) if a["max_available_at"] else None))
            built += 1
        elif old["features_json"] == a["features"] and old["max_available_at"] == a["max_available_at"]:
            unchanged += 1
        else:
            mismatched.append(c["cutoff_id"])
    warnings = []
    if sum(late.values()):
        warnings.append(_warning("LATE_EVENTS_EXCLUDED", f"{sum(late.values())} event(s) happened before the cutoff but arrived after it and were excluded", "result.arrived_late"))
    if mismatched:
        warnings.append(_warning("STORED_FEATURES_DIFFER", "stored feature rows differ from the rebuilt ones; they are append-only and were not changed", "result.mismatched"))
    result = {"prediction_at": iso_z(parse_ts(i.prediction_at)), "feature_version": world.feature_version, "fields": fields, "cutoff_rows": len(cutoffs),
              "eligible": proof["checked"], "ineligible": dict(sorted(ineligible.items())), "built": built, "unchanged": unchanged,
              "mismatched": mismatched, "arrived_late": {**late, "total": sum(late.values())}, "availability_proof": proof}
    return Outcome("built" if built else "unchanged", result, warnings=warnings,
                   audit=Audit("feature_set", result["prediction_at"], "build-point-in-time-features",
                               details={"built": built, "unchanged": unchanged, "arrived_late": sum(late.values())}))


# --- C02 define-label ----------------------------------------------------------------------------------------------------

def define_label(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """mature horizon -> outcome (P10-FLOW-02). An immature row is CENSORED: stored with churned NULL, never false, and excluded from
    every evaluation; when its window matures a later call turns it into a known outcome, once."""
    i = req.input
    data, world = _world(conn)
    cutoffs = _cutoffs_at(world, i.prediction_at, i.account_ids)
    stored = {l["cutoff_id"]: l for l in data["labels"]}
    created = matured = unchanged = censored = mature = churned = 0
    mismatched: list[str] = []
    ineligible: dict[str, int] = {}
    for c in cutoffs:
        a = dict(world.analyse(c["cutoff_id"]))
        if not a["eligible"]:
            ineligible[a["ineligible_code"]] = ineligible.get(a["ineligible_code"], 0) + 1
            continue
        a["mature"], a["churned"] = world.recomputed(c["cutoff_id"])        # labelling is the one writer: it reads the rules' maturity at the server clock, not the stored label
        censored += 0 if a["mature"] else 1
        if a["mature"]:
            mature += 1
            churned += 1 if a["churned"] else 0
        old = stored.get(c["cutoff_id"])
        if old is None:
            conn.execute("INSERT INTO labels (label_id, cutoff_id, churned, label_end, mature) VALUES (%s,%s,%s,%s,%s)",
                         (f"lb-{c['cutoff_id']}", c["cutoff_id"], a["churned"], parse_ts(a["label_end"]), a["mature"]))
            created += 1
        elif not old["mature"] and a["mature"]:
            conn.execute("UPDATE labels SET churned = %s, mature = true WHERE cutoff_id = %s", (a["churned"], c["cutoff_id"]))
            matured += 1
        elif (old["churned"], old["mature"]) == (a["churned"], a["mature"]):
            unchanged += 1
        else:
            mismatched.append(c["cutoff_id"])
    warnings = []
    if censored:
        warnings.append(_warning("CENSORED_ROWS", f"{censored} row(s) have an immature label window: labelled unknown (null), excluded from evaluation", "result.censored"))
    result = {"prediction_at": iso_z(parse_ts(i.prediction_at)), "label_version": data["label_version"]["label_version_id"],
              "cutoff_rows": len(cutoffs), "eligible": mature + censored, "ineligible": dict(sorted(ineligible.items())), "created": created,
              "matured_now": matured, "unchanged": unchanged, "mismatched": mismatched, "mature": mature, "censored": censored, "churned": churned,
              "churn_rate": p6(ratio(churned, mature)),
              "label_rule": "churned = a cancel with prediction_at <= event_at < horizon_end and available_at < label_end; immature rows are null, never false"}
    return Outcome("labelled" if created or matured else "unchanged", result, warnings=warnings,
                   audit=Audit("label_set", result["prediction_at"], "define-label", details={"created": created, "matured_now": matured, "censored": censored}))


# --- C03 split-evaluation -------------------------------------------------------------------------------------------------

def split_evaluation(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """time ranges -> train / validation / test with the label-window purge and the group purge (P10-FLOW-03)."""
    i = req.input
    now = _now()
    train_end, validation_end, test_end = parse_ts(i.train_end), parse_ts(i.validation_end), parse_ts(i.test_end)
    if not train_end < validation_end < test_end:
        raise _invalid(E.SPLIT_ORDER_INVALID, "train_end < validation_end < test_end is required", "input.train_end")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("run:" + i.training_run_id,))
    data, world = _world(conn)
    fv = i.feature_version or data["feature_version_spec"]["feature_version"]
    lv = i.label_version or data["label_version"]["label_version_id"]
    if conn.execute("SELECT 1 FROM feature_versions WHERE feature_version = %s", (fv,)).fetchone() is None:
        raise _invalid("UNKNOWN_VERSION", f"feature version {fv!r} is not registered", "input.feature_version")
    if conn.execute("SELECT 1 FROM label_versions WHERE label_version_id = %s", (lv,)).fetchone() is None:
        raise _invalid("UNKNOWN_VERSION", f"label version {lv!r} is not registered", "input.label_version")
    row = conn.execute("SELECT * FROM training_runs WHERE training_run_id = %s FOR SHARE", (i.training_run_id,)).fetchone()
    if row is None:
        config = {"feature_version": fv, "label_version": lv, "seed": i.seed, "split": "chronological", "models": []}
        conn.execute("INSERT INTO training_runs (training_run_id, train_end, validation_end, test_end, config, config_hash, created_at, created_by) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (i.training_run_id, train_end, validation_end, test_end, Jsonb(config), config_hash(config),
                                                           now, actor.actor_id))
        created = True
    else:
        if (row["train_end"], row["validation_end"], row["test_end"]) != (train_end, validation_end, test_end):
            raise _conflict("TRAINING_RUN_EXISTS", f"training run {i.training_run_id!r} exists with other boundaries (a new split is a new run)",
                            "input.training_run_id")
        created = False
    run = {"training_run_id": i.training_run_id, "train_end": iso_z(train_end), "validation_end": iso_z(validation_end), "test_end": iso_z(test_end)}
    rows, counts = split_run(world, run)
    stored = {s["cutoff_id"]: s for s in data["split_assignments"] if s["training_run_id"] == i.training_run_id}
    inserted = 0
    stale: list[str] = []
    for r in rows:
        old = stored.get(r["cutoff_id"])
        if old is None:
            conn.execute("INSERT INTO split_assignments VALUES (%s,%s,%s,%s,%s,%s)",
                         (f"sa-{i.training_run_id}-{r['cutoff_id']}", i.training_run_id, r["cutoff_id"], r["split"], r["status"], r["drop_reason"]))
            inserted += 1
        elif (old["split"], old["status"], old["drop_reason"]) != (r["split"], r["status"], r["drop_reason"]):
            stale.append(r["cutoff_id"])
    warnings = []
    if stale:
        warnings.append(_warning("SPLIT_ASSIGNMENTS_STALE", "stored assignments differ from the rebuilt split (rows were added since); they are append-only", "result.stale"))
    result = {"training_run_id": i.training_run_id, "created": created, "train_end": run["train_end"], "validation_end": run["validation_end"],
              "test_end": run["test_end"], "embargo_days": world.horizon + world.grace, "counts": counts, "assignments_inserted": inserted, "stale": stale,
              "assignments": [{"cutoff_id": r["cutoff_id"], "split": r["split"], "status": r["status"], "drop_reason": r["drop_reason"]} for r in rows],
              "config_hash": row["config_hash"] if row else config_hash(config)}
    return Outcome("split" if created or inserted else "unchanged", result, warnings=warnings,
                   audit=Audit("training_run", i.training_run_id, "split-evaluation", details={"counts": counts, "created": created}))


# --- C04 fit-preprocessing -------------------------------------------------------------------------------------------------

def fit_preprocessing_command(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """training rows only -> a fitted transformer (P10-FLOW-04). Any other row is LEAKAGE."""
    i = req.input
    run = _lock_run(conn, i.training_run_id, exclusive=True)
    _require_unfrozen(conn, i.training_run_id)
    data, world = _world(conn)
    rows, _ = split_run(world, world.runs[i.training_run_id])
    train = retained(rows, "train")
    features, labels = _stored_rows(data)
    if i.fit_rows is not None:
        try:
            check_fit_rows(i.fit_rows, train)
        except DomainError as err:
            raise _domain(err, "input.fit_rows") from None
        ids = sorted(set(i.fit_rows))
    else:
        ids = sorted(c for c in train if c in features)
    missing = [c for c in ids if c not in features]
    if missing:
        raise _invalid(E.FEATURES_NOT_BUILT, "training rows without stored feature rows (run build-point-in-time-features first)", "input.fit_rows",
                       {"offending": [{"item": c, "code": E.FEATURES_NOT_BUILT} for c in missing]})
    if not ids:
        raise _invalid(E.NO_TRAINING_ROWS, "there is no retained training row with stored features", "input.fit_rows")
    try:
        pre = fit_preprocessing([features[c] for c in ids])
    except DomainError as err:
        raise _domain(err, "input.fit_rows") from None
    pre["fit_rows_sha256"] = sha256_hex(canon(ids))
    config = dict(run["config"])
    reset = bool(config.get("models") or config.get("calibration"))
    config["preprocessing"] = pre
    config["models"] = []
    config.pop("calibration", None)
    h = _save_config(conn, i.training_run_id, config)
    warnings = [_warning("MODELS_RESET", "models and calibration fitted on the previous preprocessing were discarded", "result")] if reset else []
    return Outcome("fitted", {"training_run_id": i.training_run_id, "fit_rows": len(ids), "preprocessing": pre, "config_hash": h,
                              "fitted_on": "retained training rows only"}, warnings=warnings,
                   audit=Audit("training_run", i.training_run_id, "fit-preprocessing", details={"fit_rows": len(ids), "config_hash": h}))


# --- C05 train-baseline ------------------------------------------------------------------------------------------------------

def train_baseline(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """training rows -> the random baseline, the business rule and the logistic regression (P10-FLOW-05). The simple references are kept."""
    i = req.input
    run = _lock_run(conn, i.training_run_id, exclusive=True)
    _require_unfrozen(conn, i.training_run_id)
    config = dict(run["config"])
    pre = config.get("preprocessing")
    if not pre:
        raise _invalid(E.PREPROCESSING_REQUIRED, "fit the preprocessing on the training rows first", "input.training_run_id")
    data, world = _world(conn)
    rows, _ = split_run(world, world.runs[i.training_run_id])
    features, labels = _stored_rows(data)
    train = _labelled(retained(rows, "train"), features, labels)
    if not train:
        raise _invalid(E.NO_TRAINING_ROWS, "there is no retained, mature, labelled training row (run define-label)", "input.training_run_id")
    try:
        models = train_models(pre, [(f, y) for _, f, y in train], i.random_seed, i.l2, i.iterations, i.learning_rate)
    except DomainError as err:
        raise _domain(err, "input.training_run_id") from None
    config["models"] = models
    config.pop("calibration", None)
    h = _save_config(conn, i.training_run_id, config)
    validation = _labelled(retained(rows, "validation"), features, labels)
    comparison = _validation_comparison(config, [(c, f, y) for c, f, y in validation])
    lr, rule, rnd_ = comparison["logistic_regression"], comparison["business_rule"], comparison["random_baseline"]
    beats = {"business_rule": _better(lr["average_precision"], rule["average_precision"], False) and _better(lr["brier_score"], rule["brier_score"], True),
             "random_baseline": _better(lr["average_precision"], rnd_["average_precision"], False) and _better(lr["brier_score"], rnd_["brier_score"], True),
             "prevalence_baseline": _better(lr["brier_score"], comparison["prevalence_baseline"]["brier_score"], True)}      # AP of a constant is the prevalence: Brier only
    warnings = [_warning("VALIDATION_ONLY", "the comparison uses validation rows; the test set is read once, by the final evaluation", "result.validation_comparison")]
    return Outcome("trained", {"training_run_id": i.training_run_id, "training_rows": len(train), "models": models, "config_hash": h,
                               "validation_comparison": comparison, "logistic_beats_references_on_validation": beats,
                               "coefficients_are_frozen_strings": True}, warnings=warnings,
                   audit=Audit("training_run", i.training_run_id, "train-baseline", details={"training_rows": len(train), "config_hash": h}))


# --- C06 calibrate-model ---------------------------------------------------------------------------------------------------

def calibrate_model(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """validation rows only -> a Platt mapping (P10-FLOW-06). The reliability curve is read on rows the calibration did not see."""
    i = req.input
    run = _lock_run(conn, i.training_run_id, exclusive=True)
    _require_unfrozen(conn, i.training_run_id)
    config = dict(run["config"])
    if not model_config(config, "logistic_regression") or "coefficients" not in (model_config(config, "logistic_regression") or {}):
        raise _invalid(E.MODEL_NOT_FITTED, "train the baseline models first", "input.training_run_id")
    data, world = _world(conn)
    rows, _ = split_run(world, world.runs[i.training_run_id])
    validation, test = retained(rows, "validation"), retained(rows, "test")
    features, labels = _stored_rows(data)
    fit_ids = list(i.fit_rows) if i.fit_rows is not None else sorted(c for c in validation if c in features and c in labels and labels[c]["mature"])
    evaluation_ids = list(i.evaluation_rows) if i.evaluation_rows is not None else sorted(test)
    try:
        check_calibration_rows(fit_ids, evaluation_ids, validation)
    except DomainError as err:
        raise _domain(err, "input.fit_rows") from None
    fit = _labelled(set(fit_ids), features, labels)
    if len(fit) != len(set(fit_ids)):
        bad = sorted(set(fit_ids) - {c for c, _, _ in fit})
        raise _invalid(E.NO_VALIDATION_ROWS, "calibration rows need a stored feature row and a mature label", "input.fit_rows",
                       {"offending": [{"item": c, "code": "NOT_LABELLED"} for c in bad]})
    try:
        cal = fit_platt([score_features(config, "logistic_regression", c, f, calibrated=False) for c, f, _ in fit], [y for _, _, y in fit])
    except DomainError as err:
        raise _domain(err, "input.fit_rows") from None
    cal["fit_rows"] = len(fit)
    cal["fit_rows_sha256"] = sha256_hex(canon(sorted(c for c, _, _ in fit)))
    config["calibration"] = cal
    h = _save_config(conn, i.training_run_id, config)
    return Outcome("calibrated", {"training_run_id": i.training_run_id, "method": "platt", "a": cal["a"], "b": cal["b"], "fit_rows": len(fit),
                                  "evaluation_rows": len(evaluation_ids), "evaluation_rows_overlap_fit_rows": 0, "test_rows_read": 0, "config_hash": h,
                                  "fitted_on": "retained validation rows only"},
                   audit=Audit("training_run", i.training_run_id, "calibrate-model", details={"fit_rows": len(fit), "config_hash": h}))


# --- C07 score-accounts ----------------------------------------------------------------------------------------------------

def score_accounts(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """frozen model -> probabilities (P10-FLOW-07). Each prediction cites the run, config_hash, feature_version and label_version; the
    first score freezes the run's configuration. The publication is completed when every eligible account of the set is scored."""
    i = req.input
    model = _model_name(i.model)
    now = _now()
    run = _lock_run(conn, i.training_run_id, exclusive=True)
    config = run["config"]
    if not model_config(config, model):
        raise _invalid(E.MODEL_NOT_FITTED, f"model {model!r} has not been trained for run {i.training_run_id!r}", "input.model")
    data, world = _world(conn, model)
    features, _ = _stored_rows(data)
    eligible = [r for r in world.set_rows(i.prediction_at) if r["eligible"]]
    if not world.set_rows(i.prediction_at):
        raise _not_found("input.prediction_at", E.UNKNOWN_CUTOFF, "cutoff set")
    if not eligible:
        raise _invalid(E.NOTHING_SCORED, "the cutoff set has no eligible account", "input.prediction_at")
    unbuilt = [r["cutoff_id"] for r in eligible if r["cutoff_id"] not in features]
    if unbuilt:
        raise _invalid(E.FEATURES_NOT_BUILT, "eligible accounts without stored feature rows (run build-point-in-time-features first)", "input.prediction_at",
                       {"offending": [{"item": c, "code": E.FEATURES_NOT_BUILT} for c in unbuilt]})
    pa = parse_ts(i.prediction_at)
    done = {r["cutoff_id"] for r in eligible if (i.training_run_id, r["cutoff_id"]) in world.preds}
    calibrated = model == "logistic_regression" and bool(config.get("calibration"))
    try:
        scores = {r["cutoff_id"]: score_features(config, model, r["cutoff_id"], features[r["cutoff_id"]]) for r in eligible if r["cutoff_id"] not in done}
    except DomainError as err:
        raise _domain(err, "input.model") from None
    for c, p in scores.items():
        conn.execute("INSERT INTO predictions (prediction_id, training_run_id, cutoff_id, model_name, probability, scored_at, config_hash, feature_version, "
                     "label_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (f"pr-{c}" if model == "logistic_regression" else f"pr-{model}-{c}", i.training_run_id, c, model, p, now, run["config_hash"],
                      config["feature_version"], config["label_version"]))
    scored_total = len(done) + len(scores)
    status = "completed" if scored_total == len(eligible) else "incomplete"
    pub_id = None
    if scores or not conn.execute("SELECT 1 FROM scoring_publications WHERE training_run_id = %s AND model_name = %s AND prediction_at = %s",
                                  (i.training_run_id, model, pa)).fetchone():
        n = conn.execute("SELECT count(*) AS n FROM scoring_publications WHERE training_run_id = %s AND model_name = %s AND prediction_at = %s",
                         (i.training_run_id, model, pa)).fetchone()["n"]
        pub_id = f"sp-{i.training_run_id}-{model}-{pa.strftime('%Y%m%d')}-{n + 1}"
        conn.execute("INSERT INTO scoring_publications (publication_id, training_run_id, model_name, prediction_at, published_at, status) VALUES (%s,%s,%s,%s,%s,%s)",
                     (pub_id, i.training_run_id, model, pa, now, status))
    citations = {"training_run_id": i.training_run_id, "config_hash": run["config_hash"], "feature_version": config["feature_version"],
                 "label_version": config["label_version"], "model": model}
    result = {"publication_id": pub_id, "status": status, "prediction_at": iso_z(pa), "eligible": len(eligible), "scored": scored_total, "new": len(scores),
              "already_scored": len(done), "calibrated": calibrated, "citations": citations, "run_frozen": True,
              "predictions": [{"cutoff_id": c, "probability": p, **citations} for c, p in sorted(scores.items())]}
    return Outcome("scored" if scores else "unchanged", result,
                   audit=Audit("training_run", i.training_run_id, "score-accounts", details={"model": model, "new": len(scores), "publication_id": pub_id, "status": status}))


# --- scenarios and the queue ----------------------------------------------------------------------------------------------

def _ensure_scenario(conn: Conn, i: Any, actor: Actor, now: datetime) -> str:
    """Lock order step 3. An inline scenario is created if new and must equal the stored one otherwise (a scenario is immutable: an
    edit is a new scenario_id); a scenario_id alone must exist."""
    if i.scenario is None and i.scenario_id is None:
        raise _invalid(E.SCENARIO_INVALID, "name a scenario_id or declare a scenario", "input.scenario_id")
    if i.scenario is not None:
        s = i.scenario
        if i.scenario_id is not None and i.scenario_id != s.scenario_id:
            raise _invalid(E.SCENARIO_INVALID, "scenario_id and scenario.scenario_id differ", "input.scenario_id")
        if s.selected_on != "validation":
            try:
                check_threshold("capacity", s.selected_on)
            except DomainError as err:
                raise _domain(err, "input.scenario.selected_on") from None
        if Fraction(s.assumed_effect) > 1:
            raise _domain(DomainError(E.ASSUMED_EFFECT_OUT_OF_RANGE, "assumed_effect is the assumed share of churn risk an intervention removes, in [0, 1]",
                                      "input.scenario.assumed_effect"), "input.scenario.assumed_effect")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("scenario:" + s.scenario_id,))
        old = conn.execute("SELECT * FROM intervention_scenarios WHERE scenario_id = %s FOR SHARE", (s.scenario_id,)).fetchone()
        if old is None:
            conn.execute("INSERT INTO intervention_scenarios (scenario_id, capacity, contact_cost, assumed_effect, margin_value, created_at, created_by) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s)", (s.scenario_id, s.capacity, s.contact_cost, s.assumed_effect, s.margin_value, now, actor.actor_id))
        elif (old["capacity"], old["contact_cost"], old["assumed_effect"], old["margin_value"]) != (
                s.capacity, Decimal(s.contact_cost), Decimal(s.assumed_effect), Decimal(s.margin_value)):
            raise _domain(DomainError(E.SCENARIO_IMMUTABLE, f"scenario {s.scenario_id!r} exists with other assumptions; an edit is a new scenario_id",
                                      "input.scenario"), "input.scenario")
        return s.scenario_id
    row = conn.execute("SELECT 1 FROM intervention_scenarios WHERE scenario_id = %s FOR SHARE", (i.scenario_id,)).fetchone()
    if row is None:
        raise _not_found("input.scenario_id", E.UNKNOWN_SCENARIO, "scenario")
    return i.scenario_id


def _pool(world: World, run_id: str, prediction_at: str) -> list[dict[str, Any]]:
    """The scored eligible rows of a set, ranked: probability descending, ties by account_id (D-P10-03). Censored rows are included."""
    if not world.set_rows(prediction_at):
        raise _not_found("input.prediction_at", E.UNKNOWN_CUTOFF, "cutoff set")
    pool = [{"p": Fraction(world.preds[(run_id, r["cutoff_id"])]["probability"]), "pstr": world.preds[(run_id, r["cutoff_id"])]["probability"],
             "account_id": r["account_id"], "cutoff_id": r["cutoff_id"]} for r in world.set_rows(prediction_at)
            if r["eligible"] and (run_id, r["cutoff_id"]) in world.preds]
    return sorted(pool, key=rank_key)


def prioritize_outreach(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """scores -> a capacity-limited DRAFT queue (P10-FLOW-08). K may not exceed the scored eligible population. Nothing is ever sent, and
    a high risk is not treatment responsiveness: a request that claims it is refused."""
    i = req.input
    model = _model_name(i.model)
    now = _now()
    if i.basis != "risk_ranking":
        raise _domain(DomainError(E.RISK_NOT_RESPONSIVENESS, "churn risk ranks who may leave; it does not say who responds to an offer (basis must be 'risk_ranking')",
                                  "input.basis", {"offending": [{"item": i.basis, "code": "BASIS_NOT_RISK_RANKING"}]}), "input.basis")
    _lock_run(conn, i.training_run_id)
    scenario_id = _ensure_scenario(conn, i, actor, now)
    data, world = _world(conn, model)
    pool = _pool(world, i.training_run_id, i.prediction_at)
    scenario = world.scenarios[scenario_id]
    try:
        check_capacity(scenario_id, scenario["capacity"], len(pool))
    except DomainError as err:
        raise _domain(err, "input.capacity") from None
    if conn.execute("SELECT 1 FROM outreach_events WHERE scenario_id = %s LIMIT 1", (scenario_id,)).fetchone():
        raise _domain(DomainError(E.QUEUE_EXISTS, f"scenario {scenario_id!r} already has an outreach queue (a different queue is a new scenario)",
                                  "input.scenario_id"), "input.scenario_id")
    queue = pool[:scenario["capacity"]]
    pa = parse_ts(i.prediction_at)
    for rank, q in enumerate(queue, 1):
        conn.execute("INSERT INTO outreach_events (outreach_event_id, account_id, scenario_id, action, status, training_run_id, prediction_at, queue_rank, created_at) "
                     "VALUES (%s,%s,%s,%s,'draft',%s,%s,%s,%s)", (f"oe-{scenario_id}-{rank:04d}", q["account_id"], scenario_id, "propose_contact",
                                                                   i.training_run_id, pa, rank, now))
    warnings = [_warning("RISK_IS_NOT_RESPONSIVENESS", "the queue ranks churn risk only; it supplies no estimate of who would respond to an intervention", "result"),
                _warning("DRAFT_ONLY", "every action is a draft; nothing is sent by this product", "result.queue_status")]
    return Outcome("queued", {"scenario_id": scenario_id, "training_run_id": i.training_run_id, "prediction_at": iso_z(pa), "model": model,
                              "capacity": scenario["capacity"], "population": len(pool), "queue_status": "draft", "sent": 0,
                              "treatment_effect_estimate": None,
                              "queue": [{"rank": r, "account_id": q["account_id"], "cutoff_id": q["cutoff_id"], "probability": q["pstr"], "status": "draft"}
                                        for r, q in enumerate(queue, 1)]}, warnings=warnings,
                   audit=Audit("scenario", scenario_id, "prioritize-outreach", details={"queued": len(queue), "population": len(pool), "status": "draft"}))


def simulate_economics(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """queue + assumptions -> expected value (P10-FLOW-09). Hypothetical and assumption-based, labelled so; the ranking supplies no
    treatment effect."""
    i = req.input
    model = _model_name(i.model)
    now = _now()
    _lock_run(conn, i.training_run_id)
    scenario_id = _ensure_scenario(conn, i, actor, now)
    data, world = _world(conn, model)
    pool = _pool(world, i.training_run_id, i.prediction_at)
    scenario = world.scenarios[scenario_id]
    try:
        check_capacity(scenario_id, scenario["capacity"], len(pool))
    except DomainError as err:
        raise _domain(err, "input.capacity") from None
    out = economics(scenario, pool[:scenario["capacity"]])
    out.update({"training_run_id": i.training_run_id, "prediction_at": iso_z(parse_ts(i.prediction_at)), "model": model, "population": len(pool),
                "experiment_id": i.experiment_id, "supported_by_randomised_experiment": False,
                "disclosure": "Hypothetical: assumption-based expected value; a randomised experiment, designed separately, would be needed to support the effect."})
    warnings = [_warning("HYPOTHETICAL", "the expected value follows from the declared assumptions, not from evidence of a treatment effect", "result.expected_value")]
    return Outcome("simulated", out, warnings=warnings,
                   audit=Audit("scenario", scenario_id, "simulate-economics", details={"expected_value": out["expected_value"], "label": "hypothetical"}))


def monitor_refresh(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """new cohort -> drift and performance checks (P10-FLOW-10). Labels arrive later: performance is reported only on mature rows and the
    immature count is shown; drift, missingness and freshness do not need labels."""
    i = req.input
    model = _model_name(i.model)
    _lock_run(conn, i.training_run_id)
    data, world = _world(conn, model)
    if not world.set_rows(i.prediction_at):
        raise _not_found("input.prediction_at", E.UNKNOWN_CUTOFF, "cutoff set")
    if not world.set_rows(i.reference_prediction_at):
        raise _not_found("input.reference_prediction_at", E.UNKNOWN_CUTOFF, "reference cohort")
    drift = {"feature": i.feature or DEFAULT_DRIFT["feature"], "bins": i.bins or DEFAULT_DRIFT["bins"],
             "reference_prediction_at": iso_z(parse_ts(i.reference_prediction_at)), "floor": i.floor, "threshold": i.threshold}
    if drift["feature"] not in FEATURES:
        raise _invalid(E.UNKNOWN_FEATURE, f"{drift['feature']!r} is not a registered feature", "input.feature")
    try:
        for b in drift["bins"]:
            if set(b) != {"label", "lower", "upper"} or not isinstance(b["label"], str):
                raise ValueError
            Fraction(str(b["lower"]))
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        raise _invalid(E.INVALID_BINS, "bins are {label, lower, upper} with a numeric lower and an upper (null for open)", "input.bins") from None
    pa = iso_z(parse_ts(i.prediction_at))
    m = set_metrics(world, i.training_run_id, pa, None, drift)
    pubs = publications(world)
    pop = m["population"]
    performance = None
    if pop["evaluated"]:
        performance = {"n": pop["evaluated"], "churn_rate": m["churn_rate"], "average_precision": m["average_precision"], "brier_score": m["brier_score"]}
    result = {"training_run_id": i.training_run_id, "prediction_at": pa, "model": model, "population": pop, "immature": pop["censored"],
              "performance_reported": performance is not None, "performance": performance, "population_drift": m["population_drift"],
              "feature_missingness": m["feature_missingness"], "late_events": m["late_events"], "freshness": freshness(world, pubs)}
    warnings = []
    if pop["censored"]:
        warnings.append(_warning("LABELS_PENDING", f"{pop['censored']} eligible row(s) have no mature label yet; performance excludes them", "result.immature"))
    if m["population_drift"] and m["population_drift"]["exceeds_threshold"]:
        warnings.append(_warning("DRIFT_DIAGNOSTIC", "PSI is above the declared threshold: a diagnostic, not proof of model failure", "result.population_drift"))
    return Outcome("monitored", result, warnings=warnings,
                   audit=Audit("training_run", i.training_run_id, "monitor-refresh", details={"prediction_at": pa, "evaluated": pop["evaluated"], "immature": pop["censored"]}))
