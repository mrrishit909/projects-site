// Entity types. *Row types match the published JSON exactly (money as decimal strings).
// Parsed records (after ingest) keep the same snake_case names as the Python models, with money
// as Dec and timestamps as UTC epoch milliseconds.
import type { Dec } from "./decimal";

export interface CustomerRow { customer_id: string; customer_name: string; region_id: string; segment: string; effective_from: string }
export interface ProductRow { product_id: string; sku: string; category_id: string; unit_of_measure: string; active: boolean }
export interface OrderRow { order_id: string; customer_id: string; order_date: string; currency: string; status: string }
export interface OrderLineRow { line_id: string; order_id: string; product_id: string; quantity: number; unit_price: string }
export interface DiscountRow { discount_id: string; line_id: string; discount_amount: string; reason_code: string; approved_by: string }
export interface ShipmentRow { shipment_id: string; order_id: string; shipped_at: string; shipping_cost: string; currency: string }
export interface ShipmentLineRow { shipment_line_id: string; shipment_id: string; line_id: string; shipped_quantity: number; cost_version_id: string | null }
export interface ReturnRow { return_id: string; shipment_line_id: string; returned_quantity: number; credit_amount: string; credit_date: string }
export interface CostVersionRow { cost_version_id: string; product_id: string; unit_cost: string; valid_from: string; valid_to: string | null }
export interface ExchangeRateRow { rate_id: string; currency: string; reporting_currency: string; rate_date: string; rate: string }
export interface QuotaRow { quota_id: string; rep_id: string; period: string; period_start: string; period_end: string; quota_amount: string; currency: string }

export const ENTITIES = [
  "customers", "products", "orders", "order_lines", "discounts", "shipments",
  "shipment_lines", "returns", "cost_versions", "exchange_rates",
] as const;
export type EntityName = (typeof ENTITIES)[number];

/** The raw batch handed to ingest (golden inputs.json, or the published entity files' `rows`). */
export interface PipelineInputs {
  contract?: string;
  customers?: CustomerRow[];
  products?: ProductRow[];
  orders?: OrderRow[];
  order_lines?: OrderLineRow[];
  discounts?: DiscountRow[];
  shipments?: ShipmentRow[];
  shipment_lines?: ShipmentLineRow[];
  returns?: ReturnRow[];
  cost_versions?: CostVersionRow[];
  exchange_rates?: ExchangeRateRow[];
}

// ---- parsed records -------------------------------------------------------------------------
export type Customer = CustomerRow;
export type Product = ProductRow;
export type Order = OrderRow;
export interface OrderLine { line_id: string; order_id: string; product_id: string; quantity: number; unit_price: Dec }
export interface Discount { discount_id: string; line_id: string; discount_amount: Dec; reason_code: string; approved_by: string }
export interface Shipment { shipment_id: string; order_id: string; shipped_at: number; shipping_cost: Dec; currency: string }
export interface ShipmentLine { shipment_line_id: string; shipment_id: string; line_id: string; shipped_quantity: number; cost_version_id: string | null }
export interface Return { return_id: string; shipment_line_id: string; returned_quantity: number; credit_amount: Dec; credit_date: string }
export interface CostVersion { cost_version_id: string; product_id: string; unit_cost: Dec; valid_from: string; valid_to: string | null }
export interface ExchangeRate { rate_id: string; currency: string; reporting_currency: string; rate_date: string; rate: Dec }

export interface Accepted {
  customers: Customer[];
  products: Product[];
  orders: Order[];
  order_lines: OrderLine[];
  discounts: Discount[];
  shipments: Shipment[];
  shipment_lines: ShipmentLine[];
  returns: Return[];
  cost_versions: CostVersion[];
  exchange_rates: ExchangeRate[];
}

export interface RejectedRecord { entity: string; id: string; reason_code: string; raw_row: Record<string, unknown> }
export interface EntityCounts { accepted: number; rejected: number; quarantined: number }

/** One shipment line, all money in reporting currency (D-01, D-02). `shipped_date` is the UTC date. */
export interface ShipmentLineFact {
  shipment_line_id: string;
  shipment_id: string;
  order_id: string;
  line_id: string;
  customer_id: string;
  product_id: string;
  region_id: string;
  shipped_at: number;
  shipped_date: string;
  currency: string;
  fx_rate: Dec;
  shipped_quantity: number;
  unit_price: Dec;
  gross_sales: Dec;
  allocated_discount: Dec;
  cost_version_id: string;
  unit_cost: Dec;
  cogs: Dec;
  freight: Dec;
  returned_quantity: number;
  merchandise_credit: Dec;
  recoverable_return_cost: Dec;
}

/** One accepted return credit, recognised on credit_date (D-01a), reporting currency. */
export interface ReturnEvent {
  return_id: string;
  shipment_line_id: string;
  credit_date: string;
  returned_quantity: number;
  merchandise_credit: Dec;
  recoverable_return_cost: Dec;
}

/** The 21 contract metrics: money as 2dp strings, rates as 6dp strings or null, counts as ints. */
export interface Metrics {
  gross_sales: string;
  allocated_discounts: string;
  merchandise_credits: string;
  net_merchandise_sales: string;
  cogs: string;
  recoverable_return_cost: string;
  gross_profit: string;
  shipping_revenue: string;
  shipping_cost: string;
  other_variable_costs: string;
  contribution_margin: string;
  eligible_net_revenue: string;
  contribution_margin_rate: string | null;
  discount_rate: string | null;
  return_rate: string | null;
  average_order_value: string | null;
  allocation_residual: string;
  eligible_orders: number;
  eligible_shipment_lines: number;
  shipped_units: number;
  returned_units: number;
}
export const METRIC_KEYS: readonly (keyof Metrics)[] = [
  "gross_sales", "allocated_discounts", "merchandise_credits", "net_merchandise_sales", "cogs",
  "recoverable_return_cost", "gross_profit", "shipping_revenue", "shipping_cost", "other_variable_costs",
  "contribution_margin", "eligible_net_revenue", "contribution_margin_rate", "discount_rate",
  "return_rate", "average_order_value", "allocation_residual", "eligible_orders",
  "eligible_shipment_lines", "shipped_units", "returned_units",
];

// ---- published snapshot ---------------------------------------------------------------------
export interface Manifest {
  contract_version: string;
  dataset_hash: string;
  dataset_version: string;
  generated_at: string;
  code_sha?: string;
  designed_relationships?: string[];
  generator: { name: string; seed: number; parameters: Record<string, unknown> };
  injection_manifest: string;
  row_counts: Record<string, number>;
}
export interface EntityFile<T> { entity: string; dataset_version: string; rows: T[] }
