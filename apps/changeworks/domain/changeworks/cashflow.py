"""Cash flow of an initiative inside a scenario (D-01, D-P9-02..04, D-P9-07, D-P9-16): one-time and expanded recurring costs, the four benefit
classes, ramps, NPV as an exact rational, simple and discounted payback, and the money-class benefit claims used by the double-count rule."""
from __future__ import annotations

from fractions import Fraction as F
from typing import Any

from .context import Ctx
from .contract import CAPACITY_RATE_NAME, MONEY_TYPES, RAMP_NAME
from .ingest import Row, has_text
from .numbers import dec, ex, m4, money, mn, p6
from .timeutil import period_date

#: the classes a money claim can have; only the first four enter the cash flow
CLAIM_CLASSES = ("cash", "revenue", "avoided_cost_realised", "capacity_converted", "avoided_cost_beside")


def expand_costs(c: Row, horizon: int | None = None) -> list[tuple[Row, int, F]]:
    """One row per period of the half-open range; a one-time cost is a single row (D-01). Rows at or past ``horizon`` are dropped."""
    ps = [c["period_index"]] if c["cost_type"] == "one_time" else list(range(c["start_period"], c["end_period"]))
    return [(c, p, dec(c["amount"])) for p in ps if horizon is None or p < horizon]


def payback(cum: list[F]) -> tuple[int | None, F | None, str | None]:
    """R9-12: the period at which the cumulative flow is back at or above 0 for good, and the interpolation (t-1) + (-cum[t-1]) / (cum[t] - cum[t-1]).

    A payback needs an investment: a series that is never negative has none (``NO_INVESTMENT``, null). The payback is the last crossing: the first period t
    after the last negative cumulative, so a series that dips below 0 again after a crossing reports the later crossing; a series that ends negative has not
    paid back within the horizon (``NOT_RECOVERED``, null). A cumulative of exactly 0 counts as back (``cum[t] >= 0``)."""
    negatives = [t for t, v in enumerate(cum) if v < 0]
    if not negatives:
        return None, None, "NO_INVESTMENT"
    last = negatives[-1]
    if last == len(cum) - 1:
        return None, None, "NOT_RECOVERED"
    t = last + 1
    return t, (t - 1) + (-cum[t - 1]) / (cum[t] - cum[t - 1]), None


def payback_out(trip: tuple[int | None, F | None, str | None]) -> dict[str, Any]:
    return {"period": trip[0], "interpolated": m4(trip[1]), "reason": trip[2]}


class Model:
    """What a scenario fixes for one initiative: the ramp and the capacity conversion it pins (or the latest versions)."""

    def __init__(self, ctx: Ctx, sc: Row, iid: str) -> None:
        self.ramp_a = ctx.pick(iid, RAMP_NAME, sc)
        self.ramp = [dec(v) for v in self.ramp_a["values"]] if self.ramp_a and self.ramp_a["values"] else None
        self.conv_a = ctx.pick(iid, CAPACITY_RATE_NAME, sc)
        self.conv_ok = self.conv_a is not None and has_text(self.conv_a.get("staffing_change_evidence_ref")) and self.conv_a["value"] is not None
        self.rate_cap = dec(self.conv_a["value"]) if self.conv_ok else None

    def ramped(self, b: Row) -> F:
        """D-P9-02: ``values[min(period - starts_period, last)]`` from the row's own ``starts_period``; the last value is held."""
        a = dec(b["amount"])
        if not self.ramp:
            return a
        k = min(max(b["period_index"] - b["starts_period"], 0), len(self.ramp) - 1)
        return a * self.ramp[k]


