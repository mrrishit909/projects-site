// The derived book (book.py): duplicates, rejections, three-way match, approvals, exports and credits at one cutoff.
// A pure function of recorded facts; nothing stored as a status is read. ``cutoff`` is inclusive.
import { CREDITED, NOT_MATCHED, NOT_REVIEWABLE, REJECT_AFTER_APPROVAL, ROLE_OR_LIMIT, SELF_APPROVAL } from "./contract";
import { detectDuplicates, type MergedRecord } from "./duplicates";
import { matchRun, type MatchRun } from "./match";
import { s2 } from "./num";
import { sha256 } from "./sha256";
import { FAR_FUTURE, isoZ } from "./time";
import type { Approval, Invoice, Policy, Population } from "./types";

const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** The policy version in force at ``at`` (latest effective_from, then version, then id). */
export function effectivePolicy(policies: readonly Policy[], at: number): Policy | null {
  let best: Policy | null = null;
  for (const p of policies) {
    if (p.effective_from > at) continue;
    if (!best || p.effective_from > best.effective_from || (p.effective_from === best.effective_from && (p.version_number > best.version_number || (p.version_number === best.version_number && p.policy_id > best.policy_id)))) best = p;
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
}

function rejectDecisions(pop: Population, cutoff: number, mergedInto: Map<string, string>, invById: Map<string, Invoice>, verdicts: Map<string, Verdict>): { rejected: Set<string>; invalid: InvalidDecision[] } {
  const decisions = pop.approvals.filter((a) => a.decided_at <= cutoff).sort((a, b) => a.decided_at - b.decided_at || cmp(a.approval_id, b.approval_id));
  const firstApprove = new Map<string, [number, string]>();
  for (const a of decisions) if (a.decision === "approve" && !firstApprove.has(a.invoice_id)) firstApprove.set(a.invoice_id, [a.decided_at, a.approval_id]);
  const rejected = new Set<string>();
  const invalid: InvalidDecision[] = [];
  for (const a of decisions) {
    if (a.decision !== "reject") continue;
    const inv = invById.get(a.invoice_id);
    const pol = effectivePolicy(pop.approval_policies, a.decided_at);
    let code: string | null = null;
    if (!inv || mergedInto.has(inv.invoice_id) || inv.valid !== true || inv.imported_at > cutoff) code = NOT_REVIEWABLE;
    else if (!pol || (a.actor_role !== pol.reviewer_role && a.actor_role !== pol.escalation_role)) code = ROLE_OR_LIMIT;
    else {
      const fa = firstApprove.get(a.invoice_id);
      if (fa && (fa[0] < a.decided_at || (fa[0] === a.decided_at && fa[1] < a.approval_id))) code = REJECT_AFTER_APPROVAL;
    }
    verdicts.set(a.approval_id, { code: code ?? "COUNTED", policy_id: pol?.policy_id ?? null });
    if (code) invalid.push({ approval_id: a.approval_id, reason_code: code }); else rejected.add(a.invoice_id);
  }
  return { rejected, invalid };
}

export function candidatesOf(pop: Population, cutoff: number, mergedInto: Map<string, string>, rejected: Set<string>): Invoice[] {
  return pop.invoices.filter((i) => i.valid === true && !mergedInto.has(i.invoice_id) && !rejected.has(i.invoice_id) && i.imported_at <= cutoff);
}

export function derive(pop: Population, cutoff: number | null = null): Book {
  const c = cutoff ?? FAR_FUTURE;
  const invById = new Map(pop.invoices.map((i) => [i.invoice_id, i]));
  const { mergedInto, records: mergedRecords, groups } = detectDuplicates(pop.invoices);
  const verdicts = new Map<string, Verdict>();
  const { rejected, invalid } = rejectDecisions(pop, c, mergedInto, invById, verdicts);
  const run = matchRun(pop, candidatesOf(pop, c, mergedInto, rejected), c);

  const approved = new Map<string, number>();
  const approvedBy = new Map<string, Approval>();
  for (const a of pop.approvals.filter((a) => a.decided_at <= c && a.decision === "approve").sort((a, b) => a.decided_at - b.decided_at || cmp(a.approval_id, b.approval_id))) {
    const st = run.invoices.get(a.invoice_id);
    const inv = invById.get(a.invoice_id)!;
    const pol = effectivePolicy(pop.approval_policies, a.decided_at);
    let code: string | null = null;
    if (!st || !st.matched) code = NOT_MATCHED;
    else if (a.actor_id === inv.created_by) code = SELF_APPROVAL;
    else if (!roleMayApprove(pol, a.actor_role, st.total)) code = ROLE_OR_LIMIT;
    if (code) { invalid.push({ approval_id: a.approval_id, reason_code: code }); verdicts.set(a.approval_id, { code, policy_id: pol?.policy_id ?? null }); }
    else if (!approved.has(a.invoice_id)) { approved.set(a.invoice_id, a.decided_at); approvedBy.set(a.invoice_id, a); verdicts.set(a.approval_id, { code: "COUNTED", policy_id: pol?.policy_id ?? null }); }
    else verdicts.set(a.approval_id, { code: "SUPERSEDED", policy_id: pol?.policy_id ?? null });
  }
  const when = new Map(pop.approvals.map((a) => [a.approval_id, a.decided_at]));
  invalid.sort((a, b) => when.get(a.approval_id)! - when.get(b.approval_id)! || cmp(a.approval_id, b.approval_id));

  // export: an idempotent batch, one row per (invoice, batch); a repeated key or batch id returns the prior batch
  const reqs = pop.export_requests.filter((r) => r.exported_at <= c);
  const seenKeys = new Set<string>(), seenBatches = new Set<string>();
  const rows: ExportRow[] = [];
  const exported = new Map<string, string>();
  let batches = 0, repeats = 0;
  for (const r of reqs) {
    const repeat = seenKeys.has(r.idempotency_key) || seenBatches.has(r.batch_id);
    seenKeys.add(r.idempotency_key);
    seenBatches.add(r.batch_id);
    if (repeat) { repeats++; continue; }
    batches++;
    for (const iid of [...r.invoice_ids].sort(cmp)) {
      if (approved.has(iid) && !exported.has(iid)) {
        const i = invById.get(iid)!;
        const amt = s2(run.invoices.get(iid)!.total);
        rows.push({ export_id: `exp-${r.batch_id}-${iid}`, invoice_id: iid, batch_id: r.batch_id, exported_at: isoZ(r.exported_at), vendor_id: i.vendor_id, invoice_number: i.invoice_number, invoice_date: i.invoice_date, currency: i.currency, amount: amt, content_hash: contentHash(i, amt) });
        exported.set(iid, r.batch_id);
      }
    }
  }
  // credit notes: once per credit_id, only against an approved (or exported) invoice, no cash movement
  const credits = new Map<string, bigint>();
  for (const cn of pop.credit_notes) if ((cn.credited_at === null || cn.credited_at <= c) && approved.has(cn.invoice_id)) credits.set(cn.invoice_id, (credits.get(cn.invoice_id) ?? 0n) + cn.credit_amount);

  const status = new Map<string, string>();
  for (const [iid, i] of invById) {
    let s: string;
    if (mergedInto.has(iid)) s = "merged";
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
    exportStats: { requests_received: reqs.length, batches_created: batches, repeat_requests_returned_prior: repeats }, exported, credits, status, exceptions: exc, inBook };
}
export const obligations = (b: Book): string[] => [...b.run.invoices.keys()].sort(cmp).filter((i) => CREDITED.includes(b.status.get(i)!));
