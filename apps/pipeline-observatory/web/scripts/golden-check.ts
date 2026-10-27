// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) leaf by leaf for the golden fixture and its two variants,
// the golden world as the site computes it, the spec sentences of P08-GOLD-01 in words (10 / 8 / 1 / 1, replay 8, crash never a ninth, freshness vs
// ingestion age, completeness 8/9, the gate and the pointer, the late event, residual 0.00, recovery 475.0000 min, backfill 2/3), the arithmetic, time and
// hash primitives (against node:crypto), the half-open windows, and the PYTHON domain's results over the published snapshot
// (scripts/snapshot-reference.json, produced once by scripts/make-snapshot-reference.py): digests of the eleven metric blocks over the sample, the
// headline figures, eight window cases, the complete-world figures, the designed-relationship figures and the injection checks, the three hash kinds.
// Prints "ALL OK (N checks)" or exits 1.
import { createHash } from "node:crypto";
import { parseJsonExact } from "../src/domain/json";
import { readFileSync } from "node:fs";
import { analyseGolden, analyseSnapshot } from "../src/data/analyse";
import { ENTITY_FILES, datasetHash, isManifest, rawOf } from "../src/data/files";
import { classifyRows } from "../src/domain/classify";
import { CONTRACT_VERSION, METRIC_KEYS } from "../src/domain/contract";
import { canonicalJson, contentHash, definitionHash, payloadHash } from "../src/domain/hashing";
import { computeWindow, runPipeline } from "../src/domain/metrics";
import { decFr, fr, m4, p6, rnd } from "../src/domain/num";
import { parseTs, isoZ, dayPartitions, utcDate, secondsBetween, daysFromCivil, civilFromDays } from "../src/domain/time";
import { sha256Hex } from "../src/domain/sha256";
import { goldenExperiments, decideBackfill, retryRow } from "../src/domain/sim";
import { publishedRecords } from "../src/domain/reconcile";
import { derive } from "../src/domain/metrics";
import { funnel } from "../src/lib/derive";

const ROOT = new URL("../../", import.meta.url);
const WEB = new URL("../", import.meta.url);
const readJson = (u: URL): any => parseJsonExact(readFileSync(u, "utf8")); // eslint-disable-line @typescript-eslint/no-explicit-any

let failures = 0, checks = 0;
const canon = (v: unknown): string => canonicalJson(v ?? null);
const digest = (v: unknown): string => createHash("sha256").update(canonicalJson(v)).digest("hex");
function eq(label: string, got: unknown, want: unknown, quiet = false): void {
  checks++;
  if (canon(got) === canon(want)) { if (!quiet) console.log(`OK       ${label}`); }
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 300)} want ${canon(want).slice(0, 300)}`); }
}
/** Every leaf of two JSON values, compared by path: one check per leaf. */
function leaves(label: string, got: unknown, want: unknown): number {
  const flat = (v: unknown, p: string, out: Map<string, unknown>): Map<string, unknown> => {
    if (Array.isArray(v)) { if (v.length === 0) out.set(p, "[]"); v.forEach((x, i) => flat(x, `${p}[${i}]`, out)); }
    else if (v && typeof v === "object") { const e = Object.entries(v); if (e.length === 0) out.set(p, "{}"); for (const [k, x] of e) flat(x, `${p}.${k}`, out); }
    else out.set(p, v);
    return out;
  };
  const g = flat(JSON.parse(JSON.stringify(got)), "", new Map()), w = flat(want, "", new Map());
  let bad = 0;
  for (const k of new Set([...g.keys(), ...w.keys()])) {
    checks++;
    if (!g.has(k) || !w.has(k) || g.get(k) !== w.get(k)) { failures++; bad++; if (bad <= 8) console.log(`MISMATCH ${label}${k}: got ${String(g.get(k))} want ${String(w.get(k))}`); }
  }
  console.log(`${bad === 0 ? "OK      " : "MISMATCH"} ${label}: ${w.size} leaves`);
  return w.size;
}

// ---------------------------------------------------------------------------------------------- fixture hashes
const FIX = new URL("tests/fixtures/golden/", ROOT);
const hashes = readJson(new URL("HASHES.json", FIX)).sha256 as Record<string, string>;
for (const [f, h] of Object.entries(hashes)) {
  const text = readFileSync(new URL(f, FIX), "utf8");
  eq(`fixture ${f}: sha-256 (node:crypto)`, createHash("sha256").update(text).digest("hex"), h, true);
  eq(`fixture ${f}: sha-256 (the site's own implementation)`, sha256Hex(text), h, true);
}
console.log(`OK       ${Object.keys(hashes).length} fixture files match HASHES.json under node:crypto and under the site's sha-256`);

// ---------------------------------------------------------------------------------------------- golden and its variants
for (const v of ["", "variant-rejected/", "variant-empty/"]) {
  const inputs = readJson(new URL(`${v}inputs.json`, FIX));
  const want = readJson(new URL(`${v}expected.json`, FIX));
  const res = runPipeline(inputs);
  leaves(`${v || "golden/"}expected.json`, res.golden, want);
  eq(`${v || "golden/"}metric keys in contract order`, Object.keys(res.golden.metrics), [...METRIC_KEYS]);
}
const gInputs = readJson(new URL("inputs.json", FIX)), gExpected = readJson(new URL("expected.json", FIX));
const gold = analyseGolden(gInputs, readFileSync(new URL("inputs.json", FIX), "utf8"), sha256Hex);
leaves("golden world as the site computes it (analyseGolden) = expected.json", gold.g, gExpected);
eq("golden provenance: dataset_hash = HASHES.json hash of inputs.json; code_sha not recorded", [gold.provenance.dataset_hash, gold.provenance.code_sha], [hashes["inputs.json"], null]);

