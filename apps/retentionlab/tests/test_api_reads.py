"""Read endpoints: GET /data/{entity} (every entity, stable ordering, cursor, filters, half-open windows) and GET /metrics (the twelve metrics,
as_of, run, cutoff set, scenario, the K refusal). Minimum read tests: no records, one record, multiple pages, invalid filter, stable ordering,
evidence reconciliation."""
import base64
import json
from datetime import datetime, timezone

import pytest

from api import clock
from api.reads import ENTITIES
from support_db import (FEB, JAN, client, command, conn, count, db_url, flat, get, golden_expected, golden_inputs, load, metrics, rule_ids)  # noqa: F401
from mini import Mini
from worlds import READ_AS_OF, SETS, build_world, pipeline

LOGICAL = {  # the evidence fields of section 11, per entity
    "accounts": "account_id,created_at,segment,region,synthetic", "subscription_events": "subscription_event_id,account_id,event_type,event_at,available_at",
    "billing_events": "billing_event_id,account_id,amount,event_at,available_at", "usage_events": "usage_event_id,account_id,event_name,event_at,available_at",
    "support_events": "support_event_id,account_id,severity,event_at,available_at", "prediction_cutoffs": "cutoff_id,account_id,prediction_at,horizon_end,observation_start",
    "feature_rows": "feature_row_id,cutoff_id,feature_version,features_json,max_available_at", "labels": "label_id,cutoff_id,churned,label_end,mature",
    "training_runs": "training_run_id,train_end,validation_end,test_end,config_hash", "predictions": "prediction_id,training_run_id,cutoff_id,probability,scored_at",
    "intervention_scenarios": "scenario_id,capacity,contact_cost,assumed_effect,margin_value", "outreach_events": "outreach_event_id,account_id,scenario_id,action,status"}
EXTRA = ["feature_registry", "split_assignments", "scoring_publications"]


@pytest.fixture
def golden(client, conn):
    load(conn, golden_inputs())
    return client


# ---------------------------------------------------------------------------------------------------- no records
@pytest.mark.parametrize("entity", sorted(ENTITIES))
def test_no_records_is_an_empty_page_not_an_error(client, entity):
    r = get(client, f"/data/{entity}")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == [] and body["meta"]["total_count"] == 0 and body["meta"]["next_cursor"] is None and body["warnings"] == []
    assert set(body["meta"]) == {"dataset_version", "code_sha", "contract_version", "generated_at", "applied_filters", "total_count", "next_cursor", "exclusions"}


def test_metrics_with_no_records_is_the_empty_population_with_null_ratios(client):
    d = metrics(client)["data"]
    assert d["empty_population"] is True and d["cutoff_sets"] == {} and d["training_run_id"] is None
    assert d["freshness"]["scoring_hours"] is None and d["freshness"]["data_hours"] is None and d["scoring_publications"] == []
    r = get(client, "/metrics", prediction_at=JAN)
    assert r.status_code == 404 and rule_ids(r) == ["UNKNOWN_CUTOFF"]


def test_metrics_of_an_empty_variant_dataset_is_zero_counts_and_null_ratios(client, conn):
    load(conn, golden_inputs("variant-empty"))
    d = metrics(client, as_of="2026-05-01T00:00:00Z")["data"]
    assert d["cutoff_sets"] == {} and d["empty_population"] is True


# ---------------------------------------------------------------------------------------------------- one record
def test_one_record_with_the_documented_evidence_fields(client, conn):
    m = Mini()
    a = m.account(7)
    cid = m.cutoff(a, "2026-01-01T00:00:00Z")
    m.event("usage_events", a, "2025-12-20T00:00:00Z")
    load(conn, m.data())
    acc = get(client, "/data/accounts").json()
    assert acc["data"] == [{"account_id": 7, "created_at": "2024-01-01T00:00:00Z", "segment": "mid", "region": "amer", "synthetic": True}]
    assert acc["meta"]["total_count"] == 1 and acc["meta"]["next_cursor"] is None
    use = get(client, "/data/usage_events").json()["data"][0]
    assert set(use) == set(LOGICAL["usage_events"].split(",")) and use["event_at"] == "2025-12-20T00:00:00Z" and use["account_id"] == 7
    assert get(client, "/data/prediction_cutoffs").json()["data"][0]["cutoff_id"] == cid


