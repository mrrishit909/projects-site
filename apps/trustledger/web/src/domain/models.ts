// Typed records of the twelve entities and the population the metrics are computed over. Mirror of domain/trustledger/models.py.
// `parse` turns a raw row into a record or throws DomainError(MALFORMED_RECORD). Field kinds: `id` non-blank text; `text` any text;
// `ts` an instant with a zone; a trailing `?` allows null; `enum:a|b` one of the listed values. Unknown keys are ignored.
import { DECISIONS, EVIDENCE_TYPES, ISSUE_STATUSES, METRIC_STATUSES, NON_PORTABLE_ESCAPES, ROLES, RULE_STATUSES, RULE_TYPES, RUN_KINDS, SEVERITIES, DEFAULT_TRIM, type Entity } from "./contract";
import { DomainError, MALFORMED_RECORD, PATTERN_NOT_PORTABLE, SCHEDULE_REQUIRED, ValueError } from "./errors";
import { fracOfDec, type Fr } from "./num";
import { parseHhmm, parseTs, zone, type Instant } from "./time";

export type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface Owner { owner_id: string; owner_name: string; team: string; role: string; active: boolean; deactivated_at: Instant | null }
export interface Dataset {
  dataset_id: string; dataset_name: string; source_system: string; owner_id: string | null; classification: string | null; registered_at: Instant;
  monitored: boolean; refresh_timezone: string | null; refresh_local_time: string | null; refresh_grace_minutes: number | null; last_refreshed_at: Instant | null;
}
export interface Field { field_id: string; dataset_id: string; field_name: string; data_type: string; nullable: boolean }
export interface Rule {
  rule_id: string; dataset_id: string; field_id: string | null; rule_type: string; severity: string; version_number: number; status: string;
  disabled_at: Instant | null; disabled_reason: string | null; definition: Row;
}
export interface RuleRun {
  rule_run_id: string; rule_id: string; rule_version: number; weight_version: string; kind: string; run_at: Instant; eligible_count: number;
  failure_count: number; rerun_for_issue: string | null;
}
export interface Issue {
  issue_id: string; rule_run_id: string; owner_id: string; status: string; detected_at: Instant; due_at: Instant | null; closed_at: Instant | null;
  verification_run_id: string | null; reopened_at: Instant[];
}
export interface Edge { edge_id: string; source_dataset_id: string; target_dataset_id: string; evidence_type: string; observed_at: Instant | null }
export interface MetricVersion {
  metric_version_id: string; metric_id: string; metric_name: string; version_number: number; definition: string | null; grain: string | null;
  source_fields: string[] | null; owner_id: string | null; refresh: string | null; valid_from: Instant; status: string;
}
export interface DefinitionChange { change_id: string; metric_version_id: string; previous_metric_version_id: string | null; reason: string; approved_by: string; changed_at: Instant }
export interface CustomerRecord { record_id: string; source_system: string; source_customer_id: string; normalized_name: string; address_key: string }
export interface Candidate {
  candidate_id: string; left_record_id: string; right_record_id: string; score: Fr; features: Row; explanation: string; uncertainty: string | null;
  proposed_by: string; proposed_at: Instant;
}
export interface Decision { merge_id: string; candidate_id: string; reviewer_id: string; decision: string; decided_at: Instant; reverses_merge_id: string | null; reason: string | null }

export interface Records {
  owners: Owner; datasets: Dataset; fields: Field; quality_rules: Rule; rule_runs: RuleRun; issues: Issue; lineage_edges: Edge;
  metric_versions: MetricVersion; definition_changes: DefinitionChange; customer_records: CustomerRecord; match_candidates: Candidate; merge_decisions: Decision;
}

const malformed = (entity: string, name: string, why: string): DomainError => new DomainError(MALFORMED_RECORD, `${entity}.${name}: ${why}`, name);
const isObj = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const tsOf = (entity: string, name: string, v: unknown): Instant => {
  try { return parseTs(v); } catch (e) { if (e instanceof ValueError) throw malformed(entity, name, e.message); throw e; }
};

