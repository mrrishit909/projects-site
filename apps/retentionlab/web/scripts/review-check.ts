// Adversarial checks of the TypeScript mirror on small hand-worked worlds (the pure-domain twin of the contract's edge cases and of P10-TEST-01..12):
// post-outcome, latent and identifier fields, an event that occurred earlier and arrived after the cutoff, availability before the event, a censored row
// that someone labelled, capacity above the population, a tie across rank K, a calibration bin with no rows, zero positives, an empty population, window
// and visibility edges, label and maturity edges, the split purges, the population stability index with a floored bin, freshness, economics rounding,
// stored derived rows that disagree with the rebuilt ones, and the refusal rules. Every expected value below was worked by hand from the definitions
// in docs/contracts.md (the arithmetic is in the comment above each world). Run by `npm run check` after the golden check.
import { evaluate, type Evaluation } from "../src/domain/pipeline";
import { economics, evaluateRanked, setMetrics, type Item } from "../src/domain/metrics";
import { canon, type Row } from "../src/domain/models";
import { fr, parseFraction } from "../src/domain/num";
import { checkBasis, checkCalibrationRows, checkCapacity, checkFeatureRequest, checkFitRows, checkThreshold } from "../src/domain/rules";
import { daysUs, isoZ, parseTs } from "../src/domain/time";
import { DomainError } from "../src/domain/errors";

