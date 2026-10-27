"""Writes scripts/snapshot-reference.json: what the PYTHON domain (domain/changeworks) computes over the published snapshot in
web/public/data, so CI can compare the TypeScript mirror without Python. Run once, from apps/changeworks:

    python -I web/scripts/make-snapshot-reference.py

Contents: sha256 digests (canonical JSON, sorted keys, compact) of every metric block at the as-of 2026-10-05 and at four other instants around
period boundaries (a matured period is one whose end is <= as-of, so 2026-03-31T23:59:59Z, 2026-04-01T00:00:00Z and 2026-04-01T00:00:01Z
straddle one), half-open windows (including an empty one and one that starts exactly on a period start), a scenario narrowing, the NPV and both
paybacks of every initiative at seven horizons, the annual-to-monthly rate conversion on a grid (high-precision Decimal, an independent method),
the portfolio table (costs and each benefit class per scenario, summed from the domain's own pieces with Fractions: exact sums rounded once, never a sum of
rounded rows; the class totals are attributable, the claims that count twice taken off class by class) and the figures behind the seven designed relationships.
"""
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, getcontext
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "domain"))
from changeworks.cashflow import Model, expand_costs  # noqa: E402
from changeworks.context import Ctx  # noqa: E402
from changeworks.contract import ENTITIES  # noqa: E402
from changeworks.metrics import compute  # noqa: E402
from changeworks.numbers import dec, money  # noqa: E402
from changeworks.pipeline import run_pipeline  # noqa: E402
from changeworks.timeutil import matured_count, parse_ts  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
manifest = json.loads((DATA / "manifest.json").read_text())
files = {n: json.loads((DATA / f"{n}.json").read_text())["rows"] for n in ENTITIES}
inputs = dict(manifest["config"])
inputs.update(files)
res = run_pipeline(inputs)
pop = res.population


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(v):
    return hashlib.sha256(canon(v).encode()).hexdigest()


def blocks(m, warnings):
    out = {"summary": digest(m["summary"]), "initiatives": digest(m["initiatives"]), "groups": digest(m["groups"]), "resources": digest(m["resources"])}
    out["scenarios"] = {sid: digest(s) for sid, s in m["scenarios"].items()}
    return {"digests": out, "warning_codes": sorted({w["code"] for w in warnings}), "warning_count": len(warnings), "summary": m["summary"]}


AS_OFS = ["2026-10-05T00:00:00Z", "2026-07-01T00:00:00Z", "2026-03-31T23:59:59Z", "2026-04-01T00:00:00Z", "2026-04-01T00:00:01Z"]
as_ofs = {}
for t in AS_OFS:
    m, w = compute(pop, parse_ts(t))
    as_ofs[t] = blocks(m, w)
    as_ofs[t]["matured_periods"] = matured_count(pop.config, parse_ts(t), 36)

