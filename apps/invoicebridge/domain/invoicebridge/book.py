"""The derived book: duplicates, rejections, three-way match, approvals, exports and credits at one cutoff.

``derive(pop, cutoff)`` is a pure function of the FACTS in the population (invoices, lines, receipts, approvals,
export requests, credit notes, exception assignments). Nothing stored as a status is read, so the Python domain, the SQL
reference and the API's metrics read agree on any population. ``cutoff`` is inclusive: a fact stamped at the cutoff counts.

D-09 (committed outcomes are facts): an invoice with a policy-valid approval (``first_valid``) is COMMITTED. Committed
invoices keep the received quantity they consume ahead of every uncommitted one (consumption order: committed by commit
instant, then book order), are never displaced as the canonical copy of a duplicate group, and an invoice named by a valid
export row stays exported when a receipt is reversed afterwards (the reversal shows as an exception on it).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .amounts import invoice_amounts
from .duplicates import detect_duplicates
from .errors import (BEFORE_IMPORT, NOT_MATCHED, NOT_REVIEWABLE, REJECT_AFTER_APPROVAL, ROLE_OR_LIMIT, SELF_APPROVAL,
                     SELF_DECISION)
from .match import MatchRun, match_run
from .money import D0, exact, s2
from .models import Approval, ExportRequest, Invoice, Policy, Population
from .timeutil import FAR_FUTURE, iso_z

CREDITED = ("approved", "exported", "adjusted")


def effective_policy(policies: list[Policy], at: datetime) -> Policy | None:
    """The policy version in force at ``at`` (latest effective_from, then version, then id)."""
    live = [p for p in policies if p.effective_from <= at]
    return max(live, key=lambda p: (p.effective_from, p.version_number, p.policy_id)) if live else None


def role_may_approve(policy: Policy | None, role: str, total: Decimal) -> bool:
    """D-04: the policy's reviewer role up to its limit; the optional escalation role at any amount."""
    if policy is None:
        return False
    if policy.escalation_role is not None and role == policy.escalation_role:
        return True
    return role == policy.reviewer_role and total <= policy.amount_limit


def content_hash(inv: Invoice, amount: str) -> str:
    """D-05: sha256 of ``invoice_id|vendor_id|invoice_number|invoice_date|currency|amount`` (number as imported)."""
    payload = "|".join([inv.invoice_id, inv.vendor_id, inv.invoice_number, inv.invoice_date.isoformat(), inv.currency, amount])
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class Book:
    cutoff: datetime
    invoices: dict[str, Invoice]                  # every accepted invoice
    merged_into: dict[str, str]
    merged_records: list[dict[str, Any]]
    groups_detected: int
    rejected: set[str]                            # invoices rejected by a valid reject decision
    run: MatchRun
    approved: dict[str, datetime]                 # invoice -> decided_at of the first valid approval
    invalid_decisions: list[dict[str, str]]
    export_rows: list[dict[str, Any]]
    export_stats: dict[str, int]
    exported: dict[str, str]                      # invoice -> batch id
    credits: dict[str, Decimal]                   # invoice -> credit total applied
    status: dict[str, str]
    exceptions: list[dict[str, Any]]
    in_book: list[str] = field(default_factory=list)
    review: dict[str, str] = field(default_factory=dict)             # byte-twin held for review -> its canonical
    first_valid: dict[str, Approval] = field(default_factory=dict)   # policy-valid first approval of each committed invoice
    export_log: list[tuple[ExportRequest, bool]] = field(default_factory=list)    # every request at the cutoff, with its repeat flag
    export_late: dict[str, datetime] = field(default_factory=dict)   # approved, but a request named it before its approval

    @property
    def obligations(self) -> list[str]:
        return [i for i in sorted(self.run.invoices) if self.status[i] in CREDITED]


def policy_verdict(pop: Population, a: Approval, inv: Invoice, total: Decimal) -> str | None:
    """The rules of an approval that do not depend on the book: timing, separation of duties, the policy at decision time."""
    if a.actor_id == inv.created_by:
        return SELF_APPROVAL
    if not role_may_approve(effective_policy(pop.approval_policies, a.decided_at), a.actor_role, total):
        return ROLE_OR_LIMIT
    if a.decided_at < inv.imported_at:
        return BEFORE_IMPORT
    return None


