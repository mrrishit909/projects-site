// Cash flow of an initiative inside a scenario (D-01, D-P9-02..04, D-P9-07, D-P9-16): one-time and expanded recurring costs, the four benefit
// classes, ramps, NPV as an exact rational, simple and discounted payback, and the money-class benefit claims used by the double-count rule.
import type { Ctx } from "./context";
import { CAPACITY_RATE_NAME, MONEY_TYPES, RAMP_NAME, type Row } from "./contract";
import { hasText } from "./ingest";
import { add, cmp, cmpNum, dec, discountFactor, div, ex, fr, gt, lt, m4, maxFr, money, mn, mul, neg, p6, sub, sumFr, ZERO, type Fr } from "./num";
import { isoDate, periodDate } from "./time";

/** The classes a money claim can have; only the first four enter the cash flow. */
export const CLAIM_CLASSES = ["cash", "revenue", "avoided_cost_realised", "capacity_converted", "avoided_cost_beside"] as const;

/** One row per period of the half-open range; a one-time cost is a single row (D-01). Rows at or past `horizon` are dropped. */
export function expandCosts(c: Row, horizon?: number): [Row, number, Fr][] {
  const ps: number[] = c["cost_type"] === "one_time" ? [c["period_index"]] : Array.from({ length: Math.max(0, c["end_period"] - c["start_period"]) }, (_, k) => c["start_period"] + k);
  return ps.filter((p) => horizon === undefined || p < horizon).map((p) => [c, p, dec(c["amount"])]);
}

/** R9-12: the period at which the cumulative flow is back at or above 0 for good, and the interpolation (t-1) + (-cum[t-1]) / (cum[t] - cum[t-1]).
 * A series that is never negative has no investment to pay back (NO_INVESTMENT, null); the payback is the last crossing: the first period after the last
 * negative cumulative; a series that ends negative has not paid back within the horizon (NOT_RECOVERED, null). A cumulative of exactly 0 counts as back. */
export type PaybackTriple = [number | null, Fr | null, string | null];
export function payback(cum: readonly Fr[]): PaybackTriple {
  let last = -1;
  for (let t = 0; t < cum.length; t++) if (lt(cum[t]!, ZERO)) last = t;
  if (last < 0) return [null, null, "NO_INVESTMENT"];
  if (last === cum.length - 1) return [null, null, "NOT_RECOVERED"];
  const t = last + 1;
  return [t, add(fr(t - 1), div(neg(cum[t - 1]!), sub(cum[t]!, cum[t - 1]!))), null];
}
export const paybackOut = (p: PaybackTriple): Row => ({ period: p[0], interpolated: m4(p[1]), reason: p[2] });

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
    this.conv_ok = this.conv_a !== null && hasText(this.conv_a["staffing_change_evidence_ref"]) && this.conv_a["value"] !== null;
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

/** A money claim: [source key, period, initiative, benefit, amount, class, enters the cash flow]. */
export type Claim = readonly [string | null, number, string, string, Fr, string, boolean];
/** An hours claim: [source key, period, initiative, benefit, hours] of every capacity row, converted or not. */
export type HourClaim = readonly [string | null, number, string, string, Fr];

/** The exact figures behind a block's 2-place strings (not part of the published shape; the pages total from these, never from rounded rows). */
export interface Exact {
  cost: Fr[];
  byClass: { cash: Fr; revenue: Fr; avoided_cost_realised: Fr; capacity_converted: Fr }[];
  cf: Fr[];
  cum: Fr[];
  cumDisc: Fr[];
  df: Fr[];
  npv: Fr | null;
  /** avoided cost reported beside the cash flow, and capacity hours not converted: exact totals (R9-07) */
  beside: Fr;
  capHours: Fr;
}

export interface CashFlowResult { block: Row; claims: Claim[]; hourClaims: HourClaim[]; npv: Fr | null; cum: Fr[]; exact: Exact }

