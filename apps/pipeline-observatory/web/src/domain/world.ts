// What the published files say about the COMPLETE world without needing the raw rows (contracts D-07): the per-batch summaries, the runs, the gate
// results, the fetch log and the checkpoints are published in full, so these figures are recomputed here exactly; the figures that need the raw
// rows (freshness, completeness, late events, reconciliation, content hashes) are only recomputable over the 2,000-row sample and are otherwise
// shown as the generator recorded them, labelled as such.
import type { Row } from "./contract";
import { cmpCodePoints } from "./hashing";
import { cmpFr, p6, ratio, m4, fr, type Fr } from "./num";
import { sortedBy, sortedEntries, sortedStrings } from "./py";
import { meanMinutes, recoveryMinutes, verifiedRecovery } from "./reconcile";
import { isoZ, parseTs, secondsBetween } from "./time";

export interface SummaryTotals { batches: number; received: number; accepted_unique: number; duplicate: number; deleted: number; quarantined: number; rejection_rate: string | null; duplicate_rate: string | null; quarantine_by_reason: Record<string, number> }
function totals(rows: Row[]): SummaryTotals {
  const t = { batches: rows.length, received: 0, accepted_unique: 0, duplicate: 0, deleted: 0, quarantined: 0 };
  const by: Record<string, number> = {};
  for (const r of rows) {
    t.received += r["received"]; t.accepted_unique += r["accepted_unique"]; t.duplicate += r["duplicate"]; t.deleted += r["deleted"] ?? 0; t.quarantined += r["quarantined"];
    for (const [k, n] of Object.entries(r["quarantine_by_reason"] as Record<string, number>)) by[k] = (by[k] ?? 0) + n;
  }
  return { ...t, rejection_rate: p6(ratio(t.quarantined, t.received)), duplicate_rate: p6(ratio(t.duplicate, t.received)), quarantine_by_reason: Object.fromEntries(sortedEntries(by)) };
}
export interface SummaryWorld { overall: SummaryTotals; sources: Record<string, SummaryTotals>; by_kind: Record<string, { batches: number; written_rows: number }>; by_status: Record<string, number>; sampled_batches: number; sampled_rows: number }
/** The ingestion counts of the complete world from `batch_summaries` (committed batches only count, D-P8-04). */
export function ingestionFromSummaries(summaries: Row[], sourceIds: string[]): SummaryWorld {
  const committed = summaries.filter((s) => s["status"] === "committed");
  const sources: Record<string, SummaryTotals> = {};
  for (const sid of [...sourceIds].sort(cmpCodePoints)) sources[sid] = totals(committed.filter((s) => s["source_id"] === sid));
  const byKind: Record<string, { batches: number; written_rows: number }> = {}, byStatus: Record<string, number> = {};
  for (const s of summaries) {
    const k = (byKind[s["kind"]] ??= { batches: 0, written_rows: 0 }); k.batches++; k.written_rows += s["written_rows"];
    byStatus[s["status"]] = (byStatus[s["status"]] ?? 0) + 1;
  }
  const sampled = summaries.filter((s) => s["sampled"]);
  return { overall: totals(committed), sources, by_kind: Object.fromEntries(sortedEntries(byKind)), by_status: Object.fromEntries(sortedEntries(byStatus)), sampled_batches: sampled.length, sampled_rows: sampled.reduce((a, s) => a + s["written_rows"], 0) };
}

/** The diagnosis class of an incident from the first failed check of its run (or, with no failed check, from the failed task). */
export const RULE_CLASS: Record<string, string> = { relationships_intact: "relationships", freshness_within_target: "freshness", reconciliation_residual_zero: "residual", keys_unique: "keys" };
export interface IncidentView {
  incident_id: string; run_id: string; severity: string; opened_at: string; closed_at: string | null; recorded_recovery_run_id: string | null; status: string;
  verified: boolean; recovery_run_id: string | null; verified_at: string | null; recovery_seconds: number | null; recovery_minutes: string | null; closure_consistent: boolean;
  diagnosis_class: string; failed_checks: { rule: string; severity: string; failures: number; eligible: number }[]; failed_tasks: { task: string; attempts: number }[];
}
export interface IncidentWorld { total: number; open: number; closed: number; verified: number; mean_recovery_minutes: string | null; all_closures_consistent: boolean; by_class: Record<string, number>; incidents: IncidentView[] }
/** Verified recovery (D-P8-06): the first later run that succeeded, passed its gate, published, and whose publication reconciles to 0.00. `residualOf`
 * is the residual per publication. Over the sample the residual needs raw rows that are not published, so the caller may pass the generator's
 * recorded statement instead (every publication reconciles to 0.00, manifest stats.reconciliation) and says so on screen. */
