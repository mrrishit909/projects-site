import { FreshnessChart } from "../components/freshness-chart";
import { Link } from "../components/link";
import { Fig, Meaning, Panel, Readout, Scroll, ScopeTag, Status, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/analyse";
import { downloadCsv } from "../lib/derive";
import { p6, ratio } from "../domain/num";
import { dayTime, dur, n0 } from "../lib/format";

function Fresh({ ds }: { ds: Dataset }) {
  const rows = ds.freshness;
  const basis = rows[0]?.freshness_basis ?? "computed";
  return (
    <Panel id="freshness" title="Freshness beside ingestion age" scope={basis === "recorded" ? "recorded" : "complete"}>
      <Meaning>
        <strong>Freshness</strong> = as-of minus the newest <em>accepted</em> source event (seconds). <strong>Ingestion age</strong> = as-of minus the last <em>committed</em> batch. They differ: a batch can commit on time and carry nothing new, and every job stays green.
        {basis === "recorded" ? <> Ingestion age is recomputed here from the published checkpoints; the newest accepted event is the generator&apos;s recorded instant for the complete world (the raw rows are a sample), and freshness is the as-of minus it.</> : <> Both are recomputed here from every row of the dataset.</>}
      </Meaning>
      <FreshnessChart rows={rows} />
      <Scroll label="Freshness and ingestion age per source">
        <table className="data" data-testid="fresh-table">
          <caption>Per source, as of {ds.provenance.as_of}. Seconds are whole seconds; the text beside them is the same value in days, hours and minutes.</caption>
          <thead><tr><th scope="col">Source</th><th scope="col">Jobs</th><th scope="col">Ingestion age</th><th scope="col">Freshness</th><th scope="col">Gap</th><th scope="col">Target</th><th scope="col">Cadences</th><th scope="col">State</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.source_id} data-source={r.source_id}>
                <th scope="row"><code>{r.source_id}</code><br /><span className="sub">{r.cadence}</span></th>
                <td data-k="jobs">{r.last_batch ? <Status tone={r.last_batch.status === "committed" ? "ok" : "bad"}>last batch {r.last_batch.status}</Status> : <Status tone="idle">no batch</Status>}<br /><span className="sub">{Object.entries(r.batches_72h).map(([s, n]) => `${n} ${s}`).join(", ") || "none"} in the last 72 h</span></td>
                <td data-k="ingestion-age" data-seconds={r.ingestion_age_seconds ?? ""}><Fig k={`ingestion-age-${r.source_id}`}>{r.ingestion_age_seconds ?? "n/a"}</Fig> s<br /><span className="sub">{dur(r.ingestion_age_seconds)}</span></td>
                <td data-k="freshness" data-seconds={r.freshness_seconds ?? ""}><Fig k={`freshness-${r.source_id}`}>{r.freshness_seconds ?? "n/a"}</Fig> s<br /><span className="sub">{dur(r.freshness_seconds)}</span></td>
                <td data-k="gap">{r.gap_seconds === null ? "n/a" : <><Fig k={`gap-${r.source_id}`}>{r.gap_seconds}</Fig> s<br /><span className="sub">{dur(r.gap_seconds)}</span></>}</td>
                <td data-k="target">{r.target_seconds === null ? "none declared" : <>{r.target_seconds} s<br /><span className="sub">{dur(r.target_seconds)}</span></>}</td>
                <td data-k="cadences">{r.cadences ?? "n/a"}</td>
                <td data-k="state">{r.silent ? <Status tone="warn" k="silent">silent while green</Status> : r.past_target ? <Status tone="bad" k="past-target">past its target</Status> : <Status tone="ok" k="fresh">current</Status>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <Meaning><strong>Gap</strong> = freshness minus ingestion age: how much older the newest event is than the last batch. <strong>Cadences</strong> = freshness divided by the declared cadence. <strong>Silent</strong> (a display rule, not a contract rule) = more than 2 cadences without a new accepted event; the gate only knows each source&apos;s own target, so a source whose target is loose stays allowed while silent.</Meaning>
      <p><button type="button" className="quiet" data-testid="export-fresh" onClick={() => downloadCsv("freshness-per-source.csv", ["source_id", "cadence", "ingestion_age_seconds", "freshness_seconds", "gap_seconds", "target_seconds", "cadences", "silent", "freshness_basis"], rows.map((r) => [r.source_id, r.cadence, r.ingestion_age_seconds, r.freshness_seconds, r.gap_seconds, r.target_seconds, r.cadences, r.silent === null ? null : String(r.silent), r.freshness_basis]))}>Download this table (CSV, all {rows.length} rows)</button></p>
    </Panel>
  );
}
function RunsPanel({ ds }: { ds: Dataset }) {
  const M = ds.g.metrics;
  const R = M.runs;
  const gates = Object.values<{ decision: string }>(M.quality_gate);
  const allowed = gates.filter((g) => g.decision === "allowed").length;
  const total = Object.keys(R.runs).length;
  return (
    <Panel id="runs-panel" title="Runs, tasks and the gate" scope="complete">
      <dl className="readouts">
        <Readout k="runs-total" label="Runs" value={n0(total)} note={`${n0(R.durations.successful.count)} succeeded, ${n0(R.durations.failed.count)} failed`} />
        <Readout k="gate-allowed" label="Gate allowed" value={n0(allowed)} unit={`of ${n0(gates.length)}`} note={`${n0(gates.length - allowed)} blocked`} />
        <Readout k="task-success-rate" label="Task success rate" value={R.overall.task_success_rate ?? "n/a"} note={`${n0(R.overall.tasks_successful)} successful of ${n0(R.overall.tasks_terminal)} terminal tasks (attempts are not tasks)`} />
        <Readout k="attempt-success-rate" label="Attempt success rate" value={R.overall.attempt_success_rate ?? "n/a"} note={`${n0(R.overall.attempts_successful)} of ${n0(R.overall.attempts)} attempts; a retry that succeeds still counts a failed attempt`} />
        <Readout k="duration-success" label="Mean duration, succeeded" value={R.durations.successful.mean_minutes ?? "n/a"} unit="min" note="finished_at minus started_at; failed runs are a separate distribution" />
        <Readout k="duration-failed" label="Mean duration, failed" value={R.durations.failed.mean_minutes ?? "n/a"} unit="min" note={`${n0(R.durations.failed.count)} failed runs`} />
        <Readout k="pointer" label="Publication pointer" value={M.publications.current_publication_id ?? "none"} note="moves only to a run that succeeded, passed its gate and published" />
      </dl>
      <p><Link to="gate">Open the quality gate</Link> · <Link to="runs">Open a run</Link></p>
    </Panel>
  );
}
function Ingestion({ ds }: { ds: Dataset }) {
  const I = ds.ingestion, S = ds.g.metrics.ingestion;
  const snapshot = ds.id === "snapshot";
  const O = I.overall;
  const sourceIds = Object.keys(I.sources);
  return (
    <Panel id="ingestion" title="Ingestion: received, accepted, duplicate, quarantined" scope={snapshot ? "complete" : "complete"}>
      <Meaning>Counts are rows of committed batches. <strong>Duplicate</strong> = the source_key was already accepted (counted apart, never quarantined, never accepted twice). <strong>Quarantined</strong> = failed the contract, kept with a reason code. Rejection rate = quarantined ÷ received; duplicate rate = duplicates ÷ received (6 places). {snapshot ? "These totals come from batch_summaries, which the generator computed over all raw rows." : "The golden fixture holds every row."}</Meaning>
      <dl className="readouts">
        <Readout k="received" label="Received" value={n0(O.received)} />
        <Readout k="accepted" label="Accepted unique" value={n0(O.accepted_unique)} />
        <Readout k="duplicate" label="Duplicate" value={n0(O.duplicate)} />
        <Readout k="quarantined" label="Quarantined" value={n0(O.quarantined)} note={O.deleted ? `plus ${n0(O.deleted)} delete events (propagated, counted apart)` : undefined} />
        <Readout k="rejection-rate" label="Rejection rate" value={O.rejection_rate ?? "n/a"} />
        <Readout k="duplicate-rate" label="Duplicate rate" value={O.duplicate_rate ?? "n/a"} />
      </dl>
      <Scroll label="Ingestion per source">
        <table className="data" data-testid="ingestion-table">
          <caption>Committed batches per source{snapshot ? ", complete world (batch_summaries) beside the 2,000-row sample" : ""}.</caption>
          <thead><tr><th scope="col">Source</th><th scope="col">Received</th><th scope="col">Accepted</th><th scope="col">Duplicate</th><th scope="col">Quarantined</th>{snapshot && <th scope="col">Sample: received / accepted / duplicate / quarantined</th>}</tr></thead>
          <tbody>
            {sourceIds.map((sid) => {
              const s = I.sources[sid]!, m = S.sources[sid];
              return (
                <tr key={sid} data-source={sid}>
                  <th scope="row"><code>{sid}</code></th>
                  <td data-k="received">{n0(s.received)}</td><td data-k="accepted">{n0(s.accepted_unique)}</td><td data-k="duplicate">{n0(s.duplicate)}</td><td data-k="quarantined">{n0(s.quarantined)}</td>
                  {snapshot && <td data-k="sample">{m ? `${n0(m.received)} / ${n0(m.accepted_unique)} / ${n0(m.duplicate)} / ${n0(m.quarantined)}` : "n/a"}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </Scroll>
      {snapshot && <p className="meaning" data-testid="sample-note"><ScopeTag basis="sample" /> Over the 2,000 published rows ({n0(I.sampled_batches)} whole batches) the same classification gives {n0(S.overall.received)} received, {n0(S.overall.accepted_unique)} accepted, {n0(S.overall.duplicate)} duplicate, {n0(S.overall.quarantined)} quarantined. They differ from the complete world because a key accepted in an unsampled earlier batch is invisible to the sample, so a later repeat of it counts as accepted there.</p>}
    </Panel>
  );
}
function Completeness({ ds }: { ds: Dataset }) {
  const M = ds.g.metrics;
  const rec = (ds.manifest?.stats?.["completeness_by_source"] ?? null) as Record<string, { accepted_records: number; expected_records: number; value: string; partitions: number }> | null;
  const sample = M.completeness as Record<string, Record<string, { expected_records: number; accepted_records: number; value: string | null }>>;
  const sources = Object.keys(ds.ingestion.sources);
  const sum = (sid: string): { e: number; a: number; days: number } => Object.values(sample[sid] ?? {}).reduce((t, v) => ({ e: t.e + v.expected_records, a: t.a + v.accepted_records, days: t.days + 1 }), { e: 0, a: 0, days: 0 });
  return (
    <Panel id="completeness" title="Completeness against the declared expectation" scope={rec ? "recorded" : "complete"}>
      <Meaning>Completeness = accepted unique records of a partition ÷ the records the synthetic source declared for it (not capped; null when nothing was expected). A partition is a UTC date of the event timestamp.</Meaning>
      <Scroll label="Completeness per source">
        <table className="data" data-testid="completeness-table">
          <caption>Over all partitions of each source.{rec ? " The recorded column is the generator's figure for the complete world; the sample column is recomputed here over the 2,000 published rows." : ""}</caption>
          <thead><tr><th scope="col">Source</th><th scope="col">Partitions</th><th scope="col">Expected</th><th scope="col">Accepted</th>{rec && <th scope="col">Recorded value</th>}<th scope="col">{rec ? "Sample value" : "Value"}</th></tr></thead>
          <tbody>
            {sources.map((sid) => {
              const t = sum(sid), r = rec?.[sid];
              const v = p6(ratio(t.a, t.e));
              return (
                <tr key={sid} data-source={sid}>
                  <th scope="row"><code>{sid}</code></th>
                  <td>{r ? r.partitions : t.days}</td><td data-k="expected">{n0(r ? r.expected_records : t.e)}</td><td data-k="accepted">{n0(r ? r.accepted_records : t.a)}</td>
                  {rec && <td data-k="recorded-value">{r?.value ?? "n/a"}</td>}
                  <td data-k="value">{ds.id === "golden" ? (Object.values(sample[sid] ?? {})[0]?.value ?? "n/a") : (v ?? "n/a")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Scroll>
      {ds.id === "snapshot" && <Meaning>The sample column is the accepted ÷ expected of the sampled rows only, so it is small by construction; read it as a reconciliation of the sample, not as the pipeline&apos;s completeness. src-refunds is the exception worth reading: its last three partitions are 0.000000 in the sample too, because it stopped delivering new events.</Meaning>}
    </Panel>
  );
}
function Scope({ ds }: { ds: Dataset }) {
  return (
    <Panel id="window" title="Window, version and navigation">
      <dl className="facts">
        <div><dt>Time window</dt><dd data-testid="window">{ds.manifest?.window_start ? `${ds.manifest.window_start} to ${ds.manifest.window_end}` : `as of ${ds.provenance.as_of}`}</dd></div>
        <div><dt>As-of and cutoff</dt><dd>{ds.g.as_of} (cutoff {ds.g.cutoff}); facts after the cutoff are not known</dd></div>
        <div><dt>Data version</dt><dd>{ds.provenance.dataset_version}</dd></div>
        <div><dt>Filters</dt><dd>none on this screen; every row of the snapshot is in every figure</dd></div>
      </dl>
      <p><Link to="evidence">Evidence and hash checks</Link> · <Link to="gate">Definitions of the gate</Link> · <Link to="case-study">Case study</Link> · <Link to="dag">Dependency graph</Link>. First seen {dayTime(ds.provenance.as_of)}.</p>
      <p className="meaning">Share of the pipeline&apos;s runs that were green over the whole window: {p6(ratio(ds.g.metrics.runs.durations.successful.count, Object.keys(ds.g.metrics.runs.runs).length))} (a proportion of runs by job colour, not a freshness measure).</p>
    </Panel>
  );
}
export function OverviewView() {
  return (
    <WithData>
      {(ds) => (
        <>
          <ViewHead mark="02 · entry screen" title="Platform overview">
            <p className="lede">A green job says the code ran. It does not say the data is current. Each source below shows how old its newest accepted event is, beside how long ago its last batch committed.</p>
          </ViewHead>
          <Fresh ds={ds} />
          <RunsPanel ds={ds} />
          <Ingestion ds={ds} />
          <Completeness ds={ds} />
          <Scope ds={ds} />
        </>
      )}
    </WithData>
  );
}