def first_valid_approvals(pop: Population, cutoff: datetime, inv_by_id: dict[str, Invoice]) -> dict[str, Approval]:
    """The first policy-valid approve decision of every invoice (decided by the cutoff, invoice imported by then and not
    failed by C02): the committed invoices. Independent of duplicates, rejections and the match."""
    out: dict[str, Approval] = {}
    for a in sorted((a for a in pop.approvals if a.decided_at <= cutoff and a.decision == "approve"),
                    key=lambda a: (a.decided_at, a.approval_id)):
        inv = inv_by_id.get(a.invoice_id)
        if inv is None or inv.valid is False or inv.imported_at > cutoff or a.invoice_id in out:
            continue
        if policy_verdict(pop, a, inv, invoice_amounts(inv)[2]) is None:
            out[a.invoice_id] = a
    return out


def duplicate_groups(pop: Population, cutoff: datetime, inv_by_id: dict[str, Invoice] | None = None):
    """Duplicate detection over the invoices imported by the cutoff and not failed by C02 (an invalid invoice is never
    a canonical copy), committed invoices first. Returns ``(merged_into, records, groups, review, first_valid)``."""
    inv_by_id = inv_by_id or {i.invoice_id: i for i in pop.invoices}
    first = first_valid_approvals(pop, cutoff, inv_by_id)
    eligible = [i for i in pop.invoices if i.valid is not False and i.imported_at <= cutoff]
    merged_into, records, groups, review = detect_duplicates(eligible, {k: (a.decided_at, a.approval_id) for k, a in first.items()})
    return merged_into, records, groups, review, first


def reject_decisions(pop: Population, cutoff: datetime, merged_into: dict[str, str], inv_by_id: dict[str, Invoice],
                     first_valid: dict[str, Approval], review: dict[str, str] | None = None
                     ) -> tuple[set[str], list[dict[str, str]]]:
    """Valid reject decisions (C08): the invoice is a validated, non-merged one, the actor's role is allowed by the policy in
    force, the creator is not the rejecter, the decision is not before the import and no earlier VALID approval exists
    (an invalid approval does not block a rejection, D-09). The first valid reject per invoice wins."""
    review = review or {}
    decisions = sorted((a for a in pop.approvals if a.decided_at <= cutoff and a.decision == "reject"),
                       key=lambda a: (a.decided_at, a.approval_id))
    rejected: set[str] = set()
    invalid: list[dict[str, str]] = []
    for a in decisions:
        inv = inv_by_id.get(a.invoice_id)
        pol = effective_policy(pop.approval_policies, a.decided_at)
        fa = first_valid.get(a.invoice_id)
        code = None
        if inv is None or inv.invoice_id in merged_into or inv.invoice_id in review or inv.valid is not True or inv.imported_at > cutoff:
            code = NOT_REVIEWABLE
        elif pol is None or a.actor_role not in {pol.reviewer_role, pol.escalation_role}:
            code = ROLE_OR_LIMIT
        elif a.actor_id == inv.created_by:
            code = SELF_DECISION
        elif a.decided_at < inv.imported_at:
            code = BEFORE_IMPORT
        elif fa is not None and (fa.decided_at, fa.approval_id) < (a.decided_at, a.approval_id):
            code = REJECT_AFTER_APPROVAL
        if code:
            invalid.append({"approval_id": a.approval_id, "reason_code": code})
        else:
            rejected.add(a.invoice_id)
    return rejected, invalid


def candidates(pop: Population, cutoff: datetime, merged_into: dict[str, str], rejected: set[str],
               review: dict[str, str] | None = None) -> list[Invoice]:
    """The invoices in the book at ``cutoff``: validated, not merged, not held for review, not rejected, imported by then."""
    review = review or {}
    return [i for i in pop.invoices if i.valid is True and i.invoice_id not in merged_into and i.invoice_id not in review
            and i.invoice_id not in rejected and i.imported_at <= cutoff]


