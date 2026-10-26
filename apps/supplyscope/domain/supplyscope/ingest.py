"""Batch validation (D-01, D-04, D-06). Pure: the same input gives an equal result. Raw rows of rejected records are kept.

Reasons: MALFORMED_RECORD, DUPLICATE_ID (any entity), DUPLICATE_MOVEMENT_ID (an exact replay of a movement id: the first
occurrence is kept), DUPLICATE_MOVEMENT_CONFLICT (the same id with different payloads: EVERY occurrence is rejected),
UNKNOWN_REFERENCE, RECEIPT_BEFORE_ORDER, RECEIPT_EXCEEDS_ORDERED (a receipt that would take received above ordered).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .contract import ACCEPTED_INPUT_CONTRACTS, ENTITIES, EXTRA_ENTITIES
from .errors import (CONTRACT_MISMATCH, DUPLICATE_ID, DUPLICATE_MOVEMENT_CONFLICT, DUPLICATE_MOVEMENT_ID,
                     MALFORMED_RECORD, RECEIPT_BEFORE_ORDER, RECEIPT_EXCEEDS_ORDERED, UNKNOWN_REFERENCE, DomainError)
from .models import (Movement, Population, PoLine, PurchaseOrder, Receipt, ATTR, iso_z, parse_row, row_id)

#: Parents before children.
ORDER = ("products", "locations", "suppliers", "calendar_closures", "policy_scenarios", "cost_versions",
         "purchase_orders", "purchase_order_lines", "receipts", "inventory_movements", "sales", "promotions",
         "backorders", "reservations", "replenishment_params", "lost_sales", "latent_demand", "forecast_runs",
         "forecast_points")
#: entity -> ((field, parent entity, optional), ...)
REFS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "products": (("supplier_id", "suppliers", True),),
    "sales": (("product_id", "products", False), ("location_id", "locations", False)),
    "inventory_movements": (("product_id", "products", False), ("location_id", "locations", False)),
    "purchase_orders": (("supplier_id", "suppliers", False),),
    "purchase_order_lines": (("purchase_order_id", "purchase_orders", False), ("product_id", "products", False)),
    "receipts": (("po_line_id", "purchase_order_lines", False), ("location_id", "locations", False)),
    "promotions": (("product_id", "products", False), ("location_id", "locations", True)),
    "forecast_runs": (("product_id", "products", False), ("location_id", "locations", False)),
    "forecast_points": (("forecast_run_id", "forecast_runs", False),),
    "backorders": (("product_id", "products", False), ("location_id", "locations", False),
                   ("scenario_id", "policy_scenarios", True)),
    "reservations": (("product_id", "products", False), ("location_id", "locations", False)),
    "replenishment_params": (("product_id", "products", False), ("location_id", "locations", False),
                             ("supplier_id", "suppliers", True)),
    "cost_versions": (("product_id", "products", False),),
    "lost_sales": (("product_id", "products", False), ("location_id", "locations", False),
                   ("scenario_id", "policy_scenarios", True)),
    "latent_demand": (("product_id", "products", False), ("location_id", "locations", False)),
}


@dataclass
class RejectedRecord:
    entity: str
    id: str
    reason_code: str
    raw_row: Any
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"entity": self.entity, "id": self.id, "status": "rejected", "reason_code": self.reason_code,
                "raw_row": self.raw_row}


@dataclass
class IngestResult:
    accepted: dict[str, list[Any]] = field(default_factory=dict)
    accepted_rows: dict[str, list[dict]] = field(default_factory=dict)
    rejected: list[RejectedRecord] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    extra_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def population(self) -> Population:
        pop = Population()
        for ent in (*ENTITIES, *EXTRA_ENTITIES):
            setattr(pop, ATTR[ent], list(self.accepted.get(ent, [])))
        return pop

    def rejected_dicts(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.rejected]


def canonical(row: Any) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


def movement_payload(m: Movement) -> str:
    """The identity of a movement independent of how its instant was spelled."""
    return canonical({"movement_id": m.movement_id, "product_id": m.product_id, "location_id": m.location_id,
                      "quantity_delta": m.quantity_delta, "event_at": iso_z(m.event_at), "movement_type": m.movement_type})


def screen_movements(rows: Iterable[Any], products: Iterable[str] | None, locations: Iterable[str] | None,
                     existing: Mapping[str, str] | None = None) -> tuple[list[tuple[dict, Movement]], list[RejectedRecord]]:
    """Validate raw movement rows. ``existing`` maps already-persisted movement ids to their ``movement_payload``
    (a persisted movement is immutable, so an incoming row that repeats its id is the one rejected)."""
    rows = list(rows)
    rejected: list[RejectedRecord] = []
    parsed: list[tuple[dict, Movement]] = []
    for row in rows:
        try:
            parsed.append((row, parse_row("inventory_movements", row)))
        except ValueError as exc:
            rejected.append(RejectedRecord("inventory_movements", row_id("inventory_movements", row), MALFORMED_RECORD,
                                           row, str(exc)))
    payloads: dict[str, set[str]] = {}
    for _, m in parsed:
        payloads.setdefault(m.movement_id, set()).add(movement_payload(m))
    seen: set[str] = set()
    accepted: list[tuple[dict, Movement]] = []
    pset = None if products is None else set(products)
    lset = None if locations is None else set(locations)
    for row, m in parsed:
        have = None if existing is None else existing.get(m.movement_id)
        conflict = len(payloads[m.movement_id]) > 1 or (have is not None and have != movement_payload(m))
        if conflict:
            rejected.append(RejectedRecord("inventory_movements", m.movement_id, DUPLICATE_MOVEMENT_CONFLICT, row,
                                           "the same movement_id carries different payloads"))
        elif m.movement_id in seen or have is not None:
            rejected.append(RejectedRecord("inventory_movements", m.movement_id, DUPLICATE_MOVEMENT_ID, row,
                                           "an exact replay of a movement already loaded"))
        elif (pset is not None and m.product_id not in pset) or (lset is not None and m.location_id not in lset):
            rejected.append(RejectedRecord("inventory_movements", m.movement_id, UNKNOWN_REFERENCE, row,
                                           "unknown product or location"))
        else:
            accepted.append((row, m))
        seen.add(m.movement_id)
    return accepted, rejected


def receipt_reason(receipt: Receipt, line: PoLine, order: PurchaseOrder, received_before: int) -> str | None:
    """RECEIPT_BEFORE_ORDER if received before the order date; RECEIPT_EXCEEDS_ORDERED if it would over-receive the line."""
    if receipt.received_at < order.ordered_at:
        return RECEIPT_BEFORE_ORDER
    if received_before + receipt.received_quantity > line.ordered_quantity:
        return RECEIPT_EXCEEDS_ORDERED
    return None


def check_contract(inputs: Mapping[str, Any]) -> None:
    v = inputs.get("contract_version", 1)
    if v not in ACCEPTED_INPUT_CONTRACTS:
        raise DomainError(CONTRACT_MISMATCH, f"contract_version {v!r} is not supported", path="contract_version")


def validate_batch(inputs: Mapping[str, Any]) -> IngestResult:
    check_contract(inputs)
    res = IngestResult()
    ids: dict[str, set[str]] = {e: set() for e in ORDER}
    objects: dict[str, dict[str, Any]] = {e: {} for e in ORDER}
    for ent in ORDER:
        raw = inputs.get(ent, [])
        if not isinstance(raw, list):
            raise DomainError(MALFORMED_RECORD, f"{ent} must be a list", path=ent)
        accepted: list[tuple[dict, Any]] = []
        if ent == "inventory_movements":
            acc, rej = screen_movements(raw, ids["products"], ids["locations"])
            res.rejected += rej
            accepted = acc
            if True:
                order = {id(r): i for i, r in enumerate(raw)}
                accepted.sort(key=lambda t: order[id(t[0])])
        else:
            seen: set[str] = set()
            received: dict[str, int] = {}
            pending = list(enumerate(raw))
            if ent == "receipts":   # cumulative quantity is judged in time order, output stays in input order
                good = []
                for i, row in pending:
                    try:
                        good.append((parse_row(ent, row).received_at, row.get("receipt_id"), i, row))
                    except ValueError:
                        good.append((None, None, i, row))
                pending = [(i, row) for _, _, i, row in sorted(good, key=lambda t: (t[0] is None, t[0], str(t[1]), t[2]))]
            keep: list[tuple[int, dict, Any]] = []
            for i, row in pending:
                try:
                    obj = parse_row(ent, row)
                except ValueError as exc:
                    res.rejected.append(RejectedRecord(ent, row_id(ent, row), MALFORMED_RECORD, row, str(exc)))
                    continue
                rid = row_id(ent, row)
                if ent == "replenishment_params":
                    key = f"{obj.product_id}:{obj.location_id}"
                elif ent == "latent_demand":   # grain is product x location x day (D-03), not product
                    key = f"{obj.product_id}:{obj.location_id}:{row.get('demand_date')}"
                else:
                    key = rid
                if key in seen:
                    res.rejected.append(RejectedRecord(ent, rid, DUPLICATE_ID, row, "duplicate id; the first kept"))
                    continue
                seen.add(key)
                missing = [f for f, parent, optional in REFS.get(ent, ())
                           if (getattr(obj, f) is not None or not optional) and getattr(obj, f) not in ids[parent]]
                if missing:
                    res.rejected.append(RejectedRecord(ent, rid, UNKNOWN_REFERENCE, row,
                                                       f"unknown reference: {', '.join(missing)}"))
                    continue
                if ent == "receipts":
                    line = objects["purchase_order_lines"][obj.po_line_id]
                    reason = receipt_reason(obj, line, objects["purchase_orders"][line.purchase_order_id],
                                            received.get(line.po_line_id, 0))
                    if reason:
                        res.rejected.append(RejectedRecord(ent, rid, reason, row, reason))
                        continue
                    received[line.po_line_id] = received.get(line.po_line_id, 0) + obj.received_quantity
                keep.append((i, row, obj))
            accepted = [(row, obj) for _, row, obj in sorted(keep, key=lambda t: t[0])]
        for row, obj in accepted:
            rid = row_id(ent, row)
            ids[ent].add(rid)
            objects[ent][rid] = obj
        res.accepted[ent] = [o for _, o in accepted]
        res.accepted_rows[ent] = [r for r, _ in accepted]
    for ent in ORDER:  # a dependent whose parent was rejected later in ORDER cannot happen: parents come first
        bucket = res.counts if ent in ENTITIES else res.extra_counts
        bucket[ent] = {"accepted": len(res.accepted[ent]),
                       "rejected": sum(1 for r in res.rejected if r.entity == ent)}
    res.counts = {e: res.counts[e] for e in ENTITIES}
    res.rejected.sort(key=lambda r: (r.entity, r.id, r.reason_code))
    return res
