import { Link } from "../components/link";
import { Panel, Readout, ScopeTag, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import { funnel, funnelText, verdict } from "../lib/derive";
import { dur, minutes, n0 } from "../lib/format";
import { ROUTES } from "../routes";

function Home({ ds }: { ds: Dataset }) {
  const v = verdict(ds);
  const M = ds.g.metrics;
  const runs = Object.keys(M.runs.runs).length;
  const f = funnel(ds);
  const pubIds = Object.keys(M.publications.publications);
  const cur = M.publications.current_publication_id as string | null;
  const curPub = cur ? M.publications.publications[cur] : null;
  const silent = ds.freshness.filter((f) => f.silent);
  const written = Object.values(ds.ingestion.by_kind).reduce((a, k) => a + k.written_rows, 0);
  const sampledBatches = ds.raw ? ds.raw.batch_summaries.filter((b) => b["sampled"]).length : 0;
  const batchesWithRows = ds.raw ? new Set(ds.raw.raw_records.map((r) => r["batch_id"])).size : 0;
  const snapshot = ds.id === "snapshot";
  return (
    <>
      <ViewHead mark="00 · the observatory" title="Pipeline Observatory">
        <p className="lede" data-testid="decision">Is this dataset safe, complete, and fresh enough to publish?</p>
        <p className="lede lede--sub">A static, synthetic instrument panel for one pipeline: six sources, twelve models, one published dataset. Every figure below is recomputed in your browser from the published files.</p>
      </ViewHead>

      <section className={`verdict verdict--${v.tone}`} data-testid="verdict" aria-labelledby="verdict-h">
        <h2 id="verdict-h" className="verdict__h"><Status tone={v.tone === "ok" ? "ok" : v.tone === "warn" ? "warn" : "bad"}>{v.headline}</Status></h2>
        <ul className="verdict__why">{v.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        <p className="meaning">{v.rule}</p>
        <p><Link to="overview" className="button button--main" data-testid="main-action">See freshness beside ingestion age</Link></p>
      </section>

      <Panel id="readouts" title="The state at the as-of instant">
        <dl className="readouts">
          <Readout k="current-publication" label="Publication pointer" value={cur ?? "none"} note={curPub ? `published ${curPub.published_at}; the pointer moves only to a run that succeeded, passed its gate and published` : "no publication yet"} scope="complete" />
          <Readout k="gate-allowed" label="Gates allowed" value={n0(f.allowed)} unit={`of ${n0(f.reached)} that reached the gate`} note={<span data-testid="run-funnel">{funnelText(f)}. A run blocked at the gate or failed before it publishes nothing and opens an incident.</span>} scope="complete" />
          <Readout k="silent-sources" label="Sources silent while green" value={String(silent.length)} unit={`of ${ds.freshness.length}`} note={silent.length ? `${silent.map((x) => `${x.source_id}: newest accepted event ${dur(x.freshness_seconds)} old (${x.freshness_seconds} s = ${minutes(x.freshness_seconds)} min), last ingestion ${dur(x.ingestion_age_seconds)} ago (${x.ingestion_age_seconds} s = ${minutes(x.ingestion_age_seconds)} min)`).join("; ")}` : "every source produces new events at its declared cadence"} scope={snapshot ? "recorded" : "complete"} />
          <Readout k="incidents" label="Incidents" value={String(ds.incidents.total)} unit={`${ds.incidents.verified} verified`} note={ds.incidents.mean_recovery_minutes ? `mean verified recovery ${ds.incidents.mean_recovery_minutes} min (detection to the recovery publication)` : "no verified recovery yet"} scope="complete" />
        </dl>
      </Panel>

      <Panel id="snapshot-note" title="What is in this snapshot">
        <p data-testid="snapshot-note">
          {snapshot
            ? <>Synthetic data from seeded generator <code>generate.py</code> (seed {String(ds.manifest?.seed ?? ds.manifest?.generator?.["seed"] ?? "n/a")}): {ds.freshness.length} sources, {n0(runs)} hourly runs from {ds.manifest?.window_start?.slice(0, 10)} to {ds.manifest?.window_end?.slice(0, 10)}, {n0(ds.raw!.ingestion_batches.length)} batches, {n0(written)} raw rows written of which <strong>{n0(ds.raw!.raw_records.length)} rows in {n0(sampledBatches)} whole batches, {n0(batchesWithRows)} of which carry rows, are published</strong> (the other {n0(sampledBatches - batchesWithRows)} sampled batches wrote no row). Dataset as of <code>{ds.provenance.as_of}</code>, {n0(pubIds.length)} publications, {n0(ds.raw!.model_definitions.length)} models.</>
            : <>The golden fixture: {ds.freshness.length} sources, {n0(ds.acc["raw_records"]!.length)} raw rows, {runs} runs and {pubIds.length} publications, with every expected result derived by hand. As of <code>{ds.provenance.as_of}</code>.</>}
        </p>
        <p className="meaning">Three kinds of figure appear, always tagged: <ScopeTag basis="complete" /> recomputed from files published in full; <ScopeTag basis="sample" /> recomputed over the sample; <ScopeTag basis="recorded" /> a statement in the manifest. Mode B: this is a TypeScript mirror of the Python domain; the transactional backend (PostgreSQL, FastAPI) is verified separately by CI.</p>
      </Panel>

      <Panel id="routes" title="Where to look">
        <ol className="route-list">
          {ROUTES.filter((r) => r.path !== "").map((r, i) => (
            <li key={r.path}><Link to={r.path}><span className="route-list__n">{String(i + 1).padStart(2, "0")}</span><span className="route-list__t">{r.title}{r.entry ? <em> · entry screen</em> : null}</span></Link><span className="route-list__b">{r.blurb}</span></li>
          ))}
        </ol>
      </Panel>
    </>
  );
}
export function Landing() { return <WithData>{(ds) => <Home ds={ds} />}</WithData>; }
