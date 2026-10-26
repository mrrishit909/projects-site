"""Commands C01..C10 (docs/api-contract.md, docs/contracts.md D-01..D-05; backend conventions in README.md).

Every command runs in ONE transaction: its effects, its audit event and its stored idempotency result commit together or
not at all. Input is validated (pydantic, then domain rules) before the first write. The same ``idempotency_key`` with the
same payload (and the same actor) returns the stored response; with a different payload or actor it is a 409.

Lock order (every command, so two commands cannot deadlock on each other):
    1. the idempotency key (advisory lock; C01 then also takes advisory locks on its invoice id and source bytes)
    2. invoice rows, sorted by invoice_id (``FOR UPDATE``)
    3. PO line rows, sorted by po_line_id (``FOR UPDATE``)    (the exception row of C05 is taken after the invoice row)
A deadlock or serialization failure that still happens is rolled back and retried, three attempts in all, then answered
409 CONCURRENT_UPDATE.

Roles (X-Actor-Role): clerk | reviewer | admin.  C01-C05: clerk, reviewer, admin (anyone may import, so the separation
of duties below matters).  C07 approve, C08 reject, C09 export, C10 credit note: reviewer, admin.  Separation of duties (C07): the approver is never
the invoice's creator, and the role must be allowed by the policy version in force at decision time for the invoice total.
C06 correct-extraction is an extension and answers 501 NOT_IMPLEMENTED.
"""
from __future__ import annotations

import dataclasses
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

import psycopg
from invoicebridge.amounts import identity_key, invoice_amounts, normalise_number, validate_invoice
from invoicebridge.book import content_hash, derive, duplicate_groups, effective_policy, role_may_approve
from invoicebridge.contract import RULE_VERSION
from invoicebridge.errors import (BYTES_FIELDS_CONFLICT, CREDIT_EXCEEDS_INVOICE, DUPLICATE_SOURCE_BYTES, INVALID_STATE,
                                  NON_POSITIVE_AMOUNT)
from invoicebridge.ingest import validate_batch
from invoicebridge.models import Approval, Invoice
from invoicebridge.money import s2
from invoicebridge.timeutil import FAR_FUTURE, iso_z, parse_ts
from psycopg.types.json import Jsonb

from data.seed import canonical_json, insert_rejected, sha256_hex

from . import clock, db
from .errors import ApiError, detail
from .schemas import Envelope

Conn = psycopg.Connection[db.Row]
ROLES = frozenset({"clerk", "reviewer", "admin"})
IMPORT_ROLES = ROLES
WORK_ROLES = ROLES
DECISION_ROLES = frozenset({"reviewer", "admin"})


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
    invoice_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Outcome:
    status: str
    result: dict[str, Any]
    version: int = 1
    warnings: list[dict[str, Any]] = field(default_factory=list)
    audit: Audit | list[Audit] | None = None


Handler = Callable[[Conn, Any, Actor], Outcome]


def _warning(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path}


def _err(status: int, code: str, rule_id: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    item = detail(path, rule_id, message)
    if context:
        item["context"] = context
    return ApiError(status, code, message, [item])


def _not_found(path: str, rule_id: str, what: str) -> ApiError:
    return _err(404, "NOT_FOUND", rule_id, f"{what} not found", path)


def _conflict(code: str, message: str, path: str, context: dict[str, Any] | None = None, rule_id: str | None = None) -> ApiError:
    return _err(409, code, rule_id or code, message, path, context)


def _invalid(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    return _err(422, "VALIDATION_FAILED", code, message, path, context)


def _forbidden(code: str, message: str, path: str, context: dict[str, Any] | None = None) -> ApiError:
    return _err(403, code if code in ("SELF_APPROVAL", "SELF_DECISION") else "FORBIDDEN", code, message, path, context)


def _need_role(actor: Actor, allowed: frozenset[str], what: str) -> None:
    if actor.role not in allowed:
        raise _forbidden("ROLE_FORBIDDEN", f"{what} needs the role {' or '.join(sorted(allowed))}", "header.X-Actor-Role")


def _at(value: str | None) -> datetime:
    """An optional client instant (assigned_at, credited_at, exported_at), else the server clock. Decisions and imports never
    take a client instant (``clock.now()`` / a clamp)."""
    return parse_ts(value) if value else clock.now()


# --- idempotent execution ---------------------------------------------------------------------------------------

def _normalise(value: Any, key: str = "") -> Any:
    """An instant (a string under a ``*_at`` key) is hashed as the UTC instant it names, so ``+00:00``, ``Z`` and
    ``+01:00`` spellings of the same instant are the same payload."""
    if isinstance(value, dict):
        return {k: _normalise(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v, key) for v in value]
    if isinstance(value, str) and key.endswith("_at"):
        try:
            return iso_z(parse_ts(value))
        except ValueError:
            return value
    return value


#: Fields a retry legitimately changes (the clock of the retry): not part of the payload hash.
_HASH_EXCLUDE = {"export-payable": {"exported_at"}}


def _payload_hash(name: str, req: Envelope, actor: "Actor | None" = None) -> str:
    """sha256 over the canonical command name + dataset_version + the actor's ROLE + input (request_id and key excluded;
    instants normalised). The dataset_version and the role are part of the payload (D-09, R5-19): the same key from the same
    actor under another role is a different request, so a replay cannot launder a decision into a role that may not take it."""
    body = _normalise(req.input.model_dump())  # type: ignore[attr-defined]
    for k in _HASH_EXCLUDE.get(name, ()):
        body.pop(k, None)
    try:
        text = canonical_json({"command": name, "dataset_version": req.dataset_version,
                               **({} if actor is None else {"actor_role": actor.role}), "input": body})
    except ValueError:
        raise _invalid("JSON_NON_FINITE", "input contains a non-finite number", "input") from None
    if "\\u0000" in text:
        raise _invalid("NUL_CHARACTER", "input contains a NUL character", "input")
    return sha256_hex(text)


#: A deadlock or serialization failure rolls the whole command back; it is retried this many times in all.
MAX_ATTEMPTS = 3
_RETRYABLE = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)


def execute(name: str, req: Envelope, actor: Actor, handler: Handler,
            on_replay: Callable[[Conn, Any, Actor], None] | None = None) -> tuple[dict[str, Any], bool]:
    """Run ``handler`` once per idempotency key. Returns ``(response body, replayed)``. A deadlock is retried
    (``MAX_ATTEMPTS`` attempts in all, short randomised back-off); the last failure is 409 CONCURRENT_UPDATE, never a 500."""
    payload_hash = _payload_hash(name, req, actor)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _execute_once(name, req, actor, handler, payload_hash, on_replay)
        except _RETRYABLE:
            if attempt < MAX_ATTEMPTS:
                time.sleep(random.uniform(0.005, 0.03) * attempt)
    raise _conflict("CONCURRENT_UPDATE", f"the command lost a concurrent update {MAX_ATTEMPTS} times; retry it", "input")


def _check_dataset_version(conn: Conn, req: Envelope) -> None:
    """The request names the dataset it was prepared against; a different current version is 409 STALE_DATASET_VERSION
    and nothing is written. A database with no dataset_versions row has nothing to be stale against."""
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC "
                       "LIMIT 1").fetchone()
    if row is not None and row["dataset_version"] != req.dataset_version:
        raise ApiError(409, "STALE_DATASET_VERSION",
                       f"the request was prepared against dataset {req.dataset_version!r}; the current dataset is "
                       f"{row['dataset_version']!r}",
                       [{**detail("dataset_version", "STALE_DATASET_VERSION",
                                  "re-read the data and retry with the current dataset_version"),
                         "context": {"current": row["dataset_version"], "requested": req.dataset_version}}])


