// The generator's own claims, re-derived from this browser's computation: the seven designed relationships (DR-01..07) of the manifest, the machine
// checks of the twelve injected defects (INJ-01..12), and a replay of every ingest step of the injection events against the published world.
// The synthetic truth is never read here.
import type { Dataset } from "../data/dataset";
import { ENTITIES, ID_FIELD, type Entity, type Row } from "../domain/contract";
import { Validator, type Population } from "../domain/ingest";
import { cmp, cmpNum, dec, div, money, p6, rnd, sumFr, fr, ZERO, mul, type Fr } from "../domain/num";
import { scenariosWith } from "./derive";

export interface Claim { id: string; label: string; want: string; got: string; ok: boolean }
const canonJson = (v: unknown): string => JSON.stringify(v, (_k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => cmp(a, b))) : x));
function claim(out: Claim[], id: string, label: string, got: unknown, want: unknown): void {
  out.push({ id, label, want: canonJson(want), got: canonJson(got), ok: canonJson(got) === canonJson(want) });
}
const monthIndex = (iso: string): number => Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1;
const sorted = <T,>(xs: T[], f: (a: T, b: T) => number): T[] => [...xs].sort(f);

/** Every figure of every designed relationship in the manifest, against what this computation gives. */
export function designedClaims(ds: Dataset): Claim[] {
  const out: Claim[] = [];
  const drs = ds.manifest.designed_relationships;
  if (!drs) return out;
  const acc = ds.result.population.acc;
  const M = ds.metrics;
  const tol = Number(ds.manifest.generator?.parameters?.["forecast_miss_tolerance_percent"] ?? 10);
  for (const d of drs) {
    const R = d.realised;
    const c = (label: string, got: unknown, want: unknown): void => claim(out, d.id, label, got, want);
    if (d.id === "DR-01") {
      const iid = R["initiative_id"] as string, sid = R["scenario_id"] as string;
      const blk = M["scenarios"][sid]["initiatives"][iid] as Row;
      c("benefit classes", [...new Set(acc.benefit_items.filter((b) => b["initiative_id"] === iid).map((b) => b["benefit_type"] as string))].sort(cmp), R["benefit_classes"]);
      c("planned hours", rnd(sumFr(acc.benefit_items.filter((b) => b["initiative_id"] === iid).map((b) => dec(b["amount"]))), 2), R["planned_hours"]);
      c("capacity hours not converted", blk["excluded_from_cash_flow"]["capacity_hours_not_converted"], R["capacity_hours_not_converted"]);
      c("converted capacity items", blk["converted_capacity"].length, R["converted_capacity_items"]);
      c("cash benefits total", money(sumFr((blk["cash_flow"] as Row[]).map((r) => dec(r["cash_benefits"])))), R["cash_benefits_total"]);
      c("NPV", blk["npv"]["value"], R["npv"]);
      c("simple payback", blk["payback"]["simple"]["period"], R["simple_payback"]);
      c("capacity released per period (hours)", blk["capacity_released"]["hours"], R["capacity_released_hours_per_period"]);
    } else if (d.id === "DR-02") {
      const sid = R["scenario_id"] as string;
      const dc = M["scenarios"][sid]["double_count"] as Row;
      const ids = acc.scenario_versions.map((s) => s["scenario_id"] as string);
      const withRes = ids.filter((s) => M["scenarios"][s]["double_count"]["residual"] !== "0.00");
      c("initiatives and shared key", [(dc["overlaps"] as Row[])[0]!["claims"].map((x: Row) => x["initiative_id"]), (dc["overlaps"] as Row[])[0]!["benefit_source_key"]], [R["initiatives"], R["benefit_source_key"]]);
      c("planned benefits", dc["planned_benefits"], R["planned_benefits"]);
      c("attributable benefits", dc["attributable_benefits"], R["attributable_benefits"]);
      c("residual", dc["residual"], R["residual"]);
      c("overlap periods (count, first, last)", [dc["overlaps"].length, dc["overlaps"][0].period_index, dc["overlaps"][dc["overlaps"].length - 1].period_index], [R["overlap_periods"], R["first_overlap_period"], R["last_overlap_period"]]);
      c("scenarios with a residual", withRes, R["scenarios_with_a_residual"]);
      c("scenarios with no residual", ids.filter((s) => !withRes.includes(s)), R["scenarios_with_no_residual"]);
    } else if (d.id === "DR-03") {
      const iid = R["initiative_id"] as string;
      const sids = scenariosWith(ds, iid);
      const rows = sids.map((s) => M["scenarios"][s]["initiatives"][iid] as Row);
      const npvs = sorted(rows.map((b) => b["npv"]["exact"] as string), (a, b) => { const x = a.split("/"), y = b.split("/"); const l = BigInt(x[0]!) * BigInt(y[1] ?? 1), r = BigInt(y[0]!) * BigInt(x[1] ?? 1); return l < r ? -1 : l > r ? 1 : 0; });
      const planned = acc.cost_items.filter((x) => x["initiative_id"] === iid && x["cost_basis"] === "planned");
      const cost = sumFr(planned.map((x) => (x["cost_type"] === "one_time" ? dec(x["amount"]) : mul(dec(x["amount"]), fr(x["end_period"] - x["start_period"])))));
      const ben = rows.length ? sumFr((rows[0]!["cash_flow"] as Row[]).map((r) => dec(r["cash_benefits"]))) : ZERO;
      c("scenarios", sids, R["scenarios"]);
      c("simple payback null in", rows.filter((b) => b["payback"]["simple"]["period"] === null).length, R["scenarios_with_simple_payback_null"]);
      c("discounted payback null in", rows.filter((b) => b["payback"]["discounted"]["period"] === null).length, R["scenarios_with_discounted_payback_null"]);
      const parse = (s: string): Fr => { const [n, dd] = s.split("/"); return fr(BigInt(n!), BigInt(dd ?? 1)); };
      c("NPV lowest and highest", [rnd(parse(npvs[0]!), 2), rnd(parse(npvs[npvs.length - 1]!), 2)], [R["npv_lowest"], R["npv_highest"]]);
      c("planned cost", rnd(cost, 2), R["planned_cost"]);
      c("benefits entering the cash flow", rnd(ben, 2), R["benefits_entering_the_cash_flow"]);
      c("benefit-to-cost ratio", p6(div(ben, cost)), R["benefit_to_cost"]);
    } else if (d.id === "DR-04") {
      const iid = R["initiative_id"] as string;
      const fc = M["initiatives"][iid]["forecast"] as Row;
      const readings = new Map<number, [string, Fr][]>();
      for (const o of fc["observed"] as Row[]) if (o["period_matured"]) (readings.get(o["period_index"]) ?? readings.set(o["period_index"], []).get(o["period_index"])!).push([o["observed_at"], dec(o["measured_value"])]);
      const byTimeThenValue = (a: [string, Fr], b: [string, Fr]): number => cmp(a[0], b[0]) || (a[1].n * b[1].d < b[1].n * a[1].d ? -1 : a[1].n * b[1].d > b[1].n * a[1].d ? 1 : 0);
      const obs = new Map<number, Fr>();
      for (const [p, rs] of readings) { const srt = [...rs].sort(byTimeThenValue); obs.set(p, srt[srt.length - 1]![1]); }
      const vers = new Map<number, Map<number, Fr>>((fc["versions"] as Row[]).map((v) => [v["version_number"], new Map((v["by_period"] as Row[]).map((r) => [r["period_index"], dec(r["amount"])]))]));
      const misses: Row[] = [];
      for (const v of (fc["versions"] as Row[]).slice(1)) {
        const k: number = v["version_number"];
        const prev = vers.get(k - 1)!, before = k >= 3 ? vers.get(k - 2)! : null;
        const revised = [...prev.keys()].filter((p) => before === null || !(prev.get(p)!.n === before.get(p)?.n && prev.get(p)!.d === before.get(p)?.d));
        const seen = new Map<number, Fr>();
        for (const p of revised) {
          const got = sorted(readings.get(p) ?? [], byTimeThenValue).filter(([at]) => cmp(at, v["created_at"]) <= 0);
          if (got.length) seen.set(p, got[got.length - 1]![1]);
        }
        const short = [...seen].filter(([p, o]) => lessThan(mul(o, fr(100)), mul(prev.get(p)!, fr(100 - tol))));
        const ratio = (p: number, o: Fr): string => p6(div(o, prev.get(p)!))!;
        const asObj = (xs: [number, Fr][]): Row => Object.fromEntries(sorted(xs, (a, b) => cmpNum(a[0], b[0])).map(([p, o]) => [String(p), ratio(p, o)]));
        misses.push({ revision: k, created_at: v["created_at"], revises_version: k - 1, periods_checked: [...seen.keys()].sort(cmpNum), periods_below_the_previous_forecast: short.map(([p]) => p).sort(cmpNum),
          observed_over_forecast: asObj(short), all_checked_periods_observed_over_forecast: asObj([...seen]) });
      }
      c("versions", (fc["versions"] as Row[]).map((v) => ({ version_number: v["version_number"], created_at: v["created_at"], total: v["total"], reason: v["reason"] })), R["versions"]);
      c("original preserved, latest minus original", [fc["original_preserved"], fc["latest_minus_original"]], [R["original_preserved"], R["latest_minus_original"]]);
      c("misses (periods checked, below the previous forecast, ratios)", misses, R["misses"]);
      c("latest observed (matured periods)", Object.fromEntries([...obs].sort((a, b) => cmpNum(a[0], b[0])).map(([p, o]) => [String(p), rnd(o, 2)])), R["latest_observed"]);
    } else if (d.id === "DR-05") {
      const rid = R["resource_id"] as string;
      const res = M["resources"][rid] as Row;
      const byp = new Map<number, Row>((res["by_period"] as Row[]).map((b) => [b["period_index"], b]));
      const periods = R["periods"] as number[];
      const refused = replayInjections(ds).steps.filter((s) => s.event === "EV-09" && s.kind === "ingest").slice(0, 3);
      c("capacity", res["capacity_per_period"], R["capacity_per_period"]);
      c("allocated and headroom in the periods", [Object.fromEntries(periods.map((p) => [String(p), byp.get(p)!["allocated"]])), Object.fromEntries(periods.map((p) => [String(p), byp.get(p)!["headroom"]]))], [R["allocated"], R["headroom"]]);
      c("stored overallocated periods", res["overallocated_periods"], R["stored_overallocated_periods"]);
      c("requests refused (count, periods, amounts) when replayed", [refused.length, refused.map((s) => s.details["periods"]?.[0]), refused.map((s) => s.details["requested"])], [R["requests_refused"], R["refused_periods"], R["requested"]]);
      c("initiatives allocated in those periods", [...new Set(acc.resource_allocations.filter((a) => a["resource_id"] === rid && periods.includes(a["period_index"])).map((a) => a["initiative_id"] as string))].sort(cmp), R["initiatives_allocated_in_those_periods"]);
    } else if (d.id === "DR-06") {
      const iid = R["initiative_id"] as string, sid = R["scenario_id"] as string;
      const rb = M["scenarios"][sid]["initiatives"][iid]["benefit_realization"]["cash"] as Row;
      c("comparable rows", rb["comparable_items"].length, R["comparable_rows"]);
      c("planned, observed, realisation", [rb["planned_comparable"], rb["observed_comparable"], rb["realization"]], [R["planned_comparable"], R["observed_comparable"], R["realization"]]);
      c("baseline trend and observed above trend", [rb["baseline_trend"], rb["observed_above_trend"]], [R["baseline_trend"], R["observed_above_trend"]]);
      c("trend share of observed", p6(div(dec(rb["baseline_trend"]), dec(rb["observed_comparable"]))), R["trend_share_of_observed"]);
      c("attribution label", rb["attribution"], R["attribution"]);
    } else if (d.id === "DR-07") {
      const lags: Row[] = [];
      const asOfMonth = monthIndex(ds.manifest.as_of);
      for (const l of R["initiatives"] as Row[]) {
        const iid = l["initiative_id"] as string;
        const t90 = acc.training_completions.find((t) => t["initiative_id"] === iid && t["completed"] * 100 >= t["eligible_trainees"] * 90)?.["recorded_at"] ?? null;
        const series = M["initiatives"][iid]["adoption"]["series"] as Row[];
        const a50 = series.find((x) => x["adoption_rate"] !== null && dec(x["adoption_rate"]).n * 2n >= dec(x["adoption_rate"]).d)?.["observed_at"] ?? null;
        lags.push({ initiative_id: iid, training_90_percent_on: t90, adoption_50_percent_on: a50, lag_periods: t90 && a50 ? monthIndex(a50) - monthIndex(t90) : null,
          periods_since_training_90_percent: t90 ? asOfMonth - monthIndex(t90) : null, training_completion_now: M["initiatives"][iid]["training"]["training_completion"], adoption_rate_now: M["initiatives"][iid]["adoption"]["adoption_rate"] });
      }
      c("per initiative: dates, lag, completion and adoption now", lags, R["initiatives"]);
      c("lags sorted", lags.map((x) => x["lag_periods"]).filter((x) => x !== null).sort(cmpNum), R["lag_periods_sorted"]);
      c("never reached 50 %", lags.filter((x) => x["lag_periods"] === null).map((x) => x["initiative_id"]), R["initiatives_whose_adoption_never_reached_50_percent"]);
      c("summary training and adoption", [M["summary"]["training_completion"], M["summary"]["adoption_rate"]], [R["training_completion_summary"], R["adoption_rate_summary"]]);
    }
  }
  return out;
}
const lessThan = (a: Fr, b: Fr): boolean => a.n * b.d < b.n * a.d;

