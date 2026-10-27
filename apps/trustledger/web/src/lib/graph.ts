// A deterministic layered layout for the lineage graph: layers by longest path from the sources (back edges of a cycle ignored), then a few
// barycentre sweeps to reduce crossings. Pure and seedless: the same edges always give the same picture.
import { cmp } from "../domain/models";

export interface Placed { id: string; layer: number; row: number }
export function layout(nodes: readonly string[], edges: readonly (readonly [string, string])[]): { placed: Map<string, Placed>; layers: number; rows: number } {
  const ids = [...nodes].sort(cmp);
  const preds = new Map<string, string[]>(ids.map((n) => [n, []])), succs = new Map<string, string[]>(ids.map((n) => [n, []]));
  for (const [a, b] of edges) if (a !== b && preds.has(a) && preds.has(b)) { if (!preds.get(b)!.includes(a)) preds.get(b)!.push(a); if (!succs.get(a)!.includes(b)) succs.get(a)!.push(b); }
  const depth = new Map<string, number>();
  const stack = new Set<string>();
  const d = (v: string): number => {
    const known = depth.get(v);
    if (known !== undefined) return known;
    if (stack.has(v)) return -1;
    stack.add(v);
    let best = 0;
    for (const u of [...preds.get(v)!].sort(cmp)) { const du = d(u); if (du >= 0) best = Math.max(best, du + 1); }
    stack.delete(v);
    depth.set(v, best);
    return best;
  };
  for (const v of ids) d(v);
  const layerCount = Math.max(0, ...depth.values()) + 1;
  const cols: string[][] = Array.from({ length: layerCount }, () => []);
  for (const v of ids) cols[depth.get(v)!]!.push(v);
  const pos = new Map<string, number>();
  const reindex = (): void => cols.forEach((c) => c.forEach((v, i) => pos.set(v, i)));
  reindex();
  const bary = (v: string, nb: string[]): number => (nb.length ? nb.reduce((a, u) => a + pos.get(u)!, 0) / nb.length : pos.get(v)!);
  for (let it = 0; it < 6; it++) {
    for (let l = 1; l < layerCount; l++) { cols[l]!.sort((a, b) => bary(a, preds.get(a)!) - bary(b, preds.get(b)!) || cmp(a, b)); reindex(); }
    for (let l = layerCount - 2; l >= 0; l--) { cols[l]!.sort((a, b) => bary(a, succs.get(a)!) - bary(b, succs.get(b)!) || cmp(a, b)); reindex(); }
  }
  const placed = new Map<string, Placed>();
  cols.forEach((c, l) => c.forEach((v, i) => placed.set(v, { id: v, layer: l, row: i })));
  return { placed, layers: layerCount, rows: Math.max(1, ...cols.map((c) => c.length)) };
}
