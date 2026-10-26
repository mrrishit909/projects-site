// Domain errors and reason codes (docs/contracts.md D-01..D-06). Same codes as domain/supplyscope/errors.py.
export const DUPLICATE_MOVEMENT_ID = "DUPLICATE_MOVEMENT_ID";
export const DUPLICATE_MOVEMENT_CONFLICT = "DUPLICATE_MOVEMENT_CONFLICT";
export const RECEIPT_BEFORE_ORDER = "RECEIPT_BEFORE_ORDER";
export const RECEIPT_EXCEEDS_ORDERED = "RECEIPT_EXCEEDS_ORDERED";
export const RECEIPT_BEFORE_LEAD_TIME = "RECEIPT_BEFORE_LEAD_TIME";
export const UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE";
export const MALFORMED_RECORD = "MALFORMED_RECORD";
export const DUPLICATE_ID = "DUPLICATE_ID";
export const CONTRACT_MISMATCH = "CONTRACT_MISMATCH";
export const INVALID_WINDOW = "INVALID_WINDOW";
export const FORECAST_CUTOFF_IN_FUTURE = "FORECAST_CUTOFF_IN_FUTURE";
export const UNSUPPORTED_SERVICE_TARGET = "UNSUPPORTED_SERVICE_TARGET";
export const UNMET_POLICY_CONFLICT = "UNMET_POLICY_CONFLICT";
export const POLICY_SEED_MISMATCH = "POLICY_SEED_MISMATCH";
export const UNKNOWN_STATE = "UNKNOWN_STATE";
export const UNKNOWN_POLICY = "UNKNOWN_POLICY";
/** A flag (a warning on a reconstruction), not an error. */
export const NEGATIVE_STOCK = "NEGATIVE_STOCK";

/** A business-rule violation with a stable machine-readable code. */
export class DomainError extends Error {
  readonly code: string;
  readonly path: string | null;
  readonly details: Readonly<Record<string, unknown>>;
  constructor(code: string, message: string, path: string | null = null, details: Record<string, unknown> = {}) {
    super(`${code}: ${message}`);
    this.name = "DomainError";
    this.code = code;
    this.path = path;
    this.details = details;
  }
}
