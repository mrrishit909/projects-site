"""Adversarial cases P06-TEST-01..12 end to end (API over PostgreSQL), and the concurrency, stale-dataset and idempotency-reuse
cases. Domain-level versions of the same rules are in test_rules.py; here the refusal, its status and its envelope are the point."""
import json
import threading

from support_db import (ADMIN, ANALYST, EXPERIMENTER, Lab, World, client, command, conn, count, db_url, get, iso, rule_ids,  # noqa: F401
                        set_clock, small_experiment, ts)

from datetime import timedelta


def lab(client, conn, **kw) -> Lab:
    return Lab(client, conn, **kw)


def runs(conn) -> int:
    return count(conn, "analysis_runs", "created_by <> 'seed'")


def test_01_a_user_level_analysis_of_an_account_randomised_experiment_is_refused(client, conn):
    L = lab(client, conn)
    for unit in ("user", "session", "event"):
        r = L.analyze("2026-10-26T00:00:00Z", analysis_unit=unit)
        assert r.status_code == 422 and rule_ids(r) == ["UNIT_MISMATCH"], unit
        assert r.json()["error"]["details"][0]["context"] == {"unit_type": "account"}
    assert runs(conn) == 0                                                  # a refused analysis is not a run
    assert L.analyze("2026-10-26T00:00:00Z", analysis_unit="account").status_code == 200


def test_02_a_treatment_dependent_exclusion_is_refused(client, conn):
    L = lab(client, conn)
    for field in ("exposed", "activated", "variant", "converted"):
        r = L.analyze("2026-10-26T00:00:00Z", exclusions=[{"field": field, "values": ["false"]}])
        assert r.status_code == 422 and rule_ids(r) == ["TREATMENT_DEPENDENT_EXCLUSION"], field
    assert runs(conn) == 0
    assert L.analyze("2026-10-26T00:00:00Z", analysis="exposed_only").status_code == 422          # nor is a per-protocol primary analysis


def test_03_an_interim_result_presented_as_final_cannot_support_ship(client, conn):
    L = lab(client, conn, world=small_experiment((100, 20), (100, 60)))
    a = L.analyze("2026-10-10T00:00:00Z")
    assert a.json()["status"] == "interim" and a.json()["result"]["primary"]["conclusive"] is False
    aid = a.json()["result"]["analysis_id"]
    rv = L.review(aid).json()["result"]["review_id"]
    r = L.decide(aid, rv, "ship")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INTERIM_RUN_CANNOT_SHIP" and count(conn, "decisions") == 0
    final, frv = L.final()
    assert L.decide(final, frv, "ship").status_code == 200                                    # the same data at the planned end may ship


def test_04_an_immature_cohort_is_excluded_and_counted(client, conn):
    w = small_experiment((20, 4), (20, 10))
    w.arm("control", 6, 6, prefix="young", start="2026-10-24T00:00:00Z")                       # signed up two days before the cutoff
    L = lab(client, conn, world=w)
    res = L.analyze("2026-10-26T00:00:00Z").json()["result"]
    assert res["assigned_units"] == 46 and res["mature_units"] == 40 and res["immature_or_unobserved_excluded"] == 6
    assert res["primary"]["variants"]["control"]["conversion"] == "0.200000"                   # the six early activators do not inflate it
    c = L.post("check-maturity", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}, ANALYST).json()
    assert c["result"]["immature"] == 6 and "IMMATURE_EXCLUDED" in {x["code"] for x in c["warnings"]}


def test_05_a_duplicate_activation_is_not_counted_twice(client, conn):
    w = small_experiment((20, 4), (20, 10))
    L = lab(client, conn, world=w)
    before = L.analyze("2026-10-26T00:00:00Z").json()["result"]["primary"]["variants"]["control"]["activated"]
    # the same activation re-sent under a new id, and a second activation of an already activated account
    r = L.post("validate-tracking", {"events": [
        {"event_id": "dup-a", "user_id": "u-acc-c-001", "anonymous_id": None, "event_name": "activated", "event_at": "2026-10-01T11:00:00Z"},
        {"event_id": "dup-b", "user_id": "u-acc-c-001", "anonymous_id": None, "event_name": "activated", "event_at": "2026-10-03T11:00:00Z"}]}, ANALYST)
    assert r.status_code == 200
    set_clock("2026-10-28T12:00:00Z")                                                       # a cutoff cannot be after the server clock (D-10)
    after = L.analyze("2026-10-28T00:00:00Z").json()["result"]
    assert before == 4 and after["primary"]["variants"]["control"]["activated"] == 4          # an account activates once


