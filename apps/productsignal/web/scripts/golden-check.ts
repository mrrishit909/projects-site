// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) leaf by leaf for the golden fixture and
// its two variants, the per-entity golden copy the site serves (through the same loader code as the browser), the spec sentence in
// words, the arithmetic primitives, and the PYTHON domain's results over the published snapshot (scripts/snapshot-reference.json,
// produced once by scripts/make-snapshot-reference.py): digests of every metric block at the as-of and at each analysis-run cutoff,
// the experiment blocks and guardrail reviews of the five runs, the segment analyses, the weekly cohort grid and the local calendar
// date of every session. Prints "ALL OK (N checks)" or exits 1.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { buildInputs, isManifest } from "../src/data/inputs";
import { makeDataset, type Dataset } from "../src/data/dataset";
import { ENTITIES, METRIC_KEYS } from "../src/domain/contract";
import { retentionGrid, guardrailReview, retentionGridWindow, revenueDifference, week4Difference, Ctx, type GridRow } from "../src/domain/metrics";
import { canonicalJson, planHash } from "../src/domain/models";
import { fmt, fr, fracOf, fxQ, q, roundDiv } from "../src/domain/num";
import { goldenOf, runPipeline } from "../src/domain/pipeline";
import { sha256, sha256Bytes } from "../src/domain/sha256";
import { chi2SfDf1, normalTwoSidedP, sqrtFrac, tCrit, wilson, zCrit, newcombe } from "../src/domain/stats";
import { dayIso, localDay, parseTs, weekdayOf } from "../src/domain/time";

const ROOT = new URL("../../", import.meta.url);
const WEB = new URL("../", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

let failures = 0, checks = 0;
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) =>
  x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : typeof x === "bigint" ? x.toString() : x);
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

// ---------------------------------------------------------------------------------------------- fixture hashes
const FIX = new URL("tests/fixtures/golden/", ROOT);
const hashes = readJson(new URL("HASHES.json", FIX)).sha256 as Record<string, string>;
for (const [f, h] of Object.entries(hashes)) {
  const text = readFileSync(new URL(f, FIX), "utf8");
  eq(`fixture ${f}: sha-256 (node:crypto)`, createHash("sha256").update(text).digest("hex"), h, true);
  eq(`fixture ${f}: sha-256 (browser implementation)`, sha256(text), h, true);
}
console.log(`OK       ${Object.keys(hashes).length} fixture files match HASHES.json (two implementations)`);

// ---------------------------------------------------------------------------------------------- golden and its variants
for (const v of ["", "variant-rejected/", "variant-empty/"]) {
  const inputs = readJson(new URL(`${v}inputs.json`, FIX));
  const want = readJson(new URL(`${v}expected.json`, FIX));
  const res = runPipeline(inputs);
  leaves(`${v || "golden/"}expected.json`, goldenOf(res), want);
  eq(`${v || "golden/"}metric keys in contract order`, Object.keys(res.metrics), [...METRIC_KEYS]);
}

// ---------------------------------------------------------------------------------------------- the golden copy the site serves
const PUB = new URL("public/data/", WEB);
const loadFrom = (dir: string): { manifest: any; inputs: any; ds: Dataset } => {
  const manifest = readJson(new URL(`${dir}manifest.json`, PUB));
  if (!isManifest(manifest)) throw new Error(`${dir}manifest.json is not a manifest`);
  const files = new Map(ENTITIES.map((e) => [e, readJson(new URL(`${dir}${e}.json`, PUB))] as const));
  const inputs = buildInputs(manifest, files);
  return { manifest, inputs, ds: makeDataset(dir ? "golden" : "snapshot", manifest, inputs, dir ? readJson(new URL(`${dir}expected.json`, PUB)) : null) };
};
const gold = loadFrom("golden/");
eq("golden/expected.json served = fixture expected.json", gold.ds.expected, readJson(new URL("expected.json", FIX)));
leaves("golden per-entity copy through the site's loader = expected.json", goldenOf(runPipeline(gold.inputs)), gold.ds.expected);
for (const e of ENTITIES) eq(`golden copy ${e}: row count = manifest`, gold.inputs[e].length, gold.manifest.row_counts[e], true);
console.log("OK       golden copy row counts match its manifest");

