"""Reads: GET /data/{entity} and GET /metrics (docs/api-contract.md, D-01, D-05)."""
from __future__ import annotations

import base64

from support_db import PREFIX, client, command, conn, db_url, expected, golden_inputs, seed_db  # noqa: F401

DATA = f"{PREFIX}/data"
META_KEYS = {"dataset_version", "code_sha", "contract_version", "generated_at", "applied_filters",
             "total_count", "next_cursor", "exclusions"}


def _page_all(client, entity: str, limit: int, **params) -> tuple[list[dict], int]:
    rows, pages, cursor = [], 0, None
    while True:
        q = {"limit": limit, **params, **({"cursor": cursor} if cursor else {})}
        r = client.get(f"{DATA}/{entity}", params=q)
        assert r.status_code == 200, r.text
        body = r.json()
        rows += body["data"]
        pages += 1
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            return rows, pages
        assert pages < 50


def test_read_no_records_returns_empty_page_with_full_envelope(client):
    r = client.get(f"{DATA}/orders")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == [] and body["warnings"] == []
    assert set(body["meta"]) == META_KEYS
    assert body["meta"]["total_count"] == 0 and body["meta"]["next_cursor"] is None
    assert body["meta"]["dataset_version"] == "unversioned"
    assert body["meta"]["contract_version"] == "v1" and body["meta"]["code_sha"] == "dev"
    assert body["meta"]["applied_filters"]["limit"] == 50


def test_read_one_record_uses_decimal_strings_and_iso_timestamps(client, conn):
    seed_db(conn, golden_inputs(returns=True, costs=True))
    r = client.get(f"{DATA}/shipments")
    body = r.json()
    assert body["data"] == [{"shipment_id": "shp-001", "order_id": "ord-001",
                             "shipped_at": "2026-03-10T14:30:00Z", "shipping_cost": "15.00",
                             "currency": "USD"}]
    assert body["meta"]["total_count"] == 1
    assert body["meta"]["dataset_version"].startswith("ds-")
    line = client.get(f"{DATA}/shipment_lines").json()["data"][0]
    assert line["version"] == 1 and line["cost_version_id"] == "cv-001"
    assert client.get(f"{DATA}/order_lines").json()["data"][0]["unit_price"] == "100.00"


def test_read_multiple_pages_stable_order_no_duplicates_no_gaps(client, conn):
    data = golden_inputs()
    data["products"] = [{"product_id": f"prod-{i:02d}", "sku": f"S{i}", "category_id": "cat-001",
                         "unit_of_measure": "each", "active": True} for i in range(1, 8)]
    data["cost_versions"] = []
    data["order_lines"] = data["discounts"] = data["shipment_lines"] = data["shipments"] = []
    data["orders"] = []
    seed_db(conn, data)
    rows, pages = _page_all(client, "products", 3)
    ids = [r["product_id"] for r in rows]
    assert pages == 3 and ids == [f"prod-{i:02d}" for i in range(1, 8)]
    assert len(set(ids)) == len(ids)
    first = client.get(f"{DATA}/products", params={"limit": 3}).json()
    assert first["meta"]["total_count"] == 7 and first["meta"]["next_cursor"]
    # Same cursor twice: same page (stable); rows inserted before the cursor do not shift it.
    c = first["meta"]["next_cursor"]
    a = client.get(f"{DATA}/products", params={"limit": 3, "cursor": c}).json()["data"]
    conn.execute("INSERT INTO products VALUES ('prod-00', 'S0', 'cat-001', 'each', true)")
    b = client.get(f"{DATA}/products", params={"limit": 3, "cursor": c}).json()["data"]
    assert a == b


def test_read_composite_key_paging_customers_type2_versions(client, conn):
    data = golden_inputs()
    data["customers"] = [{"customer_id": "cust-001", "customer_name": "G", "region_id": f"reg-{i}",
                          "segment": "SMB", "effective_from": f"202{i}-01-01"} for i in range(0, 6)]
    seed_db(conn, data)
    rows, pages = _page_all(client, "customers", 2)
    assert pages == 3 and [r["effective_from"] for r in rows] == [f"202{i}-01-01" for i in range(6)]
    window, _ = _page_all(client, "customers", 2, **{"from": "2022-01-01", "to": "2025-01-01"})
    assert [r["effective_from"] for r in window] == ["2022-01-01", "2023-01-01", "2024-01-01"]


