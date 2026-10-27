// A loaded dataset: the published files (or the golden fixture), the evaluation the domain mirror ran over them in this browser, and the
// populations the evaluation views read. Nothing is fetched from a server beyond static files and nothing is invented: every figure is computed.
import { MODELS, type ModelName } from "../domain/contract";
import { rankItems, setMetrics, type Item } from "../domain/metrics";
import type { Id, Row } from "../domain/models";
import { p6, parseFraction, ratio, type Fr } from "../domain/num";
import { canonAscii, evaluate, sha256Hex, type Evaluation } from "../domain/pipeline";

export type DatasetId = "snapshot" | "golden";
export interface Strip { dataset_version: string; dataset_hash: string; generated_at: string; as_of: string; contract_version: string }

/** The five probability columns of the published test table (D-09 R10-14 added the prevalence constant). */
export const TEST_MODELS = ["random_baseline", "business_rule", "logistic_uncalibrated", "logistic_calibrated", "prevalence_baseline"] as const;
export type TestModel = (typeof TEST_MODELS)[number];
export const TEST_MODEL_LABEL: Record<TestModel, string> = {
  random_baseline: "Random baseline", business_rule: "Business rule", logistic_uncalibrated: "Logistic regression, before Platt scaling", logistic_calibrated: "Logistic regression (Platt-calibrated)",
  prevalence_baseline: "Prevalence constant (training prevalence for every account)",
};
export interface TestRow {
  account_id: number; cut: number; segment: string; region: string; usage_events_30d: number; days_since_last_usage: number | null; high_severity_support_90d: number;
  billing_total_90d: string | null; y: 0 | 1; p: Record<TestModel, string>;
}
export interface ModelSeries { key: string; label: string; role: "baseline" | "candidate" | "reference"; items: Item[] }
/** An evaluation population: the rows an outcome metric is computed on, with one series of probabilities per model. */
export interface Population { id: string; label: string; detail: string; models: ModelSeries[] }

export interface CutoffRow {
  prediction_at: string; range: string | null; cutoff_rows: number; eligible: number; mature: number; censored: number; churned: number; churn_rate: string | null;
  scored: number; evaluated: number; late_total: number; missingness_overall: string | null; ineligible: Record<string, number>;
}
export interface Dataset {
  id: DatasetId;
  strip: Strip;
  manifest: Row | null;
  inputs: Row;
  evals: Record<string, Evaluation>;
  modelKeys: string[];
  primaryModel: string;
  primary: Evaluation;
  runId: string;
  scenarios: Row[];
  populations: Population[];
  primarySeries: string;
  aggregates: Row | null; calibration: Row | null; splitSummary: Row | null; testRows: TestRow[] | null;
  injections: Row | null; injectionEvents: Row | null; training: Row | null;
  /** The generator's latent reference, kept ONLY for the disclosure on the evidence page; no computation reads it. */
  disclosure: Row | null;
  expected: Row | null;
  cutoffRows(): CutoffRow[];
  setAt(predictionAt: string, model?: string, scenarioId?: string | null): Row;
}

