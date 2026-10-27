import { CutoffPicker, Chip, Choice, Def, Fig, Scroll, ViewHead, WithData, useCutoff } from "../components/ui";
import { ArmFunnel, VisitorFunnel } from "../components/charts";
import { Link } from "../components/link";
import type { Dataset } from "../data/dataset";
import { isoZ } from "../domain/time";
import { minus, n0, pp } from "../lib/format";
import { useParam } from "../router";

/** D-08: counts of the dated rows that exist in the file but are after the cutoff, so a run at that cutoff does not see them. */
export function laterRows(ds: Dataset, xv: string, cutoff: number): { assignments: number; assignedAll: number; exposures: number; subscriptions: number; observations: number } {
  const asg = ds.population.assignments.filter((a) => a.experiment_version_id === xv);
  const ids = new Set(asg.map((a) => a.assignment_id));
  return {
    assignments: asg.filter((a) => a.assigned_at > cutoff).length, assignedAll: asg.length,
    exposures: ds.population.exposures.filter((x) => ids.has(x.assignment_id) && x.exposed_at > cutoff).length,
    subscriptions: ds.population.subscriptions.filter((s) => s.starts_at > cutoff).length,
    observations: ds.population.metric_observations.filter((o) => ids.has(o.assignment_id) && o.window_end > cutoff).length,
  };
}

export function useVersion(ds: Dataset): [string, (v: string) => void] {
  const first = ds.versions[0]!.experiment_version_id;
  const [v, set] = useParam("xv", first);
  return [ds.versions.some((x) => x.experiment_version_id === v) ? v : first, set];
}

