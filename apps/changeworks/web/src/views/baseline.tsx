import { PlateHead, Chip, NoData, ParamSelect, Scroll, WithData, ExportCsv } from "../components/ui";
import { Link } from "../components/link";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { cmp, fr, div, mul, m4, sumFr, type Fr } from "../domain/num";
import { useParam } from "../router";
import { toCsv } from "../lib/csv";
import { defaultScenario, programmeOf } from "../lib/derive";
import { bp, day, group, n0 } from "../lib/format";
import { basisPoints } from "../lib/scale";

export function BaselineView() { return <WithData>{(ds) => <Baseline ds={ds} />}</WithData>; }

function Baseline({ ds }: { ds: Dataset }) {
  const [prog, setProg] = useParam("programme", "all");
  const [show, setShow] = useParam("show", "all");
  const sid = defaultScenario(ds);
  const programmes = ds.manifest.programmes ?? [];
  const all = [...ds.result.population.acc.process_baselines].sort((a, b) => cmp(a["initiative_id"], b["initiative_id"]) || cmp(a["baseline_version"], b["baseline_version"]));
  const status = (b: Row): "approved" | "later" | "unapproved" => {
    const cur = ds.byId.initiatives.get(b["initiative_id"])!["baseline_version"];
    return cur === null ? "unapproved" : cur === b["baseline_version"] ? "approved" : "later";
  };
  const rows = all.filter((b) => (prog === "all" || programmes.find((p) => p.programme_id === prog)?.initiative_ids.includes(b["initiative_id"])) && (show === "all" || status(b) === "approved"));
  const effort = (b: Row): Fr => div(mul(fr(b["volume"]), fr(b["minutes_per_case"])), fr(60));
  const maxVol = rows.reduce((m, b) => Math.max(m, b["volume"]), 1);
  const maxEff = rows.reduce<Fr>((m, b) => (effort(b).n * m.d > m.n * effort(b).d ? effort(b) : m), fr(1));
  const approved = all.filter((b) => status(b) === "approved");
  const hours = ds.metrics["scenarios"][sid]?.["initiatives"] as Row | undefined;
  const csv = toCsv(["initiative", "version", "status", "volume", "minutes_per_case", "error_rate", "effort_hours_per_period", "evidence_ref", "measured_at", "reason"],
    rows.map((b) => [b["initiative_id"], b["baseline_version"], status(b), b["volume"], b["minutes_per_case"], b["error_rate"], m4(effort(b)), b["evidence_ref"], b["measured_at"], b["reason"]]));
  return (
    <>
      <PlateHead mark="Plate II" title="Baseline evidence">
        <p className="lede">What was measured before the change: cases handled, minutes per case and the error rate, with the evidence behind each figure. An approved baseline is immutable; a correction is a new version and the earlier one stays readable.</p>
      </PlateHead>
      <div className="controls">
        <ParamSelect name="programme" label="Programme" dflt="all" testid="programme-filter" options={[{ value: "all", label: "All programmes" }, ...programmes.map((p) => ({ value: p.programme_id, label: p.name }))]} />
        <ParamSelect name="show" label="Versions" dflt="all" testid="version-filter" options={[{ value: "all", label: "Every version" }, { value: "approved", label: "Approved only" }]} />
      </div>
      <dl className="facts" data-testid="baseline-facts">
        <div><dt>Baseline rows</dt><dd data-figure="rows">{all.length}</dd></div>
        <div><dt>Approved versions in force</dt><dd data-figure="approved">{approved.length}</dd></div>
        <div><dt>Initiatives with no approved baseline</dt><dd data-figure="unapproved">{[...ds.byId.initiatives.values()].filter((i) => i["baseline_version"] === null).length}</dd></div>
      </dl>
      <p className="small muted">Volume is cases per period; effort is volume × minutes per case ÷ 60, in hours per period (exact, shown to 4 places); error rate is a proportion with 6 places. Later versions are readable but unused until approved; initiatives without an approved baseline have no capacity-released figure (null, not zero).</p>
      {rows.length === 0 ? <NoData what="baseline rows" onClear={() => { setProg("all"); setShow("all"); }} /> : (
        <Scroll label="Process baselines">
          <table data-testid="baselines">
            <caption>Process baselines by initiative and version</caption>
            <thead><tr><th>Initiative</th><th>Version</th><th>Status</th><th className="num">Volume</th><th>Volume</th><th className="num">Minutes per case</th><th className="num">Effort, h per period</th><th>Effort</th><th className="num">Error rate</th><th>Evidence</th><th>Measured</th><th className="num">Released, h (scenario {sid})</th></tr></thead>
            <tbody>{rows.map((b) => {
              const st = status(b);
              const rel = hours?.[b["initiative_id"]]?.["capacity_released"]?.["hours"] as string | null | undefined;
              return (
                <tr key={b["baseline_id"]} data-baseline={b["baseline_id"]} className={st === "approved" ? "is-on" : undefined}>
                  <th scope="row" className="wrapcell"><Link to={`business-case?initiative=${b["initiative_id"]}`}>{b["initiative_id"]}</Link><br /><span className="muted small">{ds.byId.initiatives.get(b["initiative_id"])!["title"]}<br />{programmeOf(ds, b["initiative_id"])?.name}</span></th>
                  <td>{b["baseline_version"]}</td>
                  <td data-k="status">{st === "approved" ? <Chip kind="ok">approved</Chip> : st === "later" ? <Chip kind="hatch">later version, unused</Chip> : <Chip kind="plain">not approved</Chip>}</td>
                  <td className="num" data-k="volume">{n0(b["volume"])}</td><td><span className="meter" aria-hidden="true"><i style={{ width: bp(basisPoints(fr(b["volume"]), fr(maxVol))) }} /></span></td>
                  <td className="num" data-k="minutes">{b["minutes_per_case"]}</td><td className="num" data-k="effort">{group(m4(effort(b)))}</td><td><span className="meter" aria-hidden="true"><i style={{ width: bp(basisPoints(effort(b), maxEff)) }} /></span></td>
                  <td className="num" data-k="error">{b["error_rate"]}</td>
                  <td className="wrapcell small mono">{b["evidence_ref"]}{b["reason"] ? <><br /><span className="muted">reason: {b["reason"]}</span></> : null}</td>
                  <td className="small">{day(b["measured_at"])}</td>
                  <td className="num" data-k="released">{st === "approved" ? (rel ? group(rel) : "n/a") : "n/a"}</td>
                </tr>
              );
            })}</tbody>
            <tfoot><tr><th scope="row" colSpan={6}>Approved rows on screen: effort, hours per period (each initiative counts once, its own scale)</th><td className="num">{group(m4(sumFr(rows.filter((b) => status(b) === "approved").map(effort))))}</td><td colSpan={5} /></tr></tfoot>
          </table>
        </Scroll>
      )}
      <ExportCsv name="baselines.csv" csv={csv} label="Download the baseline rows on screen as CSV" />
      <p className="small muted">Programme approvals: {programmes.map((p) => `${p.name}: ${p.approved_baseline_version ?? "none yet"}`).join("; ") || "not recorded in this dataset"}. Nothing on this plate is estimated: every figure is a recorded measurement.</p>
    </>
  );
}
