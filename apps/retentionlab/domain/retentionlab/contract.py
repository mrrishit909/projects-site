"""Contract constants (docs/contracts.md, docs/api-contract.md, the golden fixture)."""
from __future__ import annotations

CONTRACT_VERSION = 1
ROLES = ("scientist", "analyst", "admin")
#: Entities in import order (parents first). The first twelve are the logical entities of section 03; the last three are the
#: registry, the split and the publications the application stores.
ENTITIES = ("accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows",
            "labels", "training_runs", "predictions", "intervention_scenarios", "outreach_events", "feature_registry",
            "split_assignments", "scoring_publications")
ID = {"accounts": "account_id", "subscription_events": "subscription_event_id", "billing_events": "billing_event_id",
      "usage_events": "usage_event_id", "support_events": "support_event_id", "prediction_cutoffs": "cutoff_id",
      "feature_rows": "feature_row_id", "labels": "label_id", "training_runs": "training_run_id", "predictions": "prediction_id",
      "intervention_scenarios": "scenario_id", "outreach_events": "outreach_event_id", "feature_registry": "feature_name",
      "split_assignments": "assignment_id", "scoring_publications": "publication_id"}
EVENTS = ("subscription_events", "billing_events", "usage_events", "support_events")
#: child entity -> [(foreign key field, parent entity, code when the parent id is unknown)], checked in this order (D-P10-15)
FK: dict[str, list[tuple[str, str, str]]] = {e: [("account_id", "accounts", "UNKNOWN_ACCOUNT")] for e in EVENTS}
FK.update({
    "prediction_cutoffs": [("account_id", "accounts", "UNKNOWN_ACCOUNT")],
    "feature_rows": [("cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF")],
    "labels": [("cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF")],
    "predictions": [("training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN"), ("cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF")],
    "outreach_events": [("account_id", "accounts", "UNKNOWN_ACCOUNT"), ("scenario_id", "intervention_scenarios", "UNKNOWN_SCENARIO")],
    "split_assignments": [("training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN"), ("cutoff_id", "prediction_cutoffs", "UNKNOWN_CUTOFF")],
    "scoring_publications": [("training_run_id", "training_runs", "UNKNOWN_TRAINING_RUN")]})
#: The registered features of feature version fv-1, in column order.
FEATURES = ("usage_events_30d", "days_since_last_usage", "high_severity_support_90d", "billing_total_90d")
#: Features that can be missing (null), and therefore get a missing indicator when training rows miss them.
NULLABLE_FEATURES = ("days_since_last_usage", "billing_total_90d")
CAL_BINS = 10
MODELS = ("random_baseline", "business_rule", "logistic_regression")
DEFAULT_MODEL = "logistic_regression"
BUSINESS_RULE = "no_usage_30d_or_open_high_severity_support"
DEFAULT_DRIFT_BINS = ({"label": "0", "lower": 0, "upper": 1}, {"label": "1-2", "lower": 1, "upper": 3}, {"label": "3+", "lower": 3, "upper": None})
DEFAULT_DRIFT = {"feature": "usage_events_30d", "bins": list(DEFAULT_DRIFT_BINS), "floor": "0.000100", "threshold": "0.200000"}
