// Import validation (D-P9-01), mirroring domain/changeworks/ingest.py: parents first; per record: shape, duplicate id, foreign keys
// (UNKNOWN_* / DEPENDENT_REJECTED), then the business rules. A rejection is a whole record with its reason code and details; the valid
// records around it are unaffected, and a repeat of an accepted record rejects the *later* one. Nothing is silently dropped.
// `Validator.check` is also what the browser-memory roadmap edits use to test one new row against the rows already accepted.
import {
  BASES, BENEFIT_TYPES, CAPACITY_RATE_NAME, CONVERSION_NAME, COST_BASES, DEPENDENCY_TYPES, DIMENSIONS, ENTITIES, FOREIGN_KEYS, ID_FIELD, IMPACT_LEVELS,
  INITIATIVE_STATUSES, MAX_HORIZON, MAX_PERIOD, RAMP_NAME, SCENARIO_STATUSES, type Entity, type Row,
} from "./contract";
import { add, cmp, dec, ge, gt, isDecimal, le, lt, money, ONE, sumFr, ZERO } from "./num";
import { isTs, parseTs, type Instant } from "./time";

const INT_LIMIT = 2_000_000_000;

/** Python's str.strip() whitespace (it differs from JavaScript's trim at U+001C..U+001F, U+0085 and U+FEFF). */
const PY_WS = "\\t\\n\\u000b\\f\\r\\u001c-\\u001f \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const STRIP = new RegExp(`^[${PY_WS}]+|[${PY_WS}]+$`, "gu");
export const pyStrip = (s: string): string => s.replace(STRIP, "");
const cpLen = (s: string): number => Array.from(s).length;

export interface Population {
  config: Row;
  acc: Record<Entity, Row[]>;
  /** versions of an initiative's baseline that were approved (history); the initiative row names the current one */
  approvals: Row[];
}
export const emptyAcc = (): Record<Entity, Row[]> => Object.fromEntries(ENTITIES.map((e) => [e, [] as Row[]])) as Record<Entity, Row[]>;
export const newPopulation = (config: Row): Population => ({ config, acc: emptyAcc(), approvals: [] });
export const totalRows = (p: Population): number => ENTITIES.reduce((n, e) => n + p.acc[e].length, 0);

export interface Rejection {
  entity: Entity; id: string | number | null; reason_code: string; details: Row; raw_row: unknown;
}
export function rejectionRecord(r: Rejection): Row {
  const item: Row = { entity: r.entity, id: r.id, status: "rejected", reason_code: r.reason_code };
  if (Object.keys(r.details).length) item["details"] = r.details;
  item["raw_row"] = r.raw_row;
  return item;
}

