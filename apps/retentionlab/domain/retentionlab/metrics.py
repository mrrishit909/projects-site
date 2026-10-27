"""Every metric of D-03, computed exactly on the frozen 6-place strings (``Fraction``; ``Decimal`` for money and for the one
logarithm of the population stability index). No float.

Scope (D-P10-01/02): a cutoff set is the rows sharing one ``prediction_at``. Outcome metrics use mature eligible rows with an accepted
prediction (``unscored_excluded`` is published); the churn rate uses all mature eligible rows; missingness, drift and the outreach
queue use all eligible rows, censored ones included.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction as F
from typing import Any

from . import errors as E
from .contract import CAL_BINS, EVENTS, FEATURES
from .numbers import money, p6, pp2, ratio, rnd
from .timeutil import hours_between, iso_z, parse_ts
from .world import World

#: A published model for a metric computation: probability strings keyed by (training_run_id, cutoff_id).


def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """Probability descending, ties by account_id ascending (D-P10-03)."""
    return (-item["p"], item["account_id"])


def average_precision(items: list[dict[str, Any]], positives: int) -> tuple[F | None, list[dict[str, Any]]]:
    """scikit-learn ``average_precision_score``: the sum over DISTINCT thresholds of (R_n - R_{n-1}) x P_n; tied probabilities are one
    threshold (so the result does not depend on how account ids break the tie)."""
    if positives == 0:
        return None, []
    tp = fp = 0
    prev_recall = F(0)
    total = F(0)
    terms: list[dict[str, Any]] = []
    for level in sorted({it["p"] for it in items}, reverse=True):
        group = [it for it in items if it["p"] == level]
        tp += sum(1 for it in group if it["y"])
        fp += sum(1 for it in group if not it["y"])
        precision, recall = F(tp, tp + fp), F(tp, positives)
        contribution = (recall - prev_recall) * precision
        total += contribution
        terms.append({"threshold": p6(level), "tp": tp, "fp": fp, "precision": p6(precision), "recall": p6(recall),
                      "delta_recall": p6(recall - prev_recall), "contribution": p6(contribution)})
        prev_recall = recall
    return total, terms


def calibration_bins(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """10 equal-width bins on [0, 1), the last closed; index = floor(10 p) on exact fractions; gap = (mean - observed) x 100 pp."""
    bins: list[list[dict[str, Any]]] = [[] for _ in range(CAL_BINS)]
    for it in items:
        scaled = it["p"] * CAL_BINS
        bins[min(scaled.numerator // scaled.denominator, CAL_BINS - 1)].append(it)
    out = []
    for i, b in enumerate(bins):
        mean = None if not b else sum((it["p"] for it in b), F(0)) / len(b)
        observed = None if not b else F(sum(1 for it in b if it["y"]), len(b))
        out.append({"index": i, "lower": p6(F(i, CAL_BINS)), "upper": p6(F(i + 1, CAL_BINS)), "closed_upper": i == CAL_BINS - 1,
                    "count": len(b), "mean_predicted": p6(mean), "observed_rate": p6(observed),
                    "gap_pp": None if not b else pp2(mean - observed)})  # type: ignore[operator]
    return out


def economics(scenario: dict[str, Any], queue: list[dict[str, Any]]) -> dict[str, Any]:
    """Contact budget = selected x contact_cost; expected value = sum(probability x assumed_effect x margin_value - contact_cost), the
    per-account terms unrounded to 6 places and ONE rounding at the total (ROUND_HALF_UP). Hypothetical, assumption-based."""
    cost, effect, margin = Decimal(scenario["contact_cost"]), Decimal(scenario["assumed_effect"]), Decimal(scenario["margin_value"])
    with localcontext() as ctx:
        ctx.prec = 50
        terms, total = [], Decimal(0)
        for it in queue:
            value = Decimal(it["pstr"]) * effect * margin - cost
            total += value
            terms.append({"account_id": it["account_id"], "probability": it["pstr"],
                          "value_exact": str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))})
        return {"label": "hypothetical", "assumption_based": True, "scenario_id": scenario["scenario_id"],
                "selected_account_ids": [it["account_id"] for it in queue],
                "assumptions": {"contact_cost": money(cost), "assumed_effect": str(effect), "margin_value": money(margin)},
                "contact_budget": money(cost * len(queue)), "terms": terms, "expected_value": money(total),
                "treatment_effect_estimate": None}


def psi(reference: list[int], current: list[int], labels: list[str], floor: str) -> tuple[Decimal, list[dict[str, Any]]] | None:
    """PSI = sum (actual - expected) x ln(actual / expected), natural log by ``Decimal.ln`` at 60 digits; a zero proportion is replaced
    by ``floor`` without renormalising (D-P10-10). None when either cohort is empty."""
    r_total, c_total = sum(reference), sum(current)
    if r_total == 0 or c_total == 0:
        return None
    fl = F(floor)
    with localcontext() as ctx:
        ctx.prec = 60

        def dec(x: F) -> Decimal:
            return Decimal(x.numerator) / Decimal(x.denominator)
        total = Decimal(0)
        bins = []
        for label, r, c in zip(labels, reference, current):
            expected, actual = F(r, r_total), F(c, c_total)
            e_f, a_f = (fl if expected == 0 else expected), (fl if actual == 0 else actual)
            term = (dec(a_f) - dec(e_f)) * (dec(a_f) / dec(e_f)).ln()
            total += term
            bins.append({"label": label, "reference_count": r, "current_count": c, "reference_proportion": p6(expected),
                         "current_proportion": p6(actual), "floored": expected == 0 or actual == 0,
                         "term": str(term.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP))})
        return total, bins


def _bound(x: Any) -> F | None:
    return None if x is None else F(str(x))


def in_bin(value: Any, b: dict[str, Any]) -> bool:
    """Half-open declared bin [lower, upper); a null value is in no bin."""
    if value is None:
        return False
    v = F(str(value))
    return v >= _bound(b["lower"]) and (b["upper"] is None or v < _bound(b["upper"]))  # type: ignore[operator]


def set_metrics(world: World, run_id: str, prediction_at: str, scenario_id: str | None, drift: dict[str, Any] | None) -> dict[str, Any]:
    """Everything the report says about ONE cutoff set under ONE training run (and one optional scenario)."""
    rows = world.set_rows(prediction_at)
    eligible = [r for r in rows if r["eligible"]]
    mature = [r for r in eligible if r["mature"]]
    scored = [r for r in eligible if (run_id, r["cutoff_id"]) in world.preds]
    evaluated = [r for r in mature if (run_id, r["cutoff_id"]) in world.preds]
    ineligible: dict[str, int] = {}
    for r in rows:
        if not r["eligible"]:
            ineligible[r["ineligible_code"]] = ineligible.get(r["ineligible_code"], 0) + 1
    churned = sum(1 for r in mature if r["churned"])
    out: dict[str, Any] = {
        "prediction_at": prediction_at,
        "population": {"cutoff_rows": len(rows), "eligible": len(eligible), "ineligible": dict(sorted(ineligible.items())),
                       "mature": len(mature), "censored": len(eligible) - len(mature), "scored": len(scored),
                       "evaluated": len(evaluated), "unscored_excluded": len(mature) - len(evaluated), "churned": churned},
        "empty_population": len(eligible) == 0, "empty_evaluation": len(evaluated) == 0,
        "churn_rate": {"value": p6(ratio(churned, len(mature))), "churned": churned, "mature_eligible": len(mature)}}
    late = {e: sum(r["arrived_late"][e] for r in eligible) for e in EVENTS}
    late["total"] = sum(late.values())
    out["late_events"] = late
    items = sorted(({"p": F(world.preds[(run_id, r["cutoff_id"])]["probability"]), "pstr": world.preds[(run_id, r["cutoff_id"])]["probability"],
                     "y": bool(r["churned"]), "account_id": r["account_id"], "cutoff_id": r["cutoff_id"]} for r in evaluated), key=rank_key)
    n = len(items)
    positives = sum(1 for it in items if it["y"])
    out["ranking"] = [{"rank": i + 1, "cutoff_id": it["cutoff_id"], "account_id": it["account_id"], "probability": it["pstr"],
                       "outcome": 1 if it["y"] else 0} for i, it in enumerate(items)]
    scenario = world.scenarios.get(scenario_id) if scenario_id else None
    k = scenario["capacity"] if scenario else None
    k_ok = None if k is None else (1 <= k <= n if n else False)
    out["capacity"] = None if scenario is None else {"scenario_id": scenario_id, "k": k, "population": n, "ok": k_ok,
                                                      "refusal": None if k_ok or n == 0 else E.CAPACITY_EXCEEDS_POPULATION}
    ap_total, ap_terms = average_precision(items, positives)
    out["precision_at_k"] = out["recall_at_k"] = out["risk_lift_at_k"] = None
    if k_ok:
        hits = sum(1 for it in items[:k] if it["y"])
        top_rate = F(hits, k)
        overall = ratio(positives, n)
        out["precision_at_k"] = {"value": p6(top_rate), "hits": hits, "k": k}
        out["recall_at_k"] = {"value": p6(ratio(hits, positives)), "hits": hits, "positives": positives}
        out["risk_lift_at_k"] = {"value": p6(None if not positives else top_rate / overall),  # type: ignore[operator]
                                 "top_k_rate": p6(top_rate), "overall_rate": p6(overall), "tie_split_at_k": k < n and items[k - 1]["p"] == items[k]["p"]}
    out["average_precision"] = {"value": p6(ap_total), "prevalence": p6(ratio(positives, n)), "positives": positives, "n": n, "terms": ap_terms}
    squares = [(it["p"] - (1 if it["y"] else 0)) ** 2 for it in items]
    out["brier_score"] = {"value": p6(ratio_f(sum(squares, F(0)), n)), "n": n, "terms": [p6(s) for s in squares]}
    out["calibration"] = {"bin_width": "0.100000", "bins": calibration_bins(items)}
    queue = sorted(({"p": F(world.preds[(run_id, r["cutoff_id"])]["probability"]), "pstr": world.preds[(run_id, r["cutoff_id"])]["probability"],
                     "account_id": r["account_id"]} for r in scored), key=rank_key)
    out["economics"] = out["outreach_queue"] = None
    if scenario and k is not None and 1 <= k <= len(queue):
        out["economics"] = economics(scenario, queue[:k])
        out["outreach_queue"] = {"status": "draft", "account_ids": [q["account_id"] for q in queue[:k]], "population": len(queue)}
    missing = {f: sum(1 for r in eligible if r["features"][f] is None) for f in FEATURES}
    total_missing = sum(missing.values())
    out["feature_missingness"] = {
        "period": prediction_at[:7],
        "by_feature": {f: {"missing": m, "total": len(eligible), "value": p6(ratio(m, len(eligible)))} for f, m in missing.items()},
        "overall": {"missing": total_missing, "total": len(eligible) * len(FEATURES), "value": p6(ratio(total_missing, len(eligible) * len(FEATURES)))}}
    out["population_drift"] = None
    if drift:
        out["population_drift"] = drift_block(world, eligible, drift)
    return out


def ratio_f(num: F, den: int) -> F | None:
    return None if den == 0 else num / den


def drift_block(world: World, current_eligible: list[dict[str, Any]], drift: dict[str, Any]) -> dict[str, Any]:
    reference = [r for r in world.set_rows(drift["reference_prediction_at"]) if r["eligible"]]
    bins, feature = drift["bins"], drift["feature"]
    ref_counts = [sum(1 for r in reference if in_bin(r["features"][feature], b)) for b in bins]
    cur_counts = [sum(1 for r in current_eligible if in_bin(r["features"][feature], b)) for b in bins]
    res = psi(ref_counts, cur_counts, [b["label"] for b in bins], drift["floor"])
    return {"feature": feature, "reference_prediction_at": drift["reference_prediction_at"], "reference_rows": sum(ref_counts),
            "current_rows": sum(cur_counts),
            "psi": None if res is None else str(res[0].quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
            "threshold": drift["threshold"], "diagnostic_only": True,
            "exceeds_threshold": None if res is None else res[0] > Decimal(drift["threshold"]), "bins": [] if res is None else res[1]}


def publications(world: World) -> list[dict[str, Any]]:
    """Scoring publications with a DERIVED status: completed iff at least one eligible account and every eligible account at the set
    has an accepted prediction of the run (D-P10-12)."""
    out = []
    for sp in world.acc["scoring_publications"]:
        eligible = [r for r in world.set_rows(sp["prediction_at"]) if r["eligible"]]
        scored = sum(1 for r in eligible if (sp["training_run_id"], r["cutoff_id"]) in world.preds)
        out.append({"publication_id": sp["publication_id"], "training_run_id": sp["training_run_id"], "prediction_at": sp["prediction_at"],
                    "published_at": sp["published_at"], "eligible": len(eligible), "scored": scored,
                    "status": "completed" if eligible and scored == len(eligible) else "incomplete"})
    return out


def freshness(world: World, pubs: list[dict[str, Any]]) -> dict[str, Any]:
    """Scoring freshness = as_of - the latest COMPLETED publication (hours, floored); data freshness = as_of - the latest ``available_at``
    ingested. Separate figures; null when there is nothing to measure (D-P10-12)."""
    done = [p for p in pubs if p["status"] == "completed" and parse_ts(p["published_at"]) <= world.as_of]
    latest = max(done, key=lambda p: (parse_ts(p["published_at"]), p["publication_id"])) if done else None
    available = [parse_ts(ev["available_at"]) for e in EVENTS for ev in world.acc[e] if parse_ts(ev["available_at"]) <= world.as_of]
    newest = max(available) if available else None
    return {"as_of": iso_z(world.as_of),
            "scoring_hours": None if latest is None else hours_between(world.as_of, parse_ts(latest["published_at"])),
            "latest_completed_publication_id": None if latest is None else latest["publication_id"],
            "latest_completed_published_at": None if latest is None else iso_z(parse_ts(latest["published_at"])),
            "data_hours": None if newest is None else hours_between(world.as_of, newest),
            "latest_available_at": None if newest is None else iso_z(newest)}
