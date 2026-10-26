"""Domain errors and reason codes (docs/contracts.md D-02, D-03, D-04, D-06)."""
from __future__ import annotations

from typing import Any

CURRENCY_NOT_ISO4217 = "CURRENCY_NOT_ISO4217"
FX_RATE_MISSING = "FX_RATE_MISSING"
COST_VERSION_MISSING = "COST_VERSION_MISSING"
COST_VERSION_AMBIGUOUS = "COST_VERSION_AMBIGUOUS"
RETURN_EXCEEDS_REMAINING = "RETURN_EXCEEDS_REMAINING"
CREDIT_SIGN_REVERSED = "CREDIT_SIGN_REVERSED"
INVALID_WINDOW = "INVALID_WINDOW"
SHIPMENT_LINE_UNKNOWN = "SHIPMENT_LINE_UNKNOWN"
FREIGHT_ALREADY_ALLOCATED = "FREIGHT_ALREADY_ALLOCATED"
# Review findings R-01 / R-06 (docs/contracts.md D-08).
SHIPPED_EXCEEDS_ORDERED = "SHIPPED_EXCEEDS_ORDERED"
SHIPMENT_LINE_ORDER_MISMATCH = "SHIPMENT_LINE_ORDER_MISMATCH"
# Additions beyond the coordinator's list (structural ingest failures).
MALFORMED_RECORD = "MALFORMED_RECORD"
ORPHAN_REFERENCE = "ORPHAN_REFERENCE"
CONTRACT_MISMATCH = "CONTRACT_MISMATCH"


class DomainError(Exception):
    """A business-rule violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str, path: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.details: dict[str, Any] = dict(details or {})
