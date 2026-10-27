"""The queryable projection of a run's ``config`` (preprocessing, coefficients, Platt mapping) in NUMERIC columns.

The config (strings, hashed) is the authority; these rows are written in the same transaction as every config change and are checked
against it by the tests. They are refused once the run has a prediction (trigger RUN_FROZEN).
"""
from __future__ import annotations

from typing import Any

import psycopg


def write_artefacts(conn: psycopg.Connection, run_id: str, config: dict[str, Any]) -> None:
    conn.execute("DELETE FROM model_preprocessing WHERE training_run_id = %s", (run_id,))
    conn.execute("DELETE FROM model_coefficients WHERE training_run_id = %s", (run_id,))
    conn.execute("DELETE FROM calibration_maps WHERE training_run_id = %s", (run_id,))
    pre = config.get("preprocessing")
    if pre:
        for name, p in sorted(pre["features"].items()):
            conn.execute("INSERT INTO model_preprocessing (training_run_id, feature_name, median, mean, std, missing_in_fit, missing_indicator) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                         (run_id, name, p["median"], p["mean"], p["std"], p["missing_in_fit"], name in pre["missing_indicators"]))
    for m in config.get("models", []):
        for term, value in sorted((m.get("coefficients") or {}).items()):
            conn.execute("INSERT INTO model_coefficients (training_run_id, model_name, term, value) VALUES (%s,%s,%s,%s)",
                         (run_id, m["name"], term, value))
        for term, value in sorted((m.get("rates") or {}).items()):
            conn.execute("INSERT INTO model_coefficients (training_run_id, model_name, term, value) VALUES (%s,%s,%s,%s)",
                         (run_id, m["name"], "rate_" + term, value))
    cal = config.get("calibration")
    if cal and cal.get("method") == "platt":
        conn.execute("INSERT INTO calibration_maps (training_run_id, method, a, b, fit_rows) VALUES (%s,%s,%s,%s,%s)",
                     (run_id, "platt", cal["a"], cal["b"], int(cal.get("fit_rows") or 1)))