_UNIQUE_CODES = {
    "invoices_pkey": ("DUPLICATE_ID", "an invoice with this id already exists"),
    "credit_notes_pkey": ("CREDIT_ALREADY_APPLIED", "this credit note was already applied"),
    "approvals_pkey": ("DUPLICATE_ID", "an approval with this id already exists"),
    "export_rows_inv_uq": ("ALREADY_EXPORTED", "the invoice is already exported"),
    "exceptions_open_uq": ("ALREADY_EXISTS", "the exception already exists"),
}


def _execute_once(name: str, req: Envelope, actor: Actor, handler: Handler, payload_hash: str,
                  on_replay: Callable[[Conn, Any, Actor], None] | None) -> tuple[dict[str, Any], bool]:
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (req.idempotency_key,))
        prior = conn.execute("SELECT payload_hash, actor_id, result FROM command_results "
                             "WHERE idempotency_key = %s", (req.idempotency_key,)).fetchone()
        if prior is not None:
            if prior["actor_id"] != actor.actor_id:  # bound to the actor
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "this idempotency_key was used by a different actor",
                               [detail("idempotency_key", "IDEMPOTENCY_ACTOR_MISMATCH", "same key, different X-Actor-Id")])
            if prior["payload_hash"] != payload_hash:
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "this idempotency_key was used with a different payload",
                               [detail("idempotency_key", "IDEMPOTENCY_PAYLOAD_MISMATCH",
                                       "same key, different payload (or role)")])
            if on_replay is not None:
                on_replay(conn, req, actor)
            return prior["result"], True
        _check_dataset_version(conn, req)
        try:
            out = handler(conn, req, actor)
        except psycopg.errors.UniqueViolation as exc:
            code, message = _UNIQUE_CODES.get(exc.diag.constraint_name or "",
                                              ("ALREADY_EXISTS", "a row with this key already exists"))
            raise _conflict(code, message, "input") from None
        except psycopg.errors.IntegrityError as exc:  # checks and triggers: append-only, immutable source ...
            raise _conflict("INTEGRITY_RULE", exc.diag.message_primary or "integrity rule violated", "input") from None
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        for a in ([] if out.audit is None else out.audit if isinstance(out.audit, list) else [out.audit]):
            conn.execute(
                "INSERT INTO audit_events (event_id, entity_type, entity_id, invoice_id, action, actor_id, before_version, "
                "after_version, reason, request_id, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (f"evt-{uuid.uuid4().hex[:16]}", a.entity_type, a.entity_id, a.invoice_id, a.action, actor.actor_id,
                 a.before_version, a.after_version, a.reason, req.request_id, Jsonb(a.details)))
        body = {"command_id": command_id, "status": out.status, "result": out.result,
                "warnings": out.warnings, "version": out.version}
        conn.execute("INSERT INTO command_results (idempotency_key, payload_hash, actor_id, command_id, status, result) "
                     "VALUES (%s, %s, %s, %s, %s, %s)",
                     (req.idempotency_key, payload_hash, actor.actor_id, command_id, out.status, Jsonb(body)))
        return body, False


def _refusal(actor: Actor, req: Envelope, action: str, invoice_id: str, rule_id: str, message: str) -> None:
    """Keep a refused decision in the audit trail (its own transaction: the command's is about to roll back)."""
    with db.autocommit() as c:
        c.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, invoice_id, action, actor_id, reason, request_id, "
                  "details) VALUES (%s, 'invoice', %s, %s, %s, %s, %s, %s, %s)",
                  (f"evt-{uuid.uuid4().hex[:16]}", invoice_id, invoice_id, f"{action}-refused", actor.actor_id, message,
                   req.request_id, Jsonb({"rule_id": rule_id, "actor_role": actor.role})))


# --- shared lookups and locks -----------------------------------------------------------------------------------

def _lock_invoices(conn: Conn, ids: list[str]) -> dict[str, db.Row]:
    """Lock order step 2: invoice rows ``FOR UPDATE`` in sorted order; returns the rows that exist."""
    rows = conn.execute("SELECT * FROM invoices WHERE invoice_id = ANY(%s) ORDER BY invoice_id FOR UPDATE",
                        (sorted(set(ids)),)).fetchall()
    return {r["invoice_id"]: r for r in rows}


def _lock_po_lines(conn: Conn, ids: list[str]) -> None:
    """Lock order step 3: PO line rows ``FOR UPDATE`` in sorted order."""
    conn.execute("SELECT po_line_id FROM po_lines WHERE po_line_id = ANY(%s) ORDER BY po_line_id FOR UPDATE",
                 (sorted(set(ids)),)).fetchall()


def _invoice(conn: Conn, invoice_id: str, path: str = "input.invoice_id") -> db.Row:
    row = _lock_invoices(conn, [invoice_id]).get(invoice_id)
    if row is None:
        raise _not_found(path, "INVOICE_UNKNOWN", "invoice")
    return row


def _need_status(inv: db.Row, allowed: tuple[str, ...], what: str) -> None:
    if inv["status"] not in allowed:
        raise _conflict(INVALID_STATE, f"{what} needs an invoice that is {' or '.join(allowed)}; this one is {inv['status']}",
                        "input.invoice_id", {"status": inv["status"], "allowed": list(allowed)})


