// Adversarial checks of the TypeScript domain on small hand-worked worlds (the pure-domain twin of the contract's edge cases). Every world below
// is derived by hand in its comment BEFORE the expected values were typed; the expectations are written as paths into the golden shape so that
// `REVIEW_DUMP=file npx tsx scripts/review-check.ts` can export the worlds and the Python domain can replay them (done once when this file was
// written: every expectation also holds under domain/pipeline_observatory). Worlds: replay storms, out-of-order and regressing checkpoints, a delete
// of an unknown key, delete propagation into reconciliation, a late event exactly at the watermark, a gate with a warning only, a blocked run with a
// publication attempt, overlapping and touching backfills, empty populations, and more. Run by `npm run check` after the golden check.
import { readFileSync, writeFileSync } from "node:fs";
import { checkRange, findOverlap, rangesOverlap } from "../src/domain/backfill";
import { checkCursorProgress, checkRetryAllowed, fetchAll, judgeFetch, type Fetched, type Page } from "../src/domain/fetch";
import { decide, scopeComplete } from "../src/domain/gate";
import { parseJsonExact } from "../src/domain/json";
import { moneyAmount, contractReason } from "../src/domain/classify";
import { pendingLateEvents, type Accepted } from "../src/domain/reconcile";
import { canonicalJson, contentHash, payloadHash } from "../src/domain/hashing";
import { computeWindow, runPipeline } from "../src/domain/metrics";
import { decFr, type Fr } from "../src/domain/num";
import { containsSecret, redactText, redactValue, safeLine, WITHHELD } from "../src/domain/redaction";
import { isoZ, parseTs } from "../src/domain/time";
import { DomainError } from "../src/domain/errors";
import { decideBackfill, gateWhatIf, retryAdvice } from "../src/domain/sim";

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
let failures = 0, checks = 0, worlds = 0;
const canon = (v: unknown): string => canonicalJson(v ?? null);
function eq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) !== canon(want)) { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 300)} want ${canon(want).slice(0, 300)}`); }
}
const dump: Row[] = [];

// ----------------------------------------------------------------------------------------------------------------------------- builders
const at = (hh: number, mm = 0, ss = 0, day = 4): string => `2026-10-${String(day).padStart(2, "0")}T${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}Z`;
const src = (id = "src-a", schema = "1", extra: Row = {}): Row => ({ source_id: id, source_name: id, schema_version: schema, expected_frequency: "hourly", owner_id: "own-1", ...extra });
const batch = (id: string, started: string, source = "src-a", status = "committed", extra: Row = {}): Row => ({ batch_id: id, source_id: source, source_cursor: "cur-000", started_at: started, status, ...extra });
const pay = (k: string, o: Row = {}): Row => ({ record_id: k, quantity: 1, unit_price: "10.00", amount: "10.00", event_ts: at(8), ...o });
const rr = (b: string, i: number, k: string | null, o: Row = {}, payload?: Row | null): Row => ({ raw_record_id: `rr-${b}-${i}`, batch_id: b, source_key: k, payload_hash: "h", payload_json: payload === undefined ? pay(k ?? "KX", o) : payload });
const cp = (b: string, version: number, committed: string, source = "src-a", cursor = "cur-001"): Row => ({ checkpoint_id: `cp-${b}`, source_id: source, batch_id: b, committed_cursor: cursor, committed_at: committed, version_number: version });
const run = (id: string, started: string, finished: string | null, status = "success", extra: Row = {}): Row => ({ run_id: id, started_at: started, finished_at: finished, status, code_sha: "abc1234", backfill_id: null, ...extra });
const task = (id: string, r: string, name: string, attempt: number | string, status = "success"): Row => ({ task_run_id: id, run_id: r, task_name: name, status, attempt });
const qr = (id: string, tr: string, rule: string, severity: string, eligible: number, failures: number): Row => ({ quality_result_id: id, task_run_id: tr, rule_name: rule, severity, eligible_count: eligible, failure_count: failures });
const pub = (id: string, r: string, publishedAt: string, watermark: string, included: string[], sources = ["src-a"]): Row => ({ publication_id: id, run_id: r, dataset_name: "sales_daily", published_at: publishedAt, watermark, source_ids: sources, included_batch_ids: included, content_hash: "0".repeat(64) });
const inc = (id: string, r: string, opened: string, status: string, closed: string | null, recovery: string | null): Row => ({ incident_id: id, run_id: r, severity: "high", status, opened_at: opened, closed_at: closed, recovery_run_id: recovery });
const bf = (id: string, source: string, start: string, end: string, verified: boolean[]): Row => ({ backfill_id: id, source_id: source, start_at: start, end_at: end, status: "requested", partitions: verified.map((v, i) => ({ partition: new Date(Date.parse(start) + i * 86400000).toISOString().slice(0, 10), verified: v })) });
const world = (over: Row = {}): Row => ({ contract_version: 1, as_of: at(0, 0, 0, 5), cutoff: at(0, 0, 0, 5), business_total_field: "amount", freshness_timestamp_field: "event_ts", source_expectations: [], processing_measurement: null,
  source_contracts: [src()], ingestion_batches: [], raw_records: [], quarantine_records: [], checkpoints: [], model_definitions: [], pipeline_runs: [], task_runs: [], quality_results: [], publications: [], incidents: [], backfill_requests: [], ...over });
/** One gate-bearing run: the run, its quality_gate task and the listed results. */
const gated = (id: string, started: string, finished: string, status: string, results: [string, string, number, number][], n = 1): { runs: Row[]; tasks: Row[]; qrs: Row[] } => ({
  runs: [run(id, started, finished, status)], tasks: [task(`tr-${id}`, id, "quality_gate", 1, status === "success" ? "success" : "failed")], qrs: results.map(([rule, sev, el, fl], i) => qr(`qr-${id}-${n}${i}`, `tr-${id}`, rule, sev, el, fl)) });
const lookup = (o: Row, path: string): unknown => path.split(".").reduce((c: any, k) => (c === undefined || c === null ? undefined : c[k]), o); // eslint-disable-line @typescript-eslint/no-explicit-any
const rej = (res: ReturnType<typeof runPipeline>): unknown[] => res.golden.ingest.rejected_records.map((r: Row) => [r.entity, r.id, r.reason_code]);

/** A hand-worked world: `expect` maps a path in the golden shape to its hand-derived value; `rejected` the [entity, id, code] triples in order. */
function W(title: string, inputs: Row, expect: Record<string, unknown>, rejected?: unknown[], totals?: Record<string, string>): ReturnType<typeof runPipeline> {
  worlds++;
  const t: Record<string, Fr> | null = totals ? Object.fromEntries(Object.entries(totals).map(([k, v]) => [k, decFr(v)])) : null;
  const res = runPipeline(inputs, t);
  let bad = 0;
  for (const [path, want] of Object.entries(expect)) { checks++; const got = lookup(res.golden, path); if (canon(got) !== canon(want)) { failures++; bad++; console.log(`MISMATCH world ${worlds} ${path}: got ${canon(got).slice(0, 200)} want ${canon(want).slice(0, 200)}`); } }
  if (rejected) { checks++; if (canon(rej(res)) !== canon(rejected)) { failures++; bad++; console.log(`MISMATCH world ${worlds} rejected: got ${canon(rej(res))} want ${canon(rejected)}`); } }
  console.log(`${bad ? "MISMATCH" : "OK      "} world ${String(worlds).padStart(2, "0")}: ${title} (${Object.keys(expect).length + (rejected ? 1 : 0)} expectations)`);
  dump.push({ title, inputs, totals: totals ?? null, expect, rejected: rejected ?? null });
  return res;
}
const S = "metrics.ingestion.sources.src-a";

// 1. A replay storm. b1 holds K1..K3 (all new), five replays hold the same three rows. 3 accepted; 5 x 3 = 15 duplicates; 18 received; 15/18 = 0.833333.
{
  const rows = (b: string): Row[] => ["K1", "K2", "K3"].map((k, i) => rr(b, i + 1, k));
  const ids = ["b1", "r1", "r2", "r3", "r4", "r5"];
  W("replay storm: five replays of three rows leave three accepted", world({ ingestion_batches: ids.map((b, i) => batch(b, at(8 + i))), raw_records: ids.flatMap(rows), checkpoints: ids.map((b, i) => cp(b, i + 1, at(8 + i, 5))) }),
    { [`${S}.received`]: 18, [`${S}.accepted_unique`]: 3, [`${S}.duplicate`]: 15, [`${S}.duplicate_rate`]: "0.833333", [`${S}.batches.r3.accepted_unique`]: 0, [`${S}.batches.r3.duplicate`]: 3, [`${S}.checkpoint.committed_version`]: 6 }, []);
}
// 2. An out-of-order checkpoint: versions 1 then 3 in commit order. Previous 1, so 3 skips 2 -> CHECKPOINT_GAP; its batch b2 and b2's row are DEPENDENT_REJECTED
//    (entity order: ingestion_batches, raw_records, checkpoints). Only b1 counts.
W("out-of-order checkpoint: a version gap rejects the checkpoint, its batch and the batch's rows", world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(9))], raw_records: [rr("b1", 1, "K1"), rr("b2", 1, "K2")],
  checkpoints: [cp("b1", 1, at(8, 5)), cp("b2", 3, at(9, 5))] }),
  { [`${S}.received`]: 1, [`${S}.checkpoint.committed_version`]: 1, "ingest.counts.ingestion_batches.rejected": 1, "ingest.counts.checkpoints.rejected": 1, "ingest.counts.raw_records.rejected": 1 },
  [["ingestion_batches", "b2", "DEPENDENT_REJECTED"], ["raw_records", "rr-b2-1", "DEPENDENT_REJECTED"], ["checkpoints", "cp-b2", "CHECKPOINT_GAP"]]);
// 3. A regressing checkpoint: versions 1 then 1. The second (later commit) is not previous + 1 -> CHECKPOINT_REGRESSION.
W("regressing checkpoint: version 1 twice", world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(9))], raw_records: [rr("b1", 1, "K1"), rr("b2", 1, "K2")], checkpoints: [cp("b1", 1, at(8, 5)), cp("b2", 1, at(9, 5))] }),
  { [`${S}.accepted_unique`]: 1 }, [["ingestion_batches", "b2", "DEPENDENT_REJECTED"], ["raw_records", "rr-b2-1", "DEPENDENT_REJECTED"], ["checkpoints", "cp-b2", "CHECKPOINT_REGRESSION"]]);
// 4. Commit order beats id order: cp-z is version 1 committed 08:05, cp-a is version 2 committed 09:05. Both fine; the newest version is cp-a's batch.
W("commit order, not id order, decides the version sequence", world({ ingestion_batches: [batch("bz", at(8)), batch("ba", at(9))], raw_records: [rr("bz", 1, "K1"), rr("ba", 1, "K2")], checkpoints: [cp("bz", 1, at(8, 5)), cp("ba", 2, at(9, 5))] }),
  { [`${S}.checkpoint.committed_version`]: 2, [`${S}.checkpoint.committed_batch_id`]: "ba", [`${S}.accepted_unique`]: 2 }, []);
// 5. A delete of an unknown key is quarantined DELETE_TARGET_UNKNOWN, never ignored: received 1, accepted 0, quarantined 1.
W("delete of an unknown key is quarantined", world({ ingestion_batches: [batch("b1", at(8))], raw_records: [rr("b1", 1, "K9", {}, { op: "delete", record_id: "K9", amount: "7.00" })], checkpoints: [cp("b1", 1, at(8, 5))],
  quarantine_records: [{ quarantine_id: "q1", batch_id: "b1", source_key: "K9", reason_code: "DELETE_TARGET_UNKNOWN", payload_hash: "h" }] }),
  { [`${S}.received`]: 1, [`${S}.accepted_unique`]: 0, [`${S}.quarantined`]: 1, [`${S}.quarantine_by_reason.DELETE_TARGET_UNKNOWN`]: 1, [`${S}.batches.b1.quarantine_rows_match`]: true }, []);
// 6. Delete propagation into reconciliation. b1 accepts K1 (10.00); b2 deletes K1 (delete row amount 10.00); b3 deletes K1 again (a duplicate).
//    pub-1 includes b1+b2: source = 10.00 + 10.00 = 20.00; K1 is removed from the snapshot, so published = 0.00; deletes exclusion = delete row 10.00 + removed record 10.00 = 20.00;
//    residual = 20.00 - 0.00 - 20.00 = 0.00. pub-2 includes only b1: source 10.00, published 10.00, residual 0.00.
{
  const g = gated("run-1", at(10), at(10, 30), "success", [["keys_unique", "critical", 1, 0]]);
  W("a delete removes the record from the publication that includes it and balances the reconciliation", world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(9)), batch("b3", at(9, 30))],
    raw_records: [rr("b1", 1, "K1"), rr("b2", 1, "K1", {}, { op: "delete", record_id: "K1", amount: "10.00" }), rr("b3", 1, "K1", {}, { op: "delete", record_id: "K1", amount: "10.00" })],
    checkpoints: [cp("b1", 1, at(8, 5)), cp("b2", 2, at(9, 5)), cp("b3", 3, at(9, 35))], pipeline_runs: g.runs, task_runs: g.tasks, quality_results: g.qrs,
    publications: [pub("pub-1", "run-1", at(10, 30), at(9), ["b1", "b2"])] }),
    { "metrics.reconciliation.pub-1.source_total": "20.00", "metrics.reconciliation.pub-1.published_total": "0.00", "metrics.reconciliation.pub-1.exclusions.deletes": "20.00", "metrics.reconciliation.pub-1.residual": "0.00",
      "metrics.publications.publications.pub-1.published_records": 0, [`${S}.batches.b2.received`]: 1, [`${S}.batches.b2.accepted_unique`]: 0, [`${S}.batches.b2.quarantined`]: 0, [`${S}.batches.b3.duplicate`]: 1 }, []);
  W("the same delete batch left out of a publication leaves the record in it", world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(9))], raw_records: [rr("b1", 1, "K1"), rr("b2", 1, "K1", {}, { op: "delete", record_id: "K1", amount: "10.00" })],
    checkpoints: [cp("b1", 1, at(8, 5)), cp("b2", 2, at(9, 5))], pipeline_runs: g.runs, task_runs: g.tasks, quality_results: g.qrs, publications: [pub("pub-2", "run-1", at(10, 30), at(9), ["b1"])] }),
    { "metrics.reconciliation.pub-2.source_total": "10.00", "metrics.reconciliation.pub-2.published_total": "10.00", "metrics.reconciliation.pub-2.residual": "0.00", "metrics.publications.publications.pub-2.published_records": 1 }, []);
}
// 7. A late event exactly at the watermark. pub-1 published 12:00, watermark 10:00. b2 commits 13:00 with L1 event 10:00:00 (== watermark: late), L2 event 10:00:01 (after: not late),
//    L3 event 09:59:59 (late). The next publication including b2 is pub-2 (14:00). Order of the events: arrival, then key: L1, L3. b1 (K1, committed 09:00) arrived before any publication: not late.
{
  const g1 = gated("run-1", at(11, 50), at(12), "success", [["keys_unique", "critical", 1, 0]]), g2 = gated("run-2", at(13, 50), at(14), "success", [["keys_unique", "critical", 1, 0]]);
  W("a late event exactly at the watermark is late; one second after is not", world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(12, 55))],
    raw_records: [rr("b1", 1, "K1", { event_ts: at(8) }), rr("b2", 1, "L1", { event_ts: at(10) }), rr("b2", 2, "L2", { event_ts: at(10, 0, 1) }), rr("b2", 3, "L3", { event_ts: at(9, 59, 59) })],
    checkpoints: [cp("b1", 1, at(9)), cp("b2", 2, at(13))], pipeline_runs: [...g1.runs, ...g2.runs], task_runs: [...g1.tasks, ...g2.tasks], quality_results: [...g1.qrs, ...g2.qrs],
    publications: [pub("pub-1", "run-1", at(12), at(10), ["b1"]), pub("pub-2", "run-2", at(14), at(13), ["b1", "b2"])] }),
    { "metrics.late_events.count": 2, "metrics.late_events.included_in_next_publication": 2, "metrics.late_events.lost": 0, "metrics.late_events.events.0.source_key": "L1", "metrics.late_events.events.1.source_key": "L3",
      "metrics.late_events.events.0.behind_publication_id": "pub-1", "metrics.late_events.events.0.included_in_publication_id": "pub-2", "metrics.late_events.events.0.watermark": at(10) }, []);
  // 8. A batch arriving exactly at published_at is not after it (published_at < arrived is false): no late event. One second later it is late.
  const mk = (arrive: string): Row => world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(11, 55))], raw_records: [rr("b1", 1, "K1"), rr("b2", 1, "L1", { event_ts: at(9) })], checkpoints: [cp("b1", 1, at(9)), cp("b2", 2, arrive)],
    pipeline_runs: g1.runs, task_runs: g1.tasks, quality_results: g1.qrs, publications: [pub("pub-1", "run-1", at(12), at(10), ["b1"])] });
  W("arrival exactly at the publication instant is not after it", mk(at(12)), { "metrics.late_events.count": 0 }, []);
  W("arrival one second after the publication instant, event before the watermark, is late and (no later publication) lost", mk(at(12, 0, 1)),
    { "metrics.late_events.count": 1, "metrics.late_events.lost": 1, "metrics.late_events.included_in_next_publication": 0, "metrics.late_events.events.0.included_in_publication_id": null }, []);
}
// 10. A gate with a warning only: keys_unique critical 0 failures, completeness warning 3 failures -> allowed (a failing warning never blocks); the pointer moves to pub-1.
{
  const g = gated("run-1", at(8), at(8, 20), "success", [["keys_unique", "critical", 10, 0], ["completeness_vs_expectation", "warning", 10, 3]]);
  W("a failing warning does not block the gate", world({ pipeline_runs: g.runs, task_runs: g.tasks, quality_results: g.qrs, ingestion_batches: [batch("b1", at(7))], raw_records: [rr("b1", 1, "K1")], checkpoints: [cp("b1", 1, at(7, 5))], publications: [pub("pub-1", "run-1", at(8, 20), at(7), ["b1"])] }),
    { "metrics.quality_gate.run-1.decision": "allowed", "metrics.quality_gate.run-1.critical_failures": 0, "metrics.quality_gate.run-1.noncritical_failures": 1, "metrics.publications.current_publication_id": "pub-1" }, []);
}
// 11. Fail closed: a run whose results are all warnings, and a run with no results at all, are blocked.
{
  const w = gated("run-1", at(8), at(8, 20), "success", [["completeness_vs_expectation", "warning", 10, 0]]);
  W("no critical result means blocked (fail closed): warnings only, and nothing at all", world({ pipeline_runs: [...w.runs, run("run-2", at(9), at(9, 20))], task_runs: w.tasks, quality_results: w.qrs }),
    { "metrics.quality_gate.run-1.decision": "blocked", "metrics.quality_gate.run-1.critical_failures": 0, "metrics.quality_gate.run-2.decision": "blocked" }, []);
}
// 12. The latest result per rule counts, by quality_result_id in string order: qr-a (2 failures) then qr-b (0) listed reversed -> passes; qr-10 sorts BEFORE qr-9 as text,
//     so qr-9 is the latest of the second rule: relationships_intact failures 0 at qr-9 (qr-10 had 1) -> passes. Both critical pass -> allowed.
W("latest result per rule is decided by id as text (qr-9 after qr-10)", world({ pipeline_runs: [run("run-1", at(8), at(8, 20))], task_runs: [task("t1", "run-1", "quality_gate", 1)],
  quality_results: [qr("qr-b", "t1", "keys_unique", "critical", 5, 0), qr("qr-a", "t1", "keys_unique", "critical", 5, 2), qr("qr-9", "t1", "relationships_intact", "critical", 5, 0), qr("qr-10", "t1", "relationships_intact", "critical", 5, 1)] }),
  { "metrics.quality_gate.run-1.decision": "allowed", "metrics.quality_gate.run-1.results.keys_unique.failures": 0, "metrics.quality_gate.run-1.results.relationships_intact.failures": 0 }, []);
// 13. A blocked run with a publication attempt: run-2 failed, its gate blocked (critical failure) yet a publications row pub-2 exists. The pointer must stay on pub-1.
// 14. A failed run with an allowed gate, and 15. a successful run with a blocked gate, never move the pointer either; run-4 (success + allowed + publication) does.
{
  const a = gated("run-1", at(8), at(8, 20), "success", [["keys_unique", "critical", 5, 0]]), b = gated("run-2", at(9), at(9, 20), "failed", [["keys_unique", "critical", 5, 1]]);
  const c = gated("run-3", at(10), at(10, 20), "failed", [["keys_unique", "critical", 5, 0]]), d = gated("run-4", at(11), at(11, 20), "success", [["keys_unique", "critical", 5, 1]]), e = gated("run-5", at(12), at(12, 20), "success", [["keys_unique", "critical", 5, 0]]);
  const all = [a, b, c, d, e];
  W("the pointer moves only for success + allowed + a publication", world({ pipeline_runs: all.flatMap((x) => x.runs), task_runs: all.flatMap((x) => x.tasks), quality_results: all.flatMap((x) => x.qrs),
    publications: [pub("pub-1", "run-1", at(8, 20), at(8), []), pub("pub-2", "run-2", at(9, 20), at(9), []), pub("pub-3", "run-3", at(10, 20), at(10), []), pub("pub-4", "run-4", at(11, 20), at(11), []), pub("pub-5", "run-5", at(12, 20), at(12), [])] }),
    { "metrics.publications.pointer_history": [{ run_id: "run-1", gate_decision: "allowed", pointer_after: "pub-1" }, { run_id: "run-2", gate_decision: "blocked", pointer_after: "pub-1" }, { run_id: "run-3", gate_decision: "allowed", pointer_after: "pub-1" },
      { run_id: "run-4", gate_decision: "blocked", pointer_after: "pub-1" }, { run_id: "run-5", gate_decision: "allowed", pointer_after: "pub-5" }], "metrics.publications.current_publication_id": "pub-5" }, []);
  W("a success + allowed run with no publication row leaves the pointer where it was", world({ pipeline_runs: [...a.runs, ...e.runs], task_runs: [...a.tasks, ...e.tasks], quality_results: [...a.qrs, ...e.qrs], publications: [pub("pub-1", "run-1", at(8, 20), at(8), [])] }),
    { "metrics.publications.current_publication_id": "pub-1", "metrics.publications.pointer_history.1.pointer_after": "pub-1" }, []);
  // simultaneous finish: ties break by run_id, so run-a moves the pointer before run-b
  const x = gated("run-b", at(9), at(9, 30), "success", [["keys_unique", "critical", 5, 0]]), y = gated("run-a", at(9, 5), at(9, 30), "success", [["keys_unique", "critical", 5, 0]]);
  W("two runs finishing in the same second are ordered by run_id", world({ pipeline_runs: [...x.runs, ...y.runs], task_runs: [...x.tasks, ...y.tasks], quality_results: [...x.qrs, ...y.qrs], publications: [pub("pub-a", "run-a", at(9, 30), at(9), []), pub("pub-b", "run-b", at(9, 30), at(9), [])] }),
    { "metrics.publications.pointer_history.0.run_id": "run-a", "metrics.publications.pointer_history.1.run_id": "run-b", "metrics.publications.current_publication_id": "pub-b" }, []);
}
// 16. Overlapping and touching backfills. bf-1 [Sep 1, Sep 4) verified T,T,F; bf-2 [Sep 3, Sep 6) overlaps bf-1 -> BACKFILL_OVERLAP; bf-3 [Sep 4, Sep 5) touches bf-1's end -> accepted;
//     bf-4 is a different source over the same days -> accepted. Requested 3 + 1 + 3 = 7, verified 2 + 0 + 3 = 5 -> 5/7 = 0.714286.
W("overlapping backfills are refused, touching ones and other sources are accepted", world({ source_contracts: [src("src-a"), src("src-b")],
  backfill_requests: [bf("bf-1", "src-a", "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z", [true, true, false]), bf("bf-2", "src-a", "2026-09-03T00:00:00Z", "2026-09-06T00:00:00Z", [false, false, false]),
    bf("bf-3", "src-a", "2026-09-04T00:00:00Z", "2026-09-05T00:00:00Z", [false]), bf("bf-4", "src-b", "2026-09-02T00:00:00Z", "2026-09-05T00:00:00Z", [true, true, true])] }),
  { "metrics.backfills.refused": ["bf-2"], "metrics.backfills.overall.requested_partitions": 7, "metrics.backfills.overall.verified_partitions": 5, "metrics.backfills.overall.coverage": "0.714286", "ingest.counts.backfill_requests.accepted": 3, "ingest.counts.backfill_requests.rejected": 1 },
  [["backfill_requests", "bf-2", "BACKFILL_OVERLAP"]]);
// 17. Contained and identical ranges overlap too; a range ending exactly where bf-1 starts touches and is accepted. Listed order is the judging order.
W("a contained range and an identical range are refused; a range ending at the start is accepted", world({ backfill_requests: [bf("bf-1", "src-a", "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z", [true, true, true]), bf("bf-2", "src-a", "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z", [false]),
  bf("bf-3", "src-a", "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z", [false, false, false]), bf("bf-4", "src-a", "2026-08-31T00:00:00Z", "2026-09-01T00:00:00Z", [true])] }),
  { "metrics.backfills.refused": ["bf-2", "bf-3"], "metrics.backfills.overall.coverage": "1.000000" }, [["backfill_requests", "bf-2", "BACKFILL_OVERLAP"], ["backfill_requests", "bf-3", "BACKFILL_OVERLAP"]]);
// 18. The empty population: every count 0, every ratio null, empty_population true; an expectation of 0 gives null completeness, never 0.
W("the empty population: counts 0, ratios null, flag true", world({ source_expectations: [{ source_id: "src-a", partition: "2026-10-04", expected_records: 0 }] }),
  { empty_population: true, "metrics.ingestion.overall": { received: 0, accepted_unique: 0, duplicate: 0, quarantined: 0, rejection_rate: null, duplicate_rate: null }, "metrics.freshness.src-a.freshness_seconds": null, "metrics.freshness.src-a.ingestion_age_seconds": null,
    "metrics.completeness.src-a.2026-10-04.value": null, "metrics.completeness.src-a.2026-10-04.accepted_records": 0, "metrics.incidents.mean_recovery_minutes": null, "metrics.backfills.overall.coverage": null,
    "metrics.runs.overall.task_success_rate": null, "metrics.runs.durations.successful.mean_minutes": null, "metrics.publications.current_publication_id": null, "metrics.processing_rate.records_per_second": null }, []);
// 19. A committed batch with zero rows: rates are null (zero denominator), not 0.000000.
W("a committed batch of zero rows has null rates, not zero", world({ ingestion_batches: [batch("b1", at(8))], checkpoints: [cp("b1", 1, at(8, 5))] }),
  { [`${S}.batches.b1.rejection_rate`]: null, [`${S}.batches.b1.duplicate_rate`]: null, [`${S}.rejection_rate`]: null, [`${S}.batches.b1.counted`]: true, "empty_population": true }, []);
// 20. A replayed invalid row: quarantined once per occurrence (3 batches -> 3), one distinct key; one quarantine row per occurrence makes quarantine_rows_match true.
{
  const ids = ["b1", "b2", "b3"];
  W("a replayed invalid row is quarantined each time: 3 occurrences, 1 distinct key", world({ ingestion_batches: ids.map((b, i) => batch(b, at(8 + i))), raw_records: ids.map((b) => rr(b, 1, "K9", { quantity: -4 })), checkpoints: ids.map((b, i) => cp(b, i + 1, at(8 + i, 5))),
    quarantine_records: ids.map((b) => ({ quarantine_id: `q-${b}`, batch_id: b, source_key: "K9", reason_code: "NEGATIVE_QUANTITY", payload_hash: "h" })) }),
    { [`${S}.quarantined`]: 3, [`${S}.quarantined_distinct_keys`]: 1, [`${S}.quarantine_by_reason.NEGATIVE_QUANTITY`]: 3, [`${S}.batches.b3.quarantine_rows_match`]: true, [`${S}.accepted_unique`]: 0 }, []);
}
// 21. The key check runs before the contract check: K1 accepted in b1; b2 repeats K1 with a negative quantity -> a duplicate, NOT a quarantine.
W("a known key is a duplicate even if the repeated row is invalid", world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(9))], raw_records: [rr("b1", 1, "K1"), rr("b2", 1, "K1", { quantity: -5 })], checkpoints: [cp("b1", 1, at(8, 5)), cp("b2", 2, at(9, 5))] }),
  { [`${S}.batches.b2.duplicate`]: 1, [`${S}.batches.b2.quarantined`]: 0, [`${S}.quarantined`]: 0 }, []);
// 22. A row without a key (source_key null) and a row whose payload lacks required fields are both MISSING_FIELD; the null key is not a distinct key.
W("missing key and missing fields are quarantined MISSING_FIELD, never dropped", world({ ingestion_batches: [batch("b1", at(8))], raw_records: [rr("b1", 1, null, {}, pay("KX")), rr("b1", 2, "K2", {}, { record_id: "K2", quantity: 1 })], checkpoints: [cp("b1", 1, at(8, 5))] }),
  { [`${S}.received`]: 2, [`${S}.quarantined`]: 2, [`${S}.quarantine_by_reason.MISSING_FIELD`]: 2, [`${S}.quarantined_distinct_keys`]: 1, [`${S}.accepted_unique`]: 0 }, []);
// 23. SCHEMA_CHANGED: b1 declares schema "2" against contract "1": all 3 rows quarantined whole, none accepted, and (their keys unaccepted) b2 at schema "1" accepts K1, K2.
W("a batch declaring another schema_version is quarantined whole", world({ ingestion_batches: [batch("b1", at(8), "src-a", "committed", { schema_version: "2" }), batch("b2", at(9), "src-a", "committed", { schema_version: "1" })],
  raw_records: [rr("b1", 1, "K1"), rr("b1", 2, "K2"), rr("b1", 3, "K3"), rr("b2", 1, "K1"), rr("b2", 2, "K2")], checkpoints: [cp("b1", 1, at(8, 5)), cp("b2", 2, at(9, 5))] }),
  { [`${S}.batches.b1.quarantined`]: 3, [`${S}.batches.b1.accepted_unique`]: 0, [`${S}.quarantine_by_reason.SCHEMA_CHANGED`]: 3, [`${S}.batches.b2.accepted_unique`]: 2, [`${S}.accepted_unique`]: 2 }, []);
// 24. Unknown operations: op "merge" and op null are UNKNOWN_OP; an explicit op "upsert" is an ordinary upsert.
W("unknown operations are quarantined; an explicit upsert is accepted", world({ ingestion_batches: [batch("b1", at(8))], raw_records: [rr("b1", 1, "K1", { op: "merge" }), rr("b1", 2, "K2", { op: null }), rr("b1", 3, "K3", { op: "upsert" })], checkpoints: [cp("b1", 1, at(8, 5))] }),
  { [`${S}.quarantine_by_reason.UNKNOWN_OP`]: 2, [`${S}.accepted_unique`]: 1 }, []);
// 25. Reference integrity. b0 is fine; b1 names an unknown source (UNKNOWN_SOURCE); its row and checkpoint are DEPENDENT_REJECTED; a row for batch bX is UNKNOWN_BATCH; a copy of an
//     accepted row is DUPLICATE_ID. Python lists rejections by (entity, index of the first EQUAL row), so the copy (equal to row 0) comes first among raw_records.
{
  const good = rr("b0", 1, "K1");
  W("reference integrity: unknown source, unknown batch, dependants, repeated id (Python's list.index ordering)", world({ ingestion_batches: [batch("b0", at(8)), batch("b1", at(9), "src-zzz")], raw_records: [good, rr("b1", 1, "K2"), rr("bX", 1, "K3"), { ...good }],
    checkpoints: [cp("b0", 1, at(8, 5)), cp("b1", 1, at(9, 5), "src-zzz")] }),
    { "ingest.counts.raw_records.accepted": 1, "ingest.counts.raw_records.rejected": 3 }, [["ingestion_batches", "b1", "UNKNOWN_SOURCE"], ["raw_records", "rr-b0-1", "DUPLICATE_ID"], ["raw_records", "rr-b1-1", "DEPENDENT_REJECTED"], ["raw_records", "rr-bX-1", "UNKNOWN_BATCH"], ["checkpoints", "cp-b1", "DEPENDENT_REJECTED"]]);
}
// 26. A repeated attempt: tr-1 and tr-2 are both attempt 1 of ingest in run-1 -> tr-2 DUPLICATE_ID; tr-3 is attempt 2 (accepted) and its status is final. Attempts 2, task success 1/1.
W("a repeated attempt of one task is DUPLICATE_ID; attempts count, the last one is final", world({ pipeline_runs: [run("run-1", at(8), at(8, 10), "success")],
  task_runs: [task("tr-1", "run-1", "ingest", "1", "failed"), task("tr-2", "run-1", "ingest", 1, "success"), task("tr-3", "run-1", "ingest", 2, "success")] }),
  { "metrics.runs.runs.run-1.attempts": 2, "metrics.runs.runs.run-1.tasks.ingest.final_status": "success", "metrics.runs.runs.run-1.task_success_rate": "1.000000", "metrics.runs.runs.run-1.attempt_success_rate": "0.500000" }, [["task_runs", "tr-2", "DUPLICATE_ID"]]);
// 27. The partition is the UTC date of event_ts, half-open at midnight. K1 23:59:59Z -> 10-04; K2 10-05 00:00:00Z -> 10-05; K3 "10-05T01:00:00+02:00" = 10-04 23:00Z -> 10-04.
//     Expectations: 10-04 declares 2 (accepted 2 -> 1.000000), 10-05 declares 3 (accepted 1 -> 0.333333). An event at the cutoff instant has freshness 0 s.
W("partitions are UTC dates, half-open at midnight; an offset instant is converted", world({ source_expectations: [{ source_id: "src-a", partition: "2026-10-04", expected_records: 2 }, { source_id: "src-a", partition: "2026-10-05", expected_records: 3 }],
  ingestion_batches: [batch("b1", at(0, 10, 0, 5))], raw_records: [rr("b1", 1, "K1", { event_ts: "2026-10-04T23:59:59Z" }), rr("b1", 2, "K2", { event_ts: "2026-10-05T00:00:00Z" }), rr("b1", 3, "K3", { event_ts: "2026-10-05T01:00:00+02:00" })], checkpoints: [cp("b1", 1, at(0, 15, 0, 5))] }),
  { "metrics.completeness.src-a.2026-10-04.value": "1.000000", "metrics.completeness.src-a.2026-10-04.accepted_records": 2, "metrics.completeness.src-a.2026-10-05.value": "0.333333", "metrics.freshness.src-a.freshness_seconds": 0, "metrics.freshness.src-a.latest_accepted_event_at": "2026-10-05T00:00:00Z" }, []);
// 28. Durations: run-1 600 s and run-2 1200 s succeeded (mean 1800/2/60 = 15.0000 min), run-3 failed after 180 s (3.0000), run-4 failed with no finished_at (no duration, in no group).
W("durations: successful and failed apart, an unfinished run has none", world({ pipeline_runs: [run("run-1", at(8, 15), at(8, 25)), run("run-2", at(9, 15), at(9, 35)), run("run-3", at(10), at(10, 3), "failed"), run("run-4", at(11), null, "failed")] }),
  { "metrics.runs.durations.successful.durations_seconds": [600, 1200], "metrics.runs.durations.successful.mean_minutes": "15.0000", "metrics.runs.durations.failed.count": 1, "metrics.runs.durations.failed.mean_minutes": "3.0000", "metrics.runs.runs.run-4.duration_seconds": null }, []);
// 29. Exact rational rounding at 6 places (ROUND_HALF_UP): 1 of 8 = 0.125000, 1/3 = 0.333333, 2/3 = 0.666667, 1/7 = 0.142857, 7/9 = 0.777778; mean minutes 100 s x3 -> 1.6667.
W("ratios are exact rationals rounded once, half up", world({ source_expectations: [{ source_id: "src-a", partition: "2026-10-01", expected_records: 8 }, { source_id: "src-a", partition: "2026-10-02", expected_records: 3 }, { source_id: "src-a", partition: "2026-10-03", expected_records: 3 }, { source_id: "src-a", partition: "2026-10-04", expected_records: 7 }, { source_id: "src-a", partition: "2026-09-30", expected_records: 9 }],
  ingestion_batches: [batch("b1", at(8))], checkpoints: [cp("b1", 1, at(8, 5))],
  raw_records: [rr("b1", 1, "A1", { event_ts: "2026-10-01T01:00:00Z" }), rr("b1", 2, "B1", { event_ts: "2026-10-02T01:00:00Z" }), rr("b1", 3, "C1", { event_ts: "2026-10-03T01:00:00Z" }), rr("b1", 4, "C2", { event_ts: "2026-10-03T02:00:00Z" }), rr("b1", 5, "D1", { event_ts: "2026-10-04T01:00:00Z" }),
    ...Array.from({ length: 7 }, (_, i) => rr("b1", 6 + i, `E${i}`, { event_ts: "2026-09-30T01:00:00Z" }))],
  pipeline_runs: [run("run-1", at(8), at(8, 1, 40)), run("run-2", at(9), at(9, 1, 40)), run("run-3", at(10), at(10, 1, 40))] }),
  { "metrics.completeness.src-a.2026-10-01.value": "0.125000", "metrics.completeness.src-a.2026-10-02.value": "0.333333", "metrics.completeness.src-a.2026-10-03.value": "0.666667", "metrics.completeness.src-a.2026-10-04.value": "0.142857", "metrics.completeness.src-a.2026-09-30.value": "0.777778", "metrics.runs.durations.successful.mean_minutes": "1.6667" }, []);
// 30. Verified recovery. run-1 failed 08:00 (inc-1 opened 08:10, inc-3 opened 08:20); run-2 succeeded, allowed, published pub-2 at 09:30 but its stored candidate total (5.00) differs
//     from its 10.00 of records -> residual 5.00, so it is NOT a verified recovery; run-3 published pub-3 at 10:30 with total 10.00 -> residual 0.00 -> verified. inc-1 recovers 10:30 - 08:10 = 8400 s = 140.0000 min,
//     closed_at 10:30 with recovery run-3: consistent. inc-3 (08:20) = 7800 s = 130.0000, recorded recovery run-2 (wrong) -> closure_consistent false. inc-2 opens 12:00, no later run: unverified, open, consistent.
//     Mean over the two verified: (8400 + 7800) / 2 / 60 = 135.0000.
{
  const g1 = gated("run-1", at(8), at(8, 5), "failed", [["keys_unique", "critical", 1, 1]]), g2 = gated("run-2", at(9, 20), at(9, 30), "success", [["keys_unique", "critical", 1, 0]]), g3 = gated("run-3", at(10, 20), at(10, 30), "success", [["keys_unique", "critical", 1, 0]]);
  W("verified recovery needs a later successful, allowed, published, reconciled (0.00) run; a drifting candidate is skipped", world({ ingestion_batches: [batch("b1", at(7))], raw_records: [rr("b1", 1, "K1", { event_ts: at(6) })], checkpoints: [cp("b1", 1, at(7, 5))],
    pipeline_runs: [...g1.runs, ...g2.runs, ...g3.runs], task_runs: [...g1.tasks, ...g2.tasks, ...g3.tasks], quality_results: [...g1.qrs, ...g2.qrs, ...g3.qrs],
    publications: [pub("pub-2", "run-2", at(9, 30), at(7), ["b1"]), pub("pub-3", "run-3", at(10, 30), at(7), ["b1"])],
    incidents: [inc("inc-1", "run-1", at(8, 10), "closed", at(10, 30), "run-3"), inc("inc-2", "run-3", at(12), "open", null, null), inc("inc-3", "run-1", at(8, 20), "closed", at(10, 30), "run-2")] }),
    { "metrics.reconciliation.pub-2.residual": "5.00", "metrics.reconciliation.pub-3.residual": "0.00", "metrics.incidents.incidents.inc-1.recovery_run_id": "run-3", "metrics.incidents.incidents.inc-1.recovery_seconds": 8400, "metrics.incidents.incidents.inc-1.recovery_minutes": "140.0000", "metrics.incidents.incidents.inc-1.closure_consistent": true,
      "metrics.incidents.incidents.inc-2.verified": false, "metrics.incidents.incidents.inc-2.recovery_minutes": null, "metrics.incidents.incidents.inc-2.closure_consistent": true, "metrics.incidents.incidents.inc-3.closure_consistent": false, "metrics.incidents.incidents.inc-3.recovery_minutes": "130.0000",
      "metrics.incidents.verified": 2, "metrics.incidents.open": 1, "metrics.incidents.closed": 2, "metrics.incidents.mean_recovery_minutes": "135.0000" }, [], { "pub-2": "5.00", "pub-3": "10.00" });
}
// 31. Money and contract edge cases (one row each, keys K1..K14). Accepted: "12.5", "-0.00", quantity 0. INVALID_FIELD: "12.505", "1e3", "", " 5.00", "5.00\n" (D-09: a trailing
//     newline is not money, in all three implementations), unit_price as a number, quantity true, quantity 2.5, an event_ts without a zone. MISSING_FIELD: amount absent, amount null.
//     So accepted 3, INVALID_FIELD 9, MISSING_FIELD 2, received 14.
{
  const base = (k: string): Row => pay(k);
  const rows: Row[] = [{ ...base("K1"), amount: "12.5" }, { ...base("K2"), amount: "12.505" }, { ...base("K3"), amount: "1e3" }, { ...base("K4"), amount: "" }, { ...base("K5"), amount: " 5.00" }, { ...base("K6"), amount: "5.00\n" }, { ...base("K7"), amount: "-0.00" },
    { ...base("K8"), unit_price: 10 }, { ...base("K9"), quantity: true }, { ...base("K10"), quantity: 2.5 }, { ...base("K11"), quantity: 0 }, { ...base("K12"), event_ts: "2026-10-04T08:00:00" }, (({ amount: _a, ...r }) => r)(base("K13")), { ...base("K14"), amount: null }];
  W("money and contract edges: decimals, exponent, whitespace, bool and fractional quantities, absent and null fields", world({ ingestion_batches: [batch("b1", at(8))], raw_records: rows.map((p, i) => rr("b1", i + 1, `K${i + 1}`, {}, p)), checkpoints: [cp("b1", 1, at(8, 5))] }),
    { [`${S}.received`]: 14, [`${S}.accepted_unique`]: 3, [`${S}.quarantine_by_reason.INVALID_FIELD`]: 9, [`${S}.quarantine_by_reason.MISSING_FIELD`]: 2 }, []);
  // 32. Exact decimal arithmetic: 0.10 + 0.10 + 0.10 + 0.20 = 0.50 and a very large amount stays exact (999999999999.99 + 0.01 = 1000000000000.00).
  const g = gated("run-1", at(9), at(9, 10), "success", [["keys_unique", "critical", 1, 0]]);
  W("money is exact: no binary rounding, no overflow", world({ ingestion_batches: [batch("b1", at(8))], raw_records: [rr("b1", 1, "K1", { amount: "0.10" }), rr("b1", 2, "K2", { amount: "0.10" }), rr("b1", 3, "K3", { amount: "0.10" }), rr("b1", 4, "K4", { amount: "0.20" }), rr("b1", 5, "K5", { amount: "999999999999.99" }), rr("b1", 6, "K6", { amount: "0.01" })],
    checkpoints: [cp("b1", 1, at(8, 5))], pipeline_runs: g.runs, task_runs: g.tasks, quality_results: g.qrs, publications: [pub("pub-1", "run-1", at(9, 10), at(8), ["b1"])] }),
    { "metrics.reconciliation.pub-1.source_total": "1000000000000.50", "metrics.reconciliation.pub-1.published_total": "1000000000000.50", "metrics.reconciliation.pub-1.residual": "0.00" }, []);
}
// 33. Two batches of one source with the same id (D-09, R8-03: a repeated primary key of any entity is DUPLICATE_ID before the row is accepted; this used to pass import in both
//     implementations and be counted twice). The first b1 stays, the repeat is DUPLICATE_ID, and its rows are not counted twice: 1 batch accepted, 1 rejected, 1 row received.
W("a repeated batch_id is DUPLICATE_ID and its rows are not counted twice", world({ ingestion_batches: [batch("b1", at(8)), batch("b1", at(8))], raw_records: [rr("b1", 1, "K1")], checkpoints: [cp("b1", 1, at(8, 5))] }),
  { "ingest.counts.ingestion_batches.accepted": 1, "ingest.counts.ingestion_batches.rejected": 1, [`${S}.received`]: 1, [`${S}.accepted_unique`]: 1 }, [["ingestion_batches", "b1", "DUPLICATE_ID"]]);
// 34. The processing rate: 8 accepted records of the named batch in 12 s = 0.666667 / s; 0 s gives null (zero denominator), never infinity.
{
  const rows = Array.from({ length: 8 }, (_, i) => rr("b1", i + 1, `K${i}`));
  const pm = (s: string | number): Row => ({ source_id: "src-a", batch_id: "b1", measured_seconds: s, hardware: "synthetic", cache_state: "cold" });
  W("processing rate: records over seconds, and null for zero seconds", world({ ingestion_batches: [batch("b1", at(8))], raw_records: rows, checkpoints: [cp("b1", 1, at(8, 5))], processing_measurement: pm("12") }), { "metrics.processing_rate.records_per_second": "0.666667", "metrics.processing_rate.accepted_records": 8, "metrics.processing_rate.measured_seconds": "12" }, []);
  W("processing rate with zero measured seconds is null", world({ ingestion_batches: [batch("b1", at(8))], raw_records: rows, checkpoints: [cp("b1", 1, at(8, 5))], processing_measurement: pm("0") }), { "metrics.processing_rate.records_per_second": null }, []);
}
// 35. Aborted and staged batches are evidence only: their rows exist but count for nothing, and their checkpoint-less status is listed as uncommitted.
W("aborted and staged batches count for nothing", world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(9), "src-a", "aborted"), batch("b3", at(10), "src-a", "staged")], raw_records: [rr("b1", 1, "K1"), rr("b2", 1, "K2"), rr("b3", 1, "K3")], checkpoints: [cp("b1", 1, at(8, 5))] }),
  { [`${S}.received`]: 1, [`${S}.accepted_unique`]: 1, [`${S}.batches.b2.counted`]: false, [`${S}.batches.b2.written_rows`]: 1, [`${S}.batches.b3.status`]: "staged", [`${S}.checkpoint.uncommitted_batches`]: ["b2", "b3"], "metrics.freshness.src-a.last_successful_ingestion_at": at(8, 5) }, []);

// ----------------------------------------------------------------------------------------------------------------------------- the same logic, called directly
// 36. Windows: a batch committed exactly at the cutoff is not yet known (dropped); one second earlier it is known. The window end is exclusive, the start inclusive.
{
  const w = world({ ingestion_batches: [batch("b1", at(8)), batch("b2", at(9))], raw_records: [rr("b1", 1, "K1"), rr("b2", 1, "K2")], checkpoints: [cp("b1", 1, at(8, 5)), cp("b2", 2, at(9, 5))], pipeline_runs: [run("run-1", at(8), at(8, 10)), run("run-2", at(9), at(9, 10))] });
  const r = runPipeline(w);
  const n = (o: Row): number[] => { const s = computeWindow(r.imported.accepted as any, r.imported.rejected, r.params, o); return [Object.keys(s.metrics.ingestion.sources["src-a"].batches).length, Object.keys(s.metrics.runs.runs).length]; }; // eslint-disable-line @typescript-eslint/no-explicit-any
  worlds++;
  eq("window: [08:00, 09:00) holds the run and batch starting at 08:00 and not the one starting at 09:00", n({ from: at(8), to: at(9) }), [1, 1]);
  eq("window: [08:00, 09:00:01) holds both starts", n({ from: at(8), to: at(9, 0, 1) }), [2, 2]);
  eq("window: [08:00:01, 09:00) holds neither start", n({ from: at(8, 0, 1), to: at(9) }), [0, 0]);
  eq("cutoff 09:05:00 drops b2 (committed exactly then); 09:05:01 keeps it", [n({ cutoff: at(9, 5) })[0], n({ cutoff: at(9, 5, 1) })[0]], [1, 2]);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: half-open windows and the cutoff (6 expectations)`);
}
// 37. Backfill ranges: touching is not overlap, partition alignment, order, and the console's decision.
{
  worlds++;
  eq("ranges: [a,b) and [b,c) touch and do not overlap; [a,c) and [b,d) do", [rangesOverlap(at(0), at(0, 0, 0, 5), at(0, 0, 0, 5), at(0, 0, 0, 6)), rangesOverlap(at(0), at(0, 0, 0, 6), at(0, 0, 0, 5), at(0, 0, 0, 7))], [false, true]);
  const err = (a: string, b: string): string => { try { checkRange(a, b); return "ok"; } catch (e) { return e instanceof DomainError ? e.code : "?"; } };
  eq("checkRange: aligned and ordered, else PARTITION_ALIGNMENT / INVALID_RANGE", [err("2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z"), err("2026-09-01T12:00:00Z", "2026-09-03T00:00:00Z"), err("2026-09-03T00:00:00Z", "2026-09-03T00:00:00Z"), err("2026-09-04T00:00:00Z", "2026-09-03T00:00:00Z")], ["ok", "PARTITION_ALIGNMENT", "INVALID_RANGE", "INVALID_RANGE"]);
  const acc = [bf("bf-1", "src-a", "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z", [true, true, true])];
  eq("the console: overlap names the blocking request; a touching range is accepted with its partitions; a malformed instant is INVALID_RANGE", [decideBackfill(acc, { source_id: "src-a", start_at: "2026-09-03T00:00:00Z", end_at: "2026-09-05T00:00:00Z" }).overlaps_with,
    decideBackfill(acc, { source_id: "src-a", start_at: "2026-09-04T00:00:00Z", end_at: "2026-09-06T00:00:00Z" }).partitions, decideBackfill(acc, { source_id: "src-a", start_at: "tomorrow", end_at: "later" }).code], ["bf-1", ["2026-09-04", "2026-09-05"], "INVALID_RANGE"]);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: backfill ranges and the console's decision (3 expectations)`);
}
// 38. Pagination: a retry waits exactly retry_after; a repeated cursor (A->B->A, or a self loop) stops with CURSOR_LOOP; too many 429 in a row is RETRY_EXHAUSTED.
{
  worlds++;
  let clock = parseTs(at(8));
  const sleeps: number[] = [];
  const pages: Record<string, Page[]> = { c0: [{ status: 429, records: [], next_cursor: null, retry_after_seconds: 30 }, { status: 200, records: [{ n: 1 }], next_cursor: "c1", retry_after_seconds: null }], c1: [{ status: 200, records: [{ n: 2 }], next_cursor: null, retry_after_seconds: null }] };
  const seen: Record<string, number> = {};
  const res = fetchAll((c) => pages[c]![seen[c] = (seen[c] ?? -1) + 1]!, "c0", () => clock, (s) => { sleeps.push(s); clock += BigInt(s) * 1_000_000n; });
  eq("fetchAll: a 429 with retry-after 30 sleeps exactly 30 s, then both pages arrive", [sleeps, res.records, res.cursors, Number((res.calls[1]![1] - res.calls[0]![1]) / 1_000_000n)], [[30], [{ n: 1 }, { n: 2 }], ["c0", "c1"], 30]);
  const loop = (map: Record<string, string | null>): string => { try { fetchAll((c) => ({ status: 200, records: [], next_cursor: map[c] ?? null, retry_after_seconds: null }), "A", () => 0n, () => undefined); return "ok"; } catch (e) { return e instanceof DomainError ? e.code : "?"; } };
  eq("fetchAll: A->B->A and A->A are CURSOR_LOOP; A->B->C ends", [loop({ A: "B", B: "A" }), loop({ A: "A" }), loop({ A: "B", B: "C" })], ["CURSOR_LOOP", "CURSOR_LOOP", "ok"]);
  const ex = (() => { try { fetchAll(() => ({ status: 429, records: [], next_cursor: null, retry_after_seconds: 1 }), "A", () => 0n, () => undefined); return "ok"; } catch (e) { return e instanceof DomainError ? e.code : "?"; } })();
  eq("fetchAll: six 429 in a row is RETRY_EXHAUSTED", ex, "RETRY_EXHAUSTED");
  const soon = (secs: number): string => { try { checkRetryAllowed(at(8), 30, at(8, 0, secs)); return "allowed"; } catch (e) { return e instanceof DomainError ? `${e.code}:${e.details["remaining_seconds"]}` : "?"; } };
  eq("checkRetryAllowed: 29 s after a 30 s hint is RETRY_TOO_SOON with 1 s left; exactly 30 s is allowed", [soon(29), soon(30), soon(0)], ["RETRY_TOO_SOON:1", "allowed", "RETRY_TOO_SOON:30"]);
  eq("checkCursorProgress: only a new cursor passes", [(() => { try { checkCursorProgress("a", "b", new Set(["a"])); return "ok"; } catch { return "loop"; } })(), (() => { try { checkCursorProgress("b", "a", new Set(["a", "b"])); return "ok"; } catch { return "loop"; } })()], ["ok", "loop"]);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: pagination, retry-after and cursor loops (5 expectations)`);
}
// 39. Hashes: key order and spacing do not change payload_hash; content_hash sorts; a change of one character changes the hash.
{
  worlds++;
  eq("payload_hash is independent of key order and of non-ASCII spelling", [payloadHash({ a: 1, b: "x" }) === payloadHash({ b: "x", a: 1 }), payloadHash({ a: "é" }) === payloadHash(JSON.parse('{"a":"\\u00e9"}')), payloadHash({ a: 1 }) === payloadHash({ a: 2 })], [true, true, false]);
  eq("content_hash sorts its inputs: order does not matter", contentHash(["b", "a", "c"]) === contentHash(["c", "b", "a"]), true);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: hashes (2 expectations)`);
}
// 40. Redaction: every secret span is replaced, a clean line is unchanged, a value under a secret-named key is replaced whole, and a line that still matches is withheld.
{
  worlds++;
  const lines = ["fetch ok authorization: Bearer abcdef1234567890xyz", "connect postgres://lab:hunter2@db:5432/x", "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789", "password: 'p@ss w0rd'", "key AKIAABCDEFGHIJKLMNOP leaked", "batch b-0001 committed 12 rows in 3 ms"];
  const out = lines.map(safeLine);
  eq("redaction: five secret lines are scrubbed and verified clean, the sixth is untouched", [out.slice(0, 5).map(containsSecret), out[5] === lines[5], out.slice(0, 5).every((l) => l.includes("[REDACTED]") || l === WITHHELD)], [[false, false, false, false, false], true, true]);
  eq("redaction: the key name and surrounding text survive, the value does not", [redactText("db password=s3cret end"), redactText("postgres://u:pw@h/x")], ["db password=[REDACTED] end", "postgres://u:[REDACTED]@h/x"]);
  eq("redactValue replaces the value of a secret-named key whole, walks containers and scrubs strings", redactValue({ user: "a", api_key: 12345, nested: [{ note: "Bearer abcdefghij1234" }] }), { user: "a", api_key: "[REDACTED]", nested: [{ note: "[REDACTED]" }] });
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: secret redaction (3 expectations)`);
}
// 41. The gate what-if (the screens' fault injection): forcing a critical check to fail blocks and keeps the pointer; forcing only the warning does not block.
{
  worlds++;
  const results = [qr("q1", "t", "keys_unique", "critical", 5, 0), qr("q2", "t", "relationships_intact", "critical", 5, 0), qr("q3", "t", "completeness_vs_expectation", "warning", 5, 0)];
  const a = gateWhatIf(results, { keys_unique: 2 }, true, "pub-9", "pub-10"), b = gateWhatIf(results, { completeness_vs_expectation: 4 }, true, "pub-9", "pub-10"), c = gateWhatIf(results, {}, false, "pub-9", null);
  eq("what-if: a forced critical failure blocks, fails the run and keeps the pointer; a forced warning allows and moves it; no candidate keeps it", [[a.gate.decision, a.run_status, a.pointer_after], [b.gate.decision, b.run_status, b.pointer_after], c.pointer_after], [["blocked", "failed", "pub-9"], ["allowed", "success", "pub-10"], "pub-9"]);
  eq("gate.decide is unchanged by the order results arrive in", canon(decide(results)) === canon(decide([...results].reverse())), true);
  eq("retry advice by reason: schema change refetches after a bump; a negative quantity is corrected and replayed; an unknown op needs the source", [retryAdvice("SCHEMA_CHANGED").disposition, retryAdvice("NEGATIVE_QUANTITY").disposition, retryAdvice("UNKNOWN_OP").disposition], ["refetch-after-bump", "correct-and-replay", "no-retry-source-fix"]);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: gate what-if, decide order, retry advice (3 expectations)`);
}