// the sentence of the specification, in words and in the dataset's own computation (the page shows these strings)
{
  const ex = gold.ds.at(gold.ds.cutoff).metrics.experiment!;
  const p = ex.primary;
  eq("spec: control 0.200000, treatment 0.300000", [p.variants["control"]!.conversion, p.variants["treatment"]!.conversion], ["0.200000", "0.300000"]);
  eq("spec: absolute lift +10.00 pp, relative 0.500000", [p.absolute_lift_pp, p.relative_lift], ["10.00", "0.500000"]);
  eq("spec: Newcombe [-0.020249, 0.216734], includes zero", [p.interval!.low, p.interval!.high, p.interval!.includes_zero], ["-0.020249", "0.216734", true]);
  eq("spec: Wilson control [0.133367, 0.288829], treatment [0.218949, 0.395849]", [p.variants["control"]!.wilson_95, p.variants["treatment"]!.wilson_95], [{ low: "0.133367", high: "0.288829" }, { low: "0.218949", high: "0.395849" }]);
  eq("spec: SRM OK, not conclusive, final run with one prior run", [ex.srm.verdict, p.conclusive, ex.run.interim, ex.run.prior_runs, ex.run.analysis_id], ["OK", false, false, 1, "an-002"]);
  eq("spec: day-7 retention 5 of 20 = 0.250000", [gold.ds.at(gold.ds.cutoff).metrics.retention.day7.retained, gold.ds.at(gold.ds.cutoff).metrics.retention.day7.rate], [5, "0.250000"]);
}

// ---------------------------------------------------------------------------------------------- primitives
{
  eq("q rounds half up once: 0.0000005 -> 0.000001, -0.004 -> 0.00 (never -0.00)", [q(fr(5, 10_000_000), 6), q(fr(-4, 1000), 2), q(fr(-5, 1000), 2), q(fr(5, 1000), 2)], ["0.000001", "0.00", "-0.01", "0.01"]);
  eq("fmt/roundDiv", [fmt(roundDiv(-5n, 2n), 0), fmt(12345n, 2)], ["-3", "123.45"]);
  const s2 = sqrtFrac(fr(2));
  eq("sqrt(2) truncated at 1e-20", q(s2, 20), "1.41421356237309504880");
  eq("square root: r <= sqrt(x) < r + 1e-20 (so exact to 1e-8) over a sweep of 200 rationals", Array.from({ length: 200 }, (_, i) => {
    const x = fr(i + 1, 7 + (i % 13)), r = sqrtFrac(x), up = { n: r.n + 1n, d: r.d };
    return r.n * r.n * x.d <= x.n * r.d * r.d && up.n * up.n * x.d > x.n * up.d * up.d;
  }).every(Boolean), true);
  eq("chi-square tail: stat 25.004329 -> p 0.000001; 0 -> 1.000000; 3.841459 -> 0.050000", [fxQ(chi2SfDf1(fracOf("25.004329")), 6), fxQ(chi2SfDf1(fr(0)), 6), fxQ(chi2SfDf1(fracOf("3.841459")), 6)], ["0.000001", "1.000000", "0.050000"]);
  eq("normal two-sided p(1.959964) = 0.050000; z(0.95) = 1.959964; z(0.983333) = 2.393972", [fxQ(normalTwoSidedP(fracOf("1.959964")), 6), fxQ(zCrit("0.95"), 6), fxQ(zCrit("0.983333"), 6)], ["0.050000", "1.959964", "2.393972"]);
  eq("Student t critical values at 95 %: df 99 = 1.984217, df 1 = 12.706205, df 10 = 2.228139, df 399 = 1.965927", [99, 1, 10, 399].map((n) => fxQ(tCrit(n), 6)), ["1.984217", "12.706205", "2.228139", "1.965927"]);
  const [p, lo, hi] = wilson(20, 100, fracOf("1.959964"));
  eq("Wilson 20/100", [q(p, 6), q(lo, 6), q(hi, 6)], ["0.200000", "0.133367", "0.288829"]);
  const [d, nl, nh] = newcombe(30, 100, 20, 100, fracOf("1.959964"));
  eq("Newcombe 30/100 - 20/100", [q(d, 6), q(nl, 6), q(nh, 6)], ["0.100000", "-0.020249", "0.216734"]);
  eq("canonical JSON is key-sorted and compact", canonicalJson({ b: 1, a: { d: [1, { z: 1, y: 2 }], c: "x" } }), '{"a":{"c":"x","d":[1,{"y":2,"z":1}]},"b":1}');
  eq("SHA-256 of '' and 'abc'", [sha256Bytes(new Uint8Array(0)), sha256("abc")], ["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"]);
  eq("calendar: day numbers and weekdays (2026-10-05 is a Monday)", [dayIso(parseTs("2026-10-05T00:00:00Z") / 86400), weekdayOf(parseTs("2026-10-05T00:00:00Z") / 86400)], ["2026-10-05", 0]);
  eq("local date at the zone edges (EDT -4, PDT -7, BST +1)", [
    dayIso(localDay(parseTs("2026-10-05T03:59:59Z"), "America/New_York")), dayIso(localDay(parseTs("2026-10-05T04:00:00Z"), "America/New_York")),
    dayIso(localDay(parseTs("2026-10-05T06:59:59Z"), "America/Los_Angeles")), dayIso(localDay(parseTs("2026-10-05T07:00:00Z"), "America/Los_Angeles")),
    dayIso(localDay(parseTs("2026-10-04T22:59:59Z"), "Europe/London")), dayIso(localDay(parseTs("2026-10-04T23:00:00Z"), "Europe/London"))],
    ["2026-10-04", "2026-10-05", "2026-10-04", "2026-10-05", "2026-10-04", "2026-10-05"]);
}

