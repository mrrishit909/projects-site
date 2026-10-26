"""Synthetic data generator: determinism, shapes, sizes, spec ranges, designed relationships, injected defects.

The generator (data/generate.py) is stdlib only and shares no code with the domain; these tests run the domain over its
output (ingest, the cumulative three-way match, duplicates, approvals, export, credits, metrics) to show that every designed
relationship and every injected defect is detectable and handled as the injection manifest says, and, when DATABASE_URL is
set, that data/seed.py loads the dataset, data/sql/reference_metrics.sql agrees with the domain on the full window and two
monthly as-of cutoffs, and every replay-only event behaves as recorded through the FastAPI TestClient.
"""
from __future__ import annotations

import collections
import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("ib_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["ib_generate"] = gen
_spec.loader.exec_module(gen)

from invoicebridge import compute_metrics, disclosures, run_pipeline, window_metrics  # noqa: E402
from invoicebridge.book import derive  # noqa: E402
from invoicebridge.amounts import identity_key, invoice_amounts, normalise_number  # noqa: E402
from invoicebridge.contract import METRIC_KEYS  # noqa: E402
from invoicebridge.timeutil import parse_ts  # noqa: E402

SEED = 20261026
VERSION = f"ib-{SEED}-20261026"
GOLDEN = ROOT / "tests" / "fixtures" / "golden"
BUDGET = 5_000_000
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
MONEY = re.compile(r"^\d+\.\d{2}$")
QTY = re.compile(r"^\d+\.\d{4}$")
PRICE = re.compile(r"^\d+\.\d{6}$")
WIN_END = parse_ts("2026-09-30T23:59:59Z")


def _no_float(text: str):
    def refuse(x):
        raise AssertionError(f"a float literal ({x}) in the output")
    return json.loads(text, parse_float=refuse)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen")
    out, meta = tmp / "out", tmp / "meta"
    manifest = gen.write_all(SEED, out, meta)
    rows = {}
    for name in gen.ENTITIES:
        doc = _no_float((out / f"{name}.json").read_text())
        assert doc["entity"] == name and doc["dataset_version"] == VERSION and list(doc) == ["entity", "dataset_version", "rows"]
        rows[name] = doc["rows"]
    inj_doc = json.loads((meta / "injection-manifest.json").read_text())
    return {"out": out, "meta": meta, "manifest": manifest, "rows": rows, "inj_doc": inj_doc,
            "inj": {i["id"]: i for i in inj_doc["injections"]},
            "events": {e["event_id"]: e for e in json.loads((meta / "injection-events.json").read_text())["events"]}}


@pytest.fixture(scope="module")
def inputs(built):
    m = built["manifest"]
    return {"contract_version": 1, "as_of": m["as_of"], "snapshot_cutoffs": m["snapshot_cutoffs"], "tolerances": m["tolerances"],
            **{k: v for k, v in built["rows"].items() if k in gen.DOMAIN_ENTITIES}}


@pytest.fixture(scope="module")
def result(inputs):
    return run_pipeline(inputs)


def _expected_rejections(built) -> set[tuple[str, str, str]]:
    return {(r["entity"], r["id"], r["reason_code"]) for i in built["inj"].values() for r in i.get("expected_rejections", [])}


def _expected_merges(built) -> dict[str, tuple[str, str]]:
    return {r["id"]: (r["merged_into"], r["reason_code"]) for i in built["inj"].values() for r in i.get("expected_merges", [])}


# --- determinism, files, manifest -------------------------------------------------------------------------------
def test_deterministic_across_runs_and_hash_seeds(built, tmp_path):
    again = gen.write_all(SEED, tmp_path / "out", tmp_path / "meta")
    assert again["dataset_hash"] == built["manifest"]["dataset_hash"]
    for name in gen.ENTITIES:
        assert (tmp_path / "out" / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes()
    for f in ("injection-events.json", "injection-manifest.json"):
        assert (tmp_path / "meta" / f).read_bytes() == (built["meta"] / f).read_bytes()
    other = gen.write_all(SEED + 1, tmp_path / "o2", tmp_path / "m2")
    assert other["dataset_hash"] != again["dataset_hash"]
    for hash_seed in ("0", "1", "2"):         # a fresh interpreter per PYTHONHASHSEED: nothing depends on set order
        out, meta = tmp_path / f"h{hash_seed}", tmp_path / f"hm{hash_seed}"
        proc = subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--seed", str(SEED), "--out", str(out),
                               "--data-dir", str(meta)], capture_output=True, text=True,
                              env={**os.environ, "PYTHONHASHSEED": hash_seed})
        assert proc.returncode == 0, proc.stderr
        for name in gen.ENTITIES:
            assert (out / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), (hash_seed, name)
        for f in ("injection-events.json", "injection-manifest.json"):
            assert (meta / f).read_bytes() == (built["meta"] / f).read_bytes(), (hash_seed, f)
        assert json.loads((out / "manifest.json").read_text())["dataset_hash"] == built["manifest"]["dataset_hash"]
        assert (out / "golden" / "manifest.json").read_bytes() == (built["out"] / "golden" / "manifest.json").read_bytes()


def test_committed_snapshot_is_the_generator_output(built):
    pub = ROOT / "web" / "public" / "data"
    assert (pub / "invoices.json").exists(), "web/public/data is not generated: run python data/generate.py"
    for name in gen.ENTITIES:
        assert (pub / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), name
    assert json.loads((pub / "manifest.json").read_text())["dataset_hash"] == built["manifest"]["dataset_hash"]
    assert (pub / "injection-manifest.json").read_bytes() == (built["out"] / "injection-manifest.json").read_bytes()
    assert (ROOT / "data" / "injection-manifest.json").read_bytes() == (built["out"] / "injection-manifest.json").read_bytes()
    assert (ROOT / "data" / "injection-events.json").read_bytes() == (built["meta"] / "injection-events.json").read_bytes()
    for f in sorted((built["out"] / "golden").iterdir()):
        assert (pub / "golden" / f.name).read_bytes() == f.read_bytes(), f.name


def test_manifest_shape_and_hash(built):
    m = built["manifest"]
    assert m["dataset_version"] == VERSION and m["contract_version"] == "v1"
    assert set(m) >= {"dataset_version", "dataset_hash", "generated_at", "contract_version", "generator", "row_counts",
                      "designed_relationships", "injection_manifest", "stats"}
    assert STAMP.match(m["generated_at"])
    assert m["generator"]["seed"] == SEED and m["generator"]["name"] == "generate.py"
    assert m["generator"]["parameters"]["invoices"] == 2800 and m["generator"]["parameters"]["group_02x"] == ["ven-020", "ven-029"]
    assert m["row_counts"] == {n: len(built["rows"][n]) for n in gen.ENTITIES}
    assert json.loads((built["out"] / "manifest.json").read_text())["dataset_hash"] == m["dataset_hash"]
    h = hashlib.sha256()
    for name in sorted(gen.ENTITIES):
        h.update(json.dumps(built["rows"][name], sort_keys=True, separators=(",", ":")).encode())
    assert h.hexdigest() == m["dataset_hash"]
    assert [d["id"] for d in m["designed_relationships"]] == ["DR-01", "DR-02", "DR-03", "DR-04"]
    assert built["inj_doc"]["dataset_hash"] == m["dataset_hash"]
    assert (built["out"] / "injection-manifest.json").read_bytes() == (built["meta"] / "injection-manifest.json").read_bytes()
    assert {e["injection"] for e in built["events"].values()} <= set(built["inj"])


