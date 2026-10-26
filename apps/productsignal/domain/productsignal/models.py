"""Typed records and the Population (docs/contracts.md D-01..D-05).

``parse_*`` accept a raw input row (strings, as in the fixtures) and a database row (datetime, Decimal, date) alike and raise
``DomainError(MALFORMED_RECORD)`` for anything that is not exactly the documented shape. Amounts are Decimal (2 dp), never float.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

from .contract import DEFAULT_FEATURE, MAX_ABS
from .errors import MALFORMED_RECORD, DomainError
from .timeutil import UTC, iso_z, parse_date, parse_ts, zone

Row = dict[str, Any]
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PROPORTION = re.compile(r"^(0|1)(\.\d{1,6})?$|^0?\.\d{1,6}$")


def _bad(name: str, why: str) -> DomainError:
    return DomainError(MALFORMED_RECORD, f"{name} {why}", name)


def _str(row: Row, name: str, optional: bool = False, maxlen: int = 256) -> str | None:
    v = row.get(name)
    if v is None and optional:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > maxlen or "\x00" in v:
        raise _bad(name, "must be a non-empty string")
    return v


def _bool(row: Row, name: str) -> bool:
    v = row.get(name)
    if not isinstance(v, bool):
        raise _bad(name, "must be true or false")
    return v


def _ts(row: Row, name: str, optional: bool = False) -> datetime | None:
    v = row.get(name)
    if v is None and optional:
        return None
    try:
        return parse_ts(v)
    except ValueError as exc:
        raise _bad(name, str(exc)) from None


def _tz(row: Row, name: str = "timezone") -> str:
    v = _str(row, name)
    try:
        zone(v)  # type: ignore[arg-type]
    except ValueError as exc:
        raise _bad(name, str(exc)) from None
    return v  # type: ignore[return-value]


def money(value: object, name: str) -> Decimal:
    """A decimal string with at most two decimals, finite, 0 <= value < 10^12."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise _bad(name, "must be a decimal string")
    try:
        d = Decimal(value.strip() if isinstance(value, str) else value)
    except InvalidOperation:
        raise _bad(name, "is not a decimal number") from None
    if not d.is_finite() or d < 0 or d >= MAX_ABS:
        raise _bad(name, "is out of range")
    if d != d.quantize(Decimal("0.01")):
        raise _bad(name, "carries more than 2 decimals")
    return d


def proportion(value: object, name: str) -> Fraction:
    """A decimal string with at most 6 places in [0, 1] as an exact Fraction."""
    if not isinstance(value, str) or not _PROPORTION.match(value):
        raise _bad(name, "must be a decimal string with at most 6 places in [0, 1]")
    f = Fraction(value)
    if not 0 <= f <= 1:
        raise _bad(name, "must be in [0, 1]")
    return f


# ---------------------------------------------------------------------------------------------------- entities
@dataclass(frozen=True)
class Account:
    account_id: str
    plan: str
    segment: str
    created_at: datetime
    internal: bool
    timezone: str


@dataclass(frozen=True)
class User:
    user_id: str
    account_id: str
    created_at: datetime
    timezone: str
    bot_flag: bool


@dataclass(frozen=True)
class IdentityLink:
    identity_link_id: str
    anonymous_id: str
    user_id: str
    linked_at: datetime
    rule_version: str


@dataclass(frozen=True)
class Session:
    session_id: str
    user_id: str
    started_at: datetime
    ended_at: datetime | None
    device_type: str


@dataclass(frozen=True)
class Event:
    event_id: str
    user_id: str | None
    anonymous_id: str | None
    event_name: str
    event_at: datetime
    received_at: datetime


@dataclass(frozen=True)
class EventProperty:
    property_id: str
    event_id: str
    property_key: str
    property_value: str
    value_type: str


@dataclass(frozen=True)
class Subscription:
    subscription_id: str
    account_id: str
    starts_at: datetime
    ends_at: datetime | None
    status: str
    amount_usd: Decimal


