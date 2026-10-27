"""data/sql/reference_metrics.sql recomputes net cash flow, NPV, both paybacks, capacity released, adoption, training, cost variance, benefit realization,
risk exposure, readiness, dependency delay and the double-count residual from the stored facts, independently of the Python domain and of any stored
result, and equals expected.json leaf for leaf on the three fixtures and the domain on any loaded population.

The ONLY tolerance in the project is the NPV: PostgreSQL's power(numeric, integer) keeps a bounded number of digits, so the SQL NPV (6 places) is compared
with the exact rational of the domain within 0.000001 USD; every other figure, the 2-place NPV included, is compared for equality."""
import re
from fractions import Fraction as F
from pathlib import Path

import psycopg
import pytest

from changeworks import run_pipeline
from changeworks.timeutil import parse_ts

from support_db import VARIANTS, conn, db_url, flat, golden_expected, golden_inputs, load, ts  # noqa: F401
from worlds import random_world

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
NPV_TOLERANCE = F(1, 1_000_000)
S = r"metrics\.scenarios\.[^.]+\.initiatives\.[^.]+\."
COVERED = re.compile("^(" + "|".join([
    "empty_population",
    S + r"cash_flow\[\d+\]\.(costs|cash_benefits|net_cash_flow|cumulative|discounted_cash_flow|cumulative_discounted)",
    S + r"npv\.value", S + r"payback\.(simple|discounted)\.(period|interpolated)", S + r"capacity_released\.(hours|reason)",
    S + r"cost_variance\.(window\.to_period|approved_baseline_cost|actual_cost|variance|reason)",
    S + r"benefit_realization\.[a-z_]+\.(planned_comparable|observed_comparable|realization|baseline_trend|observed_above_trend)",
    r"metrics\.scenarios\.[^.]+\.double_count\.(planned_benefits|attributable_benefits|residual)", r"metrics\.scenarios\.[^.]+\.npv_total\.value",
    r"metrics\.initiatives\.[^.]+\.adoption\.(adoption_rate|eligible_count|adopted_count)", r"metrics\.initiatives\.[^.]+\.training\.(training_completion|eligible_trainees|completed)",
    r"metrics\.initiatives\.[^.]+\.risk\.risk_exposure", r"metrics\.initiatives\.[^.]+\.roadmap\.(dependency_feasible_start|dependency_delay|binding_dependency_id)",
    r"metrics\.groups\.[^.]+\.readiness_score",
    r"metrics\.summary\.(npv_total|double_count_residual|adoption_rate|training_completion|risk_exposure_total|capacity_released_hours_total)",
]) + ")$")


def reference(conn, as_of):
    conn.execute("SET jit = off")        # the statement is cheap but PostgreSQL over-estimates its cross joins, and JIT compilation then costs ~8 s per run
    rows = conn.execute(SQL, {"as_of": parse_ts(as_of)}).fetchall()
    out = {r["path"]: r["val"] for r in rows}
    assert len(out) == len(rows), "a path is emitted twice"
    return out


def text(v):
    return None if v is None else str(v).lower() if isinstance(v, bool) else str(v)


def compare(sql, want, label=""):
    """Every SQL row equals its leaf (the 6-place NPV within the tolerance); every covered leaf of ``want`` is present in the SQL output."""
    assert not [p for p in sql if p not in want and not p.endswith(".npv.value_6dp")], [p for p in sql if p not in want][:5]
    diffs = [(p, want[p], v) for p, v in sql.items() if not p.endswith(".npv.value_6dp") and text(want[p]) != v]
    assert diffs == [], (label, diffs[:5])
    missing = [p for p in want if COVERED.match(p) and p not in sql]
    assert missing == [], (label, missing[:5])
    return len(sql)


@pytest.mark.parametrize("variant", VARIANTS)
def test_sql_equals_expected_for_every_fixture_leaf_by_leaf(conn, variant):
    inputs = golden_inputs(variant)
    load(conn, inputs)
    sql = reference(conn, inputs["as_of"])
    n = compare(sql, flat(golden_expected(variant)), variant)
    assert n == {"": 157, "variant-rejected": 229, "variant-empty": 7}[variant]


def test_sql_spec_sentence_values(conn):
    inputs = golden_inputs()
    load(conn, inputs)
    r = reference(conn, inputs["as_of"])
    p = "metrics.scenarios.scn-001.initiatives.init-001."
    assert (r[p + "npv.value"], r[p + "payback.simple.interpolated"], r[p + "payback.discounted.interpolated"]) == ("41.32", "1.6667", "1.9167")
    assert r[p + "cash_flow[1].cash_benefits"] == "600.00" and r[p + "capacity_released.hours"] == "400.0000"       # the 800 capacity hours are not in the cash flow
    assert r["metrics.scenarios.scn-001.double_count.residual"] == "75.00" and r["metrics.groups.grp-001.readiness_score"] == "3.3333"
    assert r["metrics.summary.npv_total"] == "-692.56" and r["metrics.initiatives.init-003.roadmap.dependency_delay"] == "3"


@pytest.mark.parametrize("variant", VARIANTS)
def test_sql_npv_is_within_the_documented_tolerance_of_the_exact_rational(conn, variant):
    inputs = golden_inputs(variant)
    load(conn, inputs)
    sql = reference(conn, inputs["as_of"])
    exp = flat(golden_expected(variant))
    checked = 0
    for path, exact in exp.items():
        if path.endswith(".npv.exact") and exact is not None:
            six = sql[path[: -len("exact")] + "value_6dp"]
            assert abs(F(six) - F(exact)) <= NPV_TOLERANCE, (path, six, exact)
            checked += 1
    assert checked == {"": 3, "variant-rejected": 4, "variant-empty": 0}[variant]


