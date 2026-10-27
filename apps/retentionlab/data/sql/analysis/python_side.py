"""The independent Python side of the analysis (P10-ART-04): every result set of investigations 01..08 and 10 (and 09 for the golden fixture) recomputed from the RAW published JSON.

Standard library only (``json``, ``fractions``, ``decimal``, ``datetime``): no SQL, no psycopg, no ``retentionlab`` domain code, no reference SQL. It reads ``web/public/data/*.json``
(the wrapped entity files, ``test_cohort.json``, ``cutoff_aggregates.json``, ``split_summary.json`` and the manifest) and ``tests/fixtures/golden/inputs.json`` and returns, for each result
set that ``run_all.py`` also runs in SQL, the same rows (``<file>__<block>`` keys, same columns, same order) so that the two sides are compared cell by cell. Ratios are ``Fraction``s
rounded once, half away from zero, to the places the SQL rounds to. AVERAGE PRECISION and the POPULATION STABILITY INDEX are computed here too (tied probabilities are one threshold;
``Decimal.ln`` at 60 digits), so the SQL recomputation of both in the investigations has an independent second statement. This file is a second, separately written statement of D-01..D-09.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "inputs.json"
UTC = timezone.utc
MODELS = (("random_baseline", "p_random_baseline"), ("business_rule", "p_business_rule"), ("logistic_regression (Platt)", "p_logistic_calibrated"),
          ("prevalence_baseline", "p_prevalence_baseline"), ("logistic_regression (before Platt)", "p_logistic_uncalibrated"))
RANGE_ORD = {"train": 1, "validation": 2, "test": 3, "outside": 4}
TEST_POP = "test table: 1,513 mature eligible rows of the full world (outcomes known)"


def ts(s: str | None) -> datetime | None:
    return None if s is None else datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def rnd(x: F | None, places: int) -> Decimal | None:
    """Round half away from zero (what PostgreSQL's round(numeric) does) and keep the trailing zeros."""
    if x is None:
        return None
    x = F(x)
    scaled = abs(x) * 10 ** places
    q = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    d = Decimal(q).scaleb(-places).quantize(Decimal(1).scaleb(-places))
    return -d if x < 0 and q else d


def norm(v) -> str:
    """One text for a cell, whichever side produced it (None is the empty text; Decimals keep their places)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def normalised(rows: list[dict]) -> list[dict]:
    return [{k: norm(v) for k, v in r.items()} for r in rows]


def wrapped(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text())["rows"]


def jload(name: str):
    return json.loads((DATA / f"{name}.json").read_text())


def dstr(s: str, places: int) -> Decimal:
    return Decimal(s).quantize(Decimal(1).scaleb(-places))


def ratio(n: int, d: int, places: int = 6) -> Decimal | None:
    return None if d == 0 else rnd(F(n, d), places)


# ---- metrics over (p, y, account, cutoff) items ----------------------------------------------------------------------------------------------------------------------------------
def avg_precision(items: list[tuple[F, int]]) -> F:
    """sum over DISTINCT probabilities of (recall step) x (precision at that threshold): scikit-learn's step form."""
    pos = sum(y for _, y in items)
    tp = n = 0
    total = F(0)
    for level in sorted({p for p, _ in items}, reverse=True):
        grp = [y for p, y in items if p == level]
        tp += sum(grp)
        n += len(grp)
        total += F(sum(grp), pos) * F(tp, n)
    return total


def brier(items: list[tuple[F, int]]) -> F:
    return sum(((p - y) ** 2 for p, y in items), F(0)) / len(items)


def psi(ref: list[int], cur: list[int]) -> tuple[Decimal, int]:
    """sum (a - e) ln(a / e) over the declared bins; a zero proportion is replaced by 0.0001 without renormalising; returns (psi, floored bins)."""
    rt, ct = sum(ref), sum(cur)
    with localcontext() as ctx:
        ctx.prec = 60
        tot, floored = Decimal(0), 0
        for r, c in zip(ref, cur):
            e = F(r, rt) if r else F(1, 10000)
            a = F(c, ct) if c else F(1, 10000)
            floored += 1 if (r == 0 or c == 0) else 0
            tot += (Decimal(a.numerator) / Decimal(a.denominator) - Decimal(e.numerator) / Decimal(e.denominator)) * (Decimal(a.numerator) * Decimal(e.denominator) / (Decimal(a.denominator) * Decimal(e.numerator))).ln()
        return tot, floored


def psi6(ref: list[int], cur: list[int]) -> tuple[Decimal, int, bool]:
    v, fl = psi(ref, cur)
    return v.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), fl, v > Decimal("0.2")


def usage_bin(u: int) -> int:
    return 0 if u < 1 else (1 if u < 3 else 2)


class Test:
    """The test table of the full world."""

    def __init__(self) -> None:
        t = jload("test_cohort")
        self.cols, self.cutoffs = t["head"]["columns"], [ts(c) for c in t["head"]["cutoffs"]]
        self.rows = [dict(zip(self.cols, r)) for r in t["rows"]]
        for r in self.rows:
            r["pa"] = self.cutoffs[r["cutoff_index"]]
            for _, col in MODELS:
                r[col] = F(r[col])

    def items(self, col: str, pick=lambda r: True) -> list[tuple[F, int]]:
        return [(r[col], r["churned"]) for r in self.rows if pick(r)]


