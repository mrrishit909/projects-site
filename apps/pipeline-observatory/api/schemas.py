"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return ``{command_id, status, result, warnings, version}``;
reads return ``{data, meta, warnings}``. Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in
``error.details[].rule_id``. A JSON float is refused everywhere (FLOAT_NOT_ALLOWED): money and proportions are strings, counts are integers.
Instants that are decisions (committed_at, published_at, opened_at, started_at of a batch or run) are never accepted from the client:
unknown fields are errors (FIELD_UNEXPECTED).
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any

from pipeline_observatory.timeutil import parse_ts
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_DEC = re.compile(r"^\d+(\.\d{1,3})?$")

Id = Annotated[StrictStr, Field(min_length=1, max_length=128)]
Text = Annotated[StrictStr, Field(max_length=2000)]


class Strict(BaseModel):
    """Base model: unknown fields are errors (FIELD_UNEXPECTED)."""
    model_config = ConfigDict(extra="forbid")


def _no_floats(v: Any, depth: int = 0) -> None:
    if depth > 8:
        raise PydanticCustomError("PAYLOAD_TOO_DEEP", "payload nests deeper than 8 levels")
    if isinstance(v, float):
        raise PydanticCustomError("FLOAT_NOT_ALLOWED", "a JSON number with a fraction is refused: money and proportions are strings")
    if isinstance(v, dict):
        for x in v.values():
            _no_floats(x, depth + 1)
    elif isinstance(v, list):
        for x in v:
            _no_floats(x, depth + 1)


def _instant(v: str) -> str:
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


class RecordInput(Strict):
    """One raw record of a page: the payload as the source sent it, the key the source gave it (default: payload.record_id) and, optionally,
    the hash the source computed (refused when it is not the sha256 of the canonical payload)."""
    payload: dict[str, Any]
    source_key: StrictStr | None = Field(default=None, max_length=256)
    payload_hash: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("payload")
    @classmethod
    def _payload(cls, v: dict[str, Any]) -> dict[str, Any]:
        _no_floats(v)
        return v


class PageInput(Strict):
    """The page the source answered with: status 200 with records and the next cursor, or 429 with ``retry_after_seconds``."""
    status: StrictInt = 200
    records: list[RecordInput] = Field(default_factory=list, max_length=2000)
    next_cursor: Id | None = None
    retry_after_seconds: StrictInt | None = Field(default=None, ge=0, le=86400)
    schema_version: Id | None = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: int) -> int:
        if v not in (200, 429):
            raise PydanticCustomError("PAGE_STATUS_INVALID", "page status must be 200 or 429")
        return v


class FetchSourcePageInput(Strict):
    """C01. ``batch_id`` may be named by the caller (a duplicate is refused) else the server names it; ``fetch_session`` groups the pages of
    one fetch so a repeated cursor is detected."""
    source_id: Id
    cursor: Id
    page: PageInput
    fetch_session: Id | None = None
    batch_id: Id | None = None


class ValidateContractInput(Strict):
    """C02. ``bump_schema_version`` is the explicit bump of the source's expected schema_version (operator or admin only)."""
    batch_id: Id
    bump_schema_version: Id | None = None


class ProcessingInput(Strict):
    measured_seconds: StrictStr
    hardware: Annotated[StrictStr, Field(min_length=1, max_length=200)]
    cache_state: Annotated[StrictStr, Field(min_length=1, max_length=40)]

    @field_validator("measured_seconds")
    @classmethod
    def _secs(cls, v: str) -> str:
        if not _DEC.match(v) or Decimal(v) <= 0:
            raise PydanticCustomError("MEASURED_SECONDS_INVALID", "measured_seconds must be a positive decimal string")
        return v


class CommitBatchInput(Strict):
    batch_id: Id
    checkpoint_version: StrictInt | None = Field(default=None, ge=0)
    processing: ProcessingInput | None = None


class TransformModelsInput(Strict):
    run_id: Id | None = None
    batch_ids: list[Id] = Field(min_length=1, max_length=500)
    backfill_id: Id | None = None
    attempt: StrictInt | None = Field(default=None, ge=1)


class RunQualityGateInput(Strict):
    run_id: Id
    attempt: StrictInt | None = Field(default=None, ge=1)


class PublishSnapshotInput(Strict):
    """C06. ``watermark`` is the event-time horizon the operator discloses (never after the server's now); ``published_at`` is stamped by the server."""
    run_id: Id
    watermark: StrictStr
    dataset_name: Id = "sales_daily"
    attempt: StrictInt | None = Field(default=None, ge=1)

    @field_validator("watermark")
    @classmethod
    def _wm(cls, v: str) -> str:
        return _instant(v)


class InjectFaultInput(Strict):
    fault_type: StrictStr
    target_id: Id
    note: Text | None = None

    @field_validator("fault_type")
    @classmethod
    def _ft(cls, v: str) -> str:
        if v not in ("duplicate_key", "task_failure", "crash_before_checkpoint"):
            raise PydanticCustomError("FAULT_TYPE_INVALID", "fault_type is duplicate_key, task_failure or crash_before_checkpoint")
        return v


class RequestBackfillInput(Strict):
    source_id: Id
    start_at: StrictStr
    end_at: StrictStr

    @field_validator("start_at", "end_at")
    @classmethod
    def _at(cls, v: str) -> str:
        return _instant(v)


class RecoverIncidentInput(Strict):
    incident_id: Id
    recovery_run_id: Id | None = None


class ArchiveEvidenceInput(Strict):
    run_id: Id


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


FetchSourcePageRequest = _request(FetchSourcePageInput, "FetchSourcePageRequest")
ValidateContractRequest = _request(ValidateContractInput, "ValidateContractRequest")
CommitBatchRequest = _request(CommitBatchInput, "CommitBatchRequest")
TransformModelsRequest = _request(TransformModelsInput, "TransformModelsRequest")
RunQualityGateRequest = _request(RunQualityGateInput, "RunQualityGateRequest")
PublishSnapshotRequest = _request(PublishSnapshotInput, "PublishSnapshotRequest")
InjectFaultRequest = _request(InjectFaultInput, "InjectFaultRequest")
RequestBackfillRequest = _request(RequestBackfillInput, "RequestBackfillRequest")
RecoverIncidentRequest = _request(RecoverIncidentInput, "RecoverIncidentRequest")
ArchiveEvidenceRequest = _request(ArchiveEvidenceInput, "ArchiveEvidenceRequest")


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
