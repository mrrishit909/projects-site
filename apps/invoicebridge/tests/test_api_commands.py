"""C01..C10 through the HTTP API: states, roles, envelopes, idempotency, atomicity and the golden fixtures end to end."""
import json

import pytest

from api import commands
from api.app import PREFIX

from support_db import (ADMIN, CLERK, REVIEWER, VARIANTS, Desk, actor, client, command, conn, count, db_url, drive,  # noqa: F401
                        golden_expected, golden_inputs, rule_ids, set_now, sha, current_dataset_version)
from test_golden_domain import flat


@pytest.fixture
def desk(client, conn):
    return Desk(client, conn)


# --- the golden fixtures, driven through the commands -----------------------------------------------------------

@pytest.mark.parametrize("variant", VARIANTS)
def test_api_reproduces_every_metric_of_expected_json(client, conn, variant):
    inputs, want = golden_inputs(variant), golden_expected(variant)
    drive(client, conn, inputs)
    r = client.get(f"{PREFIX}/metrics", params={"to": inputs["as_of"], "cutoff": ",".join(inputs["snapshot_cutoffs"])})
    assert r.status_code == 200, r.text
    body = r.json()
    got = body["data"]["metrics"]
    assert list(got) == list(want["metrics"])
    fe, fg = flat(want["metrics"]), flat(got)
    assert fe == fg
    assert body["data"]["snapshot_cutoffs"] == inputs["snapshot_cutoffs"] and body["warnings"] == []


def test_api_golden_documents_and_state(client, conn):
    inputs, want = golden_inputs(), golden_expected()
    log = drive(client, conn, inputs)
    assert log["import:inv-003"] == 200 and log["approve:ap-001"] == 200
    docs = {r["invoice_id"]: r for r in client.get(f"{PREFIX}/data/invoices").json()["data"]}
    for iid, d in want["documents"]["invoices"].items():
        assert docs[iid]["status"] == d["status"]
        assert (docs[iid]["subtotal"], docs[iid]["tax"], docs[iid]["total"]) == (d["subtotal"], d["tax"], d["total"])
        assert docs[iid]["merged_into"] == d.get("merged_into")
    results = [{k: v for k, v in r.items() if k in want["documents"]["match_results"][0]}
               for r in client.get(f"{PREFIX}/data/match_results", params={"status": "exception"}).json()["data"]]
    assert results[0]["reason_code"] == "QUANTITY_BLOCKED" and results[0]["rule_version"] == "1"
    exc = client.get(f"{PREFIX}/data/exceptions").json()["data"]
    assert [(e["exception_id"], e["invoice_id"], e["exception_type"], e["owner_id"], e["status"]) for e in exc] == [
        ("exc-001", "inv-002", "QUANTITY_BLOCKED", None, "open")]
    rows = client.get(f"{PREFIX}/data/export_rows").json()["data"]
    assert [(r["export_id"], r["amount"], r["content_hash"]) for r in rows] == [
        ("exp-bat-001-inv-001", "132.00", want["metrics"]["export"]["rows"][0]["content_hash"])]
    assert count(conn, "export_batches") == 1 and count(conn, "export_requests") == 2


def test_the_repeated_export_returns_the_prior_batch_and_is_counted(client, conn):
    inputs = golden_inputs()
    drive(client, conn, inputs)
    rq = conn.execute("SELECT outcome FROM export_requests ORDER BY request_seq").fetchall()
    assert [r["outcome"] for r in rq] == ["created", "returned_prior"]
    again = command(client, "export-payable", {"batch_id": "bat-001", "invoice_ids": ["inv-001"], "exported_at": "2026-10-07T09:00:00Z"},
                    key="exp-key-001", headers=REVIEWER)
    assert again.status_code == 200 and again.headers["Idempotent-Replay"] == "true" and again.json()["result"]["rows"][0]["exported_at"] == "2026-10-07T08:00:00Z"
    assert count(conn, "export_batches") == 1 and count(conn, "export_rows") == 1


# --- identity, roles and envelopes ------------------------------------------------------------------------------

