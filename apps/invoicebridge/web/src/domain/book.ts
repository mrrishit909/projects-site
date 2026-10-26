// The derived book (book.py): duplicates, rejections, three-way match, approvals, exports and credits at one cutoff.
// A pure function of recorded facts; nothing stored as a status is read. ``cutoff`` is inclusive.
// D-09: an invoice with a policy-valid approval is COMMITTED: it keeps its consumption of received quantity ahead of every
// uncommitted invoice, is never displaced as the canonical copy of a duplicate group, and stays exported when a receipt is
// reversed after a valid export row.
import { invoiceAmounts } from "./amounts";
import { BEFORE_IMPORT, CREDITED, NOT_MATCHED, NOT_REVIEWABLE, REJECT_AFTER_APPROVAL, ROLE_OR_LIMIT, SELF_APPROVAL, SELF_DECISION } from "./contract";
import { detectDuplicates, type Commit, type MergedRecord } from "./duplicates";
import { matchRun, type MatchRun } from "./match";
import { s2 } from "./num";
import { cmp } from "./order";
import { sha256 } from "./sha256";
import { FAR_FUTURE, isoZ } from "./time";
import type { Approval, ExportRequest, Invoice, Policy, Population } from "./types";

/** The policy version in force at ``at`` (latest effective_from, then version, then id). */
export function effectivePolicy(policies: readonly Policy[], at: number): Policy | null {
  let best: Policy | null = null;
  for (const p of policies) {
    if (p.effective_from > at) continue;
    if (!best || p.effective_from > best.effective_from || (p.effective_from === best.effective_from && (p.version_number > best.version_number || (p.version_number === best.version_number && cmp(p.policy_id, best.policy_id) > 0)))) best = p;
  }
  return best;
}
export function roleMayApprove(policy: Policy | null, role: string, total: bigint): boolean {
  if (!policy) return false;
  if (policy.escalation_role !== null && role === policy.escalation_role) return true;
  return role === policy.reviewer_role && total <= policy.amount_limit;
}
/** D-05: sha256 of invoice_id|vendor_id|invoice_number|invoice_date|currency|amount (number as imported). */
export const contentHash = (inv: Invoice, amount: string): string => sha256([inv.invoice_id, inv.vendor_id, inv.invoice_number, inv.invoice_date, inv.currency, amount].join("|"));

export interface ExportRow { export_id: string; invoice_id: string; batch_id: string; exported_at: string; vendor_id: string; invoice_number: string; invoice_date: string; currency: string; amount: string; content_hash: string }
export interface ExceptionEntry { exception_id: string; invoice_id: string; exception_type: string; owner_id: string | null; status: "open" | "assigned" }
export interface InvalidDecision { approval_id: string; reason_code: string }
/** How each decision on file was treated (extra to the contract, for the approval trail). */
export interface Verdict { code: "COUNTED" | "SUPERSEDED" | string; policy_id: string | null }
export interface Book {
  cutoff: number; invoices: Map<string, Invoice>; mergedInto: Map<string, string>; mergedRecords: MergedRecord[]; groupsDetected: number;
  rejected: Set<string>; run: MatchRun; approved: Map<string, number>; approvedBy: Map<string, Approval>; invalidDecisions: InvalidDecision[]; verdicts: Map<string, Verdict>;
  exportRows: ExportRow[]; exportStats: { requests_received: number; batches_created: number; repeat_requests_returned_prior: number };
  exported: Map<string, string>; credits: Map<string, bigint>; status: Map<string, string>; exceptions: ExceptionEntry[]; inBook: string[];
  /** byte-twins held for review (BYTES_FIELDS_CONFLICT) -> the canonical they share bytes with */
  review: Map<string, string>;
  /** the first policy-valid approval of every committed invoice */
  firstValid: Map<string, Approval>;
  /** every export request at the cutoff with its repeat flag */
  exportLog: { request: ExportRequest; repeat: boolean }[];
  /** approved invoices a request named before the approval (invalid export row) */
  exportLate: Set<string>;
}

/** The rules of an approval that do not depend on the book: separation of duties, the policy at decision time, timing. */
function policyVerdict(pop: Population, a: Approval, inv: Invoice, total: bigint): string | null {
  if (a.actor_id === inv.created_by) return SELF_APPROVAL;
  if (!roleMayApprove(effectivePolicy(pop.approval_policies, a.decided_at), a.actor_role, total)) return ROLE_OR_LIMIT;
  if (a.decided_at < inv.imported_at) return BEFORE_IMPORT;
  return null;
}
const byDecision = (a: Approval, b: Approval): number => a.decided_at - b.decided_at || cmp(a.approval_id, b.approval_id);

/** The first policy-valid approve decision of every invoice decided by the cutoff (invoice imported by then, not failed by C02). */
export function firstValidApprovals(pop: Population, cutoff: number, invById: Map<string, Invoice>): Map<string, Approval> {
  const out = new Map<string, Approval>();
  for (const a of pop.approvals.filter((a) => a.decided_at <= cutoff && a.decision === "approve").sort(byDecision)) {
    const inv = invById.get(a.invoice_id);
    if (!inv || inv.valid === false || inv.imported_at > cutoff || out.has(a.invoice_id)) continue;
    if (policyVerdict(pop, a, inv, invoiceAmounts(inv)[2]) === null) out.set(a.invoice_id, a);
  }
  return out;
}