// the spec sentence of P08-GOLD-01 in words and in the dataset's own computation (the pages show these strings)
{
  const M = gold.g.metrics;
  const b1 = M.ingestion.sources["src-orders"].batches["b-001"], b2 = M.ingestion.sources["src-orders"].batches["b-002"], b3 = M.ingestion.sources["src-orders"].batches["b-003"];
  eq("spec: the batch of ten rows: received 10, accepted unique 8, duplicate 1, quarantined 1", [b1.received, b1.accepted_unique, b1.duplicate, b1.quarantined], [10, 8, 1, 1]);
  eq("spec: replaying the batch leaves 8 accepted unique records (b-002: 0 new, 9 duplicates, 1 quarantined again; source accepted 8)", [b2.accepted_unique, b2.duplicate, b2.quarantined, M.ingestion.sources["src-orders"].accepted_unique], [0, 9, 1, 8]);
  eq("spec: the crashed batch b-003 is aborted, uncounted, written 10 rows, no checkpoint; the version stays 2", [b3.status, b3.counted, b3.written_rows, b3.received, M.ingestion.sources["src-orders"].checkpoint.committed_version, M.ingestion.sources["src-orders"].checkpoint.uncommitted_batches_with_checkpoint], ["aborted", false, 10, 0, 2, 0]);
  eq("spec: freshness 52200 s beside ingestion age 42900 s (orders); 53400 and 46500 (refunds)", [M.freshness["src-orders"].freshness_seconds, M.freshness["src-orders"].ingestion_age_seconds, M.freshness["src-refunds"].freshness_seconds, M.freshness["src-refunds"].ingestion_age_seconds], [52200, 42900, 53400, 46500]);
  eq("the freshness rows the page draws equal the metric block", gold.freshness.map((f) => [f.source_id, f.freshness_seconds, f.ingestion_age_seconds, f.freshness_basis]), [["src-orders", 52200, 42900, "computed"], ["src-refunds", 53400, 46500, "computed"]]);
  eq("spec: completeness 8 of 9 = 0.888889 (orders), 1 of 1 = 1.000000 (refunds)", [M.completeness["src-orders"]["2026-10-04"].value, M.completeness["src-refunds"]["2026-10-04"].value], ["0.888889", "1.000000"]);
  eq("spec: the gate blocks run-002 (keys_unique critical failed, completeness warning failed) and the pointer stays on pub-001", [M.quality_gate["run-002"].decision, M.quality_gate["run-002"].critical_failures, M.quality_gate["run-002"].noncritical_failures, M.publications.pointer_history.map((h: any) => h.pointer_after)], ["blocked", 1, 1, ["pub-001", "pub-001", "pub-003"]]);
  eq("spec: the late event REF-2001 arrives behind pub-001's watermark and enters pub-003; none lost", [M.late_events.count, M.late_events.lost, M.late_events.events[0].source_key, M.late_events.events[0].behind_publication_id, M.late_events.events[0].included_in_publication_id], [1, 0, "REF-2001", "pub-001", "pub-003"]);
  eq("spec: every publication reconciles to residual 0.00", Object.values<any>(M.reconciliation).map((r) => r.residual), ["0.00", "0.00"]);
  eq("spec: the incident closes after a verified recovery of 475.0000 minutes (28500 s) by run-003", [M.incidents.incidents["inc-001"].recovery_seconds, M.incidents.mean_recovery_minutes, M.incidents.incidents["inc-001"].recovery_run_id, M.incidents.incidents["inc-001"].closure_consistent], [28500, "475.0000", "run-003", true]);
  eq("the incident view the page shows equals the metric block (recovery, class)", [gold.incidents.mean_recovery_minutes, gold.incidents.incidents[0]!.recovery_minutes, gold.incidents.incidents[0]!.diagnosis_class, gold.incidents.all_closures_consistent], ["475.0000", "475.0000", "keys", true]);
  eq("spec: backfill coverage 2 of 3 = 0.666667", [M.backfills.overall.coverage, M.backfills.overall.verified_partitions, M.backfills.overall.requested_partitions], ["0.666667", 2, 3]);
  eq("spec: processing rate 8 / 12 s = 0.666667 records per second, labelled synthetic, not a benchmark", [M.processing_rate.records_per_second, M.processing_rate.hardware.startsWith("Synthetic fixture value, not a benchmark")], ["0.666667", true]);
  eq("the golden graph: the source feeds the staging model, the mart sales_daily feeds the publication; no dependency is invented where depends_on is absent", gold.graph.edges.map((e) => `${e.from}>${e.to}`), ["m-sales-daily>pub:sales_daily", "src-orders>m-stg-orders"]);
}
// the experiments behind the runs page, computed through the domain on copies of the golden inputs
{
  const ex = goldenExperiments(gInputs);
  eq("experiments: batch, replay, storm of 5, crash, crash with a new key all hold", ex.map((e) => [e.id, e.holds]), [["batch", true], ["replay", true], ["storm", true], ["crash", true], ["crash-new-key", true]]);
  eq("experiments: the crash leaves 8 and the replay leaves 8 (never a ninth); the new-key variant leaves 8 then 9 once", [ex[3]!.steps.map((s) => s.accepted_total), ex[4]!.steps.map((s) => s.accepted_total)], [[8, 8, 8], [8, 8, 9]]);
  eq("experiments: a storm of five replays leaves 8 after every replay", ex[2]!.steps.map((s) => s.accepted_total), [8, 8, 8, 8, 8, 8]);
}

