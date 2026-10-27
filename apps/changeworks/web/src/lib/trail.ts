// The assumption versions beside each cash-flow row: which ramp fraction, rate, conversion and target produced the row (display derivation only).
import type { Dataset } from "../data/dataset";
import { Ctx } from "../domain/context";
import { Model } from "../domain/cashflow";
import type { Row } from "../domain/contract";
import { p6 } from "../domain/num";

export interface RowTrail { period: number; items: { kind: string; text: string }[] }
export function assumptionTrail(ds: Dataset, sid: string, iid: string): { trail: RowTrail[]; rate: { text: string; assumption: Row | null }; target: Row | null; model: Model } {
  const ctx = new Ctx(ds.result.population, ds.asOf);
  const sc = ds.byId.scenarios.get(sid)!;
  const model = new Model(ctx, sc, iid);
  const H: number = sc["horizon_periods"];
  const benefits = ds.result.population.acc.benefit_items.filter((b) => b["initiative_id"] === iid);
  const trail: RowTrail[] = [];
  for (let p = 0; p < H; p++) {
    const items: RowTrail["items"] = [];
    const rows = benefits.filter((b) => b["period_index"] === p);
    if (model.ramp_a && model.ramp) {
      const fr = [...new Set(rows.map((b) => model.rampFraction(b)).filter((x) => x !== null).map((x) => p6(x!)!))];
      if (fr.length) items.push({ kind: "ramp", text: `ramp ${model.ramp_a["assumption_id"]} v${model.ramp_a["version_number"]} × ${fr.join(", ")}` });
    }
    if (model.conv_ok && rows.some((b) => b["benefit_type"] === "capacity")) items.push({ kind: "capacity", text: `capacity rate ${model.conv_a!["assumption_id"]} v${model.conv_a!["version_number"]} = ${model.conv_a!["value"]} USD/h` });
    if (rows.some((b) => b["benefit_type"] === "avoided_cost" && b["cash_realisation"] && b["evidence_ref"])) items.push({ kind: "evidence", text: "avoided cost with budget-line evidence" });
    trail.push({ period: p, items });
  }
  const [, src] = ctx.rate(sc);
  const conv = src.startsWith("conversion:") ? ctx.assumption(src.slice(11)) : null;
  const rate = { text: conv ? `${sc["discount_rate"]} ${sc["rate_basis"]} converted by ${conv["assumption_id"]} v${conv["version_number"]} = ${conv["value"]} per period` : `${sc["discount_rate"]} ${sc["rate_basis"]}, declared (basis equals the period basis)`, assumption: conv };
  return { trail, rate, target: ctx.pick(iid, "target_minutes_per_case", sc), model };
}
