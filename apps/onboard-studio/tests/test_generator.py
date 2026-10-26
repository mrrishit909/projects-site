"""Synthetic data generator: determinism, shapes, sizes, consistency, injected defects, designed relationships."""
from __future__ import annotations

import collections
import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("os_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["os_generate"] = gen
_spec.loader.exec_module(gen)

from onboard_studio import calendar as cal  # noqa: E402
from onboard_studio.metrics import FLAG_PAUSE_OUTSIDE_WORKING, compute_metrics, group_metrics  # noqa: E402
from onboard_studio.pipeline import run_pipeline  # noqa: E402
from onboard_studio.timeutil import parse_ts  # noqa: E402
from onboard_studio.workflow import definition_hash  # noqa: E402

SEED = 20261026
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
LISTED = [n for n in gen.ENTITIES if n != "workflow_requirements"]
OPTIONAL_KEYS = {"calendar_intervals": {"kind"}, "waiting_intervals": {"pause_requested"}}


def _run(tmp: Path):
    out, meta = tmp / "out", tmp / "meta"
    manifest = gen.write_all(SEED, out, meta)
    return out, meta, manifest


def _load(out: Path) -> dict:
    data: dict = {"contract": "v1"}
    for name in gen.ENTITIES:
        doc = json.loads((out / f"{name}.json").read_text())
        assert doc["entity"] == name and doc["dataset_version"] == f"os-{SEED}-20261026"
        data[name] = doc["rows"]
    data["workflow_requirements"] = {r["workflow_version_id"]: {"required_document_types": r["required_document_types"]}
                                     for r in data["workflow_requirements"]}
    return data


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen")
    out, meta, manifest = _run(tmp)
    return {"out": out, "meta": meta, "manifest": manifest, "data": _load(out),
            "inj": {i["id"]: i for i in json.loads((meta / "injection-manifest.json").read_text())["injections"]},
            "events": json.loads((meta / "injection-events.json").read_text())["events"]}


@pytest.fixture(scope="module")
def inputs(built):
    return built["data"]


@pytest.fixture(scope="module")
def result(inputs):
    return run_pipeline(inputs)


def _rows(built, name):
    return built["data"][name]


# --- determinism, files, manifest -------------------------------------------------------------------------

def test_two_runs_give_identical_files_and_hash(tmp_path, built):
    out2, meta2, m2 = _run(tmp_path)
    assert m2["dataset_hash"] == built["manifest"]["dataset_hash"]
    for name in gen.ENTITIES:
        assert (out2 / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes()
    for name in ("injection-events.json", "injection-manifest.json"):
        assert (meta2 / name).read_bytes() == (built["meta"] / name).read_bytes()


def test_manifest_fields_and_hash_recipe(built):
    m = json.loads((built["out"] / "manifest.json").read_text())
    assert m["dataset_version"] == f"os-{SEED}-20261026" and m["contract_version"] == "v1"
    assert m["generator"]["name"] == "generate.py" and m["generator"]["seed"] == SEED
    assert m["generator"]["parameters"]["cases"] == gen.CASES
    assert m["injection_manifest"] == "injection-manifest.json"
    assert len(m["designed_relationships"]) == 4
    datetime.strptime(m["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    h = hashlib.sha256()
    for name in sorted(gen.ENTITIES):
        rows = json.loads((built["out"] / f"{name}.json").read_text())["rows"]
        h.update(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
    assert h.hexdigest() == m["dataset_hash"]
    assert m["row_counts"] == {n: len(json.loads((built["out"] / f"{n}.json").read_text())["rows"])
                               for n in gen.ENTITIES}
    assert (built["out"] / "injection-manifest.json").read_text() == (built["meta"] / "injection-manifest.json").read_text()
    inj = json.loads((built["meta"] / "injection-manifest.json").read_text())
    assert inj["dataset_hash"] == m["dataset_hash"]


def test_committed_snapshot_is_current(built):
    """web/public/data and data/injection-* must be what the generator writes for the default seed."""
    pub = ROOT / "web" / "public" / "data"
    if not (pub / "manifest.json").exists():
        pytest.skip("snapshot not generated")
    committed = json.loads((pub / "manifest.json").read_text())
    assert committed["dataset_hash"] == built["manifest"]["dataset_hash"]
    for name in gen.ENTITIES:
        assert (pub / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), name
    assert (pub / "injection-manifest.json").read_bytes() == (built["out"] / "injection-manifest.json").read_bytes()
    assert (ROOT / "data" / "injection-manifest.json").read_bytes() == (built["meta"] / "injection-manifest.json").read_bytes()
    assert (ROOT / "data" / "injection-events.json").read_bytes() == (built["meta"] / "injection-events.json").read_bytes()


def test_different_seed_changes_hash(tmp_path, built):
    m = gen.write_all(SEED + 1, tmp_path / "o", tmp_path / "m")
    assert m["dataset_hash"] != built["manifest"]["dataset_hash"]


def test_total_output_under_5_mb(built):
    assert sum(p.stat().st_size for p in built["out"].glob("*.json")) < 5_000_000


# --- shapes, ids, counts ------------------------------------------------------------------------------------

def test_shapes_match_golden(built):
    data = built["data"]
    for name, g in GOLDEN.items():
        if not isinstance(g, list) or not g or not isinstance(g[0], dict):
            continue
        want = set(g[0])
        extra = OPTIONAL_KEYS.get(name, set())
        assert data[name], name
        assert all(want <= set(r) <= want | extra for r in data[name]), name
    assert all(set(r) == {"workflow_version_id", "required_document_types"} for r in
               json.loads((built["out"] / "workflow_requirements.json").read_text())["rows"])
    # the optional keys are not noise: kind on every calendar row, pause_requested only on the 3 injected waits
    assert all(r["kind"] in ("working", "holiday") for r in data["calendar_intervals"])
    assert sum(1 for r in data["waiting_intervals"] if "pause_requested" in r) == 3
    assert all(r["pause_requested"] is True for r in data["waiting_intervals"] if "pause_requested" in r)
    assert {tuple(sorted(r)) for r in data["case_events"]} == {tuple(sorted(GOLDEN["case_events"][0]))}


def test_ids_are_opaque_and_unique(built):
    pat = {"organizations": r"org-\d{4}", "cases": r"case-\d{6}", "workflow_versions": r"wfv-\d{3}",
           "step_definitions": r"sd-\d{3}", "dependencies": r"dep-\d{3}", "step_instances": r"si-\d{6}",
           "assignments": r"asg-\d{6}", "document_versions": r"dv-\d{6}", "approvals": r"apr-\d{6}",
           "sla_rules": r"sla-\d{3}", "calendar_intervals": r"ci-\d{4}", "waiting_intervals": r"wi-\d{5}",
           "case_events": r"ev-\d{6}"}
    for name, rx in pat.items():
        idf = gen_id_field(name)
        ids = [r[idf] for r in built["data"][name]]
        assert len(ids) == len(set(ids)), name
        assert all(re.fullmatch(rx, i) for i in ids), name


def gen_id_field(entity: str) -> str:
    from onboard_studio.models import ID_FIELD
    return ID_FIELD[entity]


def test_counts_within_spec_ranges(built):
    """Spec (docs/data-generator.md): ~900 cases, ~4,500 steps, ~5,500 assignments, ~2,800 documents, ~3,600
    approvals, ~1,100 waits, ~15,000 events. The 5 MB cap on the published files forces 740 cases (-18 %): the
    case, step, assignment, document, wait and event volumes sit 5-25 % under the spec, the approvals on it."""
    c = built["manifest"]["row_counts"]
    assert c["cases"] == 740 and c["organizations"] == 40
    assert c["workflow_versions"] == 2 and c["sla_rules"] == 2 and c["workflow_requirements"] == 2
    assert c["step_instances"] == c["cases"] * 5 == 3700
    for name, lo, hi in (("assignments", 4000, 5500), ("document_versions", 1900, 2800), ("approvals", 3300, 3900),
                         ("waiting_intervals", 750, 1100), ("case_events", 11500, 15500)):
        assert lo <= c[name] <= hi, (name, c[name])
    orgs = built["data"]["organizations"]
    assert collections.Counter(o["segment"] for o in orgs) == {"smb": 22, "mid_market": 12, "enterprise": 6}
    assert {o["region"] for o in orgs} == {"reg-north", "reg-south", "reg-east", "reg-west"}
    assert sum(1 for o in orgs if len(o["organization_name"]) >= 60) >= 4
    cases = built["data"]["cases"]
    assert {c["workflow_version_id"] for c in cases} == {"wfv-001", "wfv-002"}
    assert min(c["opened_at"] for c in cases) >= "2025-04-01" and max(c["opened_at"] for c in cases) <= "2026-09-30T23:59:59Z"
    assert 15 <= sum(1 for c in cases if c["status"] == "open") <= 80
    cal_rows = built["data"]["calendar_intervals"]
    assert {r["calendar_id"] for r in cal_rows} == {"cal-001"} and {r["timezone"] for r in cal_rows} == {"UTC"}
    sla = built["data"]["sla_rules"]
    assert all(r["business_minutes"] == 480 and r["pause_policy"] == ["customer_info_requested", "external_verification"]
               for r in sla)


def test_calendar_has_six_holidays_two_on_weekends(built):
    rows = built["data"]["calendar_intervals"]
    hol = [r for r in rows if r["kind"] == "holiday"]
    assert len(hol) == 6
    weekend = [r for r in hol if parse_ts(r["starts_at"]).weekday() >= 5]
    assert len(weekend) == 2 and [r["calendar_interval_id"] for r in weekend] == built["inj"]["INJ-08"]["record_ids"]
    working = [r for r in rows if r["kind"] == "working"]
    assert all(parse_ts(r["starts_at"]).weekday() < 5 for r in working)
    assert all(r["starts_at"][11:] == "09:00:00Z" and r["ends_at"][11:] == "17:00:00Z" for r in working)
    # a weekend holiday subtracts nothing: the effective set equals the working set minus the 4 weekday holidays
    ws = [(parse_ts(r["starts_at"]), parse_ts(r["ends_at"])) for r in working]
    hs = [(parse_ts(r["starts_at"]), parse_ts(r["ends_at"])) for r in hol]
    assert len(cal.effective_intervals(ws, hs)) == len(ws) - 4


def test_definition_hashes_match_the_domain(built):
    d = built["data"]
    for v in d["workflow_versions"]:
        steps = [s for s in d["step_definitions"] if s["workflow_version_id"] == v["workflow_version_id"]]
        ids = {s["step_definition_id"] for s in steps}
        deps = [x for x in d["dependencies"] if x["step_definition_id"] in ids]
        assert v["definition_hash"] == definition_hash(steps, deps)
        assert v["published_at"] is not None


# --- consistency with the contract (independent of the domain ingest) --------------------------------------

def test_every_case_is_consistent_except_the_injected_defects(built):
    d = built["data"]
    inj = built["inj"]
    roles = built["manifest"]["generator"]["parameters"]["reviewers_by_role"]
    role_of = {r: role for role, rs in roles.items() for r in rs}
    sd = {s["step_definition_id"]: s for s in d["step_definitions"]}
    deps: dict[str, list[str]] = collections.defaultdict(list)
    for x in d["dependencies"]:
        deps[x["step_definition_id"]].append(x["prerequisite_id"])
    steps_by_case, docs_by_case, waits_by_case, events_by_case = (collections.defaultdict(list) for _ in range(4))
    for s in d["step_instances"]:
        steps_by_case[s["case_id"]].append(s)
    for x in d["document_versions"]:
        docs_by_case[x["case_id"]].append(x)
    for x in d["waiting_intervals"]:
        waits_by_case[x["case_id"]].append(x)
    for x in d["case_events"]:
        events_by_case[x["case_id"]].append(x)
    assigns = collections.defaultdict(list)
    for a in d["assignments"]:
        assigns[a["step_instance_id"]].append(a)
    approvals = collections.defaultdict(list)
    for a in d["approvals"]:
        approvals[a["step_instance_id"]].append(a)
    step_case = {s["step_instance_id"]: s["case_id"] for s in d["step_instances"]}
    required_docs = {w: set(v["required_document_types"]) for w, v in
                     {k: v for k, v in built["data"]["workflow_requirements"].items()}.items()}
    self_cases = set(inj["INJ-10"]["case_ids"])
    missing_cases = set(inj["INJ-01"]["record_ids"])
    conflict_apr = set(inj["INJ-02"]["record_ids"])
    wrong = set(inj["INJ-09"]["case_ids"])
    assert not (self_cases & missing_cases) and not (wrong & missing_cases)
    for c in d["cases"]:
        cid = c["case_id"]
        steps = {s["step_definition_id"]: s for s in steps_by_case[cid]}
        defs = [s for s in d["step_definitions"] if s["workflow_version_id"] == c["workflow_version_id"]]
        assert set(steps) == {s["step_definition_id"] for s in defs}
        for sid, s in steps.items():
            if s["status"] == "blocked":
                assert s["ready_at"] is None and s["started_at"] is None and s["approved_at"] is None
                assert not assigns[s["step_instance_id"]]
                continue
            # readiness: every mandatory prerequisite approved before the step is ready or started
            for p in deps[sid]:
                assert steps[p]["approved_at"] is not None and steps[p]["approved_at"] <= s["ready_at"], (cid, sid)
            if s["started_at"]:
                assert s["ready_at"] <= s["started_at"]
            chain = sorted(assigns[s["step_instance_id"]], key=lambda a: a["assigned_at"])
            assert chain and chain[0]["assigned_at"] == s["ready_at"]
            for a, b in zip(chain, chain[1:]):  # reassignment closes the prior interval, none is dropped
                assert a["ended_at"] == b["assigned_at"] and a["assignee_id"] != b["assignee_id"]
            if s["status"] == "approved":
                assert chain[-1]["ended_at"] == s["approved_at"]
                ap = sorted(approvals[s["step_instance_id"]], key=lambda a: (a["decided_at"], a["approval_id"]))
                assert ap and ap[0]["decided_at"] == s["approved_at"] and ap[0]["decision"] == "approved"
                assert role_of[ap[0]["reviewer_id"]] == sd[sid]["role_key"]
                if cid not in self_cases:
                    assert ap[0]["reviewer_id"] not in {a["assignee_id"] for a in chain}
                extra = [a for a in ap[1:]]
                assert all(a["approval_id"] in conflict_apr for a in extra)
                assert all(role_of[a["reviewer_id"]] == sd[sid]["role_key"] for a in extra)
            else:
                assert chain[-1]["ended_at"] is None and not approvals[s["step_instance_id"]]
        # documents are append-only versions: contiguous numbers, only the last can be accepted
        per_type = collections.defaultdict(list)
        for x in docs_by_case[cid]:
            per_type[x["document_type"]].append(x)
        for t, vs in per_type.items():
            vs.sort(key=lambda x: x["version_number"])
            assert [x["version_number"] for x in vs] == list(range(1, len(vs) + 1)), (cid, t)
            assert all(x["review_status"] == "rejected" for x in vs[:-1])
            assert all(a["submitted_at"] < b["submitted_at"] for a, b in zip(vs, vs[1:]))
            assert all(x["content_hash"].startswith("sha256:") and len(x["content_hash"]) == 71 for x in vs)
        evs = sorted(events_by_case[cid], key=lambda e: e["event_id"])
        assert evs[0]["event_type"] == "case_opened" and evs[0]["occurred_at"] == c["opened_at"]
        assert [e["occurred_at"] for e in evs] == sorted(e["occurred_at"] for e in evs)
        if c["status"] == "completed":
            assert evs[-1]["event_type"] == "case_completed" and evs[-1]["occurred_at"] == c["completed_at"]
            assert sum(e["event_type"] == "case_completed" for e in evs) == 1
            assert all(s["status"] == "approved" for s in steps.values())
            accepted = {t for t, vs in per_type.items() if vs[-1]["review_status"] == "accepted"}
            if cid in missing_cases:
                assert not required_docs[c["workflow_version_id"]] <= accepted
            else:
                assert required_docs[c["workflow_version_id"]] <= accepted
            assert c["completed_at"] == max(s["approved_at"] for s in steps.values())
        else:
            assert c["completed_at"] is None and not any(e["event_type"] == "case_completed" for e in evs)
        # waits: starts inside a working interval unless injected; none overlap; none after completion
        ws = sorted(waits_by_case[cid], key=lambda w: w["starts_at"])
        for a, b in zip(ws, ws[1:]):
            assert a["ends_at"] <= b["starts_at"]
    # version 2 is published before any case binds it
    pub = {v["workflow_version_id"]: v["published_at"] for v in d["workflow_versions"]}
    assert all(pub[c["workflow_version_id"]] <= c["opened_at"] for c in d["cases"])


def test_organic_pauses_start_in_working_time(built):
    d = built["data"]
    injected = set(built["inj"]["INJ-03"]["record_ids"])
    ws = [(parse_ts(r["starts_at"]), parse_ts(r["ends_at"])) for r in d["calendar_intervals"] if r["kind"] == "working"]
    hs = [(parse_ts(r["starts_at"]), parse_ts(r["ends_at"])) for r in d["calendar_intervals"] if r["kind"] == "holiday"]
    eff = cal.effective_intervals(ws, hs)
    for w in d["waiting_intervals"]:
        if w["waiting_interval_id"] in injected or w["ends_at"] is None:
            continue
        assert cal.overlap_seconds(parse_ts(w["starts_at"]), parse_ts(w["ends_at"]), eff) > 0, w
    assert {w["reason_code"] for w in d["waiting_intervals"]} == {
        "customer_info_requested", "external_verification", "internal_processing", "document_review", "manual_check"}


def test_injection_manifest_lists_every_defect(built):
    inj = built["inj"]
    assert list(inj) == [f"INJ-{n:02d}" for n in range(1, 13)]
    for i in inj.values():
        assert {"id", "test", "entity", "record_ids", "description", "expected_handling", "location"} <= set(i)
        assert i["record_ids"]
    counts = {k: len(v["record_ids"]) for k, v in inj.items()}
    assert counts["INJ-01"] == 2 and counts["INJ-02"] == 2 and counts["INJ-03"] == 3 and counts["INJ-08"] == 2
    assert counts["INJ-09"] == 3 and counts["INJ-10"] == 2
    ev = built["events"]
    for e in ev:
        assert {"injection", "command", "expected_handling"} <= set(e) or e["command"] == "sql"
        assert e["injection"] in inj and "expected_handling" in e and (
            "expected_error_code" in e or e.get("expected_status") == 200)
    assert {e["injection"] for e in ev} == {"INJ-02", "INJ-04", "INJ-05", "INJ-06", "INJ-07", "INJ-11", "INJ-12"}
    assert len([e for e in ev if e["injection"] == "INJ-06" and e["command"] == "resubmit-document"]) == 2
    assert len([e for e in ev if e["injection"] == "INJ-07"]) == 2
    # events reference rows that exist, and the draft cycle is not in the entity files
    ids = {r["step_instance_id"] for r in built["data"]["step_instances"]}
    assert all(e["input"]["step_instance_id"] in ids for e in ev if e["command"] in ("approve-step", "reassign-work"))
    assert "wfv-003" not in {v["workflow_version_id"] for v in built["data"]["workflow_versions"]}
    steps = {s["step_instance_id"]: s for s in built["data"]["step_instances"]}
    assert all(steps[e["input"]["step_instance_id"]]["status"] == "in_review" for e in ev if e["command"] == "approve-step")


# --- the pipeline over the generated data -----------------------------------------------------------------

def test_pipeline_runs_and_rejects_exactly_the_injected_cases(result, built):
    inj = built["inj"]
    d = built["data"]
    reasons = {}
    for r in result.rejected:
        reasons.setdefault((r["entity"], r["reason_code"]), set()).add(r["id"])
    case_reason = {}
    for ids, code in ((inj["INJ-01"]["record_ids"], "MISSING_REQUIRED_DOCUMENT"),
                      (inj["INJ-10"]["case_ids"], "SELF_APPROVAL"),
                      (inj["INJ-09"]["case_ids"], "PAUSE_REASON_NOT_CONFIGURED")):
        for cid in ids:
            case_reason[cid] = code
    assert {i for (e, c), s in reasons.items() if e == "cases" for i in s} == set(case_reason)
    for (e, c), s in reasons.items():
        if e == "cases":
            assert all(case_reason[i] == c for i in s)
    # every row of a rejected case is rejected with the case's reason, and nothing else is rejected but the
    # later approval of each conflicting pair (DECISION_CONFLICT)
    step_case = {s["step_instance_id"]: s["case_id"] for s in d["step_instances"]}
    owner = {"step_instances": lambda r: r["case_id"], "assignments": lambda r: step_case[r["step_instance_id"]],
             "document_versions": lambda r: r["case_id"], "approvals": lambda r: step_case[r["step_instance_id"]],
             "waiting_intervals": lambda r: r["case_id"], "case_events": lambda r: r["case_id"],
             "cases": lambda r: r["case_id"]}
    expected = {}
    for ent, of in owner.items():
        for r in d[ent]:
            cid = of(r)
            if cid in case_reason:
                expected[(ent, r[gen_id_field(ent)])] = case_reason[cid]
    got = {(r["entity"], r["id"]): r["reason_code"] for r in result.rejected}
    conflicts = set(inj["INJ-02"]["record_ids"])
    for apr in conflicts:
        assert got.pop(("approvals", apr)) == "DECISION_CONFLICT"
    assert got == expected
    assert len(conflicts) == 2
    for ent in ("organizations", "workflow_versions", "step_definitions", "dependencies", "sla_rules",
                "calendar_intervals"):
        assert result.counts[ent]["rejected"] == 0
    assert result.counts["cases"] == {"accepted": gen.CASES - 7, "rejected": 7}


def test_completed_with_missing_document_cases_are_rejected_not_flagged(result, built):
    """Domain behaviour: a completed case without an accepted required document is rejected at ingest with
    MISSING_REQUIRED_DOCUMENT (with every row hanging off it), so it never reaches the metrics."""
    ids = set(built["inj"]["INJ-01"]["record_ids"])
    rej = {r["id"]: r["reason_code"] for r in result.rejected if r["entity"] == "cases"}
    assert {i: rej[i] for i in ids} == {i: "MISSING_REQUIRED_DOCUMENT" for i in ids}
    assert not ids & {c.case_id for c in result.population.cases}
    assert not any(f["case_id"] in ids for f in result.flags)


def test_pauses_outside_working_intervals_add_no_hours_and_are_flagged(result, built):
    inj = built["inj"]["INJ-03"]
    assert sorted(f["waiting_interval_id"] for f in result.flags) == sorted(inj["record_ids"])
    assert all(f["flag"] == FLAG_PAUSE_OUTSIDE_WORKING for f in result.flags)
    assert sorted(f["case_id"] for f in result.flags) == sorted(inj["case_ids"])
    assert sorted(inj["kinds"]) == ["holiday", "saturday", "sunday"]
    pop = result.population
    for cid, wid in zip(inj["case_ids"], inj["record_ids"]):
        sub = pop.subset({cid})
        with_wait = compute_metrics(sub)
        without = compute_metrics(dataclasses.replace(
            sub, waiting_intervals=[w for w in sub.waiting_intervals if w.waiting_interval_id != wid]))
        assert with_wait["paused_business_overlap_hours"] == without["paused_business_overlap_hours"]
        assert with_wait["active_elapsed_hours"] == without["active_elapsed_hours"]
        assert with_wait["business_cycle_time_hours"] == without["business_cycle_time_hours"]
        assert float(with_wait["paused_time_hours"]) > float(without["paused_time_hours"])  # calendar time only
    assert not [f for f in result.flags if f["waiting_interval_id"] not in set(inj["record_ids"])]


def test_metrics_are_plausible(result):
    m = result.metrics
    assert m["completed_eligible_cases"] > 600 and not m["empty_population"]
    assert 0.3 < float(m["sla_attainment"]) < 0.8
    assert float(m["document_completeness"]) > 0.98
    assert float(m["active_elapsed_hours"]) < float(m["business_cycle_time_hours"]) < float(m["calendar_cycle_time_hours"])
    assert float(m["calendar_cycle_time_hours"]) > float(m["paused_time_hours"]) > 0
    back = compute_metrics(result.population, None, ["2026-03-31T23:59:59Z", "2026-09-30T23:59:59Z"])["open_backlog_at_cutoff"]
    assert 0 < back["2026-03-31T23:59:59Z"] < 120 and back["2026-09-30T23:59:59Z"] >= 15


# --- designed relationships -------------------------------------------------------------------------------

def test_designed_relationship_v2_is_faster_with_fewer_handoffs(result):
    pop = result.population
    g = group_metrics(pop, "workflow_version")
    v1, v2 = g["wfv-001"], g["wfv-002"]
    assert float(v2["active_elapsed_hours"]) < 0.75 * float(v1["active_elapsed_hours"])
    assert float(v2["active_elapsed_hours"]) > 0.55 * float(v1["active_elapsed_hours"])
    n = collections.Counter(c.workflow_version_id for c in pop.cases)
    per_case = {k: v["handoff_count"] / n[k] for k, v in g.items()}
    assert 0.70 <= per_case["wfv-002"] / per_case["wfv-001"] <= 0.90, per_case
    assert float(v2["sla_attainment"]) > float(v1["sla_attainment"])


def test_designed_relationship_enterprise_rework_is_double(result):
    g = group_metrics(result.population, "segment")
    ent = float(g["enterprise"]["rework_rate"])
    others = [float(g[s]["rework_rate"]) for s in ("smb", "mid_market")]
    assert ent > 1.5 * max(others), (ent, others)
    n_o = sum(g[s]["completed_eligible_cases"] for s in ("smb", "mid_market"))
    assert n_o and 1.6 <= ent / (sum(o * g[s]["completed_eligible_cases"] for o, s in zip(others, ("smb", "mid_market"))) / n_o) <= 2.6


def test_designed_relationship_north_waits_longest(result):
    g = group_metrics(result.population, "region")
    paused = {k: float(v["paused_time_hours"]) for k, v in g.items()}
    north = paused.pop("reg-north")
    assert north > 1.5 * max(paused.values()), (north, paused)


def test_designed_relationship_bottleneck_at_approve_account_for_rev_004(result, built):
    pop = result.population
    names = {s.step_definition_id: s.step_name for s in pop.step_definitions}
    step = {s.step_instance_id: s for s in pop.step_instances}
    lat = collections.defaultdict(list)
    for a in pop.approvals:
        s = step[a.step_instance_id]
        if names[s.step_definition_id] == "approve_account" and s.started_at:
            lat[a.reviewer_id].append((a.decided_at - s.started_at).total_seconds() / 3600)
    assert set(lat) == {"rev-004", "rev-005", "rev-006"}
    slow = statistics.mean(lat["rev-004"])
    assert slow > 2 * max(statistics.mean(lat["rev-005"]), statistics.mean(lat["rev-006"]))
    assert len(lat["rev-004"]) > len(lat["rev-005"])
    # step waiting time (ready -> started): approve_account is the slowest step of both versions
    sw = result.metrics["step_waiting_time_hours"]
    by_name = collections.defaultdict(list)
    for sid, hrs in sw.items():
        by_name[names[sid]].append(float(hrs))
    assert max(by_name, key=lambda k: statistics.mean(by_name[k])) == "approve_account"


# --- PostgreSQL ------------------------------------------------------------------------------------------------

@pytest.fixture
def seeded_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    import psycopg
    from data import migrate
    with psycopg.connect(url, autocommit=True) as c:
        migrate.reset(c)
        migrate.apply_migrations(c)
        yield c


def test_seed_generated_data_into_postgres(seeded_conn, inputs):
    from data import seed
    from onboard_studio.ingest import validate_batch
    out = seed.seed(seeded_conn, inputs)
    ing = validate_batch(inputs)
    assert out["skipped"] == len(ing.rejected) > 7
    for ent in seed.INSERT_ORDER:
        n = seeded_conn.execute(f"SELECT count(*) FROM {ent}").fetchone()[0]  # ent is a constant
        assert n == len(ing.accepted[ent]) == out["inserted"][ent], ent
    q = lambda sql: seeded_conn.execute(sql).fetchone()[0]  # noqa: E731
    assert q("SELECT count(*) FROM cases") == gen.CASES - 7
    assert q("SELECT count(*) FROM cases WHERE status = 'completed'") == sum(
        1 for c in ing.accepted["cases"] if c.status == "completed")
    assert q("SELECT count(*) FROM workflow_requirements") == 2 + 3 and q(
        "SELECT count(*) FROM workflow_versions WHERE published_at IS NOT NULL") == 2
    assert q("SELECT count(*) FROM calendar_intervals WHERE kind = 'holiday'") == 6
    assert q("SELECT count(*) FROM rejected_records") == len(ing.rejected)
    assert q("SELECT count(*) FROM rejected_records WHERE reason_code = 'DECISION_CONFLICT'") == 2
    second = seed.seed(seeded_conn, inputs)
    assert all(v == 0 for v in second["inserted"].values())
    assert q("SELECT count(*) FROM approvals") == len(ing.accepted["approvals"])


def test_replaying_the_event_only_defects_through_the_api(seeded_conn, inputs, built):
    from fastapi.testclient import TestClient

    from api.app import PREFIX, create_app
    from data import seed
    seed.seed(seeded_conn, inputs)
    n = 0
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        for i, e in enumerate(built["events"]):
            if e["command"] == "sql":
                continue
            n += 1
            body = {"request_id": f"req-{i}", "dataset_version": built["manifest"]["dataset_version"],
                    "idempotency_key": f"inj-{i}", "input": e["input"]}
            r = client.post(f"{PREFIX}/commands/{e['command']}", json=body, headers=e["headers"])
            if "expected_error_code" not in e:
                assert r.status_code == 200, (e["injection"], r.text)
                continue
            text = r.text
            assert r.status_code >= 400 and e["expected_error_code"] in text, (e["injection"], e["command"], text)
    assert n == len([e for e in built["events"] if e["command"] != "sql"])
    for e in built["events"]:  # the SQL attempts are refused by the triggers
        if e["command"] != "sql":
            continue
        import psycopg
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            seeded_conn.execute(e["statement"])
