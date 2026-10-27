// One analysis run of the experiment, in the order the contract requires: the sample ratio first, then (only when it can be trusted)
// the lift with its interval, then the guardrail and revenue.
import type { Dataset } from "../data/dataset";
import { guardrailReview, type ExperimentOut } from "../domain/metrics";
import type { AnalysisRun } from "../domain/models";
import { isoZ } from "../domain/time";
import { minus, n0, pct, pp } from "../lib/format";
import { IntervalStrip } from "./charts";
import { Chip, Def, Fig, Scroll } from "./ui";

export function SrmBlock({ ex }: { ex: ExperimentOut }) {
  const s = ex.srm;
  return (
    <section className="block" data-testid="srm" data-verdict={s.verdict}>
      <h3>1. Sample ratio check <Chip v={s.verdict}>{s.verdict === "OK" ? "SRM OK" : s.verdict === "MISMATCH" ? "SRM MISMATCH" : "SRM INSUFFICIENT"}</Chip></h3>
      <p className="muted">Shown before any lift. Observed assignments against the allocation the plan froze: <Def term="chi-square goodness of fit">Σ (observed − expected)² / expected over the arms, one degree of freedom; p = erfc(√(statistic / 2)) from a series, no table. Verdict order: INSUFFICIENT when an expected cell is below the plan's minimum (5), MISMATCH when p &lt; 0.001, else OK.</Def></p>
      <Scroll label="Sample ratio">
        <table>
          <thead><tr><th scope="col">Arm</th><th scope="col" className="num">Planned share</th><th scope="col" className="num">Expected</th><th scope="col" className="num">Observed</th></tr></thead>
          <tbody>
            {Object.keys(ex.allocation).map((v) => (
              <tr key={v} data-arm={v}><th scope="row">{v}</th><td className="num mono">{ex.allocation[v]}</td><td className="num mono" data-k="expected">{s.expected?.[v] ?? "n/a"}</td><td className="num mono" data-k="observed">{s.observed[v]}</td></tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <p className="mono figs">chi-square <Fig k="srm.statistic">{s.statistic ?? "n/a"}</Fig> · p <Fig k="srm.p_value">{s.p_value ?? "n/a"}</Fig> · df {s.df ?? "n/a"} · {n0(ex.assigned_units)} accounts assigned by the cutoff</p>
      {s.verdict === "MISMATCH" && <p className="callout callout--bad" data-testid="srm-mismatch">The assignment counts do not match the planned allocation (p &lt; 0.001). No lift is shown for this run, and a ship decision is blocked: if assignment is broken, the arms may differ in more than the treatment.</p>}
      {s.verdict === "OK" && <p className="callout">The counts are consistent with the planned allocation (p ≥ 0.001), so the arms can be compared.</p>}
    </section>
  );
}

function verdictReasons(ex: ExperimentOut): string {
  const p = ex.primary, out: string[] = [];
  if (p.interval?.includes_zero) out.push("the interval includes 0");
  if (ex.run.interim) out.push("the run is interim (before planned_end)");
  if (!ex.run.config_hash_matches_plan && ex.run.analysis_id !== null) out.push("the run does not cite the plan's hash");
  if (ex.run.analysis_id === null) out.push("no analysis run is logged at this cutoff");
  return out.join("; ");
}

export function PrimaryBlock({ ex }: { ex: ExperimentOut }) {
  const p = ex.primary, c = p.variants["control"]!, t = p.variants["treatment"]!, iv = p.interval;
  return (
    <section className="block" data-testid="primary">
      <h3>2. Activation within 7 days (intention to treat)</h3>
      <p className="muted">Mature assigned accounts in the arm they were assigned to, exposed or not. Conversion = activated ÷ mature, per arm.</p>
      <div className="vs" data-testid="vs">
        <div className="vs__arm vs__arm--control"><span className="vs__name">control</span><span className="vs__fig mono"><Fig k="control.conversion">{c.conversion ?? "n/a"}</Fig></span><span className="mono vs__n"><Fig k="control.activated">{c.activated}</Fig> of <Fig k="control.mature">{c.mature_units}</Fig></span></div>
        <div className="vs__vs" aria-hidden="true">vs</div>
        <div className="vs__arm vs__arm--treatment"><span className="vs__name">treatment</span><span className="vs__fig mono"><Fig k="treatment.conversion">{t.conversion ?? "n/a"}</Fig></span><span className="mono vs__n"><Fig k="treatment.activated">{t.activated}</Fig> of <Fig k="treatment.mature">{t.mature_units}</Fig></span></div>
      </div>
      <dl className="facts">
        <div><dt>Absolute effect (treatment − control)</dt><dd><Fig k="absolute_lift_pp">{pp(p.absolute_lift_pp)}</Fig></dd></div>
        <div><dt>Relative lift (absolute ÷ control)</dt><dd><Fig k="relative_lift">{p.relative_lift ?? "n/a"}</Fig>{p.relative_lift === null && <span className="muted"> (null: the control rate is 0)</span>}</dd></div>
        <div><dt><Def term="Newcombe 95 % interval">Hybrid score interval for the difference of two proportions at z = {ex.primary.interval?.z ?? "1.959964"}, built from the two Wilson intervals; square roots exact to 1e-8. Treatment minus control; "includes 0" is a closed test.</Def></dt>
          <dd>{iv ? <><span className="mono" data-figure="interval">[<span data-k="low">{minus(iv.low)}</span>, <span data-k="high">{minus(iv.high)}</span>]</span> <span className="muted mono">({pp(iv.low_pp)} to {pp(iv.high_pp)})</span></> : "n/a"}</dd></div>
        <div><dt>Verdict</dt><dd data-testid="verdict">{p.conclusive ? <Chip v="conclusive">conclusive</Chip> : <Chip v="not conclusive">not conclusive</Chip>} <span className="muted">{p.conclusive ? "the interval excludes 0 on a final run with a valid plan hash" : verdictReasons(ex)}</span></dd></div>
      </dl>
      {iv && <IntervalStrip low={iv.low} high={iv.high} point={p.absolute_lift_pp === null ? null : String(Number(p.absolute_lift_pp) / 100)} label="Newcombe interval of the absolute difference" />}
      {p.conclusive && iv && Number(iv.low_pp) < 1 && <p className="callout callout--warn" data-testid="by-a-hair">Conclusive by a hair: the interval's lower bound is {minus(iv.low)} ({pp(iv.low_pp)}), so it clears zero by less than a tenth of a percentage point. Read it with the disclosure below.</p>}
      <Scroll label="Per-arm Wilson intervals">
        <table>
          <thead><tr><th scope="col">Arm</th><th scope="col" className="num">Assigned</th><th scope="col" className="num">Mature</th><th scope="col" className="num">Activated</th><th scope="col" className="num">Conversion</th><th scope="col" className="num">Wilson 95 %</th></tr></thead>
          <tbody>
            {Object.entries(p.variants).map(([v, x]) => (
              <tr key={v} data-arm={v}><th scope="row">{v}</th><td className="num mono">{x.assigned}</td><td className="num mono">{x.mature_units}</td><td className="num mono">{x.activated}</td><td className="num mono">{x.conversion ?? "n/a"}</td><td className="num mono">{x.wilson_95 ? `[${x.wilson_95.low}, ${x.wilson_95.high}]` : "n/a"}</td></tr>
            ))}
          </tbody>
        </table>
      </Scroll>
    </section>
  );
}

export function WithheldBlock({ ex }: { ex: ExperimentOut }) {
  return (
    <section className="block block--withheld" data-testid="lift-withheld">
      <h3>2. Lift <Chip v="withheld">withheld</Chip></h3>
      <p className="callout callout--bad">No lift, interval or conversion comparison is shown for {ex.experiment_version_id}: the sample ratio check failed, so the two arms may not be comparable. The rule is D-03: a MISMATCH is shown in place of a lift and blocks a ship decision. Investigate the randomiser first (here: it sends 3 of every 5 accounts to treatment while the plan says 0.40).</p>
    </section>
  );
}

export function GuardrailBlock({ ds, ex }: { ds: Dataset; ex: ExperimentOut }) {
  const g = guardrailReview(ex, ds.plans.get(ex.experiment_version_id)!);
  return (
    <section className="block" data-testid="guardrail" data-verdict={g.verdict}>
      <h3>3. Guardrail: {g.metric.replace(/_/g, " ")} <Chip v={g.verdict}>{g.verdict}</Chip></h3>
      <p className="muted">Accounts with a <span className="mono">product_error</span> event in the {g.window_days} days after their assignment ÷ eligible accounts, per arm. HARMFUL only when the whole Newcombe interval of the difference lies above 0; INSUFFICIENT when an arm has no eligible account.</p>
      <Scroll label="Guardrail by arm">
        <table>
          <thead><tr><th scope="col">Arm</th><th scope="col" className="num">Eligible</th><th scope="col" className="num">With an error</th><th scope="col" className="num">Error rate</th></tr></thead>
          <tbody>{Object.entries(g.by_variant).map(([v, x]) => <tr key={v} data-arm={v}><th scope="row">{v}</th><td className="num mono">{x.eligible_units}</td><td className="num mono">{x.units_with_error}</td><td className="num mono">{x.error_rate ?? "n/a"}</td></tr>)}</tbody>
        </table>
      </Scroll>
      {g.interval ? <p className="mono figs">difference <Fig k="guardrail.difference_pp">{pp(g.difference_pp)}</Fig> · Newcombe [{minus(g.interval.low)}, {minus(g.interval.high)}] · {g.interval.includes_zero ? "includes 0" : "excludes 0"}</p> : <p className="muted">No interval: an arm has no eligible account.</p>}
    </section>
  );
}

export function RevenueBlock({ ex }: { ex: ExperimentOut }) {
  const r = ex.revenue_per_assigned_account;
  return (
    <section className="block" data-testid="revenue">
      <h3>4. Revenue per assigned account (USD)</h3>
      <p className="muted">Active or ended subscriptions starting in [{r.window.from.slice(0, 10)}, {r.window.to.slice(0, 10)}) and on or before the cutoff, ÷ mature assigned accounts (zeros included), per arm, with a t-interval over account-level values. The contract pins no interval for the difference between arms.</p>
      <Scroll label="Revenue by arm">
        <table>
          <thead><tr><th scope="col">Arm</th><th scope="col" className="num">Accounts</th><th scope="col" className="num">Total</th><th scope="col" className="num">Mean</th><th scope="col" className="num">t 95 % interval</th></tr></thead>
          <tbody>{Object.entries(r.by_variant).map(([v, x]) => (
            <tr key={v} data-arm={v}><th scope="row">{v}</th><td className="num mono">{x.units}</td><td className="num mono">{x.total}</td><td className="num mono">{x.mean ?? "n/a"}</td><td className="num mono">{x.interval ? `[${minus(x.interval.low)}, ${minus(x.interval.high)}] (df ${x.interval.df}, t ${x.interval.t})` : "n/a"}</td></tr>
          ))}</tbody>
        </table>
      </Scroll>
    </section>
  );
}

/** A run's label: interim or final, the count of prior runs, the cutoff and the plan checks. */
export function RunHead({ ds, run, ex }: { ds: Dataset; run: AnalysisRun; ex: ExperimentOut }) {
  const plan = ds.plans.get(run.experiment_version_id)!;
  const name = ds.versions.find((v) => v.experiment_version_id === run.experiment_version_id)?.name ?? run.experiment_version_id;
  return (
    <header className="runhead" data-testid="run-head" data-run={run.analysis_id}>
      <h2>{name} · {run.experiment_version_id} · run {run.analysis_id}</h2>
      <p className="runhead__chips">
        <Chip v={ex.run.interim ? "interim" : "final"}>{ex.run.interim ? "interim run" : "final run"}</Chip>
        <span className="mono" data-testid="prior-runs">{ex.run.prior_runs} prior run{ex.run.prior_runs === 1 ? "" : "s"} of this version</span>
        <span className="muted">cutoff {isoZ(run.cutoff_at)} · planned end {isoZ(plan.planned_end)}</span>
      </p>
      <p className="muted">{ex.run.interim ? "Before planned_end: this run cannot support a ship decision. " : "At or after planned_end. "}Plan frozen before any run: {ex.run.plan_frozen ? "yes" : "no"} (frozen {isoZ(plan.frozen_at)}) · the plan's config_hash {ex.run.config_hash_matches_plan ? "matches" : "does not match"} the run's, recomputed here as sha-256 of the plan JSON: <span className="mono" title={plan.config_hash}>{plan.config_hash.slice(0, 16)}…</span></p>
    </header>
  );
}

export function Disclosures({ ds }: { ds: Dataset }) {
  const list = ds.manifest.generator?.parameters?.disclosures;
  if (!list || list.length === 0) return null;
  return (
    <aside className="disclosure" data-testid="disclosure">
      <h3>Outcome-informed choices, disclosed</h3>
      <p>The generator's manifest records choices that were made after looking at earlier drafts of the data. They do not change how any figure is computed, but they mean this experiment is not a clean pre-registered draw. Everything else was drawn once from the seed and is reported as drawn.</p>
      <ul>{list.map((d, i) => <li key={i} data-k="disclosure">{d}</li>)}</ul>
    </aside>
  );
}

/** The percent text of a rate, for captions. */
export const rateText = (r: string | null): string => (r === null ? "n/a" : `${r} (${pct(r)})`);
