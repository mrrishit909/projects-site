# Data dictionary: Revenue Atlas relational model (P01-ART-03)

All data in this model is **synthetic** (the golden fixture `revenue-atlas-golden-v1` and the generated snapshot
`ra-20261026-20261026`, seed 20261026). Sources: `data/migrations/0001_schema.sql`, `0002_constraints.sql`, `data/migrate.py`,
`docs/contracts.md` v1.1 (rules cited as D-01..D-07), `docs/api-contract.md` (commands C01..C04).
Row counts below are `SELECT count(*)` on a database prepared by `data/sql/analysis/prepare_snapshot.py` (seed of `web/public/data`,
then C01 for the three INJ-01 order bundles, then C02 and C04 for all 2,724 shipments). The ER diagram is in `erd.md`.

Conventions: money is `NUMERIC(20,6)`, carried as decimal strings in JSON (D-02); timestamps are `TIMESTAMPTZ` read as UTC instants (D-01);
dates are `DATE`; ids are `TEXT` keys supplied by the source system. "FK (enforced)" means a constraint in `0002`; "logical" means a join the
contract relies on that the database does not enforce.

## 1. Business entities (one table per `inputs.json` entity)

| Table | Grain | Primary key | Rows (snapshot DB) | Update semantics |
|---|---|---|---|---|
| `customers` | one customer **version** | `(customer_id, effective_from)` | 50 (48 customers) | Type-2: a territory or segment change is a new row with a later `effective_from`; rows are never updated. Region of a line = version with the greatest `effective_from` <= shipped UTC date, else `UNASSIGNED` (D-06). |
| `products` | one product | `product_id` | 36 | Insert-only through C01 (`ON CONFLICT DO NOTHING`). |
| `orders` | one order | `order_id` | 2,397 | Insert-only through C01; `status` becomes `partially_returned` when C03 posts the first return of a `shipped` order. |
| `order_lines` | one ordered product line | `line_id` | 6,163 | Insert-only; a wrong price cannot be corrected in place (UAT finding). |
| `discounts` | one discount posted on an order line | `discount_id` | 2,197 | Insert-only. |
| `shipments` | one physical shipment | `shipment_id` | 2,724 | Insert-only. |
| `shipment_lines` | **fact grain**: one shipped line of a shipment | `shipment_line_id` | 6,644 | `cost_version_id` is NULL until C02 sets it, then immutable (D-03); `version` is bumped by C03 (optimistic concurrency, stale = 409). |
| `returns` | one posted return (credit) | `return_id` | 384 | **Append-only**: trigger `returns_append_only` rejects UPDATE and DELETE; a correction is a new row. |
| `cost_versions` | one product cost over a validity range | `cost_version_id` | 150 | Insert-only. No exclusion constraint, so overlaps are storable and C02 can quarantine them (D-03). |
| `exchange_rates` | one currency per day to the reporting currency | `rate_id` | 1,458 | Insert-only; a missing day is repaired by a new row through C01 (clears the FX quarantine). |

Not a table: `quotas` exist only as `web/public/data/quotas.json` (64 rows, unique `(rep, period)`); the backend has no quota table and no attainment
calculation (P01-TEST-08 blocked in the ledger).

### customers
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `customer_id` | TEXT | no | Customer key (part of PK) | inputs.json `customers` |
| `customer_name` | TEXT | no | Display name (synthetic) | |
| `region_id` | TEXT | no | Sales region effective from `effective_from` (`reg-north/south/east/west` in the snapshot) | D-06 |
| `segment` | TEXT | no | `enterprise`, `mid_market`, `smb` (snapshot); `SMB` in the golden fixture | |
| `effective_from` | DATE | no | Start of this version (part of PK) | D-06 |

### products
| Field | Type | Null | Meaning | Source |
|---|---|---|---|---|
| `product_id` | TEXT | no | PK | inputs.json |
| `sku` | TEXT | no | Stock keeping unit | |
| `category_id` | TEXT | no | `cat-fixtures`, `cat-apparel`, `cat-tools`, `cat-packaging`, `cat-safety`, `cat-office` (snapshot) | |
| `unit_of_measure` | TEXT | no | e.g. `each` | |
| `active` | BOOLEAN | no | | |

