// Selectors over a Dataset that more than one screen needs. Pure; no arithmetic on a displayed figure beyond what the domain returned.
import type { Dataset } from "../data/analyse";
import type { Row } from "../domain/contract";
import { sortedBy } from "../domain/py";
import { dur, dayTimeS } from "./format";
import { safeLine } from "../domain/redaction";
import { isoZ, parseTs, secondsBetween } from "../domain/time";

export const runsOf = (ds: Dataset): Row[] => sortedBy(ds.acc["pipeline_runs"]!, (r) => [parseTs(r["started_at"]), r["run_id"] as string]);
export const gateOf = (ds: Dataset, runId: string): Row | undefined => ds.g.metrics.quality_gate[runId];
export const blockedRunIds = (ds: Dataset): string[] => runsOf(ds).filter((r) => gateOf(ds, r["run_id"])?.decision === "blocked").map((r) => r["run_id"] as string);

export interface Verdict { tone: "ok" | "warn" | "bad"; headline: string; rule: string; reasons: string[] }
/** The one-line answer to the decision, by a rule printed with it: the latest gate blocked -> do not publish; any source silent -> publish with a stated
 * exception; otherwise publish. It is a reading of the evidence, not a gate. */
export function verdict(ds: Dataset): Verdict {
  const runs = runsOf(ds);
  const last = runs[runs.length - 1];
  const gate = last ? gateOf(ds, last["run_id"]) : undefined;
  const silent = ds.freshness.filter((f) => f.silent);
  const pastTarget = ds.freshness.filter((f) => f.past_target);
  const reasons: string[] = [];
  if (last) reasons.push(`latest run ${last["run_id"]}: gate ${gate?.decision ?? "unknown"}, run ${last["status"]}`);
  reasons.push(`${ds.freshness.length - silent.length} of ${ds.freshness.length} sources produce new events at their declared cadence${silent.length ? `; silent: ${silent.map((f) => f.source_id).join(", ")}` : ""}`);
  if (pastTarget.length) reasons.push(`past their own freshness target: ${pastTarget.map((f) => f.source_id).join(", ")}`);
  const rule = "Rule: latest gate blocked, or a source past its target, means do not publish; a source silent for more than two of its declared cadences means publish with a stated exception; otherwise publish.";
  if (!last || gate?.decision === "blocked" || pastTarget.length) return { tone: "bad", headline: "Do not publish this dataset", rule, reasons };
  if (silent.length) return { tone: "warn", headline: `Publish, with a stated exception: ${silent.map((f) => f.source_id).join(", ")} ${silent.length === 1 ? "is" : "are"} silent`, rule, reasons };
  return { tone: "ok", headline: "Publish: every source is current and the latest gate is allowed", rule, reasons };
}

/** Checkpoints committed after the previous run started and up to this run's start: what the run found waiting. */
export function intake(ds: Dataset, runId: string): Row[] {
  const runs = runsOf(ds);
  const i = runs.findIndex((r) => r["run_id"] === runId);
  if (i < 0) return [];
  const lo = i > 0 ? parseTs(runs[i - 1]!["started_at"]) : -(10n ** 18n), hi = parseTs(runs[i]!["started_at"]);
  return sortedBy(ds.acc["checkpoints"]!.filter((c) => parseTs(c["committed_at"]) > lo && parseTs(c["committed_at"]) <= hi), (c) => [parseTs(c["committed_at"]), c["checkpoint_id"] as string]);
}
export interface LogLine { at: string | null; text: string; withheld: boolean }
/** The run's evidence as structured log lines, built only from published rows; every line passes the redaction check (a line that still matches a
 * secret pattern would be withheld whole). */
