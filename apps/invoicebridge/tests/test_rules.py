"""Business rules of the pure domain, one hand-computed case each (D-01..D-05). No database needed."""
import hashlib
from decimal import Decimal

import pytest

from invoicebridge import DomainError, run_pipeline, validate_batch, window_metrics
from invoicebridge.amounts import invoice_amounts, normalise_number
from invoicebridge.money import dec, frac_str
from invoicebridge.timeutil import parse_ts

from support_db import World, pipeline, sha


def one(w: World, **kw):
    return run_pipeline(w.data(), **kw)


def doc(res, iid):
    return res.documents()["invoices"][iid]


def lines_of(res, iid):
    return [r for r in res.documents()["match_results"] if r["invoice_id"] == iid]


# --- money (D-02, D-P5-1, D-P5-2) -------------------------------------------------------------------------------

def test_rounding_ties_go_away_from_zero():
    """10.125 -> 10.13 (not banker's 10.12); tax 10.125 x 0.10 = 1.0125 -> 1.01; total 11.14."""
    w = World()
    w.pol("p1", qty="100", price="10.125")
    w.receipt("p1", "10")
    w.invoice("inv-1", [("l1", "p1", "1", "10.125")], declared="11.14")
    d = doc(one(w), "inv-1")
    assert (d["subtotal"], d["tax"], d["total"]) == ("10.13", "1.01", "11.14") and d["status"] == "matched"


def test_a_half_cent_subtotal_rounds_up_to_the_cent():
    """0.5 x 0.01 = 0.005 -> 0.01; the tax on 0.005 at 10 % is 0.0005 -> 0.00."""
    w = World()
    w.pol("p1", qty="10", price="0.01")
    w.receipt("p1", "10")
    w.invoice("inv-1", [("l1", "p1", "0.5", "0.01")], declared="0.01")
    d = doc(one(w), "inv-1")
    assert (d["subtotal"], d["tax"], d["total"]) == ("0.01", "0.00", "0.01")


def test_tax_is_computed_once_per_invoice_on_the_unrounded_subtotal():
    """Three lines of 0.05 at 10 %: document tax 0.15 x 0.10 = 0.015 -> 0.02; line-level tax would give 3 x 0.01 = 0.03."""
    w = World()
    w.pol("p1", qty="10", price="0.05")
    w.receipt("p1", "10")
    w.invoice("inv-1", [("l1", "p1", "1", "0.05"), ("l2", "p1", "1", "0.05"), ("l3", "p1", "1", "0.05")], declared="0.17")
    d = doc(one(w), "inv-1")
    assert (d["subtotal"], d["tax"], d["total"]) == ("0.15", "0.02", "0.17")


def test_total_follows_the_declared_order_subtotal_tax_freight_discount():
    w = World()
    w.pol("p1", qty="10", price="20.00")
    w.receipt("p1", "10")
    w.invoice("inv-1", [("l1", "p1", "5", "20.00")], freight="7.50", discount="2.25", declared="115.25")
    d = doc(one(w), "inv-1")      # 100.00 + 10.00 + 7.50 - 2.25
    assert (d["subtotal"], d["tax"], d["freight"], d["invoice_discount"], d["total"]) == ("100.00", "10.00", "7.50", "2.25", "115.25")


def test_quantities_keep_four_decimals_and_unit_prices_six():
    w = World()
    w.pol("p1", qty="10", price="1.234567")
    w.receipt("p1", "10")
    w.invoice("inv-1", [("l1", "p1", "2.7500", "1.234567")], declared="3.74")
    res = one(w)
    assert doc(res, "inv-1")["subtotal"] == "3.40"             # 2.75 x 1.234567 = 3.39506... -> 3.40
    assert lines_of(res, "inv-1")[0]["available_quantity"] == "10.0000"


def test_floats_and_excess_precision_are_refused_not_rounded():
    w = World()
    w.pol("p1", qty="10", price="20.00")
    w.invoice("inv-a", [("la", "p1", "1.00005", "20.00")])         # 5 decimals on a quantity
    w.invoice("inv-b", [("lb", "p1", "1", "20.00")])
    w.d["invoices"][1]["tax_rate"] = 0.1                           # a JSON float
    w.invoice("inv-c", [("lc", "p1", "1", "20.0000001")])          # 7 decimals on a unit price
    res = validate_batch(w.data())
    assert {(r.entity, r.id, r.reason_code) for r in res.rejected if r.entity == "invoices"} == {
        ("invoices", "inv-b", "MALFORMED_RECORD"), ("invoices", "inv-a", "DEPENDENT_REJECTED"), ("invoices", "inv-c", "DEPENDENT_REJECTED")}
    assert {r.id: r.reason_code for r in res.rejected if r.entity == "invoice_lines"} == {
        "la": "MALFORMED_RECORD", "lb": "DEPENDENT_REJECTED", "lc": "MALFORMED_RECORD"}


