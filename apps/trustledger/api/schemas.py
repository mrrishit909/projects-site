"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return ``{command_id, status, result, warnings, version}``;
reads return ``{data, meta, warnings}``. Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in
``error.details[].rule_id``. Proportions are STRINGS: a JSON number is refused (FIELD_INVALID), never rounded.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError
from trustledger.timeutil import parse_ts

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_DEC = re.compile(r"^\d+(\.\d{1,6})?$")

Id = Annotated[StrictStr, Field(min_length=1, max_length=128)]
Text = Annotated[StrictStr, Field(max_length=2000)]


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
    """Base for inputs with optional instants named ``*_at``."""

    @field_validator("*", mode="after")
    @classmethod
    def _instants(cls, v: Any, info: Any) -> Any:
        if info.field_name.endswith("_at") and isinstance(v, str):
            _instant(v)
        return v


class FieldInput(Strict):
    field_name: Id
    data_type: Id = "text"
    nullable: StrictBool = True


class RegisterDatasetInput(At):
    """C01. ``owner_id`` and ``classification`` are checked by the domain so that a missing or blank value reports OWNER_REQUIRED /
    CLASSIFICATION_REQUIRED (D-02). ``registered_at`` is stamped by the server. ``rows`` loads measured rows (flat objects with a row_id)."""
    dataset_id: Id
    dataset_name: Annotated[StrictStr, Field(min_length=1, max_length=200)]
    source_system: Annotated[StrictStr, Field(min_length=1, max_length=100)]
    owner_id: StrictStr | None = None
    classification: StrictStr | None = None
    monitored: StrictBool = False
    refresh_timezone: StrictStr | None = None
    refresh_local_time: StrictStr | None = None
    refresh_grace_minutes: StrictInt | None = Field(default=None, ge=0, le=1439)
    last_refreshed_at: StrictStr | None = None
    fields: list[FieldInput] = Field(default_factory=list, max_length=200)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)


class PublishDefinitionInput(Strict):
    """C02. Every call adds a version row; ``metric_version_id`` names an existing row only to be refused (a published definition is
    never rewritten). ``valid_from`` and the approver are the server's time and the actor."""
    metric_id: Id
    metric_name: Annotated[StrictStr, Field(min_length=1, max_length=200)]
    definition: Text
    grain: Text
    source_fields: list[Annotated[StrictStr, Field(max_length=200)]] = Field(default_factory=list, max_length=100)
    owner_id: Id
    refresh: Text
    status: StrictStr = "published"       # draft | reviewed | published (D-10 R7-12)
    reason: Text | None = None
    metric_version_id: Id | None = None
    expected_version: StrictInt | None = Field(default=None, ge=0)


class RunRuleInput(Strict):
    """C03. ``weights`` exists only so that a weight change without a new version can be refused with a reason."""
    rule_id: Id
    weight_version: Id | None = None
    weights: dict[str, Annotated[StrictStr, Field(max_length=20)]] | None = None


class OpenIssueInput(Strict):
    rule_run_id: Id
    owner_id: Id | None = None


class TriageIssueInput(At):
    issue_id: Id
    action: StrictStr = "investigate"
    owner_id: Id | None = None
    due_at: StrictStr | None = None
    note: Text | None = None


class SuggestMatchInput(Strict):
    left_record_id: Id
    right_record_id: Id
    score: StrictStr
    features: dict[Id, Annotated[StrictStr, Field(max_length=40)]] = Field(min_length=1, max_length=50)
    explanation: Annotated[StrictStr, Field(min_length=1, max_length=2000)]
    uncertainty: Text | None = None
    candidate_id: Id | None = None

    @field_validator("score")
    @classmethod
    def _score(cls, v: str) -> str:
        if not _DEC.match(v) or Fraction(v) > 1:
            raise PydanticCustomError("SCORE_INVALID", "score must be a decimal string in [0, 1] with at most 6 places")
        return v


class ApproveMergeInput(Strict):
    candidate_id: Id
    decision: StrictStr = "approve"
    reason: Text | None = None


class ReverseMergeInput(Strict):
    merge_id: Id
    reason: Text


class DisableRuleInput(Strict):
    rule_id: Id
    reason: Text


class VerifyRemediationInput(Strict):
    issue_id: Id


Cell = StrictBool | StrictInt | StrictStr | None


class RowCorrection(Strict):
    """One record's correction: the cells to change (a flat map of text, integer, boolean or null); ``row_id`` itself never changes."""
    row_id: Id
    changes: dict[Id, Cell] = Field(min_length=1, max_length=200)


class CorrectDatasetRowsInput(Strict):
    """C11. Append-only: every correction becomes a NEW version of the record (row_version, supersedes_row_id, reason, the actor and the server's
    instant); the measurement reads the latest version of each record."""
    dataset_id: Id
    reason: Annotated[StrictStr, Field(min_length=1, max_length=2000)]
    corrections: list[RowCorrection] = Field(min_length=1, max_length=1000)


class RecordRefreshInput(At):
    """C12. A refresh of a dataset that happened at ``refreshed_at`` (not in the future); the server stamps when it was recorded."""
    dataset_id: Id
    refreshed_at: StrictStr


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


RegisterDatasetRequest = _request(RegisterDatasetInput, "RegisterDatasetRequest")
PublishDefinitionRequest = _request(PublishDefinitionInput, "PublishDefinitionRequest")
RunRuleRequest = _request(RunRuleInput, "RunRuleRequest")
OpenIssueRequest = _request(OpenIssueInput, "OpenIssueRequest")
TriageIssueRequest = _request(TriageIssueInput, "TriageIssueRequest")
SuggestMatchRequest = _request(SuggestMatchInput, "SuggestMatchRequest")
ApproveMergeRequest = _request(ApproveMergeInput, "ApproveMergeRequest")
ReverseMergeRequest = _request(ReverseMergeInput, "ReverseMergeRequest")
DisableRuleRequest = _request(DisableRuleInput, "DisableRuleRequest")
VerifyRemediationRequest = _request(VerifyRemediationInput, "VerifyRemediationRequest")
CorrectDatasetRowsRequest = _request(CorrectDatasetRowsInput, "CorrectDatasetRowsRequest")
RecordRefreshRequest = _request(RecordRefreshInput, "RecordRefreshRequest")


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
