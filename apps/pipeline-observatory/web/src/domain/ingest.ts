// Entity import validation (D-05, D-P8-11): atomic per record, dependants rejected with DEPENDENT_REJECTED, nothing dropped silently.
// `validateImport(data)` takes an inputs.json-shaped object and returns the accepted rows per entity and the rejected rows (each with its reason
// code and the raw row exactly as sent). Rules, in the order they are applied to a row: duplicate primary key (or repeated run/task/attempt) ->
// DUPLICATE_ID; foreign key unknown -> UNKNOWN_*; foreign key rejected -> DEPENDENT_REJECTED. Backfills overlapping an earlier accepted request of
// the same source (backfill_id order, half-open) -> BACKFILL_OVERLAP. A checkpoint whose version is not previous + 1 (commit order) ->
// CHECKPOINT_REGRESSION / CHECKPOINT_GAP and its batch, and through it the batch's rows, are DEPENDENT_REJECTED.
import * as E from "./errors";
import { DomainError } from "./errors";
import { findOverlap } from "./backfill";
import { nextCheckpointVersion } from "./classify";
import { ENTITIES, FK, ID, type Entity, type Row } from "./contract";
import { canonicalJson } from "./hashing";
import { isDict, pyInt, sortedBy } from "./py";
import { parseTs } from "./time";

export interface Rejected { entity: Entity; id: string | null; status: "rejected"; reason_code: string; raw_row: unknown }
export interface ImportResult { accepted: Record<Entity, Row[]>; rejected: Rejected[]; counts(): Record<Entity, { accepted: number; rejected: number }> }

const rowId = (entity: Entity, row: unknown): string | null => (isDict(row) && typeof row[ID[entity]] === "string" && row[ID[entity]] ? (row[ID[entity]] as string) : null);

