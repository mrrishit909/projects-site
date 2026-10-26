"""Load a fixture ``inputs.json`` into the tables (idempotent: ``ON CONFLICT DO NOTHING``, guarded appends).

Usage:  DATABASE_URL=postgresql://... python data/seed.py tests/fixtures/golden/inputs.json [--reference-only] [--dataset-version V]

Rows go through the domain's ``validate_batch`` (the same rules as the API): rejected rows are kept in
``rejected_records`` with the raw row, merged invoices are stored with status ``merged`` and their lineage, and the
workflow state (status, validity, match results, exceptions, export batches) is the domain's derivation at the inputs'
``as_of``. ``--reference-only`` loads only the reference data (vendors, purchase orders, receipts, policies, tolerances,
the dataset version) so the API commands can drive the rest. Each load records one ``dataset_versions`` row whose
``dataset_hash`` is the sha256 of the canonical JSON of the inputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

for _p in (Path(__file__).resolve().parents[1] / "domain",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from invoicebridge import CONTRACT_VERSION, run_pipeline  # noqa: E402
from invoicebridge.amounts import invoice_amounts, normalise_number, validate_invoice  # noqa: E402
from invoicebridge.book import effective_policy  # noqa: E402
from invoicebridge.contract import RULE_VERSION  # noqa: E402


#: Entities ``--reference-only`` loads (the API commands bring the invoices, approvals, credits and exports).
REFERENCE_ENTITIES = ("vendors", "purchase_orders", "po_lines", "receipts", "approval_policies")


def canonical_json(obj: Any) -> str:
    """Canonical JSON used for every hash in the data layer."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def insert_rejected(conn: psycopg.Connection, batch_id: str, rejected: list[Any]) -> None:
    """Keep every rejected raw row; two occurrences of one id get different ordinals."""
    seen: dict[tuple[str, str, str], int] = {}
    for rej in rejected:
        k = (rej.entity, rej.id, rej.reason_code)
        n = seen[k] = seen.get(k, -1) + 1
        conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row, ordinal) "
                     "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (batch_id, rej.entity, rej.id, rej.reason_code, Jsonb(rej.raw_row), n))


