"""Writes scripts/snapshot-reference.json: what the PYTHON domain (domain/pipeline_observatory) and plain Python arithmetic compute over the
published snapshot in web/public/data, so CI can compare the TypeScript mirror without Python. Run once, from apps/pipeline-observatory:

    ../../.venv/bin/python web/scripts/make-snapshot-reference.py

Contents (nothing is read from the TypeScript side):
  * dataset: manifest hash/version, the dataset_hash recomputed from the 16 entity files, a no-float scan of every published file;
  * sample_world: the domain's run_pipeline over the published files (the 2,000-row raw sample, the stored candidate totals as published totals):
    ingest counts, a sha256 digest of each of the eleven metric blocks, and the headline figures in clear;
  * windows: GET /metrics cases (half-open windows, a cutoff, one source), each as block digests;
  * complete_world: the figures the published files carry in full (batch_summaries, runs, gates, pointer, fetch_log, checkpoints), computed here by
    plain Python, the incidents through the domain's verified_recovery with the generator's recorded 'every publication reconciles to 0.00';
  * claims: the designed-relationship figures re-derived, and every injection-manifest check evaluated over the sample world;
  * hashes: payload_hash of every sampled raw row, definition_hash of every model, content_hash of every publication, recomputed.
The domain's parse_ts is memoised at runtime exactly as data/generate.py does (the domain files are untouched).
"""
import functools
from datetime import timedelta
import hashlib
import json
import re
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "domain"))
from pipeline_observatory import backfill, classify, fetch, hashing, ingest, metrics, reconcile, scope, timeutil  # noqa: E402
from pipeline_observatory.contract import ENTITIES, METRIC_KEYS  # noqa: E402
from pipeline_observatory.timeutil import iso_z, parse_ts, seconds_between  # noqa: E402

_memo = functools.lru_cache(maxsize=None)(timeutil.parse_ts)
for _m in (reconcile, metrics, classify, ingest, scope, backfill, fetch):
    if hasattr(_m, "parse_ts"):
        _m.parse_ts = _memo
parse_ts = _memo

DATA = ROOT / "web" / "public" / "data"
manifest = json.loads((DATA / "manifest.json").read_text())
injm = json.loads((DATA / "injection-manifest.json").read_text())
PUBLISHED = sorted([*ENTITIES, "source_expectations", "model_output_totals", "batch_summaries", "fetch_log"])


def refuse(x):
    raise AssertionError(f"a float literal ({x}) in a published file")


texts = {n: (DATA / f"{n}.json").read_text() for n in PUBLISHED}
files = {n: json.loads(t, parse_float=refuse)["rows"] for n, t in texts.items()}
json.loads((DATA / "manifest.json").read_text(), parse_float=refuse)
json.loads((DATA / "injection-manifest.json").read_text(), parse_float=refuse)


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(v):
    return hashlib.sha256(canon(v).encode()).hexdigest()


dataset_hash = hashlib.sha256("".join(canon(files[n]) for n in PUBLISHED).encode()).hexdigest()

# ------------------------------------------------------------------------------------------------------------------------------- sample world
data = dict(manifest["config"])
for e in ENTITIES:
    data[e] = files[e]
data["source_expectations"] = files["source_expectations"]
imp = ingest.validate_import(data)
params = metrics.params_of(data)
total_of_run = {t["run_id"]: t["total_amount"] for t in files["model_output_totals"]}
params["published_totals"] = {p["publication_id"]: Decimal(total_of_run[p["run_id"]]) for p in imp.accepted["publications"] if p["run_id"] in total_of_run}
g = metrics.compute(imp.accepted, imp.rejected, params)
M = g["metrics"]
acc = imp.accepted


def block_digests(shape):
    return {k: digest(shape["metrics"][k]) for k in METRIC_KEYS}


