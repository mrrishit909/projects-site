-- 09_golden_known_answer.sql: the independent known-answer fixture (P04-GOLD-01) read through this directory's views.
-- Run on the GOLDEN database only (tests/fixtures/golden/inputs.json: one agent, three tickets created at 09:00:00Z, deterministic
-- 10-minute service, FIFO). The hand calculation is tests/fixtures/golden/CALCULATION.md: service starts 0, 10, 20; waits 0, 10, 20;
-- mean wait 10; first responses 0, 10, 20; resolutions 10, 20, 30; handling 10 each (30 in all); final completion at minute 30.
-- @@ golden_per_ticket
SELECT t.ticket_id,
       round(extract(epoch FROM (t.first_human - t.created_at)) / 60, 4) AS first_response_min,
       round(extract(epoch FROM (t.first_start - t.created_at)) / 60, 4) AS wait_min,
       round(extract(epoch FROM (t.final_resolved - t.created_at)) / 60, 4) AS resolution_min,
       round(coalesce((SELECT sum(extract(epoch FROM (i.ended_at - i.started_at))) FROM sf_interval i WHERE i.ticket_id = t.ticket_id), 0) / 60, 4) AS handling_min
  FROM sf_ticket t ORDER BY t.ticket_id;
-- @@ golden_totals
-- The totals the hand calculation names: mean wait, total handling, the last completion in minutes after the first arrival, and the
-- simulated run sim-001 of the same case (seeded by data/seed.py): its service starts and resolutions are the same arithmetic.
SELECT 'event log (this directory)' AS source,
       round(avg(extract(epoch FROM (first_start - created_at)) / 60), 4) AS mean_wait_min,
       round((SELECT sum(extract(epoch FROM (ended_at - started_at))) FROM sf_interval) / 60, 4) AS handling_min_total,
       round(extract(epoch FROM (max(final_resolved) - min(created_at))) / 60, 4) AS last_completion_min
  FROM sf_ticket
UNION ALL
SELECT 'simulation sim-001 (simulation_events)',
       round(avg(s.event_at), 4),
       NULL,
       (SELECT max(event_at) FROM simulation_events WHERE simulation_id = 'sim-001' AND event_type = 'resolved')
  FROM simulation_events s WHERE s.simulation_id = 'sim-001' AND s.event_type = 'service_started';
