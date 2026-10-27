// Leaf-by-leaf comparison of two JSON values, used by the evidence page to show the browser's computation against expected.json.
export function flatten(v: unknown, path = "", out = new Map<string, unknown>()): Map<string, unknown> {
  if (Array.isArray(v)) { if (v.length === 0) out.set(path, "[]"); v.forEach((x, i) => flatten(x, `${path}[${i}]`, out)); }
  else if (v && typeof v === "object") { const e = Object.entries(v); if (e.length === 0) out.set(path, "{}"); for (const [k, x] of e) flatten(x, `${path}.${k}`, out); }
  else out.set(path, v);
  return out;
}
export function compareLeaves(got: unknown, want: unknown): { leaves: number; mismatches: string[] } {
  const g = flatten(got), w = flatten(want);
  const bad: string[] = [];
  for (const k of new Set([...g.keys(), ...w.keys()])) if (!g.has(k) || !w.has(k) || g.get(k) !== w.get(k)) bad.push(k);
  return { leaves: w.size, mismatches: bad };
}
