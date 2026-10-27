"""Fitting in the pure domain (D-02, P10-FLOW-04..06, P10-TEST-05/11/12): a small deterministic fitting test on a separable synthetic set,
preprocessing fitted on training rows only, Platt scaling on validation rows only, and the frozen outputs byte-stable across runs.

Floats exist only inside the fitting loops; every value that comes out is a 6-place decimal string."""
import json
import math
import re
from fractions import Fraction

import pytest

from retentionlab import errors as E
from retentionlab.errors import DomainError
from retentionlab.fitting import (apply_platt, det_exp, fit_logistic, fit_platt, fit_preprocessing, fit_rule, predict_logistic, random_probability,
                                  rule_flag, score_features, sigmoid, train_models, transform)
from retentionlab.metrics import average_precision

from support_db import has_float
from worlds import h

SIX = re.compile(r"^-?\d+\.\d{6}$")


def row(i: int, salt: str = "tr"):
    """One synthetic account-cutoff. The outcome is a pure function of the days since the last usage (separable at 20 days); usage count,
    support and billing are noise around it, so the business rule (no usage / high support) is only a weak guess."""
    days = h(i, salt, "d") % 40
    usage = h(i, salt, "u") % 7
    features = {"usage_events_30d": usage, "days_since_last_usage": None if h(i, salt, "m") % 9 == 0 else days,
                "high_severity_support_90d": 1 if h(i, salt, "s") % 4 == 0 else 0,
                "billing_total_90d": None if h(i, salt, "b") % 6 == 0 else f"{10 + h(i, salt, 'a') % 90}.00"}
    outcome = days >= 20
    if features["days_since_last_usage"] is None:                       # a missing value hides the truth: keep the set separable on what is observed
        features["days_since_last_usage"] = days
    return features, outcome


TRAIN = [row(i) for i in range(160)]
TEST = [row(i, "te") for i in range(80)]


def evaluate_models(models_cfg, pre):
    config = {"preprocessing": pre, "models": models_cfg}
    out = {}
    for name in ("random_baseline", "business_rule", "logistic_regression"):
        items = [{"p": Fraction(score_features(config, name, f"te-{k}", f)), "y": y, "account_id": k} for k, (f, y) in enumerate(TEST)]
        ap, _ = average_precision(items, sum(1 for it in items if it["y"]))
        brier = sum(((it["p"] - (1 if it["y"] else 0)) ** 2 for it in items), Fraction(0)) / len(items)
        out[name] = (ap, brier)
    return out


def fit_all():
    pre = fit_preprocessing([f for f, _ in TRAIN])
    return pre, train_models(pre, TRAIN)


def test_the_logistic_model_beats_the_rule_and_the_random_baseline_on_ap_and_brier():
    pre, models = fit_all()
    got = evaluate_models(models, pre)
    lr_ap, lr_brier = got["logistic_regression"]
    for baseline in ("business_rule", "random_baseline"):
        assert lr_ap > got[baseline][0] and lr_brier < got[baseline][1], baseline
    assert lr_ap >= Fraction(99, 100) and lr_brier < Fraction(1, 10)               # separable: the ranking is (almost) perfect
    assert got["business_rule"][0] < Fraction(3, 4) and got["random_baseline"][0] < Fraction(3, 4)    # the references are genuinely weaker


def test_frozen_outputs_are_byte_stable_across_two_runs_and_two_orderings_of_nothing_random():
    a = json.dumps(fit_all(), sort_keys=True)
    b = json.dumps(fit_all(), sort_keys=True)
    assert a == b and a.encode() == b.encode()
    pre, models = fit_all()
    scores = [score_features({"preprocessing": pre, "models": models}, "logistic_regression", f"te-{k}", f) for k, (f, _) in enumerate(TEST)]
    assert scores == [score_features({"preprocessing": pre, "models": models}, "logistic_regression", f"te-{k}", f) for k, (f, _) in enumerate(TEST)]


