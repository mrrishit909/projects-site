"""ProductSignal domain package (contract v1). Standard library only; Fraction and Decimal, no floats."""
from .contract import CONTRACT_VERSION, METRIC_KEYS
from .errors import DomainError
from .ingest import validate_batch
from .metrics import compute
from .pipeline import PipelineResult, run_pipeline

__all__ = ["CONTRACT_VERSION", "METRIC_KEYS", "DomainError", "validate_batch", "compute", "run_pipeline", "PipelineResult"]
