#!/usr/bin/env python3
"""Independent reference calculation for the RetentionLab golden fixtures (P10-GOLD-01..11).

Standard library only; imports nothing from the application. Recomputes every figure in expected.json from
inputs.json for the golden case and both variants (entity import validation with rejection codes and
DEPENDENT_REJECTED cascades; command refusals; point-in-time eligibility, features, arrived-late events and
labels; the chronological split with the label-window purge and the group purge; churn rate, precision and recall
at K, average precision, Brier score, risk lift at K, the 10-bin calibration table, contact budget and expected
intervention value, feature missingness, population stability index, scoring freshness and data freshness) and
compares leaf by leaf. It asserts the hand-worked figures of CALCULATION.md as literals and verifies the seven
fixture hashes.

No float anywhere: fractions.Fraction for every ratio and score (Brier score and average precision are exact
rationals on the frozen 6-place decimal strings), decimal.Decimal for money and for the one irrational figure, the
natural logarithm inside the population stability index (60 significant digits, never a float). Proportions and
scores are 6-place strings, percentage points 2 places, money 2 places, ROUND_HALF_UP. Contract v1, D-01..D-04, and
the fixture decisions D-P10-01.. of CALCULATION.md.

Usage (from apps/retentionlab):
  ../../.venv/bin/python -I tests/reference_check.py                 # check everything, exit 0 only if all OK
  ../../.venv/bin/python -I tests/reference_check.py --write-expected  # regenerate the three expected.json files
  ../../.venv/bin/python -I tests/reference_check.py --write-hashes    # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction as F
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
FIXTURES = [("golden", ""), ("variant-rejected", "variant-rejected/"), ("variant-empty", "variant-empty/")]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENT = ["accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs",
       "feature_rows", "labels", "training_runs", "predictions", "intervention_scenarios", "outreach_events",
       "feature_registry", "split_assignments", "scoring_publications"]
ID = {"accounts": "account_id", "subscription_events": "subscription_event_id", "billing_events": "billing_event_id",
      "usage_events": "usage_event_id", "support_events": "support_event_id", "prediction_cutoffs": "cutoff_id",
      "feature_rows": "feature_row_id", "labels": "label_id", "training_runs": "training_run_id",
      "predictions": "prediction_id", "intervention_scenarios": "scenario_id", "outreach_events": "outreach_event_id",
      "feature_registry": "feature_name", "split_assignments": "assignment_id", "scoring_publications": "publication_id"}
EVENTS = ["subscription_events", "billing_events", "usage_events", "support_events"]
# child entity -> [(foreign key field, parent entity, code when the parent id is unknown)], checked in this order
FK = {e: [("account_id", "accounts", "UNKNOWN_ACCOUNT")] for e in EVENTS}
FK.update({
    "prediction_cutoffs": [("account_id", "accounts", "UNKNOWN_ACCOUNT")],
    "feature_rows": [("cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF")],
    "labels": [("cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF")],
    "predictions": [("training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN"),
                    ("cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF")],
    "outreach_events": [("account_id", "accounts", "UNKNOWN_ACCOUNT"),
                        ("scenario_id", "intervention_scenarios", "UNKNOWN_SCENARIO")],
    "split_assignments": [("training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN"),
                          ("cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF")],
    "scoring_publications": [("training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN")]})
FEATURES = ["usage_events_30d", "days_since_last_usage", "high_severity_support_90d", "billing_total_90d"]
CAL_BINS = 10
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
    """ROUND_HALF_UP of a Fraction to dp places, as a string (sign kept, no negative zero)."""
    x = F(x)
    neg = x < 0
    scaled = abs(x) * 10 ** dp
    n = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    whole, frac = divmod(n, 10 ** dp)
    s = f"{whole}.{frac:0{dp}d}" if dp else str(whole)
    return ("-" if neg and n else "") + s


def p6(x):
    return None if x is None else rnd(x, 6)


def pp2(x):
    """Fraction difference of proportions -> percentage points, 2 places."""
    return None if x is None else rnd(F(x) * 100, 2)


def money(d):
    return str(Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ratio(num, den):
    return None if den == 0 else F(num, den)


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def days(n):
    return timedelta(days=n)


def hours_between(later, earlier):
    return int((later - earlier).total_seconds() // 3600)


def canon(p):
    return json.dumps(p, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


# ---------------------------------------------------------------- import validation (D-P10-15)
def validate(data):
    """Accepted rows per entity and the rejected list. Per row: duplicate id, then foreign keys in order (a parent
    that was itself rejected gives DEPENDENT_REJECTED), then the domain rule. Nothing is silently dropped."""
    as_of = ts(data["as_of"])
    grace = data["label_version"]["grace_days"]
    acc = {e: [] for e in ENT}
    ok_ids = {e: set() for e in ENT}
    rej_ids = {e: set() for e in ENT}
    rejected = []
    cutoffs = {}
    for e in ENT:
        for row in data.get(e, []):
            rid = row[ID[e]]
            code = None
            if rid in ok_ids[e]:
                code = "DUPLICATE_ID"
            if code is None:
                for fk, parent, unknown in FK.get(e, []):
                    pid = row[fk]
                    if pid in ok_ids[parent]:
                        continue
                    code = "DEPENDENT_REJECTED" if pid in rej_ids[parent] else unknown
                    break
            if code is None:
                if e == "accounts" and row.get("synthetic") is not True:
                    code = "SYNTHETIC_REQUIRED"
                elif e in EVENTS and ts(row["available_at"]) < ts(row["event_at"]):
                    code = "AVAILABILITY_BEFORE_EVENT"
                elif e == "predictions" and not (0 <= F(row["probability"]) <= 1):
                    code = "PROBABILITY_OUT_OF_RANGE"
                elif e == "labels":
                    c = cutoffs[row["cutoff_id"]]
                    if ts(c["horizon_end"]) + days(grace) > as_of and row["churned"] is not None:
                        code = "CENSORED_LABEL"
                elif e == "outreach_events" and row.get("status") != "draft":
                    code = "OUTREACH_NOT_DRAFT"
            if code:
                rejected.append({"entity": e, "id": rid, "reason_code": code})
                if code != "DUPLICATE_ID":
                    rej_ids[e].add(rid)
            else:
                acc[e].append(row)
                ok_ids[e].add(rid)
                if e == "prediction_cutoffs":
                    cutoffs[rid] = row
    return acc, rejected


# ---------------------------------------------------------------- point-in-time analysis (D-01)
class World:
    def __init__(self, data, acc):
        self.data = data
        self.acc = acc
        self.as_of = ts(data["as_of"])
        lv = data["label_version"]
        self.horizon = lv["horizon_days"]
        self.grace = lv["grace_days"]
        self.obs_days = data["feature_version_spec"]["observation_days"]
        self.fv = data["feature_version_spec"]["feature_version"]
        self.accounts = {a["account_id"]: a for a in acc["accounts"]}
        self.by_acct = {e: {} for e in EVENTS}
        for e in EVENTS:
            for ev in acc[e]:
                self.by_acct[e].setdefault(ev["account_id"], []).append(ev)
        self.cutoffs = {c["cutoff_id"]: c for c in acc["prediction_cutoffs"]}
        self.reg = {r["feature_name"]: r for r in acc["feature_registry"]}
        self.runs = {r["training_run_id"]: r for r in acc["training_runs"]}
        self.scen = {s["scenario_id"]: s for s in acc["intervention_scenarios"]}
        self.preds = {}
        for p in acc["predictions"]:
            self.preds[(p["training_run_id"], p["cutoff_id"])] = p
        self._cache = {}

    def win(self, name, default):
        r = self.reg.get(name)
        return r["window_days"] if r and r.get("window_days") else default

    def analyse(self, cid):
        if cid in self._cache:
            return self._cache[cid]
        c = self.cutoffs[cid]
        pa, obs, he = ts(c["prediction_at"]), ts(c["observation_start"]), ts(c["horizon_end"])
        label_end = he + days(self.grace)
        mature = label_end <= self.as_of
        aid = c["account_id"]
        acct = self.accounts[aid]
        row = {"cutoff_id": cid, "account_id": aid, "prediction_at": c["prediction_at"], "eligible": False,
               "ineligible_code": None, "label_end": fmt(label_end), "mature": mature, "churned": None,
               "features": None, "max_available_at": None, "arrived_late": None}
        subs = self.by_acct["subscription_events"].get(aid, [])
        visible = [s for s in subs if ts(s["event_at"]) < pa and ts(s["available_at"]) < pa]
        latest = max(visible, key=lambda s: (ts(s["event_at"]), s["subscription_event_id"])) if visible else None
        if ts(acct["created_at"]) >= obs:
            row["ineligible_code"] = "CREATED_ON_OR_AFTER_OBSERVATION_START"
        elif latest is None or latest["event_type"] == "cancel":
            row["ineligible_code"] = "NOT_ACTIVE"
        else:
            row["eligible"] = True
        if row["eligible"]:
            row.update(self._features(aid, pa, obs))
            if mature:
                row["churned"] = any(
                    s["event_type"] == "cancel" and pa <= ts(s["event_at"]) < he and ts(s["available_at"]) < label_end
                    for s in subs)
        self._cache[cid] = row
        return row

    def _features(self, aid, pa, obs):
        late = {e: 0 for e in EVENTS}
        qual = {}
        for e in EVENTS[1:]:
            qual[e] = []
            for ev in self.by_acct[e].get(aid, []):
                if obs <= ts(ev["event_at"]) < pa:
                    if ts(ev["available_at"]) < pa:
                        qual[e].append(ev)
                    else:
                        late[e] += 1
        late["subscription_events"] = sum(
            1 for s in self.by_acct["subscription_events"].get(aid, [])
            if ts(s["event_at"]) < pa <= ts(s["available_at"]))
        w_use = self.win("usage_events_30d", 30)
        usage = qual["usage_events"]
        use_n = sum(1 for u in usage if ts(u["event_at"]) >= pa - days(w_use))
        last = max((ts(u["event_at"]) for u in usage), default=None)
        high = sum(1 for s in qual["support_events"] if s["severity"] == "high")
        bills = [Decimal(b["amount"]) for b in qual["billing_events"]]
        used = [ts(ev["available_at"]) for e in EVENTS[1:] for ev in qual[e]]
        return {"features": {
            "usage_events_30d": use_n,
            "days_since_last_usage": None if last is None else int((pa - last).total_seconds() // 86400),
            "high_severity_support_90d": high,
            "billing_total_90d": money(sum(bills, Decimal(0))) if bills else None},
            "max_available_at": fmt(max(used)) if used else None,
            "arrived_late": late}

    def set_rows(self, pa):
        return [self.analyse(c["cutoff_id"]) for c in self.acc["prediction_cutoffs"] if c["prediction_at"] == pa]


# ---------------------------------------------------------------- split (D-02)
def split_run(w, run):
    te, ve, xe = ts(run["train_end"]), ts(run["validation_end"]), ts(run["test_end"])
    rows = []
    for c in w.acc["prediction_cutoffs"]:
        pa = ts(c["prediction_at"])
        label_end = ts(c["horizon_end"]) + days(w.grace)
        part = "train" if pa < te else "validation" if pa < ve else "test" if pa < xe else "outside"
        rows.append({"cutoff_id": c["cutoff_id"], "account_id": c["account_id"], "split": part,
                     "label_end": label_end, "status": "retained", "drop_reason": None})
    test_acc = {r["account_id"] for r in rows if r["split"] == "test"}
    val_acc = {r["account_id"] for r in rows if r["split"] == "validation"}
    for r in rows:
        if r["split"] == "train" and r["label_end"] > te:
            r["status"], r["drop_reason"] = "dropped", "LABEL_WINDOW"
        elif r["split"] == "validation" and r["label_end"] > ve:
            r["status"], r["drop_reason"] = "dropped", "LABEL_WINDOW"
    for r in rows:
        if r["status"] == "retained" and r["split"] in ("train", "validation"):
            if r["account_id"] in test_acc:
                r["status"], r["drop_reason"] = "dropped", "GROUP_TEST"
            elif r["split"] == "train" and r["account_id"] in val_acc:
                r["status"], r["drop_reason"] = "dropped", "GROUP_VALIDATION"
    counts = {}
    for part in ("train", "validation", "test", "outside"):
        pr = [r for r in rows if r["split"] == part]
        counts[part] = {"total": len(pr), "retained": sum(1 for r in pr if r["status"] == "retained"),
                        "label_window": sum(1 for r in pr if r["drop_reason"] == "LABEL_WINDOW"),
                        "group_test": sum(1 for r in pr if r["drop_reason"] == "GROUP_TEST"),
                        "group_validation": sum(1 for r in pr if r["drop_reason"] == "GROUP_VALIDATION")}
    return rows, counts


# ---------------------------------------------------------------- metrics (D-03)
def rank_key(item):
    return (-item["p"], item["account_id"])


def average_precision(items, positives):
    """scikit-learn average_precision_score: sum over distinct thresholds of (R_n - R_{n-1}) * P_n."""
    if positives == 0:
        return None, []
    order = sorted(items, key=rank_key)
    levels = sorted({it["p"] for it in items}, reverse=True)
    tp = fp = 0
    prev_r = F(0)
    terms = []
    total = F(0)
    for lv in levels:
        grp = [it for it in order if it["p"] == lv]
        tp += sum(1 for it in grp if it["y"])
        fp += sum(1 for it in grp if not it["y"])
        prec, rec = F(tp, tp + fp), F(tp, positives)
        contrib = (rec - prev_r) * prec
        total += contrib
        terms.append({"threshold": p6(lv), "tp": tp, "fp": fp, "precision": p6(prec), "recall": p6(rec),
                      "delta_recall": p6(rec - prev_r), "contribution": p6(contrib)})
        prev_r = rec
    return total, terms


def calibration(items):
    bins = [[] for _ in range(CAL_BINS)]
    for it in items:
        scaled = it["p"] * CAL_BINS
        bins[min(scaled.numerator // scaled.denominator, CAL_BINS - 1)].append(it)
    out = []
    for i, b in enumerate(bins):
        mean = None if not b else sum((it["p"] for it in b), F(0)) / len(b)
        obs = None if not b else F(sum(1 for it in b if it["y"]), len(b))
        out.append({"index": i, "lower": p6(F(i, CAL_BINS)), "upper": p6(F(i + 1, CAL_BINS)),
                    "closed_upper": i == CAL_BINS - 1, "count": len(b), "mean_predicted": p6(mean),
                    "observed_rate": p6(obs), "gap_pp": None if not b else pp2(mean - obs)})
    return out


def economics(w, scen, queue):
    cost, eff, margin = Decimal(scen["contact_cost"]), Decimal(scen["assumed_effect"]), Decimal(scen["margin_value"])
    with localcontext() as ctx:
        ctx.prec = 50
        terms, total = [], Decimal(0)
        for it in queue:
            v = Decimal(it["pstr"]) * eff * margin - cost
            total += v
            terms.append({"account_id": it["account_id"], "probability": it["pstr"], "value_exact": str(v.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))})
        budget = cost * len(queue)
        return {"label": "hypothetical", "assumption_based": True, "scenario_id": scen["scenario_id"],
                "selected_account_ids": [it["account_id"] for it in queue],
                "assumptions": {"contact_cost": money(cost), "assumed_effect": str(eff), "margin_value": money(margin)},
                "contact_budget": money(budget), "terms": terms, "expected_value": money(total),
                "treatment_effect_estimate": None}


def psi(ref_counts, cur_counts, labels, floor):
    R, C = sum(ref_counts), sum(cur_counts)
    if R == 0 or C == 0:
        return None
    fl = F(floor)
    with localcontext() as ctx:
        ctx.prec = 60

        def dec(x):
            return Decimal(x.numerator) / Decimal(x.denominator)
        total = Decimal(0)
        bins = []
        for lab, r, c in zip(labels, ref_counts, cur_counts):
            e, a = F(r, R), F(c, C)
            ef, af = (fl if e == 0 else e), (fl if a == 0 else a)
            term = (dec(af) - dec(ef)) * (dec(af) / dec(ef)).ln()
            total += term
            bins.append({"label": lab, "reference_count": r, "current_count": c, "reference_proportion": p6(e),
                         "current_proportion": p6(a), "floored": e == 0 or a == 0,
                         "term": str(term.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP))})
        return total, bins


def in_bin(v, b):
    return v is not None and v >= b["lower"] and (b["upper"] is None or v < b["upper"])


def set_metrics(w, data, sc):
    pa, run_id, scen_id = sc["prediction_at"], data["scope"]["training_run_id"], sc.get("scenario_id")
    rows = w.set_rows(pa)
    elig = [r for r in rows if r["eligible"]]
    mature = [r for r in elig if r["mature"]]
    scored = [r for r in elig if (run_id, r["cutoff_id"]) in w.preds]
    evaluated = [r for r in mature if (run_id, r["cutoff_id"]) in w.preds]
    ineligible = {}
    for r in rows:
        if not r["eligible"]:
            ineligible[r["ineligible_code"]] = ineligible.get(r["ineligible_code"], 0) + 1
    churned = sum(1 for r in mature if r["churned"])
    pop = {"cutoff_rows": len(rows), "eligible": len(elig), "ineligible": dict(sorted(ineligible.items())),
           "mature": len(mature), "censored": len(elig) - len(mature), "scored": len(scored),
           "evaluated": len(evaluated), "unscored_excluded": len(mature) - len(evaluated), "churned": churned}
    items = []
    for r in evaluated:
        p = w.preds[(run_id, r["cutoff_id"])]["probability"]
        items.append({"p": F(p), "pstr": p, "y": bool(r["churned"]), "account_id": r["account_id"], "cutoff_id": r["cutoff_id"]})
    items.sort(key=rank_key)
    n = len(items)
    pos = sum(1 for it in items if it["y"])
    out = {"prediction_at": pa, "population": pop, "empty_population": len(elig) == 0, "empty_evaluation": n == 0,
           "churn_rate": {"value": p6(ratio(churned, len(mature))), "churned": churned, "mature_eligible": len(mature)},
           "late_events": {e: sum(r["arrived_late"][e] for r in elig) for e in EVENTS}}
    out["late_events"]["total"] = sum(out["late_events"].values())
    out["ranking"] = [{"rank": i + 1, "cutoff_id": it["cutoff_id"], "account_id": it["account_id"],
                       "probability": it["pstr"], "outcome": 1 if it["y"] else 0} for i, it in enumerate(items)]
    scen = w.scen.get(scen_id) if scen_id else None
    k = scen["capacity"] if scen else None
    cap_ok = None if k is None else (1 <= k <= n if n else False)
    out["capacity"] = None if scen is None else {"scenario_id": scen_id, "k": k, "population": n, "ok": cap_ok,
                                                  "refusal": None if cap_ok or n == 0 else "CAPACITY_EXCEEDS_POPULATION"}
    ap_total, ap_terms = average_precision(items, pos)
    out["precision_at_k"] = out["recall_at_k"] = out["risk_lift_at_k"] = None
    if cap_ok:
        hits = sum(1 for it in items[:k] if it["y"])
        top_rate = F(hits, k)
        out["precision_at_k"] = {"value": p6(top_rate), "hits": hits, "k": k}
        out["recall_at_k"] = {"value": p6(ratio(hits, pos)), "hits": hits, "positives": pos}
        overall = ratio(pos, n)
        out["risk_lift_at_k"] = {"value": p6(None if not pos else top_rate / overall), "top_k_rate": p6(top_rate),
                                 "overall_rate": p6(overall), "tie_split_at_k": k < n and items[k - 1]["p"] == items[k]["p"]}
    out["average_precision"] = {"value": p6(ap_total), "prevalence": p6(ratio(pos, n)), "positives": pos, "n": n,
                                "terms": ap_terms}
    brier = ratio(sum(((it["p"] - (1 if it["y"] else 0)) ** 2 for it in items), F(0)), n)
    out["brier_score"] = {"value": p6(brier), "n": n,
                          "terms": [p6((it["p"] - (1 if it["y"] else 0)) ** 2) for it in items]}
    out["calibration"] = {"bin_width": "0.100000", "bins": calibration(items)}
    queue = sorted([{"p": F(w.preds[(run_id, r["cutoff_id"])]["probability"]),
                     "pstr": w.preds[(run_id, r["cutoff_id"])]["probability"], "account_id": r["account_id"]}
                    for r in scored], key=rank_key)
    out["economics"] = None
    out["outreach_queue"] = None
    if scen and k is not None and 1 <= k <= len(queue):
        out["economics"] = economics(w, scen, queue[:k])
        out["outreach_queue"] = {"status": "draft", "account_ids": [q["account_id"] for q in queue[:k]],
                                 "population": len(queue)}
    # feature missingness over the eligible rows of the observation period (all maturities)
    period = pa[:7]
    miss = {}
    for f in FEATURES:
        m = sum(1 for r in elig if r["features"][f] is None)
        miss[f] = {"missing": m, "total": len(elig), "value": p6(ratio(m, len(elig)))}
    tm = sum(v["missing"] for v in miss.values())
    out["feature_missingness"] = {"period": period, "by_feature": miss,
                                  "overall": {"missing": tm, "total": len(elig) * len(FEATURES),
                                              "value": p6(ratio(tm, len(elig) * len(FEATURES)))}}
    out["population_drift"] = None
    dr = data["scope"].get("drift")
    if dr:
        ref_rows = [r for r in w.set_rows(dr["reference_prediction_at"]) if r["eligible"]]
        bins = dr["bins"]
        ref_c = [sum(1 for r in ref_rows if in_bin(r["features"][dr["feature"]], b)) for b in bins]
        cur_c = [sum(1 for r in elig if in_bin(r["features"][dr["feature"]], b)) for b in bins]
        res = psi(ref_c, cur_c, [b["label"] for b in bins], dr["floor"])
        out["population_drift"] = {"feature": dr["feature"], "reference_prediction_at": dr["reference_prediction_at"],
                                   "reference_rows": sum(ref_c), "current_rows": sum(cur_c),
                                   "psi": None if res is None else str(res[0].quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
                                   "threshold": dr["threshold"], "diagnostic_only": True,
                                   "exceeds_threshold": None if res is None else res[0] > Decimal(dr["threshold"]),
                                   "bins": [] if res is None else res[1]}
    return out, rows, elig


# ---------------------------------------------------------------- commands (D-01, D-02, D-03)
def classify_feature(w, name):
    r = w.reg.get(name)
    if r:
        if r.get("post_outcome"):
            return "POST_OUTCOME_FIELD"
        if r.get("latent"):
            return "LATENT_TRUTH"
        if r.get("id_derived"):
            return "ID_FEATURE"
        return None
    if name.startswith("latent_"):
        return "LATENT_TRUTH"
    if name.startswith("account_id"):
        return "ID_FEATURE"
    return "UNKNOWN_FEATURE"


FEATURE_PRIORITY = ["POST_OUTCOME_FIELD", "LATENT_TRUTH", "ID_FEATURE", "UNKNOWN_FEATURE"]


def run_command(w, rq, splits, data):
    res = {"request_id": rq["request_id"], "command": rq["command"], "status": "accepted", "reason_code": None,
           "offending": [], "result": None}

    def refuse(code, off, result=None):
        res.update(status="refused", reason_code=code, offending=off, result=result)
        return res
    cmd = rq["command"]
    if cmd == "build-point-in-time-features":
        bad = [(f, classify_feature(w, f)) for f in rq["fields"]]
        bad = [(f, c) for f, c in bad if c]
        if bad:
            code = min((c for _, c in bad), key=FEATURE_PRIORITY.index)
            return refuse(code, [{"item": f, "code": c} for f, c in bad])
        res["result"] = {"fields": list(rq["fields"])}
        return res
    run = w.runs.get(rq.get("training_run_id"))
    if run is None:
        return refuse("UNKNOWN_TRAINING_RUN", [{"item": rq.get("training_run_id"), "code": "UNKNOWN_TRAINING_RUN"}])
    rows = {r["cutoff_id"]: r for r in splits[run["training_run_id"]][0]}

    def retained(part):
        return {cid for cid, r in rows.items() if r["split"] == part and r["status"] == "retained"}
    if cmd == "fit-preprocessing":
        bad = [c for c in rq["fit_rows"] if c not in retained("train")]
        if bad:
            return refuse("LEAKAGE", [{"item": c, "code": "NOT_TRAINING_ROW"} for c in bad])
        res["result"] = {"fit_rows": len(rq["fit_rows"])}
    elif cmd == "calibrate-model":
        overlap = [c for c in rq["evaluation_rows"] if c in rq["fit_rows"]]
        if overlap:
            return refuse("CALIBRATION_ON_FIT_ROWS", [{"item": c, "code": "IN_FIT_ROWS"} for c in overlap])
        bad = [c for c in rq["fit_rows"] if c not in retained("validation")]
        if bad:
            return refuse("LEAKAGE", [{"item": c, "code": "NOT_VALIDATION_ROW"} for c in bad])
        res["result"] = {"fit_rows": len(rq["fit_rows"]), "evaluation_rows": len(rq["evaluation_rows"])}
    elif cmd == "select-threshold":
        if rq["selected_on"] != "validation":
            return refuse("THRESHOLD_ON_TEST", [{"item": rq["parameter"], "code": "SELECTED_ON_" + rq["selected_on"].upper()}])
        res["result"] = {"parameter": rq["parameter"], "selected_on": "validation"}
    elif cmd == "prioritize-outreach":
        scen = w.scen.get(rq["scenario_id"])
        if scen is None:
            return refuse("UNKNOWN_SCENARIO", [{"item": rq["scenario_id"], "code": "UNKNOWN_SCENARIO"}])
        pool = sorted([{"p": F(w.preds[(run["training_run_id"], r["cutoff_id"])]["probability"]), "account_id": r["account_id"]}
                       for r in w.set_rows(rq["prediction_at"]) if r["eligible"] and (run["training_run_id"], r["cutoff_id"]) in w.preds],
                      key=rank_key)
        if scen["capacity"] > len(pool):
            return refuse("CAPACITY_EXCEEDS_POPULATION", [{"item": scen["scenario_id"], "code": f"CAPACITY_{scen['capacity']}_GT_{len(pool)}"}])
        res["result"] = {"capacity": scen["capacity"], "population": len(pool), "status": "draft",
                         "queue_account_ids": [q["account_id"] for q in pool[:scen["capacity"]]]}
    return res


# ---------------------------------------------------------------- compute
def compute(data):
    acc, rejected = validate(data)
    w = World(data, acc)
    got = {"contract_version": data["contract_version"], "as_of": data["as_of"]}
    counts = {e: {"accepted": len(acc[e]), "rejected": sum(1 for r in rejected if r["entity"] == e)} for e in ENT}
    got["ingest"] = {"counts": counts, "rejected_records": rejected}

    # derived-versus-stored consistency
    cons = {"cutoff_windows_mismatched": [], "feature_rows_mismatched": [], "labels_mismatched": [],
            "split_assignments_mismatched": [], "scoring_publications_mismatched": [], "config_hash_mismatched": [],
            "outreach_queue_mismatched": [], "predictions_citation_mismatched": []}
    for c in acc["prediction_cutoffs"]:
        pa = ts(c["prediction_at"])
        if ts(c["horizon_end"]) != pa + days(w.horizon) or ts(c["observation_start"]) != pa - days(w.obs_days):
            cons["cutoff_windows_mismatched"].append(c["cutoff_id"])
    for fr in acc["feature_rows"]:
        a = w.analyse(fr["cutoff_id"])
        if not (a["eligible"] and fr["features_json"] == a["features"] and fr["max_available_at"] == a["max_available_at"]
                and fr["feature_version"] == w.fv
                and (fr["max_available_at"] is None or ts(fr["max_available_at"]) < ts(a["prediction_at"]))):
            cons["feature_rows_mismatched"].append(fr["feature_row_id"])
    for lb in acc["labels"]:
        a = w.analyse(lb["cutoff_id"])
        if not (a["eligible"] and lb["churned"] == a["churned"] and lb["mature"] == a["mature"] and lb["label_end"] == a["label_end"]):
            cons["labels_mismatched"].append(lb["label_id"])
    for r in acc["training_runs"]:
        if sha(canon(r["config"])) != r["config_hash"]:
            cons["config_hash_mismatched"].append(r["training_run_id"])
    for p in acc["predictions"]:
        cfg = w.runs[p["training_run_id"]]
        if (p["config_hash"], p["feature_version"], p["label_version"]) != (
                cfg["config_hash"], cfg["config"]["feature_version"], cfg["config"]["label_version"]):
            cons["predictions_citation_mismatched"].append(p["prediction_id"])
    splits = {rid: split_run(w, run) for rid, run in w.runs.items()}
    for sa in acc["split_assignments"]:
        d = {r["cutoff_id"]: r for r in splits[sa["training_run_id"]][0]}[sa["cutoff_id"]]
        if (sa["split"], sa["status"], sa["drop_reason"]) != (d["split"], d["status"], d["drop_reason"]):
            cons["split_assignments_mismatched"].append(sa["assignment_id"])
    pubs = []
    for sp in acc["scoring_publications"]:
        er = [r for r in w.set_rows(sp["prediction_at"]) if r["eligible"]]
        sc = sum(1 for r in er if (sp["training_run_id"], r["cutoff_id"]) in w.preds)
        status = "completed" if er and sc == len(er) else "incomplete"
        pubs.append({"publication_id": sp["publication_id"], "training_run_id": sp["training_run_id"],
                     "prediction_at": sp["prediction_at"], "published_at": sp["published_at"], "eligible": len(er),
                     "scored": sc, "status": status})
        if sp["status"] != status:
            cons["scoring_publications_mismatched"].append(sp["publication_id"])

    sets, pit = {}, []
    scope = data["scope"]
    for sc in scope["sets"]:
        m, rows, elig = set_metrics(w, data, sc)
        sets[sc["prediction_at"]] = m
        pit.extend(rows)
        if sc.get("scenario_id") and m["outreach_queue"] is not None:
            stored = sorted(o["account_id"] for o in acc["outreach_events"] if o["scenario_id"] == sc["scenario_id"])
            if stored != sorted(m["outreach_queue"]["account_ids"]):
                cons["outreach_queue_mismatched"].append(sc["scenario_id"])
    dr = scope.get("drift")
    if dr:
        have = {r["cutoff_id"] for r in pit}
        pit.extend(r for r in w.set_rows(dr["reference_prediction_at"]) if r["cutoff_id"] not in have)
    got["consistency"] = cons
    got["commands"] = [run_command(w, rq, splits, data) for rq in data.get("requests", [])]
    got["split"] = {rid: {"train_end": w.runs[rid]["train_end"], "validation_end": w.runs[rid]["validation_end"],
                          "test_end": w.runs[rid]["test_end"], "embargo_days": w.horizon + w.grace,
                          "counts": c, "assignments": [
                              {"cutoff_id": r["cutoff_id"], "split": r["split"], "status": r["status"], "drop_reason": r["drop_reason"]}
                              for r in rs]} for rid, (rs, c) in splits.items()}
    got["point_in_time"] = {"rows": [{k: v for k, v in r.items()} for r in pit]}
    # freshness
    done = [p for p in pubs if p["status"] == "completed" and ts(p["published_at"]) <= w.as_of]
    latest = max(done, key=lambda p: (ts(p["published_at"]), p["publication_id"])) if done else None
    avail = [ts(ev["available_at"]) for e in EVENTS for ev in acc[e] if ts(ev["available_at"]) <= w.as_of]
    la = max(avail) if avail else None
    got["scoring_publications"] = pubs
    got["freshness"] = {"as_of": data["as_of"],
                        "scoring_hours": None if latest is None else hours_between(w.as_of, ts(latest["published_at"])),
                        "latest_completed_publication_id": None if latest is None else latest["publication_id"],
                        "latest_completed_published_at": None if latest is None else latest["published_at"],
                        "data_hours": None if la is None else hours_between(w.as_of, la),
                        "latest_available_at": None if la is None else fmt(la)}
    got["cutoff_sets"] = sets
    got["empty_population"] = all(s["empty_population"] for s in sets.values()) if sets else True
    return got


# ---------------------------------------------------------------- comparison
def flatten(x, prefix=""):
    out = {}
    if isinstance(x, dict):
        if not x:
            out[prefix] = {}
        for k, v in x.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(x, list):
        if not x:
            out[prefix] = []
        for i, v in enumerate(x):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = x
    return out


def no_floats(x, where):
    if isinstance(x, float):
        report(False, f"{where}.no_float", "no float", x)
    elif isinstance(x, dict):
        [no_floats(v, where) for v in x.values()]
    elif isinstance(x, list):
        [no_floats(v, where) for v in x]


def check_fixture(label, prefix):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    no_floats(data, label + ".inputs")
    no_floats(exp, label)
    got = compute(data)
    fe, fg = flatten(exp), flatten(got)
    for k in fe:
        report(k in fg and fg[k] == fe[k] and type(fg[k]) is type(fe[k]), f"{label}.{k}", fe[k], fg.get(k, "<missing>"))
    for k in fg:
        if k not in fe:
            report(False, f"{label}.{k}", "<absent>", fg[k])
    return exp


def hand(exps):
    """The hand-worked figures of CALCULATION.md, typed as literals, against expected.json (not against compute)."""
    g, vr, ve = exps["golden"], exps["variant-rejected"], exps["variant-empty"]
    JAN, FEB = "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"
    j, f = g["cutoff_sets"][JAN], g["cutoff_sets"][FEB]
    jb = {b["index"]: b for b in j["calibration"]["bins"]}
    rows = {r["cutoff_id"]: r for r in g["point_in_time"]["rows"]}
    sp = g["split"]["tr-001"]
    sa = {a["cutoff_id"]: a for a in sp["assignments"]}
    v = vr["cutoff_sets"][JAN]
    ec = j["economics"]
    # the arithmetic itself, from the hand-written fractions, rounded the documented way
    brier_terms = [F(4, 100), F(36, 100), F(36, 100), F(1, 100)]      # (.8-1)^2, (.6-0)^2, (.4-1)^2, (.1-0)^2
    ap_terms = [F(1, 2) * 1, F(0) * F(1, 2), F(1, 2) * F(2, 3), F(0) * F(1, 2)]
    ev1 = Decimal("0.8") * Decimal("0.1") * Decimal("131.75") - Decimal("5.00")   # 10.54 - 5.00
    ev2 = Decimal("0.6") * Decimal("0.1") * Decimal("131.75") - Decimal("5.00")   # 7.905 - 5.00
    with localcontext() as ctx:
        ctx.prec = 40
        psi_jan = Decimal(3) * Decimal(2).ln() / Decimal(28)                       # 3 ln2 / 28, the closed form
    rows_ = [
        # golden P10-GOLD-01
        ("hand.brier_term_a1_0.04", p6(brier_terms[0]), j["brier_score"]["terms"][0]),
        ("hand.brier_term_a2_0.36", p6(brier_terms[1]), j["brier_score"]["terms"][1]),
        ("hand.brier_term_a3_0.36", p6(brier_terms[2]), j["brier_score"]["terms"][2]),
        ("hand.brier_term_a4_0.01", p6(brier_terms[3]), j["brier_score"]["terms"][3]),
        ("hand.brier_sum_0.77_over_4_is_0.1925", p6(sum(brier_terms, F(0)) / 4), j["brier_score"]["value"]),
        ("hand.brier_sum_is_0.77", F(77, 100), sum(brier_terms, F(0))),
        ("hand.ap_term_rank1_half_times_1", p6(ap_terms[0]), j["average_precision"]["terms"][0]["contribution"]),
        ("hand.ap_term_rank2_zero", p6(ap_terms[1]), j["average_precision"]["terms"][1]["contribution"]),
        ("hand.ap_term_rank3_half_times_two_thirds", p6(ap_terms[2]), j["average_precision"]["terms"][2]["contribution"]),
        ("hand.ap_term_rank4_zero", p6(ap_terms[3]), j["average_precision"]["terms"][3]["contribution"]),
        ("hand.ap_is_5_6", p6(sum(ap_terms, F(0))), j["average_precision"]["value"]),
        ("hand.ap_5_6_equals_one_half_plus_one_third", F(5, 6), F(1, 2) + F(1, 3)),
        ("hand.ap_baseline_prevalence_2_4", p6(F(2, 4)), j["average_precision"]["prevalence"]),
        ("hand.precision_at_2_is_1_2", p6(F(1, 2)), j["precision_at_k"]["value"]),
        ("hand.recall_at_2_is_1_2", p6(F(1, 2)), j["recall_at_k"]["value"]),
        ("hand.risk_lift_at_2_is_1", p6((F(1, 2)) / F(2, 4)), j["risk_lift_at_k"]["value"]),
        ("hand.churn_rate_2_of_4", p6(F(2, 4)), j["churn_rate"]["value"]),
        ("hand.ranking_order_1_2_3_4", [1, 2, 3, 4], [r["account_id"] for r in j["ranking"]]),
        ("hand.outcomes_1_0_1_0", [1, 0, 1, 0], [r["outcome"] for r in j["ranking"]]),
        # economics D-03, hypothetical
        ("hand.contact_budget_2_x_5.00", money(2 * Decimal("5.00")), ec["contact_budget"]),
        ("hand.ev_term_a1_5.54", format(ev1, ".6f"), ec["terms"][0]["value_exact"]),
        ("hand.ev_term_a2_2.905", format(ev2, ".6f"), ec["terms"][1]["value_exact"]),
        ("hand.ev_8.445_rounds_half_up_to_8.45", money(ev1 + ev2), ec["expected_value"]),
        ("hand.economics_labelled_hypothetical", "hypothetical", ec["label"]),
        ("hand.no_treatment_effect_estimate", None, ec["treatment_effect_estimate"]),
        # eligibility, maturity, labels
        ("hand.jan_eligible_4_of_6", (6, 4), (j["population"]["cutoff_rows"], j["population"]["eligible"])),
        ("hand.a5_cancelled_before_cutoff_not_active", "NOT_ACTIVE", rows["co-05-20260101"]["ineligible_code"]),
        ("hand.a6_created_at_observation_start_ineligible", "CREATED_ON_OR_AFTER_OBSERVATION_START", rows["co-06-20260101"]["ineligible_code"]),
        ("hand.jan_label_end_2026-04-15", "2026-04-15T00:00:00Z", rows["co-01-20260101"]["label_end"]),
        ("hand.a3_cancel_arrives_in_grace_is_churn", True, rows["co-03-20260101"]["churned"]),
        ("hand.a4_cancel_arrives_after_label_end_is_not_churn", False, rows["co-04-20260101"]["churned"]),
        ("hand.a2_cancel_after_horizon_is_not_churn", False, rows["co-02-20260101"]["churned"]),
        ("hand.feb_label_end_2026-05-16_is_after_as_of", ("2026-05-16T00:00:00Z", False), (rows["co-01-20260201"]["label_end"], rows["co-01-20260201"]["mature"])),
        ("hand.feb_all_4_censored_none_mature", (4, 0), (f["population"]["censored"], f["population"]["mature"])),
        ("hand.feb_churn_rate_null_zero_denominator", None, f["churn_rate"]["value"]),
        ("hand.feb_label_null_not_false", None, rows["co-01-20260201"]["churned"]),
        # features, arrived late, boundaries
        ("hand.late_event_counted_usage_1_support_1", (1, 1, 2), (j["late_events"]["usage_events"], j["late_events"]["support_events"], j["late_events"]["total"])),
        ("hand.a1_usage_30d_is_2_late_event_excluded", 2, rows["co-01-20260101"]["features"]["usage_events_30d"]),
        ("hand.a1_days_since_usage_12", 12, rows["co-01-20260101"]["features"]["days_since_last_usage"]),
        ("hand.a1_billing_98.00_cutoff_instant_excluded", "98.00", rows["co-01-20260101"]["features"]["billing_total_90d"]),
        ("hand.a1_max_available_at_before_cutoff", "2025-12-20T00:00:00Z", rows["co-01-20260101"]["max_available_at"]),
        ("hand.a4_billing_20.00_observation_start_included", "20.00", rows["co-04-20260101"]["features"]["billing_total_90d"]),
        ("hand.a4_late_high_support_excluded", 0, rows["co-04-20260101"]["features"]["high_severity_support_90d"]),
        ("hand.a4_days_since_usage_6h_floors_to_0", 0, rows["co-04-20260101"]["features"]["days_since_last_usage"]),
        ("hand.a3_no_usage_days_since_null", None, rows["co-03-20260101"]["features"]["days_since_last_usage"]),
        ("hand.a3_no_billing_null_not_zero", None, rows["co-03-20260101"]["features"]["billing_total_90d"]),
        ("hand.same_a4_billing_20.00_in_feb_window", "20.00", rows["co-04-20260201"]["features"]["billing_total_90d"]),
        # missingness
        ("hand.jan_missing_2_of_16", p6(F(2, 16)), j["feature_missingness"]["overall"]["value"]),
        ("hand.feb_missing_1_of_16", p6(F(1, 16)), f["feature_missingness"]["overall"]["value"]),
        ("hand.jan_missing_days_since_1_of_4", p6(F(1, 4)), j["feature_missingness"]["by_feature"]["days_since_last_usage"]["value"]),
        # calibration, 10 equal-width bins
        ("hand.bin8_p0.8_goes_to_0.8_0.9_gap_-20.00", ("1", "-20.00"), (str(jb[8]["count"]), jb[8]["gap_pp"])),
        ("hand.bin6_p0.6_gap_+60.00", ("1", "60.00"), (str(jb[6]["count"]), jb[6]["gap_pp"])),
        ("hand.bin4_p0.4_gap_-60.00", ("1", "-60.00"), (str(jb[4]["count"]), jb[4]["gap_pp"])),
        ("hand.bin1_p0.1_gap_+10.00", ("1", "10.00"), (str(jb[1]["count"]), jb[1]["gap_pp"])),
        ("hand.six_empty_bins_have_null_gap", (6, 6), (sum(1 for b in jb.values() if b["count"] == 0), sum(1 for b in jb.values() if b["gap_pp"] is None))),
        # drift (PSI)
        ("hand.reference_proportions_2_7_4_7_1_7", ("0.285714", "0.571429", "0.142857"), tuple(b["reference_proportion"] for b in j["population_drift"]["bins"])),
        ("hand.psi_jan_is_3_ln2_over_28", str(psi_jan.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)), j["population_drift"]["psi"]),
        ("hand.psi_jan_below_0.2_diagnostic", False, j["population_drift"]["exceeds_threshold"]),
        ("hand.feb_zero_bin_floored_to_0.0001", True, f["population_drift"]["bins"][0]["floored"]),
        ("hand.feb_psi_bin0_term", "2.2727977861", f["population_drift"]["bins"][0]["term"]),
        ("hand.feb_psi_2.381316_exceeds_diagnostic", ("2.381316", True), (f["population_drift"]["psi"], f["population_drift"]["exceeds_threshold"])),
        # freshness, hours
        ("hand.scoring_freshness_120d_minus_2h_is_2878", 120 * 24 - 2, g["freshness"]["scoring_hours"]),
        ("hand.data_freshness_11d_is_264", 11 * 24, g["freshness"]["data_hours"]),
        ("hand.incomplete_publication_not_counted", ("sp-001", "incomplete"), (g["freshness"]["latest_completed_publication_id"], g["scoring_publications"][1]["status"])),
        # split
        ("hand.train_10_rows_4_retained", (10, 4), (sp["counts"]["train"]["total"], sp["counts"]["train"]["retained"])),
        ("hand.train_dropped_label_2_group_test_2_group_validation_2", (2, 2, 2), (sp["counts"]["train"]["label_window"], sp["counts"]["train"]["group_test"], sp["counts"]["train"]["group_validation"])),
        ("hand.validation_6_rows_3_retained_label_2_group_1", (6, 3, 2, 1), (sp["counts"]["validation"]["total"], sp["counts"]["validation"]["retained"], sp["counts"]["validation"]["label_window"], sp["counts"]["validation"]["group_test"])),
        ("hand.test_11_rows_all_retained", (11, 11), (sp["counts"]["test"]["total"], sp["counts"]["test"]["retained"])),
        ("hand.label_end_equals_train_end_is_retained", ("train", "retained"), (sa["co-10-20250319"]["split"], sa["co-10-20250319"]["status"])),
        ("hand.label_end_equals_validation_end_is_retained", ("validation", "retained"), (sa["co-13-20250819"]["split"], sa["co-13-20250819"]["status"])),
        ("hand.row_at_validation_end_is_test", "test", sa["co-14-20251201"]["split"]),
        ("hand.row_crossing_train_end_label_window", "LABEL_WINDOW", sa["co-07-20250501"]["drop_reason"]),
        ("hand.group_purge_of_label_dropped_validation_row_still_applies", "GROUP_VALIDATION", sa["co-12-20250301"]["drop_reason"]),
        ("hand.account_in_test_loses_validation_row", "GROUP_TEST", sa["co-03-20250701"]["drop_reason"]),
        ("hand.golden_ingest_rejects_nothing", 0, len(g["ingest"]["rejected_records"])),
        # rejected variant
        ("hand.variant_tie_ap_is_0.5_not_1", "0.500000", v["average_precision"]["value"]),
        ("hand.variant_brier_0.54_over_3", p6(F(54, 100) / 3), v["brier_score"]["value"]),
        ("hand.variant_lift_1_over_1_3_is_3", p6(F(1, 1) / F(1, 3)), v["risk_lift_at_k"]["value"]),
        ("hand.variant_tie_split_at_k", True, v["risk_lift_at_k"]["tie_split_at_k"]),
        ("hand.variant_churn_rate_1_of_4_unscored_counts", ("0.250000", 1), (v["churn_rate"]["value"], v["population"]["unscored_excluded"])),
        ("hand.variant_ev_0.5x0.2x100-8_is_2.00", money(Decimal("0.5") * Decimal("0.2") * Decimal("100") - Decimal("8.00")), v["economics"]["expected_value"]),
        ("hand.variant_missing_7_of_16", p6(F(7, 16)), v["feature_missingness"]["overall"]["value"]),
        ("hand.variant_rejected_total_18", 18, len(vr["ingest"]["rejected_records"])),
        ("hand.variant_refusals_nine", 9, sum(1 for c in vr["commands"] if c["status"] == "refused")),
        ("hand.variant_refusal_codes",
         ["POST_OUTCOME_FIELD", "LATENT_TRUTH", "ID_FEATURE", "POST_OUTCOME_FIELD", "UNKNOWN_FEATURE", "LEAKAGE",
          "CALIBRATION_ON_FIT_ROWS", "THRESHOLD_ON_TEST", "CAPACITY_EXCEEDS_POPULATION"], [c["reason_code"] for c in vr["commands"]]),
        ("hand.variant_no_completed_publication_freshness_null", None, vr["freshness"]["scoring_hours"]),
        # empty variant
        ("hand.empty_every_count_zero", True, all(c == {"accepted": 0, "rejected": 0} for c in ve["ingest"]["counts"].values())),
        ("hand.empty_ratios_null", (None, None, None, None), (ve["cutoff_sets"][JAN]["churn_rate"]["value"], ve["cutoff_sets"][JAN]["average_precision"]["value"],
                                                          ve["cutoff_sets"][JAN]["brier_score"]["value"], ve["cutoff_sets"][JAN]["population_drift"]["psi"])),
        ("hand.empty_freshness_null", (None, None), (ve["freshness"]["scoring_hours"], ve["freshness"]["data_hours"])),
    ]
    for name, want, got in rows_:
        report(want == got and type(want) is type(got), name, want, got)


def sha_file(rel):
    return hashlib.sha256((GOLDEN / rel).read_bytes()).hexdigest()


def write_expected():
    for label, prefix in FIXTURES:
        data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
        (GOLDEN / (prefix + "expected.json")).write_text(json.dumps(compute(data), indent=2) + "\n")
        print(f"wrote {prefix}expected.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true")
    ap.add_argument("--write-expected", action="store_true")
    args = ap.parse_args()
    if args.write_expected:
        write_expected()
        return 0
    exps = {}
    for label, prefix in FIXTURES:
        exps[label] = check_fixture(label, prefix)
    hand(exps)
    e = exps["variant-empty"]
    report(e["empty_population"] is True, "variant-empty.empty_population_true", True, e["empty_population"])
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
