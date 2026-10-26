"""Domain rules (D-01..D-05) on small hand-built worlds: every rule has a case that would fail without it."""
from datetime import timedelta
from fractions import Fraction as F

import pytest

from productsignal import run_pipeline
from productsignal.errors import DomainError
from productsignal.metrics import guardrail_review
from productsignal.models import parse_plan, plan_hash
from productsignal.stats import (chi2_sf_df1, isqrt_newton, newcombe, normal_two_sided_p, q, sqrt_frac, t_crit, wilson, z_crit)

from support_db import PLAN_BODY, World, iso, small_experiment, ts


def run(w, cutoff=None, **kw):
    return run_pipeline(w.data(), cutoff=cutoff, **kw)


# ---------------------------------------------------------------------------------------------------- numerics
def test_integer_newton_square_roots():
    assert isqrt_newton(10 ** 12) == 10 ** 6 and isqrt_newton(15) == 3 and isqrt_newton(0) == 0 and isqrt_newton(1) == 1
    assert abs(sqrt_frac(F(2)) - F(14142135623730950488, 10 ** 19)) < F(1, 10 ** 8)
    assert sqrt_frac(F(1, 4)) == F(1, 2)


@pytest.mark.parametrize("stat,want", [(F(3841459, 10 ** 6), "0.050000"), (F(4), "0.045500"), (F(10827566, 10 ** 6), "0.001000"),
                                       (F(0), "1.000000"), (F(1000), "0.000000")])
def test_chi_square_p_value_by_erfc_series(stat, want):
    assert q(chi2_sf_df1(stat), 6) == want


@pytest.mark.parametrize("df,want", [(1, "12.706205"), (2, "4.302653"), (7, "2.364624"), (9, "2.262157"), (11, "2.200985"), (99, "1.984217")])
def test_t_quantile_by_bisection_on_the_exact_cdf(df, want):
    assert q(t_crit(df), 6) == want


def test_normal_quantile_and_two_sided_p():
    assert q(z_crit("0.95"), 6) == "1.959964" and q(z_crit("0.99"), 6) == "2.575829"
    assert q(normal_two_sided_p(F(196, 100)), 6) == "0.049996"


def test_newcombe_1998_worked_example_and_wilson_extremes():
    _, lo, hi = newcombe(56, 70, 48, 80, F("1.96"))
    assert (q(lo, 4), q(hi, 4)) == ("0.0524", "0.3339")                  # Newcombe (1998), table II method 10
    p, lo, hi = wilson(0, 12, F("1.959964"))
    assert (q(lo, 6), q(hi, 6)) == ("0.000000", "0.242494")              # a zero count still has an interval


# ---------------------------------------------------------------------------------------------------- D-01 events
def test_received_by_cutoff_and_a_late_event_changes_only_a_later_run():
    """P06-TEST-06: an activation that happened in time but was received after the cutoff is in no earlier run."""
    w = small_experiment((10, 2), (10, 5))
    w.activate("acc-c-009", "2026-10-02T00:00:00Z", recv="2026-10-20T00:00:00Z")          # late: received 18 days later
    early = run(w, "2026-10-10T00:00:00Z").metrics["experiment"]["primary"]["variants"]["control"]
    late = run(w, "2026-10-26T00:00:00Z").metrics["experiment"]["primary"]["variants"]["control"]
    assert early["activated"] == 2 and late["activated"] == 3
    again = run(w, "2026-10-10T00:00:00Z")                                              # the same cutoff later: same figures
    assert again.metrics["experiment"]["primary"]["variants"]["control"]["activated"] == 2
    assert again.tracking_quality["received_after_cutoff"] == 1 and run(w).tracking_quality["received_after_cutoff"] == 0


def test_duplicates_unknown_identity_bots_internal_and_delayed_are_each_counted_apart():
    w = World()
    w.account("acc-1")
    w.account("acc-bot", bot=True)
    w.account("acc-int", internal=True)
    w.signup("acc-1", "2026-10-06T10:00:00Z")
    e1 = w.event("feature_used", "2026-10-06T11:00:00Z", user="u-acc-1", props={"feature": "export"}, eid="ev-a")
    w.event("feature_used", "2026-10-06T11:00:00Z", user="u-acc-1", props={"feature": "export"}, eid="ev-a-resend",
            recv="2026-10-06T11:00:09Z")                                                  # re-sent under a new id: a duplicate
    w.event("feature_used", "2026-10-06T11:00:00Z", user="u-acc-1", props={"feature": "import"}, eid="ev-a-other")   # other properties: kept
    w.event("visit", "2026-10-06T12:00:00Z", user="u-ghost")                              # no such user and no link
    w.event("visit", "2026-10-06T12:00:00Z")                                              # no identity at all
    w.signup("acc-bot", "2026-10-06T12:00:00Z")
    w.signup("acc-int", "2026-10-06T12:00:00Z")
    w.event("visit", "2026-10-06T08:00:00Z", user="u-acc-1", recv="2026-10-07T08:00:00Z")   # exactly 24 h: not delayed
    w.event("visit", "2026-10-06T08:00:01Z", user="u-acc-1", recv="2026-10-07T08:00:02Z")   # 24 h + 1 s: delayed
    tq = run(w).tracking_quality
    assert tq == {"rows_total": 10, "received_after_cutoff": 0, "duplicates_dropped": 1, "canonical": 9, "delayed_over_24h": 1,
                  "unknown_identity": 2, "bot_events_excluded": 1, "internal_events_excluded": 1, "analysed": 5}
    assert e1 == "ev-a"


