// Cash flow of an initiative inside a scenario (D-01, D-P9-02..04, D-P9-07, D-P9-16): one-time and expanded recurring costs, the four benefit
// classes, ramps, NPV as an exact rational, simple and discounted payback, and the money-class benefit claims used by the double-count rule.
import type { Ctx } from "./context";
import { CAPACITY_RATE_NAME, MONEY_TYPES, RAMP_NAME, type Row } from "./contract";
import { add, cmp, cmpNum, dec, discountFactor, div, ex, fr, ge, m4, maxFr, money, mn, mul, neg, p6, sub, sumFr, ZERO, type Fr } from "./num";
import { isoDate, periodDate } from "./time";

/** One row per period of the half-open range; a one-time cost is a single row (D-01). Rows at or past `horizon` are dropped. */
export function expandCosts(c: Row, horizon?: number): [Row, number, Fr][] {
  const ps: number[] = c["cost_type"] === "one_time" ? [c["period_index"]] : Array.from({ length: Math.max(0, c["end_period"] - c["start_period"]) }, (_, k) => c["start_period"] + k);
  return ps.filter((p) => horizon === undefined || p < horizon).map((p) => [c, p, dec(c["amount"])]);
}

/** First t with cumulative >= 0 (exactly 0 counts) and the interpolation (t-1) + (-cum[t-1]) / (cum[t] - cum[t-1]); 0 at t = 0; null if never. */
export function payback(cum: readonly Fr[]): [number | null, Fr | null] {
  for (let t = 0; t < cum.length; t++) {
    const v = cum[t]!;
    if (ge(v, ZERO)) {
      if (t === 0) return [t, ZERO];
      return [t, add(fr(t - 1), div(neg(cum[t - 1]!), sub(v, cum[t - 1]!)))];
    }
  }
  return [null, null];
}
export const paybackOut = (p: [number | null, Fr | null]): Row => ({ period: p[0], interpolated: m4(p[1]) });

/** Only the sensitivity lab uses this: a replacement ramp and a multiplier on every planned cost. Absent in every published computation. */
export interface Tweaks { ramp?: readonly Fr[] | null; costScale?: Fr }

/** What a scenario fixes for one initiative: the ramp and the capacity conversion it pins (or the latest versions). */
export class Model {
  readonly ramp_a: Row | null;
  readonly ramp: Fr[] | null;
  readonly conv_a: Row | null;
  readonly conv_ok: boolean;
  readonly rate_cap: Fr | null;
  constructor(ctx: Ctx, sc: Row, iid: string, readonly tweaks: Tweaks = {}) {
    this.ramp_a = ctx.pick(iid, RAMP_NAME, sc);
    this.ramp = tweaks.ramp !== undefined ? (tweaks.ramp ? [...tweaks.ramp] : null) : this.ramp_a && this.ramp_a["values"] && this.ramp_a["values"].length ? (this.ramp_a["values"] as string[]).map(dec) : null;
    this.conv_a = ctx.pick(iid, CAPACITY_RATE_NAME, sc);
    this.conv_ok = this.conv_a !== null && !!this.conv_a["staffing_change_evidence_ref"] && this.conv_a["value"] !== null;
    this.rate_cap = this.conv_ok ? dec(this.conv_a!["value"]) : null;
  }
  /** D-P9-02: `values[min(period - starts_period, last)]` from the row's own `starts_period`; the last value is held. */
  ramped(b: Row): Fr {
    const a = dec(b["amount"]);
    if (!this.ramp || !this.ramp.length) return a;
    const k = Math.min(Math.max(b["period_index"] - b["starts_period"], 0), this.ramp.length - 1);
    return mul(a, this.ramp[k]!);
  }
  /** The ramp fraction a benefit row uses (null when there is no ramp), for the assumption trail beside a cash-flow row. */
  rampFraction(b: Row): Fr | null {
    if (!this.ramp || !this.ramp.length) return null;
    return this.ramp[Math.min(Math.max(b["period_index"] - b["starts_period"], 0), this.ramp.length - 1)]!;
  }
}

export type Claim = readonly [string | null, number, string, string, Fr];

/** The exact figures behind a block's 2-place strings (not part of the published shape; the pages total from these, never from rounded rows). */
export interface Exact {
  cost: Fr[];
  byClass: { cash: Fr; revenue: Fr; avoided_cost_realised: Fr; capacity_converted: Fr }[];
  cf: Fr[];
  cum: Fr[];
  cumDisc: Fr[];
  df: Fr[];
  npv: Fr | null;
}