def test_total_size_is_under_5_mb(built, tmp_path):
    total = sum(p.stat().st_size for p in built["out"].rglob("*") if p.is_file())
    total += sum(p.stat().st_size for p in built["meta"].rglob("*") if p.is_file())
    assert total < BUDGET, total
    pub = ROOT / "web" / "public" / "data"
    committed = sum(p.stat().st_size for p in pub.rglob("*") if p.is_file())
    assert committed < BUDGET, committed


def test_source_bytes_are_represented_by_sha256_only(built):
    text = json.dumps(built["rows"])
    assert "base64" not in text.lower() and "data:application/pdf" not in text
    for i in built["rows"]["invoices"]:
        assert re.fullmatch(r"[0-9a-f]{64}", i["source_sha256"]) and i["source_filename"].endswith(".pdf")


# --- shape of every row ------------------------------------------------------------------------------------------
def test_field_names_equal_the_fixture_and_the_schema(built):
    fixture = json.loads((GOLDEN / "inputs.json").read_text())
    for name in gen.ENTITIES:
        want = set(gen.EXTRA_COLUMNS.get(name, ()))
        if fixture.get(name):
            want = set(fixture[name][0]) | set(gen.EXTRA_ROW_FIELDS.get(name, ()))
        assert built["rows"][name], name
        for row in built["rows"][name]:
            assert set(row) == want, (name, sorted(set(row) ^ want))
    # the only field beyond the fixture's rows: approvals.reason (a rejection needs one, D-04)
    assert set(gen.EXTRA_ROW_FIELDS) == {"approvals"} and {a["reason"] is None for a in built["rows"]["approvals"] if a["decision"] == "approve"} == {True}
    assert all(a["reason"] for a in built["rows"]["approvals"] if a["decision"] == "reject")
    proc = subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--profile", "golden-shape-check"],
                          capture_output=True, text=True)
    assert proc.returncode == 0 and "MISMATCH" not in proc.stdout, proc.stdout


def test_value_formats_and_ranges(built):
    r = built["rows"]
    for p in r["po_lines"]:
        assert QTY.match(p["quantity"]) and PRICE.match(p["unit_price"])
    for x in r["receipts"]:
        assert QTY.match(x["received_quantity"]) and STAMP.match(x["received_at"]) and isinstance(x["reversed"], bool)
    for i in r["invoices"]:
        assert all(MONEY.match(i[k]) for k in ("freight", "invoice_discount", "declared_total")) and PRICE.match(i["tax_rate"])
        assert STAMP.match(i["imported_at"]) and re.fullmatch(r"\d{4}-\d\d-\d\d", i["invoice_date"])
        assert i["invoice_date"] <= i["imported_at"][:10]                 # never dated after the day it was imported
    for l in r["invoice_lines"]:
        assert QTY.match(l["quantity"]) and PRICE.match(l["unit_price"]) and Decimal(l["quantity"]) > 0
    for c in r["credit_notes"]:
        assert MONEY.match(c["credit_amount"]) and Decimal(c["credit_amount"]) > 0 and STAMP.match(c["credited_at"])
    for a in r["approval_policies"]:
        assert MONEY.match(a["amount_limit"]) and STAMP.match(a["effective_from"])
    for b in r["export_batches"]:
        assert MONEY.match(b["total"]) and STAMP.match(b["exported_at"])
    for table, col in (("purchase_orders", "ordered_at"), ("approvals", "decided_at"), ("export_requests", "exported_at"),
                       ("exceptions", "created_at"), ("exception_assignments", "assigned_at")):
        for row in r[table]:
            assert STAMP.match(row[col]) and "2025-10-01T00:00:00Z" <= row[col] <= "2026-10-01T02:00:00Z", (table, row[col])
    for table in ("receipts", "invoices", "approvals", "export_requests", "credit_notes"):
        stamp = {"receipts": "received_at", "invoices": "imported_at", "approvals": "decided_at", "export_requests": "exported_at",
                 "credit_notes": "credited_at"}[table]
        assert max(x[stamp] for x in r[table]) <= "2026-09-30T23:59:59Z", table
    for name, rows in r.items():
        key = {"vendors": "vendor_id", "purchase_orders": "po_id", "po_lines": "po_line_id", "receipts": "receipt_id",
               "invoices": "invoice_id", "invoice_lines": "invoice_line_id", "credit_notes": "credit_id",
               "approval_policies": "policy_id", "approvals": "approval_id", "exceptions": "exception_id",
               "exception_assignments": "assignment_id", "export_batches": "batch_id"}.get(name)
        if key:
            ids = [x[key] for x in rows]
            assert len(set(ids)) == len(ids) and ids == sorted(ids), name


