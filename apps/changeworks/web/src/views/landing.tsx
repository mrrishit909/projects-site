import { Link } from "../components/link";
import { PlateHead, WithData, Chip } from "../components/ui";
import { PORTFOLIO } from "../components/layout";
import { maturedCount, parseTs } from "../domain/time";
import { ROUTES } from "../routes";
import { defaultScenario, scenarioTotals } from "../lib/derive";
import { group, n0 } from "../lib/format";

export function Landing() {
  return (
    <WithData>{(ds) => {
      const cfg = ds.result.population.config;
      const sid = defaultScenario(ds);
      const sc = scenarioTotals(ds).find((s) => s.id === sid);
      const matured = maturedCount(cfg, parseTs(ds.manifest.as_of), Number(ds.manifest.config["periods"] ?? 0) || 36);
      const programmes = ds.manifest.programmes?.length ?? null;
      const sum = ds.metrics["summary"];
      const golden = ds.id === "golden";
      return (
        <>
          <PlateHead mark="Frontispiece" title="ChangeWorks">
            <p className="lede" data-testid="decision">The decision this atelier supports: <strong>which transformation initiative should be funded, and how will success be established?</strong> Every figure below is recomputed in your browser from a published synthetic snapshot, with exact arithmetic and no floating point.</p>
          </PlateHead>
          <p className="notice" data-testid="snapshot-note">
            {golden
              ? <>The golden fixture: {ds.metrics["summary"]["initiatives"]} initiatives, {ds.metrics["summary"]["scenarios"]} scenario, {String(cfg["period_basis"])} periods from {String(cfg["period_start"])}, as of {ds.manifest.as_of}. Hand-derived expected results sit beside it on the Evidence plate.</>
              : <>The snapshot: {n0(ds.metrics["summary"]["initiatives"])} initiatives{programmes ? ` in ${programmes} programmes` : ""}, {n0(ds.metrics["summary"]["scenarios"])} draft scenarios, {String(ds.manifest.config["periods"])} {String(cfg["period_basis"])} periods from {String(cfg["period_start"]).slice(0, 7)}, as of {ds.manifest.as_of} ({matured} matured periods). Dataset {ds.manifest.dataset_version}.</>}
          </p>
          {sc && (
            <section aria-labelledby="h-now">
              <h2 id="h-now">The portfolio now, scenario {sc.id}</h2>
              <p className="muted small">Estimates for a {sc.horizon}-period horizon at {sc.rateBasis} declared rate {sc.declared}; within a twelve-period benefit window, not a forecast of what will be funded.</p>
              <div className="cards">
                <div className="card" data-testid="card-npv"><h3>Net present value, attributable</h3><span className="big" data-figure="npv-total">{group(sc.npv)}</span><p>USD over {sc.initiatives} initiatives with shared claims counted once; an estimate. Beside it: the plain sum {group(sc.npvSum)}, of which {group(sc.doubledPv)} is counted twice. Exact: <span className="mono">{sc.npvExact}</span></p><Link to={`portfolio?scenario=${sc.id}`}>Open the portfolio</Link></div>
                <div className="card card--brass" data-testid="card-residual"><h3>Double-count residual</h3><span className="big" data-figure="residual">{group(sc.residual)}</span><p>{sc.residual === "0.00" ? "No benefit is claimed twice in this scenario." : `Shared claims counted once (hours residual ${group(sc.hoursResidual)}); the overlap must be explained before a scenario can be proposed.`}</p><Link to={`portfolio?scenario=${sc.id}`}>See the shared keys</Link></div>
                <div className="card" data-testid="card-payback"><h3>Never paying back</h3><span className="big" data-figure="never-simple">{sc.neverSimple} of {sc.initiatives}</span><p>initiatives have no simple payback within the horizon ({sc.neverDiscounted} have no discounted payback). Null, not zero.</p><Link to={`business-case?scenario=${sc.id}`}>Open the business case</Link></div>
                <div className="card card--brass" data-testid="card-people"><h3>Adoption is not training</h3><span className="big" data-figure="adoption-summary">{sum["adoption_rate"] ?? "n/a"}</span><p>pooled adoption rate; pooled training completion is <span className="mono" data-figure="training-summary">{sum["training_completion"] ?? "n/a"}</span>. Two series, never substituted.</p><Link to="readiness">Open the readiness review</Link></div>
              </div>
            </section>
          )}
          <section aria-labelledby="h-plates">
            <h2 id="h-plates">The plates</h2>
            <ul className="routes">
              {ROUTES.filter((r) => r.path !== "").map((r) => (
                <li key={r.path}><Link to={r.path}><strong>{r.plate}: {r.title}</strong><span>{r.blurb}</span>{r.entry && <> <Chip kind="note">entry</Chip></>}</Link></li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="h-read">
            <h2 id="h-read">How to read it</h2>
            <ul>
              <li><strong>Four benefit classes</strong> (cash, avoided cost, revenue, capacity) are shown in separate columns and never added into one number without a declared conversion.</li>
              <li><strong>Two principal representations:</strong> the roadmap (initiatives as bars on periods, with dependencies and resource lanes) and the cash-flow table (each row beside the assumption versions that produced it).</li>
              <li><strong>Labels:</strong> an <Chip kind="note">estimate</Chip> is a model output; an observed change is <Chip kind="hatch">observed, not attributed</Chip>; a readiness score is an assessment, not a probability.</li>
            </ul>
            <p>The hand-derived golden case can be recomputed on <Link to="business-case">the business case</Link>, or the whole site can be opened on it with <a href={`${import.meta.env.BASE_URL}?dataset=golden`} data-testid="golden-link">?dataset=golden</a>.</p>
          </section>
          <p data-testid="backlink"><a href={PORTFOLIO}>Back to Rishit Raj Mathur's projects</a></p>
        </>
      );
    }}</WithData>
  );
}
