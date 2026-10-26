// The invoice desk: EVIDENCE beside DECISION. Left: the document as structured fields, its lines, the source hash and lineage.
// Right: the derived match, exceptions with assignment history, the approval trail, the export row and credits.
import type { ReactNode } from "react";
import type { PipelineResult } from "../domain/pipeline";
import type { ExceptionView, InvoiceView } from "../domain/view";
import { Chip, Def, InvoiceLink, Scroll } from "../components/ui";
import { stamp } from "../lib/format";

const F = ({ k, children, wide }: { k: string; children: ReactNode; wide?: boolean }) => <div className={wide ? "wide" : undefined}><dt>{k}</dt><dd>{children}</dd></div>;

export function ExceptionBlock({ e, resolved }: { e: ExceptionView; resolved?: boolean }) {
  return (
    <li className="exc" data-testid="exception-item" data-exception={e.exception_id}>
      <p className="exc__head"><Chip v={e.exception_type} /> <span className="mono">{e.exception_id}</span> <Chip v={resolved ? "resolved" : e.status}>{resolved ? "resolved" : e.status === "open" ? "open, unowned" : `assigned to ${e.owner_id}`}</Chip></p>
      {(e.created_at || e.resolved_at) && <p className="muted small">Stored record: opened {e.created_at ? stamp(e.created_at) : "unknown"}{e.resolved_at ? `, resolved ${stamp(e.resolved_at)}` : ", not resolved"}.</p>}
      {e.assignments.length === 0 ? <p className="muted small">No assignment recorded: the exception has no owner yet.</p> : (
        <Scroll label={`Assignment history of ${e.exception_id}`}>
          <table className="grid grid--tight" data-testid="assignment-history">
            <caption className="sr">Assignment history of {e.exception_id}</caption>
            <thead><tr><th scope="col">Assigned at</th><th scope="col">Owner</th><th scope="col">By</th><th scope="col">Note</th></tr></thead>
            <tbody>{e.assignments.map((a, i) => <tr key={i}><td className="mono">{stamp(a.assigned_at)}</td><td className="mono">{a.owner_id}</td><td className="mono">{a.assigned_by ?? "n/a"}</td><td>{a.note ?? ""}</td></tr>)}</tbody>
          </table>
        </Scroll>
      )}
    </li>
  );
}

function headline(v: InvoiceView): string {
  if (v.status === "merged") return `Merged into ${v.merged_into} (${v.merge_reason}). It is the same obligation, so it is not matched again and consumes no received quantity.`;
  if (v.status === "rejected") return "Rejected by a valid reviewer decision; it is out of the book and consumes nothing.";
  if (!v.in_book) return "Not in the book (invalid or not yet validated): no match was run.";
  const bad = v.lines.filter((l) => l.reason_code);
  if (v.exceptions.length === 0) return `Matched: ${v.subtotal} before tax, ${v.tax} tax, total ${v.total}${v.status === "matched" ? ". Matching never confers approval; no valid approval is on file." : "."}`;
  return `Exception: ${v.exceptions.map((e) => e.exception_type).join(", ")}${bad[0]?.quantity_variance && bad[0].reason_code === "QUANTITY_BLOCKED" ? `. ${bad[0].this_invoice} invoiced against ${bad[0].available} available (${bad[0].quantity_variance} over)` : ""}. It consumes nothing and is not an obligation.`;
}

