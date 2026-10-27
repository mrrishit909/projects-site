"""Adversarial cases P10-TEST-01..12, DETECT and RECOVER, end to end through the actual application path (API over PostgreSQL), each from its
smallest fixture under tests/fixtures/adversarial/ (hypothesis, dataset, set-up steps, the defect, the correction). The generic runner asserts the
R-items every case shares (state captured before, accepted/rejected counts, the business value, unrelated records intact, a specific safe
explanation, a retry that adds nothing); each case then has its own business assertions. Hostile-input, interruption and concurrency cases follow."""
import json
import re
import threading
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import psycopg
import pytest

from api import clock
from api import commands as cmds
from retentionlab.numbers import canon, sha256_hex
from support_db import (ADMIN, ANALYST, BUSINESS_TABLES, SCIENTIST, client, command, conn, count, current_dataset_version, db_url, get, load, metrics, offending,  # noqa: F401
                        rule_ids, table_digest, ts)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "adversarial"
IDS = [f"{n:02d}" for n in range(1, 13)]
SECRET_WORDS = ("traceback", "postgres", "password", "database_url", "psycopg", "select ", "insert into")
F4 = ["usage_events_30d", "days_since_last_usage", "high_severity_support_90d", "billing_total_90d"]


def fixture(n: str) -> dict:
    return json.loads((FIXTURES / f"p10-test-{n}.json").read_text())


def path(obj, dotted):
    for part in dotted.split("."):
        obj = obj[part]
    return obj


def prepare(conn, client, fx):
    """R03/R06: the smallest fixture, loaded; the initial canonical state and dataset hash captured; the set-up steps run through the API."""
    clock.freeze(ts(fx["clock"]))
    out = load(conn, fx["inputs"])
    assert out["skipped"] == len(fx["expect_rejected"])                                         # R08: accepted / rejected counts of the ingestion
    got = [{"entity": r["entity"], "id": r["id"], "reason_code": r["reason_code"]} for r in conn.execute("SELECT entity, id, reason_code FROM rejected_records ORDER BY 1, 2").fetchall()]
    assert got == sorted([{**e, "id": str(e["id"])} for e in fx["expect_rejected"]], key=lambda r: (r["entity"], r["id"]))
    for step in fx["setup"]:
        r = command(client, step["command"], step["input"])
        assert r.status_code == 200, (step, r.text)
    return {"digest": table_digest(conn, BUSINESS_TABLES), "dataset_version": current_dataset_version(), "dataset_hash": conn.execute("SELECT dataset_hash FROM dataset_versions").fetchone()["dataset_hash"]}


def check_expect(r, expect):
    assert r.status_code == expect["status"], r.text
    body = r.json()
    if expect["status"] == 200:
        for dotted, want in expect.get("result", {}).items():
            assert path(body["result"], dotted) == want, (dotted, body["result"])
        if "warning" in expect:
            assert expect["warning"] in {w["code"] for w in body["warnings"]}
    else:
        assert rule_ids(r) == expect["rules"]
        assert offending(r) == expect["offending"]                                          # R05: the affected items, not a generic exception
        if "message_contains" in expect:
            assert expect["message_contains"] in body["error"]["message"] or expect["message_contains"] in json.dumps(body["error"]["details"])
        low = r.text.lower()
        assert not any(w in low for w in SECRET_WORDS)                                       # R11: specific, safe, no internals


def audit_count(conn, action):
    return count(conn, "audit_events", f"action = '{action}'")                              # action is a fixture constant


