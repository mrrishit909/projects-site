"""The read side: the golden metrics through the API for all three fixtures, filters, groups, windows, cursors and the entity reads."""
import pytest

from support_db import VARIANTS, client, conn, db_url, flat, get, golden_expected, golden_inputs, load, metrics  # noqa: F401


@pytest.mark.parametrize("variant", VARIANTS)
def test_metrics_endpoint_equals_expected_json_key_by_key(client, conn, variant):
    inputs = golden_inputs(variant)
    load(conn, inputs)
    r = metrics(client, as_of=inputs["as_of"])
    want = golden_expected(variant)
    assert set(r["data"]["metrics"]) == set(want["metrics"])
    assert flat(r["data"]["metrics"]) == flat(want["metrics"])
    assert flat(r["data"]["rules"]) == flat(want["rules"]) and flat(r["data"]["definitions"]) == flat(want["definitions"])
    assert flat(r["data"]["matching"]) == flat(want["matching"])
    assert r["data"]["empty_population"] is want["empty_population"] and r["data"]["weight_version"] == want["weight_version"]
    assert r["meta"]["contract_version"] == 1 and r["meta"]["dataset_version"].startswith("ds-")


def test_api_golden_figures(client, conn):
    load(conn, golden_inputs())
    m = metrics(client, as_of="2026-10-05T00:00:00Z")["data"]["metrics"]
    assert m["completeness"]["r-cust-complete-email"]["value"] == "0.950000"
    v = m["validity"]["r-cust-valid-email"]
    assert (v["populated_only"]["value"], v["all_eligible"]["value"]) == ("0.947368", "0.900000")
    assert m["weighted_score"]["datasets"]["ds-customers"]["value"] == "0.963932"
    assert m["weighted_score"]["datasets"]["ds-customers"]["critical_override"] is True
    assert m["match_precision"]["precision"] == "0.666667"


def test_weight_version_dataset_filter_and_unknown_inputs(client, conn):
    load(conn, golden_inputs())
    w1 = metrics(client, as_of="2026-10-05T00:00:00Z", weight_version="w1")["data"]
    assert w1["weight_version"] == "w1" and w1["metrics"]["weighted_score"]["datasets"]["ds-customers"]["value"] == "0.958116"
    assert w1["metrics"]["weighted_score"]["datasets"]["ds-customers"]["weight_version"] == "w1"
    one = metrics(client, as_of="2026-10-05T00:00:00Z", dataset_id="ds-orders")
    assert list(one["data"]["metrics"]["weighted_score"]["datasets"]) == ["ds-orders"] and list(one["data"]["metrics"]["relationship_integrity"]) == ["r-ord-cust-fk"]
    assert one["data"]["metrics"]["completeness"] == {} and any(w["code"] == "PORTFOLIO_WIDE_METRICS" for w in one["warnings"])
    assert get(client, "/metrics", dataset_id="nope").status_code == 404
    assert get(client, "/metrics", weight_version="w9").json()["error"]["details"][0]["rule_id"] == "UNKNOWN_WEIGHT_VERSION"
    assert get(client, "/metrics", group_by="color").json()["error"]["details"][0]["rule_id"] == "INVALID_GROUP_BY"
    assert get(client, "/metrics", **{"from": "2026-10-05T00:00:00Z", "to": "2026-10-01T00:00:00Z"}).json()["error"]["details"][0]["rule_id"] == "INVALID_WINDOW"
    assert get(client, "/metrics", as_of="yesterday").status_code == 422


def test_as_of_time_travel_uses_the_weight_version_in_force(client, conn):
    load(conn, golden_inputs())
    early = metrics(client, as_of="2026-08-20T00:00:00Z")["data"]                      # before w2 (2026-09-01): w1 is in force
    assert early["weight_version"] == "w1"
    assert early["metrics"]["definition_coverage"]["published_metrics"] == 4            # m-revenue v1 (valid 2026-03-01) still in force: v2 starts 2026-08-15 09:00
    mid = metrics(client, as_of="2026-08-15T08:00:00Z")["data"]["definitions"]["effective_at_as_of"]
    assert mid["m-revenue"] == "mv-rev-1"
    after = metrics(client, as_of="2026-08-15T10:00:00Z")["data"]["definitions"]["effective_at_as_of"]
    assert after["m-revenue"] == "mv-rev-2"


def test_group_by_every_dimension(client, conn):
    load(conn, golden_inputs())
    base = {"as_of": "2026-10-05T00:00:00Z"}
    by_ds = metrics(client, group_by="dataset", **base)["data"]["groups"]
    assert sorted(by_ds) == ["ds-customers", "ds-orders", "ds-payments", "ds-products", "ds-shipments"]
    assert by_ds["ds-customers"]["metrics"]["weighted_score"]["datasets"]["ds-customers"]["value"] == "0.963932"
    assert "definition_coverage" not in by_ds["ds-customers"]["metrics"]
    by_owner = metrics(client, group_by="owner", **base)["data"]["groups"]
    assert by_owner["own-05"]["datasets"] == 1 and by_owner["own-05"]["metrics"]["ownership_coverage"]["uncovered"] == ["ds-shipments"]
    by_src = metrics(client, group_by="source_system", **base)["data"]["groups"]
    assert sum(g["datasets"] for g in by_src.values()) == 5
    sev = metrics(client, group_by="severity", **base)["data"]["groups"]
    assert sorted(sev) == ["critical", "high", "medium"]
    assert sev["critical"]["metrics"]["critical_failures"]["failures"] == 2 and sev["critical"]["rules"] == 1
    assert sev["high"]["metrics"]["critical_failures"]["failures"] == 0
    assert list(sev["high"]["metrics"]["completeness"]) == ["r-cust-complete-email"]


