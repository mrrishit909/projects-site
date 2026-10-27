"""A tiny hand-built dataset in the shape of inputs.json, for rule tests and the smallest adversarial fixtures."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from support_db import golden_inputs

UTC = timezone.utc


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def at(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


class Mini:
    """Accounts, events and cutoffs one call at a time; the registry, versions and as_of come from the golden fixture."""

    def __init__(self, as_of: str = "2026-05-01T00:00:00Z") -> None:
        g = golden_inputs()
        self.d: dict[str, Any] = {"contract_version": 1, "as_of": as_of, "label_version": g["label_version"], "feature_version_spec": g["feature_version_spec"],
                                  "feature_registry": g["feature_registry"]}
        for e in ("accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels",
                  "training_runs", "predictions", "intervention_scenarios", "outreach_events", "split_assignments", "scoring_publications"):
            self.d[e] = []
        self.n = 0

    def account(self, aid: int, created: str = "2024-01-01T00:00:00Z", active: bool = True) -> int:
        self.d["accounts"].append({"account_id": aid, "created_at": created, "segment": "mid", "region": "amer", "synthetic": True})
        if active:
            self.event("subscription_events", aid, event_type="start", event_at=created)
        return aid

    def event(self, entity: str, aid: int, event_at: str, available_at: str | None = None, **kw: Any) -> dict[str, Any]:
        self.n += 1
        key = {"subscription_events": "subscription_event_id", "billing_events": "billing_event_id", "usage_events": "usage_event_id",
               "support_events": "support_event_id"}[entity]
        row = {key: f"{entity[:3]}-{self.n:04d}", "account_id": aid, "event_at": event_at, "available_at": available_at or event_at, **kw}
        if entity == "usage_events":
            row.setdefault("event_name", "login")
        self.d[entity].append(row)
        return row

    def cutoff(self, aid: int, prediction_at: str) -> str:
        pa = at(prediction_at)
        cid = f"co-{aid:02d}-{pa.strftime('%Y%m%d%H%M%S')}"
        self.d["prediction_cutoffs"].append({"cutoff_id": cid, "account_id": aid, "prediction_at": prediction_at, "horizon_end": z(pa + timedelta(days=90)),
                                             "observation_start": z(pa - timedelta(days=90))})
        return cid

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self.d)


def run(train_end: str = "2025-07-01T00:00:00Z", validation_end: str = "2025-12-01T00:00:00Z", test_end: str = "2026-06-01T00:00:00Z",
        run_id: str = "tr-m") -> dict[str, Any]:
    return {"training_run_id": run_id, "train_end": train_end, "validation_end": validation_end, "test_end": test_end}
