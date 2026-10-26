"""Reads: GET /data/{entity} (none, one, stable pages, invalid filter, reversed window) and GET /metrics."""
import pytest

from data import seed

from support_db import (AS_OF, client, conn, count, db_url, get, golden_expected, golden_inputs, rule_ids,  # noqa: F401
                        seeded)

FROM = {"from": "2026-03-01T00:00:00Z"}


def _fixture_keys(metrics):
    """The keys of expected.json (R3-01 adds extra keys beside them)."""
    from supplyscope.contract import EXTRA_METRIC_KEYS
    return {k: v for k, v in metrics.items() if k not in EXTRA_METRIC_KEYS}


def add_products(conn, n):
    for i in range(n):
        conn.execute("INSERT INTO products VALUES (%s, %s, 1.00, 1, 1, %s, NULL)", (f"p-{i + 10:03d}", f"SKU-X{i}", "A" if i % 2 else "B"))


def test_read_none_and_one(client, seeded, conn):
    empty = get(client, "/data/promotions")
    assert empty.status_code == 200 and empty.json()["data"] == [] and empty.json()["meta"]["total_count"] == 0
    body = get(client, "/data/products").json()
    assert body["data"] == [{"product_id": "prod-001", "sku": "SKU-001", "unit_cost": "12.50", "pack_size": 24,
                             "minimum_order_quantity": 50, "abc_class": None, "supplier_id": None}]
    assert body["meta"]["dataset_version"].startswith("ds-") and body["meta"]["contract_version"] == "v1"
    assert set(body["meta"]) == {"dataset_version", "code_sha", "contract_version", "generated_at", "applied_filters",
                                 "total_count", "next_cursor", "exclusions"}
    mv = get(client, "/data/inventory_movements", limit=2).json()
    assert [m["movement_id"] for m in mv["data"]] == ["mv-001", "mv-002"] and mv["data"][0]["event_at"] == "2026-03-01T08:00:00Z"
    assert mv["meta"]["total_count"] == 7 and mv["meta"]["next_cursor"]


def test_read_with_no_data_at_all(client):
    r = get(client, "/data/products")
    assert r.json()["data"] == [] and r.json()["meta"]["dataset_version"] == "unversioned"


def test_pages_are_stable_with_no_duplicates_or_gaps(client, conn):
    add_products(conn, 7)
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 3} | ({"cursor": cursor} if cursor else {})
        body = get(client, "/data/products", **params).json()
        seen += [p["product_id"] for p in body["data"]]
        pages += 1
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and seen == [f"p-{i + 10:03d}" for i in range(7)]
    first = get(client, "/data/products", limit=2).json()
    conn.execute("INSERT INTO products VALUES ('p-000', 'EARLY', 1.00, 1, 1, NULL, NULL)")     # added between requests
    second = get(client, "/data/products", limit=2, cursor=first["meta"]["next_cursor"]).json()
    assert [p["product_id"] for p in second["data"]] == ["p-012", "p-013"]                      # no duplicate, no gap


def test_composite_and_typed_cursors(client, seeded, conn):
    for i in range(1, 4):
        conn.execute("INSERT INTO stock_snapshots VALUES (%s, 'prod-001', 'loc-001', 1, 1, 0, 1, 0, false, '[]')",
                     (f"2026-03-0{i}T00:00:00Z",))
    seen, cursor = [], None
    while True:
        body = get(client, "/data/stock_snapshots", limit=1, **({"cursor": cursor} if cursor else {})).json()
        seen += [s["as_of"] for s in body["data"]]
        cursor = body["meta"]["next_cursor"]
        if not cursor:
            break
    assert seen == ["2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", "2026-03-03T00:00:00Z"]
    seed.seed(conn, golden_inputs("variant-rejected"))
    rej = get(client, "/data/rejected_records", limit=1)
    assert rej.json()["meta"]["total_count"] == 2
    nxt = get(client, "/data/rejected_records", limit=1, cursor=rej.json()["meta"]["next_cursor"])
    assert nxt.status_code == 200 and len(nxt.json()["data"]) == 1
    assert rej.json()["data"][0]["raw_row"]["movement_id"] == "mv-002" or rej.json()["data"][0]["raw_row"]["receipt_id"]