def test_sql_reads_only_facts_not_stored_results_and_not_the_session_time_zone(conn):
    """Scramble what the commands store (audit, results, expanded costs, scores): the SQL does not read them. Change the session time zone: no difference."""
    inputs = golden_inputs()
    load(conn, inputs)
    base = reference(conn, inputs["as_of"])
    conn.execute("INSERT INTO audit_events (event_id, entity_type, entity_id, action, actor_id) VALUES ('e', 't', 'i', 'a', 'x')")
    conn.execute("INSERT INTO command_results VALUES ('k', 'h', 'a', 'admin', 'c', 's', '{}')")
    conn.execute("INSERT INTO expanded_costs VALUES ('scn-001', 'c-101', 'init-001', 0, 99999)")
    conn.execute("INSERT INTO opportunity_scores VALUES ('os', 'init-001', 1, '[]', 99, '99', 'r', 'a', now())")
    conn.execute("INSERT INTO rejected_records (batch_id, entity, id, reason_code, raw_row) VALUES ('b', 'cost_items', 'x', 'C', '{}')")
    assert reference(conn, inputs["as_of"]) == base
    for tz in ("Pacific/Kiritimati", "America/Los_Angeles"):
        conn.execute(f"SET TIME ZONE '{tz}'")                                                  # constants
        assert reference(conn, inputs["as_of"]) == base, tz


def test_sql_ignores_what_the_ingest_rejected_and_matches_when_nothing_is_loaded_for_a_scenario(conn):
    inputs = golden_inputs("variant-rejected")
    load(conn, inputs)
    sql = reference(conn, inputs["as_of"])
    assert not [p for p in sql if "rs-1" in p or "rs-4" in p or "rs-5" in p]                    # the rejected scenarios do not exist
    assert not conn.execute("SELECT 1 FROM scenario_versions WHERE scenario_id IN ('rs-1', 'rs-4', 'rs-5')").fetchall()


@pytest.mark.parametrize("variant,as_ofs", [
    ("", ["2026-06-30T00:00:00Z", "2026-12-31T23:59:59Z", "2027-01-01T00:00:00Z", "2027-06-30T00:00:00Z", "2028-01-01T00:00:00Z", "2028-03-31T00:00:00Z",
          "2029-01-01T00:00:00Z", "2031-01-01T00:00:00Z"]),
    ("variant-rejected", ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", "2026-03-15T00:00:00Z", "2026-06-30T00:00:00Z", "2026-09-01T00:00:00Z", "2027-06-30T00:00:00Z"])])
def test_sql_equals_the_domain_at_other_as_of_instants(conn, variant, as_ofs):
    inputs = golden_inputs(variant)
    load(conn, inputs)
    for as_of in as_ofs:
        compare(reference(conn, as_of), flat({"metrics": run_pipeline(inputs, as_of=as_of).metrics, "empty_population": False}), as_of)


@pytest.mark.parametrize("start", range(0, 60, 15))
def test_sql_equals_the_domain_on_random_populations(conn, start):
    """Seeded random populations (see worlds.py); each is loaded in a transaction that is rolled back."""
    from data import seed
    paths = checked = 0
    for s in range(start, start + 15):
        d = random_world(s)
        res = run_pipeline(d)
        with conn.transaction():                       # psycopg.Rollback ends the block and discards the load
            seed.seed(conn, d)
            paths += compare(reference(conn, d["as_of"]), flat({"metrics": res.metrics, "empty_population": res.empty_population}), f"seed {s}")
            checked += 1
            raise psycopg.Rollback()
    assert checked == 15 and paths > 15 * 20


def test_the_random_worlds_exercise_the_rules():
    """The populations are not trivial: across the seeds ramps, conversions, avoided cost beside the flow, overlaps, paybacks, null paybacks, variances,
    realization, dependency delays, rejections and monthly periods all occur."""
    seen = {k: 0 for k in ("ramp", "converted", "beside", "overlap", "payback", "never", "variance", "realization", "delay", "rejected", "monthly", "conversion_rate", "unobserved")}
    for s in range(60):
        d = random_world(s)
        r = run_pipeline(d)
        seen["rejected"] += len(r.ingest.rejected)
        seen["monthly"] += d["period_basis"] == "monthly"
        for sc in r.metrics["scenarios"].values():
            seen["conversion_rate"] += sc["rate_source"] != "declared"
            seen["overlap"] += bool(sc["double_count"]["overlaps"])
            for i in sc["initiatives"].values():
                seen["ramp"] += i["ramp"] is not None
                seen["converted"] += bool(i["converted_capacity"])
                seen["beside"] += bool(i["excluded_from_cash_flow"]["avoided_cost_beside"])
                seen["payback"] += i["payback"]["simple"]["period"] is not None
                seen["never"] += i["npv"]["value"] is not None and i["payback"]["simple"]["period"] is None
                seen["variance"] += i["cost_variance"]["variance"] is not None
                seen["realization"] += bool(i["benefit_realization"])
                seen["unobserved"] += any(x["matured_unobserved_items"] for x in i["benefit_realization"].values())
        seen["delay"] += sum(x["roadmap"]["dependency_delay"] > 0 for x in r.metrics["initiatives"].values())
    assert all(v > 5 for v in seen.values()), seen