let failures = 0, checks = 0;
function eq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 400)} want ${canon(want).slice(0, 400)}`); }
}
let worlds = 0;
const world = (name: string): void => { worlds++; console.log(`-- world ${worlds}: ${name}`); };

// ------------------------------------------------------------------------------------------------------ builders
const T = (s: string): string => s.length === 10 ? `${s}T00:00:00Z` : s;
const plus = (s: string, d: number): string => isoZ(parseTs(T(s)) + daysUs(d))!;
const REG: Row[] = [
  ["usage_events_30d", "events", false, false, false, 30, "usage_events"], ["days_since_last_usage", "events", false, false, false, 90, "usage_events"],
  ["high_severity_support_90d", "events", false, false, false, 90, "support_events"], ["billing_total_90d", "events", false, false, false, 90, "billing_events"],
  ["cancellation_reason", "events", true, false, false, null, "subscription_events"], ["cancellation_survey_score", "events", true, false, false, null, "support_events"],
  ["refund_after_cancel", "events", true, false, false, null, "billing_events"], ["latent_churn_propensity", "generator_manifest", false, true, false, null, "generator_manifest"],
  ["generator_seed_bucket", "generator_manifest", false, true, false, null, "generator_manifest"], ["account_id_hash", "identifier", false, false, true, null, "accounts"],
  ["creation_sequence", "identifier", false, false, true, null, "accounts"],
].map(([n, lineage, post, latent, idd, win, src]) => ({ feature_name: n, feature_version: "fv-1", source_entity: src, window_days: win, post_outcome: post, latent, id_derived: idd, lineage }));
const base = (over: Row = {}): Row => ({
  contract_version: 1, as_of: "2026-05-01T00:00:00Z", label_version: { label_version_id: "lv-1", horizon_days: 90, grace_days: 14 }, feature_version_spec: { feature_version: "fv-1", observation_days: 90 },
  accounts: [], subscription_events: [], billing_events: [], usage_events: [], support_events: [], prediction_cutoffs: [], feature_rows: [], labels: [], training_runs: [], predictions: [],
  intervention_scenarios: [], outreach_events: [], feature_registry: REG, split_assignments: [], scoring_publications: [], scope: { training_run_id: "tr-1", sets: [] }, ...over,
});
const acct = (id: unknown, created = "2024-06-01", extra: Row = {}): Row => ({ account_id: id, created_at: T(created), segment: "mid", region: "emea", synthetic: true, ...extra });
const sub = (id: string, a: unknown, type: string, at: string, avail = at): Row => ({ subscription_event_id: id, account_id: a, event_type: type, event_at: T(at), available_at: T(avail) });
const use = (id: string, a: unknown, at: string, avail = at): Row => ({ usage_event_id: id, account_id: a, event_name: "login", event_at: T(at), available_at: T(avail) });
const bill = (id: string, a: unknown, amount: string, at: string, avail = at): Row => ({ billing_event_id: id, account_id: a, amount, event_at: T(at), available_at: T(avail) });
const sup = (id: string, a: unknown, severity: string, at: string, avail = at): Row => ({ support_event_id: id, account_id: a, severity, event_at: T(at), available_at: T(avail) });
const cut = (a: unknown, pa: string): Row => ({ cutoff_id: `co-${a}-${pa.slice(0, 10)}`, account_id: a, prediction_at: T(pa), horizon_end: plus(pa, 90), observation_start: plus(pa, -90) });
const RUN: Row = { training_run_id: "tr-1", train_end: "2025-10-01T00:00:00Z", validation_end: "2026-02-01T00:00:00Z", test_end: "2026-06-01T00:00:00Z", config: { feature_version: "fv-1", label_version: "lv-1" }, config_hash: "h" };
const pred = (a: unknown, pa: string, p: unknown, extra: Row = {}): Row => ({ prediction_id: `pr-${a}-${pa.slice(0, 10)}`, training_run_id: "tr-1", cutoff_id: `co-${a}-${pa.slice(0, 10)}`, probability: p, scored_at: T(pa), config_hash: "h", feature_version: "fv-1", label_version: "lv-1", ...extra });
const SC = (id: string, capacity: number, cost = "1.00", effect = "0.500000", margin = "10.00"): Row => ({ scenario_id: id, capacity, contact_cost: cost, assumed_effect: effect, margin_value: margin });
const set = (pa: string, scenario: string | null = null): Row => ({ prediction_at: T(pa), scenario_id: scenario });
const JAN = "2026-01-01";
/** n accounts, all active from 2024-06-01, one cutoff each at `at`, account i churning (cancel 2026-02-10) when outcomes[i] is 1, probabilities p[i]. */
function scored(p: unknown[], y: (0 | 1)[], scenario: Row | null = null, at = JAN, over: Row = {}): Row {
  const ids = p.map((_, i) => i + 1);
  return base({
    accounts: ids.map((i) => acct(i)), subscription_events: [...ids.map((i) => sub(`s${i}`, i, "start", "2024-06-01")), ...ids.filter((i) => y[i - 1] === 1).map((i) => sub(`c${i}`, i, "cancel", "2026-02-10"))],
    prediction_cutoffs: ids.map((i) => cut(i, at)), training_runs: [RUN], predictions: ids.map((i) => pred(i, at, p[i - 1])), intervention_scenarios: scenario ? [scenario] : [],
    scope: { training_run_id: "tr-1", sets: [set(at, scenario ? (scenario["scenario_id"] as string) : null)] }, ...over,
  });
}
const run = (w: Row, hashes: Record<string, string> | null = null): Evaluation => evaluate(w, hashes);
const S = (e: Evaluation, at = JAN): Row => e.result["cutoff_sets"][T(at)];
const refusal = (f: () => void): { code: string; offending: unknown } | null => { try { f(); return null; } catch (e) { if (e instanceof DomainError) return { code: e.code, offending: e.offending }; throw e; } };
const dump: Row[] = [];
const dumped = (name: string, w: Row, e: Evaluation): Evaluation => { dump.push({ name, inputs: w, result: JSON.parse(JSON.stringify(e.result)) }); return e; };

// 1. P10-TEST-01: a post-outcome field is refused, whatever else is in the request
world("a post-outcome field in a feature request (P10-TEST-01)");
{
  const reg = run(base()).world.registry;
  eq("cancellation_reason -> POST_OUTCOME_FIELD naming the field", refusal(() => checkFeatureRequest(reg, ["usage_events_30d", "cancellation_reason"])), { code: "POST_OUTCOME_FIELD", offending: [{ item: "cancellation_reason", code: "POST_OUTCOME_FIELD" }] });
  eq("all three registered post-outcome fields are refused", ["cancellation_reason", "cancellation_survey_score", "refund_after_cancel"].map((f) => refusal(() => checkFeatureRequest(reg, [f]))!.code), ["POST_OUTCOME_FIELD", "POST_OUTCOME_FIELD", "POST_OUTCOME_FIELD"]);
  eq("the four registered features pass, in the order given", checkFeatureRequest(reg, ["billing_total_90d", "usage_events_30d"]), ["billing_total_90d", "usage_events_30d"]);
}
// 2. P10-TEST-08: latent truth
world("a latent field (P10-TEST-08)");
{
  const reg = run(base()).world.registry;
  eq("registered latent_churn_propensity and generator_seed_bucket (lineage generator_manifest) -> LATENT_TRUTH", [refusal(() => checkFeatureRequest(reg, ["latent_churn_propensity"]))!.code, refusal(() => checkFeatureRequest(reg, ["generator_seed_bucket"]))!.code], ["LATENT_TRUTH", "LATENT_TRUTH"]);
  eq("an unregistered name starting latent_ is still LATENT_TRUTH", refusal(() => checkFeatureRequest(reg, ["usage_events_30d", "latent_made_up"])), { code: "LATENT_TRUTH", offending: [{ item: "latent_made_up", code: "LATENT_TRUTH" }] });
}
// 3. P10-TEST-12: an id feature
world("an identifier-derived feature (P10-TEST-12)");
{
  const reg = run(base()).world.registry;
  eq("account_id_hash, creation_sequence (registered id_derived) and an unregistered account_id_* name -> ID_FEATURE", ["account_id_hash", "creation_sequence", "account_id_x"].map((f) => refusal(() => checkFeatureRequest(reg, [f]))!.code), ["ID_FEATURE", "ID_FEATURE", "ID_FEATURE"]);
}
// 4. priority of codes, every offending field listed
world("several offences at once: the code is the first in the order POST_OUTCOME_FIELD, LATENT_TRUTH, ID_FEATURE, UNKNOWN_FEATURE");
{
  const reg = run(base()).world.registry;
  eq("the code is POST_OUTCOME_FIELD, every offender is listed with its own code, in request order", refusal(() => checkFeatureRequest(reg, ["no_such_feature", "creation_sequence", "latent_churn_propensity", "cancellation_reason", "usage_events_30d"])),
    { code: "POST_OUTCOME_FIELD", offending: [{ item: "no_such_feature", code: "UNKNOWN_FEATURE" }, { item: "creation_sequence", code: "ID_FEATURE" }, { item: "latent_churn_propensity", code: "LATENT_TRUTH" }, { item: "cancellation_reason", code: "POST_OUTCOME_FIELD" }] });
  eq("without a post-outcome field the code is LATENT_TRUTH; with only unknown + id it is ID_FEATURE", [refusal(() => checkFeatureRequest(reg, ["no_such", "creation_sequence", "latent_x"]))!.code, refusal(() => checkFeatureRequest(reg, ["no_such", "creation_sequence"]))!.code], ["LATENT_TRUTH", "ID_FEATURE"]);
  eq("an unknown field alone is UNKNOWN_FEATURE", refusal(() => checkFeatureRequest(reg, ["no_such"]))!.code, "UNKNOWN_FEATURE");
}
// 5. P10-TEST-02: an event that occurred earlier and arrived after the cutoff, plus the window edges
world("a late arrival and the window edges (P10-TEST-02): cutoff 2026-01-01, window [2025-10-03, 2026-01-01), visibility strictly before the cutoff");
{
  // u1 occurred 12-30 12:00, arrived 01-03: late (counted, not used). u2 at the window start 10-03 00:00: inside. u3 one second before the window: outside, not late.
  // u4 at the cutoff instant: outside the window (event_at < cutoff fails), not late. u5 occurred 12-31 23:59:59, available exactly at the cutoff: not strictly before, late.
  // u6 on 12-15: inside and within 30 days (>= 12-02). Features: usage_events_30d = 1 (u6), days_since = floor((01-01 - 12-15) / 1 d) = 17, late = 2, max_available_at = 12-15.
  const w = base({ accounts: [acct(1)], subscription_events: [sub("s1", 1, "start", "2024-06-01")], prediction_cutoffs: [cut(1, JAN)],
    usage_events: [use("u1", 1, "2025-12-30T12:00:00Z", "2026-01-03"), use("u2", 1, "2025-10-03"), use("u3", 1, "2025-10-02T23:59:59Z"), use("u4", 1, "2026-01-01"), use("u5", 1, "2025-12-31T23:59:59Z", "2026-01-01"), use("u6", 1, "2025-12-15")] });
  const r = dumped("late arrival and window edges", w, run(w)).world.analyse(`co-1-${JAN}`);
  eq("features exclude the late events", r.features, { usage_events_30d: 1, days_since_last_usage: 17, high_severity_support_90d: 0, billing_total_90d: null });
  eq("two events are counted as arrived late (u1, u5); u3 and u4 are outside the window and not late", r.arrived_late, { subscription_events: 0, billing_events: 0, usage_events: 2, support_events: 0 });
  eq("max_available_at is the latest availability USED (u6), before the cutoff", r.max_available_at, "2025-12-15T00:00:00Z");
}
// 6. availability before the event
world("availability before event (ingest, P10-DOMAIN-01)");
{
  const w = base({ accounts: [acct(1)], subscription_events: [sub("s1", 1, "start", "2024-06-01")], usage_events: [use("u1", 1, "2025-12-01", "2025-11-30T23:59:59Z"), use("u2", 1, "2025-12-01", "2025-12-01")], prediction_cutoffs: [cut(1, JAN)] });
  const e = dumped("availability before event", w, run(w));
  eq("u1 is rejected AVAILABILITY_BEFORE_EVENT by one second, u2 (equal instants) is accepted", [e.ingest.rejected, e.ingest.accepted.usage_events.map((u) => u["usage_event_id"])], [[{ entity: "usage_events", id: "u1", reason_code: "AVAILABILITY_BEFORE_EVENT" }], ["u2"]]);
}
// 7. P10-TEST-07: a censored row that someone labelled; and the censored row's own treatment
world("a censored row labelled (P10-TEST-07): cutoff 2026-02-01, label_end 2026-05-16 is after as_of 2026-05-01");
{
  const FEB = "2026-02-01";
  const w = base({ accounts: [acct(1), acct(2)], subscription_events: [sub("s1", 1, "start", "2024-06-01"), sub("s2", 2, "start", "2024-06-01"), sub("c2", 2, "cancel", "2026-03-01")], prediction_cutoffs: [cut(1, FEB), cut(2, FEB)],
    labels: [{ label_id: "lb1", cutoff_id: `co-1-${FEB}`, churned: false, mature: false, label_end: "2026-05-16T00:00:00Z" }, { label_id: "lb2", cutoff_id: `co-2-${FEB}`, churned: null, mature: false, label_end: "2026-05-16T00:00:00Z" }, { label_id: "lb3", cutoff_id: `co-2-${FEB}`, churned: true, mature: false, label_end: "2026-05-16T00:00:00Z" }],
    training_runs: [RUN], predictions: [pred(1, FEB, "0.200000"), pred(2, FEB, "0.700000")], scope: { training_run_id: "tr-1", sets: [set(FEB)] } });
  const e = dumped("censored row labelled", w, run(w));
  eq("a label false on an immature row is rejected CENSORED_LABEL (never non-churn); a null label is accepted; a second label with churned true is also rejected", e.ingest.rejected, [{ entity: "labels", id: "lb1", reason_code: "CENSORED_LABEL" }, { entity: "labels", id: "lb3", reason_code: "CENSORED_LABEL" }]);
  const s = S(e, FEB);
  eq("account 2 cancelled on 03-01 but the window is not closed: churned stays null, both rows are censored, churn rate is null (not 0), no AP, no Brier",
    [s["population"].eligible, s["population"].mature, s["population"].censored, s["population"].churned, s["churn_rate"].value, s["average_precision"].value, s["brier_score"].value, s["population"].scored], [2, 0, 2, 0, null, null, null, 2]);
  eq("the censored rows are still scored and queued: missingness and the queue use all eligible rows", [s["population"].evaluated, s["population"].unscored_excluded], [0, 0]);
}
// 8. P10-TEST-10: capacity above the population
world("capacity above the population (P10-TEST-10): 3 evaluated accounts, K = 4");
{
  const w = scored(["0.9", "0.5", "0.1"].map((x) => x + "00000"), [1, 0, 1], SC("sc-big", 4));
  const s = S(dumped("capacity above population", w, run(w)));
  eq("the K metrics are refused: capacity.ok false with CAPACITY_EXCEEDS_POPULATION, no precision, recall, lift", [s["capacity"], s["precision_at_k"], s["recall_at_k"], s["risk_lift_at_k"]], [{ scenario_id: "sc-big", k: 4, population: 3, ok: false, refusal: "CAPACITY_EXCEEDS_POPULATION" }, null, null, null]);
  eq("no economics and no draft queue either (the queue needs K <= the scored population)", [s["economics"], s["outreach_queue"]], [null, null]);
  eq("the rule itself: 98 of 97 names the scenario and the numbers", refusal(() => checkCapacity("sc-x", 98, 97)), { code: "CAPACITY_EXCEEDS_POPULATION", offending: [{ item: "sc-x", code: "CAPACITY_98_GT_97" }] });
  eq("K equal to the population is allowed", refusal(() => checkCapacity("sc-x", 97, 97)), null);
}
// 9. tie across rank K
world("a tie across rank K: probabilities .5 .5 .5 .1, outcomes 0 1 1 0, K = 2");
{
  // ranked by account id inside the tie: 1, 2, 3, 4. Top 2 = accounts 1 (0) and 2 (1): precision 1/2, recall 1/2 of 2 churners, lift (1/2)/(2/4) = 1, tie_split true (rank 2 and 3 share .5).
  // AP (thresholds): .5 -> tp 2 fp 1, precision 2/3, recall 1 -> 1 x 2/3 = 0.666667; .1 adds no recall. Brier = (.25 + .25 + .25 + .01) / 4 = 0.19.
  // Economics for accounts 1, 2 (p .5, effect .5, margin 10, cost 1): .5 x .5 x 10 - 1 = 1.5 each: 3.00; budget 2.00.
  const w = scored(["0.500000", "0.500000", "0.500000", "0.100000"], [0, 1, 1, 0], SC("sc-2", 2));
  const s = S(dumped("tie across rank K", w, run(w)));
  eq("ranking breaks the tie by account id ascending", s["ranking"].map((r: Row) => r["account_id"]), [1, 2, 3, 4]);
  eq("precision 0.500000, recall 0.500000, lift 1.000000, tie flag true", [s["precision_at_k"].value, s["recall_at_k"].value, s["risk_lift_at_k"].value, s["risk_lift_at_k"].tie_split_at_k], ["0.500000", "0.500000", "1.000000", true]);
  eq("AP 0.666667 (tied probabilities are one threshold), prevalence 0.500000", [s["average_precision"].value, s["average_precision"].prevalence], ["0.666667", "0.500000"]);
  eq("Brier 0.190000", s["brier_score"].value, "0.190000");
  eq("budget 2.00, expected value 3.00 hypothetical, queue [1, 2] draft", [s["economics"].contact_budget, s["economics"].expected_value, s["economics"].label, s["outreach_queue"].account_ids, s["outreach_queue"].status], ["2.00", "3.00", "hypothetical", [1, 2], "draft"]);
}
// 10. calibration bins
world("calibration bins: edges and a bin with no rows");
{
  // p: 0.000000 -> bin 0, 0.099999 -> bin 0, 0.100000 -> bin 1, 0.300000 -> bin 3, 0.999999 and 1.000000 -> bin 9 (the last is closed). Outcomes 0 0 1 0 1 1.
  // bin 0: mean (0 + .099999)/2 = .0499995 -> 0.050000 (half up), observed 0, gap 4.99995 pp -> 5.00. bin 1: mean .1, observed 1, gap -90.00. bin 3: .3 vs 0: 30.00.
  // bin 9: mean .9999995 -> 1.000000, observed 1, gap -0.00005 pp -> 0.00 (never "-0.00"). Counts 2 1 0 1 0 0 0 0 0 2.
  const w = scored(["0.000000", "0.099999", "0.100000", "0.300000", "0.999999", "1.000000"], [0, 0, 1, 0, 1, 1]);
  const bins = S(dumped("calibration bins", w, run(w)))["calibration"].bins as Row[];
  eq("counts per bin", bins.map((b) => b["count"]), [2, 1, 0, 1, 0, 0, 0, 0, 0, 2]);
  eq("bin 0: mean, observed, gap", [bins[0]!["mean_predicted"], bins[0]!["observed_rate"], bins[0]!["gap_pp"]], ["0.050000", "0.000000", "5.00"]);
  eq("bin 1 (p = 0.1 is in the second bin): gap -90.00; bin 3: gap 30.00", [bins[1]!["gap_pp"], bins[3]!["gap_pp"]], ["-90.00", "30.00"]);
  eq("bin 9 closed at 1: mean 1.000000, observed 1.000000, gap 0.00", [bins[9]!["mean_predicted"], bins[9]!["observed_rate"], bins[9]!["gap_pp"], bins[9]!["closed_upper"]], ["1.000000", "1.000000", "0.00", true]);
  eq("an empty bin has null mean, observed and gap, never 0", bins[2], { index: 2, lower: "0.200000", upper: "0.300000", closed_upper: false, count: 0, mean_predicted: null, observed_rate: null, gap_pp: null });
}
// 11. zero positives
world("zero positives: two mature accounts, none churned, K = 1");
{
  const w = scored(["0.300000", "0.200000"], [0, 0], SC("sc-1", 1));
  const s = S(dumped("zero positives", w, run(w)));
  eq("churn rate 0.000000 (a known zero), prevalence 0.000000; recall, lift and AP are null (zero denominators), precision at K is 0.000000", [s["churn_rate"].value, s["average_precision"].prevalence, s["recall_at_k"].value, s["risk_lift_at_k"].value, s["average_precision"].value, s["precision_at_k"].value], ["0.000000", "0.000000", null, null, null, "0.000000"]);
  eq("Brier is still defined: (.09 + .04) / 2 = 0.065000", s["brier_score"].value, "0.065000");
}
// 12. empty population
world("an empty population: a set with no cutoff rows, with a scenario");
{
  const w = base({ accounts: [acct(1)], subscription_events: [sub("s1", 1, "start", "2024-06-01")], training_runs: [RUN], intervention_scenarios: [SC("sc-1", 2)], scope: { training_run_id: "tr-1", sets: [set(JAN, "sc-1")] } });
  const e = dumped("empty population", w, run(w));
  const s = S(e);
  eq("every count is 0, every ratio and score null, empty flags true, K not refused (null), no economics", [s["population"].cutoff_rows, s["population"].eligible, s["churn_rate"].value, s["average_precision"].value, s["brier_score"].value, s["empty_population"], s["empty_evaluation"], s["capacity"], s["economics"], s["feature_missingness"].overall.value],
    [0, 0, null, null, null, true, true, { scenario_id: "sc-1", k: 2, population: 0, ok: false, refusal: null }, null, null]);
  eq("the report is empty_population", e.result["empty_population"], true);
  eq("freshness of nothing: no completed publication -> null; data freshness from the one event (2024-06-01 to 2026-05-01 is 699 days = 16776 h)", [e.result["freshness"].scoring_hours, e.result["freshness"].data_hours], [null, 16776]);
}
// 13. ingest rejections, parents first
world("ingest: duplicates, foreign keys, dependents, malformed rows, in processing order");
{
  const w = base({
    accounts: [acct(1), acct(1), acct(2, "2024-06-01", { synthetic: false }), { created_at: T("2024-06-01"), synthetic: true }, acct(3, "garbage")],
    subscription_events: [sub("s1", 1, "start", "2024-06-01"), sub("s2", 2, "start", "2024-06-01"), sub("s9", 9, "start", "2024-06-01"), { account_id: 1, event_type: "renew", event_at: T("2024-07-01"), available_at: T("2024-07-01") }, sub("s1", 1, "renew", "2024-07-01")],
    usage_events: [use("u1", 2, "2025-12-01"), use("u2", 9, "2025-12-01"), { ...use("u3", 1, "2025-12-01"), event_at: "2025-12-01" }],
  });
  const e = run(w);
  eq("rejections in processing order with the right reason each", e.ingest.rejected.map((r) => [r.entity, r.id, r.reason_code]), [
    ["accounts", 1, "DUPLICATE_ID"], ["accounts", 2, "SYNTHETIC_REQUIRED"], ["accounts", null, "MALFORMED_RECORD"],
    ["subscription_events", "s2", "DEPENDENT_REJECTED"], ["subscription_events", "s9", "UNKNOWN_ACCOUNT"], ["subscription_events", null, "MALFORMED_RECORD"], ["subscription_events", "s1", "DUPLICATE_ID"],
    ["usage_events", "u1", "DEPENDENT_REJECTED"], ["usage_events", "u2", "UNKNOWN_ACCOUNT"], ["usage_events", "u3", "MALFORMED_RECORD"]]);
  eq("accepted counts: accounts 2 (ids 1 and 3: an account's created_at is not parsed at import), subscription 1, usage 0", [e.ingest.accepted.accounts.length, e.ingest.accepted.subscription_events.length, e.ingest.accepted.usage_events.length], [2, 1, 0]);
  eq("counts() reports accepted and rejected per entity", [e.ingest.counts()["accounts"], e.ingest.counts()["usage_events"]], [{ accepted: 2, rejected: 3 }, { accepted: 0, rejected: 3 }]);
}
// 14. probabilities
world("probabilities: range, rational and numeric forms, malformed");
{
  const w = scored(["1.000001", "-0.000001", "abc", "1/2", 0.25, "1.000000", "0", true, " 0.7 "], [0, 0, 0, 0, 0, 0, 0, 0, 0]);
  const e = dumped("probabilities", w, run(w));
  eq("1.000001 and -0.000001 -> PROBABILITY_OUT_OF_RANGE, abc -> MALFORMED_RECORD", e.ingest.rejected.map((r) => [r.id, r.reason_code]), [["pr-1-2026-01-01", "PROBABILITY_OUT_OF_RANGE"], ["pr-2-2026-01-01", "PROBABILITY_OUT_OF_RANGE"], ["pr-3-2026-01-01", "MALFORMED_RECORD"]]);
  eq("1/2, the number 0.25, 1.000000, 0, true (Fraction(True) = 1) and ' 0.7 ' are accepted; the ranking freezes numbers to 6 places", S(e)["ranking"].map((r: Row) => [r["account_id"], r["probability"]]),
    [[6, "1.000000"], [8, "1.000000"], [9, " 0.7 "], [4, "1/2"], [5, "0.250000"], [7, "0"]]);
}
// 15. eligibility
world("eligibility: created strictly before the observation start; the latest visible subscription event decides, ties by id");
{
  // cutoff 2026-01-01, observation_start 2025-10-03. A created exactly at the start -> ineligible; B one second earlier -> eligible; C cancelled 12-01 but the cancel arrives
  // 01-02 (after the cutoff) -> still active; D cancel visible before the cutoff -> NOT_ACTIVE; E no events -> NOT_ACTIVE; F start and cancel at one instant, cancel has the higher id -> NOT_ACTIVE;
  // G cancel then start at one instant, start has the higher id -> eligible.
  const w = base({
    accounts: [acct("A", "2025-10-03"), acct("B", "2025-10-02T23:59:59Z"), acct("C"), acct("D"), acct("E"), acct("F"), acct("G")],
    subscription_events: [sub("sa", "A", "start", "2025-10-03"), sub("sb", "B", "start", "2025-10-02T23:59:59Z"), sub("sc", "C", "start", "2024-06-01"), sub("cc", "C", "cancel", "2025-12-01", "2026-01-02"), sub("sd", "D", "start", "2024-06-01"), sub("cd", "D", "cancel", "2025-12-01"),
      sub("sf1", "F", "start", "2025-12-01"), sub("sf2", "F", "cancel", "2025-12-01"), sub("sg1", "G", "cancel", "2025-12-01"), sub("sg2", "G", "start", "2025-12-01")],
    prediction_cutoffs: ["A", "B", "C", "D", "E", "F", "G"].map((a) => cut(a, JAN)), scope: { training_run_id: "tr-1", sets: [set(JAN)] } });
  const e = dumped("eligibility", w, run(w));
  const rows = e.world.setRows(T(JAN));
  eq("eligible: B, C, G", rows.filter((r) => r.eligible).map((r) => r.account_id), ["B", "C", "G"]);
  eq("ineligible codes", rows.filter((r) => !r.eligible).map((r) => [r.account_id, r.ineligible_code]), [["A", "CREATED_ON_OR_AFTER_OBSERVATION_START"], ["D", "NOT_ACTIVE"], ["E", "NOT_ACTIVE"], ["F", "NOT_ACTIVE"]]);
  eq("the set counts them apart", S(e)["population"].ineligible, { CREATED_ON_OR_AFTER_OBSERVATION_START: 1, NOT_ACTIVE: 3 });
}
// 16. label edges
world("label edges: cutoff 2026-01-01, horizon_end 2026-04-01, label_end 2026-04-15");
{
  // a1 cancel at the cutoff instant -> churn (window start inclusive; not yet visible to the features). a2 cancel at horizon_end -> not churn (exclusive). a3 cancel 03-31 23:59:59, arrives 04-14 23:59:59 (< label_end) -> churn.
  // a4 same cancel arriving exactly at label_end -> not churn. a5 cancelled before the cutoff -> ineligible. Churn rate = 2 / 4 = 0.500000.
  const w = base({ accounts: [1, 2, 3, 4, 5].map((i) => acct(i)), subscription_events: [...[1, 2, 3, 4, 5].map((i) => sub(`s${i}`, i, "start", "2024-06-01")), sub("c1", 1, "cancel", JAN), sub("c2", 2, "cancel", "2026-04-01"),
    sub("c3", 3, "cancel", "2026-03-31T23:59:59Z", "2026-04-14T23:59:59Z"), sub("c4", 4, "cancel", "2026-03-31T23:59:59Z", "2026-04-15"), sub("c5", 5, "cancel", "2025-12-31")], prediction_cutoffs: [1, 2, 3, 4, 5].map((i) => cut(i, JAN)),
    scope: { training_run_id: "tr-1", sets: [set(JAN)] } });
  const e = dumped("label edges", w, run(w));
  eq("churned by account", e.world.setRows(T(JAN)).map((r) => [r.account_id, r.eligible, r.churned]), [[1, true, true], [2, true, false], [3, true, true], [4, true, false], [5, false, null]]);
  eq("churn rate 2 of 4 = 0.500000", S(e)["churn_rate"], { value: "0.500000", churned: 2, mature_eligible: 4 });
}
// 17. maturity edge
world("maturity: label_end <= as_of is mature");
{
  const mk = (asOf: string): Row => base({ as_of: asOf, accounts: [acct(1)], subscription_events: [sub("s1", 1, "start", "2024-06-01")], prediction_cutoffs: [cut(1, JAN)], scope: { training_run_id: "tr-1", sets: [set(JAN)] } });
  eq("as_of exactly at label_end (2026-04-15T00:00:00Z): mature, churn rate 0.000000", [S(run(mk("2026-04-15T00:00:00Z")))["population"].mature, S(run(mk("2026-04-15T00:00:00Z")))["churn_rate"].value], [1, "0.000000"]);
  eq("one second before: censored, churn rate null", [S(run(mk("2026-04-14T23:59:59Z")))["population"].censored, S(run(mk("2026-04-14T23:59:59Z")))["churn_rate"].value], [1, null]);
}
// 18. feature edges: no events, severities, billing signs and rounding
world("feature edges: missing sources are null, only 'high' severity counts, billing is summed exactly then rounded half up once");
{
  // acct 1: nothing -> usage 0, days null, high 0, billing null; acct 2: support low, medium, high, high -> 2; billing 10.00 + -30.00 = -20.00.
  // acct 3: billing -0.004 -> "-0.00" (sign kept, as Decimal.quantize does); acct 4: 0.005 -> 0.01; acct 5: -0.005 -> -0.01; acct 6: 0.004 + 0.004 = 0.008 -> 0.01 (rounded once, not per term).
  const w = base({ accounts: [1, 2, 3, 4, 5, 6].map((i) => acct(i)), subscription_events: [1, 2, 3, 4, 5, 6].map((i) => sub(`s${i}`, i, "start", "2024-06-01")), prediction_cutoffs: [1, 2, 3, 4, 5, 6].map((i) => cut(i, JAN)),
    support_events: [sup("p1", 2, "low", "2025-12-01"), sup("p2", 2, "medium", "2025-12-01"), sup("p3", 2, "high", "2025-12-01"), sup("p4", 2, "high", "2025-12-02")],
    billing_events: [bill("b1", 2, "10.00", "2025-11-01"), bill("b2", 2, "-30.00", "2025-12-01"), bill("b3", 3, "-0.004", "2025-12-01"), bill("b4", 4, "0.005", "2025-12-01"), bill("b5", 5, "-0.005", "2025-12-01"), bill("b6", 6, "0.004", "2025-12-01"), bill("b7", 6, "0.004", "2025-12-02")],
    scope: { training_run_id: "tr-1", sets: [set(JAN)] } });
  const e = dumped("feature edges", w, run(w));
  const f = (i: number): Row => e.world.analyse(`co-${i}-${JAN}`).features!;
  eq("account 1: no events anywhere", f(1), { usage_events_30d: 0, days_since_last_usage: null, high_severity_support_90d: 0, billing_total_90d: null });
  eq("account 2: two high-severity cases, billing -20.00", [f(2)["high_severity_support_90d"], f(2)["billing_total_90d"]], [2, "-20.00"]);
  eq("billing totals -0.004 -> -0.00, 0.005 -> 0.01, -0.005 -> -0.01, 0.004 + 0.004 -> 0.01", [3, 4, 5, 6].map((i) => f(i)["billing_total_90d"]), ["-0.00", "0.01", "-0.01", "0.01"]);
  eq("missingness: days_since_last_usage is missing for all six, billing for account 1 only", [S(e)["feature_missingness"].by_feature.days_since_last_usage.missing, S(e)["feature_missingness"].by_feature.billing_total_90d.missing, S(e)["feature_missingness"].overall], [6, 1, { missing: 7, total: 24, value: "0.291667" }]);
}
// 19. split purges
world("the split: label-window purge (equal does not cross), group purges counted by range, test rows never purged, outside the test range");
{
  // boundaries train_end 2025-10-01, validation_end 2026-02-01, test_end 2026-06-01; embargo 104 days.
  // t_ok  2025-06-19 -> label_end 2025-10-01 = train_end: not crossing, retained.   t_cross 2025-06-20 -> 10-02: LABEL_WINDOW.
  // v_ok  2025-10-20 -> label_end 2026-02-01 = validation_end: retained.             v_cross 2025-10-21 -> 02-02: LABEL_WINDOW.
  // G1 train 2025-06-01 + test 2026-03-15 -> the train row is GROUP_TEST.            G2 train 2025-06-01 + validation 2025-10-20 -> the train row is GROUP_VALIDATION.
  // G3 train 2025-06-20 (LABEL_WINDOW first) + test -> stays LABEL_WINDOW.            G4 validation 2025-10-21 (LABEL_WINDOW) + test -> stays LABEL_WINDOW.
  // G6 train 2025-06-01 + validation 2025-10-21 (dropped by LABEL_WINDOW) -> the train row is GROUP_VALIDATION (membership counted by range). G11 validation 2025-10-20 + test -> GROUP_TEST.
  // The test rows (2026-03-15, label_end after test_end) are retained. A row at 2026-06-01 is 'outside'.
  const rowsSpec: [string, string][] = [["t_ok", "2025-06-19"], ["t_cross", "2025-06-20"], ["v_ok", "2025-10-20"], ["v_cross", "2025-10-21"], ["G1", "2025-06-01"], ["G1", "2026-03-15"], ["G2", "2025-06-01"], ["G2", "2025-10-20"],
    ["G3", "2025-06-20"], ["G3", "2026-03-15"], ["G4", "2025-10-21"], ["G4", "2026-03-15"], ["G6", "2025-06-01"], ["G6", "2025-10-21"], ["G11", "2025-10-20"], ["G11", "2026-03-15"], ["G12", "2026-06-01"]];
  const ids = [...new Set(rowsSpec.map(([a]) => a))];
  const w = base({ accounts: ids.map((a) => acct(a)), subscription_events: ids.map((a) => sub(`s-${a}`, a, "start", "2024-06-01")), prediction_cutoffs: rowsSpec.map(([a, d]) => cut(a, d)), training_runs: [RUN] });
  const e = dumped("split purges", w, run(w));
  const asg = Object.fromEntries((e.result["split"]["tr-1"].assignments as Row[]).map((r) => [r["cutoff_id"], `${r["split"]}/${r["status"]}/${r["drop_reason"]}`]));
  eq("t_ok retained, t_cross LABEL_WINDOW", [asg["co-t_ok-2025-06-19"], asg["co-t_cross-2025-06-20"]], ["train/retained/null", "train/dropped/LABEL_WINDOW"]);
  eq("v_ok retained, v_cross LABEL_WINDOW", [asg["co-v_ok-2025-10-20"], asg["co-v_cross-2025-10-21"]], ["validation/retained/null", "validation/dropped/LABEL_WINDOW"]);
  eq("G1 train row GROUP_TEST; G2 train row GROUP_VALIDATION and its validation row retained", [asg["co-G1-2025-06-01"], asg["co-G2-2025-06-01"], asg["co-G2-2025-10-20"]], ["train/dropped/GROUP_TEST", "train/dropped/GROUP_VALIDATION", "validation/retained/null"]);
  eq("label purge takes precedence over the group purge (G3 train, G4 validation)", [asg["co-G3-2025-06-20"], asg["co-G4-2025-10-21"]], ["train/dropped/LABEL_WINDOW", "validation/dropped/LABEL_WINDOW"]);
  eq("a validation row dropped by the label window still counts as the account's validation row (G6 train -> GROUP_VALIDATION)", asg["co-G6-2025-06-01"], "train/dropped/GROUP_VALIDATION");
  eq("G11 validation row GROUP_TEST; the test rows are retained even though their windows pass test_end; 2026-06-01 is outside", [asg["co-G11-2025-10-20"], asg["co-G1-2026-03-15"], asg["co-G3-2026-03-15"], asg["co-G12-2026-06-01"]], ["validation/dropped/GROUP_TEST", "test/retained/null", "test/retained/null", "outside/retained/null"]);
  eq("counts by part", e.result["split"]["tr-1"].counts, {
    train: { total: 6, retained: 1, label_window: 2, group_test: 1, group_validation: 2 }, validation: { total: 6, retained: 2, label_window: 3, group_test: 1, group_validation: 0 },
    test: { total: 4, retained: 4, label_window: 0, group_test: 0, group_validation: 0 }, outside: { total: 1, retained: 1, label_window: 0, group_test: 0, group_validation: 0 } });
  eq("embargo is horizon + grace = 104 days", e.result["split"]["tr-1"].embargo_days, 104);
}
// 20. refusal rules of the commands
world("the command refusals: fit rows, calibration rows, threshold, basis, unknown run and scenario");
{
  const train = new Set(["a", "b"]), validation = new Set(["v1", "v2"]);
  eq("fit-preprocessing with a validation and a test row -> LEAKAGE listing exactly those", refusal(() => checkFitRows(["a", "v1", "t1"], train)), { code: "LEAKAGE", offending: [{ item: "v1", code: "NOT_TRAINING_ROW" }, { item: "t1", code: "NOT_TRAINING_ROW" }] });
  eq("calibration evaluated on its own fit rows -> CALIBRATION_ON_FIT_ROWS", refusal(() => checkCalibrationRows(["v1", "v2"], ["v2", "t1"], validation)), { code: "CALIBRATION_ON_FIT_ROWS", offending: [{ item: "v2", code: "IN_FIT_ROWS" }] });
  eq("calibration fitted on a non-validation row -> LEAKAGE; a clean request passes", [refusal(() => checkCalibrationRows(["v1", "a"], ["t1"], validation))!.code, refusal(() => checkCalibrationRows(["v1", "v2"], ["t1"], validation))], ["LEAKAGE", null]);
  eq("a threshold chosen on the test set -> THRESHOLD_ON_TEST (P10-TEST-06); on validation it passes", [refusal(() => checkThreshold("capacity", "test")), refusal(() => checkThreshold("capacity", "validation"))], [{ code: "THRESHOLD_ON_TEST", offending: [{ item: "capacity", code: "SELECTED_ON_TEST" }] }, null]);
  eq("a responsiveness or uplift basis -> RISK_NOT_RESPONSIVENESS (P10-TEST-09); risk_ranking passes", [refusal(() => checkBasis("responsiveness"))!.code, refusal(() => checkBasis("uplift"))!.code, refusal(() => checkBasis("risk_ranking"))], ["RISK_NOT_RESPONSIVENESS", "RISK_NOT_RESPONSIVENESS", null]);
  const w = scored(["0.900000", "0.500000", "0.100000"], [1, 0, 0], SC("sc-5", 5), JAN, {
    requests: [{ request_id: "r1", command: "fit-preprocessing", training_run_id: "nope", fit_rows: [] }, { request_id: "r2", command: "prioritize-outreach", training_run_id: "tr-1", scenario_id: "nope", prediction_at: T(JAN) },
      { request_id: "r3", command: "prioritize-outreach", training_run_id: "tr-1", scenario_id: "sc-5", prediction_at: T(JAN) }, { request_id: "r4", command: "select-threshold", training_run_id: "tr-1", parameter: "capacity", selected_on: "test" }] });
  const cmds = dumped("requests", w, run(w)).result["commands"] as Row[];
  eq("unknown run, unknown scenario, capacity 5 of 3, threshold on test", cmds.map((c) => [c["status"], c["reason_code"], c["offending"]]), [
    ["refused", "UNKNOWN_TRAINING_RUN", [{ item: "nope", code: "UNKNOWN_TRAINING_RUN" }]], ["refused", "UNKNOWN_SCENARIO", [{ item: "nope", code: "UNKNOWN_SCENARIO" }]],
    ["refused", "CAPACITY_EXCEEDS_POPULATION", [{ item: "sc-5", code: "CAPACITY_5_GT_3" }]], ["refused", "THRESHOLD_ON_TEST", [{ item: "capacity", code: "SELECTED_ON_TEST" }]]]);
}
// 21. PSI
world("the population stability index: hand-worked cases, floor, empty cohort");
{
  // [10,10] vs [11,9]: a=.55 e=.5: .05 ln 1.1 = 0.0047655; a=.45 e=.5: -.05 ln .9 = 0.0052680; PSI 0.010034.
  // [1,1] vs [2,0]: bins .5/.5 vs 1/0 -> 0 floored to 0.0001: .5 ln 2 = 0.3465736 and (0.0001 - .5) ln(0.0001 / .5) = 4.2577449; PSI 4.604318, above 0.2. Reversing the roles gives the same (floored on the expected side).
  const driftOf = (refCounts: number[], curCounts: number[]): Row => {
    // build a world whose two cutoff sets have usage_events_30d counts per account matching the bins [0,1), [1,inf): count 0 -> no usage events (value 0), count 1 -> one event in the last 30 days
    const accts: Row[] = [], subs: Row[] = [], cuts: Row[] = [], uses: Row[] = [];
    let n = 0;
    const add = (at: string, counts: number[]): void => counts.forEach((c, bin) => { for (let k = 0; k < c; k++) { n++; accts.push(acct(n)); subs.push(sub(`s${n}`, n, "start", "2024-06-01")); cuts.push(cut(n, at)); if (bin === 1) uses.push(use(`u${n}`, n, plus(at, -5))); } });
    add("2025-03-01", refCounts); add(JAN, curCounts);
    const w = base({ accounts: accts, subscription_events: subs, prediction_cutoffs: cuts, usage_events: uses, scope: { training_run_id: "tr-1", sets: [set(JAN)],
      drift: { feature: "usage_events_30d", reference_prediction_at: T("2025-03-01"), bins: [{ label: "0", lower: 0, upper: 1 }, { label: "1+", lower: 1, upper: null }], floor: "0.000100", threshold: "0.200000" } } });
    return dumped("psi", w, run(w)).result["cutoff_sets"][T(JAN)]["population_drift"];
  };
  const a = driftOf([10, 10], [11, 9]);
  eq("[10,10] vs [11,9]: PSI 0.010034, terms 0.0047655090 and 0.0052680258, below the threshold", [a["psi"], a["bins"].map((b: Row) => b["term"]), a["exceeds_threshold"], a["diagnostic_only"]], ["0.010034", ["0.0047655090", "0.0052680258"], false, true]);
  const b = driftOf([1, 1], [2, 0]);
  eq("[1,1] vs [2,0]: the empty current bin is floored (flagged), PSI 4.604318 exceeds 0.2", [b["psi"], b["bins"].map((x: Row) => [x["term"], x["floored"]]), b["exceeds_threshold"]], ["4.604318", [["0.3465735903", false], ["4.2577448764", true]], true]);
  const c = driftOf([2, 0], [1, 1]);
  eq("[2,0] vs [1,1]: floored on the expected side, same PSI", [c["psi"], c["bins"][1]["floored"]], ["4.604318", true]);
  const d = driftOf([3, 5], [3, 5]);
  eq("identical cohorts: PSI 0.000000 and every term prints as Python prints a zero Decimal quantized to 10 places", [d["psi"], d["bins"].map((x: Row) => x["term"])], ["0.000000", ["0E-10", "0E-10"]]);
  const e = driftOf([2, 2], [0, 0]);
  eq("an empty current cohort: PSI is null (unknown), nothing exceeds", [e["psi"], e["exceeds_threshold"], e["bins"]], [null, null, []]);
}
// 22. freshness and publications
world("freshness: completed publications only, none after as_of, data freshness from the newest availability <= as_of");
{
  // as_of 2026-05-01. P1 completed 01-01 02:00, P2 completed 02-01 02:00 (latest), P3 incomplete (one account unscored) 03-01, P4 completed but published 2026-06-01 (after as_of: ignored).
  // scoring freshness = floor((05-01 00:00 - 02-01 02:00) / 1 h) = 89 days x 24 - 2 = 2134 h. The newest event available <= as_of is 04-20 12:30:30; one event is available 2026-05-02 (ignored): data freshness = 10 d 11 h 29 m 30 s -> floor = 251 h.
  const cuts = (at: string): Row[] => [1, 2].map((i) => cut(i, at));
  const pubs: Row[] = [
    { publication_id: "P1", training_run_id: "tr-1", prediction_at: T("2026-01-01"), published_at: T("2026-01-01T02:00:00Z"), status: "completed" }, { publication_id: "P2", training_run_id: "tr-1", prediction_at: T("2026-02-01"), published_at: T("2026-02-01T02:00:00Z"), status: "completed" },
    { publication_id: "P3", training_run_id: "tr-1", prediction_at: T("2026-03-01"), published_at: T("2026-03-01T02:00:00Z"), status: "completed" }, { publication_id: "P4", training_run_id: "tr-1", prediction_at: T("2026-04-01"), published_at: T("2026-06-01T02:00:00Z"), status: "completed" }];
  const w = base({ accounts: [acct(1), acct(2)], subscription_events: [sub("s1", 1, "start", "2024-06-01"), sub("s2", 2, "start", "2024-06-01")], usage_events: [use("u1", 1, "2026-04-20T12:30:30Z"), use("u2", 1, "2026-04-30", "2026-05-02")],
    prediction_cutoffs: [...cuts("2026-01-01"), ...cuts("2026-02-01"), ...cuts("2026-03-01"), ...cuts("2026-04-01")], training_runs: [RUN], scoring_publications: pubs,
    predictions: [...cuts("2026-01-01"), ...cuts("2026-02-01"), cut(1, "2026-03-01"), ...cuts("2026-04-01")].map((c) => pred(c["account_id"], (c["prediction_at"] as string).slice(0, 10), "0.100000")), scope: { training_run_id: "tr-1", sets: [] } });
  const e = dumped("freshness", w, run(w));
  eq("publication status is derived: P3 is incomplete (1 of 2 scored)", e.result["scoring_publications"].map((p: Row) => [p["publication_id"], p["eligible"], p["scored"], p["status"]]), [["P1", 2, 2, "completed"], ["P2", 2, 2, "completed"], ["P3", 2, 1, "incomplete"], ["P4", 2, 2, "completed"]]);
  eq("scoring freshness 2134 h from P2; data freshness 251 h from 2026-04-20T12:30:30Z", [e.result["freshness"].latest_completed_publication_id, e.result["freshness"].scoring_hours, e.result["freshness"].data_hours, e.result["freshness"].latest_available_at], ["P2", 2134, 251, "2026-04-20T12:30:30Z"]);
}
// 23. economics
world("economics: one rounding at the total, negative values, boundaries of the assumed effect");
{
  const q = (ps: string[]): { pstr: string; account_id: number }[] => ps.map((p, i) => ({ pstr: p, account_id: i + 1 }));
  // three accounts at .333333, effect .15, margin 99.99, cost 4.75: each .333333 x .15 x 99.99 - 4.75 = 0.2494950005 (value_exact 0.249495), total 0.7484850015 -> 0.75; budget 14.25.
  const a = economics(SC("x", 3, "4.75", "0.15", "99.99"), q(["0.333333", "0.333333", "0.333333"]));
  eq("per-account terms keep 6 places, the total is rounded once", [a.terms.map((t) => t.value_exact), a.expected_value, a.contact_budget], [["0.249495", "0.249495", "0.249495"], "0.75", "14.25"]);
  // p .1, effect .2, margin 10, cost 8: 0.2 - 8 = -7.80
  eq("a negative expected value keeps its sign", economics(SC("x", 1, "8.00", "0.2", "10.00"), q(["0.100000"])).expected_value, "-7.80");
  // half-way totals round away from zero: +0.125 -> 0.13, -0.125 -> -0.13
  eq("0.125 -> 0.13 and -0.125 -> -0.13 (ROUND_HALF_UP)", [economics(SC("x", 1, "0", "1", "1.25"), q(["0.100000"])).expected_value, economics(SC("x", 1, "0.375", "0.5", "1"), q(["0.500000"])).expected_value], ["0.13", "-0.13"]);
  eq("effect 0: every contact only costs; effect 1: the retained probability is the risk itself", [economics(SC("x", 2, "3.00", "0", "100"), q(["0.5", "0.5"])).expected_value, economics(SC("x", 1, "0", "1", "100"), q(["0.250000"])).expected_value], ["-6.00", "25.00"]);
  eq("no treatment effect is estimated, the label says hypothetical", [a.treatment_effect_estimate, a.label, a.assumption_based], [null, "hypothetical", true]);
}
// 24. stored derived rows that disagree with the rebuilt ones
world("consistency: tampered stored rows are listed, nothing is silently trusted");
{
  const w = scored(["0.800000", "0.200000"], [1, 0], SC("sc-1", 1));
  const good = run(w);
  const snap = (): Row => JSON.parse(JSON.stringify(w));
  const fr1 = { feature_row_id: "fr1", cutoff_id: `co-1-${JAN}`, feature_version: "fv-1", features_json: good.world.analyse(`co-1-${JAN}`).features, max_available_at: null };
  const lb1 = { label_id: "lb1", cutoff_id: `co-1-${JAN}`, churned: true, mature: true, label_end: "2026-04-15T00:00:00Z" };
  const ok = snap(); ok["feature_rows"] = [fr1]; ok["labels"] = [lb1]; ok["outreach_events"] = [{ outreach_event_id: "oe0", account_id: 1, scenario_id: "sc-1", action: "propose_contact", status: "draft" }];
  eq("untouched stored rows are consistent", Object.values(run(ok).result["consistency"]).flat(), []);
  const bad = snap();
  bad["feature_rows"] = [{ ...fr1, features_json: { ...(fr1.features_json as Row), usage_events_30d: 9 } }];
  bad["labels"] = [{ ...lb1, churned: false }];
  bad["prediction_cutoffs"][0]["horizon_end"] = "2026-04-02T00:00:00Z";
  bad["predictions"][1]["config_hash"] = "other";
  bad["scoring_publications"] = [{ publication_id: "sp", training_run_id: "tr-1", prediction_at: T(JAN), published_at: "2026-01-01T02:00:00Z", status: "incomplete" }];
  bad["split_assignments"] = [{ assignment_id: "sa1", training_run_id: "tr-1", cutoff_id: `co-1-${JAN}`, split: "test", status: "retained", drop_reason: null }];
  bad["outreach_events"] = [{ outreach_event_id: "oe1", account_id: 2, scenario_id: "sc-1", action: "propose_contact", status: "draft" }];
  const c = dumped("consistency", bad, run(bad, { "tr-1": "not-the-hash" })).result["consistency"];
  eq("every kind of disagreement is listed once", c, { cutoff_windows_mismatched: [`co-1-${JAN}`], feature_rows_mismatched: ["fr1"], labels_mismatched: ["lb1"], split_assignments_mismatched: ["sa1"], scoring_publications_mismatched: ["sp"],
    config_hash_mismatched: ["tr-1"], outreach_queue_mismatched: ["sc-1"], predictions_citation_mismatched: [`pr-2-${JAN}`] });
}
// 25. ids that are strings; the documented tie rule compares code points
world("string account ids: ties break by code-point order of the id, not by natural order");
{
  const w = base({ accounts: [acct("a-2"), acct("a-10"), acct("a-1")], subscription_events: ["a-2", "a-10", "a-1"].map((a) => sub(`s-${a}`, a, "start", "2024-06-01")), prediction_cutoffs: ["a-2", "a-10", "a-1"].map((a) => cut(a, JAN)),
    training_runs: [RUN], predictions: ["a-2", "a-10", "a-1"].map((a) => pred(a, JAN, "0.400000")), scope: { training_run_id: "tr-1", sets: [set(JAN)] } });
  eq("ranking at equal probability: a-1, a-10, a-2", S(dumped("string ids", w, run(w)))["ranking"].map((r: Row) => r["account_id"]), ["a-1", "a-10", "a-2"]);
}
// 26. one prediction per (run, cutoff): the last one stored wins, as in the Python dict
world("two predictions for one (run, cutoff): the later row in the file is the one used");
{
  const w = scored(["0.100000", "0.900000"], [0, 1]);
  w["predictions"].push({ ...pred(1, JAN, "0.950000"), prediction_id: "pr-dup" });
  const s = S(dumped("duplicate prediction", w, run(w)));
  eq("account 1 is ranked with 0.950000", s["ranking"].map((r: Row) => [r["account_id"], r["probability"]]), [[1, "0.950000"], [2, "0.900000"]]);
}
// 27. time zones and fractions in instants
world("instants: a zone offset is normalised, a fraction is kept to the microsecond, naive and impossible instants are refused");
{
  const w = base({ accounts: [acct(1)], subscription_events: [sub("s1", 1, "start", "2024-06-01")], prediction_cutoffs: [cut(1, JAN)],
    usage_events: [use("u1", 1, "2025-12-31T23:30:00+02:00"), use("u2", 1, "2025-12-31T23:59:59.999999Z"), use("u3", 1, "2026-01-01T00:00:00.000001Z")] });
  const r = run(w).world.analyse(`co-1-${JAN}`);
  eq("21:30Z and 23:59:59.999999Z are inside the window; 00:00:00.000001 after the cutoff is outside; days_since is floored (0)", [r.features!["usage_events_30d"], r.features!["days_since_last_usage"], r.max_available_at], [2, 0, "2025-12-31T23:59:59.999999Z"]);
  const bad = base({ accounts: [acct(1)], subscription_events: [sub("s1", 1, "start", "2024-06-01")], usage_events: [{ ...use("u1", 1, "2025-12-01"), event_at: "2025-12-01T00:00:00" }, { ...use("u2", 1, "2025-12-01"), event_at: "2025-02-30T00:00:00Z" }] });
  eq("a naive instant and 02-30 are MALFORMED_RECORD at import", run(bad).ingest.rejected.map((x) => [x.id, x.reason_code]), [["u1", "MALFORMED_RECORD"], ["u2", "MALFORMED_RECORD"]]);
}
// 28. metric functions directly: the evaluated population is the mature, scored one
world("unscored mature rows are excluded from the outcome metrics and counted");
{
  // 4 mature accounts, 3 scored: the unscored one (account 4, churned) is not in AP/Brier, unscored_excluded = 1. Probabilities .9 (y 1), .8 (y 0), .1 (y 0): AP: .9 -> tp1 fp0 P=1, R=1/1 -> 1.0 (positives among evaluated = 1).
  const w = scored(["0.900000", "0.800000", "0.100000", "0.700000"], [1, 0, 0, 1]);
  w["predictions"] = w["predictions"].slice(0, 3);
  const s = S(dumped("unscored", w, run(w)));
  eq("evaluated 3 of 4 mature, 1 excluded and counted; churn rate still uses all 4 mature rows (2/4)", [s["population"].evaluated, s["population"].unscored_excluded, s["churn_rate"]], [3, 1, { value: "0.500000", churned: 2, mature_eligible: 4 }]);
  eq("AP over the 3 evaluated rows = 1.000000 (the one evaluated churner is ranked first); Brier = (.01 + .64 + .01)/3 = 0.220000", [s["average_precision"].value, s["average_precision"].positives, s["brier_score"].value], ["1.000000", 1, "0.220000"]);
}
// 29. direct metric edge: evaluateRanked
world("evaluateRanked directly: K = 0 and K above n are refused, K = n is the whole population");
{
  const it = (p: string, y: boolean, a: number): Item => ({ p: parseFraction(p), pstr: p, y, account_id: a, cutoff_id: `c${a}` });
  const items = [it("0.8", true, 1), it("0.6", false, 2), it("0.4", true, 3), it("0.1", false, 4)];
  const g = (k: number | null): ReturnType<typeof evaluateRanked> => evaluateRanked(items, k);
  eq("K = 0 and K = 5 are not ok; K = 4 is ok with precision = prevalence", [g(0).kOk, g(5).kOk, g(4).kOk, g(4).precision_at_k!["value"], g(null).kOk], [false, false, true, "0.500000", null]);
  eq("the golden ranking: AP 0.833333, Brier 0.192500", [g(2).average_precision.value, g(2).brier_score.value], ["0.833333", "0.192500"]);
  eq("fr and parseFraction agree on exactness", [fr(1n, 3n).n, parseFraction("0.333333").d], [1n, 1000000n]);
  void setMetrics;
}

if (process.env["REVIEW_DUMP"]) { const { writeFileSync } = await import("node:fs"); writeFileSync(process.env["REVIEW_DUMP"], JSON.stringify(dump)); }
console.log(`${worlds} worlds`);
if (failures) { console.log(`FAILED (${failures} of ${checks} checks)`); process.exitCode = 1; } else console.log(`ALL OK (${checks} checks, ${worlds} worlds)`);