/** Duplicate detection over the invoices imported by the cutoff and not failed by C02, committed invoices first. */
export function duplicateGroups(pop: Population, cutoff: number, invById: Map<string, Invoice>) {
  const firstValid = firstValidApprovals(pop, cutoff, invById);
  const eligible = pop.invoices.filter((i) => i.valid !== false && i.imported_at <= cutoff);
  const committed = new Map<string, Commit>([...firstValid].map(([k, a]) => [k, [a.decided_at, a.approval_id] as Commit]));
  return { ...detectDuplicates(eligible, committed), firstValid };
}

function rejectDecisions(pop: Population, cutoff: number, mergedInto: Map<string, string>, invById: Map<string, Invoice>, firstValid: Map<string, Approval>, review: Map<string, string>, verdicts: Map<string, Verdict>): { rejected: Set<string>; invalid: InvalidDecision[] } {
  const decisions = pop.approvals.filter((a) => a.decided_at <= cutoff && a.decision === "reject").sort(byDecision);
  const rejected = new Set<string>();
  const invalid: InvalidDecision[] = [];
  for (const a of decisions) {
    const inv = invById.get(a.invoice_id);
    const pol = effectivePolicy(pop.approval_policies, a.decided_at);
    const fa = firstValid.get(a.invoice_id);
    let code: string | null = null;
    if (!inv || mergedInto.has(inv.invoice_id) || review.has(inv.invoice_id) || inv.valid !== true || inv.imported_at > cutoff) code = NOT_REVIEWABLE;
    else if (!pol || (a.actor_role !== pol.reviewer_role && a.actor_role !== pol.escalation_role)) code = ROLE_OR_LIMIT;
    else if (a.actor_id === inv.created_by) code = SELF_DECISION;
    else if (a.decided_at < inv.imported_at) code = BEFORE_IMPORT;
    else if (fa && (fa.decided_at < a.decided_at || (fa.decided_at === a.decided_at && cmp(fa.approval_id, a.approval_id) < 0))) code = REJECT_AFTER_APPROVAL;
    verdicts.set(a.approval_id, { code: code ?? "COUNTED", policy_id: pol?.policy_id ?? null });
    if (code) invalid.push({ approval_id: a.approval_id, reason_code: code }); else rejected.add(a.invoice_id);
  }
  return { rejected, invalid };
}

export function candidatesOf(pop: Population, cutoff: number, mergedInto: Map<string, string>, rejected: Set<string>, review: Map<string, string> = new Map()): Invoice[] {
  return pop.invoices.filter((i) => i.valid === true && !mergedInto.has(i.invoice_id) && !review.has(i.invoice_id) && !rejected.has(i.invoice_id) && i.imported_at <= cutoff);
}

