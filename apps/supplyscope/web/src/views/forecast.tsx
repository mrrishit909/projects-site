// Forecast evaluation (P03-UI-05): naive and seasonal-naive baselines against the EWMA model on rolling-origin folds.
// MAE and WAPE are exact; a fold or series whose actual demand is 0 has a null WAPE (an intermittent SKU), never 0.
import { useMemo } from "react";
import { Definition } from "../components/definition";
import { Select } from "../components/filters";
import { ViewHead } from "../components/layout";
import { Empty, Gate } from "../components/status";
import { DataTable, type Column } from "../components/table";
import { MODELS, type ModelName } from "../domain/contract";
import { DomainError } from "../domain/errors";
import { beats, datasetEnd, forecastDemand, maeOf, wapeOf, type FoldScore, type ForecastResult } from "../domain/forecast";
import { decStr, ratStr, type Rat } from "../domain/money";
import { dayEnd, dayOf, dayStr, tryParseDay } from "../domain/time";
import type { Ready } from "../state/atlas";
import { useViewState } from "../state/filters";

const NAMES: Record<ModelName, string> = { naive: "Naive", seasonal_naive: "Seasonal naive (7 days)", ewma: "Model (EWMA, alpha 0.3)" };
const SHORT: Record<ModelName, string> = { naive: "naive", seasonal_naive: "seasonal naive", ewma: "model" };
const HORIZON = 14;

/** A ratio to 4 places, or the word null (never 0, never blank). */
const r4 = (r: Rat | null): string => (r === null ? "null" : ratStr(r, 4)!);
const cell = (r: Rat | null, why: string) => (r === null ? <code className="null" title={why}>null</code> : r4(r));
const flag = (b: boolean | null): string => (b === null ? "not judged" : b ? "yes" : "no");

export function Forecast() {
  return <Gate>{(s) => <Body s={s} />}</Gate>;
}

interface Row { product_id: string; sku: string; location_id: string; abc: string; res: ForecastResult; published: string }

function Body({ s }: { s: Ready }) {
  const view = useViewState();
  const pop = s.result.population;
  const cutoffs = useMemo(() => [...new Set(pop.forecast_runs.map((r) => r.cutoff))].sort((a, b) => a - b), [pop]);
  const maxDay = dayOf(s.result.asOf);
  const asked = tryParseDay(view.cutoff);
  const cutoff = asked !== null && asked <= maxDay ? dayEnd(asked) : cutoffs.length ? cutoffs[cutoffs.length - 1]! : s.result.asOf;
  const notice = view.cutoff && (asked === null || asked > maxDay) ? `cutoff=${view.cutoff} is not a date inside the data; showing ${dayStr(dayOf(cutoff))}.` : null;
  const computed = useMemo(() => {
    try {
      const end = datasetEnd(pop.sales, pop.inventory_movements, pop.receipts);
      const published = new Map(pop.forecast_runs.filter((r) => r.cutoff === cutoff).map((r) => [`${r.product_id}\u0000${r.location_id}`, r.selected_model]));
      const prods = new Map(pop.products.map((p) => [p.product_id, p]));
      const rows: Row[] = pop.replenishment_params.map((p) => ({
        product_id: p.product_id, sku: prods.get(p.product_id)!.sku, location_id: p.location_id, abc: prods.get(p.product_id)!.abc_class ?? "",
        res: forecastDemand(pop.sales, pop.promotions, p.product_id, p.location_id, cutoff, HORIZON, end), published: published.get(`${p.product_id}\u0000${p.location_id}`) ?? "",
      }));
      return { rows, error: null as string | null };
    } catch (e) {
      return { rows: [] as Row[], error: e instanceof DomainError ? e.message : String(e) };
    }
  }, [pop, cutoff]);
  const rows = computed.rows;
  const sel = rows.find((r) => r.product_id === view.sku) ?? rows[0];

  const wapeCol = (m: ModelName): Column<Row> => ({ id: `wape_${m}`, label: `WAPE ${SHORT[m]}`, value: (r) => { const w = wapeOf(r.res.evals[m]); return w === null ? null : Number(ratStr(w, 6)); }, num: true, render: (r) => cell(wapeOf(r.res.evals[m]), "the actual demand over all folds sums to 0") });
  const maeCol = (m: ModelName): Column<Row> => ({ id: `mae_${m}`, label: `MAE ${SHORT[m]}`, value: (r) => { const w = maeOf(r.res.evals[m]); return w === null ? null : Number(ratStr(w, 6)); }, num: true, render: (r) => cell(maeOf(r.res.evals[m]), "no fold could be scored") });
  const columns: Column<Row>[] = [
    { id: "sku", label: "SKU", value: (r) => r.sku, render: (r) => <button type="button" className="linklike" onClick={() => view.set({ sku: r.product_id })} aria-label={`Show folds of ${r.sku}`}>{r.sku}</button> },
    { id: "loc", label: "Location", value: (r) => r.location_id },
    { id: "abc", label: "Class", value: (r) => r.abc },
    { id: "hist", label: "History (days)", value: (r) => r.res.history_days, num: true },
    { id: "folds", label: "Folds", value: (r) => r.res.evals.naive.folds, num: true },
    { id: "zero", label: "Zero-demand folds", value: (r) => r.res.evals.naive.zero_demand_folds, num: true },
    ...MODELS.map(wapeCol), ...MODELS.map(maeCol),
    { id: "beats", label: "Model beats seasonal naive", value: (r) => flag(r.res.beats_baseline.ewma) },
    { id: "selected", label: "Selected", value: (r) => r.res.selected_model },
    { id: "published", label: "Published run selected", value: (r) => r.published || null },
  ];

  return (
    <article>
      <ViewHead eyebrow="P03-UI-05" title="Forecast evaluation">
        <p className="lede">Baselines first: naive and seasonal naive are always scored. A model counts only if it beats seasonal naive on the same rolling folds, each trained only on what was known at that fold's cutoff. WAPE is null, never 0, where the actual demand is 0.</p>
      </ViewHead>
      <section className="filters" aria-label="Forecast cutoff">
        <div className="filters__grid">
          <Select id="cutoff" label="Forecast cutoff (UTC day, whole day known)" all="Latest published" value={view.cutoff && asked !== null && asked <= maxDay ? view.cutoff : ""}
            options={cutoffs.map((c) => ({ value: dayStr(dayOf(c)), label: dayStr(dayOf(c)) }))} onChange={(v) => view.set({ cutoff: v || null })} />
        </div>
        <p className="small muted">Cutoff {dayStr(dayOf(cutoff))}: folds are 7 days long, step 7, with at least 14 days of history; the horizon is {HORIZON} days.</p>
        {notice && <p className="notice notice--error" role="alert">{notice}</p>}
      </section>
      {computed.error && <Empty title="No forecast at this cutoff"><p>{computed.error}</p></Empty>}
      {sel && (
        <>
          <Detail row={sel} />
          <section aria-labelledby="all-h">
            <h2 id="all-h" className="section-title">Every SKU at {dayStr(dayOf(cutoff))}</h2>
            <DataTable caption="Baselines and model by SKU x location" columns={columns} rows={rows} rowKey={(r) => `${r.product_id}:${r.location_id}`} testId="forecast-table" initialSort={{ id: "sku", dir: "asc" }} />
            <p className="small muted">MAE and WAPE are over all folds of the series. Published run: the model the generator's forecast run recorded as selected, shown beside the one computed here.</p>
          </section>
        </>
      )}
      <Definition only={["MAE and WAPE", "Beats baseline"]} />
    </article>
  );
}