function conv(entity: string, name: string, kind: string, v: unknown): unknown {
  const opt = kind.endsWith("?");
  const base = kind.replace(/\?+$/, "");
  if (v === null || v === undefined) {
    if (opt) return null;
    throw malformed(entity, name, "is required");
  }
  if (base === "id") {
    if (!isStr(v) || !v.trim() || v.length > 128) throw malformed(entity, name, "must be a non-blank text of at most 128 characters");
    return v;
  }
  if (base === "text") { if (!isStr(v)) throw malformed(entity, name, "must be text"); return v; }
  if (base === "bool") { if (typeof v !== "boolean") throw malformed(entity, name, "must be true or false"); return v; }
  if (base === "int") {
    if (typeof v !== "number" || !Number.isInteger(v) || v < 0 || v > 2 ** 31 - 1) throw malformed(entity, name, "must be a non-negative integer");
    return v;
  }
  if (base === "ts") return tsOf(entity, name, v);
  if (base === "ts_list") {
    if (!Array.isArray(v)) throw malformed(entity, name, "must be a list of instants");
    return v.map((x) => tsOf(entity, name, x));
  }
  if (base === "strs") {
    if (!Array.isArray(v) || !v.every(isStr)) throw malformed(entity, name, "must be a list of text");
    return [...v];
  }
  if (base === "dict") { if (!isObj(v)) throw malformed(entity, name, "must be an object"); return v; }
  if (base === "dec") {
    if (!isStr(v) || !/^\d+(\.\d+)?\n?$/.test(v)) throw malformed(entity, name, "must be a decimal string");
    return fracOfDec(v);
  }
  if (base.startsWith("enum:")) {
    const allowed = base.slice(5).split("|");
    if (!allowed.includes(v as string)) throw malformed(entity, name, `must be one of ${allowed.join(", ")}`);
    return v;
  }
  throw new Error(`unknown kind ${kind}`);
}

type Spec = readonly [string, string][];
const enumOf = (xs: readonly string[]): string => "enum:" + xs.join("|");
const SPECS: Record<Entity, { spec: Spec; optional: readonly string[] }> = {
  owners: { spec: [["owner_id", "id"], ["owner_name", "text"], ["team", "text"], ["role", enumOf(ROLES)], ["active", "bool"], ["deactivated_at", "ts?"]], optional: [] },
  datasets: { spec: [["dataset_id", "id"], ["dataset_name", "text"], ["source_system", "text"], ["owner_id", "text?"], ["classification", "text?"], ["registered_at", "ts"],
    ["monitored", "bool"], ["refresh_timezone", "text?"], ["refresh_local_time", "text?"], ["refresh_grace_minutes", "int?"], ["last_refreshed_at", "ts?"]], optional: [] },
  fields: { spec: [["field_id", "id"], ["dataset_id", "id"], ["field_name", "id"], ["data_type", "text"], ["nullable", "bool"]], optional: [] },
  quality_rules: { spec: [["rule_id", "id"], ["dataset_id", "id"], ["field_id", "text?"], ["rule_type", enumOf(RULE_TYPES)], ["severity", enumOf(SEVERITIES)],
    ["version_number", "int"], ["status", enumOf(RULE_STATUSES)], ["disabled_at", "ts?"], ["disabled_reason", "text?"], ["definition", "dict"]], optional: [] },
  rule_runs: { spec: [["rule_run_id", "id"], ["rule_id", "id"], ["rule_version", "int"], ["weight_version", "id"], ["kind", enumOf(RUN_KINDS)], ["run_at", "ts"],
    ["eligible_count", "int"], ["failure_count", "int"], ["rerun_for_issue", "text?"]], optional: ["rerun_for_issue"] },
  issues: { spec: [["issue_id", "id"], ["rule_run_id", "id"], ["owner_id", "id"], ["status", enumOf(ISSUE_STATUSES)], ["detected_at", "ts"], ["due_at", "ts?"],
    ["closed_at", "ts?"], ["verification_run_id", "text?"], ["reopened_at", "ts_list"]], optional: ["due_at", "closed_at", "verification_run_id", "reopened_at"] },
  lineage_edges: { spec: [["edge_id", "id"], ["source_dataset_id", "id"], ["target_dataset_id", "id"], ["evidence_type", enumOf(EVIDENCE_TYPES)], ["observed_at", "ts?"]], optional: ["observed_at"] },
  metric_versions: { spec: [["metric_version_id", "id"], ["metric_id", "id"], ["metric_name", "text"], ["version_number", "int"], ["definition", "text?"], ["grain", "text?"],
    ["source_fields", "strs?"], ["owner_id", "text?"], ["refresh", "text?"], ["valid_from", "ts"], ["status", enumOf(METRIC_STATUSES)]], optional: [] },
  definition_changes: { spec: [["change_id", "id"], ["metric_version_id", "id"], ["previous_metric_version_id", "text?"], ["reason", "text"], ["approved_by", "id"], ["changed_at", "ts"]], optional: [] },
  customer_records: { spec: [["record_id", "id"], ["source_system", "text"], ["source_customer_id", "text"], ["normalized_name", "text"], ["address_key", "text"]], optional: [] },
  match_candidates: { spec: [["candidate_id", "id"], ["left_record_id", "id"], ["right_record_id", "id"], ["score", "dec"], ["features", "dict"], ["explanation", "text"],
    ["uncertainty", "text?"], ["proposed_by", "id"], ["proposed_at", "ts"]], optional: ["uncertainty"] },
  merge_decisions: { spec: [["merge_id", "id"], ["candidate_id", "id"], ["reviewer_id", "id"], ["decision", enumOf(DECISIONS)], ["decided_at", "ts"], ["reverses_merge_id", "text?"], ["reason", "text?"]],
    optional: ["reverses_merge_id", "reason"] },
};

