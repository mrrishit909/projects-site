// Record classification and checkpoint ordering (D-01, D-P8-01, D-P8-11). `classifyRows` decides every raw row of one committed batch, in
// raw_record_id order. Nothing is dropped: every row has exactly one disposition.
//  * a batch whose declared schema_version differs from the source contract is quarantined WHOLE with SCHEMA_CHANGED (P08-TEST-04);
//  * `op = delete` on an accepted key propagates as `deleted` (never ignored, P08-TEST-08); a delete of a key never accepted is quarantined
//    DELETE_TARGET_UNKNOWN; a repeated delete is a duplicate;
//  * otherwise a source_key already accepted in the same source (earlier batch or earlier in this batch) is a duplicate, whatever its payload
//    hash. THE KEY CHECK RUNS BEFORE THE CONTRACT CHECK;
//  * otherwise the contract decides, in this order: MISSING_FIELD, INVALID_FIELD (a payload that is not an object, a quantity that is not an integer of
//    magnitude at most 2**53, money that is not a 2-place decimal string, an event_ts that is not a real instant), NEGATIVE_QUANTITY, EVENT_IN_FUTURE (an event
//    dated after its batch's arrival, the batch's started_at, or after the cutoff; D-09) quarantine; else the row is accepted.
import * as E from "./errors";
import { DomainError } from "./errors";
import { REQUIRED_FIELDS, type Row } from "./contract";
import { isDict, isInt, isNone, sortedBy } from "./py";
import { decFr, ZERO, type Fr } from "./num";
import { isMoney, isQuantity } from "./patterns";
import { parseTs } from "./time";

export const ACCEPTED = "accepted", DUPLICATE = "duplicate", QUARANTINED = "quarantined", DELETED = "deleted";
export interface Disposition { raw_record_id: string; kind: string; reason: string | null }
export { isMoney };

/** The version a commit may carry is previous + 1 (D-01). Less or equal: CHECKPOINT_REGRESSION; more: CHECKPOINT_GAP. */
export function nextCheckpointVersion(previous: number, version: unknown): number {
  if (!isInt(version)) throw new DomainError(E.INVALID_FIELD, "checkpoint version must be an integer", "input.checkpoint_version");
  if (version <= previous) throw new DomainError(E.CHECKPOINT_REGRESSION, `checkpoint version ${version} is not after the committed version ${previous}`, "input.checkpoint_version", { committed_version: previous, requested_version: version });
  if (version !== previous + 1) throw new DomainError(E.CHECKPOINT_GAP, `checkpoint version ${version} skips ${previous + 1}`, "input.checkpoint_version", { committed_version: previous, requested_version: version });
  return version;
}
/** The business amount of a payload as an exact decimal; a row without a usable amount (a payload that is not an object, a missing or malformed field)
 * contributes 0.00: it has no business value (D-09, R8-08). */
export function moneyAmount(payload: unknown, field = "amount"): Fr {
  const v = isDict(payload) ? payload[field] : undefined;
  return isMoney(v) ? decFr(v) : ZERO;
}
/** The latest event instant a row may carry: the earlier of its batch's arrival (started_at) and the cutoff; null when neither is given. */
export function eventLimit(arrival: unknown = null, cutoff: unknown = null): bigint | null {
  const xs = [arrival, cutoff].filter((x) => x !== null && x !== undefined).map((x) => parseTs(x));
  return xs.length ? xs.reduce((a, b) => (a < b ? a : b)) : null;
}
/** The quarantine reason of an upsert payload, or null when it satisfies the contract (D-P8-12 payload fields). `arrival` and `cutoff` bound the event. */
export function contractReason(payload: unknown, arrival: unknown = null, cutoff: unknown = null, limit: bigint | null | undefined = undefined): string | null {
  if (!isDict(payload)) return E.INVALID_FIELD;
  if (REQUIRED_FIELDS.some((k) => isNone(payload[k]))) return E.MISSING_FIELD;
  if (!isQuantity(payload["quantity"]) || !isMoney(payload["unit_price"]) || !isMoney(payload["amount"])) return E.INVALID_FIELD;
  let event: bigint;
  try { event = parseTs(payload["event_ts"]); } catch { return E.INVALID_FIELD; }
  if ((payload["quantity"] as number) < 0) return E.NEGATIVE_QUANTITY;
  const lim = limit !== undefined ? limit : eventLimit(arrival, cutoff);
  if (lim !== null && event > lim) return E.EVENT_IN_FUTURE;
  return null;
}
/** Classify the rows of ONE batch against `acceptedKeys` (every key accepted so far in the source; extended in place, as is `deletedKeys`). */
export function classifyRows(rows: Iterable<Row>, acceptedKeys: Set<unknown>, deletedKeys: Set<unknown> = new Set(), schemaOk = true, arrival: unknown = null, cutoff: unknown = null): Disposition[] {
  const limit = eventLimit(arrival, cutoff);
  const out: Disposition[] = [];
  for (const r of sortedBy(rows, (r) => [r["raw_record_id"] as string])) {
    const rid = r["raw_record_id"] as string, key = r["source_key"], payload = r["payload_json"];
    if (!schemaOk) { out.push({ raw_record_id: rid, kind: QUARANTINED, reason: E.SCHEMA_CHANGED }); continue; }
    const op = isDict(payload) ? (Object.prototype.hasOwnProperty.call(payload, "op") ? payload["op"] : "upsert") : "upsert";
    if (op === "delete") {
      if (!isNone(key) && acceptedKeys.has(key) && !deletedKeys.has(key)) { deletedKeys.add(key); out.push({ raw_record_id: rid, kind: DELETED, reason: null }); }
      else if (!isNone(key) && deletedKeys.has(key)) out.push({ raw_record_id: rid, kind: DUPLICATE, reason: null });
      else out.push({ raw_record_id: rid, kind: QUARANTINED, reason: E.DELETE_TARGET_UNKNOWN });
      continue;
    }
    if (op !== "upsert") { out.push({ raw_record_id: rid, kind: QUARANTINED, reason: E.UNKNOWN_OP }); continue; }
    if (!isNone(key) && acceptedKeys.has(key)) { out.push({ raw_record_id: rid, kind: DUPLICATE, reason: null }); continue; }
    const reason = contractReason(payload, null, null, limit);
    if (reason || isNone(key)) out.push({ raw_record_id: rid, kind: QUARANTINED, reason: reason ?? E.MISSING_FIELD });
    else { acceptedKeys.add(key); out.push({ raw_record_id: rid, kind: ACCEPTED, reason: null }); }
  }
  return out;
}
