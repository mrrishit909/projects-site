-- P09-ART-04 investigation 05: the recurring-cost expansion over half-open ranges and the one-time costs in exactly one period (D-01, D-05 D-P9-16, INJ-11, P09-TEST-11).
-- Question: is every cost in the cash flow counted in the right periods, once? A recurring cost carries a half-open range [start_period, end_period) and no period_index; it becomes one row per period
-- of the range (the command that builds the cash flows does it, never a display loop), so a range [7, 14) has 7 rows and period 14 is not one of them. A one-time cost has exactly one period_index. Two
-- adjacent ranges ([1, 7) then [7, 14)) share the boundary period 7 only once, in the later range. A one-time cost key appearing in a second period is rejected ONE_TIME_COST_REPEATED. Scope: the 900
-- cost items as loaded, and the planned costs of scn-025 inside its 36 periods.

-- @@ by_type
SELECT c.cost_type, c.cost_basis, count(*) AS items,
       sum(CASE WHEN c.cost_type = 'one_time' THEN 1 ELSE c.end_period - c.start_period END) AS expanded_rows,
       round(sum(c.amount * CASE WHEN c.cost_type = 'one_time' THEN 1 ELSE c.end_period - c.start_period END), 2) AS expanded_total,
       round(sum(c.amount), 2) AS item_amount_total
FROM cost_items c
GROUP BY c.cost_type, c.cost_basis
ORDER BY c.cost_type COLLATE "C", c.cost_basis COLLATE "C"

-- @@ recurring_by_initiative
SELECT c.initiative_id, count(*) AS recurring_items, sum(c.end_period - c.start_period) AS expanded_rows, min(c.start_period) AS first_period, max(c.end_period - 1) AS last_period,
       max(c.end_period) AS first_period_after_the_last_range, round(sum(c.amount * (c.end_period - c.start_period)), 2) AS expanded_total
FROM cost_items c WHERE c.cost_type = 'recurring'
GROUP BY c.initiative_id
ORDER BY c.initiative_id COLLATE "C"

-- @@ half_open_boundaries
-- For every pair of adjacent recurring ranges of one cost line (key stem s1, s2, ...), the boundary period is the end of the first and the start of the second: it carries the later range only.
SELECT count(*) AS adjacent_range_pairs,
       count(*) FILTER (WHERE (SELECT count(*) FROM cost_items x CROSS JOIN LATERAL generate_series(x.start_period, x.end_period - 1) AS g(t)
                               WHERE x.initiative_id = a.initiative_id AND x.cost_type = 'recurring' AND x.cost_basis = a.cost_basis
                                 AND regexp_replace(x.cost_key, '-s[0-9]+$', '') = regexp_replace(a.cost_key, '-s[0-9]+$', '') AND g.t = a.end_period) = 1) AS boundary_periods_with_exactly_one_row,
       count(*) FILTER (WHERE (SELECT count(*) FROM cost_items x CROSS JOIN LATERAL generate_series(x.start_period, x.end_period - 1) AS g(t)
                               WHERE x.cost_id = a.cost_id AND g.t = a.end_period) = 0) AS ranges_that_do_not_contain_their_own_end
FROM cost_items a JOIN cost_items b ON b.initiative_id = a.initiative_id AND b.cost_type = 'recurring' AND b.cost_basis = a.cost_basis AND b.start_period = a.end_period
  AND regexp_replace(b.cost_key, '-s[0-9]+$', '') = regexp_replace(a.cost_key, '-s[0-9]+$', '') AND b.cost_id <> a.cost_id
WHERE a.cost_type = 'recurring'

-- @@ one_time_rule
SELECT count(*) AS one_time_items, count(*) FILTER (WHERE c.period_index IS NOT NULL AND c.start_period IS NULL AND c.end_period IS NULL) AS with_exactly_one_period,
       count(*) FILTER (WHERE c.period_index IS NULL) AS with_no_period,
       (SELECT count(*) FROM (SELECT x.initiative_id, x.cost_key, x.cost_basis FROM cost_items x WHERE x.cost_type = 'one_time'
                              GROUP BY x.initiative_id, x.cost_key, x.cost_basis HAVING count(*) > 1) d) AS cost_keys_in_more_than_one_period,
       (SELECT count(*) FROM (SELECT x.initiative_id, x.cost_key, x.cost_basis FROM cost_items x GROUP BY x.initiative_id, x.cost_key, x.cost_basis HAVING count(DISTINCT x.cost_type) > 1) d) AS cost_keys_of_two_kinds
FROM cost_items c WHERE c.cost_type = 'one_time'

-- @@ inj11_key
-- INJ-11: the one-time cost ck-001-licence-setup-1 is entered again 4 periods later (c-inj-11, period 5). The world holds it once; the repeat is only a replay event and is refused.
SELECT c.cost_id, c.initiative_id, c.cost_key, c.cost_type, c.amount::numeric(20,2) AS amount, c.period_index,
       (SELECT count(*) FROM cost_items x WHERE x.initiative_id = c.initiative_id AND x.cost_key = c.cost_key AND x.cost_basis = c.cost_basis) AS rows_with_this_key,
       (SELECT count(*) FROM cost_items x WHERE x.initiative_id = c.initiative_id AND x.cost_key = c.cost_key AND x.cost_basis = c.cost_basis AND x.period_index = 5) AS rows_in_period_5
FROM cost_items c WHERE c.cost_id = 'c-0042'

-- @@ scn025_by_initiative
SELECT i.initiative_id,
       round(coalesce(sum(c.amount) FILTER (WHERE c.cost_type = 'one_time'), 0), 2) AS one_time_total, round(coalesce(sum(c.amount) FILTER (WHERE c.cost_type = 'recurring'), 0), 2) AS recurring_total,
       round(coalesce(sum(c.amount), 0), 2) AS planned_costs, count(c.cost_id) AS expanded_planned_rows
FROM initiatives i LEFT JOIN cw_cost c ON c.scenario_id = 'scn-025' AND c.initiative_id = i.initiative_id AND c.cost_basis = 'planned'
GROUP BY i.initiative_id
ORDER BY i.initiative_id COLLATE "C"
