-- 05_exception_backlog_and_assignment_history.sql: the exception backlog at three cutoffs, its age and its owners (P05-ART-04, D-04, D-06, P05-MET-12).
-- Question: which invoices require exception review, how old is the queue, and does every review have an owner?
-- Needs 00_book.sql (ib_run: the exceptions the match raises at each cutoff, recomputed from facts) and the stored history
-- (`exceptions`: created_at and resolved_at; `exception_assignments`: append-only, one row per assignment). The stored history is written by
-- the nightly matching run at 02:00 UTC, the book is recomputed for any instant; the two can differ for an invoice imported between the last
-- run and the cutoff (shown in backlog_at_cutoffs, difference column). An exception is OPEN at a cutoff when it was created by then and not
-- yet resolved; it is OWNED when an assignment exists at or before the cutoff, and its owner is the latest assignment (by time, then id).
-- Cutoffs: 2026-03-31T23:59:59Z, 2026-06-30T23:59:59Z, 2026-10-01T02:00:00Z (the as-of).

-- @@ backlog_at_cutoffs
WITH cuts(c) AS (VALUES ('2026-03-31T23:59:59Z'::timestamptz), ('2026-06-30T23:59:59Z'), ('2026-10-01T02:00:00Z')),
h AS (
    SELECT cu.c, e.exception_id,
           EXISTS (SELECT 1 FROM exception_assignments a WHERE a.exception_id = e.exception_id AND a.assigned_at <= cu.c) AS owned
    FROM cuts cu JOIN exceptions e ON e.created_at <= cu.c AND (e.resolved_at IS NULL OR e.resolved_at > cu.c)
)
SELECT cu.c AS cutoff,
       (SELECT count(*) FROM h WHERE h.c = cu.c) AS open_from_history,
       (SELECT count(*) FROM ib_run r, unnest(r.reasons) t WHERE r.c = cu.c) AS open_from_facts,
       (SELECT count(*) FROM ib_run r, unnest(r.reasons) t WHERE r.c = cu.c) - (SELECT count(*) FROM h WHERE h.c = cu.c) AS difference,
       (SELECT count(*) FROM h WHERE h.c = cu.c AND h.owned) AS owned_from_history,
       (SELECT count(*) FROM h WHERE h.c = cu.c AND NOT h.owned) AS unowned_from_history
FROM cuts cu ORDER BY cu.c;

-- @@ open_by_reason_and_age
-- The open exceptions at the as-of by reason and age (days since created_at, whole days).
WITH o AS (
    SELECT e.exception_type, floor(extract(epoch FROM ('2026-10-01T02:00:00Z'::timestamptz - e.created_at)) / 86400)::int AS age_days
    FROM exceptions e WHERE e.created_at <= '2026-10-01T02:00:00Z' AND (e.resolved_at IS NULL OR e.resolved_at > '2026-10-01T02:00:00Z')
)
SELECT exception_type AS reason, count(*) AS open_exceptions,
       count(*) FILTER (WHERE age_days < 7) AS age_0_to_6_days, count(*) FILTER (WHERE age_days BETWEEN 7 AND 13) AS age_7_to_13_days,
       count(*) FILTER (WHERE age_days BETWEEN 14 AND 29) AS age_14_to_29_days, count(*) FILTER (WHERE age_days >= 30) AS age_30_days_or_more,
       max(age_days) AS oldest_days
FROM o GROUP BY exception_type ORDER BY exception_type COLLATE "C";

-- @@ assignments_per_exception
-- Assignment history (append-only): how many owners each exception has had, by whether it is still open at the as-of.
WITH n AS (
    SELECT e.exception_id, (e.created_at <= '2026-10-01T02:00:00Z' AND (e.resolved_at IS NULL OR e.resolved_at > '2026-10-01T02:00:00Z')) AS is_open,
           (SELECT count(*) FROM exception_assignments a WHERE a.exception_id = e.exception_id) AS assignments
    FROM exceptions e
)
SELECT assignments, count(*) AS exceptions, count(*) FILTER (WHERE is_open) AS open_at_cutoff, count(*) FILTER (WHERE NOT is_open) AS resolved
FROM n GROUP BY assignments ORDER BY assignments;

-- @@ first_assignment_and_resolution
-- By reason: how long (hours, 4 dp) from creation to the first assignment, and how long (days, 4 dp) from creation to resolution.
SELECT e.exception_type AS reason, count(*) AS exceptions,
       count(*) FILTER (WHERE fa.first_at IS NOT NULL) AS with_an_assignment,
       round(avg(extract(epoch FROM (fa.first_at - e.created_at)) / 3600) FILTER (WHERE fa.first_at IS NOT NULL)::numeric, 4) AS mean_hours_to_first_assignment,
       count(*) FILTER (WHERE e.resolved_at IS NOT NULL) AS resolved,
       round(avg(extract(epoch FROM (e.resolved_at - e.created_at)) / 86400) FILTER (WHERE e.resolved_at IS NOT NULL)::numeric, 4) AS mean_days_to_resolution
FROM exceptions e LEFT JOIN LATERAL (SELECT min(a.assigned_at) AS first_at FROM exception_assignments a WHERE a.exception_id = e.exception_id) fa ON TRUE
GROUP BY e.exception_type ORDER BY e.exception_type COLLATE "C";

-- @@ owner_workload_at_cutoff
-- Open exceptions at the as-of by current owner (the latest assignment at or before the cutoff); 'unowned' when there is none.
WITH o AS (
    SELECT e.exception_id, (SELECT a.owner_id FROM exception_assignments a WHERE a.exception_id = e.exception_id AND a.assigned_at <= '2026-10-01T02:00:00Z'
                            ORDER BY a.assigned_at DESC, a.assignment_id DESC LIMIT 1) AS owner_id
    FROM exceptions e WHERE e.created_at <= '2026-10-01T02:00:00Z' AND (e.resolved_at IS NULL OR e.resolved_at > '2026-10-01T02:00:00Z')
)
SELECT coalesce(owner_id, 'unowned') AS owner, count(*) AS open_exceptions
FROM o GROUP BY coalesce(owner_id, 'unowned') ORDER BY count(*) DESC, coalesce(owner_id, 'unowned') COLLATE "C";
