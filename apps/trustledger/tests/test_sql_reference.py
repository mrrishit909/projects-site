"""data/sql/reference_metrics.sql recomputes every metric from the facts, independently of the Python domain and of any stored status or
result, and equals expected.json on the fixtures and the domain on any loaded population.

Match precision reads the verification layer's truth table, which only these tests load (``load`` does it; the seeder never does)."""
from pathlib import Path

import psycopg
import pytest

from trustledger import run_pipeline
from trustledger.contract import METRIC_KEYS
from trustledger.timeutil import parse_ts

from support_db import VARIANTS, conn, db_url, flat, golden_expected, golden_inputs, iso, load, ts  # noqa: F401
from worlds import random_world

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
COLUMNS = (*METRIC_KEYS, "empty_population")


def reference(conn, as_of, wv=None):
    return conn.execute(SQL, {"as_of": parse_ts(as_of), "wv": wv}).fetchone()


@pytest.mark.parametrize("variant", VARIANTS)
def test_sql_equals_expected_for_every_fixture_key_by_key(conn, variant):
    inputs = golden_inputs(variant)
    load(conn, inputs)
    row = reference(conn, inputs["as_of"])
    want = golden_expected(variant)
    assert set(row) == set(COLUMNS)
    for k in METRIC_KEYS:
        assert row[k] == want["metrics"][k], k
    assert row["empty_population"] is want["empty_population"]
    assert flat({k: row[k] for k in METRIC_KEYS}) == flat(want["metrics"])                           # every leaf, key by key


def test_sql_spec_sentence_values(conn):
    inputs = golden_inputs()
    load(conn, inputs)
    r = reference(conn, inputs["as_of"])
    assert r["completeness"]["r-cust-complete-email"]["value"] == "0.950000"
    v = r["validity"]["r-cust-valid-email"]
    assert (v["populated_only"], v["all_eligible"]) == ({"label": "validity_populated_only", "value": "0.947368"}, {"label": "validity_all_eligible", "value": "0.900000"})
    ws = r["weighted_score"]["datasets"]["ds-customers"]
    assert (ws["value"], ws["critical_override"], ws["critical_failures"]) == ("0.963932", True, 2)
    assert reference(conn, inputs["as_of"], "w1")["weighted_score"]["datasets"]["ds-customers"]["value"] == "0.958116"


def test_sql_precision_comes_from_the_truth_table_only(conn):
    inputs = golden_inputs()
    load(conn, inputs, truth=False)                                                             # the seeder alone loads no truth
    assert conn.execute("SELECT count(*) AS n FROM verification_truth").fetchone()["n"] == 0
    p = reference(conn, inputs["as_of"])["match_precision"]
    assert p == {"approved_decisions": 3, "approved_correct": None, "precision": None, "reviewed": 4, "reviewed_correct": None, "reviewed_correct_share": None}
    for rec, ent in inputs["synthetic_truth"]["true_entity"].items():
        conn.execute("INSERT INTO verification_truth VALUES (%s, %s)", (rec, ent))
    p = reference(conn, inputs["as_of"])["match_precision"]
    assert (p["approved_correct"], p["precision"], p["reviewed_correct_share"]) == (2, "0.666667", "0.500000")
    conn.execute("DELETE FROM verification_truth WHERE record_id = 'rec-003'")                    # one decided record unknown: unknown, not wrong
    assert reference(conn, inputs["as_of"])["match_precision"]["precision"] is None


def test_sql_is_independent_of_every_stored_result_and_of_the_session_time_zone(conn):
    """Scramble what the commands store (audit, command results, issue events, the details of runs): the SQL does not read them."""
    inputs = golden_inputs()
    load(conn, inputs)
    want = golden_expected()
    conn.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id) VALUES ('e', 't', 'i', 'a', 'x')")
    conn.execute("INSERT INTO command_results VALUES ('k', 'h', 'a', 'admin', 'c', 's', '{}')")
    conn.execute("INSERT INTO issue_events (event_id, issue_id, event_type, occurred_at) VALUES ('ie-x', 'iss-001', 'reopened', now())")
    conn.execute("ALTER TABLE rule_runs DISABLE TRIGGER USER")
    conn.execute("UPDATE rule_runs SET details = '{\"value\": \"9.9\"}'::jsonb, run_by = 'x'")
    conn.execute("ALTER TABLE rule_runs ENABLE TRIGGER USER")
    base = reference(conn, inputs["as_of"])
    for k in METRIC_KEYS:
        assert base[k] == want["metrics"][k], k
    for tz in ("Pacific/Kiritimati", "America/Los_Angeles"):
        conn.execute(f"SET TIME ZONE '{tz}'")                                                   # constants
        assert reference(conn, inputs["as_of"]) == base, tz


