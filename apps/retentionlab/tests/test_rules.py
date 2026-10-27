"""The domain rules of D-01..D-03 on hand-built worlds, one rule at a time (the rules behind P10-TEST-01..12, below the HTTP layer)."""
from decimal import Decimal
from fractions import Fraction

import pytest

from retentionlab import errors as E
from retentionlab.errors import DomainError
from retentionlab.ingest import validate
from retentionlab.metrics import average_precision, calibration_bins, economics, in_bin, psi
from retentionlab.rules import check_calibration_rows, check_capacity, check_feature_request, check_fit_rows, check_threshold
from retentionlab.split import retained, split_run
from retentionlab.world import World

from mini import Mini, run


def world(m: Mini) -> World:
    d = m.data()
    return World(d, validate(d).accepted)


# ---- D-01 registry: P10-TEST-01 / 08 / 12 -----------------------------------------------------------------------------------------
REG = {r["feature_name"]: r for r in Mini().d["feature_registry"]}


@pytest.mark.parametrize("fields,code", [
    (["cancellation_reason"], E.POST_OUTCOME_FIELD), (["cancellation_survey_score"], E.POST_OUTCOME_FIELD), (["refund_after_cancel"], E.POST_OUTCOME_FIELD),
    (["latent_churn_propensity"], E.LATENT_TRUTH), (["latent_anything_new"], E.LATENT_TRUTH),                       # a latent_ prefix is refused even unregistered
    (["account_id"], E.ID_FEATURE), (["account_id_hash"], E.ID_FEATURE), (["creation_sequence"], E.ID_FEATURE), (["account_id_bucket"], E.ID_FEATURE),
    (["days_since_signup_magic"], E.UNKNOWN_FEATURE)])
def test_every_kind_of_forbidden_field_is_refused_with_its_code(fields, code):
    with pytest.raises(DomainError) as e:
        check_feature_request(REG, fields)
    assert e.value.code == code and e.value.details["offending"] == [{"item": fields[0], "code": code}]


def test_the_first_code_in_priority_order_wins_and_every_offender_is_listed():
    with pytest.raises(DomainError) as e:
        check_feature_request(REG, ["usage_events_30d", "account_id", "nope", "latent_x", "cancellation_reason"])
    assert e.value.code == E.POST_OUTCOME_FIELD
    assert [(o["item"], o["code"]) for o in e.value.details["offending"]] == [("account_id", "ID_FEATURE"), ("nope", "UNKNOWN_FEATURE"),
                                                                              ("latent_x", "LATENT_TRUTH"), ("cancellation_reason", "POST_OUTCOME_FIELD")]


def test_a_registered_field_from_the_generator_manifest_is_latent_truth_even_without_the_flag():
    reg = {**REG, "seed_bucket": {"feature_name": "seed_bucket", "post_outcome": False, "latent": False, "id_derived": False, "lineage": "generator_manifest"}}
    with pytest.raises(DomainError) as e:
        check_feature_request(reg, ["seed_bucket"])
    assert e.value.code == E.LATENT_TRUTH


def test_the_registered_features_pass():
    assert check_feature_request(REG, ["usage_events_30d", "days_since_last_usage", "high_severity_support_90d", "billing_total_90d"]) == [
        "usage_events_30d", "days_since_last_usage", "high_severity_support_90d", "billing_total_90d"]


# ---- D-01 point in time: P10-TEST-02 --------------------------------------------------------------------------------------------------
def test_an_event_that_happened_before_the_cutoff_but_arrived_after_it_is_excluded_and_counted():
    m = Mini()
    a = m.account(1)
    cid = m.cutoff(a, "2026-01-01T00:00:00Z")
    m.event("usage_events", a, "2025-12-20T00:00:00Z")                                       # known in time
    m.event("usage_events", a, "2025-12-30T00:00:00Z", "2026-01-01T00:00:00Z")               # arrives AT the cutoff: late (equal counts)
    m.event("usage_events", a, "2025-12-31T00:00:00Z", "2026-01-05T00:00:00Z")               # arrives after
    m.event("usage_events", a, "2026-01-01T00:00:00Z")                                       # happens at the cutoff: excluded, and NOT late (not before it)
    row = world(m).analyse(cid)
    assert row["features"]["usage_events_30d"] == 1 and row["features"]["days_since_last_usage"] == 12
    assert row["arrived_late"]["usage_events"] == 2 and row["max_available_at"] == "2025-12-20T00:00:00Z"
    assert row["max_available_at"] < row["prediction_at"]


