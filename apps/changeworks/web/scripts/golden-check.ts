// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) leaf by leaf for the golden fixture and its two variants,
// the golden copy the site serves, the specification's sentences in words, the arithmetic and time primitives (half-open windows, the monthly-rate
// conversion, NPV at several horizons), the generator's twelve defect checks, the replay of its ingest events and the seven designed relationships over
// the snapshot, and the PYTHON domain's results over the published snapshot (scripts/snapshot-reference.json, produced by scripts/make-snapshot-reference.py):
// digests of every metric block at five as-of instants around period boundaries, six half-open windows, a scenario narrowing, the NPV and both paybacks
// at seven horizons, the monthly-rate grid, the portfolio table and the figures of the designed relationships. Prints "ALL OK (N checks)" or exits 1.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { makeDataset, type Dataset } from "../src/data/dataset";
import { buildInputs, isManifest, rawOf } from "../src/data/inputs";
import { GOLDEN_HASH } from "../src/data/load";
import { ENTITIES, type Row } from "../src/domain/contract";
import { Ctx } from "../src/domain/context";
import { compute } from "../src/domain/metrics";
import { cmp, dec, discountFactor, div, ex, fr, m4, monthlyFromAnnual, p6, rnd, sumFr } from "../src/domain/num";
import { goldenOf, runPipeline } from "../src/domain/pipeline";
import { isTs, isoSeconds, isoZ, maturedCount, parseTs, periodStartInstant } from "../src/domain/time";
import { designedClaims, injectionChecks, replayInjections } from "../src/lib/claims";
import { scenarioTotals } from "../src/lib/derive";

const ROOT = new URL("../../", import.meta.url);
const WEB = new URL("../", import.meta.url);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

let failures = 0, checks = 0;
const sortKeys = (_k: string, x: unknown): unknown => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => cmp(a, b))) : typeof x === "bigint" ? x.toString() : x);
const canon = (v: unknown): string => JSON.stringify(v, sortKeys);
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
const pyDumps = (v: unknown): string => JSON.stringify(v, sortKeys).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);

// ---------------------------------------------------------------------------------------------- fixture hashes and the served copy
const FIX = new URL("tests/fixtures/golden/", ROOT);
const hashes = readJson(new URL("HASHES.json", FIX)).sha256 as Record<string, string>;
for (const [f, h] of Object.entries(hashes)) eq(`fixture ${f}: sha-256`, createHash("sha256").update(readFileSync(new URL(f, FIX), "utf8")).digest("hex"), h, true);
console.log(`OK       ${Object.keys(hashes).length} fixture files match HASHES.json`);
eq("the golden copy the site serves (public/golden/inputs.json) is byte-identical to the fixture and carries the hash the site shows", [readFileSync(new URL("public/golden/inputs.json", WEB), "utf8") === readFileSync(new URL("inputs.json", FIX), "utf8"), GOLDEN_HASH], [true, hashes["inputs.json"]]);
eq("public/golden/expected.json is byte-identical to the fixture's", readFileSync(new URL("public/golden/expected.json", WEB), "utf8") === readFileSync(new URL("expected.json", FIX), "utf8"), true);

// ---------------------------------------------------------------------------------------------- golden and its variants
for (const v of ["", "variant-rejected/", "variant-empty/"]) {
  const res = runPipeline(readJson(new URL(`${v}inputs.json`, FIX)));
  leaves(`${v || "golden/"}expected.json`, goldenOf(res), readJson(new URL(`${v}expected.json`, FIX)));
}
const goldInputs = readJson(new URL("inputs.json", FIX));
const gold = makeDataset("golden", { dataset_version: "golden-fixture-v1", dataset_hash: GOLDEN_HASH, generated_at: goldInputs.as_of, as_of: goldInputs.as_of, contract_version: 1, config: {}, row_counts: {} }, goldInputs, readJson(new URL("expected.json", FIX)), null);
leaves("golden dataset object (as the site builds it) = expected.json", gold.goldenShape(), gold.expected);

