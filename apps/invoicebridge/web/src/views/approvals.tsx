import { useMemo } from "react";
import { effectivePolicy } from "../domain/book";
import { s2 } from "../domain/num";
import type { PipelineResult } from "../domain/pipeline";
import { isoZ } from "../domain/time";
import { ViewHead } from "../components/layout";
import { Chip, Def, InvoiceLink, NotBuilt, Scroll, usePager, WithData } from "../components/ui";
import { stamp } from "../lib/format";
import { useParam } from "../router";

function Desk({ result }: { result: PipelineResult }) {
  const [filter, setFilter] = useParam("show", "all");
  const b = result.book, pop = result.population, m = result.metrics;
  const polNow = effectivePolicy(pop.approval_policies, b.cutoff);
  const pending = useMemo(() => [...b.status.entries()].filter(([, s]) => s === "matched").map(([id]) => id).sort(), [b]);
  const over = pending.filter((id) => polNow && b.run.invoices.get(id)!.total > polNow.amount_limit && polNow.escalation_role === null);
  const decisions = useMemo(() => [...pop.approvals].sort((x, y) => x.decided_at - y.decided_at || (x.approval_id < y.approval_id ? -1 : 1)), [pop.approvals]);
  const shown = decisions.filter((a) => filter === "all" || (filter === "reject" ? a.decision === "reject" : filter === "approve" ? a.decision === "approve" : (b.verdicts.get(a.approval_id)?.code ?? "") === filter));
  const dp = usePager(shown, 20), pp = usePager(pending, 15);
  const self = pop.approvals.filter((a) => a.actor_id === b.invoices.get(a.invoice_id)?.created_by).length;
  const inv = m.approvals.invalid_records;
  return (
    <>
      <dl className="glance" data-testid="approval-summary">
        <div data-figure="approvals.valid_count"><dt>Valid approvals</dt><dd>{m.approvals.valid_count.toLocaleString("en-US")}</dd></div>
        <div data-figure="approvals.rejections"><dt>Valid rejections</dt><dd>{b.rejected.size}<small>invoices rejected with a reason</small></dd></div>
        <div data-figure="approvals.invalid"><dt>Invalid decisions</dt><dd>{inv.length}<small>{inv.length === 0 ? "none in this dataset" : [...new Set(inv.map((x) => x.reason_code))].join(", ")}</small></dd></div>
        <div data-figure="approvals.self"><dt>Decisions by the creator</dt><dd>{self}<small>separation of duties</small></dd></div>
        <div data-figure="approvals.pending"><dt>Matched, awaiting approval</dt><dd>{pending.length}<small>{over.length} above the limit in force</small></dd></div>
      </dl>
      <section className="panel" aria-labelledby="pol-h">
        <h2 id="pol-h">Policies <Def term="the policy in force">A decision is judged against the policy version in force at the instant it was made: the latest effective_from not after it. The reviewer role may approve totals up to the limit; an escalation role, when a policy carries one, may approve any amount. These policies carry none, so a matched invoice above the limit stays unapproved.</Def></h2>
        <Scroll label="Policies">
          <table className="grid" data-testid="policies">
            <caption className="sr">Approval policy versions</caption>
            <thead><tr><th scope="col">Policy</th><th scope="col" className="num">Version</th><th scope="col">Effective from</th><th scope="col">Role</th><th scope="col" className="num">Limit</th><th scope="col">Escalation role</th></tr></thead>
            <tbody>{[...pop.approval_policies].sort((x, y) => x.effective_from - y.effective_from).map((p) => (
              <tr key={p.policy_id}><td className="mono">{p.policy_id}{polNow?.policy_id === p.policy_id ? " (in force)" : ""}</td><td className="num">{p.version_number}</td><td className="mono">{stamp(isoZ(p.effective_from))}</td><td>{p.reviewer_role}</td><td className="num">{s2(p.amount_limit)}</td><td>{p.escalation_role ?? "none"}</td></tr>))}</tbody>
          </table>
        </Scroll>
      </section>
      <section className="panel" aria-labelledby="pend-h">
        <h2 id="pend-h">Matched and waiting</h2>
        <p className="muted">Matched invoices with no valid approval. {over.length} of them are above the limit in force ({polNow ? s2(polNow.amount_limit) : "no policy"}) and cannot be approved by the reviewer role under these policies.</p>
        <Scroll label="Matched, awaiting approval">
          <table className="grid" data-testid="pending-table">
            <caption className="sr">Matched invoices awaiting approval</caption>
            <thead><tr><th scope="col">Invoice</th><th scope="col">Vendor</th><th scope="col">Created by</th><th scope="col" className="num">Total</th><th scope="col">Against the limit</th></tr></thead>
            <tbody>{pp.page.map((id) => { const i = b.invoices.get(id)!, t = b.run.invoices.get(id)!.total; return <tr key={id}><td><InvoiceLink id={id} /></td><td className="mono">{i.vendor_id}</td><td className="mono">{i.created_by}</td><td className="num">{s2(t)}</td><td>{polNow && t > polNow.amount_limit ? <Chip v="ROLE_OR_LIMIT">over the limit</Chip> : "within the limit"}</td></tr>; })}</tbody>
          </table>
        </Scroll>
        {pp.ui}
      </section>
      <section className="panel" aria-labelledby="dec-h">
        <h2 id="dec-h">Decisions on file</h2>
        <div className="filters"><label>Show <select value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="f-show"><option value="all">All decisions</option><option value="approve">Approvals</option><option value="reject">Rejections</option><option value="COUNTED">Counted</option><option value="SUPERSEDED">Superseded</option><option value="ROLE_OR_LIMIT">ROLE_OR_LIMIT</option><option value="SELF_APPROVAL">SELF_APPROVAL</option></select></label></div>
        <Scroll label="Decisions">
          <table className="grid" data-testid="decisions-table">
            <caption className="sr">Approval decisions in time order</caption>
            <thead><tr><th scope="col">Decision</th><th scope="col">Invoice</th><th scope="col">Actor</th><th scope="col">Role</th><th scope="col">At</th><th scope="col">Policy</th><th scope="col">Verdict</th></tr></thead>
            <tbody>{dp.page.map((a) => { const v = b.verdicts.get(a.approval_id); return (
              <tr key={a.approval_id}><td>{a.decision}{a.reason ? <span className="muted small"> ({a.reason})</span> : null}</td><td><InvoiceLink id={a.invoice_id} /></td><td className="mono">{a.actor_id}</td><td>{a.actor_role}</td><td className="mono">{stamp(isoZ(a.decided_at))}</td><td className="mono">{v?.policy_id ?? "none"}</td><td><Chip v={v?.code ?? "AFTER_AS_OF"} /></td></tr>); })}</tbody>
          </table>
        </Scroll>
        {dp.ui}
      </section>
      <NotBuilt>Approving and rejecting are backend commands (and the race between two approvers, where exactly one succeeds, is tested there). This desk is read-only: it shows what was decided and how each decision was judged.</NotBuilt>
    </>
  );
}
export function ApprovalsView() {
  return (
    <>
      <ViewHead eyebrow="Read-only view" title="Approval desk">
        <p className="lede">Who decided what, under which policy, and what is still waiting. A decision counts only from a different person than the creator, in a role the policy allows for the total.</p>
      </ViewHead>
      <WithData>{({ result }) => <Desk result={result} />}</WithData>
    </>
  );
}