@dataclass(frozen=True)
class ExperimentVersion:
    experiment_version_id: str
    name: str
    unit_type: str
    primary_metric: str
    planned_end: datetime


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    experiment_version_id: str
    unit_id: str
    variant: str
    assigned_at: datetime


@dataclass(frozen=True)
class Exposure:
    exposure_id: str
    assignment_id: str
    exposed_at: datetime
    surface: str
    event_id: str | None


@dataclass(frozen=True)
class Observation:
    observation_id: str
    assignment_id: str
    metric_name: str
    value: str
    window_end: datetime


@dataclass(frozen=True)
class AnalysisRun:
    analysis_id: str
    experiment_version_id: str
    cutoff_at: datetime
    config_hash: str
    created_at: datetime


def parse_account(r: Row) -> Account:
    return Account(_str(r, "account_id"), _str(r, "plan"), _str(r, "segment"), _ts(r, "created_at"),  # type: ignore[arg-type]
                   _bool(r, "internal"), _tz(r))


def parse_user(r: Row) -> User:
    return User(_str(r, "user_id"), _str(r, "account_id"), _ts(r, "created_at"), _tz(r), _bool(r, "bot_flag"))  # type: ignore[arg-type]


def parse_link(r: Row) -> IdentityLink:
    return IdentityLink(_str(r, "identity_link_id"), _str(r, "anonymous_id"), _str(r, "user_id"), _ts(r, "linked_at"),  # type: ignore[arg-type]
                        _str(r, "rule_version"))  # type: ignore[arg-type]


def parse_session(r: Row) -> Session:
    return Session(_str(r, "session_id"), _str(r, "user_id"), _ts(r, "started_at"), _ts(r, "ended_at", True),  # type: ignore[arg-type]
                   _str(r, "device_type"))  # type: ignore[arg-type]


def parse_event(r: Row) -> Event:
    name = _str(r, "event_name")
    if not _NAME.match(name or ""):
        raise _bad("event_name", "must be lower-case letters, digits and underscores")
    return Event(_str(r, "event_id"), _str(r, "user_id", True), _str(r, "anonymous_id", True), name,  # type: ignore[arg-type]
                 _ts(r, "event_at"), _ts(r, "received_at"))  # type: ignore[arg-type]


def parse_property(r: Row) -> EventProperty:
    vt = _str(r, "value_type")
    if vt != "string":
        raise _bad("value_type", "must be string")
    return EventProperty(_str(r, "property_id"), _str(r, "event_id"), _str(r, "property_key"),  # type: ignore[arg-type]
                         _str(r, "property_value", maxlen=1024), vt)  # type: ignore[arg-type]


def parse_subscription(r: Row) -> Subscription:
    return Subscription(_str(r, "subscription_id"), _str(r, "account_id"), _ts(r, "starts_at"), _ts(r, "ends_at", True),  # type: ignore[arg-type]
                        _str(r, "status"), money(r.get("amount_usd"), "amount_usd"))  # type: ignore[arg-type]


def parse_version(r: Row) -> ExperimentVersion:
    return ExperimentVersion(_str(r, "experiment_version_id"), _str(r, "name"), _str(r, "unit_type"),  # type: ignore[arg-type]
                             _str(r, "primary_metric"), _ts(r, "planned_end"))  # type: ignore[arg-type]


def parse_assignment(r: Row) -> Assignment:
    return Assignment(_str(r, "assignment_id"), _str(r, "experiment_version_id"), _str(r, "unit_id"), _str(r, "variant"),  # type: ignore[arg-type]
                      _ts(r, "assigned_at"))  # type: ignore[arg-type]


def parse_exposure(r: Row) -> Exposure:
    return Exposure(_str(r, "exposure_id"), _str(r, "assignment_id"), _ts(r, "exposed_at"), _str(r, "surface"),  # type: ignore[arg-type]
                    _str(r, "event_id", True))


