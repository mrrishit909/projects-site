// SKU detail (P03-UI-02): one SKU at one location. The trajectory, the figures that make the draft order, the arithmetic
// line, and observed (censored) sales beside the latent demand.
import { useMemo } from "react";
import { Definition } from "../components/definition";
import { ScenarioBar, Select } from "../components/filters";
import { ViewHead } from "../components/layout";
import { Empty, Gate } from "../components/status";
import { DataTable } from "../components/table";
import { DemandChart, Trajectory } from "../components/trajectory";
import { censoredVsLatent } from "../domain/demand";
import { computeMetrics, pairSeries, paramOf } from "../domain/metrics";
import { dayOf, dayStr } from "../domain/time";
import { int, usd } from "../lib/format";
import type { Ready } from "../state/atlas";
import { useViewState } from "../state/filters";
import { useScenarioOf } from "../state/scenario";

export function Skus() {
  return <Gate>{(s) => <Body s={s} />}</Gate>;
}

const nz = (n: number | null): number => n ?? 0;

function Body({ s }: { s: Ready }) {
  const view = useViewState();
  const sc = useScenarioOf(s, view);
  const pop = s.result.population;
  const products = useMemo(() => [...pop.products].sort((a, b) => (a.product_id < b.product_id ? -1 : 1)), [pop]);
  const want = view.sku.toLowerCase();
  const prod = view.sku ? products.find((p) => p.product_id.toLowerCase() === want || p.sku.toLowerCase() === want) : products.find((p) => pop.replenishment_params.some((x) => x.product_id === p.product_id)) ?? products[0];
  const home = prod ? pop.replenishment_params.find((x) => x.product_id === prod.product_id)?.location_id : undefined;
  const locId = view.filters.loc && pop.locations.some((l) => l.location_id === view.filters.loc) ? view.filters.loc : home ?? pop.locations[0]?.location_id ?? "";
  const picker = (
    <section className="filters" aria-label="SKU and location">
      <div className="filters__grid">
        <Select id="sku-picker" label="SKU" all="Choose a SKU" value={prod?.product_id ?? ""} options={products.map((p) => ({ value: p.product_id, label: `${p.sku} · ${p.product_id}${p.abc_class ? ` · class ${p.abc_class}` : ""}` }))} onChange={(v) => view.set({ sku: v || null, loc: null })} />
        <Select id="loc-picker" label="Location" all="Home location" value={view.filters.loc} options={pop.locations.map((l) => ({ value: l.location_id, label: `${l.location_id} · ${l.location_name}` }))} onChange={(v) => view.set({ loc: v || null })} />
      </div>
    </section>
  );
  const head = <ViewHead eyebrow="P03-UI-02" title="SKU trajectory"><p className="lede">One SKU at one location: where stock stood, where the inventory position stood against the reorder point and target, and the draft order the arithmetic produces.</p></ViewHead>;
  if (!prod) return <article>{head}<ScenarioBar view={view} sc={sc} /><Empty title={view.sku ? `SKU ${view.sku} is not in the accepted population` : "No SKU in the accepted population"}>Pick a SKU from the list above.</Empty></article>;
  return (
    <article>
      {head}
      <ScenarioBar view={view} sc={sc} />
      {picker}
      <Detail s={s} sc={sc} productId={prod.product_id} locationId={locId} />
    </article>
  );
}