/** The dated model of one initiative: the output block, the benefit claims, the exact NPV, and the cumulative flows (for the paybacks). */
export function initiativeCashFlow(ctx: Ctx, sc: Row, iid: string, r: Fr, model: Model): CashFlowResult {
  const H: number = sc["horizon_periods"];
  const scale = model.tweaks.costScale;
  const costRows = new Map<number, Fr>();
  const plannedRows: Row[] = [];
  for (const c of ctx.costs(sc)) {
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
  const besideExact: Fr[] = [], capExclExact: Fr[] = [];
  const claims: Claim[] = [], hourClaims: HourClaim[] = [];
  let plannedMoney = ZERO, plannedMoneyUnramped = ZERO;
  let hasRows = costRows.size > 0;
  const items = ctx.benefits(sc).filter((b) => b["initiative_id"] === iid).sort((a, b) => cmp(a["benefit_id"], b["benefit_id"]));
  for (const b of items) {
    const p: number = b["period_index"];
    if (p >= H) { beyond.push(b["benefit_id"]); continue; }
    const a = model.ramped(b), au = dec(b["amount"]), t: string = b["benefit_type"];
    let cls: string = t;
    if (t === "cash" || t === "revenue") {
      byClass[p]![t] = add(byClass[p]![t], a);
      unrByClass[p] = add(unrByClass[p]!, au);
      hasRows = true;
    } else if (t === "avoided_cost") {
      if (b["cash_realisation"] && hasText(b["evidence_ref"])) { // D-P9-03, R9-04: a budget line actually removed, cited in words
        byClass[p]!.avoided_cost_realised = add(byClass[p]!.avoided_cost_realised, a);
        unrByClass[p] = add(unrByClass[p]!, au);
        hasRows = true;
        cls = "avoided_cost_realised";
      } else {
        beside.push({ benefit_id: b["benefit_id"], period_index: p, amount: money(a), reason: b["cash_realisation"] ? "NO_EVIDENCE_REF" : "NOT_CASH_REALISED" });
        besideExact.push(a);
        cls = "avoided_cost_beside";
      }
    } else if (t === "capacity") {
      hourClaims.push([b["benefit_source_key"], p, iid, b["benefit_id"], a]);
      if (model.conv_ok) { // D-P9-04: a derived cash item citing the assumption and its evidence
        const rate = model.rate_cap!;
        byClass[p]!.capacity_converted = add(byClass[p]!.capacity_converted, mul(a, rate));
        unrByClass[p] = add(unrByClass[p]!, mul(au, rate));
        hasRows = true;
        cls = "capacity_converted";
        capConv.push({ source_benefit_id: b["benefit_id"], period_index: p, hours: money(a), hourly_rate: money(rate), amount: money(mul(a, rate)),
          conversion_assumption_id: model.conv_a!["assumption_id"], staffing_change_evidence_ref: model.conv_a!["staffing_change_evidence_ref"] });
      } else {
        capExcl.push({ benefit_id: b["benefit_id"], period_index: p, hours: money(a), reason: "NO_CONVERSION_ASSUMPTION" });
        capExclExact.push(a);
      }
    }
    if ((MONEY_TYPES as readonly string[]).includes(t)) { // dollars and hours are never added
      plannedMoney = add(plannedMoney, a);
      plannedMoneyUnramped = add(plannedMoneyUnramped, au);
      claims.push([b["benefit_source_key"], p, iid, b["benefit_id"], a, cls, cls !== "avoided_cost_beside"]);
    } else if (t === "capacity" && model.conv_ok) {
      plannedMoney = add(plannedMoney, mul(a, model.rate_cap!));
      plannedMoneyUnramped = add(plannedMoneyUnramped, mul(au, model.rate_cap!));
      claims.push([b["benefit_source_key"], p, iid, b["benefit_id"], mul(a, model.rate_cap!), cls, true]);
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
  const noFlows: PaybackTriple = [null, null, "NO_FLOWS"];
  const sp = hasRows ? payback(cumList) : noFlows; // no flows at all: nothing to pay back
  const dp = hasRows ? payback(cumds) : noFlows;
  const unramped = model.ramp ? Array.from({ length: H }, (_, p) => money(sub(unrByClass[p]!, costRows.get(p) ?? ZERO))) : null;
  const capHours = capExcl.length ? money(sumFr(capExclExact)) : null; // R9-07: one rounding of the exact sum
  const block: Row = {
    cash_flow: rows, expanded_planned_costs: plannedRows,
    excluded_from_cash_flow: {
      capacity_not_converted: capExcl, capacity_hours_not_converted: capHours,
      avoided_cost_beside: beside, avoided_cost_beside_total: beside.length ? money(sumFr(besideExact)) : null,
      beyond_horizon: beyond,
    },
    converted_capacity: capConv,
    ramp: model.ramp_a && model.ramp ? { assumption_id: model.ramp_a["assumption_id"], values: model.ramp.map((v) => p6(v)) } : null,
    unramped_net_cash_flow: unramped,
    planned_money_benefits: { ramped: money(plannedMoney), unramped: money(plannedMoneyUnramped) },
    npv: { value: mn(npv), exact: ex(npv), unit: "USD", label: "estimate" },
    payback: { simple: paybackOut(sp), discounted: paybackOut(dp) },
  };
  const exact: Exact = { cost: Array.from({ length: H }, (_, p) => costRows.get(p) ?? ZERO), byClass, cf: cfs, cum: cumList, cumDisc: cumds, df: dfs, npv, beside: sumFr(besideExact), capHours: sumFr(capExclExact) };
  return { block, claims, hourClaims, npv, cum: cumList, exact };
}

type Group<T> = { key: string; p: number; cl: T[] };
/** The (source key, period) groups with claims of two or more initiatives, in key then period order. */
function sharedGroups<T extends readonly [string | null, number, string, ...unknown[]]>(claims: readonly T[]): Group<T>[] {
  const groups = new Map<string, Group<T>>();
  for (const c of claims) {
    if (c[0] === null) continue;
    const gk = `${c[0]}\u0000${c[1]}`;
    (groups.get(gk) ?? groups.set(gk, { key: c[0], p: c[1], cl: [] }).get(gk)!).cl.push(c);
  }
  return [...groups.values()].filter((g) => new Set(g.cl.map((c) => c[2])).size >= 2).sort((x, y) => cmp(x.key, y.key) || cmpNum(x.p, y.p));
}
/** The claim that counts: the largest; among equals the one that enters the cash flow, then the smallest (initiative, benefit). */
function retained(cl: readonly Claim[]): Claim {
  return [...cl].sort((x, y) => (gt(x[4], y[4]) ? -1 : lt(x[4], y[4]) ? 1 : 0) || (x[6] === y[6] ? 0 : x[6] ? -1 : 1) || cmp(x[2], y[2]) || cmp(x[3], y[3]))[0]!;
}

/** D-01, D-P9-09, R9-02, R9-03: claims sharing a `benefit_source_key` in one period across two or more initiatives count once, at the largest claim.
 * Money (USD) and hours are two separate rules, never added; `double_counted_amount` is the money that counts twice and `double_counted_pv` its present
 * value in the cash flow (the part of it that enters the cash flow, discounted period by period): NPV less that PV is the attributable NPV. */
export function doubleCount(claims: readonly Claim[], hourClaims: readonly HourClaim[], r: Fr): { block: Row; pvExact: Fr; byClassExact: Record<string, Fr> } {
  const planned = sumFr(claims.map((c) => c[4]));
  const overlaps: Row[] = [];
  let removed = ZERO, pv = ZERO;
  const byClass: Record<string, Fr> = Object.fromEntries(CLAIM_CLASSES.map((k) => [k, ZERO]));
  for (const g of sharedGroups(claims)) {
    const keep = retained(g.cl);
    const tot = sumFr(g.cl.map((c) => c[4])), mx = keep[4];
    removed = add(removed, sub(tot, mx));
    for (const c of g.cl) {
      if (c !== keep) {
        byClass[c[5]] = add(byClass[c[5]]!, c[4]);
        if (c[6]) pv = add(pv, mul(c[4], discountFactor(r, g.p)));
      }
    }
    overlaps.push({ benefit_source_key: g.key, period_index: g.p,
      claims: [...g.cl].sort((x, y) => cmp(x[2], y[2]) || cmp(x[3], y[3])).map((c) => ({ initiative_id: c[2], benefit_id: c[3], amount: money(c[4]), benefit_class: c[5], enters_cash_flow: c[6] })),
      counted_once: money(mx), overlap: money(sub(tot, mx)) });
  }
  const hoursPlanned = sumFr(hourClaims.map((c) => c[4]));
  let hoursRemoved = ZERO;
  const hoursOverlaps: Row[] = [];
  for (const g of sharedGroups(hourClaims)) {
    const tot = sumFr(g.cl.map((c) => c[4])), mx = maxFr(g.cl.map((c) => c[4]));
    hoursRemoved = add(hoursRemoved, sub(tot, mx));
    hoursOverlaps.push({ benefit_source_key: g.key, period_index: g.p,
      claims: [...g.cl].sort((x, y) => cmp(x[2], y[2]) || cmp(x[3], y[3])).map((c) => ({ initiative_id: c[2], benefit_id: c[3], hours: money(c[4]) })),
      counted_once: money(mx), hours_residual: money(sub(tot, mx)) });
  }
  const need = [["money", removed], ["hours", hoursRemoved]].filter(([, v]) => (v as Fr).n !== 0n).map(([k]) => k as string);
  const block: Row = { planned_benefits: money(planned), attributable_benefits: money(sub(planned, removed)), residual: money(removed),
    double_counted_amount: money(removed), double_counted_pv: money(pv), double_counted_pv_exact: ex(pv),
    double_counted_by_class: Object.fromEntries(CLAIM_CLASSES.map((k) => [k, money(byClass[k]!)])), double_counted_by_class_exact: Object.fromEntries(CLAIM_CLASSES.map((k) => [k, ex(byClass[k]!)])),
    overlaps, planned_hours: money(hoursPlanned), attributable_hours: money(sub(hoursPlanned, hoursRemoved)), hours_residual: money(hoursRemoved), hours_overlaps: hoursOverlaps,
    explanation_required: need.length > 0, explanation_required_for: need };
  return { block, pvExact: pv, byClassExact: byClass };
}

/** Initiatives that claim the same capacity (a shared key in a shared period) form one group; their released hours count once, at the largest. */
export function hoursComponents(hourClaims: readonly HourClaim[]): Set<string>[] {
  const parent = new Map<string, string>();
  const find = (x: string): string => {
    if (!parent.has(x)) parent.set(x, x);
    while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x)!)!); x = parent.get(x)!; }
    return x;
  };
  for (const g of sharedGroups(hourClaims)) {
    const ids = [...new Set(g.cl.map((c) => c[2]))].sort(cmp);
    for (const other of ids.slice(1)) parent.set(find(other), find(ids[0]!));
  }
  const comps = new Map<string, Set<string>>();
  for (const x of [...parent.keys()]) { const root = find(x); (comps.get(root) ?? comps.set(root, new Set()).get(root)!).add(x); }
  return [...comps.values()];
}
