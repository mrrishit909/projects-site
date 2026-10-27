"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return ``{command_id, status, result, warnings, version}``;
reads return ``{data, meta, warnings}``. Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in
``error.details[].rule_id``. Decimals are STRINGS: a JSON number is refused (FIELD_INVALID), never rounded. A client NEVER supplies a
decision instant (scored_at, published_at, created_at ...): the server stamps them; ``*_at`` inputs here are cutoffs of the analysis.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError
from retentionlab.timeutil import parse_ts

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_DEC = re.compile(r"^\d{1,14}(\.\d{1,6})?$")

Id = Annotated[StrictStr, Field(min_length=1, max_length=128)]
Text = Annotated[StrictStr, Field(max_length=2000)]
Instant = Annotated[StrictStr, Field(max_length=40)]


class Strict(BaseModel):
    """Base model: unknown fields are errors (FIELD_UNEXPECTED)."""
    model_config = ConfigDict(extra="forbid")


def _instant(v: str) -> str:
    try:
        parse_ts(v)
    except ValueError:
        raise PydanticCustomError("TIMESTAMP_INVALID", "must be an ISO-8601 timestamp with seconds and a zone") from None
    return v


def _decimal(v: str, what: str) -> str:
    if not _DEC.match(v):
        raise PydanticCustomError("DECIMAL_INVALID", f"{what} must be a non-negative decimal string with at most 6 places")
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


class Cutoff(Strict):
    """The cutoff set a command works on: every cutoff row sharing one ``prediction_at`` (D-P10-01)."""
    prediction_at: Instant

    @field_validator("prediction_at")
    @classmethod
    def _pa(cls, v: str) -> str:
        return _instant(v)


class BuildFeaturesInput(Cutoff):
    """C01. ``fields`` are checked against the registry (POST_OUTCOME_FIELD, LATENT_TRUTH, ID_FEATURE, UNKNOWN_FEATURE)."""
    fields: list[Annotated[StrictStr, Field(min_length=1, max_length=200)]] | None = Field(default=None, max_length=200)
    account_ids: list[StrictInt] | None = Field(default=None, max_length=5000)


class DefineLabelInput(Cutoff):
    """C02."""
    account_ids: list[StrictInt] | None = Field(default=None, max_length=5000)


class SplitInput(Strict):
    """C03. The three boundaries are the analysis' own parameters (not decision instants); the server stamps ``created_at``."""
    training_run_id: Id
    train_end: Instant
    validation_end: Instant
    test_end: Instant
    feature_version: Id | None = None
    label_version: Id | None = None
    seed: StrictInt = Field(default=20260101, ge=0, le=2**31 - 1)

    @field_validator("train_end", "validation_end", "test_end")
    @classmethod
    def _ends(cls, v: str) -> str:
        return _instant(v)


class FitPreprocessingInput(Strict):
    """C04. ``fit_rows`` defaults to every retained training row with a stored feature row; any other row is LEAKAGE."""
    training_run_id: Id
    fit_rows: list[Id] | None = Field(default=None, max_length=100000)


class TrainBaselineInput(Strict):
    """C05."""
    training_run_id: Id
    l2: StrictStr = "1.000000"
    iterations: StrictInt = Field(default=500, ge=1, le=5000)
    learning_rate: StrictStr = "0.100000"
    random_seed: StrictInt = Field(default=7, ge=0, le=2**31 - 1)

    @field_validator("l2", "learning_rate")
    @classmethod
    def _dec(cls, v: str, info: Any) -> str:
        _decimal(v, info.field_name)
        if info.field_name == "learning_rate" and not (Fraction(v) > 0 and Fraction(v) <= 1):
            raise PydanticCustomError("DECIMAL_INVALID", "learning_rate must be in (0, 1]")
        return v


class CalibrateInput(Strict):
    """C06. ``fit_rows`` defaults to the retained validation rows with labels; ``evaluation_rows`` (default: the retained test rows)
    must not include a fit row."""
    training_run_id: Id
    fit_rows: list[Id] | None = Field(default=None, max_length=100000)
    evaluation_rows: list[Id] | None = Field(default=None, max_length=100000)


class ScoreInput(Cutoff):
    """C07."""
    training_run_id: Id
    model: Id = "logistic_regression"


class ScenarioInput(Strict):
    """An intervention scenario declared inline (created if new, otherwise it must equal the stored one: scenarios are immutable)."""
    scenario_id: Id
    capacity: StrictInt = Field(ge=1, le=1_000_000)
    contact_cost: StrictStr
    assumed_effect: StrictStr
    margin_value: StrictStr
    selected_on: Literal["validation", "test"] = "validation"       # where K was chosen; "test" is refused THRESHOLD_ON_TEST

    @field_validator("contact_cost", "margin_value", "assumed_effect")
    @classmethod
    def _dec(cls, v: str, info: Any) -> str:
        return _decimal(v, info.field_name)


class PrioritizeInput(Cutoff):
    """C08. ``basis`` must be the risk ranking: a claim of responsiveness, uplift or treatment effect is refused."""
    training_run_id: Id
    scenario_id: Id | None = None
    scenario: ScenarioInput | None = None
    model: Id = "logistic_regression"
    basis: StrictStr = "risk_ranking"


class SimulateInput(Cutoff):
    """C09. ``experiment_id`` would name a randomised experiment that supports the assumed effect; none is run by this product."""
    training_run_id: Id
    scenario_id: Id | None = None
    scenario: ScenarioInput | None = None
    model: Id = "logistic_regression"
    experiment_id: Id | None = None


class MonitorInput(Cutoff):
    """C10. The reference cohort is a cutoff set; the feature and bins default to the declared drift diagnostic."""
    training_run_id: Id
    reference_prediction_at: Instant
    model: Id = "logistic_regression"
    feature: Id | None = None
    bins: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    floor: StrictStr = "0.000100"
    threshold: StrictStr = "0.200000"

    @field_validator("reference_prediction_at")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _instant(v)

    @field_validator("floor", "threshold")
    @classmethod
    def _dec(cls, v: str, info: Any) -> str:
        return _decimal(v, info.field_name)


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


BuildFeaturesRequest = _request(BuildFeaturesInput, "BuildFeaturesRequest")
DefineLabelRequest = _request(DefineLabelInput, "DefineLabelRequest")
SplitRequest = _request(SplitInput, "SplitRequest")
FitPreprocessingRequest = _request(FitPreprocessingInput, "FitPreprocessingRequest")
TrainBaselineRequest = _request(TrainBaselineInput, "TrainBaselineRequest")
CalibrateRequest = _request(CalibrateInput, "CalibrateRequest")
ScoreRequest = _request(ScoreInput, "ScoreRequest")
PrioritizeRequest = _request(PrioritizeInput, "PrioritizeRequest")
SimulateRequest = _request(SimulateInput, "SimulateRequest")
MonitorRequest = _request(MonitorInput, "MonitorRequest")


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
