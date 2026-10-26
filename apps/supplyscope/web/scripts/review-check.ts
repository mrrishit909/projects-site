// Regression checks for the master-18 reviewer findings R3-01..R3-07 and the worker findings S-02 / S-03 (TypeScript mirror of
// tests/test_review_findings.py: the same cases, the same expected values). Run by `npm run check` after the golden check.
import { readFileSync } from "node:fs";
import { EXTRA_METRIC_KEYS, METRIC_KEYS } from "../src/domain/contract";
import { decToRat } from "../src/domain/money";
import { promoFactor } from "../src/domain/forecast";
import { availabilityFlags, computeMetricsFull, groupMetrics, scoped } from "../src/domain/metrics";
import { runPipeline } from "../src/domain/pipeline";
import { isoZ, parseDay, parseTs } from "../src/domain/time";
import type { PipelineInputs, Promotion } from "../src/domain/types";

const GOLDEN = new URL("../../tests/fixtures/golden/inputs.json", import.meta.url);
const golden = (): PipelineInputs => { const g = JSON.parse(readFileSync(GOLDEN, "utf8")); delete g.states; return g; };

let failures = 0;
let checks = 0;
function expectEq(label: string, got: unknown, want: unknown): void {
  checks++;
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a === b) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${a} want ${b}`); }
}
const mv = (id: string, d: number, at = "2026-03-02T08:00:00Z", type = "adjustment", p = "prod-001", l = "loc-001") =>
  ({ movement_id: id, product_id: p, location_id: l, quantity_delta: d, event_at: at, movement_type: type });
const rows = (inp: PipelineInputs, ent: string): any[] => inp[ent] as any[];
function twoLocations(): PipelineInputs {
  const c = golden();
  rows(c, "locations").push({ location_id: "loc-002", location_name: "B", timezone: "UTC", storage_capacity: 10, active: true });
  rows(c, "inventory_movements").push(mv("x1", 100, "2026-03-02T08:00:00Z", "receipt", "prod-001", "loc-002"));
  return c;
}

// ---- R3-01: stockout_days is a SKU-day rate; the calendar share is its own key ------------------------------------------
{
  const g = runPipeline({ ...golden(), states: JSON.parse(readFileSync(GOLDEN, "utf8")).states }, "golden");
  expectEq("R3-01 golden: 1 of 31 holds under the SKU-day definition", [g.metrics.stockout_day_count, g.metrics.observed_days, g.metrics.stockout_days], [1, 31, "0.032258"]);
  expectEq("R3-01 golden extras", g.extraMetrics, { stockout_calendar_days_share: "0.032258", observed_sku_days: 31 });
  expectEq("R3-01 the fixture's metric keys stay exact and in order", Object.keys(g.metrics), [...METRIC_KEYS]);
  expectEq("R3-01 the extra keys are named", Object.keys(g.extraMetrics), [...EXTRA_METRIC_KEYS]);
  const r = runPipeline(twoLocations());
  expectEq("R3-01 two pairs, one stockout: SKU-day rate 1 / 62", [r.metrics.stockout_day_count, r.extraMetrics.observed_sku_days, r.metrics.stockout_days], [1, 62, "0.016129"]);
  expectEq("R3-01 calendar share stays 1 of 31 dates", [r.extraMetrics.stockout_calendar_days_share, r.metrics.observed_days], ["0.032258", 31]);
  for (const key of ["location", "product", "supplier", "abc_class"] as const) {
    const groups = [...groupMetrics(r.population, key, r.asOf, r.window).values()];
    expectEq(`R3-01 groups by ${key} reconcile: pair-days and SKU-days add up`, [groups.reduce((a, m) => a + m.stockout_day_count, 0), groups.reduce((a, m) => a + m.observed_sku_days, 0)], [1, 62]);
  }
  const byLoc = groupMetrics(r.population, "location", r.asOf, r.window);
  expectEq("R3-01 by location: loc-001 0.032258, loc-002 0.000000", [byLoc.get("loc-001")!.stockout_days, byLoc.get("loc-002")!.stockout_days], ["0.032258", "0.000000"]);
}

// ---- R3-02: scenario-scoped unmet demand is not canonical ---------------------------------------------------------------
{
  const c = golden();
  rows(c, "policy_scenarios").push({ scenario_id: "s-bl", scenario_name: "bl", service_target: "0.95", unmet_policy: "backlog", seed: 1, warmup_days: 0, replications: 1 });
  rows(c, "backorders").push({ backorder_id: "bo-s", product_id: "prod-001", location_id: "loc-001", quantity: 25, opened_at: "2026-03-26T10:00:00Z", closed_at: null, scenario_id: "s-bl" });
  const base = runPipeline(golden());
  const r = runPipeline(c);
  expectEq("R3-02 a scenario backorder never changes the canonical metrics", r.metrics, base.metrics);
  expectEq("R3-02 canonical position stays 60", [r.metrics.inventory_position, r.metrics.backorders, r.metrics.unmet_units], [60, 10, 5]);
  const mine = computeMetricsFull(r.population, r.asOf, r.window, null, {}, "s-bl");
  expectEq("R3-02 the scenario's own view adds its rows", [mine.inventory_position, mine.backorders, mine.unmet_units], [35, 35, 30]);
  expectEq("R3-02 scoped() hides them by default", [scoped(r.population).backorders.length, scoped(r.population, "s-bl").backorders.length], [2, 3]);
}

// ---- R3-04: the position is the sum over every location of the product --------------------------------------------------
{
  const r = runPipeline(twoLocations());
  expectEq("R3-04 multi-location product position 160, on hand 140", [r.metrics.inventory_position, r.metrics.on_hand], [160, 140]);
  expectEq("R3-04 the per-pair figures stay per pair", [r.metrics.reorder_point, r.metrics.order_quantity], [70, 72]);
  const byLoc = groupMetrics(r.population, "location", r.asOf, r.window);
  expectEq("R3-04 by location 60 and 100", [byLoc.get("loc-001")!.inventory_position, byLoc.get("loc-002")!.inventory_position], [60, 100]);
}

// ---- R3-05: sub-millisecond instants keep their microseconds ------------------------------------------------------------
{
  const a = golden();
  rows(a, "inventory_movements").push(mv("x1", 7, "2026-03-31T23:59:59.0004Z", "receipt"));
  expectEq("R3-05 a movement 0.4 ms after the cutoff is excluded (was 47, must be 40)", runPipeline(a).metrics.on_hand, 40);
  const b: PipelineInputs = { ...golden(), as_of: "2026-03-31T23:59:59.0004Z" };
  rows(b, "inventory_movements").push(mv("x1", 7, "2026-03-31T23:59:59.0001Z", "receipt"), mv("x2", -3, "2026-03-31T23:59:59.0009Z", "sale"));
  expectEq("R3-05 receipt at .0001 in, sale at .0009 out of an as-of of .0004: 47", runPipeline(b).metrics.on_hand, 47);
  expectEq("R3-05 microseconds order strictly", parseTs("2026-03-31T23:59:59.000401Z") > parseTs("2026-03-31T23:59:59.000400Z"), true);
  expectEq("R3-05 the same instant in two spellings is the same number", parseTs("2026-03-31T23:59:59.0004Z"), parseTs("2026-04-01T00:59:59.000400+01:00"));
  expectEq("R3-05 isoZ prints six digits like Python", isoZ(parseTs("2026-03-31T23:59:59.0004Z")), "2026-03-31T23:59:59.000400Z");
  expectEq("R3-05 whole seconds stay short", isoZ(parseTs("2026-03-31T23:59:59Z")), "2026-03-31T23:59:59Z");
  expectEq("R3-05 digits finer than a microsecond are truncated", parseTs("2026-03-31T23:59:59.0004019Z"), parseTs("2026-03-31T23:59:59.000401Z"));
}

// ---- R3-06: target position at least the reorder point ------------------------------------------------------------------
{
  const c = golden();
  Object.assign(rows(c, "replenishment_params")[0], { reorder_point: 70, target_position: 50 });
  const r = runPipeline(c);
  expectEq("R3-06 target below the reorder point is rejected", r.rejected.map((x) => [x.entity, x.reason_code]), [["replenishment_params", "REPLENISHMENT_PARAMS_INVALID"]]);
  expectEq("R3-06 and never orders (not evaluated)", [r.metrics.order_quantity, r.metrics.reorder_triggered], [null, null]);
  const ok = golden();
  Object.assign(rows(ok, "replenishment_params")[0], { reorder_point: 70, target_position: 70 });
  expectEq("R3-06 target equal to the reorder point is accepted", runPipeline(ok).rejected.length, 0);
}

// ---- R3-07: negative available, unclamped position -----------------------------------------------------------------------
{
  const c = golden();
  c["reservations"] = [{ reservation_id: "r1", product_id: "prod-001", location_id: "loc-001", quantity: 500, reserved_at: "2026-03-30T00:00:00Z", released_at: null }];
  const r = runPipeline(c);
  expectEq("R3-07 available -460, position 60 (reserved is not in the position)", [r.metrics.available, r.metrics.inventory_position], [-460, 60]);
  expectEq("R3-07 NEGATIVE_AVAILABLE is flagged", r.flags.map((f) => f.flag), ["NEGATIVE_AVAILABLE"]);
  expectEq("R3-07 availabilityFlags figures", availabilityFlags(r.population, r.asOf).map((f) => [f.on_hand, f.reserved, f.available]), [[40, 500, -460]]);
  const n = golden();
  rows(n, "inventory_movements").push(mv("n1", -100, "2026-03-31T10:00:00Z", "sale"));
  const m = runPipeline(n);
  expectEq("R3-07 on hand valued at zero and flagged", [m.metrics.on_hand, m.metrics.negative_stock, m.flags.map((f) => f.flag).includes("NEGATIVE_STOCK")], [0, true, true]);
  expectEq("R3-07 the position uses the unclamped ledger value: -60 + 30 - 10", m.metrics.inventory_position, -40);
  expectEq("R3-07 and the order follows it: 7 packs of 24", m.metrics.order_quantity, 168);
}

// ---- S-02: suppliers load before products --------------------------------------------------------------------------------
{
  const c = golden();
  rows(c, "products")[0].supplier_id = "sup-001";
  expectEq("S-02 a product with a supplier_id is accepted", [runPipeline(c).rejected.length, runPipeline(c).population.products[0]!.supplier_id], [0, "sup-001"]);
  const bad = golden();
  rows(bad, "products")[0].supplier_id = "sup-nope";
  expectEq("S-02 an unknown supplier is still UNKNOWN_REFERENCE", runPipeline(bad).rejected.map((x) => x.reason_code)[0], "UNKNOWN_REFERENCE");
}

// ---- S-03: the promotion factor is 1 + planned uplift --------------------------------------------------------------------
{
  const promo: Promotion = { promotion_id: "pr-1", product_id: "prod-001", starts_at: parseTs("2026-03-02T00:00:00Z"), ends_at: parseTs("2026-03-04T00:00:00Z"),
    planned_uplift: "0.50", announced_at: parseTs("2026-02-10T00:00:00Z"), realised_uplift: "9.0", location_id: null };
  const day = parseDay("2026-03-03"), known = parseTs("2026-02-28T23:59:59Z");
  const gcd = (a: bigint, b: bigint): bigint => (b === 0n ? a : gcd(b, a % b));
  const factor = (p: Promotion[], d: number, k: number): string => {
    const r = decToRat(promoFactor(p, "prod-001", d, k));
    const g = gcd(r.num, r.den);
    return `${r.num / g}/${r.den / g}`;
  };
  expectEq("S-03 one promotion: 3/2, not 1/2", factor([promo], day, known), "3/2");
  expectEq("S-03 two promotions: 9/4", factor([promo, promo], day, known), "9/4");
  expectEq("S-03 outside the window: 1", factor([promo], parseDay("2026-03-10"), known), "1/1");
  expectEq("S-03 not yet announced: 1", factor([promo], day, parseTs("2026-02-01T00:00:00Z")), "1/1");
}

console.log(failures === 0 ? `REVIEW OK (${checks} checks)` : `${failures} MISMATCH of ${checks} checks`);
process.exitCode = failures === 0 ? 0 : 1;