// ---------------------------------------------------------------------------------------------- the snapshot vs the Python domain
const ref = readJson(new URL("scripts/snapshot-reference.json", WEB));
const snap = loadFrom("");
const ds = snap.ds;
eq("snapshot: dataset_hash and version equal the Python reference's", [snap.manifest.dataset_hash, snap.manifest.dataset_version, snap.manifest.as_of], [ref.dataset_hash, ref.dataset_version, ref.as_of]);
eq("snapshot: dataset_hash = sha-256 of the 12 entity files (canonical JSON, entity-name order)", sha256([...ENTITIES].sort().map((e) => canonicalJson(snap.inputs[e])).join("")), snap.manifest.dataset_hash);
eq("snapshot: dataset_hash check agrees with Python", ref.dataset_hash_check.sha256_of_entity_files_sorted_by_name, snap.manifest.dataset_hash);
for (const e of ENTITIES) eq(`snapshot ${e}: row count = manifest`, snap.inputs[e].length, snap.manifest.row_counts[e], true);
console.log("OK       snapshot row counts match its manifest");
eq("snapshot: ingest counts and rejected count", [ds.ingest.counts, ds.ingest.rejected.length], [ref.ingest_counts, ref.rejected_count]);
for (const [xv, plan] of ds.plans) eq(`plan ${xv}: sha-256 of the plan without config_hash = config_hash`, [planHash(plan.body), plan.hash_valid], [plan.config_hash, true]);
eq("snapshot: the manifest windows are the defaults for the as-of", ds.windows, runPipeline({ ...snap.inputs, metric_windows: undefined }, snap.manifest.as_of).windows);

for (const [cut, entry] of Object.entries<any>(ref.cutoffs)) {
  const t = parseTs(cut);
  const base = ds.at(t, "xv-001");
  for (const [k, want] of Object.entries<string>(entry.common)) {
    const got = k === "tracking_quality" ? base.tracking_quality : k === "identity" ? base.identity : (base.metrics as any)[k];
    eq(`cutoff ${cut}: ${k} digest`, digest(got), want, true);
  }
  for (const xv of Object.keys(entry.experiment)) eq(`cutoff ${cut}: experiment ${xv} digest`, digest(ds.at(t, xv).metrics.experiment), entry.experiment[xv], true);
  eq(`cutoff ${cut}: warnings (without SRM and interim)`, base.warnings.map((w) => w.code).filter((c) => c !== "SRM_MISMATCH" && c !== "INTERIM_RUN").sort(), entry.warning_codes, true);
  console.log(`OK       cutoff ${cut} (${entry.windows} windows): ${Object.keys(entry.common).length} common digests + ${Object.keys(entry.experiment).length} experiment digests`);
}
for (const xv of Object.keys(ref.as_of_metrics)) leaves(`as-of metrics ${xv} (complete)`, ds.at(ds.asOf, xv).metrics, ref.as_of_metrics[xv]);
leaves("as-of tracking quality and identity", { tq: ds.at(ds.asOf).tracking_quality, id: ds.at(ds.asOf).identity }, { tq: ref.as_of_tracking_quality, id: ref.as_of_identity });

