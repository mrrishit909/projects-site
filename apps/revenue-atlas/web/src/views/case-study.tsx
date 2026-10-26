// P01-UI-10 Case study: problem, build, analytical choices (D-01..D-07), evidence, limits.
import { Link } from "../components/link";

const CI = "https://github.com/mrrishit909/projects-site/actions/workflows/revenue-atlas-ci.yml";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/revenue-atlas";
const PORTFOLIO = "https://mrrishit909.github.io/projects-site/";
const INJECTION = `${import.meta.env.BASE_URL}data/injection-manifest.json`;

export function CaseStudy() {
  return (
    <article className="study">
      <p className="eyebrow">Case study · Business Data Lab · Project 01</p>
      <h1>Revenue Atlas</h1>
      <p className="lede">A revenue analyst's tool for finding which customer, product, region or discount policy explains declining contribution margin, built so every figure reconciles to a shipment line.</p>

      <h2>Problem</h2>
      <p>
        Monthly margin reviews stall on one question: when contribution margin falls, which part of the business explains it? Reports that
        mix order dates, shipment dates and credit dates, or that average ratios over rows, give each team a different answer. The decision
        this product supports is narrow and explicit: which customer, product, region or discount policy explains the decline.
        It does not do statutory revenue recognition, bookings, invoicing or cash.
      </p>

      <h2>What was built</h2>
      <ul>
        <li>A synthetic dataset generator (seeded, with an injection manifest of the defects and relationships it plants).</li>
        <li>A Python domain, PostgreSQL migrations and a FastAPI command layer, verified in continuous integration against a transient database (Mode A).</li>
        <li>This static site: the same contract re-implemented in TypeScript with fixed-point decimals, recomputing every metric in the browser from a published snapshot (Mode B).</li>
        <li>Two principal views: the <Link to="bridge">margin bridge</Link>, a reconciled waterfall from gross sales to contribution, and the <Link to="evidence">evidence ledger</Link>, a sortable table of shipment lines with CSV export. The <Link to="overview">overview</Link> shows the monthly trend.</li>
      </ul>

      <h2>Analytical choices</h2>
      <ul>
        <li><strong>D-01 Grain and time basis.</strong> The fact grain is the shipment line. The window is half-open, [from, to), on the UTC shipment timestamp; cancelled orders never enter, and quarantined and excluded counts are shown on screen. Returns are recognised on the credit date.</li>
        <li><strong>D-02 Money and currency.</strong> Money is decimal, never floating point. Lines convert to USD at the rate for the shipment's UTC date; a missing rate quarantines the line instead of defaulting to 1.0.</li>
        <li><strong>D-03 Historical cost.</strong> A line is costed at the single cost version valid at its shipment time; zero or several matches quarantine it. A return reverses cost at the same version.</li>
        <li><strong>D-04 Allocation.</strong> Discounts and freight are allocated to shipment lines in whole cents with a deterministic remainder rule, so attribution by customer, product or region is exactly additive and the allocation residual is 0.00.</li>
        <li><strong>D-05 Metric formulas.</strong> Rates are ratios of aggregated sums, never averages of row ratios; empty populations give 0.00 or n/a, not invented values. Each metric has an "i" definition beside it.</li>
        <li><strong>D-06 Workflow invariants.</strong> Customers' regions are versioned by effective date; lines without a version appear as an explicit UNASSIGNED region. Quotas join only at rep and period grain.</li>
        <li><strong>D-07 Scenario deltas.</strong> Scenarios apply signed fractions to a copy of the baseline and are always labelled estimates beside observed results. The scenario screen is outside this entry milestone.</li>
      </ul>

      <h2>Evidence</h2>
      <ul>
        <li><a href={CI} rel="noreferrer">Continuous-integration runs for Revenue Atlas</a> (Python tests, TypeScript golden check, browser tests).</li>
        <li><a href={SOURCE} rel="noreferrer">Source tree on GitHub</a>.</li>
        <li>A hand-derived golden fixture (<code>tests/fixtures/golden</code>) is reproduced exactly by both the Python and the TypeScript domain; the browser test opens <code>?dataset=golden</code> and checks the displayed bridge against it.</li>
        <li>The ledger totals row is summed from the visible columns and must equal the bridge for the same filters; the browser tests assert it.</li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li><strong>Synthetic data.</strong> No real customer, price or company appears. Figures illustrate the method and are not findings about a business.</li>
        <li><strong>Static demo.</strong> The site is served as static files. Any scenario control would be a browser-memory simulation; a reload restores the published snapshot. The CSV export only downloads a file.</li>
        <li><strong>Mode A and Mode B.</strong> The database and API behaviour is verified in CI (Mode A) and is not running behind this page. The page recomputes the same contract in the browser (Mode B).</li>
        <li><strong>Designed relationships.</strong> The cost rise from 2026-01, the regional discount change and the apparel return pattern come from the generator's <a href={INJECTION}>injection manifest</a>. They are planted, so finding them demonstrates the tool; it does not validate it on real data.</li>
        <li>Shipping revenue and other variable costs are 0.00 because the dataset records none.</li>
      </ul>

      <p><a href={PORTFOLIO} rel="noreferrer">Back to the portfolio</a></p>
    </article>
  );
}
