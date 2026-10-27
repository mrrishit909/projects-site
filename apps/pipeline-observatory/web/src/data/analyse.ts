// Turns the published files (or the golden fixture) into everything a screen shows, in one pure function the node checks run too.
// Three scopes are kept apart on purpose (contracts D-07): "complete" = recomputed here from files that are published in full; "sample" = recomputed
// here over the 2,000 published raw rows (describes the sample, not the world); "recorded" = what the generator wrote in the manifest about the complete
// world, which the published files cannot reproduce.
import { canonicalJson } from "../domain/hashing";
import { injectionChecks, type CheckResult } from "../domain/claims";
import { type Row } from "../domain/contract";
import { buildGraph, type Graph } from "../domain/graph";
import { runPipeline, type Acc, type PipelineResult } from "../domain/metrics";
import { parseTs } from "../domain/time";
import { freshnessRows, incidentsRecovered, ingestionFromSummaries, retryStats, type FreshnessRow, type IncidentWorld, type RetryStats, type SummaryTotals, type SummaryWorld } from "../domain/world";
import { buildInputs, type Manifest, type RawFiles } from "./files";

export type Basis = "complete" | "sample" | "recorded";
export interface Claim { id: string; key: string; label: string; basis: Basis; want: unknown; got: unknown; ok: boolean | null }
export interface Provenance { dataset_version: string; dataset_hash: string; generated_at: string; code_sha: string | null; as_of: string }
export interface Dataset {
  id: "snapshot" | "golden";
  provenance: Provenance;
  /** The pipeline run over the rows the browser holds: the 2,000-row sample for the snapshot, every row for the golden fixture. */
  result: PipelineResult;
  acc: Acc;
  g: Row;
  raw: RawFiles | null;
  manifest: Manifest | null;
  /** Ingestion counts of the whole dataset: from batch_summaries (snapshot) or from the fixture's own classification (golden). */
  ingestion: SummaryWorld;
  incidents: IncidentWorld;
  residualAssumed: boolean;
  retry: RetryStats | null;
  freshness: FreshnessRow[];
  graph: Graph;
  claims: Claim[];
  injection: CheckResult[];
  injections: Row[];
  /** The replay events EV-01..EV-12 of the injection manifest (executed by the backend CI only). */
  events: Row[];
  /** Per run: the failed checks of its gate. */
  failedChecks: Record<string, { rule: string; severity: string; failures: number; eligible: number }[]>;
  pubOfRun: Record<string, string>;
}

function common(g: Row, acc: Acc): { failedChecks: Dataset["failedChecks"]; gateOf: Record<string, string>; pubOfRun: Record<string, string> } {
  const M = g["metrics"];
  const failedChecks: Dataset["failedChecks"] = {};
  const gateOf: Record<string, string> = {};
  for (const [rid, gate] of Object.entries(M.quality_gate as Record<string, Row>)) {
    gateOf[rid] = gate["decision"];
    failedChecks[rid] = Object.entries(gate["results"] as Record<string, Row>).filter(([, v]) => !v["passed"]).map(([rule, v]) => ({ rule, severity: v["severity"], failures: v["failures"], eligible: v["eligible"] }));
  }
  const pubOfRun: Record<string, string> = {};
  for (const p of acc["publications"]!) pubOfRun[p["run_id"]] = p["publication_id"];
  return { failedChecks, gateOf, pubOfRun };
}

