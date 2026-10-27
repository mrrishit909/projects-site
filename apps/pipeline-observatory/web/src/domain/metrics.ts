// The metrics tree (D-P8-07) in the exact key nesting of expected.json, computed from accepted entity rows. `compute` takes the rows that passed
// import validation and the rejected rows; `runPipeline` (pipeline.ts) does both from an inputs.json-shaped object. Every ratio is an exact rational
// rendered once (6 places, minutes 4 places), money is an exact decimal (2 places), null means unknown or a zero denominator. No float anywhere.
import * as gateMod from "./gate";
import { ACCEPTED, DELETED, DUPLICATE, QUARANTINED, classifyRows, moneyAmount, type Disposition } from "./classify";
import { CONTRACT_VERSION, ENTITIES, type Row } from "./contract";
import { add, m4, p6, ratio, ZERO, decFr, type Fr } from "./num";
import { sortedBy, sortedEntries, sortedStrings } from "./py";
import { lateEvents, meanMinutes, publicationView, recoveryMinutes, reconcile, verifiedRecovery, type Accepted } from "./reconcile";
import { dayPartitions, isoZ, parseTs, secondsBetween, utcDate } from "./time";
import { validateImport, type ImportResult, type Rejected } from "./ingest";
import { restrict, restrictExpectations } from "./scope";
import { pyInt } from "./py";

const INF = 1_000_000_000;
export type Acc = Record<string, Row[]>;
export interface Facts {
  committed: Row[]; raws: Map<string, Row[]>; cpByBatch: Map<string, Row>; disposition: Map<string, Disposition>; accepted: Accepted[];
  acceptedByBatch: Map<string, Accepted[]>; amounts: Map<string, Fr>; derivedReasons: Map<string, string[]>;
}
export interface Params {
  contract_version: unknown; as_of: string; cutoff: string; business_total_field?: string; source_expectations: Row[]; processing_measurement?: Row | null;
  /** publication_id -> total of the stored published table, which replaces the sum of the accepted records in the reconciliation. */
  published_totals?: Record<string, Fr> | null;
}

/** Classify every raw row of every committed batch (D-01). Batches are applied per source in checkpoint-version order (the order they committed in),
 * falling back to (started_at, batch_id); a batch with a schema_version other than its source contract's is quarantined whole. A row dated after its
 * batch's started_at (its arrival) or after `cutoff` is quarantined EVENT_IN_FUTURE (D-09). */
