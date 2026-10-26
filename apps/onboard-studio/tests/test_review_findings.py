"""Regression tests for the master-18 reviewer findings Q-01..Q-06 (docs/contracts.md D-06..D-09).

Each test is named after its finding. Q-07 (sub-millisecond instants) is a documented limitation (D-01).
"""
import concurrent.futures as cf
import copy
import threading

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import commands
from api.app import PREFIX, create_app
from data import seed
from onboard_studio import run_pipeline
from onboard_studio.metrics import FLAG_SLA_UNEVALUATED
from onboard_studio.timeutil import parse_ts

from support_db import (ADMIN, OPS, REVIEWER, client, command, conn, count, db_url, golden_inputs, open_case,  # noqa: F401
                        rule_ids, seeded, step_id)

R = "customer_info_requested"
HOURS = ["calendar_cycle_time_hours", "business_cycle_time_hours", "paused_time_hours",
         "paused_business_overlap_hours", "active_elapsed_hours"]


@pytest.fixture
def api(client, seeded):
    return client


def at(hm: str, day: str = "2026-03-10") -> str:
    return f"{day}T{hm}:00Z"


def drive_until_completable(api, cid: str, approvals_at: tuple[str, str] = ("09:20", "09:40"),
                            unlock_at: str = "09:25", submit2_at: str = "09:30") -> None:
    """open 09:00 -> both steps approved, identity_proof accepted; the case is ready to complete."""
    assert open_case(api, cid, at("09:00")).status_code == 200
    s1, s2 = step_id(cid, "sd-001"), step_id(cid, "sd-002")
    for name, body, headers in [
        ("submit-document", {"case_id": cid, "document_type": "identity_proof", "step_instance_id": s1,
                             "occurred_at": at("09:05")}, OPS),
        ("accept-document", {"case_id": cid, "document_type": "identity_proof", "occurred_at": at("09:10")}, REVIEWER),
        ("approve-step", {"step_instance_id": s1, "expected_version": 1, "occurred_at": at(approvals_at[0])}, OPS),
        ("unlock-dependent-step", {"step_instance_id": s2, "occurred_at": at(unlock_at)}, OPS),
        ("submit-document", {"case_id": cid, "document_type": "approval_form", "step_instance_id": s2,
                             "occurred_at": at(submit2_at)}, OPS),
        ("approve-step", {"step_instance_id": s2, "expected_version": 1, "occurred_at": at(approvals_at[1])}, REVIEWER),
    ]:
        r = command(api, name, body, headers=headers)
        assert r.status_code == 200, (name, r.text)


# --- Q-01 -------------------------------------------------------------------------------------------------

def test_q01_a2_sequence_complete_earlier_than_recorded_work_is_refused(api, conn):
    """The reviewer's A2: approvals at 15:00/15:20, an open pause starting 03-12, completion at 09:30 on 03-10."""
    drive_until_completable(api, "c2", approvals_at=("15:00", "15:20"), unlock_at="15:05", submit2_at="15:10")
    r = command(api, "pause-sla", {"case_id": "c2", "reason_code": R, "starts_at": at("09:00", "2026-03-12"),
                                   "occurred_at": at("15:25")})
    assert r.status_code == 200
    early = command(api, "complete-case", {"case_id": "c2", "occurred_at": at("09:30")}, headers=REVIEWER)
    assert early.status_code == 422 and rule_ids(early) == ["COMPLETION_BEFORE_RECORDED_WORK"]      # was 200
    ctx = early.json()["error"]["details"][0]["context"]
    assert ctx["latest_recorded_at"] == "2026-03-12T09:00:00Z"
    row = conn.execute("SELECT status, completed_at FROM cases WHERE case_id = 'c2'").fetchone()
    assert row == {"status": "open", "completed_at": None}
    assert conn.execute("SELECT ends_at FROM waiting_intervals WHERE case_id = 'c2'").fetchone()["ends_at"] is None
    # at the latest recorded instant exactly: allowed (>=), and the open wait is closed at the completion instant (D-07)
    ok = command(api, "complete-case", {"case_id": "c2", "occurred_at": at("09:00", "2026-03-12")}, headers=REVIEWER)
    assert ok.status_code == 200
    done = conn.execute("SELECT completed_at FROM cases WHERE case_id = 'c2'").fetchone()["completed_at"]
    assert conn.execute("SELECT ends_at FROM waiting_intervals WHERE case_id = 'c2'").fetchone()["ends_at"] == done


