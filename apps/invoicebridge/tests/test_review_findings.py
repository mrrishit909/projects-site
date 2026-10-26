"""Regression tests for the independent review A-038 (findings R5-01 .. R5-22; decisions in docs/contracts.md D-09).

The cases and their hand-derived expectations are in tests/review_cases.json (written by tests/make_review_cases.py); the same
file is checked against PostgreSQL in tests/test_sql_reference.py and against the TypeScript mirror by web/scripts/review-check.ts.
"""
import json
from pathlib import Path

import pytest

from invoicebridge import run_pipeline
from invoicebridge.book import derive
from invoicebridge.metrics import compute_metrics, window_metrics
from invoicebridge.models import ExceptionRecord
from invoicebridge.timeutil import parse_ts

from support_db import World, golden_inputs, sha  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CASES = {c["name"]: c for c in json.loads((ROOT / "tests" / "review_cases.json").read_text())["cases"]}


def subset(got, want, path="$"):
    """Every key of ``want`` is in ``got`` with an equal (recursively subset) value; lists are compared element by element."""
    if isinstance(want, dict):
        assert isinstance(got, dict), (path, got)
        for k, v in want.items():
            assert k in got, (path, "missing", k, sorted(got))
            subset(got[k], v, f"{path}.{k}")
    elif isinstance(want, list):
        assert isinstance(got, list) and len(got) == len(want), (path, got, want)
        for i, (g, w) in enumerate(zip(got, want)):
            subset(g, w, f"{path}[{i}]")
    else:
        assert got == want, (path, got, want)


def run_case(case):
    """The Python domain's answer for a case (a stored exception history is added the way the API read path does)."""
    res = run_pipeline(case["inputs"])
    if case.get("stored"):
        res.population.exceptions = [ExceptionRecord(e["exception_id"], e["invoice_id"], e["exception_type"]) for e in case["stored"]["exceptions"]]
        res.metrics = compute_metrics(res.population, parse_ts(case["inputs"]["as_of"]), [parse_ts(c) for c in case["inputs"].get("snapshot_cutoffs", [])])
    return res


@pytest.mark.parametrize("name", sorted(CASES))
def test_review_case_matches_the_hand_derived_expectation(name):
    case = CASES[name]
    res = run_case(case)
    docs = res.documents()["invoices"]
    want = case["expect"]
    for iid, (status, types) in want.get("docs", {}).items():
        assert (docs[iid]["status"], docs[iid]["exception_types"]) == (status, types), iid
    if "docs" in want and not want["docs"]:
        assert docs == {}
    if "rejected" in want:
        assert [[r.entity, r.id, r.reason_code] for r in res.ingest.rejected] == want["rejected"]
    subset(res.metrics, want.get("metrics", {}), "metrics")
    for path, keys in case.get("exact_keys", {}).items():
        node = res.metrics
        for part in path.split(".")[1:]:
            node = node[part]
        assert sorted(node) == keys, path


def test_every_finding_has_a_case():
    covered = {f for c in CASES.values() for f in c["finding"].split(",")}
    assert covered >= {"R5-01", "R5-02", "R5-03", "R5-04", "R5-05", "R5-06", "R5-07", "R5-08", "R5-09", "R5-10", "R5-11", "R5-13",
                       "R5-16", "R5-17", "R5-19", "R5-20"}


# --- R5-01: the committed invoice keeps its consumption, whatever arrives later -----------------------------------------

def test_consumption_order_is_committed_first_then_book_order():
    """Three invoices of 4 against 10 received: the committed one (approved) takes its 4 first even though it is last in book order."""
    w = World(); w.pol("pol-1"); w.receipt("pol-1", "10")
    w.invoice("inv-a", [("la", "pol-1", "4", "20.00")], number="A", date="2026-10-01", at="2026-10-06T09:00:00Z")
    w.invoice("inv-b", [("lb", "pol-1", "4", "20.00")], number="B", date="2026-10-02", at="2026-10-06T09:00:00Z")
    w.invoice("inv-c", [("lc", "pol-1", "4", "20.00")], number="C", date="2026-10-03", at="2026-10-06T09:00:00Z")
    w.approve("inv-c", at="2026-10-06T12:00:00Z")
    res = run_pipeline(w.data())
    docs = res.documents()["invoices"]
    assert (docs["inv-c"]["status"], docs["inv-a"]["status"], docs["inv-b"]["status"]) == ("approved", "matched", "exception")
    assert res.metrics["quantities"]["accepted_invoiced_quantity"] == "8.0000"


