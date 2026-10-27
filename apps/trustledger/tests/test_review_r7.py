"""Review R7 (docs/contracts.md D-10): each defect the reviewer reproduced, shown fixed in the domain, in the SQL reference and through the API.

Pure-domain tests run without a database; the rest need DATABASE_URL. The reviewer's own probes (timeliness around DST and the deadline,
whitespace and unicode in e-mails, empty foreign keys, null keys, a self-edge, an astral-plane pair) are replayed here with the answer stated by hand.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from api import clock
from trustledger import run_pipeline
from trustledger.contract import METRIC_KEYS
from trustledger.errors import PATTERN_NOT_PORTABLE
from trustledger.models import pattern_portable
from trustledger.timeutil import parse_ts, timeliness_state

from support_db import (ADMIN, ANALYST, INACTIVE, STEWARD, STEWARD2, World, client, command, conn, count, db_url, get, golden_inputs, load,  # noqa: F401
                        metrics, rule_ids, table_digest)

SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
AS_OF = datetime(2026, 10, 5, 0, 0, 0, tzinfo=timezone.utc)


def sql_metrics(conn, as_of, wv=None):
    return conn.execute(SQL, {"as_of": parse_ts(as_of), "wv": wv}).fetchone()


def agree(conn, inputs, wv=None):
    """The domain and the SQL reference give the same answer on one population; returns the domain's metrics."""
    res = run_pipeline(copy.deepcopy(inputs), weight_version=wv)
    load(conn, copy.deepcopy(inputs))
    row = sql_metrics(conn, inputs["as_of"], wv)
    for k in METRIC_KEYS:
        assert row[k] == res.metrics[k], (k, row[k], res.metrics[k])
    return res.metrics


def customers(d):
    return next(x for x in d["datasets"] if x["dataset_id"] == "ds-customers")


def with_refresh(local, tz, grace, last, as_of):
    d = golden_inputs()
    d["as_of"] = as_of
    customers(d).update(refresh_local_time=local, refresh_timezone=tz, refresh_grace_minutes=grace, last_refreshed_at=last, registered_at="2026-01-01T00:00:00Z")
    return d


# ---------------------------------------------------------------------------------------------------------- R7-01 timeliness
#: the reviewer's probes: (local time, zone, grace, last refresh, as_of, state, the occurrence judged)
TIMELINESS = {
    "early_refresh_1030_in_the_open_window": ("06:00", "America/New_York", 60, "2026-10-05T10:10:00Z", "2026-10-05T10:30:00Z", "on_time", "2026-10-05T10:00:00Z"),
    "early_refresh_1059": ("06:00", "America/New_York", 60, "2026-10-05T10:10:00Z", "2026-10-05T10:59:59Z", "on_time", "2026-10-05T10:00:00Z"),
    "early_refresh_1100_deadline_is_the_asof": ("06:00", "America/New_York", 60, "2026-10-05T10:10:00Z", "2026-10-05T11:00:00Z", "on_time", "2026-10-05T10:00:00Z"),
    "yesterdays_refresh_open_window_is_pending": ("06:00", "America/New_York", 60, "2026-10-04T10:20:00Z", "2026-10-05T10:30:00Z", "pending", "2026-10-05T10:00:00Z"),
    "deadline_equals_asof_no_refresh_is_late": ("06:00", "America/New_York", 60, "2026-10-04T10:20:00Z", "2026-10-05T11:00:00Z", "late", "2026-10-05T10:00:00Z"),
    "refresh_after_asof_has_not_happened": ("06:00", "America/New_York", 60, "2026-10-05T10:30:00Z", "2026-10-05T00:00:00Z", "late", "2026-10-04T10:00:00Z"),
    "refresh_equals_occurrence": ("06:00", "America/New_York", 60, "2026-10-04T10:00:00Z", "2026-10-04T11:00:00Z", "on_time", "2026-10-04T10:00:00Z"),
    "grace_zero_is_always_late": ("06:00", "America/New_York", 0, "2026-10-04T10:00:00Z", "2026-10-05T00:00:00Z", "late", "2026-10-04T10:00:00Z"),
    "deadline_equals_asof_closed": ("06:00", "America/New_York", 60, "2026-10-04T10:59:59Z", "2026-10-04T11:00:00Z", "on_time", "2026-10-04T10:00:00Z"),
    # clocks go back in New York on 2026-11-01: 01:30 happens at 05:30Z (EDT) and again at 06:30Z (EST); the later one is the occurrence (D-07)
    "clocks_back_refresh_in_the_first_0130": ("01:30", "America/New_York", 60, "2026-11-01T05:45:00Z", "2026-11-01T12:00:00Z", "late", "2026-11-01T06:30:00Z"),
    "clocks_back_refresh_in_the_second_0130": ("01:30", "America/New_York", 60, "2026-11-01T06:45:00Z", "2026-11-01T12:00:00Z", "on_time", "2026-11-01T06:30:00Z"),
    "clocks_back_asof_between_the_two": ("01:30", "America/New_York", 30, "2026-11-01T05:40:00Z", "2026-11-01T06:10:00Z", "late", "2026-10-31T05:30:00Z"),
    # clocks go forward on 2026-03-08: 02:30 does not exist and uses the offset before the change (EST, 07:30Z)
    "clocks_forward_gap": ("02:30", "America/New_York", 60, "2026-03-08T07:40:00Z", "2026-03-08T12:00:00Z", "on_time", "2026-03-08T07:30:00Z"),
}


@pytest.mark.parametrize("name", sorted(TIMELINESS))
def test_r7_01_timeliness_states_domain_and_sql_agree(conn, name):
    local, tz, grace, last, as_of, state, occurrence = TIMELINESS[name]
    assert timeliness_state(tz, local, grace, parse_ts(last), parse_ts(as_of))[0] == state            # the primitive itself
    m = agree(conn, with_refresh(local, tz, grace, last, as_of))
    t = m["timeliness"]["datasets"]["ds-customers"]
    assert (t["state"], t["evaluated_occurrence_utc"]) == (state, occurrence), name
    assert t["on_time"] is {"on_time": True, "late": False, "pending": None}[state]
    assert t["last_refreshed_at"] == (last if parse_ts(last) <= parse_ts(as_of) else None)         # a refresh after the as-of has not happened yet


