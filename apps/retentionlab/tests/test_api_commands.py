"""The ten commands end to end (API over PostgreSQL): envelope, identity, roles, validation, idempotency, server-stamped instants, locking and
the business results. Minimum request tests per command: valid, malformed, unknown resource, stale version, repeated command, unsupported action."""
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import psycopg
import pytest

from api import commands as cmds
from retentionlab.numbers import config_hash
from support_db import (ADMIN, ANALYST, BUSINESS_TABLES, SCIENTIST, SCIENTIST2, client, command, conn, count, current_dataset_version, db_url, get, golden_inputs,  # noqa: F401
                        load, metrics, offending, rule_ids, table_digest)
from worlds import READ_AS_OF, SETS, TRAIN_END, TEST_END, VALIDATION_END, build_world, pipeline

T0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
TEST_SET, NEW_SET = SETS["test"][0], SETS["new"][0]
SCENARIO = {"scenario_id": "sc-a", "capacity": 5, "contact_cost": "7.50", "assumed_effect": "0.250000", "margin_value": "321.99"}

#: command -> (a valid input after the pipeline ran, the roles that may call it)
SCIENTISTS, EVERYONE = {"scientist", "admin"}, {"scientist", "analyst", "admin"}
COMMANDS = {
    "build-point-in-time-features": ({"prediction_at": NEW_SET}, SCIENTISTS),
    "define-label": ({"prediction_at": NEW_SET}, SCIENTISTS),
    "split-evaluation": ({"training_run_id": "tr-w", "train_end": TRAIN_END, "validation_end": VALIDATION_END, "test_end": TEST_END}, SCIENTISTS),
    "fit-preprocessing": ({"training_run_id": "tr-x"}, SCIENTISTS),
    "train-baseline": ({"training_run_id": "tr-x"}, SCIENTISTS),
    "calibrate-model": ({"training_run_id": "tr-x"}, SCIENTISTS),
    "score-accounts": ({"training_run_id": "tr-w", "prediction_at": TEST_SET}, SCIENTISTS),
    "prioritize-outreach": ({"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": SCENARIO}, EVERYONE),
    "simulate-economics": ({"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": SCENARIO}, EVERYONE),
    "monitor-refresh": ({"training_run_id": "tr-w", "prediction_at": NEW_SET, "reference_prediction_at": TEST_SET}, SCIENTISTS),
}
HEADERS = {"scientist": SCIENTIST, "analyst": ANALYST, "admin": ADMIN}


@pytest.fixture
def lab(client, conn):
    """The synthetic world loaded, C01..C07 run: a fitted, calibrated, scored run 'tr-w' (test set and the immature new cohort scored)."""
    load(conn, build_world())
    out = pipeline(client, command)
    bad = [(k, r.status_code, r.text[:300]) for k, r in out.items() if r.status_code != 200]
    assert not bad, bad
    return client


@pytest.fixture
def bare(client, conn):
    load(conn, build_world())
    return client


# ---------------------------------------------------------------------------------------------------- identity and roles
@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_no_identity_is_401_and_a_blank_one_too(bare, name):
    body = {"request_id": "r", "dataset_version": current_dataset_version(), "idempotency_key": "k1", "input": COMMANDS[name][0]}
    assert bare.post(f"/api/v1/retentionlab/commands/{name}", json=body).status_code == 401
    assert bare.post(f"/api/v1/retentionlab/commands/{name}", json=body, headers={"X-Actor-Id": "  ", "X-Actor-Role": "admin"}).status_code == 401
    r = bare.post(f"/api/v1/retentionlab/commands/{name}", json=body)
    assert r.json()["error"]["code"] == "UNAUTHENTICATED" and rule_ids(r) == ["ACTOR_REQUIRED"] and r.json()["request_id"]


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_roles_403_before_the_body_is_read_and_each_role_gets_its_commands(bare, conn, name):
    inp, roles = COMMANDS[name]
    for role, headers in HEADERS.items():
        r = command(bare, name, {"definitely": "not valid"}, headers=headers)           # invalid body: a forbidden role is answered 403, an allowed one 422
        assert r.status_code == (422 if role in roles else 403), (name, role, r.text)
        if role not in roles:
            assert rule_ids(r) == ["ROLE_FORBIDDEN"]
    assert command(bare, name, inp, headers={"X-Actor-Id": "u", "X-Actor-Role": "root"}).status_code == 403
    assert command(bare, name, inp, headers={"X-Actor-Id": "u", "X-Actor-Role": "Admin"}).status_code == 403
    assert count(conn, "audit_events") == 0 and count(conn, "command_results") == 0   # nothing written by an unauthorised call


