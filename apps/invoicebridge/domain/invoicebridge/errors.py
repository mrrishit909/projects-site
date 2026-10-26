"""Domain errors and reason codes (docs/contracts.md D-01..D-05)."""
from __future__ import annotations

from typing import Any

# Ingest rejection codes (D-05).
UNKNOWN_PO_LINE = "UNKNOWN_PO_LINE"
UNKNOWN_VENDOR = "UNKNOWN_VENDOR"
UNKNOWN_PO = "UNKNOWN_PO"
NON_POSITIVE_QUANTITY = "NON_POSITIVE_QUANTITY"
DEPENDENT_REJECTED = "DEPENDENT_REJECTED"
# Ingest codes the contract does not list (listed in README.md): structure, ids, amounts, orphans.
MALFORMED_RECORD = "MALFORMED_RECORD"
DUPLICATE_ID = "DUPLICATE_ID"
UNKNOWN_INVOICE = "UNKNOWN_INVOICE"
NON_POSITIVE_AMOUNT = "NON_POSITIVE_AMOUNT"
CREDIT_EXCEEDS_INVOICE = "CREDIT_EXCEEDS_INVOICE"
# Merge reasons.
DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
DUPLICATE_SOURCE_BYTES = "DUPLICATE_SOURCE_BYTES"
# Approval verdicts (``approvals.invalid_records``).
NOT_MATCHED = "NOT_MATCHED"
SELF_APPROVAL = "SELF_APPROVAL"
ROLE_OR_LIMIT = "ROLE_OR_LIMIT"
NOT_REVIEWABLE = "NOT_REVIEWABLE"
REJECT_AFTER_APPROVAL = "REJECT_AFTER_APPROVAL"
BEFORE_IMPORT = "BEFORE_IMPORT"                 # D-09: a decision stamped before the invoice was imported
SELF_DECISION = "SELF_DECISION"                 # D-09: the creator may not reject their own invoice either
# A byte-twin whose extracted fields differ is held for review, never merged (D-09).
BYTES_FIELDS_CONFLICT = "BYTES_FIELDS_CONFLICT"
# Export exclusions.
EXCEPTION_OPEN = "EXCEPTION_OPEN"
NOT_APPROVED = "NOT_APPROVED"
APPROVED_NOT_EXPORTED = "APPROVED_NOT_EXPORTED"     # D-09: approved and not (yet) exported: explains a negative difference
EXPORT_BEFORE_APPROVAL = "EXPORT_BEFORE_APPROVAL"   # D-09: a request named the invoice before its approval: the row is invalid
# Command and metric reasons.
INVALID_WINDOW = "INVALID_WINDOW"
INVALID_STATE = "INVALID_STATE"
INVALID_GROUP = "INVALID_GROUP"


class DomainError(Exception):
    """A business-rule violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str, path: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.details: dict[str, Any] = dict(details or {})
