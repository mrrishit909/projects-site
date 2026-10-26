// P01-UI-02 Executive overview: monthly net merchandise sales and contribution margin, explicit date basis.
import { useMemo } from "react";
import { LineChart } from "../components/charts/line-chart";
import { DatasetBanner, EmptyPopulation, Filters, PopulationSummary, QueryLink } from "../components/filters";
import { fmtMoney, fmtRate, monthLabel, monthRange, toNumber } from "../components/format";
import { MetricDefinition } from "../components/metric-definition";
import { ErrorState, Loading } from "../components/status";
import { NO_WINDOW, computeMetrics, groupMetrics } from "../domain/metrics";
import { usePopulation } from "../state/filters";

const BREAK = "2026-01"; // the generator's cost-version change (data/injection-manifest.json), used only to split the comparison

export function Overview() {
  const pop = usePopulation();
  const data = useMemo(() => {
    if (pop.status !== "ready" || pop.facts.length === 0) return null;
    const groups = groupMetrics(pop.facts, (f) => f.shipped_date.slice(0, 7), NO_WINDOW);
    const keys = [...groups.keys()];
    const months = monthRange(keys[0]!, keys[keys.length - 1]!);
    const before = pop.facts.filter((f) => f.shipped_date.slice(0, 7) < BREAK);
    const after = pop.facts.filter((f) => f.shipped_date.slice(0, 7) >= BREAK);
    return {
      months,
      groups,
      rateBefore: before.length ? computeMetrics(before).contribution_margin_rate : null,
      rateAfter: after.length ? computeMetrics(after).contribution_margin_rate : null,
      hasSplit: before.length > 0 && after.length > 0,
    };
  }, [pop]);

  return (
    <article>
      <div className="page-head">
        <p className="eyebrow">Executive overview</p>
        <h1>Is contribution margin keeping up with sales?</h1>
        <p className="lede">Monthly net merchandise sales and contribution margin for the filtered population. Every figure is recomputed in your browser from the published synthetic snapshot.</p>
      </div>
      <DatasetBanner />
      {pop.status === "loading" && <Loading />}
      {pop.status === "error" && <ErrorState message={pop.error} onRetry={pop.retry} />}
      {pop.status === "ready" && (
        <>
          <Filters options={pop.options} />
          <PopulationSummary pop={pop} />
          {pop.facts.length === 0 || !data ? <EmptyPopulation windowError={pop.windowError} /> : (
            <>
              <div className="actions">
                <QueryLink to="bridge" filters={pop.filters} className="btn btn--primary" data-testid="open-bridge">Open the margin bridge</QueryLink>
                <span className="small muted">Totals for this population: net merchandise sales {fmtMoney(pop.metrics.net_merchandise_sales)} USD<MetricDefinition metric="net_merchandise_sales" />, contribution margin {fmtMoney(pop.metrics.contribution_margin)} USD<MetricDefinition metric="contribution_margin" />.</span>
              </div>
              <LineChart
                id="trend"
                title="Net merchandise sales and contribution margin by shipment month (USD)"
                caption={`USD, reporting currency. Population: ${pop.facts.length} shipment lines, shipment date in UTC, months as [start, next start). ${data.months.length} months, ${monthLabel(data.months[0]!)} to ${monthLabel(data.months[data.months.length - 1]!)}. Synthetic data.`}
                categories={data.months}
                tickLabels={data.months.map((m) => monthLabel(m).replace(/ 20(\d\d)$/, " ’$1"))}
                marker={data.months.includes(BREAK) ? { index: data.months.indexOf(BREAK), label: "2026-01 cost change" } : null}
                series={[
                  { id: "net", label: "Net merchandise sales", color: "#161a22", values: data.months.map((m) => (data.groups.has(m) ? toNumber(data.groups.get(m)!.net_merchandise_sales) : null)) },
                  { id: "cm", label: "Contribution margin", color: "#b1652c", dash: "6 4", values: data.months.map((m) => (data.groups.has(m) ? toNumber(data.groups.get(m)!.contribution_margin) : null)) },
                ]}
                tableCaption="Monthly metrics, USD. Shipment month in UTC; months with no shipments show n/a. Synthetic data."
                tableHeaders={["Shipment month (UTC)", "Net merchandise sales", "Contribution margin", "Contribution margin rate", "Shipment lines"]}
                tableRows={data.months.map((m) => {
                  const g = data.groups.get(m);
                  return g ? [m, fmtMoney(g.net_merchandise_sales), fmtMoney(g.contribution_margin), fmtRate(g.contribution_margin_rate), String(g.eligible_shipment_lines)] : [m, "n/a", "n/a", "n/a", "0"];
                })}
              />
              {data.hasSplit && (
                <p data-testid="rate-comparison" style={{ maxWidth: "none" }}>
                  <strong>Contribution margin rate</strong><MetricDefinition metric="contribution_margin_rate" />: {fmtRate(data.rateBefore)} for shipments before {BREAK}, {fmtRate(data.rateAfter)} from {BREAK} on, in this population.
                  {" "}The break at {BREAK} is where the generator raises unit costs on one category (see the <a href={`${import.meta.env.BASE_URL}data/injection-manifest.json`}>injection manifest</a>); it is a designed relationship in synthetic data, not a finding about a real business.
                </p>
              )}
            </>
          )}
        </>
      )}
    </article>
  );
}
