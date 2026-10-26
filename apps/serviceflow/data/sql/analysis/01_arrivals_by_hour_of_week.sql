-- 01_arrivals_by_hour_of_week.sql: arrivals against staffed hours by two-hour block of the UTC week; the Monday 09-11 bind.
-- Decision link: where the weekly capacity is thin against the demand (P04-DOMAIN-02/03; the designed relationship in
-- web/public/data/manifest.json is a Monday 09-11 UTC block).
-- Grain: one row per block of two consecutive clock hours of the UTC week (168 blocks, a block starts at (weekday, hour)).
-- Arrivals: accepted tickets by created_at (UTC), all twelve weeks, with the training (weeks 1-8) and holdout (weeks 9-12) parts.
-- Staffed hours: each shift's overlap with each clock hour, scaled by (shift minutes - break_minutes) / shift minutes, so the
-- declared break is spread over the shift (pro rata; D-05's whole-window rule would deduct nothing from an hour).
-- Blocks with fewer than 24 staffed hours over the twelve weeks are excluded from the ranking (about two staffed agent-hours a week).
-- Output: the six highest blocks by arrivals per staffed hour, the median of all ranked blocks (the mean of the two middle ratios,
-- since the number of blocks is even; a statistic, not one block) and the lowest block.
WITH hours AS (
    SELECT (d * 24 + h) AS slot, d, h FROM generate_series(0, 6) d, generate_series(0, 23) h
),
arr AS (
    SELECT (extract(isodow FROM created_at AT TIME ZONE 'UTC')::int - 1) * 24 + extract(hour FROM created_at AT TIME ZONE 'UTC')::int AS slot,
           count(*) AS n,
           count(*) FILTER (WHERE created_at < '2026-08-31T00:00:00Z') AS n_train,
           count(*) FILTER (WHERE created_at >= '2026-08-31T00:00:00Z') AS n_hold
      FROM tickets GROUP BY 1
),
pieces AS (
    SELECT s.shift_id, gs AS slot_start, s.starts_at, s.ends_at, s.break_minutes,
           extract(epoch FROM (s.ends_at - s.starts_at)) AS secs
      FROM shifts s
      CROSS JOIN LATERAL generate_series(date_trunc('hour', s.starts_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC',
                                         s.ends_at - interval '1 second', interval '1 hour') AS gs
),
cap AS (
    SELECT (extract(isodow FROM slot_start AT TIME ZONE 'UTC')::int - 1) * 24 + extract(hour FROM slot_start AT TIME ZONE 'UTC')::int AS slot,
           sum(extract(epoch FROM (least(slot_start + interval '1 hour', ends_at) - greatest(slot_start, starts_at))) / 3600
               * (secs - 60 * break_minutes) / secs) AS staffed_hours
      FROM pieces GROUP BY 1
),
blocks AS (
    SELECT a.slot, a.d, a.h,
           (SELECT coalesce(sum(n), 0) FROM arr WHERE slot IN (a.slot, (a.slot + 1) % 168)) AS arrivals,
           (SELECT coalesce(sum(n_train), 0) FROM arr WHERE slot IN (a.slot, (a.slot + 1) % 168)) AS arrivals_training,
           (SELECT coalesce(sum(n_hold), 0) FROM arr WHERE slot IN (a.slot, (a.slot + 1) % 168)) AS arrivals_holdout,
           (SELECT coalesce(sum(staffed_hours), 0) FROM cap WHERE slot IN (a.slot, (a.slot + 1) % 168)) AS staffed_hours
      FROM hours a
),
ranked AS (
    SELECT b.*, b.arrivals / b.staffed_hours AS ratio,
           row_number() OVER (ORDER BY b.arrivals / b.staffed_hours DESC, b.slot) AS rank_desc,
           row_number() OVER (ORDER BY b.arrivals / b.staffed_hours, b.slot) AS rank_asc,
           count(*) OVER () AS n_blocks
      FROM blocks b WHERE b.staffed_hours >= 24
),
named AS (
    SELECT r.*, (ARRAY['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])[d + 1] || ' ' || lpad(h::text, 2, '0') || '-' || lpad(((h + 2) % 24)::text, 2, '0') AS block_utc
      FROM ranked r
)
SELECT note, block_utc, arrivals, arrivals_training, arrivals_holdout, staffed_hours, arrivals_per_staffed_hour, blocks_ranked FROM (
    SELECT rank_desc AS sort_key, 'top ' || rank_desc AS note, block_utc, arrivals::int AS arrivals, arrivals_training::int AS arrivals_training,
           arrivals_holdout::int AS arrivals_holdout, round(staffed_hours::numeric, 2) AS staffed_hours,
           round((arrivals / staffed_hours)::numeric, 4) AS arrivals_per_staffed_hour, n_blocks::int AS blocks_ranked
      FROM named WHERE rank_desc <= 6
    UNION ALL
    SELECT 100, 'median of the blocks', '(mean of the two middle blocks)', NULL, NULL, NULL, NULL,
           round((percentile_cont(0.5) WITHIN GROUP (ORDER BY ratio))::numeric, 4), max(n_blocks)::int
      FROM named
    UNION ALL
    SELECT 101, 'lowest block', block_utc, arrivals::int, arrivals_training::int, arrivals_holdout::int, round(staffed_hours::numeric, 2),
           round((arrivals / staffed_hours)::numeric, 4), n_blocks::int
      FROM named WHERE rank_asc = 1
) u ORDER BY sort_key;
