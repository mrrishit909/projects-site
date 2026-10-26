// The per-invoice derived view for the invoice desk: evidence (the document as structured fields, source hash, lineage, merge)
// and decision (match per line, exceptions with assignment history, approval trail with the policy in force, export, credits).
// Everything is read from the derived book; nothing is invented. Strings are display-ready.
import { effectivePolicy, type ExportRow } from "./book";
import { lineMoney } from "./amounts";
import { fmt, rescale, s2, s4q } from "./num";
import { isoZ } from "./time";
import type { PipelineResult } from "./pipeline";
import type { Approval, Row } from "./types";

export interface LineView {
  invoice_line_id: string; po_line_id: string; product_code: string; quantity: string; unit_price: string; extended: string; stated_amount: string | null;
  status: string; reason_code: string | null; ordered: string | null; net_received: string | null; previously_invoiced: string | null; this_invoice: string;
  available: string | null; quantity_variance: string | null; price_variance: string | null; po_price: string | null; explanation: string;
}
export interface AssignmentView { assigned_at: string; owner_id: string; assigned_by: string | null; note: string | null }
export interface ExceptionView { exception_id: string; exception_type: string; owner_id: string | null; status: string; created_at: string | null; resolved_at: string | null; stored_status: string | null; assignments: AssignmentView[] }
export interface ApprovalView {
  approval_id: string; actor_id: string; actor_role: string; decision: string; decided_at: string; reason: string | null; verdict: string; policy_id: string | null;
  policy_limit: string | null; policy_role: string | null; separation: "different from the creator" | "same as the creator"; role_allowed: boolean | null;
}
export interface InvoiceView {
  invoice_id: string; vendor_id: string; vendor_name: string; invoice_number: string; invoice_date: string; currency: string; created_by: string; tax_rate: string;
  source_sha256: string; source_filename: string; idempotency_key: string; imported_at: string; status: string;
  subtotal: string; tax: string; freight: string; invoice_discount: string; total: string; declared_total: string; rounding_difference: string; in_book: boolean;
  lines: LineView[]; merged_into: string | null; merge_reason: string | null; merge_group_key: string | null;
  merged_in: { invoice_id: string; reason: string; imported_at: string; source_sha256: string; source_filename: string }[];
  exceptions: ExceptionView[]; resolved_exceptions: ExceptionView[]; approvals: ApprovalView[]; approved_by: string | null; approved_at: string | null;
  export: ExportRow | null; credits: { credit_id: string; credit_amount: string; credited_at: string | null }[]; credit_total: string; approved_payable: string | null;
  policy_now: { policy_id: string; limit: string; role: string } | null;
}
interface Index {
  approvals: Map<string, Approval[]>; credits: Map<string, { credit_id: string; credit_amount: bigint; credited_at: number | null }[]>;
  mergedIn: Map<string, string[]>; assignments: Map<string, AssignmentView[]>; exceptionRows: Map<string, Row>; exceptionsByInvoice: Map<string, Row[]>; vendors: Map<string, string>;
}
const cache = new WeakMap<PipelineResult, Index>();
function index(r: PipelineResult): Index {
  let ix = cache.get(r);
  if (ix) return ix;
  const push = <T,>(m: Map<string, T[]>, k: string, v: T): void => { (m.get(k) ?? m.set(k, []).get(k)!).push(v); };
  const approvals = new Map<string, Approval[]>(), credits: Index["credits"] = new Map(), mergedIn = new Map<string, string[]>(), assignments = new Map<string, AssignmentView[]>();
  for (const a of r.population.approvals) push(approvals, a.invoice_id, a);
  for (const a of approvals.values()) a.sort((x, y) => x.decided_at - y.decided_at || (x.approval_id < y.approval_id ? -1 : 1));
  for (const c of r.population.credit_notes) push(credits, c.invoice_id, c);
  for (const [m, c] of r.book.mergedInto) push(mergedIn, c, m);
  for (const a of [...r.population.assignments].sort((x, y) => x.assigned_at - y.assigned_at)) push(assignments, a.exception_id, { assigned_at: isoZ(a.assigned_at), owner_id: a.owner_id, assigned_by: a.assigned_by, note: a.note });
  const byInv = new Map<string, Row[]>();
  for (const e of r.exceptionRows) push(byInv, e.invoice_id as string, e);
  ix = { approvals, credits, mergedIn, assignments, exceptionRows: new Map(r.exceptionRows.map((e) => [e.exception_id as string, e])), exceptionsByInvoice: byInv, vendors: new Map(r.population.vendors.map((v) => [v.vendor_id, v.vendor_name])) };
  cache.set(r, ix);
  return ix;
}
const sOrNull = (v: unknown): string | null => (typeof v === "string" ? v : null);

