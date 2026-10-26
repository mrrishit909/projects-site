// Mirrors domain/revenue_atlas/fx.py: dated FX lookup (D-02).
import { REPORTING_CURRENCY } from "./contract";
import { type Dec, ONE } from "./decimal";
import { DomainError, FX_RATE_MISSING } from "./errors";
import type { ExchangeRate } from "./types";

export type RateIndex = Map<string, Dec>;

/** Index "currency|date" -> rate for reporting-currency rows. First row wins, as in Python. */
export function indexRates(rates: readonly ExchangeRate[]): RateIndex {
  const idx: RateIndex = new Map();
  for (const r of rates) {
    if (r.reporting_currency !== REPORTING_CURRENCY) continue;
    const k = `${r.currency}|${r.rate_date}`;
    if (!idx.has(k)) idx.set(k, r.rate);
  }
  return idx;
}

/**
 * Rate whose rate_date equals `date` (YYYY-MM-DD). A row lookup comes first; USD->USD is 1 without
 * a row. Anything else missing raises FX_RATE_MISSING and is never defaulted (D-02).
 */
export function rateFor(currency: string, date: string, idx: RateIndex): Dec {
  const hit = idx.get(`${currency}|${date}`);
  if (hit) return hit;
  if (currency === REPORTING_CURRENCY) return ONE;
  throw new DomainError(FX_RATE_MISSING, `no ${currency}->${REPORTING_CURRENCY} rate on ${date}`, { currency, date });
}
