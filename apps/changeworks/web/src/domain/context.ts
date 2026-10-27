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
  periodInWindow(p: number): boolean { return this.tsInWindow(periodStartInstant(this.cfg, p)); }
  /** The periods [a, b) of [0, end) whose start lies in the window. */
  windowPeriods(end: number): [number, number] {
    if (this.window === null) return [0, end];
    const ps: number[] = [];
    for (let p = 0; p < end; p++) if (this.periodInWindow(p)) ps.push(p);
    return ps.length ? [ps[0]!, ps[ps.length - 1]! + 1] : [0, 0];
  }

  // -- assumptions (D-P9-14): the version the scenario pins, otherwise the latest
  versions(iid: string | null, name: string): Row[] {
    return this.acc.assumption_versions.filter((a) => a["initiative_id"] === iid && a["name"] === name).sort((a, b) => a["version_number"] - b["version_number"]);
  }
  pick(iid: string, name: string, sc: Row): Row | null {
    const vs = this.versions(iid, name);
    const pinned = vs.filter((a) => (sc["pinned_assumption_ids"] as string[]).includes(a["assumption_id"]));
    return pinned.length ? pinned[pinned.length - 1]! : vs.length ? vs[vs.length - 1]! : null;
  }
  assumption(aid: string): Row { return this.acc.assumption_versions.find((a) => a["assumption_id"] === aid)!; }
  /** The effective per-period rate and where it comes from (D-01, D-P9-06). */
  rate(sc: Row): [Fr, string] {
    if (sc["rate_basis"] === this.cfg["period_basis"]) return [dec(sc["discount_rate"]), "declared"];
    const conv = this.assumption(sc["rate_conversion_assumption_id"]);
    return [dec(conv["value"]), "conversion:" + conv["assumption_id"]];
  }
}