### orders
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `order_id` | TEXT | no | PK | |
| `customer_id` | TEXT | no | Logical link to `customers.customer_id` (no FK: the key is a version pair) | |
| `order_date` | DATE | no | Booking date; **not** the reporting basis (D-01 uses `shipped_at`) | |
| `currency` | TEXT | no | CHECK `^[A-Z]{3}$` (`orders_currency_ck`); malformed values are rejected at C01 with `CURRENCY_NOT_ISO4217` | D-02, D-06 |
| `status` | TEXT | no | `shipped`, `partially_returned` enter the population; `cancelled` never does (snapshot: 2,032 / 360 / 5) | D-01, P01-TEST-09 |

### order_lines
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `line_id` | TEXT | no | PK | |
| `order_id` | TEXT | no | FK (enforced) `order_lines_order_fk` -> orders | |
| `product_id` | TEXT | no | FK (enforced) `order_lines_product_fk` -> products | |
| `quantity` | BIGINT | no | Ordered quantity, CHECK >= 1; denominator of the discount share | D-04 |
| `unit_price` | NUMERIC(20,6) | no | In order currency, CHECK >= 0 (0.00 is valid: P01-TEST-05) | D-02 |

### discounts
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `discount_id` | TEXT | no | PK | |
| `line_id` | TEXT | no | FK (enforced) `discounts_line_fk` -> order_lines; posted at order-line level | D-04 |
| `discount_amount` | NUMERIC(20,6) | no | Total for the order line, CHECK >= 0 | |
| `reason_code` | TEXT | no | `volume`, `promo`, `goodwill`, `price_match` (snapshot) | |
| `approved_by` | TEXT | no | Approver id | |

### shipments
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `shipment_id` | TEXT | no | PK | |
| `order_id` | TEXT | no | FK (enforced) `shipments_order_fk` | |
| `shipped_at` | TIMESTAMPTZ | no | **Reporting basis**: window `[from, to)` in UTC; FX date, cost-version date and region-version date are its UTC date | D-01..D-03 |
| `shipping_cost` | NUMERIC(20,6) | no | Whole-shipment freight in `currency`, CHECK >= 0; allocated over lines by C04 | D-04 |
| `currency` | TEXT | no | CHECK `^[A-Z]{3}$` | D-02 |

### shipment_lines
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `shipment_line_id` | TEXT | no | PK; **fact grain** of every metric; key of both allocation tables | D-01, D-04 |
| `shipment_id` | TEXT | no | FK (enforced) `shipment_lines_shipment_fk` | |
| `line_id` | TEXT | no | FK (enforced) `shipment_lines_line_fk` -> order_lines | |
| `shipped_quantity` | BIGINT | no | CHECK >= 0; at most the ordered quantity in practice (reviewer R-01: not enforced) | |
| `cost_version_id` | TEXT | yes | FK (enforced) `shipment_lines_cost_fk`; NULL until C02; immutable once set | D-03 |
| `version` | INT | no | Default 1, CHECK >= 1; optimistic concurrency counter bumped by C03 | D-06 |

### returns
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `return_id` | TEXT | no | PK | |
| `shipment_line_id` | TEXT | no | FK (enforced) `returns_shipment_line_fk` | |
| `returned_quantity` | BIGINT | no | CHECK >= 1; cumulative per line must not exceed `shipped_quantity` (C03: `RETURN_EXCEEDS_REMAINING`) | D-06 |
| `credit_amount` | NUMERIC(20,6) | no | CHECK >= 0 (`returns_credit_sign_ck`; C03: `CREDIT_SIGN_REVERSED`), in the order currency | D-06 |
| `credit_date` | DATE | no | Recognition date (read as 00:00 UTC); FX of this date applies | D-01a, D-02 |

