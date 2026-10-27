import { ChurnColumns } from "../components/charts";
import { Link } from "../components/link";
import { Chip, Def, ExportButton, Fig, NoData, ParamSelect, Related, Scroll, ScopeStrip, TableFold, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { p6, ratio } from "../domain/num";
import { useParam } from "../router";
import { day, n0, orDash } from "../lib/format";

export function OverviewView() {
  return <WithData>{(ds) => <Overview ds={ds} />}</WithData>;
}

function Overview({ ds }: { ds: Dataset }) {
  const all = ds.cutoffRows();
  const published = new Map<string, string | null>(ds.aggregates ? (ds.aggregates["cutoffs"] as { prediction_at: string; churn_rate: string | null }[]).map((c) => [c.prediction_at, c.churn_rate]) : []);
  const [range, setRange] = useParam("range", "all");
  const ranges = ds.aggregates ? [...new Set(all.map((r) => r.range!))] : [];
  const options = [{ value: "all", label: "All cutoffs" }, ...ranges.map((r) => ({ value: r, label: `${r[0]!.toUpperCase()}${r.slice(1)} range` })), { value: "mature", label: "Mature only" }, { value: "censored", label: "Censored only" }];
  const valid = options.some((o) => o.value === range) ? range : "all";
  const shown = all.filter((r) => valid === "all" || r.range === valid || (valid === "mature" && r.mature > 0) || (valid === "censored" && r.censored > 0));
  const sum = (k: "eligible" | "mature" | "censored" | "churned" | "cutoff_rows"): number => shown.reduce((s, r) => s + r[k], 0);
  const lv = ds.inputs["label_version"] as { horizon_days: number; grace_days: number };
  const ineligible: Record<string, number> = {};
  for (const r of shown) for (const [k, v] of Object.entries(r.ineligible)) ineligible[k] = (ineligible[k] ?? 0) + v;
  const rate = p6(ratio(sum("churned"), sum("mature")));
  const share = p6(ratio(sum("censored"), sum("eligible")));
  const header = ["prediction_at", "range", "cutoff_rows", "eligible", "mature", "censored", "churned", "churn_rate", "late_events", "missingness"];
  const tableRows = shown.map((r) => [r.prediction_at, r.range, r.cutoff_rows, r.eligible, r.mature, r.censored, r.churned, r.churn_rate, r.late_total, r.missingness_overall]);
  return (
    <>
      <ViewHead mark="01 · Overview" title="Retention overview" contracts="P10-MET-01, P10-FLOW-02, P10-FLOW-10, D-01, D-05 (D-P10-01, D-P10-08)">
        <p className="lede">Which cohorts can be trusted yet? A cutoff is judged only once its outcome window has closed. Churn is the rate among those <em>mature</em> rows; the rest are censored and are never counted as accounts that stayed.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["population", ds.aggregates ? "all 2,400 accounts as built by the domain (aggregates)" : "the golden world"], ["window", `${day(all[0]?.prediction_at ?? ds.strip.as_of)} to ${day(all[all.length - 1]?.prediction_at ?? ds.strip.as_of)}, one cutoff a month (half-open)`], ["filter", options.find((o) => o.value === valid)!.label], ["as of", day(ds.strip.as_of)]]} />
      <section className="paper" data-testid="churn-definition" aria-labelledby="def-h">
        <h2 id="def-h">What counts as churn</h2>
        <p>An account <strong>churned</strong> at a cutoff when it has a <code>cancel</code> event with <code>prediction_at ≤ event_at &lt; horizon_end</code> that was available before <code>label_end</code>. The horizon is <Fig k="horizon">{lv.horizon_days}</Fig> days and the declared grace for late-arriving cancellations is <Fig k="grace">{lv.grace_days}</Fig> days, so <code>label_end = horizon_end + {lv.grace_days} days</code>.</p>
        <p>A row is <strong>mature</strong> only when <code>label_end ≤ as_of</code> (<span className="mono">{ds.strip.as_of}</span>). Otherwise it is <strong>censored</strong>: its outcome is unknown, it is excluded from every evaluation, and it is never labelled non-churn. <strong>Churn rate</strong> = mature eligible churned ÷ mature eligible accounts, a proportion with six places; with no mature rows it is unknown (shown as a dash), never 0. <Def term="Eligible">An account created before the observation window starts and active (latest visible subscription event is start or renew) at the cutoff.</Def></p>
      </section>
      <div className="controls">
        <ParamSelect name="range" label="Show" dflt="all" options={options} testid="range-filter" />
        <button type="button" className="button--quiet" onClick={() => setRange("all")} disabled={valid === "all"}>Clear the filter</button>
      </div>
      {shown.length === 0 ? <NoData what="cutoffs" onClear={() => setRange("all")} /> : (
        <>
          <div className="grid" data-testid="overview-figures">
            <div className="card"><div className="big"><Fig k="mature-churn">{orDash(rate)}</Fig><small>churn rate of {n0(sum("mature"))} mature eligible rows ({n0(sum("churned"))} churned)</small></div></div>
            <div className="card"><div className="big"><Fig k="censored-share">{orDash(share)}</Fig><small>of {n0(sum("eligible"))} eligible rows are censored ({n0(sum("censored"))}): outcome not yet known</small></div></div>
            <div className="card"><div className="big"><Fig k="excluded">{n0(Object.values(ineligible).reduce((a, b) => a + b, 0))}</Fig><small>cutoff rows not eligible: {Object.entries(ineligible).map(([k, v]) => `${v} ${k.replace(/_/g, " ").toLowerCase()}`).join("; ") || "none"}</small></div></div>
          </div>
          <figure className="figure">
            <ChurnColumns cols={shown.map((r) => ({ label: r.prediction_at.slice(0, 7), rate: r.churn_rate, eligible: r.eligible, mature: r.mature, censored: r.censored, range: r.range }))} caption={`Churn rate by monthly cutoff; ${n0(sum("censored"))} censored rows are hatched, not drawn as zero`} />
            <figcaption>Bars: churn rate of mature eligible rows per monthly cutoff (coral = the test range). Hatched columns: cutoffs whose outcome window has not closed; they have no rate, and they are {share} of all eligible rows. Unit: share of accounts, 0 to 1.</figcaption>
          </figure>
          <TableFold summary="The same figures as a table">
            <Scroll label="Churn by cutoff">
              <table data-testid="cutoff-table">
                <caption>One row per cutoff, ordered by prediction_at. The churn rate is recomputed here from the counts; the last column compares it with the published aggregate.</caption>
                <thead><tr><th scope="col">Cutoff (prediction_at)</th><th scope="col">Range</th><th scope="col">Eligible</th><th scope="col">Mature</th><th scope="col">Censored</th><th scope="col">Churned</th><th scope="col">Churn rate</th><th scope="col">Arrived late</th><th scope="col">Missing</th><th scope="col">Published</th></tr></thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.prediction_at} data-cutoff={r.prediction_at.slice(0, 10)}>
                      <td className="l">{day(r.prediction_at)}</td><td className="t">{r.range ?? "—"}</td><td>{n0(r.eligible)}</td><td>{n0(r.mature)}</td>
                      <td data-k="censored">{r.censored > 0 ? <Chip kind="hatch">{n0(r.censored)} censored</Chip> : 0}</td><td>{n0(r.churned)}</td>
                      <td data-k="rate">{orDash(r.churn_rate, "censored")}</td><td>{n0(r.late_total)}</td><td>{orDash(r.missingness_overall)}</td>
                      <td className="t">{published.size ? (published.get(r.prediction_at) === r.churn_rate ? <Chip kind="ok">matches</Chip> : <Chip kind="risk">differs</Chip>) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
            <p><ExportButton ds={ds} name="overview-cutoffs" scope={`range=${valid}`} header={header} rows={tableRows} /></p>
          </TableFold>
        </>
      )}
      <section>
        <h2>Reading this page</h2>
        <ul className="tight">
          <li>The churn rate is a ratio of counts on the same population; the six places are the published precision, not a claim of accuracy to that many digits.</li>
          <li>Rates are comparable across cutoffs only among mature rows. The last three cutoffs are censored, so the latest months say nothing about churn yet.</li>
          <li>The ranges (train, validation, test, outside) are chronological with a label-window purge; see <Link to="features">feature evidence</Link> and <Link to="models">the model comparison</Link> for what each range is used for.</li>
        </ul>
      </section>
      <Related also={["cohorts", "monitoring"]} />
    </>
  );
}