export interface CashFlowResult { block: Row; claims: Claim[]; npv: Fr | null; cum: Fr[]; exact: Exact }

/** The dated model of one initiative: the output block, the benefit claims, the exact NPV, and the cumulative flows (for the paybacks). */
export function initiativeCashFlow(ctx: Ctx, sc: Row, iid: string, r: Fr, model: Model): CashFlowResult {
  const H: number = sc["horizon_periods"];
  const scale = model.tweaks.costScale;
  const costRows = new Map<number, Fr>();
  const plannedRows: Row[] = [];
  for (const c of ctx.acc.cost_items) {
    if (c["initiative_id"] === iid && c["cost_basis"] === "planned") {
      for (const [, p, a0] of expandCosts(c, H)) {
        const a = scale ? mul(a0, scale) : a0;
        plannedRows.push({ cost_id: c["cost_id"], cost_key: c["cost_key"], period_index: p, amount: money(a) });
        costRows.set(p, add(costRows.get(p) ?? ZERO, a));
      }
    }
  }
  plannedRows.sort((x, y) => cmpNum(x["period_index"], y["period_index"]) || cmp(x["cost_id"], y["cost_id"]));
  const byClass = Array.from({ length: H }, () => ({ cash: ZERO, revenue: ZERO, avoided_cost_realised: ZERO, capacity_converted: ZERO }));
  const unrByClass: Fr[] = Array.from({ length: H }, () => ZERO);
  const beside: Row[] = [], capExcl: Row[] = [], capConv: Row[] = [], beyond: string[] = [];
  const claims: Claim[] = [];
  let plannedMoney = ZERO, plannedMoneyUnramped = ZERO;
  let hasRows = costRows.size > 0;
  const items = ctx.acc.benefit_items.filter((b) => b["initiative_id"] === iid).sort((a, b) => cmp(a["benefit_id"], b["benefit_id"]));
  for (const b of items) {
    const p: number = b["period_index"];
    if (p >= H) { beyond.push(b["benefit_id"]); continue; }
    const a = model.ramped(b), au = dec(b["amount"]), t: string = b["benefit_type"];
    if (t === "cash" || t === "revenue") {
      byClass[p]![t] = add(byClass[p]![t], a);
      unrByClass[p] = add(unrByClass[p]!, au);
      hasRows = true;
    } else if (t === "avoided_cost") {
      if (b["cash_realisation"] && b["evidence_ref"]) { // D-P9-03: a budget line actually removed
        byClass[p]!.avoided_cost_realised = add(byClass[p]!.avoided_cost_realised, a);
        unrByClass[p] = add(unrByClass[p]!, au);
        hasRows = true;
      } else {
        beside.push({ benefit_id: b["benefit_id"], period_index: p, amount: money(a), reason: b["cash_realisation"] ? "NO_EVIDENCE_REF" : "NOT_CASH_REALISED" });
      }
    } else if (t === "capacity") {
      if (model.conv_ok) { // D-P9-04: a derived cash item citing the assumption and its evidence
        const rate = model.rate_cap!;
        byClass[p]!.capacity_converted = add(byClass[p]!.capacity_converted, mul(a, rate));
        unrByClass[p] = add(unrByClass[p]!, mul(au, rate));
        hasRows = true;
        capConv.push({ source_benefit_id: b["benefit_id"], period_index: p, hours: money(a), hourly_rate: money(rate), amount: money(mul(a, rate)),
          conversion_assumption_id: model.conv_a!["assumption_id"], staffing_change_evidence_ref: model.conv_a!["staffing_change_evidence_ref"] });
      } else {
        capExcl.push({ benefit_id: b["benefit_id"], period_index: p, hours: money(a), reason: "NO_CONVERSION_ASSUMPTION" });
      }
    }
    if ((MONEY_TYPES as readonly string[]).includes(t)) { // dollars and hours are never added
      plannedMoney = add(plannedMoney, a);
      plannedMoneyUnramped = add(plannedMoneyUnramped, au);
      claims.push([b["benefit_source_key"], p, iid, b["benefit_id"], a]);
    } else if (t === "capacity" && model.conv_ok) {
      plannedMoney = add(plannedMoney, mul(a, model.rate_cap!));
      plannedMoneyUnramped = add(plannedMoneyUnramped, mul(au, model.rate_cap!));
      claims.push([b["benefit_source_key"], p, iid, b["benefit_id"], mul(a, model.rate_cap!)]);
    }
  }
  const rows: Row[] = [];
  let cum = ZERO, cumd = ZERO;
  const cfs: Fr[] = [], cumds: Fr[] = [], dfs: Fr[] = [], cumList: Fr[] = [];
  for (let p = 0; p < H; p++) {
    const bc = byClass[p]!;
    const benTotal = sumFr(Object.values(bc));
    const cost = costRows.get(p) ?? ZERO;
    const cf = sub(benTotal, cost);
    const df = discountFactor(r, p);
    const d = mul(cf, df);
    cum = add(cum, cf);
    cumd = add(cumd, d);
    cfs.push(cf); cumds.push(cumd); dfs.push(df); cumList.push(cum);
    rows.push({ period_index: p, period_start: isoDate(periodDate(ctx.cfg, p)), costs: money(cost),
      benefits_by_class: { cash: money(bc.cash), revenue: money(bc.revenue), avoided_cost_realised: money(bc.avoided_cost_realised), capacity_converted: money(bc.capacity_converted) },
      cash_benefits: money(benTotal), net_cash_flow: money(cf), cumulative: money(cum), discount_factor: p6(df), discount_factor_exact: ex(df),
      discounted_cash_flow: money(d), discounted_exact: ex(d), cumulative_discounted: money(cumd) });
  }
  const npv = hasRows ? sumFr(cfs.map((c, p) => mul(c, dfs[p]!))) : null;
  const sp = hasRows ? payback(cumList) : ([null, null] as [null, null]); // D-P9-07: null for both paybacks when there are no flows
  const dp = hasRows ? payback(cumds) : ([null, null] as [null, null]);
  const unramped = model.ramp ? Array.from({ length: H }, (_, p) => money(sub(unrByClass[p]!, costRows.get(p) ?? ZERO))) : null;
  const capHours = capExcl.length ? money(sumFr(capExcl.map((x) => dec(x["hours"])))) : null;
  const block: Row = {
    cash_flow: rows, expanded_planned_costs: plannedRows,
    excluded_from_cash_flow: {
      capacity_not_converted: capExcl, capacity_hours_not_converted: capHours,
      avoided_cost_beside: beside, avoided_cost_beside_total: beside.length ? money(sumFr(beside.map((x) => dec(x["amount"])))) : null,
      beyond_horizon: beyond,
    },
    converted_capacity: capConv,
    ramp: model.ramp_a && model.ramp ? { assumption_id: model.ramp_a["assumption_id"], values: model.ramp.map((v) => p6(v)) } : null,
    unramped_net_cash_flow: unramped,
    planned_money_benefits: { ramped: money(plannedMoney), unramped: money(plannedMoneyUnramped) },
    npv: { value: mn(npv), exact: ex(npv), unit: "USD", label: "estimate" },
    payback: { simple: paybackOut(sp), discounted: paybackOut(dp) },
  };
  const exact: Exact = { cost: Array.from({ length: H }, (_, p) => costRows.get(p) ?? ZERO), byClass, cf: cfs, cum: cumList, cumDisc: cumds, df: dfs, npv };
  return { block, claims, npv, cum: cumList, exact };
}

