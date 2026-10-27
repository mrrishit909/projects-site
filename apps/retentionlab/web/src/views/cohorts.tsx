import { HBars, Legend, type BarRow } from "../components/charts";
import { Chip, ExportButton, NoData, ParamSelect, Related, Scroll, ScopeStrip, TableFold, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { cohortRows, groupStats, overallStat, tenureStats, type GroupStat } from "../lib/cohort";
import { n0, orDash, pp } from "../lib/format";
import { useParam } from "../router";

export function CohortsView() {
  return <WithData>{(ds) => <Cohorts ds={ds} />}</WithData>;
}

function GroupTable({ title, stats, k }: { title: string; stats: GroupStat[]; k: string }) {
  return (
    <Scroll label={title}>
      <table data-testid={`cohort-${k}`}>
        <caption>{title}. Observed = share who churned; predicted = mean of the model's risk; gap = predicted minus observed in percentage points (negative: the model under-predicts).</caption>
        <thead><tr><th scope="col">{k === "cut" ? "Cutoff" : k === "segment" ? "Plan (segment)" : "Region"}</th><th scope="col">Rows</th><th scope="col">Churned</th><th scope="col">Observed</th><th scope="col">Predicted</th><th scope="col">Gap</th></tr></thead>
        <tbody>{stats.map((s) => (
          <tr key={s.group} data-group={s.group}><td className="l">{s.group}</td><td>{n0(s.n)}</td><td>{n0(s.churned)}</td><td data-k="observed">{orDash(s.rate)}</td><td data-k="predicted">{orDash(s.mean)}</td><td data-k="gap" className={s.gap?.startsWith("-") ? "neg" : ""}>{pp(s.gap)}</td></tr>
        ))}</tbody>
      </table>
    </Scroll>
  );
}

function Cohorts({ ds }: { ds: Dataset }) {
  const rows = cohortRows(ds);
  const [seg, setSeg] = useParam("segment", "all");
  const [reg, setReg] = useParam("region", "all");
  const [cut, setCut] = useParam("cutoff", "all");
  const segs = [...new Set(rows.map((r) => r.segment))].sort(), regs = [...new Set(rows.map((r) => r.region))].sort(), cuts = [...new Set(rows.map((r) => r.cut))].sort();
  const sel = (v: string, all: string[]): string => (v === "all" || all.includes(v) ? v : "all");
  const [s, r, c] = [sel(seg, segs), sel(reg, regs), sel(cut, cuts)];
  const shown = rows.filter((x) => (s === "all" || x.segment === s) && (r === "all" || x.region === r) && (c === "all" || x.cut === c));
  const clear = (): void => { setSeg("all"); setReg("all"); setCut("all"); };
  const bySeg = groupStats(shown, "segment"), byReg = groupStats(shown, "region"), all = overallStat(shown);
  const barRows = (st: GroupStat[]): BarRow[] => st.flatMap((x) => [
    { label: `${x.group} observed`, value: x.rate, tone: "coral" as const, note: `n=${x.n}` }, { label: `${x.group} predicted`, value: x.mean, tone: "teal" as const },
  ]);
  const ten = tenureStats(ds);
  const exportRows = [...bySeg.map((x) => ["segment", x.group, x.n, x.churned, x.rate, x.mean, x.gap]), ...byReg.map((x) => ["region", x.group, x.n, x.churned, x.rate, x.mean, x.gap])];
  return (
    <>
      <ViewHead mark="02 · Cohorts" title="Cohort explorer" contracts="P10-MET-01, P10-MET-06, D-03, D-05">
        <p className="lede">Plan and tenure context: who churns, and whether the model expected it. The rows are the mature, eligible, scored accounts of {ds.testRows ? "the four test cutoffs" : "the golden set"}; every group shows how many rows it rests on.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["population", `${n0(rows.length)} mature eligible rows with a prediction`], ["filters", `plan ${s}, region ${r}, cutoff ${c}`], ["rows shown", n0(shown.length)]]} />
      <div className="controls">
        <ParamSelect name="segment" label="Plan (segment)" dflt="all" options={[{ value: "all", label: "All plans" }, ...segs.map((x) => ({ value: x, label: x }))]} testid="filter-segment" />
        <ParamSelect name="region" label="Region" dflt="all" options={[{ value: "all", label: "All regions" }, ...regs.map((x) => ({ value: x, label: x }))]} testid="filter-region" />
        <ParamSelect name="cutoff" label="Cutoff" dflt="all" options={[{ value: "all", label: "All cutoffs" }, ...cuts.map((x) => ({ value: x, label: x }))]} testid="filter-cutoff" />
        <button type="button" className="button--quiet" onClick={clear} disabled={s === "all" && r === "all" && c === "all"}>Clear the filters</button>
      </div>
      {shown.length === 0 ? <NoData what="rows" onClear={clear} /> : (
        <>
          <div className="grid">
            <div className="card"><div className="big"><span data-figure="cohort-rows">{n0(all.n)}</span><small>rows in scope, {n0(all.churned)} churned</small></div></div>
            <div className="card"><div className="big"><span data-figure="cohort-observed">{orDash(all.rate)}</span><small>observed churn rate</small></div></div>
            <div className="card"><div className="big"><span data-figure="cohort-predicted">{orDash(all.mean)}</span><small>mean predicted risk</small></div></div>
            <div className="card"><div className="big"><span data-figure="cohort-gap" className={all.gap?.startsWith("-") ? "neg" : ""}>{pp(all.gap)}</span><small>predicted minus observed</small></div></div>
          </div>
          <div className="two two--even">
            <figure className="figure">
              <h2 style={{ marginTop: 0 }}>By plan</h2>
              <HBars rows={barRows(bySeg)} caption="Observed and predicted churn by plan" testid="segment-chart" />
              <figcaption>Observed churn (coral) against the model's mean predicted risk (teal) for each plan; the scale starts at 0. Unit: share of accounts.</figcaption>
            </figure>
            <figure className="figure">
              <h2 style={{ marginTop: 0 }}>By region</h2>
              <HBars rows={barRows(byReg)} caption="Observed and predicted churn by region" testid="region-chart" />
              <figcaption>A group with few rows (n shown) moves a lot with one account.</figcaption>
            </figure>
          </div>
          <Legend items={[{ label: "observed", color: "#ef7a6a" }, { label: "predicted (mean risk)", color: "#7fc8b8" }]} />
          <TableFold summary="The same figures as tables">
            <GroupTable title="By plan" stats={bySeg} k="segment" />
            <GroupTable title="By region" stats={byReg} k="region" />
            <p><ExportButton ds={ds} name="cohorts" scope={`segment=${s}; region=${r}; cutoff=${c}`} header={["dimension", "group", "rows", "churned", "observed", "predicted", "gap_pp"]} rows={exportRows} /></p>
          </TableFold>
        </>
      )}
      <section className="panel" data-testid="tenure" aria-labelledby="tenure-h">
        <h2 id="tenure-h">Tenure <Chip kind="hatch">published cohort sample, not the population</Chip></h2>
        <p>Account creation dates are published for the {n0(ds.primary.world.accounts.size)}-account cohort only, so tenure at the cutoff is read there: mature eligible rows of every cutoff, grouped by how long the account had existed. Unaffected by the filters above.</p>
        <Scroll label="Churn by tenure at the cutoff">
          <table>
            <caption>Tenure = whole days from creation to the cutoff. Eligible rows include censored ones; the rate uses mature rows only.</caption>
            <thead><tr><th scope="col">Tenure at the cutoff</th><th scope="col">Eligible rows</th><th scope="col">Mature</th><th scope="col">Churned</th><th scope="col">Churn rate</th></tr></thead>
            <tbody>{ten.map((t) => <tr key={t.band} data-band={t.band}><td className="l">{t.band}</td><td>{n0(t.eligible)}</td><td>{n0(t.n)}</td><td>{n0(t.churned)}</td><td data-k="rate">{orDash(t.rate, "no mature rows")}</td></tr>)}</tbody>
          </table>
        </Scroll>
      </section>
      <p className="note"><strong>No causal reading.</strong> A group with a higher churn rate is a group to look at, not a group that an offer would keep. The gap column is the model's calibration error for that group, not its fault or its cause.</p>
      <Related also={["calibration", "overview"]} />
    </>
  );
}
