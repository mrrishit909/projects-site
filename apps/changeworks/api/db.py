"""psycopg helpers: one connection and one transaction per request, and the domain's population assembled from the tables.

``transaction()`` commits when the block exits normally and rolls back on any exception, so a command's effects and its audit event are atomic.
Amounts, proportions and instants are formatted in SQL (``cw_dec``, ``to_char``, ``cw_iso``) so the domain sees exactly the strings of ``inputs.json``.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from changeworks.contract import ENTITIES
from changeworks.ingest import Population
from changeworks.timeutil import iso_z
from psycopg.rows import dict_row

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
    """A separate connection whose statements commit at once: keeps a refusal in the audit trail when the command's own transaction is rolled back."""
    with _connect(True) as conn:
        yield conn


def jsonable(value: Any) -> Any:
    """Row value to JSON: Decimal exactly as stored, timestamps as UTC ISO-8601 with Z."""
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


def _d(col: str) -> str:
    return f"cw_dec({col}) AS {col}"


def _p(col: str) -> str:
    return f"to_char({col}, 'FM9990.000000') AS {col}"


def _t(col: str) -> str:
    return f"cw_iso({col}) AS {col}"


def _agg(table: str, col: str, alias: str) -> str:
    return (f"(SELECT coalesce(array_agg(x.{col} ORDER BY x.{col} COLLATE \"C\"), '{{}}') FROM {table} x "
            f"WHERE x.scenario_id = scenario_versions.scenario_id) AS {alias}")


#: entity -> (table, the columns in the shape of inputs.json, extra columns for reads, key columns)
SPECS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "initiatives": ("initiatives", "initiative_id, title, sponsor_id, status, baseline_version, requested_start_period, duration_periods, deployment_period, "
                    "eligibility_rule_version", f"version, {_t('created_at')}, created_by", ("initiative_id",)),
    "process_baselines": ("process_baselines", f"baseline_id, initiative_id, baseline_version, volume, minutes_per_case, {_p('error_rate')}, evidence_ref, "
                          f"{_t('measured_at')}, reason", f"{_t('created_at')}, created_by", ("baseline_id",)),
    "assumption_versions": ("assumption_versions", f"assumption_id, initiative_id, name, version_number, value, value_list AS \"values\", unit, rationale, author_id, "
                            f"evidence_ref, staffing_change_evidence_ref, {_t('created_at')}", "", ("assumption_id",)),
    "resources": ("resources", f"resource_id, name, {_d('capacity_per_period')}, unit", "", ("resource_id",)),
    "scenario_versions": ("scenario_versions", f"scenario_id, baseline_version, {_p('discount_rate')}, rate_basis, rate_conversion_assumption_id, horizon_periods, status, "
                          f"{_agg('scenario_initiatives', 'initiative_id', 'initiative_ids')}, {_agg('scenario_pins', 'assumption_id', 'pinned_assumption_ids')}, "
                          f"{_t('created_at')}", f"created_by, {_t('proposed_at')}, proposed_by, comparison, residual_explanation", ("scenario_id",)),
    "cost_items": ("cost_items", f"cost_id, initiative_id, cost_key, cost_type, cost_basis, {_d('amount')}, period_index, start_period, end_period, baseline_version",
                   "", ("cost_id",)),
    "benefit_items": ("benefit_items", f"benefit_id, initiative_id, benefit_type, {_d('amount')}, period_index, starts_period, unit, cash_realisation, evidence_ref, "
                      f"benefit_source_key, {_d('baseline_trend_per_period')}", "", ("benefit_id",)),
    "dependencies": ("dependencies", "dependency_id, initiative_id, prerequisite_id, dependency_type, lag_periods", "", ("dependency_id",)),
    "stakeholder_groups": ("stakeholder_groups", "group_id, group_name, owner_id, affected_count, impact_level", "", ("group_id",)),
    "impact_mappings": ("impact_mappings", "mapping_id, initiative_id, group_id, operating_change, impact_level", "", ("mapping_id",)),
    "resource_allocations": ("resource_allocations", f"allocation_id, resource_id, initiative_id, period_index, {_d('amount')}", "", ("allocation_id",)),
    "readiness_assessments": ("readiness_assessments", f"assessment_id, group_id, dimension, score, {_d('weight')}, {_t('assessed_at')}", "assessed_by",
                              ("assessment_id",)),
    "adoption_observations": ("adoption_observations", f"observation_id, initiative_id, eligible_count, adopted_count, {_t('observed_at')}, eligibility_rule_version",
                              "recorded_by", ("observation_id",)),
    "training_completions": ("training_completions", f"training_id, initiative_id, eligible_trainees, completed, {_t('recorded_at')}, eligibility_rule_version",
                             "recorded_by", ("training_id",)),
    "benefit_observations": ("benefit_observations", f"benefit_observation_id, benefit_id, {_d('measured_value')}, evidence_ref, {_t('observed_at')}", "recorded_by",
                             ("benefit_observation_id",)),
    "risk_items": ("risk_items", f"risk_id, initiative_id, {_p('probability')}, {_d('impact')}, mitigation", "", ("risk_id",)),
    "forecast_versions": ("forecast_versions", f"forecast_id, initiative_id, version_number, {_d('amount')}, period_index, reason, {_t('created_at')}", "created_by",
                          ("forecast_id",)),
}


def load_population(conn: psycopg.Connection[Row]) -> Population:
    """The domain's population from the tables (rows are trusted; they are in the shape of inputs.json)."""
    cfg = conn.execute("SELECT period_basis, period_start, cw_iso(as_of) AS as_of FROM dataset_config WHERE id = 1").fetchone()
    config = {"period_basis": cfg["period_basis"], "period_start": cfg["period_start"].isoformat(), "as_of": cfg["as_of"]} if cfg else \
        {"period_basis": "annual", "period_start": "2026-01-01", "as_of": None}
    pop = Population(config)
    for ent in ENTITIES:
        table, cols, _, key = SPECS[ent]
        order = ", ".join(f'{k} COLLATE "C"' for k in key)
        pop.acc[ent] = list(conn.execute(f"SELECT {cols} FROM {table} ORDER BY {order}").fetchall())     # constants only
    pop.approvals = list(conn.execute("SELECT initiative_id, baseline_version FROM baseline_approvals ORDER BY approval_id").fetchall())
    return pop


def current_dataset_version(conn: psycopg.Connection[Row]) -> str:
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row["dataset_version"] if row else "unversioned"
