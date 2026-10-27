-- P10-ART-04 investigation 04: the censored tail by cutoff (D-01 censoring, D-07 DR-05, D-09 R10-04).
-- Question: how many eligible cutoff rows have an outcome window that has not closed at the as-of, and what would the churn rate look like if they were
-- (wrongly) counted as retained? A row is MATURE only when label_end = horizon_end + 14 days <= as_of (2026-10-05T00:00:00Z); a censored row is excluded from every
-- evaluation and is never labelled non-churn (its stored label is NULL). Two populations, kept apart: the 200-account cohort rebuilt here from the loaded entity
-- tables, and the whole 2,400-account world published per cutoff in cutoff_aggregates.json (art_cutoff_aggregate; not recomputable from the cohort).
-- @@ world_by_cutoff
SELECT prediction_at, split_range, cutoff_rows, eligible, mature, censored, churned,
       round(censored::numeric / eligible, 6) AS censored_share,
       round(churned::numeric / NULLIF(mature, 0), 6) AS mature_churn_rate,
       (SELECT value::numeric FROM art_published_claim c WHERE c.claim = 'naive_rate_if_censored_were_non_churn_' || to_char(a.prediction_at, 'YYYY-MM-DD')) AS published_rate_if_censored_were_non_churn,
       round((SELECT value::numeric FROM art_published_claim c WHERE c.claim = 'naive_rate_if_censored_were_non_churn_' || to_char(a.prediction_at, 'YYYY-MM-DD')) * eligible) AS implied_cancellations_seen_so_far,
       (prediction_at + interval '104 days' > (SELECT as_of FROM dataset_versions ORDER BY as_of DESC LIMIT 1)) AS window_still_open_at_as_of
FROM art_cutoff_aggregate a ORDER BY prediction_at;
-- @@ world_summary
SELECT sum(eligible) AS eligible_rows, sum(mature) AS mature_rows, sum(censored) AS censored_rows, sum(churned) AS mature_churned_rows,
       round(sum(censored)::numeric / sum(eligible), 6) AS censored_share, round(sum(churned)::numeric / sum(mature), 6) AS mature_churn_rate,
       count(*) FILTER (WHERE censored > 0) AS cutoffs_with_censored_rows, min(prediction_at) FILTER (WHERE censored > 0) AS first_censored_cutoff
FROM art_cutoff_aggregate;
-- @@ cohort_by_cutoff
SELECT pc.prediction_at, count(*) AS cohort_cutoff_rows, count(fr.feature_row_id) AS eligible,
       count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND l.mature) AS mature,
       count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND NOT l.mature) AS censored,
       count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND l.churned) AS churned,
       count(*) FILTER (WHERE l.churned IS NULL AND l.mature) AS mature_without_outcome,
       count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND NOT l.mature AND l.churned IS NOT NULL) AS censored_but_labelled,
       round(count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND NOT l.mature)::numeric / NULLIF(count(fr.feature_row_id), 0), 6) AS censored_share,
       count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND NOT l.mature AND EXISTS (
           SELECT 1 FROM subscription_events s WHERE s.account_id = pc.account_id AND s.event_type = 'cancel' AND s.event_at >= pc.prediction_at
              AND s.event_at < pc.horizon_end)) AS cancellations_seen_so_far_in_censored_rows,
       round(count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND NOT l.mature AND EXISTS (
           SELECT 1 FROM subscription_events s WHERE s.account_id = pc.account_id AND s.event_type = 'cancel' AND s.event_at >= pc.prediction_at
              AND s.event_at < pc.horizon_end))::numeric / NULLIF(count(*) FILTER (WHERE fr.feature_row_id IS NOT NULL AND NOT l.mature), 0), 6) AS rate_if_censored_were_non_churn
FROM prediction_cutoffs pc LEFT JOIN feature_rows fr USING (cutoff_id) LEFT JOIN labels l USING (cutoff_id)
GROUP BY pc.prediction_at ORDER BY pc.prediction_at;
-- @@ cohort_maturity_rule
-- the maturity rule recomputed from the cutoff windows (label_end <= as_of) against the stored flag, for every labelled cohort row
SELECT count(*) AS labelled_rows, count(*) FILTER (WHERE l.mature = (pc.horizon_end + interval '14 days' <= d.as_of)) AS stored_flag_equals_rule,
       count(*) FILTER (WHERE l.label_end = pc.horizon_end + interval '14 days') AS stored_label_end_equals_rule
FROM labels l JOIN prediction_cutoffs pc USING (cutoff_id), (SELECT as_of FROM dataset_versions ORDER BY as_of DESC LIMIT 1) d;
-- @@ rejected_false_labels
-- INJ-07: labels of false for rows whose window is still open are refused (CENSORED_LABEL) and kept raw; the row keeps its censored (null) label
SELECT reason_code, count(*) AS rejected_labels, count(*) FILTER (WHERE (raw_row ->> 'churned') = 'false' AND (raw_row ->> 'mature') = 'false') AS false_and_immature
FROM rejected_records WHERE entity = 'labels' GROUP BY reason_code ORDER BY reason_code COLLATE "C";
