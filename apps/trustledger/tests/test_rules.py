"""Domain rules, one decision at a time (D-01..D-06): each test builds the smallest population that pins the rule."""
from copy import deepcopy
from fractions import Fraction

import pytest

from trustledger import DomainError, run_pipeline
from trustledger.errors import UNKNOWN_WEIGHT_VERSION
from trustledger.measure import pattern_matches
from trustledger.numbers import h4, p6, ratio, rnd

from support_db import World, rows_of

PAT = r"^[^@ \t\r\n\f\v]+@[^@ \t\r\n\f\v]+\.[A-Za-z]{2,}$"     # explicit classes only (D-10 R7-04)


def world_with_customers(values, **kw):
    w = World(**kw)
    w.owner("o1")
    w.dataset("d1", "o1", rows_of("email", values))
    return w


# ------------------------------------------------------------------------------------------------------ number formats
@pytest.mark.parametrize("x,dp,want", [(Fraction(1, 2), 0, "1"), (Fraction(1, 3), 6, "0.333333"), (Fraction(2, 3), 6, "0.666667"), (Fraction(5, 10 ** 7), 6, "0.000001"),
                                       (Fraction(4, 10 ** 7), 6, "0.000000"), (Fraction(231, 6), 4, "38.5000"), (Fraction(-1, 3), 2, "-0.33"), (Fraction(0), 6, "0.000000"),
                                       (Fraction(1), 6, "1.000000"), (Fraction(2, 8), 1, "0.3"), (Fraction(1, 8), 2, "0.13")])
def test_rounding_is_half_up_on_exact_fractions(x, dp, want):
    assert rnd(x, dp) == want


def test_null_is_unknown_never_zero():
    assert ratio(0, 0) is None and p6(None) is None and h4(None) is None and p6(ratio(0, 5)) == "0.000000"


# ------------------------------------------------------------------------------------------------------ completeness
def test_completeness_whitespace_policy_and_the_count_of_whitespace_only_values():
    vals = ["a@b.co", None, "", "   ", "\t \t", " x ", "\r\n"]
    w = world_with_customers(vals)
    w.rule("r-c", "d1", "completeness", {"field": "email"})
    c = run_pipeline(w.data()).metrics["completeness"]["r-c"]
    assert (c["eligible_count"], c["missing_count"], c["whitespace_only_count"], c["populated_count"], c["value"]) == (7, 5, 3, 2, "0.285714")


def test_a_declared_trim_set_changes_what_is_missing():
    w = world_with_customers(["x", "-", "--", " "])
    w.d["whitespace_policy"] = {"name": "dash_policy", "trim_characters": "- "}
    w.rule("r-c", "d1", "completeness", {"field": "email"})
    assert run_pipeline(w.data()).metrics["completeness"]["r-c"]["missing_count"] == 3


def test_a_rule_filter_declares_the_eligible_rows():
    w = World()
    w.owner("o1")
    w.dataset("d1", "o1", [{"row_id": "1", "email": None, "kind": "a"}, {"row_id": "2", "email": "x", "kind": "a"}, {"row_id": "3", "email": None, "kind": "b"}])
    w.rule("r-all", "d1", "completeness", {"field": "email"})
    w.rule("r-a", "d1", "completeness", {"field": "email", "filter": {"field": "kind", "equals": "a"}})
    c = run_pipeline(w.data()).metrics["completeness"]
    assert (c["r-all"]["eligible_count"], c["r-all"]["value"]) == (3, "0.333333") and (c["r-a"]["eligible_count"], c["r-a"]["value"]) == (2, "0.500000")


def test_no_rows_means_unknown_not_zero():
    w = world_with_customers([])
    w.rule("r-c", "d1", "completeness", {"field": "email"})
    w.rule("r-v", "d1", "validity", {"field": "email", "pattern": PAT})
    w.rule("r-u", "d1", "uniqueness", {"field": "email"})
    m = run_pipeline(w.data()).metrics
    assert m["completeness"]["r-c"]["value"] is None and m["validity"]["r-v"]["all_eligible"]["value"] is None
    assert m["uniqueness"]["r-u"]["group_share"]["value"] is None and m["weighted_score"]["datasets"]["d1"]["value"] is None
    assert m["weighted_score"]["datasets"]["d1"]["measured_dimensions"] == []


# ------------------------------------------------------------------------------------------------------ validity
def test_validity_is_format_validity_and_shows_both_denominators():
    w = world_with_customers(["a@b.co", "bad", None, "", "c@d.org", "x@y.z"])
    w.rule("r-v", "d1", "validity", {"field": "email", "pattern": PAT})
    v = run_pipeline(w.data()).metrics["validity"]["r-v"]
    assert (v["eligible_count"], v["populated_count"], v["passing_count"]) == (6, 4, 2)
    assert v["all_eligible"] == {"label": "validity_all_eligible", "value": "0.333333"} and v["populated_only"] == {"label": "validity_populated_only", "value": "0.500000"}


def test_validity_with_nothing_populated_is_unknown_for_populated_only():
    w = world_with_customers([None, " "])
    w.rule("r-v", "d1", "validity", {"field": "email", "pattern": PAT})
    v = run_pipeline(w.data()).metrics["validity"]["r-v"]
    assert v["all_eligible"]["value"] == "0.000000" and v["populated_only"]["value"] is None


def test_the_closing_dollar_does_not_match_before_a_final_newline():
    assert pattern_matches(PAT, "a@b.co") and not pattern_matches(PAT, "a@b.co\n") and pattern_matches(r"^a[ \t\r\n\f\v]*$", "a\n") and pattern_matches("@", "a@b\n")


