"""End to end: ingest -> population -> metrics (D-01..D-06)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .errors import UNKNOWN_STATE, DomainError
from .ingest import IngestResult, validate_batch
from .metrics import Window, compute_metrics, negative_stock_flags
from .models import Population, parse_ts


@dataclass
class PipelineResult:
    ingest: IngestResult
    population: Population
    metrics: dict[str, Any]
    as_of: datetime
    window: Window
    flags: list[dict[str, Any]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        return self.ingest.counts

    @property
    def rejected(self) -> list[dict[str, Any]]:
        return self.ingest.rejected_dicts()


def resolve_state(inputs: Mapping[str, Any], state: Any) -> Mapping[str, Any] | None:
    """``None`` keeps the accepted population; a name looks up ``inputs["states"][name]`` (``add_purchase_order_lines``);
    a dict is used as is."""
    if state is None or isinstance(state, Mapping):
        return state
    spec = inputs.get("states", {}).get(state)
    if spec is None:
        raise DomainError(UNKNOWN_STATE, f"unknown state {state!r}", details={"known": sorted(inputs.get("states", {}))})
    return spec


def run_pipeline(inputs: Mapping[str, Any], state: Any = None, as_of: str | datetime | None = None,
                 window: Window | None = None) -> PipelineResult:
    """Ingest ``inputs``, then compute the metrics of the accepted population in ``state`` at ``as_of``
    (default ``inputs["as_of"]``) over ``window`` (default ``[inputs["window_start"], as_of]``)."""
    ing = validate_batch(inputs)
    pop = ing.population()
    cut = parse_ts(as_of if as_of is not None else inputs["as_of"])
    win = window if window is not None else (parse_ts(inputs["window_start"]) if inputs.get("window_start") else None, None)
    metrics = compute_metrics(pop, cut, win, resolve_state(inputs, state))
    return PipelineResult(ing, pop, metrics, cut, win, negative_stock_flags(pop, cut))