def insert_reference(conn: psycopg.Connection, pop: Any) -> None:
    for v in pop.vendors:
        conn.execute("INSERT INTO vendors VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (v.vendor_id, v.vendor_name, v.tax_reference, v.currency, v.active))
    for p in pop.purchase_orders:
        conn.execute("INSERT INTO purchase_orders VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (p.po_id, p.vendor_id, p.ordered_at, p.status, p.currency))
    for l in pop.po_lines:
        conn.execute("INSERT INTO po_lines VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (l.po_line_id, l.po_id, l.product_code, l.quantity, l.unit_price))
    for r in pop.receipts:
        conn.execute("INSERT INTO receipts (receipt_id, po_line_id, received_quantity, received_at, reversed) "
                     "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (r.receipt_id, r.po_line_id, r.received_quantity, r.received_at, r.reversed))
    for p in pop.approval_policies:
        conn.execute("INSERT INTO approval_policies VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (p.policy_id, p.version_number, p.amount_limit, p.reviewer_role, p.escalation_role, p.effective_from))
    t = pop.tolerances
    conn.execute("INSERT INTO tolerances VALUES (1, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET price_per_unit = "
                 "EXCLUDED.price_per_unit, rounding_per_line = EXCLUDED.rounding_per_line, rounding_per_invoice = "
                 "EXCLUDED.rounding_per_invoice", (t.price_per_unit, t.rounding_per_line, t.rounding_per_invoice))


def seed(conn: psycopg.Connection, inputs: dict[str, Any], reference_only: bool = False,
         dataset_version: str | None = None) -> dict[str, Any]:
    """Seed one fixture; return ``{dataset_version, dataset_hash, inserted, skipped}``. ``dataset_version`` names the
    dataset as published (the generator's manifest ``dataset_version``, which the replay events carry); without it the
    version is ``ds-`` + the first 12 hex digits of the hash of the inputs."""
    res = run_pipeline(inputs)
    ing, pop, book = res.ingest, res.population, res.book
    dataset_hash = sha256_hex(canonical_json(inputs))
    version = dataset_version or f"ds-{dataset_hash[:12]}"
    insert_reference(conn, pop)
    inserted = {"invoices": 0, "invoice_lines": 0, "approvals": 0, "credit_notes": 0, "export_batches": 0,
                "export_rows": 0, "export_requests": 0, "exceptions": 0, "match_results": 0}
    if not reference_only:
        vendors = {v.vendor_id: v for v in pop.vendors}
        merge_reason = {r["id"]: r["reason_code"] for r in book.merged_records}    # the book at the as-of, not the batch's
        for inv in pop.invoices:
            sub, tax, total = invoice_amounts(inv)
            rules = validate_invoice(inv, vendors.get(inv.vendor_id))
            inserted["invoices"] += conn.execute(
                "INSERT INTO invoices (invoice_id, vendor_id, invoice_number, invoice_number_norm, invoice_date, currency, "
                "tax_rate, freight, invoice_discount, declared_total, subtotal, tax, total, created_by, source_sha256, "
                "source_filename, idempotency_key, imported_at, status, validity, validation_rules, merged_into, merge_reason) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (inv.invoice_id, inv.vendor_id, inv.invoice_number, normalise_number(inv.invoice_number), inv.invoice_date,
                 inv.currency, inv.tax_rate, inv.freight, inv.invoice_discount, inv.declared_total, sub, tax, total,
                 inv.created_by, inv.source_sha256, inv.source_filename, inv.idempotency_key, inv.imported_at,
                 book.status[inv.invoice_id], inv.valid, Jsonb([{"rule_id": r, "message": m} for r, m in rules]),
                 book.merged_into.get(inv.invoice_id), merge_reason.get(inv.invoice_id))).rowcount
            for l in inv.lines:
                inserted["invoice_lines"] += conn.execute(
                    "INSERT INTO invoice_lines VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (l.invoice_line_id, l.invoice_id, l.po_line_id, l.quantity, l.unit_price, l.line_amount)).rowcount
            conn.execute(
                "INSERT INTO import_lineage (invoice_id, source_sha256, source_filename, idempotency_key, imported_at, "
                "actor_id, import_status, reason_code, merged_into) SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s WHERE NOT EXISTS "
                "(SELECT 1 FROM import_lineage WHERE invoice_id = %s AND idempotency_key = %s)",
                (inv.invoice_id, inv.source_sha256, inv.source_filename, inv.idempotency_key, inv.imported_at,
                 inv.created_by, "merged" if inv.invoice_id in book.merged_into else "accepted",
                 merge_reason.get(inv.invoice_id) or ("BYTES_FIELDS_CONFLICT" if inv.invoice_id in book.review else None),
                 book.merged_into.get(inv.invoice_id), inv.invoice_id, inv.idempotency_key))
        for a in pop.approvals:
            pol = effective_policy(pop.approval_policies, a.decided_at)
            inserted["approvals"] += conn.execute(
                "INSERT INTO approvals VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (a.approval_id, a.invoice_id, a.actor_id, a.actor_role, a.decision, a.decided_at, a.reason,
                 pol.policy_id if pol else None, pol.version_number if pol else None)).rowcount
        for c in pop.credit_notes:
            inserted["credit_notes"] += conn.execute(
                "INSERT INTO credit_notes (credit_id, invoice_id, credit_amount, credited_at) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING", (c.credit_id, c.invoice_id, c.credit_amount, c.credited_at)).rowcount
        for r in res.book.run.lines:
            inserted["match_results"] += conn.execute(
                "INSERT INTO match_results (invoice_line_id, invoice_id, rule_version, status, reason_code, available_quantity, "
                "quantity_variance, price_variance, explanation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (r.invoice_line_id, r.invoice_id, RULE_VERSION, r.status, r.reason_code, r.available, r.quantity_variance,
                 r.price_variance, r.explanation)).rowcount
        for e in book.exceptions:
            inserted["exceptions"] += conn.execute(
                "INSERT INTO exceptions (exception_id, invoice_id, exception_type, status, owner_id) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING", (e["exception_id"], e["invoice_id"], e["exception_type"], e["status"], e["owner_id"])).rowcount
        # export: the requests as received (with their outcome), the batches and rows the domain created
        seen_k: set[str] = set()
        seen_b: set[str] = set()
        seen_req: dict[tuple, int] = {}
        for r in pop.export_requests:
            repeat = r.idempotency_key in seen_k or r.batch_id in seen_b
            seen_k.add(r.idempotency_key)
            seen_b.add(r.batch_id)
            outcome = "returned_prior" if repeat else "created"
            ident = (r.batch_id, r.idempotency_key, tuple(r.invoice_ids), r.exported_at, outcome)
            seen_req[ident] = seen_req.get(ident, 0) + 1
            have = conn.execute("SELECT count(*) AS n FROM export_requests WHERE batch_id = %s AND idempotency_key = %s AND "
                                "invoice_ids = %s AND exported_at = %s AND outcome = %s AND requested_by = 'seed'",
                                (r.batch_id, r.idempotency_key, list(r.invoice_ids), r.exported_at, outcome)).fetchone()["n"]
            if have < seen_req[ident]:       # loading twice adds nothing; two identical requests in one file are both kept
                inserted["export_requests"] += conn.execute(
                    "INSERT INTO export_requests (batch_id, idempotency_key, invoice_ids, exported_at, outcome, requested_by) "
                    "VALUES (%s,%s,%s,%s,%s,'seed')", (r.batch_id, r.idempotency_key, list(r.invoice_ids), r.exported_at, outcome)).rowcount
            if not repeat:
                rows = [x for x in book.export_rows if x["batch_id"] == r.batch_id]
                inserted["export_batches"] += conn.execute(
                    "INSERT INTO export_batches (batch_id, idempotency_key, requested_by, exported_at, row_count, total) "
                    "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (r.batch_id, r.idempotency_key, "seed", r.exported_at, len(rows),
                     sum((Decimal(x["amount"]) for x in rows), Decimal(0)))).rowcount
                for x in rows:
                    inserted["export_rows"] += conn.execute(
                        "INSERT INTO export_rows VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (x["export_id"], x["batch_id"], x["invoice_id"], r.exported_at, x["vendor_id"], x["invoice_number"],
                         x["invoice_date"], x["currency"], x["amount"], x["content_hash"])).rowcount
    wanted = [r for r in ing.rejected if not reference_only or r.entity in REFERENCE_ENTITIES]
    if wanted:
        insert_rejected(conn, f"batch-seed-{dataset_hash[:16]}", wanted)
    conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version) "
                 "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (version, dataset_hash, str(CONTRACT_VERSION)))
    return {"dataset_version": version, "dataset_hash": dataset_hash, "inserted": inserted, "skipped": len(wanted)}


def main(argv: list[str]) -> int:
    url = os.environ.get("DATABASE_URL")
    version = None
    if "--dataset-version" in argv:
        k = argv.index("--dataset-version")
        version = argv[k + 1] if k + 1 < len(argv) else None
        argv = argv[:k] + argv[k + 2:]
    args = [a for a in argv if not a.startswith("--")]
    if not url or len(args) != 1:
        print("usage: DATABASE_URL=... python data/seed.py <inputs.json> [--reference-only] [--dataset-version V]", file=sys.stderr)
        return 2
    inputs = json.loads(Path(args[0]).read_text())
    with psycopg.connect(url) as conn:
        print(json.dumps(seed(conn, inputs, "--reference-only" in argv, version), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