def test_non_text_populated_values_fail_a_text_pattern():
    w = World()
    w.owner("o1")
    w.dataset("d1", "o1", [{"row_id": "1", "email": 42}, {"row_id": "2", "email": "a@b.co"}])
    w.rule("r-v", "d1", "validity", {"field": "email", "pattern": PAT})
    assert run_pipeline(w.data()).metrics["validity"]["r-v"]["passing_count"] == 1


# ------------------------------------------------------------------------------------------------------ uniqueness
def test_uniqueness_group_share_and_row_share_differ_and_null_keys_are_failures():
    w = world_with_customers(["a", "a", "a", "b", "b", "c", None, "  "])
    w.rule("r-u", "d1", "uniqueness", {"field": "email"}, severity="critical")
    u = run_pipeline(w.data()).metrics["uniqueness"]["r-u"]
    assert (u["null_key_count"], u["distinct_keys"], u["duplicate_groups"], u["duplicate_rows"]) == (2, 3, 2, 3)
    assert (u["group_share"]["value"], u["row_share"]["value"]) == ("0.666667", "0.375000")
    ws = run_pipeline(w.data()).metrics["weighted_score"]["datasets"]["d1"]
    assert ws["dimension_scores"]["uniqueness"] == "0.375000" and ws["critical_failures"] == 5 == 2 + 3        # null keys + rows beyond the first
    # D-10 R7-05: the score is (eligible - null-key rows - duplicate rows) / eligible = (8 - 2 - 3) / 8, and the null-key rows are listed apart
    assert u["null_key_row_ids"] == ["r-0007", "r-0008"]


def test_keys_are_compared_as_exact_text():
    w = World()
    w.owner("o1")
    w.dataset("d1", "o1", [{"row_id": "1", "k": "1"}, {"row_id": "2", "k": 1}, {"row_id": "3", "k": "01"}, {"row_id": "4", "k": "A"}, {"row_id": "5", "k": "a"}])
    w.rule("r-u", "d1", "uniqueness", {"field": "k"})
    u = run_pipeline(w.data()).metrics["uniqueness"]["r-u"]
    assert (u["distinct_keys"], u["duplicate_rows"]) == (4, 1)                    # "1" and the number 1 are one key; "01", "A" and "a" are others


# ------------------------------------------------------------------------------------------------------ relationship integrity
def fk_world(children, parents, parent_ds=True):
    w = World()
    w.owner("o1")
    w.dataset("p", "o1", [{"row_id": f"p{i}", "k": v} for i, v in enumerate(parents)])
    w.dataset("c", "o1", [{"row_id": f"c{i}", "k": v} for i, v in enumerate(children)])
    w.rule("r-fk", "c", "relationship", {"field": "k", "parent_dataset_id": "p", "parent_field": "k"}, severity="high")
    return w


def test_null_and_blank_foreign_keys_are_counted_apart_not_dropped_and_not_matched():
    r = run_pipeline(fk_world(["a", "b", None, "", "  ", "zz"], ["a", "b", "c"]).data()).metrics["relationship_integrity"]["r-fk"]
    assert (r["total_fk_count"], r["null_fk_count"], r["eligible_count"], r["matched_count"], r["unmatched_count"], r["value"]) == (6, 3, 3, 2, 1, "0.666667")
    assert r["total_fk_count"] == r["null_fk_count"] + r["eligible_count"]


def test_all_null_foreign_keys_leave_the_value_unknown_with_the_nulls_counted():
    r = run_pipeline(fk_world([None, None], ["a"]).data()).metrics["relationship_integrity"]["r-fk"]
    assert (r["null_fk_count"], r["eligible_count"], r["value"]) == (2, 0, None)


def test_a_blank_parent_key_matches_nothing_and_a_missing_parent_dataset_matches_nothing():
    assert run_pipeline(fk_world(["a", ""], ["a", None, " "]).data()).metrics["relationship_integrity"]["r-fk"]["value"] == "1.000000"
    w = fk_world(["a"], ["a"])
    w.d["dataset_rows"].pop("p")
    assert run_pipeline(w.data()).metrics["relationship_integrity"]["r-fk"]["value"] == "0.000000"


# ------------------------------------------------------------------------------------------------------ timeliness
def tl_world(as_of, refreshed, tz="UTC", local="06:00", grace=60, monitored=True):
    w = World(as_of)
    w.owner("o1")
    w.dataset("d1", "o1", monitored=monitored, refresh_timezone=tz, refresh_local_time=local, refresh_grace_minutes=grace, last_refreshed_at=refreshed,
              registered_at="2026-01-01T00:00:00Z")
    w.rule("r-t", "d1", "timeliness", {"target": "dataset_schedule"})
    return w


@pytest.mark.parametrize("refreshed,on_time", [("2026-10-04T06:00:00Z", True), ("2026-10-04T05:59:59Z", False), ("2026-10-04T06:59:59Z", True),
                                               ("2026-10-04T07:00:00Z", False), (None, False)])
def test_the_window_is_half_open_a_refresh_at_the_deadline_is_late(refreshed, on_time):
    t = run_pipeline(tl_world("2026-10-05T00:00:00Z", refreshed).data()).metrics["timeliness"]
    assert t["datasets"]["d1"]["on_time"] is on_time and t["value"] == ("1.000000" if on_time else "0.000000")
    assert t["datasets"]["d1"]["evaluated_occurrence_utc"] == "2026-10-04T06:00:00Z" and t["datasets"]["d1"]["deadline_utc"] == "2026-10-04T07:00:00Z"


