"""Regression tests for review findings. D-08 (A-046): the cutoff rule for assignments, exposures and subscriptions.

A run at a cutoff sees only the facts that existed by it: assignments with assigned_at <= cutoff, exposures with exposed_at <=
cutoff, subscriptions with starts_at <= cutoff (and the plan's revenue window), metric observations with window_end <= cutoff.
Before D-08 an interim run counted rows dated after its cutoff (on the published snapshot at 2026-05-18: assigned_units 400 and
SRM 200/200 although 155 accounts had been assigned). Checked through the domain, the SQL reference and the API.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from productsignal import run_pipeline
from productsignal.contract import ENTITIES, METRIC_KEYS

from support_db import ANALYST, World, client, command, conn, db_url, flat, get, golden_expected, golden_inputs, load  # noqa: F401
from test_sql_reference import assert_equals_domain, reference

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "web" / "public" / "data"
CUT = "2026-10-10T00:00:00Z"            # before the plan's planned_end 2026-10-15: an interim run
LATE_AFTER = "2026-10-11T08:00:00Z"
INTERIM_SNAPSHOT = "2026-05-18T00:00:00Z"


def hand_world() -> World:
    """4 control + 4 treatment accounts, all mature at CUT, all assigned and (but one) exposed before it. Dated AFTER CUT:
    one assignment (acc-late: a ninth account), one exposure (control account acc-c-004, the only unexposed one before) and one
    subscription (acc-c-001, USD 50, inside the revenue window). Before CUT: control 100, treatment 200, and a USD 999
    subscription on the late-assigned account, which is no assigned account at CUT."""
    w = World(cutoff=CUT)
    c = w.arm("control", 4, 2, exposed=3)
    t = w.arm("treatment", 4, 2, start="2026-10-01T11:00:00Z")
    w.sub(c[0], "2026-10-05T00:00:00Z", "100.00")
    w.sub(t[0], "2026-10-06T00:00:00Z", "200.00")
    w.sub(c[0], LATE_AFTER, "50.00")                                                 # after the cutoff
    late = w.account("acc-late")
    w.signup(late, "2026-10-01T10:00:00Z")
    w.assign(late, "treatment", LATE_AFTER)                                          # after the cutoff
    w.sub(late, "2026-10-05T00:00:00Z", "999.00")
    asid = next(a["assignment_id"] for a in w.d["assignments"] if a["unit_id"] == c[3])
    w.expose(asid, LATE_AFTER)                                                       # after the cutoff
    return w


def check_experiment(ex, expect_late: bool):
    n = 9 if expect_late else 8
    assert ex["assigned_units"] == n
    assert ex["srm"]["observed"] == {"control": 4, "treatment": 5 if expect_late else 4}
    by = ex["exposure"]
    if expect_late:
        assert by["by_variant"]["control"]["exposed"] == 4 and by["overall"]["exposed"] == 8
    else:
        assert by["by_variant"]["control"] == {"exposed": 3, "units": 4, "rate": "0.750000"}
        assert by["by_variant"]["treatment"] == {"exposed": 4, "units": 4, "rate": "1.000000"}
        assert by["overall"] == {"exposed": 7, "units": 8, "rate": "0.875000"}
    rev = ex["revenue_per_assigned_account"]["by_variant"]
    if expect_late:
        assert rev["control"]["total"] == "150.00" and rev["control"]["mean"] == "37.50"
        assert rev["treatment"]["total"] == "1199.00"
    else:
        assert rev["control"]["units"] == 4 and rev["control"]["total"] == "100.00" and rev["control"]["mean"] == "25.00"
        assert rev["treatment"]["units"] == 4 and rev["treatment"]["total"] == "200.00" and rev["treatment"]["mean"] == "50.00"


# ------------------------------------------------------------------------------------------------ (a) hand-built input
def test_domain_ignores_rows_dated_after_the_cutoff():
    inputs = hand_world().data()
    check_experiment(run_pipeline(inputs, cutoff=CUT).metrics["experiment"], expect_late=False)
    check_experiment(run_pipeline(inputs, cutoff="2026-10-12T00:00:00Z").metrics["experiment"], expect_late=True)    # later cutoff: they count
    assert run_pipeline(inputs, cutoff=CUT).metrics["experiment"]["run"]["interim"] is True


def test_sql_reference_ignores_rows_dated_after_the_cutoff(conn):
    inputs = hand_world().data()
    load(conn, inputs)
    row = reference(conn, CUT)
    check_experiment(row["experiment"], expect_late=False)
    assert row["experiment"] == run_pipeline(inputs, cutoff=CUT).metrics["experiment"]
    late = reference(conn, "2026-10-12T00:00:00Z")
    check_experiment(late["experiment"], expect_late=True)
    assert late["experiment"] == run_pipeline(inputs, cutoff="2026-10-12T00:00:00Z").metrics["experiment"]


def test_api_metrics_and_commands_ignore_rows_dated_after_the_cutoff(client, conn):
    inputs = hand_world().data()
    load(conn, inputs)
    d = get(client, "/metrics", cutoff=CUT, experiment_version_id="xv-001").json()["data"]
    check_experiment(d["metrics"]["experiment"], expect_late=False)
    assert d["metrics"]["experiment"] == run_pipeline(inputs, cutoff=CUT).metrics["experiment"]
    # C07 check-maturity: the units are those assigned by the cutoff
    r = command(client, "check-maturity", {"experiment_version_id": "xv-001", "cutoff": CUT}, headers=ANALYST)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["assigned_units"] == 8 and res["mature"] == 8 and res["observations_written"] == 8
    # C08 analyze-experiment
    r = command(client, "analyze-experiment", {"experiment_version_id": "xv-001", "cutoff": CUT}, headers=ANALYST)
    assert r.status_code == 200, r.text
    check_experiment(r.json()["result"], expect_late=False)
    # the later cutoff counts them
    d = get(client, "/metrics", cutoff="2026-10-12T00:00:00Z", experiment_version_id="xv-001").json()["data"]
    check_experiment(d["metrics"]["experiment"], expect_late=True)


# ----------------------------------------------------------------------------------------------- (b) published snapshot
def snapshot_inputs() -> dict:
    m = json.loads((SNAPSHOT / "manifest.json").read_text())
    rows = {e: json.loads((SNAPSHOT / f"{e}.json").read_text())["rows"] for e in ENTITIES}
    return {"contract_version": 1, "as_of": m["as_of"], "cutoff": m["cutoff"], "analysis_plan": m["analysis_plans"]["xv-001"],
            "analysis_plans": m["analysis_plans"], "metric_windows": m["metric_windows"], **rows}


def test_snapshot_interim_cutoff_counts_only_the_accounts_assigned_by_then():
    inputs = snapshot_inputs()
    by_cut = [a for a in inputs["assignments"] if a["experiment_version_id"] == "xv-001" and a["assigned_at"] <= INTERIM_SNAPSHOT]
    assert len(by_cut) == 155                                                         # verified from the data
    ex = run_pipeline(inputs, cutoff=INTERIM_SNAPSHOT, experiment_version_id="xv-001").metrics["experiment"]
    observed = {v: sum(1 for a in by_cut if a["variant"] == v) for v in ("control", "treatment")}
    assert ex["assigned_units"] == 155 and ex["srm"]["observed"] == observed == {"control": 77, "treatment": 78}
    assert ex["srm"]["verdict"] == "OK" and ex["srm"]["statistic"] == "0.006452"
    assert ex["run"]["interim"] is True
    # revenue and exposure read only what started / happened by the cutoff
    assert ex["revenue_per_assigned_account"]["by_variant"]["control"]["total"] == "5322.00"
    assert ex["revenue_per_assigned_account"]["by_variant"]["treatment"]["total"] == "5481.00"
    exposed_by = {x["assignment_id"] for x in inputs["exposures"] if x["exposed_at"] <= INTERIM_SNAPSHOT}
    mature_ids = ex["mature_units"]
    assert ex["exposure"]["overall"]["units"] == mature_ids and ex["exposure"]["overall"]["exposed"] <= len(exposed_by)


def test_snapshot_final_cutoff_keeps_all_400():
    inputs = snapshot_inputs()
    for cut in ("2026-08-02T00:00:00Z", inputs["cutoff"]):
        ex = run_pipeline(inputs, cutoff=cut, experiment_version_id="xv-001").metrics["experiment"]
        assert ex["assigned_units"] == 400 and ex["srm"]["observed"] == {"control": 200, "treatment": 200}
        assert ex["exposure"]["overall"] == {"exposed": 349, "units": 400, "rate": "0.872500"}
        assert ex["revenue_per_assigned_account"]["by_variant"]["control"]["mean"] == "97.83"
        assert ex["revenue_per_assigned_account"]["by_variant"]["treatment"]["mean"] == "130.95"


def test_snapshot_sql_and_api_agree_with_the_domain_at_the_interim_cutoff(client, conn):
    inputs = snapshot_inputs()
    m = json.loads((SNAPSHOT / "manifest.json").read_text())
    load(conn, inputs, dataset_version=m["dataset_version"], dataset_hash=m["dataset_hash"])
    res = run_pipeline(inputs, cutoff=INTERIM_SNAPSHOT, experiment_version_id="xv-001")
    row = reference(conn, INTERIM_SNAPSHOT, xv="xv-001")
    assert row["experiment"]["assigned_units"] == 155 and row["experiment"]["srm"]["observed"] == {"control": 77, "treatment": 78}
    for k in METRIC_KEYS:
        assert row[k] == res.metrics[k], k
    d = get(client, "/metrics", cutoff=INTERIM_SNAPSHOT, experiment_version_id="xv-001").json()["data"]
    assert d["metrics"]["experiment"] == res.metrics["experiment"]
    r = command(client, "check-maturity", {"experiment_version_id": "xv-001", "cutoff": INTERIM_SNAPSHOT}, headers=ANALYST)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["assigned_units"] == 155


# ---------------------------------------------------------------------------------------- (c) golden and both variants
@pytest.mark.parametrize("variant", ["", "variant-rejected", "variant-empty"])
def test_golden_and_variants_are_unchanged_key_by_key(variant):
    want, got = flat(golden_expected(variant)), flat(run_pipeline(golden_inputs(variant)).golden())
    assert set(got) == set(want)
    assert [k for k in want if want[k] != got[k]] == []


# =============================================================================================================================
# A-053 / D-10: the second review (A-051), findings R6-01 .. R6-14. Hand values are worked out in the comments.
# =============================================================================================================================
import copy                                             # noqa: E402
from datetime import timedelta                          # noqa: E402

import psycopg                                          # noqa: E402
from psycopg.rows import dict_row                       # noqa: E402

from productsignal.errors import DomainError, VARIANTS_NOT_TWO          # noqa: E402
from productsignal.metrics import segment_analysis      # noqa: E402
from productsignal.models import parse_plan, plan_hash   # noqa: E402
from productsignal.pipeline import run_pipeline as pipeline   # noqa: E402

from support_db import ADMIN, EXPERIMENTER, PLAN_BODY, Lab, count, iso, plan_input, rule_ids, set_clock, small_experiment, ts  # noqa: E402,F401


def exp_block(w_or_inputs, cutoff=None, **kw):
    d = w_or_inputs.data() if hasattr(w_or_inputs, "data") else w_or_inputs
    return pipeline(d, cutoff=cutoff, **kw).metrics["experiment"]


def logged(w: World) -> World:
    """The final run logged five minutes after the cutoff (D-10: `conclusive` needs a plan frozen before the first logged run)."""
    w.run(w.cutoff, iso(ts(w.cutoff) + timedelta(minutes=5)))
    return w


def world_I() -> World:
    """I_frozen_late: the plan is frozen 2026-10-20, AFTER the first logged run (2026-10-10) read outcomes; control 10/100, treatment 40/100."""
    body = copy.deepcopy(PLAN_BODY)
    body["frozen_at"] = "2026-10-20T00:00:00Z"
    w = World(cutoff="2026-10-26T00:00:00Z", plan=body)
    w.arm("control", 100, 10)
    w.arm("treatment", 100, 40, start="2026-10-01T11:00:00Z")
    w.run("2026-10-10T00:00:00Z", "2026-10-10T00:05:00Z")
    w.run("2026-10-26T00:00:00Z", "2026-10-26T00:05:00Z")
    return w


def world_L() -> World:
    """L_equal: control 0/2, treatment 2/2, every account USD 10.00; no run logged. The interval excludes 0 (Newcombe low
    1 - sqrt((1-0.342)^2 + 0.658^2) = +0.07), the cutoff is after planned_end, the hash is valid; the expected cells are 2 (< 5)."""
    w = World(cutoff="2026-10-26T00:00:00Z")
    c = w.arm("control", 2, 0)
    t = w.arm("treatment", 2, 2, start="2026-10-01T11:00:00Z")
    for a in c + t:
        w.sub(a, "2026-10-05T00:00:00Z", "10.00")
    return w


def world_H() -> World:
    """H_three: 100 / 33 / 67 against 0.5 / 0.25 / 0.25 (df 2 would give p = exp(-5.78) = 0.003088; the df = 1 p is 0.000674)."""
    body = copy.deepcopy(PLAN_BODY)
    body["allocation"] = {"control": "0.500000", "treatment": "0.250000", "holdout": "0.250000"}
    w = World(cutoff="2026-10-26T00:00:00Z", plan=body)
    w.arm("control", 100, 20)
    w.arm("treatment", 33, 10, start="2026-10-01T11:00:00Z")
    w.arm("holdout", 67, 10, prefix="h", start="2026-10-01T13:00:00Z")
    return w


def world_J() -> World:
    """J_pre_treatment: ten accounts activate 30 minutes after signing up on 2026-10-01 and are assigned on 2026-10-20."""
    w = World(cutoff="2026-10-26T00:00:00Z")
    for i in range(10):
        a = w.account(f"acc-pre-{i}")
        w.signup(a, f"2026-10-01T0{i}:00:00Z")
        w.activate(a, f"2026-10-01T0{i}:30:00Z")
        w.assign(a, "treatment" if i % 2 else "control", "2026-10-20T00:00:00Z")
    return w


def world_K() -> World:
    """K_dst_sql: the activation window crosses the 2026-11-01 end of US daylight time. k1 signs up 2026-10-31T12:00Z and activates
    168.5 h later (11-07T12:30Z): outside the 168-h window. k2 signs up 11-01T00:30Z: 168 h later is 11-08T00:30Z, after the cutoff."""
    w = World(cutoff="2026-11-08T00:00:00Z")
    w.d["metric_windows"]["activation"] = {"from": "2026-10-25T00:00:00Z", "to": "2026-11-08T00:00:00Z", "window_days": 7}
    w.account("k1"); w.signup("k1", "2026-10-31T12:00:00Z"); w.activate("k1", "2026-11-07T12:30:00Z")
    w.account("k2"); w.signup("k2", "2026-11-01T00:30:00Z")
    return w


def world_B() -> World:
    """B_maturity: m1 activates exactly 7 days after signing up (outside [signup, +7 d)), m2 is immature by one second, m3 activates
    one second before the end of its window."""
    w = World(cutoff="2026-10-26T00:00:00Z")
    for a in ("acc-m1", "acc-m2", "acc-m3"):
        w.account(a)
    w.signup("acc-m1", "2026-10-19T00:00:00Z"); w.activate("acc-m1", "2026-10-26T00:00:00Z", recv="2026-10-26T00:00:00Z")
    w.signup("acc-m2", "2026-10-19T00:00:01Z"); w.activate("acc-m2", "2026-10-19T01:00:00Z")
    w.signup("acc-m3", "2026-10-19T00:00:00Z"); w.activate("acc-m3", "2026-10-25T23:59:59Z", recv="2026-10-26T00:00:00Z")
    return w


# ------------------------------------------------------------------------------------------- R6-01 / R6-14 conclusive
def test_R6_01_conclusive_needs_a_plan_frozen_before_the_first_run():
    ex = exp_block(world_I(), "2026-10-26T00:00:00Z")
    p = ex["primary"]
    assert (p["variants"]["control"]["activated"], p["variants"]["treatment"]["activated"], p["absolute_lift_pp"]) == (10, 40, "30.00")
    assert p["interval"]["includes_zero"] is False and ex["run"]["interim"] is False and ex["srm"]["verdict"] == "OK"
    assert ex["run"]["plan_frozen"] is False and ex["run"]["config_hash_matches_plan"] is True
    assert p["conclusive"] is False                                                  # before D-10: True
    w = world_I()
    w.d["analysis_plan"] = {**w.d["analysis_plan"], "frozen_at": "2026-10-05T00:00:00Z"}
    w.d["analysis_plan"]["config_hash"] = plan_hash({k: v for k, v in w.d["analysis_plan"].items() if k != "config_hash"})
    ok = exp_block(w, "2026-10-26T00:00:00Z")
    assert ok["run"]["plan_frozen"] is True and ok["primary"]["conclusive"] is True        # frozen before the first run: conclusive


def test_R6_01_no_logged_run_is_a_preview_not_a_conclusive_result():
    ex = exp_block(world_L(), "2026-10-26T00:00:00Z")
    assert ex["primary"]["interval"]["includes_zero"] is False and ex["run"]["interim"] is False
    assert ex["run"]["plan_frozen"] is False and ex["primary"]["conclusive"] is False       # L_equal: True before D-10
    big = exp_block(small_experiment((100, 20), (100, 40)), "2026-10-26T00:00:00Z")
    assert big["primary"]["interval"]["includes_zero"] is False and big["primary"]["conclusive"] is False   # no run logged
    assert exp_block(logged(small_experiment((100, 20), (100, 40))), "2026-10-26T00:00:00Z")["primary"]["conclusive"] is True


def test_R6_14_conclusive_needs_the_sample_ratio_to_be_ok():
    body = copy.deepcopy(PLAN_BODY)
    body["allocation"] = {"control": "0.700000", "treatment": "0.300000"}
    w = logged(small_experiment((100, 20), (100, 40), plan=body))                       # 100 / 100 against 0.7 / 0.3: chi-square 38.095238
    ex = exp_block(w, "2026-10-26T00:00:00Z")
    assert ex["srm"]["verdict"] == "MISMATCH" and ex["srm"]["statistic"] == "38.095238"
    assert ex["primary"]["interval"]["includes_zero"] is False and ex["run"]["plan_frozen"] is True
    assert ex["primary"]["conclusive"] is False
    tiny = exp_block(logged(small_experiment((3, 0), (3, 3))), "2026-10-26T00:00:00Z")      # expected cells 3 < 5
    assert tiny["srm"]["verdict"] == "INSUFFICIENT" and tiny["primary"]["conclusive"] is False


# ------------------------------------------------------------------------------------------------------ R6-02 two arms
@pytest.mark.parametrize("alloc", [{"control": "0.500000", "treatment": "0.250000", "holdout": "0.250000"},
                                   {"a": "0.5", "b": "0.5"}, {"control": "1.0"}, {"treatment": "0.5", "holdout": "0.5"}])
def test_R6_02_a_plan_without_exactly_control_and_treatment_is_refused(alloc):
    body = {**PLAN_BODY, "allocation": alloc}
    with pytest.raises(DomainError) as e:
        parse_plan(body, plan_hash(body))
    assert e.value.code == VARIANTS_NOT_TWO and e.value.path == "allocation"
    with pytest.raises(DomainError) as e2:
        pipeline({**World().data(), "analysis_plan": {**body, "config_hash": plan_hash(body)}})
    assert e2.value.code == VARIANTS_NOT_TWO


def test_R6_02_three_variant_inputs_are_a_rejection_everywhere_and_two_variants_keep_df_1():
    with pytest.raises(DomainError) as e:
        pipeline(world_H().data())                                   # H_three: the reviewer's case
    assert e.value.code == VARIANTS_NOT_TWO
    srm = exp_block(small_experiment((100, 20), (100, 40)), "2026-10-26T00:00:00Z")["srm"]
    assert srm["df"] == 1


def test_R6_02_sql_side_the_seed_refuses_the_three_variant_plan(conn):
    with pytest.raises(DomainError) as e:
        load(conn, world_H().data())
    assert e.value.code == VARIANTS_NOT_TWO and count(conn, "analysis_plans") == 0


# --------------------------------------------------------------------------------------- R6-09 outcomes before assignment
def test_R6_09_an_activation_before_the_assignment_is_not_a_treatment_outcome():
    ex = exp_block(world_J(), "2026-10-26T00:00:00Z")
    v = ex["primary"]["variants"]
    assert (v["control"]["mature_units"], v["treatment"]["mature_units"]) == (5, 5)
    assert (v["control"]["activated"], v["treatment"]["activated"]) == (0, 0)             # hand: every activation (10-01) precedes the assignment (10-20)
    assert ex["primary"]["absolute_lift_pp"] == "0.00" and ex["primary"]["relative_lift"] is None
    assert ex["exploratory_exposed_only"]["by_variant"]["treatment"]["activated"] == 0
    # the cohort metric is not an experiment: it still sees ten activations
    assert pipeline(world_J().data(), cutoff="2026-10-26T00:00:00Z").metrics["activation"]["activated"] == 10


def test_R6_09_the_rule_at_its_edges():
    """Activations at / after assigned_at and inside [signup, signup + 7 d) count; before assigned_at, or at +7 d, do not."""
    w = World(cutoff="2026-10-26T00:00:00Z")
    rows = {"at": "2026-10-02T10:00:00Z", "after": "2026-10-02T10:00:01Z", "before": "2026-10-02T09:59:59Z", "late": "2026-10-09T00:00:00Z",
            "last": "2026-10-08T23:59:59Z"}            # signup 10-02T00:00:00Z, assigned 10-02T10:00:00Z, window ends 10-09T00:00:00Z
    for i, (k, when) in enumerate(rows.items()):
        a = w.account(f"acc-{k}")
        w.signup(a, "2026-10-02T00:00:00Z")
        w.assign(a, "control" if i % 2 else "treatment", "2026-10-02T10:00:00Z")
        w.activate(a, when)
    w.account("acc-two"); w.signup("acc-two", "2026-10-02T00:00:00Z"); w.assign("acc-two", "control", "2026-10-02T10:00:00Z")
    w.activate("acc-two", "2026-10-02T01:00:00Z"); w.activate("acc-two", "2026-10-03T00:00:00Z")      # one before, one after: counts once
    ex = exp_block(w, "2026-10-26T00:00:00Z")
    counted = {a for a in ("at", "after", "last", "two")}
    got = {}
    for v in ("control", "treatment"):
        got[v] = ex["primary"]["variants"][v]["activated"]
    assert got["treatment"] + got["control"] == 4 and ex["mature_units"] == 6
    # one by one: the same unit alone
    for k, expect in (("at", 1), ("after", 1), ("before", 0), ("late", 0), ("last", 1), ("two", 1)):
        d = w.data()
        d["assignments"] = [a for a in d["assignments"] if a["unit_id"] == f"acc-{k}"]
        d["exposures"] = []
        r = pipeline(d, cutoff="2026-10-26T00:00:00Z").metrics["experiment"]
        assert sum(x["activated"] for x in r["primary"]["variants"].values()) == expect, k
    assert counted == {"at", "after", "last", "two"}


def test_R6_09_the_guardrail_is_eligible_only_when_its_window_is_complete():
    w = world_J()
    for i in range(10):
        w.event("product_error", f"2026-10-21T0{i}:00:00Z", user=f"u-acc-pre-{i}")
    g = exp_block(w, "2026-10-26T00:00:00Z")["guardrail"]["by_variant"]                      # assigned 10-20 + 7 d = 10-27 > 10-26
    assert g["control"] == {"eligible_units": 0, "units_with_error": 0, "error_rate": None}
    assert g["treatment"] == {"eligible_units": 0, "units_with_error": 0, "error_rate": None}
    w.d["cutoff"] = w.d["as_of"] = "2026-10-27T00:00:00Z"
    g = exp_block(w, "2026-10-27T00:00:00Z")["guardrail"]["by_variant"]                      # window complete at 10-27T00:00 (<=)
    assert g["control"] == {"eligible_units": 5, "units_with_error": 5, "error_rate": "1.000000"}
    assert pipeline(w.data(), cutoff="2026-10-26T23:59:59Z").metrics["experiment"]["guardrail"]["by_variant"]["control"]["eligible_units"] == 0


def test_R6_09_observations_and_segments_use_the_same_rule(client, conn):
    L = Lab(client, conn, world=world_J())
    r = command(client, "check-maturity", {"experiment_version_id": "xv-001", "cutoff": "2026-10-26T00:00:00Z"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["result"]["observations_written"] == 10
    vals = {x["value"] for x in conn.execute("SELECT value FROM metric_observations").fetchall()}
    assert vals == {"0"}                                                                      # not "1": the activations precede the assignments
    ex = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z", experiment_version_id="xv-001").json()["data"]["metrics"]["experiment"]
    assert ex["observations"] == {"rows_accepted": 10, "rows_matching_events": 10}
    d = pipeline(world_J().data(), cutoff="2026-10-26T00:00:00Z")
    seg = segment_analysis(d.population, ts("2026-10-26T00:00:00Z"), d.population.plans["xv-001"], "plan")
    assert all(s["variants"][v]["activated"] == 0 for s in seg["segments"] for v in ("control", "treatment"))


# ----------------------------------------------------------------------------------------------------- R6-13 Bonferroni
def test_R6_13_the_bonferroni_family_can_span_every_split_offered():
    w = small_experiment((40, 8), (40, 18))
    for i, a in enumerate(w.d["accounts"]):
        a["segment"] = ["smb", "mid", "enterprise"][i % 3]
    d = pipeline(w.data(), cutoff="2026-10-26T00:00:00Z")
    plan, cut = d.population.plans["xv-001"], ts("2026-10-26T00:00:00Z")
    one = segment_analysis(d.population, cut, plan, "segment")
    assert one["segments_tested"] == 3 and one["bonferroni_threshold"] == "0.016667" and "family_size" not in one       # unchanged default
    fam = segment_analysis(d.population, cut, plan, "segment", family=7)
    assert fam["segments_tested"] == 3 and fam["family_size"] == 7 and fam["bonferroni_threshold"] == "0.007143"        # 0.05 / 7
    assert fam["segments"][0]["adjusted_interval"]["confidence"] == "0.992857"


# ------------------------------------------------------------------------------------- R6-03 SQL independent of the session zone
ZONES = ("UTC", "America/New_York", "Europe/London", "Pacific/Kiritimati", "America/St_Johns")


def sql_in_zone(url, tz, cutoff, **kw):
    with psycopg.connect(url, row_factory=dict_row, autocommit=True, options=f"-c timezone={tz}") as c:
        return reference(c, cutoff, **kw)


@pytest.mark.parametrize("name,maker,hand", [
    ("K_dst_sql", world_K, {"signups": 2, "immature_excluded": 1, "mature_accounts": 1, "activated": 0, "rate": "0.000000"}),
    ("B_maturity", world_B, {"signups": 3, "immature_excluded": 1, "mature_accounts": 2, "activated": 1, "rate": "0.500000"})])
def test_R6_03_the_sql_reference_gives_the_same_answer_in_every_session_time_zone(db_url, conn, name, maker, hand):
    w = maker()
    load(conn, w.data())
    domain = pipeline(w.data()).metrics
    a = domain["activation"]
    assert {k: a[k] for k in hand} == hand                                                    # the hand values, from the domain
    for tz in ZONES:
        row = sql_in_zone(db_url, tz, w.cutoff)
        assert {k: row["activation"][k] for k in hand} == hand, (name, tz)
        for k in METRIC_KEYS:
            assert row[k] == domain[k], (name, tz, k)


def test_R6_03_the_hour_based_intervals_also_hold_for_the_experiment_block(db_url, conn):
    """Maturity of an assigned account across the DST end: signup 2026-10-31T12:00Z, cutoff 2026-11-07T12:00Z is exactly +168 h."""
    w = World(cutoff="2026-11-07T12:00:00Z", planned_end="2026-11-01T00:00:00Z")
    w.d["experiment_versions"][0]["planned_end"] = "2026-11-01T00:00:00Z"
    w.d["metric_windows"]["activation"] = {"from": "2026-10-25T00:00:00Z", "to": "2026-11-08T00:00:00Z", "window_days": 7}
    c = w.account("e1"); w.signup(c, "2026-10-31T12:00:00Z"); w.assign(c, "control", "2026-10-31T12:01:00Z"); w.activate(c, "2026-11-07T11:59:00Z")
    t = w.account("e2"); w.signup(t, "2026-10-31T12:00:01Z"); w.assign(t, "treatment", "2026-10-31T12:02:00Z")
    load(conn, w.data())
    domain = pipeline(w.data()).metrics
    assert domain["experiment"]["mature_units"] == 1 and domain["experiment"]["primary"]["variants"]["control"]["activated"] == 1
    for tz in ZONES:
        assert sql_in_zone(db_url, tz, w.cutoff)["experiment"] == domain["experiment"], tz


# --------------------------------------------------------------------------- SQL, domain agree on the D-10 rules (I, J, L, K, B)
@pytest.mark.parametrize("maker", [world_I, world_J, world_L, world_K, world_B], ids=lambda m: m.__name__)
def test_the_sql_reference_equals_the_domain_on_the_review_cases(conn, maker):
    w = maker()
    load(conn, w.data())
    res = pipeline(w.data())
    assert_equals_domain(reference(conn, w.cutoff), res)
    if maker is world_I:
        assert reference(conn, w.cutoff)["experiment"]["primary"]["conclusive"] is False
    if maker is world_J:
        assert reference(conn, w.cutoff)["experiment"]["primary"]["variants"]["treatment"]["activated"] == 0


# ==================================================================================================== the API (R6-04 .. R6-09)
def _analysis_runs(conn):
    return conn.execute("SELECT analysis_id, cutoff_at, created_at FROM analysis_runs WHERE created_by <> 'seed'").fetchall()


def _refusals(conn):
    return [r["details"]["rule_id"] for r in conn.execute(
        "SELECT details FROM audit_events WHERE action = 'record-decision-refused' ORDER BY occurred_at, event_id").fetchall()]


def test_R6_04_a_cutoff_after_the_api_clock_is_refused(client, conn):
    L = Lab(client, conn, world=small_experiment((20, 4), (20, 10)))               # the clock says 2026-10-26T22:00Z
    for cutoff in ("2026-10-26T22:00:01Z", "2026-10-27T00:00:00Z", "2027-01-01T00:00:00Z"):
        r = L.analyze(cutoff)
        assert r.status_code == 422 and rule_ids(r) == ["CUTOFF_IN_FUTURE"], cutoff
        r = L.post("check-maturity", {"experiment_version_id": "xv-001", "cutoff": cutoff}, ANALYST)
        assert r.status_code == 422 and rule_ids(r) == ["CUTOFF_IN_FUTURE"], cutoff
        g = get(client, "/metrics", cutoff=cutoff, experiment_version_id="xv-001")
        assert g.status_code == 422 and g.json()["error"]["details"][0]["rule_id"] == "CUTOFF_IN_FUTURE", cutoff
    assert _analysis_runs(conn) == [] and count(conn, "metric_observations") == 0          # nothing was written
    ok = L.analyze("2026-10-26T22:00:00Z")                                                 # the clock's own second is not the future
    assert ok.status_code == 200
    assert L.analyze().status_code == 200                                                  # the default cutoff is the clock
    assert get(client, "/metrics", experiment_version_id="xv-001").status_code == 200
    runs = _analysis_runs(conn)
    assert len(runs) == 2 and all(r["created_at"] >= r["cutoff_at"] for r in runs)        # a run's created_at never precedes its cutoff


def test_R6_05_facts_are_stamped_with_the_server_clock_and_only_an_admin_may_backfill(client, conn):
    w = World()
    for a in ("acc-a", "acc-b", "acc-c", "acc-d"):
        w.account(a)
    L = Lab(client, conn, world=w, facts=False)
    xv = {"experiment_version_id": "xv-001", "variant": "control"}
    def near_clock(value):                                                            # stamped with the (stepping) fixed clock
        return timedelta(0) <= ts(value[:19] + "Z") - ts("2026-10-26T22:00:00Z") < timedelta(seconds=2)
    r = L.post("assign-experiment", {**xv, "unit_id": "acc-a"})
    assert r.status_code == 200 and near_clock(r.json()["result"]["assigned_at"])
    asid = r.json()["result"]["assignment_id"]
    r = L.post("record-exposure", {"assignment_id": asid, "surface": "s"})
    assert r.status_code == 200 and near_clock(r.json()["result"]["exposed_at"])
    # a client-stated instant: not for an experimenter, not for an admin without the flag, not in the future, not a flag without an instant
    for who, body, status, rule in ((EXPERIMENTER, {"assigned_at": "2026-10-01T00:00:00Z"}, 403, "BACKFILL_ADMIN_ONLY"),
                                    (EXPERIMENTER, {"assigned_at": "2026-10-01T00:00:00Z", "backfill": True}, 403, "BACKFILL_ADMIN_ONLY"),
                                    (EXPERIMENTER, {"backfill": True}, 403, "BACKFILL_ADMIN_ONLY"),
                                    (ADMIN, {"assigned_at": "2026-10-01T00:00:00Z"}, 422, "BACKFILL_FLAG_REQUIRED"),
                                    (ADMIN, {"backfill": True}, 422, "BACKFILL_FLAG_REQUIRED"),
                                    (ADMIN, {"assigned_at": "2026-12-01T00:00:00Z", "backfill": True}, 422, "ASSIGNED_AT_IN_FUTURE")):
        r = L.post("assign-experiment", {**xv, "unit_id": "acc-b", **body}, who)
        assert (r.status_code, rule_ids(r)) == (status, [rule]), body
    assert count(conn, "assignments") == 1
    for who, body, status, rule in ((EXPERIMENTER, {"exposed_at": "2026-10-02T00:00:00Z"}, 403, "BACKFILL_ADMIN_ONLY"),
                                    (ADMIN, {"exposed_at": "2026-10-02T00:00:00Z"}, 422, "BACKFILL_FLAG_REQUIRED"),
                                    (ADMIN, {"exposed_at": "2026-12-01T00:00:00Z", "backfill": True}, 422, "EXPOSED_AT_IN_FUTURE")):
        r = L.post("record-exposure", {"assignment_id": asid, "surface": "s", **body}, who)
        assert (r.status_code, rule_ids(r)) == (status, [rule]), body
    # the admin backfill is accepted and audited
    r = L.post("assign-experiment", {**xv, "unit_id": "acc-c", "assigned_at": "2026-10-01T09:00:00Z", "backfill": True}, ADMIN)
    assert r.status_code == 200 and r.json()["result"]["assigned_at"] == "2026-10-01T09:00:00Z"
    audit = conn.execute("SELECT details FROM audit_events WHERE action = 'assign-experiment' ORDER BY occurred_at, event_id").fetchall()
    assert [a["details"]["backfill"] for a in audit] == [False, True] and audit[1]["details"]["assigned_at"] == "2026-10-01T09:00:00Z"


def test_R6_05_events_cannot_be_in_the_future_or_received_before_they_happened(client, conn):
    L = Lab(client, conn, world=small_experiment((5, 1), (5, 1)), facts=False)
    ev = lambda eid, at, **kw: {"event_id": eid, "user_id": "u-acc-c-001", "anonymous_id": None, "event_name": "visit", "event_at": at, **kw}
    r = L.post("validate-tracking", {"events": [ev("ok-1", "2026-10-26T21:59:59Z"), ev("fut-1", "2026-12-01T00:00:00Z")]}, ANALYST)
    assert r.status_code == 200 and r.json()["status"] == "partial" and r.json()["result"]["accepted"] == 1
    assert [x["reason_code"] for x in r.json()["result"]["rejected_records"]] == ["EVENT_IN_FUTURE"]
    assert count(conn, "events", "event_id = 'fut-1'") == 0 and count(conn, "rejected_records", "reason_code = 'EVENT_IN_FUTURE'") == 1
    r = L.post("validate-tracking", {"events": [ev("fut-2", "2026-12-01T00:00:00Z")]}, ANALYST)
    assert r.status_code == 422 and "EVENT_IN_FUTURE" in rule_ids(r)
    r = L.post("validate-tracking", {"events": [ev("early-1", "2026-10-02T10:00:00Z", received_at="2026-10-02T09:00:00Z")]}, ADMIN)
    assert r.status_code == 422 and rule_ids(r) == ["RECEIVED_BEFORE_EVENT"] and count(conn, "events", "event_id = 'early-1'") == 0
    ok = L.post("validate-tracking", {"events": [ev("late-1", "2026-10-02T10:00:00Z", received_at="2026-10-02T10:00:00Z")]}, ADMIN)    # equal: fine
    assert ok.status_code == 200
    audit = conn.execute("SELECT details FROM audit_events WHERE action = 'validate-tracking' ORDER BY occurred_at DESC, event_id LIMIT 1").fetchone()
    assert audit["details"]["received_at_backfilled"] == 1


def test_R6_05_a_second_run_at_the_same_cutoff_gives_the_same_answer(client, conn):
    L = Lab(client, conn, world=small_experiment((20, 4), (20, 10)))
    first = L.analyze("2026-10-26T00:00:00Z").json()["result"]
    conn.execute("INSERT INTO accounts VALUES ('acc-new', 'team', 'smb', now(), false, 'UTC')")
    new = L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-new", "variant": "treatment"})
    assert new.status_code == 200 and ts(new.json()["result"]["assigned_at"][:19] + "Z") > ts("2026-10-26T00:00:00Z")   # stamped now, not at the cutoff
    # backfilling it into the published run is refused (at or before the latest cutoff), so the run cannot change
    conn.execute("INSERT INTO accounts VALUES ('acc-new2', 'team', 'smb', now(), false, 'UTC')")
    for at in ("2026-10-01T00:00:00Z", "2026-10-26T00:00:00Z"):
        r = L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-new2", "variant": "control", "assigned_at": at, "backfill": True}, ADMIN)
        assert r.status_code == 422 and rule_ids(r) == ["ASSIGNMENT_BEFORE_PUBLISHED_RUN"], at
    exp = L.post("record-exposure", {"assignment_id": new.json()["result"]["assignment_id"], "surface": "s"})
    assert exp.status_code == 200
    again = L.analyze("2026-10-26T00:00:00Z").json()["result"]
    same = ("assigned_units", "mature_units", "srm", "primary", "exposure", "guardrail", "revenue_per_assigned_account")
    assert {k: again[k] for k in same} == {k: first[k] for k in same}
    assert first["assigned_units"] == 40 and again["run"]["prior_runs"] == 1


def test_R6_06_per_arm_outcomes_are_withheld_until_the_plan_is_frozen_and_a_freeze_cannot_be_backdated(client, conn):
    w = World(planned_end="2026-11-15T00:00:00Z")
    c = w.arm("control", 20, 4)
    w.arm("treatment", 20, 10, start="2026-10-01T11:00:00Z")
    L = Lab(client, conn, world=w, plan=False)
    g = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z", experiment_version_id="xv-001", group_by="variant")
    assert g.status_code == 409 and g.json()["error"]["code"] == "PLAN_NOT_FROZEN"
    assert "groups" not in g.text and "activated" not in g.text                                   # no per-arm outcome in the refusal
    plain = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z", experiment_version_id="xv-001")
    assert plain.status_code == 200 and plain.json()["data"]["metrics"]["experiment"] is None      # the experiment block is absent, as before
    assert get(client, "/metrics", cutoff="2026-10-26T00:00:00Z", group_by="variant").status_code == 422   # no version named: still a 422
    # something is recorded for the version (an assignment), then a plan dated before it is refused
    conn.execute("INSERT INTO accounts VALUES ('acc-new', 'team', 'smb', now(), false, 'UTC')")
    assert L.post("assign-experiment", {"experiment_version_id": "xv-001", "unit_id": "acc-new", "variant": "control"}).status_code == 200
    body = plan_input(w.d["analysis_plan"])
    for at in ("2026-09-01T00:00:00Z", "2026-10-26T21:59:59Z"):
        r = L.post("freeze-analysis-plan", {**body, "frozen_at": at})
        assert r.status_code == 422 and rule_ids(r) == ["FROZEN_AT_BACKDATED"], at
    assert count(conn, "analysis_plans") == 0
    set_clock("2026-10-27T10:00:00Z")
    assert rule_ids(L.post("freeze-analysis-plan", {**body, "frozen_at": "2026-10-27T11:00:00Z"})) == ["FROZEN_AT_IN_FUTURE"]
    ok = L.post("freeze-analysis-plan", {**body, "frozen_at": "2026-10-27T09:00:00Z"})             # after the audit row, not after the clock
    assert ok.status_code == 200
    g = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z", experiment_version_id="xv-001", group_by="variant")
    assert g.status_code == 200 and g.json()["data"]["groups"]["control"]["accounts"] == 20


def test_R6_07_every_refused_decision_leaves_an_audit_row(client, conn):
    w = small_experiment((50, 10), (50, 25))
    for i in range(12):
        w.event("product_error", f"2026-10-02T0{i % 10}:3{i // 10}:00Z", user=f"u-acc-t-{i + 1:03d}")
    L = Lab(client, conn, world=w)
    a = L.analyze("2026-10-26T00:00:00Z").json()["result"]["analysis_id"]
    ra = L.review(a).json()["result"]["review_id"]                                              # HARMFUL
    b = L.analyze("2026-10-25T00:00:00Z", exclusions=[{"field": "plan", "values": ["free"]}]).json()["result"]["analysis_id"]
    rb = L.review(b).json()["result"]["review_id"]
    d = L.analyze("2026-10-24T00:00:00Z").json()["result"]["analysis_id"]
    rd = L.review(d).json()["result"]["review_id"]
    steps = [("SEGMENT_NOT_A_DECISION_BASIS", 422, lambda: L.decide(a, ra, "ship", basis="segment")),
             ("REVIEW_MISMATCH", 422, lambda: L.decide(a, rb, "ship")),
             ("GUARDRAIL_HARM_BLOCKS_SHIP", 409, lambda: L.decide(a, ra, "ship")),
             ("PLAN_DEVIATION_BLOCKS_SHIP", 409, lambda: L.decide(b, rb, "ship"))]
    seen = []
    for rule, status, call in steps:
        before = len(_refusals(conn))
        r = call()
        assert r.status_code == status, (rule, r.text)
        seen.append(rule)
        assert _refusals(conn) == seen and len(_refusals(conn)) == before + 1, rule              # exactly one new audit row, with its rule
    assert count(conn, "decisions") == 0
    assert L.decide(a, ra, "stop").status_code == 200                                            # an honest decision is not a refusal
    r = L.decide(a, ra, "stop")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DECISION_ALREADY_RECORDED"
    seen.append("DECISION_ALREADY_RECORDED")
    assert _refusals(conn) == seen
    conn.execute("ALTER TABLE analysis_plans DISABLE TRIGGER USER")
    conn.execute("UPDATE analysis_plans SET plan = jsonb_set(plan, '{z}', '\"1.644854\"')")       # the plan changed after its hash was taken
    conn.execute("ALTER TABLE analysis_plans ENABLE TRIGGER USER")
    r = L.decide(d, rd, "ship")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PLAN_HASH_INVALID_BLOCKS_SHIP"
    seen.append("PLAN_HASH_INVALID_BLOCKS_SHIP")
    assert _refusals(conn) == seen
    row = conn.execute("SELECT actor_id, reason, details, experiment_version_id FROM audit_events WHERE action = 'record-decision-refused' "
                       "ORDER BY occurred_at DESC, event_id LIMIT 1").fetchone()
    assert row["actor_id"] == "usr-exp01" and row["details"]["actor_role"] == "experimenter" and row["experiment_version_id"] == "xv-001" and row["reason"]


def test_R6_05_a_decision_is_stamped_with_the_server_clock_and_an_admin_may_backfill_it(client, conn):
    L = Lab(client, conn, world=small_experiment((100, 20), (100, 40)))
    a1, r1 = L.final()
    a2 = L.analyze("2026-10-25T00:00:00Z").json()["result"]["analysis_id"]
    r2 = L.review(a2).json()["result"]["review_id"]
    r = L.decide(a1, r1, "ship", decided_at="2026-01-01T00:00:00Z")
    assert r.status_code == 403 and rule_ids(r) == ["BACKFILL_ADMIN_ONLY"] and count(conn, "decisions") == 0
    r = L.decide(a1, r1, "ship", who=ADMIN, decided_at="2026-10-26T21:00:00Z", backfill=True)       # before the run was logged
    assert r.status_code == 422 and rule_ids(r) == ["DECIDED_BEFORE_RUN"] and count(conn, "decisions") == 0
    assert rule_ids(L.decide(a1, r1, "ship", who=ADMIN, decided_at="2026-10-26T22:30:00Z")) == ["BACKFILL_FLAG_REQUIRED"]
    ok = L.decide(a1, r1, "ship")                                                                    # stamped by the server
    stamped = conn.execute("SELECT decided_at FROM decisions").fetchone()["decided_at"]
    assert ok.status_code == 200 and timedelta(0) <= stamped - ts("2026-10-26T22:00:00Z") < timedelta(seconds=5)
    set_clock("2026-10-26T23:00:00Z")
    r = L.decide(a2, r2, "stop", who=ADMIN, decided_at="2026-10-26T22:30:00Z", backfill=True)        # an admin backfill after the run, before now
    assert r.status_code == 200 and r.json()["result"]["decided_at"] == "2026-10-26T22:30:00Z"
    last = conn.execute("SELECT details FROM audit_events WHERE action = 'record-decision' ORDER BY occurred_at DESC, event_id LIMIT 1").fetchone()
    assert last["details"]["backfill"] is True and last["details"]["decided_at"] == "2026-10-26T22:30:00Z"


def test_R6_09_an_account_that_already_has_the_outcome_cannot_be_assigned(client, conn):
    w = World()
    x = w.account("acc-x"); w.signup(x, "2026-10-01T09:00:00Z"); w.activate(x, "2026-10-01T10:00:00Z")
    y = w.account("acc-y"); w.signup(y, "2026-10-01T09:00:00Z")
    z = w.account("acc-z"); w.signup(z, "2026-10-01T09:00:00Z")
    w.link("anon-z", f"u-{z}", "2026-10-01T09:00:00Z")
    w.event("activated", "2026-10-01T11:00:00Z", anon="anon-z")                 # an anonymous activation linked to the account counts too
    L = Lab(client, conn, world=w)
    body = {"experiment_version_id": "xv-001", "variant": "control"}
    r = L.post("assign-experiment", {**body, "unit_id": "acc-x"})
    assert r.status_code == 422 and rule_ids(r) == ["OUTCOME_BEFORE_ASSIGNMENT"]
    assert r.json()["error"]["details"][0]["context"] == {"first_activated_at": "2026-10-01T10:00:00Z"}
    assert L.post("assign-experiment", {**body, "unit_id": "acc-z"}).status_code == 422
    assert count(conn, "assignments") == 0
    assert L.post("assign-experiment", {**body, "unit_id": "acc-y"}).status_code == 200            # no outcome yet: assignable
    ok = L.post("assign-experiment", {**body, "unit_id": "acc-x", "assigned_at": "2026-10-01T09:30:00Z", "backfill": True}, ADMIN)
    assert ok.status_code == 200 and count(conn, "assignments") == 2                                # an explicit admin backfill is allowed (audited)
    assert L.post("assign-experiment", {**body, "unit_id": "acc-x"}).json()["status"] == "already_assigned"   # an existing assignment is idempotent


# ------------------------------------------------------------------------------- R6-10 secondary differences (site figures)
from productsignal.metrics import Ctx, revenue_difference, week4_difference   # noqa: E402
from productsignal.events import canonicalise                                   # noqa: E402


def _ctx(w: World, cutoff: str):
    d = pipeline(w.data(), cutoff=cutoff)
    cut = ts(cutoff)
    return Ctx(d.population, cut, canonicalise(d.population, cut), None), d.population.plans["xv-001"]


def test_R6_10_week4_difference_by_hand():
    """4 control accounts (2 retained) against 4 treatment accounts (3 retained): 0.500000 and 0.750000, +25.00 pp; Newcombe at z = 1.959964:
    Wilson 3/4 [0.30062, 0.95442], Wilson 2/4 [0.15002, 0.84998], low 0.25 - sqrt(0.44944^2 + 0.34998^2) = -0.3196, high 0.25 + sqrt(0.20442^2 + 0.34998^2) = 0.6553."""
    w = World(cutoff="2026-10-26T00:00:00Z")
    for arm, n, kept in (("control", 4, 2), ("treatment", 4, 3)):
        for i in range(n):
            a = w.account(f"acc-{arm[0]}-{i}")
            w.signup(a, "2026-08-01T12:00:00Z")
            w.assign(a, arm, "2026-08-01T12:01:00Z")
            if i < kept:
                w.session(a, "2026-08-29T12:00:00Z")                  # calendar day 28 in UTC
            else:
                w.session(a, "2026-08-27T12:00:00Z")                  # day 26: not in 28..34
    ctx, plan = _ctx(w, "2026-10-26T00:00:00Z")
    r = week4_difference(ctx, plan)
    assert r["by_variant"] == {"control": {"retained": 2, "mature_units": 4, "rate": "0.500000"},
                               "treatment": {"retained": 3, "mature_units": 4, "rate": "0.750000"}}
    assert (r["difference_pp"], r["interval"]["low"], r["interval"]["high"], r["interval"]["includes_zero"]) == ("25.00", "-0.319557", "0.655287", True)


def test_R6_10_revenue_difference_with_a_welch_interval_by_hand():
    """Control revenue 0, 0, 30 (mean 10, variance 300); treatment 10, 20, 30 (mean 20, variance 100): difference 10.00; the standard error
    is sqrt(300/3 + 100/3) = 11.547; Welch-Satterthwaite df = 133.33^2 / (100^2/2 + 33.33^2/2) = 3.2, rounded down to 3; t(3) = 3.182446;
    half-width 36.7477: [-26.75, 46.75]."""
    w = World(cutoff="2026-10-26T00:00:00Z")
    c = w.arm("control", 3, 0)
    t = w.arm("treatment", 3, 0, start="2026-10-01T11:00:00Z")
    w.sub(c[2], "2026-10-05T00:00:00Z", "30.00")
    for a, amount in zip(t, ("10.00", "20.00", "30.00")):
        w.sub(a, "2026-10-05T00:00:00Z", amount)
    ctx, plan = _ctx(w, "2026-10-26T00:00:00Z")
    r = revenue_difference(ctx, plan)
    assert r["by_variant"] == {"control": {"units": 3, "mean": "10.00"}, "treatment": {"units": 3, "mean": "20.00"}}
    assert r["difference"] == "10.00"
    assert r["interval"] == {"confidence": "0.95", "df": 3, "t": "3.182446", "low": "-26.75", "high": "46.75", "includes_zero": True}


def test_R6_10_the_snapshot_secondary_figures_equal_the_independent_reference_and_the_generators_designed_relationships():
    inputs = snapshot_inputs()
    d = pipeline(inputs, cutoff=inputs["cutoff"], experiment_version_id="xv-001")
    cut = ts(inputs["cutoff"])
    ctx = Ctx(d.population, cut, canonicalise(d.population, cut), None)
    plan = d.population.plans["xv-001"]
    ref = json.loads((ROOT / "web" / "scripts" / "snapshot-reference.json").read_text())["secondary"]["xv-001@as_of"]
    w4, rv = week4_difference(ctx, plan), revenue_difference(ctx, plan)
    assert w4["by_variant"] == ref["week4"]["by_variant"] and w4["difference_pp"] == ref["week4"]["difference_pp"] == "-4.50"
    assert (w4["interval"]["low"], w4["interval"]["high"]) == (ref["week4"]["low"], ref["week4"]["high"]) == ("-0.136053", "0.047102")
    assert rv["difference"] == ref["revenue"]["difference"] == "33.12"
    assert (rv["interval"]["df"], rv["interval"]["t"], rv["interval"]["low"], rv["interval"]["high"]) == (391, "1.966050", "-25.59", "91.83")
    dr = {x["id"]: x for x in json.loads((SNAPSHOT / "manifest.json").read_text())["designed_relationships"]}
    assert dr["DR-02"]["realised"]["week4"]["control"]["retained"] == 71 and dr["DR-02"]["realised"]["week4"]["treatment"]["retained"] == 62
    assert dr["DR-05"]["realised"]["difference_of_means"] == "33.12"          # the generator's own (normal-approximation) check
    gd = dr["DR-01"]["realised"]["instrumentation_gap_disclosure"]
    assert (gd["v1_gap_accounts"], gd["published_lift_pp"], gd["drawn_lift_pp"], gd["lift_excluding_gap_accounts_pp"]) == (11, "9.50", "11.50", "9.96")
    assert gd["by_arm"]["control"]["gap_accounts"] == 5 and gd["by_arm"]["treatment"]["gap_accounts"] == 6 and gd["by_arm"]["treatment"]["gap_drawn_activations"] == 4
    ex = d.metrics["experiment"]["primary"]
    assert ex["absolute_lift_pp"] == gd["published_lift_pp"]                   # the disclosure's published figure is the domain's


def test_R6_08_the_published_v1_figures_are_unchanged_by_the_d10_rules():
    """D-10 changes v2 (one treatment account activated before it was assigned) and nothing in v1: +9.50 pp, [0.000812, 0.186863], conclusive."""
    inputs = snapshot_inputs()
    for cut in ("2026-08-02T00:00:00Z", inputs["cutoff"]):
        p = pipeline(inputs, cutoff=cut, experiment_version_id="xv-001").metrics["experiment"]["primary"]
        assert (p["variants"]["control"]["activated"], p["variants"]["treatment"]["activated"], p["absolute_lift_pp"]) == (63, 82, "9.50")
        assert (p["interval"]["low"], p["interval"]["high"], p["conclusive"]) == ("0.000812", "0.186863", True)
    v2 = pipeline({**inputs, "analysis_plan": inputs["analysis_plans"]["xv-002"]}, cutoff="2026-10-04T00:00:00Z", experiment_version_id="xv-002").metrics["experiment"]
    assert v2["srm"]["verdict"] == "MISMATCH" and v2["srm"]["statistic"] == "25.004329" and v2["primary"]["conclusive"] is False
    assert v2["primary"]["variants"]["treatment"]["activated"] == 39                 # was 40 before D-10: one activation precedes its assignment


# ---------------------------------------------------------------------------- R6-07, the rest of C10's refusals (A-054)
def test_R6_07_the_remaining_decision_refusals_are_audited_too(client, conn):
    L = Lab(client, conn, world=small_experiment((100, 20), (100, 40)))
    a, r = L.final()
    before = len(_refusals(conn))
    cases = [("DECISION_INVALID", 422, lambda: L.decide(a, r, "launch")),
             ("BACKFILL_ADMIN_ONLY", 403, lambda: L.decide(a, r, "ship", decided_at="2026-01-01T00:00:00Z")),
             ("ANALYSIS_UNKNOWN", 404, lambda: L.decide("an-nope", r, "ship")),
             ("REVIEW_UNKNOWN", 404, lambda: L.decide(a, "rv-nope", "ship")),
             ("DECIDED_BEFORE_RUN", 422, lambda: L.decide(a, r, "ship", who=ADMIN, decided_at="2026-10-26T21:00:00Z", backfill=True))]
    seen = []
    for rule, status, call in cases:
        res = call()
        assert res.status_code == status and rule_ids(res) == [rule], (rule, res.text)
        seen.append(rule)
        assert _refusals(conn)[before:] == seen, rule                                   # exactly one new row per refusal, with its rule
    assert count(conn, "decisions") == 0
    # a version without a frozen plan: C10 is refused with PLAN_NOT_FROZEN and that is kept too
    conn.execute("ALTER TABLE analysis_plans DISABLE TRIGGER USER")
    conn.execute("DELETE FROM analysis_plans")
    conn.execute("ALTER TABLE analysis_plans ENABLE TRIGGER USER")
    res = L.decide(a, r, "ship")
    assert res.status_code == 409 and _refusals(conn)[-1] == "PLAN_NOT_FROZEN"


def test_R6_06_the_plain_read_says_why_the_experiment_block_is_withheld(client, conn):
    w = World(planned_end="2026-11-15T00:00:00Z")
    w.arm("control", 5, 1)
    w.arm("treatment", 5, 2, start="2026-10-01T11:00:00Z")
    Lab(client, conn, world=w, plan=False)
    g = get(client, "/metrics", cutoff="2026-10-26T00:00:00Z", experiment_version_id="xv-001")
    assert g.status_code == 200 and g.json()["data"]["metrics"]["experiment"] is None
    assert "EXPERIMENT_WITHHELD_PLAN_NOT_FROZEN" in [x["code"] for x in g.json()["warnings"]]
