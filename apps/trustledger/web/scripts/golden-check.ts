// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) leaf by leaf for the golden fixture and its
// two variants, the per-entity golden copy the site serves (through the same input-building code as the browser), the spec sentence in
// words, the arithmetic and time primitives, the generator's twelve defect checks and six designed relationships over the snapshot, and the
// PYTHON domain's results over the published snapshot (scripts/snapshot-reference.json, produced once by scripts/make-snapshot-reference.py):
// digests of every metric block at the as-of 2026-10-05 and at 2026-09-14 and 2026-08-17 (under the version in force, w1 and w2, match
// precision from the manifest's truth), a windowed case, the class of every issue, the identity map, and the zone probes (every local
// time on every day of 2026 and the occurrence around both DST transitions in seven zones). Prints "ALL OK (N checks)" or exits 1.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { makeDataset, type Dataset } from "../src/data/dataset";
import { FILES, isManifest, rawOf } from "../src/data/inputs";
import { METRIC_KEYS } from "../src/domain/contract";
import { compute } from "../src/domain/metrics";
import { fracOfDec, fr, h4, p6, rnd } from "../src/domain/num";
import { goldenOf, runPipeline } from "../src/domain/pipeline";
import { isoZ, localToUtc, parseHhmm, parseTs, scheduledOccurrence, daysFromCivil } from "../src/domain/time";
import { designedClaims, injectionChecks } from "../src/lib/claims";

const ROOT = new URL("../../", import.meta.url);
const WEB = new URL("../", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8")); // eslint-disable-line @typescript-eslint/no-explicit-any

let failures = 0, checks = 0;
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : typeof x === "bigint" ? x.toString() : x));
const digest = (v: unknown): string => createHash("sha256").update(canon(v)).digest("hex");
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
  const g = flat(got, "", new Map()), w = flat(want, "", new Map());
  let bad = 0;
  for (const k of new Set([...g.keys(), ...w.keys()])) {
    checks++;
    if (!g.has(k) || !w.has(k) || g.get(k) !== w.get(k)) { failures++; bad++; if (bad <= 8) console.log(`MISMATCH ${label}${k}: got ${String(g.get(k))} want ${String(w.get(k))}`); }
  }
  console.log(`${bad === 0 ? "OK      " : "MISMATCH"} ${label}: ${w.size} leaves`);
  return w.size;
}
/** json.dumps(rows, sort_keys=True, separators=(",", ":")) with ensure_ascii, as the generator hashes its entity files. */
const pyDumps = (v: unknown): string => JSON.stringify(v, (_k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : x))
  .replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);

// ---------------------------------------------------------------------------------------------- fixture hashes
const FIX = new URL("tests/fixtures/golden/", ROOT);
const hashes = readJson(new URL("HASHES.json", FIX)).sha256 as Record<string, string>;
for (const [f, h] of Object.entries(hashes)) eq(`fixture ${f}: sha-256`, createHash("sha256").update(readFileSync(new URL(f, FIX), "utf8")).digest("hex"), h, true);
console.log(`OK       ${Object.keys(hashes).length} fixture files match HASHES.json`);

// ---------------------------------------------------------------------------------------------- golden and its variants
for (const v of ["", "variant-rejected/", "variant-empty/"]) {
  const inputs = readJson(new URL(`${v}inputs.json`, FIX));
  const want = readJson(new URL(`${v}expected.json`, FIX));
  const res = runPipeline(inputs);
  leaves(`${v || "golden/"}expected.json`, goldenOf(res), want);
  eq(`${v || "golden/"}metric keys in contract order`, Object.keys(res.metrics), [...METRIC_KEYS]);
}

