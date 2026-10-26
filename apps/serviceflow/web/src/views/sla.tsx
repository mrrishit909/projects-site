import { useMemo } from "react";
import { ViewHead } from "../components/layout";
import { Gate } from "../components/status";
import { Definition, Panel, Readout, RULES, V } from "../components/ui";
import { tails } from "../domain/extras";
import { computeMetrics, groupMetrics, groupValues } from "../domain/metrics";
import { isoZ } from "../domain/time";
import type { Metrics, Window } from "../domain/types";
import { ratioToPct } from "../lib/format";
import { useParam } from "../router";
import type { Ready } from "../state/store";

const WINDOW_LABEL: Record<string, string> = { full: "Full window", training: "Training, weeks 1-8", holdout: "Holdout, weeks 9-12" };
const width = (within: number, eligible: number): string => `${eligible === 0 ? 0 : Math.round((within * 1000) / eligible) / 10}%`;

export function Sla() {
  return (
    <article>
      <ViewHead eyebrow="Entry route" title="SLA review">
        <p className="lede">Compliance with the first-response and resolution targets, by priority. Tickets that are still open and already past their resolution target are counted in their own column and never dropped; every mean has its P90 beside it.</p>
      </ViewHead>
      <Gate>{(s) => <Body s={s} />}</Gate>
    </article>
  );
}

