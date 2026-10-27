// Domain errors and reason codes (docs/contracts.md D-01..D-05; the fixture's D-P10-14/15). The strings are the Python domain's.
export const POST_OUTCOME_FIELD = "POST_OUTCOME_FIELD", LATENT_TRUTH = "LATENT_TRUTH", ID_FEATURE = "ID_FEATURE", UNKNOWN_FEATURE = "UNKNOWN_FEATURE";
export const FEATURE_PRIORITY = [POST_OUTCOME_FIELD, LATENT_TRUTH, ID_FEATURE, UNKNOWN_FEATURE] as const;
export const LEAKAGE = "LEAKAGE", CALIBRATION_ON_FIT_ROWS = "CALIBRATION_ON_FIT_ROWS", THRESHOLD_ON_TEST = "THRESHOLD_ON_TEST";
export const CAPACITY_EXCEEDS_POPULATION = "CAPACITY_EXCEEDS_POPULATION";
export const DUPLICATE_ID = "DUPLICATE_ID", DEPENDENT_REJECTED = "DEPENDENT_REJECTED", UNKNOWN_ACCOUNT = "UNKNOWN_ACCOUNT", UNKNOWN_CUTOFF = "UNKNOWN_CUTOFF";
export const UNKNOWN_TRAINING_RUN = "UNKNOWN_TRAINING_RUN", UNKNOWN_SCENARIO = "UNKNOWN_SCENARIO", SYNTHETIC_REQUIRED = "SYNTHETIC_REQUIRED";
export const AVAILABILITY_BEFORE_EVENT = "AVAILABILITY_BEFORE_EVENT", PROBABILITY_OUT_OF_RANGE = "PROBABILITY_OUT_OF_RANGE", CENSORED_LABEL = "CENSORED_LABEL";
export const OUTREACH_NOT_DRAFT = "OUTREACH_NOT_DRAFT", MALFORMED_RECORD = "MALFORMED_RECORD";
export const RISK_NOT_RESPONSIVENESS = "RISK_NOT_RESPONSIVENESS";

export interface Offending { item: unknown; code: string }
/** A business-rule violation with a stable machine-readable code; `offending` lists every offending item. */
export class DomainError extends Error {
  constructor(readonly code: string, readonly detail: string, readonly path: string | null = null, readonly offending: Offending[] = []) {
    super(`${code}: ${detail}`);
  }
}
