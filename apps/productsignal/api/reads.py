"""Read side: GET /data/{entity}, GET /data/analysis_runs/{id}, GET /data/experiment_versions/{id}/audit and GET /metrics
(docs/api-contract.md, D-02, D-04).

* Entity reads are ordered by the entity's key and paged with an opaque cursor (base64 of the last key), so pages are stable with
  no duplicates or gaps. ``from``/``to`` filter the entity's time field on the half-open window ``[from, to)``; other filters are
  equality on a whitelist of columns per entity (unknown filter: 422 INVALID_FILTER). No actor is needed.
* Metrics run the domain over the facts in the tables at ``cutoff`` (default now): only events received by the cutoff count. ``from``
  and ``to`` override the windows of the windowed metrics (signup conversion, funnel first step, activation signups, feature
  adoption, and the dates of the retention cohort); ``experiment_version_id`` picks the plan; ``group_by`` is none, variant, plan,
  segment or timezone (account-based metrics only; plan/segment/timezone also return the exploratory segment analysis with its
  Bonferroni threshold). The per-cohort retention grid is always returned.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

import psycopg
from productsignal import CONTRACT_VERSION, DomainError
from productsignal.contract import GROUPS
from productsignal.events import canonicalise
from productsignal.metrics import (Ctx, activation, compute, feature_adoption, group_values, retention, retention_grid,
                                   segment_analysis, select_funnel, select_plan)
from productsignal.timeutil import iso_z

from . import clock, db
from .errors import ApiError, detail, from_domain

Conn = psycopg.Connection[db.Row]
RESERVED = frozenset({"limit", "cursor", "from", "to"})


@dataclass(frozen=True)
class EntitySpec:
    table: str
    key: tuple[str, ...]
    time_field: str | None = None
    filters: tuple[str, ...] = field(default_factory=tuple)
    columns: str = "*"


ENTITIES: dict[str, EntitySpec] = {s.table: s for s in (
    EntitySpec("accounts", ("account_id",), "created_at", ("plan", "segment", "internal", "timezone")),
    EntitySpec("users", ("user_id",), "created_at", ("account_id", "bot_flag")),
    EntitySpec("identity_links", ("identity_link_id",), "linked_at", ("anonymous_id", "user_id", "rule_version")),
    EntitySpec("sessions", ("session_id",), "started_at", ("user_id", "device_type")),
    EntitySpec("events", ("event_id",), "event_at", ("event_name", "user_id", "anonymous_id")),
    EntitySpec("event_properties", ("property_id",), None, ("event_id", "property_key")),
    EntitySpec("subscriptions", ("subscription_id",), "starts_at", ("account_id", "status")),
    EntitySpec("experiment_versions", ("experiment_version_id",), "planned_end", ("unit_type",)),
    EntitySpec("analysis_plans", ("experiment_version_id",), "frozen_at", ("frozen_by",)),
    EntitySpec("assignments", ("assignment_id",), "assigned_at", ("experiment_version_id", "unit_id", "variant")),
    EntitySpec("exposures", ("exposure_id",), "exposed_at", ("assignment_id", "surface")),
    EntitySpec("metric_observations", ("observation_id",), "window_end", ("assignment_id", "metric_name")),
    EntitySpec("analysis_runs", ("analysis_id",), "created_at", ("experiment_version_id", "interim", "srm_verdict", "created_by"),
               "analysis_id, experiment_version_id, cutoff_at, config_hash, created_at, created_by, interim, srm_verdict, conclusive, prior_runs"),
    EntitySpec("funnel_definitions", ("definition_id", "version"), "created_at", ("definition_id",)),
    EntitySpec("guardrail_reviews", ("review_id",), "reviewed_at", ("analysis_id", "experiment_version_id", "verdict")),
    EntitySpec("decisions", ("decision_id",), "decided_at", ("experiment_version_id", "analysis_id", "decision", "decided_by")),
    EntitySpec("rejected_records", ("batch_id", "entity", "id", "reason_code", "ordinal"), "created_at", ("entity", "reason_code")),
    EntitySpec("audit_events", ("event_id",), "occurred_at", ("entity_type", "entity_id", "experiment_version_id", "action", "actor_id")),
    EntitySpec("dataset_versions", ("dataset_version",), "created_at"),
)}

_BOOL_COLUMNS = frozenset({"internal", "bot_flag", "interim"})
_INT_COLUMNS = frozenset({"version", "ordinal"})


def parse_instant(value: str, name: str) -> datetime:
    """ISO date or datetime; a missing zone means UTC."""
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "VALIDATION_FAILED", f"{name} is not an ISO-8601 date or datetime",
                       [detail(name, "INVALID_FILTER", f"{name} must be ISO-8601")]) from None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def parse_window(lo: str | None, hi: str | None) -> tuple[datetime | None, datetime | None]:
    window = (parse_instant(lo, "from") if lo else None, parse_instant(hi, "to") if hi else None)
    if window[0] is not None and window[1] is not None and window[0] >= window[1]:
        raise ApiError(422, "VALIDATION_FAILED", "from must be before to (the window is half-open)",
                       [detail("from", "INVALID_WINDOW", "from must be before to")])
    return window


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps([db.jsonable(v) for v in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, width: int) -> list[Any]:
    bad = ApiError(422, "VALIDATION_FAILED", "cursor is not valid",
                   [detail("cursor", "INVALID_CURSOR", "cursor must come from a previous next_cursor")])
    try:
        vals = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError):
        raise bad from None
    if not (isinstance(vals, list) and len(vals) == width and all(isinstance(v, (str, int)) for v in vals)):
        raise bad
    return vals


def meta(conn: Conn, applied: dict[str, Any], total: int, next_cursor: str | None, exclusions: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return {"dataset_version": row["dataset_version"] if row else "unversioned",
            "code_sha": os.environ.get("CODE_SHA", "dev"), "contract_version": CONTRACT_VERSION,
            "generated_at": iso_z(clock.now()), "applied_filters": applied,
            "total_count": total, "next_cursor": next_cursor, "exclusions": exclusions}


def _counts(conn: Conn) -> dict[str, int]:
    return {"rejected_records": conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"]}


def read_entity(entity: str, limit: int, cursor: str | None, lo: str | None, hi: str | None,
                filters: dict[str, str]) -> dict[str, Any]:
    spec = ENTITIES.get(entity)
    if spec is None:
        raise ApiError(404, "NOT_FOUND", f"unknown entity {entity!r}",
                       [detail("entity", "ENTITY_UNKNOWN", f"known: {', '.join(sorted(ENTITIES))}")])
    for name in filters:
        if name not in spec.filters:
            raise ApiError(422, "VALIDATION_FAILED", f"{entity} cannot be filtered by {name!r}",
                           [detail(name, "INVALID_FILTER", f"allowed: {', '.join(spec.filters) or 'none'}")])
    window = parse_window(lo, hi)
    if (lo or hi) and spec.time_field is None:
        raise ApiError(422, "VALIDATION_FAILED", f"{entity} has no time field to filter on",
                       [detail("from" if lo else "to", "FILTER_NOT_SUPPORTED", f"{entity} cannot be filtered by time")])
    where: list[str] = []
    params: list[Any] = []       # table and column names come from the ENTITIES constants, never from the request
    if spec.time_field and window[0] is not None:
        where.append(f"{spec.time_field} >= %s")
        params.append(window[0])
    if spec.time_field and window[1] is not None:
        where.append(f"{spec.time_field} < %s")
        params.append(window[1])
    for name, value in sorted(filters.items()):
        if name in _BOOL_COLUMNS:
            if value not in ("true", "false"):
                raise ApiError(422, "VALIDATION_FAILED", f"{name} must be true or false",
                               [detail(name, "INVALID_FILTER", f"{name} must be true or false")])
            where.append(f"{name} = %s")
            params.append(value == "true")
        else:
            where.append(f"{name} = %s")
            params.append(value)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order = ", ".join(f'{k} COLLATE "C"' if k not in _INT_COLUMNS else k for k in spec.key)
    page_where, page_params = where_sql, list(params)
    if cursor:
        after = decode_cursor(cursor, len(spec.key))
        marks = ", ".join(["%s"] * len(spec.key))
        page_where += (" AND " if where else " WHERE ") + f"({order}) > ({marks})"
        page_params += after
    with db.transaction() as conn:
        try:
            total = conn.execute(f"SELECT count(*) AS n FROM {spec.table}{where_sql}", params).fetchone()["n"]
            rows = conn.execute(f"SELECT {spec.columns} FROM {spec.table}{page_where} ORDER BY {order} LIMIT %s",
                                page_params + [limit + 1]).fetchall()
        except psycopg.errors.DataError:
            raise ApiError(422, "VALIDATION_FAILED", "a filter or the cursor is not valid for this entity",
                           [detail("cursor", "INVALID_CURSOR", "the value does not match this entity")]) from None
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor([rows[-1][k] for k in spec.key]) if more else None
        applied = {"from": iso_z(window[0]), "to": iso_z(window[1]), "limit": limit, **filters}
        return {"data": [db.jsonable_row(r) for r in rows],
                "meta": meta(conn, applied, total, next_cursor, _counts(conn)), "warnings": []}


def read_analysis_run(analysis_id: str) -> dict[str, Any]:
    """One analysis run with the result it published (never recomputed)."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM analysis_runs WHERE analysis_id = %s", (analysis_id,)).fetchone()
        if row is None:
            raise ApiError(404, "NOT_FOUND", "analysis run not found", [detail("analysis_id", "ANALYSIS_UNKNOWN", "analysis run not found")])
        return {"data": db.jsonable_row(row), "meta": meta(conn, {"analysis_id": analysis_id}, 1, None, _counts(conn)), "warnings": []}


