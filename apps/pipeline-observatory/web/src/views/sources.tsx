import { useState } from "react";
import { Meaning, Panel, Scroll, ScopeTag, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import { contractReason } from "../domain/classify";
import { REQUIRED_FIELDS, type Row } from "../domain/contract";
import { dur, n0 } from "../lib/format";
import { useParam } from "../router";

const FIELD_RULE: Record<string, string> = {
  record_id: "text; the source_key of the row repeats it", quantity: "integer, not negative (a negative quantity is NEGATIVE_QUANTITY)", unit_price: "decimal string, at most 2 places",
  amount: "signed decimal string, at most 2 places; the business total", event_ts: "UTC instant with a zone; its date is the partition",
};
function Table({ ds }: { ds: Dataset }) {
  const cps = ds.acc["checkpoints"]!;
  const batches = ds.acc["ingestion_batches"]!;
  return (
    <Panel id="contracts" title="Source contracts" scope="complete">
      <Meaning>One contract per source: the schema version the pipeline expects, how often the source should deliver, who owns it and how stale it may get before the gate objects. A batch that declares another schema version is quarantined whole.</Meaning>
      <Scroll label="Source contracts">
        <table className="data" data-testid="sources-table">
          <caption>{ds.acc["source_contracts"]!.length} sources. Checkpoint = the last committed batch of the source.</caption>
          <thead><tr><th scope="col">Source</th><th scope="col">Owner</th><th scope="col">Delivers</th><th scope="col">Schema version</th><th scope="col">Freshness target</th><th scope="col">Checkpoint</th><th scope="col">Batches</th></tr></thead>
          <tbody>
            {ds.acc["source_contracts"]!.map((s) => {
              const sid = s["source_id"] as string;
              const mine = batches.filter((b) => b["source_id"] === sid);
              const by: Record<string, number> = {};
              for (const b of mine) by[b["status"]] = (by[b["status"]] ?? 0) + 1;
              const last = ds.g.metrics.ingestion.sources[sid].checkpoint;
              const n = cps.filter((c) => c["source_id"] === sid).length;
              return (
                <tr key={sid} data-source={sid}>
                  <th scope="row"><code>{sid}</code><br /><span className="sub">{s["source_name"]}</span></th>
                  <td>{s["owner_id"]}</td><td>{s["expected_frequency"]}</td><td data-k="schema">v{s["schema_version"]}</td>
                  <td data-k="target">{s["freshness_target_seconds"] ? <>{s["freshness_target_seconds"]} s<br /><span className="sub">{dur(s["freshness_target_seconds"])}</span></> : "none declared"}</td>
                  <td data-k="checkpoint">v{last.committed_version ?? "none"}<br /><span className="sub">{last.committed_cursor ?? "no cursor"} · {n0(n)} commits</span></td>
                  <td data-k="batches">{Object.entries(by).map(([k, v]) => `${n0(v)} ${k}`).join(", ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Scroll>
    </Panel>
  );
}
function Compare({ ds }: { ds: Dataset }) {
  const inj = ds.injections.find((i) => i["id"] === "INJ-04");
  const ev = (inj?.["evidence"] ?? null) as Row | null;
  const changed = ds.acc["ingestion_batches"]!.filter((b) => b["status"] === "quarantined");
  return (
    <Panel id="versions" title="Schema and version comparison" scope={ev ? "complete" : undefined}>
      <Scroll label="Required fields of the contract">
        <table className="data" data-testid="fields-table">
          <caption>Fields every upsert payload must carry (contract D-P8-12). A missing one is MISSING_FIELD; a malformed one is INVALID_FIELD.</caption>
          <thead><tr><th scope="col">Field</th><th scope="col">Rule</th></tr></thead>
          <tbody>{REQUIRED_FIELDS.map((f) => <tr key={f}><th scope="row"><code>{f}</code></th><td>{FIELD_RULE[f]}</td></tr>)}</tbody>
        </table>
      </Scroll>
      {ev && inj ? (
        <>
          <Scroll label="Schema version comparison">
            <table className="data" data-testid="version-compare">
              <caption>{String(inj["defect"])}</caption>
              <thead><tr><th scope="col" /><th scope="col">Version {String(ev["from_version"])}</th><th scope="col">Version {String(ev["to_version"])}</th></tr></thead>
              <tbody>
                <tr><th scope="row">Required fields</th><td>{REQUIRED_FIELDS.join(", ")}</td><td>{REQUIRED_FIELDS.join(", ")}, <strong>channel</strong></td></tr>
                <tr><th scope="row">Declared in the contract</th><td>until the operator bumps it</td><td>from {String(ev["bumped_at"])}</td></tr>
                <tr><th scope="row">The first page declaring it</th><td>—</td><td>batch {String(ev["quarantined_batch"])}: {String(ev["rows_quarantined_whole"])} rows quarantined whole, SCHEMA_CHANGED, checkpoint does not move</td></tr>
                <tr><th scope="row">After the bump</th><td>—</td><td>window fetched again as {String(ev["refetch_batch"])}: {String(ev["accepted_after_the_bump"])} rows accepted</td></tr>
              </tbody>
            </table>
          </Scroll>
          <Meaning>Batches in the quarantined state here: {changed.map((b) => `${b["batch_id"]} (${b["source_id"]})`).join(", ") || "none"}. The contract&apos;s expected <code>schema_version</code> only changes by an explicit operator bump; the pipeline never adopts a new version silently. <ScopeTag basis="complete" /> for the batch facts; the field list for v2 comes from the generator&apos;s injection manifest.</Meaning>
        </>
      ) : <p className="meaning" data-testid="no-version-change">No source in this dataset changes its schema version.</p>}
    </Panel>
  );
}
const SAMPLE = '{"record_id":"ORD-9001","quantity":2,"unit_price":"12.50","amount":"25.00","event_ts":"2026-10-04T08:00:00Z"}';
function Tester({ ds }: { ds: Dataset }) {
  const sources = ds.acc["source_contracts"]!;
  const [src, setSrc] = useState(sources[0]?.["source_id"] ?? "");
  const [declared, setDeclared] = useState("");
  const [text, setText] = useState(SAMPLE);
  const contract = sources.find((s) => s["source_id"] === src);
  const want = String(contract?.["schema_version"] ?? "");
  const eff = declared || want;
  let result: { tone: "ok" | "bad"; text: string };
  try {
    const payload = JSON.parse(text);
    if (eff !== want) result = { tone: "bad", text: `SCHEMA_CHANGED: the batch declares version ${eff} but the contract expects ${want}; the whole batch is quarantined and the checkpoint does not move.` };
    else { const r = contractReason(payload); result = r ? { tone: "bad", text: `Quarantined: ${r}.` } : { tone: "ok", text: "Accepted by the contract (if its key is new; a known key would be a duplicate first)." }; }
  } catch { result = { tone: "bad", text: "Not valid JSON: nothing to check." }; }
  return (
    <Panel id="tester" title="Try the contract on a record">
      <Meaning>Evaluated in your browser by the same function the pipeline mirrors. Edit the record or the declared version; nothing is stored or sent.</Meaning>
      <div className="controls">
        <label>Source <select value={src} onChange={(e) => { setSrc(e.target.value); setDeclared(""); }} data-testid="tester-source">{sources.map((s) => <option key={s["source_id"]} value={s["source_id"]}>{s["source_id"]}</option>)}</select></label>
        <label>Declared schema version <input value={declared} placeholder={want} onChange={(e) => setDeclared(e.target.value)} data-testid="tester-version" size={4} /></label>
      </div>
      <label className="block">Payload (JSON)<textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} data-testid="tester-payload" spellCheck={false} /></label>
      <p data-testid="tester-result" role="status"><Status tone={result.tone}>{result.text}</Status></p>
    </Panel>
  );
}
function Fetching({ ds }: { ds: Dataset }) {
  const r = ds.retry;
  return (
    <Panel id="fetching" title="Fetching: cursors, rate limits and retry-after" scope={r ? "complete" : undefined}>
      {r ? (
        <>
          <Meaning>A source is fetched page by page from a cursor. A rate-limited page carries a retry-after hint; a retry never happens sooner, and a cursor that repeats stops the fetch (CURSOR_LOOP). Recomputed from the published fetch log.</Meaning>
          <dl className="readouts" data-testid="fetch-stats">
            <div className="readout"><dt>Fetches logged</dt><dd><span className="readout__v" data-figure="fetch-rows">{n0(r.fetch_rows)}</span></dd></div>
            <div className="readout"><dt>Rate-limited responses</dt><dd><span className="readout__v" data-figure="rate-limited">{n0(r.rate_limited_responses)}</span><span className="readout__u">on {r.sources_rate_limited.join(", ")}</span></dd></div>
            <div className="readout"><dt>Retries honouring retry-after</dt><dd><span className="readout__v" data-figure="honoured">{n0(r.retries_honouring_retry_after)}</span><span className="readout__u">of {n0(r.retries)}</span></dd><dd className="readout__n">{r.retries_too_soon} retried too soon; slack beyond the hint {r.min_slack_seconds} to {r.max_slack_seconds} s</dd></div>
            <div className="readout"><dt>Cursor loops stopped</dt><dd><span className="readout__v" data-figure="cursor-loops">{n0(r.cursor_loops)}</span></dd></div>
          </dl>
        </>
      ) : <p className="meaning">The golden fixture has no fetch log; the fetch experiments run on the case study.</p>}
    </Panel>
  );
}
function Checkpoints({ ds }: { ds: Dataset }) {
  const sources = ds.acc["source_contracts"]!;
  const [sid, setSid] = useParam("source", sources[0]?.["source_id"] ?? "");
  const rows = ds.acc["checkpoints"]!.filter((c) => c["source_id"] === sid).sort((a, b) => b["version_number"] - a["version_number"]).slice(0, 8);
  return (
    <Panel id="checkpoints" title="Latest checkpoints" scope="complete">
      <label>Source <select value={sid} onChange={(e) => setSid(e.target.value)} data-testid="checkpoint-source">{sources.map((s) => <option key={s["source_id"]} value={s["source_id"]}>{s["source_id"]}</option>)}</select></label>
      <Meaning>A batch commits atomically with its checkpoint: accepted rows, quarantine rows and the checkpoint row (version + 1) are one transaction. A replay from the last committed cursor is idempotent on the source key.</Meaning>
      <Scroll label="Latest checkpoints of the source">
        <table className="data" data-testid="checkpoint-table">
          <thead><tr><th scope="col">Version</th><th scope="col">Batch</th><th scope="col">Committed</th><th scope="col">Cursor</th></tr></thead>
          <tbody>{rows.map((c) => <tr key={c["checkpoint_id"]}><td>v{c["version_number"]}</td><th scope="row"><code>{c["batch_id"]}</code></th><td>{c["committed_at"]}</td><td>{c["committed_cursor"]}</td></tr>)}</tbody>
        </table>
      </Scroll>
    </Panel>
  );
}
export function SourcesView() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="05" title="Source contract">
            <p className="lede">What each source promises, which schema version the pipeline expects of it, and what happens when a delivery does not match.</p>
          </ViewHead>
          <Table ds={ds} />
          <Compare ds={ds} />
          <Tester ds={ds} />
          <Fetching ds={ds} />
          <Checkpoints ds={ds} />
        </>
      )}
    </WithData>
  );
}
