"""Discrete-event queue simulator (D-04). Pure and deterministic: the same seed gives the same path.

* ``agents`` identical servers, non-preemptive; ``fifo`` is first-in first-out, ``fifo_within_priority`` serves the
  lowest priority number first and FIFO inside a class (P1 overtakes a waiting P2, a P2 never overtakes an earlier P2).
* Service is deterministic (``service_minutes``) or exponential with that mean; arrivals are listed in
  ``arrivals`` or drawn as a Poisson process of ``arrival_rate_per_hour``. Times are exact rationals (random draws
  are rounded to 1/10000 minute), so the golden case reproduces to the digit.
* Demand (arrivals, priorities, service times) is generated from three independent ``random.Random`` streams derived
  from the seed and BEFORE any dispatching, so two policies run on the same seed see the same demand path
  (common random numbers, P04-DOMAIN-05).
* Declared horizon: arrivals at or after it are not generated, no service starts at or after it (a ticket still
  waiting is ``censored``), service already begun runs to completion. Warm-up: tickets arriving before
  ``warmup_minutes`` still occupy servers but are left out of every statistic (P04-TEST-09).
"""
from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any

from .timeutil import d4, d6, mean, nearest_rank

DISCIPLINES = ("fifo", "fifo_within_priority")
SERVICES = ("deterministic", "exponential")
_QUANTUM = 10_000  # random draws are rounded to 1/10000 minute
_CONFIG_KEYS = {"agents", "service_minutes", "arrivals", "priorities", "arrival_rate_per_hour", "priority_mix",
                "service", "discipline"}
DEFAULT_PRIORITY = "P2"
MAX_TICKETS = 20_000
#: Two-sided 95 % Student-t critical values by degrees of freedom (1..50, D-09: R4-11 needs 50 replications);
#: 2.000 beyond (within 1 % of the true value for 51..120 degrees of freedom).
_T95 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
        2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
        2.040, 2.037, 2.035, 2.032, 2.030, 2.028, 2.026, 2.024, 2.023, 2.021,
        2.020, 2.018, 2.017, 2.015, 2.014, 2.013, 2.012, 2.011, 2.010, 2.009)


