// Metrics (metrics.py): exactly the eleven keys of expected.json["metrics"], from a derived book. Integer arithmetic only.
import { derive, type Book, type ExceptionEntry, type ExportRow, type InvalidDecision } from "./book";
import { EXCEPTION_CODES, EXCEPTION_OPEN, METRIC_KEYS, NOT_APPROVED, RULE_VERSION } from "./contract";
import { quantities } from "./match";
import { fmt, fracStr, s2, sumB } from "./num";
import { isoZ } from "./time";
import type { Population } from "./types";

export interface Metrics {
  matched: { invoice_count: number; amount_before_tax: string; tax: string; total: string };
  obligations: { count: number; total: string };
  exceptions: { open_count: number; unowned_count: number; by_reason: Record<string, number>; records: ExceptionEntry[] };
  duplicates: { groups_detected: number; rows_merged: number; unresolved_groups: number };
  quantities: Record<string, string>;
  snapshots: Record<string, Record<string, string>>;
  rates: { eligible_invoices: number; straight_through_rate: string | null; exception_rate: string | null };
  processing: { approved_count: number; mean_minutes: string | null; pending_count: number };
  approvals: { valid_count: number; invalid_records: InvalidDecision[] };
  payable: { approved_total: string; credit_total: string; approved_payable: string };
  export: { requests_received: number; batches_created: number; repeat_requests_returned_prior: number; rows: ExportRow[]; exclusions: { invoice_id: string; reason_code: string }[]; accepted_export_total: string; eligible_approved_total: string; difference: string };
}

export function metricsFromBook(pop: Population, book: Book, cutoffs: readonly number[] = []): Metrics {
  const run = book.run;
  const good = book.inBook.filter((i) => ["matched", "approved", "exported", "adjusted"].includes(book.status.get(i)!));
  const sub = sumB(good.map((i) => run.invoices.get(i)!.subtotal)), tax = sumB(good.map((i) => run.invoices.get(i)!.tax)), tot = sumB(good.map((i) => run.invoices.get(i)!.total));
  const oblig = good.filter((i) => ["approved", "exported", "adjusted"].includes(book.status.get(i)!));
  const obligTotal = sumB(oblig.map((i) => run.invoices.get(i)!.total));
  const byReason: Record<string, number> = Object.fromEntries(EXCEPTION_CODES.map((c) => [c, 0]));
  const records = book.exceptions;
  for (const e of records) byReason[e.exception_type]! += 1;
  const eligible = book.inBook;
  const flagged = eligible.filter((i) => run.invoices.get(i)!.reasons.length > 0).length;
  const n = eligible.length;
  const approved = [...book.approved.keys()].sort();
  const secs = approved.map((i) => BigInt(book.approved.get(i)! - book.invoices.get(i)!.imported_at));
  const mean = secs.length === 0 ? null : fracStr(sumB(secs), 60n * BigInt(secs.length), 4);
  const credits = sumB(book.credits.values());
  const exportTotal = sumB(book.exportRows.map((r) => BigInt(r.amount.replace(".", ""))));
  const snaps: Record<string, Record<string, string>> = {};
  for (const cut of cutoffs) snaps[isoZ(cut)] = quantities((cut === book.cutoff ? book : derive(pop, cut)).run);
  return {
    matched: { invoice_count: good.length, amount_before_tax: s2(sub), tax: s2(tax), total: s2(tot) },
    obligations: { count: oblig.length, total: s2(obligTotal) },
    exceptions: { open_count: records.length, unowned_count: records.filter((e) => e.owner_id === null).length, by_reason: byReason, records },
    duplicates: { groups_detected: new Set(book.mergedRecords.map((r) => r.merged_into)).size, rows_merged: book.mergedRecords.length, unresolved_groups: 0 },
    quantities: quantities(run),
    snapshots: snaps,
    rates: { eligible_invoices: n, straight_through_rate: n === 0 ? null : fracStr(BigInt(n - flagged), BigInt(n), 6), exception_rate: n === 0 ? null : fracStr(BigInt(flagged), BigInt(n), 6) },
    processing: { approved_count: approved.length, mean_minutes: mean, pending_count: eligible.filter((i) => !book.approved.has(i)).length },
    approvals: { valid_count: approved.length, invalid_records: book.invalidDecisions },
    payable: { approved_total: s2(obligTotal), credit_total: s2(credits), approved_payable: s2(obligTotal - credits) },
    export: {
      ...book.exportStats, rows: book.exportRows,
      exclusions: eligible.filter((i) => ["exception", "matched"].includes(book.status.get(i)!)).map((i) => ({ invoice_id: i, reason_code: book.status.get(i) === "exception" ? EXCEPTION_OPEN : NOT_APPROVED })),
      accepted_export_total: s2(exportTotal), eligible_approved_total: s2(obligTotal), difference: s2(exportTotal - obligTotal),
    },
  };
}

export function computeMetrics(pop: Population, asOf: number | null, cutoffs: readonly number[] = []): Metrics {
  const m = metricsFromBook(pop, derive(pop, asOf), cutoffs);
  if (Object.keys(m).join() !== METRIC_KEYS.join()) throw new Error("metric keys differ from the contract");
  return m;
}

/** What must sit beside the numbers (metrics.disclosures). */
export function disclosures(pop: Population, book: Book): Record<string, unknown> {
  const tol = pop.tolerances;
  const tolerated = [...book.run.invoices.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).filter(([, r]) => r.rounding_difference > 0n && r.rounding_difference * 10_000n <= tol.rounding_per_invoice).map(([i, r]) => ({ invoice_id: i, rounding_difference: s2(r.rounding_difference) }));
  const byReason: Record<string, number> = {};
  for (const r of book.mergedRecords) byReason[r.reason_code] = (byReason[r.reason_code] ?? 0) + 1;
  return {
    rule_version: RULE_VERSION, tolerances: tol.raw, rounding_tolerated_invoices: tolerated, merged_by_reason: byReason,
    tax_basis: "tax is computed once per invoice on the unrounded subtotal, ROUND_HALF_UP to 2 dp (D-05)",
    obligation: "an obligation is an approved, exported or adjusted invoice; nothing here is paid and nothing marks an invoice paid",
    matching: "matching never confers approval; only a matched invoice consumes received quantity",
  };
}
export const fmtMoney = (c: bigint): string => fmt(c, 2);
