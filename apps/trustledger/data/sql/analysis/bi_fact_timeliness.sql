-- P07-ART-06 fact: one row per monitored dataset at the as-of read (15): the judged occurrence, its deadline, the latest refresh and the state (on_time, pending or late).
SELECT dataset_id, tz AS timezone, local_time AS scheduled_local, grace AS grace_minutes, tl_iso(occurrence) AS occurrence_utc, tl_iso(deadline) AS deadline_utc,
       coalesce(tl_iso(last_refresh), '') AS last_refreshed_at, state
FROM tl_tstate WHERE seq = 0 ORDER BY dataset_id COLLATE "C"
