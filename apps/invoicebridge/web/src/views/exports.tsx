import { useMemo } from "react";
import { s2 } from "../domain/num";
import type { PipelineResult } from "../domain/pipeline";
import type { Row } from "../domain/types";
import { ViewHead } from "../components/layout";
import { Chip, Def, InvoiceLink, NotBuilt, Scroll, usePager, WithData } from "../components/ui";
import { short, stamp } from "../lib/format";
import { useParam } from "../router";

function Exports({ result, stored }: { result: PipelineResult; stored: Row[] }) {
  const [batch, setBatch] = useParam("batch", "all");
  const e = result.metrics.export;
  const batches = useMemo(() => {
    const m = new Map<string, { id: string; at: string; rows: number; total: bigint }>();
    for (const r of e.rows) {
      const g = m.get(r.batch_id) ?? m.set(r.batch_id, { id: r.batch_id, at: r.exported_at, rows: 0, total: 0n }).get(r.batch_id)!;
      g.rows++; g.total += BigInt(r.amount.replace(".", ""));
    }
    return [...m.values()].sort((x, y) => (x.id < y.id ? -1 : 1));
  }, [e.rows]);
  const storedBy = new Map(stored.map((s) => [s.batch_id as string, s]));
  const rows = e.rows.filter((r) => batch === "all" || r.batch_id === batch);
  const bp = usePager(batches, 12), rp = usePager(rows, 15);
  const excl = (c: string): number => e.exclusions.filter((x) => x.reason_code === c).length;
  return (
    <>
      <dl className="glance" data-testid="export-summary">
        <div data-figure="export.requests_received"><dt>Requests received</dt><dd>{e.requests_received}</dd></div>
        <div data-figure="export.batches_created"><dt>Batches created</dt><dd>{e.batches_created}</dd></div>
        <div data-figure="export.repeat_requests_returned_prior"><dt>Repeats returned prior</dt><dd>{e.repeat_requests_returned_prior}<small>same key, same batch</small></dd></div>
        <div data-figure="export.rows"><dt>Export rows</dt><dd>{e.rows.length.toLocaleString("en-US")}</dd></div>
      </dl>
      <section className="panel" aria-labelledby="rec-h">
        <h2 id="rec-h">Export reconciliation <Def term="the check">Accepted export total minus the eligible approved total must be 0.00, with every excluded invoice named. Eligible approved means approved, exported or adjusted at the as-of instant.</Def></h2>
        <dl className="sums" data-testid="export-recon">
          <div data-figure="export.accepted_export_total"><dt>Accepted export total</dt><dd>{e.accepted_export_total}</dd></div>
          <div data-figure="export.eligible_approved_total"><dt>Eligible approved total</dt><dd>{e.eligible_approved_total}</dd></div>
          <div className="sums__total" data-figure="export.difference"><dt>Difference</dt><dd>{e.difference}</dd></div>
        </dl>
        <p data-testid="exclusions">Excluded from the export: {e.exclusions.length.toLocaleString("en-US")} invoices, {excl("EXCEPTION_OPEN").toLocaleString("en-US")} <Chip v="EXCEPTION_OPEN" /> and {excl("NOT_APPROVED").toLocaleString("en-US")} <Chip v="NOT_APPROVED" /> (matched, waiting for a reviewer). Amounts are summed across currencies as recorded; the grouping by currency is a backend option this site does not draw.</p>
      </section>
      <section className="panel" aria-labelledby="b-h">
        <h2 id="b-h">Batches</h2>
        <Scroll label="Batches">
          <table className="grid" data-testid="batch-table">
            <caption className="sr">Export batches</caption>
            <thead><tr><th scope="col">Batch</th><th scope="col">Exported</th><th scope="col">Requested by</th><th scope="col" className="num">Rows</th><th scope="col" className="num">Total</th><th scope="col">Stored record agrees</th><th scope="col">Rows</th></tr></thead>
            <tbody>{bp.page.map((x) => { const s = storedBy.get(x.id); return (
              <tr key={x.id}><td className="mono">{x.id}</td><td className="mono">{stamp(x.at)}</td><td className="mono">{(s?.requested_by as string | undefined) ?? "n/a"}</td><td className="num">{x.rows}</td><td className="num">{s2(x.total)}</td>
                <td>{s ? (s.row_count === x.rows && s.total === s2(x.total) ? "yes" : "NO") : "no stored batch"}</td><td><button type="button" className="linkish" onClick={() => setBatch(x.id)}>Show rows</button></td></tr>); })}</tbody>
          </table>
        </Scroll>
        {bp.ui}
      </section>
      <section className="panel" aria-labelledby="r-h">
        <h2 id="r-h">Export rows {batch !== "all" && <>for {batch} <button type="button" className="linkish" onClick={() => setBatch("all")}>show all</button></>}</h2>
        <Scroll label="Export rows">
          <table className="grid" data-testid="export-rows">
            <caption className="sr">Export rows with content hash</caption>
            <thead><tr><th scope="col">Export</th><th scope="col">Invoice</th><th scope="col">Vendor</th><th scope="col">Number</th><th scope="col">Date</th><th scope="col" className="num">Amount</th><th scope="col">content_hash (sha256)</th></tr></thead>
            <tbody>{rp.page.map((r) => <tr key={r.export_id}><td className="mono">{r.export_id}</td><td><InvoiceLink id={r.invoice_id} /></td><td className="mono">{r.vendor_id}</td><td className="mono">{r.invoice_number}</td><td className="mono">{r.invoice_date}</td><td className="num">{r.amount} {r.currency}</td><td className="mono" title={r.content_hash}>{short(r.content_hash, 20)}</td></tr>)}</tbody>
          </table>
        </Scroll>
        {rp.ui}
      </section>
      <NotBuilt>Requesting a batch, the file format of an ERP hand-off and any delivery are not built: nothing is exported from the site. The rows are what the recorded export requests imply, with the hash recomputed in your browser.</NotBuilt>
    </>
  );
}
export function ExportsView() {
  return (
    <>
      <ViewHead eyebrow="Read-only view" title="Export review">
        <p className="lede">Approved invoices handed to the next system in idempotent batches: a repeated request returns the prior batch, and the total must reconcile to what was approved, with every exclusion named.</p>
      </ViewHead>
      <WithData>{({ result, snapshot }) => <Exports result={result} stored={snapshot.batches} />}</WithData>
    </>
  );
}
