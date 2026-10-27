// Import validation (D-P10-15): per row DUPLICATE_ID, then foreign keys in the documented order (a parent that was itself rejected gives
// DEPENDENT_REJECTED, an absent one UNKNOWN_*), then the domain rule. Entities are processed parents first; the rejected list is in
// processing order and keeps every row; nothing is silently dropped.
import { ENTITIES, EVENTS, FK, ID, type Entity } from "./contract";
import * as E from "./errors";
import type { Row } from "./models";
import { cmpFr, fr, toFraction } from "./num";
import { daysUs, parseTs } from "./time";

export interface Rejected { entity: Entity; id: unknown; reason_code: string }
export interface Ingest { accepted: Record<Entity, Row[]>; rejected: Rejected[]; counts(): Record<string, { accepted: number; rejected: number }> }

function domainRule(entity: Entity, row: Row, cutoffs: Map<unknown, Row>, asOf: bigint, grace: number): string | null {
  if (entity === "accounts" && row["synthetic"] !== true) return E.SYNTHETIC_REQUIRED;
  if ((EVENTS as readonly string[]).includes(entity) && parseTs(row["available_at"]) < parseTs(row["event_at"])) return E.AVAILABILITY_BEFORE_EVENT;
  if (entity === "predictions") { const p = toFraction(row["probability"]); if (!(cmpFr(fr(0), p) <= 0 && cmpFr(p, fr(1)) <= 0)) return E.PROBABILITY_OUT_OF_RANGE; }
  if (entity === "labels") {
    const c = cutoffs.get(row["cutoff_id"]);
    if (c === undefined) throw new Error("KeyError");
    if (parseTs(c["horizon_end"]) + daysUs(grace) > asOf && row["churned"] !== null && row["churned"] !== undefined) return E.CENSORED_LABEL;
  }
  if (entity === "outreach_events" && row["status"] !== "draft") return E.OUTREACH_NOT_DRAFT;
  return null;
}

export function validate(data: Row): Ingest {
  const asOf = parseTs(data["as_of"]);
  const grace: number = data["label_version"]["grace_days"];
  const accepted = Object.fromEntries(ENTITIES.map((e) => [e, [] as Row[]])) as Record<Entity, Row[]>;
  const okIds = Object.fromEntries(ENTITIES.map((e) => [e, new Set<unknown>()])) as Record<Entity, Set<unknown>>;
  const rejIds = Object.fromEntries(ENTITIES.map((e) => [e, new Set<unknown>()])) as Record<Entity, Set<unknown>>;
  const rejected: Rejected[] = [];
  const cutoffs = new Map<unknown, Row>();
  for (const entity of ENTITIES) {
    for (const row of (data[entity] ?? []) as Row[]) {
      const idKey = ID[entity];
      if (!row || typeof row !== "object" || Array.isArray(row) || !(idKey in row)) { rejected.push({ entity, id: null, reason_code: E.MALFORMED_RECORD }); continue; }
      const rid = row[idKey];
      let code: string | null = okIds[entity].has(rid) ? E.DUPLICATE_ID : null;
      if (code === null) {
        for (const [fk, parent, unknown] of FK[entity] ?? []) {
          const pid = row[fk] === undefined ? null : row[fk];
          if (okIds[parent].has(pid)) continue;
          code = rejIds[parent].has(pid) ? E.DEPENDENT_REJECTED : unknown;
          break;
        }
      }
      if (code === null) {
        try { code = domainRule(entity, row, cutoffs, asOf, grace); } catch { code = E.MALFORMED_RECORD; }
      }
      if (code) {
        rejected.push({ entity, id: rid, reason_code: code });
        if (code !== E.DUPLICATE_ID) rejIds[entity].add(rid);
      } else {
        accepted[entity].push(row);
        okIds[entity].add(rid);
        if (entity === "prediction_cutoffs") cutoffs.set(rid, row);
      }
    }
  }
  return {
    accepted, rejected,
    counts: () => Object.fromEntries(ENTITIES.map((e) => [e, { accepted: accepted[e].length, rejected: rejected.filter((r) => r.entity === e).length }])),
  };
}
