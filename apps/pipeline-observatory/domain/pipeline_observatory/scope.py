"""Narrowing the accepted rows for a read: a half-open window ``[from, to)``, a ``cutoff`` and one source (GET /metrics)."""
from __future__ import annotations

from typing import Any

from .timeutil import day_partitions, parse_ts

Row = dict[str, Any]


def restrict(acc: dict[str, list[Row]], source_id: str | None = None, start: Any = None, end: Any = None, cutoff: Any = None) -> dict[str, list[Row]]:
    """Facts known at ``cutoff`` (an instant at or after the cutoff is not yet known), inside ``[start, end)`` on the primary instant of each
    entity (batches and runs: started_at; publications: published_at; incidents: opened_at; backfills: start_at; expectations: the partition
    day), for one source. Children follow their parents; a batch committed after the cutoff is dropped with its rows."""
    s, e, c = (parse_ts(x) if x is not None else None for x in (start, end, cutoff))

    def inside(t: Any) -> bool:
        d = parse_ts(t)
        return (s is None or d >= s) and (e is None or d < e) and (c is None or d < c)

    cps = {x["batch_id"]: x for x in acc["checkpoints"]}
    batches = [b for b in acc["ingestion_batches"] if (source_id is None or b["source_id"] == source_id) and inside(b["started_at"])
               and (c is None or b["batch_id"] not in cps or parse_ts(cps[b["batch_id"]]["committed_at"]) < c)]
    bids = {b["batch_id"] for b in batches}
    runs = [r for r in acc["pipeline_runs"] if inside(r["started_at"])]
    rids = {r["run_id"] for r in runs}
    tasks = [t for t in acc["task_runs"] if t["run_id"] in rids]
    tids = {t["task_run_id"] for t in tasks}
    out = dict(acc)
    out.update({
        "source_contracts": [x for x in acc["source_contracts"] if source_id is None or x["source_id"] == source_id],
        "ingestion_batches": batches,
        "raw_records": [x for x in acc["raw_records"] if x["batch_id"] in bids],
        "quarantine_records": [x for x in acc["quarantine_records"] if x["batch_id"] in bids],
        "checkpoints": [x for x in acc["checkpoints"] if x["batch_id"] in bids],
        "pipeline_runs": runs, "task_runs": tasks,
        "quality_results": [x for x in acc["quality_results"] if x["task_run_id"] in tids],
        "publications": [p for p in acc["publications"] if p["run_id"] in rids and inside(p["published_at"])
                         and (source_id is None or source_id in p["source_ids"])],
        "incidents": [i for i in acc["incidents"] if inside(i["opened_at"])],
        "backfill_requests": [b for b in acc["backfill_requests"] if (source_id is None or b["source_id"] == source_id) and inside(b["start_at"])]})
    return out


def restrict_expectations(expectations: list[Row], source_id: str | None, start: Any, end: Any, cutoff: Any) -> list[Row]:
    s, e, c = (parse_ts(x) if x is not None else None for x in (start, end, cutoff))
    out = []
    for x in expectations:
        if source_id is not None and x["source_id"] != source_id:
            continue
        day = parse_ts(day_partitions(f"{x['partition']}T00:00:00Z", f"{x['partition']}T23:59:59Z")[0] + "T00:00:00Z")
        if (s is None or day >= s) and (e is None or day < e) and (c is None or day < c):
            out.append(x)
    return out
