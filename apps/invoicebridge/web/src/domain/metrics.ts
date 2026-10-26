// Metrics (metrics.py): exactly the eleven keys of expected.json["metrics"], from a derived book. Integer arithmetic only.
import { derive, type Book, type ExceptionEntry, type ExportRow, type InvalidDecision } from "./book";
import { APPROVED_NOT_EXPORTED, EXCEPTION_CODES, EXCEPTION_OPEN, EXPORT_BEFORE_APPROVAL, METRIC_KEYS, NOT_APPROVED, RULE_VERSION } from "./contract";
import { quantities } from "./match";
import { fmt, fracStr, s2, sumB } from "./num";
import { cmp } from "./order";
import { isoZ } from "./time";
import type { Population } from "./types";

/** Per-currency figures (D-09): present only where a metric spans more than one currency; the sums stay, never converted. */
export type ByCurrency<T> = Record<string, T>;
export interface Metrics {
  matched: { invoice_count: number; amount_before_tax: string; tax: string; total: string; by_currency?: ByCurrency<{ invoice_count: number; amount_before_tax: string; tax: string; total: string }> };
  obligations: { count: number; total: string; by_currency?: ByCurrency<{ count: number; total: string }> };
  exceptions: { open_count: number; unowned_count: number; by_reason: Record<string, number>; records: ExceptionEntry[] };
  duplicates: { groups_detected: number; rows_merged: number; unresolved_groups: number };
  quantities: Record<string, string>;
  snapshots: Record<string, Record<string, string>>;
  rates: { eligible_invoices: number; straight_through_rate: string | null; exception_rate: string | null; straight_through_never_excepted_rate?: string; ever_excepted_rate?: string };
  processing: { approved_count: number; mean_minutes: string | null; pending_count: number };
  approvals: { valid_count: number; invalid_records: InvalidDecision[] };
  payable: { approved_total: string; credit_total: string; approved_payable: string; by_currency?: ByCurrency<{ approved_total: string; credit_total: string; approved_payable: string }> };
  export: { requests_received: number; batches_created: number; repeat_requests_returned_prior: number; rows: ExportRow[]; exclusions: { invoice_id: string; reason_code: string }[]; accepted_export_total: string; eligible_approved_total: string; difference: string; by_currency?: ByCurrency<{ accepted_export_total: string; eligible_approved_total: string; difference: string }> };
}

