"""RetentionLab domain package (contract v1). Standard library only; ``Fraction`` for every ratio and score, ``Decimal`` for money
and the one logarithm, no float in any published figure (floats exist only inside ``fitting``)."""
from .contract import CONTRACT_VERSION
from .errors import DomainError
from .ingest import validate
from .pipeline import evaluate

__all__ = ["CONTRACT_VERSION", "DomainError", "validate", "evaluate"]