for (const [aid, want] of Object.entries<any>(ref.runs)) {
  const run = ds.runs.find((r) => r.analysis_id === aid)!;
  const comp = ds.at(run.cutoff_at, run.experiment_version_id, aid);
  const ex = comp.metrics.experiment!;
  leaves(`run ${aid} experiment block`, ex, want.experiment);
  leaves(`run ${aid} guardrail review`, guardrailReview(ex, ds.plans.get(run.experiment_version_id)!), want.guardrail_review);
  eq(`run ${aid} warnings`, comp.warnings.map((w) => w.code).sort(), want.warning_codes, true);
  for (const by of ["plan", "segment", "timezone"]) {
    const seg = ds.segments(run.cutoff_at, run.experiment_version_id, by);
    const w = ref.segments[`${aid}/${by}`];
    eq(`run ${aid} segments by ${by}: digest, segments tested, Bonferroni threshold`, [digest(seg), seg.segments_tested, seg.bonferroni_threshold], [w.digest, w.segments_tested, w.bonferroni_threshold], true);
    if (w.full) leaves(`run ${aid} segments by ${by} (complete)`, seg, w.full);
  }
}
console.log("OK       five runs: experiment blocks, guardrail reviews and segment analyses equal the Python domain's");

// D-10: the segments page corrects the comparisons of every split it offers together (R6-13); the case study's secondary figures (R6-10)
for (const [key, want] of Object.entries<any>(ref.segments_family)) {
  const [aid, by] = key.split("/") as [string, string];
  const run = ds.runs.find((r) => r.analysis_id === aid)!;
  const seg = ds.segmentsFamily(run.cutoff_at, run.experiment_version_id, by);
  eq(`run ${aid} segments by ${by} with the family correction: k, tested, threshold, digest`, [seg.family_size, seg.segments_tested, seg.bonferroni_threshold, digest(seg)], [want.family_size, want.segments_tested, want.bonferroni_threshold, want.digest], true);
}
console.log("OK       segment analyses with the family-wide Bonferroni k equal the Python domain's");
{
  const want = ref.secondary["xv-001@as_of"];
  const plan = ds.plans.get("xv-001")!;
  const ctx = new Ctx(ds.population, ds.asOf, ds.canonAt(ds.asOf), null);
  const w4 = week4Difference(ctx, plan), rv = revenueDifference(ctx, plan);
  eq("secondary: week-4 retention by arm, difference and Newcombe interval equal Python's", [w4.by_variant["control"], w4.by_variant["treatment"], w4.difference_pp, w4.interval!.low, w4.interval!.high, w4.interval!.includes_zero],
    [want.week4.by_variant.control, want.week4.by_variant.treatment, want.week4.difference_pp, want.week4.low, want.week4.high, want.week4.includes_zero]);
  eq("secondary: revenue difference with the Welch interval equals Python's", [rv.by_variant["control"], rv.by_variant["treatment"], rv.difference, rv.interval!.df, rv.interval!.t, rv.interval!.low, rv.interval!.high, rv.interval!.includes_zero],
    [want.revenue.by_variant.control, want.revenue.by_variant.treatment, want.revenue.difference, want.revenue.df, want.revenue.t, want.revenue.low, want.revenue.high, want.revenue.includes_zero]);
  const man = ds.manifest.designed_relationships!;
  const dr2 = man.find((d) => d.id === "DR-02")!.realised as any;
  eq("secondary: week-4 retention equals the generator's DR-02 (71 of 200 vs 62 of 200, -4.50 pp, [-0.136053, 0.047102])", [w4.by_variant["control"]!.retained, w4.by_variant["treatment"]!.retained, w4.difference_pp], [dr2.week4.control.retained, dr2.week4.treatment.retained, "-4.50"]);
}

