// The dependency graph (sources -> staging -> intermediate -> marts -> publication), read from model_definitions: `depends_on` names the upstream
// models by model_name, a staging definition names its source in `source_id = '...'`, and a publication is fed by the mart of the same name.
import type { Row } from "./contract";
import { cmpCodePoints } from "./hashing";

export type NodeKind = "source" | "staging" | "intermediate" | "marts" | "publication";
export const LAYERS: NodeKind[] = ["source", "staging", "intermediate", "marts", "publication"];
export interface GNode { id: string; kind: NodeKind; label: string; column: number; row: number }
export interface GEdge { from: string; to: string }
export interface Graph { nodes: GNode[]; edges: GEdge[]; upstream(id: string): string[]; downstream(id: string): string[]; closure(id: string): Set<string> }

export function layerOf(m: Row): NodeKind {
  const l = m["layer"];
  if (l === "staging" || l === "intermediate" || l === "marts") return l;
  const n = String(m["model_name"] ?? "");
  return n.startsWith("stg_") ? "staging" : n.startsWith("int_") ? "intermediate" : "marts";
}
export function buildGraph(models: Row[], sourceIds: string[], publicationNames: string[]): Graph {
  const nodes: GNode[] = [], edges: GEdge[] = [];
  const byName = new Map<string, Row>(models.map((m) => [m["model_name"], m]));
  const rowIn = new Map<NodeKind, number>();
  const add = (id: string, kind: NodeKind, label: string): void => { const r = rowIn.get(kind) ?? 0; rowIn.set(kind, r + 1); nodes.push({ id, kind, label, column: LAYERS.indexOf(kind), row: r }); };
  const known = new Set<string>();
  for (const s of [...sourceIds].sort(cmpCodePoints)) { add(s, "source", s); known.add(s); }
  for (const kind of ["staging", "intermediate", "marts"] as NodeKind[]) for (const m of models.filter((x) => layerOf(x) === kind).sort((a, b) => cmpCodePoints(a["model_id"], b["model_id"]))) { add(m["model_id"], kind, m["model_name"]); known.add(m["model_id"]); }
  for (const m of models) {
    for (const dep of (m["depends_on"] as string[] | undefined) ?? []) { const up = byName.get(dep); if (up) edges.push({ from: up["model_id"], to: m["model_id"] }); }
    if (layerOf(m) === "staging") { const mm = /source_id\s*=\s*'([^']+)'/.exec(String(m["definition"] ?? "")); if (mm && known.has(mm[1]!)) edges.push({ from: mm[1]!, to: m["model_id"] }); }
  }
  for (const name of [...new Set(publicationNames)].sort(cmpCodePoints)) {
    const id = `pub:${name}`;
    add(id, "publication", name);
    const mart = byName.get(name);
    if (mart) edges.push({ from: mart["model_id"], to: id });
  }
  edges.sort((a, b) => cmpCodePoints(a.from, b.from) || cmpCodePoints(a.to, b.to));
  const up = new Map<string, string[]>(), down = new Map<string, string[]>();
  for (const e of edges) { (up.get(e.to) ?? up.set(e.to, []).get(e.to)!).push(e.from); (down.get(e.from) ?? down.set(e.from, []).get(e.from)!).push(e.to); }
  const walk = (start: string, adj: Map<string, string[]>): string[] => { const seen = new Set<string>(), stack = [start]; while (stack.length) { for (const n of adj.get(stack.pop()!) ?? []) if (!seen.has(n)) { seen.add(n); stack.push(n); } } return [...seen].sort(cmpCodePoints); };
  return { nodes, edges, upstream: (id) => walk(id, up), downstream: (id) => walk(id, down), closure: (id) => new Set([id, ...walk(id, up), ...walk(id, down)]) };
}
