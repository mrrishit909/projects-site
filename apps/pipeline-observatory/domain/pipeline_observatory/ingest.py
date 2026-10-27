"""Entity import validation (D-05, D-P8-11): atomic per record, dependants rejected with DEPENDENT_REJECTED, nothing dropped silently.

``validate_import(data)`` takes an inputs.json-shaped dict and returns the accepted rows per entity and the rejected rows (each with its
reason code and the raw row exactly as sent). Rules, in the order they are applied to a row:
duplicate primary key (or repeated run/task/attempt) -> DUPLICATE_ID; foreign key unknown -> UNKNOWN_*; foreign key rejected ->
DEPENDENT_REJECTED. Backfills overlapping an earlier accepted request of the same source (backfill_id order, half-open) ->
BACKFILL_OVERLAP. A checkpoint whose version is not previous + 1 (commit order) -> CHECKPOINT_REGRESSION / CHECKPOINT_GAP and its
batch, and through it the batch's rows, are DEPENDENT_REJECTED (a batch commits atomically with its checkpoint).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import errors as E
from .backfill import find_overlap
from .classify import next_checkpoint_version
from .contract import ENTITIES, FK, ID
from .errors import DomainError
from .timeutil import parse_ts

Row = dict[str, Any]


@dataclass
class ImportResult:
    accepted: dict[str, list[Row]]
    rejected: list[Row]                      # {entity, id, status: "rejected", reason_code, raw_row}, sorted by (entity order, row order)

    def counts(self) -> dict[str, dict[str, int]]:
        return {e: {"accepted": len(self.accepted[e]), "rejected": sum(1 for r in self.rejected if r["entity"] == e)} for e in ENTITIES}


def _row_id(entity: str, row: Any) -> str | None:
    if isinstance(row, dict) and isinstance(row.get(ID[entity]), str) and row[ID[entity]]:
        return row[ID[entity]]
    return None


def validate_import(data: dict[str, Any]) -> ImportResult:
    acc: dict[str, list[Row]] = {e: [] for e in ENTITIES}
    rejected_ids: dict[str, set[str]] = {e: set() for e in ENTITIES}
    rejected: list[tuple[int, int, Row]] = []
    seen_pk: dict[str, set[str]] = {e: set() for e in ENTITIES}
    seen_attempt: set[tuple[Any, Any, int]] = set()
    accepted_ids = lambda e: {r[ID[e]] for r in acc[e]}  # noqa: E731

    def reject(entity: str, row: Any, code: str) -> None:
        rid = _row_id(entity, row)
        rejected.append((ENTITIES.index(entity), data[entity].index(row), {"entity": entity, "id": rid, "status": "rejected",
                                                                           "reason_code": code, "raw_row": row}))
        if rid is not None:
            rejected_ids[entity].add(rid)

    def accept(entity: str, row: Row) -> None:
        acc[entity].append(row)
        seen_pk[entity].add(row[ID[entity]])
        if entity == "task_runs":
            seen_attempt.add((row["run_id"], row["task_name"], int(row["attempt"])))

    def refusal(entity: str, row: Any) -> str | None:
        rid = _row_id(entity, row)
        if rid is None:
            return E.MISSING_FIELD
        if rid in seen_pk[entity]:
            return E.DUPLICATE_ID
        if entity == "task_runs" and (row.get("run_id"), row.get("task_name"), int(row.get("attempt", 0))) in seen_attempt:
            return E.DUPLICATE_ID               # a repeated attempt of one task in one run
        if entity in FK:
            fk, parent, unknown = FK[entity]
            pid = row.get(fk)
            if pid in accepted_ids(parent):
                pass
            elif pid in rejected_ids[parent]:
                return E.DEPENDENT_REJECTED
            else:
                return unknown
        if entity == "pipeline_runs" and row.get("backfill_id") is not None:
            if row["backfill_id"] in rejected_ids["backfill_requests"]:
                return E.DEPENDENT_REJECTED
            if row["backfill_id"] not in accepted_ids("backfill_requests"):
                return E.UNKNOWN_BACKFILL
        return None

    def plain(entity: str) -> None:
        for row in data[entity]:
            code = refusal(entity, row)
            reject(entity, row, code) if code else accept(entity, row)

    plain("source_contracts")
    for row in data["backfill_requests"]:                       # in backfill_id order of the input list
        code = refusal("backfill_requests", row)
        if code is None and find_overlap(acc["backfill_requests"], row) is not None:
            code = E.BACKFILL_OVERLAP
        reject("backfill_requests", row, code) if code else accept("backfill_requests", row)

    batch_rows: list[Row] = []
    for row in data["ingestion_batches"]:
        code = refusal("ingestion_batches", row)
        reject("ingestion_batches", row, code) if code else batch_rows.append(row)
    live_batches = {b["batch_id"] for b in batch_rows}
    # the atomic commit: every checkpoint of a live batch must be previous + 1 of its source, in commit order
    cp_code: dict[str, str] = {}
    bad_batches: set[str] = set()
    previous: dict[str, int] = {}
    for c in sorted((c for c in data["checkpoints"] if c.get("batch_id") in live_batches), key=lambda c: (c["committed_at"], c["checkpoint_id"])):
        try:
            previous[c["source_id"]] = next_checkpoint_version(previous.get(c["source_id"], 0), c["version_number"])
        except DomainError as err:
            cp_code[c["checkpoint_id"]] = err.code
            bad_batches.add(c["batch_id"])
    for b in batch_rows:
        reject("ingestion_batches", b, E.DEPENDENT_REJECTED) if b["batch_id"] in bad_batches else accept("ingestion_batches", b)
    for c in data["checkpoints"]:
        code = cp_code.get(c["checkpoint_id"]) or refusal("checkpoints", c)
        reject("checkpoints", c, code) if code else accept("checkpoints", c)
    for entity in ("raw_records", "quarantine_records", "model_definitions", "pipeline_runs", "task_runs", "quality_results", "publications",
                   "incidents"):
        plain(entity)
    rejected.sort(key=lambda t: (t[0], t[1]))
    return ImportResult(acc, [r for _, _, r in rejected])


def check_instants(data: dict[str, Any]) -> None:
    """Raise DomainError(MALFORMED_RECORD) on an instant that is not UTC-parsable (callers that load untrusted files)."""
    for entity, fields in (("ingestion_batches", ("started_at",)), ("checkpoints", ("committed_at",)), ("pipeline_runs", ("started_at",)),
                           ("publications", ("published_at", "watermark")), ("incidents", ("opened_at",))):
        for row in data.get(entity, []):
            for f in fields:
                try:
                    parse_ts(row[f])
                except (KeyError, ValueError):
                    raise DomainError(E.MALFORMED_RECORD, f"{entity}.{f} is not an ISO-8601 instant with a zone", f"{entity}.{f}") from None