export function incidentsRecovered(acc: Record<string, Row[]>, gateOf: Record<string, string>, failedChecks: Record<string, IncidentView["failed_checks"]>, residualOf: Record<string, string>): IncidentWorld {
  const pubOfRun: Record<string, string> = {}, pubAt: Record<string, string> = {};
  for (const p of acc["publications"]!) { pubOfRun[p["run_id"]] = p["publication_id"]; pubAt[p["publication_id"]] = p["published_at"]; }
  const tasksOf = new Map<string, Map<string, number>>();
  const lastStatus = new Map<string, string>();
  for (const t of sortedBy(acc["task_runs"]!, (t) => [t["run_id"] as string, t["task_name"] as string, Number(t["attempt"])])) {
    const m = tasksOf.get(t["run_id"]) ?? tasksOf.set(t["run_id"], new Map()).get(t["run_id"])!;
    m.set(t["task_name"], Number(t["attempt"])); lastStatus.set(`${t["run_id"]}\u0000${t["task_name"]}`, t["status"]);
  }
  const views: IncidentView[] = [];
  let seconds = 0, verified = 0, closed = 0, open = 0, consistentAll = true;
  const byClass: Record<string, number> = {};
  for (const i of sortedBy(acc["incidents"]!, (i) => [i["incident_id"] as string])) {
    const found = verifiedRecovery(i["opened_at"], acc["pipeline_runs"]!, gateOf, pubOfRun, residualOf);
    const verifiedAt = found ? isoZ(pubAt[found.publication_id]!) : null;
    const sec = found ? secondsBetween(i["opened_at"], verifiedAt!) : null;
    const consistent = i["status"] !== "closed" || (found !== null && i["recovery_run_id"] === found.run["run_id"] && !!i["closed_at"] && parseTs(i["closed_at"]) === parseTs(verifiedAt!));
    const fc = failedChecks[i["run_id"]] ?? [];
    const failedTasks = [...(tasksOf.get(i["run_id"]) ?? new Map<string, number>()).entries()].filter(([task]) => lastStatus.get(`${i["run_id"]}\u0000${task}`) === "failed").map(([task, attempts]) => ({ task, attempts }));
    const cls = fc.length ? (RULE_CLASS[fc[0]!.rule] ?? fc[0]!.rule) : failedTasks.length ? (failedTasks[0]!.task === "quality_gate" ? "gate_infra" : failedTasks[0]!.task) : "unclassified";
    byClass[cls] = (byClass[cls] ?? 0) + 1;
    views.push({ incident_id: i["incident_id"], run_id: i["run_id"], severity: i["severity"], opened_at: isoZ(i["opened_at"])!, closed_at: i["closed_at"] ? isoZ(i["closed_at"]) : null, recorded_recovery_run_id: i["recovery_run_id"] ?? null,
      status: i["status"], verified: found !== null, recovery_run_id: found ? found.run["run_id"] : null, verified_at: verifiedAt, recovery_seconds: sec, recovery_minutes: recoveryMinutes(sec),
      closure_consistent: consistent, diagnosis_class: cls, failed_checks: fc, failed_tasks: failedTasks });
    if (i["status"] === "closed") closed++; else open++;
    if (found) { verified++; seconds += sec!; }
    if (!consistent) consistentAll = false;
  }
  return { total: views.length, open, closed, verified, mean_recovery_minutes: meanMinutes(seconds, verified), all_closures_consistent: consistentAll, by_class: Object.fromEntries(sortedEntries(byClass)), incidents: views };
}

export interface RetryStats { fetch_rows: number; rate_limited_responses: number; retries: number; retries_honouring_retry_after: number; retries_too_soon: number; sessions_rate_limited: number; min_slack_seconds: number | null; max_slack_seconds: number | null; cursor_loops: number; sources_rate_limited: string[] }
/** Retry behaviour from `fetch_log`: a rate-limited response is followed in the same session and for the same cursor by the retry; its slack is the
 * time between the earliest allowed instant (response + retry_after_seconds) and the retry; a negative slack would be a retry that ignored the hint. */
export function retryStats(fetchLog: Row[]): RetryStats {
  const rows = sortedBy(fetchLog, (r) => [Number(r["fetch_id"])]);
  let limited = 0, retries = 0, honouring = 0, tooSoon = 0, loops = 0;
  const sessions = new Set<string>(), sources = new Set<string>();
  const slacks: number[] = [];
  rows.forEach((r, i) => {
    if (r["status"] === "cursor_loop") loops++;
    if (r["status"] !== "rate_limited") return;
    limited++; sessions.add(r["session_id"]); sources.add(r["source_id"]);
    const next = rows.slice(i + 1).find((x) => x["session_id"] === r["session_id"] && x["cursor_value"] === r["cursor_value"]);
    if (!next) return;
    retries++;
    const slack = secondsBetween(parseTs(r["fetched_at"]) + BigInt(r["retry_after_seconds"]) * 1_000_000n, next["fetched_at"]);
    slacks.push(slack);
    if (slack >= 0) honouring++; else tooSoon++;
  });
  return { fetch_rows: rows.length, rate_limited_responses: limited, retries, retries_honouring_retry_after: honouring, retries_too_soon: tooSoon, sessions_rate_limited: sessions.size,
    min_slack_seconds: slacks.length ? Math.min(...slacks) : null, max_slack_seconds: slacks.length ? Math.max(...slacks) : null, cursor_loops: loops, sources_rate_limited: sortedStrings(sources) };
}

