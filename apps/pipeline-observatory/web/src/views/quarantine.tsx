import { parseJsonExact } from "../domain/json";
import { useMemo, useState } from "react";
import { Empty, Meaning, Pager, Panel, Scroll, SimNote, Status, ViewHead, WithData, usePage } from "../components/ui";
import type { Dataset } from "../data/analyse";
import type { Row } from "../domain/contract";
import { retryAdvice, retryRow } from "../domain/sim";
import { downloadCsv } from "../lib/derive";
import { n0, short } from "../lib/format";
import { useParam } from "../router";
import { addSimQuarantine, resetSim, useSimQuarantine } from "../state/sim";

interface QRow { id: string; batch: string; source: string; key: string | null; reason: string; hash: string; payload: Row | null; advice: ReturnType<typeof retryAdvice> }
function rowsOf(ds: Dataset): QRow[] {
  const srcOf = new Map<string, string>(ds.acc["ingestion_batches"]!.map((b) => [b["batch_id"], b["source_id"]]));
  const payload = new Map<string, Row>();
  for (const r of ds.acc["raw_records"]!) payload.set(`${r["batch_id"]}\u0000${r["payload_hash"]}`, r["payload_json"]);
  return ds.acc["quarantine_records"]!.map((q) => ({ id: q["quarantine_id"], batch: q["batch_id"], source: srcOf.get(q["batch_id"]) ?? "?", key: q["source_key"] ?? null, reason: q["reason_code"], hash: q["payload_hash"],
    payload: payload.get(`${q["batch_id"]}\u0000${q["payload_hash"]}`) ?? null, advice: retryAdvice(q["reason_code"]) }));
}
const ADVICE_LABEL: Record<string, string> = { "correct-and-replay": "correct and replay", "refetch-after-bump": "bump the schema, then refetch", "no-retry-source-fix": "source must fix" };

