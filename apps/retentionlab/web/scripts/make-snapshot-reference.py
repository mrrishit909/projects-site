"""Writes scripts/snapshot-reference.json: what the PYTHON domain (domain/retentionlab) computes over the published snapshot in
web/public/data, so CI can compare the TypeScript mirror without Python. Run from apps/retentionlab/web:

    ../../../.venv/bin/python -I scripts/make-snapshot-reference.py

Contents (every digest is the SHA-256 of canonical JSON, sorted keys, compact):
  cohort       the 200-account cohort evaluated by the domain's own `evaluate`, once per model (random, rule, logistic), over all 21 cutoff sets
               with a drift reference (2026-02-01, usage_events_30d): a digest and a compact summary of each set's complete metric block, the
               ingest counts, the rejected records, the consistency block, the split counts, the publications, the freshness; and the three
               scenarios of the 2026-09-01 queue (economics digest, expected value, contact budget, queue).
  test_table   the 1,513-row test table of the full world, ranked and evaluated through the domain's metric functions (average_precision,
               calibration_bins, economics, psi), for the union and each of the four test cutoffs, under each of the four probability columns:
               AP, Brier, the ten reliability bins, precision / recall / lift at a list of K (with the tie flag), the expected value at the three
               scenario assumptions, the gap by segment and by region (percentage points), and the usage_events_30d PSI by region against the
               first test cutoff.
  designed     every figure of the manifest's designed relationships (DR-01..DR-05) flattened to leaves, and the subset the published files let
               anyone recompute, as the domain recomputes it. The script asserts that each recomputed figure equals the manifest's and the
               published calibration.json / cutoff_aggregates.json; it stops when one does not.
"""
import hashlib
import json
import sys
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "domain"))
from retentionlab.contract import DEFAULT_DRIFT_BINS, MODELS  # noqa: E402
from retentionlab.ingest import validate  # noqa: E402
from retentionlab.metrics import average_precision, calibration_bins, economics, in_bin, psi, rank_key, set_metrics  # noqa: E402
from retentionlab.numbers import config_hash, p6, pp2, ratio  # noqa: E402
from retentionlab.pipeline import evaluate  # noqa: E402
from retentionlab.world import World  # noqa: E402
from decimal import ROUND_HALF_UP, Decimal  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
load = lambda n: json.loads((DATA / f"{n}.json").read_text())  # noqa: E731
manifest = load("manifest")
cfg = manifest["config"]
RUN = cfg["training_run_id"]


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(v):
    return hashlib.sha256(canon(v).encode()).hexdigest()


def need(label, got, want):
    if got != want:
        raise SystemExit(f"MISMATCH {label}: python recomputed {got!r}, published {want!r}")


# ------------------------------------------------------------------------------------------------------------------------------ cohort
ENT = ["accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels", "training_runs",
       "predictions", "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments", "scoring_publications"]
base = {"contract_version": 1, "as_of": manifest["as_of"], "label_version": cfg["label_version"], "feature_version_spec": cfg["feature_version_spec"]}
for e in ENT:
    base[e] = load(e)["rows"]