// the specification's sentences, in words
{
  const m = gold.metrics, b = m.scenarios["scn-001"].initiatives["init-001"], dc = m.scenarios["scn-001"].double_count;
  eq("spec: cost 1000 at t=0, inflows 600 and 600, 10 % annual: NPV = 5000/121 = 41.32 USD, an estimate", [b.npv.exact, b.npv.value, b.npv.label, b.npv.unit], ["5000/121", "41.32", "estimate", "USD"]);
  eq("spec: simple payback 2 (interpolated 1.6667) and discounted payback 2 (interpolated 1.9167), labelled separately", [b.payback.simple, b.payback.discounted], [{ period: 2, interpolated: "1.6667", reason: null }, { period: 2, interpolated: "1.9167", reason: null }]);
  eq("spec: 800 capacity hours are excluded from the cash flow (no conversion); capacity released 400.0000 h per period", [b.excluded_from_cash_flow.capacity_hours_not_converted, b.converted_capacity, b.capacity_released.hours], ["800.00", [], "400.0000"]);
  eq("spec: the double-count residual 75.00 is explained by one shared key, claimed twice in period 2 (counted once at 150.00)", [dc.residual, dc.explanation_required, dc.overlaps.length, dc.overlaps[0].benefit_source_key, dc.overlaps[0].counted_once], ["75.00", true, 1, "cost-line:CC-4410", "150.00"]);
  eq("spec: dependency delays 2 and 3, bound by d-1 and d-2; resource delay 0", [m.initiatives["init-002"].roadmap.dependency_delay, m.initiatives["init-003"].roadmap.dependency_delay, m.initiatives["init-002"].roadmap.binding_dependency_id, m.initiatives["init-003"].roadmap.binding_dependency_id, m.initiatives["init-003"].roadmap.resource_delay], [2, 3, "d-1", "d-2", 0]);
  eq("spec: the ramp is shown beside the unramped plan; avoided cost without a removed budget line stays beside the cash flow", [m.scenarios["scn-001"].initiatives["init-002"].unramped_net_cash_flow, m.scenarios["scn-001"].initiatives["init-002"].excluded_from_cash_flow.avoided_cost_beside_total], [["-500.00", "300.00", "550.00"], "120.00"]);
  eq("spec: observed benefit is labelled 'observed, not attributed' with the trend beside the raw change", [b.benefit_realization.cash.attribution, b.benefit_realization.cash.baseline_trend, b.benefit_realization.cash.observed_above_trend, b.benefit_realization.cash.observed_comparable], ["observed, not attributed", "50.00", "430.00", "480.00"]);
  eq("spec: an observation after the as-of date does not exist yet (ad-3 excluded); training 0.950000 is not adoption 0.750000", [m.initiatives["init-001"].adoption.excluded_after_as_of, m.initiatives["init-001"].training.training_completion, m.initiatives["init-001"].adoption.adoption_rate, m.initiatives["init-001"].training.substituted_for_adoption], [["ad-3"], "0.950000", "0.750000", false]);
  eq("spec: a group with no assessment has a null readiness score, not 0", [m.groups["grp-003"].readiness_score, m.groups["grp-003"].dimensions_assessed], [null, 0]);
}

// ---------------------------------------------------------------------------------------------- NPV at several horizons (golden, hand-worked)
{
  const sc = gold.result.population.acc.scenario_versions[0]!;
  const npvAt = (h: number): string[] => { const p = { config: gold.result.population.config, approvals: [], acc: structuredClone(gold.result.population.acc) }; p.acc.scenario_versions[0]!["horizon_periods"] = h; const b = compute(p, gold.asOf).metrics.scenarios[sc["scenario_id"]].initiatives["init-001"]; return [b.npv.exact, b.npv.value, String(b.payback.simple.period), String(b.payback.discounted.period)]; };
  eq("NPV, horizon 1: only the cost, -1000; no payback", npvAt(1), ["-1000", "-1000.00", "null", "null"]);
  eq("NPV, horizon 2: -1000 + 600/1.1 = -5000/11 = -454.55; simple payback not yet reached", npvAt(2), ["-5000/11", "-454.55", "null", "null"]);
  eq("NPV, horizon 3: 5000/121 = 41.32; both paybacks at period 2", npvAt(3), ["5000/121", "41.32", "2", "2"]);
}

