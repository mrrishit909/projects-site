"""The metrics (D-01..D-05): signup conversion, funnel, activation, retention, feature adoption and the experiment block.

``compute`` returns exactly the keys of ``expected.json["metrics"]`` (``METRIC_KEYS``), beside ``tracking_quality`` and
``identity``. Everything is exact (Fraction, Decimal), rounded ROUND_HALF_UP once; a zero denominator is ``None``, never 0.
The calculation follows ``tests/reference_check.py`` (the independent stdlib reference) leaf by leaf.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from fractions import Fraction as F
from typing import Any, Callable

from .contract import GROUPS, METRIC_KEYS, WEEK4
from .errors import INVALID_GROUP, DomainError
from .events import AEvent, Canon, canonicalise
from .models import FunnelDef, Plan, Population, Windows
from .stats import chi2_sf_df1, dsqrt, newcombe, normal_two_sided_p, q, q6, ratio, sqrt_frac, t_crit, wilson, z_crit
from .timeutil import UTC, iso_z, local_date

SEGMENT_FIELDS = ("plan", "segment", "timezone")


@dataclass
class Computation:
    metrics: dict[str, Any]
    tracking_quality: dict[str, int]
    identity: dict[str, int]
    empty_population: bool
    canon: Canon
    warnings: list[dict[str, Any]] = field(default_factory=list)
    experiment_version_id: str | None = None


class Ctx:
    """What the metrics share for one cutoff: canonical events, account signups, sessions and (optionally) the set of
    accounts an analysis is restricted to (a segment, a variant, a pre-assignment exclusion)."""

    def __init__(self, pop: Population, cutoff: datetime, canon: Canon, allowed: set[str] | None = None) -> None:
        self.pop, self.cutoff, self.canon, self.allowed = pop, cutoff, canon, allowed
        self.users = {u.user_id: u for u in pop.users}
        self.accounts = {a.account_id: a for a in pop.accounts}
        self.props = canon.props
        self.signup_at: dict[str, datetime] = {}
        self.act_events: dict[str, list[datetime]] = defaultdict(list)
        self.errors: dict[str, list[datetime]] = defaultdict(list)
        for a in canon.analysed:
            if a.account is None or not self.ok(a.account):
                continue
            if a.name == "signup":
                if a.account not in self.signup_at or a.at < self.signup_at[a.account]:
                    self.signup_at[a.account] = a.at
            elif a.name == "activated":
                self.act_events[a.account].append(a.at)
            elif a.name == "product_error":
                self.errors[a.account].append(a.at)
        self.sess: dict[str, list[datetime]] = defaultdict(list)
        for s in pop.sessions:
            u = self.users.get(s.user_id)
            if u is None or u.bot_flag or self.accounts[u.account_id].internal or not self.ok(u.account_id):
                continue
            if s.started_at < cutoff:
                self.sess[u.account_id].append(s.started_at)

    def ok(self, account: str) -> bool:
        return self.allowed is None or account in self.allowed

    def local(self, account: str, t: datetime) -> date:
        return local_date(t, self.accounts[account].timezone)

    def activated_within(self, account: str, days: int) -> bool:
        s = self.signup_at[account]
        return any(s <= t < s + timedelta(days=days) for t in self.act_events[account])

    def mature(self, account: str, days: int) -> bool:
        return self.signup_at[account] + timedelta(days=days) <= self.cutoff


# ---------------------------------------------------------------------------------------------------- MET-01 .. MET-06
def signup_conversion(ctx: Ctx, w: Windows) -> dict[str, Any]:
    """D-01/D-P6-10: distinct anonymous_id with a visit in [from, to) over those with a signup (same anonymous_id) in it."""
    visitors = {a.event.anonymous_id for a in ctx.canon.analysed
                if a.name == "visit" and a.event.anonymous_id and w.signup_from <= a.at < w.signup_to}
    signed = {a.event.anonymous_id for a in ctx.canon.analysed
              if a.name == "signup" and a.event.anonymous_id in visitors and w.signup_from <= a.at < w.signup_to}
    return {"window": {"from": iso_z(w.signup_from), "to": iso_z(w.signup_to)}, "unit": "distinct anonymous_id",
            "visitors": len(visitors), "signed_up": len(signed), "rate": q6(ratio(len(signed), len(visitors)))}


def funnel(ctx: Ctx, fd: FunnelDef, window: tuple[datetime, datetime] | None = None) -> dict[str, Any]:
    """D-02/D-P6-9: ordered steps with a maximum gap (inclusive); a unit reaches step k only after step k-1; no re-anchoring."""
    f_from, f_to = window or (fd.window_from, fd.window_to)
    gap = timedelta(hours=fd.max_gap_hours)
    by_vk: dict[str, list[AEvent]] = defaultdict(list)
    for a in ctx.canon.analysed:
        by_vk[a.visitor].append(a)
    reached: list[set[str]] = [set() for _ in fd.steps]
    for vk, evs in by_vk.items():
        first = sorted(a.at for a in evs if a.name == fd.steps[0] and f_from <= a.at < f_to)
        if not first:
            continue
        prev = first[0]
        reached[0].add(vk)
        for k in range(1, len(fd.steps)):
            nxt = sorted(a.at for a in evs if a.name == fd.steps[k] and prev < a.at <= prev + gap)
            if not nxt:
                break
            reached[k].add(vk)
            prev = nxt[0]
    steps = [{"step": name, "units": len(reached[k]),
              "conversion_from_previous": None if k == 0 else q6(ratio(len(reached[k]), len(reached[k - 1]))),
              "conversion_from_first": q6(ratio(len(reached[k]), len(reached[0])))} for k, name in enumerate(fd.steps)]
    return {"definition_id": fd.definition_id, "version": fd.version, "max_gap_hours": fd.max_gap_hours,
            "window": {"from": iso_z(f_from), "to": iso_z(f_to)}, "steps": steps,
            "overall_conversion": q6(ratio(len(reached[-1]), len(reached[0])))}


def activation(ctx: Ctx, w: Windows) -> dict[str, Any]:
    """D-02: activated within [signup_at, signup_at + days); only mature signups count, immature ones are counted apart."""
    pop = sorted(a for a, s in ctx.signup_at.items() if w.activation_from <= s < w.activation_to)
    mature = [a for a in pop if ctx.mature(a, w.activation_days)]
    n = sum(1 for a in mature if ctx.activated_within(a, w.activation_days))
    return {"window": {"from": iso_z(w.activation_from), "to": iso_z(w.activation_to)}, "window_days": w.activation_days,
            "signups": len(pop), "immature_excluded": len(pop) - len(mature), "mature_accounts": len(mature),
            "activated": n, "rate": q6(ratio(n, len(mature)))}


def _day_indices(ctx: Ctx, account: str) -> list[int]:
    s0 = ctx.local(account, ctx.signup_at[account])
    return [(ctx.local(account, t) - s0).days for t in ctx.sess[account]]


def retention_cohort(ctx: Ctx, w: Windows) -> list[str]:
    """Accounts whose signup date in the account's own calendar lies in [from, to)."""
    return sorted(a for a in ctx.signup_at if w.retention_from <= ctx.local(a, ctx.signup_at[a]) < w.retention_to)