/** D-01, D-P9-09: claims sharing a `benefit_source_key` in one period across two or more initiatives count once, at the largest claim. */
export function doubleCount(claims: readonly Claim[]): Row {
  const planned = sumFr(claims.map((c) => c[4]));
  const groups = new Map<string, { key: string; p: number; cl: { iid: string; bid: string; a: Fr }[] }>();
  for (const [k, p, iid, bid, a] of claims) {
    if (k === null) continue;
    const gk = `${k}\u0000${p}`;
    (groups.get(gk) ?? groups.set(gk, { key: k, p, cl: [] }).get(gk)!).cl.push({ iid, bid, a });
  }
  const overlaps: Row[] = [];
  let removed = ZERO;
  const ordered = [...groups.values()].sort((x, y) => cmp(x.key, y.key) || cmpNum(x.p, y.p));
  for (const g of ordered) {
    if (new Set(g.cl.map((c) => c.iid)).size >= 2) {
      const tot = sumFr(g.cl.map((c) => c.a)), mx = maxFr(g.cl.map((c) => c.a));
      removed = add(removed, sub(tot, mx));
      overlaps.push({ benefit_source_key: g.key, period_index: g.p,
        claims: [...g.cl].sort((x, y) => cmp(x.iid, y.iid) || cmp(x.bid, y.bid)).map((c) => ({ initiative_id: c.iid, benefit_id: c.bid, amount: money(c.a) })),
        counted_once: money(mx), overlap: money(sub(tot, mx)) });
    }
  }
  return { planned_benefits: money(planned), attributable_benefits: money(sub(planned, removed)), residual: money(removed), overlaps, explanation_required: removed.n !== 0n };
}
