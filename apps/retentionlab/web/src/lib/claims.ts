// What the manifest claims, set against what this browser computes from the published files: the five designed relationships (DR-01..DR-05) and
// the twelve injected defects (INJ-01..12). A claim is "recomputed" when the published files carry what is needed to compute it again here;
// the others are the manifest's figures from the full 2,400-account world and are shown as published, not as verified.
import type { Dataset } from "../data/dataset";
import * as E from "../domain/errors";
import type { Row } from "../domain/models";
import { canon, deepEqual } from "../domain/models";
import { cmpFr, p6, parseFraction, ratio, sub } from "../domain/num";
import { checkBasis, checkCalibrationRows, checkCapacity, checkFeatureRequest, checkFitRows, checkThreshold } from "../domain/rules";
import { retained } from "../domain/split";
import { blockOf, driftByRegion, gapOf, groupGaps, seriesOf } from "./derive";

export interface Claim { id: string; label: string; want: string | number | boolean | null; got: string | number | boolean | null; ok: boolean; recomputed: boolean }
const claim = (id: string, label: string, want: Claim["want"], got: Claim["got"], recomputed = true): Claim => ({ id, label, want, got, ok: recomputed ? want === got : true, recomputed });

/** Flatten a nested JSON value to dotted-path leaves ("realised.logistic_regression.average_precision"). */
export function leavesOf(v: unknown, p = ""): [string, unknown][] {
  if (Array.isArray(v)) return v.flatMap((x, i) => leavesOf(x, `${p}[${i}]`));
  if (v && typeof v === "object") return Object.entries(v).flatMap(([k, x]) => leavesOf(x, p ? `${p}.${k}` : k));
  return [[p, v]];
}

