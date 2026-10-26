"""Contract constants (docs/contracts.md, version 1, decisions D-01..D-05)."""
from __future__ import annotations

CONTRACT_VERSION = 1
RULE_VERSION = "v1"                     # identity-resolution rule version carried by identity links (D-01)

#: Entities of an input batch, parents first (also the order of the ingest counts in expected.json).
ENTITIES = ("accounts", "users", "identity_links", "sessions", "events", "event_properties", "subscriptions",
            "experiment_versions", "assignments", "exposures", "metric_observations", "analysis_runs")

#: Metric names in the order of expected.json["metrics"]. ``tracking_quality`` and ``identity`` are not metrics: they
#: travel beside them (PipelineResult, API ``data``), so ``metrics`` stays exactly the expected.json keys.
METRIC_KEYS = ("signup_conversion", "funnel", "activation", "retention", "feature_adoption", "experiment")

ROLES = ("analyst", "experimenter", "admin")
VARIANTS_DEFAULT = ("control", "treatment")
DECISIONS = ("ship", "stop", "inconclusive")
GROUPS = ("none", "variant", "plan", "segment", "timezone")

#: Retention thresholds (D-02): day 7 is mature once day 8 has begun; week 4 (days 28-34) once day 35 has begun.
DAY7 = 7
WEEK4 = (28, 34)

#: Upper bound of any amount (NUMERIC(20,2) columns).
MAX_ABS = 10 ** 12

#: Windows used when neither the request nor a stored configuration names one (README assumption 3).
DEFAULT_FEATURE = {"feature": "export", "eligible_plans": ["team", "business"]}
DEFAULT_ACTIVATION_DAYS = 7
