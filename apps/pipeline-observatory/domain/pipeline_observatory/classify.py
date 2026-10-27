"""Record classification and checkpoint ordering (D-01, D-P8-01, D-P8-11).

``classify_rows`` decides every raw row of one committed batch, in raw_record_id order:
  * a batch whose declared schema_version differs from the source contract is quarantined WHOLE with SCHEMA_CHANGED (P08-TEST-04);
  * ``op = delete`` on an accepted key propagates as ``deleted`` (an exclusion with its reason, never ignored, P08-TEST-08); a delete of
    a key never accepted is quarantined DELETE_TARGET_UNKNOWN; a repeated delete is a duplicate;
  * otherwise a ``source_key`` already accepted in the same source (earlier batch or earlier in this batch) is a duplicate, whatever its
    payload hash. THE KEY CHECK RUNS BEFORE THE CONTRACT CHECK;
  * otherwise the contract decides, in this order: MISSING_FIELD, INVALID_FIELD (a payload that is not an object, a quantity that is not an
    integer of magnitude at most 2**53, money that is not a 2-place decimal string, an event_ts that is not a real instant), NEGATIVE_QUANTITY,
    EVENT_IN_FUTURE (an event dated after its batch's arrival, the batch ``started_at``, or after the cutoff; D-09) quarantine; else the row
    is accepted.
Nothing is dropped: every row has exactly one disposition.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from . import errors as E
from .contract import REQUIRED_FIELDS
from .errors import DomainError
from .patterns import is_money, is_quantity
from .timeutil import parse_ts

ACCEPTED, DUPLICATE, QUARANTINED, DELETED = "accepted", "duplicate", "quarantined", "deleted"


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


def money_amount(payload: Any, field: str = "amount") -> Decimal:
    """The business amount of a payload as an exact Decimal; a row without a usable amount (a payload that is not an object, a missing or
    malformed field) contributes 0.00: it has no business value (D-09, R8-08)."""
    v = payload.get(field) if isinstance(payload, dict) else None
    if is_money(v):
        try:
            return Decimal(v)
        except InvalidOperation:
            return Decimal("0")
    return Decimal("0")


def event_limit(arrival: Any = None, cutoff: Any = None) -> Any:
    """The latest event instant a row may carry: the earlier of its batch's arrival (``started_at``) and the cutoff; None when neither is given."""
    limits = [parse_ts(x) for x in (arrival, cutoff) if x is not None]
    return min(limits) if limits else None


def contract_reason(payload: Any, arrival: Any = None, cutoff: Any = None, limit: Any = None) -> str | None:
    """The quarantine reason of an upsert payload, or None when it satisfies the contract (D-P8-12 payload fields). ``arrival`` (the batch's
    ``started_at``) and ``cutoff`` bound the event instant: a later event is EVENT_IN_FUTURE (D-09, R8-01). ``limit`` is ``event_limit`` already
    computed (a batch classifies many rows against one limit)."""
    if not isinstance(payload, dict):
        return E.INVALID_FIELD
    if any(payload.get(k) is None for k in REQUIRED_FIELDS):
        return E.MISSING_FIELD
    if not is_quantity(payload["quantity"]) or not all(is_money(payload[k]) for k in ("unit_price", "amount")):
        return E.INVALID_FIELD
    try:
        event = parse_ts(payload["event_ts"])
    except ValueError:
        return E.INVALID_FIELD
    if payload["quantity"] < 0:
        return E.NEGATIVE_QUANTITY
    limit = limit if limit is not None else event_limit(arrival, cutoff)
    if limit is not None and event > limit:
        return E.EVENT_IN_FUTURE
    return None


def classify_rows(rows: Iterable[dict[str, Any]], accepted_keys: set[str], deleted_keys: set[str] | None = None,
                  schema_ok: bool = True, arrival: Any = None, cutoff: Any = None) -> list[Disposition]:
    """Classify the rows of ONE batch against ``accepted_keys`` (every key accepted so far in the source; the set is extended in place,
    as is ``deleted_keys``). Rows are taken in raw_record_id order. ``arrival`` is the batch's ``started_at``, ``cutoff`` the instant the
    classification is made for: an upsert dated after either is quarantined EVENT_IN_FUTURE."""
    deleted = deleted_keys if deleted_keys is not None else set()
    limit = event_limit(arrival, cutoff)
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
        reason = contract_reason(payload, limit=limit)
        if reason or key is None:
            out.append(Disposition(rid, QUARANTINED, reason or E.MISSING_FIELD))
        else:
            accepted_keys.add(key)
            out.append(Disposition(rid, ACCEPTED))
    return out