export function analyseSnapshot(manifest: Manifest, raw: RawFiles, injectionManifest: Row | null): Dataset {
  const { data, publishedTotals } = buildInputs(manifest, raw);
  const result = runPipeline(data, publishedTotals);
  const g = result.golden, M = g["metrics"], acc = result.imported.accepted as Acc;
  const sourceIds = raw.source_contracts.map((s) => s["source_id"] as string);
  const ingestion = ingestionFromSummaries(raw.batch_summaries, sourceIds);
  const { failedChecks, gateOf, pubOfRun } = common(g, acc);
  const reconciled: Record<string, string> = Object.fromEntries(raw.publications.map((p) => [p["publication_id"], "0.00"]));
  const incidents = incidentsRecovered(acc, gateOf, failedChecks, reconciled);
  const retry = retryStats(raw.fetch_log);
  const recorded = Object.fromEntries(Object.entries((manifest.stats?.["freshness_at_as_of"] ?? {}) as Record<string, Row>).map(([k, v]) => [k, (v["latest_accepted_event_at"] as string) ?? null]));
  const freshness = freshnessRows(raw.source_contracts, raw.ingestion_batches, raw.checkpoints, M, g["cutoff"], Object.keys(recorded).length ? recorded : null);
  const graph = buildGraph(raw.model_definitions, sourceIds, [...new Set(raw.publications.map((p) => p["dataset_name"] as string))]);
  const injections = (injectionManifest?.["injections"] as Row[] | undefined) ?? [];
  const ds: Dataset = { id: "snapshot", provenance: { dataset_version: manifest.dataset_version, dataset_hash: manifest.dataset_hash, generated_at: manifest.generated_at, code_sha: manifest.code_sha ?? null, as_of: manifest.as_of },
    result, acc, g, raw, manifest, ingestion, incidents, residualAssumed: true, retry, freshness, graph, claims: [], injection: injectionChecks(injections, g), injections, events: (injectionManifest?.["events"] as Row[] | undefined) ?? [], failedChecks, pubOfRun };
  ds.claims = designedClaims(ds);
  return ds;
}

/** The golden fixture, computed in the browser from inputs.json: every row is present, so everything is "complete". */
export function analyseGolden(inputs: Record<string, unknown>, inputsText: string, sha256: (t: string) => string): Dataset {
  const result = runPipeline(inputs);
  const g = result.golden, M = g["metrics"], acc = result.imported.accepted as Acc;
  const ing = M.ingestion;
  const src: Record<string, SummaryTotals> = {};
  for (const [sid, s] of Object.entries(ing.sources as Record<string, Row>)) src[sid] = { batches: Object.values(s["batches"] as Record<string, Row>).filter((b) => b["counted"]).length, received: s["received"], accepted_unique: s["accepted_unique"], duplicate: s["duplicate"], deleted: 0, quarantined: s["quarantined"], rejection_rate: s["rejection_rate"], duplicate_rate: s["duplicate_rate"], quarantine_by_reason: s["quarantine_by_reason"] };
  const o = ing.overall;
  const ingestion: SummaryWorld = { overall: { batches: Object.values(src).reduce((a, s) => a + s.batches, 0), received: o.received, accepted_unique: o.accepted_unique, duplicate: o.duplicate, deleted: 0, quarantined: o.quarantined, rejection_rate: o.rejection_rate, duplicate_rate: o.duplicate_rate,
    quarantine_by_reason: Object.values(src).reduce((a, s) => { for (const [k, n] of Object.entries(s.quarantine_by_reason)) a[k] = (a[k] ?? 0) + n; return a; }, {} as Record<string, number>) },
    sources: src, by_kind: {}, by_status: {}, sampled_batches: 0, sampled_rows: 0 };
  const { failedChecks, gateOf, pubOfRun } = common(g, acc);
  const residual: Record<string, string> = Object.fromEntries(Object.entries(M.reconciliation as Record<string, Row>).map(([k, v]) => [k, v["residual"]]));
  const incidents = incidentsRecovered(acc, gateOf, failedChecks, residual);
  const freshness = freshnessRows(acc["source_contracts"]!, acc["ingestion_batches"]!, acc["checkpoints"]!, M, g["cutoff"], null);
  const graph = buildGraph(acc["model_definitions"]!, acc["source_contracts"]!.map((s) => s["source_id"] as string), [...new Set(acc["publications"]!.map((p) => p["dataset_name"] as string))]);
  return { id: "golden", provenance: { dataset_version: "golden-fixture-1", dataset_hash: sha256(inputsText), generated_at: g["as_of"], code_sha: null, as_of: g["as_of"] }, result, acc, g, raw: null, manifest: null, ingestion, incidents,
    residualAssumed: false, retry: null, freshness, graph, claims: [], injection: [], injections: [], events: [], failedChecks, pubOfRun };
}