/** A raw row to its typed record; DomainError(MALFORMED_RECORD) when it is not well formed. */
export function parse<E extends Entity>(entity: E, row: unknown): Records[E] {
  if (!isObj(row)) throw new DomainError(MALFORMED_RECORD, `${entity} row must be an object`);
  const { spec, optional } = SPECS[entity];
  const rec: Row = {};
  for (const [name, kind] of spec) {
    const has = Object.prototype.hasOwnProperty.call(row, name);
    if (!has && !optional.includes(name)) throw malformed(entity, name, "is missing");
    if (!has) { rec[name] = kind === "ts_list" ? [] : null; continue; }
    rec[name] = conv(entity, name, kind, row[name]);
  }
  if (entity === "issues" && rec["status"] === "closed" && rec["closed_at"] === null) throw malformed(entity, "closed_at", "is required when the issue is closed");
  if (entity === "datasets") checkSchedule(rec as unknown as Dataset);
  if (entity === "quality_rules") checkRule(rec as unknown as Rule);
  if (entity === "rule_runs" && rec["failure_count"] > rec["eligible_count"]) throw malformed(entity, "failure_count", "cannot exceed eligible_count");
  if (entity === "quality_rules" && rec["status"] === "disabled" && (rec["disabled_at"] === null || !(rec["disabled_reason"] ?? "").trim())) throw malformed(entity, "disabled_reason", "a disabled rule needs disabled_at and a reason");
  if (entity === "merge_decisions" && (rec["decision"] === "reverse") !== (rec["reverses_merge_id"] !== null)) throw malformed(entity, "reverses_merge_id", "is required for, and only for, a reversal");
  if (entity === "match_candidates" && Object.keys(rec["features"]).length === 0) throw malformed(entity, "features", "must name at least one feature");
  return rec as Records[E];
}

function checkSchedule(d: Dataset): void {
  const any = d.refresh_timezone !== null || d.refresh_local_time !== null || d.refresh_grace_minutes !== null || d.monitored;
  if (!any) return;
  const ok = d.refresh_timezone !== null && d.refresh_local_time !== null && d.refresh_grace_minutes !== null;
  if (d.monitored && !ok) throw new DomainError(SCHEDULE_REQUIRED, "a monitored dataset needs refresh_timezone, refresh_local_time and refresh_grace_minutes", "refresh_timezone");
  if (ok) {
    try { zone(d.refresh_timezone!); parseHhmm(d.refresh_local_time!); } catch (e) { if (e instanceof ValueError) throw malformed("datasets", "refresh_timezone", e.message); throw e; }
    if (!(d.refresh_grace_minutes! >= 0 && d.refresh_grace_minutes! <= 1439)) throw malformed("datasets", "refresh_grace_minutes", "must be 0..1439");
  }
}

/** A pattern is JavaScript's RegExp here and Python's `re` there; the contract keeps patterns in the common subset (D-07). */
export function compilePattern(pattern: string): RegExp {
  return new RegExp(pattern);
}
/** A pattern is portable only if it avoids \s \d \w \b and their negations: the three engines read them differently. Explicit classes
 * ([ \t\r\n\f\v], [0-9]) are portable, and so is an escaped backslash followed by a letter (D-10 R7-04). */
