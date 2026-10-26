// SLA explorer (P02-UI-06): business versus calendar time for the filtered population, attainment with its
// numerator and denominator, open cases beside it, and a CSV of exactly the visible cases.
import { useMemo } from "react";
import { Definition } from "../components/definition";
import { buildCsv, ExportButton } from "../components/export";
import { FilterBar, PauseToggle } from "../components/filters";
import { Gate, ViewHead, type Ready } from "../components/gate";
import { Histogram, makeBins, type Bin } from "../components/histogram";
import { Empty } from "../components/status";
import { DataTable } from "../components/table";
import { computeWithFlags, groupMetrics, inWindow, NO_WINDOW, subsetPopulation, type GroupKey } from "../domain/metrics";
import type { CaseFigures, Metrics } from "../domain/types";
import { hoursOrNa, percent } from "../lib/format";
import { describeFilters, useViewState } from "../state/filters";

export function Sla() {
  return <Gate>{(s) => <Body s={s} />}</Gate>;
}

const NONE: readonly string[] = [];
const NO_CUTOFFS: readonly string[] = [];
const quantile = (sorted: readonly number[], q: number): number | null => (sorted.length === 0 ? null : sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]!);

function Body({ s }: { s: Ready }) {
  const view = useViewState();
  const pop = s.result.population;
  const m = s.snapshot.manifest;
  const cutoffs = m.cutoffs ?? NO_CUTOFFS;
  const override = view.pause === "none" ? NONE : null;
  const orgs = useMemo(() => new Map(pop.organizations.map((o) => [o.organization_id, o])), [pop]);
  const options = useMemo(() => ({
    segments: [...new Set(pop.organizations.map((o) => o.segment))].sort(),
    regions: [...new Set(pop.organizations.map((o) => o.region))].sort(),
    versions: [...pop.workflow_versions].sort((a, b) => a.version_number - b.version_number).map((v) => ({ id: v.workflow_version_id, label: `v${v.version_number} (${v.workflow_version_id})` })),
  }), [pop]);

  const f = view.filters;
  const cases = useMemo(() => {
    if (view.window === null) return [];
    const w = view.window;
    return pop.cases.filter((c) => {
      const o = orgs.get(c.organization_id);
      return inWindow(c.opened_at, w) && (!f.segment || o?.segment === f.segment) && (!f.region || o?.region === f.region) && (!f.wf || c.workflow_version_id === f.wf);
    });
  }, [pop, orgs, view.window, f.segment, f.region, f.wf]);

  const sub = useMemo(() => subsetPopulation(pop, new Set(cases.map((c) => c.case_id))), [pop, cases]);
  const run = useMemo(() => computeWithFlags(sub, override, cutoffs, NO_WINDOW), [sub, override, cutoffs]);
  const groups = useMemo(() => ({
    workflow_version: groupMetrics(sub, "workflow_version", override, cutoffs),
    region: groupMetrics(sub, "region", override, cutoffs),
  }), [sub, override, cutoffs]);

  const mt = run.metrics;
  const open = cases.filter((c) => c.completed_at === null).length;
  const completed = cases.length - open;
  const unevaluated = completed - mt.completed_eligible_cases;
  const nums = (pick: (x: CaseFigures) => string): number[] => run.perCase.map((x) => Number(pick(x))).sort((a, b) => a - b);
  const cal = nums((x) => x.calendar_hours), bus = nums((x) => x.business_hours), act = nums((x) => x.active_hours), paused = nums((x) => x.paused_hours);
  const limits = new Set(run.perCase.map((x) => x.sla_minutes));
  const limitH = limits.size === 1 ? [...limits][0]! / 60 : null;
  const policyText = view.pause === "none" ? "none (view setting)" : `configured, per SLA rule (${[...new Set(pop.sla_rules.map((r) => r.pause_policy.join(" + ") || "none"))].join("; ")})`;
  const calendarIds = [...new Set(pop.sla_rules.map((r) => r.calendar_id))].join(", ") || "none";

  const csv = (): string => {
    const figs = new Map(run.perCase.map((x) => [x.case_id, x]));
    const head = [
      "Onboard Studio SLA export. Synthetic data.",
      `contract_version: ${m.contract_version}`,
      `dataset_version: ${m.dataset_version}`,
      `dataset_hash: ${m.dataset_hash}`,
      `generated_at: ${m.generated_at}`,
      `calendar_id: ${calendarIds}`,
      `pause_policy: ${policyText}`,
      `filters: ${describeFilters(f)}`,
      "window: opened_at, UTC, half-open [from, to)",
      `row_count: ${cases.length}`,
      "hours: exact decimals, 4 places; open cases have no figures; within_sla is blank for open cases",
    ];
    const rows = cases.map((c) => {
      const o = orgs.get(c.organization_id), x = figs.get(c.case_id);
      return [c.case_id, c.organization_id, o?.organization_name ?? "", o?.segment ?? "", o?.region ?? "", c.workflow_version_id, c.completed_at === null ? "open" : "completed",
        new Date(c.opened_at).toISOString(), c.completed_at === null ? "" : new Date(c.completed_at).toISOString(),
        x?.calendar_hours ?? "", x?.business_hours ?? "", x?.paused_hours ?? "", x?.paused_business_overlap_hours ?? "", x?.active_hours ?? "", x ? String(x.sla_minutes) : "", x ? String(x.within_sla) : ""];
    });
    return buildCsv(head, ["case_id", "organization_id", "organization_name", "segment", "region", "workflow_version_id", "status", "opened_at", "completed_at", "calendar_hours", "business_hours", "paused_hours", "paused_business_overlap_hours", "active_hours", "sla_business_minutes", "within_sla"], rows);
  };

  const binRows = (bins: readonly Bin[], n: number) => bins.map((b) => ({ key: String(b.lo), range: `${b.lo} to under ${b.hi}`, count: b.count, share: percent(b.count, n) }));
  const binTable = (title: string, bins: readonly Bin[], n: number) => (
    <DataTable
      caption={`${title}: cases per bin (hours)`}
      rows={binRows(bins, n)}
      rowKey={(r) => r.key}
      sortable={false}
      columns={[{ id: "range", label: "Hours", value: (r) => r.range }, { id: "count", label: "Cases", num: true, value: (r) => r.count }, { id: "share", label: "Share", num: true, value: (r) => r.share }]}
    />
  );
  const stat = (name: string, mean: string | null, xs: number[]) => ({ name, mean: hoursOrNa(mean), median: quantile(xs, 0.5), p90: quantile(xs, 0.9), max: xs.length ? xs[xs.length - 1]! : null });
  const summary = [stat("Calendar hours", mt.calendar_cycle_time_hours, cal), stat("Business hours", mt.business_cycle_time_hours, bus), stat("Paused (calendar)", mt.paused_time_hours, paused), stat("Active elapsed", mt.active_elapsed_hours, act)];

  const groupRows = (by: GroupKey, g: Record<string, Metrics>) => Object.entries(g).map(([k, v]) => ({ key: `${by}-${k}`, group: k, ...v }));
  const groupTable = (title: string, by: GroupKey, g: Record<string, Metrics>) => (
    <DataTable
      caption={title}
      rows={groupRows(by, g)}
      rowKey={(r) => r.key}
      testId={`group-${by}`}
      columns={[
        { id: "group", label: by === "region" ? "Region" : "Workflow version", value: (r) => r.group },
        { id: "den", label: "Completed", num: true, value: (r) => r.completed_eligible_cases },
        { id: "num", label: "Within SLA", num: true, value: (r) => r.within_sla_cases },
        { id: "att", label: "Attainment", num: true, value: (r) => (r.completed_eligible_cases === 0 ? null : r.within_sla_cases / r.completed_eligible_cases), render: (r) => percent(r.within_sla_cases, r.completed_eligible_cases) },
        { id: "cal", label: "Calendar h (mean)", num: true, value: (r) => (r.calendar_cycle_time_hours === null ? null : Number(r.calendar_cycle_time_hours)), render: (r) => hoursOrNa(r.calendar_cycle_time_hours) },
        { id: "bus", label: "Business h (mean)", num: true, value: (r) => (r.business_cycle_time_hours === null ? null : Number(r.business_cycle_time_hours)), render: (r) => hoursOrNa(r.business_cycle_time_hours) },
        { id: "act", label: "Active h (mean)", num: true, value: (r) => (r.active_elapsed_hours === null ? null : Number(r.active_elapsed_hours)), render: (r) => hoursOrNa(r.active_elapsed_hours) },
      ]}
    />
  );

  return (
    <article>
      <ViewHead eyebrow="SLA explorer" title="Business time against calendar time">
        <p className="lede">Calendar time counts every hour between opening and completion. Business time counts only working hours, and active elapsed time also takes out waiting that the SLA rule lets the team pause.</p>
      </ViewHead>
      <FilterBar view={view} options={options} shown={cases.length} total={pop.cases.length} />
      <PauseToggle view={view} policy="Configured uses each SLA rule's pause-eligible waiting reasons; None counts every waiting hour as active time." />

      {cases.length === 0 ? (
        <Empty title="No cases match these filters">
          <p>The filtered population is empty, so no figure is shown and none is substituted.</p>
          <p><button type="button" className="btn" onClick={view.clear}>Clear filters</button></p>
        </Empty>
      ) : (
        <>
          <section className="section" aria-labelledby="att-h">
            <h2 id="att-h">SLA attainment</h2>
            <dl className="figures">
              <div className="figure figure--sla" data-figure="attainment">
                <dt>Attainment (completed cases)</dt>
                <dd data-testid="sla-rate">{percent(mt.within_sla_cases, mt.completed_eligible_cases)}
                  <small><span data-testid="sla-numerator">{mt.within_sla_cases}</span> within SLA of <span data-testid="sla-denominator">{mt.completed_eligible_cases}</span> completed cases{mt.sla_attainment ? `; exact rate ${mt.sla_attainment}` : "; no completed case, so no rate"}</small></dd>
              </div>
              <div className="figure" data-figure="open"><dt>Open cases (beside, not inside)</dt><dd data-testid="open-cases">{open}<small>opened in the window, not completed; excluded from attainment</small></dd></div>
              <div className="figure" data-figure="population"><dt>Population</dt><dd>{cases.length}<small>{completed} completed, {open} open{unevaluated > 0 ? `, ${unevaluated} completed without an SLA rule or calendar` : ""}</small></dd></div>
              <div className="figure" data-figure="active-mean"><dt>Active elapsed (mean)</dt><dd>{hoursOrNa(mt.active_elapsed_hours)}<small>hours, completed cases</small></dd></div>
            </dl>
            <p className="small">SLA test: active elapsed minutes at most the rule's business minutes{limitH !== null ? ` (${limitH * 60} here)` : ""}. Pause policy: <strong>{policyText}</strong>. Calendar: {calendarIds}. Hours are exact decimals, 4 places. {s.result.rejected.length} records rejected at ingest are in no population.</p>
          </section>

          <section className="section" aria-labelledby="dist-h">
            <h2 id="dist-h">Distributions, completed cases</h2>
            <p className="small muted">Synthetic data. Bars count completed cases per bin of hours; each chart has its table below it. Chart bins are for display; the means are exact.</p>
            <div className="hists">
              <Histogram title="Calendar hours" unit="hours" bins={makeBins(cal)} />
              <Histogram title="Business hours" unit="hours" bins={makeBins(bus)} />
              <Histogram title="Active elapsed hours" unit="hours" bins={makeBins(act)} limit={limitH} limitLabel={`SLA ${limitH ?? ""} h`} />
            </div>
            <div className="two-col" style={{ marginTop: "1rem" }}>
              {binTable("Calendar hours", makeBins(cal), cal.length)}
              {binTable("Business hours", makeBins(bus), bus.length)}
              {binTable("Active elapsed hours", makeBins(act), act.length)}
            </div>
            <div style={{ marginTop: "1rem" }}>
              <DataTable
                caption="Summary of the filtered population (mean is exact; median, 90th percentile and maximum are display values from the per-case figures)"
                rows={summary}
                rowKey={(r) => r.name}
                sortable={false}
                columns={[
                  { id: "n", label: "Measure", value: (r) => r.name },
                  { id: "mean", label: "Mean (h)", num: true, value: (r) => r.mean },
                  { id: "med", label: "Median (h)", num: true, value: (r) => (r.median === null ? "n/a" : r.median.toFixed(4)) },
                  { id: "p90", label: "90th pct (h)", num: true, value: (r) => (r.p90 === null ? "n/a" : r.p90.toFixed(4)) },
                  { id: "max", label: "Max (h)", num: true, value: (r) => (r.max === null ? "n/a" : r.max.toFixed(4)) },
                ]}
              />
            </div>
          </section>

          <section className="section" aria-labelledby="grp-h">
            <h2 id="grp-h">By workflow version and by region</h2>
            <div className="stack">
              {groupTable("By workflow version (filtered population)", "workflow_version", groups.workflow_version)}
              {groupTable("By region (filtered population)", "region", groups.region)}
            </div>
          </section>

          <section className="section" aria-labelledby="exp-h">
            <h2 id="exp-h">Export</h2>
            <ExportButton filename={`onboard-studio-sla-${m.dataset_version}.csv`} build={csv} rowCount={cases.length} />
          </section>
        </>
      )}
      <Definition />
    </article>
  );
}
