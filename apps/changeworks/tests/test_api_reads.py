"""The read side: the golden metrics through the API for all three fixtures, the half-open window, as_of, and the entity reads (no records, one record,
multiple pages, invalid filter, stable ordering, evidence reconciliation)."""
import psycopg
import pytest

from api import clock
from api.app import PREFIX

from support_db import (VARIANTS, ADMIN, client, command, conn, count, db_url, flat, get, golden_expected, golden_inputs, load, metrics, SPONSOR,  # noqa: F401
                        table_digest)

ENTITIES = ["initiatives", "process_baselines", "assumption_versions", "cost_items", "benefit_items", "dependencies", "stakeholder_groups", "readiness_assessments",
            "adoption_observations", "benefit_observations", "risk_items", "scenario_versions", "resources", "resource_allocations", "impact_mappings", "training_completions",
            "forecast_versions"]
KEYS = {"initiatives": "initiative_id", "process_baselines": "baseline_id", "assumption_versions": "assumption_id", "cost_items": "cost_id", "benefit_items": "benefit_id",
        "dependencies": "dependency_id", "stakeholder_groups": "group_id", "readiness_assessments": "assessment_id", "adoption_observations": "observation_id",
        "benefit_observations": "benefit_observation_id", "risk_items": "risk_id", "scenario_versions": "scenario_id", "resources": "resource_id",
        "resource_allocations": "allocation_id", "impact_mappings": "mapping_id", "training_completions": "training_id", "forecast_versions": "forecast_id"}
EVIDENCE = {"initiatives": "initiative_id,title,sponsor_id,status,baseline_version", "process_baselines": "baseline_id,initiative_id,volume,minutes_per_case,error_rate",
            "assumption_versions": "assumption_id,initiative_id,name,value,version_number", "cost_items": "cost_id,initiative_id,cost_type,amount,period_index",
            "benefit_items": "benefit_id,initiative_id,benefit_type,amount,period_index", "dependencies": "dependency_id,initiative_id,prerequisite_id,dependency_type,lag_periods",
            "stakeholder_groups": "group_id,group_name,owner_id,affected_count,impact_level", "readiness_assessments": "assessment_id,group_id,dimension,score,assessed_at",
            "adoption_observations": "observation_id,initiative_id,eligible_count,adopted_count,observed_at",
            "benefit_observations": "benefit_observation_id,benefit_id,measured_value,evidence_ref,observed_at", "risk_items": "risk_id,initiative_id,probability,impact,mitigation",
            "scenario_versions": "scenario_id,baseline_version,discount_rate,horizon_periods,created_at"}


@pytest.mark.parametrize("variant", VARIANTS)
def test_metrics_endpoint_equals_expected_json_leaf_for_leaf_ingest_included(client, conn, variant):
    inputs = golden_inputs(variant)
    load(conn, inputs)
    r = metrics(client, as_of=inputs["as_of"])
    want = golden_expected(variant)
    assert flat(r["data"]["metrics"]) == flat(want["metrics"])
    assert flat(r["data"]["ingest"]) == flat(want["ingest"])               # counts and the rejected records with their raw rows
    d = r["data"]
    assert (d["empty_population"], d["period_basis"], d["as_of"]) == (want["empty_population"], want["period_basis"], want["as_of"])
    assert r["meta"]["contract_version"] == 1 and r["meta"]["dataset_version"].startswith("ds-") and r["warnings"] == []
    assert set(r["meta"]) == {"dataset_version", "code_sha", "contract_version", "generated_at", "applied_filters", "total_count", "next_cursor", "exclusions"}


def test_api_golden_figures(client, conn):
    load(conn, golden_inputs())
    m = metrics(client, as_of="2028-06-30T00:00:00Z")["data"]["metrics"]
    i1 = m["scenarios"]["scn-001"]["initiatives"]["init-001"]
    assert (i1["npv"]["value"], i1["payback"]["simple"]["interpolated"], i1["payback"]["discounted"]["interpolated"]) == ("41.32", "1.6667", "1.9167")
    assert m["scenarios"]["scn-001"]["double_count"]["residual"] == "75.00" and m["groups"]["grp-001"]["readiness_score"] == "3.3333"


def test_scenario_filter_unknown_scenario_and_empty_database(client, conn):
    assert metrics(client)["data"]["empty_population"] is True and metrics(client)["data"]["metrics"]["summary"]["npv_total"] is None      # an empty database: nothing invented
    load(conn, golden_inputs("variant-rejected"))
    one = metrics(client, scenario_id="rs-3", as_of="2026-06-30T00:00:00Z")
    assert list(one["data"]["metrics"]["scenarios"]) == ["rs-3"] and one["data"]["metrics"]["summary"]["summary_scenario_id"] == "rs-3" and one["meta"]["total_count"] == 1
    r = get(client, "/metrics", scenario_id="rs-1")                 # rejected at ingest: it does not exist
    assert r.status_code == 404 and r.json()["error"]["details"][0]["rule_id"] == "UNKNOWN_SCENARIO"