### cost_versions
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `cost_version_id` | TEXT | no | PK | |
| `product_id` | TEXT | no | FK (enforced) `cost_versions_product_fk` | |
| `unit_cost` | NUMERIC(20,6) | no | CHECK >= 0, reporting currency | D-03 |
| `valid_from` | DATE | no | Inclusive | |
| `valid_to` | DATE | yes | Exclusive; NULL = open; CHECK `valid_to > valid_from` | |

### exchange_rates
| Field | Type | Null | Meaning and rule | Source |
|---|---|---|---|---|
| `rate_id` | TEXT | no | PK | |
| `currency` | TEXT | no | CHECK `^[A-Z]{3}$` | D-02 |
| `reporting_currency` | TEXT | no | `USD` | |
| `rate_date` | DATE | no | Matched to the shipped UTC date (returns: `credit_date`); no row = `FX_RATE_MISSING` | D-02 |
| `rate` | NUMERIC(20,6) | no | CHECK > 0; never defaulted to 1.0 except USD to USD | |

## 2. Quarantine, rejection and operational tables

| Table | Grain | Key | Rows | Role and semantics |
|---|---|---|---|---|
| `raw_batches` | one C01 call | `batch_id`; `idempotency_key` UNIQUE | 1 | Raw payload kept as `JSONB`; `status` CHECK in (`accepted`, `partial`); `payload_hash` supports the 409 on same key / different payload (D-06). |
| `rejected_records` | one refused source row | `(batch_id, entity, id)`; FK (enforced) `batch_id` -> raw_batches | 17 | C01 refusals with `reason_code` (`CURRENCY_NOT_ISO4217`, `ORPHAN_REFERENCE`) and `raw_row`. History: rows stay. Snapshot: 3 orders + 14 dependants, all `CURRENCY_NOT_ISO4217`. |
| `quarantined_records` | one record currently excluded | `(entity, id)` | 56 | Written by C02 for shipment lines: `COST_VERSION_AMBIGUOUS`, `COST_VERSION_MISSING`, `FX_RATE_MISSING` (D-02, D-03). **Current state, not history**: upserted on change, deleted when a later C01 (rate or cost fix) or C02 rerun lets the line resolve. Excluded from every metric and counted in `meta.exclusions`. Snapshot: 31 + 15 + 10 (FX rows cover 5 shipments). |
| `freight_allocations` | one shipment line | `shipment_line_id` (PK) FK (enforced) -> shipment_lines | 6,644 | C04 output, `amount` CHECK >= 0 in the shipment currency. The PK is the double-allocation guard: a second C04 for the shipment violates `freight_allocations_pkey` -> 409 `FREIGHT_ALREADY_ALLOCATED` (P01-TEST-01). Spans **all** lines of the shipment including quarantined ones (see `sql-analysis.md`, query 09). |
| `discount_allocations` | one shipment line | `shipment_line_id` (PK) FK (enforced) -> shipment_lines | 6,644 | C04 output in the order currency; `line_id` is a logical link to `order_lines`. `ON CONFLICT DO NOTHING`. |
| `audit_events` | one state change | `event_id` | 5,449 | **Append-only** (trigger `audit_events_append_only`): `entity_type`, `entity_id`, `action`, `actor_id`, `before_version`, `after_version`, `reason`, `request_id`. Written in the same transaction as the change (atomic). |
| `command_results` | one idempotency key | `idempotency_key` | 5,449 | Stored command response (`result` JSONB) and `payload_hash`; a replay returns the stored result with `Idempotent-Replay: true`. |
| `dataset_versions` | one seeded dataset | `dataset_version` | 1 | `dataset_hash` = sha256 of the canonical JSON of the seeded inputs, `contract_version`. |
| `schema_migrations` | one applied migration | `version` | 2 | Created by `data/migrate.py` with the file checksum; a changed applied file aborts. |