def _set_status(conn: Conn, invoice_id: str, status: str, **cols: Any) -> int:
    """Move an invoice's workflow state; returns the new version."""
    sets = ", ".join(f"{k} = %s" for k in cols)
    row = conn.execute(f"UPDATE invoices SET status = %s, version = version + 1, updated_at = now(){', ' + sets if sets else ''} "
                       "WHERE invoice_id = %s RETURNING version", (status, *cols.values(), invoice_id)).fetchone()  # cols are constants
    return row["version"]


def _domain_invoice(pop: Any, invoice_id: str) -> Invoice:
    return next(i for i in pop.invoices if i.invoice_id == invoice_id)


def _amounts_json(inv: Invoice) -> dict[str, str]:
    sub, tax, total = invoice_amounts(inv)
    return {"subtotal": s2(sub), "tax": s2(tax), "total": s2(total), "declared_total": s2(inv.declared_total),
            "rounding_difference": s2(abs(inv.declared_total - total))}


def _lineage(conn: Conn, invoice_id: str, sha: str, filename: str, key: str, imported_at: datetime, actor: Actor,
             status: str, reason: str | None = None, merged_into: str | None = None) -> int:
    row = conn.execute(
        "INSERT INTO import_lineage (invoice_id, source_sha256, source_filename, idempotency_key, imported_at, actor_id, "
        "import_status, reason_code, merged_into) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING lineage_id",
        (invoice_id, sha, filename, key, imported_at, actor.actor_id, status, reason, merged_into)).fetchone()
    return row["lineage_id"]


# --- C01 import-invoice -----------------------------------------------------------------------------------------

def import_invoice(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, IMPORT_ROLES, "import-invoice")
    inp = req.input
    # D-09: an import is never stamped later than the server clock (a client that could pick the instant could place an invoice
    # anywhere in the import order); a later value is clamped and said so.
    now = clock.now()
    asked = parse_ts(inp.imported_at) if inp.imported_at else None
    imported_at = now if asked is None else min(asked, now)
    clamped = asked is not None and asked > now
    # A row that does not exist yet cannot be locked: serialise imports of one invoice id and of one set of source bytes
    # with advisory locks (taken in sorted order, after the idempotency key and before any invoice row).
    for name in sorted((f"invoice:{inp.invoice_id}", f"sha256:{inp.source_sha256}")):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (name,))
    existing = _lock_invoices(conn, [inp.invoice_id]).get(inp.invoice_id)
    if existing is not None:
        if existing["source_sha256"] != inp.source_sha256:
            raise _conflict("DUPLICATE_ID", "an invoice with this id exists with different source bytes", "input.invoice_id",
                            {"existing_sha256": existing["source_sha256"]})
        # the same bytes again under the same invoice id: one obligation, the import is recorded, nothing else changes
        lid = _lineage(conn, existing["invoice_id"], inp.source_sha256, inp.source_filename, req.idempotency_key, imported_at,
                       actor, "merged", DUPLICATE_SOURCE_BYTES, existing["invoice_id"])
        return Outcome("duplicate", {"invoice_id": existing["invoice_id"], "status": existing["status"],
                                     "import_status": "merged", "reason_code": DUPLICATE_SOURCE_BYTES,
                                     "duplicate_of": existing["invoice_id"], "lineage_id": lid},
                       existing["version"], [_warning(DUPLICATE_SOURCE_BYTES, "the same source bytes were already imported",
                                                      "input.source_sha256")],
                       Audit("invoice", inp.invoice_id, "import-invoice", invoice_id=inp.invoice_id,
                             details={"import_status": "merged", "reason_code": DUPLICATE_SOURCE_BYTES}))
    vendor = conn.execute("SELECT * FROM vendors WHERE vendor_id = %s", (inp.vendor_id,)).fetchone()
    raw_inv = {"invoice_id": inp.invoice_id, "vendor_id": inp.vendor_id, "invoice_number": inp.invoice_number,
               "invoice_date": inp.invoice_date, "currency": inp.currency, "tax_rate": inp.tax_rate, "freight": inp.freight,
               "invoice_discount": inp.invoice_discount, "declared_total": inp.declared_total, "created_by": actor.actor_id,
               "source_sha256": inp.source_sha256, "source_filename": inp.source_filename,
               "idempotency_key": req.idempotency_key, "imported_at": iso_z(imported_at)}
    raw_lines = [{"invoice_line_id": l.invoice_line_id, "invoice_id": inp.invoice_id, "po_line_id": l.po_line_id,
                  "quantity": l.quantity, "unit_price": l.unit_price,
                  **({"line_amount": l.line_amount} if l.line_amount is not None else {})} for l in inp.lines]
    batch = validate_batch({"vendors": [] if vendor is None else [{k: vendor[k].strip() if isinstance(vendor[k], str) else vendor[k]
                                                                  for k in ("vendor_id", "vendor_name", "tax_reference", "currency", "active")}],
                            "invoices": [raw_inv], "invoice_lines": raw_lines})
    clash = conn.execute("SELECT invoice_line_id FROM invoice_lines WHERE invoice_line_id = ANY(%s)",
                         ([l["invoice_line_id"] for l in raw_lines],)).fetchall()
    if batch.rejected or clash:
        details = [{**detail(f"input.{r.entity}[{r.id}]", r.reason_code, r.message or r.reason_code)} for r in batch.rejected]
        details += [detail(f"input.lines[{c['invoice_line_id']}]", "DUPLICATE_ID", "invoice_line_id already exists") for c in clash]
        _persist_rejection(req, actor, inp, imported_at, batch.rejected, bool(clash))
        raise ApiError(422, "VALIDATION_FAILED", "the invoice was rejected at import", details)
    inv = batch.accepted["invoices"][0]
    sub, tax, total = invoice_amounts(inv)
    # The same bytes under another invoice id. The canonical copy is the first stored one that can be canonical (not invalid,
    # not held for review). Same bytes AND the same identity is one obligation (merged); same bytes with other extracted fields is
    # a conflicting extraction, held for review and merged into nothing (D-09, R5-20). The stored canonical of concurrent
    # same-bytes imports can differ from the derived one (D-06: warned, counts agree); the derivation is what the metrics use.
    canon = conn.execute("SELECT invoice_id, merged_into FROM invoices WHERE source_sha256 = %s AND status <> 'needs_review' "
                         "AND validity IS DISTINCT FROM FALSE ORDER BY imported_at, invoice_id LIMIT 1", (inp.source_sha256,)).fetchone()
    merged_into = review_of = None
    if canon is not None:
        root = conn.execute("SELECT invoice_id, vendor_id, invoice_number_norm, invoice_date, total FROM invoices WHERE invoice_id = %s",
                            (canon["merged_into"] or canon["invoice_id"],)).fetchone()
        same = (root["vendor_id"], root["invoice_number_norm"], root["invoice_date"].isoformat(), root["total"]) == (
            inv.vendor_id, normalise_number(inv.invoice_number), inv.invoice_date.isoformat(), total)
        merged_into, review_of = (root["invoice_id"], None) if same else (None, root["invoice_id"])
    conn.execute(
        "INSERT INTO invoices (invoice_id, vendor_id, invoice_number, invoice_number_norm, invoice_date, currency, tax_rate, "
        "freight, invoice_discount, declared_total, subtotal, tax, total, created_by, source_sha256, source_filename, "
        "idempotency_key, imported_at, status, merged_into, merge_reason) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (inv.invoice_id, inv.vendor_id, inv.invoice_number, normalise_number(inv.invoice_number), inv.invoice_date, inv.currency,
         inv.tax_rate, inv.freight, inv.invoice_discount, inv.declared_total, sub, tax, total, actor.actor_id,
         inv.source_sha256, inv.source_filename, req.idempotency_key, imported_at,
         "merged" if merged_into else "needs_review" if review_of else "received", merged_into,
         DUPLICATE_SOURCE_BYTES if merged_into else None))
    for l in inv.lines:
        conn.execute("INSERT INTO invoice_lines VALUES (%s, %s, %s, %s, %s, %s)",
                     (l.invoice_line_id, l.invoice_id, l.po_line_id, l.quantity, l.unit_price, l.line_amount))
    lid = _lineage(conn, inv.invoice_id, inv.source_sha256, inv.source_filename, req.idempotency_key,
                   imported_at, actor, "merged" if merged_into else "accepted",
                   DUPLICATE_SOURCE_BYTES if merged_into else BYTES_FIELDS_CONFLICT if review_of else None, merged_into)
    status = "merged" if merged_into else "needs_review" if review_of else "received"
    result = {"invoice_id": inv.invoice_id, "status": status,
              "import_status": "merged" if merged_into else "accepted", "created_by": actor.actor_id, "lineage_id": lid,
              "imported_at": iso_z(imported_at), **_amounts_json(inv), "lines": len(inv.lines)}
    warnings = []
    if clamped:
        warnings.append(_warning("IMPORTED_AT_CLAMPED", f"imported_at was later than the server clock and was set to {iso_z(imported_at)}",
                                 "input.imported_at"))
    if review_of:
        result.update(reason_code=BYTES_FIELDS_CONFLICT, review_against=review_of)
        warnings.append(_warning(BYTES_FIELDS_CONFLICT, f"the same source bytes were imported as {review_of} with other extracted "
                                 "fields: held for review, not merged, nothing is consumed", "input.source_sha256"))
    if merged_into:
        result.update(reason_code=DUPLICATE_SOURCE_BYTES, duplicate_of=merged_into)
        warnings.append(_warning(DUPLICATE_SOURCE_BYTES, f"the same source bytes were imported as {merged_into}: one "
                                 "obligation, no received quantity is consumed", "input.source_sha256"))
    return Outcome(result["status"], result, 1, warnings,
                   Audit("invoice", inv.invoice_id, "import-invoice", None, 1, invoice_id=inv.invoice_id,
                         details={"import_status": result["import_status"], "source_sha256": inv.source_sha256,
                                  **({"review": BYTES_FIELDS_CONFLICT} if review_of else {})}))