def test_dec_helper_contract():
    assert dec("12.50", "x", 2) == Decimal("12.50") and dec("12.500", "x", 2) == Decimal("12.500")
    for bad in (1.5, True, "NaN", "abc", "1.005", None, [1]):
        with pytest.raises(DomainError):
            dec(bad, "x", 2)
    assert frac_str(__import__("fractions").Fraction(1, 8), 2) == "0.13" and frac_str(__import__("fractions").Fraction(-1, 8), 2) == "-0.13"


# --- three-way match (D-03) -------------------------------------------------------------------------------------

def three():
    w = World()
    w.pol("p1", qty="10", price="20.00")
    w.receipt("p1", "6")
    return w


def test_quantity_is_consumed_cumulatively_and_a_blocked_invoice_consumes_nothing():
    w = three()
    w.invoice("inv-a", [("la", "p1", "4", "20.00")], at="2026-10-06T09:00:00Z")
    w.invoice("inv-b", [("lb", "p1", "4", "20.00")], at="2026-10-06T09:01:00Z")      # 6 - 4 = 2 available: blocked by 2
    w.invoice("inv-c", [("lc", "p1", "2", "20.00")], at="2026-10-06T09:02:00Z")      # still 2 available: matches
    res = one(w)
    assert lines_of(res, "inv-a")[0]["available_quantity"] == "6.0000"
    b = lines_of(res, "inv-b")[0]
    assert (b["status"], b["reason_code"], b["available_quantity"], b["quantity_variance"]) == ("exception", "QUANTITY_BLOCKED", "2.0000", "2.0000")
    c = lines_of(res, "inv-c")[0]
    assert (c["status"], c["available_quantity"], c["quantity_variance"]) == ("matched", "2.0000", "0.0000")
    q = res.metrics["quantities"]
    assert (q["accepted_invoiced_quantity"], q["invoiced_not_received_quantity"], q["invoiced_not_received_value"]) == ("6.0000", "2.0000", "40.00")


def test_two_lines_on_one_po_line_of_one_invoice_accumulate():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "4", "20.00"), ("l2", "p1", "4", "20.00")], declared="176.00")
    r = lines_of(one(w), "inv-a")
    assert [(x["available_quantity"], x["reason_code"]) for x in r] == [("6.0000", None), ("2.0000", "QUANTITY_BLOCKED")]


def test_matching_order_is_invoice_date_then_import_time_then_id():
    w = three()
    w.invoice("inv-late-import", [("l1", "p1", "6", "20.00")], date="2026-10-05", at="2026-10-09T00:00:00Z")   # earlier DATE, imported later
    w.invoice("inv-early-import", [("l2", "p1", "6", "20.00")], date="2026-10-06", at="2026-10-06T00:00:00Z")
    res = one(w)
    assert doc(res, "inv-late-import")["status"] == "matched" and doc(res, "inv-early-import")["status"] == "exception"


def test_a_reversed_receipt_is_excluded_from_net_received():
    w = three()
    w.receipt("p1", "4", at="2026-10-05T11:00:00Z", reversed=True)
    w.invoice("inv-a", [("l1", "p1", "7", "20.00")], declared="154.00")
    res = one(w)
    assert lines_of(res, "inv-a")[0]["available_quantity"] == "6.0000" and doc(res, "inv-a")["status"] == "exception"
    assert res.metrics["quantities"]["net_received_quantity"] == "6.0000"


def test_a_receipt_after_the_cutoff_does_not_count_and_the_snapshot_says_so():
    w = three()
    w.receipt("p1", "4", at="2026-10-20T00:00:00Z")
    w.invoice("inv-a", [("l1", "p1", "8", "20.00")], declared="176.00")
    w.d["snapshot_cutoffs"] = ["2026-10-10T00:00:00Z"]
    res = one(w)
    assert doc(res, "inv-a")["status"] == "matched"                                  # as of 10-26 all 10 are received
    snap = res.metrics["snapshots"]["2026-10-10T00:00:00Z"]
    assert (snap["net_received_quantity"], snap["accepted_invoiced_quantity"], snap["open_to_receive_quantity"]) == ("6.0000", "0.0000", "4.0000")
    early = one(w, as_of="2026-10-10T00:00:00Z")                                       # as of the cutoff: 8 > 6 received
    assert doc(early, "inv-a")["exception_types"] == ["QUANTITY_BLOCKED"]