def test_an_open_occurrence_is_judged_on_its_own_window_not_on_yesterdays():
    """D-10 R7-01. At 06:30Z the 06:00 occurrence (deadline 07:00Z) is open: a refresh in it is on time, no refresh yet is pending
    (neither on time nor late, outside the denominator), and once its deadline has passed with no refresh it is late."""
    def at(as_of, refreshed):
        return run_pipeline(tl_world(as_of, refreshed).data()).metrics["timeliness"]
    refreshed = at("2026-10-05T06:30:00Z", "2026-10-05T06:10:00Z")
    assert refreshed["datasets"]["d1"]["state"] == "on_time" and refreshed["datasets"]["d1"]["evaluated_occurrence_utc"] == "2026-10-05T06:00:00Z"
    assert (refreshed["monitored_datasets"], refreshed["evaluated_datasets"], refreshed["pending_count"], refreshed["value"]) == (1, 1, 0, "1.000000")
    waiting = at("2026-10-05T06:30:00Z", "2026-10-04T06:10:00Z")          # yesterday's refresh does not make today's occurrence on time
    assert waiting["datasets"]["d1"]["state"] == "pending" and waiting["datasets"]["d1"]["on_time"] is None
    assert (waiting["monitored_datasets"], waiting["evaluated_datasets"], waiting["pending_count"], waiting["on_time_count"], waiting["value"]) == (1, 0, 1, 0, None)
    late = at("2026-10-05T07:00:00Z", "2026-10-04T06:10:00Z")             # the deadline equal to the as-of has passed
    assert late["datasets"]["d1"]["state"] == "late" and late["datasets"]["d1"]["evaluated_occurrence_utc"] == "2026-10-05T06:00:00Z" and late["value"] == "0.000000"
    future = at("2026-10-05T06:30:00Z", "2026-10-05T06:45:00Z")           # a refresh after the as-of has not happened yet
    assert future["datasets"]["d1"]["state"] == "pending"


def test_a_pending_dataset_is_not_measured_by_its_rule_and_does_not_enter_the_score():
    r = run_pipeline(tl_world("2026-10-05T06:30:00Z", "2026-10-04T06:10:00Z").data())
    assert r.computation.rules["runs"]["r-t"]["eligible_count"] == 0 and r.computation.rules["runs"]["r-t"]["failure_count"] == 0
    assert r.metrics["weighted_score"]["datasets"]["d1"]["value"] is None and r.metrics["weighted_score"]["datasets"]["d1"]["measured_dimensions"] == []


@pytest.mark.parametrize("tz,local,occurrence", [("America/New_York", "06:00", "2026-10-04T10:00:00Z"), ("Europe/London", "07:00", "2026-10-04T06:00:00Z"),
                                                 ("Asia/Kolkata", "06:00", "2026-10-04T00:30:00Z"), ("Australia/Lord_Howe", "06:00", "2026-10-04T19:00:00Z"),
                                                 ("Pacific/Auckland", "06:00", "2026-10-04T17:00:00Z")])
def test_the_schedule_is_in_the_datasets_own_zone_with_its_dst(tz, local, occurrence):
    t = run_pipeline(tl_world("2026-10-05T00:00:00Z", None, tz, local, 30).data()).metrics["timeliness"]["datasets"]["d1"]
    assert t["evaluated_occurrence_utc"] == occurrence


def test_a_local_time_that_occurs_twice_is_the_later_instant_and_a_missing_one_uses_the_earlier_offset():
    twice = run_pipeline(tl_world("2026-10-25T20:00:00Z", None, "Europe/London", "01:30", 30).data()).metrics["timeliness"]["datasets"]["d1"]
    assert twice["evaluated_occurrence_utc"] == "2026-10-25T01:30:00Z"            # 01:30 happened at 00:30Z (BST) and at 01:30Z (GMT)
    gap = run_pipeline(tl_world("2026-03-08T20:00:00Z", None, "America/New_York", "02:30", 30).data()).metrics["timeliness"]["datasets"]["d1"]
    assert gap["evaluated_occurrence_utc"] == "2026-03-08T07:30:00Z"              # 02:30 never happened on that day in New York


def test_only_monitored_datasets_count_and_an_unmonitored_timeliness_rule_is_not_measured():
    w = tl_world("2026-10-05T00:00:00Z", "2026-10-04T06:10:00Z", monitored=False)
    r = run_pipeline(w.data())
    assert r.metrics["timeliness"] == {"monitored_datasets": 0, "evaluated_datasets": 0, "pending_count": 0, "on_time_count": 0, "value": None, "datasets": {}}
    assert r.computation.rules["runs"]["r-t"]["eligible_count"] == 0 and r.metrics["weighted_score"]["datasets"]["d1"]["measured_dimensions"] == []


# ------------------------------------------------------------------------------------------------------ the weighted score
def scored_world(**kw):
    w = world_with_customers(["a@b.co", "x", None, "c@d.org"], **kw)
    w.rule("r-c", "d1", "completeness", {"field": "email"})
    w.rule("r-v", "d1", "validity", {"field": "email", "pattern": PAT})
    return w


def test_weighted_score_drops_unmeasured_dimensions_from_both_sums():
    ws = run_pipeline(scored_world().data()).metrics["weighted_score"]["datasets"]["d1"]
    # completeness 3/4 (w .25), validity populated-only 2/3 (w .25): (0.25*.75 + 0.25*2/3) / 0.5
    assert ws["measured_dimensions"] == ["completeness", "validity"] and ws["weight_sum"] == "0.500000"
    assert ws["value"] == p6((Fraction(1, 4) * Fraction(3, 4) + Fraction(1, 4) * Fraction(2, 3)) / Fraction(1, 2)) == "0.708333"


