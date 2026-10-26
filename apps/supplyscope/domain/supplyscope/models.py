"""Typed records, row parsers and the population (contract v1). A parser raises ``ValueError`` for a malformed row;
ingest turns that into MALFORMED_RECORD. Units are integers, money is Decimal (2 dp), instants are UTC datetimes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .contract import ENTITIES, EXTRA_ENTITIES, MOVEMENT_TYPES, PO_STATUSES, UNMET_POLICIES
from .money import parse_money

# --- scalar helpers ---------------------------------------------------------------------------------------------


def parse_ts(value: object) -> datetime:
    """ISO-8601 string with a zone to a UTC datetime. Naive values are refused."""
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp must be an ISO-8601 string")
    if d.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return d.astimezone(timezone.utc)


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"


def _id(row: dict, key: str) -> str:
    v = row[key]
    if not isinstance(v, str) or not v.strip() or len(v) > 128:
        raise ValueError(f"{key} must be a non-empty string")
    return v


def _opt_id(row: dict, key: str) -> str | None:
    return None if row.get(key) is None else _id(row, key)


def _int(row: dict, key: str, lo: int | None = None, hi: int = 10**9) -> int:
    v = row[key]
    if isinstance(v, bool) or not isinstance(v, int) or (lo is not None and v < lo) or v > hi or v < -hi:
        raise ValueError(f"{key} must be an integer" + (f" >= {lo}" if lo is not None else ""))
    return v


def _bool(row: dict, key: str) -> bool:
    if not isinstance(row[key], bool):
        raise ValueError(f"{key} must be a boolean")
    return row[key]


def _ts(row: dict, key: str) -> datetime:
    return parse_ts(row[key])


def _opt_ts(row: dict, key: str) -> datetime | None:
    return None if row.get(key) is None else parse_ts(row[key])


def _date(row: dict, key: str) -> date:
    v = row[key]
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if not isinstance(v, str):
        raise ValueError(f"{key} must be an ISO date")
    return date.fromisoformat(v)


def _money(row: dict, key: str) -> Decimal:
    return parse_money(row[key])


def _ratio(row: dict, key: str, hi: int = 1000) -> Decimal:
    v = row[key]
    if isinstance(v, bool) or isinstance(v, float) or not isinstance(v, (str, int, Decimal)):
        raise ValueError(f"{key} must be a decimal string")
    try:
        d = Decimal(v)
    except InvalidOperation:
        raise ValueError(f"{key} is not a number") from None
    if not d.is_finite() or d < 0 or d > hi:
        raise ValueError(f"{key} is out of range")
    return d


def _text(row: dict, key: str) -> str:
    v = row[key]
    if not isinstance(v, str) or len(v) > 500:
        raise ValueError(f"{key} must be a string")
    return v


def _row_must_be_dict(row: Any) -> dict:
    if not isinstance(row, dict):
        raise ValueError("a record must be an object")
    return row


# --- records ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Product:
    product_id: str
    sku: str
    unit_cost: Decimal
    pack_size: int
    minimum_order_quantity: int
    abc_class: str | None = None
    supplier_id: str | None = None


@dataclass(frozen=True)
class Location:
    location_id: str
    location_name: str
    timezone: str
    storage_capacity: int
    active: bool


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    supplier_name: str
    calendar_id: str
    quoted_lead_days: int
    active: bool


@dataclass(frozen=True)
class Sale:
    sale_id: str
    product_id: str
    location_id: str
    sold_at: datetime
    quantity: int


@dataclass(frozen=True)
class Movement:
    movement_id: str
    product_id: str
    location_id: str
    quantity_delta: int
    event_at: datetime
    movement_type: str


@dataclass(frozen=True)
class PurchaseOrder:
    purchase_order_id: str
    supplier_id: str
    ordered_at: datetime
    status: str
    currency: str


@dataclass(frozen=True)
class PoLine:
    po_line_id: str
    purchase_order_id: str
    product_id: str
    ordered_quantity: int
    unit_cost: Decimal


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    po_line_id: str
    location_id: str
    received_quantity: int
    received_at: datetime


@dataclass(frozen=True)
class Promotion:
    promotion_id: str
    product_id: str
    starts_at: datetime
    ends_at: datetime
    planned_uplift: Decimal           # the schedule: known when announced
    announced_at: datetime
    realised_uplift: Decimal | None   # an outcome: never a feature (P03-TEST-02)
    location_id: str | None = None


@dataclass(frozen=True)
class ForecastRun:
    forecast_run_id: str
    product_id: str
    location_id: str
    cutoff: datetime
    horizon_days: int
    selected_model: str


@dataclass(frozen=True)
class ForecastPoint:
    forecast_point_id: str
    forecast_run_id: str
    model: str
    target_date: date
    forecast_value: Decimal


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    scenario_name: str
    service_target: Decimal
    unmet_policy: str
    seed: int
    warmup_days: int
    replications: int


@dataclass(frozen=True)
class Backorder:
    backorder_id: str
    product_id: str
    location_id: str
    quantity: int
    opened_at: datetime
    closed_at: datetime | None
    scenario_id: str | None = None


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    product_id: str
    location_id: str
    quantity: int
    reserved_at: datetime
    released_at: datetime | None = None


@dataclass(frozen=True)
class Param:
    product_id: str
    location_id: str
    reorder_point: int
    target_position: int
    supplier_id: str | None = None


@dataclass(frozen=True)
class CostVersion:
    cost_version_id: str
    product_id: str
    unit_cost: Decimal
    effective_from: datetime


@dataclass(frozen=True)
class LostSale:
    lost_sale_id: str
    product_id: str
    location_id: str
    quantity: int
    occurred_at: datetime
    scenario_id: str | None = None


@dataclass(frozen=True)
class Closure:
    closure_id: str
    calendar_id: str
    closed_from: date
    closed_to: date


@dataclass(frozen=True)
class Latent:
    product_id: str
    location_id: str
    demand_date: date
    latent_quantity: int


def _product(r: dict) -> Product:
    return Product(_id(r, "product_id"), _id(r, "sku"), _money(r, "unit_cost"), _int(r, "pack_size", 1),
                   _int(r, "minimum_order_quantity", 0), _opt_id(r, "abc_class"), _opt_id(r, "supplier_id"))


def _location(r: dict) -> Location:
    return Location(_id(r, "location_id"), _text(r, "location_name"), _text(r, "timezone"),
                    _int(r, "storage_capacity", 0), _bool(r, "active"))


def _supplier(r: dict) -> Supplier:
    return Supplier(_id(r, "supplier_id"), _text(r, "supplier_name"), _id(r, "calendar_id"),
                    _int(r, "quoted_lead_days", 0, 3650), _bool(r, "active"))


def _sale(r: dict) -> Sale:
    return Sale(_id(r, "sale_id"), _id(r, "product_id"), _id(r, "location_id"), _ts(r, "sold_at"),
                _int(r, "quantity", 1))


def _movement(r: dict) -> Movement:
    kind = r["movement_type"]
    if kind not in MOVEMENT_TYPES:
        raise ValueError("unknown movement_type")
    delta = _int(r, "quantity_delta")
    if delta == 0 or (kind in ("receipt", "return") and delta < 0) or (kind == "sale" and delta > 0):
        raise ValueError("quantity_delta is zero or has the wrong sign for its movement_type")
    return Movement(_id(r, "movement_id"), _id(r, "product_id"), _id(r, "location_id"), delta, _ts(r, "event_at"), kind)


def _po(r: dict) -> PurchaseOrder:
    if r["status"] not in PO_STATUSES:
        raise ValueError("unknown purchase order status")
    return PurchaseOrder(_id(r, "purchase_order_id"), _id(r, "supplier_id"), _ts(r, "ordered_at"), r["status"],
                         _text(r, "currency"))


def _line(r: dict) -> PoLine:
    return PoLine(_id(r, "po_line_id"), _id(r, "purchase_order_id"), _id(r, "product_id"),
                  _int(r, "ordered_quantity", 1), _money(r, "unit_cost"))


def _receipt(r: dict) -> Receipt:
    return Receipt(_id(r, "receipt_id"), _id(r, "po_line_id"), _id(r, "location_id"), _int(r, "received_quantity", 1),
                   _ts(r, "received_at"))


def _promotion(r: dict) -> Promotion:
    s, e = _ts(r, "starts_at"), _ts(r, "ends_at")
    if e < s:
        raise ValueError("a promotion ends before it starts")
    realised = None if r.get("realised_uplift") is None else _ratio(r, "realised_uplift")
    return Promotion(_id(r, "promotion_id"), _id(r, "product_id"), s, e, _ratio(r, "planned_uplift"),
                     _ts(r, "announced_at"), realised, _opt_id(r, "location_id"))


def _forecast_run(r: dict) -> ForecastRun:
    return ForecastRun(_id(r, "forecast_run_id"), _id(r, "product_id"), _id(r, "location_id"), _ts(r, "cutoff"),
                       _int(r, "horizon_days", 1, 366), _id(r, "selected_model"))


def _forecast_point(r: dict) -> ForecastPoint:
    return ForecastPoint(_id(r, "forecast_point_id"), _id(r, "forecast_run_id"), _id(r, "model"),
                         _date(r, "target_date"), _ratio(r, "forecast_value", 10**9))


def _scenario(r: dict) -> Scenario:
    if r["unmet_policy"] not in UNMET_POLICIES:
        raise ValueError("unmet_policy is lost_sale or backlog")
    return Scenario(_id(r, "scenario_id"), _text(r, "scenario_name"), _ratio(r, "service_target"), r["unmet_policy"],
                    _int(r, "seed", 0), _int(r, "warmup_days", 0), _int(r, "replications", 1, 10000))


def _backorder(r: dict) -> Backorder:
    o, c = _ts(r, "opened_at"), _opt_ts(r, "closed_at")
    if c is not None and c < o:
        raise ValueError("a backorder closes before it opens")
    return Backorder(_id(r, "backorder_id"), _id(r, "product_id"), _id(r, "location_id"), _int(r, "quantity", 1), o, c,
                     _opt_id(r, "scenario_id"))


def _reservation(r: dict) -> Reservation:
    return Reservation(_id(r, "reservation_id"), _id(r, "product_id"), _id(r, "location_id"), _int(r, "quantity", 1),
                       _ts(r, "reserved_at"), _opt_ts(r, "released_at"))


def _param(r: dict) -> Param:
    return Param(_id(r, "product_id"), _id(r, "location_id"), _int(r, "reorder_point", 0), _int(r, "target_position", 0),
                 _opt_id(r, "supplier_id"))


def _cost_version(r: dict) -> CostVersion:
    return CostVersion(_id(r, "cost_version_id"), _id(r, "product_id"), _money(r, "unit_cost"), _ts(r, "effective_from"))


def _lost_sale(r: dict) -> LostSale:
    return LostSale(_id(r, "lost_sale_id"), _id(r, "product_id"), _id(r, "location_id"), _int(r, "quantity", 1),
                    _ts(r, "occurred_at"), _opt_id(r, "scenario_id"))


def _closure(r: dict) -> Closure:
    a, b = _date(r, "closed_from"), _date(r, "closed_to")
    if b < a:
        raise ValueError("a closure ends before it starts")
    return Closure(_id(r, "closure_id"), _id(r, "calendar_id"), a, b)


def _latent(r: dict) -> Latent:
    return Latent(_id(r, "product_id"), _id(r, "location_id"), _date(r, "demand_date"), _int(r, "latent_quantity", 0))


PARSERS: dict[str, Callable[[dict], Any]] = {
    "products": _product, "locations": _location, "sales": _sale, "inventory_movements": _movement,
    "purchase_orders": _po, "purchase_order_lines": _line, "receipts": _receipt, "suppliers": _supplier,
    "promotions": _promotion, "forecast_runs": _forecast_run, "forecast_points": _forecast_point,
    "policy_scenarios": _scenario, "backorders": _backorder, "reservations": _reservation,
    "replenishment_params": _param, "cost_versions": _cost_version, "lost_sales": _lost_sale,
    "calendar_closures": _closure, "latent_demand": _latent}

ID_FIELD: dict[str, str] = {
    "products": "product_id", "locations": "location_id", "sales": "sale_id", "inventory_movements": "movement_id",
    "purchase_orders": "purchase_order_id", "purchase_order_lines": "po_line_id", "receipts": "receipt_id",
    "suppliers": "supplier_id", "promotions": "promotion_id", "forecast_runs": "forecast_run_id",
    "forecast_points": "forecast_point_id", "policy_scenarios": "scenario_id", "backorders": "backorder_id",
    "reservations": "reservation_id", "replenishment_params": "product_id", "cost_versions": "cost_version_id",
    "lost_sales": "lost_sale_id", "calendar_closures": "closure_id", "latent_demand": "product_id"}

#: The attribute of ``Population`` that holds each entity.
ATTR = {e: e for e in (*ENTITIES, *EXTRA_ENTITIES)}


def parse_row(entity: str, row: Any) -> Any:
    """Parse one raw row; ``ValueError`` (including KeyError/TypeError) means MALFORMED_RECORD."""
    try:
        return PARSERS[entity](_row_must_be_dict(row))
    except (KeyError, TypeError, InvalidOperation, ArithmeticError) as exc:
        raise ValueError(f"{type(exc).__name__}: {exc}") from None


def row_id(entity: str, row: Any) -> str:
    """The id to report for a raw row (best effort for malformed rows). Parameter rows are keyed by product."""
    if isinstance(row, dict):
        v = row.get(ID_FIELD[entity])
        if entity == "replenishment_params" and v is not None and row.get("location_id") is not None:
            return f"{v}"
        if isinstance(v, str):
            return v
        if v is not None:
            return str(v)
    return "?"


@dataclass
class Population:
    """The accepted rows as typed records (a row set trusted by the database or by ingest)."""
    products: list[Product] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    sales: list[Sale] = field(default_factory=list)
    inventory_movements: list[Movement] = field(default_factory=list)
    purchase_orders: list[PurchaseOrder] = field(default_factory=list)
    purchase_order_lines: list[PoLine] = field(default_factory=list)
    receipts: list[Receipt] = field(default_factory=list)
    suppliers: list[Supplier] = field(default_factory=list)
    promotions: list[Promotion] = field(default_factory=list)
    forecast_runs: list[ForecastRun] = field(default_factory=list)
    forecast_points: list[ForecastPoint] = field(default_factory=list)
    policy_scenarios: list[Scenario] = field(default_factory=list)
    backorders: list[Backorder] = field(default_factory=list)
    reservations: list[Reservation] = field(default_factory=list)
    replenishment_params: list[Param] = field(default_factory=list)
    cost_versions: list[CostVersion] = field(default_factory=list)
    lost_sales: list[LostSale] = field(default_factory=list)
    calendar_closures: list[Closure] = field(default_factory=list)
    latent_demand: list[Latent] = field(default_factory=list)

    @classmethod
    def from_rows(cls, rows: dict[str, list[dict]]) -> "Population":
        pop = cls()
        for ent, items in rows.items():
            if ent in PARSERS:
                setattr(pop, ATTR[ent], [parse_row(ent, r) for r in items])
        return pop

    def with_lines(self, lines: list[PoLine]) -> "Population":
        """A copy with extra purchase order lines (a fixture state's ``add_purchase_order_lines``)."""
        out = Population(**{k: list(getattr(self, k)) for k in self.__dataclass_fields__})
        out.purchase_order_lines.extend(lines)
        return out

    # lookups -----------------------------------------------------------------------------------------------------
    def product(self, product_id: str) -> Product | None:
        return next((p for p in self.products if p.product_id == product_id), None)
