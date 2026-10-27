"""psycopg helpers: one connection and one transaction per request, and the domain's inputs assembled from the tables.

``transaction()`` commits when the block exits normally and rolls back on any exception, so a command's effects and its audit event
are atomic. ``load_data`` returns the same shape as a fixture's ``inputs.json`` (a snapshot AS OF an instant: events whose
``available_at`` is later, predictions scored later and publications published later are not yet known).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from retentionlab.contract import CONTRACT_VERSION
from retentionlab.timeutil import iso_z

Row = dict[str, Any]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect(autocommit: bool = False) -> psycopg.Connection[Row]:
    # UTC session so TIMESTAMPTZ comparisons never depend on the server's zone.
    return psycopg.connect(database_url(), row_factory=dict_row, options="-c timezone=UTC", autocommit=autocommit)


@contextmanager
def transaction() -> Iterator[psycopg.Connection[Row]]:
    """One transaction: commit on success, rollback on error, always close."""
    with _connect() as conn:
        yield conn


@contextmanager
def autocommit() -> Iterator[psycopg.Connection[Row]]:
    """A separate connection whose statements commit at once: keeps a refusal in the audit trail when the command's own transaction
    is about to be rolled back."""
    with _connect(True) as conn:
        yield conn


def jsonable(value: Any) -> Any:
    """Row value to JSON: Decimal exactly as stored (no float anywhere), timestamps as UTC ISO-8601 with Z."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def jsonable_row(row: Row) -> Row:
    return {k: jsonable(v) for k, v in row.items()}


def current_dataset_version(conn: psycopg.Connection[Row]) -> str:
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row["dataset_version"] if row else "unversioned"


def _q(conn: psycopg.Connection[Row], sql: str, *params: Any) -> list[Row]:
    return [jsonable_row(r) for r in conn.execute(sql, params).fetchall()]


def load_data(conn: psycopg.Connection[Row], as_of: datetime, model: str = "logistic_regression", label_version: str | None = None,
              feature_version: str | None = None) -> dict[str, Any]:
    """The domain's inputs from the tables, as known at ``as_of``. ``model`` selects which model's predictions and publications are read."""
    lv = (conn.execute("SELECT * FROM label_versions WHERE label_version_id = %s", (label_version,)).fetchone() if label_version
          else conn.execute("SELECT * FROM label_versions ORDER BY label_version_id LIMIT 1").fetchone())
    fv = (conn.execute("SELECT * FROM feature_versions WHERE feature_version = %s", (feature_version,)).fetchone() if feature_version
          else conn.execute("SELECT * FROM feature_versions ORDER BY feature_version LIMIT 1").fetchone())
    data: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION, "as_of": iso_z(as_of),
        "label_version": dict(lv) if lv else {"label_version_id": "none", "horizon_days": 90, "grace_days": 14},
        "feature_version_spec": dict(fv) if fv else {"feature_version": "none", "observation_days": 90}}
    fvn = data["feature_version_spec"]["feature_version"]
    data["accounts"] = _q(conn, "SELECT account_id, created_at, segment, region, synthetic FROM accounts ORDER BY account_id")
    for table, key, extra in (("subscription_events", "subscription_event_id", "event_type"), ("billing_events", "billing_event_id", "amount"),
                              ("usage_events", "usage_event_id", "event_name"), ("support_events", "support_event_id", "severity")):
        data[table] = _q(conn, f"SELECT {key}, account_id, {extra}, event_at, available_at FROM {table} WHERE available_at <= %s "     # constants
                               f"ORDER BY {key} COLLATE \"C\"", as_of)
    data["prediction_cutoffs"] = _q(conn, "SELECT cutoff_id, account_id, prediction_at, horizon_end, observation_start FROM prediction_cutoffs "
                                          "ORDER BY cutoff_id COLLATE \"C\"")
    data["feature_rows"] = _q(conn, "SELECT feature_row_id, cutoff_id, feature_version, features_json, max_available_at FROM feature_rows "
                                    "WHERE feature_version = %s ORDER BY feature_row_id COLLATE \"C\"", fvn)
    data["labels"] = _q(conn, "SELECT label_id, cutoff_id, churned, label_end, mature FROM labels ORDER BY label_id COLLATE \"C\"")
    data["training_runs"] = _q(conn, "SELECT training_run_id, train_end, validation_end, test_end, config, config_hash FROM training_runs "
                                     "ORDER BY training_run_id COLLATE \"C\"")
    data["predictions"] = _q(conn, "SELECT prediction_id, training_run_id, cutoff_id, probability, scored_at, config_hash, feature_version, "
                                   "label_version FROM predictions WHERE model_name = %s AND scored_at <= %s ORDER BY prediction_id COLLATE \"C\"", model, as_of)
    data["intervention_scenarios"] = _q(conn, "SELECT scenario_id, capacity, contact_cost, assumed_effect, margin_value FROM intervention_scenarios "
                                              "ORDER BY scenario_id COLLATE \"C\"")
    data["outreach_events"] = _q(conn, "SELECT outreach_event_id, account_id, scenario_id, action, status FROM outreach_events "
                                       "ORDER BY outreach_event_id COLLATE \"C\"")
    data["feature_registry"] = _q(conn, "SELECT feature_name, feature_version, source_entity, window_days, post_outcome, latent, id_derived, lineage "
                                        "FROM feature_registry WHERE feature_version = %s ORDER BY feature_name COLLATE \"C\"", fvn)
    data["split_assignments"] = _q(conn, "SELECT assignment_id, training_run_id, cutoff_id, split, status, drop_reason FROM split_assignments "
                                         "ORDER BY assignment_id COLLATE \"C\"")
    data["scoring_publications"] = _q(conn, "SELECT publication_id, training_run_id, prediction_at, published_at, status FROM scoring_publications "
                                            "WHERE model_name = %s AND published_at <= %s ORDER BY publication_id COLLATE \"C\"", model, as_of)
    return data