ats = sorted({c["prediction_at"] for c in base["prediction_cutoffs"]})
DRIFT = {"feature": "usage_events_30d", "reference_prediction_at": "2026-02-01T00:00:00Z", "bins": list(DEFAULT_DRIFT_BINS), "floor": "0.000100", "threshold": "0.200000"}
cohort = {}
for m in MODELS:
    d = {**base, "predictions": [p for p in base["predictions"] if p["model_name"] == m], "scoring_publications": [p for p in base["scoring_publications"] if p["model_name"] == m],
         "scope": {"training_run_id": RUN, "sets": [{"prediction_at": a, "scenario_id": None} for a in ats], "drift": DRIFT}}
    ev = evaluate(d)
    sets = {}
    for a, s in ev["cutoff_sets"].items():
        pd = s["population_drift"]
        sets[a] = {"digest": digest(s), "population": s["population"], "churn_rate": s["churn_rate"]["value"], "average_precision": s["average_precision"]["value"],
                   "brier_score": s["brier_score"]["value"], "prevalence": s["average_precision"]["prevalence"], "positives": s["average_precision"]["positives"],
                   "late_total": s["late_events"]["total"], "missingness_overall": s["feature_missingness"]["overall"]["value"],
                   "psi": pd["psi"], "psi_exceeds": pd["exceeds_threshold"]}
    claims = manifest["published_cohort"]["claims"][m]
    need(f"{m} consistency", ev["consistency"], claims["consistency"])
    need(f"{m} freshness", ev["freshness"], claims["freshness"])
    for a, s in sets.items():                      # the manifest's compact claims are the same domain run
        c = claims["cutoff_sets"][a]
        need(f"{m} {a} AP", s["average_precision"], c["average_precision"])
        need(f"{m} {a} Brier", s["brier_score"], c["brier_score"])
        need(f"{m} {a} churn", s["churn_rate"], c["churn_rate"])
    cohort[m] = {"ingest": ev["ingest"]["counts"], "rejected_records": ev["ingest"]["rejected_records"], "consistency": ev["consistency"], "split_counts": ev["split"][RUN]["counts"],
                 "freshness": ev["freshness"], "publications": digest(ev["scoring_publications"]), "publication_status": {p["prediction_at"]: [p["eligible"], p["scored"], p["status"]] for p in ev["scoring_publications"]},
                 "point_in_time_digest": digest(ev["point_in_time"]), "sets": sets}
world_l = World(base | {"predictions": [p for p in base["predictions"] if p["model_name"] == "logistic_regression"]},
                validate(base | {"predictions": [p for p in base["predictions"] if p["model_name"] == "logistic_regression"]}).accepted)
queue_at = manifest["published_cohort"]["queue_prediction_at"]
scen = {}
for s in base["intervention_scenarios"]:
    sm = set_metrics(world_l, RUN, queue_at, s["scenario_id"], None)
    e = sm["economics"]
    scen[s["scenario_id"]] = {"digest": digest(sm["economics"]), "capacity": s["capacity"], "population": sm["outreach_queue"]["population"], "contact_budget": e["contact_budget"],
                              "expected_value": e["expected_value"], "queue": sm["outreach_queue"]["account_ids"]}
    claim = manifest["published_cohort"]["economics"][s["scenario_id"]]
    need(f"{s['scenario_id']} expected value", e["expected_value"], claim["expected_value"])
    need(f"{s['scenario_id']} budget", e["contact_budget"], claim["contact_budget"])
    need(f"{s['scenario_id']} queue", sm["outreach_queue"]["account_ids"], manifest["published_cohort"]["queue_account_ids"][s["scenario_id"]])
cohort["scenarios"] = scen

# ------------------------------------------------------------------------------------------------------------------------------ test table
tc = load("test_cohort")
COLS = tc["head"]["columns"]
rows = [dict(zip(COLS, r)) for r in tc["rows"]]
CUTS = tc["head"]["cutoffs"]
PCOL = {"random_baseline": "p_random_baseline", "business_rule": "p_business_rule", "logistic_uncalibrated": "p_logistic_uncalibrated", "logistic_calibrated": "p_logistic_calibrated"}
KS = [1, 2, 5, 10, 20, 50, 100, 189, 500, 1513]
SCEN = {s["scenario_id"]: s for s in base["intervention_scenarios"]}


def items_of(sub, col):
    its = [{"p": F(r[col]), "pstr": r[col], "y": bool(r["churned"]), "account_id": r["account_id"], "cut": r["cutoff_index"]} for r in sub]
    return sorted(its, key=lambda it: (rank_key(it), it["cut"]))


