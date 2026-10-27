"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return ``{command_id, status, result, warnings, version}``; reads return
``{data, meta, warnings}``. Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in ``error.details[].rule_id``. Money and
proportions are STRINGS: a JSON number is refused, never rounded. No input has an instant: the server stamps ``created_at``, ``assessed_at``,
``proposed_at``... and an evidence date is a plain date (``measured_on``, ``observed_on``).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, ClassVar, Literal

from changeworks.numbers import DECIMAL_RE
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from pydantic_core import PydanticCustomError

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ASSUMPTION_WORDS = ("target", "assum", "expect", "ramp", "forecast", "discount", "rate_basis", "savings", "benefit", "scenario")

Id = Annotated[StrictStr, Field(min_length=1, max_length=128)]
Text = Annotated[StrictStr, Field(max_length=2000)]
Name = Annotated[StrictStr, Field(min_length=1, max_length=200)]
Period = Annotated[StrictInt, Field(ge=0, le=100_000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _decimal(v: str | None) -> str | None:
    if v is None:
        return None
    if not DECIMAL_RE.match(v):
        raise PydanticCustomError("DECIMAL_INVALID", "must be a decimal string with at most 6 places, e.g. \"1000.00\"")
    return v


def _on(v: str | None) -> str | None:
    if v is None:
        return None
    if not _DATE.match(v):
        raise PydanticCustomError("DATE_INVALID", "must be a plain date YYYY-MM-DD (an instant is stamped by the server)")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise PydanticCustomError("DATE_INVALID", "must be a real calendar date") from None
    return v


Dec = Annotated[StrictStr, Field(max_length=30)]


class DecModel(Strict):
    """Base for models with decimal-string fields named in ``DECIMALS`` (checked after the type)."""
    DECIMALS: ClassVar[tuple[str, ...]] = ()

    @field_validator("*", mode="after")
    @classmethod
    def _decimals(cls, v: Any, info: Any) -> Any:
        if info.field_name in cls.DECIMALS:
            _decimal(v)
        return v


class Envelope(Strict):
    """Common command envelope. ``input`` is narrowed by each command's request model."""
    request_id: StrictStr = Field(min_length=1, max_length=128)
    dataset_version: StrictStr = Field(min_length=1, max_length=128)
    idempotency_key: StrictStr

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _TOKEN.match(v):
            raise PydanticCustomError("IDEMPOTENCY_KEY_INVALID", "idempotency_key must be 1-128 of A-Za-z0-9._:-")
        return v


# --- C01
class EstablishBaselineInput(DecModel):
    """C01. ``create``: measured evidence only (volume, minutes per case, error rate, evidence reference, evidence date); ``approve`` (sponsor, admin):
    names the approved set and freezes it. Assumption fields are refused (ASSUMPTION_IN_EVIDENCE): evidence and assumptions stay separate."""
    DECIMALS = ("error_rate",)
    action: Literal["create", "approve"] = "create"
    initiative_id: Id
    baseline_version: Id
    baseline_id: Id | None = None
    volume: StrictInt | None = Field(default=None, ge=0, le=2_000_000_000)
    minutes_per_case: StrictInt | None = Field(default=None, ge=0, le=2_000_000_000)
    error_rate: Dec | None = None
    evidence_ref: Text | None = None
    measured_on: StrictStr | None = None
    reason: Text | None = None
    expected_version: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _evidence_only(cls, data: Any) -> Any:
        if isinstance(data, dict):
            known = set(cls.model_fields)
            for k in data:
                if k not in known and any(w in str(k).lower() for w in _ASSUMPTION_WORDS):
                    raise PydanticCustomError("ASSUMPTION_IN_EVIDENCE", "{field} is an assumption, not evidence: record it as an assumption version (C03)",
                                              {"field": str(k)})
        return data

    @field_validator("measured_on")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return _on(v)


# --- C02
class CriterionIn(DecModel):
    DECIMALS = ("weight",)
    criterion: Id
    score: StrictInt = Field(ge=1, le=5)
    weight: Dec


class NewInitiativeIn(Strict):
    title: Name
    sponsor_id: Id
    requested_start_period: Period = 0
    duration_periods: Annotated[StrictInt, Field(ge=1, le=100_000)] = 1
    deployment_period: Period = 1
    eligibility_rule_version: Id = "elig-v1"


class AssessOpportunityInput(Strict):
    initiative_id: Id
    new_initiative: NewInitiativeIn | None = None
    criteria: list[CriterionIn] = Field(min_length=1, max_length=50)
    rationale: Text
    expected_version: StrictInt | None = Field(default=None, ge=1)


# --- C03
class AssumptionIn(DecModel):
    DECIMALS = ("value",)
    assumption_id: Id | None = None
    initiative_id: Id | None = None
    name: Id
    version_number: StrictInt | None = Field(default=None, ge=1)
    value: Dec | None = None
    values: list[Dec] | None = Field(default=None, max_length=1200)
    unit: Text | None = None
    rationale: Text
    evidence_ref: Text | None = None
    staffing_change_evidence_ref: Text | None = None

    @field_validator("values")
    @classmethod
    def _values(cls, v: list[str] | None) -> list[str] | None:
        for x in v or []:
            _decimal(x)
        return v


class CostIn(DecModel):
    DECIMALS = ("amount",)
    cost_id: Id | None = None
    initiative_id: Id
    cost_key: Id
    cost_type: StrictStr
    cost_basis: StrictStr = "planned"
    amount: Dec
    period_index: StrictInt | None = None
    start_period: StrictInt | None = None
    end_period: StrictInt | None = None
    baseline_version: Id | None = None


class BenefitIn(DecModel):
    DECIMALS = ("amount", "baseline_trend_per_period")
    benefit_id: Id | None = None
    initiative_id: Id
    benefit_type: StrictStr
    amount: Dec
    period_index: StrictInt
    starts_period: StrictInt
    unit: StrictStr | None = None
    cash_realisation: StrictBool | None = None
    evidence_ref: Text | None = None
    benefit_source_key: Text | None = None
    baseline_trend_per_period: Dec | None = None


class BuildCashFlowsInput(DecModel):
    DECIMALS = ("discount_rate",)
    scenario_id: Id
    baseline_version: Id
    discount_rate: Dec
    rate_basis: StrictStr
    rate_conversion_assumption_id: Id | None = None
    horizon_periods: StrictInt
    initiative_ids: list[Id] = Field(min_length=1, max_length=200)
    pinned_assumption_ids: list[Id] = Field(default_factory=list, max_length=500)
    assumptions: list[AssumptionIn] = Field(default_factory=list, max_length=200)
    costs: list[CostIn] = Field(default_factory=list, max_length=500)
    benefits: list[BenefitIn] = Field(default_factory=list, max_length=500)


# --- C04
class GroupIn(Strict):
    group_id: Id
    group_name: Name
    owner_id: Id
    affected_count: StrictInt = Field(ge=0, le=2_000_000_000)
    impact_level: StrictStr


class MappingIn(Strict):
    mapping_id: Id | None = None
    group_id: Id
    operating_change: Text
    impact_level: StrictStr


class MapImpactsInput(Strict):
    initiative_id: Id
    groups: list[GroupIn] = Field(default_factory=list, max_length=200)
    mappings: list[MappingIn] = Field(min_length=1, max_length=500)


# --- C05
class AssessmentIn(DecModel):
    DECIMALS = ("weight",)
    dimension: StrictStr
    score: StrictInt
    weight: Dec = "1.00"


class AssessReadinessInput(Strict):
    group_id: Id
    assessments: list[AssessmentIn] = Field(min_length=1, max_length=50)


# --- C06
class ScheduleIn(Strict):
    initiative_id: Id
    requested_start_period: Period
    duration_periods: Annotated[StrictInt, Field(ge=1, le=100_000)]
    expected_version: StrictInt | None = Field(default=None, ge=1)


class DependencyIn(Strict):
    dependency_id: Id | None = None
    initiative_id: Id
    prerequisite_id: Id
    dependency_type: StrictStr
    lag_periods: StrictInt = 0


class ResourceIn(DecModel):
    DECIMALS = ("capacity_per_period",)
    resource_id: Id
    name: Name
    capacity_per_period: Dec
    unit: Name


class AllocationIn(DecModel):
    DECIMALS = ("amount",)
    allocation_id: Id | None = None
    resource_id: Id
    initiative_id: Id
    period_index: StrictInt
    amount: Dec


class PlanRoadmapInput(Strict):
    schedule: list[ScheduleIn] = Field(default_factory=list, max_length=200)
    dependencies: list[DependencyIn] = Field(default_factory=list, max_length=500)
    resources: list[ResourceIn] = Field(default_factory=list, max_length=100)
    allocations: list[AllocationIn] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def _something(self) -> Any:
        if not (self.schedule or self.dependencies or self.resources or self.allocations):
            raise PydanticCustomError("NOTHING_TO_PLAN", "send a schedule, dependencies, resources or allocations")
        return self


# --- C07
class SelectScenarioInput(Strict):
    """C07 sets ``proposed``, never anything else: ``status: funded`` is STATUS_NOT_ALLOWED."""
    scenario_id: Id
    compared_scenario_ids: list[Id] = Field(default_factory=list, max_length=50)
    residual_explanation: Text | None = None
    status: StrictStr = "proposed"


# --- C08
class TrainingIn(Strict):
    eligible_trainees: StrictInt = Field(ge=0, le=2_000_000_000)
    completed: StrictInt = Field(ge=0, le=2_000_000_000)


class RecordAdoptionInput(Strict):
    initiative_id: Id
    eligible_count: StrictInt = Field(ge=0, le=2_000_000_000)
    adopted_count: StrictInt = Field(ge=0, le=2_000_000_000)
    eligibility_rule_version: Id
    observed_on: StrictStr | None = None
    training: TrainingIn | None = None

    @field_validator("observed_on")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return _on(v)


# --- C09
class TrackBenefitsInput(DecModel):
    DECIMALS = ("measured_value",)
    benefit_id: Id
    measured_value: Dec
    unit: StrictStr
    evidence_ref: Text
    observed_on: StrictStr | None = None
    attribution: StrictStr = "observed_not_attributed"

    @field_validator("observed_on")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return _on(v)


# --- C10
class PeriodAmountIn(DecModel):
    DECIMALS = ("amount",)
    period_index: Period
    amount: Dec


class ReviseForecastInput(Strict):
    initiative_id: Id
    reason: Text
    periods: list[PeriodAmountIn] = Field(min_length=1, max_length=1200)
    expected_version: StrictInt = Field(ge=0)         # R9-22: the version the caller last read, 0 when there is none: always named


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


EstablishBaselineRequest = _request(EstablishBaselineInput, "EstablishBaselineRequest")
AssessOpportunityRequest = _request(AssessOpportunityInput, "AssessOpportunityRequest")
BuildCashFlowsRequest = _request(BuildCashFlowsInput, "BuildCashFlowsRequest")
MapImpactsRequest = _request(MapImpactsInput, "MapImpactsRequest")
AssessReadinessRequest = _request(AssessReadinessInput, "AssessReadinessRequest")
PlanRoadmapRequest = _request(PlanRoadmapInput, "PlanRoadmapRequest")
SelectScenarioRequest = _request(SelectScenarioInput, "SelectScenarioRequest")
RecordAdoptionRequest = _request(RecordAdoptionInput, "RecordAdoptionRequest")
TrackBenefitsRequest = _request(TrackBenefitsInput, "TrackBenefitsRequest")
ReviseForecastRequest = _request(ReviseForecastInput, "ReviseForecastRequest")


class CommandResponse(BaseModel):
    command_id: str
    status: str
    result: dict[str, Any]
    warnings: list[dict[str, Any]]
    version: int


class Meta(BaseModel):
    dataset_version: str
    code_sha: str
    contract_version: int
    generated_at: str
    applied_filters: dict[str, Any]
    total_count: int
    next_cursor: str | None
    exclusions: dict[str, Any]


class ReadResponse(BaseModel):
    data: Any
    meta: Meta
    warnings: list[dict[str, Any]]


Limit = Annotated[int, Field(ge=1, le=200)]
