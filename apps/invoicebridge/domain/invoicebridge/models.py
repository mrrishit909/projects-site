"""Typed records and the Population (docs/contracts.md D-01..D-05).

``parse_*`` accept a raw input row (strings, as in the fixtures) and a database row (Decimal, datetime, date) alike and
raise ``DomainError(MALFORMED_RECORD)`` for anything that is not exactly the documented shape. Money is Decimal, never
float; quantities carry at most 4 decimals, unit prices and rates at most 6, money at most 2.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .contract import DEFAULT_TOLERANCES
from .errors import MALFORMED_RECORD, DomainError
from .money import dec
from .timeutil import parse_date, parse_ts

SHA = re.compile(r"^[0-9a-f]{64}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
Row = dict[str, Any]


def _bad(name: str, why: str) -> DomainError:
    return DomainError(MALFORMED_RECORD, f"{name} {why}", name)


def _str(row: Row, name: str, optional: bool = False, maxlen: int = 256) -> str | None:
    v = row.get(name)
    if v is None and optional:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > maxlen:
        raise _bad(name, "must be a non-empty string")
    return v


def _bool(row: Row, name: str) -> bool:
    v = row.get(name)
    if not isinstance(v, bool):
        raise _bad(name, "must be true or false")
    return v


def _ts(row: Row, name: str, optional: bool = False) -> datetime | None:
    v = row.get(name)
    if v is None and optional:
        return None
    try:
        return parse_ts(v)
    except ValueError as exc:
        raise _bad(name, str(exc)) from None


def _date(row: Row, name: str) -> date:
    try:
        return parse_date(row.get(name))
    except ValueError as exc:
        raise _bad(name, str(exc)) from None


def _dec(row: Row, name: str, dp: int, optional: bool = False) -> Decimal | None:
    v = row.get(name)
    if v is None and optional:
        return None
    return dec(v, name, dp)


@dataclass(frozen=True)
class Vendor:
    vendor_id: str
    vendor_name: str
    tax_reference: str
    currency: str
    active: bool


@dataclass(frozen=True)
class PurchaseOrder:
    po_id: str
    vendor_id: str
    ordered_at: datetime
    status: str
    currency: str


@dataclass(frozen=True)
class PoLine:
    po_line_id: str
    po_id: str
    product_code: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    po_line_id: str
    received_quantity: Decimal
    received_at: datetime
    reversed: bool


@dataclass(frozen=True)
class InvoiceLine:
    invoice_line_id: str
    invoice_id: str
    po_line_id: str
    quantity: Decimal
    unit_price: Decimal
    line_amount: Decimal | None = None      # the extracted line amount, when the source states one (per-line rounding check)


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    vendor_id: str
    invoice_number: str
    invoice_date: date
    currency: str
    tax_rate: Decimal
    freight: Decimal
    invoice_discount: Decimal
    declared_total: Decimal
    created_by: str
    source_sha256: str
    source_filename: str
    idempotency_key: str
    imported_at: datetime
    lines: tuple[InvoiceLine, ...] = ()
    #: True: validated; False: failed C02; None: not validated yet (the invoice is outside the book).
    valid: bool | None = True


@dataclass(frozen=True)
class CreditNote:
    credit_id: str
    invoice_id: str
    credit_amount: Decimal
    credited_at: datetime | None = None


@dataclass(frozen=True)
class Policy:
    policy_id: str
    version_number: int
    amount_limit: Decimal
    reviewer_role: str
    escalation_role: str | None
    effective_from: datetime


@dataclass(frozen=True)
class Approval:
    approval_id: str
    invoice_id: str
    actor_id: str
    actor_role: str
    decision: str
    decided_at: datetime
    reason: str | None = None


@dataclass(frozen=True)
class ExportRequest:
    batch_id: str
    idempotency_key: str
    invoice_ids: tuple[str, ...]
    exported_at: datetime


@dataclass(frozen=True)
class ExceptionRecord:
    """A stored exception: supplies the id of a derived (invoice, type) pair."""
    exception_id: str
    invoice_id: str
    exception_type: str


@dataclass(frozen=True)
class Assignment:
    exception_id: str
    owner_id: str
    assigned_at: datetime


@dataclass(frozen=True)
class Tolerances:
    price_per_unit: Decimal
    rounding_per_line: Decimal
    rounding_per_invoice: Decimal


def parse_tolerances(raw: Row | None) -> Tolerances:
    raw = {**DEFAULT_TOLERANCES, **(raw or {})}
    t = Tolerances(*(dec(raw[k], k, 6) for k in ("price_per_unit", "rounding_per_line", "rounding_per_invoice")))
    if min(t.price_per_unit, t.rounding_per_line, t.rounding_per_invoice) < 0:
        raise _bad("tolerances", "must not be negative")
    return t


def parse_vendor(r: Row) -> Vendor:
    cur = _str(r, "currency")
    if not CURRENCY.match(cur or ""):
        raise _bad("currency", "must be a three-letter upper-case code")
    return Vendor(_str(r, "vendor_id"), _str(r, "vendor_name"), _str(r, "tax_reference"), cur, _bool(r, "active"))  # type: ignore[arg-type]


def parse_po(r: Row) -> PurchaseOrder:
    cur = _str(r, "currency")
    if not CURRENCY.match(cur or ""):
        raise _bad("currency", "must be a three-letter upper-case code")
    return PurchaseOrder(_str(r, "po_id"), _str(r, "vendor_id"), _ts(r, "ordered_at"), _str(r, "status"), cur)  # type: ignore[arg-type]


def parse_po_line(r: Row) -> PoLine:
    price = _dec(r, "unit_price", 6)
    if price < 0:  # type: ignore[operator]
        raise _bad("unit_price", "must not be negative")
    return PoLine(_str(r, "po_line_id"), _str(r, "po_id"), _str(r, "product_code"), _dec(r, "quantity", 4), price)  # type: ignore[arg-type]


def parse_receipt(r: Row) -> Receipt:
    return Receipt(_str(r, "receipt_id"), _str(r, "po_line_id"), _dec(r, "received_quantity", 4),  # type: ignore[arg-type]
                   _ts(r, "received_at"), _bool(r, "reversed"))  # type: ignore[arg-type]


def parse_line(r: Row) -> InvoiceLine:
    price = _dec(r, "unit_price", 6)
    if price < 0:  # type: ignore[operator]
        raise _bad("unit_price", "must not be negative")
    return InvoiceLine(_str(r, "invoice_line_id"), _str(r, "invoice_id"), _str(r, "po_line_id"),  # type: ignore[arg-type]
                       _dec(r, "quantity", 4), price, _dec(r, "line_amount", 2, optional=True))  # type: ignore[arg-type]


def parse_invoice(r: Row, lines: tuple[InvoiceLine, ...] = ()) -> Invoice:
    cur = _str(r, "currency")
    if not CURRENCY.match(cur or ""):
        raise _bad("currency", "must be a three-letter upper-case code")
    sha = _str(r, "source_sha256")
    if not SHA.match(sha or ""):
        raise _bad("source_sha256", "must be 64 lower-case hex digits")
    rate, freight, disc = _dec(r, "tax_rate", 6), _dec(r, "freight", 2), _dec(r, "invoice_discount", 2)
    if not (0 <= rate <= 1):  # type: ignore[operator]
        raise _bad("tax_rate", "must be between 0 and 1")
    if freight < 0 or disc < 0:  # type: ignore[operator]
        raise _bad("freight" if freight < 0 else "invoice_discount", "must not be negative")  # type: ignore[operator]
    valid = r.get("validity", True)
    if valid is not None and not isinstance(valid, bool):
        raise _bad("validity", "must be true, false or null")
    return Invoice(_str(r, "invoice_id"), _str(r, "vendor_id"), _str(r, "invoice_number"), _date(r, "invoice_date"),  # type: ignore[arg-type]
                   cur, rate, freight, disc, _dec(r, "declared_total", 2), _str(r, "created_by"), sha,  # type: ignore[arg-type]
                   _str(r, "source_filename"), _str(r, "idempotency_key"), _ts(r, "imported_at"), lines, valid)  # type: ignore[arg-type]


def parse_credit(r: Row) -> CreditNote:
    return CreditNote(_str(r, "credit_id"), _str(r, "invoice_id"), _dec(r, "credit_amount", 2),  # type: ignore[arg-type]
                      _ts(r, "credited_at", optional=True))


def parse_policy(r: Row) -> Policy:
    v = r.get("version_number")
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise _bad("version_number", "must be a positive integer")
    limit = _dec(r, "amount_limit", 2)
    if limit < 0:  # type: ignore[operator]
        raise _bad("amount_limit", "must not be negative")
    return Policy(_str(r, "policy_id"), v, limit, _str(r, "reviewer_role"),  # type: ignore[arg-type]
                  _str(r, "escalation_role", optional=True), _ts(r, "effective_from"))  # type: ignore[arg-type]


def parse_approval(r: Row) -> Approval:
    decision = _str(r, "decision")
    if decision not in ("approve", "reject"):
        raise _bad("decision", "must be approve or reject")
    if decision == "reject" and _str(r, "reason", optional=True) is None:
        raise _bad("reason", "is required for a rejection")
    return Approval(_str(r, "approval_id"), _str(r, "invoice_id"), _str(r, "actor_id"), _str(r, "actor_role"),  # type: ignore[arg-type]
                    decision, _ts(r, "decided_at"), _str(r, "reason", optional=True))  # type: ignore[arg-type]


def parse_export_request(r: Row) -> ExportRequest:
    ids = r.get("invoice_ids")
    if not isinstance(ids, (list, tuple)) or not all(isinstance(i, str) and i for i in ids):
        raise _bad("invoice_ids", "must be a list of invoice ids")
    return ExportRequest(_str(r, "batch_id"), _str(r, "idempotency_key"), tuple(ids), _ts(r, "exported_at"))  # type: ignore[arg-type]


@dataclass
class Population:
    """Everything the derivation reads. Facts only: statuses are derived (``book.derive``)."""
    vendors: list[Vendor] = field(default_factory=list)
    purchase_orders: list[PurchaseOrder] = field(default_factory=list)
    po_lines: list[PoLine] = field(default_factory=list)
    receipts: list[Receipt] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    credit_notes: list[CreditNote] = field(default_factory=list)
    approval_policies: list[Policy] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    export_requests: list[ExportRequest] = field(default_factory=list)
    exceptions: list[ExceptionRecord] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    tolerances: Tolerances = field(default_factory=lambda: parse_tolerances(None))

    @classmethod
    def from_rows(cls, rows: dict[str, list[Row]], tolerances: Row | None = None) -> "Population":
        """Assemble from trusted rows (database or already-validated input). The same parsers as ingest, so a stored row
        that no longer parses is an error, not a silent skip."""
        lines: dict[str, list[InvoiceLine]] = {}
        for r in rows.get("invoice_lines", []):
            ln = parse_line(r)
            lines.setdefault(ln.invoice_id, []).append(ln)
        return cls(
            vendors=[parse_vendor(r) for r in rows.get("vendors", [])],
            purchase_orders=[parse_po(r) for r in rows.get("purchase_orders", [])],
            po_lines=[parse_po_line(r) for r in rows.get("po_lines", [])],
            receipts=[parse_receipt(r) for r in rows.get("receipts", [])],
            invoices=[parse_invoice(r, tuple(lines.get(r["invoice_id"], []))) for r in rows.get("invoices", [])],
            credit_notes=[parse_credit(r) for r in rows.get("credit_notes", [])],
            approval_policies=[parse_policy(r) for r in rows.get("approval_policies", [])],
            approvals=[parse_approval(r) for r in rows.get("approvals", [])],
            export_requests=[parse_export_request(r) for r in rows.get("export_requests", [])],
            exceptions=[ExceptionRecord(r["exception_id"], r["invoice_id"], r["exception_type"])
                        for r in rows.get("exceptions", [])],
            assignments=[Assignment(r["exception_id"], r["owner_id"], parse_ts(r["assigned_at"]))
                         for r in rows.get("exception_assignments", [])],
            tolerances=parse_tolerances(tolerances),
        )
