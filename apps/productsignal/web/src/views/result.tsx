import { ArmFunnel } from "../components/charts";
import { Disclosures, GuardrailBlock, PrimaryBlock, RevenueBlock, RunHead, SrmBlock, WithheldBlock } from "../components/experiment";
import { Link } from "../components/link";
import { Choice, ViewHead, WithDataset } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { goldenShape } from "../data/dataset";
import { compareLeaves } from "../lib/compare";
import { defaultRun, runLabel, useRun } from "../lib/pick";
import type { AnalysisRun } from "../domain/models";

function Report({ ds, run }: { ds: Dataset; run: AnalysisRun }) {
  const ex = ds.at(run.cutoff_at, run.experiment_version_id, run.analysis_id).metrics.experiment!;
  const withheld = ex.srm.verdict === "MISMATCH";
  return (
    <div data-run={run.analysis_id} data-withheld={withheld ? "true" : "false"}>
      <RunHead ds={ds} run={run} ex={ex} />
      <SrmBlock ex={ex} />
      {withheld ? <WithheldBlock ex={ex} /> : <><PrimaryBlock ex={ex} /><ArmFunnel ex={ex} /></>}
      <GuardrailBlock ds={ds} ex={ex} />
      <RevenueBlock ex={ex} />
    </div>
  );
}

function GoldenCase({ ds }: { ds: Dataset }) {
  const run = defaultRun(ds);
  const check = ds.expected ? compareLeaves(goldenShape(ds), ds.expected) : null;
  return (
    <section className="block block--golden" data-testid="golden-case" aria-labelledby="golden-h">
      <h2 id="golden-h">The golden case, recomputed in your browser</h2>
      <p className="muted">A hand-derived fixture of {ds.population.accounts.length} accounts: 100 control and 100 treatment, 20 and 30 activated. Its expected results were worked out on paper before any code ran (docs: tests/fixtures/golden/CALCULATION.md). The browser's TypeScript mirror of the domain computes everything below from the raw rows.</p>
      {check && <p className="callout" data-testid="golden-check" data-ok={check.mismatches.length === 0 ? "true" : "false"}>Compared leaf by leaf with the fixture's expected.json: <strong data-k="leaves">{check.leaves - check.mismatches.length} of {check.leaves}</strong> values equal{check.mismatches.length ? `; differing: ${check.mismatches.slice(0, 5).join(", ")}` : ""}.</p>}
      <Report ds={ds} run={run} />
    </section>
  );
}

function SnapshotCase({ ds }: { ds: Dataset }) {
  const [run, setRun] = useRun(ds);
  return (
    <section className="block" data-testid="snapshot-case" aria-labelledby="snap-h">
      <h2 id="snap-h">The snapshot experiment</h2>
      <p className="muted">The onboarding checklist experiment in the synthetic 26-week snapshot: version 1 ran 2026-04-06 to 2026-08-02 with three interim runs and a final one; version 2 re-planned it with a 60/40 allocation. Pick a run: interim runs cannot support a ship decision, and the number of prior runs is part of every result.</p>
      <Choice name="run" legend="Analysis run" value={run.analysis_id} onChange={setRun} testid="run-picker" options={ds.runs.map((r) => ({ value: r.analysis_id, label: runLabel(ds, r) }))} />
      <Report ds={ds} run={run} />
      <Disclosures ds={ds} />
    </section>
  );
}

export function ResultView() {
  return (
    <>
      <ViewHead eyebrow="Experiment result" title="Did the onboarding change work?">
        <p className="lede">Order matters here: first the golden case, to show the computation reproduces a known answer; then the snapshot experiment, where the sample ratio check comes before any lift, and the lift comes with its interval rather than as a single number.</p>
      </ViewHead>
      <WithDataset id="golden">{(g) => <GoldenCase ds={g} />}</WithDataset>
      <WithDataset id="snapshot">{(s) => <SnapshotCase ds={s} />}</WithDataset>
      <p className="muted">Next: <Link to="population">assigned and exposed</Link> · <Link to="segments">segments (exploratory)</Link> · <Link to="decision">the decision memo</Link>.</p>
    </>
  );
}
