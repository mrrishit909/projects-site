"""Fitting and scoring (D-02): preprocessing fitted on training rows only, three models, Platt calibration on validation rows only.

FLOATS ARE ALLOWED INSIDE THIS MODULE'S FITTING LOOPS ONLY (gradient descent, sigmoid). Everything that leaves a function is a frozen
6-place decimal string: coefficients, preprocessing parameters, Platt a and b, probabilities. Every published metric is then computed
exactly on those strings (metrics.py). Determinism: full-batch descent in fixed row order from a fixed start with fixed iterations
and learning rate; the only transcendental functions are ``det_exp`` (below: basic IEEE operations only, identical on every platform)
and ``Decimal.ln`` (decimal arithmetic), so two runs, or two machines, freeze the same strings.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction as F
from typing import Any, Sequence

from . import errors as E
from .contract import BUSINESS_RULE, FEATURES, NULLABLE_FEATURES
from .numbers import freeze, rnd, sha256_hex

LEARNING_RATE = "0.100000"
DEFAULT_L2 = "1.000000"
DEFAULT_ITERATIONS = 500
PLATT_ITERATIONS = 500
PLATT_LEARNING_RATE = 0.1
PROBABILITY_FLOOR = Decimal("0.000001")


# --- deterministic arithmetic ----------------------------------------------------------------------------------------

def det_exp(x: float) -> float:
    """exp(x) from + - * / only: Taylor series on x / 1024, squared ten times. |x| is clamped to 40."""
    x = max(-40.0, min(40.0, x))
    y = x / 1024.0
    term = total = 1.0
    for k in range(1, 14):
        term = term * y / k
        total += term
    for _ in range(10):
        total = total * total
    return total


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + det_exp(-z))


def _logit(p: str) -> float:
    """ln(p / (1 - p)) of a probability string clamped to [1e-6, 1 - 1e-6], by ``Decimal.ln`` (deterministic)."""
    with localcontext() as ctx:
        ctx.prec = 40
        d = min(max(Decimal(p), PROBABILITY_FLOOR), 1 - PROBABILITY_FLOOR)
        return float((d / (1 - d)).ln())


# --- preprocessing (exact, then frozen) --------------------------------------------------------------------------------

def _median(values: list[F]) -> F:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _sqrt(x: F) -> F:
    with localcontext() as ctx:
        ctx.prec = 50
        root = (Decimal(x.numerator) / Decimal(x.denominator)).sqrt()
    return F(root)


def fit_preprocessing(feature_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Median imputation, standardisation and missing indicators, fitted on the GIVEN rows only (the caller has proved they are
    retained training rows; LEAKAGE otherwise). Medians, means and standard deviations are exact and frozen to 6 places; a
    zero standard deviation is replaced by 1."""
    if not feature_rows:
        raise E.DomainError(E.NO_TRAINING_ROWS, "preprocessing needs at least one training row", "input.fit_rows")
    params: dict[str, Any] = {}
    indicators: list[str] = []
    for f in FEATURES:
        observed = [F(str(r[f])) for r in feature_rows if r[f] is not None]
        missing = len(feature_rows) - len(observed)
        median = _median(observed) if observed else F(0)
        median_s = rnd(median, 6)
        filled = [F(str(r[f])) if r[f] is not None else F(median_s) for r in feature_rows]    # imputed with the FROZEN median
        mean = sum(filled, F(0)) / len(filled)
        mean_s = rnd(mean, 6)
        var = sum(((x - F(mean_s)) ** 2 for x in filled), F(0)) / len(filled)
        std_s = rnd(_sqrt(var), 6)
        params[f] = {"median": median_s, "mean": mean_s, "std": "1.000000" if F(std_s) == 0 else std_s, "missing_in_fit": missing}
        if missing and f in NULLABLE_FEATURES:
            indicators.append(f)
    return {"fit_rows": len(feature_rows), "features": params, "missing_indicators": indicators}


