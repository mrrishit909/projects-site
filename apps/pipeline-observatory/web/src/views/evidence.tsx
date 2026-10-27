import { useEffect, useMemo, useState } from "react";
import { Meaning, Panel, Scroll, ScopeTag, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import { datasetHash, ENTITY_FILES } from "../data/files";
import { METRIC_KEYS } from "../domain/contract";
import { canonicalJson, definitionHash, payloadHash } from "../domain/hashing";
import { sha256Hex } from "../domain/sha256";
import { n0, short } from "../lib/format";
import { useGoldenLab } from "../state/golden";

interface HashRow { id: string; label: string; ok: boolean | null; detail: string; basis: "complete" | "sample" | "recorded" }
function useHashes(ds: Dataset): { rows: HashRow[] | null; ms: number } {
  const lab = useGoldenLab();
  const [rows, setRows] = useState<HashRow[] | null>(null);
  const [ms, setMs] = useState(0);
  useEffect(() => {
    if (lab.status === "loading") return;
    const t0 = performance.now();
    const out: HashRow[] = [];
    if (ds.raw && ds.manifest) {
      const h = datasetHash(ds.raw);
      out.push({ id: "dataset", label: "dataset_hash of the 16 entity files", ok: h === ds.manifest.dataset_hash, detail: `recomputed ${short(h, 24)} · manifest ${short(ds.manifest.dataset_hash, 24)}`, basis: "complete" });
      const bad = ds.raw.raw_records.filter((r) => payloadHash(r["payload_json"]) !== r["payload_hash"]).length;
      out.push({ id: "payload", label: "payload_hash of every published raw record", ok: bad === 0, detail: `${n0(ds.raw.raw_records.length - bad)} of ${n0(ds.raw.raw_records.length)} match`, basis: "sample" });
      const dbad = ds.raw.model_definitions.filter((m) => definitionHash(m["definition"]) !== m["definition_hash"]).length;
      out.push({ id: "definition", label: "definition_hash of every model", ok: dbad === 0, detail: `${n0(ds.raw.model_definitions.length - dbad)} of ${n0(ds.raw.model_definitions.length)} match`, basis: "complete" });
      const okPubs = Object.values<{ content_hash_ok: boolean }>(ds.g.metrics.publications.publications).filter((p) => p.content_hash_ok).length;
      const nPubs = ds.raw.publications.length;
      out.push({ id: "content", label: "content_hash of every publication", ok: null, detail: `${n0(okPubs)} of ${n0(nPubs)} verify here: a content hash covers every accepted record of the publication, and only ${n0(ds.raw.raw_records.length)} raw rows are published. Not a failure: it cannot be checked here.`, basis: "sample" });
    } else {
      const bad = ds.acc["raw_records"]!.filter((r) => payloadHash(r["payload_json"]) !== r["payload_hash"]).length;
      out.push({ id: "payload", label: "payload_hash of every raw record", ok: bad === 0, detail: `${n0(ds.acc["raw_records"]!.length - bad)} of ${n0(ds.acc["raw_records"]!.length)} match`, basis: "complete" });
      const dbad = ds.acc["model_definitions"]!.filter((m) => definitionHash(m["definition"]) !== m["definition_hash"]).length;
      out.push({ id: "definition", label: "definition_hash of every model", ok: dbad === 0, detail: `${n0(ds.acc["model_definitions"]!.length - dbad)} of ${n0(ds.acc["model_definitions"]!.length)} match`, basis: "complete" });
      const okPubs = Object.values<{ content_hash_ok: boolean }>(ds.g.metrics.publications.publications).filter((p) => p.content_hash_ok).length;
      out.push({ id: "content", label: "content_hash of every publication", ok: okPubs === ds.acc["publications"]!.length, detail: `${okPubs} of ${ds.acc["publications"]!.length} match`, basis: "complete" });
    }
    if (lab.status === "ready") {
      const entries = Object.entries(lab.hashes);
      const bad = entries.filter(([f, h]) => sha256Hex(lab.texts[f]!) !== h).length;
      out.push({ id: "fixture", label: "golden fixture files against HASHES.json", ok: bad === 0, detail: `${entries.length - bad} of ${entries.length} files match their recorded sha-256`, basis: "complete" });
    }
    setRows(out);
    setMs(Math.round(performance.now() - t0));
  }, [ds, lab.status]); // eslint-disable-line react-hooks/exhaustive-deps
  return { rows, ms };
}
function Hashes({ ds }: { ds: Dataset }) {
  const { rows, ms } = useHashes(ds);
  return (
    <Panel id="hashes" title="Hashes recomputed in this browser">
      <Meaning>Three hash kinds (contract D-P8-10): <code>payload_hash</code> = sha-256 of the canonical JSON of a payload (sorted keys, compact separators, ASCII); <code>content_hash</code> = sha-256 of the sorted payload hashes of a publication&apos;s accepted records, joined by newlines; <code>definition_hash</code> = sha-256 of the model definition text. Computed here by a synchronous sha-256 written for this site and checked against <code>node:crypto</code> in CI.</Meaning>
      {rows === null ? <p className="notice" role="status">Recomputing hashes…</p> : (
        <Scroll label="Hash checks">
          <table className="data" data-testid="hash-table">
            <caption>{rows.length} checks, {ms} ms on this device.</caption>
            <thead><tr><th scope="col">Check</th><th scope="col">Result</th><th scope="col">Detail</th><th scope="col">Scope</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.id} data-check={r.id} data-ok={String(r.ok)}><th scope="row">{r.label}</th><td data-k="result">{r.ok === null ? <Status tone="idle">not verifiable here</Status> : r.ok ? <Status tone="ok">match</Status> : <Status tone="bad">mismatch</Status>}</td><td data-k="detail">{r.detail}</td><td><ScopeTag basis={r.basis} /></td></tr>)}</tbody>
          </table>
        </Scroll>
      )}
    </Panel>
  );
}
function Provenance({ ds }: { ds: Dataset }) {
  const m = ds.manifest;
  return (
    <Panel id="provenance" title="Provenance">
      <dl className="facts" data-testid="provenance">
        <div><dt>dataset_version</dt><dd data-k="dataset_version">{ds.provenance.dataset_version}</dd></div>
        <div><dt>dataset_hash</dt><dd data-k="dataset_hash"><code className="wrap">{ds.provenance.dataset_hash}</code></dd></div>
        <div><dt>generated_at</dt><dd data-k="generated_at">{ds.provenance.generated_at}</dd></div>
        <div><dt>code_sha</dt><dd data-k="code_sha">{ds.provenance.code_sha ?? "not recorded"}{ds.provenance.code_sha ? "" : " (the manifest records it only when CI publishes the snapshot)"}</dd></div>
        {m && <div><dt>Generator</dt><dd>{String(m.generator?.["name"] ?? "n/a")}, seed {String(m.generator?.["seed"] ?? m.seed ?? "n/a")}, contract v{m.contract_version}</dd></div>}
        {m && <div><dt>Window</dt><dd>{m.window_start} to {m.window_end}, as of {m.as_of}</dd></div>}
      </dl>
    </Panel>
  );
}
function Digests({ ds }: { ds: Dataset }) {
  const rows = useMemo(() => METRIC_KEYS.map((k) => [k, sha256Hex(canonicalJson(ds.g.metrics[k]))] as const), [ds]);
  return (
    <Panel id="digests" title="Metric-block digests">
      <Meaning>sha-256 of the canonical JSON of each of the eleven metric blocks this page computed. CI compares the same digests with the ones the Python domain produced over the same files (<code>scripts/snapshot-reference.json</code>).{ds.id === "snapshot" ? " Blocks that depend on raw rows describe the 2,000-row sample." : ""}</Meaning>
      <Scroll label="Metric-block digests">
        <table className="data" data-testid="digest-table"><thead><tr><th scope="col">Block</th><th scope="col">sha-256</th></tr></thead>
          <tbody>{rows.map(([k, d]) => <tr key={k} data-block={k}><th scope="row"><code>{k}</code></th><td><code title={d}>{d}</code></td></tr>)}</tbody></table>
      </Scroll>
    </Panel>
  );
}
function Counts({ ds }: { ds: Dataset }) {
  if (!ds.raw || !ds.manifest) return null;
  const m = ds.manifest;
  return (
    <Panel id="counts" title="Row counts: published and complete world" scope="complete">
      <Scroll label="Row counts">
        <table className="data" data-testid="count-table"><caption>Rows of each entity file as published, against the manifest&apos;s row counts of the complete world.</caption>
          <thead><tr><th scope="col">File</th><th scope="col">Published</th><th scope="col">Manifest row_counts</th><th scope="col">Complete world</th></tr></thead>
          <tbody>{ENTITY_FILES.map((n) => { const pub = (ds.raw as unknown as Record<string, unknown[]>)[n]!.length; const full = (m.full_world?.["row_counts"] as Record<string, number> | undefined)?.[n]; return <tr key={n}><th scope="row"><code>{n}</code></th><td>{n0(pub)}</td><td>{n0(m.row_counts[n] ?? 0)}</td><td>{full === undefined ? "same" : n0(full)}</td></tr>; })}</tbody></table>
      </Scroll>
    </Panel>
  );
}
function Designed({ ds }: { ds: Dataset }) {
  if (!ds.manifest) return null;
  const ids = [...new Set(ds.claims.map((c) => c.id))];
  return (
    <Panel id="designed" title="Designed relationships DR-01 to DR-05">
      <Meaning>The generator built five relationships on purpose and recorded how each came out. Every figure below is re-derived here from the published files where they allow it. <ScopeTag basis="complete" /> = recomputed from files published in full; <ScopeTag basis="sample" /> = recomputed over the sample (may differ from the complete world); <ScopeTag basis="recorded" /> = cannot be recomputed from the published files.</Meaning>
      {ids.map((id) => {
        const dr = ds.manifest!.designed_relationships?.find((d) => d["id"] === id);
        const cs = ds.claims.filter((c) => c.id === id);
        const holds = cs.filter((c) => c.ok === true).length, fails = cs.filter((c) => c.ok === false).length, rec = cs.filter((c) => c.ok === null).length;
        return (
          <details key={id} className="disc" open={id === "DR-01" || id === "DR-02"} data-dr={id}>
            <summary><strong>{id}</strong> {String(dr?.["name"] ?? "")} · <span data-k="holds">{holds}</span> hold, <span data-k="fails">{fails}</span> differ on the sample, <span data-k="recorded">{rec}</span> recorded only</summary>
            <p className="meaning">{String(dr?.["statement"] ?? "")}</p>
            <Scroll label={`Figures of ${id}`}>
              <table className="data">
                <thead><tr><th scope="col">Figure</th><th scope="col">Manifest</th><th scope="col">Recomputed here</th><th scope="col">Basis</th><th scope="col">Result</th></tr></thead>
                <tbody>{cs.map((c) => (
                  <tr key={c.key} data-claim={`${c.id}:${c.key}`} data-ok={String(c.ok)}>
                    <th scope="row">{c.label}</th><td className="wrap">{short(JSON.stringify(c.want), 80)}</td><td className="wrap">{c.basis === "recorded" ? "—" : short(JSON.stringify(c.got), 80)}</td><td><ScopeTag basis={c.basis} /></td>
                    <td>{c.ok === null ? <Status tone="idle">recorded only</Status> : c.ok ? <Status tone="ok">equal</Status> : <Status tone="warn">differs on the sample</Status>}</td>
                  </tr>))}</tbody>
              </table>
            </Scroll>
          </details>
        );
      })}
    </Panel>
  );
}
function Injections({ ds }: { ds: Dataset }) {
  if (!ds.injections.length) return null;
  return (
    <Panel id="injections" title="Injected defects INJ-01 to INJ-12">
      <Meaning>One defect per test P08-TEST-01..12. Each lists machine-checkable claims about the <em>complete</em> world; they are evaluated here over the sample, so some describe batches or publications whose rows are not published and are marked as such, never counted as failures.</Meaning>
      <Scroll label="Injected defects">
        <table className="data" data-testid="injection-table">
          <thead><tr><th scope="col">Defect</th><th scope="col">Test</th><th scope="col">Where proven</th><th scope="col">Checks holding here</th><th scope="col">Expected handling</th></tr></thead>
          <tbody>{ds.injections.map((i) => {
            const cs = ds.injection.filter((c) => c.injection === i["id"]);
            const ok = cs.filter((c) => c.ok).length;
            return <tr key={i["id"]} data-inj={i["id"]}><th scope="row"><code>{i["id"]}</code> {i["name"]}</th><td>{i["test"]}</td><td>{i["location"] === "both" ? "backend CI and the published data" : "backend CI replay only"}</td><td data-k="checks">{cs.length === 0 ? "none machine-checkable" : `${ok} of ${cs.length}`}</td><td>{i["expected_handling"]}</td></tr>;
          })}</tbody>
        </table>
      </Scroll>
      <p className="meaning" data-testid="inj-total">{ds.injection.filter((c) => c.ok).length} of {ds.injection.length} machine-checkable claims hold over the sample; {ds.injection.filter((c) => !c.ok).length} describe rows that are not published ({[...new Set(ds.injection.filter((c) => !c.ok).map((c) => c.injection))].join(", ")}).</p>
    </Panel>
  );
}
function Disclosures({ ds }: { ds: Dataset }) {
  const d = (ds.manifest?.generator?.["disclosures"] ?? []) as string[];
  const steps = ds.events.reduce((a, e) => a + (e["steps"] as unknown[]).length, 0);
  if (!d.length) return null;
  return (
    <Panel id="disclosures" title="What the generator discloses about itself">
      <ol className="plain">{d.map((t) => <li key={t.slice(0, 40)}>{t}</li>)}</ol>
      <p className="meaning">{ds.events.length} replay events ({ds.events.map((e) => e["event_id"]).join(", ")}; {steps} steps) run after the as-of on a fresh database seeded from these files; they are executed by the backend CI (Mode A) and are not replayed in the browser.</p>
    </Panel>
  );
}
export function EvidenceView() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="11" title="Evidence">
            <p className="lede">What was checked, by what, and what it cannot show. Hashes are recomputed in your browser; designed relationships and injected defects are re-derived from the published files.</p>
          </ViewHead>
          <Provenance ds={ds} />
          <Hashes ds={ds} />
          <Counts ds={ds} />
          <Digests ds={ds} />
          <Designed ds={ds} />
          <Injections ds={ds} />
          <Disclosures ds={ds} />
        </>
      )}
    </WithData>
  );
}
