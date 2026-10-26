# ServiceFlow data layer

* `python data/migrate.py [--reset]` applies `migrations/*.sql` in order (idempotent; a changed applied file is refused; `--reset` drops only this
  project's tables and functions). `python data/seed.py tests/fixtures/golden/inputs.json` loads a fixture through the domain's `validate_batch`
  (rejected rows go to `rejected_records` with the raw row), runs every accepted simulation once and stores its events in `simulation_events`;
  loading twice changes nothing.
* **Schema** (`0001`): customers, queues, agents (`max_concurrent` default 1), skills, agent_skills, queue_skills, shifts, shift_breaks, sla_policies,
  tickets (`queue_id` is the current queue, `created_at` the arrival), ticket_events, surveys, simulation_runs, simulation_events, raw_batches,
  rejected_records, audit_events, command_results (`actor_id`), dataset_versions. All instants are `TIMESTAMPTZ` (UTC).
* **Constraints** (`0002`): `ticket_events` is immutable (UPDATE, DELETE and TRUNCATE are refused) with `UNIQUE (event_id)` and `event_seq` for insertion
  order; a `replied_human` event cannot carry a bot actor; `service_started` needs an agent; `shifts` `CHECK (ends_at > starts_at)`, `break_minutes >= 0`
  and not longer than the shift; `tickets.created_at` can never change (a transfer changes only `queue_id`); `audit_events` and `simulation_events` are
  append-only. **No overlap trigger**: concurrency per agent is an application check (reason in the migration header).
* **`sql/reference_metrics.sql`** is an independent recomputation of every metric of `expected.json` from the event log with window functions
  (per-ticket first human response, wait, resolution; service intervals by lag/lead; P90 by nearest rank `ceil(9n/10)`; SLA; staffed minutes; occupancy).
  Parameters: `%(w0)s`, `%(w1)s`, `%(cutoffs)s` (timestamptz[]), `%(abandonable)s` (text[]). `tests/test_sql_reference.py` checks it against the golden fixtures,
  the Python domain on a richer history (reopen, transfer, pause, abandonment) and several windows.