def test_the_weight_version_changes_the_score_and_is_named_in_the_result():
    r = run_pipeline(scored_world().data())
    assert r.metrics["weighted_score"]["by_weight_version"]["w1"]["d1"] == p6((Fraction(4, 10) * Fraction(3, 4) + Fraction(3, 10) * Fraction(2, 3)) / Fraction(7, 10))
    w1 = run_pipeline(scored_world().data(), weight_version="w1")
    assert w1.metrics["weighted_score"]["datasets"]["d1"]["weight_version"] == "w1" and w1.computation.rules["runs"]["r-c"]["weight_version"] == "w1"
    assert w1.metrics["weighted_score"]["datasets"]["d1"]["value"] != r.metrics["weighted_score"]["datasets"]["d1"]["value"]
    with pytest.raises(DomainError) as e:
        run_pipeline(scored_world().data(), weight_version="w9")
    assert e.value.code == UNKNOWN_WEIGHT_VERSION


def test_the_version_in_force_follows_as_of():
    assert run_pipeline(scored_world(as_of="2026-08-31T23:59:59Z").data()).computation.weight_version == "w1"
    assert run_pipeline(scored_world(as_of="2026-09-01T00:00:00Z").data()).computation.weight_version == "w2"


def test_several_rules_of_one_dimension_contribute_their_mean():
    w = scored_world()
    w.d["dataset_rows"]["d1"] = [{"row_id": f"r{i}", "email": e, "alt": a} for i, (e, a) in enumerate([("a", "a"), ("b", None), ("c", None), ("d", None)])]
    w.rule("r-c2", "d1", "completeness", {"field": "alt"})
    sc = run_pipeline(w.data()).metrics["weighted_score"]["datasets"]["d1"]["dimension_scores"]["completeness"]
    assert sc == "0.625000"                                                       # (4/4 + 1/4) / 2


def test_a_perfect_score_still_shows_the_critical_override_when_a_critical_failure_is_open():
    w = World()
    w.owner("o1")
    w.dataset("d1", "o1", rows_of("k", ["a", "a", "b"]) + [{"row_id": f"x{i}", "k": f"u{i}"} for i in range(500)])
    w.rule("r-k", "d1", "uniqueness", {"field": "k"}, severity="critical")
    ws = run_pipeline(w.data()).metrics["weighted_score"]["datasets"]["d1"]
    assert Fraction(ws["value"]) > Fraction("0.99") and ws["critical_override"] is True and ws["critical_failures"] == 1


def test_the_override_is_not_derived_from_the_score_and_an_open_critical_issue_alone_triggers_it():
    w = World()
    w.owner("o1")
    w.dataset("d1", "o1", rows_of("k", ["a", "b"]))
    w.rule("r-k", "d1", "uniqueness", {"field": "k"}, severity="critical")
    w.run("rr-1", "r-k", "2026-10-01T00:00:00Z", 2, 1)
    w.d["issues"].append({"issue_id": "i1", "rule_run_id": "rr-1", "owner_id": "o1", "status": "investigating", "detected_at": "2026-10-01T00:00:00Z",
                          "due_at": None, "closed_at": None, "verification_run_id": None, "reopened_at": []})
    ws = run_pipeline(w.data()).metrics["weighted_score"]["datasets"]["d1"]
    assert (ws["value"], ws["critical_failures"], ws["critical_open_issues"], ws["critical_override"]) == ("1.000000", 0, 1, True)


def test_critical_failures_count_active_rules_only():
    w = World()
    w.owner("o1")
    w.dataset("d1", "o1", rows_of("k", ["a", "a"]))
    w.rule("r-k", "d1", "uniqueness", {"field": "k"}, severity="critical", status="disabled", disabled_at="2026-09-01T00:00:00Z", disabled_reason="x")
    r = run_pipeline(w.data())
    assert r.metrics["critical_failures"]["failures"] == 0 and r.computation.rules["disabled"]["r-k"]["disabled_reason"] == "x"
    assert run_pipeline(w.data(), as_of="2026-08-01T00:00:00Z").metrics["critical_failures"]["failures"] == 1       # it was active before it was disabled


# ------------------------------------------------------------------------------------------------------ comparable runs
def test_runs_are_comparable_only_under_the_same_rule_version():
    w = world_with_customers(["a", None])
    w.rule("r-c", "d1", "completeness", {"field": "email"}, version=2)
    w.run("old", "r-c", "2026-10-01T00:00:00Z", 10, 5, version=1)
    c = run_pipeline(w.data()).computation.rules["comparisons"]["r-c"]
    assert c["comparable"] is False and c["reason"] == "RULE_VERSION_DIFFERS" and c["failure_rate_previous"] is None and c["failure_rate_current"] is None
    w.run("older", "r-c", "2026-10-02T00:00:00Z", 10, 5, version=2)
    c = run_pipeline(w.data()).computation.rules["comparisons"]["r-c"]
    assert c["comparable"] is True and (c["previous_run_id"], c["failure_rate_previous"], c["failure_rate_current"]) == ("older", "0.500000", "0.500000")


def test_reruns_and_later_runs_are_not_the_previous_run():
    w = world_with_customers(["a", None])
    w.rule("r-c", "d1", "completeness", {"field": "email"})
    w.run("s1", "r-c", "2026-10-01T00:00:00Z", 10, 5)
    w.run("rr", "r-c", "2026-10-02T00:00:00Z", 3, 0, kind="rerun", for_issue="i")
    w.run("later", "r-c", "2026-10-09T00:00:00Z", 10, 9)
    assert run_pipeline(w.data()).computation.rules["comparisons"]["r-c"]["previous_run_id"] == "s1"