def test_window_start_is_inclusive_cutoff_exclusive_and_a_missing_source_is_null_not_zero():
    m = Mini()
    a = m.account(1)
    cid = m.cutoff(a, "2026-01-01T00:00:00Z")                                                # observation_start 2025-10-03T00:00:00Z
    m.event("billing_events", a, "2025-10-03T00:00:00Z", amount="20.00")                     # exactly the window start: included
    m.event("billing_events", a, "2025-10-02T23:59:59Z", amount="99.00")                     # one second before: excluded
    row = world(m).analyse(cid)
    assert row["features"]["billing_total_90d"] == "20.00" and row["features"]["days_since_last_usage"] is None
    assert row["features"]["usage_events_30d"] == 0 and row["features"]["high_severity_support_90d"] == 0


def test_an_event_available_before_it_happened_is_rejected_at_import():
    m = Mini()
    a = m.account(1)
    m.event("usage_events", a, "2025-12-20T00:00:00Z", "2025-12-19T00:00:00Z")
    out = validate(m.data())
    assert [(r["entity"], r["reason_code"]) for r in out.rejected] == [("usage_events", E.AVAILABILITY_BEFORE_EVENT)] and out.accepted["usage_events"] == []


def test_eligibility_uses_the_subscription_visible_at_the_cutoff():
    m = Mini()
    a, b, c, d = m.account(1), m.account(2), m.account(3, created="2025-10-03T00:00:00Z"), m.account(4, active=False)
    m.event("subscription_events", b, "2025-12-31T00:00:00Z", "2026-01-02T00:00:00Z", event_type="cancel")        # cancelled, but the cancel arrives after the cutoff
    m.event("subscription_events", a, "2025-12-31T00:00:00Z", "2025-12-31T12:00:00Z", event_type="cancel")        # cancelled and known
    ids = {x: m.cutoff(x, "2026-01-01T00:00:00Z") for x in (a, b, c, d)}
    w = world(m)
    assert w.analyse(ids[a])["ineligible_code"] == "NOT_ACTIVE"
    assert w.analyse(ids[b])["eligible"] is True                                              # the account looked active at the time
    assert w.analyse(ids[c])["ineligible_code"] == "CREATED_ON_OR_AFTER_OBSERVATION_START"    # created exactly at observation_start: strict
    assert w.analyse(ids[d])["ineligible_code"] == "NOT_ACTIVE"                                # no visible subscription event at all


# ---- D-01 labels: P10-TEST-07 -------------------------------------------------------------------------------------------------------
def test_labels_censor_immature_rows_and_a_late_cancel_is_not_churn():
    m = Mini(as_of="2026-05-01T00:00:00Z")
    a, b, c = m.account(1), m.account(2), m.account(3)
    m.event("subscription_events", a, "2026-02-01T00:00:00Z", event_type="cancel")                              # inside the horizon, arrives at once
    m.event("subscription_events", b, "2026-03-20T00:00:00Z", "2026-04-15T00:00:00Z", event_type="cancel")      # arrives AT label_end: not < label_end: not churn
    m.event("subscription_events", c, "2026-04-01T00:00:00Z", event_type="cancel")                              # horizon_end exactly: not < horizon_end
    jan = {x: m.cutoff(x, "2026-01-01T00:00:00Z") for x in (a, b, c)}                           # label_end 2026-04-15 <= as_of: mature
    feb = m.cutoff(a, "2026-02-01T00:00:00Z")                                                    # label_end 2026-05-16 > as_of: censored (a is also cancelled by then)
    w = world(m)
    assert [w.analyse(jan[x])["churned"] for x in (a, b, c)] == [True, False, False] and all(w.analyse(jan[x])["mature"] for x in (a, b, c))
    assert (w.analyse(feb)["eligible"], w.analyse(feb)["mature"], w.analyse(feb)["churned"]) == (True, False, None)   # a cancel AT the cutoff is not yet visible; the row is censored
    # equal to as_of is mature; one second later is not
    edge = Mini(as_of="2026-04-15T00:00:00Z")
    x = edge.account(1)
    cid = edge.cutoff(x, "2026-01-01T00:00:00Z")
    assert world(edge).analyse(cid)["mature"] is True
    edge2 = Mini(as_of="2026-04-14T23:59:59Z")
    y = edge2.account(1)
    cid2 = edge2.cutoff(y, "2026-01-01T00:00:00Z")
    r = world(edge2).analyse(cid2)
    assert r["mature"] is False and r["churned"] is None                                          # null, never false


def test_a_censored_row_cannot_be_imported_with_a_label():
    m = Mini()
    a = m.account(1)
    cid = m.cutoff(a, "2026-02-01T00:00:00Z")
    m.d["labels"].append({"label_id": "lb-1", "cutoff_id": cid, "churned": False, "label_end": "2026-05-16T00:00:00Z", "mature": False})
    out = validate(m.data())
    assert [r["reason_code"] for r in out.rejected] == [E.CENSORED_LABEL] and out.accepted["labels"] == []
    m.d["labels"][0]["churned"] = None
    assert validate(m.data()).rejected == []