// ---------------------------------------------------------------------------------------------------------------------------------- shapes
const isInt = (v: unknown): boolean => typeof v === "number" && Number.isInteger(v) && Math.abs(v) <= INT_LIMIT;
const isName = (v: unknown): boolean => typeof v === "string" && cpLen(pyStrip(v)) > 0 && cpLen(v) <= 2000;
const isId = (v: unknown): boolean => typeof v === "string" && cpLen(v) > 0 && cpLen(v) <= 128 && v === pyStrip(v) && !v.includes("\u0000");
const KINDS: Record<string, (v: unknown) => boolean> = {
  id: isId,
  name: isName,
  text: (v) => typeof v === "string" && cpLen(v) <= 2000 && !v.includes("\u0000"),
  int: isInt,
  dec: isDecimal,
  ts: isTs,
  bool: (v) => typeof v === "boolean",
  ids: (v) => Array.isArray(v) && v.length <= 500 && v.every(isId),
  decs: (v) => Array.isArray(v) && v.length > 0 && v.length <= 1200 && v.every(isDecimal),
};
const spec = (s: string): Record<string, string> => Object.fromEntries(s.split(" ").map((p) => p.split(":") as [string, string]));
/** field:kind, a trailing `?` allows null */
export const SHAPES: Record<Entity, Record<string, string>> = {
  initiatives: spec("initiative_id:id title:name sponsor_id:id status:text baseline_version:id? requested_start_period:int duration_periods:int deployment_period:int eligibility_rule_version:id"),
  process_baselines: spec("baseline_id:id initiative_id:id baseline_version:id volume:int minutes_per_case:int error_rate:dec evidence_ref:text measured_at:ts reason:text?"),
  assumption_versions: spec("assumption_id:id initiative_id:id? name:name version_number:int value:dec? values:decs? unit:text? rationale:text author_id:text evidence_ref:text? staffing_change_evidence_ref:text? created_at:ts"),
  resources: spec("resource_id:id name:name capacity_per_period:dec unit:name"),
  scenario_versions: spec("scenario_id:id baseline_version:id discount_rate:dec rate_basis:text rate_conversion_assumption_id:id? horizon_periods:int status:text initiative_ids:ids pinned_assumption_ids:ids created_at:ts"),
  cost_items: spec("cost_id:id initiative_id:id cost_key:id cost_type:text cost_basis:text amount:dec period_index:int? start_period:int? end_period:int? baseline_version:id?"),
  benefit_items: spec("benefit_id:id initiative_id:id benefit_type:text amount:dec period_index:int starts_period:int unit:text cash_realisation:bool? evidence_ref:text? benefit_source_key:text? baseline_trend_per_period:dec?"),
  dependencies: spec("dependency_id:id initiative_id:id prerequisite_id:id dependency_type:text lag_periods:int"),
  stakeholder_groups: spec("group_id:id group_name:name owner_id:id affected_count:int impact_level:text"),
  impact_mappings: spec("mapping_id:id initiative_id:id group_id:id operating_change:text impact_level:text"),
  resource_allocations: spec("allocation_id:id resource_id:id initiative_id:id period_index:int amount:dec"),
  readiness_assessments: spec("assessment_id:id group_id:id dimension:text score:int weight:dec assessed_at:ts"),
  adoption_observations: spec("observation_id:id initiative_id:id eligible_count:int adopted_count:int observed_at:ts eligibility_rule_version:id"),
  training_completions: spec("training_id:id initiative_id:id eligible_trainees:int completed:int recorded_at:ts eligibility_rule_version:id"),
  benefit_observations: spec("benefit_observation_id:id benefit_id:id measured_value:dec evidence_ref:text observed_at:ts"),
  risk_items: spec("risk_id:id initiative_id:id probability:dec impact:dec mitigation:text"),
  forecast_versions: spec("forecast_id:id initiative_id:id version_number:int period_index:int amount:dec reason:text created_at:ts"),
};

/** Fields that are missing, null where not allowed, or of the wrong type / format (empty when the row is well formed). */
export function shapeProblems(entity: Entity, row: unknown): Record<string, string> {
  if (row === null || typeof row !== "object" || Array.isArray(row)) return { $: "a record must be an object" };
  const r = row as Row;
  const bad: Record<string, string> = {};
  for (const [name, kind] of Object.entries(SHAPES[entity])) {
    const nullable = kind.endsWith("?");
    const base = kind.replace(/\?+$/, "");
    if (!(name in r)) bad[name] = "missing";
    else if (r[name] === null) { if (!nullable) bad[name] = "null not allowed"; }
    else if (!KINDS[base]!(r[name])) bad[name] = `not a valid ${base}`;
  }
  return bad;
}

type Verdict = [string, Row] | null;
const has = (a: readonly string[], v: unknown): boolean => a.includes(v as string);
const nul = (v: unknown): boolean => v === null || v === undefined;
const key = (...p: unknown[]): string => p.map((x) => (x === null || x === undefined ? "\u0001null" : String(x))).join("\u0000");

// ---------------------------------------------------------------------------------------------------------------------------------- validator
/** Accepted rows so far plus the checks. `add` = `check` then record; `check` never changes state. */
export class Validator {
  readonly pop: Population;
  readonly acc: Record<Entity, Row[]>;
  readonly ids: Record<Entity, Set<string>>;
  readonly rejectedIds: Record<Entity, Set<string | number | null>>;

