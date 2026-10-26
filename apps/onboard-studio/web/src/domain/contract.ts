// Contract constants (docs/contracts.md, version v1).
export const CONTRACT_VERSION = "v1";
export const ACCEPTED_INPUT_CONTRACTS: readonly string[] = ["v1"];

/** Entities of an input batch, parents first (also the order of the ingest counts). */
export const ENTITIES = [
  "organizations", "cases", "workflow_versions", "step_definitions", "dependencies",
  "step_instances", "assignments", "document_versions", "approvals", "sla_rules",
  "calendar_intervals", "waiting_intervals", "case_events",
] as const;
export type EntityName = (typeof ENTITIES)[number];

/** D-03 step instance states and their allowed transitions. */
export const STEP_STATES = ["blocked", "ready", "in_progress", "in_review", "approved", "changes_requested"] as const;
export const STEP_TRANSITIONS: Readonly<Record<string, readonly string[]>> = {
  blocked: ["ready"],
  ready: ["in_progress", "in_review"],
  in_progress: ["in_review"],
  in_review: ["approved", "changes_requested"],
  approved: [],
  changes_requested: ["ready"],
};
export const CASE_STATES = ["open", "completed"] as const;
export const DOCUMENT_STATES = ["submitted", "accepted", "rejected"] as const;
export const DEPENDENCY_TYPES = ["mandatory", "optional"] as const;

/** Metric names in the order of expected.json. */
export const METRIC_KEYS = [
  "calendar_cycle_time_hours", "business_cycle_time_hours", "paused_time_hours",
  "paused_business_overlap_hours", "active_elapsed_hours", "sla_attainment",
  "completed_eligible_cases", "within_sla_cases", "open_backlog_at_cutoff",
  "rework_rate", "handoff_count", "step_waiting_time_hours", "first_pass_approval",
  "document_completeness", "empty_population",
] as const;
export type MetricKey = (typeof METRIC_KEYS)[number];
