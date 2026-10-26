"""One test per contract rule, each on its own tiny fixture."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from revenue_atlas.allocation import allocate_discounts, allocate_freight
from revenue_atlas.errors import (COST_VERSION_AMBIGUOUS, COST_VERSION_MISSING,
                                  CREDIT_SIGN_REVERSED, FX_RATE_MISSING, INVALID_WINDOW,
                                  RETURN_EXCEEDS_REMAINING, DomainError)
from revenue_atlas.ingest import validate_batch
from revenue_atlas.metrics import compute_metrics, group_metrics, region_key
from revenue_atlas.models import Return, Shipment, ShipmentLine
from revenue_atlas.money import largest_remainder, money_str
from revenue_atlas.pipeline import run_pipeline
from revenue_atlas.returns import validate_return

D = Decimal


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def codes(res):
    return {(q.entity, q.id): q.reason_code for q in res.quarantined}


def test_largest_remainder_exact_and_tiebreak():
    out = largest_remainder(D("10.00"), [("b", D(1)), ("a", D(1)), ("c", D(1))])
    assert out == {"a": D("3.34"), "b": D("3.33"), "c": D("3.33")}
    assert sum(out.values()) == D("10.00")
    out = largest_remainder(D("0.05"), [("x", D(3)), ("y", D(7)), ("z", D(1))])
    assert sum(out.values()) == D("0.05")
    with pytest.raises(ValueError):
        largest_remainder(D("1.00"), [("a", D(0))])


def test_overlapping_cost_versions_quarantine(tiny):
    b = tiny()
    b["cost_versions"].append({"cost_version_id": "cv2", "product_id": "p1", "unit_cost": "5.00",
                               "valid_from": "2026-03-01", "valid_to": None})
    res = run_pipeline(b, False)
    assert codes(res) == {("shipment_lines", "sl1"): COST_VERSION_AMBIGUOUS}
    assert res.facts == [] and res.metrics["eligible_shipment_lines"] == 0


def test_cost_version_half_open_and_missing(tiny):
    b = tiny()
    b["cost_versions"] = [{"cost_version_id": "cv1", "product_id": "p1", "unit_cost": "4.00",
                           "valid_from": "2026-01-01", "valid_to": "2026-03-10"}]
    assert codes(run_pipeline(b, False)) == {("shipment_lines", "sl1"): COST_VERSION_MISSING}


def test_missing_fx_quarantines_not_zero(tiny):
    b = tiny()
    b["orders"][0]["currency"] = "EUR"
    b["shipments"][0]["currency"] = "EUR"
    res = run_pipeline(b, False)
    assert codes(res) == {("shipment_lines", "sl1"): FX_RATE_MISSING}
    assert res.metrics["gross_sales"] == "0.00" and res.metrics["eligible_orders"] == 0


def test_eur_converts_with_dated_rate(tiny):
    b = tiny()
    b["orders"][0]["currency"] = "EUR"
    b["shipments"][0]["currency"] = "EUR"
    b["exchange_rates"] += [
        {"rate_id": "e1", "currency": "EUR", "reporting_currency": "USD", "rate_date": "2026-03-10",
         "rate": "1.10"},
        {"rate_id": "e0", "currency": "EUR", "reporting_currency": "USD", "rate_date": "2026-03-09",
         "rate": "2.00"}]
    m = run_pipeline(b, False).metrics
    assert m["gross_sales"] == "22.00" and m["shipping_cost"] == "3.30"


def _sl(qty=3):
    return ShipmentLine("sl1", "s1", "l1", qty)


def _ret(i, q):
    return Return(f"r{i}", "sl1", q, D("1.00"), "2026-03-20")


def test_return_exceeding_remaining():
    with pytest.raises(DomainError) as e:
        validate_return(_sl(2), [], 3, D("1.00"))
    assert e.value.code == RETURN_EXCEEDS_REMAINING


def test_partial_returns_sum_to_shipped_then_third_rejected(tiny):
    b = tiny()
    b["returns"] = [
        {"return_id": f"r{i}", "shipment_line_id": "sl1", "returned_quantity": 1,
         "credit_amount": "10.00", "credit_date": f"2026-03-1{i}"} for i in (1, 2, 3)]
    res = run_pipeline(b, True)
    assert res.metrics["returned_units"] == 2 and res.metrics["merchandise_credits"] == "20.00"
    assert codes(res) == {("returns", "r3"): RETURN_EXCEEDS_REMAINING}
    validate_return(_sl(2), [_ret(1, 1)], 1, D("1.00"))


def test_negative_credit_rejected(tiny):
    with pytest.raises(DomainError) as e:
        validate_return(_sl(2), [], 1, D("-0.01"))
    assert e.value.code == CREDIT_SIGN_REVERSED
    b = tiny()
    b["returns"] = [{"return_id": "r1", "shipment_line_id": "sl1", "returned_quantity": 1,
                     "credit_amount": "-10.00", "credit_date": "2026-03-12"}]
    assert codes(run_pipeline(b, True)) == {("returns", "r1"): CREDIT_SIGN_REVERSED}


def _shp(cost="10.00"):
    return Shipment("s1", "o1", utc(2026, 3, 10), D(cost), "USD")


def test_zero_gross_allocates_by_quantity():
    sls = [ShipmentLine("a", "s1", "l1", 1), ShipmentLine("b", "s1", "l2", 3)]
    fa = allocate_freight(_shp(), sls, {"a": D(0), "b": D(0)})
    assert fa.allocations == {"a": D("2.50"), "b": D("7.50")}
    assert fa.residual == 0 and not fa.unallocated


def test_zero_quantity_is_unallocated_with_residual():
    sls = [ShipmentLine("a", "s1", "l1", 0)]
    fa = allocate_freight(_shp("4.00"), sls, {"a": D(0)})
    assert fa.unallocated and fa.allocations == {} and fa.residual == D("4.00")


def test_unallocated_freight_still_counts_in_contribution(tiny):
    b = tiny()
    b["shipment_lines"][0]["shipped_quantity"] = 0
    m = run_pipeline(b, False).metrics
    assert m["shipping_cost"] == "3.00" and m["contribution_margin"] == "-3.00"
    assert m["allocation_residual"] == "0.00"


def test_discount_allocation_remainder_by_lowest_id():
    from revenue_atlas.models import Discount, OrderLine
    ol = OrderLine("l1", "o1", "p1", 3, D("10.00"))
    ds = [Discount("d1", "l1", D("0.10"), "X", "m")]
    sls = [ShipmentLine("b", "s1", "l1", 1), ShipmentLine("a", "s2", "l1", 1),
           ShipmentLine("c", "s3", "l1", 1)]
    out = allocate_discounts([ol], ds, sls)
    assert out == {"a": D("0.04"), "b": D("0.03"), "c": D("0.03")}


def test_cancelled_order_contributes_nothing(tiny):
    b = tiny()
    b["orders"][0]["status"] = "cancelled"
    b["shipments"], b["shipment_lines"] = [], []
    res = run_pipeline(b, True)
    assert res.facts == [] and res.metrics["gross_sales"] == "0.00"
    assert res.metrics["eligible_orders"] == 0 and res.quarantined == []


def test_no_customer_version_gives_unassigned_region(tiny):
    b = tiny()
    b["customers"][0]["effective_from"] = "2026-06-01"
    res = run_pipeline(b, False)
    assert res.facts[0].region_id == "UNASSIGNED"
    groups = group_metrics(res.facts, region_key)
    assert list(groups) == ["UNASSIGNED"] and groups["UNASSIGNED"]["gross_sales"] == "20.00"
    from dataclasses import replace
    assert "UNASSIGNED" in group_metrics([replace(res.facts[0], region_id=None)], lambda f: f.region_id)


def test_customer_region_uses_version_effective_at_shipment(tiny):
    b = tiny()
    b["customers"].append({"customer_id": "c1", "customer_name": "C", "region_id": "r2",
                           "segment": "SMB", "effective_from": "2026-03-10"})
    b["customers"].append({"customer_id": "c1", "customer_name": "C", "region_id": "r3",
                           "segment": "SMB", "effective_from": "2026-04-01"})
    assert run_pipeline(b, False).facts[0].region_id == "r2"


def test_reversed_or_equal_window_rejected(tiny):
    facts = run_pipeline(tiny(), False).facts
    for w in ((utc(2026, 4, 1), utc(2026, 3, 1)), (utc(2026, 3, 1), utc(2026, 3, 1))):
        with pytest.raises(DomainError) as e:
            compute_metrics(facts, w)
        assert e.value.code == INVALID_WINDOW


def test_window_is_half_open(tiny):
    facts = run_pipeline(tiny(), False).facts
    at = facts[0].shipped_at
    assert compute_metrics(facts, (utc(2026, 3, 1), at))["eligible_shipment_lines"] == 0
    assert compute_metrics(facts, (at, utc(2026, 4, 1)))["eligible_shipment_lines"] == 1


def test_ingest_idempotent_and_currency_cascade(tiny):
    b = tiny()
    b["orders"][0]["currency"] = "usd"
    b["discounts"].append({"discount_id": "d1", "line_id": "l1", "discount_amount": "1.00",
                           "reason_code": "X", "approved_by": "m"})
    b["returns"] = [{"return_id": "r1", "shipment_line_id": "sl1", "returned_quantity": 1,
                     "credit_amount": "1.00", "credit_date": "2026-03-12"}]
    r1, r2 = validate_batch(b), validate_batch(b)
    assert r1 == r2 and r1.counts == r2.counts and r1.rejected == r2.rejected
    assert {(r.entity, r.reason_code) for r in r1.rejected} == {
        (e, "CURRENCY_NOT_ISO4217") for e in
        ("orders", "order_lines", "discounts", "shipments", "shipment_lines", "returns")}
    assert r1.rejected[0].raw_row is not b["customers"][0]
    assert money_str(D("1.005")) == "1.01"