  constructor(population?: Population, config?: Row) {
    this.pop = population ?? newPopulation(config ?? { period_basis: "annual", period_start: "2026-01-01", as_of: null });
    this.acc = this.pop.acc;
    this.ids = Object.fromEntries(ENTITIES.map((e) => [e, new Set(this.acc[e].map((r) => r[ID_FIELD[e]] as string))])) as Record<Entity, Set<string>>;
    this.rejectedIds = Object.fromEntries(ENTITIES.map((e) => [e, new Set<string | number | null>()])) as Record<Entity, Set<string | number | null>>;
  }

  check(entity: Entity, row: unknown): Rejection | null {
    const rid0 = row !== null && typeof row === "object" && !Array.isArray(row) ? (row as Row)[ID_FIELD[entity]] : undefined;
    const rid = typeof rid0 === "string" || typeof rid0 === "number" ? rid0 : null;
    const problems = shapeProblems(entity, row);
    if (Object.keys(problems).length) return { entity, id: rid, reason_code: "MALFORMED_RECORD", details: { fields: problems }, raw_row: row };
    const r = row as Row;
    if (this.ids[entity].has(rid as string)) return { entity, id: rid, reason_code: "DUPLICATE_ID", details: {}, raw_row: row };
    for (const [fld, parent, unknown, nullable, isList] of FOREIGN_KEYS[entity] ?? []) {
      for (const v of (isList ? r[fld] : [r[fld]]) as unknown[]) {
        if (v === null && nullable) continue;
        if (this.ids[parent].has(v as string)) continue;
        const code = this.rejectedIds[parent].has(v as string) ? "DEPENDENT_REJECTED" : unknown;
        return { entity, id: rid, reason_code: code, details: {}, raw_row: row }; // the expected records carry no details for a key problem
      }
    }
    const res = this.rule(entity, r);
    return res ? { entity, id: rid, reason_code: res[0], details: res[1], raw_row: row } : null;
  }

  add(entity: Entity, row: Row): Rejection | null {
    const rej = this.check(entity, row);
    if (rej === null) this.accept(entity, row);
    else if (rej.reason_code !== "DUPLICATE_ID" && rej.reason_code !== "MALFORMED_RECORD") this.rejectedIds[entity].add(rej.id);
    return rej;
  }
  accept(entity: Entity, row: Row): void { this.acc[entity].push(row); this.ids[entity].add(row[ID_FIELD[entity]] as string); }

  private initiative(iid: string): Row { return this.acc.initiatives.find((i) => i["initiative_id"] === iid)!; }
  conversionExists(iid: string): boolean {
    return this.acc.assumption_versions.some((a) => a["initiative_id"] === iid && a["name"] === CAPACITY_RATE_NAME && !!a["staffing_change_evidence_ref"]);
  }
  /** A path b -> ... -> a over accepted prerequisite edges (initiative -> prerequisite); the cycle that adding a -> b would close. */
  cycleFrom(a: string, b: string): string[] | null {
    const edges = new Map<string, string[]>();
    for (const d of this.acc.dependencies) (edges.get(d["initiative_id"]) ?? edges.set(d["initiative_id"], []).get(d["initiative_id"])!).push(d["prerequisite_id"]);
    const stack: [string, string[]][] = [[b, [b]]];
    const seen = new Set<string>();
    while (stack.length) {
      const [node, path] = stack.pop()!;
      if (node === a) return [a, ...path];
      if (seen.has(node)) continue;
      seen.add(node);
      for (const nxt of [...(edges.get(node) ?? [])].sort(cmp).reverse()) stack.push([nxt, [...path, nxt]]);
    }
    return null;
  }