def test_commands_need_an_actor_and_a_known_role(desk):
    r = command(desk.client, "import-invoice", {}, headers={})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED" and "request_id" in r.json()
    r = command(desk.client, "import-invoice", {}, headers={"X-Actor-Id": "u"})
    assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"]
    r = command(desk.client, "import-invoice", {}, headers=actor("u", "superuser"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert desk.client.post(f"{PREFIX}/commands/correct-extraction", json={}).status_code == 401


@pytest.mark.parametrize("name,who", [("approve-invoice", CLERK), ("reject-invoice", CLERK),
                                      ("export-payable", CLERK), ("apply-credit-note", CLERK)])
def test_the_role_decides_who_may_run_a_command(desk, name, who):
    inputs = {"import-invoice": {"invoice_id": "i", "vendor_id": "v", "invoice_number": "n", "invoice_date": "2026-10-06", "currency": "USD",
                                 "tax_rate": "0.1", "declared_total": "1", "source_sha256": sha("x"), "source_filename": "f",
                                 "lines": [{"invoice_line_id": "l", "po_line_id": "p", "quantity": "1", "unit_price": "1"}]},
              "approve-invoice": {"invoice_id": "i"}, "reject-invoice": {"invoice_id": "i", "reason": "r"},
              "export-payable": {"batch_id": "b", "invoice_ids": ["i"]}, "apply-credit-note": {"credit_id": "c", "invoice_id": "i", "credit_amount": "1"}}
    r = desk.post(name, inputs[name], who)
    assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"]


def test_envelope_validation_is_422_with_rule_ids_and_the_request_id_is_echoed(desk):
    r = desk.client.post(f"{PREFIX}/commands/import-invoice", json={"request_id": "req-7", "dataset_version": "x", "idempotency_key": "bad key!", "input": {}},
                         headers=CLERK)
    body = r.json()
    assert r.status_code == 422 and body["request_id"] == "req-7" and body["error"]["code"] == "VALIDATION_FAILED"
    assert "IDEMPOTENCY_KEY_INVALID" in rule_ids(r) and "FIELD_REQUIRED" in rule_ids(r)
    r = desk.imp("inv-1", tax_rate=0.1)                        # a JSON float where a decimal string is required
    assert r.status_code == 422 and "FIELD_INVALID" in rule_ids(r)
    r = desk.imp("inv-1", paid=True)                           # nothing is ever marked paid
    assert r.status_code == 422 and rule_ids(r) == ["FIELD_UNEXPECTED"]
    r = desk.imp("inv-1", imported_at="2026-10-06T09:00Z")     # seconds are required
    assert r.status_code == 422 and rule_ids(r) == ["TIMESTAMP_INVALID"]
    assert count(desk.conn, "invoices") == 0


def test_unknown_command_is_404_and_a_get_on_a_command_is_405(desk):
    r = desk.post("pay-invoice", {})
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNSUPPORTED_ACTION"
    assert desk.client.get(f"{PREFIX}/commands/import-invoice").status_code == 405


def test_c06_correct_extraction_is_routed_and_answers_501(desk):
    r = desk.post("correct-extraction", {"invoice_id": "inv-1", "fields": {"declared_total": "1.00"}})
    assert r.status_code == 501 and r.json()["error"]["code"] == "NOT_IMPLEMENTED" and rule_ids(r) == ["NOT_IMPLEMENTED"]
    paths = desk.client.get(f"{PREFIX}/openapi.json").json()["paths"]
    assert f"{PREFIX}/commands/correct-extraction" in paths


# --- C01 import-invoice -----------------------------------------------------------------------------------------

def test_import_creates_one_received_invoice_with_computed_amounts_lineage_and_audit(desk):
    r = desk.imp("inv-1", [("l1", "pol-1", "6", "20.00")])
    res = r.json()
    assert r.status_code == 200 and res["status"] == "received" and res["version"] == 1
    assert (res["result"]["subtotal"], res["result"]["tax"], res["result"]["total"], res["result"]["rounding_difference"]) == ("120.00", "12.00", "132.00", "0.00")
    row = desk.conn.execute("SELECT * FROM invoices WHERE invoice_id = 'inv-1'").fetchone()
    assert (row["created_by"], row["status"], row["validity"], row["invoice_number_norm"]) == ("usr-clerk01", "received", None, "INV1")
    lin = desk.conn.execute("SELECT * FROM import_lineage").fetchall()
    assert [(l["invoice_id"], l["import_status"], l["source_sha256"]) for l in lin] == [("inv-1", "accepted", sha("bytes-inv-1"))]
    ev = desk.conn.execute("SELECT action, actor_id, invoice_id, request_id FROM audit_events").fetchall()
    assert [(e["action"], e["actor_id"], e["invoice_id"], e["request_id"]) for e in ev] == [("import-invoice", "usr-clerk01", "inv-1", "req-test")]
    assert desk.conn.execute("SELECT count(*) AS n FROM command_results").fetchone()["n"] == 1


def test_the_same_key_and_payload_replays_the_stored_response(desk):
    first = desk.imp("inv-1", key="idem-1")
    again = desk.imp("inv-1", key="idem-1")
    assert again.status_code == 200 and again.headers.get("Idempotent-Replay") == "true" and again.json() == first.json()
    assert count(desk.conn, "invoices") == 1 and count(desk.conn, "import_lineage") == 1 and count(desk.conn, "audit_events") == 1


def test_the_same_key_with_another_payload_or_actor_is_409(desk):
    desk.imp("inv-1", key="idem-1")
    other_payload = desk.imp("inv-2", key="idem-1")
    assert other_payload.status_code == 409 and rule_ids(other_payload) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]
    other_actor = desk.imp("inv-1", key="idem-1", who=ADMIN)
    assert other_actor.status_code == 409 and other_actor.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert rule_ids(other_actor) == ["IDEMPOTENCY_ACTOR_MISMATCH"]


def test_dataset_version_is_part_of_the_payload_and_a_stale_one_writes_nothing(desk):
    cur = current_dataset_version()
    assert desk.imp("inv-1", key="idem-1", dataset_version=cur).status_code == 200
    reused = desk.imp("inv-1", key="idem-1", dataset_version="ds-other")
    assert reused.status_code == 409 and rule_ids(reused) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]       # same key, same body, another version
    stale = desk.imp("inv-2", dataset_version="ds-000000000000")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_DATASET_VERSION"
    assert stale.json()["error"]["details"][0]["context"] == {"current": cur, "requested": "ds-000000000000"}
    assert count(desk.conn, "invoices") == 1 and count(desk.conn, "command_results") == 1


def test_a_domain_rejection_is_422_with_the_rule_id_and_keeps_the_raw_record(desk):
    r = desk.imp("inv-1", vendor_id="ven-ghost", key="k-reject")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"
    assert sorted(rule_ids(r)) == ["DEPENDENT_REJECTED", "UNKNOWN_VENDOR"]
    assert count(desk.conn, "invoices") == 0 and count(desk.conn, "command_results") == 0
    rej = desk.conn.execute("SELECT entity, id, reason_code FROM rejected_records ORDER BY entity, id").fetchall()
    assert [(x["entity"], x["id"], x["reason_code"]) for x in rej] == [("invoice_lines", "inv-1-1", "DEPENDENT_REJECTED"), ("invoices", "inv-1", "UNKNOWN_VENDOR")]
    lin = desk.conn.execute("SELECT import_status, reason_code FROM import_lineage").fetchall()
    assert [(l["import_status"], l["reason_code"]) for l in lin] == [("rejected", "UNKNOWN_VENDOR")]
    desk.imp("inv-1", vendor_id="ven-ghost", key="k-reject")                       # a retry with the same key keeps one record
    assert count(desk.conn, "rejected_records") == 2 and count(desk.conn, "import_lineage") == 1
    assert count(desk.conn, "rejected_records") == 2


def test_a_non_positive_quantity_rejects_the_whole_invoice(desk):
    r = desk.imp("inv-1", [("l1", "pol-1", "2", "20.00"), ("l2", "pol-1", "-4", "20.00")])
    assert r.status_code == 422 and sorted(rule_ids(r)) == ["DEPENDENT_REJECTED", "DEPENDENT_REJECTED", "NON_POSITIVE_QUANTITY"]
    paths = {d["path"]: d["rule_id"] for d in r.json()["error"]["details"]}
    assert paths["input.invoice_lines[l2]"] == "NON_POSITIVE_QUANTITY" and paths["input.invoice_lines[l1]"] == "DEPENDENT_REJECTED"
    assert count(desk.conn, "invoices") == 0 and count(desk.conn, "invoice_lines") == 0


def test_a_line_id_that_exists_is_refused_and_the_same_id_with_other_bytes_is_409(desk):
    desk.imp("inv-1", [("l1", "pol-1", "1", "20.00")])
    r = desk.imp("inv-2", [("l1", "pol-1", "1", "20.00")])
    assert r.status_code == 422 and "DUPLICATE_ID" in rule_ids(r)
    r = desk.imp("inv-1", [("l9", "pol-1", "1", "20.00")], source_sha256=sha("other bytes"))
    assert r.status_code == 409 and rule_ids(r) == ["DUPLICATE_ID"]


