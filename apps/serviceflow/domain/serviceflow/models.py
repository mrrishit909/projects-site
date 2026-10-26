"""Typed records for the 12 input entities and the population the metrics run over."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .contract import (ENTITIES, EMPLOYMENT_TYPES, EVENT_TYPES, OPENERS, PRIORITIES, PRIORITY_POLICIES)
from .simulation import parse_config
from .timeutil import iso_z, parse_ts, parse_ts_opt


#: D-09 / R4-17: seeds are JSON-safe integers in both domains.
SEED_MAX = 2 ** 53 - 1


def _s(v: object) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > 256:
        raise ValueError("non-empty string required")
    return v


def _s_opt(v: object) -> str | None:
    return None if v is None else _s(v)


def _int(v: object, minimum: int, maximum: int | None = None) -> int:
    """D-09 / R4-17: an integer field takes a JSON number whose VALUE is an integer (``30`` and ``30.0`` alike: a
    JavaScript runtime cannot tell them apart after ``JSON.parse``, so Python must not either). 30.5, NaN, a
    boolean or a string is refused in both domains."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum or (maximum is not None and v > maximum):
        raise ValueError(f"integer >= {minimum} required")
    return v


def _bool(v: object) -> bool:
    if not isinstance(v, bool):
        raise ValueError("boolean required")
    return v


def _choice(v: object, allowed: tuple[str, ...]) -> str:
    if v not in allowed:
        raise ValueError(f"one of {allowed} required")
    return str(v)


def _zone(v: object) -> str:
    name = _s(v)
    try:
        ZoneInfo(name)
    except Exception:
        raise ValueError("IANA timezone required") from None
    return name


@dataclass(frozen=True)
class Customer:
    customer_id: str
    segment: str
    timezone: str
    created_at: datetime
    synthetic: bool


@dataclass(frozen=True)
class Queue:
    queue_id: str
    queue_name: str
    priority_policy: str
    calendar_id: str
    active: bool


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    customer_id: str
    queue_id: str
    priority: str
    created_at: datetime
    channel: str


@dataclass(frozen=True)
class TicketEvent:
    event_id: str
    ticket_id: str
    event_type: str
    occurred_at: datetime
    actor_id: str | None
    queue_id: str | None
    agent_id: str | None


@dataclass(frozen=True)
class Agent:
    agent_id: str
    agent_name: str
    timezone: str
    employment_type: str
    active: bool
    max_concurrent: int


@dataclass(frozen=True)
class Skill:
    skill_id: str
    skill_name: str
    description: str | None
    active: bool
    created_at: datetime


@dataclass(frozen=True)
class AgentSkill:
    agent_skill_id: str
    agent_id: str
    skill_id: str
    proficiency: int
    effective_from: datetime


@dataclass(frozen=True)
class QueueSkill:
    queue_id: str
    skill_id: str


@dataclass(frozen=True)
class Shift:
    shift_id: str
    agent_id: str
    starts_at: datetime
    ends_at: datetime
    break_minutes: int


@dataclass(frozen=True)
class SlaPolicy:
    sla_policy_id: str
    priority: str
    first_response_minutes: int
    resolution_minutes: int
    calendar_id: str


@dataclass(frozen=True)
class Survey:
    survey_id: str
    ticket_id: str
    response_at: datetime | None
    score: int | None
    invited_at: datetime | None


@dataclass(frozen=True)
class SimulationRun:
    simulation_id: str
    seed: int
    warmup_minutes: int | float
    policy_version: str
    horizon_minutes: int | float
    config: dict[str, Any]


def _customer(r: dict) -> Customer:
    return Customer(_s(r["customer_id"]), _s(r["segment"]), _zone(r["timezone"]), parse_ts(r["created_at"]),
                    _bool(r.get("synthetic", True)))


def _queue(r: dict) -> Queue:
    return Queue(_s(r["queue_id"]), _s(r["queue_name"]), _choice(r["priority_policy"], PRIORITY_POLICIES),
                 _s(r["calendar_id"]), _bool(r["active"]))


def _ticket(r: dict) -> Ticket:
    return Ticket(_s(r["ticket_id"]), _s(r["customer_id"]), _s(r["queue_id"]), _choice(r["priority"], PRIORITIES),
                  parse_ts(r["created_at"]), _s(r["channel"]))


def _event(r: dict) -> TicketEvent:
    t = _choice(r["event_type"], EVENT_TYPES)
    e = TicketEvent(_s(r["event_id"]), _s(r["ticket_id"]), t, parse_ts(r["occurred_at"]), _s_opt(r.get("actor_id")),
                    _s_opt(r.get("queue_id")), _s_opt(r.get("agent_id")))
    if t in OPENERS and e.agent_id is None and t == "service_started":
        raise ValueError("service_started needs an agent_id")
    if t in ("replied_human", "acknowledged_bot") and e.actor_id is None:
        raise ValueError(f"{t} needs an actor_id")
    if t in ("created", "transferred") and e.queue_id is None:
        raise ValueError(f"{t} needs a queue_id")
    return e


def _agent(r: dict) -> Agent:
    return Agent(_s(r["agent_id"]), _s(r["agent_name"]), _zone(r["timezone"]),
                 _choice(r["employment_type"], EMPLOYMENT_TYPES), _bool(r["active"]),
                 _int(r.get("max_concurrent", 1), 1, 100))


def _skill(r: dict) -> Skill:
    return Skill(_s(r["skill_id"]), _s(r["skill_name"]), _s_opt(r.get("description")), _bool(r["active"]),
                 parse_ts(r["created_at"]))


