"""Fixes adopted from review R10 (docs/contracts.md D-09): each defect is DETECTED (the case the reviewer ran) and RECOVERED (the behaviour that replaces it).

R10-01 a future as_of / a stored censored label; R10-14 the prevalence-constant baseline; R10-15 a duplicated feature field.
The generator-level items (economics on the full world, the permutation invariance of the fit, the disclosures) are in test_generator.py."""
import copy
import re
from fractions import Fraction

import pytest

from retentionlab import errors as E
from retentionlab import evaluate
from retentionlab.errors import DomainError
from retentionlab.fitting import fit_prevalence, score_features, train_models
from retentionlab.rules import check_as_of, check_feature_request
from retentionlab.timeutil import parse_ts

from mini import Mini
from support_db import FEB, JAN, client, command, conn, db_url, get, golden_inputs, load, metrics, rule_ids  # noqa: F401
from test_fitting import TEST, TRAIN, evaluate_models, fit_all
from worlds import build_world, pipeline

REVIEWER_SET = "2026-03-01T00:00:00Z"            # the reviewer's case: server clock 2026-05-01T12:00Z, the 2026-03-01 set (label_end 2026-06-13), as_of 2026-07-01
REVIEWER_AS_OF = "2026-07-01T00:00:00Z"


# ---- R10-01 -------------------------------------------------------------------------------------------------------------------------
def test_detect_a_report_as_of_later_than_the_server_clock_is_refused(client, conn):
    load(conn, build_world())
    pipeline(client, command)
    r = get(client, "/metrics", _server_clock=True, prediction_at=REVIEWER_SET, as_of=REVIEWER_AS_OF)
    assert r.status_code == 422 and rule_ids(r) == [E.AS_OF_IN_FUTURE]
    assert r.json()["error"]["details"][0]["context"]["offending"] == [{"item": "as_of", "code": "AS_OF_IN_FUTURE"}]


def test_recover_the_same_set_read_at_the_server_clock_is_censored_and_consistent(client, conn):
    load(conn, build_world())
    pipeline(client, command)
    now = metrics(client, prediction_at=REVIEWER_SET)["data"]                                  # as_of defaults to the server clock
    s = now["cutoff_sets"][REVIEWER_SET]
    stored = conn.execute("SELECT count(*) n, count(*) FILTER (WHERE mature) m FROM labels l JOIN prediction_cutoffs c USING (cutoff_id) "
                          "WHERE c.prediction_at = %s", (REVIEWER_SET,)).fetchone()
    assert stored["n"] > 0 and stored["m"] == 0                                                 # the stored labels are censored ...
    assert s["population"]["mature"] == 0 and s["population"]["censored"] == s["population"]["eligible"] > 0      # ... and so is the report
    assert s["churn_rate"]["value"] is None and s["brier_score"]["value"] is None and s["average_precision"]["value"] is None
    assert now["consistency"]["labels_mismatched"] == []
    for at in ("2026-05-01T12:00:00Z",):                                                         # an as_of at (not after) the clock is accepted
        assert get(client, "/metrics", prediction_at=REVIEWER_SET, as_of=at).status_code == 200


def test_the_refusal_is_the_rule_the_typescript_planner_mirrors():
    now = parse_ts("2026-05-01T12:00:00Z")
    check_as_of(now, now)                                                                       # equal is not the future
    with pytest.raises(DomainError) as e:
        check_as_of(parse_ts(REVIEWER_AS_OF), now)
    assert e.value.code == E.AS_OF_IN_FUTURE


def test_detect_a_2027_as_of_must_not_relabel_the_golden_cohorts_stored_censored_labels():
    data = golden_inputs()
    stored_censored = {lb["cutoff_id"]: lb["label_id"] for lb in data["labels"] if not lb["mature"]}
    assert stored_censored                                                                      # the golden cohort has censored labels (the February set)
    future = evaluate({**copy.deepcopy(data), "as_of": "2027-01-01T00:00:00Z"})
    rows = {r["cutoff_id"]: r for r in future["point_in_time"]["rows"]}
    for cid in stored_censored:                                                                 # never reported mature, never given an outcome
        if rows[cid]["eligible"]:
            assert rows[cid]["mature"] is False and rows[cid]["churned"] is None, cid
    feb = future["cutoff_sets"][FEB]["population"]
    assert feb["mature"] == 0 and feb["censored"] == feb["eligible"] > 0 and future["cutoff_sets"][FEB]["churn_rate"]["value"] is None
    # the disagreement between the stored label and the rules' own maturity is a consistency FINDING, not a relabel
    flagged = set(future["consistency"]["labels_mismatched"])
    assert flagged and flagged <= set(stored_censored.values())
    assert all(rows[c]["eligible"] for c, lid in stored_censored.items() if lid in flagged)


