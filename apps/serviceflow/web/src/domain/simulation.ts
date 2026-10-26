// Discrete-event queue simulator (D-04). Mirrors domain/serviceflow/simulation.py: pure and deterministic, the same seed
// gives the same path as the Python reference. Times are exact fractions of a minute (random draws are rounded to
// 1/10000 minute), so the golden case reproduces to the digit.
import { d4f, fAdd, fCeil, fCmp, fDiv, fMax, fMean, fMul, fSub, fSum, fToNumber, frac, parseDecimal, ZERO, type Frac } from "./fixed";
import { PyRandom } from "./pyrandom";

export const DISCIPLINES = ["fifo", "fifo_within_priority"] as const;
export const SERVICES = ["deterministic", "exponential"] as const;
const QUANTUM = 10_000;
const CONFIG_KEYS = new Set(["agents", "service_minutes", "arrivals", "priorities", "arrival_rate_per_hour", "priority_mix", "service", "discipline"]);
export const DEFAULT_PRIORITY = "P2";
export const MAX_TICKETS = 20_000;
const PRI = ["P1", "P2", "P3"];
const T95 = ["12.706", "4.303", "3.182", "2.776", "2.571", "2.447", "2.365", "2.306", "2.262", "2.228", "2.201", "2.179", "2.160", "2.145", "2.131",
  "2.120", "2.110", "2.101", "2.093", "2.086", "2.080", "2.074", "2.069", "2.064", "2.060", "2.056", "2.052", "2.048", "2.045", "2.042",
  "2.040", "2.037", "2.035", "2.032", "2.030", "2.028", "2.026", "2.024", "2.023", "2.021", "2.020", "2.018", "2.017", "2.015", "2.014", "2.013", "2.012", "2.011", "2.010", "2.009"];

const bad = (m: string): never => { throw new Error(m); };
function num(v: unknown, name: string, o: { positive?: boolean; nonneg?: boolean } = {}): Frac {
  if (typeof v === "boolean" || (typeof v !== "number" && typeof v !== "string")) bad(`${name} must be a number`);
  const f = parseDecimal(v) ?? bad(`${name} must be a finite number`);
  if (o.positive && f.n <= 0n) bad(`${name} must be positive`);
  if (o.nonneg && f.n < 0n) bad(`${name} must not be negative`);
  return f;
}