@pytest.mark.parametrize("tol,price,status,variance", [
    ("0.00", "20.00", "matched", "0.0000"), ("0.00", "20.01", "exception", "0.0100"),
    ("0.05", "20.05", "matched", "0.0500"), ("0.05", "20.06", "exception", "0.0600"),
    ("0.05", "19.94", "exception", "-0.0600"), ("0.05", "19.95", "matched", "-0.0500")])
def test_price_variance_within_and_beyond_tolerance(tol, price, status, variance):
    w = World(price_per_unit=tol)
    w.pol("p1", qty="10", price="20.00")
    w.receipt("p1", "10")
    w.invoice("inv-a", [("l1", "p1", "1", price)])
    row = lines_of(one(w), "inv-a")[0]
    assert (row["status"], row["price_variance"]) == (status, variance)
    assert row["reason_code"] == (None if status == "matched" else "PRICE_VARIANCE")


def test_price_variance_wins_only_after_quantity_and_both_are_exceptions_of_the_invoice():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "9", "21.00")], declared="207.90")
    row = lines_of(one(w), "inv-a")[0]
    assert row["reason_code"] == "QUANTITY_BLOCKED" and row["price_variance"] == "1.0000"


def test_currency_mismatch_is_never_compared_without_a_rate():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "1", "20.00")], currency="EUR", declared="22.00")
    res = one(w)
    row = lines_of(res, "inv-a")[0]
    assert (row["reason_code"], row["available_quantity"], row["price_variance"]) == ("CURRENCY_MISMATCH", None, None)
    assert doc(res, "inv-a")["exception_types"] == ["CURRENCY_MISMATCH"]


def test_a_line_naming_no_po_line_is_no_po_line_and_atomic_with_its_invoice():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "1", "20.00"), ("l2", "pol-ghost", "1", "5.00")], declared="27.50")
    res = one(w)
    assert [r["reason_code"] for r in lines_of(res, "inv-a")] == [None, "NO_PO_LINE"] and doc(res, "inv-a")["status"] == "exception"
    assert res.metrics["quantities"]["accepted_invoiced_quantity"] == "0.0000"       # the good line consumed nothing either


@pytest.mark.parametrize("declared,status,types,diff", [
    ("22.00", "matched", [], "0.00"), ("22.02", "matched", [], "0.02"), ("21.98", "matched", [], "0.02"),
    ("22.03", "exception", ["ROUNDING_EXCEPTION"], "0.03"), ("21.50", "exception", ["ROUNDING_EXCEPTION"], "0.50")])
def test_invoice_rounding_tolerance_is_0_02(declared, status, types, diff):
    w = three()
    w.invoice("inv-a", [("l1", "p1", "1", "20.00")], declared=declared)    # 20.00 + 2.00 tax = 22.00
    res = one(w)
    assert (doc(res, "inv-a")["status"], doc(res, "inv-a")["exception_types"], doc(res, "inv-a")["rounding_difference"]) == (status, types, diff)


def test_a_tolerated_rounding_difference_is_disclosed_not_hidden():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "1", "20.00")], declared="22.02")
    res = one(w)
    from invoicebridge.metrics import disclosures
    assert disclosures(res.population, res.book)["rounding_tolerated_invoices"] == [{"invoice_id": "inv-a", "rounding_difference": "0.02"}]


@pytest.mark.parametrize("stated,status,tolerated", [("20.00", "matched", False), ("20.01", "matched", True), ("19.99", "matched", True),
                                                       ("20.02", "exception", False), ("19.90", "exception", False)])
def test_line_rounding_tolerance_is_0_01(stated, status, tolerated):
    w = three()
    w.invoice("inv-a", [("l1", "p1", "1", "20.00", stated)], declared="22.00")
    res = one(w)
    from invoicebridge.metrics import disclosures
    assert doc(res, "inv-a")["status"] == status
    assert bool(disclosures(res.population, res.book)["rounding_tolerated_lines"]) == tolerated


def test_the_tolerances_travel_in_the_inputs():
    w = World(rounding_per_invoice="0.50")
    w.pol("p1", qty="10", price="20.00")
    w.receipt("p1", "10")
    w.invoice("inv-a", [("l1", "p1", "1", "20.00")], declared="22.50")
    assert doc(one(w), "inv-a")["status"] == "matched"


# --- duplicates (D-01, D-05) ------------------------------------------------------------------------------------

def test_identity_normalises_the_number_and_uses_the_computed_total():
    assert normalise_number(" inv-1001/a ") == "INV1001A"
    w = three()
    w.invoice("inv-1", [("l1", "p1", "2", "20.00")], number="INV-1001", declared="44.00")
    w.invoice("inv-2", [("l2", "p1", "2", "20.00")], number="inv 1001", declared="40.40", at="2026-10-07T09:00:00Z")   # typo'd declared total
    res = one(w)
    assert doc(res, "inv-2")["status"] == "merged" and doc(res, "inv-2")["merged_into"] == "inv-1"
    rec = res.ingest.merged_records[0]
    assert (rec["reason_code"], rec["group_key"]) == ("DUPLICATE_IDENTITY", "ven-1|INV1001|2026-10-06|44.00")
    assert doc(res, "inv-2")["exception_types"] == [] and res.metrics["duplicates"] == {"groups_detected": 1, "rows_merged": 1, "unresolved_groups": 0}


