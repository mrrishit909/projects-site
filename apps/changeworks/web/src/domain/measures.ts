// Per-initiative measures inside a scenario: capacity released (P09-MET-04), cost variance on the matured window (P09-MET-07, D-P9-05) and benefit
// realization within one benefit type on matured periods (P09-MET-06, D-P9-12).
import { expandCosts, type Model } from "./cashflow";
import type { Ctx } from "./context";
import { BENEFIT_TYPES, TARGET_NAME, type Row } from "./contract";
import { cmp, dec, div, fr, m4, money, mn, mul, p6, sub, sumFr, type Fr } from "./num";
import { matured, parseTs } from "./time";

export function capacityReleased(ctx: Ctx, sc: Row, iid: string): Row {
  const i = ctx.ini.get(iid)!;
  const base = i["baseline_version"] ? ctx.acc.process_baselines.find((x) => x["initiative_id"] === iid && x["baseline_version"] === i["baseline_version"]) ?? null : null;
  const tgt = ctx.pick(iid, TARGET_NAME, sc);
  const cap: Row = { hours: null, reason: null, baseline_version: i["baseline_version"], target_assumption_id: tgt ? tgt["assumption_id"] : null };
  if (base === null) cap["reason"] = "NO_APPROVED_BASELINE";
  else if (tgt === null || tgt["value"] === null) cap["reason"] = "NO_TARGET_ASSUMPTION";
  else {
    const hrs = div(mul(fr(base["volume"]), sub(fr(base["minutes_per_case"]), dec(tgt["value"]))), fr(60));
    Object.assign(cap, { hours: m4(hrs), volume: base["volume"], baseline_minutes_per_case: base["minutes_per_case"], target_minutes_per_case: tgt["value"] });
  }
  return cap;
}

/** Actual cost minus the approved baseline cost over [0, min(horizon, matured periods)) (narrowed by the window); null with a reason otherwise. */
export function costVariance(ctx: Ctx, sc: Row, iid: string): Row {
  const i = ctx.ini.get(iid)!;
  const wend = Math.min(sc["horizon_periods"], ctx.M);
  const [lo, hi] = ctx.windowPeriods(wend);
  const cv: Row = { window: { from_period: lo, to_period: hi }, baseline_version: i["baseline_version"], approved_baseline_cost: null, actual_cost: null, variance: null, reason: null };
  if (i["baseline_version"] === null) { cv["reason"] = "NO_APPROVED_BASELINE"; return cv; }
  if (hi <= lo) { cv["reason"] = "NO_MATURED_PERIOD"; return cv; }
  const rows = (basis: string, version: string | null): Fr[] => ctx.acc.cost_items
    .filter((c) => c["initiative_id"] === iid && c["cost_basis"] === basis && (version === null || c["baseline_version"] === version))
    .flatMap((c) => expandCosts(c, hi).filter(([, p]) => p >= lo).map(([, , a]) => a));
  const bl = sumFr(rows("planned", i["baseline_version"]));
  const actRows = rows("actual", null);
  cv["approved_baseline_cost"] = money(bl);
  if (!actRows.length) cv["reason"] = "NO_ACTUALS";
  else {
    const act = sumFr(actRows);
    cv["actual_cost"] = money(act);
    cv["variance"] = money(sub(act, bl));
  }
  return cv;
}

/** Observed comparable benefit / planned comparable benefit, within ONE type, matured periods with an observation only. Unobserved matured rows
 * are listed, never counted as 0; the baseline trend sits beside the raw change and the page says "observed, not attributed". */
export function benefitRealization(ctx: Ctx, sc: Row, iid: string, model: Model): [Row, string[]] {
  const H: number = sc["horizon_periods"];
  const realization: Row = {};
  const immature: string[] = [];
  for (const t of BENEFIT_TYPES) {
    const items = ctx.acc.benefit_items.filter((b) => b["initiative_id"] === iid && b["benefit_type"] === t && b["period_index"] < H);
    const comp: [Row, Row][] = [];
    const unobs: string[] = [];
    for (const b of [...items].sort((x, y) => cmp(x["benefit_id"], y["benefit_id"]))) {
      const obs = ctx.acc.benefit_observations.filter((o) => o["benefit_id"] === b["benefit_id"] && parseTs(o["observed_at"]) <= ctx.asOf)
        .sort((x, y) => { const a = parseTs(x["observed_at"]), c = parseTs(y["observed_at"]); return a < c ? -1 : a > c ? 1 : cmp(x["benefit_observation_id"], y["benefit_observation_id"]); });
      if (!matured(ctx.cfg, b["period_index"], ctx.asOf)) { immature.push(...obs.map((o) => o["benefit_observation_id"])); continue; }
      if (!ctx.periodInWindow(b["period_index"])) continue;
      if (obs.length) comp.push([b, obs[obs.length - 1]!]);
      else unobs.push(b["benefit_id"]);
    }
    if (!comp.length && !unobs.length) continue;
    const planned = sumFr(comp.map(([b]) => model.ramped(b)));
    const observed = sumFr(comp.map(([, o]) => dec(o["measured_value"])));
    const trends = comp.filter(([b]) => b["baseline_trend_per_period"] !== null).map(([b]) => dec(b["baseline_trend_per_period"]));
    const trend = trends.length ? sumFr(trends) : null;
    realization[t] = {
      unit: t === "capacity" ? "hours" : "USD", comparable_items: comp.map(([b]) => b["benefit_id"]),
      planned_comparable: comp.length ? money(planned) : null, observed_comparable: comp.length ? money(observed) : null,
      realization: comp.length && planned.n !== 0n ? p6(div(observed, planned)) : null,
      baseline_trend: mn(trend), observed_above_trend: trend !== null && comp.length ? mn(sub(observed, trend)) : null,
      attribution: "observed, not attributed", matured_unobserved_items: unobs,
    };
  }
  return [realization, immature.sort(cmp)];
}