def test_recover_at_the_cohorts_own_as_of_nothing_is_flagged_and_the_months_that_were_mature_do_not_move():
    data = golden_inputs()
    base = evaluate(data)
    assert base["consistency"]["labels_mismatched"] == []
    future = evaluate({**copy.deepcopy(data), "as_of": "2027-01-01T00:00:00Z"})
    for at, s in base["cutoff_sets"].items():                                                   # a set whose labels are stored mature reads the same in 2027
        stored = [lb for lb in data["labels"] if not lb["mature"] and any(c["cutoff_id"] == lb["cutoff_id"] and c["prediction_at"] == at for c in data["prediction_cutoffs"])]
        if not stored:
            assert future["cutoff_sets"][at]["churn_rate"] == s["churn_rate"] and future["cutoff_sets"][at]["brier_score"] == s["brier_score"], at


# ---- R10-14 -------------------------------------------------------------------------------------------------------------------------
def test_the_prevalence_baseline_is_the_training_prevalence_frozen_to_six_places():
    pre, models = fit_all()
    prev = models[3]
    positives = sum(1 for _, y in TRAIN if y)
    assert prev == {"name": "prevalence_baseline", "prevalence": fit_prevalence(TRAIN)}
    assert re.fullmatch(r"\d\.\d{6}", prev["prevalence"]) and Fraction(prev["prevalence"]) == Fraction(round(Fraction(positives, len(TRAIN)) * 10**6), 10**6)
    cfg = {"preprocessing": pre, "models": models}
    assert {score_features(cfg, "prevalence_baseline", f"x-{k}", f) for k, (f, _) in enumerate(TRAIN)} == {prev["prevalence"]}      # every account, one value


def test_the_logistic_model_beats_the_constant_on_brier_and_the_constant_ranks_nothing():
    pre, models = fit_all()
    got = evaluate_models_with_constant(models, pre)
    assert got["logistic_regression"][1] < got["prevalence_baseline"][1]                          # the honest reference is beaten on the separable set
    assert got["prevalence_baseline"][0] == Fraction(sum(1 for _, y in TEST if y), len(TEST))      # AP of one big tie is the prevalence


def evaluate_models_with_constant(models, pre):
    from retentionlab.metrics import average_precision
    config = {"preprocessing": pre, "models": models}
    out = dict(evaluate_models(models, pre))
    items = [{"p": Fraction(score_features(config, "prevalence_baseline", f"te-{k}", f)), "y": y, "account_id": k} for k, (f, y) in enumerate(TEST)]
    ap, _ = average_precision(items, sum(1 for it in items if it["y"]))
    out["prevalence_baseline"] = (ap, sum(((it["p"] - (1 if it["y"] else 0)) ** 2 for it in items), Fraction(0)) / len(items))
    return out


def test_the_constant_needs_training_rows():
    with pytest.raises(DomainError) as e:
        fit_prevalence([])
    assert e.value.code == E.NO_TRAINING_ROWS
    assert [m["name"] for m in train_models(fit_all()[0], TRAIN)] == ["random_baseline", "business_rule", "logistic_regression", "prevalence_baseline"]


def test_the_api_stores_scores_and_reports_the_constant(client, conn):
    load(conn, build_world())
    pipeline(client, command)
    pa = "2025-10-01T00:00:00Z"
    assert command(client, "score-accounts", {"training_run_id": "tr-w", "prediction_at": pa, "model": "prevalence_baseline"}).status_code == 200
    got = metrics(client, training_run_id="tr-w", prediction_at=pa, model="prevalence_baseline")["data"]["cutoff_sets"][pa]
    ps = {r["probability"] for r in got["ranking"]}
    assert len(ps) == 1 and got["average_precision"]["value"] == got["average_precision"]["prevalence"]
    assert conn.execute("SELECT count(*) n FROM model_coefficients WHERE model_name = 'prevalence_baseline'").fetchone()["n"] == 1


# ---- R10-15 -------------------------------------------------------------------------------------------------------------------------
REG = {r["feature_name"]: r for r in Mini().d["feature_registry"]}


def test_detect_a_feature_request_naming_a_field_twice_is_refused():
    with pytest.raises(DomainError) as e:
        check_feature_request(REG, ["usage_events_30d", "billing_total_90d", "usage_events_30d"])
    assert e.value.code == E.DUPLICATE_FIELD and e.value.details["offending"] == [{"item": "usage_events_30d", "code": "DUPLICATE_FIELD"}]


def test_recover_other_refusals_keep_their_priority_and_a_clean_request_passes():
    with pytest.raises(DomainError) as e:
        check_feature_request(REG, ["usage_events_30d", "usage_events_30d", "account_id"])
    assert e.value.code == E.ID_FEATURE and {o["code"] for o in e.value.details["offending"]} == {"ID_FEATURE", "DUPLICATE_FIELD"}
    assert check_feature_request(REG, ["usage_events_30d", "billing_total_90d"]) == ["usage_events_30d", "billing_total_90d"]


def test_the_api_refuses_a_duplicated_field(client, conn):
    load(conn, build_world())
    r = command(client, "build-point-in-time-features", {"prediction_at": "2025-10-01T00:00:00Z", "fields": ["usage_events_30d", "usage_events_30d"]})
    assert r.status_code == 422 and rule_ids(r) == ["DUPLICATE_FIELD"]
    ok = command(client, "build-point-in-time-features", {"prediction_at": "2025-10-01T00:00:00Z", "fields": ["usage_events_30d"]})
    assert ok.status_code == 200
