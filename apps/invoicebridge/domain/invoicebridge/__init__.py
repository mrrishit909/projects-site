"""InvoiceBridge domain package (contract v1). Standard library only; Decimal money, no floats."""
from .contract import CONTRACT_VERSION, METRIC_KEYS
from .errors import DomainError
from .ingest import validate_batch
from .metrics import compute_metrics, disclosures, window_metrics
from .pipeline import PipelineResult, run_pipeline

__all__ = ["CONTRACT_VERSION", "METRIC_KEYS", "DomainError", "validate_batch", "compute_metrics", "window_metrics",
           "disclosures", "run_pipeline", "PipelineResult"]
