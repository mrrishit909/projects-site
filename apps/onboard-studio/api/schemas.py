"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return
``{command_id, status, result, warnings, version}``; reads return ``{data, meta, warnings}``.
Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in ``error.details[].rule_id``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")

Id = Annotated[StrictStr, Field(min_length=1, max_length=128)]


class Strict(BaseModel):
    """Base model: unknown fields are errors (FIELD_UNEXPECTED)."""
    model_config = ConfigDict(extra="forbid")


def _instant(v: str | None) -> str | None:
    if v is None:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise PydanticCustomError("TIMESTAMP_INVALID", "must be an ISO-8601 timestamp with a zone") from None
    if d.tzinfo is None:
        raise PydanticCustomError("TIMESTAMP_INVALID", "must be an ISO-8601 timestamp with a zone")
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


class CreateCaseInput(Timed):
    case_id: Id
    organization_id: Id
    workflow_version_id: Id
    assignments: dict[Id, Id] = Field(default_factory=dict)  # step_definition_id -> assignee_id
    corrects_case_id: Id | None = None


class DocumentInput(Timed):
    case_id: Id
    document_type: Id
    step_instance_id: Id | None = None
    content_hash: StrictStr | None = None

    @field_validator("content_hash")
    @classmethod
    def _hash(cls, v: str | None) -> str | None:
        if v is not None and not _HASH.match(v):
            raise PydanticCustomError("CONTENT_HASH_INVALID",
                                      "content_hash is a synthetic placeholder: sha256: plus 64 hex digits")
        return v


class RejectInput(Timed):
    case_id: Id
    document_type: Id
    reason: StrictStr = Field(min_length=1, max_length=500)
    step_instance_id: Id | None = None

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        if not v.strip():
            raise PydanticCustomError("REASON_REQUIRED", "a reviewer reason is required")
        return v


class AcceptInput(Timed):
    case_id: Id
    document_type: Id


class UnlockInput(Timed):
    step_instance_id: Id
    expected_version: StrictInt | None = Field(default=None, ge=1)


class ApproveInput(Timed):
    step_instance_id: Id
    expected_version: StrictInt = Field(ge=1)
    reason: StrictStr | None = Field(default=None, max_length=500)


class PauseInput(Timed):
    case_id: Id
    reason_code: Id
    starts_at: StrictStr | None = None
    ends_at: StrictStr | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _at2(cls, v: str | None) -> str | None:
        return _instant(v)


class CompleteInput(Timed):
    case_id: Id
    expected_version: StrictInt | None = Field(default=None, ge=1)


class ReopenInput(Strict):
    case_id: Id


class StepIn(Strict):
    step_definition_id: Id
    step_name: Id
    required: StrictBool
    role_key: Id
    sequence: StrictInt = Field(ge=0)


class DependencyIn(Strict):
    dependency_id: Id
    step_definition_id: Id
    prerequisite_id: Id
    dependency_type: StrictStr = "mandatory"

    @field_validator("dependency_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in ("mandatory", "optional"):
            raise PydanticCustomError("DEPENDENCY_TYPE_INVALID", "dependency_type is mandatory or optional")
        return v


class SlaIn(Strict):
    sla_rule_id: Id
    business_minutes: StrictInt = Field(ge=1)
    pause_policy: list[Id] = Field(default_factory=list)
    calendar_id: Id


class PublishInput(Timed):
    workflow_version_id: Id
    template_id: Id | None = None
    version_number: StrictInt | None = Field(default=None, ge=1)
    steps: list[StepIn] | None = None
    dependencies: list[DependencyIn] = Field(default_factory=list)
    sla_rule: SlaIn | None = None
    required_document_types: list[Id] = Field(default_factory=list)


class AnyInput(BaseModel):
    """Extension commands accept any object; they answer 501."""
    model_config = ConfigDict(extra="allow")


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


CreateCaseRequest = _request(CreateCaseInput, "CreateCaseRequest")
DocumentRequest = _request(DocumentInput, "DocumentRequest")
RejectRequest = _request(RejectInput, "RejectRequest")
AcceptRequest = _request(AcceptInput, "AcceptRequest")
UnlockRequest = _request(UnlockInput, "UnlockRequest")
ApproveRequest = _request(ApproveInput, "ApproveRequest")
PauseRequest = _request(PauseInput, "PauseRequest")
CompleteRequest = _request(CompleteInput, "CompleteRequest")
ReopenRequest = _request(ReopenInput, "ReopenRequest")
PublishRequest = _request(PublishInput, "PublishRequest")
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
    contract_version: str
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