def test_a_repeated_event_id_is_idempotent_and_a_changed_one_is_rejected():
    w = World()
    w.account("acc-1")
    w.event("visit", "2026-10-06T10:00:00Z", user="u-acc-1", eid="ev-1")
    d = w.data()
    d["events"].append(dict(d["events"][0]))                                              # the same row twice
    changed = dict(d["events"][0], event_name="signup")
    d["events"].append(changed)
    res = run_pipeline(d)
    assert res.ingest.merged["events"] == 1 and [r["reason_code"] for r in res.rejected] == ["DUPLICATE_ID"]


def test_identity_is_time_aware_and_never_applied_backward():
    """P06-TEST-07: an anonymous signup before the link stays anonymous; the same signup after the link is the account's."""
    w = World()
    w.account("acc-1")
    w.event("signup", "2026-10-06T09:00:00Z", anon="a-1")                                  # before the link: anonymous
    w.link("a-1", "u-acc-1", "2026-10-06T10:00:00Z")
    before = run(w)
    assert before.identity == {"anonymous_events": 1, "attributed_by_link": 0, "remain_anonymous": 1}
    assert before.metrics["activation"]["signups"] == 0                                   # no account signup: nothing attributed backward
    w.event("signup", "2026-10-06T10:00:00Z", anon="a-1")                                  # at linked_at: attributed (>=)
    after = run(w)
    assert after.identity == {"anonymous_events": 2, "attributed_by_link": 1, "remain_anonymous": 1}
    assert after.metrics["activation"]["signups"] == 1


def test_the_earliest_link_fixes_the_user_and_a_conflicting_link_is_rejected():
    w = World()
    w.account("acc-1")
    w.account("acc-2")
    w.link("a-1", "u-acc-1", "2026-10-06T10:00:00Z")
    w.link("a-1", "u-acc-2", "2026-10-06T11:00:00Z")
    w.link("a-1", "u-acc-1", "2026-10-07T11:00:00Z")                                       # the same pair again: merged
    res = run_pipeline(w.data())
    assert [(r["id"], r["reason_code"]) for r in res.rejected] == [("il-002", "IDENTITY_CONFLICT")]
    assert res.ingest.merged["identity_links"] == 1 and res.counts["identity_links"]["accepted"] == 1


def test_accounts_roll_up_users_before_any_ratio():
    """P06-DOMAIN-01: two users of one account are one account; the earliest non-bot signup is the account's."""
    w = World()
    w.account("acc-1")
    w.user("u-second", "acc-1")
    w.user("u-bot", "acc-1", bot=True)
    w.event("signup", "2026-10-01T08:00:00Z", user="u-bot")                                 # a bot's earlier signup is ignored
    w.event("signup", "2026-10-02T09:00:00Z", user="u-second")
    w.signup("acc-1", "2026-10-03T09:00:00Z")
    for h in (1, 2, 3):                                                                    # three activations, two users: one account
        w.event("activated", f"2026-10-02T1{h}:00:00Z", user="u-second")
    w.event("activated", "2026-10-03T12:00:00Z", user="u-acc-1")
    a = run(w).metrics["activation"]
    assert (a["signups"], a["mature_accounts"], a["activated"], a["rate"]) == (1, 1, 1, "1.000000")


# ---------------------------------------------------------------------------------------------------- D-02 activation
def test_activation_window_is_half_open_and_maturity_is_inclusive():
    w = World(cutoff="2026-10-26T00:00:00Z")
    for aid, signup, act in (("in", "2026-10-10T00:00:00Z", "2026-10-16T23:59:59Z"),          # +6 d 23:59:59: counts
                             ("edge", "2026-10-10T00:00:00Z", "2026-10-17T00:00:00Z"),        # exactly +7 d: does not
                             ("boundary", "2026-10-19T00:00:00Z", "2026-10-19T01:00:00Z"),    # signup + 7 d == cutoff: mature
                             ("young", "2026-10-19T00:00:01Z", "2026-10-19T01:00:00Z")):      # one second short: immature
        w.account(aid)
        w.signup(aid, signup)
        w.activate(aid, act)
    a = run(w).metrics["activation"]
    assert (a["signups"], a["immature_excluded"], a["mature_accounts"], a["activated"]) == (4, 1, 3, 2)
    assert a["rate"] == "0.666667"


