// P01-UI-03 Margin bridge: gross sales to contribution margin as a reconciled waterfall, with drill into the ledger.
import { useMemo } from "react";
import { Waterfall, type WaterfallStep } from "../components/charts/waterfall";
import { DatasetBanner, EmptyPopulation, Filters, PopulationSummary, QueryLink } from "../components/filters";
import { fmtMoney, fmtRate } from "../components/format";
import { MetricDefinition } from "../components/metric-definition";
import { ErrorState, Loading } from "../components/status";
import { navigate } from "../router";
import { hrefFor } from "../routes";
import * as D from "../domain/decimal";
import { computeMetrics, groupMetrics, regionKey } from "../domain/metrics";
import { UNALLOCATED_GROUP, UNASSIGNED_REGION } from "../domain/contract";
import { carriedParams, queryFor, usePopulation, useSearch } from "../state/filters";

const neg = (s: string): string => (D.isZero(D.parse(s)) ? s : D.toString(D.neg(D.parse(s))));

export function Bridge() {
  const pop = usePopulation();
  const search = useSearch();
  const model = useMemo(() => {
    if (pop.status !== "ready" || (pop.facts.length === 0 && pop.outside.length === 0)) return null;
    const m = pop.metrics;
    const steps: (WaterfallStep & { metric?: string })[] = [
      { id: "gross", short: "Gross sales", label: "Gross sales", kind: "total", value: m.gross_sales, text: fmtMoney(m.gross_sales), metric: "gross_sales" },
      { id: "discounts", short: "− Allocated discounts", label: "− Allocated discounts", kind: "delta", value: neg(m.allocated_discounts), text: fmtMoney(neg(m.allocated_discounts)), metric: "allocated_discounts" },
      { id: "credits", short: "− Merchandise credits", label: "− Merchandise credits", kind: "delta", value: neg(m.merchandise_credits), text: fmtMoney(neg(m.merchandise_credits)), metric: "merchandise_credits" },
      { id: "net", short: "= Net merchandise sales", label: "= Net merchandise sales", kind: "total", value: m.net_merchandise_sales, text: fmtMoney(m.net_merchandise_sales), metric: "net_merchandise_sales" },
      { id: "cogs", short: "− COGS", label: "− COGS (after recoverable return cost)", kind: "delta", value: neg(m.cogs), text: fmtMoney(neg(m.cogs)), metric: "cogs" },
      { id: "gross_profit", short: "= Gross profit", label: "= Gross profit", kind: "total", value: m.gross_profit, text: fmtMoney(m.gross_profit), metric: "gross_profit" },
      { id: "shipping_revenue", short: "+ Shipping revenue", label: "+ Shipping revenue", kind: "delta", value: m.shipping_revenue, text: fmtMoney(m.shipping_revenue), metric: "shipping_revenue" },
      { id: "shipping_cost", short: "− Shipping cost", label: "− Shipping cost", kind: "delta", value: neg(m.shipping_cost), text: fmtMoney(neg(m.shipping_cost)), metric: "shipping_cost" },
      { id: "contribution", short: "= Contribution margin", label: "= Contribution margin", kind: "total", value: m.contribution_margin, text: fmtMoney(m.contribution_margin), metric: "contribution_margin" },
    ];
    // Recompute the subtotals from the steps and compare with the reported ones (exact decimals).
    const v = (id: string): D.Dec => D.parse(steps.find((s) => s.id === id)!.value);
    const net = D.add(D.add(v("gross"), v("discounts")), v("credits"));
    const gp = D.add(net, v("cogs"));
    const cm = D.add(D.add(gp, v("shipping_revenue")), v("shipping_cost"));
    // Each step is rounded to cents on its own (D-02, presentation), so a subtotal may differ from the sum of the
    // displayed steps by one cent per step; anything larger is a real reconciliation failure.
    const diffs = [["net", D.sub(v("net"), net)], ["gross profit", D.sub(v("gross_profit"), gp)], ["contribution", D.sub(v("contribution"), cm)]] as const;
    const tolerance = D.parse("0.02");
    const arithmeticOk = diffs.every(([, d]) => D.cmp(d.u < 0n ? D.neg(d) : d, tolerance) <= 0);
    const rounding = diffs.filter(([, d]) => !D.isZero(d)).map(([n, d]) => `${n} ${D.fixed(d, 2)}`);
    // R-04 / R-03: groups read the pipeline's returns so credits follow their credit date (D-01a, D-09); lines shipped
    // before the window that only carry credits in it still form a row. Freight no line could carry is the explicit
    // UNALLOCATED row (unfiltered population only, as for the totals).
    const regions = new Map([...groupMetrics(pop.dimFacts, regionKey, pop.window, pop.result.returns, pop.active ? D.ZERO : pop.result.unallocatedFreight)]
      .filter(([, g]) => g.eligible_shipment_lines > 0 || g.merchandise_credits !== "0.00" || g.shipping_cost !== "0.00"));
    // The UNASSIGNED row is always explicit; with no such lines it is an honest zero-line row.
    if (!regions.has(UNASSIGNED_REGION)) regions.set(UNASSIGNED_REGION, computeMetrics([]));
    return { steps, arithmeticOk, rounding, regions };
  }, [pop]);

  const residual = pop.status === "ready" ? pop.result.metrics.allocation_residual : "0.00";
  const residualOk = D.isZero(D.parse(residual));
  const drillHref = (step: string, region?: string): string =>
    `${hrefFor("evidence")}${queryFor(pop.status === "ready" ? { ...pop.filters, ...(region ? { region } : {}) } : {}, { ...carriedParams(search), hl: step })}`;
  const open = (step: string): void => navigate(drillHref(step));

  return (
    <article>
      <div className="page-head">
        <p className="eyebrow">Margin bridge</p>
        <h1>From gross sales to contribution margin</h1>
        <p className="lede">Every step is a contract metric summed over the same shipment lines. Select a step to open the evidence ledger for this population with that step's columns highlighted.</p>
      </div>
      <DatasetBanner />
      {pop.status === "loading" && <Loading />}
      {pop.status === "error" && <ErrorState message={pop.error} onRetry={pop.retry} />}
      {pop.status === "ready" && (
        <>
          <Filters options={pop.options} />
          <PopulationSummary pop={pop} />
          {(pop.facts.length === 0 && pop.outside.length === 0) || !model ? <EmptyPopulation windowError={pop.windowError} /> : (
            <>
              <Waterfall
                id="bridge"
                title="Margin bridge, gross sales to contribution margin (USD)"
                caption={`USD, reporting currency. Population: ${pop.facts.length} shipment lines shipped in the window above, UTC; excludes quarantined lines. Deductions are shown negative. Synthetic data.`}
                steps={model.steps}
                onSelect={open}
                tableCaption="Bridge steps for the current filtered population, USD. Synthetic data."
                drill={(s) => (
                  <QueryLink to="evidence" filters={pop.filters} extra={{ hl: s.id }} className="drill" data-testid={`drill-${s.id}`}>
                    Open {s.id === "shipping_revenue" ? "ledger" : "ledger, highlight"}<span className="sr-only"> for {s.label}</span>
                  </QueryLink>
                )}
              />
              <p className="small" style={{ maxWidth: "none" }}>
                Definitions:
                {model.steps.map((s) => (s.metric ? <span key={s.id}> {s.short.replace(/^[−=+] /, "")}<MetricDefinition metric={s.metric} /></span> : null))}
              </p>
              <p className={`reconcile ${residualOk && model.arithmeticOk ? "ok" : "bad"}`} data-testid="reconcile" title="Allocation residual = declared shipping cost minus the sum of allocated freight, over every shipment in the published snapshot (D-04)">
                {residualOk && model.arithmeticOk ? "Steps reconcile: " : "Steps do NOT reconcile: "}
                allocation residual <span data-testid="residual">{residual}</span>
                {!model.arithmeticOk && "; the subtotals recomputed from the steps differ from the reported ones by more than rounding"}
                {model.arithmeticOk && model.rounding.length > 0 && (
                  <span className="muted" style={{ fontWeight: 400 }} data-testid="rounding-note"> (each step is rounded to cents on its own, so a subtotal can differ from the sum of the displayed steps by a cent: {model.rounding.join(", ")})</span>
                )}
              </p>
              {pop.outside.length > 0 && (
                <p className="small" style={{ maxWidth: "none" }} data-testid="credit-basis-note">
                  Merchandise credits follow their credit date (D-01a): this window includes {pop.outside.length} credits dated inside it for lines shipped earlier. The evidence ledger lists them as credit rows (D-09) and its totals equal this bridge.
                </p>
              )}
              <section aria-labelledby="by-region">
                <h2 id="by-region">By region</h2>
                <div className="tablewrap" tabIndex={0} role="region" aria-label="Contribution by region table">
                  <table data-testid="region-table">
                    <caption>Metrics by region for the current filtered population, USD. UNASSIGNED lines have no customer version effective at the shipment date; UNALLOCATED is freight no shipment line could carry (D-04). Credits sit in the region of their line and the month of their credit date (D-01a). Synthetic data.</caption>
                    <thead><tr><th scope="col">Region</th><th scope="col" className="num">Shipment lines</th><th scope="col" className="num">Net merchandise sales</th><th scope="col" className="num">Contribution margin</th><th scope="col" className="num">Rate</th></tr></thead>
                    <tbody>
                      {[...model.regions].map(([key, g]) => (
                        <tr key={key}>
                          <th scope="row">{key}</th>
                          <td className="num">{g.eligible_shipment_lines}</td>
                          <td className="num">{fmtMoney(g.net_merchandise_sales)}</td>
                          <td className={`num${g.contribution_margin.startsWith("-") ? " neg" : ""}`}>
                            {key === UNALLOCATED_GROUP || (g.eligible_shipment_lines === 0 && g.merchandise_credits === "0.00") ? fmtMoney(g.contribution_margin) : (
                              <a className="drill" href={drillHref("contribution", key)} data-testid={`region-link-${key}`} onClick={(e) => { if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); navigate(drillHref("contribution", key)); } }}>{fmtMoney(g.contribution_margin)}</a>
                            )}
                          </td>
                          <td className="num">{fmtRate(g.contribution_margin_rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </>
      )}
    </article>
  );
}
