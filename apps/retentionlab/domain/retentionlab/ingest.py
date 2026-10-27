"""Import validation (D-P10-15): per row DUPLICATE_ID, then foreign keys in the documented order (a parent that was itself rejected
gives DEPENDENT_REJECTED, an absent one UNKNOWN_*), then the domain rule. Entities are processed parents first; the rejected list is in
processing order and keeps every row; nothing is silently dropped."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import InvalidOperation
from fractions import Fraction
from typing import Any

from . import errors as E
from .contract import ENTITIES, EVENTS, FK, ID
from .timeutil import days, parse_ts


@dataclass
class Ingest:
    accepted: dict[str, list[dict[str, Any]]]
    rejected: list[dict[str, Any]]

    def counts(self) -> dict[str, dict[str, int]]:
        return {e: {"accepted": len(self.accepted[e]), "rejected": sum(1 for r in self.rejected if r["entity"] == e)} for e in ENTITIES}


def _domain_rule(entity: str, row: dict[str, Any], cutoffs: dict[str, dict[str, Any]], as_of: Any, grace: int) -> str | None:
    if entity == "accounts" and row.get("synthetic") is not True:
        return E.SYNTHETIC_REQUIRED
    if entity in EVENTS and parse_ts(row["available_at"]) < parse_ts(row["event_at"]):
        return E.AVAILABILITY_BEFORE_EVENT
    if entity == "predictions" and not (0 <= Fraction(row["probability"]) <= 1):
        return E.PROBABILITY_OUT_OF_RANGE
    if entity == "labels":
        c = cutoffs[row["cutoff_id"]]
        if parse_ts(c["horizon_end"]) + days(grace) > as_of and row["churned"] is not None:
            return E.CENSORED_LABEL
    if entity == "outreach_events" and row.get("status") != "draft":
        return E.OUTREACH_NOT_DRAFT
    return None


def validate(data: dict[str, Any]) -> Ingest:
    as_of = parse_ts(data["as_of"])
    grace = data["label_version"]["grace_days"]
    accepted: dict[str, list[dict[str, Any]]] = {e: [] for e in ENTITIES}
    ok_ids: dict[str, set[Any]] = {e: set() for e in ENTITIES}
    rej_ids: dict[str, set[Any]] = {e: set() for e in ENTITIES}
    rejected: list[dict[str, Any]] = []
    cutoffs: dict[str, dict[str, Any]] = {}
    for entity in ENTITIES:
        for row in data.get(entity, []):
            try:
                rid = row[ID[entity]]
            except (KeyError, TypeError):
                rejected.append({"entity": entity, "id": None, "reason_code": E.MALFORMED_RECORD})
                continue
            code: str | None = E.DUPLICATE_ID if rid in ok_ids[entity] else None
            if code is None:
                for fk, parent, unknown in FK.get(entity, []):
                    pid = row.get(fk)
                    if pid in ok_ids[parent]:
                        continue
                    code = E.DEPENDENT_REJECTED if pid in rej_ids[parent] else unknown
                    break
            if code is None:
                try:
                    code = _domain_rule(entity, row, cutoffs, as_of, grace)
                except (KeyError, ValueError, TypeError, ArithmeticError, InvalidOperation):
                    code = E.MALFORMED_RECORD
            if code:
                rejected.append({"entity": entity, "id": rid, "reason_code": code})
                if code != E.DUPLICATE_ID:
                    rej_ids[entity].add(rid)
            else:
                accepted[entity].append(row)
                ok_ids[entity].add(rid)
                if entity == "prediction_cutoffs":
                    cutoffs[rid] = row
    return Ingest(accepted, rejected)
