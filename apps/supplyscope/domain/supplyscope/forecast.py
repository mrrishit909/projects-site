"""Forecasting (D-03). Baselines first: naive and seasonal-naive (period 7) are always computed; the EWMA model is only
reported as beating them when it does on the same rolling-origin folds. Only information known at the cutoff is used:
sales sold at or before it and promotion schedules announced by it; promotion outcomes are never read (P03-TEST-02).
MAE = mean |actual - forecast|; WAPE = sum |error| / sum actual, null when the actuals sum to 0 (P03-TEST-06)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from typing import Any, Callable, Iterable

from .contract import MODELS, SEASON
from .errors import FORECAST_CUTOFF_IN_FUTURE, DomainError
from .models import Movement, Promotion, Receipt, Sale
from .money import ratio

ALPHA = Fraction(3, 10)
MIN_TRAIN = 14
SECOND = timedelta(seconds=1)


def last_complete_day(cutoff: datetime) -> date:
    """The last day fully observed at the cutoff: 23:59:59 closes its own day, any earlier instant closes the day before."""
    return ((cutoff + SECOND).astimezone(timezone.utc) - timedelta(days=1)).date()


def dataset_end(sales: Iterable[Sale], movements: Iterable[Movement], receipts: Iterable[Receipt]) -> datetime | None:
    stamps = [s.sold_at for s in sales] + [m.event_at for m in movements] + [r.received_at for r in receipts]
    return max(stamps) if stamps else None


def check_cutoff(cutoff: datetime, end: datetime | None) -> None:
    """A forecast cutoff later than the last day of the data would 'see' a future that does not exist."""
    if end is not None and cutoff.astimezone(timezone.utc).date() > end.astimezone(timezone.utc).date():
        raise DomainError(FORECAST_CUTOFF_IN_FUTURE, "the cutoff is after the end of the dataset",
                          path="input.cutoff", details={"cutoff": cutoff.isoformat(), "dataset_end": end.isoformat()})


def daily_series(sales: Iterable[Sale], product_id: str, location_id: str, cutoff: datetime) -> tuple[date | None, list[int]]:
    """Daily observed units from the first sale to the last complete day at the cutoff; later sales are never read."""
    known = [s for s in sales if s.product_id == product_id and s.location_id == location_id and s.sold_at <= cutoff]
    if not known:
        return None, []
    first = min(s.sold_at for s in known).astimezone(timezone.utc).date()
    last = max(last_complete_day(cutoff), first)
    by_day: dict[date, int] = {}
    for s in known:
        d = s.sold_at.astimezone(timezone.utc).date()
        if d <= last:
            by_day[d] = by_day.get(d, 0) + s.quantity
    return first, [by_day.get(first + timedelta(days=i), 0) for i in range((last - first).days + 1)]


def naive(history: list[int], h: int) -> list[Fraction]:
    return [Fraction(history[-1] if history else 0)] * h


def seasonal_naive(history: list[int], h: int) -> list[Fraction]:
    if len(history) < SEASON:
        return naive(history, h)
    return [Fraction(history[len(history) - SEASON + (k % SEASON)]) for k in range(h)]


def ewma_level(history: list[int]) -> Fraction:
    if not history:
        return Fraction(0)
    level = Fraction(history[0])
    for y in history[1:]:
        level = ALPHA * y + (1 - ALPHA) * level
    return level


def promo_factor(promotions: Iterable[Promotion], product_id: str, day: date, known_at: datetime) -> Fraction:
    """Factor 1 + planned uplift of promotions whose schedule was announced by ``known_at`` and which cover ``day``.
    ``realised_uplift`` (an outcome) is deliberately never read here."""
    f = Fraction(1)
    for p in promotions:
        if p.product_id == product_id and p.announced_at <= known_at and \
                p.starts_at.astimezone(timezone.utc).date() <= day <= p.ends_at.astimezone(timezone.utc).date():
            f *= 1 + Fraction(p.planned_uplift)   # S-03: an uplift of 0.35 is a factor of 1.35, not 0.35
    return f


def ewma(history: list[int], h: int, start: date | None = None, promotions: Iterable[Promotion] = (),
         product_id: str = "", known_at: datetime | None = None) -> list[Fraction]:
    level = ewma_level(history)
    if start is None or known_at is None:
        return [level] * h
    promos = list(promotions)
    return [level * promo_factor(promos, product_id, start + timedelta(days=k), known_at) for k in range(h)]


@dataclass
class ModelEval:
    model: str
    folds: int = 0
    zero_demand_folds: int = 0
    points: int = 0
    abs_error: Fraction = Fraction(0)
    actual: Fraction = Fraction(0)
    residuals: list[Fraction] = field(default_factory=list)

    @property
    def mae(self) -> Fraction | None:
        return ratio(self.abs_error, self.points) if self.points else None

    @property
    def wape(self) -> Fraction | None:
        return ratio(self.abs_error, self.actual)  # None when the actuals sum to 0


def fold_origins(n: int, h: int, min_train: int = MIN_TRAIN) -> list[int]:
    """Rolling origins: train on series[:o], score series[o:o+h]; step = h so the folds do not overlap."""
    return list(range(min_train, n - h + 1, h)) if n >= min_train + h else []


def evaluate(series: list[int], first: date, h: int, promotions: list[Promotion], product_id: str,
             min_train: int = MIN_TRAIN) -> dict[str, ModelEval]:
    out = {m: ModelEval(m) for m in MODELS}
    for o in fold_origins(len(series), h, min_train):
        train, actual = series[:o], series[o:o + h]
        fold_start = first + timedelta(days=o)
        known_at = datetime.combine(fold_start, datetime.min.time(), tzinfo=timezone.utc) - SECOND  # end of the origin day
        preds = {"naive": naive(train, h), "seasonal_naive": seasonal_naive(train, h),
                 "ewma": ewma(train, h, fold_start, promotions, product_id, known_at)}
        for name, pred in preds.items():
            ev = out[name]
            ev.folds += 1
            ev.zero_demand_folds += 1 if sum(actual) == 0 else 0
            for a, f in zip(actual, pred):
                err = Fraction(a) - f
                ev.residuals.append(err)
                ev.points += 1
                ev.abs_error += abs(err)
                ev.actual += a
    return out


def beats(model: ModelEval, base: ModelEval) -> bool | None:
    """True only when the model's MAE is lower than the baseline's on the same folds; None when it cannot be judged."""
    if model.mae is None or base.mae is None or base.wape is None:
        return None
    return model.mae < base.mae


def residual_sigma(residuals: list[Fraction]) -> Fraction | None:
    """Sample variance of the residuals (n - 1); the caller takes the square root. None below 2 residuals."""
    n = len(residuals)
    if n < 2:
        return None
    mean = sum(residuals, Fraction(0)) / n
    return sum(((r - mean) ** 2 for r in residuals), Fraction(0)) / (n - 1)


@dataclass
class ForecastResult:
    product_id: str
    location_id: str
    cutoff: datetime
    horizon: int
    first_day: date | None
    history_days: int
    start: date                                          # first forecast date
    points: dict[str, list[Fraction]]
    evals: dict[str, ModelEval]
    selected_model: str
    beats_baseline: dict[str, bool | None]
    sigma_variance: Fraction | None                      # variance of the selected model's daily residuals
    notes: list[str]

    def model_report(self) -> dict[str, Any]:
        from .money import d2, d6
        return {m: {"folds": e.folds, "zero_demand_folds": e.zero_demand_folds, "points": e.points,
                    "mae": d6(e.mae), "wape": d6(e.wape)} for m, e in self.evals.items()}


def forecast_demand(sales: Iterable[Sale], promotions: Iterable[Promotion], product_id: str, location_id: str,
                    cutoff: datetime, horizon: int, end_of_data: datetime | None = None,
                    min_train: int = MIN_TRAIN) -> ForecastResult:
    """Forecast ``horizon`` days after the last complete day at ``cutoff``, from information known at ``cutoff`` only."""
    check_cutoff(cutoff, end_of_data)
    promos = [p for p in promotions if p.announced_at <= cutoff]     # schedules known at the cutoff
    first, series = daily_series(sales, product_id, location_id, cutoff)
    notes: list[str] = []
    start = last_complete_day(cutoff) + timedelta(days=1) if first is None else first + timedelta(days=len(series))
    points = {"naive": naive(series, horizon), "seasonal_naive": seasonal_naive(series, horizon),
              "ewma": ewma(series, horizon, start, promos, product_id, cutoff)}
    if not series:
        notes.append("NO_HISTORY")
        evals = {m: ModelEval(m) for m in MODELS}
    else:
        if len(series) < SEASON:
            notes.append("SEASONAL_NAIVE_FELL_BACK_TO_NAIVE")
        evals = evaluate(series, first, min(horizon, SEASON), promos, product_id, min_train)
    verdict = {"ewma": beats(evals["ewma"], evals["seasonal_naive"])}
    selected = "ewma" if verdict["ewma"] else ("seasonal_naive" if len(series) >= SEASON else "naive")
    if evals["ewma"].zero_demand_folds:
        notes.append("ZERO_DEMAND_FOLDS_DISCLOSED")
    return ForecastResult(product_id, location_id, cutoff, horizon, first, len(series), start, points, evals, selected,
                          verdict, residual_sigma(evals[selected].residuals), notes)
