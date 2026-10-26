"""End-to-end run: ingest -> facts -> allocation -> returns -> metrics (D-01..D-06)."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .allocation import allocate_discounts, allocate_freight
from .contract import ELIGIBLE_ORDER_STATUSES, UNASSIGNED_REGION
from .costing import resolve_cost_version
from .errors import SHIPMENT_LINE_UNKNOWN, DomainError
from .fx import rate_for
from .ingest import IngestResult, validate_batch
from .metrics import Window, compute_metrics, in_window
from .models import Customer, RejectedRecord, ReturnEvent, ShipmentLineFact
from .money import ZERO
from .returns import recoverable_cost, validate_return


@dataclass
class PipelineResult:
    ingest: IngestResult
    facts: list[ShipmentLineFact]
    freight_by_line: dict[str, Decimal]
    discount_by_line: dict[str, Decimal]
    quarantined: list[RejectedRecord]
    metrics: dict
    unallocated_freight: Decimal = ZERO
    excluded_shipment_lines: list[str] = field(default_factory=list)
    returns: list[ReturnEvent] = field(default_factory=list)  # accepted credits, for credit_date windows (D-01a)
    unallocated_by_shipment: dict[str, Decimal] = field(default_factory=dict)  # D-04, in the reporting currency
    unallocated_freight_in_window: Decimal = ZERO  # the part of unallocated_freight shipped in ``window``


def _raw(obj: Any) -> dict[str, Any]:
    out = {}
    for k, v in dataclasses.asdict(obj).items():
        out[k] = v.isoformat() if isinstance(v, datetime) else (str(v) if isinstance(v, Decimal) else v)
    return out


def region_for(customers: list[Customer], customer_id: str, shipped_at: datetime) -> str:
    """Customer version with greatest effective_from <= shipped date, else UNASSIGNED (D-06)."""
    day = shipped_at.astimezone(timezone.utc).date().isoformat()
    cands = [c for c in customers if c.customer_id == customer_id and c.effective_from <= day]
    if not cands:
        return UNASSIGNED_REGION
    return max(cands, key=lambda c: c.effective_from).region_id


def run_pipeline(inputs: dict, include_returns: bool,
                 window: Window = (None, None)) -> PipelineResult:
    ing = validate_batch(inputs)
    acc = ing.accepted
    orders = {o.order_id: o for o in acc["orders"]}
    lines = {x.line_id: x for x in acc["order_lines"]}
    shipments = {s.shipment_id: s for s in acc["shipments"]}
    rates, costs = acc["exchange_rates"], acc["cost_versions"]
    quarantined: list[RejectedRecord] = []
    excluded: list[str] = []

    def quarantine(entity: str, rid: str, err: DomainError, obj: Any) -> None:
        quarantined.append(RejectedRecord(entity, rid, err.code, _raw(obj)))
        ing.counts[entity]["quarantined"] += 1

    # Facts without allocation (D-01, D-02, D-03).
    base: dict[str, ShipmentLineFact] = {}
    kept_sls = []
    native_gross: dict[str, Decimal] = {}
    ship_rate: dict[str, Decimal] = {}
    for sl in acc["shipment_lines"]:
        ln, shp = lines[sl.line_id], shipments[sl.shipment_id]
        order = orders[ln.order_id]
        if order.status not in ELIGIBLE_ORDER_STATUSES:
            excluded.append(sl.shipment_line_id)
            continue
        day = shp.shipped_at.astimezone(timezone.utc).date().isoformat()
        try:
            rate = rate_for(order.currency, day, rates)
            srate = rate_for(shp.currency, day, rates)
            cv = resolve_cost_version(ln.product_id, shp.shipped_at, costs)
        except DomainError as err:
            quarantine("shipment_lines", sl.shipment_line_id, err, sl)
            continue
        native_gross[sl.shipment_line_id] = sl.shipped_quantity * ln.unit_price
        ship_rate[sl.shipment_id] = srate
        base[sl.shipment_line_id] = ShipmentLineFact(
            shipment_line_id=sl.shipment_line_id, shipment_id=shp.shipment_id,
            order_id=order.order_id, line_id=ln.line_id, customer_id=order.customer_id,
            product_id=ln.product_id,
            region_id=region_for(acc["customers"], order.customer_id, shp.shipped_at),
            shipped_at=shp.shipped_at, currency=order.currency, fx_rate=rate,
            shipped_quantity=sl.shipped_quantity, unit_price=ln.unit_price * rate,
            gross_sales=native_gross[sl.shipment_line_id] * rate, allocated_discount=ZERO,
            cost_version_id=cv.cost_version_id, unit_cost=cv.unit_cost,
            cogs=sl.shipped_quantity * cv.unit_cost, freight=ZERO, returned_quantity=0,
            merchandise_credit=ZERO, recoverable_return_cost=ZERO)
        kept_sls.append(sl)

    # Discounts (D-04), allocated natively then converted.
    disc_native = allocate_discounts(list(lines.values()), acc["discounts"], kept_sls)
    discount_by_line = {k: v * base[k].fx_rate for k, v in sorted(disc_native.items())}

    # Freight (D-04), per shipment over its included lines.
    freight_by_line: dict[str, Decimal] = {}
    unalloc_by_shp: dict[str, Decimal] = {}
    declared = ZERO
    for shp_id in sorted({sl.shipment_id for sl in kept_sls}):
        shp = shipments[shp_id]
        sls = [sl for sl in kept_sls if sl.shipment_id == shp_id]
        fa = allocate_freight(shp, sls, native_gross)
        r = ship_rate[shp_id]
        freight_by_line.update({k: v * r for k, v in fa.allocations.items()})
        if fa.unallocated:
            unalloc_by_shp[shp_id] = fa.residual * r
        if in_window(shp.shipped_at, window):
            declared += shp.shipping_cost * r
    facts = {k: dataclasses.replace(f, allocated_discount=discount_by_line.get(k, ZERO),
                                    freight=freight_by_line.get(k, ZERO))
             for k, f in base.items()}

    # Returns (D-06 C03), recognised at the credit-date rate (D-02).
    events: list[ReturnEvent] = []
    if include_returns:
        prior: dict[str, list] = {}
        sl_by_id = {sl.shipment_line_id: sl for sl in acc["shipment_lines"]}
        for ret in sorted(acc["returns"], key=lambda r: (r.credit_date, r.return_id)):
            fact = facts.get(ret.shipment_line_id)
            try:
                if fact is None:
                    raise DomainError(SHIPMENT_LINE_UNKNOWN, "shipment line not in the population",
                                      details={"shipment_line_id": ret.shipment_line_id})
                validate_return(sl_by_id[ret.shipment_line_id], prior.get(ret.shipment_line_id, []),
                                ret.returned_quantity, ret.credit_amount)
                credit = ret.credit_amount * rate_for(fact.currency, ret.credit_date, rates)
            except DomainError as err:
                quarantine("returns", ret.return_id, err, ret)
                continue
            prior.setdefault(ret.shipment_line_id, []).append(ret)
            rec = recoverable_cost(fact, ret.returned_quantity)
            events.append(ReturnEvent(ret.return_id, ret.shipment_line_id, ret.credit_date,
                                      ret.returned_quantity, credit, rec))
            facts[fact.shipment_line_id] = dataclasses.replace(
                fact, returned_quantity=fact.returned_quantity + ret.returned_quantity,
                merchandise_credit=fact.merchandise_credit + credit,
                recoverable_return_cost=fact.recoverable_return_cost
                + rec)

    fact_list = [facts[k] for k in sorted(facts)]
    in_win = [f for f in fact_list if in_window(f.shipped_at, window)]
    in_win_ids = {f.shipment_id for f in in_win}
    unalloc_w = sum((v for k, v in unalloc_by_shp.items() if k in in_win_ids), ZERO)
    metrics = compute_metrics(fact_list, window, unallocated_freight=unalloc_w,
                              declared_shipping_cost=declared, returns=events)
    return PipelineResult(ing, fact_list, freight_by_line, discount_by_line,
                          sorted(quarantined, key=lambda q: (q.entity, q.id)), metrics,
                          unallocated_freight=sum(unalloc_by_shp.values(), ZERO), excluded_shipment_lines=sorted(excluded), returns=events,
                          unallocated_by_shipment=dict(sorted(unalloc_by_shp.items())),
                          unallocated_freight_in_window=unalloc_w)
