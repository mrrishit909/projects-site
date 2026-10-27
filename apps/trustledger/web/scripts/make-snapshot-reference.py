"""Writes scripts/snapshot-reference.json: what the PYTHON domain (domain/trustledger) computes over the published snapshot in
web/public/data, so CI can compare the TypeScript mirror without Python. Run once, from apps/trustledger:

    ../../.venv/bin/python web/scripts/make-snapshot-reference.py

Contents: sha256 digests (canonical JSON, sorted keys, compact) of every metric block, the rules, definitions and matching blocks at the
as-of 2026-10-05 and at two earlier as-of instants (2026-09-14, 2026-08-17), each under the version in force and under w1 and w2 (the
match precision reads the manifest's synthetic truth, in the verification layer only); a half-open window case; the complete headline
blocks at the as-of (the figures the pages show); the class of every issue; and the zone probes (the UTC instant of a local time on every
day of 2026 and the evaluated occurrence around both DST transitions of each zone) that Intl must reproduce.
"""
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "domain"))
from trustledger.contract import ENTITIES, METRIC_KEYS  # noqa: E402
from trustledger.metrics import compute  # noqa: E402
from trustledger.pipeline import run_pipeline  # noqa: E402
from trustledger.timeutil import iso_z, latest_occurrence, local_to_utc, parse_hhmm, parse_ts, scheduled_occurrence, timeliness_state  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
manifest = json.loads((DATA / "manifest.json").read_text())
files = {n: json.loads((DATA / f"{n}.json").read_text())["rows"] for n in [*ENTITIES, "dataset_rows", "quality_rule_versions", "weight_versions"]}

inputs = json.loads(json.dumps(manifest["config"]))
for k in ENTITIES:
    inputs[k] = files[k]
grouped = {}
for r in files["dataset_rows"]:
    r = dict(r)
    grouped.setdefault(r.pop("dataset_id"), []).append(r)
inputs["dataset_rows"] = grouped
inputs["weight_versions"] = files["weight_versions"]
truth = manifest["synthetic_truth"]["true_entity"]
res = run_pipeline(inputs, truth=truth)
pop = res.population


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(v):
    return hashlib.sha256(canon(v).encode()).hexdigest()


def block_digests(c):
    out = {k: digest(c.metrics[k]) for k in METRIC_KEYS}
    out["rules"] = digest(c.rules)
    out["definitions"] = digest(c.definitions)
    out["matching"] = digest(c.matching)
    return out


def summary(c):
    return {"weight_version": c.weight_version, "empty_population": c.empty_population,
            "warning_codes": sorted(w["code"] for w in c.warnings), "digests": block_digests(c),
            "issue_classes": {k: sum(1 for v in c.views if v.cls == k) for k in ("resolved", "claimed", "open")},
            "issue_class_digest": digest([[v.issue.issue_id, v.cls] for v in c.views])}


AS_OFS = ["2026-10-05T00:00:00Z", "2026-09-14T00:00:00Z", "2026-08-17T00:00:00Z"]
asofs = {}
for t in AS_OFS:
    when = parse_ts(t)
    asofs[t] = {"default": summary(compute(pop, when, None, None, truth))}
    for wv in ("w1", "w2"):
        asofs[t][wv] = summary(compute(pop, when, wv, None, truth))

win = (parse_ts("2026-09-01T00:00:00Z"), parse_ts("2026-09-20T00:00:00Z"))
c_win = compute(pop, parse_ts(AS_OFS[0]), None, win, truth)
window_case = {"from": "2026-09-01T00:00:00Z", "to": "2026-09-20T00:00:00Z", **summary(c_win)}

c0 = compute(pop, parse_ts(AS_OFS[0]), None, None, truth)
m = c0.metrics
full = {k: m[k] for k in ("completeness", "validity", "uniqueness", "relationship_integrity", "timeliness", "weighted_score", "critical_failures",
                          "ownership_coverage", "definition_coverage", "match_precision", "lineage_coverage")}
