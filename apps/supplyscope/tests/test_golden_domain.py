"""The golden fixture, key by key, in both states (golden and position_80), through the pure domain."""
import pytest

from supplyscope import run_pipeline
from supplyscope.contract import METRIC_KEYS

from support_db import golden_expected, golden_inputs

STATES = ["golden", "position_80"]


@pytest.mark.parametrize("state", STATES)
def test_metrics_equal_expected_key_by_key(state):
    want = golden_expected()["states"][state]["metrics"]
    got = run_pipeline(golden_inputs(), state).metrics
    assert set(got) == set(want) == set(METRIC_KEYS)
    for key, value in want.items():
        assert got[key] == value and type(got[key]) is type(value), key


def test_spec_sentence_numbers():
    """P03-GOLD-01: on hand 40, on order 30, backorders 10 -> position 60; ROP 70, target 120 -> raw 60; MOQ 50, pack 24 -> 72."""
    m = run_pipeline(golden_inputs(), "golden").metrics
    assert (m["on_hand"], m["on_order"], m["backorders"], m["inventory_position"]) == (40, 30, 10, 60)
    assert (m["reorder_point"], m["target_position"], m["raw_order"], m["order_after_moq"], m["order_quantity"]) == \
        (70, 120, 60, 60, 72)
    m80 = run_pipeline(golden_inputs(), "position_80").metrics
    assert m80["inventory_position"] == 80 and m80["reorder_triggered"] is False and m80["order_quantity"] == 0


def test_ingest_counts_and_no_rejections():
    r = run_pipeline(golden_inputs(), "golden")
    assert r.counts == golden_expected()["ingest"]["counts"] and r.rejected == []


def test_day_order_prevents_the_negative_artefact():
    m = run_pipeline(golden_inputs(), "golden").metrics
    assert m["timestamp_order_stock_min"] == -35 and m["running_stock_min"] == 0 and m["negative_stock"] is False


def test_unknown_state_is_a_domain_error():
    from supplyscope import DomainError
    with pytest.raises(DomainError) as err:
        run_pipeline(golden_inputs(), "nope")
    assert err.value.code == "UNKNOWN_STATE"
