// Typed records (models.py). Money is cents, quantity ten-thousandths, unit price and rate millionths (bigint).
export type Row = Record<string, unknown>;
export interface Vendor { vendor_id: string; vendor_name: string; tax_reference: string; currency: string; active: boolean }
export interface PurchaseOrder { po_id: string; vendor_id: string; ordered_at: number; status: string; currency: string }
export interface PoLine { po_line_id: string; po_id: string; product_code: string; quantity: bigint; unit_price: bigint }
export interface Receipt { receipt_id: string; po_line_id: string; received_quantity: bigint; received_at: number; reversed: boolean }
export interface InvoiceLine { invoice_line_id: string; invoice_id: string; po_line_id: string; quantity: bigint; unit_price: bigint; line_amount: bigint | null }
export interface Invoice {
  invoice_id: string; vendor_id: string; invoice_number: string; invoice_date: string; currency: string;
  tax_rate: bigint; freight: bigint; invoice_discount: bigint; declared_total: bigint; created_by: string;
  source_sha256: string; source_filename: string; idempotency_key: string; imported_at: number;
  lines: InvoiceLine[]; valid: boolean | null;
}
export interface CreditNote { credit_id: string; invoice_id: string; credit_amount: bigint; credited_at: number | null }
export interface Policy { policy_id: string; version_number: number; amount_limit: bigint; reviewer_role: string; escalation_role: string | null; effective_from: number }
export interface Approval { approval_id: string; invoice_id: string; actor_id: string; actor_role: string; decision: string; decided_at: number; reason: string | null }
export interface ExportRequest { batch_id: string; idempotency_key: string; invoice_ids: string[]; exported_at: number }
export interface ExceptionRecord { exception_id: string; invoice_id: string; exception_type: string }
export interface Assignment { exception_id: string; owner_id: string; assigned_at: number; assigned_by: string | null; note: string | null }
export interface Tolerances {
  /** scale 1e-6 */ price_per_unit: bigint; rounding_per_line: bigint; rounding_per_invoice: bigint;
  raw: { price_per_unit: string; rounding_per_line: string; rounding_per_invoice: string };
}
export interface Population {
  vendors: Vendor[]; purchase_orders: PurchaseOrder[]; po_lines: PoLine[]; receipts: Receipt[]; invoices: Invoice[];
  credit_notes: CreditNote[]; approval_policies: Policy[]; approvals: Approval[]; export_requests: ExportRequest[];
  exceptions: ExceptionRecord[]; assignments: Assignment[]; tolerances: Tolerances;
}
/** The shape of inputs.json (and of the published entity files assembled by data/load.ts). */
export interface PipelineInputs {
  contract_version?: number; as_of?: string; snapshot_cutoffs?: string[]; tolerances?: Row;
  vendors?: Row[]; purchase_orders?: Row[]; po_lines?: Row[]; receipts?: Row[]; invoices?: Row[]; invoice_lines?: Row[];
  credit_notes?: Row[]; approval_policies?: Row[]; approvals?: Row[]; export_requests?: Row[];
  exceptions?: Row[]; exception_assignments?: Row[];
}
