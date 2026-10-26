"""Reads: GET /data/{entity} (ordering, cursor, filters, half-open windows), GET /metrics (window, cutoff, experiment_version_id,
group_by, the per-cohort retention grid) and the run and audit reads. Reads need no actor."""
from support_db import (Lab, World, client, conn, count, db_url, get, golden_expected, golden_inputs, iso, load, rule_ids,  # noqa: F401
                        small_experiment, ts)

from datetime import timedelta


def test_a_read_needs_no_actor_and_carries_the_meta_block(client, conn):
    load(conn, golden_inputs())
    r = get(client, "/data/accounts", limit=5)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"data", "meta", "warnings"} and len(body["data"]) == 5
    m = body["meta"]
    assert {"dataset_version", "code_sha", "contract_version", "generated_at", "applied_filters", "total_count", "next_cursor", "exclusions"} <= set(m)
    assert m["total_count"] == len(golden_inputs()["accounts"]) and m["next_cursor"] and m["generated_at"] == "2026-10-26T22:00:00Z"


def test_pages_are_stable_with_no_duplicates_or_gaps(client, conn):
    load(conn, golden_inputs())
    want = sorted(e["event_id"] for e in golden_inputs()["events"])
    got, cursor = [], None
    while True:
        r = get(client, "/data/events", limit=97, cursor=cursor).json()
        got += [e["event_id"] for e in r["data"]]
        cursor = r["meta"]["next_cursor"]
        if not cursor:
            break
    assert got == want and len(set(got)) == len(got)


def test_filters_windows_and_refusals(client, conn):
    load(conn, golden_inputs())
    ex = golden_inputs()["events"]
    r = get(client, "/data/events", event_name="activated", limit=200).json()
    assert r["meta"]["total_count"] == sum(e["event_name"] == "activated" for e in ex)
    lo, hi = "2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z"
    r = get(client, "/data/events", **{"from": lo, "to": hi, "limit": 200}).json()
    assert r["meta"]["total_count"] == sum(lo <= e["event_at"] < hi for e in ex)           # [from, to): the upper bound is excluded
    assert all(lo <= e["event_at"] < hi for e in r["data"])
    assert get(client, "/data/events", limit=5, colour="red").status_code == 422
    assert rule_ids(get(client, "/data/events", colour="red")) == ["INVALID_FILTER"]
    assert rule_ids(get(client, "/data/events", **{"from": hi, "to": lo})) == ["INVALID_WINDOW"]
    assert rule_ids(get(client, "/data/events", cursor="nonsense")) == ["INVALID_CURSOR"]
    assert get(client, "/data/nothing").status_code == 404
    assert get(client, "/data/accounts", internal="maybe").status_code == 422


def test_run_and_audit_reads(client, conn):
    L = Lab(client, conn, world=small_experiment((100, 20), (100, 40)))
    aid, rid = L.final()
    assert L.decide(aid, rid, "ship").status_code == 200
    run = get(client, f"/data/analysis_runs/{aid}").json()["data"]
    assert run["analysis_id"] == aid and run["result"]["srm"]["verdict"] == "OK"
    assert get(client, "/data/analysis_runs/an-zzz").status_code == 404
    a = get(client, "/data/experiment_versions/xv-001/audit").json()["data"]
    assert [x["analysis_id"] for x in a["runs"] if x["created_by"] != "seed"] == [aid]
    assert len(a["decisions"]) == 1 and len(a["guardrail_reviews"]) == 1
    assert {x["action"] for x in a["audit"]} >= {"analyze-experiment", "review-guardrails", "record-decision"}
    assert {x["variant"]: x["units"] for x in a["assignments_by_variant"]} == {"control": 100, "treatment": 100}
    assert get(client, "/data/experiment_versions/xv-zzz/audit").status_code == 404


def test_metrics_at_the_cutoff_reproduce_expected_json(client, conn):
    inputs, exp = golden_inputs(), golden_expected()
    load(conn, inputs)
    r = get(client, "/metrics", cutoff=inputs["cutoff"], experiment_version_id="xv-001")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["metrics"] == exp["metrics"] and d["tracking_quality"] == exp["tracking_quality"] and d["identity"] == exp["identity"]
    assert r.json()["meta"]["applied_filters"]["experiment_version_id"] == "xv-001"