@pytest.mark.parametrize("override", [{"vendor": "ven-2", "currency": "EUR"}, {"date": "2026-10-07"}, {"number": "INV-1002"}])
def test_a_different_vendor_date_or_number_is_not_a_duplicate(override):
    w = World()
    w.pol("p1", qty="10", price="20.00")
    w.pol("p2", po="po-2", qty="10", price="20.00")
    w.receipt("p1", "10")
    w.receipt("p2", "10")
    w.invoice("inv-1", [("l1", "p1", "1", "20.00")], number="INV-1001", at="2026-10-06T09:00:00Z")
    kw = {"number": "INV-1001", "at": "2026-10-07T09:00:00Z", **override}
    pol = "p2" if kw.get("vendor") == "ven-2" else "p1"
    w.invoice("inv-2", [("l2", pol, "1", "20.00")], **kw)
    res = one(w)
    assert res.metrics["duplicates"]["rows_merged"] == 0 and doc(res, "inv-2")["status"] != "merged"


def test_same_source_bytes_are_one_obligation_under_another_filename():
    w = three()
    w.invoice("inv-1", [("l1", "p1", "6", "20.00")], number="INV-1", digest=sha("same pdf"))
    w.invoice("inv-2", [("l2", "p1", "6", "20.00")], number="INV-1", digest=sha("same pdf"), at="2026-10-08T09:00:00Z")
    w.approve("inv-1")
    res = one(w)
    rec = res.ingest.merged_records[0]
    assert (rec["id"], rec["reason_code"], rec["merged_into"], rec["group_key"]) == ("inv-2", "DUPLICATE_SOURCE_BYTES", "inv-1", f"sha256:{sha('same pdf')}")
    assert res.metrics["obligations"]["count"] == 1 and res.metrics["quantities"]["accepted_invoiced_quantity"] == "6.0000"


def test_same_source_bytes_with_other_extracted_fields_are_held_for_review_not_merged():
    """D-09 (R5-20): a byte-twin whose number differs is a conflicting extraction: needs_review, outside the book."""
    w = three()
    w.invoice("inv-1", [("l1", "p1", "6", "20.00")], number="INV-1", digest=sha("same pdf"))
    w.invoice("inv-2", [("l2", "p1", "6", "20.00")], number="TOTALLY-OTHER", digest=sha("same pdf"), at="2026-10-08T09:00:00Z")
    w.approve("inv-1")
    res = one(w)
    assert res.metrics["duplicates"] == {"groups_detected": 0, "rows_merged": 0, "unresolved_groups": 1}
    assert doc(res, "inv-2")["status"] == "needs_review" and res.metrics["quantities"]["accepted_invoiced_quantity"] == "6.0000"
    assert res.metrics["rates"]["eligible_invoices"] == 1


def test_a_merged_duplicate_consumes_no_received_quantity_and_is_not_eligible():
    w = three()
    w.invoice("inv-1", [("l1", "p1", "3", "20.00")], number="A1")
    w.invoice("inv-2", [("l2", "p1", "3", "20.00")], number="A1", at="2026-10-07T09:00:00Z")
    w.invoice("inv-3", [("l3", "p1", "3", "20.00")], number="B1", at="2026-10-08T09:00:00Z")
    res = one(w)
    assert doc(res, "inv-3")["status"] == "matched"                         # 6 received: 3 + 3, the duplicate took nothing
    assert res.metrics["rates"]["eligible_invoices"] == 2


def test_a_chain_of_duplicates_all_merge_into_the_earliest():
    w = three()
    for n in range(1, 5):
        w.invoice(f"inv-{n}", [(f"l{n}", "p1", "1", "20.00")], number="SAME", at=f"2026-10-0{n + 5}T09:00:00Z")
    res = one(w)
    assert {r["id"]: r["merged_into"] for r in res.ingest.merged_records} == {"inv-2": "inv-1", "inv-3": "inv-1", "inv-4": "inv-1"}
    assert res.metrics["duplicates"] == {"groups_detected": 1, "rows_merged": 3, "unresolved_groups": 0}


# --- atomic invoices and dependent rejection (D-05) -------------------------------------------------------------

