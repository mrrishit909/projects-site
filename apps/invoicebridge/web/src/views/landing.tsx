import { Link } from "../components/link";
import { PORTFOLIO, ViewHead } from "../components/layout";
import { WithData } from "../components/ui";
import { CutoffTable, MetricSheet } from "./metrics-sheet";

const JOURNEY: [string, string][] = [
  ["intake", "Intake: watch the snapshot import in order and see each duplicate merged into its canonical invoice."],
  ["invoices", "Invoice desk: the document on the left, the match, exceptions, approvals and export on the right. The golden pair is the entry."],
  ["matching", "Matching: every invoice's derived state with filters; the ven-02x and ven-007 relationships; totals that reconcile to the overview."],
  ["exceptions", "Exceptions: the open queue by reason and owner, with assignment history."],
  ["approvals", "Approvals: the policies, the decisions and the matched invoices still waiting."],
  ["case-study", "Case study: what is built, what is not, and how the figures are checked."],
];

export function Landing() {
  return (
    <>
      <ViewHead eyebrow="Accounts payable automation · Business Data Lab project 05" title="InvoiceBridge">
        <p className="lede">A document reconciliation desk. It imports supplier invoices, merges the same obligation arriving twice, three-way matches each one against purchase orders and receipts, and keeps the evidence beside every decision. It stops before payment: nothing here pays, or marks anything paid.</p>
      </ViewHead>
      <section className="panel" aria-labelledby="decision-h">
        <h2 id="decision-h">The decision this supports</h2>
        <p data-testid="decision">Which invoices may advance, and which require exception review? An invoice advances when it is a distinct obligation, every line is within the received quantity and price tolerance, and a reviewer other than its creator approves it under the policy in force.</p>
      </section>
      <WithData>{({ snapshot, result }) => {
        const m = result.metrics;
        return (
          <>
            <section className="panel" aria-labelledby="snap-h">
              <h2 id="snap-h">The snapshot</h2>
              <p data-testid="snapshot-note">
                {snapshot.golden
                  ? <>This is the golden fixture, hand-derived and independent of the application code: one purchase order line of 10 units at 20.00, one receipt of 6, and three invoices. As of <span className="mono">{snapshot.manifest.as_of}</span>.</>
                  : <>This is a 12-month snapshot (2025-10-01 to 2026-09-30) as of <span className="mono">{snapshot.manifest.as_of}</span>, the last nightly matching run. It is a training-free analysis: nothing is fitted or predicted, and every figure is a rule from the contract applied to recorded facts.</>}
                {" "}Every figure below was computed in your browser by a TypeScript mirror of the Python domain, over {Object.values(snapshot.manifest.row_counts).reduce((a, b) => a + b, 0).toLocaleString("en-US")} rows, with integer arithmetic only.
              </p>
              <dl className="glance" data-testid="glance">
                <div data-figure="glance.matched"><dt>Matched or later</dt><dd>{m.matched.invoice_count.toLocaleString("en-US")}<small>{m.matched.by_currency ? <>{Object.entries(m.matched.by_currency).map(([c, v]) => `${c} ${v.total}`).join(" · ")} <span className="muted">(per currency, never converted; the sum {m.matched.total} is not a money figure)</span></> : <>total {m.matched.total}</>}</small></dd></div>
                <div data-figure="glance.obligations"><dt>Obligations</dt><dd>{m.obligations.count.toLocaleString("en-US")}<small>{m.obligations.by_currency ? <>{Object.entries(m.obligations.by_currency).map(([c, v]) => `${c} ${v.total}`).join(" · ")} <span className="muted">(per currency, never converted)</span></> : <>total {m.obligations.total}</>}</small></dd></div>
                <div data-figure="glance.exceptions"><dt>Open exceptions</dt><dd>{m.exceptions.open_count}<small>{m.exceptions.unowned_count} unowned</small></dd></div>
                <div data-figure="glance.stp"><dt>Not blocked at the cutoff <span className="muted small">(the straight-through rate)</span></dt><dd>{m.rates.straight_through_rate ?? "no value"}<small>exception rate {m.rates.exception_rate ?? "no value"}{m.rates.straight_through_never_excepted_rate ? <> · never excepted in the stored history {m.rates.straight_through_never_excepted_rate}</> : null}</small></dd></div>
                <div data-figure="glance.payable"><dt>Approved payable</dt>{m.payable.by_currency
                  ? <dd>{Object.entries(m.payable.by_currency).map(([c, v]) => <span key={c} className="mono" style={{ display: "block" }}>{c} {v.approved_payable}</span>)}<small>after credits, per currency: never converted, never summed ({m.payable.approved_payable} would add unlike currencies)</small></dd>
                  : <dd>{m.payable.approved_payable}<small>after {m.payable.credit_total} credits</small></dd>}</div>
              </dl>
            </section>
            <section className="panel" aria-labelledby="sheet-h">
              <h2 id="sheet-h">Overview metrics</h2>
              <p className="muted">The eleven metric keys of the contract fixture, in contract order, exactly as the pipeline formats them. Money is a 2-decimal string, quantity 4, rates 6; a ratio over nothing is “no value”, never 0.</p>
              <MetricSheet m={m} />
            </section>
            <section className="panel" aria-labelledby="cut-h">
              <h2 id="cut-h">Snapshot cutoffs</h2>
              <p className="muted">The quantity figures re-run as of each cutoff: only receipts and invoices at or before the instant count. The cutoffs are listed beside the metrics, not among them.</p>
              <CutoffTable m={m} asOf={snapshot.manifest.as_of} />
            </section>
          </>
        );
      }}</WithData>
      <section className="panel" aria-labelledby="journey-h">
        <h2 id="journey-h">Where to look</h2>
        <ol className="journey" data-testid="journey">{JOURNEY.map(([to, text]) => <li key={to}><Link to={to}>{to === "case-study" ? "Case study" : to[0]!.toUpperCase() + to.slice(1)}</Link> <span>{text}</span></li>)}</ol>
        <p><a data-testid="backlink" href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a> · <a data-testid="golden-link" href={`${import.meta.env.BASE_URL}invoices/?dataset=golden`}>Open the golden fixture</a> (a full reload: it reads data/golden/)</p>
      </section>
    </>
  );
}
