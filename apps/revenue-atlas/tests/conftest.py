"""Shared fixtures: golden loader and a tiny inline-batch builder."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return GOLDEN


@pytest.fixture
def load_golden():
    def _load(sub: str = "", name: str = "inputs.json") -> dict:
        return json.loads((GOLDEN / sub / name).read_text())
    return _load


def _tiny() -> dict:
    """One USD order: 2 x 10.00, shipped 2026-03-10, shipping 3.00, cost 4.00."""
    return {
        "contract": "v1",
        "customers": [{"customer_id": "c1", "customer_name": "C", "region_id": "r1",
                       "segment": "SMB", "effective_from": "2025-01-01"}],
        "products": [{"product_id": "p1", "sku": "S", "category_id": "k", "unit_of_measure": "each",
                      "active": True}],
        "orders": [{"order_id": "o1", "customer_id": "c1", "order_date": "2026-03-08",
                    "currency": "USD", "status": "shipped"}],
        "order_lines": [{"line_id": "l1", "order_id": "o1", "product_id": "p1", "quantity": 2,
                         "unit_price": "10.00"}],
        "discounts": [],
        "shipments": [{"shipment_id": "s1", "order_id": "o1", "shipped_at": "2026-03-10T12:00:00Z",
                       "shipping_cost": "3.00", "currency": "USD"}],
        "shipment_lines": [{"shipment_line_id": "sl1", "shipment_id": "s1", "line_id": "l1",
                            "shipped_quantity": 2}],
        "returns": [],
        "cost_versions": [{"cost_version_id": "cv1", "product_id": "p1", "unit_cost": "4.00",
                           "valid_from": "2026-01-01", "valid_to": None}],
        "exchange_rates": [{"rate_id": "fx1", "currency": "USD", "reporting_currency": "USD",
                            "rate_date": "2026-01-01", "rate": "1.0"}],
    }


@pytest.fixture
def tiny():
    """Factory returning a fresh, mutable tiny batch."""
    return lambda: copy.deepcopy(_tiny())
