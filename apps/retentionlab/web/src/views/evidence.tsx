import { Link } from "../components/link";
import { Chip, Fig, Related, Scroll, ScopeStrip, TableFold, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/models";
import { designedClaims, injectionChecks, leafDiff, replayRefusals } from "../lib/claims";
import { n0 } from "../lib/format";

export function EvidenceView() {
  return <WithData>{(ds) => <Evidence ds={ds} />}</WithData>;
}

const FILES = ["manifest", "accounts", "subscription_events", "billing_events", "usage_events", "support_events", "prediction_cutoffs", "feature_rows", "labels", "training_runs", "predictions", "intervention_scenarios",
  "outreach_events", "feature_registry", "split_assignments", "scoring_publications", "test_cohort", "cutoff_aggregates", "calibration", "split_summary", "injection-manifest", "injection-events"];

function Evidence({ ds }: { ds: Dataset }) {
  const m = ds.manifest;
  const dr = designedClaims(ds), inj = injectionChecks(ds), rp = replayRefusals(ds);
  const diff = ds.expected ? leafDiff(ds.primary.result, ds.expected) : null;
  const disclosures = (m?.["disclosures"] as Row[] | undefined) ?? [];
  const drs = (m?.["designed_relationships"] as Row[] | undefined) ?? [];
  const injections = (ds.injections?.["injections"] as Row[] | undefined) ?? [];
  const ceiling = ds.disclosure?.["latent_reference_test"] as Row | undefined;
  const rowCounts = (m?.["row_counts"] as Record<string, number> | undefined) ?? {};
  const base = import.meta.env.BASE_URL;
  return (
    <>
      <ViewHead mark="11 · Evidence" title="Evidence" contracts="P10-TEST-01..12 (detect and recover), P10-MET-*, D-05, D-07, D-G01..D-G09">
        <p className="lede">What was checked, by what, and what it cannot show. The checks on this page run in your browser against the published files; the backend, the golden fixture and the end-to-end evidence are separate layers and are named as such.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["dataset", ds.strip.dataset_version], ["hash", ds.strip.dataset_hash.slice(0, 16)], ["as of", ds.strip.as_of]]} />
      {diff && (
        <section className="paper" data-testid="evidence-golden" aria-labelledby="eg-h">
          <h2 id="eg-h">The golden fixture against its oracle</h2>
          <p>The fixture's inputs were evaluated in this browser and compared leaf by leaf with <code>expected.json</code>: <Fig k="leaves">{n0(diff.total)}</Fig> leaves, <Fig k="leaves-bad">{n0(diff.bad.length)}</Fig> differ. {diff.bad.length === 0 ? <Chip kind="ok">every leaf equal</Chip> : <Chip kind="risk">{diff.bad.slice(0, 5).join(", ")}</Chip>}</p>
        </section>
      )}
      {m && (
        <section aria-labelledby="prov-h">
          <h2 id="prov-h">Provenance</h2>
          <dl className="kv" data-testid="provenance">
            <dt>dataset_version</dt><dd>{m["dataset_version"]}</dd><dt>dataset_hash</dt><dd>{m["dataset_hash"]}</dd><dt>generated_at</dt><dd>{m["generated_at"]}</dd><dt>as_of</dt><dd>{m["as_of"]}</dd>
            <dt>generator</dt><dd>{m["generator"]["name"]}, seed {m["generator"]["seed"]}</dd><dt>published cohort</dt><dd>{m["published_cohort"]["accounts"]} of {n0(m["population"]["accounts"])} accounts, uniform sample: {m["published_cohort"]["sampling"]}</dd>
            <dt>rows published</dt><dd>{Object.entries(rowCounts).map(([k, v]) => `${k} ${n0(v)}`).join("; ")}</dd>
          </dl>
          <p className="note"><strong>The published rows are not the population.</strong> The cohort's event files are complete for its accounts only; the 1,513-row test table, the per-cutoff aggregates, the calibration and split summaries come from the whole 2,400-account world, which the domain evaluated in memory. Everything on this site that uses the cohort says so.</p>
        </section>
      )}
      {disclosures.length > 0 && (
        <section aria-labelledby="disc-h">
          <h2 id="disc-h">Disclosures from the generator</h2>
          <p>Stated in the manifest, in order. D-G02 is the one that matters most: the world was tuned after looking at outcomes.</p>
          <ol className="steps" data-testid="disclosures">{disclosures.map((d) => <li key={d["id"]} id={String(d["id"])} data-disclosure={d["id"]}><strong>{d["id"]}.</strong> {d["text"]}</li>)}</ol>
        </section>
      )}
      {drs.length > 0 && (
        <section aria-labelledby="dr-h">
          <h2 id="dr-h">Designed relationships: the manifest against this browser</h2>
          <p>The generator was built to show five things. Each is a statement with figures; this page recomputes the figures it can from the published files and sets them against the manifest. <Fig k="dr-ok">{dr.filter((c) => c.ok).length}</Fig> of <Fig k="dr-total">{dr.length}</Fig> are equal; <Fig k="dr-recomputed">{dr.filter((c) => c.recomputed).length}</Fig> were recomputed here and <Fig k="dr-published">{dr.filter((c) => !c.recomputed).length}</Fig> are the manifest's own figures from the full world, shown as published.</p>
          <div data-testid="designed">
            {drs.map((d) => { const cs = dr.filter((c) => c.id === d["id"]); return (
              <details key={d["id"]} className="fold" data-dr={d["id"]}>
                <summary><strong>{d["id"]}</strong> {d["name"]} {d["met"] ? <Chip kind="ok">met</Chip> : <Chip kind="risk">not met</Chip>} <span className="mono">{cs.filter((c) => c.ok).length}/{cs.length} equal</span></summary>
                <p>{d["statement"]}</p>
                <Scroll label={`${d["id"]} figures`}>
                  <table><caption>Figures of {d["id"]}.</caption><thead><tr><th scope="col">Figure</th><th scope="col">Manifest</th><th scope="col">This browser</th><th scope="col">Basis</th></tr></thead>
                    <tbody>{cs.map((c) => <tr key={c.label} data-ok={c.ok}><td className="l">{c.label}</td><td>{String(c.want)}</td><td>{c.recomputed ? String(c.got) : "—"}</td><td className="t">{c.recomputed ? (c.ok ? <Chip kind="ok">recomputed, equal</Chip> : <Chip kind="risk">differs</Chip>) : <Chip kind="hatch">published, full world</Chip>}</td></tr>)}</tbody></table>
                </Scroll>
              </details>); })}
          </div>
          <p className="note"><strong>The margin was reached by construction.</strong> DR-01 holds because the engagement signal was strengthened until it did (D-G02 item 2). Read it as "the pipeline detects and reports a model that beats the baselines", not as "such a model beats a rule on real accounts".</p>
        </section>
      )}
      {injections.length > 0 && (
        <section aria-labelledby="inj-h">
          <h2 id="inj-h">Twelve injected defects</h2>
          <p>Each defect is planted in the data or in a request, and the product must detect it and recover. <Fig k="inj-ok">{inj.filter((c) => c.ok).length}</Fig> of <Fig k="inj-total">{inj.length}</Fig> declared checks equal the facts the manifest recorded; <Fig k="replay-ok">{rp.filter((r) => r.ok).length}</Fig> of <Fig k="replay-total">{rp.length}</Fig> recorded replay requests were re-run <em>in this browser</em> through the domain's refusal rules and returned the code the API returned.</p>
          <div data-testid="injections">{injections.map((x) => { const cs = inj.filter((c) => c.inj === x["id"]); const rs = rp.filter((r) => r.injection === x["id"]); return (
            <details key={x["id"]} className="fold" data-inj={x["id"]}>
              <summary><strong>{x["id"]}</strong> {x["name"]} <span className="mono">{x["test"]}</span> {cs.every((c) => c.ok) ? <Chip kind="ok">facts equal</Chip> : <Chip kind="risk">differs</Chip>}</summary>
              <p><strong>Defect.</strong> {x["defect"]}</p><p><strong>Expected handling.</strong> {x["expected_handling"]}</p>
              <Scroll label={`${x["id"]} checks`}><table><caption>Declared checks and the re-run refusals.</caption><thead><tr><th scope="col">Check</th><th scope="col">Expected</th><th scope="col">Recorded</th><th scope="col">Result</th></tr></thead>
                <tbody>{cs.map((c, i) => <tr key={i}><td className="l">{c.path} ({c.scope})</td><td>{JSON.stringify(c.want)}</td><td>{JSON.stringify(c.got)}</td><td className="t">{c.ok ? <Chip kind="ok">equal</Chip> : <Chip kind="risk">differs</Chip>}</td></tr>)}
                  {rs.map((r, i) => <tr key={`r${i}`}><td className="l">replay {r.event}: {r.command} {r.input.slice(0, 60)}</td><td>{r.expected ?? "accepted"}</td><td>{r.got ?? "accepted"}</td><td className="t">{r.ok ? <Chip kind="ok">re-run here, equal</Chip> : <Chip kind="risk">differs</Chip>}</td></tr>)}</tbody></table></Scroll>
            </details>); })}</div>
        </section>
      )}
      {ceiling && (
        <section className="paper" data-testid="latent-ceiling" aria-labelledby="ceil-h">
          <h2 id="ceil-h">A disclosure, not an input: the latent ceiling</h2>
          <p>The generator keeps, for verification only, the true 90-day churn propensity of every account. Ranked by that hidden propensity, the test rows would score an average precision of <Fig k="ceiling-ap">{ceiling["average_precision"]}</Fig> (Brier <Fig k="ceiling-brier">{ceiling["brier_score"]}</Fig>) against the model's visible-feature result. It is an approximate ceiling for what the four features could ever see, not a bound, and <strong>no feature, prediction, chart or figure on this site reads it</strong>; a request that names a latent field is refused LATENT_TRUTH.</p>
        </section>
      )}
      <section aria-labelledby="layers-h">
        <h2 id="layers-h">The layers of checking, and what each cannot show</h2>
        <ol className="steps">
          <li><strong>The Python domain and backend</strong> (Mode A): a stdlib reference recomputes the golden fixture; the API, the PostgreSQL schema and its triggers are tested on hosted runners. Not executable from this site.</li>
          <li><strong>The TypeScript mirror</strong> (Mode B, this site): <code>scripts/golden-check.ts</code> compares every leaf of the golden fixture and both variants, then the published cohort and test table with digests of what the Python domain computes over the same files (<code>scripts/make-snapshot-reference.py</code>). <code>scripts/review-check.ts</code> works adversarial worlds by hand. They test the mirror, not the model.</li>
          <li><strong>This page</strong>: the manifest's claims set against this browser's figures, and the recorded requests re-run through the refusal rules. It cannot recompute figures that need events of accounts that are not published.</li>
          <li><strong>The end-to-end suite</strong>: Playwright drives the built site on the nested base path and records screenshots at four widths and 200 % zoom.</li>
        </ol>
        <p>What none of it shows: that any retention action works. The economics are hypothetical, the world is synthetic and the margin over the baselines was built in. <Link to="case-study">The case study</Link> says so at length.</p>
      </section>
      <TableFold summary="The published files" open={false}>
        <ul className="plain tight" data-testid="files">{FILES.map((f) => <li key={f}><a href={`${base}data/${f}.json`}>data/{f}.json</a></li>)}<li><a href={`${base}golden/inputs.json`}>golden/inputs.json</a></li><li><a href={`${base}golden/expected.json`}>golden/expected.json</a></li></ul>
      </TableFold>
      <Related also={["models", "monitoring"]} />
    </>
  );
}
