"""Request and response envelopes (docs/api-contract.md).

Commands take ``{request_id, dataset_version, idempotency_key, input}`` and return
``{command_id, status, result, warnings, version}``; reads return ``{data, meta, warnings}``.
Custom validators raise ``PydanticCustomError`` whose type is the rule_id reported in ``error.details[].rule_id``.
Money, quantities and rates are decimal STRINGS: a JSON number is refused (FIELD_INVALID), never rounded.
"""
from __future__ import annotations

import re
from typing import Annotated, Any

from invoicebridge.timeutil import parse_ts
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator
from pydantic_core import PydanticCustomError

_TOKEN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

Id = Annotated[StrictStr, Field(min_length=1, max_length=128)]
Decimal_ = Annotated[StrictStr, Field(min_length=1, max_length=40, pattern=r"^-?\d+(\.\d+)?$")]


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


class InvoiceLineInput(Strict):
    invoice_line_id: Id
    po_line_id: Id
    quantity: Decimal_
    unit_price: Decimal_
    line_amount: Decimal_ | None = None


class ImportInvoiceInput(Strict):
    """C01: one extracted invoice. ``created_by`` is the actor; ``idempotency_key`` is the envelope's."""
    invoice_id: Id
    vendor_id: Id
    invoice_number: Id
    invoice_date: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: StrictStr = Field(pattern=r"^[A-Z]{3}$")
    tax_rate: Decimal_
    freight: Decimal_ = "0.00"
    invoice_discount: Decimal_ = "0.00"
    declared_total: Decimal_
    source_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_filename: Id
    imported_at: StrictStr | None = None
    lines: list[InvoiceLineInput] = Field(min_length=1, max_length=500)

    @field_validator("imported_at")
    @classmethod
    def _at(cls, v: str | None) -> str | None:
        return _instant(v)


class InvoiceRef(Strict):
    invoice_id: Id


class ValidateInput(InvoiceRef):
    pass


class FindDuplicatesInput(InvoiceRef):
    pass


class MatchInput(InvoiceRef):
    pass


class AssignExceptionInput(Strict):
    exception_id: Id
    owner_id: Id
    note: StrictStr | None = Field(default=None, max_length=500)
    assigned_at: StrictStr | None = None

    @field_validator("assigned_at")
    @classmethod
    def _at(cls, v: str | None) -> str | None:
        return _instant(v)


class ApproveInput(InvoiceRef):
    approval_id: Id | None = None
    decided_at: StrictStr | None = None

    @field_validator("decided_at")
    @classmethod
    def _at(cls, v: str | None) -> str | None:
        return _instant(v)


class RejectInput(InvoiceRef):
    reason: StrictStr = Field(max_length=500)
    approval_id: Id | None = None
    decided_at: StrictStr | None = None

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        if not v.strip():
            raise PydanticCustomError("REASON_REQUIRED", "a rejection needs a reason")
        return v

    @field_validator("decided_at")
    @classmethod
    def _at(cls, v: str | None) -> str | None:
        return _instant(v)


class ExportInput(Strict):
    batch_id: Id
    invoice_ids: list[Id] = Field(min_length=1, max_length=500)
    exported_at: StrictStr | None = None

    @field_validator("exported_at")
    @classmethod
    def _at(cls, v: str | None) -> str | None:
        return _instant(v)


class CreditNoteInput(Strict):
    credit_id: Id
    invoice_id: Id
    credit_amount: Decimal_
    reason: StrictStr | None = Field(default=None, max_length=500)
    credited_at: StrictStr | None = None

    @field_validator("credited_at")
    @classmethod
    def _at(cls, v: str | None) -> str | None:
        return _instant(v)


class AnyInput(BaseModel):
    """Extension commands accept any object; they answer 501."""
    model_config = ConfigDict(extra="allow")


def _request(input_model: type[BaseModel], name: str) -> type[Envelope]:
    return type(name, (Envelope,), {"__annotations__": {"input": input_model}})  # type: ignore[return-value]


ImportInvoiceRequest = _request(ImportInvoiceInput, "ImportInvoiceRequest")
ValidateInvoiceRequest = _request(ValidateInput, "ValidateInvoiceRequest")
FindDuplicatesRequest = _request(FindDuplicatesInput, "FindDuplicatesRequest")
MatchRequest = _request(MatchInput, "MatchRequest")
AssignExceptionRequest = _request(AssignExceptionInput, "AssignExceptionRequest")
ApproveRequest = _request(ApproveInput, "ApproveRequest")
RejectRequest = _request(RejectInput, "RejectRequest")
ExportPayableRequest = _request(ExportInput, "ExportPayableRequest")
CreditNoteRequest = _request(CreditNoteInput, "CreditNoteRequest")
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
