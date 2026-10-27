"""D-09 (R8-01, R8-04, R8-05, R8-08): the Python domain, the PostgreSQL reference and (in web/scripts/review-check.ts) the TypeScript mirror give every
case of tests/fixtures/divergence/cases.json the SAME verdict, the one the table states; tests/reference_check.py judges the same cases with its own
hand-written parsers. The reviewer's cases are here: Arabic-Indic digits, a trailing newline, 3.0, integers beyond 2**53, an impossible calendar date,
sub-microsecond fractions, a future-dated event, a payload that is not an object."""
import json
from pathlib import Path

import pytest
from pipeline_observatory import run_pipeline
from pipeline_observatory.classify import contract_reason, money_amount
from pipeline_observatory.hashing import payload_hash
from pipeline_observatory.metrics import derive
from pipeline_observatory.patterns import MAX_SAFE_INTEGER, is_money, is_quantity
from pipeline_observatory.timeutil import iso_z, parse_ts

from support_db import conn, db_url, diff, load  # noqa: F401

CASES = Path(__file__).resolve().parent / "fixtures" / "divergence" / "cases.json"
SQL = (Path(__file__).resolve().parents[1] / "data" / "sql" / "reference_metrics.sql").read_text()
DOC = json.loads(CASES.read_text(encoding="utf-8"))          # 3.0 stays a float, 9007199254740993 stays an exact integer
IDS = [c["id"] for c in DOC["cases"]]


def world():
    """One source, two committed batches, every case a raw row of its batch (a row id is rr-<batch>-<n>)."""
    d = {"contract_version": 1, "as_of": DOC["cutoff"], "cutoff": DOC["cutoff"], "business_total_field": "amount", "freshness_timestamp_field": "event_ts",
         "partition_rule": "UTC date of the freshness timestamp field", "source_expectations": [], "processing_measurement": None,
         "source_contracts": [{"source_id": DOC["source_id"], "source_name": "Divergence", "schema_version": "1", "expected_frequency": "hourly", "owner_id": "own-01"}],
         "ingestion_batches": [], "raw_records": [], "quarantine_records": [], "checkpoints": [], "model_definitions": [], "pipeline_runs": [], "task_runs": [],
         "quality_results": [], "publications": [], "incidents": [], "backfill_requests": []}
    for b in DOC["batches"]:
        d["ingestion_batches"].append({"batch_id": b["batch_id"], "source_id": DOC["source_id"], "source_cursor": "cur-0", "started_at": b["started_at"], "status": "committed"})
        d["checkpoints"].append({"checkpoint_id": f"cp-{b['batch_id']}", "source_id": DOC["source_id"], "batch_id": b["batch_id"], "committed_cursor": b["committed_cursor"],
                                 "committed_at": b["committed_at"], "version_number": b["version_number"]})
    rid = {}
    for n, c in enumerate(DOC["cases"], 1):
        rid[c["id"]] = f"rr-{c['batch']}-{n:03d}"
        p = c["payload"]
        key = p.get("record_id") if isinstance(p, dict) else c["source_key"]
        d["raw_records"].append({"raw_record_id": rid[c["id"]], "batch_id": c["batch"], "source_key": key, "payload_hash": payload_hash(p), "payload_json": p})
    return d, rid


def test_the_table_is_what_the_issue_listed():
    kinds = {c["id"].split("-")[0] for c in DOC["cases"]}
    assert {"ok", "money", "quantity", "time", "payload", "order", "future"} <= kinds
    assert len(IDS) == len(set(IDS)) and len(IDS) >= 40


@pytest.mark.parametrize("case", DOC["cases"], ids=IDS)
def test_python_contract_reason_gives_the_table_verdict(case):
    batch = next(b for b in DOC["batches"] if b["batch_id"] == case["batch"])
    assert contract_reason(case["payload"], batch["started_at"], DOC["cutoff"]) == case["reason"]


def test_python_pipeline_classifies_every_row_as_the_table_says():
    data, rid = world()
    res = run_pipeline(data)
    assert res.rejected == []                                                       # the import accepts every row: the verdict is a disposition, never a drop
    facts = derive(res.imported.accepted, cutoff=DOC["cutoff"])
    for c in DOC["cases"]:
        d = facts.disposition[rid[c["id"]]]
        assert (d.kind, d.reason) == (c["disposition"], c["reason"]), c["id"]
    accepted = {a.raw_record_id: a for a in facts.accepted}
    for c in DOC["cases"]:
        if "event_at" in c:
            assert iso_z(parse_ts(accepted[rid[c["id"]]].event_at)) == c["event_at"]       # truncated to microseconds, never rounded up a second
    assert sum(1 for c in DOC["cases"] if c["disposition"] == "accepted") == len(facts.accepted)


