"""Variants: rejected rows leave every figure at the golden value; the empty dataset is honest (null, not zero)."""
import pytest

from invoicebridge import run_pipeline
from invoicebridge.contract import ENTITIES, METRIC_KEYS

from support_db import golden_expected, golden_inputs


@pytest.mark.parametrize("variant", ["variant-rejected", "variant-empty"])
def test_whole_variant_equals_expected_json(variant):
    assert run_pipeline(golden_inputs(variant)).golden() == golden_expected(variant)


@pytest.mark.parametrize("variant", ["variant-rejected", "variant-empty"])
@pytest.mark.parametrize("key", METRIC_KEYS)
def test_variant_metric_equals_expected(variant, key):
    assert run_pipeline(golden_inputs(variant)).metrics[key] == golden_expected(variant)["metrics"][key]


@pytest.mark.parametrize("entity", ENTITIES)
def test_rejected_variant_counts(entity):
    got = run_pipeline(golden_inputs("variant-rejected")).counts[entity]
    assert got == golden_expected("variant-rejected")["ingest"]["counts"][entity]


def test_rejected_variant_reasons_and_dependents():
    res = run_pipeline(golden_inputs("variant-rejected"))
    reasons = {(r["entity"], r["id"]): r["reason_code"] for r in res.rejected}
    assert reasons == {("receipts", "rc-002"): "UNKNOWN_PO_LINE", ("invoice_lines", "il-003-2"): "NON_POSITIVE_QUANTITY",
                       ("invoice_lines", "il-003-1"): "DEPENDENT_REJECTED", ("invoices", "inv-003"): "DEPENDENT_REJECTED",
                       ("approvals", "ap-002"): "DEPENDENT_REJECTED"}
    assert all(r["status"] == "rejected" and "raw_row" in r for r in res.rejected)


def test_rejected_variant_book_is_unchanged_by_the_rejections():
    """What acceptance would have done (negative payable, freed received quantity) did not happen."""
    m = run_pipeline(golden_inputs("variant-rejected")).metrics
    assert m["quantities"]["net_received_quantity"] == "6.0000" and m["quantities"]["accepted_invoiced_quantity"] == "6.0000"
    assert (m["obligations"]["count"], m["obligations"]["total"]) == (1, "132.00")
    assert (m["rates"]["straight_through_rate"], m["rates"]["exception_rate"]) == ("1.000000", "0.000000")
    assert m["exceptions"]["open_count"] == 0 and m["duplicates"]["groups_detected"] == 0


def test_empty_variant_is_honest_not_zero_filled():
    res = run_pipeline(golden_inputs("variant-empty"))
    m = res.metrics
    assert m["rates"] == {"eligible_invoices": 0, "straight_through_rate": None, "exception_rate": None}
    assert m["processing"] == {"approved_count": 0, "mean_minutes": None, "pending_count": 0}
    assert m["payable"] == {"approved_total": "0.00", "credit_total": "0.00", "approved_payable": "0.00"}
    assert m["quantities"]["ordered_quantity"] == "0.0000" and m["export"]["difference"] == "0.00"
    assert res.documents() == {"invoices": {}, "match_results": []}