def read_experiment_audit(xv: str) -> dict[str, Any]:
    """Everything recorded about one experiment version: the version, its frozen plan, assignments (counts by variant), runs,
    guardrail reviews, decisions and the audit trail."""
    with db.transaction() as conn:
        ver = conn.execute("SELECT * FROM experiment_versions WHERE experiment_version_id = %s", (xv,)).fetchone()
        if ver is None:
            raise ApiError(404, "NOT_FOUND", "experiment version not found",
                           [detail("experiment_version_id", "EXPERIMENT_VERSION_UNKNOWN", "experiment version not found")])

        def rows(sql: str, *args: Any) -> list[dict[str, Any]]:
            return [db.jsonable_row(r) for r in conn.execute(sql, args).fetchall()]

        data = {
            "experiment_version": db.jsonable_row(ver),
            "plan": rows("SELECT * FROM analysis_plans WHERE experiment_version_id = %s", xv),
            "assignments_by_variant": rows("SELECT variant, count(*) AS units FROM assignments WHERE experiment_version_id = %s "
                                           "GROUP BY variant ORDER BY variant", xv),
            "runs": rows("SELECT analysis_id, cutoff_at, config_hash, created_at, created_by, interim, srm_verdict, conclusive, prior_runs "
                         "FROM analysis_runs WHERE experiment_version_id = %s ORDER BY created_at, analysis_id", xv),
            "guardrail_reviews": rows("SELECT * FROM guardrail_reviews WHERE experiment_version_id = %s ORDER BY reviewed_at, review_id", xv),
            "decisions": rows("SELECT * FROM decisions WHERE experiment_version_id = %s ORDER BY decided_at, decision_id", xv),
            "audit": rows("SELECT * FROM audit_events WHERE experiment_version_id = %s ORDER BY occurred_at, event_id", xv),
        }
        return {"data": data, "meta": meta(conn, {"experiment_version_id": xv}, 1, None, _counts(conn)), "warnings": []}