def test_06_a_late_event_changes_only_a_later_run_and_the_revision_is_disclosed(client, conn):
    L = lab(client, conn, world=small_experiment((20, 4), (20, 10)))
    first = L.analyze("2026-10-26T00:00:00Z").json()["result"]
    L.post("validate-tracking", {"events": [{"event_id": "late-9", "user_id": "u-acc-c-015", "anonymous_id": None, "event_name": "activated",
                                             "event_at": "2026-10-02T00:00:00Z"}]}, ANALYST)
    same = L.analyze("2026-10-26T00:00:00Z").json()["result"]
    assert same["primary"] == first["primary"] and same["tracking_quality"]["received_after_cutoff"] == 1
    set_clock("2026-10-27T12:00:00Z")
    later = L.analyze("2026-10-27T00:00:00Z")
    assert later.json()["result"]["primary"]["variants"]["control"]["activated"] == 5
    assert later.json()["result"]["revision"]["late_events"]["count"] == 1 and "REVISION_DISCLOSED" in {x["code"] for x in later.json()["warnings"]}
    assert get(client, f"/data/analysis_runs/{first['analysis_id']}").json()["data"]["result"]["primary"] == first["primary"]


def test_07_an_identity_link_is_not_applied_backward(client, conn):
    L = lab(client, conn, facts=False)
    L.post("validate-tracking", {"events": [
        {"event_id": "v-1", "user_id": None, "anonymous_id": "anon-x", "event_name": "visit", "event_at": "2026-10-05T10:00:00Z"},
        {"event_id": "v-2", "user_id": None, "anonymous_id": "anon-x", "event_name": "visit", "event_at": "2026-10-06T10:00:00Z"}]}, ANALYST)
    r = L.post("resolve-identity", {"anonymous_id": "anon-x", "user_id": "u-acc-c-001", "linked_at": "2026-10-05T18:00:00Z", "rule_version": "v1"}, ANALYST)
    assert r.status_code == 200
    res = r.json()["result"]
    text = json.dumps(res)
    assert "attributed" in text and "anonymous" in text
    ev = {e["event_id"]: e for e in get(client, "/data/events", anonymous_id="anon-x").json()["data"]}
    assert ev["v-1"]["user_id"] is None and ev["v-2"]["user_id"] is None                        # the log is never rewritten
    set_clock("2026-10-27T12:00:00Z")
    m = get(client, "/metrics", cutoff="2026-10-27T00:00:00Z").json()["data"]["identity"]
    assert (m["attributed_by_link"], m["remain_anonymous"]) == (1, 1)                           # only the event after linked_at is attributed


def test_08_a_sample_ratio_mismatch_blocks_ship(client, conn):
    L = lab(client, conn, world=small_experiment((130, 20), (70, 40)))
    res = L.analyze("2026-10-26T00:00:00Z").json()["result"]
    assert res["srm"]["verdict"] == "MISMATCH" and res["decision_support"]["ship_allowed"] is False and res["decision_support"]["lift_interpretable"] is False
    aid, rid = L.final()
    r = L.decide(aid, rid, "ship")
    assert r.status_code == 409 and r.json()["error"]["code"] == "SRM_MISMATCH_BLOCKS_DECISION" and count(conn, "decisions") == 0


def test_09_segment_cherry_picking_is_labelled_exploratory_with_the_multiplicity(client, conn):
    w = small_experiment((40, 8), (40, 18))
    for i, a in enumerate(w.d["accounts"]):
        a["segment"] = ["smb", "mid", "enterprise", "startup"][i % 4]
    L = lab(client, conn, world=w)
    d = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z", experiment_version_id="xv-001", group_by="segment").json()
    seg = d["data"]["segment_analysis"]
    assert seg["label"] == "exploratory" and seg["decision_basis"] is False and seg["segments_tested"] == 4
    assert seg["bonferroni_threshold"] == "0.012500" and all(s["label"] == "exploratory" and s["decision_basis"] is False for s in seg["segments"])
    assert "EXPLORATORY_SEGMENT_ANALYSIS" in {x["code"] for x in d["warnings"]}
    aid, rid = L.final()
    r = L.decide(aid, rid, "ship", basis="segment")
    assert r.status_code == 422 and rule_ids(r) == ["SEGMENT_NOT_A_DECISION_BASIS"] and count(conn, "decisions") == 0