Constraint catalogue: nine named FKs in `0002` (shown in the field tables) plus three inline FKs in `0001` (`freight_allocations`, `discount_allocations`, `rejected_records`); currency regex checks on `orders`, `shipments`, `exchange_rates`;
`rate > 0`, `quantity >= 1`, `unit_price >= 0`, `discount_amount >= 0`, `shipping_cost >= 0`, `shipped_quantity >= 0`, `version >= 1`,
`returned_quantity >= 1`, `credit_amount >= 0`, `unit_cost >= 0`, `valid_to > valid_from`, freight `amount >= 0`; indexes on
`shipment_lines(shipment_id)`, `(line_id)`, `returns(shipment_line_id)`, `cost_versions(product_id, valid_from)`, `shipments(shipped_at)`,
`exchange_rates(currency, rate_date)`.

## 3. Source-to-target mapping: inputs.json -> table -> metric field

Every `inputs.json` entity loads 1:1 into the table of the same name with identical column names (`data/seed.py` `COLUMNS`); the contract metrics
(`docs/contracts.md` D-05) are then sums over shipment lines. `-` means the field is carried but feeds no money metric.

| inputs.json field | Table.column | Metric field(s) it drives | Rule |
|---|---|---|---|
| `order_lines.quantity` | order_lines.quantity | `allocated_discounts` (share = shipped/ordered) | D-04 |
| `order_lines.unit_price` | order_lines.unit_price | `gross_sales` = shipped_quantity x unit_price x FX; freight weight | D-02, D-04 |
| `shipment_lines.shipped_quantity` | shipment_lines.shipped_quantity | `gross_sales`, `cogs`, `shipped_units`, discount split weight | D-01 |
| `discounts.discount_amount` | discounts.discount_amount -> discount_allocations.amount | `allocated_discounts`, `discount_rate` | D-04 |
| `shipments.shipping_cost` | shipments.shipping_cost -> freight_allocations.amount | `shipping_cost`, `allocation_residual` | D-04 |
| `shipments.shipped_at` | shipments.shipped_at | window selection, month, FX date, cost-version date, region-version date | D-01..D-03 |
| `cost_versions.unit_cost` (+ `valid_from/valid_to`, `shipment_lines.cost_version_id`) | cost_versions.unit_cost | `cogs` (shipped_quantity x cost), `recoverable_return_cost` | D-03 |
| `returns.credit_amount` | returns.credit_amount | `merchandise_credits`, hence `net_merchandise_sales` | D-01a |
| `returns.returned_quantity` | returns.returned_quantity | `returned_units`, `return_rate`, `recoverable_return_cost` | D-05 |
| `returns.credit_date` | returns.credit_date | window for credits; FX date for credits | D-01a, D-02 |
| `exchange_rates.rate` (+ `currency`, `rate_date`) | exchange_rates.rate | USD conversion of every money field | D-02 |
| `orders.currency`, `shipments.currency` | orders.currency, shipments.currency | which rate applies; `FX_RATE_MISSING` quarantine | D-02 |
| `orders.status` | orders.status | population (shipped, partially_returned) | D-01 |
| `orders.order_id` | orders.order_id | `eligible_orders`, `average_order_value` | D-05 |
| `orders.customer_id` + `customers.region_id`, `effective_from` | customers | region group (`UNASSIGNED` when no version) | D-06 |
| `customers.segment` | customers.segment | segment group | |
| `products.category_id` | products.category_id | category group | |
| `orders.order_date`, `products.sku/unit_of_measure/active`, `customers.customer_name`, `discounts.reason_code/approved_by` | same | - (descriptive; `reason_code` is a filter/evidence field) | |

Derived metric fields (D-05) and their inputs: `net_merchandise_sales` = gross - discounts - credits; `cogs` = shipped x cost - recoverable;
`gross_profit` = net - cogs; `contribution_margin` = gross_profit + `shipping_revenue` - `shipping_cost` - `other_variable_costs`
(`shipping_revenue` and `other_variable_costs` have **no source field** and are 0.00 in this dataset); `contribution_margin_rate`, `discount_rate`,
`return_rate`, `average_order_value` are ratios of the aggregated sums (null on a zero denominator); `eligible_shipment_lines`, `eligible_orders`
are counts over the population.