def test_same_bytes_under_another_invoice_id_is_one_obligation(desk):
    desk.ready("inv-1")
    r = desk.imp("inv-1b", [("l-b", "pol-1", "6", "20.00")], source_sha256=sha("bytes-inv-1"), source_filename="renamed.pdf", invoice_number="INV-1")
    res = r.json()
    assert r.status_code == 200 and res["status"] == "merged" and res["result"]["duplicate_of"] == "inv-1"
    assert res["result"]["reason_code"] == "DUPLICATE_SOURCE_BYTES" and res["warnings"][0]["code"] == "DUPLICATE_SOURCE_BYTES"
    row = desk.conn.execute("SELECT status, merged_into, merge_reason FROM invoices WHERE invoice_id = 'inv-1b'").fetchone()
    assert (row["status"], row["merged_into"], row["merge_reason"]) == ("merged", "inv-1", "DUPLICATE_SOURCE_BYTES")
    assert desk.post("match-three-way", {"invoice_id": "inv-1b"}).status_code == 409
    again = desk.imp("inv-1", key="another-key", source_filename="again.pdf")        # the same invoice id and bytes again
    assert again.status_code == 200 and again.json()["result"]["duplicate_of"] == "inv-1" and count(desk.conn, "invoices") == 2
    assert [l["import_status"] for l in desk.conn.execute("SELECT import_status FROM import_lineage ORDER BY lineage_id").fetchall()] == [
        "accepted", "merged", "merged"]
    m = desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]
    assert m["duplicates"]["rows_merged"] == 1 and m["rates"]["eligible_invoices"] == 1 and m["quantities"]["accepted_invoiced_quantity"] == "6.0000"


# --- C02 validate-invoice ---------------------------------------------------------------------------------------

