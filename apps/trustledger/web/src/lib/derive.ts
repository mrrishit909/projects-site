// Derived figures the views and the checks share. Every number is computed from the pipeline's exact rationals; nothing is typed in.
import type { Dataset } from "../data/dataset";
import type { Computation } from "../domain/metrics";
import type { IssueView } from "../domain/issues";
import { cmp } from "../domain/models";
import { add, div, fr, h4, p6, sub, sumFr, type Fr } from "../domain/num";
import { dimensionScores, score } from "../domain/scoring";

export interface ScoreRow { dataset_id: string; name: string; scores: Record<string, Fr | null>; delta: Fr | null }
/** Exact weighted scores of every dataset under every weight version, and the shift between the first and the last version. */
export function scoreRows(ds: Dataset, comp: Computation = ds.now): ScoreRow[] {
  const pop = ds.result.population;
  const dim = dimensionScores(comp.measures);
  const versions = pop.weight_versions;
  return pop.datasets.map((d) => {
    const scores: Record<string, Fr | null> = {};
    for (const w of versions) scores[w.weight_version] = score(dim[d.dataset_id] ?? {}, w.weights).value;
    const a = scores[versions[0]!.weight_version] ?? null, b = scores[versions[versions.length - 1]!.weight_version] ?? null;
    return { dataset_id: d.dataset_id, name: d.dataset_name, scores, delta: a !== null && b !== null ? sub(b, a) : null };
  }).sort((x, y) => cmp(x.dataset_id, y.dataset_id));
}

export interface TeamRow { team: string; resolved: number; claimed: number; open: number; mean_hours: Fr | null }
/** Resolution by the owner's team (D-08: "one team twice as fast" is by the owner's team on mean resolution hours). */
export function teamRows(ds: Dataset, views: IssueView[]): TeamRow[] {
  const team = new Map(ds.raw.owners.map((o) => [o["owner_id"] as string, o["team"] as string]));
  const acc = new Map<string, { hours: Fr[]; claimed: number; open: number }>();
  for (const v of views) {
    const t = team.get(v.issue.owner_id) ?? "unknown";
    const a = acc.get(t) ?? { hours: [], claimed: 0, open: 0 };
    if (v.cls === "resolved") a.hours.push(v.hours); else if (v.cls === "claimed") a.claimed++; else a.open++;
    acc.set(t, a);
  }
  return [...acc.entries()].map(([t, a]) => ({ team: t, resolved: a.hours.length, claimed: a.claimed, open: a.open, mean_hours: a.hours.length ? div(sumFr(a.hours), fr(a.hours.length)) : null })).sort((x, y) => cmp(x.team, y.team));
}
/** Mean resolution hours of the named team against all other teams together. */
export function teamVersusRest(ds: Dataset, views: IssueView[], name: string): { team: Fr | null; rest: Fr | null; teamN: number; restN: number } {
  const team = new Map(ds.raw.owners.map((o) => [o["owner_id"] as string, o["team"] as string]));
  const mine: Fr[] = [], rest: Fr[] = [];
  for (const v of views) if (v.cls === "resolved") (team.get(v.issue.owner_id) === name ? mine : rest).push(v.hours);
  const mean = (xs: Fr[]): Fr | null => (xs.length ? div(sumFr(xs), fr(xs.length)) : null);
  return { team: mean(mine), rest: mean(rest), teamN: mine.length, restN: rest.length };
}

export const AGE_BUCKETS: { id: string; label: string; maxDays: number | null }[] = [
  { id: "d7", label: "under 7 days", maxDays: 7 }, { id: "d30", label: "7 to 29 days", maxDays: 30 },
  { id: "d60", label: "30 to 59 days", maxDays: 60 }, { id: "d60p", label: "60 days or more", maxDays: null },
];
/** Age bucket of an issue by whole days (exact integer comparison on the exact hours). */
export function ageBucket(hours: Fr): string {
  for (const b of AGE_BUCKETS) if (b.maxDays !== null && hours.n < BigInt(b.maxDays * 24) * hours.d) return b.id;
  return "d60p";
}
export const hoursText = (h: Fr): string => h4(h)!;

/** Fraction helper for the views: `a - b` of two published 6-place strings is never taken; this takes exact values. */
export const deltaText = (d: Fr | null): string | null => (d === null ? null : p6(d));
export { add };

// ---- matching state per candidate (from the decision rows; the synthetic truth is never read here) -------------------------------
export type CandidateState = "unreviewed" | "approved" | "rejected" | "reversed";
export interface CandState { candidate_id: string; state: CandidateState; approve: Row | null; reject: Row | null; reversal: Row | null }
import type { Row } from "../domain/models";
export function candidateStates(ds: Dataset): Map<string, CandState> {
  const out = new Map<string, CandState>();
  for (const c of ds.raw.match_candidates) out.set(c["candidate_id"] as string, { candidate_id: c["candidate_id"] as string, state: "unreviewed", approve: null, reject: null, reversal: null });
  const byMerge = new Map(ds.raw.merge_decisions.map((m) => [m["merge_id"] as string, m]));
  for (const m of ds.raw.merge_decisions) {
    const s = out.get(m["candidate_id"] as string);
    if (!s) continue;
    if (m["decision"] === "approve") s.approve = m;
    else if (m["decision"] === "reject") s.reject = m;
  }
  for (const m of ds.raw.merge_decisions) {
    if (m["decision"] !== "reverse") continue;
    const target = byMerge.get(m["reverses_merge_id"] as string);
    const s = target ? out.get(target["candidate_id"] as string) : undefined;
    if (s && s.approve && s.approve["merge_id"] === target!["merge_id"]) s.reversal = m;
  }
  for (const s of out.values()) s.state = s.approve ? (s.reversal ? "reversed" : "approved") : s.reject ? "rejected" : "unreviewed";
  return out;
}

/** Datasets reachable downstream of `from` over the given edges (breadth first), with the shortest path to each. */
export function downstream(edges: readonly [string, string][], from: readonly string[]): Map<string, string[]> {
  const next = new Map<string, string[]>();
  for (const [a, b] of edges) { if (!next.has(a)) next.set(a, []); next.get(a)!.push(b); }
  for (const v of next.values()) v.sort(cmp);
  const seen = new Map<string, string[]>(from.map((f) => [f, [f]]));
  const queue = [...from];
  while (queue.length) {
    const u = queue.shift()!;
    for (const v of next.get(u) ?? []) if (!seen.has(v)) { seen.set(v, [...seen.get(u)!, v]); queue.push(v); }
  }
  for (const f of from) seen.delete(f);
  return seen;
}
