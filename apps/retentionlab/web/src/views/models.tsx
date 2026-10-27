import { useEffect, useState } from "react";
import { HBars, Legend } from "../components/charts";
import { Link } from "../components/link";
import { ByConstruction, Chip, Def, ExportButton, Fig, ParamSelect, Related, Scroll, ScopeStrip, TableFold, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { loadDataset } from "../data/load";
import type { Row } from "../domain/models";
import { cmpFr, p6, parseFraction, sub } from "../domain/num";
import { leafDiff } from "../lib/claims";
import { blockOf } from "../lib/derive";
import { n0, orDash } from "../lib/format";
import { useParam } from "../router";

const SHORT: Record<string, string> = { random_baseline: "Random", business_rule: "Rule", logistic_uncalibrated: "Logistic, no Platt", logistic_calibrated: "Logistic (Platt)" };
export function ModelsView() {
  return <WithData>{(ds) => <Models ds={ds} />}</WithData>;
}

/** The golden case, recomputed in this browser whichever dataset the page shows. */
function GoldenCard({ ds }: { ds: Dataset }) {
  const [g, setG] = useState<Dataset | null>(ds.id === "golden" ? ds : null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (ds.id === "golden") { setG(ds); return; }
    let live = true;
    void loadDataset("golden").then((r) => { if (!live) return; if (r.ok) setG(r.dataset); else setErr(r.error); });
    return () => { live = false; };
  }, [ds]);
  if (err) return <div className="notice notice--bad" role="alert" data-testid="golden-error">The golden fixture did not load: {err}</div>;
  if (!g) return <p className="notice" role="status">Loading the golden fixture…</p>;
  const jan = g.setAt("2026-01-01T00:00:00Z", undefined, "sc-001"), feb = g.setAt("2026-02-01T00:00:00Z");
  const diff = g.expected ? leafDiff(g.primary.result, g.expected) : null;
  return (
    <section className="paper" data-testid="golden-case" aria-labelledby="gold-h">
      <h2 id="gold-h">The golden case, recomputed in your browser</h2>
      <p>Four accounts with known outcomes, hand-worked in the fixture: risks .8, .6, .4, .1 against outcomes 1, 0, 1, 0, capacity K = 2. The numbers below are computed from the fixture's rows right now.</p>
      <Scroll label="Golden case results">
        <table>
          <caption>Golden set 2026-01-01, scenario sc-001 (capacity {jan["capacity"].k}). Expected values are hypothetical.</caption>
          <thead><tr><th scope="col">Quantity</th><th scope="col">Recomputed here</th><th scope="col">Definition</th></tr></thead>
          <tbody>
            <tr><td className="l">Precision at K = 2</td><td data-k="golden-precision">{jan["precision_at_k"].value}</td><td className="t">true churners in the top K ÷ K</td></tr>
            <tr><td className="l">Recall at K = 2</td><td data-k="golden-recall">{jan["recall_at_k"].value}</td><td className="t">true churners in the top K ÷ all churners</td></tr>
            <tr><td className="l">Average precision</td><td data-k="golden-ap">{jan["average_precision"].value}</td><td className="t">step-wise, no interpolation, as scikit-learn</td></tr>
            <tr><td className="l">Brier score</td><td data-k="golden-brier">{jan["brier_score"].value}</td><td className="t">mean squared difference between risk and outcome</td></tr>
            <tr><td className="l">Risk lift at K</td><td data-k="golden-lift">{jan["risk_lift_at_k"].value}</td><td className="t">top-K churn rate ÷ overall churn rate (a ranking statistic, not uplift)</td></tr>
            <tr><td className="l">Contact budget</td><td data-k="golden-budget">{jan["economics"].contact_budget}</td><td className="t">K × contact cost, USD</td></tr>
            <tr><td className="l">Expected value <Chip kind="note">hypothetical</Chip></td><td data-k="golden-ev">{jan["economics"].expected_value}</td><td className="t">sum of risk × assumed effect × margin − cost, USD, one rounding</td></tr>
            <tr><td className="l">Arrived-late events</td><td data-k="golden-late">{jan["late_events"].total}</td><td className="t">occurred before the cutoff, available after it: counted, not used</td></tr>
            <tr><td className="l">February cohort</td><td data-k="golden-feb">{feb["population"].censored} censored of {feb["population"].eligible}</td><td className="t">outcome window not closed; churn rate {orDash(feb["churn_rate"].value, "censored")}, not 0</td></tr>
          </tbody>
        </table>
      </Scroll>
      {diff && <p data-testid="golden-diff">Compared leaf by leaf with the fixture's <code>expected.json</code>: <Fig k="golden-leaves">{n0(diff.total)}</Fig> leaves, <Fig k="golden-bad" tone={diff.bad.length ? "neg" : "pos"}>{n0(diff.bad.length)}</Fig> differ. {diff.bad.length === 0 ? <Chip kind="ok">all equal</Chip> : <Chip kind="risk">differs</Chip>}</p>}
      {ds.id !== "golden" && <p><Link to="?dataset=golden">Open the whole site on the golden case</Link>.</p>}
    </section>
  );
}

function Models({ ds }: { ds: Dataset }) {
  const options = ds.populations.map((p) => ({ value: p.id, label: p.label }));
  const [pid] = useParam("pop", ds.populations[0]!.id);
  const pop = ds.populations.find((p) => p.id === pid) ?? ds.populations[0]!;
  const blocks = pop.models.map((m) => ({ m, b: blockOf(m.items) }));
  const by = (k: string): ReturnType<typeof blockOf> | undefined => blocks.find((x) => x.m.key === k)?.b;
  const lr = by(ds.primarySeries), rule = by("business_rule"), rand = by("random_baseline");
  const dr1 = ds.manifest ? ((ds.manifest["designed_relationships"] as Row[]).find((d) => d["id"] === "DR-01")?.["realised"] as Row | undefined) : undefined;
  const stated = dr1?.["stated_margins"] as Record<string, string> | undefined;
  const margin = (a: string | null, b: string | null, lowerBetter: boolean): string | null => (a === null || b === null ? null : p6(lowerBetter ? sub(parseFraction(b), parseFraction(a)) : sub(parseFraction(a), parseFraction(b))));
  const margins = lr && rule && rand ? {
    ap_over_rule: margin(lr.average_precision, rule.average_precision, false), ap_over_random: margin(lr.average_precision, rand.average_precision, false),
    brier_under_rule: margin(lr.brier_score, rule.brier_score, true), brier_under_random: margin(lr.brier_score, rand.brier_score, true),
  } : null;
  const met = (k: string): boolean | null => (margins && stated && margins[k as keyof typeof margins] ? cmpFr(parseFraction(margins[k as keyof typeof margins]!), parseFraction(stated[k]!)) >= 0 : null);
  const exportRows = blocks.map(({ m, b }) => [m.key, m.label, b.n, b.positives, b.prevalence, b.average_precision, b.brier_score]);
  const ordered = [...blocks].sort((x, y) => (x.m.role === y.m.role ? 0 : x.m.role === "baseline" ? -1 : 1));
  return (
    <>
      <ViewHead mark="04 · Models" title="Model comparison" contracts="P10-MET-04, P10-MET-05, P10-FLOW-05, P10-DOMAIN-04, P10-TEST-06, D-02, D-03, D-07">
        <p className="lede">A churn model is only as good as the simple things it must beat. Here a random baseline, a one-line business rule and a logistic regression are judged on the same held-out rows, with the same two numbers: how well they rank the churners (average precision) and how honest their probabilities are (Brier score).</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["population", pop.detail], ["split", ds.testRows ? "train to 2025-10-01, validation to 2026-02-01, test to 2026-06-01; read once" : "the golden set"], ["rows", n0(pop.models[0]?.items.length ?? 0)]]} />
      <div className="controls"><ParamSelect name="pop" label="Evaluation population" dflt={ds.populations[0]!.id} options={options} testid="pop-select" /></div>
      <ByConstruction />
      <section aria-labelledby="cmp-h">
        <h2 id="cmp-h">Held-out test: the three models side by side</h2>
        <div className="two">
          <figure className="figure">
            <HBars rows={ordered.map(({ m, b }) => ({ label: SHORT[m.key] ?? m.label, value: b.average_precision, tone: m.role === "candidate" ? "coral" : "muted" }))} ref={lr?.prevalence ? { label: "prevalence", value: lr.prevalence } : undefined} caption="Average precision of each model on the evaluation population" testid="ap-chart" />
            <figcaption>Average precision (higher is better), against the prevalence: a model that ranks at random scores about the share who churn.</figcaption>
          </figure>
          <figure className="figure">
            <HBars rows={ordered.map(({ m, b }) => ({ label: SHORT[m.key] ?? m.label, value: b.brier_score, tone: m.role === "candidate" ? "coral" : "muted" }))} caption="Brier score of each model on the evaluation population" testid="brier-chart" />
            <figcaption>Brier score (lower is better): the mean squared gap between the stated risk and what happened.</figcaption>
          </figure>
        </div>
        <Legend items={[{ label: "logistic regression (Platt)", color: "#ef7a6a" }, { label: "baselines and the uncalibrated fit", color: "#bfae9f" }]} />
        <Scroll label="Model comparison table">
          <table data-testid="model-table">
            <caption>Evaluation population: {pop.detail}. Ranked by probability, ties by account id. <Def term="Average precision">The sum over distinct thresholds of the gain in recall times the precision at that threshold, without interpolation (scikit-learn's definition); tied probabilities are one threshold.</Def> <Def term="Brier score">The mean of (risk − outcome)², 0 is perfect; always saying the prevalence scores prevalence × (1 − prevalence).</Def></caption>
            <thead><tr><th scope="col">Model</th><th scope="col">Role</th><th scope="col">Rows</th><th scope="col">Churners</th><th scope="col">Prevalence</th><th scope="col">Average precision</th><th scope="col">Brier score</th></tr></thead>
            <tbody>{ordered.map(({ m, b }) => (
              <tr key={m.key} data-model={m.key}><td className="l">{m.label}</td><td className="t">{m.role}</td><td>{n0(b.n)}</td><td>{n0(b.positives)}</td><td>{orDash(b.prevalence)}</td><td data-k="ap">{orDash(b.average_precision)}</td><td data-k="brier">{orDash(b.brier_score)}</td></tr>
            ))}</tbody>
          </table>
        </Scroll>
        <p><ExportButton ds={ds} name="model-comparison" scope={pop.id} header={["model_key", "model", "rows", "churners", "prevalence", "average_precision", "brier_score"]} rows={exportRows} /></p>
      </section>
      {margins && stated && (
        <section className="panel" data-testid="margins" aria-labelledby="mar-h">
          <h2 id="mar-h">Margins over the baselines</h2>
          <Scroll label="Margins">
            <table>
              <caption>Margin = logistic regression minus the baseline (average precision) or baseline minus logistic regression (Brier). The stated margins were declared before the first run and changed afterwards; see the disclosure.</caption>
              <thead><tr><th scope="col">Margin</th><th scope="col">On this population</th><th scope="col">Stated target</th><th scope="col">Met</th></tr></thead>
              <tbody>{(["ap_over_rule", "ap_over_random", "brier_under_rule", "brier_under_random"] as const).map((k) => (
                <tr key={k} data-margin={k}><td className="l">{k.replace(/_/g, " ")}</td><td data-k="margin">{orDash(margins[k])}</td><td>{stated[k]}</td><td className="t">{met(k) ? <Chip kind="ok">met, by construction</Chip> : <Chip kind="risk">not met</Chip>}</td></tr>
              ))}</tbody>
            </table>
          </Scroll>
          <p>The latent ceiling and the synthetic world's design are in the <Link to="evidence">evidence</Link> as disclosures only; no model, metric or chart on this site reads them.</p>
        </section>
      )}
      <GoldenCard ds={ds} />
      <TableFold summary="What each model is" open={false}>
        <ul className="tight">
          <li><strong>Random baseline.</strong> A seeded hash of the cutoff id; a ranking with no information.</li>
          <li><strong>Business rule.</strong> Flags accounts with no usage in the last 30 days or a high-severity support case in the last 90; the two probabilities are the observed churn rates of flagged and unflagged training rows, so many accounts tie.</li>
          <li><strong>Logistic regression.</strong> Four features, standardised on the training rows only, L2-penalised, fitted by deterministic gradient descent; coefficients and probabilities are frozen as six-place strings and every metric is computed exactly on them. Platt scaling is fitted on validation rows only. Fitting is not mirrored in the browser: predictions are frozen inputs.</li>
        </ul>
      </TableFold>
      <Related also={["calibration", "capacity"]} />
    </>
  );
}
