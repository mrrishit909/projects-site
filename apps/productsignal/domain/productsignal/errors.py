"""Domain errors and reason codes (docs/contracts.md D-01..D-05)."""
from __future__ import annotations

from typing import Any

# Ingest rejection codes of the contract (D-03, D-05).
ASSIGNMENT_CONFLICT = "ASSIGNMENT_CONFLICT"
EXPOSURE_BEFORE_ASSIGNMENT = "EXPOSURE_BEFORE_ASSIGNMENT"
DEPENDENT_REJECTED = "DEPENDENT_REJECTED"
UNKNOWN_ASSIGNMENT = "UNKNOWN_ASSIGNMENT"
# Ingest codes the contract does not list (README.md): structure, ids, references.
MALFORMED_RECORD = "MALFORMED_RECORD"
DUPLICATE_ID = "DUPLICATE_ID"
UNKNOWN_ACCOUNT = "UNKNOWN_ACCOUNT"
UNKNOWN_USER = "UNKNOWN_USER"
UNKNOWN_EVENT = "UNKNOWN_EVENT"
UNKNOWN_EXPERIMENT_VERSION = "UNKNOWN_EXPERIMENT_VERSION"
UNKNOWN_UNIT = "UNKNOWN_UNIT"
UNKNOWN_VARIANT = "UNKNOWN_VARIANT"
INELIGIBLE_UNIT = "INELIGIBLE_UNIT"
INVALID_INTERVAL = "INVALID_INTERVAL"
IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
UNSUPPORTED_UNIT_TYPE = "UNSUPPORTED_UNIT_TYPE"
# Command and analysis reasons.
INVALID_WINDOW = "INVALID_WINDOW"
INVALID_GROUP = "INVALID_GROUP"
INVALID_STATE = "INVALID_STATE"
UNIT_MISMATCH = "UNIT_MISMATCH"
NOT_INTENTION_TO_TREAT = "NOT_INTENTION_TO_TREAT"
TREATMENT_DEPENDENT_EXCLUSION = "TREATMENT_DEPENDENT_EXCLUSION"
PLAN_NOT_FROZEN = "PLAN_NOT_FROZEN"
INTERIM_RUN_CANNOT_SHIP = "INTERIM_RUN_CANNOT_SHIP"
SRM_MISMATCH_BLOCKS_DECISION = "SRM_MISMATCH_BLOCKS_DECISION"
SEGMENT_NOT_A_DECISION_BASIS = "SEGMENT_NOT_A_DECISION_BASIS"


class DomainError(Exception):
    """A business-rule violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str, path: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.details: dict[str, Any] = dict(details or {})