# ---- 01 ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def r01(T: Test) -> dict:
    models = []
    for name, col in MODELS:
        it = T.items(col)
        pos = sum(y for _, y in it)
        models.append({"model": name, "test_rows": len(it), "accounts": len({r["account_id"] for r in T.rows}), "positive_rows": pos,
                       "positive_accounts": len({r["account_id"] for r in T.rows if r["churned"]}), "prevalence": ratio(pos, len(it)),
                       "average_precision": rnd(avg_precision(it), 6), "brier_score": rnd(brier(it), 6), "mean_probability": rnd(sum((p for p, _ in it), F(0)) / len(it), 6)})
    per = []
    for pa in T.cutoffs:
        rows = [r for r in T.rows if r["pa"] == pa]
        per.append({"prediction_at": pa, "test_rows": len(rows), "positive_rows": sum(r["churned"] for r in rows), "prevalence": ratio(sum(r["churned"] for r in rows), len(rows)),
                    "logistic_brier": rnd(brier([(r["p_logistic_calibrated"], r["churned"]) for r in rows]), 6)})
    return {"01_model_comparison__models": models, "01_model_comparison__per_cutoff": per}


# ---- 02 ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def det_sigmoid_platt(p: F, a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        pc = min(max(p, F(1, 1000000)), F(999999, 1000000))
        d = Decimal(pc.numerator) / Decimal(pc.denominator)
        z = a * (d / (1 - d)).ln() + b
        return 1 / (1 + (-z).exp())


