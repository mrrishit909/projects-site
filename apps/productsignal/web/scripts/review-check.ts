// Regression checks for the independent review A-051 (findings R6-01 .. R6-14; decisions in docs/contracts.md D-10).
// TypeScript twin of the pure-domain part of tests/test_review_findings.py: the same worlds, the same hand-worked expected values.
// The Python domain's answers for the same cases are asserted in that file, and the SQL reference's in tests/test_review_findings.py
// too, so the three domains agree through the shared expectations. Run by `npm run check` after the golden check.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { Ctx, revenueDifference, segmentAnalysis, week4Difference, type ExperimentOut } from "../src/domain/metrics";
import { canonicalise } from "../src/domain/events";
import { canonicalJson } from "../src/domain/models";
import { runPipeline, type PipelineInputs } from "../src/domain/pipeline";
import { DomainError } from "../src/domain/num";
import { parseTs } from "../src/domain/time";

let failures = 0, checks = 0;
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : typeof x === "bigint" ? x.toString() : x));
function eq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 300)} want ${canon(want).slice(0, 300)}`); }
}
const WEB = new URL("../", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));
const sha = (o: unknown): string => createHash("sha256").update(canonicalJson(o as never)).digest("hex");

// ---- a tiny world, the TypeScript twin of tests/support_db.py World ---------------------------------------------------------------
const PLAN_BODY = {
  experiment_version_id: "xv-001", primary_metric: "activation_7d", unit_type: "account", allocation: { control: "0.500000", treatment: "0.500000" },
  planned_end: "2026-10-15T00:00:00Z", activation_window_days: 7, guardrail: { metric: "product_error_rate", window_days: 7 },
  revenue_window: { from: "2026-10-01T00:00:00Z", to: "2026-10-15T00:00:00Z" }, confidence: "0.95", z: "1.959964",
  srm: { p_threshold: "0.001", min_expected_cell: 5 }, frozen_at: "2026-09-30T12:00:00Z",
};
const iso = (ms: number): string => new Date(ms).toISOString().replace(".000Z", "Z");
const plus = (t: string, ms: number): string => iso(Date.parse(t) + ms);
const MIN = 60_000, HOUR = 3_600_000;
class World {
  n = { ev: 0, ss: 0, sub: 0, as: 0, ex: 0, run: 0 };
  d: any;
  constructor(readonly cutoff = "2026-10-26T00:00:00Z", plan: any = PLAN_BODY) {
    const body = JSON.parse(JSON.stringify(plan));
    this.d = {
      contract_version: 1, as_of: cutoff, cutoff, analysis_plan: { ...body, config_hash: sha(body) },
      metric_windows: {
        signup_conversion: { from: "2026-10-05T00:00:00Z", to: "2026-10-12T00:00:00Z" },
        funnel: { definition_id: "fun-001", version: 1, steps: ["visit", "signup", "onboarding_step_1", "activated"], max_gap_hours: 48, from: "2026-10-05T00:00:00Z", to: "2026-10-12T00:00:00Z" },
        activation: { from: "2026-10-01T00:00:00Z", to: "2026-10-26T00:00:00Z", window_days: 7 },
        retention: { signup_from: "2026-09-14", signup_to: "2026-09-21" },
        feature_adoption: { from: "2026-09-21T00:00:00Z", to: "2026-09-28T00:00:00Z", feature: "export", eligible_plans: ["team", "business"] },
      },
      accounts: [], users: [], identity_links: [], sessions: [], events: [], event_properties: [], subscriptions: [],
      experiment_versions: [{ experiment_version_id: "xv-001", name: "Onboarding checklist", unit_type: "account", primary_metric: "activation_7d", planned_end: body.planned_end }],
      assignments: [], exposures: [], metric_observations: [], analysis_runs: [],
    };
  }
  account(aid: string, tz = "UTC", plan = "team", segment = "smb"): string {
    this.d.accounts.push({ account_id: aid, plan, segment, created_at: "2026-09-01T00:00:00Z", internal: false, timezone: tz });
    this.d.users.push({ user_id: `u-${aid}`, account_id: aid, created_at: "2026-09-01T00:00:00Z", timezone: tz, bot_flag: false });
    return aid;
  }
  event(name: string, at: string, user: string, recv?: string): void {
    this.n.ev++;
    this.d.events.push({ event_id: `ev-${String(this.n.ev).padStart(5, "0")}`, user_id: user, anonymous_id: null, event_name: name, event_at: at, received_at: recv ?? plus(at, 5000) });
  }
  signup(aid: string, at: string): void { this.event("signup", at, `u-${aid}`); }
  activate(aid: string, at: string, recv?: string): void { this.event("activated", at, `u-${aid}`, recv); }
  error(aid: string, at: string): void { this.event("product_error", at, `u-${aid}`); }
  session(aid: string, at: string): void {
    this.n.ss++;
    this.d.sessions.push({ session_id: `s-${String(this.n.ss).padStart(4, "0")}`, user_id: `u-${aid}`, started_at: at, ended_at: plus(at, 10 * MIN), device_type: "web" });
  }
  sub(aid: string, starts: string, amount: string): void {
    this.n.sub++;
    this.d.subscriptions.push({ subscription_id: `sub-${String(this.n.sub).padStart(3, "0")}`, account_id: aid, starts_at: starts, ends_at: null, status: "active", amount_usd: amount });
  }
  assign(aid: string, variant: string, at: string): string {
    this.n.as++;
    const id = `as-${String(this.n.as).padStart(4, "0")}`;
    this.d.assignments.push({ assignment_id: id, experiment_version_id: "xv-001", unit_id: aid, variant, assigned_at: at });
    return id;
  }
  run(cutoff: string, created: string): void {
    this.n.run++;
    this.d.analysis_runs.push({ analysis_id: `an-${String(this.n.run).padStart(3, "0")}`, experiment_version_id: "xv-001", cutoff_at: cutoff, config_hash: this.d.analysis_plan.config_hash, created_at: created });
  }
  arm(variant: string, n: number, activated: number, prefix = variant[0]!, start = "2026-10-01T09:00:00Z"): string[] {
    const ids: string[] = [];
    for (let i = 0; i < n; i++) {
      const aid = this.account(`acc-${prefix}-${String(i + 1).padStart(3, "0")}`);
      const t0 = plus(start, i * MIN);
      this.signup(aid, t0);
      this.assign(aid, variant, plus(t0, MIN));
      if (i < activated) this.activate(aid, plus(t0, 2 * HOUR));
      ids.push(aid);
    }
    return ids;
  }
  logged(): this { this.run(this.cutoff, plus(this.cutoff, 5 * MIN)); return this; }
}
const small = (c: [number, number], t: [number, number], plan: any = PLAN_BODY): World => { const w = new World("2026-10-26T00:00:00Z", plan); w.arm("control", ...c); w.arm("treatment", ...t, undefined, "2026-10-01T11:00:00Z"); return w; };
const exp = (w: World, cutoff?: string): ExperimentOut => runPipeline(w.d as PipelineInputs, cutoff ?? w.cutoff).metrics.experiment!;
const codeOf = (fn: () => unknown): string | null => { try { fn(); return null; } catch (e) { return e instanceof DomainError ? e.code : `other: ${String(e)}`; } };

// ---- R6-01: `conclusive` needs a plan frozen before the first logged run ---------------------------------------------------------
{
  const planI = { ...PLAN_BODY, frozen_at: "2026-10-20T00:00:00Z" };
  const wI = small([100, 10], [100, 40], planI);
  wI.run("2026-10-10T00:00:00Z", "2026-10-10T00:05:00Z"); wI.run("2026-10-26T00:00:00Z", "2026-10-26T00:05:00Z");
  const a = exp(wI);
  eq("R6-01 I_frozen_late: 10/100 vs 40/100, +30.00 pp, the interval excludes 0, a final run with a valid hash", [a.primary.variants["control"]!.activated, a.primary.variants["treatment"]!.activated, a.primary.absolute_lift_pp, a.primary.interval!.includes_zero, a.run.interim, a.run.config_hash_matches_plan], [10, 40, "30.00", false, false, true]);
  eq("R6-01 I_frozen_late: plan_frozen false, so conclusive false (it was true before D-10)", [a.run.plan_frozen, a.primary.conclusive], [false, false]);
  const early = new World("2026-10-26T00:00:00Z", { ...PLAN_BODY, frozen_at: "2026-10-05T00:00:00Z" });
  early.arm("control", 100, 10); early.arm("treatment", 100, 40, undefined, "2026-10-01T11:00:00Z");
  early.run("2026-10-10T00:00:00Z", "2026-10-10T00:05:00Z"); early.run("2026-10-26T00:00:00Z", "2026-10-26T00:05:00Z");
  eq("R6-01 the same data with the plan frozen before the first run is conclusive", [exp(early).run.plan_frozen, exp(early).primary.conclusive], [true, true]);
  const L = new World();
  const lc = L.arm("control", 2, 0), lt = L.arm("treatment", 2, 2, undefined, "2026-10-01T11:00:00Z");
  for (const x of [...lc, ...lt]) L.sub(x, "2026-10-05T00:00:00Z", "10.00");
  const l = exp(L);
  eq("R6-01 L_equal: 0/2 vs 2/2 excludes 0 on a final run, but no run is logged and the sample ratio is INSUFFICIENT: not conclusive", [l.primary.interval!.includes_zero, l.run.interim, l.run.plan_frozen, l.srm.verdict, l.primary.conclusive], [false, false, false, "INSUFFICIENT", false]);
  eq("R6-01 no logged run is a preview, not a conclusive result", [exp(small([100, 20], [100, 40])).primary.conclusive, exp(small([100, 20], [100, 40]).logged()).primary.conclusive], [false, true]);
}

// ---- R6-14: ... and the sample ratio must be OK -----------------------------------------------------------------------------------
{
  const skew = small([100, 20], [100, 40], { ...PLAN_BODY, allocation: { control: "0.700000", treatment: "0.300000" } }).logged();
  const e = exp(skew);
  eq("R6-14 100/100 against 0.7/0.3: MISMATCH 38.095238, the interval excludes 0 on a logged final run, still not conclusive", [e.srm.verdict, e.srm.statistic, e.primary.interval!.includes_zero, e.run.plan_frozen, e.primary.conclusive], ["MISMATCH", "38.095238", false, true, false]);
  const tiny = exp(small([3, 0], [3, 3]).logged());
  eq("R6-14 expected cells of 3 (< 5): INSUFFICIENT, not conclusive", [tiny.srm.verdict, tiny.primary.conclusive], ["INSUFFICIENT", false]);
}

// ---- R6-02: exactly control and treatment ------------------------------------------------------------------------------------------
{
  const H = new World("2026-10-26T00:00:00Z", { ...PLAN_BODY, allocation: { control: "0.500000", treatment: "0.250000", holdout: "0.250000" } });
  H.arm("control", 100, 20); H.arm("treatment", 33, 10, undefined, "2026-10-01T11:00:00Z"); H.arm("holdout", 67, 10, "h", "2026-10-01T13:00:00Z");
  eq("R6-02 H_three: the three-variant plan is a rejection", codeOf(() => runPipeline(H.d as PipelineInputs, H.cutoff)), "VARIANTS_NOT_TWO");
  for (const [name, alloc] of [["a/b", { a: "0.5", b: "0.5" }], ["control only", { control: "1.0" }], ["treatment and holdout", { treatment: "0.5", holdout: "0.5" }]] as const) {
    const w = new World("2026-10-26T00:00:00Z", { ...PLAN_BODY, allocation: alloc });
    eq(`R6-02 ${name}: VARIANTS_NOT_TWO`, codeOf(() => runPipeline(w.d as PipelineInputs, w.cutoff)), "VARIANTS_NOT_TWO");
  }
  eq("R6-02 two variants keep df = 1", exp(small([100, 20], [100, 40])).srm.df, 1);
}

// ---- R6-09: an activation before the assignment is not a treatment outcome ---------------------------------------------------------
{
  const J = new World();
  for (let i = 0; i < 10; i++) {
    const a = J.account(`acc-pre-${i}`);
    J.signup(a, `2026-10-01T0${i}:00:00Z`); J.activate(a, `2026-10-01T0${i}:30:00Z`); J.assign(a, i % 2 ? "treatment" : "control", "2026-10-20T00:00:00Z");
  }
  const j = exp(J);
  eq("R6-09 J_pre_treatment: 5 mature per arm, 0 activated (every activation precedes the assignment)", [j.primary.variants["control"]!.mature_units, j.primary.variants["treatment"]!.mature_units, j.primary.variants["control"]!.activated, j.primary.variants["treatment"]!.activated], [5, 5, 0, 0]);
  eq("R6-09 J_pre_treatment: +0.00 pp, relative lift null; the cohort metric still sees 10 activations", [j.primary.absolute_lift_pp, j.primary.relative_lift, runPipeline(J.d as PipelineInputs, J.cutoff).metrics.activation.activated], ["0.00", null, 10]);
  for (let i = 0; i < 10; i++) J.error(`acc-pre-${i}`, `2026-10-21T0${i}:00:00Z`);
  const g1 = exp(J).guardrail.by_variant;
  eq("R6-09 guardrail: assigned 10-20 + 7 d > cutoff 10-26, so nobody is eligible", [g1["control"], g1["treatment"]], [{ eligible_units: 0, units_with_error: 0, error_rate: null }, { eligible_units: 0, units_with_error: 0, error_rate: null }]);
  const g2 = exp(J, "2026-10-27T00:00:00Z").guardrail.by_variant;
  eq("R6-09 guardrail: the window is complete at 2026-10-27T00:00:00Z (<=)", g2["control"], { eligible_units: 5, units_with_error: 5, error_rate: "1.000000" });
  eq("R6-09 guardrail: one second earlier it is not", exp(J, "2026-10-26T23:59:59Z").guardrail.by_variant["control"]!.eligible_units, 0);

  // the rule at its edges: signup 10-02T00:00:00Z, assigned 10-02T10:00:00Z, window ends 10-09T00:00:00Z
  const edge = (at: string[]): number => {
    const w = new World();
    w.account("acc-e"); w.signup("acc-e", "2026-10-02T00:00:00Z"); w.assign("acc-e", "treatment", "2026-10-02T10:00:00Z");
    for (const t of at) w.activate("acc-e", t);
    const r = exp(w).primary.variants["treatment"]!;
    return r.activated;
  };
  eq("R6-09 edges: at assigned_at, after it, one second before the window ends count; one second before assignment and at +7 d do not",
    [edge(["2026-10-02T10:00:00Z"]), edge(["2026-10-02T10:00:01Z"]), edge(["2026-10-08T23:59:59Z"]), edge(["2026-10-02T09:59:59Z"]), edge(["2026-10-09T00:00:00Z"])], [1, 1, 1, 0, 0]);
  eq("R6-09 edges: an activation before and one after count once", edge(["2026-10-02T01:00:00Z", "2026-10-03T00:00:00Z"]), 1);
}

// ---- R6-03: the 168-h activation window across the end of US daylight time (no session time zone exists in the browser) ------------
{
  const K = new World("2026-11-08T00:00:00Z");
  K.d.metric_windows.activation = { from: "2026-10-25T00:00:00Z", to: "2026-11-08T00:00:00Z", window_days: 7 };
  K.account("k1"); K.signup("k1", "2026-10-31T12:00:00Z"); K.activate("k1", "2026-11-07T12:30:00Z");
  K.account("k2"); K.signup("k2", "2026-11-01T00:30:00Z");
  const a = runPipeline(K.d as PipelineInputs, K.cutoff).metrics.activation;
  eq("R6-03 K_dst_sql: 2 signups, 1 immature, 1 mature, 0 activated (168.5 h is outside the window)", [a.signups, a.immature_excluded, a.mature_accounts, a.activated, a.rate], [2, 1, 1, 0, "0.000000"]);
  const B = new World();
  for (const x of ["acc-m1", "acc-m2", "acc-m3"]) B.account(x);
  B.signup("acc-m1", "2026-10-19T00:00:00Z"); B.activate("acc-m1", "2026-10-26T00:00:00Z", "2026-10-26T00:00:00Z");
  B.signup("acc-m2", "2026-10-19T00:00:01Z"); B.activate("acc-m2", "2026-10-19T01:00:00Z");
  B.signup("acc-m3", "2026-10-19T00:00:00Z"); B.activate("acc-m3", "2026-10-25T23:59:59Z", "2026-10-26T00:00:00Z");
  const b = runPipeline(B.d as PipelineInputs, B.cutoff).metrics.activation;
  eq("R6-03 B_maturity: 3 signups, 1 immature, 2 mature, 1 activated, 0.500000", [b.signups, b.immature_excluded, b.mature_accounts, b.activated, b.rate], [3, 1, 2, 1, "0.500000"]);
}

// ---- R6-13: the Bonferroni family ---------------------------------------------------------------------------------------------------
{
  const w = small([40, 8], [40, 18]);
  w.d.accounts.forEach((a: any, i: number) => { a.segment = ["smb", "mid", "enterprise"][i % 3]; });
  const r = runPipeline(w.d as PipelineInputs, w.cutoff);
  const plan = r.plans.get("xv-001")!, cut = parseTs(w.cutoff, "cutoff");
  const one = segmentAnalysis(r.population, cut, plan, "segment");
  eq("R6-13 default: 3 tested, threshold 0.016667, no family_size", [one.segments_tested, one.bonferroni_threshold, one.family_size], [3, "0.016667", undefined]);
  const fam = segmentAnalysis(r.population, cut, plan, "segment", null, 7);
  eq("R6-13 family of 7: threshold 0.05 / 7 = 0.007143, confidence 0.992857, family_size 7", [fam.segments_tested, fam.family_size, fam.bonferroni_threshold, fam.segments[0]!.adjusted_interval!.confidence], [3, 7, "0.007143", "0.992857"]);
}

// ---- R6-10: the secondary differences, by hand ---------------------------------------------------------------------------------------
{
  const w = new World();
  for (const [arm, n, kept] of [["control", 4, 2], ["treatment", 4, 3]] as const) {
    for (let i = 0; i < n; i++) {
      const a = w.account(`acc-${arm[0]}-${i}`);
      w.signup(a, "2026-08-01T12:00:00Z"); w.assign(a, arm, "2026-08-01T12:01:00Z");
      w.session(a, i < kept ? "2026-08-29T12:00:00Z" : "2026-08-27T12:00:00Z");
    }
  }
  const r = runPipeline(w.d as PipelineInputs, w.cutoff);
  const ctx = new Ctx(r.population, parseTs(w.cutoff, "cutoff"), canonicalise(r.population, parseTs(w.cutoff, "cutoff")), null);
  const d = week4Difference(ctx, r.plans.get("xv-001")!);
  eq("R6-10 week-4: 2 of 4 against 3 of 4, +25.00 pp, Newcombe [-0.319557, 0.655287] includes 0", [d.by_variant["control"], d.by_variant["treatment"], d.difference_pp, d.interval!.low, d.interval!.high, d.interval!.includes_zero],
    [{ retained: 2, mature_units: 4, rate: "0.500000" }, { retained: 3, mature_units: 4, rate: "0.750000" }, "25.00", "-0.319557", "0.655287", true]);
  const v = new World();
  const c = v.arm("control", 3, 0), t = v.arm("treatment", 3, 0, undefined, "2026-10-01T11:00:00Z");
  v.sub(c[2]!, "2026-10-05T00:00:00Z", "30.00");
  ["10.00", "20.00", "30.00"].forEach((amount, i) => v.sub(t[i]!, "2026-10-05T00:00:00Z", amount));
  const rr = runPipeline(v.d as PipelineInputs, v.cutoff);
  const cx = new Ctx(rr.population, parseTs(v.cutoff, "cutoff"), canonicalise(rr.population, parseTs(v.cutoff, "cutoff")), null);
  const rd = revenueDifference(cx, rr.plans.get("xv-001")!);
  eq("R6-10 revenue: means 10.00 and 20.00, +10.00, Welch df 3.2 -> 3, t 3.182446, [-26.75, 46.75]", [rd.by_variant["control"], rd.by_variant["treatment"], rd.difference, rd.interval],
    [{ units: 3, mean: "10.00" }, { units: 3, mean: "20.00" }, "10.00", { confidence: "0.95", df: 3, t: "3.182446", low: "-26.75", high: "46.75", includes_zero: true }]);
}

// ---- R6-08 / R6-10 / R6-11 / R6-12: the published data, the disclosure and the site's wording ------------------------------------------
{
  const man = readJson(new URL("public/data/manifest.json", WEB));
  const dr = Object.fromEntries(man.designed_relationships.map((d: any) => [d.id, d]));
  const gd = dr["DR-01"].realised.instrumentation_gap_disclosure;
  eq("R6-08 the manifest's DR-01 discloses the gap: 11 v1 accounts, 5 control / 6 treatment, 0/5 and 4/6 drawn, +9.50 published, +11.50 drawn, +9.96 without them",
    [gd.v1_gap_accounts, gd.by_arm.control.gap_accounts, gd.by_arm.treatment.gap_accounts, gd.by_arm.control.gap_drawn_activations, gd.by_arm.treatment.gap_drawn_activations, gd.published_lift_pp, gd.drawn_lift_pp, gd.lift_excluding_gap_accounts_pp], [11, 5, 6, 0, 4, "9.50", "11.50", "9.96"]);
  const inj = readJson(new URL("public/data/injection-manifest.json", WEB)).injections.find((i: any) => i.id === "INJ-10");
  eq("R6-08 INJ-10 carries the same disclosure", inj.detail.reaches_the_as_of_read.v1_gap_accounts, 11);
  eq("R6-08 the manifest embeds the injection manifest with it", man.injection_manifest !== undefined, true);
  let hashed = "";
  for (const n of Object.keys(man.row_counts).sort()) {
    const rows = readJson(new URL(`public/data/${n}.json`, WEB)).rows;
    hashed += canonicalJson(rows as never).replace(/[\u007f-￿]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`);
  }
  eq("R6-08 the entity files are untouched: dataset_hash is the manifest's", createHash("sha256").update(hashed).digest("hex"), man.dataset_hash);
  const src = (f: string): string => readFileSync(new URL(`src/${f}`, WEB), "utf8");
  eq("R6-08 the gap note sits beside the by-a-hair note on the result page and the case study", [src("components/experiment.tsx").includes('data-testid="gap-note"'), src("views/result.tsx").includes("GapNote"), src("views/case-study.tsx").includes("<GapNote")], [true, true, true]);
  eq("R6-10 the case study computes the secondary figures and labels the manifest's as cross-checks", [src("views/case-study.tsx").includes("SecondaryFigures"), src("views/case-study.tsx").includes("cross-checks of these figures, not their source")], [true, true]);
  eq("R6-10 the tracking page shows the linked share", src("views/tracking.tsx").includes('data-testid="linked-share"'), true);
  eq("R6-11 the case study states the on-or-after definition and the forward-only identity links", [src("views/case-study.tsx").includes("includes every exact-day-7 account plus the accounts that return only later"), src("views/case-study.tsx").includes("Identity links apply forward only")], [true, true]);
  eq("R6-12 the SRM p-value is read as p < 0.000001 (exact 5.7e-7), never as p = 0.000001", [src("lib/p.ts").includes("p < 0.000001"), src("views/case-study.tsx").includes("pReading(b.srm.statistic, b.srm.p_value)")], [true, true]);
  eq("R6-13 the segments page corrects across every split it offers", src("views/segments.tsx").includes("segmentsFamily"), true);
  const contracts = readFileSync(new URL("../docs/contracts.md", WEB), "utf8");
  eq("D-10 is in docs/contracts.md with every decision", ["## D-10", "VARIANTS_NOT_TWO", "CUTOFF_IN_FUTURE", "BACKFILL_ADMIN_ONLY", "OUTCOME_BEFORE_ASSIGNMENT", "FROZEN_AT_BACKDATED", "PLAN_NOT_FROZEN"].every((x) => contracts.includes(x)), true);
}

console.log(failures === 0 ? `REVIEW OK (${checks} checks)` : `${failures} MISMATCH of ${checks} checks`);
process.exitCode = failures === 0 ? 0 : 1;
