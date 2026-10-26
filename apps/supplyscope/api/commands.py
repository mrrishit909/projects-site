"""Commands C01..C10 (docs/api-contract.md, docs/contracts.md D-01..D-06).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit together or
not at all. Input is validated (pydantic, then domain rules) before the first write. The same ``idempotency_key`` with
the same payload by the same actor returns the stored response; another payload or another actor is a 409.

Lock order (deadlock avoidance, D-08 of Onboard Studio): the idempotency advisory lock first, then rows in a fixed order
(scenario read, PO line ``FOR UPDATE``, then sorted ``(product, location)`` advisory locks, inserts in sorted-id order).
A deadlock or serialization failure rolls the whole attempt back and is retried; when it keeps failing the answer is
409 CONCURRENT_UPDATE, never a 500.

C04 classify-skus answers 501 NOT_IMPLEMENTED (extension milestone).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

import psycopg
from psycopg.types.json import Jsonb
from supplyscope import CONTRACT_VERSION, DomainError, ledger, suppliers
from supplyscope import metrics as dm
from supplyscope.demand import compare_policies
from supplyscope.errors import (RECEIPT_BEFORE_LEAD_TIME, RECEIPT_BEFORE_ORDER, RECEIPT_EXCEEDS_ORDERED,
                                UNMET_POLICY_CONFLICT)
from supplyscope.forecast import dataset_end, forecast_demand, last_complete_day
from supplyscope.ingest import movement_payload, screen_movements
from supplyscope.models import iso_z, parse_row, parse_ts
from supplyscope.money import d2, d6
from supplyscope.replenishment import (derived_parameters, effective_lead_days, lead_time_demand, replenish,
                                       safety_stock, z_value)

from data.seed import canonical_json, insert_rejected, sha256_hex

from . import db
from .errors import ApiError, detail, from_domain
from .schemas import Envelope

Conn = psycopg.Connection[db.Row]
ROLES = frozenset({"planner", "buyer", "admin"})
DEFAULT_SERVICE_TARGET = Decimal("0.95")


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str


@dataclass
class Audit:
    entity_type: str
    entity_id: str
    action: str
    before_version: int | None = None
    after_version: int | None = None
    reason: str | None = None


@dataclass
class Outcome:
    status: str
    result: dict[str, Any]
    version: int = 1
    warnings: list[dict[str, Any]] = field(default_factory=list)
    audit: Audit | None = None


Handler = Callable[[Conn, Any, Actor], Outcome]


def warning(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path}


def _not_found(path: str, rule_id: str, what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found", [detail(path, rule_id, f"{what} not found")])


def _conflict(code: str, message: str, path: str) -> ApiError:
    return ApiError(409, code, message, [detail(path, code, message)])


def _invalid(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    item = detail(path, code, message)
    if context:
        item["context"] = context
    return ApiError(422, "VALIDATION_FAILED", message, [item])


def _domain(fn: Callable[[], Any], path: str) -> Any:
    try:
        return fn()
    except DomainError as err:
        raise from_domain(err, path) from None


def not_implemented(name: str, label: str) -> ApiError:
    return ApiError(501, "NOT_IMPLEMENTED", f"{name} ({label}) is an extension-milestone command and is not implemented",
                    [detail("command", "NOT_IMPLEMENTED", f"{label} is not part of the slice")])


# --- idempotent execution ---------------------------------------------------------------------------------------

_INSTANT_FIELDS = frozenset({"occurred_at", "as_of", "cutoff", "at", "event_at"})


def _normalise(value: Any) -> Any:
    """An instant is hashed as the UTC instant it names, re-serialised with Z, so ``+00:00``, ``Z`` and ``+01:00``
    spellings of the same instant are the same payload (also inside nested rows such as ``movements[].event_at``)."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _INSTANT_FIELDS and isinstance(v, str):
                try:
                    v = iso_z(parse_ts(v))
                except ValueError:
                    pass
            out[k] = _normalise(v)
        return out
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    return value


def _payload_hash(name: str, req: Envelope) -> str:
    """sha256 over the canonical command name + input (request_id and key excluded; instants normalised)."""
    try:
        text = canonical_json({"command": name, "input": _normalise(req.input.model_dump())})  # type: ignore[attr-defined]
    except ValueError:  # NaN / Infinity are not JSON
        raise _invalid("JSON_NON_FINITE", "input contains a non-finite number", "input") from None
    if "\\u0000" in text:
        raise _invalid("NUL_CHARACTER", "input contains a NUL character", "input")
    return sha256_hex(text)