def design_names(pre: dict[str, Any]) -> list[str]:
    return list(FEATURES) + [f"{f}_missing" for f in pre["missing_indicators"]]


def transform(pre: dict[str, Any], features: dict[str, Any]) -> list[float]:
    """Impute with the frozen median, standardise with the frozen mean and std, append the missing indicators. Frozen strings -> floats."""
    x: list[float] = []
    for f in FEATURES:
        p = pre["features"][f]
        v = features[f]
        value = float(F(str(v))) if v is not None else float(p["median"])
        x.append((value - float(p["mean"])) / float(p["std"]))
    for f in pre["missing_indicators"]:
        x.append(1.0 if features[f] is None else 0.0)
    return x


# --- the three models --------------------------------------------------------------------------------------------------

def random_probability(seed: int, cutoff_id: str) -> str:
    """The seeded random baseline: a stateless hash of (seed, cutoff) into [0, 1] with 6 places (order-independent, platform-independent)."""
    n = int(sha256_hex(f"{seed}:{cutoff_id}")[:12], 16) % 1_000_001
    return rnd(F(n, 1_000_000), 6)


def rule_flag(features: dict[str, Any]) -> bool:
    """The business rule (D-02): no usage in the last 30 days, or a high-severity support case in the window (A-05)."""
    return features["usage_events_30d"] == 0 or features["high_severity_support_90d"] >= 1


def fit_rule(rows: Sequence[tuple[dict[str, Any], bool]]) -> dict[str, str]:
    """The rule's two probabilities: the observed churn rate of flagged and unflagged training rows (an empty group takes the overall
    rate). The rule itself is not fitted; only its two outputs are read off the training rows so that its Brier score is fair."""
    if not rows:
        raise E.DomainError(E.NO_TRAINING_ROWS, "the rule baseline needs training rows", "input.fit_rows")
    overall = F(sum(1 for _, y in rows if y), len(rows))
    out: dict[str, str] = {}
    for name, flagged in (("flagged", True), ("unflagged", False)):
        group = [y for f, y in rows if rule_flag(f) is flagged]
        out[name] = rnd(F(sum(1 for y in group if y), len(group)) if group else overall, 6)
    return out


def predict_rule(rates: dict[str, str], features: dict[str, Any]) -> str:
    return rates["flagged" if rule_flag(features) else "unflagged"]


def fit_logistic(pre: dict[str, Any], rows: Sequence[tuple[dict[str, Any], bool]], l2: str = DEFAULT_L2, iterations: int = DEFAULT_ITERATIONS,
                 learning_rate: str = LEARNING_RATE) -> dict[str, str]:
    """Logistic regression by deterministic full-batch gradient descent: objective mean log-loss + (l2 / 2n) x sum(w^2) (the intercept
    is not penalised), start at zero, fixed ``iterations`` and ``learning_rate``. Returns the frozen coefficients (6-place strings)."""
    if not rows:
        raise E.DomainError(E.NO_TRAINING_ROWS, "the logistic model needs training rows", "input.fit_rows")
    if len({y for _, y in rows}) < 2:
        raise E.DomainError(E.SINGLE_CLASS, "the training rows contain a single class; a ranking cannot be learned", "input.fit_rows")
    xs = [transform(pre, f) for f, _ in rows]
    ys = [1.0 if y else 0.0 for _, y in rows]
    n, d = len(xs), len(xs[0])
    lam, lr = float(l2), float(learning_rate)
    w = [0.0] * d
    b = 0.0
    for _ in range(iterations):
        gb = 0.0
        gw = [0.0] * d
        for x, y in zip(xs, ys):
            z = b
            for j in range(d):
                z += w[j] * x[j]
            err = sigmoid(z) - y
            gb += err
            for j in range(d):
                gw[j] += err * x[j]
        b -= lr * gb / n
        for j in range(d):
            w[j] -= lr * (gw[j] + lam * w[j]) / n
    names = design_names(pre)
    return {"intercept": freeze(b), **{names[j]: freeze(w[j]) for j in range(d)}}


