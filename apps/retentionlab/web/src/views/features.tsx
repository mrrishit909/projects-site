import { useMemo, useState } from "react";
import { LineSeries, Timeline, Legend, type TimelineEvent } from "../components/charts";
import { Link } from "../components/link";
import { Chip, Def, Fig, ParamSelect, Related, Scroll, ScopeStrip, TableFold, ViewHead, WithData } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { EVENTS, FEATURES } from "../domain/contract";
import { DomainError } from "../domain/errors";
import type { Row } from "../domain/models";
import { add, money, p6, parseFraction, ratio, ZERO } from "../domain/num";
import { checkFeatureRequest } from "../domain/rules";
import { daysUs, isoZ, parseTs, wholeDays } from "../domain/time";
import { classifyFeature } from "../domain/world";
import { day, n0, orDash } from "../lib/format";
import { useParam } from "../router";

export function FeaturesView() {
  return <WithData>{(ds) => <Features ds={ds} />}</WithData>;
}

const REFUSAL_WORDS: Record<string, string> = {
  POST_OUTCOME_FIELD: "only exists after the cancellation", LATENT_TRUTH: "the generator's hidden truth", ID_FEATURE: "an identifier carries creation order", UNKNOWN_FEATURE: "not registered",
};

function RequestChecker({ ds }: { ds: Dataset }) {
  const [text, setText] = useState("usage_events_30d, cancellation_reason");
  const fields = text.split(",").map((x) => x.trim()).filter(Boolean);
  let outcome: { ok: true; fields: string[] } | { ok: false; code: string; offending: { item: unknown; code: string }[] };
  try { outcome = { ok: true, fields: checkFeatureRequest(ds.primary.world.registry, fields) }; }
  catch (e) { if (!(e instanceof DomainError)) throw e; outcome = { ok: false, code: e.code, offending: e.offending }; }
  return (
    <div className="panel" data-testid="request-checker">
      <h3>Try a feature request</h3>
      <p>The builder refuses a request that names a field that only exists after the outcome, a latent field of the generator, an identifier-derived field, or a field that is not registered. This runs the domain's own rule in your browser; nothing is stored.</p>
      <label className="field">Fields, separated by commas
        <input type="text" value={text} onChange={(e) => setText(e.target.value)} data-testid="request-input" aria-describedby="request-result" spellCheck={false} />
      </label>
      <p id="request-result" role="status" data-testid="request-result">
        {fields.length === 0 ? "Name at least one field." : outcome.ok ? <><Chip kind="ok">accepted</Chip> {outcome.fields.length} registered features: {outcome.fields.join(", ")}.</>
          : <><Chip kind="risk">refused {outcome.code}</Chip> {outcome.offending.map((o) => `${String(o.item)} (${o.code})`).join(", ")}.</>}
      </p>
    </div>
  );
}