_UNIQUE_CODES = {
    "receipts_pkey": ("RECEIPT_EXISTS", "a receipt with this id already exists"),
    "backorders_pkey": ("UNMET_ALREADY_RECORDED", "this unmet demand is already recorded"),
    "lost_sales_pkey": ("UNMET_ALREADY_RECORDED", "this unmet demand is already recorded"),
    "backorders_demand_ref_key": ("UNMET_ALREADY_RECORDED", "this unmet demand is already recorded"),
    "lost_sales_demand_ref_key": ("UNMET_ALREADY_RECORDED", "this unmet demand is already recorded"),
    "inventory_movements_movement_id_key": ("DUPLICATE_MOVEMENT_ID", "a movement with this id exists"),
}

#: A deadlock or serialization failure rolls the whole command back; it is retried this many times in all.
MAX_ATTEMPTS = 3
_RETRYABLE = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)


def execute(name: str, req: Envelope, actor: Actor, handler: Handler) -> tuple[dict[str, Any], bool]:
    """Run ``handler`` once per idempotency key. Returns ``(response body, replayed)``. Retries a deadlock, then 409."""
    payload_hash = _payload_hash(name, req)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _execute_once(name, req, actor, handler, payload_hash)
        except _RETRYABLE:
            if attempt < MAX_ATTEMPTS:
                time.sleep(random.uniform(0.005, 0.03) * attempt)
    raise _conflict("CONCURRENT_UPDATE", f"the command lost a concurrent update {MAX_ATTEMPTS} times; retry it", "input")


def _execute_once(name: str, req: Envelope, actor: Actor, handler: Handler,
                  payload_hash: str) -> tuple[dict[str, Any], bool]:
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (req.idempotency_key,))
        prior = conn.execute("SELECT payload_hash, actor_id, result FROM command_results WHERE idempotency_key = %s",
                             (req.idempotency_key,)).fetchone()
        if prior is not None:
            if prior["actor_id"] is not None and prior["actor_id"] != actor.actor_id:  # bound to the actor
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "this idempotency_key was used by a different actor",
                               [detail("idempotency_key", "IDEMPOTENCY_ACTOR_MISMATCH", "same key, different X-Actor-Id")])
            if prior["payload_hash"] != payload_hash:
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "this idempotency_key was used with a different payload",
                               [detail("idempotency_key", "IDEMPOTENCY_PAYLOAD_MISMATCH",
                                       "same key, different payload_hash")])
            return prior["result"], True
        try:
            out = handler(conn, req, actor)
        except psycopg.errors.UniqueViolation as exc:
            code, message = _UNIQUE_CODES.get(exc.diag.constraint_name or "",
                                              ("ALREADY_EXISTS", "a row with this key already exists"))
            raise _conflict(code, message, "input") from None
        except psycopg.errors.IntegrityError as exc:  # triggers: immutable movements, receipt rules, one unmet kind
            raise _conflict("INTEGRITY_RULE", exc.diag.message_primary or "integrity rule violated", "input") from None
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        if out.audit is not None:
            a = out.audit
            conn.execute(
                "INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, before_version, "
                "after_version, reason, request_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (f"evt-{uuid.uuid4().hex[:16]}", a.entity_type, a.entity_id, a.action, actor.actor_id,
                 a.before_version, a.after_version, a.reason, req.request_id))
        body = {"command_id": command_id, "status": out.status, "result": out.result, "warnings": out.warnings,
                "version": out.version}
        conn.execute("INSERT INTO command_results (idempotency_key, payload_hash, actor_id, command_id, status, result) "
                     "VALUES (%s, %s, %s, %s, %s, %s)",
                     (req.idempotency_key, payload_hash, actor.actor_id, command_id, out.status, Jsonb(body)))
        return body, False


# --- shared lookups ---------------------------------------------------------------------------------------------

def _need(conn: Conn, table: str, column: str, value: str, path: str, what: str) -> db.Row:
    row = conn.execute(f"SELECT * FROM {table} WHERE {column} = %s", (value,)).fetchone()  # constants at call sites
    if row is None:
        raise _not_found(path, f"{what.upper().replace(' ', '_')}_UNKNOWN", what)
    return row