WINDOWS = [("2026-03-01T00:00:00Z", "2026-06-01T00:00:00Z"), ("2026-04-01T00:00:00Z", "2026-04-01T00:00:00Z"), (None, "2026-02-01T00:00:00Z"),
           ("2026-09-01T00:00:00Z", None), ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"), ("2026-03-31T23:59:59Z", "2026-04-01T00:00:01Z")]
windows = []
for lo, hi in WINDOWS:
    m, w = compute(pop, res.as_of, (parse_ts(lo) if lo else None, parse_ts(hi) if hi else None))
    windows.append({"from": lo, "to": hi, **blocks(m, w)})

m2, w2 = compute(pop, res.as_of, None, ["scn-025", "scn-001"])
narrow = {"scenario_ids": ["scn-025", "scn-001"], **blocks(m2, w2)}

# NPV and paybacks at several horizons: every scenario's horizon replaced, the whole domain re-run
HORIZONS = [1, 3, 6, 12, 18, 24, 36]
horizons = {}
for H in HORIZONS:
    p2 = copy.deepcopy(pop)
    for s in p2.acc["scenario_versions"]:
        s["horizon_periods"] = H
    m, _ = compute(p2, res.as_of)
    table = {sid: {iid: [b["npv"]["exact"], b["payback"]["simple"], b["payback"]["discounted"]] for iid, b in s["initiatives"].items()} for sid, s in m["scenarios"].items()}
    horizons[str(H)] = {"digest": digest(table), "scn-025_npv_exact": {iid: row[0] for iid, row in table["scn-025"].items()},
                        "scn-025_payback_simple": {iid: row[1]["period"] for iid, row in table["scn-025"].items()}}

# the monthly conversion of an annual rate, by an independent method (Decimal at 60 digits)
getcontext().prec = 60
conv = []
for k in range(0, 61):
    r = Decimal(k) / Decimal(200)           # 0.000 .. 0.300 step 0.005
    mth = ((1 + r) ** (Decimal(1) / 12) - 1).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    conv.append([f"{r:.6f}", f"{mth:.6f}"])
published_conversions = []
for s in pop.acc["scenario_versions"]:
    if s["rate_conversion_assumption_id"]:
        a = next(x for x in pop.acc["assumption_versions"] if x["assumption_id"] == s["rate_conversion_assumption_id"])
        published_conversions.append([s["scenario_id"], s["discount_rate"], a["value"]])

# the portfolio table, from the domain's own pieces and Fractions (the pages must show these)
ctx = Ctx(pop, res.as_of)


def scenario_totals(sc):
    """Per scenario: costs and each class summed from the exact amounts of the plan rows the scenario was built on (R9-01), rounded once (R9-07)."""
    tot = {"costs": F(0), "cash": F(0), "revenue": F(0), "avoided": F(0), "capacity_usd": F(0), "avoided_beside": F(0), "capacity_hours": F(0)}
    per = {}
    costs, bens = ctx.costs(sc), ctx.benefits(sc)
    for iid in sc["initiative_ids"]:
        model = Model(ctx, sc, iid)
        H = sc["horizon_periods"]
        c = {k: F(0) for k in tot}
        for ci in costs:
            if ci["initiative_id"] == iid and ci["cost_basis"] == "planned":
                for _, p, a in expand_costs(ci, H):
                    c["costs"] += a
        for b in bens:
            if b["initiative_id"] != iid or b["period_index"] >= H:
                continue
            a, t = model.ramped(b), b["benefit_type"]
            if t == "cash":
                c["cash"] += a
            elif t == "revenue":
                c["revenue"] += a
            elif t == "avoided_cost":
                if b["cash_realisation"] and (b["evidence_ref"] or "").strip():
                    c["avoided"] += a
                else:
                    c["avoided_beside"] += a
            elif t == "capacity":
                if model.conv_ok:
                    c["capacity_usd"] += a * model.rate_cap
                else:
                    c["capacity_hours"] += a
        for k in tot:
            tot[k] += c[k]
        per[iid] = {k: money(v) for k, v in c.items()}
    return tot, per


portfolio = {}
CLASS_OF = {"cash": "cash", "revenue": "revenue", "avoided": "avoided_cost_realised", "capacity_usd": "capacity_converted", "avoided_beside": "avoided_cost_beside"}
for sc in ctx.scenarios:
    t, per = scenario_totals(sc)
    blk = res.metrics["scenarios"][sc["scenario_id"]]
    removed = {k: F(blk["double_count"]["double_counted_by_class_exact"][CLASS_OF[k]]) for k in CLASS_OF}
    attributable = {k: money(t[k] - removed[k]) if k in CLASS_OF else money(t[k]) for k in t}              # the class totals less the claims that count twice; hours are never added
    portfolio[sc["scenario_id"]] = {**attributable, "listed": {k: money(t[k]) for k in CLASS_OF}, "removed": {k: money(removed[k]) for k in CLASS_OF},
                                    "npv_total": blk["npv_total"]["value"], "npv_sum": blk["npv_total"]["sum_of_initiatives"], "double_counted_pv": blk["double_count"]["double_counted_pv"],
                                    "double_counted_amount": blk["double_count"]["double_counted_amount"], "hours_residual": blk["double_count"]["hours_residual"],
                                    "residual": blk["double_count"]["residual"], "planned": blk["double_count"]["planned_benefits"],
                                    "attributable": blk["double_count"]["attributable_benefits"], "initiatives": len(sc["initiative_ids"]),
                                    "never_simple": sum(1 for b in blk["initiatives"].values() if b["payback"]["simple"]["period"] is None),
                                    "never_discounted": sum(1 for b in blk["initiatives"].values() if b["payback"]["discounted"]["period"] is None),
                                    "per_initiative_digest": digest(per)}

# the figures behind the designed relationships, from the Python domain's output
M = res.metrics
S25 = M["scenarios"]["scn-025"]
designed = {
    "DR-01": {"init-009": {"npv": S25["initiatives"]["init-009"]["npv"]["value"], "capacity_hours_not_converted": S25["initiatives"]["init-009"]["excluded_from_cash_flow"]["capacity_hours_not_converted"],
                           "simple_payback": S25["initiatives"]["init-009"]["payback"]["simple"]["period"], "released": S25["initiatives"]["init-009"]["capacity_released"]["hours"]}},
    "DR-02": {"planned": S25["double_count"]["planned_benefits"], "attributable": S25["double_count"]["attributable_benefits"], "residual": S25["double_count"]["residual"],
              "npv_attributable": S25["npv_total"]["value"], "npv_sum": S25["npv_total"]["sum_of_initiatives"], "double_counted_pv": S25["double_count"]["double_counted_pv"],
              "hours_residual": S25["double_count"]["hours_residual"],
              "overlap_periods": len(S25["double_count"]["overlaps"]), "scenarios_with_residual": [k for k, s in M["scenarios"].items() if s["double_count"]["residual"] != "0.00"],
              "scenarios_with_hours_residual": [k for k, s in M["scenarios"].items() if s["double_count"]["hours_residual"] != "0.00"]},
    "DR-03": {"init-015": {sid: [s["initiatives"]["init-015"]["npv"]["value"], s["initiatives"]["init-015"]["payback"]["simple"]["period"], s["initiatives"]["init-015"]["payback"]["discounted"]["period"]]
                           for sid, s in M["scenarios"].items() if "init-015" in s["initiatives"]},
              "benefit_to_cost": {sid: str(F(sum(F(r["cash_benefits"]) for r in s["initiatives"]["init-015"]["cash_flow"]), 1) / sum(F(r["costs"]) for r in s["initiatives"]["init-015"]["cash_flow"]))
                                  for sid, s in M["scenarios"].items() if "init-015" in s["initiatives"]}},
    "DR-04": {"versions": [[v["version_number"], v["total"], v["created_at"]] for v in M["initiatives"]["init-003"]["forecast"]["versions"]], "latest_minus_original": M["initiatives"]["init-003"]["forecast"]["latest_minus_original"]},
    "DR-05": {"res-03": M["resources"]["res-03"]},
    "DR-06": S25["initiatives"]["init-008"]["benefit_realization"]["cash"],
    "DR-07": {"adoption": M["summary"]["adoption_rate"], "training": M["summary"]["training_completion"]},
}

ref = {
    "generated_by": "scripts/make-snapshot-reference.py (the Python domain, domain/changeworks)",
    "dataset_hash": manifest["dataset_hash"], "dataset_version": manifest["dataset_version"], "as_of": manifest["as_of"],
    "ingest_counts": res.counts, "rejected_count": len(res.ingest.rejected),
    "dataset_hash_check": {"sha256_of_17_entity_files": hashlib.sha256("".join(json.dumps(files[n], sort_keys=True, separators=(",", ":")) for n in sorted(files)).encode()).hexdigest()},
    "as_ofs": as_ofs, "windows": windows, "scenario_narrowing": narrow, "horizons": horizons,
    "conversion_grid": conv, "published_conversions": published_conversions,
    "portfolio": portfolio, "designed": designed,
    "full_digest": digest(res.golden()),
}
(Path(__file__).resolve().parent / "snapshot-reference.json").write_text(json.dumps(ref, sort_keys=True, indent=1) + "\n")
print("wrote snapshot-reference.json:", len(canon(ref)), "bytes of canonical JSON;", len(as_ofs), "as-of instants,", len(windows), "windows,", len(horizons), "horizons,", len(portfolio), "scenarios")
print("dataset_hash check:", ref["dataset_hash_check"]["sha256_of_17_entity_files"] == manifest["dataset_hash"])
