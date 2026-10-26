"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return
``{command_id, status, result, warnings, version}``; reads return ``{data, meta, warnings}``.
Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in
``error.details[].rule_id``.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticCustomError

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


class Strict(BaseModel):
    """Base model: unknown fields are errors (FIELD_UNEXPECTED)."""
    model_config = ConfigDict(extra="forbid")


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


class IngestInput(Strict):
    batch: dict[str, Any]


class ShipmentInput(Strict):
    shipment_id: StrictStr = Field(min_length=1, max_length=128)


class ReturnInput(Strict):
    shipment_line_id: StrictStr = Field(min_length=1, max_length=128)
    returned_quantity: StrictInt
    credit_amount: StrictStr
    credit_date: StrictStr
    expected_version: StrictInt
    reason: StrictStr | None = Field(default=None, max_length=500)

    @field_validator("returned_quantity")
    @classmethod
    def _qty(cls, v: int) -> int:
        if v < 1:
            raise PydanticCustomError("RETURN_QUANTITY_NOT_POSITIVE",
                                      "returned_quantity must be at least 1")
        return v

    @field_validator("credit_amount")
    @classmethod
    def _credit(cls, v: str) -> str:
        try:
            d = Decimal(v)
        except InvalidOperation:
            d = None
        if d is None or not d.is_finite():
            raise PydanticCustomError("MONEY_INVALID", "credit_amount must be a decimal string")
        return v

    @field_validator("credit_date")
    @classmethod
    def _date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise PydanticCustomError("DATE_INVALID", "credit_date must be YYYY-MM-DD") from None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise PydanticCustomError("DATE_INVALID", "credit_date must be YYYY-MM-DD")
        return v

    @field_validator("expected_version")
    @classmethod
    def _version(cls, v: int) -> int:
        if v < 1:
            raise PydanticCustomError("VERSION_INVALID", "expected_version must be at least 1")
        return v


class IngestRequest(Envelope):
    input: IngestInput


class ShipmentRequest(Envelope):
    input: ShipmentInput


class ReturnRequest(Envelope):
    input: ReturnInput


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
