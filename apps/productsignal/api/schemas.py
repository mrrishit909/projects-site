"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return
``{command_id, status, result, warnings, version}``; reads return ``{data, meta, warnings}``.
Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in ``error.details[].rule_id``.
Proportions, amounts and the plan's decimals are STRINGS: a JSON number is refused (FIELD_INVALID), never rounded.
"""
from __future__ import annotations

import re
from typing import Annotated, Any

from productsignal.timeutil import parse_ts
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

Id = Annotated[StrictStr, Field(min_length=1, max_length=128)]
Dec = Annotated[StrictStr, Field(min_length=1, max_length=40, pattern=r"^\d+(\.\d+)?$")]


class Strict(BaseModel):
    """Base model: unknown fields are errors (FIELD_UNEXPECTED)."""
    model_config = ConfigDict(extra="forbid")


def _instant(v: str | None) -> str | None:
    if v is None:
        return None
    try:
        parse_ts(v)
    except ValueError:
        raise PydanticCustomError("TIMESTAMP_INVALID", "must be an ISO-8601 timestamp with seconds and a zone") from None
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


class At(Strict):
    """Mixin base for inputs that carry one optional instant per field named ``*_at``."""

    @field_validator("*", mode="after")
    @classmethod
    def _instants(cls, v: Any, info: Any) -> Any:
        if info.field_name.endswith("_at") and isinstance(v, str):
            _instant(v)
        return v


class ValidateTrackingInput(Strict):
    """C01: raw events (and the properties that travel with them). Rows are validated one by one by the domain: a bad row is
    rejected with a reason and the rest are accepted. ``received_at`` is the log's own clock; only an admin may backfill it."""
    events: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    properties: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


class ResolveIdentityInput(At):
    anonymous_id: Id
    user_id: Id
    linked_at: StrictStr | None = None
    rule_version: Id = "v1"
    identity_link_id: Id | None = None


class FunnelWindow(Strict):
    from_: StrictStr = Field(alias="from")
    to: StrictStr

    @field_validator("from_", "to")
    @classmethod
    def _at(cls, v: str) -> str:
        return _instant(v)  # type: ignore[return-value]


class DefineFunnelInput(Strict):
    definition_id: Id
    steps: list[StrictStr] = Field(min_length=2, max_length=20)
    max_gap_hours: StrictInt = Field(ge=1, le=8760)
    window: FunnelWindow


class AssignInput(At):
    experiment_version_id: Id
    unit_id: Id
    variant: Id
    assignment_id: Id | None = None
    assigned_at: StrictStr | None = None


class ExposureInput(At):
    assignment_id: Id
    surface: Id
    exposure_id: Id | None = None
    event_id: Id | None = None
    exposed_at: StrictStr | None = None


class Guardrail(Strict):
    metric: Id
    window_days: StrictInt = Field(ge=1, le=3650)


class RevenueWindow(Strict):
    from_: StrictStr = Field(alias="from")
    to: StrictStr

    @field_validator("from_", "to")
    @classmethod
    def _at(cls, v: str) -> str:
        return _instant(v)  # type: ignore[return-value]


class SrmConfig(Strict):
    p_threshold: Dec
    min_expected_cell: StrictInt = Field(ge=0, le=1000000)


class FreezePlanInput(At):
    """C06: the plan, fixed before any outcome is read. ``frozen_at`` defaults to now; the hash is taken over the body."""
    experiment_version_id: Id
    primary_metric: Id
    unit_type: Id
    allocation: dict[Id, Dec]
    planned_end: StrictStr
    activation_window_days: StrictInt = Field(ge=1, le=3650)
    guardrail: Guardrail
    revenue_window: RevenueWindow
    confidence: Dec
    z: Dec
    srm: SrmConfig
    frozen_at: StrictStr | None = None

    @field_validator("planned_end")
    @classmethod
    def _end(cls, v: str) -> str:
        return _instant(v)  # type: ignore[return-value]


class CheckMaturityInput(At):
    experiment_version_id: Id
    cutoff: StrictStr | None = None

    @field_validator("cutoff")
    @classmethod
    def _cut(cls, v: str | None) -> str | None:
        return _instant(v)


class Exclusion(Strict):
    field: StrictStr = Field(min_length=1, max_length=64)
    values: list[StrictStr] = Field(min_length=1, max_length=50)


class AnalyzeInput(Strict):
    """C08. ``analysis`` and ``analysis_unit`` exist so a request for anything but the plan's analysis can be refused with a
    reason; ``exclusions`` may only name pre-assignment attributes."""
    experiment_version_id: Id
    cutoff: StrictStr | None = None
    analysis: StrictStr = "intention_to_treat"
    analysis_unit: StrictStr = "account"
    exclusions: list[Exclusion] = Field(default_factory=list, max_length=10)

    @field_validator("cutoff")
    @classmethod
    def _cut(cls, v: str | None) -> str | None:
        return _instant(v)


class ReviewGuardrailsInput(Strict):
    analysis_id: Id


class DecisionInput(At):
    experiment_version_id: Id
    analysis_id: Id
    review_id: Id
    decision: StrictStr
    rationale: StrictStr = Field(min_length=1, max_length=2000)
    basis: StrictStr = "primary"
    decided_at: StrictStr | None = None


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


ValidateTrackingRequest = _request(ValidateTrackingInput, "ValidateTrackingRequest")
ResolveIdentityRequest = _request(ResolveIdentityInput, "ResolveIdentityRequest")
DefineFunnelRequest = _request(DefineFunnelInput, "DefineFunnelRequest")
AssignExperimentRequest = _request(AssignInput, "AssignExperimentRequest")
RecordExposureRequest = _request(ExposureInput, "RecordExposureRequest")
FreezePlanRequest = _request(FreezePlanInput, "FreezePlanRequest")
CheckMaturityRequest = _request(CheckMaturityInput, "CheckMaturityRequest")
AnalyzeRequest = _request(AnalyzeInput, "AnalyzeRequest")
ReviewGuardrailsRequest = _request(ReviewGuardrailsInput, "ReviewGuardrailsRequest")
RecordDecisionRequest = _request(DecisionInput, "RecordDecisionRequest")


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
