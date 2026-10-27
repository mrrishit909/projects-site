// Every metric of D-03, computed exactly on the frozen 6-place strings (BigInt rationals; BigInt fixed point for the one logarithm of the population
// stability index). No float.
//
// Scope (D-P10-01/02): a cutoff set is the rows sharing one `prediction_at`. Outcome metrics use mature eligible rows with an accepted prediction
// (`unscored_excluded` is published); the churn rate uses all mature eligible rows; missingness, drift and the outreach queue use all eligible rows,
// censored ones included.
import { CAL_BINS, EVENTS, FEATURES } from "./contract";
import * as E from "./errors";
import type { Id, Row } from "./models";
import { cmpId } from "./models";
import { add, cmpFr, div, eqFr, fr, mul, p6, parseFraction, toFraction, pp2, psiTermScaled, quant, ratio, scaledOfFr, scaledToDecimalStr, scaledToString, sub, sumFr, ZERO, money, type Fr } from "./num";
import { hoursBetween, isoZ, parseTs } from "./time";
import type { World, Analysis } from "./world";

/** A scored, evaluated row: the exact probability, the string it was frozen as, the outcome, and the keys the ranking breaks ties on. */
export interface Item { p: Fr; pstr: string; y: boolean; account_id: Id; cutoff_id: string }

/** An item from a frozen probability. The published data carries 6-place strings; a JSON number is accepted as the exact value it denotes and frozen
 * to 6 places for display and for the economics. */
export function itemOf(probability: unknown, y: boolean, accountId: Id, cutoffId: string): Item {
  const p = toFraction(probability);
  return { p, pstr: typeof probability === "string" ? probability : p6(p)!, y, account_id: accountId, cutoff_id: cutoffId };
}
/** Probability descending, ties by account_id ascending (D-P10-03). `extra` breaks a remaining tie (the union of several cutoffs). */
export function rankItems<T extends Item>(items: T[], extra?: (a: T, b: T) => number): T[] {
  return [...items].sort((a, b) => cmpFr(b.p, a.p) || cmpId(a.account_id, b.account_id) || (extra ? extra(a, b) : 0));
}
export interface ApTerm { threshold: string; tp: number; fp: number; precision: string; recall: string; delta_recall: string; contribution: string }
/** scikit-learn `average_precision_score`: the sum over DISTINCT thresholds of (R_n - R_{n-1}) x P_n; tied probabilities are one threshold (so the
 * result does not depend on how account ids break the tie). `items` must be ranked by probability descending. */
export function averagePrecision(items: Item[], positives: number, withTerms = true): { total: Fr | null; terms: ApTerm[] } {
  if (positives === 0) return { total: null, terms: [] };
  let tp = 0, fp = 0, prevTp = 0;
  let total = ZERO;
  const terms: ApTerm[] = [];
  let i = 0;
  while (i < items.length) {
    let j = i;
    while (j < items.length && eqFr(items[j]!.p, items[i]!.p)) j++;
    for (let k = i; k < j; k++) { if (items[k]!.y) tp++; else fp++; }
    const precision = fr(tp, tp + fp), recall = fr(tp, positives);
    const deltaTp = tp - prevTp;
    const contribution = deltaTp === 0 ? ZERO : mul(fr(deltaTp, positives), precision);
    if (deltaTp !== 0) total = add(total, contribution);
    if (withTerms) terms.push({ threshold: p6(items[i]!.p)!, tp, fp, precision: p6(precision)!, recall: p6(recall)!, delta_recall: p6(fr(deltaTp, positives))!, contribution: p6(contribution)! });
    prevTp = tp;
    i = j;
  }
  return { total, terms };
}
export interface CalBin { index: number; lower: string; upper: string; closed_upper: boolean; count: number; mean_predicted: string | null; observed_rate: string | null; gap_pp: string | null }
/** 10 equal-width bins on [0, 1), the last closed; index = floor(10 p) on exact fractions; gap = (mean - observed) x 100 pp. */
export function calibrationBins(items: Item[]): CalBin[] {
  const bins: Item[][] = Array.from({ length: CAL_BINS }, () => []);
  for (const it of items) bins[Math.min(Number((it.p.n * BigInt(CAL_BINS)) / it.p.d), CAL_BINS - 1)]!.push(it);
  return bins.map((b, i) => {
    const mean = b.length ? div(sumFr(b.map((x) => x.p)), fr(b.length)) : null;
    const observed = b.length ? fr(b.filter((x) => x.y).length, b.length) : null;
    return { index: i, lower: p6(fr(i, CAL_BINS))!, upper: p6(fr(i + 1, CAL_BINS))!, closed_upper: i === CAL_BINS - 1, count: b.length, mean_predicted: p6(mean), observed_rate: p6(observed),
      gap_pp: mean && observed ? pp2(sub(mean, observed)) : null };
  });
}
export interface Economics {
  label: "hypothetical"; assumption_based: true; scenario_id: string; selected_account_ids: Id[];
  assumptions: { contact_cost: string; assumed_effect: string; margin_value: string }; contact_budget: string;
  terms: { account_id: Id; probability: string; value_exact: string }[]; expected_value: string; treatment_effect_estimate: null;
}
/** Contact budget = selected x contact_cost; expected value = sum(probability x assumed_effect x margin_value - contact_cost), the per-account terms
 * unrounded to 6 places and ONE rounding at the total (ROUND_HALF_UP). Hypothetical, assumption-based. */
