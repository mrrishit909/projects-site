// The whole domain over one import: validation, point-in-time rebuild, consistency of the stored derived rows, the fixture's command requests,
// the split, every metric. `evaluate(inputs)` equals `expected.json` leaf for leaf on the golden fixture and both variants.
import { CONTRACT_VERSION, ENTITIES } from "./contract";
import * as E from "./errors";
import { validate, type Ingest } from "./ingest";
import { freshness, itemOf, publications, rankItems, setMetrics, type Item, type Publication } from "./metrics";
import type { Id, Row } from "./models";
import { canon, deepEqual } from "./models";
import { checkCalibrationRows, checkCapacity, checkFeatureRequest, checkFitRows, checkThreshold } from "./rules";
import { retained, splitRun, type SplitRow, type SplitCounts } from "./split";
import { daysUs, parseTs } from "./time";
import { World } from "./world";

export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
/** D-P10-17: the SHA-256 of the canonical JSON of a training run's `config`. The canonical form here escapes non-ASCII like Python's ensure_ascii. */
export const canonAscii = (v: unknown): string => canon(v).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);

type Splits = Map<string, [SplitRow[], Record<string, SplitCounts>]>;
const sortedStrings = (xs: string[]): string[] => [...xs].sort();

/** The stored derived rows that differ from the rebuilt ones (D-P10-19). Empty lists mean the stored rows are what the application would have
 * produced. `configHashes` maps a training_run_id to the SHA-256 of its canonical config (computed by the caller: hashing is asynchronous in a browser). */
export function consistency(world: World, ingest: Ingest, splits: Splits, pubs: Publication[], queues: Record<string, Id[]>, configHashes: Record<string, string> | null): Record<string, string[]> {
  const acc = ingest.accepted;
  const out: Record<string, string[]> = { cutoff_windows_mismatched: [], feature_rows_mismatched: [], labels_mismatched: [], split_assignments_mismatched: [],
    scoring_publications_mismatched: [], config_hash_mismatched: [], outreach_queue_mismatched: [], predictions_citation_mismatched: [] };
  for (const c of acc.prediction_cutoffs) {
    const pa = parseTs(c["prediction_at"]);
    if (parseTs(c["horizon_end"]) !== pa + daysUs(world.horizon) || parseTs(c["observation_start"]) !== pa - daysUs(world.obsDays)) out["cutoff_windows_mismatched"]!.push(c["cutoff_id"]);
  }
  for (const fr of acc.feature_rows) {
    const a = world.analyse(fr["cutoff_id"]);
    if (!(a.eligible && deepEqual(fr["features_json"], a.features) && fr["max_available_at"] === a.max_available_at && fr["feature_version"] === world.featureVersion
      && (fr["max_available_at"] === null || parseTs(fr["max_available_at"]) < parseTs(a.prediction_at)))) out["feature_rows_mismatched"]!.push(fr["feature_row_id"]);
  }
  for (const lb of acc.labels) {
    const a = world.analyse(lb["cutoff_id"]);
    if (!(a.eligible && lb["churned"] === a.churned && lb["mature"] === a.mature && lb["label_end"] === a.label_end)) out["labels_mismatched"]!.push(lb["label_id"]);
  }
  if (configHashes) for (const r of acc.training_runs) if (configHashes[r["training_run_id"]] !== r["config_hash"]) out["config_hash_mismatched"]!.push(r["training_run_id"]);
  for (const p of acc.predictions) {
    const run = world.runs.get(p["training_run_id"])!;
    if (p["config_hash"] !== run["config_hash"] || p["feature_version"] !== run["config"]["feature_version"] || p["label_version"] !== run["config"]["label_version"]) out["predictions_citation_mismatched"]!.push(p["prediction_id"]);
  }
  for (const sa of acc.split_assignments) {
    const d = new Map(splits.get(sa["training_run_id"])![0].map((r) => [r.cutoff_id, r])).get(sa["cutoff_id"])!;
    if (sa["split"] !== d.split || sa["status"] !== d.status || sa["drop_reason"] !== d.drop_reason) out["split_assignments_mismatched"]!.push(sa["assignment_id"]);
  }
  const storedStatus = new Map(acc.scoring_publications.map((sp) => [sp["publication_id"], sp["status"]]));
  for (const p of pubs) if (storedStatus.get(p.publication_id) !== p.status) out["scoring_publications_mismatched"]!.push(p.publication_id);
  for (const [scenarioId, rebuilt] of Object.entries(queues)) {
    const stored = sortedStrings(acc.outreach_events.filter((o) => o["scenario_id"] === scenarioId).map((o) => String(o["account_id"])));
    if (JSON.stringify(stored) !== JSON.stringify(sortedStrings(rebuilt.map(String)))) out["outreach_queue_mismatched"]!.push(scenarioId);
  }
  return out;
}

