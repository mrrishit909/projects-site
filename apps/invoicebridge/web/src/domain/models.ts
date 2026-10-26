// Row parsers (models.py): a raw input row to a typed record, or MALFORMED_RECORD for anything not exactly the documented shape.
import { DEFAULT_TOLERANCES } from "./contract";
import { malformed, parseDec } from "./num";
import { parseDate, parseTs } from "./time";
import type { Approval, CreditNote, ExportRequest, Invoice, InvoiceLine, PoLine, Policy, PurchaseOrder, Receipt, Row, Tolerances, Vendor } from "./types";

const SHA = /^[0-9a-f]{64}$/;
const CURRENCY = /^[A-Z]{3}$/;

function str(row: Row, name: string): string;
function str(row: Row, name: string, optional: true): string | null;
function str(row: Row, name: string, optional = false): string | null {
  const v = row[name];
  if ((v === undefined || v === null) && optional) return null;
  if (typeof v !== "string" || v.trim() === "" || v.length > 256) throw malformed(name, "must be a non-empty string");
  return v;
}
function bool(row: Row, name: string): boolean {
  const v = row[name];
  if (typeof v !== "boolean") throw malformed(name, "must be true or false");
  return v;
}
const ts = (row: Row, name: string): number => parseTs(row[name], name);
const currency = (row: Row): string => {
  const c = str(row, "currency");
  if (!CURRENCY.test(c)) throw malformed("currency", "must be a three-letter upper-case code");
  return c;
};

export function parseTolerances(raw: Row | null | undefined): Tolerances {
  const r = { ...DEFAULT_TOLERANCES, ...(raw ?? {}) } as Row;
  const keys = ["price_per_unit", "rounding_per_line", "rounding_per_invoice"] as const;
  const v = keys.map((k) => parseDec(r[k], k, 6)) as [bigint, bigint, bigint];
  if (v.some((x) => x < 0n)) throw malformed("tolerances", "must not be negative");
  const text = (k: (typeof keys)[number]): string => (typeof r[k] === "string" ? (r[k] as string).trim() : String(r[k]));
  return { price_per_unit: v[0], rounding_per_line: v[1], rounding_per_invoice: v[2], raw: { price_per_unit: text("price_per_unit"), rounding_per_line: text("rounding_per_line"), rounding_per_invoice: text("rounding_per_invoice") } };
}
export function parseVendor(r: Row): Vendor {
  return { vendor_id: str(r, "vendor_id"), vendor_name: str(r, "vendor_name"), tax_reference: str(r, "tax_reference"), currency: currency(r), active: bool(r, "active") };
}
export function parsePo(r: Row): PurchaseOrder {
  return { po_id: str(r, "po_id"), vendor_id: str(r, "vendor_id"), ordered_at: ts(r, "ordered_at"), status: str(r, "status"), currency: currency(r) };
}
export function parsePoLine(r: Row): PoLine {
  const price = parseDec(r.unit_price, "unit_price", 6);
  if (price < 0n) throw malformed("unit_price", "must not be negative");
  return { po_line_id: str(r, "po_line_id"), po_id: str(r, "po_id"), product_code: str(r, "product_code"), quantity: parseDec(r.quantity, "quantity", 4), unit_price: price };
}
export function parseReceipt(r: Row): Receipt {
  return { receipt_id: str(r, "receipt_id"), po_line_id: str(r, "po_line_id"), received_quantity: parseDec(r.received_quantity, "received_quantity", 4), received_at: ts(r, "received_at"), reversed: bool(r, "reversed") };
}
export function parseLine(r: Row): InvoiceLine {
  const price = parseDec(r.unit_price, "unit_price", 6);
  if (price < 0n) throw malformed("unit_price", "must not be negative");
  const la = r.line_amount;
  return {
    invoice_line_id: str(r, "invoice_line_id"), invoice_id: str(r, "invoice_id"), po_line_id: str(r, "po_line_id"),
    quantity: parseDec(r.quantity, "quantity", 4), unit_price: price, line_amount: la === undefined || la === null ? null : parseDec(la, "line_amount", 2),
  };
}
export function parseInvoice(r: Row, lines: InvoiceLine[] = []): Invoice {
  const cur = currency(r);
  const sha = str(r, "source_sha256");
  if (!SHA.test(sha)) throw malformed("source_sha256", "must be 64 lower-case hex digits");
  const rate = parseDec(r.tax_rate, "tax_rate", 6), freight = parseDec(r.freight, "freight", 2), disc = parseDec(r.invoice_discount, "invoice_discount", 2);
  if (rate < 0n || rate > 1_000_000n) throw malformed("tax_rate", "must be between 0 and 1");
  if (freight < 0n || disc < 0n) throw malformed(freight < 0n ? "freight" : "invoice_discount", "must not be negative");
  const valid = "validity" in r ? r.validity : true;
  if (valid !== null && typeof valid !== "boolean") throw malformed("validity", "must be true, false or null");
  return {
    invoice_id: str(r, "invoice_id"), vendor_id: str(r, "vendor_id"), invoice_number: str(r, "invoice_number"), invoice_date: parseDate(r.invoice_date, "invoice_date"),
    currency: cur, tax_rate: rate, freight, invoice_discount: disc, declared_total: parseDec(r.declared_total, "declared_total", 2), created_by: str(r, "created_by"),
    source_sha256: sha, source_filename: str(r, "source_filename"), idempotency_key: str(r, "idempotency_key"), imported_at: ts(r, "imported_at"), lines, valid,
  };
}
export function parseCredit(r: Row): CreditNote {
  const at = r.credited_at;
  return { credit_id: str(r, "credit_id"), invoice_id: str(r, "invoice_id"), credit_amount: parseDec(r.credit_amount, "credit_amount", 2), credited_at: at === undefined || at === null ? null : parseTs(at, "credited_at") };
}
export function parsePolicy(r: Row): Policy {
  const v = r.version_number;
  if (typeof v !== "number" || !Number.isInteger(v) || v < 1) throw malformed("version_number", "must be a positive integer");
  const limit = parseDec(r.amount_limit, "amount_limit", 2);
  if (limit < 0n) throw malformed("amount_limit", "must not be negative");
  return { policy_id: str(r, "policy_id"), version_number: v, amount_limit: limit, reviewer_role: str(r, "reviewer_role"), escalation_role: str(r, "escalation_role", true), effective_from: ts(r, "effective_from") };
}
export function parseApproval(r: Row): Approval {
  const decision = str(r, "decision");
  if (decision !== "approve" && decision !== "reject") throw malformed("decision", "must be approve or reject");
  if (decision === "reject" && str(r, "reason", true) === null) throw malformed("reason", "is required for a rejection");
  return { approval_id: str(r, "approval_id"), invoice_id: str(r, "invoice_id"), actor_id: str(r, "actor_id"), actor_role: str(r, "actor_role"), decision, decided_at: ts(r, "decided_at"), reason: str(r, "reason", true) };
}
export function parseExportRequest(r: Row): ExportRequest {
  const ids = r.invoice_ids;
  if (!Array.isArray(ids) || !ids.every((i) => typeof i === "string" && i !== "")) throw malformed("invoice_ids", "must be a list of invoice ids");
  return { batch_id: str(r, "batch_id"), idempotency_key: str(r, "idempotency_key"), invoice_ids: ids as string[], exported_at: ts(r, "exported_at") };
}
