"""Domain errors and reason codes (docs/contracts.md D-01..D-05)."""
from __future__ import annotations

from typing import Any

SELF_APPROVAL = "SELF_APPROVAL"
DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
STEP_NOT_READY = "STEP_NOT_READY"
MISSING_REQUIRED_DOCUMENT = "MISSING_REQUIRED_DOCUMENT"
CASE_ALREADY_COMPLETE = "CASE_ALREADY_COMPLETE"
PAUSE_REASON_NOT_CONFIGURED = "PAUSE_REASON_NOT_CONFIGURED"
WORKFLOW_VERSION_NOT_PUBLISHED = "WORKFLOW_VERSION_NOT_PUBLISHED"
DECISION_CONFLICT = "DECISION_CONFLICT"
# Structural failures beyond the contract list.
MALFORMED_RECORD = "MALFORMED_RECORD"
ORPHAN_REFERENCE = "ORPHAN_REFERENCE"
DUPLICATE_ID = "DUPLICATE_ID"
CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
INVALID_WINDOW = "INVALID_WINDOW"
ROLE_MISMATCH = "ROLE_MISMATCH"
INVALID_TRANSITION = "INVALID_TRANSITION"

#: Reasons that reject a whole case with its child rows at ingest, in priority order.
CASE_REASONS = (WORKFLOW_VERSION_NOT_PUBLISHED, DEPENDENCY_CYCLE, SELF_APPROVAL, STEP_NOT_READY,
                MISSING_REQUIRED_DOCUMENT, CASE_ALREADY_COMPLETE, PAUSE_REASON_NOT_CONFIGURED,
                ORPHAN_REFERENCE)


class DomainError(Exception):
    """A business-rule violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str, path: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.details: dict[str, Any] = dict(details or {})
