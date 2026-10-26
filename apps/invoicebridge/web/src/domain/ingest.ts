// Ingest (ingest.py): validate a batch of raw rows. Every row is accepted, rejected (reason code, raw row kept) or, for an
// invoice, merged into the earliest import of the same obligation. An invoice is atomic: one bad line, an unknown vendor or a
// malformed header rejects the header, every sibling line and any approval or credit note that names it (DEPENDENT_REJECTED).
import { invoiceAmounts } from "./amounts";
import {
  CREDIT_EXCEEDS_INVOICE, DEPENDENT_REJECTED, DUPLICATE_ID, ENTITIES, ID_KEYS, NON_POSITIVE_AMOUNT, NON_POSITIVE_QUANTITY, UNKNOWN_INVOICE,
  UNKNOWN_PO, UNKNOWN_PO_LINE, UNKNOWN_VENDOR, type Entity,
} from "./contract";
import { detectDuplicates, type MergedRecord } from "./duplicates";
import { DomainError, MALFORMED_RECORD } from "./num";
import { cmp } from "./order";
import { parseApproval, parseCredit, parseExportRequest, parseInvoice, parseLine, parsePo, parsePoLine, parsePolicy, parseReceipt, parseTolerances, parseVendor } from "./models";
import type { Approval, CreditNote, ExportRequest, Invoice, InvoiceLine, PipelineInputs, Policy, PoLine, Population, PurchaseOrder, Receipt, Row, Tolerances, Vendor } from "./types";

export interface Rejection { entity: Entity; id: string; status: "rejected"; reason_code: string; raw_row: Row }
export interface IngestResult {
  accepted: { vendors: Vendor[]; purchase_orders: PurchaseOrder[]; po_lines: PoLine[]; receipts: Receipt[]; invoices: Invoice[]; invoice_lines: InvoiceLine[]; credit_notes: CreditNote[]; approval_policies: Policy[]; approvals: Approval[] };
  rejected: Rejection[];
  merged_records: MergedRecord[];
  merged_into: Map<string, string>;
  groups_detected: number;
  counts: Record<Entity, { accepted: number; rejected: number; merged: number }>;
  tolerances: Tolerances;
  export_requests: ExportRequest[];
}

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const rid = (row: unknown, key: string): string => (isRow(row) && typeof row[key] === "string" ? (row[key] as string) : "");
const codeOf = (e: unknown): string => (e instanceof DomainError ? e.code : MALFORMED_RECORD);

