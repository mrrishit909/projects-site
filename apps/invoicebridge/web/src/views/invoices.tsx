import { useState } from "react";
import { invoiceView } from "../domain/view";
import { Link } from "../components/link";
import { ViewHead } from "../components/layout";
import { WithData } from "../components/ui";
import { picks, defaultInvoice } from "../lib/picks";
import { useParam } from "../router";
import { InvoiceDesk } from "./desk";

/** Find an invoice by id, number or vendor; the choice lives in the address (?invoice=). */
export function InvoiceFinder({ param = "invoice" }: { param?: string }) {
  return <WithData>{({ result, snapshot }) => <FinderInner result={result} golden={snapshot.golden} param={param} />}</WithData>;
}
function FinderInner({ result, golden, param }: { result: import("../domain/pipeline").PipelineResult; golden: boolean; param: string }) {
  const [, setId] = useParam(param, "");
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const found = needle.length < 2 ? [] : [...result.book.invoices.values()].filter((i) => i.invoice_id.includes(needle) || i.invoice_number.toLowerCase().includes(needle) || i.vendor_id.includes(needle)).slice(0, 12);
  return (
    <div className="finder" data-testid="finder">
      <label htmlFor={`find-${param}`}>Find an invoice by id, number or vendor</label>
      <input id={`find-${param}`} type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="inv-0042, OAK-7463, ven-007" autoComplete="off" />
      {needle.length >= 2 && (found.length === 0 ? <p className="muted small">No invoice matches “{q}”.</p> : (
        <ul className="finder__hits" data-testid="finder-hits">{found.map((i) => <li key={i.invoice_id}><button type="button" onClick={() => { setId(i.invoice_id); setQ(""); }}><span className="mono">{i.invoice_id}</span> {i.invoice_number} · {i.vendor_id} · {result.book.status.get(i.invoice_id)}</button></li>)}</ul>
      ))}
      <p className="finder__picks small"><span className="muted">Quick picks:</span> {(golden ? [{ label: "the golden pair", id: "inv-001" }, { label: "the blocked second invoice", id: "inv-002" }, { label: "the re-sent copy", id: "inv-003" }] : picks(result)).map((p) => <button key={p.id} type="button" className="linkish" onClick={() => setId(p.id)}>{p.label} <span className="mono">({p.id})</span></button>)}</p>
    </div>
  );
}

export function Invoices() {
  const [chosen] = useParam("invoice", "");
  return (
    <>
      <ViewHead eyebrow="Entry: the golden pair, then any invoice" title="Invoice desk">
        <p className="lede">Evidence beside decision. On the left the invoice as the system holds it: structured fields, lines, source hash and lineage. On the right what was derived from recorded facts: the three-way match per line, exceptions with their assignment history, the approval trail under the policy in force, the export row and credits.</p>
      </ViewHead>
      <InvoiceFinder />
      <WithData>{({ result, snapshot }) => {
        const ids = chosen && result.book.invoices.has(chosen) ? [chosen] : defaultInvoice(result, snapshot.golden);
        const missing = chosen && !result.book.invoices.has(chosen);
        return (
          <>
            {missing && <p className="notice notice--bad" role="alert" data-testid="unknown-invoice">No invoice “{chosen}” in this dataset; showing the default instead. <Link to="invoices">Clear</Link></p>}
            {snapshot.golden && !chosen && <p className="callout" data-testid="golden-pair-note">The golden pair: inv-001 for 6 × 20.00 matches (120.00 + 12.00 tax = 132.00) and consumes the 6 received units; inv-002 for 4 units is QUANTITY_BLOCKED because none is left until a receipt arrives. The third file, inv-003, is a re-sent copy merged into inv-001.</p>}
            {ids.map((id) => <InvoiceDesk key={id} v={invoiceView(result, id)!} result={result} />)}
          </>
        );
      }}</WithData>
    </>
  );
}
