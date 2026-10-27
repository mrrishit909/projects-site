import { Link } from "../components/link";
import { ByConstruction, Chip, Fig, Related, Scroll, ScopeStrip, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/models";
import { blockOf, driftByRegion, seriesOf } from "../lib/derive";
import { groupStats, cohortRows } from "../lib/cohort";
import { n0, pp } from "../lib/format";

export function CaseStudy() {
  return <WithData>{(ds) => <Study ds={ds} />}</WithData>;
}

function Study({ ds }: { ds: Dataset }) {
  const pop = ds.populations[0]!;
  const lr = blockOf(seriesOf(pop, ds.primarySeries));
  const rule = ds.id === "snapshot" ? blockOf(seriesOf(pop, "business_rule")) : null, rand = ds.id === "snapshot" ? blockOf(seriesOf(pop, "random_baseline")) : null;
  const training = ds.training as Row | null;
  const starter = groupStats(cohortRows(ds), "segment").find((s) => s.group === "starter");
  const apac = ds.testRows ? driftByRegion(ds.testRows, 4)[3] : null;
  const run = ds.primary.world.runs.get(ds.runId);
  const coef = (run?.["config"]?.["models"] as Row[] | undefined)?.find((m) => m["name"] === "logistic_regression")?.["coefficients"] as Record<string, string> | undefined;
  const sc = ds.scenarios.map((r) => ({ r, e: ds.setAt(ds.manifest ? "2026-09-01T00:00:00Z" : (ds.inputs["scope"]["sets"][0]["prediction_at"] as string), ds.primaryModel, r["scenario_id"])["economics"] })).filter((x) => x.e);
  return (
    <>
      <ViewHead mark="12 · Case study" title="Case study" contracts="P10-GOAL-01, P10-DOMAIN-01..06, P10-FLOW-01..10, D-01..D-07">
        <p className="lede">A model card, its evaluation, and the limits of what any of it says about keeping customers.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["decision", "which accounts deserve limited retention attention"], ["data", ds.id === "snapshot" ? "synthetic, 2,400 accounts, 200 published" : "the golden fixture"], ["status", "demonstration; no real customer"]]} />
      <section aria-labelledby="prob-h"><h2 id="prob-h">The problem</h2>
        <p>A subscription business can contact only some of its accounts. Which ones? The tempting answer is "the ones most likely to cancel". That answers a different question from the one that matters, which is where a contact changes the outcome, and the data to answer that does not exist without a randomised experiment. RetentionLab builds the first half carefully (a ranking that is point-in-time correct, honestly evaluated and honestly calibrated) and refuses to pretend it is the second.</p></section>
      <section className="paper" data-testid="model-card" aria-labelledby="card-h"><h2 id="card-h">Model card</h2>
        <dl className="kv">
          <dt>Intended use</dt><dd>rank accounts by 90-day churn risk to decide where limited attention goes; a monitoring and teaching demonstration</dd>
          <dt>Not for</dt><dd>deciding who receives an offer on the strength of risk alone; estimating the effect of an offer; any real customer</dd>
          <dt>Label</dt><dd>cancel in [cutoff, cutoff + {ds.inputs["label_version"]["horizon_days"]} d), available within {ds.inputs["label_version"]["grace_days"]} d grace; censored until then</dd>
          <dt>Features</dt><dd>four, point-in-time: usage in 30 days, days since last usage, high-severity support cases in 90 days, billing total in 90 days</dd>
          <dt>Model</dt><dd>logistic regression (L2, deterministic gradient descent), compared with a random baseline and a one-line rule; Platt scaling on validation rows</dd>
          {training && <><dt>Training rows</dt><dd data-k="train-rows">{n0(training["training_rows"])} ({training["training_positives"]} churners)</dd><dt>Validation rows</dt><dd data-k="validation-rows">{n0(training["validation_rows"])} ({training["validation_positives"]} churners)</dd></>}
          <dt>Test rows</dt><dd data-k="test-rows">{n0(lr.n)} ({lr.positives} churners, prevalence {lr.prevalence}), read once</dd>
          {coef && <><dt>Coefficients (standardised)</dt><dd>{Object.entries(coef).map(([k, v]) => `${k} ${v}`).join("; ")}</dd></>}
        </dl>
      </section>
      <section aria-labelledby="find-h"><h2 id="find-h">What the evaluation shows</h2>
        <ul className="tight" data-testid="cs-findings">
          <li>On the held-out test rows the logistic model's average precision is <Fig k="cs-ap">{lr.average_precision}</Fig> and its Brier score <Fig k="cs-brier">{lr.brier_score}</Fig>{rule && rand ? <>, against the rule's {rule.average_precision} / {rule.brier_score} and the random baseline's {rand.average_precision} / {rand.brier_score}</> : null}. Prevalence is {lr.prevalence}. <Link to="models">The comparison</Link>.</li>
          <li>The model ranks usefully and is <strong>miscalibrated</strong>: it under-predicts where most accounts sit{starter ? <>, by {pp(starter.gap)} for the starter plan</> : null}. <Link to="calibration">The reliability curve</Link> shows the rows behind each point; {lr.bins.filter((b) => b.count === 0).length} of 10 bins are empty.</li>
          {apac && <li>One region drifts and the whole population does not show it: apac's usage PSI is {apac.apac.psi} against {apac.all_accounts.psi} for everyone, because its logins stopped being recorded. <Link to="monitoring">Monitoring</Link>.</li>}
          <li>A large tail is censored, not negative: the latest cutoffs have no outcome yet and are never counted as accounts that stayed. <Link to="overview">Overview</Link>.</li>
        </ul>
        <ByConstruction />
      </section>
      <section aria-labelledby="int-h"><h2 id="int-h">The limits of the intervention</h2>
        <ul className="tight">
          <li><strong>Risk is not responsiveness.</strong> The model estimates who is likely to leave. An offer helps only where it changes the outcome, and that can be a different set of accounts (accounts that were going to stay anyway, or that will leave whatever is offered). A queue that claims to rank by response is refused RISK_NOT_RESPONSIVENESS.</li>
          <li><strong>The economics are hypothetical.</strong> {sc.length > 0 ? <>With the declared assumptions the draft queue is worth {sc.map((x) => `${x.e.expected_value} at K ${x.r["capacity"]}`).join(", ")} (USD)</> : "The expected value"}; it rests on an assumed effect of the intervention that nothing here estimates, and it changes sign with that assumption. The assumptions were changed once after the first run showed negative value for all three scenarios (D-G02 item 7).</li>
          <li><strong>No experiment.</strong> A randomised design is the only evidence of an effect; none is designed or simulated here (P10-DOMAIN-06).</li>
          <li><strong>Nothing is sent.</strong> The planner and the queue are simulations in browser memory.</li>
        </ul>
      </section>
      <section aria-labelledby="choices-h"><h2 id="choices-h">Choices made after looking at outcomes</h2>
        <p>The synthetic world was tuned after seeing results. In order: the hazard intercepts were lowered after the first simulation; <strong>the engagement signal was strengthened until the model's margins over the baselines were met</strong>; the drift change was moved and its target narrowed; late cancellations went from 2 % to 4 %; the late-arrival target was relaxed to three of four features; the scenario assumptions were changed once; and the cohort grew from 140 to 200 accounts for the size cap. The full text is disclosure D-G02 on <Link to="evidence">the evidence page</Link>. These choices make the demonstration legible; they also mean its margins are a property of the construction.</p></section>
      <section aria-labelledby="gaps-h"><h2 id="gaps-h">Known gaps</h2>
        <Scroll label="Known gaps"><table><caption>Gaps stated by the contracts; none is hidden.</caption><thead><tr><th scope="col">Gap</th><th scope="col">Consequence</th></tr></thead><tbody>
          <tr><td className="l">Four features only</td><td className="t">eight other registered fields are refused; the brief's "about twenty" is not met</td></tr>
          <tr><td className="l">Small validation set</td><td className="t">289 rows, so the Platt fit is noisy</td></tr>
          <tr><td className="l">Published sample is not the population</td><td className="t">the 200-account cohort illustrates; the test table and aggregates carry the full-world figures</td></tr>
          <tr><td className="l">Fitting is not mirrored in the browser</td><td className="t">predictions and coefficients are frozen inputs; the browser verifies every metric on them, not the training</td></tr>
          <tr><td className="l">Weak signal in one feature</td><td className="t">high-severity support cases carry little information</td></tr>
        </tbody></table></Scroll>
      </section>
      <p>Source and contracts: <a href="https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/retentionlab">apps/retentionlab</a>. <Chip kind="hatch">synthetic data, demo mode</Chip></p>
      <Related also={["models", "capacity"]} />
    </>
  );
}
