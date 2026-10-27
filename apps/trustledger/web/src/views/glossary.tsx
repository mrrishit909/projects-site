import { Link } from "../components/link";
import { Chip, Choice, Def, Fig, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { cmp, type Row } from "../domain/models";
import { dayTime } from "../lib/format";
import { useParam } from "../router";

const ITEMS = ["definition", "grain", "source_fields", "owner", "refresh"] as const;
const WORDS: Record<string, string> = { definition: "Definition", grain: "Grain", source_fields: "Source fields", owner: "Owner", refresh: "Refresh" };

const blankText = (v: unknown): boolean => v === null || v === undefined || (typeof v === "string" && v.trim() === "") || (Array.isArray(v) && v.length === 0);
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

function Versions({ ds, metricId }: { ds: Dataset; metricId: string }) {
  const versions = ds.raw.metric_versions.filter((v) => v["metric_id"] === metricId).sort((a, b) => a["version_number"] - b["version_number"]);
  const changeOf = (id: string): Row | undefined => ds.raw.definition_changes.find((c) => c["metric_version_id"] === id);
  const eff = (ds.now.definitions["effective_at_as_of"] as Record<string, string | null>)[metricId];
  const probeAt = ds.now.definitions["probe_at"] as string | null;
  const probeEff = (ds.now.definitions["effective_at_probe"] as Record<string, string | null>)[metricId];
  const gaps = (ds.now.metrics["definition_coverage"]["incomplete"] as Record<string, string[]>)[metricId];
  const ownerName = (id: string | null): string => (id ? `${ds.byId.owners.get(id)?.["owner_name"] ?? "(unknown owner)"} · ${id}` : "none");
  return (
    <div data-testid="versions">
      <div className="collation" role="group" aria-label={`Versions of ${metricId}, side by side`}>
        {versions.map((v, i) => {
          const prev = i > 0 ? versions[i - 1]! : null;
          const ch = changeOf(v["metric_version_id"]);
          const cell = (item: (typeof ITEMS)[number], text: React.ReactNode, raw: unknown) => {
            const field = item === "owner" ? "owner_id" : item;
            const changed = prev !== null && !same(raw, prev[field]);
            const blank = blankText(raw);
            return <dd className={blank ? "gap" : changed ? "changed" : ""} data-item={item} data-state={blank ? "blank" : changed ? "changed" : "same"}>{blank ? "(blank)" : text}{blank && <> <Chip kind="hatch">blank</Chip></>}{!blank && changed && <> <Chip kind="ok">changed from v{prev!["version_number"]}</Chip></>}</dd>;
          };
          return (
            <article className="version" key={v["metric_version_id"]} data-version={v["metric_version_id"]}>
              <h3><span>Version {v["version_number"]}</span><Chip kind={v["status"] === "published" ? "ok" : v["status"] === "draft" ? "note" : "hatch"}>{v["status"]}</Chip></h3>
              <p className="mono muted">{v["metric_version_id"]}</p>
              <dl>
                <dt>{WORDS["definition"]}</dt>{cell("definition", v["definition"], v["definition"])}
                <dt>{WORDS["grain"]}</dt>{cell("grain", v["grain"], v["grain"])}
                <dt>{WORDS["source_fields"]}</dt>{cell("source_fields", <span className="mono">{(v["source_fields"] ?? []).join(", ")}</span>, v["source_fields"])}
                <dt>{WORDS["owner"]}</dt>{cell("owner", ownerName(v["owner_id"]), v["owner_id"])}
                <dt>{WORDS["refresh"]}</dt>{cell("refresh", v["refresh"], v["refresh"])}
                <dt>Valid from</dt><dd className="mono">{dayTime(v["valid_from"])}</dd>
                <dt>Change record</dt><dd>{ch ? <>{ch["reason"]}. Approved by {ownerName(ch["approved_by"])} at <span className="mono">{dayTime(ch["changed_at"])}</span>.</> : prev ? <Chip kind="hatch">no change record</Chip> : "first version"}</dd>
              </dl>
            </article>
          );
        })}
      </div>
      <ul>
        <li data-testid="effective">In force at the as-of: <span className="mono">{eff ?? "none"}</span>{probeAt && <>; in force at the probe <span className="mono">{dayTime(probeAt)}</span>: <span className="mono">{probeEff ?? "none"}</span></>}. A published definition is never rewritten: a change adds a version and the older one stays readable.</li>
        <li data-testid="checklist-gaps">{gaps ? <>Checklist {ds.now.metrics["definition_coverage"]["checklist_version"]} gaps in the effective version: <strong>{gaps.map((g) => WORDS[g] ?? g).join(", ")}</strong>. It does not count as complete.</> : eff && versions.find((v) => v["metric_version_id"] === eff)?.["status"] === "published" ? <>The effective version passes checklist {ds.now.metrics["definition_coverage"]["checklist_version"]}.</> : "The effective version is not published, so it is outside the coverage figure."}</li>
      </ul>
    </div>
  );
}

function Glossary({ ds }: { ds: Dataset }) {
  const counts = ds.now.definitions["version_counts"] as Record<string, number>;
  const cov = ds.now.metrics["definition_coverage"];
  const ids = Object.keys(counts).sort(cmp);
  const redefined = ids.filter((m) => counts[m]! > 1);
  const [show, setShow] = useParam("show", "redefined");
  const list = show === "all" ? ids : redefined;
  const [m, setM] = useParam("m", "");
  const metric = m && ids.includes(m) ? m : list[0] ?? ids[0]!;
  const name = (id: string): string => ds.raw.metric_versions.find((v) => v["metric_id"] === id)!["metric_name"];
  const incomplete = Object.entries(cov["incomplete"] as Record<string, string[]>);
  return (
    <>
      <section className="block" data-testid="coverage" aria-labelledby="cov">
        <h2 id="cov">Definition coverage</h2>
        <div className="pair-fig">
          <div><span className="big"><Fig k="definition-coverage">{cov.value}</Fig></span><span className="cap">{cov.complete_metrics} of {cov.published_metrics} published metrics pass <Def term={`checklist ${cov.checklist_version}`}>The contract checklist: definition, grain, source fields, owner, refresh. Text must be non-blank, the source-field list non-empty, the owner a registered owner. Only published metrics count; drafts and superseded versions do not.</Def></span></div>
          <div><span className="big"><Fig k="redefined">{redefined.length}</Fig></span><span className="cap">of {ids.length} metrics have more than one version ({ds.raw.metric_versions.length} versions, {ds.raw.definition_changes.length} change records)</span></div>
        </div>
        {incomplete.length > 0 && <p data-testid="incomplete">Incomplete: {incomplete.map(([id, g], i) => <span key={id}>{i ? "; " : ""}<Link to={`glossary?m=${id}&show=all`}>{name(id)}</Link> (<span className="mono">{g.join(", ")}</span>)</span>)}.</p>}
      </section>
      <div className="controls">
        <Choice name="show" legend="Metrics" value={show} onChange={setShow} testid="show" options={[{ value: "redefined", label: `Redefined (${redefined.length})` }, { value: "all", label: `All (${ids.length})` }]} />
      </div>
      <ul className="metric-list" data-testid="metric-list" aria-label="Metrics">
        {list.map((id) => <li key={id}><a href={`?m=${id}${show === "all" ? "&show=all" : ""}`} aria-current={id === metric ? "true" : undefined} onClick={(e) => { e.preventDefault(); setM(id); }}>{name(id)}</a></li>)}
      </ul>
      <section className="block" aria-labelledby="mv">
        <h2 id="mv">{name(metric)} <span className="mono muted">{metric}</span></h2>
        <Versions ds={ds} metricId={metric} />
      </section>
    </>
  );
}

export function GlossaryView() {
  return (
    <>
      <ViewHead mark="Shelfmark 02 · glossary" title="Glossary">
        <p className="lede">A metric means what its definition says on the date you read it. Each version is shown beside the one before it, with what changed, who approved the change and when it took effect.</p>
        <p className="muted">The published data holds successive versions of each definition, not rival definitions in force at the same time; the side-by-side layout is for comparing what changed. A change never rewrites a published version.</p>
      </ViewHead>
      <WithData>{(ds) => <Glossary ds={ds} />}</WithData>
    </>
  );
}
