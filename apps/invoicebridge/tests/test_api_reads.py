"""GET /data/{entity}, the invoice audit and GET /metrics: stable ordering, paging, filters, windows, groups and cutoffs."""
import pytest

from api.app import PREFIX

from support_db import REVIEWER, Desk, client, conn, db_url, sha  # noqa: F401


@pytest.fixture
def desk(client, conn):
    w = Desk.default_world()
    w.pol("pol-2", po="po-2", qty="100", price="5.00")
    w.receipt("pol-2", "100")
    w.pol("pol-3", qty="100", price="2.00")
    w.receipt("pol-3", "100")
    return Desk(client, conn, w)


def get(client, path, **params):
    return client.get(f"{PREFIX}{path}", params=params)


def fill(desk, n=5):
    for i in range(1, n + 1):
        desk.ready(f"inv-{i}", [(f"l{i}", "pol-3", "1", "2.00")], imported_at=f"2026-10-0{i + 1}T09:00:00Z", invoice_date=f"2026-10-0{i + 1}")


def test_every_read_has_the_envelope_with_dataset_version_and_contract_meta(desk):
    fill(desk, 1)
    r = get(desk.client, "/data/invoices")
    body = r.json()
    assert r.status_code == 200 and set(body) == {"data", "meta", "warnings"}
    meta = body["meta"]
    assert set(meta) == {"dataset_version", "code_sha", "contract_version", "generated_at", "applied_filters", "total_count", "next_cursor", "exclusions"}
    assert meta["contract_version"] == 1 and meta["dataset_version"].startswith("ds-") and meta["total_count"] == 1
    assert body["data"][0]["total"] == "2.20" and body["data"][0]["tax_rate"] == "0.100000"          # exact decimals as strings


def test_paging_is_stable_complete_and_ordered_by_key(desk):
    fill(desk, 5)
    seen, cursor = [], None
    while True:
        r = get(desk.client, "/data/invoices", limit=2, **({"cursor": cursor} if cursor else {}))
        body = r.json()
        seen += [x["invoice_id"] for x in body["data"]]
        cursor = body["meta"]["next_cursor"]
        assert body["meta"]["total_count"] == 5
        if cursor is None:
            break
    assert seen == [f"inv-{i}" for i in range(1, 6)]
    assert get(desk.client, "/data/invoices", cursor="garbage").status_code == 422
    assert get(desk.client, "/data/invoices", limit=0).status_code == 422 and get(desk.client, "/data/invoices", limit=201).status_code == 422


def test_ordering_is_code_point_order_not_locale(desk):
    for iid in ("inv-b", "inv-B", "inv_a", "inv-A"):
        desk.imp(iid, [(f"l-{iid}", "pol-3", "1", "2.00")])
    ids = [x["invoice_id"] for x in get(desk.client, "/data/invoices").json()["data"]]
    assert ids == sorted(ids)


def test_filters_equality_unknown_and_boolean(desk):
    fill(desk, 3)
    desk.imp("inv-x", [("lx", "pol-3", "1", "2.00")])
    assert [x["invoice_id"] for x in get(desk.client, "/data/invoices", status="received").json()["data"]] == ["inv-x"]
    assert len(get(desk.client, "/data/invoices", status="matched").json()["data"]) == 3
    r = get(desk.client, "/data/invoices", colour="red")
    assert r.status_code == 422 and r.json()["error"]["details"][0]["rule_id"] == "INVALID_FILTER"
    assert [v["vendor_id"] for v in get(desk.client, "/data/vendors", active="true").json()["data"]] == ["ven-1", "ven-2"]
    assert get(desk.client, "/data/vendors", active="maybe").status_code == 422
    assert get(desk.client, "/data/receipts", reversed="false").json()["meta"]["total_count"] == 3
    assert get(desk.client, "/data/nothing").status_code == 404
    assert get(desk.client, "/data/vendors", **{"from": "2026-01-01"}).status_code == 422          # vendors have no time field


def test_the_time_window_is_half_open(desk):
    fill(desk, 3)                          # imported 10-02, 10-03, 10-04 at 09:00
    f = lambda **kw: [x["invoice_id"] for x in get(desk.client, "/data/invoices", **kw).json()["data"]]  # noqa: E731
    assert f(**{"from": "2026-10-02T09:00:00Z", "to": "2026-10-04T09:00:00Z"}) == ["inv-1", "inv-2"]       # from is inclusive, to exclusive
    assert f(**{"to": "2026-10-02T09:00:00Z"}) == []
    assert get(desk.client, "/data/invoices", **{"from": "2026-10-05", "to": "2026-10-04"}).json()["error"]["details"][0]["rule_id"] == "INVALID_WINDOW"
    assert get(desk.client, "/data/invoices", **{"from": "not-a-date"}).status_code == 422


def test_the_reference_entities_and_lineage_are_readable(desk):
    fill(desk, 1)
    for ent, n in (("vendors", 2), ("purchase_orders", 2), ("po_lines", 3), ("receipts", 3), ("approval_policies", 1), ("invoice_lines", 1),
                   ("import_lineage", 1), ("match_results", 1), ("audit_events", 3), ("dataset_versions", 1)):
        assert get(desk.client, f"/data/{ent}").json()["meta"]["total_count"] == n, ent
    lin = get(desk.client, "/data/import_lineage", source_sha256=sha("bytes-inv-1")).json()["data"][0]
    assert lin["invoice_id"] == "inv-1" and lin["import_status"] == "accepted"