def test_r7_01_pending_is_outside_the_denominator_and_counted(conn):
    local, tz, grace, last, as_of, _, _ = TIMELINESS["yesterdays_refresh_open_window_is_pending"]
    m = agree(conn, with_refresh(local, tz, grace, last, as_of))
    t = m["timeliness"]
    assert (t["monitored_datasets"], t["evaluated_datasets"], t["pending_count"]) == (4, 3, 1)
    # at 10:30Z the other three have each missed today's window (orders 06:00-06:30Z, payments 06:00-08:00Z, shipments 04:00-05:00Z): late
    assert (t["on_time_count"], t["value"]) == (0, "0.000000") and {k: v["state"] for k, v in t["datasets"].items()}["ds-orders"] == "late"
    ws = m["weighted_score"]["datasets"]["ds-customers"]
    assert "timeliness" not in ws["measured_dimensions"]                  # a pending dataset's timeliness is not scored: nothing is treated as 0 or 1


def test_r7_01_the_golden_probes_are_stated_in_the_fixture():
    g = run_pipeline(golden_inputs()).golden()["timeliness_probes"]
    assert {k: v["state"] for k, v in g.items()} == {
        "open-window-refreshed": "on_time", "open-window-not-yet-refreshed": "pending", "deadline-equals-as-of-no-refresh": "late",
        "refresh-at-the-deadline": "late", "refresh-after-as-of": "pending", "clocks-back-refresh-in-the-first-0130": "late",
        "clocks-back-refresh-in-the-second-0130": "on_time"}


# ---------------------------------------------------------------------------------------------------------- R7-02 disabled critical
def disabled_key_rule(d, at="2026-10-04T00:00:00Z"):
    r = next(x for x in d["quality_rules"] if x["rule_id"] == "r-cust-key-unique")
    r.update(status="disabled", disabled_at=at, disabled_reason="r7")
    return d


def test_r7_02_a_disabled_critical_rule_keeps_its_live_failure_and_the_override(conn):
    m = agree(conn, disabled_key_rule(golden_inputs()))
    ws = m["weighted_score"]["datasets"]["ds-customers"]
    assert (ws["critical_failures"], ws["critical_override"], ws["critical_open_issues"]) == (2, True, 1)
    assert m["critical_failures"]["carried"] == [{"dataset_id": "ds-customers", "rule_id": "r-cust-key-unique", "rule_run_id": "rr-003", "failure_count": 2}]
    assert m["uniqueness"] == {} and "uniqueness" not in ws["measured_dimensions"]       # it is no longer measured, but its failure is not forgotten


def test_r7_02_without_an_open_issue_the_override_still_holds(conn):
    d = disabled_key_rule(golden_inputs())
    d["issues"] = [i for i in d["issues"] if i["issue_id"] != "iss-006"]                # no issue at all: only the carried failure is left
    m = agree(conn, d)
    ws = m["weighted_score"]["datasets"]["ds-customers"]
    assert (ws["critical_failures"], ws["critical_open_issues"], ws["critical_override"]) == (2, 0, True)


def test_r7_02_a_passing_rerun_clears_it_and_a_failing_one_does_not(conn):
    d = disabled_key_rule(golden_inputs())
    d["rule_runs"].append({"rule_run_id": "rr-900", "rule_id": "r-cust-key-unique", "rule_version": 1, "weight_version": "w2", "kind": "rerun",
                           "run_at": "2026-10-04T12:00:00Z", "eligible_count": 2, "failure_count": 1, "rerun_for_issue": "iss-006"})
    m = run_pipeline(copy.deepcopy(d)).metrics
    assert m["critical_failures"]["carried"][0]["rule_run_id"] == "rr-900" and m["critical_failures"]["failures"] == 1
    d["rule_runs"][-1].update(rule_run_id="rr-901", failure_count=0, run_at="2026-10-04T13:00:00Z")
    m = agree(conn, d)
    assert m["critical_failures"]["carried"] == [] and m["critical_failures"]["failures"] == 0
    assert m["weighted_score"]["datasets"]["ds-customers"]["critical_override"] is True           # the open critical issue iss-006 still holds the override


def test_r7_02_a_rule_disabled_after_the_asof_was_still_active_and_a_non_critical_rule_carries_nothing():
    late = run_pipeline(disabled_key_rule(golden_inputs(), at="2026-10-06T00:00:00Z")).metrics
    assert late["critical_failures"]["carried"] == [] and late["weighted_score"]["datasets"]["ds-customers"]["critical_failures"] == 2     # measured, not carried
    m = run_pipeline(golden_inputs()).metrics              # r-ord-amount-range is disabled, not critical, and its last run fails (1): nothing carried
    assert m["critical_failures"]["carried"] == []


@pytest.fixture
def lab(client, conn):
    load(conn, golden_inputs())
    clock.freeze(AS_OF)
    return client


def test_r7_02_run_rule_then_disable_rule_without_an_issue_through_the_api(lab, conn):
    """The reviewer's sequence: C03 run-rule on the critical key rule, then C09 disable-rule, no issue opened: the failure and the override stay."""
    run = command(lab, "run-rule", {"rule_id": "r-cust-key-unique"}, headers=ANALYST)
    assert run.status_code == 200 and run.json()["result"]["failure_count"] == 2
    clock.freeze(AS_OF + timedelta(hours=1))
    dis = command(lab, "disable-rule", {"rule_id": "r-cust-key-unique", "reason": "r7 probe"}, headers=STEWARD)
    assert dis.status_code == 200 and dis.json()["result"]["carried_critical_failures"] == 2
    assert "CRITICAL_FAILURE_CARRIED" in {w["code"] for w in dis.json()["warnings"]}
    m = metrics(lab, as_of="2026-10-05T02:00:00Z")["data"]
    ws = m["metrics"]["weighted_score"]["datasets"]["ds-customers"]
    assert (ws["critical_failures"], ws["critical_override"]) == (2, True)
    assert m["metrics"]["critical_failures"]["carried"][0]["rule_run_id"] == run.json()["result"]["rule_run_id"]
    row = sql_metrics(conn, "2026-10-05T02:00:00Z")                                      # and the SQL reference says the same
    assert row["critical_failures"] == m["metrics"]["critical_failures"] and row["weighted_score"] == m["metrics"]["weighted_score"]


