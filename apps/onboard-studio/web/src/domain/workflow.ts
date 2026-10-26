// Workflow rules (D-02, D-03): publishing (Kahn), step readiness, approval, pause and completion checks.
// Mirrors domain/onboard_studio/workflow.py.
import { STEP_TRANSITIONS } from "./contract";
import {
  DEPENDENCY_CYCLE, DomainError, INVALID_TRANSITION, MISSING_REQUIRED_DOCUMENT, ORPHAN_REFERENCE,
  PAUSE_REASON_NOT_CONFIGURED, ROLE_MISMATCH, SELF_APPROVAL, STEP_NOT_READY,
} from "./errors";

/** (step, prerequisite) */
export type Edge = readonly [string, string];
const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/**
 * Kahn's algorithm. Returns [order, leftover]; leftover is non-empty iff there is a cycle.
 * Ties are broken by step id so the order is stable.
 */
export function topologicalOrder(stepIds: Iterable<string>, edges: Iterable<Edge>): [string[], string[]] {
  const ids = [...new Set(stepIds)].sort(cmp);
  const indegree = new Map<string, number>(ids.map((s) => [s, 0]));
  const followers = new Map<string, string[]>(ids.map((s) => [s, []]));
  const uniq = new Map<string, Edge>();
  for (const e of edges) uniq.set(`${e[0]}\u0000${e[1]}`, e);
  for (const [step, prereq] of [...uniq.values()].sort((a, b) => cmp(a[0], b[0]) || cmp(a[1], b[1]))) {
    indegree.set(step, (indegree.get(step) ?? 0) + 1);
    followers.get(prereq)!.push(step);
  }
  const queue = ids.filter((s) => indegree.get(s) === 0);
  const order: string[] = [];
  for (let head = 0; head < queue.length; head++) {
    const node = queue[head]!;
    order.push(node);
    for (const nxt of [...followers.get(node)!].sort(cmp)) {
      const d = indegree.get(nxt)! - 1;
      indegree.set(nxt, d);
      if (d === 0) queue.push(nxt);
    }
  }
  return [order, ids.filter((s) => indegree.get(s)! > 0)];
}

/** Reject a version whose dependencies contain a cycle (DEPENDENCY_CYCLE); returns the topological order. */
export function checkPublishable(stepIds: Iterable<string>, edges: Iterable<Edge>): string[] {
  const ids = new Set(stepIds);
  const list = [...edges];
  for (const [step, prereq] of list) {
    if (!ids.has(step) || !ids.has(prereq)) {
      throw new DomainError(ORPHAN_REFERENCE, "a dependency names a step that is not in the version", undefined, { step, prerequisite: prereq });
    }
  }
  const [order, leftover] = topologicalOrder(ids, list);
  if (leftover.length) throw new DomainError(DEPENDENCY_CYCLE, "the workflow's dependencies contain a cycle", "input.dependencies", { steps: leftover });
  return order;
}

interface StepRow { step_definition_id: string; step_name: string; required: boolean; role_key: string; sequence: number }
interface DepRow { dependency_id: string; step_definition_id: string; prerequisite_id: string; dependency_type: string }

/** JSON as Python's json.dumps(sort_keys=True, separators=(",", ":")) with ensure_ascii. */
export function compactJson(v: unknown): string {
  if (v === null || typeof v === "boolean" || typeof v === "number") return JSON.stringify(v);
  if (typeof v === "string") return JSON.stringify(v).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
  if (Array.isArray(v)) return `[${v.map(compactJson).join(",")}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o).sort().map((k) => `${compactJson(k)}:${compactJson(o[k])}`).join(",")}}`;
}

/** D-05: the compact sorted-key JSON whose sha256 is the definition_hash. */
export function definitionPayload(steps: readonly StepRow[], dependencies: readonly DepRow[]): string {
  const rows = [...steps].sort((a, b) => a.sequence - b.sequence);
  const ids = new Set(rows.map((s) => s.step_definition_id));
  return compactJson({
    steps: rows.map((s) => [s.step_definition_id, s.step_name, s.required, s.role_key, s.sequence]),
    dependencies: [...dependencies].sort((a, b) => cmp(a.dependency_id, b.dependency_id))
      .filter((d) => ids.has(d.step_definition_id))
      .map((d) => [d.step_definition_id, d.prerequisite_id, d.dependency_type]),
  });
}

