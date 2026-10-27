"""P08-TEST-11: a secret never appears in structured logs, audit rows or evidence. A redaction check runs on every log line and fails closed."""
import logging

import pytest
from pipeline_observatory import redaction
from pipeline_observatory.redaction import REDACTED, WITHHELD, contains_secret, redact_text, redact_value, safe_line

from api import logs
from support_db import FIXTURES, OPERATOR, client, command, conn, count, db_url, ingest, load_world, metrics

SECRET_LINES = (FIXTURES / "logs" / "with_secrets.log").read_text().splitlines()
CLEAN_LINES = (FIXTURES / "logs" / "clean.log").read_text().splitlines()
SECRET_VALUES = ["ghp_0123456789abcdefghijABCDEFGHIJ0123", "eyJhbGciOiJIUzI1NiJ9", "s3cr3t-pw", "sk-live-ABCDEF0123456789", "AKIAIOSFODNN7EXAMPLE", "hunter2",
                 "BEGIN RSA PRIVATE KEY", "xoxb-123456789012-abcdefghijkl"]


@pytest.mark.parametrize("line,value", list(zip(SECRET_LINES, SECRET_VALUES)))
def test_every_secret_line_of_the_fixture_is_detected_and_redacted(line, value):
    assert value in line and contains_secret(line)                                          # the check finds it
    clean = redact_text(line)
    assert value not in clean and not contains_secret(clean) and safe_line(line) == clean   # and the redacted line passes the check
    assert redact_text(clean) == clean                                                      # redaction is idempotent


@pytest.mark.parametrize("line", CLEAN_LINES)
def test_ordinary_log_lines_are_left_alone(line):
    assert not contains_secret(line) and redact_text(line) == line and safe_line(line) == line


def test_the_surrounding_context_survives_so_the_line_stays_useful():
    out = redact_text(SECRET_LINES[0])
    assert 'msg="fetching"' in out and "url=https://api.example.test/orders" in out and "token=" + REDACTED in out
    assert redact_text(SECRET_LINES[2]) == f"connecting postgresql://lab:{REDACTED}@127.0.0.1:5432/pipeline_observatory"


def test_secret_named_fields_are_redacted_whatever_their_value_looks_like():
    d = {"event": "x", "password": "p", "nested": {"API_KEY": "abc", "Authorization": "Basic Zm9vOmJhcg==", "list": [{"client_secret": "z"}, "token=abc123"]},
         "region": "eu", "amount": "25.00", "none": None, "cookie": None}
    out = redact_value(d)
    assert out["password"] == REDACTED and out["nested"]["API_KEY"] == REDACTED and out["nested"]["Authorization"] == REDACTED and out["nested"]["list"][0]["client_secret"] == REDACTED
    assert out["nested"]["list"][1] == "token=" + REDACTED and out["region"] == "eu" and out["amount"] == "25.00" and out["none"] is None and out["cookie"] is None
    assert not contains_secret(str(out))


def test_the_structured_log_line_is_checked_before_it_is_emitted(caplog):
    caplog.set_level(logging.INFO, logger="pipeline_observatory.api")
    line = logs.emit("config", api_key="sk-live-ABCDEF0123456789", dsn="postgresql://lab:s3cr3t-pw@h/db", note="Bearer abcdefghijkl", batch_id="b-1")
    assert "sk-live" not in line and "s3cr3t-pw" not in line and "abcdefghijkl" not in line and '"batch_id": "b-1"' in line.replace('"batch_id":"b-1"', '"batch_id": "b-1"')
    assert all(not contains_secret(r.getMessage()) for r in caplog.records) and caplog.records


def test_a_line_that_still_fails_the_check_is_withheld_whole(monkeypatch):
    monkeypatch.setattr(redaction, "redact_text", lambda t: t)                               # simulate a defect: redaction does nothing
    monkeypatch.setattr(redaction, "contains_secret", lambda t: "ghp_" in t)
    assert redaction.safe_line("token ghp_0123456789abcdefghijABCDEFGHIJ0123") == WITHHELD


def test_the_logging_filter_redacts_the_records_of_any_library(caplog):
    lg = logging.getLogger("third.party")
    flt = logs.RedactingFilter()
    lg.addFilter(flt)
    try:
        caplog.set_level(logging.INFO, logger="third.party")
        lg.info("calling with %s and %s", "Authorization: Bearer abcdefghijkl", "password=hunter2")
    finally:
        lg.removeFilter(flt)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "abcdefghijkl" not in text and "hunter2" not in text and "calling with" in text


@pytest.fixture
def lab(client, conn):
    load_world(conn)
    return client


def test_no_secret_reaches_a_table_a_response_or_a_log_through_the_api(lab, conn, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "ghp_0123456789abcdefghijABCDEFGHIJ0123"
    pw = "s3cr3t-pw-99"
    rid = f"req-token={secret}"
    ingest(lab, "src-orders", "b-1", [{"payload": {"record_id": "A", "quantity": 1, "unit_price": "1.00", "amount": "1.00", "event_ts": "2026-10-04T08:00:00Z"}}])
    command(lab, "transform-models", {"run_id": "run-1", "batch_ids": ["b-1"]})
    r = command(lab, "inject-fault", {"fault_type": "task_failure", "target_id": "run-1", "note": f"rotated password={pw} and token={secret}"}, headers=OPERATOR, request_id=rid)
    assert r.status_code == 200 and secret not in r.text.replace(rid, "") and pw not in r.text
    bad = command(lab, "commit-batch", {"batch_id": "b-nope"}, request_id=rid)                      # a refusal path with the same request id
    assert bad.status_code == 404
    note = conn.execute("SELECT note FROM fault_injections").fetchone()["note"]
    assert note == f"rotated password={REDACTED} and token={REDACTED}"
    # every text column of every table and every captured log record is free of the secret values
    dump = []
    for t in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall():
        for row in conn.execute(f'SELECT to_jsonb(x)::text AS j FROM "{t["table_name"]}" x').fetchall():   # table names come from the catalogue
            dump.append(row["j"])
    blob = "\n".join(dump)
    assert secret not in blob and pw not in blob
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert secret not in logged and pw not in logged
    assert all(not contains_secret(rec.getMessage()) for rec in caplog.records)                           # the check on every line
    assert count(conn, "audit_events", "request_id LIKE '%[REDACTED]%'") == 1 and count(conn, "audit_events", f"request_id LIKE '%{secret}%'") == 0


def test_command_log_lines_are_structured_json_and_name_the_actor_not_a_secret(lab, caplog):
    import json
    caplog.set_level(logging.INFO, logger="pipeline_observatory.api")
    command(lab, "request-backfill", {"source_id": "src-orders", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-02T00:00:00Z"})
    lines = [json.loads(r.getMessage()) for r in caplog.records if r.name == "pipeline_observatory.api" and r.getMessage().startswith("{")]
    cmd = [l for l in lines if l["event"] == "command"][0]
    assert cmd["name"] == "request-backfill" and cmd["actor_id"] == "usr-op01" and cmd["role"] == "operator" and cmd["status"] == "requested"


def test_evidence_manifests_are_redacted_before_they_are_hashed():
    manifest = {"items": {"gate": {"results": {"keys_unique": {"passed": True}}}, "log": ["calling https://u:pw123@host/x", "ok"], "env": {"DATABASE_URL": "postgresql://lab:lab@h/db"}}}
    out = redact_value(manifest)
    assert "pw123" not in str(out) and out["items"]["env"]["DATABASE_URL"] == f"postgresql://lab:{REDACTED}@h/db" and out["items"]["gate"] == manifest["items"]["gate"]