def test_validate_moves_received_to_valid_and_only_from_received(desk):
    desk.imp("inv-1")
    r = desk.post("validate-invoice", {"invoice_id": "inv-1"})
    assert r.status_code == 200 and r.json()["status"] == "valid" and r.json()["result"]["valid"] is True
    assert desk.status("inv-1") == "valid" and desk.conn.execute("SELECT validity FROM invoices").fetchone()["validity"] is True
    again = desk.post("validate-invoice", {"invoice_id": "inv-1"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_STATE"
    assert desk.post("validate-invoice", {"invoice_id": "inv-nope"}).status_code == 404


@pytest.mark.parametrize("kw,rule", [({"invoice_discount": "500.00"}, "NEGATIVE_TOTAL"), ({"invoice_date": "2027-01-01"}, "INVOICE_DATE_IN_FUTURE")])
def test_validate_records_the_failed_rules_and_the_invoice_leaves_the_book(desk, kw, rule):
    desk.imp("inv-1", **kw)
    r = desk.post("validate-invoice", {"invoice_id": "inv-1"})
    assert r.status_code == 200 and r.json()["status"] == "invalid" and [x["rule_id"] for x in r.json()["result"]["rules"]] == [rule]
    assert desk.status("inv-1") == "invalid" and desk.post("match-three-way", {"invoice_id": "inv-1"}).status_code == 409
    assert desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]["rates"]["eligible_invoices"] == 0


def test_an_inactive_vendor_is_invalid(client, conn):
    w = Desk.default_world()
    w.d["vendors"][0]["active"] = False
    d = Desk(client, conn, w)
    d.imp("inv-1")
    assert [x["rule_id"] for x in d.post("validate-invoice", {"invoice_id": "inv-1"}).json()["result"]["rules"]] == ["VENDOR_INACTIVE"]


# --- C03 find-duplicates ----------------------------------------------------------------------------------------

def test_find_duplicates_explains_the_matching_fields_and_merges_into_the_earliest(desk):
    desk.imp("inv-1", invoice_number="INV-1001", imported_at="2026-10-06T09:00:00Z")
    desk.imp("inv-2", invoice_number="inv 1001", imported_at="2026-10-07T09:00:00Z")
    for i in ("inv-1", "inv-2"):
        desk.post("validate-invoice", {"invoice_id": i})
    r = desk.post("find-duplicates", {"invoice_id": "inv-2"})
    res = r.json()["result"]
    assert r.status_code == 200 and res["canonical_id"] == "inv-1" and res["is_canonical"] is False and res["status"] == "merged"
    assert res["candidates"][0]["matched_on"] == ["vendor_id", "invoice_number_normalised", "invoice_date", "computed_total"]
    assert "normalised number INV1001" in res["candidates"][0]["explanation"] and res["merged"] == ["inv-2"]
    row = desk.conn.execute("SELECT status, merged_into, merge_reason FROM invoices WHERE invoice_id = 'inv-2'").fetchone()
    assert (row["status"], row["merged_into"], row["merge_reason"]) == ("merged", "inv-1", "DUPLICATE_IDENTITY")
    assert desk.status("inv-1") == "valid"
    again = desk.post("find-duplicates", {"invoice_id": "inv-1"})
    assert again.json()["result"]["is_canonical"] is True and again.json()["result"]["merged"] == []


def test_run_on_the_canonical_it_merges_the_later_copies_and_a_different_vendor_is_not_a_duplicate(desk):
    desk.imp("inv-1", invoice_number="A-1", imported_at="2026-10-06T09:00:00Z")
    desk.imp("inv-2", invoice_number="a1", imported_at="2026-10-07T09:00:00Z")
    desk.imp("inv-3", invoice_number="a1", imported_at="2026-10-08T09:00:00Z", invoice_date="2026-10-07")        # another date
    for i in ("inv-1", "inv-2", "inv-3"):
        desk.post("validate-invoice", {"invoice_id": i})
    r = desk.post("find-duplicates", {"invoice_id": "inv-1"})
    assert r.json()["result"]["merged"] == ["inv-2"] and desk.status("inv-3") == "valid"
    assert desk.post("find-duplicates", {"invoice_id": "inv-3"}).json()["result"]["candidates"] == []


def test_an_approved_canonical_copy_is_never_displaced_by_an_earlier_stamped_import(desk):
    """D-09 (R5-02): the committed copy is the canonical one; the later-arriving copy, even stamped earlier, merges into it."""
    desk.ready("inv-2", [("l2", "pol-1", "6", "20.00")], invoice_number="SAME", imported_at="2026-10-07T09:00:00Z")
    desk.approve("inv-2")
    desk.imp("inv-1", [("l1", "pol-1", "6", "20.00")], invoice_number="SAME", imported_at="2026-10-06T09:00:00Z")     # stamped earlier
    desk.post("validate-invoice", {"invoice_id": "inv-1"})
    assert desk.post("match-three-way", {"invoice_id": "inv-1"}).status_code == 409          # the derivation merges it: run find-duplicates
    r = desk.post("find-duplicates", {"invoice_id": "inv-1"})
    assert r.status_code == 200 and r.json()["result"]["canonical_id"] == "inv-2" and r.json()["result"]["merged"] == ["inv-1"]
    assert desk.status("inv-2") == "approved" and desk.status("inv-1") == "merged"


def test_a_derived_duplicate_cannot_advance_even_when_its_stored_state_says_matched(desk):
    """D-09 (R5-02): C07 re-derives; a copy the derivation merges into a committed invoice is refused (409 DUPLICATE_PENDING)."""
    desk.ready("inv-1", [("l1", "pol-1", "3", "20.00")], invoice_number="TWIN")
    desk.approve("inv-1", decided_at="2026-10-08T00:00:00Z")
    desk.imp("inv-2", [("l2", "pol-1", "3", "20.00")], invoice_number="TWIN", imported_at="2026-10-09T09:00:00Z")
    desk.post("validate-invoice", {"invoice_id": "inv-2"})
    assert desk.post("match-three-way", {"invoice_id": "inv-2"}).status_code == 409           # the derivation merges it: find-duplicates first
    desk.conn.execute("UPDATE invoices SET status = 'matched' WHERE invoice_id = 'inv-2'")    # a stale stored state
    r = desk.approve("inv-2", who=actor("usr-rev02", "reviewer"), decided_at="2026-10-09T10:00:00Z")
    assert r.status_code == 409 and rule_ids(r) == ["DUPLICATE_PENDING"] and count(desk.conn, "approvals") == 1


# --- C04 match-three-way ----------------------------------------------------------------------------------------

def test_match_persists_line_results_exceptions_and_the_rule_version(desk):
    ok = desk.ready("inv-1")
    assert ok["status"] == "matched" and ok["lines"][0]["available_quantity"] == "6.0000" and ok["rule_version"] == "1"
    blocked = desk.ready("inv-2", [("l2", "pol-1", "4", "20.00")])
    assert blocked["status"] == "exception" and blocked["lines"][0]["reason_code"] == "QUANTITY_BLOCKED"
    assert blocked["lines"][0]["quantity_variance"] == "4.0000" and blocked["exceptions"] == [
        {"exception_id": "exc-001", "exception_type": "QUANTITY_BLOCKED", "status": "open", "owner_id": None}]
    mr = desk.conn.execute("SELECT * FROM match_results WHERE invoice_line_id = 'l2'").fetchone()
    assert (mr["rule_version"], mr["status"], mr["reason_code"]) == ("1", "exception", "QUANTITY_BLOCKED")
    assert desk.status("inv-1") == "matched" and desk.status("inv-2") == "exception"


def test_matching_never_approves(desk):
    desk.ready("inv-1")
    assert desk.conn.execute("SELECT count(*) AS n FROM approvals").fetchone()["n"] == 0 and desk.status("inv-1") == "matched"


def test_match_needs_a_validated_invoice(desk):
    desk.imp("inv-1")
    r = desk.post("match-three-way", {"invoice_id": "inv-1"})
    assert r.status_code == 409 and r.json()["error"]["details"][0]["context"]["status"] == "received"


def test_a_late_receipt_resolves_the_exception_on_the_next_match(desk):
    desk.ready("inv-1")
    blocked = desk.ready("inv-2", [("l2", "pol-1", "4", "20.00")])
    assert blocked["status"] == "exception"
    desk.conn.execute("INSERT INTO receipts (receipt_id, po_line_id, received_quantity, received_at) VALUES ('rc-late', 'pol-1', 4, '2026-10-06T08:00:00Z')")
    again = desk.post("match-three-way", {"invoice_id": "inv-2"}).json()
    assert again["status"] == "matched" and again["result"]["exceptions"] == [] and again["version"] > blocked.get("version", 0)
    ex = desk.conn.execute("SELECT status, resolved_at FROM exceptions").fetchone()
    assert ex["status"] == "resolved" and ex["resolved_at"] is not None


def test_a_matched_invoice_whose_receipt_is_reversed_is_blocked_on_the_next_match(desk):
    desk.ready("inv-1")
    desk.conn.execute("UPDATE receipts SET reversed = TRUE, reversed_at = now() WHERE receipt_id = 'rc-001'")
    r = desk.post("match-three-way", {"invoice_id": "inv-1"}).json()
    assert r["status"] == "exception" and r["result"]["lines"][0]["available_quantity"] == "0.0000"
    assert desk.status("inv-1") == "exception"


# --- C05 assign-exception ---------------------------------------------------------------------------------------

def test_assigning_keeps_the_history_and_a_resolved_exception_cannot_be_assigned(desk):
    desk.ready("inv-1")
    desk.ready("inv-2", [("l2", "pol-1", "4", "20.00")])
    r = desk.post("assign-exception", {"exception_id": "exc-001", "owner_id": "usr-owner1", "assigned_at": "2026-10-08T10:00:00Z", "note": "check the receipt"})
    assert r.status_code == 200 and r.json()["result"]["status"] == "assigned" and r.json()["result"]["previous_owner_id"] is None
    r2 = desk.post("assign-exception", {"exception_id": "exc-001", "owner_id": "usr-owner2", "assigned_at": "2026-10-09T10:00:00Z"}, REVIEWER)
    assert r2.json()["result"]["previous_owner_id"] == "usr-owner1" and r2.json()["result"]["assignments"] == 2
    hist = desk.conn.execute("SELECT owner_id, assigned_by FROM exception_assignments ORDER BY assignment_id").fetchall()
    assert [(h["owner_id"], h["assigned_by"]) for h in hist] == [("usr-owner1", "usr-clerk01"), ("usr-owner2", "usr-rev01")]
    ex = desk.conn.execute("SELECT status, owner_id FROM exceptions").fetchone()
    assert (ex["status"], ex["owner_id"]) == ("assigned", "usr-owner2")
    m = desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]["exceptions"]
    assert (m["open_count"], m["unowned_count"], m["records"][0]["owner_id"], m["records"][0]["status"]) == (1, 0, "usr-owner2", "assigned")
    back = desk.client.get(f"{PREFIX}/metrics", params={"to": "2026-10-08T00:00:00Z"}).json()["data"]["metrics"]["exceptions"]   # backlog as of a cutoff
    assert back["unowned_count"] == back["open_count"] == 1
    desk.conn.execute("INSERT INTO receipts (receipt_id, po_line_id, received_quantity, received_at) VALUES ('rc-late', 'pol-1', 4, '2026-10-06T08:00:00Z')")
    desk.post("match-three-way", {"invoice_id": "inv-2"})
    gone = desk.post("assign-exception", {"exception_id": "exc-001", "owner_id": "usr-owner3"})
    assert gone.status_code == 409 and gone.json()["error"]["code"] == "INVALID_STATE"
    assert desk.post("assign-exception", {"exception_id": "exc-404", "owner_id": "u"}).status_code == 404


# --- C07 approve-invoice ----------------------------------------------------------------------------------------

def test_approval_records_the_actor_role_and_policy_version_and_moves_the_state(desk):
    desk.ready("inv-1")
    r = desk.approve("inv-1", approval_id="ap-001", decided_at="2026-10-06T15:30:00Z")
    res = r.json()["result"]
    assert r.status_code == 200 and res["status"] == "approved" and (res["policy_id"], res["policy_version"], res["actor_role"]) == ("pol-v1", 1, "reviewer")
    ap = desk.conn.execute("SELECT * FROM approvals").fetchone()
    assert (ap["actor_id"], ap["actor_role"], ap["decision"], ap["policy_version"]) == ("usr-rev01", "reviewer", "approve", 1)
    assert desk.status("inv-1") == "approved"
    m = desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]
    assert (m["obligations"], m["processing"]["mean_minutes"]) == ({"count": 1, "total": "132.00"}, "390.0000")


