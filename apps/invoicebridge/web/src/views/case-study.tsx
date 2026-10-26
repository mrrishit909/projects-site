import { Link } from "../components/link";
import { PORTFOLIO, ViewHead } from "../components/layout";
import { WithData } from "../components/ui";

const SRC = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/invoicebridge";

export function CaseStudy() {
  return (
    <>
      <ViewHead eyebrow="Entry: case study" title="Case study">
        <p className="lede">InvoiceBridge answers one question for an accounts-payable automation analyst: which invoices may advance, and which require exception review? This page says what exists, what does not, and how the figures on the other pages are checked.</p>
      </ViewHead>
      <section className="panel" aria-labelledby="what-h">
        <h2 id="what-h">What it is</h2>
        <p data-testid="tech-p1">A document reconciliation desk over supplier invoices. It identifies the same obligation arriving twice, three-way matches each invoice against purchase orders and receipts with cumulative consumption of the received quantity, routes failures to an exception queue, judges approvals by separation of duties under the policy in force, and builds idempotent export batches that reconcile to what was approved. It stops before payment: it has no bank connection, never pays and never marks anything paid.</p>
        <p>The site has two modes of the same product. <strong>Mode A</strong> is a Python domain, a PostgreSQL schema and a FastAPI backend, verified on hosted runners. <strong>Mode B</strong>, this site, is a static React page that loads a published synthetic snapshot and recomputes every figure in your browser with a TypeScript mirror of the Python domain. Any action on the intake desk is a simulation in browser memory.</p>
      </section>
      <section className="panel" aria-labelledby="built-h">
        <h2 id="built-h">What is built</h2>
        <ul data-testid="built">
          <li><strong>The contract</strong>, decisions D-01 to D-09: import identity and lineage; exact money (tax once per invoice on the unrounded subtotal, rounded half up); three-way match with tolerances carried in the inputs; approval, exception and export rules; the synthetic world.</li>
          <li><strong>A synthetic dataset</strong> from a seeded generator: 12 months, 40 vendors in three currencies, 1,200 purchase orders, 2,800 invoices (95 re-sent PDFs and 3 same-bytes copies among them), receipts with reversals, 117 credit notes, two approval policies, 52 export batches, 660 exceptions with assignment history, and designed relationships (ven-02x, ven-007, month-end re-sends, the limit change) for the match to find.</li>
          <li><strong>The Python backend</strong> (Mode A) with the same derivation as the source of truth.</li>
          <li><strong>This site</strong>: the invoice desk (evidence beside decision), the intake simulation, the matching panel, the exception queue, and read-only views of duplicates, approvals, vendors, exports and an audit timeline.</li>
        </ul>
      </section>
      <section className="panel" aria-labelledby="not-h">
        <h2 id="not-h">What is not built</h2>
        <ul data-testid="not-built-list">
          <li data-testid="c06"><strong>Correcting an extraction.</strong> The backend's correct-extraction command (C06) returns 501 (not implemented). So this snapshot holds no correction versions: every invoice shows its original, immutable extraction, and the lineage panel says so rather than inventing a history.</li>
          <li><strong>Payments and bank connections</strong> are a non-goal. Nothing is paid or marked paid; a credit note adjusts the approved payable without any cash movement.</li>
          <li><strong>Approving, rejecting, assigning and exporting from the site.</strong> Those are backend commands. The approval, exception and export pages are read-only views of recorded decisions.</li>
          <li><strong>OCR and file upload.</strong> Import is structured data; OCR is an optional adapter that does not exist here. The intake page replays a position through already-extracted rows.</li>
          <li><strong>Currency conversion.</strong> A line in a currency other than its purchase order's is never compared without a dated rate; with none it raises CURRENCY_MISMATCH.</li>
          <li><strong>Racing approvals and replayed command sequences.</strong> Five of the twelve injected defects are replay-only (they need a sequence of commands, not rows) and are exercised in the backend tests, not shown here.</li>
          <li><strong>Live activity.</strong> There is none: the snapshot is fixed as of one instant.</li>
        </ul>
      </section>
      <section className="panel" aria-labelledby="how-h">
        <h2 id="how-h">How the figures are produced and checked</h2>
        <p>All arithmetic is integer: money in cents, quantities in ten-thousandths, unit prices and rates in millionths, with exact rational ratios rounded half up. No floating point enters any published figure. The pipeline emits exactly the eleven metric keys of the contract fixture with the same string formatting, plus the snapshot cutoffs beside them.</p>
        <ul>
          <li>The TypeScript pipeline reproduces the hand-derived golden fixture and its two variants (a batch with rejected rows, and an empty one) key by key.</li>
          <li>Over the published snapshot it reproduces digests of the Python domain's results, produced once, so CI needs no Python.</li>
          <li>The matching page recomputes the totals from its own rows and shows them beside the overview metrics. The designed-relationship shares are recomputed from the derived exceptions, not copied.</li>
        </ul>
        <WithData>{({ snapshot }) => (
          <p className="muted" data-testid="provenance">This view is running on dataset <span className="mono">{snapshot.manifest.dataset_version}</span> (hash <span className="mono">{snapshot.manifest.dataset_hash.slice(0, 16)}…</span>, generated {snapshot.manifest.generated_at}). <a href={`${import.meta.env.BASE_URL}invoices/?dataset=golden`}>Open the golden fixture</a> to see the spec sentence worked by hand.</p>
        )}</WithData>
      </section>
      <section className="panel" aria-labelledby="rules-h">
        <h2 id="rules-h">Rules worth knowing</h2>
        <ul>
          <li>Identity for duplicates is (vendor, invoice number upper-cased to letters and digits, invoice date, computed total). The same number from another vendor is not a duplicate. A duplicate is merged into the canonical copy, not rejected: an approved (committed) copy first, else the earliest import, and never an invalid invoice; the same source bytes are checked first. The same bytes with other extracted fields are held for review (needs_review), not merged. Duplicates are detected as of the cutoff.</li>
          <li>Received quantity is consumed by committed (approved) invoices first, in the order they were approved, then by the others in (invoice date, imported at, invoice id) order, so a later back-dated invoice cannot take the quantity of an approved one. A line fails with the first reason in the order NO_PO_LINE (no such line, or a purchase order of another vendor), CURRENCY_MISMATCH, QUANTITY_BLOCKED, PRICE_VARIANCE. Only a fully matched invoice consumes received quantity. An invoice with a valid export row stays exported if a receipt is reversed afterwards: the reversal shows as an exception on it.</li>
          <li>Approval needs a different person than the creator (the same holds for a rejection), a role the policy in force at decision time allows for the total, and a decision not stamped before the import; only the first valid approval counts, and only an earlier valid approval blocks a rejection. The server stamps every decision. Status precedence is adjusted over exported over approved.</li>
          <li>Figures that depend on a definition say which: the straight-through rate is the share not blocked at the cutoff (not the share that never had an exception); shares of the synthetic data are given as open at the as-of and, where the history is stored, as ever raised; the export difference is a check, 0.00 here because the generator closes the period with one batch of everything approved; money is never converted, so a total across currencies is labelled as such and the per-currency figures are the ones to read.</li>
          <li>A rounding difference up to 0.02 per invoice (0.01 per line) is tolerated and disclosed; beyond it the invoice raises ROUNDING_EXCEPTION. A ratio over zero invoices is “no value”, never 0.</li>
        </ul>
      </section>
      <p><Link to="">Start page</Link> · <Link to="invoices">Invoice desk</Link> · <a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a> · <a href={SRC}>Source</a></p>
    </>
  );
}