def test_10_a_zero_control_rate_gives_a_null_relative_lift_not_zero_or_infinity(client, conn):
    L = lab(client, conn, world=small_experiment((20, 0), (20, 8)))
    p = L.analyze("2026-10-26T00:00:00Z").json()["result"]["primary"]
    assert p["variants"]["control"]["conversion"] == "0.000000" and p["relative_lift"] is None and p["absolute_lift_pp"] == "40.00"


def test_11_an_exposure_before_its_assignment_is_rejected_and_the_raw_row_kept(client, conn):
    L = lab(client, conn, facts=False)
    a = L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-c-001", "variant": "control", "assigned_at": "2026-10-01T09:01:00Z",
                                     "backfill": True}, ADMIN)
    asid = a.json()["result"]["assignment_id"]
    r = L.post("record-exposure", {"assignment_id": asid, "exposed_at": "2026-10-01T09:00:59Z", "surface": "onboarding_checklist", "backfill": True}, ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["EXPOSURE_BEFORE_ASSIGNMENT"] and count(conn, "exposures") == 0
    assert count(conn, "rejected_records", "reason_code = 'EXPOSURE_BEFORE_ASSIGNMENT'") == 1
    ok = L.post("record-exposure", {"assignment_id": asid, "exposed_at": "2026-10-01T09:01:00Z", "surface": "onboarding_checklist", "backfill": True}, ADMIN)
    assert ok.status_code == 200                                                              # equal instants satisfy exposed_at >= assigned_at


def test_12_exact_day_7_retention_and_rolling_on_or_after_are_separate_figures(client, conn):
    w = World()
    for i, day in enumerate((7, 9, None)):
        aid = w.account(f"acc-r{i}", tz="UTC", created="2026-09-01T00:00:00Z")
        w.signup(aid, "2026-09-14T09:00:00Z")
        if day:
            w.session(aid, iso(ts("2026-09-14T09:00:00Z") + timedelta(days=day)))
    lab(client, conn, world=w)
    r = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z").json()["data"]["metrics"]["retention"]
    d7, on_or_after = r["day7"], r["on_or_after_day7"]
    assert d7["retained"] == 1 and on_or_after["retained"] == 2 and d7["mature_accounts"] == 3 == on_or_after["mature_accounts"]
    assert (d7["rate"], on_or_after["rate"]) == ("0.333333", "0.666667")


def test_13_a_three_variant_plan_is_refused_so_the_sample_ratio_stays_a_one_degree_test(client, conn):
    """D-10 (R6-02): the chi-square p-value is df = 1; a plan that names a third arm is 422 VARIANTS_NOT_TWO and nothing is written."""
    from support_db import PLAN_BODY, plan_input
    L = lab(client, conn, plan=False, facts=False)
    r = L.post("freeze-analysis-plan", {**plan_input(PLAN_BODY), "allocation": {"control": "0.500000", "treatment": "0.250000", "holdout": "0.250000"}})
    assert r.status_code == 422 and rule_ids(r) == ["VARIANTS_NOT_TWO"] and count(conn, "analysis_plans") == 0
    assert L.post("freeze-analysis-plan", plan_input(PLAN_BODY)).status_code == 200


def test_14_a_run_cannot_be_dated_after_the_clock_and_a_cutoff_in_the_future_writes_nothing(client, conn):
    """D-10 (R6-04): 422 CUTOFF_IN_FUTURE for C07, C08 and GET /metrics; the interim label would otherwise be wrong the other way round."""
    L = lab(client, conn)
    before = (runs(conn), count(conn, "metric_observations"), count(conn, "audit_events"))
    assert rule_ids(L.analyze("2026-11-15T00:00:00Z")) == ["CUTOFF_IN_FUTURE"]                    # planned_end 2026-10-15: not a "final" run of the future
    assert rule_ids(L.post("check-maturity", {"experiment_version_id": "xv-001", "cutoff": "2026-11-15T00:00:00Z"}, ANALYST)) == ["CUTOFF_IN_FUTURE"]
    assert get(client, "/metrics", cutoff="2026-11-15T00:00:00Z").status_code == 422
    assert (runs(conn), count(conn, "metric_observations"), count(conn, "audit_events")) == before


# ---------------------------------------------------------------------------------------------------- concurrency
def _race(fn, n=2):
    """Run ``fn(i)`` in ``n`` threads released together; return the results in thread order."""
    barrier, out = threading.Barrier(n), [None] * n

    def run(i):
        barrier.wait()
        out[i] = fn(i)
    ts_ = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts_]
    [t.join() for t in ts_]
    return out