def initiative_cash_flow(ctx: Ctx, sc: Row, iid: str, r: F, model: Model) -> tuple[dict[str, Any], list[tuple[Any, ...]], list[tuple[Any, ...]], F | None, list[F]]:
    """The dated model of one initiative: the output block, the money claims, the hours claims, the exact NPV, and the cumulative flows (for the paybacks).
    The plan rows are the ones that existed when the scenario was created (R9-01)."""
    H = sc["horizon_periods"]
    cost_rows: dict[int, F] = {}
    planned_rows: list[dict[str, Any]] = []
    for c in ctx.costs(sc):
        if c["initiative_id"] == iid and c["cost_basis"] == "planned":
            for _, p, a in expand_costs(c, H):
                planned_rows.append({"cost_id": c["cost_id"], "cost_key": c["cost_key"], "period_index": p, "amount": money(a)})
                cost_rows[p] = cost_rows.get(p, F(0)) + a
    planned_rows.sort(key=lambda x: (x["period_index"], x["cost_id"]))
    by_class = {p: {"cash": F(0), "revenue": F(0), "avoided_cost_realised": F(0), "capacity_converted": F(0)} for p in range(H)}
    unr_by_class = {p: F(0) for p in range(H)}
    beside: list[dict[str, Any]] = []
    beside_exact: list[F] = []
    cap_excl: list[dict[str, Any]] = []
    cap_excl_exact: list[F] = []
    cap_conv: list[dict[str, Any]] = []
    beyond: list[str] = []
    claims: list[tuple[Any, ...]] = []        # (key, period, initiative, benefit, amount, class, enters the cash flow)
    hour_claims: list[tuple[Any, ...]] = []   # (key, period, initiative, benefit, hours) of every capacity row, converted or not
    planned_money = planned_money_unramped = F(0)
    has_rows = bool(cost_rows)
    for b in sorted((b for b in ctx.benefits(sc) if b["initiative_id"] == iid), key=lambda b: b["benefit_id"]):
        p = b["period_index"]
        if p >= H:
            beyond.append(b["benefit_id"])
            continue
        a, au, t = model.ramped(b), dec(b["amount"]), b["benefit_type"]
        cls = t
        if t in ("cash", "revenue"):
            by_class[p][t] += a
            unr_by_class[p] += au
            has_rows = True
        elif t == "avoided_cost":
            if b["cash_realisation"] and has_text(b["evidence_ref"]):          # D-P9-03, R9-04: a budget line actually removed, cited in words
                by_class[p]["avoided_cost_realised"] += a
                unr_by_class[p] += au
                has_rows = True
                cls = "avoided_cost_realised"
            else:
                beside.append({"benefit_id": b["benefit_id"], "period_index": p, "amount": money(a),
                               "reason": "NO_EVIDENCE_REF" if b["cash_realisation"] else "NOT_CASH_REALISED"})
                beside_exact.append(a)
                cls = "avoided_cost_beside"
        elif t == "capacity":
            hour_claims.append((b["benefit_source_key"], p, iid, b["benefit_id"], a))
            if model.conv_ok:                                          # D-P9-04: a derived cash item citing the assumption and its evidence
                by_class[p]["capacity_converted"] += a * model.rate_cap
                unr_by_class[p] += au * model.rate_cap
                has_rows = True
                cls = "capacity_converted"
                cap_conv.append({"source_benefit_id": b["benefit_id"], "period_index": p, "hours": money(a), "hourly_rate": money(model.rate_cap),
                                 "amount": money(a * model.rate_cap), "conversion_assumption_id": model.conv_a["assumption_id"],
                                 "staffing_change_evidence_ref": model.conv_a["staffing_change_evidence_ref"]})
            else:
                cap_excl.append({"benefit_id": b["benefit_id"], "period_index": p, "hours": money(a), "reason": "NO_CONVERSION_ASSUMPTION"})
                cap_excl_exact.append(a)
        if t in MONEY_TYPES:                                           # dollars and hours are never added
            planned_money += a
            planned_money_unramped += au
            claims.append((b["benefit_source_key"], p, iid, b["benefit_id"], a, cls, cls != "avoided_cost_beside"))
        elif t == "capacity" and model.conv_ok:
            planned_money += a * model.rate_cap
            planned_money_unramped += au * model.rate_cap
            claims.append((b["benefit_source_key"], p, iid, b["benefit_id"], a * model.rate_cap, cls, True))
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
    no_flows = (None, None, "NO_FLOWS")
    sp = payback(cum_list) if has_rows else no_flows          # no flows at all: nothing to pay back
    dp = payback(cumds) if has_rows else no_flows
    unramped = [money(unr_by_class[p] - cost_rows.get(p, F(0))) for p in range(H)] if model.ramp else None
    block = {"cash_flow": rows, "expanded_planned_costs": planned_rows,
             "excluded_from_cash_flow": {"capacity_not_converted": cap_excl,
                                         "capacity_hours_not_converted": money(sum(cap_excl_exact, F(0))) if cap_excl else None,      # R9-07: one rounding of the exact sum
                                         "avoided_cost_beside": beside,
                                         "avoided_cost_beside_total": money(sum(beside_exact, F(0))) if beside else None,
                                         "beyond_horizon": beyond},
             "converted_capacity": cap_conv,
             "ramp": {"assumption_id": model.ramp_a["assumption_id"], "values": [p6(v) for v in model.ramp]} if model.ramp_a and model.ramp else None,
             "unramped_net_cash_flow": unramped,
             "planned_money_benefits": {"ramped": money(planned_money), "unramped": money(planned_money_unramped)},
             "npv": {"value": mn(npv), "exact": ex(npv), "unit": "USD", "label": "estimate"},
             "payback": {"simple": payback_out(sp), "discounted": payback_out(dp)}}
    return block, claims, hour_claims, npv, cum_list