// ---------------------------------------------------------------------------------------------- the data the site serves
const PUB = new URL("public/data/", WEB);
const loadFrom = (dir: string): { manifest: any; ds: Dataset } => {
  const manifest = readJson(new URL(`${dir}manifest.json`, PUB));
  if (!isManifest(manifest)) throw new Error(`${dir}manifest.json is not a manifest`);
  const raw = rawOf(new Map(FILES.map((f) => [f, readJson(new URL(`${dir}${f}.json`, PUB))] as const)));
  const expected = dir ? readJson(new URL(`${dir}expected.json`, PUB)) : null;
  const inj = !dir && manifest.injection_manifest ? readJson(new URL(manifest.injection_manifest, PUB)) : null;
  return { manifest, ds: makeDataset(dir ? "golden" : "snapshot", manifest, raw, expected, inj) };
};
const gold = loadFrom("golden/");
eq("golden/expected.json served = fixture expected.json", gold.ds.expected, readJson(new URL("expected.json", FIX)));
leaves("golden per-entity copy through the site's input builder = expected.json", gold.ds.goldenShape(), gold.ds.expected);
eq("golden manifest: dataset_hash = HASHES.json hash of inputs.json; dataset_version golden-v1", [gold.manifest.dataset_hash, gold.manifest.dataset_version], [hashes["inputs.json"], "golden-v1"]);
eq("golden manifest: the synthetic truth equals the fixture's", gold.manifest.synthetic_truth.true_entity, readJson(new URL("inputs.json", FIX)).synthetic_truth.true_entity);
for (const f of FILES) if (f !== "weight_versions") eq(`golden copy ${f}: row count = manifest`, gold.ds.raw[f].length, gold.manifest.row_counts[f], true);
console.log("OK       golden copy row counts match its manifest");

// the sentence of the specification, in words and in the dataset's own computation (the pages show these strings)
{
  const m = gold.ds.now.metrics;
  const c = m["completeness"]["r-cust-complete-email"], v = m["validity"]["r-cust-valid-email"], u = m["uniqueness"]["r-cust-key-unique"], r = m["relationship_integrity"]["r-ord-cust-fk"], w = m["weighted_score"]["datasets"]["ds-customers"];
  eq("spec: 100 eligible rows, 5 missing e-mails, completeness 0.950000 (2 of the 5 are whitespace-only)", [c.eligible_count, c.missing_count, c.whitespace_only_count, c.populated_count, c.value], [100, 5, 2, 95, "0.950000"]);
  eq("spec: populated-only validity 90/95 = 0.947368 and all-eligible 90/100 = 0.900000, both labelled", [v.populated_only, v.all_eligible, v.populated_count, v.passing_count], [{ label: "validity_populated_only", value: "0.947368" }, { label: "validity_all_eligible", value: "0.900000" }, 95, 90]);
  eq("spec: uniqueness 1/98 groups = 0.010204 and 2/100 rows = 0.020000", [u.group_share, u.row_share, u.distinct_keys], [{ label: "duplicate_group_share", value: "0.010204" }, { label: "duplicate_row_share", value: "0.020000" }, 98]);
  eq("spec: relationship 36/38 = 0.947368 with 2 null foreign keys counted separately", [r.total_fk_count, r.null_fk_count, r.eligible_count, r.matched_count, r.value], [40, 2, 38, 36, "0.947368"]);
  eq("spec: timeliness 3/4 = 0.750000; the refresh at the deadline is late (05:00 is not < 05:00)", [m["timeliness"].value, m["timeliness"].datasets["ds-shipments"].on_time, m["timeliness"].datasets["ds-payments"].on_time], ["0.750000", false, true]);
  eq("spec: weighted 0.963932 (w2) and 0.958116 (w1) with the critical override true beside both", [w.value, m["weighted_score"].by_weight_version.w1["ds-customers"], w.critical_override, w.critical_failures, w.critical_open_issues], ["0.963932", "0.958116", true, 2, 1]);
  eq("spec: ownership 4/5, definitions 3/4, lineage 5/6, precision 2/3, resolution mean 38.4444 h", [m["ownership_coverage"].value, m["definition_coverage"].value, m["lineage_coverage"].value, m["match_precision"].precision, m["resolution_time"].mean_hours], ["0.800000", "0.750000", "0.833333", "0.666667", "38.4444"]);
  eq("spec: reviewed_correct_share 2/4 = 0.500000 is reported beside precision, labelled apart", m["match_precision"].reviewed_correct_share, "0.500000");
  eq("a rule version change is not comparable: RULE_VERSION_DIFFERS, no rates compared", gold.ds.now.rules["comparisons"]["r-cust-valid-email"], { previous_run_id: "rr-002", previous_rule_version: 1, current_rule_version: 2, comparable: false, reason: "RULE_VERSION_DIFFERS", previous_eligible_count: 92, current_eligible_count: 100, failure_rate_previous: null, failure_rate_current: null });
}