export function validateImport(data: Record<string, unknown>): ImportResult {
  const list = (e: Entity): Row[] => (Array.isArray(data[e]) ? (data[e] as Row[]) : []);
  const acc = Object.fromEntries(ENTITIES.map((e) => [e, [] as Row[]])) as Record<Entity, Row[]>;
  const accIds = Object.fromEntries(ENTITIES.map((e) => [e, new Set<string>()])) as Record<Entity, Set<string>>;
  const rejIds = Object.fromEntries(ENTITIES.map((e) => [e, new Set<string>()])) as Record<Entity, Set<string>>;
  const seenPk = Object.fromEntries(ENTITIES.map((e) => [e, new Set<string>()])) as Record<Entity, Set<string>>;
  const seenAttempt = new Set<string>();
  const rejected: [number, number, Rejected][] = [];
  const firstIndex = new Map<Entity, Map<string, number>>();
  const indexOfRow = (entity: Entity, row: unknown): number => {          // Python's list.index: the first row equal to this one
    let m = firstIndex.get(entity);
    if (!m) { m = new Map(); list(entity).forEach((r, i) => { const k = safeCanon(r); if (!m!.has(k)) m!.set(k, i); }); firstIndex.set(entity, m); }
    return m.get(safeCanon(row)) ?? 0;
  };
  const reject = (entity: Entity, row: unknown, code: string): void => {
    const rid = rowId(entity, row);
    rejected.push([ENTITIES.indexOf(entity), indexOfRow(entity, row), { entity, id: rid, status: "rejected", reason_code: code, raw_row: row }]);
    if (rid !== null) rejIds[entity].add(rid);
  };
  const accept = (entity: Entity, row: Row): void => {
    acc[entity].push(row);
    accIds[entity].add(row[ID[entity]]);
    seenPk[entity].add(row[ID[entity]]);
    if (entity === "task_runs") seenAttempt.add(`${row["run_id"]}\u0000${row["task_name"]}\u0000${pyInt(row["attempt"])}`);
  };
  const refusal = (entity: Entity, row: unknown): string | null => {
    const rid = rowId(entity, row);
    if (rid === null) return E.MISSING_FIELD;
    const r = row as Row;
    if (seenPk[entity].has(rid)) return E.DUPLICATE_ID;
    if (entity === "task_runs" && seenAttempt.has(`${r["run_id"]}\u0000${r["task_name"]}\u0000${pyInt(r["attempt"] ?? 0)}`)) return E.DUPLICATE_ID;   // a repeated attempt
    const fk = FK[entity];
    if (fk) {
      const [field, parent, unknown] = fk;
      const pid = r[field];
      if (accIds[parent].has(pid)) { /* known parent */ }
      else if (rejIds[parent].has(pid)) return E.DEPENDENT_REJECTED;
      else return unknown;
    }
    if (entity === "pipeline_runs" && r["backfill_id"] !== null && r["backfill_id"] !== undefined) {
      if (rejIds.backfill_requests.has(r["backfill_id"])) return E.DEPENDENT_REJECTED;
      if (!accIds.backfill_requests.has(r["backfill_id"])) return E.UNKNOWN_BACKFILL;
    }
    return null;
  };
  const plain = (entity: Entity): void => {
    for (const row of list(entity)) { const code = refusal(entity, row); if (code) reject(entity, row, code); else accept(entity, row); }
  };

  plain("source_contracts");
  for (const row of list("backfill_requests")) {                       // in backfill_id order of the input list
    let code = refusal("backfill_requests", row);
    if (code === null && findOverlap(acc.backfill_requests, row) !== null) code = E.BACKFILL_OVERLAP;
    if (code) reject("backfill_requests", row, code); else accept("backfill_requests", row);
  }
  const batchRows: Row[] = [];
  for (const row of list("ingestion_batches")) { const code = refusal("ingestion_batches", row); if (code) reject("ingestion_batches", row, code); else batchRows.push(row); }
  const live = new Set<string>(batchRows.map((b) => b["batch_id"]));
  // the atomic commit: every checkpoint of a live batch must be previous + 1 of its source, in commit order
  const cpCode = new Map<string, string>();
  const badBatches = new Set<string>();
  const previous = new Map<string, number>();
  for (const c of sortedBy(list("checkpoints").filter((c) => live.has(c["batch_id"])), (c) => [c["committed_at"] as string, c["checkpoint_id"] as string])) {
    try { previous.set(c["source_id"], nextCheckpointVersion(previous.get(c["source_id"]) ?? 0, c["version_number"])); }
    catch (err) { if (!(err instanceof DomainError)) throw err; cpCode.set(c["checkpoint_id"], err.code); badBatches.add(c["batch_id"]); }
  }
  for (const b of batchRows) { if (badBatches.has(b["batch_id"])) reject("ingestion_batches", b, E.DEPENDENT_REJECTED); else accept("ingestion_batches", b); }
  for (const c of list("checkpoints")) { const code = cpCode.get(c["checkpoint_id"]) || refusal("checkpoints", c); if (code) reject("checkpoints", c, code); else accept("checkpoints", c); }
  for (const e of ["raw_records", "quarantine_records", "model_definitions", "pipeline_runs", "task_runs", "quality_results", "publications", "incidents"] as const) plain(e);
  rejected.sort((a, b) => a[0] - b[0] || a[1] - b[1]);                 // stable: ties keep the order the rows were rejected in
  const rej = rejected.map((t) => t[2]);
  return { accepted: acc, rejected: rej, counts: () => Object.fromEntries(ENTITIES.map((e) => [e, { accepted: acc[e].length, rejected: rej.filter((r) => r.entity === e).length }])) as Record<Entity, { accepted: number; rejected: number }> };
}
const safeCanon = (v: unknown): string => { try { return canonicalJson(v); } catch { return JSON.stringify(v) ?? "undefined"; } };

/** Throw DomainError(MALFORMED_RECORD) on an instant that is not UTC-parsable (callers that load untrusted files). */
export function checkInstants(data: Record<string, unknown>): void {
  const spec: [Entity, string[]][] = [["ingestion_batches", ["started_at"]], ["checkpoints", ["committed_at"]], ["pipeline_runs", ["started_at"]], ["publications", ["published_at", "watermark"]], ["incidents", ["opened_at"]]];
  for (const [entity, fields] of spec) {
    for (const row of (data[entity] as Row[] | undefined) ?? []) {
      for (const f of fields) {
        try { parseTs(row[f]); } catch { throw new DomainError(E.MALFORMED_RECORD, `${entity}.${f} is not an ISO-8601 instant with a zone`, `${entity}.${f}`); }
      }
    }
  }
}