def _persist_rejection(req: Any, actor: Actor, inp: Any, imported_at: datetime, rejected: list[Any], line_clash: bool) -> None:
    """A rejected import keeps its raw rows and a lineage row even though the request is refused (own transaction)."""
    batch_id = f"batch-{sha256_hex(req.idempotency_key)[:16]}"
    if not rejected:
        return
    with db.autocommit() as c:
        insert_rejected(c, batch_id, rejected)
        c.execute("INSERT INTO import_lineage (invoice_id, source_sha256, source_filename, idempotency_key, imported_at, actor_id, "
                  "import_status, reason_code) SELECT %s,%s,%s,%s,%s,%s,'rejected',%s WHERE NOT EXISTS (SELECT 1 FROM import_lineage "
                  "WHERE invoice_id = %s AND idempotency_key = %s AND import_status = 'rejected')",
                  (inp.invoice_id, inp.source_sha256, inp.source_filename, req.idempotency_key, imported_at, actor.actor_id,
                   next((r.reason_code for r in rejected if r.entity == "invoices"), rejected[0].reason_code),
                   inp.invoice_id, req.idempotency_key))


# --- C02 validate-invoice ---------------------------------------------------------------------------------------

def validate_invoice_cmd(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, WORK_ROLES, "validate-invoice")
    inv_row = _invoice(conn, req.input.invoice_id)
    _need_status(inv_row, ("received",), "validate-invoice")
    pop = db.load_population(conn)
    inv = _domain_invoice(pop, inv_row["invoice_id"])
    vendor = next((v for v in pop.vendors if v.vendor_id == inv.vendor_id), None)
    rules = validate_invoice(inv, vendor)
    ok = not rules
    version = _set_status(conn, inv.invoice_id, "valid" if ok else "invalid", validity=ok,
                          validation_rules=Jsonb([{"rule_id": r, "message": m} for r, m in rules]))
    result = {"invoice_id": inv.invoice_id, "status": "valid" if ok else "invalid", "valid": ok, **_amounts_json(inv),
              "rules": [{"rule_id": r, "message": m} for r, m in rules]}
    return Outcome(result["status"], result, version,
                   [_warning(r, m, "input.invoice_id") for r, m in rules],
                   Audit("invoice", inv.invoice_id, "validate-invoice", version - 1, version, invoice_id=inv.invoice_id,
                         details={"rules": [r for r, _ in rules]}))


# --- C03 find-duplicates ----------------------------------------------------------------------------------------