function Overview({ ds }: { ds: Dataset }) {
  const [cut, options, setCut] = useCutoff(ds);
  const [xv, setXv] = useVersion(ds);
  const comp = ds.at(cut.at, xv);
  const m = comp.metrics, ex = m.experiment!;
  const later = laterRows(ds, xv, cut.at);
  const blocked = ex.srm.verdict === "MISMATCH";
  const c = ex.primary.variants["control"], t = ex.primary.variants["treatment"];
  const g = ex.guardrail.by_variant, r = ex.revenue_per_assigned_account.by_variant;
  const rows: { id: string; name: string; key: string; value: React.ReactNode; basis: React.ReactNode }[] = [
    { id: "MET-01", name: "Signup conversion", key: "signup_conversion", value: m.signup_conversion.rate ?? "n/a", basis: `${n0(m.signup_conversion.signed_up)} of ${n0(m.signup_conversion.visitors)} visitors (distinct anonymous ids), window ${m.signup_conversion.window.from.slice(0, 10)} to ${m.signup_conversion.window.to.slice(0, 10)}` },
    { id: "MET-02", name: "Activation within 7 days", key: "activation", value: m.activation.rate ?? "n/a", basis: `${n0(m.activation.activated)} of ${n0(m.activation.mature_accounts)} mature signups; ${n0(m.activation.immature_excluded)} immature excluded and counted` },
    { id: "MET-03", name: "Funnel conversion, visit to activated", key: "funnel", value: m.funnel?.overall_conversion ?? "n/a", basis: m.funnel ? `${n0(m.funnel.steps[m.funnel.steps.length - 1]!.units)} of ${n0(m.funnel.steps[0]!.units)} visitors, strict order, gap up to ${m.funnel.max_gap_hours} h` : "no funnel defined" },
    { id: "MET-04", name: "Day-7 retention", key: "retention_day7", value: m.retention.day7.rate ?? "n/a", basis: `${m.retention.day7.retained} of ${m.retention.day7.mature_accounts} mature accounts, a session on exactly day 7 in the account's calendar; cohort ${m.retention.signup_window.from} to ${m.retention.signup_window.to}` },
    { id: "MET-05", name: "Week-4 retention", key: "retention_week4", value: m.retention.week4.rate ?? "n/a", basis: `${m.retention.week4.retained} of ${m.retention.week4.mature_accounts} mature accounts, a session on any of days 28 to 34; ${m.retention.week4.immature_excluded} immature` },
    { id: "MET-06", name: "Feature adoption (export)", key: "feature_adoption", value: m.feature_adoption.rate ?? "n/a", basis: `${m.feature_adoption.adopting_accounts} of ${m.feature_adoption.eligible_accounts} eligible active accounts (plans ${m.feature_adoption.eligible_plans.join(", ")})` },
    { id: "MET-07", name: "Activation lift, absolute", key: "lift_abs", value: blocked ? <Chip v="withheld">withheld: SRM MISMATCH</Chip> : pp(ex.primary.absolute_lift_pp), basis: blocked ? "shown in place of a lift (D-03)" : ex.primary.interval ? `treatment ${t?.conversion} vs control ${c?.conversion}; Newcombe [${minus(ex.primary.interval.low)}, ${minus(ex.primary.interval.high)}]` : "needs mature accounts in both arms" },
    { id: "MET-08", name: "Activation lift, relative", key: "lift_rel", value: blocked ? <Chip v="withheld">withheld</Chip> : ex.primary.relative_lift ?? "n/a", basis: "absolute ÷ control; null when the control rate is 0" },
    { id: "MET-09", name: "Exposure rate", key: "exposure", value: ex.exposure.overall.rate ?? "n/a", basis: `${n0(ex.exposure.overall.exposed)} of ${n0(ex.exposure.overall.units)} mature assigned accounts` },
    { id: "MET-10", name: "Sample ratio", key: "srm", value: <Chip v={ex.srm.verdict}>{ex.srm.verdict}</Chip>, basis: ex.srm.p_value === null ? "no assigned account by this cutoff" : `chi-square ${ex.srm.statistic}, p ${ex.srm.p_value}, observed ${Object.values(ex.srm.observed).join(" / ")}` },
    { id: "MET-11", name: "Guardrail error rate", key: "guardrail", value: `${g["control"]?.error_rate ?? "n/a"} / ${g["treatment"]?.error_rate ?? "n/a"}`, basis: `control ${g["control"]?.units_with_error}/${g["control"]?.eligible_units} · treatment ${g["treatment"]?.units_with_error}/${g["treatment"]?.eligible_units}, ${ex.guardrail.window_days}-day window` },
    { id: "MET-12", name: "Revenue per assigned account (USD)", key: "revenue", value: `${r["control"]?.mean ?? "n/a"} / ${r["treatment"]?.mean ?? "n/a"}`, basis: `control total ${r["control"]?.total} over ${r["control"]?.units} · treatment total ${r["treatment"]?.total} over ${r["treatment"]?.units}` },
  ];
  return (
    <>
      <ViewHead eyebrow="Journey overview" title="From first visit to activation">
        <p className="lede">Twelve metrics, one cutoff. A run at a cutoff sees only the facts that existed by it, so moving the cutoff back shows what a team looking at the data then would have seen.</p>
      </ViewHead>
      <div className="controls">
        <CutoffPicker options={options} value={cut.value} onChange={setCut} />
        <Choice name="xv" legend="Experiment version" value={xv} onChange={setXv} testid="version-picker" options={ds.versions.map((v) => ({ value: v.experiment_version_id, label: `${v.experiment_version_id}: ${v.name}` }))} />
      </div>
      <section className="block" data-testid="d08" data-cutoff={cut.value}>
        <h2>The cutoff rule (D-08)</h2>
        <p>At <span className="mono" data-k="cutoff">{isoZ(cut.at)}</span>, <Fig k="d08.assigned">{n0(ex.assigned_units)}</Fig> of the <Fig k="d08.assigned_all">{n0(later.assignedAll)}</Fig> accounts ever assigned in {xv} had been assigned
          {ex.srm.p_value !== null && <> (observed {Object.entries(ex.srm.observed).map(([k, v]) => `${k} ${v}`).join(", ")})</>}. Rows in the file dated after the cutoff are not counted by this run: <span className="mono" data-k="later">{later.assignments} assignments, {later.exposures} exposures, {later.subscriptions} subscriptions, {later.observations} observations</span>. A later cutoff includes them as a disclosed revision, as late events are.
          {" "}<Def term="what the rule covers">Assignments with assigned_at ≤ cutoff, exposures with exposed_at ≤ cutoff, subscriptions with starts_at ≤ cutoff (inside the revenue window), observations with window_end ≤ cutoff; events by received_at ≤ cutoff; sessions by started_at &lt; cutoff. The frozen plan and the logged runs are records of what was decided, not measurements, so they are not cut by instant.</Def></p>
        <p className="muted">{ex.run.analysis_id ? <>An analysis run is logged at this cutoff: <span className="mono">{ex.run.analysis_id}</span>, {ex.run.interim ? "an interim run" : "a final run"}, {ex.run.prior_runs} prior run{ex.run.prior_runs === 1 ? "" : "s"}.</> : <>No analysis run is logged at this cutoff: these are reads of the data, not a logged run ({ex.run.interim ? "before" : "after"} the planned end {isoZ(ds.plans.get(xv)!.planned_end)}).</>} Windows: {cut.at === ds.cutoff ? "the manifest's own" : "the defaults for this cutoff (7 days before for signup conversion, funnel and feature adoption, 28 days for activation, the seven local dates ending 35 days before for the retention cohort)"}.</p>
      </section>
      <div className="two">
        {m.funnel ? <VisitorFunnel funnel={m.funnel} signup={m.signup_conversion} /> : <p className="notice">No funnel definition is stored for this dataset.</p>}
        {blocked ? <section className="block block--withheld" data-testid="arm-funnel-withheld"><h3>Experiment funnel</h3><p className="callout callout--bad">Withheld for {xv}: the sample ratio check failed ({ex.srm.verdict}). The arms are not compared.</p></section> : ex.assigned_units === 0 ? <section className="block"><h3>Experiment funnel</h3><p className="muted">No account of {xv} had been assigned by this cutoff.</p></section> : <ArmFunnel ex={ex} />}
      </div>
      <section aria-labelledby="twelve">
        <h2 id="twelve">The twelve metrics</h2>
        <Scroll label="The twelve metrics">
          <table data-testid="metrics-table">
            <thead><tr><th scope="col">Metric</th><th scope="col">Name</th><th scope="col" className="num">Value</th><th scope="col">Basis</th></tr></thead>
            <tbody>{rows.map((x) => <tr key={x.id} data-metric={x.id} data-key={x.key}><th scope="row" className="mono">{x.id}</th><td>{x.name}</td><td className="num mono" data-k="value">{x.value}</td><td className="basis">{x.basis}</td></tr>)}</tbody>
          </table>
        </Scroll>
      </section>
      <p className="muted">Next: <Link to="funnel">the funnel with its exclusions</Link>, <Link to="cohorts">the cohort grid</Link>, <Link to="result">the experiment result</Link>.</p>
    </>
  );
}
export function OverviewView() { return <WithData>{(ds) => <Overview ds={ds} />}</WithData>; }
