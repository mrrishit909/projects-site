import { useEffect, useState } from "react";
import { ViewHead } from "../components/layout";
import { ErrorState, Loading } from "../components/status";
import { Panel, V } from "../components/ui";
import { dataUrl, loadSnapshot } from "../data/load";
import { METRIC_KEYS } from "../domain/contract";
import { goldenOf, runPipeline } from "../domain/pipeline";
import { PyRandom, sha512 } from "../domain/pyrandom";
import { same } from "../lib/canon";
import { useStore } from "../state/store";

const CI = "https://github.com/mrrishit909/projects-site/actions/workflows/serviceflow-ci.yml";
const SOURCE = "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/serviceflow";

interface Row { label: string; ok: boolean; got: string; want: string }
type Run = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; rows: Row[] };
const show = (v: unknown): string => (v === null ? "null" : typeof v === "object" ? JSON.stringify(v) : String(v));
const hex = (b: ArrayBuffer | Uint8Array): string => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");

async function runChecks(): Promise<Row[]> {
  const snap = await loadSnapshot("golden");
  if (!snap.ok) throw new Error(snap.error);
  const res = await fetch(dataUrl("expected.json", "golden"));
  if (!res.ok) throw new Error(`golden/expected.json: HTTP ${res.status}`);
  const expected = await res.json() as ReturnType<typeof goldenOf>;
  const got = goldenOf(runPipeline(snap.snapshot.inputs));
  const rows: Row[] = [];
  for (const k of METRIC_KEYS) rows.push({ label: `metric ${k}`, ok: same(got.metrics[k], expected.metrics[k]), got: show(got.metrics[k]), want: show(expected.metrics[k]) });
  rows.push({ label: "ingest counts (12 entities)", ok: same(got.ingest.counts, expected.ingest.counts), got: "12 entities", want: "expected.json" });
  rows.push({ label: "rejected records", ok: same(got.ingest.rejected_records, expected.ingest.rejected_records), got: String(got.ingest.rejected_records.length), want: String(expected.ingest.rejected_records.length) });
  for (const k of ["waits_minutes", "mean_wait_minutes", "final_completion_minute", "events"] as const) {
    rows.push({ label: `simulation ${k}`, ok: same(got.simulation?.[k], expected.simulation?.[k]), got: show(got.simulation?.[k]).slice(0, 80), want: show(expected.simulation?.[k]).slice(0, 80) });
  }
  const want = new Uint8Array(await crypto.subtle.digest("SHA-512", new TextEncoder().encode("abc")));
  rows.push({ label: "SHA-512 of 'abc' equals the browser's WebCrypto", ok: hex(sha512(new TextEncoder().encode("abc"))) === hex(want), got: hex(sha512(new TextEncoder().encode("abc"))).slice(0, 16) + "…", want: hex(want).slice(0, 16) + "…" });
  const r = new PyRandom("20261026:arrivals");
  const a = r.random();
  rows.push({ label: "seeded generator reproduces CPython 3.11 (first draw of the seed 20261026 arrivals stream)", ok: a === 0.8334302546510539, got: String(a), want: "0.8334302546510539" });
  return rows;
}

