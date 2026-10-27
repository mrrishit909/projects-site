"""Constants of contract v1 (docs/contracts.md): entity names, keys, foreign keys, metric keys, roles."""
from __future__ import annotations

CONTRACT_VERSION = 1

ENTITIES = ("source_contracts", "ingestion_batches", "raw_records", "quarantine_records", "checkpoints", "model_definitions",
            "pipeline_runs", "task_runs", "quality_results", "publications", "incidents", "backfill_requests")

ID = {"source_contracts": "source_id", "ingestion_batches": "batch_id", "raw_records": "raw_record_id",
      "quarantine_records": "quarantine_id", "checkpoints": "checkpoint_id", "model_definitions": "model_id",
      "pipeline_runs": "run_id", "task_runs": "task_run_id", "quality_results": "quality_result_id",
      "publications": "publication_id", "incidents": "incident_id", "backfill_requests": "backfill_id"}

# child entity -> (foreign key field, parent entity, code when the parent id is unknown)
FK = {"ingestion_batches": ("source_id", "source_contracts", "UNKNOWN_SOURCE"),
      "backfill_requests": ("source_id", "source_contracts", "UNKNOWN_SOURCE"),
      "raw_records": ("batch_id", "ingestion_batches", "UNKNOWN_BATCH"),
      "quarantine_records": ("batch_id", "ingestion_batches", "UNKNOWN_BATCH"),
      "checkpoints": ("batch_id", "ingestion_batches", "UNKNOWN_BATCH"),
      "task_runs": ("run_id", "pipeline_runs", "UNKNOWN_RUN"),
      "quality_results": ("task_run_id", "task_runs", "UNKNOWN_TASK_RUN"),
      "publications": ("run_id", "pipeline_runs", "UNKNOWN_RUN"),
      "incidents": ("run_id", "pipeline_runs", "UNKNOWN_RUN")}

#: Payload fields every upsert record must carry (D-P8-12).
REQUIRED_FIELDS = ("record_id", "quantity", "unit_price", "amount", "event_ts")

METRIC_KEYS = ("ingestion", "freshness", "completeness", "runs", "quality_gate", "publications", "late_events", "reconciliation",
               "incidents", "backfills", "processing_rate")

ROLES = ("engineer", "operator", "admin")

#: The batch statuses. Only ``committed`` counts (D-P8-04); ``staged`` (fetched, not yet committed) and ``quarantined`` (a whole
#: batch refused, e.g. SCHEMA_CHANGED) are evidence like ``aborted``.
BATCH_STATUSES = ("staged", "committed", "aborted", "quarantined")