export function economics(scenario: Row, queue: { pstr: string; account_id: Id }[]): Economics {
  const cost = parseFraction(String(scenario["contact_cost"]), false), effect = parseFraction(String(scenario["assumed_effect"]), false), margin = parseFraction(String(scenario["margin_value"]), false);
  let total = ZERO;
  const terms = queue.map((it) => {
    const value = sub(mul(mul(parseFraction(it.pstr, false), effect), margin), cost);
    total = add(total, value);
    return { account_id: it.account_id, probability: it.pstr, value_exact: quant(value, 6) };
  });
  return { label: "hypothetical", assumption_based: true, scenario_id: scenario["scenario_id"], selected_account_ids: queue.map((q) => q.account_id),
    assumptions: { contact_cost: money(cost), assumed_effect: String(scenario["assumed_effect"]), margin_value: money(margin) },
    contact_budget: money(mul(cost, fr(queue.length))), terms, expected_value: money(total), treatment_effect_estimate: null };
}
export interface PsiBin { label: string; reference_count: number; current_count: number; reference_proportion: string; current_proportion: string; floored: boolean; term: string }
/** PSI = sum (actual - expected) x ln(actual / expected), the natural log in fixed-point BigInt arithmetic at 60 digits; a zero proportion is
 * replaced by `floor` without renormalising (D-P10-10). null when either cohort is empty. `total` is scaled by 10^60. */
export function psi(reference: number[], current: number[], labels: string[], floor: string): { total: bigint; bins: PsiBin[] } | null {
  const rTotal = reference.reduce((a, b) => a + b, 0), cTotal = current.reduce((a, b) => a + b, 0);
  if (rTotal === 0 || cTotal === 0) return null;
  const fl = parseFraction(floor, false);
  let total = 0n;
  const bins = labels.map((label, i): PsiBin => {
    const expected = fr(reference[i]!, rTotal), actual = fr(current[i]!, cTotal);
    const e = expected.n === 0n ? fl : expected, a = actual.n === 0n ? fl : actual;
    const term = psiTermScaled(a, e);
    total += term;
    return { label, reference_count: reference[i]!, current_count: current[i]!, reference_proportion: p6(expected)!, current_proportion: p6(actual)!, floored: expected.n === 0n || actual.n === 0n, term: scaledToDecimalStr(term, 10) };
  });
  return { total, bins };
}
const bound = (x: unknown): Fr | null => (x === null || x === undefined ? null : parseFraction(String(x)));
/** Half-open declared bin [lower, upper); a null value is in no bin. */
export function inBin(value: unknown, b: Row): boolean {
  if (value === null || value === undefined) return false;
  const v = parseFraction(String(value));
  const lo = bound(b["lower"])!, hi = bound(b["upper"]);
  return cmpFr(v, lo) >= 0 && (hi === null || cmpFr(v, hi) < 0);
}

export interface TopK { hits: number; precision_at_k: Row; recall_at_k: Row; risk_lift_at_k: Row }
/** Precision, recall and risk lift at K on a ranked population (1 <= K <= n; the caller refuses anything else with CAPACITY_EXCEEDS_POPULATION). */
export function topK(items: Item[], k: number, positives: number): TopK {
  const n = items.length;
  const hits = items.slice(0, k).filter((i) => i.y).length;
  const topRate = fr(hits, k);
  const overall = ratio(positives, n);
  return {
    hits,
    precision_at_k: { value: p6(topRate), hits, k },
    recall_at_k: { value: p6(ratio(hits, positives)), hits, positives },
    risk_lift_at_k: { value: p6(positives === 0 ? null : div(topRate, overall!)), top_k_rate: p6(topRate), overall_rate: p6(overall), tie_split_at_k: k < n && eqFr(items[k - 1]!.p, items[k]!.p) },
  };
}
/** Cumulative true churners in rank order: element i is the hits among the top i + 1 (for the precision and recall curves). */
export function cumulativeHits(items: Item[]): number[] {
  let h = 0;
  return items.map((i) => (h += i.y ? 1 : 0));
}