def test_self_approval_is_refused_403_and_the_refusal_is_audited(desk):
    desk.imp("inv-1", who=ADMIN)                                              # created by the admin ...
    desk.post("validate-invoice", {"invoice_id": "inv-1"})
    desk.post("match-three-way", {"invoice_id": "inv-1"})
    r = desk.approve("inv-1", who=ADMIN)                                      # ... approved by the same admin
    assert r.status_code == 403 and r.json()["error"]["code"] == "SELF_APPROVAL" and rule_ids(r) == ["SELF_APPROVAL"]
    assert desk.status("inv-1") == "matched" and count(desk.conn, "approvals") == 0
    ev = desk.conn.execute("SELECT action, actor_id, details FROM audit_events WHERE action = 'approve-invoice-refused'").fetchall()
    assert [(e["actor_id"], e["details"]["rule_id"]) for e in ev] == [("usr-adm01", "SELF_APPROVAL")]
    assert desk.approve("inv-1", who=actor("usr-rev01", "reviewer")).status_code == 200      # someone else may


def test_the_policy_in_force_at_decision_time_decides_role_and_limit(client, conn):
    w = Desk.default_world()
    w.d["approval_policies"].append({"policy_id": "pol-v2", "version_number": 2, "amount_limit": "100.00", "reviewer_role": "reviewer",
                                     "escalation_role": "admin", "effective_from": "2026-10-06T12:00:00Z"})
    d = Desk(client, conn, w)
    d.ready("inv-1")                                                         # total 132.00
    over = d.approve("inv-1", decided_at="2026-10-06T13:00:00Z")             # v2: reviewer limit 100.00
    assert over.status_code == 403 and rule_ids(over) == ["ROLE_OR_LIMIT"] and over.json()["error"]["details"][0]["context"]["total"] == "132.00"
    old = d.approve("inv-1", who=actor("usr-rev02", "reviewer"), decided_at="2026-10-06T11:00:00Z")      # v1 was in force then
    assert old.status_code == 200 and old.json()["result"]["policy_version"] == 1
    d.ready("inv-2", [("l2", "pol-1", "0.1", "20.00")], invoice_number="B")
    assert d.approve("inv-2", decided_at="2026-10-06T13:00:00Z").status_code == 409            # inv-2 is blocked (inv-1 consumed the 6 received): not approvable


def test_the_escalation_role_approves_over_the_limit_and_no_policy_means_no_approval(client, conn):
    w = Desk.default_world()
    w.d["approval_policies"][0]["amount_limit"] = "100.00"
    d = Desk(client, conn, w)
    d.ready("inv-1")
    assert d.approve("inv-1").status_code == 403
    nop = d.approve("inv-1", who=ADMIN, decided_at="2025-01-01T00:00:00Z")      # the server clock is pinned before any policy
    assert nop.status_code == 403 and rule_ids(nop) == ["NO_POLICY"]
    set_now(None)
    assert d.approve("inv-1", who=ADMIN).status_code == 200


def test_only_a_matched_invoice_can_be_approved_and_only_once(desk):
    desk.imp("inv-1")
    assert desk.approve("inv-1").status_code == 409                          # received
    desk.post("validate-invoice", {"invoice_id": "inv-1"})
    desk.post("match-three-way", {"invoice_id": "inv-1"})
    desk.ready("inv-2", [("l2", "pol-1", "4", "20.00")])                     # exception
    assert desk.approve("inv-2").json()["error"]["details"][0]["context"] == {"status": "exception", "allowed": ["matched"]}
    assert desk.approve("inv-1").status_code == 200
    again = desk.approve("inv-1", who=actor("usr-rev02", "reviewer"))
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_STATE" and count(desk.conn, "approvals") == 1
    assert desk.approve("inv-404").status_code == 404


def test_an_approval_is_refused_when_the_match_no_longer_holds(desk):
    desk.ready("inv-1")
    desk.conn.execute("UPDATE receipts SET reversed = TRUE WHERE receipt_id = 'rc-001'")        # the goods receipt is reversed
    r = desk.approve("inv-1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_MATCH" and rule_ids(r) == ["NOT_MATCHED"]
    assert count(desk.conn, "approvals") == 0 and desk.status("inv-1") == "matched"


# --- C08 reject-invoice -----------------------------------------------------------------------------------------

def test_rejection_needs_a_reason_and_releases_the_received_quantity(desk):
    desk.ready("inv-1")
    blocked = desk.ready("inv-2", [("l2", "pol-1", "6", "20.00")], invoice_number="B")
    assert blocked["status"] == "exception"
    assert desk.post("reject-invoice", {"invoice_id": "inv-1", "reason": "  "}, REVIEWER).status_code == 422
    r = desk.post("reject-invoice", {"invoice_id": "inv-1", "reason": "wrong goods"}, REVIEWER)
    assert r.status_code == 200 and r.json()["result"]["consumes_received_quantity"] is False and desk.status("inv-1") == "rejected"
    assert rule_ids(desk.post("reject-invoice", {"invoice_id": "inv-2"}, REVIEWER)) == ["FIELD_REQUIRED"]
    again = desk.post("match-three-way", {"invoice_id": "inv-2"}).json()
    assert again["status"] == "matched"                                       # the rejected invoice no longer consumes
    ap = desk.conn.execute("SELECT decision, reason, actor_id FROM approvals").fetchone()
    assert (ap["decision"], ap["reason"], ap["actor_id"]) == ("reject", "wrong goods", "usr-rev01")
    assert desk.approve("inv-1").status_code == 409                           # a rejected invoice cannot be approved
    m = desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]
    assert m["rates"]["eligible_invoices"] == 1 and m["quantities"]["accepted_invoiced_quantity"] == "6.0000"


def test_an_approved_invoice_cannot_be_rejected(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    r = desk.post("reject-invoice", {"invoice_id": "inv-1", "reason": "too late"}, REVIEWER)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


# --- C09 export-payable -----------------------------------------------------------------------------------------

def test_export_writes_a_batch_with_a_content_hash_and_moves_approved_to_exported(desk):
    import hashlib
    desk.ready("inv-1")
    desk.approve("inv-1", decided_at="2026-10-06T15:30:00Z")
    r = desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"], "exported_at": "2026-10-07T08:00:00Z"}, REVIEWER)
    res = r.json()["result"]
    assert r.status_code == 200 and res["returned_prior"] is False and res["total"] == "132.00" and "nothing is paid" in res["payments"]
    assert res["rows"][0]["content_hash"] == hashlib.sha256(b"inv-1|ven-1|INV-1|2026-10-06|USD|132.00").hexdigest()
    assert desk.status("inv-1") == "exported"
    m = desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]["export"]
    assert (m["accepted_export_total"], m["eligible_approved_total"], m["difference"]) == ("132.00", "132.00", "0.00")


