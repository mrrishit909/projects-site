// Browser-memory case actions on a COPY of the accepted population (never the published snapshot).
// Every command applies the same rules as the Python domain (workflow.ts), appends rows instead of editing
// history, logs the outcome (including refusals with their reason code), and bumps `revision`.
// reset() restores the snapshot. Nothing is persisted: a reload also restores it.
import { DomainError, CASE_ALREADY_COMPLETE, DECISION_CONFLICT, ORPHAN_REFERENCE, WORKFLOW_VERSION_NOT_PUBLISHED } from "../domain/errors";
import type { IngestResult } from "../domain/ingest";
import { runOnPopulation, type PipelineResult } from "../domain/pipeline";
import { isoZ, parseTs } from "../domain/time";
import type { PausePolicyOverride, Population } from "../domain/types";
import { checkApproval, checkPauseReason, requireCompletable, requireTransition, requireUnlockable } from "../domain/workflow";

export interface SimLogEntry { seq: number; at: string; command: string; ok: boolean; code: string | null; message: string }
export interface SimState { revision: number; log: readonly SimLogEntry[] }
export type CommandResult = { ok: true; id?: string } | { ok: false; code: string; message: string };

export interface SimulationStore {
  subscribe(listener: () => void): () => void;
  getState(): SimState;
  /** The editable copy (read-only for views). */
  population(): Population;
  /** Metrics over the copy, memoised per revision. */
  compute(): PipelineResult;
  reset(): void;
  openCase(a: { organizationId: string; workflowVersionId: string; at: string }): CommandResult;
  startStep(a: { stepInstanceId: string; assigneeId: string; at: string }): CommandResult;
  reassignStep(a: { stepInstanceId: string; assigneeId: string; at: string }): CommandResult;
  submitDocument(a: { caseId: string; documentType: string; at: string }): CommandResult;
  reviewDocument(a: { documentVersionId: string; decision: "accepted" | "rejected"; at: string }): CommandResult;
  decideStep(a: { stepInstanceId: string; reviewerId: string; reviewerRole: string; decision: "approved" | "changes_requested"; at: string; versionNumber?: number }): CommandResult;
  requestPause(a: { caseId: string; reasonCode: string; at: string }): CommandResult;
  resumePause(a: { waitingIntervalId: string; at: string }): CommandResult;
  completeCase(a: { caseId: string; at: string }): CommandResult;
  reopenCase(a: { caseId: string; at: string }): CommandResult;
}

const clonePop = (p: Population): Population => structuredClone(p);

