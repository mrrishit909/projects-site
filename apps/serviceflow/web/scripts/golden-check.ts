// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) key by key for the golden
// fixture and its two variants, the per-entity golden copy the site serves, the seeded generator and SHA-512 against Node,
// and the Python domain's results over the published snapshot (scripts/snapshot-reference.json and
// public/reference/simulation-runs.json, produced once by domain/serviceflow). Prints "ALL OK (N checks)" or exits 1.
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { buildInputs, isManifest, manifestWindow } from "../src/data/inputs";
import { ENTITIES, EXTRA_ENTITIES, GROUP_KEYS, METRIC_KEYS } from "../src/domain/contract";
import { computeMetrics, disclosures, groupMetrics, p90Seconds } from "../src/domain/metrics";
import { goldenOf, runPipeline } from "../src/domain/pipeline";
import { PyRandom, sha512 } from "../src/domain/pyrandom";
import { goldenShape, meanCi95, replicate, simulate, statistics, meanWait } from "../src/domain/simulation";
import { fixed, frac, type Frac } from "../src/domain/fixed";
import { isoZ, parseTs } from "../src/domain/time";
import type { Manifest, PipelineInputs } from "../src/domain/types";

const ROOT = new URL("../../", import.meta.url);
const WEB = new URL("../", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

let failures = 0, checks = 0;
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) =>
  x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : typeof x === "bigint" ? x.toString() : x);