def test_immature_cohort_is_excluded_from_the_experiment_and_counted():
    """P06-TEST-04."""
    w = small_experiment((10, 2), (10, 5))
    w.arm("control", 5, 5, prefix="late", start="2026-10-25T00:00:00Z")                   # signed up a day before the cutoff
    e = run(w).metrics["experiment"]
    assert e["assigned_units"] == 25 and e["mature_units"] == 20 and e["immature_or_unobserved_excluded"] == 5
    assert e["primary"]["variants"]["control"]["mature_units"] == 10 and e["srm"]["observed"]["control"] == 15


# ---------------------------------------------------------------------------------------------------- D-02 retention
def _retention_world(tz="UTC", cutoff="2026-11-10T00:00:00Z", signup="2026-10-26T12:00:00Z", lo="2026-10-26", hi="2026-10-27"):
    w = World(cutoff=cutoff)
    w.d["metric_windows"]["retention"] = {"signup_from": lo, "signup_to": hi}
    w.account("acc-1", tz=tz)
    w.signup("acc-1", signup)
    return w


def test_retention_uses_the_account_calendar_across_a_dst_change():
    """America/New_York leaves DST on 2026-11-01 (02:00 -> 01:00). Day 0 = 2026-10-26 local, day 7 = 2026-11-02 local."""
    w = _retention_world("America/New_York")
    w.session("acc-1", "2026-11-02T04:30:00Z")        # 23:30 EST on 11-01: local day 6 (a fixed -04:00 offset would say day 7)
    assert run(w).metrics["retention"]["day7"]["retained"] == 0
    w.session("acc-1", "2026-11-03T04:59:00Z")        # 23:59 EST on 11-02: local day 7 (UTC date 11-03 would say day 8)
    r = run(w).metrics["retention"]
    assert (r["day7"]["retained"], r["day7"]["mature_accounts"], r["cohort_accounts"]) == (1, 1, 1)


def test_exact_day_7_and_on_or_after_day_7_are_separate_figures():
    """P06-TEST-12: a return on day 9 is not a day-7 return; it is on-or-after-7."""
    w = _retention_world()
    w.session("acc-1", "2026-11-04T10:00:00Z")        # day 9
    r = run(w).metrics["retention"]
    assert (r["day7"]["retained"], r["on_or_after_day7"]["retained"], r["week4"]["retained"]) == (0, 1, 0)
    assert (r["day7"]["rate"], r["on_or_after_day7"]["rate"]) == ("0.000000", "1.000000")


@pytest.mark.parametrize("session,week4", [("2026-11-22T10:00:00Z", 0),       # day 27
                                           ("2026-11-23T10:00:00Z", 1),       # day 28
                                           ("2026-11-29T23:59:59Z", 1),       # day 34
                                           ("2026-11-30T00:00:00Z", 0)])      # day 35
def test_week_four_is_days_28_to_34(session, week4):
    w = _retention_world(cutoff="2026-12-31T00:00:00Z")
    w.session("acc-1", session)
    assert run(w).metrics["retention"]["week4"]["retained"] == week4


def test_retention_maturity_depends_on_the_local_calendar_and_is_counted():
    w = _retention_world(cutoff="2026-11-02T23:00:00Z")                                    # day 7 has not completed
    r = run(w).metrics["retention"]
    assert (r["day7"]["mature_accounts"], r["day7"]["immature_excluded"], r["day7"]["rate"]) == (0, 1, None)
    assert run(_retention_world(cutoff="2026-11-03T00:00:00Z")).metrics["retention"]["day7"]["mature_accounts"] == 1   # day 8 has begun
    assert run(_retention_world(cutoff="2026-11-29T23:59:59Z")).metrics["retention"]["week4"]["mature_accounts"] == 0   # day 35 not begun
    assert run(_retention_world(cutoff="2026-11-29T23:59:59Z")).metrics["retention"]["week4"]["immature_excluded"] == 1
    assert run(_retention_world(cutoff="2026-11-30T00:00:00Z")).metrics["retention"]["week4"]["mature_accounts"] == 1


