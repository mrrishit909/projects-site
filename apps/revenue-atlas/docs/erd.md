# Entity-relationship diagram (P01-ART-03)

Derived from `data/migrations/0001_schema.sql` and `0002_constraints.sql`. Solid lines are enforced foreign keys; dotted lines are logical joins the contract
relies on (D-02, D-06) that the database does not enforce. Field detail is in `data-dictionary.md`. Synthetic data only.

```mermaid
erDiagram
    customers {
        TEXT customer_id PK
        DATE effective_from PK
        TEXT customer_name
        TEXT region_id
        TEXT segment
    }
    products {
        TEXT product_id PK
        TEXT sku
        TEXT category_id
        TEXT unit_of_measure
        BOOLEAN active
    }
    orders {
        TEXT order_id PK
        TEXT customer_id
        DATE order_date
        TEXT currency
        TEXT status
    }
    order_lines {
        TEXT line_id PK
        TEXT order_id FK
        TEXT product_id FK
        BIGINT quantity
        NUMERIC unit_price
    }
    discounts {
        TEXT discount_id PK
        TEXT line_id FK
        NUMERIC discount_amount
        TEXT reason_code
        TEXT approved_by
    }
    shipments {
        TEXT shipment_id PK
        TEXT order_id FK
        TIMESTAMPTZ shipped_at
        NUMERIC shipping_cost
        TEXT currency
    }
    shipment_lines {
        TEXT shipment_line_id PK
        TEXT shipment_id FK
        TEXT line_id FK
        BIGINT shipped_quantity
        TEXT cost_version_id FK
        INT version
    }
    returns {
        TEXT return_id PK
        TEXT shipment_line_id FK
        BIGINT returned_quantity
        NUMERIC credit_amount
        DATE credit_date
    }
    cost_versions {
        TEXT cost_version_id PK
        TEXT product_id FK
        NUMERIC unit_cost
        DATE valid_from
        DATE valid_to
    }
    exchange_rates {
        TEXT rate_id PK
        TEXT currency
        TEXT reporting_currency
        DATE rate_date
        NUMERIC rate
    }
    freight_allocations {
        TEXT shipment_line_id PK
        TEXT shipment_id
        NUMERIC amount
        TIMESTAMPTZ allocated_at
    }
    discount_allocations {
        TEXT shipment_line_id PK
        TEXT line_id
        NUMERIC amount
    }
    raw_batches {
        TEXT batch_id PK
        TEXT idempotency_key
        TEXT payload_hash
        JSONB payload
        TEXT status
    }
    rejected_records {
        TEXT batch_id PK
        TEXT entity PK
        TEXT id PK
        TEXT reason_code
        JSONB raw_row
    }
    quarantined_records {
        TEXT entity PK
        TEXT id PK
        TEXT reason_code
        JSONB raw_row
        TEXT batch_id
    }
    audit_events {
        TEXT event_id PK
        TEXT entity_type
        TEXT entity_id
        TEXT action
        TEXT actor_id
        INT before_version
        INT after_version
    }
    command_results {
        TEXT idempotency_key PK
        TEXT payload_hash
        TEXT command_id
        JSONB result
    }
    dataset_versions {
        TEXT dataset_version PK
        TEXT dataset_hash
        TEXT contract_version
    }

    orders ||--|{ order_lines : "order_lines_order_fk"
    products ||--o{ order_lines : "order_lines_product_fk"
    order_lines ||--o{ discounts : "discounts_line_fk"
    orders ||--o{ shipments : "shipments_order_fk"
    shipments ||--|{ shipment_lines : "shipment_lines_shipment_fk"
    order_lines ||--o{ shipment_lines : "shipment_lines_line_fk"
    cost_versions |o--o{ shipment_lines : "shipment_lines_cost_fk (set by C02)"
    products ||--o{ cost_versions : "cost_versions_product_fk"
    shipment_lines ||--o{ returns : "returns_shipment_line_fk (append-only)"
    shipment_lines ||--o| freight_allocations : "PK = double-allocation guard"
    shipment_lines ||--o| discount_allocations : "PK = one per line"
    raw_batches ||--o{ rejected_records : "batch_id"
    customers }o..o{ orders : "logical: customer_id, version at shipped_at"
    exchange_rates }o..o{ orders : "logical: currency + rate_date"
    shipment_lines }o..o| quarantined_records : "logical: entity=shipment_lines, id"
```

Reading notes
* `customers` is type-2, so `orders.customer_id` cannot be a foreign key; the region is chosen per shipment by the version whose `effective_from` is the greatest one on or before the shipped UTC date (D-06).
* `returns` and `audit_events` carry `BEFORE UPDATE OR DELETE` triggers that raise `integrity_constraint_violation`.
* `command_results`, `audit_events`, `dataset_versions`, `quarantined_records` are not referenced by foreign keys; `quarantined_records.id` points at `shipment_lines.shipment_line_id` by convention.
