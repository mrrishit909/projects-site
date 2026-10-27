// The manifest's designed relationships (DR-01..DR-06) and the generator's defect checks (INJ-01..INJ-12) re-derived from the rows in this
// browser, so the page can show "the manifest says X, the pipeline computed Y". Nothing here is typed in: the wanted values come from the
// manifest, the computed ones from the pipeline.
import type { Dataset } from "../data/dataset";
import { cmp } from "../domain/models";
import { div, fr, h4, p6, sumFr } from "../domain/num";
import { scoreRows, teamVersusRest } from "./derive";

export interface Claim { id: string; label: string; want: string; got: string; ok: boolean }
const J = (v: unknown): string => (typeof v === "string" ? v : JSON.stringify(v));
const mk = (id: string, label: string, want: unknown, got: unknown): Claim => ({ id, label, want: J(want), got: J(got), ok: J(want) === J(got) });

export function designedClaims(ds: Dataset): Claim[] {
  const drs = ds.manifest.designed_relationships ?? [];
  const m = ds.now.metrics;
  const out: Claim[] = [];
  const get = (id: string): Record<string, any> | undefined => drs.find((d) => d.id === id)?.realised as Record<string, any> | undefined; // eslint-disable-line @typescript-eslint/no-explicit-any
  let r = get("DR-01");
  if (r) {
    const w = m["weighted_score"]["datasets"][r["dataset_id"]];
    out.push(mk("DR-01", "weighted score w2", r["weighted_score_w2"], w["value"]));
    out.push(mk("DR-01", "weighted score w1", r["weighted_score_w1"], m["weighted_score"]["by_weight_version"]["w1"][r["dataset_id"]]));
    out.push(mk("DR-01", "critical failures, open critical issues, override", [r["critical_failures"], r["critical_open_issues"], r["critical_override"]], [w["critical_failures"], w["critical_open_issues"], w["critical_override"]]));
    out.push(mk("DR-01", "datasets overridden", r["datasets_overridden"], m["critical_failures"]["datasets_overridden"]));
  }
  r = get("DR-02");
  if (r) {
    out.push(mk("DR-02", "covered and coverage", [r["covered"], r["value"]], [m["ownership_coverage"]["covered"], m["ownership_coverage"]["value"]]));
    out.push(mk("DR-02", "uncovered datasets", r["uncovered"], m["ownership_coverage"]["uncovered"]));
    out.push(mk("DR-02", "inactive owners", r["inactive_owners"], ds.raw.owners.filter((o) => o["active"] === false).map((o) => o["owner_id"]).sort()));
  }
  r = get("DR-03");
  if (r) {
    const rows = scoreRows(ds).filter((x) => x.delta !== null);
    const moved = rows.filter((x) => x.delta!.n !== 0n);
    const big = rows.filter((x) => (x.delta!.n < 0n ? -x.delta!.n : x.delta!.n) * 200n >= x.delta!.d);
    const largest = rows.reduce((a, b) => ((b.delta!.n < 0n ? -b.delta!.n : b.delta!.n) * a.delta!.d > (a.delta!.n < 0n ? -a.delta!.n : a.delta!.n) * b.delta!.d ? b : a));
    const mean = (v: string): string => p6(div(sumFr(rows.map((x) => x.scores[v]!)), fr(rows.length)))!;
    out.push(mk("DR-03", "datasets scored, with a different score, moved by 0.005 or more", [r["datasets_scored"], r["datasets_with_different_score"], r["datasets_moved_at_least_0.005"]], [rows.length, moved.length, big.length]));
    out.push(mk("DR-03", "largest move", r["largest_move"], p6(largest.delta)));
    out.push(mk("DR-03", "mean score w1 and w2", [r["mean_score_w1"], r["mean_score_w2"]], [mean("w1"), mean("w2")]));
    out.push(mk("DR-03", "runs stored under w1 and w2", [r["runs_under_w1"], r["runs_under_w2"]], [ds.raw.rule_runs.filter((x) => x["weight_version"] === "w1").length, ds.raw.rule_runs.filter((x) => x["weight_version"] === "w2").length]));
  }
  r = get("DR-04");
  if (r) {
    const t = teamVersusRest(ds, ds.now.views, r["fast_team"]);
    out.push(mk("DR-04", `${r["fast_team"]} mean hours and resolved`, [r["fast_mean_hours"], r["fast_resolved"]], [t.team === null ? null : h4(t.team), t.teamN]));
    out.push(mk("DR-04", "other teams mean hours and resolved", [r["other_mean_hours"], r["other_resolved"]], [t.rest === null ? null : h4(t.rest), t.restN]));
    out.push(mk("DR-04", "ratio", r["ratio"], t.team && t.rest ? p6(div(t.team, t.rest)) : null));
  }
  r = get("DR-05");
  if (r) {
    const un = ds.now.views.filter((v) => v.cls !== "resolved").sort((a, b) => (a.issue.detected_at < b.issue.detected_at ? -1 : a.issue.detected_at > b.issue.detected_at ? 1 : cmp(a.issue.issue_id, b.issue.issue_id)));
    const lead = un.findIndex((v) => v.cls !== "claimed");
    out.push(mk("DR-05", "unresolved issues", r["unresolved"], un.length));
    out.push(mk("DR-05", "leading run of claimed issues, first not claimed", [r["leading_claimed_run"], r["first_not_claimed"]], [lead, un[lead]?.issue.issue_id]));
    out.push(mk("DR-05", "the oldest 25 are all claimed", r["all_of_the_oldest_25_claimed"], un.slice(0, 25).every((v) => v.cls === "claimed")));
  }
  r = get("DR-06");
  if (r) {
    const p = m["match_precision"], mt = ds.now.matching;
    out.push(mk("DR-06", "candidates, reviewed, approved, rejected, reversals", [r["candidates"], r["reviewed"], r["approved"], r["rejected"], r["reversals"]], [mt["candidates"], mt["reviewed"], mt["approved"], mt["rejected"], mt["merges_reversed"]]));
    out.push(mk("DR-06", "approved correct and precision", [r["approved_correct"], r["precision"]], [p["approved_correct"], p["precision"]]));
    out.push(mk("DR-06", "reviewed correct share", r["reviewed_correct_share"], p["reviewed_correct_share"]));
  }
  return out;
}

export interface InjCheck { inj: string; test: string; name: string; path: string; want: unknown; got: unknown; ok: boolean }
/** The generator's machine-checkable defect checks, evaluated against this browser's computed `golden()` shape. */
export function injectionChecks(ds: Dataset): InjCheck[] {
  const inj = ds.injections?.["injections"] as { id: string; test: string; name: string; checks: { path: string; equals?: unknown; length?: number }[] }[] | undefined;
  if (!inj) return [];
  const shape = ds.goldenShape();
  const out: InjCheck[] = [];
  for (const i of inj) for (const c of i.checks) {
    let v: any = shape; // eslint-disable-line @typescript-eslint/no-explicit-any
    for (const k of c.path.split(".")) v = v?.[k];
    const isLen = c.length !== undefined;
    const got = isLen ? (Array.isArray(v) ? v.length : undefined) : v;
    const want = isLen ? c.length : c.equals;
    out.push({ inj: i.id, test: i.test, name: i.name, path: isLen ? `${c.path} (length)` : c.path, want, got, ok: JSON.stringify(got) === JSON.stringify(want) });
  }
  return out;
}