def test_sessions_of_bots_and_internal_accounts_are_ignored_and_the_internal_signup_is_counted():
    w = _retention_world()
    w.account("acc-int", internal=True)
    w.signup("acc-int", "2026-10-26T12:00:00Z")
    w.session("acc-int", "2026-11-02T10:00:00Z")
    w.account("acc-bot", bot=True)
    w.signup("acc-bot", "2026-10-26T12:00:00Z")
    w.session("acc-bot", "2026-11-02T10:00:00Z")
    r = run(w).metrics["retention"]
    assert (r["cohort_accounts"], r["excluded_internal_accounts"], r["day7"]["retained"]) == (1, 1, 0)


# ---------------------------------------------------------------------------------------------------- funnel, signup
def _visitor(w, anon, uid, visit, signup=None, step=None, act=None):
    w.account(uid)
    w.link(anon, f"u-{uid}", signup or visit)
    w.event("visit", visit, anon=anon)
    if signup:
        w.event("signup", signup, anon=anon)
    if step:
        w.event("onboarding_step_1", step, user=f"u-{uid}")
    if act:
        w.event("activated", act, user=f"u-{uid}")


def test_funnel_strict_order_inclusive_gap_no_reanchoring_and_the_window_on_the_first_step():
    w = World()
    _visitor(w, "a-ok", "ok", "2026-10-06T09:00:00Z", "2026-10-06T09:10:00Z", "2026-10-06T09:30:00Z", "2026-10-08T09:30:00Z")   # last gap 48 h exactly
    _visitor(w, "a-late", "late", "2026-10-06T09:00:00Z", "2026-10-06T09:10:00Z", "2026-10-06T09:30:00Z", "2026-10-08T09:30:01Z")  # 48 h + 1 s
    _visitor(w, "a-skip", "skip", "2026-10-06T09:00:00Z", "2026-10-06T09:10:00Z", None, "2026-10-06T10:00:00Z")           # skipped step 1
    _visitor(w, "a-back", "back", "2026-10-06T09:00:00Z", "2026-10-06T08:00:00Z")                                          # signup BEFORE the visit
    _visitor(w, "a-before", "before", "2026-10-04T23:59:59Z", "2026-10-05T00:10:00Z")                                      # first step outside the window
    _visitor(w, "a-re", "re", "2026-10-06T09:00:00Z", "2026-10-09T09:00:00Z")                                              # 72 h after the anchor ...
    w.event("visit", "2026-10-09T08:00:00Z", anon="a-re")                                                                  # ... a later visit does not re-anchor
    f = run(w).metrics["funnel"]
    assert [(s["step"], s["units"]) for s in f["steps"]] == [("visit", 5), ("signup", 3), ("onboarding_step_1", 2), ("activated", 1)]
    assert f["overall_conversion"] == "0.200000"
    assert f["steps"][1]["conversion_from_previous"] == "0.600000" and f["steps"][2]["conversion_from_previous"] == "0.666667"
    assert f["steps"][3]["conversion_from_previous"] == "0.500000" and f["steps"][3]["conversion_from_first"] == "0.200000"


def test_signup_conversion_has_no_gap_and_may_exceed_the_funnels_first_step():
    """D-P6-10: a signup 72 h after the visit counts for MET-01 but not for the 48 h funnel."""
    w = World()
    _visitor(w, "a-slow", "slow", "2026-10-06T09:00:00Z", "2026-10-09T09:00:00Z")
    w.event("visit", "2026-10-06T10:00:00Z", anon="a-none")
    m = run(w).metrics
    assert (m["signup_conversion"]["visitors"], m["signup_conversion"]["signed_up"], m["signup_conversion"]["rate"]) == (2, 1, "0.500000")
    assert [s["units"] for s in m["funnel"]["steps"]] == [2, 0, 0, 0]


# ---------------------------------------------------------------------------------------------------- feature adoption
def test_feature_adoption_eligibility_is_decided_without_any_outcome_and_a_use_counts_once():
    w = World()
    for aid, plan in (("team-1", "team"), ("biz-1", "business"), ("free-1", "free"), ("team-idle", "team")):
        w.account(aid, plan=plan)
    for aid in ("team-1", "biz-1", "free-1"):
        w.session(aid, "2026-09-22T10:00:00Z")
    w.event("feature_used", "2026-09-22T11:00:00Z", user="u-team-1", props={"feature": "export"})
    w.event("feature_used", "2026-09-22T11:00:00Z", user="u-team-1", props={"feature": "export"}, eid="ev-resend")        # duplicate
    w.event("feature_used", "2026-09-23T11:00:00Z", user="u-team-1", props={"feature": "export"})                          # a second use
    w.event("feature_used", "2026-09-22T11:00:00Z", user="u-biz-1", props={"feature": "import"})                           # other feature
    w.event("feature_used", "2026-09-22T11:00:00Z", user="u-free-1", props={"feature": "export"})                          # not eligible
    w.event("feature_used", "2026-09-28T00:00:00Z", user="u-biz-1", props={"feature": "export"})                           # window is half-open
    f = run(w).metrics["feature_adoption"]
    assert (f["eligible_accounts"], f["adopting_accounts"], f["use_events"], f["rate"]) == (2, 1, 2, "0.500000")


