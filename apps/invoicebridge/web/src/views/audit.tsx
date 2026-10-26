import type { PipelineResult } from "../domain/pipeline";
import { invoiceView } from "../domain/view";
import { ViewHead } from "../components/layout";
import { Chip, InvoiceLink, Scroll, WithData } from "../components/ui";
import { defaultInvoice } from "../lib/picks";
import { stamp } from "../lib/format";
import { useParam } from "../router";
import { InvoiceFinder } from "./invoices";

interface Ev { at: string; what: string; detail: string; source: string }

function timeline(result: PipelineResult, id: string): Ev[] {
  const v = invoiceView(result, id)!;
  const ev: Ev[] = [{ at: v.imported_at, what: v.merged_into ? `Imported and merged into ${v.merged_into}` : "Imported", detail: `${v.source_filename}, sha256 ${v.source_sha256.slice(0, 12)}…, created by ${v.created_by}${v.merge_reason ? `, rule ${v.merge_reason}` : ""}`, source: "invoices" }];
  for (const m of v.merged_in) ev.push({ at: m.imported_at, what: `${m.invoice_id} re-sent and merged into this invoice`, detail: `${m.source_filename}, ${m.reason}, ${m.source_sha256 === v.source_sha256 ? "same bytes" : "different bytes"}`, source: "invoices" });
  for (const e of [...v.exceptions, ...v.resolved_exceptions]) {
    if (e.created_at) ev.push({ at: e.created_at, what: `Exception ${e.exception_id} opened`, detail: e.exception_type, source: "exceptions" });
    for (const a of e.assignments) ev.push({ at: a.assigned_at, what: `${e.exception_id} assigned to ${a.owner_id}`, detail: `by ${a.assigned_by ?? "n/a"}${a.note ? `, ${a.note}` : ""}`, source: "exception_assignments" });
    if (e.resolved_at) ev.push({ at: e.resolved_at, what: `Exception ${e.exception_id} resolved`, detail: e.exception_type, source: "exceptions" });
  }
  for (const a of v.approvals) ev.push({ at: a.decided_at, what: `${a.decision === "approve" ? "Approval" : "Rejection"} by ${a.actor_id} (${a.actor_role})`, detail: `verdict ${a.verdict}${a.policy_id ? `, ${a.policy_id}` : ""}${a.reason ? `, reason: ${a.reason}` : ""}`, source: "approvals" });
  if (v.export) ev.push({ at: v.export.exported_at, what: `Exported in ${v.export.batch_id}`, detail: `${v.export.amount} ${v.export.currency}, content_hash ${v.export.content_hash.slice(0, 12)}…`, source: "export_requests" });
  for (const c of v.credits) if (c.credited_at) ev.push({ at: c.credited_at, what: `Credit note ${c.credit_id} applied`, detail: `${c.credit_amount} ${v.currency}; no cash movement`, source: "credit_notes" });
  return ev.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
}

function Audit({ result, golden }: { result: PipelineResult; golden: boolean }) {
  const [chosen] = useParam("invoice", "");
  const id = chosen && result.book.invoices.has(chosen) ? chosen : defaultInvoice(result, golden)[0]!;
  const v = invoiceView(result, id)!;
  const ev = timeline(result, id);
  return (
    <section className="panel" aria-labelledby="tl-h">
      <h2 id="tl-h">Timeline of <InvoiceLink id={id} /> <Chip v={v.status} /></h2>
      <p className="muted">{v.invoice_number} · {v.vendor_id} · {v.vendor_name}. Each row is a recorded fact with the table it comes from; the site holds no separate audit-event log.</p>
      <Scroll label="Audit timeline">
        <ol className="timeline" data-testid="timeline">
          {ev.map((e, i) => <li key={i}><time className="mono" dateTime={e.at}>{stamp(e.at)}</time><div><strong>{e.what}</strong><span className="muted small"> {e.detail}</span><span className="src small">{e.source}</span></div></li>)}
        </ol>
      </Scroll>
    </section>
  );
}
export function AuditView() {
  return (
    <>
      <ViewHead eyebrow="Read-only view" title="Audit timeline">
        <p className="lede">The life of one invoice in time order: import, duplicates merged into it, exceptions and their assignments, decisions, export and credits. It is rebuilt from recorded facts, so it can be rebuilt as of any cutoff.</p>
      </ViewHead>
      <InvoiceFinder />
      <WithData>{({ result, snapshot }) => <Audit result={result} golden={snapshot.golden} />}</WithData>
    </>
  );
}
