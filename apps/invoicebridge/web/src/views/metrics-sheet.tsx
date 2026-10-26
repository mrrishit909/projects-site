// The eleven metric keys of expected.json, laid out as a sheet; every figure is the string the pipeline produced.
import type { ReactNode } from "react";
import type { Metrics } from "../domain/metrics";
import { Def } from "../components/ui";
import { METRIC_KEYS, type MetricKey } from "../domain/contract";

type Fig = [name: string, value: string | number | null, nullNote?: string | undefined, label?: string | undefined];
const SUM = " (sum across currencies, not converted)";
const per = <T extends Record<string, string | number>>(prefix: string, by: Record<string, T> | undefined): Fig[] =>
  Object.entries(by ?? {}).flatMap(([c, v]) => Object.entries(v).map(([k, x]): Fig => [`by_currency.${c}.${k}`, x as string | number, undefined, `${prefix}${c} ${k}`]));
interface Row { key: MetricKey; label: string; def: ReactNode; figs: Fig[] }

export const QUANTITY_LABELS: Record<string, string> = {
  ordered_quantity: "Ordered", net_received_quantity: "Net received", accepted_invoiced_quantity: "Accepted invoiced", open_to_receive_quantity: "Open to receive",
  open_to_invoice_quantity: "Open to invoice", received_not_invoiced_quantity: "Received, not invoiced (qty)", received_not_invoiced_value: "Received, not invoiced (value at PO price)",
  invoiced_not_received_quantity: "Invoiced, not received (qty, blocked)", invoiced_not_received_value: "Invoiced, not received (value at invoice price)",
};

export function sheetRows(m: Metrics): Row[] {
  const q = m.quantities;
  const rows: Record<MetricKey, Row> = {
    matched: { key: "matched", label: "Matched invoices", def: "Invoices that matched or advanced further (approved, exported, adjusted), before and after tax. Matching never confers approval.", figs: [["invoice_count", m.matched.invoice_count], ["amount_before_tax", m.matched.amount_before_tax, undefined, m.matched.by_currency ? `amount_before_tax${SUM}` : undefined], ["tax", m.matched.tax, undefined, m.matched.by_currency ? `tax${SUM}` : undefined], ["total", m.matched.total, undefined, m.matched.by_currency ? `total${SUM}` : undefined], ...per("", m.matched.by_currency)] },
    obligations: { key: "obligations", label: "Obligations", def: "An obligation is an approved, exported or adjusted invoice. Nothing is paid and nothing is marked paid.", figs: [["count", m.obligations.count], ["total", m.obligations.total, undefined, m.obligations.by_currency ? `total${SUM}` : undefined], ...per("", m.obligations.by_currency)] },
    exceptions: { key: "exceptions", label: "Open exceptions", def: "One exception per (invoice, reason) of the latest run; open until assigned. Reasons: QUANTITY_BLOCKED, PRICE_VARIANCE, NO_PO_LINE, ROUNDING_EXCEPTION, CURRENCY_MISMATCH.", figs: [["open_count", m.exceptions.open_count], ["unowned_count", m.exceptions.unowned_count], ...Object.entries(m.exceptions.by_reason).map(([k, v]): Fig => [`by_reason.${k}`, v])] },
    duplicates: { key: "duplicates", label: "Duplicates", def: "Groups are counted once. Exact identity (vendor, normalised number, date, computed total) or the same source bytes with the same identity is merged into the canonical copy (a committed copy first, else the earliest import), not rejected. Unresolved groups are byte-twins whose extracted fields differ: they are held for review (needs_review) and merged into nothing.", figs: [["groups_detected", m.duplicates.groups_detected], ["rows_merged", m.duplicates.rows_merged], ["unresolved_groups", m.duplicates.unresolved_groups]] },
    quantities: { key: "quantities", label: "Open quantities", def: "Quantities at the as-of instant over all purchase-order lines: open to receive, open to invoice, received-not-invoiced valued at PO price, blocked (invoiced-not-received) valued at invoice price.", figs: Object.entries(q).map(([k, v]): Fig => [k, v]) },
    snapshots: { key: "snapshots", label: "Snapshot cutoffs", def: "The quantity figures re-run as of each cutoff (receipts and invoices up to that instant); the table below shows them side by side.", figs: Object.keys(m.snapshots).map((k): Fig => ["cutoff", k]) },
    rates: { key: "rates", label: "Rates", def: "straight_through_rate = eligible invoices that are NOT blocked at the cutoff (no exception in the latest run) / eligible; it is the complement of the exception rate, not the share that never had an exception. Eligible = distinct validated invoices still in the book (merged, held-for-review and rejected invoices have left it). Where a stored exception history adds invoices beyond the open ones, straight_through_never_excepted_rate and ever_excepted_rate are shown too. Null, never 0, when there are none.", figs: [["eligible_invoices", m.rates.eligible_invoices], ["straight_through_rate", m.rates.straight_through_rate, "no value: zero eligible invoices", "straight_through_rate (not blocked at the cutoff)"], ["exception_rate", m.rates.exception_rate, "no value: zero eligible invoices"], ...(m.rates.ever_excepted_rate === undefined ? [] : [["straight_through_never_excepted_rate", m.rates.straight_through_never_excepted_rate!] as Fig, ["ever_excepted_rate", m.rates.ever_excepted_rate] as Fig])] },
    processing: { key: "processing", label: "Processing time", def: "Mean minutes from import to the first valid approval over approved invoices only; invoices not yet approved are counted separately as pending.", figs: [["approved_count", m.processing.approved_count], ["mean_minutes", m.processing.mean_minutes, "no value: no approved invoice"], ["pending_count", m.processing.pending_count]] },
    approvals: { key: "approvals", label: "Approvals", def: "Valid approvals: the actor differs from the creator, the role is allowed by the policy in force at decision time for the total, the decision is not before the import (BEFORE_IMPORT), and the invoice was matched (an invoice with a valid export row stays approved). A rejection follows the same separation of duties (SELF_DECISION) and is blocked only by an earlier VALID approval. Invalid decisions are listed by reason.", figs: [["valid_count", m.approvals.valid_count], ["invalid_records", m.approvals.invalid_records.length]] },
    payable: { key: "payable", label: "Approved payable", def: "Approved total less credit notes. A credit applies once and adjusts the payable without any cash movement.", figs: [["approved_total", m.payable.approved_total, undefined, m.payable.by_currency ? `approved_total${SUM}` : undefined], ["credit_total", m.payable.credit_total, undefined, m.payable.by_currency ? `credit_total${SUM}` : undefined], ["approved_payable", m.payable.approved_payable, undefined, m.payable.by_currency ? `approved_payable${SUM}` : undefined], ...per("", m.payable.by_currency)] },
    export: { key: "export", label: "Export", def: "Export is an idempotent batch: a repeated request for the same key returns the prior batch. Reconciliation = accepted export total - eligible approved total; an export row needs a valid approval at or before it, and every approved invoice not exported is an explicit exclusion (APPROVED_NOT_EXPORTED, EXPORT_BEFORE_APPROVAL), so the difference is always explained. It is 0.00 on the snapshot because the generator closes the period with one batch of everything approved.", figs: [["requests_received", m.export.requests_received], ["batches_created", m.export.batches_created], ["repeat_requests_returned_prior", m.export.repeat_requests_returned_prior], ["rows", m.export.rows.length], ["exclusions", m.export.exclusions.length], ["accepted_export_total", m.export.accepted_export_total, undefined, m.export.by_currency ? `accepted_export_total${SUM}` : undefined], ["eligible_approved_total", m.export.eligible_approved_total, undefined, m.export.by_currency ? `eligible_approved_total${SUM}` : undefined], ["difference", m.export.difference, undefined, m.export.by_currency ? `difference${SUM}` : undefined], ...per("", m.export.by_currency)] },
  };
  return METRIC_KEYS.map((k) => rows[k]);
}

