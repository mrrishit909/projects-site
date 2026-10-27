import { Link } from "../components/link";
import { Chip, Choice, Def, Scroll, ViewHead, WithData } from "../components/ui";
import { SrmBlock } from "../components/experiment";
import type { Dataset } from "../data/dataset";
import { isoZ } from "../domain/time";
import { n0 } from "../lib/format";
import { runLabel, useRun } from "../lib/pick";
import { laterRows } from "./overview";

function Population({ ds }: { ds: Dataset }) {
  const [run, setRun] = useRun(ds);
  const comp = ds.at(run.cutoff_at, run.experiment_version_id, run.analysis_id);
  const ex = comp.metrics.experiment!;
  const later = laterRows(ds, run.experiment_version_id, run.cutoff_at);
  const arms = Object.keys(ex.primary.variants);
  const withheld = ex.srm.verdict === "MISMATCH";
  return (
    <>
      <ViewHead eyebrow="Population" title="Assigned, mature and exposed">
        <p className="lede">The headline analysis counts everyone who was assigned and whose 7 days are complete, whether or not they ever saw the change. Exposure is reported beside it, never instead of it.</p>
      </ViewHead>
      <Choice name="run" legend="Analysis run" value={run.analysis_id} onChange={setRun} testid="run-picker" options={ds.runs.map((r) => ({ value: r.analysis_id, label: runLabel(ds, r) }))} />
      <SrmBlock ex={ex} />
      <section className="block" data-testid="denominators" aria-labelledby="den">
        <h2 id="den">Denominators at {isoZ(run.cutoff_at)}</h2>
        <Scroll label="Denominators by arm">
          <table>
            <thead><tr><th scope="col">Arm</th><th scope="col" className="num">Assigned</th><th scope="col" className="num">Mature</th><th scope="col" className="num">Not yet mature</th><th scope="col" className="num">Exposed (of mature)</th><th scope="col" className="num">Exposure rate</th></tr></thead>
            <tbody>
              {arms.map((v) => { const p = ex.primary.variants[v]!, e = ex.exposure.by_variant[v]!; return (
                <tr key={v} data-arm={v}><th scope="row">{v}</th><td className="num mono" data-k="assigned">{p.assigned}</td><td className="num mono" data-k="mature">{p.mature_units}</td><td className="num mono">{p.assigned - p.mature_units}</td><td className="num mono" data-k="exposed">{e.exposed}</td><td className="num mono" data-k="rate">{e.rate ?? "n/a"}</td></tr>
              ); })}
              <tr data-arm="all" className="total"><th scope="row">both arms</th><td className="num mono">{ex.assigned_units}</td><td className="num mono">{ex.mature_units}</td><td className="num mono">{ex.immature_or_unobserved_excluded}</td><td className="num mono">{ex.exposure.overall.exposed}</td><td className="num mono" data-k="overall-rate">{ex.exposure.overall.rate ?? "n/a"}</td></tr>
            </tbody>
          </table>
        </Scroll>
        <p className="muted">Exposure rate = exposed mature assigned accounts ÷ mature assigned accounts. An exposure must follow its assignment; the exposure of an account that was never assigned is rejected at ingest. After D-08, rows dated after this run's cutoff are not counted: {later.assignments} assignments, {later.exposures} exposures.</p>
      </section>
      <section className="block" data-testid="itt-vs-exposed" aria-labelledby="itt">
        <h2 id="itt">Intention to treat against exposed only</h2>
        {withheld ? <p className="callout callout--bad">Withheld for this run: the sample ratio check failed, so no comparison of arms is shown, exposed-only or otherwise.</p> : (
          <Scroll label="ITT against exposed only">
            <table>
              <thead><tr><th scope="col">Arm</th><th scope="col" className="num">ITT: activated / mature</th><th scope="col" className="num">ITT conversion</th><th scope="col" className="num">Exposed only: activated / exposed <Chip v="exploratory">exploratory</Chip></th><th scope="col" className="num">Exposed-only conversion</th></tr></thead>
              <tbody>{arms.map((v) => { const p = ex.primary.variants[v]!, x = ex.exploratory_exposed_only.by_variant[v]!; return (
                <tr key={v} data-arm={v}><th scope="row">{v}</th><td className="num mono">{p.activated} / {p.mature_units}</td><td className="num mono">{p.conversion ?? "n/a"}</td><td className="num mono">{x.activated} / {x.exposed_units}</td><td className="num mono">{x.conversion ?? "n/a"}</td></tr>
              ); })}</tbody>
            </table>
          </Scroll>
        )}
        <p className="muted"><Def term="why exposed-only is never a decision basis">Who gets exposed depends on the account: in the synthetic snapshot, accounts that would activate anyway are more likely to be exposed (designed relationship DR-07 in its manifest). Comparing only the exposed therefore mixes the treatment with who chose to look. ITT keeps the randomised comparison intact.</Def> The exposed-only block is labelled exploratory and is not part of the decision.</p>
      </section>
      <p className="muted">{n0(ex.assigned_units)} accounts assigned by the cutoff, {n0(ex.mature_units)} mature. Next: <Link to="result">the result</Link> · <Link to="segments">segments</Link>.</p>
    </>
  );
}
export function PopulationView() { return <WithData>{(ds) => <Population ds={ds} />}</WithData>; }
