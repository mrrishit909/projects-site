// Adoption (P09-MET-05), training completion (P09-MET-11), risk exposure (P09-MET-09), readiness (P09-MET-08) and forecast versions (P09-FLOW-10).
// Adoption and training are never substituted for each other; null means unknown, never 0.
import type { Ctx } from "./context";
import { DIMENSIONS, type Row } from "./contract";
import { canon, cmp, cmpNum, dec, ex, fr, m4, money, mn, mul, p6, sub, sumFr, div, type Fr } from "./num";
import { matured, parseTs } from "./time";

const byTime = (tk: string, ik: string) => (x: Row, y: Row): number => { const a = parseTs(x[tk]), b = parseTs(y[tk]); return a < b ? -1 : a > b ? 1 : cmp(x[ik], y[ik]); };
/** Event time, then when it was recorded (a same-day tie goes to the later record, R9-11), then the id. */
const byObservation = (at: string, stamp: string, ik: string) => (x: Row, y: Row): number => {
  const a = parseTs(x[at]), b = parseTs(y[at]);
  if (a !== b) return a < b ? -1 : 1;
  const ra = parseTs(x[stamp] ?? x[at]), rb = parseTs(y[stamp] ?? y[at]);
  return ra < rb ? -1 : ra > rb ? 1 : cmp(x[ik], y[ik]);
};

export function adoption(ctx: Ctx, iid: string): Row {
  const rows = ctx.acc.adoption_observations.filter((o) => o["initiative_id"] === iid);
  const obs = rows.filter((o) => ctx.observationVisible(o["observed_at"], o["recorded_at"])).sort(byObservation("observed_at", "recorded_at", "observation_id"));
  const late = rows.filter((o) => parseTs(o["observed_at"]) > ctx.asOf).map((o) => o["observation_id"] as string).sort(cmp);
  const lateRecorded = rows.filter((o) => parseTs(o["observed_at"]) <= ctx.asOf && o["recorded_at"] != null && parseTs(o["recorded_at"]) > ctx.asOf).map((o) => o["observation_id"] as string).sort(cmp);
  const series = obs.map((o) => ({ observation_id: o["observation_id"], observed_at: o["observed_at"], eligible_count: o["eligible_count"], adopted_count: o["adopted_count"],
    adoption_rate: o["eligible_count"] ? p6(fr(o["adopted_count"], o["eligible_count"])) : null }));
  const last = obs.length ? obs[obs.length - 1]! : null;
  return { eligibility_rule_version: ctx.ini.get(iid)!["eligibility_rule_version"], adoption_rate: series.length ? series[series.length - 1]!.adoption_rate : null,
    eligible_count: last ? last["eligible_count"] : null, adopted_count: last ? last["adopted_count"] : null, latest_observation_id: last ? last["observation_id"] : null,
    series, excluded_after_as_of: late, late_recorded: lateRecorded };
}

export function training(ctx: Ctx, iid: string, adoptionRate: string | null): Row {
  const rows = ctx.acc.training_completions.filter((t) => t["initiative_id"] === iid);
  const tr = rows.filter((t) => ctx.observationVisible(t["recorded_at"], t["entered_at"])).sort(byObservation("recorded_at", "entered_at", "training_id"));
  const lateRecorded = rows.filter((t) => parseTs(t["recorded_at"]) <= ctx.asOf && t["entered_at"] != null && parseTs(t["entered_at"]) > ctx.asOf).map((t) => t["training_id"] as string).sort(cmp);
  const tl = tr.length ? tr[tr.length - 1]! : null;
  const rate = tl && tl["eligible_trainees"] ? p6(fr(tl["completed"], tl["eligible_trainees"])) : null;
  return { training_completion: rate, eligible_trainees: tl ? tl["eligible_trainees"] : null, completed: tl ? tl["completed"] : null, training_id: tl ? tl["training_id"] : null,
    substituted_for_adoption: false, differs_from_adoption: rate !== null && adoptionRate !== null ? rate !== adoptionRate : null, late_recorded: lateRecorded };
}

export function risk(ctx: Ctx, iid: string): Row {
  const rs = ctx.acc.risk_items.filter((x) => x["initiative_id"] === iid).sort((a, b) => cmp(a["risk_id"], b["risk_id"]));
  const exposure = rs.length ? sumFr(rs.map((x) => mul(dec(x["probability"]), dec(x["impact"])))) : null;
  return { risk_exposure: mn(exposure), risk_exposure_exact: ex(exposure), label: "scenario estimate",
    items: rs.map((x) => ({ risk_id: x["risk_id"], probability: p6(dec(x["probability"])), impact: canon(x["impact"]), expected_loss: money(mul(dec(x["probability"]), dec(x["impact"]))) })) };
}

