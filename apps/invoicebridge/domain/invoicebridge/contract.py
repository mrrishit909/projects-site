"""Contract constants (docs/contracts.md, version 1, decisions D-01..D-05)."""
from __future__ import annotations

CONTRACT_VERSION = 1
RULE_VERSION = "1"                      # carried by every match result (D-03)

#: Entities of an input batch, parents first (also the order of the ingest counts in expected.json).
ENTITIES = ("vendors", "purchase_orders", "po_lines", "receipts", "invoices", "invoice_lines",
            "credit_notes", "approval_policies", "approvals")

#: Metric names in the order of expected.json["metrics"]. ``snapshot_cutoffs`` is not a metric: it is the list of
#: instants the ``snapshots`` metric was computed for, carried beside the metrics (PipelineResult, API ``data``).
METRIC_KEYS = ("matched", "obligations", "exceptions", "duplicates", "quantities", "snapshots", "rates",
               "processing", "approvals", "payable", "export")

#: D-05 exception reasons, in the order of ``exceptions.by_reason``.
EXCEPTION_CODES = ("QUANTITY_BLOCKED", "PRICE_VARIANCE", "NO_PO_LINE", "ROUNDING_EXCEPTION", "CURRENCY_MISMATCH")

INVOICE_STATUSES = ("received", "valid", "invalid", "matched", "exception", "approved", "rejected", "exported",
                    "adjusted", "merged")
IMPORT_STATUSES = ("accepted", "rejected", "merged")
ROLES = ("clerk", "reviewer", "admin")

#: Tolerances used when an input carries none (the fixture values, D-05).
DEFAULT_TOLERANCES = {"price_per_unit": "0.00", "rounding_per_line": "0.01", "rounding_per_invoice": "0.02"}

#: Upper bound of any quantity, price or money amount (NUMERIC(20,*) columns, exact arithmetic with prec 60).
MAX_ABS = 10 ** 12
