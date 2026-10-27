// The two principal representations: the funnel (sample sizes, control beside treatment) and the cohort grid (signup week by day,
// maturity-aware: a cell whose day has not completed is blank, never zero), plus the interval-against-zero strip.
import type { ExperimentOut, FunnelOut, GridColumn, GridRow, SignupOut } from "../domain/metrics";
import { barWidth, minus, n0, pct } from "../lib/format";

/** Visitors -> signup -> activation as the funnel definition counts them (one visitor key per unit, strict order, maximum gap). */
export function VisitorFunnel({ funnel, signup }: { funnel: FunnelOut; signup: SignupOut }) {
  return (
    <figure className="funnel" data-testid="visitor-funnel">
      <figcaption>Visitor funnel: {funnel.steps.map((s) => s.step).join(" → ")}; window {funnel.window.from.slice(0, 10)} to {funnel.window.to.slice(0, 10)} (half-open), gap up to {funnel.max_gap_hours} h, strict order.</figcaption>
      <ol>
        {funnel.steps.map((s, i) => (
          <li key={s.step} data-step={s.step}>
            <div className="funnel__label"><span className="funnel__name">{s.step.replace(/_/g, " ")}</span><span className="funnel__n mono"><span data-k="units">{n0(s.units)}</span> visitors</span></div>
            <div className="bar" role="img" aria-label={`${s.step}: ${s.units} visitors, ${pct(s.conversion_from_first)} of the first step`}>
              <span className="bar__fill bar__fill--control" style={{ width: barWidth(s.conversion_from_first) }} />
            </div>
            <div className="funnel__conv mono">{i === 0 ? "first step: the window applies here" : <>step conversion <span data-k="step-conv">{s.conversion_from_previous === null ? "n/a" : s.conversion_from_previous}</span> · of first {s.conversion_from_first === null ? "n/a" : s.conversion_from_first}</>}</div>
          </li>
        ))}
      </ol>
      <p className="funnel__foot">Signup conversion (MET-01) is measured separately on distinct anonymous ids, with no gap: {n0(signup.signed_up)} of {n0(signup.visitors)} = <span className="mono">{signup.rate ?? "n/a"}</span>. It may differ from the funnel's second step.</p>
    </figure>
  );
}

const ARMS = ["control", "treatment"] as const;
/** The experiment funnel: assigned -> mature -> activated, control beside treatment, with the sample sizes in the bars. */
export function ArmFunnel({ ex }: { ex: ExperimentOut }) {
  const stages = [
    { key: "assigned", label: "Assigned accounts", get: (v: string) => ex.primary.variants[v]!.assigned },
    { key: "mature", label: "Mature (7 days complete)", get: (v: string) => ex.primary.variants[v]!.mature_units },
    { key: "activated", label: "Activated within 7 days", get: (v: string) => ex.primary.variants[v]!.activated },
  ];
  const max = Math.max(1, ...ARMS.map((v) => ex.primary.variants[v]?.assigned ?? 0));
  return (
    <figure className="funnel funnel--arms" data-testid="arm-funnel">
      <figcaption>Experiment funnel, intention to treat: every assigned mature account counts in its assigned arm, exposed or not.</figcaption>
      <ol>
        {stages.map((st) => (
          <li key={st.key} data-stage={st.key}>
            <div className="funnel__label"><span className="funnel__name">{st.label}</span></div>
            <div className="pair">
              {ARMS.map((v) => {
                const n = ex.primary.variants[v] ? st.get(v) : 0;
                return (
                  <div key={v} className={`pair__arm pair__arm--${v}`} data-arm={v}>
                    <div className="bar" role="img" aria-label={`${v}: ${n} ${st.label.toLowerCase()}`}>
                      <span className={`bar__fill bar__fill--${v}`} style={{ width: `${((n / max) * 100).toFixed(2)}%` }} />
                    </div>
                    <p className="pair__cap mono"><span className="pair__who">{v}</span> <span data-k="n">{n0(n)}</span>{st.key === "activated" ? <> · conversion <span data-k="conv">{ex.primary.variants[v]?.conversion ?? "n/a"}</span></> : null}</p>
                  </div>
                );
              })}
            </div>
          </li>
        ))}
      </ol>
    </figure>
  );
}