/** The metrics of one ranked evaluation population, shared by a cutoff set of a world and by the published test table. */
export function evaluateRanked(items: Item[], k: number | null, withTerms = true) {
  const n = items.length;
  const positives = items.filter((i) => i.y).length;
  const kOk = k === null ? null : n ? 1 <= k && k <= n : false;
  const top = kOk && k !== null ? topK(items, k, positives) : null;
  const ap = averagePrecision(items, positives, withTerms);
  const squares = items.map((it) => { const d = sub(it.p, fr(it.y ? 1 : 0)); return mul(d, d); });
  return {
    n, positives, kOk, precision_at_k: top ? top.precision_at_k : null, recall_at_k: top ? top.recall_at_k : null, risk_lift_at_k: top ? top.risk_lift_at_k : null,
    average_precision: { value: p6(ap.total), prevalence: p6(ratio(positives, n)), positives, n, terms: ap.terms },
    brier_score: { value: p6(n === 0 ? null : div(sumFr(squares), fr(n))), n, terms: withTerms ? squares.map((s) => p6(s)!) : [] },
    calibration: { bin_width: "0.100000", bins: calibrationBins(items) },
  };
}

type Drift = Row;
/** Everything the report says about ONE cutoff set under ONE training run (and one optional scenario). */
export function setMetrics(world: World, runId: string, predictionAt: string, scenarioId: string | null, drift: Drift | null): Row {
  const rows = world.setRows(predictionAt);
  const eligible = rows.filter((r) => r.eligible);
  const mature = eligible.filter((r) => r.mature);
  const scored = eligible.filter((r) => world.pred(runId, r.cutoff_id));
  const evaluated = mature.filter((r) => world.pred(runId, r.cutoff_id));
  const ineligible: Record<string, number> = {};
  for (const r of rows) if (!r.eligible) ineligible[r.ineligible_code!] = (ineligible[r.ineligible_code!] ?? 0) + 1;
  const churned = mature.filter((r) => r.churned).length;
  const out: Row = {
    prediction_at: predictionAt,
    population: { cutoff_rows: rows.length, eligible: eligible.length, ineligible: Object.fromEntries(Object.entries(ineligible).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))),
      mature: mature.length, censored: eligible.length - mature.length, scored: scored.length, evaluated: evaluated.length, unscored_excluded: mature.length - evaluated.length, churned },
    empty_population: eligible.length === 0, empty_evaluation: evaluated.length === 0,
    churn_rate: { value: p6(ratio(churned, mature.length)), churned, mature_eligible: mature.length },
  };
  const late: Record<string, number> = {};
  for (const e of EVENTS) late[e] = eligible.reduce((s, r) => s + r.arrived_late![e], 0);
  late["total"] = EVENTS.reduce((s, e) => s + late[e]!, 0);
  out["late_events"] = late;
  const mk = (r: Analysis): Item => itemOf(world.pred(runId, r.cutoff_id)!["probability"], !!r.churned, r.account_id as Id, r.cutoff_id);
  const items = rankItems(evaluated.map(mk));
  out["ranking"] = items.map((it, i) => ({ rank: i + 1, cutoff_id: it.cutoff_id, account_id: it.account_id, probability: it.pstr, outcome: it.y ? 1 : 0 }));
  const scenario = scenarioId ? world.scenarios.get(scenarioId) : undefined;
  const k: number | null = scenario ? scenario["capacity"] : null;
  const ev = evaluateRanked(items, k);
  const n = items.length;
  out["capacity"] = scenario ? { scenario_id: scenarioId, k, population: n, ok: ev.kOk, refusal: ev.kOk || n === 0 ? null : E.CAPACITY_EXCEEDS_POPULATION } : null;
  out["precision_at_k"] = ev.precision_at_k; out["recall_at_k"] = ev.recall_at_k; out["risk_lift_at_k"] = ev.risk_lift_at_k;
  out["average_precision"] = ev.average_precision; out["brier_score"] = ev.brier_score; out["calibration"] = ev.calibration;
  const queue = rankItems(scored.map(mk));
  out["economics"] = out["outreach_queue"] = null;
  if (scenario && k !== null && 1 <= k && k <= queue.length) {
    out["economics"] = economics(scenario, queue.slice(0, k));
    out["outreach_queue"] = { status: "draft", account_ids: queue.slice(0, k).map((q) => q.account_id), population: queue.length };
  }
  const missing: Record<string, number> = {};
  for (const f of FEATURES) missing[f] = eligible.filter((r) => r.features![f] === null).length;
  const totalMissing = FEATURES.reduce((s, f) => s + missing[f]!, 0);
  out["feature_missingness"] = {
    period: predictionAt.slice(0, 7),
    by_feature: Object.fromEntries(FEATURES.map((f) => [f, { missing: missing[f], total: eligible.length, value: p6(ratio(missing[f]!, eligible.length)) }])),
    overall: { missing: totalMissing, total: eligible.length * FEATURES.length, value: p6(ratio(totalMissing, eligible.length * FEATURES.length)) },
  };
  out["population_drift"] = drift ? driftBlock(world, eligible, drift) : null;
  return out;
}

