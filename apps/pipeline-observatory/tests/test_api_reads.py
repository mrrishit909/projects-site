"""Reads: GET /data/{entity} (stable ordering, cursor, filters, half-open windows) and GET /metrics (window, cutoff, source, group_by)."""
import json

import pytest

from api.reads import ENTITIES
from support_db import (CUTOFF, client, command, conn, count, db_url, diff, get, golden_expected, golden_inputs, ingest, load, load_world, metrics, rule_ids)


@pytest.fixture
def gold(client, conn):
    load(conn, golden_inputs())
    return client


def no_floats(x):
    assert not isinstance(x, float), x
    if isinstance(x, dict):
        [no_floats(v) for v in x.values()]
    if isinstance(x, list):
        [no_floats(v) for v in x]


@pytest.mark.parametrize("entity", sorted(ENTITIES))
def test_every_entity_reads_with_the_envelope_and_no_float(gold, entity):
    r = get(gold, f"/data/{entity}", limit=5)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"data", "meta", "warnings"} and isinstance(body["data"], list) and body["warnings"] == []
    assert set(body["meta"]) == {"dataset_version", "code_sha", "contract_version", "generated_at", "applied_filters", "total_count", "next_cursor", "exclusions"}
    assert body["meta"]["contract_version"] == 1 and body["meta"]["generated_at"].endswith("Z") and body["meta"]["dataset_version"].startswith("ds-")
    no_floats(body)


def test_entities_read_the_loaded_golden_rows(gold):
    assert [r["source_id"] for r in get(gold, "/data/source_contracts").json()["data"]] == ["src-orders", "src-refunds"]
    assert get(gold, "/data/raw_records").json()["meta"]["total_count"] == 31 and get(gold, "/data/accepted_records").json()["meta"]["total_count"] == 9
    assert [r["publication_id"] for r in get(gold, "/data/publications").json()["data"]] == ["pub-001", "pub-003"]
    p = get(gold, "/data/publications", run_id="run-003").json()["data"][0]
    assert p["published_at"] == "2026-10-04T20:15:00Z" and p["watermark"] == "2026-10-04T11:00:00Z" and p["included_batch_ids"] == ["b-001", "b-002", "b-101"]
    assert get(gold, "/data/publication_pointer").json()["data"][0]["publication_id"] == "pub-003"
    assert get(gold, "/data/incidents").json()["data"][0]["recovery_run_id"] == "run-003"


def test_cursor_pagination_is_stable_with_no_duplicates_or_gaps(gold):
    seen, cursor, pages = [], None, 0
    while True:
        body = get(gold, "/data/raw_records", limit=7, cursor=cursor).json()
        seen += [r["raw_record_id"] for r in body["data"]]
        pages += 1
        assert body["meta"]["total_count"] == 31
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break
    assert pages == 5 and len(seen) == 31 and len(set(seen)) == 31 and seen == sorted(seen)
    ids, cursor = [], None                                                                   # composite keys page too (accepted_records: source_id, source_key)
    while True:
        body = get(gold, "/data/accepted_records", limit=4, cursor=cursor).json()
        ids += [(r["source_id"], r["source_key"]) for r in body["data"]]
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break
    assert len(ids) == 9 and ids == sorted(ids)


def test_pages_stay_stable_while_rows_are_added_behind_the_cursor(client, conn):
    load_world(conn)
    for n in range(1, 6):
        ingest(client, "src-orders", f"b-{n}", [{"payload": {"record_id": f"R-{n}", "quantity": 1, "unit_price": "1.00", "amount": "1.00", "event_ts": "2026-10-04T08:00:00Z"}}],
               cursor=f"c{n}", next_cursor=f"c{n + 1}", commit=False)
    first = get(client, "/data/ingestion_batches", limit=2).json()
    ingest(client, "src-orders", "b-0", [], cursor="c0", next_cursor="c1", commit=False)               # sorts BEFORE the cursor: never shown twice, never shifts the page
    rest = get(client, "/data/ingestion_batches", limit=10, cursor=first["meta"]["next_cursor"]).json()["data"]
    assert [b["batch_id"] for b in first["data"]] == ["b-1", "b-2"] and [b["batch_id"] for b in rest] == ["b-3", "b-4", "b-5"]


