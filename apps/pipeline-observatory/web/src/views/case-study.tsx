import { useState } from "react";
import { Link } from "../components/link";
import { Meaning, Panel, Scroll, ScopeTag, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import { loadGolden } from "../data/golden";
import { BROWSER_EXPERIMENTS, NOT_IN_BROWSER, type ExperimentRun } from "../domain/experiments";
import { useGoldenLab } from "../state/golden";

const FALLBACK: [string, string, string][] = [
  ["INJ-01", "P08-TEST-01", "crash after the data write, before the checkpoint"], ["INJ-02", "P08-TEST-02", "overlapping backfills"], ["INJ-03", "P08-TEST-03", "retries that ignore retry-after"],
  ["INJ-04", "P08-TEST-04", "an unexpected required field"], ["INJ-05", "P08-TEST-05", "a malformed row that would vanish"], ["INJ-06", "P08-TEST-06", "a green job on a stale source"],
  ["INJ-07", "P08-TEST-07", "a failed run that would replace a publication"], ["INJ-08", "P08-TEST-08", "a delete that is not propagated"], ["INJ-09", "P08-TEST-09", "a late event behind the watermark"],
  ["INJ-10", "P08-TEST-10", "a pagination token that repeats"], ["INJ-11", "P08-TEST-11", "a secret in a structured log line"], ["INJ-12", "P08-TEST-12", "a workflow that triggers itself"],
];
function Experiments({ ds }: { ds: Dataset }) {
  const lab = useGoldenLab();
  const [out, setOut] = useState<Record<string, ExperimentRun | "running">>({});
  const list = ds.injections.length ? ds.injections.map((i) => [i["id"], i["test"], i["name"]] as [string, string, string]) : FALLBACK;
  const run = async (id: string): Promise<void> => {
    if (lab.status !== "ready") return;
    setOut((o) => ({ ...o, [id]: "running" }));
    const g = await loadGolden();
    const r = BROWSER_EXPERIMENTS[id]!({ goldenInputs: g.inputs, golden: lab.ds, ds });
    setOut((o) => ({ ...o, [id]: r }));
  };
  return (
    <Panel id="failures" title="Twelve failure experiments">
      <Meaning>The generator injected one defect per test P08-TEST-01..12. Eleven can be reproduced here through the TypeScript domain on a small scenario, with the verdict computed from the output; the twelfth (a workflow that triggers itself) is a static check of workflow text that only the backend CI performs. Whether a defect shows in the <em>published</em> data is on the <Link to="evidence#injections">evidence page</Link>.</Meaning>
      <Scroll label="Failure experiments">
        <table className="data" data-testid="experiments-table">
          <thead><tr><th scope="col">Defect</th><th scope="col">Test</th><th scope="col">Reproduce</th><th scope="col">Result</th></tr></thead>
          <tbody>
            {list.map(([id, test, name]) => {
              const r = out[id];
              return (
                <tr key={id} data-inj={id}>
                  <th scope="row"><code>{id}</code> {name}</th><td>{test}</td>
                  <td>{NOT_IN_BROWSER.has(id) ? <span className="sub">backend CI only</span> : <button type="button" className="quiet" disabled={lab.status !== "ready" || r === "running"} onClick={() => void run(id)} data-testid={`run-${id}`} aria-label={`Run ${id} in the browser`}>Run in the browser</button>}</td>
                  <td aria-live="polite" data-k="result">{r && r !== "running" ? <><Status tone={NOT_IN_BROWSER.has(id) ? "idle" : r.ok ? "ok" : "bad"}>{NOT_IN_BROWSER.has(id) ? "not run" : r.ok ? "as expected" : "unexpected"}</Status><ul className="plain">{r.lines.map((l, i) => <li key={i}>{l}</li>)}</ul></> : r === "running" ? "running…" : NOT_IN_BROWSER.has(id) ? <span className="sub">The guard reads workflow text (SELF_PUSH); not reproducible in a page.</span> : <span className="sub">not run yet</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Scroll>
    </Panel>
  );
}
function Guarantee() {
  return (
    <Panel id="guarantee" title="Delivery guarantees">
      <ul className="plain" data-testid="guarantees">
        <li><strong>At-least-once delivery, idempotent apply.</strong> A source may deliver a row again (a retry, a replay, a recovered crash). The key check turns the second delivery into a counted duplicate, so each source key is accepted at most once.</li>
        <li><strong>Proven at the source-key boundary, never exactly-once.</strong> The guarantee is that no source key is accepted twice and no row is lost without a reason code; it does not claim the network delivered each message once.</li>
        <li><strong>Atomic commit.</strong> A batch commits with its checkpoint (accepted rows, quarantine rows and the next checkpoint version are one transaction). A crash between the data write and the checkpoint rolls the transaction back and leaves the batch <code>staged</code> (a dying transaction cannot write <code>aborted</code>); a staged or aborted batch counts for nothing. The golden fixture and the generator record the same state, after cleanup, as <code>aborted</code>.</li>
        <li><strong>Fail closed.</strong> No critical result means blocked; a blocked or failed run never moves the publication pointer.</li>
        <li><strong>Nothing silently dropped.</strong> Every row has exactly one disposition: accepted, duplicate, quarantined (with a reason), or deleted.</li>
      </ul>
    </Panel>
  );
}
function Modes() {
  return (
    <Panel id="modes" title="Two modes, and where each claim is proven">
      <Scroll label="Mode A and Mode B">
        <table className="data">
          <thead><tr><th scope="col" /><th scope="col">Mode A: backend</th><th scope="col">Mode B: this site</th></tr></thead>
          <tbody>
            <tr><th scope="row">Runs</th><td>Python domain, PostgreSQL 16 and FastAPI on GitHub-hosted runners</td><td>TypeScript mirror of the domain, in your browser, over the published snapshot</td></tr>
            <tr><th scope="row">Proves</th><td>Atomic commit, locks, database guards, the API, the replay events EV-01..EV-12</td><td>Every ratio, the gate, the pointer, the reconciliation and the hashes, equal to the Python domain on the same files (CI compares digests)</td></tr>
            <tr><th scope="row">Simulated</th><td>nothing</td><td>the quarantine desk, backfill console and fault injection (browser memory, reset on reload)</td></tr>
          </tbody>
        </table>
      </Scroll>
    </Panel>
  );
}
function Limits({ ds }: { ds: Dataset }) {
  return (
    <Panel id="limits" title="What this cannot show">
      <ul className="plain">
        <li>The data is synthetic. Rates, volumes and the designed relationships come from a seeded generator, not from a real system.</li>
        {ds.id === "snapshot" && <li>The raw records are a sample (2,000 of {ds.ingestion.overall.received ? "40,191 written" : "the written"} rows). Freshness, completeness, late events, reconciliation and content hashes are therefore recorded or sampled, and tagged so.</li>}
        <li>Processing seconds are one synthetic measurement, not a benchmark, and no CI timing is published.</li>
        <li data-testid="identity-note">Mode A identifies the caller by the <code>X-Actor-Id</code> and <code>X-Actor-Role</code> headers the caller sends: <strong>header-asserted identity, no authentication</strong>. 401 means no actor header and 403 a role the command does not allow; neither proves who the caller is.</li>
        <li>Task attempts carry no timestamps in the published data, so the run timeline places batches, publication and watermark on a time axis and shows tasks as ordered steps.</li>
        <li>The silent-source rule on the overview (more than two cadences) is a display rule; the contract&apos;s gate knows only each source&apos;s own target.</li>
      </ul>
      <p><Link to="evidence">Evidence</Link> · <Link to="overview">Overview</Link> · <Link to="gate">Quality gate</Link> · <ScopeTag basis="complete" /></p>
    </Panel>
  );
}
export function CaseStudy() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="12 · entry screen" title="Case study">
            <p className="lede">Is this dataset safe, complete and fresh enough to publish? A pipeline answers by what it refuses to do: accept a key twice, drop a row without a reason, publish past a failed gate, or call a stale source fresh because its jobs are green.</p>
          </ViewHead>
          <Guarantee />
          <Experiments ds={ds} />
          <Modes />
          <Limits ds={ds} />
        </>
      )}
    </WithData>
  );
}
