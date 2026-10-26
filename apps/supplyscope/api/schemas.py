"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return
``{command_id, status, result, warnings, version}``; reads return ``{data, meta, warnings}``.
Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in ``error.details[].rule_id``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

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
            raise PydanticCustomError("IDEMPOTENCY_KEY_INVALID", "idempotency_key must be 1-128 of A-Za-z0-9._:-")
        return v


class Instants(Strict):
    """Inputs with instant fields: each is validated as an ISO-8601 timestamp with a zone."""

    @field_validator("*", mode="before")
    @classmethod
    def _stamps(cls, v: Any, info: Any) -> Any:
        if info.field_name in cls.INSTANTS and isinstance(v, str):
            _instant(v)
        return v

    INSTANTS: ClassVar[tuple[str, ...]] = ()


class LoadMovementsInput(Strict):
    movements: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


class ReconstructInput(Instants):
    INSTANTS: ClassVar[tuple[str, ...]] = ("as_of",)
    as_of: StrictStr
    product_id: Id | None = None
    location_id: Id | None = None


class ForecastInput(Instants):
    INSTANTS: ClassVar[tuple[str, ...]] = ("cutoff",)
    cutoff: StrictStr
    horizon_days: StrictInt = Field(ge=1, le=90)
    product_id: Id | None = None
    location_id: Id | None = None


class ReplenishInput(Instants):
    INSTANTS: ClassVar[tuple[str, ...]] = ("as_of",)
    as_of: StrictStr
    scenario_id: Id | None = None
    product_id: Id | None = None
    location_id: Id | None = None


class ArrivalInput(Instants):
    INSTANTS: ClassVar[tuple[str, ...]] = ("at",)
    po_line_id: Id
    at: StrictStr
    location_id: Id
    quantity: StrictInt | None = Field(default=None, ge=1, le=10**9)
    receipt_id: Id | None = None


class UnmetInput(Instants):
    INSTANTS: ClassVar[tuple[str, ...]] = ("occurred_at",)
    scenario_id: Id
    product_id: Id
    location_id: Id
    quantity: StrictInt = Field(ge=1, le=10**9)
    occurred_at: StrictStr               # required (R3-02): never defaulted to the server clock
    demand_ref: Id | None = None
    policy: StrictStr | None = None


class CompareInput(Strict):
    scenario_ids: list[Id] = Field(min_length=2, max_length=10)
    product_id: Id
    location_id: Id
    days: StrictInt = Field(default=60, ge=7, le=365)
    mean_demand: float = Field(default=5.0, ge=0, le=10000, allow_inf_nan=False)
    lead_low: StrictInt = Field(default=3, ge=1, le=90)
    lead_high: StrictInt = Field(default=7, ge=1, le=90)
    initial_stock: StrictInt = Field(default=0, ge=0, le=10**9)


class ReviewSupplierInput(Instants):
    INSTANTS: ClassVar[tuple[str, ...]] = ("as_of",)
    supplier_id: Id
    as_of: StrictStr


class ExportInput(Instants):
    INSTANTS: ClassVar[tuple[str, ...]] = ("as_of",)
    as_of: StrictStr | None = None
    scenario_id: Id | None = None
    product_id: Id | None = None
    supplier_id: Id | None = None
    draft_order_ids: list[Id] | None = Field(default=None, max_length=1000)


class AnyInput(BaseModel):
    """Extension commands accept any object; they answer 501."""
    model_config = ConfigDict(extra="allow")


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


LoadMovementsRequest = _request(LoadMovementsInput, "LoadMovementsRequest")
ReconstructRequest = _request(ReconstructInput, "ReconstructRequest")
ForecastRequest = _request(ForecastInput, "ForecastRequest")
ReplenishRequest = _request(ReplenishInput, "ReplenishRequest")
ArrivalRequest = _request(ArrivalInput, "ArrivalRequest")
UnmetRequest = _request(UnmetInput, "UnmetRequest")
CompareRequest = _request(CompareInput, "CompareRequest")
ReviewSupplierRequest = _request(ReviewSupplierInput, "ReviewSupplierRequest")
ExportRequest = _request(ExportInput, "ExportRequest")
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