def test_read_time_filter_is_half_open(client, conn):
    seed_db(conn, golden_inputs())
    f = {"from": "2026-03-10T14:30:00Z"}
    assert client.get(f"{DATA}/shipments", params=f).json()["meta"]["total_count"] == 1
    r = client.get(f"{DATA}/shipments", params={"to": "2026-03-10T14:30:00Z"}).json()
    assert r["data"] == [] and r["meta"]["total_count"] == 0
    assert r["meta"]["applied_filters"]["to"] == "2026-03-10T14:30:00+00:00"


def test_read_invalid_filters_are_422_with_path_and_rule_id(client):
    def rule(params, entity="orders"):
        r = client.get(f"{DATA}/{entity}", params=params)
        assert r.status_code == 422, (params, r.text)
        d = r.json()["error"]["details"][0]
        assert r.json()["error"]["code"] == "VALIDATION_FAILED" and r.json()["request_id"]
        return d["path"], d["rule_id"]
    assert rule({"from": "yesterday"}) == ("from", "INVALID_FILTER")
    assert rule({"to": "2026-13-45"}) == ("to", "INVALID_FILTER")
    assert rule({"cursor": "!!!"}) == ("cursor", "INVALID_CURSOR")
    garbage = base64.urlsafe_b64encode(b'["a","b"]').decode()
    assert rule({"cursor": garbage}) == ("cursor", "INVALID_CURSOR")
    assert rule({"from": "2026-01-01"}, "products") == ("from", "FILTER_NOT_SUPPORTED")
    assert rule({"limit": 0})[0] == "query.limit" and rule({"limit": 201})[0] == "query.limit"
    assert rule({"limit": "many"})[0] == "query.limit"
    assert client.get(f"{DATA}/not_an_entity").status_code == 404


def test_read_reversed_window_is_422_invalid_window(client):
    r = client.get(f"{DATA}/orders", params={"from": "2026-04-01", "to": "2026-03-01"})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["rule_id"] == "INVALID_WINDOW"
    r = client.get(f"{PREFIX}/metrics", params={"from": "2026-04-01", "to": "2026-03-01"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["rule_id"] == "INVALID_WINDOW"
    r = client.get(f"{PREFIX}/metrics", params={"from": "2026-03-01", "to": "2026-03-01"})
    assert r.status_code == 422                                    # empty window is also invalid


def test_metrics_on_golden_equal_expected_baseline_and_after_return(client, conn):
    seed_db(conn, golden_inputs())
    r = client.get(f"{PREFIX}/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == {"group_by": "none", "metrics": expected()["states"]["baseline"]["metrics"]}
    assert set(body["meta"]) == META_KEYS and body["meta"]["applied_filters"]["group_by"] == "none"
    assert body["meta"]["exclusions"]["excluded_shipment_lines"] == 0
    assert body["warnings"] == []
    seed_db(conn, golden_inputs(returns=True))
    after = client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]
    assert after == expected()["states"]["after_return"]["metrics"]


def test_metrics_group_by_every_dimension_sums_back_to_total(client, conn):
    seed_db(conn, golden_inputs(returns=True))
    total = client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]
    for group_by, key in (("region", "reg-001"), ("customer", "cust-001"), ("month", "2026-03")):
        d = client.get(f"{PREFIX}/metrics", params={"group_by": group_by}).json()["data"]
        assert list(d["groups"]) == [key] and d["groups"][key] == total, group_by
    d = client.get(f"{PREFIX}/metrics", params={"group_by": "product"}).json()["data"]["groups"]
    assert list(d) == ["prod-001", "prod-002"]
    assert d["prod-001"]["gross_sales"] == "200.00" and d["prod-002"]["gross_sales"] == "50.00"
    r = client.get(f"{PREFIX}/metrics", params={"group_by": "planet"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["rule_id"] == "INVALID_GROUP_BY"


def test_metrics_window_and_empty_database(client, conn):
    assert client.get(f"{PREFIX}/metrics").json()["data"]["metrics"]["gross_sales"] == "0.00"
    seed_db(conn, golden_inputs())
    r = client.get(f"{PREFIX}/metrics", params={"from": "2026-04-01T00:00:00Z"}).json()
    assert r["data"]["metrics"]["gross_sales"] == "0.00" and r["data"]["metrics"]["eligible_orders"] == 0
    r = client.get(f"{PREFIX}/metrics", params={"from": "2026-03-01", "to": "2026-04-01"}).json()
    assert r["data"]["metrics"]["gross_sales"] == "250.00"
