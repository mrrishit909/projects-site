// Converts the hand-derived golden fixture (tests/fixtures/golden/inputs.json) into the published
// snapshot shape (manifest.json + one file per entity) under public/data/golden/. The web app loads it
// with ?dataset=golden so the browser display of the golden answers can be tested.
// Run: npx tsx scripts/golden-to-snapshot.ts   (the output is committed)
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { ENTITIES } from "../src/domain/contract";

const GOLDEN = new URL("../../tests/fixtures/golden/", import.meta.url);
const OUT = new URL("../public/data/golden/", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

const inputs = readJson(new URL("inputs.json", GOLDEN));
const hashes = readJson(new URL("HASHES.json", GOLDEN));
const version = "golden-v1";
mkdirSync(OUT, { recursive: true });

const rowCounts: Record<string, number> = {};
const write = (name: string, rows: unknown[]): void => {
  rowCounts[name] = rows.length;
  writeFileSync(new URL(`${name}.json`, OUT), JSON.stringify({ entity: name, dataset_version: version, rows }, null, 1) + "\n");
};
for (const e of ENTITIES) write(e, inputs[e] ?? []);
// D-05: the fixture carries workflow_requirements as a block; the snapshot publishes it as rows.
write("workflow_requirements", Object.entries(inputs.workflow_requirements ?? {}).map(
  ([wfv, spec]: [string, any]) => ({ workflow_version_id: wfv, required_document_types: spec.required_document_types }),
));
const manifest = {
  contract_version: inputs.contract ?? "v1",
  dataset_hash: hashes.sha256["inputs.json"], // sha256 of the fixture's inputs.json
  dataset_version: version,
  generated_at: "2026-10-26T00:00:00Z",
  generator: { name: "tests/fixtures/golden (hand-derived, no generator)", seed: 0, parameters: {} },
  designed_relationships: [],
  fixture_id: inputs.fixture_id,
  cutoffs: inputs.cutoffs,
  states: inputs.states,
  row_counts: rowCounts,
};
writeFileSync(new URL("manifest.json", OUT), JSON.stringify(manifest, null, 2) + "\n");
console.log(`wrote ${Object.keys(rowCounts).length + 1} files to public/data/golden/`, rowCounts);
