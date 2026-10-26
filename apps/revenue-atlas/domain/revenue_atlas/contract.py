"""Contract constants (docs/contracts.md, version v1)."""
from __future__ import annotations

CONTRACT_VERSION = "v1"
REPORTING_CURRENCY = "USD"
CURRENCY_RE = r"^[A-Z]{3}$"
KNOWN_CURRENCIES = frozenset({"USD", "EUR", "GBP", "CAD", "MXN", "JPY"})
ELIGIBLE_ORDER_STATUSES = frozenset({"shipped", "partially_returned"})  # D-01
UNASSIGNED_REGION = "UNASSIGNED"  # D-06
