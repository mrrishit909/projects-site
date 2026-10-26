"""Commands C01..C04 (docs/api-contract.md, docs/contracts.md D-03, D-04, D-06).

Every command runs in ONE transaction: its effects, its audit event and its stored
idempotency result commit together or not at all. Input is validated (pydantic, then
domain rules) before the first write. The same ``idempotency_key`` with the same payload
returns the stored response; with a different payload it is a 409.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable

import psycopg
from psycopg.types.json import Jsonb
from revenue_atlas import DomainError, run_pipeline
from revenue_atlas.allocation import FreightAllocation, allocate_discounts, allocate_freight
from revenue_atlas.contract import ELIGIBLE_ORDER_STATUSES
from revenue_atlas.costing import resolve_cost_version
from revenue_atlas.ingest import ENTITIES, validate_batch
from revenue_atlas.fx import rate_for
from revenue_atlas.money import ZERO
from revenue_atlas.models import (CostVersion, Discount, ExchangeRate, OrderLine, Return, Shipment,
                                  ShipmentLine)
from revenue_atlas.returns import expected_credit, validate_return

from data.seed import canonical_json, insert_rows, row_from_record, sha256_hex

from . import db
from .errors import ApiError, detail, from_domain
from .schemas import Envelope, IngestRequest, ReturnRequest, ShipmentRequest

MAX_BATCH_ROWS = 20_000
Conn = psycopg.Connection[db.Row]


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
    version: int
    warnings: list[dict[str, Any]] = field(default_factory=list)
    audit: Audit | None = None


Handler = Callable[[Conn, Any, Actor], Outcome]

#: database constraint (migration 0003) -> (reason code, path) for a 422 (D-08).
_INVARIANT_CODES = {
    "shipment_lines_shipped_le_ordered": ("SHIPPED_EXCEEDS_ORDERED", "input.batch.shipment_lines"),
    "shipment_lines_order_match": ("SHIPMENT_LINE_ORDER_MISMATCH", "input.batch.shipment_lines"),
}


def _warning(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path}


def _not_found(path: str, rule_id: str, what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found", [detail(path, rule_id, f"{what} not found")])


# --- idempotent execution ---------------------------------------------------------

def _payload_hash(name: str, req: Envelope) -> str:
    """sha256 over the canonical command name + input (request_id/key excluded)."""
    try:
        text = canonical_json({"command": name, "input": req.input.model_dump()})  # type: ignore[attr-defined]
    except ValueError:  # NaN / Infinity are not JSON
        raise ApiError(422, "VALIDATION_FAILED", "input contains a non-finite number",
                       [detail("input", "JSON_NON_FINITE", "NaN and Infinity are not allowed")]) from None
    if "\\u0000" in text:
        raise ApiError(422, "VALIDATION_FAILED", "input contains a NUL character",
                       [detail("input", "NUL_CHARACTER", "NUL characters cannot be stored")])
    return sha256_hex(text)


def execute(name: str, req: Envelope, actor: Actor, handler: Handler) -> tuple[dict[str, Any], bool]:
    """Run ``handler`` once per idempotency key. Returns ``(response body, replayed)``."""
    payload_hash = _payload_hash(name, req)
    with db.transaction() as conn:
        # Serialise concurrent requests carrying the same key.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (req.idempotency_key,))
        prior = conn.execute("SELECT payload_hash, result FROM command_results "
                             "WHERE idempotency_key = %s", (req.idempotency_key,)).fetchone()
        if prior is not None:
            if prior["payload_hash"] != payload_hash:
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED",
                               "this idempotency_key was used with a different payload",
                               [detail("idempotency_key", "IDEMPOTENCY_PAYLOAD_MISMATCH",
                                       "same key, different payload_hash")])
            return prior["result"], True
        try:
            out = handler(conn, req, actor)
        except psycopg.errors.UniqueViolation as exc:
            # P01-TEST-01 / D-04: the PRIMARY KEY on freight_allocations.shipment_line_id.
            if exc.diag.constraint_name == "freight_allocations_pkey":
                raise ApiError(409, "FREIGHT_ALREADY_ALLOCATED",
                               "freight for this shipment line is already allocated",
                               [detail("input.shipment_id", "FREIGHT_ALREADY_ALLOCATED",
                                       "a shipment line may be allocated once")]) from None
            raise
        except psycopg.errors.CheckViolation as exc:
            # D-08: the 0003 triggers (R-01 shipped > ordered, R-06 line of another order) guard rows that
            # reach the database through a later batch; the transaction is rolled back, nothing is stored.
            name = exc.diag.constraint_name
            if name in _INVARIANT_CODES:
                code, path = _INVARIANT_CODES[name]
                raise ApiError(422, "VALIDATION_FAILED", exc.diag.message_primary or code,
                               [detail(path, code, exc.diag.message_primary or code)]) from None
            raise
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        if out.audit is not None:
            a = out.audit
            conn.execute(
                "INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id, "
                "before_version, after_version, reason, request_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (f"evt-{uuid.uuid4().hex[:16]}", a.entity_type, a.entity_id, a.action,
                 actor.actor_id, a.before_version, a.after_version, a.reason, req.request_id))
        body = {"command_id": command_id, "status": out.status, "result": out.result,
                "warnings": out.warnings, "version": out.version}
        conn.execute("INSERT INTO command_results (idempotency_key, payload_hash, command_id, "
                     "status, result) VALUES (%s, %s, %s, %s, %s)",
                     (req.idempotency_key, payload_hash, command_id, out.status, Jsonb(body)))
        return body, False


# --- C01 ingest-sales -------------------------------------------------------------

def _check_batch_shape(batch: dict[str, Any]) -> None:
    """Reject structurally invalid batches before any write (rows are validated by the domain)."""
    problems = []
    total = 0
    for ent in ENTITIES:
        rows = batch.get(ent)
        if rows is None:
            continue
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            problems.append(detail(f"input.batch.{ent}", "MALFORMED_RECORD",
                                   f"{ent} must be a list of objects"))
        else:
            total += len(rows)
    if "contract" in batch and not isinstance(batch["contract"], str):
        problems.append(detail("input.batch.contract", "CONTRACT_MISMATCH", "contract must be a string"))
    if total > MAX_BATCH_ROWS:
        problems.append(detail("input.batch", "BATCH_TOO_LARGE", f"at most {MAX_BATCH_ROWS} rows"))
    if problems:
        raise ApiError(422, "VALIDATION_FAILED", "batch is structurally invalid", problems)


def ingest_sales(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """C01: validate with the domain, write accepted rows, keep rejected raw rows (D-06)."""
    batch: dict[str, Any] = req.input.batch
    _check_batch_shape(batch)
    try:
        ing = validate_batch(batch)
    except DomainError as err:
        raise from_domain(err, "input.batch.contract") from None
    key_hash = sha256_hex(canonical_json(batch))
    batch_id = f"batch-{key_hash[:16]}-{uuid.uuid4().hex[:6]}"
    status = "partial" if ing.rejected else "accepted"
    conn.execute("INSERT INTO raw_batches (batch_id, idempotency_key, payload_hash, payload, status) "
                 "VALUES (%s, %s, %s, %s, %s)",
                 (batch_id, req.idempotency_key, key_hash, Jsonb(batch), status))
    for rej in ing.rejected:
        conn.execute("INSERT INTO rejected_records (entity, id, reason_code, raw_row, batch_id) "
                     "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (rej.entity, rej.id, rej.reason_code, Jsonb(rej.raw_row), batch_id))
    inserted = insert_rows(conn, {ent: [row_from_record(r) for r in recs]
                                  for ent, recs in ing.accepted.items()})
    if inserted.get("exchange_rates"):
        _refresh_fx_quarantine(conn)  # a new rate may make quarantined lines resolvable (D-02)
    counts = {ent: {**c, "inserted": inserted.get(ent, 0)} for ent, c in ing.counts.items()}
    warnings = [_warning(r.reason_code, f"{r.entity} {r.id!r} rejected; raw row preserved",
                         f"{r.entity}[{r.id}]") for r in ing.rejected]
    result = {"batch_id": batch_id, "counts": counts,
              "rejected_records": [{"entity": r.entity, "id": r.id, "reason_code": r.reason_code}
                                   for r in ing.rejected]}
    return Outcome(status, result, 1, warnings,
                   Audit("raw_batch", batch_id, "ingest-sales",
                         reason=f"{sum(inserted.values())} rows inserted, {len(ing.rejected)} rejected"))


# --- C02 resolve-historical-cost --------------------------------------------------

def _line_error(conn: Conn, ln: Any, shipped_at: datetime, order_currency: str,
                shipment_currency: str, versions: list[CostVersion]) -> DomainError | None:
    """The reason the pipeline would quarantine this line, or None. Same order as the pipeline:
    FX for the order and shipment currency on the shipped UTC date first, then the cost version."""
    day = shipped_at.astimezone(timezone.utc).date().isoformat()
    cur = sorted({order_currency, shipment_currency})
    rates = [ExchangeRate(r["rate_id"], r["currency"], r["reporting_currency"],
                          r["rate_date"].isoformat(), r["rate"])
             for r in conn.execute("SELECT * FROM exchange_rates WHERE currency = ANY(%s) AND rate_date = %s",
                                   (cur, day)).fetchall()]
    try:
        for c in (order_currency, shipment_currency):
            rate_for(c, day, rates)
        resolve_cost_version(ln["product_id"], shipped_at, versions)
    except DomainError as err:
        return err
    return None


def _put_quarantine(conn: Conn, sid: str, shipment_id: str, ln: Any, err: DomainError) -> bool:
    raw = {"shipment_line_id": sid, "shipment_id": shipment_id, "line_id": ln["line_id"],
           "product_id": ln["product_id"], "shipped_quantity": ln["shipped_quantity"],
           "details": err.details}
    cur = conn.execute(
        "INSERT INTO quarantined_records (entity, id, reason_code, raw_row) "
        "VALUES ('shipment_lines', %s, %s, %s) ON CONFLICT (entity, id) DO UPDATE "
        "SET reason_code = EXCLUDED.reason_code, raw_row = EXCLUDED.raw_row "
        "WHERE (quarantined_records.reason_code, quarantined_records.raw_row) "
        "IS DISTINCT FROM (EXCLUDED.reason_code, EXCLUDED.raw_row)",
        (sid, err.code, Jsonb(raw)))
    return cur.rowcount > 0


def _cost_versions(conn: Conn, products: list[str]) -> list[CostVersion]:
    return [CostVersion(r["cost_version_id"], r["product_id"], r["unit_cost"],
                        r["valid_from"].isoformat(),
                        None if r["valid_to"] is None else r["valid_to"].isoformat())
            for r in conn.execute("SELECT * FROM cost_versions WHERE product_id = ANY(%s)",
                                  (products,)).fetchall()]


def _refresh_fx_quarantine(conn: Conn) -> None:
    """After a rate ingest: re-evaluate persisted FX_RATE_MISSING rows; clear the ones that now
    resolve (or replace them with the cost reason the pipeline would report next)."""
    rows = conn.execute(
        "SELECT q.id, sl.line_id, sl.shipped_quantity, sl.shipment_id, ol.product_id, s.shipped_at, "
        "s.currency AS ship_cur, o.currency AS order_cur FROM quarantined_records q "
        "JOIN shipment_lines sl ON sl.shipment_line_id = q.id "
        "JOIN order_lines ol ON ol.line_id = sl.line_id JOIN orders o ON o.order_id = ol.order_id "
        "JOIN shipments s ON s.shipment_id = sl.shipment_id "
        "WHERE q.entity = 'shipment_lines' AND q.reason_code = 'FX_RATE_MISSING' ORDER BY q.id").fetchall()
    for r in rows:
        err = _line_error(conn, r, r["shipped_at"], r["order_cur"], r["ship_cur"],
                          _cost_versions(conn, [r["product_id"]]))
        if err is None:
            conn.execute("DELETE FROM quarantined_records WHERE entity = 'shipment_lines' AND id = %s",
                         (r["id"],))
        elif err.code != "FX_RATE_MISSING":
            _put_quarantine(conn, r["id"], r["shipment_id"], r, err)

def resolve_historical_cost(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """C02: set cost_version_id per line; 0 or >1 versions quarantine the line (D-03)."""
    inp = req.input
    shipment = conn.execute("SELECT shipment_id, shipped_at FROM shipments WHERE shipment_id = %s "
                            "FOR UPDATE", (inp.shipment_id,)).fetchone()
    if shipment is None:
        raise _not_found("input.shipment_id", "SHIPMENT_UNKNOWN", "shipment")
    lines = conn.execute(
        "SELECT sl.shipment_line_id, sl.line_id, sl.shipped_quantity, sl.cost_version_id, sl.version, "
        "ol.product_id, o.currency AS order_cur, s.currency AS ship_cur FROM shipment_lines sl "
        "JOIN order_lines ol ON ol.line_id = sl.line_id JOIN orders o ON o.order_id = ol.order_id "
        "JOIN shipments s ON s.shipment_id = sl.shipment_id "
        "WHERE sl.shipment_id = %s ORDER BY sl.shipment_line_id FOR UPDATE OF sl",
        (inp.shipment_id,)).fetchall()
    versions = _cost_versions(conn, sorted({ln["product_id"] for ln in lines}))
    outcomes: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    changed = False
    for ln in lines:
        sid = ln["shipment_line_id"]
        # DEFECT-1: the FX rate for the shipped date is evaluated here too, so FX_RATE_MISSING is
        # persisted like the cost quarantines; the pipeline reports the same reason (FX first).
        err = _line_error(conn, ln, shipment["shipped_at"], ln["order_cur"], ln["ship_cur"], versions)
        resolved_now = None
        if ln["cost_version_id"] is None:  # immutable once set (D-03)
            try:
                resolved_now = resolve_cost_version(ln["product_id"], shipment["shipped_at"], versions)
            except DomainError:
                resolved_now = None
            if resolved_now is not None:
                conn.execute("UPDATE shipment_lines SET cost_version_id = %s WHERE shipment_line_id = %s "
                             "AND cost_version_id IS NULL", (resolved_now.cost_version_id, sid))
                changed = True
        if err is not None:
            changed = _put_quarantine(conn, sid, inp.shipment_id, ln, err) or changed
            outcomes.append({"shipment_line_id": sid, "outcome": "quarantined", "reason_code": err.code})
            warnings.append(_warning(err.code, err.message, f"shipment_lines[{sid}]"))
            continue
        cleared = conn.execute("DELETE FROM quarantined_records WHERE entity = 'shipment_lines' AND id = %s",
                               (sid,)).rowcount > 0
        changed = changed or cleared
        if resolved_now is None:
            outcomes.append({"shipment_line_id": sid, "outcome": "unchanged",
                             "cost_version_id": ln["cost_version_id"]})
        else:
            outcomes.append({"shipment_line_id": sid, "outcome": "resolved",
                             "cost_version_id": resolved_now.cost_version_id})
    quarantined = sum(1 for o in outcomes if o["outcome"] == "quarantined")
    counts = {k: sum(1 for o in outcomes if o["outcome"] == k)
              for k in ("resolved", "unchanged", "quarantined")}
    version = max((ln["version"] for ln in lines), default=1)
    audit = (Audit("shipment", inp.shipment_id, "resolve-historical-cost", version, version,
                   f"resolved={counts['resolved']} quarantined={quarantined}") if changed else None)
    return Outcome("partial" if quarantined else "completed",
                   {"shipment_id": inp.shipment_id, "lines": outcomes, "counts": counts},
                   version, warnings, audit)


# --- C03 post-a-partial-return ----------------------------------------------------

def _credit_warning(conn: Conn, line_id: str, qty: int, credit: Decimal) -> list[dict[str, Any]]:
    """Non-blocking: compare the posted credit with qty x (price - discount/shipped) (D-03)."""
    res = run_pipeline(db.load_batch(conn), include_returns=False)
    fact = next((f for f in res.facts if f.shipment_line_id == line_id), None)
    if fact is None or fact.fx_rate != 1 or fact.shipped_quantity == 0:
        return []
    want = expected_credit(fact, qty)
    if want == credit:
        return []
    return [_warning("CREDIT_DIFFERS_FROM_EXPECTED",
                     f"posted credit {credit} differs from the expected {want}",
                     "input.credit_amount")]


def post_partial_return(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """C03: validate against prior returns, append a return, bump the line version (D-06)."""
    inp = req.input
    row = conn.execute("SELECT sl.shipment_line_id, sl.shipment_id, sl.line_id, sl.shipped_quantity, "
                       "sl.cost_version_id, sl.version, ol.order_id FROM shipment_lines sl "
                       "JOIN order_lines ol ON ol.line_id = sl.line_id "
                       "WHERE sl.shipment_line_id = %s FOR UPDATE OF sl",
                       (inp.shipment_line_id,)).fetchone()
    if row is None:
        raise _not_found("input.shipment_line_id", "SHIPMENT_LINE_UNKNOWN", "shipment line")
    if row["version"] != inp.expected_version:
        raise ApiError(409, "STALE_VERSION",
                       f"shipment line is at version {row['version']}, not {inp.expected_version}",
                       [detail("input.expected_version", "STALE_VERSION",
                               f"current version is {row['version']}")])
    credit = Decimal(inp.credit_amount)
    prior = [Return(r["return_id"], r["shipment_line_id"], r["returned_quantity"],
                    r["credit_amount"], r["credit_date"].isoformat())
             for r in conn.execute("SELECT * FROM returns WHERE shipment_line_id = %s "
                                   "ORDER BY credit_date, return_id", (inp.shipment_line_id,)).fetchall()]
    line = ShipmentLine(row["shipment_line_id"], row["shipment_id"], row["line_id"],
                        row["shipped_quantity"], row["cost_version_id"])
    try:
        validate_return(line, prior, inp.returned_quantity, credit)
    except DomainError as err:
        path = "input.credit_amount" if err.code == "CREDIT_SIGN_REVERSED" else "input.returned_quantity"
        raise from_domain(err, path) from None
    warnings = _credit_warning(conn, inp.shipment_line_id, inp.returned_quantity, credit)
    return_id = f"ret-{uuid.uuid4().hex[:12]}"
    conn.execute("INSERT INTO returns (return_id, shipment_line_id, returned_quantity, credit_amount, "
                 "credit_date) VALUES (%s, %s, %s, %s, %s)",
                 (return_id, inp.shipment_line_id, inp.returned_quantity, credit,
                  date.fromisoformat(inp.credit_date)))
    new_version = row["version"] + 1
    conn.execute("UPDATE shipment_lines SET version = %s WHERE shipment_line_id = %s",
                 (new_version, inp.shipment_line_id))
    conn.execute("UPDATE orders SET status = 'partially_returned' "
                 "WHERE order_id = %s AND status = 'shipped'", (row["order_id"],))
    remaining = row["shipped_quantity"] - sum(r.returned_quantity for r in prior) - inp.returned_quantity
    result = {"return_id": return_id, "shipment_line_id": inp.shipment_line_id,
              "returned_quantity": inp.returned_quantity, "credit_amount": db.money(credit),
              "credit_date": inp.credit_date, "remaining_quantity": remaining}
    return Outcome("posted", result, new_version, warnings,
                   Audit("shipment_line", inp.shipment_line_id, "post-a-partial-return",
                         row["version"], new_version, inp.reason))


# --- C04 allocate-freight ---------------------------------------------------------

def _already_allocated(conn: Conn, line_ids: list[str]) -> list[str]:
    """Shipment lines that already hold a freight allocation (pre-check before the key fires)."""
    return [r["shipment_line_id"] for r in conn.execute(
        "SELECT shipment_line_id FROM freight_allocations WHERE shipment_line_id = ANY(%s) "
        "ORDER BY shipment_line_id", (line_ids,)).fetchall()]


def _stored_freight(conn: Conn, line_ids: list[str]) -> dict[str, Decimal]:
    return {r["shipment_line_id"]: r["amount"] for r in conn.execute(
        "SELECT shipment_line_id, amount FROM freight_allocations WHERE shipment_line_id = ANY(%s)",
        (line_ids,)).fetchall()}


def allocate_freight_command(conn: Conn, req: Any, actor: Actor) -> Outcome:
    """C04: allocate shipping_cost over the shipment's non-quarantined lines by gross-sales weight (D-04, D-08).

    R-08: a line the pipeline would quarantine at this moment (FX or cost version missing/ambiguous) or whose
    order is not eligible carries no freight, exactly as in ``run_pipeline``. R-02: the discount split is
    recomputed for every order line touched, over all of its shipment lines, and upserted.
    Running C04 again for an already allocated shipment is a 409 when it would change nothing
    (P01-TEST-01); when the eligible set changed (a line was un-quarantined or quarantined since) it re-spreads:
    stale rows are deleted and the others upserted, all in this one transaction (D-08).
    """
    inp = req.input
    shp = conn.execute("SELECT * FROM shipments WHERE shipment_id = %s FOR UPDATE",
                       (inp.shipment_id,)).fetchone()
    if shp is None:
        raise _not_found("input.shipment_id", "SHIPMENT_UNKNOWN", "shipment")
    lines = conn.execute(
        "SELECT sl.*, ol.unit_price, ol.quantity AS ordered_quantity, ol.product_id, "
        "o.currency AS order_cur, o.status AS order_status FROM shipment_lines sl "
        "JOIN order_lines ol ON ol.line_id = sl.line_id JOIN orders o ON o.order_id = ol.order_id "
        "WHERE sl.shipment_id = %s ORDER BY sl.shipment_line_id", (inp.shipment_id,)).fetchall()
    ids = [ln["shipment_line_id"] for ln in lines]
    existing = _already_allocated(conn, ids)
    versions = _cost_versions(conn, sorted({ln["product_id"] for ln in lines}))
    skipped: dict[str, str] = {}
    eligible = []
    for ln in lines:
        if ln["order_status"] not in ELIGIBLE_ORDER_STATUSES:
            skipped[ln["shipment_line_id"]] = "ORDER_STATUS_EXCLUDED"
            continue
        err = _line_error(conn, ln, shp["shipped_at"], ln["order_cur"], shp["currency"], versions)
        if err is not None:
            skipped[ln["shipment_line_id"]] = err.code
            continue
        eligible.append(ln)
    domain_shipment = Shipment(shp["shipment_id"], shp["order_id"], shp["shipped_at"],
                               shp["shipping_cost"], shp["currency"])
    domain_lines = [ShipmentLine(ln["shipment_line_id"], ln["shipment_id"], ln["line_id"],
                                 ln["shipped_quantity"], ln["cost_version_id"]) for ln in eligible]
    gross = {ln["shipment_line_id"]: ln["shipped_quantity"] * ln["unit_price"] for ln in eligible}
    if eligible:
        fa = allocate_freight(domain_shipment, domain_lines, gross)
    else:  # nothing in the population carries this shipment's freight; the pipeline ignores the shipment too
        fa = FreightAllocation({}, ZERO, False)
    if not fa.unallocated and fa.residual != 0:
        raise ApiError(422, "VALIDATION_FAILED", "allocation residual is not 0.00",
                       [detail("input.shipment_id", "ALLOCATION_RESIDUAL_NONZERO", str(fa.residual))])
    respread = False
    if existing:
        stored = _stored_freight(conn, ids)
        if stored == fa.allocations:
            raise ApiError(409, "FREIGHT_ALREADY_ALLOCATED",
                           "freight for this shipment is already allocated",
                           [detail("input.shipment_id", "FREIGHT_ALREADY_ALLOCATED",
                                   f"already allocated: {', '.join(existing)}")])
        respread = True
        stale = [sid for sid in stored if sid not in fa.allocations]
        if stale:
            conn.execute("DELETE FROM freight_allocations WHERE shipment_line_id = ANY(%s)", (stale,))
        for sid, amount in sorted(fa.allocations.items()):
            conn.execute("INSERT INTO freight_allocations (shipment_line_id, shipment_id, amount) "
                         "VALUES (%s, %s, %s) ON CONFLICT (shipment_line_id) DO UPDATE "
                         "SET amount = EXCLUDED.amount, allocated_at = now()", (sid, inp.shipment_id, amount))
    else:
        for sid, amount in sorted(fa.allocations.items()):
            # No ON CONFLICT: the PRIMARY KEY is the double-allocation guard (P01-TEST-01).
            conn.execute("INSERT INTO freight_allocations (shipment_line_id, shipment_id, amount) "
                         "VALUES (%s, %s, %s)", (sid, inp.shipment_id, amount))
    discounts, resplit = _allocate_discounts(conn, inp.shipment_id, set(ids))
    result = {"shipment_id": inp.shipment_id,
              "allocations": {k: db.money(v) for k, v in sorted(fa.allocations.items())},
              "discount_allocations": {k: db.money(v) for k, v in sorted(discounts.items())},
              "allocation_residual": db.money(fa.residual if not fa.unallocated else Decimal(0)),
              "unallocated_freight": db.money(fa.residual) if fa.unallocated else "0.00",
              "skipped_lines": dict(sorted(skipped.items())),
              "discount_resplit_on_other_shipments": {k: db.money(v) for k, v in sorted(resplit.items())}}
    warnings = ([_warning("FREIGHT_UNALLOCATED", "shipment has no weight; freight stays on the "
                          "unallocated row and still counts in contribution (D-04)",
                          f"shipments[{inp.shipment_id}]")] if fa.unallocated else [])
    warnings += [_warning("FREIGHT_LINE_SKIPPED", f"{sid} carries no freight: {code} (D-08)",
                          f"shipment_lines[{sid}]") for sid, code in sorted(skipped.items())]
    if respread:
        warnings.append(_warning("FREIGHT_RESPREAD", "freight was re-spread over the lines that are "
                                 "not quarantined now (D-08)", f"shipments[{inp.shipment_id}]"))
    version = max((ln["version"] for ln in lines), default=1)
    return Outcome("reallocated" if respread else "allocated", result, version, warnings,
                   Audit("shipment", inp.shipment_id, "allocate-freight", version, version,
                         f"{len(fa.allocations)} lines allocated" + (", re-spread" if respread else "")))


def _allocate_discounts(conn: Conn, shipment_id: str,
                        line_ids: set[str]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Persist the discount split (D-04, D-08 R-02) of every order line this shipment touches.

    The split is recomputed over ALL shipment lines that exist for the order line and upserted, so the stored
    rows always equal the contract split: sum = round(discount x shipped / ordered, 2). Returns the rows of
    this shipment's lines and the rows of OTHER shipments' lines whose amount changed.
    """
    olines = conn.execute(
        "SELECT * FROM order_lines WHERE line_id IN (SELECT line_id FROM shipment_lines "
        "WHERE shipment_id = %s) ORDER BY line_id FOR NO KEY UPDATE", (shipment_id,)).fetchall()
    if not olines:
        return {}, {}
    keys = [o["line_id"] for o in olines]
    sls = [ShipmentLine(r["shipment_line_id"], r["shipment_id"], r["line_id"], r["shipped_quantity"])
           for r in conn.execute("SELECT * FROM shipment_lines WHERE line_id = ANY(%s)", (keys,)).fetchall()]
    discs = [Discount(r["discount_id"], r["line_id"], r["discount_amount"], r["reason_code"],
                      r["approved_by"])
             for r in conn.execute("SELECT * FROM discounts WHERE line_id = ANY(%s)", (keys,)).fetchall()]
    ols = [OrderLine(o["line_id"], o["order_id"], o["product_id"], o["quantity"], o["unit_price"])
           for o in olines]
    alloc = allocate_discounts(ols, discs, sls)
    before = {r["shipment_line_id"]: r["amount"] for r in conn.execute(
        "SELECT shipment_line_id, amount FROM discount_allocations WHERE shipment_line_id = ANY(%s)",
        (sorted(alloc),)).fetchall()}
    by_line = {s.shipment_line_id: s.line_id for s in sls}
    for sid, amount in sorted(alloc.items()):
        conn.execute("INSERT INTO discount_allocations (shipment_line_id, line_id, amount) "
                     "VALUES (%s, %s, %s) ON CONFLICT (shipment_line_id) DO UPDATE "
                     "SET amount = EXCLUDED.amount, line_id = EXCLUDED.line_id", (sid, by_line[sid], amount))
    mine = {k: v for k, v in alloc.items() if k in line_ids}
    others = {k: v for k, v in alloc.items() if k not in line_ids and k in before and before[k] != v}
    return mine, others


# --- dispatch ---------------------------------------------------------------------

def run_ingest(req: IngestRequest, actor: Actor) -> tuple[dict[str, Any], bool]:
    return execute("ingest-sales", req, actor, ingest_sales)


def run_resolve_cost(req: ShipmentRequest, actor: Actor) -> tuple[dict[str, Any], bool]:
    return execute("resolve-historical-cost", req, actor, resolve_historical_cost)


def run_return(req: ReturnRequest, actor: Actor) -> tuple[dict[str, Any], bool]:
    return execute("post-a-partial-return", req, actor, post_partial_return)


def run_allocate_freight(req: ShipmentRequest, actor: Actor) -> tuple[dict[str, Any], bool]:
    return execute("allocate-freight", req, actor, allocate_freight_command)