resolution = {k: v for k, v in m["resolution_time"].items() if k != "issues"}
issues_view = {iid: [b["class"], b["resolution_hours"], b["claimed_hours"], b["age_hours"], b["reopen_cycles"]] for iid, b in m["resolution_time"]["issues"].items()}
matching_head = {k: v for k, v in c0.matching.items() if k not in ("identity_map", "mapping_history")}

# ---- zone probes -----------------------------------------------------------------------------------------------------------------
zones = sorted({d["refresh_timezone"] for d in files["datasets"] if d["refresh_timezone"]} | {"Europe/Berlin", "America/Chicago", "UTC"})
locals_ = ["00:00", "01:00", "01:30", "02:00", "02:30", "03:00", "06:00"]
l2u = {}
for z in zones:
    out = []
    d0 = date(2026, 1, 1)
    for n in range(365):
        day = d0 + timedelta(days=n)
        for lt in locals_:
            out.append(iso_z(local_to_utc(day, parse_hhmm(lt), z)))
    l2u[z] = {"count": len(out), "digest": digest(out)}
occ = {}
WINDOWS = [("2026-03-07T00:00:00Z", "2026-03-10T00:00:00Z"), ("2026-03-28T00:00:00Z", "2026-03-31T00:00:00Z"),
           ("2026-10-24T00:00:00Z", "2026-10-27T00:00:00Z"), ("2026-10-31T00:00:00Z", "2026-11-03T00:00:00Z")]
for z in zones:
    out = []
    for a, b in WINDOWS:
        t, end = parse_ts(a), parse_ts(b)
        while t < end:
            for lt, g in (("02:30", 60), ("01:30", 30), ("06:00", 120), ("00:00", 0)):
                s, dl = scheduled_occurrence(z, lt, g, t)
                out.append([iso_z(s), iso_z(dl)])
            t += timedelta(minutes=30)
    occ[z] = {"count": len(out), "digest": digest(out)}
# D-10 R7-01: the latest occurrence STARTED by the instant, and the state of a dataset refreshed at five offsets from it, every 30 minutes around the same days
lat = {}
for z in zones:
    out = []
    for a, b in WINDOWS:
        t, end = parse_ts(a), parse_ts(b)
        while t < end:
            for lt, g in (("02:30", 60), ("01:30", 30), ("06:00", 120), ("00:00", 0)):
                s, dl = latest_occurrence(z, lt, g, t)
                out.append([iso_z(s), iso_z(dl)] + [timeliness_state(z, lt, g, t + timedelta(minutes=k), t)[0] for k in (-1440, -90, -30, 0, 45)])
            t += timedelta(minutes=30)
    lat[z] = {"count": len(out), "digest": digest(out)}

ref = {
    "generated_by": "scripts/make-snapshot-reference.py (the Python domain, domain/trustledger)",
    "dataset_hash": manifest["dataset_hash"], "dataset_version": manifest["dataset_version"], "as_of": manifest["as_of"],
    "ingest_counts": res.counts, "rejected_count": len(res.rejected),
    "as_ofs": asofs, "window_case": window_case,
    "full_at_as_of": full, "resolution_summary": resolution, "issues_at_as_of": issues_view, "matching_summary": matching_head,
    "identity_map_digest": digest(c0.matching["identity_map"]), "mapping_history_digest": digest(c0.matching["mapping_history"]),
    "rule_runs_at_as_of_digest": digest(c0.rules),
    "zone_probe": {"zones": zones, "local_times": locals_, "local_to_utc": l2u, "occurrence_windows": WINDOWS, "occurrences": occ, "latest_occurrences": lat},
    "dataset_hash_check": {"sha256_of_15_entity_files": hashlib.sha256("".join(
        json.dumps(files[n], sort_keys=True, separators=(",", ":")) for n in sorted(files)).encode()).hexdigest()},
}
(Path(__file__).resolve().parent / "snapshot-reference.json").write_text(json.dumps(ref, sort_keys=True, indent=1) + "\n")
print("wrote snapshot-reference.json:", len(canon(ref)), "bytes of canonical JSON;", len(asofs), "as-of instants")
print("dataset_hash check:", ref["dataset_hash_check"]["sha256_of_15_entity_files"] == manifest["dataset_hash"])