/** Seconds of a declared cadence: "hourly", "daily", "every 4 hours", "every 30 minutes", "every 2 days"; null when it cannot be read. */
export function cadenceSeconds(freq: string | null | undefined): number | null {
  if (!freq) return null;
  const f = freq.trim().toLowerCase();
  if (f === "hourly") return 3600;
  if (f === "daily") return 86400;
  if (f === "weekly") return 604800;
  const m = /^every (\d+) (minute|hour|day)s?$/.exec(f);
  return m ? Number(m[1]) * (m[2] === "minute" ? 60 : m[2] === "hour" ? 3600 : 86400) : null;
}
/** A source is shown as silent when its freshness exceeds this many declared cadences (a display rule, not a contract rule: the gate uses the target). */
export const SILENT_AFTER_CADENCES = 2;
export interface FreshnessRow {
  source_id: string; source_name: string; cadence: string; cadence_seconds: number | null; target_seconds: number | null;
  last_ingestion_at: string | null; ingestion_age_seconds: number | null; latest_event_at: string | null; freshness_seconds: number | null; freshness_basis: "recorded" | "computed";
  sample_freshness_seconds: number | null; gap_seconds: number | null; past_target: boolean | null; cadences: string | null; silent: boolean | null;
  last_batch: { batch_id: string; status: string; started_at: string } | null; batches_72h: Record<string, number>;
}
/** Freshness beside ingestion age per source. `recordedEvent` is the generator's latest accepted event per source (complete world) when the raw rows
 * are a sample; without it the figure is computed from the accepted rows (`computed`). Ingestion age is always computed (checkpoints are complete). */
export function freshnessRows(contracts: Row[], batches: Row[], checkpoints: Row[], computed: Row, cutoff: string, recordedEvent: Record<string, string | null> | null): FreshnessRow[] {
  const cut = parseTs(cutoff);
  const cpOf = new Map<string, Row>(checkpoints.map((c) => [c["batch_id"], c]));
  return sortedBy(contracts, (s) => [s["source_id"] as string]).map((s): FreshnessRow => {
    const sid = s["source_id"] as string;
    const mine = batches.filter((b) => b["source_id"] === sid);
    let lastIngest: string | null = null;
    for (const b of mine) { const c = cpOf.get(b["batch_id"]); if (b["status"] === "committed" && c && (lastIngest === null || parseTs(c["committed_at"]) > parseTs(lastIngest))) lastIngest = c["committed_at"]; }
    const ageSec = lastIngest ? secondsBetween(lastIngest, cutoff) : null;
    const basis = recordedEvent ? "recorded" : "computed";
    const ev: string | null = recordedEvent ? (recordedEvent[sid] ?? null) : (computed["freshness"][sid]?.latest_accepted_event_at ?? null);
    const fresh = ev ? secondsBetween(ev, cutoff) : null;
    const cad = cadenceSeconds(s["expected_frequency"]);
    const target = typeof s["freshness_target_seconds"] === "number" ? (s["freshness_target_seconds"] as number) : null;
    const last = sortedBy(mine, (b) => [parseTs(b["started_at"]), b["batch_id"] as string]).pop() ?? null;
    const recent: Record<string, number> = {};
    for (const b of mine) if (parseTs(b["started_at"]) > cut - 72n * 3_600_000_000n && parseTs(b["started_at"]) <= cut) recent[b["status"]] = (recent[b["status"]] ?? 0) + 1;
    const cadences = fresh !== null && cad ? ratio(fresh, cad) : null;
    return { source_id: sid, source_name: s["source_name"], cadence: s["expected_frequency"], cadence_seconds: cad, target_seconds: target, last_ingestion_at: isoZ(lastIngest), ingestion_age_seconds: ageSec,
      latest_event_at: isoZ(ev), freshness_seconds: fresh, freshness_basis: basis, sample_freshness_seconds: computed["freshness"][sid]?.freshness_seconds ?? null,
      gap_seconds: fresh !== null && ageSec !== null ? fresh - ageSec : null, past_target: fresh !== null && target !== null ? fresh > target : null,
      cadences: cadences ? m4(cadences) : null, silent: cadences ? cmpFr(cadences, fr(SILENT_AFTER_CADENCES)) > 0 : null,
      last_batch: last ? { batch_id: last["batch_id"], status: last["status"], started_at: isoZ(last["started_at"])! } : null, batches_72h: Object.fromEntries(sortedEntries(recent)) };
  });
}
export type { Fr };
