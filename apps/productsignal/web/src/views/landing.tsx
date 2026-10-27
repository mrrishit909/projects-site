import { ArmFunnel, VisitorFunnel } from "../components/charts";
import { Link } from "../components/link";
import { PORTFOLIO } from "../components/layout";
import { Chip, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { isoZ } from "../domain/time";
import { minus, n0, pp } from "../lib/format";
import { defaultRun } from "../lib/pick";

function Home({ ds }: { ds: Dataset }) {
  const m = ds.manifest, rc = m.row_counts;
  const run = defaultRun(ds);
  const c = ds.at(run.cutoff_at, run.experiment_version_id, run.analysis_id).metrics.experiment!;
  const last = ds.runs[ds.runs.length - 1]!;
  const lastEx = ds.runs.length > 1 ? ds.at(last.cutoff_at, last.experiment_version_id, last.analysis_id).metrics.experiment! : null;
  const asOf = ds.at(ds.asOf, ds.versions[0]!.experiment_version_id).metrics;
  return (
    <>
      <section className="hero" data-testid="decision">
        <p className="eyebrow">A product journey laboratory</p>
        <h1>ProductSignal</h1>
        <p className="hero__q">Should an onboarding change ship, stop, or receive more investigation?</p>
        <p className="lede">Follow visitors to activation, see who comes back and when that can first be known, and read an A/B result the way a careful analyst would: the sample ratio first, then the effect with its interval, then the guardrails. Every figure is recomputed in your browser from a synthetic snapshot.</p>
        <p className="hero__cta"><Link to="overview" className="button">Start with the journey overview</Link> <Link to="result" className="button button--quiet">Jump to the experiment result</Link></p>
      </section>
      <section className="two" aria-label="The journey, as the data shows it">
        {asOf.funnel && <VisitorFunnel funnel={asOf.funnel} signup={asOf.signup_conversion} />}
        {c.assigned_units > 0 && <ArmFunnel ex={c} />}
      </section>
      <section className="cards" aria-label="What the snapshot's experiments say">
        <article className="card" data-testid="card-v1">
          <p className="eyebrow">{c.experiment_version_id} · {c.run.interim ? "interim" : "final"} run {run.analysis_id} · {c.run.prior_runs} prior runs</p>
          <h2>{c.srm.verdict === "MISMATCH" ? "Sample ratio mismatch" : pp(c.primary.absolute_lift_pp)}</h2>
          <p>{c.srm.verdict === "MISMATCH" ? "The lift is withheld." : <>Newcombe interval <span className="mono">[{minus(c.primary.interval!.low)}, {minus(c.primary.interval!.high)}]</span> on 7-day activation, {c.primary.conclusive ? <Chip v="conclusive">conclusive</Chip> : <Chip v="not conclusive">not conclusive</Chip>}.</>} Sample ratio <Chip v={c.srm.verdict}>{c.srm.verdict}</Chip>.</p>
          <p><Link to="result">Read the full result</Link></p>
        </article>
        {lastEx && last.experiment_version_id !== run.experiment_version_id && (
          <article className="card" data-testid="card-v2">
            <p className="eyebrow">{lastEx.experiment_version_id} · final run {last.analysis_id}</p>
            <h2>{lastEx.srm.verdict === "MISMATCH" ? "Sample ratio mismatch" : pp(lastEx.primary.absolute_lift_pp)}</h2>
            <p>{lastEx.srm.verdict === "MISMATCH" ? <>Chi-square {lastEx.srm.statistic}, p {lastEx.srm.p_value}: observed {Object.values(lastEx.srm.observed).join(" / ")} against the planned split. No lift is shown, and a ship decision is blocked.</> : <>Interval [{minus(lastEx.primary.interval!.low)}, {minus(lastEx.primary.interval!.high)}].</>}</p>
            <p><Link to={`result?run=${last.analysis_id}`}>See why</Link></p>
          </article>
        )}
      </section>
      <section className="note-block" data-testid="snapshot-note">
        <h2>About the data</h2>
        {ds.id === "golden"
          ? <p>You are looking at the hand-derived golden fixture ({n0(rc["accounts"] ?? 0)} accounts, {n0(rc["events"] ?? 0)} events, cutoff {isoZ(ds.cutoff)}), whose answer was worked out on paper before any code ran. <Link to="">Return to the snapshot</Link> (remove ?dataset=golden).</p>
          : <p>A synthetic snapshot of 26 weeks (2026-04-06 to 2026-10-04): {n0(rc["accounts"] ?? 0)} accounts, {n0(rc["events"] ?? 0)} events, as of {isoZ(ds.asOf)}, generated from seed {String(m.generator?.seed ?? m.seed)} with planted tracking problems and a few outcome-informed design choices that are disclosed on the result and case-study pages. It also loads a hand-derived golden fixture (<Link to="result?dataset=golden">?dataset=golden</Link>) whose answer is known in advance.</p>}
        <p className="muted">Synthetic data, demo mode. Nothing ships from this site, and there is no live activity.</p>
      </section>
      <p className="backlink" data-testid="backlink"><a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a></p>
    </>
  );
}
export function Landing() { return <WithData>{(ds) => <Home ds={ds} />}</WithData>; }
