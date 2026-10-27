import { useState } from "react";
import { Chip, PlateHead, Scroll, SimNote, WithData } from "../components/ui";
import { scenarioIds } from "../components/pick";
import type { Dataset } from "../data/dataset";
import type { Row } from "../domain/contract";
import { cmp } from "../domain/num";
import { group } from "../lib/format";
import { COST_PCTS, pctText, RAMPS, RATE_GRID, simulate } from "../lib/simulate";
import { defaultScenario } from "../lib/derive";
import { setSensitivity, useSensitivity, type SensitivitySettings } from "../state/sim";

export function SensitivityView() {
  return <WithData>{(ds) => <Lab ds={ds} />}</WithData>;
}

function defaults(ds: Dataset): SensitivitySettings {
  const scenario = defaultScenario(ds);
  const ids = Object.keys(ds.metrics["scenarios"][scenario]["initiatives"]).sort(cmp);
  const initiative = ids.includes("init-003") ? "init-003" : ids.includes("init-001") ? "init-001" : (ids[0] ?? "");
  const sc = ds.byId.scenarios.get(scenario);
  return { initiative, scenario, rate: sc ? pctText(sc["discount_rate"]) : "8", basis: (sc?.["rate_basis"] ?? "annual") as "annual" | "monthly", ramp: "planned", costPct: 0, raw: false };
}

const pb = (p: Row): string => (p["period"] === null ? "never (null)" : `${p["period"]} (${p["interpolated"]})`);

