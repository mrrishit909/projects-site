"""The metrics tree (D-P8-07) in the exact key nesting of expected.json, computed from accepted entity rows.

``compute`` takes the rows that passed import validation (``ingest.validate_import``) and the rejected rows; ``run_pipeline`` does both from an
inputs.json-shaped dict. Every ratio is a ``Fraction`` rendered once (6 places, minutes 4 places), money is ``Decimal`` (2 places), null means
unknown or a zero denominator. No float anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from . import gate as gate_mod
from .classify import ACCEPTED, DELETED, DUPLICATE, QUARANTINED, Disposition, classify_rows, money_amount
from .contract import CONTRACT_VERSION, ENTITIES, METRIC_KEYS
from .ingest import ImportResult, validate_import
from .numbers import m4, p6, ratio
from .reconcile import Accepted, late_events, mean_minutes, publication_view, published_records, reconcile, recovery_minutes, verified_recovery
from .timeutil import day_partitions, iso_z, parse_ts, seconds_between, utc_date

Row = dict[str, Any]
INF = 10 ** 9


@dataclass
class Facts:
    """Everything derived from the accepted rows that more than one metric needs."""
    committed: list[Row]
    raws: dict[str, list[Row]]
    cp_by_batch: dict[str, Row]
    disposition: dict[str, Disposition]
    accepted: list[Accepted]
    amounts: dict[str, Decimal]
    derived_reasons: dict[str, list[str]] = field(default_factory=dict)


def derive(acc: dict[str, list[Row]], totf: str = "amount") -> Facts:
    """Classify every raw row of every committed batch (D-01). Batches are applied per source in checkpoint-version order (the order they
    committed in), falling back to (started_at, batch_id); a batch with a schema_version other than its source contract's is quarantined whole."""
    cp_by_batch = {c["batch_id"]: c for c in acc["checkpoints"]}
    contract_schema = {s["source_id"]: s.get("schema_version") for s in acc["source_contracts"]}
    committed = sorted((b for b in acc["ingestion_batches"] if b["status"] == "committed"),
                       key=lambda b: (cp_by_batch[b["batch_id"]]["version_number"] if b["batch_id"] in cp_by_batch else INF,
                                      parse_ts(b["started_at"]), b["batch_id"]))
    raws: dict[str, list[Row]] = {}
    for r in acc["raw_records"]:
        raws.setdefault(r["batch_id"], []).append(r)
    for rows in raws.values():
        rows.sort(key=lambda r: r["raw_record_id"])
    disposition: dict[str, Disposition] = {}
    keys: dict[str, set[str]] = {}
    deleted: dict[str, set[str]] = {}
    accepted: list[Accepted] = []
    by_key: dict[tuple[str, str], Accepted] = {}
    for b in committed:
        sid = b["source_id"]
        schema_ok = b.get("schema_version") in (None, contract_schema.get(sid))
        for d in classify_rows(raws.get(b["batch_id"], []), keys.setdefault(sid, set()), deleted.setdefault(sid, set()), schema_ok):
            disposition[d.raw_record_id] = d
        cp = cp_by_batch.get(b["batch_id"])
        for r in raws.get(b["batch_id"], []):
            d = disposition[r["raw_record_id"]]
            if d.kind == ACCEPTED:
                a = Accepted(sid, b["batch_id"], r["source_key"], r["payload_json"]["event_ts"], cp["committed_at"] if cp else None,
                             r["raw_record_id"], r["payload_hash"], money_amount(r["payload_json"], totf))
                accepted.append(a)
                by_key[(sid, a.key)] = a
            elif d.kind == DELETED and (sid, r["source_key"]) in by_key:
                by_key[(sid, r["source_key"])].deleted_in = b["batch_id"]
    amounts = {r["raw_record_id"]: money_amount(r["payload_json"], totf) for b in committed for r in raws.get(b["batch_id"], [])}
    reasons: dict[str, list[str]] = {}
    for b in committed:
        reasons[b["batch_id"]] = sorted(disposition[r["raw_record_id"]].reason for r in raws.get(b["batch_id"], [])
                                        if disposition[r["raw_record_id"]].kind == QUARANTINED)
    return Facts(committed, raws, cp_by_batch, disposition, accepted, amounts, reasons)


