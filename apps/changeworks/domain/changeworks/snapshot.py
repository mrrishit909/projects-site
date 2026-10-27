"""The resolved inputs of a scenario (R9-01): what the scenario's figures are computed from, and a hash of it.

A scenario's figures use the plan rows (costs, benefits) that were recorded by its ``created_at`` and, for every assumption the model reads, the version it
pins or else the latest version that existed at ``created_at``. ``scenario_snapshot`` lists exactly those inputs; ``snapshot_hash`` is the SHA-256 of their
canonical JSON. C07 stores the hash with the proposal, and a read recomputes it: a proposal whose resolved inputs no longer hash to the stored value is reported
(``snapshot_verified`` false). Standard library only."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .context import Ctx
from .contract import CAPACITY_RATE_NAME, RAMP_NAME, TARGET_NAME
from .ingest import Row


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def scenario_snapshot(ctx: Ctx, sc: Row) -> dict[str, Any]:
    costs, benefits = ctx.costs(sc), ctx.benefits(sc)
    out: dict[str, Any] = {"scenario": {k: sc[k] for k in ("scenario_id", "baseline_version", "discount_rate", "rate_basis", "rate_conversion_assumption_id",
                                                           "horizon_periods", "created_at")} | {"initiative_ids": sorted(sc["initiative_ids"]),
                                                                                                "pinned_assumption_ids": sorted(sc["pinned_assumption_ids"])},
                           "rate_conversion": ctx.assumption(sc["rate_conversion_assumption_id"]) if sc["rate_conversion_assumption_id"] else None, "initiatives": {}}
    for iid in sorted(sc["initiative_ids"]):
        i = ctx.ini[iid]
        base = [b for b in ctx.acc["process_baselines"] if b["initiative_id"] == iid and b["baseline_version"] == i["baseline_version"]]
        out["initiatives"][iid] = {
            "initiative": i, "approved_baseline": base[0] if base else None,
            "assumptions": {name: ctx.pick(iid, name, sc) for name in (RAMP_NAME, TARGET_NAME, CAPACITY_RATE_NAME)},
            "costs": sorted((c for c in costs if c["initiative_id"] == iid), key=lambda c: c["cost_id"]),
            "benefits": sorted((b for b in benefits if b["initiative_id"] == iid), key=lambda b: b["benefit_id"])}
    return out


def snapshot_hash(ctx: Ctx, sc: Row) -> str:
    return hashlib.sha256(canonical(scenario_snapshot(ctx, sc)).encode()).hexdigest()
