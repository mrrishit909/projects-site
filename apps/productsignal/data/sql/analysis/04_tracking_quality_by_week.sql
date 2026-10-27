-- 04_tracking_quality_by_week.sql: tracking quality by week, delay and identity attribution (P06-ART-04, P06-UI-04, D-01, D-05, P06-TEST-05, P06-TEST-07).
-- Question: how much of the event log reaches a figure, how does that move by week, and how late is late?
-- Needs 00_canonical_events.sql (ps_ev at the as-of 2026-10-05T00:00:00Z). Weeks are the UTC Monday of `event_at` (the business instant). A row is DELAYED when
-- received_at - event_at > 24 hours (strictly), counted among the canonical rows only; DUPLICATE rows are re-sent events dropped (earliest received wins);
-- UNKNOWN rows have no user and no link (or a user that does not exist); BOT and INTERNAL rows belong to excluded users. ANONYMOUS rows are analysed events with
-- no user id: ATTRIBUTED when a link exists with linked_at <= event_at (forward only), the rest stay anonymous.

-- @@ by_week
SELECT coalesce(to_char(date_trunc('week', r.at AT TIME ZONE 'UTC'), 'YYYY-MM-DD'), 'ALL') AS week_start,
       count(*) AS rows_total, count(*) FILTER (WHERE r.cls = 'duplicate') AS duplicates_dropped, count(*) FILTER (WHERE r.rn = 1) AS canonical,
       count(*) FILTER (WHERE r.rn = 1 AND r.received_at - r.at > interval '24 hours') AS delayed_over_24h,
       count(*) FILTER (WHERE r.cls = 'unknown') AS unknown_identity, count(*) FILTER (WHERE r.cls = 'bot') AS bot_excluded,
       count(*) FILTER (WHERE r.cls = 'internal') AS internal_excluded, count(*) FILTER (WHERE r.cls = 'analysed') AS analysed,
       count(*) FILTER (WHERE r.cls = 'analysed' AND r.user_id IS NULL) AS anonymous_events,
       count(*) FILTER (WHERE r.cls = 'analysed' AND r.user_id IS NULL AND r.u IS NOT NULL) AS attributed_by_link,
       round(count(*) FILTER (WHERE r.rn = 1 AND r.received_at - r.at > interval '24 hours')::numeric / count(*) FILTER (WHERE r.rn = 1), 6) AS delayed_share
FROM ps_ev r WHERE r.c = '2026-10-05T00:00:00Z' GROUP BY ROLLUP (date_trunc('week', r.at AT TIME ZONE 'UTC')) ORDER BY date_trunc('week', r.at AT TIME ZONE 'UTC') NULLS LAST;

-- @@ delay_distribution
-- How late the delayed canonical rows are: 24 h to 48 h, 2 to 7 days, over 7 days, and the longest delay in hours (2 places). Late rows are in the log from the
-- moment they arrive: a run at an earlier cutoff does not have them (that is 03's late_batch_effect and 08's late_events_by_cutoff).
WITH d AS (
    SELECT r.name, extract(epoch FROM r.received_at - r.at) / 3600 AS hours FROM ps_ev r
    WHERE r.c = '2026-10-05T00:00:00Z' AND r.rn = 1 AND r.received_at - r.at > interval '24 hours'
)
SELECT coalesce(name, 'ALL') AS event_name, count(*) AS delayed_rows,
       count(*) FILTER (WHERE hours <= 48) AS hours_24_to_48, count(*) FILTER (WHERE hours > 48 AND hours <= 168) AS days_2_to_7, count(*) FILTER (WHERE hours > 168) AS over_7_days,
       round(max(hours)::numeric, 2) AS longest_delay_hours
FROM d GROUP BY ROLLUP (name) ORDER BY name COLLATE "C" NULLS LAST;

-- @@ identity_links
-- Identity attribution at the as-of: links in the table, real users (non-bot users of any account), the real users reached by a link and the share (the site's
-- "linked share"), and the anonymous analysed events by what happened to them. A link attributes forward only (P06-TEST-07): the earliest link of an anonymous id
-- fixes its user, and an event before linked_at stays anonymous.
WITH real AS (SELECT u.user_id FROM users u WHERE NOT u.bot_flag),
linked AS (SELECT DISTINCT user_id FROM identity_links WHERE user_id IN (SELECT user_id FROM real))
SELECT (SELECT count(*) FROM identity_links) AS links, (SELECT count(*) FROM real) AS real_users, (SELECT count(*) FROM linked) AS real_users_linked,
       round((SELECT count(*) FROM linked)::numeric / (SELECT count(*) FROM real), 6) AS linked_share,
       (SELECT count(*) FROM ps_ev WHERE c = '2026-10-05T00:00:00Z' AND cls = 'analysed' AND user_id IS NULL) AS anonymous_events,
       (SELECT count(*) FROM ps_ev WHERE c = '2026-10-05T00:00:00Z' AND cls = 'analysed' AND user_id IS NULL AND u IS NOT NULL) AS attributed_by_link,
       (SELECT count(*) FROM ps_ev WHERE c = '2026-10-05T00:00:00Z' AND cls = 'analysed' AND user_id IS NULL AND u IS NULL) AS remain_anonymous;
