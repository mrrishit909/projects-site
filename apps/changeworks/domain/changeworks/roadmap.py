"""Roadmap (D-03, D-P9-08, D-P9-15): feasible starts propagated through the dependency chain, dependency delay (never negative), the binding
dependency, and the shared-capacity view of each resource. The roadmap is reported beside the cash flows and does not re-time them."""
from __future__ import annotations

from fractions import Fraction as F
from typing import Any

from .context import Ctx
from .errors import DomainError
from .ingest import Row
from .numbers import dec, money


def feasible_starts(ini: dict[str, Row], deps: list[Row]) -> dict[str, tuple[int, str | None]]:
    """``{initiative_id: (feasible start, binding dependency id)}``. FS: prerequisite feasible start + its duration + lag; SS: prerequisite feasible
    start + lag; the first dependency (by id) reaching the maximum above the requested start is the binding one. A cycle is DEPENDENCY_CYCLE."""
    out: dict[str, tuple[int, str | None]] = {}
    state: dict[str, int] = {}                    # 1 = on the stack, 2 = done

    def feasible(iid: str, path: tuple[str, ...]) -> tuple[int, str | None]:
        if state.get(iid) == 2:
            return out[iid]
        if state.get(iid) == 1:
            cyc = list(path[path.index(iid):]) + [iid]
            raise DomainError("DEPENDENCY_CYCLE", "the initiatives depend on each other in a cycle", details={"cycle": cyc})
        state[iid] = 1
        best, bind = ini[iid]["requested_start_period"], None
        for d in sorted((d for d in deps if d["initiative_id"] == iid), key=lambda d: d["dependency_id"]):
            pid = d["prerequisite_id"]
            s = feasible(pid, path + (iid,))[0] + (ini[pid]["duration_periods"] if d["dependency_type"] == "finish_to_start" else 0) + d["lag_periods"]
            if s > best:
                best, bind = s, d["dependency_id"]
        state[iid] = 2
        out[iid] = (best, bind)
        return out[iid]

    for iid in sorted(ini):
        feasible(iid, ())
    return out


def initiative_roadmap(ctx: Ctx, feas: dict[str, tuple[int, str | None]], iid: str) -> dict[str, Any]:
    i = ctx.ini[iid]
    fs, bind = feas[iid]
    # D-P9-15: allocations that would cross a capacity are refused when they are recorded, so the resource-constrained start equals the
    # dependency-feasible one and the resource delay is 0 (a levelling shift is not implemented).
    # R9-06: benefits are booked from ``deployment_period``; when that is earlier than the dependency-feasible start the plan books benefits before the work
    # can begin. The cash flow is not re-timed (D-P9-08): the inconsistency is reported, not repaired.
    warn = [{"code": "DEPLOYMENT_BEFORE_FEASIBLE_START", "deployment_period": i["deployment_period"], "dependency_feasible_start": fs,
             "periods_early": fs - i["deployment_period"]}] if i["deployment_period"] < fs else []
    return {"requested_start": i["requested_start_period"], "duration_periods": i["duration_periods"], "dependency_feasible_start": fs,
            "dependency_delay": fs - i["requested_start_period"], "binding_dependency_id": bind, "finish": fs + i["duration_periods"],
            "resource_constrained_start": fs, "resource_delay": 0, "deployment_period": i["deployment_period"], "warnings": warn}


def resource_views(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rsrc in sorted(ctx.acc["resources"], key=lambda x: x["resource_id"]):
        cap = dec(rsrc["capacity_per_period"])
        per: dict[int, F] = {}
        for a in ctx.acc["resource_allocations"]:
            if a["resource_id"] == rsrc["resource_id"]:
                per[a["period_index"]] = per.get(a["period_index"], F(0)) + dec(a["amount"])
        out[rsrc["resource_id"]] = {"capacity_per_period": money(cap), "unit": rsrc["unit"],
                                    "by_period": [{"period_index": p, "allocated": money(v), "headroom": money(cap - v)} for p, v in sorted(per.items())],
                                    "overallocated_periods": [p for p, v in sorted(per.items()) if v > cap]}
    return out
