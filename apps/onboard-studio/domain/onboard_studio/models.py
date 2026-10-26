"""Typed records for the 13 input entities and the population the metrics run over."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from .contract import DEPENDENCY_TYPES, DOCUMENT_STATES, ENTITIES, STEP_STATES
from .timeutil import iso_z, parse_ts, parse_ts_opt


def _s(v: object) -> str:
    if not isinstance(v, str) or not v:
        raise ValueError("non-empty string required")
    return v


def _s_opt(v: object) -> str | None:
    return None if v is None else _s(v)


def _int(v: object, minimum: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ValueError(f"integer >= {minimum} required")
    return v


def _pos_decimal(v: object) -> Decimal:
    """Business minutes: a positive integer, or a decimal string / Decimal (the column is NUMERIC)."""
    if isinstance(v, bool) or not isinstance(v, (int, str, Decimal)):
        raise ValueError("positive number required")
    d = Decimal(v)
    if not d.is_finite() or d <= 0:
        raise ValueError("positive number required")
    return d


def _bool(v: object) -> bool:
    if not isinstance(v, bool):
        raise ValueError("boolean required")
    return v


def _choice(v: object, allowed: tuple[str, ...]) -> str:
    if v not in allowed:
        raise ValueError(f"one of {allowed} required")
    return str(v)


@dataclass(frozen=True)
class Organization:
    organization_id: str
    organization_name: str
    segment: str
    region: str
    created_at: datetime


@dataclass(frozen=True)
class WorkflowVersion:
    workflow_version_id: str
    template_id: str
    version_number: int
    published_at: datetime | None
    definition_hash: str | None


@dataclass(frozen=True)
class StepDefinition:
    step_definition_id: str
    workflow_version_id: str
    step_name: str
    required: bool
    role_key: str
    sequence: int


@dataclass(frozen=True)
class Dependency:
    dependency_id: str
    step_definition_id: str
    prerequisite_id: str
    dependency_type: str
    created_at: datetime | None


@dataclass(frozen=True)
class SlaRule:
    sla_rule_id: str
    workflow_version_id: str
    business_minutes: Decimal
    pause_policy: tuple[str, ...]
    calendar_id: str


@dataclass(frozen=True)
class CalendarInterval:
    calendar_interval_id: str
    calendar_id: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    kind: str  # "working" or "holiday"


@dataclass(frozen=True)
class Case:
    case_id: str
    organization_id: str
    workflow_version_id: str
    status: str
    opened_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class StepInstance:
    step_instance_id: str
    case_id: str
    step_definition_id: str
    status: str
    version_number: int
    ready_at: datetime | None
    started_at: datetime | None
    approved_at: datetime | None


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    step_instance_id: str
    assignee_id: str
    assigned_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True)
class DocumentVersion:
    document_version_id: str
    case_id: str
    document_type: str
    version_number: int
    content_hash: str
    review_status: str
    submitted_at: datetime
    reviewed_at: datetime | None


@dataclass(frozen=True)
class Approval:
    approval_id: str
    step_instance_id: str
    reviewer_id: str
    decision: str
    decided_at: datetime
    reason: str | None
    version_number: int | None  # None: the step instance's current version


@dataclass(frozen=True)
class WaitingInterval:
    waiting_interval_id: str
    case_id: str
    reason_code: str
    starts_at: datetime
    ends_at: datetime | None
    pause_requested: bool = False


@dataclass(frozen=True)
class CaseEvent:
    event_id: str
    case_id: str
    event_type: str
    actor_id: str
    occurred_at: datetime


ID_FIELD = {"organizations": "organization_id", "cases": "case_id", "workflow_versions": "workflow_version_id",
            "step_definitions": "step_definition_id", "dependencies": "dependency_id",
            "step_instances": "step_instance_id", "assignments": "assignment_id",
            "document_versions": "document_version_id", "approvals": "approval_id",
            "sla_rules": "sla_rule_id", "calendar_intervals": "calendar_interval_id",
            "waiting_intervals": "waiting_interval_id", "case_events": "event_id"}


def _pause_policy(v: object) -> tuple[str, ...]:
    if not isinstance(v, (list, tuple)) or not all(isinstance(x, str) and x for x in v):
        raise ValueError("pause_policy must be a list of reason codes")
    return tuple(v)


def parsers() -> dict[str, Callable[[dict], Any]]:
    """One parser per entity. A malformed row raises KeyError, ValueError or TypeError."""
    return {
        "organizations": lambda r: Organization(_s(r["organization_id"]), _s(r["organization_name"]),
                                                _s(r["segment"]), _s(r["region"]), parse_ts(r["created_at"])),
        "workflow_versions": lambda r: WorkflowVersion(_s(r["workflow_version_id"]), _s(r["template_id"]),
                                                       _int(r["version_number"], 1),
                                                       parse_ts_opt(r.get("published_at")),
                                                       _s_opt(r.get("definition_hash"))),
        "step_definitions": lambda r: StepDefinition(_s(r["step_definition_id"]), _s(r["workflow_version_id"]),
                                                     _s(r["step_name"]), _bool(r["required"]), _s(r["role_key"]),
                                                     _int(r["sequence"], 0)),
        "dependencies": lambda r: Dependency(_s(r["dependency_id"]), _s(r["step_definition_id"]),
                                             _s(r["prerequisite_id"]),
                                             _choice(r.get("dependency_type", "mandatory"), DEPENDENCY_TYPES),
                                             parse_ts_opt(r.get("created_at"))),
        "sla_rules": lambda r: SlaRule(_s(r["sla_rule_id"]), _s(r["workflow_version_id"]),
                                       _pos_decimal(r["business_minutes"]), _pause_policy(r["pause_policy"]),
                                       _s(r["calendar_id"])),
        "calendar_intervals": lambda r: _calendar_interval(r),
        "cases": lambda r: _case(r),
        "step_instances": lambda r: StepInstance(_s(r["step_instance_id"]), _s(r["case_id"]),
                                                 _s(r["step_definition_id"]), _choice(r["status"], STEP_STATES),
                                                 _int(r["version_number"], 1), parse_ts_opt(r.get("ready_at")),
                                                 parse_ts_opt(r.get("started_at")),
                                                 parse_ts_opt(r.get("approved_at"))),
        "assignments": lambda r: _assignment(r),
        "document_versions": lambda r: DocumentVersion(_s(r["document_version_id"]), _s(r["case_id"]),
                                                       _s(r["document_type"]), _int(r["version_number"], 1),
                                                       _s(r["content_hash"]),
                                                       _choice(r["review_status"], DOCUMENT_STATES),
                                                       parse_ts(r["submitted_at"]),
                                                       parse_ts_opt(r.get("reviewed_at"))),
        "approvals": lambda r: Approval(_s(r["approval_id"]), _s(r["step_instance_id"]), _s(r["reviewer_id"]),
                                        _s(r["decision"]), parse_ts(r["decided_at"]), r.get("reason"),
                                        None if r.get("version_number") is None else _int(r["version_number"], 1)),
        "waiting_intervals": lambda r: _waiting(r),
        "case_events": lambda r: CaseEvent(_s(r["event_id"]), _s(r["case_id"]), _s(r["event_type"]),
                                           _s(r["actor_id"]), parse_ts(r["occurred_at"])),
    }


def _calendar_interval(r: dict) -> CalendarInterval:
    a, b = parse_ts(r["starts_at"]), parse_ts(r["ends_at"])
    if b <= a:
        raise ValueError("ends_at must be after starts_at")
    return CalendarInterval(_s(r["calendar_interval_id"]), _s(r["calendar_id"]), a, b, _s(r["timezone"]),
                            _choice(r.get("kind", "working"), ("working", "holiday")))


def _case(r: dict) -> Case:
    opened, done = parse_ts(r["opened_at"]), parse_ts_opt(r.get("completed_at"))
    if done is not None and done < opened:
        raise ValueError("completed_at before opened_at")
    return Case(_s(r["case_id"]), _s(r["organization_id"]), _s(r["workflow_version_id"]),
                _choice(r["status"], ("open", "completed")), opened, done)


def _assignment(r: dict) -> Assignment:
    a, e = parse_ts(r["assigned_at"]), parse_ts_opt(r.get("ended_at"))
    if e is not None and e < a:
        raise ValueError("ended_at before assigned_at")
    return Assignment(_s(r["assignment_id"]), _s(r["step_instance_id"]), _s(r["assignee_id"]), a, e)


def _waiting(r: dict) -> WaitingInterval:
    a, e = parse_ts(r["starts_at"]), parse_ts_opt(r.get("ends_at"))
    if e is not None and e < a:
        raise ValueError("ends_at before starts_at")
    return WaitingInterval(_s(r["waiting_interval_id"]), _s(r["case_id"]), _s(r["reason_code"]), a, e,
                           bool(r.get("pause_requested", False)))


@dataclass
class Population:
    """Parsed records of one dataset (the accepted rows) plus the required document types."""
    organizations: list[Organization] = field(default_factory=list)
    cases: list[Case] = field(default_factory=list)
    workflow_versions: list[WorkflowVersion] = field(default_factory=list)
    step_definitions: list[StepDefinition] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    step_instances: list[StepInstance] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    document_versions: list[DocumentVersion] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    sla_rules: list[SlaRule] = field(default_factory=list)
    calendar_intervals: list[CalendarInterval] = field(default_factory=list)
    waiting_intervals: list[WaitingInterval] = field(default_factory=list)
    case_events: list[CaseEvent] = field(default_factory=list)
    requirements: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows: dict[str, list[dict]], requirements: dict[str, Any] | None = None) -> "Population":
        """Parse JSON-shaped rows without applying the ingest rules (rows are trusted, e.g. from the database)."""
        ps = parsers()
        pop = cls()
        for ent in ENTITIES:
            if ent == "organizations":
                continue
            setattr(pop, ent, [ps[ent](r) for r in rows.get(ent) or []])
        pop.organizations = [ps["organizations"](r) for r in rows.get("organizations") or []]
        pop.requirements = normalise_requirements(requirements)
        return pop

    def subset(self, case_ids: set[str]) -> "Population":
        """The population restricted to some cases and everything that hangs off them."""
        steps = {s.step_instance_id for s in self.step_instances if s.case_id in case_ids}
        return Population(
            organizations=self.organizations, cases=[c for c in self.cases if c.case_id in case_ids],
            workflow_versions=self.workflow_versions, step_definitions=self.step_definitions,
            dependencies=self.dependencies,
            step_instances=[s for s in self.step_instances if s.case_id in case_ids],
            assignments=[a for a in self.assignments if a.step_instance_id in steps],
            document_versions=[d for d in self.document_versions if d.case_id in case_ids],
            approvals=[a for a in self.approvals if a.step_instance_id in steps],
            sla_rules=self.sla_rules, calendar_intervals=self.calendar_intervals,
            waiting_intervals=[w for w in self.waiting_intervals if w.case_id in case_ids],
            case_events=[e for e in self.case_events if e.case_id in case_ids],
            requirements=self.requirements)


def normalise_requirements(block: dict[str, Any] | None) -> dict[str, tuple[str, ...]]:
    """``{wfv: {required_document_types: [...]}}`` (D-05) to ``{wfv: (types...)}``."""
    out: dict[str, tuple[str, ...]] = {}
    for wfv, spec in (block or {}).items():
        types = spec.get("required_document_types", []) if isinstance(spec, dict) else spec
        out[wfv] = tuple(types)
    return out


@dataclass
class RejectedRecord:
    entity: str
    id: str
    reason_code: str
    raw_row: dict[str, Any]
    status: str = "rejected"

    def as_dict(self) -> dict[str, Any]:
        return {"entity": self.entity, "id": self.id, "status": self.status,
                "reason_code": self.reason_code, "raw_row": self.raw_row}


__all__ = ["Population", "RejectedRecord", "ID_FIELD", "parsers", "normalise_requirements", "iso_z"]
