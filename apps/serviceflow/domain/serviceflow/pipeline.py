"""End to end: ingest -> population -> metrics -> simulations (D-01..D-05)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contract import CONTRACT_VERSION, DEFAULT_ABANDONABLE
from .ingest import IngestResult, validate_batch
from .metrics import Window, compute_metrics
from .models import Population
from .simulation import SimulationResult, simulate
from .timeutil import parse_ts


@dataclass
class PipelineResult:
    ingest: IngestResult
    population: Population
    metrics: dict[str, Any]
    simulations: list[SimulationResult] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        return self.ingest.counts

    @property
    def rejected(self) -> list[dict[str, Any]]:
        return self.ingest.rejected_dicts()

    def golden(self) -> dict[str, Any]:
        """The shape of expected.json: contract_version, ingest, metrics, simulation (first run or None)."""
        return {"contract_version": CONTRACT_VERSION,
                "ingest": {"counts": self.counts, "rejected_records": self.rejected},
                "metrics": self.metrics,
                "simulation": self.simulations[0].golden() if self.simulations else None}


def window_of(inputs: dict[str, Any]) -> Window:
    return parse_ts(inputs["window_start"]), parse_ts(inputs["window_end"])


def run_pipeline(inputs: dict[str, Any], window: Window | None = None, cutoffs: list[str] | None = None) -> PipelineResult:
    """Ingest ``inputs`` and compute the metrics of the accepted population plus every accepted simulation run."""
    ing = validate_batch(inputs)
    pop = ing.population()
    win = window or window_of(inputs)
    cuts = [parse_ts(c) for c in (inputs.get("backlog_cutoffs", []) if cutoffs is None else cutoffs)]
    metrics = compute_metrics(pop, win, cuts, inputs.get("abandonable_channels", DEFAULT_ABANDONABLE))
    sims = [simulate(r.config, r.seed, r.warmup_minutes, r.horizon_minutes, r.simulation_id)
            for r in pop.simulation_runs]
    return PipelineResult(ing, pop, metrics, sims)
