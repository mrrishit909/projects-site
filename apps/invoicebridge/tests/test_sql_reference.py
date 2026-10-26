"""data/sql/reference_metrics.sql recomputes every metric from the facts, independently of the Python domain and of any stored
status, and equals expected.json on the fixtures and the domain on any loaded population."""
import json
from pathlib import Path

import psycopg
import pytest

from data import seed
from invoicebridge import run_pipeline
from invoicebridge.contract import METRIC_KEYS
from invoicebridge.timeutil import parse_ts

from support_db import World, conn, db_url, golden_expected, golden_inputs, random_world, sha  # noqa: F401

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()


def reference(conn, inputs):
    return conn.execute(SQL, {"as_of": parse_ts(inputs["as_of"]), "cutoffs": [parse_ts(c) for c in inputs["snapshot_cutoffs"]]}).fetchone()


@pytest.mark.parametrize("variant", ["", "variant-rejected", "variant-empty"])
def test_sql_equals_expected_for_every_fixture(conn, variant):
    inputs = golden_inputs(variant)
    seed.seed(conn, inputs)
    row = reference(conn, inputs)
    want = golden_expected(variant)["metrics"]
    assert set(row) == set(want) == set(METRIC_KEYS)
    for k in METRIC_KEYS:
        assert row[k] == want[k], k


@pytest.mark.parametrize("variant", ["", "variant-rejected", "variant-empty"])
def test_sql_is_independent_of_every_stored_status_and_derived_column(conn, variant):
    """Scramble what the commands store (status, merge flags, totals, match results, exceptions): the SQL does not read them."""
    inputs = golden_inputs(variant)
    seed.seed(conn, inputs)
    with conn.transaction():
        conn.execute("ALTER TABLE invoices DISABLE TRIGGER invoices_source_fixed")
        conn.execute("UPDATE invoices SET status = 'received', merged_into = NULL, merge_reason = NULL, subtotal = 1, tax = 1, total = 1, "
                     "invoice_number_norm = 'X'")
        conn.execute("ALTER TABLE invoices ENABLE TRIGGER invoices_source_fixed")
        conn.execute("UPDATE match_results SET status = 'matched', reason_code = NULL")
        conn.execute("UPDATE exceptions SET status = 'resolved'")
    row = reference(conn, inputs)
    for k, v in golden_expected(variant)["metrics"].items():
        assert row[k] == v, k


def test_sql_reads_only_facts_not_the_stored_exception_owner_column(conn):
    inputs = golden_inputs()
    seed.seed(conn, inputs)
    conn.execute("UPDATE exceptions SET status = 'assigned', owner_id = 'someone'")        # not backed by an assignment row
    assert reference(conn, inputs)["exceptions"]["records"][0]["owner_id"] is None
    conn.execute("INSERT INTO exception_assignments (exception_id, owner_id, assigned_by, assigned_at) "
                 "VALUES ('exc-001', 'usr-owner', 'usr-clerk01', '2026-10-08T00:00:00Z')")
    rec = reference(conn, inputs)["exceptions"]
    assert (rec["unowned_count"], rec["records"][0]["owner_id"], rec["records"][0]["status"]) == (0, "usr-owner", "assigned")
    early = conn.execute(SQL, {"as_of": parse_ts("2026-10-07T00:00:00Z"), "cutoffs": []}).fetchone()["exceptions"]
    assert early["records"][0]["owner_id"] is None or early["open_count"] == 0            # as of a cutoff before the assignment


def test_sql_values_for_the_spec_sentence(conn):
    inputs = golden_inputs()
    seed.seed(conn, inputs)
    row = reference(conn, inputs)
    assert row["obligations"] == {"count": 1, "total": "132.00"}
    assert row["quantities"]["invoiced_not_received_value"] == "80.00"
    assert row["rates"] == {"eligible_invoices": 2, "straight_through_rate": "0.500000", "exception_rate": "0.500000"}
    assert row["export"]["rows"][0]["content_hash"] == "7776efc65bc163e1b9a09ab336a0fcd12b52aba6ccfdefe49c06baf0b3df6779"


