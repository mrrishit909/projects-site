// Case timeline (P02-UI-03): one case on one business-hours axis, its figures, and a table of every drawn element.
import { useMemo } from "react";
import { Definition } from "../components/definition";
import { Gate, ViewHead, type Ready } from "../components/gate";
import { PauseToggle } from "../components/filters";
import { DataTable } from "../components/table";
import { buildTimeline, Timeline, type TimelineRow } from "../components/timeline";
import { buildCalendars } from "../domain/metrics";
import { runOnPopulation } from "../domain/pipeline";
import { clip, label, stamp } from "../lib/format";
import { useViewState } from "../state/filters";
import { Empty } from "../components/status";

export function Cases() {
  return <Gate>{(s) => <CasesBody s={s} />}</Gate>;
}

function CasesBody({ s }: { s: Ready }) {
  const view = useViewState();
  const pop = s.result.population;
  const cutoffs = s.snapshot.manifest.cutoffs ?? [];
  const calendars = useMemo(() => buildCalendars(pop), [pop]);
  const shown = useMemo(() => (view.pause === "none" ? runOnPopulation(s.result.ingest, pop, [], cutoffs) : s.result), [view.pause, s.result, pop, cutoffs]);
  const orgs = useMemo(() => new Map(pop.organizations.map((o) => [o.organization_id, o])), [pop]);
  const picked = pop.cases.find((c) => c.case_id === view.caseId) ?? null;
  const c = picked ?? (view.caseId ? null : pop.cases[0] ?? null);
  const rejected = view.caseId ? s.result.rejected.filter((r) => r.entity === "cases" && r.id === view.caseId) : [];

  const body = (() => {
    if (!c) {
      return (
        <Empty title={view.caseId ? `Case ${view.caseId} is not in the accepted population` : "No accepted cases"}>
          {rejected.length > 0 ? <p>Ingest rejected it with reason {rejected.map((r) => r.reason_code).join(", ")}; rejected records are kept raw and never enter any figure.</p> : <p>Pick a case from the list above.</p>}
        </Empty>
      );
    }
    const rule = pop.sla_rules.find((r) => r.workflow_version_id === c.workflow_version_id);
    const wv = pop.workflow_versions.find((v) => v.workflow_version_id === c.workflow_version_id);
    const org = orgs.get(c.organization_id);
    const defs = new Map(pop.step_definitions.map((d) => [d.step_definition_id, d]));
    const sis = pop.step_instances.filter((x) => x.case_id === c.case_id);
    const siById = new Map(sis.map((x) => [x.step_instance_id, x]));
    const policyList = view.pause === "none" ? [] : rule?.pause_policy ?? [];
    const model = buildTimeline({
      caseRow: c,
      working: rule ? calendars.get(rule.calendar_id) ?? [] : [],
      assignments: pop.assignments.filter((a) => siById.has(a.step_instance_id)).map((a) => {
        const d = defs.get(siById.get(a.step_instance_id)!.step_definition_id);
        return { a, step: d?.step_name ?? "unknown step", role: d?.role_key ?? "unknown" };
      }),
      waits: pop.waiting_intervals.filter((w) => w.case_id === c.case_id),
      policy: new Set(policyList),
      docs: pop.document_versions.filter((d) => d.case_id === c.case_id),
      steps: sis.map((si) => ({ si, name: defs.get(si.step_definition_id)?.step_name ?? si.step_definition_id, sequence: defs.get(si.step_definition_id)?.sequence ?? 0 })),
    });
    const fig = shown.perCase.find((f) => f.case_id === c.case_id);
    const flags = shown.flags.filter((f) => f.case_id === c.case_id);
    const policyText = view.pause === "none" ? "none (view setting: no reason pauses the clock)" : `configured: ${policyList.length ? policyList.join(", ") : "none"}`;
    const na = c.completed_at === null ? "n/a, case open" : "n/a";
    const minutes = fig ? (Number(fig.active_hours) * 60).toFixed(2) : null;
    return (
      <>
        <ul className="meta" aria-label="Case facts">
          <li><b>Case</b><span className="mono">{c.case_id}</span></li>
          <li><b>Organization</b><span className="ellipsis" title={org?.organization_name ?? c.organization_id}>{org?.organization_name ?? c.organization_id}</span></li>
          <li><b>Segment</b>{org?.segment ?? "unknown"}</li>
          <li><b>Region</b>{org?.region ?? "unknown"}</li>
          <li><b>Workflow</b>v{wv?.version_number ?? "?"} ({c.workflow_version_id})</li>
          <li><b>Status</b>{c.completed_at === null ? "open" : "completed"}</li>
          <li><b>Opened</b>{stamp(c.opened_at)}</li>
          <li><b>Completed</b>{stamp(c.completed_at)}</li>
        </ul>

        <section className="section" aria-labelledby="fig-title">
          <h2 id="fig-title">Figures</h2>
          <dl className="figures" data-testid="figures">
            <div className="figure" data-figure="calendar"><dt>Calendar hours</dt><dd>{fig?.calendar_hours ?? na}<small>completed − opened</small></dd></div>
            <div className="figure" data-figure="business"><dt>Business hours</dt><dd>{fig?.business_hours ?? na}<small>inside working intervals</small></dd></div>
            <div className="figure" data-figure="paused"><dt>Paused (calendar)</dt><dd>{fig?.paused_hours ?? na}<small>pause-eligible waiting, merged</small></dd></div>
            <div className="figure" data-figure="overlap"><dt>Paused business overlap</dt><dd>{fig?.paused_business_overlap_hours ?? na}<small>paused time inside working hours</small></dd></div>
            <div className="figure" data-figure="active"><dt>Active elapsed</dt><dd>{fig?.active_hours ?? na}<small>business − paused overlap</small></dd></div>
            <div className="figure figure--sla" data-figure="sla"><dt>SLA result</dt>
              <dd>{fig ? (fig.within_sla ? "SLA met" : "SLA not met") : "Not evaluated"}
                <small>{fig ? `Active ${minutes} min against ${fig.sla_minutes} business minutes` : "an open case is shown beside attainment, never inside it"}</small></dd>
            </div>
          </dl>
          <p className="small" data-testid="sla-rule">
            SLA rule {rule?.sla_rule_id ?? "none"}: {rule?.business_minutes ?? "n/a"} business minutes on calendar {rule?.calendar_id ?? "n/a"}. Pause policy shown: <strong>{policyText}</strong>. Hours are exact decimals from the domain, 4 places.
          </p>
          {flags.length > 0 && (
            <div className="notice" role="note"><p>{flags.length} pause-eligible waiting {flags.length === 1 ? "interval lies" : "intervals lie"} wholly outside working time ({flags.map((f) => f.waiting_interval_id).join(", ")}): {flags.length === 1 ? "it contributes" : "they contribute"} 0 business hours (flag {flags[0]!.flag}).</p></div>
          )}
        </section>

        <section className="section" aria-labelledby="tl-h">
          <h2 id="tl-h">Timeline</h2>
          <p className="small muted">One business-hours axis. Shaded columns are working intervals at scale; {model.gaps} non-working {model.gaps === 1 ? "gap is" : "gaps are"} compressed to narrow hatched columns marked ≈, so their length is not to scale. Synthetic data.</p>
          <Timeline model={model} />
        </section>

        <section className="section" aria-labelledby="tl-table-h">
          <h2 id="tl-table-h">Every drawn element, as a table</h2>
          <DataTable<TimelineRow>
            caption={`Elements of ${c.case_id}, ${model.rows.length} rows, synthetic data`}
            rows={model.rows}
            rowKey={(r) => r.key}
            testId="timeline-table"
            columns={[
              { id: "element", label: "Element", value: (r) => r.element },
              { id: "subject", label: "What", value: (r) => r.subject, truncate: true },
              { id: "lane", label: "Lane", value: (r) => r.lane, truncate: true },
              { id: "starts", label: "Starts (UTC)", value: (r) => r.starts, render: (r) => stamp(r.starts) },
              { id: "ends", label: "Ends (UTC)", value: (r) => r.ends, render: (r) => (r.ends === null ? "n/a" : stamp(r.ends)) },
              { id: "detail", label: "Detail", value: (r) => r.detail },
            ]}
          />
        </section>
      </>
    );
  })();

  return (
    <article>
      <ViewHead eyebrow="Case timeline" title="One case, one business-hours axis">
        <p className="lede">Calendar gaps are compressed so what remains is the time that counts: who held the case, where it waited and why, and which documents moved it.</p>
      </ViewHead>
      <div className="field picker">
        <label htmlFor="case-picker">Case (view setting: it only chooses what is shown, nothing is edited)</label>
        <select id="case-picker" value={c?.case_id ?? ""} onChange={(e) => view.set({ case: e.target.value })}>
          {c === null && <option value="">Choose a case</option>}
          {pop.cases.map((x) => (
            <option key={x.case_id} value={x.case_id}>{`${x.case_id} · ${clip(orgs.get(x.organization_id)?.organization_name ?? x.organization_id, 28)} · ${x.completed_at === null ? "open" : "completed"}`}</option>
          ))}
        </select>
      </div>
      <PauseToggle view={view} policy="Configured uses the SLA rule's pause-eligible reasons; None treats every waiting interval as active time." />
      {body}
      <Definition />
      <p className="small muted">{label("accepted_cases")}: {pop.cases.length}; rejected at ingest: {s.result.rejected.length} records. Dataset {s.snapshot.manifest.dataset_version}.</p>
    </article>
  );
}