function Detail({ s, sc, productId, locationId }: { s: Ready; sc: ReturnType<typeof useScenarioOf>; productId: string; locationId: string }) {
  const pop = s.result.population;
  const prod = pop.products.find((p) => p.product_id === productId)!;
  const param = paramOf(pop, productId, locationId);
  const name = `${prod.sku} at ${locationId}`;
  const m = useMemo(() => computeMetrics(pop, sc.asOf, sc.window, sc.state, { products: new Set([productId]), locations: new Set([locationId]) }), [pop, sc.asOf, sc.window, sc.state, productId, locationId]);
  const series = useMemo(() => pairSeries(pop, productId, locationId, sc.minDay, sc.day, sc.state), [pop, sc.minDay, sc.day, sc.state, productId, locationId]);
  const cvl = useMemo(() => censoredVsLatent(pop.sales, pop.backorders, pop.lost_sales, pop.latent_demand, productId, locationId, sc.minDay, sc.day, sc.asOf), [pop, productId, locationId, sc.minDay, sc.day, sc.asOf]);
  const unmet = useMemo(() => {
    const out = new Map<number, number>();
    const add = (t: number, q: number): void => { const d = dayOf(t); out.set(d, (out.get(d) ?? 0) + q); };
    for (const b of pop.backorders) if (b.product_id === productId && b.location_id === locationId && b.opened_at <= sc.asOf) add(b.opened_at, b.quantity);
    for (const l of pop.lost_sales) if (l.product_id === productId && l.location_id === locationId && l.occurred_at <= sc.asOf) add(l.occurred_at, l.quantity);
    return out;
  }, [pop, productId, locationId, sc.asOf]);

  if (series.days.length === 0) return <Empty title="No days to show">The as-of date is before the first observed day.</Empty>;
  const at = (d: number): number => d - sc.minDay;
  const events = [
    ...series.receipts.map((r) => ({ key: r.receipt_id, day: r.day, kind: "Receipt", qty: `+${r.quantity}` })),
    ...series.stockout_days.map((d) => ({ key: `so-${d}`, day: d, kind: "Stockout day", qty: `${unmet.get(d) ?? 0} unmet` })),
  ].sort((a, b) => a.day - b.day || (a.kind < b.kind ? -1 : 1));
  const lastChart = Math.max(cvl.days.length - 120, 0);
  const chartDays = cvl.days.slice(lastChart);
  const censored = new Set(cvl.censoredDays);
  const shortfall = cvl.days.filter((d) => censored.has(d));
  const raw = m.raw_order, after = m.order_after_moq, qty = m.order_quantity;
  const evaluated = m.reorder_point !== null && m.target_position !== null;
  const arithmetic = !evaluated ? "No replenishment parameters exist for this SKU at this location: the order is not evaluated (not 0)."
    : m.reorder_triggered ? `raw ${raw} → MOQ ${prod.minimum_order_quantity}: ${after} → pack ${prod.pack_size}: ${qty}   (target ${m.target_position} − position ${m.inventory_position} = ${raw}; max(${raw}, ${prod.minimum_order_quantity}) = ${after}; ceil(${after} / ${prod.pack_size}) × ${prod.pack_size} = ${qty})`
    : `position ${m.inventory_position} ≥ reorder point ${m.reorder_point}: not triggered, so raw 0 → MOQ 0 → pack 0, draft 0`;
  const fig = (id: string, label: string, v: string | number | null, sub?: string) => (
    <div data-figure={id}><dt>{label}</dt><dd>{v === null ? "n/a" : v}</dd>{sub && <dd className="figures__sub">{sub}</dd>}</div>
  );
  return (
    <>
      <section aria-labelledby="fig-title">
        <h2 id="fig-title" className="section-title">{name} at {sc.text}</h2>
        <p className="small muted">{prod.sku} · unit cost {usd(prod.unit_cost)} · MOQ {prod.minimum_order_quantity} · pack {prod.pack_size}{prod.abc_class ? ` · class ${prod.abc_class}` : ""}{param ? "" : " · no replenishment parameters here"}</p>
        <dl className="figures" data-testid="sku-figures">
          {fig("on_hand", "On hand", m.on_hand)}
          {fig("on_order", "On order", m.on_order, "confirmed, open")}
          {fig("backorders", "Backorders", m.backorders, "open")}
          {fig("reserved", "Reserved", m.reserved)}
          {fig("available", "Available", m.available, "on hand − reserved")}
          {fig("position", "Position", m.inventory_position, "on hand + on order − backorders")}
          {fig("rop", "Reorder point", m.reorder_point)}
          {fig("target", "Target", m.target_position)}
          {fig("raw", "Raw", raw, "target − position")}
          {fig("after_moq", "After MOQ", after, "max(raw, MOQ)")}
          {fig("draft", "Draft order", qty, "rounded up to packs")}
        </dl>
        <p className="arithmetic" data-testid="arithmetic"><strong>Draft order, never a purchase order.</strong> <span className="mono">{arithmetic}</span></p>
        {m.negative_stock && <p className="notice notice--error" role="alert">NEGATIVE_STOCK: the reconstruction went below zero; stock is valued at zero.</p>}
      </section>

      <section aria-labelledby="traj-h">
        <h2 id="traj-h" className="section-title">Inventory trajectory</h2>
        <Trajectory series={series} rop={m.reorder_point} target={m.target_position} name={name} />
        <details className="definition" open={series.receipts.length + series.stockout_days.length <= 40}>
          <summary>Table of the marks: {series.receipts.length} receipts and {series.stockout_days.length} stockout days</summary>
          <DataTable caption={`Receipts and stockout days of ${name}`} testId="events-table" initialSort={{ id: "day", dir: "asc" }}
            columns={[
              { id: "day", label: "Day", value: (r) => dayStr(r.day) },
              { id: "kind", label: "Mark", value: (r) => r.kind },
              { id: "qty", label: "Units", value: (r) => r.qty, num: true },
              { id: "oh", label: "On hand (end of day)", value: (r) => series.on_hand[at(r.day)] ?? null, num: true },
              { id: "pos", label: "Position (end of day)", value: (r) => series.position[at(r.day)] ?? null, num: true },
            ]} rows={events} rowKey={(r) => r.key} empty="No receipts or stockout days in the window." />
        </details>
      </section>

      <section aria-labelledby="dem-h">
        <h2 id="dem-h" className="section-title">Observed sales and latent demand</h2>
        <p data-testid="censor-sentence">
          {cvl.hasLatent
            ? <>Shown: <strong>observed sales</strong> (filled bars) beside the generator's <strong>published latent demand</strong> (outlined bars). On the {shortfall.length} stockout days observed sales are censored, a floor on demand and not demand. Over the window: observed {int(cvl.observedTotal)} units, latent {int(cvl.latentTotal)} units.</>
            : <>Shown: <strong>observed sales only</strong>, which are censored on the {shortfall.length} stockout days (a floor on demand, not demand). The generator publishes no latent demand for this SKU, so true demand is not known here. Over the window: observed {int(cvl.observedTotal)} units.</>}
        </p>
        <DemandChart days={chartDays} observed={cvl.observed.slice(lastChart)} latent={cvl.latent.slice(lastChart)} stockoutDays={censored} name={name} />
        <p className="small muted">The chart shows the last {chartDays.length} days; the table lists every stockout day in the window.</p>
        <DataTable caption={`Stockout days of ${name}: observed against latent`} testId="censor-table" initialSort={{ id: "day", dir: "asc" }}
          columns={[
            { id: "day", label: "Stockout day", value: (r) => dayStr(r.day) },
            { id: "obs", label: "Observed sales", value: (r) => r.obs, num: true },
            { id: "lat", label: "Latent demand", value: (r) => r.lat, num: true },
            { id: "gap", label: "Latent − observed", value: (r) => (r.lat === null ? null : r.lat - r.obs), num: true },
            { id: "unmet", label: "Unmet recorded", value: (r) => r.unmet, num: true },
          ]}
          rows={shortfall.map((d) => ({ day: d, obs: cvl.observed[d - sc.minDay]!, lat: cvl.latent[d - sc.minDay] ?? null, unmet: nz(unmet.get(d) ?? null) }))}
          rowKey={(r) => String(r.day)} empty="No stockout days in the window." />
      </section>
      <Definition only={["On hand", "Inventory position", "Reorder, raw, MOQ, pack", "Stockout days"]} />
    </>
  );
}
