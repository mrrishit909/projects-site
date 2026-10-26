"""Golden fixture through the pure domain: every metric equals expected.json key by key (both states)."""
import subprocess
import sys
from pathlib import Path

import pytest

from onboard_studio import run_pipeline
from onboard_studio.contract import METRIC_KEYS
from onboard_studio.workflow import definition_hash

from support_db import golden_expected, golden_inputs

ROOT = Path(__file__).resolve().parents[1]
STATES = ["pause_eligible", "pause_not_eligible"]


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("key", METRIC_KEYS)
def test_metric_equals_expected(state, key):
    exp = golden_expected()["states"][state]["metrics"]
    got = run_pipeline(golden_inputs(), state).metrics
    assert got[key] == exp[key]


@pytest.mark.parametrize("state", STATES)
def test_metric_names_are_exactly_the_expected_keys(state):
    exp = golden_expected()["states"][state]["metrics"]
    got = run_pipeline(golden_inputs(), state).metrics
    assert list(got) == list(exp) == list(METRIC_KEYS)


def test_golden_numbers_from_the_spec_sentence():
    m = run_pipeline(golden_inputs(), "pause_eligible").metrics
    assert (m["calendar_cycle_time_hours"], m["business_cycle_time_hours"], m["active_elapsed_hours"]) == \
        ("66.0000", "2.0000", "1.0000")
    assert run_pipeline(golden_inputs(), "pause_not_eligible").metrics["active_elapsed_hours"] == "2.0000"


def test_ingest_counts_and_rejections():
    exp = golden_expected()["ingest"]
    res = run_pipeline(golden_inputs(), "pause_eligible")
    assert res.counts == exp["counts"]
    assert res.rejected == exp["rejected_records"] == []


def test_definition_hash_matches_fixture():
    data = golden_inputs()
    wv = data["workflow_versions"][0]
    deps = data["dependencies"]
    assert definition_hash(data["step_definitions"], deps) == wv["definition_hash"]


def test_no_state_keeps_the_configured_policy():
    assert run_pipeline(golden_inputs()).metrics == run_pipeline(golden_inputs(), "pause_eligible").metrics


def test_cutoff_keys_are_utc_z_strings():
    m = run_pipeline(golden_inputs(), "pause_eligible", cutoffs=["2026-03-07T12:00:00+00:00"]).metrics
    assert m["open_backlog_at_cutoff"] == {"2026-03-07T12:00:00Z": 1}


def test_independent_oracle_still_all_ok():
    out = subprocess.run([sys.executable, "-I", str(ROOT / "tests" / "reference_check.py")],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout[-500:]
    assert out.stdout.strip().endswith("ALL OK")
