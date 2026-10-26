# Revenue Atlas data layer

PostgreSQL 16, plain SQL migrations, no ORM. Contract: `docs/contracts.md` (money `NUMERIC(20,6)`,
D-04 allocation keyed by `shipment_line_id`).

| File | Purpose |
|---|---|
| `migrations/0001_schema.sql` | Tables for every `inputs.json` entity, plus `raw_batches`, `rejected_records`, `quarantined_records`, `freight_allocations`, `discount_allocations`, `audit_events`, `command_results`, `dataset_versions`. |
| `migrations/0002_constraints.sql` | Foreign keys, CHECKs (ISO-style currency, quantity, `credit_amount >= 0`), append-only triggers on `returns` and `audit_events`, indexes. No exclusion constraint on `cost_versions`: overlaps must be storable so C02 can quarantine them. |
| `migrations/0003_shipment_invariants.sql` | Triggers for the per-line invariants (R-01, R-06, D-08): shipped quantity of an order line never exceeds its ordered quantity; a shipment line belongs to its shipment's order. |
| `migrate.py` | Applies migrations in order, records them (with checksum) in `schema_migrations`. Safe on an empty database and on a second run. `--reset` drops only this project's tables first. |
| `seed.py` | Loads an `inputs.json` (rows pass the domain's `validate_batch`), `ON CONFLICT DO NOTHING`, and records a `dataset_versions` row (`dataset_hash` = sha256 of the canonical JSON). |
| `sql/reference_totals.sql` | Independent SQL recomputation of ten money metrics, with its own largest-remainder logic. Parameters `%(lo)s`, `%(hi)s` (timestamptz or NULL, window `[lo, hi)`). |

```sh
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/revenue_atlas
python data/migrate.py            # add --reset to start clean
python data/seed.py tests/fixtures/golden/inputs.json
PYTHONPATH=domain uvicorn --factory api.app:create_app
```

Design notes

* P01-TEST-01: `freight_allocations.shipment_line_id` is the PRIMARY KEY, so a second allocation of the
  same line fails in the database; C04 turns that into `409 FREIGHT_ALREADY_ALLOCATED` with the whole
  transaction rolled back.
* `shipment_lines.version` is the optimistic-concurrency counter (C03 bumps it); `returns` is append-only.
* `cost_version_id` is NULL until C02 sets it and is never changed afterwards (D-03).
* `reference_totals.sql` reads the stored `cost_version_id`, so run C02 first; uncosted lines are
  treated as quarantined and excluded, exactly as the pipeline excludes them.
* Tests (`tests/`) reset and re-migrate the schema per test and skip when `DATABASE_URL` is unset.
