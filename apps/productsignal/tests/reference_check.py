#!/usr/bin/env python3
"""Independent reference calculation for the ProductSignal golden fixtures (P06-GOLD-01..11).

Standard library only; imports nothing from the application. Recomputes every figure in
expected.json from inputs.json (canonical events, time-aware identity, account units and
maturity, activation, funnel, retention, feature adoption, ITT experiment analysis with SRM,
Newcombe hybrid score interval, guardrail, revenue t-interval) and compares leaf by leaf.

No float anywhere in the computation: fractions.Fraction for ratios, decimal.Decimal for
money and for the special functions (p-value, t quantile), square roots by integer Newton
iteration (error far below the contract's 1e-8). Rounding is ROUND_HALF_UP (CALCULATION.md,
DECISIONS D-P6-1). Contract v1, decisions D-01..D-04.

Usage:
  ../../.venv/bin/python -I tests/reference_check.py                 # check, exit 0 only if all OK
  ../../.venv/bin/python -I tests/reference_check.py --write-hashes  # check, then write HASHES.json
  ../../.venv/bin/python -I tests/reference_check.py --emit golden   # print the recomputed expected.json
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_HALF_UP, getcontext
from fractions import Fraction as F
from pathlib import Path
from zoneinfo import ZoneInfo

getcontext().prec = 80
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
FIXTURES = [("golden", ""), ("variant-rejected", "variant-rejected/"), ("variant-empty", "variant-empty/")]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENTITIES = ["accounts", "users", "identity_links", "sessions", "events", "event_properties", "subscriptions",
            "experiment_versions", "assignments", "exposures", "metric_observations", "analysis_runs"]
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


# ---------------------------------------------------------------- numbers
def isqrt_newton(n):
    """floor(sqrt(n)) by integer Newton iteration."""
    if n < 2:
        return n
    x = 1 << ((n.bit_length() + 1) // 2)
    while True:
        y = (x + n // x) // 2
        if y >= x:
            return x
        x = y


def sqrt_frac(x):
    """sqrt of a nonnegative Fraction, truncated at 1e-20 (contract needs 1e-8)."""
    return F(isqrt_newton((x.numerator * 10 ** 40) // x.denominator), 10 ** 20)


def dsqrt(x):
    """sqrt of a nonnegative Decimal at 60 decimals by integer Newton."""
    return D(isqrt_newton(int(x * D(10) ** 120))) / D(10) ** 60


def dec(x):
    return x if isinstance(x, D) else D(x.numerator) / D(x.denominator)


def q(x, places):
    """ROUND_HALF_UP to `places`, as a string; never '-0.00'."""
    s = str(dec(x).quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP))
    return s[1:] if s.startswith("-") and not any(c in "123456789" for c in s) else s


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def datep(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def ratio(n, d):
    return None if d == 0 else F(n, d)


def q6(x):
    return None if x is None else q(x, 6)


def d_atan(x):
    """atan of a Decimal, argument halved until small, then the series."""
    k = 0
    while abs(x) > D("0.2"):
        x = x / (1 + dsqrt(1 + x * x))
        k += 1
    s, t, n = D(0), x, 0
    while abs(t) > D(10) ** -70:
        s += t / (2 * n + 1)
        t = -t * x * x
        n += 1
    return s * (2 ** k)


PI = 16 * d_atan(D(1) / 5) - 4 * d_atan(D(1) / 239)


def d_erf(x):
    s, term, n = D(0), x, 0
    while abs(term) > D(10) ** -70:
        s += term / (2 * n + 1)
        n += 1
        term = -term * x * x / n
    return 2 * s / dsqrt(PI)


def chi2_sf_df1(stat):
    """P(chi-square_1 > stat) = erfc(sqrt(stat/2)); 0 beyond 100 (below 1e-20)."""
    if stat <= 0:
        return D(1)
    if stat > 100:
        return D(0)
    return 1 - d_erf(dsqrt(dec(stat) / 2))


def t_two_sided(t, nu):
    """P(|T| < t) for integer nu (Abramowitz and Stegun 26.7.3-4 finite sums)."""
    r = dsqrt(D(nu) + t * t)
    sin, cos = t / r, dsqrt(D(nu)) / r
    if nu % 2 == 1:
        theta = d_atan(t / dsqrt(D(nu)))
        c, tot, p = D(1), D(0), cos
        for k in range((nu - 1) // 2):
            tot += c * p
            c = c * (2 * k + 2) / (2 * k + 3)
            p = p * cos * cos
        return 2 / PI * (theta + sin * tot)
    d, tot, p = D(1), D(0), D(1)
    for k in range(nu // 2):
        tot += d * p
        d = d * (2 * k + 1) / (2 * k + 2)
        p = p * cos * cos
    return sin * tot


_TCACHE = {}


def t_crit(nu, conf=D("0.95")):
    """Two-sided critical value by bisection on the exact t CDF."""
    if nu not in _TCACHE:
        lo, hi = D(0), D(1000)
        for _ in range(90):
            mid = (lo + hi) / 2
            if t_two_sided(mid, nu) < conf:
                lo = mid
            else:
                hi = mid
        _TCACHE[nu] = (lo + hi) / 2
    return _TCACHE[nu]


def wilson(x, n, z):
    p = F(x, n)
    z2 = z * z
    denom = 1 + z2 / n
    centre = p + z2 / (2 * n)
    half = z * sqrt_frac(p * (1 - p) / n + z2 / (4 * n * n))
    return p, (centre - half) / denom, (centre + half) / denom


def newcombe(x1, n1, x2, n2, z):
    """Hybrid score interval for p1 - p2 (group 1 = treatment, 2 = control)."""
    p1, l1, u1 = wilson(x1, n1, z)
    p2, l2, u2 = wilson(x2, n2, z)
    d = p1 - p2
    low = d - sqrt_frac((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = d + sqrt_frac((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, low, high


# ---------------------------------------------------------------- the calculation
def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute(data):
    cutoff = ts(data["cutoff"])
    plan = data["analysis_plan"]
    mw = data["metric_windows"]
    z = F(plan["z"])
    users = {u["user_id"]: u for u in data["users"]}
    accounts = {a["account_id"]: a for a in data["accounts"]}
    props = defaultdict(dict)
    for p in data["event_properties"]:
        props[p["event_id"]][p["property_key"]] = p["property_value"]
    links_by_anon = defaultdict(list)
    anon_of_user = {}
    for l in sorted(data["identity_links"], key=lambda l: (l["linked_at"], l["identity_link_id"])):
        links_by_anon[l["anonymous_id"]].append(l)
        anon_of_user.setdefault(l["user_id"], l["anonymous_id"])

    # --- D-01 canonical events: received by cutoff, then de-duplicated
    raw = data["events"]
    recv = sorted((e for e in raw if ts(e["received_at"]) <= cutoff), key=lambda e: (e["received_at"], e["event_id"]))
    seen_ids, seen_keys, canon, dups = set(), set(), [], 0
    for e in recv:
        actor = e["user_id"] or e["anonymous_id"]
        key = (actor, e["event_name"], e["event_at"], tuple(sorted(props[e["event_id"]].items())))
        if e["event_id"] in seen_ids or key in seen_keys:
            dups += 1
            continue
        seen_ids.add(e["event_id"])
        seen_keys.add(key)
        canon.append(e)

    def effective_user(e):
        if e["user_id"]:
            return e["user_id"]
        for l in links_by_anon.get(e["anonymous_id"], []):
            if ts(l["linked_at"]) <= ts(e["event_at"]):
                return l["user_id"]
        return None

    analysed, unknown, bots, internals = [], 0, 0, 0
    for e in canon:
        u = effective_user(e)
        if (e["user_id"] is None and e["anonymous_id"] is None) or (u is not None and u not in users):
            unknown += 1
            continue
        if u is not None and users[u]["bot_flag"]:
            bots += 1
            continue
        if u is not None and accounts[users[u]["account_id"]]["internal"]:
            internals += 1
            continue
        acct = users[u]["account_id"] if u else None
        vk = e["anonymous_id"] or (anon_of_user.get(e["user_id"]) if e["user_id"] else None) or "user:" + str(e["user_id"])
        analysed.append({"e": e, "u": u, "acct": acct, "vk": vk, "name": e["event_name"], "at": ts(e["event_at"])})
    delayed = sum(1 for e in canon if ts(e["received_at"]) - ts(e["event_at"]) > timedelta(hours=24))
    anon_events = [a for a in analysed if a["e"]["user_id"] is None]
    attributed = sum(1 for a in anon_events if a["u"] is not None)

    # --- ingest counts and rejections (experiment entities)
    rejected = []

    def reject(entity, idk, row, code):
        rejected.append({"entity": entity, "id": row[idk], "status": "rejected", "reason_code": code, "raw_row": row})

    xv = plan["experiment_version_id"]
    asg_all = sorted((a for a in data["assignments"] if a["experiment_version_id"] == xv), key=lambda a: (a["assigned_at"], a["assignment_id"]))
    accepted_unit, asg_by_id, rej_asg, repeats = {}, {a["assignment_id"]: a for a in data["assignments"]}, set(), 0
    for a in asg_all:
        first = accepted_unit.get(a["unit_id"])
        if first is None:
            accepted_unit[a["unit_id"]] = a
        elif first["variant"] == a["variant"]:
            repeats += 1
        else:
            rej_asg.add(a["assignment_id"])
            reject("assignments", "assignment_id", a, "ASSIGNMENT_CONFLICT")
    exposures_ok = {}
    for x in sorted(data["exposures"], key=lambda x: (x["exposed_at"], x["exposure_id"])):
        a = asg_by_id.get(x["assignment_id"])
        if a is None:
            reject("exposures", "exposure_id", x, "UNKNOWN_ASSIGNMENT")
        elif a["assignment_id"] in rej_asg:
            reject("exposures", "exposure_id", x, "DEPENDENT_REJECTED")
        elif ts(x["exposed_at"]) < ts(a["assigned_at"]):
            reject("exposures", "exposure_id", x, "EXPOSURE_BEFORE_ASSIGNMENT")
        else:
            exposures_ok.setdefault(a["assignment_id"], x)
    obs_ok = []
    for o in data["metric_observations"]:
        if o["assignment_id"] not in asg_by_id:
            reject("metric_observations", "observation_id", o, "UNKNOWN_ASSIGNMENT")
        elif o["assignment_id"] in rej_asg:
            reject("metric_observations", "observation_id", o, "DEPENDENT_REJECTED")
        else:
            obs_ok.append(o)
    rejected.sort(key=lambda r: (r["entity"], r["id"]))
    counts = {}
    for ent in ENTITIES:
        rej_n = sum(1 for r in rejected if r["entity"] == ent)
        merged = 0
        total = len(data[ent])
        if ent == "events":
            merged = dups
            total = len(canon)
            rej_n = 0
        if ent == "assignments":
            merged = repeats
        counts[ent] = {"accepted": total - rej_n - (merged if ent == "assignments" else 0), "rejected": rej_n, "merged": merged}

    # --- D-02 account signup and activation
    signup_at = {}
    for a in analysed:
        if a["name"] == "signup" and a["acct"]:
            if a["acct"] not in signup_at or a["at"] < signup_at[a["acct"]]:
                signup_at[a["acct"]] = a["at"]
    act_events = defaultdict(list)
    for a in analysed:
        if a["name"] == "activated" and a["acct"]:
            act_events[a["acct"]].append(a["at"])

    def activated_within(acct, days):
        s = signup_at[acct]
        return any(s <= t < s + timedelta(days=days) for t in act_events[acct])

    def mature7d(acct):
        return signup_at[acct] + timedelta(days=7) <= cutoff

    # --- MET-01 signup conversion on the visitor unit
    sc = mw["signup_conversion"]
    sc_from, sc_to = ts(sc["from"]), ts(sc["to"])
    visitors = {a["e"]["anonymous_id"] for a in analysed if a["name"] == "visit" and a["e"]["anonymous_id"] and sc_from <= a["at"] < sc_to}
    signed = {a["e"]["anonymous_id"] for a in analysed if a["name"] == "signup" and a["e"]["anonymous_id"] in visitors and sc_from <= a["at"] < sc_to}
    signup_block = {"window": {"from": sc["from"], "to": sc["to"]}, "unit": "distinct anonymous_id",
                    "visitors": len(visitors), "signed_up": len(signed), "rate": q6(ratio(len(signed), len(visitors)))}

    # --- MET-03 funnel, strict order, maximum gap, window on the first step
    fn = mw["funnel"]
    f_from, f_to, gap = ts(fn["from"]), ts(fn["to"]), timedelta(hours=fn["max_gap_hours"])
    by_vk = defaultdict(list)
    for a in analysed:
        by_vk[a["vk"]].append(a)
    reached = [set() for _ in fn["steps"]]
    for vk, evs in by_vk.items():
        first = sorted(a["at"] for a in evs if a["name"] == fn["steps"][0] and f_from <= a["at"] < f_to)
        if not first:
            continue
        prev = first[0]
        reached[0].add(vk)
        for k in range(1, len(fn["steps"])):
            nxt = sorted(a["at"] for a in evs if a["name"] == fn["steps"][k] and prev < a["at"] <= prev + gap)
            if not nxt:
                break
            reached[k].add(vk)
            prev = nxt[0]
    steps = []
    for k, name in enumerate(fn["steps"]):
        steps.append({"step": name, "units": len(reached[k]),
                      "conversion_from_previous": None if k == 0 else q6(ratio(len(reached[k]), len(reached[k - 1]))),
                      "conversion_from_first": q6(ratio(len(reached[k]), len(reached[0])))})
    funnel_block = {"definition_id": fn["definition_id"], "version": fn["version"], "max_gap_hours": fn["max_gap_hours"],
                    "window": {"from": fn["from"], "to": fn["to"]}, "steps": steps,
                    "overall_conversion": q6(ratio(len(reached[-1]), len(reached[0])))}

    # --- MET-02 activation within 7 days, mature signups only
    ac = mw["activation"]
    a_from, a_to = ts(ac["from"]), ts(ac["to"])
    pop = sorted(a for a, s in signup_at.items() if a_from <= s < a_to)
    mature = [a for a in pop if mature7d(a)]
    act_n = sum(1 for a in mature if activated_within(a, ac["window_days"]))
    activation_block = {"window": {"from": ac["from"], "to": ac["to"]}, "window_days": ac["window_days"],
                        "signups": len(pop), "immature_excluded": len(pop) - len(mature), "mature_accounts": len(mature),
                        "activated": act_n, "rate": q6(ratio(act_n, len(mature)))}

    # --- MET-04/05 retention in the account's calendar
    rt = mw["retention"]
    r_from, r_to = datep(rt["signup_from"]), datep(rt["signup_to"])
    sess_by_acct = defaultdict(list)
    for s in data["sessions"]:
        u = users.get(s["user_id"])
        if u is None or u["bot_flag"] or accounts[u["account_id"]]["internal"]:
            continue
        if ts(s["started_at"]) < cutoff:
            sess_by_acct[u["account_id"]].append(ts(s["started_at"]))

    def local(acct, t):
        return t.astimezone(ZoneInfo(accounts[acct]["timezone"])).date()

    cohort = sorted(a for a in signup_at if r_from <= local(a, signup_at[a]) < r_to)
    internal_signup_accts = set()
    for e in canon:
        u = effective_user(e)
        if e["event_name"] == "signup" and u in users and accounts[users[u]["account_id"]]["internal"] and not users[u]["bot_flag"]:
            if r_from <= local(users[u]["account_id"], ts(e["event_at"])) < r_to:
                internal_signup_accts.add(users[u]["account_id"])
    m7 = [a for a in cohort if local(a, signup_at[a]) + timedelta(days=8) <= local(a, cutoff)]
    m35 = [a for a in cohort if local(a, signup_at[a]) + timedelta(days=35) <= local(a, cutoff)]

    def days_after(acct):
        return [(local(acct, t) - local(acct, signup_at[acct])).days for t in sess_by_acct[acct]]

    d7 = [a for a in m7 if 7 in days_after(a)]
    d7plus = [a for a in m7 if any(d >= 7 for d in days_after(a))]
    w4 = [a for a in m35 if any(28 <= d <= 34 for d in days_after(a))]
    retention_block = {"signup_window": {"from": rt["signup_from"], "to": rt["signup_to"]}, "calendar": "account timezone",
                       "cohort_accounts": len(cohort), "excluded_internal_accounts": len(internal_signup_accts),
                       "day7": {"mature_accounts": len(m7), "immature_excluded": len(cohort) - len(m7), "retained": len(d7), "rate": q6(ratio(len(d7), len(m7)))},
                       "on_or_after_day7": {"mature_accounts": len(m7), "retained": len(d7plus), "rate": q6(ratio(len(d7plus), len(m7)))},
                       "week4": {"mature_accounts": len(m35), "immature_excluded": len(cohort) - len(m35), "retained": len(w4), "rate": q6(ratio(len(w4), len(m35)))}}

    # --- MET-06 feature adoption
    fa = mw["feature_adoption"]
    fa_from, fa_to = ts(fa["from"]), ts(fa["to"])
    active = {a for a, ss in sess_by_acct.items() if any(fa_from <= t < fa_to for t in ss)}
    eligible = sorted(a for a in active if accounts[a]["plan"] in fa["eligible_plans"])
    uses = [a for a in analysed if a["name"] == "feature_used" and a["acct"] in eligible and fa_from <= a["at"] < fa_to
            and props[a["e"]["event_id"]].get("feature") == fa["feature"]]
    adopters = {a["acct"] for a in uses}
    adoption_block = {"window": {"from": fa["from"], "to": fa["to"]}, "feature": fa["feature"], "eligible_plans": fa["eligible_plans"],
                      "eligible_accounts": len(eligible), "adopting_accounts": len(adopters), "use_events": len(uses),
                      "rate": q6(ratio(len(adopters), len(eligible)))}

    # --- D-03 experiment, ITT
    variants = list(plan["allocation"])
    # D-08 cutoff rule: dated facts after the cutoff do not count in the metrics (ingest counts above use every row)
    exposures_ok = {k: x for k, x in exposures_ok.items() if ts(x["exposed_at"]) <= cutoff}
    obs_ok = [o for o in obs_ok if ts(o["window_end"]) <= cutoff]
    assigned = {v: [a for a in accepted_unit.values() if a["variant"] == v and ts(a["assigned_at"]) <= cutoff] for v in variants}
    n_assigned = {v: len(assigned[v]) for v in variants}
    mat = {v: [a for a in assigned[v] if a["unit_id"] in signup_at and mature7d(a["unit_id"])] for v in variants}
    n_total = sum(n_assigned.values())
    # sample ratio mismatch
    if n_total == 0:
        srm = {"observed": n_assigned, "expected": None, "statistic": None, "p_value": None, "verdict": "INSUFFICIENT"}
    else:
        alloc = {v: F(plan["allocation"][v]) for v in variants}
        exp_cells = {v: n_total * alloc[v] for v in variants}
        stat = sum(((n_assigned[v] - exp_cells[v]) ** 2 / exp_cells[v] for v in variants), F(0))
        pv = chi2_sf_df1(stat)
        if any(c < F(plan["srm"]["min_expected_cell"]) for c in exp_cells.values()):
            verdict = "INSUFFICIENT"
        elif pv < D(plan["srm"]["p_threshold"]):
            verdict = "MISMATCH"
        else:
            verdict = "OK"
        srm = {"observed": n_assigned, "expected": {v: q(exp_cells[v], 2) for v in variants}, "statistic": q(stat, 6),
               "p_value": q(pv, 6), "df": len(variants) - 1, "verdict": verdict}
    # primary outcome
    win = plan["activation_window_days"]
    act = {v: sum(1 for a in mat[v] if activated_within(a["unit_id"], win)) for v in variants}
    n_m = {v: len(mat[v]) for v in variants}
    conv = {v: ratio(act[v], n_m[v]) for v in variants}
    per_variant = {}
    for v in variants:
        if n_m[v]:
            _, lo, hi = wilson(act[v], n_m[v], z)
            w = {"low": q(lo, 6), "high": q(hi, 6)}
        else:
            w = None
        per_variant[v] = {"assigned": n_assigned[v], "mature_units": n_m[v], "activated": act[v], "conversion": q6(conv[v]), "wilson_95": w}
    c, t = "control", "treatment"
    both = n_m[c] > 0 and n_m[t] > 0
    abs_lift = (conv[t] - conv[c]) if both else None
    rel = None if (not both or conv[c] == 0) else (conv[t] - conv[c]) / conv[c]
    run_row = next((r for r in data["analysis_runs"] if r["experiment_version_id"] == xv and ts(r["cutoff_at"]) == cutoff), None)
    plan_body = {k: v for k, v in plan.items() if k != "config_hash"}
    hash_ok = hashlib.sha256(canonical_json(plan_body).encode("utf-8")).hexdigest() == plan["config_hash"]
    interim = cutoff < ts(plan["planned_end"])
    if both:
        d, lo, hi = newcombe(act[t], n_m[t], act[c], n_m[c], z)
        includes0 = lo <= 0 <= hi
        interval = {"method": "newcombe_hybrid_score", "confidence": plan["confidence"], "z": plan["z"], "low": q(lo, 6), "high": q(hi, 6),
                    "low_pp": q(lo * 100, 2), "high_pp": q(hi * 100, 2), "includes_zero": includes0}
        conclusive = (not includes0) and (not interim) and hash_ok
    else:
        interval, conclusive = None, False
    prior = None if run_row is None else sum(1 for r in data["analysis_runs"] if r["experiment_version_id"] == xv and r["created_at"] < run_row["created_at"])
    runs = sorted(r["created_at"] for r in data["analysis_runs"] if r["experiment_version_id"] == xv)
    run_block = {"analysis_id": run_row["analysis_id"] if run_row else None, "cutoff_at": data["cutoff"], "planned_end": plan["planned_end"],
                 "interim": interim, "prior_runs": prior,
                 "plan_frozen": bool(runs) and ts(plan["frozen_at"]) <= ts(runs[0]),
                 "config_hash": plan["config_hash"], "config_hash_matches_plan": hash_ok and bool(run_row) and run_row["config_hash"] == plan["config_hash"]}
    # exposure
    exposed = {v: sum(1 for a in mat[v] if a["assignment_id"] in exposures_ok) for v in variants}
    n_m_all = sum(n_m.values())
    exposure_block = {"definition": "exposed mature assigned accounts / mature assigned accounts",
                      "by_variant": {v: {"exposed": exposed[v], "units": n_m[v], "rate": q6(ratio(exposed[v], n_m[v]))} for v in variants},
                      "overall": {"exposed": sum(exposed.values()), "units": n_m_all, "rate": q6(ratio(sum(exposed.values()), n_m_all))}}
    exploratory = {"label": "exploratory", "decision_basis": False, "by_variant": {}}
    for v in variants:
        ex = [a for a in mat[v] if a["assignment_id"] in exposures_ok]
        k = sum(1 for a in ex if activated_within(a["unit_id"], win))
        exploratory["by_variant"][v] = {"exposed_units": len(ex), "activated": k, "conversion": q6(ratio(k, len(ex)))}
    # guardrail
    gdays = timedelta(days=plan["guardrail"]["window_days"])
    errs = defaultdict(list)
    for a in analysed:
        if a["name"] == "product_error" and a["acct"]:
            errs[a["acct"]].append(a["at"])
    guard = {}
    for v in variants:
        hit = sum(1 for a in mat[v] if any(ts(a["assigned_at"]) <= e < ts(a["assigned_at"]) + gdays for e in errs[a["unit_id"]]))
        guard[v] = {"eligible_units": n_m[v], "units_with_error": hit, "error_rate": q6(ratio(hit, n_m[v]))}
    # revenue per assigned account with a t-interval
    rw_from, rw_to = ts(plan["revenue_window"]["from"]), ts(plan["revenue_window"]["to"])
    rev_by = defaultdict(lambda: D(0))
    for s in data["subscriptions"]:
        if s["status"] in ("active", "ended") and rw_from <= ts(s["starts_at"]) < rw_to and ts(s["starts_at"]) <= cutoff:
            rev_by[s["account_id"]] += D(s["amount_usd"])
    revenue = {}
    for v in variants:
        vals = [rev_by[a["unit_id"]] for a in mat[v]]
        n = len(vals)
        if n == 0:
            revenue[v] = {"units": 0, "total": q(D(0), 2), "mean": None, "interval": None}
            continue
        tot = sum(vals, D(0))
        mean = tot / n
        if n < 2:
            revenue[v] = {"units": n, "total": q(tot, 2), "mean": q(mean, 2), "interval": None}
            continue
        var = sum(((x - mean) ** 2 for x in vals), D(0)) / (n - 1)
        tc = t_crit(n - 1)
        half = tc * dsqrt(var / n)
        revenue[v] = {"units": n, "total": q(tot, 2), "mean": q(mean, 2),
                      "interval": {"df": n - 1, "t": q(tc, 6), "low": q(mean - half, 2), "high": q(mean + half, 2)}}
    # observation rows against the events
    obs_match = 0
    for o in obs_ok:
        a = asg_by_id[o["assignment_id"]]
        u = a["unit_id"]
        if u in signup_at:
            want = "1" if activated_within(u, win) else "0"
            if o["value"] == want and ts(o["window_end"]) == signup_at[u] + timedelta(days=win):
                obs_match += 1
    experiment_block = {
        "experiment_version_id": xv, "unit_type": plan["unit_type"], "allocation": plan["allocation"], "run": run_block,
        "assigned_units": n_total, "mature_units": n_m_all,
        "immature_or_unobserved_excluded": n_total - n_m_all,
        "srm": srm, "primary": {"metric": plan["primary_metric"], "analysis": "intention_to_treat", "variants": per_variant,
                                 "absolute_lift_pp": None if abs_lift is None else q(abs_lift * 100, 2),
                                 "relative_lift": q6(rel), "interval": interval, "conclusive": conclusive},
        "exposure": exposure_block, "exploratory_exposed_only": exploratory, "guardrail": {"metric": plan["guardrail"]["metric"], "window_days": plan["guardrail"]["window_days"], "by_variant": guard},
        "revenue_per_assigned_account": {"currency": "USD", "window": plan["revenue_window"], "by_variant": revenue},
        "observations": {"rows_accepted": len(obs_ok), "rows_matching_events": obs_match}}

    return {
        "contract_version": data["contract_version"],
        "empty_population": len(canon) == 0 and n_total == 0,
        "ingest": {"counts": counts, "rejected_records": rejected},
        "tracking_quality": {"rows_total": len(raw), "received_after_cutoff": len(raw) - len(recv), "duplicates_dropped": dups,
                             "canonical": len(canon), "delayed_over_24h": delayed, "unknown_identity": unknown,
                             "bot_events_excluded": bots, "internal_events_excluded": internals, "analysed": len(analysed)},
        "identity": {"anonymous_events": len(anon_events), "attributed_by_link": attributed, "remain_anonymous": len(anon_events) - attributed},
        "metrics": {"signup_conversion": signup_block, "funnel": funnel_block, "activation": activation_block,
                    "retention": retention_block, "feature_adoption": adoption_block, "experiment": experiment_block},
    }


# ---------------------------------------------------------------- checking
def flatten(x, path=""):
    if isinstance(x, dict):
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


def selftests():
    """Known textbook values for the special functions, checked before they are trusted."""
    for name, want, got in (
        ("selftest.sqrt_2_to_1e-8", True, abs(sqrt_frac(F(2)) - F(14142135623730950488, 10 ** 19)) < F(1, 10 ** 8)),
        ("selftest.isqrt_newton_1e12", 10 ** 6, isqrt_newton(10 ** 12)),
        ("selftest.z_0.975", "0.050000", q(1 - d_erf(D("1.959964") / dsqrt(D(2))), 6)),
        ("selftest.chi2_sf_3.841459", "0.050000", q(chi2_sf_df1(F(3841459, 10 ** 6)), 6)),
        ("selftest.chi2_sf_4", "0.045500", q(chi2_sf_df1(F(4)), 6)),
        ("selftest.chi2_sf_10.827566", "0.001000", q(chi2_sf_df1(F(10827566, 10 ** 6)), 6)),
        ("selftest.t975_df1", "12.706205", q(t_crit(1), 6)),
        ("selftest.t975_df2", "4.302653", q(t_crit(2), 6)),
        ("selftest.t975_df7", "2.364624", q(t_crit(7), 6)),
        ("selftest.t975_df9", "2.262157", q(t_crit(9), 6)),
        ("selftest.newcombe_1998_low_56_70_vs_48_80", "0.0524", q(newcombe(56, 70, 48, 80, F("1.96"))[1], 4)),
        ("selftest.newcombe_1998_high_56_70_vs_48_80", "0.3339", q(newcombe(56, 70, 48, 80, F("1.96"))[2], 4)),
        ("selftest.t975_df11", "2.200985", q(t_crit(11), 6)),
        ("selftest.t975_df99", "1.984217", q(t_crit(99), 6)),
    ):
        report(want == got, name, want, got)


def spec_sentence():
    """P06-GOLD-01 recomputed from the sentence alone, then compared with golden/expected.json."""
    exp = json.loads((GOLDEN / "expected.json").read_text())["metrics"]
    e = exp["experiment"]
    z = F("1.959964")
    c, t = F(20, 100), F(30, 100)
    d, lo, hi = newcombe(30, 100, 20, 100, z)
    stat = F(0)
    for name, want, got in (
        ("spec.control_conversion", "0.200000", q(c, 6)),
        ("spec.treatment_conversion", "0.300000", q(t, 6)),
        ("spec.absolute_lift_pp", "10.00", q((t - c) * 100, 2)),
        ("spec.relative_lift", "0.500000", q((t - c) / c, 6)),
        ("spec.interval_includes_zero", True, lo <= 0 <= hi),
        ("spec.not_conclusive", False, e["primary"]["conclusive"]),
        ("spec.srm_statistic", "0.000000", q(stat, 6)),
        ("spec.retention_5_of_20", "0.250000", q(F(5, 20), 6)),
        ("spec.expected_control", e["primary"]["variants"]["control"]["conversion"], q(c, 6)),
        ("spec.expected_treatment", e["primary"]["variants"]["treatment"]["conversion"], q(t, 6)),
        ("spec.expected_abs_lift", e["primary"]["absolute_lift_pp"], q((t - c) * 100, 2)),
        ("spec.expected_rel_lift", e["primary"]["relative_lift"], q((t - c) / c, 6)),
        ("spec.expected_srm", "OK", e["srm"]["verdict"]),
        ("spec.expected_retention", exp["retention"]["day7"]["rate"], q(F(5, 20), 6)),
        ("spec.expected_interval_low", e["primary"]["interval"]["low"], q(lo, 6)),
        ("spec.expected_interval_high", e["primary"]["interval"]["high"], q(hi, 6)),
    ):
        report(want == got, name, want, got)


def check_fixture(label, prefix):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    no_floats(data, label + ".inputs")
    no_floats(exp, label)
    for ent in ENTITIES:
        report(isinstance(data.get(ent), list), f"{label}.inputs.{ent}.is_list", "list", type(data.get(ent)).__name__)
    got = compute(data)
    fe, fg = flatten(exp), flatten(got)
    for k in fe:
        report(k in fg and fg[k] == fe[k], f"{label}.{k}", fe[k], fg.get(k, "<missing>"))
    for k in fg:
        if k not in fe:
            report(False, f"{label}.{k}", "<absent>", fg[k])
    return got


def sha(rel):
    return hashlib.sha256((GOLDEN / rel).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true")
    ap.add_argument("--emit", choices=[l for l, _ in FIXTURES])
    args = ap.parse_args()
    if args.emit:
        prefix = dict(FIXTURES)[args.emit]
        data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
        print(json.dumps(compute(data), indent=2))
        return 0
    selftests()
    spec_sentence()
    for label, prefix in FIXTURES:
        check_fixture(label, prefix)
    hp = GOLDEN / "HASHES.json"
    if args.write_hashes:
        if failures:
            print(f"NOT WRITING HASHES: {failures} mismatch(es)")
        else:
            hp.write_text(json.dumps({"algorithm": "sha256", "sha256": {p: sha(p) for p in HASHED}}, indent=2) + "\n")
            print(f"OK wrote {hp.name}")
    elif hp.exists():
        stored = json.loads(hp.read_text())["sha256"]
        for p in HASHED:
            report(stored.get(p) == sha(p), f"hash.{p}", stored.get(p), sha(p))
    else:
        report(False, "hash.HASHES.json", "present", "missing")
    print("ALL OK" + f" ({checks} checks)" if not failures else f"{failures} MISMATCH(ES) of {checks} checks")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