def test_q01_api_rows_pass_the_domain_ingest(api, conn):
    """What the API accepts, the ingest accepts: the A2 rows (completed at 09:30) are no longer producible."""
    drive_until_completable(api, "c2", approvals_at=("15:00", "15:20"), unlock_at="15:05", submit2_at="15:10")
    assert command(api, "complete-case", {"case_id": "c2", "occurred_at": at("15:20")}, headers=REVIEWER).status_code == 200
    from api import db as apidb
    rows = {}
    for t in ["organizations", "workflow_versions", "step_definitions", "dependencies", "sla_rules", "calendar_intervals",
              "cases", "step_instances", "assignments", "document_versions", "approvals", "waiting_intervals",
              "case_events"]:
        rows[t] = [{k: (v.isoformat() if hasattr(v, "isoformat") else (float(v) if type(v).__name__ == "Decimal" else v))
                    for k, v in r.items()} for r in conn.execute(apidb._ROWS.get(t, f"select * from {t}")).fetchall()]
    rows["workflow_requirements"] = {"wfv-001": {"required_document_types": ["identity_proof"]}}
    for r in rows["sla_rules"]:
        r["business_minutes"] = int(r["business_minutes"])
        r["pause_policy"] = list(r["pause_policy"])
    for r in rows["cases"]:
        r.pop("version", None)
        r.pop("linked_case_id", None)
    from onboard_studio.ingest import validate_batch
    assert [x.as_dict() for x in validate_batch(rows).rejected if x.entity == "cases" and x.id == "c2"] == []


@pytest.mark.parametrize("what", ["approval", "document_review", "assignment_end", "event"])
def test_q01_completion_before_each_kind_of_recorded_work(api, conn, what):
    drive_until_completable(api, "cq")
    if what == "assignment_end":
        conn.execute("UPDATE assignments SET ended_at = %s WHERE step_instance_id = %s", (at("09:55"), step_id("cq", "sd-001")))
        latest = "09:55"
    else:
        latest = {"approval": "09:40", "document_review": "09:40", "event": "09:40"}[what]
    if what == "document_review":
        # a review recorded later than everything else on the case
        conn.execute("INSERT INTO document_reviews (review_id, document_version_id, decision, reviewer_id, decided_at) "
                     "VALUES ('rev-late', 'cq:approval_form:v1', 'accepted', 'rev-1', %s)", (at("10:05"),))
        latest = "10:05"
    r = command(api, "complete-case", {"case_id": "cq", "occurred_at": at("09:39")}, headers=REVIEWER)
    assert r.status_code == 422 and rule_ids(r) == ["COMPLETION_BEFORE_RECORDED_WORK"], r.text
    r = command(api, "complete-case", {"case_id": "cq", "occurred_at": at(latest)}, headers=REVIEWER)
    assert r.status_code == 200, r.text


def test_q01_pause_outside_the_case_span_is_422(api, conn):
    open_case(api, "cp", at("09:00"))
    r = command(api, "pause-sla", {"case_id": "cp", "reason_code": R, "starts_at": at("08:59")})
    assert r.status_code == 422 and rule_ids(r) == ["PAUSE_OUTSIDE_CASE_SPAN"]
    assert r.json()["error"]["details"][0]["context"]["opened_at"] == "2026-03-10T09:00:00Z"
    assert conn.execute("SELECT count(*) AS n FROM waiting_intervals WHERE case_id = 'cp'").fetchone()["n"] == 0


def test_q01_pause_after_completion_is_refused_and_the_span_rule_covers_a_completed_row(api, conn):
    drive_until_completable(api, "cd")
    assert command(api, "complete-case", {"case_id": "cd", "occurred_at": at("09:45")}, headers=REVIEWER).status_code == 200
    r = command(api, "pause-sla", {"case_id": "cd", "reason_code": R, "starts_at": at("10:00")})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CASE_ALREADY_COMPLETE"      # the case state wins
    case = {"opened_at": parse_ts(at("09:00")), "completed_at": parse_ts(at("09:45"))}
    for start, end in ((at("09:45"), None), (at("09:30"), at("09:50")), (at("08:00"), None)):
        with pytest.raises(commands.ApiError) as e:
            commands._require_inside_case_span(case, parse_ts(start), parse_ts(end) if end else None)
        assert e.value.status == 422 and e.value.details[0]["rule_id"] == "PAUSE_OUTSIDE_CASE_SPAN"
    commands._require_inside_case_span(case, parse_ts(at("09:10")), parse_ts(at("09:45")))   # inside: no error


