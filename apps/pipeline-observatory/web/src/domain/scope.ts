// Narrowing the accepted rows for a read: a half-open window [from, to), a cutoff and one source (the API's GET /metrics).
import type { Row } from "./contract";
import { dayPartitions, parseTs } from "./time";

export type Acc = Record<string, Row[]>;
const opt = (x: unknown): bigint | null => (x === null || x === undefined ? null : parseTs(x));

/** Facts known at `cutoff` (an instant at or after the cutoff is not yet known), inside [start, end) on the primary instant of each entity
 * (batches and runs: started_at; publications: published_at; incidents: opened_at; backfills: start_at), for one source. Children follow
 * their parents; a batch committed after the cutoff is dropped with its rows. */
export function restrict(acc: Acc, sourceId: string | null = null, start: unknown = null, end: unknown = null, cutoff: unknown = null): Acc {
  const s = opt(start), e = opt(end), c = opt(cutoff);
  const inside = (t: unknown): boolean => { const d = parseTs(t); return (s === null || d >= s) && (e === null || d < e) && (c === null || d < c); };
  const cps = new Map<string, Row>(acc["checkpoints"]!.map((x) => [x["batch_id"], x]));
  const batches = acc["ingestion_batches"]!.filter((b) => (sourceId === null || b["source_id"] === sourceId) && inside(b["started_at"])
    && (c === null || !cps.has(b["batch_id"]) || parseTs(cps.get(b["batch_id"])!["committed_at"]) < c));
  const bids = new Set<string>(batches.map((b) => b["batch_id"]));
  const runs = acc["pipeline_runs"]!.filter((r) => inside(r["started_at"]));
  const rids = new Set<string>(runs.map((r) => r["run_id"]));
  const tasks = acc["task_runs"]!.filter((t) => rids.has(t["run_id"]));
  const tids = new Set<string>(tasks.map((t) => t["task_run_id"]));
  return { ...acc,
    source_contracts: acc["source_contracts"]!.filter((x) => sourceId === null || x["source_id"] === sourceId),
    ingestion_batches: batches,
    raw_records: acc["raw_records"]!.filter((x) => bids.has(x["batch_id"])),
    quarantine_records: acc["quarantine_records"]!.filter((x) => bids.has(x["batch_id"])),
    checkpoints: acc["checkpoints"]!.filter((x) => bids.has(x["batch_id"])),
    pipeline_runs: runs, task_runs: tasks,
    quality_results: acc["quality_results"]!.filter((x) => tids.has(x["task_run_id"])),
    publications: acc["publications"]!.filter((p) => rids.has(p["run_id"]) && inside(p["published_at"]) && (sourceId === null || (p["source_ids"] as string[]).includes(sourceId))),
    incidents: acc["incidents"]!.filter((i) => inside(i["opened_at"])),
    backfill_requests: acc["backfill_requests"]!.filter((b) => (sourceId === null || b["source_id"] === sourceId) && inside(b["start_at"])) };
}
export function restrictExpectations(expectations: Row[], sourceId: string | null, start: unknown, end: unknown, cutoff: unknown): Row[] {
  const s = opt(start), e = opt(end), c = opt(cutoff);
  return expectations.filter((x) => {
    if (sourceId !== null && x["source_id"] !== sourceId) return false;
    const day = parseTs(`${dayPartitions(`${x["partition"]}T00:00:00Z`, `${x["partition"]}T23:59:59Z`)[0]}T00:00:00Z`);
    return (s === null || day >= s) && (e === null || day < e) && (c === null || day < c);
  });
}
