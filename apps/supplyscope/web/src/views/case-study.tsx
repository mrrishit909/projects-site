// Case study: the problem, what was built, the analytical choices (cited to the contract), the evidence and the limits.
import { useEffect, useState } from "react";
import { Link } from "../components/link";
import { ViewHead } from "../components/layout";
import { useAtlas } from "../state/atlas";

const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/supplyscope";
const CI = "https://github.com/mrrishit909/projects-site/actions/workflows/supplyscope-ci.yml";

interface Injection { id: string; description: string; test?: string }
type Designed = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; relationships: string[]; injections: Injection[] };

function useDesigned(): Designed {
  const [d, setD] = useState<Designed>({ status: "loading" });
  useEffect(() => {
    let live = true;
    fetch(`${import.meta.env.BASE_URL}data/injection-manifest.json`, { headers: { Accept: "application/json" } })
      .then((r) => { if (!r.ok) throw new Error(`injection-manifest.json: HTTP ${r.status}`); return r.json() as Promise<{ designed_relationships?: string[]; injections?: Injection[] }>; })
      .then((j) => { if (live) setD({ status: "ready", relationships: j.designed_relationships ?? [], injections: j.injections ?? [] }); })
      .catch((e: unknown) => { if (live) setD({ status: "error", error: e instanceof Error ? e.message : String(e) }); });
    return () => { live = false; };
  }, []);
  return d;
}