def test_sql_reference_gives_the_same_verdict_for_every_row(conn):
    data, rid = world()
    load(conn, data)
    rows_sql = SQL[:SQL.rindex("SELECT (SELECT j FROM ingestion)")] + "SELECT raw_record_id, kind, q_reason, ev FROM cl ORDER BY raw_record_id"
    got = {r["raw_record_id"]: r for r in conn.execute(rows_sql, {"cutoff": DOC["cutoff"]}).fetchall()}
    assert len(got) == len(DOC["cases"])
    for c in DOC["cases"]:
        r = got[rid[c["id"]]]
        assert (r["kind"], r["q_reason"] if r["kind"] != "accepted" else None) == (c["disposition"], c["reason"]), c["id"]
        if "event_at" in c:
            assert iso_z(r["ev"]) == c["event_at"]
    # the SQL reference as a whole runs (an impossible date used to abort it) and agrees with the domain on the counts
    full = conn.execute(SQL, {"cutoff": DOC["cutoff"]}).fetchone()
    res = run_pipeline(data)
    facts = derive(res.imported.accepted, cutoff=DOC["cutoff"])
    assert full["ingestion"]["overall"]["accepted_unique"] == len(facts.accepted)
    assert full["ingestion"]["overall"]["quarantined"] == sum(1 for d in facts.disposition.values() if d.kind == "quarantined")
    for k in ("ingestion", "freshness"):                                                    # the whole trees agree, including the truncated instant's text
        assert diff(full[k], res.metrics[k]) == [], k
    assert full["freshness"]["src-div"]["latest_accepted_event_at"] == res.metrics["freshness"]["src-div"]["latest_accepted_event_at"]


def test_the_pattern_set_in_one_place():
    for ok in ("0", "-0", "12", "-12.5", "12.50", "007.1"):
        assert is_money(ok), ok
    for bad in ("", "-", ".5", "5.", "5.001", "1e3", "+5", " 5", "5 ", "5.00\n", "\n5", "١٠.٠٠", "5,00", "NaN", None, 5, 5.0, True):
        assert not is_money(bad), bad
    assert is_quantity(0) and is_quantity(-MAX_SAFE_INTEGER) and is_quantity(MAX_SAFE_INTEGER)
    for bad in (MAX_SAFE_INTEGER + 1, -MAX_SAFE_INTEGER - 1, 3.0, 2.5, True, False, "3", None):
        assert not is_quantity(bad), bad
    for bad in ("2026-02-30T00:00:00Z", "2026-10-04T24:00:00Z", "2026-10-04T08:00:60Z", "2026-10-04T08:00:00Z\n", "2026-10-04T08:00:00", "2026-10-04T08:00:00+24:00",
                "٢٠٢٦-10-04T08:00:00Z", "0000-01-01T00:00:00Z", "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-00:01"):
        with pytest.raises(ValueError):
            parse_ts(bad)
    assert iso_z(parse_ts("2026-10-04T08:00:00.9999995Z")) == "2026-10-04T08:00:00.999999Z"          # truncated
    assert iso_z(parse_ts("2026-10-04T12:00:00+02:00")) == "2026-10-04T10:00:00Z" and iso_z(parse_ts("2026-10-04 08:00:00Z")) == "2026-10-04T08:00:00Z"


def test_money_amount_guards_a_payload_that_is_not_an_object_and_a_bad_amount():
    for payload in (["amount"], "12.00", 12, None, True):
        assert str(money_amount(payload)) == "0"
    assert str(money_amount({"amount": "12.50"})) == "12.50" and str(money_amount({"amount": "12.50\n"})) == "0" and str(money_amount({"amount": "١٢.00"})) == "0"
    d = world()[0]
    d["raw_records"] += [{"raw_record_id": "rr-b-div-900", "batch_id": "b-div", "source_key": "L-1", "payload_hash": payload_hash([1, 2]), "payload_json": [1, 2]}]
    res = run_pipeline(d)                                                            # did not raise: the list payload is quarantined INVALID_FIELD and counts 0.00
    assert derive(res.imported.accepted, cutoff=DOC["cutoff"]).disposition["rr-b-div-900"].reason == "INVALID_FIELD"
