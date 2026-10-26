// Forecasting (D-03). Baselines first: naive and seasonal-naive (period 7) are always computed; the EWMA model is only
// reported as beating them when it does on the same rolling-origin folds. Only information known at the cutoff is used:
// sales sold at or before it and promotion schedules announced by it; promotion outcomes are never read (P03-TEST-02).
// MAE = mean |actual - forecast|; WAPE = sum |error| / sum actual, null when the actuals sum to 0 (P03-TEST-06).
// Values are exact decimals (BigInt), so the figures equal the Fraction arithmetic of domain/supplyscope/forecast.py.
import { MODELS, SEASON, type ModelName } from "./contract";
import { DomainError, FORECAST_CUTOFF_IN_FUTURE } from "./errors";
import { decAbs, decInt, decMul, decAdd, decSub, decToRat, parseDec, pow10, ratCmp, ratio, type Dec, type Rat } from "./money";
import { DAY_MS, SECOND_MS, dayOf, dayStart, isoZ } from "./time";
import type { Movement, Promotion, Receipt, Sale } from "./types";

const MIN_TRAIN = 14;

/** The last day fully observed at the cutoff: 23:59:59 closes its own day, any earlier instant closes the day before. */
export const lastCompleteDay = (cutoff: number): number => dayOf(cutoff + SECOND_MS - DAY_MS);

export function datasetEnd(sales: readonly Sale[], movements: readonly Movement[], receipts: readonly Receipt[]): number | null {
  let end: number | null = null;
  for (const t of [...sales.map((s) => s.sold_at), ...movements.map((m) => m.event_at), ...receipts.map((r) => r.received_at)]) if (end === null || t > end) end = t;
  return end;
}
/** A forecast cutoff later than the last day of the data would "see" a future that does not exist. */
export function checkCutoff(cutoff: number, end: number | null): void {
  if (end !== null && dayOf(cutoff) > dayOf(end)) {
    throw new DomainError(FORECAST_CUTOFF_IN_FUTURE, "the cutoff is after the end of the dataset", "input.cutoff", { cutoff: isoZ(cutoff), dataset_end: isoZ(end) });
  }
}

/** Daily observed units from the first sale to the last complete day at the cutoff; later sales are never read. */
export function dailySeries(sales: readonly Sale[], productId: string, locationId: string, cutoff: number): { first: number | null; series: number[] } {
  const known = sales.filter((s) => s.product_id === productId && s.location_id === locationId && s.sold_at <= cutoff);
  if (known.length === 0) return { first: null, series: [] };
  const first = dayOf(Math.min(...known.map((s) => s.sold_at)));
  const last = Math.max(lastCompleteDay(cutoff), first);
  const series = new Array<number>(last - first + 1).fill(0);
  for (const s of known) { const d = dayOf(s.sold_at); if (d <= last) series[d - first]! += s.quantity; }
  return { first, series };
}

export const naive = (history: readonly number[], h: number): Dec[] => Array.from({ length: h }, () => decInt(history.length ? history[history.length - 1]! : 0));
export function seasonalNaive(history: readonly number[], h: number): Dec[] {
  if (history.length < SEASON) return naive(history, h);
  return Array.from({ length: h }, (_, k) => decInt(history[history.length - SEASON + (k % SEASON)]!));
}

/** EWMA levels with alpha 3/10 after each prefix: levels[o] is the level of the first o days (levels[0] is 0). */
export function ewmaLevels(history: readonly number[]): Dec[] {
  const out: Dec[] = [decInt(0)];
  let level: Dec | null = null;
  for (const y of history) {
    // 0.3 y + 0.7 level, exact: both terms carried at scale s + 1
    level = level === null ? decInt(y) : { n: 3n * BigInt(y) * pow10(level.s) + 7n * level.n, s: level.s + 1 };
    out.push(level);
  }
  return out;
}

