// Batch validation with dependent rejection (D-01, D-02, D-05). Mirrors domain/serviceflow/ingest.py and models.py
// (without the API's `base` population: the site ingests one published batch).
import {
  AGENT_NOT_QUALIFIED, BOT_AS_HUMAN_REPLY, CONCURRENCY_EXCEEDED, CONTRACT_MISMATCH, CONTRACT_VERSION, DUPLICATE_ID,
  EMPLOYMENT_TYPES, ENTITIES, EVENT_TYPES, MALFORMED_RECORD, OPENERS, PRIORITIES, PRIORITY_POLICIES, RESUME_BEFORE_SERVICE,
  SEED_MAX, SERVICE_OUTSIDE_SHIFT, TICKET_REJECTED, TRANSFER_RESETS_ARRIVAL, UNKNOWN_REFERENCE, type Entity,
} from "./contract";
import { DomainError } from "./errors";
import { intervalConflict, isBot, ordered, queueAt, replay, type Interval } from "./events";
import { parseConfig } from "./simulation";
import { parseTs, parseTsOpt, validZone } from "./time";
import type {
  Agent, AgentSkill, Customer, IngestResult, PipelineInputs, Population, Queue, QueueSkill, RejectedRecord, Shift, SimulationRun,
  Skill, SlaPolicy, Survey, Ticket, TicketEvent,
} from "./types";

type Row = Record<string, unknown>;
const bad = (m: string): never => { throw new Error(m); };
const S = (v: unknown): string => (typeof v === "string" && v.trim() !== "" && [...v].length <= 256 ? v : bad("non-empty string required"));
const SOpt = (v: unknown): string | null => (v === null || v === undefined ? null : S(v));
/** D-09 / R4-17: an integer field takes a JSON number whose VALUE is an integer (30 and 30.0 alike, as in Python's `_int`). */
const I = (v: unknown, min: number, max?: number): number =>
  typeof v === "number" && Number.isInteger(v) && v >= min && (max === undefined || v <= max) ? v : bad(`integer >= ${min} required`);
const B = (v: unknown): boolean => (typeof v === "boolean" ? v : bad("boolean required"));
const C = <T extends string>(v: unknown, allowed: readonly T[]): T => (allowed.includes(v as T) ? (v as T) : bad("one of the allowed values required"));
const Z = (v: unknown): string => { const n = S(v); return validZone(n) ? n : bad("IANA timezone required"); };
const bool0 = (r: Row, k: string, dflt: boolean): boolean => (k in r ? B(r[k]) : dflt);