/** `a.b[2].c` on nested objects and arrays: the paths of the injection checks (rooted at {ingest, metrics}). */
export function lookup(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const part of path.replace(/\[/g, ".[").split(".")) {
    if (part.startsWith("[")) cur = (cur as unknown[])[Number(part.slice(1, -1))];
    else cur = (cur as Row)[part];
  }
  return cur;
}
export interface InjectionCheck { inj: string; test: string; name: string; path: string; got: unknown; want: unknown; ok: boolean }
export function injectionChecks(ds: Dataset): InjectionCheck[] {
  const inj = ds.injections?.["injections"] as Row[] | undefined;
  if (!inj) return [];
  const root = { ingest: ds.goldenShape()["ingest"], metrics: ds.metrics };
  return inj.flatMap((i) => (i["checks"] as Row[]).map((ch) => {
    let got: unknown;
    try { got = lookup(root, ch["path"]); } catch { got = undefined; }
    return { inj: i["id"], test: i["test"], name: i["name"], path: ch["path"], got, want: ch["equals"], ok: canonJson(got) === canonJson(ch["equals"]) } as InjectionCheck;
  }));
}

export interface ReplayStep { event: string; injection: string; entity: string; id: string; kind: string; expected: string; reasonExpected: string | null; got: string; reasonGot: string | null; ok: boolean; details: Row }
/** Every ingest step of the injection events, replayed in order against a copy of the published world by the domain's own validator. */
export function replayInjections(ds: Dataset): { steps: ReplayStep[]; commandSteps: number; readSteps: number } {
  const events = (ds.injections?.["events"] ?? []) as Row[];
  const copy: Population = { config: ds.result.population.config, approvals: [], acc: Object.fromEntries(ENTITIES.map((e) => [e, [...ds.result.population.acc[e]]])) as Population["acc"] };
  const v = new Validator(copy);
  const steps: ReplayStep[] = [];
  let commandSteps = 0, readSteps = 0;
  for (const ev of events) {
    for (const s of ev["steps"] as Row[]) {
      if (s["kind"] === "command") { commandSteps++; continue; }
      if (s["kind"] === "read") { readSteps++; continue; }
      const entity = s["entity"] as Entity;
      const rej = v.add(entity, JSON.parse(JSON.stringify(s["row"])));
      const got = rej ? "rejected" : "accepted";
      steps.push({ event: ev["event_id"], injection: ev["injection"], entity, id: String((s["row"] as Row)[ID_FIELD[entity]]), kind: "ingest", expected: s["expected"], reasonExpected: s["reason_code"] ?? null,
        got, reasonGot: rej ? rej.reason_code : null, ok: got === s["expected"] && (rej ? rej.reason_code : null) === (s["reason_code"] ?? null), details: rej ? rej.details : {} });
    }
  }
  return { steps, commandSteps, readSteps };
}
