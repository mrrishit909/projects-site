"""Demand, unmet demand and common random numbers (D-03, D-04, D-05, D-06).

Requested = immediately fulfilled sales + unmet demand opened in the window; unmet is a backorder (backlog policy) or
a lost sale (lost_sale policy), never both. A stockout day is a date on which unmet demand opened."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from typing import Any, Iterable

from .contract import UNMET_POLICIES
from .errors import POLICY_SEED_MISMATCH, UNKNOWN_POLICY, DomainError
from .models import Backorder, Latent, LostSale, Sale, Scenario
from .money import ratio

Window = tuple[datetime | None, datetime | None]
ONE_US = timedelta(microseconds=1)


def in_window(t: datetime, start: datetime | None, end: datetime | None, as_of: datetime) -> bool:
    """start <= t < end, and never after the information cutoff ``as_of`` (an absent end means 'up to as_of')."""
    return t <= as_of and (start is None or t >= start) and (end is None or t < end)


def last_observed_day(end: datetime | None, as_of: datetime) -> date:
    return (as_of if end is None else min(as_of, end - ONE_US)).astimezone(timezone.utc).date()


def observed_days(start: datetime, end: datetime | None, as_of: datetime) -> int:
    return max((last_observed_day(end, as_of) - start.astimezone(timezone.utc).date()).days + 1, 0)


@dataclass(frozen=True)
class DemandSummary:
    requested: int
    fulfilled: int
    unmet: int
    stockout_dates: frozenset[date]
    observed_days: int

    @property
    def fill_rate(self) -> Fraction | None:
        return ratio(self.fulfilled, self.requested)

    @property
    def stockout_day_ratio(self) -> Fraction | None:
        return ratio(len(self.stockout_dates), self.observed_days)


def summarise(sales: Iterable[Sale], backorders: Iterable[Backorder], lost_sales: Iterable[LostSale],
              start: datetime, end: datetime | None, as_of: datetime) -> DemandSummary:
    fulfilled = sum(s.quantity for s in sales if in_window(s.sold_at, start, end, as_of))
    unmet_rows = [(b.opened_at, b.quantity) for b in backorders if in_window(b.opened_at, start, end, as_of)]
    unmet_rows += [(l.occurred_at, l.quantity) for l in lost_sales if in_window(l.occurred_at, start, end, as_of)]
    unmet = sum(q for _, q in unmet_rows)
    return DemandSummary(fulfilled + unmet, fulfilled, unmet,
                         frozenset(t.astimezone(timezone.utc).date() for t, _ in unmet_rows),
                         observed_days(start, end, as_of))


def apply_unmet_policy(policy: str, unmet_quantity: int) -> dict[str, int]:
    """Exactly one of backorder / lost sale takes the shortfall (P03-TEST-08)."""
    if policy not in UNMET_POLICIES:
        raise DomainError(UNKNOWN_POLICY, f"unmet policy must be one of {', '.join(UNMET_POLICIES)}")
    if unmet_quantity < 0:
        raise ValueError("unmet quantity cannot be negative")
    return {"backorder": unmet_quantity, "lost_sale": 0} if policy == "backlog" else {"backorder": 0, "lost_sale": unmet_quantity}


def censored_vs_latent(sales: Iterable[Sale], backorders: Iterable[Backorder], lost_sales: Iterable[LostSale],
                       latent: Iterable[Latent], product_id: str, location_id: str, first: date, last: date,
                       as_of: datetime) -> dict[str, Any]:
    """Observed (censored) sales and the published latent demand, reported separately (P03-TEST-01).
    A day with unmet demand is censored: its observed sales are a floor on demand, not demand."""
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    obs = {d: 0 for d in days}
    for s in sales:
        d = s.sold_at.astimezone(timezone.utc).date()
        if s.product_id == product_id and s.location_id == location_id and s.sold_at <= as_of and d in obs:
            obs[d] += s.quantity
    cens = {t.astimezone(timezone.utc).date() for t, p, l in
            [(b.opened_at, b.product_id, b.location_id) for b in backorders] +
            [(x.occurred_at, x.product_id, x.location_id) for x in lost_sales]
            if p == product_id and l == location_id and t <= as_of}
    lat = {x.demand_date: x.latent_quantity for x in latent
           if x.product_id == product_id and x.location_id == location_id and first <= x.demand_date <= last}
    return {"observed": {d.isoformat(): obs[d] for d in days},
            "censored_days": sorted(d.isoformat() for d in cens if d in obs),
            "latent": {d.isoformat(): lat[d] for d in days if d in lat},
            "observed_total": sum(obs.values()), "latent_total": sum(lat.values()) if lat else None,
            "shown": "observed (censored during stockouts); latent demand is the generator's published truth"}


# --- common random numbers (D-05, P03-FLOW-08) ------------------------------------------------------------------

def _poisson(rng: random.Random, mean: float) -> int:
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def common_sample(seed: int, days: int, mean_demand: float, lead_low: int, lead_high: int) -> dict[str, list[int]]:
    """One draw of demand and lead times from ``seed``: every policy compared in one run shares this sample."""
    demand_rng, lead_rng = random.Random(f"demand:{seed}"), random.Random(f"lead:{seed}")
    return {"demand": [_poisson(demand_rng, mean_demand) for _ in range(days)],
            "lead_times": [lead_rng.randint(lead_low, lead_high) for _ in range(days)]}


def simulate_policy(sample: dict[str, list[int]], scenario: Scenario, reorder_point: int, target_position: int,
                    moq: int, pack_size: int, initial_stock: int) -> dict[str, Any]:
    """Daily loop in D-01 order: receipts, then demand, then review. Warm-up days are not scored."""
    from .replenishment import pack_round_up
    stock, backlog, pipeline = initial_stock, 0, []  # pipeline: [arrival_day, quantity]
    requested = fulfilled = stockout = scored = 0
    for day, demand in enumerate(sample["demand"]):
        for arr in [p for p in pipeline if p[0] == day]:
            stock += arr[1]
            pipeline.remove(arr)
        if backlog and stock:                      # backlog is served from arrivals first
            served = min(stock, backlog)
            stock, backlog = stock - served, backlog - served
        sold = min(stock, demand)
        stock -= sold
        short = demand - sold
        if scenario.unmet_policy == "backlog":
            backlog += short
        if day >= scenario.warmup_days:
            scored += 1
            requested += demand
            fulfilled += sold
            stockout += 1 if short else 0
        position = stock + sum(p[1] for p in pipeline) - backlog
        if position < reorder_point:
            qty = pack_round_up(max(target_position - position, moq), pack_size)
            pipeline.append([day + sample["lead_times"][day], qty])
    return {"scenario_id": scenario.scenario_id, "requested": requested, "fulfilled": fulfilled,
            "fill_rate": ratio(fulfilled, requested), "stockout_days": stockout, "scored_days": scored}


def compare_policies(scenarios: list[Scenario], days: int, mean_demand: float, lead_low: int, lead_high: int,
                     reorder_point: int, target_position: int, moq: int, pack_size: int,
                     initial_stock: int) -> dict[str, Any]:
    """Every scenario is run on the SAME sample (same seed); scenarios with different seeds are refused."""
    seeds = {s.seed for s in scenarios}
    if len(seeds) != 1:
        raise DomainError(POLICY_SEED_MISMATCH, "policies are compared on common random numbers: every scenario "
                          "must declare the same seed", details={"seeds": sorted(seeds)})
    seed = seeds.pop()
    reps = max(s.replications for s in scenarios)
    results: dict[str, list[dict[str, Any]]] = {s.scenario_id: [] for s in scenarios}
    sample_hashes = []
    for rep in range(reps):
        sample = common_sample(seed + rep, days, mean_demand, lead_low, lead_high)
        sample_hashes.append(hash((tuple(sample["demand"]), tuple(sample["lead_times"]))))
        for s in scenarios:
            results[s.scenario_id].append(simulate_policy(sample, s, reorder_point, target_position, moq, pack_size,
                                                          initial_stock))
    return {"seed": seed, "replications": reps, "sample_hashes": sample_hashes, "results": results}