def test_only_approved_invoices_export_and_the_exclusions_are_explained(desk):
    desk.ready("inv-1")
    desk.ready("inv-2", [("l2", "pol-1", "4", "20.00")])
    for ids in (["inv-1"], ["inv-2"]):
        r = desk.post("export-payable", {"batch_id": "bat-x", "invoice_ids": ids}, REVIEWER)
        assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    ex = r.json()["error"]["details"][0]["context"]["exclusions"]
    assert ex == [{"invoice_id": "inv-2", "reason_code": "EXCEPTION_OPEN", "status": "exception"}]
    assert rule_ids(desk.post("export-payable", {"batch_id": "bat-x", "invoice_ids": ["inv-ghost"]}, REVIEWER)) == ["INVOICE_UNKNOWN"]
    assert count(desk.conn, "export_batches") == 0 and count(desk.conn, "export_requests") == 0


def test_a_batch_id_names_one_set_of_invoices_and_an_invoice_exports_once(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    desk.ready("inv-2", [("l2", "pol-1", "0.5", "20.00")], invoice_number="B")
    desk.conn.execute("INSERT INTO receipts (receipt_id, po_line_id, received_quantity, received_at) VALUES ('rc-2', 'pol-1', 4, '2026-10-06T08:00:00Z')")
    desk.post("match-three-way", {"invoice_id": "inv-2"})
    desk.approve("inv-2", who=actor("usr-rev02", "reviewer"))
    assert desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"]}, REVIEWER).status_code == 200
    other = desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1", "inv-2"]}, REVIEWER)
    assert other.status_code == 409 and rule_ids(other) == ["BATCH_CONFLICT"]
    twice = desk.post("export-payable", {"batch_id": "bat-2", "invoice_ids": ["inv-1"]}, REVIEWER)
    assert twice.status_code == 409 and twice.json()["error"]["details"][0]["context"]["exclusions"][0]["reason_code"] == "ALREADY_EXPORTED"
    same = desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"]}, REVIEWER)         # another key, same batch: the prior one
    assert same.status_code == 200 and same.json()["status"] == "returned_prior" and same.json()["result"]["rows"][0]["export_id"] == "exp-bat-1-inv-1"
    assert count(desk.conn, "export_batches") == 1 and count(desk.conn, "export_rows") == 1 and count(desk.conn, "export_requests") == 2


# --- C10 apply-credit-note --------------------------------------------------------------------------------------

def test_a_credit_adjusts_the_approved_payable_once_and_moves_no_cash(desk):
    desk.ready("inv-1")
    assert desk.post("apply-credit-note", {"credit_id": "cn-1", "invoice_id": "inv-1", "credit_amount": "10.00"}, REVIEWER).status_code == 409   # not approved yet
    desk.approve("inv-1")
    r = desk.post("apply-credit-note", {"credit_id": "cn-1", "invoice_id": "inv-1", "credit_amount": "32.00", "credited_at": "2026-10-08T00:00:00Z"}, REVIEWER)
    res = r.json()["result"]
    assert r.status_code == 200 and res["status"] == "adjusted" and res["cash_movement"] is False
    assert (res["credit_total"], res["approved_payable"]) == ("32.00", "100.00") and desk.status("inv-1") == "adjusted"
    again = desk.post("apply-credit-note", {"credit_id": "cn-1", "invoice_id": "inv-1", "credit_amount": "32.00"}, REVIEWER)     # another key, same credit
    assert again.status_code == 409 and rule_ids(again) == ["CREDIT_ALREADY_APPLIED"] and count(desk.conn, "credit_notes") == 1
    m = desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]["payable"]
    assert m == {"approved_total": "132.00", "credit_total": "32.00", "approved_payable": "100.00"}
    assert desk.post("export-payable", {"batch_id": "b", "invoice_ids": ["inv-1"]}, REVIEWER).status_code == 200      # an adjusted invoice still exports at its total
    assert desk.status("inv-1") == "adjusted"


@pytest.mark.parametrize("amount,rule", [("0.00", "NON_POSITIVE_AMOUNT"), ("-1.00", "NON_POSITIVE_AMOUNT"), ("132.01", "CREDIT_EXCEEDS_INVOICE"),
                                         ("1.005", "MALFORMED_RECORD")])
def test_credit_amount_rules(desk, amount, rule):
    desk.ready("inv-1")
    desk.approve("inv-1")
    r = desk.post("apply-credit-note", {"credit_id": "cn-1", "invoice_id": "inv-1", "credit_amount": amount}, REVIEWER)
    assert r.status_code == 422 and rule_ids(r) == [rule] and count(desk.conn, "credit_notes") == 0


def test_credits_accumulate_up_to_the_invoice_total(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    for n, amt in enumerate(("100.00", "32.00")):
        assert desk.post("apply-credit-note", {"credit_id": f"cn-{n}", "invoice_id": "inv-1", "credit_amount": amt}, REVIEWER).status_code == 200
    over = desk.post("apply-credit-note", {"credit_id": "cn-9", "invoice_id": "inv-1", "credit_amount": "0.01"}, REVIEWER)
    assert over.status_code == 422 and over.json()["error"]["details"][0]["context"] == {"already_credited": "132.00", "total": "132.00"}


# --- atomicity, deadlocks and the audit trail --------------------------------------------------------------------

def test_a_command_and_its_audit_row_are_atomic(desk, monkeypatch):
    desk.ready("inv-1")
    before = {t: count(desk.conn, t) for t in ("approvals", "audit_events", "command_results")}

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(commands, "_set_status", boom)
    r = desk.approve("inv-1")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR" and "disk full" not in r.text
    assert {t: count(desk.conn, t) for t in before} == before and desk.status("inv-1") == "matched"


def test_every_successful_command_writes_its_audit_rows(desk):
    desk.imp("inv-1")
    desk.post("validate-invoice", {"invoice_id": "inv-1"})
    desk.post("match-three-way", {"invoice_id": "inv-1"})
    desk.approve("inv-1")
    desk.post("export-payable", {"batch_id": "b", "invoice_ids": ["inv-1"]}, REVIEWER)
    acts = [(e["action"], e["actor_id"]) for e in desk.conn.execute("SELECT action, actor_id FROM audit_events ORDER BY occurred_at, event_id").fetchall()]
    assert sorted(acts) == sorted([("import-invoice", "usr-clerk01"), ("validate-invoice", "usr-clerk01"), ("match-three-way", "usr-clerk01"),
                                   ("approve-invoice", "usr-rev01"), ("export-payable", "usr-rev01"),
                                   ("export-payable", "usr-rev01")])           # the batch, and the invoice in it


def test_a_deadlock_is_retried_and_after_three_attempts_is_409_concurrent_update(desk, monkeypatch):
    import psycopg
    calls = {"n": 0}
    real = commands._execute_once

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise psycopg.errors.DeadlockDetected("deadlock")
        return real(*a, **k)
    monkeypatch.setattr(commands, "_execute_once", flaky)
    assert desk.imp("inv-1").status_code == 200 and calls["n"] == 3 and count(desk.conn, "invoices") == 1
    calls["n"] = -100

    def always(*a, **k):
        calls["n"] += 1
        raise psycopg.errors.SerializationFailure("serialization")
    monkeypatch.setattr(commands, "_execute_once", always)
    r = desk.imp("inv-2")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONCURRENT_UPDATE" and calls["n"] == -97
    assert commands.MAX_ATTEMPTS == 3 and count(desk.conn, "invoices") == 1


# --- the independent review A-038 (D-09): decisions are stamped by the server, committed outcomes are facts -------------------

def test_a_decision_instant_chosen_by_the_client_is_refused(desk):
    """R5-04: decided_at is not part of C07 or C08; the server stamps it (a client could pick the policy version in force)."""
    desk.ready("inv-1")
    r = desk.post("approve-invoice", {"invoice_id": "inv-1", "decided_at": "2026-09-01T00:00:00Z"}, REVIEWER)
    assert r.status_code == 422 and rule_ids(r) == ["FIELD_UNEXPECTED"]
    r = desk.post("reject-invoice", {"invoice_id": "inv-1", "reason": "x", "decided_at": "2026-09-01T00:00:00Z"}, actor("usr-rev02", "reviewer"))
    assert r.status_code == 422 and rule_ids(r) == ["FIELD_UNEXPECTED"] and count(desk.conn, "approvals") == 0


def test_the_server_stamps_the_decision_and_the_processing_time_follows_it(desk):
    desk.ready("inv-1")
    set_now("2026-10-06T15:30:00Z")
    r = desk.post("approve-invoice", {"invoice_id": "inv-1"}, REVIEWER)
    assert r.status_code == 200 and r.json()["result"]["decided_at"] == "2026-10-06T15:30:00Z"
    p = desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]["processing"]
    assert p["mean_minutes"] == "390.0000" and p["approved_count"] == 1


