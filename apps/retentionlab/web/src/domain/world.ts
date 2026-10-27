// Point-in-time analysis (D-01, D-P10-05..08): eligibility, features, arrived-late counts, labels with censoring, per cutoff.
// A World is built from the ACCEPTED rows of an import. Everything here is exact (integers, rationals); nothing is a float.
import { EVENTS, FEATURES, type Entity, type EventEntity } from "./contract";
import * as E from "./errors";
import type { Row } from "./models";
import { cmpStr, cmpId } from "./models";
import { add, fr, money, parseFraction, ZERO } from "./num";
import { daysUs, isoZ, parseTs, wholeDays, type Ts } from "./time";

export const INELIGIBLE_CREATED = "CREATED_ON_OR_AFTER_OBSERVATION_START";
export const INELIGIBLE_INACTIVE = "NOT_ACTIVE";

/** The refusal code of one requested feature name, or null when it is a usable registered feature (D-P10-14). */
export function classifyFeature(registry: Map<string, Row>, name: string): string | null {
  const r = registry.get(name);
  if (r) {
    if (r["post_outcome"]) return E.POST_OUTCOME_FIELD;
    if (r["latent"] || r["lineage"] === "generator_manifest") return E.LATENT_TRUTH;
    if (r["id_derived"]) return E.ID_FEATURE;
    return null;
  }
  if (name.startsWith("latent_")) return E.LATENT_TRUTH;
  if (name.startsWith("account_id")) return E.ID_FEATURE;
  return E.UNKNOWN_FEATURE;
}

export interface Analysis {
  cutoff_id: string; account_id: unknown; prediction_at: string; eligible: boolean; ineligible_code: string | null; label_end: string; mature: boolean;
  churned: boolean | null; features: Record<string, unknown> | null; max_available_at: string | null; arrived_late: Record<EventEntity, number> | null;
}
const byTime = (a: Row, b: Row, idKey: string): number => { const x = parseTs(a["event_at"]), y = parseTs(b["event_at"]); return x < y ? -1 : x > y ? 1 : cmpStr(a[idKey], b[idKey]); };

export class World {
  readonly asOf: Ts;
  readonly horizon: number;
  readonly grace: number;
  readonly obsDays: number;
  readonly featureVersion: string;
  accounts = new Map<unknown, Row>();
  byAcct: Record<EventEntity, Map<unknown, Row[]>>;
  cutoffs = new Map<string, Row>();
  registry = new Map<string, Row>();
  runs = new Map<string, Row>();
  scenarios = new Map<string, Row>();
  preds = new Map<string, Row>();
  private cache: Map<string, Analysis>;
  private rowsByAt = new Map<string, Row[]>();

  constructor(readonly data: Row, readonly acc: Record<Entity, Row[]>, cache?: Map<string, Analysis>) {
    this.asOf = parseTs(data["as_of"]);
    this.horizon = data["label_version"]["horizon_days"];
    this.grace = data["label_version"]["grace_days"];
    this.obsDays = data["feature_version_spec"]["observation_days"];
    this.featureVersion = data["feature_version_spec"]["feature_version"];
    for (const a of acc.accounts) this.accounts.set(a["account_id"], a);
    this.byAcct = { subscription_events: new Map(), billing_events: new Map(), usage_events: new Map(), support_events: new Map() };
    for (const e of EVENTS) for (const ev of acc[e]) { const l = this.byAcct[e].get(ev["account_id"]); if (l) l.push(ev); else this.byAcct[e].set(ev["account_id"], [ev]); }
    for (const c of acc.prediction_cutoffs) this.cutoffs.set(c["cutoff_id"], c);
    for (const r of acc.feature_registry) this.registry.set(r["feature_name"], r);
    for (const r of acc.training_runs) this.runs.set(r["training_run_id"], r);
    for (const s of acc.intervention_scenarios) this.scenarios.set(s["scenario_id"], s);
    for (const p of acc.predictions) this.preds.set(`${p["training_run_id"]}\u0000${p["cutoff_id"]}`, p);
    this.cache = cache ?? new Map();
  }
  /** The same world with other predictions, publications, runs and scenarios (the analysis cache is shared): one view per model. */
  withEntities(extra: Partial<Record<Entity, Row[]>>): World {
    return new World(this.data, { ...this.acc, ...extra }, this.cache);
  }
  pred(runId: string, cutoffId: string): Row | undefined { return this.preds.get(`${runId}\u0000${cutoffId}`); }
  window(name: string, dflt: number): number { const r = this.registry.get(name); return r && r["window_days"] ? r["window_days"] : dflt; }

