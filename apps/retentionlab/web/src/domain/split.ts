// Chronological split with the label-window purge and the group purge (D-02, D-P10-09).
import type { Row } from "./models";
import { daysUs, parseTs, type Ts } from "./time";
import type { World } from "./world";

export const PARTS = ["train", "validation", "test", "outside"] as const;
export const LABEL_WINDOW = "LABEL_WINDOW", GROUP_TEST = "GROUP_TEST", GROUP_VALIDATION = "GROUP_VALIDATION";
export interface SplitRow { cutoff_id: string; account_id: unknown; split: (typeof PARTS)[number]; label_end: Ts; status: "retained" | "dropped"; drop_reason: string | null }
export interface SplitCounts { total: number; retained: number; label_window: number; group_test: number; group_validation: number }

/** Assign every cutoff row of the world to train / validation / test / outside by `prediction_at`, then purge.
 * Label purge first: a row whose label window [prediction_at, label_end) crosses the boundary of its own range (label_end > boundary; equal does
 * not cross) is dropped from the earlier side. Then the group purge, counting membership BY RANGE (a row dropped in step one still counts for its
 * account): an account with a test row loses its earlier train and validation rows (GROUP_TEST); an account with a validation row loses its train
 * rows (GROUP_VALIDATION). Test rows are never purged: maturity, not purging, governs their use. */
export function splitRun(world: World, run: Row): [SplitRow[], Record<string, SplitCounts>] {
  const trainEnd = parseTs(run["train_end"]), validationEnd = parseTs(run["validation_end"]), testEnd = parseTs(run["test_end"]);
  const rows: SplitRow[] = world.acc.prediction_cutoffs.map((c) => {
    const pa = parseTs(c["prediction_at"]);
    const labelEnd = parseTs(c["horizon_end"]) + daysUs(world.grace);
    const part = pa < trainEnd ? "train" : pa < validationEnd ? "validation" : pa < testEnd ? "test" : "outside";
    return { cutoff_id: c["cutoff_id"], account_id: c["account_id"], split: part, label_end: labelEnd, status: "retained", drop_reason: null };
  });
  const testAccounts = new Set(rows.filter((r) => r.split === "test").map((r) => r.account_id));
  const validationAccounts = new Set(rows.filter((r) => r.split === "validation").map((r) => r.account_id));
  for (const r of rows) {
    if ((r.split === "train" && r.label_end > trainEnd) || (r.split === "validation" && r.label_end > validationEnd)) { r.status = "dropped"; r.drop_reason = LABEL_WINDOW; }
  }
  for (const r of rows) {
    if (r.status === "retained" && (r.split === "train" || r.split === "validation")) {
      if (testAccounts.has(r.account_id)) { r.status = "dropped"; r.drop_reason = GROUP_TEST; }
      else if (r.split === "train" && validationAccounts.has(r.account_id)) { r.status = "dropped"; r.drop_reason = GROUP_VALIDATION; }
    }
  }
  const counts: Record<string, SplitCounts> = {};
  for (const part of PARTS) {
    const pr = rows.filter((r) => r.split === part);
    counts[part] = { total: pr.length, retained: pr.filter((r) => r.status === "retained").length, label_window: pr.filter((r) => r.drop_reason === LABEL_WINDOW).length,
      group_test: pr.filter((r) => r.drop_reason === GROUP_TEST).length, group_validation: pr.filter((r) => r.drop_reason === GROUP_VALIDATION).length };
  }
  return [rows, counts];
}
export const retained = (rows: SplitRow[], part: string): Set<string> => new Set(rows.filter((r) => r.split === part && r.status === "retained").map((r) => r.cutoff_id));
