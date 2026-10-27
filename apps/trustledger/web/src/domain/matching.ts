// Identity matching (D-04, D-06): candidates in canonical order, human merge decisions, reversible merges.
// This module never sees the synthetic truth. A merge maps the RIGHT record to the LEFT one; a reversal restores both identities and
// keeps the mapping history. Precision is computed from the truth by verification.ts and nowhere else.
import type { Population, Row } from "./models";
import { cmp } from "./models";

export type Pair = readonly [string, string];

export function matchingBlock(pop: Population): { block: Row; approved: Pair[]; reviewed: Pair[] } {
  const cand = new Map(pop.match_candidates.map((c) => [c.candidate_id, c]));
  const decisions = pop.merge_decisions.filter((m) => cand.has(m.candidate_id));
  const appr = new Map(decisions.filter((m) => m.decision === "approve").map((m) => [m.merge_id, m]));
  const rejected = new Set(decisions.filter((m) => m.decision === "reject").map((m) => m.candidate_id));
  const reversedBy = new Map<string, string>();
  for (const m of decisions) if (m.decision === "reverse" && m.reverses_merge_id !== null && appr.has(m.reverses_merge_id)) reversedBy.set(m.reverses_merge_id, m.merge_id);
  const apprC = new Set([...appr.values()].map((m) => m.candidate_id));
  const reviewed = new Set([...apprC, ...rejected]);
  const imap = new Map(pop.customer_records.map((r) => [r.record_id, r.record_id]));
  const hist: Row[] = [];
  for (const mid of [...appr.keys()].sort(cmp)) {
    const c = cand.get(appr.get(mid)!.candidate_id)!;
    const state = reversedBy.has(mid) ? "reversed" : "active";
    if (state === "active") imap.set(c.right_record_id, c.left_record_id);
    hist.push({ merge_id: mid, candidate_id: c.candidate_id, from_record_id: c.right_record_id, to_record_id: c.left_record_id, state, reversed_by: reversedBy.get(mid) ?? null });
  }
  const identity: Row = {};
  for (const k of [...imap.keys()].sort(cmp)) identity[k] = imap.get(k)!;
  const block = {
    candidates: cand.size, reviewed: reviewed.size, approved: apprC.size, rejected: rejected.size, unreviewed: cand.size - reviewed.size,
    merges_reversed: reversedBy.size, active_merges: appr.size - reversedBy.size, identity_map: identity, mapping_history: hist,
  };
  const pair = (cid: string): Pair => [cand.get(cid)!.left_record_id, cand.get(cid)!.right_record_id];
  return { block, approved: [...apprC].sort(cmp).map(pair), reviewed: [...reviewed].sort(cmp).map(pair) };
}
