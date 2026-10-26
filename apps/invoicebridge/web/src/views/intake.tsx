import { useMemo, useState } from "react";
import { importSequence, type ImportEvent } from "../domain/duplicates";
import { ViewHead } from "../components/layout";
import { Chip, Def, InvoiceLink, NotBuilt, Scroll, WithData } from "../components/ui";
import type { PipelineResult } from "../domain/pipeline";
import { isoZ } from "../domain/time";
import { short, stamp } from "../lib/format";

interface Resend { of: string; filename: string; canonical: string; imported_file: string }

function Intake({ result, golden }: { result: PipelineResult; golden: boolean }) {
  const invs = result.population.invoices;
  const byId = useMemo(() => new Map(invs.map((i) => [i.invoice_id, i])), [invs]);
  const seq = useMemo(() => importSequence(invs), [invs]);
  const N = seq.length;
  const [pos, setPos] = useState(golden ? N : Math.min(N, 300));
  const [resends, setResends] = useState<Resend[]>([]);
  const run = seq.slice(0, pos);
  const merged = run.filter((e) => e.verdict === "merged");
  const identity = merged.filter((e) => e.reason === "DUPLICATE_IDENTITY"), bytes = merged.filter((e) => e.reason === "DUPLICATE_SOURCE_BYTES");
  const groups = new Set(merged.map((e) => e.canonical)).size;
  const groupsOf = (reason: string): { canonical: string; key: string; members: ImportEvent[] }[] => {
    const m = new Map<string, { canonical: string; key: string; members: ImportEvent[] }>();
    for (const e of merged) {
      if (e.reason !== reason) continue;
      const key = reason === "DUPLICATE_IDENTITY" ? e.identity : `sha256:${byId.get(e.invoice_id)!.source_sha256}`;
      const g = m.get(`${e.canonical}|${key}`) ?? m.set(`${e.canonical}|${key}`, { canonical: e.canonical, key, members: [] }).get(`${e.canonical}|${key}`)!;
      g.members.push(e);
    }
    return [...m.values()].reverse();
  };
  const idGroups = groupsOf("DUPLICATE_IDENTITY"), shaGroups = groupsOf("DUPLICATE_SOURCE_BYTES");
  const latest = run.slice(-10).reverse();
  const resend = (e: ImportEvent): void => {
    const orig = byId.get(e.invoice_id)!;
    setResends((r) => [...r, { of: e.invoice_id, filename: `resent-${r.length + 1}-${orig.source_filename}`, canonical: e.canonical, imported_file: orig.source_filename }]);
  };
  const step = (n: number): void => setPos((p) => Math.min(N, p + n));
  return (
    <>
      <fieldset className="controls" data-testid="import-controls">
        <legend>Import the snapshot in order (imported_at, then invoice id)</legend>
        <label htmlFor="pos">Files imported: <output data-testid="pos-out">{pos.toLocaleString("en-US")}</output> of {N.toLocaleString("en-US")}</label>
        <input id="pos" type="range" min={0} max={N} step={1} value={pos} onChange={(e) => setPos(Number(e.target.value))} />
        <div className="btnrow">
          <button type="button" onClick={() => step(1)} disabled={pos >= N}>Import next file</button>
          <button type="button" onClick={() => step(10)} disabled={pos >= N}>Next 10</button>
          <button type="button" onClick={() => step(100)} disabled={pos >= N}>Next 100</button>
          <button type="button" onClick={() => setPos(N)} disabled={pos >= N}>Import all</button>
          <button type="button" onClick={() => { setPos(0); setResends([]); }}>Reset</button>
        </div>
        <p className="muted small">A simulation in browser memory: nothing is stored or sent. Each decision is the contract's rule applied to the facts, in import order, so the end state equals the batch result ({result.metrics.duplicates.rows_merged} merged) the overview reports.</p>
      </fieldset>
      <dl className="glance" data-testid="running-counts" aria-live="polite">
        <div data-figure="imported"><dt>Files imported</dt><dd>{pos}</dd></div>
        <div data-figure="distinct"><dt>Distinct invoices</dt><dd>{pos - merged.length}<small>canonical copies</small></dd></div>
        <div data-figure="merged_identity"><dt>Merged by identity</dt><dd>{identity.length}<small>re-sent, different bytes</small></dd></div>
        <div data-figure="merged_bytes"><dt>Merged by same bytes</dt><dd>{bytes.length}<small>same file, other name</small></dd></div>
        <div data-figure="groups"><dt>Duplicate groups</dt><dd>{groups}<small>counted once</small></dd></div>
      </dl>
      <section className="panel" aria-labelledby="dup-h">
        <h2 id="dup-h">Duplicate detection <Def term="identity vs same bytes">The same bytes under another filename are one obligation (checked first, by sha256). A re-scanned or re-sent PDF has different bytes, so identity decides: same vendor, same invoice number once upper-cased and stripped to letters and digits, same invoice date and same computed total. The earliest import is canonical; later copies are merged, never rejected, and keep their row and source hash as lineage.</Def></h2>
        <div className="two" data-testid="dup-panel">
          <div>
            <h3>Identity groups <span className="count">{idGroups.length}</span></h3>
            <GroupTable rows={idGroups} kind="identity" />
          </div>
          <div>
            <h3>Same-bytes groups <span className="count">{shaGroups.length}</span></h3>
            <GroupTable rows={shaGroups} kind="bytes" />
          </div>
        </div>
      </section>
      <section className="panel" aria-labelledby="log-h">
        <h2 id="log-h">Latest imports</h2>
        {latest.length === 0 ? <p className="muted" data-testid="nothing-imported">Nothing imported yet. Use the controls above.</p> : (
          <Scroll label="Latest imports">
            <table className="grid" data-testid="import-log">
              <caption className="sr">The ten most recent imports, newest first</caption>
              <thead><tr><th scope="col" className="num">#</th><th scope="col">Imported</th><th scope="col">Invoice</th><th scope="col">File</th><th scope="col">Decision</th><th scope="col">Canonical</th><th scope="col">Simulate</th></tr></thead>
              <tbody>{latest.map((e) => (
                <tr key={e.invoice_id} data-verdict={e.verdict}>
                  <td className="num">{e.seq}</td><td className="mono">{stamp(isoZ(e.imported_at))}</td><td><InvoiceLink id={e.invoice_id} /></td><td className="mono">{byId.get(e.invoice_id)!.source_filename}</td>
                  <td>{e.verdict === "new" ? <Chip v="new">new invoice</Chip> : <Chip v={e.reason!} />}</td><td><InvoiceLink id={e.canonical} /></td>
                  <td><button type="button" className="linkish" onClick={() => resend(e)}>Re-send this file</button></td>
                </tr>))}</tbody>
            </table>
          </Scroll>
        )}
        {resends.length > 0 && (
          <div data-testid="resend-results" className="callout">
            <p><strong>Simulated re-sends</strong> (kept only in this page):</p>
            <ul className="plain">{resends.map((r, i) => <li key={i}>{r.imported_file} sent again as <span className="mono">{r.filename}</span>: same sha256, so <Chip v="DUPLICATE_SOURCE_BYTES" /> into <InvoiceLink id={r.canonical} />. Distinct invoices stay at {pos - merged.length}: one obligation.</li>)}</ul>
          </div>
        )}
      </section>
    </>
  );
}