# ---------------------------------------------------------------------------------------------------- malformed, unknown, stale, unsupported
def test_malformed_requests_are_422_with_rule_ids_and_write_nothing(bare, conn):
    before = table_digest(conn, BUSINESS_TABLES)
    url = "/api/v1/retentionlab/commands/define-label"
    ok = {"request_id": "r", "dataset_version": current_dataset_version(), "idempotency_key": "k-m", "input": {"prediction_at": NEW_SET}}
    r = bare.post(url, content="{not json", headers={**SCIENTIST, "content-type": "application/json"})
    assert r.status_code == 422 and rule_ids(r) == ["BODY_INVALID_JSON"]
    cases = [({**ok, "input": {}}, "FIELD_REQUIRED"), ({**ok, "input": {"prediction_at": NEW_SET, "scored_at": "2026-01-01T00:00:00Z"}}, "FIELD_UNEXPECTED"),
             ({**ok, "input": {"prediction_at": "tomorrow"}}, "TIMESTAMP_INVALID"), ({**ok, "input": {"prediction_at": "2026-03-01T00:00:00"}}, "TIMESTAMP_INVALID"),
             ({**ok, "input": {"prediction_at": NEW_SET, "account_ids": ["1"]}}, "FIELD_INVALID"), ({**ok, "idempotency_key": "has space"}, "IDEMPOTENCY_KEY_INVALID"),
             ({**ok, "idempotency_key": 5}, "FIELD_INVALID"), ({k: v for k, v in ok.items() if k != "dataset_version"}, "FIELD_REQUIRED"),
             ({**ok, "extra": 1}, "FIELD_UNEXPECTED"), ({**ok, "input": [1]}, "FIELD_INVALID")]
    for body, rule in cases:
        r = bare.post(url, json=body, headers=SCIENTIST)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED" and rule in rule_ids(r), (body, r.text)
    assert table_digest(conn, BUSINESS_TABLES) == before and count(conn, "audit_events") == 0


