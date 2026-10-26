// Work queue (P02-UI-02): the open step instances of open cases. A read view: nothing here changes the data.
import { useMemo } from "react";
import { Gate, ViewHead, type Ready } from "../components/gate";
import { Empty } from "../components/status";
import { DataTable } from "../components/table";
import type { Interval } from "../domain/calendar";
import { buildCalendars } from "../domain/metrics";
import { unapprovedPrerequisites } from "../domain/workflow";
import { label, stamp } from "../lib/format";
import { Link } from "../components/link";
import { hrefFor } from "../routes";

/** The instant at which `minutes` of working time have passed since `from` (null when the calendar runs out). */
export function businessDeadline(from: number, minutes: number, working: readonly Interval[]): number | null {
  let left = minutes * 60_000;
  for (const [s, e] of working) {
    if (e <= from) continue;
    const a = Math.max(s, from);
    const room = e - a;
    if (left <= room) return a + left;
    left -= room;
  }
  return null;
}

interface Row {
  key: string; caseId: string; step: string; role: string; owner: string; state: string; readiness: string;
  readyAt: number | null; deadline: number | null; deadlineNote: string; reason: string;
}

export function Queue() {
  return <Gate>{(s) => <Body s={s} />}</Gate>;
}

function Body({ s }: { s: Ready }) {
  const pop = s.result.population;
  const rows = useMemo<Row[]>(() => {
    const calendars = buildCalendars(pop);
    const defs = new Map(pop.step_definitions.map((d) => [d.step_definition_id, d]));
    const openCases = pop.cases.filter((c) => c.completed_at === null);
    const out: Row[] = [];
    for (const c of openCases) {
      const rule = pop.sla_rules.find((r) => r.workflow_version_id === c.workflow_version_id);
      const dl = rule ? businessDeadline(c.opened_at, rule.business_minutes, calendars.get(rule.calendar_id) ?? []) : null;
      const sis = pop.step_instances.filter((x) => x.case_id === c.case_id);
      const status = new Map(sis.map((x) => [x.step_definition_id, x.status]));
      const deps = pop.dependencies;
      const openWait = pop.waiting_intervals.find((w) => w.case_id === c.case_id && w.ends_at === null);
      for (const si of sis) {
        if (si.status === "approved") continue;
        const d = defs.get(si.step_definition_id);
        const mine = pop.assignments.filter((a) => a.step_instance_id === si.step_instance_id);
        const current = mine.find((a) => a.ended_at === null) ?? [...mine].sort((a, b) => b.assigned_at - a.assigned_at)[0];
        const blockers = si.status === "blocked" ? unapprovedPrerequisites(si.step_definition_id, deps, status).map((p) => label(defs.get(p)?.step_name ?? p)) : [];
        const reason = si.status === "blocked" ? `Waiting for ${blockers.join(" and ") || "a prerequisite"} to be approved`
          : si.status === "ready" ? "Ready and not started"
          : si.status === "in_progress" ? "Being worked on"
          : si.status === "in_review" ? "Waiting for a reviewer's decision"
          : `State ${si.status}`;
        out.push({
          key: si.step_instance_id, caseId: c.case_id, step: d?.step_name ?? si.step_definition_id, role: d?.role_key ?? "unknown",
          owner: current ? current.assignee_id : "unassigned", state: si.status,
          readiness: si.status === "blocked" ? "Not ready (blocked)" : "Ready since opened or unlocked",
          readyAt: si.ready_at, deadline: dl, deadlineNote: rule ? `${rule.business_minutes} business minutes from case opening` : "no SLA rule",
          reason: openWait ? `${reason}; case waiting on ${label(openWait.reason_code)}` : reason,
        });
      }
    }
    return out;
  }, [pop]);

  const openCount = pop.cases.filter((c) => c.completed_at === null).length;
  return (
    <article>
      <ViewHead eyebrow="Work queue" title="Open step instances">
        <p className="lede">Every step of an open case that is not yet approved, with its current owner, whether it can start, and the SLA deadline of its case. This is a read view: nothing here assigns, starts or approves anything.</p>
      </ViewHead>
      <p className="small" data-testid="queue-count">{rows.length} open step instances across {openCount} open cases, from the snapshot generated {s.snapshot.manifest.generated_at}. The queue is as of that snapshot, not live.</p>
      <p className="small muted">Deadline: the instant at which the rule's business minutes have elapsed on the working calendar since the case opened. It is the earliest deadline, before any allowance for pause-eligible waiting.</p>
      {rows.length === 0 ? (
        <Empty title="No open step instances">
          <p>This snapshot has no open case, so the queue is empty. Completed cases appear on the <Link to="cases">case timeline</Link>.</p>
        </Empty>
      ) : (
        <DataTable<Row>
          caption="Open step instances (synthetic data); sort with the column buttons"
          rows={rows}
          rowKey={(r) => r.key}
          testId="queue-table"
          initialSort={{ id: "deadline", dir: "asc" }}
          columns={[
            { id: "case", label: "Case", value: (r) => r.caseId, render: (r) => <a href={`${hrefFor("cases")}?case=${encodeURIComponent(r.caseId)}`}>{r.caseId}</a> },
            { id: "step", label: "Step", value: (r) => label(r.step) },
            { id: "role", label: "Role", value: (r) => r.role },
            { id: "owner", label: "Owner", value: (r) => r.owner },
            { id: "state", label: "State", value: (r) => r.state },
            { id: "ready", label: "Readiness", value: (r) => r.readiness, render: (r) => (r.readyAt === null ? r.readiness : `Ready since ${stamp(r.readyAt)}`) },
            { id: "deadline", label: "SLA deadline (UTC)", value: (r) => r.deadline, render: (r) => (r.deadline === null ? "n/a" : stamp(r.deadline)) },
            { id: "reason", label: "Reason", value: (r) => r.reason, truncate: true },
          ]}
        />
      )}
    </article>
  );
}
