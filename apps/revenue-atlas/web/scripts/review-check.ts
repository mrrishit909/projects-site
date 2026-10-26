// Regression checks for the master-18 reviewer findings R-01, R-03, R-04, R-06, R-07 (docs/contracts.md D-08, D-09).
// Same fixtures (tests/fixtures/review) and the same expected values as tests/test_review_findings.py.
import { readFileSync } from "node:fs";
import * as D from "../src/domain/decimal";
import { UNALLOCATED_GROUP } from "../src/domain/contract";
import { NO_WINDOW, computeMetrics, groupMetrics, monthlyMetrics, regionKey, utcMidnight, windowLedger, type Window } from "../src/domain/metrics";
import { runPipeline } from "../src/domain/pipeline";
import { validateBatch } from "../src/domain/ingest";
import { ENTITIES, type PipelineInputs } from "../src/domain/types";

const ROOT = new URL("../../tests/fixtures/", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));
const review = (n: string): any => readJson(new URL(`review/in_${n}.json`, ROOT));
const golden = (): any => readJson(new URL("golden/inputs.json", ROOT));

let failures = 0;
let checks = 0;
function expectEq(label: string, got: unknown, want: unknown): void {
  checks++;
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) console.log(`OK       ${label}`);
  else {
    failures++;
    console.log(`MISMATCH ${label}: got ${g} want ${w}`);
  }
}
const rejected = (b: any): [string, string, string][] => validateBatch(b).rejected.map((r) => [r.entity, r.id, r.reason_code]);
const tiny = (qty = 2): any => ({
  contract: "v1",
  customers: [{ customer_id: "c1", customer_name: "C", region_id: "r1", segment: "SMB", effective_from: "2025-01-01" }],
  products: [{ product_id: "p1", sku: "S1", category_id: "k", unit_of_measure: "each", active: true }],
  orders: [{ order_id: "o1", customer_id: "c1", order_date: "2026-03-08", currency: "USD", status: "shipped" }],
  order_lines: [{ line_id: "l1", order_id: "o1", product_id: "p1", quantity: qty, unit_price: "10.00" }],
  discounts: [{ discount_id: "d1", line_id: "l1", discount_amount: "0.03", reason_code: "X", approved_by: "m" }],
  shipments: [], shipment_lines: [], returns: [],
  cost_versions: [{ cost_version_id: "cv1", product_id: "p1", unit_cost: "4.00", valid_from: "2026-01-01", valid_to: null }],
  exchange_rates: [{ rate_id: "fx1", currency: "USD", reporting_currency: "USD", rate_date: "2026-01-01", rate: "1.0" }],
});
const ship = (b: any, shipment: string, sl: string, qty: number): void => {
  if (!b.shipments.some((s: any) => s.shipment_id === shipment)) {
    b.shipments.push({ shipment_id: shipment, order_id: "o1", shipped_at: "2026-03-10T12:00:00Z", shipping_cost: "3.00", currency: "USD" });
  }
  b.shipment_lines.push({ shipment_line_id: sl, shipment_id: shipment, line_id: "l1", shipped_quantity: qty });
};

// ---- R-01: shipped above ordered is rejected with its dependents ------------------------------------
{
  const over = review("over");
  expectEq("R-01 over-shipped line and dependents rejected", rejected(over), [
    ["discounts", "d5", "SHIPPED_EXCEEDS_ORDERED"], ["order_lines", "L5", "SHIPPED_EXCEEDS_ORDERED"], ["shipment_lines", "sl7", "SHIPPED_EXCEEDS_ORDERED"]]);
  const withReturn = review("over");
  withReturn.returns.push({ return_id: "rX", shipment_line_id: "sl7", returned_quantity: 1, credit_amount: "1.00", credit_date: "2026-03-12" });
  expectEq("R-01 a return of the rejected shipment line follows it", rejected(withReturn).some((r) => r[1] === "rX" && r[2] === "SHIPPED_EXCEEDS_ORDERED"), true);
  const clean = review("over");
  for (const [ent, key] of [["order_lines", "L5"], ["discounts", "d5"], ["shipment_lines", "sl7"]] as const) {
    clean[ent] = clean[ent].filter((r: any) => !Object.values(r).includes(key));
  }
  expectEq("R-01 metrics equal the batch without the over-shipped line", runPipeline(review("over"), true).metrics, runPipeline(clean, true).metrics);
  const ok = tiny(2); ship(ok, "s1", "sl1", 1); ship(ok, "s2", "sl2", 1);
  expectEq("R-01 shipped == ordered across two shipments is accepted", rejected(ok), []);
  const split = tiny(2); ship(split, "s1", "sl1", 1); ship(split, "s2", "sl2", 2);
  expectEq("R-01 the total across shipment lines is what counts", rejected(split), [
    ["discounts", "d1", "SHIPPED_EXCEEDS_ORDERED"], ["order_lines", "l1", "SHIPPED_EXCEEDS_ORDERED"],
    ["shipment_lines", "sl1", "SHIPPED_EXCEEDS_ORDERED"], ["shipment_lines", "sl2", "SHIPPED_EXCEEDS_ORDERED"]]);
}

