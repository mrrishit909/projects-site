"""Invoice amounts, identity and validation (D-01, D-02, D-05).

Tax is computed once per invoice, at document level, on the UNROUNDED subtotal (D-P5-1); subtotal and tax are each
rounded ROUND_HALF_UP to 2 dp; total = subtotal + tax + freight - invoice_discount, in that declared order.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .money import D0, exact, q2, s2
from .models import Invoice, InvoiceLine, Vendor


@exact
def line_extended(line: InvoiceLine) -> Decimal:
    """quantity x unit_price at full precision (4 dp x 6 dp: exact)."""
    return line.quantity * line.unit_price


@exact
def invoice_amounts(inv: Invoice) -> tuple[Decimal, Decimal, Decimal]:
    """(subtotal, tax, total), money at 2 dp."""
    raw = sum((line_extended(l) for l in inv.lines), D0)
    sub = q2(raw)
    tax = q2(raw * inv.tax_rate)
    return sub, tax, sub + tax + inv.freight - inv.invoice_discount


def normalise_number(number: str) -> str:
    """D-P5-6: upper-case, keep letters and digits only (``inv-1001`` and ``INV 1001`` are INV1001)."""
    return re.sub(r"[^A-Z0-9]", "", number.upper())


def identity_key(inv: Invoice) -> str:
    """D-01 with D-P5-4: vendor, normalised number, invoice date and the COMPUTED total."""
    return f"{inv.vendor_id}|{normalise_number(inv.invoice_number)}|{inv.invoice_date.isoformat()}|{s2(invoice_amounts(inv)[2])}"


def validate_invoice(inv: Invoice, vendor: Vendor | None) -> list[tuple[str, str]]:
    """C02 hard validation: ``[(rule_id, message)]``, empty when the invoice is valid. Rounding differences are NOT
    validation failures: they are exceptions at match time (ROUNDING_EXCEPTION)."""
    out: list[tuple[str, str]] = []
    if vendor is None:
        out.append(("UNKNOWN_VENDOR", "the vendor is not in the vendor master"))
    elif not vendor.active:
        out.append(("VENDOR_INACTIVE", "the vendor is not active"))
    if not inv.lines:
        out.append(("NO_LINES", "an invoice needs at least one line"))
    if invoice_amounts(inv)[2] < 0:
        out.append(("NEGATIVE_TOTAL", "the computed total is negative; a negative payable is a credit note"))
    if inv.invoice_date > inv.imported_at.date():
        out.append(("INVOICE_DATE_IN_FUTURE", "the invoice date is after the day it was imported"))
    return out
