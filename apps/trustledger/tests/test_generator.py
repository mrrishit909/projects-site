"""Synthetic data generator: determinism, shapes, sizes, spec ranges, designed relationships, injected defects.

The generator (data/generate.py) is stdlib only and shares no code with the domain; these tests run the domain over its output
(ingest, the twelve metrics, the issue classes, the matching block, the verification layer) to show that every designed
relationship and every injected defect is detectable and handled as the injection manifest says, and, when DATABASE_URL is set, that
data/seed.py loads the dataset, data/sql/reference_metrics.sql agrees with the domain at the as-of and at two earlier instants (key by
key, with match precision read from a truth table that only this test loads) and every replay-only event behaves as recorded
through the FastAPI TestClient.
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
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("tl_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["tl_generate"] = gen
_spec.loader.exec_module(gen)

from trustledger import run_pipeline  # noqa: E402
from trustledger.contract import ENTITIES as DOMAIN_ENTITIES, METRIC_KEYS  # noqa: E402
from trustledger.models import SPECS  # noqa: E402
from trustledger.timeutil import parse_ts, scheduled_occurrence  # noqa: E402

SEED = 20261026
VERSION = f"tl-{SEED}-20261026"
GOLDEN = ROOT / "tests" / "fixtures" / "golden"
BUDGET = 5_000_000
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
PROP6 = re.compile(r"^[01]\.\d{6}$")
AS_OF = "2026-10-05T00:00:00Z"
FILES = gen.ENTITIES


def _no_float(text: str):
    def refuse(x):
        raise AssertionError(f"a float literal ({x}) in the output")
    return json.loads(text, parse_float=refuse)


def _strip(manifest: dict) -> dict:
    return {k: v for k, v in manifest.items() if k != "generated_at"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen")
    out, meta = tmp / "out", tmp / "meta"
    manifest = gen.write_all(SEED, out, meta)
    rows = {}
    for name in FILES:
        text = (out / f"{name}.json").read_text()
        doc = _no_float(text)
        assert list(doc) == ["entity", "dataset_version", "rows"] and doc["entity"] == name and doc["dataset_version"] == VERSION
        rows[name] = doc["rows"]
    man = _no_float((out / "manifest.json").read_text())
    inj_doc = _no_float((meta / "injection-manifest.json").read_text())
    events = _no_float((meta / "injection-events.json").read_text())
    return {"out": out, "meta": meta, "manifest": man, "rows": rows, "inj_doc": inj_doc, "inj": {i["id"]: i for i in inj_doc["injections"]},
            "dr": {d["id"]: d for d in inj_doc["designed_relationships"]}, "events": {e["event_id"]: e for e in events["events"]}}


def make_inputs(built) -> dict:
    m = built["manifest"]
    inp = copy.deepcopy(m["config"])
    for k in DOMAIN_ENTITIES:
        inp[k] = copy.deepcopy(built["rows"][k])
    grouped: dict[str, list] = {}
    for r in built["rows"]["dataset_rows"]:
        r = dict(r)
        grouped.setdefault(r.pop("dataset_id"), []).append(r)
    inp["dataset_rows"] = grouped
    inp["weight_versions"] = copy.deepcopy(built["rows"]["weight_versions"])
    inp["quality_rule_versions"] = copy.deepcopy(built["rows"]["quality_rule_versions"])
    return inp


@pytest.fixture(scope="module")
def inputs(built):
    return make_inputs(built)


@pytest.fixture(scope="module")
def truth(built):
    return built["manifest"]["synthetic_truth"]["true_entity"]


@pytest.fixture(scope="module")
def result(inputs, truth):
    return run_pipeline(inputs, truth=truth)


@pytest.fixture(scope="module")
def golden_shape(result):
    return result.golden()


def get(obj, path: str):
    for k in path.split("."):
        obj = obj[k]
    return obj


def check(shape: dict, c: dict) -> None:
    v = get(shape, c["path"])
    if "length" in c:
        assert len(v) == c["length"], c
    else:
        assert v == c["equals"], c


# --- determinism, files, size, manifest ----------------------------------------------------------------------------------
def test_deterministic_across_runs_and_hash_seeds(built, tmp_path):
    again = gen.write_all(SEED, tmp_path / "out", tmp_path / "meta")
    assert again["dataset_hash"] == built["manifest"]["dataset_hash"] and _strip(again) == _strip(built["manifest"])
    for name in FILES:
        assert (tmp_path / "out" / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes()
    for f in ("injection-events.json", "injection-manifest.json"):
        assert (tmp_path / "meta" / f).read_bytes() == (built["meta"] / f).read_bytes()
    assert gen.write_all(SEED + 1, tmp_path / "o2", tmp_path / "m2")["dataset_hash"] != built["manifest"]["dataset_hash"]
    for hs in ("0", "1", "2"):
        out, meta = tmp_path / f"h{hs}" / "out", tmp_path / f"h{hs}" / "meta"
        subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--seed", str(SEED), "--out", str(out), "--data-dir", str(meta)],
                       check=True, capture_output=True, env={**os.environ, "PYTHONHASHSEED": hs})
        for name in FILES:
            assert (out / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), (hs, name)
        for f in ("injection-events.json", "injection-manifest.json"):
            assert (meta / f).read_bytes() == (built["meta"] / f).read_bytes()
        assert _strip(json.loads((out / "manifest.json").read_text())) == _strip(built["manifest"])


def test_committed_snapshot_equals_generator_output(built):
    pub = ROOT / "web" / "public" / "data"
    for name in FILES:
        assert (pub / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), name
    assert _strip(json.loads((pub / "manifest.json").read_text())) == _strip(built["manifest"])
    for f in ("injection-manifest.json", "injection-events.json"):
        assert (ROOT / "data" / f).read_bytes() == (built["meta"] / f).read_bytes(), f
    assert (pub / "injection-manifest.json").read_bytes() == (built["meta"] / "injection-manifest.json").read_bytes()
    for p in sorted((built["out"] / "golden").iterdir()):
        assert (pub / "golden" / p.name).read_bytes() == p.read_bytes() or p.name == "manifest.json", p.name
    assert _strip(json.loads((pub / "golden" / "manifest.json").read_text())) == _strip(json.loads((built["out"] / "golden" / "manifest.json").read_text()))


def test_total_size_is_under_the_cap_and_the_hash_follows_the_spec(built):
    pub = ROOT / "web" / "public" / "data"
    total = sum(p.stat().st_size for p in pub.rglob("*.json"))
    assert total < BUDGET, total
    assert built["manifest"]["generator"]["parameters"]["size_cap_binding"] == "false"
    h = hashlib.sha256()
    for name in sorted(FILES):
        h.update(json.dumps(built["rows"][name], sort_keys=True, separators=(",", ":")).encode())
    m = built["manifest"]
    assert h.hexdigest() == m["dataset_hash"] == built["inj_doc"]["dataset_hash"]
    assert m["dataset_version"] == VERSION and m["contract_version"] == "v1" and m["generator"]["seed"] == SEED
    assert STAMP.match(m["generated_at"]) and m["as_of"] == AS_OF
    assert m["row_counts"] == {n: len(built["rows"][n]) for n in FILES}
    assert set(m) >= {"designed_relationships", "injection_manifest", "stats", "synthetic_truth", "generator", "row_counts", "config"}
    assert all(isinstance(v, str) for v in m["generator"]["parameters"].values())


def test_field_names_equal_the_fixture_and_the_domain_specs(built):
    golden = json.loads((GOLDEN / "inputs.json").read_text())
    for name in DOMAIN_ENTITIES:
        want = set(golden[name][0])
        assert want == {n for n, _ in SPECS[name][1]}, name
        assert all(set(r) == want for r in built["rows"][name]), name
    assert gen.shape_check(SEED) == 0
    for name in ("datasets",):
        assert {"refresh_local_time", "refresh_grace_minutes", "monitored", "last_refreshed_at"} <= set(built["rows"][name][0])
    drow = built["rows"]["dataset_rows"][0]
    assert "dataset_id" in drow and "row_id" in drow
    assert set(built["rows"]["weight_versions"][0]) == {"weight_version", "valid_from", "weights"}


def test_formats_no_float_no_truth_in_entity_files_and_synthetic_details(built):
    stamp_keys = {"registered_at", "last_refreshed_at", "disabled_at", "run_at", "detected_at", "due_at", "closed_at", "observed_at", "valid_from",
                  "changed_at", "proposed_at", "decided_at", "deactivated_at"}
    for name in FILES:
        for r in built["rows"][name]:
            for k, v in r.items():
                if k in stamp_keys and v is not None:
                    assert STAMP.match(v), (name, k, v)
                if name != "dataset_rows":
                    assert not isinstance(v, float)
    for c in built["rows"]["match_candidates"]:
        assert PROP6.match(c["score"]) and all(PROP6.match(v) for v in c["features"].values())
    truth_ids = set(built["manifest"]["synthetic_truth"]["true_entity"].values())
    for name in FILES:
        text = (built["out"] / f"{name}.json").read_text()
        assert "true_entity" not in text and "synthetic_truth" not in text, name
        for e in list(truth_ids)[:20]:
            assert f'"{e}"' not in text, (name, e)
    mails = [v for r in built["rows"]["dataset_rows"] for v in r.values() if isinstance(v, str) and "@" in v]
    assert mails and all(v.split("@")[-1] in ("example.com", "example.org", "example.net", "nodot", "example.c") or v.count("@") != 1 for v in mails)
    names = {c["normalized_name"] for c in built["rows"]["customer_records"]}
    assert len(names) > 1000
    assert "true_entity" in built["manifest"]["synthetic_truth"] and built["manifest"]["synthetic_truth"]["entities"] == len(set(truth_ids))


# --- spec ranges ----------------------------------------------------------------------------------------------------------
def test_counts_are_within_the_specification(built, result):
    r = built["rows"]
    assert len(r["datasets"]) == 40 and len({d["source_system"] for d in r["datasets"]}) == 6 and len(r["fields"]) == 420
    assert len(r["owners"]) == 18 and sum(1 for o in r["owners"] if not o["active"]) == 3
    assert len({m["metric_id"] for m in r["metric_versions"]}) == 30 and len(r["metric_versions"]) == 45 and len(r["definition_changes"]) == 15
    assert all(m["status"] in ("published", "superseded") for m in r["metric_versions"])
    assert len(r["quality_rules"]) == 60 and {q["rule_type"] for q in r["quality_rules"]} == set(gen.DIMS)
    assert [w["weight_version"] for w in r["weight_versions"]] == ["w1", "w2"] and r["weight_versions"][1]["valid_from"] == "2026-09-01T00:00:00Z"
    for w in r["weight_versions"]:
        assert sum(Fraction(v) for v in w["weights"].values()) == 1
    runs = r["rule_runs"]
    assert 4300 <= len(runs) <= 4700
    days = sorted({x["run_at"][:10] for x in runs if x["kind"] == "scheduled"})
    assert days[0] == "2026-07-13" and days[-1] == "2026-10-04" and max(x["run_at"] for x in runs) < AS_OF
    assert 540 <= len(r["issues"]) <= 660
    e = {t: sum(1 for x in r["lineage_edges"] if x["evidence_type"] == t) for t in ("declared", "observed", "inferred")}
    assert e == {"declared": 80, "observed": 70, "inferred": 10}
    lc = result.metrics["lineage_coverage"]
    assert len(lc["undeclared_observed"]) == 12 and lc["observed_distinct"] == 70 and lc["declared_edges"] == 80
    assert len(r["customer_records"]) == 2000 and len({c["source_system"] for c in r["customer_records"]}) == 3
    assert len(r["match_candidates"]) == 400
    reviewed = {d["candidate_id"] for d in r["merge_decisions"] if d["decision"] != "reverse"}
    assert len(reviewed) == 220 and sum(1 for d in r["merge_decisions"] if d["decision"] == "reverse") == 15
    assert sum(len(v) for v in make_inputs(built)["dataset_rows"].values()) == len(r["dataset_rows"])


def test_every_candidate_is_canonical_and_stored_once(built):
    seen = set()
    for c in built["rows"]["match_candidates"]:
        assert c["left_record_id"] < c["right_record_id"]
        assert (c["left_record_id"], c["right_record_id"]) not in seen
        seen.add((c["left_record_id"], c["right_record_id"]))
    recs = {c["record_id"]: c for c in built["rows"]["customer_records"]}
    for c in built["rows"]["match_candidates"]:
        a, b = recs[c["left_record_id"]], recs[c["right_record_id"]]
        assert a["source_system"] != b["source_system"]
        shared = a["normalized_name"] == b["normalized_name"] and a["address_key"] == b["address_key"]
        assert bool(c["uncertainty"]) == shared
    assert len(seen) == 400


# --- the domain over the world ---------------------------------------------------------------------------------------------
def test_the_pipeline_rejects_exactly_what_the_manifest_lists(built, result):
    listed = sorted((r["entity"], r["id"], r["reason_code"]) for i in built["inj"].values() for r in i["expected_rejections"])
    got = sorted((r["entity"], r["id"], r["reason_code"]) for r in result.rejected)
    assert got == listed == []
    for name in DOMAIN_ENTITIES:
        assert result.counts[name] == {"accepted": len(built["rows"][name]), "rejected": 0}, name
    assert result.counts["dataset_rows"]["accepted"] == len(built["rows"]["dataset_rows"])
    assert not result.empty_population


def test_stored_counts_agree_with_the_rows_the_domain_measures(built, result):
    """D-07: at the as-of the row-level measurement is authoritative and the last scheduled run of every active rule stores the same
    counts; the one exception is the INJ-12 rule, whose last run is version 1 and whose current version filters the rows."""
    last = {}
    for r in built["rows"]["rule_runs"]:
        if r["kind"] == "scheduled":
            last[r["rule_id"]] = r
    inj12 = [c["path"].split(".")[2] for c in built["inj"]["INJ-12"]["checks"]][0]
    runs = result.computation.rules["runs"]
    assert len(runs) == 55
    for rid, cur in runs.items():
        got = (cur["eligible_count"], cur["failure_count"])
        stored = (last[rid]["eligible_count"], last[rid]["failure_count"])
        if rid == inj12:
            assert got != stored and last[rid]["rule_version"] == 1
        else:
            assert got == stored, rid
            assert last[rid]["rule_version"] == cur["rule_version"]
    assert last
    for r in built["rows"]["rule_runs"]:
        assert 0 <= r["failure_count"] <= r["eligible_count"]
        assert r["weight_version"] == ("w2" if r["run_at"] >= "2026-09-01T00:00:00Z" else "w1")


def test_designed_near_perfect_dataset_with_an_open_critical_key_failure(built, result):
    ws = result.metrics["weighted_score"]["datasets"]["ds-customers"]
    assert Fraction(ws["value"]) > Fraction("0.95") and ws["critical_override"] is True
    assert Fraction(result.metrics["weighted_score"]["by_weight_version"]["w1"]["ds-customers"]) > Fraction("0.95")
    assert ws["critical_failures"] == 2 and ws["critical_open_issues"] == 1
    assert result.metrics["critical_failures"] == {"failures": 2, "open_issues": 1, "datasets_overridden": 1, "carried": []}
    rule = next(q for q in built["rows"]["quality_rules"] if q["rule_id"] == "r-customers-unique-customer_key")
    assert rule["severity"] == "critical" and rule["rule_type"] == "uniqueness"
    assert built["dr"]["DR-01"]["realised"]["weighted_score_w2"] == ws["value"]


def test_designed_inactive_owners_leave_five_datasets_uncovered(built, result):
    cov = result.metrics["ownership_coverage"]
    assert len(cov["uncovered"]) == 5 and cov["covered"] == 35 and cov["value"] == "0.875000"
    inactive = {o["owner_id"] for o in built["rows"]["owners"] if not o["active"]}
    owner = {d["dataset_id"]: d["owner_id"] for d in built["rows"]["datasets"]}
    assert {owner[d] for d in cov["uncovered"]} <= inactive and len({owner[d] for d in cov["uncovered"]}) == 3
    assert built["dr"]["DR-02"]["realised"]["uncovered"] == cov["uncovered"]


def test_designed_weight_change_moves_scores_without_a_rule_change(built, result):
    by = result.metrics["weighted_score"]["by_weight_version"]
    moved = [d for d in by["w1"] if by["w1"][d] is not None and by["w1"][d] != by["w2"][d]]
    assert len(moved) >= 10 and len(moved) == built["dr"]["DR-03"]["realised"]["datasets_with_different_score"]
    assert result.metrics["weighted_score"]["datasets"]["ds-orders"]["value"] == by["w2"]["ds-orders"]
    res_w1 = run_pipeline(make_inputs(built), weight_version="w1")                       # same rows, same rules, other version
    assert {d: v["value"] for d, v in res_w1.metrics["weighted_score"]["datasets"].items()} == by["w1"]
    assert res_w1.metrics["completeness"] == result.metrics["completeness"] and res_w1.metrics["uniqueness"] == result.metrics["uniqueness"]
    first = {}
    for r in sorted(built["rows"]["rule_runs"], key=lambda r: r["run_at"]):
        if r["kind"] == "scheduled" and first.get(r["rule_id"]) != r["rule_version"]:
            if r["rule_id"] in first:
                assert not ("2026-08-18" <= r["run_at"][:10] <= "2026-09-15"), r        # no rule changed within a fortnight of 2026-09-01
            first[r["rule_id"]] = r["rule_version"]
    assert abs(Fraction(built["dr"]["DR-03"]["realised"]["mean_score_w1"]) - Fraction(built["dr"]["DR-03"]["realised"]["mean_score_w2"])) > 0


def _resolution_by_team(built, result):
    team = {o["owner_id"]: o["team"] for o in built["rows"]["owners"]}
    owner = {i["issue_id"]: i["owner_id"] for i in built["rows"]["issues"]}
    out = {"fast": [], "other": []}
    for iid, v in result.metrics["resolution_time"]["issues"].items():
        if v["class"] == "resolved":
            out["fast" if team[owner[iid]] == gen.FAST_TEAM else "other"].append(Fraction(v["resolution_hours"]))
    return out


def test_designed_one_team_resolves_twice_as_fast(built, result):
    t = _resolution_by_team(built, result)
    assert len(t["fast"]) >= 50 and len(t["other"]) >= 100
    fast, other = sum(t["fast"]) / len(t["fast"]), sum(t["other"]) / len(t["other"])
    assert fast < other / 2
    r = built["dr"]["DR-04"]["realised"]
    assert r["fast_resolved"] == len(t["fast"]) and r["other_resolved"] == len(t["other"])
    assert abs(Fraction(r["fast_mean_hours"]) - fast) < Fraction(1, 1000) and abs(Fraction(r["other_mean_hours"]) - other) < Fraction(1, 1000)


def test_designed_the_oldest_unresolved_issues_are_all_claimed(built, result):
    views = result.metrics["resolution_time"]["issues"]
    det = {i["issue_id"]: i["detected_at"] for i in built["rows"]["issues"]}
    unresolved = sorted((det[i], i) for i, v in views.items() if v["class"] != "resolved")
    assert len(unresolved) > 100
    assert all(views[i]["class"] == "claimed" for _, i in unresolved[:25])
    lead = 0
    for _, i in unresolved:
        if views[i]["class"] != "claimed":
            break
        lead += 1
    assert lead == built["dr"]["DR-05"]["realised"]["leading_claimed_run"] and lead >= 25
    rt = result.metrics["resolution_time"]
    assert rt["resolved_count"] > 250 and rt["claimed_count"] > 50 and rt["open_count"] > 50 and rt["reopened_count"] >= 5


def test_the_manifest_realised_numbers_equal_the_domain(built, result):
    m = result.metrics
    ms = built["dr"]["DR-06"]["realised"]
    p = m["match_precision"]
    assert (p["approved_decisions"], p["approved_correct"], p["precision"], p["reviewed"], p["reviewed_correct_share"]) == \
        (ms["approved"], ms["approved_correct"], ms["precision"], ms["reviewed"], ms["reviewed_correct_share"])
    assert m["lineage_coverage"]["value"] == "0.725000" and m["definition_coverage"]["published_metrics"] == 30
    assert len(m["definition_coverage"]["incomplete"]) == 7 and set(m["definition_coverage"]["incomplete"]) == set(built["manifest"]["stats"]["definitions_incomplete"])
    st = built["manifest"]["stats"]["issues"]
    assert {k: m["resolution_time"][k + "_count"] for k in ("resolved", "claimed", "open")} == st["by_class"]
    assert m["resolution_time"]["reopened_count"] == st["reopened"]
    sc = {d: v for d, v in m["weighted_score"]["datasets"].items() if v["value"] is not None}
    assert len(sc) == built["dr"]["DR-03"]["realised"]["datasets_scored"]
    mean = lambda vs: sum(vs, Fraction(0)) / len(vs)  # noqa: E731
    assert gen.p6(mean([Fraction(v["value"]) for v in sc.values()])) is not None
    on = sum(1 for v in m["timeliness"]["datasets"].values() if v["on_time"])
    stats = built["manifest"]["stats"]
    assert (on, m["timeliness"]["monitored_datasets"]) == (stats["timeliness_on_time"], stats["timeliness_monitored"])


def test_timeliness_uses_the_zones_and_the_fixed_offsets_are_right(built, result):
    from zoneinfo import ZoneInfo
    for zone, minutes in gen.OFFSET_MIN.items():
        for d in ("2026-07-13", "2026-10-04", "2026-10-05"):
            t = datetime.fromisoformat(d + "T12:00:00").replace(tzinfo=ZoneInfo(zone))
            assert t.utcoffset() == timedelta(minutes=minutes), (zone, d)
    ds = {d["dataset_id"]: d for d in built["rows"]["datasets"]}
    for dsid, v in result.metrics["timeliness"]["datasets"].items():
        d = ds[dsid]
        s, dl = scheduled_occurrence(d["refresh_timezone"], d["refresh_local_time"], d["refresh_grace_minutes"], parse_ts(AS_OF))
        assert gen.evaluated_occurrence(d["refresh_timezone"], d["refresh_local_time"], d["refresh_grace_minutes"]) == (s, dl)
        assert v["on_time"] == (s <= parse_ts(d["last_refreshed_at"]) < dl)
    assert any(not v["on_time"] for v in result.metrics["timeliness"]["datasets"].values())
    assert result.metrics["timeliness"]["datasets"]["ds-customers"]["on_time"]


def test_dimensions_are_measured_and_labelled_separately(result):
    m = result.metrics
    v = next(iter(m["validity"].values()))
    assert {"all_eligible", "populated_only"} <= set(v) and v["all_eligible"]["label"] == "validity_all_eligible"
    u = next(iter(m["uniqueness"].values()))
    assert u["group_share"]["label"] == "duplicate_group_share" and u["row_share"]["label"] == "duplicate_row_share"
    assert any(c["whitespace_only_count"] > 0 for c in m["completeness"].values())
    assert sum(r["null_fk_count"] for r in m["relationship_integrity"].values()) >= 20


# --- every injected defect --------------------------------------------------------------------------------------------------
def test_injection_manifest_has_one_record_per_test_and_each_is_handled_as_recorded(built, golden_shape, inputs):
    inj = built["inj"]
    assert sorted(inj) == [f"INJ-{i:02d}" for i in range(1, 13)]
    assert [inj[f"INJ-{i:02d}"]["test"] for i in range(1, 13)] == [f"P07-TEST-{i:02d}" for i in range(1, 13)]
    keys = {"owners": "owner_id", "datasets": "dataset_id", "fields": "field_id", "quality_rules": "rule_id", "rule_runs": "rule_run_id", "issues": "issue_id",
            "lineage_edges": "edge_id", "metric_versions": "metric_version_id", "definition_changes": "change_id", "customer_records": "record_id",
            "match_candidates": "candidate_id", "merge_decisions": "merge_id", "weight_versions": "weight_version"}
    for i in inj.values():
        assert i["expected_handling"] and i["name"] and i["location"] in ("in_file", "replay", "both")
        assert i["events"] and all(e in built["events"] for e in i["events"])
        for rec in i["records"]:
            assert rec["id"] in {r[keys[rec["entity"]]] for r in built["rows"][rec["entity"]]}, rec
        for c in i["checks"]:
            check(golden_shape, c)
    assert sorted(built["events"]) == [f"EV-{i:02d}" for i in range(1, 13)]
    assert {e["injection"] for e in built["events"].values()} == set(inj)


def test_inj03_household_candidates_are_never_merged_automatically(built, truth):
    cands = {c["candidate_id"]: c for c in built["rows"]["match_candidates"]}
    hh = [r["id"] for r in built["inj"]["INJ-03"]["records"]]
    assert len(hh) == 25
    for cid in hh:
        c = cands[cid]
        assert c["uncertainty"] == "Shared name and address; possible household"
        assert truth[c["left_record_id"]] != truth[c["right_record_id"]]
    dec = {d["candidate_id"] for d in built["rows"]["merge_decisions"]}
    decisions = [d for d in built["rows"]["merge_decisions"] if d["candidate_id"] in hh]
    assert all(d["reviewer_id"] != cands[d["candidate_id"]]["proposed_by"] for d in decisions) and len(dec) >= 220


def test_inj06_reversals_restore_both_identities(built, result):
    ident = result.computation.matching["identity_map"]
    hist = result.computation.matching["mapping_history"]
    reversed_ = [h for h in hist if h["state"] == "reversed"]
    assert len(reversed_) == 15
    for h in reversed_:
        assert ident[h["from_record_id"]] == h["from_record_id"] and ident[h["to_record_id"]] == h["to_record_id"] and h["reversed_by"]
    assert all(ident[h["from_record_id"]] == h["to_record_id"] for h in hist if h["state"] == "active")


def test_inj04_nulls_never_enter_the_denominator(built, result):
    rid = "r-orders-fk-customer_key"
    b = result.metrics["relationship_integrity"][rid]
    assert b["null_fk_count"] >= 5 and b["eligible_count"] == b["total_fk_count"] - b["null_fk_count"]
    assert b["matched_count"] + b["unmatched_count"] == b["eligible_count"]


def test_inj12_the_two_runs_are_not_comparable_and_the_others_are(result, built):
    comps = result.computation.rules["comparisons"]
    bad = [r for r, c in comps.items() if not c["comparable"]]
    assert len(bad) == 1 and comps[bad[0]]["reason"] == "RULE_VERSION_DIFFERS" and comps[bad[0]]["failure_rate_current"] is None
    multi = [q for q in built["rows"]["quality_rules"] if q["version_number"] > 1]
    assert len(multi) == 14 and any(q["version_number"] == 3 for q in multi)
    assert all(comps[q["rule_id"]]["comparable"] for q in multi if q["rule_id"] != bad[0] and q["status"] == "active" and q["rule_id"] in comps)


def test_disabled_rules_keep_their_history(built, result):
    dis = [q for q in built["rows"]["quality_rules"] if q["status"] == "disabled"]
    assert len(dis) == 5 and all(q["disabled_reason"] and q["disabled_at"] for q in dis)
    block = result.computation.rules["disabled"]
    assert sorted(block) == sorted(q["rule_id"] for q in dis)
    assert all(v["runs_retained"] > 5 for v in block.values()) and sum(v["issues_retained"] for v in block.values()) > 0


def test_world_hygiene_owners_times_and_references(built):
    r = built["rows"]
    owners = {o["owner_id"]: o for o in r["owners"]}
    assert all(d["owner_id"] in owners and d["classification"] for d in r["datasets"])
    for d in r["datasets"]:
        if d["monitored"]:
            assert d["refresh_timezone"] and d["refresh_local_time"] and d["refresh_grace_minutes"] is not None
    for i in r["issues"]:
        assert i["owner_id"] in owners
    for dec in r["merge_decisions"]:
        assert owners[dec["reviewer_id"]]["role"] in ("steward", "admin") and owners[dec["reviewer_id"]]["active"]
    assert max(x["run_at"] for x in r["rule_runs"]) < AS_OF and max(d["decided_at"] for d in r["merge_decisions"]) < AS_OF
    assert len({row["row_id"] for row in r["dataset_rows"] if row["dataset_id"] == "ds-customers"}) == 120


# --- the database: seeding, the SQL reference, the replay events -----------------------------------------------------------
DB = os.environ.get("DATABASE_URL")


def _load(conn, inputs, truth):
    import psycopg  # noqa: F401
    from data import seed
    with conn.transaction():
        out = seed.seed(conn, inputs, dataset_version=VERSION)
    return out


def _truth_load(conn, truth):
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO verification_truth VALUES (%s, %s) ON CONFLICT DO NOTHING", sorted(truth.items()))


try:
    from support_db import client, conn, db_url  # noqa: E402,F401
except Exception:  # pragma: no cover
    pass


def test_seed_loads_the_world_and_the_sql_reference_equals_the_domain(conn, inputs, truth, built):
    out = _load(conn, inputs, truth)
    assert out["skipped"] == 0 and out["dataset_version"] == VERSION
    for name in DOMAIN_ENTITIES:
        assert out["inserted"][name] == len(built["rows"][name]), name
    assert out["inserted"]["dataset_rows"] == len(built["rows"]["dataset_rows"])
    assert conn.execute("SELECT count(*) AS n FROM verification_truth").fetchone()["n"] == 0        # the seeder never loads the truth
    sql = (ROOT / "data" / "sql" / "reference_metrics.sql").read_text()
    p0 = run_pipeline(inputs)
    assert p0.metrics["match_precision"]["precision"] is None                                      # no truth: unknown, never 0
    _truth_load(conn, truth)
    for as_of in (AS_OF, "2026-09-14T00:00:00Z", "2026-08-17T00:00:00Z"):
        res = run_pipeline(inputs, as_of=as_of, truth=truth)
        row = conn.execute(sql, {"as_of": parse_ts(as_of), "wv": None}).fetchone()
        diffs = [k for k in METRIC_KEYS if row[k] != res.metrics[k]]
        assert not diffs, (as_of, diffs)
        assert row["empty_population"] == res.empty_population
    row = conn.execute(sql, {"as_of": parse_ts(AS_OF), "wv": None}).fetchone()
    assert row["match_precision"]["precision"] == built["dr"]["DR-06"]["realised"]["precision"]
    assert row["weighted_score"]["datasets"]["ds-customers"]["critical_override"] is True


def _subset(want, got, path=""):
    if isinstance(want, dict):
        for k, v in want.items():
            assert k in got, f"{path}.{k} missing in {got}"
            _subset(v, got[k], f"{path}.{k}")
    else:
        assert want == got, f"{path}: {want!r} != {got!r}"


def _fill(obj, vals):
    if isinstance(obj, dict):
        return {k: _fill(v, vals) for k, v in obj.items()}
    if isinstance(obj, str) and obj.startswith("$") and obj[1:] in vals:
        return vals[obj[1:]]
    return obj


def test_every_replay_event_behaves_as_recorded(client, conn, inputs, truth, built):
    import psycopg
    from api.app import PREFIX
    _load(conn, inputs, truth)
    _truth_load(conn, truth)
    log = []
    for ev in [built["events"][k] for k in sorted(built["events"])]:
        responses: list = []
        for n, s in enumerate(ev["steps"]):
            tag = (ev["event_id"], n)
            if s["kind"] == "command":
                vals = {b["into"]: get(responses[b["from_step"]], b["path"]) for b in s.get("bind", [])}
                body = _fill(s["input"], vals)
                resp = client.post(f"{PREFIX}/commands/{s['command']}", json=body, headers=s["headers"])
                js = resp.json()
                responses.append(js)
                assert resp.status_code == s["expected_status"], (tag, resp.status_code, js)
                if "expected_reason" in s:
                    assert js["error"]["details"][0]["rule_id"] == s["expected_reason"], (tag, js)
                if "expected_result" in s:
                    _subset(s["expected_result"], js, str(tag))
                if "expected_warning_codes" in s:
                    assert [w["code"] for w in js["warnings"]] == s["expected_warning_codes"], (tag, js["warnings"])
            elif s["kind"] == "database":
                row = s["row"]
                cols = ", ".join(row)
                try:
                    conn.execute(f"INSERT INTO {s['table']} ({cols}) VALUES ({', '.join(['%s'] * len(row))})", list(row.values()))
                    assert "expected_error" not in s, tag
                except psycopg.errors.CheckViolation as e:
                    assert e.diag.constraint_name == s.get("expected_error"), (tag, e)
                responses.append({})
            else:
                resp = client.get(f"{PREFIX}{s['path']}", params=s["params"])
                assert resp.status_code == 200, (tag, resp.text)
                data = resp.json()["data"]
                responses.append(data)
                for c in s["expect"]:
                    check(data, c)
            log.append(tag)
    assert len(log) == sum(len(e["steps"]) for e in built["events"].values()) == 30
    # the audit trail kept the refused decisions
    refused = conn.execute("SELECT count(*) AS n FROM audit_events WHERE action LIKE '%%-refused'").fetchone()["n"]
    assert refused >= 2