def _override_windows(windows: Any, lo: datetime | None, hi: datetime | None) -> Any:
    """``from``/``to`` replace the bounds of every windowed metric (a missing bound keeps the stored one)."""
    ch: dict[str, Any] = {}
    if lo is not None:
        ch.update(signup_from=lo, activation_from=lo, adoption_from=lo, retention_from=lo.date())
    if hi is not None:
        ch.update(signup_to=hi, activation_to=hi, adoption_to=hi, retention_to=hi.date())
    w = replace(windows, **ch)
    if not (w.signup_from < w.signup_to and w.activation_from < w.activation_to and w.adoption_from < w.adoption_to
            and w.retention_from < w.retention_to):
        raise ApiError(422, "VALIDATION_FAILED", "from must be before to (the window is half-open)",
                       [detail("from", "INVALID_WINDOW", "the window must have from before to")])
    return w


def read_metrics(lo: str | None, hi: str | None, cutoff: str | None, xv: str | None, group_by: str,
                 analysis_id: str | None = None) -> dict[str, Any]:
    if group_by not in GROUPS:
        raise ApiError(422, "VALIDATION_FAILED", "unsupported group_by",
                       [detail("group_by", "INVALID_GROUP_BY", f"use one of {', '.join(GROUPS)}")])
    start, end = parse_window(lo, hi)
    now = clock.now()
    cut = parse_instant(cutoff, "cutoff") if cutoff else now.replace(microsecond=0)
    if cut > now:                       # D-10 (R6-04): a cutoff after the API clock names facts that do not exist yet
        raise ApiError(422, "VALIDATION_FAILED", "the cutoff is after the server clock",
                       [detail("cutoff", "CUTOFF_IN_FUTURE", "a read cannot be taken at a cutoff in the future")])
    with db.transaction() as conn:
        if xv is not None and conn.execute("SELECT 1 FROM experiment_versions WHERE experiment_version_id = %s", (xv,)).fetchone() is None \
                and conn.execute("SELECT 1 FROM analysis_plans WHERE experiment_version_id = %s", (xv,)).fetchone() is None:
            raise ApiError(404, "NOT_FOUND", "experiment version not found",
                           [detail("experiment_version_id", "EXPERIMENT_VERSION_UNKNOWN", "experiment version not found")])
        pop = db.load_population(conn)
        windows = _override_windows(db.load_windows(conn, cut), start, end)
        fd = select_funnel(pop)
        fwin = None
        if fd is not None and (start is not None or end is not None):
            fwin = (start or fd.window_from, end or fd.window_to)
            if fwin[0] >= fwin[1]:
                raise ApiError(422, "VALIDATION_FAILED", "from must be before to", [detail("from", "INVALID_WINDOW", "from must be before to")])
        try:
            comp = compute(pop, cut, windows, fd, xv, analysis_id, funnel_window=fwin)
        except DomainError as err:
            raise from_domain(err, "from") from None
        canon = comp.canon
        warnings = list(comp.warnings)
        data: dict[str, Any] = {"cutoff_at": iso_z(cut), "group_by": group_by, "windows": windows.as_dict(),
                                "metrics": comp.metrics, "tracking_quality": comp.tracking_quality, "identity": comp.identity,
                                "empty_population": comp.empty_population,
                                "retention_grid": retention_grid(Ctx(pop, cut, canon, None), windows)}
        plan = select_plan(pop, xv)
        if plan is None and xv is not None:                                # D-10 (R6-06): the experiment block is withheld, and said to be
            warnings.append({"code": "EXPERIMENT_WITHHELD_PLAN_NOT_FROZEN", "message": "the experiment block (outcomes by arm) is withheld "
                             "until this experiment version has a frozen analysis plan (C06 freeze-analysis-plan)", "path": "data.metrics.experiment"})
        if group_by == "variant" and plan is None and xv is not None:     # D-10 (R6-06): per-arm outcomes are not readable before the plan is frozen
            raise ApiError(409, "PLAN_NOT_FROZEN", "per-variant outcomes are withheld until the experiment version has a frozen "
                           "analysis plan (C06 freeze-analysis-plan first)",
                           [detail("group_by", "PLAN_NOT_FROZEN", "freeze the plan before reading outcomes by arm")])
        if group_by != "none":
            try:
                groups = group_values(pop, group_by, plan.experiment_version_id if plan else xv, cut)
            except DomainError as err:
                raise from_domain(err, "group_by") from None
            out = {}
            for value, accounts in groups.items():
                ctx = Ctx(pop, cut, canon, accounts)
                out[value] = {"accounts": len(accounts), "activation": activation(ctx, windows), "retention": retention(ctx, windows),
                              "feature_adoption": feature_adoption(ctx, windows)}
            data["groups"] = out
            warnings.append({"code": "GROUP_BY_NOT_APPLICABLE", "message": "signup_conversion, funnel (visitor unit) and the experiment "
                             "block are not split by group; segment results are in segment_analysis", "path": "data.groups"})
            if group_by != "variant":
                if plan is not None:
                    data["segment_analysis"] = segment_analysis(pop, cut, plan, group_by, canon)
                    warnings.append({"code": "EXPLORATORY_SEGMENT_ANALYSIS", "message": f"{data['segment_analysis']['segments_tested']} "
                                     f"segment(s) tested: the Bonferroni threshold is {data['segment_analysis']['bonferroni_threshold']}; "
                                     "segment results are never a decision basis", "path": "data.segment_analysis"})
                else:
                    data["segment_analysis"] = None
        applied = {"from": iso_z(start), "to": iso_z(end), "cutoff": iso_z(cut), "experiment_version_id": comp.experiment_version_id,
                   "group_by": group_by, "analysis_id": analysis_id}
        tq = comp.tracking_quality
        excl = {"bot_events_excluded": tq["bot_events_excluded"], "internal_events_excluded": tq["internal_events_excluded"],
                "unknown_identity": tq["unknown_identity"], "duplicates_dropped": tq["duplicates_dropped"],
                "received_after_cutoff": tq["received_after_cutoff"]}
        return {"data": data, "meta": meta(conn, applied, tq["analysed"], None, excl), "warnings": warnings}
