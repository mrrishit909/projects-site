import { useMemo } from "react";
import { EXCEPTION_CODES } from "../domain/contract";
import { s2 } from "../domain/num";
import type { PipelineResult } from "../domain/pipeline";
import { ViewHead } from "../components/layout";
import { Chip, Def, InvoiceLink, Scroll, usePager, WithData } from "../components/ui";
import { cmp, pct } from "../lib/format";
import { useParam } from "../router";

interface Row { id: string; vendor: string; number: string; date: string; month: string; status: string; total: bigint; reasons: string[]; lines: number; inBook: boolean }
const is02x = (v: string): boolean => /^ven-02\d$/.test(v);

function build(r: PipelineResult): Row[] {
  const b = r.book;
  return [...b.invoices.values()].sort((x, y) => cmp(x.invoice_id, y.invoice_id)).map((i) => {
    const st = b.run.invoices.get(i.invoice_id);
    return { id: i.invoice_id, vendor: i.vendor_id, number: i.invoice_number, date: i.invoice_date, month: i.invoice_date.slice(0, 7), status: b.status.get(i.invoice_id)!, total: st?.total ?? 0n, reasons: st?.reasons ?? [], lines: i.lines.length, inBook: !!st };
  });
}

function Matching({ result }: { result: PipelineResult }) {
  const all = useMemo(() => build(result), [result]);
  const [vendor, setVendor] = useParam("vendor", "all");
  const [reason, setReason] = useParam("reason", "all");
  const [month, setMonth] = useParam("month", "all");
  const m = result.metrics;
  const vendors = [...new Set(all.map((x) => x.vendor))].sort();
  const months = [...new Set(all.map((x) => x.month))].sort();
  const rows = all.filter((x) => (vendor === "all" || (vendor === "ven-02x" ? is02x(x.vendor) : x.vendor === vendor)) && (month === "all" || x.month === month)
    && (reason === "all" || (reason === "any" ? x.reasons.length > 0 : reason === "none" ? x.inBook && x.reasons.length === 0 : x.reasons.includes(reason))));
  const { page, ui } = usePager(rows, 25);
  const count = (f: (x: Row) => boolean): number => rows.filter(f).length;
  const advanced = rows.filter((x) => ["matched", "approved", "exported", "adjusted"].includes(x.status));
  const advTotal = advanced.reduce((t, x) => t + x.total, 0n);
  const byReason = Object.fromEntries(EXCEPTION_CODES.map((c) => [c, rows.filter((x) => x.reasons.includes(c)).length]));

  // reconciliation of the whole book (never filtered) to the overview metrics
  const A = all;
  const sum = (xs: Row[]): bigint => xs.reduce((t, x) => t + x.total, 0n);
  const adv = A.filter((x) => ["matched", "approved", "exported", "adjusted"].includes(x.status));
  const obl = A.filter((x) => ["approved", "exported", "adjusted"].includes(x.status));
  const recon: [string, string, string][] = [
    ["Matched or later: invoices", String(adv.length), String(m.matched.invoice_count)],
    ["Matched or later: total", s2(sum(adv)), m.matched.total],
    ["Obligations (approved, exported, adjusted): invoices", String(obl.length), String(m.obligations.count)],
    ["Obligations: total", s2(sum(obl)), m.obligations.total],
    ["Exception records (one per invoice and reason)", String(A.reduce((t, x) => t + x.reasons.length, 0)), String(m.exceptions.open_count)],
    ["Merged invoices", String(A.filter((x) => x.status === "merged").length), String(m.duplicates.rows_merged)],
    ["In the book (eligible)", String(A.filter((x) => x.inBook).length), String(m.rates.eligible_invoices)],
    ["All invoices = sum of the ten statuses", String(A.length), String(result.population.invoices.length)],
  ];
  // designed relationships, recomputed from the derived data
  const inBook = A.filter((x) => x.inBook);
  const g = (p: (v: string) => boolean): [number, number] => { const xs = inBook.filter((x) => p(x.vendor)); return [xs.filter((x) => x.reasons.includes("QUANTITY_BLOCKED")).length, xs.length]; };
  const dr1a = g(is02x), dr1b = g((v) => !is02x(v));
  const pv = A.filter((x) => x.reasons.includes("PRICE_VARIANCE"));
  const pvMonths = [...new Set(pv.map((x) => x.month))].sort();

  return (
    <>
      <section className="panel" aria-labelledby="filters-h">
        <h2 id="filters-h">Filters</h2>
        <div className="filters" data-testid="filters">
          <label>Vendor <select value={vendor} onChange={(e) => setVendor(e.target.value)} data-testid="f-vendor"><option value="all">All vendors</option><option value="ven-02x">ven-02x (ven-020 to ven-029)</option>{vendors.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
          <label>Reason <select value={reason} onChange={(e) => setReason(e.target.value)} data-testid="f-reason"><option value="all">Any state</option><option value="any">Any exception</option><option value="none">No exception (in the book)</option>{EXCEPTION_CODES.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
          <label>Invoice month <select value={month} onChange={(e) => setMonth(e.target.value)} data-testid="f-month"><option value="all">All months</option>{months.map((x) => <option key={x} value={x}>{x}</option>)}</select></label>
          <button type="button" onClick={() => { setVendor("all"); setReason("all"); setMonth("all"); }}>Clear filters</button>
        </div>
      </section>
      <section className="panel" aria-labelledby="tot-h">
        <h2 id="tot-h">Totals for this filter</h2>
        <dl className="glance" data-testid="filter-totals">
          <div data-figure="f.invoices"><dt>Invoices</dt><dd>{rows.length.toLocaleString("en-US")}</dd></div>
          <div data-figure="f.advanced"><dt>Matched or later</dt><dd>{advanced.length.toLocaleString("en-US")}<small>total {s2(advTotal)}</small></dd></div>
          <div data-figure="f.exception"><dt>With an exception</dt><dd>{count((x) => x.reasons.length > 0)}</dd></div>
          <div data-figure="f.merged"><dt>Merged</dt><dd>{count((x) => x.status === "merged")}</dd></div>
          <div data-figure="f.rejected"><dt>Rejected</dt><dd>{count((x) => x.status === "rejected")}</dd></div>
        </dl>
        <p className="small" data-testid="filter-reasons">{EXCEPTION_CODES.map((c) => `${c} ${byReason[c]}`).join(" · ")}</p>
        <Scroll label="Matching results">
          <table className="grid" data-testid="matching-table">
            <caption className="sr">Derived match state of each invoice in the filter</caption>
            <thead><tr><th scope="col">Invoice</th><th scope="col">Vendor</th><th scope="col">Number</th><th scope="col">Date</th><th scope="col">State</th><th scope="col" className="num">Total</th><th scope="col">Reasons</th></tr></thead>
            <tbody>{page.map((x) => (
              <tr key={x.id} data-vendor={x.vendor}>
                <td><InvoiceLink id={x.id} /></td><td className="mono">{x.vendor}</td><td className="mono">{x.number}</td><td className="mono">{x.date}</td><td><Chip v={x.status} /></td><td className="num">{x.inBook ? s2(x.total) : "n/a"}</td>
                <td>{x.reasons.length === 0 ? <span className="muted">none</span> : x.reasons.map((c) => <Chip key={c} v={c} />)}</td>
              </tr>))}</tbody>
          </table>
        </Scroll>
        {ui}
      </section>
      <section className="panel" aria-labelledby="rec-h">
        <h2 id="rec-h">Reconciliation to the overview <Def term="why these agree">The matching panel and the overview read the same derived book, so the totals over every invoice must equal the headline metrics. The check below recomputes them from the rows of this table, unfiltered.</Def></h2>
        <Scroll label="Reconciliation">
          <table className="grid" data-testid="reconciliation">
            <caption className="sr">Totals of all invoices against the overview metrics</caption>
            <thead><tr><th scope="col">Figure</th><th scope="col" className="num">This panel</th><th scope="col" className="num">Overview</th><th scope="col">Agree</th></tr></thead>
            <tbody>{recon.map(([k, a, b]) => <tr key={k} data-agree={a === b}><td>{k}</td><td className="num">{a}</td><td className="num">{b}</td><td>{a === b ? "yes" : "NO"}</td></tr>)}</tbody>
          </table>
        </Scroll>
      </section>
      <section className="panel" aria-labelledby="dr-h">
        <h2 id="dr-h">Designed relationships in the synthetic data</h2>
        <p className="muted">The generator plants these patterns so that the match has something to find; the shares below are recomputed here from the derived exceptions, not copied from the manifest.</p>
        <div className="two">
          <div data-testid="dr-02x">
            <h3>ven-02x invoice before they deliver</h3>
            <p>Vendors ven-020 to ven-029 invoice days before the goods arrive. QUANTITY_BLOCKED on <strong data-figure="dr1.02x">{dr1a[0]} of {dr1a[1]}</strong> of their in-book invoices ({pct(dr1a[0], dr1a[1])}) against <strong data-figure="dr1.other">{dr1b[0]} of {dr1b[1]}</strong> elsewhere ({pct(dr1b[0], dr1b[1])}).</p>
            <button type="button" onClick={() => { setVendor("ven-02x"); setReason("QUANTITY_BLOCKED"); setMonth("all"); }}>Show ven-02x blocked invoices</button>
          </div>
          <div data-testid="dr-007">
            <h3>ven-007 price list change</h3>
            <p>ven-007 bills a new price list from 2026-03 on purchase orders still carrying the old prices (the catalogue is updated on 2026-04-15). PRICE_VARIANCE invoices by invoice month: {pvMonths.map((mm) => `${mm}: ${pv.filter((x) => x.month === mm).length}`).join(", ") || "none"}. ven-007 holds <strong data-figure="dr2.share">{pv.filter((x) => x.vendor === "ven-007").length} of {pv.length}</strong> ({pct(pv.filter((x) => x.vendor === "ven-007").length, pv.length)}).</p>
            <button type="button" onClick={() => { setVendor("ven-007"); setReason("PRICE_VARIANCE"); setMonth("all"); }}>Show ven-007 price variances</button>
          </div>
        </div>
      </section>
    </>
  );
}

export function MatchingView() {
  return (
    <>
      <ViewHead eyebrow="Entry: the matching panel" title="Three-way matching">
        <p className="lede">Every invoice's derived state against purchase orders and receipts, cumulative in (invoice date, imported at, invoice id) order: an invoice consumes received quantity only once it is matched. Filter by vendor, reason or month; the totals reconcile to the overview.</p>
      </ViewHead>
      <WithData>{({ result }) => <Matching result={result} />}</WithData>
    </>
  );
}
