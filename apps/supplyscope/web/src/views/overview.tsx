// Planning overview (P03-UI-01): the as-of picker, the population figures, position against reorder point by location and
// supplier, and what ingest quarantined.
import { useMemo } from "react";
import { Definition } from "../components/definition";
import { ScenarioBar } from "../components/filters";
import { ViewHead } from "../components/layout";
import { DataTable, type Column } from "../components/table";
import { Gate } from "../components/status";
import { computeMetricsFull, groupMetrics, reorderRows, type PairRow } from "../domain/metrics";
import type { FullMetrics } from "../domain/types";
import { int, pct, usd } from "../lib/format";
import type { Ready } from "../state/atlas";
import { useViewState } from "../state/filters";
import { useScenarioOf } from "../state/scenario";

interface GroupRow { id: string; name: string; pairs: number; below: number; at: number; draft: number; m: FullMetrics }

export function Overview() {
  return <Gate>{(s) => <Body s={s} />}</Gate>;
}

function Body({ s }: { s: Ready }) {
  const view = useViewState();
  const sc = useScenarioOf(s, view);
  const pop = s.result.population;
  const all = useMemo(() => computeMetricsFull(pop, sc.asOf, sc.window, sc.state), [pop, sc.asOf, sc.window, sc.state]);
  const rows = useMemo(() => reorderRows(pop, sc.asOf, sc.state), [pop, sc.asOf, sc.state]);
  const byLocation = useMemo(() => groupMetrics(pop, "location", sc.asOf, sc.window, sc.state), [pop, sc.asOf, sc.window, sc.state]);
  const bySupplier = useMemo(() => groupMetrics(pop, "supplier", sc.asOf, sc.window, sc.state), [pop, sc.asOf, sc.window, sc.state]);
  const build = (groups: Map<string, FullMetrics>, names: Map<string, string>, pick: (r: PairRow) => string): GroupRow[] =>
    [...groups].map(([id, m]) => {
      const mine = rows.filter((r) => pick(r) === id);
      return { id, name: names.get(id) ?? id, pairs: mine.length, below: mine.filter((r) => r.triggered).length, at: mine.filter((r) => !r.triggered).length, draft: mine.reduce((a, r) => a + r.order_quantity, 0), m };
    });
  const locRows = build(byLocation, new Map(pop.locations.map((l) => [l.location_id, l.location_name])), (r) => r.location_id);
  const supRows = build(bySupplier, new Map(pop.suppliers.map((x) => [x.supplier_id, x.supplier_name])), (r) => r.supplier_id);
  const below = rows.filter((r) => r.triggered).length;
  const draftUnits = rows.reduce((a, r) => a + r.order_quantity, 0);
  const rejected = s.result.rejected;
  const columns = (kind: string): Column<GroupRow>[] => [
    { id: "group", label: kind, value: (r) => `${r.id} · ${r.name}` },
    { id: "pairs", label: "SKU x location rows", value: (r) => r.pairs, num: true },
    { id: "below", label: "Position below ROP", value: (r) => r.below, num: true },
    { id: "at", label: "At or above ROP", value: (r) => r.at, num: true },
    { id: "draft", label: "Draft units", value: (r) => r.draft, num: true, render: (r) => int(r.draft) },
    { id: "fill", label: "Fill rate", value: (r) => (r.m.fill_rate === null ? null : Number(r.m.fill_rate)), num: true, render: (r) => pct(r.m.fill_rate) },
    { id: "stockout", label: "Stockout SKU-days", value: (r) => (r.m.stockout_days === null ? null : Number(r.m.stockout_days)), num: true, render: (r) => pct(r.m.stockout_days) },
    { id: "capital", label: "Working capital", value: (r) => Number(r.m.working_capital), num: true, render: (r) => usd(r.m.working_capital) },
  ];
  const counts = [...Object.entries(s.result.ingest.counts), ...Object.entries(s.result.ingest.extraCounts)];
  return (
    <article>
      <ViewHead eyebrow="P03-UI-01" title="Planning overview">
        <p className="lede">Where the buying plan stands at the chosen date: service so far, stockout SKU-days (and, separately, stockout calendar days), capital tied up in stock, and how many SKU x location rows have fallen below their reorder point.</p>
      </ViewHead>
      <ScenarioBar view={view} sc={sc} />
      <section aria-labelledby="fig-title">
        <h2 id="fig-title" className="section-title">Population at {sc.text}</h2>
        <dl className="figures" data-testid="overview-figures">
          <div data-figure="fill_rate"><dt>Fill rate</dt><dd>{pct(all.fill_rate)}</dd><dd className="figures__sub">{int(all.fulfilled_units)} of {int(all.requested_units)} requested units</dd></div>
          <div data-figure="stockout_days"><dt>Stockout SKU-days</dt><dd>{pct(all.stockout_days)}</dd><dd className="figures__sub">{int(all.stockout_day_count)} of {int(all.observed_sku_days)} SKU-days (SKU x location x day)</dd></div>
          <div data-figure="stockout_calendar_days_share"><dt>Stockout calendar days</dt><dd>{pct(all.stockout_calendar_days_share)}</dd><dd className="figures__sub">of {int(all.observed_days)} calendar days, any SKU short</dd></div>
          <div data-figure="working_capital"><dt>Working capital</dt><dd>{usd(all.working_capital)}</dd><dd className="figures__sub">on hand x cost in force</dd></div>
          <div data-figure="below_rop"><dt>Position below ROP</dt><dd>{below} of {rows.length}</dd><dd className="figures__sub">SKU x location rows</dd></div>
          <div data-figure="draft_units"><dt>Draft units</dt><dd>{int(draftUnits)}</dd><dd className="figures__sub">recommendation, not an order</dd></div>
          <div data-figure="quarantined"><dt>Quarantined records</dt><dd>{rejected.length}</dd><dd className="figures__sub">rejected at ingest, kept raw</dd></div>
        </dl>
        <p className="small muted">Window: {new Date(sc.window[0]!).toISOString().slice(0, 10)} to {sc.text}. Rates are aggregated numerators over denominators, never averages of rates.</p>
      </section>
      <section aria-labelledby="loc-title">
        <h2 id="loc-title" className="section-title">Position against reorder point, by location</h2>
        <DataTable caption="By location" columns={columns("Location")} rows={locRows} rowKey={(r) => r.id} testId="by-location" />
      </section>
      <section aria-labelledby="sup-title">
        <h2 id="sup-title" className="section-title">Position against reorder point, by supplier</h2>
        <DataTable caption="By supplier" columns={columns("Supplier")} rows={supRows} rowKey={(r) => r.id} testId="by-supplier" />
      </section>
      <section aria-labelledby="q-title">
        <h2 id="q-title" className="section-title">Quarantine and rejections</h2>
        <p>Ingest checks every record before any figure is computed. A rejected record never enters a figure; its raw row is kept.</p>
        <DataTable caption="Rejected records" testId="rejected-table" columns={[
          { id: "entity", label: "Entity", value: (r) => r.entity },
          { id: "id", label: "Record id", value: (r) => r.id },
          { id: "reason", label: "Reason", value: (r) => r.reason_code },
          { id: "message", label: "Why", value: (r) => r.message, truncate: true },
        ]} rows={rejected} rowKey={(r) => `${r.entity}:${r.id}:${r.reason_code}`} empty="No record was rejected." />
        <details className="definition">
          <summary>Accepted and rejected records by entity</summary>
          <DataTable caption="Ingest counts" testId="ingest-counts" columns={[
            { id: "entity", label: "Entity", value: (r) => r[0] },
            { id: "accepted", label: "Accepted", value: (r) => r[1].accepted, num: true },
            { id: "rejected", label: "Rejected", value: (r) => r[1].rejected, num: true },
          ]} rows={counts} rowKey={(r) => r[0]} sortable={false} />
        </details>
      </section>
      <Definition only={["On hand", "Inventory position", "Fill rate", "Stockout days", "Stockout calendar days", "Working capital"]} />
    </article>
  );
}
