import { useEffect, useMemo, useState } from "react";
import { ViewHead } from "../components/layout";
import { ErrorState, Gate, Loading } from "../components/status";
import { Definition, Panel, V } from "../components/ui";
import { loadSimReference, loadSnapshot, dataUrl, type SimReference } from "../data/load";
import { holdoutReport } from "../domain/extras";
import { d4f, type Frac } from "../domain/fixed";
import { computeMetrics } from "../domain/metrics";
import { comparePolicies, goldenShape, meanCi95, meanWait, replicate, replicationReport, simulate, statistics, waitsOf, type SimulationResult } from "../domain/simulation";
import { same } from "../lib/canon";
import { last, ratioToPct } from "../lib/format";
import type { Ready } from "../state/store";

const ESTIMATE = "Estimate from a seeded model, not an observed result.";

export function Simulation() {
  return (
    <article>
      <ViewHead eyebrow="Entry route" title="Simulation studio">
        <p className="lede">The hand-derived golden case is reproduced first, in your browser, before any random arrivals are used. Then the three published runs are re-simulated from their seed and compared with what the Python simulator produced, and you can run seeded replications of your own. Everything beyond the golden case is an estimate from a seeded model.</p>
      </ViewHead>
      <GoldenCase />
      <Gate>{(s) => <Published s={s} />}</Gate>
    </article>
  );
}

// ---- A: the golden case ---------------------------------------------------------------------------------------------
interface GoldenExpected { simulation: { simulation_id: string; waits_minutes: string[]; mean_wait_minutes: string; final_completion_minute: string; events: { simulation_event_id: string; ticket_id: string; event_type: string; event_at: string }[] } }
type GoldenState = { status: "loading" } | { status: "error"; error: string } | { status: "ready"; result: SimulationResult; expected: GoldenExpected["simulation"]; config: Record<string, unknown>; seed: number };

function GoldenCase() {
  const [g, setG] = useState<GoldenState>({ status: "loading" });
  useEffect(() => {
    let live = true;
    (async () => {
      const snap = await loadSnapshot("golden");
      if (!snap.ok) throw new Error(snap.error);
      const res = await fetch(dataUrl("expected.json", "golden"));
      if (!res.ok) throw new Error(`golden/expected.json: HTTP ${res.status}`);
      const expected = ((await res.json()) as GoldenExpected).simulation;
      const run = (snap.snapshot.inputs.simulation_runs as { simulation_id: string; seed: number; warmup_minutes: number; horizon_minutes: number; config: Record<string, unknown> }[])[0]!;
      return { status: "ready" as const, result: simulate(run.config, run.seed, run.warmup_minutes, run.horizon_minutes, run.simulation_id), expected, config: run.config, seed: run.seed };
    })().then((v) => { if (live) setG(v); }).catch((e: unknown) => { if (live) setG({ status: "error", error: e instanceof Error ? e.message : String(e) }); });
    return () => { live = false; };
  }, []);
  if (g.status === "loading") return <Loading />;
  if (g.status === "error") return <ErrorState message={g.error} />;
  const shape = goldenShape(g.result);
  const checks: [string, boolean][] = [
    ["waits 0, 10, 20 minutes", same(shape.waits_minutes, g.expected.waits_minutes)],
    ["mean wait 10 minutes", shape.mean_wait_minutes === g.expected.mean_wait_minutes],
    ["last completion at minute 30", shape.final_completion_minute === g.expected.final_completion_minute],
    ["events se-001 to se-006, each with its ticket, type and minute", same(shape.events, g.expected.events)],
  ];
  return (
    <Panel title="The golden case, computed in your browser" id="golden-case" tone="night">
      <p className="panel__note">One agent, three tickets arriving at minute 0, a deterministic 10-minute service, first in first out (P04-GOLD-01, D-04). Config: <code>{JSON.stringify(g.config)}</code>, seed {g.seed}, warm-up 0, horizon 60. Compared with the fixture's expected.json.</p>
      <dl className="readouts readouts--dark" data-testid="golden-figures">
        <div className="readout" data-figure="golden_waits"><dt>Waits</dt><dd className="readout__v">{shape.waits_minutes.join(" / ")}</dd><dd className="readout__n">minutes, in ticket order</dd></div>
        <div className="readout" data-figure="golden_mean"><dt>Mean wait</dt><dd className="readout__v"><V v={shape.mean_wait_minutes} /></dd><dd className="readout__n">minutes</dd></div>
        <div className="readout" data-figure="golden_completion"><dt>Last completion</dt><dd className="readout__v"><V v={shape.final_completion_minute} /></dd><dd className="readout__n">minute</dd></div>
        <div className="readout" data-figure="golden_events"><dt>Events</dt><dd className="readout__v" data-testid="golden-event-ids">{shape.events.map((e) => e.simulation_event_id).join(" ")}</dd><dd className="readout__n">{shape.events.length} rows</dd></div>
      </dl>
      <ul className="checks" data-testid="golden-checks">{checks.map(([label, ok]) => <li key={label} className={ok ? "ok" : "bad"}><span aria-hidden="true">{ok ? "✓" : "✗"}</span> {label}: <strong>{ok ? "equals expected.json" : "DIFFERS from expected.json"}</strong></li>)}</ul>
      <div className="table-wrap table-wrap--dark" tabIndex={0} role="region" aria-label="Golden case events, scrolls sideways on narrow screens">
        <table className="grid-table" data-testid="golden-events">
          <caption className="sr-only">Golden case simulation events</caption>
          <thead><tr><th scope="col">Event</th><th scope="col">Ticket</th><th scope="col">Type</th><th scope="col" className="num">Minute</th></tr></thead>
          <tbody>{shape.events.map((e) => <tr key={e.simulation_event_id}><th scope="row"><code>{e.simulation_event_id}</code></th><td>{e.ticket_id}</td><td>{e.event_type}</td><td className="num">{e.event_at}</td></tr>)}</tbody>
        </table>
      </div>
    </Panel>
  );
}

