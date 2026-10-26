// Typed records for the 13 input entities, the population the metrics run over, and the snapshot shapes.
// Instants are UTC epoch milliseconds; `iso` helpers in time.ts format them.
import type { EntityName } from "./contract";

export interface Organization { organization_id: string; organization_name: string; segment: string; region: string; created_at: number }
export interface WorkflowVersion { workflow_version_id: string; template_id: string; version_number: number; published_at: number | null; definition_hash: string | null }
export interface StepDefinition { step_definition_id: string; workflow_version_id: string; step_name: string; required: boolean; role_key: string; sequence: number }
export interface Dependency { dependency_id: string; step_definition_id: string; prerequisite_id: string; dependency_type: string; created_at: number | null }
export interface SlaRule { sla_rule_id: string; workflow_version_id: string; business_minutes: number; pause_policy: readonly string[]; calendar_id: string }
export interface CalendarInterval { calendar_interval_id: string; calendar_id: string; starts_at: number; ends_at: number; timezone: string; kind: "working" | "holiday" }
export interface Case { case_id: string; organization_id: string; workflow_version_id: string; status: "open" | "completed"; opened_at: number; completed_at: number | null }
export interface StepInstance { step_instance_id: string; case_id: string; step_definition_id: string; status: string; version_number: number; ready_at: number | null; started_at: number | null; approved_at: number | null }
export interface Assignment { assignment_id: string; step_instance_id: string; assignee_id: string; assigned_at: number; ended_at: number | null }
export interface DocumentVersion { document_version_id: string; case_id: string; document_type: string; version_number: number; content_hash: string; review_status: string; submitted_at: number; reviewed_at: number | null }
export interface Approval { approval_id: string; step_instance_id: string; reviewer_id: string; decision: string; decided_at: number; reason: string | null; version_number: number | null }
export interface WaitingInterval { waiting_interval_id: string; case_id: string; reason_code: string; starts_at: number; ends_at: number | null; pause_requested: boolean }
export interface CaseEvent { event_id: string; case_id: string; event_type: string; actor_id: string; occurred_at: number }

export interface EntityTypes {
  organizations: Organization; cases: Case; workflow_versions: WorkflowVersion; step_definitions: StepDefinition;
  dependencies: Dependency; step_instances: StepInstance; assignments: Assignment; document_versions: DocumentVersion;
  approvals: Approval; sla_rules: SlaRule; calendar_intervals: CalendarInterval; waiting_intervals: WaitingInterval;
  case_events: CaseEvent;
}

/** Required document types per workflow version (D-05), normalised. */
export type Requirements = Readonly<Record<string, readonly string[]>>;

/** Parsed records of one dataset (accepted rows) plus the required document types. */
export type Population = { [K in EntityName]: EntityTypes[K][] } & { requirements: Requirements };

export type RawRow = Record<string, unknown>;
export type PausePolicyOverride = readonly string[] | Readonly<Record<string, readonly string[]>> | null;

/** An input batch. Entity arrays are raw JSON rows; `states` maps a state name to per-rule pause policies. */
export interface PipelineInputs {
  contract?: string;
  fixture_id?: string;
  cutoffs?: readonly string[];
  states?: Record<string, Record<string, { pause_policy: readonly string[] }>>;
  workflow_requirements?: Record<string, { required_document_types: readonly string[] } | readonly string[]>;
  organizations?: readonly unknown[]; cases?: readonly unknown[]; workflow_versions?: readonly unknown[];
  step_definitions?: readonly unknown[]; dependencies?: readonly unknown[]; step_instances?: readonly unknown[];
  assignments?: readonly unknown[]; document_versions?: readonly unknown[]; approvals?: readonly unknown[];
  sla_rules?: readonly unknown[]; calendar_intervals?: readonly unknown[]; waiting_intervals?: readonly unknown[];
  case_events?: readonly unknown[];
}

export interface RejectedRecord { entity: string; id: string; status: "rejected"; reason_code: string; raw_row: unknown }
export interface EntityCount { accepted: number; rejected: number }

export interface Metrics {
  calendar_cycle_time_hours: string | null;
  business_cycle_time_hours: string | null;
  paused_time_hours: string | null;
  paused_business_overlap_hours: string | null;
  active_elapsed_hours: string | null;
  sla_attainment: string | null;
  completed_eligible_cases: number;
  within_sla_cases: number;
  open_backlog_at_cutoff: Record<string, number>;
  rework_rate: string | null;
  handoff_count: number;
  step_waiting_time_hours: Record<string, string | null>;
  first_pass_approval: string | null;
  document_completeness: string | null;
  empty_population: boolean;
}

export interface Flag { waiting_interval_id?: string; case_id: string; flag: string }

/** Per completed eligible case: the exact figures behind the means (hours, 4 dp). */
export interface CaseFigures {
  case_id: string; calendar_hours: string; business_hours: string; paused_hours: string;
  paused_business_overlap_hours: string; active_hours: string; within_sla: boolean; sla_minutes: number;
}

/** Manifest of a published snapshot (public/data/manifest.json). */
export interface Manifest {
  contract_version: string; dataset_hash: string; dataset_version: string; generated_at: string;
  row_counts: Record<string, number>; code_sha?: string; fixture_id?: string;
  designed_relationships?: string[]; injection_manifest?: string; generator?: unknown;
  /** Golden snapshot only: the fixture's backlog cutoffs and named pause states. */
  cutoffs?: string[]; states?: PipelineInputs["states"];
}
export interface EntityFile<T> { entity: string; dataset_version: string; rows: T[] }
export type Window = readonly [number | null, number | null];