// ---------------------------------------------------------------------------------------------- primitives
{
  eq("rnd: ROUND_HALF_UP, once, at the stated places; never -0.00", [rnd(fr(5, 10_000_000), 6), rnd(fr(-4, 1000), 2), rnd(fr(-5, 1000), 2), rnd(fr(5, 1000), 2), rnd(fr(1, 3), 6), rnd(fr(2, 3), 4), rnd(fr(7, 2), 0), rnd(fr(-1, 2), 0)], ["0.000001", "0.00", "-0.01", "0.01", "0.333333", "0.6667", "4", "-1"]);
  eq("p6 / m4 keep null as null (unknown, never 0)", [p6(null), m4(null)], [null, null]);
  eq("dec is exact and refuses a float", [rnd(dec("0.250000"), 6), ex(dec("-3.5")), (() => { try { dec(0.1 as unknown as string); return "accepted"; } catch { return "refused"; } })()], ["0.250000", "-7/2", "refused"]);
  eq("discount factors are rationals: 1/(1.1)^2 = 100/121; at 0 % every factor is 1", [ex(discountFactor(dec("0.1"), 2)), ex(discountFactor(dec("0"), 7)), p6(discountFactor(dec("0.1"), 2))], ["100/121", "1", "0.826446"]);
  eq("parseTs / isoZ round trip and fractional seconds keep their order", [isoZ(parseTs("2026-10-05T00:00:00Z")), isoZ(parseTs("2026-10-05T00:00:00.5Z")), parseTs("2026-10-05T00:00:00.5Z") < parseTs("2026-10-05T00:00:01Z"), isoSeconds(parseTs("2026-10-05T00:00:00.5Z"))], ["2026-10-05T00:00:00Z", "2026-10-05T00:00:00.5Z", true, "2026-10-05T00:00:00Z"]);
  const bad = ["2026-10-05", "2026-10-05T00:00:00", "2026-02-30T00:00:00Z", "2026-13-01T00:00:00Z", "2026-10-05T24:00:00Z", "2026-10-05T00:00:60Z", "2026-10-05T00:00:00+01:00", 5, null];
  eq("instants without Z, impossible dates and non-text are refused", bad.map((b) => isTs(b)), bad.map(() => false));
  eq("a leap day exists in 2028 and not in 2026", [isTs("2028-02-29T00:00:00Z"), isTs("2026-02-29T00:00:00Z")], [true, false]);
  // half-open: a period is matured when its END is <= as-of; a window includes its start and excludes its end
  const cfg = { period_basis: "monthly", period_start: "2026-01-01" };
  eq("matured: period 2 (March) ends 2026-04-01; one second before, 2 periods; at the instant, 3; one second after, 3", [maturedCount(cfg, parseTs("2026-03-31T23:59:59Z"), 36), maturedCount(cfg, parseTs("2026-04-01T00:00:00Z"), 36), maturedCount(cfg, parseTs("2026-04-01T00:00:01Z"), 36)], [2, 3, 3]);
  eq("a cap stops the count; annual periods step by year; the period start is the half-open start", [maturedCount(cfg, parseTs("2030-01-01T00:00:00Z"), 5), maturedCount({ period_basis: "annual", period_start: "2026-01-01" }, parseTs("2028-01-01T00:00:00Z"), 36), isoZ(periodStartInstant(cfg, 12))], [5, 2, "2027-01-01T00:00:00Z"]);
  const ctx = new Ctx(gold.result.population, gold.asOf, [parseTs("2026-04-01T00:00:00Z"), parseTs("2026-05-01T00:00:00Z")]);
  eq("window [Apr 1, May 1): its start is inside, its end is outside, one microsecond before the end is inside", [ctx.tsInWindow(parseTs("2026-04-01T00:00:00Z")), ctx.tsInWindow(parseTs("2026-05-01T00:00:00Z")), ctx.tsInWindow(parseTs("2026-04-30T23:59:59.999999Z")), ctx.tsInWindow(parseTs("2026-03-31T23:59:59Z"))], [true, false, true, false]);
  eq("the empty window [Apr 1, Apr 1) holds nothing; an open end holds everything after the start", [new Ctx(gold.result.population, gold.asOf, [parseTs("2026-04-01T00:00:00Z"), parseTs("2026-04-01T00:00:00Z")]).tsInWindow(parseTs("2026-04-01T00:00:00Z")), new Ctx(gold.result.population, gold.asOf, [parseTs("2026-04-01T00:00:00Z"), null]).tsInWindow(parseTs("2099-01-01T00:00:00Z"))], [false, true]);
  // the monthly-rate conversion: (1 + r)^(1/12) - 1 to 6 places, exact integer search
  eq("monthly conversion: 8 % -> 0.006434, 12 % -> 0.009489, 10 % -> 0.007974, 0 % -> 0, 100 % -> 0.059463", ["0.08", "0.12", "0.10", "0", "1"].map((r) => rnd(monthlyFromAnnual(dec(r)), 6)), ["0.006434", "0.009489", "0.007974", "0.000000", "0.059463"]);
  eq("monthly conversion is a declared 6-place decimal (an exact rational over 10^6), never an irrational", ex(monthlyFromAnnual(dec("0.08"))), "3217/500000");
}

