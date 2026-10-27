"""Domain rules one by one (pure Python, no database): classification, checkpoints, pagination, backfills, the gate, reconciliation, late events,
verified recovery, schema change and delete events. The fixtures with no golden inputs (pagination, schema change, deletes) live under tests/fixtures/."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pipeline_observatory import DomainError, run_pipeline
from pipeline_observatory.backfill import check_range, find_overlap, ranges_overlap
from pipeline_observatory.classify import ACCEPTED, DELETED, DUPLICATE, QUARANTINED, classify_rows, contract_reason, money_amount, next_checkpoint_version
from pipeline_observatory.fetch import Page, check_cursor_progress, check_retry_allowed, fetch_all
from pipeline_observatory.gate import decide, may_publish
from pipeline_observatory.hashing import payload_hash
from pipeline_observatory.metrics import derive
from pipeline_observatory.numbers import m4, money, p6, ratio, rnd
from pipeline_observatory.reconcile import late_events, reconcile, verified_recovery
from pipeline_observatory.timeutil import day_partitions, parse_ts

from support_db import diff, fixture_json, golden_expected, golden_inputs


def row(n, key, **payload):
    base = {"record_id": key, "quantity": 1, "unit_price": "1.00", "amount": "1.00", "event_ts": "2026-10-04T08:00:00Z"}
    base.update(payload)
    base = {k: v for k, v in base.items() if v is not ...}
    return {"raw_record_id": f"rr-{n:03d}", "source_key": key, "payload_json": base}


def kinds(rows, accepted=None, deleted=None, schema_ok=True):
    return [(d.kind, d.reason) for d in classify_rows(rows, accepted if accepted is not None else set(), deleted, schema_ok)]


# ------------------------------------------------------------------------------------------------ classification (D-01, D-P8-01)
def test_key_check_runs_before_the_contract_check():
    seen = {"A"}
    assert kinds([row(1, "A", quantity=-5)], seen) == [(DUPLICATE, None)]                   # a known key is a duplicate even if this copy is invalid
    assert kinds([row(1, "B", quantity=-5)], seen) == [(QUARANTINED, "NEGATIVE_QUANTITY")]    # an unknown key: the contract decides


def test_a_changed_payload_under_a_known_key_is_still_a_duplicate_there_is_no_changed_class():
    assert kinds([row(1, "A"), row(2, "A", amount="9.99", unit_price="9.99")]) == [(ACCEPTED, None), (DUPLICATE, None)]


def test_a_replayed_invalid_row_is_quarantined_again_once_per_occurrence():
    bad = row(1, "X", quantity=-1)
    assert kinds([bad, {**bad, "raw_record_id": "rr-002"}]) == [(QUARANTINED, "NEGATIVE_QUANTITY")] * 2


def test_an_invalid_first_copy_does_not_block_a_later_valid_copy_of_the_key():
    assert kinds([row(1, "K", quantity=-1), row(2, "K")]) == [(QUARANTINED, "NEGATIVE_QUANTITY"), (ACCEPTED, None)]


@pytest.mark.parametrize("field", ["record_id", "quantity", "unit_price", "amount", "event_ts"])
def test_a_missing_required_field_is_quarantined_never_dropped(field):
    r = row(1, "M", **{field: ...})
    assert kinds([r]) == [(QUARANTINED, "MISSING_FIELD")]


def test_a_null_required_field_and_a_row_without_a_key_are_quarantined_not_dropped():
    assert kinds([row(1, "N", amount=None)]) == [(QUARANTINED, "MISSING_FIELD")]
    nokey = {"raw_record_id": "rr-001", "source_key": None, "payload_json": {"quantity": 1}}
    assert kinds([nokey]) == [(QUARANTINED, "MISSING_FIELD")]


@pytest.mark.parametrize("patch,reason", [({"quantity": 1.5}, "INVALID_FIELD"), ({"quantity": "2"}, "INVALID_FIELD"), ({"quantity": True}, "INVALID_FIELD"),
                                          ({"amount": "12.345"}, "INVALID_FIELD"), ({"unit_price": 3}, "INVALID_FIELD"), ({"event_ts": "yesterday"}, "INVALID_FIELD"),
                                          ({"event_ts": "2026-10-04T08:00:00"}, "INVALID_FIELD"), ({"quantity": -1}, "NEGATIVE_QUANTITY"), ({"quantity": 0}, None)])
def test_contract_reasons(patch, reason):
    assert contract_reason(row(1, "C", **patch)["payload_json"]) == reason


def test_every_row_has_exactly_one_disposition_nothing_is_dropped():
    rows = [row(1, "A"), row(2, "A"), row(3, "B", quantity=-1), row(4, "C", amount=...), row(5, "D")]
    d = classify_rows(rows, set())
    assert [x.raw_record_id for x in d] == [r["raw_record_id"] for r in rows] and len(d) == 5


def test_rows_are_taken_in_raw_record_id_order_whatever_the_input_order():
    a, b = row(1, "A"), row(2, "A")
    assert kinds([b, a]) == [(ACCEPTED, None), (DUPLICATE, None)]


def test_classification_is_idempotent_replaying_a_batch_never_adds_accepted_records():
    keys: set[str] = set()
    rows = [row(i, f"K{i}") for i in range(1, 9)]
    first = classify_rows(rows, keys)
    again = classify_rows(rows, keys)
    assert [d.kind for d in first] == [ACCEPTED] * 8 and [d.kind for d in again] == [DUPLICATE] * 8 and len(keys) == 8


# ------------------------------------------------------------------------------------------------ checkpoints (D-01, D-P8-11)
def test_checkpoint_version_must_be_previous_plus_one():
    assert next_checkpoint_version(0, 1) == 1 and next_checkpoint_version(2, 3) == 3
    for prev, version, code in ((2, 2, "CHECKPOINT_REGRESSION"), (2, 1, "CHECKPOINT_REGRESSION"), (0, 0, "CHECKPOINT_REGRESSION"), (2, 4, "CHECKPOINT_GAP"), (0, 2, "CHECKPOINT_GAP")):
        with pytest.raises(DomainError) as e:
            next_checkpoint_version(prev, version)
        assert e.value.code == code and e.value.details == {"committed_version": prev, "requested_version": version}
    with pytest.raises(DomainError) as e:
        next_checkpoint_version(1, True)
    assert e.value.code == "INVALID_FIELD"


def test_a_checkpoint_gap_in_an_import_rejects_the_batch_and_its_rows():
    d = golden_inputs()
    d["checkpoints"][1]["version_number"] = 5                                                 # cp-002 skips 2, 3, 4
    res = run_pipeline(d)
    got = {(r["entity"], r["id"]): r["reason_code"] for r in res.rejected}
    assert got[("checkpoints", "cp-002")] == "CHECKPOINT_GAP" and got[("ingestion_batches", "b-002")] == "DEPENDENT_REJECTED" and got[("raw_records", "rr-b-002-01")] == "DEPENDENT_REJECTED"
    assert res.metrics["ingestion"]["sources"]["src-orders"]["received"] == 10 and res.metrics["ingestion"]["sources"]["src-orders"]["checkpoint"]["committed_version"] == 1


# ------------------------------------------------------------------------------------------------ pagination (P08-TEST-03, P08-TEST-10)
class Transport:
    """A synthetic paginated source driven by a fixture. It records every request with the (fake) instant and counts a request made before the
    previous retry-after elapsed as a violation."""

    def __init__(self, fx):
        self.script = {k: list(v) for k, v in fx["responses"].items()}
        self.now = datetime(2026, 10, 4, 8, 0, 0, tzinfo=timezone.utc)
        self.not_before: dict[str, datetime] = {}
        self.violations: list[tuple[str, datetime]] = []
        self.requests: list[tuple[str, datetime]] = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)

    def __call__(self, cursor):
        self.requests.append((cursor, self.now))
        if cursor in self.not_before and self.now < self.not_before[cursor]:
            self.violations.append((cursor, self.now))
            return Page(429, retry_after_seconds=30)
        queue = self.script[cursor]
        r = queue.pop(0) if len(queue) > 1 else queue[0]
        if r["status"] == 429:
            self.not_before[cursor] = self.now + timedelta(seconds=r["retry_after_seconds"])
        return Page(r["status"], tuple(r.get("records", [])), r.get("next_cursor"), r.get("retry_after_seconds"))


def test_p08_test_03_retries_honour_retry_after_and_never_come_sooner():
    fx = fixture_json("pagination/rate_limited.json")
    t = Transport(fx)
    res = fetch_all(t, fx["start"], t.clock, t.sleep)
    assert (len(res.records), res.cursors, res.waits, len(t.requests)) == (fx["expected"]["records"], fx["expected"]["cursors"], fx["expected"]["waits"], fx["expected"]["requests"])
    assert t.violations == []                                                                 # not one request before its retry-after
    c1 = [at for cur, at in t.requests if cur == "c1"]
    assert [(b - a).total_seconds() for a, b in zip(c1, c1[1:])] == [30, 30]                  # each retry exactly one retry-after later


def test_p08_test_03_a_client_that_ignores_retry_after_is_caught_by_the_same_transport():
    fx = fixture_json("pagination/rate_limited.json")
    t = Transport(fx)
    t.sleep = lambda s: None                                                                  # the defect: retry at once
    with pytest.raises(DomainError) as e:
        fetch_all(t, fx["start"], t.clock, t.sleep, max_retries=3)
    assert e.value.code == "RETRY_EXHAUSTED" and len(t.violations) >= 1


def test_the_retry_check_refuses_a_retry_before_the_hint_and_accepts_it_at_the_hint():
    t0 = datetime(2026, 10, 4, 8, 0, 0, tzinfo=timezone.utc)
    check_retry_allowed(t0, 30, t0 + timedelta(seconds=30))
    with pytest.raises(DomainError) as e:
        check_retry_allowed(t0, 30, t0 + timedelta(seconds=29, milliseconds=500))
    assert e.value.code == "RETRY_TOO_SOON" and e.value.details == {"retry_after_seconds": 30, "remaining_seconds": 1}


@pytest.mark.parametrize("name", ["cursor_loop", "self_loop"])
def test_p08_test_10_a_repeating_cursor_stops_the_fetch_with_cursor_loop(name):
    fx = fixture_json(f"pagination/{name}.json")
    t = Transport(fx)
    with pytest.raises(DomainError) as e:
        fetch_all(t, fx["start"], t.clock, t.sleep)
    assert e.value.code == fx["expected"]["code"] == "CURSOR_LOOP" and len(t.requests) == fx["expected"]["pages_before_stop"]     # it stops, it does not spin


def test_cursor_progress_accepts_new_cursors_and_the_end_of_the_feed():
    check_cursor_progress("c0", "c1", {"c0"})
    check_cursor_progress("c1", None, {"c0", "c1"})
    with pytest.raises(DomainError):
        check_cursor_progress("c2", "c0", {"c0", "c1", "c2"})


# ------------------------------------------------------------------------------------------------ backfills (D-03, D-P8-11)
def bf(i, s, e, src="src-orders"):
    return {"backfill_id": f"bf-{i:03d}", "source_id": src, "start_at": f"{s}T00:00:00Z", "end_at": f"{e}T00:00:00Z"}


def test_ranges_are_half_open_touching_ranges_do_not_overlap():
    assert not ranges_overlap("2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z", "2026-09-04T00:00:00Z", "2026-09-05T00:00:00Z")
    assert ranges_overlap("2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z", "2026-09-03T00:00:00Z", "2026-09-06T00:00:00Z")
    assert ranges_overlap("2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z", "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z")            # contained
    assert ranges_overlap("2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z", "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z")            # containing
    assert not ranges_overlap("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z")


def test_overlap_is_judged_per_source_against_earlier_accepted_requests():
    accepted = [bf(1, "2026-09-01", "2026-09-04")]
    assert find_overlap(accepted, bf(2, "2026-09-03", "2026-09-06"))["backfill_id"] == "bf-001"
    assert find_overlap(accepted, bf(3, "2026-09-04", "2026-09-05")) is None
    assert find_overlap(accepted, bf(4, "2026-09-03", "2026-09-06", src="src-refunds")) is None


def test_a_range_is_daily_utc_and_a_day_of_partitions_is_half_open():
    assert check_range("2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z") == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert day_partitions("2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z") == []
    for s, e, code in (("2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", "INVALID_RANGE"), ("2026-09-04T00:00:00Z", "2026-09-01T00:00:00Z", "INVALID_RANGE"),
                       ("2026-09-01T06:00:00Z", "2026-09-04T00:00:00Z", "PARTITION_ALIGNMENT"), ("2026-09-01T00:00:00Z", "2026-09-04T00:00:01Z", "PARTITION_ALIGNMENT")):
        with pytest.raises(DomainError) as exc:
            check_range(s, e)
        assert exc.value.code == code


# ------------------------------------------------------------------------------------------------ the gate (D-02, D-P8-08)
def q(i, rule, sev, eligible, failures):
    return {"quality_result_id": f"qr-{i}", "rule_name": rule, "severity": sev, "eligible_count": eligible, "failure_count": failures}


def test_gate_fails_closed():
    assert decide([])["decision"] == "blocked"                                                 # no result at all
    assert decide([q(1, "completeness", "warning", 9, 0)])["decision"] == "blocked"            # warnings only: no critical result exists
    assert decide([q(1, "keys_unique", "critical", 8, 1)])["decision"] == "blocked"
    assert decide([q(1, "keys_unique", "critical", 8, 0)])["decision"] == "allowed"


def test_a_failing_warning_never_blocks_and_a_failing_critical_always_does():
    ok = decide([q(1, "keys_unique", "critical", 8, 0), q(2, "completeness", "warning", 9, 1)])
    assert (ok["decision"], ok["critical_failures"], ok["noncritical_failures"]) == ("allowed", 0, 1)
    bad = decide([q(1, "keys_unique", "critical", 8, 0), q(2, "reconciliation_residual_zero", "critical", 1, 1), q(3, "completeness", "warning", 9, 0)])
    assert (bad["decision"], bad["critical_failures"]) == ("blocked", 1)


def test_a_check_passes_iff_its_failure_count_is_zero_and_the_latest_result_of_a_rule_counts():
    g = decide([q(1, "keys_unique", "critical", 8, 3), q(2, "keys_unique", "critical", 8, 0)])
    assert g["results"]["keys_unique"] == {"severity": "critical", "eligible": 8, "failures": 0, "passed": True} and g["decision"] == "allowed"


def test_the_pointer_moves_only_for_a_successful_allowed_published_run():
    assert may_publish("success", "allowed", True)
    assert not may_publish("failed", "allowed", True) and not may_publish("success", "blocked", True) and not may_publish("success", "allowed", False)
    assert not may_publish("running", "allowed", True)


def test_a_blocked_run_with_a_publication_row_still_never_moves_the_pointer():
    d = golden_inputs()
    d["publications"].append({**d["publications"][0], "publication_id": "pub-002", "run_id": "run-002", "published_at": "2026-10-04T12:30:00Z"})
    res = run_pipeline(d)
    assert [h["pointer_after"] for h in res.metrics["publications"]["pointer_history"]] == ["pub-001", "pub-001", "pub-003"]
    d["pipeline_runs"][1]["status"] = "success"                                                 # a success status does not rescue a blocked gate
    assert [h["pointer_after"] for h in run_pipeline(d).metrics["publications"]["pointer_history"]] == ["pub-001", "pub-001", "pub-003"]


# ------------------------------------------------------------------------------------------------ numbers (D-04)
def test_rounding_is_half_up_and_unknown_is_null():
    assert rnd(0.5 and ratio(1, 8), 2) == "0.13" and rnd(ratio(1, 3), 6) == "0.333333" and rnd(ratio(2, 3), 6) == "0.666667" and rnd(ratio(5, 1000), 2) == "0.01"
    assert p6(ratio(0, 4)) == "0.000000" and p6(ratio(1, 0)) is None and m4(None) is None and p6(None) is None
    assert rnd(ratio(-1, 8), 2) == "-0.13" and rnd(ratio(-1, 1000), 2) == "0.00"
    assert money(Decimal("289.945")) == "289.95" and money("0") == "0.00" and money(Decimal("-0.03")) == "-0.03"


def test_money_amount_is_exact_decimal_and_a_missing_amount_is_zero():
    assert money_amount({"amount": "29.97"}) == Decimal("29.97") and money_amount({}) == Decimal("0") and money_amount({"amount": "abc"}) == Decimal("0")
    assert sum((Decimal("0.1") for _ in range(10)), Decimal("0")) == Decimal("1.0")             # no binary float drift


# ------------------------------------------------------------------------------------------------ reconciliation, late events, recovery
def test_reconciliation_residual_is_nonzero_when_something_is_unexplained():
    src = [("accepted", Decimal("10.00")), ("duplicate", Decimal("10.00")), ("quarantined", Decimal("-5.00"))]
    pub = [type("A", (), {"amount": Decimal("10.00")})()]
    assert reconcile(src, pub, Decimal("0"), [])["residual"] == "0.00"
    assert reconcile(src, [type("A", (), {"amount": Decimal("9.99")})()], Decimal("0"), [])["residual"] == "0.01"          # a cent missing is a residual
    assert reconcile(src + [("accepted", Decimal("3.00"))], pub, Decimal("0"), [])["residual"] == "3.00"                   # an accepted row never published


def test_signs_matter_a_quarantined_negative_amount_is_a_negative_exclusion():
    r = reconcile([("accepted", Decimal("40.00")), ("quarantined", Decimal("-30.00"))], [type("A", (), {"amount": Decimal("40.00")})()], Decimal("0"), [])
    assert r["exclusions"]["quarantined"] == "-30.00" and r["exclusions_total"] == "-30.00" and r["source_total"] == "10.00" and r["residual"] == "0.00"


def test_p08_test_09_late_event_rules():
    base = golden_inputs()
    f = derive(__import__("pipeline_observatory").ingest.validate_import(base).accepted)
    assert [(e["source_key"], e["included_in_publication_id"]) for e in late_events(f.accepted, base["publications"])] == [("REF-2001", "pub-003")]
    # the event is later than the watermark: not late (it belongs to the next window)
    after = deepcopy(base)
    after["publications"][0]["watermark"] = "2026-10-04T09:00:00Z"
    assert run_pipeline(after).metrics["late_events"]["count"] == 0
    # it arrived before the publication: not late
    early = deepcopy(base)
    early["publications"][0]["published_at"] = "2026-10-04T11:30:00Z"
    early["pipeline_runs"][0]["finished_at"] = "2026-10-04T11:30:00Z"
    assert run_pipeline(early).metrics["late_events"]["count"] == 0
    # never lost: a late event no later publication includes is reported as lost, not hidden
    lost = deepcopy(base)
    lost["publications"][1]["included_batch_ids"] = ["b-001", "b-002"]
    m = run_pipeline(lost).metrics["late_events"]
    assert (m["count"], m["included_in_next_publication"], m["lost"], m["events"][0]["included_in_publication_id"]) == (1, 0, 1, None)


def test_recovery_is_the_first_verified_run_not_the_first_green_task_or_a_process_restart():
    runs = [{"run_id": "r1", "started_at": "2026-10-04T13:00:00Z", "status": "success"}, {"run_id": "r2", "started_at": "2026-10-04T14:00:00Z", "status": "success"}]
    gate = {"r1": "allowed", "r2": "allowed"}
    pubs = {"r1": "p1", "r2": "p2"}
    found = verified_recovery("2026-10-04T12:20:00Z", runs, gate, pubs, {"p1": "0.01", "p2": "0.00"})
    assert found["run"]["run_id"] == "r2"                                                      # r1 succeeded and published but its residual is not 0.00
    assert verified_recovery("2026-10-04T12:20:00Z", runs, gate, pubs, {"p1": "0.01", "p2": "0.01"}) is None
    assert verified_recovery("2026-10-04T12:20:00Z", runs, {"r1": "blocked", "r2": "blocked"}, pubs, {"p1": "0.00", "p2": "0.00"}) is None
    assert verified_recovery("2026-10-04T13:30:00Z", runs, gate, pubs, {"p1": "0.00", "p2": "0.00"})["run"]["run_id"] == "r2"      # r1 started before the detection


def test_a_closed_incident_that_disagrees_with_the_verified_recovery_is_inconsistent():
    d = golden_inputs()
    d["incidents"][0]["closed_at"] = "2026-10-04T20:00:00Z"
    assert run_pipeline(d).metrics["incidents"]["incidents"]["inc-001"]["closure_consistent"] is False
    d = golden_inputs()
    d["incidents"][0].update(status="open", closed_at=None, recovery_run_id=None)
    m = run_pipeline(d).metrics["incidents"]
    assert (m["open"], m["closed"], m["verified"]) == (1, 0, 1) and m["incidents"]["inc-001"]["closure_consistent"] is True     # verified recovery is known; closing is the operator's act


def test_an_incident_with_no_later_publishing_run_is_not_verified_and_has_no_recovery_time():
    d = golden_inputs()
    d["pipeline_runs"] = d["pipeline_runs"][:2]
    d["task_runs"] = [t for t in d["task_runs"] if t["run_id"] != "run-003"]
    d["quality_results"] = [x for x in d["quality_results"] if not x["quality_result_id"].startswith("qr-003")]
    d["publications"] = d["publications"][:1]
    d["incidents"][0].update(status="open", closed_at=None, recovery_run_id=None)
    i = run_pipeline(d).metrics["incidents"]
    assert i["verified"] == 0 and i["mean_recovery_minutes"] is None and i["incidents"]["inc-001"]["recovery_seconds"] is None and i["incidents"]["inc-001"]["verified"] is False


# ------------------------------------------------------------------------------------------------ schema change (P08-TEST-04) and deletes (P08-TEST-08)
def test_p08_test_04_a_batch_declaring_another_schema_version_is_quarantined_whole():
    fx = fixture_json("schema/schema_changed.json")
    rows = [{"raw_record_id": f"rr-{i:03d}", "source_key": r["payload"]["record_id"], "payload_json": r["payload"]} for i, r in enumerate(fx["records"], 1)]
    assert [d.reason for d in classify_rows(rows, set(), None, schema_ok=False)] == ["SCHEMA_CHANGED"] * 3
    assert [d.kind for d in classify_rows(rows, set(), None, schema_ok=True)] == [ACCEPTED] * 3          # after the explicit bump the same rows are accepted
    d = golden_inputs()
    d["ingestion_batches"][0]["schema_version"] = "2"                                                       # b-001 declares version 2, the contract expects 1
    m = run_pipeline(d).metrics["ingestion"]["sources"]["src-orders"]["batches"]["b-001"]
    assert (m["accepted_unique"], m["quarantined"], m["received"]) == (0, 10, 10) and m["quarantine_rows_match"] is False        # the recorded rows do not say SCHEMA_CHANGED
    d["source_contracts"][0]["schema_version"] = "2"                                                        # the explicit bump of the expected version
    assert run_pipeline(d).metrics["ingestion"]["sources"]["src-orders"]["batches"]["b-001"]["accepted_unique"] == 8


def test_p08_test_08_a_delete_event_propagates_to_the_published_snapshot_as_an_exclusion():
    d = fixture_json("deletes/deletes.json")
    want = d.pop("expected")
    res = run_pipeline(d)
    m = res.metrics
    b2 = m["ingestion"]["sources"]["src-orders"]["batches"]["b-2"]
    assert (b2["received"], b2["accepted_unique"], b2["duplicate"], b2["quarantined"]) == tuple(want["b-2"].values()) and b2["quarantine_rows_match"] is True
    pub, rec = m["publications"]["publications"]["pub-1"], m["reconciliation"]["pub-1"]
    assert pub["published_records"] == want["publication"]["published_records"] == 2 and pub["content_hash_ok"] is True      # D-2 left the snapshot
    assert (rec["source_total"], rec["published_total"], rec["exclusions"], rec["residual"]) == (want["publication"]["source_total"], want["publication"]["published_total"],
                                                                                              want["publication"]["exclusions"], "0.00")
    f = derive(res.imported.accepted)
    assert [(a.key, a.deleted_in) for a in f.accepted] == [("D-1", None), ("D-2", "b-2"), ("D-3", None)]
    assert {r["source_key"]: f.disposition[r["raw_record_id"]].kind for r in d["raw_records"] if r["batch_id"] == "b-2"} == {"D-2": DUPLICATE, "D-9": QUARANTINED}


def test_a_publication_that_ignored_the_delete_is_detected_by_its_content_hash():
    from pipeline_observatory.hashing import content_hash
    d = fixture_json("deletes/deletes.json")
    d.pop("expected")
    f = derive(run_pipeline(d).imported.accepted)
    assert run_pipeline(d).metrics["publications"]["publications"]["pub-1"]["content_hash_ok"] is True
    d["publications"][0]["content_hash"] = content_hash(a.payload_hash for a in f.accepted)        # the snapshot still contains D-2: the delete was not propagated
    assert run_pipeline(d).metrics["publications"]["publications"]["pub-1"]["content_hash_ok"] is False


def test_a_delete_of_an_unknown_key_is_quarantined_and_a_repeated_delete_is_a_duplicate():
    keys = {"A"}
    ops = [{"raw_record_id": "rr-1", "source_key": "A", "payload_json": {"record_id": "A", "op": "delete"}},
           {"raw_record_id": "rr-2", "source_key": "A", "payload_json": {"record_id": "A", "op": "delete"}},
           {"raw_record_id": "rr-3", "source_key": "Z", "payload_json": {"record_id": "Z", "op": "delete"}},
           {"raw_record_id": "rr-4", "source_key": "A", "payload_json": {"record_id": "A", "op": "merge"}}]
    assert [(d.kind, d.reason) for d in classify_rows(ops, keys, set())] == [(DELETED, None), (DUPLICATE, None), (QUARANTINED, "DELETE_TARGET_UNKNOWN"), (QUARANTINED, "UNKNOWN_OP")]


# ------------------------------------------------------------------------------------------------ import validation (D-05)
def test_duplicate_primary_keys_unknown_parents_and_missing_ids_are_rejected_with_codes():
    d = golden_inputs()
    d["source_contracts"].append(dict(d["source_contracts"][0]))                                   # DUPLICATE_ID
    d["ingestion_batches"].append({"batch_id": "b-9", "source_id": "src-nope", "source_cursor": "c", "started_at": "2026-10-04T13:00:00Z", "status": "committed"})   # UNKNOWN_SOURCE
    d["raw_records"].append({"raw_record_id": "rr-x", "batch_id": "b-nope", "source_key": "K", "payload_hash": "0" * 64, "payload_json": {}})                      # UNKNOWN_BATCH
    d["task_runs"].append({"task_run_id": "tr-x", "run_id": "run-nope", "task_name": "ingest", "status": "success", "attempt": "1"})                              # UNKNOWN_RUN
    d["quality_results"].append({"quality_result_id": "qr-x", "task_run_id": "tr-nope", "rule_name": "r", "severity": "critical", "eligible_count": 1, "failure_count": 0})   # UNKNOWN_TASK_RUN
    d["pipeline_runs"].append({"run_id": "run-9", "started_at": "2026-10-04T13:00:00Z", "finished_at": "2026-10-04T13:10:00Z", "status": "success", "code_sha": "x", "backfill_id": "bf-nope"})  # UNKNOWN_BACKFILL
    d["incidents"].append({"incident_id": None, "run_id": "run-001", "severity": "low", "status": "open", "opened_at": "2026-10-04T13:00:00Z"})                          # MISSING_FIELD
    got = {(r["entity"], r["id"]): r["reason_code"] for r in run_pipeline(d).rejected}
    assert got == {("source_contracts", "src-orders"): "DUPLICATE_ID", ("ingestion_batches", "b-9"): "UNKNOWN_SOURCE", ("raw_records", "rr-x"): "UNKNOWN_BATCH",
                   ("task_runs", "tr-x"): "UNKNOWN_RUN", ("quality_results", "qr-x"): "UNKNOWN_TASK_RUN", ("pipeline_runs", "run-9"): "UNKNOWN_BACKFILL",
                   ("incidents", None): "MISSING_FIELD"}


def test_a_repeated_task_attempt_is_a_duplicate_id_and_the_attempt_is_not_double_counted():
    d = golden_inputs()
    d["task_runs"].append({"task_run_id": "tr-001-9", "run_id": "run-001", "task_name": "transform", "status": "success", "attempt": "2"})
    res = run_pipeline(d)
    assert [(r["id"], r["reason_code"]) for r in res.rejected] == [("tr-001-9", "DUPLICATE_ID")]
    assert res.metrics["runs"]["runs"]["run-001"]["attempts"] == 5
