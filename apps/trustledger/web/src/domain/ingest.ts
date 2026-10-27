// Ingest: validate a batch of raw rows (D-06 / D-T7-10 rejection codes, dependent rejection). Mirror of domain/trustledger/ingest.py.
// Rejection is atomic per record: a record is accepted or rejected with ONE reason code and its raw row; a child of a rejected parent is
// DEPENDENT_REJECTED (never silently dropped). The synthetic truth block is never read here.
import { DEFAULT_CHECKLIST, DEFAULT_TRIM, ENTITIES, ID_KEYS, type Entity } from "./contract";
import * as E from "./errors";
import { DomainError } from "./errors";
import { verificationProblem } from "./issues";
import { cmp, emptyPopulation, parse, type Candidate, type Decision, type Records, type Row, type Population } from "./models";
import { fracOfDec } from "./num";
import { parseTs } from "./time";

export interface Rejection { entity: string; id: string; reason_code: string; raw_row: Row; message: string }
export interface IngestResult { population: Population; rejected: Rejection[]; counts: Record<string, { accepted: number; rejected: number }> }
export const rejectedDicts = (r: IngestResult): Row[] => r.rejected.map((x) => ({ entity: x.entity, id: x.id, status: "rejected", reason_code: x.reason_code, raw_row: x.raw_row }));

/** The text a char-set strip removes from both ends. */
export function stripChars(s: string, chars: string): string {
  let a = 0, b = s.length;
  while (a < b && chars.includes(s[a]!)) a++;
  while (b > a && chars.includes(s[b - 1]!)) b--;
  return s.slice(a, b);
}
/** Missing: null, or (after trimming `trim`) empty text (D-06). */
export const blank = (v: unknown, trim: string = DEFAULT_TRIM): boolean => v === null || v === undefined || (typeof v === "string" && stripChars(v, trim) === "");

const isObj = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const ridOf = (row: unknown, key: string): string => (isObj(row) && typeof row[key] === "string" ? (row[key] as string) : "");

/** Why a dataset row cannot be loaded (null = it can): a flat object with a non-blank text `row_id` unique in its dataset, whose values are
 * text, integers, booleans or null. (JSON.parse cannot tell 1.0 from 1: a float written with a fractional part is the one case Python
 * rejects and this accepts only if it is integral; the published data holds none.) */
export function rowProblem(row: unknown, seen: Set<string>): string | null {
  const rid = isObj(row) ? row["row_id"] : null;
  if (typeof rid !== "string" || !rid.trim()) return E.MALFORMED_RECORD;
  if (seen.has(rid)) return E.DUPLICATE_ID;
  for (const v of Object.values(row as Row)) {
    if (v === null || typeof v === "string" || typeof v === "boolean") continue;
    if (typeof v === "number" && Number.isInteger(v)) continue;
    return E.MALFORMED_RECORD;
  }
  return null;
}

export function parseConfig(raw: Row, pop: Population): void {
  const wp = isObj(raw["whitespace_policy"]) ? raw["whitespace_policy"] : {};
  pop.trim = typeof wp["trim_characters"] === "string" ? wp["trim_characters"] : DEFAULT_TRIM;
  pop.weight_versions = ((raw["weight_versions"] ?? []) as Row[]).map((w) => ({
    weight_version: w["weight_version"] as string, valid_from: parseTs(w["valid_from"]),
    weights: Object.fromEntries(Object.entries(w["weights"] as Row).map(([k, v]) => [k, fracOfDec(String(v))])),
  }));
  pop.checklist_versions = (raw["checklist_versions"] as Row[] | undefined) ?? [DEFAULT_CHECKLIST];
  pop.checklist_version = (raw["checklist_version"] as string | undefined) || (pop.checklist_versions[pop.checklist_versions.length - 1]!["checklist_version"] as string);
  const probe = (raw["probes"] as Row | undefined)?.["definition_at"];
  pop.probe_definition_at = probe ? parseTs(probe) : null;
  pop.probe_timeliness = (((raw["probes"] as Row | undefined)?.["timeliness"] as Row[] | undefined) ?? []).map((c) => ({
    probe_id: String(c["probe_id"]), timezone: c["timezone"] as string, local_time: c["local_time"] as string, grace_minutes: Number(c["grace_minutes"]),
    last_refreshed_at: c["last_refreshed_at"] ? parseTs(c["last_refreshed_at"]) : null, as_of: parseTs(c["as_of"]) }));
  pop.weight_version = (raw["weight_version"] as string | undefined) ?? null;
}