def test_decimals_must_be_strings_never_numbers(bare):
    bad = {**SCENARIO, "contact_cost": 7.5}
    r = command(bare, "simulate-economics", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": bad})
    assert r.status_code == 422 and "FIELD_INVALID" in rule_ids(r)
    r = command(bare, "train-baseline", {"training_run_id": "tr-w", "l2": 1.0})
    assert r.status_code == 422
    r = command(bare, "train-baseline", {"training_run_id": "tr-w", "learning_rate": "0"})
    assert r.status_code == 422 and "DECIMAL_INVALID" in rule_ids(r)


@pytest.mark.parametrize("name,inp,rule", [
    ("build-point-in-time-features", {"prediction_at": "2030-01-01T00:00:00Z"}, "UNKNOWN_CUTOFF"),
    ("define-label", {"prediction_at": "2030-01-01T00:00:00Z"}, "UNKNOWN_CUTOFF"),
    ("fit-preprocessing", {"training_run_id": "tr-none"}, "UNKNOWN_TRAINING_RUN"), ("train-baseline", {"training_run_id": "tr-none"}, "UNKNOWN_TRAINING_RUN"),
    ("calibrate-model", {"training_run_id": "tr-none"}, "UNKNOWN_TRAINING_RUN"),
    ("score-accounts", {"training_run_id": "tr-none", "prediction_at": TEST_SET}, "UNKNOWN_TRAINING_RUN"),
    ("prioritize-outreach", {"training_run_id": "tr-none", "prediction_at": TEST_SET, "scenario_id": "sc"}, "UNKNOWN_TRAINING_RUN"),
    ("simulate-economics", {"training_run_id": "tr-none", "prediction_at": TEST_SET, "scenario_id": "sc"}, "UNKNOWN_TRAINING_RUN"),
    ("monitor-refresh", {"training_run_id": "tr-none", "prediction_at": NEW_SET, "reference_prediction_at": TEST_SET}, "UNKNOWN_TRAINING_RUN")])
def test_an_unknown_resource_is_404_with_its_rule_id(bare, conn, name, inp, rule):
    if name in ("prioritize-outreach", "simulate-economics", "monitor-refresh"):
        assert command(bare, "split-evaluation", {"training_run_id": "tr-w", "train_end": TRAIN_END, "validation_end": VALIDATION_END, "test_end": TEST_END}).status_code == 200
        if rule == "UNKNOWN_TRAINING_RUN":
            pass
    r = command(bare, name, inp)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND" and rule_ids(r) == [rule]


def test_unknown_scenario_cutoff_set_and_reference_are_404(lab):
    r = command(lab, "prioritize-outreach", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario_id": "sc-ghost"})
    assert (r.status_code, rule_ids(r)) == (404, ["UNKNOWN_SCENARIO"])
    r = command(lab, "simulate-economics", {"training_run_id": "tr-w", "prediction_at": "2030-01-01T00:00:00Z", "scenario": SCENARIO})
    assert (r.status_code, rule_ids(r)) == (404, ["UNKNOWN_CUTOFF"])
    r = command(lab, "monitor-refresh", {"training_run_id": "tr-w", "prediction_at": NEW_SET, "reference_prediction_at": "2030-01-01T00:00:00Z"})
    assert (r.status_code, rule_ids(r)) == (404, ["UNKNOWN_CUTOFF"])
    r = command(lab, "prioritize-outreach", {"training_run_id": "tr-w", "prediction_at": TEST_SET})
    assert (r.status_code, rule_ids(r)) == (422, ["SCENARIO_INVALID"])


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_a_stale_dataset_version_is_409_and_nothing_is_written(bare, conn, name):
    before = table_digest(conn, BUSINESS_TABLES)
    audits = count(conn, "audit_events")
    inp = COMMANDS[name][0]
    inp = {**inp, "training_run_id": "tr-w"} if "training_run_id" in inp else inp
    r = command(bare, name, inp, dataset_version="ds-an-older-one", headers=HEADERS["scientist"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_DATASET_VERSION" and rule_ids(r) == ["STALE_DATASET_VERSION"]
    ctx = r.json()["error"]["details"][0]["context"]
    assert ctx["requested"] == "ds-an-older-one" and ctx["current"] == current_dataset_version()
    assert table_digest(conn, BUSINESS_TABLES) == before and count(conn, "audit_events") == audits


def test_an_unsupported_action_is_404_and_needs_an_actor(bare):
    r = command(bare, "send-email-to-everyone", {})
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNSUPPORTED_ACTION" and rule_ids(r) == ["UNSUPPORTED_ACTION"]
    assert command(bare, "send-email-to-everyone", {}, headers={"X-Actor-Id": "", "X-Actor-Role": "admin"}).status_code == 401
    assert bare.get("/api/v1/retentionlab/commands/define-label").status_code == 405                    # commands are POST only
    assert bare.post("/api/v1/retentionlab/nonsense").status_code == 404


# ---------------------------------------------------------------------------------------------------- the pipeline, step by step
def test_pipeline_results_are_the_business_values_not_just_statuses(client, conn):
    load(conn, build_world())
    out = pipeline(client, command)
    assert {k: r.status_code for k, r in out.items()} == {k: 200 for k in out}
    f = out[f"features:{SETS['test'][0]}"].json()
    assert f["status"] == "built" and f["result"]["eligible"] == 28 and f["result"]["availability_proof"] == {"checked": 28, "all_before_cutoff": True}
    new = out[f"features:{NEW_SET}"].json()["result"]
    assert (new["cutoff_rows"], new["eligible"], new["ineligible"]) == (24, 15, {"NOT_ACTIVE": 9})            # 9 test-range churners cancelled before 2026-03-01
    lab = out[f"label:{NEW_SET}"].json()["result"]
    assert (lab["censored"], lab["mature"], lab["churn_rate"], lab["churned"]) == (15, 0, None, 0)            # censored: null, never 0, never non-churn
    assert out[f"label:{NEW_SET}"].json()["warnings"][0]["code"] == "CENSORED_ROWS"
    split = out["split"].json()["result"]
    assert split["embargo_days"] == 104 and split["counts"]["train"] == {"total": 52, "retained": 48, "label_window": 0, "group_test": 4, "group_validation": 0}
    assert split["counts"]["validation"]["retained"] == 12 and split["counts"]["test"]["retained"] == 28 + 24             # 24 test accounts x 2 sets + the 4 mixed accounts' test row
    pre = out["preprocessing"].json()["result"]
    assert pre["fit_rows"] == 48 and pre["fitted_on"] == "retained training rows only"
    tr = out["train"].json()["result"]
    assert tr["training_rows"] == 48 and [m["name"] for m in tr["models"]] == ["random_baseline", "business_rule", "logistic_regression", "prevalence_baseline"]
    assert tr["models"][3] == {"name": "prevalence_baseline", "prevalence": tr["models"][3]["prevalence"]} and re.fullmatch(r"\d\.\d{6}", tr["models"][3]["prevalence"])     # D-09 R10-14
    assert tr["models"][0] == {"name": "random_baseline", "seed": 7} and all(isinstance(v, str) for v in tr["models"][2]["coefficients"].values())
    assert out["train"].json()["warnings"][0]["code"] == "VALIDATION_ONLY"
    cal = out["calibrate"].json()["result"]
    assert cal["fit_rows"] == 12 and cal["test_rows_read"] == 0 and cal["evaluation_rows_overlap_fit_rows"] == 0
    s = out[f"score:{TEST_SET}"].json()["result"]
    assert (s["status"], s["eligible"], s["scored"], s["new"], s["calibrated"], s["run_frozen"]) == ("completed", 28, 28, 28, True, True)
    run = conn.execute("SELECT * FROM training_runs").fetchone()
    assert s["citations"] == {"training_run_id": "tr-w", "config_hash": run["config_hash"], "feature_version": "fv-1", "label_version": "lv-1", "model": "logistic_regression"}
    assert all(p["config_hash"] == run["config_hash"] and p["feature_version"] == "fv-1" and p["label_version"] == "lv-1" for p in s["predictions"])


def test_the_config_hash_is_the_sha256_of_the_canonical_config_and_the_artefact_tables_agree_with_it(lab, conn):
    run = conn.execute("SELECT * FROM training_runs").fetchone()
    assert run["config_hash"] == config_hash(run["config"]) and set(run["config"]) == {"feature_version", "label_version", "seed", "split", "models", "preprocessing", "calibration"}
    coefs = {r["term"]: r["value"] for r in conn.execute("SELECT term, value FROM model_coefficients WHERE model_name = 'logistic_regression'").fetchall()}
    cfg = {m["name"]: m for m in run["config"]["models"]}["logistic_regression"]["coefficients"]
    assert {k: format(v, "f") for k, v in coefs.items()} == cfg                                           # NUMERIC(20,6) round-trips the frozen string
    cal = conn.execute("SELECT * FROM calibration_maps").fetchone()
    assert (format(cal["a"], "f"), format(cal["b"], "f")) == (run["config"]["calibration"]["a"], run["config"]["calibration"]["b"])
    pre = {r["feature_name"]: r for r in conn.execute("SELECT * FROM model_preprocessing").fetchall()}
    assert {k: format(v["mean"], "f") for k, v in pre.items()} == {k: v["mean"] for k, v in run["config"]["preprocessing"]["features"].items()}


def test_a_training_run_is_deterministic_two_fits_freeze_the_same_strings(client, conn):
    outs = []
    for run_id in ("tr-1", "tr-2"):
        load(conn, build_world()) if run_id == "tr-1" else None
        for pa in [p for ps in SETS.values() for p in ps] if run_id == "tr-1" else []:
            assert command(client, "build-point-in-time-features", {"prediction_at": pa}).status_code == 200
            assert command(client, "define-label", {"prediction_at": pa}).status_code == 200
        assert command(client, "split-evaluation", {"training_run_id": run_id, "train_end": TRAIN_END, "validation_end": VALIDATION_END, "test_end": TEST_END}).status_code == 200
        assert command(client, "fit-preprocessing", {"training_run_id": run_id}).status_code == 200
        r = command(client, "train-baseline", {"training_run_id": run_id})
        assert r.status_code == 200
        outs.append(r.json()["result"]["models"])
    assert json.dumps(outs[0], sort_keys=True) == json.dumps(outs[1], sort_keys=True)


def test_scoring_publishes_completed_only_when_every_eligible_account_has_a_prediction(lab, conn):
    pubs = {p["publication_id"]: p for p in get(lab, "/data/scoring_publications").json()["data"]}
    assert {p["status"] for p in pubs.values()} == {"completed"} and count(conn, "predictions") == 28 + 15
    cs = metrics(lab, training_run_id="tr-w", as_of=READ_AS_OF)["data"]
    assert [p["status"] for p in cs["scoring_publications"]] == ["completed", "completed"]
    assert cs["consistency"] == {k: [] for k in cs["consistency"]}                                          # stored rows equal the rebuilt ones
    assert cs["freshness"]["latest_completed_publication_id"] == "sp-tr-w-logistic_regression-20260301-1"
    again = command(lab, "score-accounts", {"training_run_id": "tr-w", "prediction_at": TEST_SET})
    assert again.status_code == 200 and again.json()["status"] == "unchanged" and again.json()["result"]["new"] == 0 and again.json()["result"]["already_scored"] == 28
    assert count(conn, "predictions") == 43 and count(conn, "scoring_publications") == 2                      # no new publication for an unchanged set


def test_an_incomplete_publication_is_reported_incomplete_and_its_freshness_not_counted(client, conn):
    load(conn, build_world())
    for pa in [p for ps in SETS.values() for p in ps]:
        assert command(client, "build-point-in-time-features", {"prediction_at": pa}).status_code == 200
        assert command(client, "define-label", {"prediction_at": pa}).status_code == 200
    for cmd, inp in (("split-evaluation", {"training_run_id": "tr-w", "train_end": TRAIN_END, "validation_end": VALIDATION_END, "test_end": TEST_END}),
                     ("fit-preprocessing", {"training_run_id": "tr-w"}), ("train-baseline", {"training_run_id": "tr-w"})):
        assert command(client, cmd, inp).status_code == 200
    # one eligible account has no stored feature row -> scoring refuses the set (never a partial silent publication)
    conn.execute("SELECT 1")
    victim = conn.execute("SELECT cutoff_id FROM feature_rows WHERE cutoff_id LIKE '%20251001' ORDER BY cutoff_id LIMIT 1").fetchone()["cutoff_id"]
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("DELETE FROM feature_rows WHERE cutoff_id = %s", (victim,))                              # append-only: cannot be removed
    r = command(client, "score-accounts", {"training_run_id": "tr-w", "prediction_at": "2025-10-01T00:00:00Z", "model": "business_rule"})
    assert r.status_code == 200 and r.json()["result"]["status"] == "completed"
    assert command(client, "score-accounts", {"training_run_id": "tr-w", "prediction_at": "2025-10-01T00:00:00Z", "model": "nope"}).status_code == 422


def test_scoring_before_features_are_built_is_refused_with_the_missing_cutoffs(client, conn):
    load(conn, build_world())
    assert command(client, "split-evaluation", {"training_run_id": "tr-w", "train_end": TRAIN_END, "validation_end": VALIDATION_END, "test_end": TEST_END}).status_code == 200
    r = command(client, "fit-preprocessing", {"training_run_id": "tr-w"})
    assert r.status_code == 422 and rule_ids(r) == ["NO_TRAINING_ROWS"]
    r = command(client, "train-baseline", {"training_run_id": "tr-w"})
    assert r.status_code == 422 and rule_ids(r) == ["PREPROCESSING_REQUIRED"]
    r = command(client, "calibrate-model", {"training_run_id": "tr-w"})
    assert r.status_code == 422 and rule_ids(r) == ["MODEL_NOT_FITTED"]
    r = command(client, "score-accounts", {"training_run_id": "tr-w", "prediction_at": TEST_SET})
    assert r.status_code == 422 and rule_ids(r) == ["MODEL_NOT_FITTED"]


def test_splitting_again_is_idempotent_and_other_boundaries_are_a_new_run_not_an_edit(lab, conn):
    inp = {"training_run_id": "tr-w", "train_end": TRAIN_END, "validation_end": VALIDATION_END, "test_end": TEST_END}
    r = command(lab, "split-evaluation", inp)
    assert r.status_code == 200 and r.json()["status"] == "unchanged" and r.json()["result"]["created"] is False and r.json()["result"]["assignments_inserted"] == 0
    r = command(lab, "split-evaluation", {**inp, "train_end": "2025-05-01T00:00:00Z"})
    assert r.status_code == 409 and rule_ids(r) == ["TRAINING_RUN_EXISTS"]
    r = command(lab, "split-evaluation", {**inp, "training_run_id": "tr-2", "train_end": "2025-05-01T00:00:00Z"})
    assert r.status_code == 200 and r.json()["result"]["created"] is True and count(conn, "training_runs") == 2
    r = command(lab, "split-evaluation", {**inp, "training_run_id": "tr-3", "validation_end": TRAIN_END})
    assert r.status_code == 422 and rule_ids(r) == ["SPLIT_ORDER_INVALID"]
    r = command(lab, "split-evaluation", {**inp, "training_run_id": "tr-3", "feature_version": "fv-9"})
    assert r.status_code == 422 and rule_ids(r) == ["UNKNOWN_VERSION"]


def test_a_scored_run_never_changes_its_configuration(lab, conn):
    before = table_digest(conn, ["training_runs", "model_preprocessing", "model_coefficients", "calibration_maps"])
    for cmd in ("fit-preprocessing", "train-baseline", "calibrate-model"):
        r = command(lab, cmd, {"training_run_id": "tr-w"})
        assert r.status_code == 409 and rule_ids(r) == ["RUN_FROZEN"], cmd
    assert table_digest(conn, ["training_runs", "model_preprocessing", "model_coefficients", "calibration_maps"]) == before


def test_features_and_labels_are_built_once_and_replayed_without_duplicates(lab, conn):
    n_f, n_l = count(conn, "feature_rows"), count(conn, "labels")
    r = command(lab, "build-point-in-time-features", {"prediction_at": TEST_SET})
    assert r.status_code == 200 and r.json()["status"] == "unchanged" and (r.json()["result"]["built"], r.json()["result"]["unchanged"]) == (0, 28)
    r = command(lab, "define-label", {"prediction_at": TEST_SET})
    assert r.status_code == 200 and r.json()["status"] == "unchanged" and r.json()["result"]["unchanged"] == 28
    assert (count(conn, "feature_rows"), count(conn, "labels")) == (n_f, n_l)


def test_a_censored_label_matures_when_the_clock_passes_its_label_end_exactly_once(lab, conn):
    from api import clock
    assert count(conn, "labels", "mature = false") == 15 and count(conn, "labels", "churned IS NULL") == 15
    clock.freeze(datetime(2026, 6, 14, tzinfo=timezone.utc))                                       # 2026-03-01 + 104 d = 2026-06-13
    r = command(lab, "define-label", {"prediction_at": NEW_SET})
    res = r.json()["result"]
    assert r.status_code == 200 and res["matured_now"] == 15 and res["mature"] == 15 and res["censored"] == 0 and res["churn_rate"] is not None
    assert count(conn, "labels", "mature = false") == 0 and count(conn, "labels", "churned IS NULL") == 0
    r2 = command(lab, "define-label", {"prediction_at": NEW_SET})
    assert r2.json()["result"]["matured_now"] == 0 and r2.json()["result"]["unchanged"] == 15


# ---------------------------------------------------------------------------------------------------- idempotency (actor, role, dataset_version in the binding)
def test_a_repeated_command_returns_the_stored_response_without_new_side_effects(lab, conn):
    inp = {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": {**SCENARIO, "scenario_id": "sc-rep"}}
    first = command(lab, "prioritize-outreach", inp, key="same-key", headers=ANALYST)
    audits, digest = count(conn, "audit_events"), table_digest(conn, BUSINESS_TABLES)
    again = command(lab, "prioritize-outreach", inp, key="same-key", headers=ANALYST, request_id="a-different-request-id")
    assert first.status_code == again.status_code == 200 and again.headers["Idempotent-Replay"] == "true" and "Idempotent-Replay" not in first.headers
    assert again.json() == first.json() and again.json()["command_id"] == first.json()["command_id"]
    assert count(conn, "audit_events") == audits and table_digest(conn, BUSINESS_TABLES) == digest and count(conn, "outreach_events", "scenario_id = 'sc-rep'") == 5


def test_the_same_key_with_another_payload_actor_role_or_dataset_version_is_409(lab, conn):
    inp = {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": {**SCENARIO, "scenario_id": "sc-k"}}
    assert command(lab, "simulate-economics", inp, key="k-one", headers=SCIENTIST).status_code == 200
    r = command(lab, "simulate-economics", {**inp, "model": "business_rule"}, key="k-one", headers=SCIENTIST)
    assert (r.status_code, rule_ids(r)) == (409, ["IDEMPOTENCY_PAYLOAD_MISMATCH"]) and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    r = command(lab, "simulate-economics", inp, key="k-one", headers=SCIENTIST2)                      # another actor
    assert (r.status_code, rule_ids(r)) == (409, ["IDEMPOTENCY_ACTOR_MISMATCH"])
    r = command(lab, "simulate-economics", inp, key="k-one", headers={"X-Actor-Id": SCIENTIST["X-Actor-Id"], "X-Actor-Role": "admin"})     # the same actor, another role
    assert (r.status_code, rule_ids(r)) == (409, ["IDEMPOTENCY_ACTOR_MISMATCH"])
    r = command(lab, "simulate-economics", inp, key="k-one", headers=SCIENTIST, dataset_version="ds-other")                                 # another dataset_version
    assert (r.status_code, rule_ids(r)) == (409, ["IDEMPOTENCY_PAYLOAD_MISMATCH"])
    assert command(lab, "simulate-economics", inp, key="k-one", headers=SCIENTIST).headers["Idempotent-Replay"] == "true"
    r = command(lab, "simulate-economics", inp, key="k-one", headers=ANALYST)
    assert r.status_code == 409                                                                          # a different analyst-role actor is refused too, not served the stored body
    assert count(conn, "command_results", "idempotency_key = 'k-one'") == 1


def test_instants_in_a_payload_are_hashed_as_the_instant_they_name(lab):
    base = {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": {**SCENARIO, "scenario_id": "sc-z"}}
    assert command(lab, "simulate-economics", base, key="k-z").status_code == 200
    r = command(lab, "simulate-economics", {**base, "prediction_at": "2025-10-01T02:00:00+02:00"}, key="k-z")      # the same instant in another zone
    assert r.status_code == 200 and r.headers["Idempotent-Replay"] == "true"


# ---------------------------------------------------------------------------------------------------- server-stamped instants
def test_decision_instants_come_from_the_server_clock_never_the_client(lab, conn):
    run = conn.execute("SELECT created_at, created_by FROM training_runs").fetchone()
    assert T0 <= run["created_at"] < datetime(2026, 5, 1, 12, 1, tzinfo=timezone.utc) and run["created_by"] == SCIENTIST["X-Actor-Id"]
    scored = [r["scored_at"] for r in conn.execute("SELECT scored_at FROM predictions").fetchall()]
    pubs = [r["published_at"] for r in conn.execute("SELECT published_at FROM scoring_publications").fetchall()]
    assert all(T0 <= t < datetime(2026, 5, 1, 12, 1, tzinfo=timezone.utc) for t in scored + pubs)
    for name, inp in (("score-accounts", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scored_at": "2020-01-01T00:00:00Z"}),
                      ("split-evaluation", {**COMMANDS["split-evaluation"][0], "training_run_id": "tr-q", "created_at": "2020-01-01T00:00:00Z"}),
                      ("simulate-economics", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": SCENARIO, "published_at": "2020-01-01T00:00:00Z"}),
                      ("prioritize-outreach", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": SCENARIO, "created_at": "2020-01-01T00:00:00Z"})):
        r = command(lab, name, inp)
        assert r.status_code == 422 and "FIELD_UNEXPECTED" in rule_ids(r), name
    from api import clock
    clock.freeze(datetime(2031, 1, 2, 3, 4, 5, tzinfo=timezone.utc), step=timedelta(0))
    assert command(lab, "split-evaluation", {**COMMANDS["split-evaluation"][0], "training_run_id": "tr-later"}).status_code == 200
    assert conn.execute("SELECT created_at FROM training_runs WHERE training_run_id = 'tr-later'").fetchone()["created_at"] == datetime(2031, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert get(lab, "/data/training_runs", training_run_id="tr-later").json()["data"][0]["created_at"] == "2031-01-02T03:04:05Z"


# ---------------------------------------------------------------------------------------------------- C08 / C09
def test_the_outreach_queue_is_a_capacity_limited_draft_queue_and_nothing_is_sent(lab, conn):
    r = command(lab, "prioritize-outreach", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": SCENARIO}, headers=ANALYST)
    assert r.status_code == 200
    res = r.json()["result"]
    assert (res["capacity"], res["population"], res["queue_status"], res["sent"], res["treatment_effect_estimate"]) == (5, 28, "draft", 0, None)
    assert [q["rank"] for q in res["queue"]] == [1, 2, 3, 4, 5] and {q["status"] for q in res["queue"]} == {"draft"}
    probs = [Fraction(q["probability"]) for q in res["queue"]]
    assert probs == sorted(probs, reverse=True)                                                         # highest risk first
    top = conn.execute("SELECT account_id FROM predictions p JOIN prediction_cutoffs c USING (cutoff_id) WHERE p.prediction_id LIKE 'pr-%%20251001' "
                       "ORDER BY p.probability DESC, c.account_id ASC LIMIT 5").fetchall()
    assert [q["account_id"] for q in res["queue"]] == [t["account_id"] for t in top]
    rows = conn.execute("SELECT * FROM outreach_events WHERE scenario_id = 'sc-a' ORDER BY queue_rank").fetchall()
    assert [r["status"] for r in rows] == ["draft"] * 5 and {r["action"] for r in rows} == {"propose_contact"} and rows[0]["training_run_id"] == "tr-w"
    assert {w["code"] for w in r.json()["warnings"]} == {"RISK_IS_NOT_RESPONSIVENESS", "DRAFT_ONLY"}
    assert count(conn, "outreach_events", "status <> 'draft'") == 0
    routes = {getattr(x, "path", "") for x in lab.app.routes}
    assert not any("send" in p for p in routes)                                                          # the product has no sending route at all


def test_a_second_queue_for_one_scenario_is_a_conflict_and_a_changed_scenario_is_a_new_id(lab, conn):
    inp = {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": SCENARIO}
    assert command(lab, "prioritize-outreach", inp).status_code == 200
    r = command(lab, "prioritize-outreach", inp)
    assert r.status_code == 409 and rule_ids(r) == ["QUEUE_EXISTS"] and count(conn, "outreach_events") == 5
    r = command(lab, "prioritize-outreach", {**inp, "scenario": {**SCENARIO, "capacity": 6}})
    assert r.status_code == 409 and rule_ids(r) == ["SCENARIO_IMMUTABLE"]                                    # same id, other assumptions
    assert command(lab, "prioritize-outreach", {**inp, "scenario": {**SCENARIO, "scenario_id": "sc-b", "capacity": 6}}).status_code == 200
    assert count(conn, "outreach_events") == 11 and count(conn, "intervention_scenarios") == 2


def test_economics_are_hypothetical_assumption_based_and_exact(lab):
    r = command(lab, "simulate-economics", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": SCENARIO, "experiment_id": "exp-1"}, headers=ANALYST)
    assert r.status_code == 200
    res = r.json()["result"]
    assert (res["label"], res["assumption_based"], res["treatment_effect_estimate"], res["supported_by_randomised_experiment"]) == ("hypothetical", True, None, False)
    assert res["contact_budget"] == "37.50" and res["assumptions"] == {"contact_cost": "7.50", "assumed_effect": "0.250000", "margin_value": "321.99"}
    queue = get(lab, "/metrics", training_run_id="tr-w", prediction_at=TEST_SET, scenario_id="sc-a", as_of=READ_AS_OF).json()["data"]["cutoff_sets"][TEST_SET]
    assert res["expected_value"] == queue["economics"]["expected_value"] and res["selected_account_ids"] == queue["economics"]["selected_account_ids"]
    total = sum(Fraction(t["value_exact"]) for t in res["terms"])
    assert abs(total - Fraction(res["expected_value"])) <= Fraction(1, 200) + Fraction(5, 10**6)
    assert r.json()["warnings"][0]["code"] == "HYPOTHETICAL" and "randomised experiment" in res["disclosure"]


def test_an_assumed_effect_outside_zero_one_is_refused(lab, conn):
    r = command(lab, "simulate-economics", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": {**SCENARIO, "assumed_effect": "1.500000"}})
    assert r.status_code == 422 and rule_ids(r) == ["ASSUMED_EFFECT_OUT_OF_RANGE"] and count(conn, "intervention_scenarios") == 0
    assert command(lab, "simulate-economics", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": {**SCENARIO, "assumed_effect": "1.000000"}}).status_code == 200


def test_capacity_above_the_scored_population_is_refused_by_both_scenario_commands(lab, conn):
    big = {**SCENARIO, "scenario_id": "sc-big", "capacity": 29}
    for name in ("prioritize-outreach", "simulate-economics"):
        r = command(lab, name, {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": big})
        assert r.status_code == 422 and rule_ids(r) == ["CAPACITY_EXCEEDS_POPULATION"] and offending(r) == [{"item": "sc-big", "code": "CAPACITY_29_GT_28"}]
    assert count(conn, "outreach_events") == 0
    assert command(lab, "simulate-economics", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": {**big, "capacity": 28}}).status_code == 200


# ---------------------------------------------------------------------------------------------------- C10
def test_monitor_refresh_counts_immature_labels_and_reports_drift_as_a_diagnostic(lab):
    r = command(lab, "monitor-refresh", {"training_run_id": "tr-w", "prediction_at": NEW_SET, "reference_prediction_at": TEST_SET})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["immature"] == 15 and res["performance_reported"] is False and res["performance"] is None          # labels may arrive later: no performance yet
    assert res["population"]["eligible"] == 15 and res["population"]["censored"] == 15 and res["population"]["scored"] == 15
    d = res["population_drift"]
    assert d["diagnostic_only"] is True and d["threshold"] == "0.200000" and d["reference_rows"] == 28 and d["current_rows"] == 15 and len(d["bins"]) == 3
    assert {w["code"] for w in r.json()["warnings"]} >= {"LABELS_PENDING"}
    mature = command(lab, "monitor-refresh", {"training_run_id": "tr-w", "prediction_at": TEST_SET, "reference_prediction_at": NEW_SET})
    perf = mature.json()["result"]
    assert perf["performance_reported"] is True and perf["performance"]["n"] == 28 and perf["immature"] == 0
    assert perf["performance"]["average_precision"]["value"] is not None and perf["freshness"]["scoring_hours"] is not None


def test_monitor_refresh_validates_its_bins_and_feature(lab):
    base = {"training_run_id": "tr-w", "prediction_at": NEW_SET, "reference_prediction_at": TEST_SET}
    r = command(lab, "monitor-refresh", {**base, "feature": "cancellation_reason"})
    assert r.status_code == 422 and rule_ids(r) == ["UNKNOWN_FEATURE"]
    r = command(lab, "monitor-refresh", {**base, "bins": [{"label": "x", "lower": "abc", "upper": None}]})
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_BINS"]
    r = command(lab, "monitor-refresh", {**base, "feature": "days_since_last_usage", "bins": [{"label": "<7", "lower": 0, "upper": 7}, {"label": "7+", "lower": 7, "upper": None}]})
    assert r.status_code == 200 and [b["label"] for b in r.json()["result"]["population_drift"]["bins"]] == ["<7", "7+"]


# ---------------------------------------------------------------------------------------------------- audit
def test_every_accepted_command_leaves_one_audit_event_with_actor_role_and_request_id(lab, conn):
    rows = conn.execute("SELECT * FROM audit_events ORDER BY occurred_at, event_id").fetchall()
    actions = [r["action"] for r in rows]
    assert actions.count("build-point-in-time-features") == 5 and actions.count("define-label") == 5 and actions.count("split-evaluation") == 1
    assert actions.count("score-accounts") == 2 and "calibrate-model" in actions and "train-baseline" in actions and "fit-preprocessing" in actions
    assert all(r["actor_id"] == SCIENTIST["X-Actor-Id"] and r["actor_role"] == "scientist" and r["request_id"] == "req-test" for r in rows)
    assert count(conn, "command_results") == len(rows)                                                  # one stored result per command
    assert "secret" not in json.dumps([r["details"] for r in rows]).lower() and "postgres" not in json.dumps([r["details"] for r in rows]).lower()


# ---------------------------------------------------------------------------------------------------- locking and retries
def test_a_deadlock_is_retried_three_times_then_409_concurrent_update(lab, conn, monkeypatch):
    attempts = []

    def deadlocked(conn_, req, actor):
        attempts.append(1)
        raise psycopg.errors.DeadlockDetected("deadlock detected")
    monkeypatch.setattr(cmds, "define_label", deadlocked)
    from api import app as appmod
    client = lab
    monkeypatch.setattr(cmds.random, "uniform", lambda a, b: 0.0)                                         # no waiting in the test
    # the route captured the handler at app creation: build a fresh app around the patched one
    from fastapi.testclient import TestClient
    with TestClient(appmod.create_app(), raise_server_exceptions=False) as c:
        r = command(c, "define-label", {"prediction_at": NEW_SET})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONCURRENT_UPDATE" and rule_ids(r) == ["CONCURRENT_UPDATE"]
    assert len(attempts) == 3 == cmds.MAX_ATTEMPTS
    assert count(conn, "command_results") == count(conn, "audit_events")                                   # nothing of the failed attempts was committed


def test_a_single_deadlock_is_retried_and_the_command_succeeds(lab, conn, monkeypatch):
    real = cmds.define_label
    attempts = []

    def flaky(conn_, req, actor):
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.errors.SerializationFailure("could not serialize access")
        return real(conn_, req, actor)
    monkeypatch.setattr(cmds, "define_label", flaky)
    monkeypatch.setattr(cmds.random, "uniform", lambda a, b: 0.0)
    from fastapi.testclient import TestClient
    from api import app as appmod
    with TestClient(appmod.create_app(), raise_server_exceptions=False) as c:
        r = command(c, "define-label", {"prediction_at": NEW_SET})
    assert r.status_code == 200 and len(attempts) == 2 and r.json()["status"] == "unchanged"


def test_two_concurrent_identical_requests_run_once(lab, conn):
    inp = {"training_run_id": "tr-w", "prediction_at": TEST_SET, "scenario": {**SCENARIO, "scenario_id": "sc-par"}}
    results: list = []

    def call():
        results.append(command(lab, "prioritize-outreach", inp, key="par-key", headers=ANALYST))
    threads = [threading.Thread(target=call) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.status_code for r in results) == [200] * 6
    assert len({r.json()["command_id"] for r in results}) == 1 and sum(1 for r in results if r.headers.get("Idempotent-Replay")) == 5
    assert count(conn, "outreach_events", "scenario_id = 'sc-par'") == 5 and count(conn, "command_results", "idempotency_key = 'par-key'") == 1


def test_concurrent_scoring_with_different_keys_scores_each_account_once(client, conn):
    load(conn, build_world())
    out = pipeline(client, command, score_sets=())
    assert all(r.status_code == 200 for r in out.values())
    results: list = []

    def call(i):
        results.append(command(client, "score-accounts", {"training_run_id": "tr-w", "prediction_at": TEST_SET}, key=f"score-{i}"))
    threads = [threading.Thread(target=call, args=(i,)) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.status_code for r in results) == [200] * 5 and sorted(r.json()["status"] for r in results) == ["scored"] + ["unchanged"] * 4
    assert count(conn, "predictions") == 28 and count(conn, "scoring_publications") == 1


def test_concurrent_splits_of_one_new_run_create_it_once(client, conn):
    load(conn, build_world())
    results: list = []

    def call(i):
        results.append(command(client, "split-evaluation", {"training_run_id": "tr-par", "train_end": TRAIN_END, "validation_end": VALIDATION_END,
                                                            "test_end": TEST_END}, key=f"split-{i}"))
    threads = [threading.Thread(target=call, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.status_code for r in results) == [200] * 4 and sorted(r.json()["result"]["created"] for r in results) == [False, False, False, True]
    assert count(conn, "training_runs") == 1 and count(conn, "split_assignments") == 116


def test_the_response_of_every_command_carries_the_documented_envelope(lab):
    for name, (inp, roles) in COMMANDS.items():
        if "training_run_id" in inp:
            inp = {**inp, "training_run_id": "tr-w"}
        inp = {**inp, "scenario": {**SCENARIO, "scenario_id": f"sc-{name}"}} if "scenario" in inp else inp
        r = command(lab, name, inp, headers=HEADERS[sorted(roles)[0]])
        body = r.json()
        if r.status_code == 200:
            assert set(body) == {"command_id", "status", "result", "warnings", "version"} and body["command_id"].startswith("cmd-") and body["version"] == 1
        else:
            assert set(body) == {"error", "request_id"} and set(body["error"]) == {"code", "message", "details"}, (name, body)
            assert "Traceback" not in r.text and "postgresql" not in r.text.lower()


# ---------------------------------------------------------------------------------------------------- the route inventory
def test_the_route_inventory_of_the_docs_is_exactly_the_generated_openapi(client):
    import re
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[1] / "docs" / "api-contract.md").read_text()
    inventory = re.findall(r"\| (C\d\d) \| POST …/commands/([a-z-]+) \|", doc)
    assert [c for c, _ in inventory] == [f"C{n:02d}" for n in range(1, 11)]
    spec = client.get("/api/v1/retentionlab/openapi.json").json()
    posted = {p.rsplit("/", 1)[-1] for p, ops in spec["paths"].items() if "/commands/" in p and "post" in ops}
    assert posted == {name for _, name in inventory} == set(COMMANDS)
    assert "/api/v1/retentionlab/data/{entity}" in spec["paths"] and "/api/v1/retentionlab/metrics" in spec["paths"]
    assert "Roles: C01–C07, C10 scientist, admin; C08, C09 scientist, analyst, admin." in doc
    assert {n for n, (_, roles) in COMMANDS.items() if roles == SCIENTISTS} == {name for c, name in inventory if c not in ("C08", "C09")}
    assert {n for n, (_, roles) in COMMANDS.items() if roles == EVERYONE} == {name for c, name in inventory if c in ("C08", "C09")}