def headline(shape):
    m = shape["metrics"]
    pubs = m["publications"]["publications"]
    recon = m["reconciliation"]
    fresh = {s: [v["latest_accepted_event_at"], v["freshness_seconds"], v["last_successful_ingestion_at"], v["ingestion_age_seconds"]] for s, v in m["freshness"].items()}
    comp = [[s, d, v["expected_records"], v["accepted_records"], v["value"]] for s, days in sorted(m["completeness"].items()) for d, v in sorted(days.items())]
    inc = m["incidents"]
    return {
        "ingest_counts": shape["ingest"]["counts"], "rejected": [[r["entity"], r["id"], r["reason_code"]] for r in shape["ingest"]["rejected_records"]],
        "ingestion_overall": m["ingestion"]["overall"], "empty_population": shape["empty_population"],
        "publications": {"current": m["publications"]["current_publication_id"], "count": len(pubs), "content_hash_ok": sum(1 for p in pubs.values() if p["content_hash_ok"]),
                         "published_records": sum(p["published_records"] for p in pubs.values())},
        "late_events": {k: m["late_events"][k] for k in ("count", "included_in_next_publication", "lost")},
        "incidents": {k: inc[k] for k in ("total", "open", "closed", "verified", "mean_recovery_minutes")},
        "reconciliation": {"publications": len(recon), "residual_zero": sum(1 for r in recon.values() if r["residual"] == "0.00"), "digest": digest(recon)},
        "backfills": {"overall": m["backfills"]["overall"], "refused": m["backfills"]["refused"]},
        "processing_rate": m["processing_rate"], "runs_overall": m["runs"]["overall"],
        "durations": {k: {"count": v["count"], "mean_minutes": v["mean_minutes"]} for k, v in m["runs"]["durations"].items()},
        "gate": {"allowed": sum(1 for v in m["quality_gate"].values() if v["decision"] == "allowed"), "blocked": sum(1 for v in m["quality_gate"].values() if v["decision"] == "blocked"),
                 "reached_gate": sum(1 for v in m["quality_gate"].values() if v["results"])},
        "freshness": fresh, "completeness_partitions": len(comp), "completeness_digest": digest(comp)}


sample_world = {"digests": block_digests(g), "headline": headline(g), "shape_digest": digest(g)}

# ------------------------------------------------------------------------------------------------------------------------------- windows
runs_sorted = sorted(acc["pipeline_runs"], key=lambda r: (parse_ts(r["started_at"]), r["run_id"]))
r731 = next(r for r in runs_sorted if r["run_id"] == "run-0731")
r732 = next(r for r in runs_sorted if r["run_id"] == "run-0732")
a_batch = next(b for b in acc["checkpoints"] if b["batch_id"] == "b-0848")      # a committed-at instant used as both a cutoff and a window end


def window_case(name, source=None, lo=None, hi=None, cutoff=None):
    when = cutoff or g["cutoff"]
    scoped = scope.restrict(acc, source, lo, hi, parse_ts(when))
    p = dict(params)
    p["as_of"] = p["cutoff"] = iso_z(parse_ts(when))
    p["source_expectations"] = scope.restrict_expectations(params["source_expectations"], source, lo, hi, parse_ts(when))
    pm = p["processing_measurement"]
    if pm is not None and pm["batch_id"] not in {b["batch_id"] for b in scoped["ingestion_batches"]}:
        p["processing_measurement"] = None
    shape = metrics.compute(scoped, imp.rejected, p)
    return {"name": name, "source_id": source, "from": lo, "to": hi, "cutoff": when, "digests": block_digests(shape), "empty_population": shape["empty_population"],
            "raw_records": len(scoped["raw_records"]), "runs": len(scoped["pipeline_runs"]), "publications": len(scoped["publications"]), "batches": len(scoped["ingestion_batches"]),
            "ingestion_overall": shape["metrics"]["ingestion"]["overall"], "pointer": shape["metrics"]["publications"]["current_publication_id"]}


windows = [
    window_case("the whole world", None, None, None, None),
    window_case("one UTC day, 2026-09-09 (the unexplained residual)", None, "2026-09-09T00:00:00Z", "2026-09-10T00:00:00Z"),
    window_case("exactly one run: [run-0731.started_at, run-0732.started_at)", None, r731["started_at"], r732["started_at"]),
    window_case("an empty window: [t, t)", None, r731["started_at"], r731["started_at"]),
    window_case("a cutoff of 2026-09-20T12:00:00Z", None, None, None, "2026-09-20T12:00:00Z"),
    window_case("one source, the last five days", "src-refunds", "2026-09-30T00:00:00Z", "2026-10-05T00:00:00Z"),
    window_case("cutoff equal to a checkpoint commit instant (b-0848 drops at equality)", None, None, None, a_batch["committed_at"]),
    window_case("a window ending exactly at a run start", None, "2026-09-09T10:00:00Z", r731["started_at"]),
]

