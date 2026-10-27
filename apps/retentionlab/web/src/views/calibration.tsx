import { useState, type KeyboardEvent } from "react";
import { Legend, ReliabilityChart } from "../components/charts";
import { Chip, Choice, Def, ExportButton, Fig, ParamSelect, Related, Scroll, ScopeStrip, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { blockOf, gapOfItems, groupGaps } from "../lib/derive";
import { n0, orDash, pp } from "../lib/format";
import { cohortRows, groupStats } from "../lib/cohort";
import { useParam } from "../router";

export function CalibrationView() {
  return <WithData>{(ds) => <Calibration ds={ds} />}</WithData>;
}

function Calibration({ ds }: { ds: Dataset }) {
  const [pid] = useParam("pop", ds.populations[0]!.id);
  const pop = ds.populations.find((p) => p.id === pid) ?? ds.populations[0]!;
  const [which, setWhich] = useParam("series", ds.primarySeries);
  const key = pop.models.some((m) => m.key === which) ? which : ds.primarySeries;
  const [zoom, setZoom] = useParam("axis", "auto");
  const series = pop.models.find((m) => m.key === key)!;
  const b = blockOf(series.items);
  const [active, setActive] = useState<number>(Math.max(0, b.bins.findIndex((x) => x.count > 0)));
  const bin = b.bins[active]!;
  const overall = b.n && series.role !== "baseline" ? gapOfItems(series.items) : null;
  const empty = b.bins.filter((x) => x.count === 0).length;
  const thin = b.bins.filter((x) => x.count > 0 && x.count < 30).length;
  const cal = ds.calibration;
  const onKey = (e: KeyboardEvent<HTMLTableRowElement>): void => {
    const next = e.key === "ArrowDown" ? Math.min(9, active + 1) : e.key === "ArrowUp" ? Math.max(0, active - 1) : e.key === "Home" ? 0 : e.key === "End" ? 9 : null;
    if (next === null) return;
    e.preventDefault();
    setActive(next);
    const row = (e.currentTarget.parentElement as HTMLElement).children[next] as HTMLElement | undefined;
    row?.focus();
  };
  const segs = ds.testRows && pop.id === "test" ? groupGaps(ds.testRows, "segment", key === "logistic_uncalibrated" ? "logistic_uncalibrated" : "logistic_calibrated") : null;
  const regs = ds.testRows && pop.id === "test" ? groupGaps(ds.testRows, "region", key === "logistic_uncalibrated" ? "logistic_uncalibrated" : "logistic_calibrated") : null;
  const goldenGroups = !ds.testRows ? { seg: groupStats(cohortRows(ds), "segment"), reg: groupStats(cohortRows(ds), "region") } : null;
  const readout = bin.count === 0
    ? `Bin ${bin.lower} to ${bin.upper}${bin.closed_upper ? " (closed)" : ""}: no rows. Observed rate and gap are unknown, not zero.`
    : `Bin ${bin.lower} to ${bin.upper}${bin.closed_upper ? " (closed)" : ""}: ${bin.count} rows, mean predicted ${bin.mean_predicted}, observed ${bin.observed_rate}, gap ${pp(bin.gap_pp)}.${bin.count < 30 ? " Few rows: read with care." : ""}`;
  const keyOptions = pop.models.filter((m) => m.role !== "baseline" || ds.id === "golden").map((m) => ({ value: m.key, label: m.label }));
  return (
    <>
      <ViewHead mark="05 · Calibration" title="Calibration lab" contracts="P10-MET-05, P10-MET-06, P10-FLOW-06, P10-TEST-11, D-02, D-03, D-05 (D-P10-11)">
        <p className="lede">When the model says 15 %, do 15 % of those accounts churn? The reliability curve answers that in ten bins of predicted risk, and the number of rows behind each point says how far to trust it.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["population", pop.detail], ["series", series.label], ["bins", "10 equal-width bins on [0, 1), the last closed"], ["calibration fitted on", cal ? `${n0(cal["fit_rows"])} retained validation rows (Platt); never on these rows` : "—"]]} />
      <div className="controls">
        <ParamSelect name="pop" label="Evaluation population" dflt={ds.populations[0]!.id} options={ds.populations.map((p) => ({ value: p.id, label: p.label }))} testid="pop-select" />
        {keyOptions.length > 1 && <Choice name="series" legend="Probabilities" options={keyOptions.map((o) => ({ value: o.value, label: o.value === "logistic_calibrated" ? "After Platt scaling" : o.value === "logistic_uncalibrated" ? "Before Platt scaling" : o.label }))} value={key} onChange={setWhich} testid="series-choice" />}
        <Choice name="axis" legend="Axis range" options={[{ value: "auto", label: "Zoom to the data" }, { value: "full", label: "Full 0 to 1" }]} value={zoom === "full" ? "full" : "auto"} onChange={setZoom} testid="axis-choice" />
      </div>
      <div className="grid" data-testid="calibration-figures">
        <div className="card"><div className="big"><Fig k="brier">{orDash(b.brier_score)}</Fig><small>Brier score on {n0(b.n)} rows</small></div></div>
        <div className="card"><div className="big"><Fig k="rows">{n0(b.n)}</Fig><small>rows, {n0(b.positives)} churned ({orDash(b.prevalence)})</small></div></div>
        <div className="card"><div className="big"><Fig k="empty-bins">{empty}</Fig><small>of 10 bins have no rows; {thin} more have fewer than 30</small></div></div>
        {overall && <div className="card"><div className="big"><Fig k="overall-gap" tone={overall.gap_pp?.startsWith("-") ? "neg" : undefined}>{pp(overall.gap_pp)}</Fig><small>mean predicted ({overall.mean_predicted}) minus observed ({overall.observed_rate})</small></div></div>}
      </div>
      <section aria-labelledby="curve-h">
        <h2 id="curve-h">Reliability curve with sample counts</h2>
        <div className="two">
          <figure className="figure">
            <ReliabilityChart bins={b.bins} active={active} onPick={setActive} zoom={zoom === "full" ? "full" : "auto"} caption={`Reliability curve of ${series.label}: observed churn against mean predicted risk in ten bins, with counts`} />
            <figcaption>
              Coral points: observed churn rate (y) against mean predicted risk (x) in each bin; the printed n and the point size are the rows behind it, and an open point has fewer than 30. The dashed teal diagonal is perfect calibration. The axis runs 0 to {zoom === "full" ? "1" : "a value fitted to the data (stated on the x axis)"}; switching the range does not change any figure. Below, the number of rows per bin.
            </figcaption>
            <Legend items={[{ label: "observed rate", color: "#ef7a6a" }, { label: "perfect calibration", color: "#7fc8b8", dash: true }]} />
          </figure>
          <div>
            <h3 style={{ marginTop: 0 }}>Selected bin</h3>
            <p className="readout" role="status" aria-live="polite" data-testid="bin-readout" data-bin={active}>{readout}</p>
            <p>Gap = (mean predicted − observed) × 100, in percentage points. Negative means the model under-predicts: more accounts churn than it said. A bin with no rows has no gap.</p>
            <p><Def term="Why a table next to a chart?">The table is the same data in reading order. Focus a row and use the arrow keys, Home and End to move between bins; the chart and the readout follow.</Def></p>
          </div>
        </div>
        <Scroll label="Reliability table">
          <table role="grid" aria-label="Reliability table: one row per bin" data-testid="reliability-table" aria-rowcount={10}>
            <caption>Ten bins of predicted risk. Use the arrow keys to move between rows.</caption>
            <thead><tr><th scope="col">Bin (predicted risk)</th><th scope="col">Rows</th><th scope="col">Mean predicted</th><th scope="col">Observed rate</th><th scope="col">Gap (pp)</th></tr></thead>
            <tbody>{b.bins.map((x) => (
              <tr key={x.index} role="row" tabIndex={x.index === active ? 0 : -1} aria-selected={x.index === active} className={x.count === 0 ? "is-empty" : ""} data-bin={x.index} onKeyDown={onKey} onClick={() => setActive(x.index)} onFocus={() => setActive(x.index)}>
                <td className="l" role="gridcell">{x.lower} to {x.upper}{x.closed_upper ? " (closed)" : ""}</td><td role="gridcell" data-k="count">{n0(x.count)}</td><td role="gridcell" data-k="mean">{orDash(x.mean_predicted, "no rows")}</td>
                <td role="gridcell" data-k="observed">{orDash(x.observed_rate, "no rows")}</td><td role="gridcell" data-k="gap" className={x.gap_pp?.startsWith("-") ? "neg" : ""}>{x.gap_pp === null ? "— (no rows)" : pp(x.gap_pp)}</td>
              </tr>
            ))}</tbody>
          </table>
        </Scroll>
        <p><ExportButton ds={ds} name="reliability" scope={`${pop.id}; ${key}`} header={["bin_lower", "bin_upper", "rows", "mean_predicted", "observed_rate", "gap_pp"]} rows={b.bins.map((x) => [x.lower, x.upper, x.count, x.mean_predicted, x.observed_rate, x.gap_pp])} /></p>
      </section>
      {cal && ds.id === "snapshot" && (
        <section className="paper" data-testid="platt" aria-labelledby="platt-h">
          <h2 id="platt-h">How the calibration was made, and what it was read on</h2>
          <p>Platt scaling maps the logistic model's log-odds <code>z</code> to <code>sigmoid(a·z + b)</code> with <code>a</code> = <Fig k="platt-a">{cal["a"]}</Fig> and <code>b</code> = <Fig k="platt-b">{cal["b"]}</Fig>. It was fitted on <Fig k="platt-fit">{n0(cal["fit_rows"])}</Fig> retained, mature <strong>validation</strong> rows; this curve is read on <Fig k="platt-eval">{n0(cal["evaluation_rows"])}</Fig> <strong>test</strong> rows. The two sets share no row, and a request that evaluates on its own fit rows is refused CALIBRATION_ON_FIT_ROWS. The fit set is small, so the mapping is noisy: <Chip kind="note">read with care</Chip>.</p>
          <p>Only the logistic model is calibrated. The random baseline's probabilities are uniform noise and the rule's are two numbers, so neither has a meaningful reliability curve.</p>
        </section>
      )}
      <section aria-labelledby="grp-h">
        <h2 id="grp-h">Where the calibration gap is largest</h2>
        {segs && regs ? (
          <div className="two two--even" data-testid="group-gaps">
            {([["By plan", segs, "segment"], ["By region", regs, "region"]] as const).map(([title, g, k]) => (
              <Scroll key={k} label={title}>
                <table data-testid={`gap-${k}`}><caption>{title}: mean predicted minus observed, percentage points, on {n0(b.n)} test rows.</caption>
                  <thead><tr><th scope="col">{k}</th><th scope="col">Rows</th><th scope="col">Observed</th><th scope="col">Predicted</th><th scope="col">Gap (pp)</th></tr></thead>
                  <tbody>{Object.entries(g).map(([name, x]) => <tr key={name} data-group={name}><td className="l">{name}</td><td>{n0(x.n)}</td><td>{orDash(x.observed_rate)}</td><td>{orDash(x.mean_predicted)}</td><td data-k="gap" className={x.gap_pp?.startsWith("-") ? "neg" : ""}>{pp(x.gap_pp)}</td></tr>)}</tbody></table>
              </Scroll>
            ))}
          </div>
        ) : goldenGroups ? (
          <p>The golden set has {n0(b.n)} rows; by plan: {goldenGroups.seg.map((s) => `${s.group} ${s.n} rows, gap ${pp(s.gap)}`).join("; ")}.</p>
        ) : <p>Group gaps are shown for the whole test range; pick it above.</p>}
        <p className="note"><strong>An unobserved cause.</strong> The starter plan's under-prediction comes from a repricing on 2026-02-01 that no feature sees, and apac's from a change in how logins are recorded. Recalibrating on the overall population would not fix either. <Chip kind="note">designed in the synthetic world, disclosed</Chip></p>
      </section>
      <Related also={["models", "cohorts"]} />
    </>
  );
}
