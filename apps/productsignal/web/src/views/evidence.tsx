import { Link } from "../components/link";
import { Chip, Def, Scroll, ViewHead, WithData, WithDataset } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { goldenShape } from "../data/dataset";
import { ENTITIES } from "../domain/contract";
import { compareLeaves } from "../lib/compare";
import { n0, short } from "../lib/format";
import { ROUTES } from "../routes";

function GoldenSelfCheck({ ds }: { ds: Dataset }) {
  const check = compareLeaves(goldenShape(ds), ds.expected);
  const ok = check.mismatches.length === 0;
  const ex = ds.at(ds.cutoff).metrics.experiment!;
  return (
    <section className="block" data-testid="evidence-golden" aria-labelledby="g">
      <h2 id="g">1. The golden case, checked live in this browser</h2>
      <p>The fixture's raw rows were ingested and every metric computed by the TypeScript mirror when this page loaded, then compared leaf by leaf with the fixture's <span className="mono">expected.json</span> (worked out by hand and by an independent reference script before the code existed).</p>
      <p className="callout" data-ok={ok ? "true" : "false"}><Chip v={ok ? "OK" : "MISMATCH"}>{ok ? "all equal" : "differs"}</Chip> <strong data-k="leaves">{check.leaves - check.mismatches.length} of {check.leaves}</strong> values equal{ok ? "" : `; differing: ${check.mismatches.slice(0, 5).join(", ")}`}. Headline: control <span className="mono">{ex.primary.variants["control"]!.conversion}</span>, treatment <span className="mono">{ex.primary.variants["treatment"]!.conversion}</span>, Newcombe <span className="mono">[{ex.primary.interval!.low.replace("-", "−")}, {ex.primary.interval!.high}]</span>, SRM {ex.srm.verdict}.</p>
    </section>
  );
}

function Provenance({ ds }: { ds: Dataset }) {
  const m = ds.manifest;
  return (
    <section className="block" data-testid="provenance" aria-labelledby="p">
      <h2 id="p">2. Provenance of the loaded data ({ds.id})</h2>
      <dl className="facts">
        <div><dt>dataset_version</dt><dd className="mono">{m.dataset_version}</dd></div>
        <div><dt>dataset_hash</dt><dd className="mono" title={m.dataset_hash}>{short(m.dataset_hash, 32)}</dd></div>
        <div><dt>generated_at</dt><dd className="mono">{m.generated_at}</dd></div>
        <div><dt>as-of / cutoff</dt><dd className="mono">{m.as_of} / {m.cutoff}</dd></div>
        <div><dt>seed</dt><dd className="mono">{m.generator?.seed ?? m.seed ?? "none (hand-derived)"}</dd></div>
        <div><dt>generator</dt><dd>{m.generator?.name ?? "n/a"}</dd></div>
      </dl>
      <Scroll label="Rows per entity">
        <table data-testid="row-counts">
          <thead><tr><th scope="col">Entity</th><th scope="col" className="num">Rows in the file</th><th scope="col" className="num">Accepted</th><th scope="col" className="num">Rejected</th><th scope="col" className="num">Merged</th></tr></thead>
          <tbody>{ENTITIES.map((e) => <tr key={e} data-entity={e}><th scope="row" className="mono">{e}</th><td className="num mono">{n0(m.row_counts[e] ?? 0)}</td><td className="num mono">{n0(ds.ingest.counts[e].accepted)}</td><td className="num mono">{n0(ds.ingest.counts[e].rejected)}</td><td className="num mono">{n0(ds.ingest.counts[e].merged)}</td></tr>)}</tbody>
        </table>
      </Scroll>
      <p className="muted">Plan hashes recomputed here (sha-256 of the key-sorted compact plan JSON without the hash): {[...ds.plans.values()].map((p) => <span key={p.experiment_version_id} className="mono">{p.experiment_version_id} {p.hash_valid ? "matches" : "DIFFERS"} </span>)}. The data hash is verified in CI, not in the browser.</p>
    </section>
  );
}

function Evidence() {
  return (
    <>
      <ViewHead eyebrow="Evidence" title="What was checked, and where">
        <p className="lede">Claims on this site are backed by three things: a live check in your browser, a test suite run in CI, and the Python domain, which the TypeScript mirror is compared against. Each is described here with what it does not cover.</p>
      </ViewHead>
      <WithDataset id="golden">{(g) => <GoldenSelfCheck ds={g} />}</WithDataset>
      <WithData>{(ds) => <Provenance ds={ds} />}</WithData>
      <section className="block" data-testid="ci-checks" aria-labelledby="ci">
        <h2 id="ci">3. What CI runs (not run by this page)</h2>
        <ul>
          <li><strong className="mono">npm run check</strong>: type-check, then <span className="mono">scripts/golden-check.ts</span>: the TypeScript domain against the golden fixture and its two variants (every value of expected.json), against the per-entity golden copy the site serves, against the arithmetic primitives, and against digests of the Python domain's results over this snapshot (every metric block at the as-of and at each run's cutoff, the five runs' experiment blocks, guardrail reviews and segment analyses, the weekly cohort grid, and the local calendar date of every session).</li>
          <li><strong className="mono">npm run build:pages</strong>: the production build under this site's base path, with one entry page per route so a direct visit or reload works.</li>
          <li><strong className="mono">npm run e2e</strong>: Playwright on that build: every route at 360, 768, 1280 and 1920 px and at 200 % zoom with no horizontal overflow, the honesty labels, the figures against the Python reference, the experiment order (sample ratio before lift), and a screenshot index.</li>
          <li><strong>Mode A</strong>: the Python domain, the PostgreSQL schema, the SQL reference and the API, tested on hosted runners; the TypeScript here is a mirror, not a replacement.</li>
        </ul>
        <p className="muted">The screenshots and <span className="mono">evidence/index.json</span> are uploaded by CI as a build artifact; they are not hosted on this site, so this page links to no image. <Def term="what the live check cannot show">It shows the mirror reproduces the oracle's answers on the golden case; it cannot show the mirror equals the Python domain on other inputs. That comparison is the golden-check's job in CI.</Def></p>
      </section>
      <section className="block" data-testid="routes" aria-labelledby="rt">
        <h2 id="rt">4. Routes</h2>
        <ul className="routes">{ROUTES.map((r) => <li key={r.path || "home"}><Link to={r.path}>{r.path === "" ? "/" : `/${r.path}/`}</Link> {r.entry ? <Chip v="OK">entry route</Chip> : <span className="muted">honest supporting view</span>} <span className="muted">{r.title}</span></li>)}</ul>
      </section>
      <section className="block" aria-labelledby="lim">
        <h2 id="lim">5. Limits</h2>
        <ul>
          <li>The data is synthetic and generated by a script; its effect sizes are designed, and some choices were made after looking at earlier drafts (disclosed on <Link to="result">the result</Link> and <Link to="case-study">the case study</Link>).</li>
          <li>Local calendars use the browser's time-zone database; on this data the three zones keep a fixed offset through the whole window (2026-04-06 to 2026-10-04), and the Python outputs agree for every session and every half hour across both of the year's transitions. Behaviour at a transition is not pinned by the contract.</li>
          <li>Nothing here is live: no event is ingested, no experiment runs, and every action is a simulation in browser memory.</li>
        </ul>
      </section>
    </>
  );
}
export function EvidenceView() { return <Evidence />; }
