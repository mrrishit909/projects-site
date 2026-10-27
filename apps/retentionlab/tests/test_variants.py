"""The two variants through the domain, the loader and the database: rejection is atomic, dependent and never silent; absence is null."""
from retentionlab import evaluate

from support_db import JAN, conn, count, db_url, golden_expected, golden_inputs, load  # noqa: F401


def test_variant_rejected_lists_every_rejection_with_its_reason_in_processing_order():
    out = evaluate(golden_inputs("variant-rejected"))
    got = [(r["entity"], r["id"], r["reason_code"]) for r in out["ingest"]["rejected_records"]]
    assert got == [(r["entity"], r["id"], r["reason_code"]) for r in golden_expected("variant-rejected")["ingest"]["rejected_records"]]
    assert len(got) == 18
    codes = {c for _, _, c in got}
    assert codes == {"SYNTHETIC_REQUIRED", "DUPLICATE_ID", "AVAILABILITY_BEFORE_EVENT", "UNKNOWN_ACCOUNT", "DEPENDENT_REJECTED", "UNKNOWN_CUTOFF",
                     "CENSORED_LABEL", "PROBABILITY_OUT_OF_RANGE", "UNKNOWN_TRAINING_RUN", "UNKNOWN_SCENARIO", "OUTREACH_NOT_DRAFT"}


def test_variant_rejected_measures_what_remains():
    s = evaluate(golden_inputs("variant-rejected"))["cutoff_sets"][JAN]
    assert s["churn_rate"] == {"value": "0.250000", "churned": 1, "mature_eligible": 4}
    assert s["population"]["unscored_excluded"] == 1 and s["average_precision"]["value"] == "0.500000"      # the tie is ONE threshold, not rank order
    assert s["risk_lift_at_k"]["value"] == "3.000000" and s["risk_lift_at_k"]["tie_split_at_k"] is True
    assert s["economics"]["expected_value"] == "2.00" and s["feature_missingness"]["overall"]["value"] == "0.437500"


def test_variant_rejected_commands_are_refused_with_the_first_code_in_priority_order():
    cmds = evaluate(golden_inputs("variant-rejected"))["commands"]
    assert [c["reason_code"] for c in cmds] == ["POST_OUTCOME_FIELD", "LATENT_TRUTH", "ID_FEATURE", "POST_OUTCOME_FIELD", "UNKNOWN_FEATURE", "LEAKAGE",
                                                "CALIBRATION_ON_FIT_ROWS", "THRESHOLD_ON_TEST", "CAPACITY_EXCEEDS_POPULATION"]
    assert [o["item"] for o in cmds[3]["offending"]] == ["cancellation_reason", "account_id"]              # both listed, the first kind is the code
    assert all(c["status"] == "refused" and c["result"] is None for c in cmds)


def test_variant_empty_is_all_zero_counts_and_null_ratios_never_zero_ratios():
    out = evaluate(golden_inputs("variant-empty"))
    s = out["cutoff_sets"][JAN]
    assert out["empty_population"] is True and s["empty_population"] is True
    assert s["churn_rate"]["value"] is None and s["average_precision"]["value"] is None and s["brier_score"]["value"] is None
    assert s["population_drift"]["psi"] is None and s["feature_missingness"]["overall"]["value"] is None
    assert all(c == {"accepted": 0, "rejected": 0} for c in out["ingest"]["counts"].values())
    assert out["freshness"]["scoring_hours"] is None and out["freshness"]["data_hours"] is None
    assert [b["count"] for b in s["calibration"]["bins"]] == [0] * 10 and all(b["gap_pp"] is None for b in s["calibration"]["bins"])


def test_db_keeps_rejected_rows_raw_and_does_not_load_them(conn):
    first = load(conn, golden_inputs("variant-rejected"))
    assert first["skipped"] == 18 and first["inserted"]["accounts"] == 6 and first["inserted"]["predictions"] == 3
    assert count(conn, "rejected_records") == 18 and count(conn, "rejected_records", "reason_code = 'DEPENDENT_REJECTED'") == 5
    raw = conn.execute("SELECT raw_row FROM rejected_records WHERE entity = 'accounts' AND id = '97'").fetchone()["raw_row"]
    assert raw["synthetic"] is False                                                                      # the row as sent
    dup = conn.execute("SELECT raw_row FROM rejected_records WHERE reason_code = 'DUPLICATE_ID'").fetchone()["raw_row"]
    sent = [a for a in golden_inputs("variant-rejected")["accounts"] if a["account_id"] == 3]
    assert dup == sent[1] and conn.execute("SELECT segment FROM accounts WHERE account_id = 3").fetchone()["segment"] == sent[0]["segment"]   # the SECOND row was rejected, the first stays
    assert count(conn, "accounts", "account_id IN (97, 98, 99)") == 0
    again = load(conn, golden_inputs("variant-rejected"))
    assert sum(again["inserted"].values()) == 0 and again["dataset_version"] == first["dataset_version"]
    assert count(conn, "rejected_records") == 18 and count(conn, "dataset_versions") == 1


def test_db_variant_empty_has_nothing_but_the_versions(conn):
    load(conn, golden_inputs("variant-empty"))
    assert sum(count(conn, t) for t in ("accounts", "subscription_events", "prediction_cutoffs", "predictions", "training_runs", "outreach_events")) == 0
    assert count(conn, "label_versions") == 1 and count(conn, "feature_versions") == 1 and count(conn, "dataset_versions") == 1