def _ingestion(acc: dict[str, list[Row]], f: Facts) -> Row:
    quar_rows: dict[str, list[Row]] = {}
    for q in acc["quarantine_records"]:
        quar_rows.setdefault(q["batch_id"], []).append(q)
    sources: dict[str, Row] = {}
    tot = [0, 0, 0, 0]
    for s in sorted(acc["source_contracts"], key=lambda s: s["source_id"]):
        sid = s["source_id"]
        batches: dict[str, Row] = {}
        rec = nacc = dup = qua = 0
        by_reason: dict[str, int] = {}
        for b in acc["ingestion_batches"]:
            if b["source_id"] != sid:
                continue
            rows = f.raws.get(b["batch_id"], [])
            if b["status"] != "committed":
                batches[b["batch_id"]] = {"status": b["status"], "counted": False, "written_rows": len(rows), "received": 0, "accepted_unique": 0,
                                          "duplicate": 0, "quarantined": 0, "rejection_rate": None, "duplicate_rate": None,
                                          "quarantine_rows_match": True}
                continue
            kinds = [f.disposition[r["raw_record_id"]].kind for r in rows]
            n, a_, d_, q_ = len(rows), kinds.count(ACCEPTED), kinds.count(DUPLICATE), kinds.count(QUARANTINED)
            batches[b["batch_id"]] = {"status": "committed", "counted": True, "written_rows": n, "received": n, "accepted_unique": a_,
                                      "duplicate": d_, "quarantined": q_, "rejection_rate": p6(ratio(q_, n)), "duplicate_rate": p6(ratio(d_, n)),
                                      "quarantine_rows_match": f.derived_reasons[b["batch_id"]] == sorted(q["reason_code"] for q in quar_rows.get(b["batch_id"], []))}
            rec, nacc, dup, qua = rec + n, nacc + a_, dup + d_, qua + q_
            for reason in f.derived_reasons[b["batch_id"]]:
                by_reason[reason] = by_reason.get(reason, 0) + 1
        qkeys = {r["source_key"] for b in f.committed if b["source_id"] == sid for r in f.raws.get(b["batch_id"], [])
                 if f.disposition[r["raw_record_id"]].kind == QUARANTINED and r.get("source_key") is not None}
        cps = sorted((f.cp_by_batch[b["batch_id"]] for b in f.committed if b["source_id"] == sid and b["batch_id"] in f.cp_by_batch),
                     key=lambda c: c["version_number"])
        last = cps[-1] if cps else None
        unc = sorted(b["batch_id"] for b in acc["ingestion_batches"] if b["source_id"] == sid and b["status"] != "committed")
        sources[sid] = {"batches": batches, "received": rec, "accepted_unique": nacc, "duplicate": dup, "quarantined": qua,
                        "quarantined_distinct_keys": len(qkeys), "rejection_rate": p6(ratio(qua, rec)), "duplicate_rate": p6(ratio(dup, rec)),
                        "quarantine_by_reason": dict(sorted(by_reason.items())),
                        "checkpoint": {"committed_version": last["version_number"] if last else None,
                                       "committed_cursor": last["committed_cursor"] if last else None,
                                       "committed_batch_id": last["batch_id"] if last else None, "uncommitted_batches": unc,
                                       "uncommitted_batches_with_checkpoint": sum(1 for u in unc if u in f.cp_by_batch)}}
        tot = [tot[0] + rec, tot[1] + nacc, tot[2] + dup, tot[3] + qua]
    return {"sources": sources, "overall": {"received": tot[0], "accepted_unique": tot[1], "duplicate": tot[2], "quarantined": tot[3],
                                            "rejection_rate": p6(ratio(tot[3], tot[0])), "duplicate_rate": p6(ratio(tot[2], tot[0]))}}