/** sha256 hex of the definition payload (Web Crypto; available in browsers and Node 20+). */
export async function definitionHash(steps: readonly StepRow[], dependencies: readonly DepRow[]): Promise<string> {
  const bytes = new TextEncoder().encode(definitionPayload(steps, dependencies));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function mandatoryPrerequisites(stepDefinitionId: string, dependencies: Iterable<DepRow>): string[] {
  const out: string[] = [];
  for (const d of dependencies) if (d.step_definition_id === stepDefinitionId && d.dependency_type === "mandatory") out.push(d.prerequisite_id);
  return out.sort(cmp);
}

/** Mandatory prerequisites that are not approved (a prerequisite without an instance is not approved). */
export const unapprovedPrerequisites = (stepDefinitionId: string, dependencies: Iterable<DepRow>, statusByStep: ReadonlyMap<string, string>): string[] =>
  mandatoryPrerequisites(stepDefinitionId, dependencies).filter((p) => statusByStep.get(p) !== "approved");

/** D-03: a step is ready only when every mandatory prerequisite is approved. */
export const stepIsReady = (stepDefinitionId: string, dependencies: Iterable<DepRow>, statusByStep: ReadonlyMap<string, string>): boolean =>
  unapprovedPrerequisites(stepDefinitionId, dependencies, statusByStep).length === 0;

export function requireUnlockable(stepDefinitionId: string, dependencies: Iterable<DepRow>, statusByStep: ReadonlyMap<string, string>): void {
  const missing = unapprovedPrerequisites(stepDefinitionId, dependencies, statusByStep);
  if (missing.length) throw new DomainError(STEP_NOT_READY, "mandatory prerequisites are not approved", "input.step_instance_id", { unapproved: missing });
}

export function requireTransition(current: string, next: string): void {
  if (!(STEP_TRANSITIONS[current] ?? []).includes(next)) {
    throw new DomainError(INVALID_TRANSITION, `step cannot go from ${current} to ${next}`, undefined, { from: current, to: next });
  }
}

/** The reviewer was never an assignee of the step (SELF_APPROVAL) and has the step's role, or is admin (ROLE_MISMATCH). */
export function checkApproval(reviewerId: string, reviewerRole: string, roleKey: string, assignees: Iterable<string>): void {
  if (new Set(assignees).has(reviewerId)) {
    throw new DomainError(SELF_APPROVAL, "a reviewer cannot approve work they were assigned", "input.step_instance_id", { reviewer_id: reviewerId });
  }
  if (reviewerRole !== roleKey && reviewerRole !== "admin") {
    throw new DomainError(ROLE_MISMATCH, `the step needs role '${roleKey}'`, "input.step_instance_id", { role: reviewerRole, role_key: roleKey });
  }
}

/** Only a reason configured in the SLA rule's pause_policy may pause. */
export function checkPauseReason(reasonCode: string, pausePolicy: Iterable<string>): void {
  const configured = new Set(pausePolicy);
  if (!configured.has(reasonCode)) {
    throw new DomainError(PAUSE_REASON_NOT_CONFIGURED, `'${reasonCode}' is not a configured pause reason`, "input.reason_code", { configured: [...configured].sort(cmp) });
  }
}

/** What stops a completion: required steps not approved and required document types not accepted. */
export function missingForCompletion(requiredSteps: ReadonlyMap<string, string>, requiredTypes: Iterable<string>, acceptedTypes: Iterable<string>): { steps: string[]; document_types: string[] } {
  const accepted = new Set(acceptedTypes);
  return {
    steps: [...requiredSteps].filter(([, st]) => st !== "approved").map(([s]) => s).sort(cmp),
    document_types: [...new Set(requiredTypes)].filter((t) => !accepted.has(t)).sort(cmp),
  };
}

/** D-06 / Q-04: types whose LATEST version (highest version_number) has the effective status accepted. */
export function acceptedTypesLatest(documents: Iterable<{ document_type: string; version_number: number; review_status: string }>): Set<string> {
  const latest = new Map<string, { version_number: number; review_status: string }>();
  for (const d of documents) {
    const cur = latest.get(d.document_type);
    if (cur === undefined || d.version_number > cur.version_number) latest.set(d.document_type, d);
  }
  return new Set([...latest].filter(([, d]) => d.review_status === "accepted").map(([t]) => t));
}

export function requireCompletable(requiredSteps: ReadonlyMap<string, string>, requiredTypes: Iterable<string>, acceptedTypes: Iterable<string>): void {
  const m = missingForCompletion(requiredSteps, requiredTypes, acceptedTypes);
  if (m.steps.length || m.document_types.length) {
    throw new DomainError(MISSING_REQUIRED_DOCUMENT, "required steps or documents are missing for completion", "input.case_id", m);
  }
}
