"""The two variants through the domain, the ingest and the database: rejection is atomic, dependent and never silent; absence is null."""
from trustledger import run_pipeline

from support_db import conn, count, db_url, golden_expected, golden_inputs, load  # noqa: F401


def test_variant_rejected_lists_every_rejection_with_reason_and_raw_row():
    res = run_pipeline(golden_inputs("variant-rejected"))
    got = [(r["entity"], r["id"], r["reason_code"]) for r in res.rejected]
    assert got == [("dataset_rows", "ds-orphan", "DEPENDENT_REJECTED"), ("datasets", "ds-orphan", "OWNER_REQUIRED"), ("fields", "fld-009", "DEPENDENT_REJECTED"),
                   ("match_candidates", "cand-002", "DUPLICATE_PAIR"), ("merge_decisions", "md-2", "DEPENDENT_REJECTED"),
                   ("merge_decisions", "md-3", "REVIEWER_IS_PROPOSER"), ("merge_decisions", "md-4", "DEPENDENT_REJECTED"),
                   ("quality_rules", "r-orphan-complete", "DEPENDENT_REJECTED"), ("rule_runs", "rr-001", "DEPENDENT_REJECTED")]
    assert got == sorted(got)                                                       # sorted by entity, id
    raw = {(r["entity"], r["id"]): r["raw_row"] for r in res.rejected}
    assert raw[("match_candidates", "cand-002")]["left_record_id"] == "rec-002" and len(raw[("dataset_rows", "ds-orphan")]["rows"]) == 3          # the rejected batch is kept whole
    assert res.counts["datasets"] == {"accepted": 1, "rejected": 1} and res.counts["dataset_rows"] == {"accepted": 4, "rejected": 3}
    assert res.counts["merge_decisions"] == {"accepted": 1, "rejected": 3} and res.counts["match_candidates"] == {"accepted": 2, "rejected": 1}


def test_variant_rejected_measures_what_remains():
    m = run_pipeline(golden_inputs("variant-rejected")).metrics
    (rule, comp), = m["completeness"].items()
    assert comp["value"] == "0.750000"
    ws = m["weighted_score"]["datasets"]["ds-customers"]
    assert (ws["value"], ws["measured_dimensions"], ws["critical_override"]) == ("0.750000", ["completeness"], False)
    assert m["ownership_coverage"]["value"] == "1.000000" and m["ownership_coverage"]["datasets"] == 1          # ds-orphan is not in the denominator
    assert m["match_precision"] == {"approved_decisions": 1, "approved_correct": 1, "precision": "1.000000", "reviewed": 1, "reviewed_correct": 1,
                                    "reviewed_correct_share": "1.000000"}
    assert "ds-orphan" not in m["weighted_score"]["datasets"]


def test_variant_empty_is_all_zero_counts_and_null_ratios_never_zero_ratios():
    res = run_pipeline(golden_inputs("variant-empty"))
    m = res.metrics
    assert res.empty_population is True
    assert m["completeness"] == m["validity"] == m["uniqueness"] == m["relationship_integrity"] == {}
    assert m["timeliness"]["value"] is None and m["ownership_coverage"]["value"] is None and m["definition_coverage"]["value"] is None
    assert m["lineage_coverage"]["value"] is None and m["match_precision"]["precision"] is None and m["resolution_time"]["mean_hours"] is None
    assert m["weighted_score"]["datasets"] == {} and m["critical_failures"] == {"failures": 0, "open_issues": 0, "datasets_overridden": 0, "carried": []}
    assert all(c == {"accepted": 0, "rejected": 0} for c in res.counts.values())
    assert "0.000000" not in str(m)


def test_db_keeps_rejected_rows_raw_and_does_not_load_them(conn):
    first = load(conn, golden_inputs("variant-rejected"))
    assert first["skipped"] == 9 and first["inserted"]["datasets"] == 1 and first["inserted"]["match_candidates"] == 2 and first["inserted"]["merge_decisions"] == 1
    assert count(conn, "rejected_records") == 9 and count(conn, "rejected_records", "reason_code = 'DEPENDENT_REJECTED'") == 6
    raw = conn.execute("SELECT raw_row FROM rejected_records WHERE id = 'cand-002'").fetchone()["raw_row"]
    assert raw["left_record_id"] == "rec-002" and raw["right_record_id"] == "rec-001"                      # the reverse-order twin, as sent
    assert count(conn, "datasets", "dataset_id = 'ds-orphan'") == 0 and count(conn, "dataset_rows", "dataset_id = 'ds-orphan'") == 0
    again = load(conn, golden_inputs("variant-rejected"))
    assert sum(again["inserted"].values()) == 0 and again["dataset_version"] == first["dataset_version"]
    assert count(conn, "rejected_records") == 9 and count(conn, "dataset_versions") == 1


def test_db_variant_empty_has_nothing_but_the_configuration(conn):
    load(conn, golden_inputs("variant-empty"))
    assert sum(count(conn, t) for t in ("owners", "datasets", "dataset_rows", "quality_rules", "rule_runs", "issues", "merge_decisions", "match_candidates")) == 0
    assert count(conn, "rule_weight_versions") == 2 and count(conn, "ledger_config") == 1
