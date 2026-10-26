"""Domain errors and reason codes (docs/contracts.md D-01..D-05)."""
from __future__ import annotations

from typing import Any

# Ingest reasons (P04-TEST-01..04 and structure).
AGENT_NOT_QUALIFIED = "AGENT_NOT_QUALIFIED"
CONCURRENCY_EXCEEDED = "CONCURRENCY_EXCEEDED"
BOT_AS_HUMAN_REPLY = "BOT_AS_HUMAN_REPLY"
TRANSFER_RESETS_ARRIVAL = "TRANSFER_RESETS_ARRIVAL"
UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
MALFORMED_RECORD = "MALFORMED_RECORD"
DUPLICATE_ID = "DUPLICATE_ID"
TICKET_REJECTED = "TICKET_REJECTED"          # D-05: a dependent of a rejected ticket
# Command and metric reasons.
CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
INVALID_WINDOW = "INVALID_WINDOW"
INVALID_CONFIG = "INVALID_CONFIG"
INVALID_STATE = "INVALID_STATE"

#: Reasons that reject a whole ticket (with its events and surveys), in priority order when several apply.
TICKET_REASONS = (TRANSFER_RESETS_ARRIVAL, AGENT_NOT_QUALIFIED, CONCURRENCY_EXCEEDED)


class DomainError(Exception):
    """A business-rule violation with a stable machine-readable code."""

    def __init__(self, code: str, message: str, path: str | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.details: dict[str, Any] = dict(details or {})