def test_one_bad_line_rejects_the_header_its_siblings_and_the_approval_and_credit_on_it():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "1", "20.00"), ("l2", "p1", "0", "20.00")])
    w.approve("inv-a")
    w.credit("cn-1", "inv-a", "5.00")
    res = one(w)
    got = {(r["entity"], r["id"]): r["reason_code"] for r in res.rejected}
    assert got == {("invoices", "inv-a"): "DEPENDENT_REJECTED", ("invoice_lines", "l1"): "DEPENDENT_REJECTED",
                   ("invoice_lines", "l2"): "NON_POSITIVE_QUANTITY", ("approvals", "ap-001"): "DEPENDENT_REJECTED",
                   ("credit_notes", "cn-1"): "DEPENDENT_REJECTED"}
    assert res.metrics["obligations"]["count"] == 0 and doc_count(res) == 0


def doc_count(res):
    return len(res.documents()["invoices"])


def test_unknown_vendor_unknown_po_and_unknown_po_line_codes():
    w = three()
    w.d["purchase_orders"].append({"po_id": "po-x", "vendor_id": "ven-nope", "ordered_at": "2026-10-01T09:00:00Z", "status": "open", "currency": "USD"})
    w.d["po_lines"].append({"po_line_id": "p-x", "po_id": "po-missing", "product_code": "X", "quantity": "1", "unit_price": "1.00"})
    w.d["po_lines"].append({"po_line_id": "p-neg", "po_id": "po-1", "product_code": "X", "quantity": "-1", "unit_price": "1.00"})
    w.receipt("p-ghost", "1")
    w.invoice("inv-v", [("lv", "p1", "1", "20.00")], vendor="ven-nope")
    w.d["approvals"].append({"approval_id": "ap-x", "invoice_id": "inv-zzz", "actor_id": "a", "actor_role": "reviewer", "decision": "approve",
                             "decided_at": "2026-10-07T00:00:00Z"})
    w.d["invoice_lines"].append({"invoice_line_id": "orphan", "invoice_id": "inv-zzz", "po_line_id": "p1", "quantity": "1", "unit_price": "1"})
    got = {(r.entity, r.id): r.reason_code for r in validate_batch(w.data()).rejected}
    assert got == {("purchase_orders", "po-x"): "UNKNOWN_VENDOR", ("po_lines", "p-x"): "UNKNOWN_PO", ("po_lines", "p-neg"): "NON_POSITIVE_QUANTITY",
                   ("receipts", "rc-002"): "UNKNOWN_PO_LINE", ("invoices", "inv-v"): "UNKNOWN_VENDOR", ("invoice_lines", "lv"): "DEPENDENT_REJECTED",
                   ("approvals", "ap-x"): "UNKNOWN_INVOICE", ("invoice_lines", "orphan"): "UNKNOWN_INVOICE"}


def test_duplicate_ids_and_malformed_rows_are_rejected_with_their_raw_row():
    w = three()
    w.d["receipts"].append(dict(w.d["receipts"][0]))                       # the same receipt_id twice
    w.d["vendors"].append({"vendor_id": "ven-9"})                          # missing fields
    w.d["receipts"].append({"receipt_id": "rc-neg", "po_line_id": "p1", "received_quantity": "0", "received_at": "2026-10-05T10:00:00Z", "reversed": False})
    res = validate_batch(w.data())
    got = {(r.entity, r.id): r.reason_code for r in res.rejected}
    assert got == {("receipts", "rc-001"): "DUPLICATE_ID", ("vendors", "ven-9"): "MALFORMED_RECORD", ("receipts", "rc-neg"): "NON_POSITIVE_QUANTITY"}
    assert all(r.raw_row for r in res.rejected)


# --- approval (D-04) --------------------------------------------------------------------------------------------

def approvable():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "6", "20.00")], by="usr-clerk01", declared="132.00")
    return w


def invalid(res):
    return {r["approval_id"]: r["reason_code"] for r in res.metrics["approvals"]["invalid_records"]}


def test_a_matched_invoice_is_not_approved_until_someone_else_decides():
    res = one(approvable())
    assert doc(res, "inv-a")["status"] == "matched" and res.metrics["obligations"]["count"] == 0
    assert res.metrics["matched"]["total"] == "132.00" and res.metrics["payable"]["approved_total"] == "0.00"


def test_self_approval_is_refused_and_recorded():
    w = approvable()
    w.approve("inv-a", actor="usr-clerk01", role="reviewer")
    res = one(w)
    assert invalid(res) == {"ap-001": "SELF_APPROVAL"} and res.metrics["obligations"]["count"] == 0 and doc(res, "inv-a")["status"] == "matched"