# ------------------------------------------------------------------------------------------------------------------------------- complete world
sources = sorted(s["source_id"] for s in files["source_contracts"])


def totals(rows):
    t = {"batches": len(rows), "received": sum(r["received"] for r in rows), "accepted_unique": sum(r["accepted_unique"] for r in rows), "duplicate": sum(r["duplicate"] for r in rows),
         "deleted": sum(r.get("deleted", 0) for r in rows), "quarantined": sum(r["quarantined"] for r in rows)}
    by = {}
    for r in rows:
        for k, n in r["quarantine_by_reason"].items():
            by[k] = by.get(k, 0) + n
    t["rejection_rate"] = metrics.p6(metrics.ratio(t["quarantined"], t["received"]))
    t["duplicate_rate"] = metrics.p6(metrics.ratio(t["duplicate"], t["received"]))
    t["quarantine_by_reason"] = dict(sorted(by.items()))
    return t


summ = files["batch_summaries"]
committed_sum = [s for s in summ if s["status"] == "committed"]
by_kind, by_status = {}, {}
for s in summ:
    k = by_kind.setdefault(s["kind"], {"batches": 0, "written_rows": 0})
    k["batches"] += 1
    k["written_rows"] += s["written_rows"]
    by_status[s["status"]] = by_status.get(s["status"], 0) + 1
ingestion_world = {"overall": totals(committed_sum), "sources": {sid: totals([s for s in committed_sum if s["source_id"] == sid]) for sid in sources},
                   "by_kind": dict(sorted(by_kind.items())), "by_status": dict(sorted(by_status.items())),
                   "sampled_batches": sum(1 for s in summ if s["sampled"]), "sampled_rows": sum(s["written_rows"] for s in summ if s["sampled"])}

# retry behaviour from fetch_log, independently written
fl = sorted(files["fetch_log"], key=lambda r: r["fetch_id"])
limited = [i for i, r in enumerate(fl) if r["status"] == "rate_limited"]
slacks, sessions = [], set()
for i in limited:
    r = fl[i]
    sessions.add(r["session_id"])
    nxt = next((x for x in fl[i + 1:] if x["session_id"] == r["session_id"] and x["cursor_value"] == r["cursor_value"]), None)
    if nxt is not None:
        slacks.append(seconds_between(r["fetched_at"], nxt["fetched_at"]) - r["retry_after_seconds"])
retry = {"fetch_rows": len(fl), "rate_limited_responses": len(limited), "retries": len(slacks), "retries_honouring_retry_after": sum(1 for s in slacks if s >= 0),
         "retries_too_soon": sum(1 for s in slacks if s < 0), "sessions_rate_limited": len(sessions), "min_slack_seconds": min(slacks), "max_slack_seconds": max(slacks),
         "cursor_loops": sum(1 for r in fl if r["status"] == "cursor_loop"), "sources_rate_limited": sorted({fl[i]["source_id"] for i in limited}),
         "by_status": {k: sum(1 for r in fl if r["status"] == k) for k in sorted({r["status"] for r in fl})}}

gate_of = {rid: v["decision"] for rid, v in M["quality_gate"].items()}
pub_of_run = {p["run_id"]: p["publication_id"] for p in acc["publications"]}
pub_at = {p["publication_id"]: p["published_at"] for p in acc["publications"]}
reconciled = {p["publication_id"]: "0.00" for p in acc["publications"]}
failed_checks = {rid: [[rule, v["severity"], v["failures"], v["eligible"]] for rule, v in gate["results"].items() if not v["passed"]] for rid, gate in M["quality_gate"].items()}
RULE_CLASS = {"relationships_intact": "relationships", "freshness_within_target": "freshness", "reconciliation_residual_zero": "residual", "keys_unique": "keys"}
task_final = {}
for t in sorted(acc["task_runs"], key=lambda t: (t["run_id"], t["task_name"], int(t["attempt"]))):
    task_final[(t["run_id"], t["task_name"])] = (int(t["attempt"]), t["status"])