def parse_observation(r: Row) -> Observation:
    v = _str(r, "value")
    if v not in ("0", "1"):
        raise _bad("value", "must be '0' or '1'")
    return Observation(_str(r, "observation_id"), _str(r, "assignment_id"), _str(r, "metric_name"), v, _ts(r, "window_end"))  # type: ignore[arg-type]


def parse_run(r: Row) -> AnalysisRun:
    h = _str(r, "config_hash")
    if not _SHA.match(h or ""):
        raise _bad("config_hash", "must be 64 lower-case hex digits")
    return AnalysisRun(_str(r, "analysis_id"), _str(r, "experiment_version_id"), _ts(r, "cutoff_at"), h, _ts(r, "created_at"))  # type: ignore[arg-type]


PARSERS = {"accounts": parse_account, "users": parse_user, "identity_links": parse_link, "sessions": parse_session,
           "events": parse_event, "event_properties": parse_property, "subscriptions": parse_subscription,
           "experiment_versions": parse_version, "assignments": parse_assignment, "exposures": parse_exposure,
           "metric_observations": parse_observation, "analysis_runs": parse_run}
ID_KEYS = {"accounts": "account_id", "users": "user_id", "identity_links": "identity_link_id", "sessions": "session_id",
           "events": "event_id", "event_properties": "property_id", "subscriptions": "subscription_id",
           "experiment_versions": "experiment_version_id", "assignments": "assignment_id", "exposures": "exposure_id",
           "metric_observations": "observation_id", "analysis_runs": "analysis_id"}