export function MetricSheet({ m }: { m: Metrics }) {
  return (
    <div className="scroll" role="region" aria-label="Metric sheet" tabIndex={0}>
      <table className="grid sheet" data-testid="metric-sheet">
        <caption className="sr">The eleven metric keys</caption>
        <thead><tr><th scope="col">Metric key</th><th scope="col">Figures</th></tr></thead>
        <tbody>
          {sheetRows(m).map((r) => (
            <tr key={r.key} data-metric={r.key}>
              <th scope="row"><span className="mono">{r.key}</span><br /><span className="small">{r.label}</span><Def term="definition">{r.def}</Def></th>
              <td>
                <dl className="figs">
                  {r.figs.map(([name, value, note, label], i) => (
                    <div key={`${name}-${i}`} data-figure={`${r.key}.${name}`}><dt>{label ?? name}</dt><dd>{value === null ? <em>{note ?? "no value"}</em> : String(value)}</dd></div>
                  ))}
                </dl>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CutoffTable({ m, asOf }: { m: Metrics; asOf: string }) {
  const cuts = Object.keys(m.snapshots);
  return (
    <div className="scroll" role="region" aria-label="Snapshot cutoffs" tabIndex={0}>
      <table className="grid" data-testid="cutoffs">
        <caption>Open quantities as of each snapshot cutoff, and now ({asOf})</caption>
        <thead><tr><th scope="col">Figure</th>{cuts.map((c) => <th key={c} scope="col" className="num" data-cutoff={c}>{c}</th>)}<th scope="col" className="num">as_of (headline)</th></tr></thead>
        <tbody>{Object.keys(m.quantities).map((k) => (
          <tr key={k} data-quantity={k}><th scope="row">{QUANTITY_LABELS[k] ?? k}</th>{cuts.map((c) => <td key={c} className="num">{m.snapshots[c]![k]}</td>)}<td className="num">{m.quantities[k]}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}
