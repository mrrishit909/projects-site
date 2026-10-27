// Measuring one rule over a dataset's rows (D-01, D-06): eligible and failing counts, the dimension score, the failing records.
// Dimensions are measured on their own denominators and reported separately:
//   completeness  non-missing / eligible (missing = null or, after trimming, empty)
//   validity      all-eligible (passing / eligible) and populated-only (passing / populated), both labelled; the score uses populated-only
//   uniqueness    duplicate-group share (groups / distinct keys) and duplicate-row share (rows beyond the first / eligible); score 1 - row share
//   relationship  matched / non-null foreign keys; null foreign keys are counted separately, never in the denominator
//   timeliness    the dataset refreshed inside [occurrence, occurrence + grace) of its local daily schedule
// A cell is compared as exact text: text as is, true/false, integers in decimal. Nothing here reads a stored result.
import { stripChars } from "./ingest";
import { compilePattern, type Dataset, type Population, type Row, type Rule } from "./models";
import { fr, p6, ratio, sub, type Fr } from "./num";
import { isoZ, scheduledOccurrence, type Instant } from "./time";

/** The exact text of a cell value (null stays null). */
export function cellText(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}
export const isMissing = (v: unknown, trim: string): boolean => v === null || v === undefined || (typeof v === "string" && stripChars(v, trim) === "");

const compiled = new Map<string, RegExp>();
/** `re.search` semantics; JavaScript's `$` (no m flag) already refuses a final newline, which is the carve-out the Python domain adds. */
export function patternMatches(pattern: string, value: string): boolean {
  let re = compiled.get(pattern);
  if (!re) { re = compilePattern(pattern); compiled.set(pattern, re); }
  return re.test(value);
}

export interface Measure {
  rule: Rule; eligible: number; failures: number;
  /** the dimension score this rule contributes (null = not measured) */
  value: Fr | null;
  /** its entry under metrics.<dimension> */
  block: Row;
  run_extra: Row;
  /** row ids (the dataset id for timeliness) that failed */
  failing: string[];
}

export function runOf(m: Measure, weightVersion: string | null, runAt: Instant): Row {
  const r = m.rule;
  return { dataset_id: r.dataset_id, rule_type: r.rule_type, severity: r.severity, rule_version: r.version_number, weight_version: weightVersion, run_at: isoZ(runAt),
    eligible_count: m.eligible, failure_count: m.failures, ...m.run_extra };
}

/** All rows unless the rule declares a filter {field, equals} (D-06). */
export function eligibleRows(rule: Rule, rows: Row[]): Row[] {
  const f = rule.definition["filter"] as Row | undefined | null;
  if (!f) return rows;
  return rows.filter((r) => cellText(r[f["field"]]) === f["equals"]);
}

/** The evaluated occurrence of a monitored dataset and whether its last refresh fell inside [occurrence, deadline). */
export function timelinessOf(ds: Dataset, asOf: Instant): Row | null {
  if (!ds.monitored) return null;
  const [s, dl] = scheduledOccurrence(ds.refresh_timezone!, ds.refresh_local_time!, ds.refresh_grace_minutes!, asOf);
  const last = ds.last_refreshed_at;
  return { timezone: ds.refresh_timezone, scheduled_local: ds.refresh_local_time, grace_minutes: ds.refresh_grace_minutes, evaluated_occurrence_utc: isoZ(s), deadline_utc: isoZ(dl),
    last_refreshed_at: isoZ(last), on_time: last !== null && s <= last && last < dl };
}