export function driftBlock(world: World, currentEligible: Analysis[], drift: Drift): Row {
  const reference = world.setRows(drift["reference_prediction_at"]).filter((r) => r.eligible);
  const bins: Row[] = drift["bins"], feature: string = drift["feature"];
  const ref = bins.map((b) => reference.filter((r) => inBin(r.features![feature], b)).length);
  const cur = bins.map((b) => currentEligible.filter((r) => inBin(r.features![feature], b)).length);
  const res = psi(ref, cur, bins.map((b) => b["label"]), drift["floor"]);
  return {
    feature, reference_prediction_at: drift["reference_prediction_at"], reference_rows: ref.reduce((a, b) => a + b, 0), current_rows: cur.reduce((a, b) => a + b, 0),
    psi: res === null ? null : scaledToString(res.total, 6), threshold: drift["threshold"], diagnostic_only: true,
    exceeds_threshold: res === null ? null : res.total > scaledOfFr(parseFraction(drift["threshold"], false)), bins: res === null ? [] : res.bins,
  };
}

export interface Publication { publication_id: string; training_run_id: string; prediction_at: string; published_at: string; eligible: number; scored: number; status: "completed" | "incomplete"; model_name?: string }
/** Scoring publications with a DERIVED status: completed iff at least one eligible account and every eligible account at the set has an accepted
 * prediction of the run (D-P10-12). */
export function publications(world: World): Publication[] {
  return world.acc.scoring_publications.map((sp) => {
    const eligible = world.setRows(sp["prediction_at"]).filter((r) => r.eligible);
    const scored = eligible.filter((r) => world.pred(sp["training_run_id"], r.cutoff_id)).length;
    return { publication_id: sp["publication_id"], training_run_id: sp["training_run_id"], prediction_at: sp["prediction_at"], published_at: sp["published_at"], eligible: eligible.length, scored,
      status: eligible.length && scored === eligible.length ? "completed" : "incomplete" };
  });
}
/** Scoring freshness = as_of - the latest COMPLETED publication (hours, floored); data freshness = as_of - the latest `available_at` ingested.
 * Separate figures; null when there is nothing to measure (D-P10-12). */
export function freshness(world: World, pubs: Publication[]): Row {
  const done = pubs.filter((p) => p.status === "completed" && parseTs(p.published_at) <= world.asOf);
  let latest: Publication | null = null;
  for (const p of done) {
    if (latest === null) { latest = p; continue; }
    const a = parseTs(p.published_at), b = parseTs(latest.published_at);
    if (a > b || (a === b && p.publication_id > latest.publication_id)) latest = p;
  }
  let newest: bigint | null = null;
  for (const e of EVENTS) for (const ev of world.acc[e]) { const t = parseTs(ev["available_at"]); if (t <= world.asOf && (newest === null || t > newest)) newest = t; }
  return {
    as_of: isoZ(world.asOf), scoring_hours: latest === null ? null : hoursBetween(world.asOf, parseTs(latest.published_at)),
    latest_completed_publication_id: latest === null ? null : latest.publication_id, latest_completed_published_at: latest === null ? null : isoZ(parseTs(latest.published_at)),
    data_hours: newest === null ? null : hoursBetween(world.asOf, newest), latest_available_at: isoZ(newest),
  };
}
