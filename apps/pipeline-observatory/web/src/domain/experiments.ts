// The failure experiments of the case study that the browser can reproduce through the domain (Mode B). Each is deterministic: a small scenario, the
// domain's own function, and a verdict computed from its output. The twelve injected defects of the generator are listed in the injection manifest; the
// ones the browser cannot reproduce (a workflow that triggers itself) are said so, never faked.
import { classifyRows } from "./classify";
import type { Row } from "./contract";
import { DomainError } from "./errors";
import { checkRetryAllowed, fetchAll, type Page } from "./fetch";
import { runPipeline } from "./metrics";
import { containsSecret, safeLine } from "./redaction";
import { decideBackfill, goldenExperiments } from "./sim";
import { parseTs } from "./time";
import type { Dataset } from "../data/analyse";

export interface ExperimentRun { ok: boolean; lines: string[] }
export interface ExperimentCtx { goldenInputs: Record<string, unknown>; golden: Dataset; ds: Dataset }
const pay = (k: string, o: Row = {}): Row => ({ record_id: k, quantity: 1, unit_price: "10.00", amount: "10.00", event_ts: "2026-10-04T08:00:00Z", ...o });
const row = (n: number, k: string | null, payload: Row | null): Row => ({ raw_record_id: `r${String(n).padStart(2, "0")}`, source_key: k, payload_json: payload });
const code = (f: () => unknown): string => { try { f(); return "ok"; } catch (e) { return e instanceof DomainError ? e.code : "error"; } };