  analyse(cutoffId: string): Analysis {
    const hit = this.cache.get(cutoffId);
    if (hit) return hit;
    const c = this.cutoffs.get(cutoffId)!;
    const pa = parseTs(c["prediction_at"]), obs = parseTs(c["observation_start"]), he = parseTs(c["horizon_end"]);
    const labelEnd = he + daysUs(this.grace);
    const mature = labelEnd <= this.asOf;
    const aid = c["account_id"];
    const row: Analysis = { cutoff_id: cutoffId, account_id: aid, prediction_at: isoZ(pa)!, eligible: false, ineligible_code: null, label_end: isoZ(labelEnd)!, mature,
      churned: null, features: null, max_available_at: null, arrived_late: null };
    const subs = this.byAcct.subscription_events.get(aid) ?? [];
    const visible = subs.filter((s) => parseTs(s["event_at"]) < pa && parseTs(s["available_at"]) < pa);
    const latest = visible.length ? visible.reduce((a, b) => (byTime(a, b, "subscription_event_id") >= 0 ? a : b)) : null;
    if (parseTs(this.accounts.get(aid)!["created_at"]) >= obs) row.ineligible_code = INELIGIBLE_CREATED;
    else if (latest === null || latest["event_type"] === "cancel") row.ineligible_code = INELIGIBLE_INACTIVE;
    else row.eligible = true;
    if (row.eligible) {
      Object.assign(row, this.features(aid, pa, obs));
      if (mature) row.churned = subs.some((s) => s["event_type"] === "cancel" && pa <= parseTs(s["event_at"]) && parseTs(s["event_at"]) < he && parseTs(s["available_at"]) < labelEnd);
    }
    this.cache.set(cutoffId, row);
    return row;
  }

  private features(aid: unknown, pa: Ts, obs: Ts): Pick<Analysis, "features" | "max_available_at" | "arrived_late"> {
    const late: Record<EventEntity, number> = { subscription_events: 0, billing_events: 0, usage_events: 0, support_events: 0 };
    const q: Record<string, Row[]> = {};
    for (const e of EVENTS.slice(1) as EventEntity[]) {
      q[e] = [];
      for (const ev of this.byAcct[e].get(aid) ?? []) {
        const at = parseTs(ev["event_at"]);
        if (obs <= at && at < pa) { if (parseTs(ev["available_at"]) < pa) q[e]!.push(ev); else late[e] += 1; }
      }
    }
    late.subscription_events = (this.byAcct.subscription_events.get(aid) ?? []).filter((s) => parseTs(s["event_at"]) < pa && pa <= parseTs(s["available_at"])).length;
    const usage = q["usage_events"]!;
    const recent = pa - daysUs(this.window("usage_events_30d", 30));
    let last: Ts | null = null;
    for (const u of usage) { const t = parseTs(u["event_at"]); if (last === null || t > last) last = t; }
    const bills = q["billing_events"]!.map((b) => parseFraction(b["amount"], false));
    const used = (["billing_events", "usage_events", "support_events"] as const).flatMap((e) => q[e]!.map((ev) => parseTs(ev["available_at"])));
    const maxUsed = used.length ? used.reduce((a, b) => (a > b ? a : b)) : null;
    return {
      features: {
        usage_events_30d: usage.filter((u) => parseTs(u["event_at"]) >= recent).length,
        days_since_last_usage: last === null ? null : wholeDays(pa, last),
        high_severity_support_90d: q["support_events"]!.filter((s) => s["severity"] === "high").length,
        billing_total_90d: bills.length ? money(bills.reduce(add, ZERO)) : null,
      },
      max_available_at: isoZ(maxUsed), arrived_late: late,
    };
  }
  setRows(predictionAt: string): Analysis[] {
    let ids = this.rowsByAt.get(predictionAt);
    if (!ids) {
      const want = parseTs(predictionAt);
      ids = this.acc.prediction_cutoffs.filter((c) => parseTs(c["prediction_at"]) === want);
      this.rowsByAt.set(predictionAt, ids);
    }
    return ids.map((c) => this.analyse(c["cutoff_id"]));
  }
  predictionAts(): string[] {
    return [...new Set(this.acc.prediction_cutoffs.map((c) => isoZ(parseTs(c["prediction_at"]))!))].sort(cmpStr);
  }
}
export const accountsOf = (w: World): unknown[] => [...w.accounts.keys()].sort(cmpId);
void FEATURES; void fr;