def test_r7_02_only_a_verified_rerun_clears_it_and_disabling_never_does(lab, conn):
    run = command(lab, "run-rule", {"rule_id": "r-cust-key-unique"}, headers=ANALYST).json()["result"]["rule_run_id"]
    clock.freeze(AS_OF + timedelta(hours=1))
    assert command(lab, "disable-rule", {"rule_id": "r-cust-key-unique", "reason": "noise"}, headers=STEWARD).status_code == 200
    iid = command(lab, "open-issue", {"rule_run_id": run, "owner_id": "own-02"}, headers=ANALYST).json()["result"]["issue_id"]
    assert command(lab, "triage-issue", {"issue_id": iid, "action": "claim"}, headers=ANALYST).status_code == 200
    clock.freeze(AS_OF + timedelta(hours=2))
    still = command(lab, "verify-remediation", {"issue_id": iid}, headers=STEWARD)       # nothing was repaired: the rerun fails, the disabled rule does not excuse it
    assert still.json()["status"] == "claimed" and still.json()["result"]["reasons"] == ["RERUN_STILL_FAILING"] and still.json()["result"]["rule_disabled"] is True
    at = "2026-10-05T03:00:00Z"
    clock.freeze(AS_OF + timedelta(hours=3))
    assert metrics(lab, as_of=at)["data"]["metrics"]["critical_failures"]["carried"][0]["rule_run_id"] != run          # the failing rerun is now the latest run
    assert metrics(lab, as_of=at)["data"]["metrics"]["critical_failures"]["failures"] >= 1
    fix = command(lab, "correct-dataset-rows", {"dataset_id": "ds-customers", "reason": "the duplicated keys were typing errors", "corrections": [
        {"row_id": "cust-061", "changes": {"customer_key": "CK-0061"}}, {"row_id": "cust-062", "changes": {"customer_key": "CK-0062"}}]}, headers=ANALYST)
    assert fix.status_code == 200, fix.text
    clock.freeze(AS_OF + timedelta(hours=4))
    ok = command(lab, "verify-remediation", {"issue_id": iid}, headers=STEWARD)
    assert ok.json()["status"] == "resolved" and ok.json()["result"]["failure_count"] == 0
    m = metrics(lab, as_of="2026-10-05T05:00:00Z")["data"]["metrics"]
    assert m["critical_failures"]["carried"] == [] and m["weighted_score"]["datasets"]["ds-customers"]["critical_failures"] == 0
    assert m["weighted_score"]["datasets"]["ds-customers"]["critical_override"] is True                 # iss-006 (the golden critical issue) is still open
    assert sql_metrics(conn, "2026-10-05T05:00:00Z")["critical_failures"] == m["critical_failures"]


# ---------------------------------------------------------------------------------------------------------- R7-04 patterns
@pytest.mark.parametrize("pattern", [r"^\s+$", r"^\d+$", r"^\w+$", r"\bx", r"^\S+$", r"^\D$", r"^\W$", r"a\B", r"[\s]", r"[^@\s]+@x", "a\\\\\\s"])
def test_r7_04_a_pattern_with_s_d_w_or_b_is_refused_at_ingest(pattern):
    d = golden_inputs()
    next(x for x in d["quality_rules"] if x["rule_id"] == "r-cust-valid-email")["definition"]["pattern"] = pattern
    out = run_pipeline(d).golden()
    rej = [(r["entity"], r["id"], r["reason_code"]) for r in out["ingest"]["rejected_records"] if r["entity"] == "quality_rules"]
    assert rej == [("quality_rules", "r-cust-valid-email", PATTERN_NOT_PORTABLE)] and not pattern_portable(pattern)
    assert "r-cust-valid-email" not in out["metrics"]["validity"]                         # the rule is not measured at all; its runs are DEPENDENT_REJECTED


@pytest.mark.parametrize("pattern", [r"^[ \t\r\n\f\v]*$", r"^[0-9]+$", r"^[A-Za-z0-9_]+$", r"a\\s", r"\.", r"^[^@ \t]+@[^@ \t]+$", r"\\"])
def test_r7_04_explicit_classes_and_an_escaped_backslash_are_portable(pattern):
    assert pattern_portable(pattern)


def test_r7_04_the_database_refuses_a_non_portable_pattern_too(conn):
    load(conn, golden_inputs())
    for p in (r"^\s+$", r"[\d]", r"x\bx"):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO quality_rules VALUES ('r-x', 'ds-customers', NULL, 'validity', 'low', 1, 'active', NULL, NULL, %s::jsonb)",
                         ('{"field": "email", "pattern": ' + __import__("json").dumps(p) + "}",))
    conn.execute("INSERT INTO quality_rules VALUES ('r-ok', 'ds-customers', NULL, 'validity', 'low', 1, 'active', NULL, NULL, %s::jsonb)",
                 ('{"field": "email", "pattern": "a\\\\\\\\s"}',))                       # an escaped backslash then an s


#: characters Python's \s, JavaScript's \s and PostgreSQL's \s used to disagree about (NBSP, BOM, NEL, line separator, file separator): ordinary
#: characters for the explicit class, so all three engines say "valid"
WHITESPACE_PROBES = {"U+00A0": " ", "U+FEFF": "﻿", "U+0085": "\u0085", "U+2028": " ", "U+001C": "\x1c"}


