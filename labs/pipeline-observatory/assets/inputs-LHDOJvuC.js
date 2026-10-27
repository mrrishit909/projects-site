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
      "expected_records": 4
    }
  ],
  "processing_measurement": {
    "source_id": "src-orders",
    "batch_id": "b-001",
    "measured_seconds": "6",
    "hardware": "Synthetic fixture value, not a benchmark: 2 vCPU, 8 GB RAM, GitHub-hosted runner class",
    "cache_state": "warm"
  },
  "source_contracts": [
    {
      "source_id": "src-orders",
      "source_name": "Synthetic orders feed",
      "schema_version": "1",
      "expected_frequency": "hourly",
      "owner_id": "own-01"
    }
  ],
  "ingestion_batches": [
    {
      "batch_id": "b-001",
      "source_id": "src-orders",
      "source_cursor": "cur-000",
      "started_at": "2026-10-04T09:00:00Z",
      "status": "committed"
    },
    {
      "batch_id": "b-002",
      "source_id": "src-orders",
      "source_cursor": "cur-003",
      "started_at": "2026-10-04T10:00:00Z",
      "status": "committed"
    },
    {
      "batch_id": "b-003",
      "source_id": "src-orders",
      "source_cursor": "cur-006",
      "started_at": "2026-10-04T11:00:00Z",
      "status": "committed"
    }
  ],
  "raw_records": [
    {
      "raw_record_id": "rr-b-001-01",
      "batch_id": "b-001",
      "source_key": "ORD-1",
      "payload_hash": "98f5f44b994a2cea7324c79734c8fb1e7345d0d9d9ac8ee00529bbb44df90086",
      "payload_json": {
        "record_id": "ORD-1",
        "quantity": 2,
        "unit_price": "10.00",
        "amount": "20.00",
        "event_ts": "2026-10-04T08:00:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-02",
      "batch_id": "b-001",
      "source_key": "ORD-2",
      "payload_hash": "a6b801c37bb2d325f30ff6f4f70d600c8d7f0774a346a71ba398d1d3aeef4ae0",
      "payload_json": {
        "record_id": "ORD-2",
        "quantity": 1,
        "unit_price": "5.50",
        "amount": "5.50",
        "event_ts": "2026-10-04T08:30:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-03",
      "batch_id": "b-001",
      "source_key": "ORD-3",
      "payload_hash": "67478279c56d75c873267dc0193e330e87482ce777aa53b058fae541541548ea",
      "payload_json": {
        "record_id": "ORD-3",
        "quantity": -1,
        "unit_price": "8.00",
        "amount": "-8.00",
        "event_ts": "2026-10-04T08:45:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-01",
      "batch_id": "b-002",
      "source_key": "ORD-4",
      "payload_hash": "452a036456a5c6e4644f2a1e84b846c63d694a65655d638b450231d15534352c",
      "payload_json": {
        "record_id": "ORD-4",
        "quantity": 3,
        "unit_price": "4.00",
        "amount": "12.00",
        "event_ts": "2026-10-04T09:30:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-01",
      "batch_id": "b-003",
      "source_key": "ORD-5",
      "payload_hash": "e49b02401f7889b6a41daefe5bcac64bc08d7891db1460bb3aea7f640f4c8d9f",
      "payload_json": {
        "record_id": "ORD-5",
        "quantity": 1,
        "unit_price": "9.00",
        "amount": "9.00",
        "event_ts": "2026-10-04T10:00:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-02",
      "batch_id": "b-003",
      "source_key": "ORD-6",
      "payload_hash": "0f327ddfa8c640094edc306f303d600e9b305ea11020442ca85fac3f73a0e1bc",
      "payload_json": {
        "record_id": "ORD-6",
        "quantity": 2,
        "unit_price": "6.00",
        "amount": "12.00",
        "event_ts": "2026-10-04T10:15:00Z"
      }
    }
  ],
  "quarantine_records": [
    {
      "quarantine_id": "q-001",
      "batch_id": "b-001",
      "source_key": "ORD-3",
      "reason_code": "NEGATIVE_QUANTITY",
      "payload_hash": "67478279c56d75c873267dc0193e330e87482ce777aa53b058fae541541548ea"
    }
  ],
  "checkpoints": [
    {
      "checkpoint_id": "cp-001",
      "source_id": "src-orders",
      "batch_id": "b-001",
      "committed_cursor": "cur-003",
      "committed_at": "2026-10-04T09:05:00Z",
      "version_number": 1
    },
    {
      "checkpoint_id": "cp-002",
      "source_id": "src-orders",
      "batch_id": "b-002",
      "committed_cursor": "cur-006",
      "committed_at": "2026-10-04T10:05:00Z",
      "version_number": 2
    },
    {
      "checkpoint_id": "cp-003",
      "source_id": "src-orders",
      "batch_id": "b-003",
      "committed_cursor": "cur-009",
      "committed_at": "2026-10-04T11:05:00Z",
      "version_number": 1
    }
  ],
  "model_definitions": [],
  "pipeline_runs": [
    {
      "run_id": "run-001",
      "started_at": "2026-10-04T11:10:00Z",
      "finished_at": "2026-10-04T11:30:00Z",
      "status": "success",
      "code_sha": "a1b2c3d",
      "backfill_id": null
    },
    {
      "run_id": "run-bf-2",
      "started_at": "2026-10-04T13:00:00Z",
      "finished_at": "2026-10-04T13:10:00Z",
      "status": "success",
      "code_sha": "a1b2c3d",
      "backfill_id": "bf-002"
    }
  ],
  "task_runs": [
    {
      "task_run_id": "tr-001-1",
      "run_id": "run-001",
      "task_name": "ingest",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-001-2",
      "run_id": "run-001",
      "task_name": "ingest",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-001-3",
      "run_id": "run-001",
      "task_name": "quality_gate",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-bf2-1",
      "run_id": "run-bf-2",
      "task_name": "ingest",
      "status": "success",
      "attempt": "1"
    }
  ],
  "quality_results": [
    {
      "quality_result_id": "qr-001-1",
      "task_run_id": "tr-001-3",
      "rule_name": "keys_unique",
      "severity": "critical",
      "eligible_count": 3,
      "failure_count": 0
    },
    {
      "quality_result_id": "qr-001-2",
      "task_run_id": "tr-001-2",
      "rule_name": "keys_unique",
      "severity": "critical",
      "eligible_count": 3,
      "failure_count": 0
    },
    {
      "quality_result_id": "qr-bf2-1",
      "task_run_id": "tr-bf2-1",
      "rule_name": "keys_unique",
      "severity": "critical",
      "eligible_count": 1,
      "failure_count": 0
    }
  ],
  "publications": [
    {
      "publication_id": "pub-001",
      "run_id": "run-001",
      "dataset_name": "sales_daily",
      "published_at": "2026-10-04T11:30:00Z",
      "watermark": "2026-10-04T10:30:00Z",
      "source_ids": [
        "src-orders"
      ],
      "included_batch_ids": [
        "b-001",
        "b-002"
      ],
      "content_hash": "8b289f415f9df46dd5775d533aa2d07dcba60e9de8f78fe17ac15801030f51e4"
    }
  ],
  "incidents": [],
  "backfill_requests": [
    {
      "backfill_id": "bf-001",
      "source_id": "src-orders",
      "start_at": "2026-09-01T00:00:00Z",
      "end_at": "2026-09-04T00:00:00Z",
      "status": "partial",
      "partitions": [
        {
          "partition": "2026-09-01",
          "verified": true
        },
        {
          "partition": "2026-09-02",
          "verified": true
        },
        {
          "partition": "2026-09-03",
          "verified": false
        }
      ]
    },
    {
      "backfill_id": "bf-002",
      "source_id": "src-orders",
      "start_at": "2026-09-03T00:00:00Z",
      "end_at": "2026-09-06T00:00:00Z",
      "status": "requested",
      "partitions": [
        {
          "partition": "2026-09-03",
          "verified": false
        },
        {
          "partition": "2026-09-04",
          "verified": false
        },
        {
          "partition": "2026-09-05",
          "verified": false
        }
      ]
    },
    {
      "backfill_id": "bf-003",
      "source_id": "src-orders",
      "start_at": "2026-09-04T00:00:00Z",
      "end_at": "2026-09-05T00:00:00Z",
      "status": "requested",
      "partitions": [
        {
          "partition": "2026-09-04",
          "verified": false
        }
      ]
    }
  ]
}
`;export{n as default};
