"""Domain errors and reason codes (docs/contracts.md D-01..D-05, tests/fixtures/golden/CALCULATION.md D-P8-01..13)."""
from __future__ import annotations

from typing import Any

# Rejection and refusal codes listed by D-P8-11.
NEGATIVE_QUANTITY = "NEGATIVE_QUANTITY"
MISSING_FIELD = "MISSING_FIELD"
BACKFILL_OVERLAP = "BACKFILL_OVERLAP"
CHECKPOINT_REGRESSION = "CHECKPOINT_REGRESSION"
CHECKPOINT_GAP = "CHECKPOINT_GAP"
DUPLICATE_ID = "DUPLICATE_ID"
DEPENDENT_REJECTED = "DEPENDENT_REJECTED"
UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
UNKNOWN_BATCH = "UNKNOWN_BATCH"
UNKNOWN_RUN = "UNKNOWN_RUN"
UNKNOWN_TASK_RUN = "UNKNOWN_TASK_RUN"
UNKNOWN_BACKFILL = "UNKNOWN_BACKFILL"
# Codes the contract does not list (README, assumptions A-xx).
SCHEMA_CHANGED = "SCHEMA_CHANGED"            # D-01 / P08-TEST-04
CURSOR_LOOP = "CURSOR_LOOP"                  # D-01 / P08-TEST-10
RETRY_TOO_SOON = "RETRY_TOO_SOON"            # D-01 / P08-TEST-03
RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
INVALID_FIELD = "INVALID_FIELD"
UNKNOWN_OP = "UNKNOWN_OP"
DELETE_TARGET_UNKNOWN = "DELETE_TARGET_UNKNOWN"
MALFORMED_RECORD = "MALFORMED_RECORD"
PARTITION_ALIGNMENT = "PARTITION_ALIGNMENT"
INVALID_RANGE = "INVALID_RANGE"
EVENT_IN_FUTURE = "EVENT_IN_FUTURE"          # D-09 / R8-01: an event dated after its batch's arrival or after the cutoff
WATERMARK_REGRESSION = "WATERMARK_REGRESSION"  # D-09 / R8-02: a publication's watermark earlier than the previous one's
FETCH_SESSION_REQUIRED = "FETCH_SESSION_REQUIRED"  # D-09 / R8-06

REJECTION_CODES = (NEGATIVE_QUANTITY, MISSING_FIELD, BACKFILL_OVERLAP, CHECKPOINT_REGRESSION, CHECKPOINT_GAP, DUPLICATE_ID,
                   DEPENDENT_REJECTED, UNKNOWN_SOURCE, UNKNOWN_BATCH, UNKNOWN_RUN, UNKNOWN_TASK_RUN, UNKNOWN_BACKFILL)


class DomainError(Exception):
    """A business-rule violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str, path: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.details: dict[str, Any] = dict(details or {})
