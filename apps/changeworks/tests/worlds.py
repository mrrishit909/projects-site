"""Small-dataset builders for the rule tests (the shape of inputs.json). Defaults are valid; every test overrides what it is about."""
from __future__ import annotations

import copy
from typing import Any

ENTITIES = ["initiatives", "process_baselines", "assumption_versions", "resources", "scenario_versions", "cost_items", "benefit_items", "dependencies",
            "stakeholder_groups", "impact_mappings", "resource_allocations", "readiness_assessments", "adoption_observations", "training_completions",
            "benefit_observations", "risk_items", "forecast_versions"]


def dataset(basis: str = "annual", as_of: str = "2028-06-30T00:00:00Z", **rows: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"contract_version": 1, "as_of": as_of, "period_basis": basis, "period_start": "2026-01-01"}
    for e in ENTITIES:
        d[e] = []
    d.update(copy.deepcopy(rows))
    return d


def ini(i: str = "i-1", dep: int = 1, base: str | None = "v1", status: str = "in_delivery", start: int = 0, dur: int = 1, elig: str = "elig-v1") -> dict[str, Any]:
    return {"initiative_id": i, "title": f"Initiative {i}", "sponsor_id": "sp-1", "status": status, "baseline_version": base, "requested_start_period": start,
            "duration_periods": dur, "deployment_period": dep, "eligibility_rule_version": elig}


def pb(i: str = "i-1", v: str = "v1", vol: int = 1200, mins: int = 10, bid: str | None = None) -> dict[str, Any]:
    return {"baseline_id": bid or f"pb-{i}-{v}", "initiative_id": i, "baseline_version": v, "volume": vol, "minutes_per_case": mins, "error_rate": "0.040000",
            "evidence_ref": "ev:timesheet", "measured_at": "2025-11-30T00:00:00Z", "reason": None}


def asm(aid: str, i: str | None, name: str, n: int = 1, value: str | None = None, values: list[str] | None = None, staff: str | None = None,
        unit: str = "x") -> dict[str, Any]:
    return {"assumption_id": aid, "initiative_id": i, "name": name, "version_number": n, "value": value, "values": values, "unit": unit,
            "rationale": "synthetic rationale", "author_id": "analyst-1", "evidence_ref": None, "staffing_change_evidence_ref": staff, "created_at": "2026-01-10T00:00:00Z"}


def sc(sid: str = "scn-1", inis: tuple[str, ...] | list[str] = ("i-1",), rate: str = "0.100000", basis: str = "annual", h: int = 3, pins: tuple[str, ...] = (),
       conv: str | None = None, status: str = "draft") -> dict[str, Any]:
    return {"scenario_id": sid, "baseline_version": "v1", "discount_rate": rate, "rate_basis": basis, "rate_conversion_assumption_id": conv, "horizon_periods": h,
            "status": status, "initiative_ids": list(inis), "pinned_assumption_ids": list(pins), "created_at": "2026-01-15T09:00:00Z"}


def cost(cid: str, i: str, key: str, typ: str, amt: str, p: int | None = None, s: int | None = None, e: int | None = None, basis: str = "planned",
         bv: str | None = None) -> dict[str, Any]:
    return {"cost_id": cid, "initiative_id": i, "cost_key": key, "cost_type": typ, "cost_basis": basis, "amount": amt, "period_index": p, "start_period": s,
            "end_period": e, "baseline_version": bv}


def ben(bid: str, i: str, typ: str, amt: str, p: int, starts: int | None = None, real: bool | None = None, ev: str | None = None, key: str | None = None,
        trend: str | None = None) -> dict[str, Any]:
    return {"benefit_id": bid, "initiative_id": i, "benefit_type": typ, "amount": amt, "period_index": p, "starts_period": p if starts is None else starts,
            "unit": "hours" if typ == "capacity" else "USD", "cash_realisation": real, "evidence_ref": ev, "benefit_source_key": key, "baseline_trend_per_period": trend}


def dep(did: str, i: str, pre: str, typ: str = "finish_to_start", lag: int = 0) -> dict[str, Any]:
    return {"dependency_id": did, "initiative_id": i, "prerequisite_id": pre, "dependency_type": typ, "lag_periods": lag}


