"""Chronological split with the label-window purge and the group purge (D-02, D-P10-09)."""
from __future__ import annotations

from typing import Any

from .timeutil import days, parse_ts
from .world import World

PARTS = ("train", "validation", "test", "outside")
LABEL_WINDOW, GROUP_TEST, GROUP_VALIDATION = "LABEL_WINDOW", "GROUP_TEST", "GROUP_VALIDATION"


def split_run(world: World, run: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """Assign every cutoff row of the world to train / validation / test / outside by ``prediction_at``, then purge.

    Label purge first: a row whose label window ``[prediction_at, label_end)`` crosses the boundary of its own range
    (``label_end`` > the boundary; equal does not cross) is dropped from the earlier side. Then the group purge, counting
    membership BY RANGE (a row dropped in step one still counts for its account): an account with a test row loses its earlier
    train and validation rows (GROUP_TEST); an account with a validation row loses its train rows (GROUP_VALIDATION). Test rows are
    never purged: maturity, not purging, governs their use.
    """
    train_end, validation_end, test_end = (parse_ts(run[k]) for k in ("train_end", "validation_end", "test_end"))
    rows: list[dict[str, Any]] = []
    for c in world.acc["prediction_cutoffs"]:
        pa = parse_ts(c["prediction_at"])
        label_end = parse_ts(c["horizon_end"]) + days(world.grace)
        part = "train" if pa < train_end else "validation" if pa < validation_end else "test" if pa < test_end else "outside"
        rows.append({"cutoff_id": c["cutoff_id"], "account_id": c["account_id"], "split": part, "label_end": label_end,
                     "status": "retained", "drop_reason": None})
    test_accounts = {r["account_id"] for r in rows if r["split"] == "test"}
    validation_accounts = {r["account_id"] for r in rows if r["split"] == "validation"}
    for r in rows:
        if r["split"] == "train" and r["label_end"] > train_end or r["split"] == "validation" and r["label_end"] > validation_end:
            r["status"], r["drop_reason"] = "dropped", LABEL_WINDOW
    for r in rows:
        if r["status"] == "retained" and r["split"] in ("train", "validation"):
            if r["account_id"] in test_accounts:
                r["status"], r["drop_reason"] = "dropped", GROUP_TEST
            elif r["split"] == "train" and r["account_id"] in validation_accounts:
                r["status"], r["drop_reason"] = "dropped", GROUP_VALIDATION
    counts: dict[str, dict[str, int]] = {}
    for part in PARTS:
        pr = [r for r in rows if r["split"] == part]
        counts[part] = {"total": len(pr), "retained": sum(1 for r in pr if r["status"] == "retained"),
                        "label_window": sum(1 for r in pr if r["drop_reason"] == LABEL_WINDOW),
                        "group_test": sum(1 for r in pr if r["drop_reason"] == GROUP_TEST),
                        "group_validation": sum(1 for r in pr if r["drop_reason"] == GROUP_VALIDATION)}
    return rows, counts


def retained(rows: list[dict[str, Any]], part: str) -> set[str]:
    return {r["cutoff_id"] for r in rows if r["split"] == part and r["status"] == "retained"}
