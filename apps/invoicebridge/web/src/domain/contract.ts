// Contract constants (domain/invoicebridge/contract.py, docs/contracts.md D-01..D-07).
export const CONTRACT_VERSION = 1;
export const RULE_VERSION = "1";
export const ENTITIES = ["vendors", "purchase_orders", "po_lines", "receipts", "invoices", "invoice_lines", "credit_notes", "approval_policies", "approvals"] as const;
export type Entity = (typeof ENTITIES)[number];
/** Metric names in the order of expected.json["metrics"]; snapshot_cutoffs sit beside them, not among them. */
export const METRIC_KEYS = ["matched", "obligations", "exceptions", "duplicates", "quantities", "snapshots", "rates", "processing", "approvals", "payable", "export"] as const;
export type MetricKey = (typeof METRIC_KEYS)[number];
export const EXCEPTION_CODES = ["QUANTITY_BLOCKED", "PRICE_VARIANCE", "NO_PO_LINE", "ROUNDING_EXCEPTION", "CURRENCY_MISMATCH"] as const;
export const DEFAULT_TOLERANCES = { price_per_unit: "0.00", rounding_per_line: "0.01", rounding_per_invoice: "0.02" };
export const CREDITED = ["approved", "exported", "adjusted"];
export const ID_KEYS: Record<Entity, string> = {
  vendors: "vendor_id", purchase_orders: "po_id", po_lines: "po_line_id", receipts: "receipt_id", invoices: "invoice_id",
  invoice_lines: "invoice_line_id", credit_notes: "credit_id", approval_policies: "policy_id", approvals: "approval_id",
};
// reason codes
export const UNKNOWN_PO_LINE = "UNKNOWN_PO_LINE", UNKNOWN_VENDOR = "UNKNOWN_VENDOR", UNKNOWN_PO = "UNKNOWN_PO";
export const NON_POSITIVE_QUANTITY = "NON_POSITIVE_QUANTITY", DEPENDENT_REJECTED = "DEPENDENT_REJECTED";
export const DUPLICATE_ID = "DUPLICATE_ID", UNKNOWN_INVOICE = "UNKNOWN_INVOICE", NON_POSITIVE_AMOUNT = "NON_POSITIVE_AMOUNT";
export const CREDIT_EXCEEDS_INVOICE = "CREDIT_EXCEEDS_INVOICE";
export const DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY", DUPLICATE_SOURCE_BYTES = "DUPLICATE_SOURCE_BYTES";
export const NOT_MATCHED = "NOT_MATCHED", SELF_APPROVAL = "SELF_APPROVAL", ROLE_OR_LIMIT = "ROLE_OR_LIMIT";
export const NOT_REVIEWABLE = "NOT_REVIEWABLE", REJECT_AFTER_APPROVAL = "REJECT_AFTER_APPROVAL";
export const BEFORE_IMPORT = "BEFORE_IMPORT", SELF_DECISION = "SELF_DECISION", BYTES_FIELDS_CONFLICT = "BYTES_FIELDS_CONFLICT";
export const EXCEPTION_OPEN = "EXCEPTION_OPEN", NOT_APPROVED = "NOT_APPROVED";
export const APPROVED_NOT_EXPORTED = "APPROVED_NOT_EXPORTED", EXPORT_BEFORE_APPROVAL = "EXPORT_BEFORE_APPROVAL";