def bo(oid: str, b: str, val: str, at: str = "2028-01-31T00:00:00Z") -> dict[str, Any]:
    return {"benefit_observation_id": oid, "benefit_id": b, "measured_value": val, "evidence_ref": "ev:ledger", "observed_at": at}


def ad(oid: str, i: str, elig: int, adopted: int, at: str, rule: str = "elig-v1") -> dict[str, Any]:
    return {"observation_id": oid, "initiative_id": i, "eligible_count": elig, "adopted_count": adopted, "observed_at": at, "eligibility_rule_version": rule}


def tc(tid: str, i: str, elig: int, done: int, at: str, rule: str = "elig-v1") -> dict[str, Any]:
    return {"training_id": tid, "initiative_id": i, "eligible_trainees": elig, "completed": done, "recorded_at": at, "eligibility_rule_version": rule}


def grp(gid: str = "g-1") -> dict[str, Any]:
    return {"group_id": gid, "group_name": "Accounts payable clerks", "owner_id": "sp-1", "affected_count": 10, "impact_level": "high"}


def ra(aid: str, g: str, dim: str, score: int, weight: str = "1.00", at: str = "2027-02-01T00:00:00Z") -> dict[str, Any]:
    return {"assessment_id": aid, "group_id": g, "dimension": dim, "score": score, "weight": weight, "assessed_at": at}


def fc(i: str, v: int, p: int, amt: str, at: str = "2026-01-20T00:00:00Z", reason: str = "Approved forecast") -> dict[str, Any]:
    return {"forecast_id": f"f-{i}-{v}-{p}", "initiative_id": i, "version_number": v, "period_index": p, "amount": amt, "reason": reason, "created_at": at}


def risk(rid: str, i: str, prob: str, impact: str) -> dict[str, Any]:
    return {"risk_id": rid, "initiative_id": i, "probability": prob, "impact": impact, "mitigation": "m"}


def alloc(aid: str, r: str, i: str, p: int, amt: str) -> dict[str, Any]:
    return {"allocation_id": aid, "resource_id": r, "initiative_id": i, "period_index": p, "amount": amt}


def resource(rid: str = "res-1", cap: str = "2.00") -> dict[str, Any]:
    return {"resource_id": rid, "name": "Data engineer pool", "capacity_per_period": cap, "unit": "FTE"}


