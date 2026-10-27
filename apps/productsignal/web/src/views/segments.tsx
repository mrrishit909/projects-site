import { Link } from "../components/link";
import { Chip, Choice, Def, NotBuilt, Scroll, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { SEGMENT_FIELDS } from "../domain/contract";
import { isoZ } from "../domain/time";
import { minus, pp } from "../lib/format";
import { runLabel, useRun } from "../lib/pick";
import { useParam } from "../router";

function Segments({ ds }: { ds: Dataset }) {
  const [run, setRun] = useRun(ds);
  const [byRaw, setBy] = useParam("by", "plan");
  const by = (SEGMENT_FIELDS as readonly string[]).includes(byRaw) ? byRaw : "plan";
  const ex = ds.at(run.cutoff_at, run.experiment_version_id, run.analysis_id).metrics.experiment!;
  const seg = ds.segmentsFamily(run.cutoff_at, run.experiment_version_id, by);
  const family = seg.family_size ?? seg.segments_tested;
  const withheld = ex.srm.verdict === "MISMATCH";
  return (
    <>
      <ViewHead eyebrow="Segment analysis" title="Where might the effect differ?">
        <p className="lede">Exploratory only. Cutting an experiment by segment gives many small comparisons, and some will look different by chance. Each result carries the label, the number of segments tested and a Bonferroni-adjusted threshold; no decision may cite a segment.</p>
      </ViewHead>
      <div className="controls">
        <Choice name="run" legend="Analysis run" value={run.analysis_id} onChange={setRun} testid="run-picker" options={ds.runs.map((r) => ({ value: r.analysis_id, label: runLabel(ds, r) }))} />
        <Choice name="by" legend="Split by" value={by} onChange={setBy} testid="by-picker" options={SEGMENT_FIELDS.map((f) => ({ value: f, label: f }))} />
      </div>
      <p className="callout callout--warn" data-testid="exploratory-label"><Chip v="exploratory">exploratory</Chip> <strong>{seg.segments_tested} segments tested</strong> by {by} at {isoZ(run.cutoff_at)}, {family} comparisons across the {SEGMENT_FIELDS.length} splits offered on this page; Bonferroni threshold <span className="mono" data-k="threshold">{seg.bonferroni_threshold}</span> (alpha {seg.alpha} ÷ <span data-k="family">{family}</span>). Not a decision basis.</p>
      {withheld ? <p className="callout callout--bad" data-testid="segments-withheld">Withheld for this run: the sample ratio check failed ({ex.srm.verdict}), so no comparison of arms, by segment or overall, is shown.</p> : (
        <Scroll label="Segment results">
          <table data-testid="segment-table">
            <thead><tr><th scope="col">{by}</th><th scope="col">Label</th><th scope="col" className="num">Control activated / mature</th><th scope="col" className="num">Treatment activated / mature</th><th scope="col" className="num">Absolute effect</th><th scope="col" className="num">p (pooled z)</th><th scope="col" className="num">Interval at the adjusted level</th><th scope="col">Below the threshold?</th></tr></thead>
            <tbody>{seg.segments.map((s) => (
              <tr key={s.value} data-segment={s.value}>
                <th scope="row">{s.value}</th>
                <td><Chip v="exploratory">exploratory</Chip></td>
                <td className="num mono">{s.variants["control"]!.activated} / {s.variants["control"]!.mature_units}</td>
                <td className="num mono">{s.variants["treatment"]!.activated} / {s.variants["treatment"]!.mature_units}</td>
                <td className="num mono">{pp(s.absolute_lift_pp)}</td>
                <td className="num mono">{s.p_value ?? "n/a"}</td>
                <td className="num mono">{s.adjusted_interval ? `[${minus(s.adjusted_interval.low)}, ${minus(s.adjusted_interval.high)}] at ${s.adjusted_interval.confidence}` : "n/a"}</td>
                <td>{s.adjusted_interval === null ? "n/a" : s.below_bonferroni_threshold ? "yes (a hypothesis, not a finding)" : "no"}</td>
              </tr>
            ))}</tbody>
          </table>
        </Scroll>
      )}
      <p className="muted"><Def term="how the threshold works">With k comparisons, a segment is called "below the threshold" only if its p-value is under alpha ÷ k (alpha = 1 − confidence). k counts every segment tested in every split this page offers (plan, segment and timezone together, not only the split on screen), because a reader who switches the split is making those comparisons too; the API's segment analysis of one split corrects within that split. The interval uses the matching adjusted level, from the normal critical value found by bisection. A segment counts as tested only when both arms have assigned accounts in it.</Def> Segments are read from the account's plan, segment or timezone attribute, all fixed before assignment. {" "}
        <Link to="population">Assigned and exposed</Link>.</p>
      <NotBuilt>Interaction tests, effect-heterogeneity models, and any segment-based targeting. A segment that looks different is a hypothesis for the next experiment, never a decision basis.</NotBuilt>
    </>
  );
}
export function SegmentsView() { return <WithData>{(ds) => <Segments ds={ds} />}</WithData>; }
