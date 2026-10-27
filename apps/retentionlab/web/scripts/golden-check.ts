// Golden check: the TypeScript mirror of the evaluation must reproduce the hand-derived oracle (expected.json) leaf by leaf for the golden fixture
// and its two variants, the same through the code path the browser uses (`?dataset=golden`), the figures the task names in words, the arithmetic and
// time primitives, and the PYTHON domain's results over the published snapshot (scripts/snapshot-reference.json, produced by
// scripts/make-snapshot-reference.py): the 200-account cohort per model, the 1,513-row test table per model and per cutoff, the gaps, the PSI by
// region, every designed-relationship figure. Prints "ALL OK (N checks)" or exits 1.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { buildGolden, buildSnapshot, isManifest, SNAPSHOT_FILES, TEST_MODELS, type Dataset } from "../src/data/dataset";
import { MODELS } from "../src/domain/contract";
import { averagePrecision, calibrationBins, economics, evaluateRanked, psi, rankItems, setMetrics, type Item } from "../src/domain/metrics";
import { canon, cmpId, cmpStr } from "../src/domain/models";
import { div, fr, lnScaled, money, p6, parseFraction, pp2, rnd, scaledToDecimalStr, scaledToString, SCALED_ONE } from "../src/domain/num";
import { canonAscii, evaluate, sha256Hex } from "../src/domain/pipeline";
import { daysFromCivil, hoursBetween, isoZ, parseTs, wholeDays } from "../src/domain/time";
import { designedClaims, injectionChecks, leavesOf, replayRefusals } from "../src/lib/claims";
import { blockOf, DEFAULT_DRIFT_BINS, driftByRegion, DRIFT_FLOOR, DRIFT_THRESHOLD, gapOf, groupGaps, kAt, REFUSAL_K, seriesOf } from "../src/lib/derive";

const ROOT = new URL("../../", import.meta.url);
const WEB = new URL("../", import.meta.url);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

let failures = 0, checks = 0;
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
const sha = (u: URL): string => createHash("sha256").update(readFileSync(u, "utf8")).digest("hex");
const asJson = (v: unknown): unknown => JSON.parse(JSON.stringify(v));

