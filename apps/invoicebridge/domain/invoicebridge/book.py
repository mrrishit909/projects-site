"""The derived book: duplicates, rejections, three-way match, approvals, exports and credits at one cutoff.

``derive(pop, cutoff)`` is a pure function of the FACTS in the population (invoices, lines, receipts, approvals,
export requests, credit notes, exception assignments). Nothing stored as a status is read, so the Python domain, the SQL
reference and the API's metrics read agree on any population. ``cutoff`` is inclusive: a fact stamped at the cutoff counts.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .duplicates import detect_duplicates
from .errors import NOT_MATCHED, NOT_REVIEWABLE, REJECT_AFTER_APPROVAL, ROLE_OR_LIMIT, SELF_APPROVAL
from .match import MatchRun, match_run
from .money import D0, exact, s2
from .models import Invoice, Policy, Population
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

    @property
    def obligations(self) -> list[str]:
        return [i for i in sorted(self.run.invoices) if self.status[i] in CREDITED]


def reject_decisions(pop: Population, cutoff: datetime, merged_into: dict[str, str],
                     inv_by_id: dict[str, Invoice]) -> tuple[set[str], list[dict[str, str]]]:
    """Valid reject decisions (C08): the actor's role is allowed by the policy in force, the invoice is a validated,
    non-merged one and has no earlier approve decision. The first valid reject per invoice wins."""
    decisions = sorted((a for a in pop.approvals if a.decided_at <= cutoff), key=lambda a: (a.decided_at, a.approval_id))
    first_approve: dict[str, tuple[datetime, str]] = {}
    for a in decisions:
        if a.decision == "approve":
            first_approve.setdefault(a.invoice_id, (a.decided_at, a.approval_id))
    rejected: set[str] = set()
    invalid: list[dict[str, str]] = []
    for a in decisions:
        if a.decision != "reject":
            continue
        inv = inv_by_id.get(a.invoice_id)
        pol = effective_policy(pop.approval_policies, a.decided_at)
        code = None
        if inv is None or inv.invoice_id in merged_into or inv.valid is not True or inv.imported_at > cutoff:
            code = NOT_REVIEWABLE
        elif pol is None or a.actor_role not in {pol.reviewer_role, pol.escalation_role}:
            code = ROLE_OR_LIMIT
        elif a.invoice_id in first_approve and first_approve[a.invoice_id] < (a.decided_at, a.approval_id):
            code = REJECT_AFTER_APPROVAL
        if code:
            invalid.append({"approval_id": a.approval_id, "reason_code": code})
        else:
            rejected.add(a.invoice_id)
    return rejected, invalid


def candidates(pop: Population, cutoff: datetime, merged_into: dict[str, str], rejected: set[str]) -> list[Invoice]:
    """The invoices in the book at ``cutoff``: validated, not merged, not rejected, imported by then."""
    return [i for i in pop.invoices if i.valid is True and i.invoice_id not in merged_into
            and i.invoice_id not in rejected and i.imported_at <= cutoff]


@exact
def derive(pop: Population, cutoff: datetime | None = None) -> Book:
    c = cutoff or FAR_FUTURE
    inv_by_id = {i.invoice_id: i for i in pop.invoices}
    merged_into, merged_records, groups = detect_duplicates(pop.invoices)
    rejected, invalid = reject_decisions(pop, c, merged_into, inv_by_id)
    run = match_run(pop, candidates(pop, c, merged_into, rejected), c)

    # approvals (D-04): matched at the cutoff, separation of duties, the policy in force at decision time
    approved: dict[str, datetime] = {}
    for a in sorted((a for a in pop.approvals if a.decided_at <= c and a.decision == "approve"),
                    key=lambda a: (a.decided_at, a.approval_id)):
        st = run.invoices.get(a.invoice_id)
        inv = inv_by_id[a.invoice_id]
        pol = effective_policy(pop.approval_policies, a.decided_at)
        code = None
        if st is None or not st.matched:
            code = NOT_MATCHED
        elif a.actor_id == inv.created_by:
            code = SELF_APPROVAL
        elif not role_may_approve(pol, a.actor_role, st.total):
            code = ROLE_OR_LIMIT
        if code:
            invalid.append({"approval_id": a.approval_id, "reason_code": code})
        else:
            approved.setdefault(a.invoice_id, a.decided_at)
    when = {a.approval_id: a.decided_at for a in pop.approvals}
    invalid.sort(key=lambda r: (when[r["approval_id"]], r["approval_id"]))

    # export: an idempotent batch, one row per (invoice, batch); a repeated key or batch id returns the prior batch
    reqs = [r for r in pop.export_requests if r.exported_at <= c]
    seen_keys: set[str] = set()
    seen_batches: set[str] = set()
    rows: list[dict[str, Any]] = []
    exported: dict[str, str] = {}
    batches = repeats = 0
    for r in reqs:
        repeat = r.idempotency_key in seen_keys or r.batch_id in seen_batches
        seen_keys.add(r.idempotency_key)
        seen_batches.add(r.batch_id)
        if repeat:
            repeats += 1
            continue
        batches += 1
        for iid in sorted(r.invoice_ids):
            if iid in approved and iid not in exported:
                i = inv_by_id[iid]
                amt = s2(run.invoices[iid].total)
                rows.append({"export_id": f"exp-{r.batch_id}-{iid}", "invoice_id": iid, "batch_id": r.batch_id,
                             "exported_at": iso_z(r.exported_at), "vendor_id": i.vendor_id,
                             "invoice_number": i.invoice_number, "invoice_date": i.invoice_date.isoformat(),
                             "currency": i.currency, "amount": amt, "content_hash": content_hash(i, amt)})
                exported[iid] = r.batch_id

    # credit notes: once per credit_id, only against an approved (or exported) invoice, no cash movement
    credits: dict[str, Decimal] = {}
    for cn in pop.credit_notes:
        if (cn.credited_at is None or cn.credited_at <= c) and cn.invoice_id in approved:
            credits[cn.invoice_id] = credits.get(cn.invoice_id, D0) + cn.credit_amount

    status: dict[str, str] = {}
    for iid, i in inv_by_id.items():
        if iid in merged_into:
            status[iid] = "merged"
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
                exported, credits, status, exc, sorted(run.invoices))
