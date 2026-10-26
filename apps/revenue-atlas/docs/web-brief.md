# Revenue Atlas — static site brief (Mode B)

Visual direction (P01-GOAL-03): an **editorial financial atlas**. Ivory paper `#f4efe6`,
deep ink `#161a22`, restrained copper `#b1652c` (text on ivory `#8a4d1f`), rule grey
`#c9c2b4`, muted `#6c6a63`. Type: a serif display for titles and figures (Fraunces, vendored
or system `Georgia` fallback), a humanist sans for reading (system stack), tabular numerals
everywhere a number sits in a column. The site must not resemble the portfolio's Precision
Atelier (green/brass) and must not be a wall of KPI cards (master 17).

Two principal representations carry the identity: the **margin bridge** (a reconciled
waterfall from gross sales to contribution, every step a contract metric) and the
**transaction ledger** (a dense, sortable table of shipment lines with cost, discount, freight,
credit and FX columns). Charts are inline SVG with an adjacent accessible table.

## Routes (P01-UI-01..10), all under the injected base path
| Route | Screen | Entry milestone |
|---|---|---|
| `/` | Landing: what the product decides, demo start, mode disclosure, links (portfolio, source, evidence) | yes |
| `/overview/` | Executive overview: monthly net sales and contribution trend, explicit date basis | yes |
| `/bridge/` | Margin bridge waterfall with interaction disclosure | yes |
| `/products/` | Product matrix: sales–margin scatter + table | later |
| `/customers/` | Customer explorer with drillthrough | later |
| `/regions/` | Regional review with the UNASSIGNED row | later |
| `/returns/` | Returns desk: cohorts and maturity | later |
| `/discounts/` | Discount lab: observed vs scenario | later |
| `/evidence/` | Transaction evidence ledger | yes |
| `/scenarios/` | Scenario comparison | later |
| `/case-study/` | Case study: problem, choices, evidence, limits | yes |

Routing: real paths. The build copies `index.html` into each route directory so direct
entry and reload work on GitHub Pages under a nested base (`/projects-site/labs/revenue-atlas/`).
The app derives the current route from `location.pathname` minus `import.meta.env.BASE_URL`.
No hash routing; no reliance on a 404 fallback.

## Data
The site loads `data/manifest.json` (dataset_version, dataset_hash, generated_at,
code_sha, contract_version, generator seed and parameters, row counts, injected-defect
manifest reference) and the entity files it lists. The TypeScript domain
(`src/domain/*.ts`) recomputes every metric from the entity files with decimal-string
arithmetic (a small fixed-point helper; no floats on money), and `scripts/golden-check.ts`
asserts the same golden answers as the Python reference. Scenario edits live in React state
only; a reload restores the published fixture, and a visible banner says so before any
mutating control.

## Honesty requirements on screen (master 04, 17)
* "Synthetic data" label near every chart and table; dataset version and hash in the footer.
* Every mutating control is labelled "browser-memory simulation". No fake server replies,
  no live users, no refresh timestamps other than the real `generated_at`.
* Filters, date window (half-open, UTC basis) and denominators are always visible.
* Reduced-motion media query honoured; any continuous animation has a pause.
* Keyboard: every control reachable; focus visible; dialogs trap focus.

## Breakpoints and evidence
Playwright captures `/`, `/overview/`, `/bridge/`, `/evidence/` at 360, 768, 1280 and
1920 px wide, with long product names and dense tables, and asserts: no horizontal page
overflow, no console errors, the bridge total equals the golden contribution, the ledger
sorts, and a deep link reloads. Screenshots go to `web/evidence/` and are uploaded as the
CI artifact.