function GroupTable({ rows, kind }: { rows: { canonical: string; key: string; members: ImportEvent[] }[]; kind: "identity" | "bytes" }) {
  if (rows.length === 0) return <p className="muted small" data-testid={`no-${kind}-groups`}>No {kind === "identity" ? "identity" : "same-bytes"} group yet.</p>;
  return (
    <Scroll label={`${kind} groups`}>
      <table className="grid grid--tight" data-testid={`${kind}-groups`}>
        <caption className="sr">The latest {kind} groups, newest first</caption>
        <thead><tr><th scope="col">Canonical</th><th scope="col">Merged into it</th><th scope="col">{kind === "identity" ? "Identity key" : "Source sha256"}</th></tr></thead>
        <tbody>{rows.slice(0, 8).map((g) => <tr key={`${g.canonical}${g.key}`}><td><InvoiceLink id={g.canonical} /></td><td>{g.members.map((m, i) => <span key={m.invoice_id}>{i > 0 && ", "}<InvoiceLink id={m.invoice_id} /></span>)}</td><td className="mono" title={g.key}>{kind === "identity" ? g.key : short(g.key.slice(7), 18)}</td></tr>)}</tbody>
      </table>
      {rows.length > 8 && <p className="muted small">Showing the latest 8 of {rows.length}.</p>}
    </Scroll>
  );
}

export function IntakeView() {
  return (
    <>
      <ViewHead eyebrow="Entry: import simulation" title="Intake and duplicate detection">
        <p className="lede">Replay the import of the snapshot file by file and watch the desk decide: a new invoice, or the same obligation arriving again, merged into the earliest copy by identity or by identical bytes.</p>
      </ViewHead>
      <WithData>{({ result, snapshot }) => <Intake result={result} golden={snapshot.golden} />}</WithData>
      <NotBuilt>OCR and file upload are not part of the site: the import is structured data already extracted, and the controls only move a position through it.</NotBuilt>
    </>
  );
}