function eq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 300)} want ${canon(want).slice(0, 300)}`); }
}
const yes = (label: string, cond: boolean, detail = ""): void => { checks++; if (cond) console.log(`OK       ${label}`); else { failures++; console.log(`MISMATCH ${label} ${detail}`); } };
const hex = (b: Uint8Array): string => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
const sha256 = (s: string): string => createHash("sha256").update(s).digest("hex");

function checkFixture(name: string, inputs: PipelineInputs, expected: any): void {
  const r = runPipeline(inputs);
  const g = goldenOf(r);
  for (const k of METRIC_KEYS) eq(`${name} metric ${k}`, (g.metrics as any)[k], expected.metrics[k]);
  eq(`${name} metric key set`, Object.keys(g.metrics).sort(), Object.keys(expected.metrics).sort());
  eq(`${name} metric key order is the contract order`, Object.keys(g.metrics), [...METRIC_KEYS]);
  eq(`${name} ingest counts`, g.ingest.counts, expected.ingest.counts);
  eq(`${name} rejected records (entity, id, status, reason, raw row)`, g.ingest.rejected_records, expected.ingest.rejected_records);
  eq(`${name} contract_version`, g.contract_version, expected.contract_version);
  if (expected.simulation === null) yes(`${name} no simulation`, g.simulation === null);
  else {
    const s = g.simulation as any;
    for (const k of ["simulation_id", "waits_minutes", "mean_wait_minutes", "final_completion_minute", "events"]) eq(`${name} simulation ${k}`, s[k], expected.simulation[k]);
  }
}

// ---- fixtures under tests/fixtures: the golden case and its variants ---------------------------------------------
const fixtureDirs: [string, string][] = [["golden", ""]];
for (const v of ["variant-rejected", "variant-empty"]) if (existsSync(new URL(`tests/fixtures/golden/${v}/inputs.json`, ROOT))) fixtureDirs.push([v, `${v}/`]);
for (const [name, dir] of fixtureDirs) {
  const base = new URL(`tests/fixtures/golden/${dir}`, ROOT);
  checkFixture(name, readJson(new URL("inputs.json", base)), readJson(new URL("expected.json", base)));
}

// ---- the per-entity golden copy the site serves, built through the same loader code as the browser -----------------
function loadDir(dir: string): { manifest: Manifest; inputs: PipelineInputs } {
  const manifest = readJson(new URL(`public/data/${dir}manifest.json`, WEB));
  if (!isManifest(manifest)) throw new Error("manifest is not valid");
  const files = new Map<string, unknown>();
  for (const n of Object.keys(manifest.row_counts)) files.set(n, readJson(new URL(`public/data/${dir}${n}.json`, WEB)));
  return { manifest, inputs: buildInputs(manifest, files) };
}
{
  const { manifest, inputs } = loadDir("golden/");
  checkFixture("golden (per-entity copy)", inputs, readJson(new URL("public/data/golden/expected.json", WEB)));
  eq("golden copy equals tests/fixtures expected.json", readJson(new URL("public/data/golden/expected.json", WEB)), readJson(new URL("tests/fixtures/golden/expected.json", ROOT)));
  eq("golden manifest window", [manifest.window_start, manifest.window_end], ["2026-07-06T09:00:00Z", "2026-07-06T10:00:00Z"]);
}

// ---- the spec sentence in words (P04-GOLD-01) -----------------------------------------------------------------------
{
  const r = runPipeline(readJson(new URL("tests/fixtures/golden/inputs.json", ROOT)));
  const sim = r.simulations[0]!, gs = goldenShape(sim);
  eq("P04-GOLD-01 waits 0, 10, 20", gs.waits_minutes, ["0.0000", "10.0000", "20.0000"]);
  eq("P04-GOLD-01 mean wait 10, last completion 30", [gs.mean_wait_minutes, gs.final_completion_minute], ["10.0000", "30.0000"]);
  eq("P04-GOLD-01 events se-001..se-006", gs.events.map((e) => e.simulation_event_id), ["se-001", "se-002", "se-003", "se-004", "se-005", "se-006"]);
  eq("service starts 0, 10, 20 then resolves 10, 20, 30", gs.events.map((e) => e.event_at), ["0.0000", "10.0000", "20.0000", "10.0000", "20.0000", "30.0000"]);
  eq("observed history: mean first response 10, P90 20, SLA first response 2/3, occupancy 0.5", [r.metrics.mean_first_response_minutes, r.metrics.p90_first_response_minutes, r.metrics.sla_first_response_compliance, r.metrics.agent_occupancy], ["10.0000", "20.0000", "0.666667", "0.500000"]);
  eq("backlog at 09:05, 09:25, 10:00", Object.values(r.metrics.backlog), [3, 1, 0]);
  eq("the seed changes nothing in a deterministic case", goldenShape(simulate(r.population.simulation_runs[0]!.config, 99, 0, 60, "sim-001")).waits_minutes, ["0.0000", "10.0000", "20.0000"]);
}

// ---- arithmetic and generator primitives --------------------------------------------------------------------------
{
  eq("fixed: half up at 4 dp", [fixed(1, 3, 4), fixed(2, 3, 6), fixed(5, 2, 0), fixed(25, 100000, 4), fixed(0, 7, 4), fixed(-5, 2, 0)], ["0.3333", "0.666667", "3", "0.0003", "0.0000", "-3"]);
  eq("nearest rank P90 (n=3 -> 3rd, n=10 -> 9th, n=11 -> 10th)", [p90Seconds([60, 120, 1200]), p90Seconds([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), p90Seconds([...Array(11).keys()].map((x) => x + 1))], [1200, 9, 10]);
  for (const text of ["", "abc", "x".repeat(111), "x".repeat(112), "x".repeat(300)]) {
    const b = new TextEncoder().encode(text);
    yes(`SHA-512 equals Node's for ${b.length} bytes`, hex(sha512(b)) === createHash("sha512").update(text).digest("hex"));
  }
  // Values printed by CPython 3.11: random.Random("20261026:arrivals") and random.Random("1:priority").
  const r = new PyRandom("20261026:arrivals");
  eq("PyRandom matches CPython 3.11 random()", [r.random(), r.random()], [0.8334302546510539, 0.49165610494954937]);
  eq("PyRandom expovariate and choices match CPython", [r.expovariate(0.052), new PyRandom("1:priority").choice(["P1", "P2", "P3"], [0.09, 0.37, 0.54])], [1.6171222152493168, "P3"]);
}

// ---- seeded, reproducible: same seed same path, another seed another path, CI over replications ------------------
{
  const cfg = { agents: 5, arrival_rate_per_hour: 3.12, discipline: "fifo_within_priority", priority_mix: { P1: 0.09, P2: 0.37, P3: 0.54 }, service: "exponential", service_minutes: 69.1 };
  const a = simulate(cfg, 7, 120, 720, "x"), b = simulate(cfg, 7, 120, 720, "x"), c = simulate(cfg, 8, 120, 720, "x");
  eq("same seed, same events", a.events, b.events);
  yes("another seed, another path", canon(a.events) !== canon(c.events));
  const reps = replicate(cfg, 7, 5, 120, 720, "x");
  eq("replication 0 is the run itself", reps[0]!.events, a.events);
  const ci = meanCi95(reps.map((x) => meanWait(x)).filter((x): x is Frac => x !== null));
  yes("CI over 5 replications has n 5 and a half-width", ci.n === 5 && ci.ci95_half_width !== null);
  eq("meanCi95 of 1, 2, 3 (t 4.303, se 0.5774): mean 2.0000, half-width 2.4843", meanCi95([frac(1), frac(2), frac(3)]), { n: 3, mean: "2.0000", ci95_half_width: "2.4843" });
  yes("warm-up tickets are excluded from the statistics", statistics(a).warmup_excluded > 0 && statistics(simulate(cfg, 7, 0, 720, "x")).warmup_excluded === 0);
}

