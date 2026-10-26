// P01-UI-08 Transaction evidence ledger: filtered shipment lines, drill highlight, totals that equal the bridge, export.
import { useMemo } from "react";
import { ExportButtons } from "../components/export";
import { DatasetBanner, EmptyPopulation, Filters, PopulationSummary, QueryLink } from "../components/filters";
import { fmtDec, fmtInt } from "../components/format";
import { LedgerTable, STEP_COLUMNS, ledgerTotals } from "../components/ledger-table";
import { MetricDefinition } from "../components/metric-definition";
import { ErrorState, Loading } from "../components/status";
import { ZERO } from "../domain/decimal";
import { patchQuery, usePopulation, useSearch } from "../state/filters";

const STEP_LABEL: Record<string, string> = {
  gross: "Gross sales", discounts: "Allocated discounts", credits: "Merchandise credits", net: "Net merchandise sales",
  cogs: "COGS", gross_profit: "Gross profit", shipping_revenue: "Shipping revenue", shipping_cost: "Shipping cost", contribution: "Contribution margin",
};

export function Evidence() {
  const pop = usePopulation();
  const search = useSearch();
  const hl = new URLSearchParams(search).get("hl") ?? "";
  const cols = STEP_COLUMNS[hl] ?? [];
  const totals = useMemo(() => (pop.status === "ready" ? ledgerTotals(pop.facts, pop.active ? ZERO : pop.result.unallocatedFreight) : null), [pop]);
  const quarantine = useMemo(() => {
    if (pop.status !== "ready") return [];
    const m = new Map<string, number>();
    for (const q of pop.result.quarantined) m.set(`${q.entity}|${q.reason_code}`, (m.get(`${q.entity}|${q.reason_code}`) ?? 0) + 1);
    return [...m].sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, n]) => ({ entity: k.split("|")[0]!, reason: k.split("|")[1]!, n }));
  }, [pop]);

  return (
    <article>
      <div className="page-head">
        <p className="eyebrow">Evidence</p>
        <h1>Transaction evidence ledger</h1>
        <p className="lede">One row per shipment line. The totals below are summed from these rows and must equal the margin bridge for the same filters.</p>
      </div>
      <DatasetBanner />
      {pop.status === "loading" && <Loading />}
      {pop.status === "error" && <ErrorState message={pop.error} onRetry={pop.retry} />}
      {pop.status === "ready" && totals && (
        <>
          <Filters options={pop.options} />
          <PopulationSummary pop={pop} />
          {hl && (
            <p className="note-box" data-testid="highlight-note" role="status">
              Highlighting the columns behind <strong>{STEP_LABEL[hl] ?? hl}</strong> from the margin bridge
              {cols.length === 0 ? " (no ledger column: this step is 0.00 because the dataset records no shipping revenue)" : ""}.{" "}
              <button type="button" className="btn" onClick={() => patchQuery({ hl: null })}>Remove highlight</button>
            </p>
          )}
          {pop.facts.length === 0 ? <EmptyPopulation windowError={pop.windowError} /> : (
            <>
              <h2>Totals for this population</h2>
              <dl className="totals" data-testid="ledger-totals" aria-label="Ledger totals, USD">
                {([
                  ["gross", "Gross sales", totals.gross, "gross_sales"], ["discounts", "Allocated discounts", totals.discount, "allocated_discounts"],
                  ["credits", "Merchandise credits", totals.credit, "merchandise_credits"], ["net", "Net merchandise sales", totals.net, "net_merchandise_sales"],
                  ["cogs", "COGS after recoverable return cost", totals.cogsNet, "cogs"], ["gross_profit", "Gross profit", totals.grossProfit, "gross_profit"],
                  ["shipping_cost", "Shipping cost", totals.freight, "shipping_cost"], ["contribution", "Contribution margin", totals.contribution, "contribution_margin"],
                ] as const).map(([id, label, v, metric]) => (
                  <div key={id}><dt>{label}<MetricDefinition metric={metric} /></dt><dd data-testid={`totals-${id}`}>{fmtDec(v)}</dd></div>
                ))}
              </dl>
              <p className="small muted" style={{ maxWidth: "none" }}>
                USD. The COGS column below is cost at the shipped cost version; the total subtracts {fmtDec(totals.recoverable)} of recoverable return cost, as the bridge does (D-03).
                {" "}<QueryLink to="bridge" filters={pop.filters}>Compare with the margin bridge</QueryLink>.
              </p>
              <ExportButtons pop={pop} />
              <LedgerTable facts={pop.facts} lookups={pop.lookups} highlight={cols} extraFreight={pop.active ? ZERO : pop.result.unallocatedFreight} />
            </>
          )}
          <section className="note-box" aria-labelledby="quarantine-title" data-testid="quarantine-note">
            <h2 id="quarantine-title">Quarantined records</h2>
            <p className="small" style={{ maxWidth: "none" }}>
              Lines that cannot be costed or converted are quarantined, never guessed: they are absent from the ledger and every total above. Counts cover the whole published snapshot, whatever the filters.
              {" "}{fmtInt(pop.result.excluded.length)} lines were excluded by order status and {fmtInt(pop.result.ingest.rejected.length)} raw records were rejected at ingest.
            </p>
            {quarantine.length === 0 ? <p>No records were quarantined in this dataset.</p> : (
              <div className="tablewrap" tabIndex={0} role="region" aria-label="Quarantined records by reason">
                <table>
                  <caption>Quarantined records by entity and reason code (D-02, D-03, D-06). Synthetic data.</caption>
                  <thead><tr><th scope="col">Entity</th><th scope="col">Reason</th><th scope="col" className="num">Records</th></tr></thead>
                  <tbody>{quarantine.map((q) => <tr key={`${q.entity}${q.reason}`}><td>{q.entity}</td><td>{q.reason}</td><td className="num">{fmtInt(q.n)}</td></tr>)}</tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </article>
  );
}
