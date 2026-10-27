"""The verification layer: the ONLY reader of the synthetic truth (D-04, P07-DOMAIN-03).

``truth`` is the fixture's ``synthetic_truth.true_entity`` map (record id -> entity id). The matcher, the pipeline's matching block
and the API never read it; precision is computed here from decisions already made.

Match precision = approved merge decisions whose pair the truth shows to be ONE entity / approved merge decisions (a reversal does
not remove the approval from the ratio). The wider ``reviewed_correct_share`` (same entity / all reviewed pairs) is reported beside
it and labelled so nobody reads it as precision. If the truth does not name a record of a decided pair, nothing is confirmable and
the correct counts and shares are null (unknown), never 0.
"""
from __future__ import annotations

from typing import Any, Mapping

from .numbers import p6, ratio

Row = dict[str, Any]


def precision_block(truth: Mapping[str, str] | None, approved: list[tuple[str, str]], reviewed: list[tuple[str, str]]) -> Row:
    tm = truth or {}
    decided = {r for pair in reviewed for r in pair} | {r for pair in approved for r in pair}
    known = all(r in tm for r in decided)
    same = lambda pair: tm[pair[0]] == tm[pair[1]]  # noqa: E731
    a_ok = sum(1 for p in approved if same(p)) if known else None
    r_ok = sum(1 for p in reviewed if same(p)) if known else None
    return {"approved_decisions": len(approved), "approved_correct": a_ok,
            "precision": p6(ratio(a_ok, len(approved))) if known else None,
            "reviewed": len(reviewed), "reviewed_correct": r_ok,
            "reviewed_correct_share": p6(ratio(r_ok, len(reviewed))) if known else None}


def truth_map(block: Mapping[str, Any] | None) -> dict[str, str] | None:
    """``synthetic_truth.true_entity`` from an inputs object's block (None when there is none)."""
    if not block:
        return None
    te = block.get("true_entity")
    return dict(te) if isinstance(te, Mapping) else None