export const BROWSER_EXPERIMENTS: Record<string, (c: ExperimentCtx) => ExperimentRun> = {
  "INJ-01": (c) => {
    const e = goldenExperiments(c.goldenInputs).find((x) => x.id === "crash")!;
    return { ok: e.holds, lines: [...e.steps.map((s) => `${s.label}: ${s.accepted_total} accepted in total`), e.verdict] };
  },
  "INJ-02": () => {
    const accepted = [{ backfill_id: "bf-1", source_id: "src-a", start_at: "2026-09-01T00:00:00Z", end_at: "2026-09-04T00:00:00Z", status: "requested" }];
    const over = decideBackfill(accepted, { source_id: "src-a", start_at: "2026-09-03T00:00:00Z", end_at: "2026-09-06T00:00:00Z" });
    const touch = decideBackfill(accepted, { source_id: "src-a", start_at: "2026-09-04T00:00:00Z", end_at: "2026-09-06T00:00:00Z" });
    return { ok: over.code === "BACKFILL_OVERLAP" && touch.accepted, lines: [`[Sep 3, Sep 6) after the still-requested [Sep 1, Sep 4): ${over.code} (overlaps ${over.overlaps_with})`, `[Sep 4, Sep 6) touching [Sep 1, Sep 4): ${touch.accepted ? "accepted" : touch.code}, ${touch.partitions.length} partitions`] };
  },
  "INJ-03": () => {
    let clock = parseTs("2026-10-04T08:00:00Z");
    const sleeps: number[] = [];
    const seq: Record<string, Page[]> = { c0: [{ status: 429, records: [], next_cursor: null, retry_after_seconds: 60 }, { status: 200, records: [{ n: 1 }], next_cursor: null, retry_after_seconds: null }] };
    const used: Record<string, number> = {};
    const r = fetchAll((cur) => seq[cur]![(used[cur] = (used[cur] ?? -1) + 1)]!, "c0", () => clock, (s) => { sleeps.push(s); clock += BigInt(s) * 1_000_000n; });
    const gap = Number((r.calls[1]![1] - r.calls[0]![1]) / 1_000_000n);
    const early = code(() => checkRetryAllowed("2026-10-04T08:00:00Z", 60, "2026-10-04T08:00:59Z"));
    return { ok: gap === 60 && early === "RETRY_TOO_SOON" && r.records.length === 1, lines: [`429 with retry-after 60: waited ${sleeps[0]} s, retried ${gap} s after the first call`, `a retry 59 s after the hint: ${early}`] };
  },
  "INJ-04": () => {
    const rows = [row(1, "K1", pay("K1")), row(2, "K2", pay("K2")), row(3, "K3", pay("K3"))];
    const refused = classifyRows(rows, new Set(), new Set(), false);
    const after = classifyRows(rows, new Set(), new Set(), true);
    return { ok: refused.every((d) => d.reason === "SCHEMA_CHANGED") && after.every((d) => d.kind === "accepted"), lines: [`declared version differs from the contract: ${refused.map((d) => d.reason).join(", ")} (whole batch quarantined, checkpoint does not move)`, `after the operator bumps the expected version and the window is fetched again: ${after.map((d) => d.kind).join(", ")}`] };
  },
  "INJ-05": () => {
    const rows = [row(1, "K1", pay("K1")), row(2, "K1", pay("K1")), row(3, null, { quantity: 1 }), row(4, "K4", pay("K4", { quantity: -2 }))];
    const d = classifyRows(rows, new Set());
    const n = (k: string): number => d.filter((x) => x.kind === k).length;
    return { ok: n("accepted") + n("duplicate") + n("quarantined") === rows.length && d[2]!.reason === "MISSING_FIELD", lines: [`received ${rows.length} = accepted ${n("accepted")} + duplicate ${n("duplicate")} + quarantined ${n("quarantined")}`, `the row with no key and no fields: ${d[2]!.kind} ${d[2]!.reason}`, `the negative quantity: ${d[3]!.kind} ${d[3]!.reason}`] };
  },
  "INJ-06": (c) => {
    const f = [...c.ds.freshness].filter((x) => x.freshness_seconds !== null && x.ingestion_age_seconds !== null).sort((a, b) => (b.gap_seconds ?? 0) - (a.gap_seconds ?? 0))[0];
    if (!f) return { ok: false, lines: ["no source has both a freshness and an ingestion age"] };
    const runs = c.ds.acc["pipeline_runs"]!;
    const green = runs.filter((r) => r["status"] === "success").length;
    return { ok: (f.gap_seconds ?? 0) > 0 && f.last_batch?.status === "committed", lines: [`${f.source_id}: newest accepted event ${f.freshness_seconds} s old, last committed batch ${f.ingestion_age_seconds} s ago (gap ${f.gap_seconds} s)`, `its last batch is ${f.last_batch?.status}; ${green} of ${runs.length} runs are green`] };
  },
  "INJ-07": (c) => {
    const hist = c.ds.g.metrics.publications.pointer_history as Row[];
    const i = hist.findIndex((h, k) => k > 0 && h["gate_decision"] === "blocked");
    if (i < 0) return { ok: false, lines: ["no blocked run in this dataset"] };
    const h = hist[i]!;
    const hasPub = c.ds.acc["publications"]!.some((p) => p["run_id"] === h["run_id"]);
    return { ok: !hasPub && h["pointer_after"] === hist[i - 1]!["pointer_after"], lines: [`${h["run_id"]}: gate ${h["gate_decision"]}, publication row ${hasPub ? "exists" : "none"}`, `pointer before ${hist[i - 1]!["pointer_after"]}, after ${h["pointer_after"]}: unchanged`] };
  },
  "INJ-08": () => {
    const base: Row = { contract_version: 1, as_of: "2026-10-05T00:00:00Z", cutoff: "2026-10-05T00:00:00Z", source_expectations: [], processing_measurement: null, source_contracts: [{ source_id: "src-a", source_name: "a", schema_version: "1", expected_frequency: "hourly", owner_id: "o" }],
      ingestion_batches: [{ batch_id: "b1", source_id: "src-a", source_cursor: "c", started_at: "2026-10-04T08:00:00Z", status: "committed" }, { batch_id: "b2", source_id: "src-a", source_cursor: "c", started_at: "2026-10-04T09:00:00Z", status: "committed" }],
      raw_records: [{ raw_record_id: "r1", batch_id: "b1", source_key: "K1", payload_hash: "h", payload_json: pay("K1") }, { raw_record_id: "r2", batch_id: "b2", source_key: "K1", payload_hash: "h", payload_json: pay("K1", { op: "delete" }) }, { raw_record_id: "r3", batch_id: "b2", source_key: "K9", payload_hash: "h", payload_json: pay("K9", { op: "delete" }) }],
      quarantine_records: [], checkpoints: [{ checkpoint_id: "c1", source_id: "src-a", batch_id: "b1", committed_cursor: "c1", committed_at: "2026-10-04T08:05:00Z", version_number: 1 }, { checkpoint_id: "c2", source_id: "src-a", batch_id: "b2", committed_cursor: "c2", committed_at: "2026-10-04T09:05:00Z", version_number: 2 }],
      model_definitions: [], pipeline_runs: [{ run_id: "run-1", started_at: "2026-10-04T10:00:00Z", finished_at: "2026-10-04T10:10:00Z", status: "success", code_sha: "abc", backfill_id: null }], task_runs: [], quality_results: [], incidents: [], backfill_requests: [],
      publications: [{ publication_id: "p1", run_id: "run-1", dataset_name: "d", published_at: "2026-10-04T10:10:00Z", watermark: "2026-10-04T09:00:00Z", source_ids: ["src-a"], included_batch_ids: ["b1"], content_hash: "0" }, { publication_id: "p2", run_id: "run-1", dataset_name: "d", published_at: "2026-10-04T10:11:00Z", watermark: "2026-10-04T09:00:00Z", source_ids: ["src-a"], included_batch_ids: ["b1", "b2"], content_hash: "0" }] };
    const g = runPipeline(base).golden.metrics;
    const q = g.ingestion.sources["src-a"].quarantine_by_reason;
    return { ok: g.publications.publications.p1.published_records === 1 && g.publications.publications.p2.published_records === 0 && g.reconciliation.p2.residual === "0.00" && q.DELETE_TARGET_UNKNOWN === 1,
      lines: [`a publication of b1 shows ${g.publications.publications.p1.published_records} record; the next one, which includes the delete in b2, shows ${g.publications.publications.p2.published_records}`, `the delete enters the reconciliation as an exclusion of ${g.reconciliation.p2.exclusions.deletes}; residual ${g.reconciliation.p2.residual}`, `a delete of a key that was never accepted is quarantined: ${JSON.stringify(q)}`] };
  },
  "INJ-09": (c) => {
    const L = c.golden.g.metrics.late_events;
    const e = L.events[0];
    return { ok: L.count >= 1 && L.lost === 0 && !!e?.included_in_publication_id, lines: [`${e.source_key} (event ${e.event_at}) arrived ${e.arrival_at}, behind ${e.behind_publication_id} whose watermark is ${e.watermark}`, `included in ${e.included_in_publication_id}; late events ${L.count}, lost ${L.lost}`] };
  },
  "INJ-10": () => {
    const next: Record<string, string | null> = { A: "B", B: "C", C: "B" };
    let err = "ok";
    try { fetchAll((cur) => ({ status: 200, records: [{ cur }], next_cursor: next[cur] ?? null, retry_after_seconds: null }), "A", () => 0n, () => undefined); } catch (e) { err = e instanceof DomainError ? e.code : "error"; }
    return { ok: err === "CURSOR_LOOP", lines: [`pages A, B, C where C points back to B: ${err}`, "the fetch stops at the repeat within one session; a new session may poll the last cursor again (recorded as refetch)"] };
  },
  "INJ-11": () => {
    const lines = ["fetch ok authorization: Bearer abcdef1234567890xyz", "connect postgres://lab:hunter2@db:5432/x", "batch b-0001 committed 12 rows in 3 ms"];
    const out = lines.map(safeLine);
    return { ok: out.slice(0, 2).every((l) => !containsSecret(l) && l.includes("[REDACTED]")) && out[2] === lines[2], lines: out };
  },
  "INJ-12": () => ({ ok: true, lines: ["Not reproduced in the browser: the guard reads workflow text, which only the backend CI checks (SELF_PUSH, silenced by [skip ci])."] }),
};
export const NOT_IN_BROWSER = new Set(["INJ-12"]);