export function createSimulation(base: PipelineResult, override: PausePolicyOverride = null, cutoffs: readonly string[] = []): SimulationStore {
  let pop = clonePop(base.population);
  let state: SimState = { revision: 0, log: [] };
  let cache: { revision: number; result: PipelineResult } | null = null;
  let counter = 0;
  const listeners = new Set<() => void>();
  const ingest: IngestResult = base.ingest;
  const nextId = (kind: string): string => `sim-${kind}-${String(++counter).padStart(4, "0")}`;
  const publish = (): void => { state = { ...state, revision: state.revision + 1 }; listeners.forEach((l) => l()); };

  function run(command: string, at: string, fn: (t: number) => string | void): CommandResult {
    const seq = state.log.length + 1;
    try {
      const t = parseTs(at);
      const id = fn(t);
      state = { ...state, log: [...state.log, { seq, at, command, ok: true, code: null, message: "applied" }] };
      publish();
      return id ? { ok: true, id } : { ok: true };
    } catch (e) {
      const code = e instanceof DomainError ? e.code : "INVALID_COMMAND";
      const message = e instanceof Error ? e.message : String(e);
      state = { ...state, log: [...state.log, { seq, at, command, ok: false, code, message }] };
      publish();
      return { ok: false, code, message };
    }
  }

  const caseOf = (id: string) => {
    const c = pop.cases.find((x) => x.case_id === id);
    if (!c) throw new DomainError(ORPHAN_REFERENCE, `unknown case ${id}`);
    return c;
  };
  const stepOf = (id: string) => {
    const s = pop.step_instances.find((x) => x.step_instance_id === id);
    if (!s) throw new DomainError(ORPHAN_REFERENCE, `unknown step instance ${id}`);
    return s;
  };
  const guardOpen = (caseId: string): void => {
    if (caseOf(caseId).completed_at !== null) throw new DomainError(CASE_ALREADY_COMPLETE, "a completed case cannot change; open a linked correction case instead");
  };
  const statusByDef = (caseId: string): Map<string, string> =>
    new Map(pop.step_instances.filter((s) => s.case_id === caseId).map((s) => [s.step_definition_id, s.status]));
  const event = (caseId: string, type: string, actor: string, t: number): void => {
    pop.case_events.push({ event_id: nextId("ev"), case_id: caseId, event_type: type, actor_id: actor, occurred_at: t });
  };
  const unlock = (caseId: string, wfv: string, t: number): void => {
    const deps = pop.dependencies.filter((d) => pop.step_definitions.some((s) => s.step_definition_id === d.step_definition_id && s.workflow_version_id === wfv));
    const status = statusByDef(caseId);
    for (const si of pop.step_instances.filter((s) => s.case_id === caseId && s.status === "blocked")) {
      try { requireUnlockable(si.step_definition_id, deps, status); } catch { continue; }
      si.status = "ready"; si.ready_at = t;
    }
  };
  const assign = (si: { step_instance_id: string }, assignee: string, t: number): void => {
    for (const a of pop.assignments) if (a.step_instance_id === si.step_instance_id && a.ended_at === null) a.ended_at = t; // closed, never deleted
    pop.assignments.push({ assignment_id: nextId("asg"), step_instance_id: si.step_instance_id, assignee_id: assignee, assigned_at: t, ended_at: null });
  };

  const store: SimulationStore = {
    subscribe(l) { listeners.add(l); return () => void listeners.delete(l); },
    getState: () => state,
    population: () => pop,
    compute() {
      if (!cache || cache.revision !== state.revision) cache = { revision: state.revision, result: runOnPopulation(ingest, pop, override, cutoffs) };
      return cache.result;
    },
    reset() { pop = clonePop(base.population); counter = 0; cache = null; state = { revision: state.revision + 1, log: [] }; listeners.forEach((l) => l()); },

    openCase({ organizationId, workflowVersionId, at }) {
      return run(`open case (${organizationId}, ${workflowVersionId})`, at, (t) => {
        const wv = pop.workflow_versions.find((v) => v.workflow_version_id === workflowVersionId);
        if (!wv || !pop.organizations.some((o) => o.organization_id === organizationId)) throw new DomainError(ORPHAN_REFERENCE, "unknown organization or workflow version");
        if (wv.published_at === null || wv.published_at > t) throw new DomainError(WORKFLOW_VERSION_NOT_PUBLISHED, "the workflow version is not published at that instant");
        const caseId = nextId("case");
        pop.cases.push({ case_id: caseId, organization_id: organizationId, workflow_version_id: workflowVersionId, status: "open", opened_at: t, completed_at: null });
        const deps = pop.dependencies;
        for (const sd of pop.step_definitions.filter((s) => s.workflow_version_id === workflowVersionId).sort((a, b) => a.sequence - b.sequence)) {
          const free = !deps.some((d) => d.step_definition_id === sd.step_definition_id && d.dependency_type === "mandatory");
          pop.step_instances.push({ step_instance_id: nextId("si"), case_id: caseId, step_definition_id: sd.step_definition_id, status: free ? "ready" : "blocked", version_number: 1, ready_at: free ? t : null, started_at: null, approved_at: null });
        }
        event(caseId, "case_opened", "sim", t);
        return caseId;
      });
    },

    startStep({ stepInstanceId, assigneeId, at }) {
      return run(`start step ${stepInstanceId}`, at, (t) => {
        const si = stepOf(stepInstanceId);
        guardOpen(si.case_id);
        requireTransition(si.status, "in_progress");
        si.status = "in_progress"; si.started_at = t;
        assign(si, assigneeId, t);
        event(si.case_id, "step_started", assigneeId, t);
      });
    },

    reassignStep({ stepInstanceId, assigneeId, at }) {
      return run(`reassign step ${stepInstanceId}`, at, (t) => {
        const si = stepOf(stepInstanceId);
        guardOpen(si.case_id);
        assign(si, assigneeId, t);
        event(si.case_id, "step_reassigned", assigneeId, t);
      });
    },

    submitDocument({ caseId, documentType, at }) {
      return run(`submit ${documentType} for ${caseId}`, at, (t) => {
        guardOpen(caseId);
        const v = pop.document_versions.filter((d) => d.case_id === caseId && d.document_type === documentType).reduce((m, d) => Math.max(m, d.version_number), 0) + 1;
        const id = nextId("dv");
        pop.document_versions.push({ document_version_id: id, case_id: caseId, document_type: documentType, version_number: v, content_hash: `sha256:${"0".repeat(63)}1`, review_status: "submitted", submitted_at: t, reviewed_at: null });
        event(caseId, "document_submitted", "sim", t);
        return id; // append-only: a resubmission adds a row and leaves the prior row intact
      });
    },

    reviewDocument({ documentVersionId, decision, at }) {
      return run(`review ${documentVersionId} ${decision}`, at, (t) => {
        const d = pop.document_versions.find((x) => x.document_version_id === documentVersionId);
        if (!d) throw new DomainError(ORPHAN_REFERENCE, `unknown document version ${documentVersionId}`);
        guardOpen(d.case_id);
        if (d.review_status !== "submitted") throw new DomainError(DECISION_CONFLICT, "this document version already has a review");
        d.review_status = decision; d.reviewed_at = t;
        event(d.case_id, decision === "accepted" ? "document_accepted" : "document_rejected", "sim", t);
      });
    },

    decideStep({ stepInstanceId, reviewerId, reviewerRole, decision, at, versionNumber }) {
      return run(`${decision} step ${stepInstanceId}`, at, (t) => {
        const si = stepOf(stepInstanceId);
        const c = caseOf(si.case_id);
        guardOpen(si.case_id);
        const sd = pop.step_definitions.find((s) => s.step_definition_id === si.step_definition_id)!;
        const version = versionNumber ?? si.version_number;
        if (pop.approvals.some((a) => a.step_instance_id === si.step_instance_id && (a.version_number ?? si.version_number) === version)) {
          throw new DomainError(DECISION_CONFLICT, "a decision already exists for this step version; send the new version number");
        }
        if (si.status === "in_progress") { requireTransition("in_progress", "in_review"); si.status = "in_review"; }
        checkApproval(reviewerId, reviewerRole, sd.role_key, pop.assignments.filter((a) => a.step_instance_id === si.step_instance_id).map((a) => a.assignee_id));
        requireTransition(si.status, decision);
        pop.approvals.push({ approval_id: nextId("apr"), step_instance_id: si.step_instance_id, reviewer_id: reviewerId, decision, decided_at: t, reason: null, version_number: version });
        if (decision === "approved") { si.status = "approved"; si.approved_at = t; unlock(c.case_id, c.workflow_version_id, t); }
        else { si.status = "ready"; si.version_number += 1; si.ready_at = t; si.started_at = null; } // changes_requested -> ready (D-03)
        event(c.case_id, decision === "approved" ? "step_approved" : "changes_requested", reviewerId, t);
      });
    },

    requestPause({ caseId, reasonCode, at }) {
      return run(`pause ${caseId} (${reasonCode})`, at, (t) => {
        const c = caseOf(caseId);
        guardOpen(caseId);
        const rule = pop.sla_rules.find((r) => r.workflow_version_id === c.workflow_version_id);
        const policy = override === null || rule === undefined ? rule?.pause_policy ?? [] : Array.isArray(override) ? override : (override as Record<string, readonly string[]>)[rule.sla_rule_id] ?? rule.pause_policy;
        checkPauseReason(reasonCode, policy);
        const id = nextId("wi");
        pop.waiting_intervals.push({ waiting_interval_id: id, case_id: caseId, reason_code: reasonCode, starts_at: t, ends_at: null, pause_requested: true });
        event(caseId, "waiting_started", "sim", t);
        return id;
      });
    },

    resumePause({ waitingIntervalId, at }) {
      return run(`resume ${waitingIntervalId}`, at, (t) => {
        const w = pop.waiting_intervals.find((x) => x.waiting_interval_id === waitingIntervalId);
        if (!w) throw new DomainError(ORPHAN_REFERENCE, `unknown waiting interval ${waitingIntervalId}`);
        if (w.ends_at !== null) throw new DomainError(DECISION_CONFLICT, "this waiting interval has already ended");
        w.ends_at = Math.max(t, w.starts_at);
        event(w.case_id, "waiting_ended", "sim", t);
      });
    },

    completeCase({ caseId, at }) {
      return run(`complete ${caseId}`, at, (t) => {
        const c = caseOf(caseId);
        guardOpen(caseId);
        const steps = new Map<string, string>();
        const status = statusByDef(caseId);
        for (const sd of pop.step_definitions.filter((s) => s.workflow_version_id === c.workflow_version_id && s.required)) steps.set(sd.step_definition_id, status.get(sd.step_definition_id) ?? "missing");
        const accepted = pop.document_versions.filter((d) => d.case_id === caseId && d.review_status === "accepted").map((d) => d.document_type);
        requireCompletable(steps, pop.requirements[c.workflow_version_id] ?? [], accepted);
        c.status = "completed"; c.completed_at = Math.max(t, c.opened_at);
        event(caseId, "case_completed", "sim", t);
      });
    },

    reopenCase({ caseId, at }) {
      return run(`reopen ${caseId}`, at, () => {
        caseOf(caseId);
        throw new DomainError(CASE_ALREADY_COMPLETE, "a completed case cannot be reopened; a correction opens a linked new case");
      });
    },
  };
  return store;
}

export const nowIso = (): string => isoZ(Math.floor(Date.now() / 1000) * 1000);