export function derive(pop: Population, cutoff: number | null = null): Book {
  const c = cutoff ?? FAR_FUTURE;
  const invById = new Map(pop.invoices.map((i) => [i.invoice_id, i]));
  const { mergedInto, records: mergedRecords, groups, review, firstValid } = duplicateGroups(pop, c, invById);
  const verdicts = new Map<string, Verdict>();
  const { rejected, invalid } = rejectDecisions(pop, c, mergedInto, invById, firstValid, review, verdicts);
  const cands = candidatesOf(pop, c, mergedInto, rejected, review);
  const candIds = new Set(cands.map((i) => i.invoice_id));
  const committed = new Map<string, Commit>([...firstValid].filter(([k]) => candIds.has(k)).map(([k, a]) => [k, [a.decided_at, a.approval_id] as Commit]));
  const run = matchRun(pop, cands, c, committed);
  const a1 = new Map([...committed.keys()].map((k) => [k, firstValid.get(k)!]));

  // export: an idempotent batch, one row per (invoice, batch); a repeated key or batch id returns the prior batch; a row needs a
  // valid approval at or before its exported_at, otherwise it is invalid and listed
  const reqs = pop.export_requests.filter((r) => r.exported_at <= c);
  const seenKeys = new Set<string>(), seenBatches = new Set<string>();
  const rows: ExportRow[] = [];
  const exported = new Map<string, string>();
  const late = new Set<string>();
  const exportLog: { request: ExportRequest; repeat: boolean }[] = [];
  let batches = 0, repeats = 0;
  for (const r of reqs) {
    const repeat = seenKeys.has(r.idempotency_key) || seenBatches.has(r.batch_id);
    seenKeys.add(r.idempotency_key);
    seenBatches.add(r.batch_id);
    exportLog.push({ request: r, repeat });
    if (repeat) { repeats++; continue; }
    batches++;
    for (const iid of [...r.invoice_ids].sort(cmp)) {
      const ap = a1.get(iid);
      if (!ap || exported.has(iid)) continue;
      if (ap.decided_at > r.exported_at) { late.add(iid); continue; }
      const i = invById.get(iid)!;
      const amt = s2(run.invoices.get(iid)!.total);
      rows.push({ export_id: `exp-${r.batch_id}-${iid}`, invoice_id: iid, batch_id: r.batch_id, exported_at: isoZ(r.exported_at), vendor_id: i.vendor_id, invoice_number: i.invoice_number, invoice_date: i.invoice_date, currency: i.currency, amount: amt, content_hash: contentHash(i, amt) });
      exported.set(iid, r.batch_id);
    }
  }

  // approvals (D-04): matched at the cutoff (unless an export row commits the invoice), separation of duties, the policy in force
  // at decision time, timing
  const approved = new Map<string, number>();
  const approvedBy = new Map<string, Approval>();
  for (const a of pop.approvals.filter((a) => a.decided_at <= c && a.decision === "approve").sort(byDecision)) {
    const st = run.invoices.get(a.invoice_id);
    const inv = invById.get(a.invoice_id)!;
    const pol = effectivePolicy(pop.approval_policies, a.decided_at);
    let code: string | null = null;
    if (!st || (!st.matched && !exported.has(a.invoice_id))) code = NOT_MATCHED;
    else if (a.actor_id === inv.created_by) code = SELF_APPROVAL;
    else if (!roleMayApprove(pol, a.actor_role, st.total)) code = ROLE_OR_LIMIT;
    else if (a.decided_at < inv.imported_at) code = BEFORE_IMPORT;
    if (code) { invalid.push({ approval_id: a.approval_id, reason_code: code }); verdicts.set(a.approval_id, { code, policy_id: pol?.policy_id ?? null }); }
    else if (!approved.has(a.invoice_id)) { approved.set(a.invoice_id, a.decided_at); approvedBy.set(a.invoice_id, a); verdicts.set(a.approval_id, { code: "COUNTED", policy_id: pol?.policy_id ?? null }); }
    else verdicts.set(a.approval_id, { code: "SUPERSEDED", policy_id: pol?.policy_id ?? null });
  }
  const when = new Map(pop.approvals.map((a) => [a.approval_id, a.decided_at]));
  invalid.sort((a, b) => when.get(a.approval_id)! - when.get(b.approval_id)! || cmp(a.approval_id, b.approval_id));

  // credit notes: once per credit_id, only against an approved (or exported) invoice, no cash movement
  const credits = new Map<string, bigint>();
  for (const cn of pop.credit_notes) if ((cn.credited_at === null || cn.credited_at <= c) && approved.has(cn.invoice_id)) credits.set(cn.invoice_id, (credits.get(cn.invoice_id) ?? 0n) + cn.credit_amount);

  const status = new Map<string, string>();
  for (const [iid, i] of invById) {
    let s: string;
    if (mergedInto.has(iid)) s = "merged";
    else if (review.has(iid)) s = "needs_review";
    else if (rejected.has(iid)) s = "rejected";
    else if (i.valid === false) s = "invalid";
    else if (!run.invoices.has(iid)) s = "received";
    else if (credits.has(iid)) s = "adjusted";
    else if (exported.has(iid)) s = "exported";
    else if (approved.has(iid)) s = "approved";
    else s = run.invoices.get(iid)!.matched ? "matched" : "exception";
    status.set(iid, s);
  }

  // exceptions: one per (invoice, type) of the run; id from the stored record when there is one, owner from the assignments
  const stored = new Map<string, string>();
  for (const e of pop.exceptions) stored.set(`${e.invoice_id}\u0000${e.exception_type}`, e.exception_id);
  const owner = new Map<string, string>();
  for (const a of pop.assignments.filter((a) => a.assigned_at <= c).sort((a, b) => a.assigned_at - b.assigned_at)) owner.set(a.exception_id, a.owner_id);
  const exc: ExceptionEntry[] = [];
  const inBook = [...run.invoices.keys()].sort(cmp);
  for (const iid of inBook) {
    for (const t of run.invoices.get(iid)!.reasons) {
      const eid = stored.get(`${iid}\u0000${t}`) ?? `exc-${String(exc.length + 1).padStart(3, "0")}`;
      const o = owner.get(eid) ?? null;
      exc.push({ exception_id: eid, invoice_id: iid, exception_type: t, owner_id: o, status: o === null ? "open" : "assigned" });
    }
  }
  return { cutoff: c, invoices: invById, mergedInto, mergedRecords, groupsDetected: groups, rejected, run, approved, approvedBy, invalidDecisions: invalid, verdicts, exportRows: rows,
    exportStats: { requests_received: reqs.length, batches_created: batches, repeat_requests_returned_prior: repeats }, exported, credits, status, exceptions: exc, inBook,
    review, firstValid, exportLog, exportLate: late };
}
export const obligations = (b: Book): string[] => [...b.run.invoices.keys()].sort(cmp).filter((i) => CREDITED.includes(b.status.get(i)!));