export function patternPortable(pattern: string): boolean {
  for (let i = 0; i < pattern.length; ) {
    if (pattern[i] === "\\") {
      if (i + 1 < pattern.length && NON_PORTABLE_ESCAPES.includes(pattern[i + 1]!)) return false;
      i += 2;
    } else i += 1;
  }
  return true;
}
function checkRule(r: Rule): void {
  const d = r.definition, t = r.rule_type;
  const field = d["field"];
  if (t !== "timeliness" && !(isStr(field) && field)) throw malformed("quality_rules", "definition.field", "is required");
  if (t === "validity" && (r.status === "active" || "pattern" in d)) {
    if (isStr(d["pattern"]) && !patternPortable(d["pattern"])) {
      throw new DomainError(PATTERN_NOT_PORTABLE, "a pattern may not use \\s, \\d, \\w or \\b (they differ between Python, JavaScript and PostgreSQL): use explicit classes such as [ \\t\\r\\n\\f\\v] and [0-9]", "definition.pattern");
    }
    if (!isStr(d["pattern"])) throw malformed("quality_rules", "definition.pattern", "must be a valid regular expression");
    try { compilePattern(d["pattern"]); } catch { throw malformed("quality_rules", "definition.pattern", "must be a valid regular expression"); }
    if (!d["pattern"]) throw malformed("quality_rules", "definition.pattern", "is required");
  }
  const f = d["filter"];
  if (f !== undefined && f !== null && !(isObj(f) && isStr(f["field"]) && f["field"] && isStr(f["equals"]))) throw malformed("quality_rules", "definition.filter", "must be {field, equals} with text values");
  if (t === "relationship" && !["parent_dataset_id", "parent_field"].every((k) => isStr(d[k]) && d[k])) throw malformed("quality_rules", "definition.parent_dataset_id", "parent_dataset_id and parent_field are required");
}

/** A disabled rule disabled after `t` was still active at `t`; disabling keeps its history (D-01). */
export const ruleActiveAt = (r: Rule, t: Instant): boolean => r.status === "active" || (r.disabled_at !== null && r.disabled_at > t);

export interface WeightVersion { weight_version: string; valid_from: Instant; weights: Record<string, Fr> }

export interface Population {
  owners: Owner[]; datasets: Dataset[]; fields: Field[]; quality_rules: Rule[]; rule_runs: RuleRun[]; issues: Issue[]; lineage_edges: Edge[];
  metric_versions: MetricVersion[]; definition_changes: DefinitionChange[]; customer_records: CustomerRecord[]; match_candidates: Candidate[];
  merge_decisions: Decision[]; dataset_rows: Record<string, Row[]>; weight_versions: WeightVersion[]; checklist_versions: Row[]; checklist_version: string;
  trim: string; probe_definition_at: Instant | null; probe_timeliness: TimelinessProbe[]; weight_version: string | null;
}
/** A stated timeliness case (D-10 R7-01): judged by the rule alone. */
export interface TimelinessProbe { probe_id: string; timezone: string; local_time: string; grace_minutes: number; last_refreshed_at: Instant | null; as_of: Instant }
export function emptyPopulation(): Population {
  return { owners: [], datasets: [], fields: [], quality_rules: [], rule_runs: [], issues: [], lineage_edges: [], metric_versions: [], definition_changes: [],
    customer_records: [], match_candidates: [], merge_decisions: [], dataset_rows: {}, weight_versions: [], checklist_versions: [], checklist_version: "cl-1",
    trim: DEFAULT_TRIM, probe_definition_at: null, probe_timeliness: [], weight_version: null };
}
export function populationTotal(p: Population): number {
  const n = p.owners.length + p.datasets.length + p.fields.length + p.quality_rules.length + p.rule_runs.length + p.issues.length + p.lineage_edges.length +
    p.metric_versions.length + p.definition_changes.length + p.customer_records.length + p.match_candidates.length + p.merge_decisions.length;
  return n + Object.values(p.dataset_rows).reduce((a, v) => a + v.length, 0);
}
/** The weight version in force at `asOf`: the latest valid_from not after it (D-01). */
export function weightInForce(p: Population, asOf: Instant): string | null {
  const live = p.weight_versions.filter((w) => w.valid_from <= asOf);
  if (!live.length) return null;
  return live.reduce((a, b) => (b.valid_from > a.valid_from || (b.valid_from === a.valid_from && cmp(b.weight_version, a.weight_version) > 0) ? b : a)).weight_version;
}
/** Code-point order of two strings, which is what Python's sort and PostgreSQL's COLLATE "C" do. JavaScript's `<` compares UTF-16 units, which
 * puts an astral character (a surrogate pair) before U+E000..U+FFFF; this puts it after (D-10 R7-16). */
export function cmp(a: string, b: string): number {
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const x = a.charCodeAt(i), y = b.charCodeAt(i);
    if (x === y) continue;
    const sx = x >= 0xd800 && x <= 0xdfff, sy = y >= 0xd800 && y <= 0xdfff;
    if (sx !== sy) return sx ? 1 : -1; // a surrogate stands for an astral code point, above every BMP unit
    return x < y ? -1 : 1;
  }
  return a.length < b.length ? -1 : 1;
}
