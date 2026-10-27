"""Adoption (P09-MET-05), training completion (P09-MET-11), risk exposure (P09-MET-09), readiness (P09-MET-08) and forecast versions
(P09-FLOW-10). Adoption and training are never substituted for each other; null means unknown, never 0."""
from __future__ import annotations

from fractions import Fraction as F
from typing import Any

from .context import Ctx
from .contract import DIMENSIONS
from .numbers import canon, dec, ex, m4, money, mn, p6
from .timeutil import matured, parse_ts


def adoption(ctx: Ctx, iid: str) -> dict[str, Any]:
    rows = [o for o in ctx.acc["adoption_observations"] if o["initiative_id"] == iid]
    obs = sorted((o for o in rows if ctx.ts_visible(o["observed_at"])), key=lambda o: (parse_ts(o["observed_at"]), o["observation_id"]))
    late = sorted(o["observation_id"] for o in rows if parse_ts(o["observed_at"]) > ctx.as_of)
    series = [{"observation_id": o["observation_id"], "observed_at": o["observed_at"], "eligible_count": o["eligible_count"],
               "adopted_count": o["adopted_count"], "adoption_rate": p6(F(o["adopted_count"], o["eligible_count"])) if o["eligible_count"] else None}
              for o in obs]
    last = obs[-1] if obs else None
    return {"eligibility_rule_version": ctx.ini[iid]["eligibility_rule_version"], "adoption_rate": series[-1]["adoption_rate"] if series else None,
            "eligible_count": last["eligible_count"] if last else None, "adopted_count": last["adopted_count"] if last else None,
            "latest_observation_id": last["observation_id"] if last else None, "series": series, "excluded_after_as_of": late}


def training(ctx: Ctx, iid: str, adoption_rate: str | None) -> dict[str, Any]:
    tr = sorted((t for t in ctx.acc["training_completions"] if t["initiative_id"] == iid and ctx.ts_visible(t["recorded_at"])),
                key=lambda t: (parse_ts(t["recorded_at"]), t["training_id"]))
    tl = tr[-1] if tr else None
    rate = p6(F(tl["completed"], tl["eligible_trainees"])) if tl and tl["eligible_trainees"] else None
    return {"training_completion": rate, "eligible_trainees": tl["eligible_trainees"] if tl else None, "completed": tl["completed"] if tl else None,
            "training_id": tl["training_id"] if tl else None, "substituted_for_adoption": False,
            "differs_from_adoption": (rate != adoption_rate) if rate is not None and adoption_rate is not None else None}


def risk(ctx: Ctx, iid: str) -> dict[str, Any]:
    rs = sorted((x for x in ctx.acc["risk_items"] if x["initiative_id"] == iid), key=lambda x: x["risk_id"])
    exposure = sum((dec(x["probability"]) * dec(x["impact"]) for x in rs), F(0)) if rs else None
    return {"risk_exposure": mn(exposure), "label": "scenario estimate",
            "items": [{"risk_id": x["risk_id"], "probability": p6(dec(x["probability"])), "impact": canon(x["impact"]),
                       "expected_loss": money(dec(x["probability"]) * dec(x["impact"]))} for x in rs]}


def forecast(ctx: Ctx, iid: str) -> dict[str, Any] | None:
    """Every version in order, the original kept unchanged, latest minus original, and the observed cash values with their dates (D-P9-17)."""
    fvs = [f for f in ctx.acc["forecast_versions"] if f["initiative_id"] == iid and parse_ts(f["created_at"]) <= ctx.as_of]
    if not fvs:
        return None
    vers = []
    for v in sorted({f["version_number"] for f in fvs}):
        rows = sorted((f for f in fvs if f["version_number"] == v), key=lambda f: f["period_index"])
        vers.append({"version_number": v, "created_at": rows[0]["created_at"], "reason": rows[0]["reason"],
                     "total": money(sum((dec(f["amount"]) for f in rows), F(0))),
                     "by_period": [{"period_index": f["period_index"], "amount": canon(f["amount"])} for f in rows]})
    observed = []
    for b in sorted((b for b in ctx.acc["benefit_items"] if b["initiative_id"] == iid and b["benefit_type"] == "cash"), key=lambda b: b["benefit_id"]):
        for o in sorted((o for o in ctx.acc["benefit_observations"] if o["benefit_id"] == b["benefit_id"] and ctx.ts_visible(o["observed_at"])),
                        key=lambda o: o["benefit_observation_id"]):
            observed.append({"benefit_id": b["benefit_id"], "period_index": b["period_index"], "measured_value": canon(o["measured_value"]),
                             "observed_at": o["observed_at"], "period_matured": matured(ctx.cfg, b["period_index"], ctx.as_of)})
    return {"versions": vers, "original_version": vers[0]["version_number"], "original_preserved": True, "latest_version": vers[-1]["version_number"],
            "latest_minus_original": money(dec(vers[-1]["total"]) - dec(vers[0]["total"])), "observed": observed}


def readiness(ctx: Ctx) -> dict[str, Any]:
    """Weighted mean of the latest assessment per dimension at or before as_of (ties by id); null when nothing was assessed (D-P9-10)."""
    groups: dict[str, Any] = {}
    for g in sorted(ctx.acc["stakeholder_groups"], key=lambda g: g["group_id"]):
        latest: dict[str, dict[str, Any]] = {}
        for a in sorted((a for a in ctx.acc["readiness_assessments"] if a["group_id"] == g["group_id"] and ctx.ts_visible(a["assessed_at"])),
                        key=lambda a: (parse_ts(a["assessed_at"]), a["assessment_id"])):
            latest[a["dimension"]] = a
        dims = [latest[d] for d in DIMENSIONS if d in latest]
        sw = sum((dec(a["weight"]) for a in dims), F(0))
        score = sum((dec(a["weight"]) * a["score"] for a in dims), F(0)) / sw if dims else None
        groups[g["group_id"]] = {"affected_count": g["affected_count"], "impact_level": g["impact_level"], "readiness_score": m4(score),
                                 "readiness_exact": ex(score), "label": "assessment, not a probability", "dimensions_assessed": len(dims),
                                 "dimensions": [{"dimension": a["dimension"], "score": a["score"], "weight": canon(a["weight"]),
                                                 "assessment_id": a["assessment_id"]} for a in dims]}
    return groups