export function derive(acc: Acc, totf = "amount", cutoff: unknown = null): Facts {
  const cpByBatch = new Map<string, Row>(acc["checkpoints"]!.map((c) => [c["batch_id"], c]));
  const contractSchema = new Map<string, unknown>(acc["source_contracts"]!.map((s) => [s["source_id"], s["schema_version"]]));
  const committed = sortedBy(acc["ingestion_batches"]!.filter((b) => b["status"] === "committed"),
    (b) => [cpByBatch.has(b["batch_id"]) ? (cpByBatch.get(b["batch_id"])!["version_number"] as number) : INF, parseTs(b["started_at"]), b["batch_id"] as string]);
  const raws = new Map<string, Row[]>();
  for (const r of acc["raw_records"]!) (raws.get(r["batch_id"]) ?? raws.set(r["batch_id"], []).get(r["batch_id"])!).push(r);
  for (const rows of raws.values()) rows.sort((a, b) => (a["raw_record_id"] < b["raw_record_id"] ? -1 : a["raw_record_id"] > b["raw_record_id"] ? 1 : 0));
  const disposition = new Map<string, Disposition>();
  const keys = new Map<string, Set<unknown>>(), deleted = new Map<string, Set<unknown>>();
  const accepted: Accepted[] = [];
  const byKey = new Map<string, Accepted>();
  const acceptedByBatch = new Map<string, Accepted[]>();
  for (const b of committed) {
    const sid = b["source_id"] as string;
    const bv = b["schema_version"];
    const schemaOk = bv === null || bv === undefined || bv === contractSchema.get(sid);
    const rows = raws.get(b["batch_id"]) ?? [];
    for (const d of classifyRows(rows, keys.get(sid) ?? keys.set(sid, new Set()).get(sid)!, deleted.get(sid) ?? deleted.set(sid, new Set()).get(sid)!, schemaOk, b["started_at"], cutoff)) disposition.set(d.raw_record_id, d);
    const cp = cpByBatch.get(b["batch_id"]);
    for (const r of rows) {
      const d = disposition.get(r["raw_record_id"])!;
      if (d.kind === ACCEPTED) {
        const a: Accepted = { source_id: sid, batch_id: b["batch_id"], key: r["source_key"], event_at: r["payload_json"]["event_ts"], arrival: cp ? cp["committed_at"] : null,
          raw_record_id: r["raw_record_id"], payload_hash: r["payload_hash"], amount: moneyAmount(r["payload_json"], totf), deleted_in: null };
        accepted.push(a);
        (acceptedByBatch.get(a.batch_id) ?? acceptedByBatch.set(a.batch_id, []).get(a.batch_id)!).push(a);
        byKey.set(`${sid}\u0000${String(a.key)}`, a);
      } else if (d.kind === DELETED && byKey.has(`${sid}\u0000${String(r["source_key"])}`)) byKey.get(`${sid}\u0000${String(r["source_key"])}`)!.deleted_in = b["batch_id"];
    }
  }
  const amounts = new Map<string, Fr>();
  for (const b of committed) for (const r of raws.get(b["batch_id"]) ?? []) amounts.set(r["raw_record_id"], moneyAmount(r["payload_json"], totf));
  const derivedReasons = new Map<string, string[]>();
  for (const b of committed) derivedReasons.set(b["batch_id"], sortedStrings((raws.get(b["batch_id"]) ?? []).filter((r) => disposition.get(r["raw_record_id"])!.kind === QUARANTINED).map((r) => disposition.get(r["raw_record_id"])!.reason!)));
  return { committed, raws, cpByBatch, disposition, accepted, acceptedByBatch, amounts, derivedReasons };
}

function ingestion(acc: Acc, f: Facts): Row {
  const quarRows = new Map<string, Row[]>();
  for (const q of acc["quarantine_records"]!) (quarRows.get(q["batch_id"]) ?? quarRows.set(q["batch_id"], []).get(q["batch_id"])!).push(q);
  const sources: Row = {};
  let tot = [0, 0, 0, 0];
  for (const s of sortedBy(acc["source_contracts"]!, (s) => [s["source_id"] as string])) {
    const sid = s["source_id"] as string;
    const batches: Row = {};
    let rec = 0, nacc = 0, dup = 0, qua = 0;
    const byReason: Record<string, number> = {};
    for (const b of acc["ingestion_batches"]!) {
      if (b["source_id"] !== sid) continue;
      const rows = f.raws.get(b["batch_id"]) ?? [];
      if (b["status"] !== "committed") {
        batches[b["batch_id"]] = { status: b["status"], counted: false, written_rows: rows.length, received: 0, accepted_unique: 0, duplicate: 0, quarantined: 0, rejection_rate: null, duplicate_rate: null, quarantine_rows_match: true };
        continue;
      }
      const kinds = rows.map((r) => f.disposition.get(r["raw_record_id"])!.kind);
      const n = rows.length, a_ = kinds.filter((k) => k === ACCEPTED).length, d_ = kinds.filter((k) => k === DUPLICATE).length, q_ = kinds.filter((k) => k === QUARANTINED).length;
      const want = sortedStrings((quarRows.get(b["batch_id"]) ?? []).map((q) => q["reason_code"] as string));
      const have = f.derivedReasons.get(b["batch_id"])!;
      batches[b["batch_id"]] = { status: "committed", counted: true, written_rows: n, received: n, accepted_unique: a_, duplicate: d_, quarantined: q_, rejection_rate: p6(ratio(q_, n)), duplicate_rate: p6(ratio(d_, n)),
        quarantine_rows_match: have.length === want.length && have.every((x, i) => x === want[i]) };
      rec += n; nacc += a_; dup += d_; qua += q_;
      for (const reason of have) byReason[reason] = (byReason[reason] ?? 0) + 1;
    }
    const qkeys = new Set<unknown>();
    for (const b of f.committed) if (b["source_id"] === sid) for (const r of f.raws.get(b["batch_id"]) ?? []) if (f.disposition.get(r["raw_record_id"])!.kind === QUARANTINED && r["source_key"] !== null && r["source_key"] !== undefined) qkeys.add(r["source_key"]);
    const cps = sortedBy(f.committed.filter((b) => b["source_id"] === sid && f.cpByBatch.has(b["batch_id"])).map((b) => f.cpByBatch.get(b["batch_id"])!), (c) => [c["version_number"] as number]);
    const last = cps.length ? cps[cps.length - 1]! : null;
    const unc = sortedStrings(acc["ingestion_batches"]!.filter((b) => b["source_id"] === sid && b["status"] !== "committed").map((b) => b["batch_id"] as string));
    sources[sid] = { batches, received: rec, accepted_unique: nacc, duplicate: dup, quarantined: qua, quarantined_distinct_keys: qkeys.size, rejection_rate: p6(ratio(qua, rec)), duplicate_rate: p6(ratio(dup, rec)),
      quarantine_by_reason: Object.fromEntries(sortedEntries(byReason)),
      checkpoint: { committed_version: last ? last["version_number"] : null, committed_cursor: last ? last["committed_cursor"] : null, committed_batch_id: last ? last["batch_id"] : null,
        uncommitted_batches: unc, uncommitted_batches_with_checkpoint: unc.filter((u) => f.cpByBatch.has(u)).length } };
    tot = [tot[0]! + rec, tot[1]! + nacc, tot[2]! + dup, tot[3]! + qua];
  }
  return { sources, overall: { received: tot[0], accepted_unique: tot[1], duplicate: tot[2], quarantined: tot[3], rejection_rate: p6(ratio(tot[3]!, tot[0]!)), duplicate_rate: p6(ratio(tot[2]!, tot[0]!)) } };
}