@pytest.mark.parametrize("name", sorted(WHITESPACE_PROBES))
def test_r7_04_whitespace_probes_python_and_sql_agree(conn, name):
    d = golden_inputs()
    d["dataset_rows"]["ds-customers"][4]["email"] = f"a{WHITESPACE_PROBES[name]}b@x.io"        # cust-005 failed (no @); now it is a valid e-mail by the explicit class
    m = agree(conn, d)
    v = m["validity"]["r-cust-valid-email"]
    assert (v["passing_count"], v["populated_only"]["value"]) == (91, "0.957895")


@pytest.mark.parametrize("email,passes", [("ab@x.io\n", False), ("ab@x.io\r", False), ("ab@x.io ", False), ("a b@x.io", False), ("a\tb@x.io", False),
                                          ("a\x0bb@x.io", False), ("a\x0cb@x.io", False), ("ab@x.ıo", False), ("ab＠x.io", False)])
def test_r7_04_ascii_whitespace_and_a_trailing_newline_still_fail_and_agree(conn, email, passes):
    d = golden_inputs()
    d["dataset_rows"]["ds-customers"][0]["email"] = email
    v = agree(conn, d)["validity"]["r-cust-valid-email"]
    assert v["passing_count"] == (90 if passes else 89)


# ---------------------------------------------------------------------------------------------------------- R7-05 / R7-11 / R7-06
def test_r7_05_null_keys_fail_are_listed_and_lower_the_score(conn):
    d = golden_inputs()
    d["dataset_rows"]["ds-customers"][0]["customer_key"] = None
    d["dataset_rows"]["ds-customers"][1]["customer_key"] = "   "
    m = agree(conn, d)
    u = m["uniqueness"]["r-cust-key-unique"]
    assert (u["null_key_count"], u["null_key_row_ids"], u["duplicate_rows"], u["distinct_keys"]) == (2, ["cust-001", "cust-002"], 2, 96)
    assert m["weighted_score"]["datasets"]["ds-customers"]["dimension_scores"]["uniqueness"] == "0.960000"      # (100 - 2 - 2) / 100
    assert u["row_share"]["value"] == "0.020000" and m["critical_failures"]["failures"] == 4          # nulls fail the critical rule too


def test_r7_05_the_golden_figure_by_rows_is_unchanged():
    u = run_pipeline(golden_inputs()).metrics
    assert u["uniqueness"]["r-cust-key-unique"]["null_key_row_ids"] == []
    assert u["weighted_score"]["datasets"]["ds-customers"]["dimension_scores"]["uniqueness"] == "0.980000"


@pytest.mark.parametrize("fk,missing", [("", True), ("  ", True), ("\t \n", True), (None, True), ("CK-0001", False), (1, False)])
def test_r7_11_empty_and_whitespace_foreign_keys_are_missing_and_counted_with_the_nulls(conn, fk, missing):
    d = golden_inputs()
    d["dataset_rows"]["ds-orders"][0]["customer_key"] = fk                                  # ord-001 matched CK-0001
    m = agree(conn, d)
    r = m["relationship_integrity"]["r-ord-cust-fk"]
    want = (3 + (1 if missing else 0), 1 + (1 if isinstance(fk, str) and missing else 0))      # the golden has 3 missing (2 null + 1 empty), 1 of them empty text
    assert (r["null_fk_count"], r["empty_fk_count"]) == want
    if not missing:
        assert r["eligible_count"] == 37 and r["matched_count"] == (35 if fk == "CK-0001" else 34)        # the integer 1 is the text "1": it is no customer key


def test_r7_06_an_edge_from_a_dataset_to_itself_is_rejected_and_the_seeder_does_not_abort(conn):
    d = golden_inputs()
    d["lineage_edges"].append({"edge_id": "e-self", "source_dataset_id": "ds-orders", "target_dataset_id": "ds-orders", "evidence_type": "declared", "observed_at": None})
    d["lineage_edges"].append({"edge_id": "e-self-obs", "source_dataset_id": "ds-orders", "target_dataset_id": "ds-orders", "evidence_type": "observed",
                               "observed_at": "2026-10-01T00:00:00Z"})
    out = run_pipeline(d).golden()
    assert [(r["id"], r["reason_code"]) for r in out["ingest"]["rejected_records"]] == [("e-self", "MALFORMED_RECORD"), ("e-self-obs", "MALFORMED_RECORD")]
    res = load(conn, d)                                                                    # no IntegrityError: the domain refuses it before the database has to
    assert res["skipped"] == 2 and count(conn, "lineage_edges") == 14
    assert count(conn, "rejected_records", "entity = 'lineage_edges'") == 2
    with pytest.raises(psycopg.errors.CheckViolation):                                     # and the database would have refused it anyway
        conn.execute("INSERT INTO lineage_edges VALUES ('x', 'ds-orders', 'ds-orders', 'declared', NULL)")
    assert out["metrics"]["lineage_coverage"] == run_pipeline(golden_inputs()).metrics["lineage_coverage"]


# ---------------------------------------------------------------------------------------------------------- R7-14 reads
@pytest.mark.parametrize("path,params", [("/metrics", {"as_of": "2026-10-05T00:00:00"}), ("/metrics", {"as_of": "2026-10-05"}),
                                         ("/metrics", {"from": "2026-09-20T08:00:00", "to": "2026-09-25T10:00:00Z"}), ("/metrics", {"to": "2026-09-25"}),
                                         ("/data/identity_map", {"as_of": "2026-10-05T00:00:00"}), ("/data/rule_runs", {"from": "2026-09-20T08:00:00"}),
                                         ("/data/issues", {"to": "2026-09-25"})])
def test_r7_14_reads_refuse_instants_with_no_zone(lab, path, params):
    r = get(lab, path, **params)
    assert r.status_code == 422 and rule_ids(r) == ["TIMESTAMP_INVALID"], r.text
    ok = {k: v if v.endswith(("Z", "+00:00")) else v + "Z" for k, v in params.items() if "T" in v}
    if ok and len(ok) == len(params):
        assert get(lab, path, **ok).status_code == 200                                    # the same instants with a zone are fine


