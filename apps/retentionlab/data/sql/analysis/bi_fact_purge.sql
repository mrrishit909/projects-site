-- P10-ART-06 fact: rows kept and dropped by the chronological split (grain: population x range). cohort_200 is read from the loaded split assignments; world_2400 is the published split summary.
SELECT * FROM (SELECT 'cohort_200' AS population_key, sa.split AS split_range, count(*) AS cutoff_rows, count(*) FILTER (WHERE sa.status = 'retained') AS retained,
       count(*) FILTER (WHERE sa.drop_reason = 'LABEL_WINDOW') AS label_window, count(*) FILTER (WHERE sa.drop_reason = 'GROUP_TEST') AS group_test,
       count(*) FILTER (WHERE sa.drop_reason = 'GROUP_VALIDATION') AS group_validation
FROM split_assignments sa GROUP BY sa.split
UNION ALL SELECT 'world_2400', split_range, total, retained, label_window, group_test, group_validation FROM art_split_population) x
ORDER BY population_key COLLATE "C", CASE split_range WHEN 'train' THEN 1 WHEN 'validation' THEN 2 WHEN 'test' THEN 3 ELSE 4 END;