def _num(v: Any, name: str, *, positive: bool = False, nonneg: bool = False) -> Fraction:
    """A JSON number (int or float) or a decimal string as an exact Fraction."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ValueError(f"{name} must be a number")
    try:
        f = Fraction(str(v)) if not isinstance(v, int) else Fraction(v)
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"{name} must be a finite number") from None
    if isinstance(v, float) and v != v:
        raise ValueError(f"{name} must be finite")
    if positive and f <= 0:
        raise ValueError(f"{name} must be positive")
    if nonneg and f < 0:
        raise ValueError(f"{name} must not be negative")
    return f


@dataclass(frozen=True)
class SimConfig:
    agents: int
    service_minutes: Fraction
    arrivals: tuple[Fraction, ...] | None
    priorities: tuple[str, ...] | None
    arrival_rate_per_hour: Fraction | None
    priority_mix: tuple[tuple[str, Fraction], ...]
    service: str
    discipline: str


def parse_config(cfg: Any) -> SimConfig:
    """Validate a run config; ``ValueError`` (one message) on anything unusable."""
    if not isinstance(cfg, dict):
        raise ValueError("config must be an object")
    extra = set(cfg) - _CONFIG_KEYS
    if extra:
        raise ValueError(f"unknown config field(s): {', '.join(sorted(extra))}")
    agents = cfg.get("agents", 1)
    if isinstance(agents, bool) or not isinstance(agents, int) or not 1 <= agents <= 1000:
        raise ValueError("agents must be an integer from 1 to 1000")
    if "service_minutes" not in cfg:
        raise ValueError("service_minutes is required")
    svc = _num(cfg["service_minutes"], "service_minutes", positive=True)
    service = cfg.get("service", "deterministic")
    if service not in SERVICES:
        raise ValueError(f"service must be one of {', '.join(SERVICES)}")
    discipline = cfg.get("discipline", "fifo")
    if discipline not in DISCIPLINES:
        raise ValueError(f"discipline must be one of {', '.join(DISCIPLINES)}")
    arrivals = cfg.get("arrivals")
    rate = cfg.get("arrival_rate_per_hour")
    if (arrivals is None) == (rate is None):
        raise ValueError("give exactly one of arrivals and arrival_rate_per_hour")
    arr_t: tuple[Fraction, ...] | None = None
    pri_t: tuple[str, ...] | None = None
    rate_f: Fraction | None = None
    if arrivals is not None:
        if not isinstance(arrivals, list) or len(arrivals) > MAX_TICKETS:
            raise ValueError(f"arrivals must be a list of at most {MAX_TICKETS} minutes")
        arr_t = tuple(_num(a, "arrivals[]", nonneg=True) for a in arrivals)
        pris = cfg.get("priorities")
        if pris is not None:
            if not isinstance(pris, list) or len(pris) != len(arrivals) or any(p not in ("P1", "P2", "P3") for p in pris):
                raise ValueError("priorities must list one of P1, P2, P3 per arrival")
            pri_t = tuple(pris)
    else:
        rate_f = _num(rate, "arrival_rate_per_hour", positive=True)
    mix_raw = cfg.get("priority_mix")
    if mix_raw is None:
        mix: tuple[tuple[str, Fraction], ...] = ((DEFAULT_PRIORITY, Fraction(1)),)
    else:
        if not isinstance(mix_raw, dict) or not mix_raw or any(k not in ("P1", "P2", "P3") for k in mix_raw):
            raise ValueError("priority_mix maps P1, P2, P3 to weights")
        mix = tuple(sorted((k, _num(v, "priority_mix", nonneg=True)) for k, v in mix_raw.items()))
        if sum(w for _, w in mix) <= 0:
            raise ValueError("priority_mix needs a positive weight")
    return SimConfig(agents, svc, arr_t, pri_t, rate_f, mix, service, discipline)


def _q(x: float) -> Fraction:
    return Fraction(round(x * _QUANTUM), _QUANTUM)


@dataclass(frozen=True)
class Demand:
    index: int
    arrival: Fraction
    priority: str
    service: Fraction

    @property
    def ticket_id(self) -> str:
        return f"t-{self.index + 1:03d}"


def build_demand(cfg: SimConfig, seed: int, horizon: Fraction) -> list[Demand]:
    """The demand path of a seed: independent streams for arrivals, priorities and service times."""
    rng_a = random.Random(f"{seed}:arrivals")
    rng_p = random.Random(f"{seed}:priority")
    rng_s = random.Random(f"{seed}:service")
    if cfg.arrivals is not None:
        order = sorted(range(len(cfg.arrivals)), key=lambda i: (cfg.arrivals[i], i))
        rows = [(cfg.arrivals[i], cfg.priorities[i] if cfg.priorities else DEFAULT_PRIORITY) for i in order]
        rows = [r for r in rows if r[0] < horizon]
    else:
        assert cfg.arrival_rate_per_hour is not None
        rate_min = float(cfg.arrival_rate_per_hour) / 60.0
        names = [k for k, _ in cfg.priority_mix]
        weights = [float(w) for _, w in cfg.priority_mix]
        rows, t = [], Fraction(0)
        while len(rows) < MAX_TICKETS:
            t += _q(rng_a.expovariate(rate_min))
            if t >= horizon:
                break
            rows.append((t, rng_p.choices(names, weights)[0]))
    out: list[Demand] = []
    for i, (arr, pri) in enumerate(rows):
        svc = cfg.service_minutes if cfg.service == "deterministic" else max(
            _q(rng_s.expovariate(1.0 / float(cfg.service_minutes))), Fraction(1, _QUANTUM))
        out.append(Demand(i, arr, pri, svc))
    return out


@dataclass(frozen=True)
class Served:
    demand: Demand
    start: Fraction | None      # None: still waiting at the horizon (censored)
    end: Fraction | None
    server: int | None

    @property
    def wait(self) -> Fraction | None:
        return None if self.start is None else self.start - self.demand.arrival


def dispatch(demand: list[Demand], agents: int, discipline: str, horizon: Fraction) -> list[Served]:
    """Serve ``demand`` on ``agents`` identical servers; see the module docstring for the horizon rule."""
    n = len(demand)
    rank = (lambda d: ("P1", "P2", "P3").index(d.priority)) if discipline == "fifo_within_priority" else (lambda d: 0)
    free = [Fraction(0)] * agents
    waiting: list[tuple[int, Fraction, int]] = []
    result: dict[int, Served] = {}
    i = 0
    while True:
        sf = min(free)
        if not waiting:
            if i >= n:
                break
            d = max(sf, demand[i].arrival)
        else:
            d = sf
        while i < n and demand[i].arrival <= d:
            heapq.heappush(waiting, (rank(demand[i]), demand[i].arrival, i))
            i += 1
        if d >= horizon:
            break
        _, _, k = heapq.heappop(waiting)
        j = free.index(sf)
        end = d + demand[k].service
        free[j] = end
        result[k] = Served(demand[k], d, end, j)
    for idx in range(n):
        result.setdefault(idx, Served(demand[idx], None, None, None))
    return [result[i] for i in range(n)]


@dataclass
class SimulationResult:
    simulation_id: str
    seed: int
    warmup_minutes: Fraction
    horizon_minutes: Fraction
    served: list[Served]
    events: list[dict[str, str]] = field(default_factory=list)

    @property
    def counted(self) -> list[Served]:
        """Tickets that started service and arrived after the warm-up (the statistics population)."""
        return [s for s in self.served if s.start is not None and s.demand.arrival >= self.warmup_minutes]

    @property
    def waits(self) -> list[Fraction]:
        return [s.wait for s in self.counted if s.wait is not None]

    @property
    def mean_wait(self) -> Fraction | None:
        return mean(self.waits)

    @property
    def final_completion(self) -> Fraction | None:
        ends = [s.end for s in self.counted if s.end is not None]
        return max(ends) if ends else None

    @property
    def warmup_ticket_ids(self) -> list[str]:
        return [s.demand.ticket_id for s in self.served if s.demand.arrival < self.warmup_minutes]

    @property
    def censored_ticket_ids(self) -> list[str]:
        return [s.demand.ticket_id for s in self.served if s.start is None]

    def golden(self) -> dict[str, Any]:
        """Exactly the shape of ``expected.json`` ``simulation`` (P04-GOLD-01)."""
        return {"simulation_id": self.simulation_id, "waits_minutes": [d4(w) for w in self.waits],
                "mean_wait_minutes": d4(self.mean_wait), "final_completion_minute": d4(self.final_completion),
                "events": self.events}

    def statistics(self) -> dict[str, Any]:
        """Extra, labelled-as-estimate statistics beside the golden shape (warm-up excluded)."""
        by_pri: dict[str, list[Fraction]] = {}
        for s in self.counted:
            by_pri.setdefault(s.demand.priority, []).append(s.wait)  # type: ignore[arg-type]
        return {
            "label": "simulated estimate, not an observed result",
            "seed": self.seed, "warmup_minutes": d4(self.warmup_minutes), "horizon_minutes": d4(self.horizon_minutes),
            "tickets_generated": len(self.served), "tickets_counted": len(self.counted),
            "warmup_excluded": len(self.warmup_ticket_ids), "warmup_ticket_ids": self.warmup_ticket_ids,
            "censored_at_horizon": len(self.censored_ticket_ids),
            "p90_wait_minutes": d4(nearest_rank(self.waits, Fraction(9, 10))),
            "max_wait_minutes": d4(max(self.waits)) if self.waits else None,
            "wait_by_priority": {p: {"count": len(w), "mean_wait_minutes": d4(mean(w)),
                                     "p90_wait_minutes": d4(nearest_rank(w, Fraction(9, 10)))}
                                 for p, w in sorted(by_pri.items())},
        }


def _events(simulation_id: str, served: list[Served]) -> list[dict[str, str]]:
    """The golden order: every service_started in ticket order, then every resolved in ticket order."""
    rows: list[tuple[str, Served, Fraction]] = []
    for kind, pick in (("service_started", lambda s: s.start), ("resolved", lambda s: s.end)):
        rows += [(kind, s, pick(s)) for s in served if pick(s) is not None]
    return [{"simulation_event_id": f"se-{k + 1:03d}", "simulation_id": simulation_id,
             "ticket_id": s.demand.ticket_id, "event_type": kind, "event_at": d4(at)}
            for k, (kind, s, at) in enumerate(rows)]


def simulate(config: dict[str, Any] | SimConfig, seed: int, warmup_minutes: Any = 0, horizon_minutes: Any = 60,
             simulation_id: str = "sim") -> SimulationResult:
    """Run one replication. ``config`` is a run config (see ``parse_config``) or a parsed ``SimConfig``."""
    cfg = config if isinstance(config, SimConfig) else parse_config(config)
    warm = _num(warmup_minutes, "warmup_minutes", nonneg=True)
    horizon = _num(horizon_minutes, "horizon_minutes", positive=True)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    served = dispatch(build_demand(cfg, seed, horizon), cfg.agents, cfg.discipline, horizon)
    return SimulationResult(simulation_id, seed, warm, horizon, served, _events(simulation_id, served))


def replicate(config: dict[str, Any] | SimConfig, seed: int, replications: int, warmup_minutes: Any = 0,
              horizon_minutes: Any = 60, simulation_id: str = "sim") -> list[SimulationResult]:
    """Replication r uses seed ``seed + r``; the first one is the run itself."""
    return [simulate(config, seed + r, warmup_minutes, horizon_minutes, simulation_id) for r in range(replications)]


def mean_ci95(values: list[Fraction]) -> dict[str, Any]:
    """Mean and a 95 % Student-t half-width over replications (None with fewer than two)."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "ci95_half_width": None}
    m = sum(values, Fraction(0)) / n
    if n < 2:
        return {"n": n, "mean": d4(m), "ci95_half_width": None}
    var = sum(((v - m) ** 2 for v in values), Fraction(0)) / (n - 1)
    t = _T95[n - 2] if n - 1 <= len(_T95) else 2.000
    half = Fraction(t).limit_denominator(1000) * Fraction(float(var) ** 0.5 / n ** 0.5).limit_denominator(10 ** 8)
    return {"n": n, "mean": d4(m), "ci95_half_width": d4(half)}