const itemCache = new WeakMap<TestRow, Partial<Record<TestModel, Item>>>();
export function testItem(r: TestRow, m: TestModel): Item {
  let c = itemCache.get(r);
  if (!c) { c = {}; itemCache.set(r, c); }
  return (c[m] ??= { p: parseFraction(r.p[m], false), pstr: r.p[m], y: r.y === 1, account_id: r.account_id, cutoff_id: `${r.account_id}@${r.cut}` });
}
/** Rank the rows of the test table under one model: probability descending, then account id ascending, then the earlier cutoff. */
export function rankTest(rows: TestRow[], m: TestModel): Item[] {
  const cut = new Map<Item, number>();
  const items = rows.map((r) => { const it = testItem(r, m); cut.set(it, r.cut); return it; });
  return rankItems(items, (a, b) => cut.get(a)! - cut.get(b)!);
}
export function parseTestCohort(file: Row): TestRow[] {
  const cols: string[] = file["head"]["columns"];
  const idx = (n: string): number => { const i = cols.indexOf(n); if (i < 0) throw new Error(`test_cohort.json: column ${n} is missing`); return i; };
  const c = Object.fromEntries(["account_id", "cutoff_index", "segment", "region", "usage_events_30d", "days_since_last_usage", "high_severity_support_90d", "billing_total_90d", "churned",
    "p_random_baseline", "p_business_rule", "p_logistic_uncalibrated", "p_logistic_calibrated", "p_prevalence_baseline"].map((n) => [n, idx(n)])) as Record<string, number>;
  return (file["rows"] as unknown[][]).map((r) => ({
    account_id: r[c["account_id"]!] as number, cut: r[c["cutoff_index"]!] as number, segment: r[c["segment"]!] as string, region: r[c["region"]!] as string,
    usage_events_30d: r[c["usage_events_30d"]!] as number, days_since_last_usage: r[c["days_since_last_usage"]!] as number | null,
    high_severity_support_90d: r[c["high_severity_support_90d"]!] as number, billing_total_90d: r[c["billing_total_90d"]!] as string | null, y: r[c["churned"]!] as 0 | 1,
    p: { random_baseline: r[c["p_random_baseline"]!] as string, business_rule: r[c["p_business_rule"]!] as string, logistic_uncalibrated: r[c["p_logistic_uncalibrated"]!] as string,
      logistic_calibrated: r[c["p_logistic_calibrated"]!] as string, prevalence_baseline: r[c["p_prevalence_baseline"]!] as string },
  }));
}
const monthLabel = (iso: string): string => iso.slice(0, 7);

function makePopulations(rows: TestRow[], cutoffs: string[]): Population[] {
  const models = (sub: TestRow[]): ModelSeries[] => [
    { key: "random_baseline", label: TEST_MODEL_LABEL.random_baseline, role: "baseline", items: rankTest(sub, "random_baseline") },
    { key: "business_rule", label: TEST_MODEL_LABEL.business_rule, role: "baseline", items: rankTest(sub, "business_rule") },
    { key: "prevalence_baseline", label: TEST_MODEL_LABEL.prevalence_baseline, role: "baseline", items: rankTest(sub, "prevalence_baseline") },
    { key: "logistic_uncalibrated", label: TEST_MODEL_LABEL.logistic_uncalibrated, role: "reference", items: rankTest(sub, "logistic_uncalibrated") },
    { key: "logistic_calibrated", label: TEST_MODEL_LABEL.logistic_calibrated, role: "candidate", items: rankTest(sub, "logistic_calibrated") },
  ];
  return [
    { id: "test", label: `Test range, ${cutoffs.map(monthLabel).join(" to ")} (union)`, detail: `${rows.length.toLocaleString("en-US")} mature eligible rows of the four test cutoffs, evaluated as one population`, models: models(rows) },
    ...cutoffs.map((c, i): Population => {
      const sub = rows.filter((r) => r.cut === i);
      return { id: `test-${i}`, label: `Test cutoff ${c.slice(0, 10)}`, detail: `${sub.length} mature eligible rows of the cutoff ${c.slice(0, 10)}`, models: models(sub) };
    }),
  ];
}