inc_rows, total_sec, n_ver, by_class = [], 0, 0, {}
for i in sorted(acc["incidents"], key=lambda i: i["incident_id"]):
    found = reconcile.verified_recovery(i["opened_at"], acc["pipeline_runs"], gate_of, pub_of_run, reconciled)
    at = iso_z(parse_ts(pub_at[found["publication_id"]])) if found else None
    sec = seconds_between(i["opened_at"], at) if found else None
    fc = failed_checks[i["run_id"]]
    ft = [[task, att] for (rid, task), (att, st) in sorted(task_final.items()) if rid == i["run_id"] and st == "failed"]
    cls = RULE_CLASS.get(fc[0][0], fc[0][0]) if fc else ("gate_infra" if ft and ft[0][0] == "quality_gate" else ft[0][0] if ft else "unclassified")
    by_class[cls] = by_class.get(cls, 0) + 1
    consistent = i["status"] != "closed" or (found is not None and i.get("recovery_run_id") == found["run"]["run_id"] and parse_ts(i["closed_at"]) == parse_ts(at))
    inc_rows.append({"incident_id": i["incident_id"], "run_id": i["run_id"], "severity": i["severity"], "opened_at": iso_z(parse_ts(i["opened_at"])), "recovery_run_id": found["run"]["run_id"] if found else None,
                     "verified_at": at, "recovery_seconds": sec, "recovery_minutes": reconcile.recovery_minutes(sec), "consistent": consistent, "class": cls, "failed_checks": fc, "failed_tasks": ft})
    if found:
        n_ver += 1
        total_sec += sec
incidents_world = {"total": len(inc_rows), "verified": n_ver, "mean_recovery_minutes": reconcile.mean_minutes(total_sec, n_ver), "by_class": dict(sorted(by_class.items())),
                   "all_consistent": all(r["consistent"] for r in inc_rows), "incidents_digest": digest(inc_rows), "first": inc_rows[0], "run_1187": next(r for r in inc_rows if r["run_id"] == "run-1187")}


def cadence(freq):
    f = freq.strip().lower()
    if f == "hourly": return 3600
    if f == "daily": return 86400
    if f == "weekly": return 604800
    m = re.match(r"^every (\d+) (minute|hour|day)s?$", f)
    return int(m.group(1)) * {"minute": 60, "hour": 3600, "day": 86400}[m.group(2)] if m else None


cut = parse_ts(g["cutoff"])
cp_of = {c["batch_id"]: c for c in acc["checkpoints"]}
recorded_event = {s: v["latest_accepted_event_at"] for s, v in manifest["stats"]["freshness_at_as_of"].items()}
fresh_rows = []
for s in sorted(files["source_contracts"], key=lambda s: s["source_id"]):
    sid = s["source_id"]
    mine = [b for b in files["ingestion_batches"] if b["source_id"] == sid]
    ing = max((parse_ts(cp_of[b["batch_id"]]["committed_at"]) for b in mine if b["status"] == "committed" and b["batch_id"] in cp_of))
    age = seconds_between(ing, cut)
    fresh = seconds_between(recorded_event[sid], cut)
    cad = cadence(s["expected_frequency"])
    cads = Fraction(fresh, cad)
    last = max(mine, key=lambda b: (parse_ts(b["started_at"]), b["batch_id"]))
    recent = {}
    for b in mine:
        if timedelta(0) <= cut - parse_ts(b["started_at"]) < timedelta(hours=72):
            recent[b["status"]] = recent.get(b["status"], 0) + 1
    fresh_rows.append({"source_id": sid, "ingestion_age_seconds": age, "freshness_seconds": fresh, "sample_freshness_seconds": M["freshness"][sid]["freshness_seconds"], "cadences": metrics.m4(cads), "silent": cads > 2,
                       "past_target": fresh > s["freshness_target_seconds"], "gap_seconds": fresh - age, "last_batch": [last["batch_id"], last["status"]], "batches_72h": dict(sorted(recent.items()))})

# the graph, independently
models = files["model_definitions"]
by_name = {m["model_name"]: m for m in models}
edges = set()
for m in models:
    for d in m.get("depends_on", []):
        edges.add((by_name[d]["model_id"], m["model_id"]))
    if m["layer"] == "staging":
        edges.add((re.search(r"source_id = '([^']+)'", m["definition"]).group(1), m["model_id"]))
for name in {p["dataset_name"] for p in files["publications"]}:
    edges.add((by_name[name]["model_id"], f"pub:{name}"))
