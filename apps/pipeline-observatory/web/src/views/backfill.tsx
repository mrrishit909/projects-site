import { useMemo, useState } from "react";
import { Meaning, Panel, Scroll, SimNote, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import { findOverlap } from "../domain/backfill";
import type { Row } from "../domain/contract";
import { p6, ratio } from "../domain/num";
import { decideBackfill } from "../domain/sim";
import { dayPartitions } from "../domain/time";
import { n0, pct } from "../lib/format";
import { addSimBackfill, resetSim, useSimBackfills, verifySimPartition } from "../state/sim";

interface Req { id: string; row: Row; refused: boolean; overlapsWith: string | null }
function requests(ds: Dataset): Req[] {
  const acc = ds.acc["backfill_requests"]!;
  const out: Req[] = acc.map((row) => ({ id: row["backfill_id"], row, refused: false, overlapsWith: null }));
  const earlier: Row[] = [];
  const all = [...acc, ...ds.result.imported.rejected.filter((r) => r.entity === "backfill_requests").map((r) => r.raw_row as Row)].sort((a, b) => (a["backfill_id"] < b["backfill_id"] ? -1 : 1));
  for (const row of all) {
    const isAcc = acc.includes(row);
    if (!isAcc) out.push({ id: row["backfill_id"], row, refused: true, overlapsWith: (findOverlap(earlier, row, true)?.["backfill_id"] as string | undefined) ?? null });
    else earlier.push(row);
  }
  return out.sort((a, b) => (a.id < b.id ? -1 : 1));
}
function Cells({ parts, label }: { parts: { partition: string; verified: boolean }[]; label: string }) {
  return (
    <ul className="cells" aria-label={label}>
      {parts.map((p) => <li key={p.partition} className={p.verified ? "is-on" : ""} title={`${p.partition}: ${p.verified ? "verified" : "not verified"}`}><span aria-hidden="true">{p.verified ? "✓" : "○"}</span><span className="visually-hidden">{p.partition} {p.verified ? "verified" : "not verified"}</span></li>)}
    </ul>
  );
}
function Table({ ds }: { ds: Dataset }) {
  const reqs = useMemo(() => requests(ds), [ds]);
  const B = ds.g.metrics.backfills;
  return (
    <Panel id="requests" title="Requests, partitions and progress" scope="complete">
      <Meaning>A request covers a half-open range [start, end) of daily UTC partitions. Coverage = verified partitions ÷ requested partitions. Two requests over overlapping ranges of one source cannot run together: the later one is refused with <code>BACKFILL_OVERLAP</code> and keeps its id. A range that only touches another (ends where it starts) does not overlap.</Meaning>
      <dl className="readouts" data-testid="backfill-totals">
        <div className="readout"><dt>Requested partitions</dt><dd><span className="readout__v" data-figure="requested">{n0(B.overall.requested_partitions)}</span></dd></div>
        <div className="readout"><dt>Verified partitions</dt><dd><span className="readout__v" data-figure="verified">{n0(B.overall.verified_partitions)}</span></dd></div>
        <div className="readout"><dt>Coverage</dt><dd><span className="readout__v" data-figure="coverage">{B.overall.coverage ?? "n/a"}</span><span className="readout__u">{B.overall.verified_partitions}/{B.overall.requested_partitions}</span></dd><dd className="readout__n"><span className="bar"><span className="bar__f" style={{ width: pct(B.overall.verified_partitions, B.overall.requested_partitions) }} /></span></dd></div>
        <div className="readout"><dt>Refused</dt><dd><span className="readout__v" data-figure="refused">{B.refused.length}</span><span className="readout__u">{B.refused.join(", ") || "none"}</span></dd></div>
      </dl>
      <Scroll label="Backfill requests">
        <table className="data" data-testid="backfill-table">
          <caption>{reqs.length} requests as published ({reqs.filter((r) => r.refused).length} refused on import).</caption>
          <thead><tr><th scope="col">Request</th><th scope="col">Source</th><th scope="col">Range [start, end)</th><th scope="col">Partitions</th><th scope="col">Verified</th><th scope="col">Coverage</th><th scope="col">Outcome</th></tr></thead>
          <tbody>
            {reqs.map((r) => {
              const m = B.requests[r.id];
              return (
                <tr key={r.id} data-req={r.id} data-refused={r.refused ? "true" : "false"}>
                  <th scope="row"><code>{r.id}</code></th><td>{r.row["source_id"]}</td><td>{String(r.row["start_at"]).slice(0, 10)} → {String(r.row["end_at"]).slice(0, 10)}</td>
                  <td><Cells parts={r.row["partitions"]} label={`Partitions of ${r.id}`} /></td>
                  <td data-k="verified">{m ? `${m.verified_partitions}/${m.requested_partitions}` : "—"}</td><td data-k="coverage">{m ? m.coverage : "—"}</td>
                  <td>{r.refused ? <Status tone="bad" k="refused">refused BACKFILL_OVERLAP{r.overlapsWith ? `: overlaps ${r.overlapsWith}` : ""}</Status> : <Status tone={m && m.verified_partitions === m.requested_partitions ? "ok" : "warn"}>{r.row["status"]}</Status>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Scroll>
    </Panel>
  );
}
function Console({ ds }: { ds: Dataset }) {
  const sources = ds.acc["source_contracts"]!.map((s) => s["source_id"] as string);
  const reqs = useMemo(() => requests(ds), [ds]);
  const sim = useSimBackfills();
  const [source, setSource] = useState(sources[0] ?? "");
  const [start, setStart] = useState("2026-09-01");
  const [end, setEnd] = useState("2026-09-03");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const submit = (): void => {
    // a request made here stays "requested" until every partition is marked verified; then it is complete and blocks nothing (the domain's rule: only requested or running requests block)
    const accepted = [...ds.acc["backfill_requests"]!, ...sim.filter((s) => s.accepted).map((s) => ({ backfill_id: s.backfill_id, source_id: s.source_id, start_at: s.start_at, end_at: s.end_at, status: s.verified >= s.partitions.length ? "complete" : "requested" }))];
    const ask = { source_id: source, start_at: `${start}T00:00:00Z`, end_at: `${end}T00:00:00Z` };
    const d = decideBackfill(accepted, ask);
    const maxId = Math.max(0, ...reqs.map((r) => Number(r.id.replace(/\D/g, "")) || 0));
    const id = `bf-${String(maxId + sim.length + 1).padStart(3, "0")}`;
    addSimBackfill({ backfill_id: id, source_id: source, start_at: ask.start_at, end_at: ask.end_at, accepted: d.accepted, code: d.code, message: d.message, partitions: d.partitions });
    setMsg({ ok: d.accepted, text: `${id}: ${d.accepted ? "accepted" : `refused ${d.code}`}: ${d.message}` });
  };
  return (
    <Panel id="console" title="Backfill console">
      <SimNote>A request here is judged by the domain&apos;s own overlap and alignment rules, then kept in browser memory. A refused request still consumes its id, as in the backend. Nothing is queued or fetched.</SimNote>
      <form className="controls" onSubmit={(e) => { e.preventDefault(); submit(); }} data-testid="backfill-form">
        <label>Source <select value={source} onChange={(e) => setSource(e.target.value)} data-testid="bf-source">{sources.map((s) => <option key={s} value={s}>{s}</option>)}</select></label>
        <label>Start (UTC midnight, inclusive) <input type="date" value={start} onChange={(e) => setStart(e.target.value)} data-testid="bf-start" /></label>
        <label>End (UTC midnight, exclusive) <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} data-testid="bf-end" /></label>
        <button type="submit" data-testid="bf-submit">Request backfill</button>
      </form>
      {msg ? <p role="status" data-testid="bf-result" className="sim-result"><Status tone={msg.ok ? "ok" : "bad"}>{msg.text}</Status></p> : <p className="meaning">Try 2026-08-22 to 2026-08-23 on src-inventory: bf-004 has settled partial with that partition unverified, so the request is accepted and backfills it again. While bf-004 was still running the published data refused the same range as bf-006. Make the request twice: the second is refused, because the first is requested.</p>}
      {sim.length > 0 && (
        <>
          <Scroll label="Backfill requests made this session">
            <table className="data" data-testid="sim-backfills">
              <caption>This session, in browser memory.</caption>
              <thead><tr><th scope="col">#</th><th scope="col">Source</th><th scope="col">Range</th><th scope="col">Outcome</th><th scope="col">Progress</th><th scope="col" /></tr></thead>
              <tbody>{sim.map((s) => (
                <tr key={s.n} data-sim={s.n}>
                  <td>{s.n}</td><td>{s.source_id}</td><td>{s.start_at.slice(0, 10)} → {s.end_at.slice(0, 10)}</td>
                  <td>{s.accepted ? <Status tone="ok">accepted, {s.partitions.length} partition{s.partitions.length === 1 ? "" : "s"}</Status> : <Status tone="bad">refused {s.code}</Status>}</td>
                  <td data-k="progress">{s.accepted ? <>{s.verified}/{s.partitions.length} = {p6(ratio(s.verified, s.partitions.length))}</> : "—"}</td>
                  <td>{s.accepted ? <button type="button" className="quiet" disabled={s.verified >= s.partitions.length} onClick={() => verifySimPartition(s.n)} aria-label={`Mark the next partition of request ${s.n} verified`}>Mark next partition verified</button> : null}</td>
                </tr>))}</tbody>
            </table>
          </Scroll>
          <p><button type="button" className="quiet" data-testid="bf-reset" onClick={() => { resetSim("backfill"); setMsg(null); }}>Reset the simulation</button></p>
        </>
      )}
      <Meaning>Daily partitions of a request: {dayPartitions(`${start}T00:00:00Z`, `${end}T00:00:00Z`).length || "none (the end must be after the start)"}. Ranges must start and end at UTC midnight.</Meaning>
    </Panel>
  );
}
export function BackfillView() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="08" title="Backfill console">
            <p className="lede">Re-reading history one daily partition at a time: which ranges were requested, which overlap, and how far each has got.</p>
          </ViewHead>
          <Table ds={ds} />
          <Console ds={ds} />
        </>
      )}
    </WithData>
  );
}