// ---------------------------------------------------------------------------------------------------------------- designed relationships
const same = (a: unknown, b: unknown): boolean => canonicalJson(a) === canonicalJson(b);
/** The figures the manifest records for its five designed relationships, each re-derived here from what the published files allow, with its basis. */
export function designedClaims(ds: Dataset): Claim[] {
  const m = ds.manifest, raw = ds.raw;
  if (!m || !raw) return [];
  const out: Claim[] = [];
  const M = ds.g["metrics"];
  const asOf = parseTs(m.as_of);
  const put = (id: string, key: string, label: string, basis: Basis, want: unknown, got: unknown): void => {
    out.push({ id, key, label, basis, want, got: basis === "recorded" ? null : got, ok: basis === "recorded" ? null : same(want, got) });
  };
  const dr = (id: string): Row => (m.designed_relationships ?? []).find((d) => d["id"] === id) ?? { realised: {}, parameters: {} };
  // DR-01
  {
    const R = dr("DR-01")["realised"], P = dr("DR-01")["parameters"], sid = P["source_id"] as string, stops = parseTs(P["stops_at"]);
    const f = ds.freshness.find((x) => x.source_id === sid);
    const inWin = (t: string): boolean => parseTs(t) >= stops && parseTs(t) < asOf;
    const runs = raw.pipeline_runs.filter((r) => inWin(r["started_at"]));
    const batches = raw.ingestion_batches.filter((b) => b["source_id"] === sid && b["status"] === "committed" && inWin(b["started_at"]));
    const sums = batches.map((b) => raw.batch_summaries.find((s) => s["batch_id"] === b["batch_id"])!);
    put("DR-01", "freshness_seconds", "freshness of the silent source", "sample", R["freshness_seconds"], f?.sample_freshness_seconds ?? null);
    put("DR-01", "latest_accepted_event_at", "latest accepted event", "sample", R["latest_accepted_event_at"], M.freshness[sid]?.latest_accepted_event_at ?? null);
    put("DR-01", "ingestion_age_seconds", "ingestion age of the same source", "complete", R["ingestion_age_seconds"], f?.ingestion_age_seconds ?? null);
    put("DR-01", "last_successful_ingestion_at", "last successful ingestion", "complete", R["last_successful_ingestion_at"], f?.last_ingestion_at ?? null);
    put("DR-01", "runs_in_window", "runs since the source went silent", "complete", R["runs_in_window"], runs.length);
    put("DR-01", "runs_succeeded", "of them green", "complete", R["runs_succeeded"], runs.filter((r) => r["status"] === "success").length);
    put("DR-01", "runs_allowed_by_the_gate", "of them allowed by the gate", "complete", R["runs_allowed_by_the_gate"], runs.filter((r) => M.quality_gate[r["run_id"]]?.decision === "allowed").length);
    put("DR-01", "committed_batches_in_window", "batches committed since", "complete", R["committed_batches_in_window"], batches.length);
    put("DR-01", "accepted_in_window", "records accepted since", "complete", R["accepted_in_window"], sums.reduce((a, s) => a + s["accepted_unique"], 0));
    put("DR-01", "duplicates_in_window", "duplicates since", "complete", R["duplicates_in_window"], sums.reduce((a, s) => a + s["duplicate"], 0));
    put("DR-01", "batches_with_no_accepted_record", "batches that accepted nothing", "complete", R["batches_with_no_accepted_record"], sums.filter((s) => s["accepted_unique"] === 0).length);
    for (const day of Object.keys(R["completeness"] as Row)) put("DR-01", `completeness.${day}`, `completeness of ${day}`, "sample", (R["completeness"] as Row)[day], M.completeness[sid]?.[day]?.value ?? null);
  }
  // DR-02
  {
    const R = dr("DR-02")["realised"], rid = R["run_id"] as string;
    const hist = M.publications.pointer_history as Row[];
    const idx = hist.findIndex((h) => h["run_id"] === rid);
    const inc = ds.incidents.incidents.find((i) => i.run_id === rid);
    put("DR-02", "run_status", "status of the designated run", "complete", R["run_status"], ds.acc["pipeline_runs"]!.find((r) => r["run_id"] === rid)?.["status"] ?? null);
    put("DR-02", "gate_decision", "gate decision", "complete", R["gate_decision"], M.quality_gate[rid]?.decision ?? null);
    put("DR-02", "critical_failures", "critical checks failed", "complete", R["critical_failures"], M.quality_gate[rid]?.critical_failures ?? null);
    put("DR-02", "publication_exists", "a publication row exists", "complete", R["publication_exists"], rid in ds.pubOfRun);
    put("DR-02", "pointer_before", "pointer before the run", "complete", R["pointer_before"], idx > 0 ? hist[idx - 1]!["pointer_after"] : null);
    put("DR-02", "pointer_after", "pointer after the run", "complete", R["pointer_after"], idx >= 0 ? hist[idx]!["pointer_after"] : null);
    put("DR-02", "pointer_unchanged", "pointer unchanged", "complete", R["pointer_unchanged"], idx > 0 && hist[idx]!["pointer_after"] === hist[idx - 1]!["pointer_after"]);
    put("DR-02", "pointer_history_index", "position in the pointer history", "complete", R["pointer_history_index"], idx);
    put("DR-02", "incident_id", "incident opened", "complete", R["incident_id"], inc?.incident_id ?? null);
    put("DR-02", "recovery_run_id", "verified recovery run", "complete", R["recovery_run_id"], inc?.recovery_run_id ?? null);
    put("DR-02", "recovery_minutes", "recovery time, minutes", "complete", R["recovery_minutes"], inc?.recovery_minutes ?? null);
  }
  // DR-03
  {
    const R = dr("DR-03")["realised"], r = ds.retry!;
    for (const k of ["fetch_rows", "rate_limited_responses", "retries", "retries_honouring_retry_after", "retries_too_soon", "sessions_rate_limited", "min_slack_seconds", "max_slack_seconds", "cursor_loops"] as const) put("DR-03", k, k.replace(/_/g, " "), "complete", R[k], r[k]);
    put("DR-03", "sources_rate_limited", "sources rate limited", "complete", R["sources_rate_limited"], r.sources_rate_limited);
  }
  // DR-04
  {
    const R = dr("DR-04")["realised"];
    const events = M.late_events.events as Row[];
    for (const d of (R["designed"] as Row[]) ?? []) {
      const hit = events.find((e) => e["source_key"] === d["source_key"]);
      put("DR-04", `designed.${d["source_key"]}`, `designed late event ${d["source_key"]}`, "sample", { ...d }, hit ? { source_key: hit["source_key"], event_at: hit["event_at"], arrival_at: hit["arrival_at"], behind_publication_id: hit["behind_publication_id"], included_in_publication_id: hit["included_in_publication_id"], watermark: hit["watermark"] } : null);
    }
    put("DR-04", "late_events_in_all", "late events in the complete world", "recorded", R["late_events_in_all"], null);
    put("DR-04", "lost", "late events lost", "recorded", R["lost"], null);
  }
  // DR-05
  {
    const R = dr("DR-05")["realised"], rid = R["incident_run_id"] as string;
    const inc = ds.incidents.incidents.find((i) => i.run_id === rid);
    const cand = raw.model_output_totals.find((t) => t["run_id"] === rid);
    const row = (R["candidates_with_nonzero_residual"] as Row[])[0] ?? {};
    put("DR-05", "publications", "publications", "complete", R["publications"], raw.publications.length);
    put("DR-05", "incident_id", "incident opened", "complete", R["incident_id"], inc?.incident_id ?? null);
    put("DR-05", "gate", "the designated run is blocked", "complete", "blocked", M.quality_gate[rid]?.decision ?? null);
    put("DR-05", "failed_check", "failed critical check", "complete", "reconciliation_residual_zero", ds.failedChecks[rid]?.[0]?.rule ?? null);
    put("DR-05", "recovery_run_id", "verified recovery run", "complete", R["recovery_run_id"], inc?.recovery_run_id ?? null);
    put("DR-05", "recovery_minutes", "recovery time, minutes", "complete", R["recovery_minutes"], inc?.recovery_minutes ?? null);
    put("DR-05", "leak_batch_status", `crashed batch ${R["leak_batch_id"]}`, "complete", "aborted", raw.ingestion_batches.find((b) => b["batch_id"] === R["leak_batch_id"])?.["status"] ?? null);
    put("DR-05", "candidate_total", "stored candidate total of the run", "complete", row["published_total"], cand?.["total_amount"] ?? null);
    put("DR-05", "residual", "unexplained residual of the candidate", "recorded", row["residual"], null);
    put("DR-05", "publications_with_nonzero_residual", "publications with a non-zero residual", "recorded", R["publications_with_nonzero_residual"], null);
  }
  return out;
}
