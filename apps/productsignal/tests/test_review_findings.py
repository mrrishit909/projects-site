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
from test_sql_reference import reference

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
