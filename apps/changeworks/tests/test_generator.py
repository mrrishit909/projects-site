"""Synthetic data generator: determinism, size, the brief's counts, designed relationships, injected defects.

The generator (data/generate.py) is deterministic (stdlib plus the domain) and writes the world under web/public/data. These tests run the domain over
that world (ingest with no rejection, the metrics, the manifest's claims, every designed relationship, every injection check) and replay the rows and
commands of the injection manifest: the ingest-level steps through the domain's validator, and, with DATABASE_URL set, the command and read steps
through the FastAPI TestClient on the seeded world. The database tests FAIL (they do not skip) without DATABASE_URL, like the rest of the suite.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("cw_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["cw_generate"] = gen
_spec.loader.exec_module(gen)

from changeworks import run_pipeline  # noqa: E402
from changeworks.contract import ENTITIES as DOMAIN_ENTITIES, ID_FIELD  # noqa: E402
from changeworks.ingest import Validator, validate_batch  # noqa: E402

SEED = 20261026
VERSION = f"cw-{SEED}-20261026"
PUBLISHED = ROOT / "web" / "public" / "data"
BUDGET = 5_000_000
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
MONEY = re.compile(r"^-?\d+\.\d{2}$")
PROP6 = re.compile(r"^[01]\.\d{6}$")
AS_OF = "2026-10-05T00:00:00Z"
BRIEF = {"initiatives": 24, "process_baselines": 30, "assumption_versions": 160, "resources": 8, "scenario_versions": 30, "cost_items": 900, "benefit_items": 700,
         "dependencies": 40, "stakeholder_groups": 60, "readiness_assessments": 300, "adoption_observations": 500, "training_completions": 200, "benefit_observations": 400,
         "risk_items": 120}
MONEY_FIELDS = {"cost_items": ("amount",), "benefit_items": ("amount", "baseline_trend_per_period"), "benefit_observations": ("measured_value",), "risk_items": ("impact",),
                "forecast_versions": ("amount",), "resource_allocations": ("amount",), "resources": ("capacity_per_period",)}
INSTANT_FIELDS = {"process_baselines": ("measured_at",), "assumption_versions": ("created_at",), "scenario_versions": ("created_at",), "readiness_assessments": ("assessed_at",),
                  "adoption_observations": ("observed_at",), "training_completions": ("recorded_at",), "benefit_observations": ("observed_at",), "forecast_versions": ("created_at",)}


def no_float(text: str):
    def refuse(x):
        raise AssertionError(f"a float literal ({x}) in the output")
    return json.loads(text, parse_float=refuse)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen")
    out = tmp / "out"
    manifest = gen.write_all(SEED, out)
    rows = {}
    for name in gen.ENTITIES:
        doc = no_float((out / f"{name}.json").read_text())
        assert list(doc) == ["entity", "dataset_version", "rows"] and doc["entity"] == name and doc["dataset_version"] == VERSION
        rows[name] = doc["rows"]
    man = no_float((out / "manifest.json").read_text())
    inj = no_float((out / "injection-manifest.json").read_text())
    inputs = gen.to_inputs(rows)
    return {"out": out, "manifest": man, "inj_doc": inj, "rows": rows, "inputs": inputs, "result": run_pipeline(inputs),
            "inj": {i["id"]: i for i in inj["injections"]}, "dr": {d["id"]: d for d in inj["designed_relationships"]}, "events": {e["event_id"]: e for e in inj["events"]}}


# ------------------------------------------------------------------------------------------------------------------------------ determinism, size
def test_same_seed_same_bytes(built, tmp_path):
    again = tmp_path / "again"
    gen.write_all(SEED, again)
    names = sorted(p.name for p in built["out"].glob("*.json"))
    assert names == sorted(p.name for p in again.glob("*.json")) and len(names) == len(gen.ENTITIES) + 2
    for n in names:
        assert (built["out"] / n).read_bytes() == (again / n).read_bytes(), n


def test_python_hash_seed_does_not_change_the_bytes(built, tmp_path):
    for hs in ("1", "2"):
        out = tmp_path / f"hs{hs}"
        r = subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--out", str(out)], env={**os.environ, "PYTHONHASHSEED": hs}, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        for n in ("manifest.json", "injection-manifest.json", "benefit_items.json", "adoption_observations.json"):
            assert (out / n).read_bytes() == (built["out"] / n).read_bytes(), (hs, n)


def test_another_seed_gives_another_world(built, tmp_path):
    out = tmp_path / "other"
    other = gen.write_all(SEED + 1, out)
    assert other["dataset_hash"] != built["manifest"]["dataset_hash"]
    ents = {n: no_float((out / f"{n}.json").read_text())["rows"] for n in gen.ENTITIES}
    assert not validate_batch(gen.to_inputs(ents)).rejected, "another seed must also be a valid world"


def test_the_published_files_are_the_generator_output():
    """The committed files are what `python data/generate.py` writes: a rerun produces no diff."""
    assert PUBLISHED.is_dir(), "run python data/generate.py"
    names = sorted(p.name for p in PUBLISHED.glob("*.json"))
    assert names == sorted([f"{n}.json" for n in gen.ENTITIES] + ["manifest.json", "injection-manifest.json"])
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        gen.write_all(SEED, Path(d))
        for n in names:
            assert (PUBLISHED / n).read_bytes() == (Path(d) / n).read_bytes(), n


def test_size_cap_under_5_mb(built):
    total = sum(p.stat().st_size for p in built["out"].glob("*.json"))
    assert total < BUDGET, total
    assert built["manifest"]["stats"]["entity_file_bytes"] < BUDGET
    assert sum(p.stat().st_size for p in PUBLISHED.glob("*.json")) < BUDGET


def test_manifest_shape_and_fixed_dates(built):
    m = built["manifest"]
    assert m["dataset_version"] == VERSION and m["as_of"] == AS_OF and m["generated_at"] == AS_OF and m["contract_version"] == "v1"
    assert re.fullmatch(r"[0-9a-f]{64}", m["dataset_hash"]) and m["injection_manifest"] == "injection-manifest.json"
    assert m["dataset_hash"] == gen.dataset_hash(built["rows"]) == built["inj_doc"]["dataset_hash"]
    assert m["config"] == {"contract_version": 1, "period_basis": "monthly", "period_start": "2026-01-01", "periods": 36, "as_of": AS_OF}
    assert m["generator"]["name"] == "generate.py" and m["generator"]["seed"] == SEED
    assert m["row_counts"] == {n: len(built["rows"][n]) for n in gen.ENTITIES}
    assert "disclosures" in m["generator"]["parameters"] and "outcome-informed" in m["generator"]["parameters"]["disclosures"].lower()
    assert m["stats"]["forecast_version_sets"] == 12
    assert m["stats"]["primary_objects"] > 0 and m["stats"]["linked_events"] > 0                    # objects and events are reported apart (section 12)
    assert [p["programme_id"] for p in m["programmes"]] == ["prog-fin", "prog-cust", "prog-supply", "prog-work"]
    assert sorted(i for p in m["programmes"] for i in p["initiative_ids"]) == sorted(r["initiative_id"] for r in built["rows"]["initiatives"])


# ------------------------------------------------------------------------------------------------------------------------------ formats and the brief
def test_row_counts_are_the_briefs(built):
    for name, n in BRIEF.items():
        assert len(built["rows"][name]) == n, name
    assert len({(f["initiative_id"], f["version_number"]) for f in built["rows"]["forecast_versions"]}) == 12
    assert len(built["rows"]["impact_mappings"]) >= 60 and len(built["rows"]["resource_allocations"]) > 100


def test_money_instants_and_proportions_are_formatted(built):
    for name, fields in MONEY_FIELDS.items():
        for r in built["rows"][name]:
            for f in fields:
                if r[f] is not None:
                    assert MONEY.match(r[f]), (name, r)
    for name, fields in INSTANT_FIELDS.items():
        for r in built["rows"][name]:
            for f in fields:
                assert STAMP.match(r[f]), (name, f, r[f])
    for r in built["rows"]["risk_items"]:
        assert PROP6.match(r["probability"])
    for r in built["rows"]["process_baselines"]:
        assert PROP6.match(r["error_rate"])
    for r in built["rows"]["scenario_versions"]:
        assert PROP6.match(r["discount_rate"])
    for r in built["rows"]["assumption_versions"]:
        for v in ([r["value"]] if r["value"] is not None else r["values"]):
            assert re.fullmatch(r"\d+(\.\d{1,6})?", v), r
    for ent, rows in built["rows"].items():
        ids = [r[ID_FIELD[ent]] for r in rows]
        assert len(ids) == len(set(ids)), f"{ent}: ids are not unique"


def test_the_calendar_and_the_register_follow_the_brief(built):
    R = built["rows"]
    assert built["inputs"]["period_basis"] == "monthly" and built["inputs"]["period_start"] == "2026-01-01" and built["inputs"]["as_of"] == AS_OF
    top = max([b["period_index"] for b in R["benefit_items"]] + [c["period_index"] for c in R["cost_items"] if c["period_index"] is not None]
              + [c["end_period"] - 1 for c in R["cost_items"] if c["end_period"] is not None])
    assert top <= 35 and all(s["horizon_periods"] <= 36 for s in R["scenario_versions"])
    assert {i["status"] for i in R["initiatives"]} == {"candidate", "assessed", "in_delivery", "adopted", "closed"}
    assert not any(i["status"] == "funded" for i in R["initiatives"]) and not any(s["status"] == "funded" for s in R["scenario_versions"])
    progs = built["manifest"]["programmes"]
    assert len(progs) == 4 and all(len(p["initiative_ids"]) == 6 for p in progs) and len({i["sponsor_id"] for i in R["initiatives"]}) >= 4
    assert {b["baseline_version"] for b in R["process_baselines"]} == {"v1", "v2"} and {i["baseline_version"] for i in R["initiatives"]} == {"v1", "v2", None}
    assert {b["benefit_type"] for b in R["benefit_items"]} == {"cash", "avoided_cost", "revenue", "capacity"}
    assert {c["cost_type"] for c in R["cost_items"]} == {"one_time", "recurring"} and {c["cost_basis"] for c in R["cost_items"]} == {"planned", "actual"}
    assert {d["dependency_type"] for d in R["dependencies"]} == {"finish_to_start", "start_to_start"}
    assert len({a["resource_id"] for a in R["resource_allocations"]}) == 8
    assert {s["rate_basis"] for s in R["scenario_versions"]} == {"annual", "monthly"}
    assert {a["name"] for a in R["assumption_versions"]} >= {"adoption_ramp", "target_minutes_per_case", "capacity_hourly_rate", "monthly_rate_conversion"}
    assert max(a["version_number"] for a in R["assumption_versions"]) >= 2
    conv = [a for a in R["assumption_versions"] if a["name"] == "monthly_rate_conversion"]
    assert len(conv) == 4 and all(a["initiative_id"] is None and re.fullmatch(r"0\.\d{6}", a["value"]) for a in conv)
    for r in R["benefit_observations"]:
        assert r["observed_at"] < AS_OF                                             # nothing after the as-of instant exists yet
    for name in ("adoption_observations", "training_completions", "readiness_assessments", "forecast_versions"):
        for r in R[name]:
            assert next(v for k, v in r.items() if k in INSTANT_FIELDS[name]) <= AS_OF, (name, r)
    assert all(b["baseline_trend_per_period"] is not None for b in R["benefit_items"])       # a trend on every benefit: the partial-coverage rule never fires


def test_stakeholder_labels_are_synthetic(built):
    for g in built["rows"]["stakeholder_groups"]:
        name = g["group_name"].replace(" ", "").replace("-", "")
        assert "@" not in name and not re.search(r"\d{6,}", name)
    groups = {g["group_id"] for g in built["rows"]["stakeholder_groups"]}
    assert {m["group_id"] for m in built["rows"]["impact_mappings"]} == groups
    assert {a["group_id"] for a in built["rows"]["readiness_assessments"]} == groups


# ------------------------------------------------------------------------------------------------------------------------------ the domain reads the world
def test_the_domain_ingests_the_world_with_the_manifests_counts(built):
    res, m = built["result"], built["manifest"]
    counts = res.counts
    assert counts == {e: {"accepted": m["row_counts"][e], "rejected": 0} for e in DOMAIN_ENTITIES}
    assert m["stats"]["ingest"] == counts and res.ingest.rejected_records() == [] and not res.empty_population
    assert {x["code"] for x in res.warnings} <= {"BASELINE_VERSION_DIFFERS"} and m["stats"]["warnings"] == {"BASELINE_VERSION_DIFFERS": len(res.warnings)}


def test_the_manifests_numbers_are_the_domains(built):
    res, m = built["result"], built["manifest"]
    assert m["stats"]["summary"] == res.metrics["summary"]
    for sid, s in res.metrics["scenarios"].items():
        row = m["stats"]["scenarios"][sid]
        assert row == {"status": s["status"], "baseline_version": s["baseline_version"], "horizon_periods": s["horizon_periods"], "rate_source": s["rate_source"],
                       "effective_period_rate": s["effective_period_rate"], "npv_total": s["npv_total"]["value"], "double_count_residual": s["double_count"]["residual"]}
    for iid, row in m["stats"]["initiatives_in_scn-025"].items():
        b = res.metrics["scenarios"]["scn-025"]["initiatives"][iid]
        assert row["npv"] == b["npv"]["value"] and row["simple_payback"] == b["payback"]["simple"]["period"] and row["capacity_released_hours"] == b["capacity_released"]["hours"]
        assert row["adoption_rate"] == res.metrics["initiatives"][iid]["adoption"]["adoption_rate"]


def test_the_generator_and_a_second_reading_agree(built):
    """The manifest was written from the domain's reading inside the generator; a fresh reading of the written files gives the same designed relationships."""
    _, ents, inj = gen.build(SEED)
    assert json.loads(json.dumps(inj.designed)) == built["inj_doc"]["designed_relationships"] == built["manifest"]["designed_relationships"]
    assert json.loads(json.dumps(ents)) == built["rows"]


