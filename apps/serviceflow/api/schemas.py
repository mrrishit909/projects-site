"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return
``{command_id, status, result, warnings, version}``; reads return ``{data, meta, warnings}``.
Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in ``error.details[].rule_id``.
"""
from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError
from serviceflow.models import SEED_MAX
from serviceflow.timeutil import parse_ts

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

Id = Annotated[StrictStr, Field(min_length=1, max_length=128)]
Rows = Annotated[list[dict[str, Any]], Field(max_length=20000)]


class Strict(BaseModel):
    """Base model: unknown fields are errors (FIELD_UNEXPECTED)."""
    model_config = ConfigDict(extra="forbid")


def _instant(v: str | None) -> str | None:
    if v is None:
        return None
    try:
        parse_ts(v)          # D-09: the same single form as the domain (seconds required)
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
            raise PydanticCustomError("IDEMPOTENCY_KEY_INVALID",
                                      "idempotency_key must be 1-128 of A-Za-z0-9._:-")
        return v


class Timed(Strict):
    """Inputs that may carry the instant the action happened (default: now)."""
    occurred_at: StrictStr | None = None

    @field_validator("occurred_at")
    @classmethod
    def _at(cls, v: str | None) -> str | None:
        return _instant(v)


class IngestInput(Strict):
    """C01: raw rows per entity. They are validated by the domain, not here, so a bad row is a rejected record
    (with its reason) and never a failed request."""
    customers: Rows = Field(default_factory=list)
    queues: Rows = Field(default_factory=list)
    agents: Rows = Field(default_factory=list)
    skills: Rows = Field(default_factory=list)
    agent_skills: Rows = Field(default_factory=list)
    queue_skills: Rows = Field(default_factory=list)
    shifts: Rows = Field(default_factory=list)
    sla_policies: Rows = Field(default_factory=list)
    tickets: Rows = Field(default_factory=list)
    ticket_events: Rows = Field(default_factory=list)
    surveys: Rows = Field(default_factory=list)


class AssignQueueInput(Timed):
    ticket_id: Id
    queue_id: Id


class StartServiceInput(Timed):
    ticket_id: Id
    agent_id: Id
    reply: StrictBool = False      # also record the agent's first human reply at the same instant


class TransferInput(Timed):
    ticket_id: Id
    to_queue_id: Id


class PauseInput(Timed):
    ticket_id: Id


class ResumeInput(Timed):
    ticket_id: Id


class ResolveInput(Timed):
    ticket_id: Id


class ReopenInput(Timed):
    ticket_id: Id


class RunSimulationInput(Strict):
    simulation_id: Id
    seed: StrictInt = Field(ge=-SEED_MAX, le=SEED_MAX)
    warmup_minutes: StrictInt | float = Field(default=0, ge=0, allow_inf_nan=False)
    horizon_minutes: StrictInt | float = Field(gt=0, allow_inf_nan=False)
    policy_version: Id
    config: dict[str, Any]
    replications: StrictInt = Field(default=1, ge=1, le=200)


class ComparePoliciesInput(Strict):
    seed: StrictInt = Field(ge=-SEED_MAX, le=SEED_MAX)
    warmup_minutes: StrictInt | float = Field(default=0, ge=0, allow_inf_nan=False)
    horizon_minutes: StrictInt | float = Field(gt=0, allow_inf_nan=False)
    replications: StrictInt = Field(default=10, ge=1, le=200)
    baseline: dict[str, Any]
    proposal: dict[str, Any]


class AnyInput(BaseModel):
    """Extension commands accept any object; they answer 501."""
    model_config = ConfigDict(extra="allow")


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


IngestRequest = _request(IngestInput, "IngestRequest")
AssignQueueRequest = _request(AssignQueueInput, "AssignQueueRequest")
StartServiceRequest = _request(StartServiceInput, "StartServiceRequest")
TransferRequest = _request(TransferInput, "TransferRequest")
PauseRequest = _request(PauseInput, "PauseRequest")
ResumeRequest = _request(ResumeInput, "ResumeRequest")
ResolveRequest = _request(ResolveInput, "ResolveRequest")
ReopenRequest = _request(ReopenInput, "ReopenRequest")
RunSimulationRequest = _request(RunSimulationInput, "RunSimulationRequest")
ComparePoliciesRequest = _request(ComparePoliciesInput, "ComparePoliciesRequest")
ExtensionRequest = _request(AnyInput, "ExtensionRequest")


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