  // business rules (after the key checks); returns [code, details] or null
  private rule(e: Entity, r: Row): Verdict {
    const acc = this.acc;
    switch (e) {
      case "initiatives": {
        if (!has(INITIATIVE_STATUSES, r["status"])) return ["STATUS_NOT_ALLOWED", { status: r["status"] }];
        if (!(r["requested_start_period"] >= 0 && r["requested_start_period"] <= MAX_PERIOD && r["deployment_period"] >= 0 && r["deployment_period"] <= MAX_PERIOD)) return ["INVALID_PERIOD", {}];
        if (!(r["duration_periods"] >= 1 && r["duration_periods"] <= MAX_PERIOD)) return ["INVALID_DURATION", { duration_periods: r["duration_periods"] }];
        return null;
      }
      case "process_baselines": {
        if (r["volume"] < 0 || r["minutes_per_case"] < 0 || !(ge(dec(r["error_rate"]), ZERO) && le(dec(r["error_rate"]), ONE))) return ["INVALID_AMOUNT", {}];
        if (!pyStrip(r["evidence_ref"])) return ["EVIDENCE_REQUIRED", {}];
        for (const b of acc[e]) {
          if (b["initiative_id"] === r["initiative_id"] && b["baseline_version"] === r["baseline_version"]) {
            const ini = this.initiative(r["initiative_id"]);
            if (ini["baseline_version"] === r["baseline_version"]) return ["BASELINE_FROZEN", { baseline_version: r["baseline_version"], existing_id: b["baseline_id"] }];
            return ["VERSION_EXISTS", { existing_id: b["baseline_id"], baseline_version: r["baseline_version"] }];
          }
        }
        return null;
      }
      case "assumption_versions": {
        if (r["version_number"] < 1) return ["INVALID_VERSION", {}];
        if (!pyStrip(r["rationale"])) return ["RATIONALE_REQUIRED", {}];
        if (!pyStrip(r["author_id"])) return ["AUTHOR_REQUIRED", {}];
        if (nul(r["value"]) === nul(r["values"])) return ["INVALID_ASSUMPTION", { reason: "exactly one of value and values" }];
        if (r["name"] === RAMP_NAME) {
          const vals = ((r["values"] ?? []) as string[]).map(dec);
          if (!vals.length || vals.some((v) => lt(v, ZERO) || gt(v, ONE)) || vals.slice(1).some((b, i) => lt(b, vals[i]!))) {
            return ["INVALID_RAMP", { reason: "a ramp is a non-decreasing list of fractions in [0, 1]" }];
          }
        }
        for (const a of acc[e]) {
          if (key(a["initiative_id"], a["name"], a["version_number"]) === key(r["initiative_id"], r["name"], r["version_number"])) {
            return ["VERSION_EXISTS", { existing_id: a["assumption_id"], version_number: r["version_number"] }];
          }
        }
        return null;
      }
      case "resources": {
        if (lt(dec(r["capacity_per_period"]), ZERO)) return ["INVALID_AMOUNT", {}];
        return null;
      }
      case "scenario_versions": {
        if (!has(SCENARIO_STATUSES, r["status"])) return ["STATUS_NOT_ALLOWED", { status: r["status"] }];
        if (!(r["horizon_periods"] >= 1 && r["horizon_periods"] <= MAX_HORIZON)) return ["INVALID_HORIZON", { horizon_periods: r["horizon_periods"] }];
        if (!has(BASES, r["rate_basis"])) return ["INVALID_RATE_BASIS", { rate_basis: r["rate_basis"] }];
        if (!(ge(dec(r["discount_rate"]), ZERO) && le(dec(r["discount_rate"]), ONE))) return ["INVALID_RATE", { discount_rate: r["discount_rate"] }];
        if (!r["initiative_ids"].length) return ["INVALID_SCENARIO", { reason: "a scenario names at least one initiative" }];
        const periodBasis = this.pop.config["period_basis"];
        if (r["rate_basis"] !== periodBasis) {
          const cid = r["rate_conversion_assumption_id"];
          if (cid === null) return ["RATE_PERIOD_MISMATCH", { rate_basis: r["rate_basis"], period_basis: periodBasis }];
          const conv = acc.assumption_versions.find((a) => a["assumption_id"] === cid)!;
          if (conv["name"] !== CONVERSION_NAME || conv["value"] === null || !(ge(dec(conv["value"]), ZERO) && le(dec(conv["value"]), ONE))) {
            return ["INVALID_CONVERSION", { assumption_id: cid, expected_name: CONVERSION_NAME }];
          }
        }
        return null;
      }
      case "cost_items": {
        if (r["cost_type"] === "one_time") {
          if (r["period_index"] === null || !(r["period_index"] >= 0 && r["period_index"] <= MAX_PERIOD) || r["start_period"] !== null || r["end_period"] !== null) return ["INVALID_PERIOD", {}];
          for (const c of acc[e]) {
            if (key(c["initiative_id"], c["cost_key"], c["cost_basis"], c["cost_type"]) === key(r["initiative_id"], r["cost_key"], r["cost_basis"], "one_time")) {
              return ["ONE_TIME_COST_REPEATED", { first_cost_id: c["cost_id"], first_period: c["period_index"], repeat_period: r["period_index"] }];
            }
          }
        } else if (r["cost_type"] === "recurring") {
          if (r["period_index"] !== null || r["start_period"] === null || r["end_period"] === null || !(r["start_period"] >= 0 && r["start_period"] < r["end_period"] && r["end_period"] <= MAX_PERIOD)) return ["INVALID_PERIOD", {}];
        } else return ["INVALID_COST_TYPE", {}];
        if (!has(COST_BASES, r["cost_basis"]) || lt(dec(r["amount"]), ZERO)) return ["INVALID_AMOUNT", {}];
        return null;
      }
      case "benefit_items": {
        if (!has(BENEFIT_TYPES, r["benefit_type"])) return ["INVALID_BENEFIT_TYPE", {}];
        if (lt(dec(r["amount"]), ZERO) || (r["baseline_trend_per_period"] !== null && lt(dec(r["baseline_trend_per_period"]), ZERO))) return ["INVALID_AMOUNT", {}];
        if (r["unit"] !== (r["benefit_type"] === "capacity" ? "hours" : "USD")) return ["INVALID_UNIT", { unit: r["unit"], benefit_type: r["benefit_type"] }];
        const ini = this.initiative(r["initiative_id"]);
        if (r["starts_period"] < ini["deployment_period"]) return ["BENEFIT_BEFORE_DEPLOYMENT", { starts_period: r["starts_period"], deployment_period: ini["deployment_period"] }];
        if (r["period_index"] < r["starts_period"] || r["period_index"] > MAX_PERIOD) return ["INVALID_PERIOD", {}];
        if (r["benefit_type"] === "capacity" && r["cash_realisation"] && !this.conversionExists(r["initiative_id"])) return ["CAPACITY_WITHOUT_CONVERSION", { hours: r["amount"] }];
        return null;
      }
      case "dependencies": {
        if (!has(DEPENDENCY_TYPES, r["dependency_type"])) return ["INVALID_DEPENDENCY_TYPE", {}];
        if (r["lag_periods"] < 0 || r["lag_periods"] > MAX_PERIOD) return ["INVALID_LAG", {}];
        const cyc = r["initiative_id"] === r["prerequisite_id"] ? [r["initiative_id"], r["initiative_id"]] : this.cycleFrom(r["initiative_id"], r["prerequisite_id"]);
        if (cyc) return ["DEPENDENCY_CYCLE", { cycle: cyc }];
        return null;
      }
      case "stakeholder_groups": {
        if (!has(IMPACT_LEVELS, r["impact_level"])) return ["INVALID_IMPACT_LEVEL", {}];
        if (r["group_name"].includes("@") || /\p{Nd}{6,}/u.test(r["group_name"].replaceAll(" ", "").replaceAll("-", ""))) return ["LABEL_NOT_SYNTHETIC", { field: "group_name" }]; // a synthetic role or team, never an e-mail or a phone number
        if (r["affected_count"] < 0) return ["INVALID_COUNT", {}];
        return null;
      }
      case "impact_mappings": {
        if (!has(IMPACT_LEVELS, r["impact_level"])) return ["INVALID_IMPACT_LEVEL", {}];
        if (!pyStrip(r["operating_change"])) return ["OPERATING_CHANGE_REQUIRED", {}];
        return null;
      }
      case "resource_allocations": {
        const cap = dec(acc.resources.find((x) => x["resource_id"] === r["resource_id"])!["capacity_per_period"]);
        if (lt(dec(r["amount"]), ZERO) || !(r["period_index"] >= 0 && r["period_index"] <= MAX_PERIOD)) return ["INVALID_AMOUNT", {}];
        const used = sumFr(acc[e].filter((a) => a["resource_id"] === r["resource_id"] && a["period_index"] === r["period_index"]).map((a) => dec(a["amount"])));
        if (gt(add(used, dec(r["amount"])), cap)) { // D-P9-15: checked in id order; a sum equal to capacity is allowed
          return ["RESOURCE_OVERALLOCATED", { resource_id: r["resource_id"], periods: [r["period_index"]], allocated_before: money(used), requested: r["amount"], capacity: money(cap) }];
        }
        return null;
      }
      case "readiness_assessments": {
        if (!has(DIMENSIONS, r["dimension"])) return ["INVALID_DIMENSION", {}];
        if (!(r["score"] >= 1 && r["score"] <= 5)) return ["INVALID_SCORE", { score: r["score"] }];
        if (!gt(dec(r["weight"]), ZERO)) return ["INVALID_WEIGHT", {}];
        return null;
      }
      case "adoption_observations":
      case "training_completions": {
        const [a, b] = e === "adoption_observations" ? ["eligible_count", "adopted_count"] : ["eligible_trainees", "completed"];
        const ini = this.initiative(r["initiative_id"]);
        if (r["eligibility_rule_version"] !== ini["eligibility_rule_version"]) return ["ELIGIBILITY_RULE_MISMATCH", { initiative_rule: ini["eligibility_rule_version"], row_rule: r["eligibility_rule_version"] }];
        if (r[a!] < 0 || r[b!] < 0 || r[b!] > r[a!]) return [e === "adoption_observations" ? "ADOPTED_EXCEEDS_ELIGIBLE" : "COMPLETED_EXCEEDS_ELIGIBLE", { eligible: r[a!], numerator: r[b!] }];
        return null;
      }
      case "benefit_observations": {
        if (lt(dec(r["measured_value"]), ZERO)) return ["INVALID_AMOUNT", {}];
        return null;
      }
      case "risk_items": {
        if (!(ge(dec(r["probability"]), ZERO) && le(dec(r["probability"]), ONE))) return ["PROBABILITY_OUT_OF_RANGE", { probability: r["probability"] }];
        if (lt(dec(r["impact"]), ZERO)) return ["INVALID_AMOUNT", {}];
        return null;
      }
      case "forecast_versions": {
        if (r["version_number"] < 1 || !(r["period_index"] >= 0 && r["period_index"] <= MAX_PERIOD) || lt(dec(r["amount"]), ZERO)) return ["INVALID_AMOUNT", {}];
        for (const a of acc[e]) {
          if (key(a["initiative_id"], a["version_number"], a["period_index"]) === key(r["initiative_id"], r["version_number"], r["period_index"])) {
            return ["VERSION_EXISTS", { existing_id: a["forecast_id"], version_number: r["version_number"] }];
          }
        }
        return null;
      }
    }
  }
}

