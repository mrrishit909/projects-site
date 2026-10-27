"""``run_pipeline``: validate a dataset, compute the metrics, and shape the result exactly like ``expected.json``."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .context import Window
from .contract import CONTRACT_VERSION
from .ingest import Ingest, Population, parse_as_of, validate_batch
from .metrics import compute
from .timeutil import parse_ts


@dataclass
class PipelineResult:
    ingest: Ingest
    population: Population
    as_of: datetime
    metrics: dict[str, Any]
    warnings: list[dict[str, Any]]

    @property
    def empty_population(self) -> bool:
        return not self.population.acc["initiatives"]

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        return self.ingest.counts()

    def golden(self) -> dict[str, Any]:
        """The whole shape of ``expected.json``."""
        cfg = self.population.config
        return {"contract_version": CONTRACT_VERSION, "as_of": cfg["as_of"] if self.as_of == parse_as_of(cfg["as_of"]) else self.as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "period_basis": cfg["period_basis"], "empty_population": self.empty_population,
                "ingest": {"counts": self.counts, "rejected_records": self.ingest.rejected_records()}, "metrics": self.metrics}


def run_pipeline(inputs: dict[str, Any], as_of: str | None = None, window: Window | None = None, scenario_ids: list[str] | None = None) -> PipelineResult:
    ing = validate_batch(inputs)
    when = parse_ts(as_of or inputs["as_of"])
    metrics, warnings = compute(ing.population, when, window, scenario_ids)
    return PipelineResult(ing, ing.population, when, metrics, warnings)