def test_a_disabled_rule_keeps_its_runs_and_issues_readable():
    r = run_pipeline(__import__("support_db").golden_inputs())
    d = r.computation.rules["disabled"]["r-ord-amount-range"]
    assert (d["runs_retained"], d["issues_retained"]) == (2, 1) and "r-ord-amount-range" not in r.computation.rules["runs"] and r.computation.rules["active_count"] == 8
    assert r.metrics["resolution_time"]["issues"]["iss-004"]["class"] == "claimed"       # its issue is still listed


# ------------------------------------------------------------------------------------------------------ issues
def issue_world(**issue):
    w = World()
    w.owner("o1")
    w.dataset("d1", "o1", rows_of("k", ["a", "b"]))
    w.rule("r-k", "d1", "completeness", {"field": "k"}, severity="high")
    w.run("rr-1", "r-k", "2026-10-01T00:00:00Z", 10, 2)
    base = {"issue_id": "i1", "rule_run_id": "rr-1", "owner_id": "o1", "status": "closed", "detected_at": "2026-10-01T00:00:00Z", "due_at": None,
            "closed_at": "2026-10-02T00:00:00Z", "verification_run_id": None, "reopened_at": []}
    w.d["issues"].append({**base, **issue})
    return w


def klass(w, **kw):
    return run_pipeline(w.data(), **kw).metrics["resolution_time"]["issues"]["i1"]


def test_a_close_without_a_rerun_is_claimed_and_never_resolved():
    k = klass(issue_world())
    assert k["class"] == "claimed" and k["claimed_hours"] == "24.0000" and k["resolution_hours"] is None
    r = run_pipeline(issue_world().data()).metrics["resolution_time"]
    assert (r["resolved_count"], r["claimed_count"], r["mean_hours"]) == (0, 1, None)


def test_resolved_at_is_the_verifying_reruns_time_not_the_close():
    w = issue_world(verification_run_id="rr-2")
    w.run("rr-2", "r-k", "2026-10-03T12:00:00Z", 2, 0, kind="rerun", for_issue="i1")
    k = klass(w)
    assert (k["class"], k["resolution_hours"]) == ("resolved", "60.0000")             # 10-01 00:00 -> 10-03 12:00, not the close on 10-02


@pytest.mark.parametrize("patch,code", [({"failure_count": 1}, "RERUN_STILL_FAILING"), ({"rule_version": 2}, "RULE_VERSION_DIFFERS"),
                                        ({"for_issue": "other"}, "NOT_A_RERUN_OF_THIS_ISSUE"), ({"kind": "scheduled", "for_issue": None}, "NOT_A_RERUN_OF_THIS_ISSUE"),
                                        ({"at": "2026-09-30T00:00:00Z"}, "RERUN_BEFORE_DETECTION")])
def test_a_verification_that_is_not_a_successful_rerun_of_the_same_rule_version_is_rejected(patch, code):
    w = issue_world(verification_run_id="rr-2")
    args = {"at": "2026-10-03T00:00:00Z", "eligible": 2, "failures": patch.get("failure_count", 0), "version": patch.get("rule_version", 1),
            "kind": patch.get("kind", "rerun"), "for_issue": patch.get("for_issue", "i1")}
    if "at" in patch:
        args["at"] = patch["at"]
    w.run("rr-2", "r-k", **args)
    r = run_pipeline(w.data())
    assert [(x.entity, x.id, x.reason_code, x.message) for x in r.ingest.rejected] == [("issues", "i1", "VERIFICATION_RUN_INVALID", code)]
    assert [(x["entity"], x["id"], x["reason_code"]) for x in r.rejected] == [("issues", "i1", "VERIFICATION_RUN_INVALID")]
    from trustledger.issues import verification_problem
    from trustledger.models import parse
    runs = {x["rule_run_id"]: parse("rule_runs", x) for x in w.d["rule_runs"]}
    issue = parse("issues", w.d["issues"][0])
    assert verification_problem(issue, runs["rr-1"], runs["rr-2"]) == code


def test_open_issues_age_to_as_of_and_a_reopened_issue_keeps_its_first_detected_at():
    w = issue_world(status="open", reopened_at=["2026-10-04T00:00:00Z", "2026-10-06T00:00:00Z"], verification_run_id="rr-2")
    w.run("rr-2", "r-k", "2026-10-02T00:00:00Z", 2, 0, kind="rerun", for_issue="i1")
    k = klass(w)
    assert (k["class"], k["reopen_cycles"], k["age_hours"]) == ("open", 1, "96.0000")           # as_of 10-05: only the first reopen has happened; age from 10-01
    k = klass(w, as_of="2026-10-07T00:00:00Z")
    assert (k["reopen_cycles"], k["age_hours"]) == (2, "144.0000")
    r = run_pipeline(w.data()).metrics["resolution_time"]
    assert (r["reopened_count"], r["reopen_cycles_total"]) == (1, 1)


def test_a_closed_issue_whose_old_rerun_predates_a_reopen_is_claimed_again():
    w = issue_world(status="closed", closed_at="2026-10-04T12:00:00Z", reopened_at=["2026-10-04T00:00:00Z"], verification_run_id="rr-2")
    w.run("rr-2", "r-k", "2026-10-02T00:00:00Z", 2, 0, kind="rerun", for_issue="i1")
    assert klass(w)["class"] == "claimed"


def test_an_issue_not_yet_closed_at_as_of_is_open_then():
    assert klass(issue_world(), as_of="2026-10-01T12:00:00Z")["class"] == "open"
    assert "i1" not in run_pipeline(issue_world().data(), as_of="2026-09-30T00:00:00Z").metrics["resolution_time"]["issues"]


