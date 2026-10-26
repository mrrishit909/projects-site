"""Contract constants (docs/contracts.md, version 1)."""
from __future__ import annotations

CONTRACT_VERSION = "v1"
ACCEPTED_INPUT_CONTRACTS = frozenset({1, "1", "v1"})

#: The fifteen counted entities of an input batch, in the order of the ingest counts of expected.json.
ENTITIES = ("products", "locations", "sales", "inventory_movements", "purchase_orders", "purchase_order_lines",
            "receipts", "suppliers", "promotions", "forecast_runs", "forecast_points", "policy_scenarios",
            "backorders", "reservations", "replenishment_params")
#: Optional entities (D-05 cost versions, lost sales, supplier calendar closures, published latent demand).
EXTRA_ENTITIES = ("cost_versions", "lost_sales", "calendar_closures", "latent_demand")

#: Metric names in the order of expected.json.
METRIC_KEYS = ("fill_rate", "requested_units", "fulfilled_units", "unmet_units", "observed_days",
               "stockout_day_count", "stockout_days", "running_stock_min", "timestamp_order_stock_min",
               "negative_stock", "working_capital", "empty_population", "on_hand", "on_order", "backorders",
               "reserved", "available", "inventory_position", "reorder_point", "target_position",
               "reorder_triggered", "raw_order", "order_after_moq", "order_quantity")

GROUP_KEYS = ("product", "location", "supplier", "abc_class")
MOVEMENT_TYPES = ("receipt", "sale", "adjustment", "review", "return")
PO_STATUSES = ("confirmed", "cancelled", "closed")
UNMET_POLICIES = ("lost_sale", "backlog")
MODELS = ("naive", "seasonal_naive", "ewma")
#: Standard-normal quantiles for the supported service targets (6 dp).
Z_TABLE = {"0.90": "1.281552", "0.95": "1.644854", "0.98": "2.053749", "0.99": "2.326348"}
SEASON = 7
