"""Builds tests/review_cases.json: the regression cases of the independent review A-038 (findings R5-xx), each with the inputs
and the HAND-DERIVED expectations (written out below, never captured from the code). The same file is read by
tests/test_review_findings.py (Python), tests/test_sql_reference.py (PostgreSQL) and web/scripts/review-check.ts (TypeScript),
so the three implementations are held to one set of values.

    ../../.venv/bin/python tests/make_review_cases.py        # rewrites tests/review_cases.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "domain"), str(HERE.parent)]
from support_db import World, golden_inputs, sha  # noqa: E402

CASES: list[dict] = []


def case(name: str, finding: str, note: str, world, expect: dict, **extra) -> None:
    inputs = world.data() if isinstance(world, World) else world
    CASES.append({"name": name, "finding": finding, "note": note, "inputs": inputs, "expect": expect, **extra})


def empty_export(**kw) -> dict:
    return {"requests_received": 0, "batches_created": 0, "repeat_requests_returned_prior": 0, "rows": [], **kw}


# ---- R5-01 / R5-09: a back-dated invoice cannot take the receipt of an exported one ---------------------------------------
w = World(); w.pol("pol-1"); w.receipt("pol-1", "6")
w.invoice("inv-late", [("il-late", "pol-1", "6", "20.00")], date="2026-10-06", at="2026-10-06T09:00:00Z")
w.approve("inv-late", at="2026-10-06T15:00:00Z"); w.export("bat-1", "k1", ["inv-late"], at="2026-10-07T08:00:00Z")
w.invoice("inv-back", [("il-back", "pol-1", "6", "20.00")], number="B-0", date="2026-10-05", at="2026-10-08T09:00:00Z")
w.d["snapshot_cutoffs"] = ["2026-10-07T12:00:00Z"]
q0 = {"accepted_invoiced_quantity": "6.0000", "invoiced_not_received_quantity": "0.0000", "net_received_quantity": "6.0000"}
case("back_dated_after_export", "R5-01,R5-09",
     "inv-late is approved and exported; inv-back (earlier invoice date, imported later) finds the 6 received units consumed: it is QUANTITY_BLOCKED, inv-late stays exported",
     w, {"docs": {"inv-late": ["exported", []], "inv-back": ["exception", ["QUANTITY_BLOCKED"]]},
         "metrics": {"obligations": {"count": 1, "total": "132.00"},
                     "quantities": {"accepted_invoiced_quantity": "6.0000", "invoiced_not_received_quantity": "6.0000", "invoiced_not_received_value": "120.00"},
                     "snapshots": {"2026-10-07T12:00:00Z": q0},
                     "export": {"accepted_export_total": "132.00", "eligible_approved_total": "132.00", "difference": "0.00",
                                "exclusions": [{"invoice_id": "inv-back", "reason_code": "EXCEPTION_OPEN"}]},
                     "rates": {"eligible_invoices": 2, "exception_rate": "0.500000"}}})

# ---- R5-03: a receipt reversed after export does not un-export --------------------------------------------------------------
w = World(); w.pol("pol-1"); w.receipt("pol-1", "6", reversed=True); w.receipt("pol-1", "0.0001", at="2026-10-04T00:00:00Z")
w.invoice("inv-1", [("il-1", "pol-1", "6", "20.00")]); w.approve("inv-1"); w.export("bat-1", "k1", ["inv-1"])
case("receipt_reversed_after_export", "R5-03",
     "the invoice stays exported (obligation 132.00, one export row, difference 0.00) and the reversal shows as a QUANTITY_BLOCKED exception ON the exported invoice",
     w, {"docs": {"inv-1": ["exported", ["QUANTITY_BLOCKED"]]},
         "metrics": {"obligations": {"count": 1, "total": "132.00"}, "approvals": {"valid_count": 1, "invalid_records": []},
                     "exceptions": {"open_count": 1, "records": [{"invoice_id": "inv-1", "exception_type": "QUANTITY_BLOCKED"}]},
                     "quantities": {"accepted_invoiced_quantity": "0.0000", "net_received_quantity": "0.0001"},
                     "export": {"accepted_export_total": "132.00", "difference": "0.00", "exclusions": [], "batches_created": 1},
                     "rates": {"straight_through_rate": "0.000000", "exception_rate": "1.000000"}}})

w = World(); w.pol("pol-1"); w.receipt("pol-1", "6", reversed=True)
w.invoice("inv-1", [("il-1", "pol-1", "6", "20.00")]); w.approve("inv-1")
case("receipt_reversed_after_approval_only", "R5-03",
     "approved but not exported: the approval no longer matches (NOT_MATCHED) and the obligation drops, as before",
     w, {"docs": {"inv-1": ["exception", ["QUANTITY_BLOCKED"]]},
         "metrics": {"obligations": {"count": 0}, "approvals": {"valid_count": 0, "invalid_records": [{"approval_id": "ap-001", "reason_code": "NOT_MATCHED"}]}}})

# ---- R5-09: an export row needs a valid approval at or before it; the difference is always explained -------------------------
w = World(); w.pol("pol-1", qty="100"); w.receipt("pol-1", "100")
w.invoice("inv-1", [("il-1", "pol-1", "6", "20.00")]); w.approve("inv-1")
w.credit("cn-1", "inv-1", "100.00"); w.credit("cn-2", "inv-1", "40.00")
w.invoice("inv-2", [("il-2", "pol-1", "1", "20.00")]); w.approve("inv-2"); w.credit("cn-3", "inv-2", "22.01")
w.invoice("inv-3", [("il-3", "pol-1", "1", "20.00")], declared="99.00")
w.invoice("inv-4", [("il-4", "pol-1", "1", "20.00")]); w.approve("inv-4", at="2026-10-08T00:00:00Z")
w.export("bat-1", "k1", ["inv-1", "inv-3", "inv-4"], at="2026-10-07T08:00:00Z")
w.export("bat-1", "k2", ["inv-2"], at="2026-10-07T09:00:00Z"); w.export("bat-2", "k1", ["inv-2"], at="2026-10-07T10:00:00Z")
case("export_needs_a_prior_approval", "R5-09,R5-13",
     "inv-4 is approved AFTER its export instant: that row is invalid and listed (EXPORT_BEFORE_APPROVAL); inv-2's two requests repeat a batch id / a key; the difference -44.00 is exactly the two approved-not-exported invoices",
     w, {"docs": {"inv-1": ["adjusted", []], "inv-2": ["approved", []], "inv-3": ["exception", ["ROUNDING_EXCEPTION"]], "inv-4": ["approved", []]},
         "rejected": [["credit_notes", "cn-2", "CREDIT_EXCEEDS_INVOICE"], ["credit_notes", "cn-3", "CREDIT_EXCEEDS_INVOICE"]],
         "metrics": {"obligations": {"count": 3, "total": "176.00"}, "payable": {"credit_total": "100.00", "approved_payable": "76.00"},
                     "export": {"requests_received": 3, "batches_created": 1, "repeat_requests_returned_prior": 2,
                                "accepted_export_total": "132.00", "eligible_approved_total": "176.00", "difference": "-44.00",
                                "exclusions": [{"invoice_id": "inv-2", "reason_code": "APPROVED_NOT_EXPORTED"},
                                               {"invoice_id": "inv-3", "reason_code": "EXCEPTION_OPEN"},
                                               {"invoice_id": "inv-4", "reason_code": "EXPORT_BEFORE_APPROVAL"}]},
                     "processing": {"approved_count": 3, "mean_minutes": "1040.0000", "pending_count": 1}}})

# ---- R5-02: a committed canonical copy is never displaced -------------------------------------------------------------------
w = World(); w.pol("pol-1"); w.receipt("pol-1", "6")
w.invoice("inv-a", [("la", "pol-1", "6", "20.00")], number="SAME", at="2026-10-07T09:00:00Z")
w.approve("inv-a", at="2026-10-07T10:00:00Z")
w.invoice("inv-b", [("lb", "pol-1", "6", "20.00")], number="same", at="2026-10-06T09:00:00Z")        # stamped EARLIER, other bytes
case("committed_canonical_is_not_displaced", "R5-02",
     "inv-a is approved; its identity twin inv-b is stamped earlier. The canonical copy is the committed one: inv-b merges into inv-a, not the other way round",
     w, {"docs": {"inv-a": ["approved", []], "inv-b": ["merged", []]},
         "metrics": {"duplicates": {"groups_detected": 1, "rows_merged": 1, "unresolved_groups": 0}, "obligations": {"count": 1, "total": "132.00"},
                     "quantities": {"accepted_invoiced_quantity": "6.0000"}, "approvals": {"valid_count": 1, "invalid_records": []}}})

# ---- R5-04: an approval before the import is invalid, processing time is never negative -------------------------------------
w = World(); w.pol("pol-1"); w.receipt("pol-1", "6")
w.invoice("inv-1", [("il-1", "pol-1", "6", "20.00")], at="2026-10-06T09:00:00Z")
w.approve("inv-1", at="2026-10-01T00:00:00Z")
case("approval_before_import", "R5-04",
     "decided_at 2026-10-01 is before the import 2026-10-06T09:00: invalid BEFORE_IMPORT, no obligation, no (negative) processing time",
     w, {"docs": {"inv-1": ["matched", []]},
         "metrics": {"approvals": {"valid_count": 0, "invalid_records": [{"approval_id": "ap-001", "reason_code": "BEFORE_IMPORT"}]},
                     "processing": {"approved_count": 0, "mean_minutes": None, "pending_count": 1}, "obligations": {"count": 0}}})

# ---- R5-05: only a valid invoice can be canonical ----------------------------------------------------------------------------
w = World(); w.pol("pol-1", qty="100"); w.receipt("pol-1", "100")
w.invoice("inv-p", [("il-p", "pol-1", "1", "20.00")], number="Q-1", date="2026-10-07", at="2026-10-06T09:00:00Z")      # dated after its import: invalid
w.invoice("inv-q", [("il-q", "pol-1", "1", "20.00")], number="Q-1", date="2026-10-07", at="2026-10-08T09:00:00Z")
case("merge_into_invalid_canonical", "R5-05",
     "inv-p fails C02 (INVOICE_DATE_IN_FUTURE); its re-sent copy inv-q is valid and stays in the book instead of merging into an invalid canonical",
     w, {"docs": {"inv-p": ["invalid", []], "inv-q": ["matched", []]},
         "metrics": {"duplicates": {"groups_detected": 0, "rows_merged": 0, "unresolved_groups": 0}, "rates": {"eligible_invoices": 1},
                     "matched": {"invoice_count": 1, "total": "22.00"}, "quantities": {"accepted_invoiced_quantity": "1.0000"}}})

# ---- R5-06: the PO line must belong to the invoice's vendor ----------------------------------------------------------------
w = World()
w.d["purchase_orders"].append({"po_id": "po-3", "vendor_id": "ven-2", "ordered_at": "2026-10-01T09:00:00Z", "status": "open", "currency": "USD"})
w.pol("pol-3", po="po-3", qty="10"); w.receipt("pol-3", "10")
w.invoice("inv-5", [("il-5", "pol-3", "10", "20.00")])                         # ven-1 bills a line of ven-2's purchase order
case("vendor_mismatch", "R5-06",
     "the PO line exists, in the right currency and fully received, but belongs to another vendor: NO_PO_LINE, nothing consumed",
     w, {"docs": {"inv-5": ["exception", ["NO_PO_LINE"]]},
         "metrics": {"exceptions": {"by_reason": {"NO_PO_LINE": 1, "QUANTITY_BLOCKED": 0}}, "quantities": {"accepted_invoiced_quantity": "0.0000"}}})

# ---- R5-07: duplicates ignore nothing later than the cutoff ------------------------------------------------------------------
g = golden_inputs(); g["as_of"] = "2026-10-07T00:00:00Z"; g["snapshot_cutoffs"] = []
case("duplicates_respect_the_cutoff", "R5-07,R5-13",
     "the golden fixture as of 2026-10-07T00:00Z: the re-sent PDF inv-003 (imported 10-07T09:00) does not exist yet, the export (10-07T08:00) has not happened: nothing merged, inv-001 is approved and listed APPROVED_NOT_EXPORTED",
     g, {"docs": {"inv-001": ["approved", []], "inv-002": ["exception", ["QUANTITY_BLOCKED"]], "inv-003": ["received", []]},
         "metrics": {"duplicates": {"groups_detected": 0, "rows_merged": 0, "unresolved_groups": 0},
                     "export": {"requests_received": 0, "accepted_export_total": "0.00", "eligible_approved_total": "132.00", "difference": "-132.00",
                                "exclusions": [{"invoice_id": "inv-001", "reason_code": "APPROVED_NOT_EXPORTED"}, {"invoice_id": "inv-002", "reason_code": "EXCEPTION_OPEN"}]}}})

# ---- R5-08: only a VALID earlier approval blocks a rejection --------------------------------------------------------------------
w = World(); w.pol("pol-1", qty="10000", price="1.00"); w.receipt("pol-1", "10000")
w.invoice("inv-ir", [("il-ir", "pol-1", "10", "1.00")]); w.approve("inv-ir", actor="usr-clerk01")          # ap-001: self-approval, invalid
w.approve("inv-ir", at="2026-10-07T00:00:00Z", decision="reject", reason="wrong goods")                      # ap-002: a valid rejection
w.invoice("inv-rar", [("il-rar", "pol-1", "10", "1.00")], number="RAR"); w.approve("inv-rar")                # ap-003: valid
w.approve("inv-rar", at="2026-10-07T00:00:00Z", decision="reject", reason="changed mind")                    # ap-004: after a valid approval
case("rejection_after_invalid_approval", "R5-08",
     "an invalid (self) approval does not block the rejection (that approval then lists as NOT_MATCHED: the invoice has left the book); a valid approval does block it (REJECT_AFTER_APPROVAL)",
     w, {"docs": {"inv-ir": ["rejected", []], "inv-rar": ["approved", []]},
         "metrics": {"approvals": {"valid_count": 1, "invalid_records": [{"approval_id": "ap-001", "reason_code": "NOT_MATCHED"},
                                                                         {"approval_id": "ap-004", "reason_code": "REJECT_AFTER_APPROVAL"}]},
                     "rates": {"eligible_invoices": 1}, "obligations": {"count": 1, "total": "11.00"}}})

# ---- R5-19: separation of duties covers rejection -----------------------------------------------------------------------------
w = World(); w.pol("pol-1"); w.receipt("pol-1", "6")
w.invoice("inv-1", [("il-1", "pol-1", "6", "20.00")]); w.approve("inv-1", actor="usr-clerk01", role="reviewer", decision="reject", reason="mine")
case("creator_cannot_reject", "R5-19",
     "the creator's own rejection is invalid (SELF_DECISION): the invoice stays in the book",
     w, {"docs": {"inv-1": ["matched", []]},
         "metrics": {"approvals": {"invalid_records": [{"approval_id": "ap-001", "reason_code": "SELF_DECISION"}]}, "rates": {"eligible_invoices": 1}}})

# ---- R5-10: the history pair appears only where a stored exception history adds invoices ----------------------------------
g = golden_inputs()
case("exception_history_rates", "R5-10",
     "golden plus a stored history (a resolved PRICE_VARIANCE on inv-001): straight_through_rate stays 'not blocked at the cutoff' 0.500000; the history pair is published: 0 of 2 never excepted",
     g, {"metrics": {"rates": {"eligible_invoices": 2, "straight_through_rate": "0.500000", "exception_rate": "0.500000",
                               "straight_through_never_excepted_rate": "0.000000", "ever_excepted_rate": "1.000000"}}},
     stored={"exceptions": [{"exception_id": "exc-001", "invoice_id": "inv-002", "exception_type": "QUANTITY_BLOCKED", "status": "open"},
                            {"exception_id": "exc-002", "invoice_id": "inv-001", "exception_type": "PRICE_VARIANCE", "status": "resolved"}],
             "exception_assignments": []})
case("golden_rates_have_no_history_pair", "R5-10",
     "the golden fixture's own stored exception equals its derived one: no extra keys, the published rates are exactly expected.json's",
     golden_inputs(), {"metrics": {"rates": {"eligible_invoices": 2, "straight_through_rate": "0.500000", "exception_rate": "0.500000"}}},
     stored={"exceptions": [{"exception_id": "exc-001", "invoice_id": "inv-002", "exception_type": "QUANTITY_BLOCKED", "status": "open"}], "exception_assignments": []},
     exact_keys={"metrics.rates": ["eligible_invoices", "exception_rate", "straight_through_rate"]})

# ---- R5-11 / R5-20: two currencies, and a byte-twin with other extracted fields -----------------------------------------------
w = World(); w.pol("pol-1", qty="100"); w.receipt("pol-1", "100")
w.invoice("inv-a", [("il-a", "pol-1", "1", "20.00")], number="X-1", at="2026-10-06T09:00:00Z")
w.invoice("inv-b", [("il-b", "pol-1", "1", "20.00")], number="x 1", at="2026-10-06T10:00:00Z")                      # identity duplicate, other bytes
w.invoice("inv-c", [("il-c", "pol-1", "2", "20.00")], number="X-2", at="2026-10-06T11:00:00Z", digest=sha("bytes-inv-a"))   # the bytes of inv-a, other fields
w.invoice("inv-d", [("il-d", "pol-1", "2", "20.00")], number="X-2", at="2026-10-06T12:00:00Z")                      # the identity of inv-c: must NOT merge into inv-a
w.pol("pol-9", po="po-2", qty="100", price="20.00"); w.receipt("pol-9", "100")
w.invoice("inv-e", [("il-e", "pol-9", "1", "20.00")], number="X-1", vendor="ven-2", currency="EUR", at="2026-10-06T13:00:00Z")
w.approve("inv-a", at="2026-10-07T09:00:00Z"); w.approve("inv-e", at="2026-10-07T09:00:00Z")
case("byte_twin_with_other_fields_and_two_currencies", "R5-20,R5-11",
     "inv-c has the bytes of inv-a but another number and quantity: held for review (needs_review), unresolved_groups 1, and it seeds no identity: inv-d stays its own invoice. Two currencies: the sums remain and each metric carries by_currency",
     w, {"docs": {"inv-a": ["approved", []], "inv-b": ["merged", []], "inv-c": ["needs_review", []], "inv-d": ["matched", []], "inv-e": ["approved", []]},
         "metrics": {"duplicates": {"groups_detected": 1, "rows_merged": 1, "unresolved_groups": 1},
                     "matched": {"invoice_count": 3, "total": "88.00",
                                 "by_currency": {"EUR": {"invoice_count": 1, "amount_before_tax": "20.00", "tax": "2.00", "total": "22.00"},
                                                 "USD": {"invoice_count": 2, "amount_before_tax": "60.00", "tax": "6.00", "total": "66.00"}}},
                     "obligations": {"count": 2, "total": "44.00", "by_currency": {"EUR": {"count": 1, "total": "22.00"}, "USD": {"count": 1, "total": "22.00"}}},
                     "payable": {"approved_payable": "44.00", "by_currency": {"EUR": {"approved_total": "22.00", "credit_total": "0.00", "approved_payable": "22.00"},
                                                                             "USD": {"approved_total": "22.00", "credit_total": "0.00", "approved_payable": "22.00"}}},
                     "export": {"difference": "-44.00", "by_currency": {"EUR": {"accepted_export_total": "0.00", "eligible_approved_total": "22.00", "difference": "-22.00"},
                                                                       "USD": {"accepted_export_total": "0.00", "eligible_approved_total": "22.00", "difference": "-22.00"}}},
                     "quantities": {"accepted_invoiced_quantity": "4.0000"}}})

# ---- R5-16: ids outside the BMP order by code point ------------------------------------------------------------------------
w = World(); w.pol("pol-1", qty="10"); w.receipt("pol-1", "4")
w.invoice("inv-\U0001F600", [("il-x", "pol-1", "4", "20.00")], number="E-1")
w.invoice("inv-￿", [("il-y", "pol-1", "4", "20.00")], number="E-2")
case("ids_outside_the_bmp", "R5-16",
     "same date and instant: the tie is broken by invoice id in code-point order, U+FFFF before U+1F600 (UTF-16 order says the opposite)",
     w, {"docs": {"inv-￿": ["matched", []], "inv-\U0001F600": ["exception", ["QUANTITY_BLOCKED"]]},
         "metrics": {"exceptions": {"records": [{"invoice_id": "inv-\U0001F600", "exception_type": "QUANTITY_BLOCKED"}]}}})

# ---- R5-17: only ASCII decimal spellings ----------------------------------------------------------------------------------------
for tag, spelling in (("underscore", "1_0"), ("exponent", "1E+1"), ("arabic_indic_digits", "١٠")):
    w = World(); w.pol("pol-1", qty="10"); w.receipt("pol-1", "10")
    w.invoice("inv-1", [("il-1", "pol-1", "10", "20.00")]); w.d["invoice_lines"][0]["quantity"] = spelling
    case(f"decimal_spelling_{tag}", "R5-17", f"the quantity {spelling!r} is not an ASCII decimal: the line and its invoice are rejected, as in TypeScript",
         w, {"docs": {}, "rejected": [["invoice_lines", "il-1", "MALFORMED_RECORD"], ["invoices", "inv-1", "DEPENDENT_REJECTED"]],
             "metrics": {"matched": {"invoice_count": 0}, "obligations": {"count": 0}}})

OUT = HERE / "review_cases.json"
if __name__ == "__main__":
    OUT.write_text(json.dumps({"generated_by": "tests/make_review_cases.py", "cases": CASES}, indent=1, sort_keys=True) + "\n")
    print(f"wrote {OUT.name}: {len(CASES)} cases")