def predict_logistic(pre: dict[str, Any], coefficients: dict[str, str], features: dict[str, Any]) -> str:
    """sigmoid(intercept + sum w x) from the FROZEN strings, frozen again as a 6-place probability."""
    x = transform(pre, features)
    z = float(coefficients["intercept"])
    for name, value in zip(design_names(pre), x):
        z += float(coefficients[name]) * value
    return freeze(sigmoid(z))


# --- Platt scaling -----------------------------------------------------------------------------------------------------

def fit_platt(probabilities: Sequence[str], outcomes: Sequence[bool], iterations: int = PLATT_ITERATIONS) -> dict[str, str]:
    """Platt scaling of the model's frozen probabilities: p' = sigmoid(a x logit(p) + b), a and b by full-batch descent from the
    identity (a = 1, b = 0). The caller has proved the rows are retained validation rows and not the evaluation rows."""
    if not probabilities:
        raise E.DomainError(E.NO_VALIDATION_ROWS, "calibration needs validation rows", "input.fit_rows")
    if len(set(outcomes)) < 2:
        raise E.DomainError(E.SINGLE_CLASS, "the validation rows contain a single class; a calibration cannot be learned", "input.fit_rows")
    xs = [_logit(p) for p in probabilities]
    ys = [1.0 if y else 0.0 for y in outcomes]
    a, b, n = 1.0, 0.0, len(xs)
    for _ in range(iterations):
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            err = sigmoid(a * x + b) - y
            ga += err * x
            gb += err
        a -= PLATT_LEARNING_RATE * ga / n
        b -= PLATT_LEARNING_RATE * gb / n
    return {"method": "platt", "a": freeze(a), "b": freeze(b)}


def apply_platt(calibration: dict[str, str], probability: str) -> str:
    return freeze(sigmoid(float(calibration["a"]) * _logit(probability) + float(calibration["b"])))


# --- the run's config ----------------------------------------------------------------------------------------------------

def model_config(config: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((m for m in config.get("models", []) if m.get("name") == name), None)


def train_models(pre: dict[str, Any], rows: Sequence[tuple[dict[str, Any], bool]], random_seed: int = 7, l2: str = DEFAULT_L2,
                 iterations: int = DEFAULT_ITERATIONS, learning_rate: str = LEARNING_RATE) -> list[dict[str, Any]]:
    """The three model entries of a run's ``config.models``: the seeded random baseline, the business rule, the logistic regression."""
    return [{"name": "random_baseline", "seed": random_seed},
            {"name": "business_rule", "rule": BUSINESS_RULE, "rates": fit_rule(rows)},
            {"name": "logistic_regression", "l2": l2, "iterations": iterations, "learning_rate": learning_rate,
             "coefficients": fit_logistic(pre, rows, l2, iterations, learning_rate)}]


def score_features(config: dict[str, Any], model: str, cutoff_id: str, features: dict[str, Any], calibrated: bool = True) -> str:
    """One account's frozen probability under one model of a run's config (the logistic one is Platt-scaled when the run has a
    calibration and ``calibrated``)."""
    m = model_config(config, model)
    if m is None:
        raise E.DomainError(E.MODEL_NOT_FITTED, f"model {model!r} has not been trained for this run", "input.model")
    if model == "random_baseline":
        return random_probability(int(m["seed"]), cutoff_id)
    if model == "business_rule":
        return predict_rule(m["rates"], features)
    pre = config.get("preprocessing")
    if pre is None or "coefficients" not in m or not set(design_names(pre)) <= set(m["coefficients"]):
        raise E.DomainError(E.PREPROCESSING_REQUIRED, "the logistic model needs the fitted preprocessing it was trained with", "input.model")
    p = predict_logistic(pre, m["coefficients"], features)
    cal = config.get("calibration")
    return apply_platt(cal, p) if calibrated and cal else p