function Lineage({ ds }: { ds: Dataset }) {
  const w = ds.primary.world;
  const lateRows = useMemo(() => w.acc.prediction_cutoffs.map((c) => w.analyse(c["cutoff_id"])).filter((r) => r.eligible && r.arrived_late && Object.values(r.arrived_late).some((n) => n > 0)).map((r) => r.cutoff_id).sort(), [w]);
  const example = ((ds.injections?.["injections"] as Row[] | undefined)?.find((i) => i["id"] === "INJ-02")?.["facts"]?.["cohort"]?.["examples"]?.[0]?.["cutoff_id"]) as string | undefined;
  const dflt = example && lateRows.includes(example) ? example : (lateRows[0] ?? "");
  const [sel] = useParam("cutoff", dflt);
  const cutoffId = lateRows.includes(sel) ? sel : dflt;
  if (!cutoffId) return <p className="notice" data-testid="no-late">No eligible row in this dataset has an event that arrived after its cutoff.</p>;
  const c = w.cutoffs.get(cutoffId)!;
  const a = w.analyse(cutoffId);
  const pa = parseTs(c["prediction_at"]), obs = parseTs(c["observation_start"]);
  const sec = (t: bigint): number => Number(t / 1_000_000n);
  const rows: { lane: TimelineEvent["lane"]; id: string; at: bigint; avail: bigint; detail: string }[] = [];
  const lanes: [typeof EVENTS[number], TimelineEvent["lane"], (e: Row) => string][] = [["usage_events", "usage", (e) => String(e["event_name"])], ["billing_events", "billing", (e) => `amount ${e["amount"]}`], ["support_events", "support", (e) => `severity ${e["severity"]}`], ["subscription_events", "subscription", (e) => String(e["event_type"])]];
  for (const [ent, lane, det] of lanes) for (const e of w.byAcct[ent].get(c["account_id"]) ?? []) {
    const at = parseTs(e["event_at"]);
    if (at >= obs - daysUs(10) && at < pa + daysUs(14)) rows.push({ lane, id: e[Object.keys(e).find((k) => k.endsWith("_event_id"))!], at, avail: parseTs(e["available_at"]), detail: det(e) });
  }
  rows.sort((x, y) => (x.at < y.at ? -1 : x.at > y.at ? 1 : x.id < y.id ? -1 : 1));
  const status = (r: (typeof rows)[number]): "used" | "late" | "outside" => (r.at >= obs && r.at < pa ? (r.avail < pa ? "used" : "late") : r.lane === "subscription" && r.at < pa && pa <= r.avail ? "late" : "outside");
  const events: TimelineEvent[] = rows.map((r) => ({ id: r.id, lane: r.lane, at: sec(r.at), avail: sec(r.avail), late: status(r) === "late", inWindow: status(r) === "used" }));
  const stored = w.acc.feature_rows.find((f) => f["cutoff_id"] === cutoffId)?.["features_json"] as Row | undefined;
  // the same features if availability were ignored (a leak): count and total every event that happened inside the window
  const inWin = (ent: (typeof EVENTS)[number]): Row[] => (w.byAcct[ent].get(c["account_id"]) ?? []).filter((e) => { const t = parseTs(e["event_at"]); return t >= obs && t < pa; });
  const u = inWin("usage_events"), recent = pa - daysUs(w.window("usage_events_30d", 30));
  const lastU = u.reduce<bigint | null>((m, e) => { const t = parseTs(e["event_at"]); return m === null || t > m ? t : m; }, null);
  const bills = inWin("billing_events").map((e) => parseFraction(e["amount"], false));
  const ignoring: Record<string, unknown> = {
    usage_events_30d: u.filter((e) => parseTs(e["event_at"]) >= recent).length, days_since_last_usage: lastU === null ? null : wholeDays(pa, lastU),
    high_severity_support_90d: inWin("support_events").filter((e) => e["severity"] === "high").length, billing_total_90d: bills.length ? money(bills.reduce(add, ZERO)) : null,
  };
  return (
    <section className="panel" data-testid="lineage" aria-labelledby="lineage-h">
      <h2 id="lineage-h">Point-in-time lineage of one feature row</h2>
      <p>A feature may use an event only if it happened inside the observation window <em>and</em> was available before the cutoff. Pick a row that has events arriving late.</p>
      <div className="controls">
        <ParamSelect name="cutoff" label={`Cutoff row with a late event (${lateRows.length} in the cohort)`} dflt={dflt} options={lateRows.map((id) => ({ value: id, label: `${id}` }))} testid="lineage-select" />
      </div>
      <dl className="kv" data-testid="lineage-facts">
        <dt>account</dt><dd>{String(c["account_id"])}</dd><dt>cutoff</dt><dd>{c["prediction_at"]}</dd><dt>observation window</dt><dd>[{c["observation_start"]}, {c["prediction_at"]})</dd>
        <dt>max_available_at used</dt><dd data-k="max-available">{a.max_available_at ?? "none"}</dd>
        <dt>arrived late (excluded)</dt><dd data-k="arrived-late">{a.arrived_late ? EVENTS.map((e) => `${e.replace("_events", "")} ${a.arrived_late![e]}`).join(", ") : "none"}</dd>
      </dl>
      <figure className="figure">
        <Timeline events={events} start={sec(obs - daysUs(10))} cutoff={sec(pa)} end={sec(pa + daysUs(14))} caption={`Events of account ${String(c["account_id"])} around the cutoff ${day(c["prediction_at"])}; hollow circles arrived after the cutoff`} />
        <figcaption>Time runs left to right from ten days before the observation window to fourteen days after the cutoff. The vertical line is the cutoff; a hollow circle is where a late event occurred, its dashed line runs to where it became available.</figcaption>
      </figure>
      <TableFold summary="Every event in the picture, as a table">
        <Scroll label="Events around the cutoff">
          <table data-testid="lineage-events">
            <caption>Ordered by event time, then id. "used" counts toward the features; "arrived late" occurred in the window but was available at or after the cutoff.</caption>
            <thead><tr><th scope="col">Event</th><th scope="col">Kind</th><th scope="col">Detail</th><th scope="col">Occurred (event_at)</th><th scope="col">Available (available_at)</th><th scope="col">Treatment</th></tr></thead>
            <tbody>{rows.map((r) => { const st = status(r); return (
              <tr key={r.id} data-status={st}><td className="l">{r.id}</td><td className="t">{r.lane}</td><td className="t">{r.detail}</td><td>{isoZ(r.at)}</td><td>{isoZ(r.avail)}</td>
                <td className="t">{st === "used" ? <Chip kind="ok">used</Chip> : st === "late" ? <Chip kind="risk">arrived late, excluded</Chip> : <Chip kind="hatch">outside the window</Chip>}</td></tr>); })}</tbody>
          </table>
        </Scroll>
      </TableFold>
      <Scroll label="Feature values">
        <table data-testid="lineage-features">
          <caption>The four registered features, rebuilt here from the events, against the stored row and against what they would be if availability were ignored.</caption>
          <thead><tr><th scope="col">Feature</th><th scope="col">Rebuilt here</th><th scope="col">Stored feature row</th><th scope="col">If available_at were ignored</th></tr></thead>
          <tbody>{FEATURES.map((f) => { const v = a.features?.[f]; const st = stored?.[f]; const ig = ignoring[f]; return (
            <tr key={f} data-feature={f}><td className="l">{f}</td><td data-k="rebuilt">{v === null || v === undefined ? "— (missing)" : String(v)}</td>
              <td data-k="stored">{st === undefined ? "— (no stored row)" : st === null ? "— (missing)" : String(st)} {stored ? (JSON.stringify(st ?? null) === JSON.stringify(v ?? null) ? <Chip kind="ok">same</Chip> : <Chip kind="risk">differs</Chip>) : null}</td>
              <td data-k="ignoring">{ig === null ? "— (missing)" : String(ig)} {JSON.stringify(ig ?? null) !== JSON.stringify(v ?? null) ? <Chip kind="risk">would change</Chip> : <Chip kind="hatch">unchanged</Chip>}</td></tr>); })}</tbody>
        </table>
      </Scroll>
    </section>
  );
}

