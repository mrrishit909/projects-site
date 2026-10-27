"""Refusal rules for the commands (D-P10-14): pure checks that raise ``DomainError`` with every offending item listed.

The same functions serve the fixture's ``requests`` (pipeline.py) and the API handlers.
"""
from __future__ import annotations

from typing import Any, Iterable

from . import errors as E
from .world import classify_feature


def _refuse(code: str, message: str, offending: list[dict[str, Any]], path: str | None = None) -> E.DomainError:
    return E.DomainError(code, message, path, {"offending": offending})


def check_feature_request(registry: dict[str, dict[str, Any]], fields: Iterable[str]) -> list[str]:
    """Refuse a request naming a post-outcome, latent, identifier-derived or unregistered field; the code is the first in the order
    POST_OUTCOME_FIELD, LATENT_TRUTH, ID_FEATURE, UNKNOWN_FEATURE and every offending field is listed with its own code."""
    names = list(fields)
    bad = [(f, classify_feature(registry, f)) for f in names]
    bad = [(f, c) for f, c in bad if c]
    if bad:
        code = min((c for _, c in bad), key=E.FEATURE_PRIORITY.index)
        raise _refuse(code, "the request names fields that cannot be features: " + ", ".join(f for f, _ in bad),
                      [{"item": f, "code": c} for f, c in bad], "input.fields")
    return names


def check_fit_rows(fit_rows: list[str], retained_train: set[str]) -> None:
    """Preprocessing is fitted on retained training rows only (P10-FLOW-04)."""
    bad = [c for c in fit_rows if c not in retained_train]
    if bad:
        raise _refuse(E.LEAKAGE, "preprocessing may be fitted on retained training rows only",
                      [{"item": c, "code": "NOT_TRAINING_ROW"} for c in bad], "input.fit_rows")


def check_calibration_rows(fit_rows: list[str], evaluation_rows: list[str], retained_validation: set[str]) -> None:
    """Platt scaling is fitted on retained validation rows and never evaluated on the rows it was fitted on (P10-FLOW-06)."""
    overlap = [c for c in evaluation_rows if c in set(fit_rows)]
    if overlap:
        raise _refuse(E.CALIBRATION_ON_FIT_ROWS, "the reliability curve must use rows the calibration did not see",
                      [{"item": c, "code": "IN_FIT_ROWS"} for c in overlap], "input.evaluation_rows")
    bad = [c for c in fit_rows if c not in retained_validation]
    if bad:
        raise _refuse(E.LEAKAGE, "calibration may be fitted on retained validation rows only",
                      [{"item": c, "code": "NOT_VALIDATION_ROW"} for c in bad], "input.fit_rows")


def check_threshold(parameter: str, selected_on: str) -> None:
    """Capacity and thresholds are chosen on validation; the test set is read once (P10-FLOW-06, P10-TEST-06)."""
    if selected_on != "validation":
        raise _refuse(E.THRESHOLD_ON_TEST, "capacity and thresholds are chosen on validation rows; the test set is read once",
                      [{"item": parameter, "code": "SELECTED_ON_" + selected_on.upper()}], "input.selected_on")


def check_capacity(scenario_id: str, capacity: int, population: int) -> None:
    """K may not exceed the scored eligible population (P10-MET-02, P10-TEST-10)."""
    if capacity > population:
        raise _refuse(E.CAPACITY_EXCEEDS_POPULATION, f"capacity {capacity} exceeds the population {population}",
                      [{"item": scenario_id, "code": f"CAPACITY_{capacity}_GT_{population}"}], "input.capacity")