/** Every figure of every designed relationship: recomputed from the published files where they allow it, otherwise shown as published. */
export function designedClaims(ds: Dataset): Claim[] {
  const out: Claim[] = [];
  const man = ds.manifest;
  if (!man || !ds.testRows || !ds.aggregates || !ds.calibration) return out;
  const DR = new Map<string, Row>((man["designed_relationships"] as Row[]).map((d) => [d["id"], d["realised"]]));
  const real = (id: string): Row => DR.get(id)!;
  const rows = ds.testRows;
  const pop = ds.populations[0]!;
  // DR-01: average precision and Brier per model on the whole test range, the margins and whether each stated margin is met
  const models: [string, string][] = [["random_baseline", "random_baseline"], ["business_rule", "business_rule"], ["logistic_regression", "logistic_calibrated"]];
  const blocks: Record<string, ReturnType<typeof blockOf>> = {};
  for (const [name, key] of models) {
    const b = (blocks[name] = blockOf(seriesOf(pop, key)));
    const r = real("DR-01")[name];
    out.push(claim("DR-01", `${name} average precision`, r["average_precision"], b.average_precision), claim("DR-01", `${name} Brier score`, r["brier_score"], b.brier_score),
      claim("DR-01", `${name} rows`, r["n"], b.n), claim("DR-01", `${name} churners`, r["positives"], b.positives), claim("DR-01", `${name} prevalence`, r["prevalence"], b.prevalence));
  }
  const lr = blocks["logistic_regression"]!, ru = blocks["business_rule"]!, ra = blocks["random_baseline"]!;
  const margins: Record<string, string> = {
    ap_over_rule: p6(sub(parseFraction(lr.average_precision!), parseFraction(ru.average_precision!)))!, ap_over_random: p6(sub(parseFraction(lr.average_precision!), parseFraction(ra.average_precision!)))!,
    brier_under_rule: p6(sub(parseFraction(ru.brier_score!), parseFraction(lr.brier_score!)))!, brier_under_random: p6(sub(parseFraction(ra.brier_score!), parseFraction(lr.brier_score!)))!,
  };
  for (const [k, v] of Object.entries(margins)) {
    out.push(claim("DR-01", `margin ${k}`, real("DR-01")["margins"][k], v));
    out.push(claim("DR-01", `stated margin ${k} met`, real("DR-01")["met"][k], cmpFr(parseFraction(v), parseFraction(real("DR-01")["stated_margins"][k])) >= 0));
  }
  // DR-02: the gap between mean predicted and observed churn, overall, by segment and by region (percentage points)
  const r2 = real("DR-02");
  const gaps = (label: string, got: Record<string, ReturnType<typeof gapOf>>, want: Row): void => {
    for (const [g, w] of Object.entries(want)) for (const f of ["gap_pp", "mean_predicted", "n", "observed_rate", "positives"] as const) out.push(claim("DR-02", `${label} ${g} ${f}`, w[f], got[g]![f] as never));
  };
  gaps("segment", groupGaps(rows, "segment"), r2["by_segment"]);
  gaps("region", groupGaps(rows, "region"), r2["by_region"]);
  gaps("overall", { overall: gapOf(rows) }, { overall: r2["overall"] });
  gaps("uncalibrated overall", { overall: gapOf(rows, "logistic_uncalibrated") }, { overall: r2["uncalibrated_overall"] });
  const others = Object.entries(groupGaps(rows, "segment")).filter(([g]) => g !== r2["segment"]).map(([, g]) => g.gap_pp!);
  const largest = others.map((g) => g.replace("-", "")).reduce((a, b) => (cmpFr(parseFraction(a), parseFraction(b)) >= 0 ? a : b));
  out.push(claim("DR-02", "largest other segment absolute gap", r2["largest_other_segment_abs_gap_pp"], largest));
  // DR-03: PSI of the apac cohort against its 2026-02-01 cohort; the four test cutoffs are recomputed, the later ones are the manifest's
  const r3 = real("DR-03");
  const drift = driftByRegion(rows, 4);
  out.push(claim("DR-03", "before change, reference cutoff", r3["before_change_psi"][0], drift[0]!.apac.psi), claim("DR-03", "before change, 2026-03-01", r3["before_change_psi"][1], drift[1]!.apac.psi),
    claim("DR-03", "first cutoff after the change (2026-05-01)", r3["after_change_psi"][0], drift[3]!.apac.psi));
  (r3["after_change_psi"] as string[]).slice(1).forEach((v, i) => out.push(claim("DR-03", `after change, cutoff ${["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"][i]} (not in the test table)`, v, v, false)));
  out.push(claim("DR-03", "whole population stays below the threshold in the test range", true, drift.every((d) => d.all_accounts.exceeds === false)));
  // DR-04: the manifest's counts, divided here; the changed features themselves need the full event history
  const r4 = real("DR-04");
  for (const e of ["billing_events", "subscription_events", "support_events", "usage_events"]) out.push(claim("DR-04", `${e} late share`, r4["realised"][e]["share"], p6(ratio(r4["realised"][e]["late_one_day_or_more"], r4["realised"][e]["events"]))));
  out.push(claim("DR-04", "share of test rows whose features change if available_at is ignored", r4["share_of_test_rows_changed"], p6(ratio(r4["test_rows_features_change_if_ignored"], r4["test_rows"]))));
  out.push(claim("DR-04", "test rows in this table", r4["test_rows"], rows.length));
  for (const [f, n] of Object.entries(r4["features_flipped"] as Record<string, number>)) out.push(claim("DR-04", `rows where ${f} would flip (full-world count)`, n, n, false));
  // DR-05: the censored tail, from the per-cutoff aggregates
  const r5 = real("DR-05");
  const cs = ds.aggregates["cutoffs"] as Row[];
  const sum = (k: string): number => cs.reduce((s, c) => s + c["population"][k], 0);
  out.push(claim("DR-05", "eligible rows", r5["eligible_rows"], sum("eligible")), claim("DR-05", "censored rows", r5["censored_rows"], sum("censored")),
    claim("DR-05", "censored share", r5["censored_share"], p6(ratio(sum("censored"), sum("eligible")))), claim("DR-05", "mature churn rate", r5["mature_churn_rate"], p6(ratio(sum("churned"), sum("mature")))));
  for (const [at, v] of Object.entries(r5["churn_rate_if_censored_were_non_churn"] as Record<string, string>)) out.push(claim("DR-05", `churn rate at ${at.slice(0, 10)} if the censored rows were non-churn`, v, v, false));
  return out;
}