const parsers: Record<Entity, (r: Row) => unknown> = {
  customers: (r): Customer => ({ customer_id: S(r.customer_id), segment: S(r.segment), timezone: Z(r.timezone), created_at: parseTs(r.created_at), synthetic: bool0(r, "synthetic", true) }),
  queues: (r): Queue => ({ queue_id: S(r.queue_id), queue_name: S(r.queue_name), priority_policy: C(r.priority_policy, PRIORITY_POLICIES), calendar_id: S(r.calendar_id), active: B(r.active) }),
  tickets: (r): Ticket => ({ ticket_id: S(r.ticket_id), customer_id: S(r.customer_id), queue_id: S(r.queue_id), priority: C(r.priority, PRIORITIES), created_at: parseTs(r.created_at), channel: S(r.channel) }),
  ticket_events: (r): TicketEvent => {
    const t = C(r.event_type, EVENT_TYPES);
    const e: TicketEvent = { event_id: S(r.event_id), ticket_id: S(r.ticket_id), event_type: t, occurred_at: parseTs(r.occurred_at), actor_id: SOpt(r.actor_id), queue_id: SOpt(r.queue_id), agent_id: SOpt(r.agent_id) };
    if (t === "service_started" && e.agent_id === null) bad("service_started needs an agent_id");
    if ((t === "replied_human" || t === "acknowledged_bot") && e.actor_id === null) bad(`${t} needs an actor_id`);
    if ((t === "created" || t === "transferred") && e.queue_id === null) bad(`${t} needs a queue_id`);
    return e;
  },
  agents: (r): Agent => ({ agent_id: S(r.agent_id), agent_name: S(r.agent_name), timezone: Z(r.timezone), employment_type: C(r.employment_type, EMPLOYMENT_TYPES), active: B(r.active), max_concurrent: "max_concurrent" in r ? I(r.max_concurrent, 1, 100) : 1 }),
  skills: (r): Skill => ({ skill_id: S(r.skill_id), skill_name: S(r.skill_name), description: SOpt(r.description), active: B(r.active), created_at: parseTs(r.created_at) }),
  agent_skills: (r): AgentSkill => ({ agent_skill_id: S(r.agent_skill_id), agent_id: S(r.agent_id), skill_id: S(r.skill_id), proficiency: I(r.proficiency, 1, 5), effective_from: parseTs(r.effective_from) }),
  queue_skills: (r): QueueSkill => ({ queue_id: S(r.queue_id), skill_id: S(r.skill_id) }),
  shifts: (r): Shift => {
    const s: Shift = { shift_id: S(r.shift_id), agent_id: S(r.agent_id), starts_at: parseTs(r.starts_at), ends_at: parseTs(r.ends_at), break_minutes: I(r.break_minutes, 0) };
    if (s.ends_at <= s.starts_at) bad("ends_at must be after starts_at");
    if (s.break_minutes * 60 > s.ends_at - s.starts_at) bad("break longer than the shift");
    return s;
  },
  sla_policies: (r): SlaPolicy => ({ sla_policy_id: S(r.sla_policy_id), priority: C(r.priority, PRIORITIES), first_response_minutes: I(r.first_response_minutes, 1), resolution_minutes: I(r.resolution_minutes, 1), calendar_id: S(r.calendar_id) }),
  surveys: (r): Survey => {
    const resp = parseTsOpt(r.response_at);
    const score = r.score === null || r.score === undefined ? null : I(r.score, 1, 5);
    if ((score === null) !== (resp === null)) bad("score and response_at go together");
    return { survey_id: S(r.survey_id), ticket_id: S(r.ticket_id), response_at: resp, score, invited_at: parseTsOpt(r.invited_at) };
  },
  simulation_runs: (r): SimulationRun => {
    const cfg = r.config;
    parseConfig(cfg);
    const nonneg = (v: unknown): number => (typeof v === "number" && v >= 0 ? v : bad("minutes must be non-negative numbers"));
    const warm = nonneg(r.warmup_minutes), horizon = nonneg(r.horizon_minutes);
    if (horizon <= 0) bad("horizon must be positive");
    return { simulation_id: S(r.simulation_id), seed: I(r.seed, -SEED_MAX, SEED_MAX), warmup_minutes: warm, policy_version: S(r.policy_version), horizon_minutes: horizon, config: cfg as Record<string, unknown> };
  },
};

const ID_FIELD: Record<Entity, string> = {
  customers: "customer_id", queues: "queue_id", tickets: "ticket_id", ticket_events: "event_id", agents: "agent_id", skills: "skill_id",
  agent_skills: "agent_skill_id", queue_skills: "queue_id", shifts: "shift_id", sla_policies: "sla_policy_id", surveys: "survey_id",
  simulation_runs: "simulation_id",
};
/** The id of a raw row or typed record (queue_skills: `queue_id/skill_id`); "" when unusable. */
export function rowId(entity: Entity, row: unknown): string {
  const r = (row ?? {}) as Row;
  if (entity === "queue_skills") return typeof r.queue_id === "string" && typeof r.skill_id === "string" ? `${r.queue_id}/${r.skill_id}` : "";
  const v = r[ID_FIELD[entity]];
  return typeof v === "string" ? v : "";
}

interface Parsed { pos: number; row: unknown; obj: any | null }
const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
function group<T>(items: readonly T[], key: (x: T) => string): Map<string, T[]> {
  const out = new Map<string, T[]>();
  for (const x of items) { const k = key(x); const l = out.get(k); if (l) l.push(x); else out.set(k, [x]); }
  return out;
}