// ---------------------------------------------------------------------------------------------- primitives
{
  eq("rnd: ROUND_HALF_UP, once, at the stated places; never -0.00", [rnd(fr(5, 10_000_000), 6), rnd(fr(-4, 1000), 2), rnd(fr(-5, 1000), 2), rnd(fr(5, 1000), 2), rnd(fr(1, 3), 6), rnd(fr(2, 3), 4), rnd(fr(7, 2), 0)], ["0.000001", "0.00", "-0.01", "0.01", "0.333333", "0.6667", "4"]);
  eq("p6/m4 keep null as null (unknown, never 0)", [p6(null), m4(null)], [null, null]);
  eq("decFr is exact, signed, tolerant of surrounding whitespace", [rnd(decFr("0.250000"), 6), rnd(decFr("-12.50"), 2), rnd(decFr(" 3\n"), 2)], ["0.250000", "-12.50", "3.00"]);
  eq("parseTs / isoZ round trip, offsets, fractional seconds", [isoZ(parseTs("2026-10-05T00:00:00Z")), isoZ(parseTs("2026-10-05T05:30:00+05:30")), isoZ(parseTs("2026-10-05 00:00:00.5Z")), isoZ(parseTs("2026-02-28T23:59:59Z")), isoZ(parseTs("2028-02-29T12:00:00.123456789Z"))],
    ["2026-10-05T00:00:00Z", "2026-10-05T00:00:00Z", "2026-10-05T00:00:00.500000Z", "2026-02-28T23:59:59Z", "2028-02-29T12:00:00.123456Z"]);
  const bad = ["2026-10-05", "2026-10-05T00:00:00", "2026-02-30T00:00:00Z", "2026-13-01T00:00:00Z", "2026-10-05T24:00:00Z", "2026-10-05T00:00:60Z", "2026-10-05T00:00:00z", "2027-02-29T00:00:00Z", 5, null];
  eq("parseTs refuses naive, impossible and non-text instants", bad.map((b) => { try { parseTs(b); return "accepted"; } catch { return "refused"; } }), bad.map(() => "refused"));
  eq("civil dates round trip over 1900-2100 (every day)", (() => { let n = 0; for (let d = daysFromCivil(1900, 1, 1); d <= daysFromCivil(2100, 12, 31); d++) { const [y, m, dd] = civilFromDays(d); if (daysFromCivil(y, m, dd) !== d) n++; } return n; })(), 0);
  eq("half-open day partitions: [Sep 1, Sep 4) has three, [Sep 1, Sep 1) none, a midnight end excludes its own day, a leap day is counted", [dayPartitions("2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z"), dayPartitions("2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"), dayPartitions("2028-02-28T00:00:00Z", "2028-03-01T00:00:00Z"), dayPartitions("2026-09-01T00:00:00Z", "2026-09-02T00:00:00.000001Z")],
    [["2026-09-01", "2026-09-02", "2026-09-03"], [], ["2028-02-28", "2028-02-29"], ["2026-09-01", "2026-09-02"]]);
  eq("seconds between: whole seconds (floor), negative direction, across midnight", [secondsBetween("2026-10-04T09:30:00Z", "2026-10-05T00:00:00Z"), secondsBetween("2026-10-05T00:00:00Z", "2026-10-04T23:59:59.5Z"), secondsBetween("2026-10-04T23:59:59Z", "2026-10-05T00:00:00.9Z")], [52200, -1, 1]);
  eq("utcDate is the UTC date, also for an offset instant", [utcDate("2026-10-04T23:59:59Z"), utcDate("2026-10-05T00:00:00Z"), utcDate("2026-10-05T01:30:00+05:30")], ["2026-10-04", "2026-10-05", "2026-10-04"]);
  // sha-256 against node:crypto: boundary lengths, unicode, a long text
  const texts = [...Array.from({ length: 140 }, (_, n) => "a".repeat(n)), "", "é", "日本語", "😀 emoji", "line\nbreak", JSON.stringify({ k: [1, 2, 3] }), "x".repeat(10_000)];
  eq(`sha-256: ${texts.length} texts (every length 0..139 around the 55/56/63/64 block edges, unicode, 10 kB) equal node:crypto`, texts.filter((t) => sha256Hex(t) !== createHash("sha256").update(t).digest("hex")).length, 0);
  eq("canonical JSON: sorted keys, compact separators, ASCII only (DEL, accents, an astral character), integers only", [canonicalJson({ b: 1, a: ["x", null, true], "é": "\u007f", z: "😀" }), (() => { try { canonicalJson({ x: 1.5 }); return "accepted"; } catch { return "refused"; } })()], ['{"a":["x",null,true],"b":1,"z":"\\ud83d\\ude00","\\u00e9":"\\u007f"}', "refused"]);
  eq("canonical JSON puts the astral key last", canonicalJson({ "\u{1F600}": 1, "�": 2 }), '{"\\ufffd":2,"\\ud83d\\ude00":1}');
  // classification primitives
  const ks = new Set<unknown>();
  const dis = classifyRows([{ raw_record_id: "r2", source_key: "A", payload_json: { record_id: "A", quantity: 1, unit_price: "1.00", amount: "1.00", event_ts: "2026-10-05T00:00:00Z" } },
    { raw_record_id: "r1", source_key: "A", payload_json: { record_id: "A", quantity: -1, unit_price: "1.00", amount: "1.00", event_ts: "2026-10-05T00:00:00Z" } }], ks);
  eq("classification is in raw_record_id order and the key check runs before the contract check (r1 negative but first: quarantined; r2 then accepted)", dis.map((d) => [d.raw_record_id, d.kind, d.reason]), [["r1", "quarantined", "NEGATIVE_QUANTITY"], ["r2", "accepted", null]]);
}
// the three hash kinds recomputed over the golden fixture (31 payloads, 2 contents, 2 definitions)
{
  const bad = gInputs.raw_records.filter((r: any) => payloadHash(r.payload_json) !== r.payload_hash).length;
  eq(`golden: payload_hash recomputed for ${gInputs.raw_records.length} raw rows`, bad, 0);
  const facts = derive(gold.acc);
  for (const p of gInputs.publications) {
    const inc = (p.included_batch_ids as string[]).filter((b) => facts.committed.some((c) => c["batch_id"] === b));
    eq(`golden: content_hash of ${p.publication_id} recomputed from its included accepted records`, contentHash(publishedRecords(facts.accepted, inc).map((a) => a.payload_hash)), p.content_hash);
  }
  for (const m of gInputs.model_definitions) eq(`golden: definition_hash of ${m.model_id}`, definitionHash(m.definition), m.definition_hash);
}

