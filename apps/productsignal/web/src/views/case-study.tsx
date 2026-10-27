import { Disclosures } from "../components/experiment";
import { Link } from "../components/link";
import { Chip, Def, ViewHead, WithDataset } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { minus, n0, pp } from "../lib/format";
import { isFinal } from "../lib/pick";

function Study({ ds }: { ds: Dataset }) {
  const m = ds.manifest, rc = m.row_counts;
  const fin = ds.runs.find((r) => r.analysis_id === "an-004") ?? ds.runs.filter((r) => isFinal(ds, r))[0]!;
  const v2 = ds.runs[ds.runs.length - 1]!;
  const a = ds.at(fin.cutoff_at, fin.experiment_version_id, fin.analysis_id).metrics.experiment!;
  const b = ds.at(v2.cutoff_at, v2.experiment_version_id, v2.analysis_id).metrics.experiment!;
  const w4 = ds.at(ds.asOf).metrics;
  return (
    <>
      <section className="block" data-testid="cs-problem" aria-labelledby="a1">
        <h2 id="a1">The problem</h2>
        <p>A product team changes its onboarding and asks one question: should the change ship, stop, or get more investigation? The usual failures are not arithmetic. They are an experiment whose arms were not split as planned, a result peeked at until it looked good, a metric computed on people who have not had time to activate, and a segment cut chosen after the fact. ProductSignal is a small laboratory that makes those failures visible before a number is trusted.</p>
        <p className="muted">Primary users: a product analyst and an experimentation analyst. Not in scope: any automatic release from a decision, causal claims from observational feature correlations, and any chatbot or paid inference.</p>
      </section>
      <section className="block" data-testid="cs-approach" aria-labelledby="a2">
        <h2 id="a2">The approach</h2>
        <ul>
          <li><strong>The unit is the account.</strong> User events roll up to the account before any ratio, so a metric over accounts never counts users.</li>
          <li><strong>Maturity.</strong> A signup counts for 7-day activation only when its 7 days are complete at the cutoff; immature signups are excluded and counted. Retention days are local calendar days in the account's timezone, and a cell is blank until its day has passed.</li>
          <li><strong>The sample ratio comes first.</strong> A chi-square check of the observed assignment against the frozen allocation; on a mismatch the lift is withheld and a ship decision is blocked.</li>
          <li><strong>A lift is an interval.</strong> The absolute difference with a Newcombe hybrid score interval; "conclusive" needs the interval to exclude 0, a final run, and a plan whose hash still matches.</li>
          <li><strong>The plan is frozen before any outcome is read</strong>, and every run is logged: an interim run cannot support a ship decision, and the count of prior runs is shown with every result.</li>
          <li><strong>A run sees only what existed by its cutoff</strong> (D-08): assignments, exposures, subscriptions, observations and events dated after it are not counted.</li>
          <li><strong>Exact arithmetic.</strong> Every published figure comes from integer and rational arithmetic: no floating point. A TypeScript mirror of the Python domain computes them in the browser and is compared with the Python results in CI.</li>
        </ul>
      </section>
      <section className="block" data-testid="cs-data" aria-labelledby="a3">
        <h2 id="a3">The data</h2>
        <p>A synthetic world from one seed ({String(m.generator?.seed ?? m.seed)}): {n0(rc["accounts"] ?? 0)} accounts, {n0(rc["users"] ?? 0)} users, {n0(rc["events"] ?? 0)} events and {n0(rc["sessions"] ?? 0)} sessions over 26 weeks (2026-04-06 to 2026-10-04), as of {m.as_of}. Timezones are America/New_York, America/Los_Angeles and Europe/London with no daylight-saving transition in the window. Planted on purpose: re-sent duplicates, late events, bots, internal accounts, unknown identities, a sample ratio mismatch and others (see <Link to="tracking">tracking quality</Link>). Roughly a third of accounts subscribe; "the business segment activates faster" is read as the business plan with the correlated enterprise segment.</p>
        <p>The designed effect of the treatment on 7-day activation is +{m.generator?.parameters?.true_activation_effect_pp ?? "n/a"} percentage points. What one draw gave is reported, not selected.</p>
      </section>
      <section className="block" data-testid="cs-result" aria-labelledby="a4">
        <h2 id="a4">What the experiment says</h2>
        <p data-testid="cs-v1">Version 1, final run ({fin.analysis_id}, {a.run.prior_runs} prior runs): control {a.primary.variants["control"]!.activated}/{a.primary.variants["control"]!.mature_units} = {a.primary.variants["control"]!.conversion}, treatment {a.primary.variants["treatment"]!.activated}/{a.primary.variants["treatment"]!.mature_units} = {a.primary.variants["treatment"]!.conversion}; {pp(a.primary.absolute_lift_pp)}, Newcombe [{minus(a.primary.interval!.low)}, {minus(a.primary.interval!.high)}]. The sample ratio is {a.srm.verdict}. The result is {a.primary.conclusive ? <Chip v="conclusive">conclusive</Chip> : <Chip v="not conclusive">not conclusive</Chip>}, but only by a hair: the lower bound is {a.primary.interval!.low_pp} percentage points.</p>
        <p data-testid="cs-v2">Version 2 ({v2.analysis_id}): the sample ratio is <Chip v={b.srm.verdict}>{b.srm.verdict}</Chip> (chi-square {b.srm.statistic}, p {b.srm.p_value}; observed {Object.values(b.srm.observed).join(" / ")} against an expected {b.srm.expected ? Object.values(b.srm.expected).join(" / ") : "n/a"}). Its lift is withheld: the randomiser was sending 3 of every 5 accounts to treatment while the plan said 0.40.</p>
        <p>Beside the headline, week-4 retention is not lifted (the designed relationship DR-02 reads −4.50 pp with an interval that includes 0), the error-rate guardrail shows no harm, and revenue per account is noisy. Segment results are exploratory and are never cited. In the as-of read, day-7 retention for the cohort window is {w4.retention.day7.rate} ({w4.retention.day7.retained} of {w4.retention.day7.mature_accounts}).</p>
        <p className="muted"><Def term="what the site does not decide">It lists what the evidence supports and what the contract allows (<Link to="decision">the decision memo</Link>). Whether to ship a change that is conclusive by a hair, with disclosed outcome-informed choices in how the data was made, is a human decision; "inconclusive" stays a valid option.</Def></p>
      </section>
      <Disclosures ds={ds} />
      <section className="block" data-testid="cs-modes" aria-labelledby="a5">
        <h2 id="a5">Two modes</h2>
        <p><strong>Mode A</strong> is the Python domain, a PostgreSQL schema with an independent SQL reference, and a FastAPI service, verified on hosted runners. <strong>Mode B</strong> is this static site: a TypeScript mirror of the domain over the published snapshot. The registry and decision screens are browser-memory simulations and say so; there is no server, no live activity and nothing ships.</p>
      </section>
      <section className="block" data-testid="cs-assumptions" aria-labelledby="a6">
        <h2 id="a6">Assumptions made in this build</h2>
        <ul>
          <li>At a cutoff other than the as-of, the windowed metrics (signup conversion, funnel, activation, feature adoption, the retention cohort) use the defaults for that cutoff (README assumption 3); at the as-of they use the manifest's windows, which equal those defaults.</li>
          <li>The cohort page groups accounts by the Monday of their local signup date; a week is partial when only some of its accounts are mature, and its cell counts the mature ones.</li>
          <li>Local calendars come from the browser's Intl time-zone database, checked against Python's zoneinfo; daylight-saving edges are not pinned by the contract.</li>
          <li>The decision screen applies the rules of C10 as written (including the coordinator's decision that a sample ratio mismatch also blocks stop) and adds one decision per run; none of it touches a product.</li>
          <li>Fonts are system fonts (a geometric sans for display, a humanist sans for reading, a monospace for figures), so nothing is fetched from a third party.</li>
        </ul>
      </section>
      <section className="block" data-testid="cs-notbuilt" aria-labelledby="a7">
        <h2 id="a7">Not built</h2>
        <p>Live ingestion, user-level or exposed-only decision analysis, sequential testing corrections beyond showing the prior-run count, a real registry and audit trail in the browser, automatic release, and any model of feature impact. Where a view stops short it says so.</p>
      </section>
      <p className="muted">Next: <Link to="evidence">what was verified</Link> · <Link to="overview">back to the overview</Link>.</p>
    </>
  );
}

export function CaseStudy() {
  return (
    <>
      <ViewHead eyebrow="Case study" title="ProductSignal: trusting an A/B result before shipping it">
        <p className="lede">A static laboratory for the questions that come before "did it work": was the split right, are the people old enough to count, how many times did we look, and how wide is the interval.</p>
      </ViewHead>
      <WithDataset id="snapshot">{(ds) => <Study ds={ds} />}</WithDataset>
    </>
  );
}
