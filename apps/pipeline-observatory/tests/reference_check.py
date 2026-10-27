#!/usr/bin/env python3
"""Independent reference calculation for the Pipeline Observatory golden fixtures (P08-GOLD-01..11).

Standard library only; imports nothing from the application. Recomputes every figure in expected.json from
inputs.json (entity import validation and rejection with dependants, duplicate / quarantine classification on
source_key, per-batch and per-source counts and rates, checkpoint versions, freshness vs ingestion age,
completeness against the declared expectation, task and attempt success, run durations, the fail-closed
quality gate and the atomic publication pointer, publication lag and watermark, late events, reconciliation
residual with its parts, verified incident recovery, half-open backfills with overlap refusal, the observed
processing rate) and compares leaf by leaf. It also recomputes every payload_hash, definition_hash and
content_hash from the documented rules, and asserts the hand-worked headline figures of CALCULATION.md as
literals. No float anywhere: fractions.Fraction for every ratio, decimal.Decimal for money. Proportions are
6-place decimal strings, minutes 4-place, money 2-place, ROUND_HALF_UP. Contract v1, D-01..D-04.

Usage:
  python3 -I reference_check.py                # check everything, exit 0 only if all OK
  python3 -I reference_check.py --write-hashes # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction as F
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
FIXTURES = [("golden", ""), ("variant-rejected", "variant-rejected/"), ("variant-empty", "variant-empty/")]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENTITIES = ["source_contracts", "ingestion_batches", "raw_records", "quarantine_records", "checkpoints",
            "model_definitions", "pipeline_runs", "task_runs", "quality_results", "publications", "incidents",
            "backfill_requests"]
ID = {"source_contracts": "source_id", "ingestion_batches": "batch_id", "raw_records": "raw_record_id",
      "quarantine_records": "quarantine_id", "checkpoints": "checkpoint_id", "model_definitions": "model_id",
      "pipeline_runs": "run_id", "task_runs": "task_run_id", "quality_results": "quality_result_id",
      "publications": "publication_id", "incidents": "incident_id", "backfill_requests": "backfill_id"}
# child entity -> (foreign key field, parent entity, code when the parent id is unknown)
FK = {"ingestion_batches": ("source_id", "source_contracts", "UNKNOWN_SOURCE"),
      "backfill_requests": ("source_id", "source_contracts", "UNKNOWN_SOURCE"),
      "raw_records": ("batch_id", "ingestion_batches", "UNKNOWN_BATCH"),
      "quarantine_records": ("batch_id", "ingestion_batches", "UNKNOWN_BATCH"),
      "checkpoints": ("batch_id", "ingestion_batches", "UNKNOWN_BATCH"),
      "task_runs": ("run_id", "pipeline_runs", "UNKNOWN_RUN"),
      "quality_results": ("task_run_id", "task_runs", "UNKNOWN_TASK_RUN"),
      "publications": ("run_id", "pipeline_runs", "UNKNOWN_RUN"),
      "incidents": ("run_id", "pipeline_runs", "UNKNOWN_RUN")}
REQUIRED = ["record_id", "quantity", "unit_price", "amount", "event_ts"]
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


# ---------------------------------------------------------------- number formats (D-04)
def rnd(x, dp):
    """ROUND_HALF_UP of a Fraction to dp places, as a string."""
    x = F(x)
    neg = x < 0
    scaled = abs(x) * 10 ** dp
    n = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    whole, frac = divmod(n, 10 ** dp)
    s = f"{whole}.{frac:0{dp}d}" if dp else str(whole)
    return ("-" if neg and n else "") + s


def p6(x):
    return None if x is None else rnd(x, 6)


def m4(x):
    return None if x is None else rnd(x, 4)


def money(d):
    return str(Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ratio(num, den):
    return None if den == 0 else F(num, den)


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def secs(a, b):
    return int((ts(b) - ts(a)).total_seconds())


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def canon(p):
    return json.dumps(p, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------- import validation
def validate_import(data):
    """Return (accepted dict of lists, rejected records list). Rejection is atomic per record; a record whose
    parent was rejected is DEPENDENT_REJECTED; nothing is silently dropped."""
    acc = {e: [] for e in ENTITIES}
    rej_ids = {e: set() for e in ENTITIES}
    rejected = []
    pos = {e: {r[ID[e]]: i for i, r in enumerate(data[e])} for e in ENTITIES}

    def rej(e, row, code):
        rejected.append((ENTITIES.index(e), data[e].index(row), {"entity": e, "id": row[ID[e]], "status": "rejected",
                                                                 "reason_code": code, "raw_row": row}))
        rej_ids[e].add(row[ID[e]])

    seen_pk = {e: set() for e in ENTITIES}
    seen_attempt = set()

    def common(e, row):
        """duplicate primary key, then foreign key; returns a reason code or None."""
        if row[ID[e]] in seen_pk[e]:
            return "DUPLICATE_ID"
        if e == "task_runs" and (row["run_id"], row["task_name"], row["attempt"]) in seen_attempt:
            return "DUPLICATE_ID"          # the attempt of this task in this run repeats
        if e in FK:
            fk, parent, unknown = FK[e]
            pid = row[fk]
            ok_parent = {r[ID[parent]] for r in acc[parent]}
            if pid in ok_parent:
                pass
            elif pid in rej_ids[parent]:
                return "DEPENDENT_REJECTED"
            else:
                return unknown
        if e == "pipeline_runs" and row.get("backfill_id") is not None:
            if row["backfill_id"] in rej_ids["backfill_requests"]:
                return "DEPENDENT_REJECTED"
            if row["backfill_id"] not in {r["backfill_id"] for r in acc["backfill_requests"]}:
                return "UNKNOWN_BACKFILL"
        return None

    def take(e, row):
        acc[e].append(row)
        seen_pk[e].add(row[ID[e]])
        if e == "task_runs":
            seen_attempt.add((row["run_id"], row["task_name"], row["attempt"]))

    def plain(e):
        for row in data[e]:
            code = common(e, row)
            if code:
                rej(e, row, code)
            else:
                take(e, row)

    plain("source_contracts")
    # backfills: half-open [start, end); a request overlapping an earlier accepted one of the same source is refused
    for row in data["backfill_requests"]:
        code = common("backfill_requests", row)
        if code is None:
            s, e_ = ts(row["start_at"]), ts(row["end_at"])
            for o in acc["backfill_requests"]:
                if o["source_id"] == row["source_id"] and s < ts(o["end_at"]) and ts(o["start_at"]) < e_:
                    code = "BACKFILL_OVERLAP"
                    break
        if code:
            rej("backfill_requests", row, code)
        else:
            take("backfill_requests", row)
    # batches and their checkpoints: the version must be previous + 1 in commit order, else the whole commit fails
    batch_rows = []
    for row in data["ingestion_batches"]:
        code = common("ingestion_batches", row)
        if code:
            rej("ingestion_batches", row, code)
        else:
            batch_rows.append(row)
    batch_ids = {b["batch_id"] for b in batch_rows}
    bad_cp_batches = set()
    cps = [c for c in data["checkpoints"] if c["batch_id"] in batch_ids]
    prev = {}
    cp_reason = {}
    for c in sorted(cps, key=lambda c: (c["committed_at"], c["checkpoint_id"])):
        p = prev.get(c["source_id"], 0)
        if c["version_number"] <= p:
            cp_reason[c["checkpoint_id"]] = "CHECKPOINT_REGRESSION"
            bad_cp_batches.add(c["batch_id"])
        elif c["version_number"] != p + 1:
            cp_reason[c["checkpoint_id"]] = "CHECKPOINT_GAP"
            bad_cp_batches.add(c["batch_id"])
        else:
            prev[c["source_id"]] = c["version_number"]
    for b in batch_rows:
        if b["batch_id"] in bad_cp_batches:
            rej("ingestion_batches", b, "DEPENDENT_REJECTED")
        else:
            take("ingestion_batches", b)
    for c in data["checkpoints"]:
        code = cp_reason.get(c["checkpoint_id"]) or common("checkpoints", c)
        if code:
            rej("checkpoints", c, code)
        else:
            take("checkpoints", c)
    for e in ["raw_records", "quarantine_records", "model_definitions", "pipeline_runs"]:
        plain(e)
    for e in ["task_runs", "quality_results", "publications", "incidents"]:
        plain(e)
    rejected.sort(key=lambda t: (t[0], t[1]))
    return acc, [r for _, _, r in rejected]


# ---------------------------------------------------------------- metrics
def amount_of(raw, field):
    return Decimal(raw["payload_json"][field])


def compute(data):
    acc, rejected = validate_import(data)
    counts = {e: {"accepted": len(acc[e]), "rejected": sum(1 for r in rejected if r["entity"] == e)} for e in ENTITIES}
    cutoff = data["cutoff"]
    tsf = data["freshness_timestamp_field"]
    totf = data["business_total_field"]
    for r in acc["raw_records"]:
        assert r["payload_json"].get("op", "upsert") == "upsert", "delete events are not exercised by this fixture"
    empty = len(acc["raw_records"]) == 0

    # ---- classification (D-01): committed batches in (started_at, batch_id) order, rows by raw_record_id;
    # a source_key already accepted is a duplicate (checked first); otherwise the contract decides.
    batches = {b["batch_id"]: b for b in acc["ingestion_batches"]}
    cp_by_batch = {c["batch_id"]: c for c in acc["checkpoints"]}
    committed = sorted([b for b in acc["ingestion_batches"] if b["status"] == "committed"],
                       key=lambda b: (b["started_at"], b["batch_id"]))
    raws = {}
    for r in acc["raw_records"]:
        raws.setdefault(r["batch_id"], []).append(r)
    for v in raws.values():
        v.sort(key=lambda r: r["raw_record_id"])
    quar_rows = {}
    for q in acc["quarantine_records"]:
        quar_rows.setdefault(q["batch_id"], []).append(q)
    cls = {}          # raw_record_id -> "accepted" | "duplicate" | "quarantined"
    reason = {}
    accepted_keys = {}
    for b in committed:
        keys = accepted_keys.setdefault(b["source_id"], set())
        for r in raws.get(b["batch_id"], []):
            p = r["payload_json"]
            if r["source_key"] in keys:
                cls[r["raw_record_id"]] = "duplicate"
            elif any(p.get(k) is None for k in REQUIRED):
                cls[r["raw_record_id"]], reason[r["raw_record_id"]] = "quarantined", "MISSING_FIELD"
            elif p["quantity"] < 0:
                cls[r["raw_record_id"]], reason[r["raw_record_id"]] = "quarantined", "NEGATIVE_QUANTITY"
            else:
                cls[r["raw_record_id"]] = "accepted"
                keys.add(r["source_key"])

    def batch_counts(bid):
        rows = raws.get(bid, [])
        c = {k: sum(1 for r in rows if cls.get(r["raw_record_id"]) == k) for k in ("accepted", "duplicate", "quarantined")}
        return len(rows), c["accepted"], c["duplicate"], c["quarantined"]

    sources = {}
    tot = [0, 0, 0, 0]
    for s in sorted(acc["source_contracts"], key=lambda s: s["source_id"]):
        sid = s["source_id"]
        out_b = {}
        rec = acc_n = dup = qua = 0
        by_reason = {}
        for b in acc["ingestion_batches"]:
            if b["source_id"] != sid:
                continue
            if b["status"] != "committed":
                out_b[b["batch_id"]] = {"status": b["status"], "counted": False, "written_rows": len(raws.get(b["batch_id"], [])),
                                        "received": 0, "accepted_unique": 0, "duplicate": 0, "quarantined": 0,
                                        "rejection_rate": None, "duplicate_rate": None, "quarantine_rows_match": True}
                continue
            r_, a_, d_, q_ = batch_counts(b["batch_id"])
            derived = sorted(reason[r["raw_record_id"]] for r in raws.get(b["batch_id"], []) if cls[r["raw_record_id"]] == "quarantined")
            recorded = sorted(q["reason_code"] for q in quar_rows.get(b["batch_id"], []))
            out_b[b["batch_id"]] = {"status": "committed", "counted": True, "written_rows": r_, "received": r_,
                                    "accepted_unique": a_, "duplicate": d_, "quarantined": q_,
                                    "rejection_rate": p6(ratio(q_, r_)), "duplicate_rate": p6(ratio(d_, r_)),
                                    "quarantine_rows_match": derived == recorded}
            rec, acc_n, dup, qua = rec + r_, acc_n + a_, dup + d_, qua + q_
            for c_ in derived:
                by_reason[c_] = by_reason.get(c_, 0) + 1
        qkeys = {r["source_key"] for b in committed if b["source_id"] == sid for r in raws.get(b["batch_id"], [])
                 if cls[r["raw_record_id"]] == "quarantined"}
        cps = sorted([cp_by_batch[b["batch_id"]] for b in committed if b["source_id"] == sid and b["batch_id"] in cp_by_batch],
                     key=lambda c: c["version_number"])
        last = cps[-1] if cps else None
        unc = sorted(b["batch_id"] for b in acc["ingestion_batches"] if b["source_id"] == sid and b["status"] != "committed")
        sources[sid] = {
            "batches": out_b, "received": rec, "accepted_unique": acc_n, "duplicate": dup, "quarantined": qua,
            "quarantined_distinct_keys": len(qkeys), "rejection_rate": p6(ratio(qua, rec)),
            "duplicate_rate": p6(ratio(dup, rec)), "quarantine_by_reason": dict(sorted(by_reason.items())),
            "checkpoint": {"committed_version": last["version_number"] if last else None,
                           "committed_cursor": last["committed_cursor"] if last else None,
                           "committed_batch_id": last["batch_id"] if last else None,
                           "uncommitted_batches": unc,
                           "uncommitted_batches_with_checkpoint": sum(1 for u in unc if u in cp_by_batch)}}
        tot = [tot[0] + rec, tot[1] + acc_n, tot[2] + dup, tot[3] + qua]
    ingestion = {"sources": sources, "overall": {
        "received": tot[0], "accepted_unique": tot[1], "duplicate": tot[2], "quarantined": tot[3],
        "rejection_rate": p6(ratio(tot[3], tot[0])), "duplicate_rate": p6(ratio(tot[2], tot[0]))}}

    # ---- accepted records with their arrival (the checkpoint commit instant of their batch)
    accepted = []
    for b in committed:
        cp = cp_by_batch.get(b["batch_id"])
        for r in raws.get(b["batch_id"], []):
            if cls[r["raw_record_id"]] == "accepted":
                accepted.append({"source_id": b["source_id"], "batch_id": b["batch_id"], "key": r["source_key"],
                                 "event": r["payload_json"][tsf], "arrival": cp["committed_at"] if cp else None,
                                 "raw": r, "hash": r["payload_hash"]})

    # ---- freshness vs ingestion age (D-02)
    freshness = {}
    for sid in sources:
        ev = [a["event"] for a in accepted if a["source_id"] == sid]
        ing = [cp_by_batch[b["batch_id"]]["committed_at"] for b in committed
               if b["source_id"] == sid and b["batch_id"] in cp_by_batch]
        le, li = (max(ev) if ev else None), (max(ing) if ing else None)
        freshness[sid] = {"latest_accepted_event_at": le, "freshness_seconds": secs(le, cutoff) if le else None,
                          "last_successful_ingestion_at": li, "ingestion_age_seconds": secs(li, cutoff) if li else None}

    # ---- completeness against the declared expectation (D-02)
    completeness = {}
    for x in data["source_expectations"]:
        n = sum(1 for a in accepted if a["source_id"] == x["source_id"] and a["event"][:10] == x["partition"])
        completeness.setdefault(x["source_id"], {})[x["partition"]] = {
            "expected_records": x["expected_records"], "accepted_records": n,
            "value": p6(ratio(n, x["expected_records"]))}

    # ---- runs, tasks and attempts (D-03)
    runs_by = {r["run_id"]: r for r in acc["pipeline_runs"]}
    tasks = {}
    for t in acc["task_runs"]:
        tasks.setdefault(t["run_id"], {}).setdefault(t["task_name"], []).append(t)
    runs = {}
    T = [0, 0, 0, 0]
    dur = {"success": [], "failed": []}
    for rid in sorted(runs_by):
        run = runs_by[rid]
        tk = {}
        for name, atts in sorted(tasks.get(rid, {}).items()):
            atts.sort(key=lambda t: int(t["attempt"]))
            tk[name] = {"attempts": len(atts), "final_status": atts[-1]["status"]}
        term = [v for v in tk.values() if v["final_status"] in ("success", "failed")]
        ok = sum(1 for v in term if v["final_status"] == "success")
        att = sum(v["attempts"] for v in tk.values())
        att_ok = sum(1 for t in acc["task_runs"] if t["run_id"] == rid and t["status"] == "success")
        d = secs(run["started_at"], run["finished_at"])
        if run["status"] in dur:
            dur[run["status"]].append(d)
        runs[rid] = {"status": run["status"], "duration_seconds": d, "tasks": tk, "tasks_terminal": len(term),
                     "tasks_successful": ok, "task_success_rate": p6(ratio(ok, len(term))), "attempts": att,
                     "attempts_successful": att_ok, "attempt_success_rate": p6(ratio(att_ok, att))}
        T = [T[0] + len(term), T[1] + ok, T[2] + att, T[3] + att_ok]

    def group(ds):
        return {"count": len(ds), "durations_seconds": sorted(ds), "mean_minutes": m4(ratio(sum(ds), 60 * len(ds)))}
    runs_out = {"runs": runs, "overall": {
        "tasks_terminal": T[0], "tasks_successful": T[1], "task_success_rate": p6(ratio(T[1], T[0])),
        "attempts": T[2], "attempts_successful": T[3], "attempt_success_rate": p6(ratio(T[3], T[2]))},
        "durations": {"successful": group(dur["success"]), "failed": group(dur["failed"])}}

    # ---- quality gate, fail closed (D-02)
    task_run_run = {t["task_run_id"]: t["run_id"] for t in acc["task_runs"]}
    gate = {}
    for rid in sorted(runs_by):
        res = [q for q in acc["quality_results"] if task_run_run[q["task_run_id"]] == rid]
        out = {}
        for q in sorted(res, key=lambda q: q["quality_result_id"]):
            out[q["rule_name"]] = {"severity": q["severity"], "eligible": q["eligible_count"],
                                   "failures": q["failure_count"], "passed": q["failure_count"] == 0}
        crit = [v for v in out.values() if v["severity"] == "critical"]
        cf = sum(1 for v in crit if not v["passed"])
        wf = sum(1 for v in out.values() if v["severity"] != "critical" and not v["passed"])
        gate[rid] = {"results": out, "critical_failures": cf, "noncritical_failures": wf,
                     "decision": "allowed" if crit and cf == 0 else "blocked"}

    # ---- publications: totals, lag, reconciliation (D-02)
    amounts = {}
    for b in committed:
        for r in raws.get(b["batch_id"], []):
            amounts[r["raw_record_id"]] = amount_of(r, totf)
    pubs = {}
    recon = {}
    pub_rows = sorted(acc["publications"], key=lambda p: p["published_at"])
    for p in pub_rows:
        inc = [b for b in p["included_batch_ids"] if b in {c["batch_id"] for c in committed}]
        rows = [r for b in inc for r in raws.get(b, [])]
        pubd = [a for a in accepted if a["batch_id"] in inc]
        latest = max((a["event"] for a in pubd), default=None)
        expect_hash = sha("\n".join(sorted(a["hash"] for a in pubd)))
        pubs[p["publication_id"]] = {
            "run_id": p["run_id"], "published_at": p["published_at"], "watermark": p["watermark"],
            "included_batches": sorted(inc), "published_records": len(pubd), "latest_included_event_at": latest,
            "lag_seconds": secs(latest, p["published_at"]) if latest else None, "content_hash_ok": expect_hash == p["content_hash"]}
        src_total = sum((amounts[r["raw_record_id"]] for r in rows), Decimal("0"))
        pub_total = sum((amounts[a["raw"]["raw_record_id"]] for a in pubd), Decimal("0"))
        q_amt = sum((amounts[r["raw_record_id"]] for r in rows if cls[r["raw_record_id"]] == "quarantined"), Decimal("0"))
        d_amt = sum((amounts[r["raw_record_id"]] for r in rows if cls[r["raw_record_id"]] == "duplicate"), Decimal("0"))
        recon[p["publication_id"]] = {
            "source_total": money(src_total), "published_total": money(pub_total),
            "exclusions": {"quarantined": money(q_amt), "duplicates": money(d_amt), "deletes": money(Decimal("0"))},
            "exclusions_total": money(q_amt + d_amt), "residual": money(src_total - pub_total - (q_amt + d_amt))}
    # the atomic pointer moves only to a passed candidate's publication
    pointer, hist = None, []
    pub_of_run = {p["run_id"]: p["publication_id"] for p in pub_rows}
    for run in sorted(acc["pipeline_runs"], key=lambda r: (r["finished_at"], r["run_id"])):
        g = gate[run["run_id"]]["decision"]
        if g == "allowed" and run["status"] == "success" and run["run_id"] in pub_of_run:
            pointer = pub_of_run[run["run_id"]]
        hist.append({"run_id": run["run_id"], "gate_decision": g, "pointer_after": pointer})
    publications = {"current_publication_id": pointer, "pointer_history": hist, "publications": pubs}

    # ---- late events behind the watermark (D-02)
    late = []
    for a in accepted:
        if a["arrival"] is None:
            continue
        before = [p for p in pub_rows if a["source_id"] in p["source_ids"] and p["published_at"] < a["arrival"]]
        if not before:
            continue
        p = before[-1]
        if a["event"] <= p["watermark"]:
            nxt = [q for q in pub_rows if q["published_at"] > a["arrival"] and a["batch_id"] in q["included_batch_ids"]]
            late.append({"source_id": a["source_id"], "source_key": a["key"], "batch_id": a["batch_id"],
                         "event_at": a["event"], "arrival_at": a["arrival"], "behind_publication_id": p["publication_id"],
                         "watermark": p["watermark"], "included_in_publication_id": nxt[0]["publication_id"] if nxt else None})
    late.sort(key=lambda x: (x["arrival_at"], x["source_key"]))
    late_out = {"count": len(late), "included_in_next_publication": sum(1 for x in late if x["included_in_publication_id"]),
                "lost": sum(1 for x in late if not x["included_in_publication_id"]), "events": late}

    # ---- incidents and verified recovery (D-03)
    incs = {}
    ts_ = {"closed": 0, "open": 0, "verified": 0, "seconds": 0}
    for i in sorted(acc["incidents"], key=lambda i: i["incident_id"]):
        found = None
        for run in sorted(acc["pipeline_runs"], key=lambda r: (r["started_at"], r["run_id"])):
            pid = pub_of_run.get(run["run_id"])
            if (run["started_at"] >= i["opened_at"] and run["status"] == "success" and gate[run["run_id"]]["decision"] == "allowed"
                    and pid and recon[pid]["residual"] == "0.00"):
                found = (run, pid)
                break
        v_at = pubs[found[1]]["published_at"] if found else None
        sec = secs(i["opened_at"], v_at) if found else None
        consistent = (i["status"] != "closed") or (found is not None and i["recovery_run_id"] == found[0]["run_id"]
                                                   and i["closed_at"] == v_at)
        incs[i["incident_id"]] = {"run_id": i["run_id"], "status": i["status"], "detected_at": i["opened_at"],
                                  "verified": found is not None, "recovery_run_id": found[0]["run_id"] if found else None,
                                  "verified_at": v_at, "recovery_seconds": sec, "recovery_minutes": m4(ratio(sec, 60)) if found else None,
                                  "closure_consistent": consistent}
        ts_["closed" if i["status"] == "closed" else "open"] += 1
        if found:
            ts_["verified"] += 1
            ts_["seconds"] += sec
    incidents = {"total": len(incs), "open": ts_["open"], "closed": ts_["closed"], "verified": ts_["verified"],
                 "mean_recovery_minutes": m4(ratio(ts_["seconds"], 60 * ts_["verified"])), "incidents": incs}

    # ---- backfills: half-open ranges, daily partitions, coverage (D-03)
    bf = {}
    rq = vf = 0
    for b in sorted(acc["backfill_requests"], key=lambda b: b["backfill_id"]):
        parts, cur = [], ts(b["start_at"])
        while cur < ts(b["end_at"]):
            parts.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        ver = sorted(p["partition"] for p in b["partitions"] if p["verified"] and p["partition"] in parts)
        bf[b["backfill_id"]] = {"source_id": b["source_id"], "start_at": b["start_at"], "end_at": b["end_at"],
                                "requested_partitions": len(parts), "verified_partitions": len(ver),
                                "coverage": p6(ratio(len(ver), len(parts)))}
        rq, vf = rq + len(parts), vf + len(ver)
    backfills = {"requests": bf, "refused": sorted(r["id"] for r in rejected if r["entity"] == "backfill_requests"
                                                    and r["reason_code"] == "BACKFILL_OVERLAP"),
                 "overall": {"requested_partitions": rq, "verified_partitions": vf, "coverage": p6(ratio(vf, rq))}}

    # ---- observed processing rate (D-03)
    pm = data["processing_measurement"]
    if pm is None:
        rate = {"accepted_records": 0, "measured_seconds": None, "records_per_second": None, "hardware": None, "cache_state": None}
    else:
        n = sum(1 for a in accepted if a["batch_id"] == pm["batch_id"])
        sec = F(Decimal(pm["measured_seconds"]))
        rate = {"accepted_records": n, "measured_seconds": pm["measured_seconds"], "records_per_second": p6(ratio(n, sec)),
                "hardware": pm["hardware"], "cache_state": pm["cache_state"]}

    return {"contract_version": data["contract_version"], "as_of": data["as_of"], "cutoff": cutoff,
            "empty_population": empty, "ingest": {"counts": counts, "rejected_records": rejected},
            "metrics": {"ingestion": ingestion, "freshness": freshness, "completeness": completeness, "runs": runs_out,
                        "quality_gate": gate, "publications": publications, "late_events": late_out,
                        "reconciliation": recon, "incidents": incidents, "backfills": backfills, "processing_rate": rate}}


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


def integrity(label, data):
    """The fixture's own hashes follow the documented rules (D-01 payload_hash, definition_hash, content_hash)."""
    bad = [r["raw_record_id"] for r in data["raw_records"] if sha(canon(r["payload_json"])) != r["payload_hash"]]
    report(not bad, f"{label}.payload_hash_is_sha256_of_canonical_payload", "none wrong", bad or "all match")
    bad = [m["model_id"] for m in data["model_definitions"] if sha(m["definition"]) != m["definition_hash"]]
    report(not bad, f"{label}.definition_hash_is_sha256_of_definition", "none wrong", bad or "all match")
    qbad = []
    raw_by = {r["raw_record_id"]: r for r in data["raw_records"]}
    for q in data["quarantine_records"]:
        if not any(r["batch_id"] == q["batch_id"] and r["source_key"] == q["source_key"] and r["payload_hash"] == q["payload_hash"]
                   for r in raw_by.values()):
            qbad.append(q["quarantine_id"])
    report(not qbad, f"{label}.quarantine_rows_trace_to_raw_rows", "none orphaned", qbad or "all trace")