def test_role_and_limit_come_from_the_policy_in_force_at_decision_time():
    w = World()
    w.pol("p1", qty="100", price="20.00")
    w.pol("p-big", qty="10", price="250.00")
    w.receipt("p1", "100")
    w.receipt("p-big", "10")
    w.d["approval_policies"].append({"policy_id": "pol-v2", "version_number": 2, "amount_limit": "100.00", "reviewer_role": "reviewer",
                                     "escalation_role": "admin", "effective_from": "2026-10-06T12:00:00Z"})
    w.invoice("inv-a", [("l1", "p1", "6", "20.00")], number="A", declared="132.00")
    w.invoice("inv-b", [("l2", "p1", "0.1", "20.00")], number="B", declared="2.20")
    w.invoice("inv-d", [("l4", "p-big", "1", "250.00")], number="D", declared="275.00")
    w.approve("inv-a", at="2026-10-06T11:59:59Z")                          # v1: limit 5000: 132.00 is fine
    w.approve("inv-b", at="2026-10-06T12:00:00Z")                          # v2 from 12:00: 2.20 <= 100: fine
    w.approve("inv-d", at="2026-10-06T13:00:00Z")                          # v2: 275.00 > 100 for a reviewer
    w.approve("inv-d", actor="usr-adm01", role="admin", at="2026-10-06T14:00:00Z")   # the escalation role may
    res = one(w)
    assert invalid(res) == {"ap-003": "ROLE_OR_LIMIT"}
    assert set(res.book.approved) == {"inv-a", "inv-b", "inv-d"}


def test_a_clerk_and_an_unknown_role_cannot_approve_and_no_policy_means_no_approval():
    w = approvable()
    w.approve("inv-a", actor="usr-clerk09", role="clerk")
    w.approve("inv-a", actor="usr-rev01", role="reviewer", at="2025-12-31T23:59:59Z")     # before any policy is effective
    assert invalid(one(w)) == {"ap-001": "ROLE_OR_LIMIT", "ap-002": "ROLE_OR_LIMIT"}


def test_an_invoice_in_exception_cannot_be_approved():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "9", "20.00")], declared="198.00")
    w.approve("inv-a")
    res = one(w)
    assert invalid(res) == {"ap-001": "NOT_MATCHED"} and res.metrics["obligations"]["count"] == 0


def test_only_the_first_valid_approval_counts_and_approvals_after_the_as_of_are_ignored():
    w = approvable()
    w.approve("inv-a", at="2026-10-06T10:00:00Z")
    w.approve("inv-a", actor="usr-rev02", at="2026-10-06T11:00:00Z")
    w.approve("inv-a", actor="usr-rev03", at="2026-10-30T11:00:00Z")      # after as_of 10-26
    res = one(w)
    assert res.metrics["approvals"]["valid_count"] == 1 and res.metrics["processing"]["approved_count"] == 1
    assert res.metrics["processing"]["mean_minutes"] == "60.0000"


def test_rejection_takes_the_invoice_out_of_the_book_and_frees_its_quantity():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "6", "20.00")], at="2026-10-06T09:00:00Z", declared="132.00")
    w.invoice("inv-b", [("l2", "p1", "6", "20.00")], at="2026-10-06T10:00:00Z", number="B", declared="132.00")
    w.approve("inv-a", actor="usr-rev01", decision="reject", reason="wrong goods", at="2026-10-06T11:00:00Z")
    res = one(w)
    assert doc(res, "inv-a")["status"] == "rejected" and doc(res, "inv-b")["status"] == "matched"
    assert res.metrics["rates"]["eligible_invoices"] == 1 and res.metrics["quantities"]["accepted_invoiced_quantity"] == "6.0000"


def test_a_reject_after_an_approve_and_a_reject_by_a_clerk_are_invalid():
    w = approvable()
    w.approve("inv-a", at="2026-10-06T10:00:00Z")
    w.approve("inv-a", actor="usr-rev02", decision="reject", reason="too late", at="2026-10-06T11:00:00Z")
    w.approve("inv-a", actor="usr-clerk07", role="clerk", decision="reject", reason="nope", at="2026-10-06T09:00:00Z")
    res = one(w)
    assert invalid(res) == {"ap-003": "ROLE_OR_LIMIT", "ap-002": "REJECT_AFTER_APPROVAL"} and doc(res, "inv-a")["status"] == "approved"


def test_a_rejection_needs_a_reason():
    w = approvable()
    w.d["approvals"].append({"approval_id": "ap-9", "invoice_id": "inv-a", "actor_id": "usr-rev01", "actor_role": "reviewer",
                             "decision": "reject", "decided_at": "2026-10-06T10:00:00Z"})
    assert {(r.id, r.reason_code) for r in validate_batch(w.data()).rejected} == {("ap-9", "MALFORMED_RECORD")}


# --- credit notes (D-04) ----------------------------------------------------------------------------------------