/** Factor 1 + planned uplift of promotions whose schedule was announced by `knownAt` and which cover `day` (S-03: an uplift
 * of 0.35 is a factor of 1.35). `realised_uplift` (an outcome) is deliberately never read here. */
export function promoFactor(promotions: readonly Promotion[], productId: string, day: number, knownAt: number): Dec {
  let f = decInt(1);
  for (const p of promotions) {
    if (p.product_id === productId && p.announced_at <= knownAt && dayOf(p.starts_at) <= day && day <= dayOf(p.ends_at)) f = decMul(f, decAdd(decInt(1), parseDec(p.planned_uplift)));
  }
  return f;
}
function ewmaPoints(level: Dec, h: number, start: number | null, promotions: readonly Promotion[], productId: string, knownAt: number | null): Dec[] {
  if (start === null || knownAt === null) return Array.from({ length: h }, () => level);
  return Array.from({ length: h }, (_, k) => decMul(level, promoFactor(promotions, productId, start + k, knownAt)));
}

export interface FoldScore {
  /** 1-based fold number. */
  fold: number;
  /** First forecast day of the fold (a day number). */
  start: number;
  actual: number;
  abs_error: Dec;
  mae: Rat;
  /** Null when the fold's actual demand is 0. */
  wape: Rat | null;
}
export interface ModelEval {
  model: ModelName; folds: number; zero_demand_folds: number; points: number; abs_error: Dec; actual: number;
  residuals: Dec[]; fold_scores: FoldScore[];
}
const newEval = (model: ModelName): ModelEval => ({ model, folds: 0, zero_demand_folds: 0, points: 0, abs_error: decInt(0), actual: 0, residuals: [], fold_scores: [] });
export const maeOf = (e: ModelEval): Rat | null => (e.points ? ratio(e.abs_error.n, BigInt(e.points) * pow10(e.abs_error.s)) : null);
/** Null when the actuals sum to 0. */
export const wapeOf = (e: ModelEval): Rat | null => (e.actual === 0 ? null : ratio(e.abs_error.n, BigInt(e.actual) * pow10(e.abs_error.s)));

/** Rolling origins: train on series[:o], score series[o:o+h]; step = h so the folds do not overlap. */
export function foldOrigins(n: number, h: number, minTrain = MIN_TRAIN): number[] {
  const out: number[] = [];
  if (n >= minTrain + h) for (let o = minTrain; o <= n - h; o += h) out.push(o);
  return out;
}

export function evaluate(series: readonly number[], first: number, h: number, promotions: readonly Promotion[], productId: string, minTrain = MIN_TRAIN): Record<ModelName, ModelEval> {
  const out = Object.fromEntries(MODELS.map((m) => [m, newEval(m)])) as Record<ModelName, ModelEval>;
  const origins = foldOrigins(series.length, h, minTrain);
  const levels = origins.length ? ewmaLevels(series.slice(0, origins[origins.length - 1])) : [];
  origins.forEach((o, i) => {
    const train = series.slice(0, o), actual = series.slice(o, o + h);
    const foldStart = first + o;
    const knownAt = dayStart(foldStart) - SECOND_MS; // end of the origin day
    const preds: Record<ModelName, Dec[]> = { naive: naive(train, h), seasonal_naive: seasonalNaive(train, h), ewma: ewmaPoints(levels[o]!, h, foldStart, promotions, productId, knownAt) };
    const total = actual.reduce((a, b) => a + b, 0);
    for (const name of MODELS) {
      const ev = out[name];
      ev.folds += 1;
      ev.zero_demand_folds += total === 0 ? 1 : 0;
      let foldErr = decInt(0);
      actual.forEach((a, k) => {
        const err = decSub(decInt(a), preds[name][k]!);
        ev.residuals.push(err);
        ev.points += 1;
        ev.abs_error = decAdd(ev.abs_error, decAbs(err));
        ev.actual += a;
        foldErr = decAdd(foldErr, decAbs(err));
      });
      ev.fold_scores.push({ fold: i + 1, start: foldStart, actual: total, abs_error: foldErr, mae: { num: foldErr.n, den: pow10(foldErr.s) * BigInt(h) }, wape: total === 0 ? null : { num: foldErr.n, den: pow10(foldErr.s) * BigInt(total) } });
    }
  });
  return out;
}