// ---------------------------------------------------------------------------------------------- the snapshot vs the Python domain
const PUB = new URL("public/data/", WEB);
const manifest = readJson(new URL("manifest.json", PUB));
if (!isManifest(manifest)) throw new Error("manifest.json is not a manifest");
const raw = rawOf(new Map(ENTITIES.map((e) => [e, readJson(new URL(`${e}.json`, PUB))] as const)));
const ds: Dataset = makeDataset("snapshot", manifest, buildInputs(manifest, raw), null, readJson(new URL(manifest.injection_manifest!, PUB)));
const ref = readJson(new URL("scripts/snapshot-reference.json", WEB));
eq("snapshot: dataset_hash, version and as-of equal the Python reference's", [manifest.dataset_hash, manifest.dataset_version, manifest.as_of], [ref.dataset_hash, ref.dataset_version, ref.as_of]);
eq("snapshot: dataset_hash = sha-256 of the 17 entity files (json.dumps sort_keys, compact, entity-name order)", createHash("sha256").update([...ENTITIES].sort().map((e) => pyDumps(raw[e])).join("")).digest("hex"), manifest.dataset_hash);
eq("snapshot: the hash check agrees with Python", ref.dataset_hash_check.sha256_of_17_entity_files, manifest.dataset_hash);
for (const e of ENTITIES) eq(`snapshot ${e}: row count = manifest`, raw[e].length, manifest.row_counts[e], true);
console.log("OK       snapshot row counts match its manifest");
eq("snapshot: ingest counts and rejected count equal Python's (nothing rejected)", [goldenOf(ds.result)["ingest"]["counts"], ds.result.ingest.rejected.length], [ref.ingest_counts, ref.rejected_count]);
eq("snapshot: the manifest's synthetic truth is not in the inputs the domain reads", [JSON.stringify(ds.inputs).includes("true_attributable_share"), Object.keys(ds.inputs).some((k) => k.includes("truth"))], [false, false]);
eq("snapshot: the whole golden-shaped result (ingest and every metric) equals Python's, by digest", digest(ds.goldenShape()), ref.full_digest);

