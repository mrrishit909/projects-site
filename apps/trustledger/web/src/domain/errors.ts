// Domain errors and reason codes (docs/contracts.md D-01..D-08; mirror of domain/trustledger/errors.py).
export const OWNER_REQUIRED = "OWNER_REQUIRED";
export const DUPLICATE_PAIR = "DUPLICATE_PAIR";
export const NON_CANONICAL_ORDER = "NON_CANONICAL_ORDER";
export const REVIEWER_IS_PROPOSER = "REVIEWER_IS_PROPOSER";
export const DEPENDENT_REJECTED = "DEPENDENT_REJECTED";
export const UNKNOWN_OWNER = "UNKNOWN_OWNER";
export const OWNER_INACTIVE = "OWNER_INACTIVE";
export const CLASSIFICATION_REQUIRED = "CLASSIFICATION_REQUIRED";
export const UNKNOWN_DATASET = "UNKNOWN_DATASET";
export const UNKNOWN_RULE = "UNKNOWN_RULE";
export const UNKNOWN_RULE_RUN = "UNKNOWN_RULE_RUN";
export const UNKNOWN_METRIC_VERSION = "UNKNOWN_METRIC_VERSION";
export const UNKNOWN_RECORD = "UNKNOWN_RECORD";
export const UNKNOWN_CANDIDATE = "UNKNOWN_CANDIDATE";
export const UNKNOWN_MERGE = "UNKNOWN_MERGE";
export const SAME_RECORD = "SAME_RECORD";
export const INVALID_CANDIDATE = "INVALID_CANDIDATE";
export const ROLE_NOT_PERMITTED = "ROLE_NOT_PERMITTED";
export const MALFORMED_RECORD = "MALFORMED_RECORD";
export const DUPLICATE_ID = "DUPLICATE_ID";
export const SCHEDULE_REQUIRED = "SCHEDULE_REQUIRED";
export const INVALID_COUNTS = "INVALID_COUNTS";
export const ALREADY_REVIEWED = "ALREADY_REVIEWED";
export const INVALID_REVERSAL = "INVALID_REVERSAL";
export const ALREADY_REVERSED = "ALREADY_REVERSED";
export const VERIFICATION_RUN_INVALID = "VERIFICATION_RUN_INVALID";
export const INVALID_WINDOW = "INVALID_WINDOW";
export const INVALID_GROUP = "INVALID_GROUP";
export const UNKNOWN_WEIGHT_VERSION = "UNKNOWN_WEIGHT_VERSION";
export const WEIGHT_CHANGE_REQUIRES_VERSION = "WEIGHT_CHANGE_REQUIRES_VERSION";
export const RULE_VERSION_DIFFERS = "RULE_VERSION_DIFFERS";

/** A business-rule violation with a stable machine-readable code. */
export class DomainError extends Error {
  constructor(readonly code: string, readonly detail: string, readonly path: string | null = null) {
    super(`${code}: ${detail}`);
    this.name = "DomainError";
  }
}
/** The TypeScript twin of Python's ValueError for instants, zones and local times. */
export class ValueError extends Error {
  constructor(message: string) { super(message); this.name = "ValueError"; }
}
