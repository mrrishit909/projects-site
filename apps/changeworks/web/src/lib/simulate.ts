// The sensitivity lab's engine: the same domain code, run over a changed rate, ramp or cost scale. Exact rationals throughout; the result is a simulation.
import type { Dataset } from "../data/dataset";
import { Ctx } from "../domain/context";
import { Model, initiativeCashFlow, type Tweaks } from "../domain/cashflow";
import type { Row } from "../domain/contract";
import { Validator } from "../domain/ingest";
import { RAMP_NAME } from "../domain/contract";
import { add, dec, div, fr, ge, le, mn, monthlyFromAnnual, mul, ONE, rnd, sub, ZERO, type Fr } from "../domain/num";
import type { SensitivitySettings } from "../state/sim";

export type Outcome = { ok: true; npv: string | null; npvExact: string | null; simple: Row; discounted: Row; rate: Fr; rateNote: string; published: string | null; delta: string | null; ramp: string[] | null }
  | { ok: false; code: string; message: string };

export const RAMPS: { value: SensitivitySettings["ramp"]; label: string }[] = [
  { value: "planned", label: "As planned" }, { value: "immediate", label: "Full from the first benefit period" },
  { value: "late2", label: "Two periods late" }, { value: "slow75", label: "75 % of planned fractions" },
];
export const COST_PCTS = [-20, -10, 0, 10, 20, 30];
export const RATE_GRID = ["0", "2", "4", "6", "8", "10", "12", "15", "20"];

/** "8" or "7.5" percent as an exact fraction; null when it is not a percentage between 0 and 100 with at most 4 decimals. */
export function parsePercent(s: string): Fr | null {
  if (!/^\d{1,3}(\.\d{1,4})?$/.test(s.trim())) return null;
  const f = div(dec(s.trim()), fr(100));
  return le(f, ONE) && ge(f, ZERO) ? f : null;
}

export function rampValues(ctx: Ctx, sc: Row, iid: string, kind: SensitivitySettings["ramp"]): Fr[] | undefined {
  if (kind === "planned") return undefined;
  const a = ctx.pick(iid, RAMP_NAME, sc);
  const planned: Fr[] = a && a["values"] ? (a["values"] as string[]).map(dec) : [ONE];
  if (kind === "immediate") return [ONE];
  if (kind === "late2") return [ZERO, ZERO, ...planned];
  return planned.map((v) => div({ n: v.n * 3n, d: v.d }, fr(4)));
}

export function simulate(ds: Dataset, s: SensitivitySettings, ratePct = s.rate, costPct = s.costPct): Outcome {
  const base = ds.byId.scenarios.get(s.scenario);
  const blk = ds.metrics["scenarios"][s.scenario]?.["initiatives"][s.initiative] as Row | undefined;
  if (!base || !blk) return { ok: false, code: "UNKNOWN_SCENARIO", message: "that initiative is not in that scenario" };
  const r0 = parsePercent(ratePct);
  if (r0 === null) return { ok: false, code: "INVALID_RATE", message: "the rate must be a percentage from 0 to 100 with at most four decimals" };
  const periodBasis = String(ds.result.population.config["period_basis"]);
  let r = r0, rateNote = `${ratePct} % declared on ${periodBasis} periods`;
  if (s.basis !== periodBasis) {
    const probe = new Validator(ds.result.population).check("scenario_versions", { ...base, scenario_id: "sim-probe", discount_rate: rnd(r0, 6), rate_basis: s.basis, rate_conversion_assumption_id: null, status: "draft" });
    if (s.raw || s.basis === "monthly" || probe === null) {
      return { ok: false, code: probe?.reason_code ?? "RATE_PERIOD_MISMATCH", message: `a ${s.basis} rate on ${periodBasis} periods is refused unless an explicit conversion is recorded${s.basis === "annual" ? "; untick the box to apply the declared 6-place conversion" : ""}` };
    }
    r = monthlyFromAnnual(r0);
    rateNote = `${ratePct} % annual converted to ${rnd(r, 6)} per month, (1 + r)^(1/12) − 1 recorded to 6 places as its own simulated assumption`;
  }
  const ctx = new Ctx(ds.result.population, ds.asOf);
  const tweaks: Tweaks = { costScale: add(ONE, div(fr(costPct), fr(100))) };
  const ramp = rampValues(ctx, base, s.initiative, s.ramp);
  if (ramp !== undefined) tweaks.ramp = ramp;
  const model = new Model(ctx, base, s.initiative, tweaks);
  const res = initiativeCashFlow(ctx, base, s.initiative, r, model);
  const b = res.block;
  const pub = blk["npv"]["exact"] as string | null;
  const delta = res.npv && pub ? mn(sub(res.npv, { n: BigInt(pub.split("/")[0]!), d: BigInt(pub.split("/")[1] ?? 1) })) : null;
  return { ok: true, npv: b["npv"]["value"], npvExact: b["npv"]["exact"], simple: b["payback"]["simple"], discounted: b["payback"]["discounted"], rate: r, rateNote, published: blk["npv"]["value"], delta, ramp: model.ramp ? model.ramp.map((v) => rnd(v, 6)) : null };
}

/** A declared rate string ("0.080000") as percent text ("8"), exact. */
export function pctText(rate: string): string {
  const t = rnd(mul(dec(rate), fr(100)), 4);
  return t.replace(/0+$/, "").replace(/\.$/, "");
}
