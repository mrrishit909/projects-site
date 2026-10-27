"""Domain errors: a stable ``code`` (the rule id reported to clients), a safe message, an optional path and details."""
from __future__ import annotations

from typing import Any


class DomainError(Exception):
    def __init__(self, code: str, message: str, path: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.details = details or {}
