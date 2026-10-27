-- P07-ART-04 investigation 08: timeliness states, on time / pending / late (D-01, D-06, D-10 R7-01).
-- Timeliness = monitored datasets refreshed within their target / monitored datasets EVALUATED. The target is the dataset's daily local time in its IANA zone plus a grace;
-- the window is half-open [occurrence, occurrence + grace), so a refresh AT the deadline is late. At a read taken while the latest occurrence's window is still open and
-- no refresh has arrived the dataset is `pending`: neither on time nor late, and outside the denominator. Observed at the snapshot's as-of; the other instants are the
-- same loaded refresh history read at a later instant (a sensitivity, not an observed read: nothing else is read at a probe).

-- @@ at_the_as_of
SELECT t.dataset_id, t.tz AS timezone, t.local_time AS scheduled_local, t.grace AS grace_minutes, tl_iso(t.occurrence) AS evaluated_occurrence_utc, tl_iso(t.deadline) AS deadline_utc,
       tl_iso(t.last_refresh) AS last_refreshed_at, t.state, o.team AS owner_team, o.active AS owner_active
FROM tl_tstate t JOIN datasets d ON d.dataset_id = t.dataset_id JOIN owners o ON o.owner_id = d.owner_id WHERE t.seq = 0 ORDER BY t.dataset_id COLLATE "C"

-- @@ summary
SELECT count(*) AS monitored_datasets, count(*) FILTER (WHERE state = 'on_time') AS on_time, count(*) FILTER (WHERE state = 'pending') AS pending,
       count(*) FILTER (WHERE state = 'late') AS late, count(*) FILTER (WHERE state <> 'pending') AS evaluated,
       round(count(*) FILTER (WHERE state = 'on_time')::numeric / nullif(count(*) FILTER (WHERE state <> 'pending'), 0), 6) AS timeliness
FROM tl_tstate WHERE seq = 0

-- @@ by_read_instant
-- The same refresh history judged at four instants. Pending appears only while a window is open; a read taken a day later finds every dataset late because the loaded
-- history ends at the as-of (so only the first row is an observed read).
SELECT seq AS read_no, label, tl_iso(at) AS read_at, count(*) AS monitored_datasets, count(*) FILTER (WHERE state = 'on_time') AS on_time, count(*) FILTER (WHERE state = 'pending') AS pending,
       count(*) FILTER (WHERE state = 'late') AS late, count(*) FILTER (WHERE state <> 'pending') AS evaluated,
       round(count(*) FILTER (WHERE state = 'on_time')::numeric / nullif(count(*) FILTER (WHERE state <> 'pending'), 0), 6) AS timeliness
FROM tl_tstate GROUP BY seq, label, at ORDER BY seq

-- @@ late_with_rules
-- The datasets that are late at the as-of, how late the refresh was against the deadline, and whether their timeliness rule is still active.
SELECT t.dataset_id, tl_iso(t.deadline) AS deadline_utc, tl_iso(t.last_refresh) AS last_refreshed_at,
       CASE WHEN t.last_refresh IS NULL THEN NULL ELSE round(extract(epoch FROM (t.last_refresh - t.deadline)) / 60) END AS minutes_after_deadline,
       coalesce((SELECT string_agg(r.rule_id || ' (' || r.status || ')', ', ' ORDER BY r.rule_id COLLATE "C") FROM quality_rules r WHERE r.dataset_id = t.dataset_id AND r.rule_type = 'timeliness'), 'none') AS timeliness_rule
FROM tl_tstate t WHERE t.seq = 0 AND t.state = 'late' ORDER BY t.dataset_id COLLATE "C"
