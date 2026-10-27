import { Link } from "../components/link";
import { Chip, Def, Scroll, ViewHead, WithData, WithDataset } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { ENTITIES } from "../domain/contract";
import { compareLeaves } from "../lib/compare";
import { designedClaims, injectionChecks } from "../lib/claims";
import { n0, short } from "../lib/format";
import { ROUTES } from "../routes";

function GoldenSelfCheck({ ds }: { ds: Dataset }) {
  const check = compareLeaves(ds.goldenShape(), ds.expected);
  const ok = check.mismatches.length === 0;
  const m = ds.now.metrics;
  const w = m["weighted_score"]["datasets"]["ds-customers"];
  return (
    <section className="block" data-testid="evidence-golden" aria-labelledby="g">
      <h2 id="g">1. The golden case, checked live in this browser</h2>
      <p>The fixture’s raw rows were ingested and every metric computed by the TypeScript mirror when this page loaded, then compared leaf by leaf with the fixture’s <span className="mono">expected.json</span>, which was worked out by hand and by an independent reference script before any application code existed.</p>
      <p className="callout" data-ok={ok ? "true" : "false"}><Chip kind={ok ? "ok" : "note"}>{ok ? "all equal" : "differs"}</Chip> <strong data-k="leaves">{check.leaves - check.mismatches.length} of {check.leaves}</strong> values equal{ok ? "" : `; differing: ${check.mismatches.slice(0, 5).join(", ")}`}.</p>
      <ul>
        <li>Completeness <span className="mono">{m["completeness"]["r-cust-complete-email"].value}</span>; validity populated-only <span className="mono">{m["validity"]["r-cust-valid-email"].populated_only.value}</span> beside all-eligible <span className="mono">{m["validity"]["r-cust-valid-email"].all_eligible.value}</span>.</li>
        <li>Weighted score <span className="mono">{w.value}</span> ({ds.now.weight_version}) and <span className="mono">{m["weighted_score"].by_weight_version.w1["ds-customers"]}</span> (w1), with the critical override <span className="mono">{String(w.critical_override)}</span> beside both.</li>
      </ul>
      <p><Link to="scorecard?dataset=golden">Open the golden scorecard</Link></p>
    </section>
  );
}

function Provenance({ ds }: { ds: Dataset }) {
  const m = ds.manifest;
  const counts = ds.result.ingest.counts;
  return (
    <section className="block" data-testid="provenance" aria-labelledby="p">
      <h2 id="p">2. Provenance of the loaded data ({ds.id})</h2>
      <dl className="facts">
        <div><dt>dataset_version</dt><dd className="mono">{m.dataset_version}</dd></div>
        <div><dt>dataset_hash</dt><dd className="mono" title={m.dataset_hash}>{short(m.dataset_hash, 32)}</dd></div>
        <div><dt>generated_at</dt><dd className="mono">{m.generated_at}</dd></div>
        <div><dt>as-of</dt><dd className="mono">{m.as_of}</dd></div>
        <div><dt>seed</dt><dd className="mono">{m.generator?.seed ?? m.seed ?? "none (hand-derived)"}</dd></div>
        <div><dt>generator</dt><dd>{m.generator?.name ?? "n/a"}</dd></div>
        <div><dt>code_sha</dt><dd className="mono">{m.code_sha ?? "not recorded in the manifest"}</dd></div>
      </dl>
      <Scroll label="Rows per entity">
        <table data-testid="row-counts">
          <thead><tr><th scope="col">Entity</th><th scope="col" className="num">Rows in the file</th><th scope="col" className="num">Accepted</th><th scope="col" className="num">Rejected</th></tr></thead>
          <tbody>{[...ENTITIES, "dataset_rows" as const].map((e) => <tr key={e} data-entity={e}><th scope="row" className="mono">{e}</th><td className="num mono">{n0(m.row_counts[e] ?? 0)}</td><td className="num mono">{n0(counts[e]!.accepted)}</td><td className="num mono">{n0(counts[e]!.rejected)}</td></tr>)}</tbody>
        </table>
      </Scroll>
      <p className="muted">The data hash is verified in CI (<span className="mono">npm run check</span> recomputes it from the entity files), not in the browser.</p>
    </section>
  );
}