// ---- R-06: a shipment line of another order is rejected -----------------------------------------------
{
  const cross = review("cross");
  expectEq("R-06 cross-order shipment line rejected", rejected(cross), [["shipment_lines", "sl9", "SHIPMENT_LINE_ORDER_MISMATCH"]]);
  cross.returns.push({ return_id: "rY", shipment_line_id: "sl9", returned_quantity: 1, credit_amount: "1.00", credit_date: "2026-03-12" });
  expectEq("R-06 its return follows it", rejected(cross).some((r) => r[1] === "rY" && r[2] === "SHIPMENT_LINE_ORDER_MISMATCH"), true);
  expectEq("R-06 it is not counted against the line it points at", rejected(cross).some((r) => r[2] === "SHIPPED_EXCEEDS_ORDERED"), false);
  const clean = review("cross");
  clean.shipment_lines = clean.shipment_lines.filter((r: any) => r.shipment_line_id !== "sl9");
  expectEq("R-06 metrics equal the batch without that line", runPipeline(review("cross"), true).metrics, runPipeline(clean, true).metrics);
}

// ---- R-07: negative zero credit ----------------------------------------------------------------------
for (const zero of ["-0.00", "-0", "-0.0000"]) {
  const b = golden();
  b.returns[0].credit_amount = zero;
  expectEq(`R-07 credit ${zero} is CREDIT_SIGN_REVERSED`, rejected(b), [["returns", "ret-001", "CREDIT_SIGN_REVERSED"]]);
  expectEq(`R-07 credit ${zero} adds no credit`, runPipeline(b, true).metrics.merchandise_credits, "0.00");
}
{
  const b = golden();
  b.returns[0].credit_amount = "0.00";
  expectEq("R-07 a plain 0.00 credit is still accepted", rejected(b), []);
}

// ---- R-03: grouped shipping cost includes the UNALLOCATED group --------------------------------------------
{
  const res = runPipeline(review("unalloc"), true);
  expectEq("R-03 overall shipping cost", res.metrics.shipping_cost, "36.25");
  expectEq("R-03 unallocated freight", D.toString(res.unallocatedFreight), "5.00");
  const keys: Record<string, (f: any) => string> = { region: regionKey, customer: (f) => f.customer_id, product: (f) => f.product_id, month: (f) => f.shipped_date.slice(0, 7) };
  for (const [name, key] of Object.entries(keys)) {
    const groups = groupMetrics(res.facts, key, NO_WINDOW, res.returns, res.unallocatedFreight);
    const u = groups.get(UNALLOCATED_GROUP)!;
    expectEq(`R-03 ${name}: UNALLOCATED group`, [u.shipping_cost, u.contribution_margin, u.gross_sales], ["5.00", "-5.00", "0.00"]);
    let ship = D.ZERO;
    let cm = D.ZERO;
    for (const g of groups.values()) { ship = D.add(ship, D.parse(g.shipping_cost)); cm = D.add(cm, D.parse(g.contribution_margin)); }
    expectEq(`R-03 ${name}: grouped shipping cost sums to the overall 36.25`, D.toString(ship), "36.25");
    const drift = D.sub(cm, D.parse(res.metrics.contribution_margin));
    expectEq(`R-03 ${name}: contribution within the R-05 cent drift`, D.cmp(drift.u < 0n ? D.neg(drift) : drift, D.parse("0.02")) <= 0, true);
    expectEq(`R-03 ${name}: keys sorted`, [...groups.keys()], [...groups.keys()].sort());
  }
  const without = groupMetrics(res.facts, regionKey, NO_WINDOW, res.returns);
  expectEq("R-03 nothing emitted without unallocated freight", without.has(UNALLOCATED_GROUP), false);
}