def _group_of(pop: Any, invoice_id: str) -> tuple[str, list[str], dict[str, str], dict[str, str]]:
    """The duplicate group of an invoice as the derivation sees it (committed copy first, then the earliest import; an invalid
    invoice is never canonical). Returns ``(canonical, members, merged_into, held_for_review)``."""
    merged_into, _records, _g, review, _first = duplicate_groups(pop, FAR_FUTURE)
    canon = merged_into.get(invoice_id, invoice_id)
    members = sorted({canon} | {i for i, c in merged_into.items() if c == canon})
    return canon, members, merged_into, review


def find_duplicates(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, WORK_ROLES, "find-duplicates")
    iid = req.input.invoice_id
    if conn.execute("SELECT 1 FROM invoices WHERE invoice_id = %s", (iid,)).fetchone() is None:
        raise _not_found("input.invoice_id", "INVOICE_UNKNOWN", "invoice")
    canon, members, _, _ = _group_of(db.load_population(conn), iid)        # find the group, then lock it (sorted) ...
    locked = _lock_invoices(conn, members + [iid])
    pop = db.load_population(conn)                                         # ... and read it again under the locks
    canon, members, merged_into, review = _group_of(pop, iid)
    if set(members) - set(locked):                                          # a new member appeared: lock it too
        locked.update(_lock_invoices(conn, members))
    target = locked[iid]
    _need_status(target, ("valid", "matched", "exception", "merged", "needs_review"), "find-duplicates")
    if iid in review:                                                       # same bytes, other fields: held for review (D-09)
        version = target["version"]
        if target["status"] != "needs_review":
            if target["status"] in ("approved", "exported", "adjusted"):
                raise _conflict(INVALID_STATE, f"{iid} is {target['status']} and cannot be held for review", "input.invoice_id",
                                {"invoice_id": iid, "status": target["status"]})
            version = _set_status(conn, iid, "needs_review")
        return Outcome("needs_review", {"invoice_id": iid, "status": "needs_review", "reason_code": BYTES_FIELDS_CONFLICT,
                                        "review_against": review[iid], "canonical_id": review[iid], "is_canonical": False,
                                        "candidates": [], "merged": [], "review": "a person decides: same bytes, other fields"},
                       version, [_warning(BYTES_FIELDS_CONFLICT, f"{iid} has the source bytes of {review[iid]} but other extracted fields",
                                          "input.invoice_id")],
                       Audit("invoice", iid, "find-duplicates", invoice_id=iid, details={"review": BYTES_FIELDS_CONFLICT}))
    by_id = {i.invoice_id: i for i in pop.invoices}
    me = by_id[iid]
    candidates = []
    for m in members:
        if m == iid:
            continue
        o = by_id[m]
        matched_on = []
        if o.source_sha256 == me.source_sha256:
            matched_on.append("source_sha256")
        if identity_key(o) == identity_key(me):
            matched_on += ["vendor_id", "invoice_number_normalised", "invoice_date", "computed_total"]
        candidates.append({"invoice_id": m, "status": locked[m]["status"], "matched_on": matched_on or ["via_group"],
                           "role": "canonical" if m == canon else "duplicate",
                           "explanation": ("same source bytes" if "source_sha256" in matched_on else
                                           f"same vendor, normalised number {normalise_number(o.invoice_number)}, invoice date "
                                           f"{o.invoice_date.isoformat()} and computed total {s2(invoice_amounts(o)[2])}")
                           if matched_on else "linked through another invoice of the group"})
    merged_now: list[str] = []
    for m in members:
        if m == canon:
            continue
        st = locked[m]["status"]
        if st == "merged":
            continue
        if st not in ("received", "valid", "invalid", "matched", "exception", "rejected"):
            raise _conflict(INVALID_STATE, f"{m} is {st} and cannot be merged into {canon}", "input.invoice_id",
                            {"invoice_id": m, "status": st})
        reason = "DUPLICATE_SOURCE_BYTES" if by_id[m].source_sha256 == by_id[canon].source_sha256 else "DUPLICATE_IDENTITY"
        _set_status(conn, m, "merged", merged_into=canon, merge_reason=reason)
        conn.execute("UPDATE exceptions SET status = 'resolved', resolved_at = now() WHERE invoice_id = %s AND status <> 'resolved'", (m,))
        _lineage(conn, m, by_id[m].source_sha256, by_id[m].source_filename, by_id[m].idempotency_key, by_id[m].imported_at,
                 actor, "merged", reason, canon)
        merged_now.append(m)
    status = "merged" if iid in merged_into else locked[iid]["status"]
    version = conn.execute("SELECT version FROM invoices WHERE invoice_id = %s", (iid,)).fetchone()["version"]
    result = {"invoice_id": iid, "status": status, "canonical_id": canon, "is_canonical": canon == iid,
              "candidates": candidates, "merged": merged_now, "review": "none" if not candidates else "merged automatically"}
    return Outcome("merged" if iid in merged_into else ("duplicates_found" if candidates else "no_duplicates"), result, version,
                   audit=Audit("invoice", iid, "find-duplicates", invoice_id=iid,
                               details={"canonical": canon, "merged": merged_now}))


# --- C04 match-three-way ----------------------------------------------------------------------------------------

