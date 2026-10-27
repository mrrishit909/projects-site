"""ONE ASCII-only pattern set with FULL-MATCH semantics for money, quantity and timestamp fields (D-09, R8-04).

The same set is implemented four times and must agree on every input: here (``re.fullmatch`` with ``re.ASCII`` and explicit ``[0-9]``, so
Arabic-Indic and other Unicode digits never match and ``$`` can never match before a trailing newline), in ``data/sql/reference_metrics.sql``
(PostgreSQL ``\\A...\\Z`` with ``[0-9]``), in ``web/src/domain`` (``^...$`` with the ``u`` flag plus an explicit newline refusal) and in
``tests/reference_check.py``. A JSON number is a quantity only when it is an integer whose magnitude is at most 2**53 (the largest integer a
JSON consumer using doubles reads back exactly); ``3.0`` and ``1e2`` are floats and therefore ``INVALID_FIELD``.
"""
from __future__ import annotations

import re
from typing import Any

MONEY_SOURCE = r"-?[0-9]+(?:\.[0-9]{1,2})?"
TIMESTAMP_SOURCE = r"([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})"
MONEY = re.compile(MONEY_SOURCE, re.ASCII)
TIMESTAMP = re.compile(TIMESTAMP_SOURCE, re.ASCII)
MAX_SAFE_INTEGER = 2 ** 53


def is_money(v: Any) -> bool:
    """A money string: optional minus, digits, optionally a point and one or two decimals; nothing before, after or between (no newline, no space)."""
    return isinstance(v, str) and MONEY.fullmatch(v) is not None


def is_quantity(v: Any) -> bool:
    """A quantity: a JSON integer (never a bool, never a float such as ``3.0``) of magnitude at most 2**53."""
    return type(v) is int and abs(v) <= MAX_SAFE_INTEGER