// ---------------------------------------------------------------------------------------------- primitives
{
  eq("rnd: ROUND_HALF_UP, once, at the stated places; never -0.00", [rnd(fr(5, 10_000_000), 6), rnd(fr(-4, 1000), 2), rnd(fr(-5, 1000), 2), rnd(fr(5, 1000), 2), rnd(fr(1, 3), 6), rnd(fr(2, 3), 4), rnd(fr(7, 2), 0)], ["0.000001", "0.00", "-0.01", "0.01", "0.333333", "0.6667", "4"]);
  eq("p6/h4 keep null as null (unknown, never 0)", [p6(null), h4(null)], [null, null]);
  eq("fracOfDec is exact", [rnd(fracOfDec("0.250000"), 6), rnd(fracOfDec("1"), 2)], ["0.250000", "1.00"]);
  eq("parseTs / isoZ round trip, offsets, fractional seconds", [isoZ(parseTs("2026-10-05T00:00:00Z")), isoZ(parseTs("2026-10-05T05:30:00+05:30")), isoZ(parseTs("2026-10-05 00:00:00.5Z")), isoZ(parseTs("2026-02-28T23:59:59Z"))], ["2026-10-05T00:00:00Z", "2026-10-05T00:00:00Z", "2026-10-05T00:00:00.500000Z", "2026-02-28T23:59:59Z"]);
  const bad = ["2026-10-05", "2026-10-05T00:00:00", "2026-02-30T00:00:00Z", "2026-13-01T00:00:00Z", "2026-10-05T24:00:00Z", 5, null];
  eq("parseTs refuses naive, impossible and non-text instants", bad.map((b) => { try { parseTs(b); return "accepted"; } catch { return "refused"; } }), bad.map(() => "refused"));
  const day = (y: number, m: number, d: number): number => daysFromCivil(y, m, d);
  const at = (y: number, m: number, d: number, hhmm: string, tz: string): string => { const [h, mi] = parseHhmm(hhmm); return isoZ(localToUtc(day(y, m, d), h, mi, tz))!; };
  eq("local time to UTC: EDT, EST, BST, GMT, a zone without DST", [at(2026, 10, 4, "06:00", "America/New_York"), at(2026, 11, 2, "06:00", "America/New_York"), at(2026, 10, 4, "07:00", "Europe/London"), at(2026, 12, 1, "07:00", "Europe/London"), at(2026, 10, 4, "06:00", "Asia/Kolkata")],
    ["2026-10-04T10:00:00Z", "2026-11-02T11:00:00Z", "2026-10-04T06:00:00Z", "2026-12-01T07:00:00Z", "2026-10-04T00:30:00Z"]);
  eq("clocks going back: 01:30 occurs twice and is the LATER instant (New York 2026-11-01, London 2026-10-25)", [at(2026, 11, 1, "01:30", "America/New_York"), at(2026, 10, 25, "01:30", "Europe/London")], ["2026-11-01T06:30:00Z", "2026-10-25T01:30:00Z"]);
  eq("clocks going forward: 02:30 does not exist and uses the offset before the change (New York 2026-03-08, Berlin 2026-03-29)", [at(2026, 3, 8, "02:30", "America/New_York"), at(2026, 3, 29, "02:30", "Europe/Berlin")], ["2026-03-08T07:30:00Z", "2026-03-29T01:30:00Z"]);
  const occ = (tz: string, lt: string, g: number, asOf: string): string[] => scheduledOccurrence(tz, lt, g, parseTs(asOf)).map((x) => isoZ(x)!);
  eq("occurrence: the latest whose grace has closed by the as-of (a deadline equal to the as-of counts)", [occ("Europe/London", "07:00", 30, "2026-10-05T00:00:00Z"), occ("America/New_York", "06:00", 60, "2026-10-05T11:00:00Z"), occ("America/New_York", "06:00", 60, "2026-10-05T10:59:59Z")],
    [["2026-10-04T06:00:00Z", "2026-10-04T06:30:00Z"], ["2026-10-05T10:00:00Z", "2026-10-05T11:00:00Z"], ["2026-10-04T10:00:00Z", "2026-10-04T11:00:00Z"]]);
}