(async () => {
  // ------------------------------------------------------------------------------------------------------------ fixture hashes and the served copy
  const FIX = new URL("tests/fixtures/golden/", ROOT);
  const hashes = readJson(new URL("HASHES.json", FIX)).sha256 as Record<string, string>;
  for (const [f, h] of Object.entries(hashes)) eq(`fixture ${f}: sha-256`, sha(new URL(f, FIX)), h, true);
  console.log(`OK       ${Object.keys(hashes).length} fixture files match HASHES.json`);
  eq("the served golden inputs.json is the fixture's, byte for byte", sha(new URL("public/golden/inputs.json", WEB)), hashes["inputs.json"]);
  eq("the served golden expected.json is the fixture's, byte for byte", sha(new URL("public/golden/expected.json", WEB)), hashes["expected.json"]);

  // ------------------------------------------------------------------------------------------------------------ golden and its variants, leaf by leaf
  const runHashes = async (inputs: any): Promise<Record<string, string>> =>  // eslint-disable-line @typescript-eslint/no-explicit-any
    Object.fromEntries(await Promise.all((inputs.training_runs as any[]).map(async (r) => [r.training_run_id, await sha256Hex(canonAscii(r.config))] as const)));  // eslint-disable-line @typescript-eslint/no-explicit-any
  let total = 0;
  for (const v of ["", "variant-rejected/", "variant-empty/"]) {
    const inputs = readJson(new URL(`${v}inputs.json`, FIX));
    total += leaves(`${v || "golden/"}expected.json`, asJson(evaluate(inputs, await runHashes(inputs)).result), readJson(new URL(`${v}expected.json`, FIX)));
  }
  console.log(`OK       ${total} oracle leaves (the fixture states 912 / 480 / 334)`);
  eq("oracle leaf counts are the fixture's 912 / 480 / 334", total, 912 + 480 + 334);

  // ------------------------------------------------------------------------------------------------------------ the same through the browser's code path
  const goldenText = readFileSync(new URL("public/golden/inputs.json", WEB), "utf8");
  const gold = await buildGolden(goldenText, readJson(new URL("public/golden/expected.json", WEB)));
  leaves("?dataset=golden: the dataset the browser builds equals expected.json", asJson(gold.primary.result), readJson(new URL("expected.json", FIX)));
  eq("golden strip: hash is the SHA-256 of inputs.json", gold.strip.dataset_hash, hashes["inputs.json"]);
  const jan = gold.setAt("2026-01-01T00:00:00Z", undefined, "sc-001");
  eq("golden: precision at K = 2 is 0.500000 (1 hit of 2)", [jan["precision_at_k"].value, jan["precision_at_k"].hits, jan["precision_at_k"].k], ["0.500000", 1, 2]);
  eq("golden: recall at K = 2 is 0.500000 (1 of 2 churners)", [jan["recall_at_k"].value, jan["recall_at_k"].positives], ["0.500000", 2]);
  eq("golden: average precision is 0.833333", jan["average_precision"].value, "0.833333");
  eq("golden: Brier score is 0.192500", jan["brier_score"].value, "0.192500");
  eq("golden: risk lift at K is 1.000000, no tie across rank K", [jan["risk_lift_at_k"].value, jan["risk_lift_at_k"].tie_split_at_k], ["1.000000", false]);
  eq("golden: contact budget 10.00 and expected value 8.45, hypothetical, no treatment effect estimate", [jan["economics"].contact_budget, jan["economics"].expected_value, jan["economics"].label, jan["economics"].treatment_effect_estimate], ["10.00", "8.45", "hypothetical", null]);
  eq("golden: the draft queue is accounts 1 and 2, status draft", [jan["outreach_queue"].account_ids, jan["outreach_queue"].status], [[1, 2], "draft"]);
  eq("golden: an event that occurred before the cutoff and arrived after it is counted, not used (usage 1, support 1)", [jan["late_events"].usage_events, jan["late_events"].support_events, jan["late_events"].total], [1, 1, 2]);
  const feb = gold.setAt("2026-02-01T00:00:00Z");
  eq("golden: the February cohort is censored: 4 eligible, 0 mature, 4 censored, churn rate null (not 0), no AP, no Brier", [feb["population"].eligible, feb["population"].mature, feb["population"].censored, feb["churn_rate"].value, feb["average_precision"].value, feb["brier_score"].value], [4, 0, 4, null, null, null]);
  eq("golden: the incomplete publication is not the freshest (sp-001 completed, 2878 h scoring freshness, 264 h data freshness)", [gold.primary.result["freshness"].latest_completed_publication_id, gold.primary.result["freshness"].scoring_hours, gold.primary.result["freshness"].data_hours], ["sp-001", 2878, 264]);
  eq("golden: the K refusal above the population (K = 5 of 4)", kAt(gold.populations[0]!.models[0]!.items, 5), REFUSAL_K);

  // ------------------------------------------------------------------------------------------------------------ primitives
  eq("rnd: ROUND_HALF_UP away from zero, to 6 places (0.0000005 -> 0.000001, -0.0000005 -> -0.000001)", [rnd(fr(1n, 2000000n), 6), rnd(fr(-1n, 2000000n), 6), rnd(fr(-1n, 4000000n), 6)], ["0.000001", "-0.000001", "0.000000"]);
  eq("pp2: 2 places, sign kept", [pp2(fr(-807n, 10000n)), pp2(fr(1n, 3n))], ["-8.07", "33.33"]);
  eq("money: 2 places, half up; a negative that rounds to zero keeps its sign as Decimal does", [money(fr(1n, 8n)), money(fr(-5n, 1000n)), money(fr(-1n, 1000n))], ["0.13", "-0.01", "-0.00"]);
  eq("parseFraction reads what Python's Fraction reads", [p6(parseFraction("0.25")), p6(parseFraction(" 3/4 ")), p6(parseFraction("1e-3")), p6(parseFraction("-.5"))], ["0.250000", "0.750000", "0.001000", "-0.500000"]);
  for (const bad of ["", "abc", "1/0", "--1", "1.2.3", "0x10"]) { let threw = false; try { parseFraction(bad); } catch { threw = true; } eq(`parseFraction refuses ${JSON.stringify(bad)}`, threw, true, true); }
  const LN2 = "693147180559945309417232121458176568075500134360255254120680009";
  eq("ln(2) to 60 places (deterministic BigInt series)", String(lnScaled(fr(2))).slice(0, 60).padEnd(60, "0"), LN2.slice(0, 60));
  eq("Decimal printing of a quantized term: plain above 1e-6, scientific below, zero as 0E-10", [scaledToDecimalStr(0n, 10), scaledToDecimalStr(SCALED_ONE / 10n ** 10n, 10), scaledToDecimalStr((SCALED_ONE * 12n) / 10n ** 10n, 10), scaledToDecimalStr((SCALED_ONE * 47689783n) / 10n ** 10n, 10), scaledToDecimalStr((SCALED_ONE * 123456n) / 10n ** 10n, 10)], ["0E-10", "1E-10", "1.2E-9", "0.0047689783", "0.0000123456"]);
  eq("ln(1) is exactly 0, ln(1/2) = -ln(2)", [lnScaled(fr(1)), lnScaled(fr(1n, 2n)) + lnScaled(fr(2))], [0n, 0n]);
  eq("ln(3) = 1.098612288668109691395245236922525704647490557822749451734694", scaledToString(lnScaled(fr(3)), 40), "1.0986122886681096913952452369225257046475");
  eq("ln(10) = 2.302585092994045684017991454684364207601101488628772976033327", scaledToString(lnScaled(fr(10)), 40), "2.3025850929940456840179914546843642076011");
  eq("ln(0.0001) = -9.2103403719761827360719658187374568304", scaledToString(lnScaled(fr(1n, 10000n)), 30), "-9.210340371976182736071965818737");
  eq("ln(0.285714...) agrees to 20 places with ln(2/7) = -1.2527629684953679", scaledToString(lnScaled(fr(2n, 7n)), 16), "-1.2527629684953680");
  eq("scaled one is 10^90", SCALED_ONE, 10n ** 90n);
  {
    const r = psi([2, 4, 1], [1, 2, 1], ["0", "1-2", "3+"], "0.000100")!;
    eq("PSI golden bins: 0.074266 and the terms to 10 places", [scaledToString(r.total, 6), r.bins.map((b) => b.term)], ["0.074266", ["0.0047689783", "0.0095379566", r.bins[2]!.term]]);
    const z = psi([2, 4, 1], [0, 3, 1], ["0", "1-2", "3+"], "0.000100")!;
    eq("PSI: a zero proportion is floored to 0.0001 (not renormalised) and flagged", [z.bins[0]!.floored, z.bins[0]!.current_proportion], [true, "0.000000"]);
    eq("PSI: an empty cohort is unknown, not zero", [psi([0, 0], [1, 1], ["a", "b"], "0.000100"), psi([1, 1], [0, 0], ["a", "b"], "0.000100")], [null, null]);
    eq("PSI: identical cohorts give exactly 0.000000", scaledToString(psi([3, 5], [3, 5], ["a", "b"], "0.000100")!.total, 6), "0.000000");
  }
  eq("time: civil days, the epoch and a leap day", [daysFromCivil(1970, 1, 1), daysFromCivil(2024, 3, 1) - daysFromCivil(2024, 2, 1), daysFromCivil(2100, 3, 1) - daysFromCivil(2100, 2, 1)], [0, 29, 28]);
  eq("time: parse and format round-trip, offsets, fractions", [isoZ(parseTs("2026-10-05T00:00:00Z")), isoZ(parseTs("2026-10-05T02:00:00+02:00")), isoZ(parseTs("2026-10-05 00:00:00.5Z")), isoZ(parseTs("2026-10-05T00:00:00.1234567Z"))],
    ["2026-10-05T00:00:00Z", "2026-10-05T00:00:00Z", "2026-10-05T00:00:00.500000Z", "2026-10-05T00:00:00.123456Z"]);
  for (const bad of ["2026-10-05", "2026-10-05T00:00:00", "2026-02-30T00:00:00Z", "2026-13-01T00:00:00Z", "2026-10-05T24:00:00Z", "2026-10-05T00:00:60Z", "garbage"]) { let threw = false; try { parseTs(bad); } catch { threw = true; } eq(`time: ${JSON.stringify(bad)} is refused`, threw, true, true); }
  eq("time: hours are floored, days_since is floored", [hoursBetween(parseTs("2026-10-05T00:00:00Z"), parseTs("2026-10-04T22:09:42Z")), wholeDays(parseTs("2026-01-02T00:00:00Z"), parseTs("2025-12-30T12:00:00Z"))], [1, 2]);
  eq("ordering: code-point order, ids numbers before strings", [cmpStr("rec-Ａ", "rec-\u{1f600}"), cmpId(2, 10), cmpId("a", "b"), cmpId(5, "a")], [-1, -1, -1, -1]);

  // ------------------------------------------------------------------------------------------------------------ the published snapshot
  const PUB = new URL("public/data/", WEB);
  const files = new Map<string, unknown>(SNAPSHOT_FILES.map((n) => [n, readJson(new URL(`${n}.json`, PUB))] as const));
  const manifest = files.get("manifest") as Record<string, any>;  // eslint-disable-line @typescript-eslint/no-explicit-any
  eq("manifest has the fields the site reads", isManifest(manifest), true);
  const ds: Dataset = await buildSnapshot(files);
  eq("the strip shows the manifest's dataset_version, dataset_hash and generated_at", [ds.strip.dataset_version, ds.strip.dataset_hash, ds.strip.generated_at], [manifest.dataset_version, manifest.dataset_hash, manifest.generated_at]);
  eq("the generator's latent propensities are not in the dataset's manifest", "synthetic_truth" in (ds.manifest ?? {}), false);
  const ref = readJson(new URL("scripts/snapshot-reference.json", WEB));
  eq("the reference is for this snapshot (dataset_version and hash)", [ref.dataset_version, ref.dataset_hash], [manifest.dataset_version, manifest.dataset_hash]);

  // the cohort, per model, through the browser's evaluate with the reference's drift scope
  const cohortHashes = await runHashes(ds.inputs);
  const DRIFT = { feature: "usage_events_30d", reference_prediction_at: "2026-02-01T00:00:00Z", bins: DEFAULT_DRIFT_BINS, floor: DRIFT_FLOOR, threshold: DRIFT_THRESHOLD };
  const ats = ds.primary.world.predictionAts();
  eq("cohort: 21 cutoff sets", ats.length, 21);
  for (const m of MODELS) {
    const d = { ...ds.inputs, predictions: ds.inputs["predictions"].filter((p: any) => p.model_name === m), scoring_publications: ds.inputs["scoring_publications"].filter((p: any) => p.model_name === m),  // eslint-disable-line @typescript-eslint/no-explicit-any
      scope: { training_run_id: ds.runId, sets: ats.map((a) => ({ prediction_at: a, scenario_id: null })), drift: DRIFT } };
    const ev = evaluate(d, cohortHashes);
    const r = asJson(ev.result) as Record<string, any>;  // eslint-disable-line @typescript-eslint/no-explicit-any
    const want = ref.cohort[m];
    eq(`cohort ${m}: ingest counts`, r["ingest"].counts, want.ingest);
    eq(`cohort ${m}: rejected records (the four injected censored labels)`, r["ingest"].rejected_records, want.rejected_records);
    eq(`cohort ${m}: consistency block is empty and equals Python's`, r["consistency"], want.consistency);
    eq(`cohort ${m}: split counts`, r["split"][ds.runId].counts, want.split_counts);
    eq(`cohort ${m}: freshness`, r["freshness"], want.freshness);
    eq(`cohort ${m}: publications digest`, digest(r["scoring_publications"]), want.publications);
    eq(`cohort ${m}: publication status by cutoff`, Object.fromEntries(r["scoring_publications"].map((p: any) => [p.prediction_at, [p.eligible, p.scored, p.status]])), want.publication_status);  // eslint-disable-line @typescript-eslint/no-explicit-any
    eq(`cohort ${m}: point-in-time rows digest (${r["point_in_time"].rows.length} rows)`, digest(r["point_in_time"]), want.point_in_time_digest);
    let psiSets = 0;
    for (const [at, s] of Object.entries(r["cutoff_sets"] as Record<string, any>)) {  // eslint-disable-line @typescript-eslint/no-explicit-any
      const w = want.sets[at];
      eq(`cohort ${m} ${at.slice(0, 10)}: complete metric block digest`, digest(s), w.digest, true);
      eq(`cohort ${m} ${at.slice(0, 10)}: summary`, [s.population, s.churn_rate.value, s.average_precision.value, s.brier_score.value, s.average_precision.prevalence, s.average_precision.positives, s.late_events.total, s.feature_missingness.overall.value, s.population_drift.psi, s.population_drift.exceeds_threshold],
        [w.population, w.churn_rate, w.average_precision, w.brier_score, w.prevalence, w.positives, w.late_total, w.missingness_overall, w.psi, w.psi_exceeds], true);
      psiSets++;
    }
    console.log(`OK       cohort ${m}: ${psiSets} cutoff sets, each block's digest and summary equal the Python domain's`);
    // the manifest's own compact claims (the generator ran the same domain)
    const claims = manifest.published_cohort.claims[m];
    for (const [at, c] of Object.entries(claims.cutoff_sets as Record<string, any>)) {  // eslint-disable-line @typescript-eslint/no-explicit-any
      const s = (r["cutoff_sets"] as any)[at];  // eslint-disable-line @typescript-eslint/no-explicit-any
      eq(`manifest claim ${m} ${at.slice(0, 10)}: AP, Brier, churn, eligible, mature, censored, late, missingness`, [s.average_precision.value, s.brier_score.value, s.churn_rate.value, s.population.eligible, s.population.mature, s.population.censored, s.late_events.total, s.feature_missingness.overall.value],
        [c.average_precision, c.brier_score, c.churn_rate, c.eligible, c.mature, c.censored, c.late_events.total, c.missingness_overall], true);
    }
    eq(`manifest claims ${m}: freshness 812 h scoring, 1 h data`, [r["freshness"].scoring_hours, r["freshness"].data_hours], [812, 1]);
  }
  for (const [sid, w] of Object.entries(ref.cohort.scenarios as Record<string, any>)) {  // eslint-disable-line @typescript-eslint/no-explicit-any
    const sm = ds.setAt("2026-09-01T00:00:00Z", "logistic_regression", sid);
    eq(`scenario ${sid} (K ${w.capacity}): economics digest, budget ${w.contact_budget}, expected value ${w.expected_value} (hypothetical)`, [digest(sm["economics"]), sm["economics"].contact_budget, sm["economics"].expected_value, sm["outreach_queue"].account_ids, sm["outreach_queue"].population],
      [w.digest, w.contact_budget, w.expected_value, w.queue, w.population]);
  }
  eq("scenario economics are +21.38, -6.87, -95.46 (contracts.md D-07)", ["sc-001", "sc-002", "sc-003"].map((s) => ds.setAt("2026-09-01T00:00:00Z", "logistic_regression", s)["economics"].expected_value), ["21.38", "-6.87", "-95.46"]);

  // the test table, per population and model
  const rows = ds.testRows!;
  eq("test table: 1,513 mature eligible rows, 189 churners", [rows.length, rows.filter((r) => r.y === 1).length], [1513, 189]);
  let blocks = 0;
  for (const pop of ds.populations) {
    for (const key of TEST_MODELS) {
      const b = blockOf(seriesOf(pop, key), ref.ks, ds.scenarios);
      const w = ref.test_table[pop.id][key];
      eq(`test table ${pop.id} ${key}: n, churners, AP, prevalence, Brier`, [b.n, b.positives, b.average_precision, b.prevalence, b.brier_score], [w.n, w.positives, w.average_precision, w.prevalence, w.brier_score], true);
      eq(`test table ${pop.id} ${key}: ten reliability bins with counts`, b.bins, w.bins, true);
      eq(`test table ${pop.id} ${key}: bins digest`, digest(b.bins), w.bins_digest, true);
      const k = Object.fromEntries(Object.entries(b.k).map(([kk, v]) => [kk, typeof v === "string" ? v : { hits: v.hits, precision: v.precision, recall: v.recall, lift: v.lift, tie_split: v.tie_split }]));
      eq(`test table ${pop.id} ${key}: precision, recall, lift and the tie flag at K = ${ref.ks.join(", ")}`, k, w.k, true);
      eq(`test table ${pop.id} ${key}: contact budget and expected value at the three scenarios`, b.economics, w.economics, true);
      blocks++;
    }
  }
  console.log(`OK       test table: ${blocks} population x model blocks equal the Python domain's (AP, Brier, bins, K metrics, economics)`);
  eq("gaps: overall, by segment (starter -8.07), by region (apac -10.68) equal Python and the published calibration.json", [gapOf(rows), groupGaps(rows, "segment"), groupGaps(rows, "region")], [ref.gaps.overall, ref.gaps.by_segment, ref.gaps.by_region]);
  eq("gaps: equal the published calibration.json", [gapOf(rows), groupGaps(rows, "segment"), groupGaps(rows, "region")], [ds.calibration!["overall"], ds.calibration!["by_segment"], ds.calibration!["by_region"]]);
  const pop0 = ds.populations[0]!;
  eq("reliability curve (Platt) equals the published calibration.json bin by bin: counts, mean predicted, observed, gap", blockOf(seriesOf(pop0, "logistic_calibrated")).bins, ds.calibration!["reliability_calibrated"]);
  eq("reliability curve (before Platt) equals the published calibration.json", blockOf(seriesOf(pop0, "logistic_uncalibrated")).bins, ds.calibration!["reliability_uncalibrated"]);
  const drift = driftByRegion(rows, 4);
  const cuts: string[] = (files.get("test_cohort") as any).head.cutoffs;  // eslint-disable-line @typescript-eslint/no-explicit-any
  cuts.forEach((c, i) => {
    const w = ref.psi_by_region[c];
    for (const g of ["all_accounts", "apac", "other_regions"] as const) {
      const d = drift[i]![g];
      eq(`PSI ${c.slice(0, 10)} ${g}: psi, exceeds, rows, terms equal Python`, [d.psi, d.exceeds, d.reference_rows, d.current_rows, d.bins.map((b) => [b.label, b.term, b.floored])], [w[g].psi, w[g].exceeds, w[g].reference_rows, w[g].current_rows, w[g].bins.map((b: any) => [b.label, b.term, b.floored])], true);  // eslint-disable-line @typescript-eslint/no-explicit-any
      const pub = (ds.aggregates!["drift"].by_cutoff as any[]).find((x) => x.prediction_at === c)[g];  // eslint-disable-line @typescript-eslint/no-explicit-any
      eq(`PSI ${c.slice(0, 10)} ${g}: equals the published series (6 places, from the Python Decimal.ln)`, [d.psi, d.exceeds, d.current_rows], [pub.psi, pub.exceeds_threshold, pub.current_rows], true);
    }
  });
  console.log("OK       PSI by region for the four test cutoffs equals Python and the published aggregates");
  eq("DR-03: apac exceeds 0.2 from 2026-05-01 while the whole population stays below it", [drift[3]!.apac.exceeds, drift[3]!.all_accounts.exceeds, drift[3]!.apac.psi, drift[3]!.all_accounts.psi], [true, false, "0.513545", "0.017043"]);

  // per-cutoff aggregates of the full world, the four test cutoffs, three models
  const aggs = ds.aggregates!["cutoffs"] as any[];  // eslint-disable-line @typescript-eslint/no-explicit-any
  for (let i = 0; i < 4; i++) {
    const a = aggs.find((c) => c.prediction_at === cuts[i])!;
    for (const [m, key] of [["random_baseline", "random_baseline"], ["business_rule", "business_rule"], ["logistic_regression", "logistic_calibrated"]] as const) {
      const sub = ds.populations[i + 1]!;
      const items = seriesOf(sub, key);
      const b = blockOf(items);
      const mean = items.length ? p6(div(items.reduce((s, x) => ({ n: s.n * x.p.d + x.p.n * s.d, d: s.d * x.p.d }), fr(0)), fr(items.length))) : null;
      void mean;
      const w = a.models[m];
      eq(`aggregates ${cuts[i]!.slice(0, 10)} ${m}: n, churners, prevalence, AP, Brier equal the full-world per-cutoff figures`, [b.n, b.positives, b.prevalence, b.average_precision, b.brier_score], [w.n, w.positives, w.prevalence, w.average_precision, w.brier_score], true);
    }
  }
  console.log("OK       per-cutoff AP and Brier of the test range equal cutoff_aggregates.json");
  const split = ds.splitSummary!;
  eq("split: the cohort counts of the run equal split_summary.json", ds.primary.result["split"][ds.runId].counts, split["published_cohort"]);
  eq("split: the embargo is horizon + grace = 104 days", ds.primary.result["split"][ds.runId].embargo_days, split["embargo_days"]);

  // designed relationships: every figure of the manifest
  const refLeaves = ref.designed.leaves as Record<string, Record<string, unknown>>;
  let nLeaves = 0;
  for (const d of manifest.designed_relationships as any[]) {  // eslint-disable-line @typescript-eslint/no-explicit-any
    const mine = Object.fromEntries(leavesOf(d.realised).map(([p, v]) => [`.${p}`, v]));
    nLeaves += Object.keys(mine).length;
    eq(`${d.id}: every figure of the manifest is in the Python reference (${Object.keys(mine).length} leaves)`, mine, refLeaves[d.id], true);
    eq(`${d.id}: the manifest says met`, d.met, true, true);
  }
  const dr = designedClaims(ds);
  eq(`DR-01..05: ${dr.length} figures (${dr.filter((c) => c.recomputed).length} recomputed here, ${dr.filter((c) => !c.recomputed).length} shown as published) equal the manifest`, dr.filter((c) => !c.ok).map((c) => `${c.id} ${c.label}: want ${c.want} got ${c.got}`), []);
  eq("DR: all five relationships are represented", [...new Set(dr.map((c) => c.id))], ["DR-01", "DR-02", "DR-03", "DR-04", "DR-05"]);
  console.log(`OK       ${nLeaves} designed-relationship leaves in the manifest equal the reference`);
  const lr = blockOf(seriesOf(pop0, "logistic_calibrated")), ru = blockOf(seriesOf(pop0, "business_rule")), ra = blockOf(seriesOf(pop0, "random_baseline"));
  eq("DR-01: per-model AP and Brier on the 1,513 test rows (logistic 0.238552 / 0.105019, rule 0.136653 / 0.109255, random 0.126793 / 0.326543)", [lr.average_precision, lr.brier_score, ru.average_precision, ru.brier_score, ra.average_precision, ra.brier_score],
    ["0.238552", "0.105019", "0.136653", "0.109255", "0.126793", "0.326543"]);

  // the injected defects
  const ic = injectionChecks(ds);
  eq(`INJ: ${ic.length} declared checks over twelve defects equal the facts the manifest recorded`, ic.filter((c) => !c.ok).map((c) => `${c.inj} ${c.path}`), []);
  eq("INJ: twelve defects, one per P10-TEST-01..12", [...new Set(ic.map((c) => c.test))].length, 12);
  const rp = replayRefusals(ds);
  eq(`INJ: ${rp.length} recorded replay requests re-run in the browser return the code the API returned`, rp.filter((c) => !c.ok).map((c) => `${c.event} ${c.command} want ${c.expected} got ${c.got}`), []);

  // ------------------------------------------------------------------------------------------------------------ K, ties, empty bins on the real table
  const n = rows.length;
  const lrItems = seriesOf(pop0, "logistic_calibrated"), ruItems = seriesOf(pop0, "business_rule");
  eq("K above the population is refused (1514 of 1513), K = 0 and K = 1.5 as well", [kAt(lrItems, n + 1), kAt(lrItems, 0), kAt(lrItems, 1.5)], [REFUSAL_K, REFUSAL_K, REFUSAL_K]);
  const full = kAt(lrItems, n) as Exclude<ReturnType<typeof kAt>, string>;
  eq("K = the whole population: precision is the prevalence, recall 1.000000, lift 1.000000", [full.precision, full.recall, full.lift], ["0.124917", "1.000000", "1.000000"]);
  const k1 = kAt(ruItems, 1) as Exclude<ReturnType<typeof kAt>, string>;
  eq("ties: the rule gives one probability to many rows, so K = 1 splits a tie and the flag says so", k1.tie_split, true);
  const topP = ruItems[0]!.p;
  const tied = rows.filter((r) => parseFraction(r.p.business_rule).n * topP.d === topP.n * parseFraction(r.p.business_rule).d);
  const minAcct = Math.min(...tied.map((r) => r.account_id));
  eq("ties: the first rank goes to the smallest account id among the tied rows (then the earlier cutoff)", ruItems[0]!.account_id, minAcct);
  const reversed = [...ruItems].sort((a, b) => (b.p.n * a.p.d < a.p.n * b.p.d ? -1 : b.p.n * a.p.d > a.p.n * b.p.d ? 1 : cmpId(b.account_id, a.account_id)));
  eq("ties: average precision does not depend on how account ids break a tie (scikit-learn thresholds)", [averagePrecision(reversed, 189, false).total, averagePrecision(ruItems, 189, false).total], [averagePrecision(ruItems, 189, false).total, averagePrecision(ruItems, 189, false).total]);
  eq("ties: precision at K does depend on the documented tie rule (K = 1: ascending account id gives a different first row than descending)", [reversed[0]!.account_id !== ruItems[0]!.account_id], [true]);
  const empty = blockOf(lrItems).bins.filter((b) => b.count === 0);
  eq("empty bins: six of ten bins have no rows and every figure of theirs is null, never 0", [empty.length, empty.every((b) => b.mean_predicted === null && b.observed_rate === null && b.gap_pp === null)], [6, true]);
  eq("empty bins: counts sum to the population", blockOf(lrItems).bins.reduce((s, b) => s + b.count, 0), n);
  eq("an empty population evaluates to nulls, not zeros, and K is not refused", (() => { const e = evaluateRanked([], 3); return [e.average_precision.value, e.brier_score.value, e.precision_at_k, e.kOk]; })(), [null, null, null, false]);
  eq("zero churners: AP, recall and lift are null, precision at K is 0.000000", (() => { const it: Item[] = [{ p: fr(1n, 2n), pstr: "0.500000", y: false, account_id: 1, cutoff_id: "a" }, { p: fr(1n, 4n), pstr: "0.250000", y: false, account_id: 2, cutoff_id: "b" }]; const e = evaluateRanked(it, 1); return [e.average_precision.value, e.precision_at_k!["value"], e.recall_at_k!["value"], e.risk_lift_at_k!["value"]]; })(), [null, "0.000000", null, null]);
  eq("calibration bin edges: p = 1 is in the last bin, p = 0.1 in the second", (() => { const mk = (s: string): Item => ({ p: parseFraction(s), pstr: s, y: false, account_id: 1, cutoff_id: s }); const b = calibrationBins([mk("1.000000"), mk("0.100000"), mk("0.099999"), mk("0.000000")]); return [b[9]!.count, b[1]!.count, b[0]!.count]; })(), [1, 1, 2]);
  eq("ranking: probability descending, account ascending", rankItems([2, 1, 3].map((a, i): Item => ({ p: fr(i === 2 ? 1n : 1n, 2n), pstr: "0.5", y: false, account_id: a, cutoff_id: String(a) }))).map((x) => x.account_id), [1, 2, 3]);
  eq("economics: one rounding at the total (three terms of 0.0049 each rounds once)", economics({ scenario_id: "x", contact_cost: "0.00", assumed_effect: "0.100000", margin_value: "0.49" }, [{ pstr: "0.100000", account_id: 1 }, { pstr: "0.100000", account_id: 2 }, { pstr: "0.100000", account_id: 3 }]).expected_value, "0.01");
  eq("setMetrics on the golden world refuses K above the evaluated population without throwing", (() => { const g = gold.primary.world; const s = { ...Object.fromEntries(g.scenarios) }; void s; return setMetrics(g, gold.runId, "2026-01-01T00:00:00Z", null, null)["capacity"]; })(), null);

  // ------------------------------------------------------------------------------------------------------------ static guards on the sources
  const walk = (dir: URL, out: string[] = []): string[] => { for (const f of readdirSync(dir)) { const u = new URL(f, dir); if (statSync(u).isDirectory()) walk(new URL(`${f}/`, dir), out); else out.push(u.pathname); } return out; };
  const src = walk(new URL("src/", WEB));
  const text = (p: string): string => readFileSync(new URL(`file://${p}`), "utf8");
  const bad: string[] = [];
  for (const p of src) {
    const t = text(p).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    if (/\bMath\.(log|exp|pow|sqrt)\b/.test(t) && !p.endsWith("/components/charts.tsx")) bad.push(`${p}: Math function outside the chart geometry`);
    if (/parseFloat|toPrecision/.test(t)) bad.push(`${p}: float parse`);
    if (/toFixed/.test(t) && !p.endsWith("/components/charts.tsx")) bad.push(`${p}: toFixed outside the chart geometry`);
    if (/synthetic_truth|latent_churn_propensity_ppm/.test(t) && !p.endsWith("/data/dataset.ts")) bad.push(`${p}: reads the generator's synthetic truth`);
    if (/localStorage|sessionStorage|indexedDB|document\.cookie/.test(t)) bad.push(`${p}: browser storage`);
  }
  eq(`sources (${src.length} files): no float function in a figure, toFixed only in chart geometry, synthetic truth read only by the loader, no browser storage`, bad, []);
  eq("the generator's latent reference is carried to the evidence page only as a disclosure object", Object.keys(ds.disclosure ?? {}).sort(), ["hidden_risk_accounts", "latent_reference_test", "note", "roles", "unobserved_designs"]);
  eq("the web directory has no dependency beyond react", Object.keys(readJson(new URL("package.json", WEB)).dependencies), ["react", "react-dom"]);
  void existsSync;

  if (failures) { console.log(`FAILED (${failures} of ${checks} checks)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks)`);
})();
