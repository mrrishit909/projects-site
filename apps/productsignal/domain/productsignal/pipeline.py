"""End to end: ingest -> canonical events -> metrics (D-01..D-05)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .contract import CONTRACT_VERSION, METRIC_KEYS
from .events import Canon
from .ingest import IngestResult, validate_batch
from .metrics import Computation, compute
from .models import Plan, Population, default_windows, parse_funnel, parse_plan, parse_windows
from .timeutil import parse_ts


@dataclass
class PipelineResult:
    ingest: IngestResult
    population: Population
    metrics: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    computation: Computation | None = None
    cutoff: datetime | None = None

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        """Ingest counts. Events are counted as the canonical log of this run: accepted = canonical, merged = duplicates
        dropped (plus idempotent repeats), rows received after the cutoff are in neither (they are in tracking_quality)."""
        c = {k: dict(v) for k, v in self.ingest.counts.items()}
        comp = self.computation
        if comp is not None:
            c["events"] = {"accepted": comp.tracking_quality["canonical"], "rejected": c["events"]["rejected"],
                           "merged": comp.tracking_quality["duplicates_dropped"] + c["events"]["merged"]}
        return c

    @property
    def rejected(self) -> list[dict[str, Any]]:
        return self.ingest.rejected_dicts()

    @property
    def tracking_quality(self) -> dict[str, int]:
        return self.computation.tracking_quality  # type: ignore[union-attr]

    @property
    def identity(self) -> dict[str, int]:
        return self.computation.identity  # type: ignore[union-attr]

    @property
    def empty_population(self) -> bool:
        return self.computation.empty_population  # type: ignore[union-attr]

    def golden(self) -> dict[str, Any]:
        """The shape of expected.json."""
        return {"contract_version": CONTRACT_VERSION, "empty_population": self.empty_population,
                "ingest": {"counts": self.counts, "rejected_records": self.rejected},
                "tracking_quality": self.tracking_quality, "identity": self.identity, "metrics": self.metrics}


def run_pipeline(inputs: dict[str, Any], cutoff: str | datetime | None = None, experiment_version_id: str | None = None,
                 run_id: str | None = None) -> PipelineResult:
    """Ingest ``inputs`` (the shape of inputs.json) and compute the metrics at ``cutoff`` (default: the inputs' own cutoff).
    A run at an earlier cutoff sees only events received by then (D-01)."""
    plans: dict[str, Plan] = {}
    if inputs.get("analysis_plan") is not None:
        p = parse_plan(inputs["analysis_plan"])
        plans[p.experiment_version_id] = p
    when = parse_ts(cutoff or inputs["cutoff"])
    ing = validate_batch(inputs, plans)
    mw = inputs.get("metric_windows")
    funnels = [parse_funnel(mw["funnel"])] if mw and mw.get("funnel") else []
    windows = parse_windows(mw) if mw else default_windows(when)
    pop = ing.population(plans, funnels=funnels, windows=windows)
    comp = compute(pop, when, windows, funnels[0] if funnels else None, experiment_version_id, run_id)
    assert tuple(comp.metrics) == METRIC_KEYS
    return PipelineResult(ing, pop, comp.metrics, comp.warnings, comp, when)
