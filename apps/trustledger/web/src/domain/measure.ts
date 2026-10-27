// Measuring one rule over a dataset's rows (D-01, D-06): eligible and failing counts, the dimension score, the failing records.
// Dimensions are measured on their own denominators and reported separately:
//   completeness  non-missing / eligible (missing = null or, after trimming, empty)
//   validity      all-eligible (passing / eligible) and populated-only (passing / populated), both labelled; the score uses populated-only
//   uniqueness    duplicate-group share (groups / distinct keys) and duplicate-row share (rows beyond the first / eligible); null keys are listed apart;
//                 score (eligible - null-key rows - duplicate rows) / eligible (D-10 R7-05)
//   relationship  matched / non-missing foreign keys; null, empty and whitespace-only keys (the whitespace policy) are counted separately, never in the
//                 denominator (D-10 R7-11)
//   timeliness    a refresh inside [latest occurrence <= as_of, its deadline) of the dataset's local daily schedule; an open occurrence with no refresh
//                 yet is pending, outside the denominator (D-10 R7-01)
// A cell is compared as exact text: text as is, true/false, integers in decimal. Nothing here reads a stored result.
import { stripChars } from "./ingest";
import { compilePattern, type Dataset, type Population, type Row, type Rule } from "./models";
import { fr, p6, ratio, type Fr } from "./num";
import { isoZ, timelinessState, type Instant } from "./time";

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

/** The state of a monitored dataset at asOf: on_time, late or pending (D-10 R7-01), with the occurrence it was judged on. `on_time` is null while pending. */
export function timelinessOf(ds: Dataset, asOf: Instant): Row | null {
  if (!ds.monitored) return null;
  const last = ds.last_refreshed_at !== null && ds.last_refreshed_at <= asOf ? ds.last_refreshed_at : null; // a later refresh has not happened yet
  const { state, start, deadline } = timelinessState(ds.refresh_timezone!, ds.refresh_local_time!, ds.refresh_grace_minutes!, last, asOf);
  return { timezone: ds.refresh_timezone, scheduled_local: ds.refresh_local_time, grace_minutes: ds.refresh_grace_minutes, evaluated_occurrence_utc: isoZ(start), deadline_utc: isoZ(deadline),
    last_refreshed_at: isoZ(last), state, on_time: state === "pending" ? null : state === "on_time" };
}

export function measureRule(rule: Rule, pop: Population, asOf: Instant): Measure {
  const ds = pop.datasets.find((d) => d.dataset_id === rule.dataset_id)!;
  const t = rule.rule_type, d = rule.definition, trim = pop.trim;
  const allRows = pop.dataset_rows[rule.dataset_id] ?? [];
  const rows = eligibleRows(rule, allRows);
  if (t === "timeliness") {
    const tl = timelinessOf(ds, asOf);
    if (!tl) return { rule, eligible: 0, failures: 0, value: null, block: {}, run_extra: {}, failing: [] };
    if (tl["state"] === "pending") return { rule, eligible: 0, failures: 0, value: null, block: tl, run_extra: {}, failing: [] }; // an open occurrence with no refresh yet is not measured
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
    const score = ratio(el - nulls.length - dup.length, el); // null-key rows fail too (D-10 R7-05)
    const block = { dataset_id: rule.dataset_id, eligible_count: el, null_key_count: nulls.length, null_key_row_ids: nulls.map((i) => ids[i]!), distinct_keys: freq.size, duplicate_groups: groups, duplicate_rows: dup.length,
      group_share: { label: "duplicate_group_share", value: p6(ratio(groups, freq.size)) }, row_share: { label: "duplicate_row_share", value: p6(rowshare) } };
    return { rule, eligible: el, failures: nulls.length + dup.length, value: score, block, run_extra: {},
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
  const emptyText = [...nullSet].filter((i) => typeof vals[i] === "string").length; // text that is empty after trimming: missing like a null (D-10 R7-11)
  const block = { dataset_id: rule.dataset_id, total_fk_count: el, null_fk_count: nullSet.size, empty_fk_count: emptyText, eligible_count: elig, matched_count: matched.length, unmatched_count: elig - matched.length, value: p6(val) };
  return { rule, eligible: elig, failures: elig - matched.length, value: val, block, run_extra: { null_fk_count: nullSet.size }, failing: present.filter((i) => !mset.has(i)).map((i) => ids[i]!) };
}
