"""Contract constants (docs/contracts.md D-01..D-05; the fixture's decisions D-P9-01..24 are the binding form)."""
from __future__ import annotations

CONTRACT_VERSION = 1

#: Entities in import order: parents first (D-P9-01).
ENTITIES = ("initiatives", "process_baselines", "assumption_versions", "resources", "scenario_versions", "cost_items",
            "benefit_items", "dependencies", "stakeholder_groups", "impact_mappings", "resource_allocations",
            "readiness_assessments", "adoption_observations", "training_completions", "benefit_observations", "risk_items",
            "forecast_versions")
ID_FIELD = {"initiatives": "initiative_id", "process_baselines": "baseline_id", "assumption_versions": "assumption_id",
            "resources": "resource_id", "scenario_versions": "scenario_id", "cost_items": "cost_id",
            "benefit_items": "benefit_id", "dependencies": "dependency_id", "stakeholder_groups": "group_id",
            "impact_mappings": "mapping_id", "resource_allocations": "allocation_id", "readiness_assessments": "assessment_id",
            "adoption_observations": "observation_id", "training_completions": "training_id",
            "benefit_observations": "benefit_observation_id", "risk_items": "risk_id", "forecast_versions": "forecast_id"}
#: entity -> [(field, parent entity, code when unknown, nullable, is_list)]
FOREIGN_KEYS = {
    "process_baselines": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
    "assumption_versions": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", True, False)],
    "scenario_versions": [("initiative_ids", "initiatives", "UNKNOWN_INITIATIVE", False, True),
                          ("pinned_assumption_ids", "assumption_versions", "UNKNOWN_ASSUMPTION", False, True),
                          ("rate_conversion_assumption_id", "assumption_versions", "UNKNOWN_ASSUMPTION", True, False)],
    "cost_items": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
    "benefit_items": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
    "dependencies": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False),
                     ("prerequisite_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
    "impact_mappings": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False),
                        ("group_id", "stakeholder_groups", "UNKNOWN_GROUP", False, False)],
    "resource_allocations": [("resource_id", "resources", "UNKNOWN_RESOURCE", False, False),
                             ("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
    "readiness_assessments": [("group_id", "stakeholder_groups", "UNKNOWN_GROUP", False, False)],
    "adoption_observations": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
    "training_completions": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
    "benefit_observations": [("benefit_id", "benefit_items", "UNKNOWN_BENEFIT", False, False)],
    "risk_items": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
    "forecast_versions": [("initiative_id", "initiatives", "UNKNOWN_INITIATIVE", False, False)],
}
INITIATIVE_STATUSES = ("candidate", "assessed", "in_delivery", "adopted", "closed")   # no "funded" (P09-FLOW-07, D-P9-19)
SCENARIO_STATUSES = ("draft", "proposed")
BENEFIT_TYPES = ("cash", "avoided_cost", "revenue", "capacity")
MONEY_TYPES = ("cash", "avoided_cost", "revenue")
COST_TYPES = ("one_time", "recurring")
COST_BASES = ("planned", "actual")
DEPENDENCY_TYPES = ("finish_to_start", "start_to_start")
IMPACT_LEVELS = ("low", "medium", "high")
DIMENSIONS = ("awareness", "desire", "knowledge", "ability", "reinforcement")      # ADKAR-inspired (D-03)
BASES = ("annual", "monthly")
ROLES = ("analyst", "sponsor", "admin")
CONVERSION_NAME = "monthly_rate_conversion"
CAPACITY_RATE_NAME = "capacity_hourly_rate"
RAMP_NAME = "adoption_ramp"
TARGET_NAME = "target_minutes_per_case"
MAX_HORIZON = 600
MAX_PERIOD = 100_000