function Lab({ ds }: { ds: Dataset }) {
  const stored = useSensitivity();
  const s = stored ?? defaults(ds);
  const [touched, setTouched] = useState(false);
  const set = (patch: Partial<SensitivitySettings>): void => { setTouched(true); setSensitivity({ ...s, ...patch }); };
  const ids = Object.keys(ds.metrics["scenarios"][s.scenario]?.["initiatives"] ?? {}).sort(cmp);
  const out = simulate(ds, s);
  const periodBasis = String(ds.result.population.config["period_basis"]);
  return (
    <>
      <PlateHead mark="Plate IV" title="Sensitivity lab">
        <p className="lede">Change the discount rate, the adoption ramp or the cost of one initiative and watch the exact NPV and both paybacks move. The same domain code runs; only the inputs differ.</p>
      </PlateHead>
      <SimNote>Every control here is a simulation in browser memory. It reloads to the published figures, saves nothing, proposes nothing and changes no scenario: scenarios are immutable, and an edit would be a new scenario.</SimNote>
      <form className="controls" onSubmit={(e) => e.preventDefault()} aria-label="Sensitivity settings" data-testid="lab-controls">
        <label>Scenario<select value={s.scenario} onChange={(e) => { const sc = e.target.value; const ii = Object.keys(ds.metrics["scenarios"][sc]["initiatives"]).sort(cmp); const row = ds.byId.scenarios.get(sc)!; set({ scenario: sc, initiative: ii.includes(s.initiative) ? s.initiative : ii[0]!, rate: pctText(row["discount_rate"]), basis: row["rate_basis"] }); }} data-testid="lab-scenario">{scenarioIds(ds).map((id) => <option key={id}>{id}</option>)}</select></label>
        <label>Initiative<select value={s.initiative} onChange={(e) => set({ initiative: e.target.value })} data-testid="lab-initiative">{ids.map((id) => <option key={id} value={id}>{id} {ds.byId.initiatives.get(id)!["title"]}</option>)}</select></label>
        <label>Discount rate, percent<input type="text" inputMode="decimal" value={s.rate} onChange={(e) => set({ rate: e.target.value })} data-testid="lab-rate" aria-describedby="rate-help" size={7} /></label>
        <label>Rate is<select value={s.basis} onChange={(e) => set({ basis: e.target.value as "annual" | "monthly" })} data-testid="lab-basis"><option value="annual">annual</option><option value="monthly">monthly</option></select></label>
        <label style={{ display: "flex", gap: ".4rem", alignItems: "center" }}><input type="checkbox" checked={s.raw} onChange={(e) => set({ raw: e.target.checked })} data-testid="lab-raw" />Apply the rate as it stands, without a conversion</label>
        <fieldset className="picker" data-testid="lab-ramp"><legend>Adoption ramp</legend><div className="picker__row">{RAMPS.map((r) => <label key={r.value} className={`picker__opt${s.ramp === r.value ? " is-on" : ""}`}><input type="radio" name="ramp" checked={s.ramp === r.value} onChange={() => set({ ramp: r.value })} /><span>{r.label}</span></label>)}</div></fieldset>
        <fieldset className="picker" data-testid="lab-cost"><legend>Planned costs</legend><div className="picker__row">{COST_PCTS.map((c) => <label key={c} className={`picker__opt${s.costPct === c ? " is-on" : ""}`}><input type="radio" name="cost" checked={s.costPct === c} onChange={() => set({ costPct: c })} /><span>{c > 0 ? `+${c}` : c} %</span></label>)}</div></fieldset>
        <button type="button" className="button--quiet" onClick={() => { setSensitivity(null); setTouched(false); }} data-testid="lab-reset">Reset to the published scenario</button>
      </form>
      <p id="rate-help" className="small muted">Periods are {periodBasis}. A rate on a different basis is never applied raw: an annual rate on monthly periods is converted exactly, as (1 + r)^(1/12) − 1 to 6 places, and recorded as its own assumption; ticking the box shows the refusal instead.</p>
      <section aria-labelledby="h-res" data-testid="lab-result" aria-live="polite">
        <h2 id="h-res">Result {touched ? <Chip kind="note">simulated</Chip> : <Chip kind="plain">as published</Chip>}</h2>
        {!out.ok ? (
          <div className="notice notice--bad" role="alert" data-testid="lab-refusal"><strong className="refused">Refused {out.code}.</strong> {out.message}</div>
        ) : (
          <>
            <dl className="facts">
              <div><dt>NPV (USD)</dt><dd data-figure="lab-npv">{group(out.npv)}</dd></div>
              <div><dt>NPV exact</dt><dd data-figure="lab-npv-exact" className="wrapcell">{out.npvExact ?? "n/a"}</dd></div>
              <div><dt>Published NPV</dt><dd data-figure="lab-published">{group(out.published)}</dd></div>
              <div><dt>Change from published</dt><dd data-figure="lab-delta">{group(out.delta)}</dd></div>
              <div><dt>Simple payback</dt><dd data-figure="lab-simple">{pb(out.simple)}</dd></div>
              <div><dt>Discounted payback</dt><dd data-figure="lab-discounted">{pb(out.discounted)}</dd></div>
            </dl>
            <p className="small muted" data-testid="lab-ratenote">Rate: {out.rateNote}. Ramp: {out.ramp ? out.ramp.join(", ") : "none planned"}. Costs {s.costPct > 0 ? "+" : ""}{s.costPct} %.</p>
          </>
        )}
      </section>
      <section aria-labelledby="h-grid">
        <h2 id="h-grid">NPV across rates and costs</h2>
        <p className="small muted">{s.initiative} in {s.scenario}, USD, with the ramp chosen above; rates are percent on the basis chosen above. The cell for the current settings is marked.</p>
        <Scroll label="NPV by rate and cost change">
          <table data-testid="lab-grid">
            <caption>NPV (USD) by rate and by change in planned cost</caption>
            <thead><tr><th>Rate, percent</th>{COST_PCTS.map((c) => <th key={c} className="num">{c > 0 ? `+${c}` : c} % cost</th>)}</tr></thead>
            <tbody>{RATE_GRID.map((r) => (
              <tr key={r}><th scope="row">{r} %</th>{COST_PCTS.map((c) => { const o = simulate(ds, s, r, c); const on = r === s.rate.trim() && c === s.costPct; return <td key={c} className={`num${on ? " is-on" : ""}${o.ok && o.npv?.startsWith("-") ? " neg" : ""}`} data-rate={r} data-cost={c} aria-current={on ? "true" : undefined}>{o.ok ? group(o.npv) : o.code}</td>; })}</tr>
            ))}</tbody>
          </table>
        </Scroll>
      </section>
    </>
  );
}
