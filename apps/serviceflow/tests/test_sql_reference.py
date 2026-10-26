"""data/sql/reference_metrics.sql recomputes the metrics independently of the Python domain (event log, window
functions) and equals the golden values and the domain."""
from pathlib import Path

import pytest

from serviceflow import compute_metrics, run_pipeline
from serviceflow.contract import METRIC_KEYS
from serviceflow.timeutil import parse_ts

from support_db import World, at, conn, db_url, golden_expected, golden_inputs, load, seeded  # noqa: F401

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()


def reference(conn, inputs):
    return conn.execute(SQL, {"w0": inputs["window_start"], "w1": inputs["window_end"],
                              "cutoffs": inputs["backlog_cutoffs"], "abandonable": inputs["abandonable_channels"]}).fetchone()


@pytest.mark.parametrize("variant", ["", "variant-rejected", "variant-empty"])
def test_sql_equals_expected_for_every_fixture(conn, variant):
    from data import seed
    inputs = golden_inputs(variant)
    seed.seed(conn, inputs)
    row = reference(conn, inputs)
    want = golden_expected(variant)["metrics"]
    assert set(row) == set(want) == set(METRIC_KEYS)
    for k in METRIC_KEYS:
        assert row[k] == want[k], k


def test_sql_values_for_the_spec_sentence(seeded):
    row = reference(seeded, golden_inputs())
    assert (row["mean_wait_minutes"], row["p90_first_response_minutes"], row["handling_minutes_total"],
            row["agent_occupancy"], row["sla_first_response_compliance"]) == ("10.0000", "20.0000", "30.0000", "0.500000", "0.666667")
    assert row["backlog"] == {"2026-07-06T09:05:00Z": 3, "2026-07-06T09:25:00Z": 1, "2026-07-06T10:00:00Z": 0}


def rich_world() -> World:
    """Reopen, transfer, pause/resume, abandonment, a bot ack, an open overdue ticket, two priorities and surveys."""
    w = World(window=(0, 240), cutoffs=[15, 70, 100, 240])
    w.ticket("t-01", 0, priority="P1")
    w.ev("t-01", "acknowledged_bot", 0.1, actor="bot-1")
    w.serve("t-01", 4, 20)
    w.ticket("t-02", 5, channel="chat")
    w.ev("t-02", "abandoned", 12, actor=None)
    w.ticket("t-03", 10, queue="q-1")
    w.ev("t-03", "transferred", 20, actor="s", queue="q-2")
    w.serve("t-03", 40, 55, queue="q-2")
    w.ev("t-03", "reopened", 60, actor="s")
    w.serve("t-03", 80, 95, agent="a-2")
    w.ticket("t-04", 30, priority="P3")
    w.ev("t-04", "service_started", 35, agent="a-2")
    w.ev("t-04", "replied_human", 36, agent="a-2")
    w.ev("t-04", "paused", 50, agent="a-2")
    w.ev("t-04", "resumed", 120, agent="a-2")
    w.ev("t-04", "resolved", 130, agent="a-2")
    w.ticket("t-05", 0)                                     # still open at the end: overdue
    w.ticket("t-06", 100, priority="P2")
    w.serve("t-06", 150, 151, agent="a-1")
    for i, (tid, resp, score) in enumerate((("t-01", True, 5), ("t-03", True, 2), ("t-04", False, None), ("t-06", True, 4)), 1):
        w.d["surveys"].append({"survey_id": f"sv-{i}", "ticket_id": tid, "invited_at": at(200),
                               "response_at": at(210) if resp else None, "score": score})
    w.d["surveys"].append({"survey_id": "sv-9", "ticket_id": "t-05", "invited_at": at(200), "response_at": None, "score": None})
    return w


def test_sql_agrees_with_the_domain_on_a_rich_history(conn):
    w = rich_world()
    inputs = w.data()
    load(conn, w)
    res = run_pipeline(inputs)
    assert res.rejected == []
    row = reference(conn, inputs)
    for k in METRIC_KEYS:
        assert row[k] == res.metrics[k], k
    assert res.metrics["completion_count"] == 4 and res.metrics["open_overdue_at_cutoff"] == 1


@pytest.mark.parametrize("window", [(0, 60), (30, 125), (100, 240), (0, 481)])
def test_sql_agrees_with_the_domain_in_other_windows(conn, window):
    w = rich_world()
    inputs = w.data()
    inputs["window_start"], inputs["window_end"] = at(window[0]), at(window[1])
    inputs["backlog_cutoffs"] = [at(window[0] + 1), at(window[1])]
    load(conn, w)
    got = run_pipeline(inputs).metrics
    row = reference(conn, inputs)
    for k in METRIC_KEYS:
        assert row[k] == got[k], (window, k)


def test_sql_p90_is_nearest_rank_on_ten(conn):
    w = World()
    for i in range(1, 11):
        w.ticket(f"t-{i:02d}", 0)
        w.serve(f"t-{i:02d}", i * 2, i * 2 + 1)
    inputs = w.data()
    load(conn, w)
    assert reference(conn, inputs)["p90_first_response_minutes"] == "18.0000"