/** Every version in order, the original kept unchanged, latest minus original, and the observed cash values with their dates (D-P9-17).
 * `original_preserved` is read from the stored rows (version 1 is there and has its periods); the difference of the totals is exact (R9-07) and is
 * published only when the latest version covers every period of the original (R9-10): otherwise it compares different things and is null. */
export function forecast(ctx: Ctx, iid: string): Row | null {
  const fvs = ctx.acc.forecast_versions.filter((f) => f["initiative_id"] === iid && parseTs(f["created_at"]) <= ctx.asOf);
  if (!fvs.length) return null;
  const vers: Row[] = [];
  const totals = new Map<number, Fr>(), periods = new Map<number, Set<number>>();
  for (const v of [...new Set(fvs.map((f) => f["version_number"] as number))].sort(cmpNum)) {
    const rows = fvs.filter((f) => f["version_number"] === v).sort((a, b) => cmpNum(a["period_index"], b["period_index"]));
    totals.set(v, sumFr(rows.map((f) => dec(f["amount"]))));
    periods.set(v, new Set(rows.map((f) => f["period_index"] as number)));
    vers.push({ version_number: v, created_at: rows[0]!["created_at"], reason: rows[0]!["reason"], total: money(totals.get(v)!),
      by_period: rows.map((f) => ({ period_index: f["period_index"], amount: canon(f["amount"]) })) });
  }
  const observed: Row[] = [];
  for (const b of ctx.acc.benefit_items.filter((x) => x["initiative_id"] === iid && x["benefit_type"] === "cash").sort((x, y) => cmp(x["benefit_id"], y["benefit_id"]))) {
    for (const o of ctx.acc.benefit_observations.filter((q) => q["benefit_id"] === b["benefit_id"] && ctx.observationVisible(q["observed_at"], q["recorded_at"])).sort((x, y) => cmp(x["benefit_observation_id"], y["benefit_observation_id"]))) {
      observed.push({ benefit_id: b["benefit_id"], period_index: b["period_index"], measured_value: canon(o["measured_value"]), observed_at: o["observed_at"],
        period_matured: matured(ctx.cfg, b["period_index"], ctx.asOf) });
    }
  }
  const first: number = vers[0]!["version_number"], last: number = vers[vers.length - 1]!["version_number"];
  const covers = [...periods.keys()].every((v) => [...periods.get(first)!].every((p) => periods.get(v)!.has(p)));
  return { versions: vers, original_version: first, original_preserved: first === 1 && periods.get(first)!.size > 0, latest_version: last,
    revisions_cover_original_periods: covers, latest_minus_original: covers ? money(sub(totals.get(last)!, totals.get(first)!)) : null, observed };
}

/** Weighted mean of the latest assessment per dimension at or before as_of (ties by id); null when nothing was assessed (D-P9-10). */
export function readiness(ctx: Ctx): Row {
  const groups: Row = {};
  for (const g of [...ctx.acc.stakeholder_groups].sort((a, b) => cmp(a["group_id"], b["group_id"]))) {
    const latest = new Map<string, Row>();
    for (const a of ctx.acc.readiness_assessments.filter((x) => x["group_id"] === g["group_id"] && ctx.tsVisible(x["assessed_at"])).sort(byTime("assessed_at", "assessment_id"))) latest.set(a["dimension"], a);
    const dims = DIMENSIONS.filter((d) => latest.has(d)).map((d) => latest.get(d)!);
    const sw = sumFr(dims.map((a) => dec(a["weight"])));
    const score: Fr | null = dims.length ? div(sumFr(dims.map((a) => mul(dec(a["weight"]), fr(a["score"])))), sw) : null;
    groups[g["group_id"]] = { affected_count: g["affected_count"], impact_level: g["impact_level"], readiness_score: m4(score), readiness_exact: ex(score),
      label: "assessment, not a probability", dimensions_assessed: dims.length,
      dimensions: dims.map((a) => ({ dimension: a["dimension"], score: a["score"], weight: canon(a["weight"]), assessment_id: a["assessment_id"] })) };
  }
  return groups;
}
