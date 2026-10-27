import { VisitorFunnel } from "../components/charts";
import { Link } from "../components/link";
import { CutoffPicker, Def, Fig, Scroll, ViewHead, WithData, useCutoff } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { fr, q6, ratio } from "../domain/num";
import { isoZ } from "../domain/time";
import { n0 } from "../lib/format";

function Funnel({ ds }: { ds: Dataset }) {
  const [cut, options, setCut] = useCutoff(ds);
  const comp = ds.at(cut.at);
  const f = comp.metrics.funnel, tq = comp.tracking_quality, id = comp.identity, m = comp.metrics;
  const share = (n: number, d: number): string => q6(ratio(n, d) ?? fr(0)) ?? "n/a";
  const excl: { key: string; what: string; n: number; why: string }[] = [
    { key: "bot_events_excluded", what: "Events of bot users", n: tq.bot_events_excluded, why: "users flagged bot_flag, including anonymous events a link attributes to a bot; excluded everywhere" },
    { key: "internal_events_excluded", what: "Events of internal accounts", n: tq.internal_events_excluded, why: "staff and test accounts; excluded everywhere, and such accounts are not randomised" },
    { key: "unknown_identity", what: "Events with an unknown identity", n: tq.unknown_identity, why: "a user_id that is no user, or neither id present; an unlinked anonymous visit is valid and is kept" },
    { key: "duplicates_dropped", what: "Duplicates dropped", n: tq.duplicates_dropped, why: "same event_id, or same user or anonymous id, name, instant and properties; the earliest received_at wins" },
    { key: "received_after_cutoff", what: "Events received after the cutoff", n: tq.received_after_cutoff, why: "not in this run; a later cutoff includes them as a disclosed revision" },
  ];
  return (
    <>
      <ViewHead eyebrow="Funnel explorer" title="Visitors to activation, in order">
        <p className="lede">A visitor reaches a step only if it reached the previous one earlier and within the gap. The first step's window decides who is in the funnel; the exclusions below are counted, not hidden.</p>
      </ViewHead>
      <CutoffPicker options={options} value={cut.value} onChange={setCut} />
      {f ? <VisitorFunnel funnel={f} signup={m.signup_conversion} /> : <p className="notice">No funnel definition is stored for this dataset.</p>}
      {f && (
        <section className="block" data-testid="definition">
          <h2>Definition</h2>
          <dl className="facts">
            <div><dt>Definition</dt><dd className="mono">{f.definition_id} v{f.version}</dd></div>
            <div><dt>Ordered steps</dt><dd className="mono">{f.steps.map((s) => s.step).join(" → ")}</dd></div>
            <div><dt>Maximum gap between steps</dt><dd>{f.max_gap_hours} hours, inclusive</dd></div>
            <div><dt>Window (first step)</dt><dd className="mono">[{f.window.from}, {f.window.to})</dd></div>
            <div><dt>Unit</dt><dd>the visitor key: the anonymous id, or for a user without one the user; anchored on the earliest first step in the window, no re-anchoring</dd></div>
          </dl>
        </section>
      )}
      <section className="block" data-testid="exclusions" aria-labelledby="excl">
        <h2 id="excl">Exclusions at {isoZ(cut.at)}</h2>
        <p className="muted">Processing order: received by the cutoff, de-duplicate, unknown identity, bots, internal accounts. {n0(tq.rows_total)} rows in the log; {n0(tq.canonical)} canonical after de-duplication; {n0(tq.analysed)} analysed.</p>
        <Scroll label="Exclusions">
          <table>
            <thead><tr><th scope="col">Exclusion</th><th scope="col" className="num">Events</th><th scope="col" className="num">Share of log rows</th><th scope="col">Rule</th></tr></thead>
            <tbody>{excl.map((e) => <tr key={e.key} data-exclusion={e.key}><th scope="row">{e.what}</th><td className="num mono" data-k="n">{n0(e.n)}</td><td className="num mono">{share(e.n, tq.rows_total)}</td><td className="basis">{e.why}</td></tr>)}</tbody>
          </table>
        </Scroll>
        <p className="muted">Also counted: {n0(tq.delayed_over_24h)} events were delayed (received more than 24 h after they happened) and are kept; {n0(m.retention.excluded_internal_accounts)} internal account(s) signed up in the retention cohort window and are listed there; {n0(m.activation.immature_excluded)} signup(s) are too recent to know whether they activate in 7 days and are excluded from activation until they mature.</p>
      </section>
      <section className="block" data-testid="identity">
        <h2>Identity</h2>
        <p>An identity link attributes the anonymous events of an id to a user only from the moment of the link, never backwards. Of <Fig k="identity.anonymous">{n0(id.anonymous_events)}</Fig> anonymous events analysed, <Fig k="identity.attributed">{n0(id.attributed_by_link)}</Fig> were attributed by a link and <Fig k="identity.remain">{n0(id.remain_anonymous)}</Fig> remain anonymous (visitors who never signed up). <Def term="why signup conversion and the funnel's second step differ">Signup conversion counts distinct anonymous ids that have a visit and a signup in the window, with no gap and no order. The funnel needs the signup within the gap after the visit and in order, on the visitor key. They can differ; both are shown.</Def></p>
      </section>
      <p className="muted">Next: <Link to="cohorts">retention cohorts</Link> · <Link to="tracking">tracking quality</Link>.</p>
    </>
  );
}
export function FunnelView() { return <WithData>{(ds) => <Funnel ds={ds} />}</WithData>; }
