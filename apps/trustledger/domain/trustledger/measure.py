"""Measuring one rule over a dataset's rows (D-01, D-06): eligible and failing counts, the dimension score, the failing records.

Dimensions are measured on their own denominators and reported separately:
  completeness  non-missing / eligible (missing = null or, after trimming, empty)
  validity      all-eligible (passing / eligible) and populated-only (passing / populated), both labelled; the score uses populated-only
  uniqueness    duplicate-group share (groups / distinct keys) and duplicate-row share (rows beyond the first / eligible); score 1 - row share
  relationship  matched / non-null foreign keys; null foreign keys are counted separately, never in the denominator
  timeliness    the dataset refreshed inside [occurrence, occurrence + grace) of its local daily schedule
A cell is compared as exact text: text as is, true/false, integers in decimal. Nothing here reads a stored result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from functools import lru_cache
from typing import Any

from .models import Dataset, Population, Rule
from .numbers import p6, ratio
from .timeutil import iso_z, scheduled_occurrence

Row = dict[str, Any]


def cell_text(v: Any) -> str | None:
    """The exact text of a cell value (None stays None)."""
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def is_missing(v: Any, trim: str) -> bool:
    return v is None or (isinstance(v, str) and v.strip(trim) == "")


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def pattern_matches(pattern: str, value: str) -> bool:
    """``re.search``, except that a closing ``$`` does not match before a final newline (PostgreSQL's ``~`` and the SQL reference
    agree with this; Python's ``$`` alone would accept ``"a@b.co\\n"``)."""
    m = _compiled(pattern).search(value)
    if m and pattern.endswith("$") and not pattern.endswith("\\$") and value.endswith("\n") and m.end() == len(value) - 1:
        return False
    return m is not None


@dataclass
class Measure:
    rule: Rule
    eligible: int
    failures: int
    value: Fraction | None                       # the dimension score this rule contributes (None = not measured)
    block: Row                                   # its entry under metrics.<dimension>
    run_extra: Row = field(default_factory=dict)  # populated_count / null_fk_count on the run
    failing: list[str] = field(default_factory=list)   # row ids (the dataset id for timeliness) that failed

    def run(self, weight_version: str | None, run_at: datetime) -> Row:
        r = self.rule
        return {"dataset_id": r.dataset_id, "rule_type": r.rule_type, "severity": r.severity, "rule_version": r.version_number,
                "weight_version": weight_version, "run_at": iso_z(run_at), "eligible_count": self.eligible,
                "failure_count": self.failures, **self.run_extra}


def eligible_rows(rule: Rule, rows: list[Row]) -> list[Row]:
    """All rows unless the rule declares a filter ``{field, equals}`` (D-06)."""
    f = rule.definition.get("filter")
    if not f:
        return rows
    return [r for r in rows if cell_text(r.get(f["field"])) == f["equals"]]


def timeliness_of(ds: Dataset, as_of: datetime) -> Row | None:
    """The evaluated occurrence of a monitored dataset and whether its last refresh fell inside [occurrence, deadline)."""
    if not ds.monitored:
        return None
    s, dl = scheduled_occurrence(ds.refresh_timezone, ds.refresh_local_time, ds.refresh_grace_minutes, as_of)  # type: ignore[arg-type]
    last = ds.last_refreshed_at
    return {"timezone": ds.refresh_timezone, "scheduled_local": ds.refresh_local_time, "grace_minutes": ds.refresh_grace_minutes,
            "evaluated_occurrence_utc": iso_z(s), "deadline_utc": iso_z(dl), "last_refreshed_at": iso_z(last),
            "on_time": last is not None and s <= last < dl}


def measure_rule(rule: Rule, pop: Population, as_of: datetime) -> Measure:
    ds = next(d for d in pop.datasets if d.dataset_id == rule.dataset_id)
    t, d, trim = rule.rule_type, rule.definition, pop.trim
    all_rows = pop.dataset_rows.get(rule.dataset_id, [])
    rows = eligible_rows(rule, all_rows)
    if t == "timeliness":
        tl = timeliness_of(ds, as_of)
        if tl is None:                                    # not monitored: nothing to measure
            return Measure(rule, 0, 0, None, {})
        late = not tl["on_time"]
        return Measure(rule, 1, 1 if late else 0, Fraction(0 if late else 1), tl, failing=[rule.dataset_id] if late else [])
    vals = [r.get(d["field"]) for r in rows]
    ids = [r["row_id"] for r in rows]
    el = len(vals)
    if t == "completeness":
        miss = [i for i, v in enumerate(vals) if is_missing(v, trim)]
        ws = sum(1 for i in miss if isinstance(vals[i], str) and vals[i] != "")
        val = ratio(el - len(miss), el)
        block = {"dataset_id": rule.dataset_id, "eligible_count": el, "missing_count": len(miss), "whitespace_only_count": ws,
                 "populated_count": el - len(miss), "value": p6(val)}
        return Measure(rule, el, len(miss), val, block, failing=[ids[i] for i in miss])
    if t == "validity":
        populated = [i for i, v in enumerate(vals) if not is_missing(v, trim)]
        passing = [i for i in populated if isinstance(vals[i], str) and pattern_matches(d["pattern"], vals[i])]
        ok = set(passing)
        allv, popv = ratio(len(passing), el), ratio(len(passing), len(populated))
        block = {"dataset_id": rule.dataset_id, "eligible_count": el, "populated_count": len(populated), "passing_count": len(passing),
                 "all_eligible": {"label": "validity_all_eligible", "value": p6(allv)},
                 "populated_only": {"label": "validity_populated_only", "value": p6(popv)}}
        return Measure(rule, el, el - len(passing), popv, block, {"populated_count": len(populated)},
                       [ids[i] for i in range(el) if i not in ok])
    if t == "uniqueness":
        first: dict[str, int] = {}
        freq: dict[str, int] = {}
        nulls, dup = [], []
        for i, v in enumerate(vals):
            if is_missing(v, trim):
                nulls.append(i)
                continue
            k = cell_text(v)
            freq[k] = freq.get(k, 0) + 1                        # type: ignore[index]
            if k in first:
                dup.append(i)
            else:
                first[k] = i                                    # type: ignore[index]
        groups = sum(1 for c in freq.values() if c > 1)
        rowshare = ratio(len(dup), el)
        block = {"dataset_id": rule.dataset_id, "eligible_count": el, "null_key_count": len(nulls), "distinct_keys": len(freq),
                 "duplicate_groups": groups, "duplicate_rows": len(dup),
                 "group_share": {"label": "duplicate_group_share", "value": p6(ratio(groups, len(freq)))},
                 "row_share": {"label": "duplicate_row_share", "value": p6(rowshare)}}
        return Measure(rule, el, len(nulls) + len(dup), None if rowshare is None else 1 - rowshare, block,
                       failing=[ids[i] for i in sorted(nulls + dup)])
    # relationship: null foreign keys are excluded from the denominator and counted separately
    parent = {cell_text(r.get(d["parent_field"])) for r in pop.dataset_rows.get(d["parent_dataset_id"], [])
              if not is_missing(r.get(d["parent_field"]), trim)}
    nulls = [i for i, v in enumerate(vals) if is_missing(v, trim)]
    present = [i for i in range(el) if i not in set(nulls)]
    matched = [i for i in present if cell_text(vals[i]) in parent]
    mset = set(matched)
    elig = len(present)
    val = ratio(len(matched), elig)
    block = {"dataset_id": rule.dataset_id, "total_fk_count": el, "null_fk_count": len(nulls), "eligible_count": elig,
             "matched_count": len(matched), "unmatched_count": elig - len(matched), "value": p6(val)}
    return Measure(rule, elig, elig - len(matched), val, block, {"null_fk_count": len(nulls)}, [ids[i] for i in present if i not in mset])


def dimension_of(rule: Rule) -> str:
    return rule.rule_type
