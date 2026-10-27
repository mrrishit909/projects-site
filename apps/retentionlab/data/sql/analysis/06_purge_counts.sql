-- P10-ART-04 investigation 06: how many rows the chronological split drops, and why (D-02 purge, D-07 purge counts, P10-FLOW-03, P10-TEST-03/04).
-- Question: of the cutoff rows that fall into the train and validation ranges, how many are dropped because their label window [prediction_at, label_end) crosses the next
-- boundary (LABEL_WINDOW, embargo = horizon 90 + grace 14 = 104 days), and how many because the same account has a row on the other side (GROUP_TEST, GROUP_VALIDATION)?
-- Rules (D-P10-09): label purge first, then group purge counting membership by RANGE; test rows are never purged; rows at or after test_end are 'outside' and kept.
-- Populations: the 200-account cohort (stored split_assignments, and the same assignment recomputed here from prediction_cutoffs and the run's three boundaries) and the
-- whole 2,400-account world as the domain published it (art_split_population; split counts need every account, so they are not recomputable from the cohort).
-- @@ cohort_stored
SELECT sa.split AS split_range, count(*) AS cutoff_rows, count(*) FILTER (WHERE sa.status = 'retained') AS retained,
       count(*) FILTER (WHERE sa.drop_reason = 'LABEL_WINDOW') AS label_window, count(*) FILTER (WHERE sa.drop_reason = 'GROUP_TEST') AS group_test,
       count(*) FILTER (WHERE sa.drop_reason = 'GROUP_VALIDATION') AS group_validation
FROM split_assignments sa GROUP BY sa.split ORDER BY CASE sa.split WHEN 'train' THEN 1 WHEN 'validation' THEN 2 WHEN 'test' THEN 3 ELSE 4 END;
-- @@ cohort_recomputed
WITH run AS (SELECT train_end, validation_end, test_end FROM training_runs ORDER BY training_run_id COLLATE "C" LIMIT 1),
c AS (
    SELECT pc.cutoff_id, pc.account_id, pc.prediction_at, pc.horizon_end + interval '14 days' AS label_end,
           CASE WHEN pc.prediction_at < r.train_end THEN 'train' WHEN pc.prediction_at < r.validation_end THEN 'validation' WHEN pc.prediction_at < r.test_end THEN 'test' ELSE 'outside' END AS rng,
           r.train_end, r.validation_end
    FROM prediction_cutoffs pc, run r
),
a AS (
    SELECT c.*, (c.rng = 'train' AND c.label_end > c.train_end) OR (c.rng = 'validation' AND c.label_end > c.validation_end) AS label_dropped,
           EXISTS (SELECT 1 FROM c t WHERE t.account_id = c.account_id AND t.rng = 'test') AS has_test, EXISTS (SELECT 1 FROM c v WHERE v.account_id = c.account_id AND v.rng = 'validation') AS has_validation
    FROM c
),
d AS (
    SELECT a.*, CASE WHEN label_dropped THEN 'LABEL_WINDOW'
                     WHEN rng IN ('train', 'validation') AND has_test THEN 'GROUP_TEST'
                     WHEN rng = 'train' AND has_validation THEN 'GROUP_VALIDATION' END AS reason
    FROM a
)
SELECT d.rng AS split_range, count(*) AS cutoff_rows, count(*) FILTER (WHERE reason IS NULL) AS retained, count(*) FILTER (WHERE reason = 'LABEL_WINDOW') AS label_window,
       count(*) FILTER (WHERE reason = 'GROUP_TEST') AS group_test, count(*) FILTER (WHERE reason = 'GROUP_VALIDATION') AS group_validation,
       count(*) FILTER (WHERE (reason IS NULL) <> (sa.status = 'retained') OR reason IS DISTINCT FROM sa.drop_reason) AS rows_that_differ_from_the_stored_assignment
FROM d JOIN split_assignments sa USING (cutoff_id)
GROUP BY d.rng ORDER BY CASE d.rng WHEN 'train' THEN 1 WHEN 'validation' THEN 2 WHEN 'test' THEN 3 ELSE 4 END;
-- @@ cohort_no_account_on_both_sides
-- P10-TEST-03: after the group purge no account keeps retained rows in two different ranges of train / validation / test
SELECT count(*) AS accounts_retained_in_two_ranges FROM (
    SELECT pc.account_id FROM split_assignments sa JOIN prediction_cutoffs pc USING (cutoff_id)
    WHERE sa.status = 'retained' AND sa.split IN ('train', 'validation', 'test') GROUP BY pc.account_id HAVING count(DISTINCT sa.split) > 1) x;
-- @@ cohort_label_windows_inside_the_range
-- P10-TEST-04: no retained train or validation row has a label window that ends after its range's boundary
SELECT sa.split AS split_range, count(*) AS retained_rows,
       count(*) FILTER (WHERE pc.horizon_end + interval '14 days' > CASE sa.split WHEN 'train' THEN r.train_end ELSE r.validation_end END) AS retained_rows_crossing_the_boundary
FROM split_assignments sa JOIN prediction_cutoffs pc USING (cutoff_id), (SELECT train_end, validation_end FROM training_runs ORDER BY training_run_id COLLATE "C" LIMIT 1) r
WHERE sa.status = 'retained' AND sa.split IN ('train', 'validation') GROUP BY sa.split ORDER BY CASE sa.split WHEN 'train' THEN 1 ELSE 2 END;
-- @@ world_published
SELECT split_range, total AS cutoff_rows, retained, label_window, group_test, group_validation, (total - retained) AS dropped,
       (retained + label_window + group_test + group_validation = total) AS counts_add_up
FROM art_split_population ORDER BY CASE split_range WHEN 'train' THEN 1 WHEN 'validation' THEN 2 WHEN 'test' THEN 3 ELSE 4 END;
-- @@ world_totals
SELECT sum(label_window) FILTER (WHERE split_range = 'train') AS train_label_window, sum(group_test) FILTER (WHERE split_range = 'train') AS train_group_test,
       sum(group_validation) FILTER (WHERE split_range = 'train') AS train_group_validation,
       sum(label_window) FILTER (WHERE split_range = 'validation') AS validation_label_window, sum(group_test) FILTER (WHERE split_range = 'validation') AS validation_group_test,
       sum(group_test + group_validation) FILTER (WHERE split_range = 'train') AS train_dropped_because_the_account_sits_on_the_other_side,
       sum(label_window + group_test + group_validation) AS dropped_in_all_ranges, 104 AS embargo_days
FROM art_split_population;