def test_a_book_never_changes_under_a_later_fact_at_the_same_cutoff():
    """derive(pop, c) ignores every fact after c: a later back-dated invoice does not change the book of an earlier cutoff."""
    case = CASES["back_dated_after_export"]
    res = run_pipeline(case["inputs"])
    early = derive(res.population, parse_ts("2026-10-07T12:00:00Z"))
    assert early.status["inv-late"] == "exported" and early.status["inv-back"] == "received"
    assert early.export_rows == derive(res.population, None).export_rows                 # the batch's content never changes afterwards


# --- R5-02 / R5-20: duplicates ----------------------------------------------------------------------------------------------

def test_two_committed_copies_keep_the_earlier_commit_as_canonical_and_the_other_is_listed_invalid():
    w = World(); w.pol("pol-1"); w.receipt("pol-1", "10")
    w.invoice("inv-a", [("la", "pol-1", "3", "20.00")], number="TWIN", at="2026-10-06T09:00:00Z")
    w.invoice("inv-b", [("lb", "pol-1", "3", "20.00")], number="TWIN", at="2026-10-06T10:00:00Z")
    w.approve("inv-b", at="2026-10-06T11:00:00Z"); w.approve("inv-a", actor="usr-rev02", at="2026-10-06T12:00:00Z")
    res = run_pipeline(w.data())
    docs = res.documents()["invoices"]
    assert (docs["inv-b"]["status"], docs["inv-a"]["status"], docs["inv-a"].get("merged_into")) == ("approved", "merged", "inv-b")
    assert res.metrics["approvals"]["invalid_records"] == [{"approval_id": "ap-002", "reason_code": "NOT_MATCHED"}]
    assert res.metrics["obligations"]["count"] == 1


def test_an_invalid_invoice_never_anchors_a_group_and_a_none_validity_may_be_merged():
    w = World(); w.pol("pol-1", qty="100"); w.receipt("pol-1", "100")
    w.invoice("inv-1", [("l1", "pol-1", "1", "20.00")], number="N", date="2026-10-07", at="2026-10-06T09:00:00Z")      # invalid
    w.invoice("inv-2", [("l2", "pol-1", "1", "20.00")], number="N", date="2026-10-07", at="2026-10-08T09:00:00Z")
    w.invoice("inv-3", [("l3", "pol-1", "1", "20.00")], number="N", date="2026-10-07", at="2026-10-09T09:00:00Z")
    docs = run_pipeline(w.data()).documents()["invoices"]
    assert [docs[i]["status"] for i in ("inv-1", "inv-2", "inv-3")] == ["invalid", "matched", "merged"] and docs["inv-3"]["merged_into"] == "inv-2"


# --- R5-04: processing time --------------------------------------------------------------------------------------------------

def test_processing_minutes_are_never_negative_whatever_the_decision_instants():
    w = World(); w.pol("pol-1", qty="100"); w.receipt("pol-1", "100")
    for k in range(6):
        w.invoice(f"inv-{k}", [(f"l{k}", "pol-1", "1", "20.00")], number=f"N{k}", at="2026-10-06T09:00:00Z")
        w.approve(f"inv-{k}", at=f"2026-10-0{k + 1}T09:00:00Z")                     # from 10-01 (before the import) to 10-06 (at it)
    m = run_pipeline(w.data()).metrics
    assert m["processing"]["approved_count"] == 1 and m["processing"]["mean_minutes"] == "0.0000"
    assert [r["reason_code"] for r in m["approvals"]["invalid_records"]] == ["BEFORE_IMPORT"] * 5


# --- R5-07: windows and cutoffs -----------------------------------------------------------------------------------------------

def test_a_window_before_the_resent_pdf_does_not_count_the_merge():
    res = run_pipeline(golden_inputs())
    early = window_metrics(res.population, (None, parse_ts("2026-10-07T00:00:00Z")))["metrics"]
    assert early["duplicates"] == {"groups_detected": 0, "rows_merged": 0, "unresolved_groups": 0}
    assert early["export"]["requests_received"] == 0
    full = window_metrics(res.population, (None, parse_ts("2026-10-08T00:00:00Z")))["metrics"]
    assert full["duplicates"]["rows_merged"] == 1 and full["export"]["difference"] == "0.00"
    cohort = window_metrics(res.population, (parse_ts("2026-10-01T00:00:00Z"), parse_ts("2026-10-07T00:00:00Z")))["metrics"]
    assert cohort["duplicates"]["rows_merged"] == 0