const maxInstant = (xs: string[]): string | null => { let best: string | null = null; for (const x of xs) if (best === null || parseTs(x) > parseTs(best)) best = x; return best; };
function freshness(acc: Acc, f: Facts, cutoff: string): Row {
  const out: Row = {};
  for (const s of sortedBy(acc["source_contracts"]!, (s) => [s["source_id"] as string])) {
    const sid = s["source_id"] as string;
    const le = maxInstant(f.accepted.filter((a) => a.source_id === sid).map((a) => a.event_at));          // freshness: cutoff - latest accepted source event
    const li = maxInstant(f.committed.filter((b) => b["source_id"] === sid && f.cpByBatch.has(b["batch_id"])).map((b) => f.cpByBatch.get(b["batch_id"])!["committed_at"]));   // ingestion age: cutoff - last committed batch (D-P8-03)
    out[sid] = { latest_accepted_event_at: isoZ(le), freshness_seconds: le ? secondsBetween(le, cutoff) : null, freshness_reason: le ? null : "NO_ACCEPTED_EVENT", last_successful_ingestion_at: isoZ(li), ingestion_age_seconds: li ? secondsBetween(li, cutoff) : null };
  }
  return out;
}
function completeness(expectations: Row[], f: Facts): Row {
  const counts = new Map<string, number>();
  for (const a of f.accepted) { const k = `${a.source_id}\u0000${utcDate(a.event_at)}`; counts.set(k, (counts.get(k) ?? 0) + 1); }
  const out: Row = {};
  for (const x of expectations) {
    const n = counts.get(`${x["source_id"]}\u0000${x["partition"]}`) ?? 0;
    (out[x["source_id"]] ??= {})[x["partition"]] = { expected_records: x["expected_records"], accepted_records: n, value: p6(ratio(n, x["expected_records"])) };
  }
  return out;
}
function runsBlock(acc: Acc): Row {
  const tasks = new Map<string, Map<string, Row[]>>();
  const flat = new Map<string, Row[]>();
  for (const t of acc["task_runs"]!) {
    const byName = tasks.get(t["run_id"]) ?? tasks.set(t["run_id"], new Map()).get(t["run_id"])!;
    (byName.get(t["task_name"]) ?? byName.set(t["task_name"], []).get(t["task_name"])!).push(t);
    (flat.get(t["run_id"]) ?? flat.set(t["run_id"], []).get(t["run_id"])!).push(t);
  }
  const runs: Row = {};
  let total = [0, 0, 0, 0];
  const durations: Record<string, number[]> = { success: [], failed: [] };
  for (const run of sortedBy(acc["pipeline_runs"]!, (r) => [r["run_id"] as string])) {
    const rid = run["run_id"] as string;
    const perTask: Row = {};
    for (const [name, attempts] of sortedEntries(Object.fromEntries(tasks.get(rid) ?? []))) {
      const sorted = sortedBy(attempts as Row[], (t) => [pyInt(t["attempt"])]);
      perTask[name] = { attempts: sorted.length, final_status: sorted[sorted.length - 1]!["status"] };
    }
    const vals = Object.values(perTask) as Row[];
    const terminal = vals.filter((v) => v["final_status"] === "success" || v["final_status"] === "failed");
    const ok = terminal.filter((v) => v["final_status"] === "success").length;
    const nAttempts = vals.reduce((s, v) => s + (v["attempts"] as number), 0);
    const okAttempts = (flat.get(rid) ?? []).filter((t) => t["status"] === "success").length;
    const d = run["finished_at"] ? secondsBetween(run["started_at"], run["finished_at"]) : null;
    if (d !== null && run["status"] in durations) durations[run["status"]]!.push(d);
    runs[rid] = { status: run["status"], duration_seconds: d, tasks: perTask, tasks_terminal: terminal.length, tasks_successful: ok, task_success_rate: p6(ratio(ok, terminal.length)),
      attempts: nAttempts, attempts_successful: okAttempts, attempt_success_rate: p6(ratio(okAttempts, nAttempts)) };
    total = [total[0]! + terminal.length, total[1]! + ok, total[2]! + nAttempts, total[3]! + okAttempts];
  }
  const group = (ds: number[]): Row => ({ count: ds.length, durations_seconds: [...ds].sort((a, b) => a - b), mean_minutes: m4(ratio(ds.reduce((a, b) => a + b, 0), 60 * ds.length)) });
  return { runs, overall: { tasks_terminal: total[0], tasks_successful: total[1], task_success_rate: p6(ratio(total[1]!, total[0]!)), attempts: total[2], attempts_successful: total[3], attempt_success_rate: p6(ratio(total[3]!, total[2]!)) },
    durations: { successful: group(durations["success"]!), failed: group(durations["failed"]!) } };
}
export function gates(acc: Acc): Record<string, gateMod.GateDecision> {
  const runOf = new Map<string, string>(acc["task_runs"]!.map((t) => [t["task_run_id"], t["run_id"]]));
  const byRun = new Map<string, Row[]>();
  for (const q of acc["quality_results"]!) { const r = runOf.get(q["task_run_id"])!; (byRun.get(r) ?? byRun.set(r, []).get(r)!).push(q); }
  const out: Record<string, gateMod.GateDecision> = {};
  for (const run of sortedBy(acc["pipeline_runs"]!, (r) => [r["run_id"] as string])) out[run["run_id"]] = gateMod.decide(byRun.get(run["run_id"]) ?? []);
  return out;
}
export interface Scope { inc: string[]; pubd: Accepted[]; srcRows: [string, Fr][]; removed: Accepted[]; delRows: Fr }
/** (included committed batches, published records, (disposition, amount) of every received row, records a delete removed, delete rows' amount). */
export function publicationScope(pub: Row, f: Facts): Scope {
  const committedIds = new Set<string>(f.committed.map((b) => b["batch_id"]));
  const inc = (pub["included_batch_ids"] as string[]).filter((b) => committedIds.has(b));
  const incSet = new Set(inc);
  const srcRows: [string, Fr][] = [];
  for (const b of inc) for (const r of f.raws.get(b) ?? []) srcRows.push([f.disposition.get(r["raw_record_id"])!.kind, f.amounts.get(r["raw_record_id"])!]);
  const pubd: Accepted[] = [], removed: Accepted[] = [];
  for (const b of incSet) for (const a of f.acceptedByBatch.get(b) ?? []) { if (a.deleted_in && incSet.has(a.deleted_in)) removed.push(a); else pubd.push(a); }
  let delRows: Fr = ZERO;
  for (const [k, amt] of srcRows) if (k === DELETED) delRows = add(delRows, amt);
  return { inc, pubd, srcRows, removed, delRows };
}

