const n=`{
  "contract_version": 1,
  "as_of": "2026-10-05T00:00:00Z",
  "cutoff": "2026-10-05T00:00:00Z",
  "business_total_field": "amount",
  "freshness_timestamp_field": "event_ts",
  "partition_rule": "UTC date of the freshness timestamp field",
  "source_expectations": [
    {
      "source_id": "src-orders",
      "partition": "2026-10-04",
      "expected_records": 0
    }
  ],
  "processing_measurement": null,
  "source_contracts": [
    {
      "source_id": "src-orders",
      "source_name": "Synthetic orders feed",
      "schema_version": "1",
      "expected_frequency": "hourly",
      "owner_id": "own-01"
    }
  ],
  "ingestion_batches": [],
  "raw_records": [],
  "quarantine_records": [],
  "checkpoints": [],
  "model_definitions": [],
  "pipeline_runs": [],
  "task_runs": [],
  "quality_results": [],
  "publications": [],
  "incidents": [],
  "backfill_requests": []
}
`;export{n as default};
