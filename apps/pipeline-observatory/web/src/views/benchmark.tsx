import { useState } from "react";
import { Meaning, Panel, Scroll, ScopeTag, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import { buildInputs, datasetHash, ENTITY_FILES } from "../data/files";
import { runPipeline } from "../domain/metrics";
import { p6, ratio } from "../domain/num";
import { n0 } from "../lib/format";

function Recorded({ ds }: { ds: Dataset }) {
  const sample = ds.g.metrics.processing_rate;
  const rec = (ds.manifest?.stats?.["processing_rate"] ?? null) as Record<string, string | number> | null;
  return (
    <Panel id="recorded" title="The recorded processing measurement" scope={rec ? "recorded" : "complete"}>
      <Meaning>Processing rate = accepted records of the measured batch ÷ measured processing seconds (6 places). It is one measurement of one synthetic batch, with its hardware and cache state disclosed. <strong>It is not a benchmark</strong>: the seconds are a synthetic value of the world, not a CI timing.</Meaning>
      <Scroll label="Processing measurement">
        <table className="data" data-testid="bench-recorded">
          <thead><tr><th scope="col" /><th scope="col">Recorded (complete world)</th><th scope="col">Recomputed here{ds.id === "snapshot" ? " (2,000-row sample)" : ""}</th></tr></thead>
          <tbody>
            <tr><th scope="row">Batch</th><td colSpan={2}>{String(ds.manifest?.config["processing_measurement"]?.["batch_id"] ?? ds.acc["ingestion_batches"]![0]?.["batch_id"] ?? "n/a")}</td></tr>
            <tr><th scope="row">Accepted records</th><td data-k="rec-accepted">{rec ? String(rec["accepted_records"]) : "—"}</td><td data-k="accepted">{sample.accepted_records}</td></tr>
            <tr><th scope="row">Measured seconds</th><td>{rec ? String(rec["measured_seconds"]) : "—"}</td><td data-k="seconds">{sample.measured_seconds ?? "n/a"}</td></tr>
            <tr><th scope="row">Records per second</th><td data-k="rec-rate">{rec ? String(rec["records_per_second"]) : "—"}</td><td data-k="rate">{sample.records_per_second ?? "n/a"}</td></tr>
            <tr><th scope="row">Hardware</th><td colSpan={2}>{sample.hardware ?? "n/a"}</td></tr>
            <tr><th scope="row">Cache state</th><td colSpan={2}>{sample.cache_state ?? "n/a"}</td></tr>
          </tbody>
        </table>
      </Scroll>
      {rec && rec["accepted_records"] !== sample.accepted_records && <Meaning>The batch accepted {String(rec["accepted_records"])} records in the complete world and {sample.accepted_records} over the sample: a key accepted in an unsampled earlier batch is invisible to the sample, so one more row looks new. The rates differ for that reason only.</Meaning>}
    </Panel>
  );
}
function Size({ ds, bytes }: { ds: Dataset; bytes: Record<string, number> }) {
  const raw = ds.raw;
  if (!raw || !ds.manifest) return <Panel id="size" title="Size"><p className="meaning">The golden fixture is {n0(Object.values(bytes).reduce((a, b) => a + b, 0))} bytes in {Object.keys(bytes).length} files; the published snapshot is measured on the snapshot view.</p></Panel>;
  const m = ds.manifest;
  const total = ENTITY_FILES.reduce((a, n) => a + (bytes[`${n}.json`] ?? 0), 0);
  const cap = (m.sample?.["size_cap_bytes"] as number | undefined) ?? 5_000_000;
  return (
    <Panel id="size" title="Size of the published data" scope="complete">
      <Meaning>Bytes as served (UTF-8 length of each file as fetched); rows as published. The generator caps the published entity files at {n0(cap)} bytes and publishes a 2,000-row sample of the raw records to stay under it.</Meaning>
      <Scroll label="Published files, rows and bytes">
        <table className="data" data-testid="bench-size">
          <thead><tr><th scope="col">File</th><th scope="col">Rows published</th><th scope="col">Rows in the complete world</th><th scope="col">Bytes</th></tr></thead>
          <tbody>
            {ENTITY_FILES.map((n) => <tr key={n}><th scope="row"><code>{n}.json</code></th><td data-k="rows">{n0((raw as unknown as Record<string, unknown[]>)[n]!.length)}</td><td>{n0(Number(m.row_counts[n] ?? 0))}</td><td data-k="bytes">{n0(bytes[`${n}.json`] ?? 0)}</td></tr>)}
            <tr className="total"><th scope="row">16 entity files</th><td /><td /><td data-k="total-bytes" data-figure="total-bytes">{n0(total)}</td></tr>
          </tbody>
        </table>
      </Scroll>
      <p className="meaning" data-testid="size-note">Total {n0(total)} bytes of {n0(cap)} allowed ({n0(Math.floor((total * 100) / cap))}%). The manifest records {n0(Number(m.sample?.["entity_bytes"] ?? 0))} bytes for the same files{total === Number(m.sample?.["entity_bytes"]) ? ", which is exactly what was served" : ` (served bytes differ by ${n0(Math.abs(total - Number(m.sample?.["entity_bytes"] ?? 0)))}, line endings)`}. {n0(bytes["manifest.json"] ?? 0)} bytes of manifest and {n0(bytes["injection-manifest.json"] ?? 0)} of injection manifest come on top.</p>
    </Panel>
  );
}
interface Timing { runs: number[]; hashMs: number; accepted: number; cores: number | null; memory: number | null }
function Live({ ds }: { ds: Dataset }) {
  const [t, setT] = useState<Timing | null>(null);
  const [busy, setBusy] = useState(false);
  if (!ds.raw || !ds.manifest) return <Panel id="live" title="Measure in this browser"><p className="meaning">Switch to the snapshot to measure the full pipeline here; the golden fixture is too small to time.</p></Panel>;
  const run = (): void => {
    setBusy(true);
    setTimeout(() => {
      const raw = ds.raw!, m = ds.manifest!;
      const { data, publishedTotals } = buildInputs(m, raw);
      const runs: number[] = [];
      let accepted = 0;
      for (let i = 0; i < 3; i++) { const a = performance.now(); const r = runPipeline(data, publishedTotals); runs.push(Math.round(performance.now() - a)); accepted = r.golden.metrics.ingestion.overall.accepted_unique; }
      const h0 = performance.now(); datasetHash(raw); const hashMs = Math.round(performance.now() - h0);
      const nav = navigator as Navigator & { deviceMemory?: number };
      setT({ runs, hashMs, accepted, cores: nav.hardwareConcurrency ?? null, memory: nav.deviceMemory ?? null });
      setBusy(false);
    }, 20);
  };
  const best = t ? Math.min(...t.runs) : 0;
  return (
    <Panel id="live" title="Measure in this browser">
      <Meaning>Runs the TypeScript pipeline over the published snapshot three times on <em>your</em> device and times it. <strong>This is not CI, not stored and not comparable with the recorded figure</strong>: it depends on your hardware, browser and what else is running, and changes every run. Durations are whole milliseconds.</Meaning>
      <p><button type="button" onClick={run} disabled={busy} data-testid="bench-run">{busy ? "Measuring…" : "Run the pipeline here"}</button></p>
      {t && (
        <dl className="facts" data-testid="bench-result" aria-live="polite">
          <div><dt>Device</dt><dd>{t.cores ?? "unknown"} logical cores{t.memory ? `, about ${t.memory} GB reported` : ""}; measured with <code>performance.now()</code></dd></div>
          <div><dt>Pipeline, 3 runs</dt><dd data-k="runs">{t.runs.join(" ms, ")} ms</dd></div>
          <div><dt>Hash of the 16 files</dt><dd data-k="hash-ms">{t.hashMs} ms</dd></div>
          <div><dt>Throughput at the fastest run</dt><dd data-k="throughput">{best > 0 ? `${p6(ratio(t.accepted * 1000, best))} accepted records per second` : "faster than one millisecond: not reported"} ({n0(t.accepted)} accepted records of the sample ÷ {best} ms)</dd></div>
        </dl>
      )}
    </Panel>
  );
}
export function BenchmarkView() {
  return (
    <WithData>
      {(ds, bytes) => (
        <>
          <ViewHead mark="10" title="Benchmark evidence">
            <p className="lede">What was measured, on what, over how much data, and what each number can and cannot say.</p>
          </ViewHead>
          <Recorded ds={ds} />
          <Size ds={ds} bytes={bytes} />
          <Live ds={ds} />
          <Panel id="ci" title="What a CI benchmark would add">
            <p>The brief asks for measured hardware, size and duration <em>from CI</em>. No CI timing is part of the published snapshot: <code>code_sha</code> is <Status tone="idle">not recorded</Status> until a CI run publishes it, and the one stored measurement is a synthetic value of the generated world. Once the workflow publishes a run, its hardware, data size and duration belong beside the recorded measurement above, not in place of it. The delivery guarantee is unaffected: it is shown at the source-key boundary on the case study, not by speed.</p>
            <p className="meaning"><ScopeTag basis="recorded" /> for the recorded measurement; the live measurement is a local reading with no scope claim.</p>
          </Panel>
        </>
      )}
    </WithData>
  );
}