# --- R5-10: straight-through ----------------------------------------------------------------------------------------------------

def test_straight_through_rate_keeps_its_published_meaning_not_blocked_at_the_cutoff():
    """D-09: the golden value (0.5 = 1 of 2 not blocked) is unchanged; a resolved exception raises ever_excepted_rate only."""
    case = CASES["exception_history_rates"]
    res = run_case(case)
    r = res.metrics["rates"]
    assert (r["straight_through_rate"], r["exception_rate"]) == ("0.500000", "0.500000")
    assert (r["straight_through_never_excepted_rate"], r["ever_excepted_rate"]) == ("0.000000", "1.000000")
    golden = run_pipeline(golden_inputs()).metrics["rates"]
    assert set(golden) == {"eligible_invoices", "straight_through_rate", "exception_rate"}


def test_rejected_invoices_are_outside_the_denominator():
    """D-09: eligible = validated invoices still in the book; a rejected invoice has left it (and is counted in approvals)."""
    case = CASES["rejection_after_invalid_approval"]
    res = run_pipeline(case["inputs"])
    assert res.metrics["rates"]["eligible_invoices"] == 1 and res.book.status["inv-ir"] == "rejected"


# --- R5-11: money per currency -----------------------------------------------------------------------------------------------------

def test_a_single_currency_book_carries_no_by_currency_keys():
    m = run_pipeline(golden_inputs()).metrics
    for k in ("matched", "obligations", "payable", "export"):
        assert "by_currency" not in m[k]


def test_group_by_currency_has_one_currency_per_group_and_no_by_currency():
    res = run_pipeline(CASES["byte_twin_with_other_fields_and_two_currencies"]["inputs"])
    groups = window_metrics(res.population, (None, None), [], "currency")["groups"]
    assert [g["key"] for g in groups] == ["EUR", "USD"] and all("by_currency" not in g["metrics"]["matched"] for g in groups)


# --- R5-18: grouped export counts ------------------------------------------------------------------------------------------------------

def test_a_batch_naming_two_vendors_is_counted_once_across_the_groups():
    w = World(); w.pol("pol-1", qty="100"); w.receipt("pol-1", "100"); w.pol("pol-9", po="po-2", qty="100"); w.receipt("pol-9", "100")
    w.invoice("inv-1", [("l1", "pol-1", "1", "20.00")], number="A")
    w.invoice("inv-2", [("l2", "pol-9", "1", "20.00")], number="B", vendor="ven-2", currency="EUR")
    w.approve("inv-1"); w.approve("inv-2")
    w.export("bat-1", "k1", ["inv-1", "inv-2"]); w.export("bat-1", "k2", ["inv-1", "inv-2"], at="2026-10-07T09:00:00Z")
    pop = run_pipeline(w.data()).population
    for by in ("vendor", "currency"):
        groups = window_metrics(pop, (None, None), [], by)["groups"]
        got = [g["metrics"]["export"] for g in groups]
        assert sum(e["requests_received"] for e in got) == 2 and sum(e["batches_created"] for e in got) == 1
        assert sum(e["repeat_requests_returned_prior"] for e in got) == 1
        assert [len(e["rows"]) for e in got] == [1, 1]                      # the rows are still per invoice
    whole = compute_metrics(pop, None)["export"]
    assert (whole["requests_received"], whole["batches_created"]) == (2, 1)


# --- R5-21: no float in the published parameters ----------------------------------------------------------------------------------------

def test_the_published_manifest_carries_no_float():
    def refuse(text):
        raise AssertionError(f"float {text} in manifest.json")
    for name in ("manifest.json", "golden/manifest.json"):
        json.loads((ROOT / "web" / "public" / "data" / name).read_text(), parse_float=refuse)


# --- R5-17 -------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,ok", [("10", True), ("-1.5", True), ("+2", True), (".5", True), ("5.", True), (" 7 ", True),
                                     ("1_0", False), ("1E+1", False), ("1e1", False), ("١٠", False), ("Infinity", False), ("NaN", False),
                                     ("", False), ("1 0", False), ("0x10", False), ("１０", False)])
def test_only_ascii_decimal_spellings_parse(text, ok):
    from invoicebridge.errors import DomainError
    from invoicebridge.money import dec
    if ok:
        dec(text, "q", 4)
    else:
        with pytest.raises(DomainError):
            dec(text, "q", 4)
