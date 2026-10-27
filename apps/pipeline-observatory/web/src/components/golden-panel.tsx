import { Meaning, Panel, Scroll, Status } from "./ui";
import { useGoldenLab } from "../state/golden";
import { n0 } from "../lib/format";

/** The golden batch of P08-GOLD-01 and its experiments, always from the bundled fixture, computed here through the domain. */
export function GoldenPanel() {
  const lab = useGoldenLab();
  if (lab.status === "loading") return <p className="notice" role="status" data-testid="golden-loading">Recomputing the golden fixture…</p>;
  if (lab.status === "error") return <div className="notice notice--bad" role="alert" data-testid="golden-error"><p>The golden fixture did not load: {lab.error}</p></div>;
  const { ds, experiments } = lab;
  const rows = (ds.acc["raw_records"] ?? []).filter((r) => r["batch_id"] === "b-001");
  const facts = ds.result.facts;
  const M = ds.g.metrics.ingestion.sources["src-orders"];
  const b = (id: string): Record<string, number | string | boolean> => M.batches[id];
  return (
    <Panel id="golden" title="The golden batch: 10 received, 8 accepted, 1 duplicate, 1 quarantined" scope="complete">
      <Meaning>The fixture of P08-GOLD-01, recomputed here from its inputs by the TypeScript domain and compared leaf by leaf with the hand-derived <code>expected.json</code> in CI. Batch b-001 is the first delivery; b-002 replays it; b-003 is a crash after the data write and before the checkpoint.</Meaning>
      <Scroll label="The ten rows of batch b-001 and their class">
        <table className="data" data-testid="golden-rows">
          <caption>Batch b-001, rows in delivery order. The key check runs before the contract check.</caption>
          <thead><tr><th scope="col">Row</th><th scope="col">source_key</th><th scope="col">Quantity</th><th scope="col">Amount</th><th scope="col">Class</th></tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const d = facts.disposition.get(r["raw_record_id"])!;
              return (
                <tr key={r["raw_record_id"]} data-class={d.kind}>
                  <td>{String(i + 1).padStart(2, "0")}</td><th scope="row"><code>{r["source_key"]}</code></th><td>{r["payload_json"].quantity}</td><td>{r["payload_json"].amount}</td>
                  <td><Status tone={d.kind === "accepted" ? "ok" : d.kind === "duplicate" ? "info" : "bad"}>{d.kind}{d.reason ? ` · ${d.reason}` : ""}</Status></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Scroll>
      <Scroll label="Golden batches b-001, b-002, b-003">
        <table className="data" data-testid="golden-batches">
          <caption>The three batches of src-orders. A batch counts only when it committed with its checkpoint.</caption>
          <thead><tr><th scope="col">Batch</th><th scope="col">Status</th><th scope="col">Counted</th><th scope="col">Written rows</th><th scope="col">Received</th><th scope="col">Accepted</th><th scope="col">Duplicate</th><th scope="col">Quarantined</th></tr></thead>
          <tbody>
            {["b-001", "b-002", "b-003"].map((id) => (
              <tr key={id} data-batch={id}>
                <th scope="row"><code>{id}</code></th><td>{String(b(id)["status"])}</td><td>{b(id)["counted"] ? "yes" : "no"}</td><td>{n0(Number(b(id)["written_rows"]))}</td>
                <td data-k="received">{n0(Number(b(id)["received"]))}</td><td data-k="accepted">{n0(Number(b(id)["accepted_unique"]))}</td><td data-k="duplicate">{n0(Number(b(id)["duplicate"]))}</td><td data-k="quarantined">{n0(Number(b(id)["quarantined"]))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <p className="meaning" data-testid="golden-totals">After b-001 and its replay b-002 the source holds <strong data-figure="golden-accepted">{n0(M.accepted_unique)}</strong> accepted unique records ({n0(M.received)} received, {n0(M.duplicate)} duplicates, {n0(M.quarantined)} quarantined occurrences of {n0(M.quarantined_distinct_keys)} key). The crashed b-003 wrote {n0(Number(b("b-003")["written_rows"]))} rows and counts for nothing; the checkpoint stays at version {M.checkpoint.committed_version}.</p>
      <h3>Experiments through the domain</h3>
      <div data-testid="experiments">
        {experiments.map((e) => (
          <section key={e.id} className="experiment" data-experiment={e.id} data-holds={e.holds ? "true" : "false"}>
            <h4>{e.title} <Status tone={e.holds ? "ok" : "bad"}>{e.holds ? "holds" : "fails"}</Status></h4>
            <Scroll label={`Steps of ${e.title}`}>
              <table className="data">
                <thead><tr><th scope="col">Step</th><th scope="col">Received</th><th scope="col">New accepted</th><th scope="col">Duplicate</th><th scope="col">Quarantined</th><th scope="col">Accepted in total</th></tr></thead>
                <tbody>{e.steps.map((s) => <tr key={s.label}><th scope="row">{s.label}<br /><span className="sub">{s.note}</span></th><td>{s.counts.received}</td><td>{s.counts.accepted_unique}</td><td>{s.counts.duplicate}</td><td>{s.counts.quarantined}</td><td data-k="total">{s.accepted_total}</td></tr>)}</tbody>
              </table>
            </Scroll>
            <p className="meaning">{e.verdict}.</p>
          </section>
        ))}
      </div>
      <Meaning>Delivery guarantee: <strong>at-least-once with idempotent apply</strong>, shown at the source-key boundary. Nothing here claims exactly-once: a retry may deliver a row again; it is applied at most once because the key check sees it.</Meaning>
    </Panel>
  );
}
