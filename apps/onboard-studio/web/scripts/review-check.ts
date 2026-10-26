// Regression checks for the master-18 reviewer findings that live in the TypeScript domain (docs/contracts.md D-06, D-09):
//   Q-03 exact ties (mean of 150 cases = 0.00005 h rounds half-up to 0.0001), overlapping waits merge,
//   Q-04 the LATEST document version decides completion and completeness,
//   Q-05 a calendar without working intervals leaves the case "unevaluated" (same as Python and SQL).
// The expected literals are the values the Python domain returns for the same inputs (tests/test_review_findings.py).
import { readFileSync } from "node:fs";
import { runPipeline } from "../src/domain/pipeline";
import type { PipelineInputs } from "../src/domain/types";

const GOLDEN = new URL("../../tests/fixtures/golden/inputs.json", import.meta.url);
const golden = (): any => JSON.parse(readFileSync(GOLDEN, "utf8"));

let failures = 0, checks = 0;
function expectEq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`); }
}
const R = "customer_info_requested";

// ---- Q-04: v1 accepted, v2 rejected (or only submitted) -------------------------------------------
function withV2(status: string): any {
  const d = golden();
  const v1 = d.document_versions[0];
  d.document_versions.push({ ...v1, document_version_id: "doc-002", version_number: 2, review_status: status,
    submitted_at: "2026-03-09T09:36:00Z", reviewed_at: "2026-03-09T09:38:00Z", content_hash: "sha256:" + "0".repeat(63) + "2" });
  return d;
}
for (const status of ["rejected", "submitted"]) {
  const r = runPipeline(withV2(status) as PipelineInputs);
  expectEq(`Q-04 ${status} v2 after accepted v1: the completed case is rejected MISSING_REQUIRED_DOCUMENT`,
    r.rejected.filter((x) => x.entity === "cases").map((x) => [x.id, x.reason_code]), [["case-001", "MISSING_REQUIRED_DOCUMENT"]]);
  expectEq(`Q-04 ${status} v2: no completed eligible case`, r.metrics.completed_eligible_cases, 0);
}
{
  const open = (d: any): any => {
    d.cases[0].status = "open"; d.cases[0].completed_at = null;
    d.case_events = d.case_events.filter((e: any) => e.event_type !== "case_completed");
    return d;
  };
  expectEq("Q-04 completeness with only v1 accepted is 1", runPipeline(open(golden())).metrics.document_completeness, "1.000000");
  const rej = open(withV2("rejected"));
  expectEq("Q-04 completeness: v1 accepted, v2 rejected is 0 (was 1)", runPipeline(rej).metrics.document_completeness, "0.000000");
  rej.document_versions[1].review_status = "accepted";
  expectEq("Q-04 completeness: v1 accepted, v2 accepted is 1", runPipeline(rej).metrics.document_completeness, "1.000000");
}

// ---- Q-05: calendar with no working interval ------------------------------------------------------
const holiday = { calendar_interval_id: "h", calendar_id: "cal-001", starts_at: "2026-03-02T00:00:00Z", ends_at: "2026-03-03T00:00:00Z", timezone: "UTC", kind: "holiday" };
for (const [label, cal] of [["no intervals", []], ["only a holiday", [holiday]]] as const) {
  const d = golden(); d.calendar_intervals = cal;
  const r = runPipeline(d as PipelineInputs, "pause_eligible");
  expectEq(`Q-05 ${label}: unevaluated 1, flag SLA_UNEVALUATED_NO_WORKING_TIME`, [r.sla_unevaluated_cases, r.flags.map((f) => f.flag)], [1, ["SLA_UNEVALUATED_NO_WORKING_TIME"]]);
  expectEq(`Q-05 ${label}: excluded from the denominator (0 completed, 0 within, null attainment)`,
    [r.metrics.completed_eligible_cases, r.metrics.within_sla_cases, r.metrics.sla_attainment], [0, 0, null]);
  expectEq(`Q-05 ${label}: no durations`, [r.metrics.business_cycle_time_hours, r.metrics.active_elapsed_hours], [null, null]);
}
expectEq("Q-05 the golden calendar has no unevaluated case", runPipeline(golden() as PipelineInputs, "pause_eligible").sla_unevaluated_cases, 0);

// ---- Q-03 (TS side): exact tie and merged overlapping waits ---------------------------------------
function bare(cases: [string, string][], waits: [string, string][] = []): PipelineInputs {
  const d = golden(); const tmpl = d.cases[0];
  d.cases = cases.map(([o, c], i) => ({ ...tmpl, case_id: `c${i}`, opened_at: o, completed_at: c, status: "completed" }));
  for (const k of ["step_instances", "assignments", "approvals", "case_events", "document_versions"]) d[k] = [];
  d.waiting_intervals = waits.map(([s, e], j) => ({ waiting_interval_id: `w${j}`, case_id: "c0", reason_code: R, starts_at: s, ends_at: e }));
  d.workflow_requirements = {};
  for (const s of d.step_definitions) s.required = false;
  return d as PipelineInputs;
}
{
  const cs: [string, string][] = [];
  [7, 7, 7, 4, 1, 1, ...Array(144).fill(0)].forEach((secs: number, i: number) => {
    const o = Date.UTC(2026, 2, 2 + (i % 4), 9 + (Math.floor(i / 4) % 8), Math.floor(i / 32) * 5);
    const iso = (t: number) => new Date(t).toISOString().replace(".000Z", "Z");
    cs.push([iso(o), iso(o + secs * 1000)]);
  });
  const m = runPipeline(bare(cs), "pause_eligible").metrics;
  expectEq("Q-03 150-case tie: mean 0.00005 h rounds half-up to 0.0001", [m.completed_eligible_cases, m.calendar_cycle_time_hours], [150, "0.0001"]);
}
{
  const m = runPipeline(bare([["2026-03-02T09:00:00Z", "2026-03-02T17:00:00Z"]],
    [["2026-03-02T10:00:00Z", "2026-03-02T12:00:00Z"], ["2026-03-02T11:00:00Z", "2026-03-02T13:00:00Z"]]), "pause_eligible").metrics;
  expectEq("Q-03 overlapping waits merge: paused 3 h, active 5 h", [m.paused_time_hours, m.active_elapsed_hours], ["3.0000", "5.0000"]);
}

console.log(failures === 0 ? `ALL OK (${checks} checks)` : `${failures} MISMATCH of ${checks} checks`);
process.exitCode = failures === 0 ? 0 : 1;