def r02(T: Test, C: "Cohort") -> dict:
    bins = []
    for ord_, (name, col) in enumerate([MODELS[2], MODELS[4]], 1):
        cnt = {i: [] for i in range(10)}
        for r in T.rows:
            cnt[min(int(r[col] * 10 // 1), 9)].append(r)
        for i in range(10):
            b = cnt[i]
            n, pos = len(b), sum(r["churned"] for r in b)
            mean = None if not n else sum((r[col] for r in b), F(0)) / n
            obs = None if not n else F(pos, n)
            bins.append({"model": name, "bin_index": i, "lower_bound": rnd(F(i, 10), 6), "upper_bound": rnd(F(i + 1, 10), 6), "rows_in_bin": n, "churned_rows": pos, "empty_bin": n == 0,
                         "mean_predicted": None if n == 0 else rnd(mean, 6), "observed_rate": None if n == 0 else rnd(obs, 6), "gap_pp": None if n == 0 else rnd((mean - obs) * 100, 2)})
    n = len(T.rows)
    cal = C.run["config"]["calibration"]
    bu, bc = brier(T.items("p_logistic_uncalibrated")), brier(T.items("p_logistic_calibrated"))
    mean_y = F(sum(r["churned"] for r in T.rows), n)
    gu = sum((r["p_logistic_uncalibrated"] for r in T.rows), F(0)) / n - mean_y
    gc = sum((r["p_logistic_calibrated"] for r in T.rows), F(0)) / n - mean_y
    eff = [{"test_rows": n, "platt_a": dstr(cal["a"], 6), "platt_b": dstr(cal["b"], 6), "fit_rows": cal["fit_rows"], "brier_before": rnd(bu, 6), "brier_after": rnd(bc, 6),
            "brier_change": rnd(bc - bu, 6), "overall_gap_pp_before": rnd(gu * 100, 2), "overall_gap_pp_after": rnd(gc * 100, 2), "made_the_brier_worse": rnd(bc, 6) > rnd(bu, 6)}]
    fit: dict[datetime, int] = {}
    for sa in C.split:
        if sa["split"] == "validation" and sa["status"] == "retained":
            c = C.cutoff[sa["cutoff_id"]]
            lab = C.label.get(sa["cutoff_id"])
            if lab and lab["mature"] and sa["cutoff_id"] in C.features:
                fit[c["pa"]] = fit.get(c["pa"], 0) + 1
    a, b = dstr(cal["a"], 6), dstr(cal["b"], 6)
    eq = within = far = 0
    for r in T.rows:
        raw = det_sigmoid_platt(r["p_logistic_uncalibrated"], a, b).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        stored = Decimal(r["p_logistic_calibrated"].numerator) / Decimal(r["p_logistic_calibrated"].denominator)
        eq += raw == stored
        within += abs(raw - stored) <= Decimal("0.000001")
        far += abs(raw - stored) > Decimal("0.000001")
    return {"02_calibration_platt__bins": bins, "02_calibration_platt__platt_effect": eff,
            "02_calibration_platt__fit_rows_by_cutoff": [{"prediction_at": k, "retained_mature_validation_rows_of_the_cohort": v} for k, v in sorted(fit.items())],
            "02_calibration_platt__platt_reproduced": [{"rows_compared": n, "equal_at_6_places": eq, "within_one_unit_in_the_6th_place": within, "further_apart": far}]}


# ---- the cohort (raw entity files) -----------------------------------------------------------------------------------------------------------------------------------------------
class Cohort:
    def __init__(self) -> None:
        self.manifest = jload("manifest")
        self.as_of = ts(self.manifest["as_of"])
        self.run = wrapped("training_runs")[0]
        self.accounts = {a["account_id"]: a for a in wrapped("accounts")}
        self.cutoffs = wrapped("prediction_cutoffs")
        self.cutoff = {}
        for c in self.cutoffs:
            self.cutoff[c["cutoff_id"]] = {**c, "pa": ts(c["prediction_at"]), "obs": ts(c["observation_start"]), "hz": ts(c["horizon_end"]), "label_end": ts(c["horizon_end"]) + timedelta(days=14)}
        self.features = {f["cutoff_id"]: f for f in wrapped("feature_rows")}
        # the four injected labels of false for an open window are refused by the seed (INJ-07); the rest are loaded
        self.rejected_labels = [l for l in wrapped("labels") if (not l["mature"]) and l["churned"] is not None]
        self.label = {l["cutoff_id"]: l for l in wrapped("labels") if not ((not l["mature"]) and l["churned"] is not None)}
        self.ev = {k: wrapped(k) for k in ("usage_events", "billing_events", "support_events", "subscription_events")}
        self.by_account: dict[str, dict[int, list]] = {}
        for k, rows in self.ev.items():
            idx = self.by_account.setdefault(k, {})
            for e in rows:
                e["t"], e["av"] = ts(e["event_at"]), ts(e["available_at"])
                idx.setdefault(e["account_id"], []).append(e)
        self.split = wrapped("split_assignments")
        self.pred = wrapped("predictions")
        self.scen = wrapped("intervention_scenarios")
        self.outreach = wrapped("outreach_events")
        self.train_end, self.validation_end, self.test_end = ts(self.run["train_end"]), ts(self.run["validation_end"]), ts(self.run["test_end"])

    def range_of(self, pa: datetime) -> str:
        return "train" if pa < self.train_end else "validation" if pa < self.validation_end else "test" if pa < self.test_end else "outside"


# ---- 03 ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def r03(T: Test, C: Cohort) -> dict:
    out = []
    for name, col in (MODELS[0], MODELS[1], MODELS[2], MODELS[3]):
        order = sorted(T.rows, key=lambda r: (-r[col], r["account_id"], r["cutoff_index"]))
        n, pos = len(order), sum(r["churned"] for r in order)
        for sid, k in (("sc-001", 5), ("sc-002", 10), ("sc-003", 20)):
            tp = sum(r["churned"] for r in order[:k])
            level = order[k - 1][col]
            tie = any(r[col] == level for r in order[k:])
            out.append({"model": name, "scenario_id": sid, "capacity": k, "evaluated_rows": n, "positives": pos, "churners_in_top_k": tp, "precision_at_k": ratio(tp, k),
                        "recall_at_k": ratio(tp, pos), "risk_lift_at_k": rnd(F(tp, k) / F(pos, n), 6), "tie_split_at_k": tie, "population": TEST_POP})
    latest = max(C.cutoff[p["cutoff_id"]]["pa"] for p in C.pred)
    scored = [(C.cutoff[p["cutoff_id"]]["account_id"], Decimal(p["probability"])) for p in C.pred if p["model_name"] == "logistic_regression" and C.cutoff[p["cutoff_id"]]["pa"] == latest]
    ranked = sorted(scored, key=lambda x: (-x[1], x[0]))
    world = {s: e for s, e in C.manifest["economics_full_world"]["scenarios"].items()}
    coh, both = [], []
    for s in sorted(C.scen, key=lambda s: s["capacity"]):
        k = s["capacity"]
        cost, eff, mar = Decimal(s["contact_cost"]), Decimal(s["assumed_effect"]), Decimal(s["margin_value"])
        top = ranked[:k]
        ev = sum((p * eff * mar - cost for _, p in top), Decimal(0))
        ev2 = rnd(F(ev), 2)
        queue = {o["account_id"] for o in C.outreach if o["scenario_id"] == s["scenario_id"]}
        coh.append({"scenario_id": s["scenario_id"], "capacity": k, "scored_accounts": len(scored), "contact_cost": cost.quantize(Decimal("0.000001")), "assumed_effect": eff.quantize(Decimal("0.000001")),
                    "margin_value": mar.quantize(Decimal("0.000001")), "selected_accounts": len(top), "contact_budget": rnd(F(cost * k), 2), "expected_value": ev2,
                    "stored_draft_queue_rows": len(queue), "stored_rows_in_my_top_k": len(queue & {a for a, _ in top}), "label": "hypothetical",
                    "population": "97 scored accounts of the published cohort at 2026-09-01 (outcomes censored)"})
        w = world[s["scenario_id"]]
        both.append({"scenario_id": s["scenario_id"], "capacity": k, "contact_budget": rnd(F(cost * k), 2), "cohort_scored_accounts": len(scored), "cohort_expected_value": ev2,
                     "world_scored_accounts": w["scored_accounts"], "world_expected_value": dstr(w["expected_value"], 2), "world_contact_budget": dstr(w["contact_budget"], 2),
                     "world_value_positive": Decimal(w["expected_value"]) > 0, "cohort_value_positive": ev2 > 0, "label": "hypothetical", "world_label_is_hypothetical": w["label"] == "hypothetical"})
    rows = [c for c in C.cutoff.values() if c["pa"] == latest and c["cutoff_id"] in C.label]
    cens = [{"prediction_at": latest, "cohort_cutoff_rows": len(rows), "mature_rows": sum(1 for c in rows if C.label[c["cutoff_id"]]["mature"]),
             "censored_rows": sum(1 for c in rows if not C.label[c["cutoff_id"]]["mature"])}]
    return {"03_capacity_economics__test_population_at_k": out, "03_capacity_economics__cohort_economics": coh, "03_capacity_economics__both_populations": both,
            "03_capacity_economics__censored_at_the_queue_cutoff": cens}


# ---- 04 ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def r04(C: Cohort) -> dict:
    agg = jload("cutoff_aggregates")["cutoffs"]
    naive = C.manifest["designed_relationships"][4]["realised"]["churn_rate_if_censored_were_non_churn"]
    world = []
    for c in agg:
        p = c["population"]
        pa = ts(c["prediction_at"])
        rate = naive.get(c["prediction_at"])
        world.append({"prediction_at": pa, "split_range": c["range"], "cutoff_rows": p["cutoff_rows"], "eligible": p["eligible"], "mature": p["mature"], "censored": p["censored"], "churned": p["churned"],
                      "censored_share": ratio(p["censored"], p["eligible"]), "mature_churn_rate": ratio(p["churned"], p["mature"]),
                      "published_rate_if_censored_were_non_churn": None if rate is None else Decimal(rate),
                      "implied_cancellations_seen_so_far": None if rate is None else rnd(F(rate) * p["eligible"], 0),
                      "window_still_open_at_as_of": pa + timedelta(days=104) > C.as_of})
    s = lambda k: sum(c["population"][k] for c in agg)
    first = min((ts(c["prediction_at"]) for c in agg if c["population"]["censored"] > 0), default=None)
    summ = [{"eligible_rows": s("eligible"), "mature_rows": s("mature"), "censored_rows": s("censored"), "mature_churned_rows": s("churned"), "censored_share": ratio(s("censored"), s("eligible")),
             "mature_churn_rate": ratio(s("churned"), s("mature")), "cutoffs_with_censored_rows": sum(1 for c in agg if c["population"]["censored"] > 0), "first_censored_cutoff": first}]
    by: dict[datetime, list] = {}
    for c in C.cutoff.values():
        by.setdefault(c["pa"], []).append(c)
    coh = []
    cancels: dict[int, list] = {}
    for e in C.ev["subscription_events"]:
        if e["event_type"] == "cancel":
            cancels.setdefault(e["account_id"], []).append(e)
    for pa in sorted(by):
        rows = by[pa]
        el = [c for c in rows if c["cutoff_id"] in C.features]
        lab = {c["cutoff_id"]: C.label.get(c["cutoff_id"]) for c in rows}
        mature = [c for c in el if lab[c["cutoff_id"]] and lab[c["cutoff_id"]]["mature"]]
        cens = [c for c in el if lab[c["cutoff_id"]] and not lab[c["cutoff_id"]]["mature"]]
        seen = sum(1 for c in cens if any(c["pa"] <= e["t"] < c["hz"] for e in cancels.get(c["account_id"], [])))
        coh.append({"prediction_at": pa, "cohort_cutoff_rows": len(rows), "eligible": len(el), "mature": len(mature), "censored": len(cens),
                    "churned": sum(1 for c in el if lab[c["cutoff_id"]] and lab[c["cutoff_id"]]["churned"]),
                    "mature_without_outcome": sum(1 for c in rows if lab[c["cutoff_id"]] and lab[c["cutoff_id"]]["churned"] is None and lab[c["cutoff_id"]]["mature"]),
                    "censored_but_labelled": sum(1 for c in cens if lab[c["cutoff_id"]]["churned"] is not None), "censored_share": ratio(len(cens), len(el)),
                    "cancellations_seen_so_far_in_censored_rows": seen, "rate_if_censored_were_non_churn": ratio(seen, len(cens))})
    lab_rows = [(C.cutoff[cid], l) for cid, l in C.label.items()]
    rule = [{"labelled_rows": len(lab_rows), "stored_flag_equals_rule": sum(1 for c, l in lab_rows if l["mature"] == (c["label_end"] <= C.as_of)),
             "stored_label_end_equals_rule": sum(1 for c, l in lab_rows if ts(l["label_end"]) == c["label_end"])}]
    rej = [{"reason_code": "CENSORED_LABEL", "rejected_labels": len(C.rejected_labels),
            "false_and_immature": sum(1 for l in C.rejected_labels if l["churned"] is False and l["mature"] is False)}]
    return {"04_censored_tail__world_by_cutoff": world, "04_censored_tail__world_summary": summ, "04_censored_tail__cohort_by_cutoff": coh,
            "04_censored_tail__cohort_maturity_rule": rule, "04_censored_tail__rejected_false_labels": rej}


# ---- 05 ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def features_of(C: Cohort, c: dict, strict: bool) -> dict:
    ok = (lambda e: e["av"] < c["pa"]) if strict else (lambda e: True)
    acc = c["account_id"]
    us = [e for e in C.by_account["usage_events"].get(acc, []) if c["obs"] <= e["t"] < c["pa"] and ok(e)]
    hs = [e for e in C.by_account["support_events"].get(acc, []) if e["severity"] == "high" and c["obs"] <= e["t"] < c["pa"] and ok(e)]
    bs = [e for e in C.by_account["billing_events"].get(acc, []) if c["obs"] <= e["t"] < c["pa"] and ok(e)]
    return {"usage": sum(1 for e in us if e["t"] >= c["pa"] - timedelta(days=30)),
            "days": None if not us else int((c["pa"] - max(e["t"] for e in us)).total_seconds() // 86400), "high": len(hs),
            "billing": None if not bs else sum((Decimal(e["amount"]) for e in bs), Decimal(0))}


def r05(C: Cohort) -> dict:
    claims = C.manifest["designed_relationships"][3]["realised"]
    src = []
    for k in ("usage_events", "billing_events", "support_events", "subscription_events"):
        rows = C.ev[k]
        late = sum(1 for e in rows if e["av"] - e["t"] >= timedelta(days=1))
        src.append({"source": k, "cohort_events": len(rows), "late_one_day_or_more": late, "cohort_share": ratio(late, len(rows)),
                    "published_full_world_share": Decimal(claims["realised"][k]["share"])})
    stat = {"all": [0] * 9, "test": [0] * 9}
    for cid, fr in C.features.items():
        c = C.cutoff[cid]
        s, i = features_of(C, c, True), features_of(C, c, False)
        st = fr["features_json"]
        same = (st["usage_events_30d"] == s["usage"] and st["days_since_last_usage"] == s["days"] and st["high_severity_support_90d"] == s["high"]
                and ((st["billing_total_90d"] is None and s["billing"] is None) or (st["billing_total_90d"] is not None and s["billing"] is not None and Decimal(st["billing_total_90d"]) == s["billing"])))
        late = any(e for k in ("usage_events", "billing_events", "support_events") for e in C.by_account[k].get(c["account_id"], []) if c["obs"] <= e["t"] < c["pa"] and e["av"] >= c["pa"])
        flips = (s["usage"] != i["usage"], s["days"] != i["days"], s["high"] != i["high"], s["billing"] != i["billing"])
        vals = [1, same, late, any(flips), *flips]
        for scope in ("all", "test") if C.range_of(c["pa"]) == "test" else ("all",):
            for n, v in enumerate(vals):
                stat[scope][n] += int(v)
    fr_rows = []
    for scope, label in (("all", "all 765 eligible cohort rows"), ("test", "test-range cohort rows")):
        v = stat[scope]
        fr_rows.append({"scope": label, "feature_rows": v[0], "stored_equals_point_in_time_recomputation": v[1], "rows_with_a_late_event": v[2], "rows_changed_if_arrival_ignored": v[3],
                        "usage_events_30d_changed": v[4], "days_since_last_usage_changed": v[5], "high_severity_support_90d_changed": v[6], "billing_total_90d_changed": v[7], "share_changed": ratio(v[3], v[0])})
    pub = [{"claim": "test_rows", "value": str(claims["test_rows"])}, {"claim": "test_rows_with_a_late_event", "value": str(claims["test_rows_with_a_late_event"])},
           {"claim": "test_rows_features_change_if_ignored", "value": str(claims["test_rows_features_change_if_ignored"])},
           {"claim": "share_of_test_rows_changed", "value": claims["share_of_test_rows_changed"]}]
    byr: dict[str, list[int]] = {}
    for cid in C.features:
        c = C.cutoff[cid]
        late = any(e for k in ("usage_events", "billing_events", "support_events") for e in C.by_account[k].get(c["account_id"], []) if c["obs"] <= e["t"] < c["pa"] and e["av"] >= c["pa"])
        x = byr.setdefault(C.range_of(c["pa"]), [0, 0])
        x[0] += 1
        x[1] += int(late)
    rng = [{"split_range": k, "cohort_feature_rows": byr[k][0], "rows_with_a_late_event": byr[k][1]} for k in ("train", "validation", "test", "outside")]
    return {"05_arrived_late__late_events_by_source": src, "05_arrived_late__feature_recomputation": fr_rows, "05_arrived_late__published_full_world": pub, "05_arrived_late__arrived_late_counted_by_range": rng}


# ---- 06 ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def r06(C: Cohort) -> dict:
    split = [r for r in C.split]
    stored = []
    for k in ("train", "validation", "test", "outside"):
        rows = [r for r in split if r["split"] == k]
        stored.append({"split_range": k, "cutoff_rows": len(rows), "retained": sum(r["status"] == "retained" for r in rows), "label_window": sum(r["drop_reason"] == "LABEL_WINDOW" for r in rows),
                       "group_test": sum(r["drop_reason"] == "GROUP_TEST" for r in rows), "group_validation": sum(r["drop_reason"] == "GROUP_VALIDATION" for r in rows)})
    rng = {cid: C.range_of(c["pa"]) for cid, c in C.cutoff.items()}
    has = {(c["account_id"], rng[cid]) for cid, c in C.cutoff.items()}
    reason: dict[str, str | None] = {}
    for cid, c in C.cutoff.items():
        r = rng[cid]
        if (r == "train" and c["label_end"] > C.train_end) or (r == "validation" and c["label_end"] > C.validation_end):
            reason[cid] = "LABEL_WINDOW"
        elif r in ("train", "validation") and (c["account_id"], "test") in has:
            reason[cid] = "GROUP_TEST"
        elif r == "train" and (c["account_id"], "validation") in has:
            reason[cid] = "GROUP_VALIDATION"
        else:
            reason[cid] = None
    sa = {r["cutoff_id"]: r for r in split}
    rec = []
    for k in ("train", "validation", "test", "outside"):
        ids = [cid for cid in C.cutoff if rng[cid] == k]
        rec.append({"split_range": k, "cutoff_rows": len(ids), "retained": sum(reason[i] is None for i in ids), "label_window": sum(reason[i] == "LABEL_WINDOW" for i in ids),
                    "group_test": sum(reason[i] == "GROUP_TEST" for i in ids), "group_validation": sum(reason[i] == "GROUP_VALIDATION" for i in ids),
                    "rows_that_differ_from_the_stored_assignment": sum(1 for i in ids if (reason[i] is None) != (sa[i]["status"] == "retained") or reason[i] != sa[i]["drop_reason"])})
    both = {}
    for r in split:
        if r["status"] == "retained" and r["split"] in ("train", "validation", "test"):
            both.setdefault(C.cutoff[r["cutoff_id"]]["account_id"], set()).add(r["split"])
    two = [{"accounts_retained_in_two_ranges": sum(1 for v in both.values() if len(v) > 1)}]
    cross = []
    for k, bound in (("train", C.train_end), ("validation", C.validation_end)):
        ids = [r["cutoff_id"] for r in split if r["split"] == k and r["status"] == "retained"]
        cross.append({"split_range": k, "retained_rows": len(ids), "retained_rows_crossing_the_boundary": sum(1 for i in ids if C.cutoff[i]["label_end"] > bound)})
    pop = jload("split_summary")["population"]
    world = []
    for k in ("train", "validation", "test", "outside"):
        p = pop[k]
        world.append({"split_range": k, "cutoff_rows": p["total"], "retained": p["retained"], "label_window": p["label_window"], "group_test": p["group_test"],
                      "group_validation": p["group_validation"], "dropped": p["total"] - p["retained"],
                      "counts_add_up": p["retained"] + p["label_window"] + p["group_test"] + p["group_validation"] == p["total"]})
    tot = [{"train_label_window": pop["train"]["label_window"], "train_group_test": pop["train"]["group_test"], "train_group_validation": pop["train"]["group_validation"],
            "validation_label_window": pop["validation"]["label_window"], "validation_group_test": pop["validation"]["group_test"],
            "train_dropped_because_the_account_sits_on_the_other_side": pop["train"]["group_test"] + pop["train"]["group_validation"],
            "dropped_in_all_ranges": sum(p["label_window"] + p["group_test"] + p["group_validation"] for p in pop.values()), "embargo_days": 104}]
    return {"06_purge_counts__cohort_stored": stored, "06_purge_counts__cohort_recomputed": rec, "06_purge_counts__cohort_no_account_on_both_sides": two,
            "06_purge_counts__cohort_label_windows_inside_the_range": cross, "06_purge_counts__world_published": world, "06_purge_counts__world_totals": tot}


# ---- 07 ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def r07(T: Test) -> dict:
    groups = [("all_accounts", lambda r: True), ("other_regions", lambda r: r["region"] != "apac")] + [(g, (lambda g: lambda r: r["region"] == g)(g)) for g in sorted({r["region"] for r in T.rows})]
    out = []
    for name, pick in groups:
        ref = [0, 0, 0]
        for r in T.rows:
            if r["cutoff_index"] == 0 and pick(r):
                ref[usage_bin(r["usage_events_30d"])] += 1
        for ci, pa in enumerate(T.cutoffs):
            cur = [0, 0, 0]
            for r in T.rows:
                if r["cutoff_index"] == ci and pick(r):
                    cur[usage_bin(r["usage_events_30d"])] += 1
            v, fl, ex = psi6(ref, cur)
            out.append({"grp": name, "prediction_at": pa, "reference_rows": sum(ref), "current_rows": sum(cur), "psi": v, "floored_bins": fl, "exceeds_threshold": ex})
    drift = jload("cutoff_aggregates")["drift"]["by_cutoff"]
    series = []
    for d in drift:
        pa = ts(d["prediction_at"])
        a = d["apac"]
        series.append({"prediction_at": pa, "psi": Decimal(a["psi"]), "current_rows": a["current_rows"], "reference_rows": a["reference_rows"], "floored_bins": a["floored_bins"],
                       "exceeds_threshold": a["exceeds_threshold"], "comparison_before_the_change": pa < ts("2026-03-31T00:00:00Z") and pa != ts("2026-02-01T00:00:00Z"),
                       "exceeds_with_a_floored_bin": a["exceeds_threshold"] and a["floored_bins"] > 0, "all_accounts_psi": Decimal(d["all_accounts"]["psi"]),
                       "other_regions_psi": Decimal(d["other_regions"]["psi"])})
    ref_t, chg, may = ts("2026-02-01T00:00:00Z"), ts("2026-03-31T00:00:00Z"), ts("2026-05-01T00:00:00Z")
    ap = [(ts(d["prediction_at"]), d["apac"]) for d in drift]
    before_ref = [(p, a) for p, a in ap if p < ref_t]
    pre = [(p, a) for p, a in ap if p < chg and p != ref_t]
    post = [(p, a) for p, a in ap if p >= ts("2026-04-01T00:00:00Z") and a["exceeds_threshold"]]
    allp = [Decimal(d["all_accounts"]["psi"]) for d in drift]
    summ = [{"cutoffs_before_the_reference": len(before_ref), "exceedances_before_the_reference": sum(a["exceeds_threshold"] for _, a in before_ref),
             "comparison_cutoffs_before_the_change": len(pre), "exceedances_before_the_change": sum(a["exceeds_threshold"] for _, a in pre),
             "exceedances_before_the_change_with_a_floored_bin": sum(a["exceeds_threshold"] and a["floored_bins"] > 0 for _, a in pre),
             "exceedances_before_the_change_without_a_floored_bin": sum(a["exceeds_threshold"] and a["floored_bins"] == 0 for _, a in pre),
             "max_psi_before_the_change": max(Decimal(a["psi"]) for _, a in pre), "exceedances_from_the_change": len(post), "first_exceedance_from_the_change": min(p for p, _ in post),
             "shift_min_psi": min(Decimal(a["psi"]) for p, a in ap if p >= may), "shift_max_psi": max(Decimal(a["psi"]) for p, a in ap if p >= may), "all_accounts_max_psi": max(allp),
             "all_accounts_psi_2026_05": next(Decimal(d["all_accounts"]["psi"]) for d in drift if d["prediction_at"] == "2026-05-01T00:00:00Z"),
             "all_accounts_psi_latest": Decimal(drift[-1]["all_accounts"]["psi"]), "other_regions_max_psi": max(Decimal(d["other_regions"]["psi"]) for d in drift)}]
    return {"07_drift_by_region__psi_test_range": out, "07_drift_by_region__published_series_apac": series, "07_drift_by_region__published_summary": summ}


# ---- 08 and 10 -------------------------------------------------------------------------------------------------------------------------------------------------------------------
def r08(T: Test) -> dict:
    n = len(T.rows)
    per: dict[int, list[int]] = {}
    for r in T.rows:
        x = per.setdefault(r["account_id"], [0, 0])
        x[0] += 1
        x[1] += r["churned"]
    pos = sum(r["churned"] for r in T.rows)
    pop = [{"test_rows": n, "distinct_accounts": len(per), "churning_rows": pos, "churning_accounts": sum(1 for v in per.values() if v[1] > 0), "accounts_with_1_row": sum(1 for v in per.values() if v[0] == 1),
            "accounts_with_2_rows": sum(1 for v in per.values() if v[0] == 2), "accounts_with_3_rows": sum(1 for v in per.values() if v[0] == 3), "accounts_with_4_rows": sum(1 for v in per.values() if v[0] == 4),
            "accounts_churning_in_more_than_one_row": sum(1 for v in per.values() if v[1] > 1), "prevalence_of_rows": ratio(pos, n),
            "share_of_accounts_with_a_churning_row": ratio(sum(1 for v in per.values() if v[1] > 0), len(per))}]
    m = {k: (avg_precision(T.items(c)), brier(T.items(c))) for k, c in (("random_baseline", "p_random_baseline"), ("business_rule", "p_business_rule"), ("logistic_regression", "p_logistic_calibrated"),
                                                                       ("prevalence_baseline", "p_prevalence_baseline"))}
    ra = lambda k: F(rnd(m[k][0], 6))                 # the SQL rounds each model's figure to 6 places before it takes the margin
    rb = lambda k: F(rnd(m[k][1], 6))
    L = "logistic_regression"
    rows = [("ap_over_rule", Decimal("0.030000"), "business_rule", ra(L) - ra("business_rule"), "met, by construction (D-G02)"),
            ("ap_over_random", Decimal("0.050000"), "random_baseline", ra(L) - ra("random_baseline"), "met, by construction (D-G02)"),
            ("brier_under_rule", Decimal("0.002000"), "business_rule", rb("business_rule") - rb(L), "met, by construction (D-G02)"),
            ("brier_under_random", Decimal("0.050000"), "random_baseline", rb("random_baseline") - rb(L), "met, by construction (D-G02); uninformative: a uniform random score cannot beat about 0.33"),
            ("ap_over_prevalence_constant (reference)", None, "prevalence_baseline", ra(L) - ra("prevalence_baseline"), "reference, not a target"),
            ("brier_under_prevalence_constant (reference)", None, "prevalence_baseline", rb("prevalence_baseline") - rb(L), "reference, not a target")]
    margins = [{"margin": a, "declared_before_the_first_run": b, "against": c, "realised_margin": rnd(d, 6), "status": e} for a, b, c, d, e in rows]
    unin = [{"random_baseline_brier": rnd(brier(T.items("p_random_baseline")), 6), "prevalence_constant_brier": rnd(brier(T.items("p_prevalence_baseline")), 6),
             "random_baseline_mean_probability": rnd(sum((r["p_random_baseline"] for r in T.rows), F(0)) / n, 6), "prevalence": ratio(pos, n)}]
    return {"08_rows_and_margins__rows_and_accounts": pop, "08_rows_and_margins__margins": margins, "08_rows_and_margins__random_brier_is_uninformative": unin}


def gap(rows: list[dict], col: str) -> F:
    n = len(rows)
    return (sum((r[col] for r in rows), F(0)) / n - F(sum(r["churned"] for r in rows), n)) * 100


def r10(T: Test) -> dict:
    def block(dim: str, key: str, values: list[str]) -> list[dict]:
        out = []
        for v in values:
            rows = [r for r in T.rows if r[key] == v]
            n, pos = len(rows), sum(r["churned"] for r in rows)
            out.append({"dimension": dim, "grp": v, "test_rows": n, "churning_rows": pos, "mean_predicted": rnd(sum((r["p_logistic_calibrated"] for r in rows), F(0)) / n, 6),
                        "observed_rate": ratio(pos, n), "gap_pp": rnd(gap(rows, "p_logistic_calibrated"), 2), "gap_pp_before_platt": rnd(gap(rows, "p_logistic_uncalibrated"), 2)})
        return out
    seg = block("segment", "segment", sorted({r["segment"] for r in T.rows}))
    reg = block("region", "region", sorted({r["region"] for r in T.rows}))
    allg = [("overall", "all test rows", len(T.rows), gap(T.rows, "p_logistic_calibrated"))]
    for dim, rows in (("segment", seg), ("region", reg)):
        g = {}
        for r in rows:
            sel = [x for x in T.rows if x["segment" if dim == "segment" else "region"] == r["grp"]]
            g[r["grp"]] = (len(sel), gap(sel, "p_logistic_calibrated"))
        k = min(g, key=lambda x: (g[x][1], x))
        allg.append((dim, k, g[k][0], g[k][1]))
    largest = [{"dimension": d, "most_negative_gap_group": k, "test_rows": n, "gap_pp": rnd(v, 2)} for d, k, n, v in allg]
    starter = []
    for pa in T.cutoffs:
        rows = [r for r in T.rows if r["segment"] == "starter" and r["pa"] == pa]
        n, pos = len(rows), sum(r["churned"] for r in rows)
        starter.append({"prediction_at": pa, "starter_rows": n, "churning_rows": pos, "mean_predicted": rnd(sum((r["p_logistic_calibrated"] for r in rows), F(0)) / n, 6),
                        "observed_rate": ratio(pos, n), "gap_pp": rnd(gap(rows, "p_logistic_calibrated"), 2)})
    return {"10_segment_region_calibration__by_segment": seg, "10_segment_region_calibration__by_region": reg, "10_segment_region_calibration__largest_gaps": largest,
            "10_segment_region_calibration__starter_after_the_repricing": starter}


def results() -> dict[str, list[dict]]:
    """Every result set of investigations 01..08 and 10, recomputed from the raw published files."""
    T, C = Test(), Cohort()
    out: dict[str, list[dict]] = {}
    for part in (r01(T), r02(T, C), r03(T, C), r04(C), r05(C), r06(C), r07(T), r08(T), r10(T)):
        out.update(part)
    return out


# ---- 09: the golden fixture ----------------------------------------------------------------------------------------------------------------------------------------------------
def golden_results() -> dict[str, list[dict]]:
    g = json.loads(GOLDEN.read_text())
    as_of = ts(g["as_of"])
    created = {a["account_id"]: ts(a["created_at"]) for a in g["accounts"]}
    subs = [{**e, "t": ts(e["event_at"]), "av": ts(e["available_at"])} for e in g["subscription_events"]]
    cutoffs = {c["cutoff_id"]: {**c, "pa": ts(c["prediction_at"]), "obs": ts(c["observation_start"]), "hz": ts(c["horizon_end"])} for c in g["prediction_cutoffs"]}
    pred = {p["cutoff_id"]: Decimal(p["probability"]) for p in g["predictions"]}
    jan, feb, ref = ts("2026-01-01T00:00:00Z"), ts("2026-02-01T00:00:00Z"), ts("2025-03-01T00:00:00Z")

    def eligible(c: dict) -> bool:
        vis = [e for e in subs if e["account_id"] == c["account_id"] and e["t"] < c["pa"] and e["av"] < c["pa"]]
        if not vis or created[c["account_id"]] >= c["obs"]:
            return False
        return max(vis, key=lambda e: (e["t"], e["subscription_event_id"]))["event_type"] in ("start", "renew")

    def churned(c: dict) -> bool:
        le = c["hz"] + timedelta(days=14)
        return any(e["account_id"] == c["account_id"] and e["event_type"] == "cancel" and c["pa"] <= e["t"] < c["hz"] and e["av"] < le for e in subs)

    jc = [c for c in cutoffs.values() if c["pa"] == jan]
    el = sorted([c for c in jc if eligible(c)], key=lambda c: (-pred[c["cutoff_id"]], c["account_id"]))
    rk = [(c["account_id"], pred[c["cutoff_id"]], int(churned(c))) for c in el]
    ranking = [{"rank": i, "account_id": a, "risk": p, "outcome": y, "squared_error": rnd(F((p - y) ** 2), 6)} for i, (a, p, y) in enumerate(rk, 1)]
    sc = g["intervention_scenarios"][0]
    k, cost, eff, mar = sc["capacity"], Decimal(sc["contact_cost"]), Decimal(sc["assumed_effect"]), Decimal(sc["margin_value"])
    n, pos = len(rk), sum(y for _, _, y in rk)
    tpk = sum(y for _, _, y in rk[:k])
    items = [(F(p), y) for _, p, y in rk]
    ev = sum((p * eff * mar - cost for _, p, _ in rk[:k]), Decimal(0))
    known = [{"cutoff_rows": len(jc), "eligible_rows": n, "ineligible_created_on_or_after_observation_start": sum(1 for c in jc if created[c["account_id"]] >= c["obs"]),
              "ineligible_not_active": sum(1 for c in jc if created[c["account_id"]] < c["obs"] and not eligible(c)), "mature_eligible": n, "churned": pos, "churn_rate": ratio(pos, n), "capacity": k,
              "precision_at_k": ratio(tpk, k), "recall_at_k": ratio(tpk, pos), "risk_lift_at_k": rnd(F(tpk, k) / F(pos, n), 6), "brier_score": rnd(brier(items), 6),
              "average_precision": rnd(avg_precision(items), 6), "contact_budget": rnd(F(cost * k), 2), "expected_intervention_value": rnd(F(ev), 2), "label": "hypothetical"}]
    terms, tp, nn = [], 0, 0
    for level in sorted({p for p, _ in items}, reverse=True):
        grp = [y for p, y in items if p == level]
        tp, nn = tp + sum(grp), nn + len(grp)
        terms.append({"threshold": rnd(level, 6), "true_positives": tp, "false_positives": nn - tp, "precision": ratio(tp, nn), "recall": ratio(tp, pos), "delta_recall": ratio(sum(grp), pos),
                      "term": rnd(F(sum(grp), pos) * F(tp, nn), 6)})
    feats = {f["cutoff_id"] for f in g["feature_rows"]}

    def late(src: str, pick) -> int:
        n_ = 0
        for c in jc:
            if c["cutoff_id"] in feats:
                n_ += sum(1 for e in g[src] if e["account_id"] == c["account_id"] and pick(c, ts(e["event_at"])) and ts(e["available_at"]) >= c["pa"])
        return n_
    win = lambda c, t: c["obs"] <= t < c["pa"]
    arrived = [{"source": "usage_events", "arrived_late": late("usage_events", win)}, {"source": "support_events", "arrived_late": late("support_events", win)},
               {"source": "billing_events", "arrived_late": late("billing_events", win)}, {"source": "subscription_events", "arrived_late": late("subscription_events", lambda c, t: t < c["pa"])}]
    fc = [c for c in cutoffs.values() if c["pa"] == feb and c["cutoff_id"] in feats]
    labs = {l["cutoff_id"]: l for l in g["labels"]}
    mat = sum(1 for c in fc if labs[c["cutoff_id"]]["mature"])
    cens = [{"prediction_at": feb, "eligible_rows": len(fc), "mature_rows": mat, "censored_rows": len(fc) - mat, "rows_with_an_outcome": sum(1 for c in fc if labs[c["cutoff_id"]]["churned"] is not None),
             "churn_rate": ratio(sum(1 for c in fc if labs[c["cutoff_id"]]["churned"]), mat)}]
    purge = []
    for key in ("train", "validation", "test"):
        rows = [r for r in g["split_assignments"] if r["split"] == key]
        purge.append({"split_range": key, "cutoff_rows": len(rows), "retained": sum(r["status"] == "retained" for r in rows), "label_window": sum(r["drop_reason"] == "LABEL_WINDOW" for r in rows),
                      "group_test": sum(r["drop_reason"] == "GROUP_TEST" for r in rows), "group_validation": sum(r["drop_reason"] == "GROUP_VALIDATION" for r in rows)})
    bins = []
    for i in range(10):
        b = [(p, y) for _, p, y in rk if min(int(p * 10 // 1), 9) == i]
        m = None if not b else sum((F(p) for p, _ in b), F(0)) / len(b)
        o = None if not b else F(sum(y for _, y in b), len(b))
        bins.append({"bin_index": i, "rows_in_bin": len(b), "empty_bin": not b, "mean_predicted": None if not b else rnd(m, 6), "observed_rate": None if not b else rnd(o, 6),
                     "gap_pp": None if not b else rnd((m - o) * 100, 2)})
    feat_rows = {f["cutoff_id"]: f["features_json"]["usage_events_30d"] for f in g["feature_rows"]}

    def counts(pa: datetime) -> list[int]:
        out = [0, 0, 0]
        for cid, u in feat_rows.items():
            if cutoffs[cid]["pa"] == pa:
                out[usage_bin(u)] += 1
        return out
    drift = []
    for pa in (jan, feb):
        v, fl, ex = psi6(counts(ref), counts(pa))
        drift.append({"prediction_at": pa, "reference_rows": sum(counts(ref)), "current_rows": sum(counts(pa)), "psi": v, "floored_bins": fl, "exceeds_threshold": ex})
    return {"09_golden_known_answer__ranking": ranking, "09_golden_known_answer__known_answer": known, "09_golden_known_answer__average_precision_terms": terms,
            "09_golden_known_answer__arrived_late": arrived, "09_golden_known_answer__censored_cohort": cens, "09_golden_known_answer__purge_counts": purge,
            "09_golden_known_answer__calibration_bins": bins, "09_golden_known_answer__psi_against_the_march_2025_cohort": drift}
