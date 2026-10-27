import { Link } from "../components/link";
import { Chip, NotBuilt, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { asOfIso } from "../data/dataset";
import { h4 } from "../domain/num";
import { teamVersusRest } from "../lib/derive";
import { n0 } from "../lib/format";

function Study({ ds }: { ds: Dataset }) {
  const m = ds.now.metrics, wv = ds.now.weight_version ?? "";
  const w = m["weighted_score"]["datasets"] as Record<string, Record<string, any>>; // eslint-disable-line @typescript-eslint/no-explicit-any
  const over = Object.entries(w).find(([, v]) => v["critical_override"]);
  const own = m["ownership_coverage"], lin = m["lineage_coverage"], res = m["resolution_time"], pr = m["match_precision"], mt = ds.now.matching;
  const dp = teamVersusRest(ds, ds.now.views, "Data Platform");
  const snap = ds.id === "snapshot";
  return (
    <>
      <section className="block" data-testid="cs-problem" aria-labelledby="p">
        <h2 id="p">The decision</h2>
        <p className="hero__q">Which data issues should be fixed first, and who is accountable?</p>
        <p>The people asking are a data governance analyst and a data quality analyst. They have hundreds of open findings, a score that is easy to read and easy to misread, and a register in which some owners have left. TrustLedger is a set of calculations and pages that keeps each figure honest enough to prioritise with.</p>
      </section>
      <section className="block" data-testid="cs-data" aria-labelledby="d">
        <h2 id="d">The data</h2>
        <p>{snap ? <>A synthetic world: {ds.raw.datasets.length} datasets across 6 source systems, {ds.raw.owners.length} owners, {ds.raw.quality_rules.length} rules run daily for twelve weeks ({n0(ds.raw.rule_runs.length)} runs), {ds.raw.issues.length} issues, lineage with declared, observed and inferred edges, and {n0(ds.raw.customer_records.length)} synthetic customer records.</> : <>The golden fixture: five datasets and 140 rows, small enough to check by hand.</>} Measured as of <span className="mono">{asOfIso(ds)}</span>. There are no real companies, customers or people, and the generator’s disclosures are on the <Link to="evidence">evidence page</Link>.</p>
      </section>
      <section className="block" data-testid="cs-method" aria-labelledby="m">
        <h2 id="m">How it measures</h2>
        <ul>
          <li><strong>Dimensions stay apart.</strong> Completeness, validity, uniqueness, relationship integrity and timeliness each have their own denominator. Validity is shown twice, populated-only and all-eligible, with labels; uniqueness twice, by group and by row; null foreign keys are counted separately, never silently.</li>
          <li><strong>The weighted score names its weights.</strong> A change of weight version moves a score without any rule changing, so every result says which version produced it.</li>
          <li><strong>A critical failure is never averaged away.</strong> It is counted on its own and sets an override beside the score.</li>
          <li><strong>Resolved means verified.</strong> An issue closed without a successful rerun of the same rule version is claimed, listed separately and never counted as resolved.</li>
          <li><strong>Identity is a decision.</strong> Candidates are proposed with a score and an explanation; a person reviews them; a merge is reversible; the synthetic truth is read only to compute precision.</li>
          <li><strong>Exact arithmetic.</strong> Every ratio is a fraction rounded once, half up. The same code runs in the browser and is compared with the Python domain and with a hand-derived fixture.</li>
        </ul>
      </section>
      <section className="block" data-testid="cs-findings" aria-labelledby="f">
        <h2 id="f">What it finds</h2>
        <ul data-testid="findings">
          {over && <li data-finding="override"><span className="mono">{over[0]}</span> scores {over[1]["value"]} under {wv} and {m["weighted_score"]["by_weight_version"][ds.weightVersions[0]!][over[0]]} under {ds.weightVersions[0]}{over[1]["value"] > "0.950000" && m["weighted_score"]["by_weight_version"][ds.weightVersions[0]!][over[0]] > "0.950000" ? ", above 0.95 under both versions," : ","} while {over[1]["critical_failures"]} of its rows fail a critical key rule and {over[1]["critical_open_issues"]} critical issue is open. <Chip kind="crit">critical override</Chip> sits beside the score. <Link to="scorecard">Scorecard</Link></li>}
          <li data-finding="ownership">Ownership coverage is {own["value"]}: {(own["uncovered"] as string[]).length} datasets are owned by someone no longer active ({(own["uncovered"] as string[]).join(", ")}). <Link to="catalog">Catalog</Link></li>
          <li data-finding="issues">{res["resolved_count"]} issues are resolved with a verifying rerun, {res["claimed_count"]} are claimed, {res["open_count"]} are open. Mean resolution is {res["mean_hours"]} hours over the resolved ones.{snap && dp.team && dp.rest ? <> Data Platform’s resolved issues average {h4(dp.team)} hours against {h4(dp.rest)} for the others, an effect built into the synthetic data.</> : null} <Link to="issues">Issues</Link></li>
          <li data-finding="lineage">Observed lineage covers {lin["value"]} of the declared edges; {(lin["undeclared_observed"] as unknown[]).length} observed edges are undeclared and {(lin["inferred_edges"] as unknown[]).length} inferred edges are kept out of the numerator. <Link to="lineage">Lineage</Link></li>
          <li data-finding="matching">{mt["candidates"]} candidate pairs, {mt["reviewed"]} reviewed, {mt["merges_reversed"]} merges reversed; precision against the synthetic truth is {pr["precision"] ?? "unknown"}, and the wider reviewed-correct share is {pr["reviewed_correct_share"] ?? "unknown"}, labelled apart. <Link to="merges">Merges</Link></li>
        </ul>
      </section>
      <section className="block" data-testid="cs-honesty" aria-labelledby="h">
        <h2 id="h">What is not claimed, and what is not built</h2>
        <ul>
          <li>The findings are properties of a synthetic world, some of them designed in; they are not findings about any real organisation or team.</li>
          <li>Validity is format validity, never correctness; the match precision comes from synthetic truth and says nothing about real people.</li>
          <li>The issue workbench and the duplicate review simulate in browser memory. There is no database, no registration of datasets, no scheduled rerun and no live activity.</li>
        </ul>
        <NotBuilt>No dataset is registered, no rule is created or disabled, no issue is stored and no merge happens from the site. The impact page lists what a definition change reaches; it does not predict by how much any figure moves.</NotBuilt>
      </section>
      <section className="block" data-testid="cs-evidence" aria-labelledby="e">
        <h2 id="e">The evidence</h2>
        <p>The golden fixture reproduces the contract’s own sentence: 100 eligible rows with 5 missing e-mails give completeness 0.950000, and 90 of the 95 populated e-mails pass, so populated-only validity is 0.947368 beside all-eligible 0.900000. <Link to="scorecard?dataset=golden">Open it on the scorecard</Link> or see <Link to="evidence">how each claim is checked</Link>.</p>
      </section>
    </>
  );
}

export function CaseStudy() {
  return (
    <>
      <ViewHead mark="Shelfmark 11 · case study" title="Case study">
        <p className="lede">The problem, the method, what the data says and what it cannot say.</p>
      </ViewHead>
      <WithData>{(ds) => <Study ds={ds} />}</WithData>
    </>
  );
}