def match_three_way(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, WORK_ROLES, "match-three-way")
    inv_row = _invoice(conn, req.input.invoice_id)
    _need_status(inv_row, ("valid", "matched", "exception"), "match-three-way")
    iid = inv_row["invoice_id"]
    _lock_po_lines(conn, [r["po_line_id"] for r in conn.execute(
        "SELECT po_line_id FROM invoice_lines WHERE invoice_id = %s", (iid,)).fetchall()])
    pop = db.load_population(conn)
    book = derive(pop, None)
    if iid in book.merged_into:
        raise _conflict(INVALID_STATE, f"{iid} is a duplicate of {book.merged_into[iid]}; run find-duplicates first",
                        "input.invoice_id", {"merged_into": book.merged_into[iid]})
    if iid not in book.run.invoices:
        raise _conflict(INVALID_STATE, f"{iid} is not in the book (status {book.status[iid]}): it is not matched", "input.invoice_id",
                        {"derived_status": book.status[iid]})
    res = book.run.invoices[iid]
    lines = sorted((r for r in book.run.lines if r.invoice_id == iid), key=lambda r: r.invoice_line_id)
    for r in lines:
        conn.execute(
            "INSERT INTO match_results (invoice_line_id, invoice_id, rule_version, status, reason_code, available_quantity, "
            "quantity_variance, price_variance, explanation, matched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now()) "
            "ON CONFLICT (invoice_line_id) DO UPDATE SET rule_version = EXCLUDED.rule_version, status = EXCLUDED.status, "
            "reason_code = EXCLUDED.reason_code, available_quantity = EXCLUDED.available_quantity, "
            "quantity_variance = EXCLUDED.quantity_variance, price_variance = EXCLUDED.price_variance, "
            "explanation = EXCLUDED.explanation, matched_at = now()",
            (r.invoice_line_id, iid, RULE_VERSION, r.status, r.reason_code, r.available, r.quantity_variance,
             r.price_variance, r.explanation))
    # exceptions: keep the open ones that still hold, resolve those that no longer do, open the new ones
    open_rows = {r["exception_type"]: r for r in conn.execute(
        "SELECT * FROM exceptions WHERE invoice_id = %s AND status <> 'resolved' FOR UPDATE", (iid,)).fetchall()}
    for t, row in open_rows.items():
        if t not in res.reasons:
            conn.execute("UPDATE exceptions SET status = 'resolved', resolved_at = now() WHERE exception_id = %s", (row["exception_id"],))
    exceptions = []
    for t in res.reasons:
        if t in open_rows:
            row = open_rows[t]
        else:
            while True:
                eid = f"exc-{conn.execute('SELECT nextval(%s) AS n', ('exception_seq',)).fetchone()['n']:03d}"
                if conn.execute("SELECT 1 FROM exceptions WHERE exception_id = %s", (eid,)).fetchone() is None:
                    break
            row = conn.execute("INSERT INTO exceptions (exception_id, invoice_id, exception_type) VALUES (%s,%s,%s) RETURNING *",
                               (eid, iid, t)).fetchone()
        exceptions.append({"exception_id": row["exception_id"], "exception_type": t, "status": row["status"],
                           "owner_id": row["owner_id"]})
    status = "matched" if res.matched else "exception"
    version = _set_status(conn, iid, status)
    result = {"invoice_id": iid, "status": status, "matched": res.matched, "rule_version": RULE_VERSION,
              "lines": [{**r.as_row(), "explanation": r.explanation} for r in lines], "exceptions": exceptions,
              "subtotal": s2(res.subtotal), "tax": s2(res.tax), "total": s2(res.total),
              "rounding_difference": s2(res.rounding_difference),
              "note": "matching never confers approval; an approval is a separate decision by another person"}
    return Outcome(status, result, version,
                   [_warning(t, f"{iid} raised {t}", "input.invoice_id") for t in res.reasons],
                   Audit("invoice", iid, "match-three-way", version - 1, version, invoice_id=iid,
                         details={"matched": res.matched, "reasons": res.reasons}))


# --- C05 assign-exception ---------------------------------------------------------------------------------------

def assign_exception(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, WORK_ROLES, "assign-exception")
    inp = req.input
    row = conn.execute("SELECT invoice_id FROM exceptions WHERE exception_id = %s", (inp.exception_id,)).fetchone()
    if row is None:
        raise _not_found("input.exception_id", "EXCEPTION_UNKNOWN", "exception")
    _lock_invoices(conn, [row["invoice_id"]])                             # lock order: the invoice first ...
    exc = conn.execute("SELECT * FROM exceptions WHERE exception_id = %s FOR UPDATE", (inp.exception_id,)).fetchone()   # ... then the exception
    if exc["status"] == "resolved":
        raise _conflict(INVALID_STATE, "the exception is resolved and cannot be assigned", "input.exception_id",
                        {"status": "resolved"})
    at = _at(inp.assigned_at)
    prior_owner = exc["owner_id"]
    aid = conn.execute("INSERT INTO exception_assignments (exception_id, owner_id, assigned_by, assigned_at, note) "
                       "VALUES (%s,%s,%s,%s,%s) RETURNING assignment_id",
                       (inp.exception_id, inp.owner_id, actor.actor_id, at, inp.note)).fetchone()["assignment_id"]
    conn.execute("UPDATE exceptions SET status = 'assigned', owner_id = %s WHERE exception_id = %s", (inp.owner_id, inp.exception_id))
    history = conn.execute("SELECT count(*) AS n FROM exception_assignments WHERE exception_id = %s", (inp.exception_id,)).fetchone()["n"]
    return Outcome("assigned", {"exception_id": inp.exception_id, "invoice_id": exc["invoice_id"], "status": "assigned",
                                "owner_id": inp.owner_id, "previous_owner_id": prior_owner, "assignment_id": aid,
                                "assignments": history, "assigned_at": iso_z(at)},
                   history, audit=Audit("exception", inp.exception_id, "assign-exception", history - 1, history,
                                        invoice_id=exc["invoice_id"], details={"owner_id": inp.owner_id}))


# --- C07 approve-invoice ----------------------------------------------------------------------------------------

def _need_current_match(book: Any, iid: str) -> None:
    """C07, C09 and C10 re-derive the match from the facts: a receipt reversed since the match, or a copy of an invoice that is
    already committed, refuses the command (409), whatever the stored workflow state says (D-09)."""
    if iid in book.merged_into:
        raise _conflict("DUPLICATE_PENDING", f"{iid} is a duplicate of {book.merged_into[iid]}: only the canonical copy can advance",
                        "input.invoice_id", {"merged_into": book.merged_into[iid]})
    if iid in book.review:
        raise _conflict("DUPLICATE_PENDING", f"{iid} has the source bytes of {book.review[iid]} with other extracted fields: it is held "
                        "for review", "input.invoice_id", {"review_against": book.review[iid]})
    st = book.run.invoices.get(iid)
    if st is None or not st.matched:                                       # a receipt may have been reversed since the match
        raise _conflict("STALE_MATCH", "the invoice no longer matches (receipts or invoices changed); match it again",
                        "input.invoice_id", {"rule_id": "NOT_MATCHED"}, rule_id="NOT_MATCHED")


