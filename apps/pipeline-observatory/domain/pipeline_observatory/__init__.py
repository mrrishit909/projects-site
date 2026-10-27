"""Pipeline Observatory domain package (contract v1). Standard library only; Fraction for ratios, Decimal for money, no floats."""
from .contract import CONTRACT_VERSION, METRIC_KEYS, ROLES
from .errors import DomainError
from .ingest import validate_import
from .metrics import compute, run_pipeline

__all__ = ["CONTRACT_VERSION", "METRIC_KEYS", "ROLES", "DomainError", "validate_import", "compute", "run_pipeline"]