def test_a_back_dated_invoice_cannot_take_the_quantity_of_an_exported_one(desk):
    """R5-01 / R5-09 (the reviewer's B1): inv-late is approved and exported; inv-back (earlier invoice date, imported later) is blocked."""
    desk.ready("inv-late", [("l1", "pol-1", "6", "20.00")], invoice_date="2026-10-06", imported_at="2026-10-06T09:00:00Z")
    assert desk.approve("inv-late").status_code == 200
    assert desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-late"]}, REVIEWER).status_code == 200
    r = desk.ready("inv-back", [("l2", "pol-1", "6", "20.00")], invoice_number="B-0", invoice_date="2026-10-05", imported_at="2026-10-08T09:00:00Z")
    assert r["status"] == "exception" and r["lines"][0]["reason_code"] == "QUANTITY_BLOCKED"
    assert desk.approve("inv-back").status_code == 409
    assert desk.post("export-payable", {"batch_id": "bat-2", "invoice_ids": ["inv-back"]}, REVIEWER).status_code == 409
    assert (desk.status("inv-late"), desk.status("inv-back")) == ("exported", "exception") and count(desk.conn, "export_rows") == 1
    m = desk.client.get(f"{PREFIX}/metrics").json()
    ex = m["data"]["metrics"]["export"]
    assert (ex["accepted_export_total"], ex["eligible_approved_total"], ex["difference"]) == ("132.00", "132.00", "0.00")
    assert ex["exclusions"] == [{"invoice_id": "inv-back", "reason_code": "EXCEPTION_OPEN"}]
    assert m["data"]["metrics"]["quantities"]["accepted_invoiced_quantity"] == "6.0000" and m["warnings"] == []


def test_a_reversed_receipt_refuses_export_and_credit_and_never_un_exports(desk):
    """R5-03 (the reviewer's B2): C09 and C10 re-derive the match like C07 (409 STALE_MATCH); an exported invoice stays exported."""
    desk.ready("inv-1")
    desk.approve("inv-1")
    desk.conn.execute("UPDATE receipts SET reversed = TRUE")
    for name, body in (("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"]}),
                       ("apply-credit-note", {"credit_id": "cn-1", "invoice_id": "inv-1", "credit_amount": "10.00"})):
        r = desk.post(name, body, REVIEWER)
        assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_MATCH" and rule_ids(r) == ["NOT_MATCHED"], name
    assert count(desk.conn, "export_rows") == 0 and count(desk.conn, "credit_notes") == 0
    m = desk.client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]
    assert m["obligations"]["count"] == 0 and m["approvals"]["invalid_records"][0]["reason_code"] == "NOT_MATCHED"