def test_the_invoice_audit_and_lineage_gather_everything_about_one_invoice(desk):
    desk.ready("inv-1")
    desk.approve("inv-1")
    desk.post("export-payable", {"batch_id": "b", "invoice_ids": ["inv-1"]}, REVIEWER)
    desk.imp("inv-1b", [("lb", "pol-1", "6", "20.00")], source_sha256=sha("bytes-inv-1"), invoice_number="INV-1")             # the same bytes under another id
    for path in ("audit", "lineage"):
        body = get(desk.client, f"/data/invoices/inv-1/{path}").json()["data"]
        assert body["invoice"]["status"] == "exported" and [l["invoice_line_id"] for l in body["lines"]] == ["inv-1-1"]
        assert [x["action"] for x in body["audit"]] == ["import-invoice", "validate-invoice", "match-three-way", "approve-invoice", "export-payable"]
        assert [x["import_status"] for x in body["lineage"]] == ["accepted", "merged"]               # the merged copy is part of the lineage
        assert body["match_results"][0]["rule_version"] == "1" and body["approvals"][0]["policy_version"] == 1
        assert body["export_rows"][0]["amount"] == "132.00" and body["credit_notes"] == []
    assert get(desk.client, "/data/invoices/inv-nope/audit").status_code == 404


def test_metrics_envelope_window_and_cutoffs(desk):
    fill(desk, 3)
    r = get(desk.client, "/metrics", cutoff="2026-10-04T00:00:00Z,2026-10-26T00:00:00Z")
    body = r.json()
    assert r.status_code == 200 and list(body["data"]["metrics"]) == ["matched", "obligations", "exceptions", "duplicates", "quantities", "snapshots",
                                                                       "rates", "processing", "approvals", "payable", "export"]
    assert body["data"]["snapshot_cutoffs"] == ["2026-10-04T00:00:00Z", "2026-10-26T00:00:00Z"]
    snaps = body["data"]["metrics"]["snapshots"]      # the receipts arrive on 10-05: before that nothing is received, so nothing can be consumed
    assert (snaps["2026-10-04T00:00:00Z"]["net_received_quantity"], snaps["2026-10-04T00:00:00Z"]["accepted_invoiced_quantity"]) == ("0.0000", "0.0000")
    assert (snaps["2026-10-26T00:00:00Z"]["net_received_quantity"], snaps["2026-10-26T00:00:00Z"]["accepted_invoiced_quantity"]) == ("206.0000", "3.0000")
    assert body["data"]["disclosures"]["rule_version"] == "1" and body["meta"]["applied_filters"]["group_by"] == "none"
    win = get(desk.client, "/metrics", **{"from": "2026-10-03T00:00:00Z", "to": "2026-10-04T09:00:00Z"}).json()
    wm = win["data"]["metrics"]
    # inv-2 only (inv-3 is imported AT `to`); every fact is read as of `to`, when the receipts (10-05) have not arrived: blocked
    assert (wm["rates"]["eligible_invoices"], wm["exceptions"]["by_reason"]["QUANTITY_BLOCKED"], win["meta"]["total_count"]) == (1, 1, 1)
    late = get(desk.client, "/metrics", **{"from": "2026-10-03T00:00:00Z", "to": "2026-10-04T09:00:01Z"}).json()["data"]["metrics"]
    assert late["rates"]["eligible_invoices"] == 2


def test_metrics_group_by_vendor_and_currency(desk):
    desk.ready("inv-1", [("l1", "pol-3", "2", "2.00")])
    desk.ready("inv-2", [("l2", "pol-2", "4", "5.00")], vendor_id="ven-2", currency="EUR")
    data = get(desk.client, "/metrics", group_by="vendor").json()["data"]
    assert [(g["key"], g["metrics"]["matched"]["total"]) for g in data["groups"]] == [("ven-1", "4.40"), ("ven-2", "22.00")]
    assert [g["key"] for g in get(desk.client, "/metrics", group_by="currency").json()["data"]["groups"]] == ["EUR", "USD"]
    r = get(desk.client, "/metrics", group_by="colour")
    assert r.status_code == 422 and r.json()["error"]["details"][0]["rule_id"] == "INVALID_GROUP_BY"
    assert get(desk.client, "/metrics", **{"from": "2026-10-05", "to": "2026-10-04"}).status_code == 422
    assert get(desk.client, "/metrics", cutoff="soon").status_code == 422


def test_metrics_say_when_the_stored_workflow_state_differs_from_the_facts(desk):
    desk.ready("inv-1")
    assert get(desk.client, "/metrics").json()["warnings"] == []
    desk.conn.execute("UPDATE receipts SET reversed = TRUE WHERE receipt_id = 'rc-001'")        # a receipt is reversed after the match
    w = get(desk.client, "/metrics").json()["warnings"]
    assert [(x["code"], x["path"]) for x in w] == [("WORKFLOW_STATE_DIFFERS", "invoices[inv-1]")] and "stored as matched" in w[0]["message"]


def test_an_empty_database_answers_honestly(client, conn):
    body = get(client, "/metrics").json()
    m = body["data"]["metrics"]
    assert m["rates"] == {"eligible_invoices": 0, "straight_through_rate": None, "exception_rate": None} and body["meta"]["dataset_version"] == "unversioned"
    assert get(client, "/data/invoices").json()["data"] == []