const blocksOf = (m: Row, w: Row[]): Row => ({ digests: { summary: digest(m["summary"]), initiatives: digest(m["initiatives"]), groups: digest(m["groups"]), resources: digest(m["resources"]), scenarios: Object.fromEntries(Object.entries(m["scenarios"] as Row).map(([k, s]) => [k, digest(s)])) },
  warning_codes: [...new Set(w.map((x) => x["code"] as string))].sort(cmp), warning_count: w.length, summary: m["summary"] });
for (const [t, want] of Object.entries<Row>(ref.as_ofs)) {
  const c = compute(ds.result.population, parseTs(t));
  const got = blocksOf(c.metrics, c.warnings);
  eq(`as-of ${t}: ${Object.keys(want["digests"]["scenarios"]).length} scenario digests, summary, initiatives, groups, resources, warnings`, got, { digests: want["digests"], warning_codes: want["warning_codes"], warning_count: want["warning_count"], summary: want["summary"] }, true);
  eq(`as-of ${t}: matured periods`, maturedCount(ds.result.population.config, parseTs(t), 36), want["matured_periods"], true);
  console.log(`OK       as-of ${t}: ${want["matured_periods"]} matured periods; summary, initiatives, groups, resources and ${Object.keys(want["digests"]["scenarios"]).length} scenario blocks equal Python's digests`);
}
for (const w of ref.windows as Row[]) {
  const c = compute(ds.result.population, ds.asOf, [w["from"] ? parseTs(w["from"]) : null, w["to"] ? parseTs(w["to"]) : null]);
  eq(`window [${w["from"]}, ${w["to"]}): every block digest, warnings and summary`, blocksOf(c.metrics, c.warnings), { digests: w["digests"], warning_codes: w["warning_codes"], warning_count: w["warning_count"], summary: w["summary"] }, true);
}
console.log(`OK       ${ref.windows.length} half-open windows (an empty one, an open start, an open end, one starting exactly on a period start) equal Python's`);
{
  const c = compute(ds.result.population, ds.asOf, null, ref.scenario_narrowing.scenario_ids);
  eq("scenario narrowing: the summary follows the first scenario kept", blocksOf(c.metrics, c.warnings), { digests: ref.scenario_narrowing.digests, warning_codes: ref.scenario_narrowing.warning_codes, warning_count: ref.scenario_narrowing.warning_count, summary: ref.scenario_narrowing.summary });
}
for (const [h, want] of Object.entries<Row>(ref.horizons)) {
  const p = { config: ds.result.population.config, approvals: [], acc: structuredClone(ds.result.population.acc) };
  for (const s of p.acc.scenario_versions) s["horizon_periods"] = Number(h);
  const m = compute(p, ds.asOf).metrics;
  const table = Object.fromEntries(Object.entries(m["scenarios"] as Row).map(([sid, s]) => [sid, Object.fromEntries(Object.entries(s["initiatives"] as Row).map(([iid, b]) => [iid, [b["npv"]["exact"], b["payback"]["simple"], b["payback"]["discounted"]]]))]));
  eq(`horizon ${h}: exact NPV and both paybacks of every initiative of every scenario (digest)`, digest(table), want["digest"], true);
  eq(`horizon ${h}: scn-025 exact NPVs and simple paybacks`, [Object.fromEntries(Object.entries(table["scn-025"]).map(([i, r]) => [i, (r as unknown[])[0]])), Object.fromEntries(Object.entries(table["scn-025"]).map(([i, r]) => [i, ((r as Row[])[1] as Row)["period"]]))], [want["scn-025_npv_exact"], want["scn-025_payback_simple"]], true);
}
console.log(`OK       NPV and both paybacks at ${Object.keys(ref.horizons).join(", ")} periods equal Python's`);
for (const [r, mth] of ref.conversion_grid as [string, string][]) eq(`rate grid ${r} -> ${mth}`, rnd(monthlyFromAnnual(dec(r)), 6), mth, true);
console.log(`OK       ${ref.conversion_grid.length} annual rates convert to the same 6-place monthly rate as a 60-digit Decimal calculation`);
for (const [sid, annual, mth] of ref.published_conversions as [string, string, string][]) {
  const sc = ds.byId.scenarios.get(sid)!;
  if (sc["rate_basis"] === "annual") eq(`published conversion of ${sid}: ${annual} annual -> ${mth}`, rnd(monthlyFromAnnual(dec(annual)), 6), mth, true);
}
console.log(`OK       ${ref.published_conversions.length} published monthly conversions (annual-rate scenarios) equal the integer-root conversion`);
{
  const got = Object.fromEntries(scenarioTotals(ds).map((s) => [s.id, { costs: s.costs, cash: s.cash, revenue: s.revenue, avoided: s.avoided, capacity_usd: s.capacityUsd, avoided_beside: s.avoidedBeside, capacity_hours: s.capacityHours,
    listed: { cash: s.listed.cash, revenue: s.listed.revenue, avoided: s.listed.avoided, capacity_usd: s.listed.capacityUsd, avoided_beside: s.listed.avoidedBeside },
    removed: { cash: s.removed.cash, revenue: s.removed.revenue, avoided: s.removed.avoided, capacity_usd: s.removed.capacityUsd, avoided_beside: s.removed.avoidedBeside },
    npv_total: s.npv, npv_sum: s.npvSum, double_counted_pv: s.doubledPv, double_counted_amount: s.doubledAmount, hours_residual: s.hoursResidual,
    residual: s.residual, planned: s.planned, attributable: s.attributable, initiatives: s.initiatives, never_simple: s.neverSimple, never_discounted: s.neverDiscounted }]));
  const want = Object.fromEntries(Object.entries<Row>(ref.portfolio).map(([k, v]) => { const { per_initiative_digest: _d, ...rest } = v; void _d; return [k, rest]; }));
  eq("the portfolio table (costs and each benefit class per scenario as attributable totals, the plain sums and what was taken off them, the attributable NPV and the sum beside it, residuals, paybacks never reached) equals Python's, for all 30 scenarios", got, want);
}
{
  const m = ds.metrics, d = ref.designed;
  const b9 = m.scenarios["scn-025"].initiatives["init-009"];
  eq("DR-01 (Python): init-009 NPV, hours not converted, no payback, released hours", [b9.npv.value, b9.excluded_from_cash_flow.capacity_hours_not_converted, b9.payback.simple.period, b9.capacity_released.hours], [d["DR-01"]["init-009"].npv, d["DR-01"]["init-009"].capacity_hours_not_converted, d["DR-01"]["init-009"].simple_payback, d["DR-01"]["init-009"].released]);
  const dc = m.scenarios["scn-025"].double_count;
  eq("DR-02 (Python): planned, attributable, residual, overlap periods, scenarios with a residual in money and in hours, the attributable NPV, the sum beside it, the present value that counts twice", [dc.planned_benefits, dc.attributable_benefits, dc.residual, dc.overlaps.length, Object.keys(m.scenarios).filter((k) => m.scenarios[k].double_count.residual !== "0.00"), Object.keys(m.scenarios).filter((k) => m.scenarios[k].double_count.hours_residual !== "0.00"), m.scenarios["scn-025"].npv_total.value, m.scenarios["scn-025"].npv_total.sum_of_initiatives, dc.double_counted_pv, dc.hours_residual],
    [d["DR-02"].planned, d["DR-02"].attributable, d["DR-02"].residual, d["DR-02"].overlap_periods, d["DR-02"].scenarios_with_residual, d["DR-02"].scenarios_with_hours_residual, d["DR-02"].npv_attributable, d["DR-02"].npv_sum, d["DR-02"].double_counted_pv, d["DR-02"].hours_residual]);
  eq("DR-03 (Python): init-015 NPV and both paybacks in each of its scenarios", Object.fromEntries(Object.entries(m.scenarios as Row).filter(([, s]) => "init-015" in s.initiatives).map(([sid, s]) => [sid, [s.initiatives["init-015"].npv.value, s.initiatives["init-015"].payback.simple.period, s.initiatives["init-015"].payback.discounted.period]])), d["DR-03"]["init-015"]);
  eq("DR-03 (Python): the benefit-to-cost ratio of init-015 in each of its scenarios, exactly", Object.fromEntries(Object.entries(m.scenarios as Row).filter(([, s]) => "init-015" in s.initiatives).map(([sid, s]) => [sid, ex(div(sumFr((s.initiatives["init-015"].cash_flow as Row[]).map((r) => dec(r["cash_benefits"]))), sumFr((s.initiatives["init-015"].cash_flow as Row[]).map((r) => dec(r["costs"])))))])), d["DR-03"].benefit_to_cost);
  eq("DR-04 (Python): init-003 forecast versions and latest minus original", [m.initiatives["init-003"].forecast.versions.map((v: Row) => [v.version_number, v.total, v.created_at]), m.initiatives["init-003"].forecast.latest_minus_original], [d["DR-04"].versions, d["DR-04"].latest_minus_original]);
  eq("DR-05 (Python): res-03 by period and its overallocated periods", m.resources["res-03"], d["DR-05"]["res-03"]);
  eq("DR-06 (Python): init-008 cash realisation block", m.scenarios["scn-025"].initiatives["init-008"].benefit_realization.cash, d["DR-06"]);
  eq("DR-07 (Python): pooled adoption and training completion", [m.summary.adoption_rate, m.summary.training_completion], [d["DR-07"].adoption, d["DR-07"].training]);
}
console.log("OK       the Python domain's results over the snapshot equal the TypeScript mirror's (5 as-of instants, 6 windows, 7 horizons, the portfolio, the designed figures)");