def test_filters_windows_and_errors(client, seeded):
    assert len(get(client, "/data/inventory_movements", movement_type="receipt").json()["data"]) == 3
    assert len(get(client, "/data/inventory_movements", **{"from": "2026-03-05", "to": "2026-03-12"}).json()["data"]) == 2   # [from, to)
    r = get(client, "/data/inventory_movements", **{"from": "2026-03-12T09:00:00Z", "to": "2026-03-12T09:00:00Z"})
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_WINDOW"]
    assert rule_ids(get(client, "/data/inventory_movements", colour="red")) == ["INVALID_FILTER"]
    assert rule_ids(get(client, "/data/products", **{"from": "2026-03-01"})) == ["FILTER_NOT_SUPPORTED"]
    assert rule_ids(get(client, "/data/inventory_movements", **{"from": "yesterday"})) == ["INVALID_FILTER"]
    assert get(client, "/data/nothing").status_code == 404
    assert get(client, "/data/products", limit=201).status_code == 422 and get(client, "/data/products", limit=0).status_code == 422
    assert rule_ids(get(client, "/data/products", cursor="garbage")) == ["INVALID_CURSOR"]
    assert rule_ids(get(client, "/data/locations", active="maybe")) == ["INVALID_FILTER"]
    assert len(get(client, "/data/locations", active="true").json()["data"]) == 1
    injected = get(client, "/data/inventory_movements", product_id="' OR 1=1 --")
    assert injected.status_code == 200 and injected.json()["data"] == []


# --- metrics ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("state", ["golden", "position_80"])
def test_metrics_golden_states_over_http(client, seeded, state):
    r = get(client, "/metrics", as_of=AS_OF, state=state, **FROM)
    assert r.status_code == 200
    want = golden_expected()["states"][state]["metrics"]
    assert _fixture_keys(r.json()["data"]["metrics"]) == want
    assert r.json()["meta"]["applied_filters"]["state"] == state and r.json()["data"]["supplementary"]["inventory_turnover"] is not None


def test_metrics_without_a_state_and_default_window(client, seeded):
    m = get(client, "/metrics", as_of=AS_OF).json()["data"]["metrics"]     # window defaults to the first day of data
    assert m["on_hand"] == 40 and m["inventory_position"] == 60 and m["fill_rate"] == "0.950000"


def test_metrics_variants_over_http(client, conn):
    seed.seed(conn, golden_inputs("variant-rejected"))
    assert _fixture_keys(get(client, "/metrics", as_of=AS_OF, state="golden", **FROM).json()["data"]["metrics"]) == \
        golden_expected()["states"]["golden"]["metrics"]


def test_metrics_empty_dataset(client, conn):
    seed.seed(conn, golden_inputs("variant-empty"))
    m = get(client, "/metrics", as_of=AS_OF, state="empty", **FROM).json()["data"]["metrics"]
    assert _fixture_keys(m) == golden_expected("variant-empty")["states"]["empty"]["metrics"]


def test_metrics_group_by(client, seeded, conn):
    for key, name in (("product", "prod-001"), ("location", "loc-001"), ("supplier", "unassigned"), ("abc_class", "unclassified")):
        r = get(client, "/metrics", as_of=AS_OF, group_by=key, **FROM)
        assert r.status_code == 200, key
        groups = r.json()["data"]["groups"]
        assert set(groups) == {name} or key == "supplier", (key, groups.keys())
    r = get(client, "/metrics", as_of=AS_OF, group_by="product", state="golden", **FROM).json()["data"]["groups"]["prod-001"]
    assert r["order_quantity"] == 72 and r["on_hand"] == 40
    conn.execute("UPDATE products SET abc_class = 'A', supplier_id = 'sup-001'")
    assert set(get(client, "/metrics", as_of=AS_OF, group_by="abc_class", **FROM).json()["data"]["groups"]) == {"A"}
    assert set(get(client, "/metrics", as_of=AS_OF, group_by="supplier", **FROM).json()["data"]["groups"]) == {"sup-001"}


def test_metrics_window_instant_and_errors(client, seeded):
    narrow = get(client, "/metrics", as_of=AS_OF, **{"from": "2026-03-10T00:00:00Z", "to": "2026-03-12T00:00:00Z"}).json()["data"]["metrics"]
    assert narrow["fulfilled_units"] == 35 and narrow["observed_days"] == 2
    early = get(client, "/metrics", as_of="2026-03-12T10:00:00Z", **FROM)
    assert early.json()["data"]["metrics"]["negative_stock"] is True and early.json()["warnings"][0]["code"] == "NEGATIVE_STOCK"
    assert rule_ids(get(client, "/metrics", group_by="colour")) == ["INVALID_GROUP_BY"]
    assert rule_ids(get(client, "/metrics", state="nope")) == ["INVALID_STATE"]
    assert rule_ids(get(client, "/metrics", **{"from": "2026-03-10", "to": "2026-03-01"})) == ["INVALID_WINDOW"]
    assert rule_ids(get(client, "/metrics", as_of="soon")) == ["INVALID_FILTER"]
    assert get(client, "/metrics").status_code == 200                                         # as_of defaults to now