def test_an_exported_invoice_stays_exported_when_its_receipt_is_reversed_afterwards(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    assert desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"]}, REVIEWER).status_code == 200
    desk.conn.execute("UPDATE receipts SET reversed = TRUE")
    body = desk.client.get(f"{PREFIX}/metrics").json()
    m = body["data"]["metrics"]
    assert (m["obligations"]["count"], m["export"]["accepted_export_total"], m["export"]["difference"]) == (1, "132.00", "0.00")
    assert [(e["invoice_id"], e["exception_type"]) for e in m["exceptions"]["records"]] == [("inv-1", "QUANTITY_BLOCKED")]
    assert body["warnings"] == [] and body["data"]["export_reconciliation"]["stored_minus_derived"] == "0.00"
    r = desk.post("apply-credit-note", {"credit_id": "cn-1", "invoice_id": "inv-1", "credit_amount": "10.00"}, REVIEWER)
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_MATCH"


def test_an_export_cannot_be_stamped_before_the_approval(desk):
    desk.ready("inv-1")
    desk.approve("inv-1", decided_at="2026-10-08T00:00:00Z")
    r = desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"], "exported_at": "2026-10-07T08:00:00Z"}, REVIEWER)
    assert r.status_code == 422 and rule_ids(r) == ["EXPORTED_BEFORE_APPROVAL"] and count(desk.conn, "export_rows") == 0
    assert desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-1"], "exported_at": "2026-10-08T00:00:00Z"}, REVIEWER).status_code == 200


def test_the_creator_cannot_reject_their_own_invoice_and_the_refusal_is_audited(desk):
    """R5-19 (the reviewer's B5): separation of duties covers rejection."""
    desk.ready("inv-1")
    r = desk.post("reject-invoice", {"invoice_id": "inv-1", "reason": "mine"}, actor("usr-clerk01", "reviewer"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "SELF_DECISION" and rule_ids(r) == ["SELF_DECISION"]
    assert desk.status("inv-1") == "matched" and count(desk.conn, "approvals") == 0
    audit = [x["action"] for x in desk.conn.execute("SELECT action FROM audit_events WHERE invoice_id = 'inv-1' ORDER BY occurred_at, event_id").fetchall()]
    assert audit[-1] == "reject-invoice-refused"
    assert desk.post("reject-invoice", {"invoice_id": "inv-1", "reason": "wrong goods"}, actor("usr-rev02", "reviewer")).status_code == 200


def test_the_idempotency_key_is_bound_to_the_role_as_well_as_the_actor(desk):
    """R5-19: the same key and payload from the same actor under another role is not a replay."""
    desk.ready("inv-1")
    first = desk.post("approve-invoice", {"invoice_id": "inv-1"}, actor("usr-rev01", "reviewer"), key="k-role")
    again = desk.post("approve-invoice", {"invoice_id": "inv-1"}, actor("usr-rev01", "reviewer"), key="k-role")
    other = desk.post("approve-invoice", {"invoice_id": "inv-1"}, actor("usr-rev01", "admin"), key="k-role")
    assert first.status_code == 200 and again.status_code == 200 and again.headers["Idempotent-Replay"] == "true"
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED" and "Idempotent-Replay" not in other.headers


def test_same_bytes_with_other_extracted_fields_are_held_for_review(desk):
    """R5-20: not merged (it would seed the identity map); needs_review, a warning, nothing consumed, no command advances it."""
    desk.ready("inv-1")
    r = desk.imp("inv-1b", [("l-b", "pol-1", "6", "20.00")], source_sha256=sha("bytes-inv-1"), invoice_number="OTHER")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "needs_review" and body["result"]["reason_code"] == "BYTES_FIELDS_CONFLICT"
    assert body["result"]["review_against"] == "inv-1" and body["warnings"][0]["code"] == "BYTES_FIELDS_CONFLICT"
    assert desk.status("inv-1b") == "needs_review"
    assert desk.post("validate-invoice", {"invoice_id": "inv-1b"}).status_code == 409
    assert desk.post("match-three-way", {"invoice_id": "inv-1b"}).status_code == 409
    m = desk.client.get(f"{PREFIX}/metrics").json()
    assert m["data"]["metrics"]["duplicates"] == {"groups_detected": 0, "rows_merged": 0, "unresolved_groups": 1}
    assert m["warnings"] == [] and m["data"]["metrics"]["quantities"]["accepted_invoiced_quantity"] == "6.0000"


def test_an_earlier_stamped_copy_cannot_displace_an_exported_canonical_and_cannot_advance(desk):
    """R5-02 (the reviewer's api_attacks4): the committed copy stays canonical; the copy is merged, matched never, exported never."""
    desk.ready("inv-a", [("la", "pol-1", "6", "20.00")], invoice_number="INV-77", invoice_date="2026-10-05", imported_at="2026-10-06T09:00:00Z")
    desk.approve("inv-a")
    assert desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-a"]}, REVIEWER).status_code == 200
    desk.imp("inv-b", [("lb", "pol-1", "6", "20.00")], invoice_number="inv 77", invoice_date="2026-10-05", imported_at="2026-10-05T09:00:00Z")
    assert desk.post("validate-invoice", {"invoice_id": "inv-b"}).status_code == 200
    assert desk.post("match-three-way", {"invoice_id": "inv-b"}).status_code == 409                 # the derivation merges it already
    r = desk.post("find-duplicates", {"invoice_id": "inv-b"})
    assert r.status_code == 200 and r.json()["result"]["canonical_id"] == "inv-a" and r.json()["result"]["merged"] == ["inv-b"]
    assert desk.approve("inv-b").status_code == 409 and desk.post("export-payable", {"batch_id": "bat-2", "invoice_ids": ["inv-b"]}, REVIEWER).status_code == 409
    assert (desk.status("inv-a"), desk.status("inv-b")) == ("exported", "merged") and count(desk.conn, "export_rows") == 1
    m = desk.client.get(f"{PREFIX}/metrics").json()
    assert m["data"]["metrics"]["obligations"] == {"count": 1, "total": "132.00"} and m["warnings"] == []


def test_an_invalid_earlier_stamped_copy_never_becomes_canonical_or_advances(desk):
    desk.ready("inv-a", [("la", "pol-1", "6", "20.00")], invoice_number="INV-77", invoice_date="2026-10-05", imported_at="2026-10-06T09:00:00Z")
    desk.approve("inv-a")
    desk.post("export-payable", {"batch_id": "bat-1", "invoice_ids": ["inv-a"]}, REVIEWER)
    desk.imp("inv-b", [("lb", "pol-1", "6", "20.00")], invoice_number="inv 77", invoice_date="2026-10-05", imported_at="2026-10-04T09:00:00Z")
    assert desk.post("validate-invoice", {"invoice_id": "inv-b"}).json()["status"] == "invalid"           # dated after its import
    for r in (desk.post("find-duplicates", {"invoice_id": "inv-b"}), desk.post("match-three-way", {"invoice_id": "inv-b"}), desk.approve("inv-b"),
              desk.post("export-payable", {"batch_id": "bat-2", "invoice_ids": ["inv-b"]}, REVIEWER)):
        assert r.status_code == 409
    m = desk.client.get(f"{PREFIX}/metrics").json()
    assert m["data"]["metrics"]["duplicates"]["rows_merged"] == 0 and m["warnings"] == []                 # inv-a is not displaced into an invalid canonical


def test_a_future_imported_at_is_clamped_to_the_server_clock(desk):
    r = desk.imp("inv-1", imported_at="2999-01-01T00:00:00Z")
    assert r.status_code == 200 and r.json()["result"]["imported_at"] < "2999" and r.json()["warnings"][0]["code"] == "IMPORTED_AT_CLAMPED"


def test_non_ascii_digits_in_a_decimal_are_refused_by_the_schema(desk):
    r = desk.imp("inv-1", [("l1", "pol-1", "١٠", "20.00")])
    assert r.status_code == 422 and rule_ids(r)[0] == "FIELD_INVALID" and count(desk.conn, "invoice_lines") == 0


def test_the_export_is_reconciled_against_the_stored_rows_too(desk):
    """R5-13: a stored export row the facts do not support is reported (EXPORT_ROWS_DIFFER) beside the derived reconciliation."""
    desk.ready("inv-1")
    desk.conn.execute("INSERT INTO export_batches (batch_id, idempotency_key, requested_by, exported_at, row_count, total) VALUES ('bat-x', 'k', 'u', now(), 1, 132.00)")
    desk.conn.execute("INSERT INTO export_rows VALUES ('exp-bat-x-inv-1', 'bat-x', 'inv-1', now(), 'ven-1', 'INV-1', '2026-10-06', 'USD', 132.00, repeat('a', 64))")
    body = desk.client.get(f"{PREFIX}/metrics").json()
    rec = body["data"]["export_reconciliation"]
    assert rec["only_in_stored_rows"] == ["inv-1"] and rec["stored_total"] == "132.00" and rec["derived_total"] == "0.00"
    assert "EXPORT_ROWS_DIFFER" in [w["code"] for w in body["warnings"]]
