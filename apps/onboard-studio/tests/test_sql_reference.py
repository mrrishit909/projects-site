"""data/sql/reference_metrics.sql recomputes the golden hours independently of the Python domain."""
from pathlib import Path

import pytest

from onboard_studio import run_pipeline

from support_db import conn, db_url, golden_expected, golden_inputs, seeded  # noqa: F401

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
HOURS = ["calendar_cycle_time_hours", "business_cycle_time_hours", "paused_time_hours",
         "paused_business_overlap_hours", "active_elapsed_hours"]


def reference(conn):
    return conn.execute(SQL).fetchone()


@pytest.mark.parametrize("state", ["pause_eligible", "pause_not_eligible"])
def test_sql_equals_expected_golden_hours(seeded, state):
    policy = golden_expected()["states"][state]["pause_policy"]
    seeded.execute("UPDATE sla_rules SET pause_policy = %s", (policy,))
    row = reference(seeded)
    want = golden_expected()["states"][state]["metrics"]
    for k in HOURS:
        assert row[k] == want[k], k
    assert row["completed_eligible_cases"] == want["completed_eligible_cases"]
    assert row["within_sla_cases"] == want["within_sla_cases"]


def test_sql_values_for_the_spec_sentence(seeded):
    row = reference(seeded)
    assert (row["calendar_cycle_time_hours"], row["business_cycle_time_hours"], row["active_elapsed_hours"]) == \
        ("66.0000", "2.0000", "1.0000")


def test_sql_on_an_empty_database_returns_null_means(conn, db_url):
    row = reference(conn)
    assert row["completed_eligible_cases"] == 0 and row["calendar_cycle_time_hours"] is None


@pytest.mark.parametrize("start,end,business", [
    ("2026-03-07T00:00:00Z", "2026-03-08T23:59:00Z", "2.0000"),   # weekend holiday subtracts nothing (P02-TEST-08)
    ("2026-03-09T09:00:00Z", "2026-03-09T17:00:00Z", "1.0000"),   # Monday holiday
])
def test_sql_agrees_with_the_domain_on_holidays(seeded, start, end, business):
    seeded.execute("INSERT INTO calendar_intervals VALUES ('hol-1', 'cal-001', %s, %s, 'UTC', 'holiday')", (start, end))
    assert reference(seeded)["business_cycle_time_hours"] == business
    data = golden_inputs()
    data["calendar_intervals"].append({"calendar_interval_id": "hol-1", "calendar_id": "cal-001",
                                       "starts_at": start, "ends_at": end, "timezone": "UTC", "kind": "holiday"})
    assert run_pipeline(data, "pause_eligible").metrics["business_cycle_time_hours"] == business


def test_sql_agrees_with_the_domain_when_the_pause_is_outside_working_time(seeded):
    seeded.execute("UPDATE waiting_intervals SET starts_at = '2026-03-07 10:00+00', ends_at = '2026-03-08 10:00+00'")
    row = reference(seeded)
    data = golden_inputs()
    data["waiting_intervals"][0].update(starts_at="2026-03-07T10:00:00Z", ends_at="2026-03-08T10:00:00Z")
    m = run_pipeline(data, "pause_eligible").metrics
    for k in HOURS:
        assert row[k] == m[k], k
    assert row["paused_business_overlap_hours"] == "0.0000" and row["paused_time_hours"] == "24.0000"
