"""SupplyScope domain package (contract v1). Standard library only."""
from .contract import CONTRACT_VERSION
from .errors import DomainError
from .metrics import compute_metrics, group_metrics
from .pipeline import PipelineResult, run_pipeline

__all__ = ["CONTRACT_VERSION", "DomainError", "compute_metrics", "group_metrics", "run_pipeline", "PipelineResult"]
