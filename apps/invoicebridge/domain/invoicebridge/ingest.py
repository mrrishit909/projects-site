"""Ingest: validate a batch of raw rows (D-05 rejection codes, atomic invoices, dependent rejection, merge).

Every row is accepted, rejected (reason code, raw row kept) or, for an invoice, merged into the earliest import of the
same obligation. Order of checks follows ``tests/reference_check.py`` exactly for the fixtures; codes the contract does
not list (MALFORMED_RECORD, DUPLICATE_ID, UNKNOWN_INVOICE, NON_POSITIVE_AMOUNT, CREDIT_EXCEEDS_INVOICE) are the
backend's assumptions and are listed in README.md.

An invoice is atomic: one bad line, an unknown vendor or a malformed header rejects the header, every sibling line and
any approval or credit note that names it (DEPENDENT_REJECTED).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from .amounts import invoice_amounts
from .contract import ENTITIES
from .duplicates import detect_duplicates
from .errors import (CREDIT_EXCEEDS_INVOICE, DEPENDENT_REJECTED, DUPLICATE_ID, MALFORMED_RECORD, NON_POSITIVE_AMOUNT,
                     NON_POSITIVE_QUANTITY, UNKNOWN_INVOICE, UNKNOWN_PO, UNKNOWN_PO_LINE, UNKNOWN_VENDOR, DomainError)
from .models import (CreditNote, Invoice, InvoiceLine, Population, parse_approval, parse_credit, parse_export_request, parse_invoice, parse_line,
                     parse_po, parse_po_line, parse_policy, parse_receipt, parse_tolerances, parse_vendor)

Row = dict[str, Any]
ID_KEYS = {"vendors": "vendor_id", "purchase_orders": "po_id", "po_lines": "po_line_id", "receipts": "receipt_id",
           "invoices": "invoice_id", "invoice_lines": "invoice_line_id", "credit_notes": "credit_id",
           "approval_policies": "policy_id", "approvals": "approval_id"}


@dataclass(frozen=True)
class Rejection:
    entity: str
    id: str
    reason_code: str
    raw_row: Row
    message: str = ""

    def as_dict(self) -> Row:
        return {"entity": self.entity, "id": self.id, "status": "rejected", "reason_code": self.reason_code,
                "raw_row": self.raw_row}


@dataclass
class IngestResult:
    accepted: dict[str, list[Any]]                  # typed records by entity (merged invoices included)
    accepted_rows: dict[str, list[Row]]             # the same rows as given
    rejected: list[Rejection]
    merged_records: list[Row]
    merged_into: dict[str, str]
    groups_detected: int
    counts: dict[str, dict[str, int]]
    tolerances: Any
    export_requests: list[Any] = field(default_factory=list)

    def rejected_dicts(self) -> list[Row]:
        return [r.as_dict() for r in self.rejected]

    def population(self) -> Population:
        a = self.accepted
        return Population(vendors=list(a["vendors"]), purchase_orders=list(a["purchase_orders"]),
                          po_lines=list(a["po_lines"]), receipts=list(a["receipts"]), invoices=list(a["invoices"]),
                          credit_notes=list(a["credit_notes"]), approval_policies=list(a["approval_policies"]),
                          approvals=list(a["approvals"]), export_requests=list(self.export_requests),
                          tolerances=self.tolerances)


def _rid(row: Any, key: str) -> str:
    v = row.get(key) if isinstance(row, dict) else None
    return v if isinstance(v, str) else ""


def validate_batch(raw: dict[str, Any]) -> IngestResult:
    """Validate an inputs object (the shape of ``tests/fixtures/golden/inputs.json``)."""
    rej: list[Rejection] = []
    acc: dict[str, list[Any]] = {e: [] for e in ENTITIES}
    rows: dict[str, list[Row]] = {e: [] for e in ENTITIES}
    ids: dict[str, set[str]] = {e: set() for e in ENTITIES}

    def reject(ent: str, row: Any, code: str, msg: str = "") -> None:
        rej.append(Rejection(ent, _rid(row, ID_KEYS[ent]), code, row if isinstance(row, dict) else {"value": repr(row)}, msg))

    def parsed(ent: str, row: Any, fn: Callable[[Row], Any]) -> Any | None:
        """Parse + duplicate-id check; on failure the rejection is recorded and None returned."""
        if not isinstance(row, dict):
            reject(ent, row, MALFORMED_RECORD, "row must be an object")
            return None
        try:
            obj = fn(row)
        except DomainError as err:
            reject(ent, row, err.code, err.message)
            return None
        return obj

    def take(ent: str, row: Row, obj: Any) -> None:
        ids[ent].add(row[ID_KEYS[ent]])
        acc[ent].append(obj)
        rows[ent].append(row)

    def section(ent: str) -> list[Any]:
        v = raw.get(ent, [])
        return v if isinstance(v, list) else []

    try:
        tolerances = parse_tolerances(raw.get("tolerances"))
    except DomainError:
        tolerances = parse_tolerances(None)

    for r in section("vendors"):
        o = parsed("vendors", r, parse_vendor)
        if o is None:
            continue
        if o.vendor_id in ids["vendors"]:
            reject("vendors", r, DUPLICATE_ID, "vendor_id already loaded")
        else:
            take("vendors", r, o)
    for r in section("purchase_orders"):
        o = parsed("purchase_orders", r, parse_po)
        if o is None:
            continue
        if o.po_id in ids["purchase_orders"]:
            reject("purchase_orders", r, DUPLICATE_ID, "po_id already loaded")
        elif o.vendor_id not in ids["vendors"]:
            reject("purchase_orders", r, UNKNOWN_VENDOR)
        else:
            take("purchase_orders", r, o)
    for r in section("po_lines"):
        o = parsed("po_lines", r, parse_po_line)
        if o is None:
            continue
        if o.po_line_id in ids["po_lines"]:
            reject("po_lines", r, DUPLICATE_ID, "po_line_id already loaded")
        elif o.po_id not in ids["purchase_orders"]:
            reject("po_lines", r, UNKNOWN_PO)
        elif o.quantity <= 0:
            reject("po_lines", r, NON_POSITIVE_QUANTITY)
        else:
            take("po_lines", r, o)
    for r in section("receipts"):
        o = parsed("receipts", r, parse_receipt)
        if o is None:
            continue
        if o.receipt_id in ids["receipts"]:
            reject("receipts", r, DUPLICATE_ID, "receipt_id already loaded")
        elif o.po_line_id not in ids["po_lines"]:
            reject("receipts", r, UNKNOWN_PO_LINE)
        elif o.received_quantity <= 0:
            reject("receipts", r, NON_POSITIVE_QUANTITY)
        else:
            take("receipts", r, o)

    # --- invoices are atomic: a bad header, vendor or line rejects the header and every sibling line ------------------
    header_rows = [r for r in section("invoices")]
    header_ids = {_rid(r, "invoice_id") for r in header_rows if isinstance(r, dict)}
    lines_by_inv: dict[str, list[Row]] = {}
    for l in section("invoice_lines"):
        iid = _rid(l, "invoice_id")
        if not isinstance(l, dict) or iid not in header_ids:
            reject("invoice_lines", l, UNKNOWN_INVOICE if isinstance(l, dict) else MALFORMED_RECORD,
                   "no invoice with this id in the batch")
        else:
            lines_by_inv.setdefault(iid, []).append(l)
    seen_line_ids: set[str] = set()
    rejected_invoices: set[str] = set()
    for h in header_rows:
        if not isinstance(h, dict) or not _rid(h, "invoice_id"):
            reject("invoices", h, MALFORMED_RECORD, "invoice_id must be a non-empty string")
            continue
        iid = h["invoice_id"]
        if iid in ids["invoices"] or iid in rejected_invoices:
            reject("invoices", h, DUPLICATE_ID, "invoice_id already in the batch")
            continue
        ls = lines_by_inv.pop(iid, [])
        header_err: DomainError | None = None
        header: Invoice | None = None
        try:
            header = parse_invoice(h)
        except DomainError as err:
            header_err = err
        parsed_lines: list[InvoiceLine] = []
        line_codes: dict[int, str] = {}                  # index -> own reason
        for n, l in enumerate(ls):
            try:
                ln = parse_line(l)
            except DomainError as err:
                line_codes[n] = err.code
                continue
            if ln.quantity <= 0:
                line_codes[n] = NON_POSITIVE_QUANTITY
            elif ln.invoice_line_id in seen_line_ids:
                line_codes[n] = DUPLICATE_ID
            else:
                parsed_lines.append(ln)
                seen_line_ids.add(ln.invoice_line_id)
        if header_err is not None:
            code = header_err.code
        elif header.vendor_id not in ids["vendors"]:  # type: ignore[union-attr]
            code = UNKNOWN_VENDOR
        elif not ls:
            code = MALFORMED_RECORD
        elif line_codes:
            code = DEPENDENT_REJECTED
        else:
            code = ""
        if code:
            rejected_invoices.add(iid)
            reject("invoices", h, code, header_err.message if header_err else "")
            for n, l in enumerate(ls):
                reject("invoice_lines", l, line_codes.get(n, DEPENDENT_REJECTED))
            continue
        inv = parse_invoice(h, tuple(parsed_lines))
        take("invoices", h, inv)
        acc["invoice_lines"].extend(parsed_lines)
        rows["invoice_lines"].extend(ls)
        for ln in parsed_lines:
            ids["invoice_lines"].add(ln.invoice_line_id)
    for iid, ls in lines_by_inv.items():     # lines of a duplicated header id: attach to nothing
        for l in ls:
            reject("invoice_lines", l, DUPLICATE_ID, "its invoice_id was repeated in the batch")

    inv_by_id = {i.invoice_id: i for i in acc["invoices"]}
    credited: dict[str, Decimal] = {}
    for ent, fn in (("credit_notes", parse_credit), ("approvals", parse_approval)):
        for r in section(ent):
            o = parsed(ent, r, fn)
            if o is None:
                continue
            if o.invoice_id in rejected_invoices:
                reject(ent, r, DEPENDENT_REJECTED)
            elif o.invoice_id not in inv_by_id:
                reject(ent, r, UNKNOWN_INVOICE)
            elif _rid(r, ID_KEYS[ent]) in ids[ent]:
                reject(ent, r, DUPLICATE_ID)
            elif isinstance(o, CreditNote) and o.credit_amount <= 0:
                reject(ent, r, NON_POSITIVE_AMOUNT)
            elif isinstance(o, CreditNote) and (credited.get(o.invoice_id, Decimal(0)) + o.credit_amount
                                                > invoice_amounts(inv_by_id[o.invoice_id])[2]):
                reject(ent, r, CREDIT_EXCEEDS_INVOICE)
            else:
                if isinstance(o, CreditNote):
                    credited[o.invoice_id] = credited.get(o.invoice_id, Decimal(0)) + o.credit_amount
                take(ent, r, o)
    for r in section("approval_policies"):
        o = parsed("approval_policies", r, parse_policy)
        if o is None:
            continue
        if o.policy_id in ids["approval_policies"]:
            reject("approval_policies", r, DUPLICATE_ID)
        else:
            take("approval_policies", r, o)

    export_requests = []
    for r in section("export_requests"):
        try:
            export_requests.append(parse_export_request(r))
        except DomainError:
            continue                                  # not an ingest entity: a malformed request is ignored here
    rej.sort(key=lambda r: (r.entity, r.id))

    merged_into, merged_records, groups, _review = detect_duplicates(acc["invoices"])
    counts = {e: {"accepted": len(acc[e]), "rejected": sum(1 for r in rej if r.entity == e), "merged": 0} for e in ENTITIES}
    counts["invoices"]["accepted"] -= len(merged_into)
    counts["invoices"]["merged"] = len(merged_into)
    merged_lines = sum(len(inv_by_id[i].lines) for i in merged_into)
    counts["invoice_lines"]["accepted"] -= merged_lines
    counts["invoice_lines"]["merged"] = merged_lines
    return IngestResult(acc, rows, rej, merged_records, merged_into, groups, counts, tolerances, export_requests)