def test_synthetic_truth_lives_only_in_the_manifest(built):
    m = built["manifest"]
    assert m["synthetic_truth"]["by_initiative_and_type"] and "never loaded" in m["synthetic_truth"]["note"]
    for name in gen.ENTITIES:
        text = (built["out"] / f"{name}.json").read_text()
        assert "true_" not in text and "synthetic_truth" not in text, name
    assert "synthetic_truth" not in (built["out"] / "injection-manifest.json").read_text()
    t8 = m["synthetic_truth"]["by_initiative_and_type"]["init-008/cash"]
    assert Fraction(t8["true_attributable_share"]) < Fraction(25, 100)                         # DR-06: the rollout caused a minor share


# ------------------------------------------------------------------------------------------------------------------------------ designed relationships
def metrics_of(built):
    return built["result"].metrics


def test_dr01_capacity_is_the_only_benefit(built):
    d = built["dr"]["DR-01"]["realised"]
    M = metrics_of(built)
    iid = d["initiative_id"]
    assert [b["benefit_type"] for b in built["rows"]["benefit_items"] if b["initiative_id"] == iid and b["benefit_type"] != "capacity"] == []
    assert d["benefit_classes"] == ["capacity"] and d["cash_benefits_total"] == "0.00" and d["converted_capacity_items"] == 0
    blk = M["scenarios"][d["scenario_id"]]["initiatives"][iid]
    assert blk["payback"]["simple"]["period"] is None and d["simple_payback"] is None and Fraction(blk["npv"]["value"]) < 0
    assert blk["excluded_from_cash_flow"]["capacity_hours_not_converted"] == d["capacity_hours_not_converted"]
    assert not [a for a in built["rows"]["assumption_versions"] if a["initiative_id"] == iid and a["name"] == "capacity_hourly_rate"]


