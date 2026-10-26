// Typed records, the population and the pipeline input/output shapes (contract v1). Instants are UTC epoch ms,
// dates are "YYYY-MM-DD", units are integers, money and ratios are decimal strings.
import type { EntityName, MetricKey } from "./contract";

export interface Product { product_id: string; sku: string; unit_cost: string; pack_size: number; minimum_order_quantity: number; abc_class: string | null; supplier_id: string | null }
export interface Location { location_id: string; location_name: string; timezone: string; storage_capacity: number; active: boolean }
export interface Supplier { supplier_id: string; supplier_name: string; calendar_id: string; quoted_lead_days: number; active: boolean }
export interface Sale { sale_id: string; product_id: string; location_id: string; sold_at: number; quantity: number }
export interface Movement { movement_id: string; product_id: string; location_id: string; quantity_delta: number; event_at: number; movement_type: string }
export interface PurchaseOrder { purchase_order_id: string; supplier_id: string; ordered_at: number; status: string; currency: string }
export interface PoLine { po_line_id: string; purchase_order_id: string; product_id: string; ordered_quantity: number; unit_cost: string }
export interface Receipt { receipt_id: string; po_line_id: string; location_id: string; received_quantity: number; received_at: number }
/** `planned_uplift` is the schedule (known when announced); `realised_uplift` is an outcome and is never a feature. */
export interface Promotion { promotion_id: string; product_id: string; starts_at: number; ends_at: number; planned_uplift: string; announced_at: number; realised_uplift: string | null; location_id: string | null }
export interface ForecastRun { forecast_run_id: string; product_id: string; location_id: string; cutoff: number; horizon_days: number; selected_model: string }
export interface ForecastPoint { forecast_point_id: string; forecast_run_id: string; model: string; target_date: string; forecast_value: string }
export interface Scenario { scenario_id: string; scenario_name: string; service_target: string; unmet_policy: string; seed: number; warmup_days: number; replications: number }
export interface Backorder { backorder_id: string; product_id: string; location_id: string; quantity: number; opened_at: number; closed_at: number | null; scenario_id: string | null }
export interface Reservation { reservation_id: string; product_id: string; location_id: string; quantity: number; reserved_at: number; released_at: number | null }
export interface Param { product_id: string; location_id: string; reorder_point: number; target_position: number; supplier_id: string | null }
export interface CostVersion { cost_version_id: string; product_id: string; unit_cost: string; effective_from: number }
export interface LostSale { lost_sale_id: string; product_id: string; location_id: string; quantity: number; occurred_at: number; scenario_id: string | null }
export interface Closure { closure_id: string; calendar_id: string; closed_from: string; closed_to: string }
export interface Latent { product_id: string; location_id: string; demand_date: string; latent_quantity: number }

export interface Population {
  products: Product[]; locations: Location[]; sales: Sale[]; inventory_movements: Movement[]; purchase_orders: PurchaseOrder[];
  purchase_order_lines: PoLine[]; receipts: Receipt[]; suppliers: Supplier[]; promotions: Promotion[]; forecast_runs: ForecastRun[];
  forecast_points: ForecastPoint[]; policy_scenarios: Scenario[]; backorders: Backorder[]; reservations: Reservation[];
  replenishment_params: Param[]; cost_versions: CostVersion[]; lost_sales: LostSale[]; calendar_closures: Closure[]; latent_demand: Latent[];
}

export type Row = Record<string, unknown>;
export interface StateSpec { add_purchase_order_lines?: Row[] }
/** A raw input batch: entity -> rows, plus the fixture/snapshot envelope. */
export interface PipelineInputs {
  contract_version?: string | number;
  as_of?: string;
  window_start?: string;
  states?: Record<string, StateSpec>;
  [entity: string]: unknown;
}

export interface RejectedRecord { entity: string; id: string; status: "rejected"; reason_code: string; raw_row: unknown; message: string }
export interface IngestResult {
  accepted: Record<string, unknown[]>;
  acceptedRows: Record<string, Row[]>;
  rejected: RejectedRecord[];
  counts: Record<string, { accepted: number; rejected: number }>;
  extraCounts: Record<string, { accepted: number; rejected: number }>;
}

/** Exactly the keys of expected.json, in order. Money and rates are strings, null where not evaluated. */
export type Metrics = {
  fill_rate: string | null; requested_units: number; fulfilled_units: number; unmet_units: number; observed_days: number;
  stockout_day_count: number; stockout_days: string | null; running_stock_min: number; timestamp_order_stock_min: number;
  negative_stock: boolean; working_capital: string; empty_population: boolean; on_hand: number; on_order: number;
  backorders: number; reserved: number; available: number; inventory_position: number; reorder_point: number | null;
  target_position: number | null; reorder_triggered: boolean | null; raw_order: number | null; order_after_moq: number | null;
  order_quantity: number | null;
} & Record<MetricKey, string | number | boolean | null>;
/** The metrics added after the golden fixture (R3-01), reported next to `Metrics` by `computeMetricsFull`. */
export interface ExtraMetrics {
  /** Dates with any unmet demand / calendar days observed (the calendar-day figure; `stockout_days` is the SKU-day rate). */
  stockout_calendar_days_share: string | null;
  /** Active (product, location) pairs x calendar days observed: the denominator of `stockout_days`. */
  observed_sku_days: number;
}
export type FullMetrics = Metrics & ExtraMetrics;

export interface Manifest {
  contract_version: string; dataset_hash: string; dataset_version: string; generated_at: string;
  row_counts: Record<string, number>; code_sha?: string; designed_relationships?: string[];
  generator?: { name?: string; seed?: number; parameters?: { as_of?: string; window?: [string, string]; [k: string]: unknown } };
  /** Golden snapshot only: the fixture's envelope. */
  as_of?: string; window_start?: string; states?: Record<string, StateSpec>; fixture_id?: string;
}
export interface EntityFile<T> { entity: EntityName | string; dataset_version: string; rows: T[] }