// ---------------------------------------------------------------------------------------------------------------------------------- batch
export interface Ingest { population: Population; rejected: Rejection[] }
export function ingestCounts(ing: Ingest): Record<string, { accepted: number; rejected: number }> {
  return Object.fromEntries(ENTITIES.map((e) => [e, { accepted: ing.population.acc[e].length, rejected: ing.rejected.filter((r) => r.entity === e).length }]));
}
export const rejectedRecords = (ing: Ingest): Row[] => ing.rejected.map(rejectionRecord);
export const configOf = (inputs: Row): Row => ({ period_basis: inputs["period_basis"], period_start: inputs["period_start"], as_of: inputs["as_of"] ?? null });

/** Validate a whole dataset (the shape of inputs.json): accepted rows per entity and the rejected records in entity order then row order. */
export function validateBatch(inputs: Row): Ingest {
  const v = new Validator(undefined, configOf(inputs));
  const rejected: Rejection[] = [];
  for (const e of ENTITIES) {
    for (const row of (inputs[e] ?? []) as unknown[]) {
      const rej = v.add(e, row as Row);
      if (rej !== null) rejected.push(rej);
    }
  }
  return { population: v.pop, rejected };
}
export function parseAsOf(s: string | null | undefined): Instant | null { return s ? parseTs(s) : null; }