export interface SimConfig {
  agents: number; service_minutes: Frac; arrivals: Frac[] | null; priorities: string[] | null; arrival_rate_per_hour: Frac | null;
  priority_mix: [string, Frac][]; service: string; discipline: string;
}
/** Validate a run config; throws an Error (one message) on anything unusable. */
export function parseConfig(cfg: unknown): SimConfig {
  if (cfg === null || typeof cfg !== "object" || Array.isArray(cfg)) bad("config must be an object");
  const c = cfg as Record<string, unknown>;
  const extra = Object.keys(c).filter((k) => !CONFIG_KEYS.has(k));
  if (extra.length) bad(`unknown config field(s): ${extra.sort().join(", ")}`);
  const agents: unknown = "agents" in c ? c.agents : 1;
  if (typeof agents !== "number" || !Number.isInteger(agents) || agents < 1 || agents > 1000) bad("agents must be an integer from 1 to 1000");
  if (!("service_minutes" in c)) bad("service_minutes is required");
  const svc = num(c.service_minutes, "service_minutes", { positive: true });
  const service = "service" in c ? c.service : "deterministic";
  if (!SERVICES.includes(service as never)) bad(`service must be one of ${SERVICES.join(", ")}`);
  const discipline = "discipline" in c ? c.discipline : "fifo";
  if (!DISCIPLINES.includes(discipline as never)) bad(`discipline must be one of ${DISCIPLINES.join(", ")}`);
  const arrivals = c.arrivals ?? null, rate = c.arrival_rate_per_hour ?? null;
  if ((arrivals === null) === (rate === null)) bad("give exactly one of arrivals and arrival_rate_per_hour");
  let arr: Frac[] | null = null, pri: string[] | null = null, rateF: Frac | null = null;
  if (arrivals !== null) {
    if (!Array.isArray(arrivals) || arrivals.length > MAX_TICKETS) bad(`arrivals must be a list of at most ${MAX_TICKETS} minutes`);
    arr = (arrivals as unknown[]).map((a) => num(a, "arrivals[]", { nonneg: true }));
    const p = c.priorities ?? null;
    if (p !== null) {
      if (!Array.isArray(p) || p.length !== arr.length || p.some((x) => !PRI.includes(x as string))) bad("priorities must list one of P1, P2, P3 per arrival");
      pri = p as string[];
    }
  } else rateF = num(rate, "arrival_rate_per_hour", { positive: true });
  const mixRaw = c.priority_mix ?? null;
  let mix: [string, Frac][];
  if (mixRaw === null) mix = [[DEFAULT_PRIORITY, frac(1)]];
  else {
    if (typeof mixRaw !== "object" || Array.isArray(mixRaw) || Object.keys(mixRaw).length === 0 || Object.keys(mixRaw).some((k) => !PRI.includes(k))) bad("priority_mix maps P1, P2, P3 to weights");
    mix = Object.entries(mixRaw as Record<string, unknown>).map(([k, v]): [string, Frac] => [k, num(v, "priority_mix", { nonneg: true })]).sort((a, b) => (a[0] < b[0] ? -1 : 1));
    if (fSum(mix.map((m) => m[1])).n <= 0n) bad("priority_mix needs a positive weight");
  }
  return { agents: agents as number, service_minutes: svc, arrivals: arr, priorities: pri, arrival_rate_per_hour: rateF, priority_mix: mix, service: service as string, discipline: discipline as string };
}

/** Python's round() on a float: half to even. */
function roundHalfEven(x: number): number {
  const f = Math.floor(x), d = x - f;
  return d < 0.5 ? f : d > 0.5 ? f + 1 : f % 2 === 0 ? f : f + 1;
}
const q = (x: number): Frac => frac(roundHalfEven(x * QUANTUM), QUANTUM);

export interface Demand { index: number; arrival: Frac; priority: string; service: Frac; ticket_id: string }
const tid = (i: number): string => `t-${String(i + 1).padStart(3, "0")}`;

/** The demand path of a seed: independent streams for arrivals, priorities and service times (common random numbers). */
export function buildDemand(cfg: SimConfig, seed: number, horizon: Frac): Demand[] {
  const rngA = new PyRandom(`${seed}:arrivals`), rngP = new PyRandom(`${seed}:priority`), rngS = new PyRandom(`${seed}:service`);
  let rows: [Frac, string][];
  if (cfg.arrivals !== null) {
    const arr = cfg.arrivals;
    const order = arr.map((_, i) => i).sort((a, b) => fCmp(arr[a]!, arr[b]!) || a - b);
    rows = order.map((i): [Frac, string] => [arr[i]!, cfg.priorities ? cfg.priorities[i]! : DEFAULT_PRIORITY]).filter((r) => fCmp(r[0], horizon) < 0);
  } else {
    const rateMin = fToNumber(cfg.arrival_rate_per_hour!) / 60.0;
    const names = cfg.priority_mix.map((m) => m[0]), weights = cfg.priority_mix.map((m) => fToNumber(m[1]));
    rows = [];
    let t = ZERO;
    while (rows.length < MAX_TICKETS) {
      t = fAdd(t, q(rngA.expovariate(rateMin)));
      if (fCmp(t, horizon) >= 0) break;
      rows.push([t, rngP.choice(names, weights)]);
    }
  }
  return rows.map(([arrival, priority], i) => ({
    index: i, arrival, priority, ticket_id: tid(i),
    service: cfg.service === "deterministic" ? cfg.service_minutes : fMax(q(rngS.expovariate(1.0 / fToNumber(cfg.service_minutes))), frac(1, QUANTUM)),
  }));
}

