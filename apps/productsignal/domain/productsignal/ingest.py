"""Ingest: validate a batch of raw rows (D-03/D-05 rejection codes, dependent rejection, merge of idempotent repeats).

Every row is accepted, rejected (reason code, raw row kept) or, for an idempotent repeat, merged. The order of checks for
assignments, exposures and observations follows ``tests/reference_check.py`` for the fixtures; codes the contract does not
list (MALFORMED_RECORD, DUPLICATE_ID, UNKNOWN_*, INVALID_INTERVAL, IDENTITY_CONFLICT, UNSUPPORTED_UNIT_TYPE) are the
backend's assumptions and are listed in README.md.

Events are an immutable log: a row is accepted once well formed. De-duplication, the received-by-cutoff rule, unknown
identity and exclusions are decided per run in ``events.canonicalise`` (they depend on the cutoff), not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .contract import ENTITIES
from .errors import (ASSIGNMENT_CONFLICT, DEPENDENT_REJECTED, DUPLICATE_ID, EXPOSURE_BEFORE_ASSIGNMENT, IDENTITY_CONFLICT, INELIGIBLE_UNIT,
                     INVALID_INTERVAL, MALFORMED_RECORD, UNKNOWN_ACCOUNT, UNKNOWN_ASSIGNMENT, UNKNOWN_EVENT,
                     UNKNOWN_EXPERIMENT_VERSION, UNKNOWN_UNIT, UNKNOWN_USER, UNKNOWN_VARIANT, UNSUPPORTED_UNIT_TYPE,
                     DomainError)
from .models import ID_KEYS, PARSERS, Plan, Population

Row = dict[str, Any]


@dataclass(frozen=True)
class Rejection:
    entity: str
    id: str
    reason_code: str
    raw_row: Row
    message: str = ""

    def as_dict(self) -> Row:
        return {"entity": self.entity, "id": self.id, "status": "rejected", "reason_code": self.reason_code,
                "raw_row": self.raw_row}


@dataclass
class IngestResult:
    accepted: dict[str, list[Any]]                  # typed records by entity (events: every well-formed log row)
    accepted_rows: dict[str, list[Row]]             # the same rows as given
    rejected: list[Rejection]
    merged: dict[str, int]                          # idempotent repeats per entity
    merged_assignments: dict[str, str]              # repeated assignment id -> the id that fixed the variant
    counts: dict[str, dict[str, int]]

    def rejected_dicts(self) -> list[Row]:
        return [r.as_dict() for r in self.rejected]

    def population(self, plans: dict[str, Plan] | None = None, **kw: Any) -> Population:
        return Population(**{e: list(self.accepted[e]) for e in ENTITIES}, plans=dict(plans or {}), **kw)


def _rid(row: Any, key: str) -> str:
    v = row.get(key) if isinstance(row, dict) else None
    return v if isinstance(v, str) else ""


def validate_batch(raw: dict[str, Any], plans: dict[str, Plan] | None = None) -> IngestResult:
    """Validate an inputs object (the shape of ``tests/fixtures/golden/inputs.json``). ``plans`` (by experiment version id)
    lets an assignment to a variant the plan does not name be rejected."""
    plans = plans or {}
    rej: list[Rejection] = []
    acc: dict[str, list[Any]] = {e: [] for e in ENTITIES}
    rows: dict[str, list[Row]] = {e: [] for e in ENTITIES}
    ids: dict[str, dict[str, Any]] = {e: {} for e in ENTITIES}      # accepted id -> typed record
    rejected_ids: dict[str, set[str]] = {e: set() for e in ENTITIES}
    merged = {e: 0 for e in ENTITIES}
    seen: dict[str, dict[str, Row]] = {e: {} for e in ENTITIES}      # every well-formed row by id (take() runs after sorting)

    def reject(ent: str, row: Any, code: str, msg: str = "") -> None:
        rid = _rid(row, ID_KEYS[ent])
        if rid:
            rejected_ids[ent].add(rid)
        rej.append(Rejection(ent, rid, code, row if isinstance(row, dict) else {"value": repr(row)}, msg))

    def section(ent: str) -> list[Any]:
        v = raw.get(ent, [])
        return v if isinstance(v, list) else []

    def parsed(ent: str, row: Any) -> Any | None:
        """Parse + duplicate-id check; on failure the rejection is recorded and None returned."""
        if not isinstance(row, dict):
            reject(ent, row, MALFORMED_RECORD, "row must be an object")
            return None
        try:
            obj = PARSERS[ent](row)
        except DomainError as err:
            reject(ent, row, err.code, err.message)
            return None
        rid = row[ID_KEYS[ent]]
        if rid in seen[ent]:
            if row == seen[ent][rid]:
                merged[ent] += 1                    # the same row sent twice is idempotent, not an error
            else:
                reject(ent, row, DUPLICATE_ID, f"{ID_KEYS[ent]} already loaded with different content")
            return None
        seen[ent][rid] = row
        return obj

    def take(ent: str, row: Row, obj: Any) -> None:
        ids[ent][row[ID_KEYS[ent]]] = obj
        acc[ent].append(obj)
        rows[ent].append(row)

    for r in section("accounts"):
        if (o := parsed("accounts", r)) is not None:
            take("accounts", r, o)
    for r in section("users"):
        if (o := parsed("users", r)) is None:
            continue
        if o.account_id not in ids["accounts"]:
            reject("users", r, UNKNOWN_ACCOUNT)
        else:
            take("users", r, o)
    link_rows = [r for r in section("identity_links")]
    ok_links = []
    for r in link_rows:
        if (o := parsed("identity_links", r)) is None:
            continue
        if o.user_id not in ids["users"]:
            reject("identity_links", r, UNKNOWN_USER)
        else:
            ok_links.append((o, r))
    linked: set[str] = set()
    first_user: dict[str, str] = {}                  # the earliest link of an anonymous_id fixes its user (D-01)
    for o, r in sorted(ok_links, key=lambda t: (t[0].linked_at, t[0].identity_link_id)):
        if first_user.setdefault(o.anonymous_id, o.user_id) != o.user_id:
            reject("identity_links", r, IDENTITY_CONFLICT, "this anonymous_id is already linked to another user")
        elif o.anonymous_id in linked:
            merged["identity_links"] += 1           # a later link of the same pair adds nothing: the earliest one counts
        else:
            linked.add(o.anonymous_id)
            take("identity_links", r, o)
    for r in section("sessions"):
        if (o := parsed("sessions", r)) is None:
            continue
        if o.user_id not in ids["users"]:
            reject("sessions", r, UNKNOWN_USER)
        elif o.ended_at is not None and o.ended_at < o.started_at:
            reject("sessions", r, INVALID_INTERVAL, "ended_at is before started_at")
        else:
            take("sessions", r, o)
    for r in section("events"):
        if (o := parsed("events", r)) is not None:
            take("events", r, o)
    seen_keys: set[tuple[str, str]] = set()
    for r in section("event_properties"):
        if (o := parsed("event_properties", r)) is None:
            continue
        if o.event_id in rejected_ids["events"] and o.event_id not in ids["events"]:
            reject("event_properties", r, DEPENDENT_REJECTED)
        elif o.event_id not in ids["events"]:
            reject("event_properties", r, UNKNOWN_EVENT)
        elif (o.event_id, o.property_key) in seen_keys:
            reject("event_properties", r, DUPLICATE_ID, "this event already carries the property")
        else:
            seen_keys.add((o.event_id, o.property_key))
            take("event_properties", r, o)
    for r in section("subscriptions"):
        if (o := parsed("subscriptions", r)) is None:
            continue
        if o.account_id not in ids["accounts"]:
            reject("subscriptions", r, UNKNOWN_ACCOUNT)
        elif o.ends_at is not None and o.ends_at < o.starts_at:
            reject("subscriptions", r, INVALID_INTERVAL, "ends_at is before starts_at")
        else:
            take("subscriptions", r, o)
    for r in section("experiment_versions"):
        if (o := parsed("experiment_versions", r)) is None:
            continue
        if o.unit_type != "account":
            reject("experiment_versions", r, UNSUPPORTED_UNIT_TYPE, "the unit of randomisation is the account")
        else:
            take("experiment_versions", r, o)

    # --- assignments: processed in (assigned_at, assignment_id) order; the first per (version, unit) wins (D-03) -----------
    cand = []
    for r in section("assignments"):
        if (o := parsed("assignments", r)) is None:
            continue
        plan = plans.get(o.experiment_version_id)
        if o.experiment_version_id not in ids["experiment_versions"]:
            reject("assignments", r, UNKNOWN_EXPERIMENT_VERSION)
        elif o.unit_id not in ids["accounts"]:
            reject("assignments", r, UNKNOWN_UNIT, "the unit of randomisation is an account that exists")
        elif ids["accounts"][o.unit_id].internal:
            reject("assignments", r, INELIGIBLE_UNIT, "internal accounts are not randomised (decided before assignment)")
        elif plan is not None and o.variant not in plan.allocation:
            reject("assignments", r, UNKNOWN_VARIANT, f"the plan names {', '.join(plan.allocation)}")
        else:
            cand.append((o, r))
    first_by_unit: dict[tuple[str, str], Any] = {}
    merged_into: dict[str, str] = {}
    for o, r in sorted(cand, key=lambda t: (t[0].assigned_at, t[0].assignment_id)):
        first = first_by_unit.get((o.experiment_version_id, o.unit_id))
        if first is None:
            first_by_unit[(o.experiment_version_id, o.unit_id)] = o
            take("assignments", r, o)
        elif first.variant == o.variant:
            merged["assignments"] += 1
            merged_into[o.assignment_id] = first.assignment_id
        else:
            reject("assignments", r, ASSIGNMENT_CONFLICT, "the first assignment of a unit fixes its variant")
    accepted_asg = ids["assignments"]
    rejected_asg = rejected_ids["assignments"] - set(accepted_asg) - set(merged_into)

    def resolve(ent: str, o: Any, r: Row) -> Any | None:
        """The accepted assignment an exposure or observation refers to, or None after recording why not."""
        aid = o.assignment_id
        if aid in merged_into:
            aid = merged_into[aid]
        if aid in accepted_asg:
            return accepted_asg[aid]
        reject(ent, r, DEPENDENT_REJECTED if aid in rejected_asg else UNKNOWN_ASSIGNMENT)
        return None

    exposed: set[str] = set()
    expo = []
    for r in section("exposures"):
        if (o := parsed("exposures", r)) is not None:
            expo.append((o, r))
    for o, r in sorted(expo, key=lambda t: (t[0].exposed_at, t[0].exposure_id)):
        a = resolve("exposures", o, r)
        if a is None:
            continue
        if o.exposed_at < a.assigned_at:
            reject("exposures", r, EXPOSURE_BEFORE_ASSIGNMENT, "an exposure cannot precede its assignment")
        elif a.assignment_id in exposed:
            merged["exposures"] += 1                # a unit is exposed once; later exposures add nothing
        else:
            exposed.add(a.assignment_id)
            o = o.__class__(**{**o.__dict__, "assignment_id": a.assignment_id})
            take("exposures", r, o)
    observed: dict[tuple[str, str], Any] = {}
    for r in section("metric_observations"):
        if (o := parsed("metric_observations", r)) is None:
            continue
        if (a := resolve("metric_observations", o, r)) is None:
            continue
        o = o.__class__(**{**o.__dict__, "assignment_id": a.assignment_id})
        prior = observed.get((o.assignment_id, o.metric_name))
        if prior is None:
            observed[(o.assignment_id, o.metric_name)] = o
            take("metric_observations", r, o)
        elif (prior.value, prior.window_end) == (o.value, o.window_end):
            merged["metric_observations"] += 1
        else:
            reject("metric_observations", r, DUPLICATE_ID, "the unit already has a different observation of this metric")
    for r in section("analysis_runs"):
        if (o := parsed("analysis_runs", r)) is None:
            continue
        if o.experiment_version_id not in ids["experiment_versions"]:
            reject("analysis_runs", r, UNKNOWN_EXPERIMENT_VERSION)
        else:
            take("analysis_runs", r, o)

    rej.sort(key=lambda r: (r.entity, r.id))
    counts = {e: {"accepted": len(acc[e]), "rejected": sum(1 for r in rej if r.entity == e), "merged": merged[e]} for e in ENTITIES}
    return IngestResult(acc, rows, rej, merged, merged_into, counts)