def test_counts_within_spec(built):
    r = built["rows"]
    assert len(r["vendors"]) == 40 and {v["currency"] for v in r["vendors"]} == {"USD", "EUR", "GBP"}
    assert len(r["purchase_orders"]) == 1200 and len(r["po_lines"]) == 3000 and len(r["invoices"]) == 2800
    assert 4500 <= len(r["invoice_lines"]) <= 6500 and 4500 <= len(r["receipts"]) <= 6000
    assert {p["ordered_at"][:7] for p in r["purchase_orders"]} >= {"2025-10", "2026-03", "2026-08"}
    # receipts: partials (a line received in more than one delivery) and about 2 % reversals
    live = collections.Counter(x["po_line_id"] for x in r["receipts"] if not x["reversed"])
    assert sum(1 for n in live.values() if n >= 2) >= 0.30 * len(live)
    rev = sum(1 for x in r["receipts"] if x["reversed"]) / len(r["receipts"])
    assert 0.015 <= rev <= 0.025, rev
    # credit notes on 4 % of the invoices
    credited = len({c["invoice_id"] for c in r["credit_notes"]}) / len(r["invoices"])
    assert 0.035 <= credited <= 0.045, credited
    # two policy versions with the limit change on 2026-04-01
    pol = {p["policy_id"]: p for p in r["approval_policies"]}
    assert pol["pol-v1"]["version_number"] == 1 and pol["pol-v2"]["version_number"] == 2
    assert pol["pol-v2"]["effective_from"] == "2026-04-01T00:00:00Z" and Decimal(pol["pol-v2"]["amount_limit"]) > Decimal(pol["pol-v1"]["amount_limit"])
    assert sum(1 for a in r["approvals"] if a["decision"] == "approve") > 2000 and sum(1 for a in r["approvals"] if a["decision"] == "reject") >= 20
    assert 40 <= len(r["export_batches"]) <= 60 and len(r["export_requests"]) == len(r["export_batches"]) + 7
    assert len(r["exceptions"]) >= 300 and len(r["exception_assignments"]) >= 300
    # invoice currency follows the vendor except in the INJ-09 invoices; nobody invoices from the dormant vendor
    vend = {v["vendor_id"]: v for v in r["vendors"]}
    fx = {x for i in built["inj"]["INJ-09"]["detail"] for x in (i["invoice_id"],)}
    for i in r["invoices"]:
        assert (i["currency"] == vend[i["vendor_id"]]["currency"]) or i["invoice_id"] in fx
        assert vend[i["vendor_id"]]["active"]
    assert sum(1 for v in r["vendors"] if not v["active"]) == 1
    # each PO's lines belong to the PO's vendor catalogue: invoice lines name lines of the invoice's own PO and vendor
    pol_po = {l["po_line_id"]: l["po_id"] for l in r["po_lines"]}
    po_vendor = {p["po_id"]: p["vendor_id"] for p in r["purchase_orders"]}
    inv_vendor = {i["invoice_id"]: i["vendor_id"] for i in r["invoices"]}
    pos_of = collections.defaultdict(set)
    for l in r["invoice_lines"]:
        pos_of[l["invoice_id"]].add(pol_po[l["po_line_id"]])
        assert po_vendor[pol_po[l["po_line_id"]]] == inv_vendor[l["invoice_id"]]
    assert all(len(v) == 1 for v in pos_of.values())


def test_golden_copy_for_the_web_app(built):
    g = built["out"] / "golden"
    fixture = json.loads((GOLDEN / "inputs.json").read_text())
    for name in gen.ENTITIES:
        doc = json.loads((g / f"{name}.json").read_text())
        assert doc["entity"] == name and doc["dataset_version"] == "golden-v1" and doc["rows"] == fixture.get(name, [])
    man = json.loads((g / "manifest.json").read_text())
    assert man["dataset_version"] == "golden-v1" and man["dataset_hash"] == json.loads((GOLDEN / "HASHES.json").read_text())["sha256"]["inputs.json"]
    assert man["generator"]["seed"] == 0 and man["designed_relationships"] == [] and man["snapshot_cutoffs"] == fixture["snapshot_cutoffs"]
    assert man["as_of"] == fixture["as_of"] and man["tolerances"] == fixture["tolerances"]
    assert man["row_counts"]["invoices"] == 3 and man["row_counts"]["export_requests"] == 2 and man["row_counts"]["exceptions"] == 0
    assert json.loads((g / "expected.json").read_text()) == json.loads((GOLDEN / "expected.json").read_text())


# --- the domain on the generated world --------------------------------------------------------------------------
def test_pipeline_rejects_exactly_what_the_manifest_lists_and_merges_exactly_what_it_lists(built, result):
    got = {(r["entity"], r["id"], r["reason_code"]) for r in result.rejected}
    assert got == _expected_rejections(built) == set()                    # the clean files carry no ingest rejection
    counts = result.counts
    for name in gen.DOMAIN_ENTITIES:
        if name in counts:
            assert counts[name]["rejected"] == 0 and counts[name]["accepted"] + counts[name]["merged"] == len(built["rows"][name]), name
    expected = _expected_merges(built)
    by_bytes = {r["id"]: (r["merged_into"], r["reason_code"]) for r in result.ingest.merged_records
                if r["reason_code"] == "DUPLICATE_SOURCE_BYTES"}
    assert by_bytes == expected and len(expected) == 3
    resent = [r for r in result.ingest.merged_records if r["reason_code"] == "DUPLICATE_IDENTITY"]
    assert len(resent) == built["manifest"]["generator"]["parameters"]["resent_pdf_duplicates"] == 95
    assert counts["invoices"]["merged"] == 98 and counts["invoices"]["accepted"] == 2702
    assert result.metrics["duplicates"] == {"groups_detected": 98, "rows_merged": 98, "unresolved_groups": 0}
    # a re-sent PDF: another file (other bytes), the same vendor, normalised number, date and computed total
    inv = {i["invoice_id"]: i for i in built["rows"]["invoices"]}
    for r in resent:
        a, b = inv[r["merged_into"]], inv[r["id"]]
        assert a["source_sha256"] != b["source_sha256"] and a["vendor_id"] == b["vendor_id"] and a["invoice_date"] == b["invoice_date"]
        assert normalise_number(a["invoice_number"]) == normalise_number(b["invoice_number"]) and a["imported_at"] < b["imported_at"]
    assert not result.warnings


def test_the_book_is_clean_approvals_valid_and_the_export_reconciles(built, result):
    m = result.metrics
    assert m["approvals"]["invalid_records"] == []                        # no self-approval, no unmatched or over-limit approval
    assert m["approvals"]["valid_count"] == sum(1 for a in built["rows"]["approvals"] if a["decision"] == "approve")
    assert m["export"]["difference"] == "0.00" and m["export"]["accepted_export_total"] == m["obligations"]["total"]
    assert m["export"]["batches_created"] == len(built["rows"]["export_batches"]) and m["export"]["repeat_requests_returned_prior"] == 7
    assert m["export"]["requests_received"] == len(built["rows"]["export_requests"])
    assert m["payable"]["credit_total"] != "0.00" and Decimal(m["payable"]["approved_payable"]) < Decimal(m["payable"]["approved_total"])
    assert 0.85 <= float(m["rates"]["straight_through_rate"]) <= 0.95 and m["processing"]["approved_count"] > 2000
    assert result.book.status.keys() == {i["invoice_id"] for i in built["rows"]["invoices"]}
    assert set(result.book.status.values()) >= {"matched", "exception", "exported", "adjusted", "merged", "rejected"}
    assert "approved" in set(derive(result.population, parse_ts("2026-06-30T23:59:59Z")).status.values())   # not yet exported mid-year
    assert "paid" not in set(result.book.status.values())
    # every valid rejection is a reviewer decision on an invoice that was an exception in every run; none is invalid
    rejected = {a["invoice_id"] for a in built["rows"]["approvals"] if a["decision"] == "reject"}
    assert rejected == {i for i, s in result.book.status.items() if s == "rejected"}
    d = disclosures(result.population, result.book)
    assert len(d["rounding_tolerated_invoices"]) >= 15                    # vendors that round tax per line: disclosed, tolerated


