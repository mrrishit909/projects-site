// The verification layer: the ONLY reader of the synthetic truth (D-04, P07-DOMAIN-03). `truth` is the manifest's
// synthetic_truth.true_entity map (record id -> entity id). The matcher, the pipeline's matching block and every view other than the
// labelled verification figures never read it. Match precision = approved merge decisions whose pair the truth shows to be ONE entity /
// approved merge decisions (a reversal does not remove the approval from the ratio); `reviewed_correct_share` (same entity / all reviewed
// pairs) is reported beside it and labelled so nobody reads it as precision. If the truth does not name a record of a decided pair,
// nothing is confirmable and the correct counts and shares are null (unknown), never 0.
import type { Pair } from "./matching";
import type { Row } from "./models";
import { p6, ratio } from "./num";

export type Truth = Readonly<Record<string, string>>;

export function precisionBlock(truth: Truth | null | undefined, approved: readonly Pair[], reviewed: readonly Pair[]): Row {
  const tm = truth ?? {};
  const decided = new Set<string>();
  for (const p of [...reviewed, ...approved]) { decided.add(p[0]); decided.add(p[1]); }
  const known = [...decided].every((r) => Object.prototype.hasOwnProperty.call(tm, r));
  const same = (p: Pair): boolean => tm[p[0]] === tm[p[1]];
  const aOk = known ? approved.filter(same).length : null;
  const rOk = known ? reviewed.filter(same).length : null;
  return {
    approved_decisions: approved.length, approved_correct: aOk, precision: known ? p6(ratio(aOk!, approved.length)) : null,
    reviewed: reviewed.length, reviewed_correct: rOk, reviewed_correct_share: known ? p6(ratio(rOk!, reviewed.length)) : null,
  };
}

/** `synthetic_truth.true_entity` from a block (null when there is none). */
export function truthMap(block: unknown): Truth | null {
  if (!block || typeof block !== "object") return null;
  const te = (block as Row)["true_entity"];
  return te && typeof te === "object" && !Array.isArray(te) ? (te as Truth) : null;
}
