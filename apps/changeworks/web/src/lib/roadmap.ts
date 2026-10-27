// The roadmap as the domain computes it, optionally with the browser-memory edits applied (shifted requested starts, added dependencies and allocations).
import type { Dataset } from "../data/dataset";
import { Ctx } from "../domain/context";
import { ENTITIES, type Entity, type Row } from "../domain/contract";
import { Validator, type Population } from "../domain/ingest";
import { cmp, cmpNum } from "../domain/num";
import { feasibleStarts, resourceViews } from "../domain/roadmap";
import type { RoadmapEdits } from "../state/sim";
import { replayInjections } from "./claims";

export interface RoadItem { iid: string; title: string; requested: number; duration: number; feasible: number; delay: number; binding: string | null; finish: number; prereqs: Row[]; dependents: Row[] }
export interface RoadModel { items: RoadItem[]; deps: Row[]; resources: Row; periods: number; refused: { resource_id: string; period: number; requested: string; source: string }[]; allocations: Row[] }

function withRows(pop: Population, extra: Partial<Record<Entity, Row[]>>): Population {
  return { config: pop.config, approvals: [], acc: Object.fromEntries(ENTITIES.map((e) => [e, [...pop.acc[e], ...(extra[e] ?? [])]])) as Population["acc"] };
}
/** A validator over the world plus the edits accepted so far, to test one more row. */
export function validatorWith(ds: Dataset, edits: RoadmapEdits): Validator {
  return new Validator(withRows(ds.result.population, { dependencies: edits.deps, resource_allocations: edits.allocations }));
}
export function buildRoadmap(ds: Dataset, edits: RoadmapEdits): RoadModel {
  const acc = ds.result.population.acc;
  const ini = new Map<string, Row>(acc.initiatives.map((i) => [i["initiative_id"], { ...i, requested_start_period: Math.max(0, i["requested_start_period"] + (edits.shifts[i["initiative_id"]] ?? 0)) }]));
  const deps = [...acc.dependencies, ...edits.deps].sort((a, b) => cmp(a["dependency_id"], b["dependency_id"]));
  const feas = feasibleStarts(ini, deps);
  const items: RoadItem[] = [...ini.values()].map((i) => {
    const [fs, bind] = feas.get(i["initiative_id"])!;
    return { iid: i["initiative_id"], title: i["title"], requested: i["requested_start_period"], duration: i["duration_periods"], feasible: fs, delay: fs - i["requested_start_period"], binding: bind, finish: fs + i["duration_periods"],
      prereqs: deps.filter((d) => d["initiative_id"] === i["initiative_id"]), dependents: deps.filter((d) => d["prerequisite_id"] === i["initiative_id"]) };
  }).sort((a, b) => cmpNum(a.feasible, b.feasible) || cmp(a.iid, b.iid));
  const pop = withRows(ds.result.population, { resource_allocations: edits.allocations });
  const resources = resourceViews(new Ctx(pop, ds.asOf));
  const refused = ds.injections ? replayInjections(ds).steps.filter((s) => s.entity === "resource_allocations" && s.got === "rejected").map((s) => ({ resource_id: String(s.details["resource_id"]), period: Number((s.details["periods"] as number[])[0]), requested: String(s.details["requested"]), source: s.event })) : [];
  const periods = Math.max(...items.map((i) => Math.max(i.finish, i.requested + i.duration)), ...Object.values(resources).flatMap((r) => (r as Row)["by_period"].map((b: Row) => b["period_index"] + 1)), 1) + 1;
  return { items, deps, resources, periods, refused, allocations: [...acc.resource_allocations, ...edits.allocations] };
}
