// Contract constants (docs/contracts.md, version 1, decisions D-01..D-08; mirror of domain/trustledger/contract.py).
export const CONTRACT_VERSION = 1;

/** Entities of an input batch, parents first (also the order of the ingest counts in expected.json). */
export const ENTITIES = ["owners", "datasets", "fields", "quality_rules", "rule_runs", "issues", "lineage_edges", "metric_versions",
  "definition_changes", "customer_records", "match_candidates", "merge_decisions"] as const;
export type Entity = (typeof ENTITIES)[number];

/** Metric names in the order of expected.json["metrics"] keys (D-06). */
export const METRIC_KEYS = ["completeness", "validity", "uniqueness", "relationship_integrity", "timeliness", "weighted_score",
  "critical_failures", "resolution_time", "ownership_coverage", "definition_coverage", "match_precision", "lineage_coverage"] as const;

export const ROLES = ["analyst", "steward", "admin"];
export const DIMENSIONS = ["completeness", "validity", "uniqueness", "relationship", "timeliness"] as const;
export type Dimension = (typeof DIMENSIONS)[number];
export const RULE_TYPES: readonly string[] = DIMENSIONS;
export const SEVERITIES = ["low", "medium", "high", "critical"];
export const RULE_STATUSES = ["active", "disabled"];
export const RUN_KINDS = ["scheduled", "rerun"];
export const ISSUE_STATUSES = ["open", "investigating", "closed"];
export const EVIDENCE_TYPES = ["declared", "observed", "inferred"];
export const METRIC_STATUSES = ["draft", "published", "superseded"];
export const DECISIONS = ["approve", "reject", "reverse"];

export const DEFAULT_TRIM = " \t\r\n";
export const DEFAULT_CHECKLIST = { checklist_version: "cl-1", items: ["definition", "grain", "source_fields", "owner", "refresh"] };
export const ID_KEYS: Record<Entity, string> = {
  owners: "owner_id", datasets: "dataset_id", fields: "field_id", quality_rules: "rule_id", rule_runs: "rule_run_id", issues: "issue_id",
  lineage_edges: "edge_id", metric_versions: "metric_version_id", definition_changes: "change_id", customer_records: "record_id",
  match_candidates: "candidate_id", merge_decisions: "merge_id",
};
