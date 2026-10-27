// One account at one cutoff: its frozen risk, its rank among the scored accounts, and the signed contributions of its features to the logistic
// model's log-odds. A contribution describes how the fitted model arrives at a score; it is an association in the data, not a cause.
import type { Dataset } from "../data/dataset";
import { FEATURES } from "../domain/contract";
import { rankItems, itemOf, type Item } from "../domain/metrics";
import type { Id, Row } from "../domain/models";
import { add, div, mul, parseFraction, rnd, sub, ZERO, type Fr } from "../domain/num";

/** Scored eligible rows of a cutoff set, ranked by risk descending then account id (the order of the outreach queue). */
export function rankScored(ds: Dataset, predictionAt: string, model?: string): Item[] {
  const w = ds.evals[model ?? ds.primaryModel]!.world;
  return rankItems(w.setRows(predictionAt).filter((r) => r.eligible && w.pred(ds.runId, r.cutoff_id)).map((r) => itemOf(w.pred(ds.runId, r.cutoff_id)!["probability"], !!r.churned, r.account_id as Id, r.cutoff_id)));
}
export interface Contribution { term: string; value: string; detail: string }
/** log-odds terms of the fitted logistic regression for a feature row: intercept + sum of coefficient x standardised value (missing -> the fit median, plus the missing indicator). */
export function contributions(config: Row | undefined, features: Record<string, unknown>): { terms: Contribution[]; logit: string } | null {
  const model = (config?.["models"] as Row[] | undefined)?.find((m) => m["name"] === "logistic_regression");
  const pre = config?.["preprocessing"]?.["features"] as Row | undefined;
  if (!model?.["coefficients"] || !pre) return null;
  const co = model["coefficients"] as Record<string, string>;
  const terms: { term: string; v: Fr; detail: string }[] = [];
  let total = parseFraction(co["intercept"]!, false);
  for (const f of FEATURES) {
    const p = pre[f] as Row, raw = features[f];
    const missing = raw === null || raw === undefined;
    const x = missing ? parseFraction(p["median"], false) : parseFraction(String(raw), false);
    const z = div(sub(x, parseFraction(p["mean"], false)), parseFraction(p["std"], false));
    const v = mul(parseFraction(co[f]!, false), z);
    total = add(total, v);
    terms.push({ term: f, v, detail: missing ? `missing, the fit median ${p["median"]} is used` : `value ${String(raw)}, mean ${p["mean"]}, deviation ${p["std"]}` });
    if (co[`${f}_missing`] !== undefined) {
      const ind = missing ? parseFraction(co[`${f}_missing`]!, false) : ZERO;
      total = add(total, ind);
      terms.push({ term: `${f} missing`, v: ind, detail: missing ? "the value is missing: the missing-indicator coefficient applies" : "the value is present: the indicator is 0" });
    }
  }
  const order = (t: { term: string; v: Fr }): Fr => ({ n: t.v.n < 0n ? -t.v.n : t.v.n, d: t.v.d });
  terms.sort((a, b) => { const l = order(a).n * order(b).d, r = order(b).n * order(a).d; return l < r ? 1 : l > r ? -1 : 0; });
  return { terms: [{ term: "intercept", value: rnd(parseFraction(co["intercept"]!, false), 6), detail: "the model's starting log-odds" }, ...terms.map((t) => ({ term: t.term, value: rnd(t.v, 6), detail: t.detail }))], logit: rnd(total, 6) };
}

/** The cutoff whose scored accounts form the outreach queue: the latest the published cohort scored (snapshot) or the fixture's first scenario set (golden). */
export function queueAt(ds: Dataset): string {
  const m = ds.manifest?.["published_cohort"]?.["queue_prediction_at"] as string | undefined;
  return m ?? (ds.inputs["scope"]["sets"][0]["prediction_at"] as string);
}
