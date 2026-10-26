"""Duplicate detection and merge (D-01, D-05 / D-P5-3).

Two invoices are the same obligation when they share the SOURCE BYTES (sha256) or the identity (vendor, normalised
number, invoice date, computed total). The earliest import (imported_at, invoice_id) is canonical; every later one is
MERGED into it: status ``merged``, lineage and source hash kept, no received quantity consumed. Bytes are checked first
(exact evidence); the identity second. Groups are unordered and counted once (P05-MET-09).
"""
from __future__ import annotations

from typing import Any, Sequence

from .amounts import identity_key
from .errors import DUPLICATE_IDENTITY, DUPLICATE_SOURCE_BYTES
from .models import Invoice


def group_key_for(reason: str, inv: Invoice) -> str:
    return identity_key(inv) if reason == DUPLICATE_IDENTITY else f"sha256:{inv.source_sha256}"


def detect_duplicates(invoices: Sequence[Invoice]) -> tuple[dict[str, str], list[dict[str, Any]], int]:
    """Returns ``(merged_into, merged_records, groups_detected)`` over all given invoices."""
    by_key: dict[str, str] = {}
    by_sha: dict[str, str] = {}
    merged_into: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for inv in sorted(invoices, key=lambda i: (i.imported_at, i.invoice_id)):
        key = identity_key(inv)
        canon = by_sha.get(inv.source_sha256)
        reason = DUPLICATE_SOURCE_BYTES
        if canon is None:
            canon, reason = by_key.get(key), DUPLICATE_IDENTITY
        if canon is None:
            canon = inv.invoice_id
        else:
            merged_into[inv.invoice_id] = canon
            records.append({"entity": "invoices", "id": inv.invoice_id, "status": "merged", "reason_code": reason,
                            "merged_into": canon, "group_key": group_key_for(reason, inv),
                            "source_sha256": inv.source_sha256})
        by_key.setdefault(key, canon)
        by_sha.setdefault(inv.source_sha256, canon)
    records.sort(key=lambda r: r["id"])
    return merged_into, records, len(set(merged_into.values()))
