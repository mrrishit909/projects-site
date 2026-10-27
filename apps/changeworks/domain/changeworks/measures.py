"""Per-initiative measures inside a scenario: capacity released (P09-MET-04), cost variance on the matured window (P09-MET-07, D-P9-05) and benefit
realization within one benefit type on matured periods (P09-MET-06, D-P9-12)."""
from __future__ import annotations

from fractions import Fraction as F
from typing import Any

from .cashflow import Model, expand_costs
from .context import Ctx
from .contract import BENEFIT_TYPES, TARGET_NAME
from .ingest import Row
from .numbers import canon, dec, ex, m4, money, mn, p6
from .timeutil import matured, parse_ts


def capacity_released(ctx: Ctx, sc: Row, iid: str) -> dict[str, Any]:
    """hours per period = volume x (baseline minutes_per_case - pinned target minutes_per_case) / 60, from the APPROVED baseline."""
    i = ctx.ini[iid]
    base = next((x for x in ctx.acc["process_baselines"] if x["initiative_id"] == iid and x["baseline_version"] == i["baseline_version"]), None) \
        if i["baseline_version"] else None
    tgt = ctx.pick(iid, TARGET_NAME, sc)
    cap: dict[str, Any] = {"hours": None, "reason": None, "baseline_version": i["baseline_version"],
                           "target_assumption_id": tgt["assumption_id"] if tgt else None}
    if base is None:
        cap["reason"] = "NO_APPROVED_BASELINE"
    elif tgt is None or tgt["value"] is None:
        cap["reason"] = "NO_TARGET_ASSUMPTION"
    else:
        hrs = F(base["volume"]) * (F(base["minutes_per_case"]) - dec(tgt["value"])) / 60
        cap.update({"hours": m4(hrs), "hours_exact": ex(hrs), "volume": base["volume"], "baseline_minutes_per_case": base["minutes_per_case"],
                    "target_minutes_per_case": tgt["value"]})
    return cap


def cost_variance(ctx: Ctx, sc: Row, iid: str) -> dict[str, Any]:
    """Actual cost minus the approved baseline cost over [0, min(horizon, matured periods)) (narrowed by the window); null with a reason otherwise."""
    i = ctx.ini[iid]
    wend = min(sc["horizon_periods"], ctx.M)
    lo, hi = ctx.window_periods(wend)
    cv: dict[str, Any] = {"window": {"from_period": lo, "to_period": hi}, "baseline_version": i["baseline_version"],
                          "approved_baseline_cost": None, "actual_cost": None, "variance": None, "reason": None}
    if i["baseline_version"] is None:
        cv["reason"] = "NO_APPROVED_BASELINE"
        return cv
    if hi <= lo:
        cv["reason"] = "NO_MATURED_PERIOD"
        return cv

    def rows(basis: str, version: str | None) -> list[F]:
        return [a for c in ctx.costs(sc) if c["initiative_id"] == iid and c["cost_basis"] == basis and (version is None or c["baseline_version"] == version)
                for _, p, a in expand_costs(c, hi) if p >= lo]
    bl = sum(rows("planned", i["baseline_version"]), F(0))
    act_rows = rows("actual", None)
    cv["approved_baseline_cost"] = money(bl)
    if not act_rows:
        cv["reason"] = "NO_ACTUALS"
    else:
        act = sum(act_rows, F(0))
        cv["actual_cost"] = money(act)
        cv["variance"] = money(act - bl)
    return cv


def benefit_realization(ctx: Ctx, sc: Row, iid: str, model: Model) -> tuple[dict[str, Any], list[str], list[str]]:
    """Observed comparable benefit / planned comparable benefit, within ONE type, matured periods with an observation only. Unobserved matured rows
    are listed, never counted as 0; the baseline trend sits beside the raw change and the page says "observed, not attributed". An observation counts
    when it happened and was recorded by as_of (R9-11); one recorded later is listed in ``late``. ``observed_above_trend`` is published only when every
    compared row carries a recorded trend (R9-13): otherwise it is null and the rows without a trend are listed."""
    H = sc["horizon_periods"]
    realization: dict[str, Any] = {}
    immature: list[str] = []
    late: list[str] = []
    for t in BENEFIT_TYPES:
        items = [b for b in ctx.benefits(sc) if b["initiative_id"] == iid and b["benefit_type"] == t and b["period_index"] < H]
        comp: list[tuple[Row, Row]] = []
        unobs: list[str] = []
        for b in sorted(items, key=lambda b: b["benefit_id"]):
            mine = [o for o in ctx.acc["benefit_observations"] if o["benefit_id"] == b["benefit_id"] and parse_ts(o["observed_at"]) <= ctx.as_of]
            late += [o["benefit_observation_id"] for o in mine if o.get("recorded_at") is not None and parse_ts(o["recorded_at"]) > ctx.as_of]
            obs = sorted((o for o in mine if o.get("recorded_at") is None or parse_ts(o["recorded_at"]) <= ctx.as_of),
                         key=lambda o: (parse_ts(o["observed_at"]), parse_ts(o.get("recorded_at") or o["observed_at"]), o["benefit_observation_id"]))
            if not matured(ctx.cfg, b["period_index"], ctx.as_of):
                immature += [o["benefit_observation_id"] for o in obs]
                continue
            if not ctx.period_in_window(b["period_index"]):
                continue
            if obs:
                comp.append((b, obs[-1]))
            else:
                unobs.append(b["benefit_id"])
        if not comp and not unobs:
            continue
        planned = sum((model.ramped(b) for b, _ in comp), F(0))
        observed = sum((dec(o["measured_value"]) for _, o in comp), F(0))
        trends = [dec(b["baseline_trend_per_period"]) for b, _ in comp if b["baseline_trend_per_period"] is not None]
        trend = sum(trends, F(0)) if trends else None
        missing = [b["benefit_id"] for b, _ in comp if b["baseline_trend_per_period"] is None]
        realization[t] = {"unit": "hours" if t == "capacity" else "USD", "comparable_items": [b["benefit_id"] for b, _ in comp],
                          "planned_comparable": money(planned) if comp else None, "observed_comparable": money(observed) if comp else None,
                          "realization": p6(observed / planned) if comp and planned != 0 else None,
                          "baseline_trend": mn(trend),
                          "observed_above_trend": mn(observed - trend) if trend is not None and comp and not missing else None,
                          "trend_coverage": {"complete": not missing, "rows_without_trend": missing},
                          "attribution": "observed, not attributed", "matured_unobserved_items": unobs}
    return realization, sorted(immature), sorted(late)


def canon_or_none(v: str | None) -> str | None:
    return None if v is None else canon(v)
