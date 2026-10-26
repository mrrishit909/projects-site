"""The golden fixture through the pure domain: every figure equals expected.json key by key (P05-GOLD-01..)."""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from invoicebridge import run_pipeline
from invoicebridge.contract import ENTITIES, METRIC_KEYS

from support_db import golden_expected, golden_inputs


def flat(x, path=""):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            out.update(flat(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(x, list):
        if not x:
            return {path + "[]": "empty"}
        out = {}
        for i, v in enumerate(x):
            out.update(flat(v, f"{path}[{i}]"))
        return out
    return {path: x}


@pytest.fixture(scope="module")
def result():
    return run_pipeline(golden_inputs())


@pytest.mark.parametrize("key", METRIC_KEYS)
def test_metric_equals_expected(result, key):
    exp = golden_expected()["metrics"]
    assert result.metrics[key] == exp[key]


def test_metric_names_are_exactly_the_expected_keys_and_snapshot_cutoffs_travel_beside(result):
    exp = golden_expected()["metrics"]
    assert list(result.metrics) == list(exp) == list(METRIC_KEYS)
    assert result.snapshot_cutoffs == golden_inputs()["snapshot_cutoffs"] == list(exp["snapshots"])


def test_whole_golden_shape_equals_expected_json(result):
    assert result.golden() == golden_expected()


def test_every_leaf_of_expected_json_is_reproduced_and_nothing_else_is_emitted(result):
    fe, fg = flat(golden_expected()), flat(result.golden())
    assert set(fe) == set(fg)
    assert [k for k in fe if fe[k] != fg[k]] == []
    assert len(fe) == 148                       # the number of leaves of the golden expected.json


@pytest.mark.parametrize("entity", ENTITIES)
def test_ingest_counts_per_entity(result, entity):
    assert result.counts[entity] == golden_expected()["ingest"]["counts"][entity]


def test_spec_sentence_figures(result):
    """PO 10 at 20, receipt 6, invoice 6 -> 120 + 12 tax = 132; the second invoice for 4 is blocked; one obligation."""
    docs = result.documents()["invoices"]
    assert (docs["inv-001"]["subtotal"], docs["inv-001"]["tax"], docs["inv-001"]["total"]) == ("120.00", "12.00", "132.00")
    assert docs["inv-002"]["status"] == "exception" and docs["inv-002"]["exception_types"] == ["QUANTITY_BLOCKED"]
    assert docs["inv-003"]["status"] == "merged" and docs["inv-003"]["merged_into"] == "inv-001"
    m = result.metrics
    assert (m["obligations"]["count"], m["obligations"]["total"]) == (1, "132.00")
    assert m["quantities"]["invoiced_not_received_value"] == "80.00"


def test_blocked_invoice_matches_once_the_receipt_arrives():
    """CALCULATION.md: inv-002 would match only after net received >= 10."""
    d = golden_inputs()
    d["receipts"].append({"receipt_id": "rc-002", "po_line_id": "pol-001", "received_quantity": "4",
                          "received_at": "2026-10-06T08:00:00Z", "reversed": False})
    docs = run_pipeline(d).documents()["invoices"]
    assert docs["inv-002"]["status"] == "matched" and docs["inv-002"]["exception_types"] == []


def test_domain_source_has_no_float():
    """No float anywhere in the domain package: no float() call, no float literal, no total_seconds() (a float); minutes and
    rates are Fractions rendered by integer arithmetic."""
    root = Path(__file__).resolve().parents[1] / "domain" / "invoicebridge"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), f"{path.name}:{node.lineno} float literal"
            assert not (isinstance(node, ast.Name) and node.id == "float"), f"{path.name}:{node.lineno} float"
            assert not (isinstance(node, ast.Attribute) and node.attr in ("total_seconds",)), f"{path.name}:{node.lineno} float seconds"


def test_subprocess_reference_check_is_independent_of_the_domain():
    """reference_check.py imports nothing from the application; it still agrees (also run as a script by the CI gate)."""
    p = Path(__file__).resolve().parent / "reference_check.py"
    out = subprocess.run([sys.executable, "-I", str(p)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and "ALL OK (412 checks)" in out.stdout
    assert sum(1 for l in out.stdout.splitlines() if l.startswith("OK hash.")) == 7


def test_expected_json_has_no_float_numbers():
    text = (Path(__file__).resolve().parent / "fixtures" / "golden" / "expected.json").read_text()
    json.loads(text, parse_float=lambda s: pytest.fail(f"float {s} in expected.json"))