def test_dr02_two_initiatives_claim_the_same_capacity(built):
    d = built["dr"]["DR-02"]["realised"]
    M = metrics_of(built)
    claims = [b for b in built["rows"]["benefit_items"] if b["benefit_source_key"] == d["benefit_source_key"]]
    assert {b["initiative_id"] for b in claims} == set(d["initiatives"]) and {b["benefit_type"] for b in claims} == {"capacity"}
    dc = M["scenarios"][d["scenario_id"]]["double_count"]
    assert dc["residual"] == d["residual"] and Fraction(d["residual"]) > 0 and dc["explanation_required"] is True
    assert Fraction(dc["planned_benefits"]) - Fraction(dc["attributable_benefits"]) == Fraction(dc["residual"])
    assert "scn-026" in d["scenarios_with_no_residual"] and not set(d["scenarios_with_no_residual"]) & set(d["scenarios_with_a_residual"])
    assert sorted(d["scenarios_with_no_residual"] + d["scenarios_with_a_residual"]) == sorted(s["scenario_id"] for s in built["rows"]["scenario_versions"])
    assert d["scenarios_with_a_residual"] == sorted(sid for sid, s in M["scenarios"].items() if s["double_count"]["residual"] != "0.00")
    pins_before_may = [s for s in built["rows"]["scenario_versions"] if s["created_at"] < "2026-05-01" and set(d["initiatives"]) <= set(s["initiative_ids"])]
    assert pins_before_may and all(M["scenarios"][s["scenario_id"]]["double_count"]["residual"] == "0.00" for s in pins_before_may)


