"""Frozen domain records. Field names follow tests/fixtures/golden/inputs.json."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Customer:
    customer_id: str
    customer_name: str
    region_id: str
    segment: str
    effective_from: str  # YYYY-MM-DD (type-2 version, D-06)


@dataclass(frozen=True)
class Product:
    product_id: str
    sku: str
    category_id: str
    unit_of_measure: str
    active: bool


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    order_date: str
    currency: str
    status: str


@dataclass(frozen=True)
class OrderLine:
    line_id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class Discount:
    discount_id: str
    line_id: str
    discount_amount: Decimal
    reason_code: str
    approved_by: str


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    order_id: str
    shipped_at: datetime  # tz-aware UTC
    shipping_cost: Decimal
    currency: str


@dataclass(frozen=True)
class ShipmentLine:
    shipment_line_id: str
    shipment_id: str
    line_id: str
    shipped_quantity: int
    cost_version_id: str | None = None


@dataclass(frozen=True)
class Return:
    return_id: str
    shipment_line_id: str
    returned_quantity: int
    credit_amount: Decimal
    credit_date: str


@dataclass(frozen=True)
class CostVersion:
    cost_version_id: str
    product_id: str
    unit_cost: Decimal
    valid_from: str
    valid_to: str | None  # None = open (D-03)


@dataclass(frozen=True)
class ExchangeRate:
    rate_id: str
    currency: str
    reporting_currency: str
    rate_date: str
    rate: Decimal


@dataclass(frozen=True)
class Quota:
    quota_id: str
    rep_id: str
    period: str
    amount: Decimal


@dataclass(frozen=True)
class RejectedRecord:
    entity: str
    id: str
    reason_code: str
    raw_row: dict[str, Any]


@dataclass(frozen=True)
class ShipmentLineFact:
    """One shipment line, all money in reporting currency (D-01, D-02)."""
    shipment_line_id: str
    shipment_id: str
    order_id: str
    line_id: str
    customer_id: str
    product_id: str
    region_id: str
    shipped_at: datetime
    currency: str
    fx_rate: Decimal
    shipped_quantity: int
    unit_price: Decimal
    gross_sales: Decimal
    allocated_discount: Decimal
    cost_version_id: str
    unit_cost: Decimal
    cogs: Decimal
    freight: Decimal
    returned_quantity: int
    merchandise_credit: Decimal
    recoverable_return_cost: Decimal


@dataclass(frozen=True)
class ReturnEvent:
    """One accepted return credit, recognised on ``credit_date`` (D-01a), reporting currency."""
    return_id: str
    shipment_line_id: str
    credit_date: str  # YYYY-MM-DD, UTC
    returned_quantity: int
    merchandise_credit: Decimal
    recoverable_return_cost: Decimal
