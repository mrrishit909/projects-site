"""Adversarial scenarios for every D-05 "not yet pinned by a fixture row" item and the injected defects of the data generator
(docs/data-generator.md), end to end through the API and the database; races run on real threads."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api.app import PREFIX, create_app

from support_db import (CLERK, REVIEWER, Desk, actor, client, conn, count, current_dataset_version, db_url, rule_ids, sha)  # noqa: F401


@pytest.fixture
def desk(client, conn):
    return Desk(client, conn)


def metrics(desk, **params):
    return desk.client.get(f"{PREFIX}/metrics", params=params).json()["data"]["metrics"]


def race(n, fn):
    """Run ``fn(i, client)`` on ``n`` threads released together; each thread has its own client. Returns the results in order."""
    gate = threading.Barrier(n)
    clients = [TestClient(create_app(), raise_server_exceptions=False) for _ in range(n)]

    def run(i):
        gate.wait()
        return fn(i, clients[i])
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


def post(client, name, input_, headers, key, version):
    return client.post(f"{PREFIX}/commands/{name}", headers=headers,
                       json={"request_id": f"req-{key}", "dataset_version": version, "idempotency_key": key, "input": input_})


# --- same bytes, identity, tax and rounding ---------------------------------------------------------------------

def test_same_bytes_under_two_filenames_leave_one_obligation(desk):
    """The injected defect: the same PDF under two filenames. One obligation, one received quantity consumed."""
    desk.ready("inv-1", source_filename="a.pdf")
    dup = desk.imp("inv-2", [("l2", "pol-1", "6", "20.00")], source_sha256=sha("bytes-inv-1"), source_filename="b-copy.pdf", invoice_number="INV-1")
    assert dup.json()["status"] == "merged"
    desk.approve("inv-1")
    m = metrics(desk)
    assert (m["obligations"]["count"], m["obligations"]["total"], m["quantities"]["accepted_invoiced_quantity"]) == (1, "132.00", "6.0000")
    assert (m["duplicates"]["groups_detected"], m["duplicates"]["rows_merged"]) == (1, 1)
    assert desk.conn.execute("SELECT count(*) AS n FROM invoices WHERE source_sha256 = %s", (sha("bytes-inv-1"),)).fetchone()["n"] == 2   # both kept as lineage


def test_a_reused_invoice_number_across_vendors_is_not_a_duplicate(client, conn):
    w = Desk.default_world()
    w.pol("pol-e", po="po-2", qty="10", price="20.00")
    w.receipt("pol-e", "6")
    d = Desk(client, conn, w)
    d.ready("inv-1", invoice_number="INV-1001")
    d.ready("inv-2", [("l2", "pol-e", "6", "20.00")], invoice_number="INV-1001", vendor_id="ven-2", currency="EUR")
    assert d.post("find-duplicates", {"invoice_id": "inv-2"}).json()["result"]["candidates"] == []
    assert metrics(d)["duplicates"]["rows_merged"] == 0 and metrics(d)["matched"]["invoice_count"] == 2


def test_multi_line_tax_is_computed_once_per_invoice_not_per_line(desk):
    r = desk.imp("inv-1", [("l1", "pol-1", "1", "0.05"), ("l2", "pol-1", "1", "0.05"), ("l3", "pol-1", "1", "0.05")])
    res = r.json()["result"]
    assert (res["subtotal"], res["tax"], res["total"]) == ("0.15", "0.02", "0.17")        # per line it would be 0.03 tax
    row = desk.conn.execute("SELECT subtotal, tax, total FROM invoices").fetchone()
    assert (str(row["subtotal"]), str(row["tax"]), str(row["total"])) == ("0.15", "0.02", "0.17")


@pytest.mark.parametrize("lines,sub,tax,total", [
    ([("l1", "pol-1", "1", "10.125")], "10.13", "1.01", "11.14"),         # 10.125 -> 10.13 (half up, not banker's), tax 1.0125 -> 1.01
    ([("l1", "pol-1", "0.5", "0.01")], "0.01", "0.00", "0.01"),           # 0.005 -> 0.01
    ([("l1", "pol-1", "2.5", "0.202")], "0.51", "0.05", "0.56")])         # 0.505 -> 0.51, tax 0.0505 -> 0.05
def test_rounding_ties_round_half_up_in_the_stored_amounts(desk, lines, sub, tax, total):
    res = desk.imp("inv-1", lines, declared_total=total).json()["result"]
    assert (res["subtotal"], res["tax"], res["total"], res["rounding_difference"]) == (sub, tax, total, "0.00")


def test_a_rounding_gap_over_tolerance_is_a_rounding_exception_and_within_tolerance_is_disclosed(desk):
    desk.ready("inv-1", [("l1", "pol-1", "5", "20.00")], declared_total="110.02")      # computed 110.00: 0.02 off, tolerated
    assert desk.status("inv-1") == "matched" and metrics(desk)["matched"]["total"] == "110.00"
    disc = desk.client.get(f"{PREFIX}/metrics").json()["data"]["disclosures"]["rounding_tolerated_invoices"]
    assert disc == [{"invoice_id": "inv-1", "rounding_difference": "0.02"}]
    bad = desk.ready("inv-2", [("l2", "pol-1", "0.1", "20.00")], declared_total="2.25")      # 2.20 computed: 0.05 off
    assert bad["status"] == "exception" and [e["exception_type"] for e in bad["exceptions"]] == ["ROUNDING_EXCEPTION"]
    assert bad["rounding_difference"] == "0.05"


# --- price, currency and PO line --------------------------------------------------------------------------------

@pytest.mark.parametrize("tol,price,status", [("0.05", "20.05", "matched"), ("0.05", "20.06", "exception"), ("0.00", "20.01", "exception"),
                                              ("0.05", "19.94", "exception")])
def test_price_variance_within_and_beyond_the_tolerance(client, conn, tol, price, status):
    w = Desk.default_world()
    w.d["tolerances"]["price_per_unit"] = tol
    d = Desk(client, conn, w)
    res = d.ready("inv-1", [("l1", "pol-1", "1", price)])
    assert res["status"] == status
    if status == "exception":
        assert res["lines"][0]["reason_code"] == "PRICE_VARIANCE" and [e["exception_type"] for e in res["exceptions"]] == ["PRICE_VARIANCE"]
    assert metrics(d)["exceptions"]["by_reason"]["PRICE_VARIANCE"] == (0 if status == "matched" else 1)


def test_a_foreign_currency_invoice_without_a_rate_is_a_currency_mismatch(desk):
    res = desk.ready("inv-1", currency="EUR")
    assert res["status"] == "exception" and res["lines"][0]["reason_code"] == "CURRENCY_MISMATCH"
    assert res["lines"][0]["available_quantity"] is None and res["lines"][0]["price_variance"] is None       # never compared
    assert metrics(desk)["exceptions"]["by_reason"]["CURRENCY_MISMATCH"] == 1 and metrics(desk)["quantities"]["accepted_invoiced_quantity"] == "0.0000"


def test_a_line_naming_no_po_line_is_no_po_line(desk):
    res = desk.ready("inv-1", [("l1", "pol-1", "1", "20.00"), ("l2", "pol-ghost", "1", "5.00")])
    assert res["status"] == "exception" and [x["reason_code"] for x in res["lines"]] == [None, "NO_PO_LINE"]
    assert metrics(desk)["exceptions"]["by_reason"]["NO_PO_LINE"] == 1 and metrics(desk)["quantities"]["accepted_invoiced_quantity"] == "0.0000"


def test_partial_receipts_and_cumulative_consumption_block_the_second_invoice(desk):
    desk.ready("inv-1", [("l1", "pol-1", "4", "20.00")])
    res = desk.ready("inv-2", [("l2", "pol-1", "4", "20.00")])          # 6 received - 4 consumed = 2 available
    assert res["status"] == "exception" and res["lines"][0]["available_quantity"] == "2.0000" and res["lines"][0]["quantity_variance"] == "2.0000"
    m = metrics(desk)
    assert (m["quantities"]["invoiced_not_received_quantity"], m["quantities"]["invoiced_not_received_value"]) == ("2.0000", "40.00")


# --- approval, credits, paid, corrections -----------------------------------------------------------------------

def test_self_approval_is_refused_and_leaves_the_invoice_matched(desk):
    assert desk.imp("inv-1", who=actor("usr-rev01", "reviewer")).status_code == 200      # a reviewer may import ...
    desk.post("validate-invoice", {"invoice_id": "inv-1"}, REVIEWER)
    desk.post("match-three-way", {"invoice_id": "inv-1"}, REVIEWER)
    r = desk.approve("inv-1", who=REVIEWER)               # ... but never approve what they imported
    assert r.status_code == 403 and r.json()["error"]["code"] == "SELF_APPROVAL" and desk.status("inv-1") == "matched"
    assert metrics(desk)["obligations"]["count"] == 0


def test_a_credit_note_applies_once_even_when_sent_again_under_new_keys(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    body = {"credit_id": "cn-1", "invoice_id": "inv-1", "credit_amount": "12.00"}
    codes = [desk.post("apply-credit-note", body, REVIEWER).status_code for _ in range(3)]       # three fresh idempotency keys
    assert codes == [200, 409, 409] and count(desk.conn, "credit_notes") == 1
    assert metrics(desk)["payable"] == {"approved_total": "132.00", "credit_total": "12.00", "approved_payable": "120.00"}
    other = {"credit_id": "cn-2", "invoice_id": "inv-1", "credit_amount": "1.00"}
    first = desk.post("apply-credit-note", other, REVIEWER, key="cn-key")
    replay = desk.post("apply-credit-note", other, REVIEWER, key="cn-key")
    assert first.status_code == 200 and replay.headers.get("Idempotent-Replay") == "true" and replay.json() == first.json()
    assert count(desk.conn, "credit_notes") == 2 and metrics(desk)["payable"]["credit_total"] == "13.00"


def test_a_paid_flag_attempt_is_refused_and_no_command_can_mark_an_invoice_paid(desk):
    desk.ready("inv-1")
    for name, body in (("import-invoice", {"paid": True}), ("approve-invoice", {"invoice_id": "inv-1", "paid": True}),
                       ("export-payable", {"batch_id": "b", "invoice_ids": ["inv-1"], "status": "paid"})):
        r = desk.post(name, body, REVIEWER if name != "import-invoice" else CLERK)
        assert r.status_code == 422 and ("FIELD_UNEXPECTED" in rule_ids(r) or "FIELD_REQUIRED" in rule_ids(r))
    assert desk.conn.execute("SELECT count(*) AS n FROM invoices WHERE status = 'paid'").fetchone()["n"] == 0
    assert "paid" not in str(desk.client.get(f"{PREFIX}/openapi.json").json()["paths"].keys())


def test_a_correction_never_overwrites_the_original_extraction(desk):
    desk.imp("inv-1")
    assert desk.post("correct-extraction", {"invoice_id": "inv-1", "declared_total": "1.00"}).status_code == 501      # C06 is an extension
    import psycopg
    with pytest.raises(psycopg.errors.IntegrityError):                       # and the database would refuse the overwrite anyway
        desk.conn.execute("UPDATE invoices SET declared_total = 1.00 WHERE invoice_id = 'inv-1'")
    with pytest.raises(psycopg.errors.IntegrityError):
        desk.conn.execute("UPDATE invoice_lines SET quantity = 1 WHERE invoice_id = 'inv-1'")


def test_a_reversed_receipt_after_approval_flags_the_approval_and_drops_the_obligation(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    assert metrics(desk)["obligations"]["count"] == 1
    desk.conn.execute("UPDATE receipts SET reversed = TRUE, reversed_at = now() WHERE receipt_id = 'rc-001'")
    body = desk.client.get(f"{PREFIX}/metrics").json()
    m = body["data"]["metrics"]
    assert m["obligations"]["count"] == 0 and m["approvals"]["invalid_records"][0]["reason_code"] == "NOT_MATCHED"
    assert m["exceptions"]["by_reason"]["QUANTITY_BLOCKED"] == 1 and m["quantities"]["net_received_quantity"] == "0.0000"
    assert body["warnings"][0]["code"] == "WORKFLOW_STATE_DIFFERS"           # the stored state is behind: re-match it
    again = desk.post("match-three-way", {"invoice_id": "inv-1"})
    assert again.status_code == 409                                          # an approved invoice is not re-matched
    r = domain_equals_sql(desk)
    assert r["approvals"]["invalid_records"] == m["approvals"]["invalid_records"]


def domain_equals_sql(desk):
    """The SQL reference equals the API's (domain) metrics on whatever the commands left in the database."""
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
    from invoicebridge.timeutil import parse_ts
    row = desk.conn.execute(sql, {"as_of": parse_ts("2999-01-01T00:00:00Z"), "cutoffs": []}).fetchone()
    api = metrics(desk)
    for k in row:
        if k != "snapshots":
            assert row[k] == api[k], k
    return row


