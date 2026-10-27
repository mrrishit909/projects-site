// Shared shapes and small helpers of the domain mirror. Rows are the JSON the application publishes; their fields are read by name.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any>;
export type Id = string | number | boolean | null;

/** Code-point order, as Python compares strings (UTF-16 order disagrees for astral characters). */
export function cmpStr(a: string, b: string): number {
  const x = Array.from(a), y = Array.from(b);
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) { const p = x[i]!.codePointAt(0)!, q = y[i]!.codePointAt(0)!; if (p !== q) return p < q ? -1 : 1; }
  return x.length === y.length ? 0 : x.length < y.length ? -1 : 1;
}
/** Total order on account ids: numbers numerically, strings by code point, numbers before strings. */
export function cmpId(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a < b ? -1 : a > b ? 1 : 0;
  if (typeof a === "string" && typeof b === "string") return cmpStr(a, b);
  return typeof a === "number" ? -1 : typeof b === "number" ? 1 : 0;
}
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
/** Python `==` on JSON values: objects regardless of key order, arrays in order, numbers by value. */
export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => deepEqual(x, b[i]));
  if (isObj(a) && isObj(b)) { const ka = Object.keys(a), kb = Object.keys(b); return ka.length === kb.length && ka.every((k) => k in b && deepEqual(a[k], b[k])); }
  return false;
}
/** Sorted-key, compact JSON: the form every hash and digest is taken over (Python `json.dumps(sort_keys=True, separators=(",", ":"))`). */
export function canon(v: unknown): string {
  return JSON.stringify(v, (_k, x) => (isObj(x) ? Object.fromEntries(Object.entries(x).sort(([p], [q]) => cmpStr(p, q))) : typeof x === "bigint" ? x.toString() : x));
}
