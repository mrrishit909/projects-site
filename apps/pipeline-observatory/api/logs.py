"""Structured logs that never carry a secret (P08-TEST-11): every line passes the redaction check before it is emitted, and a line that still
fails the check is withheld whole (fail closed)."""
from __future__ import annotations

import json
import logging
from typing import Any

from pipeline_observatory.redaction import WITHHELD, contains_secret, redact_value, safe_line

log = logging.getLogger("pipeline_observatory.api")


def render(event: str, **fields: Any) -> str:
    """One JSON line: ``fields`` are redacted by key name and by value pattern, then the whole line is checked."""
    body = {"event": event, **redact_value(fields)}
    return safe_line(json.dumps(body, sort_keys=True, default=str, ensure_ascii=True))


def emit(event: str, level: int = logging.INFO, **fields: Any) -> str:
    line = render(event, **fields)
    log.log(level, "%s", line)
    return line


class RedactingFilter(logging.Filter):
    """Attach to a handler or logger to redact every record of any library (messages and arguments)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg, record.args = (WITHHELD if contains_secret(safe_line(message)) else safe_line(message)), ()
        return True
