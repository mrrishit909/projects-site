import { Link } from "../components/link";
import { Chip, Choice, Def, Fig, Scroll, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { cmp, type Row } from "../domain/models";
import { p6 } from "../domain/num";
import { dayTime, LABELS, minus } from "../lib/format";
import { scoreRows } from "../lib/derive";
import { useParam } from "../router";

const sev = (s: string) => (s === "critical" ? <Chip kind="crit">critical</Chip> : <span>{s}</span>);
const entries = (b: Row, only: string): [string, Row][] => Object.entries(b as Record<string, Row>).filter(([, v]) => only === "all" || v["dataset_id"] === only).sort((a, b) => cmp(a[0], b[0]));

function RuleCell({ ds, id }: { ds: Dataset; id: string }) {
  const r = ds.byId.rules.get(id)!;
  return <><th scope="row"><span className="mono">{id}</span><br /><span className="muted">v{r["version_number"]} · {sev(r["severity"])}</span></th><td className="mono">{r["dataset_id"]}</td></>;
}

function Dimensions({ ds, only, wv }: { ds: Dataset; only: string; wv: string }) {
  const m = ds.at(ds.asOf, wv).metrics;
  const comp = entries(m["completeness"], only), val = entries(m["validity"], only), uni = entries(m["uniqueness"], only), rel = entries(m["relationship_integrity"], only);
  const tl = m["timeliness"];
  const tlRows = Object.entries(tl["datasets"] as Record<string, Row>).filter(([id]) => only === "all" || id === only);
  return (
    <section aria-labelledby="dims" data-testid="dimensions">
      <h2 id="dims">The five dimensions, measured and reported separately</h2>
      <p className="muted">No dimension is folded into another. Each is measured on its own denominator, which is printed beside it. A figure that is unknown (no denominator) reads “n/a”, never 0.</p>

      <div className="block" data-testid="dim-completeness">
        <h3>Completeness <Def term="how it is measured">Non-missing eligible values ÷ eligible values. A value is missing when it is null or, after trimming space, tab, return and newline, empty (the whitespace policy is declared in the rule version). The count of whitespace-only values is shown beside it.</Def></h3>
        <Scroll label="Completeness by rule"><table>
          <thead><tr><th scope="col">Rule</th><th scope="col">Dataset</th><th scope="col" className="num">Eligible</th><th scope="col" className="num">Missing</th><th scope="col" className="num">of which whitespace-only</th><th scope="col" className="num">Populated</th><th scope="col" className="num">Completeness</th></tr></thead>
          <tbody>{comp.map(([id, b]) => <tr key={id} data-rule={id}><RuleCell ds={ds} id={id} /><td className="num mono">{b["eligible_count"]}</td><td className="num mono">{b["missing_count"]}</td><td className="num mono">{b["whitespace_only_count"]}</td><td className="num mono">{b["populated_count"]}</td><td className="num mono" data-k="value">{b["value"] ?? "n/a"}</td></tr>)}{comp.length === 0 && <tr><td colSpan={7}>No active completeness rule{only === "all" ? "" : " on this dataset"}.</td></tr>}</tbody>
        </table></Scroll>
      </div>

      <div className="block" data-testid="dim-validity">
        <h3>Validity <Def term="two denominators, both shown">Validity is format validity, never correctness. Populated-only validity = passing ÷ populated; all-eligible validity = passing ÷ eligible. They differ exactly by the missing values, so both are printed with their labels. The weighted score uses the populated-only figure, because completeness already carries the missing share.</Def></h3>
        <Scroll label="Validity by rule"><table>
          <thead><tr><th scope="col">Rule</th><th scope="col">Dataset</th><th scope="col" className="num">Eligible</th><th scope="col" className="num">Populated</th><th scope="col" className="num">Passing</th><th scope="col" className="num">Populated-only<br /><span className="mono muted">validity_populated_only</span></th><th scope="col" className="num">All-eligible<br /><span className="mono muted">validity_all_eligible</span></th></tr></thead>
          <tbody>{val.map(([id, b]) => <tr key={id} data-rule={id}><RuleCell ds={ds} id={id} /><td className="num mono">{b["eligible_count"]}</td><td className="num mono">{b["populated_count"]}</td><td className="num mono">{b["passing_count"]}</td>
            <td className="num mono" data-k="populated_only" data-label={b["populated_only"]["label"]}>{b["populated_only"]["value"] ?? "n/a"}</td><td className="num mono" data-k="all_eligible" data-label={b["all_eligible"]["label"]}>{b["all_eligible"]["value"] ?? "n/a"}</td></tr>)}{val.length === 0 && <tr><td colSpan={7}>No active validity rule{only === "all" ? "" : " on this dataset"}.</td></tr>}</tbody>
        </table></Scroll>
        <p className="muted">{LABELS["validity_populated_only"]}; {LABELS["validity_all_eligible"]}.</p>
      </div>

      <div className="block" data-testid="dim-uniqueness">
        <h3>Uniqueness <Def term="groups and rows">Duplicate-group share = keys with more than one row ÷ distinct keys. Duplicate-row share = rows beyond the first per key ÷ eligible rows. Null (and empty or whitespace-only) keys are failures counted and listed separately. The first row in row order is kept; the dimension score is (eligible − null-key rows − duplicate rows) ÷ eligible, so a null key lowers the score exactly as a duplicate does.</Def></h3>
        <Scroll label="Uniqueness by rule"><table>
          <thead><tr><th scope="col">Rule</th><th scope="col">Dataset</th><th scope="col" className="num">Eligible</th><th scope="col" className="num">Null keys</th><th scope="col" className="num">Distinct keys</th><th scope="col" className="num">Groups</th><th scope="col" className="num">Rows beyond first</th><th scope="col" className="num">Group share<br /><span className="mono muted">duplicate_group_share</span></th><th scope="col" className="num">Row share<br /><span className="mono muted">duplicate_row_share</span></th></tr></thead>
          <tbody>{uni.map(([id, b]) => <tr key={id} data-rule={id}><RuleCell ds={ds} id={id} /><td className="num mono">{b["eligible_count"]}</td><td className="num mono">{b["null_key_count"]}</td><td className="num mono">{b["distinct_keys"]}</td><td className="num mono">{b["duplicate_groups"]}</td><td className="num mono">{b["duplicate_rows"]}</td>
            <td className="num mono" data-k="group_share" data-label={b["group_share"]["label"]}>{b["group_share"]["value"] ?? "n/a"}</td><td className="num mono" data-k="row_share" data-label={b["row_share"]["label"]}>{b["row_share"]["value"] ?? "n/a"}</td></tr>)}{uni.length === 0 && <tr><td colSpan={9}>No active uniqueness rule{only === "all" ? "" : " on this dataset"}.</td></tr>}</tbody>
        </table></Scroll>
      </div>

      <div className="block" data-testid="dim-relationship">
        <h3>Relationship integrity <Def term="null foreign keys">Matched eligible foreign keys ÷ eligible foreign keys. A missing foreign key is excluded from the denominator and counted separately, so it neither passes nor fails silently. Missing means null, or text that is empty after trimming under the whitespace policy: an empty string and a string of spaces are counted with the nulls.</Def></h3>
        <Scroll label="Relationship integrity by rule"><table>
          <thead><tr><th scope="col">Rule</th><th scope="col">Dataset</th><th scope="col" className="num">Foreign keys</th><th scope="col" className="num">Null or empty (whitespace policy), counted separately</th><th scope="col" className="num">Eligible</th><th scope="col" className="num">Matched</th><th scope="col" className="num">Unmatched</th><th scope="col" className="num">Integrity</th></tr></thead>
          <tbody>{rel.map(([id, b]) => <tr key={id} data-rule={id}><RuleCell ds={ds} id={id} /><td className="num mono">{b["total_fk_count"]}</td><td className="num mono" data-k="null_fk">{b["null_fk_count"]}</td><td className="num mono">{b["eligible_count"]}</td><td className="num mono">{b["matched_count"]}</td><td className="num mono">{b["unmatched_count"]}</td><td className="num mono" data-k="value">{b["value"] ?? "n/a"}</td></tr>)}{rel.length === 0 && <tr><td colSpan={8}>No active relationship rule{only === "all" ? "" : " on this dataset"}.</td></tr>}</tbody>
        </table></Scroll>
      </div>

      <div className="block" data-testid="dim-timeliness">
        <h3>Timeliness <Def term="the local schedule">A monitored dataset is on time at the as-of when a refresh (not after the as-of) falls in [occurrence, occurrence + grace) of the latest daily occurrence, in its own IANA zone, that has started by the as-of. The window is half-open, so a refresh exactly at the deadline is late. If that occurrence is still open and nothing has been refreshed yet, the dataset is pending: neither on time nor late, and outside the denominator. Only monitored datasets count.</Def></h3>
        <p className="pair-fig"><span><span className="big"><Fig k="timeliness">{tl["value"] ?? "n/a"}</Fig></span><span className="cap">{tl["on_time_count"]} of {tl["evaluated_datasets"]} evaluated datasets refreshed within their target ({tl["monitored_datasets"]} monitored; <span data-k="pending-count">{tl["pending_count"]}</span> pending: an open window with no refresh yet is neither on time nor late){only === "all" ? "" : " (portfolio figure; the table below is this dataset)"}</span></span></p>
        <Scroll label="Timeliness by monitored dataset"><table>
          <thead><tr><th scope="col">Dataset</th><th scope="col">Schedule</th><th scope="col">Occurrence (UTC)</th><th scope="col">Deadline (UTC)</th><th scope="col">Last refresh (UTC)</th><th scope="col">State</th></tr></thead>
          <tbody>{tlRows.map(([id, t]) => <tr key={id} data-dataset={id}><th scope="row" className="mono">{id}</th><td>{t["scheduled_local"]} {t["timezone"]}, grace {t["grace_minutes"]} min</td><td className="mono">{dayTime(t["evaluated_occurrence_utc"])}</td><td className="mono">{dayTime(t["deadline_utc"])}</td><td className="mono">{t["last_refreshed_at"] ? dayTime(t["last_refreshed_at"]) : "never"}</td><td data-k="on_time" data-state={t["state"]}>{t["state"] === "on_time" ? <Chip kind="ok">on time</Chip> : t["state"] === "pending" ? <Chip kind="note">pending</Chip> : <Chip kind="hatch">late</Chip>}</td></tr>)}{tlRows.length === 0 && <tr><td colSpan={6}>Not monitored.</td></tr>}</tbody>
        </table></Scroll>
      </div>
      <p className="muted">Dimension figures do not depend on the weight version; the selected version ({wv}) only changes the weighted score below.</p>
    </section>
  );
}

function Weighted({ ds, only, wv }: { ds: Dataset; only: string; wv: string }) {
  const comp = ds.at(ds.asOf, wv);
  const w = comp.metrics["weighted_score"]["datasets"] as Record<string, Row>;
  const by = comp.metrics["weighted_score"]["by_weight_version"] as Record<string, Record<string, string | null>>;
  const shift = new Map(scoreRows(ds).map((r) => [r.dataset_id, r]));
  const versions = ds.weightVersions;
  const rows = Object.entries(w).filter(([id]) => only === "all" || id === only).sort((a, b) => Number(b[1]["critical_override"]) - Number(a[1]["critical_override"]) || cmp(a[0], b[0]));
  const crit = comp.metrics["critical_failures"];
  const wvRow = ds.result.population.weight_versions.find((x) => x.weight_version === wv)!;
  const wvRaw = ds.raw.weight_versions.find((x) => x["weight_version"] === wv)!["valid_from"] as string;
  return (
    <section aria-labelledby="ws" data-testid="weighted">
      <h2 id="ws">The weighted score, and the critical failures that no score may hide</h2>
      <p>Score = Σ(dimension score × weight) ÷ Σ(weights of the dimensions that were measured), under the weight version named in the result. A dimension that was not measured is left out of both sums; a dataset that measures nothing has no score (n/a), never 0.</p>
      <div className="block block--crit" data-testid="critical-summary">
        <h3>Critical failures, shown independently</h3>
        <div className="pair-fig">
          <div><span className="big crit-text"><Fig k="critical-failures">{crit["failures"]}</Fig></span><span className="cap">failing rows of active critical rules on the current run, plus the live failure of a critical rule disabled while its latest run fails ({(crit["carried"] as Row[]).length} carried)</span></div>
          <div><span className="big crit-text"><Fig k="critical-open">{crit["open_issues"]}</Fig></span><span className="cap">critical issues not resolved (open, reopened or claimed)</span></div>
          <div><span className="big crit-text"><Fig k="overridden">{crit["datasets_overridden"]}</Fig></span><span className="cap">datasets carrying <Def term="the critical override">A dataset with any open critical failure carries critical_override = true beside its score, however high the score. The override is never recomputed from the score.</Def></span></div>
        </div>
      </div>
      <Scroll label="Weighted score by dataset"><table data-testid="score-table">
        <caption>Weights {wv}, valid from {dayTime(wvRaw)}: {Object.entries(wvRow.weights).map(([k, v]) => `${k} ${p6(v)}`).join(", ")}</caption>
        <thead><tr><th scope="col">Dataset</th><th scope="col">Measured</th><th scope="col" className="num">Weight sum</th><th scope="col" className="num">Score ({wv})</th>{versions.map((v) => <th key={v} scope="col" className="num">{v}</th>)}<th scope="col" className="num">Shift</th><th scope="col" className="num">Critical rows</th><th scope="col" className="num">Open critical issues</th><th scope="col">Critical override</th></tr></thead>
        <tbody>{rows.map(([id, r]) => {
          const sh = shift.get(id)?.delta ?? null;
          return (
            <tr key={id} data-dataset={id} className={r["critical_override"] ? "is-crit" : ""}>
              <th scope="row"><span className="mono">{id}</span></th>
              <td>{(r["measured_dimensions"] as string[]).length ? (r["measured_dimensions"] as string[]).join(", ") : "none"}</td>
              <td className="num mono">{r["weight_sum"]}</td>
              <td className="num mono" data-k="score">{r["value"] ?? "n/a"}{r["critical_override"] && <> <Chip kind="crit" k="override">critical override</Chip></>}</td>
              {versions.map((v) => <td key={v} className="num mono" data-k={v}>{by[v]?.[id] ?? "n/a"}</td>)}
              <td className="num mono" data-k="shift">{sh === null ? "n/a" : minus(p6(sh)!)}</td>
              <td className={`num mono${r["critical_failures"] ? " crit-text" : ""}`} data-k="critical">{r["critical_failures"]}</td>
              <td className={`num mono${r["critical_open_issues"] ? " crit-text" : ""}`} data-k="critical-issues">{r["critical_open_issues"]}</td>
              <td data-k="override">{r["critical_override"] ? <Chip kind="crit">override: true</Chip> : <span className="muted">false</span>}</td>
            </tr>
          );
        })}</tbody>
      </table></Scroll>
      <p className="muted">The same rows and rules score differently under different weight versions: the shift column is the last version minus the first, computed from exact fractions. The weight change moves a score without any rule changing, which is why the version is named in every result.</p>
      <p className="muted" data-testid="shift-footnote">Note: the shift uses the exact fractions, not the rounded scores shown, so it can differ from the difference of the two rounded scores by 0.000001.</p>
      {(crit["carried"] as Row[]).length > 0 && <p className="notice" data-testid="carried">Carried: {(crit["carried"] as Row[]).map((c) => `${c["rule_id"]} (${c["failure_count"]} from run ${c["rule_run_id"]})`).join(", ")}. A critical rule that was disabled while its latest run fails keeps counting that failure until a verified rerun passes; disabling is not repair.</p>}
    </section>
  );
}

function Portfolio({ ds, wv }: { ds: Dataset; wv: string }) {
  const rows = scoreRows(ds, ds.at(ds.asOf, wv)).filter((r) => r.delta !== null);
  const moved = rows.filter((r) => r.delta!.n !== 0n);
  const big = rows.filter((r) => (r.delta!.n < 0n ? -r.delta!.n : r.delta!.n) * 200n >= r.delta!.d);
  const largest = rows.reduce<typeof rows[number] | null>((a, b) => (a === null || (b.delta!.n < 0n ? -b.delta!.n : b.delta!.n) * a.delta!.d > (a.delta!.n < 0n ? -a.delta!.n : a.delta!.n) * b.delta!.d ? b : a), null);
  const own = ds.now.metrics["ownership_coverage"];
  return (
    <section className="block" data-testid="portfolio" aria-labelledby="port">
      <h2 id="port">The portfolio around the scores</h2>
      <div className="tiles">
        <div className="tile"><b data-figure="scored">{rows.length}</b><span>datasets with a score ({ds.raw.datasets.length - rows.length} measure nothing)</span></div>
        <div className="tile"><b data-figure="moved">{moved.length}</b><span>score differently under {ds.weightVersions.join(" and ")}</span></div>
        <div className="tile"><b data-figure="moved-big">{big.length}</b><span>move by 0.005 or more</span></div>
        <div className="tile"><b data-figure="largest">{largest ? minus(p6(largest.delta)!) : "n/a"}</b><span>largest shift{largest ? <>: <span className="mono">{largest.dataset_id}</span></> : ""}</span></div>
      </div>
      <div className="pair-fig" data-testid="ownership-strip"><div><span className="big"><Fig k="ownership">{own["value"]}</Fig></span><span className="cap">ownership coverage: {own["covered"]} of {own["datasets"]} datasets have an active owner</span></div>
        <div><span className="big"><Fig k="uncovered">{(own["uncovered"] as string[]).length}</Fig></span><span className="cap">uncovered: {(own["uncovered"] as string[]).length ? (own["uncovered"] as string[]).join(", ") : "none"}</span></div></div>
      <p className="muted">See <Link to="catalog">the catalog</Link> for who owns the uncovered datasets and <Link to="rules">the rules</Link> for the runs behind each figure.</p>
    </section>
  );
}

function Scorecard({ ds }: { ds: Dataset }) {
  const dflt = ds.now.weight_version ?? ds.weightVersions[ds.weightVersions.length - 1]!;
  const [wv, setWv] = useParam("wv", dflt);
  const [only, setOnly] = useParam("ds", "all");
  const version = ds.weightVersions.includes(wv) ? wv : dflt;
  const dsIds = ds.raw.datasets.map((d) => d["dataset_id"] as string).sort(cmp);
  return (
    <>
      <div className="controls">
        <Choice name="wv" legend="Weight version" value={version} onChange={setWv} testid="wv-switch" options={ds.weightVersions.map((v) => ({ value: v, label: `${v}${v === dflt ? " (in force at the as-of)" : ""}` }))} />
        <label className="field">Dataset
          <select value={only} onChange={(e) => setOnly(e.target.value)} aria-label="Dataset" data-testid="dataset-filter">
            <option value="all">All datasets</option>
            {dsIds.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
      </div>
      <Weighted ds={ds} only={only} wv={version} />
      <Dimensions ds={ds} only={only} wv={version} />
      <Portfolio ds={ds} wv={version} />
    </>
  );
}

export function ScorecardView() {
  return (
    <>
      <ViewHead mark="Shelfmark 03 · scorecard" title="Quality scorecard">
        <p className="lede">Five dimensions, each on its own denominator, then one weighted score with its weight version named, and critical failures counted separately so that no average can hide them.</p>
      </ViewHead>
      <WithData>{(ds) => <Scorecard ds={ds} />}</WithData>
    </>
  );
}