def test_a_credit_adjusts_the_payable_once_per_credit_id_and_moves_no_cash():
    w = approvable()
    w.approve("inv-a")
    w.credit("cn-1", "inv-a", "32.00")
    w.credit("cn-1", "inv-a", "32.00")                       # the same credit twice
    res = one(w)
    assert [(r["id"], r["reason_code"]) for r in res.rejected] == [("cn-1", "DUPLICATE_ID")]
    assert res.metrics["payable"] == {"approved_total": "132.00", "credit_total": "32.00", "approved_payable": "100.00"}
    assert doc(res, "inv-a")["status"] == "adjusted" and res.metrics["obligations"]["count"] == 1
    assert res.metrics["export"]["eligible_approved_total"] == "132.00"      # the invoice total, not net of credit


def test_a_credit_on_an_unapproved_invoice_does_not_count_and_one_beyond_the_total_is_rejected():
    w = approvable()
    w.credit("cn-1", "inv-a", "10.00")
    w.credit("cn-2", "inv-a", "132.01")
    res = one(w)
    assert [(r["id"], r["reason_code"]) for r in res.rejected] == [("cn-2", "CREDIT_EXCEEDS_INVOICE")]
    assert res.metrics["payable"]["credit_total"] == "0.00"
    w2 = approvable()
    w2.credit("cn-3", "inv-a", "0.00")
    assert [(r["id"], r["reason_code"]) for r in one(w2).rejected] == [("cn-3", "NON_POSITIVE_AMOUNT")]


# --- export (D-04, D-05) ----------------------------------------------------------------------------------------

def test_export_is_idempotent_by_key_and_batch_and_hashes_the_documented_payload():
    w = approvable()
    w.approve("inv-a")
    w.export("bat-1", "k1", ["inv-a"])
    w.export("bat-1", "k1", ["inv-a"], at="2026-10-07T08:00:30Z")     # same key: a retry
    w.export("bat-1", "k2", ["inv-a"], at="2026-10-07T09:00:00Z")     # another key, same batch id: the prior batch
    res = one(w)
    e = res.metrics["export"]
    assert (e["requests_received"], e["batches_created"], e["repeat_requests_returned_prior"]) == (3, 1, 2)
    assert len(e["rows"]) == 1 and e["rows"][0]["exported_at"] == "2026-10-07T08:00:00Z"
    payload = "inv-a|ven-1|INV-A|2026-10-06|USD|132.00"
    assert e["rows"][0]["content_hash"] == hashlib.sha256(payload.encode()).hexdigest()
    assert doc(res, "inv-a")["status"] == "exported"


def test_only_approved_invoices_export_and_the_others_are_listed_as_exclusions():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "3", "20.00")], number="A", declared="66.00")
    w.invoice("inv-b", [("l2", "p1", "3", "20.00")], number="B", declared="66.00", at="2026-10-06T09:05:00Z")
    w.invoice("inv-c", [("l3", "p1", "5", "20.00")], number="C", declared="110.00", at="2026-10-06T09:10:00Z")   # blocked
    w.approve("inv-a")
    w.export("bat-1", "k1", ["inv-a", "inv-b", "inv-c", "inv-ghost"])
    e = one(w).metrics["export"]
    assert [r["invoice_id"] for r in e["rows"]] == ["inv-a"]
    assert e["exclusions"] == [{"invoice_id": "inv-b", "reason_code": "NOT_APPROVED"}, {"invoice_id": "inv-c", "reason_code": "EXCEPTION_OPEN"}]
    assert e["difference"] == "0.00"


def test_an_invoice_exports_once_across_batches():
    w = approvable()
    w.approve("inv-a")
    w.export("bat-1", "k1", ["inv-a"])
    w.export("bat-2", "k2", ["inv-a"])
    e = one(w).metrics["export"]
    assert (e["batches_created"], len(e["rows"])) == (2, 1)


# --- rates, processing, exceptions, windows ---------------------------------------------------------------------

def test_processing_time_is_exact_minutes_and_rounds_half_up_at_the_end():
    w = approvable()
    w.d["invoices"][0]["imported_at"] = "2026-10-06T09:00:00Z"
    w.approve("inv-a", at="2026-10-06T09:00:00.003Z")                    # 0.003 s = 0.00005 min -> 0.0001
    assert one(w).metrics["processing"]["mean_minutes"] == "0.0001"


def test_rates_have_distinct_validated_invoices_as_denominator():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "2", "20.00")], number="A")
    w.invoice("inv-b", [("l2", "p1", "9", "20.00")], number="B", declared="198.00", at="2026-10-06T09:05:00Z")
    w.invoice("inv-c", [("l3", "p1", "2", "20.00")], number="A", at="2026-10-07T09:00:00Z")          # a duplicate of inv-a
    m = one(w).metrics
    assert m["rates"] == {"eligible_invoices": 2, "straight_through_rate": "0.500000", "exception_rate": "0.500000"}


