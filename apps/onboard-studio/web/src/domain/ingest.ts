// Batch validation with dependent rejection (D-02, D-03, D-05). Pure: the same input gives an equal result.
// A case that breaks a case-level rule is rejected together with every row that hangs off it, each carrying
// the case's reason. Reasons, in priority order when several apply: WORKFLOW_VERSION_NOT_PUBLISHED,
// DEPENDENCY_CYCLE, SELF_APPROVAL, STEP_NOT_READY, MISSING_REQUIRED_DOCUMENT, CASE_ALREADY_COMPLETE,
// PAUSE_REASON_NOT_CONFIGURED, ORPHAN_REFERENCE. DECISION_CONFLICT rejects only the later approval of a
// step version that already has a decision. Mirrors domain/onboard_studio/ingest.py.
import {
  ACCEPTED_INPUT_CONTRACTS, CONTRACT_VERSION, DEPENDENCY_TYPES, DOCUMENT_STATES, ENTITIES, STEP_STATES, type EntityName,
} from "./contract";
import {
  CASE_ALREADY_COMPLETE, CASE_REASONS, CONTRACT_MISMATCH, DECISION_CONFLICT, DEPENDENCY_CYCLE, DUPLICATE_ID, DomainError,
  MALFORMED_RECORD, MISSING_REQUIRED_DOCUMENT, ORPHAN_REFERENCE, PAUSE_REASON_NOT_CONFIGURED, SELF_APPROVAL,
  STEP_NOT_READY, WORKFLOW_VERSION_NOT_PUBLISHED,
} from "./errors";
import { parseTs, parseTsOpt } from "./time";
import type {
  Approval, Assignment, CalendarInterval, Case, CaseEvent, Dependency, DocumentVersion, EntityCount, EntityTypes,
  Organization, PipelineInputs, Population, RawRow, RejectedRecord, Requirements, SlaRule, StepDefinition,
  StepInstance, WaitingInterval, WorkflowVersion,
} from "./types";
import { acceptedTypesLatest, missingForCompletion, topologicalOrder } from "./workflow";

export const ID_FIELD: Record<EntityName, string> = {
  organizations: "organization_id", cases: "case_id", workflow_versions: "workflow_version_id",
  step_definitions: "step_definition_id", dependencies: "dependency_id", step_instances: "step_instance_id",
  assignments: "assignment_id", document_versions: "document_version_id", approvals: "approval_id",
  sla_rules: "sla_rule_id", calendar_intervals: "calendar_interval_id", waiting_intervals: "waiting_interval_id",
  case_events: "event_id",
};