/** Validate and parse a raw batch; raw rows of rejected records are kept as they arrived. */
export function validateBatch(raw: PipelineInputs): IngestResult {
  if ((raw.contract_version ?? CONTRACT_VERSION) !== CONTRACT_VERSION) throw new DomainError(CONTRACT_MISMATCH, `expected contract_version ${CONTRACT_VERSION}`);
  const badMap = new Map<string, string>();               // `${entity}|${position}` -> reason
  const key = (ent: Entity, pos: number): string => `${ent}|${pos}`;
  const parsed = {} as Record<Entity, Parsed[]>;
  for (const ent of ENTITIES) {
    parsed[ent] = [];
    const seen = new Set<string>();
    const rows = Array.isArray(raw[ent]) ? (raw[ent] as unknown[]) : [];
    rows.forEach((row, pos) => {
      let obj: any;
      try {
        if (row === null || typeof row !== "object" || Array.isArray(row)) throw new Error("record must be an object");
        obj = parsers[ent](row as Row);
      } catch {
        badMap.set(key(ent, pos), MALFORMED_RECORD); parsed[ent].push({ pos, row, obj: null }); return;
      }
      const rid = rowId(ent, obj);
      if (seen.has(rid)) { badMap.set(key(ent, pos), DUPLICATE_ID); parsed[ent].push({ pos, row, obj: null }); return; }
      seen.add(rid);
      parsed[ent].push({ pos, row, obj });
    });
  }
  const ok = (ent: Entity): Parsed[] => parsed[ent].filter((p) => !badMap.has(key(ent, p.pos)) && p.obj !== null);
  const reject = (ent: Entity, pos: number, reason: string): void => { if (!badMap.has(key(ent, pos))) badMap.set(key(ent, pos), reason); };

  // references among reference data
  const known = {} as Record<Entity, Set<string>>;
  for (const ent of ENTITIES) known[ent] = new Set();
  for (const ent of ["customers", "queues", "agents", "skills"] as const) for (const p of ok(ent)) known[ent].add(rowId(ent, p.obj));
  const checks: [Entity, [string, Entity][]][] = [
    ["queue_skills", [["queue_id", "queues"], ["skill_id", "skills"]]],
    ["agent_skills", [["agent_id", "agents"], ["skill_id", "skills"]]],
    ["shifts", [["agent_id", "agents"]]],
    ["tickets", [["customer_id", "customers"], ["queue_id", "queues"]]],
  ];
  for (const [ent, refs] of checks) for (const p of ok(ent)) if (refs.some(([f, parent]) => !known[parent].has(p.obj[f]))) reject(ent, p.pos, UNKNOWN_REFERENCE);
  for (const ent of ["queue_skills", "agent_skills", "shifts", "tickets"] as const) for (const p of ok(ent)) known[ent].add(rowId(ent, p.obj));

  // tickets already rejected for structure: their dependents carry TICKET_REJECTED
  const badTicket = new Map<string, string>();
  for (const p of parsed.tickets) {
    const reason = badMap.get(key("tickets", p.pos));
    if (reason === MALFORMED_RECORD || reason === UNKNOWN_REFERENCE) {
      const tid = p.obj !== null ? p.obj.ticket_id : (p.row as Row | null)?.ticket_id;
      if (typeof tid === "string" && !badTicket.has(tid)) badTicket.set(tid, reason);
    }
  }
  const newTicketIds = new Set(ok("tickets").map((p) => (p.obj as Ticket).ticket_id));

  for (const p of ok("ticket_events")) {
    const e = p.obj as TicketEvent;
    if (badTicket.has(e.ticket_id)) reject("ticket_events", p.pos, TICKET_REJECTED);
    else if (!newTicketIds.has(e.ticket_id) || (e.queue_id !== null && !known.queues.has(e.queue_id)) || (e.agent_id !== null && !known.agents.has(e.agent_id))) reject("ticket_events", p.pos, UNKNOWN_REFERENCE);
    else if (e.event_type === "replied_human" && isBot(e.actor_id)) reject("ticket_events", p.pos, BOT_AS_HUMAN_REPLY);
  }
  for (const p of ok("surveys")) {
    const s = p.obj as Survey;
    if (badTicket.has(s.ticket_id)) reject("surveys", p.pos, TICKET_REJECTED);
    else if (!newTicketIds.has(s.ticket_id)) reject("surveys", p.pos, UNKNOWN_REFERENCE);
  }

  // ticket rules
  const tickets = new Map<string, Ticket>(ok("tickets").map((p) => [(p.obj as Ticket).ticket_id, p.obj as Ticket]));
  const newEv = group(ok("ticket_events").map((p) => ({ pos: p.pos, e: p.obj as TicketEvent })), (x) => x.e.ticket_id);
  const skillsOfQueue = new Map<string, Set<string>>();
  for (const p of ok("queue_skills")) { const q = p.obj as QueueSkill; (skillsOfQueue.get(q.queue_id) ?? skillsOfQueue.set(q.queue_id, new Set()).get(q.queue_id)!).add(q.skill_id); }
  const agentSkills = group(ok("agent_skills").map((p) => p.obj as AgentSkill), (s) => s.agent_id);
  const agents = new Map<string, Agent>(ok("agents").map((p) => [(p.obj as Agent).agent_id, p.obj as Agent]));
  const shiftsOf = group(ok("shifts").map((p) => p.obj as Shift), (s) => s.agent_id);
  const reasonOf = new Map<string, string>();
  const flag = (tid: string, reason: string): void => { if (!reasonOf.has(tid)) reasonOf.set(tid, reason); };
  const eventsOf = (tid: string): TicketEvent[] => (newEv.get(tid) ?? []).map((x) => x.e);

  for (const tid of [...newEv.keys()].sort(cmp)) {
    const t = tickets.get(tid)!, evs = eventsOf(tid);
    if (evs.some((e) => e.event_type === "transferred") && t.created_at > Math.min(...evs.map((e) => e.occurred_at))) flag(tid, TRANSFER_RESETS_ARRIVAL);
    for (const { e } of newEv.get(tid)!) {
      if (e.event_type !== "service_started") continue;
      const q = queueAt(t, evs, e.occurred_at);
      const held = new Set((agentSkills.get(e.agent_id ?? "") ?? []).filter((s) => s.effective_from <= e.occurred_at).map((s) => s.skill_id));
      const need = skillsOfQueue.get(q ?? "") ?? new Set<string>();
      if (![...need].every((s) => held.has(s))) flag(tid, AGENT_NOT_QUALIFIED);
    }
    // R4-16: the first service opener of a ticket must be a service_started, not a resumed
    const firstOpener = ordered(evs).find((e) => OPENERS.has(e.event_type));
    if (firstOpener !== undefined && firstOpener.event_type === "resumed") flag(tid, RESUME_BEFORE_SERVICE);
    // R4-03: an agent starts service only when available: the instant lies inside one of their shifts
    const own = replay(t, evs).cycles.flatMap((c) => c.intervals);
    for (const { e } of newEv.get(tid)!) {
      if (!OPENERS.has(e.event_type)) continue;
      const iv = own.find((i) => i.start === e.occurred_at && (e.agent_id === null || i.agent_id === e.agent_id));
      if (iv === undefined) continue;
      if (!(shiftsOf.get(iv.agent_id ?? "") ?? []).some((s) => s.starts_at <= e.occurred_at && e.occurred_at < s.ends_at)) flag(tid, SERVICE_OUTSIDE_SHIFT);
    }
  }

  // concurrency, sequentially by start so the earlier start wins
  const acceptedIv = new Map<string, Interval[]>();
  const candidates: { at: number; id: string; e: TicketEvent }[] = [];
  for (const [tid, lst] of newEv) for (const { e } of lst) if (OPENERS.has(e.event_type) && !reasonOf.has(tid)) candidates.push({ at: e.occurred_at, id: e.event_id, e });
  candidates.sort((a, b) => a.at - b.at || cmp(a.id, b.id));
  const history = new Map([...newEv.keys()].map((tid) => [tid, replay(tickets.get(tid)!, eventsOf(tid))] as const));
  for (const { at, e } of candidates) {
    const tid = e.ticket_id;
    if (reasonOf.has(tid)) continue;
    const iv = history.get(tid)!.cycles.flatMap((c) => c.intervals).find((i) => i.start === at && (e.agent_id === null || i.agent_id === e.agent_id));
    if (iv === undefined) continue;
    const ag = agents.get(iv.agent_id ?? "");
    const cap = ag !== undefined ? ag.max_concurrent : 1;
    const mine = acceptedIv.get(iv.agent_id ?? "") ?? [];
    if (intervalConflict(mine, iv, cap)) {
      flag(tid, CONCURRENCY_EXCEEDED);
      for (const [k, ivs] of acceptedIv) acceptedIv.set(k, ivs.filter((i) => i.ticket_id !== tid)); // a rejected ticket occupies nobody
      continue;
    }
    acceptedIv.set(iv.agent_id ?? "", [...mine, iv]);
  }

  // R4-02: iterate to a fixed point. A ticket rejected only because of a ticket that was rejected later is accepted
  // again when all its intervals fit among the tickets that stay accepted.
  let released = true;
  while (released) {
    released = false;
    const firstStart = (t: string): number => Math.min(...history.get(t)!.cycles.flatMap((c) => c.intervals).map((i) => i.start), Infinity);
    const pending = [...reasonOf].filter(([t, r]) => r === CONCURRENCY_EXCEEDED && history.has(t)).map(([t]) => t).sort((a, b) => firstStart(a) - firstStart(b) || cmp(a, b));
    for (const tid of pending) {
      const trial = new Map<string, Interval[]>([...acceptedIv].map(([k, v]) => [k, [...v]]));
      let fits = true;
      for (const iv of history.get(tid)!.cycles.flatMap((c) => c.intervals).sort((a, b) => a.start - b.start)) {
        const ag = agents.get(iv.agent_id ?? "");
        const lst = trial.get(iv.agent_id ?? "") ?? [];
        if (intervalConflict(lst, iv, ag !== undefined ? ag.max_concurrent : 1)) { fits = false; break; }
        trial.set(iv.agent_id ?? "", [...lst, iv]);
      }
      if (fits) {
        reasonOf.delete(tid);
        acceptedIv.clear();
        for (const [k, v] of trial) acceptedIv.set(k, v);
        released = true;
      }
    }
  }

  for (const [tid, reason] of reasonOf) {
    for (const p of parsed.tickets) if (p.obj !== null && p.obj.ticket_id === tid && !badMap.has(key("tickets", p.pos))) badMap.set(key("tickets", p.pos), reason);
    for (const { pos } of newEv.get(tid) ?? []) if (!badMap.has(key("ticket_events", pos))) badMap.set(key("ticket_events", pos), TICKET_REJECTED);
    for (const p of ok("surveys")) if ((p.obj as Survey).ticket_id === tid) reject("surveys", p.pos, TICKET_REJECTED);
  }

  // result
  const accepted = {} as Record<Entity, unknown[]>;
  for (const ent of ENTITIES) accepted[ent] = parsed[ent].filter((p) => !badMap.has(key(ent, p.pos)) && p.obj !== null).map((p) => p.obj);
  const rejected: RejectedRecord[] = [];
  for (const ent of ENTITIES) for (const p of parsed[ent]) {
    const reason = badMap.get(key(ent, p.pos));
    if (reason !== undefined) rejected.push({ entity: ent, id: rowId(ent, p.obj !== null ? p.obj : p.row), reason_code: reason, raw_row: p.row, status: "rejected" });
  }
  rejected.sort((a, b) => cmp(a.entity, b.entity) || cmp(a.id, b.id));
  const counts = {} as IngestResult["counts"];
  for (const ent of ENTITIES) counts[ent] = { accepted: accepted[ent].length, rejected: rejected.filter((r) => r.entity === ent).length };
  return { accepted: accepted as unknown as Population, rejected, counts };
}