# ---------------------------------------------------------------------------------------------------- plan
def canonical_json(obj: Any) -> str:
    """Compact, key-sorted JSON: the form the plan hash is taken over (D-P6-22)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def plan_hash(body: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of the plan WITHOUT ``config_hash``."""
    return hashlib.sha256(canonical_json({k: v for k, v in body.items() if k != "config_hash"}).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Plan:
    """A frozen analysis plan: the primary outcome, guardrail, horizon and allocation, fixed before any outcome is read."""
    experiment_version_id: str
    primary_metric: str
    unit_type: str
    allocation: dict[str, str]
    planned_end: datetime
    activation_window_days: int
    guardrail_metric: str
    guardrail_window_days: int
    revenue_from: datetime
    revenue_to: datetime
    confidence: str
    z: str
    srm_p_threshold: str
    srm_min_expected_cell: int
    frozen_at: datetime
    config_hash: str
    body: dict[str, Any] = field(compare=False, default_factory=dict)   # the plan as stored, without the hash

    @property
    def variants(self) -> list[str]:
        return list(self.allocation)

    @property
    def hash_valid(self) -> bool:
        return plan_hash(self.body) == self.config_hash


def _pos_int(v: Any, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 1 or v > 3650:
        raise _bad(name, "must be a positive integer")
    return v


def parse_plan(raw: Row, config_hash: str | None = None) -> Plan:
    """A plan object (the shape of ``analysis_plan`` in the inputs). ``config_hash`` may sit inside ``raw`` or be given."""
    if not isinstance(raw, dict):
        raise _bad("analysis_plan", "must be an object")
    body = {k: v for k, v in raw.items() if k != "config_hash"}
    h = config_hash if config_hash is not None else raw.get("config_hash")
    if not isinstance(h, str) or not _SHA.match(h):
        raise _bad("config_hash", "must be 64 lower-case hex digits")
    alloc = raw.get("allocation")
    if not isinstance(alloc, dict) or len(alloc) < 2 or not all(isinstance(k, str) and k for k in alloc):
        raise _bad("allocation", "must name at least two variants")
    if "control" not in alloc or "treatment" not in alloc:
        raise _bad("allocation", "must name control and treatment (lift is treatment minus control)")
    shares = {k: proportion(v, f"allocation.{k}") for k, v in alloc.items()}
    if sum(shares.values()) != 1 or any(s == 0 for s in shares.values()):
        raise _bad("allocation", "shares must be positive and sum to 1")
    guard, rw, srm = raw.get("guardrail"), raw.get("revenue_window"), raw.get("srm")
    if not isinstance(guard, dict) or not isinstance(rw, dict) or not isinstance(srm, dict):
        raise _bad("analysis_plan", "needs guardrail, revenue_window and srm objects")
    conf, z = _str(raw, "confidence"), _str(raw, "z")
    for name, v in (("confidence", conf), ("z", z), ("srm.p_threshold", srm.get("p_threshold"))):
        if not isinstance(v, str) or not re.match(r"^\d+(\.\d+)?$", v):
            raise _bad(name, "must be a decimal string")
    if not 0 < Fraction(conf) < 1 or Fraction(z) <= 0:  # type: ignore[arg-type]
        raise _bad("confidence", "must be in (0, 1) with a positive z")
    cell = srm.get("min_expected_cell")
    if isinstance(cell, bool) or not isinstance(cell, int) or cell < 0:
        raise _bad("srm.min_expected_cell", "must be a nonnegative integer")
    rf, rt = _ts(rw, "from"), _ts(rw, "to")
    if rf >= rt:  # type: ignore[operator]
        raise _bad("revenue_window", "from must be before to")
    unit = _str(raw, "unit_type")
    if unit != "account":
        raise _bad("unit_type", "must be account (the unit of randomisation and analysis)")
    plan = Plan(_str(raw, "experiment_version_id"), _str(raw, "primary_metric"), unit, dict(alloc),  # type: ignore[arg-type]
                _ts(raw, "planned_end"), _pos_int(raw.get("activation_window_days"), "activation_window_days"),  # type: ignore[arg-type]
                _str(guard, "metric"), _pos_int(guard.get("window_days"), "guardrail.window_days"), rf, rt,  # type: ignore[arg-type]
                conf, z, srm["p_threshold"], cell, _ts(raw, "frozen_at"), h, body)  # type: ignore[arg-type]
    return plan


# ---------------------------------------------------------------------------------------------------- windows
@dataclass(frozen=True)
class FunnelDef:
    definition_id: str
    version: int
    steps: tuple[str, ...]
    max_gap_hours: int
    window_from: datetime
    window_to: datetime
    created_at: datetime | None = None


def parse_funnel(r: Row, created_at: datetime | None = None) -> FunnelDef:
    steps = r.get("steps")
    if not isinstance(steps, (list, tuple)) or len(steps) < 2 or len(steps) > 20 or \
            not all(isinstance(s, str) and _NAME.match(s) for s in steps):
        raise _bad("steps", "must be 2 to 20 event names")
    if len(set(steps)) != len(steps):
        raise _bad("steps", "must be distinct")
    gap = r.get("max_gap_hours")
    if isinstance(gap, bool) or not isinstance(gap, int) or not 1 <= gap <= 24 * 365:
        raise _bad("max_gap_hours", "must be a positive integer number of hours")
    ver = r.get("version", 1)
    if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
        raise _bad("version", "must be a positive integer")
    f, t = _ts(r, "from" if "from" in r else "window_from"), _ts(r, "to" if "to" in r else "window_to")
    if f >= t:  # type: ignore[operator]
        raise _bad("window", "from must be before to")
    return FunnelDef(_str(r, "definition_id"), ver, tuple(steps), gap, f, t, created_at)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Windows:
    """The metric windows (half-open). ``signup_*`` and ``adoption_*`` and ``activation_*`` are instants, the retention cohort
    is a range of account-local calendar dates."""
    signup_from: datetime
    signup_to: datetime
    activation_from: datetime
    activation_to: datetime
    activation_days: int
    retention_from: date
    retention_to: date
    adoption_from: datetime
    adoption_to: datetime
    feature: str
    eligible_plans: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"signup_conversion": {"from": iso_z(self.signup_from), "to": iso_z(self.signup_to)},
                "activation": {"from": iso_z(self.activation_from), "to": iso_z(self.activation_to),
                               "window_days": self.activation_days},
                "retention": {"signup_from": self.retention_from.isoformat(), "signup_to": self.retention_to.isoformat()},
                "feature_adoption": {"from": iso_z(self.adoption_from), "to": iso_z(self.adoption_to),
                                     "feature": self.feature, "eligible_plans": list(self.eligible_plans)}}


def parse_windows(mw: Row) -> Windows:
    """``metric_windows`` of the inputs (the funnel entry is read by ``parse_funnel``)."""
    try:
        sc, ac, rt, fa = mw["signup_conversion"], mw["activation"], mw["retention"], mw["feature_adoption"]
    except (KeyError, TypeError):
        raise _bad("metric_windows", "needs signup_conversion, activation, retention and feature_adoption") from None
    plans = fa.get("eligible_plans")
    if not isinstance(plans, list) or not all(isinstance(p, str) for p in plans):
        raise _bad("eligible_plans", "must be a list of plan names")
    try:
        rf, rtt = parse_date(rt.get("signup_from")), parse_date(rt.get("signup_to"))
    except ValueError as exc:
        raise _bad("retention", str(exc)) from None
    w = Windows(_ts(sc, "from"), _ts(sc, "to"), _ts(ac, "from"), _ts(ac, "to"), _pos_int(ac.get("window_days"), "window_days"),  # type: ignore[arg-type]
                rf, rtt, _ts(fa, "from"), _ts(fa, "to"), _str(fa, "feature"), tuple(plans))  # type: ignore[arg-type]
    if w.signup_from >= w.signup_to or w.activation_from >= w.activation_to or w.adoption_from >= w.adoption_to or rf >= rtt:
        raise DomainError("INVALID_WINDOW", "every window must have from before to", "metric_windows")
    return w


def default_windows(cutoff: datetime) -> Windows:
    """Windows for a database that has none stored (README assumption 3): signup conversion, funnel and feature adoption
    look at the 7 days before the cutoff, activation at 28 days, the retention cohort at the seven local dates that end 35
    days before the cutoff date."""
    from datetime import timedelta
    day = cutoff.astimezone(UTC).date()
    return Windows(cutoff - timedelta(days=7), cutoff, cutoff - timedelta(days=28), cutoff, 7,
                   day - timedelta(days=42), day - timedelta(days=35), cutoff - timedelta(days=7), cutoff,
                   DEFAULT_FEATURE["feature"], tuple(DEFAULT_FEATURE["eligible_plans"]))


# ---------------------------------------------------------------------------------------------------- population
@dataclass
class Population:
    """Everything the metrics read: the twelve entities plus plans and funnel definitions. Facts only."""
    accounts: list[Account] = field(default_factory=list)
    users: list[User] = field(default_factory=list)
    identity_links: list[IdentityLink] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    event_properties: list[EventProperty] = field(default_factory=list)
    subscriptions: list[Subscription] = field(default_factory=list)
    experiment_versions: list[ExperimentVersion] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    exposures: list[Exposure] = field(default_factory=list)
    metric_observations: list[Observation] = field(default_factory=list)
    analysis_runs: list[AnalysisRun] = field(default_factory=list)
    plans: dict[str, Plan] = field(default_factory=dict)
    funnels: list[FunnelDef] = field(default_factory=list)
    windows: Windows | None = None

    @classmethod
    def from_rows(cls, rows: dict[str, list[Row]], plans: list[Plan] | None = None, funnels: list[FunnelDef] | None = None,
                  windows: Windows | None = None) -> "Population":
        """Assemble from trusted rows (database or already-validated input). The same parsers as ingest, so a stored row
        that no longer parses is an error, not a silent skip."""
        kw = {ent: [PARSERS[ent](r) for r in rows.get(ent, [])] for ent in PARSERS}
        return cls(**kw, plans={p.experiment_version_id: p for p in plans or []}, funnels=list(funnels or []), windows=windows)