def test_dr03_one_initiative_never_pays_back(built):
    d = built["dr"]["DR-03"]["realised"]
    M = metrics_of(built)
    assert d["scenarios"] and d["scenarios_with_simple_payback_null"] == d["scenarios_with_discounted_payback_null"] == len(d["scenarios"])
    for sid in d["scenarios"]:
        b = M["scenarios"][sid]["initiatives"][d["initiative_id"]]
        assert b["payback"]["simple"] == {"period": None, "interpolated": None} and b["payback"]["discounted"] == {"period": None, "interpolated": None}
        assert Fraction(b["npv"]["value"]) < 0
    assert Fraction(d["benefit_to_cost"]) < 1 and Fraction(d["npv_highest"]) < 0
    others = [i["initiative_id"] for i in built["rows"]["initiatives"] if i["initiative_id"] != d["initiative_id"]]
    assert sum(1 for iid in others if M["scenarios"]["scn-025"]["initiatives"][iid]["payback"]["simple"]["period"] is not None) >= 12      # the others do pay back


def test_dr04_a_forecast_revised_twice_after_a_missed_target(built):
    d = built["dr"]["DR-04"]["realised"]
    fc = metrics_of(built)["initiatives"][d["initiative_id"]]["forecast"]
    assert [v["version_number"] for v in fc["versions"]] == [1, 2, 3] and fc["original_version"] == 1 and fc["original_preserved"] is True
    assert [v["created_at"] for v in d["versions"]] == ["2026-03-12T10:00:00Z", "2026-06-12T10:00:00Z", "2026-09-09T10:00:00Z"]
    rows = [f for f in built["rows"]["forecast_versions"] if f["initiative_id"] == d["initiative_id"]]
    v1 = {f["period_index"]: Fraction(f["amount"]) for f in rows if f["version_number"] == 1}
    v2 = {f["period_index"]: Fraction(f["amount"]) for f in rows if f["version_number"] == 2}
    v3 = {f["period_index"]: Fraction(f["amount"]) for f in rows if f["version_number"] == 3}
    assert sum(v1.values()) > sum(v2.values()) > sum(v3.values()) and v1.keys() == v2.keys() == v3.keys()
    assert [p for p in v1 if v1[p] != v2[p]] and all(v1[p] == v2[p] for p in v1 if p < 5)
    for miss, prev_label in zip(d["misses"], ("version 1", "version 2")):
        assert miss["periods_below_the_previous_forecast"], f"no missed period before the revision of {prev_label}"
        assert miss["periods_below_the_previous_forecast"] == miss["periods_checked"]
        for p, ratio in miss["observed_over_forecast"].items():
            assert Fraction(ratio) < Fraction(100 - d["miss_tolerance_percent"], 100)
    assert len(d["misses"]) == 2 and all(o["period_matured"] for o in fc["observed"] if o["period_index"] <= 8)