def test_r7_14_an_offset_is_accepted_and_means_the_same_instant(lab):
    a = metrics(lab, as_of="2026-10-05T01:00:00+01:00")["data"]
    b = metrics(lab, as_of="2026-10-05T00:00:00Z")["data"]
    assert a["as_of"] == b["as_of"] == "2026-10-05T00:00:00Z" and a["metrics"] == b["metrics"]


# ---------------------------------------------------------------------------------------------------------- R7-16 canonical order
def test_r7_16_canonical_order_compares_code_points(conn):
    """rec-Ａ (U+FF21, one UTF-16 unit) sorts before rec-😀 (U+1F600, a surrogate pair) by code point; UTF-16 order says the opposite."""
    d = golden_inputs()
    d["customer_records"] += [{"record_id": "rec-Ａ", "source_system": "s", "source_customer_id": "A", "normalized_name": "a", "address_key": "x"},
                              {"record_id": "rec-\U0001f600", "source_system": "s", "source_customer_id": "B", "normalized_name": "b", "address_key": "y"}]
    cand = {"candidate_id": "cand-900", "left_record_id": "rec-Ａ", "right_record_id": "rec-\U0001f600", "score": "0.500000", "features": {"f": "1.000000"},
            "explanation": "x", "uncertainty": None, "proposed_by": "own-01", "proposed_at": "2026-10-01T00:00:00Z"}
    d["match_candidates"].append(cand)
    out = run_pipeline(d).golden()
    assert [r for r in out["ingest"]["rejected_records"] if r["entity"] == "match_candidates"] == []
    assert load(conn, d)["skipped"] == 0                                                     # the database (COLLATE "C") agrees: this pair is canonical
    d["match_candidates"].append({**cand, "left_record_id": "rec-\U0001f600", "right_record_id": "rec-Ａ", "candidate_id": "cand-901"})
    again = run_pipeline(d).golden()
    assert [(r["id"], r["reason_code"]) for r in again["ingest"]["rejected_records"] if r["entity"] == "match_candidates"] == [("cand-901", "DUPLICATE_PAIR")]


# ---------------------------------------------------------------------------------------------------------- R7-07 C11 / C12
def completeness_issue(lab, who=ANALYST):
    """C03 run-rule -> C04 open-issue -> C05 claim on the completeness rule of the customers' e-mail (5 missing)."""
    run = command(lab, "run-rule", {"rule_id": "r-cust-complete-email"}, headers=who).json()["result"]
    assert (run["eligible_count"], run["failure_count"]) == (100, 5)
    iid = command(lab, "open-issue", {"rule_run_id": run["rule_run_id"], "owner_id": "own-02"}, headers=who).json()["result"]["issue_id"]
    assert command(lab, "triage-issue", {"issue_id": iid, "action": "claim"}, headers=who).status_code == 200
    return iid


MISSING = ["cust-011", "cust-029", "cust-047", "cust-063", "cust-088"]       # the golden's five missing e-mails


def test_r7_07_a_completeness_issue_is_resolved_through_c11_then_c10_with_no_sql_outside_the_application(lab, conn):
    iid = completeness_issue(lab)
    clock.freeze(AS_OF + timedelta(hours=1))
    before = command(lab, "verify-remediation", {"issue_id": iid}, headers=STEWARD).json()
    assert before["status"] == "claimed" and before["result"]["reasons"] == ["RERUN_STILL_FAILING"] and (before["result"]["eligible_count"], before["result"]["failure_count"]) == (5, 5)
    originals = table_digest(conn, ["dataset_rows"])
    rows_before = conn.execute("SELECT dataset_id, ordinal, row_id, data FROM dataset_rows ORDER BY dataset_id, ordinal").fetchall()
    clock.freeze(AS_OF + timedelta(hours=2))
    fix = command(lab, "correct-dataset-rows", {"dataset_id": "ds-customers", "reason": "e-mail addresses recovered from the CRM export",
                                                "corrections": [{"row_id": rid, "changes": {"email": f"{rid.replace('-', '')}@example.test"}} for rid in MISSING]}, headers=ANALYST)
    assert fix.status_code == 200, fix.text
    res = fix.json()["result"]
    assert fix.json()["status"] == "corrected" and res["corrected_by"] == "own-01" and res["recorded_at"].startswith("2026-10-05T02:00:00")
    assert [(c["row_id"], c["row_version"], c["supersedes_row_id"]) for c in res["corrected"]] == [(rid, 2, f"{rid}@1") for rid in MISSING]
    assert fix.json()["warnings"][0]["code"] == "CORRECTION_IS_NOT_VERIFICATION"                    # a correction resolves nothing by itself
    assert {i["issue_id"]: i["class"] for i in get(lab, "/data/issues").json()["data"]}[iid] == "claimed"
    # append-only: five new rows, the originals untouched, and the history of measurement is as it was
    assert count(conn, "dataset_rows") == 140 + 5 and conn.execute(
        "SELECT dataset_id, ordinal, row_id, data FROM dataset_rows WHERE row_version = 1 ORDER BY dataset_id, ordinal").fetchall() == rows_before
    v2 = conn.execute("SELECT * FROM dataset_rows WHERE row_id = 'cust-011' AND row_version = 2").fetchone()
    assert (v2["supersedes_row_id"], v2["reason"], v2["corrected_by"]) == ("cust-011@1", "e-mail addresses recovered from the CRM export", "own-01") and v2["data"]["email"] == "cust011@example.test"
    assert v2["recorded_at"] == AS_OF + timedelta(hours=2, milliseconds=2) or v2["recorded_at"].isoformat().startswith("2026-10-05T02:00:00")
    assert table_digest(conn, ["dataset_rows"]) != originals
    for sql in ("UPDATE dataset_rows SET data = '{}'::jsonb WHERE row_id = 'cust-011'", "DELETE FROM dataset_rows WHERE row_id = 'cust-011' AND row_version = 2"):
        with pytest.raises(psycopg.errors.IntegrityError):
            conn.execute(sql)
    clock.freeze(AS_OF + timedelta(hours=3))
    ok = command(lab, "verify-remediation", {"issue_id": iid}, headers=STEWARD)
    assert ok.status_code == 200 and ok.json()["status"] == "resolved" and ok.json()["result"]["verified"] is True
    assert (ok.json()["result"]["eligible_count"], ok.json()["result"]["failure_count"]) == (5, 0)
    assert {i["issue_id"]: i["class"] for i in get(lab, "/data/issues").json()["data"]}[iid] == "resolved"
    # the measurement uses the latest version of each record, as of each instant; the SQL reference reads the same rows
    now = metrics(lab, as_of="2026-10-05T04:00:00Z")["data"]["metrics"]["completeness"]["r-cust-complete-email"]
    then = metrics(lab, as_of="2026-10-05T01:00:00Z")["data"]["metrics"]["completeness"]["r-cust-complete-email"]
    assert (now["missing_count"], now["value"]) == (0, "1.000000") and (then["missing_count"], then["value"]) == (5, "0.950000")
    for at in ("2026-10-05T04:00:00Z", "2026-10-05T01:00:00Z"):
        assert sql_metrics(conn, at)["completeness"] == metrics(lab, as_of=at)["data"]["metrics"]["completeness"]
    stored = conn.execute("SELECT count(*) AS n, min(failure_count) AS lo FROM rule_runs WHERE rerun_for_issue = %s", (iid,)).fetchone()
    assert stored["n"] == 2                                                                  # the failing rerun is kept beside the passing one