def block(sub, col):
    its = items_of(sub, col)
    n, pos = len(its), sum(1 for i in its if i["y"])
    ap, _ = average_precision(its, pos)
    sq = [(i["p"] - (1 if i["y"] else 0)) ** 2 for i in its]
    ks = {}
    for k in KS:
        if k > n:
            ks[str(k)] = "CAPACITY_EXCEEDS_POPULATION"
            continue
        hits = sum(1 for i in its[:k] if i["y"])
        top = F(hits, k)
        ks[str(k)] = {"hits": hits, "precision": p6(top), "recall": p6(ratio(hits, pos)), "lift": p6(None if not pos else top / ratio(pos, n)),
                      "tie_split": k < n and its[k - 1]["p"] == its[k]["p"]}
    eco = {}
    for sid, sc in SCEN.items():
        q = [{"pstr": i["pstr"], "account_id": i["account_id"]} for i in its[:min(sc["capacity"], n)]]
        e = economics(sc, q)
        eco[sid] = {"k": len(q), "contact_budget": e["contact_budget"], "expected_value": e["expected_value"]}
    return {"n": n, "positives": pos, "average_precision": p6(ap), "prevalence": p6(ratio(pos, n)), "brier_score": p6(sum(sq, F(0)) / n), "bins": calibration_bins(its),
            "bins_digest": digest(calibration_bins(its)), "k": ks, "economics": eco}


pops = {"test": rows} | {f"test-{i}": [r for r in rows if r["cutoff_index"] == i] for i in range(len(CUTS))}
test_table = {pid: {m: block(sub, col) for m, col in PCOL.items()} for pid, sub in pops.items()}


def gap(sub):
    n, pos = len(sub), sum(r["churned"] for r in sub)
    mean = sum((F(r["p_logistic_calibrated"]) for r in sub), F(0)) / n
    obs = F(pos, n)
    return {"gap_pp": pp2(mean - obs), "mean_predicted": p6(mean), "n": n, "observed_rate": p6(obs), "positives": pos}


gaps = {"overall": gap(rows), "by_segment": {s: gap([r for r in rows if r["segment"] == s]) for s in sorted({r["segment"] for r in rows})},
        "by_region": {s: gap([r for r in rows if r["region"] == s]) for s in sorted({r["region"] for r in rows})}}
cal = load("calibration")
need("gap overall", gaps["overall"], cal["overall"])
need("gap by segment", gaps["by_segment"], cal["by_segment"])
need("gap by region", gaps["by_region"], cal["by_region"])
need("reliability (calibrated)", test_table["test"]["logistic_calibrated"]["bins"], cal["reliability_calibrated"])
need("reliability (uncalibrated)", test_table["test"]["logistic_uncalibrated"]["bins"], cal["reliability_uncalibrated"])

BINS = list(DEFAULT_DRIFT_BINS)


def psi_for(sub_ref, sub_cur):
    ref = [sum(1 for r in sub_ref if in_bin(r["usage_events_30d"], b)) for b in BINS]
    cur = [sum(1 for r in sub_cur if in_bin(r["usage_events_30d"], b)) for b in BINS]
    res = psi(ref, cur, [b["label"] for b in BINS], "0.000100")
    return {"psi": str(res[0].quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)), "exceeds": res[0] > Decimal("0.200000"), "reference_rows": sum(ref), "current_rows": sum(cur),
            "bins": [{"label": b["label"], "term": b["term"], "floored": b["floored"]} for b in res[1]]}


drift = {}
agg = load("cutoff_aggregates")
for i, cut in enumerate(CUTS):
    cur = [r for r in rows if r["cutoff_index"] == i]
    ref = [r for r in rows if r["cutoff_index"] == 0]
    drift[cut] = {"all_accounts": psi_for(ref, cur), "apac": psi_for([r for r in ref if r["region"] == "apac"], [r for r in cur if r["region"] == "apac"]),
                  "other_regions": psi_for([r for r in ref if r["region"] != "apac"], [r for r in cur if r["region"] != "apac"])}
    pub = next(c for c in agg["drift"]["by_cutoff"] if c["prediction_at"] == cut)
    for k, kk in (("all_accounts", "all_accounts"), ("apac", "apac"), ("other_regions", "other_regions")):
        need(f"psi {cut} {k}", drift[cut][k]["psi"], pub[kk]["psi"])

