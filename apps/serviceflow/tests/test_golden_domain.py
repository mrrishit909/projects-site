"""Golden fixture through the pure domain: every metric equals expected.json key by key (P04-GOLD-01..)."""
from datetime import datetime, timezone

import pytest

from serviceflow import compute_metrics, run_pipeline, simulate
from serviceflow.contract import ENTITIES, METRIC_KEYS
from serviceflow.metrics import histories
from serviceflow.timeutil import parse_ts

from support_db import golden_expected, golden_inputs


@pytest.fixture(scope="module")
def result():
    return run_pipeline(golden_inputs())


@pytest.mark.parametrize("key", METRIC_KEYS)
def test_metric_equals_expected(result, key):
    exp = golden_expected()["metrics"]
    assert result.metrics[key] == exp[key] and type(result.metrics[key]) is type(exp[key])


def test_metric_names_are_exactly_the_expected_keys(result):
    exp = golden_expected()["metrics"]
    assert list(result.metrics) == list(exp) == list(METRIC_KEYS)


def test_whole_golden_shape_equals_expected_json(result):
    assert result.golden() == golden_expected()


@pytest.mark.parametrize("entity", ENTITIES)
def test_ingest_counts_per_entity(result, entity):
    assert result.counts[entity] == golden_expected()["ingest"]["counts"][entity]


def test_nothing_is_rejected_in_the_golden_batch(result):
    assert result.rejected == golden_expected()["ingest"]["rejected_records"] == []


def test_spec_sentence_service_starts_waits_mean_and_final_completion():
    """P04-GOLD-01: one agent, three tickets at minute 0, deterministic 10 minute service, FIFO."""
    sim = simulate({"agents": 1, "service_minutes": 10, "arrivals": [0, 0, 0], "discipline": "fifo"}, 1, 0, 60, "sim-001")
    starts = [e["event_at"] for e in sim.events if e["event_type"] == "service_started"]
    assert starts == ["0.0000", "10.0000", "20.0000"]
    g = sim.golden()
    assert g["waits_minutes"] == ["0.0000", "10.0000", "20.0000"]
    assert g["mean_wait_minutes"] == "10.0000" and g["final_completion_minute"] == "30.0000"


def test_simulation_equals_expected_key_by_key(result):
    exp = golden_expected()["simulation"]
    got = result.simulations[0].golden()
    assert list(got) == list(exp)
    for k in exp:
        assert got[k] == exp[k], k


def test_observed_history_gives_the_same_waits_as_the_simulation(result):
    """Part (a) and part (b) of CALCULATION.md are the same arithmetic by different routes."""
    waits = result.metrics["wait_minutes"]
    assert [waits[t] for t in ("t-001", "t-002", "t-003")] == result.simulations[0].golden()["waits_minutes"]


def test_bot_acknowledgement_is_never_the_first_response(result):
    # every ticket has a bot ack at +5 s; the first responses are 0, 10, 20 minutes, not 5 seconds
    assert result.metrics["first_response_minutes"] == {"t-001": "0.0000", "t-002": "10.0000", "t-003": "20.0000"}


def test_late_queued_stamp_does_not_move_the_replay():
    """e-003 'queued' is stamped one second AFTER service began: the replay keeps the real service interval."""
    pop = run_pipeline(golden_inputs()).population
    h = histories(pop)["t-001"]
    assert [(iv.start.minute, iv.end.minute) for iv in h.intervals] == [(0, 10)]
    assert h.state_at(parse_ts("2026-07-06T09:00:03Z")) == "in_service"


def test_window_is_half_open():
    inputs = golden_inputs()
    pop = run_pipeline(inputs).population
    w = lambda a, b: (parse_ts(a), parse_ts(b))  # noqa: E731
    # [09:00, 09:30): t-003 resolves AT 09:30 so it is outside; arrivals at 09:00 are inside
    m = compute_metrics(pop, w("2026-07-06T09:00:00Z", "2026-07-06T09:30:00Z"), [])
    assert (m["arrival_count"], m["completion_count"]) == (3, 2)
    # [09:00:01, ...): the three arrivals at exactly 09:00:00 fall before the window
    m = compute_metrics(pop, w("2026-07-06T09:00:01Z", "2026-07-06T10:00:00Z"), [])
    assert m["arrival_count"] == 0 and m["completion_count"] == 3 and m["mean_first_response_minutes"] is None


def test_reversed_window_is_refused():
    pop = run_pipeline(golden_inputs()).population
    with pytest.raises(Exception) as err:
        compute_metrics(pop, (datetime(2026, 7, 7, tzinfo=timezone.utc), datetime(2026, 7, 6, tzinfo=timezone.utc)))
    assert "INVALID_WINDOW" in str(err.value)


def test_subprocess_reference_check_is_independent_of_the_domain():
    """reference_check.py imports nothing from the application; it still agrees (also run as a script by the gate)."""
    import subprocess
    import sys
    from pathlib import Path
    p = Path(__file__).resolve().parent / "reference_check.py"
    out = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip().endswith("ALL OK")
