import type { Entity, GroupKey } from "./contract";

// Typed records. Instants are integer UTC epoch seconds; field names are the fixture's.
export interface Customer { customer_id: string; segment: string; timezone: string; created_at: number; synthetic: boolean }
export interface Queue { queue_id: string; queue_name: string; priority_policy: string; calendar_id: string; active: boolean }
export interface Ticket { ticket_id: string; customer_id: string; queue_id: string; priority: string; created_at: number; channel: string }
export interface TicketEvent { event_id: string; ticket_id: string; event_type: string; occurred_at: number; actor_id: string | null; queue_id: string | null; agent_id: string | null }
export interface Agent { agent_id: string; agent_name: string; timezone: string; employment_type: string; active: boolean; max_concurrent: number }
export interface Skill { skill_id: string; skill_name: string; description: string | null; active: boolean; created_at: number }
export interface AgentSkill { agent_skill_id: string; agent_id: string; skill_id: string; proficiency: number; effective_from: number }
export interface QueueSkill { queue_id: string; skill_id: string }
export interface Shift { shift_id: string; agent_id: string; starts_at: number; ends_at: number; break_minutes: number }
export interface SlaPolicy { sla_policy_id: string; priority: string; first_response_minutes: number; resolution_minutes: number; calendar_id: string }
export interface Survey { survey_id: string; ticket_id: string; response_at: number | null; score: number | null; invited_at: number | null }
export interface SimulationRun { simulation_id: string; seed: number; warmup_minutes: number; policy_version: string; horizon_minutes: number; config: Record<string, unknown> }
export interface ShiftBreak { break_id: string; shift_id: string; agent_id: string; starts_at: string; ends_at: string }

export interface Population {
  customers: Customer[]; queues: Queue[]; tickets: Ticket[]; ticket_events: TicketEvent[]; agents: Agent[]; skills: Skill[];
  agent_skills: AgentSkill[]; queue_skills: QueueSkill[]; shifts: Shift[]; sla_policies: SlaPolicy[]; surveys: Survey[];
  simulation_runs: SimulationRun[];
}
export interface RejectedRecord { entity: Entity; id: string; reason_code: string; raw_row: unknown; status: "rejected" }
export interface IngestResult {
  accepted: Population;
  rejected: RejectedRecord[];
  counts: Record<Entity, { accepted: number; rejected: number }>;
}

export type RawRows = Record<string, unknown>;
/** A raw batch: the twelve entities' rows plus the window and backlog cutoffs (ISO strings). */
export interface PipelineInputs {
  contract_version: number | string;
  window_start: string;
  window_end: string;
  backlog_cutoffs?: string[];
  abandonable_channels?: string[];
  [entity: string]: unknown;
}

export type Window = readonly [number, number];
export type Metrics = {
  arrival_count: number; completion_count: number; arrival_rate_per_hour: string; completion_rate_per_hour: string;
  backlog: Record<string, number>;
  first_response_minutes: Record<string, string>; mean_first_response_minutes: string | null; p90_first_response_minutes: string | null;
  wait_minutes: Record<string, string>; mean_wait_minutes: string | null;
  resolution_minutes: Record<string, string>; mean_resolution_minutes: string | null;
  handling_minutes_total: string;
  sla_first_response_compliance: string | null; sla_first_response_within: number; sla_first_response_eligible: number;
  sla_resolution_compliance: string | null; sla_resolution_within: number; sla_resolution_eligible: number;
  open_overdue_at_cutoff: number;
  staffed_available_minutes: string | null; staffed_shift_minutes_whole: string | null; agent_occupancy: string | null;
  abandonment_rate: string | null; csat: string | null; survey_invitation_rate: string | null; survey_response_rate: string | null;
  empty_population: boolean;
};
export type GroupMetrics = Record<string, Metrics>;
export interface Disclosures {
  reopened_tickets: number; reopen_events: number; reopened_among_completions: number; reopened_basis: string; transferred_tickets: number; arrivals_without_human_reply: number;
  bot_events_ignored_for_first_response: number; open_overdue_at_window_end: number; p90_method: string;
  csat: { completed_tickets: number; invited: number; valid_responses: number; nonresponse: number; note: string };
  staffed_break_rule: string;
}
export type { GroupKey };

/** R4-13: the holdout uplift is a chosen realisation of a fixed series of attempts; the generator records which one and what it discarded. */
export interface ArrivalRealisation {
  rule: string; designed_uplift_percent: number; tolerance_points: number; attempt_index: number | null;
  discarded_uplift_percent: number[]; chosen_uplift_percent: number | null; noise_sd_points: number; note: string;
}

/** The snapshot manifest as the site shows it. */
export interface Manifest {
  contract_version: string; dataset_version: string; dataset_hash: string; generated_at: string;
  row_counts: Record<string, number>;
  code_sha?: string;
  designed_relationships?: string[];
  generator?: { parameters?: { as_of?: string; window?: [string, string]; training_weeks?: [number, number]; weeks?: number; arrival_realisation?: ArrivalRealisation; dst_weekend?: { saturday: string; sunday: string; transition_utc: string; zone: string } } };
  stats?: Record<string, unknown>;
  // the golden fixture's own manifest
  window_start?: string; window_end?: string; backlog_cutoffs?: string[]; abandonable_channels?: string[]; fixture_id?: string;
}
