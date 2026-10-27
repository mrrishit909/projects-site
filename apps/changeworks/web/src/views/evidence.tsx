import { Chip, PlateHead, Scroll, WithData, WithDataset } from "../components/ui";
import { Link } from "../components/link";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { ENTITIES } from "../domain/contract";
import { designedClaims, injectionChecks, replayInjections } from "../lib/claims";
import { compareLeaves } from "../lib/compare";
import { n0, short } from "../lib/format";

export function EvidenceView() {
  return (
    <>
      <PlateHead mark="Plate X" title="Evidence">
        <p className="lede">What was checked, by what, and what it cannot show. Every check below runs in your browser when the page loads; none is a screenshot or a stored result.</p>
      </PlateHead>
      <WithDataset id="golden">{(g) => <GoldenCheck g={g} />}</WithDataset>
      <WithData>{(ds) => <SnapshotEvidence ds={ds} />}</WithData>
    </>
  );
}

function GoldenCheck({ g }: { g: Dataset }) {
  const cmpRes = compareLeaves(g.goldenShape(), g.expected);
  const ok = cmpRes.mismatches.length === 0;
  const blk = g.metrics["scenarios"]["scn-001"]["initiatives"]["init-001"] as Row;
  return (
    <section aria-labelledby="h-gold" data-testid="evidence-golden">
      <h2 id="h-gold">The golden case against its expected answer</h2>
      <div className="callout" data-ok={ok ? "true" : "false"}><strong>{ok ? "Every leaf equal." : "Mismatch."}</strong> The hand-derived case (three initiatives, one annual scenario) was recomputed here and compared leaf by leaf with <span className="mono">expected.json</span>, which was written independently of this code: <span data-k="leaves">{cmpRes.leaves - cmpRes.mismatches.length} of {cmpRes.leaves}</span> leaves equal. NPV of init-001 = <span className="mono">{blk["npv"]["exact"]}</span> = {blk["npv"]["value"]} USD; paybacks {blk["payback"]["simple"]["period"]} ({blk["payback"]["simple"]["interpolated"]}) simple and {blk["payback"]["discounted"]["period"]} ({blk["payback"]["discounted"]["interpolated"]}) discounted.
        {!ok && <ul>{cmpRes.mismatches.slice(0, 6).map((m) => <li key={m} className="mono">{m}</li>)}</ul>}</div>
      <p className="small muted">The backend (Python, PostgreSQL) reproduces the same file and an independent SQL recomputation agrees; this page shows the TypeScript mirror agrees too. Open the whole site on the fixture: <a href={`${import.meta.env.BASE_URL}evidence/?dataset=golden`}>?dataset=golden</a>.</p>
    </section>
  );
}

