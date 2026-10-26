import { EXCEPTION_CODES } from "../domain/contract";
import type { PipelineResult } from "../domain/pipeline";
import { invoiceView } from "../domain/view";
import { isoZ } from "../domain/time";
import { ViewHead } from "../components/layout";
import { Chip, Def, InvoiceLink, Scroll, usePager, WithData } from "../components/ui";
import { stamp } from "../lib/format";
import { useParam } from "../router";
import { ExceptionBlock } from "./desk";

function Queue({ result }: { result: PipelineResult }) {
  const [reason, setReason] = useParam("reason", "all");
  const [owner, setOwner] = useParam("owner", "all");
  const [sel, setSel] = useParam("exception", "");
  const b = result.book;
  const stored = new Map(result.exceptionRows.map((e) => [e.exception_id as string, e]));
  const assigns = new Map<string, { at: number; owner: string }[]>();
  for (const a of result.population.assignments) (assigns.get(a.exception_id) ?? assigns.set(a.exception_id, []).get(a.exception_id)!).push({ at: a.assigned_at, owner: a.owner_id });
  const all = b.exceptions;
  const owners = [...new Set(all.map((e) => e.owner_id).filter((o): o is string => o !== null))].sort();
  const rows = all.filter((e) => (reason === "all" || e.exception_type === reason) && (owner === "all" || (owner === "unowned" ? e.owner_id === null : e.owner_id === owner)));
  const { page, ui } = usePager(rows, 20);
  const asOfMs = Date.parse(isoZ(b.cutoff));
  const opened = (id: string): string | null => (typeof stored.get(id)?.created_at === "string" ? (stored.get(id)!.created_at as string) : null);
  const selected = all.find((e) => e.exception_id === sel) ?? null;
  const selView = selected ? invoiceView(result, selected.invoice_id)!.exceptions.find((e) => e.exception_id === selected.exception_id) ?? null : null;
  const matrix = EXCEPTION_CODES.map((c) => ({ c, total: all.filter((e) => e.exception_type === c).length, unowned: all.filter((e) => e.exception_type === c && e.owner_id === null).length }));
  return (
    <>
      <section className="panel" aria-labelledby="sum-h">
        <h2 id="sum-h">Open exceptions by reason and owner <Def term="what is open">One exception per (invoice, reason) in the latest matching run. It is open until it is assigned to an owner, and it clears when the pair stops failing (a receipt arrives) or the invoice is rejected. Backlog can be rebuilt as of any cutoff from the assignment history.</Def></h2>
        <div className="two">
          <Scroll label="By reason">
            <table className="grid" data-testid="by-reason">
              <caption className="sr">Open exceptions by reason</caption>
              <thead><tr><th scope="col">Reason</th><th scope="col" className="num">Open</th><th scope="col" className="num">Unowned</th><th scope="col" className="num">Owned</th></tr></thead>
              <tbody>{matrix.map((x) => <tr key={x.c} data-reason={x.c}><td><Chip v={x.c} /></td><td className="num">{x.total}</td><td className="num">{x.unowned}</td><td className="num">{x.total - x.unowned}</td></tr>)}
                <tr className="total"><th scope="row">All reasons</th><td className="num" data-figure="exceptions.open_count">{all.length}</td><td className="num" data-figure="exceptions.unowned_count">{all.filter((e) => e.owner_id === null).length}</td><td className="num">{all.filter((e) => e.owner_id !== null).length}</td></tr></tbody>
            </table>
          </Scroll>
          <Scroll label="By owner">
            <table className="grid" data-testid="by-owner">
              <caption className="sr">Open exceptions by owner</caption>
              <thead><tr><th scope="col">Owner</th><th scope="col" className="num">Open</th></tr></thead>
              <tbody><tr><td>unowned</td><td className="num">{all.filter((e) => e.owner_id === null).length}</td></tr>{owners.map((o) => <tr key={o}><td className="mono">{o}</td><td className="num">{all.filter((e) => e.owner_id === o).length}</td></tr>)}</tbody>
            </table>
          </Scroll>
        </div>
      </section>
      <section className="panel" aria-labelledby="q-h">
        <h2 id="q-h">The queue</h2>
        <div className="filters" data-testid="filters">
          <label>Reason <select value={reason} onChange={(e) => setReason(e.target.value)} data-testid="f-reason"><option value="all">All reasons</option>{EXCEPTION_CODES.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
          <label>Owner <select value={owner} onChange={(e) => setOwner(e.target.value)} data-testid="f-owner"><option value="all">Everyone</option><option value="unowned">Unowned</option>{owners.map((o) => <option key={o} value={o}>{o}</option>)}</select></label>
          <button type="button" onClick={() => { setReason("all"); setOwner("all"); }}>Clear filters</button>
        </div>
        <Scroll label="Exception queue">
          <table className="grid" data-testid="queue-table">
            <caption className="sr">Open exceptions</caption>
            <thead><tr><th scope="col">Exception</th><th scope="col">Invoice</th><th scope="col">Vendor</th><th scope="col">Reason</th><th scope="col">Owner</th><th scope="col" className="num">Assignments</th><th scope="col">Opened</th><th scope="col" className="num">Age (days)</th><th scope="col">History</th></tr></thead>
            <tbody>{page.map((e) => {
              const a = assigns.get(e.exception_id) ?? [];
              const o = opened(e.exception_id);
              return (
                <tr key={e.exception_id} data-exception={e.exception_id} aria-selected={e.exception_id === sel}>
                  <td className="mono">{e.exception_id}</td><td><InvoiceLink id={e.invoice_id} /></td><td className="mono">{b.invoices.get(e.invoice_id)!.vendor_id}</td><td><Chip v={e.exception_type} /></td>
                  <td>{e.owner_id ?? <Chip v="open">unowned</Chip>}</td><td className="num">{a.length}</td><td className="mono">{o ? stamp(o) : "n/a"}</td><td className="num">{o ? Math.floor((asOfMs - Date.parse(o)) / 86_400_000) : "n/a"}</td>
                  <td><button type="button" className="linkish" onClick={() => setSel(e.exception_id === sel ? "" : e.exception_id)}>{e.exception_id === sel ? "Hide" : "Show"}</button></td>
                </tr>);
            })}</tbody>
          </table>
        </Scroll>
        {ui}
        {all.length === 0 && <p className="muted" data-testid="queue-empty">No exception is open in this dataset.</p>}
      </section>
      {selView && selected && (
        <section className="panel" aria-labelledby="hist-h" data-testid="selected-exception">
          <h2 id="hist-h">Assignment history of {selected.exception_id}</h2>
          <p>Invoice <InvoiceLink id={selected.invoice_id} /> · {b.invoices.get(selected.invoice_id)!.vendor_id}</p>
          <ul className="plain"><ExceptionBlock e={selView} /></ul>
        </section>
      )}
      <p className="muted small">Assigning, reassigning and resolving an exception are backend commands that this site does not run: the queue is read-only and shows what the recorded assignments imply.</p>
    </>
  );
}
export function ExceptionsView() {
  return (
    <>
      <ViewHead eyebrow="Entry: the exception queue" title="Exception queue">
        <p className="lede">What stops an invoice from advancing, by reason and by owner. Each open exception keeps its assignment history; an exception nobody owns is shown as unowned.</p>
      </ViewHead>
      <WithData>{({ result }) => <Queue result={result} />}</WithData>
    </>
  );
}
