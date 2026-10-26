// Reason codes mirror domain/revenue_atlas/errors.py.
export const CURRENCY_NOT_ISO4217 = "CURRENCY_NOT_ISO4217";
export const FX_RATE_MISSING = "FX_RATE_MISSING";
export const COST_VERSION_MISSING = "COST_VERSION_MISSING";
export const COST_VERSION_AMBIGUOUS = "COST_VERSION_AMBIGUOUS";
export const RETURN_EXCEEDS_REMAINING = "RETURN_EXCEEDS_REMAINING";
export const CREDIT_SIGN_REVERSED = "CREDIT_SIGN_REVERSED";
export const INVALID_WINDOW = "INVALID_WINDOW";
export const SHIPMENT_LINE_UNKNOWN = "SHIPMENT_LINE_UNKNOWN";
export const MALFORMED_RECORD = "MALFORMED_RECORD";
export const ORPHAN_REFERENCE = "ORPHAN_REFERENCE";
export const CONTRACT_MISMATCH = "CONTRACT_MISMATCH";

export class DomainError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;
  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(`${code}: ${message}`);
    this.name = "DomainError";
    this.code = code;
    this.details = details;
  }
}

/** Python-style string ordering (code point order) for deterministic sorts. */
export const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