def test_sql_reference_equals_the_api_after_a_full_workflow(desk):
    desk.ready("inv-1", [("l1", "pol-1", "4", "20.00")])
    desk.ready("inv-2", [("l2", "pol-1", "4", "20.00")])
    desk.approve("inv-1")
    desk.post("apply-credit-note", {"credit_id": "cn", "invoice_id": "inv-1", "credit_amount": "10.00"}, REVIEWER)
    desk.post("export-payable", {"batch_id": "b1", "invoice_ids": ["inv-1"]}, REVIEWER)
    desk.post("assign-exception", {"exception_id": "exc-001", "owner_id": "usr-o"})
    domain_equals_sql(desk)


# --- stale state ------------------------------------------------------------------------------------------------

def test_a_stale_dataset_version_is_409_for_every_command(desk):
    desk.ready("inv-1")
    for name, body, who in (("approve-invoice", {"invoice_id": "inv-1"}, REVIEWER), ("match-three-way", {"invoice_id": "inv-1"}, CLERK),
                            ("export-payable", {"batch_id": "b", "invoice_ids": ["inv-1"]}, REVIEWER)):
        r = desk.post(name, body, who, dataset_version="ds-stale")
        assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_DATASET_VERSION"
    assert desk.status("inv-1") == "matched"
    desk.conn.execute("INSERT INTO dataset_versions (dataset_version, dataset_hash, contract_version, created_at) VALUES ('ds-newer', 'h', '1', now() + interval '1 hour')")
    r = desk.post("approve-invoice", {"invoice_id": "inv-1"}, REVIEWER, dataset_version="ds-old")
    assert r.status_code == 409 and r.json()["error"]["details"][0]["context"]["current"] == "ds-newer"


