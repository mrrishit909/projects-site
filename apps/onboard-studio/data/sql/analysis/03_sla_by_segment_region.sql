-- 03: SLA attainment by segment and region, open cases beside the rate and never inside it (P02-MET-05, D-04).
-- Attainment = completed cases with active elapsed <= SLA minutes / completed cases (480 business minutes here).
-- GROUPING SETS gives each (segment, region) cell, the segment and region margins and the overall row.
-- pct_v2 is the share of the cell's completed cases that ran on workflow v2: attainment differs by version (query 02),
-- so a cell with more v2 cases reads better for that reason alone.
SELECT COALESCE(segment, 'ALL') AS segment, COALESCE(region, 'ALL') AS region,
       count(*) FILTER (WHERE completed_at IS NOT NULL)::int                         AS completed_cases,
       count(*) FILTER (WHERE within_sla)::int                                       AS within_sla,
       round(count(*) FILTER (WHERE within_sla)::numeric / NULLIF(count(within_sla), 0), 6) AS sla_attainment,
       count(*) FILTER (WHERE completed_at IS NULL)::int                             AS open_cases_not_in_rate,
       round(avg(active_s) / 3600, 4)                                                AS active_h,
       round(100.0 * count(*) FILTER (WHERE version_number = 2 AND completed_at IS NOT NULL)
             / NULLIF(count(*) FILTER (WHERE completed_at IS NOT NULL), 0), 1)       AS pct_v2
  FROM os_case_facts
 GROUP BY GROUPING SETS ((segment, region), (segment), (region), ())
 ORDER BY (segment IS NULL), segment, (region IS NULL), region;