function SnapshotEvidence({ ds }: { ds: Dataset }) {
  const dr = designedClaims(ds);
  const inj = injectionChecks(ds);
  const replay = replayInjections(ds);
  const m = ds.manifest;
  const drIds = [...new Set(dr.map((c) => c.id))];
  const injIds = [...new Set(inj.map((c) => c.inj))];
  const disclosures = (m.generator?.parameters?.["disclosures"] ?? "").split(" | ").filter(Boolean);
  const truth = m.synthetic_truth?.by_initiative_and_type;
  return (
    <>
      <section aria-labelledby="h-dr" data-testid="designed">
        <h2 id="h-dr">Designed relationships, re-derived</h2>
        {dr.length === 0 ? <p className="notice">This dataset has no generator claims to check.</p> : (
          <>
            <p>The generator built seven relationships into the world and recorded the figures it realised. Each figure below is recomputed from the rows by this browser's domain code and compared with the manifest.</p>
            <Scroll label="Designed relationships">
              <table data-testid="designed-table"><caption>{dr.length} figures of {drIds.length} designed relationships</caption>
                <thead><tr><th>Relationship</th><th>What it says</th><th className="num">Figures</th><th>All equal?</th></tr></thead>
                <tbody>{drIds.map((id) => { const cs = dr.filter((c) => c.id === id); const d = m.designed_relationships!.find((x) => x.id === id)!; return (
                  <tr key={id} data-dr={id}><th scope="row">{id}<br /><span className="small muted">{d.name}</span></th><td className="wrapcell small">{d.statement}</td><td className="num">{cs.length}</td><td data-k="holds">{cs.every((c) => c.ok) ? <Chip kind="ok">{cs.length} of {cs.length} hold</Chip> : <Chip kind="crit">differs</Chip>}</td></tr>); })}</tbody>
              </table>
            </Scroll>
            <details><summary>Every figure</summary>
              <Scroll label="Every designed-relationship figure"><table data-testid="designed-figures"><thead><tr><th>Id</th><th>Figure</th><th>Computed here</th><th>Manifest</th></tr></thead>
                <tbody>{dr.map((c, i) => <tr key={i}><td>{c.id}</td><td className="wrapcell">{c.label}</td><td className="wrapcell mono small">{short(c.got, 120)}</td><td className="wrapcell mono small">{c.ok ? "equal" : short(c.want, 120)}</td></tr>)}</tbody></table></Scroll>
            </details>
          </>
        )}
      </section>
      <section aria-labelledby="h-inj" data-testid="injections">
        <h2 id="h-inj">Twelve injected defects</h2>
        {inj.length === 0 ? <p className="notice">No injection manifest in this dataset.</p> : (
          <>
            <p>The generator planted one defect for each adversarial test (P09-TEST-01 to 12) and recorded what the computation must show. {inj.length} machine checks are evaluated against this browser's result; {replay.steps.length} ingest steps of the replay events are run through the validator against a copy of the world, and the other {replay.commandSteps + replay.readSteps} steps (API commands and reads) belong to the backend tests.</p>
            <Scroll label="Injected defects">
              <table data-testid="injections-table"><caption>Injected defects and their checks</caption>
                <thead><tr><th>Defect</th><th>Test</th><th className="num">Checks</th><th>Hold?</th><th className="num">Replayed refusals and acceptances</th></tr></thead>
                <tbody>{injIds.map((id) => { const cs = inj.filter((c) => c.inj === id); const st = replay.steps.filter((s) => s.injection === id); return (
                  <tr key={id} data-inj={id}><th scope="row">{id}<br /><span className="small muted wrapcell">{cs[0]!.name}</span></th><td>{cs[0]!.test}</td><td className="num">{cs.length}</td><td data-k="holds">{cs.every((c) => c.ok) ? <Chip kind="ok">{cs.length} of {cs.length} hold</Chip> : <Chip kind="crit">differs</Chip>}</td>
                    <td className="num" data-k="replay">{st.length === 0 ? "dataset only" : `${st.filter((s) => s.ok).length} of ${st.length} as expected`}</td></tr>); })}</tbody>
              </table>
            </Scroll>
            <Scroll label="Replayed ingest steps"><table data-testid="replay-table"><caption>Ingest steps replayed in this browser</caption>
              <thead><tr><th>Event</th><th>Entity</th><th>Row</th><th>Expected</th><th>Got</th><th>Reason</th></tr></thead>
              <tbody>{replay.steps.map((s, i) => <tr key={i} data-event={s.event}><td>{s.event}</td><td>{s.entity}</td><td className="mono small">{s.id}</td><td>{s.expected}{s.reasonExpected ? ` ${s.reasonExpected}` : ""}</td><td>{s.got}</td><td>{s.ok ? <Chip kind="ok">as expected</Chip> : <Chip kind="crit">differs</Chip>} {s.reasonGot ?? ""}</td></tr>)}</tbody></table></Scroll>
          </>
        )}
      </section>
      <section aria-labelledby="h-dis" data-testid="disclosures">
        <h2 id="h-dis">What the generator discloses</h2>
        {disclosures.length ? <ol>{disclosures.map((d, i) => <li key={i} className="small">{d}</li>)}</ol> : <p className="muted">No disclosures recorded for this dataset.</p>}
      </section>
      <section aria-labelledby="h-truth" data-testid="truth-disclosure">
        <h2 id="h-truth">Disclosure: the synthetic counterfactual</h2>
        <p>The manifest records, for {truth ? Object.keys(truth).length : 0} initiative and benefit-type pairs, the share of the observed improvement that the rollout really caused. That is knowable only because the data is synthetic. It is <strong>never an input</strong> to any figure on this site: the benefits register compares observed change with the baseline trend recorded before deployment and says "observed, not attributed". For init-008 cash the generator's true share is {truth?.["init-008/cash"]?.true_attributable_share ?? "n/a"}, while the recorded trend explains most of the observed change; see <Link to="benefits?initiative=init-008&type=cash">the benefits register</Link>.</p>
      </section>
      <section aria-labelledby="h-rows">
        <h2 id="h-rows">The dataset</h2>
        <dl className="facts"><div><dt>dataset_version</dt><dd>{m.dataset_version}</dd></div><div><dt>dataset_hash</dt><dd title={m.dataset_hash}>{short(m.dataset_hash, 24)}</dd></div><div><dt>as_of</dt><dd>{m.as_of}</dd></div><div><dt>Rejected at ingest</dt><dd data-figure="rejected">{ds.result.ingest.rejected.length}</dd></div></dl>
        <Scroll label="Row counts"><table data-testid="row-counts"><caption>Rows per entity: manifest against what loaded</caption><thead><tr><th>Entity</th><th className="num">Manifest</th><th className="num">Accepted</th></tr></thead>
          <tbody>{ENTITIES.map((e) => <tr key={e} data-entity={e}><th scope="row">{e}</th><td className="num">{n0(m.row_counts[e] ?? 0)}</td><td className="num">{n0(ds.result.population.acc[e].length)}</td></tr>)}</tbody></table></Scroll>
      </section>
      <section aria-labelledby="h-lim" data-testid="limits">
        <h2 id="h-lim">What this cannot show</h2>
        <ul>
          <li><strong>Mode.</strong> The backend (Python domain, PostgreSQL, FastAPI) is verified on hosted runners; this site is the TypeScript mirror over a published snapshot. The sensitivity lab, the roadmap edits and the scenario selection are browser-memory simulations that reset on reload.</li>
          <li><strong>Twelve-period benefit window.</strong> Benefits are recognised within a twelve-period window per stream (the shorter streams run for fewer periods) and recurring costs run over the same window, so NPV and payback describe that window after go-live, not a multi-year case.</li>
          <li><strong>Drafts.</strong> All 30 scenarios are drafts; the seeder cannot load a proposed one. Nothing is funded and there is no funded status.</li>
          <li><strong>Attribution.</strong> An observed change is never attributed to the rollout; the baseline trend sits beside it.</li>
          <li><strong>Payback rule.</strong> A payback is the period of the last crossing from below zero. A series that is never negative has no payback and the reason NO_INVESTMENT; one that ends negative has NOT_RECOVERED; one with no flows has NO_FLOWS. The same rule runs in the Python domain, the SQL reference and this mirror.</li>
          <li><strong>Partial trend coverage.</strong> Where only some compared rows carry a trend, the figure "observed above trend" is null with the warning PARTIAL_TREND_COVERAGE instead of a partial difference (all implementations). The world records a trend on every observed benefit.</li>
          <li><strong>Timing.</strong> Three initiatives are deployed before their dependency-feasible start (DEPLOYMENT_BEFORE_FEASIBLE_START); the cash flow is shown as recorded and not re-timed.</li>
          <li><strong>Attributable totals.</strong> A total is attributable: a claim two initiatives make on one source counts once. The plain sum and the amount counted twice are shown beside it, in money and in hours.</li>
        </ul>
      </section>
    </>
  );
}