// ---- field parsers (throw on a malformed value; the caller maps that to MALFORMED_RECORD) ----------
const has = (r: RawRow, k: string): boolean => Object.prototype.hasOwnProperty.call(r, k);
function req(r: RawRow, k: string): unknown {
  if (!has(r, k)) throw new Error(`missing ${k}`);
  return r[k];
}
const opt = (r: RawRow, k: string): unknown => (has(r, k) ? r[k] : null);
function str(v: unknown): string {
  if (typeof v !== "string" || v === "") throw new Error("non-empty string required");
  return v;
}
const strOpt = (v: unknown): string | null => (v === null || v === undefined ? null : str(v));
function int(v: unknown, minimum: number): number {
  if (typeof v !== "number" || !Number.isInteger(v) || v < minimum) throw new Error(`integer >= ${minimum} required`);
  return v;
}
function posNumber(v: unknown): number {
  let n: number;
  if (typeof v === "number") { if (!Number.isInteger(v)) throw new Error("positive number required"); n = v; }
  else if (typeof v === "string" && /^\s*[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?\s*$/i.test(v)) n = Number(v);
  else throw new Error("positive number required");
  if (!Number.isFinite(n) || n <= 0) throw new Error("positive number required");
  return n;
}
function bool(v: unknown): boolean {
  if (typeof v !== "boolean") throw new Error("boolean required");
  return v;
}
function choice<T extends string>(v: unknown, allowed: readonly T[]): T {
  if (typeof v !== "string" || !(allowed as readonly string[]).includes(v)) throw new Error("allowed value required");
  return v as T;
}
function pausePolicy(v: unknown): string[] {
  if (!Array.isArray(v) || !v.every((x) => typeof x === "string" && x !== "")) throw new Error("pause_policy must be a list of reason codes");
  return v as string[];
}
/** Python truthiness of a JSON value (for the optional pause_requested flag). */
function truthy(v: unknown): boolean {
  if (v === null || v === undefined || v === false || v === 0 || v === "") return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.keys(v as object).length > 0;
  return true;
}

const PARSERS: { [K in EntityName]: (r: RawRow) => EntityTypes[K] } = {
  organizations: (r): Organization => ({
    organization_id: str(req(r, "organization_id")), organization_name: str(req(r, "organization_name")),
    segment: str(req(r, "segment")), region: str(req(r, "region")), created_at: parseTs(req(r, "created_at")),
  }),
  workflow_versions: (r): WorkflowVersion => ({
    workflow_version_id: str(req(r, "workflow_version_id")), template_id: str(req(r, "template_id")),
    version_number: int(req(r, "version_number"), 1), published_at: parseTsOpt(opt(r, "published_at")),
    definition_hash: strOpt(opt(r, "definition_hash")),
  }),
  step_definitions: (r): StepDefinition => ({
    step_definition_id: str(req(r, "step_definition_id")), workflow_version_id: str(req(r, "workflow_version_id")),
    step_name: str(req(r, "step_name")), required: bool(req(r, "required")), role_key: str(req(r, "role_key")),
    sequence: int(req(r, "sequence"), 0),
  }),
  dependencies: (r): Dependency => ({
    dependency_id: str(req(r, "dependency_id")), step_definition_id: str(req(r, "step_definition_id")),
    prerequisite_id: str(req(r, "prerequisite_id")),
    dependency_type: choice(has(r, "dependency_type") ? r.dependency_type : "mandatory", DEPENDENCY_TYPES),
    created_at: parseTsOpt(opt(r, "created_at")),
  }),
  sla_rules: (r): SlaRule => ({
    sla_rule_id: str(req(r, "sla_rule_id")), workflow_version_id: str(req(r, "workflow_version_id")),
    business_minutes: posNumber(req(r, "business_minutes")), pause_policy: pausePolicy(req(r, "pause_policy")),
    calendar_id: str(req(r, "calendar_id")),
  }),
  calendar_intervals: (r): CalendarInterval => {
    const a = parseTs(req(r, "starts_at")), b = parseTs(req(r, "ends_at"));
    if (b <= a) throw new Error("ends_at must be after starts_at");
    return {
      calendar_interval_id: str(req(r, "calendar_interval_id")), calendar_id: str(req(r, "calendar_id")),
      starts_at: a, ends_at: b, timezone: str(req(r, "timezone")),
      kind: choice(has(r, "kind") ? r.kind : "working", ["working", "holiday"] as const),
    };
  },
  cases: (r): Case => {
    const opened = parseTs(req(r, "opened_at")), done = parseTsOpt(opt(r, "completed_at"));
    if (done !== null && done < opened) throw new Error("completed_at before opened_at");
    return {
      case_id: str(req(r, "case_id")), organization_id: str(req(r, "organization_id")),
      workflow_version_id: str(req(r, "workflow_version_id")),
      status: choice(req(r, "status"), ["open", "completed"] as const), opened_at: opened, completed_at: done,
    };
  },
  step_instances: (r): StepInstance => ({
    step_instance_id: str(req(r, "step_instance_id")), case_id: str(req(r, "case_id")),
    step_definition_id: str(req(r, "step_definition_id")), status: choice(req(r, "status"), STEP_STATES),
    version_number: int(req(r, "version_number"), 1), ready_at: parseTsOpt(opt(r, "ready_at")),
    started_at: parseTsOpt(opt(r, "started_at")), approved_at: parseTsOpt(opt(r, "approved_at")),
  }),
  assignments: (r): Assignment => {
    const a = parseTs(req(r, "assigned_at")), e = parseTsOpt(opt(r, "ended_at"));
    if (e !== null && e < a) throw new Error("ended_at before assigned_at");
    return { assignment_id: str(req(r, "assignment_id")), step_instance_id: str(req(r, "step_instance_id")), assignee_id: str(req(r, "assignee_id")), assigned_at: a, ended_at: e };
  },
  document_versions: (r): DocumentVersion => ({
    document_version_id: str(req(r, "document_version_id")), case_id: str(req(r, "case_id")),
    document_type: str(req(r, "document_type")), version_number: int(req(r, "version_number"), 1),
    content_hash: str(req(r, "content_hash")), review_status: choice(req(r, "review_status"), DOCUMENT_STATES),
    submitted_at: parseTs(req(r, "submitted_at")), reviewed_at: parseTsOpt(opt(r, "reviewed_at")),
  }),
  approvals: (r): Approval => ({
    approval_id: str(req(r, "approval_id")), step_instance_id: str(req(r, "step_instance_id")),
    reviewer_id: str(req(r, "reviewer_id")), decision: str(req(r, "decision")), decided_at: parseTs(req(r, "decided_at")),
    reason: (opt(r, "reason") as string | null) ?? null,
    version_number: opt(r, "version_number") === null ? null : int(r.version_number, 1),
  }),
  waiting_intervals: (r): WaitingInterval => {
    const a = parseTs(req(r, "starts_at")), e = parseTsOpt(opt(r, "ends_at"));
    if (e !== null && e < a) throw new Error("ends_at before starts_at");
    return {
      waiting_interval_id: str(req(r, "waiting_interval_id")), case_id: str(req(r, "case_id")),
      reason_code: str(req(r, "reason_code")), starts_at: a, ends_at: e, pause_requested: truthy(opt(r, "pause_requested")),
    };
  },
  case_events: (r): CaseEvent => ({
    event_id: str(req(r, "event_id")), case_id: str(req(r, "case_id")), event_type: str(req(r, "event_type")),
    actor_id: str(req(r, "actor_id")), occurred_at: parseTs(req(r, "occurred_at")),
  }),
};

/** `{wfv: {required_document_types: [...]}}` (D-05) to `{wfv: [types]}`. */
export function normaliseRequirements(block: PipelineInputs["workflow_requirements"] | null | undefined): Requirements {
  const out: Record<string, readonly string[]> = {};
  for (const [wfv, spec] of Object.entries(block ?? {})) {
    out[wfv] = Array.isArray(spec) ? spec : ((spec as { required_document_types?: readonly string[] }).required_document_types ?? []);
  }
  return out;
}

export interface IngestResult {
  accepted: { [K in EntityName]: EntityTypes[K][] };
  acceptedRows: { [K in EntityName]: RawRow[] };
  rejected: RejectedRecord[];
  counts: Record<EntityName, EntityCount>;
  requirements: Requirements;
}

/** The accepted records as a Population (arrays are copied). */
export function populationOf(res: IngestResult): Population {
  const pop: Record<string, unknown> = { requirements: { ...res.requirements } };
  for (const e of ENTITIES) pop[e] = [...res.accepted[e]];
  return pop as unknown as Population;
}

function groupBy<T>(items: readonly T[], key: (x: T) => string | undefined): Map<string, T[]> {
  const out = new Map<string, T[]>();
  for (const x of items) {
    const k = key(x);
    if (k === undefined) continue;
    const list = out.get(k);
    if (list) list.push(x); else out.set(k, [x]);
  }
  return out;
}

interface Ctx {
  versions: Map<string, WorkflowVersion>; orgIds: Set<string>; cyclic: Set<string>;
  stepsByVersion: Map<string, StepDefinition[]>; depsByVersion: Map<string, Dependency[]>;
  instancesByCase: Map<string, StepInstance[]>; approvalsByCase: Map<string, Approval[]>;
  assignees: Map<string, Set<string>>; docsByCase: Map<string, DocumentVersion[]>;
  eventsByCase: Map<string, CaseEvent[]>; waitingByCase: Map<string, WaitingInterval[]>;
  slaByVersion: Map<string, SlaRule>; requirements: Requirements;
}

/** Every case-level rule the case breaks (a set; the caller picks by priority). */
function caseReasons(c: Case, ctx: Ctx): Set<string> {
  const out = new Set<string>();
  const wv = ctx.versions.get(c.workflow_version_id);
  if (!ctx.orgIds.has(c.organization_id) || wv === undefined) out.add(ORPHAN_REFERENCE);
  if (wv !== undefined && (wv.published_at === null || wv.published_at > c.opened_at)) out.add(WORKFLOW_VERSION_NOT_PUBLISHED);
  if (ctx.cyclic.has(c.workflow_version_id)) out.add(DEPENDENCY_CYCLE);

  const steps = new Map((ctx.stepsByVersion.get(c.workflow_version_id) ?? []).map((s) => [s.step_definition_id, s]));
  const instances = ctx.instancesByCase.get(c.case_id) ?? [];
  const instByDef = new Map(instances.map((i) => [i.step_definition_id, i])); // the last instance of a step wins
  if (instances.some((i) => !steps.has(i.step_definition_id))) out.add(ORPHAN_REFERENCE);

  // SELF_APPROVAL: the reviewer is any assignee ever on the step instance.
  for (const a of ctx.approvalsByCase.get(c.case_id) ?? []) {
    if (ctx.assignees.get(a.step_instance_id)?.has(a.reviewer_id)) out.add(SELF_APPROVAL);
  }

  // STEP_NOT_READY: work began before every mandatory prerequisite was approved.
  const deps = ctx.depsByVersion.get(c.workflow_version_id) ?? [];
  for (const i of instances) {
    if (i.status === "blocked" && i.ready_at === null && i.started_at === null) continue;
    const marks = [i.ready_at, i.started_at].filter((t): t is number => t !== null);
    for (const d of deps) {
      if (d.step_definition_id !== i.step_definition_id || d.dependency_type !== "mandatory") continue;
      const pi = instByDef.get(d.prerequisite_id);
      if (pi === undefined || pi.approved_at === null || marks.some((t) => pi.approved_at! > t)) out.add(STEP_NOT_READY);
    }
  }

  if (c.status === "completed" || c.completed_at !== null) {
    const requiredSteps = new Map<string, string>();
    for (const [sid, s] of steps) if (s.required) requiredSteps.set(sid, instByDef.get(sid)?.status ?? "missing");
    const accepted = acceptedTypesLatest(ctx.docsByCase.get(c.case_id) ?? []); // D-06: the latest version decides
    const m = missingForCompletion(requiredSteps, ctx.requirements[c.workflow_version_id] ?? [], accepted);
    if (m.steps.length || m.document_types.length) out.add(MISSING_REQUIRED_DOCUMENT);
  }

  // CASE_ALREADY_COMPLETE: a second completion, a reopening, or activity after the completion.
  const events = ctx.eventsByCase.get(c.case_id) ?? [];
  const completions = events.filter((e) => e.event_type === "case_completed");
  if (completions.length > 1 || events.some((e) => e.event_type === "case_reopened") ||
      (completions.length > 0 && events.some((e) => e.occurred_at > completions[0]!.occurred_at))) {
    out.add(CASE_ALREADY_COMPLETE);
  }

  // PAUSE_REASON_NOT_CONFIGURED: an interval that asks to pause for a reason the SLA rule does not list.
  const rule = ctx.slaByVersion.get(c.workflow_version_id);
  for (const w of ctx.waitingByCase.get(c.case_id) ?? []) {
    if (w.pause_requested && (rule === undefined || !rule.pause_policy.includes(w.reason_code))) out.add(PAUSE_REASON_NOT_CONFIGURED);
  }
  return out;
}

const isRow = (v: unknown): v is RawRow => typeof v === "object" && v !== null && !Array.isArray(v);
const clone = <T>(v: T): T => (v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T));
const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** Validate and parse a raw batch; raw rows of rejected records are kept as they arrived. */
export function validateBatch(raw: PipelineInputs): IngestResult {
  const contract = raw.contract ?? CONTRACT_VERSION;
  if (!ACCEPTED_INPUT_CONTRACTS.includes(contract)) {
    throw new DomainError(CONTRACT_MISMATCH, `expected contract ${CONTRACT_VERSION}`, undefined, { got: raw.contract });
  }
  const parsed = {} as { [K in EntityName]: [RawRow, EntityTypes[K]][] };
  const rejected = new Map<string, RejectedRecord>(); // key: entity + NUL + id
  const badCaseIds = new Map<string, string>();
  const dupes: RejectedRecord[] = []; // a repeated id never displaces the first row carrying it
  const rkey = (ent: string, id: string): string => `${ent}\u0000${id}`;

  const reject = (ent: EntityName, row: unknown, code: string): void => {
    const idv = isRow(row) ? row[ID_FIELD[ent]] : undefined;
    const rid = idv === undefined ? "" : idv === null ? "None" : String(idv);
    const k = rkey(ent, rid);
    if (!rejected.has(k)) rejected.set(k, { entity: ent, id: rid, status: "rejected", reason_code: code, raw_row: clone(row) });
  };

  for (const ent of ENTITIES) {
    const list: [RawRow, unknown][] = [];
    const seen = new Set<string>();
    for (const row of (raw[ent] ?? []) as readonly unknown[]) {
      let obj: unknown;
      try {
        if (!isRow(row)) throw new Error("row must be an object");
        obj = (PARSERS[ent] as (r: RawRow) => unknown)(row);
      } catch {
        reject(ent, row, MALFORMED_RECORD);
        if (ent === "cases" && isRow(row) && typeof row.case_id === "string") badCaseIds.set(row.case_id, MALFORMED_RECORD);
        continue;
      }
      const rid = (obj as Record<string, unknown>)[ID_FIELD[ent]] as string;
      if (seen.has(rid)) { dupes.push({ entity: ent, id: rid, status: "rejected", reason_code: DUPLICATE_ID, raw_row: clone(row) }); continue; }
      seen.add(rid);
      list.push([row as RawRow, obj]);
    }
    (parsed as Record<string, unknown>)[ent] = list;
  }
  const objs = {} as { [K in EntityName]: EntityTypes[K][] };
  for (const ent of ENTITIES) (objs as Record<string, unknown>)[ent] = (parsed[ent] as [RawRow, unknown][]).map(([, o]) => o);

  const versions = new Map(objs.workflow_versions.map((v) => [v.workflow_version_id, v]));
  const stepsByVersion = groupBy(objs.step_definitions, (s) => s.workflow_version_id);
  const stepVersion = new Map(objs.step_definitions.map((s) => [s.step_definition_id, s.workflow_version_id]));

  // Dependencies that name unknown steps are orphans; the rest feed Kahn's algorithm per version.
  const depsByVersion = new Map<string, Dependency[]>();
  for (const [row, d] of parsed.dependencies) {
    const v1 = stepVersion.get(d.step_definition_id), v2 = stepVersion.get(d.prerequisite_id);
    if (v1 === undefined || v1 !== v2) reject("dependencies", row, ORPHAN_REFERENCE);
    else (depsByVersion.get(v1) ?? depsByVersion.set(v1, []).get(v1)!).push(d);
  }
  const cyclic = new Set<string>();
  for (const vid of versions.keys()) {
    const ids = (stepsByVersion.get(vid) ?? []).map((s) => s.step_definition_id);
    const edges = (depsByVersion.get(vid) ?? []).map((d) => [d.step_definition_id, d.prerequisite_id] as const);
    if (topologicalOrder(ids, edges)[1].length) cyclic.add(vid);
  }
  for (const [row, o] of parsed.workflow_versions) if (cyclic.has(o.workflow_version_id)) reject("workflow_versions", row, DEPENDENCY_CYCLE);
  for (const [row, o] of parsed.step_definitions) if (cyclic.has(o.workflow_version_id)) reject("step_definitions", row, DEPENDENCY_CYCLE);
  for (const [row, o] of parsed.sla_rules) if (cyclic.has(o.workflow_version_id)) reject("sla_rules", row, DEPENDENCY_CYCLE);
  for (const [row, d] of parsed.dependencies) {
    const v = stepVersion.get(d.step_definition_id);
    if (v !== undefined && cyclic.has(v)) reject("dependencies", row, DEPENDENCY_CYCLE);
  }

  const stepCase = new Map(objs.step_instances.map((i) => [i.step_instance_id, i.case_id]));
  const assignees = new Map<string, Set<string>>();
  for (const a of objs.assignments) (assignees.get(a.step_instance_id) ?? assignees.set(a.step_instance_id, new Set()).get(a.step_instance_id)!).add(a.assignee_id);
  const ctx: Ctx = {
    versions, orgIds: new Set(objs.organizations.map((o) => o.organization_id)), cyclic, stepsByVersion, depsByVersion,
    instancesByCase: groupBy(objs.step_instances, (i) => i.case_id),
    approvalsByCase: groupBy(objs.approvals, (a) => stepCase.get(a.step_instance_id)),
    assignees, docsByCase: groupBy(objs.document_versions, (d) => d.case_id),
    eventsByCase: groupBy(objs.case_events, (e) => e.case_id), waitingByCase: groupBy(objs.waiting_intervals, (w) => w.case_id),
    slaByVersion: new Map(objs.sla_rules.map((r) => [r.workflow_version_id, r])),
    requirements: normaliseRequirements(raw.workflow_requirements),
  };

  for (const [, c] of parsed.cases) {
    const reasons = caseReasons(c, ctx);
    if (reasons.size) badCaseIds.set(c.case_id, CASE_REASONS.find((r) => reasons.has(r))!);
  }
  const knownCases = new Set(objs.cases.map((c) => c.case_id));

  const owners: [EntityName, (o: never) => string | undefined][] = [
    ["cases", (o: Case) => o.case_id], ["step_instances", (o: StepInstance) => o.case_id],
    ["assignments", (o: Assignment) => stepCase.get(o.step_instance_id)], ["document_versions", (o: DocumentVersion) => o.case_id],
    ["approvals", (o: Approval) => stepCase.get(o.step_instance_id)], ["waiting_intervals", (o: WaitingInterval) => o.case_id],
    ["case_events", (o: CaseEvent) => o.case_id],
  ] as unknown as [EntityName, (o: never) => string | undefined][];
  for (const [ent, of] of owners) {
    for (const [row, o] of parsed[ent] as [RawRow, never][]) {
      const cid = of(o);
      const bad = cid === undefined ? undefined : badCaseIds.get(cid);
      if (bad !== undefined) reject(ent, row, bad);
      else if (cid === undefined || !knownCases.has(cid)) reject(ent, row, ORPHAN_REFERENCE);
    }
  }

  // DECISION_CONFLICT: a second decision on the same step version (the earlier one stands).
  const instVersion = new Map(objs.step_instances.map((i) => [i.step_instance_id, i.version_number]));
  const first = new Set<string>();
  const sortedApprovals = [...parsed.approvals].sort((p, q) => p[1].decided_at - q[1].decided_at || cmp(p[1].approval_id, q[1].approval_id));
  for (const [row, a] of sortedApprovals) {
    if (rejected.has(rkey("approvals", a.approval_id))) continue;
    const key = `${a.step_instance_id}\u0000${a.version_number || instVersion.get(a.step_instance_id) || 1}`;
    if (first.has(key)) reject("approvals", row, DECISION_CONFLICT);
    else first.add(key);
  }

  const accepted = {} as IngestResult["accepted"], acceptedRows = {} as IngestResult["acceptedRows"];
  for (const ent of ENTITIES) {
    const a: unknown[] = [], ar: RawRow[] = [];
    for (const [row, obj] of parsed[ent] as unknown as [RawRow, Record<string, unknown>][]) {
      if (!rejected.has(rkey(ent, obj[ID_FIELD[ent]] as string))) { a.push(obj); ar.push(row); }
    }
    (accepted as Record<string, unknown>)[ent] = a;
    acceptedRows[ent] = ar;
  }
  const all = [...rejected.values(), ...dupes].sort((a, b) => cmp(a.entity, b.entity) || cmp(a.id, b.id));
  const counts = {} as IngestResult["counts"];
  const rejectedBy = new Map<string, number>();
  for (const r of all) rejectedBy.set(r.entity, (rejectedBy.get(r.entity) ?? 0) + 1);
  for (const ent of ENTITIES) counts[ent] = { accepted: accepted[ent].length, rejected: rejectedBy.get(ent) ?? 0 };
  return { accepted, acceptedRows, rejected: all, counts, requirements: ctx.requirements };
}
