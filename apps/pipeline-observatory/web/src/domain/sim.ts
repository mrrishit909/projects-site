// The pure parts of the three browser-memory simulations (quarantine desk, backfill console, fault injection) and of the in-browser experiments.
// Nothing here is stored or sent anywhere: each function takes the published rows and returns what the domain would decide; the screens keep the
// results in browser memory and say so.
import { checkRange, findOverlap } from "./backfill";
import { classifyRows } from "./classify";
import type { Row } from "./contract";
import { DomainError } from "./errors";
import * as E from "./errors";
import { decide, mayPublish, type GateDecision } from "./gate";
import { runPipeline } from "./metrics";
import { isoZ } from "./time";

// ------------------------------------------------------------------------------------------------------------ quarantine desk
export type Disposition = "correct-and-replay" | "refetch-after-bump" | "no-retry-source-fix";
/** What an operator can do with a quarantined row, by reason code (a display rule over the contract's reason codes). */
export function retryAdvice(reason: string): { disposition: Disposition; text: string } {
  switch (reason) {
    case E.SCHEMA_CHANGED: return { disposition: "refetch-after-bump", text: "The whole batch was refused because its declared schema_version differs from the contract. Bump the expected schema_version explicitly (operator), then fetch the window again." };
    case E.DELETE_TARGET_UNKNOWN: return { disposition: "no-retry-source-fix", text: "The delete names a key that was never accepted. Replaying it changes nothing until the key exists; ask the source whether the upsert was lost." };
    case E.UNKNOWN_OP: return { disposition: "no-retry-source-fix", text: "The record carries an operation the contract does not know. The source must send upsert or delete." };
    default: return { disposition: "correct-and-replay", text: "The payload fails the contract. Correct the field at the source (or here, in memory) and replay it; the key check runs first, then the contract check." };
  }
}
export interface RetryOutcome { kind: string; reason: string | null }
/** Replay one payload as a new row of a source whose accepted keys are `acceptedKeys` (the keys visible to the caller; extended only on acceptance). */
export function retryRow(sourceKey: string | null, payload: unknown, acceptedKeys: ReadonlySet<unknown>, cutoff: unknown = null): RetryOutcome {
  const keys = new Set<unknown>(acceptedKeys);
  const d = classifyRows([{ raw_record_id: "rr-retry", source_key: sourceKey, payload_json: payload }], keys, new Set(), true, null, cutoff)[0]!;
  return { kind: d.kind, reason: d.reason };
}

// ------------------------------------------------------------------------------------------------------------ backfill console
export interface BackfillAsk { source_id: string; start_at: string; end_at: string }
export interface BackfillDecision { accepted: boolean; code: string | null; message: string; partitions: string[]; overlaps_with: string | null; revisits: { backfill_id: string; partition: string }[] }
/** The domain's decision on a backfill request against the accepted requests (half-open ranges, daily UTC partitions; touching ranges are allowed).
 * Only requests still requested or running block (D-09, R8-12); a settled (partial or complete) request does not, and the partitions of the ask that
 * a partial request left unverified are listed in `revisits`: the recovery path. */
export function decideBackfill(accepted: Row[], ask: BackfillAsk): BackfillDecision {
  let partitions: string[];
  try { partitions = checkRange(ask.start_at, ask.end_at); }
  catch (e) {
    if (e instanceof DomainError) return { accepted: false, code: e.code, message: e.message.replace(/^[A-Z_]+: /, ""), partitions: [], overlaps_with: null, revisits: [] };
    return { accepted: false, code: E.INVALID_RANGE, message: "start_at and end_at must be UTC instants such as 2026-09-01T00:00:00Z", partitions: [], overlaps_with: null, revisits: [] };
  }
  const hit = findOverlap(accepted, { source_id: ask.source_id, start_at: ask.start_at, end_at: ask.end_at });
  if (hit) return { accepted: false, code: E.BACKFILL_OVERLAP, message: `overlaps ${hit["backfill_id"]} [${isoZ(hit["start_at"])}, ${isoZ(hit["end_at"])}) of the same source, which is still ${hit["status"]}; two backfills over overlapping ranges cannot run together`, partitions, overlaps_with: hit["backfill_id"], revisits: [] };
  const revisits: { backfill_id: string; partition: string }[] = [];
  for (const o of accepted) {
    if (o["source_id"] !== ask.source_id || o["status"] !== "partial") continue;
    for (const p of (o["partitions"] ?? []) as Row[]) if (!p["verified"] && partitions.includes(p["partition"])) revisits.push({ backfill_id: o["backfill_id"], partition: p["partition"] });
  }
  const again = revisits.length ? `; it backfills again ${revisits.map((r) => `${r.partition} (left unverified by ${r.backfill_id}, which has settled)`).join(", ")}` : "";
  return { accepted: true, code: null, message: `accepted: ${partitions.length} daily partition${partitions.length === 1 ? "" : "s"}, none verified yet${again}`, partitions, overlaps_with: null, revisits };
}