def test_filters_windows_and_validation(gold):
    assert [b["batch_id"] for b in get(gold, "/data/ingestion_batches", source_id="src-orders", status="committed").json()["data"]] == ["b-001", "b-002"]
    assert get(gold, "/data/ingestion_batches", status="nope").json()["data"] == []
    # half-open [from, to): b-001 starts at 10:00:00 exactly
    assert [b["batch_id"] for b in get(gold, "/data/ingestion_batches", **{"from": "2026-10-04T10:00:00Z", "to": "2026-10-04T11:00:00Z"}).json()["data"]] == ["b-001"]
    assert get(gold, "/data/ingestion_batches", **{"from": "2026-10-04T10:00:01Z", "to": "2026-10-04T11:00:00Z"}).json()["data"] == []
    assert [b["batch_id"] for b in get(gold, "/data/ingestion_batches", **{"to": "2026-10-04T11:00:01Z"}).json()["data"]] == ["b-001", "b-101"]
    r = get(gold, "/data/ingestion_batches", **{"from": "2026-10-04T11:00:00Z", "to": "2026-10-04T11:00:00Z"})
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_WINDOW"]
    assert rule_ids(get(gold, "/data/ingestion_batches", **{"from": "yesterday"})) == ["INVALID_FILTER"]
    assert rule_ids(get(gold, "/data/source_contracts", **{"from": "2026-10-04"})) == ["FILTER_NOT_SUPPORTED"]
    assert rule_ids(get(gold, "/data/raw_records", payload_hash="x")) == ["INVALID_FILTER"]
    assert rule_ids(get(gold, "/data/raw_records", cursor="not-a-cursor")) == ["INVALID_CURSOR"]
    assert get(gold, "/data/raw_records", limit=0).status_code == 422 and get(gold, "/data/raw_records", limit=201).status_code == 422
    r = get(gold, "/data/nothing")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND" and rule_ids(r) == ["ENTITY_UNKNOWN"]


def test_reads_never_need_an_actor_and_the_error_envelope_has_a_request_id(gold):
    r = get(gold, "/data/nothing")
    assert r.status_code == 404 and r.json()["request_id"].startswith("req-") and set(r.json()) == {"error", "request_id"}


def test_filter_values_are_parameters_not_sql(gold):
    r = get(gold, "/data/raw_records", source_key="x'; DROP TABLE raw_records; --")
    assert r.status_code == 200 and r.json()["data"] == []
    assert get(gold, "/data/raw_records").json()["meta"]["total_count"] == 31


# ------------------------------------------------------------------------------------------------------------ /metrics
def test_metrics_default_equals_the_reference_when_the_cutoff_is_the_fixtures(gold):
    body = metrics(gold, cutoff=CUTOFF)
    assert diff(body["data"]["metrics"], golden_expected()["metrics"]) == []
    assert body["meta"]["applied_filters"] == {"from": None, "to": None, "cutoff": CUTOFF, "source_id": None, "group_by": "none"}
    assert body["meta"]["exclusions"] == {"rejected_records": 0} and body["warnings"][0]["code"] == "PROCESSING_RATE_OBSERVED"
    no_floats(body)


def test_metrics_cutoff_is_the_instant_freshness_is_measured_at_and_drops_later_facts(gold):
    m = metrics(gold, cutoff="2026-10-04T12:00:00Z")["data"]["metrics"]
    assert m["freshness"]["src-orders"]["freshness_seconds"] == 9000 and m["freshness"]["src-orders"]["ingestion_age_seconds"] == 6900          # 12:00 - 09:30 and 12:00 - 10:05
    assert m["freshness"]["src-orders"]["latest_accepted_event_at"] == "2026-10-04T09:30:00Z" and m["freshness"]["src-orders"]["last_successful_ingestion_at"] == "2026-10-04T10:05:00Z"
    assert sorted(m["ingestion"]["sources"]["src-orders"]["batches"]) == ["b-001"]                    # b-002 (12:00) and b-003 (18:00) are not known yet
    assert m["publications"]["current_publication_id"] == "pub-001" and sorted(m["runs"]["runs"]) == ["run-001"] and m["incidents"]["total"] == 0
    assert m["late_events"]["count"] == 1 and m["late_events"]["lost"] == 1       # REF-2001 arrived behind pub-001's watermark; pub-003 (20:15) is not known yet: reported, never hidden


