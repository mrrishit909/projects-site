// Regression checks for the independent review A-031 (findings R4-01 .. R4-18; decisions in docs/contracts.md D-09).
// TypeScript twin of tests/test_review_findings.py: the same cases, the same expected values. The Python domain's answers
// for the same cases are asserted in that file, so the two domains agree through the shared expectations. Run by
// `npm run check` after the golden check.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { computeMetrics, disclosures } from "../src/domain/metrics";
import { replay } from "../src/domain/events";
import { runPipeline } from "../src/domain/pipeline";
import { validateBatch } from "../src/domain/ingest";
import { breakFlags } from "../src/domain/diagnostics";
import { comparePolicies, meanCi95, replicationReport } from "../src/domain/simulation";
import { frac } from "../src/domain/fixed";
import { histories } from "../src/domain/metrics";
import { parseTs } from "../src/domain/time";
import type { PipelineInputs } from "../src/domain/types";

let failures = 0, checks = 0;
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : x));
function eq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 300)} want ${canon(want).slice(0, 300)}`); }
}
const WEB = new URL("../", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

// ---- a tiny world, the TypeScript twin of tests/support_db.py World (minute 0 = 2026-07-06T09:00:00Z) --------------------
const BASE = Date.parse("2026-07-06T09:00:00Z");
const at = (m: number): string => new Date(BASE + Math.round(m * 60) * 1000).toISOString().replace(".000Z", "Z");
class World {
  n = 0;
  d: any;
  constructor(window: [number, number] = [0, 180], cutoffs?: number[]) {
    this.d = {
      contract_version: 1, window_start: at(window[0]), window_end: at(window[1]), backlog_cutoffs: (cutoffs ?? [window[1]]).map(at), abandonable_channels: ["chat", "phone"],
      customers: Array.from({ length: 12 }, (_, i) => ({ customer_id: `c-${i + 1}`, segment: "smb", timezone: "America/New_York", created_at: "2026-01-01T00:00:00Z", synthetic: true })),
      queues: ["q-1", "q-2"].map((q) => ({ queue_id: q, queue_name: q, priority_policy: "fifo_within_priority", calendar_id: "cal-1", active: true })),
      tickets: [], ticket_events: [],
      agents: ["a-1", "a-2"].map((a) => ({ agent_id: a, agent_name: a, timezone: "UTC", employment_type: "full_time", active: true, max_concurrent: 1 })),
      skills: [{ skill_id: "s-1", skill_name: "General", description: null, active: true, created_at: "2026-01-01T00:00:00Z" }],
      agent_skills: ["a-1", "a-2"].map((a) => ({ agent_skill_id: `as-${a}`, agent_id: a, skill_id: "s-1", proficiency: 4, effective_from: "2026-01-01T00:00:00Z" })),
      queue_skills: ["q-1", "q-2"].map((q) => ({ queue_id: q, skill_id: "s-1" })),
      shifts: ["a-1", "a-2"].map((a) => ({ shift_id: `sh-${a}`, agent_id: a, starts_at: at(0), ends_at: at(480), break_minutes: 30 })),
      sla_policies: [["P1", 5, 30], ["P2", 15, 60], ["P3", 30, 120]].map(([p, f, r]) => ({ sla_policy_id: `sla-${p}`, priority: p, first_response_minutes: f, resolution_minutes: r, calendar_id: "cal-1" })),
      surveys: [], simulation_runs: [],
    };
  }
  ticket(tid: string, minute = 0, queue = "q-1", priority = "P2"): string {
    this.n++;
    this.d.tickets.push({ ticket_id: tid, customer_id: `c-${(this.n % 12) + 1}`, queue_id: queue, priority, created_at: at(minute), channel: "email" });
    this.ev(tid, "created", minute, null, null, queue);
    return tid;
  }
  ev(tid: string, type: string, minute: number, actor: string | null | "auto" = "auto", agent: string | null = null, queue: string | null = null): void {
    const a = actor === "auto" ? agent : actor;
    this.d.ticket_events.push({ event_id: `e-${String(this.d.ticket_events.length + 1).padStart(4, "0")}`, ticket_id: tid, event_type: type, occurred_at: at(minute), actor_id: a, queue_id: queue, agent_id: agent });
  }
  serve(tid: string, start: number, end: number | null, agent = "a-1"): void {
    this.ev(tid, "service_started", start, "auto", agent, "q-1");
    this.ev(tid, "replied_human", start, "auto", agent, "q-1");
    if (end !== null) this.ev(tid, "resolved", end, "auto", agent, "q-1");
  }
  data(): PipelineInputs { return JSON.parse(JSON.stringify(this.d)); }
}
const rejectedMap = (r: ReturnType<typeof runPipeline>): Record<string, string> => Object.fromEntries(r.ingest.rejected.map((x) => [`${x.entity}/${x.id}`, x.reason_code]));
const ticketReasons = (r: ReturnType<typeof runPipeline>): Record<string, string> => Object.fromEntries(Object.entries(rejectedMap(r)).filter(([k]) => k.startsWith("tickets/")));

// ---- R4-02: concurrency to a fixed point ---------------------------------------------------------------------------------
{
  const w = new World([0, 180]);
  for (const t of ["t-1", "t-2", "t-A", "t-C", "t-B"]) w.ticket(t, 0);
  w.serve("t-1", 0, 30); w.serve("t-2", 10, 40);
  w.ev("t-A", "service_started", 50, "auto", "a-1"); w.ev("t-A", "replied_human", 50, "auto", "a-1"); w.ev("t-A", "paused", 100, "auto", "a-1");
  w.ev("t-A", "resumed", 150, "auto", "a-2"); w.ev("t-A", "resolved", 170, "auto", "a-2");
  w.serve("t-C", 60, 70); w.serve("t-B", 120, 160, "a-2");
  const r = runPipeline(w.data());
  eq("R4-02 t-C stays accepted: only t-2 and t-A are rejected", ticketReasons(r), { "tickets/t-2": "CONCURRENCY_EXCEEDED", "tickets/t-A": "CONCURRENCY_EXCEEDED" });
  eq("R4-02 arrivals 3 (the hand count)", r.metrics.arrival_count, 3);
  const p = new World([0, 180]); p.ticket("t-1", 0); p.ticket("t-2", 0); p.serve("t-1", 0, 30); p.serve("t-2", 10, 40);
  eq("R4-02 the earlier start still wins without a cascade", ticketReasons(runPipeline(p.data())), { "tickets/t-2": "CONCURRENCY_EXCEEDED" });
}

// ---- R4-03: availability at ingest ----------------------------------------------------------------------------------------
{
  const w = new World([0, 700]);
  w.ticket("t-late", 485); w.serve("t-late", 490, 520); w.ticket("t-ok", 100); w.serve("t-ok", 110, 120);
  const r = runPipeline(w.data());
  eq("R4-03 service outside every shift rejects the ticket", rejectedMap(r)["tickets/t-late"], "SERVICE_OUTSIDE_SHIFT");
  eq("R4-03 its events carry TICKET_REJECTED", Object.entries(rejectedMap(r)).filter(([k]) => !k.startsWith("tickets/")).every(([, v]) => v === "TICKET_REJECTED"), true);
  eq("R4-03 arrivals and handling are the accepted ticket's", [r.metrics.arrival_count, r.metrics.handling_minutes_total], [1, "10.0000"]);
  for (const [start, ok] of [[0, true], [479, true], [480, false], [-1, false]] as const) {
    const x = new World([-10, 700]); x.ticket("t-1", start > 0 ? start - 1 : -5); x.serve("t-1", start, start + 5);
    eq(`R4-03 the shift is half-open: start ${start}`, "tickets/t-1" in rejectedMap(runPipeline(x.data())), !ok);
  }
  const rs = new World([0, 700]);
  rs.ticket("t-1", 0); rs.ev("t-1", "service_started", 400, "auto", "a-1"); rs.ev("t-1", "replied_human", 400, "auto", "a-1");
  rs.ev("t-1", "paused", 470, "auto", "a-1"); rs.ev("t-1", "resumed", 490, "auto", "a-1"); rs.ev("t-1", "resolved", 500, "auto", "a-1");
  eq("R4-03 a resume outside a shift rejects the ticket", rejectedMap(runPipeline(rs.data()))["tickets/t-1"], "SERVICE_OUTSIDE_SHIFT");
  const ns = new World([0, 180]); ns.d.shifts = ns.d.shifts.filter((s: any) => s.agent_id !== "a-1"); ns.ticket("t-1", 0); ns.serve("t-1", 10, 20);
  eq("R4-03 an agent with no shift is unavailable", rejectedMap(runPipeline(ns.data()))["tickets/t-1"], "SERVICE_OUTSIDE_SHIFT");
  // breaks: flag only
  const b = new World([0, 480]); b.ticket("t-1", 0); b.serve("t-1", 110, 120);
  const run = runPipeline(b.data());
  const flags = breakFlags(histories(run.population), [{ break_id: "br-1", agent_id: "a-1", starts_at: at(100), ends_at: at(130) }]);
  eq("R4-03 a service that opens inside a recorded break is flagged, not rejected", [flags.map((f) => [f.ticket_id, f.break_id]), run.metrics.arrival_count], [[["t-1", "br-1"]], 1]);
}

// ---- R4-01 (TypeScript side), R4-15, R4-16 -----------------------------------------------------------------------------------
{
  const w = new World([0, 180]); w.d.shifts = []; w.ticket("t-1", 0);
  const m = runPipeline(w.data()).metrics;
  eq("R4-01 no shift in the window: staffed 0.0000 and occupancy null", [m.staffed_available_minutes, m.agent_occupancy], ["0.0000", null]);
  for (const [first, second, completed] of [["reopened", "resolved", 1], ["resolved", "reopened", 0]] as const) {
    const x = new World([0, 180]); x.ticket("t-1", 0); x.serve("t-1", 5, 20);
    x.ev("t-1", first, 30, "x", first === "resolved" ? "a-1" : null); x.ev("t-1", second, 30, "x", second === "resolved" ? "a-1" : null);
    eq(`R4-15 same instant ${first} then ${second}: completions ${completed}`, runPipeline(x.data()).metrics.completion_count, completed);
  }
  const r = new World([0, 180]); r.ticket("t-1", 0);
  r.ev("t-1", "resumed", 5, "auto", "a-1"); r.ev("t-1", "service_started", 10, "auto", "a-1"); r.ev("t-1", "replied_human", 10, "auto", "a-1"); r.ev("t-1", "resolved", 20, "auto", "a-1");
  const rr = runPipeline(r.data());
  eq("R4-16 a log that opens with resumed is rejected", rejectedMap(rr)["tickets/t-1"], "RESUME_BEFORE_SERVICE");
  eq("R4-16 its events carry TICKET_REJECTED and nothing is counted", [Object.entries(rejectedMap(rr)).filter(([k]) => k.startsWith("ticket_events/")).every(([, v]) => v === "TICKET_REJECTED"), rr.metrics.arrival_count], [true, 0]);
  const ok = new World([0, 180]); ok.ticket("t-1", 0);
  ok.ev("t-1", "service_started", 10, "auto", "a-1"); ok.ev("t-1", "replied_human", 10, "auto", "a-1"); ok.ev("t-1", "paused", 20, "auto", "a-1");
  ok.ev("t-1", "resumed", 40, "auto", "a-1"); ok.ev("t-1", "resolved", 50, "auto", "a-1");
  const okr = runPipeline(ok.data());
  eq("R4-16 a resume after a service start is unaffected", [okr.ingest.rejected.length, okr.metrics.wait_minutes], [0, { "t-1": "10.0000" }]);
}

// ---- R4-17: one parsing rule ------------------------------------------------------------------------------------------------
{
  const mk = () => { const w = new World([0, 180]); w.ticket("t-1", 0); w.serve("t-1", 5, 20); return w.data(); };
  for (const [v, ok] of [[30.0, true], [30, true], [30.5, false], [Number.NaN, false], [true, false], ["30", false]] as const) {
    const d = mk(); d.shifts = [{ shift_id: "sh-x", agent_id: "a-1", starts_at: at(0), ends_at: at(480), break_minutes: v }];
    eq(`R4-17 break_minutes ${String(v)} ${ok ? "accepted" : "refused"}`, validateBatch(d).rejected.length === 0, ok);
  }
  const d = mk(); const evs = d.ticket_events as { occurred_at: string }[]; evs[evs.length - 1]!.occurred_at = "2026-07-06T09:20Z";
  eq("R4-17 an instant without seconds is MALFORMED_RECORD", validateBatch(d).rejected.map((x) => [x.entity, x.reason_code]), [["ticket_events", "MALFORMED_RECORD"]]);
  eq("R4-17 the accepted forms name one instant", [parseTs("2026-07-06T09:20:00Z"), parseTs("2026-07-06T11:20:00+02:00"), parseTs("2026-07-06 09:20:00+00:00")].every((x) => x === parseTs("2026-07-06T09:20:00Z")), true);
  for (const [seed, ok] of [[2 ** 53 - 1, true], [-(2 ** 53 - 1), true], [2 ** 53, false], [2 ** 62, false], [-(2 ** 62), false]] as const) {
    const x = mk(); x.simulation_runs = [{ simulation_id: "s-1", seed, warmup_minutes: 0, policy_version: "p", horizon_minutes: 60, config: { service_minutes: 10, arrivals: [0] } }];
    eq(`R4-17 seed ${seed} ${ok ? "accepted" : "refused"}`, validateBatch(x).rejected.length === 0, ok);
  }
}

// ---- R4-18 and the cutoff edge -----------------------------------------------------------------------------------------------
{
  const r = runPipeline(new World([0, 180]).data());
  eq("R4-18 a calendar other than cal-001 is warned about, once per policy", r.warnings.map((x) => x.code), ["SLA_CALENDAR_IGNORED", "SLA_CALENDAR_IGNORED", "SLA_CALENDAR_IGNORED"]);
  const d = new World([0, 180]).data(); for (const p of d.sla_policies as any[]) p.calendar_id = "cal-001";
  eq("R4-18 cal-001 (24x7) is silent", runPipeline(d).warnings, []);
  const e = new World([0, 60], [60]); e.ticket("t-1", 0); e.serve("t-1", 10, 60); e.ticket("t-3", 60);
  const er = runPipeline(e.data());
  eq("R4-18 documented edge: arrival at the end counts in the backlog, resolution at the end does not", [er.metrics.arrival_count, er.metrics.completion_count, er.metrics.backlog], [1, 0, { [at(60)]: 1 }]);
  eq("R4-18 and the cutoff warning fires", er.warnings.filter((x) => x.code.startsWith("CUTOFF")).map((x) => x.code), ["CUTOFF_AT_OR_AFTER_WINDOW_END"]);
  const inside = new World([0, 60], [59]); inside.ticket("t-1", 0);
  eq("R4-18 a cutoff inside the window is silent", runPipeline(inside.data()).warnings.filter((x) => x.code.startsWith("CUTOFF")), []);
}

// ---- R4-09: reopens over completions as well as arrivals ----------------------------------------------------------------------
{
  const w = new World([100, 300]); w.ticket("t-1", 0); w.serve("t-1", 5, 20); w.ev("t-1", "reopened", 110, "c"); w.serve("t-1", 120, 130);
  const r = runPipeline(w.data());
  const dd = disclosures(r.population, [parseTs(at(100)), parseTs(at(300))], r.histories);
  eq("R4-09 arrived before the window, reopened and completed inside: counted", [r.metrics.arrival_count, r.metrics.completion_count, dd.reopened_tickets, dd.reopen_events, dd.reopened_among_completions], [0, 1, 1, 1, 1]);
  const m = computeMetrics(r.population, [parseTs(at(100)), parseTs(at(300))], [parseTs(at(300))], r.abandonable, r.histories);
  eq("R4-09 resolution is measured from the original arrival (the dormant gap is charged)", m.resolution_minutes, { "t-1": "130.0000" });
  void replay;
}

// ---- R4-11: replications and the paired difference -----------------------------------------------------------------------------
{
  const ref = readJson(new URL("public/reference/simulation-runs.json", WEB)).replications;
  const rows = readJson(new URL("public/data/simulation_runs.json", WEB)).rows as any[];
  eq("R4-11 50 replications per run", ref.count, 50);
  for (const r of rows) eq(`R4-11 ${r.simulation_id}: 50 replications equal the stored Python report`, replicationReport(r.config, r.seed, 50, r.warmup_minutes, r.horizon_minutes), ref.runs[r.simulation_id]);
  const [b, p] = rows;
  const pair = comparePolicies(b.config, p.config, b.seed, 50, b.warmup_minutes, b.horizon_minutes);
  eq("R4-11 baseline vs plus one: same demand path, proposal better, 50 paired replications", [pair.same_demand_paths, pair.proposal_better, pair.paired_replications], [true, true, 50]);
  eq("R4-11 the difference and its interval equal Python's", pair.difference_mean_wait_minutes, ref.paired.baseline_vs_plus_one_agent.difference_mean_wait_minutes);
  eq("R4-11 sim-003 does not share the demand path, by design", ref.paired.baseline_vs_holdout_intensity.same_demand_paths, false);
  const vals = Array.from({ length: 50 }, (_, i) => frac(i));
  const sd = Math.sqrt(Array.from({ length: 50 }, (_, i) => (i - 24.5) ** 2).reduce((a, x) => a + x, 0) / 49);
  eq("R4-11 the 95 % interval uses t = 2.010 at 49 degrees of freedom", Math.abs(Number(meanCi95(vals).ci95_half_width) - 2.010 * sd / Math.sqrt(50)) < 5e-4, true);
}

// ---- R4-12 / R4-13 and the wording the site and docs share --------------------------------------------------------------------------
{
  const man = readJson(new URL("public/data/manifest.json", WEB));
  const r = man.generator.parameters.arrival_realisation;
  eq("R4-13 the manifest records attempt 7 and the discarded ratios", [r.attempt_index, r.discarded_uplift_percent, r.chosen_uplift_percent, r.noise_sd_points], [7, [12.86, 14.58, 22.82, 16.92, 12.69, 22.02, 30.46], 20.1, 4.3]);
  let hashed = "";
  for (const n of Object.keys(man.row_counts).sort()) {
    const rows = readJson(new URL(`public/data/${n}.json`, WEB)).rows;
    const sorted = (v: any): any => (Array.isArray(v) ? v.map(sorted) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v);
    hashed += (JSON.stringify(sorted(rows)).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`));
  }
  eq("R4-13 dataset_hash is unchanged (it covers the entity files only)", createHash("sha256").update(hashed).digest("hex"), "944ef91b3dc17c04c6bb601e0faac94f956d121877de2b9864988cf7c5d5cba4");
  const contracts = readFileSync(new URL("../docs/contracts.md", WEB), "utf8");
  eq("R4-12 the staffed-minutes sentence is corrected", [contracts.includes("(447,450 vs 447,990)"), ["447,450", "447,990", "297,870", "149,640", "447,510"].every((x) => contracts.includes(x))], [false, true]);
  const src = (f: string): string => readFileSync(new URL(`src/${f}`, WEB), "utf8");
  eq("R4-10 the site says wait to first service", [src("views/overview.tsx").includes("Wait to first service, mean"), src("views/tickets.tsx").includes("Wait to first service (min)"), /Wait for service|Mean wait \(min\)/.test(src("views/overview.tsx"))], [true, true, false]);
  eq("R4-09 SLA and overview state the original-arrival basis", [src("views/sla.tsx").includes("original arrival"), src("views/overview.tsx").includes("original arrival")], [true, true]);
  eq("R4-13 the chosen-realisation label is on the case study, overview and SLA pages", [src("views/case-study.tsx"), src("views/overview.tsx"), src("views/sla.tsx")].map((t) => t.includes("RealisationNote")), [true, true, true]);
  eq("R4-14 the simulation page says censored tickets are excluded and counted separately", [src("views/simulation.tsx").includes("excluded from the wait statistics and counted separately"), src("views/simulation.tsx").includes("reported as censored, not dropped")], [true, false]);
}

console.log(failures === 0 ? `REVIEW OK (${checks} checks)` : `${failures} MISMATCH of ${checks} checks`);
process.exitCode = failures === 0 ? 0 : 1;