export interface Served { demand: Demand; start: Frac | null; end: Frac | null; server: number | null }
export const waitOf = (s: Served): Frac | null => (s.start === null ? null : fSub(s.start, s.demand.arrival));

/** Serve `demand` on `agents` identical servers; see the horizon rule in the Python module docstring. */
export function dispatch(demand: readonly Demand[], agents: number, discipline: string, horizon: Frac): Served[] {
  const n = demand.length;
  const rank = discipline === "fifo_within_priority" ? (d: Demand): number => PRI.indexOf(d.priority) : (): number => 0;
  const free: Frac[] = Array.from({ length: agents }, () => ZERO);
  const waiting: { r: number; a: Frac; k: number }[] = [];
  const before = (x: { r: number; a: Frac; k: number }, y: { r: number; a: Frac; k: number }): boolean => x.r !== y.r ? x.r < y.r : (fCmp(x.a, y.a) || x.k - y.k) < 0;
  const push = (it: { r: number; a: Frac; k: number }): void => {
    let lo = 0, hi = waiting.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (before(waiting[m]!, it)) lo = m + 1; else hi = m; }
    waiting.splice(lo, 0, it);
  };
  const result = new Map<number, Served>();
  let i = 0;
  for (;;) {
    const sf = free.reduce((a, b) => (fCmp(b, a) < 0 ? b : a));
    let d: Frac;
    if (waiting.length === 0) { if (i >= n) break; d = fMax(sf, demand[i]!.arrival); } else d = sf;
    while (i < n && fCmp(demand[i]!.arrival, d) <= 0) { push({ r: rank(demand[i]!), a: demand[i]!.arrival, k: i }); i++; }
    if (fCmp(d, horizon) >= 0) break;
    const { k } = waiting.shift()!;
    const j = free.findIndex((f) => fCmp(f, sf) === 0);
    const end = fAdd(d, demand[k]!.service);
    free[j] = end;
    result.set(k, { demand: demand[k]!, start: d, end, server: j });
  }
  return demand.map((dm, idx) => result.get(idx) ?? { demand: dm, start: null, end: null, server: null });
}

export interface SimEvent { simulation_event_id: string; simulation_id: string; ticket_id: string; event_type: string; event_at: string }
export interface SimulationResult {
  simulation_id: string; seed: number; warmup_minutes: Frac; horizon_minutes: Frac; served: Served[]; events: SimEvent[];
}

const nearestRank = (xs: Frac[]): Frac | null => {
  if (!xs.length) return null;
  const s = [...xs].sort(fCmp);
  const idx = fCeil(fMul(frac(9, 10), frac(s.length)));
  return s[Number(idx < 1n ? 1n : idx) - 1]!;
};

/** Tickets that started service and arrived after the warm-up (the statistics population). */
export const counted = (r: SimulationResult): Served[] => r.served.filter((s) => s.start !== null && fCmp(s.demand.arrival, r.warmup_minutes) >= 0);
export const waitsOf = (r: SimulationResult): Frac[] => counted(r).map((s) => waitOf(s)!);
export const meanWait = (r: SimulationResult): Frac | null => fMean(waitsOf(r));
export function finalCompletion(r: SimulationResult): Frac | null {
  const ends = counted(r).map((s) => s.end).filter((e): e is Frac => e !== null);
  return ends.length ? ends.reduce((a, b) => (fCmp(b, a) > 0 ? b : a)) : null;
}

/** Exactly the shape of expected.json `simulation` (P04-GOLD-01). */
export function goldenShape(r: SimulationResult): { simulation_id: string; waits_minutes: (string | null)[]; mean_wait_minutes: string | null; final_completion_minute: string | null; events: SimEvent[] } {
  return { simulation_id: r.simulation_id, waits_minutes: waitsOf(r).map(d4f), mean_wait_minutes: d4f(meanWait(r)), final_completion_minute: d4f(finalCompletion(r)), events: r.events };
}

