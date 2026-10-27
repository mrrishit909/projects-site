import { Link } from "../components/link";
import { Chip, Fig, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { asOfIso } from "../data/dataset";
import { PORTFOLIO } from "../components/layout";
import { n0 } from "../lib/format";
import { ROUTES } from "../routes";

function overridden(ds: Dataset): { id: string; w: Record<string, any> }[] {
  const d = ds.now.metrics["weighted_score"]["datasets"] as Record<string, Record<string, any>>; // eslint-disable-line @typescript-eslint/no-explicit-any
  return Object.entries(d).filter(([, v]) => v["critical_override"]).map(([id, w]) => ({ id, w }));
}

function Snapshot({ ds }: { ds: Dataset }) {
  const m = ds.now.metrics, wv = ds.now.weight_version ?? "";
  const over = overridden(ds);
  const top = over[0];
  const own = m["ownership_coverage"], lin = m["lineage_coverage"], res = m["resolution_time"], mt = ds.now.matching, def = m["definition_coverage"];
  const redefined = Object.values(ds.now.definitions["version_counts"] as Record<string, number>).filter((n) => n > 1).length;
  const c = ds.raw;
  return (
    <>
      <section className="block" aria-labelledby="snap" data-testid="snapshot-note">
        <h2 id="snap">The {ds.id === "golden" ? "golden fixture" : "snapshot"}</h2>
        <p>
          {n0(c.datasets.length)} datasets, {n0(c.fields.length)} fields, {n0(c.owners.length)} owners, {n0(c.quality_rules.length)} quality rules, {n0(c.rule_runs.length)} rule runs,{" "}
          {n0(c.issues.length)} issues, {n0(c.lineage_edges.length)} lineage edges, {n0(c.metric_versions.length)} metric versions, {n0(c.customer_records.length)} synthetic customer records and{" "}
          {n0(c.match_candidates.length)} match candidates, measured as of <span className="mono">{asOfIso(ds)}</span> under weight version <span className="mono">{wv}</span>.{" "}
          Every figure below and on the other pages was recomputed in your browser from the published rows when the page loaded.
        </p>
      </section>
      <section aria-labelledby="found">
        <h2 id="found">Five things the data says first</h2>
        <div className="cards">
          <article className={`card${top ? " card--crit" : ""}`} data-testid="card-scorecard">
            <span className="card__k">Score and override</span>
            {top ? <>
              <span className="card__v"><Fig k="top-score">{top.w["value"]}</Fig></span>
              <p><span className="mono">{top.id}</span> scores {top.w["value"]} under {wv}, and <Chip kind="crit">critical override</Chip> sits beside it: {top.w["critical_failures"]} failing rows of a critical rule and {top.w["critical_open_issues"]} open critical issue.</p>
            </> : <><span className="card__v">no override</span><p>No dataset carries an open critical failure at this as-of.</p></>}
            <Link to="scorecard">Open the scorecard</Link>
          </article>
          <article className="card" data-testid="card-ownership">
            <span className="card__k">Ownership coverage</span>
            <span className="card__v"><Fig k="ownership">{own.value}</Fig></span>
            <p>{own.covered} of {own.datasets} datasets have an active accountable owner; {(own.uncovered as string[]).length} {(own.uncovered as string[]).length === 1 ? "has" : "have"} an inactive one.</p>
            <Link to="catalog">Open the catalog</Link>
          </article>
          <article className="card" data-testid="card-lineage">
            <span className="card__k">Observed lineage coverage</span>
            <span className="card__v"><Fig k="lineage">{lin.value}</Fig></span>
            <p>{lin.observed_matching_declared} of {lin.declared_edges} declared edges were observed; {(lin.undeclared_observed as unknown[]).length} observed edges are undeclared; {(lin.inferred_edges as unknown[]).length} inferred edges are never counted as observed.</p>
            <Link to="lineage">Open the lineage</Link>
          </article>
          <article className="card" data-testid="card-issues">
            <span className="card__k">Issues</span>
            <span className="card__v"><Fig k="issues">{res.resolved_count} / {res.claimed_count} / {res.open_count}</Fig></span>
            <p>resolved / claimed / open. A close without a verifying rerun is claimed and never counts as resolved.</p>
            <Link to="issues">Open the workbench</Link>
          </article>
          <article className="card" data-testid="card-matching">
            <span className="card__k">Identity matching</span>
            <span className="card__v"><Fig k="candidates">{mt["candidates"]}</Fig></span>
            <p>candidate pairs, {mt["reviewed"]} reviewed by a person, {mt["merges_reversed"]} merges reversed. Nothing is merged automatically.</p>
            <Link to="duplicates">Open the duplicate review</Link>
          </article>
          <article className="card" data-testid="card-definitions">
            <span className="card__k">Definitions</span>
            <span className="card__v"><Fig k="definitions">{def.value}</Fig></span>
            <p>checklist {def.checklist_version} coverage of {def.published_metrics} published metrics; {redefined} {redefined === 1 ? "metric has" : "metrics have"} more than one version.</p>
            <Link to="glossary">Open the glossary</Link>
          </article>
        </div>
      </section>
    </>
  );
}

export function Landing() {
  return (
    <>
      <section className="hero" aria-labelledby="top">
        <p className="shelfmark">Shelf 07 · an evidence library for data trust</p>
        <h1 id="top">TrustLedger</h1>
        <p className="lede">A data governance analyst has to decide where to spend scarce attention. TrustLedger keeps the evidence for that decision on the shelf: quality measured one dimension at a time, ownership, definitions, lineage, remediation and identity matching, each figure with the rule that produced it.</p>
        <p className="hero__q" data-testid="decision">Which data issues should be fixed first, and who is accountable?</p>
        <div className="cta">
          <Link className="button" to="scorecard">Open the scorecard</Link>
          <Link className="button button--quiet" to="scorecard?dataset=golden">The golden fixture</Link>
          <Link className="button button--quiet" to="case-study">Read the case study</Link>
        </div>
      </section>
      <WithData>{(ds) => <Snapshot ds={ds} />}</WithData>
      <section aria-labelledby="shelf" className="block">
        <h2 id="shelf">The shelf</h2>
        <ul className="routes">
          {ROUTES.filter((r) => r.path !== "").map((r) => <li key={r.path}><Link to={r.path}>{r.label}</Link><span className="muted">{r.blurb}</span></li>)}
        </ul>
      </section>
      <p className="backlink" data-testid="backlink"><a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a></p>
    </>
  );
}