function Claims({ ds }: { ds: Dataset }) {
  const inj = injectionChecks(ds), dr = designedClaims(ds);
  const ids = [...new Set(inj.map((c) => c.inj))];
  if (ids.length === 0 && dr.length === 0) return <section className="block" data-testid="claims" aria-labelledby="c"><h2 id="c">3. The generator’s defect checks and designed relationships</h2><p>The golden fixture is hand-derived and has no generator claims. Switch to the snapshot to see them.</p></section>;
  return (
    <section className="block" data-testid="claims" aria-labelledby="c">
      <h2 id="c">3. The generator’s defect checks and designed relationships, re-derived here</h2>
      <p>The snapshot was generated with twelve injected defects (one per test requirement P07-TEST-01..12) and six designed relationships. Each carries machine-checkable expectations; the browser evaluates them against the figures it computed from the rows. <Def term="what this does and does not show">It shows the figures the pages print are the ones the generator’s own checks expect. It does not show the generator is right about the world: it is synthetic, and the designed relationships were built into it on purpose.</Def></p>
      <Scroll label="Defect checks"><table data-testid="injections">
        <thead><tr><th scope="col">Defect</th><th scope="col">Test</th><th scope="col">What was injected</th><th scope="col" className="num">Checks that hold</th></tr></thead>
        <tbody>{ids.map((id) => { const cs = inj.filter((c) => c.inj === id); const okN = cs.filter((c) => c.ok).length; return (
          <tr key={id} data-inj={id}><th scope="row" className="mono">{id}</th><td className="mono">{cs[0]!.test}</td><td>{cs[0]!.name}</td><td className="num mono" data-k="holds">{okN} of {cs.length} {okN === cs.length ? <Chip kind="ok">hold</Chip> : <Chip kind="note">fail</Chip>}</td></tr>); })}</tbody>
      </table></Scroll>
      <Scroll label="Designed relationships"><table data-testid="designed">
        <thead><tr><th scope="col">Relationship</th><th scope="col">Figure</th><th scope="col">Manifest says</th><th scope="col">Computed here</th><th scope="col">Equal</th></tr></thead>
        <tbody>{dr.map((c, i) => <tr key={`${c.id}${i}`} data-dr={c.id}><th scope="row" className="mono">{c.id}</th><td>{c.label}</td><td className="mono">{c.want}</td><td className="mono">{c.got}</td><td>{c.ok ? <Chip kind="ok">equal</Chip> : <Chip kind="note">differs</Chip>}</td></tr>)}</tbody>
      </table></Scroll>
    </section>
  );
}

function Disclosures({ ds }: { ds: Dataset }) {
  const p = ds.manifest.generator?.parameters ?? {};
  const parts = (p["disclosures"] ?? "").split(" | ").filter(Boolean);
  return (
    <section className="block" data-testid="disclosures" aria-labelledby="dc">
      <h2 id="dc">4. Disclosures in the manifest</h2>
      {parts.length === 0 ? <p>The golden fixture is hand-derived: no generator, no draws, no outcome-informed choices.</p> : <ul className="disclosure">{parts.map((t, i) => <li key={i}>{t}</li>)}</ul>}
      <p className="muted">Synthetic match truth lives only in the manifest’s verification block. The matcher, the candidates, the duplicate review and the merge history never read it; only the match-precision figure does, and it is labelled as coming from there.</p>
    </section>
  );
}