def _matured(ctx: Ctx, account: str, day: int) -> bool:
    """Day ``day`` is complete: local signup date + day + 1 <= local cutoff date (day 7: day 8 has begun; D-02)."""
    return ctx.local(account, ctx.signup_at[account]) + timedelta(days=day + 1) <= local_date(ctx.cutoff, ctx.accounts[account].timezone)


def retention(ctx: Ctx, w: Windows) -> dict[str, Any]:
    """D-02/D-P6-12: exact day 7, on-or-after day 7 and week 4 (days 28-34) are separate figures, on the local calendar."""
    cohort = retention_cohort(ctx, w)
    m7 = [a for a in cohort if _matured(ctx, a, 7)]
    m35 = [a for a in cohort if _matured(ctx, a, WEEK4[1])]
    d7 = [a for a in m7 if 7 in _day_indices(ctx, a)]
    d7plus = [a for a in m7 if any(d >= 7 for d in _day_indices(ctx, a))]
    w4 = [a for a in m35 if any(WEEK4[0] <= d <= WEEK4[1] for d in _day_indices(ctx, a))]
    internal = {a for a, t in ctx.canon.internal_signup_accounts
                if ctx.ok(a) and w.retention_from <= ctx.local(a, t) < w.retention_to}
    return {"signup_window": {"from": w.retention_from.isoformat(), "to": w.retention_to.isoformat()},
            "calendar": "account timezone", "cohort_accounts": len(cohort), "excluded_internal_accounts": len(internal),
            "day7": {"mature_accounts": len(m7), "immature_excluded": len(cohort) - len(m7), "retained": len(d7),
                     "rate": q6(ratio(len(d7), len(m7)))},
            "on_or_after_day7": {"mature_accounts": len(m7), "retained": len(d7plus), "rate": q6(ratio(len(d7plus), len(m7)))},
            "week4": {"mature_accounts": len(m35), "immature_excluded": len(cohort) - len(m35), "retained": len(w4),
                      "rate": q6(ratio(len(w4), len(m35)))}}