@pytest.mark.parametrize("entity", sorted(LOGICAL))
def test_every_logical_entity_exposes_its_evidence_fields(golden, entity):
    rows = get(golden, f"/data/{entity}").json()["data"]
    assert rows and set(LOGICAL[entity].split(",")) <= set(rows[0])
    assert get(golden, f"/data/{entity}").json()["meta"]["total_count"] == len(rows)


@pytest.mark.parametrize("entity", EXTRA)
def test_the_registry_the_split_and_the_publications_are_readable(golden, entity):
    inputs = golden_inputs()
    rows = get(golden, f"/data/{entity}").json()["data"]
    assert len(rows) == len(inputs[entity])


def test_amounts_and_probabilities_are_exact_strings_never_floats(golden):
    bill = get(golden, "/data/billing_events", account_id=1).json()["data"]
    assert [b["amount"] for b in bill] == ["49.000000", "49.000000", "49.000000"]
    pr = get(golden, "/data/predictions", limit=200).json()["data"]
    assert {p["probability"] for p in pr} >= {"0.800000", "0.600000", "0.400000", "0.100000"} and all(isinstance(p["probability"], str) for p in pr)
    sc = get(golden, "/data/intervention_scenarios").json()["data"][0]
    assert (sc["contact_cost"], sc["assumed_effect"], sc["margin_value"], sc["capacity"]) == ("5.000000", "0.100000", "131.750000", 2)
    fr = get(golden, "/data/feature_rows", cutoff_id="co-01-20260101").json()["data"][0]
    assert fr["features_json"] == {"usage_events_30d": 2, "days_since_last_usage": 12, "high_severity_support_90d": 1, "billing_total_90d": "98.00"}


def test_reads_need_no_actor(golden):
    assert golden.get("/api/v1/retentionlab/data/accounts").status_code == 200
    assert golden.get("/api/v1/retentionlab/metrics", params={"as_of": "2026-05-01T00:00:00Z"}).status_code == 200
    assert golden.post("/api/v1/retentionlab/data/accounts").status_code == 405


# ---------------------------------------------------------------------------------------------------- multiple pages and stable ordering
@pytest.mark.parametrize("entity,key", [("usage_events", "usage_event_id"), ("prediction_cutoffs", "cutoff_id"), ("subscription_events", "subscription_event_id"),
                                       ("split_assignments", "assignment_id"), ("accounts", "account_id"), ("feature_registry", "feature_name")])