# ---------------------------------------------------------------------------------------------------- D-03 experiment
def test_primary_result_is_intention_to_treat_and_exposure_rate_is_reported_beside_it():
    w = small_experiment((20, 4), (20, 10))
    w2 = World()
    w2.arm("control", 20, 4, exposed=10)
    w2.arm("treatment", 20, 10, start="2026-10-01T11:00:00Z", exposed=5)
    e = run(w2).metrics["experiment"]
    assert e["primary"]["variants"]["treatment"]["mature_units"] == 20                    # unexposed units stay in their arm
    assert e["exposure"]["by_variant"] == {"control": {"exposed": 10, "units": 20, "rate": "0.500000"},
                                           "treatment": {"exposed": 5, "units": 20, "rate": "0.250000"}}
    assert e["exploratory_exposed_only"]["decision_basis"] is False
    assert run(w).metrics["experiment"]["exposure"]["overall"]["rate"] == "1.000000"


def test_exposure_before_assignment_is_rejected_and_the_unit_is_not_exposed():
    """P06-TEST-11."""
    w = World()
    ids = w.arm("control", 3, 0, exposed=0)
    asid = w.d["assignments"][0]["assignment_id"]
    w.expose(asid, "2026-10-01T08:59:59Z")                                                 # one second before the assignment
    res = run_pipeline(w.data())
    assert [(r["entity"], r["reason_code"]) for r in res.rejected] == [("exposures", "EXPOSURE_BEFORE_ASSIGNMENT")]
    assert res.metrics["experiment"]["exposure"]["overall"]["exposed"] == 0 and ids


@pytest.mark.parametrize("c,t,verdict", [((100, 0), (100, 0), "OK"), ((130, 0), (70, 0), "MISMATCH"), ((125, 0), (75, 0), "MISMATCH"),
                                         ((60, 0), (40, 0), "OK"), ((4, 0), (0, 0), "INSUFFICIENT"), ((8, 0), (1, 0), "INSUFFICIENT"),
                                         ((0, 0), (0, 0), "INSUFFICIENT")])
def test_srm_verdict_order_insufficient_then_mismatch_then_ok(c, t, verdict):
    w = World()
    w.arm("control", *c)
    w.arm("treatment", *t, start="2026-10-01T11:00:00Z")
    s = run(w).metrics["experiment"]["srm"]
    assert s["verdict"] == verdict
    if c[0] + t[0] == 0:
        assert s["statistic"] is None and s["p_value"] is None and s["expected"] is None


def test_srm_statistic_and_p_value_for_a_130_70_split():
    w = World()
    w.arm("control", 130, 0)
    w.arm("treatment", 70, 0, start="2026-10-01T14:00:00Z")
    s = run(w).metrics["experiment"]["srm"]
    assert (s["statistic"], s["expected"], s["df"]) == ("18.000000", {"control": "100.00", "treatment": "100.00"}, 1)
    assert s["p_value"] == "0.000022" and s["verdict"] == "MISMATCH"                      # erfc(sqrt(9)) = 2.2090e-5


def test_lift_signs_nulls_and_conclusive_needs_an_interval_that_excludes_zero():
    better = run(small_experiment((100, 20), (100, 40))).metrics["experiment"]["primary"]
    assert (better["absolute_lift_pp"], better["relative_lift"], better["interval"]["includes_zero"], better["conclusive"]) == ("20.00", "1.000000", False, True)
    worse = run(small_experiment((100, 40), (100, 20))).metrics["experiment"]["primary"]
    assert (worse["absolute_lift_pp"], worse["relative_lift"]) == ("-20.00", "-0.500000") and worse["conclusive"] is True
    flat_ = run(small_experiment((100, 20), (100, 30))).metrics["experiment"]["primary"]
    assert flat_["interval"]["includes_zero"] is True and flat_["conclusive"] is False   # the golden shape
    zero = run(small_experiment((20, 0), (20, 8))).metrics["experiment"]["primary"]
    assert zero["relative_lift"] is None and zero["absolute_lift_pp"] == "40.00"          # P06-TEST-10: null, never 0 or infinity
    none = run(small_experiment((20, 0), (20, 0))).metrics["experiment"]["primary"]
    assert (none["relative_lift"], none["absolute_lift_pp"], none["conclusive"]) == (None, "0.00", False)