def _groups(claims: list[tuple[Any, ...]]) -> dict[tuple[Any, int], list[tuple[Any, ...]]]:
    groups: dict[tuple[Any, int], list[tuple[Any, ...]]] = {}
    for c in claims:
        if c[0] is not None:
            groups.setdefault((c[0], c[1]), []).append(c)
    return {k: v for k, v in groups.items() if len({c[2] for c in v}) >= 2}


def _retained(cl: list[tuple[Any, ...]], enters_at: int | None) -> tuple[Any, ...]:
    """The claim that counts: the largest; among equals the one that enters the cash flow, then the smallest (initiative, benefit)."""
    return sorted(cl, key=lambda c: (-c[4], 0 if enters_at is None or c[enters_at] else 1, c[2], c[3]))[0]


def double_count(claims: list[tuple[Any, ...]], hour_claims: list[tuple[Any, ...]], r: F) -> dict[str, Any]:
    """D-01, D-P9-09, R9-02, R9-03: claims sharing a ``benefit_source_key`` in one period across two or more initiatives count once, at the largest claim.
    Money (USD) and hours are two separate rules, never added; ``double_counted_amount`` is the money that counts twice and ``double_counted_pv`` its present
    value in the cash flow (the part of it that enters the cash flow, discounted period by period): NPV less that PV is the attributable NPV."""
    planned = sum((c[4] for c in claims), F(0))
    overlaps: list[dict[str, Any]] = []
    removed = pv = F(0)
    by_class = {k: F(0) for k in CLAIM_CLASSES}
    for (key, p), cl in sorted(_groups(claims).items()):
        keep = _retained(cl, 6)
        tot, mx = sum((c[4] for c in cl), F(0)), keep[4]
        removed += tot - mx
        for c in cl:
            if c is not keep:
                by_class[c[5]] += c[4]
                if c[6]:
                    pv += c[4] / (1 + r) ** p
        overlaps.append({"benefit_source_key": key, "period_index": p,
                         "claims": [{"initiative_id": c[2], "benefit_id": c[3], "amount": money(c[4]), "benefit_class": c[5], "enters_cash_flow": c[6]}
                                    for c in sorted(cl, key=lambda c: (c[2], c[3]))],
                         "counted_once": money(mx), "overlap": money(tot - mx)})
    hours_planned = sum((c[4] for c in hour_claims), F(0))
    hours_removed = F(0)
    hours_overlaps: list[dict[str, Any]] = []
    for (key, p), cl in sorted(_groups(hour_claims).items()):
        tot, mx = sum((c[4] for c in cl), F(0)), max(c[4] for c in cl)
        hours_removed += tot - mx
        hours_overlaps.append({"benefit_source_key": key, "period_index": p,
                               "claims": [{"initiative_id": c[2], "benefit_id": c[3], "hours": money(c[4])} for c in sorted(cl, key=lambda c: (c[2], c[3]))],
                               "counted_once": money(mx), "hours_residual": money(tot - mx)})
    need = [k for k, v in (("money", removed), ("hours", hours_removed)) if v != 0]
    return {"planned_benefits": money(planned), "attributable_benefits": money(planned - removed), "residual": money(removed),
            "double_counted_amount": money(removed), "double_counted_pv": money(pv), "double_counted_pv_exact": ex(pv),
            "double_counted_by_class": {k: money(v) for k, v in by_class.items()}, "double_counted_by_class_exact": {k: ex(v) for k, v in by_class.items()},
            "overlaps": overlaps,
            "planned_hours": money(hours_planned), "attributable_hours": money(hours_planned - hours_removed), "hours_residual": money(hours_removed),
            "hours_overlaps": hours_overlaps,
            "explanation_required": bool(need), "explanation_required_for": need}


def hours_components(hour_claims: list[tuple[Any, ...]]) -> list[set[str]]:
    """Initiatives that claim the same capacity (a shared key in a shared period) form one group; their released hours count once, at the largest."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for cl in _groups(hour_claims).values():
        ids = sorted({c[2] for c in cl})
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])
    comps: dict[str, set[str]] = {}
    for x in list(parent):
        comps.setdefault(find(x), set()).add(x)
    return list(comps.values())
