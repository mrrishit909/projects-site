"""Synthetic data generator (P08-WORK-03): determinism, size, the spec's shape, designed relationships, the twelve injected defects, and the domain.

The generator (data/generate.py, standard library only) builds the whole world in memory (about 40,000 raw records) and publishes the entity files
with a SAMPLE of the raw records plus per-batch summaries. These tests regenerate the world and
  * run the domain over the COMPLETE world: the counts and metrics the manifest states are the domain's, and the domain's classification of every raw
    record equals what the generator constructed (two independent implementations of the same rules);
  * run the domain over the PUBLISHED files and check the counts the manifest states for that ingest;
  * check each designed relationship and each injected defect (the checks in injection-manifest.json run against the complete world);
  * seed the published files into PostgreSQL and replay the twelve recorded events through the FastAPI TestClient.
The build takes about a minute (the domain over 40,000 rows); it is built once per test session.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("po_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["po_generate"] = gen
_spec.loader.exec_module(gen)

from pipeline_observatory.timeutil import parse_ts  # noqa: E402
from support_db import at, client, db_url  # noqa: E402,F401  (fixtures and the clock freezer)

SEED = 20261026
VERSION = f"po-{SEED}-20261026"
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
MONEY = re.compile(r"^-?\d+\.\d\d$")
BUDGET = 5_000_000


def _no_float(text: str):
    def refuse(x):
        raise AssertionError(f"a float literal ({x}) in the output")
    return json.loads(text, parse_float=refuse)


def get(obj, path: str):
    for k in path.split("."):
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj


def check(shape: dict, c: dict) -> None:
    """One check of injection-manifest.json against the domain's output for the complete world."""
    if c.get("absent"):
        try:
            get(shape, c["path"])
        except (KeyError, IndexError):
            return
        raise AssertionError(f"{c['path']} exists")
    v = get(shape, c["path"])
    if "find" in c:
        hits = [x for x in v if all(x.get(k) == w for k, w in c["find"].items())]
        assert len(hits) == 1, (c["path"], c["find"], len(hits))
        for k, w in c["equals"].items():
            assert hits[0][k] == w, (c["path"], c["find"], k, hits[0][k], w)
    elif "equals" in c:
        assert v == c["equals"], (c["path"], v, c["equals"])
    elif "min" in c:
        assert v >= c["min"], (c["path"], v, c["min"])
    elif "max" in c:
        assert v <= c["max"], (c["path"], v, c["max"])
    elif "contains" in c:
        assert c["contains"] in v, (c["path"], c["contains"])
    elif "not_contains" in c:
        assert c["not_contains"] not in v, (c["path"], c["not_contains"])
    else:
        raise AssertionError(f"unknown check {c}")


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("po-gen") / "out"
    manifest, b = gen.write_all(SEED, out)
    files = {p.name: p.read_text() for p in out.glob("*.json")}
    docs = {n: _no_float(t) for n, t in files.items()}
    return {"out": out, "b": b, "w": b.w, "files": files, "docs": docs, "manifest": docs["manifest.json"], "inj": docs["injection-manifest.json"],
            "rows": {n: docs[f"{n}.json"]["rows"] for n in gen.PUBLISHED}}