def test_exceptions_file_agrees_with_the_domain_and_keeps_its_assignment_history(built, result):
    exc = built["rows"]["exceptions"]
    live = {(e["invoice_id"], e["exception_type"]) for e in exc if e["status"] != "resolved"}
    dom = {(e["invoice_id"], e["exception_type"]) for e in result.metrics["exceptions"]["records"]}
    assert live == dom
    assert {e["exception_type"] for e in exc} == {"QUANTITY_BLOCKED", "PRICE_VARIANCE", "ROUNDING_EXCEPTION", "CURRENCY_MISMATCH"}
    assert result.metrics["exceptions"]["by_reason"]["NO_PO_LINE"] == 0
    asg = collections.defaultdict(list)
    for a in built["rows"]["exception_assignments"]:
        asg[a["exception_id"]].append(a)
    by_id = {e["exception_id"]: e for e in exc}
    assert set(asg) <= set(by_id)
    for eid, history in asg.items():
        e = by_id[eid]
        assert [a["assigned_at"] for a in history] == sorted(a["assigned_at"] for a in history)
        assert all(a["assigned_at"] >= e["created_at"] for a in history)
        assert all(e["resolved_at"] is None or a["assigned_at"] < e["resolved_at"] for a in history)
        assert all(history[i]["owner_id"] != history[i + 1]["owner_id"] for i in range(len(history) - 1))
        if e["status"] != "resolved":
            assert e["owner_id"] == history[-1]["owner_id"] and e["status"] == "assigned"
    for e in exc:
        assert (e["status"] == "open") == (e["owner_id"] is None and e["resolved_at"] is None)
        assert e["resolved_at"] is None or e["resolved_at"] >= e["created_at"]
    assert sum(1 for e in exc if e["status"] == "resolved") > 100 and sum(1 for e in exc if len(asg.get(e["exception_id"], [])) >= 2) > 20
    assert result.metrics["exceptions"]["open_count"] == len(live)
    # an invoice never has two open exceptions of one type (the unique index of 0002_constraints.sql)
    assert len(live) == sum(1 for e in exc if e["status"] != "resolved")


def test_export_batches_and_requests_agree_with_the_domain(built, result):
    rows = collections.defaultdict(list)
    for r in result.metrics["export"]["rows"]:
        rows[r["batch_id"]].append(r)
    for b in built["rows"]["export_batches"]:
        got = rows[b["batch_id"]]
        assert b["row_count"] == len(got) and b["total"] == str(sum((Decimal(r["amount"]) for r in got), Decimal(0)).quantize(Decimal("0.01")))
        assert all(r["exported_at"] == b["exported_at"] for r in got)
    assert sum(len(v) for v in rows.values()) == len(result.metrics["export"]["rows"]) == result.metrics["obligations"]["count"]
    firsts = {}
    for q in built["rows"]["export_requests"]:
        firsts.setdefault(q["batch_id"], q)
    repeats = [q for q in built["rows"]["export_requests"] if q["exported_at"] != firsts[q["batch_id"]]["exported_at"]]
    assert len(repeats) == 7
    for q in repeats:
        f = firsts[q["batch_id"]]
        assert q["idempotency_key"] == f["idempotency_key"] and q["invoice_ids"] == f["invoice_ids"]
        assert 0 < (parse_ts(q["exported_at"]) - parse_ts(f["exported_at"])).total_seconds() <= 120
    assert [q["exported_at"] for q in built["rows"]["export_requests"]] == sorted(q["exported_at"] for q in built["rows"]["export_requests"])


# --- designed relationships -------------------------------------------------------------------------------------
def _qb_rates(built, result):
    inv_vendor = {i["invoice_id"]: i["vendor_id"] for i in built["rows"]["invoices"]}
    blocked = {e["invoice_id"] for e in result.metrics["exceptions"]["records"] if e["exception_type"] == "QUANTITY_BLOCKED"}
    per = collections.defaultdict(lambda: [0, 0])
    for iid in result.book.in_book:
        per[inv_vendor[iid]][1] += 1
        per[inv_vendor[iid]][0] += iid in blocked
    return per


def test_ven_02x_invoices_before_receipts_have_the_highest_quantity_blocked_rate(built, result):
    per = _qb_rates(built, result)
    g02 = [f"ven-{i:03d}" for i in range(20, 30)]
    rate = {v: a / n for v, (a, n) in per.items() if n}
    assert min(rate[v] for v in g02) > max(rate[v] for v in rate if v not in g02) + 0.15
    qb02, n02 = (sum(per[v][0] for v in g02), sum(per[v][1] for v in g02))
    qbo, no = (sum(a for v, (a, n) in per.items() if v not in g02), sum(n for v, (a, n) in per.items() if v not in g02))
    assert qb02 / n02 > 0.25 and qbo / no < 0.04 and qb02 / n02 > 8 * (qbo / no)
    assert qb02 > 4 * qbo
    # the cause: at the instant they are imported their lines are not yet covered by what was received (net of earlier invoices)
    inv = {i["invoice_id"]: i for i in built["rows"]["invoices"]}
    received = collections.defaultdict(list)
    for rc in built["rows"]["receipts"]:
        if not rc["reversed"]:
            received[rc["po_line_id"]].append((rc["received_at"], Decimal(rc["received_quantity"])))
    by_line = collections.defaultdict(list)
    for l in built["rows"]["invoice_lines"]:
        if l["invoice_id"] not in result.book.merged_into:
            by_line[l["po_line_id"]].append(l)
    ahead = collections.defaultdict(lambda: [0, 0])
    for pl, ls in by_line.items():
        ls.sort(key=lambda l: (inv[l["invoice_id"]]["imported_at"], l["invoice_id"]))
        prior = Decimal(0)
        for l in ls:
            i = inv[l["invoice_id"]]
            net = sum(q for t, q in received[pl] if t <= i["imported_at"])
            g = "02x" if i["vendor_id"] in g02 else "other"
            ahead[g][1] += 1
            ahead[g][0] += net - prior < Decimal(l["quantity"])
            prior += Decimal(l["quantity"])
    assert ahead["02x"][0] / ahead["02x"][1] > 0.95 and ahead["other"][0] / ahead["other"][1] < 0.03, dict(ahead)
    dr = built["manifest"]["designed_relationships"][0]["realised"]
    assert dr["ven_02x_quantity_blocked"] == qb02 and dr["ven_02x_invoices"] == n02 and dr["other_quantity_blocked"] == qbo
    # the same ordering holds at a monthly cutoff
    for cut in ("2026-03-31T23:59:59Z", "2026-06-30T23:59:59Z"):
        b = derive(result.population, parse_ts(cut))
        blocked = {i for i, st in b.run.invoices.items() if "QUANTITY_BLOCKED" in st.reasons}
        in02 = [i for i in b.in_book if inv[i]["vendor_id"] in g02]
        other = [i for i in b.in_book if inv[i]["vendor_id"] not in g02]
        a = sum(1 for i in in02 if i in blocked) / len(in02)
        o = sum(1 for i in other if i in blocked) / len(other)
        assert a > 3 * o and a > 0.2, (cut, a, o)