export function makeDataset(parts: Omit<Dataset, "cutoffRows" | "setAt" | "primary">): Dataset {
  const primary = parts.evals[parts.primaryModel]!;
  const memo = new Map<string, Row>();
  const setAt = (at: string, model?: string, scenario: string | null = null): Row => {
    const key = `${model ?? parts.primaryModel}|${at}|${scenario ?? ""}`;
    let v = memo.get(key);
    if (!v) { v = setMetrics(parts.evals[model ?? parts.primaryModel]!.world, parts.runId, at, scenario, null); memo.set(key, v); }
    return v;
  };
  const cutoffRows = (): CutoffRow[] => {
    if (parts.aggregates) {
      return (parts.aggregates["cutoffs"] as Row[]).map((c): CutoffRow => ({
        prediction_at: c["prediction_at"], range: c["range"], cutoff_rows: c["population"]["cutoff_rows"], eligible: c["population"]["eligible"], mature: c["population"]["mature"],
        censored: c["population"]["censored"], churned: c["population"]["churned"], churn_rate: p6(ratio(c["population"]["churned"], c["population"]["mature"])),
        scored: c["population"]["scored"], evaluated: c["population"]["evaluated"], late_total: c["late_events"]["total"], missingness_overall: c["missingness"]["overall"], ineligible: c["population"]["ineligible"],
      }));
    }
    return primary.world.predictionAts().map((at): CutoffRow => {
      const m = setAt(at);
      return { prediction_at: at, range: null, cutoff_rows: m["population"]["cutoff_rows"], eligible: m["population"]["eligible"], mature: m["population"]["mature"], censored: m["population"]["censored"],
        churned: m["population"]["churned"], churn_rate: m["churn_rate"]["value"], scored: m["population"]["scored"], evaluated: m["population"]["evaluated"], late_total: m["late_events"]["total"],
        missingness_overall: m["feature_missingness"]["overall"]["value"], ineligible: m["population"]["ineligible"] };
    });
  };
  return { ...parts, primary, cutoffRows, setAt };
}

// ------------------------------------------------------------------------------------------------------ the published snapshot
export const SNAPSHOT_FILES = ["manifest", "accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels", "training_runs",
  "predictions", "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments", "scoring_publications", "calibration", "cutoff_aggregates", "split_summary", "test_cohort",
  "injection-manifest", "injection-events"] as const;
const rowsOf = (files: ReadonlyMap<string, unknown>, name: string): Row[] => {
  const f = files.get(name) as { rows?: Row[] } | undefined;
  if (!f || !Array.isArray(f.rows)) throw new Error(`${name}.json: no rows array`);
  return f.rows;
};
export const isManifest = (m: unknown): boolean => {
  const x = m as Row | null;
  return !!x && typeof x["dataset_version"] === "string" && typeof x["dataset_hash"] === "string" && typeof x["generated_at"] === "string" && typeof x["as_of"] === "string"
    && !!x["config"] && typeof x["config"] === "object" && Array.isArray(x["designed_relationships"]);
};

