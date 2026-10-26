"""ServiceFlow domain package (contract v1). Standard library only."""
from .contract import CONTRACT_VERSION
from .errors import DomainError
from .ingest import validate_batch
from .metrics import compute_metrics, disclosures, group_metrics
from .pipeline import PipelineResult, run_pipeline
from .simulation import compare_policies, simulate

__all__ = ["CONTRACT_VERSION", "DomainError", "compute_metrics", "group_metrics", "disclosures", "run_pipeline",
           "PipelineResult", "validate_batch", "simulate", "compare_policies"]
