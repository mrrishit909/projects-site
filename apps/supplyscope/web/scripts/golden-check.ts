// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) and the two variants key by
// key, then run the full published snapshot under a time budget and confirm the injected defects are caught.
import { readFileSync } from "node:fs";
import { buildInputs, isManifest, listedFiles } from "../src/data/inputs";
import { ENTITIES, EXTRA_ENTITIES, METRIC_KEYS } from "../src/domain/contract";
import { comparePolicies, commonSample } from "../src/domain/demand";
import { DomainError } from "../src/domain/errors";
import { datasetEnd, forecastDemand, maeOf, wapeOf } from "../src/domain/forecast";
import { parseMoney, roundHalfUp, d6, ratio } from "../src/domain/money";
import { computeMetrics, groupMetrics, pairSeries, reorderRows, supplementary } from "../src/domain/metrics";
import { runPipeline } from "../src/domain/pipeline";
import { arrivalDay, safetyStock, zValue } from "../src/domain/replenishment";
import { onTimeRate } from "../src/domain/suppliers";
import { dayEnd, parseDay, parseTs } from "../src/domain/time";
import type { PipelineInputs, Population } from "../src/domain/types";
import { manifestAsOf } from "../src/data/inputs";
import { createSimulation } from "../src/state/simulation";

const GOLDEN = new URL("../../tests/fixtures/golden/", import.meta.url);
const DATA = new URL("../public/data/", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

let failures = 0;
let checks = 0;
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) =>
  x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : typeof x === "bigint" ? x.toString() : x);
function expectEq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got)} want ${canon(want)}`); }
}
function expectTrue(label: string, cond: boolean, detail = ""): void {
  checks++;
  if (cond) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label} ${detail}`); }
}
const last = <T,>(xs: readonly T[]): T | undefined => xs[xs.length - 1];
const byKey = (a: { entity: string; id: string }, b: { entity: string; id: string }): number =>
  a.entity < b.entity ? -1 : a.entity > b.entity ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;

function checkFixture(name: string, inputs: PipelineInputs, expected: any): void {
  const states = Object.keys(expected.states);
  for (const state of states) {
    const want = expected.states[state];
    const r = runPipeline(inputs, state);
    const tag = `${name}/${state}`;
    for (const key of METRIC_KEYS) expectEq(`${tag} metric ${key}`, (r.metrics as any)[key], want.metrics[key]);
    expectEq(`${tag} metric key set`, Object.keys(r.metrics).sort(), Object.keys(want.metrics).sort());
    expectEq(`${tag} metric key order is the contract order`, Object.keys(r.metrics), [...METRIC_KEYS]);
    if (state === states[0]) {
      expectEq(`${name} ingest counts`, r.ingest.counts, expected.ingest.counts);
      const wantRej = [...expected.ingest.rejected_records].sort(byKey);
      expectEq(`${name} rejected records (entity, id, reason)`, r.rejected.map((x) => [x.entity, x.id, x.reason_code]), wantRej.map((x: any) => [x.entity, x.id, x.reason_code]));
      expectEq(`${name} rejected raw rows preserved`, r.rejected.map((x) => x.raw_row), wantRej.map((x: any) => x.raw_row));
      expectEq(`${name} rejected status`, r.rejected.map((x) => x.status), wantRej.map(() => "rejected"));
    }
  }
}

for (const [name, dir] of [["golden", ""], ["variant-rejected", "variant-rejected/"], ["variant-empty", "variant-empty/"]] as const) {
  checkFixture(name, readJson(new URL(`${dir}inputs.json`, GOLDEN)), readJson(new URL(`${dir}expected.json`, GOLDEN)));
}

