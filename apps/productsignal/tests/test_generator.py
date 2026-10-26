"""Synthetic data generator: determinism, shapes, sizes, spec ranges, designed relationships, injected defects.

The generator (data/generate.py) is stdlib only and shares no code with the domain; these tests run the domain over its output
(ingest, canonical events, identity, funnel, activation, retention, the experiment block, intervals, the sample ratio) to show
that every designed relationship and every injected defect is detectable and handled as the injection manifest says, and, when
DATABASE_URL is set, that data/seed.py loads the dataset, data/sql/reference_metrics.sql agrees with the domain at the as-of and at
earlier cutoffs (key by key), and every replay-only event behaves as recorded through the FastAPI TestClient.
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
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("ps_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["ps_generate"] = gen
_spec.loader.exec_module(gen)

from productsignal import run_pipeline  # noqa: E402
from productsignal.contract import ENTITIES as DOMAIN_ENTITIES, METRIC_KEYS  # noqa: E402
from productsignal.events import canonicalise, late_arrivals  # noqa: E402
from productsignal.metrics import Ctx, activation, group_values, guardrail_review, retention  # noqa: E402
from productsignal.models import parse_plan  # noqa: E402
from productsignal.stats import newcombe, t_crit  # noqa: E402
from productsignal.timeutil import local_date, parse_ts  # noqa: E402

SEED = 20261026
VERSION = f"ps-{SEED}-20261026"
GOLDEN = ROOT / "tests" / "fixtures" / "golden"
BUDGET = 5_000_000
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
MONEY = re.compile(r"^\d+\.\d{2}$")
PROP6 = re.compile(r"^[01]\.\d{6}$")
AS_OF = parse_ts("2026-10-05T00:00:00Z")
XV1, XV2 = "xv-001", "xv-002"
Z = Fraction("1.959964")


def _no_float(text: str):
    def refuse(x):
        raise AssertionError(f"a float literal ({x}) in the output")
    return json.loads(text, parse_float=refuse)


def _strip_generated(manifest: dict) -> dict:
    return {k: v for k, v in manifest.items() if k != "generated_at"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen")
    out, meta = tmp / "out", tmp / "meta"
    manifest = gen.write_all(SEED, out, meta)
    rows = {}
    for name in gen.ENTITIES:
        doc = _no_float((out / f"{name}.json").read_text())
        assert doc["entity"] == name and doc["dataset_version"] == VERSION and list(doc) == ["entity", "dataset_version", "rows"]
        rows[name] = doc["rows"]
    _no_float((out / "manifest.json").read_text())                      # no float literal anywhere in the manifest either
    inj_doc = _no_float((meta / "injection-manifest.json").read_text())
    return {"out": out, "meta": meta, "manifest": manifest, "rows": rows, "inj_doc": inj_doc,
            "inj": {i["id"]: i for i in inj_doc["injections"]},
            "dr": {d["id"]: d for d in inj_doc["designed_relationships"]},
            "events": {e["event_id"]: e for e in _no_float((meta / "injection-events.json").read_text())["events"]}}


def make_inputs(built, xv: str = XV1) -> dict:
    m = built["manifest"]
    return {"contract_version": 1, "as_of": m["as_of"], "cutoff": m["cutoff"], "analysis_plan": copy.deepcopy(m["analysis_plans"][xv]),
            "metric_windows": copy.deepcopy(m["metric_windows"]), **copy.deepcopy(built["rows"])}


@pytest.fixture(scope="module")
def inputs(built):
    return make_inputs(built)


@pytest.fixture(scope="module")
def result(inputs):
    return run_pipeline(inputs)


@pytest.fixture(scope="module")
def result_v2(built):
    return run_pipeline(make_inputs(built, XV2), experiment_version_id=XV2)


def _expected_rejections(built) -> set[tuple[str, str, str]]:
    return {(r["entity"], r["id"], r["reason_code"]) for i in built["inj"].values() for r in i.get("expected_rejections", [])}


# --- determinism, files, manifest -------------------------------------------------------------------------------
def test_deterministic_across_runs_and_hash_seeds(built, tmp_path):
    again = gen.write_all(SEED, tmp_path / "out", tmp_path / "meta")
    assert again["dataset_hash"] == built["manifest"]["dataset_hash"]
    assert _strip_generated(again) == _strip_generated(built["manifest"])
    for name in gen.ENTITIES:
        assert (tmp_path / "out" / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes()
    for f in ("injection-events.json", "injection-manifest.json"):
        assert (tmp_path / "meta" / f).read_bytes() == (built["meta"] / f).read_bytes()
    other = gen.write_all(SEED + 1, tmp_path / "o2", tmp_path / "m2")
    assert other["dataset_hash"] != again["dataset_hash"]
    for hash_seed in ("0", "1", "2"):         # a fresh interpreter per PYTHONHASHSEED: nothing depends on set or dict-of-str order
        out, meta = tmp_path / f"h{hash_seed}", tmp_path / f"hm{hash_seed}"
        proc = subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--seed", str(SEED), "--out", str(out),
                               "--data-dir", str(meta)], capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": hash_seed})
        assert proc.returncode == 0, proc.stderr
        for name in gen.ENTITIES:
            assert (out / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), (hash_seed, name)
        for f in ("injection-events.json", "injection-manifest.json"):
            assert (meta / f).read_bytes() == (built["meta"] / f).read_bytes(), (hash_seed, f)
        assert _strip_generated(json.loads((out / "manifest.json").read_text())) == _strip_generated(built["manifest"])
        assert (out / "golden" / "manifest.json").read_bytes() == (built["out"] / "golden" / "manifest.json").read_bytes()


def test_committed_snapshot_is_the_generator_output(built):
    pub = ROOT / "web" / "public" / "data"
    assert (pub / "events.json").exists(), "web/public/data is not generated: run python data/generate.py"
    for name in gen.ENTITIES:
        assert (pub / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), name
    assert _strip_generated(json.loads((pub / "manifest.json").read_text())) == _strip_generated(built["manifest"])
    assert (pub / "injection-manifest.json").read_bytes() == (built["out"] / "injection-manifest.json").read_bytes()
    assert (ROOT / "data" / "injection-manifest.json").read_bytes() == (built["out"] / "injection-manifest.json").read_bytes()
    assert (ROOT / "data" / "injection-events.json").read_bytes() == (built["meta"] / "injection-events.json").read_bytes()
    for f in sorted((built["out"] / "golden").iterdir()):
        assert (pub / "golden" / f.name).read_bytes() == f.read_bytes(), f.name


def test_manifest_shape_and_hash(built):
    m = built["manifest"]
    assert m["dataset_version"] == VERSION and m["contract_version"] == "v1" and m["as_of"] == "2026-10-05T00:00:00Z"
    assert set(m) >= {"dataset_version", "dataset_hash", "generated_at", "contract_version", "generator", "row_counts",
                      "designed_relationships", "injection_manifest", "stats", "analysis_plans", "metric_windows"}
    assert STAMP.match(m["generated_at"])
    assert m["generator"]["seed"] == SEED and m["generator"]["name"] == "generate.py"
    assert m["generator"]["parameters"]["accounts"] == 600 and "outcome_selection" in m["generator"]["parameters"]
    assert m["row_counts"] == {n: len(built["rows"][n]) for n in gen.ENTITIES}
    assert set(gen.ENTITIES) == set(DOMAIN_ENTITIES)
    h = hashlib.sha256()
    for name in sorted(gen.ENTITIES):
        h.update(json.dumps(built["rows"][name], sort_keys=True, separators=(",", ":")).encode())
    assert h.hexdigest() == m["dataset_hash"] == built["inj_doc"]["dataset_hash"]
    assert [d["id"] for d in m["designed_relationships"]] == [f"DR-0{i}" for i in range(1, 8)]
    assert (built["out"] / "injection-manifest.json").read_bytes() == (built["meta"] / "injection-manifest.json").read_bytes()
    assert {e["injection"] for e in built["events"].values()} <= set(built["inj"])
    for xv, plan in m["analysis_plans"].items():       # the plans are frozen: the hash is the sha256 of the canonical plan
        body = {k: v for k, v in plan.items() if k != "config_hash"}
        assert plan["config_hash"] == hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert parse_plan(plan).hash_valid
    assert m["analysis_plan"] == m["analysis_plans"][XV1]
    runs = {r["analysis_id"]: r for r in built["rows"]["analysis_runs"]}
    assert all(r["config_hash"] == m["analysis_plans"][r["experiment_version_id"]]["config_hash"] for r in runs.values())
    assert all(r["created_at"] >= m["analysis_plans"][r["experiment_version_id"]]["frozen_at"] for r in runs.values())


def test_total_size_is_under_5_mb(built):
    total = sum(p.stat().st_size for p in built["out"].rglob("*") if p.is_file())
    total += sum(p.stat().st_size for p in built["meta"].rglob("*") if p.is_file())
    assert total < BUDGET, total
    pub = ROOT / "web" / "public" / "data"
    committed = sum(p.stat().st_size for p in pub.rglob("*") if p.is_file())
    committed += sum((ROOT / "data" / f).stat().st_size for f in ("injection-manifest.json", "injection-events.json"))
    assert committed < BUDGET, committed


# --- shape of every row ------------------------------------------------------------------------------------------
def test_field_names_equal_the_fixture(built):
    fixture = json.loads((GOLDEN / "inputs.json").read_text())
    for name in gen.ENTITIES:
        want = set(fixture[name][0])
        assert built["rows"][name], name
        for row in built["rows"][name]:
            assert set(row) == want, (name, sorted(set(row) ^ want))
    # D-05's added fields are there
    assert "timezone" in built["rows"]["accounts"][0] and "anonymous_id" in built["rows"]["events"][0]
    assert "amount_usd" in built["rows"]["subscriptions"][0]
    proc = subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--profile", "golden-shape-check"], capture_output=True, text=True)
    assert proc.returncode == 0 and "MISMATCH" not in proc.stdout, proc.stdout


def test_value_formats_and_ranges(built):
    r = built["rows"]
    last = "2026-10-04T23:59:59Z"
    for a in r["accounts"]:
        assert STAMP.match(a["created_at"]) and isinstance(a["internal"], bool) and a["created_at"] <= last
    for u in r["users"]:
        assert STAMP.match(u["created_at"]) and isinstance(u["bot_flag"], bool)
    for s in r["sessions"]:
        assert STAMP.match(s["started_at"]) and STAMP.match(s["ended_at"]) and s["ended_at"] >= s["started_at"] and s["started_at"] <= last
    for e in r["events"]:
        assert STAMP.match(e["event_at"]) and STAMP.match(e["received_at"])
        assert e["received_at"] >= e["event_at"], e                    # a log accepts an event after it happened
        assert e["received_at"] <= "2026-10-05T00:00:00Z" and e["event_at"] <= last
        assert e["event_name"] in {"visit", "signup", "onboarding_step_1", "onboarding_step_2", "onboarding_step_3", "activated",
                                   "feature_used", "product_error"}
    for p in r["event_properties"]:
        assert p["value_type"] == "string" and p["property_key"] in {"feature", "error_code"}
    for s in r["subscriptions"]:
        assert MONEY.match(s["amount_usd"]) and Decimal(s["amount_usd"]) > 0 and STAMP.match(s["starts_at"]) and s["starts_at"] <= last
        assert s["status"] in {"trial", "active", "ended", "refunded"}
        assert s["ends_at"] is None or (STAMP.match(s["ends_at"]) and s["ends_at"] >= s["starts_at"] and s["ends_at"] <= last)
        assert (s["ends_at"] is None) == (s["status"] in {"trial", "active"})
    for l in r["identity_links"]:
        assert STAMP.match(l["linked_at"]) and l["rule_version"] == "v1"
    for a in r["assignments"]:
        assert a["variant"] in {"control", "treatment"} and STAMP.match(a["assigned_at"])
    for x in r["exposures"]:
        assert STAMP.match(x["exposed_at"]) and x["surface"] == "onboarding_checklist"
    for o in r["metric_observations"]:
        assert o["value"] in {"0", "1"} and o["metric_name"] == "activation_7d" and STAMP.match(o["window_end"])
    for plan in built["manifest"]["analysis_plans"].values():
        assert all(PROP6.match(v) for v in plan["allocation"].values()) and sum(Fraction(v) for v in plan["allocation"].values()) == 1
    for name, rows in r.items():
        key = {"accounts": "account_id", "users": "user_id", "identity_links": "identity_link_id", "sessions": "session_id",
               "events": "event_id", "event_properties": "property_id", "subscriptions": "subscription_id",
               "experiment_versions": "experiment_version_id", "assignments": "assignment_id", "exposures": "exposure_id",
               "metric_observations": "observation_id", "analysis_runs": "analysis_id"}[name]
        ids = [x[key] for x in rows]
        assert len(set(ids)) == len(ids) and ids == sorted(ids), name


def test_references_and_identity_links_are_consistent(built):
    r = built["rows"]
    accounts = {a["account_id"]: a for a in r["accounts"]}
    users = {u["user_id"]: u for u in r["users"]}
    assert all(u["account_id"] in accounts and u["timezone"] == accounts[u["account_id"]]["timezone"] for u in users.values())
    assert all(s["user_id"] in users for s in r["sessions"])
    assert all(s["account_id"] in accounts for s in r["subscriptions"])
    asg = {a["assignment_id"]: a for a in r["assignments"]}
    assert all(a["unit_id"] in accounts and not accounts[a["unit_id"]]["internal"] for a in asg.values())       # internal accounts are never randomised
    assert len({(a["experiment_version_id"], a["unit_id"]) for a in asg.values()}) == len(asg)                 # one assignment per unit
    assert all(x["assignment_id"] in asg and x["exposed_at"] >= asg[x["assignment_id"]]["assigned_at"] for x in r["exposures"])
    assert len({x["assignment_id"] for x in r["exposures"]}) == len(r["exposures"])
    assert {o["assignment_id"] for o in r["metric_observations"]} <= set(asg)
    # identity: one link per anonymous id; a link never predates the user it names; the earliest events of the visitor come first
    links = r["identity_links"]
    assert len({l["anonymous_id"] for l in links}) == len(links) and len({l["user_id"] for l in links}) == len(links)
    for l in links:
        assert l["user_id"] in users and l["linked_at"] >= users[l["user_id"]]["created_at"]
    first_visit: dict[str, str] = {}
    for e in r["events"]:
        if e["anonymous_id"] and e["event_name"] == "visit":
            first_visit[e["anonymous_id"]] = min(first_visit.get(e["anonymous_id"], e["event_at"]), e["event_at"])
    assert all(first_visit[l["anonymous_id"]] <= l["linked_at"] for l in links)            # every link follows a visit of that visitor
    event_props = {}
    for p in r["event_properties"]:
        event_props.setdefault(p["event_id"], {})[p["property_key"]] = p["property_value"]
    assert {e["event_id"] for e in r["events"]} >= set(event_props)
    for e in r["events"]:
        if e["event_name"] == "feature_used":
            assert set(event_props[e["event_id"]]) == {"feature"}
        elif e["event_name"] == "product_error":
            assert set(event_props[e["event_id"]]) == {"error_code"}
        else:
            assert e["event_id"] not in event_props


def test_fixed_utc_offsets_equal_the_tz_database(built):
    d = datetime(2026, 4, 6, tzinfo=timezone.utc)
    while d <= AS_OF:
        for tz, hours in gen.OFFSET_H.items():
            assert d.astimezone(ZoneInfo(tz)).utcoffset() == timedelta(hours=hours), (tz, d)
        d += timedelta(hours=6)
    assert set(gen.OFFSET_H) == {a["timezone"] for a in built["rows"]["accounts"]}


def test_counts_within_spec(built):
    r, st = built["rows"], built["manifest"]["stats"]
    acc = r["accounts"]
    assert len(acc) == 600 and {a["plan"] for a in acc} == {"free", "team", "business"} and {a["segment"] for a in acc} == {"smb", "mid", "enterprise"}
    assert len({a["timezone"] for a in acc}) == 3
    assert sum(1 for a in acc if a["internal"]) == 12                                                      # 2 %
    users = r["users"]
    bots = sum(1 for u in users if u["bot_flag"])
    assert 1700 <= len(users) <= 1900 and bots == 18 and 0.009 <= bots / len(users) <= 0.011
    real = len(users) - bots
    linked = len(r["identity_links"])
    assert 0.68 <= linked / real <= 0.72                                                                  # about 70 % of signups linked
    ev = r["events"]
    names = {e["event_name"] for e in ev}
    assert names == {"visit", "signup", "onboarding_step_1", "onboarding_step_2", "onboarding_step_3", "activated", "feature_used", "product_error"}
    delayed = sum(1 for e in ev if parse_ts(e["received_at"]) - parse_ts(e["event_at"]) > timedelta(hours=24))
    assert 0.015 <= delayed / len(ev) <= 0.025, delayed / len(ev)                                         # 2 % delayed over 24 h
    assert Fraction("0.008") <= Fraction(st["duplicate_share"]) <= Fraction("0.012")
    assert any(e["user_id"] is None and e["anonymous_id"] is None for e in ev) and any(e["user_id"] and e["user_id"].startswith("u-ghost") for e in ev)
    subs_accounts = {s["account_id"] for s in r["subscriptions"]}
    assert 0.30 <= len(subs_accounts) / 600 <= 0.40                                                       # about 35 % of accounts
    assert {s["status"] for s in r["subscriptions"]} == {"trial", "active", "ended", "refunded"}
    asg = r["assignments"]
    n1 = sum(1 for a in asg if a["experiment_version_id"] == XV1)
    n2 = sum(1 for a in asg if a["experiment_version_id"] == XV2)
    assert 390 <= n1 <= 410 and 140 <= n2 <= 160, (n1, n2)                                                # about 400 and about 150
    exposed = len(r["exposures"]) / len(asg)
    assert 0.82 <= exposed <= 0.90, exposed                                                               # about 85 %
    assert len(r["analysis_runs"]) == 5 and [x["experiment_version_id"] for x in r["analysis_runs"]] == [XV1] * 4 + [XV2]
    cuts = [x["cutoff_at"] for x in r["analysis_runs"] if x["experiment_version_id"] == XV1]
    planned = built["manifest"]["analysis_plans"][XV1]["planned_end"]
    assert [c < planned for c in cuts] == [True, True, True, False] and cuts[-1] == planned           # three interim runs and one at planned_end
    assert [(e["experiment_version_id"], e["planned_end"]) for e in r["experiment_versions"]] == \
        [(XV1, "2026-08-02T00:00:00Z"), (XV2, "2026-10-04T00:00:00Z")]
    # v1 enrolment ends a week before planned_end, v2's plan was frozen after v1's last run and before its first assignment
    p2 = built["manifest"]["analysis_plans"][XV2]
    assert p2["frozen_at"] > cuts[-1] and p2["frozen_at"] < min(a["assigned_at"] for a in asg if a["experiment_version_id"] == XV2)
    assert built["manifest"]["analysis_plans"][XV1]["frozen_at"] < min(a["assigned_at"] for a in asg)
    assert st["events_total"] == len(ev) and st["bot_users"] == bots
    # the weekly signup profile covers the 26 weeks
    weeks = {(date.fromisoformat(a["created_at"][:10]) - date(2026, 4, 6)).days // 7 for a in acc}
    assert weeks == set(range(26))


def test_golden_copy_for_the_web_app(built):
    g = built["out"] / "golden"
    fixture = json.loads((GOLDEN / "inputs.json").read_text())
    for name in gen.ENTITIES:
        doc = json.loads((g / f"{name}.json").read_text())
        assert doc["entity"] == name and doc["dataset_version"] == "golden-v1" and doc["rows"] == fixture[name]
    man = json.loads((g / "manifest.json").read_text())
    assert man["dataset_version"] == "golden-v1" and man["dataset_hash"] == json.loads((GOLDEN / "HASHES.json").read_text())["sha256"]["inputs.json"]
    assert man["generator"]["seed"] == 0 and man["designed_relationships"] == [] and man["as_of"] == fixture["as_of"]
    assert man["analysis_plan"] == fixture["analysis_plan"] and man["metric_windows"] == fixture["metric_windows"]
    assert man["row_counts"]["accounts"] == 235 and man["row_counts"]["events"] == 529 and man["row_counts"]["assignments"] == 200
    assert json.loads((g / "expected.json").read_text()) == json.loads((GOLDEN / "expected.json").read_text())


# --- the domain on the generated world --------------------------------------------------------------------------
def test_pipeline_rejects_exactly_what_the_manifest_lists(built, result):
    got = {(r["entity"], r["id"], r["reason_code"]) for r in result.rejected}
    assert got == _expected_rejections(built) == set()                    # the clean files carry no ingest rejection
    for name in gen.ENTITIES:
        c = result.ingest.counts[name]
        assert c["rejected"] == 0 and c["accepted"] + c["merged"] == len(built["rows"][name]), name
    assert not result.ingest.merged_assignments and {i["expected_merges"] != [] for i in built["inj"].values()} == {False}
    assert set(result.metrics) == set(METRIC_KEYS)
    assert not result.empty_population


def test_tracking_quality_equals_what_was_generated(built, result):
    tq, st = result.tracking_quality, built["manifest"]["stats"]
    assert tq["rows_total"] == len(built["rows"]["events"]) and tq["received_after_cutoff"] == 0
    assert tq["duplicates_dropped"] == st["duplicates_resent"] == built["inj"]["INJ-05"]["expected"]["duplicates_dropped_at_as_of"]
    assert tq["delayed_over_24h"] == st["delayed_over_24h"]
    assert tq["unknown_identity"] == st["ghost_events"] == 30
    assert tq["canonical"] == tq["rows_total"] - tq["duplicates_dropped"]
    bot_users = {u["user_id"] for u in built["rows"]["users"] if u["bot_flag"]}
    assert tq["bot_events_excluded"] > 100 and tq["internal_events_excluded"] > 50
    assert tq["analysed"] == tq["canonical"] - tq["unknown_identity"] - tq["bot_events_excluded"] - tq["internal_events_excluded"]
    assert result.identity["attributed_by_link"] > 100 and result.identity["remain_anonymous"] > 1000
    assert bot_users and any(l["user_id"] in bot_users for l in built["rows"]["identity_links"])       # a link can attribute to a bot (excluded)


# --- designed relationships (read through the domain, compared with the manifest) -----------------------------------
def test_treatment_lifts_activation_and_the_interval_is_reported(built, result):
    ex = result.metrics["experiment"]
    p = ex["primary"]
    c, t = p["variants"]["control"], p["variants"]["treatment"]
    assert ex["srm"]["verdict"] == "OK" and ex["assigned_units"] == ex["mature_units"] == 400 and ex["immature_or_unobserved_excluded"] == 0
    assert Fraction(t["conversion"]) > Fraction(c["conversion"]) and Decimal(p["absolute_lift_pp"]) > 0 and p["relative_lift"] is not None
    iv = p["interval"]
    assert iv["method"] == "newcombe_hybrid_score" and Fraction(iv["low"]) < Fraction(p["absolute_lift_pp"]) / 100 < Fraction(iv["high"])
    assert p["conclusive"] is (not iv["includes_zero"])                    # conclusive only when the interval excludes 0 (final run, valid plan)
    dr = built["dr"]["DR-01"]["realised"]["at_as_of"]
    assert dr["arms"]["control"]["activated"] == c["activated"] and dr["arms"]["treatment"]["activated"] == t["activated"]
    assert (dr["absolute_lift_pp"], dr["newcombe_95_low"], dr["newcombe_95_high"], dr["interval_includes_zero"]) == \
        (p["absolute_lift_pp"], iv["low"], iv["high"], iv["includes_zero"])
    pe = built["dr"]["DR-01"]["realised"]["at_planned_end"]
    assert pe["cutoff"] == "2026-08-02T00:00:00Z" and pe["arms"]["control"]["mature"] >= 190 and Decimal(pe["absolute_lift_pp"]) > 0
    # the observations agree with the events
    assert ex["observations"]["rows_accepted"] == ex["observations"]["rows_matching_events"] == 400
    # exposure about 85 % in both arms; ITT keeps the unexposed
    assert Fraction("0.80") <= Fraction(ex["exposure"]["overall"]["rate"]) <= Fraction("0.92")
    assert all(Fraction("0.78") <= Fraction(v["rate"]) <= Fraction("0.93") for v in ex["exposure"]["by_variant"].values())


def _arm_accounts(result, xv):
    return group_values(result.population, "variant", xv)


def test_treatment_does_not_lift_week_4_retention(built, result):
    pop = result.population
    w = replace(pop.windows, retention_from=date(2026, 4, 6), retention_to=date(2026, 7, 26))
    canon = canonicalise(pop, AS_OF)
    arms = _arm_accounts(result, XV1)
    r = {v: retention(Ctx(pop, AS_OF, canon, accs), w)["week4"] for v, accs in arms.items()}
    assert all(r[v]["mature_accounts"] == 200 and r[v]["immature_excluded"] == 0 for v in r)
    d, lo, hi = newcombe(r["treatment"]["retained"], r["treatment"]["mature_accounts"], r["control"]["retained"], r["control"]["mature_accounts"], Z)
    assert lo <= 0 <= hi, (lo, hi)                                                                   # no week-4 retention difference
    assert lo > Fraction(-1, 2) and hi < Fraction(1, 2)                                              # the interval is informative, not vacuous
    dr = built["dr"]["DR-02"]["realised"]
    assert dr["week4"]["control"]["retained"] == r["control"]["retained"] and dr["week4"]["treatment"]["retained"] == r["treatment"]["retained"]
    assert dr["interval_includes_zero"] is True
    # while activation is lifted in the same accounts (the retention figure is not a restatement of activation)
    p = result.metrics["experiment"]["primary"]["variants"]
    assert Fraction(p["treatment"]["conversion"]) > Fraction(p["control"]["conversion"])


def test_business_segment_activates_most_and_fastest(built, result):
    pop = result.population
    w = replace(pop.windows, activation_from=parse_ts("2026-04-06T00:00:00Z"), activation_to=AS_OF)
    canon = canonicalise(pop, AS_OF)
    treated = {a.unit_id for a in pop.assignments if a.variant == "treatment"}
    rates: dict[str, dict[str, Fraction]] = {}
    for by in ("plan", "segment"):
        rates[by] = {}
        for value, accs in group_values(pop, by, None).items():
            a = activation(Ctx(pop, AS_OF, canon, accs - treated), w)             # control and unassigned accounts: no treatment effect mixed in
            assert a["mature_accounts"] > 30
            rates[by][value] = Fraction(a["rate"])
    assert max(rates["plan"], key=rates["plan"].get) == "business" and max(rates["segment"], key=rates["segment"].get) == "enterprise"
    assert sorted(rates["plan"].values())[0] < Fraction(1, 4) < rates["plan"]["business"]
    # faster: the median time to activation (of those activated within seven days) is shortest on the business plan
    acc = {a["account_id"]: a for a in built["rows"]["accounts"]}
    users = {u["user_id"]: u for u in built["rows"]["users"]}
    signup: dict[str, str] = {}
    for e in built["rows"]["events"]:
        if e["event_name"] == "signup" and e["user_id"] in users and not users[e["user_id"]]["bot_flag"]:
            a = users[e["user_id"]]["account_id"]
            signup[a] = min(signup.get(a, e["event_at"]), e["event_at"])
    hours: dict[str, list[int]] = {}
    for e in built["rows"]["events"]:
        if e["event_name"] == "activated" and e["user_id"] in users and not users[e["user_id"]]["bot_flag"]:
            a = users[e["user_id"]]["account_id"]
            dt = parse_ts(e["event_at"]) - parse_ts(signup[a])
            if dt < timedelta(days=7) and not acc[a]["internal"] and a not in treated:
                hours.setdefault(acc[a]["plan"], []).append(int(dt.total_seconds()))
    med = {p: sorted(v)[len(v) // 2] for p, v in hours.items()}
    assert min(med, key=med.get) == "business", med
    dr = built["dr"]["DR-03"]["realised"]
    assert max(dr["plan"], key=lambda k: dr["plan"][k]["rate"]) == "business" and min(dr["plan"], key=lambda k: Decimal(dr["plan"][k]["median_hours_to_activate"])) == "business"
    assert {k: Fraction(v["rate"]) for k, v in dr["plan"].items()} == rates["plan"]


def test_guardrail_error_rate_is_equal_across_variants(built, result):
    ex = result.metrics["experiment"]
    plan = result.population.plans[XV1]
    g = guardrail_review(ex, plan)
    assert g["verdict"] == "OK" and g["interval"]["includes_zero"] is True, g
    by = ex["guardrail"]["by_variant"]
    assert by["control"]["eligible_units"] == by["treatment"]["eligible_units"] == 200
    assert 5 <= by["control"]["units_with_error"] and 5 <= by["treatment"]["units_with_error"]        # errors are not so rare that equality is trivial
    dr = built["dr"]["DR-04"]["realised"]
    assert dr["by_variant"]["control"]["units_with_error"] == by["control"]["units_with_error"]
    assert dr["by_variant"]["treatment"]["units_with_error"] == by["treatment"]["units_with_error"] and dr["interval_includes_zero"] is True


def test_revenue_per_assigned_account_is_noisy_and_inconclusive(built, result):
    rev = result.metrics["experiment"]["revenue_per_assigned_account"]["by_variant"]
    assert rev["control"]["units"] == rev["treatment"]["units"] == 200
    # per variant: a t-interval over account-level values (zeros included); the two overlap and the interval is wide
    ci = {v: (Decimal(x["interval"]["low"]), Decimal(x["interval"]["high"]), Decimal(x["mean"])) for v, x in rev.items()}
    assert max(ci["control"][0], ci["treatment"][0]) < min(ci["control"][1], ci["treatment"][1])
    assert all((hi - lo) > Decimal("0.3") * mean for lo, hi, mean in ci.values())
    # the difference of means: Welch interval from the account-level values, standard library only
    plan = result.population.plans[XV1]
    asg = {a.unit_id: a.variant for a in result.population.assignments if a.experiment_version_id == XV1}
    vals: dict[str, dict[str, Decimal]] = {"control": {}, "treatment": {}}
    for u, v in asg.items():
        vals[v][u] = Decimal(0)
    for s in result.population.subscriptions:
        if s.status in ("active", "ended") and plan.revenue_from <= s.starts_at < plan.revenue_to and s.account_id in asg:
            vals[asg[s.account_id]][s.account_id] += s.amount_usd
    stats = {}
    for v, d in vals.items():
        x = list(d.values())
        n = len(x)
        mean = sum(x) / n
        stats[v] = (n, mean, sum((i - mean) ** 2 for i in x) / (n - 1))
    se = (stats["treatment"][2] / stats["treatment"][0] + stats["control"][2] / stats["control"][0]).sqrt()
    diff = stats["treatment"][1] - stats["control"][1]
    assert abs(diff) < Decimal("1.959964") * se, (diff, se)                                              # inconclusive: the difference is within noise
    dr = built["dr"]["DR-05"]["realised"]
    assert dr["interval_includes_zero"] is True and Decimal(dr["difference_of_means"]) == diff.quantize(Decimal("0.01"))
    assert {v: dr["by_variant"][v]["mean"] for v in dr["by_variant"]} == {v: rev[v]["mean"] for v in rev}
    assert t_crit(199) < Decimal("2.0")


def test_v2_has_a_sample_ratio_mismatch_and_v1_does_not(built, result, result_v2):
    s1, s2 = result.metrics["experiment"]["srm"], result_v2.metrics["experiment"]["srm"]
    assert s1["verdict"] == "OK" and s2["verdict"] == "MISMATCH"
    assert Decimal(s2["p_value"]) < Decimal("0.001") and s2["observed"]["treatment"] > s2["observed"]["control"]
    dr = built["dr"]["DR-06"]["realised"]
    assert dr["v1"]["verdict"] == "OK" and dr["v2"]["verdict"] == "MISMATCH"
    for ours, theirs in ((dr["v1"], s1), (dr["v2"], s2)):
        assert (ours["observed"], ours["expected"], ours["statistic"], ours["p_value"]) == \
            (theirs["observed"], theirs["expected"], theirs["statistic"], theirs["p_value"])
    ex2 = result_v2.metrics["experiment"]
    assert ex2["assigned_units"] == len([a for a in built["rows"]["assignments"] if a["experiment_version_id"] == XV2])
    assert ex2["allocation"] == {"control": "0.600000", "treatment": "0.400000"}


# --- the twelve defects --------------------------------------------------------------------------------------------
def test_manifest_lists_the_twelve_defects(built):
    inj = built["inj_doc"]["injections"]
    assert [i["id"] for i in inj] == [f"INJ-{n:02d}" for n in range(1, 13)]
    assert [i["test"] for i in inj] == [f"P06-TEST-{n:02d}" for n in range(1, 13)]
    for i in inj:
        assert i["expected_handling"] and i["description"] and i["record_ids"] and i["handling_kind"]
        assert i["expected_rejections"] == [] and i["expected_merges"] == []
        assert i["location"] in {"entity_files", "events", "entity_files+events"}
        if i["handling_kind"] == "replay_only":
            assert i["replay"] and all(e in built["events"] for e in i["replay"])
    assert {e for i in inj for e in i.get("replay", [])} == set(built["events"])


def test_inj_04_an_immature_cohort_is_excluded_and_counted(built, result, result_v2):
    inj = built["inj"]["INJ-04"]
    a = result.metrics["activation"]
    assert a["immature_excluded"] == inj["expected"]["activation_immature_excluded"] == len(inj["record_ids"]) > 10
    assert a["signups"] == a["immature_excluded"] + a["mature_accounts"] and a["mature_accounts"] > 40
    ex2 = result_v2.metrics["experiment"]
    assert ex2["immature_or_unobserved_excluded"] == inj["expected"]["v2_immature_or_unobserved_excluded"] == len(inj["detail"]["v2_assigned_immature_ids"]) > 5
    assert ex2["mature_units"] == ex2["assigned_units"] - ex2["immature_or_unobserved_excluded"]
    # none of them is counted as activated even when they have an activation event
    mature = {x for x in result.population.accounts if x.account_id in inj["record_ids"]}
    assert all(x.created_at + timedelta(days=7) > AS_OF for x in mature)


def test_inj_05_duplicate_activation_events_are_dropped_and_change_nothing(built, inputs, result):
    inj = built["inj"]["INJ-05"]
    ev = {e["event_id"]: e for e in built["rows"]["events"]}
    props = {}
    for p in built["rows"]["event_properties"]:
        props.setdefault(p["event_id"], {})[p["property_key"]] = p["property_value"]
    assert len(inj["record_ids"]) == 14
    for d in inj["detail"]:
        a, b = ev[d["duplicate_of"]], ev[d["event_id"]]
        assert a["event_name"] == b["event_name"] == "activated" and a["user_id"] == b["user_id"] and a["event_at"] == b["event_at"]
        assert a["event_id"] != b["event_id"] and b["received_at"] > a["received_at"] and props.get(a["event_id"]) == props.get(b["event_id"])
    drop = set(inj["record_ids"])
    clean = copy.deepcopy(inputs)
    clean["events"] = [e for e in clean["events"] if e["event_id"] not in drop]
    r2 = run_pipeline(clean)
    assert r2.tracking_quality["duplicates_dropped"] == result.tracking_quality["duplicates_dropped"] - 14
    for k in METRIC_KEYS:
        assert r2.metrics[k] == result.metrics[k], k                      # an account is activated once: no figure moves


def test_inj_06_a_late_event_changes_a_later_funnel_never_the_published_one(built, inputs, result):
    inj = built["inj"]["INJ-06"]
    late_ids = set(inj["record_ids"])
    cut = parse_ts(inj["detail"]["earlier_cutoff"])
    assert len(late_ids) == 8
    ev = {e["event_id"]: e for e in built["rows"]["events"]}
    assert all(parse_ts(ev[i]["event_at"]) < cut < parse_ts(ev[i]["received_at"]) for i in late_ids)
    assert all(parse_ts(ev[i]["received_at"]) - parse_ts(ev[i]["event_at"]) > timedelta(hours=24) for i in late_ids)
    steps = lambda r: {s["step"]: s["units"] for s in r.metrics["funnel"]["steps"]}        # noqa: E731
    without = copy.deepcopy(inputs)
    without["events"] = [e for e in without["events"] if e["event_id"] not in late_ids]
    base, now = steps(run_pipeline(without)), steps(result)
    assert now["onboarding_step_1"] == base["onboarding_step_1"] + inj["expected"]["funnel_step_1_units_added"]
    assert now["activated"] == base["activated"] + inj["expected"]["funnel_activated_units_added"]
    assert now["signup"] == base["signup"] and now["visit"] == base["visit"]
    # the run at the earlier cutoff does not have them; it is the run at the as-of that differs, as a disclosed revision
    earlier = run_pipeline(inputs, cutoff=cut)
    assert steps(earlier)["onboarding_step_1"] <= base["onboarding_step_1"]
    late = late_arrivals(result.population, cut, AS_OF)
    assert late_ids <= {e.event_id for e in late}
    assert earlier.tracking_quality["received_after_cutoff"] >= 8
    # the published (earlier) result is unchanged by the later arrival: recomputing it at its cutoff gives the same figures
    again = run_pipeline(inputs, cutoff=cut)
    assert again.metrics == earlier.metrics


def test_inj_07_an_identity_link_is_never_applied_backward(built, result):
    inj = built["inj"]["INJ-07"]
    canon = canonicalise(result.population, AS_OF)
    by_id = {a.event.event_id: a for a in canon.analysed}
    links = {l["anonymous_id"]: l for l in built["rows"]["identity_links"]}
    assert len(inj["detail"]["before_link_event_ids"]) >= 30 and len(inj["detail"]["after_link_event_ids"]) == 15
    ev = {e["event_id"]: e for e in built["rows"]["events"]}
    for eid in inj["detail"]["before_link_event_ids"]:                              # before the link: still anonymous
        assert ev[eid]["user_id"] is None and ev[eid]["event_at"] < links[ev[eid]["anonymous_id"]]["linked_at"]
        assert by_id[eid].user is None, eid
    for eid in inj["detail"]["after_link_event_ids"]:                               # after it: attributed to the user the link names
        l = links[ev[eid]["anonymous_id"]]
        assert ev[eid]["user_id"] is None and ev[eid]["event_at"] >= l["linked_at"]
        assert by_id[eid].user == l["user_id"], eid
    assert result.identity["attributed_by_link"] >= 15 and result.identity["remain_anonymous"] >= 30


def test_inj_10_the_instrumentation_gap_gives_zero_control_conversions_early(built, inputs):
    inj = built["inj"]["INJ-10"]
    cut = parse_ts(inj["detail"]["early_cutoff"])
    res = run_pipeline(inputs, cutoff=cut)
    p = res.metrics["experiment"]["primary"]
    c, t = p["variants"]["control"], p["variants"]["treatment"]
    assert c["mature_units"] == inj["detail"]["mature_control"] >= 1 and t["mature_units"] == inj["detail"]["mature_treatment"] >= 1
    assert c["activated"] == 0 and c["conversion"] == "0.000000" and t["activated"] == 0
    assert p["relative_lift"] is None and p["absolute_lift_pp"] == "0.00" and p["conclusive"] is False
    assert res.metrics["experiment"]["run"]["interim"] is True
    assert set(inj["record_ids"]) >= {a.unit_id for a in res.population.assignments if a.unit_id in inj["record_ids"]}
    # the gap accounts have no `activated` event at all, in either arm
    users = {u["user_id"]: u["account_id"] for u in built["rows"]["users"]}
    gap = set(inj["record_ids"])
    assert not [e for e in built["rows"]["events"] if e["event_name"] == "activated" and users.get(e["user_id"]) in gap]


def test_inj_12_exact_day_7_and_the_rolling_definition_are_separate_figures(built, result):
    inj = built["inj"]["INJ-12"]
    pop = result.population
    w = replace(pop.windows, retention_from=date.fromisoformat(inj["detail"]["retention_window"]["signup_from"]),
                retention_to=date.fromisoformat(inj["detail"]["retention_window"]["signup_to"]))
    ret = retention(Ctx(pop, AS_OF, canonicalise(pop, AS_OF), None), w)
    gap = ret["on_or_after_day7"]["retained"] - ret["day7"]["retained"]
    assert ret["day7"]["mature_accounts"] == ret["on_or_after_day7"]["mature_accounts"] > 80
    assert gap >= inj["expected"]["on_or_after_minus_exact_day7_at_least"] == 10, ret
    for a in inj["detail"]["late_returners"]:
        assert 7 not in a["local_day_indices"] and any(d >= 8 for d in a["local_day_indices"])
    accounts = {a.account_id: a for a in pop.accounts}
    users = {u.user_id: u for u in pop.users}
    sess: dict[str, list] = {}
    for s in pop.sessions:
        sess.setdefault(users[s.user_id].account_id, []).append(s.started_at)
    signup = {}
    for a in canonicalise(pop, AS_OF).analysed:
        if a.name == "signup" and a.account:
            signup[a.account] = min(signup.get(a.account, a.at), a.at)
    for a in inj["detail"]["timezone_edge"]:
        acc = accounts[a["account_id"]]
        d0 = local_date(signup[acc.account_id], acc.timezone)
        local_idx = {(local_date(t, acc.timezone) - d0).days for t in sess[acc.account_id]}
        utc_idx = {(t.date() - signup[acc.account_id].date()).days for t in sess[acc.account_id]}
        assert 7 in local_idx and 7 not in utc_idx, a                   # day 7 on the account's calendar only; the UTC date says day 8
        assert acc.timezone in ("America/New_York", "America/Los_Angeles")


def test_replay_events_refer_to_rows_that_exist(built):
    runs = {r["analysis_id"]: r for r in built["rows"]["analysis_runs"]}
    asg = {a["assignment_id"]: a for a in built["rows"]["assignments"]}
    exposed = {x["assignment_id"] for x in built["rows"]["exposures"]}
    for ev in built["events"].values():
        assert ev["steps"] and ev["expected_status"] == ev["steps"][-1]["expected_status"]
        for rid in ev["requires"]:
            assert rid in runs
        for s in ev["steps"]:
            assert s["input"]["dataset_version"] == VERSION and s["headers"]["X-Actor-Id"] and s["headers"]["X-Actor-Role"] in ("analyst", "experimenter")
            assert re.fullmatch(r"[A-Za-z0-9._:\-]{1,128}", s["input"]["idempotency_key"])
            for b in s.get("bind", []):
                assert 0 <= b["from_step"] < ev["steps"].index(s)
            inp = s["input"]["input"]
            if "analysis_id" in inp:
                assert inp["analysis_id"] in runs
            if s["command"] == "record-exposure":
                a = asg[inp["assignment_id"]]
                assert a["assignment_id"] not in exposed and inp["exposed_at"] < a["assigned_at"]
    keys = [s["input"]["idempotency_key"] for ev in built["events"].values() for s in ev["steps"]]
    assert len(set(keys)) == len(keys)
    # the interim run EV-03 cites is before planned_end; the run EV-08 cites belongs to v2; EV-09's is the final run of v1
    assert runs["an-002"]["cutoff_at"] < "2026-08-02T00:00:00Z" and runs["an-005"]["experiment_version_id"] == XV2
    assert runs["an-004"]["cutoff_at"] == "2026-08-02T00:00:00Z"


# --- PostgreSQL (needs DATABASE_URL) ---------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def loaded(built, inputs):
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    import psycopg
    from psycopg.rows import dict_row
    from data import migrate, seed
    with psycopg.connect(url) as c:
        migrate.reset(c)
        migrate.apply_migrations(c)
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as c:
        with c.transaction():
            # the replay events carry the dataset_version the generator published: name the load by it so the API's "current
            # dataset" is the one the events were prepared against; the manifest carries both plans
            out = seed.seed(c, {**inputs, "analysis_plans": built["manifest"]["analysis_plans"]}, dataset_version=VERSION,
                            dataset_hash=built["manifest"]["dataset_hash"])
        yield c, out


def test_seed_loads_the_generated_files(loaded, inputs, result, built):
    conn, out = loaded
    assert out["skipped"] == 0 and not result.rejected
    for name in gen.ENTITIES:
        assert out["inserted"][name] == len(inputs[name]), name
        assert conn.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"] == len(inputs[name]), name
    n = lambda t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]                # noqa: E731
    assert n("rejected_records") == 0 and n("analysis_plans") == 2 and n("funnel_definitions") == 1
    assert n("dataset_versions") == 1


def _sql(conn, cutoff: str, xv: str):
    sql = (ROOT / "data" / "sql" / "reference_metrics.sql").read_text()
    return conn.execute(sql, {"cutoff": parse_ts(cutoff), "xv": xv, "run_id": None}).fetchone()


@pytest.mark.parametrize("cutoff,xv", [("2026-10-05T00:00:00Z", XV1), ("2026-08-02T00:00:00Z", XV1), ("2026-06-15T00:00:00Z", XV1),
                                       ("2026-10-05T00:00:00Z", XV2)], ids=["as-of-v1", "planned-end-v1", "interim-v1", "as-of-v2"])
def test_sql_reference_agrees_with_the_domain_key_by_key(loaded, built, cutoff, xv):
    conn, _ = loaded
    row = _sql(conn, cutoff, xv)
    res = run_pipeline(make_inputs(built, xv), cutoff=cutoff, experiment_version_id=xv)
    assert set(row) == {*METRIC_KEYS, "tracking_quality", "identity", "empty_population"}
    for k in METRIC_KEYS:
        assert row[k] == res.metrics[k], (k, str(row[k])[:200], str(res.metrics[k])[:200])
    assert row["tracking_quality"] == res.tracking_quality and row["identity"] == res.identity and row["empty_population"] is res.empty_population
    ex = row["experiment"]
    if xv == XV2:
        assert ex["srm"]["verdict"] == "MISMATCH"
    elif cutoff.startswith("2026-06"):
        assert ex["run"]["analysis_id"] == "an-002" and ex["run"]["prior_runs"] == 1 and ex["run"]["interim"] is True
    elif cutoff.startswith("2026-08"):
        assert ex["run"]["analysis_id"] == "an-004" and ex["run"]["prior_runs"] == 3 and ex["run"]["interim"] is False
    else:
        assert ex["srm"]["verdict"] == "OK" and ex["primary"]["interval"] is not None


def test_replay_events_behave_as_recorded(loaded, built):
    from fastapi.testclient import TestClient
    from api.app import PREFIX, create_app
    conn, _ = loaded
    n = lambda sql, *args: conn.execute(sql, args).fetchone()["n"]                              # noqa: E731
    version = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    assert version["dataset_version"] == VERSION                                                  # replayed AS PUBLISHED
    exposures0, runs0 = n("SELECT count(*) AS n FROM exposures"), n("SELECT count(*) AS n FROM analysis_runs")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        for eid, ev in sorted(built["events"].items()):
            responses: list = []
            for i, s in enumerate(ev["steps"]):
                body = copy.deepcopy(s["input"])
                for b in s.get("bind", []):
                    v = responses[b["from_step"]].json()
                    for part in b["path"].split("."):
                        v = v[part]
                    body["input"][b["into"]] = v
                r = client.post(f"{PREFIX}/commands/{s['command']}", json=body, headers=s["headers"])
                assert r.status_code == s["expected_status"], (eid, i, r.text[:600])
                if s.get("expected_reason"):
                    err = r.json()["error"]
                    assert s["expected_reason"] in {err["code"]} | {d["rule_id"] for d in err["details"]}, (eid, i, err)
                responses.append(r)
            exp = ev["expected"]
            last = responses[-1]
            if eid in ("EV-01", "EV-02"):
                assert exp["runs_written"] == 0
            elif eid == "EV-03":
                assert n("SELECT count(*) AS n FROM decisions") == 0 and \
                    n("SELECT count(*) AS n FROM audit_events WHERE action = 'record-decision-refused' AND experiment_version_id = %s", XV1) == 1
            elif eid == "EV-08":
                assert n("SELECT count(*) AS n FROM decisions WHERE experiment_version_id = %s", XV2) == exp["decisions_written"] == 1
                assert conn.execute("SELECT decision FROM decisions WHERE experiment_version_id = %s", (XV2,)).fetchone()["decision"] == exp["decision"]
                assert n("SELECT count(*) AS n FROM audit_events WHERE action = 'record-decision-refused' AND experiment_version_id = %s", XV2) == exp["refusals_audited"]
                assert responses[0].json()["result"]["verdict"] in ("OK", "HARMFUL", "INSUFFICIENT")
            elif eid == "EV-09":
                assert n("SELECT count(*) AS n FROM decisions WHERE experiment_version_id = %s", XV1) == 0
                sa = exp["segment_analysis"]
                m = client.get(f"{PREFIX}/metrics", params={"group_by": sa["by"], "experiment_version_id": XV1, "cutoff": sa["cutoff"]})
                assert m.status_code == 200
                seg = m.json()["data"]["segment_analysis"]
                assert seg["label"] == sa["label"] and seg["decision_basis"] is sa["decision_basis"] and seg["segments_tested"] == sa["segments_tested"]
                assert seg["bonferroni_threshold"] == "0.016667" and seg["alpha"] == "0.050000"
                assert all(s["label"] == "exploratory" and s["decision_basis"] is False for s in seg["segments"])
            elif eid == "EV-10":
                prim = last.json()["result"]["primary"]
                assert last.json()["status"] == "interim" and prim["relative_lift"] is None and prim["absolute_lift_pp"] == exp["absolute_lift_pp"]
                assert prim["variants"]["control"]["conversion"] == exp["control_conversion"]
                assert (prim["variants"]["control"]["mature_units"], prim["variants"]["treatment"]["mature_units"]) == \
                    (exp["mature_control"], exp["mature_treatment"])
                assert last.json()["result"]["run"]["prior_runs"] >= 4
            elif eid == "EV-11":
                assert n("SELECT count(*) AS n FROM exposures") == exposures0 and n("SELECT count(*) AS n FROM exposures WHERE exposure_id = 'ex-ev11'") == 0
                assert n("SELECT count(*) AS n FROM rejected_records WHERE entity = 'exposures' AND reason_code = 'EXPOSURE_BEFORE_ASSIGNMENT'") == exp["rejected_records_kept"]
        # a refused request is not a run: only EV-10 wrote one (plus the logged history)
        assert n("SELECT count(*) AS n FROM analysis_runs") == runs0 + 1
        assert n("SELECT count(*) AS n FROM analysis_runs WHERE created_by <> 'seed'") == 1
        assert n("SELECT count(*) AS n FROM decisions") == 1


def test_the_loaded_dataset_is_served_by_the_api(loaded, built):
    from fastapi.testclient import TestClient
    from api.app import PREFIX, create_app
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        for name, extra in (("accounts", {}), ("assignments", {"experiment_version_id": XV2}), ("sessions", {})):
            r = client.get(f"{PREFIX}/data/{name}", params={"limit": 5, **extra})
            assert r.status_code == 200, r.text
            want = len([x for x in built["rows"][name] if all(x[k] == v for k, v in extra.items())])
            assert r.json()["meta"]["total_count"] == want
        r = client.get(f"{PREFIX}/metrics", params={"experiment_version_id": XV2, "cutoff": "2026-10-05T00:00:00Z"})
        assert r.status_code == 200 and r.json()["data"]["metrics"]["experiment"]["srm"]["verdict"] == "MISMATCH"
        assert {w["code"] for w in r.json()["warnings"]} >= {"SRM_MISMATCH"}