def test_dr05_a_specialist_is_overallocated_in_three_periods(built):
    d = built["dr"]["DR-05"]["realised"]
    M = metrics_of(built)
    assert d["periods"] == d["refused_periods"] == [14, 15, 16] and d["requests_refused"] == 3 and d["stored_overallocated_periods"] == []
    res = M["resources"][d["resource_id"]]
    assert res["overallocated_periods"] == [] and all(res["by_period"][i]["allocated"] == "2.00" for i in range(len(res["by_period"])) if res["by_period"][i]["period_index"] in (14, 15, 16))
    for r in M["resources"].values():
        assert r["overallocated_periods"] == []
    ev = built["events"]["EV-09"]["steps"]
    assert [s["reason_code"] for s in ev[:3]] == ["RESOURCE_OVERALLOCATED"] * 3 and [s["details"]["periods"] for s in ev[:3]] == [[14], [15], [16]]
    assert not [a for a in built["rows"]["resource_allocations"] if a["allocation_id"].startswith("al-inj")]          # the refused rows are not in the world


def test_dr06_an_improvement_that_is_mostly_the_baseline_trend(built):
    d = built["dr"]["DR-06"]["realised"]
    rb = metrics_of(built)["scenarios"][d["scenario_id"]]["initiatives"][d["initiative_id"]]["benefit_realization"]["cash"]
    assert rb["attribution"] == "observed, not attributed" and d["realization"] == rb["realization"]
    assert Fraction(rb["realization"]) > Fraction(9, 10)                                                         # close to plan ...
    share = Fraction(rb["baseline_trend"]) / Fraction(rb["observed_comparable"])
    assert Fraction(8, 10) < share < Fraction(9, 10) and abs(Fraction(d["trend_share_of_observed"]) - share) <= Fraction(1, 10 ** 6)             # ... and mostly the trend
    assert Fraction(rb["observed_above_trend"]) == Fraction(rb["observed_comparable"]) - Fraction(rb["baseline_trend"])
    typical = [Fraction(b["baseline_trend"]) / Fraction(b["observed_comparable"]) for iid, blk in metrics_of(built)["scenarios"]["scn-025"]["initiatives"].items()
               for t, b in blk["benefit_realization"].items() if iid != d["initiative_id"] and b["observed_comparable"] and Fraction(b["observed_comparable"]) > 0]
    assert typical and max(typical) < Fraction(1, 2)