export function metricsFromBook(pop: Population, book: Book, cutoffs: readonly number[] = []): Metrics {
  const run = book.run;
  const cur = (i: string): string => book.invoices.get(i)!.currency;
  const good = book.inBook.filter((i) => ["matched", "approved", "exported", "adjusted"].includes(book.status.get(i)!));
  const sub = sumB(good.map((i) => run.invoices.get(i)!.subtotal)), tax = sumB(good.map((i) => run.invoices.get(i)!.tax)), tot = sumB(good.map((i) => run.invoices.get(i)!.total));
  const oblig = good.filter((i) => ["approved", "exported", "adjusted"].includes(book.status.get(i)!));
  const obligTotal = sumB(oblig.map((i) => run.invoices.get(i)!.total));
  const byReason: Record<string, number> = Object.fromEntries(EXCEPTION_CODES.map((c) => [c, 0]));
  const records = book.exceptions;
  for (const e of records) byReason[e.exception_type]! += 1;
  const eligible = book.inBook;
  const flaggedIds = new Set(eligible.filter((i) => run.invoices.get(i)!.reasons.length > 0));
  const flagged = flaggedIds.size;
  const n = eligible.length;
  const approved = [...book.approved.keys()].sort(cmp);
  const secs = approved.map((i) => BigInt(book.approved.get(i)! - book.invoices.get(i)!.imported_at));
  const mean = secs.length === 0 ? null : fracStr(sumB(secs), 60n * BigInt(secs.length), 4);
  const credits = sumB(book.credits.values());
  const exportTotal = sumB(book.exportRows.map((r) => BigInt(r.amount.replace(".", ""))));
  const snaps: Record<string, Record<string, string>> = {};
  for (const cut of cutoffs) snaps[isoZ(cut)] = quantities((cut === book.cutoff ? book : derive(pop, cut)).run);
  const exclusions: { invoice_id: string; reason_code: string }[] = [];
  for (const i of eligible) {
    if (book.exported.has(i)) continue;
    const st = book.status.get(i)!;
    exclusions.push({ invoice_id: i, reason_code: st === "exception" ? EXCEPTION_OPEN : st === "matched" ? NOT_APPROVED : book.exportLate.has(i) ? EXPORT_BEFORE_APPROVAL : APPROVED_NOT_EXPORTED });
  }
  const rates: Metrics["rates"] = { eligible_invoices: n, straight_through_rate: n === 0 ? null : fracStr(BigInt(n - flagged), BigInt(n), 6), exception_rate: n === 0 ? null : fracStr(BigInt(flagged), BigInt(n), 6) };
  if (pop.exceptions.length > 0 && n > 0) {        // D-09: published only where the stored exception history adds invoices beyond the flagged ones
    const inBook = new Set(eligible);
    const ever = new Set(flaggedIds);
    for (const e of pop.exceptions) if (inBook.has(e.invoice_id)) ever.add(e.invoice_id);
    if (ever.size > flagged) {
      rates.straight_through_never_excepted_rate = fracStr(BigInt(n - ever.size), BigInt(n), 6);
      rates.ever_excepted_rate = fracStr(BigInt(ever.size), BigInt(n), 6);
    }
  }
  const out: Metrics = {
    matched: { invoice_count: good.length, amount_before_tax: s2(sub), tax: s2(tax), total: s2(tot) },
    obligations: { count: oblig.length, total: s2(obligTotal) },
    exceptions: { open_count: records.length, unowned_count: records.filter((e) => e.owner_id === null).length, by_reason: byReason, records },
    duplicates: { groups_detected: new Set(book.mergedRecords.map((r) => r.merged_into)).size, rows_merged: book.mergedRecords.length, unresolved_groups: new Set(book.review.values()).size },
    quantities: quantities(run),
    snapshots: snaps,
    rates,
    processing: { approved_count: approved.length, mean_minutes: mean, pending_count: eligible.filter((i) => !book.approved.has(i)).length },
    approvals: { valid_count: approved.length, invalid_records: book.invalidDecisions },
    payable: { approved_total: s2(obligTotal), credit_total: s2(credits), approved_payable: s2(obligTotal - credits) },
    export: {
      ...book.exportStats, rows: book.exportRows, exclusions,
      accepted_export_total: s2(exportTotal), eligible_approved_total: s2(obligTotal), difference: s2(exportTotal - obligTotal),
    },
  };
  // D-09: a metric that spans more than one currency also carries its figures per currency (the sums stay, never converted)
  const sum = (ids: string[], f: (i: string) => bigint): Map<string, bigint> => { const m = new Map<string, bigint>(); for (const i of ids) m.set(cur(i), (m.get(cur(i)) ?? 0n) + f(i)); return m; };
  const keys = (...ms: Map<string, bigint>[]): string[] => [...new Set(ms.flatMap((m) => [...m.keys()]))].sort(cmp);
  const goodKeys = [...new Set(good.map(cur))].sort(cmp);
  if (goodKeys.length > 1) {
    const sb = sum(good, (i) => run.invoices.get(i)!.subtotal), tx = sum(good, (i) => run.invoices.get(i)!.tax), tt = sum(good, (i) => run.invoices.get(i)!.total);
    out.matched.by_currency = Object.fromEntries(goodKeys.map((k) => [k, { invoice_count: good.filter((i) => cur(i) === k).length, amount_before_tax: s2(sb.get(k) ?? 0n), tax: s2(tx.get(k) ?? 0n), total: s2(tt.get(k) ?? 0n) }]));
  }
  const ob = sum(oblig, (i) => run.invoices.get(i)!.total);
  const cr = sum([...book.credits.keys()], (i) => book.credits.get(i)!);
  const ex = new Map<string, bigint>();
  for (const r of book.exportRows) ex.set(r.currency, (ex.get(r.currency) ?? 0n) + BigInt(r.amount.replace(".", "")));
  const obKeys = keys(ob, cr);
  if (obKeys.length > 1) {
    out.obligations.by_currency = Object.fromEntries(obKeys.map((k) => [k, { count: oblig.filter((i) => cur(i) === k).length, total: s2(ob.get(k) ?? 0n) }]));
    out.payable.by_currency = Object.fromEntries(obKeys.map((k) => [k, { approved_total: s2(ob.get(k) ?? 0n), credit_total: s2(cr.get(k) ?? 0n), approved_payable: s2((ob.get(k) ?? 0n) - (cr.get(k) ?? 0n)) }]));
  }
  const exKeys = keys(ex, ob);
  if (exKeys.length > 1) out.export.by_currency = Object.fromEntries(exKeys.map((k) => [k, { accepted_export_total: s2(ex.get(k) ?? 0n), eligible_approved_total: s2(ob.get(k) ?? 0n), difference: s2((ex.get(k) ?? 0n) - (ob.get(k) ?? 0n)) }]));
  return out;
}

export function computeMetrics(pop: Population, asOf: number | null, cutoffs: readonly number[] = []): Metrics {
  const m = metricsFromBook(pop, derive(pop, asOf), cutoffs);
  if (Object.keys(m).join() !== METRIC_KEYS.join()) throw new Error("metric keys differ from the contract");
  return m;
}

/** What must sit beside the numbers (metrics.disclosures). */
export function disclosures(pop: Population, book: Book): Record<string, unknown> {
  const tol = pop.tolerances;
  const sorted = [...book.run.invoices.entries()].sort(([a], [b]) => cmp(a, b));
  const tolerated = sorted.filter(([, r]) => r.rounding_difference > 0n && r.rounding_difference * 10_000n <= tol.rounding_per_invoice).map(([i, r]) => ({ invoice_id: i, rounding_difference: s2(r.rounding_difference) }));
  const lineTolerated = sorted.flatMap(([i, r]) => r.line_rounding.filter(([, d]) => d > 0n && d * 10_000n <= tol.rounding_per_line).map(([lid, d]) => ({ invoice_id: i, invoice_line_id: lid, rounding_difference: s2(d) })));
  const byReason: Record<string, number> = {};
  for (const r of book.mergedRecords) byReason[r.reason_code] = (byReason[r.reason_code] ?? 0) + 1;
  return {
    rule_version: RULE_VERSION, tolerances: tol.raw, rounding_tolerated_invoices: tolerated, rounding_tolerated_lines: lineTolerated, merged_by_reason: byReason,
    tax_basis: "tax is computed once per invoice on the unrounded subtotal, ROUND_HALF_UP to 2 dp (D-05)",
    obligation: "an obligation is an approved, exported or adjusted invoice; nothing here is paid and nothing marks an invoice paid",
    matching: "matching never confers approval; only a matched invoice consumes received quantity",
  };
}
export const fmtMoney = (c: bigint): string => fmt(c, 2);