// ---- B and C: the published runs and seeded studio --------------------------------------------------------------------
const cfgLine = (c: Record<string, unknown>): string => {
  const mix = c.priority_mix ? Object.entries(c.priority_mix as Record<string, number>).map(([k, v]) => `${k} ${v}`).join(", ") : "P2 only";
  return `${String(c.agents)} agent${c.agents === 1 ? "" : "s"}, ${c.arrival_rate_per_hour !== undefined ? `${String(c.arrival_rate_per_hour)} arrivals per hour` : `${(c.arrivals as unknown[]).length} listed arrivals`}, ${String(c.service)} service, mean ${String(c.service_minutes)} min, ${String(c.discipline)}, mix ${mix}`;
};

function Published({ s }: { s: Ready }) {
  const [ref, setRef] = useState<SimReference | null | "error">(null);
  useEffect(() => { let live = true; loadSimReference().then((r) => live && setRef(r)).catch(() => live && setRef("error")); return () => { live = false; }; }, []);
  const runs = s.result.population.simulation_runs, sims = s.result.simulations;
  const pop = s.result.population;
  const { training, holdout } = s.windows;
  const hold = useMemo(() => {
    if (!training || !holdout) return null;
    const a = computeMetrics(pop, training, [training[1]], s.result.abandonable, s.result.histories).arrival_count;
    const b = computeMetrics(pop, holdout, [holdout[1]], s.result.abandonable, s.result.histories).arrival_count;
    return { a, b, ...holdoutReport(a, training[1] - training[0], b, holdout[1] - holdout[0]) };
  }, [pop, training, holdout, s.result]);

  return (
    <>
      <Panel title="The published runs, re-simulated with their seed" id="published-runs">
        <p className="panel__note">{ESTIMATE} Each run below is run again in this browser from its declared seed, config, warm-up and horizon, then compared event by event with the reference stored beside the site (<code>reference/simulation-runs.json</code>, produced once by the Python simulator). Warm-up observations are excluded from every statistic (P04-TEST-09); tickets still waiting at the horizon are excluded from the wait statistics and counted separately as censored (so the waits shown are of served tickets only, and a long queue makes them look better than it is). One run is one draw: the replication means with 95 % intervals are further down.</p>
        {s.snapshot.golden ? <p>The golden fixture's only run is the case above; the published runs belong to the full snapshot (open this page without <code>?dataset=golden</code>).</p> : ref === null ? <Loading /> : ref === "error" ? <ErrorState message="The stored Python reference could not be read (reference/simulation-runs.json); runs are shown without the comparison." /> : null}
        <div className="runs">
          {sims.map((r, i) => <RunCard key={r.simulation_id} r={r} run={runs[i]!} reference={ref !== null && ref !== "error" && !s.snapshot.golden ? ref.runs.find((x) => x.simulation_id === r.simulation_id) ?? null : null} />)}
        </div>
        {sims.length >= 2 && <Differences sims={sims} />}
      </Panel>

      <Replications s={s} reference={ref !== null && ref !== "error" && !s.snapshot.golden ? ref : null} />

      {hold && (
        <Panel title="Holdout check" id="holdout">
          <p className="panel__note">Arrival intensity is estimated on the training window only and compared with the holdout window; a change is reported, never hidden (D-04, P04-TEST-12).</p>
          <dl className="facts" data-testid="holdout-facts">
            <div><dt>Training, weeks 1-8</dt><dd>{hold.a} arrivals, {hold.train_rate} per hour</dd></div>
            <div><dt>Holdout, weeks 9-12</dt><dd>{hold.b} arrivals, {hold.holdout_rate} per hour</dd></div>
            <div><dt>Relative change</dt><dd data-fact="holdout-change"><V v={ratioToPct(hold.relative_change)} /> {hold.relative_change !== null && Number(hold.relative_change) > 0.1 ? "(above the 10 % tolerance: the training estimate understates the holdout)" : ""}</dd></div>
          </dl>
          <p className="small">sim-003 runs the Monday-bind technical queue at the holdout intensity ({String(runs[2]?.config.arrival_rate_per_hour ?? "n/a")} against {String(runs[0]?.config.arrival_rate_per_hour ?? "n/a")} arrivals per hour in sim-001).</p>
        </Panel>
      )}

      <Studio s={s} />
      <Definition items={[
        { name: "Seeded and reproducible", rule: "D-04", text: "Demand (arrivals, priorities, service times) comes from three independent random streams derived from the seed and is drawn before any dispatching, so two policies run on the same seed see the same demand path. Draws are rounded to 1/10000 minute and all times are exact fractions; the generator is CPython's Mersenne Twister seeded from the string, reimplemented so the browser draws the same path." },
        { name: "Horizon, warm-up and censoring", rule: "D-04, D-06, D-09", text: "Arrivals at or after the horizon are not generated and no service starts at or after it; a ticket still waiting then is censored: it is excluded from the wait statistics and counted separately, so waits are those of served tickets. Tickets arriving before the warm-up still occupy agents but are left out of every statistic." },
        { name: "Replications and the interval", rule: "D-04", text: "Replication r uses seed + r. The mean over replications carries its count and a 95 % Student-t half-width, an estimate. The browser takes the square root in exact integers at 1e-8, where Python uses a float, so the last digit can differ in rare edge cases." },
      ]} />
    </>
  );
}

// ---- replications and the paired difference (R4-11) -------------------------------------------------------------------------
const REPS = 50;
function Replications({ s, reference }: { s: Ready; reference: SimReference | null }) {
  const runs = s.result.population.simulation_runs;
  const [calc, setCalc] = useState<{ reps: Record<string, ReturnType<typeof replicationReport>>; paired: ReturnType<typeof comparePolicies> | null } | null>(null);
  useEffect(() => {
    if (runs.length === 0) return;
    const t = setTimeout(() => {
      const reps = Object.fromEntries(runs.map((r) => [r.simulation_id, replicationReport(r.config, r.seed, REPS, r.warmup_minutes, r.horizon_minutes)]));
      const [b, p] = runs;
      setCalc({ reps, paired: b && p ? comparePolicies(b.config, p.config, b.seed, REPS, b.warmup_minutes, b.horizon_minutes) : null });
    }, 0);
    return () => clearTimeout(t);
  }, [runs]);
  if (runs.length === 0) return null;
  const rr = reference?.replications ?? null;
  const agree = (a: unknown, b: unknown): boolean => same(a, b);
  const pairedRef = rr?.paired.baseline_vs_plus_one_agent ?? null;
  const strip = (x: Record<string, unknown>): Record<string, unknown> => { const { baseline: _b, proposal: _p, note: _n, ...rest } = x; return rest; };
  return (
    <Panel title={`Replication means and the paired difference (${REPS} replications)`} id="replications">
      <p className="panel__note">{ESTIMATE} One run is one draw of a random path, so its mean wait can sit far from what the policy does on average. Each run is repeated {REPS} times on seeds seed + r (r = 0 to {REPS - 1}); the table gives the mean of the replication means with a 95 % Student-t interval, computed in this browser by the TypeScript simulator and compared with the Python reference.</p>
      {calc === null ? <Loading /> : (
        <>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Replication means, scrolls sideways on narrow screens">
            <table className="grid-table" data-testid="replications-table">
              <caption className="sr-only">Mean wait over {REPS} replications for each published run</caption>
              <thead><tr><th scope="col">Run</th><th scope="col" className="num">Replications</th><th scope="col" className="num">Mean wait (min)</th><th scope="col" className="num">95 % half-width (min)</th><th scope="col" className="num">Censored (all replications)</th><th scope="col">Python reference</th></tr></thead>
              <tbody>{runs.map((r) => { const x = calc.reps[r.simulation_id]!; const want = rr?.runs[r.simulation_id]; return (
                <tr key={r.simulation_id} data-run={r.simulation_id}>
                  <th scope="row">{r.simulation_id} <span className="muted">{r.policy_version}</span></th>
                  <td className="num">{x.mean_wait_minutes.n}</td><td className="num"><V v={x.mean_wait_minutes.mean} /></td><td className="num"><V v={x.mean_wait_minutes.ci95_half_width} /></td><td className="num">{x.censored_tickets_total}</td>
                  <td data-testid={`rep-match-${r.simulation_id}`}>{want === undefined ? "none stored" : agree(x, want) ? "equal" : "DIFFERS"}</td>
                </tr>); })}</tbody>
            </table>
          </div>
          {calc.paired && runs[0] && runs[1] && (
            <dl className="facts" data-testid="paired-facts">
              <div><dt>Plus one agent ({runs[1].simulation_id}) minus baseline ({runs[0].simulation_id}), same {REPS} seeds</dt><dd data-fact="paired-diff"><V v={calc.paired.difference_mean_wait_minutes.mean} unit=" min" /> <span className="muted">± <V v={calc.paired.difference_mean_wait_minutes.ci95_half_width} unit=" min" /> (95 %, {calc.paired.paired_replications} paired replications)</span></dd></div>
              <div><dt>Same demand path in every pair</dt><dd data-fact="paired-same">{calc.paired.same_demand_paths ? "yes: same seed and arrival rate, only the number of agents differs" : "no"}</dd></div>
              <div><dt>Python reference</dt><dd data-fact="paired-match">{pairedRef === null ? "none stored" : agree(strip(calc.paired as unknown as Record<string, unknown>), strip(pairedRef as unknown as Record<string, unknown>)) ? "equal" : "DIFFERS"}</dd></div>
            </dl>
          )}
        </>
      )}
      <ul className="small" data-testid="replication-caveats">
        <li><strong>sim-003 does not share the demand path, by design.</strong> It runs the holdout arrival intensity, so even on the same seed its arrivals differ from sim-001 and sim-002; it is a stress case, not a policy comparison. Only the paired difference above (same seed, same intensity, one more agent) isolates a policy effect.</li>
        <li><strong>Dedicated servers are a simplification.</strong> The model gives the technical queue five dedicated agents. In the snapshot four of the five technical agents on shift at the first training Monday bind also hold another queue's skill, and about 29 % of the handling minutes started in the Monday 09:00 to 11:00 bind of the training weeks by technical-skilled agents went to other queues (docs/uat-evidence.md, R4-11). The simulated wait is therefore an optimistic picture of that queue.</li>
        <li><strong>Censored tickets are excluded</strong> from the wait statistics and counted separately in the table above.</li>
      </ul>
    </Panel>
  );
}

function RunCard({ r, run, reference }: { r: SimulationResult; run: { policy_version: string; config: Record<string, unknown>; seed: number; warmup_minutes: number; horizon_minutes: number }; reference: SimReference["runs"][number] | null }) {
  const st = statistics(r), g = goldenShape(r);
  const ref = reference;
  const eventsEqual = ref ? same(g.events, ref.golden.events) : null;
  const statsEqual = ref ? same({ w: g.waits_minutes, m: g.mean_wait_minutes, c: g.final_completion_minute, s: st }, { w: ref.golden.waits_minutes, m: ref.golden.mean_wait_minutes, c: ref.golden.final_completion_minute, s: ref.statistics }) : null;
  return (
    <section className="run" data-testid={`run-${r.simulation_id}`} aria-labelledby={`${r.simulation_id}-h`}>
      <h3 id={`${r.simulation_id}-h`} className="h3">{r.simulation_id} <span className="muted">{run.policy_version}</span></h3>
      <p className="small">{cfgLine(run.config)}; seed {run.seed}, warm-up {run.warmup_minutes} min, horizon {run.horizon_minutes} min.</p>
      <dl className="facts facts--tight">
        <div><dt>Mean wait</dt><dd data-fact="mean-wait"><V v={g.mean_wait_minutes} unit=" min" /></dd></div>
        <div><dt>P90 wait</dt><dd data-fact="p90-wait"><V v={st.p90_wait_minutes} unit=" min" /></dd></div>
        <div><dt>Longest wait</dt><dd><V v={st.max_wait_minutes} unit=" min" /></dd></div>
        <div><dt>Tickets generated / counted</dt><dd>{st.tickets_generated} / {st.tickets_counted} ({st.warmup_excluded} in the warm-up)</dd></div>
        <div><dt>Censored at the horizon</dt><dd>{st.censored_at_horizon}</dd></div>
        <div><dt>Last completion</dt><dd><V v={g.final_completion_minute} unit=" min" /></dd></div>
        <div><dt>Events</dt><dd>{g.events.length} ({g.events[0]?.simulation_event_id} to {last(g.events)?.simulation_event_id})</dd></div>
      </dl>
      <p className={`match ${eventsEqual === null ? "" : eventsEqual && statsEqual ? "ok" : "bad"}`} data-testid={`match-${r.simulation_id}`}>
        {eventsEqual === null ? "No stored reference to compare with." : eventsEqual && statsEqual ? `All ${g.events.length} events, the waits and the statistics equal the stored Python reference.` : "DIFFERS from the stored Python reference."}
      </p>
    </section>
  );
}

function Differences({ sims }: { sims: SimulationResult[] }) {
  const path = (r: SimulationResult): unknown => r.served.map((x) => [d4f(x.demand.arrival), x.demand.priority]);
  const rows = sims.map((r) => ({ r, st: statistics(r) }));
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Runs side by side, scrolls sideways on narrow screens">
      <table className="grid-table" data-testid="runs-table">
        <caption className="sr-only">The three published runs side by side</caption>
        <thead><tr><th scope="col">Run</th><th scope="col" className="num">Mean wait (min)</th><th scope="col" className="num">P90 wait (min)</th><th scope="col" className="num">Counted</th><th scope="col" className="num">Censored</th><th scope="col">P1 / P2 / P3 mean wait (min)</th><th scope="col">Same demand path as {sims[0]!.simulation_id}</th></tr></thead>
        <tbody>{rows.map(({ r, st }) => (
          <tr key={r.simulation_id}>
            <th scope="row">{r.simulation_id}</th>
            <td className="num"><V v={d4f(meanWait(r))} /></td><td className="num"><V v={st.p90_wait_minutes} /></td><td className="num">{st.tickets_counted}</td><td className="num">{st.censored_at_horizon}</td>
            <td>{["P1", "P2", "P3"].map((p) => st.wait_by_priority[p]?.mean_wait_minutes ?? "no value").join(" / ")}</td>
            <td>{r === sims[0] ? "(baseline)" : same(path(r), path(sims[0]!)) ? "yes: same seed and arrival rate, only the policy differs" : "no: a different intensity, so a different path"}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

// ---- C: your own seeded runs ----------------------------------------------------------------------------------------------
function Studio({ s }: { s: Ready }) {
  const runs = s.result.population.simulation_runs;
  const [base, setBase] = useState(runs[0]?.simulation_id ?? "");
  const [seed, setSeed] = useState(String(runs[0]?.seed ?? 1));
  const [agents, setAgents] = useState(String(runs[0]?.config.agents ?? 1));
  const [reps, setReps] = useState("10");
  const [cold, setCold] = useState(false);
  const [out, setOut] = useState<{ results: SimulationResult[]; label: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = (): void => {
    try {
      const b = runs.find((x) => x.simulation_id === base);
      if (!b) throw new Error("no run selected");
      const n = Math.max(1, Math.min(30, Math.floor(Number(reps))));
      const a = Math.max(1, Math.min(50, Math.floor(Number(agents))));
      const sd = Number(seed);
      if (!Number.isInteger(sd)) throw new Error("the seed must be an integer");
      const results = replicate({ ...b.config, agents: a }, sd, n, cold ? 0 : b.warmup_minutes, b.horizon_minutes, `${b.simulation_id}-studio`);
      setErr(null);
      setOut({ results, label: `${b.simulation_id} config with ${a} agent${a === 1 ? "" : "s"}, seeds ${sd} to ${sd + n - 1}${cold ? ", warm-up counted" : `, warm-up ${b.warmup_minutes} min excluded`}` });
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  useEffect(run, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (runs.length === 0) return null;
  const ci = out ? meanCi95(out.results.map((r) => meanWait(r)).filter((x): x is Frac => x !== null)) : null;

  return (
    <Panel title="Seeded runs of your own" id="studio">
      <p className="panel__note">{ESTIMATE} Change the seed or the number of agents and run again; the same inputs always give the same numbers. Nothing is stored.</p>
      <form className="toolbar" onSubmit={(e) => { e.preventDefault(); run(); }} aria-label="Seeded run settings">
        <div className="field"><label htmlFor="sim-base">Start from</label>
          <select id="sim-base" value={base} onChange={(e) => { setBase(e.target.value); const b = runs.find((x) => x.simulation_id === e.target.value); if (b) { setSeed(String(b.seed)); setAgents(String(b.config.agents)); } }}>
            {runs.map((r) => <option key={r.simulation_id} value={r.simulation_id}>{r.simulation_id} {r.policy_version}</option>)}
          </select></div>
        <div className="field"><label htmlFor="sim-seed">Seed</label><input id="sim-seed" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} /></div>
        <div className="field"><label htmlFor="sim-agents">Agents (1 to 50)</label><input id="sim-agents" type="number" min={1} max={50} value={agents} onChange={(e) => setAgents(e.target.value)} /></div>
        <div className="field"><label htmlFor="sim-reps">Replications (1 to 30)</label><input id="sim-reps" type="number" min={1} max={30} value={reps} onChange={(e) => setReps(e.target.value)} /></div>
        <div className="field field--check"><label><input type="checkbox" checked={cold} onChange={(e) => setCold(e.target.checked)} /> Count the warm-up (INJ-07, not recommended)</label></div>
        <div className="field field--action"><button type="submit" className="btn btn--primary" data-testid="run-sim">Run</button></div>
      </form>
      {err && <p className="notice notice--error" role="alert">{err}</p>}
      {out && ci && (
        <div data-testid="studio-result">
          <p className="summary">{out.label}. {ESTIMATE}</p>
          <dl className="facts">
            <div><dt>Replications</dt><dd data-fact="reps">{ci.n}</dd></div>
            <div><dt>Mean wait over replications</dt><dd data-fact="studio-mean"><V v={ci.mean} unit=" min" /></dd></div>
            <div><dt>95 % interval half-width</dt><dd data-fact="studio-ci"><V v={ci.ci95_half_width === null ? null : `± ${ci.ci95_half_width}`} unit=" min" /></dd></div>
          </dl>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Replications, scrolls sideways on narrow screens">
            <table className="grid-table" data-testid="studio-table">
              <caption className="sr-only">Replications</caption>
              <thead><tr><th scope="col">Seed</th><th scope="col" className="num">Counted</th><th scope="col" className="num">Censored</th><th scope="col" className="num">Mean wait (min)</th><th scope="col" className="num">P90 wait (min)</th></tr></thead>
              <tbody>{out.results.map((r) => { const st = statistics(r); return (
                <tr key={r.seed}><th scope="row">{r.seed}</th><td className="num">{st.tickets_counted}</td><td className="num">{st.censored_at_horizon}</td><td className="num"><V v={d4f(meanWait(r))} /></td><td className="num"><V v={st.p90_wait_minutes} /></td></tr>
              ); })}</tbody>
            </table>
          </div>
          <p className="small muted">Waits per replication are measured from arrival to the start of service; {waitsOf(out.results[0]!).length} counted waits in the first replication.</p>
        </div>
      )}
    </Panel>
  );
}
