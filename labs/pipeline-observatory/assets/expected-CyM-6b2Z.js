const n=`{
  "contract_version": 1,
  "as_of": "2026-10-05T00:00:00Z",
  "cutoff": "2026-10-05T00:00:00Z",
  "empty_population": false,
  "ingest": {
    "counts": {
      "source_contracts": {
        "accepted": 1,
        "rejected": 0
      },
      "ingestion_batches": {
        "accepted": 2,
        "rejected": 1
      },
      "raw_records": {
        "accepted": 4,
        "rejected": 2
      },
      "quarantine_records": {
        "accepted": 1,
        "rejected": 0
      },
      "checkpoints": {
        "accepted": 2,
        "rejected": 1
      },
      "model_definitions": {
        "accepted": 0,
        "rejected": 0
      },
      "pipeline_runs": {
        "accepted": 1,
        "rejected": 1
      },
      "task_runs": {
        "accepted": 2,
        "rejected": 2
      },
      "quality_results": {
        "accepted": 1,
        "rejected": 2
      },
      "publications": {
        "accepted": 1,
        "rejected": 0
      },
      "incidents": {
        "accepted": 0,
        "rejected": 0
      },
      "backfill_requests": {
        "accepted": 2,
        "rejected": 1
      }
    },
    "rejected_records": [
      {
        "entity": "ingestion_batches",
        "id": "b-003",
        "status": "rejected",
        "reason_code": "DEPENDENT_REJECTED",
        "raw_row": {
          "batch_id": "b-003",
          "source_id": "src-orders",
          "source_cursor": "cur-006",
          "started_at": "2026-10-04T11:00:00Z",
          "status": "committed"
        }
      },
      {
        "entity": "raw_records",
        "id": "rr-b-003-01",
        "status": "rejected",
        "reason_code": "DEPENDENT_REJECTED",
        "raw_row": {
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
        }
      },
      {
        "entity": "raw_records",
        "id": "rr-b-003-02",
        "status": "rejected",
        "reason_code": "DEPENDENT_REJECTED",
        "raw_row": {
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
      },
      {
        "entity": "checkpoints",
        "id": "cp-003",
        "status": "rejected",
        "reason_code": "CHECKPOINT_REGRESSION",
        "raw_row": {
          "checkpoint_id": "cp-003",
          "source_id": "src-orders",
          "batch_id": "b-003",
          "committed_cursor": "cur-009",
          "committed_at": "2026-10-04T11:05:00Z",
          "version_number": 1
        }
      },
      {
        "entity": "pipeline_runs",
        "id": "run-bf-2",
        "status": "rejected",
        "reason_code": "DEPENDENT_REJECTED",
        "raw_row": {
          "run_id": "run-bf-2",
          "started_at": "2026-10-04T13:00:00Z",
          "finished_at": "2026-10-04T13:10:00Z",
          "status": "success",
          "code_sha": "a1b2c3d",
          "backfill_id": "bf-002"
        }
      },
      {
        "entity": "task_runs",
        "id": "tr-001-2",
        "status": "rejected",
        "reason_code": "DUPLICATE_ID",
        "raw_row": {
          "task_run_id": "tr-001-2",
          "run_id": "run-001",
          "task_name": "ingest",
          "status": "success",
          "attempt": "1"
        }
      },
      {
        "entity": "task_runs",
        "id": "tr-bf2-1",
        "status": "rejected",
        "reason_code": "DEPENDENT_REJECTED",
        "raw_row": {
          "task_run_id": "tr-bf2-1",
          "run_id": "run-bf-2",
          "task_name": "ingest",
          "status": "success",
          "attempt": "1"
        }
      },
      {
        "entity": "quality_results",
        "id": "qr-001-2",
        "status": "rejected",
        "reason_code": "DEPENDENT_REJECTED",
        "raw_row": {
          "quality_result_id": "qr-001-2",
          "task_run_id": "tr-001-2",
          "rule_name": "keys_unique",
          "severity": "critical",
          "eligible_count": 3,
          "failure_count": 0
        }
      },
      {
        "entity": "quality_results",
        "id": "qr-bf2-1",
        "status": "rejected",
        "reason_code": "DEPENDENT_REJECTED",
        "raw_row": {
          "quality_result_id": "qr-bf2-1",
          "task_run_id": "tr-bf2-1",
          "rule_name": "keys_unique",
          "severity": "critical",
          "eligible_count": 1,
          "failure_count": 0
        }
      },
      {
        "entity": "backfill_requests",
        "id": "bf-002",
        "status": "rejected",
        "reason_code": "BACKFILL_OVERLAP",
        "raw_row": {
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
        }
      }
    ]
  },
  "metrics": {
    "ingestion": {
      "sources": {
        "src-orders": {
          "batches": {
            "b-001": {
              "status": "committed",
              "counted": true,
              "written_rows": 3,
              "received": 3,
              "accepted_unique": 2,
              "duplicate": 0,
              "quarantined": 1,
              "rejection_rate": "0.333333",
              "duplicate_rate": "0.000000",
              "quarantine_rows_match": true
            },
            "b-002": {
              "status": "committed",
              "counted": true,
              "written_rows": 1,
              "received": 1,
              "accepted_unique": 1,
              "duplicate": 0,
              "quarantined": 0,
              "rejection_rate": "0.000000",
              "duplicate_rate": "0.000000",
              "quarantine_rows_match": true
            }
          },
          "received": 4,
          "accepted_unique": 3,
          "duplicate": 0,
          "quarantined": 1,
          "quarantined_distinct_keys": 1,
          "rejection_rate": "0.250000",
          "duplicate_rate": "0.000000",
          "quarantine_by_reason": {
            "NEGATIVE_QUANTITY": 1
          },
          "checkpoint": {
            "committed_version": 2,
            "committed_cursor": "cur-006",
            "committed_batch_id": "b-002",
            "uncommitted_batches": [],
            "uncommitted_batches_with_checkpoint": 0
          }
        }
      },
      "overall": {
        "received": 4,
        "accepted_unique": 3,
        "duplicate": 0,
        "quarantined": 1,
        "rejection_rate": "0.250000",
        "duplicate_rate": "0.000000"
      }
    },
    "freshness": {
      "src-orders": {
        "latest_accepted_event_at": "2026-10-04T09:30:00Z",
        "freshness_seconds": 52200,
        "last_successful_ingestion_at": "2026-10-04T10:05:00Z",
        "ingestion_age_seconds": 50100
      }
    },
    "completeness": {
      "src-orders": {
        "2026-10-04": {
          "expected_records": 4,
          "accepted_records": 3,
          "value": "0.750000"
        }
      }
    },
    "runs": {
      "runs": {
        "run-001": {
          "status": "success",
          "duration_seconds": 1200,
          "tasks": {
            "ingest": {
              "attempts": 1,
              "final_status": "success"
            },
            "quality_gate": {
              "attempts": 1,
              "final_status": "success"
            }
          },
          "tasks_terminal": 2,
          "tasks_successful": 2,
          "task_success_rate": "1.000000",
          "attempts": 2,
          "attempts_successful": 2,
          "attempt_success_rate": "1.000000"
        }
      },
      "overall": {
        "tasks_terminal": 2,
        "tasks_successful": 2,
        "task_success_rate": "1.000000",
        "attempts": 2,
        "attempts_successful": 2,
        "attempt_success_rate": "1.000000"
      },
      "durations": {
        "successful": {
          "count": 1,
          "durations_seconds": [
            1200
          ],
          "mean_minutes": "20.0000"
        },
        "failed": {
          "count": 0,
          "durations_seconds": [],
          "mean_minutes": null
        }
      }
    },
    "quality_gate": {
      "run-001": {
        "results": {
          "keys_unique": {
            "severity": "critical",
            "eligible": 3,
            "failures": 0,
            "passed": true
          }
        },
        "critical_failures": 0,
        "noncritical_failures": 0,
        "decision": "allowed"
      }
    },
    "publications": {
      "current_publication_id": "pub-001",
      "pointer_history": [
        {
          "run_id": "run-001",
          "gate_decision": "allowed",
          "pointer_after": "pub-001"
        }
      ],
      "publications": {
        "pub-001": {
          "run_id": "run-001",
          "published_at": "2026-10-04T11:30:00Z",
          "watermark": "2026-10-04T10:30:00Z",
          "included_batches": [
            "b-001",
            "b-002"
          ],
          "published_records": 3,
          "latest_included_event_at": "2026-10-04T09:30:00Z",
          "lag_seconds": 7200,
          "content_hash_ok": true
        }
      }
    },
    "late_events": {
      "count": 0,
      "included_in_next_publication": 0,
      "lost": 0,
      "events": []
    },
    "reconciliation": {
      "pub-001": {
        "source_total": "29.50",
        "published_total": "37.50",
        "exclusions": {
          "quarantined": "-8.00",
          "duplicates": "0.00",
          "deletes": "0.00"
        },
        "exclusions_total": "-8.00",
        "residual": "0.00"
      }
    },
    "incidents": {
      "total": 0,
      "open": 0,
      "closed": 0,
      "verified": 0,
      "mean_recovery_minutes": null,
      "incidents": {}
    },
    "backfills": {
      "requests": {
        "bf-001": {
          "source_id": "src-orders",
          "start_at": "2026-09-01T00:00:00Z",
          "end_at": "2026-09-04T00:00:00Z",
          "requested_partitions": 3,
          "verified_partitions": 2,
          "coverage": "0.666667"
        },
        "bf-003": {
          "source_id": "src-orders",
          "start_at": "2026-09-04T00:00:00Z",
          "end_at": "2026-09-05T00:00:00Z",
          "requested_partitions": 1,
          "verified_partitions": 0,
          "coverage": "0.000000"
        }
      },
      "refused": [
        "bf-002"
      ],
      "overall": {
        "requested_partitions": 4,
        "verified_partitions": 2,
        "coverage": "0.500000"
      }
    },
    "processing_rate": {
      "accepted_records": 2,
      "measured_seconds": "6",
      "records_per_second": "0.333333",
      "hardware": "Synthetic fixture value, not a benchmark: 2 vCPU, 8 GB RAM, GitHub-hosted runner class",
      "cache_state": "warm"
    }
  }
}
`;export{n as default};
