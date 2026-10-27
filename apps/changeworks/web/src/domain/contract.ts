// Contract constants (docs/contracts.md D-01..D-05; the fixture's decisions D-P9-01..24 are the binding form). Mirrors domain/changeworks/contract.py.
export const CONTRACT_VERSION = 1;

/** Entities in import order: parents first (D-P9-01). */
export const ENTITIES = ["initiatives", "process_baselines", "assumption_versions", "resources", "scenario_versions", "cost_items",
  "benefit_items", "dependencies", "stakeholder_groups", "impact_mappings", "resource_allocations",
  "readiness_assessments", "adoption_observations", "training_completions", "benefit_observations", "risk_items",
  "forecast_versions"] as const;
export type Entity = (typeof ENTITIES)[number];

export const ID_FIELD: Record<Entity, string> = {
  initiatives: "initiative_id", process_baselines: "baseline_id", assumption_versions: "assumption_id", resources: "resource_id",
  scenario_versions: "scenario_id", cost_items: "cost_id", benefit_items: "benefit_id", dependencies: "dependency_id",
  stakeholder_groups: "group_id", impact_mappings: "mapping_id", resource_allocations: "allocation_id", readiness_assessments: "assessment_id",
  adoption_observations: "observation_id", training_completions: "training_id", benefit_observations: "benefit_observation_id",
  risk_items: "risk_id", forecast_versions: "forecast_id",
};
/** [field, parent entity, code when unknown, nullable, is_list] */
export type ForeignKey = readonly [string, Entity, string, boolean, boolean];
export const FOREIGN_KEYS: Partial<Record<Entity, readonly ForeignKey[]>> = {
  process_baselines: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
  assumption_versions: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", true, false]],
  scenario_versions: [["initiative_ids", "initiatives", "UNKNOWN_INITIATIVE", false, true],
    ["pinned_assumption_ids", "assumption_versions", "UNKNOWN_ASSUMPTION", false, true],
    ["rate_conversion_assumption_id", "assumption_versions", "UNKNOWN_ASSUMPTION", true, false]],
  cost_items: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
  benefit_items: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
  dependencies: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false], ["prerequisite_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
  impact_mappings: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false], ["group_id", "stakeholder_groups", "UNKNOWN_GROUP", false, false]],
  resource_allocations: [["resource_id", "resources", "UNKNOWN_RESOURCE", false, false], ["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
  readiness_assessments: [["group_id", "stakeholder_groups", "UNKNOWN_GROUP", false, false]],
  adoption_observations: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
  training_completions: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
  benefit_observations: [["benefit_id", "benefit_items", "UNKNOWN_BENEFIT", false, false]],
  risk_items: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
  forecast_versions: [["initiative_id", "initiatives", "UNKNOWN_INITIATIVE", false, false]],
};
export const INITIATIVE_STATUSES = ["candidate", "assessed", "in_delivery", "adopted", "closed"] as const; // no "funded" (P09-FLOW-07, D-P9-19)
export const SCENARIO_STATUSES = ["draft", "proposed"] as const;
export const BENEFIT_TYPES = ["cash", "avoided_cost", "revenue", "capacity"] as const;
export type BenefitType = (typeof BENEFIT_TYPES)[number];
export const MONEY_TYPES = ["cash", "avoided_cost", "revenue"] as const;
export const COST_TYPES = ["one_time", "recurring"] as const;
export const COST_BASES = ["planned", "actual"] as const;
export const DEPENDENCY_TYPES = ["finish_to_start", "start_to_start"] as const;
export const IMPACT_LEVELS = ["low", "medium", "high"] as const;
export const DIMENSIONS = ["awareness", "desire", "knowledge", "ability", "reinforcement"] as const; // ADKAR-inspired (D-03)
export const BASES = ["annual", "monthly"] as const;
export const CONVERSION_NAME = "monthly_rate_conversion";
export const CAPACITY_RATE_NAME = "capacity_hourly_rate";
export const RAMP_NAME = "adoption_ramp";
export const TARGET_NAME = "target_minutes_per_case";
export const MAX_HORIZON = 600;
export const MAX_PERIOD = 100_000;

/** A record as the contract sees it: JSON values by field name. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any>;

export class DomainError extends Error {
  constructor(readonly code: string, readonly detail: string, readonly details: Row = {}) { super(`${code}: ${detail}`); }
}