export function validateBatch(raw: Row): IngestResult {
  const pop = emptyPopulation();
  parseConfig(raw, pop);
  const trim = pop.trim;
  const rej: Rejection[] = [];
  const rejectedIds = Object.fromEntries(ENTITIES.map((e) => [e, new Set<string>()])) as Record<Entity, Set<string>>;
  const seen = Object.fromEntries(ENTITIES.map((e) => [e, new Set<string>()])) as Record<Entity, Set<string>>;

  const reject = (ent: Entity, row: unknown, code: string, msg = ""): void => {
    const rid = ridOf(row, ID_KEYS[ent]);
    if (rid) rejectedIds[ent].add(rid);
    rej.push({ entity: ent, id: rid, reason_code: code, raw_row: isObj(row) ? row : { value: String(row) }, message: msg });
  };
  const section = (ent: string): unknown[] => (Array.isArray(raw[ent]) ? (raw[ent] as unknown[]) : []);
  const parsed = <T extends Entity>(ent: T, row: unknown): Records[T] | null => {
    let obj: Records[T];
    try { obj = parse(ent, row); } catch (err) {
      if (err instanceof DomainError) { reject(ent, row, err.code, err.detail); return null; }
      throw err;
    }
    const rid = (row as Row)[ID_KEYS[ent]] as string;
    if (seen[ent].has(rid)) { reject(ent, row, E.DUPLICATE_ID, `${ID_KEYS[ent]} already loaded`); return null; }
    seen[ent].add(rid);
    return obj;
  };

  const owners = new Map<string, Records["owners"]>();
  for (const r of section("owners")) { const o = parsed("owners", r); if (o) { pop.owners.push(o); owners.set(o.owner_id, o); } }

  const dsOk = new Map<string, Records["datasets"]>();
  for (const r of section("datasets")) {
    const d = parsed("datasets", r);
    if (!d) continue;
    const o = d.owner_id === null ? undefined : owners.get(d.owner_id);
    if (blank(d.owner_id, trim)) reject("datasets", r, E.OWNER_REQUIRED);
    else if (!o) reject("datasets", r, E.UNKNOWN_OWNER);
    else if (o.deactivated_at !== null && d.registered_at >= o.deactivated_at) reject("datasets", r, E.OWNER_INACTIVE);
    else if (blank(d.classification, trim)) reject("datasets", r, E.CLASSIFICATION_REQUIRED);
    else { pop.datasets.push(d); dsOk.set(d.dataset_id, d); }
  }
  const dsBad = rejectedIds.datasets;

  const child = <T extends Entity>(ent: T, parentOk: { has(k: string): boolean }, parentBad: Set<string>, parentKey: keyof Records[T] & string, unknown: string): Records[T][] => {
    const out: Records[T][] = [];
    for (const r of section(ent)) {
      const obj = parsed(ent, r);
      if (!obj) continue;
      const p = obj[parentKey] as unknown as string;
      if (parentOk.has(p)) out.push(obj);
      else if (parentBad.has(p)) reject(ent, r, E.DEPENDENT_REJECTED);
      else reject(ent, r, unknown);
    }
    return out;
  };

  pop.fields = child("fields", dsOk, dsBad, "dataset_id", E.UNKNOWN_DATASET);
  pop.quality_rules = child("quality_rules", dsOk, dsBad, "dataset_id", E.UNKNOWN_DATASET);
  const rules = new Map(pop.quality_rules.map((r) => [r.rule_id, r]));
  pop.rule_runs = child("rule_runs", rules, rejectedIds.quality_rules, "rule_id", E.UNKNOWN_RULE);
  const runs = new Map(pop.rule_runs.map((r) => [r.rule_run_id, r]));
  pop.issues = [];
  const issueRows = new Map<unknown, Row>();
  for (const r of section("issues")) if (isObj(r)) issueRows.set(r["issue_id"], r);
  for (const i of child("issues", runs, rejectedIds.rule_runs, "rule_run_id", E.UNKNOWN_RULE_RUN)) {
    const row = issueRows.get(i.issue_id)!;
    const ver = i.verification_run_id ? runs.get(i.verification_run_id) : undefined;
    if (!owners.has(i.owner_id)) reject("issues", row, E.UNKNOWN_OWNER);
    else if (i.verification_run_id && !ver) reject("issues", row, rejectedIds.rule_runs.has(i.verification_run_id) ? E.DEPENDENT_REJECTED : E.UNKNOWN_RULE_RUN);
    else if (ver && verificationProblem(i, runs.get(i.rule_run_id)!, ver) !== null) reject("issues", row, E.VERIFICATION_RUN_INVALID, verificationProblem(i, runs.get(i.rule_run_id)!, ver) ?? "");
    else pop.issues.push(i);
  }

  for (const r of section("lineage_edges")) {
    const e = parsed("lineage_edges", r);
    if (!e) continue;
    const ends = [e.source_dataset_id, e.target_dataset_id];
    if ((e.evidence_type === "observed") !== (e.observed_at !== null)) reject("lineage_edges", r, E.MALFORMED_RECORD); // D-08: observed edges carry an instant, others none
    else if (e.source_dataset_id === e.target_dataset_id) reject("lineage_edges", r, E.MALFORMED_RECORD, "an edge needs two different datasets"); // D-10 R7-06
    else if (ends.every((x) => dsOk.has(x))) pop.lineage_edges.push(e);
    else if (ends.some((x) => dsBad.has(x))) reject("lineage_edges", r, E.DEPENDENT_REJECTED);
    else reject("lineage_edges", r, E.UNKNOWN_DATASET);
  }

  for (const r of section("metric_versions")) { const m = parsed("metric_versions", r); if (m) pop.metric_versions.push(m); }
  const mvOk = new Set(pop.metric_versions.map((m) => m.metric_version_id));
  for (const r of section("definition_changes")) {
    const c = parsed("definition_changes", r);
    if (!c) continue;
    if (mvOk.has(c.metric_version_id) && (c.previous_metric_version_id === null || mvOk.has(c.previous_metric_version_id))) pop.definition_changes.push(c);
    else reject("definition_changes", r, E.UNKNOWN_METRIC_VERSION);
  }

  for (const r of section("customer_records")) { const c = parsed("customer_records", r); if (c) pop.customer_records.push(c); }
  const recOk = new Set(pop.customer_records.map((c) => c.record_id));

  const seenPairs = new Set<string>(); // a pair is stored once, in canonical order (D-04)
  for (const r of section("match_candidates")) {
    const c = parsed("match_candidates", r);
    if (!c) continue;
    const lo = c.left_record_id, hi = c.right_record_id;
    const key = cmp(lo, hi) < 0 ? `${lo}\u0000${hi}` : `${hi}\u0000${lo}`;
    if (!recOk.has(lo) || !recOk.has(hi)) reject("match_candidates", r, E.UNKNOWN_RECORD);
    else if (lo === hi) reject("match_candidates", r, E.SAME_RECORD);
    else if (!(c.score.n >= 0n && c.score.n <= c.score.d) || blank(c.explanation, trim)) reject("match_candidates", r, E.INVALID_CANDIDATE);
    else if (seenPairs.has(key)) reject("match_candidates", r, E.DUPLICATE_PAIR);
    else if (cmp(lo, hi) > 0) reject("match_candidates", r, E.NON_CANONICAL_ORDER); // code-point order, not UTF-16 (D-10 R7-16)
    else { seenPairs.add(key); pop.match_candidates.push(c); }
  }
  const cand = new Map<string, Candidate>(pop.match_candidates.map((c) => [c.candidate_id, c]));
  const candBad = rejectedIds.match_candidates;

  const accepted = new Map<string, Decision>();
  const reviewed = new Set<string>();
  const reversedIds = new Set<string>();
  const typed: [Decision, unknown][] = [];
  for (const r of section("merge_decisions")) { const m = parsed("merge_decisions", r); if (m) typed.push([m, r]); }
  typed.sort((a, b) => (a[0].decided_at < b[0].decided_at ? -1 : a[0].decided_at > b[0].decided_at ? 1 : cmp(a[0].merge_id, b[0].merge_id)));
  for (const [m, r] of typed) {
    const c = cand.get(m.candidate_id);
    const rev = owners.get(m.reviewer_id);
    const tgt = m.decision === "reverse" && m.reverses_merge_id !== null ? accepted.get(m.reverses_merge_id) : undefined;
    if (candBad.has(m.candidate_id)) reject("merge_decisions", r, E.DEPENDENT_REJECTED);
    else if (m.decision === "reverse" && !tgt) reject("merge_decisions", r, rejectedIds.merge_decisions.has(m.reverses_merge_id!) ? E.DEPENDENT_REJECTED : E.UNKNOWN_MERGE);
    else if (!c || !rev) reject("merge_decisions", r, E.UNKNOWN_CANDIDATE);
    else if (m.reviewer_id === c.proposed_by) reject("merge_decisions", r, E.REVIEWER_IS_PROPOSER);
    else if (!(rev.role === "steward" || rev.role === "admin") || !rev.active) reject("merge_decisions", r, E.ROLE_NOT_PERMITTED);
    else if (m.decision === "reverse" && (tgt!.decision !== "approve" || tgt!.candidate_id !== m.candidate_id || blank(m.reason, trim))) reject("merge_decisions", r, E.INVALID_REVERSAL);
    else if (m.decision === "reverse" && reversedIds.has(m.reverses_merge_id!)) reject("merge_decisions", r, E.ALREADY_REVERSED);
    else if (m.decision !== "reverse" && reviewed.has(m.candidate_id)) reject("merge_decisions", r, E.ALREADY_REVIEWED);
    else {
      accepted.set(m.merge_id, m);
      if (m.decision === "reverse") reversedIds.add(m.reverses_merge_id!); else reviewed.add(m.candidate_id);
    }
  }
  pop.merge_decisions = [...accepted.values()].sort((a, b) => cmp(a.merge_id, b.merge_id));

  // dataset rows follow their dataset (a dataset's whole batch is one record); a bad row is rejected on its own
  const rawRows = isObj(raw["dataset_rows"]) ? (raw["dataset_rows"] as Row) : {};
  let rowsRejected = 0;
  for (const [dsid, rows] of Object.entries(rawRows)) {
    if (dsOk.has(dsid)) {
      const good: Row[] = [], ids = new Set<string>();
      (Array.isArray(rows) ? rows : []).forEach((row: unknown, i: number) => {
        const rid = isObj(row) ? row["row_id"] : null;
        const code = rowProblem(row, ids);
        if (code) {
          rowsRejected++;
          rej.push({ entity: "dataset_rows", id: `${dsid}/${typeof rid === "string" && rid ? rid : i}`, reason_code: code, raw_row: { dataset_id: dsid, row }, message: "" });
        } else { ids.add(rid as string); good.push(row as Row); }
      });
      pop.dataset_rows[dsid] = good;
    } else {
      rowsRejected += Array.isArray(rows) ? rows.length : 0;
      rej.push({ entity: "dataset_rows", id: dsid, reason_code: dsBad.has(dsid) ? E.DEPENDENT_REJECTED : E.UNKNOWN_DATASET, raw_row: { dataset_id: dsid, rows }, message: "" });
    }
  }
  rej.sort((a, b) => cmp(a.entity, b.entity) || cmp(a.id, b.id));
  const counts: IngestResult["counts"] = {};
  for (const e of ENTITIES) counts[e] = { accepted: (pop[e] as unknown[]).length, rejected: rejectedIds[e].size };
  counts["dataset_rows"] = { accepted: Object.values(pop.dataset_rows).reduce((a, v) => a + v.length, 0), rejected: rowsRejected };
  return { population: pop, rejected: rej, counts };
}
