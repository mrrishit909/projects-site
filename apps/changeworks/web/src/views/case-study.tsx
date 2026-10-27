import { Chip, NoData, PlateHead, WithData } from "../components/ui";
import { Link } from "../components/link";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { cmp } from "../domain/num";
import { replayInjections } from "../lib/claims";
import { defaultScenario, scenariosWith } from "../lib/derive";
import { group } from "../lib/format";

export function CaseStudy() {
  return (
    <>
      <PlateHead mark="Plate XI" title="Case study">
        <p className="lede" data-testid="cs-problem">Which transformation initiative should be funded, and how will success be established? An investment case is only as honest as its separation of cash from capacity, estimate from observation, and plan from what the trend would have given anyway.</p>
      </PlateHead>
      <WithData>{(ds) => <Findings ds={ds} />}</WithData>
    </>
  );
}

function Findings({ ds }: { ds: Dataset }) {
  const sid = defaultScenario(ds);
  const sc = ds.metrics["scenarios"][sid] as Row | undefined;
  const get = (iid: string): Row | undefined => sc?.["initiatives"][iid];
  const d9 = get("init-009"), d15 = get("init-015"), d3 = ds.metrics["initiatives"]["init-003"] as Row | undefined, d8 = get("init-008");
  const res3 = ds.metrics["resources"]["res-03"] as Row | undefined;
  const refused = ds.injections ? replayInjections(ds).steps.filter((s) => s.event === "EV-09" && s.got === "rejected").length : 0;
  const dc = sc?.["double_count"] as Row | undefined;
  const real8 = d8?.["benefit_realization"]["cash"] as Row | undefined;
  const sum = ds.metrics["summary"] as Row;
  const have = ds.id === "snapshot" && !!sc && !!d9 && !!d15 && !!d3 && !!res3;
  return (
    <>
      <section aria-labelledby="h-logic"><h2 id="h-logic">The investment logic</h2>
        <ol>
          <li><strong>Evidence first.</strong> A process baseline (volume, minutes per case, error rate) is measured, approved and then immutable; a correction is a new version.</li>
          <li><strong>Assumptions beside it.</strong> Ramps, targets, rates and conversions are versioned assumptions with an author and a rationale, pinned by a scenario.</li>
          <li><strong>Four classes of benefit.</strong> Cash and revenue enter the cash flow; avoided cost only with a removed budget line; capacity only with a conversion and staffing-change evidence. Dollars and hours are never added.</li>
          <li><strong>Exact discounting.</strong> NPV is a sum of rationals; a rate must match the period basis or be converted by a recorded assumption; two paybacks are reported separately and are null when never reached.</li>
          <li><strong>No double counting.</strong> A benefit claimed twice from one source counts once, and the residual is explained before a scenario can be proposed. A proposal is not funding.</li>
          <li><strong>Success as observation.</strong> Realisation is compared within a type, on matured periods, beside the baseline trend, and labelled <Chip kind="hatch">observed, not attributed</Chip>.</li>
        </ol>
      </section>
      <section aria-labelledby="h-find" data-testid="cs-findings">
        <h2 id="h-find">What the snapshot shows</h2>
        {!have ? <NoData what="findings (they are computed from the published snapshot, not from the golden fixture)" /> : (
          <ul>
            <li data-finding="capacity"><strong>Hours are not cash.</strong> init-009 plans only capacity: {group(d9!["excluded_from_cash_flow"]["capacity_hours_not_converted"])} hours stay out of the cash flow, so in {sid} its NPV is {group(d9!["npv"]["value"])} USD and it has no payback ({d9!["payback"]["simple"]["period"] === null ? "null" : "reached"}). Releasing {d9!["capacity_released"]["hours"]} hours a period is not a saving until staffing changes.</li>
            <li data-finding="double-count"><strong>Two initiatives, one team.</strong> Planned benefits of {group(dc!["planned_benefits"])} USD fall to {group(dc!["attributable_benefits"])} once the shared source {(dc!["overlaps"] as Row[])[0]?.["benefit_source_key"]} is counted once: a residual of {group(dc!["residual"])} over {(dc!["overlaps"] as Row[]).length} periods, present in {Object.keys(ds.metrics["scenarios"]).filter((s) => ds.metrics["scenarios"][s]["double_count"]["residual"] !== "0.00").length} of {Object.keys(ds.metrics["scenarios"]).length} scenarios.</li>
            <li data-finding="never-pays-back"><strong>Some never pay back.</strong> init-015 has no simple or discounted payback in {scenariosWith(ds, "init-015").filter((s) => ds.metrics["scenarios"][s]["initiatives"]["init-015"]["payback"]["simple"]["period"] === null).length} of its {scenariosWith(ds, "init-015").length} scenarios; its NPV in {sid} is {group(d15!["npv"]["value"])} USD. Null, never 0.</li>
            <li data-finding="forecast"><strong>A forecast revised, the original kept.</strong> init-003: {(d3!["forecast"]["versions"] as Row[]).map((v) => `v${v["version_number"]} ${group(v["total"])}`).join(" → ")}; the latest is {group(d3!["forecast"]["latest_minus_original"])} USD from the original, which is still on record.</li>
            <li data-finding="resource"><strong>A shared specialist at capacity.</strong> res-03 is fully allocated in periods {(res3!["by_period"] as Row[]).filter((b) => b["headroom"] === "0.00").map((b) => b["period_index"]).join(", ")}; {refused} further requests are refused rather than stored.</li>
            <li data-finding="attribution"><strong>Improvement is not attribution.</strong> init-008's cash benefit realises {real8?.["realization"]} of plan, but the trend recorded before deployment is {group(real8?.["baseline_trend"] ?? null)} of the {group(real8?.["observed_comparable"] ?? null)} observed; only {group(real8?.["observed_above_trend"] ?? null)} is above the trend, and even that is not attributed.</li>
            <li data-finding="people"><strong>Trained is not adopted.</strong> Pooled training completion is {sum["training_completion"]} while pooled adoption is {sum["adoption_rate"]}; the two series are never substituted.</li>
          </ul>
        )}
        <p className="small muted">These sentences are generated from the computation on this page load; if the data changes they change with it. They describe a synthetic world, not a real portfolio.</p>
      </section>
      <section aria-labelledby="h-lim"><h2 id="h-lim">Limits of attribution</h2>
        <ul>
          <li>A baseline trend is an estimate made before deployment; it is evidence of what was already happening, not of what would have happened.</li>
          <li>The share above the trend is shown beside the raw change, never in place of it, and no figure here claims the rollout caused it.</li>
          <li>Risk exposure is Σ probability × impact and is a scenario estimate; readiness is an assessment, not a probability.</li>
          <li>The snapshot covers {String(ds.manifest.config["periods"] ?? "")} periods but benefits only 12 per stream: a first-year case.</li>
        </ul>
      </section>
      <p>See the <Link to="portfolio">portfolio</Link>, the <Link to="business-case">business case</Link>, the <Link to="roadmap">roadmap</Link> and the <Link to="evidence">evidence</Link>. {[...ds.byId.initiatives.keys()].sort(cmp).length} initiatives, synthetic.</p>
      <aside className="notbuilt" data-testid="not-built"><strong>Not built here.</strong> No funding decision, no workbook export and no live data: the formula-driven workbook and the executive recommendation are deliverables of the backend work, and this site only reads a snapshot.</aside>
    </>
  );
}
