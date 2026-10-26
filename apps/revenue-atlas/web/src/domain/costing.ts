// Mirrors domain/revenue_atlas/costing.py: historical cost resolution (D-03).
import { COST_VERSION_AMBIGUOUS, COST_VERSION_MISSING, DomainError } from "./errors";
import { utcDate } from "./ingest";
import type { CostVersion } from "./types";

export type CostIndex = Map<string, CostVersion[]>;

export function indexCosts(versions: readonly CostVersion[]): CostIndex {
  const idx: CostIndex = new Map();
  for (const c of versions) {
    const list = idx.get(c.product_id);
    if (list) list.push(c);
    else idx.set(c.product_id, [c]);
  }
  return idx;
}

/** The single version of the product with valid_from <= UTC date < valid_to (open if valid_to is null). */
export function resolveCostVersion(productId: string, shippedAt: number, idx: CostIndex): CostVersion {
  const day = utcDate(shippedAt);
  const hits = (idx.get(productId) ?? []).filter((c) => c.valid_from <= day && (c.valid_to === null || day < c.valid_to));
  if (hits.length === 0) throw new DomainError(COST_VERSION_MISSING, `no cost version for ${productId} on ${day}`, { product_id: productId, date: day });
  if (hits.length > 1) {
    throw new DomainError(COST_VERSION_AMBIGUOUS, `${hits.length} cost versions for ${productId} on ${day}`, {
      product_id: productId, date: day, cost_version_ids: hits.map((c) => c.cost_version_id).sort(),
    });
  }
  return hits[0]!;
}