#: Columns of the per-cohort retention grid: exact calendar days, then the two ranges (never mixed, TEST-12).
GRID_DAYS = (1, 7, 14, 28)


def retention_grid(ctx: Ctx, w: Windows) -> dict[str, Any]:
    """One row per local signup date of the cohort window; one cell per column. A cell counts the accounts of the cohort
    whose day has completed (mature) and those with a session on exactly that day (or in the range)."""
    rows = []
    cohort = retention_cohort(ctx, w)
    by_date: dict[date, list[str]] = defaultdict(list)
    for a in cohort:
        by_date[ctx.local(a, ctx.signup_at[a])].append(a)
    cols = [(f"day{d}", d, d, d) for d in GRID_DAYS] + [("on_or_after_day7", 7, None, 7), ("week4", WEEK4[0], WEEK4[1], WEEK4[1])]
    for day in sorted(by_date):
        cells = {}
        for name, lo, hi, need in cols:
            mat = [a for a in by_date[day] if _matured(ctx, a, need)]
            hit = [a for a in mat if any(lo <= d <= (hi if hi is not None else 10 ** 9) for d in _day_indices(ctx, a))]
            cells[name] = {"mature_accounts": len(mat), "retained": len(hit), "rate": q6(ratio(len(hit), len(mat)))}
        rows.append({"cohort": day.isoformat(), "accounts": len(by_date[day]), "cells": cells})
    return {"cohort_unit": "account-local signup date", "calendar": "account timezone",
            "columns": [{"name": n, "from_day": lo, "to_day": hi} for n, lo, hi, _ in cols], "rows": rows}


def feature_adoption(ctx: Ctx, w: Windows) -> dict[str, Any]:
    """D-02/D-P6-13: eligible active accounts (plan from the list, a non-bot session in the window) using the feature."""
    active = {a for a, ss in ctx.sess.items() if any(w.adoption_from <= t < w.adoption_to for t in ss)}
    eligible = sorted(a for a in active if ctx.accounts[a].plan in w.eligible_plans)
    uses = [a for a in ctx.canon.analysed if a.name == "feature_used" and a.account in eligible
            and w.adoption_from <= a.at < w.adoption_to and ctx.props.get(a.event.event_id, {}).get("feature") == w.feature]
    adopters = {a.account for a in uses}
    return {"window": {"from": iso_z(w.adoption_from), "to": iso_z(w.adoption_to)}, "feature": w.feature,
            "eligible_plans": list(w.eligible_plans), "eligible_accounts": len(eligible), "adopting_accounts": len(adopters),
            "use_events": len(uses), "rate": q6(ratio(len(adopters), len(eligible)))}