def test_a_run_before_planned_end_is_interim_and_never_conclusive():
    """P06-TEST-03 (domain side): the same data, a cutoff before planned_end: interim, so not conclusive."""
    w = small_experiment((100, 20), (100, 60), cutoff="2026-10-26T00:00:00Z")
    final = run(w).metrics["experiment"]
    assert final["run"]["interim"] is False and final["primary"]["conclusive"] is True
    w2 = small_experiment((100, 20), (100, 60), planned_end="2026-10-27T00:00:00Z")
    for r in (w2.d["experiment_versions"][0],):
        r["planned_end"] = "2026-10-27T00:00:00Z"
    peek = run(w2).metrics["experiment"]
    assert peek["primary"]["interval"]["includes_zero"] is False and peek["run"]["interim"] is True and peek["primary"]["conclusive"] is False


def test_prior_runs_are_counted_and_the_plan_hash_must_match():
    w = small_experiment((10, 2), (10, 5))
    w.run("2026-10-10T00:00:00Z", "2026-10-10T01:00:00Z")
    w.run("2026-10-20T00:00:00Z", "2026-10-20T01:00:00Z")
    third = w.run("2026-10-26T00:00:00Z", "2026-10-26T01:00:00Z")
    r = run(w).metrics["experiment"]["run"]
    assert (r["analysis_id"], r["prior_runs"], r["plan_frozen"], r["config_hash_matches_plan"]) == (third, 2, True, True)
    assert run(w, run_id="an-001").metrics["experiment"]["run"]["prior_runs"] == 0
    bad = w.data()
    bad["analysis_plan"]["z"] = "1.644854"                                                  # the plan changed after the hash was taken
    e = run_pipeline(bad).metrics["experiment"]
    assert e["run"]["config_hash_matches_plan"] is False and e["primary"]["conclusive"] is False
    assert any(x["code"] == "PLAN_HASH_MISMATCH" for x in run_pipeline(bad).warnings)


def test_a_plan_frozen_after_the_first_run_is_not_frozen():
    w = small_experiment((10, 2), (10, 5))
    w.run("2026-10-10T00:00:00Z", "2026-09-01T00:00:00Z")                                   # a run before frozen_at (2026-09-30)
    assert run(w).metrics["experiment"]["run"]["plan_frozen"] is False


def test_guardrail_window_is_half_open_from_assignment_and_counts_an_account_once():
    w = World()
    ids = w.arm("control", 5, 0)
    w.event("product_error", "2026-10-02T09:00:00Z", user=f"u-{ids[0]}")
    w.event("product_error", "2026-10-03T09:00:00Z", user=f"u-{ids[0]}")                    # the same account twice: one
    w.event("product_error", "2026-10-08T09:02:00Z", user=f"u-{ids[1]}")                    # assigned 09:02 + 7 d exactly: outside
    w.event("product_error", "2026-10-08T09:02:59Z", user=f"u-{ids[2]}")                    # assigned 09:03: one second inside
    w.event("product_error", "2026-10-01T09:03:59Z", user=f"u-{ids[3]}")                    # before its assignment (09:04): not counted
    g = run(w).metrics["experiment"]["guardrail"]["by_variant"]["control"]
    assert (g["eligible_units"], g["units_with_error"], g["error_rate"]) == (5, 2, "0.400000")


def test_revenue_per_assigned_account_with_a_t_interval_over_accounts():
    w = World()
    c = w.arm("control", 2, 0)
    t = w.arm("treatment", 2, 0, start="2026-10-01T11:00:00Z")
    w.sub(c[1], "2026-10-03T00:00:00Z", "10.00")
    w.sub(c[0], "2026-10-03T00:00:00Z", "99.00", status="trial")                           # not active or ended
    w.sub(c[0], "2026-10-15T00:00:00Z", "99.00")                                           # window is half-open
    w.sub(t[0], "2026-10-04T00:00:00Z", "30.00", status="ended")
    w.sub(t[1], "2026-10-04T00:00:00Z", "30.00")
    by = run(w).metrics["experiment"]["revenue_per_assigned_account"]["by_variant"]
    # two accounts [0, 10]: mean 5, s = sqrt(50), se = 5, t(0.975, 1) = 12.706205, half = 63.531
    assert by["control"] == {"units": 2, "total": "10.00", "mean": "5.00",
                             "interval": {"df": 1, "t": "12.706205", "low": "-58.53", "high": "68.53"}}
    assert by["treatment"]["interval"] == {"df": 1, "t": "12.706205", "low": "30.00", "high": "30.00"}    # zero variance


