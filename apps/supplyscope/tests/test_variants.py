"""variant-rejected and variant-empty: counts, rejected rows with raw rows, totals and nulls."""
import pytest

from supplyscope import run_pipeline

from support_db import golden_expected, golden_inputs


@pytest.mark.parametrize("sub,states", [("variant-rejected", ["golden", "position_80"]), ("variant-empty", ["empty"])])
def test_variants_key_by_key(sub, states):
    exp = golden_expected(sub)
    for state in states:
        r = run_pipeline(golden_inputs(sub), state)
        assert r.counts == exp["ingest"]["counts"]
        assert r.rejected == exp["ingest"]["rejected_records"]
        want = exp["states"][state]["metrics"]
        assert set(r.metrics) == set(want)
        for k, v in want.items():
            assert r.metrics[k] == v and type(r.metrics[k]) is type(v), (sub, state, k)


def test_rejected_variant_totals_equal_golden():
    gold = golden_expected()["states"]
    for state in ("golden", "position_80"):
        assert run_pipeline(golden_inputs("variant-rejected"), state).metrics == gold[state]["metrics"]


def test_rejected_rows_keep_their_raw_payload():
    r = run_pipeline(golden_inputs("variant-rejected"), "golden")
    by_id = {x["id"]: x for x in r.rejected}
    assert by_id["mv-002"]["reason_code"] == "DUPLICATE_MOVEMENT_ID" and by_id["mv-002"]["raw_row"]["quantity_delta"] == -25
    assert by_id["rcpt-001"]["reason_code"] == "RECEIPT_BEFORE_ORDER"
    assert r.metrics["on_order"] == 30       # the rejected receipt did not reduce the open line


def test_empty_variant_is_not_evaluated_not_zero():
    m = run_pipeline(golden_inputs("variant-empty"), "empty").metrics
    assert m["reorder_triggered"] is None and m["order_quantity"] is None and m["empty_population"] is True
    assert m["fill_rate"] is None and m["stockout_days"] is None and m["working_capital"] == "0.00"
