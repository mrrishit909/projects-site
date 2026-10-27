import { Link } from "../components/link";
import { ByConstruction, Chip, Fig, Related, Scroll, ScopeStrip, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/models";
import { blockOf, driftByRegion, seriesOf } from "../lib/derive";
import { groupStats, cohortRows } from "../lib/cohort";
import { n0, pp } from "../lib/format";
import { TEST_COUNTS } from "../lib/counts";

/** An identifier that may wrap after an underscore but is never broken inside a word (D-09, R10-03). */
export function Ident({ children }: { children: string }) {
  return <>{children.split("_").map((part, i) => <span key={i}>{i > 0 ? <>_<wbr /></> : null}{part}</span>)}</>;
}

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
  const drift = ds.aggregates?.["drift"] as Row | undefined;
  const apacPre = drift ? (drift["by_cutoff"] as Row[]).filter((c) => c["apac"]["exceeds_threshold"] && String(c["prediction_at"]) < String(drift["change_at"])).length : 0;
  const run = ds.primary.world.runs.get(ds.runId);
  const coef = (run?.["config"]?.["models"] as Row[] | undefined)?.find((m) => m["name"] === "logistic_regression")?.["coefficients"] as Record<string, string> | undefined;
  const fwScen = (ds.aggregates?.["economics_full_world"] as Row | undefined)?.["scenarios"] as Record<string, Row> | undefined;
  const disc = (id: string): Row | undefined => (ds.manifest?.["disclosures"] as Row[] | undefined)?.find((d) => d["id"] === id);
  const g02 = (disc("D-G02")?.["items"] as string[] | undefined) ?? [], g03 = (disc("D-G03")?.["items"] as string[] | undefined) ?? [];
  const split = training?.["split_counts_population"] as Record<string, Row> | undefined;
  const testAccounts = new Set(pop.models[0]?.items.map((i) => String(i.account_id))).size;
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
          <dt>Model</dt><dd>logistic regression (L2, deterministic gradient descent), compared with a random baseline, a one-line rule and a constant at the training prevalence; Platt scaling on validation rows</dd>
          {training && <><dt>Training rows</dt><dd data-k="train-rows">{n0(split?.["train"]?.["retained"] ?? 0)} retained rows, {n0(training["training_rows"])} eligible and mature for fitting ({training["training_positives"]} churners)</dd><dt>Validation rows</dt><dd data-k="validation-rows">{n0(split?.["validation"]?.["retained"] ?? 0)} retained rows, {n0(training["validation_rows"])} eligible and mature for calibration ({training["validation_positives"]} churners)</dd></>}
          <dt>Test rows</dt><dd data-k="test-rows">{n0(lr.n)} rows{ds.testRows ? ` from ${n0(testAccounts)} accounts` : ""} ({lr.positives} churners, prevalence {lr.prevalence}), read once</dd>
          {coef && <><dt>Coefficients (standardised)</dt><dd data-testid="coefficients">{Object.entries(coef).map(([k, v], i) => <span key={k}>{i > 0 ? "; " : ""}<Ident>{k}</Ident> {v}</span>)}</dd></>}
        </dl>
      </section>
      <section aria-labelledby="find-h"><h2 id="find-h">What the evaluation shows</h2>
        <ul className="tight" data-testid="cs-findings">
          <li>On the held-out test rows the logistic model's average precision is <Fig k="cs-ap">{lr.average_precision}</Fig> and its Brier score <Fig k="cs-brier">{lr.brier_score}</Fig>{rule && rand ? <>, against the rule's {rule.average_precision} / {rule.brier_score} and the random baseline's {rand.average_precision} / {rand.brier_score}</> : null}. Prevalence is {lr.prevalence}. <Link to="models">The comparison</Link>.</li>
          <li>The model ranks usefully and is <strong>miscalibrated</strong>: it under-predicts where most accounts sit{starter ? <>, by {pp(starter.gap)} for the starter plan</> : null}. <Link to="calibration">The reliability curve</Link> shows the rows behind each point; {lr.bins.filter((b) => b.count === 0).length} of 10 bins are empty.</li>
          {apac && <li>One region drifts and the whole population does not show it: apac's usage PSI is {apac.apac.psi} against {apac.all_accounts.psi} for everyone, because its logins stopped being recorded. The same series also exceeds 0.2 at {apacPre} cutoffs before that change; those are false positives of the 0.0001 floor on a small cohort, not drift. <Link to="monitoring">Monitoring</Link>.</li>}
          <li>A large tail is censored, not negative: the latest cutoffs have no outcome yet and are never counted as accounts that stayed. <Link to="overview">Overview</Link>.</li>
        </ul>
        <ByConstruction />
      </section>
      <section aria-labelledby="int-h"><h2 id="int-h">The limits of the intervention</h2>
        <ul className="tight">
          <li><strong>Risk is not responsiveness.</strong> The model estimates who is likely to leave. An offer helps only where it changes the outcome, and that can be a different set of accounts (accounts that were going to stay anyway, or that will leave whatever is offered). A queue that claims to rank by response is refused RISK_NOT_RESPONSIVENESS.</li>
          <li><strong>The economics are hypothetical.</strong> {sc.length > 0 ? <>With the declared assumptions the draft queue is worth {sc.map((x) => `${x.e.expected_value} at K ${x.r["capacity"]}`).join(", ")} (USD, on the <span data-k="cs-cohort-scored">{n0(ds.setAt("2026-09-01T00:00:00Z", ds.primaryModel, sc[0]!.r["scenario_id"])["outreach_queue"].population)}</span> scored accounts of the published cohort){fwScen ? <>; on the whole 2,400-account world ({n0(fwScen["sc-001"]!["scored_accounts"])} scored accounts) the same scenarios are worth {ds.scenarios.map((r) => `${fwScen[r["scenario_id"]]?.["expected_value"]} at K ${r["capacity"]}`).join(", ")}</> : null}</> : "The expected value"}; it rests on an assumed effect of the intervention that nothing here estimates, and it changes sign with that assumption. The assumptions were changed once after the first run showed negative value for all three scenarios (D-G02 item 7).</li>
          <li><strong>No experiment.</strong> A randomised design is the only evidence of an effect; none is designed or simulated here (P10-DOMAIN-06).</li>
          <li><strong>Nothing is sent.</strong> The planner and the queue are simulations in browser memory.</li>
        </ul>
      </section>
      <section aria-labelledby="choices-h"><h2 id="choices-h">Choices made after looking at outcomes</h2>
        <p>The synthetic world was tuned after seeing results. Every choice below is listed in the manifest (disclosures D-G02 and D-G03, in full on <Link to="evidence">the evidence page</Link>), in the order it was made. <strong>The engagement signal was strengthened until the model's margins over the baselines were met</strong>, so those margins are a property of the construction, not a finding.</p>
        {g02.length > 0 && <ol className="steps" data-testid="choices-list" data-count={g02.length + g03.length}>{[...g02, ...g03].map((t, k) => <li key={k} data-choice={k < g02.length ? "D-G02" : "D-G03"}>{t}</li>)}</ol>}
        <p>These choices make the demonstration legible; they also mean the margins over the baselines are a property of the construction.</p></section>
      <section aria-labelledby="gaps-h"><h2 id="gaps-h">Known gaps</h2>
        <Scroll label="Known gaps"><table><caption>Gaps stated by the contracts; none is hidden.</caption><thead><tr><th scope="col">Gap</th><th scope="col">Consequence</th></tr></thead><tbody>
          <tr><td className="l">Four features only</td><td className="t">eight other registered fields are refused; the brief's "about twenty" is not met</td></tr>
          <tr><td className="l">Small validation set</td><td className="t">289 rows, so the Platt fit is noisy</td></tr>
          <tr><td className="l">Published sample is not the population</td><td className="t">the 200-account cohort illustrates; the test table and aggregates carry the full-world figures</td></tr>
          <tr><td className="l">Fitting is not mirrored in the browser</td><td className="t">predictions and coefficients are frozen inputs; the browser verifies every metric on them, not the training</td></tr>
          <tr><td className="l">Weak signal in one feature</td><td className="t">high-severity support cases carry little information</td></tr>
        </tbody></table></Scroll>
      </section>
      <section aria-labelledby="checks-h"><h2 id="checks-h">How it was checked</h2>
        <p data-testid="test-counts">The Python domain and API are covered by <Fig k="count-pytest">{n0(TEST_COUNTS.pytest)}</Fig> tests and the golden fixture by <Fig k="count-reference">{n0(TEST_COUNTS.reference)}</Fig> independent reference checks; this site by <Fig k="count-golden">{n0(TEST_COUNTS.golden)}</Fig> mirror checks, <Fig k="count-review">{n0(TEST_COUNTS.review)}</Fig> adversarial checks and <Fig k="count-e2e">{n0(TEST_COUNTS.e2e)}</Fig> browser tests. <Link to="evidence">The layers and what each cannot show</Link>.</p></section>
      <p>Source and contracts: <a href="https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/retentionlab">apps/retentionlab</a>. <Chip kind="hatch">synthetic data, demo mode</Chip></p>
      <Related also={["models", "capacity"]} />
    </>
  );
}
