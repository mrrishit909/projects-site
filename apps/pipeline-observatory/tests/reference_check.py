#!/usr/bin/env python3
"""Independent reference calculation for the Pipeline Observatory golden fixtures (P08-GOLD-01..11).

Standard library only; imports nothing from the application. Recomputes every figure in expected.json from
inputs.json (entity import validation and rejection with dependants, duplicate / quarantine classification on
source_key, per-batch and per-source counts and rates, checkpoint versions, freshness vs ingestion age,
completeness against the declared expectation, task and attempt success, run durations, the fail-closed
quality gate and the atomic publication pointer, publication lag and watermark, late events, reconciliation
residual with its parts, verified incident recovery, half-open backfills with overlap refusal, the observed
processing rate) and compares leaf by leaf, then replays the shared divergence cases (tests/fixtures/divergence/cases.json: ASCII-only
full-match patterns, big and non-integer JSON numbers, impossible dates, sub-microsecond fractions, future-dated events) with its own
hand-written parsers. It also recomputes every payload_hash, definition_hash and
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
DIVERGENCE = Path(__file__).resolve().parent / "fixtures" / "divergence" / "cases.json"
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
    return parse_instant(s)


def secs(a, b):
    """Whole seconds from a to b (floor, integer arithmetic)."""
    return (ts(b) - ts(a)) // timedelta(seconds=1)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def canon(p):
    return json.dumps(p, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------- D-09 patterns, written by hand (no regular expression, no application import)
def all_digits(x):
    return len(x) > 0 and all(c in "0123456789" for c in x)


def is_money(v):
    """-?digits(.d|.dd)? and nothing else: no newline, no space, no non-ASCII digit."""
    if not isinstance(v, str):
        return False
    body = v[1:] if v.startswith("-") else v
    whole, dot, frac = body.partition(".")
    return all_digits(whole) and (not dot or (1 <= len(frac) <= 2 and all_digits(frac)))


def is_quantity(v):
    """A JSON integer (not a bool, not a float such as 3.0) of magnitude at most 2**53."""
    return type(v) is int and abs(v) <= 2 ** 53


def parse_instant(v):
    """UTC datetime of YYYY-MM-DD[T ]HH:MM:SS[.f+](Z|+hh:mm|-hh:mm), or None. Digits beyond microseconds are truncated; a real calendar only."""
    if not isinstance(v, str) or len(v) < 20:
        return None
    if v.endswith("Z"):
        body, off = v[:-1], timedelta(0)
    else:
        if v[-6] not in "+-" or v[-3] != ":" or not (all_digits(v[-5:-3]) and all_digits(v[-2:])):
            return None
        if int(v[-5:-3]) > 23 or int(v[-2:]) > 59:
            return None
        off = timedelta(hours=int(v[-5:-3]), minutes=int(v[-2:])) * (1 if v[-6] == "+" else -1)
        body = v[:-6]
    if len(body) < 19 or body[4] != "-" or body[7] != "-" or body[10] not in "T " or body[13] != ":" or body[16] != ":":
        return None
    y, mo, d, h, mi, s = body[0:4], body[5:7], body[8:10], body[11:13], body[14:16], body[17:19]
    rest = body[19:]
    if not all(all_digits(x) for x in (y, mo, d, h, mi, s)):
        return None
    if rest and not (rest[0] == "." and all_digits(rest[1:])):
        return None
    micro = int((rest[1:7] if rest else "").ljust(6, "0"))
    try:
        return (datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), micro, tzinfo=timezone.utc) - off).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"


def contract_reason(p, started_at, cutoff):
    """MISSING_FIELD, INVALID_FIELD, NEGATIVE_QUANTITY, EVENT_IN_FUTURE (an event after its batch's arrival or after the cutoff), else None."""
    if not isinstance(p, dict):
        return "INVALID_FIELD"
    if any(p.get(k) is None for k in REQUIRED):
        return "MISSING_FIELD"
    if not is_quantity(p["quantity"]) or not is_money(p["unit_price"]) or not is_money(p["amount"]):
        return "INVALID_FIELD"
    ev = parse_instant(p["event_ts"])
    if ev is None:
        return "INVALID_FIELD"
    if p["quantity"] < 0:
        return "NEGATIVE_QUANTITY"
    if ev > min(parse_instant(started_at), parse_instant(cutoff)):
        return "EVENT_IN_FUTURE"
    return None


def amount_value(p, field):
    """The business amount of a payload; a row without a usable amount counts 0.00."""
    return Decimal(p[field]) if isinstance(p, dict) and is_money(p.get(field)) else Decimal("0")


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
        if e == "quality_results" and row.get("severity") not in ("critical", "warning"):
            return "INVALID_FIELD"
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
    # backfills: half-open [start, end); a request overlapping an earlier accepted one of the same source that was still ACTIVE is refused.
    # Active = status requested or running, or (the request carries requested_at) settled after the request was made; a request with no clock
    # (a static snapshot) cannot say what was running, so every earlier accepted request counts.
    for row in data["backfill_requests"]:
        code = common("backfill_requests", row)
        if code is None:
            s, e_ = ts(row["start_at"]), ts(row["end_at"])
            for o in acc["backfill_requests"]:
                if o["source_id"] == row["source_id"] and s < ts(o["end_at"]) and ts(o["start_at"]) < e_:
                    at = row.get("requested_at")
                    if at is None or o["status"] in ("requested", "running") or (o.get("settled_at") is not None and at < o["settled_at"]):
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
            seen_pk["ingestion_batches"].add(row["batch_id"])         # a repeated batch_id is DUPLICATE_ID before acceptance
    batch_ids = {b["batch_id"] for b in batch_rows}
    bad_cp_batches = set()
    first_ids, firsts = set(), []
    for c in data["checkpoints"]:                      # a repeated checkpoint id takes no part in the ordering: it is DUPLICATE_ID
        if c["checkpoint_id"] not in first_ids:
            first_ids.add(c["checkpoint_id"])
            firsts.append(c)
    cps = [c for c in firsts if c["batch_id"] in batch_ids]
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
    seen_cp = set()
    for c in data["checkpoints"]:
        repeat = c["checkpoint_id"] in seen_cp
        seen_cp.add(c["checkpoint_id"])
        code = ("DUPLICATE_ID" if repeat else None) or cp_reason.get(c["checkpoint_id"]) or common("checkpoints", c)
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
    return amount_value(raw["payload_json"], field)


def compute(data):
    acc, rejected = validate_import(data)
    counts = {e: {"accepted": len(acc[e]), "rejected": sum(1 for r in rejected if r["entity"] == e)} for e in ENTITIES}
    cutoff = data["cutoff"]
    tsf = data["freshness_timestamp_field"]
    totf = data["business_total_field"]
    for r in acc["raw_records"]:
        assert not isinstance(r["payload_json"], dict) or r["payload_json"].get("op", "upsert") == "upsert", "delete events are not exercised by this fixture"
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
            why = contract_reason(p, b["started_at"], cutoff)
            if r["source_key"] in keys:
                cls[r["raw_record_id"]] = "duplicate"
            elif why or r["source_key"] is None:
                cls[r["raw_record_id"]], reason[r["raw_record_id"]] = "quarantined", why or "MISSING_FIELD"
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
                dt = parse_instant(r["payload_json"][tsf])
                accepted.append({"source_id": b["source_id"], "batch_id": b["batch_id"], "key": r["source_key"],
                                 "event": iso(dt), "dt": dt, "arrival": cp["committed_at"] if cp else None,
                                 "raw": r, "hash": r["payload_hash"]})

    # ---- freshness vs ingestion age (D-02)
    freshness = {}
    for sid in sources:
        ev = [a["dt"] for a in accepted if a["source_id"] == sid]
        ing = [cp_by_batch[b["batch_id"]]["committed_at"] for b in committed
               if b["source_id"] == sid and b["batch_id"] in cp_by_batch]
        le, li = (iso(max(ev)) if ev else None), (max(ing, key=ts) if ing else None)
        freshness[sid] = {"latest_accepted_event_at": le, "freshness_seconds": secs(le, cutoff) if le else None,
                          "freshness_reason": None if le else "NO_ACCEPTED_EVENT", "last_successful_ingestion_at": li, "ingestion_age_seconds": secs(li, cutoff) if li else None}

    # ---- completeness against the declared expectation (D-02)
    completeness = {}
    for x in data["source_expectations"]:
        n = sum(1 for a in accepted if a["source_id"] == x["source_id"] and a["dt"].strftime("%Y-%m-%d") == x["partition"])
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
        latest = iso(max((a["dt"] for a in pubd))) if pubd else None
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
        if a["dt"] <= ts(p["watermark"]):
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
    rf, b101 = m["ingestion"]["sources"]["src-refunds"], m["ingestion"]["sources"]["src-refunds"]["batches"]["b-101"]
    ov, rc3 = m["ingestion"]["overall"], m["reconciliation"]["pub-003"]
    rows += [
        # D-09 R8-01: b-101 also carries REF-2002, dated 12:00 while the batch arrived at 11:00 -> quarantined EVENT_IN_FUTURE
        ("hand.b101_received_2", 2, b101["received"]), ("hand.b101_accepted_1", 1, b101["accepted_unique"]),
        ("hand.b101_quarantined_1", 1, b101["quarantined"]), ("hand.b101_rejection_rate_1_2", "0.500000", b101["rejection_rate"]),
        ("hand.b101_reason_EVENT_IN_FUTURE", {"EVENT_IN_FUTURE": 1}, rf["quarantine_by_reason"]),
        ("hand.refunds_freshness_stays_53400_s", 53400, m["freshness"]["src-refunds"]["freshness_seconds"]),
        ("hand.refunds_latest_event_still_0910", "2026-10-04T09:10:00Z", m["freshness"]["src-refunds"]["latest_accepted_event_at"]),
        ("hand.freshness_reason_none_when_a_value_exists", None, m["freshness"]["src-orders"]["freshness_reason"]),
        ("hand.overall_received_22", 22, ov["received"]), ("hand.overall_accepted_9", 9, ov["accepted_unique"]),
        ("hand.overall_duplicates_10", 10, ov["duplicate"]), ("hand.overall_quarantined_3", 3, ov["quarantined"]),
        ("hand.overall_rejection_rate_3_22", "0.136364", ov["rejection_rate"]), ("hand.overall_duplicate_rate_10_22", "0.454545", ov["duplicate_rate"]),
        ("hand.pub003_source_total_599.88", "599.88", rc3["source_total"]), ("hand.pub003_published_total_301.97", "301.97", rc3["published_total"]),
        ("hand.pub003_quarantined_-52.00", "-52.00", rc3["exclusions"]["quarantined"]),
        ("hand.pub003_duplicates_349.91", "349.91", rc3["exclusions"]["duplicates"]),
        ("hand.pub003_exclusions_297.91", "297.91", rc3["exclusions_total"]), ("hand.pub003_residual_0.00", "0.00", rc3["residual"]),
    ]
    for name, want, got in rows:
        report(want == got, name, want, got)
    # recomputed here from the stated facts, with Fractions
    report(p6(F(1, 10)) == b1["rejection_rate"] == b1["duplicate_rate"], "hand.1_of_10_is_0.100000", "0.100000", b1["rejection_rate"])
    report(p6(F(8, 9)) == m["completeness"]["src-orders"]["2026-10-04"]["value"], "hand.8_of_9_is_0.888889", "0.888889", p6(F(8, 9)))
    report(p6(F(2, 3)) == m["backfills"]["requests"]["bf-001"]["coverage"], "hand.2_of_3_is_0.666667", "0.666667", p6(F(2, 3)))
    report(p6(F(1, 2)) == b101["rejection_rate"], "hand.1_of_2_is_0.500000", "0.500000", p6(F(1, 2)))
    report(p6(F(3, 22)) == ov["rejection_rate"] and p6(F(10, 22)) == ov["duplicate_rate"], "hand.3_and_10_of_22", "0.136364 / 0.454545", (p6(F(3, 22)), p6(F(10, 22))))
    report(money(Decimal("289.94") + Decimal("289.94") + Decimal("12.00") + Decimal("8.00")) == rc3["source_total"], "hand.pub003_source_289.94+289.94+12.00+8.00", "599.88", rc3["source_total"])
    report(money(Decimal("-30.00") * 2 + Decimal("8.00")) == rc3["exclusions"]["quarantined"], "hand.pub003_quarantined_-30.00x2+8.00", "-52.00", rc3["exclusions"]["quarantined"])


def check_divergence():
    """The shared divergence cases (D-09): every case classified by this file's own hand-written patterns and parsers."""
    doc = json.loads(DIVERGENCE.read_text(encoding="utf-8"))          # floats stay floats (3.0), big integers stay integers
    batches = {b["batch_id"]: b for b in doc["batches"]}
    bad = []
    for c in doc["cases"]:
        why = contract_reason(c["payload"], batches[c["batch"]]["started_at"], doc["cutoff"])
        got = "quarantined" if why else "accepted"
        if (got, why) != (c["disposition"], c["reason"]):
            bad.append((c["id"], (got, why), (c["disposition"], c["reason"])))
        if "event_at" in c and iso(parse_instant(c["payload"]["event_ts"])) != c["event_at"]:
            bad.append((c["id"], iso(parse_instant(c["payload"]["event_ts"])), c["event_at"]))
    report(not bad, "divergence.every_case_classified_as_the_shared_table_says", "none differ", bad or f"all {len(doc['cases'])} agree")
    # the lexemes the table depends on are still lexemes (a re-serialisation would silently turn 3.0 into 3)
    by = {c["id"]: c for c in doc["cases"]}
    report(isinstance(by["quantity-float-3.0"]["payload"]["quantity"], float) and type(by["quantity-big"]["payload"]["quantity"]) is int,
           "divergence.3.0_is_a_float_and_2^53+1_an_integer", True, True)


def check_rules(label, data):
    """D-09 rules the fixtures do not carry, on mutated copies of the golden inputs, with the outcome written by hand (not compared with another implementation)."""
    import copy
    base = compute(data)
    # R8-03: a repeated batch_id (and its repeated rows) is DUPLICATE_ID; the counts do not double
    d = copy.deepcopy(data)
    d["ingestion_batches"].append(copy.deepcopy(d["ingestion_batches"][0]))
    d["raw_records"] += copy.deepcopy([r for r in d["raw_records"] if r["batch_id"] == "b-001"])
    got = compute(d)
    codes = {(r["entity"], r["id"]): r["reason_code"] for r in got["ingest"]["rejected_records"]}
    report(codes.get(("ingestion_batches", "b-001")) == "DUPLICATE_ID" and got["metrics"]["ingestion"]["overall"] == base["metrics"]["ingestion"]["overall"],
           f"{label}.rule.a_repeated_batch_id_is_DUPLICATE_ID_and_counts_do_not_double", "DUPLICATE_ID, same counts", (codes.get(("ingestion_batches", "b-001")), got["metrics"]["ingestion"]["overall"]))
    # a repeated checkpoint id is DUPLICATE_ID and does not poison its batch
    d = copy.deepcopy(data)
    d["checkpoints"].append(copy.deepcopy(d["checkpoints"][0]))
    got = compute(d)
    report([(r["entity"], r["reason_code"]) for r in got["ingest"]["rejected_records"]] == [("checkpoints", "DUPLICATE_ID")] and got["metrics"]["ingestion"] == base["metrics"]["ingestion"],
           f"{label}.rule.a_repeated_checkpoint_id_is_DUPLICATE_ID_and_its_batch_stays", "[checkpoints DUPLICATE_ID]", [(r["entity"], r["reason_code"]) for r in got["ingest"]["rejected_records"]])
    # severity: anything but critical / warning is INVALID_FIELD, and a gate left with no critical result blocks
    d = copy.deepcopy(data)
    first = d["quality_results"][0]
    first["severity"] = "Critical"
    got = compute(d)
    report([(r["id"], r["reason_code"]) for r in got["ingest"]["rejected_records"]] == [(first["quality_result_id"], "INVALID_FIELD")]
           and got["metrics"]["quality_gate"]["run-001"]["decision"] == "blocked", f"{label}.rule.severity_is_validated_and_the_gate_fails_closed", "INVALID_FIELD, blocked", [r["reason_code"] for r in got["ingest"]["rejected_records"]])
    # R8-12: a request made while its victim was running is refused; one made after the victim settled is accepted; a clockless snapshot counts every earlier one
    def bfr(i, s_, e, status="requested", **more):
        return {"backfill_id": f"bf-{i:03d}", "source_id": "src-orders", "start_at": f"{s_}T00:00:00Z", "end_at": f"{e}T00:00:00Z", "status": status,
                "partitions": [{"partition": s_, "verified": False}], **more}
    d = copy.deepcopy(data)
    d["backfill_requests"] = [bfr(1, "2026-09-01", "2026-09-03", "partial", requested_at="2026-08-30T10:00:00Z", settled_at="2026-08-30T12:00:00Z"),
                              bfr(2, "2026-09-02", "2026-09-03", requested_at="2026-08-30T11:00:00Z"), bfr(3, "2026-09-02", "2026-09-03", requested_at="2026-08-30T13:00:00Z")]
    got = compute(d)
    report(got["metrics"]["backfills"]["refused"] == ["bf-002"] and sorted(got["metrics"]["backfills"]["requests"]) == ["bf-001", "bf-003"],
           f"{label}.rule.overlap_is_judged_against_requests_still_active", "bf-002 refused", got["metrics"]["backfills"]["refused"])
    d["backfill_requests"] = [bfr(1, "2026-09-01", "2026-09-03", "partial"), bfr(2, "2026-09-02", "2026-09-03")]
    got = compute(d)
    report(got["metrics"]["backfills"]["refused"] == ["bf-002"], f"{label}.rule.a_clockless_snapshot_counts_every_earlier_request", "bf-002 refused", got["metrics"]["backfills"]["refused"])
    # R8-01 with an unaccepted refund: nothing accepted from src-refunds -> freshness null with a reason, never negative
    d = copy.deepcopy(data)
    d["raw_records"] = [r for r in d["raw_records"] if r["raw_record_id"] != "rr-b-101-01"]
    d["quarantine_records"] = [q for q in d["quarantine_records"] if q["quarantine_id"] != "q-b-101-99"]
    f = compute(d)["metrics"]["freshness"]["src-refunds"]
    report(f["freshness_seconds"] is None and f["freshness_reason"] == "NO_ACCEPTED_EVENT", f"{label}.rule.freshness_is_null_with_a_reason_when_nothing_is_accepted", "null, NO_ACCEPTED_EVENT", f)


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
    check_divergence()
    check_rules("golden", json.loads((GOLDEN / "inputs.json").read_text()))
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
