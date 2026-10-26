#!/usr/bin/env python3
"""Independent reference calculation for the Onboard Studio golden fixtures.

Standard library only. Imports nothing from the application. Every number is
recomputed from inputs.json with decimal.Decimal and plain interval arithmetic,
then compared with expected.json (durations exact at 4 dp, rates exact at 6 dp).

Usage:
  python3 reference_check.py                # check everything, exit 0 only if all OK
  python3 reference_check.py --write-hashes # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
FOUR = Decimal("0.0001")
SIX = Decimal("0.000001")
SECONDS_PER_HOUR = Decimal(3600)
FIXTURES = ["", "variant-rejected/", "variant-empty/"]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENTITIES = ["organizations", "cases", "workflow_versions", "step_definitions", "dependencies",
            "step_instances", "assignments", "document_versions", "approvals", "sla_rules",
            "calendar_intervals", "waiting_intervals", "case_events"]
ID_KEY = {"organizations": "organization_id", "cases": "case_id", "workflow_versions": "workflow_version_id",
          "step_definitions": "step_definition_id", "dependencies": "dependency_id",
          "step_instances": "step_instance_id", "assignments": "assignment_id",
          "document_versions": "document_version_id", "approvals": "approval_id", "sla_rules": "sla_rule_id",
          "calendar_intervals": "calendar_interval_id", "waiting_intervals": "waiting_interval_id",
          "case_events": "event_id"}

failures = 0


def report(ok, name, expected, got):
    global failures
    if ok:
        print(f"OK {name} {got}")
    else:
        failures += 1
        print(f"MISMATCH {name} expected {expected} got {got}")


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def seconds(a, b):
    return Decimal(int((b - a).total_seconds()))


def hours(secs):
    return secs / SECONDS_PER_HOUR


def d4(x):
    return None if x is None else str(x.quantize(FOUR, rounding=ROUND_HALF_UP))


def d6(x):
    return None if x is None else str(x.quantize(SIX, rounding=ROUND_HALF_UP))


def ratio(num, den):
    return None if den == 0 else Decimal(num) / Decimal(den)


def mean(values):
    return None if not values else sum(values, Decimal(0)) / len(values)


def overlap_seconds(start, end, intervals):
    """Seconds of [start, end) that fall inside the working intervals (explicit arithmetic)."""
    total = Decimal(0)
    for ci_start, ci_end in intervals:
        lo = max(start, ci_start)
        hi = min(end, ci_end)
        if hi > lo:
            total += seconds(lo, hi)
    return total


def ingest(data):
    """Rule SELF_APPROVAL: an approval whose reviewer is any assignee of the same step
    instance is rejected, and so is everything that depends on its case (the case, its
    step instances, assignments, documents, approvals, waiting intervals and events)."""
    assignees = {}
    for a in data["assignments"]:
        assignees.setdefault(a["step_instance_id"], set()).add(a["assignee_id"])
    step_case = {s["step_instance_id"]: s["case_id"] for s in data["step_instances"]}
    bad_cases = {step_case[a["step_instance_id"]] for a in data["approvals"]
                 if a["reviewer_id"] in assignees.get(a["step_instance_id"], set())}
    bad_steps = {s for s, c in step_case.items() if c in bad_cases}
    owner = {"cases": lambda r: r["case_id"],
             "step_instances": lambda r: r["case_id"],
             "assignments": lambda r: step_case[r["step_instance_id"]],
             "document_versions": lambda r: r["case_id"],
             "approvals": lambda r: step_case[r["step_instance_id"]],
             "waiting_intervals": lambda r: r["case_id"],
             "case_events": lambda r: r["case_id"]}
    accepted, rejected = {}, []
    for ent in ENTITIES:
        accepted[ent] = []
        for row in data[ent]:
            if ent in owner and owner[ent](row) in bad_cases:
                rejected.append({"entity": ent, "id": row[ID_KEY[ent]], "status": "rejected",
                                 "reason_code": "SELF_APPROVAL", "raw_row": row})
            else:
                accepted[ent].append(row)
    rejected.sort(key=lambda r: (r["entity"], r["id"]))
    return accepted, rejected


def compute(data, acc, pause_policy, cutoffs):
    """All metrics for one state. pause_policy replaces sla_rules[*].pause_policy."""
    calendars = {}
    for ci in acc["calendar_intervals"]:
        calendars.setdefault(ci["calendar_id"], []).append((ts(ci["starts_at"]), ts(ci["ends_at"])))
    sla = {r["workflow_version_id"]: r for r in acc["sla_rules"]}
    cases = acc["cases"]
    completed = [c for c in cases if c["completed_at"] is not None]

    cal_h, bus_h, paused_h, pov_h, act_h, within = [], [], [], [], [], 0
    for c in completed:
        rule = sla[c["workflow_version_id"]]
        working = calendars[rule["calendar_id"]]
        opened, done = ts(c["opened_at"]), ts(c["completed_at"])
        calendar = hours(seconds(opened, done))                      # completed_at - opened_at
        business = hours(overlap_seconds(opened, done, working))     # sum of overlaps with working intervals
        paused = Decimal(0)                                          # eligible waiting, calendar hours
        paused_business = Decimal(0)                                 # business overlap of eligible waiting
        for w in acc["waiting_intervals"]:
            if w["case_id"] == c["case_id"] and w["reason_code"] in pause_policy:
                ws, we = ts(w["starts_at"]), ts(w["ends_at"])
                paused += hours(seconds(ws, we))
                paused_business += hours(overlap_seconds(ws, we, working))
        active = business - paused_business
        cal_h.append(calendar); bus_h.append(business); paused_h.append(paused)
        pov_h.append(paused_business); act_h.append(active)
        if active * 60 <= rule["business_minutes"]:
            within += 1

    open_backlog = {}
    for cut in cutoffs:
        t = ts(cut)
        open_backlog[cut] = sum(1 for c in cases if ts(c["opened_at"]) <= t and
                                (c["completed_at"] is None or ts(c["completed_at"]) > t))

    # rework: cases with a rejected submission / cases with a submission
    docs_by_case = {}
    for d in acc["document_versions"]:
        docs_by_case.setdefault(d["case_id"], []).append(d)
    submitted_cases = [c for c in cases if docs_by_case.get(c["case_id"])]
    reworked = [c for c in submitted_cases
                if any(d["review_status"] == "rejected" for d in docs_by_case[c["case_id"]])]

    # first pass: first submission (lowest version per case and type), reviewed ones only
    firsts = {}
    for d in acc["document_versions"]:
        k = (d["case_id"], d["document_type"])
        if k not in firsts or d["version_number"] < firsts[k]["version_number"]:
            firsts[k] = d
    reviewed = [d for d in firsts.values() if d["review_status"] in ("accepted", "rejected")]
    first_ok = [d for d in reviewed if d["review_status"] == "accepted"]

    # completeness: required accepted types present / required types, over accepted cases
    req_total = req_ok = 0
    for c in cases:
        required = data["workflow_requirements"][c["workflow_version_id"]]["required_document_types"]
        accepted_types = {d["document_type"] for d in docs_by_case.get(c["case_id"], [])
                          if d["review_status"] == "accepted"}
        req_total += len(required)
        req_ok += sum(1 for t in required if t in accepted_types)

    # handoffs: assignments per step instance minus one
    per_step = {}
    for a in acc["assignments"]:
        per_step[a["step_instance_id"]] = per_step.get(a["step_instance_id"], 0) + 1
    handoffs = sum(n - 1 for n in per_step.values())

    # step waiting: business hours from ready to first work, mean per step definition
    case_wv = {c["case_id"]: c["workflow_version_id"] for c in cases}
    waits = {sd["step_definition_id"]: [] for sd in data["step_definitions"]}
    for si in acc["step_instances"]:
        if si["started_at"] is None or si["ready_at"] is None:
            continue
        working = calendars[sla[case_wv[si["case_id"]]]["calendar_id"]]
        waits[si["step_definition_id"]].append(
            hours(overlap_seconds(ts(si["ready_at"]), ts(si["started_at"]), working)))

    return {
        "calendar_cycle_time_hours": d4(mean(cal_h)),
        "business_cycle_time_hours": d4(mean(bus_h)),
        "paused_time_hours": d4(mean(paused_h)),
        "paused_business_overlap_hours": d4(mean(pov_h)),
        "active_elapsed_hours": d4(mean(act_h)),
        "sla_attainment": d6(ratio(within, len(completed))),
        "completed_eligible_cases": len(completed),
        "within_sla_cases": within,
        "open_backlog_at_cutoff": open_backlog,
        "rework_rate": d6(ratio(len(reworked), len(submitted_cases))),
        "handoff_count": handoffs,
        "step_waiting_time_hours": {k: d4(mean(v)) for k, v in sorted(waits.items())},
        "first_pass_approval": d6(ratio(len(first_ok), len(reviewed))),
        "document_completeness": d6(ratio(req_ok, req_total)),
        "empty_population": len(cases) == 0,
    }


def check_fixture(prefix):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    label = prefix.rstrip("/") or "golden"

    # informational integrity: definition_hash = sha256 of canonical steps + dependencies
    for wv in data["workflow_versions"]:
        steps = [[s["step_definition_id"], s["step_name"], s["required"], s["role_key"], s["sequence"]]
                 for s in sorted(data["step_definitions"], key=lambda s: s["sequence"])
                 if s["workflow_version_id"] == wv["workflow_version_id"]]
        sids = {s[0] for s in steps}
        deps = [[d["step_definition_id"], d["prerequisite_id"], d["dependency_type"]]
                for d in sorted(data["dependencies"], key=lambda d: d["dependency_id"])
                if d["step_definition_id"] in sids]
        h = hashlib.sha256(json.dumps({"steps": steps, "dependencies": deps}, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
        report(h == wv["definition_hash"], f"{label}.definition_hash[{wv['workflow_version_id']}]",
               wv["definition_hash"], h)

    accepted, rejected = ingest(data)
    for ent in ENTITIES:
        e = exp["ingest"]["counts"][ent]
        report(e == {"accepted": len(accepted[ent]), "rejected": sum(1 for r in rejected if r["entity"] == ent)},
               f"{label}.ingest.{ent}", e, f"accepted={len(accepted[ent])}")
    report(rejected == exp["ingest"]["rejected_records"], f"{label}.ingest.rejected_records",
           [(r["entity"], r["id"], r["reason_code"]) for r in exp["ingest"]["rejected_records"]],
           [(r["entity"], r["id"], r["reason_code"]) for r in rejected])

    for state, spec in exp["states"].items():
        override = data["states"][state]["sla-001"]["pause_policy"]
        report(override == spec["pause_policy"], f"{label}.{state}.pause_policy", spec["pause_policy"], override)
        got = compute(data, accepted, override, data["cutoffs"])
        for k, want in spec["metrics"].items():
            report(got.get(k) == want, f"{label}.{state}.{k}", want, got.get(k))
        report(set(got) == set(spec["metrics"]), f"{label}.{state}.metric_names", sorted(spec["metrics"]), sorted(got))

    # the rejected variant must equal the golden totals
    if prefix == "variant-rejected/":
        gold = json.loads((GOLDEN / "expected.json").read_text())
        report(gold["states"] == exp["states"], f"{label}.totals_equal_golden", "equal", "equal"
               if gold["states"] == exp["states"] else "different")


def sha(path):
    return hashlib.sha256((GOLDEN / path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true")
    args = ap.parse_args()
    for prefix in FIXTURES:
        check_fixture(prefix)
    hashes_path = GOLDEN / "HASHES.json"
    if args.write_hashes:
        if failures:
            print(f"NOT WRITING HASHES: {failures} mismatch(es)")
        else:
            hashes_path.write_text(json.dumps({"algorithm": "sha256", "sha256": {p: sha(p) for p in HASHED}}, indent=2) + "\n")
            print(f"OK wrote {hashes_path.name}")
    elif hashes_path.exists():
        stored = json.loads(hashes_path.read_text())["sha256"]
        for p in HASHED:
            report(stored.get(p) == sha(p), f"hash[{p}]", stored.get(p), sha(p))
    print("ALL OK" if not failures else f"{failures} MISMATCH(ES)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