def _inputs_of(built):
    m = built["manifest"]
    return {"contract_version": 1, "as_of": m["as_of"], "snapshot_cutoffs": m["snapshot_cutoffs"], "tolerances": m["tolerances"],
            **{k: v for k, v in built["rows"].items() if k in gen.DOMAIN_ENTITIES}}


def test_price_list_vendor_price_variances_begin_in_march_2026(built, result):
    inv = {i["invoice_id"]: i for i in built["rows"]["invoices"]}
    hist = [e for e in built["rows"]["exceptions"] if e["exception_type"] == "PRICE_VARIANCE"]
    mine = [e for e in hist if inv[e["invoice_id"]]["vendor_id"] == "ven-007"]
    assert len(mine) >= 30 and min(e["created_at"] for e in mine)[:7] == "2026-03"
    assert min(inv[e["invoice_id"]]["invoice_date"] for e in mine) >= "2026-03-01"
    assert not [e for e in mine if e["created_at"] < "2026-03-01"]
    assert len(mine) / len(hist) > 0.85                                   # the vendor is the cause, a few noise invoices elsewhere
    live = [e for e in result.metrics["exceptions"]["records"] if e["exception_type"] == "PRICE_VARIANCE"]
    live07 = [e for e in live if inv[e["invoice_id"]]["vendor_id"] == "ven-007"]
    assert len(live07) >= 20 and all(inv[e["invoice_id"]]["invoice_date"] >= "2026-03-01" for e in live07)
    # new prices are +7.5 %: the invoice line price exceeds the PO price; before March the same vendor bills the PO price
    price = {l["po_line_id"]: Decimal(l["unit_price"]) for l in built["rows"]["po_lines"]}
    over = collections.Counter()
    for l in built["rows"]["invoice_lines"]:
        i = inv[l["invoice_id"]]
        if i["vendor_id"] == "ven-007":
            diff = Decimal(l["unit_price"]) - price[l["po_line_id"]]
            over[(i["invoice_date"] >= "2026-03-01", diff > 0)] += 1
    assert over[(False, True)] == 0 and over[(True, True)] >= 30
    # a monthly series: none of the vendor's exceptions in the six months before, some every month from March to July
    by_month = collections.Counter(inv[e["invoice_id"]]["imported_at"][:7] for e in mine)
    assert not [m for m in by_month if m < "2026-03"] and all(by_month[m] > 0 for m in ("2026-03", "2026-04", "2026-05"))


def test_resent_pdfs_cluster_in_the_last_three_days_of_the_month(built, result):
    inv = {i["invoice_id"]: i for i in built["rows"]["invoices"]}

    def month_end(stamp: str) -> bool:
        d = date.fromisoformat(stamp[:10])
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        return (nxt - d).days <= 3

    merged = [r["id"] for r in result.ingest.merged_records if r["reason_code"] == "DUPLICATE_IDENTITY"]
    share = sum(month_end(inv[i]["imported_at"]) for i in merged) / len(merged)
    others = [i["invoice_id"] for i in built["rows"]["invoices"] if i["invoice_id"] not in set(merged)]
    base = sum(month_end(inv[i]["imported_at"]) for i in others) / len(others)
    assert share >= 0.65 and base <= 0.20 and share > 3.5 * base, (share, base)
    by_month = collections.Counter(inv[i]["imported_at"][:7] for i in merged)
    assert len(by_month) >= 10                                            # every month has some: it is the day that clusters
    dr = built["manifest"]["designed_relationships"][2]["realised"]
    assert dr["resent_duplicates"] == 95 and abs(float(dr["share"]) - share) < 0.02


def test_policy_limit_change_governs_who_may_approve(built, result):
    run = result.book.run.invoices
    lim = {"pol-v1": Decimal("5000.00"), "pol-v2": Decimal("8000.00")}
    before, after = [], []
    for a in built["rows"]["approvals"]:
        if a["decision"] != "approve":
            continue
        total = run[a["invoice_id"]].total
        (before if a["decided_at"] < "2026-04-01T00:00:00Z" else after).append(total)
    assert max(before) <= lim["pol-v1"] and lim["pol-v1"] < max(after) <= lim["pol-v2"]
    assert sum(1 for t in after if t > lim["pol-v1"]) >= 10               # approvable only under pol-v2
    over = [i for i in result.book.in_book if result.book.status[i] == "matched" and run[i].total > lim["pol-v1"]]
    assert over and built["manifest"]["designed_relationships"][3]["realised"]["matched_unapproved_over_limit"] >= 20
    assert {a["actor_role"] for a in built["rows"]["approvals"]} == {"reviewer"}
    created = {i["invoice_id"]: i["created_by"] for i in built["rows"]["invoices"]}
    assert all(created[a["invoice_id"]] != a["actor_id"] for a in built["rows"]["approvals"])      # separation of duties holds throughout
    assert any(created[i].startswith("usr-rev") for i in created)        # reviewers do import some invoices (EV-02 relies on it)


# --- injected defects -------------------------------------------------------------------------------------------
def test_manifest_lists_the_twelve_defects(built):
    inj = built["inj"]
    assert sorted(inj) == [f"INJ-{i:02d}" for i in range(1, 13)]
    for i in inj.values():
        assert {"id", "test", "entity", "location", "record_ids", "description", "expected_handling", "handling_kind"} <= set(i)
        assert i["location"] in ("entity_files", "events", "entity_files+events")
        assert i["handling_kind"] in ("merged", "accepted_distinct", "exception", "warned", "replay_only")
    assert sorted(built["events"]) == [f"EV-0{i}" for i in range(1, 8)]
    for e in built["events"].values():
        assert {"event_id", "injection", "steps", "expected_status", "expected_reason", "expected_handling", "expected"} <= set(e)
        assert e["steps"] and all({"command", "headers", "input"} <= set(s) for s in e["steps"])
    # defects that cannot sit in a clean file are replay-only, and the entity files hold no trace of them
    replay = {k for k, v in inj.items() if v["location"] == "events"}
    assert replay == {"INJ-06", "INJ-07", "INJ-08", "INJ-10", "INJ-12"}
    for k in replay:
        assert inj[k]["record_ids"] == [] and inj[k]["events"] and all(e in built["events"] for e in inj[k]["events"])
    for k in sorted(inj):
        for rec in inj[k]["record_ids"]:
            assert re.match(r"^(inv|bat)-\d{3,4}$", rec)
    rows = built["rows"]
    assert len({c["credit_id"] for c in rows["credit_notes"]}) == len(rows["credit_notes"])              # no credit applied twice
    assert not any("paid" in json.dumps(r).lower() for name in ("invoices", "approvals", "export_requests", "export_batches", "credit_notes")
                   for r in rows[name])
    assert len({a["invoice_id"] for a in rows["approvals"] if a["decision"] == "approve"}) == sum(1 for a in rows["approvals"] if a["decision"] == "approve")
    assert not any(i["invoice_id"].startswith("inv-ev") for i in rows["invoices"])                       # events use their own ids