export function validateBatch(raw: PipelineInputs): IngestResult {
  const rej: Rejection[] = [];
  const acc = { vendors: [] as Vendor[], purchase_orders: [] as PurchaseOrder[], po_lines: [] as PoLine[], receipts: [] as Receipt[], invoices: [] as Invoice[], invoice_lines: [] as InvoiceLine[], credit_notes: [] as CreditNote[], approval_policies: [] as Policy[], approvals: [] as Approval[] };
  const ids = Object.fromEntries(ENTITIES.map((e) => [e, new Set<string>()])) as Record<Entity, Set<string>>;
  const reject = (ent: Entity, row: unknown, code: string): void => {
    rej.push({ entity: ent, id: rid(row, ID_KEYS[ent]), status: "rejected", reason_code: code, raw_row: isRow(row) ? row : { value: String(row) } });
  };
  const parsed = <T,>(ent: Entity, row: unknown, fn: (r: Row) => T): T | null => {
    if (!isRow(row)) { reject(ent, row, MALFORMED_RECORD); return null; }
    try { return fn(row); } catch (e) { if (!(e instanceof DomainError)) throw e; reject(ent, row, e.code); return null; }
  };
  const take = (ent: Entity, row: Row): void => { ids[ent].add(row[ID_KEYS[ent]] as string); };
  const section = (ent: string): unknown[] => { const v = (raw as Record<string, unknown>)[ent]; return Array.isArray(v) ? v : []; };

  let tolerances: Tolerances;
  try { tolerances = parseTolerances(raw.tolerances); } catch { tolerances = parseTolerances(null); }

  for (const r of section("vendors")) {
    const o = parsed("vendors", r, parseVendor);
    if (!o) continue;
    if (ids.vendors.has(o.vendor_id)) reject("vendors", r, DUPLICATE_ID); else { take("vendors", r as Row); acc.vendors.push(o); }
  }
  for (const r of section("purchase_orders")) {
    const o = parsed("purchase_orders", r, parsePo);
    if (!o) continue;
    if (ids.purchase_orders.has(o.po_id)) reject("purchase_orders", r, DUPLICATE_ID);
    else if (!ids.vendors.has(o.vendor_id)) reject("purchase_orders", r, UNKNOWN_VENDOR);
    else { take("purchase_orders", r as Row); acc.purchase_orders.push(o); }
  }
  for (const r of section("po_lines")) {
    const o = parsed("po_lines", r, parsePoLine);
    if (!o) continue;
    if (ids.po_lines.has(o.po_line_id)) reject("po_lines", r, DUPLICATE_ID);
    else if (!ids.purchase_orders.has(o.po_id)) reject("po_lines", r, UNKNOWN_PO);
    else if (o.quantity <= 0n) reject("po_lines", r, NON_POSITIVE_QUANTITY);
    else { take("po_lines", r as Row); acc.po_lines.push(o); }
  }
  for (const r of section("receipts")) {
    const o = parsed("receipts", r, parseReceipt);
    if (!o) continue;
    if (ids.receipts.has(o.receipt_id)) reject("receipts", r, DUPLICATE_ID);
    else if (!ids.po_lines.has(o.po_line_id)) reject("receipts", r, UNKNOWN_PO_LINE);
    else if (o.received_quantity <= 0n) reject("receipts", r, NON_POSITIVE_QUANTITY);
    else { take("receipts", r as Row); acc.receipts.push(o); }
  }

  // invoices are atomic
  const headerRows = section("invoices");
  const headerIds = new Set(headerRows.filter(isRow).map((r) => rid(r, "invoice_id")));
  const linesByInv = new Map<string, Row[]>();
  for (const l of section("invoice_lines")) {
    const iid = rid(l, "invoice_id");
    if (!isRow(l) || !headerIds.has(iid)) reject("invoice_lines", l, isRow(l) ? UNKNOWN_INVOICE : MALFORMED_RECORD);
    else (linesByInv.get(iid) ?? linesByInv.set(iid, []).get(iid)!).push(l);
  }
  const seenLineIds = new Set<string>();
  const rejectedInvoices = new Set<string>();
  for (const h of headerRows) {
    if (!isRow(h) || !rid(h, "invoice_id")) { reject("invoices", h, MALFORMED_RECORD); continue; }
    const iid = h.invoice_id as string;
    if (ids.invoices.has(iid) || rejectedInvoices.has(iid)) { reject("invoices", h, DUPLICATE_ID); continue; }
    const ls = linesByInv.get(iid) ?? [];
    linesByInv.delete(iid);
    let headerErr: unknown = null;
    let header: Invoice | null = null;
    try { header = parseInvoice(h); } catch (e) { if (!(e instanceof DomainError)) throw e; headerErr = e; }
    const parsedLines: InvoiceLine[] = [];
    const lineCodes = new Map<number, string>();
    ls.forEach((l, n) => {
      let ln: InvoiceLine;
      try { ln = parseLine(l); } catch (e) { if (!(e instanceof DomainError)) throw e; lineCodes.set(n, e.code); return; }
      if (ln.quantity <= 0n) lineCodes.set(n, NON_POSITIVE_QUANTITY);
      else if (seenLineIds.has(ln.invoice_line_id)) lineCodes.set(n, DUPLICATE_ID);
      else { parsedLines.push(ln); seenLineIds.add(ln.invoice_line_id); }
    });
    let code = "";
    if (headerErr !== null) code = codeOf(headerErr);
    else if (!ids.vendors.has(header!.vendor_id)) code = UNKNOWN_VENDOR;
    else if (ls.length === 0) code = MALFORMED_RECORD;
    else if (lineCodes.size > 0) code = DEPENDENT_REJECTED;
    if (code) {
      rejectedInvoices.add(iid);
      reject("invoices", h, code);
      ls.forEach((l, n) => reject("invoice_lines", l, lineCodes.get(n) ?? DEPENDENT_REJECTED));
      continue;
    }
    const inv = parseInvoice(h, parsedLines);
    take("invoices", h);
    acc.invoices.push(inv);
    acc.invoice_lines.push(...parsedLines);
    for (const ln of parsedLines) ids.invoice_lines.add(ln.invoice_line_id);
  }
  for (const ls of linesByInv.values()) for (const l of ls) reject("invoice_lines", l, DUPLICATE_ID);

  const invById = new Map(acc.invoices.map((i) => [i.invoice_id, i]));
  const credited = new Map<string, bigint>();
  for (const [ent, fn] of [["credit_notes", parseCredit], ["approvals", parseApproval]] as const) {
    for (const r of section(ent)) {
      const o = parsed(ent, r, fn as (r: Row) => CreditNote | Approval);
      if (!o) continue;
      if (rejectedInvoices.has(o.invoice_id)) reject(ent, r, DEPENDENT_REJECTED);
      else if (!invById.has(o.invoice_id)) reject(ent, r, UNKNOWN_INVOICE);
      else if (ids[ent].has(rid(r, ID_KEYS[ent]))) reject(ent, r, DUPLICATE_ID);
      else if (ent === "credit_notes" && (o as CreditNote).credit_amount <= 0n) reject(ent, r, NON_POSITIVE_AMOUNT);
      else if (ent === "credit_notes" && (credited.get(o.invoice_id) ?? 0n) + (o as CreditNote).credit_amount > invoiceAmounts(invById.get(o.invoice_id)!)[2]) reject(ent, r, CREDIT_EXCEEDS_INVOICE);
      else {
        if (ent === "credit_notes") credited.set(o.invoice_id, (credited.get(o.invoice_id) ?? 0n) + (o as CreditNote).credit_amount);
        take(ent, r as Row);
        if (ent === "credit_notes") acc.credit_notes.push(o as CreditNote); else acc.approvals.push(o as Approval);
      }
    }
  }
  for (const r of section("approval_policies")) {
    const o = parsed("approval_policies", r, parsePolicy);
    if (!o) continue;
    if (ids.approval_policies.has(o.policy_id)) reject("approval_policies", r, DUPLICATE_ID); else { take("approval_policies", r as Row); acc.approval_policies.push(o); }
  }
  const exportRequests: ExportRequest[] = [];
  for (const r of section("export_requests")) {
    try { exportRequests.push(parseExportRequest(r as Row)); } catch (e) { if (!(e instanceof DomainError)) throw e; }
  }
  rej.sort((a, b) => cmp(a.entity, b.entity) || cmp(a.id, b.id));

  const { mergedInto, records, groups } = detectDuplicates(acc.invoices);
  const counts = Object.fromEntries(ENTITIES.map((e) => [e, { accepted: acc[e].length, rejected: rej.filter((r) => r.entity === e).length, merged: 0 }])) as IngestResult["counts"];
  counts.invoices.accepted -= mergedInto.size;
  counts.invoices.merged = mergedInto.size;
  let mergedLines = 0;
  for (const i of mergedInto.keys()) mergedLines += invById.get(i)!.lines.length;
  counts.invoice_lines.accepted -= mergedLines;
  counts.invoice_lines.merged = mergedLines;
  return { accepted: acc, rejected: rej, merged_records: records, merged_into: mergedInto, groups_detected: groups, counts, tolerances, export_requests: exportRequests };
}