// the generator's own checks and the manifest's designed relationships, re-derived from the rows
{
  const dr = designedClaims(ds);
  eq(`DR-01..07: ${dr.length} designed-relationship figures of the manifest equal this computation`, dr.filter((c) => !c.ok).map((c) => `${c.id} ${c.label}: want ${c.want} got ${c.got}`), []);
  eq("DR: all seven relationships are represented", [...new Set(dr.map((c) => c.id))], ["DR-01", "DR-02", "DR-03", "DR-04", "DR-05", "DR-06", "DR-07"]);
  const inj = injectionChecks(ds);
  eq(`INJ-01..12: ${inj.length} machine-checkable defect checks of the generator hold in the computed shape`, inj.filter((c) => !c.ok).map((c) => `${c.inj} ${c.path}`), []);
  eq("INJ: twelve defects, one per P09-TEST-01..12", [...new Set(inj.map((c) => c.test))].length, 12);
  const rp = replayInjections(ds);
  eq(`replay: ${rp.steps.length} ingest steps of the injection events give the refusals and acceptances the generator recorded (${rp.commandSteps} command and ${rp.readSteps} read steps belong to the API tests)`, rp.steps.filter((s) => !s.ok).map((s) => `${s.event} ${s.entity} ${s.id}`), []);
  eq("replay: the reasons seen are the contract's", [...new Set(rp.steps.filter((s) => s.got === "rejected").map((s) => String(s.reasonGot)))].sort(cmp), ["ADOPTED_EXCEEDS_ELIGIBLE", "BENEFIT_BEFORE_DEPLOYMENT", "CAPACITY_WITHOUT_CONVERSION", "DEPENDENCY_CYCLE", "ELIGIBILITY_RULE_MISMATCH", "ONE_TIME_COST_REPEATED", "RATE_PERIOD_MISMATCH", "RESOURCE_OVERALLOCATED", "VERSION_EXISTS"]);
  eq("the replay does not change the loaded dataset", [ds.result.population.acc.benefit_items.length, ds.result.population.acc.resource_allocations.length], [700, 557]);
  eq("the golden fixture has no generator claims to check", [designedClaims(gold).length, injectionChecks(gold).length], [0, 0]);
}

if (failures) { console.log(`FAILED (${failures} of ${checks} checks)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks)`);