// D-08, in words: the interim cutoff of 2026-05-18 sees only the facts that existed by then
{
  const ex = ds.at(parseTs("2026-05-18T00:00:00Z"), "xv-001").metrics.experiment!;
  eq("D-08 at 2026-05-18: 155 assigned (77/78), SRM OK 0.006452, interim", [ex.assigned_units, ex.srm.observed, ex.srm.verdict, ex.srm.statistic, ex.run.interim], [155, { control: 77, treatment: 78 }, "OK", "0.006452", true]);
  eq("D-08 at 2026-05-18: revenue totals 5322.00 / 5481.00", [ex.revenue_per_assigned_account.by_variant["control"]!.total, ex.revenue_per_assigned_account.by_variant["treatment"]!.total], ["5322.00", "5481.00"]);
  const fin = ds.at(parseTs("2026-08-02T00:00:00Z"), "xv-001", "an-004").metrics.experiment!;
  eq("v1 final run: 63/200 vs 82/200, +9.50 pp, [0.000812, 0.186863], conclusive, 3 prior runs", [fin.primary.variants["control"]!.activated, fin.primary.variants["treatment"]!.activated, fin.primary.absolute_lift_pp, fin.primary.interval!.low, fin.primary.interval!.high, fin.primary.conclusive, fin.run.prior_runs], [63, 82, "9.50", "0.000812", "0.186863", true, 3]);
  const v2 = ds.at(parseTs("2026-10-04T00:00:00Z"), "xv-002", "an-005").metrics.experiment!;
  eq("v2 final run: SRM MISMATCH 25.004329 p 0.000001, 62/92 observed, not conclusive", [v2.srm.verdict, v2.srm.statistic, v2.srm.p_value, v2.srm.observed, v2.primary.conclusive], ["MISMATCH", "25.004329", "0.000001", { control: 62, treatment: 92 }, false]);
}

// the cohort grid by local signup week, over every account (the cohorts page), and the zone conversion
const mondayOf = (_a: string, d: number): number => d - weekdayOf(d);
const weekly = (cut: string): unknown[] => {
  const t = parseTs(cut);
  const ctx = new Ctx(ds.population, t, ds.canonAt(t), null);
  return retentionGrid(ctx, [...ctx.signupAt.keys()], mondayOf).map((r: GridRow) => ({ week: dayIso(r.key), accounts: r.accounts, cells: r.cells }));
};
for (const [cut, w] of Object.entries<any>(ref.weekly_grid)) {
  eq(`weekly retention grid at ${cut}: ${w.weeks} weeks, digest`, [weekly(cut).length, digest(weekly(cut))], [w.weeks, w.digest], true);
  if (w.rows) leaves(`weekly retention grid at ${cut} (complete)`, weekly(cut), w.rows);
}
{
  const t = ds.asOf;
  const ctx = new Ctx(ds.population, t, ds.canonAt(t), null);
  eq("contract grid of the cohort window is part of the as-of digests (shape check)", Object.keys(retentionGridWindow(ctx, ds.windows)).sort(), ["calendar", "cohort_unit", "columns", "rows"]);
}
{
  const acct = new Map(ds.population.accounts.map((a) => [a.account_id, a]));
  const user = new Map(ds.population.users.map((u) => [u.user_id, u]));
  const loc = [...ds.population.sessions].sort((a, b) => (a.session_id < b.session_id ? -1 : 1)).map((s) => [s.session_id, dayIso(localDay(s.started_at, acct.get(user.get(s.user_id)!.account_id)!.timezone))]);
  eq("local calendar date of every session (Intl) = Python zoneinfo", [loc.length, digest(loc)], [ref.session_local_dates.count, ref.session_local_dates.digest]);
  for (const [tz, want] of Object.entries<string>(ref.tz_probe.digests)) {
    const out: string[] = [];
    for (let t = ref.tz_probe.from; t < ref.tz_probe.to; t += ref.tz_probe.step_seconds) out.push(dayIso(localDay(t, tz)));
    eq(`local date every half hour 2026-03-01..2026-11-12 in ${tz} (both DST transitions) = Python`, digest(out), want);
  }
}
if (failures) { console.log(`FAILED (${failures} of ${checks} checks)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks)`);
