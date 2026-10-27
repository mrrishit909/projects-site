"""The independent Python side of the analysis (P08-ART-04): every result set of investigations 01..08 and 10 recomputed from the RAW published JSON.

Standard library only (``json``, ``re``, ``hashlib``, ``fractions``, ``decimal``): no SQL, no psycopg, no ``pipeline_observatory`` domain code, no reference SQL. It reads
``web/public/data/*.json`` (the wrapped entity files and the manifest) and returns, for each result set that ``run_all.py`` also runs in SQL, the same rows (``<file>__<block>``
keys, same columns, same order) so that the two sides are compared cell by cell. Ratios are ``Fraction``s rounded once, half away from zero, to the places the SQL rounds to.
The rules are those of D-01..D-09 (see 00_definitions.sql); this file is a second, separately written statement of them, including the sample's own classification of raw rows
(``classify_sample``), written from the contract text and not from ``domain/pipeline_observatory/classify.py``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "web" / "public" / "data"
UTC = timezone.utc
MONEY = re.compile(r"-?[0-9]+(?:\.[0-9]{1,2})?", re.ASCII)
STAMP = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})", re.ASCII)
REQUIRED = ("record_id", "quantity", "unit_price", "amount", "event_ts")


def ts(s: str | None) -> datetime | None:
    return None if s is None else datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%d")


def secs(a: datetime, b: datetime) -> int:
    """Whole seconds from b to a, floored (what floor(extract(epoch ...)) does; every published instant is a whole second)."""
    return math.floor((a - b).total_seconds())


def rnd(x: F | None, places: int) -> Decimal | None:
    """Round half away from zero (what PostgreSQL's round(numeric) does) and keep the trailing zeros."""
    if x is None:
        return None
    scale = 10 ** places
    scaled = x * scale
    n = scaled.numerator * 2 + scaled.denominator * (1 if scaled >= 0 else -1)
    q = n // (2 * scaled.denominator) if scaled >= 0 else -((-n) // (2 * scaled.denominator))
    return Decimal(q).scaleb(-places).quantize(Decimal(1).scaleb(-places))


def share(n: int, d: int, places: int = 6) -> Decimal | None:
    return None if d == 0 else rnd(F(n, d), places)


def norm(v) -> str:
    """One text for a cell, whichever side produced it (None is the empty text; Decimals keep their places)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def normalised(rows: list[dict]) -> list[dict]:
    return [{k: norm(v) for k, v in r.items()} for r in rows]


def wrapped(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text())["rows"]


def dataset_hash() -> str:
    """The dataset hash recomputed from the sixteen entity files (sha256 over the canonical rows of each, in name order)."""
    h = hashlib.sha256()
    for name in sorted(p.stem for p in DATA.glob("*.json") if p.stem not in ("manifest", "injection-manifest")):
        h.update(json.dumps(wrapped(name), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode())
    return h.hexdigest()


def cadence_seconds(freq: str) -> int:
    if freq == "daily":
        return 86400
    m = re.fullmatch(r"every ([0-9]+) hours", freq)
    return int(m.group(1)) * 3600


class Ctx:
    def __init__(self) -> None:
        self.manifest = json.loads((DATA / "manifest.json").read_text())
        self.as_of = ts(self.manifest["config"]["as_of"])
        self.cutoff = ts(self.manifest["config"]["cutoff"])
        self.contracts = {r["source_id"]: r for r in wrapped("source_contracts")}
        self.batches = {r["batch_id"]: r for r in wrapped("ingestion_batches")}
        self.summaries = {r["batch_id"]: r for r in wrapped("batch_summaries")}
        self.checkpoints = wrapped("checkpoints")
        self.cp_by_batch = {c["batch_id"]: c for c in self.checkpoints}
        self.quarantine = wrapped("quarantine_records")
        self.raw = wrapped("raw_records")
        self.runs = sorted(wrapped("pipeline_runs"), key=lambda r: (r["started_at"], r["run_id"]))
        self.tasks = wrapped("task_runs")
        self.results = wrapped("quality_results")
        self.pubs = wrapped("publications")
        self.pub_by_run = {p["run_id"]: p for p in self.pubs}
        self.incidents = sorted(wrapped("incidents"), key=lambda i: i["incident_id"])
        self.expect = wrapped("source_expectations")
        self.fetch = sorted(wrapped("fetch_log"), key=lambda f: f["fetch_id"])
        self.totals = {t["run_id"]: t for t in wrapped("model_output_totals")}
        self.committed = {b for b, r in self.batches.items() if r["status"] == "committed"}
        self.gate = self.gate_results()
        self.run = self.run_table()
        self.backfills, self.refused = self.split_backfills()
        self.sample = self.classify_sample()

    # ---- runs, gates ---------------------------------------------------------------------------------------------------------------------------------
    def gate_results(self) -> dict[str, dict[str, dict]]:
        task_run = {t["task_run_id"]: t["run_id"] for t in self.tasks}
        latest: dict[tuple[str, str], dict] = {}
        for q in sorted(self.results, key=lambda q: q["quality_result_id"]):
            latest[(task_run[q["task_run_id"]], q["rule_name"])] = q                   # the latest result of a rule name in a run counts
        out: dict[str, dict[str, dict]] = defaultdict(dict)
        for (run, rule), q in latest.items():
            out[run][rule] = q
        return out

    def run_table(self) -> dict[str, dict]:
        by_run: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for t in self.tasks:
            by_run[t["run_id"]][t["task_name"]].append(t)
        out = {}
        for r in self.runs:
            g = self.gate.get(r["run_id"], {})
            crit = [q for q in g.values() if q["severity"] == "critical"]
            failed_crit = sorted(q["rule_name"] for q in crit if q["failure_count"] > 0)
            reached = len(g) > 0
            decision = "not_reached" if not reached else ("allowed" if crit and not failed_crit else "blocked")
            failed_tasks = sorted(n for n, ts_ in by_run[r["run_id"]].items() if max(ts_, key=lambda t: t["attempt"])["status"] == "failed")
            stage = "published" if r["status"] == "success" else ("blocked_at_gate" if reached else "failed_before_gate")
            kind = None
            if r["status"] == "failed":
                if reached:
                    kind = {"freshness_within_target": "freshness", "relationships_intact": "relationships", "reconciliation_residual_zero": "residual"}.get(failed_crit[0], failed_crit[0])
                else:
                    kind = ",".join({"quality_gate": "gate_infra"}.get(n, n) for n in failed_tasks)
            out[r["run_id"]] = {**r, "duration": secs(ts(r["finished_at"]), ts(r["started_at"])), "reached": reached, "decision": decision, "published": r["run_id"] in self.pub_by_run,
                                "stage": stage, "kind": kind, "failed_critical": failed_crit, "start": ts(r["started_at"])}
        return out

    def pointer_before(self, run: dict, inclusive: bool) -> str | None:
        best = None
        for r in self.runs:
            s = ts(r["started_at"])
            if (s <= run["start"] if inclusive else s < run["start"]) and r["run_id"] in self.pub_by_run:
                best = self.pub_by_run[r["run_id"]]["publication_id"]
        return best

    def split_backfills(self) -> tuple[list[dict], list[dict]]:
        """Accepted and refused requests: a request is refused when an EARLIER accepted request of its source intersects its half-open range and was still active (made no later
        than the request, not yet settled) when it was made (D-09 R8-12). Judged in backfill_id order."""
        accepted: list[dict] = []
        refused: list[dict] = []
        for r in sorted(wrapped("backfill_requests"), key=lambda r: r["backfill_id"]):
            s, e, at = ts(r["start_at"]), ts(r["end_at"]), ts(r["requested_at"])
            clash = [a for a in accepted if a["source_id"] == r["source_id"] and ts(a["start_at"]) < e and s < ts(a["end_at"])
                     and ts(a["requested_at"]) <= at and (a["settled_at"] is None or at < ts(a["settled_at"]))]
            (refused if clash else accepted).append(r)
        return accepted, refused

    # ---- the sample's own classification of the loaded raw rows (no key history beyond the sample) -----------------------------------------------------
    def classify_sample(self) -> dict[str, str]:
        rows_by_batch: dict[str, list[dict]] = defaultdict(list)
        for r in self.raw:
            rows_by_batch[r["batch_id"]].append(r)
        verdict: dict[str, str] = {}
        accepted: dict[str, set[str]] = defaultdict(set)
        deleted: dict[str, set[str]] = defaultdict(set)
        order = sorted((b for b in self.committed), key=lambda b: (self.batches[b]["source_id"], self.cp_by_batch[b]["version_number"] if b in self.cp_by_batch else 10 ** 9,
                                                                       self.batches[b]["started_at"], b))
        for bid in order:
            src = self.batches[bid]["source_id"]
            limit = min(ts(self.batches[bid]["started_at"]), self.cutoff)
            for r in sorted(rows_by_batch.get(bid, []), key=lambda r: r["raw_record_id"]):
                verdict[r["raw_record_id"]] = self.verdict(r, accepted[src], deleted[src], limit)
        return verdict

    def verdict(self, r: dict, accepted: set[str], deleted: set[str], limit: datetime) -> str:
        key, p = r.get("source_key"), r["payload_json"]
        op = p.get("op", "upsert") if isinstance(p, dict) else "upsert"
        if op == "delete":
            if key is not None and key in accepted and key not in deleted:
                deleted.add(key)
                return "deleted"
            return "duplicate" if key is not None and key in deleted else "quarantined"
        if op != "upsert":
            return "quarantined"
        if key is not None and key in accepted:                                               # the key check runs before the contract check
            return "duplicate"
        if not isinstance(p, dict) or key is None or any(p.get(k) is None for k in REQUIRED):
            return "quarantined"
        q = p["quantity"]
        if type(q) is not int or abs(q) > 2 ** 53 or not all(isinstance(p[k], str) and MONEY.fullmatch(p[k]) for k in ("unit_price", "amount")):
            return "quarantined"
        m = STAMP.fullmatch(p["event_ts"]) if isinstance(p["event_ts"], str) else None
        if not m:
            return "quarantined"
        try:
            ev = datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6]), tzinfo=UTC)
        except ValueError:
            return "quarantined"
        if m[8] != "Z":
            ev -= (1 if m[8][0] == "+" else -1) * timedelta(hours=int(m[8][1:3]), minutes=int(m[8][4:6]))
        if q < 0 or ev > limit:
            return "quarantined"
        accepted.add(key)
        return "accepted"


def results() -> dict[str, list[dict]]:
    c = Ctx()
    R: dict[str, list[dict]] = {}
    sources = sorted(c.contracts)
    summ_c = {b: s for b, s in c.summaries.items() if b in c.committed}

    # ---- 01 ingestion by source ----------------------------------------------------------------------------------------------------------------------
    def tot(rows: list[dict]) -> dict:
        t = {k: sum(r[k] for r in rows) for k in ("received", "accepted_unique", "duplicate", "quarantined", "deleted")}
        t["batches"] = len(rows)
        return t
    by_src = {s: tot([x for b, x in summ_c.items() if x["source_id"] == s]) for s in sources}
    R["01_ingestion_by_source__by_source"] = [{"source_id": s, "committed_batches": t["batches"], "received": t["received"], "accepted_unique": t["accepted_unique"], "duplicate": t["duplicate"],
                                              "quarantined": t["quarantined"], "deleted": t["deleted"], "rejection_rate": share(t["quarantined"], t["received"]),
                                              "duplicate_rate": share(t["duplicate"], t["received"])} for s, t in by_src.items()]
    o = tot(list(summ_c.values()))
    R["01_ingestion_by_source__overall"] = [{"committed_batches": o["batches"], "received": o["received"], "accepted_unique": o["accepted_unique"], "duplicate": o["duplicate"],
                                             "quarantined": o["quarantined"], "deleted": o["deleted"], "rejection_rate": share(o["quarantined"], o["received"]),
                                             "duplicate_rate": share(o["duplicate"], o["received"]),
                                             "unclassified": o["received"] - o["accepted_unique"] - o["duplicate"] - o["quarantined"] - o["deleted"]}]
    qc = [q for q in c.quarantine if c.batches[q["batch_id"]]["status"] == "committed"]
    R["01_ingestion_by_source__quarantine_distinct_keys"] = [{
        "source_id": s, "quarantine_rows": sum(1 for q in qc if c.batches[q["batch_id"]]["source_id"] == s),
        "distinct_keys": len({q["source_key"] for q in qc if c.batches[q["batch_id"]]["source_id"] == s and q["source_key"] is not None}),
        "rows_without_key": sum(1 for q in qc if c.batches[q["batch_id"]]["source_id"] == s and q["source_key"] is None)} for s in sources]
    reasons = sorted({q["reason_code"] for q in c.quarantine})
    R["01_ingestion_by_source__quarantine_by_reason"] = [{
        "reason_code": x, "in_committed_batches": sum(1 for q in c.quarantine if q["reason_code"] == x and c.batches[q["batch_id"]]["status"] == "committed"),
        "in_schema_quarantined_batch": sum(1 for q in c.quarantine if q["reason_code"] == x and c.batches[q["batch_id"]]["status"] == "quarantined"),
        "in_other_batches": sum(1 for q in c.quarantine if q["reason_code"] == x and c.batches[q["batch_id"]]["status"] not in ("committed", "quarantined")),
        "all_rows": sum(1 for q in c.quarantine if q["reason_code"] == x)} for x in reasons]
    sq = sorted((b for b in c.batches.values() if b["status"] == "quarantined" or c.summaries[b["batch_id"]]["kind"] == "schema_refetch"), key=lambda b: (b["started_at"], b["batch_id"]))
    R["01_ingestion_by_source__schema_quarantined"] = [{
        "batch_id": b["batch_id"], "source_id": b["source_id"], "status": b["status"], "started_at": b["started_at"], "source_cursor": b["source_cursor"], "kind": c.summaries[b["batch_id"]]["kind"],
        "written_rows": c.summaries[b["batch_id"]]["written_rows"], "schema_changed_rows": sum(1 for q in c.quarantine if q["batch_id"] == b["batch_id"] and q["reason_code"] == "SCHEMA_CHANGED"),
        "checkpoints": 1 if b["batch_id"] in c.cp_by_batch else 0, "contract_schema_version": c.contracts[b["source_id"]]["schema_version"]} for b in sq]
    groups = sorted({(c.summaries[b]["kind"], r["status"]) for b, r in c.batches.items()})
    kb = []
    for kind, status in groups:
        ids = [b for b, r in c.batches.items() if c.summaries[b]["kind"] == kind and r["status"] == status]
        kb.append({"kind": kind, "status": status, "batches": len(ids), "written_rows": sum(c.summaries[b]["written_rows"] for b in ids), "received": sum(c.summaries[b]["received"] for b in ids),
                   "accepted_unique": sum(c.summaries[b]["accepted_unique"] for b in ids), "duplicate": sum(c.summaries[b]["duplicate"] for b in ids),
                   "checkpoints": sum(1 for b in ids if b in c.cp_by_batch)})
    R["01_ingestion_by_source__by_batch_kind"] = kb
    cr = []
    for a in sorted((b for b in c.batches.values() if b["status"] == "aborted"), key=lambda b: b["batch_id"]):
        later = sorted((b for b in c.batches.values() if b["source_id"] == a["source_id"] and b["source_cursor"] == a["source_cursor"] and b["status"] == "committed"
                        and b["started_at"] > a["started_at"]), key=lambda b: (b["started_at"], b["batch_id"]))
        if not later:
            continue
        rp = later[0]
        prev = max(cp["version_number"] for cp in c.checkpoints if cp["source_id"] == a["source_id"] and c.batches[cp["batch_id"]]["started_at"] < a["started_at"])
        sa, sr = c.summaries[a["batch_id"]], c.summaries[rp["batch_id"]]
        v = c.cp_by_batch[rp["batch_id"]]["version_number"]
        cr.append({"aborted_batch": a["batch_id"], "source_id": a["source_id"], "aborted_rows": sa["written_rows"], "aborted_checkpoints": 1 if a["batch_id"] in c.cp_by_batch else 0,
                   "replay_batch": rp["batch_id"], "replay_received": sr["received"], "replay_accepted": sr["accepted_unique"], "replay_duplicate": sr["duplicate"],
                   "replay_quarantined": sr["quarantined"], "previous_version": prev, "replay_version": v, "version_step": v - prev,
                   "rows_classified_once": sr["accepted_unique"] + sr["duplicate"] + sr["quarantined"] == sa["written_rows"]})
    R["01_ingestion_by_source__crash_replay"] = cr

    # ---- 02 run funnel --------------------------------------------------------------------------------------------------------------------------------
    runs = list(c.run.values())
    R["02_run_funnel_by_failure_kind__funnel"] = [{
        "runs": len(runs), "reached_gate": sum(r["reached"] for r in runs), "allowed": sum(r["decision"] == "allowed" for r in runs), "blocked_at_gate": sum(r["decision"] == "blocked" for r in runs),
        "failed_before_gate": sum(r["stage"] == "failed_before_gate" for r in runs), "succeeded": sum(r["status"] == "success" for r in runs), "failed": sum(r["status"] == "failed" for r in runs),
        "published": sum(r["published"] for r in runs), "backfill_runs": sum(r["backfill_id"] is not None for r in runs)}]
    inc_by_run = {i["run_id"]: i for i in c.incidents}
    fk = defaultdict(list)
    for r in runs:
        if r["status"] == "failed":
            fk[(r["stage"], r["kind"])].append(r)
    R["02_run_funnel_by_failure_kind__by_failure_kind"] = [{
        "stage": st, "failure_kind": k, "runs": len(v), "incidents": sum(1 for r in v if r["run_id"] in inc_by_run), "mean_duration_minutes": rnd(F(sum(r["duration"] for r in v), len(v) * 60), 4),
        "first_run": min(r["run_id"] for r in v), "last_run": max(r["run_id"] for r in v)} for (st, k), v in sorted(fk.items())]
    gc = defaultdict(list)
    for g in c.gate.values():
        for q in g.values():
            gc[q["rule_name"]].append(q)
    R["02_run_funnel_by_failure_kind__gate_checks"] = [{
        "rule_name": n, "severity": v[0]["severity"], "gates": len(v), "failed": sum(q["failure_count"] > 0 for q in v), "failed_share": share(sum(q["failure_count"] > 0 for q in v), len(v)),
        "eligible_total": sum(q["eligible_count"] for q in v), "failure_total": sum(q["failure_count"] for q in v)} for n, v in sorted(gc.items(), key=lambda kv: (kv[1][0]["severity"], kv[0]))]
    R["02_run_funnel_by_failure_kind__durations"] = [{
        "status": st, "runs": len(v), "min_seconds": min(r["duration"] for r in v), "max_seconds": max(r["duration"] for r in v), "mean_minutes": rnd(F(sum(r["duration"] for r in v), len(v) * 60), 4)}
        for st, v in sorted({s: [r for r in runs if r["status"] == s] for s in {r["status"] for r in runs}}.items())]
    wk = defaultdict(list)
    for r in runs:
        d = r["start"].date()
        wk[d - timedelta(days=d.weekday())].append(r)
    R["02_run_funnel_by_failure_kind__failures_by_week"] = [{
        "week_start": w.isoformat(), "runs": len(v), "failed": sum(r["status"] == "failed" for r in v), "blocked_at_gate": sum(r["decision"] == "blocked" for r in v),
        "failed_before_gate": sum(r["stage"] == "failed_before_gate" for r in v)} for w, v in sorted(wk.items())]

    # ---- 03 task vs attempt ---------------------------------------------------------------------------------------------------------------------------
    tk: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in c.tasks:
        tk[(t["run_id"], t["task_name"])].append(t)
    info = {k: {"attempts": len(v), "ok": sum(t["status"] == "success" for t in v), "final": max(v, key=lambda t: t["attempt"])["status"]} for k, v in tk.items()}

    def rates(items: list[dict]) -> dict:
        n, ts_ = len(items), sum(i["final"] == "success" for i in items)
        a, ao = sum(i["attempts"] for i in items), sum(i["ok"] for i in items)
        return {"tasks": n, "tasks_successful": ts_, "task_success_rate": share(ts_, n), "attempts": a, "attempts_successful": ao, "attempt_success_rate": share(ao, a),
                "tasks_retried": sum(i["attempts"] > 1 for i in items)}
    allr = rates(list(info.values()))
    R["03_task_vs_attempt_success__overall"] = [{"tasks_terminal": allr["tasks"], "tasks_successful": allr["tasks_successful"], "task_success_rate": allr["task_success_rate"], "attempts": allr["attempts"],
                                                 "attempts_successful": allr["attempts_successful"], "attempt_success_rate": allr["attempt_success_rate"], "tasks_retried": allr["tasks_retried"],
                                                 "retried_then_succeeded": sum(i["attempts"] > 1 and i["final"] == "success" for i in info.values())}]
    names = sorted({k[1] for k in info})
    R["03_task_vs_attempt_success__by_task"] = [{"task_name": n, **rates([i for k, i in info.items() if k[1] == n])} for n in names]
    R["03_task_vs_attempt_success__retry_depth"] = [{
        "attempts": a, "tasks": sum(i["attempts"] == a for i in info.values()), "ended_success": sum(i["attempts"] == a and i["final"] == "success" for i in info.values()),
        "ended_failed": sum(i["attempts"] == a and i["final"] == "failed" for i in info.values())} for a in sorted({i["attempts"] for i in info.values()})]
    rl = []
    for st in sorted({r["status"] for r in runs}):
        ids = {r["run_id"] for r in runs if r["status"] == st}
        att = [t for t in c.tasks if t["run_id"] in ids]
        rl.append({"status": st, "runs": len(ids), "attempts": len(att), "attempts_successful": sum(t["status"] == "success" for t in att),
                   "attempt_success_rate": share(sum(t["status"] == "success" for t in att), len(att))})
    R["03_task_vs_attempt_success__run_level"] = rl

    # ---- 04 freshness vs ingestion age ----------------------------------------------------------------------------------------------------------------
    age = {}
    for s in sources:
        cps = [cp for cp in c.checkpoints if cp["source_id"] == s and cp["batch_id"] in c.committed]
        last = max(ts(cp["committed_at"]) for cp in cps)
        age[s] = {"last": last, "seconds": secs(c.as_of, last), "version": max(cp["version_number"] for cp in cps), "n": len(cps)}
    R["04_freshness_vs_ingestion_age__ingestion_age"] = [{"source_id": s, "last_successful_ingestion_at": iso(a["last"]), "ingestion_age_seconds": a["seconds"],
                                                           "ingestion_age_minutes": rnd(F(a["seconds"], 60), 4), "checkpoint_version": a["version"], "committed_batches": a["n"]} for s, a in age.items()]
    rec = c.manifest["stats"]["freshness_at_as_of"]
    fr = {}
    for s in sources:
        ev = ts(rec[s]["latest_accepted_event_at"])
        fr[s] = {"event": ev, "seconds": secs(c.as_of, ev)}
    R["04_freshness_vs_ingestion_age__freshness_vs_age"] = [{
        "source_id": s, "latest_accepted_event_at": iso(fr[s]["event"]), "freshness_seconds": fr[s]["seconds"], "freshness_minutes": rnd(F(fr[s]["seconds"], 60), 4),
        "recorded_freshness_seconds": rec[s]["freshness_seconds"], "ingestion_age_seconds": age[s]["seconds"], "recorded_ingestion_age_seconds": rec[s]["ingestion_age_seconds"],
        "gap_seconds": fr[s]["seconds"] - age[s]["seconds"], "freshness_target_seconds": c.contracts[s]["freshness_target_seconds"],
        "over_target": fr[s]["seconds"] > c.contracts[s]["freshness_target_seconds"], "cadence_seconds": cadence_seconds(c.contracts[s]["expected_frequency"]),
        "silent": fr[s]["seconds"] > 2 * cadence_seconds(c.contracts[s]["expected_frequency"])} for s in sources]
    silent = [s for s in sources if fr[s]["seconds"] > 2 * cadence_seconds(c.contracts[s]["expected_frequency"])]
    since = {s: datetime(fr[s]["event"].year, fr[s]["event"].month, fr[s]["event"].day, tzinfo=UTC) + timedelta(days=1) for s in silent}
    ss = []
    for s in silent:
        sb = [b for b in c.batches.values() if b["source_id"] == s and b["status"] == "committed" and ts(b["started_at"]) >= since[s]]
        since_runs = [r for r in runs if r["start"] >= since[s]]
        ss.append({"source_id": s, "silent_since": iso(since[s]), "runs_since": len(since_runs), "runs_succeeded": sum(r["status"] == "success" for r in since_runs),
                   "runs_allowed_by_the_gate": sum(r["decision"] == "allowed" for r in since_runs),
                   "freshness_checks_passed": sum(1 for r in since_runs if r["run_id"] in c.gate and "freshness_within_target" in c.gate[r["run_id"]] and c.gate[r["run_id"]]["freshness_within_target"]["failure_count"] == 0),
                   "committed_batches_since": len(sb), "batches_with_no_accepted_record": sum(c.summaries[b["batch_id"]]["accepted_unique"] == 0 for b in sb),
                   "accepted_since": sum(c.summaries[b["batch_id"]]["accepted_unique"] for b in sb), "duplicates_since": sum(c.summaries[b["batch_id"]]["duplicate"] for b in sb)})
    R["04_freshness_vs_ingestion_age__silent_source"] = ss
    R["04_freshness_vs_ingestion_age__silent_partitions"] = [{"source_id": e["source_id"], "partition": e["partition"], "expected_records": e["expected_records"]}
                                                              for e in sorted(c.expect, key=lambda e: (e["source_id"], e["partition"])) if e["source_id"] in silent and e["partition"] >= day(since[e["source_id"]])]
    comp = []
    for s in sources:
        ex = [e for e in c.expect if e["source_id"] == s]
        acc = sum(x["accepted_unique"] for x in summ_c.values() if x["source_id"] == s)
        comp.append({"source_id": s, "partitions": len(ex), "expected_records": sum(e["expected_records"] for e in ex), "accepted_records": acc,
                     "completeness": share(acc, sum(e["expected_records"] for e in ex))})
    R["04_freshness_vs_ingestion_age__completeness"] = comp

    # ---- 05 pointer -----------------------------------------------------------------------------------------------------------------------------------
    latest_pub = max(c.pubs, key=lambda p: (p["published_at"], p["publication_id"]))
    pointer_run = max((r for r in runs if r["published"]), key=lambda r: r["start"])
    R["05_publication_pointer_and_blocked_runs__summary"] = [{
        "runs": len(runs), "publications": len(c.pubs), "runs_that_moved_the_pointer": sum(r["published"] for r in runs), "runs_that_left_it": sum(not r["published"] for r in runs),
        "pointer": c.pub_by_run[pointer_run["run_id"]]["publication_id"], "pointer_run": pointer_run["run_id"], "latest_publication": latest_pub["publication_id"],
        "publications_of_failed_or_blocked_runs": sum(1 for p in c.pubs if c.run[p["run_id"]]["status"] != "success" or c.run[p["run_id"]]["decision"] != "allowed"),
        "first_published_at": min(p["published_at"] for p in c.pubs), "last_published_at": max(p["published_at"] for p in c.pubs)}]
    um = []
    for r in runs:
        if r["published"]:
            continue
        um.append({"run_id": r["run_id"], "started_at": r["started_at"], "stage": r["stage"], "failure_kind": r["kind"], "failed_critical_check": (r["failed_critical"] or [None])[0],
                   "pointer_before": c.pointer_before(r, False), "pointer_after": c.pointer_before(r, True), "pointer_unchanged": c.pointer_before(r, False) == c.pointer_before(r, True),
                   "publication_exists": False, "incident_id": inc_by_run[r["run_id"]]["incident_id"] if r["run_id"] in inc_by_run else None})
    R["05_publication_pointer_and_blocked_runs__unmoved_runs"] = um
    rel = [r for r in runs if r["kind"] == "relationships"]
    d2 = rel[1]
    R["05_publication_pointer_and_blocked_runs__designed_blocked_run"] = [{
        "run_id": d2["run_id"], "failure_kind": d2["kind"], "relationships_eligible": c.gate[d2["run_id"]]["relationships_intact"]["eligible_count"],
        "relationships_failed": c.gate[d2["run_id"]]["relationships_intact"]["failure_count"], "gate_decision": d2["decision"], "pointer_before": c.pointer_before(d2, False),
        "pointer_after": c.pointer_before(d2, True), "publication_exists": d2["published"], "incident_id": inc_by_run[d2["run_id"]]["incident_id"],
        "recovery_run_id": inc_by_run[d2["run_id"]]["recovery_run_id"], "detected_at": inc_by_run[d2["run_id"]]["opened_at"]}]
    stale = []
    for r in runs:
        if r["published"]:
            continue
        cur = [p for p in c.pubs if c.run[p["run_id"]]["start"] < r["start"]]
        nxt = [p for p in c.pubs if c.run[p["run_id"]]["start"] > r["start"]]
        if cur and nxt:
            a = max(cur, key=lambda p: c.run[p["run_id"]]["start"])
            b = min(nxt, key=lambda p: c.run[p["run_id"]]["start"])
            stale.append(secs(ts(b["published_at"]), ts(a["published_at"])))
    R["05_publication_pointer_and_blocked_runs__pointer_staleness"] = [{"unmoved_runs": len(stale), "min_seconds": min(stale), "max_seconds": max(stale), "mean_minutes": rnd(F(sum(stale), len(stale) * 60), 4)}]

    # ---- 06 incidents ---------------------------------------------------------------------------------------------------------------------------------
    def verified(i: dict) -> tuple[str | None, datetime | None]:
        for r in runs:
            g = c.gate.get(r["run_id"], {})
            if (r["start"] >= ts(i["opened_at"]) and r["status"] == "success" and r["decision"] == "allowed" and r["published"]
                    and "reconciliation_residual_zero" in g and g["reconciliation_residual_zero"]["failure_count"] == 0):
                return r["run_id"], ts(c.pub_by_run[r["run_id"]]["published_at"])
        return None, None
    inc = []
    for i in c.incidents:
        vr, va = verified(i)
        secs_ = secs(va, ts(i["opened_at"]))
        inc.append({"incident_id": i["incident_id"], "run_id": i["run_id"], "failure_kind": c.run[i["run_id"]]["kind"], "severity": i["severity"], "status": i["status"], "detected_at": i["opened_at"],
                    "recovery_run_id": i["recovery_run_id"], "first_verified_run": vr, "recovery_is_first_verified": i["recovery_run_id"] == vr, "verified_at": iso(va),
                    "closed_at_is_verified_instant": i["closed_at"] == iso(va), "recovery_seconds": secs_, "recovery_minutes": rnd(F(secs_, 60), 4)})
    R["06_incidents_and_verified_recovery__incidents"] = inc
    s_ = [x["recovery_seconds"] for x in inc]
    R["06_incidents_and_verified_recovery__summary"] = [{
        "incidents": len(inc), "open": sum(x["status"] == "open" for x in inc), "closed": sum(x["status"] == "closed" for x in inc),
        "verified": sum(x["status"] == "closed" and x["recovery_is_first_verified"] for x in inc),
        "closures_consistent": sum(x["closed_at_is_verified_instant"] and x["recovery_is_first_verified"] for x in inc), "mean_recovery_minutes": rnd(F(sum(s_), len(s_) * 60), 4),
        "min_recovery_minutes": rnd(F(min(s_), 60), 4), "max_recovery_minutes": rnd(F(max(s_), 60), 4)}]
    bk = defaultdict(list)
    for x in inc:
        bk[(x["failure_kind"], c.run[x["run_id"]]["stage"])].append(x["recovery_seconds"])
    R["06_incidents_and_verified_recovery__by_failure_kind"] = [{
        "failure_kind": k, "stage": st, "incidents": len(v), "mean_recovery_minutes": rnd(F(sum(v), len(v) * 60), 4), "min_recovery_minutes": rnd(F(min(v), 60), 4),
        "max_recovery_minutes": rnd(F(max(v), 60), 4)} for (k, st), v in sorted(bk.items())]
    rc = []
    for x in c.manifest["designed_relationships"]:
        if x["id"] == "DR-05":
            for cand in sorted(x["realised"]["candidates_with_nonzero_residual"], key=lambda z: z["run_id"]):
                tot_ = Decimal(c.totals[cand["run_id"]]["total_amount"])
                rc.append({"run_id": cand["run_id"], "day": cand["day"], "source_total": Decimal(cand["source_total"]), "exclusions_total": Decimal(cand["exclusions_total"]),
                           "stored_candidate_total": tot_, "recorded_published_total": Decimal(cand["published_total"]),
                           "residual": Decimal(cand["source_total"]) - tot_ - Decimal(cand["exclusions_total"]), "recorded_residual": Decimal(cand["residual"]),
                           "stage": c.run[cand["run_id"]]["stage"], "failure_kind": c.run[cand["run_id"]]["kind"],
                           "incident_id": inc_by_run[cand["run_id"]]["incident_id"] if cand["run_id"] in inc_by_run else None, "publications_of_the_run": int(cand["run_id"] in c.pub_by_run)})
    R["06_incidents_and_verified_recovery__residual_candidate"] = rc

    # ---- 07 backfills ---------------------------------------------------------------------------------------------------------------------------------
    def parts(r: dict) -> tuple[int, int]:
        return len(r["partitions"]), sum(1 for p in r["partitions"] if p["verified"])
    req = []
    for r in sorted(c.backfills + c.refused, key=lambda r: r["backfill_id"]):
        accepted = r in c.backfills
        n, v = parts(r)
        run = next((x["run_id"] for x in runs if x["backfill_id"] == r["backfill_id"]), None) if accepted else None
        req.append({"backfill_id": r["backfill_id"], "source_id": r["source_id"], "outcome": "accepted" if accepted else "refused", "start_day": day(ts(r["start_at"])), "end_day": day(ts(r["end_at"])),
                    "requested_partitions": n, "verified_partitions": v if accepted else 0, "coverage": share(v, n) if accepted else None, "status": r["status"], "requested_at": r["requested_at"],
                    "settled_at": r["settled_at"], "run_id": run})
    R["07_backfill_coverage_and_refused_overlaps__requests"] = req
    rp = sum(parts(r)[0] for r in c.backfills)
    vp = sum(parts(r)[1] for r in c.backfills)
    R["07_backfill_coverage_and_refused_overlaps__coverage_summary"] = [{
        "accepted_requests": len(c.backfills), "requested_partitions": rp, "verified_partitions": vp, "coverage": share(vp, rp), "refused_requests": len(c.refused),
        "refused_partitions": sum(parts(r)[0] for r in c.refused), "requests_complete": sum(r["status"] == "complete" for r in c.backfills),
        "requests_partial": sum(r["status"] == "partial" for r in c.backfills), "backfill_runs": sum(r["backfill_id"] is not None for r in runs)}]
    bs = []
    for s in sorted({r["source_id"] for r in c.backfills}):
        rs = [r for r in c.backfills if r["source_id"] == s]
        n, v = sum(parts(r)[0] for r in rs), sum(parts(r)[1] for r in rs)
        bs.append({"source_id": s, "accepted_requests": len(rs), "requested_partitions": n, "verified_partitions": v, "coverage": share(v, n),
                   "refused_requests": sum(1 for r in c.refused if r["source_id"] == s)})
    R["07_backfill_coverage_and_refused_overlaps__by_source"] = bs
    R["07_backfill_coverage_and_refused_overlaps__unverified_partitions"] = [
        {"backfill_id": r["backfill_id"], "source_id": r["source_id"], "partition": p["partition"], "status": r["status"]}
        for r in sorted(c.backfills, key=lambda r: r["backfill_id"]) for p in sorted(r["partitions"], key=lambda p: p["partition"]) if not p["verified"]]
    ro = []
    for r in sorted(c.refused, key=lambda r: r["backfill_id"]):
        s, e, at = ts(r["start_at"]), ts(r["end_at"]), ts(r["requested_at"])
        v = next(b for b in sorted(c.backfills, key=lambda b: b["backfill_id"]) if b["source_id"] == r["source_id"] and ts(b["start_at"]) < e and s < ts(b["end_at"])
                 and ts(b["requested_at"]) <= at and (b["settled_at"] is None or at < ts(b["settled_at"])))
        shared = (min(e, ts(v["end_at"])) - max(s, ts(v["start_at"]))).days
        ro.append({"refused_request": r["backfill_id"], "source_id": r["source_id"], "start_day": day(s), "end_day": day(e), "overlapped_request": v["backfill_id"],
                   "overlapped_start_day": day(ts(v["start_at"])), "overlapped_end_day": day(ts(v["end_at"])), "shared_partitions": shared,
                   "seconds_before_the_overlapped_request_settled": secs(ts(v["settled_at"]), at), "overlapped_final_status": v["status"], "reason_code": "BACKFILL_OVERLAP"})
    R["07_backfill_coverage_and_refused_overlaps__refused_overlaps"] = ro
    ov = tc = pairs = 0
    for a in c.backfills:
        for b in c.backfills:
            if a["source_id"] == b["source_id"] and a["backfill_id"] < b["backfill_id"]:
                pairs += 1
                ov += ts(a["start_at"]) < ts(b["end_at"]) and ts(b["start_at"]) < ts(a["end_at"])
                tc += a["end_at"] == b["start_at"] or b["end_at"] == a["start_at"]
    R["07_backfill_coverage_and_refused_overlaps__accepted_pairs"] = [{"overlapping_pairs": ov, "touching_pairs": tc, "pairs_of_one_source": pairs}]

    # ---- 08 fetch log ---------------------------------------------------------------------------------------------------------------------------------
    fl = c.fetch
    key = lambda f: (f["fetched_at"], f["fetch_id"])                                      # ISO instants of one format sort as instants
    R["08_fetch_log_retry_after__statuses"] = [{
        "status": st, "fetches": sum(f["status"] == st for f in fl), "sessions": len({f["session_id"] for f in fl if f["status"] == st}), "sources": len({f["source_id"] for f in fl if f["status"] == st}),
        "with_a_batch": sum(1 for f in fl if f["status"] == st and f["batch_id"] is not None)} for st in sorted({f["status"] for f in fl})]
    R["08_fetch_log_retry_after__by_source"] = [{
        "source_id": s, "fetches": sum(f["source_id"] == s for f in fl), **{k: sum(f["source_id"] == s and f["status"] == k for f in fl) for k in ("ok", "rate_limited", "refetch", "cursor_loop")}}
        for s in sorted({f["source_id"] for f in fl})]
    retries = []
    for f in fl:
        if f["status"] != "rate_limited":
            continue
        later = sorted((x for x in fl if x["source_id"] == f["source_id"] and x["session_id"] == f["session_id"] and x["cursor_value"] == f["cursor_value"] and key(x) > key(f)), key=key)
        n = later[0] if later else None
        w = secs(ts(n["fetched_at"]), ts(f["fetched_at"])) if n else None
        retries.append({"fetch_id": f["fetch_id"], "source_id": f["source_id"], "session_id": f["session_id"], "cursor_value": f["cursor_value"], "retry_after_seconds": f["retry_after_seconds"],
                        "rate_limited_at": f["fetched_at"], "retried_at": n["fetched_at"] if n else None, "waited_seconds": w, "slack_seconds": w - f["retry_after_seconds"] if n else None,
                        "honoured": ts(n["fetched_at"]) >= ts(f["fetched_at"]) + timedelta(seconds=f["retry_after_seconds"]) if n else None, "retry_status": n["status"] if n else None})
    R["08_fetch_log_retry_after__retries"] = retries
    done = [r for r in retries if r["retried_at"] is not None]
    R["08_fetch_log_retry_after__retry_summary"] = [{
        "rate_limited_responses": len(retries), "retries": len(done), "retries_honouring_retry_after": sum(r["honoured"] for r in done), "retries_too_soon": sum(not r["honoured"] for r in done),
        "min_slack_seconds": min(r["slack_seconds"] for r in done), "max_slack_seconds": max(r["slack_seconds"] for r in done), "sessions_rate_limited": len({r["session_id"] for r in retries}),
        "sources_rate_limited": len({r["source_id"] for r in retries}), "source_id": min(r["source_id"] for r in retries), "retries_rate_limited_again": sum(r["retry_status"] == "rate_limited" for r in done)}]
    R["08_fetch_log_retry_after__retry_by_hint"] = [{
        "retry_after_seconds": h, "responses": sum(r["retry_after_seconds"] == h for r in retries), "min_slack_seconds": min(r["slack_seconds"] for r in done if r["retry_after_seconds"] == h),
        "max_slack_seconds": max(r["slack_seconds"] for r in done if r["retry_after_seconds"] == h), "honoured": sum(r["honoured"] for r in done if r["retry_after_seconds"] == h)}
        for h in sorted({r["retry_after_seconds"] for r in retries})]
    kind = lambda f: c.summaries[f["batch_id"]]["kind"] if f["batch_id"] is not None else "no batch"
    rl_ = defaultdict(list)
    for f in fl:
        if f["status"] in ("refetch", "cursor_loop"):
            rl_[(f["status"], kind(f))].append(f)
    R["08_fetch_log_retry_after__refetch_vs_loop"] = [{"status": st, "batch_kind": k, "fetches": len(v), "pointing_at_themselves": sum(f["next_cursor"] == f["cursor_value"] for f in v)} for (st, k), v in sorted(rl_.items())]

    def earlier(f: dict, same_session: bool, pred) -> bool:
        return any(e["source_id"] == f["source_id"] and (e["session_id"] == f["session_id"]) == same_session and e["status"] in ("ok", "refetch") and key(e) < key(f) and pred(e, f) for e in fl)
    rc_ = []
    for st in sorted({f["status"] for f in fl}):
        v = [f for f in fl if f["status"] == st]
        served = lambda f: earlier(f, False, lambda e, f: e["cursor_value"] == f["cursor_value"])
        rc_.append({"status": st, "fetches": len(v), "cursor_served_before_by_another_session": sum(served(f) for f in v), "pointing_at_themselves": sum(f["next_cursor"] == f["cursor_value"] for f in v),
                    "refetch_conditions_met": sum(f["next_cursor"] == f["cursor_value"] or served(f) for f in v),
                    "repeats_inside_its_session": sum(earlier(f, True, lambda e, f: e["cursor_value"] == f["cursor_value"] or e["cursor_value"] == f["next_cursor"] or e["next_cursor"] == f["next_cursor"]) for f in v)})
    R["08_fetch_log_retry_after__refetch_check"] = rc_
    cl = []
    for l in sorted((f for f in fl if f["status"] == "cursor_loop"), key=lambda f: f["fetch_id"]):
        for p in sorted((f for f in fl if f["source_id"] == l["source_id"] and f["session_id"] == l["session_id"] and f["cursor_value"] == l["next_cursor"] and f["status"] == "ok"), key=lambda f: f["fetch_id"]):
            cl.append({"loop_fetch": l["fetch_id"], "source_id": l["source_id"], "session_id": l["session_id"], "looping_cursor": l["cursor_value"], "points_back_to": l["next_cursor"],
                       "first_page_fetch": p["fetch_id"], "first_page_cursor": p["cursor_value"], "first_page_next": p["next_cursor"], "first_page_at": p["fetched_at"], "loop_detected_at": l["fetched_at"],
                       "no_batch_created": l["batch_id"] is None, "rows_in_the_session": sum(1 for x in fl if x["session_id"] == l["session_id"])})
    R["08_fetch_log_retry_after__cursor_loop"] = cl

    # ---- 10 sample scope ------------------------------------------------------------------------------------------------------------------------------
    rows_by_src: dict[str, list[dict]] = defaultdict(list)
    for r in c.raw:
        rows_by_src[c.batches[r["batch_id"]]["source_id"]].append(r)
    sc = []
    for s in sources:
        bs_ = [x for x in c.summaries.values() if x["source_id"] == s]
        w = sum(x["written_rows"] for x in bs_)
        sc.append({"source_id": s, "batches": len(bs_), "sampled_batches": sum(x["sampled"] for x in bs_), "sampled_batches_with_rows": sum(x["sampled"] and x["written_rows"] > 0 for x in bs_),
                   "world_rows": w, "sample_rows": len(rows_by_src[s]), "sample_share": share(len(rows_by_src[s]), w)})
    R["10_sample_scope_reconciliation__scope_rows"] = sc
    allw = sum(x["written_rows"] for x in c.summaries.values())
    R["10_sample_scope_reconciliation__scope_total"] = [{
        "batches": len(c.summaries), "sampled_batches": sum(x["sampled"] for x in c.summaries.values()), "sampled_batches_with_rows": sum(x["sampled"] and x["written_rows"] > 0 for x in c.summaries.values()),
        "world_rows": allw, "sample_rows": len(c.raw), "sample_share": share(len(c.raw), allw), "sample_rows_in_uncounted_batches": sum(1 for r in c.raw if c.batches[r["batch_id"]]["status"] != "committed")}]
    ccls = []
    for s in sources:
        sm = [x for b, x in summ_c.items() if x["source_id"] == s and x["sampled"]]
        sr = [c.sample[r["raw_record_id"]] for r in rows_by_src[s] if c.batches[r["batch_id"]]["status"] == "committed"]
        ccls.append({"source_id": s, "received": sum(x["received"] for x in sm), "world_accepted": sum(x["accepted_unique"] for x in sm), "world_duplicate": sum(x["duplicate"] for x in sm),
                     "world_quarantined": sum(x["quarantined"] for x in sm), "world_deleted": sum(x["deleted"] for x in sm), "sample_accepted": sr.count("accepted"),
                     "sample_duplicate": sr.count("duplicate"), "sample_quarantined": sr.count("quarantined"), "sample_deleted": sr.count("deleted")})
    R["10_sample_scope_reconciliation__classes_by_source"] = ccls
    allsum = list(summ_c.values())
    smp = [x for x in allsum if x["sampled"]]
    sv = [c.sample[r["raw_record_id"]] for r in c.raw if c.batches[r["batch_id"]]["status"] == "committed"]

    def scope_row(label: str, rec_, acc, dup, q) -> dict:
        return {"scope": label, "received": rec_, "accepted_unique": acc, "duplicate": dup, "quarantined": q, "rejection_rate": share(q, rec_), "duplicate_rate": share(dup, rec_)}
    R["10_sample_scope_reconciliation__rates_by_scope"] = [
        scope_row("complete world, 1,302 committed batches", sum(x["received"] for x in allsum), sum(x["accepted_unique"] for x in allsum), sum(x["duplicate"] for x in allsum), sum(x["quarantined"] for x in allsum)),
        scope_row("the sampled committed batches, classified with the full key history", sum(x["received"] for x in smp), sum(x["accepted_unique"] for x in smp), sum(x["duplicate"] for x in smp),
                  sum(x["quarantined"] for x in smp)),
        scope_row("the 2,000-row sample, classified from the loaded rows only", len(sv), sv.count("accepted"), sv.count("duplicate"), sv.count("quarantined"))]
    sb = lambda q: c.summaries[q["batch_id"]]["sampled"]
    R["10_sample_scope_reconciliation__quarantine_rows"] = [{
        "quarantine_rows": len(c.quarantine), "in_sampled_batches": sum(sb(q) for q in c.quarantine), "in_unsampled_batches": sum(not sb(q) for q in c.quarantine),
        "unsampled_in_committed_batches": sum(not sb(q) and c.batches[q["batch_id"]]["status"] == "committed" for q in c.quarantine),
        "in_the_schema_quarantined_batch": sum(c.batches[q["batch_id"]]["status"] == "quarantined" for q in c.quarantine)}]
    inc_ = [(len(p["included_batch_ids"]), sum(1 for b in p["included_batch_ids"] if c.summaries[b]["sampled"] and c.summaries[b]["written_rows"] > 0)) for p in c.pubs]
    R["10_sample_scope_reconciliation__publications"] = [{"publications": len(c.pubs), "verifiable_from_the_sample": sum(n == k for n, k in inc_),
                                                           "partly_in_the_sample": sum(k > 0 and n > k for n, k in inc_), "none_in_the_sample": sum(k == 0 for n, k in inc_)}]
    fs = []
    for s in sources:
        # accepted_records holds every ACCEPTED key, also those a later delete event removed: a row counts when its verdict is accepted
        evs = [ts(r["payload_json"]["event_ts"]) for r in rows_by_src[s] if c.sample.get(r["raw_record_id"]) == "accepted"]
        fs.append({"source_id": s, "sample_latest_accepted_event_at": iso(max(evs)), "sample_freshness_seconds": secs(c.as_of, max(evs)), "recorded_freshness_seconds": rec[s]["freshness_seconds"]})
    R["10_sample_scope_reconciliation__freshness_on_the_sample"] = fs
    pm = c.manifest["config"]["processing_measurement"]
    wacc = c.summaries[pm["batch_id"]]["accepted_unique"]
    sacc = sum(1 for r in c.raw if r["batch_id"] == pm["batch_id"] and c.sample.get(r["raw_record_id"]) == "accepted")
    secs_ = Decimal(pm["measured_seconds"])
    R["10_sample_scope_reconciliation__processing_batch"] = [{
        "batch_id": pm["batch_id"], "measured_seconds": secs_, "cache_state": pm["cache_state"], "received": c.summaries[pm["batch_id"]]["received"], "world_accepted": wacc, "sample_accepted": sacc,
        "world_records_per_second": rnd(F(wacc) / F(secs_), 6), "sample_records_per_second": rnd(F(sacc) / F(secs_), 6)}]
    return R


if __name__ == "__main__":
    out = results()
    print(json.dumps({k: len(v) for k, v in out.items()}, indent=1))
