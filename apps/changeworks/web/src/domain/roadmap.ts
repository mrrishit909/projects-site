// Roadmap (D-03, D-P9-08, D-P9-15): feasible starts propagated through the dependency chain, dependency delay (never negative), the binding
// dependency, and the shared-capacity view of each resource. The roadmap is reported beside the cash flows and does not re-time them.
import type { Ctx } from "./context";
import { DomainError, type Row } from "./contract";
import { add, cmp, cmpNum, dec, gt, money, ZERO, sub, type Fr } from "./num";

/** `{initiative_id: [feasible start, binding dependency id]}`. FS: prerequisite feasible start + its duration + lag; SS: prerequisite feasible
 * start + lag; the first dependency (by id) reaching the maximum above the requested start is the binding one. A cycle is DEPENDENCY_CYCLE. */
export function feasibleStarts(ini: ReadonlyMap<string, Row>, deps: readonly Row[]): Map<string, [number, string | null]> {
  const out = new Map<string, [number, string | null]>();
  const state = new Map<string, number>(); // 1 = on the stack, 2 = done
  const feasible = (iid: string, path: readonly string[]): [number, string | null] => {
    if (state.get(iid) === 2) return out.get(iid)!;
    if (state.get(iid) === 1) throw new DomainError("DEPENDENCY_CYCLE", "the initiatives depend on each other in a cycle", { cycle: [...path.slice(path.indexOf(iid)), iid] });
    state.set(iid, 1);
    let best: number = ini.get(iid)!["requested_start_period"], bind: string | null = null;
    for (const d of deps.filter((x) => x["initiative_id"] === iid).sort((a, b) => cmp(a["dependency_id"], b["dependency_id"]))) {
      const pid: string = d["prerequisite_id"];
      const s = feasible(pid, [...path, iid])[0] + (d["dependency_type"] === "finish_to_start" ? ini.get(pid)!["duration_periods"] : 0) + d["lag_periods"];
      if (s > best) { best = s; bind = d["dependency_id"]; }
    }
    state.set(iid, 2);
    out.set(iid, [best, bind]);
    return out.get(iid)!;
  };
  for (const iid of [...ini.keys()].sort(cmp)) feasible(iid, []);
  return out;
}

export function initiativeRoadmap(ctx: Ctx, feas: ReadonlyMap<string, [number, string | null]>, iid: string): Row {
  const i = ctx.ini.get(iid)!;
  const [fs, bind] = feas.get(iid)!;
  // D-P9-15: allocations that would cross a capacity are refused when they are recorded, so the resource-constrained start equals the
  // dependency-feasible one and the resource delay is 0 (a levelling shift is not implemented).
  // R9-06: benefits are booked from `deployment_period`; when that is earlier than the dependency-feasible start the plan books benefits before the work can begin.
  // The cash flow is not re-timed (D-P9-08): the inconsistency is reported, not repaired.
  const warnings: Row[] = i["deployment_period"] < fs ? [{ code: "DEPLOYMENT_BEFORE_FEASIBLE_START", deployment_period: i["deployment_period"], dependency_feasible_start: fs, periods_early: fs - i["deployment_period"] }] : [];
  return { requested_start: i["requested_start_period"], duration_periods: i["duration_periods"], dependency_feasible_start: fs, dependency_delay: fs - i["requested_start_period"],
    binding_dependency_id: bind, finish: fs + i["duration_periods"], resource_constrained_start: fs, resource_delay: 0, deployment_period: i["deployment_period"], warnings };
}

export function resourceViews(ctx: Ctx): Row {
  const out: Row = {};
  for (const rs of [...ctx.acc.resources].sort((a, b) => cmp(a["resource_id"], b["resource_id"]))) {
    const cap = dec(rs["capacity_per_period"]);
    const per = new Map<number, Fr>();
    for (const a of ctx.acc.resource_allocations) if (a["resource_id"] === rs["resource_id"]) per.set(a["period_index"], add(per.get(a["period_index"]) ?? ZERO, dec(a["amount"])));
    const sorted = [...per.entries()].sort((x, y) => cmpNum(x[0], y[0]));
    out[rs["resource_id"]] = { capacity_per_period: money(cap), unit: rs["unit"],
      by_period: sorted.map(([p, v]) => ({ period_index: p, allocated: money(v), headroom: money(sub(cap, v)) })),
      overallocated_periods: sorted.filter(([, v]) => gt(v, cap)).map(([p]) => p) };
  }
  return out;
}
