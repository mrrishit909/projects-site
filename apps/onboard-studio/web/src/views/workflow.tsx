// Workflow canvas (P02-UI-04): the steps of one published workflow version, dependency arrows, and the same
// steps as an ordered list in topological order.
import { Dag } from "../components/dag";
import { Gate, ViewHead, type Ready } from "../components/gate";
import { DataTable } from "../components/table";
import { topologicalOrder } from "../domain/workflow";
import { label, stamp } from "../lib/format";
import { useViewState } from "../state/filters";

export function Workflow() {
  return <Gate>{(s) => <Body s={s} />}</Gate>;
}

function Body({ s }: { s: Ready }) {
  const view = useViewState();
  const pop = s.result.population;
  const versions = [...pop.workflow_versions].sort((a, b) => a.version_number - b.version_number);
  const wv = versions.find((v) => String(v.version_number) === view.version) ?? versions[0];
  if (!wv) return <article><ViewHead eyebrow="Workflow canvas" title="Workflow" /><p>No published workflow version in the accepted population.</p></article>;
  const steps = pop.step_definitions.filter((d) => d.workflow_version_id === wv.workflow_version_id);
  const ids = new Set(steps.map((d) => d.step_definition_id));
  const deps = pop.dependencies.filter((d) => ids.has(d.step_definition_id));
  const seq = new Map(steps.map((d) => [d.step_definition_id, d.sequence]));
  const [order] = topologicalOrder(ids, deps.map((d) => [d.step_definition_id, d.prerequisite_id] as const));
  const byId = new Map(steps.map((d) => [d.step_definition_id, d]));
  const rule = pop.sla_rules.find((r) => r.workflow_version_id === wv.workflow_version_id);
  const counts = new Map(versions.map((v) => [v.workflow_version_id, pop.cases.filter((c) => c.workflow_version_id === v.workflow_version_id).length]));

  return (
    <article>
      <ViewHead eyebrow="Workflow canvas" title="Steps and their dependencies">
        <p className="lede">Each case binds one published workflow version and keeps it. Arrows point from a prerequisite to the step that needs it; a step becomes ready only when every mandatory prerequisite is approved (D-03).</p>
      </ViewHead>

      <fieldset className="version-switch">
        <legend>Workflow version (view setting, kept in the address; it chooses what is drawn)</legend>
        {versions.map((v) => (
          <label key={v.workflow_version_id}>
            <input type="radio" name="wfv" checked={v.workflow_version_id === wv.workflow_version_id} onChange={() => view.set({ v: String(v.version_number) })} />
            v{v.version_number}
          </label>
        ))}
      </fieldset>

      <section className="section" aria-labelledby="sel-h">
        <h2 id="sel-h">Version v{wv.version_number} ({wv.workflow_version_id})</h2>
        <ul className="meta" aria-label="Selected version">
          <li><b>Published</b>{stamp(wv.published_at)}</li>
          <li><b>Steps</b>{steps.length}</li>
          <li><b>Dependencies</b>{deps.length}</li>
          <li><b>SLA rule</b>{rule ? `${rule.sla_rule_id}, ${rule.business_minutes} business minutes` : "none"}</li>
        </ul>
        <p className="small" data-testid="definition-hash"><b>definition_hash</b> <span className="hash">{wv.definition_hash ?? "not recorded"}</span></p>
        <p className="small muted">A published version is immutable (D-02); the hash is the sha256 of its ordered steps and dependencies (D-05). Synthetic data.</p>
        <Dag steps={steps} deps={deps} order={order} title={`Workflow v${wv.version_number}: ${steps.length} steps in dependency order`} />
      </section>

      <section className="section" aria-labelledby="ord-h">
        <h2 id="ord-h">Steps in topological order</h2>
        <p className="small muted">Prerequisites always come before the steps that need them; ties are broken by step id. This list is the accessible equivalent of the drawing.</p>
        <ol className="steps-list" data-testid="steps-order">
          {order.map((id) => {
            const d = byId.get(id)!;
            const pre = deps.filter((x) => x.step_definition_id === id).map((x) => `${label(byId.get(x.prerequisite_id)?.step_name ?? x.prerequisite_id)} (${x.dependency_type})`);
            return (
              <li key={id} data-step={d.step_name}>
                <strong>{label(d.step_name)}</strong>: {d.required ? "required" : "optional"}, role {d.role_key}, sequence {seq.get(id)}. {pre.length ? `After ${pre.join(" and ")}.` : "No prerequisites: ready when the case opens."}
              </li>
            );
          })}
        </ol>
      </section>

      <section className="section" aria-labelledby="all-h">
        <h2 id="all-h">Both versions</h2>
        <DataTable
          caption="Published workflow versions (immutable once published)"
          rows={versions}
          rowKey={(v) => v.workflow_version_id}
          testId="versions-table"
          sortable={false}
          columns={[
            { id: "v", label: "Version", value: (v) => `v${v.version_number}` },
            { id: "id", label: "Id", value: (v) => v.workflow_version_id },
            { id: "pub", label: "Published (UTC)", value: (v) => stamp(v.published_at) },
            { id: "steps", label: "Steps", num: true, value: (v) => pop.step_definitions.filter((d) => d.workflow_version_id === v.workflow_version_id).length },
            { id: "cases", label: "Cases", num: true, value: (v) => counts.get(v.workflow_version_id) ?? 0 },
            { id: "hash", label: "definition_hash", value: (v) => v.definition_hash ?? "not recorded", render: (v) => <span className="hash">{v.definition_hash ?? "not recorded"}</span> },
          ]}
        />
      </section>
    </article>
  );
}