# ---------------------------------------------------------------------------------------------------- the experiment
def accepted_assignments(pop: Population, xv: str, allowed: set[str] | None) -> dict[str, Any]:
    """The first accepted assignment per unit of the version (ingest keeps one; a loaded population is trusted)."""
    out: dict[str, Any] = {}
    for a in sorted((a for a in pop.assignments if a.experiment_version_id == xv), key=lambda a: (a.assigned_at, a.assignment_id)):
        if allowed is None or a.unit_id in allowed:
            out.setdefault(a.unit_id, a)
    return out


def srm_block(plan: Plan, observed: dict[str, int]) -> dict[str, Any]:
    """D-03 MET-10: chi-square against the prespecified allocation; verdict order INSUFFICIENT, MISMATCH, OK."""
    variants = plan.variants
    n = sum(observed.values())
    if n == 0:
        return {"observed": observed, "expected": None, "statistic": None, "p_value": None, "verdict": "INSUFFICIENT"}
    alloc = {v: F(plan.allocation[v]) for v in variants}
    cells = {v: n * alloc[v] for v in variants}
    stat = sum(((observed[v] - cells[v]) ** 2 / cells[v] for v in variants), F(0))
    pv = chi2_sf_df1(stat)
    if any(c < F(plan.srm_min_expected_cell) for c in cells.values()):
        verdict = "INSUFFICIENT"
    elif pv < D(plan.srm_p_threshold):
        verdict = "MISMATCH"
    else:
        verdict = "OK"
    return {"observed": observed, "expected": {v: q(cells[v], 2) for v in variants}, "statistic": q(stat, 6),
            "p_value": q(pv, 6), "df": len(variants) - 1, "verdict": verdict}