// ---------------------------------------------------------------------------------------------- the snapshot vs the Python domain
const ref = readJson(new URL("scripts/snapshot-reference.json", WEB));
const snap = loadFrom("");
const ds = snap.ds;
eq("snapshot: dataset_hash, version and as-of equal the Python reference's", [snap.manifest.dataset_hash, snap.manifest.dataset_version, snap.manifest.as_of], [ref.dataset_hash, ref.dataset_version, ref.as_of]);
eq("snapshot: dataset_hash = sha-256 of the 14 entity files (json.dumps sort_keys, compact, entity-name order)", createHash("sha256").update([...FILES].sort().map((e) => pyDumps(ds.raw[e])).join("")).digest("hex"), snap.manifest.dataset_hash);
eq("snapshot: the hash check agrees with Python", ref.dataset_hash_check.sha256_of_14_entity_files, snap.manifest.dataset_hash);
for (const f of FILES) if (f !== "weight_versions") eq(`snapshot ${f}: row count = manifest`, ds.raw[f].length, snap.manifest.row_counts[f], true);
console.log("OK       snapshot row counts match its manifest");
eq("snapshot: ingest counts and rejected count equal Python's", [ds.result.ingest.counts, ds.result.ingest.rejected.length], [ref.ingest_counts, ref.rejected_count]);
eq("snapshot: the manifest's truth is not in the inputs the matcher reads", [Object.keys(ds.inputs).some((k) => k.includes("truth")), JSON.stringify(ds.inputs).includes("true_entity")], [false, false]);

