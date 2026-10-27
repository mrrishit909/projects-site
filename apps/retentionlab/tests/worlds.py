"""A small deterministic synthetic world (shape of inputs.json, without derived rows) for the end-to-end and SQL tests.

Accounts 1..24 live in the TRAIN range (cutoffs 2025-01-01 and 2025-02-01), 25..36 in VALIDATION (2025-06-01), 37..60 in TEST (2025-10-01
and the immature 2026-03-01); 61..64 (``mixed``) have a train row and a test row, so the group purge drops their train rows. About a
third of the accounts churn (a cancel inside the 90-day horizon); churners mostly show little recent usage, with noise. Every choice is a
hash of the account id: the same world every run. The world carries no latent column: nothing here is a predictor input but the events.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from support_db import golden_inputs

UTC = timezone.utc
AS_OF = "2026-05-01T00:00:00Z"                    # the dataset's own as_of (inputs)
READ_AS_OF = "2026-05-02T00:00:00Z"               # a report read after the commands ran (the test clock starts at 2026-05-01T12:00:00Z)
TRAIN_END, VALIDATION_END, TEST_END = "2025-06-01T00:00:00Z", "2025-10-01T00:00:00Z", "2026-06-01T00:00:00Z"
SETS = {"train": ["2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z"], "validation": ["2025-06-01T00:00:00Z"],
        "test": ["2025-10-01T00:00:00Z"], "new": ["2026-03-01T00:00:00Z"]}


def h(*parts: Any) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:12], 16)


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def t(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def build_world(train: int = 24, validation: int = 12, test: int = 24, mixed: int = 4, churn_share: int = 35) -> dict[str, Any]:
    g = golden_inputs()
    w: dict[str, Any] = {"contract_version": 1, "as_of": AS_OF, "label_version": g["label_version"], "feature_version_spec": g["feature_version_spec"],
                         "feature_registry": g["feature_registry"], "accounts": [], "subscription_events": [], "billing_events": [], "usage_events": [],
                         "support_events": [], "prediction_cutoffs": [], "feature_rows": [], "labels": [], "training_runs": [], "predictions": [],
                         "intervention_scenarios": [], "outreach_events": [], "split_assignments": [], "scoring_publications": []}
    plan: list[tuple[int, list[str]]] = []
    n = 0
    for count, sets in ((train, SETS["train"]), (validation, SETS["validation"]), (test, SETS["test"] + SETS["new"]), (mixed, [SETS["train"][0], SETS["test"][0]])):
        for _ in range(count):
            n += 1
            plan.append((n, sets))
    for aid, sets in plan:
        w["accounts"].append({"account_id": aid, "created_at": "2024-01-01T00:00:00Z", "segment": ("smb", "mid", "ent")[h(aid, "seg") % 3],
                              "region": ("amer", "emea", "apac")[h(aid, "reg") % 3], "synthetic": True})
        w["subscription_events"].append({"subscription_event_id": f"se-{aid:03d}-start", "account_id": aid, "event_type": "start",
                                         "event_at": "2024-01-01T00:00:00Z", "available_at": "2024-01-01T00:00:00Z"})
        churner = h(aid, "churn") % 100 < churn_share
        active_low = churner if h(aid, "flip") % 100 >= 12 else not churner           # 12% of accounts break the pattern (noise)
        first = t(sets[0])
        cancel_base = t(sets[-1] if sets[-1] != SETS["new"][0] else SETS["test"][0])    # a churner cancels inside the horizon of its last mature cutoff
        if aid > train + validation + test:                                              # mixed: churn judged at the train cutoff (cancel after the test one is moot)
            cancel_base = t(SETS["train"][0])
        if churner:
            when = cancel_base + timedelta(days=20 + h(aid, "when") % 40)
            if aid > train + validation + test:
                churner = False                                                          # mixed accounts stay active (they are only there for the group purge)
            else:
                w["subscription_events"].append({"subscription_event_id": f"se-{aid:03d}-cancel", "account_id": aid, "event_type": "cancel",
                                                 "event_at": z(when), "available_at": z(when + timedelta(days=1))})
        for si, s in enumerate(sets):
            pa = t(s)
            cid = f"co-{aid:03d}-{pa.strftime('%Y%m%d')}"
            w["prediction_cutoffs"].append({"cutoff_id": cid, "account_id": aid, "prediction_at": s, "horizon_end": z(pa + timedelta(days=90)),
                                            "observation_start": z(pa - timedelta(days=90))})
            recent = (h(aid, si, "r") % 2) if active_low else 3 + h(aid, si, "r") % 6    # usage events in the last 30 days
            for k in range(recent):
                at = pa - timedelta(days=1 + (k * 29 // max(recent, 1)) + h(aid, si, k) % 2, hours=h(aid, si, k, "h") % 20)
                late = h(aid, si, k, "late") % 100 < 8
                w["usage_events"].append({"usage_event_id": f"ue-{aid:03d}-{si}-{k}", "account_id": aid, "event_name": "login", "event_at": z(at),
                                          "available_at": z(at + timedelta(days=2 if late else 0))})
            for k in range(h(aid, si, "old") % 4):                                          # older usage inside the observation window
                at = pa - timedelta(days=31 + k * 12 + h(aid, si, k, "o") % 5)
                w["usage_events"].append({"usage_event_id": f"ue-{aid:03d}-{si}-o{k}", "account_id": aid, "event_name": "report", "event_at": z(at),
                                          "available_at": z(at)})
            if active_low and h(aid, si, "sup") % 100 < 45 or (not active_low and h(aid, si, "sup") % 100 < 8):
                at = pa - timedelta(days=5 + h(aid, si, "sd") % 40)
                w["support_events"].append({"support_event_id": f"sup-{aid:03d}-{si}", "account_id": aid, "severity": "high", "event_at": z(at), "available_at": z(at)})
            if h(aid, si, "bill") % 100 < 80:
                at = pa - timedelta(days=10 + h(aid, si, "bd") % 60)
                w["billing_events"].append({"billing_event_id": f"bil-{aid:03d}-{si}", "account_id": aid, "amount": f"{20 + h(aid, 'amt') % 80}.50", "event_at": z(at),
                                            "available_at": z(at)})
    return w


def pipeline(client, command, run_id: str = "tr-w", score_sets: tuple[str, ...] = ("2025-10-01T00:00:00Z", "2026-03-01T00:00:00Z"),
             calibrate: bool = True) -> dict[str, Any]:
    """C01 + C02 for every set, then C03..C07 through the API; returns every response body by step."""
    out: dict[str, Any] = {}
    for pa in [p for ps in SETS.values() for p in ps]:
        out[f"features:{pa}"] = command(client, "build-point-in-time-features", {"prediction_at": pa})
        out[f"label:{pa}"] = command(client, "define-label", {"prediction_at": pa})
    out["split"] = command(client, "split-evaluation", {"training_run_id": run_id, "train_end": TRAIN_END, "validation_end": VALIDATION_END, "test_end": TEST_END})
    out["preprocessing"] = command(client, "fit-preprocessing", {"training_run_id": run_id})
    out["train"] = command(client, "train-baseline", {"training_run_id": run_id})
    if calibrate:
        out["calibrate"] = command(client, "calibrate-model", {"training_run_id": run_id})
    for pa in score_sets:
        out[f"score:{pa}"] = command(client, "score-accounts", {"training_run_id": run_id, "prediction_at": pa})
    return out