# --- races ------------------------------------------------------------------------------------------------------

def test_two_concurrent_approvals_leave_exactly_one_approval(desk):
    desk.ready("inv-1")
    version = current_dataset_version()
    who = [actor("usr-rev01", "reviewer"), actor("usr-rev02", "reviewer")]
    results = race(2, lambda i, c: post(c, "approve-invoice", {"invoice_id": "inv-1"}, who[i], f"race-approve-{i}", version))
    assert sorted(r.status_code for r in results) == [200, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "INVALID_STATE"
    rows = desk.conn.execute("SELECT actor_id FROM approvals").fetchall()
    assert len(rows) == 1 and desk.status("inv-1") == "approved"
    assert count(desk.conn, "audit_events") == 4                       # import, validate, match, the one approval
    assert metrics(desk)["approvals"]["valid_count"] == 1


def test_many_concurrent_approvals_from_many_threads_still_leave_one(desk):
    desk.ready("inv-1")
    version = current_dataset_version()
    results = race(6, lambda i, c: post(c, "approve-invoice", {"invoice_id": "inv-1"}, actor(f"usr-rev{i + 10}", "reviewer"), f"many-{i}", version))
    codes = sorted(r.status_code for r in results)
    assert codes == [200] + [409] * 5 and count(desk.conn, "approvals") == 1


def test_the_same_idempotency_key_sent_concurrently_runs_once(desk):
    version = current_dataset_version()
    body = {"invoice_id": "inv-1", "vendor_id": "ven-1", "invoice_number": "INV-1", "invoice_date": "2026-10-06", "currency": "USD",
            "tax_rate": "0.10", "freight": "0.00", "invoice_discount": "0.00", "declared_total": "132.00", "source_sha256": sha("race"),
            "source_filename": "r.pdf", "imported_at": "2026-10-06T09:00:00Z", "lines": [{"invoice_line_id": "l1", "po_line_id": "pol-1", "quantity": "6", "unit_price": "20.00"}]}
    results = race(6, lambda i, c: post(c, "import-invoice", body, CLERK, "same-key", version))
    assert [r.status_code for r in results] == [200] * 6
    assert sum(1 for r in results if r.headers.get("Idempotent-Replay") == "true") == 5
    assert len({r.json()["command_id"] for r in results}) == 1 and count(desk.conn, "invoices") == 1 and count(desk.conn, "import_lineage") == 1


def test_the_same_invoice_bytes_imported_concurrently_under_different_keys_make_one_invoice(desk):
    version = current_dataset_version()

    def body(i):
        return {"invoice_id": "inv-1", "vendor_id": "ven-1", "invoice_number": "INV-1", "invoice_date": "2026-10-06", "currency": "USD",
                "tax_rate": "0.10", "declared_total": "132.00", "source_sha256": sha("race2"), "source_filename": f"copy-{i}.pdf",
                "imported_at": "2026-10-06T09:00:00Z", "lines": [{"invoice_line_id": "l1", "po_line_id": "pol-1", "quantity": "6", "unit_price": "20.00"}]}
    results = race(5, lambda i, c: post(c, "import-invoice", body(i), CLERK, f"imp-{i}", version))
    assert [r.status_code for r in results] == [200] * 5
    assert sorted(r.json()["status"] for r in results) == ["duplicate"] * 4 + ["received"]
    assert count(desk.conn, "invoices") == 1 and count(desk.conn, "invoice_lines") == 1
    assert sorted(l["import_status"] for l in desk.conn.execute("SELECT import_status FROM import_lineage").fetchall()) == ["accepted"] + ["merged"] * 4


def test_export_batch_idempotency_under_concurrency_same_key(desk):
    desk.ready("inv-1")
    desk.approve("inv-1", decided_at="2026-10-06T15:30:00Z")
    version = current_dataset_version()
    results = race(6, lambda i, c: post(c, "export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"], "exported_at": f"2026-10-07T08:00:{i:02d}Z"},
                                         REVIEWER, "exp-key", version))
    assert [r.status_code for r in results] == [200] * 6
    assert len({r.json()["command_id"] for r in results}) == 1 and len({r.json()["result"]["rows"][0]["export_id"] for r in results}) == 1
    assert count(desk.conn, "export_batches") == 1 and count(desk.conn, "export_rows") == 1
    outcomes = sorted(r["outcome"] for r in desk.conn.execute("SELECT outcome FROM export_requests").fetchall())
    assert outcomes == ["created"] + ["returned_prior"] * 5
    m = metrics(desk)["export"]
    assert (m["requests_received"], m["batches_created"], m["repeat_requests_returned_prior"], len(m["rows"])) == (6, 1, 5, 1)
    assert m["rows"][0]["exported_at"].startswith("2026-10-07T08:00:")


