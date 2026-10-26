"""Contract constants (docs/contracts.md, version v1)."""
from __future__ import annotations

CONTRACT_VERSION = "v1"
ACCEPTED_INPUT_CONTRACTS = frozenset({"v1"})

#: Entities of an input batch, parents first (also the order of the ingest counts).
ENTITIES = ("organizations", "cases", "workflow_versions", "step_definitions", "dependencies",
            "step_instances", "assignments", "document_versions", "approvals", "sla_rules",
            "calendar_intervals", "waiting_intervals", "case_events")

#: D-03 step instance states and their allowed transitions.
STEP_STATES = ("blocked", "ready", "in_progress", "in_review", "approved", "changes_requested")
STEP_TRANSITIONS: dict[str, frozenset[str]] = {
    "blocked": frozenset({"ready"}),
    "ready": frozenset({"in_progress", "in_review"}),
    "in_progress": frozenset({"in_review"}),
    "in_review": frozenset({"approved", "changes_requested"}),
    "approved": frozenset(),
    "changes_requested": frozenset({"ready"}),
}
CASE_STATES = ("open", "completed")
DOCUMENT_STATES = ("submitted", "accepted", "rejected")
DEPENDENCY_TYPES = ("mandatory", "optional")

#: Metric names in the order of expected.json.
METRIC_KEYS = ("calendar_cycle_time_hours", "business_cycle_time_hours", "paused_time_hours",
               "paused_business_overlap_hours", "active_elapsed_hours", "sla_attainment",
               "completed_eligible_cases", "within_sla_cases", "open_backlog_at_cutoff",
               "rework_rate", "handoff_count", "step_waiting_time_hours", "first_pass_approval",
               "document_completeness", "empty_population")