def test_r7_07_a_record_corrected_twice_has_a_chain_of_versions(lab, conn):
    for n, value in enumerate(("a@x.io", "b@x.io"), start=1):
        clock.freeze(AS_OF + timedelta(hours=n))
        r = command(lab, "correct-dataset-rows", {"dataset_id": "ds-customers", "reason": f"round {n}", "corrections": [{"row_id": "cust-011", "changes": {"email": value}}]}, headers=STEWARD)
        assert r.status_code == 200 and r.json()["result"]["corrected"][0]["row_version"] == n + 1 and r.json()["warnings"]
    chain = conn.execute("SELECT row_version, supersedes_row_id, data ->> 'email' AS email FROM dataset_rows WHERE row_id = 'cust-011' ORDER BY row_version").fetchall()
    assert [(c["row_version"], c["supersedes_row_id"], c["email"]) for c in chain] == [(1, None, None), (2, "cust-011@1", "a@x.io"), (3, "cust-011@2", "b@x.io")]
    assert metrics(lab, as_of="2026-10-05T01:30:00Z")["data"]["metrics"]["completeness"]["r-cust-complete-email"]["missing_count"] == 4         # version 2 (a valid e-mail)
    assert get(lab, "/data/dataset_rows", row_id="cust-011").json()["meta"]["total_count"] == 3


@pytest.mark.parametrize("body,status,code", [
    ({"corrections": [{"row_id": "cust-999", "changes": {"email": "x@y.io"}}]}, 422, "UNKNOWN_ROW"),
    ({"corrections": [{"row_id": "cust-011", "changes": {"row_id": "cust-012"}}]}, 422, "ROW_ID_IMMUTABLE"),
    ({"corrections": [{"row_id": "cust-001", "changes": {"email": "customer001@example.test"}}]}, 422, "NO_CHANGE"),
    ({"corrections": [{"row_id": "cust-011", "changes": {"email": "a@b.io"}}, {"row_id": "cust-011", "changes": {"email": "c@d.io"}}]}, 422, "DUPLICATE_ROW"),
    ({"corrections": [{"row_id": "cust-011", "changes": {"email": {"nested": 1}}}]}, 422, "FIELD_INVALID"),
    ({"corrections": [{"row_id": "cust-011", "changes": {"email": 1.5}}]}, 422, "FIELD_INVALID"),
    ({"corrections": []}, 422, "FIELD_INVALID"),
    ({"corrections": [{"row_id": "cust-011", "changes": {}}]}, 422, "FIELD_INVALID"),
    ({"reason": " "}, 422, "REASON_REQUIRED"),
    ({"dataset_id": "ds-nope"}, 404, "DATASET_UNKNOWN")])
def test_r7_07_c11_hard_validation_writes_nothing(lab, conn, body, status, code):
    base = {"dataset_id": "ds-customers", "reason": "fix", "corrections": [{"row_id": "cust-011", "changes": {"email": "a@b.io"}}]}
    before = table_digest(conn, ["dataset_rows", "audit_events", "command_results"])
    r = command(lab, "correct-dataset-rows", {**base, **body}, headers=ANALYST)
    assert r.status_code == status and code in rule_ids(r), r.text
    assert table_digest(conn, ["dataset_rows", "audit_events", "command_results"]) == before


def test_r7_07_c11_audit_idempotency_and_the_relationship_parent(lab, conn):
    body = {"dataset_id": "ds-customers", "reason": "retire a key", "corrections": [{"row_id": "cust-001", "changes": {"customer_key": "CK-1001"}}]}
    first = command(lab, "correct-dataset-rows", body, key="c11-idem", headers=ANALYST)
    assert first.status_code == 200
    replay = command(lab, "correct-dataset-rows", body, key="c11-idem", headers=ANALYST)
    assert replay.json() == first.json() and count(conn, "dataset_rows", "row_id = 'cust-001'") == 2
    a = conn.execute("SELECT * FROM audit_events WHERE action = 'correct-dataset-rows'").fetchall()
    assert len(a) == 1 and a[0]["actor_id"] == "own-01" and a[0]["reason"] == "retire a key" and a[0]["details"]["rows"] == ["cust-001"]
    # ord-001 pointed at CK-0001, which no longer exists as a customer key: the relationship rule reads the corrected parent rows
    run = command(lab, "run-rule", {"rule_id": "r-ord-cust-fk"}, headers=ANALYST).json()["result"]
    assert (run["eligible_count"], run["failure_count"]) == (37, 3)
    assert command(lab, "correct-dataset-rows", body, headers=INACTIVE).status_code == 403


