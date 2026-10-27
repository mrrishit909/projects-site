// Contract constants (docs/contracts.md, version 1, decisions D-01..D-08) mirrored from domain/productsignal/contract.py.
export const CONTRACT_VERSION = 1;
export const ENTITIES = ["accounts", "users", "identity_links", "sessions", "events", "event_properties", "subscriptions",
  "experiment_versions", "assignments", "exposures", "metric_observations", "analysis_runs"] as const;
export type Entity = (typeof ENTITIES)[number];
/** Metric names in the order of expected.json["metrics"]. */
export const METRIC_KEYS = ["signup_conversion", "funnel", "activation", "retention", "feature_adoption", "experiment"] as const;
export const DAY7 = 7;
export const WEEK4: readonly [number, number] = [28, 34];
export const GRID_DAYS = [1, 7, 14, 28] as const;
export const SEGMENT_FIELDS = ["plan", "segment", "timezone"] as const;
export const DEFAULT_FEATURE = { feature: "export", eligible_plans: ["team", "business"] } as const;

export const ID_KEYS: Record<Entity, string> = {
  accounts: "account_id", users: "user_id", identity_links: "identity_link_id", sessions: "session_id", events: "event_id",
  event_properties: "property_id", subscriptions: "subscription_id", experiment_versions: "experiment_version_id",
  assignments: "assignment_id", exposures: "exposure_id", metric_observations: "observation_id", analysis_runs: "analysis_id",
};

export const ASSIGNMENT_CONFLICT = "ASSIGNMENT_CONFLICT";
export const EXPOSURE_BEFORE_ASSIGNMENT = "EXPOSURE_BEFORE_ASSIGNMENT";
export const DEPENDENT_REJECTED = "DEPENDENT_REJECTED";
export const UNKNOWN_ASSIGNMENT = "UNKNOWN_ASSIGNMENT";
export const DUPLICATE_ID = "DUPLICATE_ID";
export const UNKNOWN_ACCOUNT = "UNKNOWN_ACCOUNT";
export const UNKNOWN_USER = "UNKNOWN_USER";
export const UNKNOWN_EVENT = "UNKNOWN_EVENT";
export const UNKNOWN_EXPERIMENT_VERSION = "UNKNOWN_EXPERIMENT_VERSION";
export const UNKNOWN_UNIT = "UNKNOWN_UNIT";
export const UNKNOWN_VARIANT = "UNKNOWN_VARIANT";
export const INELIGIBLE_UNIT = "INELIGIBLE_UNIT";
export const INVALID_INTERVAL = "INVALID_INTERVAL";
export const IDENTITY_CONFLICT = "IDENTITY_CONFLICT";
export const UNSUPPORTED_UNIT_TYPE = "UNSUPPORTED_UNIT_TYPE";
export const INVALID_GROUP = "INVALID_GROUP";
