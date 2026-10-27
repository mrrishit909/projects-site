"""Import validation (D-P9-01): parents first; per record: shape, duplicate id, foreign keys (``UNKNOWN_*`` / ``DEPENDENT_REJECTED``), then the
business rules. A rejection is a whole record with its reason code and details; the valid records around it are unaffected, and a repeat of
an accepted record rejects the *later* one. Nothing is silently dropped.

``Validator`` is also what the API commands use to check one new row against the rows already stored (``check`` does not change state).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction as F
from typing import Any, Callable

from .contract import (BASES, BENEFIT_TYPES, COST_BASES, DEPENDENCY_TYPES, DIMENSIONS, ENTITIES, FOREIGN_KEYS, ID_FIELD,
                       IMPACT_LEVELS, INITIATIVE_STATUSES, MAX_HORIZON, MAX_PERIOD, SCENARIO_STATUSES, CAPACITY_RATE_NAME, CONVERSION_NAME,
                       RAMP_NAME)
from .numbers import dec, is_decimal, money
from .timeutil import check_period_start, is_ts, parse_ts

Row = dict[str, Any]
INT_LIMIT = 2_000_000_000


@dataclass
class Population:
    """The accepted rows of every entity plus the dataset configuration (period basis, period start, default as_of)."""
    config: dict[str, Any]
    acc: dict[str, list[Row]] = field(default_factory=lambda: {e: [] for e in ENTITIES})
    #: versions of an initiative's baseline that were approved (history); the initiative row names the current one
    approvals: list[Row] = field(default_factory=list)

    def total(self) -> int:
        return sum(len(v) for v in self.acc.values())


@dataclass
class Rejection:
    entity: str
    id: Any
    reason_code: str
    details: dict[str, Any]
    raw_row: Any

    def record(self) -> dict[str, Any]:
        item: dict[str, Any] = {"entity": self.entity, "id": self.id, "status": "rejected", "reason_code": self.reason_code}
        if self.details:
            item["details"] = self.details
        item["raw_row"] = self.raw_row
        return item


# ------------------------------------------------------------------------------------------------------------------------- shapes
def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and abs(v) <= INT_LIMIT


def _name(v: Any) -> bool:
    return isinstance(v, str) and 0 < len(v.strip()) and len(v) <= 2000


KINDS: dict[str, Callable[[Any], bool]] = {
    "id": lambda v: isinstance(v, str) and 0 < len(v) <= 128 and v == v.strip() and "\x00" not in v,
    "name": _name,
    "text": lambda v: isinstance(v, str) and len(v) <= 2000 and "\x00" not in v,
    "int": _is_int,
    "dec": is_decimal,
    "ts": is_ts,
    "bool": lambda v: isinstance(v, bool),
    "ids": lambda v: isinstance(v, list) and len(v) <= 500 and all(KINDS["id"](x) for x in v),
    "decs": lambda v: isinstance(v, list) and 0 < len(v) <= 1200 and all(is_decimal(x) for x in v),
}


def _spec(s: str) -> dict[str, str]:
    return dict(p.split(":") for p in s.split())


#: field:kind, a trailing ``?`` allows null
SHAPES: dict[str, dict[str, str]] = {e: _spec(s) for e, s in {
    "initiatives": "initiative_id:id title:name sponsor_id:id status:text baseline_version:id? requested_start_period:int duration_periods:int "
                   "deployment_period:int eligibility_rule_version:id",
    "process_baselines": "baseline_id:id initiative_id:id baseline_version:id volume:int minutes_per_case:int error_rate:dec evidence_ref:text "
                         "measured_at:ts reason:text?",
    "assumption_versions": "assumption_id:id initiative_id:id? name:name version_number:int value:dec? values:decs? unit:text? rationale:text "
                           "author_id:text evidence_ref:text? staffing_change_evidence_ref:text? created_at:ts",
    "resources": "resource_id:id name:name capacity_per_period:dec unit:name",
    "scenario_versions": "scenario_id:id baseline_version:id discount_rate:dec rate_basis:text rate_conversion_assumption_id:id? horizon_periods:int "
                         "status:text initiative_ids:ids pinned_assumption_ids:ids created_at:ts",
    "cost_items": "cost_id:id initiative_id:id cost_key:id cost_type:text cost_basis:text amount:dec period_index:int? start_period:int? "
                  "end_period:int? baseline_version:id?",
    "benefit_items": "benefit_id:id initiative_id:id benefit_type:text amount:dec period_index:int starts_period:int unit:text cash_realisation:bool? "
                     "evidence_ref:text? benefit_source_key:text? baseline_trend_per_period:dec?",
    "dependencies": "dependency_id:id initiative_id:id prerequisite_id:id dependency_type:text lag_periods:int",
    "stakeholder_groups": "group_id:id group_name:name owner_id:id affected_count:int impact_level:text",
    "impact_mappings": "mapping_id:id initiative_id:id group_id:id operating_change:text impact_level:text",
    "resource_allocations": "allocation_id:id resource_id:id initiative_id:id period_index:int amount:dec",
    "readiness_assessments": "assessment_id:id group_id:id dimension:text score:int weight:dec assessed_at:ts",
    "adoption_observations": "observation_id:id initiative_id:id eligible_count:int adopted_count:int observed_at:ts eligibility_rule_version:id",
    "training_completions": "training_id:id initiative_id:id eligible_trainees:int completed:int recorded_at:ts eligibility_rule_version:id",
    "benefit_observations": "benefit_observation_id:id benefit_id:id measured_value:dec evidence_ref:text observed_at:ts",
    "risk_items": "risk_id:id initiative_id:id probability:dec impact:dec mitigation:text",
    "forecast_versions": "forecast_id:id initiative_id:id version_number:int period_index:int amount:dec reason:text created_at:ts",
}.items()}


#: Server-stamped instants (R9-01, R9-11): absent on the rows of a loaded world (they then count from the start of time / equal the event time), present on
#: every row the API writes. ``recorded_at`` of a plan row is when it was entered; of an observation, when it was recorded (as opposed to when it happened).
OPTIONAL_TS: dict[str, tuple[str, ...]] = {"cost_items": ("recorded_at",), "benefit_items": ("recorded_at",), "adoption_observations": ("recorded_at",),
                                           "benefit_observations": ("recorded_at",), "training_completions": ("entered_at",)}


def has_text(v: Any) -> bool:
    """A non-blank string (Python ``strip()`` whitespace): the test every evidence reference passes (R9-04)."""
    return isinstance(v, str) and bool(v.strip())


def shape_problems(entity: str, row: Any) -> dict[str, str]:
    """Fields that are missing, null where not allowed, or of the wrong type / format (empty when the row is well formed)."""
    if not isinstance(row, dict):
        return {"$": "a record must be an object"}
    bad: dict[str, str] = {}
    for name in OPTIONAL_TS.get(entity, ()):
        if name in row and row[name] is not None and not is_ts(row[name]):
            bad[name] = "not a valid ts"
    for name, kind in SHAPES[entity].items():
        nullable = kind.endswith("?")
        check = KINDS[kind.rstrip("?")]
        if name not in row:
            bad[name] = "missing"
        elif row[name] is None:
            if not nullable:
                bad[name] = "null not allowed"
        elif not check(row[name]):
            bad[name] = f"not a valid {kind.rstrip('?')}"
    return bad


# ------------------------------------------------------------------------------------------------------------------------- validator
class Validator:
    """Accepted rows so far plus the checks. ``add`` = ``check`` then record; ``check`` never changes state."""

    def __init__(self, population: Population | None = None, config: dict[str, Any] | None = None) -> None:
        self.pop = population or Population(config or {"period_basis": "annual", "period_start": "2026-01-01", "as_of": None})
        self.acc = self.pop.acc
        self.ids: dict[str, set[str]] = {e: {r[ID_FIELD[e]] for r in self.acc[e]} for e in ENTITIES}
        self.rejected_ids: dict[str, set[str]] = {e: set() for e in ENTITIES}

    # -- public
    def check(self, entity: str, row: Any) -> Rejection | None:
        rid = row.get(ID_FIELD[entity]) if isinstance(row, dict) else None
        problems = shape_problems(entity, row)
        if problems:
            return Rejection(entity, rid if isinstance(rid, (str, int)) else None, "MALFORMED_RECORD", {"fields": problems}, row)
        if rid in self.ids[entity]:
            return Rejection(entity, rid, "DUPLICATE_ID", {}, row)
        for fld, parent, unknown, nullable, is_list in FOREIGN_KEYS.get(entity, []):
            for v in (row[fld] if is_list else [row[fld]]):
                if v is None and nullable:
                    continue
                if v in self.ids[parent]:
                    continue
                code = "DEPENDENT_REJECTED" if v in self.rejected_ids[parent] else unknown
                return Rejection(entity, rid, code, {}, row)      # the expected records carry no details for a key problem
        res = self._rule(entity, row)
        if res:
            return Rejection(entity, rid, res[0], res[1], row)
        return None

    def add(self, entity: str, row: Row) -> Rejection | None:
        rej = self.check(entity, row)
        if rej is None:
            self.accept(entity, row)
        elif rej.reason_code not in ("DUPLICATE_ID", "MALFORMED_RECORD"):
            self.rejected_ids[entity].add(rej.id)
        return rej

    def accept(self, entity: str, row: Row) -> None:
        self.acc[entity].append(row)
        self.ids[entity].add(row[ID_FIELD[entity]])

    # -- helpers
    def _initiative(self, iid: str) -> Row:
        return next(i for i in self.acc["initiatives"] if i["initiative_id"] == iid)

    def conversion_exists(self, iid: str) -> bool:
        return any(a["initiative_id"] == iid and a["name"] == CAPACITY_RATE_NAME and has_text(a.get("staffing_change_evidence_ref"))
                   for a in self.acc["assumption_versions"])

    def cycle_from(self, a: str, b: str) -> list[str] | None:
        """A path b -> ... -> a over accepted prerequisite edges (initiative -> prerequisite); the cycle that adding a -> b would close."""
        edges: dict[str, list[str]] = {}
        for d in self.acc["dependencies"]:
            edges.setdefault(d["initiative_id"], []).append(d["prerequisite_id"])
        stack = [(b, [b])]
        seen: set[str] = set()
        while stack:
            node, path = stack.pop()
            if node == a:
                return [a] + path
            if node in seen:
                continue
            seen.add(node)
            for nxt in sorted(edges.get(node, []), reverse=True):
                stack.append((nxt, path + [nxt]))
        return None

    # -- business rules (after the key checks); returns (code, details) or None
    def _rule(self, e: str, r: Row) -> tuple[str, dict[str, Any]] | None:
        acc = self.acc
        if e == "initiatives":
            if r["status"] not in INITIATIVE_STATUSES:
                return "STATUS_NOT_ALLOWED", {"status": r["status"]}
            if not (0 <= r["requested_start_period"] <= MAX_PERIOD and 0 <= r["deployment_period"] <= MAX_PERIOD):
                return "INVALID_PERIOD", {}
            if not 1 <= r["duration_periods"] <= MAX_PERIOD:
                return "INVALID_DURATION", {"duration_periods": r["duration_periods"]}
        elif e == "process_baselines":
            if r["volume"] < 0 or r["minutes_per_case"] < 0:
                return "INVALID_AMOUNT", {}
            if not 0 <= dec(r["error_rate"]) <= 1:
                return "INVALID_FIELD", {"field": "error_rate", "reason": "a proportion in [0, 1]"}
            if not r["evidence_ref"].strip():
                return "EVIDENCE_REQUIRED", {"field": "evidence_ref"}
            for b in acc[e]:
                if (b["initiative_id"], b["baseline_version"]) == (r["initiative_id"], r["baseline_version"]):
                    ini = self._initiative(r["initiative_id"])
                    if ini["baseline_version"] == r["baseline_version"]:
                        return "BASELINE_FROZEN", {"baseline_version": r["baseline_version"], "existing_id": b["baseline_id"]}
                    return "VERSION_EXISTS", {"existing_id": b["baseline_id"], "baseline_version": r["baseline_version"]}
        elif e == "assumption_versions":
            if r["version_number"] < 1:
                return "INVALID_VERSION", {}
            if not r["rationale"].strip():
                return "RATIONALE_REQUIRED", {}
            if not r["author_id"].strip():
                return "AUTHOR_REQUIRED", {}
            for fld in ("evidence_ref", "staffing_change_evidence_ref"):
                if r[fld] is not None and not r[fld].strip():
                    return "EVIDENCE_REQUIRED", {"field": fld}
            if (r["value"] is None) == (r["values"] is None):
                return "INVALID_ASSUMPTION", {"reason": "exactly one of value and values"}
            if r["name"] == RAMP_NAME:
                vals = [dec(v) for v in (r["values"] or [])]
                if not vals or any(v < 0 or v > 1 for v in vals) or any(b < a for a, b in zip(vals, vals[1:])):
                    return "INVALID_RAMP", {"reason": "a ramp is a non-decreasing list of fractions in [0, 1]"}
            key = (r["initiative_id"], r["name"], r["version_number"])
            for a in acc[e]:
                if (a["initiative_id"], a["name"], a["version_number"]) == key:
                    return "VERSION_EXISTS", {"existing_id": a["assumption_id"], "version_number": r["version_number"]}
        elif e == "resources":
            if dec(r["capacity_per_period"]) < 0:
                return "INVALID_AMOUNT", {}
        elif e == "scenario_versions":
            if r["status"] not in SCENARIO_STATUSES:
                return "STATUS_NOT_ALLOWED", {"status": r["status"]}
            if not 1 <= r["horizon_periods"] <= MAX_HORIZON:
                return "INVALID_HORIZON", {"horizon_periods": r["horizon_periods"]}
            if r["rate_basis"] not in BASES:
                return "INVALID_RATE_BASIS", {"rate_basis": r["rate_basis"]}
            if not F(0) <= dec(r["discount_rate"]) <= F(1):
                return "INVALID_RATE", {"discount_rate": r["discount_rate"]}
            if not r["initiative_ids"]:
                return "INVALID_SCENARIO", {"reason": "a scenario names at least one initiative"}
            period_basis = self.pop.config["period_basis"]
            if r["rate_basis"] != period_basis:
                cid = r["rate_conversion_assumption_id"]
                if cid is None:
                    return "RATE_PERIOD_MISMATCH", {"rate_basis": r["rate_basis"], "period_basis": period_basis}
                conv = next(a for a in acc["assumption_versions"] if a["assumption_id"] == cid)
                if conv["name"] != CONVERSION_NAME or conv["value"] is None or not F(0) <= dec(conv["value"]) <= F(1):
                    return "INVALID_CONVERSION", {"assumption_id": cid, "expected_name": CONVERSION_NAME}
        elif e == "cost_items":
            if r["cost_type"] in ("one_time", "recurring"):
                for c in acc[e]:       # R9-05: one cost key is one kind of cost for an initiative and a basis
                    if (c["initiative_id"], c["cost_key"], c["cost_basis"]) == (r["initiative_id"], r["cost_key"], r["cost_basis"]) and c["cost_type"] != r["cost_type"]:
                        return "COST_KEY_BASIS_CONFLICT", {"first_cost_id": c["cost_id"], "first_cost_type": c["cost_type"], "this_cost_type": r["cost_type"],
                                                           "cost_key": r["cost_key"], "cost_basis": r["cost_basis"]}
            if r["cost_type"] == "one_time":
                if r["period_index"] is None or not 0 <= r["period_index"] <= MAX_PERIOD or r["start_period"] is not None or r["end_period"] is not None:
                    return "INVALID_PERIOD", {}
                for c in acc[e]:
                    if (c["initiative_id"], c["cost_key"], c["cost_basis"], c["cost_type"]) == (r["initiative_id"], r["cost_key"], r["cost_basis"], "one_time"):
                        return "ONE_TIME_COST_REPEATED", {"first_cost_id": c["cost_id"], "first_period": c["period_index"], "repeat_period": r["period_index"]}
            elif r["cost_type"] == "recurring":
                if (r["period_index"] is not None or r["start_period"] is None or r["end_period"] is None
                        or not 0 <= r["start_period"] < r["end_period"] <= MAX_PERIOD):
                    return "INVALID_PERIOD", {}
            else:
                return "INVALID_COST_TYPE", {}
            if r["cost_basis"] not in COST_BASES or dec(r["amount"]) < 0:
                return "INVALID_AMOUNT", {}
        elif e == "benefit_items":
            if r["benefit_type"] not in BENEFIT_TYPES:
                return "INVALID_BENEFIT_TYPE", {}
            if dec(r["amount"]) < 0 or (r["baseline_trend_per_period"] is not None and dec(r["baseline_trend_per_period"]) < 0):
                return "INVALID_AMOUNT", {}
            if r["unit"] != ("hours" if r["benefit_type"] == "capacity" else "USD"):
                return "INVALID_UNIT", {"unit": r["unit"], "benefit_type": r["benefit_type"]}
            if r["evidence_ref"] is not None and not r["evidence_ref"].strip():
                return "EVIDENCE_REQUIRED", {"field": "evidence_ref"}
            ini = self._initiative(r["initiative_id"])
            if r["starts_period"] < ini["deployment_period"]:
                return "BENEFIT_BEFORE_DEPLOYMENT", {"starts_period": r["starts_period"], "deployment_period": ini["deployment_period"]}
            if r["period_index"] < r["starts_period"] or r["period_index"] > MAX_PERIOD:
                return "INVALID_PERIOD", {}
            if r["benefit_type"] == "capacity" and r["cash_realisation"] and not self.conversion_exists(r["initiative_id"]):
                return "CAPACITY_WITHOUT_CONVERSION", {"hours": r["amount"]}
        elif e == "dependencies":
            if r["dependency_type"] not in DEPENDENCY_TYPES:
                return "INVALID_DEPENDENCY_TYPE", {}
            if r["lag_periods"] < 0 or r["lag_periods"] > MAX_PERIOD:
                return "INVALID_LAG", {}
            cyc = [r["initiative_id"], r["initiative_id"]] if r["initiative_id"] == r["prerequisite_id"] else self.cycle_from(r["initiative_id"], r["prerequisite_id"])
            if cyc:
                return "DEPENDENCY_CYCLE", {"cycle": cyc}
        elif e == "stakeholder_groups":
            if r["impact_level"] not in IMPACT_LEVELS:
                return "INVALID_IMPACT_LEVEL", {}
            if "@" in r["group_name"] or re.search(r"\d{6,}", r["group_name"].replace(" ", "").replace("-", "")):
                return "LABEL_NOT_SYNTHETIC", {"field": "group_name"}      # a stakeholder label is a synthetic role or team, never an e-mail or a phone number
            if r["affected_count"] < 0:
                return "INVALID_COUNT", {}
        elif e == "impact_mappings":
            if r["impact_level"] not in IMPACT_LEVELS:
                return "INVALID_IMPACT_LEVEL", {}
            if not r["operating_change"].strip():
                return "OPERATING_CHANGE_REQUIRED", {}
        elif e == "resource_allocations":
            cap = dec(next(x for x in acc["resources"] if x["resource_id"] == r["resource_id"])["capacity_per_period"])
            if dec(r["amount"]) < 0 or not 0 <= r["period_index"] <= MAX_PERIOD:
                return "INVALID_AMOUNT", {}
            used = sum((dec(a["amount"]) for a in acc[e] if a["resource_id"] == r["resource_id"] and a["period_index"] == r["period_index"]), F(0))
            if used + dec(r["amount"]) > cap:            # D-P9-15: checked in id order; a sum equal to capacity is allowed
                return "RESOURCE_OVERALLOCATED", {"resource_id": r["resource_id"], "periods": [r["period_index"]], "allocated_before": money(used),
                                                  "requested": r["amount"], "capacity": money(cap)}
        elif e == "readiness_assessments":
            if r["dimension"] not in DIMENSIONS:
                return "INVALID_DIMENSION", {}
            if not 1 <= r["score"] <= 5:
                return "INVALID_SCORE", {"score": r["score"]}
            if dec(r["weight"]) <= 0:
                return "INVALID_WEIGHT", {}
        elif e in ("adoption_observations", "training_completions"):
            a, b = ("eligible_count", "adopted_count") if e == "adoption_observations" else ("eligible_trainees", "completed")
            ini = self._initiative(r["initiative_id"])
            if r["eligibility_rule_version"] != ini["eligibility_rule_version"]:
                return "ELIGIBILITY_RULE_MISMATCH", {"initiative_rule": ini["eligibility_rule_version"], "row_rule": r["eligibility_rule_version"]}
            if r[a] < 0 or r[b] < 0 or r[b] > r[a]:
                return ("ADOPTED_EXCEEDS_ELIGIBLE" if e == "adoption_observations" else "COMPLETED_EXCEEDS_ELIGIBLE"), {"eligible": r[a], "numerator": r[b]}
        elif e == "benefit_observations":
            if dec(r["measured_value"]) < 0:
                return "INVALID_AMOUNT", {}
            if not r["evidence_ref"].strip():
                return "EVIDENCE_REQUIRED", {"field": "evidence_ref"}
        elif e == "risk_items":
            if not F(0) <= dec(r["probability"]) <= F(1):
                return "PROBABILITY_OUT_OF_RANGE", {"probability": r["probability"]}
            if dec(r["impact"]) < 0:
                return "INVALID_AMOUNT", {}
        elif e == "forecast_versions":
            if r["version_number"] < 1 or not 0 <= r["period_index"] <= MAX_PERIOD or dec(r["amount"]) < 0:
                return "INVALID_AMOUNT", {}
            key = (r["initiative_id"], r["version_number"], r["period_index"])
            for a in acc[e]:
                if (a["initiative_id"], a["version_number"], a["period_index"]) == key:
                    return "VERSION_EXISTS", {"existing_id": a["forecast_id"], "version_number": r["version_number"]}
        return None


# ------------------------------------------------------------------------------------------------------------------------- batch
@dataclass
class Ingest:
    population: Population
    rejected: list[Rejection]

    def counts(self) -> dict[str, dict[str, int]]:
        return {e: {"accepted": len(self.population.acc[e]), "rejected": sum(1 for r in self.rejected if r.entity == e)} for e in ENTITIES}

    def rejected_records(self) -> list[dict[str, Any]]:
        return [r.record() for r in self.rejected]


def config_of(inputs: dict[str, Any]) -> dict[str, Any]:
    check_period_start(inputs["period_start"])           # R9-14: refused cleanly, never a crash inside the calendar
    return {"period_basis": inputs["period_basis"], "period_start": inputs["period_start"], "as_of": inputs.get("as_of")}


def validate_batch(inputs: dict[str, Any]) -> Ingest:
    """Validate a whole dataset (the shape of ``inputs.json``): accepted rows per entity and the rejected records in entity order then row order."""
    v = Validator(config=config_of(inputs))
    rejected: list[Rejection] = []
    for e in ENTITIES:
        for row in inputs.get(e) or []:
            rej = v.add(e, row)
            if rej is not None:
                rejected.append(rej)
    return Ingest(v.pop, rejected)


def parse_as_of(s: str | None) -> datetime | None:
    return parse_ts(s) if s else None
