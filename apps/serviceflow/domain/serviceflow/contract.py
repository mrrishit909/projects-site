"""Contract constants (docs/contracts.md, version 1, decisions D-01..D-05)."""
from __future__ import annotations

CONTRACT_VERSION = 1

#: Entities of an input batch, parents first (also the order of the ingest counts in expected.json).
ENTITIES = ("customers", "queues", "tickets", "ticket_events", "agents", "skills", "agent_skills",
            "queue_skills", "shifts", "sla_policies", "surveys", "simulation_runs")

#: D-01 event types of the canonical log.
EVENT_TYPES = ("created", "queued", "acknowledged_bot", "service_started", "replied_human", "paused", "resumed",
               "transferred", "resolved", "reopened", "abandoned")
#: Events that open an active-service interval, and events that close one (D-02: handling = sum of intervals).
OPENERS = frozenset({"service_started", "resumed"})
CLOSERS = frozenset({"resolved", "paused", "transferred", "abandoned"})

PRIORITIES = ("P1", "P2", "P3")
PRIORITY_POLICIES = ("fifo_within_priority", "fifo")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contractor")

#: An actor id with this prefix is automation: its replies are never a first human response (D-02, P04-TEST-01).
BOT_PREFIX = "bot-"
#: Channels that can abandon when the batch does not declare ``abandonable_channels`` (D-05).
DEFAULT_ABANDONABLE = ("chat", "phone")

#: Group keys of ``group_metrics``.
GROUP_KEYS = ("queue", "priority", "agent", "channel")

#: Metric names in the order of expected.json.
METRIC_KEYS = (
    "arrival_count", "completion_count", "arrival_rate_per_hour", "completion_rate_per_hour", "backlog",
    "first_response_minutes", "mean_first_response_minutes", "p90_first_response_minutes", "wait_minutes",
    "mean_wait_minutes", "resolution_minutes", "mean_resolution_minutes", "handling_minutes_total",
    "sla_first_response_compliance", "sla_first_response_within", "sla_first_response_eligible",
    "sla_resolution_compliance", "sla_resolution_within", "sla_resolution_eligible", "open_overdue_at_cutoff",
    "staffed_available_minutes", "staffed_shift_minutes_whole", "agent_occupancy", "abandonment_rate", "csat",
    "survey_invitation_rate", "survey_response_rate", "empty_population")