# ------------------------------------------------------------------------------------------------------------------ seeded random populations
def random_world(seed: int) -> dict[str, Any]:
    """A reproducible random population exercising every rule: monthly or annual periods, ramps, pinned and unpinned assumptions, capacity conversions,
    avoided cost with and without evidence, shared source keys, recurring costs, actuals, observations around as_of, dependencies (acyclic) and the rest.
    Some rows are invalid on purpose; the domain rejects them and the tests load only what it accepted."""
    import random
    rnd = random.Random(seed)
    basis = rnd.choice(["annual", "monthly"])
    as_of = f"{rnd.choice([2026, 2027, 2028, 2029])}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}T00:00:00Z"
    money = lambda lo, hi: f"{rnd.randint(lo, hi)}.{rnd.choice(['00', '25', '50', '75', '10'])}"
    d = dataset(basis, as_of)
    n = rnd.randint(1, 4)
    ids = [f"i{k}" for k in range(1, n + 1)]
    for k, i in enumerate(ids):
        base = rnd.choice(["v1", "v1", None])
        d["initiatives"].append(ini(i, dep=rnd.randint(0, 2), base=base, status=rnd.choice(["candidate", "in_delivery", "assessed"]), start=rnd.randint(0, 2), dur=rnd.randint(1, 3)))
        if base:
            d["process_baselines"].append(pb(i, vol=rnd.randint(100, 5000), mins=rnd.randint(5, 40)))
        if rnd.random() < 0.3:
            d["process_baselines"].append(pb(i, "v2", vol=rnd.randint(100, 5000), mins=rnd.randint(5, 40)))
        for name, make in (("target_minutes_per_case", lambda: dict(value=str(rnd.randint(2, 30)))),
                           ("adoption_ramp", lambda: dict(values=[f"{x:.6f}" for x in sorted(rnd.random() for _ in range(rnd.randint(1, 4)))])),
                           ("capacity_hourly_rate", lambda: dict(value=money(10, 90), staff=rnd.choice(["hr:plan", None])))):
            if rnd.random() < 0.55:
                for v in range(1, rnd.randint(1, 2) + 1):
                    d["assumption_versions"].append(asm(f"a-{i}-{name[:3]}-{v}", i, name, v, **make()))
        for c in range(rnd.randint(0, 3)):
            typ, basis_c = rnd.choice(["one_time", "recurring"]), rnd.choice(["planned", "planned", "actual"])
            bv = rnd.choice(["v1", "v1", "v2", None]) if basis_c == "planned" else None
            if typ == "one_time":
                d["cost_items"].append(cost(f"c-{i}-{c}", i, f"k{c}", typ, money(10, 900), p=rnd.randint(0, 3), basis=basis_c, bv=bv))
            else:
                s = rnd.randint(0, 3)
                d["cost_items"].append(cost(f"c-{i}-{c}", i, f"k{c}", typ, money(5, 90), s=s, e=s + rnd.randint(1, 4), basis=basis_c, bv=bv))
        dep_p = d["initiatives"][-1]["deployment_period"]
        for b in range(rnd.randint(0, 5)):
            typ = rnd.choice(["cash", "revenue", "avoided_cost", "capacity", "cash"])
            starts = dep_p + rnd.randint(0, 2)
            p = starts + rnd.randint(0, 3)
            d["benefit_items"].append(ben(f"b-{i}-{b}", i, typ, money(5, 500), p, starts=starts, real=rnd.choice([None, True, False]), ev=rnd.choice([None, "budget-line:x"]),
                                          key=rnd.choice([None, "k1", "k2", "k1"]), trend=rnd.choice([None, money(1, 20)])))
            if rnd.random() < 0.5:
                d["benefit_observations"].append(bo(f"o-{i}-{b}-1", f"b-{i}-{b}", money(1, 400), f"{rnd.randint(2026, 2029)}-{rnd.randint(1, 12):02d}-15T00:00:00Z"))
            if rnd.random() < 0.2:
                d["benefit_observations"].append(bo(f"o-{i}-{b}-2", f"b-{i}-{b}", money(1, 400), f"{rnd.randint(2026, 2029)}-{rnd.randint(1, 12):02d}-20T00:00:00Z"))
        for a in range(rnd.randint(0, 3)):
            eligible = rnd.randint(0, 60)
            d["adoption_observations"].append(ad(f"ad-{i}-{a}", i, eligible, rnd.randint(0, eligible), f"{rnd.randint(2026, 2029)}-{rnd.randint(1, 12):02d}-10T00:00:00Z"))
        if rnd.random() < 0.5:
            eligible = rnd.randint(0, 60)
            d["training_completions"].append(tc(f"tc-{i}", i, eligible, rnd.randint(0, eligible), f"{rnd.randint(2026, 2029)}-{rnd.randint(1, 12):02d}-10T00:00:00Z"))
        for r in range(rnd.randint(0, 3)):
            d["risk_items"].append(risk(f"r-{i}-{r}", i, f"{rnd.random():.6f}", money(10, 5000)))
        if k and rnd.random() < 0.7:
            d["dependencies"].append(dep(f"d-{i}", i, rnd.choice(ids[:k]), rnd.choice(["finish_to_start", "start_to_start"]), rnd.randint(0, 2)))
        for p in range(rnd.randint(0, 2)):
            d["forecast_versions"].append(fc(i, 1, p, money(10, 500), at=f"{rnd.randint(2026, 2028)}-0{rnd.randint(1, 9)}-01T00:00:00Z"))
    for g in range(rnd.randint(0, 2)):
        d["stakeholder_groups"].append(grp(f"g{g}"))
        for dim in rnd.sample(["awareness", "desire", "knowledge", "ability", "reinforcement"], rnd.randint(0, 5)):
            for v in range(rnd.randint(1, 2)):
                d["readiness_assessments"].append(ra(f"ra-{g}-{dim}-{v}", f"g{g}", dim, rnd.randint(1, 5), rnd.choice(["1.00", "2.50", "0.75"]),
                                                     f"{rnd.randint(2026, 2029)}-{rnd.randint(1, 12):02d}-05T00:00:00Z"))
    d["resources"].append(resource("res-1", "3.00"))
    for a in range(rnd.randint(0, 4)):
        d["resource_allocations"].append(alloc(f"al-{a}", "res-1", rnd.choice(ids), rnd.randint(0, 3), rnd.choice(["0.50", "1.00", "1.50"])))
    if basis == "monthly":
        d["assumption_versions"].append(asm("a-conv", None, "monthly_rate_conversion", value=f"0.00{rnd.randint(10, 99)}")) if False else None
    d["assumption_versions"].append(asm("a-conv", None, "monthly_rate_conversion", value=f"0.0{rnd.randint(10, 99)}0{rnd.randint(0, 9)}0"))
    for s in range(rnd.randint(1, 2)):
        use = ids if rnd.random() < 0.5 else rnd.sample(ids, rnd.randint(1, len(ids)))
        pins = [a["assumption_id"] for a in d["assumption_versions"] if a["initiative_id"] in use and rnd.random() < 0.5]
        other = "monthly" if basis == "annual" else "annual"
        if rnd.random() < 0.4:
            d["scenario_versions"].append(sc(f"s{s}", use, rate=f"0.{rnd.randint(0, 25):02d}0000", basis=other, h=rnd.randint(2, 6), pins=pins, conv="a-conv"))
        else:
            d["scenario_versions"].append(sc(f"s{s}", use, rate=f"0.{rnd.randint(0, 25):02d}0000", basis=basis, h=rnd.randint(2, 6), pins=pins))
    return stamp_world(d, seed)


