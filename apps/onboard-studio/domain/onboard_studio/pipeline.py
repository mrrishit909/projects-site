"""End to end: ingest -> population -> metrics (D-01..D-05)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ingest import IngestResult, validate_batch
from .metrics import Window, compute_with_flags
from .models import Population


@dataclass
class PipelineResult:
    ingest: IngestResult
    population: Population
    metrics: dict[str, Any]
    flags: list[dict[str, str]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        return self.ingest.counts

    @property
    def rejected(self) -> list[dict[str, Any]]:
        return self.ingest.rejected_dicts()


def pause_override(inputs: dict[str, Any], state: Any) -> Any:
    """Resolve ``state`` to a pause-policy override: ``None`` keeps the configured policy, a state name looks
    up ``inputs["states"][name]`` (``{sla_rule_id: {"pause_policy": [...]}}``), a list or dict is used as is."""
    if state is None or isinstance(state, (list, tuple)):
        return state
    if isinstance(state, dict):
        return {k: v["pause_policy"] if isinstance(v, dict) else v for k, v in state.items()}
    spec = inputs.get("states", {}).get(state)
    if spec is None:
        raise KeyError(f"unknown state {state!r}")
    return {rule: v["pause_policy"] for rule, v in spec.items()}


def run_pipeline(inputs: dict[str, Any], state: Any = None, cutoffs: list[str] | None = None,
                 window: Window = (None, None)) -> PipelineResult:
    """Ingest ``inputs``, then compute the metrics of the accepted population in ``state``."""
    ing = validate_batch(inputs)
    pop = ing.population()
    cuts = inputs.get("cutoffs", []) if cutoffs is None else cutoffs
    metrics, flags = compute_with_flags(pop, pause_override(inputs, state), cuts, window)
    return PipelineResult(ing, pop, metrics, flags)