def test_dr07_adoption_lags_training_completion(built):
    d = built["dr"]["DR-07"]["realised"]
    M = metrics_of(built)
    assert len(d["initiatives"]) == 11 and d["lag_periods_sorted"] and min(d["lag_periods_sorted"]) >= 3
    for x in d["initiatives"]:
        assert Fraction(x["training_completion_now"]) > Fraction(9, 10)
        assert x["periods_since_training_90_percent"] >= 3
        if x["lag_periods"] is None:
            assert Fraction(x["adoption_rate_now"]) < Fraction(1, 2)
        else:
            assert x["lag_periods"] >= 3
        assert M["initiatives"][x["initiative_id"]]["training"]["substituted_for_adoption"] is False
    assert Fraction(M["summary"]["training_completion"]) > Fraction(M["summary"]["adoption_rate"]) + Fraction(1, 5)


# ------------------------------------------------------------------------------------------------------------------------------ injections
def test_twelve_injections_map_to_the_twelve_adversarial_tests(built):
    inj = built["inj"]
    assert sorted(inj) == [f"INJ-{n:02d}" for n in range(1, 13)]
    for n in range(1, 13):
        i = inj[f"INJ-{n:02d}"]
        assert i["test"] == f"P09-TEST-{n:02d}" and i["location"] in ("dataset", "replay", "both")
        assert i["defect"] and i["expected_handling"] and i["name"] and i["events"] == [f"EV-{n:02d}"] and built["events"][f"EV-{n:02d}"]["injection"] == i["id"]
        assert i["checks"] or i["expected_rejections"]
    assert built["inj_doc"]["dataset_version"] == VERSION and built["inj_doc"]["seed"] == SEED


def test_every_dataset_check_equals_the_domains_reading(built):
    doc = {"metrics": built["result"].metrics, "ingest": {"counts": built["result"].counts, "rejected_records": []}}
    n = 0
    for i in built["inj"].values():
        for c in i["checks"]:
            assert gen.lookup(doc, c["path"]) == c["equals"], (i["id"], c["path"])
            n += 1
    assert n > 60


def test_expected_handling_per_defect_in_the_data(built):
    M, R = metrics_of(built), built["rows"]
    sc = M["scenarios"]["scn-025"]
    # 01: hours stay out of the cash flow and no derived cash item exists for the capacity-only initiative
    assert sc["initiatives"]["init-009"]["converted_capacity"] == [] and all(r["cash_benefits"] == "0.00" for r in sc["initiatives"]["init-009"]["cash_flow"])
    # 02: see DR-02. 03: the converted rate is a declared six-place assumption and the annual rate is never applied raw
    s1 = M["scenarios"]["scn-001"]
    conv = next(a for a in R["assumption_versions"] if a["assumption_id"] == s1["rate_source"].split(":")[1])
    assert s1["rate_basis"] == "annual" and s1["declared_rate"] == "0.080000" and s1["effective_period_rate"] == conv["value"] == "0.006434"
    for s in R["scenario_versions"]:
        out = M["scenarios"][s["scenario_id"]]
        assert (s["rate_basis"] == "monthly") == (out["rate_source"] == "declared")
    assert abs((1 + Fraction(conv["value"])) ** 12 - Fraction(108, 100)) < Fraction(2, 10 ** 5)          # the declared monthly rate is the twelfth root of 1.08 to six places
    # 04: no benefit before deployment; the ramp sits beside the unramped plan
    dep = {i["initiative_id"]: i["deployment_period"] for i in R["initiatives"]}
    assert all(b["starts_period"] >= dep[b["initiative_id"]] for b in R["benefit_items"])
    blk = sc["initiatives"]["init-001"]
    assert blk["ramp"]["values"] and blk["unramped_net_cash_flow"] and Fraction(blk["planned_money_benefits"]["unramped"]) > Fraction(blk["planned_money_benefits"]["ramped"])
    # 05: training and adoption are two numbers
    ini = M["initiatives"]["init-003"]
    assert Fraction(ini["training"]["training_completion"]) > Fraction(9, 10) > Fraction(1, 2) > Fraction(ini["adoption"]["adoption_rate"])
    assert ini["training"]["differs_from_adoption"] is True and ini["training"]["substituted_for_adoption"] is False
    # 06: the original forecast is untouched; 07: acyclic; 08: see DR-03; 09: see DR-05
    assert ini["forecast"]["original_preserved"] is True
    feas = M["initiatives"]
    assert all(v["roadmap"]["dependency_feasible_start"] >= v["roadmap"]["requested_start"] for v in feas.values()) and any(v["roadmap"]["dependency_delay"] > 0 for v in feas.values())
    # 10: observed, not attributed beside the raw change
    cash = sc["initiatives"]["init-008"]["benefit_realization"]["cash"]
    assert cash["attribution"] == "observed, not attributed" and cash["baseline_trend"] is not None and cash["observed_above_trend"] is not None
    # 11: no one-time cost repeats; recurring costs carry a half-open range
    keys = [(c["initiative_id"], c["cost_key"], c["cost_basis"]) for c in R["cost_items"] if c["cost_type"] == "one_time"]
    assert len(keys) == len(set(keys)) and all(c["start_period"] < c["end_period"] for c in R["cost_items"] if c["cost_type"] == "recurring")
    # 12: avoided cost enters only when realised with evidence; the rest is beside the cash flow
    entering = {b["benefit_id"] for b in R["benefit_items"] if b["benefit_type"] == "avoided_cost" and b["cash_realisation"] and b["evidence_ref"]}
    assert entering and any(b["benefit_type"] == "avoided_cost" and b["cash_realisation"] and not b["evidence_ref"] for b in R["benefit_items"])
    assert any(b["benefit_type"] == "avoided_cost" and b["cash_realisation"] is False for b in R["benefit_items"])
    assert sc["initiatives"]["init-003"]["excluded_from_cash_flow"]["avoided_cost_beside"][0]["reason"] == "NO_EVIDENCE_REF"
    assert sc["initiatives"]["init-002"]["excluded_from_cash_flow"]["avoided_cost_beside"][0]["reason"] == "NOT_CASH_REALISED"
    assert sc["initiatives"]["init-001"]["excluded_from_cash_flow"]["avoided_cost_beside"] == []
    assert any(r["benefits_by_class"]["avoided_cost_realised"] != "0.00" for r in sc["initiatives"]["init-001"]["cash_flow"])


