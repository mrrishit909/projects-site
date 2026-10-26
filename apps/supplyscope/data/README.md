# SupplyScope data layer

* `migrations/0001_schema.sql` tables for every entity (TIMESTAMPTZ everywhere, money NUMERIC(14,2)) plus
  `backorders`, `reservations`, `replenishment_params`, `cost_versions` (D-05), `lost_sales`, `calendar_closures`,
  `latent_demand`, the derived `stock_snapshots` and `draft_orders`, `fixture_states`, and the operational tables
  `raw_batches`, `rejected_records` (with an `ordinal` so two rejected occurrences of one id both survive),
  `quarantined_records`, `audit_events`, `command_results` (with `actor_id`), `dataset_versions`.
* `migrations/0002_constraints.sql` CHECKs and triggers: `inventory_movements` is immutable (UPDATE, DELETE and TRUNCATE
  are refused) with `UNIQUE (movement_id)`; `receipts` need `received_quantity > 0`, a trigger refuses a receipt dated before
  its order and one that would exceed the ordered quantity (the line is locked); a purchase order with receipts cannot be
  re-dated; a backorder and a lost sale cannot share a `demand_ref`; `draft_orders.status` is always `draft` and the order
  quantity a whole number of packs; `audit_events` is append-only.
* `migrate.py [--reset]` applies the files in order, records checksums in `schema_migrations`, refuses a changed file.
* `seed.py <inputs.json>` loads a fixture through the domain's `validate_batch`; rejected rows are kept in
  `rejected_records` under one `raw_batches` row; the fixture's named states go to `fixture_states`. Running it twice
  inserts nothing.
* `sql/reference_metrics.sql` recomputes every metric of `expected.json` in plain SQL (no code shared with the domain):
  on hand as of the cutoff with the day order receipts, sales, review via a sort key on (date, movement type rank,
  event_at, movement_id); on order, open backorders, reserved, position; replenishment with MOQ and pack rounding as SQL
  expressions; fill rate, stockout days, working capital at the cost in force. Parameters `%(as_of)s`,
  `%(window_start)s`, `%(window_end)s` (NULL = up to as_of).
  Purchase order lines carry no location: a product's open quantity counts at its first parameter location (else its first
  movement location), in the SQL and in the domain alike.