# ------------------------------------------------------------------------------------------------------------------------------ designed relationships
def leaves(v, p=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from leaves(x, f"{p}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from leaves(x, f"{p}[{i}]")
    else:
        yield p, v


dr = {d["id"]: dict(leaves(d["realised"])) for d in manifest["designed_relationships"]}
# DR-01: AP and Brier per model on the test population, and the margins
t = test_table["test"]
real = {m: (t[mm]["average_precision"], t[mm]["brier_score"]) for m, mm in (("random_baseline", "random_baseline"), ("business_rule", "business_rule"), ("logistic_regression", "logistic_calibrated"))}
for m, (a, b) in real.items():
    need(f"DR-01 {m} AP", a, dr["DR-01"][f".{m}.average_precision"])
    need(f"DR-01 {m} Brier", b, dr["DR-01"][f".{m}.brier_score"])
lr, ru, ra = real["logistic_regression"], real["business_rule"], real["random_baseline"]
margins = {"ap_over_rule": p6(F(lr[0]) - F(ru[0])), "ap_over_random": p6(F(lr[0]) - F(ra[0])), "brier_under_rule": p6(F(ru[1]) - F(lr[1])), "brier_under_random": p6(F(ra[1]) - F(lr[1]))}
for k, v in margins.items():
    need(f"DR-01 margin {k}", v, dr["DR-01"][f".margins.{k}"])
# DR-03: the PSI of the apac cohort in the test range
need("DR-03 before change", [drift[CUTS[0]]["apac"]["psi"], drift[CUTS[1]]["apac"]["psi"]], [dr["DR-03"][".before_change_psi[0]"], dr["DR-03"][".before_change_psi[1]"]])
need("DR-03 first after change", drift[CUTS[3]]["apac"]["psi"], dr["DR-03"][".after_change_psi[0]"])
# DR-05: shares from the per-cutoff aggregates
elig = sum(c["population"]["eligible"] for c in agg["cutoffs"])
cens = sum(c["population"]["censored"] for c in agg["cutoffs"])
mat = sum(c["population"]["mature"] for c in agg["cutoffs"])
chn = sum(c["population"]["churned"] for c in agg["cutoffs"])
need("DR-05 eligible", elig, dr["DR-05"][".eligible_rows"])
need("DR-05 censored", cens, dr["DR-05"][".censored_rows"])
need("DR-05 share", p6(F(cens, elig)), dr["DR-05"][".censored_share"])
need("DR-05 mature churn", p6(F(chn, mat)), dr["DR-05"][".mature_churn_rate"])
# DR-04: the shares and the changed-row share are ratios of the manifest's own counts
r4 = dr["DR-04"]
for e in ("billing_events", "subscription_events", "support_events", "usage_events"):
    need(f"DR-04 {e} share", p6(F(r4[f".realised.{e}.late_one_day_or_more"], r4[f".realised.{e}.events"])), r4[f".realised.{e}.share"])
need("DR-04 changed share", p6(F(r4[".test_rows_features_change_if_ignored"], r4[".test_rows"])), r4[".share_of_test_rows_changed"])

ref = {"generated_by": "scripts/make-snapshot-reference.py", "python": sys.version.split()[0], "dataset_version": manifest["dataset_version"], "dataset_hash": manifest["dataset_hash"],
       "ks": KS, "cohort": cohort, "test_table": test_table, "gaps": gaps, "psi_by_region": drift,
       "designed": {"leaves": {k: v for k, v in dr.items()}, "recomputed": {"DR-01": ["average_precision", "brier_score", "margins"], "DR-02": ["gap_pp by segment and region, overall"],
                                                                         "DR-03": ["PSI in the four test cutoffs (before change and first after change)"], "DR-04": ["the shares as ratios of the manifest's counts"],
                                                                         "DR-05": ["eligible, censored, share, mature churn from the aggregates"]}}}
out = Path(__file__).resolve().parent / "snapshot-reference.json"
out.write_text(json.dumps(ref, indent=1, sort_keys=True) + "\n")
print(f"wrote {out} ({out.stat().st_size} bytes); config_hash check {config_hash(load('training_runs')['rows'][0]['config'])[:12]}")