def test_inj_01_same_bytes_under_two_filenames_is_merged(built, result):
    inj = built["inj"]["INJ-01"]
    inv = {i["invoice_id"]: i for i in built["rows"]["invoices"]}
    assert inj["handling_kind"] == "merged" and len(inj["record_ids"]) == 3
    for d in inj["detail"]:
        a, b = inv[d["same_bytes_as"]], inv[d["invoice_id"]]
        assert a["source_sha256"] == b["source_sha256"] == d["source_sha256"] and a["source_filename"] != b["source_filename"]
        assert result.book.status[b["invoice_id"]] == "merged" and result.book.merged_into[b["invoice_id"]] == a["invoice_id"]
        assert result.book.status[a["invoice_id"]] != "merged"
    assert {m["id"]: m["merged_into"] for m in inj["expected_merges"]} == {r["id"]: r["merged_into"] for r in result.ingest.merged_records
                                                                          if r["reason_code"] == "DUPLICATE_SOURCE_BYTES"}


def test_inj_02_reused_number_across_vendors_is_not_a_duplicate(built, result):
    inj = built["inj"]["INJ-02"]
    inv = {i["invoice_id"]: i for i in built["rows"]["invoices"]}
    assert inj["handling_kind"] == "accepted_distinct" and len(inj["detail"]) == 4
    for d in inj["detail"]:
        a, b = (inv[x] for x in d["invoices"])
        assert a["vendor_id"] != b["vendor_id"] and normalise_number(a["invoice_number"]) == normalise_number(b["invoice_number"])
        assert result.book.status[a["invoice_id"]] != "merged" and result.book.status[b["invoice_id"]] != "merged"
    assert any(inv[d["invoices"][0]]["invoice_number"] != inv[d["invoices"][1]]["invoice_number"] for d in inj["detail"])   # case differs
    # no other pair of different vendors shares a normalised number
    seen = collections.defaultdict(set)
    for i in built["rows"]["invoices"]:
        seen[normalise_number(i["invoice_number"])].add(i["vendor_id"])
    cross = {n for n, v in seen.items() if len(v) > 1}
    assert len(cross) == 4


@pytest.mark.parametrize("inj_id,reason", [("INJ-03", "QUANTITY_BLOCKED"), ("INJ-04", "QUANTITY_BLOCKED"),
                                           ("INJ-05", "ROUNDING_EXCEPTION"), ("INJ-09", "CURRENCY_MISMATCH")])
def test_injected_exceptions_are_raised_by_the_domain_with_the_listed_reason(built, result, inj_id, reason):
    inj = built["inj"][inj_id]
    assert inj["handling_kind"] == "exception" and inj["expected_exceptions"]
    live = {(e["invoice_id"], e["exception_type"]) for e in result.metrics["exceptions"]["records"]}
    for e in inj["expected_exceptions"]:
        assert e["reason_code"] == reason and (e["invoice_id"], reason) in live, e
        assert result.book.status[e["invoice_id"]] == "exception"
    assert len(inj["expected_exceptions"]) == len(inj["record_ids"])


def test_inj_03_receipts_fall_short_and_inj_04_is_cumulative(built, result):
    inv = {i["invoice_id"]: i for i in built["rows"]["invoices"]}
    lines = {l["invoice_line_id"]: l for l in built["rows"]["invoice_lines"]}
    for d in built["inj"]["INJ-03"]["detail"]:
        assert Decimal(d["received_quantity"]) < Decimal(d["invoiced_quantity"]) and Decimal(d["received_quantity"]) >= Decimal("0.6") * Decimal(d["invoiced_quantity"]) - Decimal("1")
        assert lines[d["invoice_line_id"]]["quantity"] == d["invoiced_quantity"]
    net = collections.defaultdict(Decimal)
    for rc in built["rows"]["receipts"]:
        if not rc["reversed"]:
            net[rc["po_line_id"]] += Decimal(rc["received_quantity"])
    for d in built["inj"]["INJ-04"]["detail"]:
        pl = d["po_line_id"]
        # each invoice alone is within what was received; together they are not
        assert Decimal(d["first_quantity"]) <= net[pl] and Decimal(d["second_quantity"]) <= net[pl]
        assert Decimal(d["first_quantity"]) + Decimal(d["second_quantity"]) > net[pl]
        assert result.book.status[d["first_invoice"]] in ("approved", "exported", "adjusted", "matched")
        row = next(r for r in result.book.run.lines if r.invoice_id == d["invoice_id"])
        assert row.reason_code == "QUANTITY_BLOCKED" and row.available == 0 and row.quantity_variance > 0
    # small gaps (up to 0.02) are tolerated and disclosed, the injected ones are larger
    for d in built["inj"]["INJ-05"]["detail"]:
        assert Decimal(d["difference"]) > Decimal("0.02")
    tolerated = {t["invoice_id"] for t in disclosures(result.population, result.book)["rounding_tolerated_invoices"]}
    assert tolerated and not tolerated & {d["invoice_id"] for d in built["inj"]["INJ-05"]["detail"]}


def test_inj_09_currency_mismatch_invoices_are_in_a_currency_other_than_the_po(built, result):
    po_cur = {p["po_id"]: p["currency"] for p in built["rows"]["purchase_orders"]}
    line_po = {l["po_line_id"]: l["po_id"] for l in built["rows"]["po_lines"]}
    inv_line = {}
    for l in built["rows"]["invoice_lines"]:
        inv_line.setdefault(l["invoice_id"], l)
    inv = {i["invoice_id"]: i for i in built["rows"]["invoices"]}
    for d in built["inj"]["INJ-09"]["detail"]:
        i = inv[d["invoice_id"]]
        assert po_cur[line_po[inv_line[i["invoice_id"]]["po_line_id"]]] == d["po_currency"] != i["currency"] == d["invoice_currency"]
    assert sum(1 for i in built["rows"]["invoices"]
               if i["currency"] != po_cur[line_po[inv_line[i["invoice_id"]]["po_line_id"]]]) == 3