/** Build the snapshot dataset from its parsed files. Throws a readable error when a file is not what the page expects. */
export async function buildSnapshot(files: ReadonlyMap<string, unknown>): Promise<Dataset> {
  const manifestFile = files.get("manifest") as Row;
  if (!isManifest(manifestFile)) throw new Error("manifest.json: required fields are missing");
  // The generator's latent propensities are a disclosure, never an input: keep the reference line and drop the per-row values at once.
  const truth = manifestFile["synthetic_truth"] as Row | undefined;
  const disclosure: Row | null = truth ? { note: truth["note"], latent_reference_test: truth["latent_reference_test"], unobserved_designs: truth["unobserved_designs"], roles: truth["roles"], hidden_risk_accounts: truth["hidden_risk_accounts"] } : null;
  const manifest: Row = { ...manifestFile };
  delete manifest["synthetic_truth"];
  const cfg = manifest["config"] as Row;
  const base: Row = { contract_version: 1, as_of: manifest["as_of"], label_version: cfg["label_version"], feature_version_spec: cfg["feature_version_spec"] };
  const entities = ["accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels", "training_runs", "predictions",
    "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments", "scoring_publications"];
  for (const e of entities) base[e] = rowsOf(files, e);
  const runId = cfg["training_run_id"] as string;
  const configHashes = Object.fromEntries(await Promise.all((base["training_runs"] as Row[]).map(async (r) => [r["training_run_id"], await sha256Hex(canonAscii(r["config"]))] as const)));
  const ats = [...new Set((base["prediction_cutoffs"] as Row[]).map((c) => c["prediction_at"] as string))].sort();
  const evals: Record<string, Evaluation> = {};
  for (const m of MODELS) {
    const data: Row = { ...base, predictions: (base["predictions"] as Row[]).filter((p) => p["model_name"] === m), scoring_publications: (base["scoring_publications"] as Row[]).filter((p) => p["model_name"] === m),
      scope: { training_run_id: runId, sets: ats.map((at) => ({ prediction_at: at, scenario_id: null })) } };
    evals[m] = evaluate(data, configHashes);
  }
  const testRows = parseTestCohort(files.get("test_cohort") as Row);
  const aggregates = files.get("cutoff_aggregates") as Row;
  const testCutoffs: string[] = (files.get("test_cohort") as Row)["head"]["cutoffs"];
  return makeDataset({
    id: "snapshot",
    strip: { dataset_version: manifest["dataset_version"], dataset_hash: manifest["dataset_hash"], generated_at: manifest["generated_at"], as_of: manifest["as_of"], contract_version: String(manifest["contract_version"]) },
    manifest, inputs: base, evals, modelKeys: [...MODELS], primaryModel: "logistic_regression", runId, scenarios: base["intervention_scenarios"],
    populations: makePopulations(testRows, testCutoffs), primarySeries: "logistic_calibrated",
    aggregates, calibration: files.get("calibration") as Row, splitSummary: files.get("split_summary") as Row, testRows,
    injections: files.get("injection-manifest") as Row, injectionEvents: files.get("injection-events") as Row, training: manifest["training"], disclosure, expected: null,
  });
}

// ------------------------------------------------------------------------------------------------------ the golden fixture
/** The golden case: the fixture's inputs evaluated in this browser, its expected results alongside (never used to compute anything). */
export async function buildGolden(inputsText: string, expected: Row): Promise<Dataset> {
  const inputs = JSON.parse(inputsText) as Row;
  const run = (inputs["training_runs"] as Row[])[0]!;
  const hashes = Object.fromEntries(await Promise.all((inputs["training_runs"] as Row[]).map(async (r) => [r["training_run_id"], await sha256Hex(canonAscii(r["config"]))] as const)));
  const ev0 = evaluate(inputs, hashes);
  const jan = ev0.result["cutoff_sets"]["2026-01-01T00:00:00Z"] as Row | undefined;
  const items: Item[] = jan ? (jan["ranking"] as Row[]).map((r) => ({ p: parseFraction(r["probability"]), pstr: r["probability"], y: r["outcome"] === 1, account_id: r["account_id"] as Id, cutoff_id: r["cutoff_id"] })) : [];
  return makeDataset({
    id: "golden",
    strip: { dataset_version: "golden-fixture-v1", dataset_hash: await sha256Hex(inputsText), generated_at: inputs["as_of"], as_of: inputs["as_of"], contract_version: String(inputs["contract_version"]) },
    manifest: null, inputs, evals: { default: ev0 }, modelKeys: ["default"], primaryModel: "default", runId: run["training_run_id"], scenarios: inputs["intervention_scenarios"],
    populations: [{ id: "golden-2026-01", label: "Golden set 2026-01-01", detail: `${items.length} mature eligible rows with an accepted prediction (the fixture's P10-GOLD-01 set)`,
      models: [{ key: "frozen", label: "Frozen predictions of the fixture", role: "candidate", items }] }],
    primarySeries: "frozen", aggregates: null, calibration: null, splitSummary: null, testRows: null, injections: null, injectionEvents: null, training: null, disclosure: null, expected,
  });
}

export const modelLabel = (k: string): string => (MODELS as readonly string[]).includes(k) ? ({ random_baseline: "Random baseline", business_rule: "Business rule", logistic_regression: "Logistic regression (Platt)", prevalence_baseline: "Prevalence constant" } as Record<string, string>)[k]! : k === "default" ? "Frozen predictions" : k;
export type { Fr, ModelName };
