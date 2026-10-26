"""Batch validation (D-06 C01). Pure: same input gives an equal result."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .contract import ACCEPTED_INPUT_CONTRACTS, CONTRACT_VERSION, CURRENCY_RE, KNOWN_CURRENCIES
from .errors import (CONTRACT_MISMATCH, CURRENCY_NOT_ISO4217, MALFORMED_RECORD,
                     ORPHAN_REFERENCE, DomainError)
from .models import (CostVersion, Customer, Discount, ExchangeRate, Order, OrderLine,
                     Product, RejectedRecord, Return, Shipment, ShipmentLine)
from .money import parse_money

ENTITIES = ("customers", "products", "orders", "order_lines", "discounts", "shipments",
            "shipment_lines", "returns", "cost_versions", "exchange_rates")


def currency_ok(code: object) -> bool:
    """Currency must match the 3-letter pattern and the configured list."""
    return isinstance(code, str) and re.match(CURRENCY_RE, code) is not None \
        and code in KNOWN_CURRENCIES


def _ts(v: object) -> datetime:
    if not isinstance(v, str):
        raise ValueError("timestamp must be a string")
    d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return d.astimezone(timezone.utc)


def _date(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("date must be a string")
    return datetime.strptime(v, "%Y-%m-%d").date().isoformat()


def _int(v: object, minimum: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ValueError(f"integer >= {minimum} required")
    return v


def _s(v: object) -> str:
    if not isinstance(v, str) or not v:
        raise ValueError("non-empty string required")
    return v


def _parsers() -> dict[str, Callable[[dict], Any]]:
    return {
        "customers": lambda r: Customer(_s(r["customer_id"]), r["customer_name"], r["region_id"],
                                        r["segment"], _date(r["effective_from"])),
        "products": lambda r: Product(_s(r["product_id"]), r["sku"], r["category_id"],
                                      r["unit_of_measure"], bool(r["active"])),
        "orders": lambda r: Order(_s(r["order_id"]), _s(r["customer_id"]), _date(r["order_date"]),
                                  r["currency"], _s(r["status"])),
        "order_lines": lambda r: OrderLine(_s(r["line_id"]), _s(r["order_id"]), _s(r["product_id"]),
                                           _int(r["quantity"], 1), parse_money(r["unit_price"])),
        "discounts": lambda r: Discount(_s(r["discount_id"]), _s(r["line_id"]),
                                        parse_money(r["discount_amount"]), r["reason_code"],
                                        r["approved_by"]),
        "shipments": lambda r: Shipment(_s(r["shipment_id"]), _s(r["order_id"]), _ts(r["shipped_at"]),
                                        parse_money(r["shipping_cost"]), r["currency"]),
        "shipment_lines": lambda r: ShipmentLine(_s(r["shipment_line_id"]), _s(r["shipment_id"]),
                                                 _s(r["line_id"]), _int(r["shipped_quantity"], 0),
                                                 r.get("cost_version_id")),
        "returns": lambda r: Return(_s(r["return_id"]), _s(r["shipment_line_id"]),
                                    _int(r["returned_quantity"], 1), parse_money(r["credit_amount"]),
                                    _date(r["credit_date"])),
        "cost_versions": lambda r: CostVersion(_s(r["cost_version_id"]), _s(r["product_id"]),
                                               parse_money(r["unit_cost"]), _date(r["valid_from"]),
                                               None if r.get("valid_to") is None else _date(r["valid_to"])),
        "exchange_rates": lambda r: ExchangeRate(_s(r["rate_id"]), r["currency"],
                                                 r["reporting_currency"], _date(r["rate_date"]),
                                                 parse_money(r["rate"])),
    }


_ID_FIELD = {"customers": "customer_id", "products": "product_id", "orders": "order_id",
             "order_lines": "line_id", "discounts": "discount_id", "shipments": "shipment_id",
             "shipment_lines": "shipment_line_id", "returns": "return_id",
             "cost_versions": "cost_version_id", "exchange_rates": "rate_id"}


@dataclass
class IngestResult:
    accepted: dict[str, list[Any]] = field(default_factory=dict)
    rejected: list[RejectedRecord] = field(default_factory=list)
    quarantined: list[RejectedRecord] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)


def validate_batch(raw: dict) -> IngestResult:
    """Validate and parse a raw batch.

    A bad order currency rejects the order and every dependent (lines, discounts,
    shipments, shipment lines, returns) with CURRENCY_NOT_ISO4217; a bad shipment
    currency rejects the shipment and its lines and returns. Raw rows are kept.
    """
    if raw.get("contract", CONTRACT_VERSION) not in ACCEPTED_INPUT_CONTRACTS:
        raise DomainError(CONTRACT_MISMATCH, f"expected contract {CONTRACT_VERSION}",
                          details={"got": raw.get("contract")})
    parsers = _parsers()
    parsed: dict[str, list[tuple[dict, Any]]] = {}
    rejected: dict[tuple[str, str], RejectedRecord] = {}

    def reject(entity: str, row: dict, code: str) -> None:
        rid = str(row.get(_ID_FIELD[entity], ""))
        rejected.setdefault((entity, rid), RejectedRecord(entity, rid, code, copy.deepcopy(row)))

    for ent in ENTITIES:
        parsed[ent] = []
        for row in raw.get(ent) or []:
            try:
                parsed[ent].append((row, parsers[ent](row)))
            except (KeyError, ValueError, TypeError, AttributeError):
                reject(ent, row, MALFORMED_RECORD)

    bad_orders: set[str] = set()
    for row, o in parsed["orders"]:
        if not currency_ok(o.currency):
            bad_orders.add(o.order_id)
            reject("orders", row, CURRENCY_NOT_ISO4217)
    order_ids = {o.order_id for _, o in parsed["orders"]}

    bad_shipments: set[str] = set()
    for row, s in parsed["shipments"]:
        if s.order_id in bad_orders or not currency_ok(s.currency):
            bad_shipments.add(s.shipment_id)
            reject("shipments", row, CURRENCY_NOT_ISO4217)
        elif s.order_id not in order_ids:
            reject("shipments", row, ORPHAN_REFERENCE)
    ship_ids = {s.shipment_id for _, s in parsed["shipments"]}

    bad_lines: set[str] = set()
    for row, ln in parsed["order_lines"]:
        if ln.order_id in bad_orders:
            bad_lines.add(ln.line_id)
            reject("order_lines", row, CURRENCY_NOT_ISO4217)
        elif ln.order_id not in order_ids:
            reject("order_lines", row, ORPHAN_REFERENCE)
    line_ids = {ln.line_id for _, ln in parsed["order_lines"]}

    for row, d in parsed["discounts"]:
        if d.line_id in bad_lines:
            reject("discounts", row, CURRENCY_NOT_ISO4217)
        elif d.line_id not in line_ids:
            reject("discounts", row, ORPHAN_REFERENCE)

    bad_sls: set[str] = set()
    for row, sl in parsed["shipment_lines"]:
        if sl.shipment_id in bad_shipments or sl.line_id in bad_lines:
            bad_sls.add(sl.shipment_line_id)
            reject("shipment_lines", row, CURRENCY_NOT_ISO4217)
        elif sl.shipment_id not in ship_ids or sl.line_id not in line_ids:
            reject("shipment_lines", row, ORPHAN_REFERENCE)
    sl_ids = {sl.shipment_line_id for _, sl in parsed["shipment_lines"]}

    for row, r in parsed["returns"]:
        if r.shipment_line_id in bad_sls:
            reject("returns", row, CURRENCY_NOT_ISO4217)
        elif r.shipment_line_id not in sl_ids:
            reject("returns", row, ORPHAN_REFERENCE)

    result = IngestResult()
    for ent in ENTITIES:
        idf = _ID_FIELD[ent]
        keep = [m for row, m in parsed[ent] if (ent, str(row[idf])) not in rejected]
        keep.sort(key=lambda m: tuple(str(getattr(m, f)) for f in _sort_fields(ent)))
        result.accepted[ent] = keep
        nrej = sum(1 for (e, _) in rejected if e == ent)
        result.counts[ent] = {"accepted": len(keep), "rejected": nrej, "quarantined": 0}
    result.rejected = [rejected[k] for k in sorted(rejected)]
    return result


def _sort_fields(ent: str) -> tuple[str, ...]:
    return ("customer_id", "effective_from") if ent == "customers" else (_ID_FIELD[ent],)
