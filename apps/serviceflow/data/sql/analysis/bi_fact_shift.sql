-- bi_fact_shift.sql: fact_shift of the BI package. Grain: one shift of one agent (1,020 rows). Durations in minutes. The declared break
-- is shifts.break_minutes; the recorded break is the sum of its shift_breaks intervals. staffed_available_minutes follows D-05 for a
-- shift the selected dates cover whole: shift minutes minus the DECLARED break. crosses_clock_change = 1 when the UTC offset of the
-- agent's zone differs at the start and the end of the shift (the real length then differs from the wall-clock length).
SELECT s.shift_id, s.agent_id,
       to_char(s.starts_at AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS start_date_key,
       to_char(s.starts_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS starts_at,
       to_char(s.ends_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS ends_at,
       (extract(epoch FROM (s.ends_at - s.starts_at)) / 60)::int AS shift_minutes,
       s.break_minutes AS declared_break_minutes,
       coalesce((SELECT sum(extract(epoch FROM (b.ends_at - b.starts_at)) / 60) FROM shift_breaks b WHERE b.shift_id = s.shift_id), 0)::int AS recorded_break_minutes,
       ((extract(epoch FROM (s.ends_at - s.starts_at)) / 60)::int - s.break_minutes) AS staffed_available_minutes,
       ((s.ends_at AT TIME ZONE a.timezone) - (s.starts_at AT TIME ZONE a.timezone) <> s.ends_at - s.starts_at)::int AS crosses_clock_change
  FROM shifts s JOIN agents a ON a.agent_id = s.agent_id
 ORDER BY s.shift_id;