def fresh_validator(built) -> Validator:
    return Validator(validate_batch(copy.deepcopy(built["inputs"])).population)


@pytest.mark.parametrize("ev", [f"EV-{n:02d}" for n in range(1, 13)])
def test_replayed_rows_are_handled_as_the_manifest_says(built, ev):
    """Each ingest step through the domain's validator on the loaded world: a refused row has exactly the recorded code and details, an accepted one is accepted."""
    event = built["events"][ev]
    v = fresh_validator(built)
    before = {e: len(v.acc[e]) for e in DOMAIN_ENTITIES}
    steps = [s for s in event["steps"] if s["kind"] == "ingest"]
    accepted = {e: 0 for e in DOMAIN_ENTITIES}
    for s in steps:
        rej = v.add(s["entity"], copy.deepcopy(s["row"]))
        if s["expected"] == "rejected":
            assert rej is not None and rej.reason_code == s["reason_code"] and rej.details == s["details"], (ev, s["row"])
        else:
            assert rej is None, (ev, s["row"], rej and rej.reason_code)
            accepted[s["entity"]] += 1
    after = {e: len(v.acc[e]) for e in DOMAIN_ENTITIES}
    assert after == {e: before[e] + accepted[e] for e in DOMAIN_ENTITIES}                 # a refusal changes nothing else
    listed = [r for i in built["inj"].values() for r in i["expected_rejections"] if i["id"] == event["injection"]]
    refused = [s for s in steps if s["expected"] == "rejected"]
    assert [(r["entity"], r["reason_code"], r["details"]) for r in listed] == [(s["entity"], s["reason_code"], s["details"]) for s in refused]