@pytest.mark.parametrize("limit", [1, 4, 9])
def test_pages_concatenate_to_the_full_list_with_no_duplicates_or_gaps(golden, entity, key, limit):
    full = get(golden, f"/data/{entity}", limit=200).json()
    total = full["meta"]["total_count"]
    assert len(full["data"]) == total
    seen, cursor, pages = [], None, 0
    while True:
        r = get(golden, f"/data/{entity}", limit=limit, cursor=cursor).json()
        assert r["meta"]["total_count"] == total and len(r["data"]) <= limit
        seen += r["data"]
        pages += 1
        cursor = r["meta"]["next_cursor"]
        if cursor is None:
            break
        assert len(r["data"]) == limit
    assert seen == full["data"] and pages == -(-total // limit)
    keys = [row[key] for row in seen]
    assert len(set(keys)) == len(keys)


def test_ordering_is_code_point_order_for_text_keys_and_numeric_for_integer_keys(client, conn):
    m = Mini()
    for aid in (10, 2, 9, 100):
        m.account(aid)
    for suffix in ("b", "B", "a", "_"):
        m.d["usage_events"].append({"usage_event_id": f"ue-{suffix}", "account_id": 2, "event_name": "x", "event_at": "2025-12-01T00:00:00Z", "available_at": "2025-12-01T00:00:00Z"})
    load(conn, m.data())
    assert [a["account_id"] for a in get(client, "/data/accounts").json()["data"]] == [2, 9, 10, 100]            # numeric, not "10" < "2"
    assert [u["usage_event_id"] for u in get(client, "/data/usage_events").json()["data"]] == ["ue-B", "ue-_", "ue-a", "ue-b"]   # 'B' < '_' < 'a' < 'b'
    page1 = get(client, "/data/accounts", limit=2).json()
    assert [a["account_id"] for a in get(client, "/data/accounts", limit=2, cursor=page1["meta"]["next_cursor"]).json()["data"]] == [10, 100]


def test_limit_bounds(golden):
    assert get(golden, "/data/accounts", limit=200).status_code == 200
    for bad in (0, 201, -1):
        r = get(golden, "/data/accounts", limit=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"
    assert len(get(golden, "/data/accounts").json()["data"]) == 14                                          # the default limit is 50


# ---------------------------------------------------------------------------------------------------- invalid filters and cursors
@pytest.mark.parametrize("entity,params,rule", [
    ("accounts", {"colour": "red"}, "INVALID_FILTER"), ("accounts", {"synthetic": "yes"}, "INVALID_FILTER"), ("usage_events", {"account_id": "abc"}, "INVALID_FILTER"),
    ("accounts", {"from": "yesterday"}, "INVALID_FILTER"), ("accounts", {"from": "2026-01-02", "to": "2026-01-01"}, "INVALID_WINDOW"),
    ("accounts", {"from": "2026-01-01", "to": "2026-01-01"}, "INVALID_WINDOW"), ("feature_registry", {"from": "2026-01-01"}, "FILTER_NOT_SUPPORTED"),
    ("split_assignments", {"to": "2026-01-01"}, "FILTER_NOT_SUPPORTED"), ("accounts", {"cursor": "!!!"}, "INVALID_CURSOR"),
    ("accounts", {"cursor": base64.urlsafe_b64encode(b'["a","b"]').decode()}, "INVALID_CURSOR"), ("accounts", {"cursor": base64.urlsafe_b64encode(b'{"x":1}').decode()}, "INVALID_CURSOR"),
    ("accounts", {"cursor": base64.urlsafe_b64encode(b'["not-an-int"]').decode()}, "INVALID_CURSOR"), ("accounts", {"cursor": base64.urlsafe_b64encode(b'[true]').decode()}, "INVALID_CURSOR")])
def test_invalid_filters_windows_and_cursors_are_422_with_a_rule_id(golden, entity, params, rule):
    r = get(golden, f"/data/{entity}", **params)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED" and rule_ids(r) == [rule], r.text


def test_an_unknown_entity_is_404_and_a_hostile_filter_is_inert(golden, conn):
    r = get(golden, "/data/passwords")
    assert r.status_code == 404 and rule_ids(r) == ["ENTITY_UNKNOWN"]
    r = get(golden, "/data/audit_events%3B%20DROP%20TABLE%20accounts")
    assert r.status_code == 404
    r = get(golden, "/data/accounts", segment="mid'; DROP TABLE accounts; --")
    assert r.status_code == 200 and r.json()["data"] == [] and count(conn, "accounts") == 14
    r = get(golden, "/data/accounts", **{"segment; DROP TABLE accounts": "x"})
    assert r.status_code == 422 and count(conn, "accounts") == 14
    assert get(golden, "/data/accounts", segment="mid").json()["meta"]["total_count"] == sum(1 for a in golden_inputs()["accounts"] if a["segment"] == "mid")


def test_filters_equality_and_the_applied_filters_are_echoed(golden):
    r = get(golden, "/data/labels", mature="false", limit=3).json()
    assert r["meta"]["total_count"] == 4 and len(r["data"]) == 3 and r["meta"]["applied_filters"]["mature"] == "false" and r["meta"]["next_cursor"]
    assert {l["churned"] for l in r["data"]} == {None}
    assert get(golden, "/data/labels", churned="true").json()["meta"]["total_count"] == 2
    assert get(golden, "/data/usage_events", account_id=1).json()["meta"]["total_count"] == 7
    assert get(golden, "/data/outreach_events", status="draft").json()["meta"]["total_count"] == 2
    assert get(golden, "/data/outreach_events", status="sent").json()["data"] == []


def test_time_windows_are_half_open(golden):
    ev = get(golden, "/data/usage_events", account_id=1, limit=200).json()["data"]
    at = sorted(e["event_at"] for e in ev)
    lo, hi = at[2], at[5]
    got = [e["event_at"] for e in get(golden, "/data/usage_events", account_id=1, **{"from": lo, "to": hi}).json()["data"]]
    assert sorted(got) == [t for t in at if lo <= t < hi] and lo in got and hi not in got
    assert get(golden, "/data/usage_events", account_id=1, **{"from": "2030-01-01"}).json()["data"] == []
    jan = get(golden, "/data/prediction_cutoffs", **{"from": JAN, "to": FEB}).json()
    assert jan["meta"]["total_count"] == 6 and jan["meta"]["applied_filters"]["from"] == JAN


# ---------------------------------------------------------------------------------------------------- metrics: the golden fixture
def test_metrics_endpoint_equals_expected_json_for_each_set(golden):
    want = golden_expected()
    jan = metrics(golden, training_run_id="tr-001", prediction_at=JAN, scenario_id="sc-001", as_of="2026-05-01T00:00:00Z", reference_prediction_at="2025-03-01T00:00:00Z")["data"]
    feb = metrics(golden, training_run_id="tr-001", prediction_at=FEB, as_of="2026-05-01T00:00:00Z", reference_prediction_at="2025-03-01T00:00:00Z")["data"]
    assert flat(jan["cutoff_sets"][JAN]) == flat(want["cutoff_sets"][JAN]) and flat(feb["cutoff_sets"][FEB]) == flat(want["cutoff_sets"][FEB])
    assert jan["freshness"] == want["freshness"] and jan["scoring_publications"] == want["scoring_publications"] and jan["consistency"] == want["consistency"]
    both = metrics(golden, training_run_id="tr-001", **{"from": JAN, "to": "2026-03-01T00:00:00Z"}, as_of="2026-05-01T00:00:00Z")["data"]
    assert list(both["cutoff_sets"]) == [JAN, FEB]


def test_the_default_set_selection_is_every_set_and_the_run_defaults_to_the_only_one(golden):
    d = metrics(golden, as_of="2026-05-01T00:00:00Z")["data"]
    assert list(d["cutoff_sets"]) == ["2025-03-01T00:00:00Z", "2025-03-19T00:00:00Z", "2025-05-01T00:00:00Z", "2025-07-01T00:00:00Z", "2025-08-19T00:00:00Z",
                                     "2025-09-15T00:00:00Z", "2025-12-01T00:00:00Z", JAN, FEB] and d["training_run_id"] == "tr-001"
    assert d["empty_population"] is False


def test_a_cutoff_id_names_its_set(golden):
    d = metrics(golden, cutoff_id="co-04-20260101,co-02-20260201", as_of="2026-05-01T00:00:00Z")["data"]
    assert list(d["cutoff_sets"]) == [JAN, FEB]
    r = get(golden, "/metrics", cutoff_id="co-nope")
    assert r.status_code == 404 and rule_ids(r) == ["UNKNOWN_CUTOFF"]


def test_as_of_decides_what_is_known_and_what_is_mature(golden):
    mature = metrics(golden, training_run_id="tr-001", prediction_at=JAN, as_of="2026-05-01T00:00:00Z")["data"]["cutoff_sets"][JAN]
    early = metrics(golden, training_run_id="tr-001", prediction_at=JAN, as_of="2026-04-12T00:00:00Z")["data"]["cutoff_sets"][JAN]
    assert mature["population"]["mature"] == 4 and mature["churn_rate"]["value"] == "0.500000"
    assert early["population"]["mature"] == 0 and early["population"]["censored"] == 4 and early["churn_rate"]["value"] is None and early["precision_at_k"] is None
    # D-09 (R10-01): the future is not known. An as_of later than the server clock is refused; and a stored CENSORED label stays censored in every report
    # until the labelling command (C02) matures it at a clock past its label_end, so a later as_of can never relabel a row by itself.
    future = get(golden, "/metrics", _server_clock=True, training_run_id="tr-001", prediction_at=FEB, as_of="2026-05-17T00:00:00Z")
    assert future.status_code == 422 and rule_ids(future) == ["AS_OF_IN_FUTURE"]
    before = metrics(golden, training_run_id="tr-001", prediction_at=FEB, as_of="2026-05-17T00:00:00Z")["data"]
    assert before["cutoff_sets"][FEB]["population"]["mature"] == 0 and before["cutoff_sets"][FEB]["churn_rate"]["value"] is None       # stored labels are authoritative
    assert before["consistency"]["labels_mismatched"] != []                                                                          # the disagreement is a finding, not a relabel
    clock.freeze(datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc))
    assert command(golden, "define-label", {"prediction_at": FEB}).json()["result"]["matured_now"] == 4                               # the one place a label matures
    late = metrics(golden, training_run_id="tr-001", prediction_at=FEB, as_of="2026-05-17T00:00:00Z")["data"]["cutoff_sets"][FEB]
    assert late["population"]["mature"] == 4 and late["population"]["unscored_excluded"] == 1 and late["population"]["evaluated"] == 3        # now Feb labels are known
    assert late["churn_rate"]["churned"] == 4 and late["churn_rate"]["value"] == "1.000000"                                           # all four cancel inside the Feb horizon and arrive before 05-16
    clock.freeze(datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc))                                                                  # back to the test clock
    default = metrics(golden)["data"]
    assert default["as_of"].startswith("2026-05-01T12:00:00")                                                                         # the server's clock


