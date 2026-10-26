// Contract constants (docs/contracts.md, version 1, decisions D-01..D-07). Mirrors domain/serviceflow/contract.py.
export const CONTRACT_VERSION = 1;

/** Entities of an input batch, parents first (also the order of the ingest counts in expected.json). */
export const ENTITIES = ["customers", "queues", "tickets", "ticket_events", "agents", "skills", "agent_skills",
  "queue_skills", "shifts", "sla_policies", "surveys", "simulation_runs"] as const;
export type Entity = (typeof ENTITIES)[number];
/** Files the snapshot carries beyond the twelve ingest entities (data-load only, never ingested). */
export const EXTRA_ENTITIES = ["shift_breaks"] as const;

export const EVENT_TYPES = ["created", "queued", "acknowledged_bot", "service_started", "replied_human", "paused", "resumed",
  "transferred", "resolved", "reopened", "abandoned"] as const;
export const OPENERS: ReadonlySet<string> = new Set(["service_started", "resumed"]);
export const CLOSERS: ReadonlySet<string> = new Set(["resolved", "paused", "transferred", "abandoned"]);
export const PRIORITIES = ["P1", "P2", "P3"] as const;
export const PRIORITY_POLICIES = ["fifo_within_priority", "fifo"] as const;
export const EMPLOYMENT_TYPES = ["full_time", "part_time", "contractor"] as const;
export const BOT_PREFIX = "bot-";
export const DEFAULT_ABANDONABLE: readonly string[] = ["chat", "phone"];
export const GROUP_KEYS = ["queue", "priority", "agent", "channel"] as const;
export type GroupKey = (typeof GROUP_KEYS)[number];

/** Metric names in the order of expected.json. */
export const METRIC_KEYS = [
  "arrival_count", "completion_count", "arrival_rate_per_hour", "completion_rate_per_hour", "backlog",
  "first_response_minutes", "mean_first_response_minutes", "p90_first_response_minutes", "wait_minutes",
  "mean_wait_minutes", "resolution_minutes", "mean_resolution_minutes", "handling_minutes_total",
  "sla_first_response_compliance", "sla_first_response_within", "sla_first_response_eligible",
  "sla_resolution_compliance", "sla_resolution_within", "sla_resolution_eligible", "open_overdue_at_cutoff",
  "staffed_available_minutes", "staffed_shift_minutes_whole", "agent_occupancy", "abandonment_rate", "csat",
  "survey_invitation_rate", "survey_response_rate", "empty_population",
] as const;
export type MetricKey = (typeof METRIC_KEYS)[number];

// Reason codes (domain/serviceflow/errors.py).
export const AGENT_NOT_QUALIFIED = "AGENT_NOT_QUALIFIED";
export const CONCURRENCY_EXCEEDED = "CONCURRENCY_EXCEEDED";
export const BOT_AS_HUMAN_REPLY = "BOT_AS_HUMAN_REPLY";
export const TRANSFER_RESETS_ARRIVAL = "TRANSFER_RESETS_ARRIVAL";
export const UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE";
export const MALFORMED_RECORD = "MALFORMED_RECORD";
export const DUPLICATE_ID = "DUPLICATE_ID";
export const TICKET_REJECTED = "TICKET_REJECTED";
export const CONTRACT_MISMATCH = "CONTRACT_MISMATCH";
export const INVALID_WINDOW = "INVALID_WINDOW";
