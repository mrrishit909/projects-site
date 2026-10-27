// The evaluation context of one metrics computation: the population, `as_of`, the optional window and the lookups every metric shares.
import { type Row } from "./contract";
import type { Population } from "./ingest";
import { cmp, dec, type Fr } from "./num";
import { maturedCount, parseTs, periodStartInstant, type Instant } from "./time";

export type Window = readonly [Instant | null, Instant | null];

export class Ctx {
  readonly acc: Population["acc"];
  readonly cfg: Row;
  readonly window: Window | null;
  readonly ini: Map<string, Row>;
  readonly scenarios: Row[];
  /** leading matured periods, never more than the longest horizon */
  readonly M: number;

  constructor(readonly pop: Population, readonly asOf: Instant, window?: Window | null, scenarioIds?: readonly string[] | null) {
    this.acc = pop.acc;
    this.cfg = pop.config;
    this.window = window && (window[0] !== null || window[1] !== null) ? window : null;
    this.ini = new Map(this.acc.initiatives.map((i) => [i["initiative_id"] as string, i]));
    this.scenarios = this.acc.scenario_versions.filter((s) => !scenarioIds || scenarioIds.includes(s["scenario_id"])).sort((a, b) => cmp(a["scenario_id"], b["scenario_id"]));
    const cap = this.acc.scenario_versions.reduce((m, s) => Math.max(m, s["horizon_periods"] as number), 0);
    this.M = maturedCount(this.cfg, asOf, cap);
  }

  // -- time
  /** An instant that exists at as_of and lies in the window (half-open [from, to)). */
  tsVisible(ts: string): boolean {
    const t = parseTs(ts);
    if (t > this.asOf) return false;
    return this.tsInWindow(t);
  }
  tsInWindow(t: Instant): boolean {
    if (this.window === null) return true;
    const [lo, hi] = this.window;
    return (lo === null || t >= lo) && (hi === null || t < hi);
  }
  /** R9-11: an observation exists at as_of when it happened by then AND was recorded by then (`stamp`: its server-recorded instant; absent: the event time), and its event time lies in the window. */
  observationVisible(observedAt: string, stamp: string | null | undefined): boolean {
    const t = parseTs(observedAt);
    if (t > this.asOf || (stamp !== null && stamp !== undefined && parseTs(stamp) > this.asOf)) return false;
    return this.tsInWindow(t);
  }
  // -- the plan as it was when a scenario was built (R9-01)
  created(sc: Row): Instant { return parseTs(sc["created_at"]); }
  /** The cost rows that existed at the scenario's `created_at` (rows with no `recorded_at` are part of the loaded world and always do). */
  costs(sc: Row): Row[] { const t = this.created(sc); return this.acc.cost_items.filter((c) => c["recorded_at"] == null || parseTs(c["recorded_at"]) <= t); }
  benefits(sc: Row): Row[] { const t = this.created(sc); return this.acc.benefit_items.filter((b) => b["recorded_at"] == null || parseTs(b["recorded_at"]) <= t); }
  periodInWindow(p: number): boolean { return this.tsInWindow(periodStartInstant(this.cfg, p)); }
  /** The periods [a, b) of [0, end) whose start lies in the window. */
  windowPeriods(end: number): [number, number] {
    if (this.window === null) return [0, end];
    const ps: number[] = [];
    for (let p = 0; p < end; p++) if (this.periodInWindow(p)) ps.push(p);
    return ps.length ? [ps[0]!, ps[ps.length - 1]! + 1] : [0, 0];
  }

  // -- assumptions (D-P9-14, R9-01): the version the scenario pins, otherwise the latest that existed when the scenario was created
  versions(iid: string | null, name: string): Row[] {
    return this.acc.assumption_versions.filter((a) => a["initiative_id"] === iid && a["name"] === name).sort((a, b) => a["version_number"] - b["version_number"]);
  }
  pick(iid: string, name: string, sc: Row): Row | null {
    const vs = this.versions(iid, name);
    const pinned = vs.filter((a) => (sc["pinned_assumption_ids"] as string[]).includes(a["assumption_id"]));
    if (pinned.length) return pinned[pinned.length - 1]!;
    const t = this.created(sc);
    const known = vs.filter((a) => parseTs(a["created_at"]) <= t);
    return known.length ? known[known.length - 1]! : null;
  }
  assumption(aid: string): Row { return this.acc.assumption_versions.find((a) => a["assumption_id"] === aid)!; }
  /** The effective per-period rate and where it comes from (D-01, D-P9-06). */
  rate(sc: Row): [Fr, string] {
    if (sc["rate_basis"] === this.cfg["period_basis"]) return [dec(sc["discount_rate"]), "declared"];
    const conv = this.assumption(sc["rate_conversion_assumption_id"]);
    return [dec(conv["value"]), "conversion:" + conv["assumption_id"]];
  }
}