@pytest.mark.parametrize("n", IDS)
def test_detect(client, conn, n):
    fx = fixture(n)
    d = fx["detect"]
    state = prepare(conn, client, fx)
    audits, results = count(conn, "audit_events"), count(conn, "command_results")
    r = command(client, d["command"], d["input"], key=f"detect-{n}")
    check_expect(r, d["expect"])
    if d["expect"]["status"] != 200:
        # R10: nothing about the valid records or the prior publications changed; the refusal itself is audited; nothing stored for replay
        assert table_digest(conn, BUSINESS_TABLES) == state["digest"]
        assert audit_count(conn, d["audit"]) == 1 and count(conn, "audit_events") == audits + 1 and count(conn, "command_results") == results
        a = conn.execute("SELECT * FROM audit_events WHERE action = %s", (d["audit"],)).fetchone()
        assert a["actor_id"] == SCIENTIST["X-Actor-Id"] and a["details"]["rule_id"] == d["expect"]["rules"][0]
        for t in d.get("unchanged", []):
            assert table_digest(conn, [t]) == {t: state["digest"][t]}
        # R12: retrying the refused action adds no side effect and is refused the same way
        again = command(client, d["command"], d["input"], key=f"detect-{n}-retry")
        assert again.status_code == r.status_code and rule_ids(again) == rule_ids(r) and table_digest(conn, BUSINESS_TABLES) == state["digest"]
        for extra in d.get("also", []):
            r2 = command(client, d["command"], {**d["input"], **{k: v for k, v in extra.items() if k != "rules"}})
            assert r2.status_code == 422 and rule_ids(r2) == extra["rules"], extra
            assert table_digest(conn, BUSINESS_TABLES) == state["digest"]
    else:
        for bad in d.get("db_refuse", []):
            with pytest.raises(getattr(psycopg.errors, bad["error"]), match=bad["match"]):
                conn.execute(bad["sql"])                                                    # the database refuses what the application would never write
        replay = command(client, d["command"], d["input"], key=f"detect-{n}")
        assert replay.headers.get("Idempotent-Replay") == "true" and replay.json() == r.json()           # R12
    BESPOKE_DETECT.get(n, lambda *a: None)(client, conn, fx, state, r)
    assert state["dataset_hash"] == conn.execute("SELECT dataset_hash FROM dataset_versions").fetchone()["dataset_hash"]      # the dataset itself was never touched


@pytest.mark.parametrize("n", IDS)
def test_recover(client, conn, n):
    fx = fixture(n)
    rc = fx["recover"]
    state = prepare(conn, client, fx)
    d = fx["detect"]
    if d["expect"]["status"] != 200:
        assert command(client, d["command"], d["input"]).status_code == d["expect"]["status"]       # the defect first, refused
    else:
        assert command(client, d["command"], d["input"]).status_code == 200
    if rc.get("clock"):
        clock.freeze(ts(rc["clock"]))
    before = table_digest(conn, BUSINESS_TABLES)
    r = command(client, rc["command"], rc["input"], key=f"recover-{n}")
    check_expect(r, rc["expect"])                                                          # a valid correction restores a consistent state
    after = table_digest(conn, BUSINESS_TABLES)
    replay = command(client, rc["command"], rc["input"], key=f"recover-{n}")
    assert replay.headers["Idempotent-Replay"] == "true" and replay.json() == r.json() and table_digest(conn, BUSINESS_TABLES) == after      # safe replay
    runs = count(conn, "training_runs")
    if runs <= 1:                                                                         # stored derived rows equal the rebuilt ones (the server's now is the as_of)
        cons = metrics(client, training_run_id="tr-1" if runs else None)["data"]["consistency"]
        assert all(v == [] for v in cons.values()), cons
    BESPOKE_RECOVER.get(n, lambda *a: None)(client, conn, fx, state, r, before)


# ---------------------------------------------------------------------------------------------------- the case-specific business assertions
def d01(client, conn, fx, state, r):
    assert count(conn, "feature_rows") == 0                                                  # no row built, in particular none with the post-outcome field


def r01(client, conn, fx, state, r, before):
    keys = {k for row in conn.execute("SELECT features_json FROM feature_rows").fetchall() for k in row["features_json"]}
    assert keys == set(F4) and "cancellation_reason" not in keys


def d02(client, conn, fx, state, r):
    row = conn.execute("SELECT * FROM feature_rows WHERE cutoff_id = 'co-01-20260101000000'").fetchone()
    assert row["features_json"]["usage_events_30d"] == 1 and row["features_json"]["days_since_last_usage"] == 12      # the late event (12-30, arrived 01-05) is not in it
    assert row["max_available_at"] < ts("2026-01-01T00:00:00Z")


def r02(client, conn, fx, state, r, before):
    later = conn.execute("SELECT features_json, max_available_at FROM feature_rows WHERE cutoff_id = 'co-01-20260110000000'").fetchone()
    assert later["features_json"]["usage_events_30d"] == 2 and later["features_json"]["days_since_last_usage"] == 11 and later["max_available_at"] == ts("2026-01-05T00:00:00Z")
    first = conn.execute("SELECT features_json FROM feature_rows WHERE cutoff_id = 'co-01-20260101000000'").fetchone()
    assert first["features_json"]["usage_events_30d"] == 1                                    # the earlier row is append-only: it did not change when the event "arrived"