def rich_world() -> dict:
    """Every rule at once: cumulative blocks, two currencies, price and rounding differences, both duplicate kinds, a reversed
    receipt, a rejection, self-approval, a limit, an escalation, a credit, repeated exports and two snapshot cutoffs."""
    w = World(price_per_unit="0.05")
    w.pol("p1", qty="40", price="20.00")
    w.pol("p2", qty="10", price="100.125")
    w.pol("pe", po="po-2", qty="20", price="3.00")
    for pl, q, at, rev in (("p1", "10", "2026-10-02T10:00:00Z", False), ("p1", "5", "2026-10-04T10:00:00Z", True), ("p1", "20", "2026-10-09T10:00:00Z", False),
                           ("p2", "4", "2026-10-03T10:00:00Z", False), ("pe", "20", "2026-10-03T10:00:00Z", False)):
        w.receipt(pl, q, at=at, reversed=rev)
    w.invoice("inv-01", [("a1", "p1", "6", "20.00"), ("a2", "p2", "1.5", "100.125")], number="A-1", at="2026-10-05T09:00:00Z", date="2026-10-05")
    w.invoice("inv-02", [("b1", "p1", "6", "20.04")], number="A-2", at="2026-10-05T09:05:00Z", date="2026-10-05")           # price within tolerance
    w.invoice("inv-03", [("c1", "p1", "6", "20.50")], number="A-3", at="2026-10-05T09:10:00Z", date="2026-10-05")           # price variance
    w.invoice("inv-04", [("d1", "p1", "4", "20.00")], number="A-4", at="2026-10-06T09:00:00Z", date="2026-10-06", declared="88.03")   # rounding
    w.invoice("inv-05", [("e1", "pe", "5", "3.00")], number="E-1", vendor="ven-2", currency="EUR", at="2026-10-06T10:00:00Z", date="2026-10-06")
    w.invoice("inv-06", [("f1", "pe", "5", "3.00")], number="E-2", vendor="ven-2", currency="USD", at="2026-10-06T11:00:00Z", date="2026-10-06")   # currency mismatch
    w.invoice("inv-07", [("g1", "p-ghost", "1", "1.00")], number="G-1", at="2026-10-06T12:00:00Z", date="2026-10-06")        # no PO line
    w.invoice("inv-08", [("h1", "p1", "6", "20.00")], number="a 1", at="2026-10-07T09:00:00Z", date="2026-10-05")             # identity duplicate of inv-01? no: other total
    w.invoice("inv-09", [("i1", "p1", "4", "20.00"), ("i2", "p1", "4", "20.00")], number="A-9", at="2026-10-07T10:00:00Z", date="2026-10-07")
    w.invoice("inv-10", [("j1", "p1", "1", "20.00")], number="A-10", at="2026-10-08T10:00:00Z", date="2026-10-08", digest=sha("dupe"))
    w.invoice("inv-11", [("k1", "p1", "1", "20.00")], number="A-10", at="2026-10-08T11:00:00Z", date="2026-10-08", digest=sha("dupe"))   # same bytes and identity: merged
    w.invoice("inv-13", [("n1", "p2", "1", "100.125")], number="M-9", at="2026-10-09T10:00:00Z", date="2026-10-09", digest=sha("bytes-inv-12"))   # the bytes of inv-12, other fields: held for review
    w.invoice("inv-12", [("m1", "p2", "9", "100.125")], number="M-1", at="2026-10-09T09:00:00Z", date="2026-10-09")           # quantity blocked
    w.approve("inv-01", actor="usr-clerk01", role="reviewer", at="2026-10-06T10:00:00Z")      # self-approval
    w.approve("inv-01", actor="usr-rev01", at="2026-10-06T11:00:00Z")
    w.approve("inv-03", actor="usr-rev01", role="clerk", at="2026-10-06T11:00:00Z")           # wrong role (and not matched)
    w.approve("inv-02", actor="usr-rev01", decision="reject", reason="not ours", at="2026-10-06T12:00:00Z")
    w.approve("inv-04", actor="usr-rev01", at="2026-10-06T13:00:00Z")                         # not matched
    w.approve("inv-10", actor="usr-adm01", role="admin", at="2026-10-09T13:00:00Z")
    w.credit("cn-1", "inv-01", "50.00")
    w.credit("cn-2", "inv-10", "5.00")
    w.export("bat-1", "k1", ["inv-01", "inv-10", "inv-02"], at="2026-10-10T08:00:00Z")
    w.export("bat-1", "k1", ["inv-01"], at="2026-10-10T08:00:30Z")
    w.export("bat-2", "k2", ["inv-10"], at="2026-10-11T08:00:00Z")
    d = w.data()
    d["snapshot_cutoffs"] = ["2026-10-03T12:00:00Z", "2026-10-06T00:00:00Z", "2026-10-26T00:00:00Z"]
    return d