def _freshness(acc: dict[str, list[Row]], f: Facts, cutoff: str) -> Row:
    out = {}
    for s in sorted(acc["source_contracts"], key=lambda s: s["source_id"]):
        sid = s["source_id"]
        events = [a.event_at for a in f.accepted if a.source_id == sid]
        ingested = [f.cp_by_batch[b["batch_id"]]["committed_at"] for b in f.committed if b["source_id"] == sid and b["batch_id"] in f.cp_by_batch]
        le = max(events, key=parse_ts) if events else None          # freshness: cutoff - latest accepted source event
        li = max(ingested, key=parse_ts) if ingested else None      # ingestion age: cutoff - last committed batch (D-P8-03)
        out[sid] = {"latest_accepted_event_at": iso_z(le), "freshness_seconds": seconds_between(le, cutoff) if le else None,
                    "last_successful_ingestion_at": iso_z(li), "ingestion_age_seconds": seconds_between(li, cutoff) if li else None}
    return out


def _completeness(expectations: list[Row], f: Facts) -> Row:
    out: dict[str, Row] = {}
    for x in expectations:
        n = sum(1 for a in f.accepted if a.source_id == x["source_id"] and utc_date(a.event_at) == x["partition"])
        out.setdefault(x["source_id"], {})[x["partition"]] = {"expected_records": x["expected_records"], "accepted_records": n,
                                                              "value": p6(ratio(n, x["expected_records"]))}
    return out


def _runs(acc: dict[str, list[Row]]) -> tuple[Row, dict[str, Row]]:
    tasks: dict[str, dict[str, list[Row]]] = {}
    for t in acc["task_runs"]:
        tasks.setdefault(t["run_id"], {}).setdefault(t["task_name"], []).append(t)
    runs: dict[str, Row] = {}
    total = [0, 0, 0, 0]
    durations: dict[str, list[int]] = {"success": [], "failed": []}
    for run in sorted(acc["pipeline_runs"], key=lambda r: r["run_id"]):
        rid = run["run_id"]
        per_task: dict[str, Row] = {}
        for name, attempts in sorted(tasks.get(rid, {}).items()):
            attempts.sort(key=lambda t: int(t["attempt"]))
            per_task[name] = {"attempts": len(attempts), "final_status": attempts[-1]["status"]}
        terminal = [v for v in per_task.values() if v["final_status"] in ("success", "failed")]
        ok = sum(1 for v in terminal if v["final_status"] == "success")
        n_attempts = sum(v["attempts"] for v in per_task.values())
        ok_attempts = sum(1 for t in acc["task_runs"] if t["run_id"] == rid and t["status"] == "success")
        d = seconds_between(run["started_at"], run["finished_at"]) if run.get("finished_at") else None
        if d is not None and run["status"] in durations:
            durations[run["status"]].append(d)
        runs[rid] = {"status": run["status"], "duration_seconds": d, "tasks": per_task, "tasks_terminal": len(terminal), "tasks_successful": ok,
                     "task_success_rate": p6(ratio(ok, len(terminal))), "attempts": n_attempts, "attempts_successful": ok_attempts,
                     "attempt_success_rate": p6(ratio(ok_attempts, n_attempts))}
        total = [total[0] + len(terminal), total[1] + ok, total[2] + n_attempts, total[3] + ok_attempts]

    def group(ds: list[int]) -> Row:
        return {"count": len(ds), "durations_seconds": sorted(ds), "mean_minutes": m4(ratio(sum(ds), 60 * len(ds)))}
    out = {"runs": runs, "overall": {"tasks_terminal": total[0], "tasks_successful": total[1], "task_success_rate": p6(ratio(total[1], total[0])),
                                     "attempts": total[2], "attempts_successful": total[3], "attempt_success_rate": p6(ratio(total[3], total[2]))},
           "durations": {"successful": group(durations["success"]), "failed": group(durations["failed"])}}
    return out, runs


def _gates(acc: dict[str, list[Row]]) -> dict[str, Row]:
    run_of = {t["task_run_id"]: t["run_id"] for t in acc["task_runs"]}
    return {run["run_id"]: gate_mod.decide(q for q in acc["quality_results"] if run_of[q["task_run_id"]] == run["run_id"])
            for run in sorted(acc["pipeline_runs"], key=lambda r: r["run_id"])}