def d03(client, conn, fx, state, r):
    sides = {}
    for row in conn.execute("SELECT s.split, c.account_id FROM split_assignments s JOIN prediction_cutoffs c USING (cutoff_id) WHERE s.status = 'retained'").fetchall():
        sides.setdefault(row["split"], set()).add(row["account_id"])
    assert sides["train"] == {2} and sides["test"] == {1, 3} and not (sides["train"] & sides["test"])
    dropped = conn.execute("SELECT cutoff_id, drop_reason FROM split_assignments WHERE status = 'dropped'").fetchall()
    assert [(x["cutoff_id"], x["drop_reason"]) for x in dropped] == [("co-01-20250301000000", "GROUP_TEST")]


def r03(client, conn, fx, state, r, before):
    assert conn.execute("SELECT config -> 'preprocessing' ->> 'fit_rows' AS n FROM training_runs").fetchone()["n"] == "1"


def d04(client, conn, fx, state, r):
    rows = {x["cutoff_id"]: (x["status"], x["drop_reason"]) for x in conn.execute("SELECT * FROM split_assignments").fetchall()}
    assert rows == {"co-01-20250319000000": ("retained", None), "co-02-20250320000000": ("dropped", "LABEL_WINDOW")}       # label_end = train_end stays; one second... one day later crosses


def r04(client, conn, fx, state, r, before):
    rows = conn.execute("SELECT training_run_id, cutoff_id, status FROM split_assignments ORDER BY 1, 2").fetchall()
    assert [(x["training_run_id"], x["status"]) for x in rows] == [("tr-1", "retained"), ("tr-1", "dropped"), ("tr-2", "retained"), ("tr-2", "retained")]      # tr-1 history intact


def r05(client, conn, fx, state, r, before):
    cfg = conn.execute("SELECT config FROM training_runs").fetchone()["config"]["preprocessing"]
    train = conn.execute("SELECT f.features_json FROM feature_rows f JOIN split_assignments s USING (cutoff_id) WHERE s.split = 'train' AND s.status = 'retained'").fetchall()
    every = conn.execute("SELECT features_json FROM feature_rows").fetchall()
    use = sorted(Fraction(str(x["features_json"]["usage_events_30d"])) for x in train)
    assert len(use) == 6 and cfg["features"]["usage_events_30d"]["median"] == f"{float((use[2] + use[3]) / 2):.6f}"
    mean_train = sum(use) / 6
    assert cfg["features"]["usage_events_30d"]["mean"] == f"{float(mean_train):.6f}"
    mean_all = sum(Fraction(str(x["features_json"]["usage_events_30d"])) for x in every) / len(every)
    assert mean_all != mean_train                                                              # a fit over all rows WOULD have been a different (leaking) transformer
    assert cfg["fit_rows_sha256"] == sha256_hex(canon(sorted(x["cutoff_id"] for x in conn.execute("SELECT cutoff_id FROM split_assignments WHERE split = 'train' AND status = 'retained'").fetchall())))


def r06(client, conn, fx, state, r, before):
    assert conn.execute("SELECT selected_on FROM intervention_scenarios WHERE scenario_id = 'sc-t'").fetchone()["selected_on"] == "validation"
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO intervention_scenarios (scenario_id, capacity, contact_cost, assumed_effect, margin_value, selected_on) VALUES ('sc-x', 1, 1, 0.1, 1, 'test')")


def d07(client, conn, fx, state, r):
    lab = conn.execute("SELECT * FROM labels WHERE cutoff_id = 'co-02-20260201000000'").fetchone()
    assert (lab["churned"], lab["mature"]) == (None, False)                                    # unknown, not false
    assert conn.execute("SELECT count(*) AS n FROM labels WHERE churned = false AND mature = false").fetchone()["n"] == 0


def r07(client, conn, fx, state, r, before):
    lab = conn.execute("SELECT * FROM labels WHERE cutoff_id = 'co-02-20260201000000'").fetchone()
    assert (lab["churned"], lab["mature"]) == (True, True)
    with pytest.raises(psycopg.errors.IntegrityError, match="LABEL_IMMUTABLE"):
        conn.execute("UPDATE labels SET churned = false WHERE cutoff_id = 'co-02-20260201000000'")
    again = command(client, "define-label", {"prediction_at": "2026-02-01T00:00:00Z"})
    assert again.json()["status"] == "unchanged" and again.json()["result"]["matured_now"] == 0