def experiment(ctx: Ctx, plan: Plan, run_id: str | None = None) -> dict[str, Any]:
    pop, cutoff = ctx.pop, ctx.cutoff
    xv = plan.experiment_version_id
    variants = plan.variants
    z = F(plan.z)
    accepted = accepted_assignments(pop, xv, ctx.allowed)
    assigned = {v: [a for a in accepted.values() if a.variant == v] for v in variants}
    n_assigned = {v: len(assigned[v]) for v in variants}
    win = plan.activation_window_days
    mat = {v: [a for a in assigned[v] if a.unit_id in ctx.signup_at and ctx.mature(a.unit_id, win)] for v in variants}
    n_total = sum(n_assigned.values())
    srm = srm_block(plan, n_assigned)

    act = {v: sum(1 for a in mat[v] if ctx.activated_within(a.unit_id, win)) for v in variants}
    n_m = {v: len(mat[v]) for v in variants}
    conv = {v: ratio(act[v], n_m[v]) for v in variants}
    per_variant = {}
    for v in variants:
        w = None
        if n_m[v]:
            _, lo, hi = wilson(act[v], n_m[v], z)
            w = {"low": q(lo, 6), "high": q(hi, 6)}
        per_variant[v] = {"assigned": n_assigned[v], "mature_units": n_m[v], "activated": act[v], "conversion": q6(conv[v]),
                          "wilson_95": w}
    c, t = "control", "treatment"
    both = n_m.get(c, 0) > 0 and n_m.get(t, 0) > 0
    abs_lift = (conv[t] - conv[c]) if both else None
    rel = None if (not both or conv[c] == 0) else (conv[t] - conv[c]) / conv[c]

    runs = [r for r in pop.analysis_runs if r.experiment_version_id == xv]
    cand = [r for r in runs if r.analysis_id == run_id] if run_id else [r for r in runs if r.cutoff_at == cutoff]
    run_row = min(cand, key=lambda r: (r.created_at, r.analysis_id)) if cand else None
    hash_ok = plan.hash_valid
    interim = cutoff < plan.planned_end
    if both:
        _, lo, hi = newcombe(act[t], n_m[t], act[c], n_m[c], z)
        includes0 = lo <= 0 <= hi
        interval = {"method": "newcombe_hybrid_score", "confidence": plan.confidence, "z": plan.z, "low": q(lo, 6),
                    "high": q(hi, 6), "low_pp": q(lo * 100, 2), "high_pp": q(hi * 100, 2), "includes_zero": includes0}
        conclusive = (not includes0) and (not interim) and hash_ok
    else:
        interval, conclusive = None, False
    prior = None if run_row is None else sum(1 for r in runs if r.created_at < run_row.created_at)
    run_block = {"analysis_id": run_row.analysis_id if run_row else None, "cutoff_at": iso_z(cutoff),
                 "planned_end": iso_z(plan.planned_end), "interim": interim, "prior_runs": prior,
                 "plan_frozen": bool(runs) and plan.frozen_at <= min(r.created_at for r in runs),
                 "config_hash": plan.config_hash,
                 "config_hash_matches_plan": hash_ok and run_row is not None and run_row.config_hash == plan.config_hash}

    exposed_ids = {x.assignment_id for x in pop.exposures}
    exposed = {v: sum(1 for a in mat[v] if a.assignment_id in exposed_ids) for v in variants}
    n_m_all = sum(n_m.values())
    exposure_block = {"definition": "exposed mature assigned accounts / mature assigned accounts",
                      "by_variant": {v: {"exposed": exposed[v], "units": n_m[v], "rate": q6(ratio(exposed[v], n_m[v]))} for v in variants},
                      "overall": {"exposed": sum(exposed.values()), "units": n_m_all, "rate": q6(ratio(sum(exposed.values()), n_m_all))}}
    exploratory: dict[str, Any] = {"label": "exploratory", "decision_basis": False, "by_variant": {}}
    for v in variants:
        ex = [a for a in mat[v] if a.assignment_id in exposed_ids]
        k = sum(1 for a in ex if ctx.activated_within(a.unit_id, win))
        exploratory["by_variant"][v] = {"exposed_units": len(ex), "activated": k, "conversion": q6(ratio(k, len(ex)))}

    gdays = timedelta(days=plan.guardrail_window_days)
    guard = {}
    for v in variants:
        hit = sum(1 for a in mat[v] if any(a.assigned_at <= e < a.assigned_at + gdays for e in ctx.errors[a.unit_id]))
        guard[v] = {"eligible_units": n_m[v], "units_with_error": hit, "error_rate": q6(ratio(hit, n_m[v]))}

    rev_by: dict[str, D] = defaultdict(lambda: D(0))
    for s in pop.subscriptions:
        if s.status in ("active", "ended") and plan.revenue_from <= s.starts_at < plan.revenue_to:
            rev_by[s.account_id] += s.amount_usd
    revenue = {}
    for v in variants:
        vals = [rev_by[a.unit_id] for a in mat[v]]
        n = len(vals)
        if n == 0:
            revenue[v] = {"units": 0, "total": q(D(0), 2), "mean": None, "interval": None}
            continue
        tot = sum(vals, D(0))
        mean = tot / n
        if n < 2:
            revenue[v] = {"units": n, "total": q(tot, 2), "mean": q(mean, 2), "interval": None}
            continue
        var = sum(((x - mean) ** 2 for x in vals), D(0)) / (n - 1)
        tc = t_crit(n - 1, plan.confidence)
        half = tc * dsqrt(var / n)
        revenue[v] = {"units": n, "total": q(tot, 2), "mean": q(mean, 2),
                      "interval": {"df": n - 1, "t": q(tc, 6), "low": q(mean - half, 2), "high": q(mean + half, 2)}}

    obs_ids = {a.assignment_id: a for a in accepted.values()}
    obs_ok = [o for o in pop.metric_observations if o.assignment_id in obs_ids]
    obs_match = 0
    for o in obs_ok:
        u = obs_ids[o.assignment_id].unit_id
        if u in ctx.signup_at:
            want = "1" if ctx.activated_within(u, win) else "0"
            if o.value == want and o.window_end == ctx.signup_at[u] + timedelta(days=win):
                obs_match += 1
    return {
        "experiment_version_id": xv, "unit_type": plan.unit_type, "allocation": dict(plan.allocation), "run": run_block,
        "assigned_units": n_total, "mature_units": n_m_all, "immature_or_unobserved_excluded": n_total - n_m_all,
        "srm": srm,
        "primary": {"metric": plan.primary_metric, "analysis": "intention_to_treat", "variants": per_variant,
                    "absolute_lift_pp": None if abs_lift is None else q(abs_lift * 100, 2),
                    "relative_lift": q6(rel), "interval": interval, "conclusive": conclusive},
        "exposure": exposure_block, "exploratory_exposed_only": exploratory,
        "guardrail": {"metric": plan.guardrail_metric, "window_days": plan.guardrail_window_days, "by_variant": guard},
        "revenue_per_assigned_account": {"currency": "USD", "window": {"from": iso_z(plan.revenue_from), "to": iso_z(plan.revenue_to)},
                                         "by_variant": revenue},
        "observations": {"rows_accepted": len(obs_ok), "rows_matching_events": obs_match}}


