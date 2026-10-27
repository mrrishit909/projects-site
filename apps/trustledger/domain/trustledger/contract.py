"""Contract constants (docs/contracts.md, version 1, decisions D-01..D-06)."""
from __future__ import annotations

CONTRACT_VERSION = 1

#: Entities of an input batch, parents first (also the order of the ingest counts in expected.json).
ENTITIES = ("owners", "datasets", "fields", "quality_rules", "rule_runs", "issues", "lineage_edges", "metric_versions",
            "definition_changes", "customer_records", "match_candidates", "merge_decisions")

#: Metric names in the order of expected.json["metrics"] keys (D-06: metrics.{...}).
METRIC_KEYS = ("completeness", "validity", "uniqueness", "relationship_integrity", "timeliness", "weighted_score",
               "critical_failures", "resolution_time", "ownership_coverage", "definition_coverage", "match_precision",
               "lineage_coverage")

ROLES = ("analyst", "steward", "admin")
DIMENSIONS = ("completeness", "validity", "uniqueness", "relationship", "timeliness")
RULE_TYPES = DIMENSIONS
SEVERITIES = ("low", "medium", "high", "critical")
RULE_STATUSES = ("active", "disabled")
RUN_KINDS = ("scheduled", "rerun")
ISSUE_STATUSES = ("open", "investigating", "closed")
EVIDENCE_TYPES = ("declared", "observed", "inferred")
METRIC_STATUSES = ("draft", "reviewed", "published", "superseded")   # FLOW-02: draft -> reviewed -> published (D-10)
DECISIONS = ("approve", "reject", "reverse")
GROUPS = ("none", "dataset", "owner", "source_system", "severity")

DEFAULT_TRIM = " \t\r\n"
#: Pattern escapes that Python ``re``, JavaScript RegExp and PostgreSQL regular expressions do not agree on (Unicode versus ASCII
#: classes, ``\b`` as a boundary or a backspace). A rule that uses one is refused at ingest (D-10, R7-04).
NON_PORTABLE_ESCAPES = "sSdDwWbB"
DEFAULT_WHITESPACE = {"name": "trim_empty_is_missing", "trim_characters": DEFAULT_TRIM}
DEFAULT_CHECKLIST = {"checklist_version": "cl-1", "items": ["definition", "grain", "source_fields", "owner", "refresh"]}
ID_KEYS = {"owners": "owner_id", "datasets": "dataset_id", "fields": "field_id", "quality_rules": "rule_id",
           "rule_runs": "rule_run_id", "issues": "issue_id", "lineage_edges": "edge_id",
           "metric_versions": "metric_version_id", "definition_changes": "change_id",
           "customer_records": "record_id", "match_candidates": "candidate_id", "merge_decisions": "merge_id"}
