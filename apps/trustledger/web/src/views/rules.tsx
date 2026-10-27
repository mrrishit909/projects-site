import { Link } from "../components/link";
import { Chip, Choice, Def, Fig, Pager, Scroll, usePage, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import type { Measure } from "../domain/measure";
import { cmp, type Row } from "../domain/models";
import { p6, ratio } from "../domain/num";
import { dayTime, show } from "../lib/format";
import { useParam } from "../router";

const sevChip = (s: string) => (s === "critical" ? <Chip kind="crit">critical</Chip> : <span>{s}</span>);
const rate = (fail: number, el: number): string => p6(ratio(fail, el)) ?? "n/a";

function Detail({ ds, id }: { ds: Dataset; id: string }) {
  const rule = ds.byId.rules.get(id)!;
  const comp = ds.now;
  const m: Measure | undefined = comp.measures.find((x) => x.rule.rule_id === id);
  const cmpRow = (comp.rules["comparisons"] as Record<string, Row>)[id];
  const disabled = (comp.rules["disabled"] as Record<string, Row>)[id];
  const dsRow = ds.byId.datasets.get(rule["dataset_id"])!;
  const def = rule["definition"] as Row;
  const rows = ds.result.population.dataset_rows[rule["dataset_id"]] ?? [];
  const byRow = new Map(rows.map((r) => [r["row_id"] as string, r]));
  const field: string | undefined = def["field"];
  const runs = ds.raw.rule_runs.filter((r) => r["rule_id"] === id).sort((a, b) => cmp(b["run_at"], a["run_at"]));
  const scheduled = runs.filter((r) => r["kind"] === "scheduled");
  const shown = scheduled.slice(0, 14);
  const type = rule["rule_type"] as string;
  const popLine = ((): string => {
    if (type === "timeliness") return "The eligible population is one dataset: the schedule is evaluated once per dataset.";
    const f = def["filter"] as Row | undefined;
    const base = `${rows.length} rows in ${rule["dataset_id"]}`;
    return f ? `${base}; eligible: rows where ${f["field"]} = “${f["equals"]}” (a filter declared in the rule version).` : `${base}; eligible: all rows (no filter declared).`;
  })();
  return (
    <section className="block" data-testid="rule-detail" data-rule={id} aria-labelledby="rd">
      <h2 id="rd"><span className="mono">{id}</span></h2>
      <dl className="facts">
        <div><dt>Dataset</dt><dd><span className="mono">{rule["dataset_id"]}</span> · {dsRow["dataset_name"]}</dd></div>
        <div><dt>Dimension, severity</dt><dd>{type}, {sevChip(rule["severity"])}</dd></div>
        <div><dt>Rule version</dt><dd className="mono">v{rule["version_number"]}</dd></div>
        <div><dt>Status</dt><dd>{rule["status"] === "active" ? <Chip kind="ok">active</Chip> : <Chip kind="hatch">disabled</Chip>} {disabled && <span data-testid="disabled-info">since {dayTime(disabled["disabled_at"])}: “{disabled["disabled_reason"]}”. {disabled["runs_retained"]} runs and {disabled["issues_retained"]} issues are retained and readable; disabling a rule is not repair.</span>}</dd></div>
        <div><dt>Definition</dt><dd><pre className="json">{JSON.stringify(def, null, 1)}</pre></dd></div>
      </dl>

      <h3>Eligible population</h3>
      <p data-testid="eligible">{popLine}</p>
      {m && (
        <ul data-testid="counts">
          <li>Eligible: <Fig k="eligible">{m.eligible}</Fig>{type === "relationship" && <> (foreign keys {m.block["total_fk_count"]}, of which <Fig k="null-fk">{m.block["null_fk_count"]}</Fig> null and counted separately, not in the denominator)</>}{type === "validity" && <>, populated <Fig k="populated">{m.block["populated_count"]}</Fig></>}</li>
          <li>Failures: <Fig k="failures">{m.failures}</Fig> ({type === "completeness" && <>missing values, of which {m.block["whitespace_only_count"]} whitespace-only</>}{type === "validity" && <>missing or not matching the format; validity is format, never correctness</>}{type === "uniqueness" && <>{m.block["null_key_count"]} null keys and {m.block["duplicate_rows"]} rows beyond the first of their key</>}{type === "relationship" && <>eligible keys with no parent row</>}{type === "timeliness" && <>the dataset refreshed outside [occurrence, deadline)</>})</li>
          <li>Failure rate: <span className="mono">{rate(m.failures, m.eligible)}</span> · dimension score: <span className="mono">{m.value === null ? "n/a" : p6(m.value)}</span></li>
        </ul>
      )}
      {!m && <p className="notice" data-testid="no-measure">{rule["status"] === "disabled" ? "This rule is disabled: it has no current measurement, but its history below is kept." : "This rule is not measured at the as-of (an unmonitored dataset's timeliness rule, or a validity rule without a pattern)."}</p>}

      <h3>Failing examples</h3>
      {m && m.failing.length > 0 && type !== "timeliness" ? (
        <Scroll label="Failing examples"><table data-testid="failing">
          <thead><tr><th scope="col">Row</th><th scope="col">{field}</th></tr></thead>
          <tbody>{m.failing.slice(0, 10).map((rid) => <tr key={rid}><th scope="row" className="mono">{rid}</th><td className="mono">{show(byRow.get(rid)?.[field ?? ""])}</td></tr>)}</tbody>
        </table></Scroll>
      ) : <p data-testid="no-failing">{m ? (type === "timeliness" ? (m.failures ? `The dataset refreshed outside its window at the as-of.` : "The dataset refreshed within its window at the as-of.") : "No failing rows at the as-of.") : "Not measured."}</p>}
      {m && m.failing.length > 10 && <p className="muted">Showing 10 of {m.failing.length} failing rows. Values are printed as JSON so null, empty and whitespace-only text are distinguishable.</p>}

      <h3>Comparable runs</h3>
      <div data-testid="comparison">
        {cmpRow ? (cmpRow["comparable"]
          ? <p className="callout"><Chip kind="ok">comparable</Chip> The previous scheduled run <span className="mono">{cmpRow["previous_run_id"]}</span> used the same rule version (v{cmpRow["current_rule_version"]}), so the eligibility definition is the same: failure rate {cmpRow["failure_rate_previous"]} then, {cmpRow["failure_rate_current"]} now.</p>
          : <p className="callout" data-testid="not-comparable"><Chip kind="note" k="RULE_VERSION_DIFFERS">RULE_VERSION_DIFFERS</Chip> The previous scheduled run <span className="mono">{cmpRow["previous_run_id"]}</span> was rule v{cmpRow["previous_rule_version"]} (eligible {cmpRow["previous_eligible_count"]}); the current rule is v{cmpRow["current_rule_version"]} (eligible {cmpRow["current_eligible_count"]}). The denominator changed with the rule, so <strong>no rates are compared</strong>.</p>)
          : <p className="muted">{m ? "There is no earlier scheduled run to compare with." : "No current run to compare."}</p>}
      </div>
      <Scroll label="Recent scheduled runs of this rule"><table data-testid="runs">
        <thead><tr><th scope="col">Run</th><th scope="col">At (UTC)</th><th scope="col">Rule version</th><th scope="col">Weights</th><th scope="col" className="num">Eligible</th><th scope="col" className="num">Failures</th><th scope="col" className="num">Failure rate</th></tr></thead>
        <tbody>{shown.map((r) => { const same = r["rule_version"] === rule["version_number"]; return (
          <tr key={r["rule_run_id"]} data-run={r["rule_run_id"]} data-comparable={same}><th scope="row" className="mono">{r["rule_run_id"]}</th><td className="mono">{dayTime(r["run_at"])}</td><td className="mono">v{r["rule_version"]}{!same && <> <Chip kind="note">not comparable with v{rule["version_number"]}</Chip></>}</td><td className="mono">{r["weight_version"]}</td><td className="num mono">{r["eligible_count"]}</td><td className="num mono">{r["failure_count"]}</td><td className="num mono">{same ? rate(r["failure_count"], r["eligible_count"]) : "not compared"}</td></tr>); })}</tbody>
      </table></Scroll>
      <p className="muted">{scheduled.length} scheduled and {runs.length - scheduled.length} verification reruns are stored for this rule; the newest {shown.length} scheduled runs are shown. A rate is printed only when its run used the rule version that is current now: two runs are comparable only when their eligibility definition is the same.</p>
      <p><Link to={`scorecard?ds=${rule["dataset_id"]}`}>See this dataset on the scorecard</Link> · <Link to="issues">Issues opened by failing runs</Link></p>
    </section>
  );
}

function Rules({ ds }: { ds: Dataset }) {
  const comp = ds.now;
  const cmps = comp.rules["comparisons"] as Record<string, Row>;
  const disabled = comp.rules["disabled"] as Record<string, Row>;
  const all = [...ds.raw.quality_rules].sort((a, b) => cmp(a["rule_id"], b["rule_id"]));
  const notComparable = all.filter((r) => cmps[r["rule_id"]] && !cmps[r["rule_id"]]!["comparable"]);
  const dflt = (notComparable[0] ?? all[0])["rule_id"] as string;
  const [id, setId] = useParam("rule", dflt);
  const [filter, setFilter] = useParam("only", "all");
  const rule = ds.byId.rules.has(id) ? id : dflt;
  const list = all.filter((r) => filter === "all" || (filter === "version" && cmps[r["rule_id"]] && !cmps[r["rule_id"]]!["comparable"]) || (filter === "disabled" && r["rule_id"] in disabled) || (filter === "critical" && r["severity"] === "critical"));
  const pg = usePage("page", 12, list.length);
  return (
    <>
      <Detail ds={ds} id={rule} />
      <section className="block" aria-labelledby="idx" data-testid="rule-index">
        <h2 id="idx">All rules ({all.length})</h2>
        <p className="muted"><Fig k="not-comparable">{notComparable.length}</Fig> {notComparable.length === 1 ? "rule's" : "rules'"} current version cannot be compared with its previous scheduled run (<span className="mono">RULE_VERSION_DIFFERS</span>); {Object.keys(disabled).length} {Object.keys(disabled).length === 1 ? "rule is" : "rules are"} disabled with history kept.</p>
        <Choice name="only" legend="Show" value={filter} onChange={(v) => { setFilter(v); }} testid="rule-filter" options={[{ value: "all", label: "All" }, { value: "version", label: `Version differs (${notComparable.length})` }, { value: "disabled", label: `Disabled (${Object.keys(disabled).length})` }, { value: "critical", label: "Critical" }]} />
        <Scroll label="Rules"><table>
          <thead><tr><th scope="col">Rule</th><th scope="col">Dataset</th><th scope="col">Dimension</th><th scope="col">Severity</th><th scope="col">Version</th><th scope="col">Status</th></tr></thead>
          <tbody>{list.slice(pg.from, pg.to).map((r) => { const rid = r["rule_id"] as string; return (
            <tr key={rid} data-rule={rid} className={rid === rule ? "is-sel" : ""}>
              <th scope="row"><a className="mono" href={`?rule=${rid}${filter !== "all" ? `&only=${filter}` : ""}`} aria-current={rid === rule ? "true" : undefined} onClick={(e) => { e.preventDefault(); setId(rid); window.scrollTo(0, 0); }}>{rid}</a></th>
              <td className="mono">{r["dataset_id"]}</td><td>{r["rule_type"]}</td><td>{sevChip(r["severity"])}</td><td className="mono">v{r["version_number"]}</td>
              <td>{rid in disabled ? <Chip kind="hatch">disabled</Chip> : cmps[rid] && !cmps[rid]!["comparable"] ? <Chip kind="note">version differs</Chip> : <Chip kind="ok">active</Chip>}</td>
            </tr>); })}</tbody>
        </table></Scroll>
        <Pager {...pg} total={list.length} label="Rules" />
      </section>
    </>
  );
}

export function RulesView() {
  return (
    <>
      <ViewHead mark="Shelfmark 04 · rules" title="Rule detail">
        <p className="lede">A rule is a published definition of what to measure. This page shows who is eligible to be measured, what failed with real examples, and whether today’s run can honestly be compared with yesterday’s. <Def term="why comparison can be refused">Two runs are comparable only when their eligibility definition (the rule version) is the same. If a version added a filter, the denominator changed, so a drop in the failure rate would be an artefact. The result says RULE_VERSION_DIFFERS and compares nothing.</Def></p>
      </ViewHead>
      <WithData>{(ds) => <Rules ds={ds} />}</WithData>
    </>
  );
}
