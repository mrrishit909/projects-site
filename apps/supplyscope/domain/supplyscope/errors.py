"""Domain errors and reason codes (docs/contracts.md D-01..D-06)."""
from __future__ import annotations

from typing import Any

DUPLICATE_MOVEMENT_ID = "DUPLICATE_MOVEMENT_ID"
DUPLICATE_MOVEMENT_CONFLICT = "DUPLICATE_MOVEMENT_CONFLICT"
RECEIPT_BEFORE_ORDER = "RECEIPT_BEFORE_ORDER"
RECEIPT_EXCEEDS_ORDERED = "RECEIPT_EXCEEDS_ORDERED"
RECEIPT_BEFORE_LEAD_TIME = "RECEIPT_BEFORE_LEAD_TIME"
UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
MALFORMED_RECORD = "MALFORMED_RECORD"
DUPLICATE_ID = "DUPLICATE_ID"
CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
INVALID_WINDOW = "INVALID_WINDOW"
FORECAST_CUTOFF_IN_FUTURE = "FORECAST_CUTOFF_IN_FUTURE"
UNSUPPORTED_SERVICE_TARGET = "UNSUPPORTED_SERVICE_TARGET"
UNMET_POLICY_CONFLICT = "UNMET_POLICY_CONFLICT"
POLICY_SEED_MISMATCH = "POLICY_SEED_MISMATCH"
UNKNOWN_STATE = "UNKNOWN_STATE"
UNKNOWN_POLICY = "UNKNOWN_POLICY"
#: R3-06: a parameter row whose target position is below its reorder point (D-02: a triggered order would be 0 or negative).
REPLENISHMENT_PARAMS_INVALID = "REPLENISHMENT_PARAMS_INVALID"
#: D-07: the request's dataset_version is not the current one (API).
STALE_DATASET_VERSION = "STALE_DATASET_VERSION"
#: A flag (a warning on a reconstruction), not an error.
NEGATIVE_STOCK = "NEGATIVE_STOCK"
#: R3-07: available (clamped on hand - reserved) is below zero for a (product, location): a flag, not an error.
NEGATIVE_AVAILABLE = "NEGATIVE_AVAILABLE"


class DomainError(Exception):
    """A business-rule violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str, path: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.details: dict[str, Any] = dict(details or {})
