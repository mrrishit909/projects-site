"""Historical cost resolution (D-03)."""
from __future__ import annotations

from datetime import datetime, timezone

from .errors import COST_VERSION_AMBIGUOUS, COST_VERSION_MISSING, DomainError
from .models import CostVersion


def resolve_cost_version(product_id: str, shipped_at: datetime,
                         cost_versions: list[CostVersion]) -> CostVersion:
    """Single version of the product with ``valid_from <= UTC date < valid_to``."""
    day = shipped_at.astimezone(timezone.utc).date().isoformat()
    hits = [c for c in cost_versions
            if c.product_id == product_id and c.valid_from <= day
            and (c.valid_to is None or day < c.valid_to)]
    if not hits:
        raise DomainError(COST_VERSION_MISSING, f"no cost version for {product_id} on {day}",
                          details={"product_id": product_id, "date": day})
    if len(hits) > 1:
        raise DomainError(COST_VERSION_AMBIGUOUS, f"{len(hits)} cost versions for {product_id} on {day}",
                          details={"product_id": product_id, "date": day,
                                   "cost_version_ids": sorted(c.cost_version_id for c in hits)})
    return hits[0]