def _agent_skill(r: dict) -> AgentSkill:
    return AgentSkill(_s(r["agent_skill_id"]), _s(r["agent_id"]), _s(r["skill_id"]), _int(r["proficiency"], 1, 5),
                      parse_ts(r["effective_from"]))


def _queue_skill(r: dict) -> QueueSkill:
    return QueueSkill(_s(r["queue_id"]), _s(r["skill_id"]))


def _shift(r: dict) -> Shift:
    s = Shift(_s(r["shift_id"]), _s(r["agent_id"]), parse_ts(r["starts_at"]), parse_ts(r["ends_at"]),
              _int(r["break_minutes"], 0))
    if s.ends_at <= s.starts_at:
        raise ValueError("ends_at must be after starts_at")
    if s.break_minutes * 60 > (s.ends_at - s.starts_at).total_seconds():
        raise ValueError("break longer than the shift")
    return s


def _sla(r: dict) -> SlaPolicy:
    return SlaPolicy(_s(r["sla_policy_id"]), _choice(r["priority"], PRIORITIES), _int(r["first_response_minutes"], 1),
                     _int(r["resolution_minutes"], 1), _s(r["calendar_id"]))


def _survey(r: dict) -> Survey:
    score = r.get("score")
    resp = parse_ts_opt(r.get("response_at"))
    if score is not None:
        score = _int(score, 1, 5)
    if (score is None) != (resp is None):
        raise ValueError("score and response_at go together")
    return Survey(_s(r["survey_id"]), _s(r["ticket_id"]), resp, score, parse_ts_opt(r.get("invited_at")))


def _sim_run(r: dict) -> SimulationRun:
    cfg = r["config"]
    parse_config(cfg)  # ValueError on an unusable config
    warm, horizon = r["warmup_minutes"], r["horizon_minutes"]
    for v in (warm, horizon):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise ValueError("minutes must be non-negative numbers")
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    return SimulationRun(_s(r["simulation_id"]), _int(r["seed"], -SEED_MAX, SEED_MAX), warm, _s(r["policy_version"]),
                         horizon, cfg)


#: Primary key field per entity (queue_skills: the pair, joined).
ID_FIELD = {"customers": "customer_id", "queues": "queue_id", "tickets": "ticket_id", "ticket_events": "event_id",
            "agents": "agent_id", "skills": "skill_id", "agent_skills": "agent_skill_id", "queue_skills": "queue_id",
            "shifts": "shift_id", "sla_policies": "sla_policy_id", "surveys": "survey_id",
            "simulation_runs": "simulation_id"}


def row_id(entity: str, row: Any) -> str:
    """The id of a raw row or typed record (queue_skills: ``queue_id/skill_id``); '' when unusable."""
    get = row.get if isinstance(row, dict) else (lambda k, d=None: getattr(row, k, d))
    if entity == "queue_skills":
        q, s = get("queue_id"), get("skill_id")
        return f"{q}/{s}" if isinstance(q, str) and isinstance(s, str) else ""
    v = get(ID_FIELD[entity])
    return v if isinstance(v, str) else ""


def parsers() -> dict[str, Callable[[dict], Any]]:
    return {"customers": _customer, "queues": _queue, "tickets": _ticket, "ticket_events": _event,
            "agents": _agent, "skills": _skill, "agent_skills": _agent_skill, "queue_skills": _queue_skill,
            "shifts": _shift, "sla_policies": _sla, "surveys": _survey, "simulation_runs": _sim_run}


@dataclass(frozen=True)
class RejectedRecord:
    entity: str
    id: str
    reason_code: str
    raw_row: Any
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"entity": self.entity, "id": self.id, "status": "rejected", "reason_code": self.reason_code,
                "raw_row": self.raw_row}


@dataclass
class Population:
    """Typed accepted records of every entity, with the lookups the metrics need."""
    customers: list[Customer] = field(default_factory=list)
    queues: list[Queue] = field(default_factory=list)
    tickets: list[Ticket] = field(default_factory=list)
    ticket_events: list[TicketEvent] = field(default_factory=list)
    agents: list[Agent] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    agent_skills: list[AgentSkill] = field(default_factory=list)
    queue_skills: list[QueueSkill] = field(default_factory=list)
    shifts: list[Shift] = field(default_factory=list)
    sla_policies: list[SlaPolicy] = field(default_factory=list)
    surveys: list[Survey] = field(default_factory=list)
    simulation_runs: list[SimulationRun] = field(default_factory=list)

    @classmethod
    def from_rows(cls, rows: dict[str, list[dict]]) -> "Population":
        """Trusted rows (e.g. read from the tables) to typed records; no ingest rules are re-applied."""
        ps = parsers()
        pop = cls()
        for ent in ENTITIES:
            setattr(pop, ent, [ps[ent](dict(r)) for r in rows.get(ent, [])])
        return pop

    def events_by_ticket(self) -> dict[str, list[TicketEvent]]:
        out: dict[str, list[TicketEvent]] = {t.ticket_id: [] for t in self.tickets}
        for e in self.ticket_events:
            out.setdefault(e.ticket_id, []).append(e)
        return out


def event_row(e: TicketEvent) -> dict[str, Any]:
    return {"event_id": e.event_id, "ticket_id": e.ticket_id, "event_type": e.event_type,
            "occurred_at": iso_z(e.occurred_at), "actor_id": e.actor_id, "queue_id": e.queue_id,
            "agent_id": e.agent_id}