def test_every_frozen_number_is_a_six_place_decimal_string_and_nothing_is_a_float():
    pre, models = fit_all()
    assert not has_float([pre, models])
    lr = models[2]
    assert set(lr["coefficients"]) == {"intercept", "usage_events_30d", "days_since_last_usage", "high_severity_support_90d", "billing_total_90d",
                                       "billing_total_90d_missing"}                 # days_since is never missing in this set: no indicator for it
    for v in lr["coefficients"].values():
        assert SIX.match(v)
    for p in pre["features"].values():
        assert all(SIX.match(p[k]) for k in ("median", "mean", "std"))
    assert all(SIX.match(models[1]["rates"][k]) for k in ("flagged", "unflagged")) and models[0] == {"name": "random_baseline", "seed": 7}


def test_known_coefficients_pin_the_deterministic_descent():
    """Pinned once: det_exp uses + - * / only, so these strings are the same on every platform and every Python 3 build."""
    pre, models = fit_all()
    got = models[2]["coefficients"]
    assert got["days_since_last_usage"] == "3.453290" and got["intercept"] == "-0.197240"


def test_det_exp_agrees_with_the_library_and_sigmoid_is_bounded():
    for x in (-40, -12.5, -3, -0.25, 0, 0.001, 1, 2.5, 7.75, 20, 39.9):
        assert abs(det_exp(x) / math.exp(x) - 1) < 1e-11
    assert det_exp(100) == det_exp(40) and 0 < sigmoid(-50) < 1e-15 and sigmoid(0) == 0.5 and sigmoid(50) <= 1


def test_preprocessing_is_fitted_on_the_given_training_rows_only_and_applied_frozen_to_the_rest():
    train, test = [f for f, _ in TRAIN], [f for f, _ in TEST]
    only_train = fit_preprocessing(train)
    with_test = fit_preprocessing(train + test)
    assert only_train != with_test and only_train["fit_rows"] == 160 and with_test["fit_rows"] == 240      # a fit over other rows is a different transformer
    assert fit_preprocessing(train) == only_train                                                         # test rows do not move it: same inputs, same fit
    x_before = transform(only_train, test[0])
    fit_preprocessing(train + test)                                                                       # fitting elsewhere changes nothing already frozen
    assert transform(only_train, test[0]) == x_before
    p = only_train["features"]["days_since_last_usage"]
    assert Fraction(p["median"]) in {Fraction(x) for x in range(0, 40)} | {Fraction(k, 2) for k in range(0, 80)}


def test_median_imputation_standardisation_and_missing_indicators_by_hand():
    rows = [{"usage_events_30d": 1, "days_since_last_usage": 4, "high_severity_support_90d": 0, "billing_total_90d": "10.00"},
            {"usage_events_30d": 3, "days_since_last_usage": None, "high_severity_support_90d": 0, "billing_total_90d": None},
            {"usage_events_30d": 5, "days_since_last_usage": 8, "high_severity_support_90d": 0, "billing_total_90d": "30.00"}]
    pre = fit_preprocessing(rows)
    u = pre["features"]["usage_events_30d"]
    assert (u["median"], u["mean"]) == ("3.000000", "3.000000") and u["std"] == "1.632993"               # sqrt(8/3)
    d = pre["features"]["days_since_last_usage"]
    assert (d["median"], d["missing_in_fit"]) == ("6.000000", 1) and Fraction(d["mean"]) == Fraction(6)    # the missing 4/8 -> median 6
    assert pre["features"]["high_severity_support_90d"]["std"] == "1.000000"                              # zero variance: divide by 1, not 0
    assert pre["missing_indicators"] == ["days_since_last_usage", "billing_total_90d"]
    x = transform(pre, rows[1])
    assert x[1] == 0.0 and x[3] == 0.0 and x[-2:] == [1.0, 1.0]                                          # imputed to the mean -> 0 after standardising; indicators on
    assert transform(pre, rows[0])[-2:] == [0.0, 0.0]
    assert fit_preprocessing(rows[:1])["missing_indicators"] == []                                       # nothing missing in the fit: no indicator column


def test_empty_and_single_class_fits_are_refused_with_codes():
    with pytest.raises(DomainError) as e:
        fit_preprocessing([])
    assert e.value.code == E.NO_TRAINING_ROWS
    pre = fit_preprocessing([f for f, _ in TRAIN])
    with pytest.raises(DomainError) as e:
        fit_logistic(pre, [(f, True) for f, _ in TRAIN])
    assert e.value.code == E.SINGLE_CLASS
    with pytest.raises(DomainError) as e:
        fit_platt(["0.500000", "0.600000"], [True, True])
    assert e.value.code == E.SINGLE_CLASS
    with pytest.raises(DomainError) as e:
        fit_rule([])
    assert e.value.code == E.NO_TRAINING_ROWS


