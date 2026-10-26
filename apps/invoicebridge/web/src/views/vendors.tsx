import { useMemo } from "react";
import { s2 } from "../domain/num";
import type { PipelineResult } from "../domain/pipeline";
import { ViewHead } from "../components/layout";
import { Scroll, WithData } from "../components/ui";
import { pct } from "../lib/format";
import { useParam } from "../router";

function Vendors({ result }: { result: PipelineResult }) {
  const [sort, setSort] = useParam("sort", "id");
  const b = result.book;
  const rows = useMemo(() => result.population.vendors.map((v) => {
    const inv = [...b.invoices.values()].filter((i) => i.vendor_id === v.vendor_id);
    const inBook = inv.filter((i) => b.run.invoices.has(i.invoice_id));
    const has = (i: { invoice_id: string }, c: string): boolean => b.run.invoices.get(i.invoice_id)!.reasons.includes(c);
    const oblig = inBook.filter((i) => ["approved", "exported", "adjusted"].includes(b.status.get(i.invoice_id)!));
    const total = oblig.reduce((t, i) => t + b.run.invoices.get(i.invoice_id)!.total, 0n);
    const design = /^ven-02\d$/.test(v.vendor_id) ? "ven-02x: invoices before receipts" : v.vendor_id === "ven-007" ? "ven-007: price list change" : "";
    return { v, invoices: inv.length, inBook: inBook.length, merged: inv.filter((i) => b.status.get(i.invoice_id) === "merged").length, exc: inBook.filter((i) => b.run.invoices.get(i.invoice_id)!.reasons.length > 0).length,
      qb: inBook.filter((i) => has(i, "QUANTITY_BLOCKED")).length, pv: inBook.filter((i) => has(i, "PRICE_VARIANCE")).length, oblig: oblig.length, total, design };
  }), [result, b]);
  const sorted = [...rows].sort((x, y) => sort === "qb" ? y.qb * Math.max(x.inBook, 1) - x.qb * Math.max(y.inBook, 1) : sort === "pv" ? y.pv - x.pv : sort === "invoices" ? y.invoices - x.invoices : x.v.vendor_id < y.v.vendor_id ? -1 : 1);
  return (
    <>
      <div className="filters"><label>Sort by <select value={sort} onChange={(e) => setSort(e.target.value)} data-testid="f-sort"><option value="id">Vendor id</option><option value="qb">QUANTITY_BLOCKED share</option><option value="pv">PRICE_VARIANCE count</option><option value="invoices">Invoices</option></select></label></div>
      <Scroll label="Vendors">
        <table className="grid" data-testid="vendor-table">
          <caption className="sr">One row per vendor</caption>
          <thead><tr><th scope="col">Vendor</th><th scope="col">Name</th><th scope="col">Cur.</th><th scope="col" className="num">Invoices</th><th scope="col" className="num">In book</th><th scope="col" className="num">Merged</th><th scope="col" className="num">With exception</th><th scope="col" className="num">Blocked</th><th scope="col" className="num">Blocked share</th><th scope="col" className="num">Price var.</th><th scope="col" className="num">Obligations</th><th scope="col" className="num">Obligation total (vendor currency)</th><th scope="col">Designed relationship</th></tr></thead>
          <tbody>{sorted.map((r) => (
            <tr key={r.v.vendor_id} className={r.design ? "hl" : undefined} data-vendor={r.v.vendor_id}>
              <td className="mono">{r.v.vendor_id}</td><td>{r.v.vendor_name}{r.v.active ? "" : " (inactive)"}</td><td>{r.v.currency}</td><td className="num">{r.invoices}</td><td className="num">{r.inBook}</td><td className="num">{r.merged}</td><td className="num">{r.exc}</td><td className="num">{r.qb}</td><td className="num">{pct(r.qb, r.inBook)}</td><td className="num">{r.pv}</td><td className="num">{r.oblig}</td><td className="num">{s2(r.total)}</td><td>{r.design}</td>
            </tr>))}</tbody>
        </table>
      </Scroll>
      <p className="muted small">Totals are in each vendor's own currency (25 vendors bill in USD, 10 in EUR, 5 in GBP); no conversion is applied anywhere, and a line in a currency other than its PO's raises CURRENCY_MISMATCH.</p>
    </>
  );
}
export function VendorsView() {
  return (
    <>
      <ViewHead eyebrow="Read-only view" title="Vendors">
        <p className="lede">Per-vendor counts from the derived book. The shaded rows carry the two relationships planted in the synthetic data: ven-020 to ven-029 invoice before they deliver, and ven-007 changed its price list in March 2026.</p>
      </ViewHead>
      <WithData>{({ result }) => <Vendors result={result} />}</WithData>
    </>
  );
}
