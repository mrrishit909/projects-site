// Domain errors and reason codes (docs/contracts.md D-01..D-06, tests/fixtures/golden/CALCULATION.md D-P8-01..13).
export const NEGATIVE_QUANTITY = "NEGATIVE_QUANTITY";
export const MISSING_FIELD = "MISSING_FIELD";
export const BACKFILL_OVERLAP = "BACKFILL_OVERLAP";
export const CHECKPOINT_REGRESSION = "CHECKPOINT_REGRESSION";
export const CHECKPOINT_GAP = "CHECKPOINT_GAP";
export const DUPLICATE_ID = "DUPLICATE_ID";
export const DEPENDENT_REJECTED = "DEPENDENT_REJECTED";
export const UNKNOWN_SOURCE = "UNKNOWN_SOURCE";
export const UNKNOWN_BATCH = "UNKNOWN_BATCH";
export const UNKNOWN_RUN = "UNKNOWN_RUN";
export const UNKNOWN_TASK_RUN = "UNKNOWN_TASK_RUN";
export const UNKNOWN_BACKFILL = "UNKNOWN_BACKFILL";
export const SCHEMA_CHANGED = "SCHEMA_CHANGED";
export const CURSOR_LOOP = "CURSOR_LOOP";
export const RETRY_TOO_SOON = "RETRY_TOO_SOON";
export const RETRY_EXHAUSTED = "RETRY_EXHAUSTED";
export const INVALID_FIELD = "INVALID_FIELD";
export const UNKNOWN_OP = "UNKNOWN_OP";
export const DELETE_TARGET_UNKNOWN = "DELETE_TARGET_UNKNOWN";
export const MALFORMED_RECORD = "MALFORMED_RECORD";
export const PARTITION_ALIGNMENT = "PARTITION_ALIGNMENT";
export const INVALID_RANGE = "INVALID_RANGE";
export const EVENT_IN_FUTURE = "EVENT_IN_FUTURE";            // D-09 / R8-01: an event dated after its batch's arrival or after the cutoff
export const WATERMARK_REGRESSION = "WATERMARK_REGRESSION";  // D-09 / R8-02
export const FETCH_SESSION_REQUIRED = "FETCH_SESSION_REQUIRED";  // D-09 / R8-06

export class DomainError extends Error {
  readonly code: string; readonly path: string | null; readonly details: Record<string, unknown>;
  constructor(code: string, message: string, path: string | null = null, details: Record<string, unknown> = {}) {
    super(`${code}: ${message}`);
    this.name = "DomainError";
    this.code = code; this.path = path; this.details = details;
  }
}