// ---------------------------------------------------------------------------------------------- the published snapshot vs the Python domain
const PUB = new URL("public/data/", WEB);
const ref = readJson(new URL("scripts/snapshot-reference.json", WEB));
const manifest = readJson(new URL("manifest.json", PUB));
if (!isManifest(manifest)) throw new Error("manifest.json is not a manifest");
const texts = new Map<string, string>(ENTITY_FILES.map((n) => [n, readFileSync(new URL(`${n}.json`, PUB), "utf8")]));
const raw = rawOf(new Map(ENTITY_FILES.map((n) => [n, parseJsonExact(texts.get(n)!)] as const)));
const injm = readJson(new URL("injection-manifest.json", PUB));
const t0 = Date.now();
const ds = analyseSnapshot(manifest, raw, injm);
console.log(`OK       the pipeline over the published snapshot ran in ${Date.now() - t0} ms`);
eq("snapshot: dataset_hash, version and as-of equal the Python reference's", [manifest.dataset_hash, manifest.dataset_version, manifest.as_of], [ref.dataset.dataset_hash, ref.dataset.dataset_version, ref.dataset.as_of]);
eq("snapshot: dataset_hash recomputed in TypeScript = the manifest's = Python's recomputation", [datasetHash(raw), ref.dataset.dataset_hash_recomputed], [manifest.dataset_hash, manifest.dataset_hash]);
for (const n of ENTITY_FILES) eq(`snapshot ${n}: row count = manifest row_counts = Python`, [(raw as any)[n].length, ref.dataset.row_counts[n]], [manifest.row_counts[n], (raw as any)[n].length], true);
console.log(`OK       ${ENTITY_FILES.length} entity files: row counts equal the manifest's and Python's`);
{ // no JSON float token in any published file (the contract forbids floats): scan every number token outside strings
  let floats = 0, tokens = 0;
  for (const [n, t] of [...texts, ["manifest", readFileSync(new URL("manifest.json", PUB), "utf8")] as const, ["injection-manifest", readFileSync(new URL("injection-manifest.json", PUB), "utf8")] as const]) {
    let i = 0;
    while (i < t.length) {
      const c = t[i]!;
      if (c === '"') { i++; while (i < t.length && t[i] !== '"') i += t[i] === "\\" ? 2 : 1; i++; continue; }
      if (c === "-" || (c >= "0" && c <= "9")) { let j = i + 1; while (j < t.length && /[0-9.eE+-]/.test(t[j]!)) j++; tokens++; if (/[.eE]/.test(t.slice(i, j))) { floats++; if (floats < 4) console.log(`float token in ${n}: ${t.slice(i, j + 5)}`); } i = j; continue; }
      i++;
    }
  }
  eq(`snapshot: no float token among ${tokens} number tokens of the 18 published files`, floats, 0);
  eq("snapshot: Python found no float either", ref.dataset.no_float_tokens, true);
}