export function invoiceView(r: PipelineResult, id: string): InvoiceView | null {
  const { book, population: pop } = r;
  const inv = book.invoices.get(id);
  if (!inv) return null;
  const ix = index(r);
  const st = book.run.invoices.get(id);
  const lineRows = new Map(book.run.lines.filter((l) => l.invoice_id === id).map((l) => [l.invoice_line_id, l]));
  const poLines = new Map(pop.po_lines.map((p) => [p.po_line_id, p]));
  const lines: LineView[] = inv.lines.map((l) => {
    const m = lineRows.get(l.invoice_line_id);
    return {
      invoice_line_id: l.invoice_line_id, po_line_id: l.po_line_id, product_code: poLines.get(l.po_line_id)?.product_code ?? "unknown", quantity: s4q(l.quantity), unit_price: fmt(l.unit_price, 6),
      extended: s2(lineMoney(l)), stated_amount: l.line_amount === null ? null : s2(l.line_amount),
      status: m?.status ?? "not matched", reason_code: m?.reason_code ?? null, ordered: m?.ordered != null ? s4q(m.ordered) : null, net_received: m?.net_received != null ? s4q(m.net_received) : null,
      previously_invoiced: m?.previously_invoiced != null ? s4q(m.previously_invoiced) : null, this_invoice: s4q(l.quantity), available: m?.available != null ? s4q(m.available) : null,
      quantity_variance: m?.quantity_variance != null ? s4q(m.quantity_variance) : null, price_variance: m?.price_variance != null ? fmt(rescale(m.price_variance, 6, 4), 4) : null,
      po_price: m?.po_price != null ? fmt(m.po_price, 6) : null, explanation: m?.explanation ?? "this invoice is not in the book (merged, rejected or invalid), so no match was run",
    };
  }).sort((a, b) => (a.invoice_line_id < b.invoice_line_id ? -1 : 1));
  const mergedRec = book.mergedRecords.find((m) => m.id === id) ?? null;
  const exceptions: ExceptionView[] = book.exceptions.filter((e) => e.invoice_id === id).map((e) => {
    const row = ix.exceptionRows.get(e.exception_id);
    return { exception_id: e.exception_id, exception_type: e.exception_type, owner_id: e.owner_id, status: e.status, created_at: sOrNull(row?.created_at), resolved_at: sOrNull(row?.resolved_at), stored_status: sOrNull(row?.status), assignments: ix.assignments.get(e.exception_id) ?? [] };
  });
  const live = new Set(exceptions.map((e) => e.exception_id));
  const resolved_exceptions: ExceptionView[] = (ix.exceptionsByInvoice.get(id) ?? []).filter((e) => !live.has(e.exception_id as string)).map((row) => ({
    exception_id: row.exception_id as string, exception_type: row.exception_type as string, owner_id: sOrNull(row.owner_id), status: "resolved", created_at: sOrNull(row.created_at),
    resolved_at: sOrNull(row.resolved_at), stored_status: sOrNull(row.status), assignments: ix.assignments.get(row.exception_id as string) ?? [],
  }));
  const approvals: ApprovalView[] = (ix.approvals.get(id) ?? []).map((a) => {
    const v = book.verdicts.get(a.approval_id);
    const pol = effectivePolicy(pop.approval_policies, a.decided_at);
    return {
      approval_id: a.approval_id, actor_id: a.actor_id, actor_role: a.actor_role, decision: a.decision, decided_at: isoZ(a.decided_at), reason: a.reason, verdict: v?.code ?? "AFTER_AS_OF",
      policy_id: pol?.policy_id ?? null, policy_limit: pol ? s2(pol.amount_limit) : null, policy_role: pol?.reviewer_role ?? null,
      separation: a.actor_id === inv.created_by ? "same as the creator" : "different from the creator",
      role_allowed: pol ? a.actor_role === pol.reviewer_role || a.actor_role === pol.escalation_role : null,
    };
  });
  const polNow = effectivePolicy(pop.approval_policies, book.cutoff);
  const credits = (ix.credits.get(id) ?? []).filter((c) => book.credits.has(id) && (c.credited_at === null || c.credited_at <= book.cutoff));
  const creditTotal = book.credits.get(id) ?? 0n;
  const appr = book.approvedBy.get(id) ?? null;
  return {
    invoice_id: id, vendor_id: inv.vendor_id, vendor_name: ix.vendors.get(inv.vendor_id) ?? "unknown vendor", invoice_number: inv.invoice_number, invoice_date: inv.invoice_date,
    currency: inv.currency, created_by: inv.created_by, tax_rate: fmt(inv.tax_rate, 6), source_sha256: inv.source_sha256, source_filename: inv.source_filename,
    idempotency_key: inv.idempotency_key, imported_at: isoZ(inv.imported_at), status: book.status.get(id)!,
    subtotal: s2(st?.subtotal ?? 0n), tax: s2(st?.tax ?? 0n), freight: s2(inv.freight), invoice_discount: s2(inv.invoice_discount), total: s2(st?.total ?? 0n),
    declared_total: s2(inv.declared_total), rounding_difference: s2(st?.rounding_difference ?? 0n), in_book: !!st, lines,
    merged_into: book.mergedInto.get(id) ?? null, merge_reason: mergedRec?.reason_code ?? null, merge_group_key: mergedRec?.group_key ?? null,
    merged_in: (ix.mergedIn.get(id) ?? []).map((m) => {
      const mi = book.invoices.get(m)!;
      return { invoice_id: m, reason: book.mergedRecords.find((x) => x.id === m)?.reason_code ?? "", imported_at: isoZ(mi.imported_at), source_sha256: mi.source_sha256, source_filename: mi.source_filename };
    }),
    exceptions, resolved_exceptions, approvals, approved_by: appr?.actor_id ?? null, approved_at: appr ? isoZ(appr.decided_at) : null,
    export: book.exportRows.find((e) => e.invoice_id === id) ?? null,
    credits: credits.map((c) => ({ credit_id: c.credit_id, credit_amount: s2(c.credit_amount), credited_at: c.credited_at === null ? null : isoZ(c.credited_at) })),
    credit_total: s2(creditTotal), approved_payable: book.approved.has(id) ? s2((st?.total ?? 0n) - creditTotal) : null,
    policy_now: polNow ? { policy_id: polNow.policy_id, limit: s2(polNow.amount_limit), role: polNow.reviewer_role } : null,
  };
}
