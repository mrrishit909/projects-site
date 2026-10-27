// Refusal rules for the commands (D-P10-14): pure checks that throw a DomainError with every offending item listed. The same functions serve the
// fixture's requests (pipeline.ts) and the in-browser checks of the evidence page.
import * as E from "./errors";
import type { Row } from "./models";
import { classifyFeature } from "./world";

const refuse = (code: string, message: string, offending: E.Offending[], path: string): E.DomainError => new E.DomainError(code, message, path, offending);

/** Refuse a request naming a post-outcome, latent, identifier-derived or unregistered field; the code is the first in the order POST_OUTCOME_FIELD,
 * LATENT_TRUTH, ID_FEATURE, UNKNOWN_FEATURE, DUPLICATE_FIELD and every offending field is listed with its own code. */
export function checkFeatureRequest(registry: Map<string, Row>, fields: readonly string[]): string[] {
  const bad = fields.map((f) => [f, classifyFeature(registry, f)] as const).filter((x): x is readonly [string, string] => x[1] !== null);
  const flagged = new Set(bad.map(([f]) => f)), seen = new Set<string>();
  for (const f of fields) {                                // D-09 (R10-15): a field named twice is refused once per repeated name, after every other code
    if (seen.has(f) && !flagged.has(f)) { bad.push([f, E.DUPLICATE_FIELD] as const); flagged.add(f); }
    seen.add(f);
  }
  if (bad.length) {
    const code = bad.map(([, c]) => c).reduce((a, b) => (E.FEATURE_PRIORITY.indexOf(a as never) <= E.FEATURE_PRIORITY.indexOf(b as never) ? a : b));
    throw refuse(code, `the request names fields that cannot be features: ${bad.map(([f]) => f).join(", ")}`, bad.map(([f, c]) => ({ item: f, code: c })), "input.fields");
  }
  return [...fields];
}
/** Preprocessing is fitted on retained training rows only (P10-FLOW-04). */
export function checkFitRows(fitRows: readonly string[], retainedTrain: Set<string>): void {
  const bad = fitRows.filter((c) => !retainedTrain.has(c));
  if (bad.length) throw refuse(E.LEAKAGE, "preprocessing may be fitted on retained training rows only", bad.map((c) => ({ item: c, code: "NOT_TRAINING_ROW" })), "input.fit_rows");
}
/** Platt scaling is fitted on retained validation rows and never evaluated on the rows it was fitted on (P10-FLOW-06). */
export function checkCalibrationRows(fitRows: readonly string[], evaluationRows: readonly string[], retainedValidation: Set<string>): void {
  const fit = new Set(fitRows);
  const overlap = evaluationRows.filter((c) => fit.has(c));
  if (overlap.length) throw refuse(E.CALIBRATION_ON_FIT_ROWS, "the reliability curve must use rows the calibration did not see", overlap.map((c) => ({ item: c, code: "IN_FIT_ROWS" })), "input.evaluation_rows");
  const bad = fitRows.filter((c) => !retainedValidation.has(c));
  if (bad.length) throw refuse(E.LEAKAGE, "calibration may be fitted on retained validation rows only", bad.map((c) => ({ item: c, code: "NOT_VALIDATION_ROW" })), "input.fit_rows");
}
/** Capacity and thresholds are chosen on validation; the test set is read once (P10-FLOW-06, P10-TEST-06). */
export function checkThreshold(parameter: string, selectedOn: string): void {
  if (selectedOn !== "validation") throw refuse(E.THRESHOLD_ON_TEST, "capacity and thresholds are chosen on validation rows; the test set is read once", [{ item: parameter, code: `SELECTED_ON_${selectedOn.toUpperCase()}` }], "input.selected_on");
}
/** K may not exceed the scored eligible population (P10-MET-02, P10-TEST-10). */
export function checkCapacity(scenarioId: string, capacity: number, population: number): void {
  if (capacity > population) throw refuse(E.CAPACITY_EXCEEDS_POPULATION, `capacity ${capacity} exceeds the population ${population}`, [{ item: scenarioId, code: `CAPACITY_${capacity}_GT_${population}` }], "input.capacity");
}
/** A basis other than the risk ranking is a claim of treatment responsiveness, which a churn risk cannot support (P10-FLOW-08, P10-TEST-09). */
export function checkBasis(basis: string): void {
  if (basis !== "risk_ranking") throw refuse(E.RISK_NOT_RESPONSIVENESS, "a churn risk ranks accounts; it does not say who would respond to an offer", [{ item: basis, code: "BASIS_NOT_RISK_RANKING" }], "input.basis");
}
/** A report's as_of may not be later than the server clock (D-09, R10-01): the future is not known, so no label can be mature in it. Instants are epoch
 * microsecond bigints (time.ts). Mirrors rules.check_as_of; the site offers no as-of control, so the guard is exercised by the check scripts. */
export function checkAsOf(asOf: bigint, now: bigint): void {
  if (asOf > now) throw refuse(E.AS_OF_IN_FUTURE, "as_of is later than the server clock; no row can be mature in the future", [{ item: "as_of", code: E.AS_OF_IN_FUTURE }], "as_of");
}
