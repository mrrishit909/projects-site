"""Metric aggregation (D-01..D-06). ``compute_metrics`` returns EXACTLY the keys of expected.json; rates come from
aggregated numerators and denominators (never an average of rates), money is a 2 dp string, rates 6 dp."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable, Mapping

from . import demand, ledger, replenishment
from .contract import GROUP_KEYS, METRIC_KEYS
from .errors import INVALID_WINDOW, DomainError
from .models import Population, PoLine, parse_row, iso_z
from .money import cost_in_force, d2, d6, on_hand_value, ratio, utc_date
from .suppliers import open_quantity

Window = tuple[datetime | None, datetime | None]


def check_window(window: Window) -> None:
    lo, hi = window
    if lo is not None and hi is not None and lo >= hi:
        raise DomainError(INVALID_WINDOW, "window start must be before end", details={"from": iso_z(lo), "to": iso_z(hi)})


def state_lines(pop: Population, state: Mapping[str, Any] | None) -> list[PoLine]:
    """The extra purchase order lines of a fixture state; each must reference a known purchase order and product."""
    out: list[PoLine] = []
    for row in (state or {}).get("add_purchase_order_lines", []):
        line = parse_row("purchase_order_lines", row)
        if line.purchase_order_id not in {o.purchase_order_id for o in pop.purchase_orders}:
            raise DomainError("UNKNOWN_REFERENCE", f"state line {line.po_line_id} references an unknown purchase order")
        out.append(line)
    return out


def supplier_of(pop: Population, product_id: str) -> str:
    """The supplier a product is bought from: its own record, a parameter row, its latest purchase order, else none."""
    prod = pop.product(product_id)
    if prod is not None and prod.supplier_id:
        return prod.supplier_id
    for p in sorted(pop.replenishment_params, key=lambda p: p.location_id):
        if p.product_id == product_id and p.supplier_id:
            return p.supplier_id
    orders = {o.purchase_order_id: o for o in pop.purchase_orders}
    lines = [(orders[l.purchase_order_id].ordered_at, l.po_line_id, orders[l.purchase_order_id].supplier_id)
             for l in pop.purchase_order_lines if l.product_id == product_id and l.purchase_order_id in orders]
    return max(lines)[2] if lines else "unassigned"


def allocation_location(pop: Population, product_id: str) -> str | None:
    """Purchase order lines carry no location: a product's open quantity counts at its first parameter location, else
    the first location with movements, else the first location."""
    for pool in ([p.location_id for p in pop.replenishment_params if p.product_id == product_id],
                 [m.location_id for m in pop.inventory_movements if m.product_id == product_id],
                 [l.location_id for l in pop.locations]):
        if pool:
            return min(pool)
    return None


def on_order_by_product(pop: Population, as_of: datetime) -> dict[str, int]:
    """Open quantity (ordered - received at or before as_of) of lines on confirmed orders placed by as_of."""
    orders = {o.purchase_order_id: o for o in pop.purchase_orders}
    out: dict[str, int] = {}
    for l in pop.purchase_order_lines:
        o = orders.get(l.purchase_order_id)
        if o is not None and o.status == "confirmed" and o.ordered_at <= as_of:
            out[l.product_id] = out.get(l.product_id, 0) + open_quantity(l, pop.receipts, as_of)
    return out


def default_start(pop: Population, as_of: datetime) -> datetime:
    stamps = [s.sold_at for s in pop.sales] + [m.event_at for m in pop.inventory_movements]
    first = min(stamps) if stamps else as_of
    return datetime.combine(first.astimezone(timezone.utc).date(), datetime.min.time(), tzinfo=timezone.utc)


def compute_metrics(pop: Population, as_of: datetime, window: Window = (None, None), state: Mapping[str, Any] | None = None,
                    *, products: Iterable[str] | None = None, locations: Iterable[str] | None = None) -> dict[str, Any]:
    """The metric set at ``as_of`` over the window [start, end) (an absent end means up to and including as_of).
    ``products`` / ``locations`` narrow the scope (used by ``group_metrics``). ``state`` may add purchase order lines."""
    check_window(window)
    extra = state_lines(pop, state)
    if extra:
        pop = pop.with_lines(extra)
    start = window[0] or default_start(pop, as_of)
    end = window[1]
    pset = None if products is None else set(products)
    lset = None if locations is None else set(locations)
    inp = lambda p, l: (pset is None or p in pset) and (lset is None or l in lset)  # noqa: E731

    moves = [m for m in pop.inventory_movements if inp(m.product_id, m.location_id)]
    stocks = ledger.reconstruct(moves, as_of)
    on_hand = sum(s.on_hand for s in stocks.values())
    running_min = min([0, *[s.running_min for s in stocks.values()]])
    naive_min = min([0, *[s.timestamp_order_min for s in stocks.values()]])

    alloc = {p.product_id: allocation_location(pop, p.product_id) for p in pop.products}
    open_by_product = on_order_by_product(pop, as_of)
    on_order = sum(q for p, q in open_by_product.items() if inp(p, alloc.get(p) or ""))
    open_bo: dict[tuple[str, str], int] = {}
    for b in pop.backorders:
        if inp(b.product_id, b.location_id) and b.opened_at <= as_of and (b.closed_at is None or b.closed_at > as_of):
            open_bo[(b.product_id, b.location_id)] = open_bo.get((b.product_id, b.location_id), 0) + b.quantity
    backorders = sum(open_bo.values())
    reserved = sum(r.quantity for r in pop.reservations if inp(r.product_id, r.location_id) and r.reserved_at <= as_of
                   and (r.released_at is None or r.released_at > as_of))
    position = replenishment.inventory_position(on_hand, on_order, backorders)  # reserved is NOT subtracted

    out: dict[str, Any] = {}
    params = [p for p in pop.replenishment_params if inp(p.product_id, p.location_id)]
    if params:
        rows = []
        for p in params:
            prod = pop.product(p.product_id)
            st = stocks.get((p.product_id, p.location_id))
            oo = open_by_product.get(p.product_id, 0) if alloc.get(p.product_id) == p.location_id else 0
            rows.append(replenishment.replenish(st.on_hand if st else 0, oo, open_bo.get((p.product_id, p.location_id), 0),
                                                p.reorder_point, p.target_position, prod.minimum_order_quantity,
                                                prod.pack_size))
        out.update(reorder_point=sum(r.reorder_point for r in rows), target_position=sum(r.target_position for r in rows),
                   reorder_triggered=any(r.triggered for r in rows), raw_order=sum(r.raw_order for r in rows),
                   order_after_moq=sum(r.order_after_moq for r in rows), order_quantity=sum(r.order_quantity for r in rows))
        if len(rows) == 1:  # one parameter row: the position is that row's own
            position = rows[0].position
    else:
        out.update(reorder_point=None, target_position=None, reorder_triggered=None, raw_order=None,
                   order_after_moq=None, order_quantity=None)

    ds = demand.summarise((s for s in pop.sales if inp(s.product_id, s.location_id)),
                          (b for b in pop.backorders if inp(b.product_id, b.location_id)),
                          (l for l in pop.lost_sales if inp(l.product_id, l.location_id)), start, end, as_of)
    empty = not moves and not any(inp(s.product_id, s.location_id) for s in pop.sales)
    prods = {p.product_id: p for p in pop.products}
    versions: dict[str, list] = {}
    for v in pop.cost_versions:
        versions.setdefault(v.product_id, []).append(v)
    capital = sum((on_hand_value(s.on_hand, cost_in_force(prods[s.product_id].unit_cost, versions.get(s.product_id, []),
                                                           utc_date(as_of))) for s in stocks.values()), Decimal(0))
    out.update(on_hand=on_hand, on_order=on_order, backorders=backorders, reserved=reserved, available=on_hand - reserved,
               inventory_position=position, working_capital=d2(capital), requested_units=ds.requested,
               fulfilled_units=ds.fulfilled, unmet_units=ds.unmet, fill_rate=d6(ds.fill_rate),
               observed_days=ds.observed_days, stockout_day_count=len(ds.stockout_dates),
               stockout_days=None if empty else d6(ds.stockout_day_ratio), running_stock_min=running_min,
               timestamp_order_stock_min=naive_min, negative_stock=any(s.negative for s in stocks.values()),
               empty_population=empty)
    return {k: out[k] for k in METRIC_KEYS}


def negative_stock_flags(pop: Population, as_of: datetime) -> list[dict[str, Any]]:
    return [{"flag": f, "product_id": s.product_id, "location_id": s.location_id, "on_hand_raw": s.on_hand_raw}
            for s in ledger.reconstruct(pop.inventory_movements, as_of).values() for f in s.flags]


def group_values(pop: Population, key: str) -> dict[str, dict[str, Any]]:
    """group value -> the scope (products, locations) of the group."""
    if key not in GROUP_KEYS:
        raise ValueError(f"group_by must be one of {', '.join(GROUP_KEYS)}")
    groups: dict[str, set[str]] = {}
    if key == "product":
        return {p.product_id: {"products": {p.product_id}} for p in sorted(pop.products, key=lambda p: p.product_id)}
    if key == "location":
        return {l.location_id: {"locations": {l.location_id}} for l in sorted(pop.locations, key=lambda l: l.location_id)}
    for p in pop.products:
        g = supplier_of(pop, p.product_id) if key == "supplier" else (p.abc_class or "unclassified")
        groups.setdefault(g, set()).add(p.product_id)
    return {g: {"products": ps} for g, ps in sorted(groups.items())}


def group_metrics(pop: Population, key: str, as_of: datetime, window: Window = (None, None),
                  state: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return {g: compute_metrics(pop, as_of, window, state, **scope) for g, scope in group_values(pop, key).items()}


def supplementary(pop: Population, as_of: datetime, window: Window = (None, None)) -> dict[str, Any]:
    """Average daily inventory value and turnover (annualised COGS / average inventory value, D-05). Each day is valued
    at the cost in force on that day (P03-TEST-12)."""
    start = window[0] or default_start(pop, as_of)
    first = start.astimezone(timezone.utc).date()
    last = demand.last_observed_day(window[1], as_of)
    if last < first:
        return {"average_inventory_value": None, "annualised_cogs": None, "inventory_turnover": None}
    eod = ledger.end_of_day_on_hand([m for m in pop.inventory_movements if m.event_at <= as_of], first, last)
    prods = {p.product_id: p for p in pop.products}
    versions: dict[str, list] = {}
    for v in pop.cost_versions:
        versions.setdefault(v.product_id, []).append(v)
    days = (last - first).days + 1
    total = Decimal(0)
    for (p, _), series in eod.items():
        for d, qty in series.items():
            total += on_hand_value(qty, cost_in_force(prods[p].unit_cost, versions.get(p, []), d))
    cogs = Decimal(0)
    for s in pop.sales:
        if demand.in_window(s.sold_at, start, window[1], as_of):
            cogs += s.quantity * cost_in_force(prods[s.product_id].unit_cost, versions.get(s.product_id, []), utc_date(s.sold_at))
    avg = Fraction(total) / days
    annual = Fraction(cogs) * 365 / days
    return {"average_inventory_value": d2(avg), "annualised_cogs": d2(annual),
            "inventory_turnover": d6(ratio(annual, avg))}