export function runLog(ds: Dataset, runId: string): LogLine[] {
  const run = ds.acc["pipeline_runs"]!.find((r) => r["run_id"] === runId);
  if (!run) return [];
  const out: LogLine[] = [];
  const add = (at: string | null, text: string): void => { const t = safeLine(text); out.push({ at, text: t, withheld: t !== text && t.startsWith("[LOG LINE WITHHELD") }); };
  add(isoZ(run["started_at"]), `run ${runId} started code_sha=${run["code_sha"]}${run["backfill_id"] ? ` backfill=${run["backfill_id"]}` : ""}`);
  const batchOf = new Map<string, Row>(ds.acc["ingestion_batches"]!.map((b) => [b["batch_id"], b]));
  const fetchOf = new Map<string, Row[]>();
  for (const f of ds.raw?.fetch_log ?? []) { const a = fetchOf.get(f["batch_id"]) ?? []; a.push(f); fetchOf.set(f["batch_id"], a); }
  for (const c of intake(ds, runId)) {
    const b = batchOf.get(c["batch_id"]);
    for (const f of fetchOf.get(c["batch_id"]) ?? []) add(isoZ(f["fetched_at"]), `fetch ${f["source_id"]} cursor=${f["cursor_value"]} -> ${f["status"]}`);
    add(isoZ(c["committed_at"]), `batch ${c["batch_id"]} (${b?.["source_id"] ?? c["source_id"]}) committed with checkpoint v${c["version_number"]} cursor=${c["committed_cursor"]}`);
  }
  const tasks = sortedBy(ds.acc["task_runs"]!.filter((t) => t["run_id"] === runId), (t) => [t["task_name"] === "ingest" ? 0 : t["task_name"] === "transform" ? 1 : t["task_name"] === "quality_gate" ? 2 : 3, Number(t["attempt"])]);
  for (const t of tasks) add(null, `task ${t["task_name"]} attempt ${t["attempt"]} ${t["status"]}`);
  const gate = gateOf(ds, runId);
  if (gate) {
    for (const [rule, r] of Object.entries(gate.results as Record<string, Row>)) add(null, `gate ${rule} ${r["severity"]} eligible=${r["eligible"]} failures=${r["failures"]} ${r["passed"] ? "pass" : "FAIL"}`);
    add(null, `gate decision ${gate.decision}`);
  }
  const pub = ds.acc["publications"]!.find((p) => p["run_id"] === runId);
  const hist = ds.g.metrics.publications.pointer_history as Row[];
  const h = hist.find((x) => x["run_id"] === runId);
  if (pub) add(isoZ(pub["published_at"]), `published ${pub["publication_id"]} watermark=${isoZ(pub["watermark"])} included_batches=${(pub["included_batch_ids"] as string[]).length}`);
  else add(null, `no publication row: ${gate?.decision === "blocked" ? "the gate blocked this run" : `run ${run["status"]}`}`);
  if (h) add(null, `pointer ${h["pointer_after"] && pub && h["pointer_after"] === pub["publication_id"] ? "moved to" : "unchanged at"} ${h["pointer_after"] ?? "(none)"}`);
  if (run["finished_at"]) add(isoZ(run["finished_at"]), `run ${runId} finished status=${run["status"]} duration=${dur(secondsBetween(run["started_at"], run["finished_at"]))}`);
  return out;
}
export const timeLabel = (iso: string | null): string => (iso ? dayTimeS(iso) : "—");

/** The diagnosis the published rows support for a run: failed checks of its gate, else failed tasks. */
export function diagnosis(ds: Dataset, runId: string): string {
  const fc = ds.failedChecks[runId] ?? [];
  if (fc.length) return fc.map((c) => `${c.rule} (${c.failures} of ${c.eligible} ${c.severity})`).join("; ");
  const failed = ds.acc["task_runs"]!.filter((t) => t["run_id"] === runId && t["status"] === "failed");
  return failed.length ? `task ${[...new Set(failed.map((t) => t["task_name"]))].join(", ")} failed` : "no failed check or task recorded";
}
export function downloadCsv(name: string, header: string[], rows: (string | number | null)[][]): void {
  const esc = (v: string | number | null): string => { const s = v === null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const text = [header, ...rows].map((r) => r.map(esc).join(",")).join("\n") + "\n";
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