export function Evidence() {
  const { state } = useStore();
  const [run, setRun] = useState<Run>({ status: "loading" });
  useEffect(() => {
    let live = true;
    runChecks().then((rows) => live && setRun({ status: "ready", rows })).catch((e: unknown) => live && setRun({ status: "error", error: e instanceof Error ? e.message : String(e) }));
    return () => { live = false; };
  }, []);
  const m = state.status === "ready" ? state.snapshot.manifest : null;
  return (
    <article>
      <ViewHead eyebrow="Evidence" title="Evidence and checks">
        <p className="lede">What was checked, where, and what this page can and cannot show. The first table is run live in your browser against the hand-derived golden fixture; the second list names the checks that run in CI and are not re-run here.</p>
      </ViewHead>

      <Panel title="Run now, in this browser: the golden fixture" id="live-checks">
        <p className="panel__note">The TypeScript domain replays the golden case (three tickets, one agent, one hour) and each of the 28 metric keys, the ingest counts, the simulation and two primitives are compared with the fixture's <code>expected.json</code>.</p>
        {run.status === "loading" ? <Loading /> : run.status === "error" ? <ErrorState message={run.error} /> : (
          <>
            <p className={`match ${run.rows.every((r) => r.ok) ? "ok" : "bad"}`} data-testid="live-summary">{run.rows.filter((r) => r.ok).length} of {run.rows.length} checks equal their expected value.</p>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Live checks, scrolls sideways on narrow screens">
              <table className="grid-table" data-testid="live-table">
                <caption className="sr-only">Golden checks computed in the browser</caption>
                <thead><tr><th scope="col">Check</th><th scope="col">Computed here</th><th scope="col">Expected</th><th scope="col">Result</th></tr></thead>
                <tbody>{run.rows.map((r) => <tr key={r.label} className={r.ok ? "" : "is-flag"}><th scope="row">{r.label}</th><td><code>{r.got}</code></td><td><code>{r.want}</code></td><td>{r.ok ? "equal" : "DIFFERS"}</td></tr>)}</tbody>
              </table>
            </div>
          </>
        )}
      </Panel>

      <Panel title="Checks that run in CI (not re-run on this page)" id="ci-checks">
        <p className="panel__note">This page does not say whether any CI run passed: open the workflow to see the runs and their artifacts.</p>
        <h3 className="h3">Mode A: Python domain, PostgreSQL and API (GitHub-hosted runner)</h3>
        <ul>
          <li>An independent reference check (standard library only) recomputes every golden figure from the fixture inputs.</li>
          <li>The golden fixture's seven file hashes are unchanged.</li>
          <li>The domain, migration, SQL reference, generator and API tests run under pytest against PostgreSQL 16.</li>
        </ul>
        <h3 className="h3">Mode B: this static site (GitHub-hosted runner)</h3>
        <ul>
          <li><code>npm ci</code> installs the locked dependencies.</li>
          <li><code>npm run check</code> type-checks, then the golden check compares the TypeScript domain, key by key, with the fixture, its two variants, the per-entity copy this site serves and the Python domain's results over the published snapshot (every metric by window and grouping, the ingest rejections and the three published simulation runs, event for event). It prints ALL OK with the number of checks.</li>
          <li><code>npm run build:pages</code> builds under the Pages base path and writes one index.html per route.</li>
          <li><code>npm run e2e</code> runs the entry journey in Chromium (golden figures, honesty labels, console errors fail the test) and takes full-page screenshots of every route at 360, 768, 1280 and 1920 px and at 200 % zoom, failing on any horizontal overflow; the screenshots and an index.json are uploaded as an artifact.</li>
        </ul>
        <p><a href={CI}>Open the CI workflow</a> · <a href={SOURCE}>Source on GitHub</a> <span className="muted">(branch business-data-lab)</span></p>
      </Panel>

      <Panel title="The dataset this page is showing" id="dataset">
        {m ? (
          <dl className="facts" data-testid="evidence-manifest">
            <div><dt>dataset_version</dt><dd>{m.dataset_version}</dd></div>
            <div><dt>dataset_hash</dt><dd><code>{m.dataset_hash}</code></dd></div>
            <div><dt>generated_at</dt><dd>{m.generated_at}</dd></div>
            <div><dt>contract_version</dt><dd>{m.contract_version}</dd></div>
            <div><dt>code_sha</dt><dd><V v={m.code_sha ?? null} /></dd></div>
            <div><dt>row counts</dt><dd>{Object.entries(m.row_counts).map(([k, v]) => `${k} ${v}`).join(", ")}</dd></div>
          </dl>
        ) : <p>The snapshot has not loaded.</p>}
      </Panel>
    </article>
  );
}