@pytest.mark.parametrize("params,status,rule", [
    ({"training_run_id": "tr-none"}, 404, "UNKNOWN_TRAINING_RUN"), ({"scenario_id": "sc-none"}, 404, "UNKNOWN_SCENARIO"), ({"prediction_at": "2031-01-01T00:00:00Z"}, 404, "UNKNOWN_CUTOFF"),
    ({"reference_prediction_at": "2031-01-01T00:00:00Z"}, 404, "UNKNOWN_CUTOFF"), ({"model": "oracle"}, 422, "UNKNOWN_MODEL"), ({"as_of": "soon"}, 422, "INVALID_FILTER"),
    ({"from": JAN, "to": JAN}, 422, "INVALID_WINDOW"), ({"from": "2026-02-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"}, 422, "INVALID_WINDOW")])
def test_metrics_input_errors(golden, params, status, rule):
    r = get(golden, "/metrics", **params)
    assert r.status_code == status and rule_ids(r) == [rule]


def test_several_training_runs_require_a_choice(golden, conn):
    conn.execute("INSERT INTO training_runs VALUES ('tr-002', '2025-07-01T00:00:00Z', '2025-12-01T00:00:00Z', '2026-06-01T00:00:00Z', '{\"feature_version\":\"fv-1\",\"label_version\":\"lv-1\"}', repeat('d', 64), now(), 'x')")
    r = get(golden, "/metrics")
    assert r.status_code == 422 and rule_ids(r) == ["TRAINING_RUN_REQUIRED"]
    d = metrics(golden, training_run_id="tr-002", prediction_at=JAN, as_of="2026-05-01T00:00:00Z")["data"]["cutoff_sets"][JAN]
    assert d["population"]["scored"] == 0 and d["population"]["evaluated"] == 0 and d["population"]["unscored_excluded"] == 4         # another run has no predictions