def r08(client, conn, fx, state, r, before):
    cols = conn.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND (column_name ILIKE '%latent%' OR column_name ILIKE '%propensity%' OR column_name ILIKE '%true_churn%')").fetchall()
    assert [(c["table_name"], c["column_name"]) for c in cols] == [("feature_registry", "latent")]      # the registry's FLAG; the generator's truth itself has no column anywhere
    assert {k for row in conn.execute("SELECT features_json FROM feature_rows").fetchall() for k in row["features_json"]} == set(F4)


def d09(client, conn, fx, state, r):
    assert count(conn, "outreach_events") == 0 and count(conn, "intervention_scenarios") == 0


def r09(client, conn, fx, state, r, before):
    assert conn.execute("SELECT array_agg(status) AS s FROM outreach_events").fetchone()["s"] == ["draft", "draft"]
    sim = command(client, "simulate-economics", {"training_run_id": "tr-1", "prediction_at": "2025-10-01T00:00:00Z", "scenario_id": "sc-r"})
    assert sim.json()["result"]["treatment_effect_estimate"] is None and sim.json()["result"]["label"] == "hypothetical"
    text = json.dumps(metrics(client, training_run_id="tr-1", prediction_at="2025-10-01T00:00:00Z", scenario_id="sc-r", as_of="2026-05-02T00:00:00Z")["data"]).lower()
    assert "uplift" not in text and "responsiveness" not in text and "risk_lift_at_k" in text      # lift is a ranking statistic, never named uplift


def d10(client, conn, fx, state, r):
    conn.execute("INSERT INTO intervention_scenarios (scenario_id, capacity, contact_cost, assumed_effect, margin_value) VALUES ('sc-big', 5, 5, 0.1, 100)")
    m = get(client, "/metrics", training_run_id="tr-1", prediction_at="2025-10-01T00:00:00Z", scenario_id="sc-big", as_of="2026-05-02T00:00:00Z")
    assert m.status_code == 422 and rule_ids(m) == ["CAPACITY_EXCEEDS_POPULATION"]             # the read side refuses the same K


def r10(client, conn, fx, state, r, before):
    rows = conn.execute("SELECT queue_rank FROM outreach_events WHERE scenario_id = 'sc-ok' ORDER BY 1").fetchall()
    assert [x["queue_rank"] for x in rows] == [1, 2, 3, 4]


def r11(client, conn, fx, state, r, before):
    cal = conn.execute("SELECT config -> 'calibration' AS c FROM training_runs").fetchone()["c"]
    val = sorted(x["cutoff_id"] for x in conn.execute("SELECT cutoff_id FROM split_assignments WHERE split = 'validation' AND status = 'retained'").fetchall())
    test = {x["cutoff_id"] for x in conn.execute("SELECT cutoff_id FROM split_assignments WHERE split = 'test' AND status = 'retained'").fetchall()}
    assert cal["fit_rows_sha256"] == sha256_hex(canon(val)) and not (set(val) & test) and cal["fit_rows"] == 4
    assert conn.execute("SELECT a, b FROM calibration_maps").fetchone() is not None


def d11(client, conn, fx, state, r):
    assert count(conn, "calibration_maps") == 0 and "calibration" not in conn.execute("SELECT config FROM training_runs").fetchone()["config"]


def d12(client, conn, fx, state, r):
    assert count(conn, "feature_rows") == 14                                                    # only the ones the set-up built from registered fields


def r12(client, conn, fx, state, r, before):
    run = conn.execute("SELECT config FROM training_runs").fetchone()["config"]
    coefs = {m["name"]: m for m in run["models"]}["logistic_regression"]["coefficients"]
    allowed = {"intercept", *F4} | {f"{f}_missing" for f in F4}
    assert set(coefs) <= allowed                                                                # no id, seed or manifest term can have been learned
    assert not any(re.search(r"seed|account|latent|manifest|sequence", t) for t in coefs)


BESPOKE_DETECT = {"01": d01, "02": d02, "03": d03, "04": d04, "07": d07, "09": d09, "10": d10, "11": d11, "12": d12}
BESPOKE_RECOVER = {"01": r01, "02": r02, "03": r03, "04": r04, "05": r05, "06": r06, "07": r07, "08": r08, "09": r09, "10": r10, "11": r11, "12": r12}


