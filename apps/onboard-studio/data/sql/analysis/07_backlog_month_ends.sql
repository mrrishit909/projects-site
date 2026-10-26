-- 07: open backlog as of month-ends, reconstructed from opened_at and completed_at (P02-MET-11; D-04, D-05).
-- A case is open at cutoff t when opened_at <= t and (completed_at IS NULL OR completed_at > t). The cutoff of a month is
-- the first instant of the next month (UTC), i.e. the end of its last day. opened/completed are counts inside the month
-- (half-open [month start, cutoff)), so open_at_end = previous open_at_end + opened - completed holds on every row.
-- The last cutoff, 2026-10-01T00:00Z, is just after the snapshot window; the 21 cases still open then have no completed_at.
WITH m AS (
    SELECT g AT TIME ZONE 'UTC' AS lo, (g + interval '1 month') AT TIME ZONE 'UTC' AS cutoff
      FROM generate_series(TIMESTAMP '2025-04-01', TIMESTAMP '2026-09-01', interval '1 month') g)
SELECT to_char(m.lo AT TIME ZONE 'UTC', 'YYYY-MM') AS month,
       to_char(m.cutoff AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI"Z"') AS cutoff,
       count(*) FILTER (WHERE c.opened_at >= m.lo AND c.opened_at < m.cutoff)::int      AS opened,
       count(*) FILTER (WHERE c.completed_at >= m.lo AND c.completed_at < m.cutoff)::int AS completed,
       count(*) FILTER (WHERE c.opened_at <= m.cutoff AND (c.completed_at IS NULL OR c.completed_at > m.cutoff))::int AS open_at_end,
       count(*) FILTER (WHERE c.opened_at <= m.cutoff AND (c.completed_at IS NULL OR c.completed_at > m.cutoff)
                          AND c.workflow_version_id = 'wfv-001')::int AS open_v1,
       count(*) FILTER (WHERE c.opened_at <= m.cutoff AND (c.completed_at IS NULL OR c.completed_at > m.cutoff)
                          AND c.workflow_version_id = 'wfv-002')::int AS open_v2
  FROM m CROSS JOIN cases c
 GROUP BY m.lo, m.cutoff
 ORDER BY m.lo;
