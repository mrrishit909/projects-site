"""The three hash kinds of D-P8-10: payload_hash, content_hash, definition_hash. sha256, canonical JSON, no float."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def canonical_json(obj: Any) -> str:
    """Sorted keys, ``,`` and ``:`` separators, ASCII only, NaN refused."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def payload_hash(payload: Any) -> str:
    """sha256 of the canonical JSON of a payload."""
    return sha256_hex(canonical_json(payload))


def content_hash(payload_hashes: Iterable[str]) -> str:
    """sha256 of the sorted payload hashes of the included accepted records, joined with a newline."""
    return sha256_hex("\n".join(sorted(payload_hashes)))


def definition_hash(definition: str) -> str:
    """sha256 of the model definition text."""
    return sha256_hex(definition)