def test_every_case_has_a_hypothesis_a_fixture_and_both_modes():
    assert [fixture(n)["id"] for n in IDS] == [f"P10-TEST-{n}" for n in IDS]
    for n in IDS:
        fx = fixture(n)
        assert fx["hypothesis"] and fx["inputs"]["accounts"] and fx["detect"]["expect"]["status"] in (200, 422) and fx["recover"]["expect"]["status"] == 200
    assert {fixture(n)["hypothesis"] for n in IDS} >= {"Cancellation reason enters pre-cancellation features", "Generator seed memorized by complex model",
                                                      "Calibration evaluated on calibration training data", "High churn risk mistaken for offer responsiveness"}


# ---------------------------------------------------------------------------------------------------- interruption, hostile input, abuse
def test_an_interrupted_command_leaves_nothing_and_a_retry_with_the_same_key_succeeds(client, conn, monkeypatch):
    fx = fixture("10")
    prepare(conn, client, fx)
    digest, audits, results = table_digest(conn, BUSINESS_TABLES), count(conn, "audit_events"), count(conn, "command_results")
    real = cmds.prioritize_outreach

    def crash_after_writing(c, req, actor):
        real(c, req, actor)                                                                  # the queue rows and the scenario ARE written ...
        raise RuntimeError("connection lost; password=hunter2 host=db.internal")             # ... and then the process dies before commit
    monkeypatch.setattr(cmds, "prioritize_outreach", crash_after_writing)
    from fastapi.testclient import TestClient
    from api import app as appmod
    inp = fx["recover"]["input"]
    with TestClient(appmod.create_app(), raise_server_exceptions=False) as c:
        r = command(c, "prioritize-outreach", inp, key="crash-key")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR" and "hunter2" not in r.text and "db.internal" not in r.text
    assert table_digest(conn, BUSINESS_TABLES) == digest and count(conn, "audit_events") == audits and count(conn, "command_results") == results       # explicit non-commit
    monkeypatch.setattr(cmds, "prioritize_outreach", real)
    with TestClient(appmod.create_app(), raise_server_exceptions=False) as c:
        ok = command(c, "prioritize-outreach", inp, key="crash-key")
        assert ok.status_code == 200 and "Idempotent-Replay" not in ok.headers and count(conn, "outreach_events") == 4
        assert command(c, "prioritize-outreach", inp, key="crash-key").headers["Idempotent-Replay"] == "true" and count(conn, "outreach_events") == 4


@pytest.mark.parametrize("name,inp", [
    ("build-point-in-time-features", {"prediction_at": "2026-01-01T00:00:00Z", "fields": ["usage_events_30d\u0000"]}),
    ("fit-preprocessing", {"training_run_id": "tr-1\u0000"}), ("define-label", {"prediction_at": "2026-01-01T00:00:00Z\u0000"})])
def test_a_nul_character_is_refused_before_anything_is_written(client, conn, name, inp):
    prepare(conn, client, fixture("08"))
    digest = table_digest(conn, BUSINESS_TABLES)
    r = command(client, name, inp)
    assert r.status_code == 422 and table_digest(conn, BUSINESS_TABLES) == digest and count(conn, "audit_events") == 0
    assert any(x in rule_ids(r) for x in ("NUL_CHARACTER", "TIMESTAMP_INVALID"))


def test_hostile_identifiers_are_data_not_code(client, conn):
    prepare(conn, client, fixture("08"))
    n_accounts = count(conn, "accounts")
    evil = "x'; DROP TABLE accounts; --"
    r = command(client, "fit-preprocessing", {"training_run_id": evil})
    assert r.status_code == 404 and rule_ids(r) == ["UNKNOWN_TRAINING_RUN"] and count(conn, "accounts") == n_accounts
    r = command(client, "build-point-in-time-features", {"prediction_at": "2026-01-01T00:00:00Z", "fields": [evil, "=HYPERLINK(\"http://x\")"]})
    assert r.status_code == 422 and rule_ids(r) == ["UNKNOWN_FEATURE"] and [o["item"] for o in offending(r)] == [evil, "=HYPERLINK(\"http://x\")"]
    assert get(client, "/data/accounts", segment=evil).json()["data"] == [] and count(conn, "accounts") == n_accounts
    formula = "=cmd|' /C calc'!A0"
    c2 = command(client, "split-evaluation", {"training_run_id": formula, "train_end": "2025-06-01T00:00:00Z", "validation_end": "2025-10-01T00:00:00Z", "test_end": "2026-06-01T00:00:00Z"})
    assert c2.status_code == 200 and get(client, "/data/training_runs", training_run_id=formula).json()["data"][0]["training_run_id"] == formula        # stored and returned verbatim, never evaluated