# ---- D-02 split: P10-TEST-03 / 04 --------------------------------------------------------------------------------------------------------
def test_label_windows_crossing_a_boundary_are_dropped_from_the_earlier_side_and_equal_does_not_cross():
    m = Mini()
    a = m.account(1)
    ends = {"equal": "2025-03-19T00:00:00Z", "crosses": "2025-03-19T00:00:01Z", "early": "2025-03-01T00:00:00Z"}      # label_end = pa + 104 d: 2025-07-01T00:00:00Z for 'equal'
    ids = {k: m.cutoff(m.account(i), v) for i, (k, v) in enumerate(ends.items(), start=2)}
    rows, counts = split_run(world(m), run())
    by = {r["cutoff_id"]: r for r in rows}
    assert by[ids["equal"]]["status"] == "retained" and by[ids["early"]]["status"] == "retained"
    assert (by[ids["crosses"]]["status"], by[ids["crosses"]]["drop_reason"]) == ("dropped", "LABEL_WINDOW")
    assert counts["train"] == {"total": 3, "retained": 2, "label_window": 1, "group_test": 0, "group_validation": 0}


def test_group_purge_counts_membership_by_range_and_test_beats_validation():
    m = Mini()
    a, b, c, d = (m.account(i) for i in (1, 2, 3, 4))
    t1, v1, x1 = m.cutoff(a, "2025-03-01T00:00:00Z"), m.cutoff(a, "2025-07-01T00:00:00Z"), m.cutoff(a, "2026-01-01T00:00:00Z")      # a: train, validation, test
    t2, v2 = m.cutoff(b, "2025-03-01T00:00:00Z"), m.cutoff(b, "2025-07-01T00:00:00Z")                                         # b: train, validation
    t3 = m.cutoff(c, "2025-05-01T00:00:00Z")                                                                                   # c: train, label-dropped
    v3 = m.cutoff(c, "2025-09-15T00:00:00Z")                                                                                   # c: validation, label-dropped
    t4 = m.cutoff(d, "2025-03-01T00:00:00Z")                                                                                   # d: train only
    rows, counts = split_run(world(m), run())
    by = {r["cutoff_id"]: (r["status"], r["drop_reason"]) for r in rows}
    assert by[t1] == ("dropped", "GROUP_TEST") and by[v1] == ("dropped", "GROUP_TEST") and by[x1] == ("retained", None)        # test wins over validation
    assert by[t2] == ("dropped", "GROUP_VALIDATION") and by[v2] == ("retained", None)
    assert by[t3] == ("dropped", "LABEL_WINDOW") and by[v3] == ("dropped", "LABEL_WINDOW")
    assert by[t4] == ("retained", None)
    train_accounts = {r["account_id"] for r in rows if r["split"] == "train" and r["status"] == "retained"}
    val_accounts = {r["account_id"] for r in rows if r["split"] == "validation" and r["status"] == "retained"}
    test_accounts = {r["account_id"] for r in rows if r["split"] == "test" and r["status"] == "retained"}
    assert not (train_accounts & val_accounts) and not (train_accounts & test_accounts) and not (val_accounts & test_accounts)   # no account on both sides


def test_a_row_at_a_boundary_belongs_to_the_later_range_and_rows_past_test_end_are_outside():
    m = Mini()
    a, b, c = m.account(1), m.account(2), m.account(3)
    ids = [m.cutoff(a, "2025-07-01T00:00:00Z"), m.cutoff(b, "2025-12-01T00:00:00Z"), m.cutoff(c, "2026-06-01T00:00:00Z")]
    rows, _ = split_run(world(m), run())
    assert [r["split"] for r in rows] == ["validation", "test", "outside"] and retained(rows, "outside") == {ids[2]}


# ---- fit/calibration/threshold/capacity rules: P10-TEST-05 / 06 / 10 / 11 -----------------------------------------------------------------
def test_leakage_rules():
    train = {"a", "b"}
    check_fit_rows(["a", "b"], train)
    with pytest.raises(DomainError) as e:
        check_fit_rows(["a", "v1", "t1"], train)
    assert e.value.code == E.LEAKAGE and [o["item"] for o in e.value.details["offending"]] == ["v1", "t1"]
    check_calibration_rows(["v1", "v2"], ["t1"], {"v1", "v2"})
    with pytest.raises(DomainError) as e:
        check_calibration_rows(["v1", "v2"], ["t1", "v2"], {"v1", "v2"})
    assert e.value.code == E.CALIBRATION_ON_FIT_ROWS and e.value.details["offending"] == [{"item": "v2", "code": "IN_FIT_ROWS"}]
    with pytest.raises(DomainError) as e:
        check_calibration_rows(["t1"], ["t2"], {"v1"})
    assert e.value.code == E.LEAKAGE


