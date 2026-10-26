"""Migrations are idempotent and the database enforces the money, immutability and append-only rules."""
from decimal import Decimal

import psycopg
import pytest

from data import migrate, seed

from support_db import conn, count, db_url, golden_inputs  # noqa: F401

TABLES = ["vendors", "purchase_orders", "po_lines", "receipts", "approval_policies", "tolerances", "invoices", "invoice_lines",
          "import_lineage", "match_results", "exceptions", "exception_assignments", "approvals", "credit_notes", "export_batches",
          "export_rows", "export_requests", "rejected_records", "audit_events", "command_results", "dataset_versions"]


@pytest.fixture
def golden(conn):
    seed.seed(conn, golden_inputs())
    return conn


def test_migrations_are_idempotent(db_url):
    with psycopg.connect(db_url) as c:
        assert migrate.apply_migrations(c) == []                      # the fixture already applied them
        migrate.reset(c)
        assert migrate.apply_migrations(c) == ["0001_schema.sql", "0002_constraints.sql", "0003_review_status.sql"]
        assert migrate.apply_migrations(c) == []
    for name in ("0001_schema.sql", "0002_constraints.sql", "0003_review_status.sql"):          # each file also re-runs cleanly
        with psycopg.connect(db_url) as c:
            c.execute((migrate.MIGRATIONS_DIR / name).read_text())


def test_reset_drops_everything_the_migrations_create(db_url):
    with psycopg.connect(db_url) as c:
        migrate.reset(c)
        left = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'").fetchone()[0]
        funcs = c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                          "WHERE n.nspname = 'public' AND p.proname LIKE 'ib\\_%'").fetchone()[0]
        seqs = c.execute("SELECT count(*) FROM pg_class WHERE relkind = 'S' AND relname = 'exception_seq'").fetchone()[0]
    assert (left, funcs, seqs) == (0, 0, 0)


