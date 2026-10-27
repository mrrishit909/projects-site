"""Record classification and checkpoint ordering (D-01, D-P8-01, D-P8-11).

``classify_rows`` decides every raw row of one committed batch, in raw_record_id order:
  * a batch whose declared schema_version differs from the source contract is quarantined WHOLE with SCHEMA_CHANGED (P08-TEST-04);
  * ``op = delete`` on an accepted key propagates as ``deleted`` (an exclusion with its reason, never ignored, P08-TEST-08); a delete of
    a key never accepted is quarantined DELETE_TARGET_UNKNOWN; a repeated delete is a duplicate;
  * otherwise a ``source_key`` already accepted in the same source (earlier batch or earlier in this batch) is a duplicate, whatever its
    payload hash. THE KEY CHECK RUNS BEFORE THE CONTRACT CHECK;
  * otherwise the contract decides: MISSING_FIELD, INVALID_FIELD, NEGATIVE_QUANTITY quarantine; else the row is accepted.
Nothing is dropped: every row has exactly one disposition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from . import errors as E
from .contract import REQUIRED_FIELDS
from .errors import DomainError
from .timeutil import parse_ts

ACCEPTED, DUPLICATE, QUARANTINED, DELETED = "accepted", "duplicate", "quarantined", "deleted"
_MONEY = re.compile(r"^-?\d+(\.\d{1,2})?$")


@dataclass(frozen=True)
class Disposition:
    raw_record_id: str
    kind: str
    reason: str | None = None


def next_checkpoint_version(previous: int, version: int) -> int:
    """The version a commit may carry is previous + 1 (D-01). Less or equal: CHECKPOINT_REGRESSION; more: CHECKPOINT_GAP."""
    if isinstance(version, bool) or not isinstance(version, int):
        raise DomainError(E.INVALID_FIELD, "checkpoint version must be an integer", "input.checkpoint_version")
    if version <= previous:
        raise DomainError(E.CHECKPOINT_REGRESSION, f"checkpoint version {version} is not after the committed version {previous}",
                          "input.checkpoint_version", {"committed_version": previous, "requested_version": version})
    if version != previous + 1:
        raise DomainError(E.CHECKPOINT_GAP, f"checkpoint version {version} skips {previous + 1}", "input.checkpoint_version",
                          {"committed_version": previous, "requested_version": version})
    return version


def money_amount(payload: dict[str, Any], field: str = "amount") -> Decimal:
    """The business amount of a payload as an exact Decimal; a row without a usable amount contributes 0.00 (it has no business value)."""
    v = payload.get(field)
    if isinstance(v, str) and _MONEY.match(v):
        try:
            return Decimal(v)
        except InvalidOperation:
            return Decimal("0")
    return Decimal("0")


def contract_reason(payload: Any) -> str | None:
    """The quarantine reason of an upsert payload, or None when it satisfies the contract (D-P8-12 payload fields)."""
    if not isinstance(payload, dict):
        return E.MISSING_FIELD
    if any(payload.get(k) is None for k in REQUIRED_FIELDS):
        return E.MISSING_FIELD
    q = payload["quantity"]
    if isinstance(q, bool) or not isinstance(q, int):
        return E.INVALID_FIELD
    if q < 0:
        return E.NEGATIVE_QUANTITY
    for k in ("unit_price", "amount"):
        if not isinstance(payload[k], str) or not _MONEY.match(payload[k]):
            return E.INVALID_FIELD
    try:
        parse_ts(payload["event_ts"])
    except ValueError:
        return E.INVALID_FIELD
    return None


def classify_rows(rows: Iterable[dict[str, Any]], accepted_keys: set[str], deleted_keys: set[str] | None = None,
                  schema_ok: bool = True) -> list[Disposition]:
    """Classify the rows of ONE batch against ``accepted_keys`` (every key accepted so far in the source; the set is extended in place,
    as is ``deleted_keys``). Rows are taken in raw_record_id order."""
    deleted = deleted_keys if deleted_keys is not None else set()
    out: list[Disposition] = []
    for r in sorted(rows, key=lambda r: r["raw_record_id"]):
        rid, key, payload = r["raw_record_id"], r.get("source_key"), r.get("payload_json")
        if not schema_ok:
            out.append(Disposition(rid, QUARANTINED, E.SCHEMA_CHANGED))
            continue
        op = payload.get("op", "upsert") if isinstance(payload, dict) else "upsert"
        if op == "delete":
            if key is not None and key in accepted_keys and key not in deleted:
                deleted.add(key)
                out.append(Disposition(rid, DELETED))
            elif key is not None and key in deleted:
                out.append(Disposition(rid, DUPLICATE))
            else:
                out.append(Disposition(rid, QUARANTINED, E.DELETE_TARGET_UNKNOWN))
            continue
        if op != "upsert":
            out.append(Disposition(rid, QUARANTINED, E.UNKNOWN_OP))
            continue
        if key is not None and key in accepted_keys:
            out.append(Disposition(rid, DUPLICATE))
            continue
        reason = contract_reason(payload)
        if reason or key is None:
            out.append(Disposition(rid, QUARANTINED, reason or E.MISSING_FIELD))
        else:
            accepted_keys.add(key)
            out.append(Disposition(rid, ACCEPTED))
    return out