# ---------------------------------------------------------------------------------------------------- the whole set
def select_funnel(pop: Population, definition_id: str | None = None, version: int | None = None) -> FunnelDef | None:
    """The funnel definition to use: the named one (latest version unless given), else the most recently created."""
    cand = [f for f in pop.funnels if (definition_id is None or f.definition_id == definition_id)
            and (version is None or f.version == version)]
    if not cand:
        return None
    if definition_id is not None:
        return max(cand, key=lambda f: f.version)
    return max(cand, key=lambda f: (f.created_at or datetime.min.replace(tzinfo=UTC), f.definition_id, f.version))


def select_plan(pop: Population, xv: str | None) -> Plan | None:
    if xv is not None:
        return pop.plans.get(xv)
    return max(pop.plans.values(), key=lambda p: (p.frozen_at, p.experiment_version_id)) if pop.plans else None


def compute(pop: Population, cutoff: datetime, windows: Windows, funnel_def: FunnelDef | None = None,
            experiment_version_id: str | None = None, run_id: str | None = None, allowed: set[str] | None = None,
            funnel_window: tuple[datetime, datetime] | None = None, canon: Canon | None = None) -> Computation:
    """All six metrics at ``cutoff``. ``allowed`` restricts the account-based metrics to a set of accounts (signup
    conversion and the funnel are measured on visitors and are not restricted)."""
    canon = canon or canonicalise(pop, cutoff)
    ctx = Ctx(pop, cutoff, canon, allowed)
    plan = select_plan(pop, experiment_version_id)
    warnings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {
        "signup_conversion": signup_conversion(ctx, windows),
        "funnel": funnel(ctx, funnel_def, funnel_window) if funnel_def else None,
        "activation": activation(ctx, windows),
        "retention": retention(ctx, windows),
        "feature_adoption": feature_adoption(ctx, windows),
        "experiment": experiment(ctx, plan, run_id) if plan else None}
    if funnel_def is None:
        warnings.append({"code": "NO_FUNNEL_DEFINITION", "message": "no funnel is defined (C03 define-funnel)", "path": "metrics.funnel"})
    if plan is None:
        warnings.append({"code": "NO_ANALYSIS_PLAN", "message": "no frozen analysis plan: the experiment is not analysed",
                         "path": "metrics.experiment"})
    else:
        if not plan.hash_valid:
            warnings.append({"code": "PLAN_HASH_MISMATCH", "message": "config_hash is not the hash of the stored plan",
                             "path": "metrics.experiment.run.config_hash"})
        ex = metrics["experiment"]
        if ex["srm"]["verdict"] == "MISMATCH":
            warnings.append({"code": "SRM_MISMATCH", "message": "the assignment counts do not match the allocation: "
                             "no lift can be trusted and a ship decision is blocked", "path": "metrics.experiment.srm"})
        if ex["run"]["interim"]:
            warnings.append({"code": "INTERIM_RUN", "message": "the cutoff is before planned_end: this is an interim run and "
                             "cannot support a ship decision", "path": "metrics.experiment.run.interim"})
    tq = canon.tracking_quality()
    if tq["received_after_cutoff"]:
        warnings.append({"code": "EVENTS_RECEIVED_AFTER_CUTOFF", "message": f"{tq['received_after_cutoff']} event(s) were received "
                         "after the cutoff and are not in this run (a later cutoff will include them, as a disclosed revision)",
                         "path": "tracking_quality.received_after_cutoff"})
    for key, code, what in (("unknown_identity", "UNKNOWN_IDENTITY_EXCLUDED", "with an unknown identity"),
                            ("bot_events_excluded", "BOT_EVENTS_EXCLUDED", "of bot users"),
                            ("internal_events_excluded", "INTERNAL_EVENTS_EXCLUDED", "of internal accounts")):
        if tq[key]:
            warnings.append({"code": code, "message": f"{tq[key]} event(s) {what} are excluded from every figure",
                             "path": f"tracking_quality.{key}"})
    empty = len(canon.canon) == 0 and (metrics["experiment"] is None or metrics["experiment"]["assigned_units"] == 0)
    assert tuple(metrics) == METRIC_KEYS
    return Computation(metrics, tq, canon.identity(), empty, canon, warnings, plan.experiment_version_id if plan else None)


