// Adversarial checks of the TypeScript domain on small hand-worked worlds (the pure-domain twin of the contract's edge cases):
// whitespace policy, validity denominators, uniqueness with null keys, null foreign keys, the half-open timeliness deadline and DST,
// the weighted score with unmeasured dimensions, the critical override under a high score, claimed against resolved, canonical pairs,
// reviewer = proposer, precision from the truth only, disabled rules and the observed-edge rule; then the review R7 fixes (D-10): timeliness open windows and
// pending, a disabled critical rule that still fails, non-portable patterns, whitespace characters the engines disagreed about, null keys in the score, empty foreign
// keys, a self-edge and code-point order. Run by `npm run check` after the golden check.
import { runPipeline, goldenOf } from "../src/domain/pipeline";
import { cmp, patternPortable, type Row } from "../src/domain/models";

let failures = 0, checks = 0;
const canon = (v: unknown): string => JSON.stringify(v);
function eq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 300)} want ${canon(want).slice(0, 300)}`); }
}
const WV = [
  { weight_version: "w1", valid_from: "2026-01-01T00:00:00Z", weights: { completeness: "0.400000", validity: "0.300000", uniqueness: "0.200000", relationship: "0.050000", timeliness: "0.050000" } },
  { weight_version: "w2", valid_from: "2026-09-01T00:00:00Z", weights: { completeness: "0.250000", validity: "0.250000", uniqueness: "0.250000", relationship: "0.150000", timeliness: "0.100000" } },
];
const owner = (id: string, role = "steward", active = true, when: string | null = null): Row => ({ owner_id: id, owner_name: id, team: "T", role, active, deactivated_at: when });
const ds = (id: string, o = "o1", extra: Row = {}): Row => ({ dataset_id: id, dataset_name: id, source_system: "s", owner_id: o, classification: "internal", registered_at: "2026-01-01T00:00:00Z", monitored: false, refresh_timezone: null, refresh_local_time: null, refresh_grace_minutes: null, last_refreshed_at: null, ...extra });
const rule = (id: string, d: string, type: string, definition: Row, extra: Row = {}): Row => ({ rule_id: id, dataset_id: d, field_id: null, rule_type: type, severity: "medium", version_number: 1, status: "active", disabled_at: null, disabled_reason: null, definition, ...extra });
const world = (extra: Row): Row => ({ contract_version: 1, as_of: "2026-10-05T00:00:00Z", weight_version: "w2", weight_versions: WV, whitespace_policy: { name: "x", trim_characters: " \t\r\n" },
  checklist_version: "cl-1", checklist_versions: [{ checklist_version: "cl-1", items: ["definition", "grain", "source_fields", "owner", "refresh"] }],
  owners: [owner("o1")], datasets: [], fields: [], quality_rules: [], rule_runs: [], issues: [], lineage_edges: [], metric_versions: [], definition_changes: [], customer_records: [],
  match_candidates: [], merge_decisions: [], dataset_rows: {}, ...extra });
const rows = (n: number, f: (i: number) => Row): Row[] => Array.from({ length: n }, (_, i) => ({ row_id: `r${i + 1}`, ...f(i) }));
const run = (w: Row, wv?: string) => runPipeline(w, undefined, wv);

// whitespace policy: trimmed-empty is missing; the count of whitespace-only values is reported
{
  const w = world({ datasets: [ds("d1")], quality_rules: [rule("c", "d1", "completeness", { field: "e" })], dataset_rows: { d1: rows(6, (i) => ({ e: ["a", null, "", "  ", "\t \t", "b"][i] })) } });
  const b = run(w).metrics["completeness"]["c"];
  eq("whitespace: 6 rows, 4 missing (null, empty, two whitespace-only), 2 whitespace-only reported, completeness 0.333333", [b.missing_count, b.whitespace_only_count, b.populated_count, b.value], [4, 2, 2, "0.333333"]);
  const w2 = world({ ...w, whitespace_policy: { name: "x", trim_characters: "" }, datasets: [ds("d1")], quality_rules: [rule("c", "d1", "completeness", { field: "e" })], dataset_rows: { d1: rows(3, (i) => ({ e: ["a", " ", ""][i] })) } });
  eq("a policy that trims nothing keeps a space as populated, the empty string is still missing", run(w2).metrics["completeness"]["c"].missing_count, 1);
}
// validity: populated-only differs from all-eligible; a non-string value cannot pass; a trailing newline does not satisfy $
{
  const w = world({ datasets: [ds("d1")], quality_rules: [rule("v", "d1", "validity", { field: "e", pattern: "^[a-z]+@x\\.io$" })], dataset_rows: { d1: rows(5, (i) => ({ e: ["a@x.io", "b@x.io\n", null, "", 7][i] })) } });
  const b = run(w).metrics["validity"]["v"];
  eq("validity: 1 of 3 populated passes (a final newline fails, a number fails): populated-only 0.333333, all-eligible 0.200000", [b.populated_count, b.passing_count, b.populated_only.value, b.all_eligible.value], [3, 1, "0.333333", "0.200000"]);
}
// uniqueness: null keys are failures counted separately; first row kept; text compare is exact
{
  const w = world({ datasets: [ds("d1")], quality_rules: [rule("u", "d1", "uniqueness", { field: "k" })], dataset_rows: { d1: rows(7, (i) => ({ k: ["A", "A", "a", null, null, "B", 1][i] })) } });
  const b = run(w).metrics["uniqueness"]["u"];
  eq("uniqueness: keys A,A,a,B,1 -> 5 distinct, 1 group, 1 row beyond the first, 2 null keys; shares 0.200000 and 0.142857", [b.distinct_keys, b.duplicate_groups, b.duplicate_rows, b.null_key_count, b.group_share.value, b.row_share.value], [4, 1, 1, 2, "0.250000", "0.142857"]);
}
// relationship: null foreign keys out of the denominator; a parent with no rows matches nothing
{
  const w = world({ datasets: [ds("p"), ds("c")], quality_rules: [rule("r", "c", "relationship", { field: "fk", parent_dataset_id: "p", parent_field: "k" })],
    dataset_rows: { p: rows(2, (i) => ({ k: `K${i}` })), c: rows(5, (i) => ({ fk: ["K0", "K1", "K9", null, " "][i] })) } });
  const b = run(w).metrics["relationship_integrity"]["r"];
  eq("relationship: 5 keys, 2 null/blank counted separately, 3 eligible, 2 matched, 0.666667", [b.total_fk_count, b.null_fk_count, b.eligible_count, b.matched_count, b.value], [5, 2, 3, 2, "0.666667"]);
  const w0 = world({ ...w, datasets: [ds("p"), ds("c")], quality_rules: [rule("r", "c", "relationship", { field: "fk", parent_dataset_id: "p", parent_field: "k" })], dataset_rows: { c: rows(2, () => ({ fk: "K0" })) } });
  eq("a parent without rows matches nothing: 0 of 2 = 0.000000, not unknown", run(w0).metrics["relationship_integrity"]["r"].value, "0.000000");
}
// timeliness: half-open deadline, zone matters, DST day, never refreshed is late
{
  const mon = (tz: string, t: string, g: number, last: string | null): Row => ({ monitored: true, refresh_timezone: tz, refresh_local_time: t, refresh_grace_minutes: g, last_refreshed_at: last });
  const w = world({ datasets: [ds("a", "o1", mon("America/New_York", "06:00", 60, "2026-10-04T10:00:00Z")), ds("b", "o1", mon("America/New_York", "06:00", 60, "2026-10-04T11:00:00Z")), ds("c", "o1", mon("America/New_York", "06:00", 60, "2026-10-04T09:59:59Z")), ds("d", "o1", mon("Europe/London", "07:00", 30, null)), ds("e")],
    quality_rules: ["a", "b", "c", "d"].map((d) => rule(`t${d}`, d, "timeliness", {})) });
  const t = run(w).metrics["timeliness"];
  eq("timeliness: refresh at the occurrence is on time; at the deadline is late; a minute before the occurrence is late; never refreshed is late; unmonitored not counted", [t.datasets["a"].on_time, t.datasets["b"].on_time, t.datasets["c"].on_time, t.datasets["d"].on_time, t.monitored_datasets, t.value], [true, false, false, false, 4, "0.250000"]);
  const dst = world({ as_of: "2026-11-02T00:00:00Z", datasets: [ds("a", "o1", mon("America/New_York", "01:30", 60, "2026-11-01T06:40:00Z"))], quality_rules: [rule("ta", "a", "timeliness", {})] });
  const d = run(dst).metrics["timeliness"].datasets["a"];
  eq("DST fall-back day: 01:30 occurs twice and the LATER instant (06:30Z, EST) is the target, so a refresh at 06:40Z is on time", [d.evaluated_occurrence_utc, d.deadline_utc, d.on_time], ["2026-11-01T06:30:00Z", "2026-11-01T07:30:00Z", true]);
}
// weighted score: unmeasured dimensions dropped from both sums; version named; critical override under a high score
{
  const mk = (n: number) => rows(n, (i) => ({ k: `K${i}`, e: "a@x.io" }));
  const w = world({ datasets: [ds("d1")], quality_rules: [rule("c", "d1", "completeness", { field: "e" }), rule("u", "d1", "uniqueness", { field: "k" }, { severity: "critical" })],
    rule_runs: [{ rule_run_id: "rr1", rule_id: "u", rule_version: 1, weight_version: "w2", kind: "scheduled", run_at: "2026-10-04T00:00:00Z", eligible_count: 200, failure_count: 1, rerun_for_issue: null }],
    issues: [{ issue_id: "i1", rule_run_id: "rr1", owner_id: "o1", status: "open", detected_at: "2026-10-04T00:00:00Z" }],
    dataset_rows: { d1: [...mk(199), { row_id: "dup", k: "K0", e: "a@x.io" }] } });
  const r = run(w);
  const s = r.metrics["weighted_score"];
  eq("score over measured dimensions only: completeness 1, uniqueness 0.995 -> (0.25 + 0.24875) / 0.5 = 0.997500 under w2; weight sum 0.500000", [s.datasets["d1"].value, s.datasets["d1"].weight_sum, s.datasets["d1"].measured_dimensions], ["0.997500", "0.500000", ["completeness", "uniqueness"]]);
  eq("the same rows under w1: (0.4 + 0.199) / 0.6 = 0.998333 (the version is named)", [s.by_weight_version["w1"]["d1"], run(w, "w1").computation.weight_version], ["0.998333", "w1"]);
  eq("a 0.9975 score still carries the critical override: 1 failing row of a critical rule and 1 open critical issue", [s.datasets["d1"].critical_override, s.datasets["d1"].critical_failures, s.datasets["d1"].critical_open_issues, r.metrics["critical_failures"]], [true, 1, 1, { failures: 1, open_issues: 1, datasets_overridden: 1, carried: [] }]);
  const none = run(world({ datasets: [ds("x")] })).metrics["weighted_score"].datasets["x"];
  eq("a dataset that measures nothing has a null score, not 0", [none.value, none.weight_sum, none.measured_dimensions], [null, "0.000000", []]);
}
// issues: claimed is never resolved; a rerun of another version does not verify; reopened keeps first detected_at
{
  const runs = (rv: number, fc: number): Row => ({ rule_run_id: `x${rv}${fc}`, rule_id: "c", rule_version: rv, weight_version: "w2", kind: "rerun", run_at: "2026-09-25T00:00:00Z", eligible_count: 10, failure_count: fc, rerun_for_issue: "i2" });
  const base: Row = { rule_run_id: "rr1", rule_id: "c", rule_version: 1, weight_version: "w2", kind: "scheduled", run_at: "2026-09-20T00:00:00Z", eligible_count: 10, failure_count: 2, rerun_for_issue: null };
  const w = world({ datasets: [ds("d1")], quality_rules: [rule("c", "d1", "completeness", { field: "e" })], rule_runs: [base, runs(1, 0)], dataset_dummy: 0,
    issues: [{ issue_id: "i1", rule_run_id: "rr1", owner_id: "o1", status: "closed", detected_at: "2026-09-20T00:00:00Z", closed_at: "2026-09-21T00:00:00Z" },
      { issue_id: "i2", rule_run_id: "rr1", owner_id: "o1", status: "closed", detected_at: "2026-09-20T00:00:00Z", closed_at: "2026-09-26T00:00:00Z", verification_run_id: "x10" },
      { issue_id: "i3", rule_run_id: "rr1", owner_id: "o1", status: "open", detected_at: "2026-09-20T00:00:00Z", closed_at: null, reopened_at: ["2026-09-28T00:00:00Z"] }], dataset_rows: { d1: rows(1, () => ({ e: "a" })) } });
  const r = run(w).metrics["resolution_time"];
  eq("closed without a rerun is claimed; closed with a successful rerun is resolved at the rerun's time (120 h); reopened is open with its first detected_at", [r.issues["i1"].class, r.issues["i2"].class, r.issues["i2"].resolution_hours, r.issues["i3"].class, r.issues["i3"].reopen_cycles, r.issues["i3"].age_hours, r.resolved_count, r.claimed_count], ["claimed", "resolved", "120.0000", "open", 1, "360.0000", 1, 1]);
  const bad = world({ ...w, rule_runs: [base, runs(2, 0)], issues: [{ issue_id: "i2", rule_run_id: "rr1", owner_id: "o1", status: "closed", detected_at: "2026-09-20T00:00:00Z", closed_at: "2026-09-26T00:00:00Z", verification_run_id: "x20" }] });
  eq("a verifying run of another rule version is refused at ingest (VERIFICATION_RUN_INVALID)", run(bad).ingest.rejected.map((x) => [x.entity, x.reason_code]), [["issues", "VERIFICATION_RUN_INVALID"]]);
}
// rules: disabled after as-of is still active; disabled before keeps its history; comparison refuses a changed version
{
  const rr = (id: string, v: number, at: string, el: number, f: number): Row => ({ rule_run_id: id, rule_id: "c", rule_version: v, weight_version: "w1", kind: "scheduled", run_at: at, eligible_count: el, failure_count: f, rerun_for_issue: null });
  const w = world({ datasets: [ds("d1")], quality_rules: [rule("c", "d1", "completeness", { field: "e" }, { version_number: 2 }), rule("z", "d1", "completeness", { field: "e" }, { status: "disabled", disabled_at: "2026-09-01T00:00:00Z", disabled_reason: "retired" }), rule("later", "d1", "completeness", { field: "e" }, { status: "disabled", disabled_at: "2026-10-10T00:00:00Z", disabled_reason: "retired later" })],
    rule_runs: [rr("a", 1, "2026-09-01T00:00:00Z", 100, 10), rr("b", 1, "2026-09-02T00:00:00Z", 80, 10), { ...rr("z1", 1, "2026-08-01T00:00:00Z", 5, 1), rule_id: "z" }], dataset_rows: { d1: rows(2, () => ({ e: "a" })) } });
  const c = run(w);
  eq("disabled before the as-of: history kept and readable; disabled after the as-of: still active at it", [Object.keys(c.computation.rules["disabled"]), c.computation.rules["disabled"]["z"].runs_retained, Object.keys(c.computation.rules["runs"])], [["z"], 1, ["c", "later"]]);
  const cmp = c.computation.rules["comparisons"]["c"];
  eq("RULE_VERSION_DIFFERS: v1 -> v2 is not comparable and no rates are compared", [cmp.comparable, cmp.reason, cmp.failure_rate_previous, cmp.failure_rate_current, cmp.previous_eligible_count], [false, "RULE_VERSION_DIFFERS", null, null, 80]);
}
// matching: canonical order, duplicate pair, reviewer = proposer, reversal, precision only from the truth
{
  const rec = (id: string): Row => ({ record_id: id, source_system: "s", source_customer_id: id, normalized_name: "n", address_key: "a" });
  const cand = (id: string, l: string, r: string, by = "o1"): Row => ({ candidate_id: id, left_record_id: l, right_record_id: r, score: "0.900000", features: { name: "1.000000" }, explanation: "same", uncertainty: "Shared name and address", proposed_by: by, proposed_at: "2026-09-01T00:00:00Z" });
  const dec = (id: string, c: string, by: string, d: string, at: string, extra: Row = {}): Row => ({ merge_id: id, candidate_id: c, reviewer_id: by, decision: d, decided_at: at, reverses_merge_id: null, reason: null, ...extra });
  const w = world({ owners: [owner("o1"), owner("o2"), owner("o3", "analyst")], customer_records: ["r1", "r2", "r3", "r4", "r5", "r6"].map(rec),
    match_candidates: [cand("c1", "r1", "r2"), cand("c2", "r2", "r1"), cand("c3", "r6", "r5"), cand("c4", "r3", "r4"), cand("c5", "r5", "r6")],
    merge_decisions: [dec("m1", "c1", "o2", "approve", "2026-09-02T00:00:00Z"), dec("m2", "c4", "o1", "approve", "2026-09-02T00:00:00Z"), dec("m3", "c4", "o2", "approve", "2026-09-03T00:00:00Z"), dec("m4", "c4", "o2", "reverse", "2026-09-04T00:00:00Z", { reverses_merge_id: "m3", reason: "wrong person" }), dec("m5", "c5", "o3", "approve", "2026-09-05T00:00:00Z")],
    synthetic_truth: { true_entity: { r1: "E1", r2: "E1", r3: "E2", r4: "E3", r5: "E4", r6: "E5" } } });
  const r = run(w);
  eq("ingest: the reverse-order twin is DUPLICATE_PAIR, a first-seen left > right pair is NON_CANONICAL_ORDER, reviewer = proposer, and an analyst reviewer are refused", r.ingest.rejected.map((x) => [x.id, x.reason_code]), [["c2", "DUPLICATE_PAIR"], ["c3", "NON_CANONICAL_ORDER"], ["m2", "REVIEWER_IS_PROPOSER"], ["m5", "ROLE_NOT_PERMITTED"]]);
  const m = r.computation.matching;
  eq("a reversal restores both identities and keeps the history: c4 reversed, c1 active", [m["identity_map"]["r4"], m["identity_map"]["r2"], m["merges_reversed"], m["active_merges"], m["mapping_history"].map((h: Row) => [h["merge_id"], h["state"]])], ["r4", "r1", 1, 1, [["m1", "active"], ["m3", "reversed"]]]);
  eq("precision = approved decisions the truth confirms / approved (a reversal does not remove the approval): m1 right, m3 wrong -> 0.500000", [r.metrics["match_precision"].precision, r.metrics["match_precision"].approved_decisions], ["0.500000", 2]);
  const noTruth = runPipeline({ ...w, synthetic_truth: undefined });
  eq("without a truth block precision is null (unknown), never 0, and a warning says so", [noTruth.metrics["match_precision"].precision, noTruth.warnings.map((x) => x.code)], [null, ["MATCH_TRUTH_UNAVAILABLE"]]);
  const flipped = runPipeline({ ...w, synthetic_truth: { true_entity: Object.fromEntries(["r1", "r2", "r3", "r4", "r5", "r6"].map((k) => [k, "E"])) } });
  eq("the truth changes only the precision block, nothing the matcher reports", [canon(goldenOf(flipped).matching), flipped.metrics["match_precision"].precision], [canon(goldenOf(r).matching), "1.000000"]);
}
// ownership: an inactive owner is not covered; lineage: observed rule and distinct pairs; empty population
{
  const w = world({ owners: [owner("o1"), owner("o2", "steward", false, "2026-09-15T00:00:00Z")], datasets: [ds("a"), ds("b", "o2"), ds("c", "o1"), ds("d", "o1")],
    lineage_edges: [{ edge_id: "e1", source_dataset_id: "a", target_dataset_id: "b", evidence_type: "declared", observed_at: null }, { edge_id: "e2", source_dataset_id: "a", target_dataset_id: "c", evidence_type: "declared", observed_at: null },
      { edge_id: "e3", source_dataset_id: "a", target_dataset_id: "b", evidence_type: "observed", observed_at: "2026-10-01T00:00:00Z" }, { edge_id: "e4", source_dataset_id: "a", target_dataset_id: "b", evidence_type: "observed", observed_at: "2026-10-02T00:00:00Z" },
      { edge_id: "e5", source_dataset_id: "a", target_dataset_id: "c", evidence_type: "inferred", observed_at: null }, { edge_id: "e6", source_dataset_id: "c", target_dataset_id: "d", evidence_type: "observed", observed_at: "2026-10-02T00:00:00Z" },
      { edge_id: "e7", source_dataset_id: "b", target_dataset_id: "d", evidence_type: "observed", observed_at: null }, { edge_id: "e8", source_dataset_id: "b", target_dataset_id: "c", evidence_type: "inferred", observed_at: "2026-10-02T00:00:00Z" }] });
  const r = run(w);
  eq("ownership: 3 of 4 (the inactive owner leaves b uncovered)", [r.metrics["ownership_coverage"].value, r.metrics["ownership_coverage"].uncovered], ["0.750000", ["b"]]);
  eq("lineage: observed edges without observed_at and inferred edges with one are MALFORMED_RECORD (D-08)", r.ingest.rejected.map((x) => [x.id, x.reason_code]), [["e7", "MALFORMED_RECORD"], ["e8", "MALFORMED_RECORD"]]);
  const l = r.metrics["lineage_coverage"];
  eq("lineage: a pair observed twice counts once; an inferred edge never counts as observed; coverage 1/2 = 0.500000; c->d undeclared", [l.observed_distinct, l.observed_matching_declared, l.value, l.undeclared_observed, l.inferred_edges], [2, 1, "0.500000", [{ source_dataset_id: "c", target_dataset_id: "d" }], [{ source_dataset_id: "a", target_dataset_id: "c" }]]);
  const e = run(world({ owners: [] }));
  eq("an empty world: every count 0, every ratio null, empty_population true", [e.computation.empty_population, e.metrics["ownership_coverage"].value, e.metrics["timeliness"].value, e.metrics["match_precision"].precision, e.metrics["resolution_time"].mean_hours], [true, null, null, null, null]);
}

// ---------------------------------------------------------------------------------------------------------------- review R7 (D-10)
const mon = (tz: string, t: string, g: number, last: string | null): Row => ({ monitored: true, refresh_timezone: tz, refresh_local_time: t, refresh_grace_minutes: g, last_refreshed_at: last });
const NY = (last: string | null, asOf: string, local = "06:00", grace = 60): Row => world({ as_of: asOf, datasets: [ds("a", "o1", mon("America/New_York", local, grace, last))], quality_rules: [rule("ta", "a", "timeliness", {})] });
const tlOf = (w: Row): Row => run(w).metrics["timeliness"];
// R7-01: the latest occurrence STARTED by the as-of is judged; an open window with no refresh yet is pending, outside the denominator
{
  const a = tlOf(NY("2026-10-05T10:10:00Z", "2026-10-05T10:30:00Z"));
  eq("R7-01: refreshed 10:10Z, as-of 10:30Z (06:00 New York, grace 60): on time, judged on the 10:00Z occurrence", [a.datasets["a"].state, a.datasets["a"].evaluated_occurrence_utc, a.value], ["on_time", "2026-10-05T10:00:00Z", "1.000000"]);
  const p = tlOf(NY("2026-10-04T10:20:00Z", "2026-10-05T10:30:00Z"));
  eq("R7-01: yesterday's refresh, today's window open: pending, neither on time nor late; evaluated 0, pending 1, value null", [p.datasets["a"].state, p.datasets["a"].on_time, p.monitored_datasets, p.evaluated_datasets, p.pending_count, p.value], ["pending", null, 1, 0, 1, null]);
  const late = tlOf(NY("2026-10-04T10:20:00Z", "2026-10-05T11:00:00Z"));
  eq("R7-01: the deadline equal to the as-of has passed: late", [late.datasets["a"].state, late.value], ["late", "0.000000"]);
  const atDeadline = tlOf(NY("2026-10-05T11:00:00Z", "2026-10-05T12:00:00Z"));
  eq("R7-01: a refresh at the deadline is late; a refresh after the as-of has not happened (pending)", [atDeadline.datasets["a"].state, tlOf(NY("2026-10-05T10:45:00Z", "2026-10-05T10:30:00Z")).datasets["a"].state], ["late", "pending"]);
  const first = tlOf(NY("2026-11-01T05:45:00Z", "2026-11-01T12:00:00Z", "01:30")), second = tlOf(NY("2026-11-01T06:45:00Z", "2026-11-01T12:00:00Z", "01:30"));
  eq("R7-19: clocks back, 01:30 happens at 05:30Z and 06:30Z, the later is the occurrence: a refresh at 05:45Z is late, at 06:45Z on time", [first.datasets["a"].state, first.datasets["a"].evaluated_occurrence_utc, second.datasets["a"].state], ["late", "2026-11-01T06:30:00Z", "on_time"]);
  const scored = run(NY("2026-10-04T10:20:00Z", "2026-10-05T10:30:00Z")).metrics["weighted_score"].datasets["a"];
  eq("R7-01: a pending dataset's timeliness is not scored (no dimension, null score), and its rule run has eligible 0", [scored.measured_dimensions, scored.value, run(NY("2026-10-04T10:20:00Z", "2026-10-05T10:30:00Z")).computation.rules["runs"]["ta"].eligible_count], [[], null, 0]);
}
// R7-02: a critical rule disabled while its latest run fails keeps counting that failure and the override until a passing rerun
{
  const crit = (extra: Row = {}): Row => rule("u", "d1", "uniqueness", { field: "k" }, { severity: "critical", status: "disabled", disabled_at: "2026-10-04T00:00:00Z", disabled_reason: "r7", ...extra });
  const rr = (id: string, kind: string, at: string, f: number): Row => ({ rule_run_id: id, rule_id: "u", rule_version: 1, weight_version: "w2", kind, run_at: at, eligible_count: 10, failure_count: f, rerun_for_issue: kind === "rerun" ? "i1" : null });
  const w = (runs: Row[], extra: Row = {}): Row => world({ datasets: [ds("d1")], quality_rules: [crit(extra)], rule_runs: runs, dataset_rows: { d1: rows(2, (i) => ({ k: `K${i}` })) } });
  const m = run(w([rr("a", "scheduled", "2026-10-03T00:00:00Z", 3)])).metrics;
  eq("R7-02: disabled with a failing latest run (3): critical failures 3, override true, listed as carried, no issue needed", [m["weighted_score"].datasets["d1"].critical_failures, m["weighted_score"].datasets["d1"].critical_override, m["critical_failures"]], [3, true, { failures: 3, open_issues: 0, datasets_overridden: 1, carried: [{ dataset_id: "d1", rule_id: "u", rule_run_id: "a", failure_count: 3 }] }]);
  const failed = run(w([rr("a", "scheduled", "2026-10-03T00:00:00Z", 3), rr("b", "rerun", "2026-10-03T12:00:00Z", 1)])).metrics["critical_failures"];
  eq("R7-02: a failing rerun is the latest run and keeps counting (1)", [failed.failures, failed.carried[0].rule_run_id], [1, "b"]);
  const cleared = run(w([rr("a", "scheduled", "2026-10-03T00:00:00Z", 3), rr("b", "rerun", "2026-10-03T12:00:00Z", 0)])).metrics;
  eq("R7-02: a passing rerun clears it: 0 failures, nothing carried, no override", [cleared["critical_failures"], cleared["weighted_score"].datasets["d1"].critical_override], [{ failures: 0, open_issues: 0, datasets_overridden: 0, carried: [] }, false]);
  const later = run(w([rr("a", "scheduled", "2026-10-03T00:00:00Z", 3)], { disabled_at: "2026-10-06T00:00:00Z" })).metrics["critical_failures"];
  eq("R7-02: disabled after the as-of it was still active: measured, not carried", [later.carried, later.failures], [[], 0]);
  const lowSev = run(w([rr("a", "scheduled", "2026-10-03T00:00:00Z", 3)], { severity: "high" })).metrics["critical_failures"];
  eq("R7-02: a disabled rule that is not critical carries nothing", [lowSev.carried, lowSev.failures], [[], 0]);
}
// R7-04: a pattern with \s \d \w \b is refused at ingest; explicit classes pass; the characters the engines disagreed about are ordinary
{
  const v = (pattern: string, email: string | null = "a@x.io"): Row => world({ datasets: [ds("d1")], quality_rules: [rule("v", "d1", "validity", { field: "e", pattern })], dataset_rows: { d1: rows(1, () => ({ e: email })) } });
  for (const p of ["^\\s+$", "^\\d+$", "^\\w+$", "\\bx", "^\\S+$", "^\\D$", "^\\W$", "a\\B", "[^@\\s]+@x"]) {
    eq(`R7-04: ${p} is refused (PATTERN_NOT_PORTABLE) and the rule is not measured`, [run(v(p)).ingest.rejected.filter((x) => x.entity === "quality_rules").map((x) => x.reason_code), Object.keys(run(v(p)).metrics["validity"])], [["PATTERN_NOT_PORTABLE"], []]);
  }
  eq("R7-04: explicit classes and an escaped backslash are portable", ["[ \\t\\r\\n\\f\\v]", "[0-9]", "a\\\\s", "\\.", "^[^@ \\t\\r\\n\\f\\v]+$"].map(patternPortable), [true, true, true, true, true]);
  const email = "^[^@ \\t\\r\\n\\f\\v]+@[^@ \\t\\r\\n\\f\\v]+\\.[A-Za-z]{2,}$";
  for (const [name, ch] of [["U+00A0", "\u00a0"], ["U+FEFF", "\ufeff"], ["U+0085", "\u0085"], ["U+2028", "\u2028"], ["U+001C", "\x1c"]] as const) {
    eq(`R7-04: ${name} inside an e-mail is an ordinary character for the explicit class (passes, as in Python and SQL)`, run(v(email, `a${ch}b@x.io`)).metrics["validity"]["v"].passing_count, 1);
  }
  eq("R7-04: ASCII whitespace, a trailing newline or CR, and a non-ASCII top-level label still fail", ["a b@x.io", "a\tb@x.io", "ab@x.io\n", "ab@x.io\r", "ab@x.ıo", "ab＠x.io"].map((s) => run(v(email, s)).metrics["validity"]["v"].passing_count), [0, 0, 0, 0, 0, 0]);
}
// R7-05: null-key rows fail, are listed apart and lower the score: (eligible - null-key rows - duplicate rows) / eligible
{
  const w = world({ datasets: [ds("d1")], quality_rules: [rule("u", "d1", "uniqueness", { field: "k" })], dataset_rows: { d1: rows(10, (i) => ({ k: ["A", "A", "B", null, "  ", "C", "D", "E", "F", "G"][i] })) } });
  const r = run(w), b = r.metrics["uniqueness"]["u"];
  eq("R7-05: 10 rows, 2 null keys (r4, r5), 1 duplicate row: score (10 - 2 - 1) / 10 = 0.700000, group share 1/7 = 0.142857, row share 0.100000, 3 failures", [b.null_key_count, b.null_key_row_ids, b.distinct_keys, b.group_share.value, b.row_share.value, r.metrics["weighted_score"].datasets["d1"].dimension_scores.uniqueness, r.computation.rules["runs"]["u"].failure_count], [2, ["r4", "r5"], 7, "0.142857", "0.100000", "0.700000", 3]);
}
// R7-11: empty and whitespace-only foreign keys are missing under the policy and are counted with the nulls
{
  const w = world({ datasets: [ds("p"), ds("c")], quality_rules: [rule("r", "c", "relationship", { field: "fk", parent_dataset_id: "p", parent_field: "k" })],
    dataset_rows: { p: rows(2, (i) => ({ k: `K${i}` })), c: rows(6, (i) => ({ fk: ["K0", "K1", "K9", null, "", " \t"][i] })) } });
  const b = run(w).metrics["relationship_integrity"]["r"];
  eq("R7-11: 6 keys, null + empty + whitespace-only = 3 missing (2 of them text), 3 eligible, 2 matched, 0.666667", [b.total_fk_count, b.null_fk_count, b.empty_fk_count, b.eligible_count, b.matched_count, b.value], [6, 3, 2, 3, 2, "0.666667"]);
}
// R7-06: an edge from a dataset to itself is MALFORMED_RECORD (the seeder never meets it)
{
  const edge = (id: string, ev: string): Row => ({ edge_id: id, source_dataset_id: "a", target_dataset_id: "a", evidence_type: ev, observed_at: ev === "observed" ? "2026-10-01T00:00:00Z" : null });
  const r = run(world({ datasets: [ds("a")], lineage_edges: [edge("e1", "declared"), edge("e2", "observed"), edge("e3", "inferred")] }));
  eq("R7-06: a self-edge of any evidence type is MALFORMED_RECORD and none is counted", [r.ingest.rejected.map((x) => [x.id, x.reason_code]), r.metrics["lineage_coverage"].declared_edges], [[["e1", "MALFORMED_RECORD"], ["e2", "MALFORMED_RECORD"], ["e3", "MALFORMED_RECORD"]], 0]);
}
// R7-16: canonical order is code-point order (UTF-16 order puts a surrogate pair before U+E000..U+FFFF)
{
  eq("R7-16: rec-Ａ (U+FF21) sorts before rec-😀 (U+1F600) as in Python and PostgreSQL, not after it", [cmp("rec-\uff21", "rec-\u{1f600}"), cmp("rec-\u{1f600}", "rec-\uff21"), "rec-\uff21" < "rec-\u{1f600}"], [-1, 1, false]);
  eq("R7-16: cmp is a total order on the usual cases (equal, prefix, ASCII, BMP, astral vs astral)", [cmp("a", "a"), cmp("a", "ab"), cmp("b", "a"), cmp("\u00e9", "z"), cmp("\u{1f600}", "\u{1f601}"), cmp("\ue000", "\u{10000}")], [0, -1, 1, 1, -1, -1]);
  const rec = (id: string): Row => ({ record_id: id, source_system: "s", source_customer_id: id, normalized_name: "n", address_key: "a" });
  const cand = (id: string, l: string, r: string): Row => ({ candidate_id: id, left_record_id: l, right_record_id: r, score: "0.500000", features: { f: "1.000000" }, explanation: "x", uncertainty: null, proposed_by: "o1", proposed_at: "2026-09-01T00:00:00Z" });
  const w = world({ customer_records: ["rec-\uff21", "rec-\u{1f600}"].map(rec), match_candidates: [cand("c1", "rec-\uff21", "rec-\u{1f600}"), cand("c2", "rec-\u{1f600}", "rec-\uff21")] });
  eq("R7-16: through ingest, the pair in code-point order is canonical and its reverse is the DUPLICATE_PAIR", run(w).ingest.rejected.map((x) => [x.id, x.reason_code]), [["c2", "DUPLICATE_PAIR"]]);
}

if (failures) { console.log(`FAILED (${failures} of ${checks} checks)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks)`);