// the sample world, block by block
const sw = ref.sample_world;
const sampleDigests = Object.fromEntries(METRIC_KEYS.map((k) => [k, digest(ds.g.metrics[k])]));
for (const k of METRIC_KEYS) eq(`sample world: ${k} block digest = Python's`, sampleDigests[k], sw.digests[k], true);
console.log(`OK       sample world: ${METRIC_KEYS.length} metric-block digests equal Python's`);
eq("sample world: the whole computed shape digest = Python's", digest(ds.g), sw.shape_digest);
{
  const M = ds.g.metrics, H = sw.headline;
  eq("sample world: import counts and rejected rows", [ds.g.ingest.counts, ds.g.ingest.rejected_records.map((r: any) => [r.entity, r.id, r.reason_code])], [H.ingest_counts, H.rejected]);
  eq("sample world: ingestion overall (1,878 received of the sampled batches)", [M.ingestion.overall, ds.g.empty_population], [H.ingestion_overall, H.empty_population]);
  const pubs = Object.values<any>(M.publications.publications);
  eq("sample world: publications (count, pointer, content hashes verifiable on the sample, published records)", { current: M.publications.current_publication_id, count: pubs.length, content_hash_ok: pubs.filter((p) => p.content_hash_ok).length, published_records: pubs.reduce((a, p) => a + p.published_records, 0) }, H.publications);
  eq("sample world: late events", { count: M.late_events.count, included_in_next_publication: M.late_events.included_in_next_publication, lost: M.late_events.lost }, H.late_events);
  eq("sample world: incidents over the sample (residual not evaluable)", { total: M.incidents.total, open: M.incidents.open, closed: M.incidents.closed, verified: M.incidents.verified, mean_recovery_minutes: M.incidents.mean_recovery_minutes }, H.incidents);
  eq("sample world: reconciliation of 1,318 publications over the sample", { publications: Object.keys(M.reconciliation).length, residual_zero: Object.values<any>(M.reconciliation).filter((r) => r.residual === "0.00").length, digest: digest(M.reconciliation) }, H.reconciliation);
  eq("sample world: backfills, processing rate, runs, durations, gate", [M.backfills.overall, M.backfills.refused, M.processing_rate, M.runs.overall, { successful: { count: M.runs.durations.successful.count, mean_minutes: M.runs.durations.successful.mean_minutes }, failed: { count: M.runs.durations.failed.count, mean_minutes: M.runs.durations.failed.mean_minutes } },
    { allowed: Object.values<any>(M.quality_gate).filter((v) => v.decision === "allowed").length, blocked: Object.values<any>(M.quality_gate).filter((v) => v.decision === "blocked").length, reached_gate: Object.values<any>(M.quality_gate).filter((v) => Object.keys(v.results).length > 0).length }], [H.backfills.overall, H.backfills.refused, H.processing_rate, H.runs_overall, H.durations, H.gate]);
  eq("sample world: freshness per source (latest event, freshness, last ingestion, ingestion age)", Object.fromEntries(Object.entries<any>(M.freshness).map(([s, v]) => [s, [v.latest_accepted_event_at, v.freshness_seconds, v.last_successful_ingestion_at, v.ingestion_age_seconds]])), H.freshness);
  const comp = Object.entries<any>(M.completeness).sort(([a], [b]) => (a < b ? -1 : 1)).flatMap(([s, days]) => Object.entries<any>(days).sort(([a], [b]) => (a < b ? -1 : 1)).map(([d, v]) => [s, d, v.expected_records, v.accepted_records, v.value]));
  eq("sample world: completeness partitions", [comp.length, digest(comp)], [H.completeness_partitions, H.completeness_digest]);
}
// half-open windows, a cutoff and one source (the API's GET /metrics) against Python
{
  const r731 = ds.acc["pipeline_runs"]!.find((r) => r["run_id"] === "run-0731")!, r732 = ds.acc["pipeline_runs"]!.find((r) => r["run_id"] === "run-0732")!;
  const cp = ds.acc["checkpoints"]!.find((c) => c["batch_id"] === "b-0848")!;
  const opts: Record<string, any> = {
    "the whole world": {}, "one UTC day, 2026-09-09 (the unexplained residual)": { from: "2026-09-09T00:00:00Z", to: "2026-09-10T00:00:00Z" },
    "exactly one run: [run-0731.started_at, run-0732.started_at)": { from: r731["started_at"], to: r732["started_at"] }, "an empty window: [t, t)": { from: r731["started_at"], to: r731["started_at"] },
    "a cutoff of 2026-09-20T12:00:00Z": { cutoff: "2026-09-20T12:00:00Z" }, "one source, the last five days": { source_id: "src-refunds", from: "2026-09-30T00:00:00Z", to: "2026-10-05T00:00:00Z" },
    "cutoff equal to a checkpoint commit instant (b-0848 drops at equality)": { cutoff: cp["committed_at"] }, "a window ending exactly at a run start": { from: "2026-09-09T10:00:00Z", to: r731["started_at"] },
  };
  for (const w of ref.windows) {
    const shape = computeWindow(ds.acc, ds.result.imported.rejected, ds.result.params, opts[w.name]);
    const dig = Object.fromEntries(METRIC_KEYS.map((k) => [k, digest(shape.metrics[k])]));
    for (const k of METRIC_KEYS) eq(`window "${w.name}": ${k} digest`, dig[k], w.digests[k], true);
    eq(`window "${w.name}": empty flag, ingestion overall, pointer`, [shape.empty_population, shape.metrics.ingestion.overall, shape.metrics.publications.current_publication_id], [w.empty_population, w.ingestion_overall, w.pointer]);
    console.log(`OK       window "${w.name}": ${METRIC_KEYS.length} block digests equal Python's (pointer ${w.pointer})`);
  }
  const edge = ref.windows.find((w: any) => w.name.startsWith("exactly one run"));
  eq("half-open: [t0, t1) holds the run starting at t0 and not the one starting at t1; [t, t) holds nothing", [edge.runs, ref.windows.find((w: any) => w.name.startsWith("an empty")).runs, ref.windows.find((w: any) => w.name.startsWith("a window ending exactly")).runs], [1, 0, 1]);
}
// the complete-world figures
{
  const cw = ref.complete_world;
  eq("complete world: ingestion from batch_summaries (overall, six sources, kinds, statuses, sampled batches)", ds.ingestion, cw.ingestion);
  eq("complete world: retry behaviour from fetch_log", ds.retry, cw.retry);
  const rows = ds.incidents.incidents.map((i) => ({ incident_id: i.incident_id, run_id: i.run_id, severity: i.severity, opened_at: i.opened_at, recovery_run_id: i.recovery_run_id, verified_at: i.verified_at, recovery_seconds: i.recovery_seconds, recovery_minutes: i.recovery_minutes,
    consistent: i.closure_consistent, class: i.diagnosis_class, failed_checks: i.failed_checks.map((c) => [c.rule, c.severity, c.failures, c.eligible]), failed_tasks: i.failed_tasks.map((t) => [t.task, t.attempts]) }));
  eq("complete world: incidents with verified recovery (25 verified, mean, classes, every closure consistent)", { total: ds.incidents.total, verified: ds.incidents.verified, mean_recovery_minutes: ds.incidents.mean_recovery_minutes, by_class: ds.incidents.by_class, all_consistent: ds.incidents.all_closures_consistent,
    incidents_digest: digest(rows), first: rows[0], run_1187: rows.find((r) => r.run_id === "run-1187") }, cw.incidents);
  eq("complete world: freshness beside ingestion age, cadences, silent flag, last batch, batches in 72 h", ds.freshness.map((f) => ({ source_id: f.source_id, ingestion_age_seconds: f.ingestion_age_seconds, freshness_seconds: f.freshness_seconds, sample_freshness_seconds: f.sample_freshness_seconds, cadences: f.cadences, silent: f.silent,
    past_target: f.past_target, gap_seconds: f.gap_seconds, last_batch: [f.last_batch!.batch_id, f.last_batch!.status], batches_72h: f.batches_72h })), cw.freshness);
  eq("complete world: only src-refunds is silent, and the gate's own target (7 days) does not see it", [ds.freshness.filter((f) => f.silent).map((f) => f.source_id), ds.freshness.filter((f) => f.past_target).length], [["src-refunds"], 0]);
  const edges = ds.graph.edges.map((e) => [e.from, e.to]);
  eq("complete world: the graph (19 nodes, edges digest)", { nodes: ds.graph.nodes.length, edges: edges.length, edges_digest: digest(edges) }, cw.graph);
  const M = ds.g.metrics, hist = M.publications.pointer_history as any[];
  eq("complete world: the pointer, its history and the blocked runs", { current: M.publications.current_publication_id, history_digest: digest(hist), history_length: hist.length, blocked_runs: Object.entries<any>(M.quality_gate).filter(([, v]) => v.decision === "blocked").map(([k]) => k).sort(),
    pointer_never_moved_by_blocked: hist.every((h, k) => k === 0 || h.gate_decision !== "blocked" || h.pointer_after === hist[k - 1].pointer_after) }, cw.pointer);
  eq("complete world: runs, durations, backfills, models per layer", [{ overall: M.runs.overall, durations: { successful: { count: M.runs.durations.successful.count, mean_minutes: M.runs.durations.successful.mean_minutes }, failed: { count: M.runs.durations.failed.count, mean_minutes: M.runs.durations.failed.mean_minutes } } }, M.backfills,
    Object.fromEntries(["staging", "intermediate", "marts"].map((l) => [l, raw.model_definitions.filter((m) => m["layer"] === l).length]))], [cw.runs, cw.backfills, cw.models]);
  const per: Record<string, number> = {};
  for (const q of raw.quality_results) per[q["rule_name"]] = (per[q["rule_name"]] ?? 0) + 1;
  eq("complete world: quality results per rule", Object.fromEntries(Object.entries(per).sort(([a], [b]) => (a < b ? -1 : 1))), cw.quality_results_per_rule);
}
// the manifest's own recorded statistics (complete world) against what the published files give in full
{
  const S = manifest.stats!, I = ds.ingestion, M = ds.g.metrics;
  eq("manifest.stats.ingestion.overall = batch_summaries totals", { accepted_unique: I.overall.accepted_unique, duplicate: I.overall.duplicate, duplicate_rate: I.overall.duplicate_rate, quarantined: I.overall.quarantined, received: I.overall.received, rejection_rate: I.overall.rejection_rate }, S["ingestion"].overall);
  eq("manifest.stats.batches_by_kind = batch_summaries kinds", Object.fromEntries(Object.entries(I.by_kind).map(([k, v]) => [k, v.batches])), S["batches_by_kind"]);
  eq("manifest.stats.quarantine_by_reason_committed_batches = summaries", I.overall.quarantine_by_reason, S["quarantine_by_reason_committed_batches"]);
  eq("manifest.stats.retry = fetch_log (sans source_id; by_status is the manifest's fetch_log_statuses)", (({ by_status, ...r }) => ({ ...r, fetch_log_statuses: by_status, source_id: "src-shipments" }))(ds.retry!), S["retry"]);
  eq("manifest.stats.incidents: 25 closed, 25 verified, mean 60.6827, all consistent, by type", [ds.incidents.total, ds.incidents.closed, ds.incidents.open, ds.incidents.verified, ds.incidents.mean_recovery_minutes, ds.incidents.all_closures_consistent, ds.incidents.by_class],
    [S["incidents"].total, S["incidents"].closed, S["incidents"].open, S["incidents"].verified, String(S["incidents"].mean_recovery_minutes).replace(/^60\.6827$/, "60.6827"), S["incidents"].all_closures_consistent, S["incidents"].by_type]);
  eq("manifest.stats.runs: successful 1318 (13.9114 min), failed 25 (13.7227 min), overall rates", [M.runs.durations.successful.count, M.runs.durations.successful.mean_minutes, M.runs.durations.failed.count, M.runs.durations.failed.mean_minutes, M.runs.overall.attempt_success_rate, M.runs.overall.task_success_rate], [S["runs"].successful.count, S["runs"].successful.mean_minutes, S["runs"].failed.count, S["runs"].failed.mean_minutes, S["runs"].overall.attempt_success_rate, S["runs"].overall.task_success_rate]);
  eq("manifest.stats.quality_gate (D-09): 1343 runs, 1328 reached the gate, 1318 allowed, 10 blocked at the gate, 15 failed before it; publications; models", [funnel(ds), raw.publications.length, M.publications.current_publication_id],
    [{ runs: S["quality_gate"].runs, reached: S["quality_gate"].reached_gate, allowed: S["quality_gate"].allowed, blocked: S["quality_gate"].blocked_at_gate, failedBefore: S["quality_gate"].failed_before_gate }, S["publications"].count, S["publications"].current_publication_id]);
  eq("manifest.stats.backfills = the domain's", [M.backfills.overall, M.backfills.refused], [S["backfills"].overall, S["backfills"].refused]);
  eq("manifest.stats.freshness_at_as_of: ingestion ages equal the checkpoints' and the freshness equals cutoff minus the recorded event", ds.freshness.map((f) => [f.source_id, f.freshness_seconds, f.ingestion_age_seconds, f.last_ingestion_at, f.latest_event_at]),
    Object.entries<any>(S["freshness_at_as_of"]).sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => [k, v.freshness_seconds, v.ingestion_age_seconds, v.last_successful_ingestion_at, v.latest_accepted_event_at]));
  eq("manifest.sample.published_world = the sample computation (ingestion overall, publications, content hashes ok 0, pointer)", [M.ingestion.overall, raw.publications.length, Object.values<any>(M.publications.publications).filter((p) => p.content_hash_ok).length, M.publications.current_publication_id],
    [manifest.sample!["published_world"].ingestion_overall, manifest.sample!["published_world"].publications, manifest.sample!["published_world"].publications_content_hash_ok, manifest.sample!["published_world"].current_publication_id]);
  eq("manifest.sample: 62 sampled batches and 2000 rows = batch_summaries' sampled flags", [I.sampled_batches, I.sampled_rows, raw.raw_records.length], [manifest.sample!["batches_sampled"], manifest.sample!["cap_used"], manifest.sample!["raw_records_published"]]);
  eq("manifest.full_world counts: raw rows written 40,191; received by committed batches 39,901; row_counts of the complete world", [Object.values(I.by_kind).reduce((a, k) => a + k.written_rows, 0), I.overall.received, manifest.full_world!["row_counts"]["raw_records"]], [manifest.full_world!["raw_records_written_in_all_batches"], manifest.full_world!["raw_records_received_by_committed_batches"], 40191]);
  eq("contract version in the config", manifest.config["contract_version"], CONTRACT_VERSION);
}
// designed relationships and the injection manifest's checks
{
  const dc = ref.claims.designed;
  const mine = ds.claims.filter((c) => c.basis !== "recorded");
  eq("designed relationships: every figure the TypeScript re-derives equals Python's (same keys)", Object.fromEntries(mine.map((c) => [`${c.id}:${c.key}`, c.got])), dc);
  const complete = ds.claims.filter((c) => c.basis === "complete");
  eq(`designed relationships: all ${complete.length} figures recomputable from files published in full equal the manifest's realised values`, complete.filter((c) => c.ok !== true).map((c) => `${c.id}:${c.key}`), []);
  const sample = ds.claims.filter((c) => c.basis === "sample");
  console.log(`OK       designed relationships over the 2,000-row sample: ${sample.filter((c) => c.ok).length} of ${sample.length} sampled figures hold (the rest describe the complete world; shown as such on screen)`);
  eq("designed relationships: DR-01..DR-05 all represented, recorded-only figures carry no recomputed value", [[...new Set(ds.claims.map((c) => c.id))], ds.claims.filter((c) => c.basis === "recorded").every((c) => c.got === null && c.ok === null)], [["DR-01", "DR-02", "DR-03", "DR-04", "DR-05"], true]);
  eq("DR-01: the silent source is src-refunds: freshness 262378 s with ingestion age 17363 s, 72 green runs, completeness 0.000000 on the three silent days", [ds.freshness.find((f) => f.source_id === "src-refunds")?.freshness_seconds, ds.claims.find((c) => c.key === "ingestion_age_seconds")?.got, ds.claims.find((c) => c.key === "runs_succeeded")?.got, ds.claims.filter((c) => c.key.startsWith("completeness.")).map((c) => c.got)], [262378, 17363, 72, ["0.000000", "0.000000", "0.000000"]]);
  const inj = ds.injection;
  eq("injection checks: the pass/fail of every one of the 41 machine-checkable checks over the sample equals Python's", inj.map((c) => [c.injection, c.path, c.ok]), ref.claims.injection);
  eq(`injection checks: ${ref.claims.injection_holding} of ${inj.length} hold over the sample (the rest describe the complete world)`, inj.filter((c) => c.ok).length, ref.claims.injection_holding);
  eq("injection manifest: twelve injections INJ-01..INJ-12, one per P08-TEST-01..12", ds.injections.map((i) => [i["id"], i["test"]]), Array.from({ length: 12 }, (_, i) => [`INJ-${String(i + 1).padStart(2, "0")}`, `P08-TEST-${String(i + 1).padStart(2, "0")}`]));
  eq("injection manifest: dataset_hash and version equal the manifest's", [injm.dataset_hash, injm.dataset_version], [manifest.dataset_hash, manifest.dataset_version]);
  const notHold = inj.filter((c) => !c.ok);
  eq("injection checks that do not hold on the sample are all about batches or publications whose rows are not in the 2,000-row sample", notHold.every((c) => /^metrics\.(ingestion\.sources\.[^.]+\.batches\.b-\d+\.accepted_unique|reconciliation\.pub-\d+\.residual|publications\.publications\.pub-\d+\.published_records)$/.test(c.path)), true);
}
// the three hash kinds over the snapshot
{
  const H = ref.hashes;
  const rawBad = raw.raw_records.filter((r) => payloadHash(r["payload_json"]) !== r["payload_hash"]).length;
  const defBad = raw.model_definitions.filter((m) => definitionHash(m["definition"]) !== m["definition_hash"]).length;
  const okPubs = Object.values<any>(ds.g.metrics.publications.publications).filter((p) => p.content_hash_ok).length;
  eq(`payload_hash recomputed for the ${raw.raw_records.length} sampled rows (Python: ${H.raw_payload_hash_ok} of ${H.raw_rows})`, [raw.raw_records.length - rawBad, raw.raw_records.length], [H.raw_payload_hash_ok, H.raw_rows]);
  eq(`definition_hash recomputed for the ${raw.model_definitions.length} models`, [raw.model_definitions.length - defBad, raw.model_definitions.length], [H.definition_hash_ok, H.models]);
  eq("content_hash: 0 of 1,318 publications verify over the sample (D-07), as Python finds", [okPubs, raw.publications.length], [H.publication_content_hash_ok, H.publications]);
  eq("dataset_hash verified by both implementations", H.dataset_hash_ok, true);
}
// the simulations' building blocks on the published rows
{
  const accepted = ds.acc["backfill_requests"]!;
  const ask = { source_id: "src-inventory", start_at: "2026-08-22T00:00:00Z", end_at: "2026-08-24T00:00:00Z" };
  eq("backfill console (D-09): bf-004 settled partial, so a range over its unverified partition is accepted and names what it backfills again; a touching range is accepted; a half-day is refused", [
    decideBackfill(accepted, ask).accepted, decideBackfill(accepted, ask).revisits,
    decideBackfill(accepted, { source_id: "src-inventory", start_at: "2026-08-23T00:00:00Z", end_at: "2026-08-24T00:00:00Z" }).accepted,
    decideBackfill(accepted, { ...ask, start_at: "2026-08-22T12:00:00Z" }).code,
    decideBackfill(accepted, { ...ask, source_id: "src-orders" }).accepted], [true, [{ backfill_id: "bf-004", partition: "2026-08-22" }], true, "PARTITION_ALIGNMENT", true]);
  eq("backfill console (D-09): a request that is still requested or running blocks an overlapping one with BACKFILL_OVERLAP; once complete it does not", [
    decideBackfill([...accepted, { backfill_id: "bf-016", source_id: "src-inventory", start_at: ask.start_at, end_at: ask.end_at, status: "requested" }], ask).code,
    decideBackfill([...accepted, { backfill_id: "bf-016", source_id: "src-inventory", start_at: ask.start_at, end_at: ask.end_at, status: "running" }], ask).overlaps_with,
    decideBackfill([...accepted, { backfill_id: "bf-016", source_id: "src-inventory", start_at: ask.start_at, end_at: ask.end_at, status: "complete" }], ask).accepted], ["BACKFILL_OVERLAP", "bf-016", true]);
  eq("the published refusals were refused in history: bf-006 over bf-004 and bf-012 over bf-010, each made while the earlier request was still running", ds.result.imported.rejected.filter((r) => r.entity === "backfill_requests").map((r) => [r.id, r.reason_code]), [["bf-006", "BACKFILL_OVERLAP"], ["bf-012", "BACKFILL_OVERLAP"]]);
  eq("quarantine desk: a corrected quantity is accepted, the same key again is a duplicate (the key check runs first), an unknown op stays quarantined", [
    retryRow("K1", { record_id: "K1", quantity: 2, unit_price: "1.00", amount: "2.00", event_ts: "2026-10-04T00:00:00Z" }, new Set()).kind,
    retryRow("K1", { record_id: "K1", quantity: -2, unit_price: "1.00", amount: "2.00", event_ts: "2026-10-04T00:00:00Z" }, new Set(["K1"])).kind,
    retryRow("K1", { op: "merge", record_id: "K1" }, new Set()).reason], ["accepted", "duplicate", "UNKNOWN_OP"]);
}

if (failures) { console.log(`FAILED (${failures} of ${checks} checks)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks)`);