def _client():
    from fastapi.testclient import TestClient
    from api.app import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


def test_two_threads_assigning_one_unit_leave_one_assignment(client, conn):
    lab(client, conn, facts=False)
    for unit, variants in (("acc-c-001", ("control", "control")), ("acc-c-003", ("control", "treatment"))):      # assignments are append-only: one unit per case
        out = _race(lambda i: command(_client(), "assign-experiment", {"experiment_version_id": "xv-001", "unit_id": unit, "variant": variants[i]},
                                      key=f"race-{unit}-{i}"))
        assert count(conn, "assignments", f"unit_id = '{unit}'") == 1, variants
        codes = sorted(r.status_code for r in out)
        assert codes == ([200, 200] if variants[0] == variants[1] else [200, 409]), (variants, [r.text for r in out])
        if variants[0] != variants[1]:
            assert {r.json().get("error", {}).get("code") for r in out} == {None, "ASSIGNMENT_CONFLICT"}


def test_two_concurrent_decisions_on_one_run_leave_one_decision(client, conn):
    L = lab(client, conn, world=small_experiment((100, 20), (100, 40)))
    aid, rid = L.final()
    out = _race(lambda i: command(_client(), "record-decision", {"experiment_version_id": "xv-001", "analysis_id": aid, "review_id": rid,
                                                                 "decision": ("ship", "stop")[i], "rationale": "race"}, key=f"dec-{i}"))
    assert sorted(r.status_code for r in out) == [200, 409], [r.text for r in out]
    assert count(conn, "decisions") == 1 and count(conn, "audit_events", "action = 'record-decision'") == 1
    assert [r.json()["error"]["code"] for r in out if r.status_code == 409] == ["DECISION_ALREADY_RECORDED"]


def test_the_same_idempotency_key_raced_executes_once(client, conn):
    L = lab(client, conn, facts=False)
    body = {"experiment_version_id": "xv-001", "unit_id": "acc-c-002", "variant": "control"}
    out = _race(lambda i: command(_client(), "assign-experiment", body, key="same-key"), 3)
    assert {r.status_code for r in out} == {200} and count(conn, "assignments") == 1 and count(conn, "command_results", "idempotency_key = 'same-key'") == 1
    assert len({r.json()["command_id"] for r in out}) == 1


# ---------------------------------------------------------------------------------------------------- stale dataset and key reuse
def test_a_stale_dataset_version_is_409_and_nothing_is_written(client, conn):
    L = lab(client, conn)
    r = L.post("analyze-experiment", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}, ANALYST, dataset_version="ds-old")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_DATASET_VERSION" and runs(conn) == 0


def test_reusing_an_idempotency_key_with_a_different_payload_or_actor_is_409(client, conn):
    L = lab(client, conn)
    base = {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}
    first = L.post("analyze-experiment", base, ANALYST, key="reuse-1")
    assert first.status_code == 200
    changed = L.post("analyze-experiment", {**base, "cutoff": "2026-10-27T00:00:00Z"}, ANALYST, key="reuse-1")
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    other = L.post("analyze-experiment", base, {"X-Actor-Id": "usr-other", "X-Actor-Role": "analyst"}, key="reuse-1")
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    role = L.post("analyze-experiment", base, {"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "admin"}, key="reuse-1")
    assert role.status_code == 409
    replay = L.post("analyze-experiment", base, ANALYST, key="reuse-1")
    assert replay.status_code == 200 and replay.json()["command_id"] == first.json()["command_id"] and runs(conn) == 1
