// The checks the generator publishes about itself, evaluated by the same operators in the browser: the injection manifest's machine-checkable
// `checks` (paths into the shape of expected.json) and the designed relationships' realised figures. Each check carries the basis it can be
// judged on, because the published raw_records are a 2,000-row sample (contracts D-07): a check that describes the complete world may differ here.
import { canonicalJson } from "./hashing";
import type { Row } from "./contract";

export interface Check { path: string; equals?: unknown; find?: Row; min?: number; max?: number; contains?: unknown; not_contains?: unknown; absent?: boolean }
export interface CheckResult { injection: string; path: string; operator: string; want: unknown; got: unknown; ok: boolean }

const MISSING = Symbol("missing");
function get(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const k of path.split(".")) {
    if (Array.isArray(cur)) { const i = Number(k); if (!Number.isInteger(i) || i < 0 || i >= cur.length) return MISSING; cur = cur[i]; }
    else if (cur !== null && typeof cur === "object" && Object.prototype.hasOwnProperty.call(cur, k)) cur = (cur as Row)[k];
    else return MISSING;
  }
  return cur;
}
const same = (a: unknown, b: unknown): boolean => canonicalJson(a) === canonicalJson(b);
const show = (v: unknown): unknown => (v === MISSING ? "(absent)" : v);

/** One check of injection-manifest.json against a computed shape (the operators of `check_operators`). */
export function evalCheck(injection: string, shape: unknown, c: Check): CheckResult {
  const v = get(shape, c.path);
  const res = (operator: string, want: unknown, ok: boolean, got: unknown = show(v)): CheckResult => ({ injection, path: c.path, operator, want, got, ok });
  if (c.absent) return res("absent", true, v === MISSING);
  if (v === MISSING) return res(c.find ? "find" : Object.keys(c).find((k) => k !== "path") ?? "?", c.find ?? c.equals ?? c.min ?? c.max ?? c.contains ?? c.not_contains, false);
  if (c.find) {
    const hits = (Array.isArray(v) ? v : []).filter((x: Row) => Object.entries(c.find!).every(([k, w]) => same(x[k], w)));
    if (hits.length !== 1) return res("find", c.equals, false, `${hits.length} matches`);
    const ok = Object.entries(c.equals as Row).every(([k, w]) => same(hits[0][k], w));
    return res("find", c.equals, ok, hits[0]);
  }
  if ("equals" in c) return res("equals", c.equals, same(v, c.equals));
  if ("min" in c) return res("min", c.min, typeof v === "number" && v >= c.min!);
  if ("max" in c) return res("max", c.max, typeof v === "number" && v <= c.max!);
  if ("contains" in c) return res("contains", c.contains, Array.isArray(v) ? v.some((x) => same(x, c.contains)) : typeof v === "string" && typeof c.contains === "string" && v.includes(c.contains));
  if ("not_contains" in c) return res("not_contains", c.not_contains, !(typeof v === "string" && typeof c.not_contains === "string" && v.includes(c.not_contains)));
  return res("?", null, false);
}
export function injectionChecks(injections: Row[], shape: unknown): CheckResult[] {
  const out: CheckResult[] = [];
  for (const inj of injections) for (const c of inj["checks"] as Check[]) out.push(evalCheck(inj["id"], shape, c));
  return out;
}
