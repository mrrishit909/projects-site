"""D-01a: a window selects shipment lines by shipped_at and return credits by credit_date."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from revenue_atlas.pipeline import run_pipeline
from support_db import golden_inputs


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_credit_dated_after_the_window_is_not_in_it_but_is_in_the_later_window():
    inputs = golden_inputs(returns=True)  # one shipment 2026-03-10, one return credited 2026-03-20
    early = run_pipeline(copy.deepcopy(inputs), True, (utc(2026, 3, 1), utc(2026, 3, 15))).metrics
    late = run_pipeline(copy.deepcopy(inputs), True, (utc(2026, 3, 15), utc(2026, 4, 1))).metrics
    whole = run_pipeline(copy.deepcopy(inputs), True).metrics
    assert (early["net_merchandise_sales"], early["merchandise_credits"], early["returned_units"]) == ("225.00", "0.00", 0)
    assert (late["gross_sales"], late["merchandise_credits"], late["net_merchandise_sales"]) == ("0.00", "90.00", "-90.00")
    assert late["return_rate"] is None and late["eligible_shipment_lines"] == 0
    assert late["recoverable_return_cost"] != "0.00" and late["returned_units"] == 1
    assert whole["merchandise_credits"] == "90.00"


def test_credit_date_window_is_half_open_at_utc_midnight():
    inputs = golden_inputs(returns=True)
    inc = run_pipeline(copy.deepcopy(inputs), True, (utc(2026, 3, 20), None)).metrics
    exc = run_pipeline(copy.deepcopy(inputs), True, (None, utc(2026, 3, 20))).metrics
    assert inc["merchandise_credits"] == "90.00" and exc["merchandise_credits"] == "0.00"
