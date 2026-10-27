// Adversarial checks of the TypeScript domain on small hand-worked worlds (the pure-domain twin of the contract's edge cases): a one-time cost repeated,
// an annual rate on monthly periods (refused, then converted), a benefit before deployment, a cycle, an overallocation, a touching allocation accepted, a
// case that never pays back, avoided cost with and without evidence, capacity with and without a conversion, ties and repeats in the double-count rule, empty
// populations and zero denominators, ramps, realisation on matured periods, cost variance, readiness, risk, roadmap chains, instants that sort as instants,
// half-open windows and malformed records. Every expected value is worked by hand in the comment above its check. Run by `npm run check` after the golden check.
import { ENTITIES, type Row } from "../src/domain/contract";
import { Validator } from "../src/domain/ingest";
import { parseTs } from "../src/domain/time";
import { goldenOf, runPipeline } from "../src/domain/pipeline";

let failures = 0, checks = 0, worlds = 0;
const canon = (v: unknown): string => JSON.stringify(v);
function eq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 400)} want ${canon(want).slice(0, 400)}`); }
}
const world = (label: string): void => { worlds++; console.log(`-- world ${worlds}: ${label}`); };

// ------------------------------------------------------------------------------------------------------------------------ builders
const world0 = (basis = "annual", asOf = "2028-06-30T00:00:00Z", rows: Row = {}): Row => {
  const d: Row = { contract_version: 1, as_of: asOf, period_basis: basis, period_start: "2026-01-01" };
  for (const e of ENTITIES) d[e] = [];
  return Object.assign(d, structuredClone(rows));
};
const ini = (i = "i-1", dep = 1, base: string | null = "v1", extra: Row = {}): Row => ({ initiative_id: i, title: `Initiative ${i}`, sponsor_id: "sp-1", status: "in_delivery", baseline_version: base, requested_start_period: 0, duration_periods: 1, deployment_period: dep, eligibility_rule_version: "elig-v1", ...extra });
const pb = (i = "i-1", v = "v1", vol = 1200, mins = 10): Row => ({ baseline_id: `pb-${i}-${v}`, initiative_id: i, baseline_version: v, volume: vol, minutes_per_case: mins, error_rate: "0.040000", evidence_ref: "ev:timesheet", measured_at: "2025-11-30T00:00:00Z", reason: null });
const asm = (aid: string, i: string | null, name: string, n = 1, value: string | null = null, values: string[] | null = null, staff: string | null = null): Row => ({ assumption_id: aid, initiative_id: i, name, version_number: n, value, values, unit: "x", rationale: "synthetic", author_id: "an-1", evidence_ref: null, staffing_change_evidence_ref: staff, created_at: "2026-01-10T00:00:00Z" });
const sc = (sid = "s-1", inis: string[] = ["i-1"], rate = "0.100000", basis = "annual", h = 3, pins: string[] = [], conv: string | null = null, status = "draft"): Row => ({ scenario_id: sid, baseline_version: "v1", discount_rate: rate, rate_basis: basis, rate_conversion_assumption_id: conv, horizon_periods: h, status, initiative_ids: inis, pinned_assumption_ids: pins, created_at: "2026-01-15T09:00:00Z" });
const cost = (cid: string, i: string, key: string, typ: string, amt: string, p: number | null = null, s: number | null = null, e: number | null = null, basis = "planned", bv: string | null = null): Row => ({ cost_id: cid, initiative_id: i, cost_key: key, cost_type: typ, cost_basis: basis, amount: amt, period_index: p, start_period: s, end_period: e, baseline_version: bv });
const ben = (bid: string, i: string, typ: string, amt: string, p: number, starts: number | null = null, real: boolean | null = null, ev: string | null = null, key: string | null = null, trend: string | null = null): Row => ({ benefit_id: bid, initiative_id: i, benefit_type: typ, amount: amt, period_index: p, starts_period: starts ?? p, unit: typ === "capacity" ? "hours" : "USD", cash_realisation: real, evidence_ref: ev, benefit_source_key: key, baseline_trend_per_period: trend });
const dep = (did: string, i: string, pre: string, typ = "finish_to_start", lag = 0): Row => ({ dependency_id: did, initiative_id: i, prerequisite_id: pre, dependency_type: typ, lag_periods: lag });
const bo = (oid: string, b: string, val: string, at = "2028-01-31T00:00:00Z"): Row => ({ benefit_observation_id: oid, benefit_id: b, measured_value: val, evidence_ref: "ev:ledger", observed_at: at });
const ad = (oid: string, i: string, elig: number, adopted: number, at: string, rule = "elig-v1"): Row => ({ observation_id: oid, initiative_id: i, eligible_count: elig, adopted_count: adopted, observed_at: at, eligibility_rule_version: rule });
const grp = (gid = "g-1", name = "Accounts payable clerks"): Row => ({ group_id: gid, group_name: name, owner_id: "sp-1", affected_count: 10, impact_level: "high" });
const ra = (aid: string, g: string, dim: string, score: number, weight = "1.00", at = "2027-02-01T00:00:00Z"): Row => ({ assessment_id: aid, group_id: g, dimension: dim, score, weight, assessed_at: at });
const fc = (i: string, v: number, p: number, amt: string, at = "2026-01-20T00:00:00Z"): Row => ({ forecast_id: `f-${i}-${v}-${p}`, initiative_id: i, version_number: v, period_index: p, amount: amt, reason: "Approved forecast", created_at: at });
const run = (w: Row) => runPipeline(w);
const blk = (r: ReturnType<typeof run>, s = "s-1", i = "i-1"): Row => r.metrics["scenarios"][s]["initiatives"][i];
const rej = (r: ReturnType<typeof run>): [string, string, string][] => r.ingest.rejected.map((x) => [x.entity, String(x.id), x.reason_code]);

// ------------------------------------------------------------------------------------------------------------------------ 1. a one-time cost repeated
// Cost ck-a (1000 at t=0) is recorded again for t=1: the later row is refused with the first row named; only one row expands. NPV = -1000 + 600/1.1 + 600/1.21 = 5000/121.
world("a one-time cost repeated in a second period");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], scenario_versions: [sc()], cost_items: [cost("c-1", "i-1", "ck-a", "one_time", "1000.00", 0), cost("c-2", "i-1", "ck-a", "one_time", "1000.00", 1)], benefit_items: [ben("b-1", "i-1", "cash", "600.00", 1), ben("b-2", "i-1", "cash", "600.00", 2)] }));
  eq("the repeat is refused ONE_TIME_COST_REPEATED, the first row is kept", [rej(r), r.ingest.rejected[0]!.details, r.computation.metrics.summary.initiatives], [[["cost_items", "c-2", "ONE_TIME_COST_REPEATED"]], { first_cost_id: "c-1", first_period: 0, repeat_period: 1 }, 1]);
  eq("one expanded cost row; NPV 5000/121 = 41.32; cumulative at t=0 is -1000.00", [blk(r)["expanded_planned_costs"].length, blk(r)["npv"].exact, blk(r)["npv"].value, blk(r)["cash_flow"][0].cumulative], [1, "5000/121", "41.32", "-1000.00"]);
}
// the same key with another basis (actual) or another initiative is not a repeat
world("the same cost key in another basis is not a repeat");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini(), ini("i-2")], cost_items: [cost("c-1", "i-1", "ck-a", "one_time", "10.00", 0), cost("c-2", "i-1", "ck-a", "one_time", "11.00", 0, null, null, "actual"), cost("c-3", "i-2", "ck-a", "one_time", "12.00", 0)] }));
  eq("planned, actual and another initiative's row all accepted", [rej(r), r.population.acc.cost_items.length], [[], 3]);
}
// ------------------------------------------------------------------------------------------------------------------------ 2-3. rate basis
// Monthly periods and an annual rate with no conversion: refused, the scenario does not exist, the summary has no NPV.
world("an annual rate on monthly periods, no conversion");
{
  const r = run(world0("monthly", "2026-10-05T00:00:00Z", { initiatives: [ini()], scenario_versions: [sc("s-1", ["i-1"], "0.100000", "annual", 2)] }));
  eq("refused RATE_PERIOD_MISMATCH with both bases named; no scenario; NPV null", [rej(r), r.ingest.rejected[0]!.details, Object.keys(r.metrics["scenarios"]), r.metrics["summary"]["npv_total"]], [[["scenario_versions", "s-1", "RATE_PERIOD_MISMATCH"]], { rate_basis: "annual", period_basis: "monthly" }, [], null]);
}
// With a recorded conversion 0.007974: 1+r = 503987/500000; NPV = -1000 + 1100 * 500000/503987 = 46013000/503987 = 91.2979... -> 91.30.
world("an annual rate converted explicitly");
{
  const r = run(world0("monthly", "2026-10-05T00:00:00Z", { initiatives: [ini()], assumption_versions: [asm("a-conv", null, "monthly_rate_conversion", 1, "0.007974")], scenario_versions: [sc("s-1", ["i-1"], "0.100000", "annual", 2, [], "a-conv")], cost_items: [cost("c-1", "i-1", "ck", "one_time", "1000.00", 0)], benefit_items: [ben("b-1", "i-1", "cash", "1100.00", 1)] }));
  const s = r.metrics["scenarios"]["s-1"];
  eq("the conversion is the rate used, never the raw annual figure", [s.rate_source, s.effective_period_rate, s.effective_period_rate_exact, s.declared_rate], ["conversion:a-conv", "0.007974", "3987/500000", "0.100000"]);
  eq("NPV exact 46013000/503987 = 4183000/45817 (both divided by 11) = 91.30; row 1 starts 2026-02-01", [blk(r).npv.exact, blk(r).npv.value, blk(r).cash_flow[1].period_start], ["4183000/45817", "91.30", "2026-02-01"]);
}
// A conversion that is not a monthly_rate_conversion assumption is refused INVALID_CONVERSION.
world("a conversion that is not a conversion");
{
  const r = run(world0("monthly", "2026-10-05T00:00:00Z", { initiatives: [ini()], assumption_versions: [asm("a-x", "i-1", "target_minutes_per_case", 1, "8")], scenario_versions: [sc("s-1", ["i-1"], "0.100000", "annual", 2, [], "a-x")] }));
  eq("refused INVALID_CONVERSION naming the expected assumption", [rej(r), r.ingest.rejected[0]!.details], [[["scenario_versions", "s-1", "INVALID_CONVERSION"]], { assumption_id: "a-x", expected_name: "monthly_rate_conversion" }]);
}
// ------------------------------------------------------------------------------------------------------------------------ 4-5. deployment
world("a benefit before deployment, and one exactly at deployment");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1", 3)], benefit_items: [ben("b-1", "i-1", "cash", "50.00", 2), ben("b-2", "i-1", "cash", "50.00", 3), ben("b-3", "i-1", "cash", "50.00", 4, 3)] }));
  eq("starts_period 2 < deployment 3 is refused with both numbers; starts at 3 (touching) and a later period of a stream that starts at 3 are accepted", [rej(r), r.ingest.rejected[0]!.details], [[["benefit_items", "b-1", "BENEFIT_BEFORE_DEPLOYMENT"]], { starts_period: 2, deployment_period: 3 }]);
}
// ------------------------------------------------------------------------------------------------------------------------ 6. cycles
world("a cycle among three, and a self-dependency");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1"), ini("i-2"), ini("i-3")], dependencies: [dep("d-1", "i-2", "i-1"), dep("d-2", "i-3", "i-2"), dep("d-3", "i-1", "i-3"), dep("d-4", "i-3", "i-3")] }));
  eq("d-3 closes i-1 -> i-3 -> i-2 -> i-1, listed from the rejected edge's initiative; the self-dependency is a two-element cycle", [rej(r), r.ingest.rejected.map((x) => x.details["cycle"])], [[["dependencies", "d-3", "DEPENDENCY_CYCLE"], ["dependencies", "d-4", "DEPENDENCY_CYCLE"]], [["i-1", "i-3", "i-2", "i-1"], ["i-3", "i-3"]]]);
  eq("the accepted edges still give a roadmap (no cycle in the stored data)", [r.metrics["initiatives"]["i-3"].roadmap.dependency_feasible_start, r.metrics["initiatives"]["i-3"].roadmap.dependency_delay], [2, 2]);
}
// ------------------------------------------------------------------------------------------------------------------------ 7-8. allocations
world("an overallocation and a touching allocation");
{
  const al = (id: string, p: number, amt: string, i = "i-1"): Row => ({ allocation_id: id, resource_id: "r-1", initiative_id: i, period_index: p, amount: amt });
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini(), ini("i-2")], resources: [{ resource_id: "r-1", name: "Analysts", capacity_per_period: "1.00", unit: "FTE" }], resource_allocations: [al("al-1", 0, "0.60"), al("al-2", 0, "0.50", "i-2"), al("al-3", 1, "0.60"), al("al-4", 1, "0.40", "i-2")] }));
  eq("0.60 + 0.50 > 1.00: the crossing row is refused with the periods, what was allocated, requested and the capacity", [rej(r), r.ingest.rejected[0]!.details], [[["resource_allocations", "al-2", "RESOURCE_OVERALLOCATED"]], { resource_id: "r-1", periods: [0], allocated_before: "0.60", requested: "0.50", capacity: "1.00" }]);
  eq("0.60 + 0.40 = 1.00 is accepted (a sum equal to capacity is allowed): headroom 0.00 and nothing stored above capacity", [r.metrics["resources"]["r-1"].by_period, r.metrics["resources"]["r-1"].overallocated_periods], [[{ period_index: 0, allocated: "0.60", headroom: "0.40" }, { period_index: 1, allocated: "1.00", headroom: "0.00" }], []]);
}
// ------------------------------------------------------------------------------------------------------------------------ 9. never pays back
// cost 1000 at t=0 and 100 a period for three periods at 10 %: cumulative -900, -800, -700 never reaches 0: payback null (not 0); NPV negative.
world("a case that never pays back");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], scenario_versions: [sc("s-1", ["i-1"], "0.100000", "annual", 4)], cost_items: [cost("c-1", "i-1", "ck", "one_time", "1000.00", 0)], benefit_items: [ben("b-1", "i-1", "cash", "100.00", 1), ben("b-2", "i-1", "cash", "100.00", 2), ben("b-3", "i-1", "cash", "100.00", 3)] }));
  eq("both paybacks null, cumulative ends at -700.00", [blk(r).payback, blk(r).cash_flow[3].cumulative], [{ simple: { period: null, interpolated: null, reason: "NOT_RECOVERED" }, discounted: { period: null, interpolated: null, reason: "NOT_RECOVERED" } }, "-700.00"]);
  // NPV = -1000 + 100/1.1 + 100/1.21 + 100/1.331 = (-1331000 + 121000 + 110000 + 100000)/1331 = -1000000/1331 = -751.31...
  eq("NPV = -1000000/1331 = -751.31", [blk(r).npv.exact, blk(r).npv.value], ["-1000000/1331", "-751.31"]);
}
// The simple payback can come before the discounted one: cost 1000, inflows 600, 600 at 50 %: cumulative -400, 200 -> simple 2; discounted -1000+400+266.67 = -333.33 never.
world("simple payback without a discounted one");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], scenario_versions: [sc("s-1", ["i-1"], "0.500000", "annual", 3)], cost_items: [cost("c-1", "i-1", "ck", "one_time", "1000.00", 0)], benefit_items: [ben("b-1", "i-1", "cash", "600.00", 1), ben("b-2", "i-1", "cash", "600.00", 2)] }));
  // simple: t=2, 1 + 400/(200+400) = 1.6667 ; discounted: -1000 + 400 + 266.666... = -333.33 -> never
  eq("simple payback 2 (1.6667), discounted null: two paybacks, labelled separately", blk(r).payback, { simple: { period: 2, interpolated: "1.6667", reason: null }, discounted: { period: null, interpolated: null, reason: "NOT_RECOVERED" } });
}
// ------------------------------------------------------------------------------------------------------------------------ 10. no flows, and a flow at t=0
world("no flows at all, and a first flow at t=0");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1", 0), ini("i-2", 0)], scenario_versions: [sc("s-1", ["i-1", "i-2"], "0.100000", "annual", 2)], benefit_items: [ben("b-1", "i-1", "cash", "100.00", 0)] }));
  eq("an initiative with no costs and no benefits has NPV and both paybacks null, not 0, and rows of zeros", [blk(r, "s-1", "i-2").npv, blk(r, "s-1", "i-2").payback.simple, blk(r, "s-1", "i-2").cash_flow.map((x: Row) => x["net_cash_flow"])], [{ value: null, exact: null, unit: "USD", label: "estimate" }, { period: null, interpolated: null, reason: "NO_FLOWS" }, ["0.00", "0.00"]]);
  eq("a flow of +100 at t=0 with no cost never goes negative: payback null, reason NO_INVESTMENT (R9-12); NPV 100", [blk(r).payback.simple, blk(r).npv.exact], [{ period: null, interpolated: null, reason: "NO_INVESTMENT" }, "100"]);
}
// ------------------------------------------------------------------------------------------------------------------------ 11. avoided cost
// cost 100 at t=0; avoided 100 with budget evidence (enters), 50 with a claim but no evidence, 30 not cash-realised, 20 with no flag. r=0: NPV = 0.
world("avoided cost with and without evidence");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], scenario_versions: [sc("s-1", ["i-1"], "0.000000", "annual", 3)], cost_items: [cost("c-1", "i-1", "ck", "one_time", "100.00", 0)],
    benefit_items: [ben("b-1", "i-1", "avoided_cost", "100.00", 1, null, true, "ev:budget-line"), ben("b-2", "i-1", "avoided_cost", "50.00", 1, null, true, null), ben("b-3", "i-1", "avoided_cost", "30.00", 2, null, false, "ev:x"), ben("b-4", "i-1", "avoided_cost", "20.00", 2, null, null)] }));
  const e = blk(r).excluded_from_cash_flow;
  eq("only the evidenced line enters (NPV 0.00 at a zero rate); the rest sit beside with their reasons, 100.00 in all", [blk(r).npv.value, blk(r).cash_flow[1].benefits_by_class.avoided_cost_realised, e.avoided_cost_beside.map((x: Row) => [x["benefit_id"], x["reason"]]), e.avoided_cost_beside_total], ["0.00", "100.00", [["b-2", "NO_EVIDENCE_REF"], ["b-3", "NOT_CASH_REALISED"], ["b-4", "NOT_CASH_REALISED"]], "100.00"]);
}
// ------------------------------------------------------------------------------------------------------------------------ 12-13. capacity
// 10 hours in period 1, cost 400 at t=0, r = 0. With rate 50 and staffing evidence: 500.00 enters as a derived cash item; NPV 100.00.
world("capacity with a conversion, without one, and with a rate but no staffing evidence");
{
  const base = { initiatives: [ini()], scenario_versions: [sc("s-1", ["i-1"], "0.000000", "annual", 2)], cost_items: [cost("c-1", "i-1", "ck", "one_time", "400.00", 0)], benefit_items: [ben("b-1", "i-1", "capacity", "10.00", 1, null, null, null, "src-cap")] };
  const withConv = run(world0("annual", "2028-06-30T00:00:00Z", { ...base, assumption_versions: [asm("a-r", "i-1", "capacity_hourly_rate", 1, "50", null, "ev:headcount-plan")] }));
  eq("converted: one derived item citing the assumption and its evidence; NPV 100.00; no hours excluded", [blk(withConv).converted_capacity, blk(withConv).npv.value, blk(withConv).excluded_from_cash_flow.capacity_hours_not_converted], [[{ source_benefit_id: "b-1", period_index: 1, hours: "10.00", hourly_rate: "50.00", amount: "500.00", conversion_assumption_id: "a-r", staffing_change_evidence_ref: "ev:headcount-plan" }], "100.00", null]);
  eq("the converted amount is a money claim of 500.00 for the double-count rule", withConv.metrics["scenarios"]["s-1"].double_count.planned_benefits, "500.00");
  const none = run(world0("annual", "2028-06-30T00:00:00Z", base));
  eq("no conversion: the 10 hours stay out of the cash flow (NPV = -400.00) and are listed; a capacity hour is not a dollar", [blk(none).npv.value, blk(none).excluded_from_cash_flow.capacity_hours_not_converted, blk(none).converted_capacity, none.metrics["scenarios"]["s-1"].double_count.planned_benefits], ["-400.00", "10.00", [], "0.00"]);
  const noEv = run(world0("annual", "2028-06-30T00:00:00Z", { ...base, assumption_versions: [asm("a-r", "i-1", "capacity_hourly_rate", 1, "50", null, null)] }));
  eq("a rate without staffing-change evidence converts nothing", [blk(noEv).converted_capacity, blk(noEv).excluded_from_cash_flow.capacity_hours_not_converted], [[], "10.00"]);
  const claim = run(world0("annual", "2028-06-30T00:00:00Z", { ...base, benefit_items: [ben("b-1", "i-1", "capacity", "10.00", 1, null, true)] }));
  eq("a capacity row that claims cash realisation without a conversion is refused CAPACITY_WITHOUT_CONVERSION", [rej(claim), claim.ingest.rejected[0]!.details], [[["benefit_items", "b-1", "CAPACITY_WITHOUT_CONVERSION"]], { hours: "10.00" }]);
}
// ------------------------------------------------------------------------------------------------------------------------ 14-15. double counting
// Key K, period 1: i-1 100, i-2 100 (a tie), i-3 50 -> counted once at 100, overlap 150. Period 2: i-1 100, i-2 80 -> overlap 80. Residual 230; planned 430; attributable 200.
world("a tie and a third claimant in the double-count rule");
{
  const K = "K";
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1"), ini("i-2"), ini("i-3")], scenario_versions: [sc("s-1", ["i-1", "i-2", "i-3"], "0.000000", "annual", 3)],
    benefit_items: [ben("b-1", "i-1", "cash", "100.00", 1, null, null, null, K), ben("b-2", "i-1", "cash", "100.00", 2, 1, null, null, K), ben("b-3", "i-2", "cash", "100.00", 1, null, null, null, K), ben("b-4", "i-2", "cash", "80.00", 2, 1, null, null, K), ben("b-5", "i-3", "cash", "50.00", 1, null, null, null, K)] }));
  const dc = r.metrics["scenarios"]["s-1"].double_count;
  eq("planned 430.00, attributable 200.00, residual 230.00, explanation required", [dc.planned_benefits, dc.attributable_benefits, dc.residual, dc.explanation_required], ["430.00", "200.00", "230.00", true]);
  eq("overlaps in key then period order: 150.00 (tie counted once) then 80.00; claims sorted by initiative", [dc.overlaps.map((o: Row) => [o["period_index"], o["counted_once"], o["overlap"], o["claims"].map((c: Row) => c["initiative_id"])])], [[[1, "100.00", "150.00", ["i-1", "i-2", "i-3"]], [2, "100.00", "80.00", ["i-1", "i-2"]]]]);
}
world("one initiative claiming a key twice is not an overlap; a null key never overlaps");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1"), ini("i-2")], scenario_versions: [sc("s-1", ["i-1", "i-2"], "0.000000", "annual", 3)],
    benefit_items: [ben("b-1", "i-1", "cash", "100.00", 1, null, null, null, "K"), ben("b-2", "i-1", "revenue", "100.00", 1, null, null, null, "K"), ben("b-3", "i-1", "cash", "70.00", 2, null, null, null, null), ben("b-4", "i-2", "cash", "70.00", 2, null, null, null, null)] }));
  const dc = r.metrics["scenarios"]["s-1"].double_count;
  eq("residual 0.00, no overlaps, no explanation needed", [dc.residual, dc.overlaps, dc.explanation_required, dc.planned_benefits], ["0.00", [], false, "340.00"]);
}
// ------------------------------------------------------------------------------------------------------------------------ 16-19. empty, zero denominators, people
world("an empty population");
{
  const r = run(world0());
  eq("everything null or zero by contract: empty_population, no scenarios, summary nulls", [r.emptyPopulation, goldenOf(r)["empty_population"], r.metrics["summary"]], [true, true, { summary_scenario_id: null, initiatives: 0, scenarios: 0, npv_total: null, npv_sum_of_initiatives: null, double_counted_amount: null, double_counted_pv: null, double_count_residual: null, hours_residual: null, adoption_rate: null, training_completion: null, risk_exposure_total: null, capacity_released_hours_total: null, capacity_released_hours_double_counted: null }]);
}
world("zero eligible, no training, an unmatched rule and an impossible count");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini(), ini("i-2")], adoption_observations: [ad("ad-1", "i-1", 0, 0, "2027-03-31T00:00:00Z"), ad("ad-2", "i-2", 10, 4, "2027-03-31T00:00:00Z", "elig-v2"), ad("ad-3", "i-2", 10, 11, "2027-03-31T00:00:00Z"), ad("ad-4", "i-2", 10, 4, "2027-03-31T00:00:00Z")] }));
  eq("a rule version that is not the initiative's, and adopted > eligible, are refused with their reasons", [rej(r), r.ingest.rejected.map((x) => x.details)], [[["adoption_observations", "ad-2", "ELIGIBILITY_RULE_MISMATCH"], ["adoption_observations", "ad-3", "ADOPTED_EXCEEDS_ELIGIBLE"]], [{ initiative_rule: "elig-v1", row_rule: "elig-v2" }, { eligible: 10, numerator: 11 }]]);
  const m = r.metrics["initiatives"];
  eq("0 eligible: rate null (not 0), the count is 0; no training record: null, and 'differs' is unknown, not false", [m["i-1"].adoption.adoption_rate, m["i-1"].adoption.eligible_count, m["i-1"].training.training_completion, m["i-1"].training.differs_from_adoption, m["i-2"].adoption.adoption_rate], [null, 0, null, null, "0.400000"]);
  eq("the pooled summary skips the initiative with no eligible population: 4 of 10 = 0.400000; training pooled is null", [r.metrics["summary"]["adoption_rate"], r.metrics["summary"]["training_completion"]], ["0.400000", null]);
}
// ------------------------------------------------------------------------------------------------------------------------ 20. forecasts
world("a forecast revised, the original kept, a repeat refused");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], forecast_versions: [fc("i-1", 1, 1, "600.00"), fc("i-1", 1, 2, "600.00"), fc("i-1", 2, 1, "480.00", "2027-02-15T00:00:00Z"), fc("i-1", 2, 2, "500.00", "2027-02-15T00:00:00Z"), { ...fc("i-1", 2, 2, "1.00", "2027-03-15T00:00:00Z"), forecast_id: "f-dup" }, fc("i-1", 3, 1, "400.00", "2029-01-01T00:00:00Z")] }));
  const f = r.metrics["initiatives"]["i-1"].forecast;
  eq("the repeat of (version 2, period 2) is refused VERSION_EXISTS naming the first", [rej(r), r.ingest.rejected[0]!.details], [[["forecast_versions", "f-dup", "VERSION_EXISTS"]], { existing_id: "f-i-1-2-2", version_number: 2 }]);
  eq("version 1 is untouched (1200.00), version 2 is 980.00, latest minus original -220.00; a version dated after as-of does not exist yet", [f.versions.map((v: Row) => [v["version_number"], v["total"]]), f.latest_minus_original, f.original_preserved, f.latest_version], [[[1, "1200.00"], [2, "980.00"]], "-220.00", true, 2]);
}
// ------------------------------------------------------------------------------------------------------------------------ 21. realisation
// Annual periods, as-of 2028-06-30: periods 0 and 1 are matured (they end 2027-01-01 and 2028-01-01), period 2 is not.
world("realisation: matured only, within one type, nothing unobserved counted as zero");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1", 0)], scenario_versions: [sc("s-1", ["i-1"], "0.100000", "annual", 3)],
    benefit_items: [ben("b-1", "i-1", "cash", "100.00", 0, null, null, null, null, "10.00"), ben("b-4", "i-1", "cash", "50.00", 1), ben("b-5", "i-1", "cash", "70.00", 2), ben("b-3", "i-1", "revenue", "0.00", 1), ben("b-6", "i-1", "capacity", "40.00", 0)],
    benefit_observations: [bo("bo-1", "b-1", "80.00", "2027-02-01T00:00:00Z"), bo("bo-5", "b-5", "60.00", "2028-02-01T00:00:00Z"), bo("bo-3", "b-3", "5.00", "2028-02-01T00:00:00Z"), bo("bo-6", "b-6", "30.00", "2027-02-01T00:00:00Z"), bo("bo-late", "b-1", "999.00", "2029-01-01T00:00:00Z")] }));
  const re = blk(r).benefit_realization;
  eq("cash: only b-1 is comparable (planned 100.00, observed 80.00, 0.800000); b-4 is matured and unobserved, listed not zero; b-5 is not matured", [re.cash.comparable_items, re.cash.planned_comparable, re.cash.observed_comparable, re.cash.realization, re.cash.matured_unobserved_items, blk(r).immature_observation_ids], [["b-1"], "100.00", "80.00", "0.800000", ["b-4"], ["bo-5"]]);
  eq("the reading dated after as-of does not exist yet; the trend 10.00 sits beside the raw change: above trend 70.00; labelled observed, not attributed", [re.cash.baseline_trend, re.cash.observed_above_trend, re.cash.attribution], ["10.00", "70.00", "observed, not attributed"]);
  eq("revenue: planned 0 gives a null realisation (not 0, not infinity) while the observed 5.00 is kept; capacity is its own type in hours (30 of 40 = 0.750000)", [re.revenue.realization, re.revenue.observed_comparable, re.capacity.unit, re.capacity.realization], [null, "5.00", "hours", "0.750000"]);
}
// ------------------------------------------------------------------------------------------------------------------------ 22-23. ramps
// ramp [0.5, 1] from each row's own starts_period 1; rows in periods 1, 2, 3 of 100: 50 + 100 + 100 = 250 ramped (last value held), 300 unramped. r=0, no cost.
world("a ramp indexed from the row's own start, the last value held; a decreasing ramp refused");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], assumption_versions: [asm("a-ramp", "i-1", "adoption_ramp", 1, null, ["0.500000", "1.000000"])], scenario_versions: [sc("s-1", ["i-1"], "0.000000", "annual", 4)],
    benefit_items: [ben("b-1", "i-1", "cash", "100.00", 1, 1), ben("b-2", "i-1", "cash", "100.00", 2, 1), ben("b-3", "i-1", "cash", "100.00", 3, 1)] }));
  eq("ramped 250.00 beside unramped 300.00; per-period flows 0, 50, 100, 100; the unramped plan stays visible", [blk(r).planned_money_benefits, blk(r).cash_flow.map((x: Row) => x["net_cash_flow"]), blk(r).unramped_net_cash_flow, blk(r).ramp], [{ ramped: "250.00", unramped: "300.00" }, ["0.00", "50.00", "100.00", "100.00"], ["0.00", "100.00", "100.00", "100.00"], { assumption_id: "a-ramp", values: ["0.500000", "1.000000"] }]);
  const bad = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], assumption_versions: [asm("a-ramp", "i-1", "adoption_ramp", 1, null, ["0.800000", "0.500000"]), asm("a-ramp2", "i-1", "adoption_ramp", 2, null, ["0.5", "1.5"])] }));
  eq("a ramp that falls, or leaves [0, 1], is refused INVALID_RAMP", rej(bad), [["assumption_versions", "a-ramp", "INVALID_RAMP"], ["assumption_versions", "a-ramp2", "INVALID_RAMP"]]);
}
// ------------------------------------------------------------------------------------------------------------------------ 24. cost variance
// recurring planned 100 for [0, 3) under baseline v1; actual 130 in period 0 and 90 in period 1; as-of 2028-06-30 -> 2 matured periods: planned 200, actual 220, variance +20.
world("cost variance over matured periods only; null without an approved baseline");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1"), ini("i-2", 1, null)], process_baselines: [pb("i-1")], scenario_versions: [sc("s-1", ["i-1", "i-2"], "0.100000", "annual", 3)],
    cost_items: [cost("c-1", "i-1", "ck-p", "recurring", "100.00", null, 0, 3, "planned", "v1"), cost("c-2", "i-1", "ck-a1", "one_time", "130.00", 0, null, null, "actual"), cost("c-3", "i-1", "ck-a2", "one_time", "90.00", 1, null, null, "actual"), cost("c-4", "i-2", "ck-p", "one_time", "50.00", 0)] }));
  eq("planned 200.00 (two matured periods of three), actual 220.00, variance 20.00 over [0, 2)", blk(r).cost_variance, { window: { from_period: 0, to_period: 2 }, baseline_version: "v1", approved_baseline_cost: "200.00", actual_cost: "220.00", variance: "20.00", reason: null });
  eq("no approved baseline: every figure null with the reason", blk(r, "s-1", "i-2").cost_variance, { window: { from_period: 0, to_period: 2 }, baseline_version: null, approved_baseline_cost: null, actual_cost: null, variance: null, reason: "NO_APPROVED_BASELINE" });
}
world("capacity released needs an approved baseline and a target");
{
  const w = world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1"), ini("i-2", 1, null), ini("i-3")], process_baselines: [pb("i-1"), pb("i-2"), pb("i-3")], assumption_versions: [asm("a-t1", "i-1", "target_minutes_per_case", 1, "8"), asm("a-t2", "i-2", "target_minutes_per_case", 1, "8")], scenario_versions: [sc("s-1", ["i-1", "i-2", "i-3"])] });
  const r = run(w);
  eq("40.0000 h = 1200 x (10 - 8) / 60; no approved baseline -> null (NO_APPROVED_BASELINE); a baseline with no target -> NO_TARGET_ASSUMPTION", ["i-1", "i-2", "i-3"].map((i) => [blk(r, "s-1", i).capacity_released.hours, blk(r, "s-1", i).capacity_released.reason]), [["40.0000", null], [null, "NO_APPROVED_BASELINE"], [null, "NO_TARGET_ASSUMPTION"]]);
  const dec = run({ ...w, assumption_versions: [asm("a-t1", "i-1", "target_minutes_per_case", 1, "8.5")] });
  eq("a decimal target is exact: 1200 x 1.5 / 60 = 30.0000", blk(dec, "s-1", "i-1").capacity_released.hours, "30.0000");
}
// ------------------------------------------------------------------------------------------------------------------------ 25. readiness
// awareness 3 then 5 (the later wins); desire 2 weight 3; ability 1 and 4 at the same instant (the later id wins) -> (5 + 6 + 4) / (1 + 3 + 1) = 3.
world("readiness: the latest per dimension, ties by id, incomplete sets, null");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { stakeholder_groups: [grp("g-1"), grp("g-2", "Branch tellers")], readiness_assessments: [ra("ra-1", "g-1", "awareness", 3, "1.00", "2027-01-01T00:00:00Z"), ra("ra-2", "g-1", "awareness", 5, "1.00", "2027-02-01T00:00:00Z"), ra("ra-3", "g-1", "desire", 2, "3.00"), ra("ra-4", "g-1", "ability", 1), ra("ra-5", "g-1", "ability", 4), ra("ra-9", "g-1", "knowledge", 1, "1.00", "2029-01-01T00:00:00Z")] }));
  const g = r.metrics["groups"];
  eq("g-1: score 3.0000 (exact 3) from three dimensions, labelled an assessment, not a probability; a reading after as-of is ignored", [g["g-1"].readiness_score, g["g-1"].readiness_exact, g["g-1"].dimensions_assessed, g["g-1"].label], ["3.0000", "3", 3, "assessment, not a probability"]);
  eq("g-2 has nothing assessed: null, not 0", [g["g-2"].readiness_score, g["g-2"].dimensions], [null, []]);
  const w2 = run(world0("annual", "2028-06-30T00:00:00Z", { stakeholder_groups: [grp("g-1")], readiness_assessments: [ra("ra-1", "g-1", "awareness", 4, "1.00"), ra("ra-2", "g-1", "desire", 1, "2.00")] }));
  eq("an incomplete set is allowed: (4 + 2) / 3 = 2.0000", w2.metrics["groups"]["g-1"].readiness_score, "2.0000");
  const bad = run(world0("annual", "2028-06-30T00:00:00Z", { stakeholder_groups: [grp("g-1")], readiness_assessments: [ra("ra-1", "g-1", "awareness", 6), ra("ra-2", "g-1", "mood", 3), ra("ra-3", "g-1", "desire", 3, "0.00")] }));
  eq("a score of 6, an unknown dimension and a zero weight are refused", rej(bad), [["readiness_assessments", "ra-1", "INVALID_SCORE"], ["readiness_assessments", "ra-2", "INVALID_DIMENSION"], ["readiness_assessments", "ra-3", "INVALID_WEIGHT"]]);
}
// ------------------------------------------------------------------------------------------------------------------------ 26. risk
world("risk exposure: probabilities 0 and 1 are inside, 1.5 is not, no items is null");
{
  const rk = (id: string, p: string, impact: string): Row => ({ risk_id: id, initiative_id: "i-1", probability: p, impact, mitigation: "weekly review" });
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini(), ini("i-2")], risk_items: [rk("r-1", "0.000000", "9999.00"), rk("r-2", "1.000000", "100.00"), rk("r-3", "0.250000", "1000.00"), rk("r-4", "1.500000", "5.00")] }));
  eq("0 x 9999 + 1 x 100 + 0.25 x 1000 = 350.00, labelled a scenario estimate; 1.5 refused PROBABILITY_OUT_OF_RANGE; an initiative without items is null", [r.metrics["initiatives"]["i-1"].risk.risk_exposure, r.metrics["initiatives"]["i-1"].risk.label, rej(r), r.metrics["initiatives"]["i-2"].risk.risk_exposure], ["350.00", "scenario estimate", [["risk_items", "r-4", "PROBABILITY_OUT_OF_RANGE"]], null]);
}
// ------------------------------------------------------------------------------------------------------------------------ 27. roadmap chains
// i-1 duration 2 from 0. i-2: FS lag 1 on i-1 -> 0 + 2 + 1 = 3. i-3: SS lag 2 on i-2 -> 3 + 2 = 5 and FS on i-1 -> 2: binding d-2 (5). i-4: d-3 FS lag 1 on i-1 = 3 and d-4 SS lag 0 on i-2 = 3: a tie -> the first by id (d-3).
world("a roadmap chain with finish-to-start, start-to-start, a lag and a tie");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1", 1, "v1", { duration_periods: 2 }), ini("i-2"), ini("i-3"), ini("i-4")],
    dependencies: [dep("d-1", "i-2", "i-1", "finish_to_start", 1), dep("d-2", "i-3", "i-2", "start_to_start", 2), dep("d-0", "i-3", "i-1", "finish_to_start", 0), dep("d-3", "i-4", "i-1", "finish_to_start", 1), dep("d-4", "i-4", "i-2", "start_to_start", 0)] }));
  const m = r.metrics["initiatives"];
  eq("feasible starts 0, 3, 5, 3; delays 0, 3, 5, 3; binding d-1, d-2 (not d-0, which gives 2), d-3 (the tie goes to the first id)", ["i-1", "i-2", "i-3", "i-4"].map((i) => [m[i].roadmap.dependency_feasible_start, m[i].roadmap.dependency_delay, m[i].roadmap.binding_dependency_id]), [[0, 0, null], [3, 3, "d-1"], [5, 5, "d-2"], [3, 3, "d-3"]]);
  eq("finish = feasible start + duration; resource-constrained start equals the feasible one and the resource delay is 0 (no levelling)", [m["i-3"].roadmap.finish, m["i-3"].roadmap.resource_constrained_start, m["i-3"].roadmap.resource_delay], [6, 5, 0]);
  const early = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1"), { ...ini("i-2"), requested_start_period: 9 }], dependencies: [dep("d-1", "i-2", "i-1")] }));
  eq("delay is never negative: a prerequisite that allows an earlier start than requested leaves the requested start (9) and delay 0", [early.metrics["initiatives"]["i-2"].roadmap.dependency_feasible_start, early.metrics["initiatives"]["i-2"].roadmap.dependency_delay], [9, 0]);
}
// ------------------------------------------------------------------------------------------------------------------------ 28. statuses
world("there is no funded status");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1", 1, "v1", { status: "funded" }), ini("i-2")], scenario_versions: [sc("s-1", ["i-2"], "0.100000", "annual", 3, [], null, "funded"), sc("s-2", ["i-2"], "0.1", "annual", 3), sc("s-3", ["i-2"], "0.100000", "annual", 3, [], null, "proposed")] }));
  eq("an initiative or a scenario with status funded is refused STATUS_NOT_ALLOWED; a rate written 0.1 is a valid decimal and a proposed scenario is allowed", [rej(r)], [[["initiatives", "i-1", "STATUS_NOT_ALLOWED"], ["scenario_versions", "s-1", "STATUS_NOT_ALLOWED"]]]);
  eq("a proposed scenario keeps its status and a draft is not changed by anything", [Object.keys(r.metrics["scenarios"]), r.metrics["scenarios"]["s-3"].status, r.metrics["scenarios"]["s-2"].status], [["s-2", "s-3"], "proposed", "draft"]);
}
// ------------------------------------------------------------------------------------------------------------------------ 29-30. horizon and rate zero
world("a benefit beyond the horizon, and a zero rate");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], scenario_versions: [sc("s-1", ["i-1"], "0.000000", "annual", 3)], cost_items: [cost("c-1", "i-1", "ck", "one_time", "300.00", 0)], benefit_items: [ben("b-1", "i-1", "cash", "200.00", 1), ben("b-2", "i-1", "cash", "5000.00", 5), ben("b-3", "i-1", "cash", "200.00", 2)] }));
  eq("the period-5 row is listed as beyond the horizon and is not in the NPV; at r = 0 the NPV is the plain sum -300 + 200 + 200 = 100; every discount factor is 1", [blk(r).excluded_from_cash_flow.beyond_horizon, blk(r).npv.value, blk(r).cash_flow.map((x: Row) => x["discount_factor_exact"])], [["b-2"], "100.00", ["1", "1", "1"]]);
  eq("paybacks at r = 0 coincide: cumulative -300, -100, 100 -> period 2, 1 + 100/200 = 1.5000", [blk(r).payback.simple, blk(r).payback.discounted], [{ period: 2, interpolated: "1.5000", reason: null }, { period: 2, interpolated: "1.5000", reason: null }]);
}
// ------------------------------------------------------------------------------------------------------------------------ 31. instants
world("instants sort as instants, not as strings");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1", 0)], scenario_versions: [sc("s-1", ["i-1"], "0.100000", "annual", 3)], benefit_items: [ben("b-1", "i-1", "cash", "100.00", 0)],
    benefit_observations: [bo("bo-1", "b-1", "70.00", "2027-02-01T00:00:00.5Z"), bo("bo-2", "b-1", "60.00", "2027-02-01T00:00:00Z")] }));
  // as strings "...00.5Z" < "...00Z" ('.' < 'Z'); as instants 00Z is earlier, so the .5 reading (70.00) is the latest.
  eq("the later instant (…00.5Z) wins although it sorts first as text: observed 70.00", blk(r).benefit_realization.cash.observed_comparable, "70.00");
}
// ------------------------------------------------------------------------------------------------------------------------ 32. windows
world("half-open windows: the start is in, the end is out; the dated model is not windowed");
{
  const w = world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1")], scenario_versions: [sc("s-1", ["i-1"], "0.100000", "annual", 3)],
    adoption_observations: [ad("ad-1", "i-1", 100, 10, "2027-03-31T00:00:00Z"), ad("ad-2", "i-1", 100, 40, "2027-06-30T00:00:00Z"), ad("ad-3", "i-1", 100, 70, "2027-09-30T00:00:00Z")] });
  const at = (lo: string | null, hi: string | null) => { const rr = runPipeline(w, undefined, [lo ? parseTs(lo) : null, hi ? parseTs(hi) : null]); return [rr.metrics["initiatives"]["i-1"].adoption.series.map((s: Row) => s["observation_id"]), rr.warnings.map((x) => x["code"])]; };
  eq("[2027-03-31, 2027-09-30): ad-1 (the start) and ad-2 are in, ad-3 (the end) is out; MODEL_NOT_WINDOWED is said", at("2027-03-31T00:00:00Z", "2027-09-30T00:00:00Z"), [["ad-1", "ad-2"], ["MODEL_NOT_WINDOWED"]]);
  eq("an empty window [x, x) holds nothing; with no bounds there is no window and no warning", [at("2027-06-30T00:00:00Z", "2027-06-30T00:00:00Z"), at(null, null)], [[[], ["MODEL_NOT_WINDOWED"]], [["ad-1", "ad-2", "ad-3"], []]]);
}
// ------------------------------------------------------------------------------------------------------------------------ 33. malformed records
world("malformed records: floats, too many decimals, exponents, missing and null fields, non-objects");
{
  const bad: Row[] = [{ ...cost("c-1", "i-1", "ck", "one_time", "1000.00", 0), amount: 1000 }, { ...cost("c-2", "i-1", "ck2", "one_time", "1.1234567", 0) }, cost("c-3", "i-1", "ck3", "one_time", "1e3", 0), (() => { const c = cost("c-4", "i-1", "ck4", "one_time", "5.00", 0); delete (c as Row)["cost_key"]; return c; })(), { ...cost("c-5", "i-1", "ck5", "one_time", "5.00", 0), cost_type: null }, cost("c-6", "i-1", "ck6", "one_time", "123456789012345.00", 0), cost("c-7", "i-1", "ck7", "one_time", "-0.50", 0)];
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini()], cost_items: [...bad, "not a record" as unknown as Row] }));
  eq("a number, 7 decimals, an exponent, a missing key, a null, 15 integer digits: each MALFORMED_RECORD with the failing field; a negative amount is INVALID_AMOUNT; nothing is dropped silently", [r.ingest.rejected.map((x) => [x.reason_code, Object.keys((x.details["fields"] ?? {}) as object)]), r.ingest.rejected.length], [[["MALFORMED_RECORD", ["amount"]], ["MALFORMED_RECORD", ["amount"]], ["MALFORMED_RECORD", ["amount"]], ["MALFORMED_RECORD", ["cost_key"]], ["MALFORMED_RECORD", ["cost_type"]], ["MALFORMED_RECORD", ["amount"]], ["INVALID_AMOUNT", []], ["MALFORMED_RECORD", ["$"]]], 8]);
}
// ------------------------------------------------------------------------------------------------------------------------ 34. keys, duplicates and cascades
world("duplicate ids, unknown and dependent-rejected parents");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1", 1, "v1", { status: "funded" }), ini("i-2"), ini("i-2")], cost_items: [cost("c-1", "i-1", "ck", "one_time", "10.00", 0), cost("c-2", "i-x", "ck", "one_time", "10.00", 0), cost("c-3", "i-2", "ck", "one_time", "10.00", 0), cost("c-3", "i-2", "ck2", "one_time", "99.00", 0)] }));
  eq("a rejected parent makes its child DEPENDENT_REJECTED; an unknown parent is UNKNOWN_INITIATIVE; the later of two repeats is DUPLICATE_ID and the first is kept", [rej(r), r.population.acc.cost_items.map((c) => [c["cost_id"], c["amount"]])], [[["initiatives", "i-1", "STATUS_NOT_ALLOWED"], ["initiatives", "i-2", "DUPLICATE_ID"], ["cost_items", "c-1", "DEPENDENT_REJECTED"], ["cost_items", "c-2", "UNKNOWN_INITIATIVE"], ["cost_items", "c-3", "DUPLICATE_ID"]], [["c-3", "10.00"]]]);
}
// ------------------------------------------------------------------------------------------------------------------------ 35. labels
world("stakeholder labels must be synthetic");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { stakeholder_groups: [grp("g-1", "Jo Smith <jo@example.com>"), grp("g-2", "Call 555 123 4567 desk"), grp("g-3", "Branch tellers 2026"), { ...grp("g-4"), affected_count: -1 }] }));
  eq("an e-mail and a 10-digit number are refused LABEL_NOT_SYNTHETIC; a year in a label and a role are accepted; a negative count is INVALID_COUNT", rej(r), [["stakeholder_groups", "g-1", "LABEL_NOT_SYNTHETIC"], ["stakeholder_groups", "g-2", "LABEL_NOT_SYNTHETIC"], ["stakeholder_groups", "g-4", "INVALID_COUNT"]]);
}
// ------------------------------------------------------------------------------------------------------------------------ 36-37. monthly periods and half-open expansion
// Monthly, as-of 2026-03-01T00:00:00Z: periods 0 (Jan) and 1 (Feb) have ended (Feb ends exactly at the as-of: equal counts), March has not.
world("monthly periods: a period ending exactly at the as-of is matured; a recurring cost expands over [start, end)");
{
  const r = run(world0("monthly", "2026-03-01T00:00:00Z", { initiatives: [ini("i-1", 0)], process_baselines: [pb("i-1")], scenario_versions: [sc("s-1", ["i-1"], "0.000000", "monthly", 4)],
    cost_items: [cost("c-1", "i-1", "ck-r", "recurring", "10.00", null, 1, 4, "planned", "v1"), cost("c-2", "i-1", "ck-a", "one_time", "25.00", 1, null, null, "actual"), cost("c-3", "i-1", "ck-bad", "recurring", "10.00", null, 3, 3)] }));
  eq("[1, 4) gives periods 1, 2, 3 (three rows, not four); an empty range is INVALID_PERIOD", [blk(r).expanded_planned_costs.map((x: Row) => x["period_index"]), rej(r)], [[1, 2, 3], [["cost_items", "c-3", "INVALID_PERIOD"]]]);
  eq("variance over [0, 2): planned 10.00 (only period 1 is inside), actual 25.00, +15.00; month starts 2026-01-01 .. 2026-04-01", [blk(r).cost_variance.window, blk(r).cost_variance.variance, blk(r).cash_flow.map((x: Row) => x["period_start"])], [{ from_period: 0, to_period: 2 }, "15.00", ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]]);
}
// ------------------------------------------------------------------------------------------------------------------------ 38. the Validator on one new row (the roadmap edits' engine)
world("the validator checks one new row without changing anything");
{
  const r = run(world0("annual", "2028-06-30T00:00:00Z", { initiatives: [ini("i-1"), ini("i-2")], dependencies: [dep("d-1", "i-2", "i-1")] }));
  const v = new Validator(r.population);
  const before = r.population.acc.dependencies.length;
  const bad = v.check("dependencies", dep("d-2", "i-1", "i-2"));
  const good = v.check("dependencies", dep("d-3", "i-1", "i-2", "start_to_start", 1));
  eq("closing the loop is refused with the cycle; check() never records; a repeat of an existing id is a DUPLICATE_ID", [bad?.reason_code, bad?.details["cycle"], v.check("dependencies", dep("d-1", "i-2", "i-1"))?.reason_code, r.population.acc.dependencies.length === before], ["DEPENDENCY_CYCLE", ["i-1", "i-2", "i-1"], "DUPLICATE_ID", true]);
  eq("(the cycle check is on the rows accepted so far: d-3 would also close the loop)", good?.reason_code, "DEPENDENCY_CYCLE");
}

if (failures) { console.log(`FAILED (${failures} of ${checks} checks, ${worlds} worlds)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks in ${worlds} worlds)`);