export function InvoiceDesk({ v, result }: { v: InvoiceView; result: PipelineResult }) {
  const tol = result.population.tolerances.raw;
  return (
    <article className="pair" data-testid={`desk-${v.invoice_id}`} data-invoice={v.invoice_id} aria-label={`Invoice ${v.invoice_number}`}>
      <header className="pair__head">
        <h2><span className="mono">{v.invoice_id}</span> · {v.invoice_number}</h2>
        <p><Chip v={v.status} /> <span className="muted">{v.vendor_id} · {v.vendor_name} · {v.currency}</span></p>
      </header>
      <p className="verdict" data-testid="verdict">{headline(v)}</p>
      <div className="pair__grid">
        <section className="doc" aria-label="Evidence: the invoice document">
          <h3><span className="tag">Evidence</span> the document</h3>
          <dl className="fields" data-testid="doc-fields">
            <F k="invoice_id">{v.invoice_id}</F><F k="vendor">{v.vendor_id}</F>
            <F k="invoice_number">{v.invoice_number}</F><F k="invoice_date">{v.invoice_date}</F>
            <F k="currency">{v.currency}</F><F k="created_by">{v.created_by}</F>
            <F k="imported_at">{stamp(v.imported_at)}</F><F k="tax_rate">{v.tax_rate}</F>
          </dl>
          <Scroll label="Document lines">
            <table className="grid" data-testid="doc-lines">
              <caption className="sr">Lines of {v.invoice_id}</caption>
              <thead><tr><th scope="col">Line</th><th scope="col">PO line</th><th scope="col">Product</th><th scope="col" className="num">Quantity</th><th scope="col" className="num">Unit price</th><th scope="col" className="num">Extended</th></tr></thead>
              <tbody>{v.lines.map((l) => <tr key={l.invoice_line_id}><td className="mono">{l.invoice_line_id}</td><td className="mono">{l.po_line_id}</td><td className="mono">{l.product_code}</td><td className="num">{l.quantity}</td><td className="num">{l.unit_price}</td><td className="num">{l.extended}</td></tr>)}</tbody>
            </table>
          </Scroll>
          <dl className="sums" data-testid="doc-sums">
            <div><dt>Subtotal</dt><dd data-figure="subtotal">{v.subtotal}</dd></div>
            <div><dt>Tax <Def term="how tax is rounded">Tax is computed once per invoice on the unrounded subtotal and rounded half up to 2 decimals (D-05). The total is subtotal + tax + freight - discount, in that order.</Def></dt><dd data-figure="tax">{v.tax}</dd></div>
            <div><dt>Freight</dt><dd data-figure="freight">{v.freight}</dd></div>
            <div><dt>Discount</dt><dd data-figure="invoice_discount">{v.invoice_discount}</dd></div>
            <div className="sums__total"><dt>Total (computed)</dt><dd data-figure="total">{v.total}</dd></div>
            <div><dt>Declared on the document</dt><dd data-figure="declared_total">{v.declared_total}</dd></div>
            <div><dt>Rounding difference <Def term="tolerance">Up to {tol.rounding_per_invoice} per invoice (and {tol.rounding_per_line} per line) is tolerated and disclosed; beyond that the invoice raises ROUNDING_EXCEPTION.</Def></dt><dd data-figure="rounding_difference">{v.rounding_difference}</dd></div>
          </dl>
          <h4>Source and lineage</h4>
          <dl className="fields" data-testid="lineage">
            <F k="source_sha256" wide>{v.source_sha256}</F>
            <F k="source_filename">{v.source_filename}</F><F k="idempotency_key">{v.idempotency_key}</F>
          </dl>
          <p className="muted small">The source payload is immutable. A correction would be a new versioned row that never overwrites this extraction; this snapshot holds no correction versions, and the backend's correct-extraction command (C06) returns 501.</p>
          {v.merged_into && <p className="callout" data-testid="merge-note">Merged into <InvoiceLink id={v.merged_into} /> by <Chip v={v.merge_reason ?? ""} />. Group key <span className="mono">{v.merge_group_key}</span>. This row and its source hash are kept as lineage.</p>}
          {v.merged_in.length > 0 && (
            <div data-testid="merged-in">
              <p className="callout">Canonical copy: {v.merged_in.length} later import{v.merged_in.length === 1 ? "" : "s"} merged into this invoice.</p>
              <Scroll label="Invoices merged into this one">
                <table className="grid grid--tight">
                  <caption className="sr">Imports merged into {v.invoice_id}</caption>
                  <thead><tr><th scope="col">Invoice</th><th scope="col">Rule</th><th scope="col">Imported</th><th scope="col">File</th><th scope="col">Bytes</th></tr></thead>
                  <tbody>{v.merged_in.map((m) => <tr key={m.invoice_id}><td><InvoiceLink id={m.invoice_id} /></td><td><Chip v={m.reason} /></td><td className="mono">{stamp(m.imported_at)}</td><td className="mono">{m.source_filename}</td><td>{m.source_sha256 === v.source_sha256 ? "same bytes" : "different bytes"}</td></tr>)}</tbody>
                </table>
              </Scroll>
            </div>
          )}
        </section>
        <section className="decision" aria-label="Decision: the derived result">
          <h3><span className="tag tag--decision">Decision</span> derived, not stored</h3>
          <h4>Three-way match per line <Def term="how a line is matched">Available = net received (receipts minus reversals) minus quantity already consumed by invoices ahead of this one in the consumption order (approved invoices first, by approval instant, then (invoice date, imported at, invoice id) order). A line matches when invoiced quantity does not exceed available and the unit price is within tolerance ({tol.price_per_unit}). Reason order: NO_PO_LINE (no such line, or another vendor's), CURRENCY_MISMATCH, QUANTITY_BLOCKED, PRICE_VARIANCE.</Def></h4>
          <Scroll label="Match per line">
            <table className="grid" data-testid="match-lines">
              <caption className="sr">Match result per line of {v.invoice_id}</caption>
              <thead><tr><th scope="col">Line</th><th scope="col" className="num">Ordered</th><th scope="col" className="num">Net received</th><th scope="col" className="num">Previously invoiced</th><th scope="col" className="num">This invoice</th><th scope="col" className="num">Available</th><th scope="col" className="num">Qty variance</th><th scope="col" className="num">Price variance</th><th scope="col">Result</th></tr></thead>
              <tbody>{v.lines.map((l) => (
                <tr key={l.invoice_line_id} data-line={l.invoice_line_id}>
                  <td className="mono">{l.invoice_line_id}</td><td className="num">{l.ordered ?? "n/a"}</td><td className="num">{l.net_received ?? "n/a"}</td><td className="num">{l.previously_invoiced ?? "n/a"}</td><td className="num">{l.this_invoice}</td>
                  <td className="num">{l.available ?? "n/a"}</td><td className="num">{l.quantity_variance ?? "n/a"}</td><td className="num">{l.price_variance ?? "n/a"}</td>
                  <td>{l.reason_code ? <Chip v={l.reason_code} /> : <Chip v={l.status === "matched" ? "matched" : "received"}>{l.status}</Chip>}</td>
                </tr>))}</tbody>
            </table>
          </Scroll>
          <ul className="plain" data-testid="match-explanations">{v.lines.map((l) => <li key={l.invoice_line_id} className="muted small"><span className="mono">{l.invoice_line_id}</span>: {l.explanation}.</li>)}</ul>
          <h4>Exceptions</h4>
          {v.exceptions.length === 0 && v.resolved_exceptions.length === 0 && <p className="muted" data-testid="no-exceptions">No exception on this invoice.</p>}
          {v.exceptions.length > 0 && <ul className="plain" data-testid="exceptions">{v.exceptions.map((e) => <ExceptionBlock key={e.exception_id} e={e} />)}</ul>}
          {v.resolved_exceptions.length > 0 && <><p className="muted small">Resolved earlier (stored records; the exception cleared when the receipt arrived or a decision was made):</p><ul className="plain" data-testid="resolved-exceptions">{v.resolved_exceptions.map((e) => <ExceptionBlock key={e.exception_id} e={e} resolved />)}</ul></>}
          <h4>Approval trail <Def term="separation of duties">Approval needs an actor different from the invoice's creator and a role the policy version in force at decision time allows for this total. Only the first valid approval counts. A rejection needs a reason.</Def></h4>
          {v.approvals.length === 0 ? <p className="muted" data-testid="no-approvals">No approval or rejection on file{v.in_book && v.exceptions.length === 0 ? "; the invoice is matched and waiting for a reviewer" : ""}.</p> : (
            <Scroll label="Approval trail">
              <table className="grid" data-testid="approval-trail">
                <caption className="sr">Decisions on {v.invoice_id}</caption>
                <thead><tr><th scope="col">Decision</th><th scope="col">Actor</th><th scope="col">Role</th><th scope="col">At</th><th scope="col">Policy in force</th><th scope="col">Separation of duties</th><th scope="col">Verdict</th></tr></thead>
                <tbody>{v.approvals.map((a) => (
                  <tr key={a.approval_id}>
                    <td>{a.decision}{a.reason ? <span className="muted small"> ({a.reason})</span> : null}</td><td className="mono">{a.actor_id}</td><td>{a.actor_role}</td><td className="mono">{stamp(a.decided_at)}</td>
                    <td className="mono">{a.policy_id ? `${a.policy_id}: ${a.policy_role} up to ${a.policy_limit}` : "no policy"}</td><td>{a.separation}{a.role_allowed === false ? "; role not allowed" : ""}</td><td><Chip v={a.verdict} /></td>
                  </tr>))}</tbody>
              </table>
            </Scroll>
          )}
          <h4>Export</h4>
          {v.export ? (
            <dl className="fields" data-testid="export-row">
              <F k="export_id">{v.export.export_id}</F><F k="batch_id">{v.export.batch_id}</F>
              <F k="exported_at">{stamp(v.export.exported_at)}</F><F k="amount">{v.export.amount} {v.export.currency}</F>
              <F k="content_hash" wide>{v.export.content_hash}</F>
            </dl>
          ) : <p className="muted" data-testid="no-export">No export row: {v.status === "approved" ? "approved, not yet in a batch." : "only an approved invoice can be exported."}</p>}
          <p className="muted small">The hash is the sha256 of <span className="mono">invoice_id|vendor_id|invoice_number|invoice_date|currency|amount</span>; the site recomputes it. Nothing is sent anywhere.</p>
          <h4>Credits and payable</h4>
          {v.credits.length === 0 ? <p className="muted" data-testid="no-credits">No credit note applies.</p> : (
            <ul className="plain" data-testid="credits">{v.credits.map((c) => <li key={c.credit_id}><span className="mono">{c.credit_id}</span> credits {c.credit_amount} {v.currency}{c.credited_at ? ` on ${stamp(c.credited_at)}` : ""}</li>)}</ul>
          )}
          {v.approved_payable !== null && <p data-testid="payable">Approved payable: <strong className="mono">{v.approved_payable}</strong> {v.currency} = {v.total} total − {v.credit_total} credits. No cash moves and nothing is marked paid.</p>}
          <p className="muted small">Policy now in force: {v.policy_now ? `${v.policy_now.policy_id}, ${v.policy_now.role} up to ${v.policy_now.limit}` : "none"}.</p>
        </section>
      </div>
    </article>
  );
}
