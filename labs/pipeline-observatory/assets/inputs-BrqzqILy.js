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
      "expected_records": 9
    },
    {
      "source_id": "src-refunds",
      "partition": "2026-10-04",
      "expected_records": 1
    }
  ],
  "processing_measurement": {
    "source_id": "src-orders",
    "batch_id": "b-001",
    "measured_seconds": "12",
    "hardware": "Synthetic fixture value, not a benchmark: 2 vCPU, 8 GB RAM, GitHub-hosted runner class",
    "cache_state": "cold"
  },
  "source_contracts": [
    {
      "source_id": "src-orders",
      "source_name": "Synthetic orders feed",
      "schema_version": "1",
      "expected_frequency": "hourly",
      "owner_id": "own-01"
    },
    {
      "source_id": "src-refunds",
      "source_name": "Synthetic refunds feed",
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
      "started_at": "2026-10-04T10:00:00Z",
      "status": "committed"
    },
    {
      "batch_id": "b-002",
      "source_id": "src-orders",
      "source_cursor": "cur-000",
      "started_at": "2026-10-04T12:00:00Z",
      "status": "committed"
    },
    {
      "batch_id": "b-003",
      "source_id": "src-orders",
      "source_cursor": "cur-000",
      "started_at": "2026-10-04T18:00:00Z",
      "status": "aborted"
    },
    {
      "batch_id": "b-101",
      "source_id": "src-refunds",
      "source_cursor": "cur-000",
      "started_at": "2026-10-04T11:00:00Z",
      "status": "committed"
    }
  ],
  "raw_records": [
    {
      "raw_record_id": "rr-b-001-01",
      "batch_id": "b-001",
      "source_key": "ORD-1001",
      "payload_hash": "7681bee6d69b7d1d9d40989ef44b8725d2ec2fea4fa67f9437165a67c17e4910",
      "payload_json": {
        "record_id": "ORD-1001",
        "quantity": 2,
        "unit_price": "12.50",
        "amount": "25.00",
        "event_ts": "2026-10-04T08:00:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-02",
      "batch_id": "b-001",
      "source_key": "ORD-1002",
      "payload_hash": "da6a70b792830d165833be26e4244597f99448747c23c3a34ad9ca58fa766971",
      "payload_json": {
        "record_id": "ORD-1002",
        "quantity": 1,
        "unit_price": "40.00",
        "amount": "40.00",
        "event_ts": "2026-10-04T08:20:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-03",
      "batch_id": "b-001",
      "source_key": "ORD-1003",
      "payload_hash": "1d13824d2b0bb385ffab1c229e4e35203efbf8e915468ad0fef217b5c6dff324",
      "payload_json": {
        "record_id": "ORD-1003",
        "quantity": 3,
        "unit_price": "9.99",
        "amount": "29.97",
        "event_ts": "2026-10-04T08:40:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-04",
      "batch_id": "b-001",
      "source_key": "ORD-1004",
      "payload_hash": "408e3f857a89a8ac3752fc355676987a4151eb5428c39f5d7ad65394f8862f87",
      "payload_json": {
        "record_id": "ORD-1004",
        "quantity": 5,
        "unit_price": "4.00",
        "amount": "20.00",
        "event_ts": "2026-10-04T09:00:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-05",
      "batch_id": "b-001",
      "source_key": "ORD-1005",
      "payload_hash": "e2afbede2a25b481cee29eafde3fe7986aade38ac724893c3bc9c7197a7a81a4",
      "payload_json": {
        "record_id": "ORD-1005",
        "quantity": 1,
        "unit_price": "100.00",
        "amount": "100.00",
        "event_ts": "2026-10-04T09:10:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-06",
      "batch_id": "b-001",
      "source_key": "ORD-1003",
      "payload_hash": "1d13824d2b0bb385ffab1c229e4e35203efbf8e915468ad0fef217b5c6dff324",
      "payload_json": {
        "record_id": "ORD-1003",
        "quantity": 3,
        "unit_price": "9.99",
        "amount": "29.97",
        "event_ts": "2026-10-04T08:40:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-07",
      "batch_id": "b-001",
      "source_key": "ORD-1006",
      "payload_hash": "36239b2d0a91e87dfc769909e0b9547516877918df899d9e83a35b375b715df6",
      "payload_json": {
        "record_id": "ORD-1006",
        "quantity": 4,
        "unit_price": "7.25",
        "amount": "29.00",
        "event_ts": "2026-10-04T09:20:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-08",
      "batch_id": "b-001",
      "source_key": "ORD-1009",
      "payload_hash": "5984b9748d4a5220c39dfd105d12cfc50cff400642fab1f53b8aabeb188b13a4",
      "payload_json": {
        "record_id": "ORD-1009",
        "quantity": -3,
        "unit_price": "10.00",
        "amount": "-30.00",
        "event_ts": "2026-10-04T09:25:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-09",
      "batch_id": "b-001",
      "source_key": "ORD-1007",
      "payload_hash": "47eb58cfc78aba4a9da3cb9864841624afba12c070f3b968e0cda846a4f80f9b",
      "payload_json": {
        "record_id": "ORD-1007",
        "quantity": 2,
        "unit_price": "15.50",
        "amount": "31.00",
        "event_ts": "2026-10-04T09:30:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-001-10",
      "batch_id": "b-001",
      "source_key": "ORD-1008",
      "payload_hash": "f1e8cede22c9398e9df70ead7db2d069b29ddd74994e54138cbbd1a302d94680",
      "payload_json": {
        "record_id": "ORD-1008",
        "quantity": 6,
        "unit_price": "2.50",
        "amount": "15.00",
        "event_ts": "2026-10-04T09:15:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-01",
      "batch_id": "b-002",
      "source_key": "ORD-1001",
      "payload_hash": "7681bee6d69b7d1d9d40989ef44b8725d2ec2fea4fa67f9437165a67c17e4910",
      "payload_json": {
        "record_id": "ORD-1001",
        "quantity": 2,
        "unit_price": "12.50",
        "amount": "25.00",
        "event_ts": "2026-10-04T08:00:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-02",
      "batch_id": "b-002",
      "source_key": "ORD-1002",
      "payload_hash": "da6a70b792830d165833be26e4244597f99448747c23c3a34ad9ca58fa766971",
      "payload_json": {
        "record_id": "ORD-1002",
        "quantity": 1,
        "unit_price": "40.00",
        "amount": "40.00",
        "event_ts": "2026-10-04T08:20:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-03",
      "batch_id": "b-002",
      "source_key": "ORD-1003",
      "payload_hash": "1d13824d2b0bb385ffab1c229e4e35203efbf8e915468ad0fef217b5c6dff324",
      "payload_json": {
        "record_id": "ORD-1003",
        "quantity": 3,
        "unit_price": "9.99",
        "amount": "29.97",
        "event_ts": "2026-10-04T08:40:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-04",
      "batch_id": "b-002",
      "source_key": "ORD-1004",
      "payload_hash": "408e3f857a89a8ac3752fc355676987a4151eb5428c39f5d7ad65394f8862f87",
      "payload_json": {
        "record_id": "ORD-1004",
        "quantity": 5,
        "unit_price": "4.00",
        "amount": "20.00",
        "event_ts": "2026-10-04T09:00:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-05",
      "batch_id": "b-002",
      "source_key": "ORD-1005",
      "payload_hash": "e2afbede2a25b481cee29eafde3fe7986aade38ac724893c3bc9c7197a7a81a4",
      "payload_json": {
        "record_id": "ORD-1005",
        "quantity": 1,
        "unit_price": "100.00",
        "amount": "100.00",
        "event_ts": "2026-10-04T09:10:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-06",
      "batch_id": "b-002",
      "source_key": "ORD-1003",
      "payload_hash": "1d13824d2b0bb385ffab1c229e4e35203efbf8e915468ad0fef217b5c6dff324",
      "payload_json": {
        "record_id": "ORD-1003",
        "quantity": 3,
        "unit_price": "9.99",
        "amount": "29.97",
        "event_ts": "2026-10-04T08:40:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-07",
      "batch_id": "b-002",
      "source_key": "ORD-1006",
      "payload_hash": "36239b2d0a91e87dfc769909e0b9547516877918df899d9e83a35b375b715df6",
      "payload_json": {
        "record_id": "ORD-1006",
        "quantity": 4,
        "unit_price": "7.25",
        "amount": "29.00",
        "event_ts": "2026-10-04T09:20:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-08",
      "batch_id": "b-002",
      "source_key": "ORD-1009",
      "payload_hash": "5984b9748d4a5220c39dfd105d12cfc50cff400642fab1f53b8aabeb188b13a4",
      "payload_json": {
        "record_id": "ORD-1009",
        "quantity": -3,
        "unit_price": "10.00",
        "amount": "-30.00",
        "event_ts": "2026-10-04T09:25:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-09",
      "batch_id": "b-002",
      "source_key": "ORD-1007",
      "payload_hash": "47eb58cfc78aba4a9da3cb9864841624afba12c070f3b968e0cda846a4f80f9b",
      "payload_json": {
        "record_id": "ORD-1007",
        "quantity": 2,
        "unit_price": "15.50",
        "amount": "31.00",
        "event_ts": "2026-10-04T09:30:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-002-10",
      "batch_id": "b-002",
      "source_key": "ORD-1008",
      "payload_hash": "f1e8cede22c9398e9df70ead7db2d069b29ddd74994e54138cbbd1a302d94680",
      "payload_json": {
        "record_id": "ORD-1008",
        "quantity": 6,
        "unit_price": "2.50",
        "amount": "15.00",
        "event_ts": "2026-10-04T09:15:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-01",
      "batch_id": "b-003",
      "source_key": "ORD-1001",
      "payload_hash": "7681bee6d69b7d1d9d40989ef44b8725d2ec2fea4fa67f9437165a67c17e4910",
      "payload_json": {
        "record_id": "ORD-1001",
        "quantity": 2,
        "unit_price": "12.50",
        "amount": "25.00",
        "event_ts": "2026-10-04T08:00:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-02",
      "batch_id": "b-003",
      "source_key": "ORD-1002",
      "payload_hash": "da6a70b792830d165833be26e4244597f99448747c23c3a34ad9ca58fa766971",
      "payload_json": {
        "record_id": "ORD-1002",
        "quantity": 1,
        "unit_price": "40.00",
        "amount": "40.00",
        "event_ts": "2026-10-04T08:20:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-03",
      "batch_id": "b-003",
      "source_key": "ORD-1003",
      "payload_hash": "1d13824d2b0bb385ffab1c229e4e35203efbf8e915468ad0fef217b5c6dff324",
      "payload_json": {
        "record_id": "ORD-1003",
        "quantity": 3,
        "unit_price": "9.99",
        "amount": "29.97",
        "event_ts": "2026-10-04T08:40:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-04",
      "batch_id": "b-003",
      "source_key": "ORD-1004",
      "payload_hash": "408e3f857a89a8ac3752fc355676987a4151eb5428c39f5d7ad65394f8862f87",
      "payload_json": {
        "record_id": "ORD-1004",
        "quantity": 5,
        "unit_price": "4.00",
        "amount": "20.00",
        "event_ts": "2026-10-04T09:00:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-05",
      "batch_id": "b-003",
      "source_key": "ORD-1005",
      "payload_hash": "e2afbede2a25b481cee29eafde3fe7986aade38ac724893c3bc9c7197a7a81a4",
      "payload_json": {
        "record_id": "ORD-1005",
        "quantity": 1,
        "unit_price": "100.00",
        "amount": "100.00",
        "event_ts": "2026-10-04T09:10:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-06",
      "batch_id": "b-003",
      "source_key": "ORD-1003",
      "payload_hash": "1d13824d2b0bb385ffab1c229e4e35203efbf8e915468ad0fef217b5c6dff324",
      "payload_json": {
        "record_id": "ORD-1003",
        "quantity": 3,
        "unit_price": "9.99",
        "amount": "29.97",
        "event_ts": "2026-10-04T08:40:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-07",
      "batch_id": "b-003",
      "source_key": "ORD-1006",
      "payload_hash": "36239b2d0a91e87dfc769909e0b9547516877918df899d9e83a35b375b715df6",
      "payload_json": {
        "record_id": "ORD-1006",
        "quantity": 4,
        "unit_price": "7.25",
        "amount": "29.00",
        "event_ts": "2026-10-04T09:20:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-08",
      "batch_id": "b-003",
      "source_key": "ORD-1009",
      "payload_hash": "5984b9748d4a5220c39dfd105d12cfc50cff400642fab1f53b8aabeb188b13a4",
      "payload_json": {
        "record_id": "ORD-1009",
        "quantity": -3,
        "unit_price": "10.00",
        "amount": "-30.00",
        "event_ts": "2026-10-04T09:25:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-09",
      "batch_id": "b-003",
      "source_key": "ORD-1007",
      "payload_hash": "47eb58cfc78aba4a9da3cb9864841624afba12c070f3b968e0cda846a4f80f9b",
      "payload_json": {
        "record_id": "ORD-1007",
        "quantity": 2,
        "unit_price": "15.50",
        "amount": "31.00",
        "event_ts": "2026-10-04T09:30:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-003-10",
      "batch_id": "b-003",
      "source_key": "ORD-1008",
      "payload_hash": "f1e8cede22c9398e9df70ead7db2d069b29ddd74994e54138cbbd1a302d94680",
      "payload_json": {
        "record_id": "ORD-1008",
        "quantity": 6,
        "unit_price": "2.50",
        "amount": "15.00",
        "event_ts": "2026-10-04T09:15:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-101-01",
      "batch_id": "b-101",
      "source_key": "REF-2001",
      "payload_hash": "ee43ad3c318a2af19e1f97543c56c13f854f9310cb5ace4fd5f228fd6b26349e",
      "payload_json": {
        "record_id": "REF-2001",
        "quantity": 1,
        "unit_price": "12.00",
        "amount": "12.00",
        "event_ts": "2026-10-04T09:10:00Z"
      }
    },
    {
      "raw_record_id": "rr-b-101-02",
      "batch_id": "b-101",
      "source_key": "REF-2002",
      "payload_hash": "d880397f860730292cdf7fcb39fa68de35874edf35bf58429215f970f93ef5c1",
      "payload_json": {
        "record_id": "REF-2002",
        "quantity": 2,
        "unit_price": "4.00",
        "amount": "8.00",
        "event_ts": "2026-10-04T12:00:00Z"
      }
    }
  ],
  "quarantine_records": [
    {
      "quarantine_id": "q-b-001-01",
      "batch_id": "b-001",
      "source_key": "ORD-1009",
      "reason_code": "NEGATIVE_QUANTITY",
      "payload_hash": "5984b9748d4a5220c39dfd105d12cfc50cff400642fab1f53b8aabeb188b13a4"
    },
    {
      "quarantine_id": "q-b-002-01",
      "batch_id": "b-002",
      "source_key": "ORD-1009",
      "reason_code": "NEGATIVE_QUANTITY",
      "payload_hash": "5984b9748d4a5220c39dfd105d12cfc50cff400642fab1f53b8aabeb188b13a4"
    },
    {
      "quarantine_id": "q-b-101-01",
      "batch_id": "b-101",
      "source_key": "REF-2002",
      "reason_code": "EVENT_IN_FUTURE",
      "payload_hash": "d880397f860730292cdf7fcb39fa68de35874edf35bf58429215f970f93ef5c1"
    }
  ],
  "checkpoints": [
    {
      "checkpoint_id": "cp-001",
      "source_id": "src-orders",
      "batch_id": "b-001",
      "committed_cursor": "cur-010",
      "committed_at": "2026-10-04T10:05:00Z",
      "version_number": 1
    },
    {
      "checkpoint_id": "cp-002",
      "source_id": "src-orders",
      "batch_id": "b-002",
      "committed_cursor": "cur-010",
      "committed_at": "2026-10-04T12:05:00Z",
      "version_number": 2
    },
    {
      "checkpoint_id": "cp-101",
      "source_id": "src-refunds",
      "batch_id": "b-101",
      "committed_cursor": "cur-001",
      "committed_at": "2026-10-04T11:05:00Z",
      "version_number": 1
    }
  ],
  "model_definitions": [
    {
      "model_id": "m-stg-orders",
      "model_name": "stg_orders",
      "grain": "one row per source_key",
      "version_number": 1,
      "definition": "select record_id, quantity, unit_price, amount, event_ts from raw_accepted where source_id = 'src-orders'",
      "definition_hash": "5ccae027b232596af04c7553dcbf3a1b65b9ea984843acb0ea248244713cb207"
    },
    {
      "model_id": "m-sales-daily",
      "model_name": "sales_daily",
      "grain": "one row per record_id and UTC day",
      "version_number": 1,
      "definition": "select date(event_ts) as day, record_id, amount from stg_orders union all select date(event_ts), record_id, amount from stg_refunds",
      "definition_hash": "8168915abb4ff9507e86ddf50333a5f00d834cf6d1847574b153a004faf3d6d2"
    }
  ],
  "pipeline_runs": [
    {
      "run_id": "run-001",
      "started_at": "2026-10-04T10:10:00Z",
      "finished_at": "2026-10-04T10:30:00Z",
      "status": "success",
      "code_sha": "a1b2c3d",
      "backfill_id": null
    },
    {
      "run_id": "run-002",
      "started_at": "2026-10-04T12:10:00Z",
      "finished_at": "2026-10-04T12:20:00Z",
      "status": "failed",
      "code_sha": "a1b2c3d",
      "backfill_id": null
    },
    {
      "run_id": "run-003",
      "started_at": "2026-10-04T20:00:00Z",
      "finished_at": "2026-10-04T20:15:00Z",
      "status": "success",
      "code_sha": "a1b2c3d",
      "backfill_id": null
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
      "task_name": "transform",
      "status": "failed",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-001-3",
      "run_id": "run-001",
      "task_name": "transform",
      "status": "success",
      "attempt": "2"
    },
    {
      "task_run_id": "tr-001-4",
      "run_id": "run-001",
      "task_name": "quality_gate",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-001-5",
      "run_id": "run-001",
      "task_name": "publish",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-002-1",
      "run_id": "run-002",
      "task_name": "ingest",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-002-2",
      "run_id": "run-002",
      "task_name": "transform",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-002-3",
      "run_id": "run-002",
      "task_name": "quality_gate",
      "status": "failed",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-003-1",
      "run_id": "run-003",
      "task_name": "ingest",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-003-2",
      "run_id": "run-003",
      "task_name": "transform",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-003-3",
      "run_id": "run-003",
      "task_name": "quality_gate",
      "status": "success",
      "attempt": "1"
    },
    {
      "task_run_id": "tr-003-4",
      "run_id": "run-003",
      "task_name": "publish",
      "status": "success",
      "attempt": "1"
    }
  ],
  "quality_results": [
    {
      "quality_result_id": "qr-001-1",
      "task_run_id": "tr-001-4",
      "rule_name": "keys_unique",
      "severity": "critical",
      "eligible_count": 8,
      "failure_count": 0
    },
    {
      "quality_result_id": "qr-001-2",
      "task_run_id": "tr-001-4",
      "rule_name": "completeness_vs_expectation",
      "severity": "warning",
      "eligible_count": 9,
      "failure_count": 1
    },
    {
      "quality_result_id": "qr-002-1",
      "task_run_id": "tr-002-3",
      "rule_name": "keys_unique",
      "severity": "critical",
      "eligible_count": 9,
      "failure_count": 1
    },
    {
      "quality_result_id": "qr-002-2",
      "task_run_id": "tr-002-3",
      "rule_name": "completeness_vs_expectation",
      "severity": "warning",
      "eligible_count": 9,
      "failure_count": 1
    },
    {
      "quality_result_id": "qr-003-1",
      "task_run_id": "tr-003-3",
      "rule_name": "keys_unique",
      "severity": "critical",
      "eligible_count": 9,
      "failure_count": 0
    },
    {
      "quality_result_id": "qr-003-2",
      "task_run_id": "tr-003-3",
      "rule_name": "reconciliation_residual_zero",
      "severity": "critical",
      "eligible_count": 1,
      "failure_count": 0
    },
    {
      "quality_result_id": "qr-003-3",
      "task_run_id": "tr-003-3",
      "rule_name": "completeness_vs_expectation",
      "severity": "warning",
      "eligible_count": 9,
      "failure_count": 1
    }
  ],
  "publications": [
    {
      "publication_id": "pub-001",
      "run_id": "run-001",
      "dataset_name": "sales_daily",
      "published_at": "2026-10-04T10:30:00Z",
      "watermark": "2026-10-04T10:00:00Z",
      "source_ids": [
        "src-orders",
        "src-refunds"
      ],
      "included_batch_ids": [
        "b-001"
      ],
      "content_hash": "d4970d9ff7fcfd52465d20a68fa0a1e4d923900ae741914c599c8b6f3c5312b1"
    },
    {
      "publication_id": "pub-003",
      "run_id": "run-003",
      "dataset_name": "sales_daily",
      "published_at": "2026-10-04T20:15:00Z",
      "watermark": "2026-10-04T11:00:00Z",
      "source_ids": [
        "src-orders",
        "src-refunds"
      ],
      "included_batch_ids": [
        "b-001",
        "b-002",
        "b-101"
      ],
      "content_hash": "2f99e5b9b102d612edb60b4ce4415481273dd2889096d73f51441b4020a15b9c"
    }
  ],
  "incidents": [
    {
      "incident_id": "inc-001",
      "run_id": "run-002",
      "severity": "high",
      "status": "closed",
      "opened_at": "2026-10-04T12:20:00Z",
      "closed_at": "2026-10-04T20:15:00Z",
      "recovery_run_id": "run-003"
    }
  ],
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
    }
  ]
}
`;export{n as default};
