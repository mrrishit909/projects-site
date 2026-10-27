import { Chip, Choice, Def, Fig, Pager, Scroll, SimNote, usePage, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { IssueView } from "../domain/issues";
import { verificationProblem } from "../domain/issues";
import { measureRule } from "../domain/measure";
import { cmp } from "../domain/models";
import { h4 } from "../domain/num";
import { isoZ } from "../domain/time";
import { AGE_BUCKETS, ageBucket, teamRows, teamVersusRest } from "../lib/derive";
import { dayTime } from "../lib/format";
import { useParam } from "../router";
import { addSimIssue, simClassOf, useSimIssues, type SimIssue } from "../state/sim";

const sevChip = (s: string) => (s === "critical" ? <Chip kind="crit">critical</Chip> : <span>{s}</span>);
const clsChip = (c: string) => (c === "resolved" ? <Chip kind="ok">resolved</Chip> : c === "claimed" ? <Chip kind="hatch">claimed</Chip> : <Chip kind="note">open</Chip>);
const days = (h: IssueView["hours"]): string => String(Number(h.n / (h.d * 24n)));

/** A rerun here re-measures the rule over the published rows at the as-of; it is not stored. Seeded issues carry no record ids, so the whole rule is rerun (D-08).
 * Like C10 it also reruns a DISABLED rule (disabling is not repair, and only a passing rerun resolves; D-10 R7-02): the rule is measured from its own definition. */
function simulateRerun(ds: Dataset, v: IssueView): Omit<SimIssue, "n" | "issue_id" | "action"> {
  const disabled = v.rule.rule_id in (ds.now.rules["disabled"] as Record<string, unknown>);
  const why = disabled ? " The rule is disabled; disabling is not repair, so only a passing rerun would resolve it." : "";
  if (v.cls === "resolved") return { outcome: "resolved", code: null, note: "Already resolved: a verifying rerun is on record. Nothing changes." };
  if (v.rule.version_number !== v.base.rule_version) return { outcome: "claimed", code: "RULE_VERSION_DIFFERS", note: `The issue was opened by rule v${v.base.rule_version}; the rule is now v${v.rule.version_number}. A rerun must be the same rule version to verify, so it is not verified.${why}` };
  if (v.rule.rule_type === "validity" && !v.rule.definition["pattern"]) return { outcome: "claimed", code: "RULE_NOT_MEASURABLE", note: `The rule has no pattern, so there is nothing to rerun and the issue is not verified.${why}` };
  const m = disabled ? measureRule(v.rule, ds.result.population, ds.asOf) : ds.now.measures.find((x) => x.rule.rule_id === v.rule.rule_id);
  if (!m) return { outcome: "claimed", code: "NO_RECORDS_TO_CHECK", note: "The rule is not measured at the as-of, so there is nothing to verify." };
  if (m.eligible === 0) return { outcome: "claimed", code: "NO_RECORDS_TO_CHECK", note: `The rule has no eligible records.${why}` };
  if (m.failures > 0) return { outcome: "claimed", code: "RERUN_STILL_FAILING", note: `The rerun still fails on ${m.failures} of ${m.eligible} eligible records, so the issue is not verified and stays claimed.${why}` };
  return { outcome: "resolved", code: null, note: `The rerun of v${v.rule.version_number} fails on 0 of ${m.eligible} records: a successful rerun of the same rule version would verify the issue and it would count as resolved.${why}` };
}

function Summary({ ds, views, log }: { ds: Dataset; views: IssueView[]; log: readonly SimIssue[] }) {
  const r = ds.now.metrics["resolution_time"];
  const sim = (c: string): number => views.filter((v) => simClassOf(log, v.issue.issue_id, v.cls) === c).length;
  const claimed = views.filter((v) => v.cls === "claimed");
  const failedRerun = new Map<string, number>();
  const runs = new Map(ds.result.population.rule_runs.map((x) => [x.rule_run_id, x]));
  for (const v of claimed) if (v.issue.verification_run_id) { const p = verificationProblem(v.issue, v.base, runs.get(v.issue.verification_run_id)); failedRerun.set(p ?? "VERIFIED", (failedRerun.get(p ?? "VERIFIED") ?? 0) + 1); }
  const withRerun = [...failedRerun.values()].reduce((a, b) => a + b, 0);
  const changed = log.some((e) => e.outcome !== "refused");
  const critOpen = views.filter((v) => v.rule.severity === "critical" && v.cls !== "resolved").length;
  return (
    <section className="block" aria-labelledby="cvr" data-testid="claimed-vs-resolved">
      <h2 id="cvr">Claimed against resolved</h2>
      <p>An issue is <strong>resolved</strong> only after a successful rerun of the same rule version confirms it. Closing it without that rerun makes it <strong>claimed</strong>: listed separately and never counted as resolved.</p>
      <div className="tiles">
        <div className="tile"><b data-figure="resolved">{r["resolved_count"]}</b><span>resolved (a verifying rerun on record)</span></div>
        <div className="tile"><b data-figure="claimed">{r["claimed_count"]}</b><span>claimed (closed without verification)</span></div>
        <div className="tile"><b data-figure="open">{r["open_count"]}</b><span>open, of which {r["reopened_count"]} reopened ({r["reopen_cycles_total"]} cycles)</span></div>
        <div className={`tile${critOpen ? " tile--crit" : ""}`}><b data-figure="critical-unresolved">{critOpen}</b><span>critical issues not resolved</span></div>
      </div>
      <p>Mean resolution time <Def term="how it is measured">Resolution time = the verifying rerun’s time − the first detected_at, in hours, over resolved issues. A reopened issue keeps its first detected_at and counts its cycles; open issues are aged separately to the as-of.</Def>: <Fig k="mean-hours">{r["mean_hours"] ?? "n/a"}</Fig> hours over {r["resolved_count"]} resolved issues.
        {withRerun > 0 && <> Of the {claimed.length} claimed, <span data-figure="claimed-rerun">{withRerun}</span> have a rerun on record that did not verify them ({[...failedRerun.entries()].map(([k, n]) => `${k}: ${n}`).join(", ")}).</>}</p>
      {changed && (
        <p className="callout" data-testid="sim-counts">If your simulated actions were real the counts would read: resolved <b>{sim("resolved")}</b>, claimed <b>{sim("claimed")}</b>, open <b>{sim("open")}</b>. The published counts above are unchanged.</p>
      )}
    </section>
  );
}

function Aging({ views, asOf }: { views: IssueView[]; asOf: string }) {
  const open = views.filter((v) => v.cls === "open");
  const sevs = ["critical", "high", "medium", "low"];
  const cell = (b: string, s: string): number => open.filter((v) => ageBucket(v.hours) === b && v.rule.severity === s).length;
  const oldest = open.reduce<IssueView | null>((a, v) => (a === null || v.hours.n * a.hours.d > a.hours.n * v.hours.d ? v : a), null);
  return (
    <section className="block" aria-labelledby="age" data-testid="aging">
      <h2 id="age">Aging of open issues</h2>
      <p>Open issues are aged from their first detection to the as-of <span className="mono">{asOf}</span>; a reopened issue keeps its first detected_at.</p>
      <Scroll label="Open issues by age and severity"><table>
        <thead><tr><th scope="col">Age</th>{sevs.map((s) => <th key={s} scope="col" className="num">{s}</th>)}<th scope="col" className="num">All</th></tr></thead>
        <tbody>{AGE_BUCKETS.map((b) => <tr key={b.id} data-bucket={b.id}><th scope="row">{b.label}</th>{sevs.map((s) => <td key={s} className={`num mono${s === "critical" && cell(b.id, s) ? " crit-text" : ""}`}>{cell(b.id, s)}</td>)}<td className="num mono" data-k="total">{open.filter((v) => ageBucket(v.hours) === b.id).length}</td></tr>)}</tbody>
      </table></Scroll>
      {oldest && <p>Oldest open issue: <span className="mono">{oldest.issue.issue_id}</span>, {days(oldest.hours)} days ({h4(oldest.hours)} hours){oldest.cycles ? `, reopened ${oldest.cycles} time${oldest.cycles === 1 ? "" : "s"}` : ""}.</p>}
    </section>
  );
}

function Ownership({ ds, views }: { ds: Dataset; views: IssueView[] }) {
  const teams = teamRows(ds, views);
  const owners = new Map(ds.raw.owners.map((o) => [o["owner_id"] as string, o]));
  const inactiveOpen = views.filter((v) => v.cls === "open" && owners.get(v.issue.owner_id)?.["active"] === false);
  const dp = teamVersusRest(ds, views, "Data Platform");
  return (
    <section className="block" aria-labelledby="own" data-testid="issue-ownership">
      <h2 id="own">Ownership of issues</h2>
      <Scroll label="Issues by owner team"><table>
        <thead><tr><th scope="col">Team</th><th scope="col" className="num">Resolved</th><th scope="col" className="num">Mean resolution (hours)</th><th scope="col" className="num">Claimed</th><th scope="col" className="num">Open</th></tr></thead>
        <tbody>{teams.map((t) => <tr key={t.team} data-team={t.team}><th scope="row">{t.team}</th><td className="num mono">{t.resolved}</td><td className="num mono" data-k="mean">{t.mean_hours ? h4(t.mean_hours) : "n/a"}</td><td className="num mono">{t.claimed}</td><td className="num mono">{t.open}</td></tr>)}</tbody>
      </table></Scroll>
      {dp.team && dp.rest && <p className="muted" data-testid="team-contrast">{ds.id === "snapshot" ? <>One team resolves faster: Data Platform’s {dp.teamN} resolved issues average {h4(dp.team)} hours against {h4(dp.rest)} hours for the other teams’ {dp.restN}, by the owner’s team on mean resolution hours. This is a property of the synthetic data, not a finding about any real team.</> : <>Data Platform {h4(dp.team)} hours over {dp.teamN} resolved; others {h4(dp.rest)} hours over {dp.restN}.</>}</p>}
      <p data-testid="inactive-open">{inactiveOpen.length === 0 ? "No open issue is owned by an inactive owner." : <><strong>{inactiveOpen.length}</strong> open {inactiveOpen.length === 1 ? "issue is" : "issues are"} owned by an owner who is no longer active: nobody is accountable for {inactiveOpen.length === 1 ? "it" : "them"} until triage reassigns.</>}</p>
    </section>
  );
}

function Workbench({ ds, views, log }: { ds: Dataset; views: IssueView[]; log: readonly SimIssue[] }) {
  const [cls, setCls] = useParam("class", "all");
  const [sev, setSev] = useParam("severity", "all");
  const first = views.find((v) => v.cls === "open" && v.rule.severity === "critical") ?? views.find((v) => v.cls === "open") ?? views[0];
  const [sel, setSel] = useParam("issue", first?.issue.issue_id ?? "");
  const owners = new Map(ds.raw.owners.map((o) => [o["owner_id"] as string, o]));
  const list = views.filter((v) => (cls === "all" || simClassOf(log, v.issue.issue_id, v.cls) === cls) && (sev === "all" || v.rule.severity === sev))
    .sort((a, b) => (a.cls === "open" ? 0 : 1) - (b.cls === "open" ? 0 : 1) || Number(b.rule.severity === "critical") - Number(a.rule.severity === "critical") || (b.hours.n * a.hours.d > a.hours.n * b.hours.d ? 1 : -1) || cmp(a.issue.issue_id, b.issue.issue_id));
  const pg = usePage("page", 12, list.length);
  const cur = views.find((v) => v.issue.issue_id === sel) ?? first;
  const ownerName = (id: string): string => owners.get(id)?.["owner_name"] ?? id;
  const run = (action: SimIssue["action"]): void => {
    if (!cur) return;
    const id = cur.issue.issue_id;
    const now = simClassOf(log, id, cur.cls);
    if (action === "claim") {
      if (now !== "open") addSimIssue({ issue_id: id, action, outcome: "refused", code: "NOT_OPEN", note: `The issue is ${now}; only an open issue can be closed.` });
      else addSimIssue({ issue_id: id, action, outcome: "claimed", code: null, note: "Closed without a rerun: it counts as claimed, never as resolved." });
    } else if (action === "rerun") {
      const r = simulateRerun(ds, now === cur.cls ? cur : { ...cur, cls: now });
      addSimIssue({ issue_id: id, action, ...r });
    } else {
      if (now === "open") addSimIssue({ issue_id: id, action, outcome: "refused", code: "NOT_CLOSED", note: "The issue is already open." });
      else addSimIssue({ issue_id: id, action, outcome: "open", code: null, note: "Reopened: the issue is open again, keeps its first detected_at and counts another cycle." });
    }
  };
  const mine = log.filter((e) => cur && e.issue_id === cur.issue.issue_id);
  const nowCls = cur ? simClassOf(log, cur.issue.issue_id, cur.cls) : "open";
  const runs = new Map(ds.result.population.rule_runs.map((x) => [x.rule_run_id, x]));
  const ver = cur?.issue.verification_run_id ? runs.get(cur.issue.verification_run_id) : undefined;
  return (
    <section className="block" aria-labelledby="wb" data-testid="workbench">
      <h2 id="wb">The workbench</h2>
      <SimNote>Closing, rerunning and reopening below only change what this page shows you; the published issue, its rule runs and every count above stay as they are.</SimNote>
      <div className="controls">
        <Choice name="class" legend="Class" value={cls} onChange={setCls} testid="class-filter" options={[{ value: "all", label: "All" }, { value: "open", label: "Open" }, { value: "claimed", label: "Claimed" }, { value: "resolved", label: "Resolved" }]} />
        <Choice name="severity" legend="Severity" value={sev} onChange={setSev} testid="severity-filter" options={[{ value: "all", label: "All" }, { value: "critical", label: "Critical" }, { value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" }]} />
      </div>
      <Scroll label="Issues"><table data-testid="issue-table">
        <thead><tr><th scope="col">Issue</th><th scope="col">Rule</th><th scope="col">Severity</th><th scope="col">Owner</th><th scope="col">Class</th><th scope="col">Detected (UTC)</th><th scope="col" className="num">Hours</th><th scope="col" className="num">Reopens</th></tr></thead>
        <tbody>{list.slice(pg.from, pg.to).map((v) => { const id = v.issue.issue_id; const c = simClassOf(log, id, v.cls); return (
          <tr key={id} data-issue={id} className={`${id === cur?.issue.issue_id ? "is-sel" : ""}${v.rule.severity === "critical" && c !== "resolved" ? " is-crit" : ""}`}>
            <th scope="row"><a className="mono" href={`?issue=${id}`} aria-current={id === cur?.issue.issue_id ? "true" : undefined} onClick={(e) => { e.preventDefault(); setSel(id); }}>{id}</a></th>
            <td className="mono">{v.rule.rule_id}</td><td>{sevChip(v.rule.severity)}</td><td>{ownerName(v.issue.owner_id)}</td>
            <td data-k="class">{clsChip(c)}{c !== v.cls && <> <span className="muted">(simulated; published: {v.cls})</span></>}</td>
            <td className="mono">{dayTime(isoZ(v.issue.detected_at)!)}</td><td className="num mono" title={v.cls === "resolved" ? "resolution time" : v.cls === "claimed" ? "claimed age" : "open age"}>{h4(v.hours)}</td><td className="num mono">{v.cycles}</td>
          </tr>); })}</tbody>
      </table></Scroll>
      <Pager {...pg} total={list.length} label="Issues" />
      {cur && (
        <div className="block" data-testid="issue-detail" data-issue={cur.issue.issue_id} style={{ marginBottom: 0 }}>
          <h3><span className="mono">{cur.issue.issue_id}</span> {sevChip(cur.rule.severity)} {clsChip(nowCls)}</h3>
          <dl className="facts">
            <div><dt>Rule and run</dt><dd><span className="mono">{cur.rule.rule_id}</span> v{cur.base.rule_version}, run <span className="mono">{cur.base.rule_run_id}</span> ({cur.base.failure_count} failures of {cur.base.eligible_count})</dd></div>
            <div><dt>Owner</dt><dd>{ownerName(cur.issue.owner_id)} · {owners.get(cur.issue.owner_id)?.["team"]} {owners.get(cur.issue.owner_id)?.["active"] === false && <Chip kind="hatch">inactive owner</Chip>}</dd></div>
            <div><dt>Detected</dt><dd className="mono">{isoZ(cur.issue.detected_at)}{cur.cycles > 0 && ` · reopened ${cur.cycles}×`}</dd></div>
            <div><dt>Closed</dt><dd className="mono">{cur.issue.closed_at ? isoZ(cur.issue.closed_at) : "not closed"}</dd></div>
            <div><dt>Verification</dt><dd>{ver ? <><span className="mono">{ver.rule_run_id}</span>: {verificationProblem(cur.issue, cur.base, ver) ?? "a successful rerun of the same rule version"} ({ver.failure_count} failures at {isoZ(ver.run_at)})</> : "no verifying rerun on record"}</dd></div>
            <div><dt>Published class</dt><dd>{clsChip(cur.cls)} <span data-testid="detail-hours">{cur.cls === "resolved" ? `resolved after ${h4(cur.hours)} hours` : cur.cls === "claimed" ? `claimed ${h4(cur.hours)} hours after detection` : `open for ${h4(cur.hours)} hours at the as-of`}</span></dd></div>
          </dl>
          <div className="btn-row" role="group" aria-label="Simulated actions">
            <button type="button" className="button--quiet" onClick={() => run("claim")}>Simulate: close without a rerun</button>
            <button type="button" className="button--quiet" onClick={() => run("rerun")}>Simulate: rerun the same rule version</button>
            <button type="button" className="button--quiet" onClick={() => run("reopen")}>Simulate: reopen</button>
          </div>
          <div role="status" aria-live="polite" data-testid="sim-status">
            {mine.length > 0 && <ul className="sim-log" data-testid="sim-log">{mine.map((e) => <li key={e.n} data-outcome={e.outcome}><strong>{e.action}</strong> → {e.outcome}{e.code ? <> <span className="mono">{e.code}</span></> : ""}: {e.note}</li>)}</ul>}
          </div>
        </div>
      )}
    </section>
  );
}

function Issues({ ds }: { ds: Dataset }) {
  const log = useSimIssues();
  const views = ds.now.views;
  return (<><Summary ds={ds} views={views} log={log} /><Aging views={views} asOf={isoZ(ds.asOf)!} /><Ownership ds={ds} views={views} /><Workbench ds={ds} views={views} log={log} /></>);
}

export function IssuesView() {
  return (
    <>
      <ViewHead mark="Shelfmark 05 · issues" title="Issue workbench">
        <p className="lede">A failing run opens an issue with the rule’s severity. Triage gives it an owner. It is closed honestly only when a rerun of the same rule version confirms the fix.</p>
      </ViewHead>
      <WithData>{(ds) => <Issues ds={ds} />}</WithData>
    </>
  );
}