def stamp_world(d: dict[str, Any], seed: int) -> dict[str, Any]:
    """The review-9 dimensions of a random population, drawn from a stream of their own (the draws above stay what they were): scenarios created at different
    instants, assumption versions created before and after them, plan rows recorded before and after them (R9-01), observations recorded after the event and
    sometimes after as_of (R9-11)."""
    import random
    from datetime import datetime, timedelta, timezone
    r = random.Random(seed * 7919 + 13)
    base = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
    when = lambda days: (base + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for x in d["scenario_versions"]:
        x["created_at"] = when(r.randint(10, 700))
    for x in d["assumption_versions"]:
        x["created_at"] = when(r.randint(0, 700))
    for x in d["benefit_items"]:       # more claims on a shared source in a shared period, in money and in hours (R9-02, R9-03)
        if r.random() < 0.4 and x["starts_period"] <= 3:
            x["period_index"], x["benefit_source_key"] = r.choice([3, 4]) if x["starts_period"] <= 3 else x["period_index"], r.choice(["kk1", "kk2"])
            if r.random() < 0.5:
                x["benefit_type"], x["unit"], x["cash_realisation"] = "capacity", "hours", False
    for x in d["benefit_items"]:       # a baseline trend on some rows and not on others: partial coverage (R9-13)
        x["baseline_trend_per_period"] = None if r.random() < 0.35 else x["baseline_trend_per_period"] or ("5.00" if r.random() < 0.5 else None)
    if len(d["initiatives"]) >= 2 and r.random() < 0.5:        # two initiatives claim the same team's hours in one period
        for k, hours in enumerate(("40.00", "60.00")):
            i = d["initiatives"][k]
            d["benefit_items"].append(ben(f"b-kk-{k}", i["initiative_id"], "capacity", hours, 3, starts=max(i["deployment_period"], 1), real=False, key="kk3"))
    for e in ("cost_items", "benefit_items"):
        for x in d[e]:
            if r.random() < 0.3:
                x["recorded_at"] = when(r.randint(0, 800))
    for e, f, stamp in (("adoption_observations", "observed_at", "recorded_at"), ("benefit_observations", "observed_at", "recorded_at"), ("training_completions", "recorded_at", "entered_at")):
        for x in d[e]:
            if r.random() < 0.35:
                happened = datetime.strptime(x[f], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                x[stamp] = (happened + timedelta(days=r.randint(0, 400), hours=r.randint(0, 23))).strftime("%Y-%m-%dT%H:%M:%SZ")
    return d
