/** JSON with sorted keys: two values are the same when their canonical strings are. */
export const canon = (v: unknown): string => JSON.stringify(v, (_k, x) =>
  x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : x);
export const same = (a: unknown, b: unknown): boolean => canon(a) === canon(b);