# ---------------------------------------------------------------------------------------------------- segments (exploratory)
def test_segment_analysis_is_exploratory_with_the_number_tested_and_a_bonferroni_threshold():
    """P06-TEST-09 (domain side)."""
    from productsignal.metrics import segment_analysis
    w = World()
    for seg, (c, t) in {"smb": ((30, 3), (30, 15)), "mid": ((30, 6), (30, 7)), "enterprise": ((30, 9), (30, 9))}.items():
        for arm, (n, k) in (("control", c), ("treatment", t)):
            for i in range(n):
                aid = w.account(f"acc-{seg}-{arm[0]}{i:02d}", segment=seg)
                t0 = ts("2026-10-01T09:00:00Z") + timedelta(minutes=i)
                w.signup(aid, iso(t0))
                w.assign(aid, arm, iso(t0 + timedelta(minutes=1)))
                if i < k:
                    w.activate(aid, iso(t0 + timedelta(hours=2)))
    res = run(w)
    s = segment_analysis(res.population, ts("2026-10-26T00:00:00Z"), res.population.plans["xv-001"], "segment")
    assert (s["label"], s["decision_basis"], s["segments_tested"], s["correction"]) == ("exploratory", False, 3, "bonferroni")
    assert (s["alpha"], s["bonferroni_threshold"]) == ("0.050000", "0.016667")
    smb = next(x for x in s["segments"] if x["value"] == "smb")
    assert smb["label"] == "exploratory" and smb["decision_basis"] is False and smb["absolute_lift_pp"] == "40.00"
    assert smb["below_bonferroni_threshold"] is True and smb["adjusted_interval"]["includes_zero"] is False
    mid = next(x for x in s["segments"] if x["value"] == "mid")
    assert mid["below_bonferroni_threshold"] is False and mid["adjusted_interval"]["includes_zero"] is True
    assert q(F(1) - F(1, 60), 6) == s["segments"][0]["adjusted_interval"]["confidence"]    # 1 - alpha / k
    with pytest.raises(DomainError):
        segment_analysis(res.population, ts("2026-10-26T00:00:00Z"), res.population.plans["xv-001"], "variant")


def test_guardrail_review_verdicts():
    plan = parse_plan({**PLAN_BODY, "config_hash": plan_hash(PLAN_BODY)})
    def block(c, t):
        return {"guardrail": {"metric": "product_error_rate", "window_days": 7, "by_variant": {
            "control": {"eligible_units": c[0], "units_with_error": c[1], "error_rate": None},
            "treatment": {"eligible_units": t[0], "units_with_error": t[1], "error_rate": None}}}}
    assert guardrail_review(block((100, 3), (100, 4)), plan)["verdict"] == "OK"
    assert guardrail_review(block((100, 1), (100, 20)), plan)["verdict"] == "HARMFUL"
    assert guardrail_review(block((100, 20), (100, 1)), plan)["verdict"] == "OK"            # fewer errors is not harm
    assert guardrail_review(block((0, 0), (100, 4)), plan)["verdict"] == "INSUFFICIENT"
    r = guardrail_review(block((100, 3), (100, 4)), plan)
    assert r["prespecified"] is True and r["window_days"] == 7 and r["difference_pp"] == "1.00"


# ---------------------------------------------------------------------------------------------------- ingest rules
def test_ingest_rejections_for_assignments_and_references():
    w = World()
    w.account("acc-1")
    w.account("acc-int", internal=True)
    d = w.data()
    base = {"experiment_version_id": "xv-001", "assigned_at": "2026-10-01T09:00:00Z"}
    d["assignments"] = [
        {"assignment_id": "a1", "unit_id": "acc-1", "variant": "control", **base},
        {"assignment_id": "a2", "unit_id": "acc-nope", "variant": "control", **base},           # unknown unit
        {"assignment_id": "a3", "unit_id": "acc-int", "variant": "control", **base},            # internal: decided before assignment
        {"assignment_id": "a4", "unit_id": "acc-1", "variant": "holdout", **base},              # a variant the plan does not name
        {"assignment_id": "a5", "unit_id": "acc-1", "variant": "control", "experiment_version_id": "xv-zzz", "assigned_at": base["assigned_at"]},
        {"assignment_id": "a6", "unit_id": "acc-1", "variant": "control", **{**base, "assigned_at": "2026-10-02T09:00:00Z"}},   # same variant: merged
        {"assignment_id": "a7", "unit_id": "acc-1", "variant": "treatment", **{**base, "assigned_at": "2026-10-02T09:00:00Z"}},  # conflict
    ]
    d["exposures"] = [{"exposure_id": "x1", "assignment_id": "a7", "exposed_at": "2026-10-03T00:00:00Z", "surface": "s", "event_id": None},
                      {"exposure_id": "x2", "assignment_id": "a-zzz", "exposed_at": "2026-10-03T00:00:00Z", "surface": "s", "event_id": None},
                      {"exposure_id": "x3", "assignment_id": "a6", "exposed_at": "2026-10-03T00:00:00Z", "surface": "s", "event_id": None}]
    res = run_pipeline(d)
    assert {(r["id"], r["reason_code"]) for r in res.rejected} == {
        ("a2", "UNKNOWN_UNIT"), ("a3", "INELIGIBLE_UNIT"), ("a4", "UNKNOWN_VARIANT"), ("a5", "UNKNOWN_EXPERIMENT_VERSION"),
        ("a7", "ASSIGNMENT_CONFLICT"), ("x1", "DEPENDENT_REJECTED"), ("x2", "UNKNOWN_ASSIGNMENT")}
    assert res.counts["assignments"] == {"accepted": 1, "rejected": 5, "merged": 1}
    assert [x.assignment_id for x in res.population.exposures] == ["a1"]                    # the merged id resolves to the one that fixed it