def test_recoveries_change_the_figures_as_the_contract_says(built):
    # 01: after a conversion assumption with a staffing evidence reference, the hours become a separate derived cash item
    v = fresh_validator(built)
    for s in built["events"]["EV-01"]["steps"]:
        if s["kind"] == "ingest":
            v.add(s["entity"], copy.deepcopy(s["row"]))
    res = run_pipeline({**built["inputs"], **{e: v.acc[e] for e in DOMAIN_ENTITIES}})
    blk = res.metrics["scenarios"]["scn-025"]["initiatives"]["init-009"]
    item = next(c for c in blk["converted_capacity"] if c["source_benefit_id"] == "b-inj-01b")
    assert item["hourly_rate"] == "31.50" and item["conversion_assumption_id"] == "a-inj-01-rate" and Fraction(item["amount"]) > 0
    assert abs(Fraction(item["amount"]) - Fraction(item["hours"]) * Fraction("31.5")) <= Fraction(1, 5)              # hours (shown to 2 places, ramped) x rate
    assert all(c["staffing_change_evidence_ref"] == "ev:hr-headcount-plan-complaints-2026" for c in blk["converted_capacity"])
    assert any(r["benefits_by_class"]["capacity_converted"] != "0.00" for r in blk["cash_flow"])        # a separate derived cash item, not the hours itself
    # 09: the moved allocation is accepted and the specialist is still never overallocated
    v = fresh_validator(built)
    for s in built["events"]["EV-09"]["steps"]:
        if s["kind"] == "ingest":
            v.add(s["entity"], copy.deepcopy(s["row"]))
    res = run_pipeline({**built["inputs"], **{e: v.acc[e] for e in DOMAIN_ENTITIES}})
    assert res.metrics["resources"]["res-03"]["overallocated_periods"] == [] and res.metrics["resources"]["res-03"]["by_period"][-1]["period_index"] == 18
    # 08: a 120-period horizon does not create a payback
    v = fresh_validator(built)
    for s in built["events"]["EV-08"]["steps"]:
        if s["kind"] == "ingest":
            v.add(s["entity"], copy.deepcopy(s["row"]))
    res = run_pipeline({**built["inputs"], **{e: v.acc[e] for e in DOMAIN_ENTITIES}})
    assert res.metrics["scenarios"]["scn-inj-08"]["initiatives"]["init-015"]["payback"]["simple"]["period"] is None


def test_the_replay_events_name_records_that_exist(built):
    ids = {e: {r[ID_FIELD[e]] for r in rows} for e, rows in built["rows"].items()}
    flat = set().union(*ids.values())
    flat |= {s["scenario_id"] for s in built["rows"]["scenario_versions"]}
    for ev in built["events"].values():
        for need in ev["requires"]:
            assert need in flat, (ev["event_id"], need)
        assert ev["steps"]
        for s in ev["steps"]:
            assert s["kind"] in ("ingest", "command", "read")
            if s["kind"] == "ingest":
                assert s["row"][ID_FIELD[s["entity"]]] not in ids[s["entity"]], "a replay row must not be in the world"
            if s["kind"] == "command":
                assert s["input"]["dataset_version"] == VERSION and s["expected_status"] in (200, 409, 422)


# ------------------------------------------------------------------------------------------------------------------------------ the database and the API
from support_db import client, command, conn, current_dataset_version, db_url, get, load, rule_ids  # noqa: E402,F401


@pytest.fixture
def seeded(client, conn, built):
    res = load(conn, copy.deepcopy(built["inputs"]), dataset_version=VERSION, dataset_hash=built["manifest"]["dataset_hash"])
    return res


def test_the_seeder_loads_the_whole_world(seeded, built, conn):
    assert seeded["skipped"] == 0 and seeded["dataset_version"] == VERSION
    assert seeded["inserted"] == {e: len(built["rows"][e]) for e in DOMAIN_ENTITIES}, seeded["warnings"]
    assert not seeded["warnings"]
    n = conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"]
    assert n == 0


def test_the_api_serves_the_manifests_figures(seeded, client, built):
    r = get(client, "/metrics", as_of=AS_OF)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["metrics"] == json.loads(json.dumps(built["result"].metrics)) and data["period_basis"] == "monthly" and data["ingest"]["counts"] == built["result"].counts


@pytest.mark.parametrize("ev", [f"EV-{n:02d}" for n in range(1, 13)])
def test_replayed_commands_and_reads_through_the_api(seeded, client, conn, built, ev):
    for s in built["events"][ev]["steps"]:
        if s["kind"] == "command":
            body = s["input"]
            r = client.post(f"/api/v1/changeworks/commands/{s['command']}", json=body, headers=s["headers"])
            assert r.status_code == s["expected_status"], (ev, s["command"], r.status_code, r.text[:600])
            if "expected_reason" in s:
                assert s["expected_reason"] in rule_ids(r), (ev, r.text[:600])
        elif s["kind"] == "read":
            r = get(client, s["path"], **s["params"])
            assert r.status_code == s["expected_status"], r.text[:400]
            doc = r.json()["data"]
            for c in s["expect"]:
                assert gen.lookup(doc, c["path"]) == c["equals"], (ev, c["path"])


def test_a_proposal_is_never_funded(seeded, client):
    r = command(client, "select-scenario", {"scenario_id": "scn-001", "status": "funded"})
    assert r.status_code == 422 and "STATUS_NOT_ALLOWED" in rule_ids(r)