def publication_scope(pub: Row, f: Facts) -> tuple[list[str], list[Accepted], list[tuple[str, Decimal]], list[Accepted], Decimal]:
    """(included committed batches, published records, (disposition, amount) of every received row, records a delete removed, delete rows' amount)."""
    committed_ids = {b["batch_id"] for b in f.committed}
    inc = [b for b in pub["included_batch_ids"] if b in committed_ids]
    rows = [r for b in inc for r in f.raws.get(b, [])]
    src_rows = [(f.disposition[r["raw_record_id"]].kind, f.amounts[r["raw_record_id"]]) for r in rows]
    pubd = published_records(f.accepted, inc)
    removed = [a for a in f.accepted if a.batch_id in inc and a.deleted_in in inc]
    del_rows = sum((amt for k, amt in src_rows if k == DELETED), Decimal("0"))
    return inc, pubd, src_rows, removed, del_rows


def compute(acc: dict[str, list[Row]], rejected: list[Row], params: dict[str, Any]) -> Row:
    """The full golden shape. ``params``: contract_version, as_of, cutoff, business_total_field, freshness_timestamp_field (the payload
    field is ``event_ts`` in this contract), source_expectations, processing_measurement, and optionally published_totals (publication_id ->
    Decimal total of the stored published table, which replaces the sum of the accepted records in the reconciliation)."""
    cutoff = params["cutoff"]
    f = derive(acc, params.get("business_total_field", "amount"))
    counts = {e: {"accepted": len(acc[e]), "rejected": sum(1 for r in rejected if r["entity"] == e)} for e in ENTITIES}
    ingestion = _ingestion(acc, f)
    runs_out, _ = _runs(acc)
    gates = _gates(acc)

    pubs_sorted = sorted(acc["publications"], key=lambda p: (parse_ts(p["published_at"]), p["publication_id"]))
    pubs: dict[str, Row] = {}
    recon: dict[str, Row] = {}
    for p in pubs_sorted:
        inc, pubd, src_rows, removed, del_rows = publication_scope(p, f)
        view = publication_view(p, pubd)
        pubs[p["publication_id"]] = {"run_id": p["run_id"], "published_at": iso_z(p["published_at"]), "watermark": iso_z(p["watermark"]),
                                     "included_batches": sorted(inc), "published_records": len(pubd), "latest_included_event_at": iso_z(view["latest"]),
                                     "lag_seconds": view["lag_seconds"], "content_hash_ok": view["content_hash"] == p["content_hash"]}
        recon[p["publication_id"]] = reconcile(src_rows, pubd, del_rows, removed, (params.get("published_totals") or {}).get(p["publication_id"]))
    pub_of_run = {p["run_id"]: p["publication_id"] for p in pubs_sorted}
    pointer: str | None = None
    history = []
    for run in sorted(acc["pipeline_runs"], key=lambda r: (parse_ts(r.get("finished_at") or r["started_at"]), r["run_id"])):
        decision = gates[run["run_id"]]["decision"]
        if gate_mod.may_publish(run["status"], decision, run["run_id"] in pub_of_run):
            pointer = pub_of_run[run["run_id"]]
        history.append({"run_id": run["run_id"], "gate_decision": decision, "pointer_after": pointer})
    publications = {"current_publication_id": pointer, "pointer_history": history, "publications": pubs}

    late = late_events(f.accepted, acc["publications"])
    late_out = {"count": len(late), "included_in_next_publication": sum(1 for x in late if x["included_in_publication_id"]),
                "lost": sum(1 for x in late if not x["included_in_publication_id"]), "events": late}

    gate_of = {rid: g["decision"] for rid, g in gates.items()}
    residual_of = {pid: r["residual"] for pid, r in recon.items()}
    incidents: dict[str, Row] = {}
    tally = {"closed": 0, "open": 0, "verified": 0, "seconds": 0}
    for i in sorted(acc["incidents"], key=lambda i: i["incident_id"]):
        found = verified_recovery(i["opened_at"], acc["pipeline_runs"], gate_of, pub_of_run, residual_of)
        verified_at = pubs[found["publication_id"]]["published_at"] if found else None
        sec = seconds_between(i["opened_at"], verified_at) if found else None
        consistent = i["status"] != "closed" or (found is not None and i.get("recovery_run_id") == found["run"]["run_id"]
                                                 and i.get("closed_at") is not None and parse_ts(i["closed_at"]) == parse_ts(verified_at))
        incidents[i["incident_id"]] = {"run_id": i["run_id"], "status": i["status"], "detected_at": iso_z(i["opened_at"]), "verified": found is not None,
                                       "recovery_run_id": found["run"]["run_id"] if found else None, "verified_at": verified_at,
                                       "recovery_seconds": sec, "recovery_minutes": recovery_minutes(sec), "closure_consistent": consistent}
        tally["closed" if i["status"] == "closed" else "open"] += 1
        if found:
            tally["verified"] += 1
            tally["seconds"] += sec
    incident_out = {"total": len(incidents), "open": tally["open"], "closed": tally["closed"], "verified": tally["verified"],
                    "mean_recovery_minutes": mean_minutes(tally["seconds"], tally["verified"]), "incidents": incidents}

    requests: dict[str, Row] = {}
    req = ver = 0
    for b in sorted(acc["backfill_requests"], key=lambda b: b["backfill_id"]):
        parts = day_partitions(b["start_at"], b["end_at"])
        verified = sorted(p["partition"] for p in b["partitions"] if p["verified"] and p["partition"] in parts)
        requests[b["backfill_id"]] = {"source_id": b["source_id"], "start_at": iso_z(b["start_at"]), "end_at": iso_z(b["end_at"]),
                                      "requested_partitions": len(parts), "verified_partitions": len(verified), "coverage": p6(ratio(len(verified), len(parts)))}
        req, ver = req + len(parts), ver + len(verified)
    backfills = {"requests": requests, "refused": sorted(r["id"] for r in rejected if r["entity"] == "backfill_requests" and r["reason_code"] == "BACKFILL_OVERLAP"),
                 "overall": {"requested_partitions": req, "verified_partitions": ver, "coverage": p6(ratio(ver, req))}}

    pm = params.get("processing_measurement")
    if pm is None:
        rate: Row = {"accepted_records": 0, "measured_seconds": None, "records_per_second": None, "hardware": None, "cache_state": None}
    else:
        n = sum(1 for a in f.accepted if a.batch_id == pm["batch_id"])
        secs = Decimal(str(pm["measured_seconds"]))
        rate = {"accepted_records": n, "measured_seconds": pm["measured_seconds"] if isinstance(pm["measured_seconds"], str) else format(secs, "f"),
                "records_per_second": p6(ratio(n, _fraction(secs))), "hardware": pm["hardware"], "cache_state": pm["cache_state"]}

    return {"contract_version": params["contract_version"], "as_of": params["as_of"], "cutoff": cutoff,
            "empty_population": len(acc["raw_records"]) == 0, "ingest": {"counts": counts, "rejected_records": rejected},
            "metrics": {"ingestion": ingestion, "freshness": _freshness(acc, f, cutoff), "completeness": _completeness(params["source_expectations"], f),
                        "runs": runs_out, "quality_gate": gates, "publications": publications, "late_events": late_out, "reconciliation": recon,
                        "incidents": incident_out, "backfills": backfills, "processing_rate": rate}}