export interface SimStatistics {
  label: string; seed: number; warmup_minutes: string | null; horizon_minutes: string | null; tickets_generated: number; tickets_counted: number;
  warmup_excluded: number; warmup_ticket_ids: string[]; censored_at_horizon: number; p90_wait_minutes: string | null; max_wait_minutes: string | null;
  wait_by_priority: Record<string, { count: number; mean_wait_minutes: string | null; p90_wait_minutes: string | null }>;
}
/** Extra statistics beside the golden shape (warm-up excluded); an estimate, labelled as one. */
export function statistics(r: SimulationResult): SimStatistics {
  const byPri = new Map<string, Frac[]>();
  for (const s of counted(r)) (byPri.get(s.demand.priority) ?? byPri.set(s.demand.priority, []).get(s.demand.priority)!).push(waitOf(s)!);
  const waits = waitsOf(r);
  const warm = r.served.filter((s) => fCmp(s.demand.arrival, r.warmup_minutes) < 0).map((s) => s.demand.ticket_id);
  return {
    label: "simulated estimate, not an observed result", seed: r.seed, warmup_minutes: d4f(r.warmup_minutes), horizon_minutes: d4f(r.horizon_minutes),
    tickets_generated: r.served.length, tickets_counted: counted(r).length, warmup_excluded: warm.length, warmup_ticket_ids: warm,
    censored_at_horizon: r.served.filter((s) => s.start === null).length,
    p90_wait_minutes: d4f(nearestRank(waits)), max_wait_minutes: waits.length ? d4f(waits.reduce((a, b) => (fCmp(b, a) > 0 ? b : a))) : null,
    wait_by_priority: Object.fromEntries([...byPri.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([p, w]) => [p, { count: w.length, mean_wait_minutes: d4f(fMean(w)), p90_wait_minutes: d4f(nearestRank(w)) }])),
  };
}

function eventsOf(simulationId: string, served: readonly Served[]): SimEvent[] {
  const rows: [string, Served, Frac][] = [];
  for (const [kind, pick] of [["service_started", (s: Served) => s.start], ["resolved", (s: Served) => s.end]] as const)
    for (const s of served) { const at = pick(s); if (at !== null) rows.push([kind, s, at]); }
  return rows.map(([kind, s, at], k) => ({ simulation_event_id: `se-${String(k + 1).padStart(3, "0")}`, simulation_id: simulationId, ticket_id: s.demand.ticket_id, event_type: kind, event_at: d4f(at)! }));
}

/** Run one replication. `config` is a run config (see parseConfig) or a parsed one. */
export function simulate(config: unknown, seed: number, warmupMinutes: unknown = 0, horizonMinutes: unknown = 60, simulationId = "sim"): SimulationResult {
  const cfg = isParsed(config) ? config : parseConfig(config);
  const warm = num(warmupMinutes, "warmup_minutes", { nonneg: true });
  const horizon = num(horizonMinutes, "horizon_minutes", { positive: true });
  if (typeof seed !== "number" || !Number.isInteger(seed)) bad("seed must be an integer");
  const served = dispatch(buildDemand(cfg, seed, horizon), cfg.agents, cfg.discipline, horizon);
  return { simulation_id: simulationId, seed, warmup_minutes: warm, horizon_minutes: horizon, served, events: eventsOf(simulationId, served) };
}
const isParsed = (c: unknown): c is SimConfig => !!c && typeof c === "object" && "priority_mix" in c && Array.isArray((c as SimConfig).priority_mix) && (c as SimConfig).service_minutes !== undefined && typeof (c as SimConfig).service_minutes === "object" && "n" in (c as SimConfig).service_minutes;