def test_ingest_malformed_rows_are_rejected_not_rounded():
    w = World()
    w.account("acc-1")
    d = w.data()
    d["subscriptions"] = [
        {"subscription_id": "s1", "account_id": "acc-1", "starts_at": "2026-10-01T00:00:00Z", "ends_at": None, "status": "active", "amount_usd": "49.00"},
        {"subscription_id": "s2", "account_id": "acc-1", "starts_at": "2026-10-01T00:00:00Z", "ends_at": None, "status": "active", "amount_usd": 49.5},
        {"subscription_id": "s3", "account_id": "acc-1", "starts_at": "2026-10-01T00:00:00Z", "ends_at": None, "status": "active", "amount_usd": "49.001"},
        {"subscription_id": "s4", "account_id": "acc-1", "starts_at": "2026-10-01T00:00:00Z", "ends_at": None, "status": "active", "amount_usd": "-1.00"},
        {"subscription_id": "s5", "account_id": "acc-zzz", "starts_at": "2026-10-01T00:00:00Z", "ends_at": None, "status": "active", "amount_usd": "1.00"},
        {"subscription_id": "s6", "account_id": "acc-1", "starts_at": "2026-10-05T00:00:00Z", "ends_at": "2026-10-01T00:00:00Z", "status": "active", "amount_usd": "1.00"}]
    d["accounts"].append({"account_id": "acc-badtz", "plan": "team", "segment": "smb", "created_at": "2026-09-01T00:00:00Z", "internal": False,
                          "timezone": "Mars/Olympus"})
    d["events"].append({"event_id": "e1", "user_id": "u", "anonymous_id": None, "event_name": "Bad Name", "event_at": "2026-10-01T00:00:00Z",
                        "received_at": "2026-10-01T00:00:00Z"})
    d["events"].append({"event_id": "e2", "user_id": "u", "anonymous_id": None, "event_name": "visit", "event_at": "2026-10-01 00:00:00",
                        "received_at": "2026-10-01T00:00:00Z"})                               # no zone
    res = run_pipeline(d)
    assert {(r["id"], r["reason_code"]) for r in res.rejected} == {
        ("s2", "MALFORMED_RECORD"), ("s3", "MALFORMED_RECORD"), ("s4", "MALFORMED_RECORD"), ("s5", "UNKNOWN_ACCOUNT"),
        ("s6", "INVALID_INTERVAL"), ("acc-badtz", "MALFORMED_RECORD"), ("e1", "MALFORMED_RECORD"), ("e2", "MALFORMED_RECORD")}


def test_plan_validation():
    ok = {**PLAN_BODY, "config_hash": plan_hash(PLAN_BODY)}
    assert parse_plan(ok).hash_valid
    for bad in ({**ok, "allocation": {"control": "0.7", "treatment": "0.7"}}, {**ok, "allocation": {"a": "0.5", "b": "0.5"}},
                {**ok, "unit_type": "user"}, {**ok, "config_hash": "zz"}, {**ok, "z": 1.96}, {**ok, "confidence": "1.5"},
                {**ok, "revenue_window": {"from": "2026-10-15T00:00:00Z", "to": "2026-10-01T00:00:00Z"}}):
        with pytest.raises(DomainError):
            parse_plan(bad)


# ---------------------------------------------------------------------------------------------------- domain == reference
@pytest.mark.parametrize("start", range(0, 120, 20))
def test_domain_equals_the_independent_reference_on_random_worlds(start):
    """Seeded random populations (timezones, bots, internal accounts, links, duplicates, late events, edges of every window):
    the domain and the stdlib reference computation agree on every leaf."""
    import importlib.util
    from pathlib import Path
    from support_db import flat, random_world
    spec = importlib.util.spec_from_file_location("reference_check", Path(__file__).resolve().parent / "reference_check.py")
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    for s in range(start, start + 20):
        d = random_world(s)
        got = run_pipeline(d)
        assert got.rejected == [], (s, got.rejected[:2])
        diffs = {k for k, v in flat(ref.compute(d)).items() if flat(got.golden()).get(k) != v}
        assert not diffs, (s, sorted(diffs)[:5])