const summarise = (c: ReturnType<typeof compute>): Record<string, unknown> => {
  const dig: Record<string, string> = Object.fromEntries(METRIC_KEYS.map((k) => [k, digest(c.metrics[k])]));
  dig["rules"] = digest(c.rules); dig["definitions"] = digest(c.definitions); dig["matching"] = digest(c.matching);
  return { weight_version: c.weight_version, empty_population: c.empty_population, warning_codes: c.warnings.map((w) => w.code).sort(), digests: dig,
    issue_classes: { resolved: c.views.filter((v) => v.cls === "resolved").length, claimed: c.views.filter((v) => v.cls === "claimed").length, open: c.views.filter((v) => v.cls === "open").length },
    issue_class_digest: digest(c.views.map((v) => [v.issue.issue_id, v.cls])) };
};
for (const [t, byWv] of Object.entries<any>(ref.as_ofs)) {
  for (const [wv, want] of Object.entries<any>(byWv)) {
    const got = summarise(ds.at(parseTs(t), wv === "default" ? null : wv)) as any;
    eq(`as-of ${t} under ${wv} (${got.weight_version}): weight version, empty flag, warnings, issue classes`, [got.weight_version, got.empty_population, got.warning_codes, got.issue_classes, got.issue_class_digest], [want.weight_version, want.empty_population, want.warning_codes, want.issue_classes, want.issue_class_digest], true);
    for (const k of Object.keys(want.digests)) eq(`as-of ${t} under ${wv}: ${k} digest`, got.digests[k], want.digests[k], true);
    console.log(`OK       as-of ${t} under ${wv}: ${Object.keys(want.digests).length} block digests, weight ${want.weight_version}, issues ${JSON.stringify(want.issue_classes)}`);
  }
}
{
  const w = ref.window_case;
  const got = summarise(compute(ds.result.population, ds.asOf, null, [parseTs(w.from), parseTs(w.to)], ds.truth)) as any;
  for (const k of Object.keys(w.digests)) eq(`window [${w.from}, ${w.to}): ${k} digest`, got.digests[k], w.digests[k], true);
  eq("window case: issue classes and warnings", [got.issue_classes, got.warning_codes], [w.issue_classes, w.warning_codes], true);
  console.log(`OK       half-open window [${w.from}, ${w.to}): ${Object.keys(w.digests).length} block digests equal Python's`);
}
{
  const m = ds.now.metrics;
  leaves("as-of headline blocks (complete: dimensions, weighted score, critical, ownership, definitions, lineage, precision, timeliness)", Object.fromEntries(Object.keys(ref.full_at_as_of).map((k) => [k, m[k]])), ref.full_at_as_of);
  eq("as-of resolution summary (counts and mean hours)", Object.fromEntries(Object.entries(m["resolution_time"]).filter(([k]) => k !== "issues")), ref.resolution_summary);
  eq("as-of class, hours and cycles of every issue", Object.fromEntries(Object.entries<any>(m["resolution_time"].issues).map(([k, b]) => [k, [b.class, b.resolution_hours, b.claimed_hours, b.age_hours, b.reopen_cycles]])), ref.issues_at_as_of);
  eq("as-of matching summary, identity map and mapping history", [Object.fromEntries(Object.entries(ds.now.matching).filter(([k]) => k !== "identity_map" && k !== "mapping_history")), digest(ds.now.matching["identity_map"]), digest(ds.now.matching["mapping_history"])], [ref.matching_summary, ref.identity_map_digest, ref.mapping_history_digest]);
  eq("as-of rules block (runs, comparisons, disabled)", digest(ds.now.rules), ref.rule_runs_at_as_of_digest);
}
{
  const zp = ref.zone_probe;
  for (const z of zp.zones) {
    const out: string[] = [];
    const d0 = daysFromCivil(2026, 1, 1);
    for (let n = 0; n < 365; n++) for (const lt of zp.local_times) { const [h, m] = parseHhmm(lt); out.push(isoZ(localToUtc(d0 + n, h, m, z))!); }
    eq(`zone ${z}: UTC instant of ${zp.local_times.length} local times on each of 365 days of 2026 (${out.length}) = Python zoneinfo`, [out.length, digest(out)], [zp.local_to_utc[z].count, zp.local_to_utc[z].digest]);
    const occ: string[][] = [];
    for (const [a, b] of zp.occurrence_windows as [string, string][]) {
      for (let t = parseTs(a); t < parseTs(b); t += 30n * 60n * 1_000_000n) for (const [lt, g] of [["02:30", 60], ["01:30", 30], ["06:00", 120], ["00:00", 0]] as [string, number][]) occ.push(scheduledOccurrence(z, lt, g, t).map((x) => isoZ(x)!));
    }
    eq(`zone ${z}: evaluated occurrence every 30 minutes around both DST transitions (${occ.length}) = Python`, [occ.length, digest(occ)], [zp.occurrences[z].count, zp.occurrences[z].digest]);
  }
}
console.log("OK       the Python domain's results over the snapshot equal the TypeScript mirror's (3 as-of instants x 3 weight choices, a window, every issue, the identity map, the zones)");

// the generator's own checks and the manifest's designed relationships, re-derived from the rows
{
  const inj = injectionChecks(ds);
  eq(`INJ-01..12: ${inj.length} machine-checkable defect checks of the generator hold in the computed shape`, inj.filter((c) => !c.ok).map((c) => `${c.inj} ${c.path}`), []);
  eq("INJ: twelve defects, one per P07-TEST-01..12", [...new Set(inj.map((c) => c.inj))].length, 12);
  const dr = designedClaims(ds);
  eq(`DR-01..06: ${dr.length} designed-relationship figures in the manifest equal this computation`, dr.filter((c) => !c.ok).map((c) => `${c.id} ${c.label}: want ${c.want} got ${c.got}`), []);
  eq("DR: all six relationships are represented", [...new Set(dr.map((c) => c.id))], ["DR-01", "DR-02", "DR-03", "DR-04", "DR-05", "DR-06"]);
  eq("the golden fixture has no generator claims to check", [designedClaims(gold.ds).length, injectionChecks(gold.ds).length], [0, 0]);
}

if (failures) { console.log(`FAILED (${failures} of ${checks} checks)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks)`);