def test_k_above_the_evaluated_population_is_refused_on_the_metrics_endpoint_but_not_for_an_empty_population(golden, conn):
    conn.execute("INSERT INTO intervention_scenarios (scenario_id, capacity, contact_cost, assumed_effect, margin_value) VALUES ('sc-big', 9, 1, 0.5, 10)")
    r = get(golden, "/metrics", training_run_id="tr-001", prediction_at=JAN, scenario_id="sc-big", as_of="2026-05-01T00:00:00Z")
    assert r.status_code == 422 and rule_ids(r) == ["CAPACITY_EXCEEDS_POPULATION"]
    ctx = r.json()["error"]["details"][0]["context"]
    assert ctx["offending"] == [{"item": "sc-big", "code": "CAPACITY_9_GT_4"}] and ctx["prediction_at"] == JAN
    ok = get(golden, "/metrics", training_run_id="tr-001", prediction_at=FEB, scenario_id="sc-big", as_of="2026-05-01T00:00:00Z")
    assert ok.status_code == 200                                                                                   # 0 evaluated rows: K metrics null, not a refusal
    s = ok.json()["data"]["cutoff_sets"][FEB]
    assert s["precision_at_k"] is None and s["recall_at_k"] is None and s["risk_lift_at_k"] is None and s["capacity"]["refusal"] is None and s["capacity"]["ok"] is False
    assert s["economics"] is None                                                                                   # scored 3 < K 9: no queue, no value
    exactly = conn.execute("INSERT INTO intervention_scenarios (scenario_id, capacity, contact_cost, assumed_effect, margin_value) VALUES ('sc-4', 4, 1, 0.5, 10)")
    r = get(golden, "/metrics", training_run_id="tr-001", prediction_at=JAN, scenario_id="sc-4", as_of="2026-05-01T00:00:00Z")
    assert r.status_code == 200 and r.json()["data"]["cutoff_sets"][JAN]["precision_at_k"]["k"] == 4