function Detail({ row }: { row: Row }) {
  const { res } = row;
  const evals = res.evals;
  const base = evals.seasonal_naive;
  const modelRows = MODELS.map((m) => ({ m, e: evals[m] }));
  const folds = evals.naive.fold_scores.map((f, i) => ({ f, byModel: MODELS.map((m) => evals[m].fold_scores[i]!) }));
  return (
    <section aria-labelledby="det-h" data-testid="forecast-detail">
      <h2 id="det-h" className="section-title">{row.sku} at {row.location_id}</h2>
      <p className="small muted">{res.history_days} days of history before the cutoff; {evals.naive.folds} rolling folds, {evals.naive.zero_demand_folds} of them with zero actual demand{res.notes.length ? ` · ${res.notes.join(", ")}` : ""}.</p>
      <DataTable caption={`Baselines and model, ${row.sku}`} testId="models-table" sortable={false} rowKey={(r) => r.m}
        columns={[
          { id: "model", label: "Model", value: (r) => NAMES[r.m] },
          { id: "folds", label: "Folds", value: (r) => r.e.folds, num: true },
          { id: "zero", label: "Zero-demand folds", value: (r) => r.e.zero_demand_folds, num: true },
          { id: "actual", label: "Actual units", value: (r) => r.e.actual, num: true },
          { id: "abs", label: "Sum |error|", value: (r) => decStr(r.e.abs_error, 2), num: true },
          { id: "mae", label: "MAE", value: (r) => r4(maeOf(r.e)), num: true },
          { id: "wape", label: "WAPE", value: (r) => r4(wapeOf(r.e)), num: true, render: (r) => cell(wapeOf(r.e), "the actual demand sums to 0") },
          { id: "beats", label: "Beats baseline", value: (r) => (r.m === "ewma" ? `${flag(beats(r.e, base))} (vs seasonal naive)` : "baseline"), render: (r) => <span data-testid={`beats-${r.m}`}>{r.m === "ewma" ? `${flag(beats(r.e, base))} (vs seasonal naive)` : "baseline"}</span> },
        ]} rows={modelRows} />
      <p className="small muted">Selected for this SKU: <strong>{res.selected_model.replace("_", " ")}</strong>. The model's promotion adjustment multiplies its level by the planned uplift ratio exactly as the Python reference does.</p>
      <details className="definition" open>
        <summary>Fold errors: {folds.length} rolling folds</summary>
        {folds.length === 0 ? <Empty title="No rolling fold">Fewer than 21 days of history: nothing can be scored, so no error is shown.</Empty> : (
          <DataTable caption={`Fold errors of ${row.sku}`} testId="folds-table" rowKey={(r) => String(r.f.fold)} initialSort={{ id: "fold", dir: "asc" }}
            columns={[
              { id: "fold", label: "Fold", value: (r) => r.f.fold, num: true },
              { id: "start", label: "First forecast day", value: (r) => dayStr(r.f.start) },
              { id: "actual", label: "Actual units", value: (r) => r.f.actual, num: true },
              ...MODELS.flatMap((m, k): Column<{ f: FoldScore; byModel: FoldScore[] }>[] => [
                { id: `mae_${m}`, label: `MAE ${SHORT[m]}`, value: (r) => Number(ratStr(r.byModel[k]!.mae, 6)), num: true, render: (r) => r4(r.byModel[k]!.mae) },
                { id: `wape_${m}`, label: `WAPE ${SHORT[m]}`, value: (r) => (r.byModel[k]!.wape === null ? null : Number(ratStr(r.byModel[k]!.wape, 6))), num: true, render: (r) => cell(r.byModel[k]!.wape, "the fold's actual demand is 0") },
              ]),
            ]} rows={folds} />
        )}
      </details>
    </section>
  );
}
