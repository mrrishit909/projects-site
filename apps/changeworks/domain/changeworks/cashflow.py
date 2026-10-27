"""Cash flow of an initiative inside a scenario (D-01, D-P9-02..04, D-P9-07, D-P9-16): one-time and expanded recurring costs, the four benefit
classes, ramps, NPV as an exact rational, simple and discounted payback, and the money-class benefit claims used by the double-count rule."""
from __future__ import annotations

from fractions import Fraction as F
from typing import Any

from .context import Ctx
from .contract import CAPACITY_RATE_NAME, MONEY_TYPES, RAMP_NAME
from .ingest import Row
from .numbers import dec, ex, m4, money, mn, p6
from .timeutil import period_date


def expand_costs(c: Row, horizon: int | None = None) -> list[tuple[Row, int, F]]:
    """One row per period of the half-open range; a one-time cost is a single row (D-01). Rows at or past ``horizon`` are dropped."""
    ps = [c["period_index"]] if c["cost_type"] == "one_time" else list(range(c["start_period"], c["end_period"]))
    return [(c, p, dec(c["amount"])) for p in ps if horizon is None or p < horizon]


def payback(cum: list[F]) -> tuple[int | None, F | None]:
    """First t with cumulative >= 0 (exactly 0 counts) and the interpolation (t-1) + (-cum[t-1]) / (cum[t] - cum[t-1]); 0 at t = 0; null if never."""
    for t, v in enumerate(cum):
        if v >= 0:
            if t == 0:
                return t, F(0)
            return t, (t - 1) + (-cum[t - 1]) / (v - cum[t - 1])
    return None, None


def payback_out(pair: tuple[int | None, F | None]) -> dict[str, Any]:
    return {"period": pair[0], "interpolated": m4(pair[1])}


class Model:
    """What a scenario fixes for one initiative: the ramp and the capacity conversion it pins (or the latest versions)."""

    def __init__(self, ctx: Ctx, sc: Row, iid: str) -> None:
        self.ramp_a = ctx.pick(iid, RAMP_NAME, sc)
        self.ramp = [dec(v) for v in self.ramp_a["values"]] if self.ramp_a and self.ramp_a["values"] else None
        self.conv_a = ctx.pick(iid, CAPACITY_RATE_NAME, sc)
        self.conv_ok = self.conv_a is not None and bool(self.conv_a.get("staffing_change_evidence_ref")) and self.conv_a["value"] is not None
        self.rate_cap = dec(self.conv_a["value"]) if self.conv_ok else None

    def ramped(self, b: Row) -> F:
        """D-P9-02: ``values[min(period - starts_period, last)]`` from the row's own ``starts_period``; the last value is held."""
        a = dec(b["amount"])
        if not self.ramp:
            return a
        k = min(max(b["period_index"] - b["starts_period"], 0), len(self.ramp) - 1)
        return a * self.ramp[k]