# ------------------------------------------------------------------------------------------------------ ownership, definitions, lineage
def test_ownership_coverage_inactive_owner_uncovered_and_time_of_deactivation_matters():
    w = World()
    w.owner("act")
    w.owner("gone", active=False, deactivated_at="2026-10-01T00:00:00Z")
    w.owner("soon", deactivated_at="2026-11-01T00:00:00Z")
    for n, o in (("d1", "act"), ("d2", "gone"), ("d3", "soon")):
        w.dataset(n, o)
    o = run_pipeline(w.data()).metrics["ownership_coverage"]
    assert (o["covered"], o["datasets"], o["value"], o["uncovered"]) == (2, 3, "0.666667", ["d2"])
    assert run_pipeline(w.data(), as_of="2026-11-02T00:00:00Z").metrics["ownership_coverage"]["uncovered"] == ["d2", "d3"]
    assert run_pipeline(w.data(), as_of="2026-09-30T00:00:00Z").metrics["ownership_coverage"]["uncovered"] == []


def mv(mid, n, valid, status="published", **kw):
    return {"metric_version_id": f"{mid}-{n}", "metric_id": mid, "metric_name": mid, "version_number": n, "definition": "d", "grain": "g", "source_fields": ["a"],
            "owner_id": "o1", "refresh": "daily", "valid_from": valid, "status": status, **kw}


def test_definition_coverage_checklist_items_and_only_published_count():
    w = World()
    w.owner("o1")
    w.d["metric_versions"] = [mv("ok", 1, "2026-01-01T00:00:00Z"), mv("blank", 1, "2026-01-01T00:00:00Z", definition="  ", grain=""),
                              mv("nofields", 1, "2026-01-01T00:00:00Z", source_fields=[" "]), mv("noowner", 1, "2026-01-01T00:00:00Z", owner_id="ghost"),
                              mv("draft", 1, "2026-01-01T00:00:00Z", status="draft"), mv("norefresh", 1, "2026-01-01T00:00:00Z", refresh=None)]
    c = run_pipeline(w.data()).metrics["definition_coverage"]
    assert (c["published_metrics"], c["complete_metrics"], c["value"]) == (5, 1, "0.200000")
    assert c["incomplete"] == {"blank": ["definition", "grain"], "nofields": ["source_fields"], "noowner": ["owner"], "norefresh": ["refresh"]}


def test_a_later_version_replaces_the_earlier_and_a_draft_successor_does_not_unpublish():
    w = World()
    w.owner("o1")
    w.d["metric_versions"] = [mv("m", 1, "2026-01-01T00:00:00Z", status="superseded", grain=""), mv("m", 2, "2026-09-01T00:00:00Z"), mv("m", 3, "2026-09-20T00:00:00Z", status="draft")]
    d = run_pipeline(w.data()).computation.definitions
    assert d["effective_at_as_of"] == {"m": "m-2"} and d["effective_at_probe"] == {"m": "m-1"} and d["version_counts"] == {"m": 3}
    assert d["versions_without_change_record"] == ["m-2", "m-3"]
    assert run_pipeline(w.data()).metrics["definition_coverage"]["complete_metrics"] == 1


def test_lineage_coverage_is_over_distinct_pairs_and_inferred_is_never_observed():
    w = World()
    w.owner("o1")
    for d in "abc":
        w.dataset(d, "o1")
    e = lambda i, s, t, ev, at=None: {"edge_id": i, "source_dataset_id": s, "target_dataset_id": t, "evidence_type": ev, "observed_at": at}  # noqa: E731
    w.d["lineage_edges"] = [e("d1", "a", "b", "declared"), e("d2", "b", "c", "declared"), e("o1", "a", "b", "observed", "2026-10-01T00:00:00Z"),
                            e("o2", "a", "b", "observed", "2026-10-02T00:00:00Z"), e("o3", "c", "a", "observed", "2026-10-02T00:00:00Z"), e("i1", "b", "c", "inferred")]
    lc = run_pipeline(w.data()).metrics["lineage_coverage"]
    assert (lc["declared_edges"], lc["observed_rows"], lc["observed_distinct"], lc["observed_matching_declared"], lc["value"]) == (2, 3, 2, 1, "0.500000")
    assert lc["undeclared_observed"] == [{"source_dataset_id": "c", "target_dataset_id": "a"}] and lc["inferred_edges"] == [{"source_dataset_id": "b", "target_dataset_id": "c"}]
    assert lc["declared_not_observed"] == [{"source_dataset_id": "b", "target_dataset_id": "c"}]       # the inferred edge did not make it observed


# ------------------------------------------------------------------------------------------------------ matching
def match_world():
    w = World()
    for o, role in (("p", "analyst"), ("s1", "steward"), ("s2", "admin"), ("an", "analyst")):
        w.owner(o, role)
    w.d["customer_records"] = [{"record_id": f"r{i}", "source_system": "s", "source_customer_id": str(i), "normalized_name": "n", "address_key": "a"} for i in range(1, 7)]
    w.d["synthetic_truth"]["true_entity"] = {"r1": "A", "r2": "A", "r3": "B", "r4": "C", "r5": "D", "r6": "D"}
    cand = lambda i, a, b, pb="p": {"candidate_id": i, "left_record_id": a, "right_record_id": b, "score": "0.9", "features": {"f": "1"}, "explanation": "x",  # noqa: E731
                                    "uncertainty": None, "proposed_by": pb, "proposed_at": "2026-10-01T00:00:00Z"}
    w.d["match_candidates"] = [cand("c1", "r1", "r2"), cand("c2", "r3", "r4"), cand("c3", "r5", "r6")]
    dec = lambda i, c, who, kind, at, rev=None, reason=None: {"merge_id": i, "candidate_id": c, "reviewer_id": who, "decision": kind, "decided_at": at,  # noqa: E731
                                                              "reverses_merge_id": rev, "reason": reason}
    w.dec = dec
    return w


