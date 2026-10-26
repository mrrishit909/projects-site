// Contract constants (docs/contracts.md, version 1). Mirrors domain/supplyscope/contract.py.
export const CONTRACT_VERSION = "v1";
export const ACCEPTED_INPUT_CONTRACTS: readonly (string | number)[] = [1, "1", "v1"];

/** The fifteen counted entities of an input batch, in the order of the ingest counts of expected.json. */
export const ENTITIES = [
  "products", "locations", "sales", "inventory_movements", "purchase_orders", "purchase_order_lines",
  "receipts", "suppliers", "promotions", "forecast_runs", "forecast_points", "policy_scenarios",
  "backorders", "reservations", "replenishment_params",
] as const;
/** Optional entities: D-05 cost versions, lost sales, supplier calendar closures, published latent demand. */
export const EXTRA_ENTITIES = ["cost_versions", "lost_sales", "calendar_closures", "latent_demand"] as const;
export type EntityName = (typeof ENTITIES)[number] | (typeof EXTRA_ENTITIES)[number];

/** Metric names in the order of expected.json. */
export const METRIC_KEYS = [
  "fill_rate", "requested_units", "fulfilled_units", "unmet_units", "observed_days", "stockout_day_count",
  "stockout_days", "running_stock_min", "timestamp_order_stock_min", "negative_stock", "working_capital",
  "empty_population", "on_hand", "on_order", "backorders", "reserved", "available", "inventory_position",
  "reorder_point", "target_position", "reorder_triggered", "raw_order", "order_after_moq", "order_quantity",
] as const;
export type MetricKey = (typeof METRIC_KEYS)[number];

export const GROUP_KEYS = ["product", "location", "supplier", "abc_class"] as const;
export type GroupKey = (typeof GROUP_KEYS)[number];
export const MOVEMENT_TYPES = ["receipt", "sale", "adjustment", "review", "return"] as const;
export const PO_STATUSES = ["confirmed", "cancelled", "closed"] as const;
export const UNMET_POLICIES = ["lost_sale", "backlog"] as const;
export const MODELS = ["naive", "seasonal_naive", "ewma"] as const;
export type ModelName = (typeof MODELS)[number];
/** Standard-normal quantiles for the supported service targets (6 dp). */
export const Z_TABLE: Readonly<Record<string, string>> = { "0.90": "1.281552", "0.95": "1.644854", "0.98": "2.053749", "0.99": "2.326348" };
export const SEASON = 7;