def test_the_business_rule_is_the_rule_of_d_02_and_its_two_outputs_are_observed_rates():
    assert rule_flag({"usage_events_30d": 0, "high_severity_support_90d": 0}) and rule_flag({"usage_events_30d": 4, "high_severity_support_90d": 1})
    assert not rule_flag({"usage_events_30d": 4, "high_severity_support_90d": 0})
    rows = [({"usage_events_30d": 0, "high_severity_support_90d": 0}, True), ({"usage_events_30d": 0, "high_severity_support_90d": 0}, False),
            ({"usage_events_30d": 2, "high_severity_support_90d": 0}, False), ({"usage_events_30d": 3, "high_severity_support_90d": 0}, False)]
    assert fit_rule(rows) == {"flagged": "0.500000", "unflagged": "0.000000"}
    assert fit_rule([rows[0], rows[1]]) == {"flagged": "0.500000", "unflagged": "0.500000"}               # an empty group takes the overall rate


def test_the_random_baseline_is_seeded_stateless_and_in_range():
    a = [random_probability(7, f"c{i}") for i in range(400)]
    assert a == [random_probability(7, f"c{i}") for i in reversed(range(400))][::-1]                      # order of calls does not matter
    assert a != [random_probability(8, f"c{i}") for i in range(400)] and all(SIX.match(x) and 0 <= Fraction(x) <= 1 for x in a)
    assert abs(sum(Fraction(x) for x in a) / 400 - Fraction(1, 2)) < Fraction(1, 10)


def test_platt_scaling_shrinks_an_overconfident_model_and_is_frozen():
    # an overconfident score: the right ordering, probabilities pushed to the ends, 25% of outcomes against it
    probs = ["0.950000" if h(i, "p") % 2 else "0.050000" for i in range(200)]
    outcomes = [(p == "0.950000") != (h(i, "n") % 4 == 0) for i, p in enumerate(probs)]
    cal = fit_platt(probs, outcomes)
    assert cal["method"] == "platt" and SIX.match(cal["a"]) and SIX.match(cal["b"]) and Fraction(cal["a"]) < 1
    high, low = apply_platt(cal, "0.950000"), apply_platt(cal, "0.050000")
    assert SIX.match(high) and Fraction(low) < Fraction("0.05") + Fraction(1, 2) and Fraction("0.6") < Fraction(high) < Fraction("0.95")   # pulled toward 0.75
    assert fit_platt(probs, outcomes) == cal                                                              # byte-stable


def test_a_calibrated_score_is_applied_only_when_the_run_has_a_calibration():
    pre, models = fit_all()
    cfg = {"preprocessing": pre, "models": models}
    raw = score_features(cfg, "logistic_regression", "x", TEST[0][0])
    cal = fit_platt([score_features(cfg, "logistic_regression", f"v{k}", f, calibrated=False) for k, (f, _) in enumerate(TRAIN[:80])], [y for _, y in TRAIN[:80]])
    cfg2 = {**cfg, "calibration": cal}
    assert score_features(cfg2, "logistic_regression", "x", TEST[0][0], calibrated=False) == raw
    assert score_features(cfg2, "logistic_regression", "x", TEST[0][0]) == apply_platt(cal, raw)
    assert score_features(cfg2, "business_rule", "x", TEST[0][0]) == score_features(cfg, "business_rule", "x", TEST[0][0])     # baselines are never calibrated
    assert predict_logistic(pre, models[2]["coefficients"], TEST[0][0]) == raw


def test_scoring_a_model_that_was_not_trained_or_has_no_preprocessing_is_refused():
    with pytest.raises(DomainError) as e:
        score_features({"models": []}, "logistic_regression", "c", TEST[0][0])
    assert e.value.code == E.MODEL_NOT_FITTED
    fixture_like = {"models": [{"name": "logistic_regression", "l2": "1.000000", "iterations": 500, "coefficients": {"intercept": "-0.500000", "usage_events_30d": "-0.300000"}}]}
    with pytest.raises(DomainError) as e:
        score_features(fixture_like, "logistic_regression", "c", TEST[0][0])
    assert e.value.code == E.PREPROCESSING_REQUIRED