def _fraction(d: Decimal):
    from fractions import Fraction
    return Fraction(d)


def params_of(data: dict[str, Any]) -> dict[str, Any]:
    return {"contract_version": data.get("contract_version", CONTRACT_VERSION), "as_of": data["as_of"], "cutoff": data["cutoff"],
            "business_total_field": data.get("business_total_field", "amount"), "source_expectations": data.get("source_expectations", []),
            "processing_measurement": data.get("processing_measurement")}


@dataclass
class PipelineResult:
    imported: ImportResult
    golden: Row

    @property
    def metrics(self) -> Row:
        return self.golden["metrics"]

    @property
    def counts(self) -> Row:
        return self.golden["ingest"]["counts"]

    @property
    def rejected(self) -> list[Row]:
        return self.imported.rejected

    @property
    def empty_population(self) -> bool:
        return self.golden["empty_population"]


def run_pipeline(data: dict[str, Any]) -> PipelineResult:
    """Import-validate an inputs.json-shaped dict and compute the golden shape."""
    imp = validate_import(data)
    return PipelineResult(imp, compute(imp.accepted, imp.rejected, params_of(data)))


__all__ = ["compute", "run_pipeline", "derive", "Facts", "publication_scope", "params_of", "PipelineResult", "METRIC_KEYS"]