def test_q01_database_trigger_enforces_completed_at_after_every_event(api, conn):
    drive_until_completable(api, "ct")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="latest recorded event"):
        conn.execute("UPDATE cases SET status = 'completed', completed_at = %s WHERE case_id = 'ct'", (at("09:30"),))
    assert command(api, "complete-case", {"case_id": "ct", "occurred_at": at("09:45")}, headers=REVIEWER).status_code == 200
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="cannot follow the completion"):
        conn.execute("INSERT INTO case_events VALUES ('ev-late', 'ct', 'step_approved', 'x', %s)", (at("10:00"),))
    conn.execute("INSERT INTO case_events VALUES ('ev-same', 'ct', 'note', 'x', %s)", (at("09:45"),))   # equal is fine


# --- Q-02 -------------------------------------------------------------------------------------------------

def test_q02_every_command_locks_the_case_before_the_step(api, monkeypatch):
    open_case(api, "cl", at("09:00"))
    s1, s2 = step_id("cl", "sd-001"), step_id("cl", "sd-002")
    order: list[str] = []
    real_case, real_step = commands._case, commands._step
    monkeypatch.setattr(commands, "_case", lambda *a, **k: (order.append("case"), real_case(*a, **k))[1])
    monkeypatch.setattr(commands, "_step", lambda *a, **k: (order.append("step"), real_step(*a, **k))[1])
    command(api, "submit-document", {"case_id": "cl", "document_type": "identity_proof", "step_instance_id": s1})
    command(api, "approve-step", {"step_instance_id": s1, "expected_version": 1})
    command(api, "unlock-dependent-step", {"step_instance_id": s2})
    assert order == ["case", "step", "case", "step", "case", "step"]       # was step, case for approve and unlock


def test_q02_a_deadlock_is_retried_then_409_never_500(api, monkeypatch):
    calls = {"n": 0}
    real = commands._execute_once

    def always(*a, **k):
        calls["n"] += 1
        raise psycopg.errors.DeadlockDetected("deadlock detected")
    monkeypatch.setattr(commands, "_execute_once", always)
    monkeypatch.setattr(commands.time, "sleep", lambda s: None)
    r = command(api, "pause-sla", {"case_id": "case-001", "reason_code": R})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONCURRENT_UPDATE" and calls["n"] == 3

    calls["n"] = 0

    def once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.errors.SerializationFailure("could not serialize access")
        return real(*a, **k)
    monkeypatch.setattr(commands, "_execute_once", real)
    open_case(api, "cr", at("09:00"))
    calls["n"] = 0
    monkeypatch.setattr(commands, "_execute_once", once)
    r = command(api, "pause-sla", {"case_id": "cr", "reason_code": R, "starts_at": at("10:00"), "ends_at": at("11:00")})
    assert r.status_code == 200 and calls["n"] == 2


def test_q02_the_reviewers_25_races_have_no_500(api, db_url):
    """approve-step vs reject-submission on the same step, 25 times (9/25 were 500 before)."""
    codes: dict[tuple, int] = {}
    for i in range(25):
        cid = f"d{i}"
        open_case(api, cid, at("09:00"))
        s1 = step_id(cid, "sd-001")
        command(api, "submit-document", {"case_id": cid, "document_type": "identity_proof", "step_instance_id": s1,
                                         "occurred_at": at("09:05")})
        bar = threading.Barrier(2)

        def approve():
            bar.wait()
            with TestClient(create_app(), raise_server_exceptions=False) as c:
                return "approve", command(c, "approve-step", {"step_instance_id": s1, "expected_version": 1}, headers=OPS)

        def reject():
            bar.wait()
            with TestClient(create_app(), raise_server_exceptions=False) as c:
                return "reject", command(c, "reject-submission", {"case_id": cid, "document_type": "identity_proof",
                                                                  "step_instance_id": s1, "reason": "blurry"}, headers=REVIEWER)
        with cf.ThreadPoolExecutor(2) as ex:
            for name, r in [f.result() for f in [ex.submit(approve), ex.submit(reject)]]:
                key = (name, r.status_code)
                codes[key] = codes.get(key, 0) + 1
    assert not [k for k in codes if k[1] >= 500], codes
    assert sum(codes.values()) == 50


