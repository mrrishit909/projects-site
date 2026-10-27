"""Identity matching (D-04, D-06): candidates in canonical order, human merge decisions, reversible merges.

This module never sees the synthetic truth: it reports what was proposed, approved, rejected and reversed, and which candidates were
approved or reviewed. Precision is computed from the truth by ``verification.precision_block`` and nowhere else.
A merge maps the RIGHT record to the LEFT one; a reversal restores both identities and keeps the mapping history.
"""
from __future__ import annotations

from typing import Any

from .models import Population

Row = dict[str, Any]


def matching_block(pop: Population) -> tuple[Row, list[tuple[str, str]], list[tuple[str, str]]]:
    """(matching block, approved pairs, reviewed pairs). Pairs are (left_record_id, right_record_id), one per candidate."""
    cand = {c.candidate_id: c for c in pop.match_candidates}
    decisions = [m for m in pop.merge_decisions if m.candidate_id in cand]
    appr = {m.merge_id: m for m in decisions if m.decision == "approve"}
    rejected = {m.candidate_id for m in decisions if m.decision == "reject"}
    reversed_by = {m.reverses_merge_id: m.merge_id for m in decisions if m.decision == "reverse" and m.reverses_merge_id in appr}
    appr_c = {m.candidate_id for m in appr.values()}
    reviewed = appr_c | rejected
    imap = {r.record_id: r.record_id for r in pop.customer_records}
    hist = []
    for mid in sorted(appr):
        c = cand[appr[mid].candidate_id]
        state = "reversed" if mid in reversed_by else "active"
        if state == "active":
            imap[c.right_record_id] = c.left_record_id
        hist.append({"merge_id": mid, "candidate_id": c.candidate_id, "from_record_id": c.right_record_id,
                     "to_record_id": c.left_record_id, "state": state, "reversed_by": reversed_by.get(mid)})
    block = {"candidates": len(cand), "reviewed": len(reviewed), "approved": len(appr_c), "rejected": len(rejected),
             "unreviewed": len(cand) - len(reviewed), "merges_reversed": len(reversed_by),
             "active_merges": len(appr) - len(reversed_by), "identity_map": dict(sorted(imap.items())), "mapping_history": hist}
    pair = lambda cid: (cand[cid].left_record_id, cand[cid].right_record_id)  # noqa: E731
    return block, [pair(c) for c in sorted(appr_c)], [pair(c) for c in sorted(reviewed)]