def replication_report(config: dict[str, Any], seed: int, replications: int, warmup_minutes: Any = 0,
                       horizon_minutes: Any = 60) -> dict[str, Any]:
    """D-09 / R4-11: one run is one draw, so a published run carries replications beside it: replication r uses seed
    ``seed + r``; the mean of the per-replication mean waits has its count and a 95 % interval (an estimate)."""
    runs = replicate(config, seed, replications, warmup_minutes, horizon_minutes, "replication")
    waits = [r.mean_wait for r in runs]
    return {"label": "simulated estimate, not an observed result", "seed": seed, "replications": replications,
            "seeds": [seed + r for r in range(replications)],
            "mean_wait_minutes": mean_ci95([w for w in waits if w is not None]),
            "replications_without_a_wait": sum(1 for w in waits if w is None),
            "censored_tickets_total": sum(len(r.censored_ticket_ids) for r in runs),
            "per_replication_mean_wait_minutes": [d4(w) for w in waits]}


def compare_policies(baseline: dict[str, Any], proposal: dict[str, Any], seed: int, replications: int,
                     warmup_minutes: Any = 0, horizon_minutes: Any = 60) -> dict[str, Any]:
    """Two configs on the SAME seeds and therefore the same demand paths; the paired difference per replication is
    summarised with the replication count and a confidence interval (D-04, P04-MET-12). An estimate, labelled as one."""
    base = replicate(baseline, seed, replications, warmup_minutes, horizon_minutes, "baseline")
    prop = replicate(proposal, seed, replications, warmup_minutes, horizon_minutes, "proposal")
    pairs = [(b.mean_wait, p.mean_wait) for b, p in zip(base, prop)]
    paired = [(b, p) for b, p in pairs if b is not None and p is not None]
    diffs = [p - b for b, p in paired]
    same_demand = all([(s.demand.arrival, s.demand.priority) for s in b.served] ==
                      [(s.demand.arrival, s.demand.priority) for s in p.served] for b, p in zip(base, prop))
    return {
        "label": "simulated estimate, not an observed result", "seed": seed, "replications": replications,
        "seeds": [seed + r for r in range(replications)], "same_demand_paths": same_demand,
        "baseline_mean_wait_minutes": mean_ci95([b for b, _ in paired]),
        "proposal_mean_wait_minutes": mean_ci95([p for _, p in paired]),
        "difference_mean_wait_minutes": mean_ci95(diffs),
        "paired_replications": len(paired),
        "proposal_better": (sum(diffs, Fraction(0)) < 0) if diffs else None,
    }