# ---------------------------------------------------------------------------------------------------- groups and segments
def group_values(pop: Population, by: str, xv: str | None) -> dict[str, set[str]]:
    """Account ids per value of ``by``: plan, segment, timezone, or (variant) the variant of the version's assignment."""
    if by not in GROUPS or by == "none":
        raise DomainError(INVALID_GROUP, f"group_by must be one of {', '.join(GROUPS)}", "group_by")
    out: dict[str, set[str]] = defaultdict(set)
    if by == "variant":
        if xv is None:
            raise DomainError(INVALID_GROUP, "group_by=variant needs an experiment_version_id", "group_by")
        for a in accepted_assignments(pop, xv, None).values():
            out[a.variant].add(a.unit_id)
    else:
        for a in pop.accounts:
            out[getattr(a, by)].add(a.account_id)
    return {k: out[k] for k in sorted(out)}


def segment_analysis(pop: Population, cutoff: datetime, plan: Plan, by: str, canon: Canon | None = None) -> dict[str, Any]:
    """Exploratory segment results (D-03, P06-UI-08): every segment carries the label, the number of segments tested and the
    Bonferroni-adjusted threshold alpha / k. No decision may cite a segment."""
    if by not in SEGMENT_FIELDS:
        raise DomainError(INVALID_GROUP, f"a segment analysis is by {', '.join(SEGMENT_FIELDS)}", "group_by")
    canon = canon or canonicalise(pop, cutoff)
    base = Ctx(pop, cutoff, canon, None)
    alpha = 1 - F(plan.confidence)
    groups = {k: v for k, v in group_values(pop, by, None).items()}
    tested = [k for k in groups if _has_both_arms(pop, plan, groups[k])]
    k_n = max(len(tested), 1)
    thr = alpha / k_n
    zadj = z_crit(q(1 - thr, 6)) if len(tested) > 0 else None
    win = plan.activation_window_days
    segs = []
    for val in groups:
        ctx = Ctx(pop, cutoff, canon, groups[val])
        acc = accepted_assignments(pop, plan.experiment_version_id, groups[val])
        cells: dict[str, tuple[int, int]] = {}
        for v in plan.variants:
            m = [a for a in acc.values() if a.variant == v and a.unit_id in ctx.signup_at and ctx.mature(a.unit_id, win)]
            cells[v] = (sum(1 for a in m if ctx.activated_within(a.unit_id, win)), len(m))
        (xc, nc), (xt, nt) = cells["control"], cells["treatment"]
        item: dict[str, Any] = {
            "value": val, "label": "exploratory", "decision_basis": False,
            "variants": {v: {"mature_units": cells[v][1], "activated": cells[v][0], "conversion": q6(ratio(*cells[v]))}
                         for v in plan.variants}, "absolute_lift_pp": None, "p_value": None, "adjusted_interval": None,
            "below_bonferroni_threshold": False}
        if nc and nt:
            d = F(xt, nt) - F(xc, nc)
            item["absolute_lift_pp"] = q(d * 100, 2)
            pooled = F(xt + xc, nt + nc)
            se2 = pooled * (1 - pooled) * (F(1, nt) + F(1, nc))
            if se2 > 0:
                zstat = d / sqrt_frac(se2)
                pv = normal_two_sided_p(zstat)
                item["p_value"] = q(pv, 6)
                item["below_bonferroni_threshold"] = pv < D(thr.numerator) / D(thr.denominator)
            _, lo, hi = newcombe(xt, nt, xc, nc, F(zadj))  # type: ignore[arg-type]
            item["adjusted_interval"] = {"confidence": q(1 - thr, 6), "z": q(zadj, 6), "low": q(lo, 6), "high": q(hi, 6),
                                         "includes_zero": lo <= 0 <= hi}
        segs.append(item)
    return {"label": "exploratory", "decision_basis": False, "by": by, "segments_tested": len(tested),
            "alpha": q(alpha, 6), "bonferroni_threshold": q(thr, 6), "correction": "bonferroni",
            "note": "segment results are exploratory: a segment that looks different is a hypothesis for the next experiment, "
                    "never a decision basis",
            "segments": segs}