// ---- R-04: months follow the credit date; the ledger decomposition equals the bridge --------------------------
{
  const b = golden();
  b.returns[0].credit_date = "2026-04-05"; // shipped 2026-03-10, credited a month later
  const res = runPipeline(b, true);
  const months = monthlyMetrics(res.facts, res.returns);
  expectEq("R-04 months", [...months.keys()], ["2026-03", "2026-04"]);
  expectEq("R-04 March gross/credits", [months.get("2026-03")!.gross_sales, months.get("2026-03")!.merchandise_credits], ["250.00", "0.00"]);
  expectEq("R-04 April gross/credits/net", [months.get("2026-04")!.gross_sales, months.get("2026-04")!.merchandise_credits, months.get("2026-04")!.net_merchandise_sales], ["0.00", "90.00", "-90.00"]);
  for (const k of ["merchandise_credits", "net_merchandise_sales", "contribution_margin", "cogs"] as const) {
    let s = D.ZERO;
    for (const m of months.values()) s = D.add(s, D.parse(m[k]));
    expectEq(`R-04 months add up to the total (${k})`, D.toString(s), res.metrics[k]);
  }
  const byShipMonth = groupMetrics(res.facts, (f) => f.shipped_date.slice(0, 7), NO_WINDOW, res.returns);
  expectEq("R-04 (the pre-fix view) grouping by shipment month books the credit in March", byShipMonth.get("2026-03")!.merchandise_credits, "90.00");
  const april: Window = { from: utcMidnight("2026-04-01"), to: utcMidnight("2026-04-10") };
  const led = windowLedger(res.facts, res.returns, april);
  expectEq("R-04 ledger window: no lines, one credit row", [led.lines.length, led.outside.map((o) => o.event.return_id)], [0, ["ret-001"]]);
}
{
  const snap: Record<string, unknown> = { contract: "v1" };
  const DATA = new URL("../public/data/", import.meta.url);
  for (const e of ENTITIES) snap[e] = readJson(new URL(`${e}.json`, DATA)).rows;
  const res = runPipeline(snap as PipelineInputs, true);
  const months = monthlyMetrics(res.facts, res.returns);
  expectEq("R-04 snapshot 2024-11 credits follow D-01a (SQL month table: 6096.40)", months.get("2024-11")!.merchandise_credits, "6096.40");
  for (const k of ["gross_sales", "allocated_discounts", "merchandise_credits", "net_merchandise_sales", "cogs", "shipping_cost", "contribution_margin"] as const) {
    let s = D.ZERO;
    for (const m of months.values()) s = D.add(s, D.parse(m[k]));
    // each month is rounded to cents on its own (presentation, D-02), so the sum may differ by a cent or two
    const diff = D.sub(s, D.parse(res.metrics[k]));
    expectEq(`R-04 snapshot: the months add up to the total within rounding (${k})`, D.cmp(diff.u < 0n ? D.neg(diff) : diff, D.parse("0.05")) <= 0, true);
  }
  // Ledger decomposition (D-09): lines + credit rows reproduce computeMetrics for every window and a region filter.
  const windows: Window[] = [
    NO_WINDOW,
    { from: utcMidnight("2025-03-01"), to: utcMidnight("2025-04-01") },
    { from: utcMidnight("2026-01-01"), to: null },
    { from: null, to: utcMidnight("2024-12-01") },
  ];
  for (const [i, w] of windows.entries()) {
    for (const region of [null, "reg-west"]) {
      const dim = region ? res.facts.filter((f) => f.region_id === region) : res.facts;
      const m = computeMetrics(dim, w, { returns: res.returns });
      const { lines, outside } = windowLedger(dim, res.returns, w);
      let credit = D.ZERO, rec = D.ZERO, gross = D.ZERO, cogs = D.ZERO;
      for (const f of lines) { credit = D.add(credit, f.merchandise_credit); rec = D.add(rec, f.recoverable_return_cost); gross = D.add(gross, f.gross_sales); cogs = D.add(cogs, f.cogs); }
      for (const o of outside) { credit = D.add(credit, o.event.merchandise_credit); rec = D.add(rec, o.event.recoverable_return_cost); }
      expectEq(`R-04 ledger == bridge window ${i} region ${region ?? "all"}`,
        [D.fixed(gross, 2), D.fixed(credit, 2), D.fixed(D.sub(cogs, rec), 2), lines.length],
        [m.gross_sales, m.merchandise_credits, m.cogs, m.eligible_shipment_lines]);
    }
  }
}

console.log(failures === 0 ? `ALL OK (${checks} checks)` : `${failures} MISMATCH of ${checks} checks`);
process.exitCode = failures === 0 ? 0 : 1;