def _lock_pairs(conn: Conn, pairs: list[tuple[str, str]]) -> None:
    """Advisory locks on (product, location) pairs in sorted order: every command takes them in the same order."""
    for p, l in sorted(set(pairs)):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"pair:{p}:{l}",))


def _short(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _scope_pairs(pop: Any, product_id: str | None, location_id: str | None) -> list[tuple[str, str]]:
    pairs = {(p.product_id, p.location_id) for p in pop.replenishment_params}
    pairs |= {(m.product_id, m.location_id) for m in pop.inventory_movements}
    pairs |= {(s.product_id, s.location_id) for s in pop.sales}
    return sorted(pr for pr in pairs if (product_id in (None, pr[0])) and (location_id in (None, pr[1])))


def _check_scope(conn: Conn, product_id: str | None, location_id: str | None) -> None:
    if product_id is not None:
        _need(conn, "products", "product_id", product_id, "input.product_id", "product")
    if location_id is not None:
        _need(conn, "locations", "location_id", location_id, "input.location_id", "location")


# --- C01 load-movements -----------------------------------------------------------------------------------------

def load_movements(conn: Conn, req: Any, actor: Actor) -> Outcome:
    rows = req.input.movements
    ids = sorted({r["movement_id"] for r in rows if isinstance(r, dict) and isinstance(r.get("movement_id"), str)})
    existing: dict[str, str] = {}
    for r in conn.execute("SELECT * FROM inventory_movements WHERE movement_id = ANY(%s)", (ids,)).fetchall():
        existing[r["movement_id"]] = movement_payload(parse_row("inventory_movements", r))
    products = {r["product_id"] for r in conn.execute("SELECT product_id FROM products").fetchall()}
    locations = {r["location_id"] for r in conn.execute("SELECT location_id FROM locations").fetchall()}
    accepted, rejected = screen_movements(rows, products, locations, existing)
    payload_hash = _payload_hash("load-movements", req)
    batch_id = f"batch-{payload_hash[:16]}"
    _lock_pairs(conn, [(m.product_id, m.location_id) for _, m in accepted])
    inserted = 0
    for row, m in sorted(accepted, key=lambda t: t[1].movement_id):  # sorted-id inserts: a fixed lock order
        n = conn.execute("INSERT INTO inventory_movements (movement_id, product_id, location_id, quantity_delta, "
                         "event_at, movement_type) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                         (m.movement_id, m.product_id, m.location_id, m.quantity_delta, m.event_at,
                          m.movement_type)).rowcount
        if n:
            inserted += 1
        else:  # a concurrent load won the id between the check and the insert: an exact replay or a conflict
            from supplyscope.ingest import RejectedRecord
            rejected.append(RejectedRecord("inventory_movements", m.movement_id, "DUPLICATE_MOVEMENT_ID", row,
                                           "loaded concurrently"))
    status = "accepted" if not rejected else ("partial" if inserted else "rejected")
    conn.execute("INSERT INTO raw_batches (batch_id, idempotency_key, payload_hash, payload, status) "
                 "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                 (batch_id, req.idempotency_key, payload_hash, Jsonb({"movements": rows}), status))
    rejected.sort(key=lambda r: (r.entity, r.id, r.reason_code))
    insert_rejected(conn, batch_id, rejected)
    result = {"batch_id": batch_id, "received": len(rows), "accepted": inserted, "rejected": len(rejected),
              "rejected_records": [{"id": r.id, "reason_code": r.reason_code} for r in rejected]}
    return Outcome("loaded" if not rejected else status, result,
                   warnings=[warning(r.reason_code, r.message or r.reason_code, f"input.movements[{r.id}]") for r in rejected],
                   audit=Audit("raw_batch", batch_id, "load-movements"))


# --- C02 reconstruct-stock --------------------------------------------------------------------------------------

def reconstruct_stock(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    as_of = parse_ts(inp.as_of)
    _check_scope(conn, inp.product_id, inp.location_id)
    pop = db.load_population(conn)
    moves = [m for m in pop.inventory_movements if inp.product_id in (None, m.product_id)
             and inp.location_id in (None, m.location_id)]
    stocks = ledger.reconstruct(moves, as_of)
    _lock_pairs(conn, list(stocks))
    rows, warnings = [], []
    for (p, l), s in sorted(stocks.items()):
        reserved = sum(r.quantity for r in pop.reservations if (r.product_id, r.location_id) == (p, l)
                       and r.reserved_at <= as_of and (r.released_at is None or r.released_at > as_of))
        flags = s.flags
        conn.execute(
            "INSERT INTO stock_snapshots (as_of, product_id, location_id, on_hand_raw, on_hand, reserved, available, "
            "running_stock_min, negative_stock, flags) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (as_of, product_id, location_id) DO UPDATE SET on_hand_raw = EXCLUDED.on_hand_raw, "
            "on_hand = EXCLUDED.on_hand, reserved = EXCLUDED.reserved, available = EXCLUDED.available, "
            "running_stock_min = EXCLUDED.running_stock_min, negative_stock = EXCLUDED.negative_stock, "
            "flags = EXCLUDED.flags",
            (as_of, p, l, s.on_hand_raw, s.on_hand, reserved, s.on_hand - reserved, s.running_min, s.negative,
             Jsonb(flags)))
        rows.append({"product_id": p, "location_id": l, "on_hand_raw": s.on_hand_raw, "on_hand": s.on_hand,
                     "reserved": reserved, "available": s.on_hand - reserved, "running_stock_min": s.running_min,
                     "negative_stock": s.negative, "flags": flags})
        if s.negative:
            warnings.append(warning("NEGATIVE_STOCK", "the reconstruction is negative: flagged, valued at zero",
                                    f"stock[{p}:{l}]"))
    return Outcome("reconstructed", {"as_of": iso_z(as_of), "snapshots": rows}, warnings=warnings,
                   audit=Audit("stock_snapshot", iso_z(as_of) or "", "reconstruct-stock"))


# --- C03 forecast-demand ----------------------------------------------------------------------------------------

def forecast_demand_command(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    cutoff = parse_ts(inp.cutoff)
    _check_scope(conn, inp.product_id, inp.location_id)
    pop = db.load_population(conn)
    end = dataset_end(pop.sales, pop.inventory_movements, pop.receipts)
    pairs = sorted({(s.product_id, s.location_id) for s in pop.sales if s.sold_at <= cutoff
                    and inp.product_id in (None, s.product_id) and inp.location_id in (None, s.location_id)})
    if inp.product_id and inp.location_id and (inp.product_id, inp.location_id) not in pairs:
        pairs.append((inp.product_id, inp.location_id))
    _lock_pairs(conn, pairs)
    runs, warnings = [], []
    for p, l in sorted(pairs):
        fc = _domain(lambda: forecast_demand(pop.sales, pop.promotions, p, l, cutoff, inp.horizon_days, end),
                     "input.cutoff")
        info = canonical_json({"cutoff": iso_z(cutoff), "horizon": inp.horizon_days, "p": p, "l": l,
                               "sales": sorted((s.sale_id, s.quantity, iso_z(s.sold_at)) for s in pop.sales
                                               if (s.product_id, s.location_id) == (p, l) and s.sold_at <= cutoff),
                               "promotions": sorted((x.promotion_id, str(x.planned_uplift), iso_z(x.starts_at),
                                                     iso_z(x.ends_at)) for x in pop.promotions
                                                    if x.product_id == p and x.announced_at <= cutoff)})
        info_hash = sha256_hex(info)
        run_id = f"fr-{info_hash[:16]}"
        report = fc.model_report()
        conn.execute("INSERT INTO forecast_runs (forecast_run_id, product_id, location_id, cutoff, horizon_days, "
                     "selected_model, information_hash, model_report, notes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                     "ON CONFLICT DO NOTHING", (run_id, p, l, cutoff, inp.horizon_days, fc.selected_model, info_hash,
                                                Jsonb(report), Jsonb(fc.notes)))
        for model, vals in sorted(fc.points.items()):
            for k, v in enumerate(vals):
                day = fc.start + timedelta(days=k)
                conn.execute("INSERT INTO forecast_points (forecast_point_id, forecast_run_id, model, target_date, "
                             "forecast_value) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                             (f"{run_id}:{model}:{day.isoformat()}", run_id, model, day, d2(v)))
        runs.append({"forecast_run_id": run_id, "product_id": p, "location_id": l, "selected_model": fc.selected_model,
                     "baselines": ["naive", "seasonal_naive"], "beats_baseline": fc.beats_baseline,
                     "model_report": report, "notes": fc.notes, "history_days": fc.history_days,
                     "first_target_date": fc.start.isoformat()})
        warnings += [warning(n, f"{n} for {p}:{l}", f"forecast[{p}:{l}]") for n in fc.notes]
    return Outcome("forecasted", {"cutoff": iso_z(cutoff), "horizon_days": inp.horizon_days, "runs": runs},
                   warnings=warnings, audit=Audit("forecast", iso_z(cutoff) or "", "forecast-demand"))


# --- C05 calculate-replenishment --------------------------------------------------------------------------------

def calculate_replenishment(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    as_of = parse_ts(inp.as_of)
    scenario = None
    if inp.scenario_id:
        scenario = _need(conn, "policy_scenarios", "scenario_id", inp.scenario_id, "input.scenario_id", "scenario")
    z = _domain(lambda: z_value(scenario["service_target"] if scenario else DEFAULT_SERVICE_TARGET),
                "input.scenario_id")
    _check_scope(conn, inp.product_id, inp.location_id)
    pop = db.load_population(conn)
    pairs = _scope_pairs(pop, inp.product_id, inp.location_id)
    _lock_pairs(conn, pairs)
    stocks = ledger.reconstruct(pop.inventory_movements, as_of)
    open_by_product = dm.on_order_by_product(pop, as_of)
    params = {(p.product_id, p.location_id): p for p in pop.replenishment_params}
    sup_by_id = {s.supplier_id: s for s in pop.suppliers}
    end = dataset_end(pop.sales, pop.inventory_movements, pop.receipts)
    evaluated, warnings, created = [], [], 0
    for (p, l) in pairs:
        prod = pop.product(p)
        st = stocks.get((p, l))
        oo = open_by_product.get(p, 0) if dm.allocation_location(pop, p) == l else 0
        bo = sum(b.quantity for b in pop.backorders if (b.product_id, b.location_id) == (p, l) and b.opened_at <= as_of
                 and (b.closed_at is None or b.closed_at > as_of))
        supplier_id = dm.supplier_of(pop, p)
        param = params.get((p, l))
        if param is not None:
            rop, target, source = param.reorder_point, param.target_position, "params"
        else:
            sup = sup_by_id.get(supplier_id)
            if sup is None:
                warnings.append(warning("NOT_EVALUATED_NO_SUPPLIER", "no parameters and no supplier to size the lead time",
                                        f"replenishment[{p}:{l}]"))
                continue
            lead = effective_lead_days(as_of.astimezone(timezone.utc).date(), sup.quoted_lead_days,
                                       pop.calendar_closures, sup.calendar_id)
            fc = _domain(lambda: forecast_demand(pop.sales, pop.promotions, p, l, as_of, max(lead, 7), end),
                         "input.as_of")
            series = fc.points[fc.selected_model]
            rop, target = derived_parameters(lead_time_demand(series, lead), safety_stock(z, fc.sigma_variance, lead),
                                             sum(series[:7]))
            source = "forecast"
        r = replenish(st.on_hand if st else 0, oo, bo, rop, target, prod.minimum_order_quantity, prod.pack_size)
        draft_id = f"do-{_short(iso_z(as_of), inp.scenario_id or '-', p, l)}"
        row = {"product_id": p, "location_id": l, "supplier_id": supplier_id, "inventory_position": r.position,
               "reorder_point": r.reorder_point, "target_position": r.target_position, "triggered": r.triggered,
               "raw_order": r.raw_order, "minimum_order_quantity": prod.minimum_order_quantity,
               "order_after_moq": r.order_after_moq, "pack_size": prod.pack_size, "order_quantity": r.order_quantity,
               "parameter_source": source, "draft_order_id": None}
        if r.triggered and r.order_quantity > 0:
            conn.execute(
                "INSERT INTO draft_orders (draft_order_id, as_of, scenario_id, product_id, location_id, supplier_id, "
                "inventory_position, reorder_point, target_position, raw_order, minimum_order_quantity, order_after_moq, "
                "pack_size, order_quantity, parameter_source, status, dataset_version) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s) "
                "ON CONFLICT (draft_order_id) DO UPDATE SET supplier_id = EXCLUDED.supplier_id, "
                "inventory_position = EXCLUDED.inventory_position, reorder_point = EXCLUDED.reorder_point, "
                "target_position = EXCLUDED.target_position, raw_order = EXCLUDED.raw_order, "
                "minimum_order_quantity = EXCLUDED.minimum_order_quantity, order_after_moq = EXCLUDED.order_after_moq, "
                "pack_size = EXCLUDED.pack_size, order_quantity = EXCLUDED.order_quantity, "
                "parameter_source = EXCLUDED.parameter_source, dataset_version = EXCLUDED.dataset_version",
                (draft_id, as_of, inp.scenario_id, p, l, supplier_id, r.position, r.reorder_point, r.target_position,
                 r.raw_order, prod.minimum_order_quantity, r.order_after_moq, prod.pack_size, r.order_quantity, source,
                 db.dataset_version(conn)))
            row["draft_order_id"] = draft_id
            created += 1
        else:  # no longer triggered: a draft left by an earlier run of the same as-of is withdrawn
            conn.execute("DELETE FROM draft_orders WHERE draft_order_id = %s", (draft_id,))
        evaluated.append(row)
    return Outcome("calculated", {"as_of": iso_z(as_of), "scenario_id": inp.scenario_id, "evaluated": evaluated,
                                  "drafts": created, "note": "draft recommendations only; never a purchase order"},
                   warnings=warnings, audit=Audit("draft_order", iso_z(as_of) or "", "calculate-replenishment"))


# --- C06 simulate-arrival ---------------------------------------------------------------------------------------

def simulate_arrival(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    at = parse_ts(inp.at)
    line = conn.execute("SELECT * FROM purchase_order_lines WHERE po_line_id = %s FOR UPDATE", (inp.po_line_id,)).fetchone()
    if line is None:
        raise _not_found("input.po_line_id", "PO_LINE_UNKNOWN", "purchase order line")
    order = conn.execute("SELECT * FROM purchase_orders WHERE purchase_order_id = %s", (line["purchase_order_id"],)).fetchone()
    _need(conn, "locations", "location_id", inp.location_id, "input.location_id", "location")
    if order["status"] != "confirmed":
        raise _invalid("ORDER_NOT_RECEIVABLE", f"the order is {order['status']}; only a confirmed order is received",
                       "input.po_line_id")
    sup = conn.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (order["supplier_id"],)).fetchone()
    if at < order["ordered_at"]:
        raise _invalid(RECEIPT_BEFORE_ORDER, "a receipt cannot be dated before its order", "input.at")
    closures = db.load_population(conn).calendar_closures
    lead = effective_lead_days(order["ordered_at"].astimezone(timezone.utc).date(), sup["quoted_lead_days"], closures,
                               sup["calendar_id"])
    earliest = order["ordered_at"] + timedelta(days=lead)
    if at < earliest:
        raise _invalid(RECEIPT_BEFORE_LEAD_TIME, "no receipt before the lead time on the supplier calendar", "input.at",
                       {"earliest": iso_z(earliest), "quoted_lead_days": sup["quoted_lead_days"],
                        "effective_lead_days": lead})
    got = conn.execute("SELECT COALESCE(sum(received_quantity), 0) AS n FROM receipts WHERE po_line_id = %s",
                       (inp.po_line_id,)).fetchone()["n"]
    remaining = line["ordered_quantity"] - got
    qty = inp.quantity if inp.quantity is not None else remaining
    if remaining <= 0 or qty > remaining:
        raise _invalid(RECEIPT_EXCEEDS_ORDERED, "the receipt would take received above ordered", "input.quantity",
                       {"ordered": line["ordered_quantity"], "received": int(got), "remaining": int(remaining)})
    receipt_id = inp.receipt_id or f"rcpt-{uuid.uuid4().hex[:12]}"
    conn.execute("INSERT INTO receipts (receipt_id, po_line_id, location_id, received_quantity, received_at) "
                 "VALUES (%s, %s, %s, %s, %s)", (receipt_id, inp.po_line_id, inp.location_id, qty, at))
    conn.execute("INSERT INTO inventory_movements (movement_id, product_id, location_id, quantity_delta, event_at, "
                 "movement_type) VALUES (%s, %s, %s, %s, %s, 'receipt')",
                 (f"mv-{receipt_id}", line["product_id"], inp.location_id, qty, at))
    left = remaining - qty
    return Outcome("received", {"receipt_id": receipt_id, "movement_id": f"mv-{receipt_id}", "po_line_id": inp.po_line_id,
                                "received_quantity": qty, "received_total": int(got) + qty, "remaining": int(left),
                                "line_status": "open" if left > 0 else "complete", "earliest_receipt": iso_z(earliest)},
                   audit=Audit("receipt", receipt_id, "simulate-arrival"))


# --- C07 record-unmet-demand ------------------------------------------------------------------------------------

def record_unmet_demand(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    sc = _need(conn, "policy_scenarios", "scenario_id", inp.scenario_id, "input.scenario_id", "scenario")
    _check_scope(conn, inp.product_id, inp.location_id)
    if inp.policy is not None and inp.policy != sc["unmet_policy"]:
        raise _invalid("POLICY_MISMATCH", f"scenario {inp.scenario_id} uses the {sc['unmet_policy']} policy",
                       "input.policy", {"scenario_policy": sc["unmet_policy"]})
    at = parse_ts(inp.occurred_at) if inp.occurred_at else datetime.now(timezone.utc)
    ref = inp.demand_ref or f"ud-{_short(inp.scenario_id, inp.product_id, inp.location_id, iso_z(at), inp.quantity)}"
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"unmet:{ref}",))
    other = "lost_sales" if sc["unmet_policy"] == "backlog" else "backorders"
    if conn.execute(f"SELECT 1 FROM {other} WHERE demand_ref = %s", (ref,)).fetchone():  # constants
        raise _conflict(UNMET_POLICY_CONFLICT, "this demand is already recorded as the other kind: lost sale XOR backlog",
                        "input.demand_ref")
    if sc["unmet_policy"] == "backlog":
        row_id = f"bo-{_short(ref)}"
        conn.execute("INSERT INTO backorders (backorder_id, product_id, location_id, quantity, opened_at, scenario_id, "
                     "demand_ref) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (row_id, inp.product_id, inp.location_id, inp.quantity, at, inp.scenario_id, ref))
        kind = "backorder"
    else:
        row_id = f"ls-{_short(ref)}"
        conn.execute("INSERT INTO lost_sales (lost_sale_id, product_id, location_id, quantity, occurred_at, scenario_id, "
                     "demand_ref) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (row_id, inp.product_id, inp.location_id, inp.quantity, at, inp.scenario_id, ref))
        kind = "lost_sale"
    return Outcome("recorded", {"kind": kind, "id": row_id, "demand_ref": ref, "policy": sc["unmet_policy"],
                                "quantity": inp.quantity, "occurred_at": iso_z(at)},
                   audit=Audit(kind, row_id, "record-unmet-demand"))


# --- C08 compare-policies (read-only simulation) ---------------------------------------------------------------

def compare_policies_command(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    if inp.lead_high < inp.lead_low:
        raise _invalid("LEAD_RANGE_INVALID", "lead_high must be at least lead_low", "input.lead_high")
    pop = db.load_population(conn)
    by_id = {s.scenario_id: s for s in pop.policy_scenarios}
    for i, sid in enumerate(inp.scenario_ids):
        if sid not in by_id:
            raise _not_found(f"input.scenario_ids[{i}]", "SCENARIO_UNKNOWN", "scenario")
    prod = pop.product(inp.product_id)
    if prod is None:
        raise _not_found("input.product_id", "PRODUCT_UNKNOWN", "product")
    param = next((p for p in pop.replenishment_params if (p.product_id, p.location_id) == (inp.product_id, inp.location_id)),
                 None)
    if param is None:
        raise _invalid("NO_PARAMETERS", "the pair has no replenishment parameters to simulate", "input.product_id")
    res = _domain(lambda: compare_policies([by_id[s] for s in inp.scenario_ids], inp.days, inp.mean_demand, inp.lead_low,
                                           inp.lead_high, param.reorder_point, param.target_position,
                                           prod.minimum_order_quantity, prod.pack_size, inp.initial_stock),
                  "input.scenario_ids")
    out = {sid: [{"replication": i, "fill_rate": d6(r["fill_rate"]), "requested": r["requested"],
                  "fulfilled": r["fulfilled"], "stockout_days": r["stockout_days"]} for i, r in enumerate(rs)]
           for sid, rs in res["results"].items()}
    return Outcome("compared", {"seed": res["seed"], "replications": res["replications"],
                                "common_random_numbers": True, "results": out},
                   audit=Audit("policy_comparison", ",".join(inp.scenario_ids), "compare-policies"))


# --- C09 review-supplier ----------------------------------------------------------------------------------------

def review_supplier(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    as_of = parse_ts(inp.as_of)
    _need(conn, "suppliers", "supplier_id", inp.supplier_id, "input.supplier_id", "supplier")
    pop = db.load_population(conn)
    res = suppliers.on_time_rate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers,
                                 pop.calendar_closures, as_of, inp.supplier_id)
    res.update(supplier_id=inp.supplier_id, as_of=iso_z(as_of),
               basis="receipts dated at or before as_of; partial receipts never complete a line")
    return Outcome("reviewed", res, audit=Audit("supplier", inp.supplier_id, "review-supplier"))


# --- C10 export-buying-plan -------------------------------------------------------------------------------------

def neutralise(cell: Any) -> Any:
    """Formula-injection guard: a text cell that a spreadsheet would read as a formula gets a leading apostrophe."""
    if isinstance(cell, str) and cell and (cell[0] in "=+-@\t\r" or cell.lstrip()[:1] in ("=", "+", "-", "@")):
        return "'" + cell
    return cell


PLAN_COLUMNS = ("draft_order_id", "as_of", "scenario_id", "product_id", "location_id", "supplier_id",
                "inventory_position", "reorder_point", "target_position", "raw_order", "minimum_order_quantity",
                "order_after_moq", "pack_size", "order_quantity", "parameter_source", "status")


def export_buying_plan(conn: Conn, req: Any, actor: Actor) -> Outcome:
    inp = req.input
    where, params = ["status = 'draft'"], []
    filters: dict[str, Any] = {}
    for col, val in (("scenario_id", inp.scenario_id), ("product_id", inp.product_id), ("supplier_id", inp.supplier_id)):
        if val is not None:
            where.append(f"{col} = %s")
            params.append(val)
            filters[col] = val
    if inp.as_of is not None:
        where.append("as_of = %s")
        params.append(parse_ts(inp.as_of))
        filters["as_of"] = iso_z(parse_ts(inp.as_of))
    if inp.draft_order_ids is not None:
        where.append("draft_order_id = ANY(%s)")
        params.append(sorted(inp.draft_order_ids))
        filters["draft_order_ids"] = sorted(inp.draft_order_ids)
    rows = conn.execute(f"SELECT * FROM draft_orders WHERE {' AND '.join(where)} ORDER BY as_of, product_id, location_id, "
                        "draft_order_id", params).fetchall()  # column names are constants above
    dv = db.dataset_version(conn)
    out = io.StringIO()
    scen = ",".join(sorted({r["scenario_id"] or "-" for r in rows})) or (inp.scenario_id or "-")
    asofs = ",".join(sorted({iso_z(r["as_of"]) or "" for r in rows})) or (filters.get("as_of") or "-")
    for line in (f"# contract_version: {CONTRACT_VERSION}", f"# dataset_version: {dv}", f"# as_of: {asofs}",
                 f"# scenario: {scen}", f"# filters: {json.dumps(filters, sort_keys=True, separators=(',', ':'))}",
                 f"# rows: {len(rows)}", "# status: DRAFT RECOMMENDATIONS ONLY - not purchase orders, no supplier commitment"):
        out.write(line.replace("\r", " ").replace("\n", " ") + "\n")
    w = csv.writer(out, lineterminator="\n")
    w.writerow(PLAN_COLUMNS)
    for r in rows:
        w.writerow([neutralise(db.jsonable(r[c])) for c in PLAN_COLUMNS])
    text = out.getvalue()
    return Outcome("exported", {"csv": text, "row_count": len(rows), "filters": filters, "dataset_version": dv,
                                "contract_version": CONTRACT_VERSION, "draft_order_ids": [r["draft_order_id"] for r in rows],
                                "sha256": sha256_hex(text)},
                   warnings=[] if rows else [warning("NO_DRAFTS", "no draft orders match the filters", "input")],
                   audit=Audit("buying_plan", sha256_hex(text)[:16], "export-buying-plan"))
