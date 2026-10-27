"""The three hash kinds of D-P8-10, recomputed from the documented rules (P08-GOLD-10): payload_hash, content_hash, definition_hash."""
import hashlib
import json

import pytest
from pipeline_observatory import run_pipeline
from pipeline_observatory.hashing import canonical_json, content_hash, definition_hash, payload_hash

from support_db import GOLDEN, VARIANTS, golden_inputs


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_payload_hash_is_the_sha256_of_the_canonical_payload(variant):
    for r in golden_inputs(variant)["raw_records"]:
        text = json.dumps(r["payload_json"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)      # the rule, written out again here
        assert hashlib.sha256(text.encode()).hexdigest() == r["payload_hash"] == payload_hash(r["payload_json"]), r["raw_record_id"]


def test_the_golden_has_31_payload_hashes_and_the_duplicate_shares_its_hash():
    raws = golden_inputs()["raw_records"]
    assert len(raws) == 31
    by = {r["raw_record_id"]: r["payload_hash"] for r in raws}
    assert by["rr-b-001-03"] == by["rr-b-001-06"]                                  # ORD-1003 and its duplicate: same payload, same hash


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_definition_hash_is_the_sha256_of_the_definition_text(variant):
    for m in golden_inputs(variant)["model_definitions"]:
        assert hashlib.sha256(m["definition"].encode()).hexdigest() == m["definition_hash"] == definition_hash(m["definition"])


@pytest.mark.parametrize("variant", ["", "variant-rejected"])
def test_every_content_hash_is_the_sha256_of_the_sorted_payload_hashes_joined_by_newlines(variant):
    inputs = golden_inputs(variant)
    res = run_pipeline(inputs)
    from pipeline_observatory.metrics import derive                                  # the accepted records per batch, as the domain classified them
    facts = derive(res.imported.accepted)
    for p in inputs["publications"]:
        hashes = sorted(a.payload_hash for a in facts.accepted if a.batch_id in p["included_batch_ids"])
        assert hashlib.sha256("\n".join(hashes).encode()).hexdigest() == p["content_hash"] == content_hash(hashes), p["publication_id"]
        assert res.metrics["publications"]["publications"][p["publication_id"]]["content_hash_ok"] is True


def test_a_tampered_payload_or_publication_is_detected():
    inputs = golden_inputs()
    inputs["publications"][0]["content_hash"] = "0" * 64
    assert run_pipeline(inputs).metrics["publications"]["publications"]["pub-001"]["content_hash_ok"] is False
    changed = golden_inputs()
    changed["raw_records"][0]["payload_hash"] = payload_hash({**changed["raw_records"][0]["payload_json"], "quantity": 99})
    assert run_pipeline(changed).metrics["publications"]["publications"]["pub-001"]["content_hash_ok"] is False        # the published set no longer matches


def test_canonical_json_is_key_order_independent_ascii_and_compact():
    assert canonical_json({"b": 1, "a": [2, {"d": 1, "c": 2}]}) == '{"a":[2,{"c":2,"d":1}],"b":1}'
    assert payload_hash({"a": 1, "b": 2}) == payload_hash({"b": 2, "a": 1})
    assert canonical_json({"name": "café"}) == '{"name":"caf\\u00e9"}'
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_content_hash_ignores_order_and_changes_with_membership():
    a, b, c = (payload_hash({"k": i}) for i in range(3))
    assert content_hash([a, b, c]) == content_hash([c, a, b]) != content_hash([a, b])


def test_the_fixture_hash_file_matches_the_files_on_disk():
    stored = json.loads((GOLDEN / "HASHES.json").read_text())["sha256"]
    for rel, want in stored.items():
        assert hashlib.sha256((GOLDEN / rel).read_bytes()).hexdigest() == want, rel