def test_candidates_are_stored_once_in_canonical_order():
    w = match_world()
    extra = [{**w.d["match_candidates"][0], "candidate_id": "rev", "left_record_id": "r2", "right_record_id": "r1"},
             {**w.d["match_candidates"][0], "candidate_id": "swap", "left_record_id": "r6", "right_record_id": "r4"},
             {**w.d["match_candidates"][0], "candidate_id": "same", "left_record_id": "r1", "right_record_id": "r1"},
             {**w.d["match_candidates"][0], "candidate_id": "unk", "left_record_id": "r1", "right_record_id": "r99"},
             {**w.d["match_candidates"][0], "candidate_id": "bad", "left_record_id": "r1", "right_record_id": "r3", "score": "1.5"}]
    w.d["match_candidates"] += extra
    got = {(r["id"]): r["reason_code"] for r in run_pipeline(w.data()).rejected}
    assert got == {"rev": "DUPLICATE_PAIR", "swap": "NON_CANONICAL_ORDER", "same": "SAME_RECORD", "unk": "UNKNOWN_RECORD", "bad": "INVALID_CANDIDATE"}


def test_a_merge_needs_a_reviewer_other_than_the_proposer_with_a_steward_or_admin_role():
    w = match_world()
    w.d["merge_decisions"] = [w.dec("m1", "c1", "p", "approve", "2026-10-02T00:00:00Z"), w.dec("m2", "c2", "an", "approve", "2026-10-02T00:00:00Z"),
                              w.dec("m3", "c3", "s1", "approve", "2026-10-02T00:00:00Z")]
    r = run_pipeline(w.data())
    assert {x["id"]: x["reason_code"] for x in r.rejected} == {"m1": "REVIEWER_IS_PROPOSER", "m2": "ROLE_NOT_PERMITTED"}
    assert r.computation.matching["approved"] == 1 and r.computation.matching["identity_map"]["r6"] == "r5"


def test_a_reversal_restores_both_identities_keeps_the_history_and_the_approval_stays_in_precision():
    w = match_world()
    w.d["merge_decisions"] = [w.dec("m1", "c1", "s1", "approve", "2026-10-02T00:00:00Z"), w.dec("m3", "c3", "s1", "approve", "2026-10-02T01:00:00Z"),
                              w.dec("m3r", "c3", "s2", "reverse", "2026-10-03T00:00:00Z", "m3", "wrong people")]
    r = run_pipeline(w.data())
    assert r.computation.matching["identity_map"]["r6"] == "r6" and r.computation.matching["identity_map"]["r2"] == "r1"
    assert [(h["merge_id"], h["state"], h["reversed_by"]) for h in r.computation.matching["mapping_history"]] == [("m1", "active", None), ("m3", "reversed", "m3r")]
    assert (r.metrics["match_precision"]["approved_decisions"], r.metrics["match_precision"]["approved_correct"]) == (2, 2)
    assert r.computation.matching["merges_reversed"] == 1 and r.computation.matching["active_merges"] == 1


def test_invalid_reversals_and_second_decisions_are_rejected():
    w = match_world()
    w.d["merge_decisions"] = [w.dec("m1", "c1", "s1", "approve", "2026-10-02T00:00:00Z"), w.dec("m1b", "c1", "s2", "reject", "2026-10-02T01:00:00Z"),
                              w.dec("r1", "c1", "s2", "reverse", "2026-10-03T00:00:00Z", "m1", "r"), w.dec("r2", "c1", "s2", "reverse", "2026-10-03T01:00:00Z", "m1", "again"),
                              w.dec("r3", "c2", "s2", "reverse", "2026-10-03T02:00:00Z", "m1", "wrong candidate"), w.dec("r4", "c1", "s2", "reverse", "2026-10-03T03:00:00Z", "m1b", "x"),
                              w.dec("r5", "c2", "s2", "reverse", "2026-10-03T04:00:00Z", "nope", "x")]
    got = {x["id"]: x["reason_code"] for x in run_pipeline(w.data()).rejected}
    assert got == {"m1b": "ALREADY_REVIEWED", "r2": "ALREADY_REVERSED", "r3": "INVALID_REVERSAL", "r4": "DEPENDENT_REJECTED", "r5": "UNKNOWN_MERGE"}


def test_precision_is_approved_and_confirmed_over_approved_and_the_wider_share_is_labelled_apart():
    w = match_world()
    w.d["merge_decisions"] = [w.dec("m1", "c1", "s1", "approve", "2026-10-02T00:00:00Z"), w.dec("m2", "c2", "s1", "approve", "2026-10-02T00:00:00Z"),
                              w.dec("m3", "c3", "s1", "reject", "2026-10-02T00:00:00Z")]
    p = run_pipeline(w.data()).metrics["match_precision"]
    assert (p["approved_decisions"], p["approved_correct"], p["precision"]) == (2, 1, "0.500000")             # r3/r4 are different people
    assert (p["reviewed"], p["reviewed_correct"], p["reviewed_correct_share"]) == (3, 2, "0.666667")        # the rejection of a true pair is "not correct" here