/** True only when the model's MAE is lower than the baseline's on the same folds; null when it cannot be judged. */
export function beats(model: ModelEval, base: ModelEval): boolean | null {
  const m = maeOf(model), b = maeOf(base);
  if (m === null || b === null || wapeOf(base) === null) return null;
  return ratCmp(m, b) < 0;
}

/** Sample variance of the residuals (n - 1); the caller takes the square root. Null below 2 residuals. */
export function residualVariance(residuals: readonly Dec[]): Rat | null {
  const n = residuals.length;
  if (n < 2) return null;
  let sum: Dec = decInt(0), sumSq: Dec = decInt(0);
  for (const r of residuals) { sum = decAdd(sum, r); sumSq = decAdd(sumSq, decMul(r, r)); }
  // sum (r - mean)^2 / (n - 1) = (n * sumSq - sum^2) / (n (n - 1))
  const numer = decSub(decMul(decInt(n), sumSq), decMul(sum, sum));
  return ratio(decToRat(numer).num, decToRat(numer).den * BigInt(n) * BigInt(n - 1));
}

export interface ForecastResult {
  product_id: string; location_id: string; cutoff: number; horizon: number; first_day: number | null; history_days: number;
  /** First forecast day. */
  start: number;
  points: Record<ModelName, Dec[]>; evals: Record<ModelName, ModelEval>; selected_model: ModelName;
  beats_baseline: { ewma: boolean | null }; sigma_variance: Rat | null; notes: string[];
}

/** Forecast `horizon` days after the last complete day at `cutoff`, from information known at `cutoff` only. */
export function forecastDemand(sales: readonly Sale[], promotions: readonly Promotion[], productId: string, locationId: string,
  cutoff: number, horizon: number, endOfData: number | null = null, minTrain = MIN_TRAIN): ForecastResult {
  checkCutoff(cutoff, endOfData);
  const promos = promotions.filter((p) => p.announced_at <= cutoff); // schedules known at the cutoff
  const { first, series } = dailySeries(sales, productId, locationId, cutoff);
  const notes: string[] = [];
  const start = first === null ? lastCompleteDay(cutoff) + 1 : first + series.length;
  const levels = ewmaLevels(series);
  const points: Record<ModelName, Dec[]> = { naive: naive(series, horizon), seasonal_naive: seasonalNaive(series, horizon), ewma: ewmaPoints(levels[series.length]!, horizon, start, promos, productId, cutoff) };
  let evals: Record<ModelName, ModelEval>;
  if (series.length === 0 || first === null) {
    notes.push("NO_HISTORY");
    evals = Object.fromEntries(MODELS.map((m) => [m, newEval(m)])) as Record<ModelName, ModelEval>;
  } else {
    if (series.length < SEASON) notes.push("SEASONAL_NAIVE_FELL_BACK_TO_NAIVE");
    evals = evaluate(series, first, Math.min(horizon, SEASON), promos, productId, minTrain);
  }
  const verdict = beats(evals.ewma, evals.seasonal_naive);
  const selected: ModelName = verdict ? "ewma" : series.length >= SEASON ? "seasonal_naive" : "naive";
  if (evals.ewma.zero_demand_folds) notes.push("ZERO_DEMAND_FOLDS_DISCLOSED");
  return { product_id: productId, location_id: locationId, cutoff, horizon, first_day: first, history_days: series.length, start, points, evals, selected_model: selected, beats_baseline: { ewma: verdict }, sigma_variance: residualVariance(evals[selected].residuals), notes };
}