def test_threshold_and_capacity_rules():
    check_threshold("capacity", "validation")
    with pytest.raises(DomainError) as e:
        check_threshold("threshold", "test")
    assert e.value.code == E.THRESHOLD_ON_TEST
    check_capacity("sc", 3, 3)
    with pytest.raises(DomainError) as e:
        check_capacity("sc", 4, 3)
    assert e.value.code == E.CAPACITY_EXCEEDS_POPULATION and e.value.details["offending"][0]["code"] == "CAPACITY_4_GT_3"


# ---- D-03 metrics --------------------------------------------------------------------------------------------------------------------------
def items(pairs):
    return [{"p": Fraction(p), "y": bool(y), "account_id": i} for i, (p, y) in enumerate(pairs, 1)]


def test_average_precision_groups_ties_like_scikit_learn_and_is_independent_of_account_ids():
    tied = items([("0.5", 1), ("0.5", 0), ("0.2", 0)])
    assert average_precision(tied, 1)[0] == Fraction(1, 2)
    flipped = items([("0.5", 0), ("0.5", 1), ("0.2", 0)])
    assert average_precision(flipped, 1)[0] == Fraction(1, 2)                                 # a rank-order AP would say 1.0 or 0.5 by account id
    assert average_precision(items([("0.8", 1), ("0.6", 0), ("0.4", 1), ("0.1", 0)]), 2)[0] == Fraction(5, 6)
    assert average_precision(items([("0.9", 0), ("0.1", 0)]), 0) == (None, [])               # no positives: null


def test_calibration_bins_use_exact_fractions_and_close_the_last_bin():
    bins = calibration_bins(items([("0.800000", 1), ("0.000000", 0), ("1.000000", 1), ("0.999999", 0), ("0.100000", 0), ("0.299999", 1)]))
    assert [b["count"] for b in bins] == [1, 1, 1, 0, 0, 0, 0, 0, 1, 2]                      # 0.8 is in bin 8 (not 7); 1.0 in the closed last bin; 0.299999 in bin 2
    assert bins[9]["closed_upper"] is True and bins[9]["mean_predicted"] == "1.000000" and bins[9]["gap_pp"] == "50.00"     # mean .9999995 vs observed .5
    assert bins[3]["gap_pp"] is None and bins[3]["mean_predicted"] is None


def test_economics_rounds_once_at_the_total_half_up_and_labels_itself_hypothetical():
    sc = {"scenario_id": "s", "contact_cost": "5.00", "assumed_effect": "0.100000", "margin_value": "131.75"}
    out = economics(sc, [{"pstr": "0.800000", "account_id": 1}, {"pstr": "0.600000", "account_id": 2}])
    assert [t["value_exact"] for t in out["terms"]] == ["5.540000", "2.905000"] and out["expected_value"] == "8.45" and out["contact_budget"] == "10.00"
    assert out["label"] == "hypothetical" and out["assumption_based"] is True and out["treatment_effect_estimate"] is None


def test_assumed_effect_is_a_share_of_the_risk_not_an_absolute_reduction():
    """p x effect x margin - cost: an account at risk 0.5 with effect 0.2 retains 0.1 of a unit of margin (0.5 x 0.2), not 0.5 - 0.2."""
    sc = {"scenario_id": "s", "contact_cost": "0.00", "assumed_effect": "0.200000", "margin_value": "100.00"}
    assert economics(sc, [{"pstr": "0.500000", "account_id": 1}])["expected_value"] == "10.00"


def test_psi_floors_zero_proportions_and_returns_null_for_an_empty_cohort():
    total, bins = psi([2, 4, 1], [1, 2, 1], ["0", "1-2", "3+"], "0.000100")
    assert str(total.quantize(Decimal("0.000001"))) == "0.074266" and not any(b["floored"] for b in bins)
    total, bins = psi([2, 4, 1], [0, 3, 1], ["0", "1-2", "3+"], "0.000100")
    assert str(total.quantize(Decimal("0.000001"))) == "2.381316" and bins[0]["floored"] and bins[0]["current_proportion"] == "0.000000"
    assert psi([2, 4, 1], [0, 0, 0], ["a", "b", "c"], "0.000100") is None and psi([0, 0], [1, 1], ["a", "b"], "0.000100") is None


def test_bins_are_half_open_and_null_is_in_no_bin():
    b = {"label": "1-2", "lower": 1, "upper": 3}
    assert [in_bin(v, b) for v in (0, 1, 2, "2.99", 3, None)] == [False, True, True, True, False, False]
    assert in_bin(10**6, {"label": "3+", "lower": 3, "upper": None})
