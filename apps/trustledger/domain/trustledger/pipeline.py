"""End to end: ingest -> metrics (D-01..D-06). The pipeline's optional ``truth`` goes only to the verification layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .contract import CONTRACT_VERSION, METRIC_KEYS
from .ingest import IngestResult, validate_batch
from .metrics import Computation, Window, compute
from .models import Population
from .timeutil import iso_z, parse_ts
from .verification import truth_map


@dataclass
class PipelineResult:
    ingest: IngestResult
    population: Population
    metrics: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    computation: Computation | None = None
    as_of: datetime | None = None

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        return self.ingest.counts

    @property
    def rejected(self) -> list[dict[str, Any]]:
        return self.ingest.rejected_dicts()

    @property
    def empty_population(self) -> bool:
        return self.computation.empty_population  # type: ignore[union-attr]

    def golden(self) -> dict[str, Any]:
        """The shape of expected.json."""
        c = self.computation
        assert c is not None
        return {"contract_version": CONTRACT_VERSION, "as_of": iso_z(self.as_of), "weight_version": c.weight_version,
                "checklist_version": self.population.checklist_version, "empty_population": c.empty_population,
                "ingest": {"counts": self.counts, "rejected_records": self.rejected},
                "rules": c.rules, "metrics": self.metrics, "definitions": c.definitions, "matching": c.matching}


def run_pipeline(inputs: dict[str, Any], as_of: str | datetime | None = None, weight_version: str | None = None,
                 window: Window | None = None, truth: Mapping[str, str] | None = None) -> PipelineResult:
    """Ingest ``inputs`` (the shape of inputs.json) and compute the metrics at ``as_of`` (default: the inputs' own).

    ``truth`` is the synthetic truth (record id -> entity id) for the precision step only; when omitted the inputs' own top-level
    ``synthetic_truth`` block is used if it has one, and without either precision is null. Nothing but
    ``verification.precision_block`` ever reads it."""
    when = parse_ts(as_of or inputs["as_of"])
    ing = validate_batch(inputs)
    tm = truth if truth is not None else truth_map(inputs.get("synthetic_truth"))
    comp = compute(ing.population, when, weight_version, window, tm)
    assert tuple(comp.metrics) == METRIC_KEYS
    return PipelineResult(ing, ing.population, comp.metrics, comp.warnings, comp, when)
