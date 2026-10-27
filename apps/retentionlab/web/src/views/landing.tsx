import { Link } from "../components/link";
import { Chip, WithData, ByConstruction } from "../components/ui";
import { ReliabilityChart } from "../components/charts";
import { blockOf, seriesOf } from "../lib/derive";
import { headlines } from "../lib/headlines";
import { n0, orDash } from "../lib/format";
import { ROUTES } from "../routes";
import { useState } from "react";

export function Landing() {
  return (
    <WithData>{(ds) => {
      const h = headlines(ds);
      const pop = ds.populations[0]!;
      const cal = blockOf(seriesOf(pop, ds.primarySeries));
      const rule = ds.id === "snapshot" ? blockOf(seriesOf(pop, "business_rule")) : null;
      const rnd = ds.id === "snapshot" ? blockOf(seriesOf(pop, "random_baseline")) : null;
      return <LandingBody ds={ds} h={h} cal={cal} rule={rule} rnd={rnd} />;
    }}</WithData>
  );
}

function LandingBody({ ds, h, cal, rule, rnd }: { ds: import("../data/dataset").Dataset; h: ReturnType<typeof headlines>; cal: ReturnType<typeof blockOf>; rule: ReturnType<typeof blockOf> | null; rnd: ReturnType<typeof blockOf> | null }) {
  const [active, setActive] = useState<number | null>(null);
  return (
    <>
      <section className="hero">
        <p className="shelfmark">Customer intelligence lab</p>
        <h1>RetentionLab</h1>
        <p className="decision" data-testid="decision">Which accounts deserve limited retention attention <em>under uncertain intervention value</em>?</p>
        <p className="lede">A synthetic subscription business, a churn model that was fitted on it, and every number that judges the model recomputed in your browser from the published rows: churn, average precision, the Brier score, the reliability curve with the rows behind each point, precision and recall at the capacity a team really has, drift, and what a retention queue would be worth under stated assumptions.</p>
        <p className="contracts" data-testid="contracts">Contracts: P10-GOAL-01, D-01 to D-07</p>
      </section>
      <section className="panel" data-testid="snapshot-note" aria-labelledby="snap-h">
        <h2 id="snap-h">The snapshot</h2>
        {ds.id === "snapshot" ? (
          <p>
            <Chip kind="plain">synthetic</Chip> A 2,400-account world, evaluated by the domain; the files published here are the complete records of a uniform <strong>{n0((ds.manifest!["published_cohort"] as { accounts: number }).accounts)}-account cohort</strong> plus the full-world test table
            ({n0(ds.testRows!.length)} mature eligible rows, {n0(cal.positives)} churners), the per-cutoff aggregates and the calibration and split summaries. As of <span className="mono">{ds.strip.as_of}</span>, dataset <span className="mono">{ds.strip.dataset_version}</span>.
            The cohort is a sample, not the population.
          </p>
        ) : (
          <p><Chip kind="note">golden fixture</Chip> Fourteen accounts and a few dozen events, small enough to check by hand. The browser evaluates them and the evidence page compares every result with the fixture's expected.json. <Link to="?dataset=snapshot">Open the snapshot</Link> or stay here.</p>
        )}
        <div className="grid" data-testid="landing-figures">
          <div className="card"><div className="big"><span data-figure="ap-logistic">{orDash(cal.average_precision)}</span><small>average precision, {ds.id === "snapshot" ? "logistic (Platt)" : "frozen predictions"}</small></div></div>
          {rule && rnd && <div className="card"><div className="big"><span data-figure="ap-rule">{rule.average_precision}</span> <small style={{ display: "inline" }}>rule</small> / <span data-figure="ap-random">{rnd.average_precision}</span> <small style={{ display: "inline" }}>random</small><small>the baselines, same rows</small></div></div>}
          <div className="card"><div className="big"><span data-figure="brier">{orDash(cal.brier_score)}</span><small>Brier score (lower is better)</small></div></div>
          <div className="card"><div className="big"><span data-figure="prevalence">{orDash(cal.prevalence)}</span><small>prevalence: the share who churn, the floor for average precision</small></div></div>
        </div>
        <ByConstruction compact />
        <p>
          <Link to={ds.id === "golden" ? "" : "?dataset=golden"} data-testid="golden-link">{ds.id === "golden" ? "You are on the golden case" : "Open the golden case (?dataset=golden)"}</Link> recomputes the hand-derived fixture: precision and recall at K = 2, average precision, Brier score, lift, contact budget and expected value.
        </p>
      </section>
      <section aria-labelledby="front-h">
        <h2 id="front-h">The instrument: the reliability curve</h2>
        <div className="two">
          <figure className="figure">
            <ReliabilityChart bins={cal.bins} active={active} onPick={setActive} zoom="auto" caption="Reliability curve: observed churn rate against mean predicted risk in ten bins, with the number of rows behind each point" />
            <figcaption>Each point is a bin of accounts the model scored alike; its size and its printed n are the rows behind it. Points on the dashed line are calibrated. Bins with no rows are not drawn. <Link to="calibration">The lab, with its table</Link>.</figcaption>
          </figure>
          <div>
            <p>A model that ranks well can still be wrong about how likely. Here the model under-predicts: in the bins where most accounts sit, the observed churn rate is above the mean predicted risk. That gap is the thing a retention budget would be planned on, so it is shown next to the ranking metrics and not behind them.</p>
            <p>The second instrument is <Link to="capacity">precision and recall at capacity</Link>: a team can contact K accounts, not all of them, so the question is how many true churners are in the top K and what the contacts cost.</p>
          </div>
        </div>
      </section>
      <section aria-labelledby="routes-h">
        <h2 id="routes-h">Where to look</h2>
        <div className="grid grid--wide" data-testid="route-cards">
          {ROUTES.filter((r) => r.path !== "").map((r) => {
            const x = h[r.path];
            return (
              <Link key={r.path} to={r.path} className="card" data-testid={`card-${r.path}`}>
                <h3>{r.title}</h3>
                <p>{r.blurb}</p>
                {x && <div className="big"><span data-figure={`headline-${r.path}`}>{x.value}</span><small>{x.label}{x.note ? `; ${x.note}` : ""}</small></div>}
              </Link>
            );
          })}
        </div>
      </section>
    </>
  );
}