@exact
def derive(pop: Population, cutoff: datetime | None = None) -> Book:
    c = cutoff or FAR_FUTURE
    inv_by_id = {i.invoice_id: i for i in pop.invoices}
    merged_into, merged_records, groups, review, first_valid = duplicate_groups(pop, c, inv_by_id)
    rejected, invalid = reject_decisions(pop, c, merged_into, inv_by_id, first_valid, review)
    cands = candidates(pop, c, merged_into, rejected, review)
    cand_ids = {i.invoice_id for i in cands}
    committed = {k: (a.decided_at, a.approval_id) for k, a in first_valid.items() if k in cand_ids}
    run = match_run(pop, cands, c, committed)
    a1 = {k: first_valid[k] for k in committed}                    # the committed invoices of the book

    # export (D-04, D-09): an idempotent batch, one row per (invoice, batch); a repeated key or batch id returns the prior
    # batch; a row needs a valid approval at or before its exported_at, otherwise it is invalid and listed
    reqs = [r for r in pop.export_requests if r.exported_at <= c]
    seen_keys: set[str] = set()
    seen_batches: set[str] = set()
    rows: list[dict[str, Any]] = []
    exported: dict[str, str] = {}
    late: dict[str, datetime] = {}
    log: list[tuple[ExportRequest, bool]] = []
    batches = repeats = 0
    for r in reqs:
        repeat = r.idempotency_key in seen_keys or r.batch_id in seen_batches
        seen_keys.add(r.idempotency_key)
        seen_batches.add(r.batch_id)
        log.append((r, repeat))
        if repeat:
            repeats += 1
            continue
        batches += 1
        for iid in sorted(r.invoice_ids):
            ap = a1.get(iid)
            if ap is None or iid in exported:
                continue
            if ap.decided_at > r.exported_at:
                late[iid] = ap.decided_at
                continue
            i = inv_by_id[iid]
            amt = s2(run.invoices[iid].total)
            rows.append({"export_id": f"exp-{r.batch_id}-{iid}", "invoice_id": iid, "batch_id": r.batch_id,
                         "exported_at": iso_z(r.exported_at), "vendor_id": i.vendor_id,
                         "invoice_number": i.invoice_number, "invoice_date": i.invoice_date.isoformat(),
                         "currency": i.currency, "amount": amt, "content_hash": content_hash(i, amt)})
            exported[iid] = r.batch_id

    # approvals (D-04): timing, matched at the cutoff (unless an export row commits the invoice), separation of duties,
    # the policy in force at decision time
    approved: dict[str, datetime] = {}
    for a in sorted((a for a in pop.approvals if a.decided_at <= c and a.decision == "approve"),
                    key=lambda a: (a.decided_at, a.approval_id)):
        st = run.invoices.get(a.invoice_id)
        inv = inv_by_id[a.invoice_id]
        pol = effective_policy(pop.approval_policies, a.decided_at)
        code = None
        if st is None or (not st.matched and a.invoice_id not in exported):
            code = NOT_MATCHED
        elif a.actor_id == inv.created_by:
            code = SELF_APPROVAL
        elif not role_may_approve(pol, a.actor_role, st.total):
            code = ROLE_OR_LIMIT
        elif a.decided_at < inv.imported_at:
            code = BEFORE_IMPORT
        if code:
            invalid.append({"approval_id": a.approval_id, "reason_code": code})
        else:
            approved.setdefault(a.invoice_id, a.decided_at)
    when = {a.approval_id: a.decided_at for a in pop.approvals}
    invalid.sort(key=lambda r: (when[r["approval_id"]], r["approval_id"]))

    # credit notes: once per credit_id, only against an approved (or exported) invoice, no cash movement
    credits: dict[str, Decimal] = {}
    for cn in pop.credit_notes:
        if (cn.credited_at is None or cn.credited_at <= c) and cn.invoice_id in approved:
            credits[cn.invoice_id] = credits.get(cn.invoice_id, D0) + cn.credit_amount

    status: dict[str, str] = {}
    for iid, i in inv_by_id.items():
        if iid in merged_into:
            status[iid] = "merged"
        elif iid in review:
            status[iid] = "needs_review"
        elif iid in rejected:
            status[iid] = "rejected"
        elif i.valid is False:
            status[iid] = "invalid"
        elif iid not in run.invoices:
            status[iid] = "received"
        elif iid in credits:
            status[iid] = "adjusted"
        elif iid in exported:
            status[iid] = "exported"
        elif iid in approved:
            status[iid] = "approved"
        else:
            status[iid] = "matched" if run.invoices[iid].matched else "exception"

    # exceptions: one per (invoice, type) of the run; id and owner from the stored record when there is one
    stored = {(e.invoice_id, e.exception_type): e.exception_id for e in pop.exceptions}
    owner: dict[str, str] = {}
    for a in sorted((a for a in pop.assignments if a.assigned_at <= c), key=lambda a: a.assigned_at):
        owner[a.exception_id] = a.owner_id
    exc: list[dict[str, Any]] = []
    for iid in sorted(run.invoices):
        for t in run.invoices[iid].reasons:
            eid = stored.get((iid, t)) or f"exc-{len(exc) + 1:03d}"
            o = owner.get(eid)
            exc.append({"exception_id": eid, "invoice_id": iid, "exception_type": t, "owner_id": o,
                        "status": "open" if o is None else "assigned"})
    return Book(c, inv_by_id, merged_into, merged_records, groups, rejected, run, approved, invalid, rows,
                {"requests_received": len(reqs), "batches_created": batches, "repeat_requests_returned_prior": repeats},
                exported, credits, status, exc, sorted(run.invoices), review, first_valid, log, late)