def test_r7_07_c12_records_a_refresh_and_timeliness_follows_it_through_the_api_alone(lab, conn):
    """The reviewer's case without a line of SQL: ds-customers (New York 06:00, grace 60) at 10:30Z, refreshed 10:10Z."""
    at = "2026-10-05T10:30:00Z"
    before = metrics(lab, as_of=at)["data"]["metrics"]["timeliness"]
    assert before["datasets"]["ds-customers"]["state"] == "pending" and before["pending_count"] == 1
    clock.freeze(parse_ts(at))
    r = command(lab, "record-refresh", {"dataset_id": "ds-customers", "refreshed_at": "2026-10-05T10:10:00Z"}, headers=ANALYST)
    assert r.status_code == 200 and r.json()["status"] == "recorded" and r.json()["result"]["last_refreshed_at"] == "2026-10-05T10:10:00Z"
    after = metrics(lab, as_of=at)["data"]["metrics"]["timeliness"]
    assert after["datasets"]["ds-customers"]["state"] == "on_time" and after["datasets"]["ds-customers"]["last_refreshed_at"] == "2026-10-05T10:10:00Z"
    assert (after["pending_count"], after["evaluated_datasets"]) == (0, 4)
    early = metrics(lab, as_of="2026-10-05T10:05:00Z")["data"]["metrics"]["timeliness"]["datasets"]["ds-customers"]      # history: before it happened it was not there
    assert (early["state"], early["last_refreshed_at"]) == ("pending", "2026-10-04T10:20:00Z")
    assert sql_metrics(conn, at)["timeliness"] == after
    assert sql_metrics(conn, "2026-10-05T10:05:00Z")["timeliness"]["datasets"]["ds-customers"] == early
    rule = command(lab, "run-rule", {"rule_id": "r-cust-fresh"}, headers=ANALYST).json()["result"]
    assert (rule["eligible_count"], rule["failure_count"]) == (1, 0)                          # the rule run reads the same history
    assert get(lab, "/data/dataset_refreshes", dataset_id="ds-customers").json()["data"][0]["recorded_by"] == "own-01"


@pytest.mark.parametrize("body,status,code", [
    ({"refreshed_at": "2026-10-06T00:00:00Z"}, 422, "REFRESH_IN_FUTURE"),
    ({"refreshed_at": "2026-05-31T23:59:59Z"}, 422, "REFRESH_BEFORE_REGISTRATION"),
    ({"refreshed_at": "2026-10-04T12:00:00"}, 422, "TIMESTAMP_INVALID"),
    ({"refreshed_at": "yesterday"}, 422, "TIMESTAMP_INVALID"),
    ({"dataset_id": "ds-nope", "refreshed_at": "2026-10-04T12:00:00Z"}, 404, "DATASET_UNKNOWN")])
def test_r7_07_c12_validation_writes_nothing(lab, conn, body, status, code):
    before = table_digest(conn, ["dataset_refreshes", "audit_events"])
    r = command(lab, "record-refresh", {"dataset_id": "ds-customers", "refreshed_at": "2026-10-04T12:00:00Z", **body}, headers=ANALYST)
    assert r.status_code == status and code in rule_ids(r), r.text
    assert table_digest(conn, ["dataset_refreshes", "audit_events"]) == before


def test_r7_07_c12_a_repeated_refresh_is_409_and_the_history_cannot_be_edited(lab, conn):
    body = {"dataset_id": "ds-customers", "refreshed_at": "2026-10-04T12:00:00Z"}
    assert command(lab, "record-refresh", body, headers=ANALYST).status_code == 200
    again = command(lab, "record-refresh", body, headers=STEWARD)
    assert again.status_code == 409 and rule_ids(again) == ["REFRESH_EXISTS"]
    for sql in ("UPDATE dataset_refreshes SET refreshed_at = now()", "DELETE FROM dataset_refreshes"):
        with pytest.raises(psycopg.errors.IntegrityError):
            conn.execute(sql)
    unmonitored = command(lab, "record-refresh", {"dataset_id": "ds-products", "refreshed_at": "2026-10-04T12:00:00Z"}, headers=ANALYST)
    assert unmonitored.status_code == 200 and unmonitored.json()["warnings"][0]["code"] == "NOT_MONITORED"


# ---------------------------------------------------------------------------------------------------------- R7-12 rule versions and metric lifecycle
def test_r7_12_every_rule_version_has_its_definition_and_the_reads_expose_it(lab, conn):
    rows = get(lab, "/data/quality_rule_versions", limit=200).json()["data"]
    assert len(rows) == 9 and {(r["rule_id"], r["version_number"]) for r in rows} >= {("r-cust-valid-email", 2)}
    one = get(lab, "/data/quality_rule_versions", rule_id="r-cust-valid-email").json()["data"]
    assert one[0]["definition"]["pattern"].startswith("^[^@ ") and one[0]["rule_type"] == "validity"
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("UPDATE quality_rule_versions SET definition = '{}'::jsonb")
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute("DELETE FROM quality_rule_versions")