function Features({ ds }: { ds: Dataset }) {
  const reg = ds.primary.world.acc.feature_registry;
  const rows = ds.cutoffRows();
  const dr4 = ds.manifest ? (ds.manifest["designed_relationships"] as Row[]).find((d) => d["id"] === "DR-04")?.["realised"] as Row | undefined : undefined;
  const lateTotal = rows.reduce((s, r) => s + r.late_total, 0);
  const withProps = rows.filter((r) => r.eligible > 0);
  const nBad = ds.primary.world.acc.feature_rows.filter((f) => f["max_available_at"] !== null && parseTs(f["max_available_at"]) >= parseTs(ds.primary.world.cutoffs.get(f["cutoff_id"])!["prediction_at"])).length;
  return (
    <>
      <ViewHead mark="03 · Features" title="Feature evidence" contracts="P10-FLOW-01, P10-TEST-01, P10-TEST-02, P10-TEST-08, P10-TEST-12, P10-MET-10, D-01, D-05 (D-P10-05..07)">
        <p className="lede">A feature must be knowable at the cutoff. Four features are built, each from events that happened in the observation window <em>and</em> were available before the cutoff; seven more registered fields are refused, and each refusal has a reason.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["feature version", ds.primary.world.featureVersion], ["observation window", `${ds.primary.world.obsDays} days before each cutoff, [start, cutoff)`], ["rule", "event_at in the window and available_at before the cutoff"]]} />
      <section className="paper" aria-labelledby="proof-h">
        <h2 id="proof-h">The availability proof</h2>
        <p>Every stored feature row records <code>max_available_at</code>, the latest <code>available_at</code> of any event it used. In this dataset <Fig k="proof-rows">{n0(ds.primary.world.acc.feature_rows.length)}</Fig> feature rows are published and <Fig k="proof-bad">{n0(nBad)}</Fig> of them used an event available at or after their cutoff. Across the {n0(rows.length)} cutoffs {n0(lateTotal)} events that occurred earlier but arrived after the cutoff were excluded and counted ({Math.max(...rows.map((r) => r.late_total))} at most in one cutoff).</p>
        {dr4 && <p>If availability were ignored, at least one feature would change on <Fig k="dr4-share">{String(dr4["share_of_test_rows_changed"])}</Fig> of the test rows ({n0(Number(dr4["test_rows_features_change_if_ignored"]))} of {n0(Number(dr4["test_rows"]))}); the counts by feature are in the evidence page. <Chip kind="note">full-world figure from the manifest</Chip></p>}
      </section>
      <section aria-labelledby="reg-h">
        <h2 id="reg-h">The feature registry</h2>
        <Scroll label="Feature registry">
          <table data-testid="registry">
            <caption>All registered fields of feature version {ds.primary.world.featureVersion}, in registry order. A field is usable only when it is neither post-outcome, latent nor identifier-derived.</caption>
            <thead><tr><th scope="col">Field</th><th scope="col">Source</th><th scope="col">Window (days)</th><th scope="col">Status</th><th scope="col">Why</th></tr></thead>
            <tbody>{reg.map((r) => { const code = classifyFeature(ds.primary.world.registry, r["feature_name"]); return (
              <tr key={r["feature_name"]} data-feature={r["feature_name"]}><td className="l">{r["feature_name"]}</td><td className="t">{r["source_entity"]}</td><td>{r["window_days"] ?? "—"}</td>
                <td className="t">{code ? <Chip kind="risk">refused {code}</Chip> : <Chip kind="ok">built</Chip>}</td><td className="t">{code ? REFUSAL_WORDS[code] : `a count or total over ${r["window_days"]} days of ${r["source_entity"].replace("_", " ")}`}</td></tr>); })}</tbody>
          </table>
        </Scroll>
      </section>
      <RequestChecker ds={ds} />
      <Lineage ds={ds} />
      <section aria-labelledby="late-h">
        <h2 id="late-h">What arrived late, by cutoff</h2>
        <figure className="figure">
          <LineSeries labels={withProps.map((r) => r.prediction_at.slice(0, 7))} series={[{ key: "late", label: "arrived-late events per eligible row", color: "#ef7a6a", values: withProps.map((r) => p6(ratio(r.late_total, r.eligible))) }]} caption="Events that arrived after their cutoff, per eligible row, by monthly cutoff" testid="late-chart" />
          <figcaption>Events that occurred inside the window but were available only after the cutoff, divided by the eligible rows of that cutoff. Unit: events per row.</figcaption>
        </figure>
        <Legend items={[{ label: "arrived late per eligible row", color: "#ef7a6a" }]} />
        <TableFold summary="The same figures as a table" open={false}>
          <Scroll label="Arrived-late events by cutoff">
            <table data-testid="late-table"><caption>Counts over eligible rows; usage, billing, support and subscription events.</caption>
              <thead><tr><th scope="col">Cutoff</th><th scope="col">Eligible rows</th><th scope="col">Arrived late (events)</th><th scope="col">Per row</th></tr></thead>
              <tbody>{withProps.map((r) => <tr key={r.prediction_at}><td className="l">{day(r.prediction_at)}</td><td>{n0(r.eligible)}</td><td>{n0(r.late_total)}</td><td>{orDash(p6(ratio(r.late_total, r.eligible)))}</td></tr>)}</tbody></table>
          </Scroll>
        </TableFold>
        <p><Def term="Why not use them anyway?">At the cutoff those events were not yet in the data. A model trained on them would see tomorrow's data, score well on a back-test and fail in use.</Def> <Link to="monitoring">Monitoring</Link> tracks missing values and drift of the features over time.</p>
      </section>
      <Related also={["monitoring", "models"]} />
    </>
  );
}
