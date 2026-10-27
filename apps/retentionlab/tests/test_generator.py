"""RetentionLab synthetic data generator (P10-WORK-03): determinism, size, shapes, designed relationships, injected defects.

The generator (data/generate.py) simulates the world and hands every result to the domain; these tests repeat the domain's work from the
PUBLISHED files only (ingest, split, metrics, refusals) and compare it with what the manifest claims, regenerate the whole 2,400-account
world once to check the population-level numbers the published sample cannot show, and, when DATABASE_URL is set, seed the database
with the published cohort and replay every injection event through the FastAPI TestClient.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT, ROOT / "data", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import generate as gen  # noqa: E402
from retentionlab import errors as E  # noqa: E402
from retentionlab.contract import FEATURES, MODELS  # noqa: E402
from retentionlab.ingest import validate  # noqa: E402
from retentionlab.metrics import average_precision, psi  # noqa: E402
from retentionlab.numbers import canon, p6, pp2, rnd, sha256_hex  # noqa: E402
from retentionlab.rules import check_feature_request  # noqa: E402
from retentionlab.split import split_run  # noqa: E402
from retentionlab.timeutil import parse_ts  # noqa: E402
from retentionlab.world import World  # noqa: E402
from support_db import client, conn, db_url  # noqa: E402,F401  (fixtures; db_url is the fixture client and conn depend on)

SEED = 20261026
VERSION = f"rl-{SEED}-20261026"
DATA = ROOT / "web" / "public" / "data"
EVENTS_COPY = ROOT / "data" / "injection-events.json"
BUDGET = 5_000_000
AS_OF = "2026-10-05T00:00:00Z"
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
ANY_STAMP = re.compile(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d")
ENTITIES = gen.ENTITIES
EVENT_ENTITIES = gen.EVENT_ENTITIES


def no_float(text: str) -> Any:
    def refuse(x: str) -> None:
        raise AssertionError(f"a float literal ({x}) in the output")
    return json.loads(text, parse_float=refuse)


def read(name: str) -> Any:
    return no_float((DATA / name).read_text())


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return read("manifest.json")


@pytest.fixture(scope="module")
def files() -> dict[str, Any]:
    """Every published entity file as rows, the compact table as its dict, the analytic files as objects."""
    out: dict[str, Any] = {n: read(f"{n}.json")["rows"] for n in ENTITIES}
    t = read("test_cohort.json")
    out["test_cohort"] = {**t["head"], "rows": t["rows"]}
    for n in ("cutoff_aggregates", "calibration", "split_summary"):
        out[n] = read(f"{n}.json")
    return out


@pytest.fixture(scope="module")
def inputs(manifest: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    cfg = manifest["config"]
    d = {"contract_version": 1, "as_of": manifest["as_of"], "label_version": cfg["label_version"], "feature_version_spec": cfg["feature_version_spec"]}
    d.update({n: files[n] for n in ENTITIES})
    return d


@pytest.fixture(scope="module")
def built() -> dict[str, Any]:
    """The whole 2,400-account world, rebuilt in memory (about 25 seconds): the population numbers the published sample cannot show."""
    return gen.build_all(SEED)


def model_view(inputs: dict[str, Any], model: str) -> dict[str, Any]:
    return {**inputs, "predictions": [p for p in inputs["predictions"] if p["model_name"] == model],
            "scoring_publications": [p for p in inputs["scoring_publications"] if p["model_name"] == model]}


def cohort_world(inputs: dict[str, Any]) -> tuple[World, Any]:
    ing = validate(inputs)
    return World(inputs, ing.accepted), ing


# ---------------------------------------------------------------------------------------------------- determinism and size
def run_generator(out: Path, data_dir: Path, hashseed: str) -> None:
    env = {**os.environ, "PYTHONHASHSEED": hashseed}
    subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--seed", str(SEED), "--out", str(out), "--data-dir", str(data_dir)], check=True,
                   capture_output=True, env=env, cwd=ROOT)


def test_two_runs_are_byte_identical_and_equal_to_the_committed_files(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run_generator(a / "out", a / "data", "0")
    run_generator(b / "out", b / "data", "1")
    names = sorted(p.name for p in (a / "out").glob("*.json"))
    assert names == sorted(p.name for p in (b / "out").glob("*.json")) == sorted(p.name for p in DATA.glob("*.json"))
    for n in names:
        first = (a / "out" / n).read_bytes()
        assert first == (b / "out" / n).read_bytes(), n
        assert first == (DATA / n).read_bytes(), f"{n}: the committed file is not what the generator writes"
    assert (a / "data" / "injection-events.json").read_bytes() == (b / "data" / "injection-events.json").read_bytes() == EVENTS_COPY.read_bytes()


def test_the_published_data_is_under_five_megabytes_and_the_cap_is_declared(manifest):
    total = sum(p.stat().st_size for p in DATA.glob("*.json"))
    assert total < BUDGET and total < 4_800_000, total
    assert manifest["stats"]["size_cap_bytes"] == BUDGET
    assert manifest["stats"]["data_file_bytes_without_manifest"] == total - (DATA / "manifest.json").stat().st_size


def test_no_float_and_every_instant_is_utc_with_z():
    bad: list[str] = []

    def walk(x: Any, where: str) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{where}[{i}]")
        elif isinstance(x, str) and ANY_STAMP.match(x) and not STAMP.match(x):
            bad.append(f"{where}={x}")
    for p in sorted(DATA.glob("*.json")) + [EVENTS_COPY]:
        walk(no_float(p.read_text()), p.name)
    assert not bad, bad[:5]


def test_manifest_fields_and_hash(manifest, files):
    assert manifest["dataset_version"] == VERSION and manifest["generated_at"] == manifest["as_of"] == AS_OF
    assert manifest["generator"]["seed"] == SEED and manifest["injection_manifest"] == "injection-manifest.json"
    assert {"dataset_version", "dataset_hash", "generated_at", "as_of", "row_counts", "designed_relationships", "generator", "disclosures", "injection_manifest",
            "synthetic_truth", "published_cohort", "population", "training", "config", "stats"} <= set(manifest)
    assert manifest["row_counts"] == {**{n: len(files[n]) for n in ENTITIES}, "test_cohort": len(files["test_cohort"]["rows"]), "cutoff_aggregates": len(files["cutoff_aggregates"]["cutoffs"])}
    h = hashlib.sha256()
    for k in sorted({**{n: 0 for n in ENTITIES}, "test_cohort": 0, "cutoff_aggregates": 0, "calibration": 0, "split_summary": 0}):
        h.update(canon(files[k]).encode())
    assert h.hexdigest() == manifest["dataset_hash"]
    for n in ENTITIES:
        assert read(f"{n}.json")["dataset_version"] == VERSION
    assert manifest["generator"]["parameters"]["size_cap_bytes"] == str(BUDGET) and len(manifest["disclosures"]) >= 8
    assert all(d["id"].startswith("D-G") and d["text"] for d in manifest["disclosures"])


def test_the_specified_sizes_and_calendar(manifest, built):
    pop = manifest["population"]
    assert pop["accounts"] == 2400 and sum(pop["by_segment"].values()) == 2400 and len(pop["by_segment"]) == 4 and len(pop["by_region"]) == 5
    cfg = manifest["config"]
    assert cfg["cutoffs"][0] == "2025-01-01T00:00:00Z" and cfg["cutoffs"][-1] == "2026-09-01T00:00:00Z" and len(cfg["cutoffs"]) == 21
    assert cfg["label_version"]["horizon_days"] == 90 and cfg["label_version"]["grace_days"] == 14
    assert cfg["immature_cutoffs"] == ["2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"]
    created = sorted(a["created"] for a in built["pop"]["accounts"])
    assert created[0].strftime("%Y-%m") == "2024-01" and created[-1].strftime("%Y-%m") == "2026-06"
    tr = manifest["training"]
    assert (tr["train_end"], tr["validation_end"], tr["test_end"]) == ("2025-10-01T00:00:00Z", "2026-02-01T00:00:00Z", "2026-06-01T00:00:00Z")


# ---------------------------------------------------------------------------------------------------- the domain over the published rows
def test_the_domain_ingests_the_published_world_with_the_manifests_counts(manifest, inputs):
    claims = manifest["published_cohort"]["claims"]
    ing = validate(inputs)
    counts = ing.counts()
    for m in MODELS:                                  # per model: the domain keys a prediction by (run, cutoff), so one model's predictions at a time
        view = validate(model_view(inputs, m))
        assert claims[m]["ingest"] == view.counts(), m
        assert claims[m]["rejected_records"] == view.rejected == ing.rejected
    assert counts["labels"]["rejected"] == gen.INJ07_EXAMPLES and counts["predictions"]["accepted"] == len(inputs["predictions"])
    assert all(r["reason_code"] == E.CENSORED_LABEL and r["entity"] == "labels" and r["id"].startswith("lb-inj-") for r in ing.rejected)
    for e in ENTITIES:
        want = len(inputs[e]) - counts[e]["rejected"]
        assert counts[e]["accepted"] == want, e
    assert all(a["synthetic"] is True for a in inputs["accounts"])


def test_the_domain_metrics_on_the_published_rows_equal_the_manifests_claims(manifest, inputs):
    claims = manifest["published_cohort"]["claims"]
    assert gen.cohort_claims(inputs) == claims
    for m in MODELS:
        c = claims[m]
        assert all(not v for v in c["consistency"].values()), (m, c["consistency"])
        assert all(status == "completed" and e == s for e, s, status in c["publications"].values())
        assert c["freshness"]["scoring_hours"] == 812 and c["freshness"]["data_hours"] is not None
    eco = manifest["published_cohort"]["economics"]
    world, _ = cohort_world(inputs)
    wl = gen.with_predictions(world, {"predictions": inputs["predictions"], "training_runs": inputs["training_runs"],
                                      "intervention_scenarios": inputs["intervention_scenarios"]}, "logistic_regression")
    from retentionlab.metrics import set_metrics
    for s in inputs["intervention_scenarios"]:
        sm = set_metrics(wl, "tr-001", manifest["published_cohort"]["queue_prediction_at"], s["scenario_id"], None)
        assert sm["economics"]["expected_value"] == eco[s["scenario_id"]]["expected_value"] and sm["economics"]["contact_budget"] == eco[s["scenario_id"]]["contact_budget"]
        assert sm["outreach_queue"]["account_ids"] == manifest["published_cohort"]["queue_account_ids"][s["scenario_id"]]
        assert sorted(o["account_id"] for o in inputs["outreach_events"] if o["scenario_id"] == s["scenario_id"]) == sorted(sm["outreach_queue"]["account_ids"])
        assert eco[s["scenario_id"]]["label"] == "hypothetical" and eco[s["scenario_id"]]["treatment_effect_estimate"] is None
    assert all(o["status"] == "draft" for o in inputs["outreach_events"])


def test_every_prediction_cites_the_run_and_probabilities_are_frozen_six_place_strings(inputs):
    run = inputs["training_runs"][0]
    assert run["config_hash"] == sha256_hex(canon(run["config"]))
    assert {p["model_name"] for p in inputs["predictions"]} == set(MODELS)
    for p in inputs["predictions"]:
        assert p["config_hash"] == run["config_hash"] and p["feature_version"] == "fv-1" and p["label_version"] == "lv-1"
        assert re.fullmatch(r"[01]\.\d{6}", p["probability"])
        assert parse_ts(p["scored_at"]) > parse_ts(next(c["prediction_at"] for c in inputs["prediction_cutoffs"] if c["cutoff_id"] == p["cutoff_id"]))
    cal = run["config"]["calibration"]
    assert cal["method"] == "platt" and re.fullmatch(r"-?\d+\.\d{6}", cal["a"]) and re.fullmatch(r"-?\d+\.\d{6}", cal["b"])
    assert [m["name"] for m in run["config"]["models"]] == list(MODELS)
    # every eligible cutoff of a published range has all three predictions
    world, _ = cohort_world(inputs)
    have = {(p["cutoff_id"], p["model_name"]) for p in inputs["predictions"]}
    for c in inputs["prediction_cutoffs"]:
        if parse_ts(c["prediction_at"]) >= gen.PUBLISH_FROM and world.analyse(c["cutoff_id"])["eligible"]:
            assert all((c["cutoff_id"], m) in have for m in MODELS)


def test_available_at_is_never_before_event_at_and_late_arrival_is_declared(inputs, manifest, built):
    for e in EVENT_ENTITIES:
        assert all(parse_ts(r["available_at"]) >= parse_ts(r["event_at"]) and parse_ts(r["available_at"]) <= parse_ts(AS_OF) for r in inputs[e]), e
    declared = manifest["generator"]["parameters"]["late_arrival"]
    assert json.loads(declared) == {e: {"ppm": v[0], "days": list(v[1])} for e, v in gen.LATE.items()}
    late = manifest["designed_relationships"][3]["realised"]["realised"]
    for e, v in gen.LATE.items():
        realised = Fraction(late[e]["share"])
        assert abs(realised - Fraction(v[0], 1_000_000)) < Fraction(2, 100), (e, realised)        # the realised share is near the declared one
    ents = built["ents"]
    assert sum(1 for s in ents["subscription_events"] if parse_ts(s["event_at"]) >= parse_ts(AS_OF)) == 0
    assert all(parse_ts(r["available_at"]) <= parse_ts(AS_OF) for e in EVENT_ENTITIES for r in ents[e])


# ---------------------------------------------------------------------------------------------------- designed relationships
def table_items(t: dict[str, Any], col: str, pick=lambda r: True) -> list[dict[str, Any]]:
    cols = t["columns"]
    ix = {c: i for i, c in enumerate(cols)}
    return [{"p": Fraction(r[ix[col]]), "y": bool(r[ix["churned"]]), "account_id": r[ix["account_id"]], "row": r} for r in t["rows"] if pick(r)]


def ap_brier(items: list[dict[str, Any]]) -> tuple[str, str]:
    items = sorted(items, key=lambda it: (-it["p"], it["account_id"]))
    pos = sum(1 for it in items if it["y"])
    ap, _ = average_precision(items, pos)
    return p6(ap), p6(sum(((it["p"] - (1 if it["y"] else 0)) ** 2 for it in items), Fraction(0)) / len(items))


def test_dr01_the_logistic_model_beats_the_rule_and_the_random_baseline_by_the_stated_margin(manifest, files):
    dr = manifest["designed_relationships"][0]
    t = files["test_cohort"]
    got = {m: ap_brier(table_items(t, c)) for m, c in (("random_baseline", "p_random_baseline"), ("business_rule", "p_business_rule"), ("logistic_regression", "p_logistic_calibrated"))}
    for m, (ap, brier) in got.items():
        assert dr["realised"][m]["average_precision"] == ap and dr["realised"][m]["brier_score"] == brier, m
        assert dr["realised"][m]["n"] == len(t["rows"])
    stated = dr["realised"]["stated_margins"]
    lr, rule, rnd_ = got["logistic_regression"], got["business_rule"], got["random_baseline"]
    assert Fraction(lr[0]) - Fraction(rule[0]) >= Fraction(stated["ap_over_rule"]) and Fraction(lr[0]) - Fraction(rnd_[0]) >= Fraction(stated["ap_over_random"])
    assert Fraction(rule[1]) - Fraction(lr[1]) >= Fraction(stated["brier_under_rule"]) and Fraction(rnd_[1]) - Fraction(lr[1]) >= Fraction(stated["brier_under_random"])
    assert dr["met"] is True and all(dr["realised"]["met"].values())
    assert dr["realised"]["margins"]["ap_over_rule"] == rnd(Fraction(lr[0]) - Fraction(rule[0]), 6)
    # the oracle reference is a ceiling in spirit: it beats the model, and it is stated, never used by a feature
    assert Fraction(manifest["synthetic_truth"]["latent_reference_test"]["average_precision"]) > Fraction(lr[0])


def test_dr02_a_segment_has_a_calibration_gap(manifest, files):
    dr = manifest["designed_relationships"][1]
    t = files["test_cohort"]
    ix = {c: i for i, c in enumerate(t["columns"])}
    seg = {}
    for s in ("starter", "smb", "mid", "enterprise"):
        items = table_items(t, "p_logistic_calibrated", lambda r, s=s: r[ix["segment"]] == s)
        mean = sum((it["p"] for it in items), Fraction(0)) / len(items)
        obs = Fraction(sum(1 for it in items if it["y"]), len(items))
        seg[s] = pp2(mean - obs)
        assert dr["realised"]["by_segment"][s]["gap_pp"] == seg[s] and dr["realised"]["by_segment"][s]["n"] == len(items)
    assert Fraction(seg["starter"]) <= -Fraction("3.00") and dr["met"] is True
    assert max(abs(Fraction(v)) for k, v in seg.items() if k != "starter") < abs(Fraction(seg["starter"]))
    cal = read("calibration.json")
    assert cal["reliability_calibrated"] and sum(b["count"] for b in cal["reliability_calibrated"]) == len(t["rows"])
    assert sum(b["count"] for b in cal["reliability_uncalibrated"]) == len(t["rows"]) and cal["fit_rows"] > 0 and cal["evaluation_rows"] == len(t["rows"])


def test_dr03_a_cohort_drifts_after_2026_03(manifest, files):
    dr = manifest["designed_relationships"][2]
    t = files["test_cohort"]
    ix = {c: i for i, c in enumerate(t["columns"])}
    from retentionlab.contract import DEFAULT_DRIFT
    bins = DEFAULT_DRIFT["bins"]

    def counts(region_is_apac: bool, k: int) -> list[int]:
        from retentionlab.metrics import in_bin
        rows = [r for r in t["rows"] if r[ix["cutoff_index"]] == k and (r[ix["region"]] == "apac") == region_is_apac]
        return [sum(1 for r in rows if in_bin(r[ix["usage_events_30d"]], b)) for b in bins]
    labels = [b["label"] for b in bins]
    for k, key in ((2, "2026-04-01T00:00:00Z"), (3, "2026-05-01T00:00:00Z")):
        a = psi(counts(True, 0), counts(True, k), labels, DEFAULT_DRIFT["floor"])
        o = psi(counts(False, 0), counts(False, k), labels, DEFAULT_DRIFT["floor"])
        e = next(x for x in files["cutoff_aggregates"]["drift"]["by_cutoff"] if x["prediction_at"] == key)
        assert e["apac"]["psi"] == rnd(Fraction(a[0]), 6) and e["other_regions"]["psi"] == rnd(Fraction(o[0]), 6)
    series = {e["prediction_at"]: e for e in files["cutoff_aggregates"]["drift"]["by_cutoff"]}
    for key, e in series.items():
        if key >= "2026-05-01":
            assert e["apac"]["exceeds_threshold"] is True and Fraction(e["apac"]["psi"]) > Fraction("0.2"), key
        if key >= "2026-02-01":
            assert e["other_regions"]["exceeds_threshold"] is False, key
    assert dr["met"] is True and dr["realised"]["region"] == "apac" and dr["realised"]["change_at"] == "2026-03-31T00:00:00Z"
    assert all(e["all_accounts"]["exceeds_threshold"] is False for k, e in series.items() if k >= "2026-02-01"), "the whole population hides the cohort's drift"


def test_dr04_ignoring_available_at_would_flip_features(manifest, built):
    dr = manifest["designed_relationships"][3]
    r = dr["realised"]
    assert dr["met"] is True and built["dr"]["late"]["features_flipped"] == r["features_flipped"] and built["dr"]["late"]["test_rows"] == r["test_rows"]
    assert sum(1 for v in r["features_flipped"].values() if v > 0) >= 3
    assert Fraction(r["share_of_test_rows_changed"]) >= Fraction("0.03") and r["test_rows_with_a_late_event"] >= r["test_rows_features_change_if_ignored"]
    # independent check on the cohort: rebuilding with every event treated as available at event time changes some feature of some published row
    assert r["subscription_events_arriving_after_the_grace"] > 0


def test_dr05_a_sizeable_censored_tail(manifest, files):
    dr = manifest["designed_relationships"][4]
    agg = files["cutoff_aggregates"]["cutoffs"]
    eligible = sum(e["population"]["eligible"] for e in agg)
    censored = sum(e["population"]["censored"] for e in agg)
    assert dr["realised"]["eligible_rows"] == eligible and dr["realised"]["censored_rows"] == censored and dr["realised"]["censored_share"] == p6(Fraction(censored, eligible))
    assert Fraction(censored, eligible) >= Fraction("0.15") and dr["met"] is True
    for e in agg:
        immature = e["prediction_at"] in manifest["config"]["immature_cutoffs"]
        assert (e["population"]["censored"] > 0) == immature and (e["population"]["mature"] == 0) == immature, e["prediction_at"]
        if immature:
            assert e["models"]["logistic_regression"]["n"] == 0 and e["models"]["logistic_regression"]["average_precision"] is None   # no outcome metric on an immature cutoff
            assert e["churn_rate"] is None
    for key, naive in dr["realised"]["churn_rate_if_censored_were_non_churn"].items():
        assert Fraction(naive) < Fraction(dr["realised"]["mature_churn_rate"])


# ---------------------------------------------------------------------------------------------------- split and the purge
def test_the_split_and_its_drop_counts(manifest, files, inputs, built):
    world, _ = cohort_world(inputs)
    rows, counts = split_run(world, inputs["training_runs"][0])
    assert files["split_summary"]["published_cohort"] == counts and files["split_summary"]["population"] == built["fit"]["split_counts"]
    assert {(r["cutoff_id"], r["split"], r["status"], r["drop_reason"]) for r in rows} == {(s["cutoff_id"], s["split"], s["status"], s["drop_reason"]) for s in inputs["split_assignments"]}
    pc = files["split_summary"]["population"]
    assert pc["train"]["label_window"] > 0 and pc["validation"]["label_window"] > 0 and pc["train"]["group_test"] > 0 and pc["train"]["group_validation"] > 0 and pc["validation"]["group_test"] > 0
    assert pc["test"]["label_window"] == pc["test"]["group_test"] == 0 and pc["outside"]["retained"] == pc["outside"]["total"]
    assert files["split_summary"]["embargo_days"] == 104
    # the training run was fitted on the retained, mature training rows of the population and calibrated on the retained validation rows
    tr = manifest["training"]
    assert tr["training_rows"] == built["fit"]["run"]["config"]["preprocessing"]["fit_rows"] == len(built["fit"]["train_ids"])
    assert tr["validation_rows"] == built["fit"]["run"]["config"]["calibration"]["fit_rows"] and tr["training_positives"] > 20 and tr["validation_positives"] > 10


# ---------------------------------------------------------------------------------------------------- injections
def pop_summary_from(manifest: dict[str, Any], inj: dict[str, Any]) -> dict[str, Any]:
    ex = inj["INJ-02"]["facts"]["cohort"]["examples"]
    return {"cohort_set": set(manifest["published_cohort"]["account_ids"]), "violators": manifest["synthetic_truth"]["violators"],
            "inj02": [{"account_id": e["account_id"], "prediction_at": gen.parse_pa(e["cutoff_id"]), "event_at": e["event_at"], "available_at": e["available_at"], "in_cohort": True}
                      for e in ex]}


def test_every_injection_is_present_and_handled_as_the_contract_says(manifest, inputs, built):
    doc = read("injection-manifest.json")
    assert doc["dataset_version"] == VERSION and doc["dataset_hash"] == manifest["dataset_hash"] and doc["events_file"] == "injection-events.json"
    by = {i["id"]: i for i in doc["injections"]}
    assert sorted(by) == [f"INJ-{n:02d}" for n in range(1, 13)]
    assert [by[f"INJ-{n:02d}"]["test"] for n in range(1, 13)] == [f"P10-TEST-{n:02d}" for n in range(1, 13)]
    for i in doc["injections"]:
        assert i["name"] and i["defect"] and i["expected_handling"] and i["records"] and i["checks"] and i["events"], i["id"]
    world, ing = cohort_world(inputs)
    facts = gen.cohort_facts(inputs, world, pop_summary_from(manifest, by))
    for inj in by.values():                                                        # the facts the manifest states are the facts of the published rows
        assert inj["facts"]["cohort"] == json.loads(json.dumps(facts[inj["id"]], sort_keys=True)), inj["id"]
        for c in inj["checks"]:
            src = facts if c["scope"] == "cohort" else built["pfacts"]
            assert gen.resolve(src, c["path"]) == c["equals"], (inj["id"], c)
    # the contract's codes, one by one
    code = lambda k: facts[k]["refusal"]["code"]      # noqa: E731
    assert code("INJ-01") == E.POST_OUTCOME_FIELD and code("INJ-03") == E.LEAKAGE and code("INJ-04") == E.LEAKAGE and code("INJ-05") == E.LEAKAGE
    assert code("INJ-06") == E.THRESHOLD_ON_TEST and code("INJ-08") == E.LATENT_TRUTH and code("INJ-10") == E.CAPACITY_EXCEEDS_POPULATION
    assert code("INJ-11") == E.CALIBRATION_ON_FIT_ROWS and code("INJ-12") == E.LATENT_TRUTH and facts["INJ-12"]["refusal_id_only"]["code"] == E.ID_FEATURE
    assert facts["INJ-12"]["refusal"]["offending"] == [{"item": "generator_seed_bucket", "code": "LATENT_TRUTH"}, {"item": "creation_sequence", "code": "ID_FEATURE"}]
    assert facts["INJ-10"]["refusal"]["offending"][0]["code"] == f"CAPACITY_{facts['INJ-10']['oversize_capacity']}_GT_{facts['INJ-10']['queue_population']}"


def test_inj02_a_late_event_is_counted_as_arrived_late_and_excluded(manifest, inputs):
    doc = read("injection-manifest.json")
    ex = next(i for i in doc["injections"] if i["id"] == "INJ-02")["facts"]["cohort"]["examples"]
    assert len(ex) >= 3
    world, _ = cohort_world(inputs)
    usage = {u["usage_event_id"]: u for u in inputs["usage_events"]}
    for e in ex:
        u = usage[e["usage_event_id"]]
        row = world.analyse(e["cutoff_id"])
        pa = parse_ts(row["prediction_at"])
        assert parse_ts(u["event_at"]) < pa <= parse_ts(u["available_at"])                       # it happened before the cutoff and arrived after it
        assert row["eligible"] and row["arrived_late"]["usage_events"] >= 1 and row["features"]["usage_events_30d"] == 0
        assert row["max_available_at"] is None or parse_ts(row["max_available_at"]) < pa
        stored = next(f for f in inputs["feature_rows"] if f["cutoff_id"] == e["cutoff_id"])
        assert stored["features_json"] == row["features"]
        assert row["features"]["usage_events_30d"] == 0 and row["features"]["high_severity_support_90d"] == 0      # flagged by the rule; counted, it would not be


def test_inj03_and_04_the_purge_removes_what_would_leak(manifest, inputs):
    world, _ = cohort_world(inputs)
    rows, counts = split_run(world, inputs["training_runs"][0])
    assert counts["train"]["group_test"] > 0 and counts["train"]["group_validation"] > 0 and counts["train"]["label_window"] > 0 and counts["validation"]["label_window"] > 0
    seen: dict[int, set[str]] = {}
    for r in rows:
        if r["status"] == "retained" and r["split"] != "outside":
            seen.setdefault(r["account_id"], set()).add(r["split"])
    assert all(len(v) == 1 for v in seen.values())
    viol = {a for v in manifest["synthetic_truth"]["violators"].values() for a in v} & set(manifest["published_cohort"]["account_ids"])
    dropped = {r["account_id"] for r in rows if r["drop_reason"] in ("GROUP_TEST", "GROUP_VALIDATION")}
    assert dropped and dropped <= viol                                                       # only the injected accounts are dropped by the group purge


def test_inj07_immature_rows_are_never_labelled_non_churn(manifest, inputs):
    world, ing = cohort_world(inputs)
    bad = [lb for lb in inputs["labels"] if lb["label_id"].startswith("lb-inj-")]
    assert len(bad) == gen.INJ07_EXAMPLES and all(lb["churned"] is False and lb["mature"] is False for lb in bad)
    assert {r["id"] for r in ing.rejected} == {lb["label_id"] for lb in bad}
    for lb in bad:
        assert world.analyse(lb["cutoff_id"])["mature"] is False and world.analyse(lb["cutoff_id"])["churned"] is None
    for lb in ing.accepted["labels"]:
        a = world.analyse(lb["cutoff_id"])
        assert lb["churned"] == a["churned"] and lb["mature"] == a["mature"] and (a["mature"] or lb["churned"] is None)


def test_inj08_and_12_nothing_latent_or_identifier_derived_is_a_feature(manifest, inputs, files):
    found: list[str] = []

    def walk(x: Any, where: str) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).startswith("latent_") or str(k) in ("latent", "propensity", "churn_propensity"):
                    found.append(f"{where}.{k}")
                walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for v in x:
                walk(v, where)
    for n in ENTITIES:
        walk(files[n], n)
    walk(files["test_cohort"], "test_cohort")
    assert not [f for f in found if not f.startswith("feature_registry")], found
    assert files["test_cohort"]["columns"] == ["account_id", "cutoff_index", "segment", "region", *FEATURES, "churned", "p_random_baseline", "p_business_rule",
                                                "p_logistic_uncalibrated", "p_logistic_calibrated"]
    reg = {r["feature_name"]: r for r in inputs["feature_registry"]}
    usable = [n for n in reg if not (reg[n]["post_outcome"] or reg[n]["latent"] or reg[n]["id_derived"])]
    assert usable == list(FEATURES) and check_feature_request(reg, usable) == usable
    for fr in inputs["feature_rows"]:
        assert set(fr["features_json"]) == set(FEATURES) and fr["feature_version"] == "fv-1"
    cfg = inputs["training_runs"][0]["config"]
    names = {k for m in cfg["models"] if "coefficients" in m for k in m["coefficients"]}
    assert names <= {"intercept", *FEATURES, "billing_total_90d_missing", "days_since_last_usage_missing"}
    # the features are what the events say: the domain rebuilds every stored row from the events alone (no latent value is an input of the rebuild)
    world, ing = cohort_world(inputs)
    for fr in ing.accepted["feature_rows"]:
        a = world.analyse(fr["cutoff_id"])
        assert a["eligible"] and a["features"] == fr["features_json"] and a["max_available_at"] == fr["max_available_at"]
    # the truth lives only in the manifest, and is not what the model predicted
    truth = manifest["synthetic_truth"]
    assert len(truth["latent_churn_propensity_ppm"]) == manifest["population"]["feature_rows"] and all(isinstance(v, int) and 0 <= v <= 1_000_000 for v in truth["latent_churn_propensity_ppm"].values())
    published_probabilities = {p["cutoff_id"]: p["probability"] for p in inputs["predictions"] if p["model_name"] == "logistic_regression"}
    same = sum(1 for c, p in published_probabilities.items() if c in truth["latent_churn_propensity_ppm"] and Fraction(p) * 1_000_000 == truth["latent_churn_propensity_ppm"][c])
    assert same <= len(published_probabilities) // 50
    for p in sorted(DATA.glob("*.json")):
        if p.name not in ("manifest.json", "injection-manifest.json"):
            assert "latent_churn_propensity_ppm" not in p.read_text() and "synthetic_truth" not in p.read_text(), p.name


def test_inj09_and_10_queues_are_drafts_within_the_population_and_hypothetical(manifest, inputs):
    pop = manifest["published_cohort"]["economics"]["sc-001"]["population"]
    assert all(s["capacity"] <= pop for s in inputs["intervention_scenarios"]) and [s["capacity"] for s in inputs["intervention_scenarios"]] == [5, 10, 20]
    assert {o["status"] for o in inputs["outreach_events"]} == {"draft"} and all(o["action"] == "propose_contact" for o in inputs["outreach_events"])
    assert not any("treatment" in k or "uplift" in k or "responsive" in k for s in inputs["intervention_scenarios"] + inputs["outreach_events"] for k in s)
    for s in inputs["intervention_scenarios"]:
        assert 0 <= Fraction(s["assumed_effect"]) <= 1
        assert sum(1 for o in inputs["outreach_events"] if o["scenario_id"] == s["scenario_id"]) == s["capacity"]


def test_inj11_calibration_is_fitted_on_validation_and_evaluated_on_test(manifest, built):
    pf = built["pfacts"]["INJ-11"]
    assert pf["overlap_with_test_rows"] == 0 and pf["all_fit_rows_in_the_validation_range"] and pf["equals_retained_mature_validation_rows"]
    cal = read("calibration.json")
    assert cal["fit_range"].startswith("validation") and cal["evaluation_range"] == "test" and cal["fit_rows"] == pf["calibration_fit_rows"]
    assert built["pfacts"]["INJ-05"]["all_fit_rows_in_the_train_range"] and built["pfacts"]["INJ-05"]["fit_rows_sha256_is_the_retained_train_rows"]


def test_the_events_file_is_the_one_in_the_data_directory_and_every_event_belongs_to_an_injection(manifest):
    ev = read("injection-events.json")
    assert ev == no_float(EVENTS_COPY.read_text()) and ev["dataset_version"] == VERSION and ev["server_clock"] == "2026-10-05T12:00:00Z"
    doc = read("injection-manifest.json")
    ids = {e["event_id"]: e["injection"] for e in ev["events"]}
    assert sorted(set(ids.values())) == [f"INJ-{n:02d}" for n in range(1, 13)]
    for i in doc["injections"]:
        assert sorted(i["events"]) == sorted(e for e, inj in ids.items() if inj == i["id"])
    for e in ev["events"]:
        assert e["steps"] and e["requires"] == ["seed:published-cohort"]
        for s in e["steps"]:
            assert s["kind"] in ("command", "read") and s["expected_status"] in (200, 422)


# ---------------------------------------------------------------------------------------------------- the API replay (needs DATABASE_URL)
def dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        m = re.fullmatch(r"(\w+)?\[(\d+)\]", part)
        if m:
            if m.group(1):
                cur = cur[m.group(1)]
            cur = cur[int(m.group(2))]
        else:
            cur = cur[part]
    return cur


def test_every_injection_event_replays_through_the_api_as_recorded(client, conn, manifest, inputs):  # noqa: F811
    from api import clock
    from api.app import PREFIX
    from support_db import get, load, offending, rule_ids
    ev = read("injection-events.json")
    load(conn, inputs, dataset_version=VERSION)
    clock.freeze(parse_ts(ev["server_clock"]))
    for e in ev["events"]:
        for n, step in enumerate(e["steps"], 1):
            where = f"{e['event_id']} step {n}"
            if step["kind"] == "command":
                r = client.post(f"{PREFIX}/commands/{step['command']}", json=step["input"], headers=step["headers"])
            else:
                r = get(client, step["path"], **step["params"])
            assert r.status_code == step["expected_status"], (where, r.text[:600])
            body = r.json()
            if r.status_code == 422:
                assert rule_ids(r)[: len(step["expected_rules"])] == step["expected_rules"], (where, r.text[:600])
                if "expected_offending" in step:
                    assert offending(r) == step["expected_offending"], (where, offending(r))
                continue
            if step["kind"] == "command":
                for path, want in step.get("expected_result", {}).items():
                    assert dig(body["result"], path) == want, (where, path, dig(body["result"], path), want)
                got = {w["code"] for w in body["warnings"]}
                assert set(step.get("expected_warning_codes", [])) <= got, (where, got)
            else:
                for x in step["expect"]:
                    assert dig(body, x["path"]) == x["equals"], (where, x["path"], dig(body, x["path"]))
