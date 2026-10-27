"""Secret redaction for structured logs and evidence (D-03, P08-TEST-11). A redaction check runs on every log line and fails closed."""
from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
WITHHELD = "[LOG LINE WITHHELD: a secret pattern survived redaction]"

#: Field names whose value is never logged, whatever it looks like.
SECRET_KEYS = re.compile(r"(?<![a-z])(pass(word|wd)?|secrets?|tokens?|api[_-]?keys?|apikey|authorization|auth|credentials?|private[_-]?key|access[_-]?key|cookie|session[_-]?id|dsn|connection[_-]?string)(?![a-z])",
                         re.IGNORECASE)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    ("basic", re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{12,}")),
    ("url_credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")),
    ("key_value", re.compile(r"(?i)\b(pass(?:word|wd)?|secret|token|api[_-]?key|apikey|authorization|access[_-]?key|private[_-]?key|client[_-]?secret)([\"']?\s*[=:]\s*)(?![\"']?\[REDACTED\])(\"[^\"]*\"|'[^']*'|[^\s,;&\"'}]+)")),
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


def redact_text(text: str) -> str:
    """Replace every secret-looking span of a log line with ``[REDACTED]`` (the key name and the surrounding text stay)."""
    out = text
    for name in ("bearer", "basic"):                         # the scheme and its credential go together, before ``Authorization: ...``
        out = dict(_PATTERNS)[name].sub(REDACTED, out)
    out = dict(_PATTERNS)["url_credentials"].sub(lambda m: f"{m.group(1)}{m.group(2)}:{REDACTED}@", out)
    out = dict(_PATTERNS)["key_value"].sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    for name, pat in _PATTERNS:
        if name not in ("bearer", "basic", "url_credentials", "key_value"):
            out = pat.sub(REDACTED, out)
    return out


def contains_secret(text: str) -> bool:
    """True if ``text`` still carries a secret pattern. A span already replaced by ``[REDACTED]`` is stable under ``redact_text``, so
    "redacting changes nothing" means "no secret is left"."""
    return redact_text(text) != text


def redact_value(value: Any, key: str = "") -> Any:
    """Redact a JSON-like value: secret-named keys are replaced whole, strings are scrubbed, containers are walked."""
    if key and SECRET_KEYS.search(key) and value is not None:
        return REDACTED
    if isinstance(value, dict):
        return {k: redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v, key) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def safe_line(line: str) -> str:
    """The structured-log check: redact, then verify nothing survived; a line that still fails is withheld whole (fail closed)."""
    clean = redact_text(line)
    return WITHHELD if contains_secret(clean) else clean