def test_inj_11_repeated_exports_return_the_prior_batch(built, result):
    inj = built["inj"]["INJ-11"]
    assert inj["handling_kind"] == "warned" and len(inj["detail"]) == 7
    assert result.metrics["export"]["repeat_requests_returned_prior"] == len(inj["record_ids"]) == 7
    assert {d["batch_id"] for d in inj["detail"]} == set(inj["record_ids"])
    rows = [r for r in result.metrics["export"]["rows"] if r["batch_id"] in set(inj["record_ids"])]
    assert len({r["invoice_id"] for r in rows}) == len(rows)              # no second row for the repeat


def test_replay_events_refer_to_rows_that_exist(built, result):
    po_lines = {l["po_line_id"]: l for l in built["rows"]["po_lines"]}
    vendors = {v["vendor_id"] for v in built["rows"]["vendors"]}
    run = result.book.run
    seen_lines: dict[str, str] = {}
    for ev in built["events"].values():
        for s in ev["steps"]:
            assert s["input"]["dataset_version"] == VERSION and s["headers"]["X-Actor-Id"] and s["headers"]["X-Actor-Role"] in ("clerk", "reviewer", "admin")
            inp = s["input"]["input"]
            if s["command"] == "import-invoice" and inp["invoice_id"].endswith("a"):
                assert inp["vendor_id"] in vendors
                for l in inp["lines"]:
                    assert l["po_line_id"] in po_lines and seen_lines.setdefault(l["po_line_id"], ev["event_id"]) == ev["event_id"]
                    # received quantity left over by the matched invoices covers the event's invoice: it will match
                    assert run.net[l["po_line_id"]] - run.consumed[l["po_line_id"]] >= Decimal(l["quantity"]), ev["event_id"]
                    assert po_lines[l["po_line_id"]]["unit_price"] == l["unit_price"]
    assert len(seen_lines) == 7


# --- PostgreSQL (needs DATABASE_URL) ---------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def loaded(inputs, built):
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    import psycopg
    from psycopg.rows import dict_row
    from data import migrate, seed
    with psycopg.connect(url) as c:
        migrate.reset(c)
        migrate.apply_migrations(c)
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as c:
        out = seed.seed(c, inputs)
        yield c, out


def test_seed_loads_the_generated_files(loaded, inputs, result, built):
    conn, out = loaded
    assert out["skipped"] == 0 and not result.rejected
    for name in ("vendors", "purchase_orders", "po_lines", "receipts", "invoices", "invoice_lines", "credit_notes",
                 "approval_policies", "approvals"):
        assert out["inserted"].get(name, len(inputs[name])) == len(inputs[name]), name
        assert conn.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"] == len(inputs[name]), name
    n = lambda t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
    assert n("rejected_records") == 0 and n("export_batches") == len(built["rows"]["export_batches"])
    assert n("export_requests") == len(built["rows"]["export_requests"]) and n("export_rows") == result.metrics["obligations"]["count"]
    assert conn.execute("SELECT count(*) AS n FROM invoices WHERE status = 'merged'").fetchone()["n"] == 98
    assert conn.execute("SELECT count(*) AS n FROM import_lineage").fetchone()["n"] == 2800
    stored = {r["invoice_id"]: r["status"] for r in conn.execute("SELECT invoice_id, status FROM invoices").fetchall()}
    assert stored == result.book.status
    # the exception history (resolved exceptions and the assignment trail) replaces the derived positional rows
    conn.execute("DELETE FROM exceptions")
    for e in built["rows"]["exceptions"]:
        conn.execute("INSERT INTO exceptions (exception_id, invoice_id, exception_type, status, owner_id, created_at, resolved_at) "
                     "VALUES (%(exception_id)s, %(invoice_id)s, %(exception_type)s, %(status)s, %(owner_id)s, %(created_at)s, %(resolved_at)s)", e)
    for a in built["rows"]["exception_assignments"]:
        conn.execute("INSERT INTO exception_assignments (assignment_id, exception_id, owner_id, assigned_by, assigned_at, note) "
                     "VALUES (%(assignment_id)s, %(exception_id)s, %(owner_id)s, %(assigned_by)s, %(assigned_at)s, %(note)s)", a)
    assert n("exceptions") == len(built["rows"]["exceptions"]) and n("exception_assignments") == len(built["rows"]["exception_assignments"])
    conn.execute("SELECT setval('exception_seq', %s)", (len(built["rows"]["exceptions"]),))


def _with_history(pop, built):
    """The population with the stored exception records and assignment history the database now holds (the SQL reference
    takes the id and owner of a derived exception from them; the preferred record of a pair is the last in the list)."""
    from invoicebridge.models import Assignment, ExceptionRecord
    exc = sorted(built["rows"]["exceptions"], key=lambda e: (e["status"] != "resolved", e["created_at"], e["exception_id"]))
    return dataclasses.replace(
        pop, exceptions=[ExceptionRecord(e["exception_id"], e["invoice_id"], e["exception_type"]) for e in exc],
        assignments=[Assignment(a["exception_id"], a["owner_id"], parse_ts(a["assigned_at"])) for a in built["rows"]["exception_assignments"]])


@pytest.mark.parametrize("as_of", ["2026-10-01T02:00:00Z", "2026-03-31T23:59:59Z", "2026-06-30T23:59:59Z"],
                         ids=["full-window", "to-2026-03-31", "to-2026-06-30"])
def test_sql_reference_agrees_with_the_domain(loaded, inputs, result, built, as_of):
    conn, _ = loaded
    sql = (ROOT / "data" / "sql" / "reference_metrics.sql").read_text()
    cuts = [parse_ts(c) for c in inputs["snapshot_cutoffs"]]
    row = conn.execute(sql, {"as_of": parse_ts(as_of), "cutoffs": cuts}).fetchone()
    want = compute_metrics(_with_history(result.population, built), parse_ts(as_of), cuts)
    assert set(row) == set(want) == set(METRIC_KEYS)
    for k in METRIC_KEYS:
        assert row[k] == want[k], (k, str(row[k])[:160], str(want[k])[:160])
    assert want["matched"]["invoice_count"] > 100 and want["approvals"]["valid_count"] > 100
    if as_of.startswith("2026-10"):
        assert want["obligations"]["count"] > 2000 and want["exceptions"]["open_count"] > 100
    else:                                                                 # a month-end snapshot is a smaller, different book
        full = compute_metrics(result.population, parse_ts("2026-10-01T02:00:00Z"), [])
        assert want["obligations"]["count"] < full["obligations"]["count"]


