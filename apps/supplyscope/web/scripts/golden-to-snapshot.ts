// Converts the hand-derived golden fixture (tests/fixtures/golden/inputs.json) into the published snapshot shape
// (manifest.json + one file per entity) under public/data/golden/. The web app loads it with ?dataset=golden so the browser
// display of the golden answers can be tested.
// Run: npx tsx scripts/golden-to-snapshot.ts   (the output is committed)
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { ENTITIES, EXTRA_ENTITIES } from "../src/domain/contract";

const GOLDEN = new URL("../../tests/fixtures/golden/", import.meta.url);
const OUT = new URL("../public/data/golden/", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

const inputs = readJson(new URL("inputs.json", GOLDEN));
const hashes = readJson(new URL("HASHES.json", GOLDEN));
const version = "golden-v1";
mkdirSync(OUT, { recursive: true });

const rowCounts: Record<string, number> = {};
for (const e of [...ENTITIES, ...EXTRA_ENTITIES]) {
  const rows: unknown[] = inputs[e] ?? []; // the fixture has no cost versions, lost sales, closures or latent demand
  rowCounts[e] = rows.length;
  writeFileSync(new URL(`${e}.json`, OUT), JSON.stringify({ entity: e, dataset_version: version, rows }, null, 1) + "\n");
}
const manifest = {
  contract_version: inputs.contract_version === 1 ? "v1" : String(inputs.contract_version),
  dataset_hash: hashes.sha256["inputs.json"], // sha256 of the fixture's inputs.json
  dataset_version: version,
  generated_at: "2026-10-26T00:00:00Z",
  generator: { name: "tests/fixtures/golden (hand-derived, no generator)", seed: 0, parameters: {} },
  designed_relationships: [],
  fixture_id: inputs.fixture_id,
  as_of: inputs.as_of,
  window_start: inputs.window_start,
  states: inputs.states,
  row_counts: rowCounts,
};
writeFileSync(new URL("manifest.json", OUT), JSON.stringify(manifest, null, 2) + "\n");
console.log(`wrote ${Object.keys(rowCounts).length + 1} files to public/data/golden/`, rowCounts);