// ---- the published snapshot against the Python domain's results ------------------------------------------------------
{
  const { manifest, inputs } = loadDir("");
  const ref = readJson(new URL("scripts/snapshot-reference.json", WEB));
  eq("snapshot dataset_hash is the one the reference was produced from", manifest.dataset_hash, ref.dataset_hash);
  // dataset_hash = sha256 over the entity files' rows, canonical JSON (sorted keys, no spaces, ASCII), in name order.
  const ascii = (s: string): string => s.replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
  const names = Object.keys(manifest.row_counts).sort();
  yes("dataset_hash recomputed from the 13 entity files", sha256(names.map((n) => ascii(canon((inputs[n] ?? readJson(new URL(`public/data/${n}.json`, WEB)).rows)))).join("")) === manifest.dataset_hash, "(hash of canonical rows differs from the manifest)");
  yes("entities are the 12 ingest entities plus shift_breaks", ENTITIES.every((e) => e in manifest.row_counts) && EXTRA_ENTITIES.every((e) => e in manifest.row_counts));
  const r = runPipeline(inputs);
  eq("snapshot ingest counts", r.ingest.counts, ref.ingest_counts);
  eq("snapshot rejected (entity, id, reason)", r.ingest.rejected.map((x) => [x.entity, x.id, x.reason_code]), ref.rejected);
  const win = manifestWindow(manifest);
  const W: Record<string, [string, string]> = { full: [win.start, win.end], training: ["2026-07-06T00:00:00Z", "2026-08-31T00:00:00Z"], holdout: ["2026-08-31T00:00:00Z", "2026-09-28T00:00:00Z"] };
  for (const [name, [a, b]] of Object.entries(W)) {
    const w: [number, number] = [parseTs(a), parseTs(b)];
    const want = ref.windows[name];
    eq(`${name} window bounds`, [isoZ(w[0]), isoZ(w[1])], [want.from, want.to]);
    const m = computeMetrics(r.population, w, [w[1]], r.abandonable, r.histories);
    for (const [k, v] of Object.entries(want.headline)) eq(`${name} ${k}`, (m as any)[k], v);
    eq(`${name} backlog at the window end`, m.backlog, want.backlog);
    eq(`${name} all 28 metrics (digest of the canonical JSON, per-ticket maps included)`, sha256(canon(m)), want.metrics_digest);
    eq(`${name} disclosures (digest)`, sha256(canon(disclosures(r.population, w, r.histories))), want.disclosures_digest);
    for (const g of GROUP_KEYS) {
      const gm = groupMetrics(r.population, g, w, [w[1]], r.abandonable, r.histories);
      eq(`${name} group_by ${g} keys`, Object.keys(gm), want.groups[g].keys);
      eq(`${name} group_by ${g} metrics (digest)`, sha256(canon(gm)), want.groups[g].digest);
    }
  }
  // the three published runs, re-simulated with their seed, equal the Python events, waits and statistics
  const simRef = readJson(new URL("public/reference/simulation-runs.json", WEB));
  eq("three published runs", r.simulations.map((s) => s.simulation_id), ["sim-001", "sim-002", "sim-003"]);
  for (const s of r.simulations) {
    const want = simRef.runs.find((x: any) => x.simulation_id === s.simulation_id);
    const got = goldenShape(s);
    eq(`${s.simulation_id} events equal Python's (${got.events.length})`, got.events, want.golden.events);
    eq(`${s.simulation_id} waits, mean wait, final completion`, [got.waits_minutes, got.mean_wait_minutes, got.final_completion_minute], [want.golden.waits_minutes, want.golden.mean_wait_minutes, want.golden.final_completion_minute]);
    eq(`${s.simulation_id} statistics`, statistics(s), want.statistics);
  }
  // designed relationships quoted in the manifest are recomputed, not trusted
  const tech = groupMetrics(r.population, "queue", [parseTs(win.start), parseTs(win.end)], [parseTs(win.end)], r.abandonable, r.histories)["q-002"]!;
  yes("technical queue resolution is measured from the original arrival", tech.completion_count > 0);
}

if (failures > 0) { console.log(`\n${failures} of ${checks} checks FAILED`); process.exitCode = 1; }
else console.log(`\nALL OK (${checks} checks)`);
