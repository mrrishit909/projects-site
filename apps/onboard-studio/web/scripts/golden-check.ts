// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) and the two
// variants exactly in both pause states, then run the full published snapshot under a time budget and
// confirm the injected defects are caught.
import { readFileSync } from "node:fs";
import { isManifest, buildInputs, listedFiles } from "../src/data/inputs";
import { ENTITIES, METRIC_KEYS } from "../src/domain/contract";
import { groupMetrics } from "../src/domain/metrics";
import { runPipeline } from "../src/domain/pipeline";
import type { PipelineInputs, RejectedRecord } from "../src/domain/types";
import { definitionHash, definitionPayload } from "../src/domain/workflow";

const GOLDEN = new URL("../../tests/fixtures/golden/", import.meta.url);
const DATA = new URL("../public/data/", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

let failures = 0;
let checks = 0;
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) =>
  x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : x);
function expectEq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got)} want ${canon(want)}`); }
}
const byKey = (a: { entity: string; id: string }, b: { entity: string; id: string }): number =>
  a.entity < b.entity ? -1 : a.entity > b.entity ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;

function checkFixture(name: string, inputs: PipelineInputs, expected: any): void {
  for (const state of Object.keys(expected.states)) {
    const want = expected.states[state];
    const r = runPipeline(inputs, state);
    const tag = `${name}/${state}`;
    for (const key of METRIC_KEYS) expectEq(`${tag} metric ${key}`, (r.metrics as any)[key], want.metrics[key]);
    expectEq(`${tag} metric key set`, Object.keys(r.metrics).sort(), Object.keys(want.metrics).sort());
    expectEq(`${tag} metric key order`, Object.keys(r.metrics), Object.keys(want.metrics));
    expectEq(`${tag} pause policy`, inputs.states![state]!, Object.fromEntries(Object.entries(inputs.states![state]!).map(([k]) => [k, { pause_policy: want.pause_policy }])));
    if (state === Object.keys(expected.states)[0]) {
      expectEq(`${name} ingest counts`, r.ingest.counts, expected.ingest.counts);
      const wantRej = [...expected.ingest.rejected_records].sort(byKey);
      expectEq(`${name} rejected records (entity, id, reason)`, r.rejected.map((x) => [x.entity, x.id, x.reason_code]), wantRej.map((x: any) => [x.entity, x.id, x.reason_code]));
      expectEq(`${name} rejected raw rows preserved`, r.rejected.map((x: RejectedRecord) => x.raw_row), wantRej.map((x: any) => x.raw_row));
    }
  }
}

for (const [name, dir] of [["golden", ""], ["variant-rejected", "variant-rejected/"], ["variant-empty", "variant-empty/"]] as const) {
  checkFixture(name, readJson(new URL(`${dir}inputs.json`, GOLDEN)), readJson(new URL(`${dir}expected.json`, GOLDEN)));
}

// ---- the spec sentence in words (P02-GOLD-01) and group metrics ---------------------------------
{
  const inputs = readJson(new URL("inputs.json", GOLDEN)) as PipelineInputs;
  const a = runPipeline(inputs, "pause_eligible"), b = runPipeline(inputs, "pause_not_eligible");
  expectEq("P02-GOLD-01 calendar 66 h, business 2 h", [a.metrics.calendar_cycle_time_hours, a.metrics.business_cycle_time_hours], ["66.0000", "2.0000"]);
  expectEq("P02-GOLD-01 active 1 h when pause-eligible, 2 h when not", [a.metrics.active_elapsed_hours, b.metrics.active_elapsed_hours], ["1.0000", "2.0000"]);
  const g = groupMetrics(a.population, "region", { "sla-001": ["customer_info_requested"] }, inputs.cutoffs);
  expectEq("group metrics by region equal the population metrics", g.emea, a.metrics);
  expectEq("group metrics keys per dimension", (["organization", "segment", "region", "workflow_version"] as const).map((k) => Object.keys(groupMetrics(a.population, k))), [["org-001"], ["smb"], ["emea"], ["wfv-001"]]);
  const fx = readJson(new URL("inputs.json", GOLDEN));
  const sd = fx.step_definitions, dp = fx.dependencies;
  expectEq("definition_hash (D-05) of wfv-001 reproduces the fixture", await definitionHash(sd, dp), fx.workflow_versions[0].definition_hash);
  checks++;
  if (definitionPayload(sd, dp).startsWith('{"dependencies":[["sd-002","sd-001","mandatory"]],"steps":')) console.log("OK       definition payload is compact sorted-key JSON");
  else { failures++; console.log("MISMATCH definition payload shape"); }
}

// ---- published snapshot: row counts, injected defects, time budget, definition hashes -------------
{
  const manifest = readJson(new URL("manifest.json", DATA));
  checks++;
  if (isManifest(manifest)) console.log("OK       manifest has the required fields"); else { failures++; console.log("MISMATCH manifest fields"); }
  const files = new Map<string, unknown>();
  for (const n of listedFiles(manifest)) files.set(n, readJson(new URL(`${n}.json`, DATA)));
  for (const e of [...ENTITIES, "workflow_requirements"]) expectEq(`snapshot row count ${e}`, (files.get(e) as any).rows.length, manifest.row_counts[e]);
  const inputs = buildInputs(manifest, files);
  const t0 = performance.now();
  const full = runPipeline(inputs, null);
  const ms = performance.now() - t0;
  console.log(`TIMING   runPipeline(snapshot) ${ms.toFixed(0)} ms over ${manifest.row_counts.cases} cases, ${manifest.row_counts.case_events} events`);
  checks++;
  if (ms < 2000) console.log("OK       snapshot pipeline under 2000 ms");
  else { failures++; console.log(`MISMATCH snapshot pipeline took ${ms.toFixed(0)} ms (budget 2000)`); }
  expectEq("snapshot pipeline completes with a non-empty population", full.metrics.empty_population, false);

  const inj = readJson(new URL("injection-manifest.json", DATA)).injections as { id: string; record_ids: string[]; case_ids?: string[] }[];
  const find = (id: string) => inj.find((i) => i.id === id)!;
  const rejIds = (entity: string, reason?: string) => full.rejected.filter((r) => r.entity === entity && (!reason || r.reason_code === reason)).map((r) => r.id).sort();
  const sorted = (xs: string[]) => [...xs].sort();
  expectEq("INJ-01 rejected cases = MISSING_REQUIRED_DOCUMENT", rejIds("cases", "MISSING_REQUIRED_DOCUMENT"), sorted(find("INJ-01").record_ids));
  expectEq("INJ-02 rejected approvals = DECISION_CONFLICT", rejIds("approvals", "DECISION_CONFLICT"), sorted(find("INJ-02").record_ids));
  expectEq("INJ-09 rejected cases = PAUSE_REASON_NOT_CONFIGURED", rejIds("cases", "PAUSE_REASON_NOT_CONFIGURED"), sorted(find("INJ-09").case_ids!));
  expectEq("INJ-10 rejected cases = SELF_APPROVAL", rejIds("cases", "SELF_APPROVAL"), sorted(find("INJ-10").case_ids!));
  expectEq("rejected case ids = INJ-01 + INJ-09 + INJ-10 cases", rejIds("cases"),
    sorted([...find("INJ-01").record_ids, ...find("INJ-09").case_ids!, ...find("INJ-10").case_ids!]));
  expectEq("INJ-03 flags = the three out-of-hours pauses", full.flags.map((f) => f.waiting_interval_id).sort(), sorted(find("INJ-03").record_ids));
  expectEq("INJ-03 flag code", [...new Set(full.flags.map((f) => f.flag))], ["PAUSE_OUTSIDE_WORKING_INTERVAL"]);
  expectEq("accepted + rejected cases = published cases", full.ingest.counts.cases.accepted + full.ingest.counts.cases.rejected, manifest.row_counts.cases);
  for (const v of (files.get("workflow_versions") as any).rows as any[]) {
    const steps = ((files.get("step_definitions") as any).rows as any[]).filter((s) => s.workflow_version_id === v.workflow_version_id);
    const deps = ((files.get("dependencies") as any).rows as any[]).filter((d) => steps.some((s) => s.step_definition_id === d.step_definition_id));
    expectEq(`definition_hash ${v.workflow_version_id} reproduces the published value`, await definitionHash(steps, deps), v.definition_hash);
  }
}

console.log(failures === 0 ? `ALL OK (${checks} checks)` : `${failures} MISMATCH of ${checks} checks`);
process.exitCode = failures === 0 ? 0 : 1;