def test_the_cutoff_decides_which_events_count(client, conn):
    load(conn, golden_inputs())
    early = get(client, "/metrics", cutoff="2026-10-06T00:00:00Z", experiment_version_id="xv-001").json()
    late = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z", experiment_version_id="xv-001").json()
    assert early["data"]["tracking_quality"]["received_after_cutoff"] > late["data"]["tracking_quality"]["received_after_cutoff"]
    assert early["data"]["tracking_quality"]["analysed"] < late["data"]["tracking_quality"]["analysed"]
    assert early["data"]["metrics"] != late["data"]["metrics"]


def test_from_and_to_replace_the_windows_half_open(client, conn):
    inputs = golden_inputs()
    load(conn, inputs)
    base = get(client, "/metrics", cutoff=inputs["cutoff"]).json()["data"]
    narrow = get(client, "/metrics", cutoff=inputs["cutoff"], **{"from": "2026-10-05T00:00:00Z", "to": "2026-10-06T00:00:00Z"}).json()
    assert narrow["data"]["windows"] != base["windows"] and narrow["meta"]["applied_filters"]["to"] == "2026-10-06T00:00:00Z"
    assert narrow["data"]["metrics"]["signup_conversion"] != base["metrics"]["signup_conversion"]
    bad = get(client, "/metrics", **{"from": "2026-10-06T00:00:00Z", "to": "2026-10-06T00:00:00Z"})
    assert bad.status_code == 422 and rule_ids(bad) == ["INVALID_WINDOW"]


def test_group_by_variant_plan_timezone_segment_and_refusals(client, conn):
    inputs = golden_inputs()
    load(conn, inputs)
    kw = dict(cutoff=inputs["cutoff"], experiment_version_id="xv-001")
    for by, key in (("plan", "plan"), ("timezone", "timezone"), ("segment", "segment")):
        d = get(client, "/metrics", group_by=by, **kw).json()
        want = {a[key] for a in inputs["accounts"] if not a["internal"]}
        assert set(d["data"]["groups"]) <= {a[key] for a in inputs["accounts"]} and want <= set(d["data"]["groups"]), by
        sa = d["data"]["segment_analysis"]
        assert sa["label"] == "exploratory" and sa["decision_basis"] is False and 1 <= sa["segments_tested"] <= len(sa["segments"])   # a segment is tested only when it has both arms
        assert "EXPLORATORY_SEGMENT_ANALYSIS" in {w["code"] for w in d["warnings"]}
    v = get(client, "/metrics", group_by="variant", **kw).json()
    assert set(v["data"]["groups"]) == {"control", "treatment"} and "segment_analysis" not in v["data"]
    assert {g["accounts"] for g in v["data"]["groups"].values()} == {100}
    assert get(client, "/metrics", group_by="colour", **kw).status_code == 422
    assert rule_ids(get(client, "/metrics", group_by="colour")) == ["INVALID_GROUP_BY"]
    assert get(client, "/metrics", experiment_version_id="xv-zzz").status_code == 404


def test_the_per_cohort_retention_grid(client, conn):
    w = World()
    for i, (signup, days) in enumerate([("2026-09-14T09:00:00Z", (7,)), ("2026-09-14T10:00:00Z", (7, 30)), ("2026-09-15T09:00:00Z", (9,)),
                                        ("2026-09-15T10:00:00Z", ())]):
        aid = w.account(f"acc-g{i}")
        w.signup(aid, signup)
        for dd in days:
            w.session(aid, iso(ts(signup) + timedelta(days=dd)))
    Lab(client, conn, world=w)
    grid = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z").json()["data"]["retention_grid"]
    text = str(grid)
    assert "2026-09-14" in text and "2026-09-15" in text
    by_date = {r["cohort"]: r for r in grid["rows"]}
    assert by_date["2026-09-14"]["accounts"] == 2 and by_date["2026-09-15"]["accounts"] == 2
    c14, c15 = by_date["2026-09-14"]["cells"], by_date["2026-09-15"]["cells"]
    assert (c14["day7"]["retained"], c14["day7"]["rate"], c14["week4"]["retained"]) == (2, "1.000000", 1)
    assert (c15["day7"]["retained"], c15["on_or_after_day7"]["retained"]) == (0, 1)             # day 9 is not day 7, but is on or after it


def test_an_empty_database_gives_an_honest_empty_population(client, conn):
    d = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z")
    assert d.status_code == 200 and d.json()["data"]["empty_population"] is True