export function CaseStudy() {
  const designed = useDesigned();
  const { state } = useAtlas();
  const rejected = state.status === "ready" ? state.result.rejected.length : null;
  return (
    <article className="prose">
      <ViewHead eyebrow="Case study" title="SupplyScope: what to order, when, and at what cost in stock">
        <p className="lede">An operations analyst prepares a weekly buying plan. This project rebuilds stock from a movement ledger, compares each SKU's inventory position with its reorder point and target, and shows the draft quantity together with the arithmetic that produced it.</p>
      </ViewHead>

      <section aria-labelledby="problem">
        <h2 id="problem">Problem</h2>
        <p>Whether to order, how much, and from whom depends on stock that is rarely a single number: some of it is on the shelf, some is on order, some is owed to customers, and demand during a stockout is hidden because nothing was sold. The decision (P03-GOAL-01) is what should be ordered, when, and under which service and working-capital assumptions, without presenting a recommendation as a commitment.</p>
      </section>

      <section aria-labelledby="built">
        <h2 id="built">What was built</h2>
        <ul>
          <li>A planning overview: fill rate, stockout days and working capital at a chosen date, position against reorder point by location and supplier, and what ingest quarantined. See <Link to="overview">Overview</Link>.</li>
          <li>SKU trajectories: stock on hand, inventory position, reorder point and target over time with receipts and stockout days marked, the figures behind the draft order, and observed sales beside latent demand. See <Link to="skus">SKUs</Link>.</li>
          <li>A forecast evaluation: naive, seasonal naive and an EWMA model on rolling folds, with MAE and WAPE (null for zero-demand folds) and a computed beats-baseline flag. See <Link to="forecast">Forecast</Link>.</li>
          <li>A reorder workbench: every SKU x location row with its arithmetic, sortable, filterable, with a CSV export of the visible rows. See <Link to="reorder">Reorder</Link>.</li>
          <li>A TypeScript domain that mirrors the Python rules and is checked against a hand-derived golden fixture (position 60 gives a draft of 72, position 80 gives 0).</li>
        </ul>
        <p>Locations, suppliers, the simulator, working capital and the purchase draft export are in progress and are not part of this milestone.</p>
      </section>

      <section aria-labelledby="choices">
        <h2 id="choices">Analytical choices</h2>
        <ul>
          <li><strong>D-01, ledger, day order and as-of stock.</strong> Stock is the sum of posted movements up to the as-of instant; movements are immutable and a replayed movement id is rejected. Within a date the order is receipts, then demand, then review. Position is on hand plus confirmed on order minus backorders; reserved units are not subtracted.</li>
          <li><strong>D-02, replenishment.</strong> When position is below the reorder point, order quantity is the target minus position, lifted to the MOQ and rounded up to whole packs; otherwise 0. A draft is a recommendation row and nothing becomes a supplier commitment; export is CSV only.</li>
          <li><strong>D-03, demand, censoring and forecasts.</strong> Observed sales are censored during stockouts, and the generator publishes latent demand separately, so each chart says which one it shows. Baselines are always computed; a model counts only if it beats seasonal naive on the same rolling folds, using only what was known at the cutoff. WAPE is null when actual demand is 0.</li>
          <li><strong>D-04, receipts, suppliers and unmet demand.</strong> A receipt before its order is rejected; a partial receipt leaves the line open. Supplier on-time rates use only receipts dated up to the cutoff. Unmet demand is a lost sale or a backlog, never both. Fill rate is immediately fulfilled units over requested units.</li>
          <li><strong>D-05, simulation and working capital.</strong> Policies are compared on common random numbers drawn from the published seed; working capital is on hand valued at the cost in force on the valuation date.</li>
          <li><strong>D-06, clarifications.</strong> Requested demand is fulfilled sales plus unmet demand opened in the window; a stockout day is a date on which unmet demand opened; raw, MOQ and pack quantities are 0 when not triggered; with no replenishment parameters the order is not evaluated (null); an exact replay of a movement id is rejected and the first occurrence kept.</li>
        </ul>
      </section>

      <section aria-labelledby="evidence">
        <h2 id="evidence">Evidence</h2>
        <ul>
          <li><a href={CI} rel="noreferrer">CI workflow: supplyscope-ci</a> is the automated check for this app on GitHub-hosted runners; its run history is the evidence for the Python domain, database and API (Mode A) and for this site (Mode B).</li>
          <li><a href={SOURCE} rel="noreferrer">Source tree on GitHub</a> (branch business-data-lab).</li>
          <li>Every page footer prints the dataset version, dataset hash, contract version and the generation time of the snapshot it shows. Add <code>?dataset=golden</code> to a view to see the golden fixture, and <code>&amp;state=position_80</code> for its second state.</li>
          {rejected !== null && <li>Ingest of the published snapshot rejected {rejected} records with reason codes; they are kept raw and never enter a figure.</li>}
        </ul>
      </section>

      <section aria-labelledby="limits">
        <h2 id="limits">Limits</h2>
        <ul>
          <li><strong>Synthetic.</strong> Every product, supplier, movement and order is generated. There is no real inventory, supplier or purchase order, and no export is ever a purchase order.</li>
          <li><strong>Static demo (Mode B).</strong> This site is a TypeScript re-implementation over a published snapshot; the simulator runs in the browser on a copy with the published seed and nothing is persisted. The Python domain, PostgreSQL and FastAPI commands (Mode A) are verified separately and are not running here.</li>
          <li><strong>One home location per SKU.</strong> Purchase order lines carry no location, so a SKU's open quantity counts at its parameter location; each SKU is stocked at one home location, so the figures are exact for this data and would need a per-location allocation if a SKU were stocked in two places.</li>
          <li><strong>Reference behaviour kept.</strong> The model's promotion adjustment multiplies its level by the planned uplift ratio, as the Python reference does, while the generator applies one plus the realised uplift to demand. This is reported as an open question and not corrected here.</li>
          <li><strong>Designed relationships, not discoveries.</strong> The generator builds in the effects below, so seeing them in the charts confirms the pipeline recovers them; it is not evidence about real supply chains.</li>
        </ul>
        {designed.status === "loading" && <p className="muted" role="status">Loading the designed relationships from data/injection-manifest.json.</p>}
        {designed.status === "error" && <p className="notice notice--error" role="alert">The injection manifest could not be loaded: {designed.error}. Nothing is substituted.</p>}
        {designed.status === "ready" && (
          <>
            <ul data-testid="designed-relationships">{designed.relationships.map((r) => <li key={r}>{r}</li>)}</ul>
            <p className="small muted">{designed.injections.length} injected data-quality cases are also recorded in the manifest (ids {designed.injections.map((i) => i.id).join(", ")}) so that ingest rejections can be checked against a known list.</p>
          </>
        )}
      </section>

      <p className="actions"><a className="btn btn--primary" href={PORTFOLIO} rel="noreferrer">Back to the portfolio</a> <Link to="reorder" className="btn">Open the reorder workbench</Link></p>
    </article>
  );
}