# ---------------------------------------------------------------------------------------------------------------------------------- files
def test_files_shapes_sizes_and_formats(built):
    files, docs = built["files"], built["docs"]
    assert set(files) == {f"{n}.json" for n in gen.PUBLISHED} | {"manifest.json", "injection-manifest.json"}
    assert sum(len(t.encode()) for t in files.values()) < BUDGET
    for n in gen.PUBLISHED:
        d = docs[f"{n}.json"]
        assert list(d) == ["entity", "dataset_version", "rows"] and d["entity"] == n and d["dataset_version"] == VERSION and d["rows"], n

    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str) and re.match(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d", x) and key.endswith(("_at", "watermark")):
            assert STAMP.match(x), (key, x)
    for n in gen.PUBLISHED:
        walk(built["rows"][n])
    for t in built["rows"]["model_output_totals"]:
        assert MONEY.match(t["total_amount"])
    for r in built["rows"]["raw_records"]:
        for k in ("unit_price", "amount"):
            v = r["payload_json"].get(k)
            assert v is None or isinstance(v, str)


def test_the_hash_the_version_and_the_clock_are_fixed(built):
    m, rows = built["manifest"], built["rows"]
    h = hashlib.sha256()
    for n in sorted(gen.PUBLISHED):
        h.update(gen.canon(rows[n]).encode())
    assert m["dataset_hash"] == h.hexdigest() == built["inj"]["dataset_hash"]
    assert m["dataset_version"] == VERSION and m["generated_at"] == m["as_of"] == "2026-10-05T00:00:00Z" and m["generator"]["seed"] == SEED
    assert m["row_counts"] == {n: len(rows[n]) for n in gen.PUBLISHED}
    assert m["injection_manifest"] == "injection-manifest.json"
    assert m["generator"]["disclosures"] and all(isinstance(x, str) and x for x in m["generator"]["disclosures"])
    assert all(isinstance(v, str) for v in m["generator"]["parameters"].values())
    assert m["sample"]["size_cap_bytes"] == BUDGET and m["sample"]["size_cap_binding"] is False


def test_byte_identical_on_rerun_under_another_hash_seed(built, tmp_path):
    env = dict(os.environ, PYTHONHASHSEED="3")
    r = subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--out", str(tmp_path / "again")], env=env, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-800:]
    again = {p.name: p.read_bytes() for p in (tmp_path / "again").glob("*.json")}
    assert set(again) == set(built["files"])
    for n, text in built["files"].items():
        assert again[n] == text.encode(), n
    assert json.loads(r.stdout)["dataset_hash"] == built["manifest"]["dataset_hash"]


def test_the_manifest_does_not_use_the_wall_clock(built):
    assert "2026-10-2" not in json.dumps(built["manifest"]["generated_at"]) and built["manifest"]["generated_at"] == "2026-10-05T00:00:00Z"
    src = (ROOT / "data" / "generate.py").read_text()
    assert "datetime.now" not in src and "time.time()" not in src and "float(" not in src and "import random\n" in src


# ---------------------------------------------------------------------------------------------------------------------------------- the spec
def test_the_world_has_the_size_and_shape_of_the_brief(built):
    w, rows, m = built["w"], built["rows"], built["manifest"]
    assert len(rows["source_contracts"]) == 6 and all(s["freshness_target_seconds"] > 0 and s["expected_frequency"] for s in rows["source_contracts"])
    assert sorted({s["schema_version"] for s in rows["source_contracts"]}) == ["1", "2"] and [s["source_id"] for s in rows["source_contracts"] if s["schema_version"] == "2"] == ["src-payments"]
    assert 1250 <= len(rows["ingestion_batches"]) <= 1400
    assert 38_000 <= m["full_world"]["raw_records_written_in_all_batches"] <= 42_000 and m["full_world"]["domain_ingest_counts"]["raw_records"] == m["full_world"]["raw_records_written_in_all_batches"]
    assert len(rows["raw_records"]) <= 2000 and m["sample"]["raw_records_published"] == len(rows["raw_records"])
    assert len(rows["pipeline_runs"]) == 1343 and rows["pipeline_runs"][0]["started_at"] == "2026-08-10T01:15:00Z" and rows["pipeline_runs"][-1]["started_at"] == "2026-10-04T23:15:00Z"
    starts = [parse_ts(r["started_at"]) for r in rows["pipeline_runs"]]
    assert all((b - a).total_seconds() == 3600 for a, b in zip(starts, starts[1:]))
    assert len(rows["model_definitions"]) == 12 and {x["layer"] for x in rows["model_definitions"]} == {"staging", "intermediate", "marts"}
    for x in rows["model_definitions"]:
        assert x["definition_hash"] == hashlib.sha256(x["definition"].encode()).hexdigest()
    assert len(rows["incidents"]) == 25 and len(rows["backfill_requests"]) == 15 and len(rows["task_runs"]) > len(rows["pipeline_runs"]) * 3
    assert len(rows["quality_results"]) > len(rows["pipeline_runs"]) * 4 and 1300 <= len(rows["publications"]) <= 1343
    assert {r["rule_name"] for r in rows["quality_results"]} == {"keys_unique", "relationships_intact", "reconciliation_residual_zero", "freshness_within_target", "completeness_vs_expectation"}
    # attempts: some task has more than one attempt, some run has a terminally failed task
    assert any(t["attempt"] > 1 for t in rows["task_runs"]) and any(t["status"] == "failed" for t in rows["task_runs"])
    # checkpoints are consecutive per source and in commit order
    by = {}
    for c in sorted(rows["checkpoints"], key=lambda c: (c["committed_at"], c["checkpoint_id"])):
        by.setdefault(c["source_id"], []).append(c["version_number"])
    assert all(v == list(range(1, len(v) + 1)) for v in by.values()) and len(by) == 6
    # cursors: each live checkpoint cursor is the cursor its batch returned
    batch = {b["batch_id"]: b for b in rows["ingestion_batches"]}
    assert all(batch[c["batch_id"]]["status"] == "committed" for c in rows["checkpoints"])
    assert {b["status"] for b in rows["ingestion_batches"]} == {"committed", "aborted", "quarantined"}


def test_sources_have_expectations_and_a_schema_bump_on_2026_09_15(built):
    rows = built["rows"]
    parts = {(e["source_id"], e["partition"]) for e in rows["source_expectations"]}
    assert len(parts) == len(rows["source_expectations"]) == 6 * 56 and min(p for _, p in parts) == "2026-08-10" and max(p for _, p in parts) == "2026-10-04"
    q = [b for b in rows["ingestion_batches"] if b["status"] == "quarantined"]
    assert len(q) == 1 and q[0]["source_id"] == "src-payments" and q[0]["started_at"].startswith("2026-09-15") and q[0]["schema_version"] == "2"
    pay = [b for b in rows["ingestion_batches"] if b["source_id"] == "src-payments" and b["status"] == "committed"]
    assert all(("schema_version" in b) == (b["started_at"] >= "2026-09-15") for b in pay)
    assert all(r["reason_code"] == "SCHEMA_CHANGED" for r in rows["quarantine_records"] if r["batch_id"] == q[0]["batch_id"])


def test_size_cap_and_sampling_are_disclosed(built):
    m, rows = built["manifest"], built["rows"]
    s = m["sample"]
    summaries = {x["batch_id"]: x for x in rows["batch_summaries"]}
    sampled = {r["batch_id"] for r in rows["raw_records"]}
    flagged = {b for b, x in summaries.items() if x["sampled"]}
    assert s["batches_in_all"] == len(rows["ingestion_batches"]) and s["batches_sampled"] == len(flagged)
    assert flagged - sampled == {b for b in flagged if summaries[b]["written_rows"] == 0} and sampled <= flagged     # an empty batch has no row to sample
    for b in sampled:                                  # a sampled batch is whole: its rows are exactly written_rows
        assert sum(1 for r in rows["raw_records"] if r["batch_id"] == b) == summaries[b]["written_rows"]
    assert sum(x["written_rows"] for x in summaries.values()) == m["full_world"]["raw_records_written_in_all_batches"]
    text = " ".join(m["generator"]["disclosures"])
    assert "SAMPLE" in text and "2,000" in text and "outcome" in text.lower()


# ---------------------------------------------------------------------------------------------------------------------------------- the domain
def test_the_domain_ingests_the_complete_world_with_the_counts_the_manifest_states(built):
    b, m = built["b"], built["manifest"]
    counts = {k: v["accepted"] for k, v in b.golden["ingest"]["counts"].items()}
    assert counts == m["full_world"]["domain_ingest_counts"]
    assert {k: v["rejected"] for k, v in b.golden["ingest"]["counts"].items() if v["rejected"]} == {"backfill_requests": 2} == m["full_world"]["domain_rejected"]
    assert [r["id"] for r in b.golden["ingest"]["rejected_records"]] == ["bf-006", "bf-012"] and {r["reason_code"] for r in b.golden["ingest"]["rejected_records"]} == {"BACKFILL_OVERLAP"}
    for k in ("ingestion_batches", "checkpoints", "pipeline_runs", "task_runs", "quality_results", "publications", "incidents", "model_definitions", "quarantine_records"):
        assert counts[k] == len(b.w.ents[k]) == m["full_world"]["row_counts"][k], k
    assert b.golden["empty_population"] is False and b.golden["contract_version"] == 1


def test_the_domain_ingests_the_published_files_with_the_counts_the_manifest_states(built):
    m, rows = built["manifest"], built["rows"]
    inputs = {**m["config"], "source_expectations": rows["source_expectations"]}
    for k in gen.DOMAIN12:
        inputs[k] = rows[k]
    from pipeline_observatory import run_pipeline
    res = run_pipeline(inputs)
    assert {k: v["accepted"] for k, v in res.counts.items()} == m["sample"]["published_world"]["domain_ingest_counts"]
    assert res.metrics["ingestion"]["overall"] == m["sample"]["published_world"]["ingestion_overall"]
    assert len(res.rejected) == 2 and res.metrics["publications"]["current_publication_id"] == m["sample"]["published_world"]["current_publication_id"]


def test_the_metrics_the_manifest_states_are_the_domains(built):
    b, st = built["b"], built["manifest"]["stats"]
    m = b.golden["metrics"]
    assert st["ingestion"]["overall"] == m["ingestion"]["overall"] and st["freshness_at_as_of"] == m["freshness"]
    assert st["runs"]["overall"] == m["runs"]["overall"] and st["runs"]["successful"]["count"] == m["runs"]["durations"]["successful"]["count"]
    assert st["incidents"]["mean_recovery_minutes"] == m["incidents"]["mean_recovery_minutes"] and st["processing_rate"] == m["processing_rate"]
    assert st["backfills"]["overall"] == m["backfills"]["overall"] and st["late_events"]["count"] == m["late_events"]["count"]
    assert st["publications"]["current_publication_id"] == m["publications"]["current_publication_id"]
    assert st["quality_gate"] == {"allowed": 1318, "blocked": 25}
    # the headline rates are stated to six places and are the exact ratios of the counts
    o = m["ingestion"]["overall"]
    assert o["rejection_rate"] == gen.rnd6(o["quarantined"], o["received"]) and o["duplicate_rate"] == gen.rnd6(o["duplicate"], o["received"])
    assert o["received"] == o["accepted_unique"] + o["duplicate"] + o["quarantined"] + sum(1 for r in built["w"].batches if r.status == "committed" for x in r.rows if x["disp"] == "deleted")
    assert st["processing_rate"]["records_per_second"] == gen.rnd6(st["processing_rate"]["accepted_records"] * 1000, int(st["processing_rate"]["measured_seconds"].replace(".", "")))


def test_the_domain_classifies_every_raw_record_as_the_generator_constructed_it(built):
    """Two implementations of D-01: the generator's mirror (used to plan the gate) and the domain's classify_rows over the same rows."""
    b, w = built["b"], built["w"]
    n = 0
    for batch in w.committed:
        for i, r in enumerate(batch.rows, 1):
            d = b.facts.disposition[w.raw_id(batch, i)]
            assert (d.kind, d.reason) == (r["disp"], r["reason"]), (batch.batch_id, i, r["label"], d, r["disp"], r["reason"])
            n += 1
    assert n == b.golden["metrics"]["ingestion"]["overall"]["received"] > 38_000
    # every quarantined row of a committed batch has its quarantine row (nothing dropped) and every batch agrees
    sources = b.golden["metrics"]["ingestion"]["sources"]
    assert all(v["quarantine_rows_match"] for s in sources.values() for v in s["batches"].values() if v["counted"])
    # no key is accepted twice in a source, whatever the batches
    seen = set()
    for a in b.facts.accepted:
        assert (a.source_id, a.key) not in seen
        seen.add((a.source_id, a.key))


def test_batch_summaries_are_the_domains_counts_for_every_batch(built):
    b = built["b"]
    ing = b.golden["metrics"]["ingestion"]["sources"]
    for x in built["rows"]["batch_summaries"]:
        v = ing[x["source_id"]]["batches"][x["batch_id"]]
        assert v["status"] == x["status"] and v["written_rows"] == x["written_rows"]
        if x["status"] == "committed":
            assert (v["received"], v["accepted_unique"], v["duplicate"], v["quarantined"]) == (x["received"], x["accepted_unique"], x["duplicate"], x["quarantined"])
            assert sum(x["quarantine_by_reason"].values()) == x["quarantined"]
        else:
            assert v["counted"] is False and x["received"] == 0


def test_every_publication_reconciles_hashes_and_the_gate_is_fail_closed(built):
    b, rows = built["b"], built["rows"]
    m = b.golden["metrics"]
    assert all(r["residual"] == "0.00" for r in m["reconciliation"].values()) and len(m["reconciliation"]) == 1318
    assert all(p["content_hash_ok"] for p in m["publications"]["publications"].values())
    assert all(p["lag_seconds"] is not None and p["lag_seconds"] > 0 for p in m["publications"]["publications"].values())
    runs = {r["run_id"]: r for r in rows["pipeline_runs"]}
    pub = {p["run_id"]: p for p in rows["publications"]}
    for rid, r in runs.items():
        assert (r["status"] == "success") == (rid in pub) == (m["quality_gate"][rid]["decision"] == "allowed" and r["status"] == "success"), rid
        if rid in pub:
            assert pub[rid]["published_at"] == r["finished_at"] and parse_ts(pub[rid]["watermark"]) < parse_ts(pub[rid]["published_at"])
    # the pointer moves only to a passed candidate and never regresses
    hist = m["publications"]["pointer_history"]
    prev = None
    for h in hist:
        if h["gate_decision"] == "allowed" and runs[h["run_id"]]["status"] == "success":
            assert h["pointer_after"] == f"pub-{h['run_id'][4:]}"
        else:
            assert h["pointer_after"] == prev
        prev = h["pointer_after"]
    # the gate's numbers agree with the domain's for every published run
    results = {}
    for q in rows["quality_results"]:
        results.setdefault(q["task_run_id"].rsplit("-", 1)[0].replace("tr-", "run-"), {})[q["rule_name"]] = q
    pubs = m["publications"]["publications"]
    for rid, p in pub.items():
        res = results[rid]
        assert res["keys_unique"]["eligible_count"] == res["relationships_intact"]["eligible_count"] == pubs[p["publication_id"]]["published_records"]
        assert res["freshness_within_target"]["failure_count"] == 0 and res["freshness_within_target"]["eligible_count"] == len({b_["source_id"] for b_ in rows["ingestion_batches"] if b_["batch_id"] in p["included_batch_ids"]})
        assert all(x["failure_count"] <= x["eligible_count"] for x in res.values())


def test_incidents_are_verified_recoveries_the_domain_agrees_with(built):
    b, rows = built["b"], built["rows"]
    inc = b.golden["metrics"]["incidents"]
    assert (inc["total"], inc["open"], inc["closed"], inc["verified"]) == (25, 0, 25, 25)
    assert all(v["closure_consistent"] and v["verified"] and v["recovery_seconds"] > 0 for v in inc["incidents"].values())
    failed = {r["run_id"] for r in rows["pipeline_runs"] if r["status"] == "failed"}
    assert failed == {i["run_id"] for i in rows["incidents"]} and len(failed) == 25
    for i in rows["incidents"]:
        run = next(r for r in rows["pipeline_runs"] if r["run_id"] == i["run_id"])
        assert i["opened_at"] == run["finished_at"] and i["status"] == "closed" and i["recovery_run_id"] > i["run_id"]
    kinds = built["manifest"]["stats"]["incidents"]["by_type"]
    assert kinds == {"freshness": 5, "gate_infra": 3, "ingest": 3, "relationships": 4, "residual": 1, "transform": 9}


def test_backfills_cover_partitions_and_two_overlaps_are_refused(built):
    b, rows = built["b"], built["rows"]
    bf = b.golden["metrics"]["backfills"]
    assert bf["refused"] == ["bf-006", "bf-012"] and len(bf["requests"]) == 13
    assert bf["overall"]["requested_partitions"] == sum(r["requested_partitions"] for r in bf["requests"].values()) and 0 < bf["overall"]["verified_partitions"] < bf["overall"]["requested_partitions"]
    ranges = {r["backfill_id"]: r for r in rows["backfill_requests"]}
    assert ranges["bf-006"]["source_id"] == ranges["bf-004"]["source_id"] and ranges["bf-006"]["start_at"] < ranges["bf-004"]["end_at"] and ranges["bf-004"]["start_at"] < ranges["bf-006"]["end_at"]
    assert ranges["bf-012"]["source_id"] == ranges["bf-010"]["source_id"] and ranges["bf-012"]["start_at"] < ranges["bf-010"]["end_at"] and ranges["bf-010"]["start_at"] < ranges["bf-012"]["end_at"]
    # a partition is verified exactly when the backfill delivered every expected record of it
    exp = {(e["source_id"], e["partition"]): e["expected_records"] for e in rows["source_expectations"]}
    comp = b.golden["metrics"]["completeness"]
    for r in rows["backfill_requests"]:
        if r["backfill_id"] in bf["refused"]:
            assert not any(p["verified"] for p in r["partitions"])
            continue
        for p in r["partitions"]:
            got = comp[r["source_id"]][p["partition"]]
            assert p["verified"] == (got["accepted_records"] >= exp[(r["source_id"], p["partition"])]), (r["backfill_id"], p)
    assert sorted(r["backfill_id"] for r in rows["pipeline_runs"] if r["backfill_id"]) == sorted(k for k in bf["requests"])


# ---------------------------------------------------------------------------------------------------------------------------------- designed relationships
def dr(built, ident):
    return next(d for d in built["inj"]["designed_relationships"] if d["id"] == ident)


def test_dr01_a_source_is_stale_for_three_days_while_its_jobs_stay_green(built):
    b, rows = built["b"], built["rows"]
    r = dr(built, "DR-01")["realised"]
    f = b.golden["metrics"]["freshness"]["src-refunds"]
    assert r["freshness_seconds"] == f["freshness_seconds"] >= 3 * 86400 and r["ingestion_age_seconds"] == f["ingestion_age_seconds"] < 6 * 3600
    assert r["runs_in_window"] == r["runs_succeeded"] == r["runs_allowed_by_the_gate"] == 72
    assert set(r["completeness"].values()) == {"0.000000"} and len(r["completeness"]) == 3 and r["committed_batches_in_window"] >= 11
    assert r["latest_accepted_event_at"].startswith("2026-10-01T2")
    # no incident touches the window and every other source is fresh
    assert all(i["opened_at"] < "2026-10-02" for i in rows["incidents"])
    for sid, v in b.golden["metrics"]["freshness"].items():
        if sid != "src-refunds":
            assert v["freshness_seconds"] < 2 * 86400, sid
    target = next(s["freshness_target_seconds"] for s in rows["source_contracts"] if s["source_id"] == "src-refunds")
    assert target > r["freshness_seconds"]                         # the gate is blind to it: the target is looser than the silence


def test_dr02_a_failed_run_never_replaces_the_publication(built):
    r = dr(built, "DR-02")["realised"]
    assert r["run_status"] == "failed" and r["gate_decision"] == "blocked" and r["critical_failures"] == 1 and r["publication_exists"] is False
    assert r["pointer_unchanged"] is True and r["pointer_before"] == r["pointer_after"]
    # the pointer never points at a run that failed
    rows = built["rows"]
    failed = {x["run_id"] for x in rows["pipeline_runs"] if x["status"] == "failed"}
    assert not any(h["pointer_after"] and f"run-{h['pointer_after'][4:]}" in failed for h in built["b"].golden["metrics"]["publications"]["pointer_history"])
    assert not any(p["run_id"] in failed for p in rows["publications"])


def test_dr03_the_rate_limited_source_honours_retry_after(built):
    rows = built["rows"]["fetch_log"]
    fm = built["b"].dom.mod["fetch"]
    limited = [r for r in rows if r["status"] == "rate_limited"]
    assert len(limited) >= 20 and {r["source_id"] for r in limited} == {"src-shipments"} and all(r["retry_after_seconds"] in (30, 60, 90, 120) for r in limited)
    sess = {}
    for r in rows:
        sess.setdefault((r["source_id"], r["session_id"]), []).append(r)
    n = 0
    for seq in sess.values():
        seq.sort(key=lambda r: (r["fetched_at"], r["fetch_id"]))
        for i, r in enumerate(seq):
            if r["status"] == "rate_limited":
                fm.check_retry_allowed(parse_ts(r["fetched_at"]), r["retry_after_seconds"], parse_ts(seq[i + 1]["fetched_at"]))      # raises RETRY_TOO_SOON otherwise
                assert seq[i + 1]["cursor_value"] == r["cursor_value"]
                n += 1
        assert seq[-1]["status"] == "ok" or seq[-1]["status"] == "cursor_loop"
    d = dr(built, "DR-03")["realised"]
    assert n == d["retries"] == d["retries_honouring_retry_after"] == len(limited) and d["retries_too_soon"] == 0 and d["min_slack_seconds"] >= 0


def test_dr04_late_events_are_counted_and_included_in_the_next_publication(built):
    b = built["b"]
    r = dr(built, "DR-04")["realised"]
    late = b.golden["metrics"]["late_events"]
    assert late["lost"] == 0 and late["included_in_next_publication"] == late["count"] and r["designed_events"] == 9 == len(r["designed"])
    pubs = {p["publication_id"]: p for p in built["rows"]["publications"]}
    for d in r["designed"]:
        behind, nxt = pubs[d["behind_publication_id"]], pubs[d["included_in_publication_id"]]
        assert parse_ts(d["event_at"]) <= parse_ts(behind["watermark"]) < parse_ts(d["arrival_at"]) and parse_ts(behind["published_at"]) < parse_ts(d["arrival_at"]) < parse_ts(nxt["published_at"])
    assert sum(r["by_cause"].values()) == late["count"]
    # a late event is also an accepted record: the late batch is committed and its record enters the published count
    assert late["count"] == len(late["events"]) and all(e["included_in_publication_id"] for e in late["events"])


def test_dr05_the_residual_is_zero_except_one_day(built):
    b = built["b"]
    r = dr(built, "DR-05")["realised"]
    assert r["publications_with_nonzero_residual"] == 0 and len(r["candidates_with_nonzero_residual"]) == 1 and r["days_with_nonzero_residual"] == ["2026-09-09"]
    c = r["candidates_with_nonzero_residual"][0]
    leak = next(x for x in built["w"].batches if x.batch_id == r["leak_batch_id"])
    assert leak.status == "aborted" and c["residual"] == "-" + gen.cents(sum(x["ev"].amount for x in [y for y in leak.rows if y["label"] == "ok"][:3]))
    from decimal import Decimal
    assert Decimal(c["source_total"]) - Decimal(c["published_total"]) - Decimal(c["exclusions_total"]) == Decimal(c["residual"])
    inc = next(i for i in built["rows"]["incidents"] if i["incident_id"] == r["incident_id"])
    assert inc["run_id"] == c["run_id"] == r["incident_run_id"] and inc["severity"] == "critical"
    res = next(q for q in built["rows"]["quality_results"] if q["task_run_id"].startswith("tr-" + c["run_id"][4:] + "-") and q["rule_name"] == "reconciliation_residual_zero")
    assert res["failure_count"] == 1 and b.golden["metrics"]["quality_gate"][c["run_id"]]["decision"] == "blocked"
    assert b.golden["metrics"]["incidents"]["incidents"][r["incident_id"]]["verified"] is True


# ---------------------------------------------------------------------------------------------------------------------------------- injections
def test_the_manifest_lists_twelve_injections_with_their_tests(built):
    inj = built["inj"]["injections"]
    assert [i["id"] for i in inj] == [f"INJ-{n:02d}" for n in range(1, 13)] and [i["test"] for i in inj] == [f"P08-TEST-{n:02d}" for n in range(1, 13)]
    events = {e["event_id"]: e for e in built["inj"]["events"]}
    assert sorted(events) == [f"EV-{n:02d}" for n in range(1, 13)]
    for i in inj:
        assert i["defect"] and i["expected_handling"] and i["location"] in ("both", "replay", "world") and i["events"] and all(e in events for e in i["events"])
        assert events[i["events"][0]]["injection"] == i["id"]
    assert [r["id"] for r in inj[1]["expected_rejections"]] == ["bf-006", "bf-012"] and {r["reason_code"] for r in inj[1]["expected_rejections"]} == {"BACKFILL_OVERLAP"}


def test_every_record_an_injection_points_at_exists_and_every_check_holds(built):
    rows, golden = built["rows"], built["b"].golden
    ids = {"raw_records": "raw_record_id", "ingestion_batches": "batch_id", "checkpoints": "checkpoint_id", "backfill_requests": "backfill_id", "fetch_log": "fetch_id",
           "pipeline_runs": "run_id", "quality_results": "quality_result_id", "incidents": "incident_id", "publications": "publication_id", "source_contracts": "source_id",
           "quarantine_records": "quarantine_id"}
    for inj in built["inj"]["injections"]:
        for rec in inj["records"]:
            assert any(r[ids[rec["entity"]]] == rec["id"] for r in rows[rec["entity"]]), (inj["id"], rec)
        assert inj["checks"] or inj["id"] in ("INJ-03", "INJ-10", "INJ-11", "INJ-12")
        for c in inj["checks"]:
            check(golden, c)


def test_injection_01_the_crashed_batch_counts_for_nothing_and_no_key_is_accepted_twice(built):
    b, w = built["b"], built["w"]
    inj = built["inj"]["injections"][0]
    a_id = inj["evidence"]["aborted_batch"]
    A, R = w.by_id[a_id], w.by_id[inj["evidence"]["replay_batch"]]
    assert A.status == "aborted" and A.commit is None and not any(c["batch_id"] == a_id for c in built["rows"]["checkpoints"])
    assert [x["payload"] for x in A.rows] == [x["payload"] for x in R.rows] and A.cursor_from == R.cursor_from
    keys = {x["key"] for x in A.rows if x["label"] == "ok"}
    accepted = [a for a in b.facts.accepted if a.key in keys and a.source_id == A.src]
    assert len(accepted) == len({a.key for a in accepted}) == inj["evidence"]["accepted_by_the_replay"] and {a.batch_id for a in accepted} == {R.batch_id}


def test_injection_04_the_schema_change_quarantines_the_whole_batch_and_the_bump_is_explicit(built):
    ev = built["inj"]["injections"][3]["evidence"]
    rows = built["rows"]
    q = [r for r in rows["quarantine_records"] if r["batch_id"] == ev["quarantined_batch"]]
    assert len(q) == ev["rows_quarantined_whole"] and {r["reason_code"] for r in q} == {"SCHEMA_CHANGED"}
    assert not any(c["batch_id"] == ev["quarantined_batch"] for c in rows["checkpoints"])
    assert ev["bumped_at"] > next(b for b in rows["ingestion_batches"] if b["batch_id"] == ev["quarantined_batch"])["started_at"]
    new = [x for x in built["w"].by_id[ev["refetch_batch"]].rows]
    assert all("channel" in x["payload"] for x in new)


def test_injection_05_the_malformed_row_is_quarantined_not_dropped(built):
    ev = built["inj"]["injections"][4]["evidence"]
    raw = next(r for r in built["b"].w.ents["raw_records"] if r["raw_record_id"] == ev["raw_record_id"])
    assert raw["source_key"] is None and "record_id" not in raw["payload_json"]
    d = built["b"].facts.disposition[ev["raw_record_id"]]
    assert (d.kind, d.reason) == ("quarantined", "MISSING_FIELD")
    assert any(q["batch_id"] == ev["batch"] and q["source_key"] is None and q["reason_code"] == "MISSING_FIELD" for q in built["rows"]["quarantine_records"])


def test_injection_08_a_delete_leaves_the_snapshot_and_shows_as_an_exclusion(built):
    b = built["b"]
    ev = built["inj"]["injections"][7]["evidence"]
    m = b.golden["metrics"]
    last, first = m["reconciliation"][ev["last_publication_with_the_record"]], m["reconciliation"][ev["first_publication_without_it"]]
    assert last["exclusions"]["deletes"] == "0.00" and first["exclusions"]["deletes"] != "0.00" and first["residual"] == "0.00"
    de = built["w"].delete_event
    assert [a.deleted_in for a in b.facts.accepted if a.key == de.key] == [ev["deleted_in"]]
    unknown = [r for r in b.w.ents["quarantine_records"] if r["reason_code"] == "DELETE_TARGET_UNKNOWN"]
    assert len(unknown) >= 1
    # a repeated delete is a duplicate, never a second exclusion
    assert sum(1 for x in b.w.committed for r in x.rows if r["label"] == "del" and r["disp"] == "duplicate") >= 1


def test_injection_10_the_repeating_cursor_is_a_loop_in_the_fetch_log_and_creates_no_batch(built):
    rows = built["rows"]["fetch_log"]
    loops = [r for r in rows if r["status"] == "cursor_loop"]
    assert len(loops) == 1 and loops[0]["next_cursor"] == loops[0]["cursor_value"] and loops[0]["batch_id"] is None
    nxt = next(r for r in rows if r["source_id"] == loops[0]["source_id"] and r["status"] == "ok" and r["cursor_value"] == loops[0]["cursor_value"] and r["fetched_at"] > loops[0]["fetched_at"])
    assert nxt["session_id"] != loops[0]["session_id"] and nxt["next_cursor"] != nxt["cursor_value"]


def test_injections_11_and_12_the_redaction_and_the_workflow_guard(built):
    inj = built["inj"]["injections"]
    ev = inj[10]["evidence"]
    mod = built["b"].dom.mod
    clean = mod["redaction"].safe_line(ev["log_line"])
    assert clean == ev["redacted_by_the_domain"] and not any(s in clean for s in ev["secrets"]) and "[REDACTED]" in clean
    assert mod["redaction"].contains_secret(ev["log_line"]) and not mod["redaction"].contains_secret(clean)
    ev12 = inj[11]["evidence"]
    assert [f["code"] for f in ev12["findings"]] == ["SELF_PUSH"]
    assert mod["workflow_guard"].analyze(ev12["fixed_text"], ev12["workflow_file"]) == []


def test_the_text_of_the_secrets_is_obviously_synthetic(built):
    text = json.dumps(built["inj"])
    assert "SYNTHETIC" in text and not re.search(r"gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abprs]-|sk-live", text)


# ---------------------------------------------------------------------------------------------------------------------------------- the API replays
REPLAY = [f"EV-{n:02d}" for n in range(1, 13)]


def _subset(got, want, path=""):
    if isinstance(want, dict):
        assert isinstance(got, dict), (path, got)
        for k, v in want.items():
            assert k in got, (path + "." + k, got)
            _subset(got[k], v, path + "." + k)
    else:
        assert got == want, (path, got, want)


@pytest.fixture
def loaded(built, db_url):
    """The published files seeded into PostgreSQL (the API's start state for every event)."""
    import psycopg
    from psycopg.rows import dict_row
    from data import seed
    m, rows = built["manifest"], built["rows"]
    inputs = {**m["config"], "source_expectations": rows["source_expectations"]}
    for k in gen.DOMAIN12:
        inputs[k] = rows[k]
    with psycopg.connect(db_url, row_factory=dict_row, autocommit=True) as conn:
        with conn.transaction():
            seed.seed(conn, inputs, dataset_version=m["dataset_version"], dataset_hash=m["dataset_hash"])
        yield conn


@pytest.mark.parametrize("event_id", REPLAY)
def test_each_recorded_event_replays_as_recorded(built, loaded, client, event_id):
    from api.app import PREFIX
    ev = next(e for e in built["inj"]["events"] if e["event_id"] == event_id)
    mod = built["b"].dom.mod
    for n, s in enumerate(ev["steps"]):
        where = f"{event_id} step {n}"
        if s["kind"] == "check":
            fn = s["fn"]
            if fn == "redaction.safe_line":
                out = mod["redaction"].safe_line(s["args"]["line"])
                assert all(x in out for x in s["expect_contains"]) and not any(x in out for x in s["expect_not_contains"]), where
            else:
                found = [f.code for f in mod["workflow_guard"].analyze(s["args"]["text"], s["args"]["file_name"])]
                assert found == s["expect_codes"], (where, found)
            continue
        at(s["at"])
        if s["kind"] == "command":
            r = client.post(f"{PREFIX}/commands/{s['command']}", json=s["input"], headers=s["headers"])
            assert r.status_code == s["expected_status"], (where, r.status_code, r.text[:600])
            body = r.json()
            if "expected_reason" in s:
                assert [d["rule_id"] for d in body["error"]["details"]][0] == s["expected_reason"], (where, body)
            if "expected_body" in s:
                _subset(body, s["expected_body"], where)
            if "expected_warning_codes" in s:
                assert [w["code"] for w in body["warnings"]] == s["expected_warning_codes"], (where, body["warnings"])
            for k, v in s.get("expected_headers", {}).items():
                assert r.headers[k] == v, (where, k, r.headers.get(k))
        else:
            r = client.get(f"{PREFIX}{s['path']}", params=s["params"])
            assert r.status_code == s["expected_status"], (where, r.text[:600])
            for c in s["expect"]:
                check(r.json(), c)