def initiative_cash_flow(ctx: Ctx, sc: Row, iid: str, r: F, model: Model) -> tuple[dict[str, Any], list[tuple[Any, ...]], F | None, list[F]]:
    """The dated model of one initiative: the output block, the benefit claims, the exact NPV, and the cumulative flows (for the paybacks)."""
    H = sc["horizon_periods"]
    cost_rows: dict[int, F] = {}
    planned_rows: list[dict[str, Any]] = []
    for c in ctx.acc["cost_items"]:
        if c["initiative_id"] == iid and c["cost_basis"] == "planned":
            for _, p, a in expand_costs(c, H):
                planned_rows.append({"cost_id": c["cost_id"], "cost_key": c["cost_key"], "period_index": p, "amount": money(a)})
                cost_rows[p] = cost_rows.get(p, F(0)) + a
    planned_rows.sort(key=lambda x: (x["period_index"], x["cost_id"]))
    by_class = {p: {"cash": F(0), "revenue": F(0), "avoided_cost_realised": F(0), "capacity_converted": F(0)} for p in range(H)}
    unr_by_class = {p: F(0) for p in range(H)}
    beside: list[dict[str, Any]] = []
    cap_excl: list[dict[str, Any]] = []
    cap_conv: list[dict[str, Any]] = []
    beyond: list[str] = []
    claims: list[tuple[Any, ...]] = []
    planned_money = planned_money_unramped = F(0)
    has_rows = bool(cost_rows)
    for b in sorted((b for b in ctx.acc["benefit_items"] if b["initiative_id"] == iid), key=lambda b: b["benefit_id"]):
        p = b["period_index"]
        if p >= H:
            beyond.append(b["benefit_id"])
            continue
        a, au, t = model.ramped(b), dec(b["amount"]), b["benefit_type"]
        if t in ("cash", "revenue"):
            by_class[p][t] += a
            unr_by_class[p] += au
            has_rows = True
        elif t == "avoided_cost":
            if b["cash_realisation"] and b["evidence_ref"]:          # D-P9-03: a budget line actually removed
                by_class[p]["avoided_cost_realised"] += a
                unr_by_class[p] += au
                has_rows = True
            else:
                beside.append({"benefit_id": b["benefit_id"], "period_index": p, "amount": money(a),
                               "reason": "NO_EVIDENCE_REF" if b["cash_realisation"] else "NOT_CASH_REALISED"})
        elif t == "capacity":
            if model.conv_ok:                                          # D-P9-04: a derived cash item citing the assumption and its evidence
                by_class[p]["capacity_converted"] += a * model.rate_cap
                unr_by_class[p] += au * model.rate_cap
                has_rows = True
                cap_conv.append({"source_benefit_id": b["benefit_id"], "period_index": p, "hours": money(a), "hourly_rate": money(model.rate_cap),
                                 "amount": money(a * model.rate_cap), "conversion_assumption_id": model.conv_a["assumption_id"],
                                 "staffing_change_evidence_ref": model.conv_a["staffing_change_evidence_ref"]})
            else:
                cap_excl.append({"benefit_id": b["benefit_id"], "period_index": p, "hours": money(a), "reason": "NO_CONVERSION_ASSUMPTION"})
        if t in MONEY_TYPES:                                           # dollars and hours are never added
            planned_money += a
            planned_money_unramped += au
            claims.append((b["benefit_source_key"], p, iid, b["benefit_id"], a))
        elif t == "capacity" and model.conv_ok:
            planned_money += a * model.rate_cap
            planned_money_unramped += au * model.rate_cap
            claims.append((b["benefit_source_key"], p, iid, b["benefit_id"], a * model.rate_cap))
    rows: list[dict[str, Any]] = []
    cum = cumd = F(0)
    cfs: list[F] = []
    cumds: list[F] = []
    for p in range(H):
        bc = by_class[p]
        ben_total = sum(bc.values(), F(0))
        cf = ben_total - cost_rows.get(p, F(0))
        df = 1 / (1 + r) ** p
        d = cf * df
        cum += cf
        cumd += d
        cfs.append(cf)
        cumds.append(cumd)
        rows.append({"period_index": p, "period_start": period_date(ctx.cfg, p).isoformat(), "costs": money(cost_rows.get(p, F(0))),
                     "benefits_by_class": {k: money(v) for k, v in bc.items()}, "cash_benefits": money(ben_total), "net_cash_flow": money(cf),
                     "cumulative": money(cum), "discount_factor": p6(df), "discount_factor_exact": ex(df), "discounted_cash_flow": money(d),
                     "discounted_exact": ex(d), "cumulative_discounted": money(cumd)})
    npv = sum((c * (1 / (1 + r) ** p) for p, c in enumerate(cfs)), F(0)) if has_rows else None
    cum_list = [sum(cfs[:k + 1], F(0)) for k in range(H)]
    sp = payback(cum_list) if has_rows else (None, None)       # D-P9-07: null for both paybacks when there are no flows
    dp = payback(cumds) if has_rows else (None, None)
    unramped = [money(unr_by_class[p] - cost_rows.get(p, F(0))) for p in range(H)] if model.ramp else None
    block = {"cash_flow": rows, "expanded_planned_costs": planned_rows,
             "excluded_from_cash_flow": {"capacity_not_converted": cap_excl,
                                         "capacity_hours_not_converted": money(sum((dec(x["hours"]) for x in cap_excl), F(0))) if cap_excl else None,
                                         "avoided_cost_beside": beside,
                                         "avoided_cost_beside_total": money(sum((dec(x["amount"]) for x in beside), F(0))) if beside else None,
                                         "beyond_horizon": beyond},
             "converted_capacity": cap_conv,
             "ramp": {"assumption_id": model.ramp_a["assumption_id"], "values": [p6(v) for v in model.ramp]} if model.ramp_a and model.ramp else None,
             "unramped_net_cash_flow": unramped,
             "planned_money_benefits": {"ramped": money(planned_money), "unramped": money(planned_money_unramped)},
             "npv": {"value": mn(npv), "exact": ex(npv), "unit": "USD", "label": "estimate"},
             "payback": {"simple": payback_out(sp), "discounted": payback_out(dp)}}
    return block, claims, npv, cum_list


def double_count(claims: list[tuple[Any, ...]]) -> dict[str, Any]:
    """D-01, D-P9-09: claims sharing a ``benefit_source_key`` in one period across two or more initiatives count once, at the largest claim."""
    planned = sum((c[4] for c in claims), F(0))
    groups: dict[tuple[Any, int], list[tuple[str, str, F]]] = {}
    for key, p, iid, bid, a in claims:
        if key is not None:
            groups.setdefault((key, p), []).append((iid, bid, a))
    overlaps: list[dict[str, Any]] = []
    removed = F(0)
    for (key, p), cl in sorted(groups.items()):
        if len({c[0] for c in cl}) >= 2:
            tot, mx = sum((c[2] for c in cl), F(0)), max(c[2] for c in cl)
            removed += tot - mx
            overlaps.append({"benefit_source_key": key, "period_index": p,
                             "claims": [{"initiative_id": c[0], "benefit_id": c[1], "amount": money(c[2])} for c in sorted(cl)],
                             "counted_once": money(mx), "overlap": money(tot - mx)})
    return {"planned_benefits": money(planned), "attributable_benefits": money(planned - removed), "residual": money(removed),
            "overlaps": overlaps, "explanation_required": removed != 0}
