// Contract constants (docs/contracts.md, the golden fixture): the entities in import order, their ids and foreign keys, the registered features.
export const CONTRACT_VERSION = 1;
export const ENTITIES = ["accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows",
  "labels", "training_runs", "predictions", "intervention_scenarios", "outreach_events", "feature_registry", "split_assignments", "scoring_publications"] as const;
export type Entity = (typeof ENTITIES)[number];
export const ID: Record<Entity, string> = {
  accounts: "account_id", subscription_events: "subscription_event_id", billing_events: "billing_event_id", usage_events: "usage_event_id",
  support_events: "support_event_id", prediction_cutoffs: "cutoff_id", feature_rows: "feature_row_id", labels: "label_id", training_runs: "training_run_id",
  predictions: "prediction_id", intervention_scenarios: "scenario_id", outreach_events: "outreach_event_id", feature_registry: "feature_name",
  split_assignments: "assignment_id", scoring_publications: "publication_id",
};
export const EVENTS = ["subscription_events", "billing_events", "usage_events", "support_events"] as const;
export type EventEntity = (typeof EVENTS)[number];
export const FK: Partial<Record<Entity, [string, Entity, string][]>> = {
  ...Object.fromEntries(EVENTS.map((e) => [e, [["account_id", "accounts", "UNKNOWN_ACCOUNT"]]])),
  prediction_cutoffs: [["account_id", "accounts", "UNKNOWN_ACCOUNT"]],
  feature_rows: [["cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF"]],
  labels: [["cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF"]],
  predictions: [["training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN"], ["cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF"]],
  outreach_events: [["account_id", "accounts", "UNKNOWN_ACCOUNT"], ["scenario_id", "intervention_scenarios", "UNKNOWN_SCENARIO"]],
  split_assignments: [["training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN"], ["cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF"]],
  scoring_publications: [["training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN"]],
};
/** The registered features of feature version fv-1, in column order. */
export const FEATURES = ["usage_events_30d", "days_since_last_usage", "high_severity_support_90d", "billing_total_90d"] as const;
export const CAL_BINS = 10;
export const MODELS = ["random_baseline", "business_rule", "logistic_regression"] as const;
export type ModelName = (typeof MODELS)[number];
export const MODEL_LABEL: Record<ModelName, string> = { random_baseline: "Random baseline", business_rule: "Business rule", logistic_regression: "Logistic regression (Platt)" };