/** The full golden shape. `params`: contract_version, as_of, cutoff, business_total_field, source_expectations, processing_measurement, and optionally
 * published_totals (publication_id -> exact total of the stored published table). */
export function compute(acc: Acc, rejected: Rejected[], params: Params): Row {
  const cutoff = params.cutoff;
  const f = derive(acc, params.business_total_field ?? "amount", params.cutoff);
  const counts = Object.fromEntries(ENTITIES.map((e) => [e, { accepted: (acc[e] ?? []).length, rejected: rejected.filter((r) => r.entity === e).length }]));
  const ing = ingestion(acc, f);
  const runsOut = runsBlock(acc);
  const gs = gates(acc);

  const pubsSorted = sortedBy(acc["publications"]!, (p) => [parseTs(p["published_at"]), p["publication_id"] as string]);
  const pubs: Row = {}, recon: Row = {};
  for (const p of pubsSorted) {
    const sc = publicationScope(p, f);
    const view = publicationView(p, sc.pubd);
    pubs[p["publication_id"]] = { run_id: p["run_id"], published_at: isoZ(p["published_at"]), watermark: isoZ(p["watermark"]), included_batches: sortedStrings(sc.inc), published_records: sc.pubd.length,
      latest_included_event_at: isoZ(view.latest), lag_seconds: view.lag_seconds, content_hash_ok: view.content_hash === p["content_hash"] };
    recon[p["publication_id"]] = reconcile(sc.srcRows, sc.pubd, sc.delRows, sc.removed, params.published_totals?.[p["publication_id"]] ?? null);
  }
  const pubOfRun: Record<string, string> = {};
  for (const p of pubsSorted) pubOfRun[p["run_id"]] = p["publication_id"];
  let pointer: string | null = null;
  const history: Row[] = [];
  for (const run of sortedBy(acc["pipeline_runs"]!, (r) => [parseTs(r["finished_at"] || r["started_at"]), r["run_id"] as string])) {
    const decision = gs[run["run_id"]]!.decision;
    if (gateMod.mayPublish(run["status"], decision, run["run_id"] in pubOfRun)) pointer = pubOfRun[run["run_id"]]!;
    history.push({ run_id: run["run_id"], gate_decision: decision, pointer_after: pointer });
  }
  const publications = { current_publication_id: pointer, pointer_history: history, publications: pubs };

  const late = lateEvents(f.accepted, acc["publications"]!);
  const lateOut = { count: late.length, included_in_next_publication: late.filter((x) => x.included_in_publication_id).length, lost: late.filter((x) => !x.included_in_publication_id).length, events: late };

  const gateOf: Record<string, string> = Object.fromEntries(Object.entries(gs).map(([rid, g]) => [rid, g.decision]));
  const residualOf: Record<string, string> = Object.fromEntries(Object.entries(recon).map(([pid, r]) => [pid, r["residual"]]));
  const incidents: Row = {};
  const tally = { closed: 0, open: 0, verified: 0, seconds: 0 };
  for (const i of sortedBy(acc["incidents"]!, (i) => [i["incident_id"] as string])) {
    const found = verifiedRecovery(i["opened_at"], acc["pipeline_runs"]!, gateOf, pubOfRun, residualOf);
    const verifiedAt = found ? pubs[found.publication_id].published_at as string : null;
    const sec = found ? secondsBetween(i["opened_at"], verifiedAt!) : null;
    const consistent = i["status"] !== "closed" || (found !== null && i["recovery_run_id"] === found.run["run_id"] && i["closed_at"] !== null && i["closed_at"] !== undefined && parseTs(i["closed_at"]) === parseTs(verifiedAt!));
    incidents[i["incident_id"]] = { run_id: i["run_id"], status: i["status"], detected_at: isoZ(i["opened_at"]), verified: found !== null, recovery_run_id: found ? found.run["run_id"] : null,
      verified_at: verifiedAt, recovery_seconds: sec, recovery_minutes: recoveryMinutes(sec), closure_consistent: consistent };
    tally[i["status"] === "closed" ? "closed" : "open"]++;
    if (found) { tally.verified++; tally.seconds += sec!; }
  }
  const incidentOut = { total: Object.keys(incidents).length, open: tally.open, closed: tally.closed, verified: tally.verified, mean_recovery_minutes: meanMinutes(tally.seconds, tally.verified), incidents };

  const requests: Row = {};
  let req = 0, ver = 0;
  for (const b of sortedBy(acc["backfill_requests"]!, (b) => [b["backfill_id"] as string])) {
    const parts = dayPartitions(b["start_at"], b["end_at"]);
    const verified = sortedStrings((b["partitions"] as Row[]).filter((p) => p["verified"] && parts.includes(p["partition"])).map((p) => p["partition"] as string));
    requests[b["backfill_id"]] = { source_id: b["source_id"], start_at: isoZ(b["start_at"]), end_at: isoZ(b["end_at"]), requested_partitions: parts.length, verified_partitions: verified.length, coverage: p6(ratio(verified.length, parts.length)) };
    req += parts.length; ver += verified.length;
  }
  const backfills = { requests, refused: sortedStrings(rejected.filter((r) => r.entity === "backfill_requests" && r.reason_code === "BACKFILL_OVERLAP").map((r) => r.id as string)),
    overall: { requested_partitions: req, verified_partitions: ver, coverage: p6(ratio(ver, req)) } };

  const pm = params.processing_measurement ?? null;
  let rate: Row;
  if (pm === null) rate = { accepted_records: 0, measured_seconds: null, records_per_second: null, hardware: null, cache_state: null };
  else {
    const n = f.accepted.filter((a) => a.batch_id === pm["batch_id"]).length;
    const secs = decFr(String(pm["measured_seconds"]));
    rate = { accepted_records: n, measured_seconds: typeof pm["measured_seconds"] === "string" ? pm["measured_seconds"] : String(pm["measured_seconds"]), records_per_second: p6(ratio(n, secs)), hardware: pm["hardware"], cache_state: pm["cache_state"] };
  }
  return { contract_version: params.contract_version, as_of: params.as_of, cutoff, empty_population: (acc["raw_records"] ?? []).length === 0, ingest: { counts, rejected_records: rejected },
    metrics: { ingestion: ing, freshness: freshness(acc, f, cutoff), completeness: completeness(params.source_expectations, f), runs: runsOut, quality_gate: gs, publications, late_events: lateOut,
      reconciliation: recon, incidents: incidentOut, backfills, processing_rate: rate } };
}
export function paramsOf(data: Record<string, unknown>): Params {
  return { contract_version: data["contract_version"] ?? CONTRACT_VERSION, as_of: data["as_of"] as string, cutoff: data["cutoff"] as string, business_total_field: (data["business_total_field"] as string) ?? "amount",
    source_expectations: (data["source_expectations"] as Row[]) ?? [], processing_measurement: (data["processing_measurement"] as Row | null) ?? null };
}
export interface PipelineResult { imported: ImportResult; golden: Row; facts: Facts; params: Params }
export function runPipeline(data: Record<string, unknown>, published_totals: Record<string, Fr> | null = null): PipelineResult {
  const imp = validateImport(data);
  const params = { ...paramsOf(data), published_totals };
  return { imported: imp, golden: compute(imp.accepted, imp.rejected, params), facts: derive(imp.accepted, params.business_total_field ?? "amount", params.cutoff), params };
}

export interface WindowOpts { source_id?: string | null; from?: string | null; to?: string | null; cutoff?: string | null }
/** The API's GET /metrics: the facts known at `cutoff` inside the half-open window [from, to), for one source or all. as_of and cutoff become `cutoff`. */
export function computeWindow(acc: Acc, rejected: Rejected[], params: Params, o: WindowOpts): Row {
  const when = o.cutoff ?? params.cutoff;
  const scoped = restrict(acc, o.source_id ?? null, o.from ?? null, o.to ?? null, when);
  const p: Params = { ...params, as_of: isoZ(when)!, cutoff: isoZ(when)!, source_expectations: restrictExpectations(params.source_expectations, o.source_id ?? null, o.from ?? null, o.to ?? null, when) };
  const pm = p.processing_measurement;
  if (pm && !scoped["ingestion_batches"]!.some((b) => b["batch_id"] === pm["batch_id"])) p.processing_measurement = null;
  return compute(scoped, rejected, p);
}
