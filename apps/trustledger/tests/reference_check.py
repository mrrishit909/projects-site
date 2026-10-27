#!/usr/bin/env python3
"""Independent reference calculation for the TrustLedger golden fixtures (P07-GOLD-01..11).

Standard library only; imports nothing from the application. Recomputes every figure in
expected.json from inputs.json (import validation and rejection, completeness with the whitespace
policy, validity both ways, uniqueness both ways, relationship integrity with null foreign keys,
timeliness on the dataset's schedule and IANA timezone, the weighted score under each weight version
with the critical override, rule-run comparability, disabled-rule history, ownership coverage,
definition coverage and versions, lineage coverage, issue resolution with verified reruns, canonical
match pairs, reversible merges and match precision against the synthetic truth) and compares leaf
by leaf. No float anywhere: fractions.Fraction for every ratio. Proportions are 6-place decimal
strings, hours 4-place, rounding ROUND_HALF_UP (CALCULATION.md, DECISIONS). Contract v1, D-01..D-05.

Usage:
  python3 -I reference_check.py                # check everything, exit 0 only if all OK
  python3 -I reference_check.py --write-hashes # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone, date, time
from fractions import Fraction as F
from pathlib import Path
from zoneinfo import ZoneInfo

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
FIXTURES = [("golden", ""), ("variant-rejected", "variant-rejected/"), ("variant-empty", "variant-empty/")]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENTITIES = ["owners", "datasets", "fields", "quality_rules", "rule_runs", "issues", "lineage_edges",
            "metric_versions", "definition_changes", "customer_records", "match_candidates", "merge_decisions"]
ID = {"owners": "owner_id", "datasets": "dataset_id", "fields": "field_id", "quality_rules": "rule_id",
      "rule_runs": "rule_run_id", "issues": "issue_id", "lineage_edges": "edge_id",
      "metric_versions": "metric_version_id", "definition_changes": "change_id",
      "customer_records": "record_id", "match_candidates": "candidate_id", "merge_decisions": "merge_id"}
DIMS = ["completeness", "validity", "uniqueness", "relationship", "timeliness"]
failures = 0
checks = 0


def report(ok, name, expected, got):
    global failures, checks
    checks += 1
    if ok:
        print(f"OK {name} {got}")
    else:
        failures += 1
        print(f"MISMATCH {name} expected {expected!r} got {got!r}")


# ---------------------------------------------------------------- number formats (D-05)
def rnd(x, dp):
    """ROUND_HALF_UP of a Fraction to dp places, as a string."""
    x = F(x)
    sign = "-" if x < 0 else ""
    x = abs(x)
    scaled = x * 10 ** dp
    n = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    whole, frac = divmod(n, 10 ** dp)
    s = f"{whole}.{frac:0{dp}d}" if dp else str(whole)
    return ("-" if sign and n else "") + s


def p6(x):
    return None if x is None else rnd(x, 6)


def h4(x):
    return None if x is None else rnd(x, 4)


def ratio(num, den):
    return None if den == 0 else F(num, den)


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def zstr(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours(a, b):
    return F(int((b - a).total_seconds()), 3600)


# ---------------------------------------------------------------- import validation
def blank(v, trim):
    return v is None or (isinstance(v, str) and v.strip(trim) == "")


def validate(data):
    """Return (accepted dict of lists, rejected records, counts). Rejection is atomic per record;
    a record whose parent was rejected is DEPENDENT_REJECTED (never silently dropped)."""
    trim = data["whitespace_policy"]["trim_characters"]
    rejected = []
    acc = {}
    rej_ids = {}

    def rej(entity, row, code):
        rejected.append({"entity": entity, "id": row[ID[entity]], "status": "rejected", "reason_code": code,
                         "raw_row": row})
        rej_ids.setdefault(entity, set()).add(row[ID[entity]])

    owners = {o["owner_id"]: o for o in data["owners"]}
    acc["owners"] = list(data["owners"])
    # datasets
    acc["datasets"] = []
    for d in data["datasets"]:
        o = owners.get(d.get("owner_id"))
        if blank(d.get("owner_id"), trim):
            rej("datasets", d, "OWNER_REQUIRED")
        elif o is None:
            rej("datasets", d, "UNKNOWN_OWNER")
        elif o["deactivated_at"] is not None and ts(d["registered_at"]) >= ts(o["deactivated_at"]):
            rej("datasets", d, "OWNER_INACTIVE")
        elif blank(d.get("classification"), trim):
            rej("datasets", d, "CLASSIFICATION_REQUIRED")
        else:
            acc["datasets"].append(d)
    ds_ok = {d["dataset_id"] for d in acc["datasets"]}
    ds_bad = rej_ids.get("datasets", set())

    def child(entity, rows, parent_ok, parent_bad, parent_key, unknown_code):
        acc[entity] = []
        for r_ in rows:
            p = r_[parent_key]
            if p in parent_ok:
                acc[entity].append(r_)
            elif p in parent_bad:
                rej(entity, r_, "DEPENDENT_REJECTED")
            else:
                rej(entity, r_, unknown_code)

    child("fields", data["fields"], ds_ok, ds_bad, "dataset_id", "UNKNOWN_DATASET")
    child("quality_rules", data["quality_rules"], ds_ok, ds_bad, "dataset_id", "UNKNOWN_DATASET")
    rule_ok = {r_["rule_id"] for r_ in acc["quality_rules"]}
    rule_bad = rej_ids.get("quality_rules", set())
    child("rule_runs", data["rule_runs"], rule_ok, rule_bad, "rule_id", "UNKNOWN_RULE")
    run_ok = {r_["rule_run_id"] for r_ in acc["rule_runs"]}
    run_bad = rej_ids.get("rule_runs", set())
    child("issues", data["issues"], run_ok, run_bad, "rule_run_id", "UNKNOWN_RULE_RUN")
    # lineage edges need both ends
    acc["lineage_edges"] = []
    for e in data["lineage_edges"]:
        ends = (e["source_dataset_id"], e["target_dataset_id"])
        if (e["evidence_type"] == "observed") != (e.get("observed_at") is not None):   # D-08
            rej("lineage_edges", e, "MALFORMED_RECORD")
        elif all(x in ds_ok for x in ends):
            acc["lineage_edges"].append(e)
        elif any(x in ds_bad for x in ends):
            rej("lineage_edges", e, "DEPENDENT_REJECTED")
        else:
            rej("lineage_edges", e, "UNKNOWN_DATASET")
    acc["metric_versions"] = list(data["metric_versions"])
    mv_ok = {m["metric_version_id"] for m in acc["metric_versions"]}
    acc["definition_changes"] = []
    for c in data["definition_changes"]:
        if c["metric_version_id"] in mv_ok:
            acc["definition_changes"].append(c)
        else:
            rej("definition_changes", c, "UNKNOWN_METRIC_VERSION")
    acc["customer_records"] = list(data["customer_records"])
    rec_ok = {r_["record_id"] for r_ in acc["customer_records"]}
    # match candidates: canonical order, once per pair
    acc["match_candidates"] = []
    seen = set()
    for c in data["match_candidates"]:
        l_, r_ = c["left_record_id"], c["right_record_id"]
        s = F(c["score"])
        if l_ not in rec_ok or r_ not in rec_ok:
            rej("match_candidates", c, "UNKNOWN_RECORD")
        elif l_ == r_:
            rej("match_candidates", c, "SAME_RECORD")
        elif not (0 <= s <= 1) or not c["features"] or blank(c["explanation"], trim):
            rej("match_candidates", c, "INVALID_CANDIDATE")
        elif (min(l_, r_), max(l_, r_)) in seen:
            rej("match_candidates", c, "DUPLICATE_PAIR")
        elif l_ > r_:
            rej("match_candidates", c, "NON_CANONICAL_ORDER")
        else:
            seen.add((l_, r_))
            acc["match_candidates"].append(c)
    cand = {c["candidate_id"]: c for c in acc["match_candidates"]}
    cand_bad = rej_ids.get("match_candidates", set())
    acc["merge_decisions"] = []
    mds = {}
    for m in sorted(data["merge_decisions"], key=lambda x: (x["decided_at"], x["merge_id"])):
        c = cand.get(m["candidate_id"])
        rev = owners.get(m["reviewer_id"])
        tgt = mds.get(m["reverses_merge_id"]) if m["decision"] == "reverse" else None
        if m["candidate_id"] in cand_bad:
            rej("merge_decisions", m, "DEPENDENT_REJECTED")
        elif m["decision"] == "reverse" and tgt is None:
            code = "DEPENDENT_REJECTED" if m["reverses_merge_id"] in rej_ids.get("merge_decisions", set()) else "UNKNOWN_MERGE"
            rej("merge_decisions", m, code)
        elif c is None or rev is None:
            rej("merge_decisions", m, "UNKNOWN_CANDIDATE")
        elif m["reviewer_id"] == c["proposed_by"]:
            rej("merge_decisions", m, "REVIEWER_IS_PROPOSER")
        elif rev["role"] not in ("steward", "admin") or not rev["active"]:
            rej("merge_decisions", m, "ROLE_NOT_PERMITTED")
        else:
            acc["merge_decisions"].append(m)
            mds[m["merge_id"]] = m
    acc["merge_decisions"].sort(key=lambda x: x["merge_id"])
    # dataset rows follow their dataset
    acc["dataset_rows"] = {}
    rows_bad = 0
    for dsid, rows in data["dataset_rows"].items():
        if dsid in ds_ok:
            acc["dataset_rows"][dsid] = rows
        else:
            rows_bad += len(rows)
            rejected.append({"entity": "dataset_rows", "id": dsid, "status": "rejected",
                             "reason_code": "DEPENDENT_REJECTED" if dsid in ds_bad else "UNKNOWN_DATASET",
                             "raw_row": {"dataset_id": dsid, "rows": rows}})
    rejected.sort(key=lambda r_: (r_["entity"], r_["id"]))
    counts = {e: {"accepted": len(acc[e]), "rejected": len(rej_ids.get(e, ()))} for e in ENTITIES}
    counts["dataset_rows"] = {"accepted": sum(len(v) for v in acc["dataset_rows"].values()), "rejected": rows_bad}
    return acc, rejected, counts


# ---------------------------------------------------------------- measurement
def scheduled_occurrence(ds, as_of):
    """Latest local daily occurrence S (in the dataset's IANA zone) whose grace window has closed:
    S + grace <= as_of. Returns (S_utc, deadline_utc)."""
    tz = ZoneInfo(ds["refresh_timezone"])
    hh, mm = (int(x) for x in ds["refresh_local_time"].split(":"))
    grace = timedelta(minutes=ds["refresh_grace_minutes"])
    d0 = as_of.astimezone(tz).date()
    for back in range(-1, 4):
        d = d0 - timedelta(days=back)
        s = datetime.combine(d, time(hh, mm), tzinfo=tz).astimezone(timezone.utc)
        if s + grace <= as_of:
            return s, s + grace
    raise ValueError("no occurrence")


def compute(data):
    as_of = ts(data["as_of"])
    trim = data["whitespace_policy"]["trim_characters"]
    acc, rejected, counts = validate(data)
    owners = {o["owner_id"]: o for o in acc["owners"]}
    datasets = {d["dataset_id"]: d for d in acc["datasets"]}
    rules = {r_["rule_id"]: r_ for r_ in acc["quality_rules"]}
    runs = {r_["rule_run_id"]: r_ for r_ in acc["rule_runs"]}
    rows = acc["dataset_rows"]
    wv_in_force = data["weight_version"]
    weights = {w["weight_version"]: {k: F(v) for k, v in w["weights"].items()} for w in data["weight_versions"]}
    populated_total = sum(len(acc[e]) for e in ENTITIES) + sum(len(v) for v in rows.values())
    empty = populated_total == 0

    def missing(v):
        return blank(v, trim)

    # ---- active rule runs at as_of
    rr, comps, dim_val, ts_detail = {}, {}, {}, {}
    m_comp, m_valid, m_uniq, m_rel = {}, {}, {}, {}
    for rid in sorted(rules):
        rule = rules[rid]
        if rule["status"] != "active":
            continue
        dsid = rule["dataset_id"]
        ds = datasets[dsid]
        d = rule["definition"]
        run = {"dataset_id": dsid, "rule_type": rule["rule_type"], "severity": rule["severity"],
               "rule_version": rule["version_number"], "weight_version": wv_in_force, "run_at": data["as_of"]}
        t = rule["rule_type"]
        rws = rows.get(dsid, [])
        if t == "completeness":
            vals = [r_.get(d["field"]) for r_ in rws]
            miss = sum(1 for v in vals if missing(v))
            ws = sum(1 for v in vals if isinstance(v, str) and v != "" and missing(v))
            el = len(vals)
            val = ratio(el - miss, el)
            m_comp[rid] = {"dataset_id": dsid, "eligible_count": el, "missing_count": miss,
                           "whitespace_only_count": ws, "populated_count": el - miss, "value": p6(val)}
            run.update(eligible_count=el, failure_count=miss)
            dim_val[(dsid, "completeness")] = val
        elif t == "validity":
            vals = [r_.get(d["field"]) for r_ in rws]
            pat = re.compile(d["pattern"])
            pop = [v for v in vals if not missing(v)]
            passing = sum(1 for v in pop if pat.search(v))
            el = len(vals)
            allv, popv = ratio(passing, el), ratio(passing, len(pop))
            m_valid[rid] = {"dataset_id": dsid, "eligible_count": el, "populated_count": len(pop),
                            "passing_count": passing,
                            "all_eligible": {"label": "validity_all_eligible", "value": p6(allv)},
                            "populated_only": {"label": "validity_populated_only", "value": p6(popv)}}
            run.update(eligible_count=el, failure_count=el - passing, populated_count=len(pop))
            dim_val[(dsid, "validity")] = popv
        elif t == "uniqueness":
            vals = [r_.get(d["field"]) for r_ in rws]
            nulls = sum(1 for v in vals if missing(v))
            freq = {}
            for v in vals:
                if not missing(v):
                    freq[v] = freq.get(v, 0) + 1
            distinct = len(freq)
            groups = sum(1 for c in freq.values() if c > 1)
            dup_rows = sum(c - 1 for c in freq.values() if c > 1)
            el = len(vals)
            rowshare = ratio(dup_rows, el)
            m_uniq[rid] = {"dataset_id": dsid, "eligible_count": el, "null_key_count": nulls,
                           "distinct_keys": distinct, "duplicate_groups": groups, "duplicate_rows": dup_rows,
                           "group_share": {"label": "duplicate_group_share", "value": p6(ratio(groups, distinct))},
                           "row_share": {"label": "duplicate_row_share", "value": p6(rowshare)}}
            run.update(eligible_count=el, failure_count=nulls + dup_rows)
            dim_val[(dsid, "uniqueness")] = None if rowshare is None else 1 - rowshare
        elif t == "relationship":
            parent = {r_.get(d["parent_field"]) for r_ in rows.get(d["parent_dataset_id"], []) if not missing(r_.get(d["parent_field"]))}
            fks = [r_.get(d["field"]) for r_ in rws]
            nulls = sum(1 for v in fks if missing(v))
            el = len(fks) - nulls
            matched = sum(1 for v in fks if not missing(v) and v in parent)
            val = ratio(matched, el)
            m_rel[rid] = {"dataset_id": dsid, "total_fk_count": len(fks), "null_fk_count": nulls,
                          "eligible_count": el, "matched_count": matched, "unmatched_count": el - matched,
                          "value": p6(val)}
            run.update(eligible_count=el, failure_count=el - matched, null_fk_count=nulls)
            dim_val[(dsid, "relationship")] = val
        elif t == "timeliness":
            on = False
            if ds["monitored"]:
                s, dl = scheduled_occurrence(ds, as_of)
                last = ds["last_refreshed_at"]
                on = last is not None and s <= ts(last) < dl
            run.update(eligible_count=1, failure_count=0 if on else 1)
            dim_val[(dsid, "timeliness")] = F(1) if on else F(0)
        rr[rid] = run
    # comparisons: latest earlier scheduled run of the same rule
    for rid, run in rr.items():
        prev = [r_ for r_ in acc["rule_runs"] if r_["rule_id"] == rid and r_["kind"] == "scheduled"
                and ts(r_["run_at"]) < as_of]
        if not prev:
            continue
        p = max(prev, key=lambda r_: (r_["run_at"], r_["rule_run_id"]))
        same = p["rule_version"] == run["rule_version"]
        comps[rid] = {"previous_run_id": p["rule_run_id"], "previous_rule_version": p["rule_version"],
                      "current_rule_version": run["rule_version"], "comparable": same,
                      "reason": None if same else "RULE_VERSION_DIFFERS",
                      "previous_eligible_count": p["eligible_count"], "current_eligible_count": run["eligible_count"],
                      "failure_rate_previous": p6(ratio(p["failure_count"], p["eligible_count"])) if same else None,
                      "failure_rate_current": p6(ratio(run["failure_count"], run["eligible_count"])) if same else None}
    disabled = {}
    for rid, rule in rules.items():
        if rule["status"] == "disabled":
            disabled[rid] = {"disabled_at": rule["disabled_at"], "disabled_reason": rule["disabled_reason"],
                             "runs_retained": sum(1 for r_ in acc["rule_runs"] if r_["rule_id"] == rid),
                             "issues_retained": sum(1 for i in acc["issues"] if runs[i["rule_run_id"]]["rule_id"] == rid)}

    # ---- timeliness metric over monitored datasets
    tl = {}
    for dsid in sorted(datasets):
        ds = datasets[dsid]
        if not ds["monitored"]:
            continue
        s, dl = scheduled_occurrence(ds, as_of)
        last = ds["last_refreshed_at"]
        tl[dsid] = {"timezone": ds["refresh_timezone"], "scheduled_local": ds["refresh_local_time"],
                    "grace_minutes": ds["refresh_grace_minutes"], "evaluated_occurrence_utc": zstr(s),
                    "deadline_utc": zstr(dl), "last_refreshed_at": last,
                    "on_time": last is not None and s <= ts(last) < dl}
    on_n = sum(1 for v in tl.values() if v["on_time"])
    timeliness = {"monitored_datasets": len(tl), "on_time_count": on_n, "value": p6(ratio(on_n, len(tl))),
                  "datasets": tl}

    # ---- issues
    issue_out = {}
    for i in sorted(acc["issues"], key=lambda x: x["issue_id"]):
        base = runs[i["rule_run_id"]]
        rule = rules[base["rule_id"]]
        ver = runs.get(i["verification_run_id"]) if i["verification_run_id"] else None
        verified = (ver is not None and ver["kind"] == "rerun" and ver["rerun_for_issue"] == i["issue_id"]
                    and ver["rule_id"] == base["rule_id"] and ver["rule_version"] == base["rule_version"]
                    and ver["failure_count"] == 0 and ts(ver["run_at"]) >= ts(i["detected_at"]))
        det = ts(i["detected_at"])
        if i["status"] == "closed" and verified:
            cls = "resolved"
        elif i["status"] == "closed":
            cls = "claimed"
        else:
            cls = "open"
        issue_out[i["issue_id"]] = {
            "rule_id": base["rule_id"], "severity": rule["severity"], "class": cls,
            "resolution_hours": h4(hours(det, ts(ver["run_at"]))) if cls == "resolved" else None,
            "claimed_hours": h4(hours(det, ts(i["closed_at"]))) if cls == "claimed" else None,
            "age_hours": h4(hours(det, as_of)) if cls == "open" else None,
            "reopen_cycles": len(i["reopened_at"])}
        issue_out[i["issue_id"]]["_hours"] = hours(det, ts(ver["run_at"])) if cls == "resolved" else None
    resolved_h = [v["_hours"] for v in issue_out.values() if v["class"] == "resolved"]
    for v in issue_out.values():
        del v["_hours"]
    resolution = {"resolved_count": len(resolved_h),
                  "claimed_count": sum(1 for v in issue_out.values() if v["class"] == "claimed"),
                  "open_count": sum(1 for v in issue_out.values() if v["class"] == "open"),
                  "reopened_count": sum(1 for v in issue_out.values() if v["reopen_cycles"] > 0),
                  "reopen_cycles_total": sum(v["reopen_cycles"] for v in issue_out.values()),
                  "mean_hours": h4(ratio(sum(resolved_h, F(0)), len(resolved_h)) if resolved_h else None),
                  "issues": issue_out}

    # ---- weighted score, critical override
    def wscore(dsid, wv):
        w = weights[wv]
        meas = [dm for dm in DIMS if dim_val.get((dsid, dm)) is not None]
        wsum = sum((w[dm] for dm in meas), F(0))
        if not meas or wsum == 0:
            return meas, wsum, None
        return meas, wsum, sum((w[dm] * dim_val[(dsid, dm)] for dm in meas), F(0)) / wsum

    ws_out, by_wv = {}, {k: {} for k in sorted(weights)}
    crit_f = crit_i = over = 0
    for dsid in sorted(datasets):
        meas, wsum, val = wscore(dsid, wv_in_force)
        cf = sum(rr[rid]["failure_count"] for rid in rr if rr[rid]["dataset_id"] == dsid and rr[rid]["severity"] == "critical")
        ci = sum(1 for v in issue_out.values() if v["severity"] == "critical" and v["class"] != "resolved"
                 and rules[v["rule_id"]]["dataset_id"] == dsid)
        ov = cf > 0 or ci > 0
        ws_out[dsid] = {"weight_version": wv_in_force,
                        "dimension_scores": {dm: p6(dim_val[(dsid, dm)]) for dm in meas},
                        "measured_dimensions": meas, "weight_sum": p6(wsum), "value": p6(val),
                        "critical_failures": cf, "critical_open_issues": ci, "critical_override": ov}
        crit_f += cf; crit_i += ci; over += 1 if ov else 0
        for wv in by_wv:
            by_wv[wv][dsid] = p6(wscore(dsid, wv)[2])

    # ---- ownership
    covered = [d for d in datasets.values() if d["owner_id"] in owners and (owners[d["owner_id"]]["deactivated_at"] is None
                                                                            or as_of < ts(owners[d["owner_id"]]["deactivated_at"]))]
    cov_ids = {d["dataset_id"] for d in covered}
    ownership = {"datasets": len(datasets), "covered": len(covered), "value": p6(ratio(len(covered), len(datasets))),
                 "uncovered": sorted(set(datasets) - cov_ids)}

    # ---- definitions
    checklist = next((c for c in data["checklist_versions"] if c["checklist_version"] == data["checklist_version"]))
    by_metric = {}
    for m in acc["metric_versions"]:
        by_metric.setdefault(m["metric_id"], []).append(m)

    def effective(mid, t):
        c = [m for m in by_metric[mid] if m["status"] in ("published", "superseded") and ts(m["valid_from"]) <= t]
        return max(c, key=lambda m: m["valid_from"]) if c else None

    def item_ok(m, it):
        v = m.get(it if it != "owner" else "owner_id")
        if it == "source_fields":
            return isinstance(v, list) and len(v) > 0 and all(not missing(x) for x in v)
        if it == "owner":
            return v in owners
        return not missing(v)

    pub, complete, incomplete = 0, 0, {}
    for mid in sorted(by_metric):
        e = effective(mid, as_of)
        if e is None or e["status"] != "published":
            continue
        pub += 1
        bad = [it for it in checklist["items"] if not item_ok(e, it)]
        if bad:
            incomplete[mid] = bad
        else:
            complete += 1
    defcov = {"checklist_version": data["checklist_version"], "published_metrics": pub, "complete_metrics": complete,
              "value": p6(ratio(complete, pub)), "incomplete": incomplete}
    probe = ts(data["probes"]["definition_at"])
    chg = {c["metric_version_id"]: c for c in acc["definition_changes"]}
    definitions = {
        "version_counts": {mid: len(v) for mid, v in sorted(by_metric.items())},
        "change_records": len(acc["definition_changes"]),
        "versions_without_change_record": sorted(m["metric_version_id"] for m in acc["metric_versions"]
                                                 if m["version_number"] > 1 and m["metric_version_id"] not in chg),
        "changes_with_mismatched_valid_from": sorted(
            m["metric_version_id"] for m in acc["metric_versions"]
            if m["metric_version_id"] in chg and chg[m["metric_version_id"]]["changed_at"] != m["valid_from"]),
        "effective_at_as_of": {mid: (effective(mid, as_of) or {}).get("metric_version_id") for mid in sorted(by_metric)},
        "probe_at": data["probes"]["definition_at"],
        "effective_at_probe": {mid: (effective(mid, probe) or {}).get("metric_version_id") for mid in sorted(by_metric)}}

    # ---- lineage
    edges = acc["lineage_edges"]
    pairs = lambda ev: {(e["source_dataset_id"], e["target_dataset_id"]) for e in edges if e["evidence_type"] == ev}
    pr = lambda s: [{"source_dataset_id": a, "target_dataset_id": b} for a, b in sorted(s)]
    dec, obs, inf = pairs("declared"), pairs("observed"), pairs("inferred")
    lineage = {"declared_edges": len(dec), "observed_rows": sum(1 for e in edges if e["evidence_type"] == "observed"),
               "observed_distinct": len(obs), "observed_matching_declared": len(dec & obs),
               "value": p6(ratio(len(dec & obs), len(dec))), "undeclared_observed": pr(obs - dec),
               "declared_not_observed": pr(dec - obs), "inferred_edges": pr(inf)}

    # ---- matching (the only reader of the synthetic truth)
    truth = data["synthetic_truth"]["true_entity"]
    cand = {c["candidate_id"]: c for c in acc["match_candidates"]}
    appr, reject, reversed_ids = {}, set(), {}
    for m in acc["merge_decisions"]:
        if m["decision"] == "approve":
            appr[m["merge_id"]] = m
        elif m["decision"] == "reject":
            reject.add(m["candidate_id"])
        elif m["decision"] == "reverse":
            reversed_ids[m["reverses_merge_id"]] = m["merge_id"]
    appr_c = {m["candidate_id"] for m in appr.values()}
    reviewed = appr_c | reject
    same = lambda c: truth[cand[c]["left_record_id"]] == truth[cand[c]["right_record_id"]]
    a_ok = sum(1 for c in appr_c if same(c))
    r_ok = sum(1 for c in reviewed if same(c))
    imap = {r_["record_id"]: r_["record_id"] for r_ in acc["customer_records"]}
    hist = []
    for mid in sorted(appr):
        c = cand[appr[mid]["candidate_id"]]
        state = "reversed" if mid in reversed_ids else "active"
        if state == "active":
            imap[c["right_record_id"]] = c["left_record_id"]
        hist.append({"merge_id": mid, "candidate_id": c["candidate_id"], "from_record_id": c["right_record_id"],
                     "to_record_id": c["left_record_id"], "state": state, "reversed_by": reversed_ids.get(mid)})
    matching = {"candidates": len(cand), "reviewed": len(reviewed), "approved": len(appr_c),
                "rejected": len(reject), "unreviewed": len(cand) - len(reviewed),
                "merges_reversed": len(reversed_ids), "active_merges": len(appr) - len(reversed_ids),
                "identity_map": dict(sorted(imap.items())), "mapping_history": hist}
    mprec = {"approved_decisions": len(appr_c), "approved_correct": a_ok, "precision": p6(ratio(a_ok, len(appr_c))),
             "reviewed": len(reviewed), "reviewed_correct": r_ok,
             "reviewed_correct_share": p6(ratio(r_ok, len(reviewed)))}

    return {
        "contract_version": data["contract_version"], "as_of": data["as_of"], "weight_version": wv_in_force,
        "checklist_version": data["checklist_version"], "empty_population": empty,
        "ingest": {"counts": counts, "rejected_records": rejected},
        "rules": {"active_count": len(rr), "runs": rr, "comparisons": comps, "disabled": disabled},
        "metrics": {
            "completeness": m_comp, "validity": m_valid, "uniqueness": m_uniq, "relationship_integrity": m_rel,
            "timeliness": timeliness,
            "weighted_score": {"datasets": ws_out, "by_weight_version": by_wv},
            "critical_failures": {"failures": crit_f, "open_issues": crit_i, "datasets_overridden": over},
            "resolution_time": resolution, "ownership_coverage": ownership, "definition_coverage": defcov,
            "match_precision": mprec, "lineage_coverage": lineage},
        "definitions": definitions, "matching": matching}


# ---------------------------------------------------------------- comparison harness
def flatten(x, path=""):
    if isinstance(x, dict):
        if not x:
            return {path + "{}": "empty"}
        out = {}
        for k, v in x.items():
            out.update(flatten(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(x, list):
        if not x:
            return {path + "[]": "empty"}
        out = {}
        for i, v in enumerate(x):
            out.update(flatten(v, f"{path}[{i}]"))
        return out
    return {path: x}


def no_floats(x, where):
    if isinstance(x, float):
        report(False, f"{where}.no_float", "no float", x)
    elif isinstance(x, dict):
        [no_floats(v, where) for v in x.values()]
    elif isinstance(x, list):
        [no_floats(v, where) for v in x]


def spec_sentence():
    """P07-GOLD-01 recomputed from the sentence alone, then compared with golden/expected.json."""
    exp = json.loads((GOLDEN / "expected.json").read_text())
    m = exp["metrics"]
    el, miss, passing = 100, 5, 90
    pop = el - miss
    comp, vpop, vall = F(pop, el), F(passing, pop), F(passing, el)
    c = m["completeness"]["r-cust-complete-email"]
    v = m["validity"]["r-cust-valid-email"]
    ws = m["weighted_score"]["datasets"]["ds-customers"]
    for name, want, got in (
            ("spec.completeness", p6(comp), c["value"]), ("spec.completeness_is_0.950000", "0.950000", c["value"]),
            ("spec.populated_only_validity_90_95", p6(vpop), v["populated_only"]["value"]),
            ("spec.all_eligible_validity_90_100", p6(vall), v["all_eligible"]["value"]),
            ("spec.validity_labels", "validity_all_eligible/validity_populated_only",
             v["all_eligible"]["label"] + "/" + v["populated_only"]["label"]),
            ("spec.populated_only_is_not_90_100", True, v["populated_only"]["value"] != v["all_eligible"]["value"])):
        report(want == got, name, want, got)
    exceeds = F(ws["value"]) > F("0.95")
    report(exceeds, "spec.weighted_score_exceeds_0.95", True, exceeds)
    report(ws["critical_override"] is True and ws["critical_failures"] == 2, "spec.critical_failure_visible_beside_score",
           "override true, 2 failures", f'{ws["critical_override"]}, {ws["critical_failures"]}')


def check_fixture(label, prefix):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    no_floats(data, label + ".inputs")
    no_floats(exp, label)
    # the synthetic truth is a separate top-level block; no entity row carries truth
    leaked = [e for e in ENTITIES for row in data[e] if any("true_entity" in k or "truth" in k for k in row)]
    report(not leaked and "synthetic_truth" in data, f"{label}.truth_is_separate_block", "no truth in entities", leaked or "ok")
    got = compute(data)
    fe, fg = flatten(exp), flatten(got)
    for k in fe:
        report(k in fg and fg[k] == fe[k], f"{label}.{k}", fe[k], fg.get(k, "<missing>"))
    for k in fg:
        if k not in fe:
            report(False, f"{label}.{k}", "<absent>", fg[k])


def sha(rel):
    return hashlib.sha256((GOLDEN / rel).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true")
    args = ap.parse_args()
    spec_sentence()
    for label, prefix in FIXTURES:
        check_fixture(label, prefix)
    hp = GOLDEN / "HASHES.json"
    if args.write_hashes:
        if failures:
            print(f"NOT WRITING HASHES: {failures} mismatch(es)")
        else:
            hp.write_text(json.dumps({"algorithm": "sha256", "sha256": {p: sha(p) for p in HASHED}}, indent=2) + "\n")
            print(f"OK wrote {hp.name}")
    elif hp.exists():
        stored = json.loads(hp.read_text())["sha256"]
        for p in HASHED:
            report(stored.get(p) == sha(p), f"hash.{p}", stored.get(p), sha(p))
    else:
        report(False, "hash.HASHES.json", "present", "missing")
    print("ALL OK" + f" ({checks} checks)" if not failures else f"{failures} MISMATCH(ES) of {checks} checks")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