def test_metrics_warnings_disclose_censoring_and_hypothetical_economics(golden):
    r = get(golden, "/metrics", training_run_id="tr-001", scenario_id="sc-001", as_of="2026-05-01T00:00:00Z", prediction_at=f"{JAN},{FEB}").json()
    codes = {w["code"] for w in r["warnings"]}
    assert codes == {"LABELS_PENDING", "HYPOTHETICAL"} and r["meta"]["total_count"] == 2
    assert r["meta"]["applied_filters"]["prediction_at"] == [JAN, FEB] and r["meta"]["applied_filters"]["scenario_id"] == "sc-001"
    assert r["meta"]["contract_version"] == 1 and r["meta"]["dataset_version"].startswith("ds-")


# ---------------------------------------------------------------------------------------------------- evidence reconciliation
def test_metrics_reconcile_with_the_entity_reads_they_come_from(client, conn):
    load(conn, build_world())
    out = pipeline(client, command)
    assert all(r.status_code == 200 for r in out.values())
    pa = SETS["test"][0]
    s = metrics(client, training_run_id="tr-w", prediction_at=pa, as_of=READ_AS_OF)["data"]["cutoff_sets"][pa]
    cuts = [c["cutoff_id"] for c in get(client, "/data/prediction_cutoffs", limit=200, **{"from": pa, "to": "2025-10-02T00:00:00Z"}).json()["data"]]
    labels = {l["cutoff_id"]: l for l in get(client, "/data/labels", limit=200).json()["data"]}
    preds = {p["cutoff_id"]: p for p in get(client, "/data/predictions", limit=200, training_run_id="tr-w").json()["data"]}
    feats = {f["cutoff_id"] for f in get(client, "/data/feature_rows", limit=200).json()["data"]}
    assert s["population"]["cutoff_rows"] == len(cuts) == 28
    mature = [c for c in cuts if c in labels and labels[c]["mature"]]
    assert s["population"]["mature"] == len(mature) and s["churn_rate"]["churned"] == sum(1 for c in mature if labels[c]["churned"])
    assert s["population"]["scored"] == sum(1 for c in cuts if c in preds) and set(c for c in cuts if c in feats) == set(c for c in cuts if c in labels)
    ranking = s["ranking"]
    assert [r["probability"] for r in ranking] == sorted((preds[r["cutoff_id"]]["probability"] for r in ranking), reverse=True)
    assert [r["outcome"] for r in ranking] == [1 if labels[r["cutoff_id"]]["churned"] else 0 for r in ranking]
    assert get(client, "/data/predictions", training_run_id="tr-w").json()["meta"]["total_count"] == 43
    full = get(client, "/data/split_assignments", training_run_id="tr-w", status="retained").json()["meta"]["total_count"]
    assert full == 48 + 12 + 52
    run = get(client, "/data/training_runs").json()["data"][0]
    assert run["config_hash"] == preds[ranking[0]["cutoff_id"]]["config_hash"] and run["config"]["models"][2]["name"] == "logistic_regression"
    audit = get(client, "/data/audit_events", action="score-accounts").json()
    assert audit["meta"]["total_count"] == 2 and all(a["actor_role"] == "scientist" for a in audit["data"])


def test_the_logistic_model_beats_the_baselines_on_the_held_out_test_set_of_the_world(client, conn):
    """P10-DOMAIN-04 end to end: the same test rows scored by all three models; the final evaluation reads the test set once."""
    load(conn, build_world())
    out = pipeline(client, command)
    assert all(r.status_code == 200 for r in out.values())
    pa = SETS["test"][0]
    for model in ("random_baseline", "business_rule"):
        assert command(client, "score-accounts", {"training_run_id": "tr-w", "prediction_at": pa, "model": model}).status_code == 200
    got = {m: metrics(client, training_run_id="tr-w", prediction_at=pa, model=m, as_of=READ_AS_OF)["data"]["cutoff_sets"][pa]
           for m in ("random_baseline", "business_rule", "logistic_regression")}
    from fractions import Fraction
    lr = got["logistic_regression"]
    for base in ("random_baseline", "business_rule"):
        assert Fraction(lr["average_precision"]["value"]) > Fraction(got[base]["average_precision"]["value"]), base
        assert Fraction(lr["brier_score"]["value"]) < Fraction(got[base]["brier_score"]["value"]), base
    assert lr["population"]["evaluated"] == 28 and got["random_baseline"]["population"]["evaluated"] == 28