@pytest.mark.parametrize("as_of", ["2026-08-20T00:00:00Z", "2026-09-21T00:00:00Z", "2026-09-30T03:00:00Z", "2026-10-05T00:00:00Z", "2026-12-01T00:00:00Z"])
def test_sql_equals_the_domain_on_the_golden_population_at_other_times(conn, as_of):
    inputs = golden_inputs()
    load(conn, inputs)
    res = run_pipeline(inputs, as_of=as_of)
    row = reference(conn, as_of)
    assert {k: row[k] for k in METRIC_KEYS} == res.metrics and row["empty_population"] == res.empty_population


@pytest.mark.parametrize("start", range(0, 160, 20))
def test_sql_equals_the_domain_on_random_populations(conn, start):
    """Seeded random populations (see worlds.py); each is loaded in a transaction that is rolled back."""
    from data import seed
    checked = 0
    for s in range(start, start + 20):
        d, wv = random_world(s)
        res = run_pipeline(d, weight_version=wv)
        with conn.transaction():                       # psycopg.Rollback ends the block and discards the load
            seed.seed(conn, d)
            for rec, ent in d["synthetic_truth"]["true_entity"].items():
                conn.execute("INSERT INTO verification_truth VALUES (%s, %s)", (rec, ent))
            row = reference(conn, d["as_of"], wv)
            diffs = [k for k in METRIC_KEYS if row[k] != res.metrics[k]] + ([] if row["empty_population"] == res.empty_population else ["empty_population"])
            assert not diffs, (s, diffs, [(k, flat(row[k]), flat(res.metrics[k])) for k in diffs[:1]])
            checked += 1
            raise psycopg.Rollback()
    assert checked == 20


def test_the_random_worlds_exercise_the_rules():
    """The populations are not trivial: across the seeds every rule type, every issue class, reversals and the override all occur."""
    seen = {"types": set(), "classes": set(), "override": 0, "reversed": 0, "uncovered": 0, "rejected": 0, "not_comparable": 0, "late": 0, "filters": 0}
    for s in range(160):
        d, wv = random_world(s)
        res = run_pipeline(d, weight_version=wv)
        m = res.metrics
        seen["types"] |= {r.rule_type for r in res.population.quality_rules}
        seen["classes"] |= {v["class"] for v in m["resolution_time"]["issues"].values()}
        seen["override"] += sum(1 for v in m["weighted_score"]["datasets"].values() if v["critical_override"])
        seen["reversed"] += res.computation.matching["merges_reversed"]
        seen["uncovered"] += len(m["ownership_coverage"]["uncovered"])
        seen["rejected"] += len(res.rejected)
        seen["not_comparable"] += sum(1 for c in res.computation.rules["comparisons"].values() if not c["comparable"])
        seen["late"] += sum(1 for v in m["timeliness"]["datasets"].values() if not v["on_time"])
        seen["filters"] += sum(1 for r in res.population.quality_rules if r.definition.get("filter"))
    assert seen["types"] == {"completeness", "validity", "uniqueness", "relationship", "timeliness"} and seen["classes"] == {"open", "claimed", "resolved"}
    assert all(seen[k] > 5 for k in ("override", "reversed", "uncovered", "rejected", "not_comparable", "late", "filters")), seen


@pytest.mark.parametrize("zone,day,local", [("Europe/London", "2026-10-25", "01:30"), ("America/New_York", "2026-11-01", "01:30"),
                                            ("Europe/London", "2026-03-29", "01:30"), ("America/New_York", "2026-03-08", "02:30"),
                                            ("Australia/Lord_Howe", "2026-10-04", "02:15"), ("Pacific/Auckland", "2026-09-27", "02:30")])
def test_clock_change_days_sql_and_domain_agree_on_the_occurrence(conn, zone, day, local):
    from support_db import World
    w = World(f"{day}T20:00:00Z")
    w.owner("o1")
    w.dataset("d1", "o1", monitored=True, refresh_timezone=zone, refresh_local_time=local, refresh_grace_minutes=90, last_refreshed_at=f"{day}T02:00:00Z")
    for hour in range(0, 24):
        for minute in (0, 30):
            w.d["as_of"] = f"{day}T{hour:02d}:{minute:02d}:00Z"
            res = run_pipeline(w.data())
            with conn.transaction():
                from data import seed
                seed.seed(conn, w.data())
                row = reference(conn, w.d["as_of"])
                assert row["timeliness"] == res.metrics["timeliness"], (zone, w.d["as_of"])
                raise psycopg.Rollback()