def test_exception_records_get_stable_ids_and_the_owner_as_of_the_cutoff():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "1", "21.00"), ("l2", "p1", "9", "20.00")], declared="221.10")   # PRICE_VARIANCE and QUANTITY_BLOCKED
    res = run_pipeline(w.data())
    recs = res.metrics["exceptions"]["records"]
    assert [(r["exception_id"], r["exception_type"], r["owner_id"], r["status"]) for r in recs] == [
        ("exc-001", "PRICE_VARIANCE", None, "open"), ("exc-002", "QUANTITY_BLOCKED", None, "open")]
    from invoicebridge.models import Assignment, ExceptionRecord
    from invoicebridge.metrics import compute_metrics
    pop = res.population
    pop.exceptions = [ExceptionRecord("exc-077", "inv-a", "QUANTITY_BLOCKED")]
    pop.assignments = [Assignment("exc-077", "usr-x", parse_ts("2026-10-08T00:00:00Z")), Assignment("exc-077", "usr-y", parse_ts("2026-10-12T00:00:00Z"))]
    owner = lambda at: {r["exception_type"]: (r["exception_id"], r["owner_id"], r["status"]) for r in compute_metrics(pop, parse_ts(at))["exceptions"]["records"]}  # noqa: E731
    assert owner("2026-10-07T00:00:00Z")["QUANTITY_BLOCKED"] == ("exc-077", None, "open")          # backlog as of a cutoff
    assert owner("2026-10-09T00:00:00Z")["QUANTITY_BLOCKED"] == ("exc-077", "usr-x", "assigned")
    assert owner("2026-10-26T00:00:00Z")["QUANTITY_BLOCKED"] == ("exc-077", "usr-y", "assigned")


def test_window_is_half_open_and_matching_still_sees_the_whole_book():
    w = three()
    w.invoice("inv-a", [("l1", "p1", "6", "20.00")], number="A", at="2026-10-06T09:00:00Z", declared="132.00")
    w.invoice("inv-b", [("l2", "p1", "1", "20.00")], number="B", at="2026-10-08T09:00:00Z", declared="22.00")
    pop = pipeline(w.data()).population
    lo, hi = parse_ts("2026-10-08T00:00:00Z"), parse_ts("2026-10-09T00:00:00Z")
    out = window_metrics(pop, (lo, hi))["metrics"]
    assert out["rates"]["eligible_invoices"] == 1 and out["exceptions"]["by_reason"]["QUANTITY_BLOCKED"] == 1     # inv-b blocked by inv-a's 6
    at_edge = window_metrics(pop, (None, parse_ts("2026-10-08T09:00:00Z")))["metrics"]           # inv-b imported AT `to`: excluded
    assert at_edge["rates"]["eligible_invoices"] == 1
    with pytest.raises(DomainError) as err:
        window_metrics(pop, (hi, lo))
    assert err.value.code == "INVALID_WINDOW"
    with pytest.raises(DomainError) as err:
        window_metrics(pop, (None, None), group_by="colour")
    assert err.value.code == "INVALID_GROUP"


def test_group_by_vendor_and_currency_split_the_cohort():
    w = World()
    w.pol("p1", qty="10", price="20.00")
    w.pol("p2", po="po-2", qty="10", price="5.00")
    w.receipt("p1", "10")
    w.receipt("p2", "10")
    w.invoice("inv-a", [("l1", "p1", "1", "20.00")], number="A")
    w.invoice("inv-b", [("l2", "p2", "2", "5.00")], number="B", vendor="ven-2", currency="EUR", at="2026-10-06T10:00:00Z")
    pop = pipeline(w.data()).population
    groups = window_metrics(pop, (None, None), group_by="vendor")["groups"]
    assert [(g["key"], g["metrics"]["matched"]["total"], g["metrics"]["quantities"]["ordered_quantity"]) for g in groups] == [
        ("ven-1", "22.00", "10.0000"), ("ven-2", "11.00", "10.0000")]
    assert [g["key"] for g in window_metrics(pop, (None, None), group_by="currency")["groups"]] == ["EUR", "USD"]
    whole = window_metrics(pop, (None, None))["metrics"]
    assert whole["matched"]["total"] == "33.00"


def test_invoice_amounts_helper_matches_the_document():
    res = pipeline(three().data())
    w = three()
    w.invoice("inv-z", [("lz", "p1", "6", "20.00")], declared="132.00")
    inv = pipeline(w.data()).population.invoices[0]
    assert invoice_amounts(inv) == (Decimal("120.00"), Decimal("12.00"), Decimal("132.00"))
    assert res.metrics["rates"]["straight_through_rate"] is None