// 44. D-09 divergence cases, read as TEXT (3.0 and 9007199254740993 must keep their lexemes): the verdict of every case equals the table that Python, the PostgreSQL reference and
//     tests/reference_check.py also satisfy (tests/fixtures/divergence/cases.json).
{
  worlds++;
  const doc = parseJsonExact(readFileSync(new URL("../../tests/fixtures/divergence/cases.json", import.meta.url), "utf8")) as Row;
  const started: Record<string, string> = Object.fromEntries((doc["batches"] as Row[]).map((b) => [b["batch_id"], b["started_at"]]));
  const bad: string[] = [];
  for (const c of doc["cases"] as Row[]) {
    const why = contractReason(c["payload"], started[c["batch"]], doc["cutoff"]);
    if ((why === null ? "accepted" : "quarantined") !== c["disposition"] || why !== c["reason"]) bad.push(`${c["id"]}: ${why}`);
  }
  eq(`divergence: all ${(doc["cases"] as Row[]).length} cases classified as the shared table says`, bad, []);
  const by = Object.fromEntries((doc["cases"] as Row[]).map((c) => [c["id"], c]));
  eq("divergence: 3.0 and 1e2 are not integers, 9007199254740993 is kept exact and refused, 2**53 is accepted", [by["quantity-float-3.0"].payload.quantity.lexeme, by["quantity-exponent"].payload.quantity.lexeme, by["quantity-big"].payload.quantity.lexeme, by["ok-quantity-2-53"].payload.quantity], ["3.0", "1e2", "9007199254740993", 9007199254740992]);
  const rowsOf = (cases: Row[]): Row[] => cases.map((c, i) => ({ raw_record_id: `rr-d-${String(i).padStart(3, "0")}`, batch_id: c["batch"], source_key: c["payload"]?.record_id ?? c["source_key"], payload_hash: "h", payload_json: c["payload"] }));
  const batches = (doc["batches"] as Row[]).map((b) => batch(b["batch_id"], b["started_at"], "src-div"));
  const res = runPipeline(world({ source_contracts: [src("src-div")], ingestion_batches: batches, raw_records: rowsOf(doc["cases"]), checkpoints: (doc["batches"] as Row[]).map((b) => cp(b["batch_id"], b["version_number"], b["committed_at"], "src-div", b["committed_cursor"])) }));
  const facts = res.facts;
  const wrong = (doc["cases"] as Row[]).filter((c, i) => facts.disposition.get(`rr-d-${String(i).padStart(3, "0")}`)!.kind !== c["disposition"]).map((c) => c["id"]);
  eq("divergence: the whole pipeline (not only contractReason) agrees, and nothing is rejected at import", [wrong, res.golden.ingest.rejected_records.length], [[], 0]);
  eq("divergence: the sub-microsecond event is truncated to .999999, never rounded up a second", [isoZ(by["ok-sub-microsecond"].payload.event_ts), by["ok-sub-microsecond"].event_at], ["2026-10-04T08:00:00.999999Z", "2026-10-04T08:00:00.999999Z"]);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: the shared divergence cases (${(doc["cases"] as Row[]).length + 4} expectations)`);
}
// 45. D-09 rules: a payload that is not an object, a future-dated row against a stale source, severity, overlap against active requests, duplicate keys of every entity.
{
  worlds++;
  eq("moneyAmount guards a payload that is not an object (it used to be a TypeError in the mirror and an AttributeError in Python)", [["x"], "12.00", 12, null, true].map((p) => String(moneyAmount(p).n)), ["0", "0", "0", "0", "0"]);
  const stale = W("a future-dated row is quarantined and cannot make a stale source look fresh", world({ ingestion_batches: [batch("b1", at(10))],
    raw_records: [rr("b1", 1, "K1", { event_ts: at(8) }), rr("b1", 2, "K2", { event_ts: "2030-01-01T00:00:00Z" })], checkpoints: [cp("b1", 1, at(10, 5))] }),
    { [`${S}.accepted_unique`]: 1, [`${S}.quarantined`]: 1, [`${S}.quarantine_by_reason.EVENT_IN_FUTURE`]: 1, "metrics.freshness.src-a.latest_accepted_event_at": at(8), "metrics.freshness.src-a.freshness_seconds": 57600, "metrics.freshness.src-a.freshness_reason": null }, []);
  void stale;
  W("freshness is null with a reason when nothing is accepted, never negative", world({ ingestion_batches: [batch("b1", at(10))], raw_records: [rr("b1", 1, "K1", { event_ts: "2030-01-01T00:00:00Z" })], checkpoints: [cp("b1", 1, at(10, 5))] }),
    { "metrics.freshness.src-a.freshness_seconds": null, "metrics.freshness.src-a.freshness_reason": "NO_ACCEPTED_EVENT", "metrics.freshness.src-a.ingestion_age_seconds": 50100 }, []);
  W("the cutoff binds when it is earlier than the batch's arrival", world({ cutoff: at(9), as_of: at(9), ingestion_batches: [batch("b1", at(12))], raw_records: [rr("b1", 1, "K1", { event_ts: at(8) }), rr("b1", 2, "K2", { event_ts: at(10) })], checkpoints: [cp("b1", 1, at(12, 5))] }),
    { [`${S}.accepted_unique`]: 1, [`${S}.quarantine_by_reason.EVENT_IN_FUTURE`]: 1 }, []);
  const q1 = qr("qr-1", "tr-1", "keys_unique", "Critical", 1, 0);
  const g = gated("run-1", at(9), at(9, 10), "success", [["keys_unique", "critical", 1, 0]]);
  W("severity is validated on import: an unknown severity is INVALID_FIELD and the gate left with no critical result blocks", world({ ingestion_batches: [batch("b1", at(8))], raw_records: [rr("b1", 1, "K1")], checkpoints: [cp("b1", 1, at(8, 5))],
    pipeline_runs: g.runs, task_runs: g.tasks, quality_results: [{ ...g.qrs[0], severity: "Critical" }] }), { "metrics.quality_gate.run-1.decision": "blocked", "ingest.counts.quality_results.rejected": 1 }, [["quality_results", g.qrs[0]!["quality_result_id"], "INVALID_FIELD"]]);
  void q1;
  const mk = (i: number, a: string, b: string, status: string, extra: Row = {}): Row => ({ ...bf(`bf-${i}`, "src-a", `2026-09-${a}T00:00:00Z`, `2026-09-${b}T00:00:00Z`, [false]), status, ...extra });
  const hit = (acc: Row[], req: Row, history = false): string | null => findOverlap(acc, req, history)?.["backfill_id"] ?? null;
  eq("overlap is judged against requested or running requests only", ["requested", "running", "partial", "complete", "cancelled"].map((st) => hit([mk(1, "01", "03", st)], mk(2, "02", "04", "requested"))), ["bf-1", "bf-1", null, null, null]);
  const victim = mk(1, "01", "03", "partial", { requested_at: "2026-08-30T10:00:00Z", settled_at: "2026-08-30T12:00:00Z" });
  eq("history: refused while the victim was running, accepted once it settled; a clockless snapshot counts every earlier request", [hit([victim], mk(2, "02", "03", "requested", { requested_at: "2026-08-30T11:00:00Z" }), true), hit([victim], mk(3, "02", "03", "requested", { requested_at: "2026-08-30T12:00:00Z" }), true),
    hit([mk(1, "01", "03", "partial")], mk(4, "02", "03", "requested"), true)], ["bf-1", null, "bf-1"]);
  const dup = (entity: string, row: Row, extra: Row = {}): unknown => rej(runPipeline(world({ ...extra, [entity]: [row, { ...row }] }))).filter((r: any) => r[0] === entity); // eslint-disable-line @typescript-eslint/no-explicit-any
  eq("a repeated primary key of any entity is DUPLICATE_ID: source, run, publication, incident, model", [
    dup("source_contracts", src()), dup("pipeline_runs", run("run-1", at(8), at(8, 5)))].map((x) => (x as unknown[][]).map((r) => r[2])), [["DUPLICATE_ID"], ["DUPLICATE_ID"]]);
  const cpRepeat = runPipeline(world({ ingestion_batches: [batch("b1", at(8))], raw_records: [rr("b1", 1, "K1")], checkpoints: [cp("b1", 1, at(8, 5)), cp("b1", 1, at(8, 5))] }));
  eq("a repeated checkpoint id is DUPLICATE_ID and does not poison its batch", [rej(cpRepeat), cpRepeat.golden.metrics.ingestion.overall.accepted_unique], [[["checkpoints", "cp-b1", "DUPLICATE_ID"]], 1]);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: D-09 rules (see above)`);
}
// 46. D-09 fetch sessions: a loop is a repeated cursor inside one session; a new session fetches a cursor again as a refetch; a stale source's re-poll of the last committed cursor is a refetch.
{
  worlds++;
  const h = (...pages: [string, string, string | null][]): Fetched[] => pages.map(([session, cursor, next_cursor]) => ({ session, cursor, next_cursor, status: "ok" }));
  const j = (history: Fetched[], last: string | null, session: string, cursor: string, next: string | null): string => { try { return judgeFetch(history, last, session, cursor, next); } catch (e) { return e instanceof DomainError ? e.code : "?"; } };
  const hist = h(["s", "A", "B"], ["s", "B", "C"]);
  eq("judgeFetch: ok for a new cursor, refetch for a cursor fetched in another session, CURSOR_LOOP for a repeat inside the session", [j([], null, "s", "A", "B"), j(hist, "C", "t", "A", "B"), j(hist, "C", "s", "C", "A"), j(hist, "C", "s", "C", "B"), j(hist, "C", "s", "C", "C"), j(hist, "C", "s", "A", "D")],
    ["ok", "refetch", "CURSOR_LOOP", "CURSOR_LOOP", "CURSOR_LOOP", "CURSOR_LOOP"]);
  eq("judgeFetch: the first page of a new session that re-polls the last committed cursor and points at itself is a refetch; the same page elsewhere, or twice in a session, is a loop", [j(hist, "C", "t", "C", "C"), j(hist, "C", "t", "Z", "Z"),
    j([...hist, { session: "t", cursor: "C", next_cursor: "C", status: "refetch" }], "C", "t", "C", "C"), j([{ session: "s", cursor: "A", next_cursor: "B", status: "rate_limited" }], null, "s", "A", "B")], ["refetch", "CURSOR_LOOP", "CURSOR_LOOP", "ok"]);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: fetch sessions (10 expectations)`);
}
// 47. D-09 the gate's two new checks: scope_complete and the late events no publication includes.
{
  worlds++;
  const committed: [string, string][] = [["b1", at(10)], ["b2", at(11)], ["b3", at(12)]];
  eq("scopeComplete: complete, the omit attack, a declared scope, and a batch committed at the run's start belongs to the next run", [scopeComplete(committed, ["b1", "b2", "b3"], null, at(13)), scopeComplete(committed, ["b1", "b3"], null, at(13)), scopeComplete(committed, ["b3"], at(11, 30), at(13)), scopeComplete(committed, ["b1"], null, at(11))],
    [[3, []], [3, ["b2"]], [1, []], [1, []]]);
  const acc = (key: string, batchId: string, event: string, arrival: string): Accepted => ({ source_id: "s", batch_id: batchId, key, event_at: event, arrival, raw_record_id: "rr", payload_hash: "h", amount: { n: 0n, d: 1n }, deleted_in: null });
  const pubs: Row[] = [pub("pub-1", "run-1", at(11), at(9), ["b1"], ["s"])];
  const late = acc("K3", "b3", at(8, 30), at(12)), fresh = acc("K4", "b4", at(11, 30), at(12));
  eq("pendingLateEvents: late and unpublished; not before the run started; included by a later publication", [pendingLateEvents([late, fresh], pubs, at(13)).map((e) => e.source_key), pendingLateEvents([late, fresh], pubs, at(12)).length,
    pendingLateEvents([late, fresh], [...pubs, pub("pub-2", "run-2", at(12, 30), at(10), ["b1", "b3"], ["s"])], at(13)).length], [["K3"], 0, 0]);
  console.log(`OK       world ${String(worlds).padStart(2, "0")}: the gate's two new checks (5 expectations)`);
}

if (process.env["REVIEW_DUMP"]) writeFileSync(process.env["REVIEW_DUMP"], JSON.stringify(dump));
if (failures) { console.log(`FAILED (${failures} of ${checks} checks, ${worlds} worlds)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks, ${worlds} worlds)`);