def test_as_of_time_travel_and_the_default_is_the_servers_now(client, conn):
    load(conn, golden_inputs())
    early = metrics(client, as_of="2026-12-31T23:59:59Z")["data"]
    assert early["metrics"]["scenarios"]["scn-001"]["initiatives"]["init-001"]["cost_variance"]["reason"] == "NO_MATURED_PERIOD"
    assert early["metrics"]["initiatives"]["init-001"]["adoption"]["adoption_rate"] is None                                      # nothing observed yet
    late = metrics(client, as_of="2029-01-01T00:00:00Z")["data"]["metrics"]["initiatives"]["init-001"]["adoption"]
    assert late["adoption_rate"] == "0.900000" and late["excluded_after_as_of"] == []                                           # ad-3 (36/40) now exists
    clock.freeze(__import__("datetime").datetime(2028, 3, 1, tzinfo=__import__("datetime").timezone.utc))
    now = metrics(client)["data"]
    assert now["as_of"].startswith("2028-03-01T00:00:00") and now["metrics"]["initiatives"]["init-001"]["adoption"]["adoption_rate"] == "0.250000"


def test_window_is_half_open_and_says_the_model_is_not_windowed(client, conn):
    load(conn, golden_inputs())
    r = metrics(client, as_of="2028-06-30T00:00:00Z", **{"from": "2027-01-01", "to": "2028-03-31"})          # ad-1 (2027-03-31) in; ad-2 is exactly at `to`: out
    ad = r["data"]["metrics"]["initiatives"]["init-001"]["adoption"]
    assert [s["observation_id"] for s in ad["series"]] == ["ad-1"] and [w["code"] for w in r["warnings"]] == ["MODEL_NOT_WINDOWED"]
    assert r["data"]["window"] == {"from": "2027-01-01T00:00:00Z", "to": "2028-03-31T00:00:00Z"} and r["meta"]["applied_filters"]["from"] == "2027-01-01T00:00:00Z"
    assert r["data"]["metrics"]["scenarios"]["scn-001"]["initiatives"]["init-001"]["npv"]["value"] == "41.32"     # the dated model is not windowed
    only = metrics(client, as_of="2028-06-30T00:00:00Z", **{"from": "2028-01-01"})["data"]["metrics"]["scenarios"]["scn-001"]["initiatives"]["init-002"]["cost_variance"]
    assert only["reason"] == "NO_MATURED_PERIOD" and only["variance"] is None             # a window that starts at period 2 holds no matured period
    for bad in ({"from": "2028-01-01", "to": "2027-01-01"}, {"from": "2028-01-01", "to": "2028-01-01"}, {"from": "yesterday"}, {"to": "2028-13-01"}, {"as_of": "soon"}):
        r = get(client, "/metrics", **bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED", bad


# ------------------------------------------------------------------------------------------------------------ entity reads
@pytest.mark.parametrize("entity", ENTITIES)
def test_no_records_one_record_and_the_evidence_fields_of_every_entity(client, conn, entity):
    empty = get(client, f"/data/{entity}")
    assert empty.status_code == 200 and empty.json()["data"] == [] and empty.json()["meta"]["total_count"] == 0 and empty.json()["meta"]["next_cursor"] is None
    load(conn, golden_inputs())
    full = get(client, f"/data/{entity}").json()
    assert full["meta"]["total_count"] == len(full["data"]) > 0
    if entity in EVIDENCE:
        assert set(EVIDENCE[entity].split(",")) <= set(full["data"][0])
    one = get(client, f"/data/{entity}", limit=1).json()
    assert len(one["data"]) == 1 and one["meta"]["total_count"] == full["meta"]["total_count"]                 # the total is separate from the page length
    assert (one["meta"]["next_cursor"] is not None) == (full["meta"]["total_count"] > 1)


@pytest.mark.parametrize("entity", ENTITIES)
def test_pages_are_stable_ordered_by_key_with_no_duplicates_or_gaps(client, conn, entity):
    load(conn, golden_inputs("variant-rejected") if entity in ("initiatives", "cost_items", "benefit_items") else golden_inputs())
    key = KEYS[entity]
    seen, cur, pages = [], None, 0
    while True:
        page = get(client, f"/data/{entity}", limit=2, cursor=cur).json()
        seen += [r[key] for r in page["data"]]
        cur, pages = page["meta"]["next_cursor"], pages + 1
        if not cur:
            break
    total = get(client, f"/data/{entity}").json()["meta"]["total_count"]
    assert seen == sorted(seen) and len(seen) == len(set(seen)) == total and pages == -(-total // 2)
    assert seen == [r[key] for r in get(client, f"/data/{entity}").json()["data"]]                                # the same order whatever the page size


def test_invalid_filters_cursors_limits_windows_and_unknown_entities(client, conn):
    load(conn, golden_inputs())
    assert get(client, "/data/cost_items", color="red").status_code == 422
    assert get(client, "/data/cost_items", initiative_id="init-001", cost_basis="actual").json()["meta"]["total_count"] == 1
    r = get(client, "/data/cost_items", cost_type="weekly")
    assert r.status_code == 200 and r.json()["data"] == []                                                         # a value with no match is an empty page, not an error
    assert get(client, "/data/benefit_items", period_index="x").json()["error"]["details"][0]["rule_id"] == "INVALID_FILTER"
    assert get(client, "/data/cost_items", cursor="@@").json()["error"]["details"][0]["rule_id"] == "INVALID_CURSOR"
    assert get(client, "/data/nothing").status_code == 404 and get(client, "/data/cost_items", limit=0).status_code == 422 and get(client, "/data/cost_items", limit=201).status_code == 422
    assert get(client, "/data/resources", **{"from": "2026-01-01"}).status_code == 422                              # no time field to filter on
    assert get(client, "/data/audit_events", **{"from": "2028-02-01", "to": "2028-01-01"}).status_code == 422
    win = get(client, "/data/adoption_observations", **{"from": "2027-03-31T00:00:00Z", "to": "2028-03-31T00:00:00Z"}).json()["data"]
    assert [x["observation_id"] for x in win] == ["ad-1"]                                                           # [from, to): ad-2 at exactly `to` is out
    assert [x["observation_id"] for x in get(client, "/data/adoption_observations", **{"from": "2028-03-31T00:00:00Z"}).json()["data"]] == ["ad-2", "ad-3", "ad-4", "ad-5"]


def test_evidence_reconciles_with_the_ingest_the_sql_and_the_metrics(client, conn):
    inputs = golden_inputs()
    load(conn, inputs)
    counts = golden_expected()["ingest"]["counts"]
    for entity in ENTITIES:
        assert get(client, f"/data/{entity}").json()["meta"]["total_count"] == counts[entity]["accepted"], entity
    costs = get(client, "/data/cost_items", limit=200).json()["data"]
    assert sorted(c["amount"] for c in costs)[0] == "100.00" and len(costs) == 7
    sql_sum = conn.execute("SELECT cw_dec(sum(amount)) AS s FROM cost_items WHERE cost_basis = 'planned' AND cost_type = 'one_time'").fetchone()["s"]
    from fractions import Fraction
    api_sum = sum((Fraction(c["amount"]) for c in costs if c["cost_basis"] == "planned" and c["cost_type"] == "one_time"), Fraction(0))
    assert Fraction(sql_sum) == api_sum == 2300                                                                      # 1000 + 500 + 800
    m = metrics(client, as_of="2028-06-30T00:00:00Z")["data"]["metrics"]["scenarios"]["scn-001"]["initiatives"]
    assert sum(Fraction(x["amount"]) for i in m.values() for x in i["expanded_planned_costs"] if x["period_index"] == 0) == 2300       # the metrics read the same rows
    rej = load_rejected(client, conn)
    assert rej["meta"]["total_count"] == 30 and rej["data"][0]["raw_row"] and set(rej["data"][0]) >= {"entity", "id", "reason_code", "details", "raw_row"}


def load_rejected(client, conn):
    load(conn, golden_inputs("variant-rejected"))
    return get(client, "/data/rejected_records", limit=200).json()


def test_scenario_rows_carry_initiatives_pins_and_amounts_keep_their_places(client, conn):
    load(conn, golden_inputs())
    sc = get(client, "/data/scenario_versions").json()["data"][0]
    assert sc["initiative_ids"] == ["init-001", "init-002", "init-003"] and sc["pinned_assumption_ids"] == ["a-101-t1", "a-201-r1", "a-201-t1"]
    assert (sc["discount_rate"], sc["status"], sc["horizon_periods"], sc["created_at"]) == ("0.100000", "draft", 3, "2026-01-15T09:00:00Z")
    a = {x["assumption_id"]: x for x in get(client, "/data/assumption_versions").json()["data"]}
    assert a["a-101-t1"]["value"] == "8" and a["a-201-r1"]["values"] == ["0.500000", "1.000000"] and a["a-201-r1"]["value"] is None
    assert get(client, "/data/risk_items").json()["data"][0]["probability"] == "0.200000"
    assert get(client, "/data/benefit_items", benefit_type="capacity").json()["meta"]["total_count"] == 2


def test_the_reads_never_expose_a_funded_status_or_secrets(client, conn):
    load(conn, golden_inputs())
    spec = client.get(f"{PREFIX}/openapi.json").json()
    props = spec["components"]["schemas"]["SelectScenarioInput"]["properties"]["status"]
    assert props["default"] == "proposed" and "enum" not in props and "funded" not in str(spec["components"]["schemas"]["ReadResponse"]).lower()       # a selection proposes
    for e in ENTITIES:
        text = get(client, f"/data/{e}").text.lower()
        assert "postgresql://" not in text and "password" not in text and "funded" not in text


def test_openapi_lists_every_route(client):
    spec = client.get(f"{PREFIX}/openapi.json").json()
    paths = set(spec["paths"])
    for c in ("establish-baseline", "assess-opportunity", "build-cash-flows", "map-impacts", "assess-readiness", "plan-roadmap", "select-scenario", "record-adoption", "track-benefits",
              "revise-forecast"):
        assert f"{PREFIX}/commands/{c}" in paths
    assert {f"{PREFIX}/metrics", f"{PREFIX}/data/{{entity}}"} <= paths