def test_window_narrows_the_time_stamped_facts_half_open(client, conn):
    load(conn, golden_inputs())
    base = {"as_of": "2026-10-05T00:00:00Z"}
    # iss-001 detected 09-20 08:00, iss-002 09-22 09:15, iss-003 09-25 10:00, iss-005 09-10, iss-006 09-30, iss-004 08-25
    w = metrics(client, **{"from": "2026-09-20T08:00:00Z", "to": "2026-09-25T10:00:00Z"}, **base)["data"]["metrics"]["resolution_time"]
    assert sorted(w["issues"]) == ["iss-001", "iss-002"] and w["mean_hours"] == "21.5000"      # (30.5 + 12.5) / 2; the end is exclusive
    p = metrics(client, **{"from": "2026-09-30T00:00:00Z"}, **base)["data"]["metrics"]
    assert sorted(p["resolution_time"]["issues"]) == ["iss-006"]
    assert p["match_precision"]["approved_decisions"] == 0                                    # all decisions are before the window
    assert p["completeness"]["r-cust-complete-email"]["value"] == "0.950000"                  # a snapshot of the rows: not windowed


def test_entity_reads_order_cursor_filters_and_errors(client, conn):
    load(conn, golden_inputs())
    first = get(client, "/data/rule_runs", limit=5).json()
    assert [r["rule_run_id"] for r in first["data"]] == [f"rr-00{i}" for i in range(1, 6)] and first["meta"]["total_count"] == 13
    seen, cur = [], None
    while True:
        page = get(client, "/data/rule_runs", limit=4, cursor=cur).json()
        seen += [r["rule_run_id"] for r in page["data"]]
        cur = page["meta"]["next_cursor"]
        if not cur:
            break
    assert seen == sorted(seen) and len(seen) == len(set(seen)) == 13
    assert [r["rule_run_id"] for r in get(client, "/data/rule_runs", rule_id="r-cust-complete-email", kind="rerun").json()["data"]] == ["rr-011", "rr-013"]
    win = get(client, "/data/rule_runs", **{"from": "2026-09-20T08:00:00Z", "to": "2026-09-22T09:15:00Z"}).json()["data"]
    assert [r["rule_run_id"] for r in win] == ["rr-006", "rr-007"]                             # [from, to): rr-008 at 09:15 is excluded
    assert get(client, "/data/rule_runs", color="red").status_code == 422
    assert get(client, "/data/rule_runs", cursor="@@").json()["error"]["details"][0]["rule_id"] == "INVALID_CURSOR"
    assert get(client, "/data/nothing").status_code == 404
    assert get(client, "/data/customer_records", **{"from": "2026-01-01T00:00:00Z"}).status_code == 422
    assert get(client, "/data/rule_runs", limit=0).status_code == 422


def test_issue_rows_carry_class_and_lineage_rows_carry_evidence_type(client, conn):
    load(conn, golden_inputs())
    issues = {r["issue_id"]: r for r in get(client, "/data/issues").json()["data"]}
    assert {k: v["class"] for k, v in issues.items()} == {"iss-001": "resolved", "iss-002": "resolved", "iss-003": "resolved", "iss-004": "claimed",
                                                         "iss-005": "open", "iss-006": "open"}
    assert issues["iss-003"]["resolved_at"] == "2026-09-28T10:20:00Z" and issues["iss-005"]["reopen_cycles"] == 1
    edges = get(client, "/data/lineage_edges").json()["data"]
    by = {e["edge_id"]: e["evidence_type"] for e in edges}
    assert by["ei-1"] == "inferred" and by["eo-7"] == "observed" and by["ed-6"] == "declared"
    assert [e["edge_id"] for e in get(client, "/data/lineage_edges", evidence_type="inferred").json()["data"]] == ["ei-1"]


def test_comparable_runs_read(client, conn):
    load(conn, golden_inputs())
    data = {r["rule_id"]: r for r in get(client, "/data/comparable_runs").json()["data"]}
    valid = data["r-cust-valid-email"]
    assert sorted({x["rule_version"] for x in valid["runs"]}) == [1]
    assert valid["current_rule_version"] == 2
    one = get(client, "/data/comparable_runs", rule_id="r-cust-complete-email").json()["data"][0]
    assert one["comparable_pairs"] == len(one["comparisons"]) and all(c["comparable"] for c in one["comparisons"])
    assert get(client, "/data/comparable_runs", rule_id="nope").status_code == 404
    assert get(client, "/data/identity_map").json()["data"]["identity_map"]["rec-006"] == "rec-006"       # md-3 was reversed: both identities restored


def test_metrics_default_as_of_is_the_servers_now_and_openapi_lists_the_routes(client, conn):
    from api.app import PREFIX
    load(conn, golden_inputs())
    r = metrics(client)["data"]                                              # the frozen test clock: 2026-10-26T22:00:00Z
    assert r["as_of"].startswith("2026-10-26T22:00:00") and r["weight_version"] == "w2" and r["metrics"]["timeliness"]["on_time_count"] == 0
    spec = client.get(f"{PREFIX}/openapi.json").json()
    paths = set(spec["paths"])
    for c in ("register-dataset", "publish-definition", "run-rule", "open-issue", "triage-issue", "suggest-match", "approve-merge", "reverse-merge",
              "disable-rule", "verify-remediation"):
        assert f"{PREFIX}/commands/{c}" in paths
    assert {f"{PREFIX}/metrics", f"{PREFIX}/data/{{entity}}", f"{PREFIX}/data/comparable_runs", f"{PREFIX}/data/identity_map"} <= paths