def test_metrics_window_is_half_open_on_each_entitys_primary_instant(gold):
    inside = metrics(gold, **{"from": "2026-10-04T10:00:00Z", "to": "2026-10-04T10:10:00Z", "cutoff": CUTOFF})["data"]["metrics"]
    assert sorted(inside["ingestion"]["sources"]["src-orders"]["batches"]) == ["b-001"] and sorted(inside["runs"]["runs"]) == []             # run-001 starts at 10:10:00 = excluded
    edge = metrics(gold, **{"from": "2026-10-04T10:10:00Z", "to": "2026-10-04T10:10:01Z", "cutoff": CUTOFF})["data"]["metrics"]
    assert sorted(edge["runs"]["runs"]) == ["run-001"] and edge["ingestion"]["overall"]["received"] == 0
    r = get(gold, "/metrics", **{"from": "2026-10-05", "to": "2026-10-04"})
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_WINDOW"]


def test_metrics_source_filter_and_group_by_source(gold):
    one = metrics(gold, source_id="src-refunds", cutoff=CUTOFF)["data"]
    assert sorted(one["metrics"]["ingestion"]["sources"]) == ["src-refunds"] and one["metrics"]["ingestion"]["overall"]["received"] == 1
    assert set(one["metrics"]["completeness"]) == {"src-refunds"} and one["source_id"] == "src-refunds"
    grouped = metrics(gold, group_by="source", cutoff=CUTOFF)["data"]
    assert sorted(grouped["groups"]) == ["src-orders", "src-refunds"]
    assert grouped["groups"]["src-orders"]["ingestion"]["accepted_unique"] == 8 and grouped["groups"]["src-orders"]["freshness"]["freshness_seconds"] == 52200
    assert grouped["groups"]["src-refunds"]["completeness"]["2026-10-04"]["value"] == "1.000000"
    assert get(gold, "/metrics", source_id="src-nope").status_code == 404
    r = get(gold, "/metrics", group_by="owner")
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_GROUP_BY"]


def test_metrics_on_an_empty_world_are_null_not_zero(client, conn):
    load_world(conn)
    d = metrics(client, cutoff=CUTOFF)["data"]
    assert d["empty_population"] is True and d["metrics"]["ingestion"]["overall"]["rejection_rate"] is None and d["metrics"]["completeness"]["src-orders"]["2026-10-04"]["value"] == "0.000000"
    assert d["metrics"]["publications"]["current_publication_id"] is None and d["metrics"]["incidents"]["mean_recovery_minutes"] is None and d["metrics"]["freshness"]["src-orders"]["freshness_seconds"] is None
    assert d["metrics"]["backfills"]["overall"]["coverage"] is None and d["metrics"]["processing_rate"]["records_per_second"] is None


def test_metrics_report_rejected_import_rows_and_never_hide_them(client, conn):
    load(conn, golden_inputs("variant-rejected"))
    body = metrics(client, cutoff=CUTOFF)
    assert body["meta"]["exclusions"] == {"rejected_records": 10} and len(body["data"]["ingest"]["rejected_records"]) == 10
    assert body["data"]["metrics"]["backfills"]["refused"] == ["bf-002"]
    assert get(client, "/data/rejected_records", entity="backfill_requests").json()["data"][0]["reason_code"] == "BACKFILL_OVERLAP"


def test_the_metrics_a_reader_sees_after_commands_are_the_domains_numbers(client, conn):
    from support_db import payloads
    load_world(conn)
    ingest(client, "src-orders", "b-001", payloads(golden_inputs(), "b-001"))
    ingest(client, "src-orders", "b-002", payloads(golden_inputs(), "b-002"))
    s = metrics(client)["data"]["metrics"]["ingestion"]["sources"]["src-orders"]          # the default cutoff is the server's now
    assert (s["received"], s["accepted_unique"], s["duplicate"], s["quarantined"], s["rejection_rate"], s["duplicate_rate"]) == (20, 8, 10, 2, "0.100000", "0.500000")
