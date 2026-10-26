// Invoice amounts, identity and validation (amounts.py). Tax once per invoice on the UNROUNDED subtotal, ROUND_HALF_UP.
import { fmt, money10, roundDiv, s2, sumB } from "./num";
import type { Invoice, InvoiceLine, Vendor } from "./types";
import { dayOf } from "./time";

/** quantity x unit price, scale 1e-10 (exact). */
export const lineExtended = (l: InvoiceLine): bigint => l.quantity * l.unit_price;
export const lineMoney = (l: InvoiceLine): bigint => money10(lineExtended(l));

/** [subtotal, tax, total] in cents. total = subtotal + tax + freight - invoice_discount, in that declared order. */
export function invoiceAmounts(inv: Invoice): [bigint, bigint, bigint] {
  const raw = sumB(inv.lines.map(lineExtended));
  const sub = roundDiv(raw, 100_000_000n);
  const tax = roundDiv(raw * inv.tax_rate, 100_000_000_000_000n);
  return [sub, tax, sub + tax + inv.freight - inv.invoice_discount];
}
/** D-P5-6: upper-case, keep letters and digits only. */
export const normaliseNumber = (n: string): string => n.toUpperCase().replace(/[^A-Z0-9]/g, "");
export const identityKey = (inv: Invoice): string => `${inv.vendor_id}|${normaliseNumber(inv.invoice_number)}|${inv.invoice_date}|${s2(invoiceAmounts(inv)[2])}`;

export function validateInvoice(inv: Invoice, vendor: Vendor | undefined): [string, string][] {
  const out: [string, string][] = [];
  if (!vendor) out.push(["UNKNOWN_VENDOR", "the vendor is not in the vendor master"]);
  else if (!vendor.active) out.push(["VENDOR_INACTIVE", "the vendor is not active"]);
  if (inv.lines.length === 0) out.push(["NO_LINES", "an invoice needs at least one line"]);
  if (invoiceAmounts(inv)[2] < 0n) out.push(["NEGATIVE_TOTAL", "the computed total is negative; a negative payable is a credit note"]);
  if (inv.invoice_date > dayOf(inv.imported_at)) out.push(["INVOICE_DATE_IN_FUTURE", "the invoice date is after the day it was imported"]);
  return out;
}
export const money = (cents: bigint): string => fmt(cents, 2);