# --- Q-03 -------------------------------------------------------------------------------------------------

SQL = (__import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()


def case_inputs(cases, waits=(), calendar=None):
    """Golden inputs reduced to bare completed cases (no steps, documents or events) plus optional waits."""
    d = golden_inputs()
    tmpl = d["cases"][0]
    d["cases"] = [dict(tmpl, case_id=f"c{i}", opened_at=o, completed_at=c, status="completed" if c else "open")
                  for i, (o, c) in enumerate(cases)]
    for k in ("step_instances", "assignments", "approvals", "case_events", "document_versions"):
        d[k] = []
    d["waiting_intervals"] = [dict(waiting_interval_id=f"w{j}", case_id=cid, reason_code=R, starts_at=s, ends_at=e)
                              for j, (cid, s, e) in enumerate(waits)]
    d["workflow_requirements"] = {}
    for s in d["step_definitions"]:
        s["required"] = False
    if calendar is not None:
        d["calendar_intervals"] = calendar
    return d


def test_q03_sql_sums_seconds_first_so_an_exact_tie_rounds_half_up(conn):
    """150 cases of 7,7,7,4,1,1 and 144 x 0 seconds: the mean is exactly 0.00005 h, which rounds to 0.0001."""
    from datetime import datetime, timedelta, timezone
    cs = []
    for i, secs in enumerate([7, 7, 7, 4, 1, 1] + [0] * 144):
        o = datetime(2026, 3, 2 + i % 4, 9 + (i // 4) % 8, (i // 32) * 5, tzinfo=timezone.utc)
        cs.append((o.isoformat().replace("+00:00", "Z"), (o + timedelta(seconds=secs)).isoformat().replace("+00:00", "Z")))
    data = case_inputs(cs)
    seed.seed(conn, data)
    row = conn.execute(SQL).fetchone()
    want = run_pipeline(data, "pause_eligible").metrics
    assert row["completed_eligible_cases"] == 150
    assert row["calendar_cycle_time_hours"] == "0.0001" == want["calendar_cycle_time_hours"]
    for k in HOURS:
        assert row[k] == want[k], k


@pytest.mark.parametrize("waits,paused,active", [
    ([("c0", "2026-03-02T10:00:00Z", "2026-03-02T12:00:00Z"), ("c0", "2026-03-02T11:00:00Z", "2026-03-02T13:00:00Z")], "3.0000", "5.0000"),
    ([("c0", "2026-03-02T10:00:00Z", "2026-03-02T12:00:00Z"), ("c0", "2026-03-02T12:00:00Z", "2026-03-02T13:00:00Z")], "3.0000", "5.0000"),
    ([("c0", "2026-03-02T10:00:00Z", "2026-03-02T14:00:00Z"), ("c0", "2026-03-02T11:00:00Z", "2026-03-02T12:00:00Z")], "4.0000", "4.0000"),
    ([("c0", "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z"), ("c0", "2026-03-02T15:00:00Z", "2026-03-02T16:00:00Z")], "2.0000", "6.0000"),
])
def test_q03_sql_merges_overlapping_waits_like_the_domain(conn, waits, paused, active):
    data = case_inputs([("2026-03-02T09:00:00Z", "2026-03-02T17:00:00Z")], waits)
    seed.seed(conn, data)
    row = conn.execute(SQL).fetchone()
    want = run_pipeline(data, "pause_eligible").metrics
    assert (row["paused_time_hours"], row["active_elapsed_hours"]) == (paused, active)       # 4.0000 / 4.0000 before the merge
    for k in HOURS:
        assert row[k] == want[k], k


# --- Q-04 -------------------------------------------------------------------------------------------------

def v2_of(data, status):
    v1 = data["document_versions"][0]
    data["document_versions"].append(dict(v1, document_version_id="doc-002", version_number=2, review_status=status,
                                          submitted_at="2026-03-09T09:36:00Z", reviewed_at="2026-03-09T09:38:00Z",
                                          content_hash="sha256:" + "0" * 63 + "2"))


@pytest.mark.parametrize("status", ["rejected", "submitted"])
def test_q04_python_ingest_a_later_version_that_is_not_accepted_blocks_completion(status):
    data = golden_inputs()
    assert [r for r in run_pipeline(data).rejected] == []
    v2_of(data, status)
    res = run_pipeline(data)
    assert [(r["entity"], r["id"], r["reason_code"]) for r in res.rejected if r["entity"] == "cases"] == \
        [("cases", "case-001", "MISSING_REQUIRED_DOCUMENT")]                                  # was accepted
    assert res.metrics["completed_eligible_cases"] == 0


def test_q04_python_document_completeness_uses_the_latest_version():
    data = golden_inputs()
    c = data["cases"][0]
    c.update(status="open", completed_at=None)              # an open case: it reaches the metrics
    data["case_events"] = [e for e in data["case_events"] if e["event_type"] != "case_completed"]
    assert run_pipeline(data).metrics["document_completeness"] == "1.000000"
    v2_of(data, "rejected")
    assert run_pipeline(data).metrics["document_completeness"] == "0.000000"                 # was 1.000000
    data["document_versions"][1]["review_status"] = "accepted"
    assert run_pipeline(data).metrics["document_completeness"] == "1.000000"                 # v1 rejected, v2 accepted


def test_q04_api_complete_case_uses_the_latest_version(api, conn):
    drive_until_completable(api, "cv")
    conn.execute("INSERT INTO document_versions (document_version_id, case_id, document_type, version_number, "
                 "content_hash, review_status, submitted_at) VALUES ('cv:identity_proof:v2', 'cv', 'identity_proof', 2, "
                 "'sha256:x', 'submitted', %s)", (at("09:41"),))
    r = command(api, "complete-case", {"case_id": "cv", "occurred_at": at("09:50")}, headers=REVIEWER)
    assert r.status_code == 422 and rule_ids(r) == ["MISSING_REQUIRED_DOCUMENT"]            # v1 accepted, v2 only submitted
    assert r.json()["error"]["details"][0]["context"]["document_types"] == ["identity_proof"]
    assert command(api, "accept-document", {"case_id": "cv", "document_type": "identity_proof", "occurred_at": at("09:55")},
                   headers=REVIEWER).status_code == 200
    assert command(api, "complete-case", {"case_id": "cv", "occurred_at": at("09:56")}, headers=REVIEWER).status_code == 200


# --- Q-05 -------------------------------------------------------------------------------------------------

def publish_body(wid, calendar):
    return {"workflow_version_id": wid,
            "steps": [{"step_definition_id": f"{wid}-a", "step_name": "a", "required": True, "role_key": "ops", "sequence": 1}],
            "dependencies": [], "required_document_types": [],
            "sla_rule": {"sla_rule_id": f"sla-{wid}", "business_minutes": 480, "pause_policy": [R], "calendar_id": calendar}}


def test_q05_publish_with_an_unknown_calendar_is_422_and_writes_nothing(api, conn):
    r = command(api, "publish-workflow-version", publish_body("wv-x", "cal-nope"), headers=ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["CALENDAR_UNKNOWN"]
    assert r.json()["error"]["details"][0]["path"] == "input.sla_rule.calendar_id"
    assert count(conn, "workflow_versions") == 1 and count(conn, "sla_rules") == 1
    assert command(api, "publish-workflow-version", publish_body("wv-x", "cal-001"), headers=ADMIN).status_code == 200


def test_q05_sla_rules_calendar_id_is_a_foreign_key(seeded):
    assert seeded.execute("SELECT calendar_id FROM calendars").fetchall() == [{"calendar_id": "cal-001"}]
    seeded.execute("INSERT INTO workflow_versions (workflow_version_id, template_id, version_number) VALUES ('wv-q', 'tpl-q', 1)")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        seeded.execute("INSERT INTO sla_rules VALUES ('sla-bad', 'wv-q', 10, '{}', 'cal-nope')")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        seeded.execute("INSERT INTO calendar_intervals VALUES ('ci-x', 'cal-nope', now(), now() + interval '1 hour', 'UTC', 'working')")


@pytest.mark.parametrize("calendar", [[], [dict(calendar_interval_id="h", calendar_id="cal-001", starts_at="2026-03-02T00:00:00Z",
                                                ends_at="2026-03-03T00:00:00Z", timezone="UTC", kind="holiday")]])
def test_q05_python_a_calendar_without_working_intervals_is_unevaluated(calendar):
    data = golden_inputs()
    data["calendar_intervals"] = calendar
    res = run_pipeline(data, "pause_eligible")
    m = res.metrics
    assert res.sla_unevaluated_cases == 1 and [f["flag"] for f in res.flags] == [FLAG_SLA_UNEVALUATED]
    assert (m["completed_eligible_cases"], m["within_sla_cases"], m["sla_attainment"]) == (0, 0, None)   # was 1, 1, 1.000000
    assert m["business_cycle_time_hours"] is None and m["active_elapsed_hours"] is None
    assert run_pipeline(golden_inputs(), "pause_eligible").sla_unevaluated_cases == 0


def test_q05_sql_and_api_agree_with_python_on_an_empty_calendar(api, conn):
    conn.execute("DELETE FROM calendar_intervals")
    row = conn.execute(SQL).fetchone()
    assert (row["completed_eligible_cases"], row["within_sla_cases"], row["sla_unevaluated_cases"]) == (0, 0, 1)
    assert row["business_cycle_time_hours"] is None
    body = api.get(f"{PREFIX}/metrics").json()
    assert body["data"]["sla_unevaluated_cases"] == 1
    assert body["data"]["metrics"]["completed_eligible_cases"] == 0 and body["data"]["metrics"]["sla_attainment"] is None
    assert [w["code"] for w in body["warnings"]] == [FLAG_SLA_UNEVALUATED]
    conn.execute("DELETE FROM waiting_intervals")
    seed.seed(conn, golden_inputs())
    assert conn.execute(SQL).fetchone()["sla_unevaluated_cases"] == 0
    assert api.get(f"{PREFIX}/metrics").json()["data"]["sla_unevaluated_cases"] == 0


# --- Q-06 -------------------------------------------------------------------------------------------------

def test_q06_a_replay_by_a_different_actor_is_409(api, conn):
    open_case(api, "ci", at("09:00"))
    body = {"case_id": "ci", "reason_code": R, "starts_at": at("10:00"), "ends_at": at("11:00")}
    first = command(api, "pause-sla", body, key="idem-q6")
    assert first.status_code == 200
    same = command(api, "pause-sla", body, key="idem-q6")
    assert same.status_code == 200 and same.headers["Idempotent-Replay"] == "true" and same.json() == first.json()
    other = command(api, "pause-sla", body, key="idem-q6", headers=ADMIN)
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"       # was a replay
    assert rule_ids(other) == ["IDEMPOTENCY_ACTOR_MISMATCH"]
    assert conn.execute("SELECT count(*) AS n FROM waiting_intervals WHERE case_id = 'ci'").fetchone()["n"] == 1
    diff = command(api, "pause-sla", dict(body, ends_at=at("12:00")), key="idem-q6")
    assert diff.status_code == 409 and rule_ids(diff) == ["IDEMPOTENCY_PAYLOAD_MISMATCH"]


@pytest.mark.parametrize("variant", ["2026-03-10T10:00:00+00:00", "2026-03-10T11:00:00+01:00", "2026-03-10T10:00:00.000Z"])
def test_q06_instants_are_normalised_before_hashing(api, conn, variant):
    open_case(api, "cz", at("09:00"))
    base = {"case_id": "cz", "reason_code": R, "starts_at": at("10:00"), "ends_at": at("11:00")}
    first = command(api, "pause-sla", base, key="idem-z")
    assert first.status_code == 200
    replay = command(api, "pause-sla", dict(base, starts_at=variant), key="idem-z")
    assert replay.status_code == 200 and replay.headers["Idempotent-Replay"] == "true"       # was 409 PAYLOAD_MISMATCH
    assert replay.json() == first.json()
    assert conn.execute("SELECT count(*) AS n FROM waiting_intervals WHERE case_id = 'cz'").fetchone()["n"] == 1
    other = command(api, "pause-sla", dict(base, starts_at="2026-03-10T10:00:01+00:00"), key="idem-z")
    assert other.status_code == 409                                                           # a different instant is different