def check_fixture(label, prefix):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    no_floats(data, label + ".inputs")
    no_floats(exp, label)
    integrity(label, data)
    got = compute(data)
    fe, fg = flatten(exp), flatten(got)
    for k in fe:
        report(k in fg and fg[k] == fe[k], f"{label}.{k}", fe[k], fg.get(k, "<missing>"))
    for k in fg:
        if k not in fe:
            report(False, f"{label}.{k}", "<absent>", fg[k])
    return exp


def hand(exp):
    """The hand-worked figures of CALCULATION.md, typed as literals, against expected.json (not against compute)."""
    m = exp["metrics"]
    s = m["ingestion"]["sources"]["src-orders"]
    b1, b2, b3 = s["batches"]["b-001"], s["batches"]["b-002"], s["batches"]["b-003"]
    rc = m["reconciliation"]["pub-001"]
    rows = [
        ("hand.b001_received_10", 10, b1["received"]), ("hand.b001_accepted_unique_8", 8, b1["accepted_unique"]),
        ("hand.b001_duplicate_1", 1, b1["duplicate"]), ("hand.b001_quarantined_1", 1, b1["quarantined"]),
        ("hand.b001_rejection_rate_1_10", "0.100000", b1["rejection_rate"]),
        ("hand.b001_duplicate_rate_1_10", "0.100000", b1["duplicate_rate"]),
        ("hand.b002_replay_accepts_0_new", 0, b2["accepted_unique"]), ("hand.b002_duplicates_9", 9, b2["duplicate"]),
        ("hand.b002_quarantined_1", 1, b2["quarantined"]), ("hand.source_accepted_stays_8", 8, s["accepted_unique"]),
        ("hand.crash_batch_contributes_0", 0, b3["accepted_unique"]), ("hand.crash_batch_not_counted", False, b3["counted"]),
        ("hand.checkpoint_version_stays_2", 2, s["checkpoint"]["committed_version"]),
        ("hand.freshness_52200_s", 52200, m["freshness"]["src-orders"]["freshness_seconds"]),
        ("hand.ingestion_age_42900_s", 42900, m["freshness"]["src-orders"]["ingestion_age_seconds"]),
        ("hand.completeness_8_9", "0.888889", m["completeness"]["src-orders"]["2026-10-04"]["value"]),
        ("hand.run001_task_success_4_4", "1.000000", m["runs"]["runs"]["run-001"]["task_success_rate"]),
        ("hand.run001_attempts_4_of_5", "0.800000", m["runs"]["runs"]["run-001"]["attempt_success_rate"]),
        ("hand.run001_duration_1200_s", 1200, m["runs"]["runs"]["run-001"]["duration_seconds"]),
        ("hand.run001_gate_allowed", "allowed", m["quality_gate"]["run-001"]["decision"]),
        ("hand.run002_gate_blocked", "blocked", m["quality_gate"]["run-002"]["decision"]),
        ("hand.pointer_stays_on_pub001_after_run002", "pub-001", m["publications"]["pointer_history"][1]["pointer_after"]),
        ("hand.pub001_lag_3600_s", 3600, m["publications"]["publications"]["pub-001"]["lag_seconds"]),
        ("hand.late_events_1", 1, m["late_events"]["count"]),
        ("hand.late_event_in_pub003", "pub-003", m["late_events"]["events"][0]["included_in_publication_id"]),
        ("hand.source_total_289.94", "289.94", rc["source_total"]), ("hand.published_total_289.97", "289.97", rc["published_total"]),
        ("hand.exclusion_quarantined_-30.00", "-30.00", rc["exclusions"]["quarantined"]),
        ("hand.exclusion_duplicates_29.97", "29.97", rc["exclusions"]["duplicates"]),
        ("hand.residual_0.00", "0.00", rc["residual"]),
        ("hand.recovery_28500_s", 28500, m["incidents"]["incidents"]["inc-001"]["recovery_seconds"]),
        ("hand.recovery_475_minutes", "475.0000", m["incidents"]["incidents"]["inc-001"]["recovery_minutes"]),
        ("hand.backfill_coverage_2_3", "0.666667", m["backfills"]["requests"]["bf-001"]["coverage"]),
        ("hand.processing_rate_8_12", "0.666667", m["processing_rate"]["records_per_second"]),
        ("hand.freshness_differs_from_ingestion_age", True,
         m["freshness"]["src-orders"]["freshness_seconds"] != m["freshness"]["src-orders"]["ingestion_age_seconds"]),
    ]
    for name, want, got in rows:
        report(want == got, name, want, got)
    # recomputed here from the stated facts, with Fractions
    report(p6(F(1, 10)) == b1["rejection_rate"] == b1["duplicate_rate"], "hand.1_of_10_is_0.100000", "0.100000", b1["rejection_rate"])
    report(p6(F(8, 9)) == m["completeness"]["src-orders"]["2026-10-04"]["value"], "hand.8_of_9_is_0.888889", "0.888889", p6(F(8, 9)))
    report(p6(F(2, 3)) == m["backfills"]["requests"]["bf-001"]["coverage"], "hand.2_of_3_is_0.666667", "0.666667", p6(F(2, 3)))


def sha_file(rel):
    return hashlib.sha256((GOLDEN / rel).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true")
    args = ap.parse_args()
    exps = {}
    for label, prefix in FIXTURES:
        exps[label] = check_fixture(label, prefix)
    hand(exps["golden"])
    e = exps["variant-empty"]
    report(e["empty_population"] is True, "variant-empty.empty_population_true", True, e["empty_population"])
    hp = GOLDEN / "HASHES.json"
    if args.write_hashes:
        if failures:
            print(f"NOT WRITING HASHES: {failures} mismatch(es)")
        else:
            hp.write_text(json.dumps({"algorithm": "sha256", "sha256": {p: sha_file(p) for p in HASHED}}, indent=2) + "\n")
            print(f"OK wrote {hp.name}")
    elif hp.exists():
        stored = json.loads(hp.read_text())["sha256"]
        for p in HASHED:
            report(stored.get(p) == sha_file(p), f"hash.{p}", stored.get(p), sha_file(p))
    else:
        report(False, "hash.HASHES.json", "present", "missing")
    print("ALL OK" + f" ({checks} checks)" if not failures else f"{failures} MISMATCH(ES) of {checks} checks")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
