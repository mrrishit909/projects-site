"""Golden fixture through the domain pipeline (P01-GOLD-*)."""
from __future__ import annotations

import json

import pytest

from revenue_atlas.money import money_str
from revenue_atlas.pipeline import run_pipeline


@pytest.fixture(scope="module")
def expected():
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures/golden/expected.json").read_text())


@pytest.mark.parametrize("state,include", [("baseline", False), ("after_return", True)])
def test_golden_state(load_golden, expected, state, include):
    res = run_pipeline(load_golden(), include_returns=include)
    exp = expected["states"][state]
    assert set(res.metrics) == set(exp["metrics"])
    for key, want in exp["metrics"].items():
        assert res.metrics[key] == want, key
        assert type(res.metrics[key]) is type(want), key
    assert {k: money_str(v) for k, v in res.freight_by_line.items()} == exp["freight_by_shipment_line"]
    assert {k: money_str(v) for k, v in res.discount_by_line.items()} == exp["discount_by_shipment_line"]
    assert res.ingest.counts == expected["ingest"]["counts"]
    assert res.quarantined == []


def test_golden_is_deterministic(load_golden):
    a = run_pipeline(load_golden(), True)
    b = run_pipeline(load_golden(), True)
    assert a.metrics == b.metrics and a.facts == b.facts
