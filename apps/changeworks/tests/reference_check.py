#!/usr/bin/env python3
"""Independent reference calculation for the ChangeWorks golden fixtures (P09-GOLD-01..11).

Standard library only; imports nothing from the application. Recomputes every figure in expected.json from inputs.json
(entity import validation with the rejection codes of contract D-01..D-03, dependants rejected, then net cash flow with
cost expansion and benefit classes, NPV, simple and discounted payback, capacity released, adoption, training completion,
benefit realization within a benefit type on matured periods, cost variance against the approved baseline, readiness,
risk exposure, dependency delay with shared-capacity checks, the double-count residual, forecast versions) and compares
leaf by leaf for the golden case and both variants. The hand-worked figures of CALCULATION.md are typed into this file
as literals (`OK hand.*`) and checked against expected.json, not against the computation. No float anywhere:
fractions.Fraction for every ratio, rate and discount factor, decimal.Decimal for money parsing and money display.
Money 2-place strings, proportions 6-place strings, paybacks / hours / readiness 4-place strings, ROUND_HALF_UP,
half-open ranges, null never 0. Contract v1, D-01..D-04, plus decisions D-P9-01.. of CALCULATION.md.

Usage:
  python3 -I reference_check.py                  # check everything, exit 0 only if all OK
  python3 -I reference_check.py --write-expected # (re)generate the three expected.json from inputs.json, then check
  python3 -I reference_check.py --write-hashes   # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction as F
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
FIXTURES = [("golden", ""), ("variant-rejected", "variant-rejected/"), ("variant-empty", "variant-empty/")]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENT = ["initiatives", "process_baselines", "assumption_versions", "resources", "scenario_versions", "cost_items",
       "benefit_items", "dependencies", "stakeholder_groups", "impact_mappings", "resource_allocations",
       "readiness_assessments", "adoption_observations", "training_completions", "benefit_observations", "risk_items",
       "forecast_versions"]
ID = {"initiatives": "initiative_id", "process_baselines": "baseline_id", "assumption_versions": "assumption_id",
      "resources": "resource_id", "scenario_versions": "scenario_id", "cost_items": "cost_id",
      "benefit_items": "benefit_id", "dependencies": "dependency_id", "stakeholder_groups": "group_id",
      "impact_mappings": "mapping_id", "resource_allocations": "allocation_id", "readiness_assessments": "assessment_id",
      "adoption_observations": "observation_id", "training_completions": "training_id",
      "benefit_observations": "benefit_observation_id", "risk_items": "risk_id", "forecast_versions": "forecast_id"}
# entity -> [(field, parent entity, code when unknown, nullable, is_list)]
FK = {"process_baselines": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
      "assumption_versions": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", True, False)],
      "scenario_versions": [("initiative_ids", "initiatives", "UNKNOWN_INITIATIVE", False, True),
                            ("pinned_assumption_ids", "assumption_versions", "UNKNOWN_ASSUMPTION", False, True),
                            ("rate_conversion_assumption_id", "assumption_versions", "UNKNOWN_ASSUMPTION", True, False)],
      "cost_items": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
      "benefit_items": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
      "dependencies": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False),
                       ("prerequisite_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
      "impact_mappings": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False),
                          ("group_id", "stakeholder_groups", "UNKNOWN_GROUP", False, False)],
      "resource_allocations": [("resource_id", "resources", "UNKNOWN_RESOURCE", False, False),
                               ("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
      "readiness_assessments": [("group_id", "stakeholder_groups", "UNKNOWN_GROUP", False, False)],
      "adoption_observations": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
      "training_completions": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
      "benefit_observations": [("benefit_id", "benefit_items", "UNKNOWN_BENEFIT", False, False)],
      "risk_items": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
      "forecast_versions": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)]}
INI_STATUS = {"candidate", "assessed", "in_delivery", "adopted", "closed"}      # no "funded" (P09-FLOW-07)
SCN_STATUS = {"draft", "proposed"}
BEN_TYPES = ["cash", "avoided_cost", "revenue", "capacity"]
MONEY_TYPES = {"cash", "avoided_cost", "revenue"}
DIMENSIONS = ["awareness", "desire", "knowledge", "ability", "reinforcement"]
failures = 0
checks = 0


def report(ok, name, expected, got):
    global failures, checks
    checks += 1
    if ok:
        print(f"OK {name} {got}")
    else:
        failures += 1
        print(f"MISMATCH {name} expected {expected!r} got {got!r}")


# ---------------------------------------------------------------- number formats (D-04)
def rnd(x, dp):
    """ROUND_HALF_UP of a Fraction to dp places, as a string (integer arithmetic)."""
    x = F(x)
    neg = x < 0
    scaled = abs(x) * 10 ** dp
    n = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    whole, frac = divmod(n, 10 ** dp)
    s = f"{whole}.{frac:0{dp}d}" if dp else str(whole)
    return ("-" if neg and n else "") + s


def money(x):
    """2-place money string of a Fraction via Decimal ROUND_HALF_UP (cross-checked against the integer rounding)."""
    x = F(x)
    with localcontext() as c:
        c.prec = 200
        d = (Decimal(x.numerator) / Decimal(x.denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = "0.00" if d == 0 else str(d)
    assert s == rnd(x, 2), (s, rnd(x, 2))
    return s


def p6(x):
    return None if x is None else rnd(x, 6)


def m4(x):
    return None if x is None else rnd(x, 4)


def mn(x):
    return None if x is None else money(x)


def ex(x):
    """exact rational as a string"""
    return None if x is None else str(F(x))


def dec(s):
    """Money / count string -> Fraction through Decimal (exact; floats are never created)."""
    return F(Decimal(s))


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


# ---------------------------------------------------------------- calendar (D-04: integer periods, half-open)
def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def period_date(data, t):
    """period_start of period t (the start of the half-open period [t, t+1))."""
    s = date.fromisoformat(data["period_start"])
    if data["period_basis"] == "annual":
        return date(s.year + t, s.month, s.day)
    m = s.month - 1 + t
    return date(s.year + m // 12, m % 12 + 1, s.day)


def matured(data, t):
    """a period is matured when its end (= start of period t+1) is <= as_of"""
    d = period_date(data, t + 1)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) <= parse_ts(data["as_of"])


def matured_count(data):
    n = 0
    while matured(data, n):
        n += 1
    return n


# ---------------------------------------------------------------- import validation
def validate(data):
    """Return (accepted dict of lists, rejected records). Atomic per record; a record whose parent was rejected is
    DEPENDENT_REJECTED; nothing is silently dropped. Entities are processed parents first (ENT order)."""
    acc = {e: [] for e in ENT}
    rej_ids = {e: set() for e in ENT}
    rejected = []
    seen_ids = {e: set() for e in ENT}
    accid = lambda e: {r[ID[e]] for r in acc[e]}

    def conversion_exists(ini_id):
        return any(a["initiative_id"] == ini_id and a["name"] == "capacity_hourly_rate"
                   and a.get("staffing_change_evidence_ref") for a in acc["assumption_versions"])

    def cycle_from(a, b):
        """path b -> ... -> a over accepted prerequisite edges (initiative -> prerequisite); returns cycle list or None"""
        edges = {}
        for d in acc["dependencies"]:
            edges.setdefault(d["initiative_id"], []).append(d["prerequisite_id"])
        stack = [(b, [b])]
        seen = set()
        while stack:
            node, path = stack.pop()
            if node == a:
                return [a] + path
            if node in seen:
                continue
            seen.add(node)
            for nxt in sorted(edges.get(node, []), reverse=True):
                stack.append((nxt, path + [nxt]))
        return None

    def rule(e, r):
        """domain and business rules after the key checks; returns (code, details) or None"""
        if e == "initiatives":
            if r["status"] not in INI_STATUS:
                return "STATUS_NOT_ALLOWED", {"status": r["status"]}
        elif e == "assumption_versions":
            key = (r["initiative_id"], r["name"], r["version_number"])
            for a in acc[e]:
                if (a["initiative_id"], a["name"], a["version_number"]) == key:
                    return "VERSION_EXISTS", {"existing_id": a["assumption_id"], "version_number": r["version_number"]}
        elif e == "scenario_versions":
            if r["status"] not in SCN_STATUS:
                return "STATUS_NOT_ALLOWED", {"status": r["status"]}
            if r["horizon_periods"] < 1:
                return "INVALID_HORIZON", {}
            if r["rate_basis"] != data["period_basis"] and r["rate_conversion_assumption_id"] is None:
                return "RATE_PERIOD_MISMATCH", {"rate_basis": r["rate_basis"], "period_basis": data["period_basis"]}
        elif e == "cost_items":
            if r["cost_type"] == "one_time":
                if r["period_index"] is None or r["period_index"] < 0:
                    return "INVALID_PERIOD", {}
                for c in acc[e]:
                    if (c["initiative_id"], c["cost_key"], c["cost_basis"], c["cost_type"]) == \
                            (r["initiative_id"], r["cost_key"], r["cost_basis"], "one_time"):
                        return "ONE_TIME_COST_REPEATED", {"first_cost_id": c["cost_id"], "first_period": c["period_index"],
                                                          "repeat_period": r["period_index"]}
            elif r["cost_type"] == "recurring":
                if r["start_period"] is None or r["end_period"] is None or not 0 <= r["start_period"] < r["end_period"]:
                    return "INVALID_PERIOD", {}
            else:
                return "INVALID_COST_TYPE", {}
            if r["cost_basis"] not in ("planned", "actual") or dec(r["amount"]) < 0:
                return "INVALID_AMOUNT", {}
        elif e == "benefit_items":
            if r["benefit_type"] not in BEN_TYPES:
                return "INVALID_BENEFIT_TYPE", {}
            ini = next(i for i in acc["initiatives"] if i["initiative_id"] == r["initiative_id"])
            if r["starts_period"] < ini["deployment_period"]:
                return "BENEFIT_BEFORE_DEPLOYMENT", {"starts_period": r["starts_period"],
                                                      "deployment_period": ini["deployment_period"]}
            if r["period_index"] < r["starts_period"]:
                return "INVALID_PERIOD", {}
            if r["benefit_type"] == "capacity" and r["cash_realisation"] and not conversion_exists(r["initiative_id"]):
                return "CAPACITY_WITHOUT_CONVERSION", {"hours": r["amount"]}
        elif e == "dependencies":
            if r["dependency_type"] not in ("finish_to_start", "start_to_start"):
                return "INVALID_DEPENDENCY_TYPE", {}
            if r["lag_periods"] < 0:
                return "INVALID_LAG", {}
            cyc = [r["initiative_id"], r["initiative_id"]] if r["initiative_id"] == r["prerequisite_id"] \
                else cycle_from(r["initiative_id"], r["prerequisite_id"])
            if cyc:
                return "DEPENDENCY_CYCLE", {"cycle": cyc}
        elif e == "stakeholder_groups":
            if r["impact_level"] not in ("low", "medium", "high"):
                return "INVALID_IMPACT_LEVEL", {}
        elif e == "resource_allocations":
            cap = dec(next(x for x in acc["resources"] if x["resource_id"] == r["resource_id"])["capacity_per_period"])
            used = sum((dec(a["amount"]) for a in acc[e] if a["resource_id"] == r["resource_id"]
                        and a["period_index"] == r["period_index"]), F(0))
            if used + dec(r["amount"]) > cap:
                return "RESOURCE_OVERALLOCATED", {"resource_id": r["resource_id"], "periods": [r["period_index"]],
                                                  "allocated_before": money(used), "requested": r["amount"],
                                                  "capacity": money(cap)}
        elif e == "readiness_assessments":
            if r["dimension"] not in DIMENSIONS:
                return "INVALID_DIMENSION", {}
            if not isinstance(r["score"], int) or not 1 <= r["score"] <= 5:
                return "INVALID_SCORE", {"score": r["score"]}
            if dec(r["weight"]) <= 0:
                return "INVALID_WEIGHT", {}
        elif e in ("adoption_observations", "training_completions"):
            a, b = (("eligible_count", "adopted_count") if e == "adoption_observations" else ("eligible_trainees", "completed"))
            ini = next(i for i in acc["initiatives"] if i["initiative_id"] == r["initiative_id"])
            if r["eligibility_rule_version"] != ini["eligibility_rule_version"]:
                return "ELIGIBILITY_RULE_MISMATCH", {"initiative_rule": ini["eligibility_rule_version"],
                                                     "row_rule": r["eligibility_rule_version"]}
            if r[a] < 0 or r[b] < 0 or r[b] > r[a]:
                return ("ADOPTED_EXCEEDS_ELIGIBLE" if e == "adoption_observations" else "COMPLETED_EXCEEDS_ELIGIBLE"), \
                       {"eligible": r[a], "numerator": r[b]}
        elif e == "benefit_observations":
            if dec(r["measured_value"]) < 0:
                return "INVALID_AMOUNT", {}
        elif e == "risk_items":
            if not F(0) <= dec(r["probability"]) <= F(1):
                return "PROBABILITY_OUT_OF_RANGE", {"probability": r["probability"]}
            if dec(r["impact"]) < 0:
                return "INVALID_AMOUNT", {}
        elif e == "forecast_versions":
            key = (r["initiative_id"], r["version_number"], r["period_index"])
            for a in acc[e]:
                if (a["initiative_id"], a["version_number"], a["period_index"]) == key:
                    return "VERSION_EXISTS", {"existing_id": a["forecast_id"], "version_number": r["version_number"]}
        return None

    for e in ENT:
        for idx, r in enumerate(data[e]):
            rid = r[ID[e]]
            code = det = None
            if rid in seen_ids[e]:
                code, det = "DUPLICATE_ID", {}
            else:
                for field, parent, unknown, nullable, is_list in FK.get(e, []):
                    vals = r[field] if is_list else [r[field]]
                    for v in vals:
                        if v is None and nullable:
                            continue
                        if v in accid(parent):
                            continue
                        code, det = ("DEPENDENT_REJECTED", {}) if v in rej_ids[parent] else (unknown, {})
                        break
                    if code:
                        break
                if not code:
                    res = rule(e, r)
                    if res:
                        code, det = res
            if code:
                item = {"entity": e, "id": rid, "status": "rejected", "reason_code": code}
                if det:
                    item["details"] = det
                item["raw_row"] = r
                rejected.append((ENT.index(e), idx, item))
                if code != "DUPLICATE_ID":
                    rej_ids[e].add(rid)
            else:
                acc[e].append(r)
                seen_ids[e].add(rid)
    rejected.sort(key=lambda t: (t[0], t[1]))
    return acc, [t[2] for t in rejected]


# ---------------------------------------------------------------- the calculation
def expand_costs(c, H=None):
    """one row per period of the half-open range; a one-time cost is a single row (D-01)"""
    if c["cost_type"] == "one_time":
        ps = [c["period_index"]]
    else:
        ps = list(range(c["start_period"], c["end_period"]))
    return [(c, p, dec(c["amount"])) for p in ps if H is None or p < H]


def payback(cum):
    """first t with cumulative >= 0, plus linear interpolation (t-1) + (-cum[t-1]) / (cum[t] - cum[t-1]); null if never"""
    for t, v in enumerate(cum):
        if v >= 0:
            if t == 0:
                return t, F(0)
            return t, (t - 1) + (-cum[t - 1]) / (v - cum[t - 1])
    return None, None


def pb_out(pair):
    return {"period": pair[0], "interpolated": m4(pair[1])}


def compute(data):
    acc, rejected = validate(data)
    counts = {e: {"accepted": len(acc[e]), "rejected": sum(1 for r in rejected if r["entity"] == e)} for e in ENT}
    asof = parse_ts(data["as_of"])
    M = matured_count(data)
    ini = {i["initiative_id"]: i for i in acc["initiatives"]}
    ben = {b["benefit_id"]: b for b in acc["benefit_items"]}
    empty = not acc["initiatives"]

    def versions(init_id, name):
        return sorted((a for a in acc["assumption_versions"] if a["initiative_id"] == init_id and a["name"] == name),
                      key=lambda a: a["version_number"])

    def pick(init_id, name, sc):
        """the assumption version used: the one pinned by the scenario, otherwise the latest version (D-P9-14)"""
        vs = versions(init_id, name)
        pinned = [a for a in vs if a["assumption_id"] in sc["pinned_assumption_ids"]]
        return pinned[-1] if pinned else (vs[-1] if vs else None)

    # ------------------------------------------------ scenario level
    scenarios = {}
    for sc in sorted(acc["scenario_versions"], key=lambda s: s["scenario_id"]):
        H = sc["horizon_periods"]
        if sc["rate_basis"] == data["period_basis"]:
            r = dec(sc["discount_rate"])
            src = "declared"
        else:
            conv = next(a for a in acc["assumption_versions"] if a["assumption_id"] == sc["rate_conversion_assumption_id"])
            r = dec(conv["value"])
            src = "conversion:" + conv["assumption_id"]
        out_i = {}
        claims = []                      # money benefit claims for the double-count residual
        for iid in sc["initiative_ids"]:
            i = ini[iid]
            ramp_a = pick(iid, "adoption_ramp", sc)
            ramp = [dec(v) for v in ramp_a["values"]] if ramp_a else None
            conv_a = pick(iid, "capacity_hourly_rate", sc)
            conv_ok = conv_a is not None and bool(conv_a.get("staffing_change_evidence_ref"))
            rate_cap = dec(conv_a["value"]) if conv_ok else None

            def ramped(b):
                a = dec(b["amount"])
                if not ramp:
                    return a
                k = min(max(b["period_index"] - b["starts_period"], 0), len(ramp) - 1)
                return a * ramp[k]

            cost_rows = {}
            planned_rows = []
            for c in acc["cost_items"]:
                if c["initiative_id"] == iid and c["cost_basis"] == "planned":
                    for _, p, a in expand_costs(c, H):
                        planned_rows.append({"cost_id": c["cost_id"], "cost_key": c["cost_key"], "period_index": p, "amount": money(a)})
                        cost_rows[p] = cost_rows.get(p, F(0)) + a
            planned_rows.sort(key=lambda x: (x["period_index"], x["cost_id"]))
            by_class = {p: {"cash": F(0), "revenue": F(0), "avoided_cost_realised": F(0), "capacity_converted": F(0)} for p in range(H)}
            unr_by_class = {p: F(0) for p in range(H)}
            beside, cap_excl, cap_conv, beyond = [], [], [], []
            planned_money = F(0)
            planned_money_unramped = F(0)
            has_rows = bool(cost_rows)
            for b in sorted((b for b in acc["benefit_items"] if b["initiative_id"] == iid), key=lambda b: b["benefit_id"]):
                p = b["period_index"]
                if p >= H:
                    beyond.append(b["benefit_id"])
                    continue
                a, au = ramped(b), dec(b["amount"])
                t = b["benefit_type"]
                if t in ("cash", "revenue"):
                    by_class[p][t] += a
                    unr_by_class[p] += au
                    has_rows = True
                elif t == "avoided_cost":
                    if b["cash_realisation"] and b["evidence_ref"]:
                        by_class[p]["avoided_cost_realised"] += a
                        unr_by_class[p] += au
                        has_rows = True
                    else:
                        beside.append({"benefit_id": b["benefit_id"], "period_index": p, "amount": money(a),
                                       "reason": "NO_EVIDENCE_REF" if b["cash_realisation"] else "NOT_CASH_REALISED"})
                elif t == "capacity":
                    if conv_ok:
                        by_class[p]["capacity_converted"] += a * rate_cap
                        unr_by_class[p] += au * rate_cap
                        has_rows = True
                        cap_conv.append({"source_benefit_id": b["benefit_id"], "period_index": p, "hours": money(a),
                                         "hourly_rate": money(rate_cap), "amount": money(a * rate_cap),
                                         "conversion_assumption_id": conv_a["assumption_id"],
                                         "staffing_change_evidence_ref": conv_a["staffing_change_evidence_ref"]})
                    else:
                        cap_excl.append({"benefit_id": b["benefit_id"], "period_index": p, "hours": money(a),
                                         "reason": "NO_CONVERSION_ASSUMPTION"})
                # money-class claims (hours are never added to dollars)
                if t in MONEY_TYPES:
                    planned_money += a
                    planned_money_unramped += au
                    claims.append((b["benefit_source_key"], p, iid, b["benefit_id"], a))
                elif t == "capacity" and conv_ok:
                    planned_money += a * rate_cap
                    planned_money_unramped += au * rate_cap
                    claims.append((b["benefit_source_key"], p, iid, b["benefit_id"], a * rate_cap))
            rows, cum, cumd, cfs, dcfs = [], F(0), F(0), [], []
            for p in range(H):
                bc = by_class[p]
                ben_total = sum(bc.values(), F(0))
                cf = ben_total - cost_rows.get(p, F(0))
                df = 1 / (1 + r) ** p
                d = cf * df
                cum += cf
                cumd += d
                cfs.append(cf)
                dcfs.append(cumd)
                rows.append({"period_index": p, "period_start": period_date(data, p).isoformat(),
                             "costs": money(cost_rows.get(p, F(0))),
                             "benefits_by_class": {k: money(v) for k, v in bc.items()},
                             "cash_benefits": money(ben_total), "net_cash_flow": money(cf), "cumulative": money(cum),
                             "discount_factor": p6(df), "discount_factor_exact": ex(df),
                             "discounted_cash_flow": money(d), "discounted_exact": ex(d),
                             "cumulative_discounted": money(cumd)})
            npv = sum((c * (1 / (1 + r) ** p) for p, c in enumerate(cfs)), F(0)) if has_rows else None
            cum_list = [sum(cfs[:k + 1], F(0)) for k in range(H)]
            sp = payback(cum_list) if has_rows else (None, None)
            dp_ = payback(dcfs) if has_rows else (None, None)
            unramped = None
            if ramp:
                unramped = [money(unr_by_class[p] - cost_rows.get(p, F(0))) for p in range(H)]
            # capacity released (hours) from the approved baseline and the pinned target (D-01)
            base = next((x for x in acc["process_baselines"] if x["initiative_id"] == iid and x["baseline_version"] == i["baseline_version"]), None) \
                if i["baseline_version"] else None
            tgt = pick(iid, "target_minutes_per_case", sc)
            cap = {"hours": None, "reason": None, "baseline_version": i["baseline_version"], "target_assumption_id": tgt["assumption_id"] if tgt else None}
            if base is None:
                cap["reason"] = "NO_APPROVED_BASELINE"
            elif tgt is None:
                cap["reason"] = "NO_TARGET_ASSUMPTION"
            else:
                hrs = F(base["volume"]) * (F(base["minutes_per_case"]) - dec(tgt["value"])) / 60
                cap.update({"hours": m4(hrs), "volume": base["volume"], "baseline_minutes_per_case": base["minutes_per_case"],
                            "target_minutes_per_case": tgt["value"]})
            # cost variance on the matured part of the horizon, against the approved baseline (D-02, D-P9-05)
            wend = min(H, M)
            cv = {"window": {"from_period": 0, "to_period": wend}, "baseline_version": i["baseline_version"],
                  "approved_baseline_cost": None, "actual_cost": None, "variance": None, "reason": None}
            if i["baseline_version"] is None:
                cv["reason"] = "NO_APPROVED_BASELINE"
            elif wend == 0:
                cv["reason"] = "NO_MATURED_PERIOD"
            else:
                bl = sum((a for c in acc["cost_items"] if c["initiative_id"] == iid and c["cost_basis"] == "planned"
                          and c["baseline_version"] == i["baseline_version"] for _, p, a in expand_costs(c, wend)), F(0))
                act_rows = [a for c in acc["cost_items"] if c["initiative_id"] == iid and c["cost_basis"] == "actual"
                            for _, p, a in expand_costs(c, wend)]
                cv["approved_baseline_cost"] = money(bl)
                if not act_rows:
                    cv["reason"] = "NO_ACTUALS"
                else:
                    act = sum(act_rows, F(0))
                    cv["actual_cost"] = money(act)
                    cv["variance"] = money(act - bl)
            # benefit realization within one benefit type, matured periods only (D-02)
            realization, immature = {}, []
            for t in BEN_TYPES:
                items = [b for b in acc["benefit_items"] if b["initiative_id"] == iid and b["benefit_type"] == t and b["period_index"] < H]
                comp, unobs = [], []
                for b in sorted(items, key=lambda b: b["benefit_id"]):
                    obs = sorted((o for o in acc["benefit_observations"] if o["benefit_id"] == b["benefit_id"]
                                  and parse_ts(o["observed_at"]) <= asof), key=lambda o: (o["observed_at"], o["benefit_observation_id"]))
                    if not matured(data, b["period_index"]):
                        immature += [o["benefit_observation_id"] for o in obs]
                        continue
                    if obs:
                        comp.append((b, obs[-1]))
                    else:
                        unobs.append(b["benefit_id"])
                if not comp and not unobs:
                    continue
                planned = sum((ramped(b) for b, _ in comp), F(0))
                observed = sum((dec(o["measured_value"]) for _, o in comp), F(0))
                trends = [dec(b["baseline_trend_per_period"]) for b, _ in comp if b["baseline_trend_per_period"] is not None]
                trend = sum(trends, F(0)) if trends else None
                realization[t] = {"unit": "hours" if t == "capacity" else "USD",
                                  "comparable_items": [b["benefit_id"] for b, _ in comp],
                                  "planned_comparable": money(planned) if comp else None,
                                  "observed_comparable": money(observed) if comp else None,
                                  "realization": p6(observed / planned) if comp and planned != 0 else None,
                                  "baseline_trend": mn(trend), "observed_above_trend": mn(observed - trend) if trend is not None and comp else None,
                                  "attribution": "observed, not attributed",
                                  "matured_unobserved_items": unobs}
            out_i[iid] = {"cash_flow": rows,
                          "expanded_planned_costs": planned_rows,
                          "excluded_from_cash_flow": {"capacity_not_converted": cap_excl,
                                                      "capacity_hours_not_converted": money(sum((dec(x["hours"]) for x in cap_excl), F(0))) if cap_excl else None,
                                                      "avoided_cost_beside": beside,
                                                      "avoided_cost_beside_total": money(sum((dec(x["amount"]) for x in beside), F(0))) if beside else None,
                                                      "beyond_horizon": beyond},
                          "converted_capacity": cap_conv,
                          "ramp": {"assumption_id": ramp_a["assumption_id"], "values": ramp_a["values"]} if ramp_a else None,
                          "unramped_net_cash_flow": unramped,
                          "planned_money_benefits": {"ramped": money(planned_money), "unramped": money(planned_money_unramped)},
                          "npv": {"value": mn(npv), "exact": ex(npv), "unit": "USD", "label": "estimate"},
                          "payback": {"simple": pb_out(sp), "discounted": pb_out(dp_)},
                          "capacity_released": cap, "cost_variance": cv,
                          "benefit_realization": realization, "immature_observation_ids": sorted(immature)}
        # double-count residual (D-01, D-P9-09)
        planned = sum((c[4] for c in claims), F(0))
        groups = {}
        for key, p, iid, bid, a in claims:
            if key is not None:
                groups.setdefault((key, p), []).append((iid, bid, a))
        overlaps, removed = [], F(0)
        for (key, p), cl in sorted(groups.items()):
            if len({c[0] for c in cl}) >= 2:
                tot, mx = sum((c[2] for c in cl), F(0)), max(c[2] for c in cl)
                removed += tot - mx
                overlaps.append({"benefit_source_key": key, "period_index": p,
                                 "claims": [{"initiative_id": c[0], "benefit_id": c[1], "amount": money(c[2])} for c in sorted(cl)],
                                 "counted_once": money(mx), "overlap": money(tot - mx)})
        dc = {"planned_benefits": money(planned), "attributable_benefits": money(planned - removed),
              "residual": money(removed), "overlaps": overlaps, "explanation_required": removed != 0}
        npvs = [dec_exact for dec_exact in (F(x["npv"]["exact"]) for x in out_i.values() if x["npv"]["exact"] is not None)]
        scenarios[sc["scenario_id"]] = {"status": sc["status"], "baseline_version": sc["baseline_version"], "horizon_periods": H,
                                        "rate_basis": sc["rate_basis"], "declared_rate": sc["discount_rate"],
                                        "effective_period_rate": p6(r), "effective_period_rate_exact": ex(r), "rate_source": src,
                                        "initiatives": out_i, "double_count": dc,
                                        "npv_total": {"value": mn(sum(npvs, F(0))) if npvs else None, "exact": ex(sum(npvs, F(0))) if npvs else None}}

    # ------------------------------------------------ scenario-independent initiative metrics
    feas = {}
    deps = acc["dependencies"]

    def feasible(iid, stack=()):
        if iid in feas:
            return feas[iid]
        i = ini[iid]
        best, bind = i["requested_start_period"], None
        for d in sorted((d for d in deps if d["initiative_id"] == iid), key=lambda d: d["dependency_id"]):
            pid = d["prerequisite_id"]
            s = feasible(pid)[0] + (ini[pid]["duration_periods"] if d["dependency_type"] == "finish_to_start" else 0) + d["lag_periods"]
            if s > best:
                best, bind = s, d["dependency_id"]
        feas[iid] = (best, bind)
        return feas[iid]

    inits = {}
    for iid in sorted(ini):
        i = ini[iid]
        fs, bind = feasible(iid)
        roadmap = {"requested_start": i["requested_start_period"], "duration_periods": i["duration_periods"],
                   "dependency_feasible_start": fs, "dependency_delay": fs - i["requested_start_period"],
                   "binding_dependency_id": bind, "finish": fs + i["duration_periods"],
                   "resource_constrained_start": fs, "resource_delay": 0}
        obs = sorted((o for o in acc["adoption_observations"] if o["initiative_id"] == iid and parse_ts(o["observed_at"]) <= asof),
                     key=lambda o: (o["observed_at"], o["observation_id"]))
        late = sorted(o["observation_id"] for o in acc["adoption_observations"] if o["initiative_id"] == iid and parse_ts(o["observed_at"]) > asof)
        series = [{"observation_id": o["observation_id"], "observed_at": o["observed_at"], "eligible_count": o["eligible_count"],
                   "adopted_count": o["adopted_count"],
                   "adoption_rate": p6(F(o["adopted_count"], o["eligible_count"])) if o["eligible_count"] else None} for o in obs]
        last = obs[-1] if obs else None
        adoption = {"eligibility_rule_version": i["eligibility_rule_version"],
                    "adoption_rate": series[-1]["adoption_rate"] if series else None,
                    "eligible_count": last["eligible_count"] if last else None, "adopted_count": last["adopted_count"] if last else None,
                    "latest_observation_id": last["observation_id"] if last else None, "series": series,
                    "excluded_after_as_of": late}
        tr = sorted((t for t in acc["training_completions"] if t["initiative_id"] == iid and parse_ts(t["recorded_at"]) <= asof),
                    key=lambda t: (t["recorded_at"], t["training_id"]))
        tl = tr[-1] if tr else None
        trate = p6(F(tl["completed"], tl["eligible_trainees"])) if tl and tl["eligible_trainees"] else None
        training = {"training_completion": trate, "eligible_trainees": tl["eligible_trainees"] if tl else None,
                    "completed": tl["completed"] if tl else None, "training_id": tl["training_id"] if tl else None,
                    "substituted_for_adoption": False,
                    "differs_from_adoption": (trate != adoption["adoption_rate"]) if trate is not None and adoption["adoption_rate"] is not None else None}
        rs = sorted((x for x in acc["risk_items"] if x["initiative_id"] == iid), key=lambda x: x["risk_id"])
        exposure = sum((dec(x["probability"]) * dec(x["impact"]) for x in rs), F(0)) if rs else None
        risk = {"risk_exposure": mn(exposure), "label": "scenario estimate",
                "items": [{"risk_id": x["risk_id"], "probability": x["probability"], "impact": x["impact"],
                           "expected_loss": money(dec(x["probability"]) * dec(x["impact"]))} for x in rs]}
        fvs = [f for f in acc["forecast_versions"] if f["initiative_id"] == iid]
        forecast = None
        if fvs:
            vers = []
            for v in sorted({f["version_number"] for f in fvs}):
                rows = sorted((f for f in fvs if f["version_number"] == v), key=lambda f: f["period_index"])
                vers.append({"version_number": v, "created_at": rows[0]["created_at"], "reason": rows[0]["reason"],
                             "total": money(sum((dec(f["amount"]) for f in rows), F(0))),
                             "by_period": [{"period_index": f["period_index"], "amount": f["amount"]} for f in rows]})
            observed = []
            for b in sorted((b for b in acc["benefit_items"] if b["initiative_id"] == iid and b["benefit_type"] == "cash"), key=lambda b: b["benefit_id"]):
                for o in sorted((o for o in acc["benefit_observations"] if o["benefit_id"] == b["benefit_id"]), key=lambda o: o["benefit_observation_id"]):
                    observed.append({"benefit_id": b["benefit_id"], "period_index": b["period_index"], "measured_value": o["measured_value"],
                                     "observed_at": o["observed_at"], "period_matured": matured(data, b["period_index"])})
            forecast = {"versions": vers, "original_version": vers[0]["version_number"], "original_preserved": True,
                        "latest_version": vers[-1]["version_number"],
                        "latest_minus_original": money(dec(vers[-1]["total"]) - dec(vers[0]["total"])),
                        "observed": observed}
        inits[iid] = {"roadmap": roadmap, "adoption": adoption, "training": training, "risk": risk, "forecast": forecast}

    # groups: readiness (D-03)
    groups = {}
    for g in sorted(acc["stakeholder_groups"], key=lambda g: g["group_id"]):
        latest = {}
        for a in sorted((a for a in acc["readiness_assessments"] if a["group_id"] == g["group_id"] and parse_ts(a["assessed_at"]) <= asof),
                        key=lambda a: (a["assessed_at"], a["assessment_id"])):
            latest[a["dimension"]] = a
        dims = [latest[d] for d in DIMENSIONS if d in latest]
        sw = sum((dec(a["weight"]) for a in dims), F(0))
        score = sum((dec(a["weight"]) * a["score"] for a in dims), F(0)) / sw if dims else None
        groups[g["group_id"]] = {"affected_count": g["affected_count"], "impact_level": g["impact_level"],
                                 "readiness_score": m4(score), "readiness_exact": ex(score), "label": "assessment, not a probability",
                                 "dimensions_assessed": len(dims),
                                 "dimensions": [{"dimension": a["dimension"], "score": a["score"], "weight": a["weight"],
                                                 "assessment_id": a["assessment_id"]} for a in dims]}
    # resources: shared capacity (D-03)
    resources = {}
    for rsrc in sorted(acc["resources"], key=lambda x: x["resource_id"]):
        cap = dec(rsrc["capacity_per_period"])
        per = {}
        for a in acc["resource_allocations"]:
            if a["resource_id"] == rsrc["resource_id"]:
                per[a["period_index"]] = per.get(a["period_index"], F(0)) + dec(a["amount"])
        resources[rsrc["resource_id"]] = {"capacity_per_period": money(cap), "unit": rsrc["unit"],
                                          "by_period": [{"period_index": p, "allocated": money(v), "headroom": money(cap - v)} for p, v in sorted(per.items())],
                                          "overallocated_periods": [p for p, v in sorted(per.items()) if v > cap]}
    # summary (pooled figures only where pooling is meaningful)
    first = next(iter(scenarios.values()), None)
    adopted = sum(x["adoption"]["adopted_count"] for x in inits.values() if x["adoption"]["eligible_count"])
    elig = sum(x["adoption"]["eligible_count"] for x in inits.values() if x["adoption"]["eligible_count"])
    tcomp = sum(x["training"]["completed"] for x in inits.values() if x["training"]["eligible_trainees"])
    telig = sum(x["training"]["eligible_trainees"] for x in inits.values() if x["training"]["eligible_trainees"])
    risks = [F(x["risk"]["risk_exposure"]) for x in inits.values() if x["risk"]["risk_exposure"] is not None]
    caps = [F(x["capacity_released"]["hours"]) for x in (first["initiatives"].values() if first else []) if x["capacity_released"]["hours"] is not None]
    summary = {"summary_scenario_id": next(iter(scenarios), None), "initiatives": len(ini), "scenarios": len(scenarios),
               "npv_total": first["npv_total"]["value"] if first else None,
               "double_count_residual": first["double_count"]["residual"] if first and first["initiatives"] else None,
               "adoption_rate": p6(F(adopted, elig)) if elig else None,
               "training_completion": p6(F(tcomp, telig)) if telig else None,
               "risk_exposure_total": mn(sum(risks, F(0))) if risks else None,
               "capacity_released_hours_total": m4(sum(caps, F(0))) if caps else None}
    return {"contract_version": 1, "as_of": data["as_of"], "period_basis": data["period_basis"], "empty_population": empty,
            "ingest": {"counts": counts, "rejected_records": rejected},
            "metrics": {"summary": summary, "scenarios": scenarios, "initiatives": inits, "groups": groups, "resources": resources}}


# ---------------------------------------------------------------- comparison harness
def flatten(x, path=""):
    if isinstance(x, dict):
        if not x:
            return {path + "{}": "empty"}
        out = {}
        for k, v in x.items():
            out.update(flatten(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(x, list):
        if not x:
            return {path + "[]": "empty"}
        out = {}
        for i, v in enumerate(x):
            out.update(flatten(v, f"{path}[{i}]"))
        return out
    return {path: x}


def no_floats(x, where):
    if isinstance(x, float):
        report(False, f"{where}.no_float", "no float", x)
    elif isinstance(x, dict):
        [no_floats(v, where) for v in x.values()]
    elif isinstance(x, list):
        [no_floats(v, where) for v in x]


def check_fixture(label, prefix, write):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    no_floats(data, label + ".inputs")
    got = compute(data)
    if write:
        (GOLDEN / (prefix + "expected.json")).write_text(json.dumps(got, indent=2) + "\n")
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    no_floats(exp, label)
    fe, fg = flatten(exp), flatten(got)
    for k in fe:
        report(k in fg and fg[k] == fe[k], f"{label}.{k}", fe[k], fg.get(k, "<missing>"))
    for k in fg:
        if k not in fe:
            report(False, f"{label}.{k}", "<absent>", fg[k])
    return exp


def hand(g, rj, em):
    """The hand-worked figures of CALCULATION.md, typed as literals, against expected.json (not against compute)."""
    s = g["metrics"]["scenarios"]["scn-001"]
    i1, i2, i3 = (s["initiatives"][k] for k in ("init-001", "init-002", "init-003"))
    mi = g["metrics"]["initiatives"]
    cf1 = i1["cash_flow"]
    rows = [
        # P09-GOLD-01: init-001
        ("hand.gold_net_cash_flow_p0_-1000.00", "-1000.00", cf1[0]["net_cash_flow"]),
        ("hand.gold_net_cash_flow_p1_600.00", "600.00", cf1[1]["net_cash_flow"]),
        ("hand.gold_net_cash_flow_p2_600.00", "600.00", cf1[2]["net_cash_flow"]),
        ("hand.gold_cumulative_p1_-400.00", "-400.00", cf1[1]["cumulative"]),
        ("hand.gold_cumulative_p2_200.00", "200.00", cf1[2]["cumulative"]),
        ("hand.gold_discount_factor_p1_10/11", "10/11", cf1[1]["discount_factor_exact"]),
        ("hand.gold_discount_factor_p2_100/121", "100/121", cf1[2]["discount_factor_exact"]),
        ("hand.gold_discounted_p1_545.45", "545.45", cf1[1]["discounted_cash_flow"]),
        ("hand.gold_discounted_p2_495.87", "495.87", cf1[2]["discounted_cash_flow"]),
        ("hand.gold_cumulative_discounted_p1_-454.55", "-454.55", cf1[1]["cumulative_discounted"]),
        ("hand.gold_cumulative_discounted_p2_41.32", "41.32", cf1[2]["cumulative_discounted"]),
        ("hand.gold_npv_exact_5000/121", "5000/121", i1["npv"]["exact"]),
        ("hand.gold_npv_41.32", "41.32", i1["npv"]["value"]),
        ("hand.gold_simple_payback_2", 2, i1["payback"]["simple"]["period"]),
        ("hand.gold_simple_payback_interpolated_1.6667", "1.6667", i1["payback"]["simple"]["interpolated"]),
        ("hand.gold_discounted_payback_2", 2, i1["payback"]["discounted"]["period"]),
        ("hand.gold_discounted_payback_interpolated_1.9167", "1.9167", i1["payback"]["discounted"]["interpolated"]),
        ("hand.gold_capacity_hours_excluded_800.00", "800.00", i1["excluded_from_cash_flow"]["capacity_hours_not_converted"]),
        ("hand.gold_capacity_not_in_cash_benefits_p1", "600.00", cf1[1]["cash_benefits"]),
        ("hand.gold_capacity_released_400.0000_hours", "400.0000", i1["capacity_released"]["hours"]),
        # init-002: expansion, ramp, classes
        ("hand.i2_recurring_expanded_to_2_rows", 3, len(i2["expanded_planned_costs"])),
        ("hand.i2_net_cash_flow_p0_-500.00", "-500.00", i2["cash_flow"][0]["net_cash_flow"]),
        ("hand.i2_net_cash_flow_p1_100.00", "100.00", i2["cash_flow"][1]["net_cash_flow"]),
        ("hand.i2_net_cash_flow_p2_425.00", "425.00", i2["cash_flow"][2]["net_cash_flow"]),
        ("hand.i2_unramped_net_cash_flow_p1_300.00", "300.00", i2["unramped_net_cash_flow"][1]),
        ("hand.i2_unramped_net_cash_flow_p2_550.00", "550.00", i2["unramped_net_cash_flow"][2]),
        ("hand.i2_realised_avoided_cost_p2_75.00", "75.00", i2["cash_flow"][2]["benefits_by_class"]["avoided_cost_realised"]),
        ("hand.i2_revenue_p2_50.00", "50.00", i2["cash_flow"][2]["benefits_by_class"]["revenue"]),
        ("hand.i2_avoided_cost_beside_cash_flow_120.00", "120.00", i2["excluded_from_cash_flow"]["avoided_cost_beside_total"]),
        ("hand.i2_npv_exact_-7000/121", "-7000/121", i2["npv"]["exact"]),
        ("hand.i2_npv_-57.85", "-57.85", i2["npv"]["value"]),
        ("hand.i2_simple_payback_2", 2, i2["payback"]["simple"]["period"]),
        ("hand.i2_simple_payback_interpolated_1.9412", "1.9412", i2["payback"]["simple"]["interpolated"]),
        ("hand.i2_discounted_payback_null", None, i2["payback"]["discounted"]["period"]),
        ("hand.i2_capacity_released_pinned_target_24_is_600.0000", "600.0000", i2["capacity_released"]["hours"]),
        # init-003: never pays back
        ("hand.i3_npv_exact_-81800/121", "-81800/121", i3["npv"]["exact"]),
        ("hand.i3_npv_-676.03", "-676.03", i3["npv"]["value"]),
        ("hand.i3_simple_payback_null", None, i3["payback"]["simple"]["period"]),
        ("hand.i3_discounted_payback_interpolated_null", None, i3["payback"]["discounted"]["interpolated"]),
        ("hand.i3_capacity_released_null_no_approved_baseline", None, i3["capacity_released"]["hours"]),
        ("hand.i3_cost_variance_null_no_approved_baseline", None, i3["cost_variance"]["variance"]),
        ("hand.scenario_npv_total_exact_-83800/121", "-83800/121", s["npv_total"]["exact"]),
        # cost variance
        ("hand.i1_cost_variance_0.00_not_null", "0.00", i1["cost_variance"]["variance"]),
        ("hand.i2_cost_variance_window_0_2", 2, i2["cost_variance"]["window"]["to_period"]),
        ("hand.i2_approved_baseline_cost_600.00", "600.00", i2["cost_variance"]["approved_baseline_cost"]),
        ("hand.i2_actual_cost_620.00", "620.00", i2["cost_variance"]["actual_cost"]),
        ("hand.i2_cost_variance_20.00", "20.00", i2["cost_variance"]["variance"]),
        # benefit realization within a type, matured periods only
        ("hand.i1_cash_realization_480_of_600", "0.800000", i1["benefit_realization"]["cash"]["realization"]),
        ("hand.i1_capacity_realization_340_of_400_hours", "0.850000", i1["benefit_realization"]["capacity"]["realization"]),
        ("hand.i1_cash_observed_above_trend_430.00", "430.00", i1["benefit_realization"]["cash"]["observed_above_trend"]),
        ("hand.i1_cash_attribution_caveat", "observed, not attributed", i1["benefit_realization"]["cash"]["attribution"]),
        ("hand.i1_immature_observation_excluded_bo-3", ["bo-3"], i1["immature_observation_ids"]),
        ("hand.i2_cash_realization_150_of_200_ramped", "0.750000", i2["benefit_realization"]["cash"]["realization"]),
        ("hand.i2_avoided_cost_realization_30_of_40", "0.750000", i2["benefit_realization"]["avoided_cost"]["realization"]),
        # adoption and training
        ("hand.i1_adoption_30_of_40", "0.750000", mi["init-001"]["adoption"]["adoption_rate"]),
        ("hand.i1_adoption_first_observation_10_of_40", "0.250000", mi["init-001"]["adoption"]["series"][0]["adoption_rate"]),
        ("hand.i1_adoption_after_as_of_excluded_ad-3", ["ad-3"], mi["init-001"]["adoption"]["excluded_after_as_of"]),
        ("hand.i1_training_completion_38_of_40", "0.950000", mi["init-001"]["training"]["training_completion"]),
        ("hand.i1_training_differs_from_adoption", True, mi["init-001"]["training"]["differs_from_adoption"]),
        ("hand.i2_adoption_20_of_50", "0.400000", mi["init-002"]["adoption"]["adoption_rate"]),
        ("hand.i3_adoption_zero_denominator_null", None, mi["init-003"]["adoption"]["adoption_rate"]),
        ("hand.i2_training_null_no_records", None, mi["init-002"]["training"]["training_completion"]),
        # risk, readiness
        ("hand.i1_risk_exposure_2000.00", "2000.00", mi["init-001"]["risk"]["risk_exposure"]),
        ("hand.i2_risk_exposure_500.00", "500.00", mi["init-002"]["risk"]["risk_exposure"]),
        ("hand.i3_risk_exposure_null_no_risks", None, mi["init-003"]["risk"]["risk_exposure"]),
        ("hand.grp001_readiness_10/3_is_3.3333", "3.3333", g["metrics"]["groups"]["grp-001"]["readiness_score"]),
        ("hand.grp001_readiness_exact_10/3", "10/3", g["metrics"]["groups"]["grp-001"]["readiness_exact"]),
        ("hand.grp002_readiness_4.0000", "4.0000", g["metrics"]["groups"]["grp-002"]["readiness_score"]),
        ("hand.grp003_readiness_null_nothing_assessed", None, g["metrics"]["groups"]["grp-003"]["readiness_score"]),
        # roadmap and shared capacity
        ("hand.i1_dependency_delay_0", 0, mi["init-001"]["roadmap"]["dependency_delay"]),
        ("hand.i2_dependency_delay_2", 2, mi["init-002"]["roadmap"]["dependency_delay"]),
        ("hand.i3_dependency_delay_3", 3, mi["init-003"]["roadmap"]["dependency_delay"]),
        ("hand.i3_binding_dependency_d-2", "d-2", mi["init-003"]["roadmap"]["binding_dependency_id"]),
        ("hand.res001_peak_p3_allocated_2.00_within_capacity", "2.00", g["metrics"]["resources"]["res-001"]["by_period"][2]["allocated"]),
        ("hand.res001_no_overallocated_period", [], g["metrics"]["resources"]["res-001"]["overallocated_periods"]),
        # double count
        ("hand.planned_benefits_2195.00", "2195.00", s["double_count"]["planned_benefits"]),
        ("hand.attributable_benefits_2120.00", "2120.00", s["double_count"]["attributable_benefits"]),
        ("hand.double_count_residual_75.00", "75.00", s["double_count"]["residual"]),
        ("hand.double_count_counted_once_150.00", "150.00", s["double_count"]["overlaps"][0]["counted_once"]),
        # forecast
        ("hand.forecast_v1_total_1200.00", "1200.00", mi["init-001"]["forecast"]["versions"][0]["total"]),
        ("hand.forecast_v2_total_980.00", "980.00", mi["init-001"]["forecast"]["versions"][1]["total"]),
        ("hand.forecast_original_kept_unchanged_p1_600.00", "600.00", mi["init-001"]["forecast"]["versions"][0]["by_period"][0]["amount"]),
        ("hand.forecast_revision_minus_original_-220.00", "-220.00", mi["init-001"]["forecast"]["latest_minus_original"]),
        # summary and ingest
        ("hand.summary_adoption_pooled_50_of_90", "0.555556", g["metrics"]["summary"]["adoption_rate"]),
        ("hand.summary_risk_exposure_total_2500.00", "2500.00", g["metrics"]["summary"]["risk_exposure_total"]),
        ("hand.golden_total_rows_accepted_71", 71, sum(v["accepted"] for v in g["ingest"]["counts"].values())),
        ("hand.golden_total_rows_rejected_0", 0, sum(v["rejected"] for v in g["ingest"]["counts"].values())),
        # variant-rejected
        ("hand.rejected_one_time_cost_repeated", "ONE_TIME_COST_REPEATED", rj_code(rj, "rc-2")),
        ("hand.rejected_rate_period_mismatch", "RATE_PERIOD_MISMATCH", rj_code(rj, "rs-1")),
        ("hand.rejected_benefit_before_deployment", "BENEFIT_BEFORE_DEPLOYMENT", rj_code(rj, "rb-4")),
        ("hand.rejected_dependency_cycle", "DEPENDENCY_CYCLE", rj_code(rj, "rd-3")),
        ("hand.rejected_resource_overallocated", "RESOURCE_OVERALLOCATED", rj_code(rj, "al-r2")),
        ("hand.rejected_capacity_without_conversion", "CAPACITY_WITHOUT_CONVERSION", rj_code(rj, "rb-7")),
        ("hand.rejected_version_exists", "VERSION_EXISTS", rj_code(rj, "ra-t1x")),
        ("hand.rejected_probability_out_of_range", "PROBABILITY_OUT_OF_RANGE", rj_code(rj, "rk-2")),
        ("hand.rejected_unknown_initiative_cost", "UNKNOWN_INITIATIVE", rj_code(rj, "rc-7")),
        ("hand.rejected_dependent_rejected_cost", "DEPENDENT_REJECTED", rj_code(rj, "rc-8")),
        ("hand.rejected_dependent_rejected_observation", "DEPENDENT_REJECTED", rj_code(rj, "rbo-2")),
        ("hand.rejected_cycle_listed", ["rj-i1", "rj-i3", "rj-i2", "rj-i1"], rj_rec(rj, "rd-3")["details"]["cycle"]),
        ("hand.rejected_funded_status", "STATUS_NOT_ALLOWED", rj_code(rj, "rj-i5")),
        ("hand.rejected_total_records_30", 30, len(rj["ingest"]["rejected_records"])),
        ("hand.rej_i2_simple_payback_3_cumulative_exactly_0", 3, rj["metrics"]["scenarios"]["rs-3"]["initiatives"]["rj-i2"]["payback"]["simple"]["period"]),
        ("hand.rej_i2_simple_payback_interpolated_3.0000", "3.0000", rj["metrics"]["scenarios"]["rs-3"]["initiatives"]["rj-i2"]["payback"]["simple"]["interpolated"]),
        ("hand.rej_i2_discounted_payback_null_at_1pct", None, rj["metrics"]["scenarios"]["rs-3"]["initiatives"]["rj-i2"]["payback"]["discounted"]["period"]),
        ("hand.rej_i2_npv_exact_-7590300/1030301", "-7590300/1030301", rj["metrics"]["scenarios"]["rs-3"]["initiatives"]["rj-i2"]["npv"]["exact"]),
        ("hand.rej_i2_npv_-7.37", "-7.37", rj["metrics"]["scenarios"]["rs-3"]["initiatives"]["rj-i2"]["npv"]["value"]),
        ("hand.rej_i3_never_pays_back_simple_null", None, rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i3"]["payback"]["simple"]["period"]),
        ("hand.rej_i3_not_cash_realised_avoided_cost_excluded", "NO_EVIDENCE_REF", rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i3"]["excluded_from_cash_flow"]["avoided_cost_beside"][0]["reason"]),
        ("hand.rej_i4_converted_capacity_100h_x_25.00_is_2500.00", "2500.00", rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i4"]["cash_flow"][1]["net_cash_flow"]),
        ("hand.rej_i4_simple_payback_interpolated_0.4000", "0.4000", rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i4"]["payback"]["simple"]["interpolated"]),
        ("hand.rej_i1_simple_payback_interpolated_1.5385", "1.5385", rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i1"]["payback"]["simple"]["interpolated"]),
        ("hand.rej_i1_planned_cost_rows_1_one_time_plus_3_recurring", 4, len(rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i1"]["expanded_planned_costs"])),
        ("hand.rej_i1_npv_919.31_at_converted_monthly_rate", "919.31", rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i1"]["npv"]["value"]),
        ("hand.rej_i3_npv_-401.97", "-401.97", rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i3"]["npv"]["value"]),
        ("hand.rej_i4_npv_3940.82", "3940.82", rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i4"]["npv"]["value"]),
        ("hand.rej_converted_rate_is_recorded_assumption_0.007974", "0.007974", rj["metrics"]["scenarios"]["rs-2"]["effective_period_rate"]),
        ("hand.rej_i1_capacity_released_1200x2/60_is_40.0000", "40.0000", rj["metrics"]["scenarios"]["rs-2"]["initiatives"]["rj-i1"]["capacity_released"]["hours"]),
        ("hand.rej_i1_training_18_of_20", "0.900000", rj["metrics"]["initiatives"]["rj-i1"]["training"]["training_completion"]),
        ("hand.rej_i1_forecast_original_kept_700.00", "700.00", rj["metrics"]["initiatives"]["rj-i1"]["forecast"]["versions"][0]["total"]),
        ("hand.rej_i3_dependency_delay_4", 4, rj["metrics"]["initiatives"]["rj-i3"]["roadmap"]["dependency_delay"]),
        # variant-empty
        ("hand.empty_population_true", True, em["empty_population"]),
        ("hand.empty_every_count_0", 0, sum(v["accepted"] + v["rejected"] for v in em["ingest"]["counts"].values())),
        ("hand.empty_npv_null", None, em["metrics"]["summary"]["npv_total"]),
        ("hand.empty_adoption_null", None, em["metrics"]["summary"]["adoption_rate"]),
        ("hand.empty_training_null", None, em["metrics"]["summary"]["training_completion"]),
        ("hand.empty_residual_null", None, em["metrics"]["summary"]["double_count_residual"]),
        ("hand.empty_risk_null", None, em["metrics"]["summary"]["risk_exposure_total"]),
        ("hand.empty_capacity_null", None, em["metrics"]["summary"]["capacity_released_hours_total"]),
        ("hand.empty_no_scenarios", {}, em["metrics"]["scenarios"]),
    ]
    for name, want, got in rows:
        report(want == got, name, want, got)
    # recomputed here from the stated facts with Fractions (no float anywhere)
    npv = -1000 + F(600) / F(11, 10) + F(600) / F(11, 10) ** 2
    report(npv == F(5000, 121) and rnd(npv, 2) == "41.32", "hand.5000/121_is_41.32", "41.32", rnd(npv, 2))
    report(rnd(F(400, 600) + 1, 4) == "1.6667" and rnd(1 + F(55, 60), 4) == "1.9167", "hand.interpolations_1_plus_2/3_and_1_plus_11/12", "1.6667/1.9167",
           rnd(F(400, 600) + 1, 4) + "/" + rnd(1 + F(55, 60), 4))
    report(rnd(F(12000 * (10 - 8), 60), 4) == "400.0000", "hand.12000_x_2_div_60_is_400", "400.0000", rnd(F(12000 * 2, 60), 4))
    report(rnd(F(20, 6), 4) == "3.3333", "hand.readiness_20_over_6", "3.3333", rnd(F(20, 6), 4))
    report(rnd(F(-7000, 121), 2) == "-57.85" and rnd(F(-81800, 121), 2) == "-676.03", "hand.negative_npvs_round_half_up", "-57.85/-676.03",
           rnd(F(-7000, 121), 2) + "/" + rnd(F(-81800, 121), 2))
    report(rnd(F(1, 2), 0) == "1" and rnd(F(-1, 2), 0) == "-1" and rnd(F(5, 1000), 2) == "0.01", "hand.round_half_up_away_from_zero", "1/-1/0.01",
           rnd(F(1, 2), 0) + "/" + rnd(F(-1, 2), 0) + "/" + rnd(F(5, 1000), 2))


def rj_rec(rj, rid):
    return next(r for r in rj["ingest"]["rejected_records"] if r["id"] == rid)


def rj_code(rj, rid):
    return rj_rec(rj, rid)["reason_code"]


def sha_file(rel):
    return hashlib.sha256((GOLDEN / rel).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-expected", action="store_true")
    ap.add_argument("--write-hashes", action="store_true")
    args = ap.parse_args()
    exps = {label: check_fixture(label, prefix, args.write_expected) for label, prefix in FIXTURES}
    hand(exps["golden"], exps["variant-rejected"], exps["variant-empty"])
    hp = GOLDEN / "HASHES.json"
    if args.write_hashes:
        if failures:
            print(f"NOT WRITING HASHES: {failures} mismatch(es)")
        else:
            hp.write_text(json.dumps({"algorithm": "sha256", "sha256": {p: sha_file(p) for p in HASHED}}, indent=2) + "\n")
            print(f"OK wrote {hp.name}")
    elif hp.exists():
        stored = json.loads(hp.read_text())["sha256"]
        for p in HASHED:
            report(stored.get(p) == sha_file(p), f"hash.{p}", stored.get(p), sha_file(p))
    else:
        report(False, "hash.HASHES.json", "present", "missing")
    print("ALL OK" + f" ({checks} checks)" if not failures else f"{failures} MISMATCH(ES) of {checks} checks")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
