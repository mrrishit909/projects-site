// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) and the
// two variants exactly, then run the full published snapshot under a time budget.
import { readFileSync } from "node:fs";
import { toString } from "../src/domain/decimal";
import { runPipeline } from "../src/domain/pipeline";
import { ENTITIES, METRIC_KEYS, type PipelineInputs } from "../src/domain/types";

const GOLDEN = new URL("../../tests/fixtures/golden/", import.meta.url);
const DATA = new URL("../public/data/", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

let failures = 0;
let checks = 0;
function expectEq(label: string, got: unknown, want: unknown): void {
  checks++;
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) console.log(`OK       ${label}`);
  else {
    failures++;
    console.log(`MISMATCH ${label}: got ${g} want ${w}`);
  }
}
const money = (m: ReadonlyMap<string, import("../src/domain/decimal").Dec>): Record<string, string> => {
  const o: Record<string, string> = {};
  for (const [k, v] of m) o[k] = toString(v);
  return o;
};

function checkFixture(name: string, inputs: PipelineInputs, expected: any): void {
  for (const [state, includeReturns] of [["baseline", false], ["after_return", true]] as const) {
    const want = expected.states[state];
    const r = runPipeline(inputs, includeReturns);
    const tag = `${name}/${state}`;
    for (const key of METRIC_KEYS) expectEq(`${tag} metric ${key}`, r.metrics[key], want.metrics[key]);
    expectEq(`${tag} metric key set`, Object.keys(r.metrics).sort(), Object.keys(want.metrics).sort());
    expectEq(`${tag} discount_by_shipment_line`, money(r.discountByLine), want.discount_by_shipment_line);
    expectEq(`${tag} freight_by_shipment_line`, money(r.freightByLine), want.freight_by_shipment_line);
    if (state === "baseline") {
      expectEq(`${name} ingest counts`, r.ingest.counts, expected.ingest.counts);
      expectEq(
        `${name} rejected records`,
        r.ingest.rejected.map((x) => [x.entity, x.id, x.reason_code]),
        [...expected.ingest.rejected_records].map((x: any) => [x.entity, x.id, x.reason_code]).sort(
          (a: string[], b: string[]) => (a[0]! < b[0]! ? -1 : a[0]! > b[0]! ? 1 : a[1]! < b[1]! ? -1 : a[1]! > b[1]! ? 1 : 0),
        ),
      );
      expectEq(`${name} rejected raw rows preserved`, r.ingest.rejected.map((x) => x.raw_row), [...expected.ingest.rejected_records].sort(
        (a: any, b: any) => (a.entity < b.entity ? -1 : a.entity > b.entity ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
      ).map((x: any) => x.raw_row));
    }
  }
}

for (const [name, dir] of [["golden", ""], ["variant-rejected", "variant-rejected/"], ["variant-empty", "variant-empty/"]] as const) {
  checkFixture(name, readJson(new URL(`${dir}inputs.json`, GOLDEN)), readJson(new URL(`${dir}expected.json`, GOLDEN)));
}

// ---- published snapshot: invariants and time budget -----------------------------------------
const snapshot: Record<string, unknown> = { contract: "v1" };
for (const e of ENTITIES) snapshot[e] = readJson(new URL(`${e}.json`, DATA)).rows;
const manifest = readJson(new URL("manifest.json", DATA));
for (const e of ENTITIES) expectEq(`snapshot row count ${e}`, (snapshot[e] as unknown[]).length, manifest.row_counts[e]);
const t0 = performance.now();
const full = runPipeline(snapshot as PipelineInputs, true);
const ms = performance.now() - t0;
console.log(`TIMING   runPipeline(snapshot, returns) ${ms.toFixed(0)} ms over ${manifest.row_counts.shipment_lines} shipment lines`);
checks++;
if (ms < 2000) console.log("OK       snapshot pipeline under 2000 ms");
else {
  failures++;
  console.log(`MISMATCH snapshot pipeline took ${ms.toFixed(0)} ms (budget 2000)`);
}
expectEq("snapshot allocation_residual", full.metrics.allocation_residual, "0.00");
const c = full.ingest.counts.shipment_lines;
expectEq("snapshot lines: facts + excluded + quarantined = accepted", full.facts.length + full.excluded.length + c.quarantined, c.accepted);

console.log(failures === 0 ? `ALL OK (${checks} checks)` : `${failures} MISMATCH of ${checks} checks`);
process.exitCode = failures === 0 ? 0 : 1;
