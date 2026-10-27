import { LineSeries, Legend } from "../components/charts";
import { Link } from "../components/link";
import { Chip, Def, ExportButton, Fig, Related, Scroll, ScopeStrip, TableFold, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/models";
import { cmpFr, p6, parseFraction, ratio } from "../domain/num";
import { driftByRegion } from "../lib/derive";
import { day, n0, orDash } from "../lib/format";

export function MonitoringView() {
  return <WithData>{(ds) => <Monitoring ds={ds} />}</WithData>;
}

function Monitoring({ ds }: { ds: Dataset }) {
  const rows = ds.cutoffRows();
  const fresh = ds.primary.result["freshness"] as Row;
  const pubs = ds.primary.pubs;
  const drift = ds.aggregates ? (ds.aggregates["drift"] as Row) : null;
  const byCutoff = (drift?.["by_cutoff"] ?? []) as Row[];
  const recomputed = ds.testRows ? driftByRegion(ds.testRows, 4) : [];
  const testCuts: string[] = ds.testRows ? ((ds.populations.slice(1).map((p) => p.label.replace("Test cutoff ", "") + "T00:00:00Z"))) : [];
  const recomp = (at: string, k: "all_accounts" | "apac" | "other_regions"): string | null => { const i = testCuts.indexOf(at); return i < 0 ? null : recomputed[i]![k].psi; };
  const censored = rows.filter((r) => r.censored > 0);
  const last = byCutoff[byCutoff.length - 1];
  const worst = byCutoff.length ? byCutoff.reduce((a, b) => (cmpFr(parseFraction(b["apac"]["psi"]), parseFraction(a["apac"]["psi"])) > 0 ? b : a)) : null;
  const goldenSets = !drift ? Object.entries(ds.primary.result["cutoff_sets"] as Record<string, Row>).filter(([, s]) => s["population_drift"]) : [];
  return (
    <>
      <ViewHead mark="10 · Monitoring" title="Monitoring" contracts="P10-MET-10, P10-MET-11, P10-MET-12, P10-FLOW-10, D-02, D-03, D-05 (D-P10-10/12)">
        <p className="lede">After a model is in use: have the inputs moved, which cohorts can be judged yet, and how stale is the scoring? The population stability index is a diagnostic with a threshold of 0.2, not proof that anything is wrong.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["as of", fresh["as_of"]], ["drift feature", "usage_events_30d on bins 0, 1-2, 3+ (half-open)"], ["reference", drift ? String(drift["reference_prediction_at"]).slice(0, 10) : "2025-03-01 (golden)"], ["zero proportions", "floored to 0.0001, not renormalised"]]} />
      {drift ? (
        <section aria-labelledby="drift-h">
          <h2 id="drift-h">Drift by region: the whole population hides the apac cohort</h2>
          <p className="note" data-testid="hide-note">At the {String(last?.["prediction_at"]).slice(0, 10)} cutoff the whole population's usage PSI is <Fig k="psi-all-last">{last?.["all_accounts"]["psi"]}</Fig> and the other regions' <Fig k="psi-other-last">{last?.["other_regions"]["psi"]}</Fig>, both far below 0.2, while apac's is <Fig k="psi-apac-last" tone="neg">{last?.["apac"]["psi"]}</Fig> (peak <Fig k="psi-apac-max" tone="neg">{worst?.["apac"]["psi"]}</Fig> at {String(worst?.["prediction_at"]).slice(0, 10)}). apac is about {orDash(p6(ratio(last?.["apac"]["current_rows"] ?? 0, last?.["all_accounts"]["current_rows"] ?? 0)))} of the accounts; from 2026-03-31 the generator records only 40 % of apac logins (an instrumentation change, not a change in behaviour; see the manifest). Before the change apac spikes above 0.2 in some months too: its cohorts are small ({last?.["apac"]["reference_rows"]} reference rows, a few dozen per cutoff), so its PSI is noisy; the sustained level from 2026-05-01 is the signal. <Chip kind="note">designed in the synthetic world</Chip></p>
          <figure className="figure">
            <LineSeries labels={byCutoff.map((c) => String(c["prediction_at"]).slice(0, 7))} threshold="0.200000" testid="drift-chart" caption="Population stability index of usage_events_30d by cutoff for the whole population, the other regions and apac"
              series={[
                { key: "all", label: "whole population", color: "#f4ecdf", values: byCutoff.map((c) => c["all_accounts"]["psi"]), marks: byCutoff.map((c) => recomp(c["prediction_at"], "all_accounts") !== null) },
                { key: "other", label: "other regions", color: "#7fc8b8", values: byCutoff.map((c) => c["other_regions"]["psi"]), marks: byCutoff.map((c) => recomp(c["prediction_at"], "other_regions") !== null) },
                { key: "apac", label: "apac", color: "#ef7a6a", values: byCutoff.map((c) => c["apac"]["psi"]), marks: byCutoff.map((c) => recomp(c["prediction_at"], "apac") !== null) },
              ]} />
            <figcaption>PSI of each monthly cutoff against the 2026-02-01 cohort, 21 cutoffs. Dots mark the four test cutoffs, which this page recomputes from the test table and checks against the published series; the rest are the published figures from the full world. Unit: PSI (0 means no shift). The gold line is the 0.2 threshold.</figcaption>
          </figure>
          <Legend items={[{ label: "whole population", color: "#f4ecdf" }, { label: "other regions", color: "#7fc8b8" }, { label: "apac", color: "#ef7a6a" }]} />
          <TableFold summary="The same figures as a table">
            <Scroll label="PSI by cutoff and region">
              <table data-testid="drift-table">
                <caption>Against the 2026-02-01 cohort. "Recomputed" is this browser's figure from the test table (only the four test cutoffs); it must equal the published one.</caption>
                <thead><tr><th scope="col">Cutoff</th><th scope="col">Range</th><th scope="col">Whole population</th><th scope="col">Other regions</th><th scope="col">apac</th><th scope="col">apac mean usage</th><th scope="col">Recomputed here</th></tr></thead>
                <tbody>{byCutoff.map((c) => {
                  const ra = recomp(c["prediction_at"], "apac"), rl = recomp(c["prediction_at"], "all_accounts"), ro = recomp(c["prediction_at"], "other_regions");
                  return (
                    <tr key={c["prediction_at"]} data-cutoff={String(c["prediction_at"]).slice(0, 10)}>
                      <td className="l">{day(c["prediction_at"])}</td><td className="t">{c["range"]}</td><td data-k="all">{c["all_accounts"]["psi"]}</td><td data-k="other">{c["other_regions"]["psi"]}</td>
                      <td data-k="apac" className={c["apac"]["exceeds_threshold"] ? "neg" : ""}>{c["apac"]["psi"]} {c["apac"]["exceeds_threshold"] ? <Chip kind="risk">above 0.2</Chip> : null}</td><td>{c["apac"]["mean_usage_events_30d"]}</td>
                      <td className="t">{ra === null ? "—" : ra === c["apac"]["psi"] && rl === c["all_accounts"]["psi"] && ro === c["other_regions"]["psi"] ? <Chip kind="ok">equal</Chip> : <Chip kind="risk">differs</Chip>}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </Scroll>
            <p><ExportButton ds={ds} name="drift" scope="usage_events_30d PSI, published series" header={["prediction_at", "range", "psi_all", "psi_other_regions", "psi_apac", "apac_mean_usage"]} rows={byCutoff.map((c) => [c["prediction_at"], c["range"], c["all_accounts"]["psi"], c["other_regions"]["psi"], c["apac"]["psi"], c["apac"]["mean_usage_events_30d"]])} /></p>
          </TableFold>
        </section>
      ) : (
        <section aria-labelledby="drift-h">
          <h2 id="drift-h">Drift of the golden world</h2>
          <Scroll label="Golden drift">
            <table data-testid="drift-table"><caption>usage_events_30d against the reference cutoff 2025-03-01, floor 0.0001. A diagnostic, not proof.</caption>
              <thead><tr><th scope="col">Cutoff</th><th scope="col">Reference rows</th><th scope="col">Current rows</th><th scope="col">PSI</th><th scope="col">Above 0.2</th><th scope="col">Floored bins</th></tr></thead>
              <tbody>{goldenSets.map(([at, s]) => { const d = s["population_drift"]; return <tr key={at}><td className="l">{day(at)}</td><td>{d.reference_rows}</td><td>{d.current_rows}</td><td data-k="psi">{orDash(d.psi)}</td><td className="t">{d.exceeds_threshold ? <Chip kind="risk">yes</Chip> : <Chip kind="ok">no</Chip>}</td><td>{(d.bins as Row[]).filter((b) => b["floored"]).length}</td></tr>; })}</tbody>
            </table>
          </Scroll>
        </section>
      )}
      <section aria-labelledby="mat-h">
        <h2 id="mat-h">Maturity: which cohorts can be judged yet</h2>
        <p>Performance on a cohort is reported only once its rows are mature. The immature count is shown, never hidden: <Fig k="immature-rows">{n0(censored.reduce((s, r) => s + r.censored, 0))}</Fig> eligible rows in <Fig k="immature-cutoffs">{censored.length}</Fig> cutoffs are censored at <span className="mono">{ds.strip.as_of}</span>.</p>
        <Scroll label="Censored cutoffs">
          <table data-testid="maturity-table"><caption>Cutoffs with an open outcome window, and when each closes (label_end = horizon_end + grace).</caption>
            <thead><tr><th scope="col">Cutoff</th><th scope="col">Eligible rows</th><th scope="col">Censored</th><th scope="col">Evaluated (mature, scored)</th><th scope="col">Churn rate</th></tr></thead>
            <tbody>{censored.map((r) => <tr key={r.prediction_at}><td className="l">{day(r.prediction_at)}</td><td>{n0(r.eligible)}</td><td>{n0(r.censored)}</td><td>{n0(r.evaluated)}</td><td>{orDash(r.churn_rate, "censored")}</td></tr>)}{censored.length === 0 && <tr><td className="l" colSpan={5}>Every cutoff is mature.</td></tr>}</tbody>
          </table>
        </Scroll>
      </section>
      <section aria-labelledby="fresh-h">
        <h2 id="fresh-h">Freshness: two clocks</h2>
        <div className="grid" data-testid="freshness">
          <div className="card"><div className="big"><Fig k="scoring-hours">{fresh["scoring_hours"] === null ? "—" : n0(fresh["scoring_hours"])}</Fig><small>hours since the latest <em>completed</em> scoring publication ({String(fresh["latest_completed_publication_id"] ?? "none")}, {String(fresh["latest_completed_published_at"] ?? "—")})</small></div></div>
          <div className="card"><div className="big"><Fig k="data-hours">{fresh["data_hours"] === null ? "—" : n0(fresh["data_hours"])}</Fig><small>hours since the newest event became available ({String(fresh["latest_available_at"] ?? "—")})</small></div></div>
        </div>
        <p>The data can be an hour old while the scores are weeks old: the two are separate figures. <Def term="Definition">Scoring freshness = as_of − the latest completed scoring publication, whole hours, floored. Data freshness = as_of − the latest available_at ingested. A publication is completed only when every eligible account at its cutoff has a prediction.</Def></p>
        <Scroll label="Scoring publications">
          <table data-testid="publications"><caption>Scoring publications of the primary model, status derived from the predictions present.</caption>
            <thead><tr><th scope="col">Publication</th><th scope="col">Cutoff</th><th scope="col">Published</th><th scope="col">Eligible</th><th scope="col">Scored</th><th scope="col">Status</th></tr></thead>
            <tbody>{pubs.map((p) => <tr key={p.publication_id}><td className="l">{p.publication_id}</td><td>{day(p.prediction_at)}</td><td>{p.published_at}</td><td>{n0(p.eligible)}</td><td>{n0(p.scored)}</td><td className="t">{p.status === "completed" ? <Chip kind="ok">completed</Chip> : <Chip kind="risk">incomplete</Chip>}</td></tr>)}</tbody>
          </table>
        </Scroll>
      </section>
      <section aria-labelledby="miss-h">
        <h2 id="miss-h">Missing feature values</h2>
        <figure className="figure">
          <LineSeries labels={rows.filter((r) => r.eligible > 0).map((r) => r.prediction_at.slice(0, 7))} series={[{ key: "miss", label: "missing share", color: "#e3c58a", values: rows.filter((r) => r.eligible > 0).map((r) => r.missingness_overall) }]} caption="Share of eligible feature values that are missing, by cutoff" testid="missing-chart" />
          <figcaption>Missing eligible feature values ÷ eligible values (four features per row), by monthly cutoff. Mostly billing: an account with no billing event in 90 days has no total, which is missing, not zero.</figcaption>
        </figure>
      </section>
      <p className="note"><strong>Diagnostic, not proof.</strong> A PSI above 0.2 says an input moved; it does not say the model is wrong, and a PSI below 0.2 does not say it is right. The calibration gaps are on <Link to="calibration">the calibration lab</Link>.</p>
      <Related also={["features", "calibration"]} />
    </>
  );
}
