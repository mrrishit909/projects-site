// Converts the hand-derived golden fixture (tests/fixtures/golden/inputs.json) into the published
// snapshot shape (manifest.json + one file per entity) under public/data/golden/. The web app loads it
// with ?dataset=golden so the browser display of the golden answers (P01-GOLD-06) can be tested.
// Run: npx tsx scripts/golden-to-snapshot.ts   (the output is committed)
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { ENTITIES } from "../src/domain/types";

const GOLDEN = new URL("../../tests/fixtures/golden/", import.meta.url);
const OUT = new URL("../public/data/golden/", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

const inputs = readJson(new URL("inputs.json", GOLDEN));
const hashes = readJson(new URL("HASHES.json", GOLDEN));
const version = "golden-v1";
mkdirSync(OUT, { recursive: true });

const rowCounts: Record<string, number> = {};
for (const e of ENTITIES) {
  const rows = inputs[e] ?? [];
  rowCounts[e] = rows.length;
  writeFileSync(new URL(`${e}.json`, OUT), JSON.stringify({ entity: e, dataset_version: version, rows }, null, 1) + "\n");
}
const manifest = {
  contract_version: inputs.contract,
  dataset_hash: hashes.sha256["inputs.json"], // sha256 of the fixture's inputs.json
  dataset_version: version,
  generated_at: "2026-10-26T00:00:00Z",
  generator: { name: "tests/fixtures/golden (hand-derived, no generator)", seed: 0, parameters: {} },
  injection_manifest: "../injection-manifest.json",
  designed_relationships: [],
  fixture_id: inputs.fixture_id,
  row_counts: rowCounts,
};
writeFileSync(new URL("manifest.json", OUT), JSON.stringify(manifest, null, 2) + "\n");
console.log(`wrote ${ENTITIES.length + 1} files to public/data/golden/`, rowCounts);
