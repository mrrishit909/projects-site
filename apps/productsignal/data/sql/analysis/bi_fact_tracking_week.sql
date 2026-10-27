-- bi_fact_tracking_week.sql: the tracking-quality fact of the BI package (docs/bi-package.md): one row per UTC week of event_at at the as-of 2026-10-05T00:00:00Z (26 rows).
-- Needs 00_canonical_events.sql. Grain: ONE ROW PER WEEK. Same classes as 04_tracking_quality_by_week.sql (the by_week block without its ALL row): rows_total, duplicates_dropped,
-- canonical, delayed_over_24h (canonical rows received more than 24 h after event_at), unknown_identity, bot_excluded, internal_excluded, analysed.
-- @@ fact_tracking_week
SELECT to_char(date_trunc('week', r.at AT TIME ZONE 'UTC'), 'YYYY-MM-DD') AS week_start,
       count(*) AS rows_total, count(*) FILTER (WHERE r.cls = 'duplicate') AS duplicates_dropped, count(*) FILTER (WHERE r.rn = 1) AS canonical,
       count(*) FILTER (WHERE r.rn = 1 AND r.received_at - r.at > interval '24 hours') AS delayed_over_24h,
       count(*) FILTER (WHERE r.cls = 'unknown') AS unknown_identity, count(*) FILTER (WHERE r.cls = 'bot') AS bot_excluded, count(*) FILTER (WHERE r.cls = 'internal') AS internal_excluded,
       count(*) FILTER (WHERE r.cls = 'analysed') AS analysed
FROM ps_ev r WHERE r.c = '2026-10-05T00:00:00Z' GROUP BY date_trunc('week', r.at AT TIME ZONE 'UTC') ORDER BY date_trunc('week', r.at AT TIME ZONE 'UTC');
