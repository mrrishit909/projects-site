import { Chip, Def, NoData, ParamSelect, PlateHead, Scroll, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { DIMENSIONS, type Row } from "../domain/contract";
import { cmp, fr, sub, div } from "../domain/num";
import { useParam } from "../router";
import { bp, n0 } from "../lib/format";
import { basisPoints } from "../lib/scale";

export function ReadinessView() { return <WithData>{(ds) => <Readiness ds={ds} />}</WithData>; }

function Readiness({ ds }: { ds: Dataset }) {
  const [level, setLevel] = useParam("level", "all");
  const [show, setShow] = useParam("show", "all");
  const gm = ds.metrics["groups"] as Row;
  const ids = Object.keys(gm).sort(cmp);
  const rows = ids.filter((g) => (level === "all" || gm[g].impact_level === level) && (show === "all" || gm[g].readiness_score !== null));
  const assessed = ids.filter((g) => gm[g].readiness_score !== null).length;
  const inits = Object.keys(ds.metrics["initiatives"]).sort(cmp);
  const span = fr(4);
  return (
    <>
      <PlateHead mark="Plate VII" title="Readiness review">
        <p className="lede">How ready each group is for the change, on five ADKAR-inspired dimensions scored 1 to 5 with declared weights. A readiness score is <strong>an assessment, not a probability</strong> of adoption.</p>
      </PlateHead>
      <dl className="facts" data-testid="readiness-facts">
        <div><dt>Groups</dt><dd data-figure="groups">{ids.length}</dd></div><div><dt>Assessed on at least one dimension</dt><dd data-figure="assessed">{assessed}</dd></div>
        <div><dt>Not assessed (null, not zero)</dt><dd data-figure="unassessed">{ids.length - assessed}</dd></div>
      </dl>
      <div className="controls">
        <ParamSelect name="level" label="Impact level" dflt="all" testid="level-filter" options={[{ value: "all", label: "All levels" }, { value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" }]} />
        <ParamSelect name="show" label="Show" dflt="all" testid="assessed-filter" options={[{ value: "all", label: "All groups" }, { value: "assessed", label: "Assessed only" }]} />
      </div>
      {rows.length === 0 ? <NoData what="groups" onClear={() => { setLevel("all"); setShow("all"); }} /> : (
        <Scroll label="Readiness by group and dimension">
          <table data-testid="readiness-table">
            <caption>Readiness by group: latest assessment per dimension at or before the as-of date</caption>
            <thead><tr><th>Group</th><th>Level</th><th className="num">People</th>{DIMENSIONS.map((d) => <th key={d} className="num">{d}</th>)}<th className="num">Score (1 to 5)</th><th>Scale</th><th>Label</th></tr></thead>
            <tbody>{rows.map((g) => {
              const r = gm[g] as Row;
              const dim = new Map<string, Row>((r["dimensions"] as Row[]).map((d) => [d["dimension"], d]));
              return (
                <tr key={g} data-group={g}>
                  <th scope="row" className="wrapcell">{ds.byId.groups.get(g)?.["group_name"]}<br /><span className="muted small mono">{g}</span></th><td>{r["impact_level"]}</td><td className="num">{n0(r["affected_count"])}</td>
                  {DIMENSIONS.map((d) => <td key={d} className="num" data-k={d}>{dim.has(d) ? `${dim.get(d)!["score"]} × ${dim.get(d)!["weight"]}` : "not assessed"}</td>)}
                  <td className="num" data-k="score">{r["readiness_score"] ?? "n/a"}</td>
                  <td><span className="meter" aria-hidden="true"><i style={{ width: r["readiness_exact"] ? bp(basisPoints(div(sub(parseExact(r["readiness_exact"]), fr(1)), span), fr(1))) : "0%" }} /></span></td>
                  <td><Chip kind="hatch">assessment, not a probability</Chip> <span className="small muted">{r["dimensions_assessed"]} of 5 dimensions</span></td>
                </tr>);
            })}</tbody>
          </table>
        </Scroll>
      )}
      <p className="small muted"><Def term="How a score is formed">Readiness = Σ weight × score ÷ Σ weight over the dimensions assessed for the group (exact, shown to 4 places). Entries are score × weight. An incomplete set is allowed and says so in the last column.</Def> Scores are on a 1 to 5 scale, so the bar runs from 1 to 5, not from 0.</p>
      <section aria-labelledby="h-adopt">
        <h2 id="h-adopt">Adoption is not training</h2>
        <p>Training completion (completed ÷ eligible trainees) and adoption (adopted ÷ eligible, with the denominator kept) are two series. A high completion rate is never read as adoption.</p>
        <Scroll label="Training completion beside adoption">
          <table data-testid="adoption-table">
            <caption>Latest training completion and adoption rate by initiative</caption>
            <thead><tr><th>Initiative</th><th className="num">Training completion</th><th className="num">Trainees</th><th className="num">Adoption rate</th><th className="num">Adopted ÷ eligible</th><th>Rule</th><th>Differ?</th></tr></thead>
            <tbody>{inits.map((i) => {
              const m = ds.metrics["initiatives"][i] as Row;
              return <tr key={i} data-initiative={i}><th scope="row">{i}</th><td className="num" data-k="training">{m["training"]["training_completion"] ?? "n/a"}</td><td className="num">{m["training"]["completed"] === null ? "n/a" : `${m["training"]["completed"]} ÷ ${m["training"]["eligible_trainees"]}`}</td>
                <td className="num" data-k="adoption">{m["adoption"]["adoption_rate"] ?? "n/a"}</td><td className="num">{m["adoption"]["adopted_count"] === null ? "n/a" : `${m["adoption"]["adopted_count"]} ÷ ${m["adoption"]["eligible_count"]}`}</td><td>{m["adoption"]["eligibility_rule_version"]}</td>
                <td>{m["training"]["differs_from_adoption"] === null ? "unknown" : m["training"]["differs_from_adoption"] ? "yes, two numbers" : "equal"}</td></tr>;
            })}</tbody>
          </table>
        </Scroll>
        <p className="small muted" data-testid="pooled">Pooled over the initiatives that have a series: training completion {ds.metrics["summary"]["training_completion"] ?? "n/a"}, adoption {ds.metrics["summary"]["adoption_rate"] ?? "n/a"}. Eligibility is fixed by each initiative's rule version; a record under another rule is refused.</p>
      </section>
    </>
  );
}
function parseExact(s: string) { const [n, d] = s.split("/"); return { n: BigInt(n!), d: BigInt(d ?? 1) }; }
