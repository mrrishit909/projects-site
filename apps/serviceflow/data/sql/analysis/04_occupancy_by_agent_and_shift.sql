-- 04_occupancy_by_agent_and_shift.sql: agent occupancy against staffed time, with the breaks shown, by agent and by shift pattern.
-- Decision link: how much of the staffed time the agents actually spend handling tickets, and how much capacity a break counted as
-- available would invent (P04-MET-09, P04-TEST-05, P04-TEST-07). Occupancy and the waiting tail are different numbers (P04-DOMAIN-04).
-- Window: the whole twelve weeks [2026-07-06, 2026-09-28). Staffed available time follows D-05: the shift's overlap with the window,
-- minus the shift's DECLARED break_minutes only when the window covers the whole shift. Handling = service intervals clipped to the
-- window, attributed to the agent named on the opening event; waiting_customer and idle time are not handling (D-02).
-- Recorded breaks are the shift_breaks intervals (a data-load-only table: data/seed.py has no loader, prepare_snapshot.py inserts them).
-- @@ occupancy_by_agent
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
sh AS (
    SELECT s.agent_id, count(*) FILTER (WHERE least(s.ends_at, w.w1) > greatest(s.starts_at, w.w0)) AS shifts,
           sum(extract(epoch FROM (least(s.ends_at, w.w1) - greatest(s.starts_at, w.w0))) / 60
               - CASE WHEN s.starts_at >= w.w0 AND s.ends_at <= w.w1 THEN s.break_minutes ELSE 0 END)
               FILTER (WHERE least(s.ends_at, w.w1) > greatest(s.starts_at, w.w0)) AS staffed_min,
           sum(s.break_minutes) FILTER (WHERE s.starts_at >= w.w0 AND s.ends_at <= w.w1) AS declared_break_min
      FROM shifts s, win w GROUP BY s.agent_id
),
rb AS (
    SELECT b.agent_id, sum(extract(epoch FROM (b.ends_at - b.starts_at)) / 60) AS recorded_break_min
      FROM shift_breaks b, win w WHERE b.starts_at >= w.w0 AND b.ends_at <= w.w1 GROUP BY b.agent_id
),
hd AS (
    SELECT i.agent_id, count(*) AS intervals,
           sum(greatest(0, extract(epoch FROM (least(coalesce(i.ended_at, w.w1), w.w1) - greatest(i.started_at, w.w0)))) / 60) AS handling_min
      FROM sf_interval i, win w GROUP BY i.agent_id
),
rows_ AS (
    SELECT a.agent_id, a.timezone, a.employment_type, sh.shifts, sh.staffed_min, sh.declared_break_min, rb.recorded_break_min,
           hd.intervals, hd.handling_min
      FROM agents a LEFT JOIN sh USING (agent_id) LEFT JOIN rb USING (agent_id) LEFT JOIN hd USING (agent_id)
)
SELECT agent_id, timezone, employment_type, shifts::int, round(staffed_min::numeric, 4) AS staffed_available_min,
       round(declared_break_min::numeric, 4) AS declared_break_min, round(recorded_break_min::numeric, 4) AS recorded_break_min,
       intervals::int AS service_intervals, round(handling_min::numeric, 4) AS handling_min,
       round(handling_min::numeric / nullif(staffed_min::numeric, 0), 6) AS occupancy
  FROM (SELECT * FROM rows_
        UNION ALL
        SELECT 'ALL', '', '', sum(shifts), sum(staffed_min), sum(declared_break_min), sum(recorded_break_min), sum(intervals), sum(handling_min) FROM rows_) u
 ORDER BY (agent_id = 'ALL'), agent_id;