function Desk({ ds }: { ds: Dataset }) {
  const all = useMemo(() => rowsOf(ds), [ds]);
  const [reason, setReason] = useParam("reason", "all");
  const [source, setSource] = useParam("source", "all");
  const [payload, setPayload] = useParam("payload", "any");
  const [q, setQ] = useParam("q", "");
  const reasons = useMemo(() => [...new Set(all.map((r) => r.reason))].sort(), [all]);
  const sources = useMemo(() => [...new Set(all.map((r) => r.source))].sort(), [all]);
  const filtered = all.filter((r) => (reason === "all" || r.reason === reason) && (source === "all" || r.source === source) && (payload === "any" || (payload === "yes") === (r.payload !== null)) && (!q || (r.key ?? "").toLowerCase().includes(q.toLowerCase()) || r.id.toLowerCase().includes(q.toLowerCase())));
  const page = usePage("page", 25, filtered.length);
  const [sel, setSel] = useParam("row", "");
  const clear = (): void => { setReason("all"); setSource("all"); setPayload("any"); setQ(""); };
  const sim = useSimQuarantine();
  const last = new Map<string, (typeof sim)[number]>();
  for (const s of sim) last.set(s.quarantine_id, s);
  const by = (reason: string): number => all.filter((r) => r.reason === reason).length;
  const selected = all.find((r) => r.id === sel) ?? null;
  return (
    <>
      <Panel id="reasons" title="Why rows are quarantined" scope="complete">
        <Meaning>A row that fails the contract is quarantined with a reason code and kept: <strong>nothing is silently dropped</strong>. A repeated key is a duplicate, never a quarantine. The published quarantine table has {n0(all.length)} rows, one per occurrence.</Meaning>
        <Scroll label="Quarantine rows by reason">
          <table className="data" data-testid="reason-table">
            <thead><tr><th scope="col">Reason</th><th scope="col">Rows</th><th scope="col">Retry disposition</th></tr></thead>
            <tbody>{reasons.map((r) => <tr key={r} data-reason={r}><th scope="row"><code>{r}</code></th><td data-k="rows">{n0(by(r))}</td><td>{retryAdvice(r).text}</td></tr>)}</tbody>
          </table>
        </Scroll>
      </Panel>

      <Panel id="desk" title="The desk" scope="complete">
        <SimNote>Retrying, parking or discarding below changes nothing published and writes nothing; it only records what you decided, here, until you reload.</SimNote>
        <form className="controls" onSubmit={(e) => e.preventDefault()} aria-label="Filters" data-testid="q-filters">
          <label>Reason <select value={reason} onChange={(e) => setReason(e.target.value)} data-testid="f-reason"><option value="all">all reasons</option>{reasons.map((r) => <option key={r} value={r}>{r}</option>)}</select></label>
          <label>Source <select value={source} onChange={(e) => setSource(e.target.value)} data-testid="f-source"><option value="all">all sources</option>{sources.map((r) => <option key={r} value={r}>{r}</option>)}</select></label>
          <label>Payload <select value={payload} onChange={(e) => setPayload(e.target.value)} data-testid="f-payload"><option value="any">any</option><option value="yes">published (in the sample)</option><option value="no">not published</option></select></label>
          <label>Search key or id <input type="search" value={q} onChange={(e) => setQ(e.target.value)} data-testid="f-q" placeholder="e.g. ORD-0000" /></label>
          <button type="button" className="quiet" onClick={clear} data-testid="f-clear">Clear filters</button>
        </form>
        <p className="meaning" data-testid="q-count">{n0(filtered.length)} of {n0(all.length)} rows match. <button type="button" className="quiet" data-testid="export-quarantine" onClick={() => downloadCsv("quarantine-rows.csv", ["quarantine_id", "batch_id", "source_id", "source_key", "reason_code", "payload_hash", "payload_published"], filtered.map((r) => [r.id, r.batch, r.source, r.key, r.reason, r.hash, r.payload ? "yes" : "no"]))}>Download the {n0(filtered.length)} matching rows (CSV)</button></p>
        {filtered.length === 0 ? <Empty onClear={clear}>No quarantined row matches these filters.</Empty> : (
          <>
            <Scroll label="Quarantined rows">
              <table className="data" data-testid="q-table">
                <caption>Quarantined rows, {page.from + 1} to {page.to} of {n0(filtered.length)}. Sorted as published.</caption>
                <thead><tr><th scope="col">Id</th><th scope="col">Batch</th><th scope="col">Source key</th><th scope="col">Reason</th><th scope="col">Retry disposition</th><th scope="col">Payload</th><th scope="col">Simulated</th><th scope="col"><span className="visually-hidden">Open</span></th></tr></thead>
                <tbody>
                  {filtered.slice(page.from, page.to).map((r) => {
                    const s = last.get(r.id);
                    return (
                      <tr key={r.id} data-qid={r.id} className={r.id === sel ? "is-sel" : ""}>
                        <th scope="row"><code>{short(r.id, 22)}</code></th><td><code>{r.batch}</code><br /><span className="sub">{r.source}</span></td><td className="wrap">{r.key ?? <span className="sub">(no key)</span>}</td>
                        <td data-k="reason"><code>{r.reason}</code></td><td>{ADVICE_LABEL[r.advice.disposition]}</td><td>{r.payload ? "published" : <span className="sub">not published</span>}</td>
                        <td data-k="sim">{s ? <Status tone={s.outcome === "accepted" ? "ok" : s.action === "discard" ? "idle" : "warn"}>{s.action}: {s.outcome}</Status> : <span className="sub">—</span>}</td>
                        <td><button type="button" className="quiet" onClick={() => setSel(r.id)} aria-label={`Open ${r.id}`} data-testid={`open-${r.id}`}>Open</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Scroll>
            <Pager {...page} total={filtered.length} label="Quarantined rows" />
          </>
        )}
      </Panel>
      {selected ? <Detail ds={ds} row={selected} close={() => setSel("")} /> : <p className="meaning">Open a row to see its retry disposition and, where its payload is published, replay a corrected copy.</p>}
      <Sim all={all} />
    </>
  );
}
function Detail({ ds, row, close }: { ds: Dataset; row: QRow; close: () => void }) {
  const [text, setText] = useState(() => (row.payload ? JSON.stringify(row.payload, null, 1) : ""));
  const [why, setWhy] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const keys = useMemo(() => new Set<unknown>(ds.result.facts.accepted.filter((a) => a.source_id === row.source).map((a) => a.key)), [ds, row.source]);
  const retry = (): void => {
    let payload: unknown;
    try { payload = parseJsonExact(text); } catch { setResult("The payload is not valid JSON; nothing was replayed."); return; }
    const o = retryRow(row.key, payload, keys, ds.g.cutoff);
    const outcome = o.kind === "accepted" ? "accepted" : o.kind === "duplicate" ? "duplicate" : `still quarantined (${o.reason})`;
    addSimQuarantine({ quarantine_id: row.id, action: "retry", outcome: o.kind === "quarantined" ? `still quarantined: ${o.reason}` : o.kind, reason: o.reason, note: text.slice(0, 80) });
    setResult(`Replayed as a new row of ${row.source}: ${outcome}. ${o.kind === "accepted" ? "Simulated delta: quarantined −1, accepted +1." : o.kind === "duplicate" ? "The key check runs first: its key is already accepted, so it is counted as a duplicate, not a second record." : "It stays quarantined, with a reason code."}`);
  };
  return (
    <Panel id="detail" title={`Row ${row.id}`}>
      <dl className="facts" data-testid="q-detail">
        <div><dt>Batch and source</dt><dd>{row.batch} · {row.source}</dd></div>
        <div><dt>Source key</dt><dd>{row.key ?? "(no key: MISSING_FIELD)"}</dd></div>
        <div><dt>Reason</dt><dd><code>{row.reason}</code></dd></div>
        <div><dt>Payload hash</dt><dd title={row.hash}><code>{short(row.hash, 20)}</code></dd></div>
        <div><dt>Retry disposition</dt><dd data-k="advice">{row.advice.text}</dd></div>
      </dl>
      {row.payload ? (
        <div>
          <label className="block">Payload to replay (JSON, editable)<textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} data-testid="q-payload" /></label>
          <p className="actions">
            <button type="button" onClick={retry} data-testid="q-retry">Retry in memory</button>
            <button type="button" className="quiet" data-testid="q-park" onClick={() => { addSimQuarantine({ quarantine_id: row.id, action: "park", outcome: "parked", reason: null, note: "" }); setResult("Parked: left in quarantine, marked for the source owner."); }}>Park</button>
            <label className="inline">Reason to discard <input value={why} onChange={(e) => setWhy(e.target.value)} data-testid="q-why" placeholder="required" /></label>
            <button type="button" className="quiet" data-testid="q-discard" disabled={!why.trim()} onClick={() => { addSimQuarantine({ quarantine_id: row.id, action: "discard", outcome: "discarded", reason: why.trim(), note: "" }); setResult(`Discarded with a recorded reason: “${why.trim()}”. The row stays in the evidence list; nothing is silently dropped.`); }}>Discard with reason</button>
            <button type="button" className="quiet" onClick={close}>Close</button>
          </p>
        </div>
      ) : (
        <p className="notice" data-testid="q-nopayload">This row&apos;s payload is not among the 2,000 published raw rows (only its hash and reason are), so it cannot be replayed in the browser. {row.advice.disposition === "refetch-after-bump" ? "Its batch is refetched after the schema bump." : "The source would be asked to resend it."} <button type="button" className="quiet" onClick={() => { addSimQuarantine({ quarantine_id: row.id, action: "park", outcome: "parked", reason: null, note: "" }); setResult("Parked: left in quarantine."); }}>Park</button> <button type="button" className="quiet" onClick={close}>Close</button></p>
      )}
      {result ? <p role="status" className="sim-result" data-testid="q-result">{result}</p> : null}
      <p className="meaning">The key check runs against the accepted keys visible in the sample ({n0(keys.size)} for {row.source}); a key accepted in an unsampled batch is invisible here.</p>
    </Panel>
  );
}
function Sim({ all }: { all: QRow[] }) {
  const sim = useSimQuarantine();
  const last = new Map<string, (typeof sim)[number]>();
  for (const s of sim) last.set(s.quarantine_id, s);
  const vals = [...last.values()];
  const count = (f: (s: (typeof sim)[number]) => boolean): number => vals.filter(f).length;
  return (
    <Panel id="sim" title="What you did this session (browser memory)">
      <SimNote>Cleared on reload. The published table keeps all {n0(all.length)} rows.</SimNote>
      <dl className="readouts" data-testid="sim-counters">
        <div className="readout"><dt>Rows touched</dt><dd><span className="readout__v" data-figure="sim-touched">{vals.length}</span></dd></div>
        <div className="readout"><dt>Retried and accepted</dt><dd><span className="readout__v" data-figure="sim-accepted">{count((s) => s.action === "retry" && s.outcome === "accepted")}</span></dd></div>
        <div className="readout"><dt>Retried, still quarantined</dt><dd><span className="readout__v" data-figure="sim-still">{count((s) => s.action === "retry" && s.outcome.startsWith("still"))}</span></dd></div>
        <div className="readout"><dt>Retried, duplicate</dt><dd><span className="readout__v" data-figure="sim-duplicate">{count((s) => s.action === "retry" && s.outcome === "duplicate")}</span></dd></div>
        <div className="readout"><dt>Parked</dt><dd><span className="readout__v" data-figure="sim-parked">{count((s) => s.action === "park")}</span></dd></div>
        <div className="readout"><dt>Discarded with a reason</dt><dd><span className="readout__v" data-figure="sim-discarded">{count((s) => s.action === "discard")}</span></dd></div>
      </dl>
      {sim.length > 0 && (
        <Scroll label="Simulated actions in order">
          <table className="data" data-testid="sim-log"><thead><tr><th scope="col">#</th><th scope="col">Row</th><th scope="col">Action</th><th scope="col">Outcome</th></tr></thead>
            <tbody>{sim.map((s) => <tr key={s.n}><td>{s.n}</td><th scope="row"><code>{short(s.quarantine_id, 22)}</code></th><td>{s.action}</td><td>{s.outcome}{s.action === "discard" && s.reason ? ` — ${s.reason}` : ""}</td></tr>)}</tbody></table>
        </Scroll>
      )}
      <p><button type="button" className="quiet" onClick={() => resetSim("quarantine")} data-testid="sim-reset" disabled={sim.length === 0}>Reset the simulation</button></p>
    </Panel>
  );
}
export function QuarantineView() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="06 · entry screen" title="Quarantine desk">
            <p className="lede">Rows that failed the contract, why, and what an operator could do with each. The desk is a simulation: it shows the decision, it does not write one.</p>
          </ViewHead>
          <Desk ds={ds} />
        </>
      )}
    </WithData>
  );
}