// ---- the spec sentences in words (P03-GOLD-01), pair rows and the trajectory ----------------------------------
{
  const inputs = readJson(new URL("inputs.json", GOLDEN)) as PipelineInputs;
  const g = runPipeline(inputs, "golden"), p80 = runPipeline(inputs, "position_80");
  expectEq("P03-GOLD-01 on hand 40, on order 30, backorders 10 -> position 60", [g.metrics.on_hand, g.metrics.on_order, g.metrics.backorders, g.metrics.inventory_position], [40, 30, 10, 60]);
  expectEq("P03-GOLD-01 ROP 70, target 120 -> raw 60; MOQ 50, pack 24 -> 72", [g.metrics.reorder_point, g.metrics.target_position, g.metrics.raw_order, g.metrics.order_after_moq, g.metrics.order_quantity], [70, 120, 60, 60, 72]);
  expectEq("P03-GOLD-01 position 80 -> no order", [p80.metrics.inventory_position, p80.metrics.reorder_triggered, p80.metrics.order_quantity], [80, false, 0]);
  const rows = reorderRows(g.population, g.asOf, null);
  expectEq("golden pair row draft", rows.map((r) => [r.product_id, r.location_id, r.position, r.raw_order, r.order_after_moq, r.order_quantity, r.triggered, r.status]), [["prod-001", "loc-001", 60, 60, 60, 72, true, "draft"]]);
  const rows80 = reorderRows(p80.population, p80.asOf, inputs.states!["position_80"]!);
  expectEq("position_80 pair row", rows80.map((r) => [r.position, r.order_quantity, r.triggered]), [[80, 0, false]]);
  const s = pairSeries(g.population, "prod-001", "loc-001", parseDay("2026-03-01"), parseDay("2026-03-31"));
  expectEq("trajectory last day equals the figures (on hand, on order, backorders, position)", [last(s.on_hand), last(s.on_order), last(s.backorders), last(s.position)], [40, 30, 10, 60]);
  expectEq("trajectory on hand 03-11 is 0, 03-12 is 0, 03-16 is 40", [s.on_hand[10], s.on_hand[11], s.on_hand[15]], [0, 0, 40]);
  expectEq("trajectory stockout days (backorder opened 03-12)", s.stockout_days, [parseDay("2026-03-12")]);
  const s80 = pairSeries(p80.population, "prod-001", "loc-001", parseDay("2026-03-01"), parseDay("2026-03-31"), inputs.states!["position_80"]!);
  expectEq("position_80 trajectory ends at position 80", last(s80.position), 80);
  expectEq("working capital 500.00; D-05 turnover = annualised COGS (95 x 12.50 x 365 / 31 = 13981.85) / daily average value (439.52); equals the Python reference", [g.metrics.working_capital, supplementary(g.population, g.asOf, g.window)], ["500.00", { average_inventory_value: "439.52", annualised_cogs: "13981.85", inventory_turnover: "31.811927" }]);
}

// ---- helpers: fixed-point, calendar, safety stock --------------------------------------------------------------
{
  expectEq("1/31 rounds half-up to 0.032258", d6(ratio(1, 31)), "0.032258");
  expectEq("d6 of 0 denominators is null", d6(ratio(5, 0)), null);
  expectEq("roundHalfUp 5/2 = 3, -5/2 = -3", [roundHalfUp(5n, 2n), roundHalfUp(-5n, 2n)], [3n, -3n]);
  expectEq("parseMoney canonicalises 12.5 -> 12.50", parseMoney("12.5"), "12.50");
  let threw = false;
  try { parseMoney("12.505"); } catch { threw = true; }
  expectTrue("parseMoney refuses a third decimal", threw);
  expectEq("z(0.95) is 1.644854", zValue("0.95"), 1644854n);
  let code = "";
  try { zValue("0.5"); } catch (e) { code = e instanceof DomainError ? e.code : "other"; }
  expectEq("z(0.5) is UNSUPPORTED_SERVICE_TARGET", code, "UNSUPPORTED_SERVICE_TARGET");
  // ceil(1.644854 * sqrt(4 * 9)) = ceil(9.869124) = 10; exact boundary: z=1.000000-like check via variance 1/1, lead 1
  expectEq("safety stock ceil(1.644854 * sqrt(4 * 9)) = 10", safetyStock(1644854n, ratio(4, 1), 9), 10);
  expectEq("safety stock 0 for no variance", safetyStock(1644854n, null, 9), 0);
  const closures = [{ closure_id: "c", calendar_id: "cal-02", closed_from: "2026-01-05", closed_to: "2026-01-18" }];
  expectEq("12 lead days from 2025-12-24 on cal-02 land on 2026-01-19 (INJ-04)", arrivalDay(parseDay("2025-12-24"), 12, closures, "cal-02"), parseDay("2026-01-19"));
  expectEq("the same without the closure lands on 2026-01-05", arrivalDay(parseDay("2025-12-24"), 12, [], "cal-02"), parseDay("2026-01-05"));
}