@pytest.mark.parametrize("as_of", ["2026-10-26T00:00:00Z", "2026-10-06T12:00:00Z", "2026-10-09T00:00:00Z", "2026-10-02T00:00:00Z"])
def test_sql_equals_the_domain_on_a_rich_population(conn, as_of):
    d = rich_world()
    d["as_of"] = as_of
    res = run_pipeline(d)
    seed.seed(conn, d)
    row = reference(conn, d)
    for k in METRIC_KEYS:
        assert row[k] == res.metrics[k], k
    if as_of == "2026-10-26T00:00:00Z":              # the world really exercises the rules
        m = res.metrics
        assert m["approvals"]["valid_count"] >= 2 and len(m["approvals"]["invalid_records"]) >= 3
        assert {c for c, n in m["exceptions"]["by_reason"].items() if n} >= {"PRICE_VARIANCE", "QUANTITY_BLOCKED", "NO_PO_LINE", "CURRENCY_MISMATCH", "ROUNDING_EXCEPTION"}
        assert m["duplicates"]["rows_merged"] == 1 and m["payable"]["credit_total"] != "0.00" and m["export"]["repeat_requests_returned_prior"] == 1


@pytest.mark.parametrize("start", range(0, 120, 20))
def test_sql_equals_the_domain_on_random_populations(conn, start):
    """Seeded random populations (cumulative consumption, several lines, currencies, duplicates, reversals, approvals,
    rejections, exports, credits, cutoffs); each one is loaded in a transaction that is rolled back."""
    for s in range(start, start + 20):
        d = random_world(s)
        res = run_pipeline(d)
        with conn.transaction():                      # psycopg.Rollback ends the block and discards the load
            seed.seed(conn, d)
            row = reference(conn, d)
            diffs = [k for k in METRIC_KEYS if row[k] != res.metrics[k]]
            assert not diffs, (s, diffs)
            raise psycopg.Rollback()


def test_sql_collation_independent_ordering(conn):
    """Ids that sort differently under a locale and under code points still agree with Python (COLLATE "C")."""
    w = World()
    w.pol("p1", qty="100", price="1.00")
    w.receipt("p1", "100")
    for iid in ("inv-B", "inv-a", "inv_c", "inv-Z"):
        w.invoice(iid, [(f"l-{iid}", "p1", "1", "9.99")], number=iid, at="2026-10-06T09:00:00Z")      # price variance on each: 4 exceptions
    d = w.data()
    res = run_pipeline(d)
    seed.seed(conn, d)
    row = reference(conn, d)
    assert [r["invoice_id"] for r in row["exceptions"]["records"]] == [r["invoice_id"] for r in res.metrics["exceptions"]["records"]] == ["inv-B", "inv-Z", "inv-a", "inv_c"]
    assert row["exceptions"] == res.metrics["exceptions"]


# --- the review cases (A-038, findings R5-xx): one set of hand-derived expectations for Python, SQL and TypeScript ------------

from test_review_findings import CASES as REVIEW_CASES, subset  # noqa: E402


@pytest.mark.parametrize("name", sorted(REVIEW_CASES))
def test_sql_meets_the_hand_derived_review_expectations_and_equals_the_domain(conn, name):
    """D-09: committed-first consumption, per-cutoff duplicates, held byte-twins, vendor mismatch, SELF_DECISION, BEFORE_IMPORT,
    EXPORT_BEFORE_APPROVAL / APPROVED_NOT_EXPORTED, by_currency and the history rates, each as the SQL reference recomputes them."""
    case = REVIEW_CASES[name]
    d = case["inputs"]
    seed.seed(conn, d)
    for e in (case.get("stored") or {}).get("exceptions", []):             # the stored history (a resolved exception is history, not backlog)
        conn.execute("INSERT INTO exceptions (exception_id, invoice_id, exception_type, status) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (e["exception_id"], e["invoice_id"], e["exception_type"], e["status"]))
    row = reference(conn, d)
    subset(dict(row), case["expect"].get("metrics", {}), "sql")
    if not case.get("stored"):
        res = run_pipeline(d)
        for k in METRIC_KEYS:
            assert row[k] == res.metrics[k], k
    for path, keys in case.get("exact_keys", {}).items():
        node = dict(row)
        for part in path.split(".")[1:]:
            node = node[part]
        assert sorted(node) == keys, path


def test_sql_by_currency_is_absent_for_one_currency_and_present_for_two(conn):
    seed.seed(conn, golden_inputs())
    one = reference(conn, golden_inputs())
    assert all("by_currency" not in one[k] for k in ("matched", "obligations", "payable", "export"))
    d = REVIEW_CASES["byte_twin_with_other_fields_and_two_currencies"]["inputs"]
    with conn.transaction():
        seed.seed(conn, d)
        two = reference(conn, d)
        assert sorted(two["matched"]["by_currency"]) == ["EUR", "USD"] and sorted(two["export"]["by_currency"]) == ["EUR", "USD"]
        raise psycopg.Rollback()