function Body({ s }: { s: Ready }) {
  const [win, setWin] = useParam("window", "full");
  const avail = (["full", "training", "holdout"] as const).filter((k) => s.windows[k] !== null);
  const wkey = avail.includes(win as never) ? (win as "full" | "training" | "holdout") : "full";
  const w = s.windows[wkey] as Window;
  const pop = s.result.population, hist = s.result.histories, ab = s.result.abandonable;
  const cut = useMemo(() => [w[1]], [w]);
  const all = useMemo(() => computeMetrics(pop, w, cut, ab, hist), [pop, w, cut, ab, hist]);
  const byP = useMemo(() => groupMetrics(pop, "priority", w, cut, ab, hist), [pop, w, cut, ab, hist]);
  const ids = useMemo(() => groupValues(pop, "priority", hist), [pop, hist]);
  const tl = useMemo(() => Object.fromEntries(["P1", "P2", "P3", "all"].map((p) => [p, tails(pop.tickets, hist, w, p === "all" ? null : ids.get(p) ?? new Set())])), [pop, hist, w, ids]);
  const policy = new Map(pop.sla_policies.map((p) => [p.priority, p] as const));
  const rows: [string, Metrics][] = [...["P1", "P2", "P3"].filter((p) => byP[p]).map((p): [string, Metrics] => [p, byP[p]!]), ["all", all]];
  const compare = (["training", "holdout"] as const).filter((k) => s.windows[k] !== null).map((k) => [k, computeMetrics(pop, s.windows[k] as Window, [(s.windows[k] as Window)[1]], ab, hist)] as const);

  return (
    <>
      <form className="toolbar" aria-label="SLA settings" onSubmit={(e) => e.preventDefault()}>
        <fieldset className="seg">
          <legend>Window</legend>
          {avail.map((k) => <label key={k} className={wkey === k ? "is-on" : ""}><input type="radio" name="sla-window" value={k} checked={wkey === k} onChange={() => setWin(k)} />{WINDOW_LABEL[k]}</label>)}
        </fieldset>
      </form>
      <p className="summary">Window [{isoZ(w[0])}, {isoZ(w[1])}). Targets are wall clock (calendar cal-001, 24x7): {["P1", "P2", "P3"].filter((p) => policy.has(p)).map((p) => `${p} ${policy.get(p)!.first_response_minutes} / ${policy.get(p)!.resolution_minutes} min`).join("; ")} (first response / resolution).</p>

      <dl className="readouts" aria-label="All tickets" data-testid="sla-headline">
        <Readout id="sla_fr" label="First-response compliance" value={ratioToPct(all.sla_first_response_compliance)} note={`${all.sla_first_response_within} of ${all.sla_first_response_eligible} eligible`} />
        <Readout id="sla_rs" label="Resolution compliance" value={ratioToPct(all.sla_resolution_compliance)} note={`${all.sla_resolution_within} of ${all.sla_resolution_eligible} completed`} />
        <Readout id="sla_overdue" label="Open overdue, separately" value={all.open_overdue_at_cutoff} note="still open and past the resolution target; not in the ratio above" tone="alert" />
      </dl>

      <Panel title="By priority" id="sla-by-priority">
        <div className="table-wrap" tabIndex={0} role="region" aria-label="SLA table, scrolls sideways on narrow screens">
          <table className="grid-table sla" data-testid="sla-table">
            <caption className="sr-only">SLA compliance by priority for the {WINDOW_LABEL[wkey]}</caption>
            <thead>
              <tr><th rowSpan={2} scope="col">Priority</th><th colSpan={5} scope="colgroup" className="grp">First response</th><th colSpan={5} scope="colgroup" className="grp">Resolution</th><th rowSpan={2} scope="col" className="num grp-alert">Open overdue</th></tr>
              <tr>
                <th scope="col" className="num">Within / eligible</th><th scope="col">Compliance</th><th scope="col" className="num">Mean (min)</th><th scope="col" className="num">P90 (min)</th><th scope="col" className="num">P90 / mean</th>
                <th scope="col" className="num">Within / eligible</th><th scope="col">Compliance</th><th scope="col" className="num">Mean (min)</th><th scope="col" className="num">P90 (min)</th><th scope="col" className="num">P90 / mean</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([p, m]) => (
                <tr key={p} data-priority={p} className={p === "all" ? "is-total" : ""}>
                  <th scope="row">{p === "all" ? "All priorities" : p}{p !== "all" && policy.has(p) ? <span className="sub">{policy.get(p)!.first_response_minutes} / {policy.get(p)!.resolution_minutes} min</span> : null}</th>
                  <td className="num">{m.sla_first_response_within} / {m.sla_first_response_eligible}</td>
                  <td><Bar within={m.sla_first_response_within} eligible={m.sla_first_response_eligible} text={ratioToPct(m.sla_first_response_compliance)} /></td>
                  <td className="num"><V v={m.mean_first_response_minutes} /></td>
                  <td className="num"><V v={m.p90_first_response_minutes} /></td>
                  <td className="num"><V v={tl[p]!.first_response.p90_over_mean} /></td>
                  <td className="num">{m.sla_resolution_within} / {m.sla_resolution_eligible}</td>
                  <td><Bar within={m.sla_resolution_within} eligible={m.sla_resolution_eligible} text={ratioToPct(m.sla_resolution_compliance)} /></td>
                  <td className="num"><V v={m.mean_resolution_minutes} /></td>
                  <td className="num"><V v={tl[p]!.resolution.p90} /></td>
                  <td className="num"><V v={tl[p]!.resolution.p90_over_mean} /></td>
                  <td className="num alert" data-cell="overdue">{m.open_overdue_at_cutoff}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small">The first-response P90 is a contract metric for all tickets; the P90 of each priority and of resolution are additions computed from the same populations with the same nearest-rank rule. A ratio is "no value" when nothing was eligible, never 0.</p>
      </Panel>

      {compare.length === 2 && (
        <Panel title="Training against holdout" id="sla-compare">
          <p className="panel__note">The holdout weeks arrive harder by design; a change is reported, not hidden (D-04).</p>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Training against holdout, scrolls sideways on narrow screens">
            <table className="grid-table" data-testid="sla-compare-table">
              <thead><tr><th scope="col">Window</th><th scope="col" className="num">Arrivals</th><th scope="col">First-response compliance</th><th scope="col" className="num">P90 first response (min)</th><th scope="col">Resolution compliance</th><th scope="col" className="num">Open overdue</th></tr></thead>
              <tbody>{compare.map(([k, m]) => (
                <tr key={k}><th scope="row">{WINDOW_LABEL[k]}</th><td className="num">{m.arrival_count}</td><td><V v={ratioToPct(m.sla_first_response_compliance)} /></td><td className="num"><V v={m.p90_first_response_minutes} /></td><td><V v={ratioToPct(m.sla_resolution_compliance)} /></td><td className="num">{m.open_overdue_at_cutoff}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </Panel>
      )}
      <Definition items={[RULES.sla, RULES.p90, RULES.firstResponse, RULES.resolution, RULES.window]} />
    </>
  );
}

function Bar({ within, eligible, text }: { within: number; eligible: number; text: string | null }) {
  return (
    <span className="bar2" title={eligible === 0 ? "nothing eligible" : `${within} of ${eligible}`}>
      <span className="bar2__track" aria-hidden="true"><span className="bar2__fill" style={{ width: width(within, eligible) }} /></span>
      <span className="bar2__text"><V v={text} /></span>
    </span>
  );
}