graph = {"nodes": len(sources) + len(models) + 1, "edges": len(edges), "edges_digest": digest(sorted(edges))}

hist = M["publications"]["pointer_history"]
blocked_runs = sorted(rid for rid, d in gate_of.items() if d == "blocked")
complete_world = {"ingestion": ingestion_world, "retry": retry, "incidents": incidents_world, "freshness": fresh_rows, "graph": graph,
                  "pointer": {"current": M["publications"]["current_publication_id"], "history_digest": digest(hist), "history_length": len(hist), "blocked_runs": blocked_runs,
                              "pointer_never_moved_by_blocked": all(h["pointer_after"] == hist[k - 1]["pointer_after"] for k, h in enumerate(hist) if k and h["gate_decision"] == "blocked")},
                  "runs": {"overall": M["runs"]["overall"], "durations": {k: {"count": v["count"], "mean_minutes": v["mean_minutes"]} for k, v in M["runs"]["durations"].items()}},
                  "quality_results_per_rule": {r: sum(1 for q in files["quality_results"] if q["rule_name"] == r) for r in sorted({q["rule_name"] for q in files["quality_results"]})},
                  "backfills": M["backfills"], "models": {layer: sum(1 for m in models if m["layer"] == layer) for layer in ("staging", "intermediate", "marts")}}

# ------------------------------------------------------------------------------------------------------------------------------- claims
def get(obj, path):
    for k in path.split("."):
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj


def check(shape, c):
    if c.get("absent"):
        try:
            get(shape, c["path"])
        except (KeyError, IndexError):
            return True
        return False
    try:
        v = get(shape, c["path"])
    except (KeyError, IndexError):
        return False
    if "find" in c:
        hits = [x for x in v if all(x.get(k) == w for k, w in c["find"].items())]
        return len(hits) == 1 and all(hits[0][k] == w for k, w in c["equals"].items())
    if "equals" in c:
        return v == c["equals"]
    if "min" in c:
        return v >= c["min"]
    if "max" in c:
        return v <= c["max"]
    if "contains" in c:
        return c["contains"] in v
    if "not_contains" in c:
        return c["not_contains"] not in v
    return False


inj_results = [[i["id"], c["path"], check(g, c)] for i in injm["injections"] for c in i["checks"]]

dr = {d["id"]: d for d in manifest["designed_relationships"]}
claims = {}
as_of = parse_ts(manifest["as_of"])
R1, P1 = dr["DR-01"]["realised"], dr["DR-01"]["parameters"]
sid1 = P1["source_id"]
stops = parse_ts(P1["stops_at"])
in_win = lambda t: stops <= parse_ts(t) < as_of  # noqa: E731
runs_w = [r for r in files["pipeline_runs"] if in_win(r["started_at"])]
bat_w = [b for b in files["ingestion_batches"] if b["source_id"] == sid1 and b["status"] == "committed" and in_win(b["started_at"])]
sum_of = {s["batch_id"]: s for s in summ}
f1 = next(f for f in fresh_rows if f["source_id"] == sid1)
claims.update({
    "DR-01:ingestion_age_seconds": f1["ingestion_age_seconds"],
    "DR-01:last_successful_ingestion_at": iso_z(max(parse_ts(cp_of[b["batch_id"]]["committed_at"]) for b in files["ingestion_batches"] if b["source_id"] == sid1 and b["status"] == "committed" and b["batch_id"] in cp_of)),
    "DR-01:runs_in_window": len(runs_w), "DR-01:runs_succeeded": sum(1 for r in runs_w if r["status"] == "success"), "DR-01:runs_allowed_by_the_gate": sum(1 for r in runs_w if gate_of[r["run_id"]] == "allowed"),
    "DR-01:committed_batches_in_window": len(bat_w), "DR-01:accepted_in_window": sum(sum_of[b["batch_id"]]["accepted_unique"] for b in bat_w),
    "DR-01:duplicates_in_window": sum(sum_of[b["batch_id"]]["duplicate"] for b in bat_w), "DR-01:batches_with_no_accepted_record": sum(1 for b in bat_w if sum_of[b["batch_id"]]["accepted_unique"] == 0)})
for day in R1["completeness"]:
    claims[f"DR-01:completeness.{day}"] = M["completeness"][sid1][day]["value"]