def approve_invoice(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, DECISION_ROLES, "approve-invoice")
    inp = req.input
    inv_row = _invoice(conn, inp.invoice_id)
    _need_status(inv_row, ("matched",), "approve-invoice")
    iid = inv_row["invoice_id"]
    if actor.actor_id == inv_row["created_by"]:                              # separation of duties (D-04, P05-TEST-06)
        _refusal(actor, req, "approve-invoice", iid, "SELF_APPROVAL", "the approver created or imported this invoice")
        raise _forbidden("SELF_APPROVAL", "the approver must differ from the person who created the invoice",
                         "header.X-Actor-Id", {"created_by": inv_row["created_by"]})
    at = clock.now()                                                         # the server stamps the decision (D-09, R5-04)
    pop = db.load_population(conn)
    policy = effective_policy(pop.approval_policies, at)
    total = inv_row["total"]
    if not role_may_approve(policy, actor.role, total):
        _refusal(actor, req, "approve-invoice", iid, "ROLE_OR_LIMIT", "role or limit not allowed by the policy in force")
        raise _forbidden("ROLE_OR_LIMIT" if policy else "NO_POLICY",
                         "no approval policy is in force at that instant" if policy is None else
                         f"the policy v{policy.version_number} does not allow role {actor.role} to approve {s2(total)}",
                         "header.X-Actor-Role", {"policy_id": getattr(policy, "policy_id", None), "total": s2(total)})
    aid = inp.approval_id or f"ap-{uuid.uuid4().hex[:12]}"
    # re-derive WITH this approval: it commits the invoice, so it is matched ahead of every uncommitted invoice (D-09)
    book = derive(dataclasses.replace(pop, approvals=[*pop.approvals, Approval(aid, iid, actor.actor_id, actor.role, "approve", at)]), None)
    _need_current_match(book, iid)
    conn.execute("INSERT INTO approvals (approval_id, invoice_id, actor_id, actor_role, decision, decided_at, policy_id, "
                 "policy_version) VALUES (%s,%s,%s,%s,'approve',%s,%s,%s)",
                 (aid, iid, actor.actor_id, actor.role, at, policy.policy_id, policy.version_number))
    version = _set_status(conn, iid, "approved")
    return Outcome("approved", {"approval_id": aid, "invoice_id": iid, "status": "approved", "actor_id": actor.actor_id,
                                "actor_role": actor.role, "decided_at": iso_z(at), "policy_id": policy.policy_id,
                                "policy_version": policy.version_number, "total": s2(total)},
                   version, audit=Audit("invoice", iid, "approve-invoice", version - 1, version, invoice_id=iid,
                                        details={"approval_id": aid, "policy_version": policy.version_number}))


# --- C08 reject-invoice -----------------------------------------------------------------------------------------

def reject_invoice(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, DECISION_ROLES, "reject-invoice")
    inp = req.input
    inv_row = _invoice(conn, inp.invoice_id)
    _need_status(inv_row, ("valid", "matched", "exception"), "reject-invoice")
    iid = inv_row["invoice_id"]
    if actor.actor_id == inv_row["created_by"]:                              # separation of duties covers rejection too (D-09, R5-19)
        _refusal(actor, req, "reject-invoice", iid, "SELF_DECISION", "the rejecter created or imported this invoice")
        raise _forbidden("SELF_DECISION", "the rejecter must differ from the person who created the invoice",
                         "header.X-Actor-Id", {"created_by": inv_row["created_by"]})
    at = clock.now()
    pop = db.load_population(conn)
    policy = effective_policy(pop.approval_policies, at)
    if policy is None or actor.role not in {policy.reviewer_role, policy.escalation_role}:
        raise _forbidden("ROLE_OR_LIMIT", "the policy in force does not allow this role to decide invoices",
                         "header.X-Actor-Role")
    aid = inp.approval_id or f"ap-{uuid.uuid4().hex[:12]}"
    conn.execute("INSERT INTO approvals (approval_id, invoice_id, actor_id, actor_role, decision, decided_at, reason, policy_id, "
                 "policy_version) VALUES (%s,%s,%s,%s,'reject',%s,%s,%s,%s)",
                 (aid, iid, actor.actor_id, actor.role, at, inp.reason.strip(), policy.policy_id, policy.version_number))
    conn.execute("UPDATE exceptions SET status = 'resolved', resolved_at = now() WHERE invoice_id = %s AND status <> 'resolved'", (iid,))
    version = _set_status(conn, iid, "rejected")
    return Outcome("rejected", {"approval_id": aid, "invoice_id": iid, "status": "rejected", "reason": inp.reason.strip(),
                                "decided_at": iso_z(at), "consumes_received_quantity": False},
                   version, audit=Audit("invoice", iid, "reject-invoice", version - 1, version, reason=inp.reason.strip(),
                                        invoice_id=iid, details={"approval_id": aid}))


# --- C09 export-payable -----------------------------------------------------------------------------------------

def _batch_json(conn: Conn, batch_id: str) -> dict[str, Any]:
    b = conn.execute("SELECT * FROM export_batches WHERE batch_id = %s", (batch_id,)).fetchone()
    rows = conn.execute("SELECT * FROM export_rows WHERE batch_id = %s ORDER BY invoice_id COLLATE \"C\"", (batch_id,)).fetchall()
    return {"batch_id": batch_id, "exported_at": iso_z(b["exported_at"]), "total": format(b["total"], "f"),
            "rows": [{k: db.jsonable(v) for k, v in r.items() if k != "exported_at"} | {"exported_at": iso_z(r["exported_at"])}
                     for r in rows]}


def _record_request(conn: Conn, inp: Any, key: str, actor: Actor, outcome: str) -> None:
    conn.execute("INSERT INTO export_requests (batch_id, idempotency_key, invoice_ids, exported_at, outcome, requested_by) "
                 "VALUES (%s,%s,%s,%s,%s,%s)", (inp.batch_id, key, list(inp.invoice_ids), _at(inp.exported_at), outcome, actor.actor_id))


def export_replayed(conn: Conn, req: Any, actor: Actor) -> None:
    """The same idempotency key again (a retry after a timeout): the stored batch is returned and the request is counted."""
    _record_request(conn, req.input, req.idempotency_key, actor, "returned_prior")