def test_oversized_and_malformed_values_are_422(client, conn):
    prepare(conn, client, fixture("08"))
    base = {"prediction_at": "2026-01-01T00:00:00Z"}
    assert command(client, "define-label", {**base, "account_ids": list(range(5001))}).status_code == 422
    assert command(client, "define-label", {**base, "account_ids": [2**70]}).status_code in (200, 404, 422)
    assert command(client, "build-point-in-time-features", {**base, "fields": ["x" * 10_000]}).status_code == 422
    assert command(client, "define-label", base, key="k" * 129).status_code == 422
    assert command(client, "define-label", base, request_id="r" * 129).status_code == 422
    assert client.post("/api/v1/retentionlab/commands/define-label", headers={**SCIENTIST, "X-Actor-Id": "a" * 129},
                       json={"request_id": "r", "dataset_version": "d", "idempotency_key": "k", "input": base}).status_code == 401
    body = '{"request_id": "r", "dataset_version": "d", "idempotency_key": "k", "input": {"prediction_at": NaN}}'
    r = client.post("/api/v1/retentionlab/commands/define-label", content=body, headers={**SCIENTIST, "content-type": "application/json"})
    assert r.status_code == 422
    assert command(client, "train-baseline", {"training_run_id": "tr-1", "iterations": 10**9}).status_code == 422
    assert command(client, "train-baseline", {"training_run_id": "tr-1", "l2": "-1"}).status_code == 422
    assert command(client, "simulate-economics", {"training_run_id": "tr-1", "prediction_at": base["prediction_at"], "scenario": {"scenario_id": "s", "capacity": 0, "contact_cost": "1", "assumed_effect": "0.1", "margin_value": "1"}}).status_code == 422
    assert command(client, "simulate-economics", {"training_run_id": "tr-1", "prediction_at": base["prediction_at"], "scenario": {"scenario_id": "s", "capacity": 1, "contact_cost": "1e3", "assumed_effect": "0.1", "margin_value": "1"}}).status_code == 422


def test_a_role_cannot_borrow_another_roles_idempotency_record(client, conn):
    fx = fixture("10")
    prepare(conn, client, fx)
    inp = fx["recover"]["input"]
    assert command(client, "prioritize-outreach", inp, key="shared", headers=SCIENTIST).status_code == 200
    r = command(client, "prioritize-outreach", inp, key="shared", headers=ADMIN)
    assert r.status_code == 409 and rule_ids(r) == ["IDEMPOTENCY_ACTOR_MISMATCH"] and "command_id" not in r.text
    r = command(client, "prioritize-outreach", inp, key="shared", headers=ANALYST)
    assert r.status_code == 409


def test_an_analyst_can_queue_and_simulate_but_cannot_change_a_model(client, conn):
    fx = fixture("10")
    prepare(conn, client, fx)
    assert command(client, "prioritize-outreach", fx["recover"]["input"], headers=ANALYST).status_code == 200
    for name, inp in (("score-accounts", {"training_run_id": "tr-1", "prediction_at": "2025-10-01T00:00:00Z"}), ("calibrate-model", {"training_run_id": "tr-1"}),
                      ("train-baseline", {"training_run_id": "tr-1"}), ("fit-preprocessing", {"training_run_id": "tr-1"}), ("define-label", {"prediction_at": "2025-10-01T00:00:00Z"})):
        r = command(client, name, inp, headers=ANALYST)
        assert r.status_code == 403 and rule_ids(r) == ["ROLE_FORBIDDEN"], name


def test_concurrent_refusals_never_leave_a_partial_queue(client, conn):
    fx = fixture("10")
    prepare(conn, client, fx)
    digest = table_digest(conn, BUSINESS_TABLES)
    results: list = []

    def call(i):
        results.append(command(client, "prioritize-outreach", fx["detect"]["input"], key=f"par-{i}", headers=ANALYST))
    threads = [threading.Thread(target=call, args=(i,)) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert {r.status_code for r in results} == {422} and all(rule_ids(r) == ["CAPACITY_EXCEEDS_POPULATION"] for r in results)
    assert table_digest(conn, BUSINESS_TABLES) == digest and audit_count(conn, "prioritize-outreach-refused") == 5
