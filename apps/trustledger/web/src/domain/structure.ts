// Ownership coverage, versioned definitions and definition coverage, lineage coverage (D-02, D-06, D-08).
import { isMissing } from "./measure";
import { cmp, type MetricVersion, type Owner, type Population, type Row } from "./models";
import { p6, ratio } from "./num";
import { isoZ, type Instant } from "./time";

/** An owner is accountable at asOf when active; one deactivated at or before asOf leaves its datasets uncovered. */
export function ownerCovers(owner: Owner | undefined, asOf: Instant): boolean {
  if (!owner) return false;
  if (owner.deactivated_at !== null) return asOf < owner.deactivated_at;
  return owner.active;
}

export function ownershipBlock(pop: Population, asOf: Instant): Row {
  const owners = new Map(pop.owners.map((o) => [o.owner_id, o]));
  const cov = pop.datasets.filter((d) => ownerCovers(d.owner_id === null ? undefined : owners.get(d.owner_id), asOf)).map((d) => d.dataset_id);
  const cs = new Set(cov);
  return { datasets: pop.datasets.length, covered: cov.length, value: p6(ratio(cov.length, pop.datasets.length)),
    uncovered: pop.datasets.filter((d) => !cs.has(d.dataset_id)).map((d) => d.dataset_id).sort(cmp) };
}

/** The version of a metric in force at t: published or superseded, valid_from not after t, the latest valid_from. A published
 * definition is never rewritten: a change adds a version row and the older one stays readable. */
export function effectiveVersion(pop: Population, metricId: string, t: Instant): MetricVersion | null {
  const c = pop.metric_versions.filter((m) => m.metric_id === metricId && (m.status === "published" || m.status === "superseded") && m.valid_from <= t);
  if (!c.length) return null;
  return c.reduce((a, b) => (b.valid_from > a.valid_from || (b.valid_from === a.valid_from && b.version_number > a.version_number) ? b : a));
}

/** The checklist items a metric version fails (definition, grain, source_fields, owner, refresh). */
export function checklistGaps(pop: Population, m: MetricVersion, items: string[], owners: Set<string>): string[] {
  const ok = (it: string): boolean => {
    if (it === "source_fields") return !!m.source_fields && m.source_fields.length > 0 && m.source_fields.every((x) => !isMissing(x, pop.trim));
    if (it === "owner") return m.owner_id !== null && owners.has(m.owner_id);
    return !isMissing((m as unknown as Row)[it], pop.trim);
  };
  return items.filter((it) => !ok(it));
}

export function definitionsBlocks(pop: Population, asOf: Instant): { coverage: Row; definitions: Row } {
  const cl = pop.checklist_versions.find((c) => c["checklist_version"] === pop.checklist_version);
  const items: string[] = cl ? [...(cl["items"] as string[])] : [];
  const owners = new Set(pop.owners.map((o) => o.owner_id));
  const byMetric = new Map<string, MetricVersion[]>();
  for (const m of pop.metric_versions) { if (!byMetric.has(m.metric_id)) byMetric.set(m.metric_id, []); byMetric.get(m.metric_id)!.push(m); }
  const ids = [...byMetric.keys()].sort(cmp);
  let published = 0, complete = 0;
  const incomplete: Row = {};
  for (const mid of ids) {
    const e = effectiveVersion(pop, mid, asOf);
    if (!e || e.status !== "published") continue;
    published++;
    const gaps = checklistGaps(pop, e, items, owners);
    if (gaps.length) incomplete[mid] = gaps; else complete++;
  }
  const coverage = { checklist_version: pop.checklist_version, published_metrics: published, complete_metrics: complete, value: p6(ratio(complete, published)), incomplete };
  const probe = pop.probe_definition_at;
  const chg = new Map(pop.definition_changes.map((c) => [c.metric_version_id, c]));
  const idOf = (m: MetricVersion | null): string | null => (m ? m.metric_version_id : null);
  const definitions = {
    version_counts: Object.fromEntries(ids.map((m) => [m, byMetric.get(m)!.length])),
    change_records: pop.definition_changes.length,
    versions_without_change_record: pop.metric_versions.filter((m) => m.version_number > 1 && !chg.has(m.metric_version_id)).map((m) => m.metric_version_id).sort(cmp),
    changes_with_mismatched_valid_from: pop.metric_versions.filter((m) => chg.has(m.metric_version_id) && chg.get(m.metric_version_id)!.changed_at !== m.valid_from).map((m) => m.metric_version_id).sort(cmp),
    effective_at_as_of: Object.fromEntries(ids.map((m) => [m, idOf(effectiveVersion(pop, m, asOf))])),
    probe_at: isoZ(probe),
    effective_at_probe: Object.fromEntries(ids.map((m) => [m, probe !== null ? idOf(effectiveVersion(pop, m, probe)) : null])),
  };
  return { coverage, definitions };
}

/** Declared, observed and inferred edges are kept apart. Coverage = distinct observed pairs that match a declared edge / declared edges;
 * repeat observations add nothing; an inferred edge is never part of the observed numerator. */
export function lineageBlock(pop: Population): Row {
  const key = (a: string, b: string): string => `${a}\u0000${b}`;
  const pairs = (ev: string): Map<string, [string, string]> => {
    const m = new Map<string, [string, string]>();
    for (const e of pop.lineage_edges) if (e.evidence_type === ev) m.set(key(e.source_dataset_id, e.target_dataset_id), [e.source_dataset_id, e.target_dataset_id]);
    return m;
  };
  const dec = pairs("declared"), obs = pairs("observed"), inf = pairs("inferred");
  const fmt = (xs: Iterable<[string, string]>): Row[] => [...xs].sort((a, b) => cmp(a[0], b[0]) || cmp(a[1], b[1])).map(([a, b]) => ({ source_dataset_id: a, target_dataset_id: b }));
  const both = [...dec.keys()].filter((k) => obs.has(k)).length;
  return {
    declared_edges: dec.size, observed_rows: pop.lineage_edges.filter((e) => e.evidence_type === "observed").length, observed_distinct: obs.size,
    observed_matching_declared: both, value: p6(ratio(both, dec.size)),
    undeclared_observed: fmt([...obs].filter(([k]) => !dec.has(k)).map(([, v]) => v)), declared_not_observed: fmt([...dec].filter(([k]) => !obs.has(k)).map(([, v]) => v)),
    inferred_edges: fmt(inf.values()),
  };
}
