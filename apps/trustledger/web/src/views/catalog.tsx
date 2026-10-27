import { Link } from "../components/link";
import { Chip, Choice, Def, Fig, Scroll, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/models";
import { dayTime } from "../lib/format";
import { useParam } from "../router";

const tokens = (q: string): string[] => q.toLowerCase().split(/\s+/).filter(Boolean);
const hit = (ts: string[], ...texts: (string | null | undefined)[]): boolean => { const hay = texts.map((x) => (x ?? "").toLowerCase()).join(" \u0001 "); return ts.every((t) => hay.includes(t)); };

function Ownership({ ds }: { ds: Dataset }) {
  const o = ds.now.metrics["ownership_coverage"];
  const rows = (o.uncovered as string[]).map((id) => ds.byId.datasets.get(id)!);
  return (
    <section className="block" data-testid="ownership" aria-labelledby="own">
      <h2 id="own">Ownership coverage</h2>
      <div className="pair-fig">
        <div><span className="big"><Fig k="ownership-value">{o.value}</Fig></span><span className="cap">{o.covered} of {o.datasets} datasets have an <Def term="active accountable owner">A dataset is covered only when its accountable owner is active at the as-of. An inactive owner leaves the dataset uncovered; it is never counted as covered (P07-MET-09).</Def></span></div>
        <div><span className="big"><Fig k="uncovered">{rows.length}</Fig></span><span className="cap">uncovered datasets</span></div>
      </div>
      {rows.length === 0 ? <p>Every dataset has an active owner.</p> : (
        <Scroll label="Uncovered datasets">
          <table data-testid="uncovered">
            <thead><tr><th scope="col">Dataset</th><th scope="col">Accountable owner</th><th scope="col">Team</th><th scope="col">Inactive since</th></tr></thead>
            <tbody>{rows.map((d) => { const ow = ds.byId.owners.get(d["owner_id"]); return (
              <tr key={d["dataset_id"]} data-dataset={d["dataset_id"]}><th scope="row" className="mono">{d["dataset_id"]}</th><td>{ow?.["owner_name"] ?? "(unknown)"} <span className="mono muted">{d["owner_id"]}</span></td><td>{ow?.["team"]}</td><td className="mono">{ow?.["deactivated_at"] ? dayTime(ow["deactivated_at"]) : "no instant recorded"}</td></tr>
            ); })}</tbody>
          </table>
        </Scroll>
      )}
    </section>
  );
}

function Results({ ds, q, scope }: { ds: Dataset; q: string; scope: string }) {
  const ts = tokens(q);
  const ownerOf = (id: string | null): Row | undefined => (id ? ds.byId.owners.get(id) : undefined);
  const owned = new Map<string, number>();
  for (const d of ds.raw.datasets) owned.set(d["owner_id"], (owned.get(d["owner_id"]) ?? 0) + 1);
  const datasets = ds.raw.datasets.filter((d) => { const o = ownerOf(d["owner_id"]); return hit(ts, d["dataset_id"], d["dataset_name"], d["source_system"], d["classification"], d["owner_id"], o?.["owner_name"], o?.["team"]); });
  const fields = ds.raw.fields.filter((f) => hit(ts, f["field_name"], f["dataset_id"], ds.byId.datasets.get(f["dataset_id"])?.["dataset_name"], f["data_type"]));
  const owners = ds.raw.owners.filter((o) => hit(ts, o["owner_id"], o["owner_name"], o["team"], o["role"], o["active"] ? "active" : "inactive"));
  const FIELD_LIMIT = 40;
  const show = (k: string): boolean => scope === "all" || scope === k;
  return (
    <>
      <p role="status" data-testid="result-counts">{datasets.length} datasets, {fields.length} fields and {owners.length} owners match{q ? <> “<span className="mono">{q}</span>”</> : " (no search text: everything is listed)"}.</p>
      {show("datasets") && (
        <section className="block" data-testid="datasets" aria-labelledby="dsets">
          <h2 id="dsets">Datasets ({datasets.length})</h2>
          <Scroll label="Datasets">
            <table>
              <thead><tr><th scope="col">Dataset</th><th scope="col">Name</th><th scope="col">Source</th><th scope="col">Classification</th><th scope="col">Accountable owner</th><th scope="col">Monitored</th></tr></thead>
              <tbody>{datasets.map((d) => { const o = ownerOf(d["owner_id"]); return (
                <tr key={d["dataset_id"]} data-dataset={d["dataset_id"]}>
                  <th scope="row" className="mono">{d["dataset_id"]}</th><td>{d["dataset_name"]}</td><td>{d["source_system"]}</td><td>{d["classification"]}</td>
                  <td>{o ? <>{o["owner_name"]} <span className="muted">({o["team"]})</span> {o["active"] ? <Chip kind="ok">active</Chip> : <Chip kind="hatch">inactive</Chip>}</> : "none"}</td>
                  <td>{d["monitored"] ? `${d["refresh_local_time"]} ${d["refresh_timezone"]}` : "no"}</td>
                </tr>); })}</tbody>
            </table>
          </Scroll>
        </section>
      )}
      {show("fields") && (
        <section className="block" data-testid="fields" aria-labelledby="flds">
          <h2 id="flds">Fields ({fields.length})</h2>
          <Scroll label="Fields">
            <table>
              <thead><tr><th scope="col">Field</th><th scope="col">Dataset</th><th scope="col">Type</th><th scope="col">Nullable</th></tr></thead>
              <tbody>{fields.slice(0, FIELD_LIMIT).map((f) => <tr key={f["field_id"]}><th scope="row" className="mono">{f["field_name"]}</th><td><span className="mono">{f["dataset_id"]}</span></td><td>{f["data_type"]}</td><td>{f["nullable"] ? "yes" : "no"}</td></tr>)}</tbody>
            </table>
          </Scroll>
          {fields.length > FIELD_LIMIT && <p className="muted">Showing the first {FIELD_LIMIT} of {fields.length}; narrow the search to see the rest.</p>}
        </section>
      )}
      {show("owners") && (
        <section className="block" data-testid="owners" aria-labelledby="ownr">
          <h2 id="ownr">Owners ({owners.length})</h2>
          <Scroll label="Owners">
            <table>
              <thead><tr><th scope="col">Owner</th><th scope="col">Name</th><th scope="col">Team</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col" className="num">Datasets</th></tr></thead>
              <tbody>{owners.map((o) => <tr key={o["owner_id"]} data-owner={o["owner_id"]}><th scope="row" className="mono">{o["owner_id"]}</th><td>{o["owner_name"]}</td><td>{o["team"]}</td><td>{o["role"]}</td>
                <td>{o["active"] ? <Chip kind="ok">active</Chip> : <Chip kind="hatch">inactive since {o["deactivated_at"] ? (o["deactivated_at"] as string).slice(0, 10) : "?"}</Chip>}</td><td className="num mono">{owned.get(o["owner_id"]) ?? 0}</td></tr>)}</tbody>
            </table>
          </Scroll>
        </section>
      )}
    </>
  );
}

export function CatalogView() {
  const [q, setQ] = useParam("q", "");
  const [scope, setScope] = useParam("scope", "all");
  return (
    <>
      <ViewHead mark="Shelfmark 01 · catalog" title="Catalog">
        <p className="lede">Every dataset is registered with an accountable owner and a classification. Search by dataset, field, owner or team; the ownership coverage figure counts only owners who are active.</p>
      </ViewHead>
      <div className="controls">
        <label className="field">Search datasets, fields and owners
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="for example: crm, email, Data Platform, inactive" aria-label="Search datasets, fields and owners" data-testid="search" />
        </label>
        <Choice name="scope" legend="Show" value={scope} onChange={setScope} testid="scope" options={[{ value: "all", label: "All" }, { value: "datasets", label: "Datasets" }, { value: "fields", label: "Fields" }, { value: "owners", label: "Owners" }]} />
      </div>
      <WithData>{(ds) => (<><Ownership ds={ds} /><Results ds={ds} q={q} scope={scope} /><p className="muted">Next: <Link to="scorecard">the scorecard</Link> shows how well these datasets measure, and <Link to="issues">the issue workbench</Link> shows who is working on what.</p></>)}</WithData>
    </>
  );
}