// ---- published snapshot: row counts, injected defects, time budget -----------------------------------------------
{
  const manifest = readJson(new URL("manifest.json", DATA));
  expectTrue("manifest has the required fields", isManifest(manifest));
  const files = new Map<string, unknown>();
  for (const n of listedFiles(manifest)) files.set(n, readJson(new URL(`${n}.json`, DATA)));
  for (const e of [...ENTITIES, ...EXTRA_ENTITIES]) expectEq(`snapshot row count ${e}`, (files.get(e) as any).rows.length, manifest.row_counts[e]);
  const inputs = buildInputs(manifest, files);
  const t0 = performance.now();
  const full = runPipeline(inputs, null);
  const ms = performance.now() - t0;
  console.log(`TIMING   runPipeline(snapshot) ${ms.toFixed(0)} ms over ${manifest.row_counts.sales} sales, ${manifest.row_counts.inventory_movements} movements`);
  expectTrue("snapshot pipeline under 3000 ms", ms < 3000, `(${ms.toFixed(0)} ms)`);
  expectEq("snapshot pipeline completes with a non-empty population", full.metrics.empty_population, false);

  const inj = readJson(new URL("injection-manifest.json", DATA)).injections as { id: string; record_ids: string[] }[];
  const find = (id: string) => inj.find((i) => i.id === id)!;
  expectEq("INJ-01 rejected movements = the three exact replays (DUPLICATE_MOVEMENT_ID)", full.rejected.filter((r) => r.entity === "inventory_movements").map((r) => [r.id, r.reason_code]).sort(),
    find("INJ-01").record_ids.map((id) => [id, "DUPLICATE_MOVEMENT_ID"]).sort());
  expectEq("INJ-02 rejected receipts = the pre-order receipt (RECEIPT_BEFORE_ORDER)", full.rejected.filter((r) => r.entity === "receipts").map((r) => [r.id, r.reason_code]),
    find("INJ-02").record_ids.map((id) => [id, "RECEIPT_BEFORE_ORDER"]));
  expectEq("rejected ids = INJ-01 + INJ-02 and nothing else", full.rejected.map((r) => r.id).sort(), [...find("INJ-01").record_ids, ...find("INJ-02").record_ids].sort());
  for (const e of [...ENTITIES, ...EXTRA_ENTITIES]) {
    const c = (full.ingest.counts as any)[e] ?? (full.ingest.extraCounts as any)[e];
    if (c.accepted + c.rejected !== manifest.row_counts[e]) { failures++; console.log(`MISMATCH accepted + rejected ${e}`); }
  }
  expectEq("accepted + rejected movements = published movements", full.ingest.counts.inventory_movements.accepted + full.ingest.counts.inventory_movements.rejected, manifest.row_counts.inventory_movements);
  expectEq("no NEGATIVE_STOCK flag in the published ledger", full.flags.length, 0);

  // the sum of the draft rows equals the overall metrics; groups sum to the whole
  const rows = reorderRows(full.population, full.asOf);
  expectEq("60 draft rows, one per parameter row", rows.length, manifest.row_counts.replenishment_params);
  expectEq("sum of draft quantities equals metrics.order_quantity", rows.reduce((a, r) => a + r.order_quantity, 0), full.metrics.order_quantity);
  expectEq("triggered rows agree with metrics.reorder_triggered", rows.some((r) => r.triggered), full.metrics.reorder_triggered);
  expectTrue("every draft row is a draft", rows.every((r) => r.status === "draft"));
  for (const key of ["location", "supplier", "product"] as const) {
    const groups = groupMetrics(full.population, key, full.asOf, full.window);
    const sum = (f: (m: any) => number): number => [...groups.values()].reduce((a, m) => a + f(m), 0);
    expectEq(`groups by ${key} sum on_hand to the whole`, sum((m) => m.on_hand), full.metrics.on_hand);
    expectEq(`groups by ${key} sum requested units to the whole`, sum((m) => m.requested_units), full.metrics.requested_units);
  }
  for (const r of [rows[0]!, rows[17]!, rows[41]!]) {
    const m = computeMetrics(full.population, full.asOf, full.window, null, { products: new Set([r.product_id]), locations: new Set([r.location_id]) });
    expectEq(`pair ${r.product_id}/${r.location_id} figures = draft row`, [m.on_hand, m.on_order, m.backorders, m.inventory_position, m.order_quantity], [r.on_hand, r.on_order, r.backorders, r.position, r.order_quantity]);
    const s = pairSeries(full.population, r.product_id, r.location_id, parseDay("2025-04-01"), parseDay("2026-09-30"));
    expectEq(`pair ${r.product_id}/${r.location_id} trajectory ends at the figures`, [last(s.on_hand), last(s.on_order), last(s.backorders), last(s.position)], [r.on_hand, r.on_order, r.backorders, r.position]);
  }
  const overall = supplementary(full.population, full.asOf, full.window);
  expectTrue("turnover and average inventory value are computed", overall.inventory_turnover !== null && overall.average_inventory_value !== null);

  // suppliers: the designed late-receipt rates (INJ designed relationship: sup-03 late on 31.9% of 254)
  const pop = full.population as Population;
  const s3 = onTimeRate(pop.purchase_orders, pop.purchase_order_lines, pop.receipts, pop.suppliers, pop.calendar_closures, full.asOf, "sup-03");
  expectEq("sup-03 eligible receipts = 254", s3.eligible_receipts, 254);
  expectEq("sup-03 late share rounds to 31.9%", ((s3.late_receipts.length / s3.eligible_receipts) * 100).toFixed(1), "31.9");
  expectEq("the two partially received closed lines are open", s3.partially_received_open_lines.filter((l) => ["pol-00795", "pol-00840"].includes(l)).sort(), ["pol-00795", "pol-00840"]);

  // forecast: every pair at the last published cutoff, exact; an intermittent SKU shows zero-demand folds and null WAPE
  const cutoff = parseTs("2026-09-16T23:59:59Z");
  const end = datasetEnd(pop.sales, pop.inventory_movements, pop.receipts);
  const t1 = performance.now();
  const results = pop.replenishment_params.map((p) => forecastDemand(pop.sales, pop.promotions, p.product_id, p.location_id, cutoff, 14, end));
  console.log(`TIMING   forecastDemand x${results.length} (exact decimals) ${(performance.now() - t1).toFixed(0)} ms`);
  expectEq("60 forecasts computed with baselines", results.filter((r) => r.evals.naive.folds > 0 && r.evals.seasonal_naive.folds === r.evals.naive.folds).length, 60);
  const intermittent = find("INJ-05").record_ids[0]!;
  const fr = results.find((r) => r.product_id === intermittent)!;
  expectTrue(`intermittent ${intermittent} has zero-demand folds`, fr.evals.ewma.zero_demand_folds > 0);
  expectTrue(`intermittent ${intermittent}: a zero-demand fold has null WAPE and a defined MAE`, fr.evals.naive.fold_scores.some((f) => f.actual === 0 && f.wape === null && f.mae.num >= 0n));
  expectTrue("a series with demand has a WAPE", results.some((r) => wapeOf(r.evals.naive) !== null && maeOf(r.evals.naive) !== null));
  let future = "";
  try { forecastDemand(pop.sales, pop.promotions, "prod-001", "loc-01", parseTs("2030-01-01T00:00:00Z"), 14, end); } catch (e) { future = e instanceof DomainError ? e.code : "other"; }
  expectEq("a cutoff after the data is FORECAST_CUTOFF_IN_FUTURE", future, "FORECAST_CUTOFF_IN_FUTURE");

  // the browser simulation: same seed, same sample; reset restores the published population
  const a = commonSample(20261026, 30, 4, 3, 7), b = commonSample(20261026, 30, 4, 3, 7);
  expectEq("common random numbers: same seed, same sample", a, b);
  let mismatch = "";
  try { comparePolicies([{ ...pop.policy_scenarios[0]! }, { ...pop.policy_scenarios[1]!, seed: 1 }], 10, 3, 2, 4, 5, 20, 6, 6, 10); } catch (e) { mismatch = e instanceof DomainError ? e.code : "other"; }
  expectEq("policies with different seeds are refused (POLICY_SEED_MISMATCH)", mismatch, "POLICY_SEED_MISMATCH");
  const sim = createSimulation(pop, manifestAsOf(manifest));
  const first = sim.run("prod-001", "loc-01", { reorderPoint: 48, target: 144, days: 90 });
  const again = sim.run("prod-001", "loc-01", { reorderPoint: 48, target: 144, days: 90 });
  expectEq("simulation: the published seed gives the same result twice", canon(first.results), canon(again.results));
  sim.reset();
  expectEq("simulation: reset() clears the run and the log", [sim.getState().last, sim.getState().log.length], [null, 0]);
  expectEq("simulation never touches the population (position unchanged)", computeMetrics(pop, full.asOf, full.window).inventory_position, full.metrics.inventory_position);
  expectEq("day end helper is 23:59:59", dayEnd(parseDay("2026-09-30")), full.asOf);
}

console.log(failures === 0 ? `ALL OK (${checks} checks)` : `${failures} MISMATCH of ${checks} checks`);
process.exitCode = failures === 0 ? 0 : 1;