/** The interval of the absolute difference against zero, on a fixed axis of -30 pp .. +30 pp (drawing only; the figures are printed). */
export function IntervalStrip({ low, high, point, label }: { low: string; high: string; point: string | null; label: string }) {
  const lim = 0.3;
  const x = (s: string): number => 50 + (Math.max(-lim, Math.min(lim, Number(s))) / lim) * 50;
  const lo = x(low), hi = x(high);
  return (
    <div className="strip-iv" role="img" aria-label={`${label}: from ${minus(low)} to ${high}, zero is ${Number(low) <= 0 && Number(high) >= 0 ? "inside" : "outside"} the interval`}>
      <svg viewBox="0 0 100 14" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" x2="100" y1="7" y2="7" className="iv-axis" />
        <line x1="50" x2="50" y1="1" y2="13" className="iv-zero" />
        <rect x={lo} y="4" width={Math.max(0.6, hi - lo)} height="6" className="iv-range" />
        {point !== null && <line x1={x(point)} x2={x(point)} y1="2" y2="12" className="iv-point" />}
      </svg>
      <div className="strip-iv__ticks mono" aria-hidden="true"><span>−30 pp</span><span>0</span><span>+30 pp</span></div>
    </div>
  );
}

const COL_LABEL: Record<string, string> = { day1: "Day 1", day7: "Day 7", day14: "Day 14", day28: "Day 28", on_or_after_day7: "Day 7 or later", week4: "Days 28 to 34" };
/** Signup week by retention day. A cell is blank when no account of the cohort has reached the day yet (immature, not zero), partial when only some have. */
export function CohortGrid({ rows, columns, weekLabel }: { rows: GridRow[]; columns: GridColumn[]; weekLabel: (key: number) => string }) {
  return (
    <div className="grid-wrap">
      <table className="cohort" data-testid="cohort-grid">
        <caption className="sr-only">Retention by local signup week and day. Blank cells are immature: the day has not yet completed for any account of the cohort.</caption>
        <thead>
          <tr><th scope="col">Signup week</th><th scope="col" className="num">Accounts</th>{columns.map((c) => <th scope="col" key={c.name}>{COL_LABEL[c.name] ?? c.name}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} data-week={weekLabel(r.key)}>
              <th scope="row" className="mono">{weekLabel(r.key)}</th>
              <td className="num mono">{r.accounts}</td>
              {columns.map((c) => {
                const cell = r.cells[c.name]!;
                const state = cell.mature_accounts === 0 ? "blank" : cell.mature_accounts < r.accounts ? "partial" : "full";
                const tint = cell.rate === null ? 0 : Math.round(Number(cell.rate) * 100);
                return (
                  <td key={c.name} data-col={c.name} data-state={state} className={`cell cell--${state}`} style={state === "blank" ? undefined : { ["--heat" as string]: `${Math.min(100, tint * 1.6)}%` }}
                    title={state === "blank" ? "Immature: this day has not completed for any account of the cohort" : `${cell.retained} of ${cell.mature_accounts} mature accounts${state === "partial" ? ` (${r.accounts - cell.mature_accounts} of ${r.accounts} not yet mature)` : ""}`}>
                    {state === "blank" ? <span className="cell__blank" aria-label="immature, not computed">{" "}</span>
                      : <><span className="cell__rate mono">{cell.rate === null ? "n/a" : pct(cell.rate).replace(" %", "")}</span><span className="cell__n mono">{cell.retained}/{cell.mature_accounts}{state === "partial" ? "*" : ""}</span></>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