def test_monthly_windows_of_the_domain_are_consistent_with_the_whole(result):
    """The SQL reference has no window parameter (as-of only); the domain's half-open window of import instants is checked
    against the cumulative as-of view: a window [from, to) is the as-of(to) book restricted to invoices imported in it."""
    for lo, hi in (("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"), ("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")):
        w = window_metrics(result.population, (parse_ts(lo), parse_ts(hi)), [])["metrics"]
        month = [i.invoice_id for i in result.population.invoices if parse_ts(lo) <= i.imported_at < parse_ts(hi)]
        assert w["rates"]["eligible_invoices"] <= len(month) and w["rates"]["eligible_invoices"] > 150
        assert w["duplicates"]["rows_merged"] > 0 and w["exceptions"]["open_count"] == len(w["exceptions"]["records"])
    by_vendor = window_metrics(result.population, (parse_ts("2026-03-01T00:00:00Z"), parse_ts("2026-04-01T00:00:00Z")), [], "vendor")["groups"]
    assert len(by_vendor) >= 35 and sum(g["metrics"]["rates"]["eligible_invoices"] for g in by_vendor) > 150


def _race(n, fn):
    from fastapi.testclient import TestClient
    from api.app import create_app
    gate = threading.Barrier(n)
    clients = [TestClient(create_app(), raise_server_exceptions=False) for _ in range(n)]

    def run(i):
        gate.wait()
        return fn(i, clients[i])
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


def test_replay_events_behave_as_recorded(loaded, inputs, built):
    from fastapi.testclient import TestClient
    from api.app import PREFIX, create_app
    conn, _ = loaded
    version = lambda: conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()["dataset_version"]

    def post(client, step):
        # the replay carries the dataset_version a client has just read from the API, not the generator's label
        body = {**step["input"], "dataset_version": version()}
        return client.post(f"{PREFIX}/commands/{step['command']}", json=body, headers=step["headers"])

    def n(sql, *args):
        return conn.execute(sql, args).fetchone()["n"]

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        for eid, ev in sorted(built["events"].items()):
            steps = ev["steps"]
            k = ev.get("concurrent_last", 1)
            responses = [post(client, s) for s in steps[:-k]]
            for r in responses:
                assert r.status_code == 200, (eid, r.text)
            if k > 1:
                tail = _race(k, lambda i, c: c.post(f"{PREFIX}/commands/{steps[-k + i]['command']}", headers=steps[-k + i]["headers"],
                                                    json={**steps[-k + i]["input"], "dataset_version": version()}))
                assert sorted(r.status_code for r in tail) == ev["expected"]["concurrent_statuses"], (eid, [r.text for r in tail])
                last = next(r for r in tail if r.status_code != 200)
            else:
                last = post(client, steps[-1])
            assert last.status_code == ev["expected_status"], (eid, last.text)
            body = last.json()
            exp = ev["expected"]
            iid = next((s["input"]["input"].get("invoice_id") for s in steps if "invoice_id" in s["input"]["input"]), None)
            if ev["expected_status"] != 200:
                err = body["error"]
                assert ev["expected_reason"] in {err["code"]} | {d["rule_id"] for d in err["details"]}, (eid, body)
            if eid == "EV-01":
                res = body["result"]
                assert {k: res[k] for k in exp} == exp
                assert body["warnings"][0]["code"] == "DUPLICATE_SOURCE_BYTES"
                assert n("SELECT count(*) AS n FROM invoices WHERE invoice_id = 'inv-ev01b' AND status = 'merged'") == 1
            elif eid == "EV-02":
                assert body["error"]["code"] == "SELF_APPROVAL"
                assert conn.execute("SELECT status FROM invoices WHERE invoice_id = %s", (iid,)).fetchone()["status"] == exp["invoice_status_after"]
                assert n("SELECT count(*) AS n FROM approvals WHERE invoice_id = %s", iid) == exp["approvals_rows"]
                assert n("SELECT count(*) AS n FROM audit_events WHERE invoice_id = %s AND action = 'approve-invoice-refused'", iid) == 1
            elif eid == "EV-03":
                assert n("SELECT count(*) AS n FROM approvals WHERE invoice_id = %s", iid) == exp["approvals_rows"]
                assert conn.execute("SELECT status FROM invoices WHERE invoice_id = %s", (iid,)).fetchone()["status"] == exp["invoice_status_after"]
            elif eid == "EV-04":
                assert n("SELECT count(*) AS n FROM credit_notes WHERE invoice_id = %s", iid) == exp["credit_rows"]
                assert body["error"]["code"] == "CREDIT_ALREADY_APPLIED"
                assert conn.execute("SELECT credit_amount FROM credit_notes WHERE invoice_id = %s", (iid,)).fetchone()["credit_amount"] == Decimal(exp["credit_total"])
            elif eid == "EV-05":
                assert n("SELECT count(*) AS n FROM invoice_lines WHERE invoice_id = %s", iid) == exp["lines_after"]
                assert conn.execute("SELECT source_sha256 FROM invoices WHERE invoice_id = %s", (iid,)).fetchone()["source_sha256"].strip() == exp["source_sha256_after"]
            elif eid == "EV-06":
                assert last.headers.get("Idempotent-Replay") == "true" and last.json() == responses[-1].json()
                assert last.json()["result"]["rows"][0]["amount"] == exp["amount"]
                assert n("SELECT count(*) AS n FROM export_rows WHERE batch_id = 'bat-ev06'") == exp["export_rows"]
                outcomes = sorted(r["outcome"] for r in conn.execute("SELECT outcome FROM export_requests WHERE batch_id = 'bat-ev06'").fetchall())
                assert outcomes == sorted(exp["outcomes"]) and len(outcomes) == exp["export_requests"]
            elif eid == "EV-07":
                assert any(d["rule_id"] == "FIELD_UNEXPECTED" for d in body["error"]["details"])
                assert n("SELECT count(*) AS n FROM export_rows WHERE batch_id = 'bat-ev07'") == exp["export_rows"]
                assert conn.execute("SELECT status FROM invoices WHERE invoice_id = %s", (iid,)).fetchone()["status"] == exp["invoice_status_after"]
        # nothing in the system marks anything paid
        assert n("SELECT count(*) AS n FROM invoices WHERE status = 'paid'") == 0


def test_the_loaded_history_is_served_by_the_api(loaded, built):
    from fastapi.testclient import TestClient
    from api.app import PREFIX, create_app
    conn, _ = loaded
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        r = client.get(f"{PREFIX}/data/exceptions", params={"limit": 200, "status": "resolved"})
        assert r.status_code == 200 and r.json()["meta"]["total_count"] == sum(1 for e in built["rows"]["exceptions"] if e["status"] == "resolved")
        owner = next(e["owner_id"] for e in built["rows"]["exceptions"] if e["owner_id"])
        r = client.get(f"{PREFIX}/data/exception_assignments", params={"limit": 200, "owner_id": owner})
        assert r.status_code == 200 and r.json()["meta"]["total_count"] == sum(1 for a in built["rows"]["exception_assignments"] if a["owner_id"] == owner)
        r = client.get(f"{PREFIX}/metrics", params={"from": "2026-03-01", "to": "2026-04-01", "group_by": "vendor"})
        assert r.status_code == 200 and len(r.json()["data"]["groups"]) >= 35
