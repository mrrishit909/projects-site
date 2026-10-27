// Small helpers that give TypeScript the semantics of the Python expressions the domain uses.
import { cmpCodePoints } from "./hashing";
export { cmpCodePoints };

/** isinstance(v, int) and not a bool. */
export const isInt = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);
/** int(v) for a number, a bool or a numeric string; anything else raises, as Python's int() does. */
export function pyInt(v: unknown): number {
  if (typeof v === "boolean") return v ? 1 : 0;
  if (isInt(v)) return v;
  if (typeof v === "string" && /^\s*[+-]?\d+\s*$/.test(v)) return Number.parseInt(v, 10);
  throw new RangeError(`invalid literal for int(): ${JSON.stringify(v)}`);
}
export const isNone = (v: unknown): v is null | undefined => v === null || v === undefined;
export const isDict = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
/** A stable sort by a key function returning a tuple of comparable parts (strings by code point, numbers, bigints). */
export type Part = string | number | bigint;
export function cmpTuple(a: readonly Part[], b: readonly Part[]): number {
  for (let i = 0; i < a.length; i++) {
    const x = a[i]!, y = b[i]!;
    if (typeof x === "string" && typeof y === "string") { const c = cmpCodePoints(x, y); if (c) return c; }
    else if (x < y) return -1; else if (x > y) return 1;
  }
  return 0;
}
export function sortedBy<T>(xs: Iterable<T>, key: (x: T) => readonly Part[]): T[] {
  return [...xs].map((x) => [key(x), x] as const).sort((p, q) => cmpTuple(p[0], q[0])).map((p) => p[1]);
}
export const sortedStrings = (xs: Iterable<string>): string[] => [...xs].sort(cmpCodePoints);
/** The entries of a record in code-point key order (a Python `sorted(d.items())`). */
export const sortedEntries = <T>(o: Record<string, T>): [string, T][] => Object.entries(o).sort(([a], [b]) => cmpCodePoints(a, b));
