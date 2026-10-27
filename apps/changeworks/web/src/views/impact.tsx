import { useState } from "react";
import { Chip, ExportCsv, NoData, ParamSelect, PlateHead, Scroll, WithData } from "../components/ui";
import { Link } from "../components/link";
import type { Dataset } from "../data/dataset";
import { cmp, fr } from "../domain/num";
import { useParam } from "../router";
import { toCsv } from "../lib/csv";
import { bp, n0 } from "../lib/format";
import { basisPoints } from "../lib/scale";

export function ImpactView() { return <WithData>{(ds) => <Impact ds={ds} />}</WithData>; }
const kind = (l: string): "crit" | "note" | "plain" => (l === "high" ? "note" : l === "medium" ? "plain" : "plain");

function Impact({ ds }: { ds: Dataset }) {
  const [level, setLevel] = useParam("level", "all");
  const [iid, setIid] = useParam("initiative", "all");
  const [q, setQ] = useState("");
  const acc = ds.result.population.acc;
  const groups = ds.byId.groups;
  const rows = acc.impact_mappings.filter((m) => (level === "all" || m["impact_level"] === level) && (iid === "all" || m["initiative_id"] === iid)
    && (!q.trim() || `${groups.get(m["group_id"])?.["group_name"]} ${m["operating_change"]}`.toLowerCase().includes(q.trim().toLowerCase())))
    .sort((a, b) => cmp(a["initiative_id"], b["initiative_id"]) || cmp(a["mapping_id"], b["mapping_id"]));
  const byIni = [...ds.byId.initiatives.keys()].sort(cmp).map((id) => {
    const ms = acc.impact_mappings.filter((m) => m["initiative_id"] === id);
    const gs = [...new Set(ms.map((m) => m["group_id"] as string))];
    return { id, n: ms.length, high: ms.filter((m) => m["impact_level"] === "high").length, medium: ms.filter((m) => m["impact_level"] === "medium").length, low: ms.filter((m) => m["impact_level"] === "low").length, groups: gs.length, people: gs.reduce((s, g) => s + (groups.get(g)?.["affected_count"] ?? 0), 0) };
  });
  const maxN = Math.max(1, ...byIni.map((r) => r.n));
  const csv = toCsv(["mapping", "initiative", "group", "group_name", "affected_count", "impact_level", "operating_change"], rows.map((m) => [m["mapping_id"], m["initiative_id"], m["group_id"], groups.get(m["group_id"])?.["group_name"], groups.get(m["group_id"])?.["affected_count"], m["impact_level"], m["operating_change"]]));
  const clear = (): void => { setLevel("all"); setIid("all"); setQ(""); };
  return (
    <>
      <PlateHead mark="Plate VI" title="Change impact">
        <p className="lede">Which groups of people each initiative changes, and what changes for them day to day. Group names are synthetic roles and teams, never people.</p>
      </PlateHead>
      <dl className="facts" data-testid="impact-facts">
        <div><dt>Stakeholder groups</dt><dd data-figure="groups">{groups.size}</dd></div>
        <div><dt>Operating-change mappings</dt><dd data-figure="mappings">{acc.impact_mappings.length}</dd></div>
        <div><dt>Initiatives with a mapping</dt><dd data-figure="mapped">{byIni.filter((r) => r.n).length} of {byIni.length}</dd></div>
      </dl>
      <h2>Reach by initiative</h2>
      <Scroll label="Impact by initiative">
        <table data-testid="impact-by-initiative">
          <caption>Mappings per initiative, by impact level</caption>
          <thead><tr><th>Initiative</th><th className="num">Mappings</th><th>Mappings</th><th className="num">High</th><th className="num">Medium</th><th className="num">Low</th><th className="num">Groups</th><th className="num">Sum of group counts</th></tr></thead>
          <tbody>{byIni.map((r) => (
            <tr key={r.id} data-initiative={r.id}><th scope="row"><button type="button" className="button--quiet" onClick={() => setIid(r.id)} aria-label={`Show the mappings of ${r.id}`}>{r.id}</button></th><td className="num">{r.n}</td>
              <td><span className="meter" aria-hidden="true"><i style={{ width: bp(basisPoints(fr(r.n), fr(maxN))) }} /></span></td><td className="num">{r.high}</td><td className="num">{r.medium}</td><td className="num">{r.low}</td><td className="num">{r.groups}</td><td className="num">{n0(r.people)}</td></tr>))}</tbody>
        </table>
      </Scroll>
      <p className="small muted">"Sum of group counts" adds the affected counts of the distinct groups an initiative touches; a person who belongs to two groups is counted twice, so it is a reach measure, not a headcount. Mappings are validated and counted only; no impact score is derived from them.</p>
      <h2>Operating changes</h2>
      <div className="controls">
        <ParamSelect name="level" label="Impact level" dflt="all" testid="level-filter" options={[{ value: "all", label: "All levels" }, { value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" }]} />
        <ParamSelect name="initiative" label="Initiative" dflt="all" testid="impact-initiative" options={[{ value: "all", label: "All initiatives" }, ...byIni.map((r) => ({ value: r.id, label: r.id }))]} />
        <label>Search<input type="text" value={q} onChange={(e) => setQ(e.target.value)} data-testid="impact-search" /></label>
      </div>
      {rows.length === 0 ? <NoData what="operating changes" onClear={clear} /> : (
        <Scroll label="Operating changes">
          <table data-testid="mappings">
            <caption>{rows.length} operating changes</caption>
            <thead><tr><th>Initiative</th><th>Group</th><th className="num">People in group</th><th>Level</th><th>What changes</th></tr></thead>
            <tbody>{rows.map((m) => (
              <tr key={m["mapping_id"]} data-mapping={m["mapping_id"]}><th scope="row"><Link to={`roadmap?initiative=${m["initiative_id"]}`}>{m["initiative_id"]}</Link></th>
                <td className="wrapcell">{groups.get(m["group_id"])?.["group_name"]}<br /><span className="muted small mono">{m["group_id"]}</span></td><td className="num">{n0(groups.get(m["group_id"])?.["affected_count"] ?? 0)}</td>
                <td><Chip kind={kind(m["impact_level"])}>{m["impact_level"]}</Chip></td><td className="wrapcell">{m["operating_change"]}</td></tr>))}</tbody>
          </table>
        </Scroll>
      )}
      <ExportCsv name="operating-changes.csv" csv={csv} label="Download the operating changes on screen as CSV" />
    </>
  );
}