# --- training window fit and holdout validation (P04-DOMAIN-02/03, P04-TEST-12) ---------------------------------

def arrival_rate_per_hour(arrivals: list[datetime], start: datetime, end: datetime) -> Fraction:
    """Arrivals per hour in the half-open window [start, end)."""
    hours = Fraction(int((end - start).total_seconds()), 3600)
    if hours <= 0:
        raise ValueError("window must be positive")
    return Fraction(sum(1 for a in arrivals if start <= a < end)) / hours


def holdout_report(arrivals: list[datetime], train: tuple[datetime, datetime], holdout: tuple[datetime, datetime],
                   tolerance: Fraction = Fraction(1, 10)) -> dict[str, Any]:
    """The intensity is estimated on the training window ONLY and compared with the holdout window; a change larger
    than ``tolerance`` (relative) is reported as ``intensity_changed`` and never hidden."""
    fit = arrival_rate_per_hour(arrivals, *train)
    seen = arrival_rate_per_hour(arrivals, *holdout)
    change = None if fit == 0 else (seen - fit) / fit
    changed = (seen != 0) if fit == 0 else abs(change) > tolerance  # type: ignore[arg-type]
    return {"estimated_on": "training window only", "train_rate_per_hour": d6(fit),
            "holdout_rate_per_hour": d6(seen), "relative_change": d6(change), "tolerance": d6(tolerance),
            "intensity_changed": bool(changed),
            "note": ("holdout intensity differs from the training estimate: forecasts and simulations built on the "
                     "training rate are optimistic or pessimistic by this much" if changed
                     else "holdout intensity is within tolerance of the training estimate")}