export function measureRule(rule: Rule, pop: Population, asOf: Instant): Measure {
  const ds = pop.datasets.find((d) => d.dataset_id === rule.dataset_id)!;
  const t = rule.rule_type, d = rule.definition, trim = pop.trim;
  const allRows = pop.dataset_rows[rule.dataset_id] ?? [];
  const rows = eligibleRows(rule, allRows);
  if (t === "timeliness") {
    const tl = timelinessOf(ds, asOf);
    if (!tl) return { rule, eligible: 0, failures: 0, value: null, block: {}, run_extra: {}, failing: [] };
    const late = !tl["on_time"];
    return { rule, eligible: 1, failures: late ? 1 : 0, value: fr(late ? 0 : 1), block: tl, run_extra: {}, failing: late ? [rule.dataset_id] : [] };
  }
  const vals = rows.map((r) => r[d["field"]]);
  const ids = rows.map((r) => r["row_id"] as string);
  const el = vals.length;
  if (t === "completeness") {
    const miss: number[] = [];
    vals.forEach((v, i) => { if (isMissing(v, trim)) miss.push(i); });
    const ws = miss.filter((i) => typeof vals[i] === "string" && vals[i] !== "").length;
    const val = ratio(el - miss.length, el);
    const block = { dataset_id: rule.dataset_id, eligible_count: el, missing_count: miss.length, whitespace_only_count: ws, populated_count: el - miss.length, value: p6(val) };
    return { rule, eligible: el, failures: miss.length, value: val, block, run_extra: {}, failing: miss.map((i) => ids[i]!) };
  }
  if (t === "validity") {
    const populated: number[] = [];
    vals.forEach((v, i) => { if (!isMissing(v, trim)) populated.push(i); });
    const passing = populated.filter((i) => typeof vals[i] === "string" && patternMatches(d["pattern"], vals[i] as string));
    const ok = new Set(passing);
    const allv = ratio(passing.length, el), popv = ratio(passing.length, populated.length);
    const block = { dataset_id: rule.dataset_id, eligible_count: el, populated_count: populated.length, passing_count: passing.length,
      all_eligible: { label: "validity_all_eligible", value: p6(allv) }, populated_only: { label: "validity_populated_only", value: p6(popv) } };
    const failing: string[] = [];
    for (let i = 0; i < el; i++) if (!ok.has(i)) failing.push(ids[i]!);
    return { rule, eligible: el, failures: el - passing.length, value: popv, block, run_extra: { populated_count: populated.length }, failing };
  }
  if (t === "uniqueness") {
    const first = new Map<string, number>(), freq = new Map<string, number>();
    const nulls: number[] = [], dup: number[] = [];
    vals.forEach((v, i) => {
      if (isMissing(v, trim)) { nulls.push(i); return; }
      const k = cellText(v)!;
      freq.set(k, (freq.get(k) ?? 0) + 1);
      if (first.has(k)) dup.push(i); else first.set(k, i);
    });
    const groups = [...freq.values()].filter((c) => c > 1).length;
    const rowshare = ratio(dup.length, el);
    const block = { dataset_id: rule.dataset_id, eligible_count: el, null_key_count: nulls.length, distinct_keys: freq.size, duplicate_groups: groups, duplicate_rows: dup.length,
      group_share: { label: "duplicate_group_share", value: p6(ratio(groups, freq.size)) }, row_share: { label: "duplicate_row_share", value: p6(rowshare) } };
    return { rule, eligible: el, failures: nulls.length + dup.length, value: rowshare === null ? null : sub(fr(1), rowshare), block, run_extra: {},
      failing: [...nulls, ...dup].sort((a, b) => a - b).map((i) => ids[i]!) };
  }
  // relationship: null foreign keys are excluded from the denominator and counted separately
  const parent = new Set<string>();
  for (const r of pop.dataset_rows[d["parent_dataset_id"]] ?? []) if (!isMissing(r[d["parent_field"]], trim)) parent.add(cellText(r[d["parent_field"]])!);
  const nullSet = new Set<number>();
  vals.forEach((v, i) => { if (isMissing(v, trim)) nullSet.add(i); });
  const present: number[] = [];
  for (let i = 0; i < el; i++) if (!nullSet.has(i)) present.push(i);
  const matched = present.filter((i) => parent.has(cellText(vals[i])!));
  const mset = new Set(matched);
  const elig = present.length;
  const val = ratio(matched.length, elig);
  const block = { dataset_id: rule.dataset_id, total_fk_count: el, null_fk_count: nullSet.size, eligible_count: elig, matched_count: matched.length, unmatched_count: elig - matched.length, value: p6(val) };
  return { rule, eligible: elig, failures: elig - matched.length, value: val, block, run_extra: { null_fk_count: nullSet.size }, failing: present.filter((i) => !mset.has(i)).map((i) => ids[i]!) };
}