def test_r7_12_an_earlier_versions_denominator_is_readable_in_the_generated_world(conn):
    """The generator states every earlier version. The INJ-12 rule changed to version 2 (a filter) after its last run: the stored run's 'eligible'
    is the version-1 denominator, and measuring the version-1 definition today reproduces it, while the current definition does not."""
    import importlib.util
    import sys
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("tl_generate_r7", root / "data" / "generate.py")
    gen = importlib.util.module_from_spec(spec)
    sys.modules["tl_generate_r7"] = gen
    spec.loader.exec_module(gen)
    w = gen.build(20261026)
    inputs = {**copy.deepcopy(w.ents), **gen.to_inputs(w.ents)}
    load(conn, gen.to_inputs(w.ents), dataset_version="tl-r7")
    rule = w.inj12_rule
    versions = {r["version_number"]: r for r in conn.execute("SELECT * FROM quality_rule_versions WHERE rule_id = %s", (rule.rule_id,)).fetchall()}
    assert sorted(versions) == [1, 2] and "filter" not in versions[1]["definition"] and versions[2]["definition"]["filter"] == {"field": "status", "equals": "active"}
    last = conn.execute("SELECT eligible_count, rule_version FROM rule_runs WHERE rule_id = %s AND kind = 'scheduled' ORDER BY run_at DESC LIMIT 1", (rule.rule_id,)).fetchone()
    assert last["rule_version"] == 1
    from dataclasses import replace
    from api import db
    from trustledger.measure import measure_rule
    pop = db.load_population(conn, parse_ts("2026-10-05T00:00:00Z"))
    stored = next(r for r in pop.quality_rules if r.rule_id == rule.rule_id)
    assert stored.version_number == 2 and stored.definition == versions[2]["definition"]                 # the rule's own row is the current version
    as_v1 = measure_rule(replace(stored, definition=versions[1]["definition"], version_number=1), pop, parse_ts("2026-10-05T00:00:00Z"))
    as_v2 = measure_rule(stored, pop, parse_ts("2026-10-05T00:00:00Z"))
    assert as_v1.eligible == last["eligible_count"] == 65 and as_v2.eligible == 54          # the version-1 denominator is readable; the current one differs


def test_r7_12_the_valid_from_of_a_version_is_the_day_of_its_first_run(conn):
    from fractions import Fraction  # noqa: F401
    import importlib.util
    import sys
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("tl_generate_r7b", root / "data" / "generate.py")
    gen = importlib.util.module_from_spec(spec)
    sys.modules["tl_generate_r7b"] = gen
    spec.loader.exec_module(gen)
    w = gen.build(20261026)
    by = {}
    for v in w.ents["quality_rule_versions"]:
        by.setdefault(v["rule_id"], []).append(v)
    runs = {}
    for r in w.ents["rule_runs"]:
        runs.setdefault((r["rule_id"], r["rule_version"]), []).append(r["run_at"])
    for rid, vs in by.items():
        assert [v["version_number"] for v in vs] == list(range(1, len(vs) + 1))
        for v in vs:
            first = min(runs.get((rid, v["version_number"]), ["9999"]))
            assert first == "9999" or first[:10] >= v["valid_from"][:10], (rid, v["version_number"])


def test_r7_07_the_new_reads_page_with_a_stable_cursor(lab):
    for hour in (3, 1, 2):                                  # recorded out of order: the read orders by instant
        assert command(lab, "record-refresh", {"dataset_id": "ds-customers", "refreshed_at": f"2026-10-04T{12 + hour:02d}:00:00Z"}, headers=ANALYST).status_code == 200
    first = get(lab, "/data/dataset_refreshes", dataset_id="ds-customers", limit=2).json()
    assert [r["refreshed_at"] for r in first["data"]] == ["2026-10-04T13:00:00Z", "2026-10-04T14:00:00Z"] and first["meta"]["next_cursor"]
    second = get(lab, "/data/dataset_refreshes", dataset_id="ds-customers", limit=2, cursor=first["meta"]["next_cursor"]).json()
    assert [r["refreshed_at"] for r in second["data"]] == ["2026-10-04T15:00:00Z"] and second["meta"]["next_cursor"] is None
    seen, cursor = [], None
    while True:
        page = get(lab, "/data/quality_rule_versions", limit=4, cursor=cursor).json()
        seen += [(r["rule_id"], r["version_number"]) for r in page["data"]]
        cursor = page["meta"]["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 9 and seen == sorted(seen)


def test_r7_migration_0003_constraints(conn):
    load(conn, golden_inputs())
    ins = "INSERT INTO dataset_rows (dataset_id, ordinal, row_id, data, row_version, supersedes_row_id, reason, corrected_by, recorded_at) VALUES ('ds-customers', %s, 'cust-001', '{}'::jsonb, %s, %s, %s, %s, %s)"
    bad = [(900, 2, None, "x", "o", "2026-10-01T00:00:00Z"),                 # a later version must name what it supersedes
           (901, 2, "cust-001@9", "x", "o", "2026-10-01T00:00:00Z"),         # ... the version just before it
           (902, 2, "cust-001@1", " ", "o", "2026-10-01T00:00:00Z"),         # ... with a reason
           (903, 2, "cust-001@1", "x", None, "2026-10-01T00:00:00Z"),        # ... by someone
           (904, 2, "cust-001@1", "x", "o", None),                           # ... at an instant
           (905, 1, "cust-001@0", "x", "o", "2026-10-01T00:00:00Z")]         # a first version supersedes nothing
    for args in bad:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(ins, args)
    conn.execute(ins, (906, 2, "cust-001@1", "x", "o", "2026-10-01T00:00:00Z"))
    with pytest.raises(psycopg.errors.UniqueViolation):                      # one row per (dataset, record, version)
        conn.execute(ins, (907, 2, "cust-001@1", "x", "o", "2026-10-01T00:00:00Z"))
    mv = "INSERT INTO metric_versions (metric_version_id, metric_id, metric_name, version_number, valid_from, status) VALUES (%s, 'm-x', 'X', %s, now(), %s)"
    for n, status in enumerate(("draft", "reviewed", "published"), start=1):
        conn.execute(mv, (f"mv-x-{n}", n, status))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(mv, ("mv-x-4", 4, "approved"))
    with pytest.raises(psycopg.errors.IntegrityError):                       # a refresh needs a dataset
        conn.execute("INSERT INTO dataset_refreshes VALUES ('ds-nope', now(), now(), 'o')")