/** IngestResult.population(): typed facts for the derivation. ``stored`` adds the stored exception ids and assignments. */
export function populationOf(ing: IngestResult, stored?: { exceptions: Row[]; assignments: Row[] }): Population {
  const a = ing.accepted;
  // invoice_lines are parsed per header inside accepted.invoices[].lines; the flat list is only for counts
  return {
    vendors: a.vendors, purchase_orders: a.purchase_orders, po_lines: a.po_lines, receipts: a.receipts, invoices: a.invoices, credit_notes: a.credit_notes,
    approval_policies: a.approval_policies, approvals: a.approvals, export_requests: ing.export_requests, tolerances: ing.tolerances,
    exceptions: (stored?.exceptions ?? []).map((r) => ({ exception_id: r.exception_id as string, invoice_id: r.invoice_id as string, exception_type: r.exception_type as string })),
    assignments: (stored?.assignments ?? []).map((r) => ({
      exception_id: r.exception_id as string, owner_id: r.owner_id as string, assigned_at: parseTsLoose(r.assigned_at),
      assigned_by: typeof r.assigned_by === "string" ? r.assigned_by : null, note: typeof r.note === "string" ? r.note : null,
    })),
  };
}
import { parseTs } from "./time";
const parseTsLoose = (v: unknown): number => parseTs(v, "assigned_at");