def _has_both_arms(pop: Population, plan: Plan, accounts: set[str]) -> bool:
    acc = accepted_assignments(pop, plan.experiment_version_id, accounts)
    return {"control", "treatment"} <= {a.variant for a in acc.values()}


# ---------------------------------------------------------------------------------------------------- exclusions
#: Pre-assignment attributes an analysis may exclude on (TEST-02): they exist before, and independently of, the treatment.
EXCLUSION_FIELDS = ("plan", "segment", "timezone", "internal")


def allowed_after_exclusions(pop: Population, exclusions: list[dict[str, Any]]) -> set[str]:
    """Accounts that remain after pre-assignment exclusions. Anything that depends on the treatment is refused upstream."""
    out = set()
    for a in pop.accounts:
        drop = False
        for e in exclusions:
            v = str(a.internal).lower() if e["field"] == "internal" else getattr(a, e["field"])
            drop = drop or v in e["values"]
        if not drop:
            out.add(a.account_id)
    return out


# ---------------------------------------------------------------------------------------------------- guardrail review
def guardrail_review(block: dict[str, Any], plan: Plan) -> dict[str, Any]:
    """C09: the guardrail of a run over its prespecified window (the plan's ``guardrail``): error rate per variant and the
    treatment minus control difference with a Newcombe interval at the plan's z. HARMFUL when the whole interval lies above 0
    (more errors under treatment), INSUFFICIENT when a variant has no eligible unit, else OK."""
    g = block["guardrail"]
    c, t = g["by_variant"]["control"], g["by_variant"]["treatment"]
    out: dict[str, Any] = {"metric": g["metric"], "window_days": g["window_days"], "prespecified": True,
                           "source": "frozen analysis plan", "by_variant": g["by_variant"], "difference_pp": None, "interval": None}
    if c["eligible_units"] == 0 or t["eligible_units"] == 0:
        out["verdict"] = "INSUFFICIENT"
        return out
    d, lo, hi = newcombe(t["units_with_error"], t["eligible_units"], c["units_with_error"], c["eligible_units"], F(plan.z))
    out["difference_pp"] = q(d * 100, 2)
    out["interval"] = {"method": "newcombe_hybrid_score", "confidence": plan.confidence, "z": plan.z, "low": q(lo, 6),
                       "high": q(hi, 6), "includes_zero": lo <= 0 <= hi}
    out["verdict"] = "HARMFUL" if lo > 0 else "OK"
    return out
