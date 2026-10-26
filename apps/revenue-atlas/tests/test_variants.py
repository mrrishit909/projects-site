"""Rejected-record and empty-population variants (P01-GOLD-08/09)."""
from __future__ import annotations

import json

from revenue_atlas.pipeline import run_pipeline


def test_variant_rejected(load_golden, golden_dir):
    exp = json.loads((golden_dir / "variant-rejected/expected.json").read_text())
    res = run_pipeline(load_golden("variant-rejected"), include_returns=True)
    got = [{"entity": r.entity, "id": r.id, "reason_code": r.reason_code, "raw_row": r.raw_row}
           for r in res.ingest.rejected]
    want = [{k: v for k, v in r.items() if k != "status"}
            for r in exp["ingest"]["rejected_records"]]
    assert got == want
    assert res.ingest.counts == exp["ingest"]["counts"]
    base = run_pipeline(load_golden("variant-rejected"), include_returns=False)
    assert base.metrics == exp["states"]["baseline"]["metrics"]
    assert res.metrics == exp["states"]["after_return"]["metrics"]


def test_variant_empty(load_golden, golden_dir):
    exp = json.loads((golden_dir / "variant-empty/expected.json").read_text())
    assert exp["empty_population"] is True
    for include, state in ((False, "baseline"), (True, "after_return")):
        res = run_pipeline(load_golden("variant-empty"), include_returns=include)
        assert res.metrics == exp["states"][state]["metrics"]
        assert res.facts == [] and res.freight_by_line == {} and res.discount_by_line == {}
    assert res.ingest.counts == exp["ingest"]["counts"]
    assert res.metrics["contribution_margin_rate"] is None
    assert res.metrics["average_order_value"] is None
