"""Point-in-time analysis (D-01, D-P10-05..08): eligibility, features, arrived-late counts, labels with censoring, per cutoff.

A ``World`` is built from the ACCEPTED rows of an import (or of the database). Everything here is exact (integers, ``Fraction``,
``Decimal``); nothing is a float.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import errors as E
from .contract import EVENTS, FEATURES
from .numbers import money
from .timeutil import days, iso_z, parse_ts

INELIGIBLE_CREATED = "CREATED_ON_OR_AFTER_OBSERVATION_START"
INELIGIBLE_INACTIVE = "NOT_ACTIVE"


def classify_feature(registry: dict[str, dict[str, Any]], name: str) -> str | None:
    """The refusal code of one requested feature name, or None when it is a usable registered feature (D-P10-14)."""
    r = registry.get(name)
    if r:
        if r.get("post_outcome"):
            return E.POST_OUTCOME_FIELD
        if r.get("latent") or r.get("lineage") == "generator_manifest":     # D-01: a latent_ field or anything from the generator manifest
            return E.LATENT_TRUTH
        if r.get("id_derived"):
            return E.ID_FEATURE
        return None
    if name.startswith("latent_"):
        return E.LATENT_TRUTH
    if name.startswith("account_id"):
        return E.ID_FEATURE
    return E.UNKNOWN_FEATURE


class World:
    def __init__(self, data: dict[str, Any], accepted: dict[str, list[dict[str, Any]]]) -> None:
        self.data = data
        self.acc = accepted
        self.as_of = parse_ts(data["as_of"])
        lv = data["label_version"]
        self.horizon = lv["horizon_days"]
        self.grace = lv["grace_days"]
        self.obs_days = data["feature_version_spec"]["observation_days"]
        self.feature_version = data["feature_version_spec"]["feature_version"]
        self.accounts = {a["account_id"]: a for a in accepted["accounts"]}
        self.by_acct: dict[str, dict[Any, list[dict[str, Any]]]] = {e: {} for e in EVENTS}
        for e in EVENTS:
            for ev in accepted[e]:
                self.by_acct[e].setdefault(ev["account_id"], []).append(ev)
        self.cutoffs = {c["cutoff_id"]: c for c in accepted["prediction_cutoffs"]}
        self.registry = {r["feature_name"]: r for r in accepted["feature_registry"]}
        self.runs = {r["training_run_id"]: r for r in accepted["training_runs"]}
        self.scenarios = {s["scenario_id"]: s for s in accepted["intervention_scenarios"]}
        self.preds: dict[tuple[str, str], dict[str, Any]] = {(p["training_run_id"], p["cutoff_id"]): p for p in accepted["predictions"]}
        self._cache: dict[str, dict[str, Any]] = {}

    def window(self, name: str, default: int) -> int:
        r = self.registry.get(name)
        return r["window_days"] if r and r.get("window_days") else default

    def analyse(self, cutoff_id: str) -> dict[str, Any]:
        if cutoff_id in self._cache:
            return self._cache[cutoff_id]
        c = self.cutoffs[cutoff_id]
        pa, obs, he = parse_ts(c["prediction_at"]), parse_ts(c["observation_start"]), parse_ts(c["horizon_end"])
        label_end = he + days(self.grace)
        mature = label_end <= self.as_of
        aid = c["account_id"]
        row: dict[str, Any] = {"cutoff_id": cutoff_id, "account_id": aid, "prediction_at": iso_z(pa), "eligible": False,
                               "ineligible_code": None, "label_end": iso_z(label_end), "mature": mature, "churned": None,
                               "features": None, "max_available_at": None, "arrived_late": None}
        subs = self.by_acct["subscription_events"].get(aid, [])
        visible = [s for s in subs if parse_ts(s["event_at"]) < pa and parse_ts(s["available_at"]) < pa]
        latest = max(visible, key=lambda s: (parse_ts(s["event_at"]), s["subscription_event_id"])) if visible else None
        if parse_ts(self.accounts[aid]["created_at"]) >= obs:
            row["ineligible_code"] = INELIGIBLE_CREATED
        elif latest is None or latest["event_type"] == "cancel":
            row["ineligible_code"] = INELIGIBLE_INACTIVE
        else:
            row["eligible"] = True
        if row["eligible"]:
            row.update(self._features(aid, pa, obs))
            if mature:
                row["churned"] = any(s["event_type"] == "cancel" and pa <= parse_ts(s["event_at"]) < he and parse_ts(s["available_at"]) < label_end
                                     for s in subs)
        self._cache[cutoff_id] = row
        return row

    def _features(self, aid: Any, pa: Any, obs: Any) -> dict[str, Any]:
        late = {e: 0 for e in EVENTS}
        qualifying: dict[str, list[dict[str, Any]]] = {}
        for e in EVENTS[1:]:
            qualifying[e] = []
            for ev in self.by_acct[e].get(aid, []):
                if obs <= parse_ts(ev["event_at"]) < pa:
                    if parse_ts(ev["available_at"]) < pa:
                        qualifying[e].append(ev)
                    else:
                        late[e] += 1
        late["subscription_events"] = sum(1 for s in self.by_acct["subscription_events"].get(aid, [])
                                          if parse_ts(s["event_at"]) < pa <= parse_ts(s["available_at"]))
        usage = qualifying["usage_events"]
        recent = pa - days(self.window("usage_events_30d", 30))
        last = max((parse_ts(u["event_at"]) for u in usage), default=None)
        bills = [Decimal(b["amount"]) for b in qualifying["billing_events"]]
        used = [parse_ts(ev["available_at"]) for e in EVENTS[1:] for ev in qualifying[e]]
        return {"features": {
            "usage_events_30d": sum(1 for u in usage if parse_ts(u["event_at"]) >= recent),
            "days_since_last_usage": None if last is None else int((pa - last).total_seconds() // 86400),
            "high_severity_support_90d": sum(1 for s in qualifying["support_events"] if s["severity"] == "high"),
            "billing_total_90d": money(sum(bills, Decimal(0))) if bills else None},
            "max_available_at": iso_z(max(used)) if used else None,
            "arrived_late": late}

    def set_rows(self, prediction_at: str) -> list[dict[str, Any]]:
        want = parse_ts(prediction_at)
        return [self.analyse(c["cutoff_id"]) for c in self.acc["prediction_cutoffs"] if parse_ts(c["prediction_at"]) == want]

    def prediction_ats(self) -> list[str]:
        return sorted({iso_z(parse_ts(c["prediction_at"])) for c in self.acc["prediction_cutoffs"]})  # type: ignore[misc]


assert FEATURES  # the registered feature order is part of the contract