def test_export_batch_idempotency_under_concurrency_distinct_keys_same_batch(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    version = current_dataset_version()
    results = race(6, lambda i, c: post(c, "export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"]}, REVIEWER, f"exp-key-{i}", version))
    assert [r.status_code for r in results] == [200] * 6
    assert sorted(r.json()["status"] for r in results) == ["exported"] + ["returned_prior"] * 5
    assert len({r.json()["result"]["rows"][0]["content_hash"] for r in results}) == 1
    assert count(desk.conn, "export_batches") == 1 and count(desk.conn, "export_rows") == 1 and count(desk.conn, "export_requests") == 6
    m = metrics(desk)["export"]
    assert (m["batches_created"], m["repeat_requests_returned_prior"]) == (1, 5) and m["difference"] == "0.00"


def test_two_batches_racing_for_one_invoice_export_it_once(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    version = current_dataset_version()
    results = race(2, lambda i, c: post(c, "export-payable", {"batch_id": f"bat-{i}", "invoice_ids": ["inv-1"]}, REVIEWER, f"two-{i}", version))
    assert sorted(r.status_code for r in results) == [200, 409] and count(desk.conn, "export_rows") == 1


def test_concurrent_matches_on_one_po_line_never_double_consume(desk):
    """Two invoices of 6 units race for 6 received units: exactly one matches, in book order, whichever C04 runs first."""
    for i in (1, 2):
        desk.imp(f"inv-{i}", [(f"l{i}", "pol-1", "6", "20.00")], invoice_number=f"N{i}", imported_at=f"2026-10-06T09:0{i}:00Z")
        desk.post("validate-invoice", {"invoice_id": f"inv-{i}"})
    version = current_dataset_version()
    results = race(2, lambda i, c: post(c, "match-three-way", {"invoice_id": f"inv-{2 - i}"}, CLERK, f"m-{i}", version))
    assert [r.status_code for r in results] == [200, 200]
    assert (desk.status("inv-1"), desk.status("inv-2")) == ("matched", "exception")
    m = metrics(desk)
    assert m["quantities"]["accepted_invoiced_quantity"] == "6.0000" and m["exceptions"]["by_reason"]["QUANTITY_BLOCKED"] == 1


def test_a_racing_approval_and_rejection_leave_one_decision(desk):
    desk.ready("inv-1")
    version = current_dataset_version()

    def fn(i, c):
        if i == 0:
            return post(c, "approve-invoice", {"invoice_id": "inv-1"}, REVIEWER, "ar-0", version)
        return post(c, "reject-invoice", {"invoice_id": "inv-1", "reason": "duplicate payment risk"}, actor("usr-rev02", "reviewer"), "ar-1", version)
    results = race(2, fn)
    assert sorted(r.status_code for r in results) == [200, 409]
    assert count(desk.conn, "approvals") == 1 and desk.status("inv-1") in ("approved", "rejected")


def test_concurrent_credit_notes_for_one_credit_id_apply_once(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    version = current_dataset_version()
    results = race(4, lambda i, c: post(c, "apply-credit-note", {"credit_id": "cn-1", "invoice_id": "inv-1", "credit_amount": "10.00"}, REVIEWER, f"cn-{i}", version))
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409] and count(desk.conn, "credit_notes") == 1
    assert metrics(desk)["payable"]["credit_total"] == "10.00"


# --- the golden fixture's spec sentence, end to end -------------------------------------------------------------

def test_the_spec_sentence_through_the_api(client, conn):
    """PO 10 at 20, receipt 6: invoice of 6 matches 120 before tax (132 with 10 %); a second for 4 is blocked; the first twice is one obligation."""
    d = Desk(client, conn, World_from_golden())
    first = d.ready("inv-1", [("il-1", "pol-001", "6", "20.00")])
    assert first["status"] == "matched" and (first["subtotal"], first["total"]) == ("120.00", "132.00")
    assert d.imp("inv-1", [("il-1", "pol-001", "6", "20.00")], key="idem-first").status_code == 200
    assert d.imp("inv-1", [("il-1", "pol-001", "6", "20.00")], key="idem-first").headers["Idempotent-Replay"] == "true"
    second = d.ready("inv-2", [("il-2", "pol-001", "4", "20.00")])
    assert second["status"] == "exception" and second["lines"][0]["reason_code"] == "QUANTITY_BLOCKED"
    d.approve("inv-1")
    m = metrics(d)
    assert (m["obligations"], m["matched"]["amount_before_tax"]) == ({"count": 1, "total": "132.00"}, "120.00")


def World_from_golden():
    from support_db import World
    w = World()
    w.d["vendors"] = [w.d["vendors"][0]]
    w.d["purchase_orders"] = [w.d["purchase_orders"][0]]
    w.pol("pol-001", qty="10", price="20.00")
    w.receipt("pol-001", "6")
    return w


def test_the_same_bytes_under_different_invoice_ids_imported_concurrently_make_one_obligation(desk):
    version = current_dataset_version()

    def body(i):
        return {"invoice_id": f"inv-{i}", "vendor_id": "ven-1", "invoice_number": "N-1", "invoice_date": "2026-10-06", "currency": "USD",
                "tax_rate": "0.10", "declared_total": "132.00", "source_sha256": sha("race3"), "source_filename": f"copy-{i}.pdf",
                "imported_at": f"2026-10-06T09:00:0{i}Z", "lines": [{"invoice_line_id": f"l{i}", "po_line_id": "pol-1", "quantity": "6", "unit_price": "20.00"}]}
    results = race(4, lambda i, c: post(c, "import-invoice", body(i), CLERK, f"sha-{i}", version))
    assert [r.status_code for r in results] == [200] * 4
    rows = desk.conn.execute("SELECT invoice_id, status, merged_into FROM invoices ORDER BY invoice_id").fetchall()
    assert len(rows) == 4 and sum(1 for r in rows if r["status"] == "received") == 1 and sum(1 for r in rows if r["status"] == "merged") == 3
    canon = next(r["invoice_id"] for r in rows if r["status"] == "received")
    assert all(r["merged_into"] == canon for r in rows if r["status"] == "merged")