rid2 = dr["DR-02"]["realised"]["run_id"]
k2 = next(k for k, h in enumerate(hist) if h["run_id"] == rid2)
inc2 = next(r for r in inc_rows if r["run_id"] == rid2)
claims.update({"DR-02:run_status": next(r for r in files["pipeline_runs"] if r["run_id"] == rid2)["status"], "DR-02:pointer_unchanged": hist[k2]["pointer_after"] == hist[k2 - 1]["pointer_after"], "DR-02:gate_decision": gate_of[rid2], "DR-02:critical_failures": M["quality_gate"][rid2]["critical_failures"], "DR-02:publication_exists": rid2 in pub_of_run,
               "DR-02:pointer_before": hist[k2 - 1]["pointer_after"], "DR-02:pointer_after": hist[k2]["pointer_after"], "DR-02:pointer_history_index": k2,
               "DR-02:incident_id": inc2["incident_id"], "DR-02:recovery_run_id": inc2["recovery_run_id"], "DR-02:recovery_minutes": inc2["recovery_minutes"]})
for k in ("fetch_rows", "rate_limited_responses", "retries", "retries_honouring_retry_after", "retries_too_soon", "sessions_rate_limited", "min_slack_seconds", "max_slack_seconds", "cursor_loops", "sources_rate_limited"):
    claims[f"DR-03:{k}"] = retry[k]
claims["DR-03:fetch_log_statuses"] = retry["by_status"]
ev = {e["source_key"]: e for e in M["late_events"]["events"]}
for d in dr["DR-04"]["realised"]["designed"]:
    e = ev.get(d["source_key"])
    claims[f"DR-04:designed.{d['source_key']}"] = None if e is None else {k: e[k] for k in ("source_key", "event_at", "arrival_at", "behind_publication_id", "included_in_publication_id", "watermark")}
rid5 = dr["DR-05"]["realised"]["incident_run_id"]
inc5 = next(r for r in inc_rows if r["run_id"] == rid5)
claims.update({"DR-05:publications": len(files["publications"]), "DR-05:incident_id": inc5["incident_id"], "DR-05:gate": gate_of[rid5], "DR-05:failed_check": failed_checks[rid5][0][0],
               "DR-05:recovery_run_id": inc5["recovery_run_id"], "DR-05:recovery_minutes": inc5["recovery_minutes"],
               "DR-05:leak_batch_status": next(b for b in files["ingestion_batches"] if b["batch_id"] == dr["DR-05"]["realised"]["leak_batch_id"])["status"],
               "DR-05:candidate_total": total_of_run[rid5]})

# ------------------------------------------------------------------------------------------------------------------------------- hashes
raws = files["raw_records"]
hash_checks = {
    "raw_payload_hash_ok": sum(1 for r in raws if hashing.payload_hash(r["payload_json"]) == r["payload_hash"]), "raw_rows": len(raws),
    "definition_hash_ok": sum(1 for m in models if hashing.definition_hash(m["definition"]) == m["definition_hash"]), "models": len(models),
    "publication_content_hash_ok": M and sum(1 for p in M["publications"]["publications"].values() if p["content_hash_ok"]), "publications": len(files["publications"]),
    "dataset_hash_ok": dataset_hash == manifest["dataset_hash"]}

ref = {"generated_by": "web/scripts/make-snapshot-reference.py (the Python domain, domain/pipeline_observatory, and plain Python over web/public/data)",
       "dataset": {"dataset_hash": manifest["dataset_hash"], "dataset_version": manifest["dataset_version"], "as_of": manifest["as_of"], "dataset_hash_recomputed": dataset_hash,
                   "row_counts": {n: len(files[n]) for n in PUBLISHED}, "no_float_tokens": True},
       "sample_world": sample_world, "windows": windows, "complete_world": complete_world,
       "claims": {"designed": claims, "injection": inj_results, "injection_holding": sum(1 for r in inj_results if r[2])},
       "hashes": hash_checks}
(Path(__file__).resolve().parent / "snapshot-reference.json").write_text(json.dumps(ref, sort_keys=True, indent=1) + "\n")
print("wrote snapshot-reference.json:", len(canon(ref)), "bytes of canonical JSON;", len(windows), "window cases;", len(claims), "designed figures;", len(inj_results), "injection checks")
print("dataset_hash recomputed equals the manifest's:", dataset_hash == manifest["dataset_hash"])