/** One fixture request through the same refusal rules the API uses. */
export function runRequest(world: World, rq: Row, splits: Splits): Row {
  const res: Row = { request_id: rq["request_id"], command: rq["command"], status: "accepted", reason_code: null, offending: [], result: null };
  try {
    const cmd = rq["command"];
    if (cmd === "build-point-in-time-features") { res["result"] = { fields: checkFeatureRequest(world.registry, rq["fields"]) }; return res; }
    const run = world.runs.get(rq["training_run_id"]);
    if (!run) throw new E.DomainError(E.UNKNOWN_TRAINING_RUN, "unknown training run", null, [{ item: rq["training_run_id"] ?? null, code: E.UNKNOWN_TRAINING_RUN }]);
    const rows = splits.get(run["training_run_id"])![0];
    if (cmd === "fit-preprocessing") { checkFitRows(rq["fit_rows"], retained(rows, "train")); res["result"] = { fit_rows: rq["fit_rows"].length }; }
    else if (cmd === "calibrate-model") { checkCalibrationRows(rq["fit_rows"], rq["evaluation_rows"], retained(rows, "validation")); res["result"] = { fit_rows: rq["fit_rows"].length, evaluation_rows: rq["evaluation_rows"].length }; }
    else if (cmd === "select-threshold") { checkThreshold(rq["parameter"], rq["selected_on"]); res["result"] = { parameter: rq["parameter"], selected_on: "validation" }; }
    else if (cmd === "prioritize-outreach") {
      const scenario = world.scenarios.get(rq["scenario_id"]);
      if (!scenario) throw new E.DomainError(E.UNKNOWN_SCENARIO, "unknown scenario", null, [{ item: rq["scenario_id"], code: E.UNKNOWN_SCENARIO }]);
      const pool = rankItems(world.setRows(rq["prediction_at"]).filter((r) => r.eligible && world.pred(run["training_run_id"], r.cutoff_id)).map((r): Item => {
        return itemOf(world.pred(run["training_run_id"], r.cutoff_id)!["probability"], false, r.account_id as Id, r.cutoff_id);
      }));
      checkCapacity(scenario["scenario_id"], scenario["capacity"], pool.length);
      res["result"] = { capacity: scenario["capacity"], population: pool.length, status: "draft", queue_account_ids: pool.slice(0, scenario["capacity"]).map((q) => q.account_id) };
    }
  } catch (err) {
    if (!(err instanceof E.DomainError)) throw err;
    Object.assign(res, { status: "refused", reason_code: err.code, offending: err.offending, result: null });
  }
  return res;
}

export interface Evaluation {
  world: World; ingest: Ingest; splits: Splits; pubs: Publication[]; result: Row;
}
/** Evaluate an import. `configHashes` (optional) are the SHA-256 digests of the runs' canonical configs; the browser computes them with Web Crypto. */
export function evaluate(data: Row, configHashes: Record<string, string> | null = null): Evaluation {
  const ingest = validate(data);
  const world = new World(data, ingest.accepted);
  const splits: Splits = new Map(ingest.accepted.training_runs.map((run) => [run["training_run_id"], splitRun(world, run)]));
  const pubs = publications(world);
  const scope = data["scope"];
  const sets: Record<string, Row> = {};
  const pointInTime: Row[] = [];
  const queues: Record<string, Id[]> = {};
  for (const sc of scope["sets"] as Row[]) {
    const m = setMetrics(world, scope["training_run_id"], sc["prediction_at"], sc["scenario_id"] ?? null, scope["drift"] ?? null);
    sets[sc["prediction_at"]] = m;
    pointInTime.push(...world.setRows(sc["prediction_at"]));
    if (sc["scenario_id"] && m["outreach_queue"] !== null) queues[sc["scenario_id"]] = m["outreach_queue"]["account_ids"];
  }
  const drift = scope["drift"];
  if (drift) {
    const have = new Set(pointInTime.map((r) => r["cutoff_id"]));
    pointInTime.push(...world.setRows(drift["reference_prediction_at"]).filter((r) => !have.has(r.cutoff_id)));
  }
  const result: Row = {
    contract_version: data["contract_version"], as_of: data["as_of"],
    ingest: { counts: ingest.counts(), rejected_records: ingest.rejected },
    consistency: consistency(world, ingest, splits, pubs, queues, configHashes),
    commands: ((data["requests"] ?? []) as Row[]).map((rq) => runRequest(world, rq, splits)),
    split: Object.fromEntries([...splits].map(([rid, [rs, counts]]) => [rid, { train_end: world.runs.get(rid)!["train_end"], validation_end: world.runs.get(rid)!["validation_end"], test_end: world.runs.get(rid)!["test_end"],
      embargo_days: world.horizon + world.grace, counts, assignments: rs.map((r) => ({ cutoff_id: r.cutoff_id, split: r.split, status: r.status, drop_reason: r.drop_reason })) }])),
    point_in_time: { rows: pointInTime },
    scoring_publications: pubs,
    freshness: freshness(world, pubs),
    cutoff_sets: sets,
    empty_population: Object.keys(sets).length ? Object.values(sets).every((s) => s["empty_population"]) : true,
  };
  return { world, ingest, splits, pubs, result };
}
export { CONTRACT_VERSION, ENTITIES };