export interface InjectionCheck { inj: string; test: string; scope: string; path: string; want: unknown; got: unknown; ok: boolean }
/** Evaluate each injection's declared checks against the facts the manifest recorded ("INJ-01.refusal.code", "...#len" for a length). */
export function injectionChecks(ds: Dataset): InjectionCheck[] {
  const out: InjectionCheck[] = [];
  for (const x of (ds.injections?.["injections"] ?? []) as Row[]) {
    for (const c of x["checks"] as Row[]) {
      const segs = String(c["path"]).split(".").slice(1);
      let cur: unknown = (x["facts"] as Row)[c["scope"]];
      let len = false;
      for (let s of segs) {
        if (s.endsWith("#len")) { len = true; s = s.slice(0, -4); }
        cur = cur && typeof cur === "object" ? (cur as Row)[s] : undefined;
      }
      const got = len ? (Array.isArray(cur) ? cur.length : undefined) : cur;
      out.push({ inj: x["id"], test: x["test"], scope: c["scope"], path: c["path"], want: c["equals"], got: got === undefined ? null : got, ok: deepEqual(got === undefined ? null : got, c["equals"]) });
    }
  }
  return out;
}

export interface Replay { event: string; injection: string; command: string; expected: string | null; got: string | null; ok: boolean; input: string }
/** Re-run the recorded replay requests that the domain's own rules answer (feature requests, fit rows, calibration rows, thresholds, basis,
 * capacity) in this browser and compare the refusal code with the one the API returned. The requests that need the server are not replayed. */
export function replayRefusals(ds: Dataset): Replay[] {
  const out: Replay[] = [];
  if (!ds.injectionEvents) return out;
  const w = ds.primary.world;
  const [splitRows] = ds.primary.splits.get(ds.runId)!;
  const queuePop = (ds.setAt("2026-09-01T00:00:00Z")["population"]["scored"]) as number;
  for (const ev of ds.injectionEvents["events"] as Row[]) {
    for (const st of ev["steps"] as Row[]) {
      if (st["kind"] !== "command") continue;
      const inp: Row = st["input"]["input"];
      let got: string | null = null, tried = true;
      try {
        switch (st["command"]) {
          case "build-point-in-time-features": if (inp["fields"]) checkFeatureRequest(w.registry, inp["fields"]); else tried = false; break;
          case "fit-preprocessing": if (inp["fit_rows"]) checkFitRows(inp["fit_rows"], retained(splitRows, "train")); else tried = false; break;
          case "calibrate-model": if (inp["fit_rows"]) checkCalibrationRows(inp["fit_rows"], inp["evaluation_rows"], retained(splitRows, "validation")); else tried = false; break;
          case "simulate-economics": checkThreshold("capacity", inp["scenario"]["selected_on"] ?? "validation"); break;
          case "prioritize-outreach": if (inp["basis"]) checkBasis(inp["basis"]); checkCapacity(inp["scenario"]["scenario_id"], inp["scenario"]["capacity"], queuePop); break;
          default: tried = false;
        }
      } catch (e) {
        if (!(e instanceof E.DomainError)) throw e;
        got = e.code;
      }
      if (!tried) continue;
      const expected = (st["expected_rules"] as string[] | undefined)?.[0] ?? null;
      out.push({ event: ev["event_id"], injection: ev["injection"], command: st["command"], expected, got, ok: expected === got, input: canon(inp).slice(0, 160) });
    }
  }
  return out;
}

/** Every leaf of two JSON values compared by path (the comparison the golden check makes, run here against the fixture's expected.json). */
export function leafDiff(got: unknown, want: unknown): { total: number; bad: string[] } {
  const flat = (v: unknown, p: string, out: Map<string, unknown>): Map<string, unknown> => {
    if (Array.isArray(v)) { if (v.length === 0) out.set(p, "[]"); v.forEach((x, i) => flat(x, `${p}[${i}]`, out)); }
    else if (v && typeof v === "object") { const e = Object.entries(v); if (e.length === 0) out.set(p, "{}"); for (const [k, x] of e) flat(x, `${p}.${k}`, out); }
    else out.set(p, v);
    return out;
  };
  const g = flat(JSON.parse(JSON.stringify(got)), "", new Map()), w = flat(want, "", new Map());
  const bad: string[] = [];
  for (const k of new Set([...g.keys(), ...w.keys()])) if (!g.has(k) || !w.has(k) || g.get(k) !== w.get(k)) bad.push(k);
  return { total: w.size, bad };
}
