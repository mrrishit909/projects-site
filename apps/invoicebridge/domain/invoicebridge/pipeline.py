"""End to end: ingest -> validate -> derive -> metrics (D-01..D-05)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .amounts import invoice_amounts, validate_invoice
from .book import Book, derive
from .contract import CONTRACT_VERSION, METRIC_KEYS
from .ingest import IngestResult, validate_batch
from .match import InvoiceResult
from .metrics import compute_metrics
from .models import Population
from .money import s2
from .timeutil import parse_ts


@dataclass
class PipelineResult:
    ingest: IngestResult
    population: Population
    metrics: dict[str, Any]
    snapshot_cutoffs: list[str]
    book: Book
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        return self.ingest.counts

    @property
    def rejected(self) -> list[dict[str, Any]]:
        return self.ingest.rejected_dicts()

    def documents(self) -> dict[str, Any]:
        """Per-invoice documents and the match results of the book (shape of expected.json ``documents``)."""
        book, run = self.book, self.book.run
        docs: dict[str, Any] = {}
        for iid in sorted(book.invoices):
            inv = book.invoices[iid]
            st: InvoiceResult | None = run.invoices.get(iid)
            sub, tax, total = (st.subtotal, st.tax, st.total) if st else invoice_amounts(inv)
            diff = st.rounding_difference if st else abs(inv.declared_total - total)
            d = {"status": book.status[iid], "subtotal": s2(sub), "tax": s2(tax), "freight": s2(inv.freight),
                 "invoice_discount": s2(inv.invoice_discount), "total": s2(total), "declared_total": s2(inv.declared_total),
                 "rounding_difference": s2(diff), "exception_types": list(st.reasons) if st else []}
            if iid in book.merged_into:
                d["merged_into"] = book.merged_into[iid]
            docs[iid] = d
        return {"invoices": docs,
                "match_results": [r.as_row() for r in sorted(run.lines, key=lambda r: r.invoice_line_id)]}

    def golden(self) -> dict[str, Any]:
        """The shape of expected.json."""
        return {"contract_version": CONTRACT_VERSION,
                "ingest": {"counts": self.counts, "rejected_records": self.rejected,
                           "merged_records": self.ingest.merged_records},
                "documents": self.documents(), "metrics": self.metrics}


def validate_population(pop: Population) -> Population:
    """Mark each invoice valid or invalid with the C02 rules (what the API's validate-invoice records)."""
    vendors = {v.vendor_id: v for v in pop.vendors}
    pop.invoices = [i.__class__(**{**i.__dict__, "valid": not validate_invoice(i, vendors.get(i.vendor_id))})
                    for i in pop.invoices]
    return pop


def run_pipeline(inputs: dict[str, Any], as_of: str | None = None, cutoffs: list[str] | None = None) -> PipelineResult:
    """Ingest ``inputs`` (the shape of inputs.json) and compute the book and metrics at ``as_of`` (default: the
    inputs' own ``as_of``)."""
    ing = validate_batch(inputs)
    pop = validate_population(ing.population())
    when = parse_ts(as_of or inputs["as_of"]) if (as_of or inputs.get("as_of")) else None
    cuts = [parse_ts(c) for c in (inputs.get("snapshot_cutoffs", []) if cutoffs is None else cutoffs)]
    book = derive(pop, when)
    metrics = compute_metrics(pop, when, cuts)
    assert tuple(metrics) == METRIC_KEYS
    return PipelineResult(ing, pop, metrics, [c.strftime("%Y-%m-%dT%H:%M:%SZ") for c in cuts], book)
