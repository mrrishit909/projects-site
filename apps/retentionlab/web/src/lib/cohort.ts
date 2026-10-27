// Cohort rows and their statistics: who churned and what the model expected, by plan (segment), region and tenure.
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/models";
import { div, fr, p6, parseFraction, pp2, ratio, sub, sumFr, type Fr } from "../domain/num";
import { parseTs, wholeDays } from "../domain/time";

export interface CRow { account_id: unknown; cut: string; segment: string; region: string; y: boolean; p: Fr }
/** The mature eligible rows with a prediction that the cohort explorer groups: the 1,513-row test table (snapshot) or the golden set. */
export function cohortRows(ds: Dataset): CRow[] {
  if (ds.testRows) {
    const cuts: string[] = (ds.populations[1] ? ds.populations.slice(1).map((p) => p.label.replace("Test cutoff ", "")) : []);
    return ds.testRows.map((r) => ({ account_id: r.account_id, cut: cuts[r.cut] ?? String(r.cut), segment: r.segment, region: r.region, y: r.y === 1, p: parseFraction(r.p.logistic_calibrated, false) }));
  }
  const w = ds.primary.world;
  const out: CRow[] = [];
  for (const at of w.predictionAts()) {
    for (const r of w.setRows(at)) {
      if (!r.eligible || !r.mature) continue;
      const pr = w.pred(ds.runId, r.cutoff_id);
      if (!pr) continue;
      const a = w.accounts.get(r.account_id)!;
      out.push({ account_id: r.account_id, cut: at.slice(0, 10), segment: a["segment"], region: a["region"], y: !!r.churned, p: parseFraction(pr["probability"]) });
    }
  }
  return out;
}
export interface GroupStat { group: string; n: number; churned: number; rate: string | null; mean: string | null; gap: string | null }
export function groupStats(rows: CRow[], key: "segment" | "region" | "cut"): GroupStat[] {
  return [...new Set(rows.map((r) => r[key]))].sort().map((g) => {
    const sub_ = rows.filter((r) => r[key] === g);
    const churned = sub_.filter((r) => r.y).length;
    const mean = sub_.length ? div(sumFr(sub_.map((r) => r.p)), fr(sub_.length)) : null;
    const obs = ratio(churned, sub_.length);
    return { group: g, n: sub_.length, churned, rate: p6(obs), mean: p6(mean), gap: mean && obs ? pp2(sub(mean, obs)) : null };
  });
}
export function overallStat(rows: CRow[]): GroupStat { return groupStats(rows.map((r) => ({ ...r, cut: "all" })), "cut")[0] ?? { group: "all", n: 0, churned: 0, rate: null, mean: null, gap: null }; }

export const TENURE_BANDS: [string, number, number][] = [["under 6 months", 0, 182], ["6 to 12 months", 182, 365], ["1 to 2 years", 365, 730], ["2 years or more", 730, Infinity]];
export interface TenureStat { band: string; n: number; churned: number; rate: string | null; eligible: number }
/** Churn by account tenure at the cutoff, over the published cohort sample (the only place account creation dates are published). */
export function tenureStats(ds: Dataset): TenureStat[] {
  const w = ds.primary.world;
  const tally = TENURE_BANDS.map(([band]) => ({ band, n: 0, churned: 0, eligible: 0 }));
  for (const at of w.predictionAts()) {
    for (const r of w.setRows(at)) {
      if (!r.eligible) continue;
      const days = wholeDays(parseTs(r.prediction_at), parseTs((w.accounts.get(r.account_id) as Row)["created_at"]));
      const i = TENURE_BANDS.findIndex(([, lo, hi]) => days >= lo && days < hi);
      tally[i]!.eligible++;
      if (r.mature) { tally[i]!.n++; if (r.churned) tally[i]!.churned++; }
    }
  }
  return tally.map((t) => ({ ...t, rate: p6(ratio(t.churned, t.n)) }));
}