def export_payable(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, DECISION_ROLES, "export-payable")
    inp = req.input
    ids = sorted(set(inp.invoice_ids))
    locked = _lock_invoices(conn, ids)
    unknown = [i for i in ids if i not in locked]
    if unknown:
        raise _invalid("INVOICE_UNKNOWN", f"unknown invoice(s): {', '.join(unknown)}", "input.invoice_ids", {"unknown": unknown})
    prior = conn.execute("SELECT batch_id FROM export_batches WHERE batch_id = %s", (inp.batch_id,)).fetchone()
    if prior is not None:                                                  # keyed by (invoice_id, batch_id): the prior batch
        same = [r["invoice_id"] for r in conn.execute("SELECT invoice_id FROM export_rows WHERE batch_id = %s ORDER BY invoice_id COLLATE \"C\"",
                                                      (inp.batch_id,)).fetchall()]
        if same != ids:
            raise _conflict("BATCH_CONFLICT", "this batch id exists with a different set of invoices", "input.batch_id",
                            {"batch_invoices": same})
        _record_request(conn, inp, req.idempotency_key, actor, "returned_prior")
        out = {**_batch_json(conn, inp.batch_id), "returned_prior": True}
        return Outcome("returned_prior", out, 1, [_warning("BATCH_RETURNED_PRIOR", "the batch already exists: its rows are returned", "input.batch_id")],
                       Audit("export_batch", inp.batch_id, "export-payable", details={"returned_prior": True}))
    problems = []
    for iid in ids:
        st = locked[iid]["status"]
        if conn.execute("SELECT 1 FROM export_rows WHERE invoice_id = %s", (iid,)).fetchone():
            problems.append({"invoice_id": iid, "reason_code": "ALREADY_EXPORTED"})
        elif st not in ("approved", "adjusted"):
            problems.append({"invoice_id": iid, "reason_code": "EXCEPTION_OPEN" if st == "exception" else "NOT_APPROVED", "status": st})
    if problems:
        raise _conflict(INVALID_STATE, "some invoices cannot be exported", "input.invoice_ids", {"exclusions": problems})
    at = _at(inp.exported_at)
    pop = db.load_population(conn)
    book = derive(pop, None)
    for iid in ids:                                                        # re-derive the match like C07 does (D-09)
        _need_current_match(book, iid)
    early = [i for i in ids if i in book.approved and at < book.approved[i]]
    if early:                                                              # an export row needs a valid approval at or before it
        raise _invalid("EXPORTED_BEFORE_APPROVAL", f"exported_at {iso_z(at)} is before the approval of {', '.join(early)}",
                       "input.exported_at", {"invoices": early, "approved_at": {i: iso_z(book.approved[i]) for i in early}})
    total = sum((locked[i]["total"] for i in ids), Decimal(0))
    conn.execute("INSERT INTO export_batches (batch_id, idempotency_key, requested_by, exported_at, row_count, total) "
                 "VALUES (%s,%s,%s,%s,%s,%s)", (inp.batch_id, req.idempotency_key, actor.actor_id, at, len(ids), total))
    for iid in ids:
        i = _domain_invoice(pop, iid)
        amount = s2(locked[iid]["total"])
        conn.execute("INSERT INTO export_rows VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (f"exp-{inp.batch_id}-{iid}", inp.batch_id, iid, at, i.vendor_id, i.invoice_number, i.invoice_date,
                      i.currency, amount, content_hash(i, amount)))
        if locked[iid]["status"] == "approved":
            _set_status(conn, iid, "exported")
    _record_request(conn, inp, req.idempotency_key, actor, "created")
    out = {**_batch_json(conn, inp.batch_id), "returned_prior": False, "payments": "none: nothing is paid and no invoice is marked paid"}
    return Outcome("exported", out, 1, audit=[Audit("export_batch", inp.batch_id, "export-payable", details={"invoices": ids}),
                                              *[Audit("invoice", i, "export-payable", invoice_id=i, details={"batch_id": inp.batch_id}) for i in ids]])


# --- C10 apply-credit-note --------------------------------------------------------------------------------------

def apply_credit_note(conn: Conn, req: Any, actor: Actor) -> Outcome:
    _need_role(actor, DECISION_ROLES, "apply-credit-note")
    inp = req.input
    inv_row = _invoice(conn, inp.invoice_id)
    _need_status(inv_row, ("approved", "exported", "adjusted"), "apply-credit-note")
    iid = inv_row["invoice_id"]
    _need_current_match(derive(db.load_population(conn), None), iid)      # re-derive the match like C07 does (D-09)
    try:
        amount = Decimal(inp.credit_amount)
    except Exception:
        raise _invalid("MALFORMED_RECORD", "credit_amount is not a decimal number", "input.credit_amount") from None
    if -amount.as_tuple().exponent > 2 and amount != amount.quantize(Decimal("0.01")):
        raise _invalid("MALFORMED_RECORD", "credit_amount carries more than 2 decimals", "input.credit_amount")
    if amount <= 0:
        raise _invalid(NON_POSITIVE_AMOUNT, "a credit note must be a positive amount", "input.credit_amount")
    if conn.execute("SELECT 1 FROM credit_notes WHERE credit_id = %s", (inp.credit_id,)).fetchone():
        raise _conflict("CREDIT_ALREADY_APPLIED", "this credit note was already applied (once per credit_id)", "input.credit_id")
    used = conn.execute("SELECT coalesce(sum(credit_amount), 0) AS s FROM credit_notes WHERE invoice_id = %s", (iid,)).fetchone()["s"]
    if used + amount > inv_row["total"]:
        raise _invalid(CREDIT_EXCEEDS_INVOICE, f"credits {s2(used + amount)} would exceed the invoice total {s2(inv_row['total'])}",
                       "input.credit_amount", {"already_credited": s2(used), "total": s2(inv_row["total"])})
    at = _at(inp.credited_at)
    conn.execute("INSERT INTO credit_notes (credit_id, invoice_id, credit_amount, credited_at, reason, created_by) "
                 "VALUES (%s,%s,%s,%s,%s,%s)", (inp.credit_id, iid, amount, at, inp.reason, actor.actor_id))
    version = _set_status(conn, iid, "adjusted")
    credited = used + amount
    return Outcome("adjusted", {"credit_id": inp.credit_id, "invoice_id": iid, "status": "adjusted", "credit_amount": s2(amount),
                                "credit_total": s2(credited), "invoice_total": s2(inv_row["total"]),
                                "approved_payable": s2(inv_row["total"] - credited), "cash_movement": False,
                                "credited_at": iso_z(at)},
                   version, audit=Audit("invoice", iid, "apply-credit-note", version - 1, version, invoice_id=iid,
                                        details={"credit_id": inp.credit_id, "credit_amount": s2(amount)}))


# --- extension commands -----------------------------------------------------------------------------------------

def not_implemented(name: str, code: str) -> ApiError:
    return ApiError(501, "NOT_IMPLEMENTED", f"{name} ({code}) is an extension-milestone command and is not implemented",
                    [detail("command", "NOT_IMPLEMENTED", f"{name} is not implemented in this milestone")])


__all__ = ["Actor", "ROLES", "execute", "import_invoice", "validate_invoice_cmd", "find_duplicates", "match_three_way",
           "assign_exception", "approve_invoice", "reject_invoice", "export_payable", "export_replayed",
           "apply_credit_note", "not_implemented"]
