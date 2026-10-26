// The eleven metric keys of expected.json, laid out as a sheet; every figure is the string the pipeline produced.
import type { ReactNode } from "react";
import type { Metrics } from "../domain/metrics";
import { Def } from "../components/ui";
import { METRIC_KEYS, type MetricKey } from "../domain/contract";

type Fig = [name: string, value: string | number | null, nullNote?: string];
interface Row { key: MetricKey; label: string; def: ReactNode; figs: Fig[] }

export const QUANTITY_LABELS: Record<string, string> = {
  ordered_quantity: "Ordered", net_received_quantity: "Net received", accepted_invoiced_quantity: "Accepted invoiced", open_to_receive_quantity: "Open to receive",
  open_to_invoice_quantity: "Open to invoice", received_not_invoiced_quantity: "Received, not invoiced (qty)", received_not_invoiced_value: "Received, not invoiced (value at PO price)",
  invoiced_not_received_quantity: "Invoiced, not received (qty, blocked)", invoiced_not_received_value: "Invoiced, not received (value at invoice price)",
};

export function sheetRows(m: Metrics): Row[] {
  const q = m.quantities;
  const rows: Record<MetricKey, Row> = {
    matched: { key: "matched", label: "Matched invoices", def: "Invoices that matched or advanced further (approved, exported, adjusted), before and after tax. Matching never confers approval.", figs: [["invoice_count", m.matched.invoice_count], ["amount_before_tax", m.matched.amount_before_tax], ["tax", m.matched.tax], ["total", m.matched.total]] },
    obligations: { key: "obligations", label: "Obligations", def: "An obligation is an approved, exported or adjusted invoice. Nothing is paid and nothing is marked paid.", figs: [["count", m.obligations.count], ["total", m.obligations.total]] },
    exceptions: { key: "exceptions", label: "Open exceptions", def: "One exception per (invoice, reason) of the latest run; open until assigned. Reasons: QUANTITY_BLOCKED, PRICE_VARIANCE, NO_PO_LINE, ROUNDING_EXCEPTION, CURRENCY_MISMATCH.", figs: [["open_count", m.exceptions.open_count], ["unowned_count", m.exceptions.unowned_count], ...Object.entries(m.exceptions.by_reason).map(([k, v]): Fig => [`by_reason.${k}`, v])] },
    duplicates: { key: "duplicates", label: "Duplicates", def: "Groups are counted once. Exact identity (vendor, normalised number, date, computed total) or the same source bytes is merged into the earliest import, not rejected; unresolved groups are 0 after the automatic merge.", figs: [["groups_detected", m.duplicates.groups_detected], ["rows_merged", m.duplicates.rows_merged], ["unresolved_groups", m.duplicates.unresolved_groups]] },
    quantities: { key: "quantities", label: "Open quantities", def: "Quantities at the as-of instant over all purchase-order lines: open to receive, open to invoice, received-not-invoiced valued at PO price, blocked (invoiced-not-received) valued at invoice price.", figs: Object.entries(q).map(([k, v]): Fig => [k, v]) },
    snapshots: { key: "snapshots", label: "Snapshot cutoffs", def: "The quantity figures re-run as of each cutoff (receipts and invoices up to that instant); the table below shows them side by side.", figs: Object.keys(m.snapshots).map((k): Fig => ["cutoff", k]) },
    rates: { key: "rates", label: "Rates", def: "Straight-through = eligible invoices without a manual exception / eligible. Exception rate = flagged / eligible. Eligible = distinct validated invoices (merged and rejected excluded). Null, never 0, when there are none.", figs: [["eligible_invoices", m.rates.eligible_invoices], ["straight_through_rate", m.rates.straight_through_rate, "no value: zero eligible invoices"], ["exception_rate", m.rates.exception_rate, "no value: zero eligible invoices"]] },
    processing: { key: "processing", label: "Processing time", def: "Mean minutes from import to the first valid approval over approved invoices only; invoices not yet approved are counted separately as pending.", figs: [["approved_count", m.processing.approved_count], ["mean_minutes", m.processing.mean_minutes, "no value: no approved invoice"], ["pending_count", m.processing.pending_count]] },
    approvals: { key: "approvals", label: "Approvals", def: "Valid approvals: the actor differs from the creator, the role is allowed by the policy in force at decision time for the total, and the invoice was matched. Invalid decisions are listed by reason.", figs: [["valid_count", m.approvals.valid_count], ["invalid_records", m.approvals.invalid_records.length]] },
    payable: { key: "payable", label: "Approved payable", def: "Approved total less credit notes. A credit applies once and adjusts the payable without any cash movement.", figs: [["approved_total", m.payable.approved_total], ["credit_total", m.payable.credit_total], ["approved_payable", m.payable.approved_payable]] },
    export: { key: "export", label: "Export", def: "Export is an idempotent batch: a repeated request for the same key returns the prior batch. Reconciliation = accepted export total - eligible approved total, with explicit exclusions.", figs: [["requests_received", m.export.requests_received], ["batches_created", m.export.batches_created], ["repeat_requests_returned_prior", m.export.repeat_requests_returned_prior], ["rows", m.export.rows.length], ["exclusions", m.export.exclusions.length], ["accepted_export_total", m.export.accepted_export_total], ["eligible_approved_total", m.export.eligible_approved_total], ["difference", m.export.difference]] },
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
                  {r.figs.map(([name, value, note], i) => (
                    <div key={`${name}-${i}`} data-figure={`${r.key}.${name}`}><dt>{name}</dt><dd>{value === null ? <em>{note ?? "no value"}</em> : String(value)}</dd></div>
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