// ------------------------------------------------------------------------------------------------------------ gate what-if / fault injection
export interface WhatIf { gate: GateDecision; publishes: boolean; pointer_after: string | null; run_status: "success" | "failed" }
/** Re-decide a run's gate with some checks forced to fail (a fault injected in the synthetic sandbox): `failures` maps rule_name -> failure_count. */
export function gateWhatIf(results: Row[], failures: Record<string, number>, hasPublication: boolean, pointerBefore: string | null, candidate: string | null): WhatIf {
  const forced = results.map((q) => (q["rule_name"] in failures ? { ...q, failure_count: failures[q["rule_name"]] } : q));
  const gate = decide(forced);
  const status = gate.decision === "allowed" ? "success" : "failed";
  const publishes = mayPublish(status, gate.decision, hasPublication || candidate !== null);
  return { gate, publishes, pointer_after: publishes ? (candidate ?? pointerBefore) : pointerBefore, run_status: status };
}

// ------------------------------------------------------------------------------------------------------------ experiments on the golden fixture
export interface Counts { received: number; accepted_unique: number; duplicate: number; quarantined: number }
export interface Experiment { id: string; title: string; steps: { label: string; counts: Counts; accepted_total: number; note: string }[]; verdict: string; holds: boolean }
export interface BatchSpec { batch_id: string; source_id: string; started_at: string; status: string; rows: Row[]; checkpoint: { committed_at: string; committed_cursor: string } | null }
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
/** A copy of an inputs.json-shaped object with extra batches, their raw rows (renamed to the new batch) and, where committed, a next-version checkpoint. */
export function withBatches(inputs: Record<string, unknown>, specs: BatchSpec[]): Record<string, unknown> {
  const d = clone(inputs) as Record<string, Row[]>;
  const version: Record<string, number> = {};
  for (const c of d["checkpoints"]!) version[c["source_id"]] = Math.max(version[c["source_id"]] ?? 0, c["version_number"]);
  for (const s of specs) {
    d["ingestion_batches"]!.push({ batch_id: s.batch_id, source_id: s.source_id, source_cursor: "cur-000", started_at: s.started_at, status: s.status });
    s.rows.forEach((r, i) => d["raw_records"]!.push({ ...r, raw_record_id: `rr-${s.batch_id}-${String(i + 1).padStart(2, "0")}`, batch_id: s.batch_id }));
    if (s.checkpoint) {
      version[s.source_id] = (version[s.source_id] ?? 0) + 1;
      d["checkpoints"]!.push({ checkpoint_id: `cp-${s.batch_id}`, source_id: s.source_id, batch_id: s.batch_id, committed_cursor: s.checkpoint.committed_cursor, committed_at: s.checkpoint.committed_at, version_number: version[s.source_id] });
    }
  }
  return d;
}
function countsOf(inputs: Record<string, unknown>, sourceId: string): { overall: Counts; batches: Record<string, Row>; total: number } {
  const g = runPipeline(inputs).golden;
  const s = g.metrics.ingestion.sources[sourceId];
  return { overall: { received: s.received, accepted_unique: s.accepted_unique, duplicate: s.duplicate, quarantined: s.quarantined }, batches: s.batches, total: s.accepted_unique };
}
/** The experiments of P08-GOLD-01 run through the domain on copies of the golden inputs: the batch, its replay (and a storm of replays), and a crash. */
export function goldenExperiments(inputs: Record<string, unknown>): Experiment[] {
  const raws = (inputs["raw_records"] as Row[]).filter((r) => r["batch_id"] === "b-001");
  const first = (inputs["ingestion_batches"] as Row[]).find((b) => b["batch_id"] === "b-001")!;
  const src = first["source_id"] as string;
  const base = { ...(inputs as Row), ingestion_batches: [first], raw_records: raws, checkpoints: (inputs["checkpoints"] as Row[]).filter((c) => c["batch_id"] === "b-001") } as Record<string, unknown>;
  const one = countsOf(base, src);
  const out: Experiment[] = [];
  out.push({ id: "batch", title: "One batch of ten rows", steps: [{ label: "commit b-001", counts: one.overall, accepted_total: one.total, note: "8 valid unique keys accepted, ORD-1003 repeated, ORD-1009 has a negative quantity" }],
    verdict: "received 10 = 8 accepted + 1 duplicate + 1 quarantined; nothing dropped", holds: one.overall.received === 10 && one.overall.accepted_unique === 8 && one.overall.duplicate === 1 && one.overall.quarantined === 1 });
  const at = (h: number): string => `2026-10-04T${String(h).padStart(2, "0")}:00:00Z`;
  const replay = (n: number): Experiment => {
    const specs: BatchSpec[] = Array.from({ length: n }, (_, i) => ({ batch_id: `b-r${i + 1}`, source_id: src, started_at: at(12 + i), status: "committed", rows: raws, checkpoint: { committed_at: at(12 + i).replace(":00:00", ":05:00"), committed_cursor: "cur-010" } }));
    const steps = [{ label: "commit b-001", counts: one.overall, accepted_total: one.total, note: "the first delivery" }];
    for (let i = 1; i <= n; i++) {
      const c = countsOf(withBatches(base, specs.slice(0, i)), src);
      const b = c.batches[`b-r${i}`] as Row;
      steps.push({ label: `replay ${i}`, counts: { received: b["received"], accepted_unique: b["accepted_unique"], duplicate: b["duplicate"], quarantined: b["quarantined"] }, accepted_total: c.total, note: "same ten rows from the same cursor" });
    }
    return { id: n === 1 ? "replay" : "storm", title: n === 1 ? "Replaying the batch" : `A replay storm of ${n} replays`, steps, verdict: `accepted stays ${steps[steps.length - 1]!.accepted_total}: apply is idempotent on source_key (at-least-once delivery, idempotent apply)`, holds: steps.every((s) => s.accepted_total === 8) };
  };
  out.push(replay(1), replay(5));
  const crashCase = (id: string, title: string, extra: Row[], verdictOf: (c: { crashed: number; redone: number; added: number }) => string, holds: (c: { crashed: number; redone: number; added: number }) => boolean): Experiment => {
    const crash: BatchSpec = { batch_id: "b-x1", source_id: src, started_at: at(18), status: "aborted", rows: [...raws, ...extra], checkpoint: null };
    const redo: BatchSpec = { batch_id: "b-x2", source_id: src, started_at: at(19), status: "committed", rows: [...raws, ...extra], checkpoint: { committed_at: "2026-10-04T19:05:00Z", committed_cursor: "cur-011" } };
    const crashed = countsOf(withBatches(base, [crash]), src), redone = countsOf(withBatches(base, [crash, redo]), src);
    const x2 = redone.batches["b-x2"] as Row;
    const c = { crashed: crashed.total, redone: redone.total, added: x2["accepted_unique"] as number };
    return { id, title, steps: [
      { label: "commit b-001", counts: one.overall, accepted_total: one.total, note: "8 accepted" },
      { label: `b-x1 writes its ${raws.length + extra.length} rows and dies before the checkpoint`, counts: { received: 0, accepted_unique: 0, duplicate: 0, quarantined: 0 }, accepted_total: crashed.total, note: "no checkpoint row: the batch is aborted, counted false, and counts for nothing" },
      { label: "replay from the last committed cursor as b-x2", counts: { received: x2["received"], accepted_unique: x2["accepted_unique"], duplicate: x2["duplicate"], quarantined: x2["quarantined"] }, accepted_total: redone.total, note: extra.length ? "the new key is accepted once, by the committed batch only" : "every key is already accepted" }],
      verdict: verdictOf(c), holds: holds(c) };
  };
  out.push(crashCase("crash", "A crash after the data write, before the checkpoint", [], (c) => `the crash leaves ${c.crashed} and the replay leaves ${c.redone}: a ninth accepted record is never created`, (c) => c.crashed === 8 && c.redone === 8 && c.added === 0));
  const ninth: Row = { source_key: "ORD-1010", payload_hash: "0".repeat(64), payload_json: { record_id: "ORD-1010", quantity: 1, unit_price: "5.00", amount: "5.00", event_ts: "2026-10-04T09:40:00Z" } };
  out.push(crashCase("crash-new-key", "The same crash when the batch also carried one new key", [ninth], (c) => `the crash still leaves ${c.crashed}; the key it carried becomes the ${c.redone}th record once, when the replay commits`, (c) => c.crashed === 8 && c.redone === 9 && c.added === 1));
  return out;
}