def test_every_table_exists_and_instants_are_timestamptz(conn):
    names = {r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(TABLES) <= names
    bad = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND (column_name LIKE '%\\_at') AND data_type <> 'timestamp with time zone'").fetchall()
    assert bad == []


def test_money_and_quantities_are_exact_numeric_never_float(conn):
    rows = conn.execute("SELECT table_name, column_name, data_type, numeric_scale FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND data_type IN ('numeric', 'double precision', 'real')").fetchall()
    assert rows and not [r for r in rows if r["data_type"] != "numeric"]
    scale = {(r["table_name"], r["column_name"]): r["numeric_scale"] for r in rows}
    assert scale[("invoices", "total")] == 2 and scale[("invoice_lines", "quantity")] == 4
    assert scale[("invoice_lines", "unit_price")] == 6 and scale[("invoices", "tax_rate")] == 6


def test_changed_migration_is_detected(db_url, monkeypatch, tmp_path):
    (tmp_path / "0001_schema.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with psycopg.connect(db_url) as c, pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate.apply_migrations(c)


def test_seed_is_idempotent_and_records_rejected_rows(conn):
    first = seed.seed(conn, golden_inputs("variant-rejected"))
    assert first["skipped"] == 5 and first["inserted"]["invoices"] == 1 and first["inserted"]["approvals"] == 1
    again = seed.seed(conn, golden_inputs("variant-rejected"))
    assert sum(again["inserted"].values()) == 0 and again["dataset_version"] == first["dataset_version"]
    assert count(conn, "invoices") == 1 and count(conn, "rejected_records") == 5 and count(conn, "dataset_versions") == 1
    assert count(conn, "import_lineage") == 1 and count(conn, "export_requests") == 1
    assert conn.execute("SELECT count(*) AS n FROM rejected_records WHERE reason_code = 'DEPENDENT_REJECTED'").fetchone()["n"] == 3


def test_golden_seed_stores_the_derived_state_and_the_lineage(golden):
    inv = {r["invoice_id"]: r for r in golden.execute("SELECT * FROM invoices ORDER BY invoice_id").fetchall()}
    assert [inv[i]["status"] for i in ("inv-001", "inv-002", "inv-003")] == ["exported", "exception", "merged"]
    assert inv["inv-003"]["merged_into"] == "inv-001" and inv["inv-003"]["merge_reason"] == "DUPLICATE_IDENTITY"
    assert (inv["inv-001"]["subtotal"], inv["inv-001"]["tax"], inv["inv-001"]["total"]) == (Decimal("120.00"), Decimal("12.00"), Decimal("132.00"))
    lin = golden.execute("SELECT invoice_id, source_sha256, import_status FROM import_lineage ORDER BY lineage_id").fetchall()
    assert [(r["invoice_id"], r["import_status"]) for r in lin] == [("inv-001", "accepted"), ("inv-002", "accepted"), ("inv-003", "merged")]
    assert lin[2]["source_sha256"] == "3ccdec1f40078d08adffbefe342b727cc023fbe5e59c7090cb9723e205e31357"     # kept as lineage
    assert count(conn := golden, "export_requests") == 2 and count(conn, "export_batches") == 1 and count(conn, "export_rows") == 1


# --- the database refuses what the domain refuses --------------------------------------------------------------

@pytest.mark.parametrize("sql,kind", [
    ("UPDATE invoices SET total = 1 WHERE invoice_id = 'inv-001'", psycopg.errors.IntegrityError),               # the extracted source is immutable
    ("UPDATE invoices SET source_sha256 = repeat('a', 64) WHERE invoice_id = 'inv-001'", psycopg.errors.IntegrityError),
    ("UPDATE invoices SET imported_at = now() WHERE invoice_id = 'inv-001'", psycopg.errors.IntegrityError),
    ("DELETE FROM invoices WHERE invoice_id = 'inv-001'", psycopg.errors.IntegrityError),
    ("UPDATE invoice_lines SET quantity = 9 WHERE invoice_line_id = 'il-001'", psycopg.errors.IntegrityError),
    ("DELETE FROM invoice_lines WHERE invoice_line_id = 'il-001'", psycopg.errors.IntegrityError),
    ("UPDATE import_lineage SET import_status = 'rejected'", psycopg.errors.IntegrityError),                    # append-only lineage
    ("DELETE FROM import_lineage", psycopg.errors.IntegrityError),
    ("TRUNCATE import_lineage", psycopg.errors.IntegrityError),
    ("UPDATE approvals SET actor_id = 'x'", psycopg.errors.IntegrityError),
    ("DELETE FROM approvals", psycopg.errors.IntegrityError),
    ("UPDATE export_rows SET amount = 1", psycopg.errors.IntegrityError),
    ("DELETE FROM export_rows", psycopg.errors.IntegrityError),
    ("UPDATE receipts SET received_quantity = 99 WHERE receipt_id = 'rc-001'", psycopg.errors.IntegrityError),   # a receipt is only reversed
    ("DELETE FROM receipts", psycopg.errors.IntegrityError),
    ("UPDATE invoices SET status = 'paid' WHERE invoice_id = 'inv-001'", psycopg.errors.CheckViolation),         # nothing is ever 'paid'
    ("UPDATE invoices SET status = 'merged' WHERE invoice_id = 'inv-001'", psycopg.errors.CheckViolation),       # merged needs merged_into
    ("INSERT INTO credit_notes (credit_id, invoice_id, credit_amount) VALUES ('c', 'inv-001', 0)", psycopg.errors.CheckViolation),
    ("INSERT INTO credit_notes (credit_id, invoice_id, credit_amount) VALUES ('c', 'inv-001', -1)", psycopg.errors.CheckViolation),
    ("INSERT INTO credit_notes (credit_id, invoice_id, credit_amount) VALUES ('c', 'inv-zzz', 1)", psycopg.errors.ForeignKeyViolation),
    ("INSERT INTO receipts (receipt_id, po_line_id, received_quantity, received_at) VALUES ('r', 'pol-001', 0, now())", psycopg.errors.CheckViolation),
    ("INSERT INTO receipts (receipt_id, po_line_id, received_quantity, received_at) VALUES ('r', 'pol-999', 1, now())", psycopg.errors.ForeignKeyViolation),
    ("INSERT INTO po_lines VALUES ('p', 'po-001', 'X', -1, 1)", psycopg.errors.CheckViolation),
    ("INSERT INTO approvals (approval_id, invoice_id, actor_id, actor_role, decision, decided_at) VALUES ('a', 'inv-001', 'u', 'reviewer', 'reject', now())", psycopg.errors.CheckViolation),
    ("INSERT INTO approvals (approval_id, invoice_id, actor_id, actor_role, decision, decided_at) VALUES ('a', 'inv-001', 'u', 'reviewer', 'maybe', now())", psycopg.errors.CheckViolation),
    ("INSERT INTO export_rows VALUES ('e2', 'bat-001', 'inv-001', now(), 'v', 'n', '2026-10-06', 'USD', 1, repeat('a', 64))", psycopg.errors.UniqueViolation),   # an invoice exports once
    ("INSERT INTO export_rows VALUES ('e3', 'bat-001', 'inv-002', now(), 'v', 'n', '2026-10-06', 'USD', 1, 'short')", psycopg.errors.CheckViolation),
    ("INSERT INTO exceptions (exception_id, invoice_id, exception_type) VALUES ('x', 'inv-002', 'QUANTITY_BLOCKED')", psycopg.errors.UniqueViolation),   # one open exception per (invoice, type)
    ("INSERT INTO exceptions (exception_id, invoice_id, exception_type) VALUES ('x', 'inv-002', 'PAID')", psycopg.errors.CheckViolation),
    ("INSERT INTO import_lineage (invoice_id, source_sha256, source_filename, idempotency_key, imported_at, actor_id, import_status) VALUES ('i', 'zz', 'f', 'k', now(), 'a', 'accepted')", psycopg.errors.CheckViolation),
    ("INSERT INTO match_results (invoice_line_id, invoice_id, rule_version, status, reason_code) VALUES ('il-002', 'inv-002', '1', 'matched', 'QUANTITY_BLOCKED')", psycopg.errors.IntegrityError),
    ("INSERT INTO tolerances VALUES (2, 0, 0, 0)", psycopg.errors.CheckViolation),
])
def test_the_database_refuses(golden, sql, kind):
    with pytest.raises(kind):
        golden.execute(sql)


def test_a_receipt_can_be_reversed_and_only_that(golden):
    golden.execute("UPDATE receipts SET reversed = TRUE, reversed_at = now() WHERE receipt_id = 'rc-001'")
    assert golden.execute("SELECT reversed FROM receipts WHERE receipt_id = 'rc-001'").fetchone()["reversed"] is True
    with pytest.raises(psycopg.errors.IntegrityError):
        golden.execute("UPDATE receipts SET reversed = FALSE WHERE receipt_id = 'rc-001'")         # a reversal is not undone


def test_workflow_columns_of_an_invoice_may_move(golden):
    golden.execute("UPDATE invoices SET status = 'adjusted', version = version + 1 WHERE invoice_id = 'inv-001'")
    assert golden.execute("SELECT status FROM invoices WHERE invoice_id = 'inv-001'").fetchone()["status"] == "adjusted"
