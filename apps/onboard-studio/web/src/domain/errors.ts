// Domain errors and reason codes (docs/contracts.md D-01..D-05). Mirrors domain/onboard_studio/errors.py.
export const SELF_APPROVAL = "SELF_APPROVAL";
export const DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE";
export const STEP_NOT_READY = "STEP_NOT_READY";
export const MISSING_REQUIRED_DOCUMENT = "MISSING_REQUIRED_DOCUMENT";
export const CASE_ALREADY_COMPLETE = "CASE_ALREADY_COMPLETE";
export const PAUSE_REASON_NOT_CONFIGURED = "PAUSE_REASON_NOT_CONFIGURED";
export const WORKFLOW_VERSION_NOT_PUBLISHED = "WORKFLOW_VERSION_NOT_PUBLISHED";
export const DECISION_CONFLICT = "DECISION_CONFLICT";
export const MALFORMED_RECORD = "MALFORMED_RECORD";
export const ORPHAN_REFERENCE = "ORPHAN_REFERENCE";
export const DUPLICATE_ID = "DUPLICATE_ID";
export const CONTRACT_MISMATCH = "CONTRACT_MISMATCH";
export const INVALID_WINDOW = "INVALID_WINDOW";
export const ROLE_MISMATCH = "ROLE_MISMATCH";
export const INVALID_TRANSITION = "INVALID_TRANSITION";

/** Reasons that reject a whole case with its child rows at ingest, in priority order. */
export const CASE_REASONS: readonly string[] = [
  WORKFLOW_VERSION_NOT_PUBLISHED, DEPENDENCY_CYCLE, SELF_APPROVAL, STEP_NOT_READY,
  MISSING_REQUIRED_DOCUMENT, CASE_ALREADY_COMPLETE, PAUSE_REASON_NOT_CONFIGURED, ORPHAN_REFERENCE,
];

/** A business-rule violation with a stable machine-readable code. */
export class DomainError extends Error {
  readonly code: string;
  readonly path: string | undefined;
  readonly details: Record<string, unknown>;
  constructor(code: string, message: string, path?: string, details: Record<string, unknown> = {}) {
    super(`${code}: ${message}`);
    this.name = "DomainError";
    this.code = code;
    this.path = path;
    this.details = details;
  }
}
