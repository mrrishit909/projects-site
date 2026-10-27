// Constants of contract v1 (docs/contracts.md): entity names, keys, foreign keys, metric keys.
import * as E from "./errors";

export const CONTRACT_VERSION = 1;
export const ENTITIES = ["source_contracts", "ingestion_batches", "raw_records", "quarantine_records", "checkpoints", "model_definitions",
  "pipeline_runs", "task_runs", "quality_results", "publications", "incidents", "backfill_requests"] as const;
export type Entity = (typeof ENTITIES)[number];
export const ID: Record<Entity, string> = {
  source_contracts: "source_id", ingestion_batches: "batch_id", raw_records: "raw_record_id", quarantine_records: "quarantine_id",
  checkpoints: "checkpoint_id", model_definitions: "model_id", pipeline_runs: "run_id", task_runs: "task_run_id", quality_results: "quality_result_id",
  publications: "publication_id", incidents: "incident_id", backfill_requests: "backfill_id",
};
/** child entity -> [foreign key field, parent entity, code when the parent id is unknown] */
export const FK: Partial<Record<Entity, readonly [string, Entity, string]>> = {
  ingestion_batches: ["source_id", "source_contracts", E.UNKNOWN_SOURCE],
  backfill_requests: ["source_id", "source_contracts", E.UNKNOWN_SOURCE],
  raw_records: ["batch_id", "ingestion_batches", E.UNKNOWN_BATCH],
  quarantine_records: ["batch_id", "ingestion_batches", E.UNKNOWN_BATCH],
  checkpoints: ["batch_id", "ingestion_batches", E.UNKNOWN_BATCH],
  task_runs: ["run_id", "pipeline_runs", E.UNKNOWN_RUN],
  quality_results: ["task_run_id", "task_runs", E.UNKNOWN_TASK_RUN],
  publications: ["run_id", "pipeline_runs", E.UNKNOWN_RUN],
  incidents: ["run_id", "pipeline_runs", E.UNKNOWN_RUN],
};
/** Payload fields every upsert record must carry (D-P8-12). */
export const REQUIRED_FIELDS = ["record_id", "quantity", "unit_price", "amount", "event_ts"] as const;
export const METRIC_KEYS = ["ingestion", "freshness", "completeness", "runs", "quality_gate", "publications", "late_events", "reconciliation",
  "incidents", "backfills", "processing_rate"] as const;
export const BATCH_STATUSES = ["staged", "committed", "aborted", "quarantined"] as const;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any>;