def test_candidates_and_decisions_after_as_of_do_not_exist_yet_and_the_window_narrows_decisions():
    w = match_world()
    w.d["merge_decisions"] = [w.dec("m1", "c1", "s1", "approve", "2026-10-06T00:00:00Z"), w.dec("m2", "c2", "s1", "approve", "2026-10-02T00:00:00Z")]
    assert run_pipeline(w.data()).computation.matching["approved"] == 1                                         # as_of 10-05: m1 is in the future
    assert run_pipeline(w.data(), as_of="2026-10-07T00:00:00Z").computation.matching["approved"] == 2
    win = run_pipeline(w.data(), as_of="2026-10-07T00:00:00Z", window=(None, deepcopy(__import__("trustledger.timeutil", fromlist=["x"]).parse_ts("2026-10-03T00:00:00Z"))))
    assert win.computation.matching["approved"] == 1


# ------------------------------------------------------------------------------------------------------ ingest odds and ends
def test_ingest_rejects_malformed_and_duplicate_records_by_reason():
    w = world_with_customers(["a"])
    w.d["owners"].append({"owner_id": "o1", "owner_name": "dup", "team": "t", "role": "steward", "active": True, "deactivated_at": None})
    w.d["owners"].append({"owner_id": "bad role", "owner_name": "x", "team": "t", "role": "king", "active": True, "deactivated_at": None})
    w.d["datasets"].append({**w.d["datasets"][0], "dataset_id": "ds-unk", "owner_id": "ghost"})
    w.d["datasets"].append({**w.d["datasets"][0], "dataset_id": "ds-cls", "classification": "  "})
    w.d["datasets"].append({**w.d["datasets"][0], "dataset_id": "ds-late", "registered_at": "2026-06-02T00:00:00Z", "owner_id": "o2"})
    w.d["owners"].append({"owner_id": "o2", "owner_name": "x", "team": "t", "role": "steward", "active": False, "deactivated_at": "2026-06-01T00:00:00Z"})
    w.d["datasets"].append({**w.d["datasets"][0], "dataset_id": "ds-mon", "monitored": True})
    w.d["dataset_rows"]["d1"] += [{"row_id": "r-0001", "email": "dup"}, {"email": "no id"}, {"row_id": "nested", "email": {"a": 1}}, {"row_id": "flt", "email": 1.5}]
    got = {(x["entity"], x["id"]): x["reason_code"] for x in run_pipeline(w.data()).rejected}
    assert got == {("owners", "o1"): "DUPLICATE_ID", ("owners", "bad role"): "MALFORMED_RECORD", ("datasets", "ds-unk"): "UNKNOWN_OWNER", ("datasets", "ds-cls"): "CLASSIFICATION_REQUIRED",
                   ("datasets", "ds-late"): "OWNER_INACTIVE", ("datasets", "ds-mon"): "SCHEDULE_REQUIRED", ("dataset_rows", "d1/r-0001"): "DUPLICATE_ID",
                   ("dataset_rows", "d1/2"): "MALFORMED_RECORD", ("dataset_rows", "d1/nested"): "MALFORMED_RECORD", ("dataset_rows", "d1/flt"): "MALFORMED_RECORD"}


def test_a_relationship_rule_must_name_its_parent_and_a_rule_for_an_unknown_dataset_is_rejected():
    w = world_with_customers(["a"])
    w.d["quality_rules"].append({"rule_id": "bad", "dataset_id": "d1", "field_id": None, "rule_type": "relationship", "severity": "low", "version_number": 1,
                                 "status": "active", "disabled_at": None, "disabled_reason": None, "definition": {"field": "k"}})
    w.d["quality_rules"].append({"rule_id": "orphan", "dataset_id": "nope", "field_id": None, "rule_type": "completeness", "severity": "low", "version_number": 1,
                                 "status": "active", "disabled_at": None, "disabled_reason": None, "definition": {"field": "k"}})
    assert {x["id"]: x["reason_code"] for x in run_pipeline(w.data()).rejected} == {"bad": "MALFORMED_RECORD", "orphan": "UNKNOWN_DATASET"}


def test_the_pipeline_is_deterministic_and_does_not_mutate_its_input():
    inputs = __import__("support_db").golden_inputs()
    before = deepcopy(inputs)
    a, b = run_pipeline(inputs).golden(), run_pipeline(inputs).golden()
    assert a == b and inputs == before


def test_observed_lineage_edge_without_an_instant_is_malformed():
    """D-08 (A-055 finding): an observed edge needs observed_at and a declared or inferred edge must not carry one;
    the domain now agrees with the database check edges_evidence_ck."""
    from support_db import golden_inputs
    from trustledger import run_pipeline
    base = golden_inputs()
    ds = [d["dataset_id"] for d in base["datasets"]][:2]
    bad = dict(base)
    bad["lineage_edges"] = list(base["lineage_edges"]) + [
        {"edge_id": "edge-x1", "source_dataset_id": ds[0], "target_dataset_id": ds[1], "evidence_type": "observed", "observed_at": None},
        {"edge_id": "edge-x2", "source_dataset_id": ds[0], "target_dataset_id": ds[1], "evidence_type": "declared", "observed_at": "2026-10-01T00:00:00Z"},
    ]
    res = run_pipeline(bad)
    codes = {(r["entity"], r["id"]): r["reason_code"] for r in res.golden()["ingest"]["rejected"]} if "rejected" in res.golden()["ingest"] else {}
    rejected = [r for r in res.ingest.rejected if r.entity == "lineage_edges"] if hasattr(res.ingest, "rejected") else []
    ids = {getattr(r, "id", None) or getattr(r, "record_id", None) for r in rejected} | {k[1] for k in codes if k[0] == "lineage_edges"}
    assert {"edge-x1", "edge-x2"} <= ids