/** Replication r uses seed `seed + r`; the first one is the run itself. */
export const replicate = (config: unknown, seed: number, replications: number, warmup: unknown, horizon: unknown, id: string): SimulationResult[] =>
  Array.from({ length: replications }, (_, r) => simulate(config, seed + r, warmup, horizon, id));

function isqrt(n: bigint): bigint { if (n < 2n) return n; let x = n, y = (x + 1n) / 2n; while (y < x) { x = y; y = (x + n / x) / 2n; } return x; }
/** Mean over replications and a 95 % Student-t half-width (null with fewer than two); an estimate. The square root is
 * taken in integers at 1e-8; Python's float square root can differ from it past the 8th decimal. */
export function meanCi95(values: Frac[]): { n: number; mean: string | null; ci95_half_width: string | null } {
  const n = values.length;
  if (n === 0) return { n: 0, mean: null, ci95_half_width: null };
  const m = fDiv(fSum(values), frac(n));
  if (n < 2) return { n, mean: d4f(m), ci95_half_width: null };
  const varr = fDiv(fSum(values.map((v) => fMul(fSub(v, m), fSub(v, m)))), frac(n - 1));
  const t = n - 1 <= T95.length ? parseDecimal(T95[n - 2])! : parseDecimal("2.000")!; // D-09: table to 50 df, 2.000 beyond
  const se2 = fDiv(varr, frac(n));
  const se = frac(isqrt((se2.n * 10n ** 16n) / se2.d), 10n ** 8n);
  return { n, mean: d4f(m), ci95_half_width: d4f(fMul(t, se)) };
}

/** D-09 / R4-11: replication r uses seed `seed + r`; the mean of the per-replication mean waits with its count and 95 % interval. */
export function replicationReport(config: unknown, seed: number, replications: number, warmup: unknown = 0, horizon: unknown = 60) {
  const runs = replicate(config, seed, replications, warmup, horizon, "replication");
  const waits = runs.map((r) => meanWait(r));
  return {
    label: "simulated estimate, not an observed result", seed, replications, seeds: runs.map((r) => r.seed),
    mean_wait_minutes: meanCi95(waits.filter((w): w is Frac => w !== null)),
    replications_without_a_wait: waits.filter((w) => w === null).length,
    censored_tickets_total: runs.reduce((a, r) => a + r.served.filter((x) => x.start === null).length, 0),
    per_replication_mean_wait_minutes: waits.map((w) => d4f(w)),
  };
}

/** Two configs on the SAME seeds, hence the same demand paths when only the policy differs; the paired difference per
 * replication (proposal minus baseline) with the replication count and a 95 % interval. An estimate, labelled as one. Mirrors
 * `compare_policies` in domain/serviceflow/simulation.py. */
export function comparePolicies(baseline: unknown, proposal: unknown, seed: number, replications: number, warmup: unknown = 0, horizon: unknown = 60) {
  const base = replicate(baseline, seed, replications, warmup, horizon, "baseline");
  const prop = replicate(proposal, seed, replications, warmup, horizon, "proposal");
  const pairs = base.map((b, i) => [meanWait(b), meanWait(prop[i]!)] as const).filter((p): p is readonly [Frac, Frac] => p[0] !== null && p[1] !== null);
  const diffs = pairs.map(([b, p]) => fSub(p, b));
  const path = (r: SimulationResult): string => JSON.stringify(r.served.map((x) => [d4f(x.demand.arrival), x.demand.priority]));
  const sameDemand = base.every((b, i) => path(b) === path(prop[i]!));
  return {
    label: "simulated estimate, not an observed result", seed, replications, seeds: base.map((r) => r.seed), same_demand_paths: sameDemand,
    baseline_mean_wait_minutes: meanCi95(pairs.map(([b]) => b)), proposal_mean_wait_minutes: meanCi95(pairs.map(([, p]) => p)),
    difference_mean_wait_minutes: meanCi95(diffs), paired_replications: pairs.length,
    proposal_better: diffs.length ? fCmp(fSum(diffs), frac(0)) < 0 : null,
  };
}