-- @@ breaks_declared_vs_recorded
-- One row per shift pattern: gross length, the declared break and the recorded break. A shift whose declared break is 0 although a
-- 30-minute break is recorded counts the break as capacity (the injected defect INJ-05: three 480-minute shifts); the 420-minute row
-- is the Santiago night shift across the clock change (the real length; INJ-08 is the recorded 480-minute row of agt-018, which is
-- in the 480 / 30 row). Staffed (declared) = gross - declared break; staffed (recorded) = gross - recorded break. Handling is the
-- minutes of service intervals inside those shifts, and the minutes of them that fall inside a recorded break.
WITH sh AS (
    SELECT s.shift_id, s.agent_id, s.starts_at, s.ends_at, s.break_minutes AS declared,
           extract(epoch FROM (s.ends_at - s.starts_at)) / 60 AS gross,
           coalesce((SELECT sum(extract(epoch FROM (b.ends_at - b.starts_at)) / 60) FROM shift_breaks b WHERE b.shift_id = s.shift_id), 0) AS recorded
      FROM shifts s
),
hin AS (
    SELECT sh.shift_id,
           sum(extract(epoch FROM (least(coalesce(i.ended_at, 'infinity'), sh.ends_at) - greatest(i.started_at, sh.starts_at))) / 60) AS m
      FROM sh JOIN sf_interval i ON i.agent_id = sh.agent_id AND i.started_at < sh.ends_at AND coalesce(i.ended_at, 'infinity') > sh.starts_at
     GROUP BY sh.shift_id
),
hbr AS (
    SELECT b.shift_id,
           sum(extract(epoch FROM (least(coalesce(i.ended_at, 'infinity'), b.ends_at) - greatest(i.started_at, b.starts_at))) / 60) AS m
      FROM shift_breaks b JOIN sf_interval i ON i.agent_id = b.agent_id AND i.started_at < b.ends_at AND coalesce(i.ended_at, 'infinity') > b.starts_at
     GROUP BY b.shift_id
)
SELECT round(sh.gross::numeric, 0) AS shift_min, sh.declared AS declared_break_min, round(sh.recorded::numeric, 0) AS recorded_break_min,
       count(*)::int AS shifts,
       round(sum(sh.gross - sh.declared)::numeric, 4) AS staffed_min_declared,
       round(sum(sh.gross - sh.recorded)::numeric, 4) AS staffed_min_recorded,
       round(sum(sh.recorded - sh.declared)::numeric, 4) AS capacity_overstated_by_declared_min,
       round(coalesce(sum(hin.m), 0)::numeric, 4) AS handling_min,
       round(coalesce(sum(hbr.m), 0)::numeric, 4) AS handling_inside_a_recorded_break_min
  FROM sh LEFT JOIN hin USING (shift_id) LEFT JOIN hbr USING (shift_id)
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
-- @@ monday_bind_handling_by_queue
-- Where the technical-skilled agents' time goes in the Monday 09:00-11:00 UTC bind of the training weeks (weeks 1-8, Mondays 2026-07-06
-- .. 2026-08-24). The simulation of docs/executive-memo.md treats the technical queue's agents as DEDICATED servers; this block measures
-- how far that holds. An interval counts when it STARTS in the bind and its agent holds the skill of queue q-002 (technical) at that
-- instant (agent_skills.effective_from). The queue of an interval is the queue the ticket was in when it started: the latest created /
-- queued / transferred queue up to that instant.
WITH tech AS (SELECT skill_id FROM queue_skills WHERE queue_id = 'q-002'),
iv AS (
    SELECT i.agent_id, i.started_at, i.ended_at,
           (SELECT x.queue_id FROM sf_ev x
             WHERE x.ticket_id = i.ticket_id AND x.event_type IN ('created', 'queued', 'transferred') AND x.queue_id IS NOT NULL
               AND x.occurred_at <= i.started_at
             ORDER BY x.occurred_at DESC, x.event_id DESC LIMIT 1) AS queue_at_start
      FROM sf_interval i
     WHERE i.started_at >= '2026-07-06T00:00:00Z' AND i.started_at < '2026-08-31T00:00:00Z'
       AND extract(isodow FROM i.started_at AT TIME ZONE 'UTC') = 1 AND extract(hour FROM i.started_at AT TIME ZONE 'UTC') IN (9, 10)
       AND EXISTS (SELECT 1 FROM agent_skills s JOIN tech t ON t.skill_id = s.skill_id WHERE s.agent_id = i.agent_id AND s.effective_from <= i.started_at)
),
grp AS (SELECT queue_at_start AS queue_id, started_at, ended_at FROM iv UNION ALL SELECT 'ALL', started_at, ended_at FROM iv)
SELECT queue_id, count(*)::int AS intervals,
       round(sum(extract(epoch FROM (ended_at - started_at))) / 60, 4) AS handling_min,
       round(100 * sum(extract(epoch FROM (ended_at - started_at))) / (SELECT sum(extract(epoch FROM (ended_at - started_at))) FROM iv), 1) AS share_pct
  FROM grp GROUP BY queue_id ORDER BY (queue_id = 'ALL'), queue_id;
-- @@ occupancy_by_skill_set
-- The same occupancy grouped by the queues an agent can serve (the skill set at the END of the window: two agents gained a skill during the
-- twelve weeks, agt-005 on 2026-08-03 and agt-015 on 2026-08-17). Staffed and handling minutes are those of the first block, summed over the group.
-- Contribution to the decision: where the slack is, so a routing (cross-skilling) change can be set beside a staffing (adding capacity) change.
WITH win AS (SELECT w0, w1 FROM sf_window WHERE window_name = 'full'),
skills_of AS (
    SELECT a.agent_id, string_agg(qs.queue_id, ' + ' ORDER BY qs.queue_id) AS skill_set
      FROM agents a JOIN agent_skills s ON s.agent_id = a.agent_id JOIN queue_skills qs ON qs.skill_id = s.skill_id
     GROUP BY a.agent_id
),
sh AS (
    SELECT s.agent_id,
           sum(extract(epoch FROM (least(s.ends_at, w.w1) - greatest(s.starts_at, w.w0))) / 60
               - CASE WHEN s.starts_at >= w.w0 AND s.ends_at <= w.w1 THEN s.break_minutes ELSE 0 END)
               FILTER (WHERE least(s.ends_at, w.w1) > greatest(s.starts_at, w.w0)) AS staffed_min
      FROM shifts s, win w GROUP BY s.agent_id
),
hd AS (
    SELECT i.agent_id, sum(greatest(0, extract(epoch FROM (least(coalesce(i.ended_at, w.w1), w.w1) - greatest(i.started_at, w.w0)))) / 60) AS handling_min
      FROM sf_interval i, win w GROUP BY i.agent_id
)
SELECT k.skill_set, count(*)::int AS agents, string_agg(k.agent_id, ', ' ORDER BY k.agent_id) AS agent_ids,
       round(sum(sh.staffed_min)::numeric, 4) AS staffed_available_min, round(sum(hd.handling_min)::numeric, 4) AS handling_min,
       round(sum(hd.handling_min)::numeric / sum(sh.staffed_min)::numeric, 6) AS occupancy
  FROM skills_of k JOIN sh ON sh.agent_id = k.agent_id JOIN hd ON hd.agent_id = k.agent_id
 GROUP BY k.skill_set ORDER BY k.skill_set;