function Evidence() {
  return (
    <>
      <ViewHead mark="Shelfmark 10 · evidence" title="What was checked, and where">
        <p className="lede">Claims on this site are backed by four things: a live check in your browser, the generator’s own defect checks, a test suite run in CI, and the Python domain, which the TypeScript mirror is compared against. Each is described with what it cannot show.</p>
      </ViewHead>
      <WithDataset id="golden">{(g) => <GoldenSelfCheck ds={g} />}</WithDataset>
      <WithData>{(ds) => <><Provenance ds={ds} /><Claims ds={ds} /><Disclosures ds={ds} /></>}</WithData>
      <section className="block" data-testid="ci-checks" aria-labelledby="ci">
        <h2 id="ci">5. What CI runs (not run by this page)</h2>
        <ul>
          <li><strong className="mono">npm run check</strong>: type-check; <span className="mono">scripts/golden-check.ts</span> (the TypeScript domain against the golden fixture and its two variants leaf by leaf, against the per-entity golden copy this site serves, against the generator’s twelve defect checks and six designed relationships, and against digests of the Python domain’s results over this snapshot at three as-of instants under the version in force, w1 and w2, a half-open window, every issue’s class, the identity map, and every local time of 2026 in seven time zones across both DST transitions); and <span className="mono">scripts/review-check.ts</span> (adversarial cases).</li>
          <li><strong className="mono">npm run build:pages</strong>: the production build under this site’s base path, with one entry page per route so a direct visit or reload works.</li>
          <li><strong className="mono">npm run e2e</strong>: Playwright on that build: every route at 360, 768, 1280 and 1920 px and at 200 % zoom with no horizontal overflow, the honesty labels, the golden and snapshot figures, the simulations, and a screenshot index.</li>
          <li><strong>Mode A</strong>: the Python domain, the PostgreSQL schema, the SQL reference and the API, tested on hosted runners; the TypeScript here is a mirror, not a replacement.</li>
        </ul>
        <p className="muted">The screenshots and <span className="mono">evidence/index.json</span> are uploaded by CI as a build artifact; they are not hosted on this site, so this page links to no image.</p>
      </section>
      <section className="block" data-testid="routes" aria-labelledby="rt">
        <h2 id="rt">6. Routes</h2>
        <ul className="routes">{ROUTES.map((r) => <li key={r.path || "home"}><Link to={r.path}>{r.path === "" ? "/" : `/${r.path}/`}</Link><span>{r.entry ? <Chip kind="ok">entry route</Chip> : <span className="muted">supporting view</span>} <span className="muted">{r.title}</span></span></li>)}</ul>
      </section>
      <section className="block" aria-labelledby="lim" data-testid="limits">
        <h2 id="lim">7. Limits</h2>
        <ul>
          <li>The data is synthetic and generated by a script; its relationships are designed, and the generator’s disclosures (section 4) list the choices made after looking at earlier drafts.</li>
          <li>Validity patterns are JavaScript regular expressions here, Python’s <span className="mono">re</span> in the reference and PostgreSQL regular expressions in the SQL. The three engines read <span className="mono">\s</span>, <span className="mono">\d</span>, <span className="mono">\w</span> and <span className="mono">\b</span> differently (which characters count, a boundary or a backspace), so a rule that uses one is refused at ingest (<span className="mono">PATTERN_NOT_PORTABLE</span>) and the patterns here use explicit classes. Beyond that, no assurance is given that every pattern means the same in the three engines: only the patterns in this data are checked, and they agree. Local schedules use the browser’s time-zone database; the checks compare it with Python’s <span className="mono">zoneinfo</span> for 2026 in seven zones. Four of those zones have daylight-saving time (America/New_York, America/Chicago, Europe/London, Europe/Berlin) and three do not (UTC, Asia/Kolkata, Asia/Singapore). A browser with an older database could differ.</li>
          <li>Floating-point numbers never enter a published figure: every ratio is an exact fraction rounded half up once. JSON cannot tell <span className="mono">1.0</span> from <span className="mono">1</span>, so a float written that way in a dataset row would be accepted here and rejected by the Python domain; the published rows hold none.</li>
          <li>Nothing here is live: no dataset is registered, no issue is closed, no pair is merged and no rule is disabled from the site, and every action is a simulation in browser memory.</li>
        </ul>
      </section>
    </>
  );
}
export function EvidenceView() { return <Evidence />; }
