# Data dictionary: SupplyScope relational model (P03-ART-03)

All data in this model is **synthetic**: the golden fixture `supplyscope-golden-v1` and the generated snapshot `ss-20261026-20261026` (seed 20261026, generator `dataset_hash` `5bdabb50eea4b192e3b17e1e5b1a79dc6b26feb4a2b8b78ad094acde9f8bcc8c`, contract v1). The company "Northgate Components" and its suppliers do not exist. Sources: `data/migrations/0001_schema.sql` and `0002_constraints.sql`, `data/migrate.py`, `data/seed.py`, `docs/contracts.md` (rules cited as D-01..D-06), `docs/api-contract.md` (commands C01..C10), `data/README-generator.md`. The ER diagram is `erd.md`.

Row counts are `SELECT count(*)` on scratch databases prepared by `data/sql/analysis/prepare_snapshot.py` (migrate, then `seed.py` through the domain's `validate_batch` over `web/public/data`): the snapshot database holds 10,913 of the 10,916 generated movements and 1,308 of the 1,309 receipts; **4 rows were rejected** (3 duplicate movement replays and 1 receipt before its order) and kept in `rejected_records`. The golden database holds the fixture (7 movements, 1 order, 1 line, 2 backorders, 1 parameter row).

Conventions: all instants are `TIMESTAMPTZ` read as UTC (D-01); dates (`DATE`) are UTC calendar dates; money is `NUMERIC(14,2)`, rates are computed (6 dp, ROUND_HALF_UP) and not stored; ids are `TEXT` keys supplied by the source. "FK" means a foreign key enforced in `0001`; "logical" means a join the contract relies on that the database does not enforce. Constraint and trigger names are those of `0002`. **Kinds:** *source* = loaded from the entity files (`inputs.json` entities), *derived* = written by a command or computed from source rows, *operational* = ingestion, idempotency, audit.

## 1. Tables, grain, keys and update semantics

| Table | Kind | Grain | Primary key | Rows (snapshot DB) | Rows (golden DB) | Update semantics |
|---|---|---|---|---|---|---|
| `suppliers` | source | one supplier | `supplier_id` | 4 | 1 | Insert-only through the seed. `quoted_lead_days` is the promise the on-time rate is measured against (D-04). Not versioned: a change would rewrite history. |
| `products` | source | one SKU | `product_id`; unique `sku` | 60 | 1 | Insert-only through the seed. `unit_cost` is the cost BEFORE any `cost_versions` row (D-05). `supplier_id` is NULL in the snapshot (open S-02, section 6): the supplier of a product is read from `replenishment_params`. |
| `locations` | source | one stocking location | `location_id` | 3 | 1 | Insert-only. `storage_capacity` binds orders at `loc-02` in the generator (62 % of the summed targets) but is not a rule of the draft-order arithmetic. |
| `calendar_closures` | source | one closed date range of one supplier calendar | `closure_id` | 1 | 0 | Insert-only. Closed days do not count towards lead days (P03-TEST-05); `closures_range_ck` forbids `closed_to < closed_from`. One row in the snapshot: `cal-02` 2026-01-05 .. 2026-01-18. |
| `cost_versions` | source | one unit cost effective from one instant for one product | `cost_version_id`; unique `(product_id, effective_from)` | 15 | 0 | Insert-only. The cost in force on a date is the latest `effective_from` (UTC date) on or before it, else `products.unit_cost` (D-05). |
| `policy_scenarios` | source | one simulation scenario | `scenario_id` | 4 | 0 | Insert-only. `unmet_policy` is `lost_sale` OR `backlog`, never both (P03-TEST-08); the seed, warm-up days and replications are declared here (P03-DOMAIN-05). |
| `purchase_orders` | source | one purchase order header | `purchase_order_id` | 998 | 1 | `status` is the CURRENT status (`confirmed`, `cancelled`, `closed`) and is updated in place, so it is not an as-of fact: query 01 counts every order that is not cancelled. A trigger refuses to re-date an order that has receipts. A purchase order is a recommendation record in this model, never a supplier commitment. |
| `purchase_order_lines` | source | one SKU line of one order | `po_line_id` | 1,282 | 1 | Insert-only. A line has no location; its open quantity counts at the product's home location (first `replenishment_params` row). Open quantity = `ordered_quantity` - received, never below 0. |
| `receipts` | source | one receipt of part or all of one line | `receipt_id` | 1,308 | 0 | Insert-only. Trigger `receipts_rules` refuses a receipt dated before its order (`RECEIPT_BEFORE_ORDER`) and one that would exceed the ordered quantity (`RECEIPT_EXCEEDS_ORDERED`); the line row is locked. A partial receipt leaves the line open. |
| `inventory_movements` | source | one posted stock movement (an immutable event) | `movement_id` (also `UNIQUE`) | 10,913 | 7 | **Immutable**: trigger `inventory_movements_immutable` refuses UPDATE and DELETE, `inventory_movements_no_truncate` refuses TRUNCATE. A duplicate `movement_id` is rejected at load (`DUPLICATE_MOVEMENT_ID`). Sale movements outnumber `sales` rows by the 358 units of backlog fills (movement without a `sales` row). |
| `sales` | source | one sale (SKU x location x day aggregate in the snapshot) | `sale_id` | 9,475 | 4 | Insert-only. Observed sales are censored by stockouts; `latent_demand` is the separate published truth (D-03). |
| `promotions` | source | one promotion window of one SKU | `promotion_id` | 45 | 0 | Insert-only. `planned_uplift` and `announced_at` are the schedule, known when announced; `realised_uplift` is an OUTCOME and never a forecast feature (P03-TEST-02). |
| `latent_demand` | source | one SKU x location x day of latent demand (positive days only) | `(product_id, location_id, demand_date)` | 6,380 | 0 | Insert-only. The generator's published truth, 27 pairs (class A, promoted and intermittent); an absent day is 0. Never used as a forecast input. |
| `forecast_runs` | derived | one forecast fit for one SKU x location at one cutoff | `forecast_run_id` | 56 | 0 | Written by C03 forecast-demand (and loaded from the snapshot). The columns `information_hash`, `model_report` and `notes` are NULL in the seeded snapshot (the seed loads six columns); C03 fills them. `selected_model` comes from a rolling-origin backtest and is a model other than seasonal-naive only when it beats it (D-03). |
| `forecast_points` | derived | one forecast value for one run, model and target date | `forecast_point_id`; unique `(forecast_run_id, model, target_date)` | 2,352 | 0 | Written with its run. 56 runs x 14 days x 3 models would be 2,352: 14 pairs x 4 cutoffs x 14 days x 3 models. |
| `backorders` | source | one unmet-demand event recorded as a backorder | `backorder_id`; unique `demand_ref` | 70 | 2 | `closed_at` NULL means open; `closed_at >= opened_at`. Trigger `backorders_xor` refuses a `demand_ref` already recorded as a lost sale (P03-TEST-08). Only `loc-03` uses the backlog policy in the snapshot. |
| `lost_sales` | source | one unmet-demand event recorded as a lost sale | `lost_sale_id`; unique `demand_ref` | 361 | 0 | Insert-only; mirror of `backorders` for the lost-sale policy (`loc-01`, `loc-02`). |
| `reservations` | source | one reservation of stock | `reservation_id` | 16 | 0 | `released_at` NULL means open. Reserved reduces AVAILABLE, never the inventory position (P03-TEST-10); 6 are open at the snapshot cutoff (INJ-07). |
| `replenishment_params` | source | reorder parameters of one SKU at one location | `(product_id, location_id)` | 60 | 1 | Insert-only. In the snapshot `supplier_id` is stated here (not on `products`). `reorder_point` and `target_position` are the parameters of record (`parameter_source = 'params'` in drafts). |
| `stock_snapshots` | derived | one reconstructed stock row per as-of instant, SKU and location | `(as_of, product_id, location_id)` | 0 | 0 | Written (upserted) by C02 reconstruct-stock; empty in the seeded snapshot. `on_hand` is `on_hand_raw` floored at 0; `negative_stock` and `flags` carry `NEGATIVE_STOCK`. |
| `draft_orders` | derived | one draft buying recommendation for one SKU x location at one as-of instant (and scenario) | `draft_order_id` | 0 | 0 | Written (upserted) by C05 calculate-replenishment only for triggered rows; empty in the seeded snapshot. `status` is always `draft` (CHECK) and the quantity a whole number of packs (CHECK). Exported as CSV by C10, never submitted anywhere. |
| `fixture_states` | operational | one named fixture state (extra order lines) | `state_name` | 0 | 2 | Loaded by the seed from `inputs.json` `states` so a state such as `position_80` can be requested by name. Empty for the generated snapshot. |
| `raw_batches` | operational | one received input batch | `batch_id`; unique `idempotency_key` | 1 | 0 | Insert-only; `status` in `accepted`, `partial`, `rejected`. The whole payload is kept as `JSONB` with its hash. |
| `rejected_records` | operational | one raw row refused at load | `(batch_id, entity, id, reason_code, ordinal)` | 4 | 0 | Insert-only. `raw_row` keeps the row as it arrived; `ordinal` separates two rejected occurrences of one id. |
| `quarantined_records` | operational | one record held back for repair | `(entity, id)` | 0 | 0 | Reserved; nothing writes to it in the slice (the load rejects rather than quarantines). Exposed by the reads API. |
| `audit_events` | operational | one audit line per accepted command | `event_id` | 0 | 0 | **Append-only** (`audit_events_append_only`). Written in the SAME transaction as the command it records, so an audit line exists exactly when the effect does (atomic audit). |
| `command_results` | operational | one stored result per idempotency key | `idempotency_key` | 0 | 0 | Insert-only. The same key, payload and actor replays the stored result; another payload or actor is a 409 `IDEMPOTENCY_KEY_REUSED`. |
| `dataset_versions` | operational | one seeded dataset | `dataset_version` | 1 | 1 | Insert-only. The seed hashes the INPUT JSON (`ds-<12 hex>`), which is not the generator's file hash in `manifest.json` (`ss-20261026-20261026`, `5bdabb50...`); see section 6. |
| `schema_migrations` | operational | one applied migration (created by `data/migrate.py`, not by the SQL files) | `version` | 2 | 2 | Holds the sha256 of each applied file; a changed file is refused. |

Immutable and append-only: `inventory_movements` (UPDATE, DELETE and TRUNCATE refused), `audit_events` (UPDATE and DELETE refused). Draft orders are **drafts**: `draft_orders` rows are upserted by C05 until exported, carry `status = 'draft'` forever, and are never a purchase order. Everything else is insert-only in the slice.

## 2. Columns

Type is the PostgreSQL type of `0001_schema.sql`; Null is whether the column accepts NULL; Source is the entity-file field the seed loads it from (`web/public/data/<entity>.json`, same field names as `tests/fixtures/golden/inputs.json`) or how it is produced.

### suppliers
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `supplier_id` | TEXT | no | Key | suppliers.supplier_id |
| `supplier_name` | TEXT | no | Display name (synthetic) | suppliers.supplier_name |
| `calendar_id` | TEXT | no | Supplier calendar; the join to `calendar_closures.calendar_id` is logical, not a foreign key | suppliers.calendar_id |
| `quoted_lead_days` | INT | no | Promised lead time in supplier-calendar days (5 / 12 / 9 / 21); `>= 0` (`suppliers_lead_ck`) | suppliers.quoted_lead_days |
| `active` | BOOLEAN | no | Whether the supplier can be ordered from | suppliers.active |

### products
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `product_id` | TEXT | no | Key | products.product_id |
| `sku` | TEXT | no | Business key, unique | products.sku |
| `unit_cost` | NUMERIC(14,2) | no | Cost before any cost version, `>= 0` (`products_cost_ck`) | products.unit_cost |
| `pack_size` | INT | no | Units per pack, `>= 1` (`products_pack_ck`); orders are whole packs | products.pack_size |
| `minimum_order_quantity` | INT | no | MOQ, `>= 0` (`products_moq_ck`); applied BEFORE pack rounding | products.minimum_order_quantity |
| `abc_class` | TEXT | yes | `A`, `B` or `C` (8 / 16 / 36); NULL allowed (unclassified); C04 would set it (501 in the slice) | products.abc_class |
| `supplier_id` | TEXT | yes | Optional FK to `suppliers`; NULL in the snapshot (S-02) | omitted by the generator |

### locations
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `location_id` | TEXT | no | Key | locations.location_id |
| `location_name` | TEXT | no | Display name | locations.location_name |
| `timezone` | TEXT | no | IANA zone of the site; day order and date bucketing use UTC (D-01), so it is descriptive | locations.timezone |
| `storage_capacity` | INT | no | Units the site can hold, `>= 0` | locations.storage_capacity |
| `active` | BOOLEAN | no | Whether the site is in use | locations.active |

### calendar_closures
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `closure_id` | TEXT | no | Key | calendar_closures.closure_id |
| `calendar_id` | TEXT | no | Supplier calendar closed (logical join to `suppliers.calendar_id`) | calendar_closures.calendar_id |
| `closed_from` | DATE | no | First closed date, inclusive | calendar_closures.closed_from |
| `closed_to` | DATE | no | Last closed date, inclusive, `>= closed_from` | calendar_closures.closed_to |

### cost_versions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `cost_version_id` | TEXT | no | Key | cost_versions.cost_version_id |
| `product_id` | TEXT | no | FK to `products` | cost_versions.product_id |
| `unit_cost` | NUMERIC(14,2) | no | Cost from `effective_from`, `>= 0` | cost_versions.unit_cost |
| `effective_from` | TIMESTAMPTZ | no | Instant the cost takes effect (compared as a UTC date) | cost_versions.effective_from |

### policy_scenarios
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `scenario_id` | TEXT | no | Key | policy_scenarios.scenario_id |
| `scenario_name` | TEXT | no | Display name | policy_scenarios.scenario_name |
| `service_target` | NUMERIC(4,2) | no | Service level, 0 < x < 1 (`scenarios_target_ck`); 0.95 or 0.98 in the snapshot | policy_scenarios.service_target |
| `unmet_policy` | TEXT | no | `lost_sale` or `backlog` (`scenarios_policy_ck`) | policy_scenarios.unmet_policy |
| `seed` | BIGINT | no | Random seed shared by every policy (common random numbers, P03-FLOW-08); 20261026 | policy_scenarios.seed |
| `warmup_days` | INT | no | Days discarded before measuring, `>= 0`; 28 | policy_scenarios.warmup_days |
| `replications` | INT | no | Replications, `>= 1`; 100 | policy_scenarios.replications |

### purchase_orders
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `purchase_order_id` | TEXT | no | Key | purchase_orders.purchase_order_id |
| `supplier_id` | TEXT | no | FK to `suppliers` | purchase_orders.supplier_id |
| `ordered_at` | TIMESTAMPTZ | no | Order instant; receipts may not precede it | purchase_orders.ordered_at |
| `status` | TEXT | no | `confirmed`, `cancelled` or `closed` (`po_status_ck`); current status, not as-of | purchase_orders.status |
| `currency` | TEXT | no | ISO currency; `USD` | purchase_orders.currency |

### purchase_order_lines
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `po_line_id` | TEXT | no | Key | purchase_order_lines.po_line_id |
| `purchase_order_id` | TEXT | no | FK to `purchase_orders` | purchase_order_lines.purchase_order_id |
| `product_id` | TEXT | no | FK to `products` | purchase_order_lines.product_id |
| `ordered_quantity` | INT | no | Units ordered, `> 0` (`po_lines_qty_ck`) | purchase_order_lines.ordered_quantity |
| `unit_cost` | NUMERIC(14,2) | no | Cost at order time, `>= 0` (a cost step later does not rewrite it) | purchase_order_lines.unit_cost |

### receipts
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `receipt_id` | TEXT | no | Key | receipts.receipt_id |
| `po_line_id` | TEXT | no | FK to `purchase_order_lines` | receipts.po_line_id |
| `location_id` | TEXT | no | FK to `locations`: where the units arrived | receipts.location_id |
| `received_quantity` | INT | no | Units received, `> 0` (`receipts_qty_ck`) | receipts.received_quantity |
| `received_at` | TIMESTAMPTZ | no | Receipt instant, `>= ordered_at` | receipts.received_at |

### inventory_movements
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `movement_id` | TEXT | no | Key (also unique): a replay is rejected | inventory_movements.movement_id |
| `product_id` | TEXT | no | FK to `products` | inventory_movements.product_id |
| `location_id` | TEXT | no | FK to `locations` | inventory_movements.location_id |
| `quantity_delta` | INT | no | Signed units, `<> 0` (`movements_delta_ck`); receipts and returns are positive, sales negative (`movements_sign_ck`) | inventory_movements.quantity_delta |
| `event_at` | TIMESTAMPTZ | no | Instant posted; the day order sorts by its UTC date, then type, then this instant | inventory_movements.event_at |
| `movement_type` | TEXT | no | `receipt`, `sale`, `adjustment`, `review` or `return` (`movements_type_ck`); rank 0 / 1 / 2 in the day order | inventory_movements.movement_type |

### sales
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `sale_id` | TEXT | no | Key | sales.sale_id |
| `product_id` | TEXT | no | FK to `products` | sales.product_id |
| `location_id` | TEXT | no | FK to `locations` | sales.location_id |
| `sold_at` | TIMESTAMPTZ | no | Instant of the sale | sales.sold_at |
| `quantity` | INT | no | Units sold immediately, `> 0` (`sales_qty_ck`) | sales.quantity |

### promotions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `promotion_id` | TEXT | no | Key | promotions.promotion_id |
| `product_id` | TEXT | no | FK to `products` | promotions.product_id |
| `location_id` | TEXT | yes | Optional FK to `locations` (NULL = all) | promotions.location_id |
| `starts_at` | TIMESTAMPTZ | no | Window start | promotions.starts_at |
| `ends_at` | TIMESTAMPTZ | no | Window end, `>= starts_at` | promotions.ends_at |
| `planned_uplift` | NUMERIC(8,4) | no | Scheduled uplift, `>= 0`, known when announced | promotions.planned_uplift |
| `announced_at` | TIMESTAMPTZ | no | When the schedule became known (the information cutoff for forecasts) | promotions.announced_at |
| `realised_uplift` | NUMERIC(8,4) | yes | Outcome after the window; never a forecast feature | promotions.realised_uplift |

### latent_demand
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `product_id` | TEXT | no | FK to `products` | latent_demand.product_id |
| `location_id` | TEXT | no | FK to `locations` | latent_demand.location_id |
| `demand_date` | DATE | no | UTC date | latent_demand.demand_date |
| `latent_quantity` | INT | no | Units the customers wanted, `>= 0` | latent_demand.latent_quantity |

### forecast_runs
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `forecast_run_id` | TEXT | no | Key | forecast_runs.forecast_run_id |
| `product_id` | TEXT | no | FK to `products` | forecast_runs.product_id |
| `location_id` | TEXT | no | FK to `locations` | forecast_runs.location_id |
| `cutoff` | TIMESTAMPTZ | no | Information cutoff: only data known at this instant may be used | forecast_runs.cutoff |
| `horizon_days` | INT | no | Days forecast, `>= 1`; 14 | forecast_runs.horizon_days |
| `selected_model` | TEXT | no | `naive`, `seasonal_naive` or `ewma` | forecast_runs.selected_model |
| `information_hash` | TEXT | yes | Hash of the information used; NULL in the seeded snapshot | written by C03 |
| `model_report` | JSONB | yes | Per-model folds, WAPE, MAE; NULL in the seeded snapshot | written by C03 |
| `notes` | JSONB | yes | Disclosures such as zero-demand folds; NULL in the seeded snapshot | written by C03 |
| `created_at` | TIMESTAMPTZ | no | Insert time (`now()`), not deterministic | database default |

### forecast_points
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `forecast_point_id` | TEXT | no | Key | forecast_points.forecast_point_id |
| `forecast_run_id` | TEXT | no | FK to `forecast_runs` | forecast_points.forecast_run_id |
| `model` | TEXT | no | Model that produced the value | forecast_points.model |
| `target_date` | DATE | no | UTC date forecast; always after the run's cutoff date | forecast_points.target_date |
| `forecast_value` | NUMERIC(14,2) | no | Units, `>= 0` (`forecast_points_ck`), 2 dp | forecast_points.forecast_value |

### backorders
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `backorder_id` | TEXT | no | Key | backorders.backorder_id |
| `product_id` | TEXT | no | FK to `products` | backorders.product_id |
| `location_id` | TEXT | no | FK to `locations` | backorders.location_id |
| `quantity` | INT | no | Units owed, `> 0` | backorders.quantity |
| `opened_at` | TIMESTAMPTZ | no | Instant the shortfall was recorded; a stockout day is its UTC date (D-06) | backorders.opened_at |
| `closed_at` | TIMESTAMPTZ | yes | Instant it was filled; NULL = open | backorders.closed_at |
| `scenario_id` | TEXT | yes | Optional FK to `policy_scenarios` | backorders.scenario_id |
| `demand_ref` | TEXT | yes | Idempotency handle of the demand event; unique, shared namespace with `lost_sales` through the trigger | written by C07; NULL in the snapshot |

### lost_sales
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `lost_sale_id` | TEXT | no | Key | lost_sales.lost_sale_id |
| `product_id` | TEXT | no | FK to `products` | lost_sales.product_id |
| `location_id` | TEXT | no | FK to `locations` | lost_sales.location_id |
| `quantity` | INT | no | Units lost, `> 0` | lost_sales.quantity |
| `occurred_at` | TIMESTAMPTZ | no | Instant of the lost demand | lost_sales.occurred_at |
| `scenario_id` | TEXT | yes | Optional FK to `policy_scenarios` | lost_sales.scenario_id |
| `demand_ref` | TEXT | yes | As in `backorders` | written by C07; NULL in the snapshot |

### reservations
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `reservation_id` | TEXT | no | Key | reservations.reservation_id |
| `product_id` | TEXT | no | FK to `products` | reservations.product_id |
| `location_id` | TEXT | no | FK to `locations` | reservations.location_id |
| `quantity` | INT | no | Units reserved, `> 0` | reservations.quantity |
| `reserved_at` | TIMESTAMPTZ | no | Reservation instant | reservations.reserved_at |
| `released_at` | TIMESTAMPTZ | yes | Release instant, `>= reserved_at`; NULL = open | reservations.released_at |

### replenishment_params
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `product_id` | TEXT | no | FK to `products`; part of the key | replenishment_params.product_id |
| `location_id` | TEXT | no | FK to `locations`; part of the key | replenishment_params.location_id |
| `reorder_point` | INT | no | Trigger level, `>= 0`: order when position < this | replenishment_params.reorder_point |
| `target_position` | INT | no | Order-up-to level, `>= 0` | replenishment_params.target_position |
| `supplier_id` | TEXT | yes | Optional FK to `suppliers`: the supplier of this SKU (S-02 workaround) | replenishment_params.supplier_id |

### stock_snapshots
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `as_of` | TIMESTAMPTZ | no | Cutoff instant; part of the key | written by C02 |
| `product_id` | TEXT | no | FK to `products`; part of the key | written by C02 |
| `location_id` | TEXT | no | FK to `locations`; part of the key | written by C02 |
| `on_hand_raw` | INT | no | Sum of deltas up to `as_of`, possibly negative | derived (ledger) |
| `on_hand` | INT | no | `on_hand_raw` floored at 0 | derived |
| `reserved` | INT | no | Open reservations at `as_of` | derived |
| `available` | INT | no | `on_hand` - `reserved` | derived |
| `running_stock_min` | INT | no | Lowest running stock in day order, incl. the opening 0 | derived |
| `negative_stock` | BOOLEAN | no | TRUE when the raw or the running stock went below 0 | derived |
| `flags` | JSONB | no | JSON array of flags, `NEGATIVE_STOCK` | derived |

### draft_orders
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `draft_order_id` | TEXT | no | Key (deterministic hash of as-of, scenario, SKU, location) | written by C05 |
| `as_of` | TIMESTAMPTZ | no | Cutoff instant of the position | written by C05 |
| `scenario_id` | TEXT | yes | Optional FK to `policy_scenarios` | written by C05 |
| `product_id` | TEXT | no | FK to `products` | written by C05 |
| `location_id` | TEXT | no | FK to `locations` | written by C05 |
| `supplier_id` | TEXT | yes | Supplier of the SKU (no FK: kept as text) | written by C05 |
| `inventory_position` | INT | no | on hand + on order - backorders | derived |
| `reorder_point` | INT | no | Parameter used | derived |
| `target_position` | INT | no | Parameter used | derived |
| `raw_order` | INT | no | target - position when triggered, else 0 | derived |
| `minimum_order_quantity` | INT | no | MOQ of the product | derived |
| `order_after_moq` | INT | no | MAX(raw, MOQ) when triggered, else 0 | derived |
| `pack_size` | INT | no | Pack size of the product, `>= 1` | derived |
| `order_quantity` | INT | no | CEILING(after MOQ / pack) x pack; `>= 0`, `order_quantity % pack_size = 0` (`draft_orders_qty_ck`) | derived |
| `parameter_source` | TEXT | no | `params` or `forecast` (`draft_orders_source_ck`) | derived |
| `status` | TEXT | no | Always `draft` (`draft_orders_status_ck`) | constant |
| `dataset_version` | TEXT | yes | Dataset the command ran on | dataset_versions |
| `created_at` | TIMESTAMPTZ | no | Insert time (`now()`) | database default |

### fixture_states
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `state_name` | TEXT | no | Name such as `position_80` | inputs.json states key |
| `payload` | JSONB | no | `add_purchase_order_lines` of the state | inputs.json states value |

### raw_batches
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `batch_id` | TEXT | no | Key | seed or C01 |
| `received_at` | TIMESTAMPTZ | no | Receipt time (`now()`) | database default |
| `idempotency_key` | TEXT | no | Unique | seed or C01 |
| `payload_hash` | TEXT | no | sha256 of the canonical JSON | derived |
| `payload` | JSONB | no | The whole input | seed or C01 |
| `status` | TEXT | no | `accepted`, `partial` or `rejected` (`raw_batches_status_ck`) | derived |

### rejected_records
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `entity` | TEXT | no | Entity of the refused row (`inventory_movements`, `receipts`, ...) | domain `validate_batch` |
| `id` | TEXT | no | Id of the refused row | domain `validate_batch` |
| `reason_code` | TEXT | no | `DUPLICATE_MOVEMENT_ID`, `RECEIPT_BEFORE_ORDER`, ... (section 5) | domain `validate_batch` |
| `raw_row` | JSONB | no | The row exactly as it arrived | domain `validate_batch` |
| `batch_id` | TEXT | no | FK to `raw_batches` | seed |
| `ordinal` | INT | no | 0, 1, ... for repeated (entity, id, reason) | derived |

### quarantined_records
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `entity` | TEXT | no | Entity | reserved |
| `id` | TEXT | no | Id | reserved |
| `reason_code` | TEXT | no | Reason | reserved |
| `raw_row` | JSONB | no | Raw row | reserved |
| `batch_id` | TEXT | yes | Optional batch; no FK | reserved |

### audit_events
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `event_id` | TEXT | no | Key | written by commands |
| `entity_type` | TEXT | no | Kind of entity changed | written by commands |
| `entity_id` | TEXT | no | Id of the entity changed (by value) | written by commands |
| `action` | TEXT | no | Command name | written by commands |
| `actor_id` | TEXT | no | `X-Actor-Id` | request header |
| `occurred_at` | TIMESTAMPTZ | no | `now()` | database default |
| `before_version` | INT | yes | Optional version before | written by commands |
| `after_version` | INT | yes | Optional version after | written by commands |
| `reason` | TEXT | yes | Optional reason | written by commands |
| `request_id` | TEXT | yes | Request correlation id | request body |

### command_results
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `idempotency_key` | TEXT | no | Key, 1-128 of `A-Za-z0-9._:-` | request body |
| `payload_hash` | TEXT | no | Hash of command name + input | derived |
| `actor_id` | TEXT | yes | Actor bound to the key | request header |
| `command_id` | TEXT | no | `cmd-<hex>` | derived |
| `status` | TEXT | no | Outcome status | derived |
| `result` | JSONB | no | The stored response body | derived |
| `created_at` | TIMESTAMPTZ | no | `now()` | database default |

### dataset_versions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `dataset_version` | TEXT | no | `ds-<first 12 hex of the hash>` | seed |
| `dataset_hash` | TEXT | no | sha256 of the canonical input JSON | seed |
| `contract_version` | TEXT | no | `v1` | domain CONTRACT_VERSION |
| `created_at` | TIMESTAMPTZ | no | `now()` | database default |

## 3. Keys and relationships

Enforced foreign keys (35): `products.supplier_id`, `cost_versions.product_id`, `purchase_orders.supplier_id`, `purchase_order_lines.(purchase_order_id, product_id)`, `receipts.(po_line_id, location_id)`, `inventory_movements.(product_id, location_id)`, `sales.(product_id, location_id)`, `promotions.(product_id, location_id)`, `latent_demand.(product_id, location_id)`, `forecast_runs.(product_id, location_id)`, `forecast_points.forecast_run_id`, `backorders.(product_id, location_id, scenario_id)`, `lost_sales.(product_id, location_id, scenario_id)`, `reservations.(product_id, location_id)`, `replenishment_params.(product_id, location_id, supplier_id)`, `stock_snapshots.(product_id, location_id)`, `draft_orders.(scenario_id, product_id, location_id)`, `rejected_records.batch_id`.

Logical joins the database does not enforce: `suppliers.calendar_id` to `calendar_closures.calendar_id`; `draft_orders.supplier_id` to `suppliers`; `audit_events.entity_id`, `rejected_records.id` and `command_results.idempotency_key` point at rows by value; `quarantined_records.batch_id` has no FK; a purchase order line has no location (its open quantity is counted at the product's home location, `replenishment_params`, as in `data/sql/reference_metrics.sql`).

## 4. Constraints, triggers and indexes (`0002_constraints.sql`)

* **CHECK constraints (29)** named in the column tables, for example `movements_sign_ck` (a sale is never positive), `draft_orders_qty_ck` (whole packs), `scenarios_policy_ck` (`lost_sale` or `backlog`), `po_status_ck`.
* **Immutable / append-only (`ss_forbid_mutation`):** `inventory_movements_immutable`, `inventory_movements_no_truncate`, `audit_events_append_only`. The error is an `integrity_constraint_violation`, mapped to 409 `INTEGRITY_RULE` by the API.
* **Receipt rules (`ss_receipt_rules`, trigger `receipts_rules`):** `RECEIPT_BEFORE_ORDER`, `RECEIPT_EXCEEDS_ORDERED`; the line is locked `FOR UPDATE` so two concurrent receipts cannot both fit. `purchase_orders_date_fixed` forbids re-dating an order that has receipts.
* **Unmet XOR (`ss_unmet_xor`, triggers `backorders_xor`, `lost_sales_xor`):** a `demand_ref` is a backorder or a lost sale, never both (P03-TEST-08), under an advisory lock.
* **Indexes:** `movements_pair_at_idx (product_id, location_id, event_at)`, `sales_pair_at_idx`, `receipts_line_idx`, `po_lines_order_idx`, `draft_orders_as_of_idx`.

## 5. Rejection tables

`rejected_records` keeps every refused raw row with its reason; `quarantined_records` is reserved and empty. The load (`validate_batch`, used by the seed and by C01) refuses, with these reason codes:

| Reason code | Meaning | Snapshot rows | Where |
|---|---|---|---|
| `DUPLICATE_MOVEMENT_ID` | An exact replay of an already posted `movement_id`: the first occurrence is kept | 3 (`mv-002230`, `mv-005418`, `mv-006574`; INJ-01) | `inventory_movements` |
| `DUPLICATE_MOVEMENT_CONFLICT` | The same `movement_id` with a different payload: EVERY occurrence is rejected | 0 (EV-01 is a command replay) | `inventory_movements` |
| `RECEIPT_BEFORE_ORDER` | A receipt dated before its order (P03-TEST-11) | 1 (`rcpt-01309`, 10 days before `po-0998`; INJ-02) | `receipts` |
| `RECEIPT_EXCEEDS_ORDERED` | A receipt that would take received above ordered | 0 | `receipts` |
| `DUPLICATE_ID` | A repeated primary key in any other entity | 0 | any entity |
| `UNKNOWN_REFERENCE` | A foreign key whose parent was not loaded (parents load first) | 0 | any entity |
| `MALFORMED_RECORD` | A row that does not parse | 0 | any entity |

The API commands answer with the same codes: 422 `VALIDATION_FAILED` with `details[].rule_id` (for example `RECEIPT_BEFORE_ORDER`, `RECEIPT_BEFORE_LEAD_TIME`, `RECEIPT_EXCEEDS_ORDERED`), 409 for idempotency and integrity conflicts, 501 for the extension commands. See `technical-case-study.md`.

## 6. Source-to-target mapping

`data/generate.py` writes 19 entity files `web/public/data/<entity>.json` (`{entity, dataset_version, rows}`) with the field names of `inputs.json`; `data/sql/analysis/prepare_snapshot.py` builds one input document from them (`contract_version`, `as_of` = `2026-09-30T23:59:59Z`, `window_start` = `2025-04-01T00:00:00Z`) and `data/seed.py` loads it through `validate_batch` in the order below (`INSERT ... ON CONFLICT DO NOTHING`, so a second run inserts nothing).

| Load order | Entity file | Target table | Rows in file | Rows loaded | Note |
|---|---|---|---|---|---|
| 1 | `suppliers.json` | `suppliers` | 4 | 4 |  |
| 2 | `products.json` | `products` | 60 | 60 | `supplier_id` not in the file (S-02) |
| 3 | `locations.json` | `locations` | 3 | 3 |  |
| 4 | `calendar_closures.json` | `calendar_closures` | 1 | 1 |  |
| 5 | `cost_versions.json` | `cost_versions` | 15 | 15 | +6 % on the 15 `sup-04` products from 2026-02-01 |
| 6 | `policy_scenarios.json` | `policy_scenarios` | 4 | 4 |  |
| 7 | `purchase_orders.json` | `purchase_orders` | 998 | 998 |  |
| 8 | `purchase_order_lines.json` | `purchase_order_lines` | 1,282 | 1,282 |  |
| 9 | `receipts.json` | `receipts` | 1,309 | 1,308 | `rcpt-01309` rejected (`RECEIPT_BEFORE_ORDER`) |
| 10 | `inventory_movements.json` | `inventory_movements` | 10,916 | 10,913 | 3 exact replays rejected (`DUPLICATE_MOVEMENT_ID`) |
| 11 | `sales.json` | `sales` | 9,475 | 9,475 | one row per SKU x location x day with sales |
| 12 | `promotions.json` | `promotions` | 45 | 45 |  |
| 13 | `latent_demand.json` | `latent_demand` | 6,380 | 6,380 | keyed by product, location and day since fix S-01 |
| 14 | `forecast_runs.json` | `forecast_runs` | 56 | 56 | 6 columns loaded; `information_hash`, `model_report`, `notes` stay NULL |
| 15 | `forecast_points.json` | `forecast_points` | 2,352 | 2,352 |  |
| 16 | `backorders.json` | `backorders` | 70 | 70 | `demand_ref` NULL |
| 17 | `lost_sales.json` | `lost_sales` | 361 | 361 | `demand_ref` NULL |
| 18 | `reservations.json` | `reservations` | 16 | 16 | 6 open at the cutoff |
| 19 | `replenishment_params.json` | `replenishment_params` | 60 | 60 | carries `supplier_id` |

Not loaded from files: `stock_snapshots` (C02), `draft_orders` (C05), `forecast_runs.model_report` (C03), `audit_events` and `command_results` (every command), `fixture_states` (golden fixture only), `raw_batches`, `rejected_records` and `dataset_versions` (the seed).

Field-level rules: instants stay ISO-8601 with `Z` in the files and become `TIMESTAMPTZ`; money strings (`"12.50"`) become `NUMERIC(14,2)`; booleans stay booleans; `null` is NULL. The generator publishes `unit_cost` in `products` and `cost_versions` as 2-decimal strings.

## 7. Known mismatches and open items (disclosed, not hidden)

* **S-02:** `validate_batch` loads `products` before `suppliers`, so a product row with `supplier_id` would be rejected `UNKNOWN_REFERENCE`; the generator omits it and the supplier lives on `replenishment_params`. Open (T-03-07).
* **Two dataset hashes:** the generator's `dataset_hash` (`5bdabb50...`, sha256 over the 19 entity files) differs from the seed's `dataset_versions.dataset_hash` (`ds-9c4be62bbee4`, sha256 of the combined input JSON). Both are deterministic; neither is the other.
* **`purchase_orders.status` is current, not as-of:** a closed order was open in earlier months. Any as-of reconstruction must not filter on `confirmed`; query 01 uses `status <> 'cancelled'` and reports the contract's confirmed-only figure beside it. The cancellation instant is not stored, so a cancelled order is excluded at every as-of (assumption A-1 in `sql-analysis.md`).
* **S-04:** closed orders with a partly received line (INJ-03, `pol-00795`, `pol-00840`, 72 units never received) are not counted as on order by the contract (D-01, confirmed only). Open decision.
* **R3-04:** for a product with parameters at one of several locations, the position of that location is reported as the total. The snapshot has one home location per product, so no snapshot figure is affected. Open (T-03-07).
* **`draft_orders` and `stock_snapshots` are empty** in the seeded snapshot: the analysis SQL computes the same arithmetic from source rows (queries 01, 02) and `bi_fact_draft_order.sql` unions persisted rows when they exist.

## 8. Reproduce

```sh
cd apps/supplyscope
export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/<empty scratch database>
../../.venv/bin/python data/sql/analysis/prepare_snapshot.py            # reset + migrate + seed web/public/data
psql "$DATABASE_URL" -c "select count(*) from inventory_movements"   # 10913
```
